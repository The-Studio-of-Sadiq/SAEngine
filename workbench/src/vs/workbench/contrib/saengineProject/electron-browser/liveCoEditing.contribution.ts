/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Emitter } from '../../../../base/common/event.js';
import { StringSHA1 } from '../../../../base/common/hash.js';
import { Disposable, DisposableMap, DisposableStore, IDisposable, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { relativePath } from '../../../../base/common/resources.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { ConfigurationTarget, IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { coEditingRoom, ISaengineCoEditingService, relayUrlProblem } from '../../../../platform/saengine/common/coEditing.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ISaengineModelSelectionService } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { ITextFileEditorModel, ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { ICoEditedDocument, ICoEditingProvider, ICoEditingSession, ICoEditor, LIVE_START_COMMAND, registerCoEditingProvider, RELAY_URL_SETTING } from '../browser/liveCoEditing.js';
import { IProjectShareService } from '../browser/shareService.js';

/*
 * Live co-editing in the window: the Yjs engine (ISaengineCoEditingService, in the main process)
 * as the co-editing provider, and while live co-editing is on for a shared project, every part
 * file (JSON) open in the window joins its room. The part editors work on the file's text model,
 * so they show a colleague's edit as they show an undo: no editor needs to know about co-editing.
 */

const DISPLAY_NAME_SETTING = 'saengine.collaboration.displayName';
/** Per project: live co-editing on. */
const LIVE_STORAGE_KEY = 'saengine.collaboration.live';
const LiveCoEditingContext = new RawContextKey<boolean>('saengineLiveCoEditing', false);
const RelayHostedContext = new RawContextKey<boolean>('saengineCoEditingRelayHosted', false);

const START_COMMAND = LIVE_START_COMMAND;
const STOP_COMMAND = 'saengine.collaboration.stop';
const HOST_COMMAND = 'saengine.collaboration.hostRelay';
const STOP_HOSTING_COMMAND = 'saengine.collaboration.stopRelay';
/** Selection to the others: the floor plan's source name in the selection service is not ours. */
const SELECTION_SOURCE = 'coEditing';

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineCollaboration',
	properties: {
		[DISPLAY_NAME_SETTING]: {
			type: 'string',
			default: '',
			markdownDescription: localize('collaboration.displayName', "Your name as colleagues see it in live co-editing. Empty: this computer's user name."),
		},
	},
});

/** The Yjs engine as the co-editing provider of `liveCoEditing.ts`. */
class YjsCoEditingProvider implements ICoEditingProvider {

	readonly name = 'Yjs';

	constructor(private readonly service: ISaengineCoEditingService) { }

	async join(relayUrl: string, projectId: string, document: ICoEditedDocument, me: { readonly name: string }): Promise<ICoEditingSession> {
		const store = new DisposableStore();
		const joined = await this.service.join({ relayUrl, room: coEditingRoom(projectId, document.path), name: me.name, text: document.getText() });
		const session = joined.session;
		const onDidChangePeople = store.add(new Emitter<readonly ICoEditor[]>());
		let people: readonly ICoEditor[] = [];
		let applying = false;

		store.add(this.service.onDidChangeRemote(e => {
			if (e.session === session && e.text !== document.getText()) {
				applying = true;
				try {
					document.applyRemote(e.text);
				} finally {
					applying = false;
				}
			}
		}));
		store.add(this.service.onDidChangePeople(e => {
			if (e.session === session) {
				people = e.people.map(p => ({ id: String(p.id), name: p.name, selection: p.selection, color: p.color }));
				onDidChangePeople.fire(people);
			}
		}));
		// This engineer's edits, a moment after typing or a drag stops.
		const send = store.add(new RunOnceScheduler(() => void this.service.update(session, document.getText()), 150));
		store.add(document.onDidChangeLocally(() => {
			if (!applying) {
				send.schedule();
			}
		}));
		store.add(toDisposable(() => {
			send.flush();
			void this.service.leave(session);
		}));
		const result: ICoEditingSession = {
			get people() { return people; },
			onDidChangePeople: onDidChangePeople.event,
			setSelection: ids => void this.service.setSelection(session, ids),
			dispose: () => store.dispose(),
		};
		return result;
	}
}

