/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { ILocalizedString } from '../../../../platform/action/common/action.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IHostService } from '../../../services/host/browser/host.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { coEditingBlocker, coEditingProvider, RELAY_URL_SETTING } from './liveCoEditing.js';
import { PROJECT_MENU, ProjectOpenContext } from './projectMenu.js';
import { isServerLocation, IShareConflict, ISyncResult, Resolution, SHARE_JOIN_COMMAND, shareSummary, syncMessage } from './shareModel.js';
import { IProjectShareService } from './shareService.js';

/*
 * Shared projects in the workbench: Share Project, Sync with Office Copy, Lock and Unlock a
 * part, Open Shared Project and Live Co-Editing, in the Project menu and the command palette.
 * The Versions editor shows the shared state (./versionsEditor.ts).
 */

const category = localize2('saengine.category', "SAEngine");

/** `saengine.component.collaboration` (contrib/saengineUpdate): the setup's Collaboration component. */
const COLLABORATION_COMPONENT_KEY = 'saengine.component.collaboration';
const COMPONENTS_ADD_COMMAND = 'saengine.components.add';

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineCollaboration',
	title: localize('collaboration.settings', "SAEngine Collaboration"),
	type: 'object',
	properties: {
		[RELAY_URL_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('collaboration.relayUrl', "The office's own co-editing relay for live co-editing (`ws://` or `wss://`, on the office network). Empty: live co-editing is off and nothing is sent anywhere. SAEngine uses no third-party cloud."),
		},
	},
});

interface IResolutionPick extends IQuickPickItem {
	readonly resolution: Resolution;
}

/** The engineer's choices behind the share commands. */
class ShareFlows {

	constructor(
		@IProjectShareService private readonly shareService: IProjectShareService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IDialogService private readonly dialogService: IDialogService,
		@INotificationService private readonly notificationService: INotificationService,
		@ICommandService private readonly commandService: ICommandService,
		@IHostService private readonly hostService: IHostService,
		@IContextKeyService private readonly contextKeyService: IContextKeyService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
	) { }

	private ready(): boolean {
		if (!this.projectService.project) {
			this.notificationService.info(localize('share.noProject', "Open a SAEngine project first."));
			return false;
		}
		if (!this.shareService.available) {
			this.notificationService.info(localize('share.unavailable', "Sharing projects is not available in this build of SAEngine."));
			return false;
		}
		return true;
	}

	/** Where to share: a shared folder (chosen) or a git server address (typed). */
	private async askLocation(): Promise<string | undefined> {
		const folder = { label: `$(${Codicon.folder.id}) ${localize('share.folderChoice', "Shared Folder...")}`, detail: localize('share.folderDetail', "A folder on the office file server (a network share or a mapped drive). Sync, part locks and presence."), kind: 'folder' as const };
		const server = { label: `$(${Codicon.server.id}) ${localize('share.serverChoice', "Git Server Address...")}`, detail: localize('share.serverDetail', "The office's own git server (https:// or ssh://). Sync only: locks and presence need a shared folder."), kind: 'server' as const };
		const picked = await this.quickInputService.pick([folder, server], { title: localize('share.whereTitle', "Share Project"), placeHolder: localize('share.wherePlaceholder', "Where is the office copy kept?") });
		if (!picked) {
			return undefined;
		}
		if (picked.kind === 'folder') {
			const chosen = await this.fileDialogService.showOpenDialog({
				title: localize('share.folderTitle', "Choose an Empty Shared Folder, or This Project's Shared Folder"),
				canSelectFiles: false,
				canSelectFolders: true,
				canSelectMany: false,
				availableFileSystems: ['file'],
			});
			return chosen?.[0]?.fsPath;
		}
		return this.quickInputService.input({
			title: localize('share.serverTitle', "Git Server Address"),
			placeHolder: 'https://git.office.local/projects/tower-a.git',
			validateInput: async value => value.trim() && !isServerLocation(value) ? localize('share.serverInvalid', "Enter an https://, ssh:// or git@host: address.") : undefined,
		});
	}

	async share(): Promise<void> {
		if (!this.ready()) {
			return;
		}
		const location = await this.askLocation();
		if (!location?.trim()) {
			return;
		}
		try {
			const result = await this.shareService.connect(location);
			await this.reportSync(result);
		} catch (error) {
			this.notificationService.error(localize('share.connectFailed', "The project could not be shared: {0}", toErrorMessage(error)));
		}
	}

	async sync(): Promise<void> {
		if (!this.ready()) {
			return;
		}
		try {
			await this.reportSync(await this.shareService.sync());
		} catch (error) {
			this.notificationService.error(localize('share.syncFailed', "Sync with the office copy failed: {0}", toErrorMessage(error)));
		}
	}

