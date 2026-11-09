/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { timeout } from '../../../../base/common/async.js';
import { CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IFemSolverService, L12EngineMethod } from '../../../../platform/saengine/common/femSolver.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ISecretStorageService } from '../../../../platform/secrets/common/secrets.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProject, ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { ExchangeFormat, isPlainNetworkUrl, officeBlocker, officeServerUrl } from '../common/automationModel.js';
import { bag, callBackend, callBackendWith, saveProjectParts } from './automationBackend.js';
import { GraphEditor } from './graphEditor.js';
import { GraphEditorInput } from './graphEditorInput.js';
import { StudiesEditor } from './studiesEditor.js';
import { StudiesEditorInput } from './studiesEditorInput.js';

const category = localize2('saengine.category', "SAEngine");

/** Setting: the office server may be used (off by default: nothing leaves the computer). */
export const OFFICE_ENABLED_SETTING = 'saengine.officeServer.enabled';
/** Setting: the office server's address, e.g. `https://analysis.office.local:8737`. */
export const OFFICE_URL_SETTING = 'saengine.officeServer.url';
/** The secret storage key of the office server's token. */
const OFFICE_TOKEN_KEY = 'saengine.officeServer.token';
/** How often a running office job is asked about [ms]. */
const OFFICE_POLL = 4000;

/** `saengine.export.exchange` `{projectRoot, format}`: the backend of the exchange exports. */
export const EXPORT_EXCHANGE_COMMAND = 'saengine.export.exchange';
/** `saengine.drawings.automate` `{actions, sheets?}`: drawing automation on the open project's sheets. */
export const DRAWINGS_AUTOMATE_COMMAND = 'saengine.drawings.automate';

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineOfficeServer',
	order: 102,
	title: localize('saengineOfficeServerTitle', "SAEngine Office Server"),
	type: 'object',
	properties: {
		[OFFICE_ENABLED_SETTING]: {
			type: 'boolean',
			default: false,
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.officeServer.enabled', "Allow sending a project to your office's analysis server (**SAEngine: Run on Office Server**). Off by default. When on, the project (without results or versions) goes only to the address below, never to any other service."),
		},
		[OFFICE_URL_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.officeServer.url', "The office server's address, e.g. `https://analysis.office.local:8737` (started with `saengine office-server`). Its token is kept in the system's secret storage: **SAEngine: Set Office Server Token**. Use `https` on a network: with `http` the token and the project travel unencrypted."),
		},
	},
});

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(GraphEditor, GraphEditor.ID, localize('saengineGraphEditor', "SAEngine Visual Program")),
	[new SyncDescriptor(GraphEditorInput)]
);
Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(StudiesEditor, StudiesEditor.ID, localize('saengineStudiesEditor', "SAEngine Design Studies")),
	[new SyncDescriptor(StudiesEditorInput)]
);

/** The services the actions use, taken while the accessor is valid (before any await). */
interface IServices {
	readonly notifications: INotificationService;
	readonly editors: IEditorService;
	readonly opener: IOpenerService;
	readonly progress: IProgressService;
	readonly quickInput: IQuickInputService;
	readonly textFiles: ITextFileService;
	readonly secrets: ISecretStorageService;
	readonly configuration: IConfigurationService;
	readonly project: ISaengineProject | undefined;
	call(method: L12EngineMethod, params: object): Promise<unknown>;
}

function services(accessor: ServicesAccessor): IServices {
	const instantiationService = accessor.get(IInstantiationService);
	const femSolverService = accessor.get(IFemSolverService);
	return {
		notifications: accessor.get(INotificationService),
		editors: accessor.get(IEditorService),
		opener: accessor.get(IOpenerService),
		progress: accessor.get(IProgressService),
		quickInput: accessor.get(IQuickInputService),
		textFiles: accessor.get(ITextFileService),
		secrets: accessor.get(ISecretStorageService),
		configuration: accessor.get(IConfigurationService),
		project: accessor.get(ISaengineProjectService).project,
		call: (method, params) => callBackend(instantiationService, femSolverService, method, params),
	};
}

function openProject(s: IServices): ISaengineProject | undefined {
	if (!s.project) {
		s.notifications.info(localize('automation.noProject', "Open a SAEngine project first."));
	}
	return s.project;
}

//#region Exchange exports

CommandsRegistry.registerCommand(EXPORT_EXCHANGE_COMMAND, (accessor, args: { readonly projectRoot: string; readonly format: ExchangeFormat; readonly outPath?: string }) =>
	callBackendWith(accessor, 'export/exchange', { projectRoot: args.projectRoot, format: args.format, ...(args.outPath ? { outPath: args.outPath } : {}) }));

