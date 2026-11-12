/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ConfigurationTarget, IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { CREATE_DIAGNOSTICS_COMMAND, DIAGNOSTICS_SETTING, FeedbackKind, REPORT_BUG_COMMAND, SEND_FEEDBACK_COMMAND } from '../common/feedback.js';
import { ISaengineDiagnosticsService, SaengineDiagnosticsService } from './diagnosticsService.js';
import { FeedbackEditor, FeedbackEditorInput } from './feedbackEditor.js';

/*
 * U2: Help > Report a Bug / Send Feedback, and the opt-in diagnostics for the developers. Off by
 * default; SAEngine asks once, after the first project is open or after a crash, never at the
 * first launch. With no developers' endpoint yet the diagnostics are a local, anonymised bundle
 * the engineer reviews and sends with the feedback form. VS Code's own telemetry stays off.
 */

const category = localize2('saengine.category', "SAEngine");

registerSingleton(ISaengineDiagnosticsService, SaengineDiagnosticsService, InstantiationType.Eager);

const configurationRegistry = Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration);
configurationRegistry.registerConfiguration({
	id: 'saengineDiagnostics',
	order: 103,
	title: localize('diagnosticsConfigurationTitle', "SAEngine Diagnostics"),
	type: 'object',
	properties: {
		[DIAGNOSTICS_SETTING]: {
			type: 'boolean',
			default: false,
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('saengine.diagnostics.share', "Help the SAEngine developers with an anonymised diagnostics bundle: SAEngine's version, the operating system, the code pack in use and recent error messages, with names, folders and e-mail addresses removed; never project files or values. Nothing is sent automatically: the bundle is attached to **Help › Report a Bug** (where you see it in full before sending), and after a crash SAEngine offers to report it. Off by default."),
		},
	},
});

// VS Code's own usage and crash telemetry stays off: SAEngine sends nothing of its own accord.
configurationRegistry.registerDefaultConfigurations([{ overrides: { 'telemetry.telemetryLevel': 'off' } }]);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(FeedbackEditor, FeedbackEditor.ID, localize('saengineFeedbackEditor', "SAEngine Feedback")),
	[new SyncDescriptor(FeedbackEditorInput)]
);

async function openForm(accessor: ServicesAccessor, kind: FeedbackKind): Promise<void> {
	const diagnostics = accessor.get(ISaengineDiagnosticsService);
	const editorService = accessor.get(IEditorService);
	const input = FeedbackEditorInput.instance(kind);
	// The window as the engineer saw it, before the form covers it (attached only when ticked).
	input.screenshot = await diagnostics.screenshot().catch(() => undefined);
	await editorService.openEditor(input, { pinned: true });
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: REPORT_BUG_COMMAND,
			title: localize2('saengine.feedback.reportBug', "Report a Bug..."),
			category,
			f1: true,
			menu: { id: MenuId.MenubarHelpMenu, group: '3_feedback', order: 0 },
		});
	}
	override run(accessor: ServicesAccessor): Promise<void> {
		return openForm(accessor, 'bug');
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SEND_FEEDBACK_COMMAND,
			title: localize2('saengine.feedback.send', "Send Feedback..."),
			category,
			f1: true,
			menu: { id: MenuId.MenubarHelpMenu, group: '3_feedback', order: 1 },
		});
	}
	override run(accessor: ServicesAccessor): Promise<void> {
		return openForm(accessor, 'feedback');
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CREATE_DIAGNOSTICS_COMMAND,
			title: localize2('saengine.diagnostics.create', "Create Diagnostics Bundle"),
			metadata: { description: localize2('saengine.diagnostics.create.description', "Writes the anonymised diagnostics bundle to a file on this computer and opens it, so you can see exactly what a bug report would attach. Nothing is sent.") },
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const diagnostics = accessor.get(ISaengineDiagnosticsService);
		const editorService = accessor.get(IEditorService);
		const file = await diagnostics.writeBundle();
		await editorService.openEditor({ resource: file, options: { pinned: true } });
	}
});