/** A part file's text model as a co-edited document. */
function textModelDocument(model: ITextFileEditorModel, path: string): ICoEditedDocument {
	const textModel = model.textEditorModel!;
	return {
		path,
		getText: () => textModel.getValue(),
		// The text model's onDidChangeContent is a method: call it on the model.
		onDidChangeLocally: listener => textModel.onDidChangeContent(() => listener()),
		applyRemote: text => {
			textModel.pushStackElement();
			textModel.pushEditOperations([], [{ range: textModel.getFullModelRange(), text }], () => null);
			textModel.pushStackElement();
		},
	};
}

interface IPartSession {
	readonly path: string;
	readonly session: ICoEditingSession;
}

class LiveCoEditingContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.liveCoEditing';
	/** The window's instance, for the commands. */
	static instance: LiveCoEditingContribution | undefined;

	private readonly provider: YjsCoEditingProvider;
	private readonly live: IContextKey<boolean>;
	private readonly hosted: IContextKey<boolean>;
	/** Open part sessions by the part file's URI. */
	private readonly sessions = this._register(new DisposableMap<string, IDisposable>());
	private readonly parts = new Map<string, IPartSession>();
	private readonly modelListeners = this._register(new MutableDisposable<DisposableStore>());
	private readonly status = this._register(new MutableDisposable<IStatusbarEntryAccessor>());

	constructor(
		@ISaengineCoEditingService service: ISaengineCoEditingService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IProjectShareService private readonly shareService: IProjectShareService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IStorageService private readonly storageService: IStorageService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISaengineModelSelectionService selectionService: ISaengineModelSelectionService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		super();
		LiveCoEditingContribution.instance = this;
		this._register(toDisposable(() => LiveCoEditingContribution.instance = undefined));
		this.provider = new YjsCoEditingProvider(service);
		this._register(registerCoEditingProvider(this.provider));
		this.live = LiveCoEditingContext.bindTo(contextKeyService);
		this.hosted = RelayHostedContext.bindTo(contextKeyService);
		void service.relayInfo().then(info => this.hosted.set(!!info));

		this._register(projectService.onDidChangeProject(() => this.update()));
		this._register(shareService.onDidChange(() => this.update()));
		this._register(configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(RELAY_URL_SETTING) || e.affectsConfiguration(DISPLAY_NAME_SETTING)) {
				this.stopSessions();
				this.update();
			}
		}));
		this._register(selectionService.onDidChangeSelection(e => {
			if (e.source !== SELECTION_SOURCE) {
				const ids = !e.selection || e.selection.kind === 'gridLine' ? [] : [e.selection.id];
				for (const part of this.parts.values()) {
					part.session.setSelection(ids);
				}
			}
		}));
		this.update();
	}

	/** The shared project's key: the same for every engineer of the office copy. */
	private projectKey(): string | undefined {
		const location = this.shareService.status?.shared ? this.shareService.status.location : undefined;
		if (!location) {
			return undefined;
		}
		const sha = new StringSHA1();
		sha.update(location.trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase());
		return sha.digest().slice(0, 20);
	}

	isOn(): boolean {
		return this.storageService.getBoolean(LIVE_STORAGE_KEY, StorageScope.WORKSPACE, false);
	}

	setHosted(hosted: boolean): void {
		this.hosted.set(hosted);
	}

	async setOn(on: boolean): Promise<void> {
		this.storageService.store(LIVE_STORAGE_KEY, on, StorageScope.WORKSPACE, StorageTarget.MACHINE);
		if (!on) {
			this.stopSessions();
		}
		this.update();
	}

	private relayUrl(): string | undefined {
		const url = this.configurationService.getValue<string>(RELAY_URL_SETTING)?.trim();
		return url && !relayUrlProblem(url) ? url : undefined;
	}

	/** Joins the rooms of the part files open now and of those opened later, or leaves them all. */
	private update(): void {
		const project = this.projectService.project;
		const key = this.projectKey();
		const relay = this.relayUrl();
		const on = !!project && !!key && !!relay && this.isOn();
		this.live.set(on);
		if (!on) {
			this.stopSessions();
			this.modelListeners.clear();
			this.renderStatus();
			return;
		}
		if (!this.modelListeners.value) {
			const store = new DisposableStore();
			store.add(this.textFileService.files.onDidResolve(e => this.bind(e.model)));
			this.modelListeners.value = store;
		}
		for (const model of this.textFileService.files.models) {
			this.bind(model);
		}
		this.renderStatus();
	}

	private bind(model: ITextFileEditorModel): void {
		const project = this.projectService.project;
		const key = this.projectKey();
		const relay = this.relayUrl();
		if (!project || !key || !relay || !this.isOn() || !model.textEditorModel) {
			return;
		}
		const path = relativePath(project.root, model.resource);
		if (!path || !path.toLowerCase().endsWith('.json') || path.startsWith('.') || this.sessions.has(model.resource.toString())) {
			return;
		}
		const resource = model.resource.toString();
		const store = new DisposableStore();
		this.sessions.set(resource, store);
		store.add(model.onWillDispose(() => this.sessions.deleteAndDispose(resource)));
		store.add(toDisposable(() => {
			this.parts.delete(resource);
			this.renderStatus();
		}));
		const name = this.configurationService.getValue<string>(DISPLAY_NAME_SETTING) ?? '';
		this.provider.join(relay, key, textModelDocument(model, path), { name }).then(session => {
			if (store.isDisposed) {
				session.dispose();
				return;
			}
			store.add(session);
			this.parts.set(resource, { path, session });
			store.add(session.onDidChangePeople(() => this.renderStatus()));
			this.renderStatus();
		}, error => {
			this.sessions.deleteAndDispose(resource);
			this.notificationService.warn(localize('live.joinFailed', "Live co-editing could not join {0}: {1}", path, toErrorMessage(error)));
		});
	}

	private stopSessions(): void {
		this.sessions.clearAndDisposeAll();
		this.parts.clear();
		this.renderStatus();
	}

	/** Who else is in the parts open here: one status bar entry while live co-editing is on. */
	private renderStatus(): void {
		if (!this.live.get()) {
			this.status.clear();
			return;
		}
		const byName = new Map<string, string[]>();
		for (const part of this.parts.values()) {
			for (const person of part.session.people) {
				const parts = byName.get(person.name) ?? [];
				parts.push(part.path + (person.selection.length ? ` (${person.selection.join(', ')})` : ''));
				byName.set(person.name, parts);
			}
		}
		const count = byName.size;
		const text = count
			? `$(live-share) ${localize('live.status.people', "{0} co-editing", count)}`
			: `$(live-share) ${localize('live.status.alone', "Live")}`;
		const tooltip = count
			? [localize('live.status.tooltip', "Live co-editing: these colleagues are in the parts you have open."), ...[...byName].map(([name, parts]) => `${name}: ${parts.join('; ')}`)].join('\n')
			: localize('live.status.aloneTooltip', "Live co-editing is on: your edits reach colleagues in the same part as you make them. No one else is in the parts you have open.");
		const entry = { name: localize('live.status.name', "Live Co-Editing"), text, ariaLabel: tooltip, tooltip, command: STOP_COMMAND };
		if (this.status.value) {
			this.status.value.update(entry);
		} else {
			this.status.value = this.statusbarService.addEntry(entry, 'saengine.liveCoEditing', StatusbarAlignment.LEFT, 50);
		}
	}
}