const EXPORTS: readonly { readonly format: ExchangeFormat; readonly id: string; readonly title: ReturnType<typeof localize2> }[] = [
	{ format: 's2k', id: 'saengine.export.s2k', title: localize2('export.s2k', "Export Analysis Model as .s2k Text") },
	{ format: 'std', id: 'saengine.export.std', title: localize2('export.std', "Export Analysis Model as .std Commands") },
	{ format: 'saf', id: 'saengine.export.saf', title: localize2('export.saf', "Export Analysis Model as SAF (.xlsx)") },
	{ format: 'sdnf', id: 'saengine.export.sdnf', title: localize2('export.sdnf', "Export Steelwork as SDNF") },
	{ format: 'cis2', id: 'saengine.export.cis2', title: localize2('export.cis2', "Export Analysis Model as CIS/2 (LPM/6)") },
	{ format: 'webViewer', id: 'saengine.export.webViewer', title: localize2('export.webViewer', "Export Web Viewer for Reviewers") },
];

async function exportAs(s: IServices, format: ExchangeFormat): Promise<void> {
	const project = openProject(s);
	if (!project) {
		return;
	}
	const notificationService = s.notifications;
	const editorService = s.editors;
	const openerService = s.opener;
	await saveProjectParts(s.textFiles, project);
	const answer = bag(await s.progress.withProgress(
		{ location: ProgressLocation.Notification, title: localize('export.running', "Deriving the analysis model and writing the export...") },
		() => s.call('export/exchange', { projectRoot: project.root.fsPath, format }),
	));
	if (typeof answer.error === 'string' || typeof answer.path !== 'string') {
		notificationService.error(localize('export.failed', "The export failed: {0}", String(answer.error ?? localize('export.noAnswer', "no answer from the backend"))));
		return;
	}
	const path = answer.path;
	const readable = typeof answer.readablePath === 'string' ? answer.readablePath : undefined;
	const report = bag(answer.report);
	const left = (Array.isArray(report.skipped) ? report.skipped.length : 0) + (Array.isArray(report.approximated) ? report.approximated.length : 0);
	notificationService.prompt(Severity.Info,
		format === 'webViewer'
			? localize('export.webDone', "Wrote the web viewer to {0}. Reviewers open index.html in any browser.", path)
			: left
				? localize('export.doneWithNotes', "Wrote {0}. {1} kinds of things were left out or approximated: see the export report.", path, left)
				: localize('export.done', "Wrote {0}.", path),
		[
			...(readable ? [{ label: localize('export.openReport', "Open Export Report"), run: () => editorService.openEditor({ resource: URI.file(readable) }) }] : []),
			...(format === 'webViewer' ? [{ label: localize('export.openBrowser', "Open in Browser"), run: () => openerService.open(URI.file(path), { openExternal: true }) }] : []),
		]);
}

for (const entry of EXPORTS) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id: entry.id, title: entry.title, category, f1: true });
		}
		override run(accessor: ServicesAccessor): Promise<void> {
			return exportAs(services(accessor), entry.format);
		}
	});
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.export.detailingNote',
			title: localize2('export.detailingNote', "How to Send the Model to Steel Detailing Software"),
			category,
			f1: true,
		});
	}
	override run(accessor: ServicesAccessor): void {
		accessor.get(INotificationService).info(localize('export.detailingNoteText', "There is no proprietary link to detailing programs. Export IFC (the building model, with the steel members' profiles) and open it there; SDNF and CIS/2 are written too for programs that read them."));
	}
});

//#endregion

//#region Office server

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.officeServer.setToken', title: localize2('office.setToken', "Set Office Server Token..."), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const s = services(accessor);
		const token = await s.quickInput.input({
			password: true,
			prompt: localize('office.tokenPrompt', "The token your office server printed when it started (kept in the system's secret storage)."),
			placeHolder: localize('office.tokenPlaceholder', "Office server token"),
		});
		if (token && token.trim()) {
			await s.secrets.set(OFFICE_TOKEN_KEY, token.trim());
			s.notifications.info(localize('office.tokenSaved', "The office server token is saved."));
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.officeServer.clearToken', title: localize2('office.clearToken', "Forget Office Server Token"), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ISecretStorageService).delete(OFFICE_TOKEN_KEY);
	}
});