	/** A sync's outcome; conflicts are settled part by part and the sync runs again. */
	private async reportSync(result: ISyncResult): Promise<void> {
		if (result.state !== 'conflicts') {
			this.notificationService.info(syncMessage(result));
			return;
		}
		const resolutions: { [part: string]: Resolution } = {};
		for (const conflict of result.conflicts) {
			const choice = await this.askResolution(conflict);
			if (!choice) {
				this.notificationService.info(localize('share.conflictsLeft', "Nothing was merged. Your versions are kept here; sync again to choose."));
				return;
			}
			resolutions[conflict.part] = choice;
		}
		try {
			const again = await this.shareService.sync(resolutions);
			this.notificationService.info(syncMessage(again));
		} catch (error) {
			this.notificationService.error(localize('share.syncFailed', "Sync with the office copy failed: {0}", toErrorMessage(error)));
		}
	}

	private async askResolution(conflict: IShareConflict): Promise<Resolution | undefined> {
		const items: IResolutionPick[] = [
			{ label: localize('share.keepMine', "Keep Mine"), detail: localize('share.keepMineDetail', "This copy's {0} replaces the office copy's.", conflict.title), resolution: 'mine' },
			{ label: localize('share.takeTheirs', "Take Theirs"), detail: localize('share.takeTheirsDetail', "The office copy's {0} replaces yours (yours stays in Versions, \"Before syncing\").", conflict.title), resolution: 'theirs' },
		];
		const picked = await this.quickInputService.pick(items, {
			title: localize('share.conflictTitle', "{0} Changed on Both Sides", conflict.title),
			placeHolder: conflict.paths.join(', '),
		});
		return picked?.resolution;
	}

	private async pickPart(placeHolder: string): Promise<string | undefined> {
		const status = this.shareService.status;
		const items = this.projectService.parts.map(part => {
			const lock = status?.locks.find(l => l.part === part.id);
			return {
				id: part.id,
				label: part.folder,
				description: lock ? (lock.mine ? localize('share.lockedByMe', "locked by you") : localize('share.lockedBy', "locked by {0}", lock.user)) : undefined,
			};
		});
		return (await this.quickInputService.pick(items, { placeHolder }))?.id;
	}

	async lock(part?: string): Promise<void> {
		if (!this.ready()) {
			return;
		}
		if (this.shareService.status?.kind !== 'folder') {
			this.notificationService.info(localize('share.locksNeedFolder', "Part locks need a project shared through a shared folder."));
			return;
		}
		part ??= await this.pickPart(localize('share.lockPlaceholder', "Which part are you going to edit?"));
		if (!part) {
			return;
		}
		try {
			await this.shareService.lock(part);
		} catch (error) {
			this.notificationService.warn(toErrorMessage(error));
		}
	}

	async unlock(part?: string): Promise<void> {
		if (!this.ready()) {
			return;
		}
		part ??= await this.pickPart(localize('share.unlockPlaceholder', "Which part's lock to release?"));
		if (!part) {
			return;
		}
		const lock = this.shareService.status?.locks.find(l => l.part === part);
		let force = false;
		if (lock && !lock.mine) {
			const { confirmed } = await this.dialogService.confirm({
				type: Severity.Warning,
				message: localize('share.breakLock', "Break {0}'s lock on {1}?", lock.user, lock.title),
				detail: localize('share.breakLockDetail', "Only if they are not working on it (a computer that crashed or left the office). Their unsent changes to it may then conflict at their next sync."),
				primaryButton: localize({ key: 'share.breakLockButton', comment: ['&& denotes a mnemonic'] }, "&&Break Lock"),
			});
			if (!confirmed) {
				return;
			}
			force = true;
		}
		try {
			await this.shareService.unlock(part, force);
		} catch (error) {
			this.notificationService.warn(toErrorMessage(error));
		}
	}

	async stop(): Promise<void> {
		if (!this.ready() || !this.shareService.status?.shared) {
			return;
		}
		const { confirmed } = await this.dialogService.confirm({
			message: localize('share.stopTitle', "Stop syncing this copy with the office copy?"),
			detail: localize('share.stopDetail', "The office copy and this copy's versions both stay; you can share again later."),
			primaryButton: localize({ key: 'share.stopButton', comment: ['&& denotes a mnemonic'] }, "&&Stop Sharing"),
		});
		if (confirmed) {
			await this.shareService.disconnect().catch(error => this.notificationService.error(toErrorMessage(error)));
		}
	}

	/** Copies a shared project to a new local folder and opens it. */
	async join(): Promise<void> {
		if (!CommandsRegistry.getCommand(SHARE_JOIN_COMMAND)) {
			this.notificationService.info(localize('share.unavailable', "Sharing projects is not available in this build of SAEngine."));
			return;
		}
		const location = await this.askLocation();
		if (!location?.trim()) {
			return;
		}
		const target = await this.fileDialogService.showOpenDialog({
			title: localize('share.joinTarget', "Choose an Empty Folder for Your Copy"),
			canSelectFiles: false,
			canSelectFolders: true,
			canSelectMany: false,
			availableFileSystems: ['file'],
		});
		if (!target?.[0]) {
			return;
		}
		try {
			const answer = await this.commandService.executeCommand<{ projectRoot?: string }>(SHARE_JOIN_COMMAND, { location, target: target[0].fsPath });
			if (answer?.projectRoot) {
				await this.hostService.openWindow([{ folderUri: URI.file(answer.projectRoot) }], { forceReuseWindow: true });
			}
		} catch (error) {
			this.notificationService.error(localize('share.joinFailed', "The shared project could not be copied: {0}", toErrorMessage(error)));
		}
	}