/** The one-time opt-in prompt has been shown (whatever the answer). */
const PROMPTED_KEY = 'saengine.diagnostics.prompted';
/** Seconds after the first project opens before asking (not in the middle of creating it). */
const PROMPT_DELAY_MS = 20_000;

/**
 * Asks once whether to help with diagnostics: after the first project is open, or after a
 * crash; never at the first launch. With diagnostics on, a crash offers a bug report.
 */
class DiagnosticsPromptContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.diagnosticsPrompt';

	private timer: ReturnType<typeof setTimeout> | undefined;

	constructor(
		@ISaengineDiagnosticsService private readonly diagnostics: ISaengineDiagnosticsService,
		@IStorageService private readonly storageService: IStorageService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super();
		// The crash check reads the sessions recorded at start: give it a moment.
		this.timer = setTimeout(() => this.start(), 3000);
		this._register({ dispose: () => this.timer && clearTimeout(this.timer) });
	}

	private get prompted(): boolean {
		return this.storageService.getBoolean(PROMPTED_KEY, StorageScope.APPLICATION, false);
	}

	private start(): void {
		const enabled = this.configurationService.getValue<boolean>(DIAGNOSTICS_SETTING) === true;
		if (this.diagnostics.lastSessionEndedUnexpectedly) {
			if (enabled) {
				this.offerCrashReport();
			} else if (!this.prompted) {
				this.ask(true);
			}
			return;
		}
		if (this.prompted) {
			return;
		}
		const later = () => {
			this.timer = setTimeout(() => {
				if (!this.prompted) {
					this.ask(false);
				}
			}, PROMPT_DELAY_MS);
		};
		if (this.projectService.project) {
			later();
		} else {
			const listener = this._register(this.projectService.onDidChangeProject(project => {
				if (project) {
					listener.dispose();
					later();
				}
			}));
		}
	}

	private ask(afterCrash: boolean): void {
		this.storageService.store(PROMPTED_KEY, true, StorageScope.APPLICATION, StorageTarget.USER);
		const message = (afterCrash ? localize('diagnostics.askCrash', "SAEngine closed unexpectedly last time. ") : '')
			+ localize('diagnostics.ask', "Help improve SAEngine? When you report a problem, SAEngine can attach an anonymised diagnostics bundle: its version, your operating system, the code pack in use and recent error messages, with names, folders and e-mail addresses removed. Never your project files or values, and nothing is sent automatically: you see it and send it yourself. Off unless you turn it on.");
		this.notificationService.prompt(Severity.Info, message, [
			{ label: localize('diagnostics.turnOn', "Turn On"), run: () => this.configurationService.updateValue(DIAGNOSTICS_SETTING, true, ConfigurationTarget.USER) },
			{ label: localize('diagnostics.show', "Show What Is Included"), run: () => this.showBundle() },
			{ label: localize('diagnostics.noThanks', "No Thanks"), run: () => undefined },
		], { sticky: true });
	}

	private offerCrashReport(): void {
		this.notificationService.prompt(Severity.Info, localize('diagnostics.crash', "SAEngine closed unexpectedly last time. Report it to the developers? You see the whole report, with its anonymised diagnostics, before anything is sent."), [
			{ label: localize('diagnostics.report', "Report a Bug"), run: () => this.editorService.openEditor(FeedbackEditorInput.instance('bug'), { pinned: true }) },
			{ label: localize('diagnostics.notNow', "Not Now"), run: () => undefined },
		]);
	}

	private async showBundle(): Promise<void> {
		const file = await this.diagnostics.writeBundle();
		await this.editorService.openEditor({ resource: file, options: { pinned: true } });
	}
}

registerWorkbenchContribution2(DiagnosticsPromptContribution.ID, DiagnosticsPromptContribution, WorkbenchPhase.Eventually);