registerWorkbenchContribution2(LiveCoEditingContribution.ID, LiveCoEditingContribution, WorkbenchPhase.AfterRestored);

function contribution(): LiveCoEditingContribution | undefined {
	return LiveCoEditingContribution.instance;
}

/** Hosts the relay here and points this computer at it; the colleagues' address goes to the clipboard. */
async function host(service: ISaengineCoEditingService, configurationService: IConfigurationService, notificationService: INotificationService, clipboardService: IClipboardService): Promise<boolean> {
	try {
		const info = await service.hostRelay();
		await configurationService.updateValue(RELAY_URL_SETTING, info.localUrl, ConfigurationTarget.USER);
		contribution()?.setHosted(true);
		const address = info.urls[0];
		if (address) {
			await clipboardService.writeText(address);
		}
		notificationService.info(address
			? localize('live.hosted', "This computer hosts the co-editing relay. Colleagues set their relay address to {0} (copied to the clipboard). Windows may ask to allow SAEngine on private networks: allow it. The relay runs while SAEngine is open.", address)
			: localize('live.hostedNoNetwork', "This computer hosts the co-editing relay, but it is on no network that colleagues can reach."));
		return true;
	} catch (error) {
		notificationService.error(localize('live.hostFailed', "The co-editing relay could not start: {0}. Another program may be using the port.", toErrorMessage(error)));
		return false;
	}
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: START_COMMAND,
			title: localize2('live.start', "Start Live Co-Editing"),
			category: localize2('live.category', "Collaboration"),
			f1: true,
			precondition: LiveCoEditingContext.negate(),
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const shareService = accessor.get(IProjectShareService);
		const configurationService = accessor.get(IConfigurationService);
		const notificationService = accessor.get(INotificationService);
		const projectService = accessor.get(ISaengineProjectService);
		const service = accessor.get(ISaengineCoEditingService);
		const clipboardService = accessor.get(IClipboardService);
		const commandService = accessor.get(ICommandService);
		if (!projectService.project) {
			notificationService.info(localize('live.noProject', "Open a project first."));
			return;
		}
		if (!shareService.status) {
			// Not read yet (the engine was starting when the project opened): read it now.
			await shareService.refresh(false);
		}
		if (!shareService.status?.shared) {
			notificationService.info(localize('live.notShared', "Share the project first (Share Project...): live co-editing joins the engineers of a shared project."));
			return;
		}
		const url = configurationService.getValue<string>(RELAY_URL_SETTING)?.trim() ?? '';
		if (!url || relayUrlProblem(url)) {
			notificationService.prompt(Severity.Info,
				localize('live.needRelay', "Live co-editing needs the office's co-editing relay. Host it on this computer for the office network, or enter the address a colleague or the office server gives you."),
				[
					{
						label: localize('live.hostHere', "Host on This Computer"), run: async () => {
							if (await host(service, configurationService, notificationService, clipboardService)) {
								await contribution()?.setOn(true);
							}
						}
					},
					{ label: localize('live.enterAddress', "Enter Relay Address..."), run: () => commandService.executeCommand('workbench.action.openSettings', RELAY_URL_SETTING) },
				]);
			return;
		}
		await contribution()?.setOn(true);
		notificationService.info(localize('live.started', "Live co-editing is on: the parts you open are shared, as you edit, with the colleagues who have them open. Save as usual; Sync with Office Copy keeps the versions."));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: STOP_COMMAND,
			title: localize2('live.stop', "Stop Live Co-Editing"),
			category: localize2('live.category', "Collaboration"),
			f1: true,
			precondition: LiveCoEditingContext,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const dialogService = accessor.get(IDialogService);
		const { confirmed } = await dialogService.confirm({
			message: localize('live.stopConfirm', "Stop live co-editing?"),
			detail: localize('live.stopDetail', "Your edits stay in your parts; colleagues stop seeing them as you make them. Save and Sync with Office Copy to share them."),
			primaryButton: localize({ key: 'live.stopButton', comment: ['&& denotes a mnemonic'] }, "&&Stop"),
		});
		if (confirmed) {
			await contribution()?.setOn(false);
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: HOST_COMMAND,
			title: localize2('live.host', "Host Co-Editing Relay on This Computer"),
			category: localize2('live.category', "Collaboration"),
			f1: true,
			precondition: RelayHostedContext.negate(),
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await host(accessor.get(ISaengineCoEditingService), accessor.get(IConfigurationService), accessor.get(INotificationService), accessor.get(IClipboardService));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: STOP_HOSTING_COMMAND,
			title: localize2('live.stopHost', "Stop Hosting the Co-Editing Relay"),
			category: localize2('live.category', "Collaboration"),
			f1: true,
			precondition: RelayHostedContext,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const service = accessor.get(ISaengineCoEditingService);
		const dialogService = accessor.get(IDialogService);
		const info = await service.relayInfo();
		if (info && info.connections > 1) {
			const { confirmed } = await dialogService.confirm({
				message: localize('live.stopHostConfirm', "Stop hosting the co-editing relay?"),
				detail: localize('live.stopHostDetail', "{0} connections use it now; those colleagues stop co-editing until a relay runs again. Their edits stay in their parts.", info.connections),
				primaryButton: localize({ key: 'live.stopHostButton', comment: ['&& denotes a mnemonic'] }, "&&Stop Hosting"),
			});
			if (!confirmed) {
				return;
			}
		}
		await service.stopRelay();
		contribution()?.setHosted(false);
	}
});