/** The office server's address and token, or undefined after saying what is missing. */
async function officeConnection(s: IServices): Promise<{ readonly server: string; readonly token: string } | undefined> {
	const configuration = s.configuration;
	const notificationService = s.notifications;
	const url = configuration.getValue<string>(OFFICE_URL_SETTING);
	const token = (await s.secrets.get(OFFICE_TOKEN_KEY)) || undefined;
	switch (officeBlocker(configuration.getValue<boolean>(OFFICE_ENABLED_SETTING) === true, url, !!token)) {
		case 'disabled':
			notificationService.info(localize('office.disabled', "Sending projects to an office server is off. Turn on the setting \"SAEngine Office Server: Enabled\" and enter its address."));
			return undefined;
		case 'noUrl':
			notificationService.info(localize('office.noUrl', "Enter the office server's address (http:// or https://) in the setting \"SAEngine Office Server: Url\"."));
			return undefined;
		case 'noToken':
			notificationService.info(localize('office.noToken', "Enter the office server's token first: SAEngine: Set Office Server Token."));
			return undefined;
	}
	return { server: officeServerUrl(url)!, token: token! };
}

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.officeServer.check', title: localize2('office.check', "Check Office Server"), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const s = services(accessor);
		const connection = await officeConnection(s);
		if (!connection) {
			return;
		}
		const answer = bag(await s.call('office/info', connection));
		const notificationService = s.notifications;
		if (answer.ok === false) {
			notificationService.error(String(answer.message));
		} else {
			notificationService.info(localize('office.ok', "The office server answers: SAEngine {0}, {1} job(s) running.", String(answer.version ?? '?'), String(answer.busy ?? 0)));
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.officeServer.run',
			title: localize2('office.run', "Run on Office Server"),
			metadata: { description: localize2('office.run.description', "Sends the saved project (no results, no versions) to the office server configured in the settings, runs the analysis and the design there and brings the results back.") },
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const s = services(accessor);
		const project = openProject(s);
		const connection = project && await officeConnection(s);
		if (!project || !connection) {
			return;
		}
		const notificationService = s.notifications;
		const quickInputService = s.quickInput;
		const progressService = s.progress;
		if (isPlainNetworkUrl(connection.server)) {
			const go = await quickInputService.pick<IQuickPickItem & { go: boolean }>([
				{ label: localize('office.sendAnyway', "Send Anyway"), go: true },
				{ label: localize('office.dontSend', "Don't Send"), go: false },
			], { placeHolder: localize('office.plainWarning', "{0} is not https: the token and the project travel unencrypted on the network.", connection.server) });
			if (!go?.go) {
				return;
			}
		}
		await saveProjectParts(s.textFiles, project);
		const started = bag(await s.call('office/submit', { projectRoot: project.root.fsPath, server: connection.server, token: connection.token }));
		if (started.ok === false || typeof started.id !== 'string') {
			notificationService.error(localize('office.submitFailed', "The project could not be sent: {0}", String(started.message ?? '')));
			return;
		}
		const id = started.id;
		const cancel = new CancellationTokenSource();
		const final = await progressService.withProgress(
			{ location: ProgressLocation.Notification, title: localize('office.title', "Office server"), cancellable: true },
			async progress => {
				for (; ;) {
					if (cancel.token.isCancellationRequested) {
						return bag(await s.call('office/cancel', { id }));
					}
					const status = bag(await s.call('office/status', { id }));
					const state = String(status.state ?? 'unknown');
					const log = Array.isArray(status.log) ? status.log : [];
					progress.report({ message: `${state}${log.length ? `: ${String(log[log.length - 1])}` : ''}` });
					if (['done', 'failed', 'cancelled', 'unknown'].includes(state)) {
						return status;
					}
					await timeout(OFFICE_POLL);
				}
			},
			() => cancel.cancel(),
		);
		cancel.dispose();
		const result = bag(final.result);
		if (final.state === 'done') {
			const kept = Array.isArray(result.kept) ? result.kept : [];
			const written = Array.isArray(result.written) ? result.written.length : 0;
			notificationService.notify({
				severity: kept.length ? Severity.Warning : Severity.Info,
				message: kept.length
					? localize('office.doneKept', "The office server finished: {0} files brought back; {1} were changed here meanwhile and kept as they are ({2}).", written, kept.length, kept.slice(0, 3).join(', '))
					: localize('office.done', "The office server finished: {0} files brought back into the project.", written),
			});
		} else if (final.state !== 'cancelled') {
			notificationService.error(localize('office.failed', "The office server job stopped: {0}", String(final.message || final.state)));
		}
	}
});

//#endregion

//#region Drawing automation