	/** Live co-editing of a part: says what it still needs, or (with an engine) joins the room. */
	async live(): Promise<void> {
		if (!this.ready()) {
			return;
		}
		const state = this.contextKeyService.getContextKeyValue<string>(COLLABORATION_COMPONENT_KEY);
		const blocker = coEditingBlocker({
			componentUsable: state === 'installed' || state === 'elsewhere' || state === undefined /* sources build */,
			provider: !!coEditingProvider(),
			relayUrl: this.configurationService.getValue<string>(RELAY_URL_SETTING),
			shared: !!this.shareService.status?.shared,
		});
		switch (blocker) {
			case 'component':
				this.notificationService.prompt(Severity.Info, localize('live.component', "Live co-editing is part of the Collaboration component of the SAEngine setup, which is not installed."),
					CommandsRegistry.getCommand(COMPONENTS_ADD_COMMAND) ? [{ label: localize('live.addComponent', "Add Component..."), run: () => this.commandService.executeCommand(COMPONENTS_ADD_COMMAND, 'collaboration') }] : []);
				return;
			case 'engine':
				this.notificationService.info(localize('live.engine', "Live co-editing (several engineers in one part at once) is not in this build yet: its co-editing engine is still to be added. Until then, share the project, lock the part you edit and sync; the Versions view shows who else has the project open."));
				return;
			case 'notShared':
				this.notificationService.info(localize('live.notShared', "Share the project first (Share Project...): live co-editing joins the engineers of a shared project."));
				return;
			case 'relay':
				this.notificationService.info(localize('live.relay', "Set the office's co-editing relay ({0}) to start live co-editing. SAEngine uses no outside service for it.", RELAY_URL_SETTING));
				return;
		}
		// With an engine registered, the part editors join their rooms when they open (the engine
		// registers that behaviour with the provider).
		this.notificationService.info(localize('live.on', "Live co-editing is on for this project; {0}", shareSummary(this.shareService.status!)));
	}
}

function flows(accessor: ServicesAccessor): ShareFlows {
	return accessor.get(IInstantiationService).createInstance(ShareFlows);
}

const actions: { id: string; title: ILocalizedString; order: number; run: (f: ShareFlows, arg?: unknown) => Promise<void>; projectOnly: boolean }[] = [
	{ id: 'saengine.share.shareProject', title: localize2('share.shareProject', "Share Project..."), order: 4, run: f => f.share(), projectOnly: true },
	{ id: 'saengine.share.syncNow', title: localize2('share.syncNow', "Sync with Office Copy"), order: 5, run: f => f.sync(), projectOnly: true },
	{ id: 'saengine.share.lockPart', title: localize2('share.lockPart', "Lock Part for Editing..."), order: 6, run: (f, part) => f.lock(typeof part === 'string' ? part : undefined), projectOnly: true },
	{ id: 'saengine.share.unlockPart', title: localize2('share.unlockPart', "Release Part Lock..."), order: 7, run: (f, part) => f.unlock(typeof part === 'string' ? part : undefined), projectOnly: true },
	{ id: 'saengine.share.liveCoEditing', title: localize2('share.liveCoEditing', "Live Co-Editing..."), order: 8, run: f => f.live(), projectOnly: true },
	{ id: 'saengine.share.stopSharing', title: localize2('share.stopSharing', "Stop Sharing..."), order: 9, run: f => f.stop(), projectOnly: true },
	{ id: 'saengine.share.openShared', title: localize2('share.openShared', "Open Shared Project..."), order: 10, run: f => f.join(), projectOnly: false },
];

for (const action of actions) {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: action.id,
				title: action.title,
				category,
				f1: true,
				precondition: action.projectOnly ? ProjectOpenContext : undefined,
				menu: { id: PROJECT_MENU, group: '3_share', order: action.order, when: action.projectOnly ? ProjectOpenContext : undefined },
			});
		}

		override run(accessor: ServicesAccessor, arg?: unknown): Promise<void> {
			return action.run(flows(accessor), arg);
		}
	});
}

/** Starts the share service with the workbench, so presence is kept while a shared project is open. */
class ProjectShareStartup extends Disposable implements IWorkbenchContribution {
	static readonly ID = 'workbench.contrib.saengineProjectShare';

	constructor(@IProjectShareService shareService: IProjectShareService) {
		super();
		void shareService.refresh(false);
	}
}

registerWorkbenchContribution2(ProjectShareStartup.ID, ProjectShareStartup, WorkbenchPhase.Eventually);