CommandsRegistry.registerCommand(DRAWINGS_AUTOMATE_COMMAND, async (accessor, args: { readonly actions: readonly string[]; readonly sheets?: readonly string[] }) => {
	const project = accessor.get(ISaengineProjectService).project;
	if (!project) {
		return { error: 'No project is open.' };
	}
	return callBackendWith(accessor, 'drawings/automate', { projectRoot: project.root.fsPath, actions: args.actions, ...(args.sheets?.length ? { sheets: args.sheets } : {}) });
});

const DRAWING_ACTIONS: readonly { readonly id: string; readonly action: string; readonly title: ReturnType<typeof localize2> }[] = [
	{ id: 'saengine.drawings.autoDimension', action: 'dimension', title: localize2('drawings.autoDimension', "Auto-Dimension Drawing Sheets") },
	{ id: 'saengine.drawings.autoTag', action: 'tag', title: localize2('drawings.autoTag', "Auto-Tag Drawing Sheets") },
	{ id: 'saengine.drawings.autoArrange', action: 'arrange', title: localize2('drawings.autoArrange', "Arrange Drawing Labels") },
	{ id: 'saengine.drawings.undoAutomation', action: 'undo', title: localize2('drawings.undoAutomation', "Undo Drawing Automation") },
];

for (const entry of DRAWING_ACTIONS) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id: entry.id, title: entry.title, category, f1: true });
		}
		override async run(accessor: ServicesAccessor): Promise<void> {
			const s = services(accessor);
			const project = openProject(s);
			if (!project) {
				return;
			}
			const notificationService = s.notifications;
			const answer = bag(await s.progress.withProgress(
				{ location: ProgressLocation.Notification, title: localize('drawings.automating', "Working on the drawing sheets...") },
				() => s.call('drawings/automate', { projectRoot: project.root.fsPath, actions: [entry.action] }),
			));
			if (typeof answer.error === 'string') {
				notificationService.info(answer.error);
				return;
			}
			const sheets = Array.isArray(answer.sheets) ? answer.sheets.map(bag) : [];
			const counts = sheets.map(s => bag(bag(s.results)[entry.action]));
			const total = counts.reduce((sum, c) => sum + Number(c.added ?? c.moved ?? c.removed ?? 0), 0);
			const failed = sheets.filter(s => typeof s.error === 'string').length;
			notificationService.info(localize('drawings.automated', "{0} sheet(s) done, {1} change(s){2}. Regenerating the drawings draws the sheets again without them.", sheets.length - failed, total, failed ? localize('drawings.automatedFailed', "; {0} sheet(s) could not be read", failed) : ''));
		}
	});
}

//#endregion

//#region Visual programs and design studies

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.graph.new', title: localize2('graph.new', "New Visual Program..."), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const s = services(accessor);
		const project = openProject(s);
		if (!project) {
			return;
		}
		const name = await s.quickInput.input({ prompt: localize('graph.namePrompt', "Name of the visual program"), value: localize('graph.defaultName', "Study") });
		if (!name) {
			return;
		}
		const answer = bag(await s.call('graph/create', { projectRoot: project.root.fsPath, name }));
		if (typeof answer.path !== 'string') {
			s.notifications.error(String(answer.error ?? localize('graph.notCreated', "The program could not be created.")));
			return;
		}
		await s.editors.openEditor(new GraphEditorInput(URI.file(answer.path)), { pinned: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.graph.open', title: localize2('graph.open', "Open Visual Program..."), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const s = services(accessor);
		const project = openProject(s);
		if (!project) {
			return;
		}
		const answer = bag(await s.call('graph/list', { projectRoot: project.root.fsPath }));
		const graphs = (Array.isArray(answer.graphs) ? answer.graphs : []).map(bag).filter(g => typeof g.path === 'string');
		if (!graphs.length) {
			s.notifications.info(localize('graph.none', "The project has no visual programs yet: SAEngine: New Visual Program."));
			return;
		}
		const picked = await s.quickInput.pick(graphs.map(g => ({ label: String(g.name), description: String(g.path), path: String(g.path) })), { placeHolder: localize('graph.pick', "Visual program to open") });
		if (picked) {
			await s.editors.openEditor(new GraphEditorInput(URI.file(picked.path)), { pinned: true });
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.studies.open', title: localize2('studies.open', "Open Design Studies"), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const s = services(accessor);
		const project = openProject(s);
		if (project) {
			await s.editors.openEditor(new StudiesEditorInput(project.root), { pinned: true });
		}
	}
});

//#endregion
