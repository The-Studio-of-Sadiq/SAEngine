/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineShell.css';
import { $, append } from '../../../../base/browser/dom.js';
import { BaseActionViewItem, IBaseActionViewItemOptions } from '../../../../base/browser/ui/actionbar/actionViewItems.js';
import { IAction } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { FileAccess } from '../../../../base/common/network.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { KeybindingsRegistry, KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { OPEN_MANUAL_COMMAND } from './editorFrame.js';
import { localize, localize2 } from '../../../../nls.js';
import { IActionViewItemService } from '../../../../platform/actions/browser/actionViewItemService.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ConfigurationTarget, IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationDefaults, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ContextKeyExpr, IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { isAccountsActionVisible, setAccountsActionVisible } from '../../../browser/parts/globalCompositeBar.js';
import { ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ActiveViewletContext } from '../../../common/contextkeys.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewsRegistry } from '../../../common/views.js';
import { ILifecycleService, LifecyclePhase } from '../../../services/lifecycle/common/lifecycle.js';
import { PROJECT_PARTS, STRUCTURE_PART } from '../../../services/saengineProject/common/saengineProject.js';
import { IStatusbarService } from '../../../services/statusbar/browser/statusbar.js';
import { applyDeveloperItems, ConfigurationDefaultsSwitch, gateMenuItems, gateSubmenus, parseDeveloperItemsSnapshot, partEditorLabels, ViewsGate } from './saengineShell.js';

/*
 * The SAEngine window: an engineering app first. The code-editor half of Code-OSS (source control,
 * debugging, extensions, terminal, outline, timeline, editor status) stays installed and comes back
 * with the `saengine.developerMode` setting; without it the window shows only what an engineer uses.
 */

export const DEVELOPER_MODE_SETTING = 'saengine.developerMode';
export const DeveloperModeContext = new RawContextKey<boolean>('saengineDeveloperMode', false, localize('saengineDeveloperMode', "Whether SAEngine shows its code-editor features (developer mode)"));

const RUN_ALL_COMMAND = 'saengine.runAll';
const ProjectOpenContext = ContextKeyExpr.has('saengineProjectOpen');

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineShell',
	title: localize('saengine.configurationTitle', "SAEngine"),
	type: 'object',
	properties: {
		[DEVELOPER_MODE_SETTING]: {
			type: 'boolean',
			default: false,
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('saengine.developerMode', "Shows the code-editor features of the workbench: source control, run and debug, extensions, testing, the terminal, the outline and timeline, breadcrumbs and the text editor status. Nothing is removed while this is off; it is only out of sight."),
		},
	},
});

//#region Configuration defaults

/** Window chrome of the engineering app, in both modes. */
const SHELL_DEFAULTS: IConfigurationDefaults = {
	overrides: {
		// One ≡ button in the title bar instead of a menu bar.
		'window.menuBarVisibility': 'compact',
		'window.commandCenter': true,
		// The command center stays a search field ("Search or run a command"); the chat toggle sits beside it.
		'chat.agentsControl.enabled': 'badge',
		// The view switcher sits on top of the side bar, so the title bar hosts the ≡ menu.
		'workbench.activityBar.location': 'top',
		'workbench.layoutControl.enabled': false,
		// The chat stays one click away but starts closed.
		'workbench.secondarySideBar.defaultVisibility': 'hidden',
		// SAEngine projects are the user's own engineering data: no Restricted Mode.
		'security.workspace.trust.enabled': false,
		'workbench.welcomePage.walkthroughs.openOnInstall': false,
		// The part tabs shrink to fit at 1366 px instead of running off the strip (G14).
		'workbench.editor.tabSizing': 'shrink',
	},
	source: { id: 'saengine.shell', displayName: 'SAEngine' },
};

/** Code-editor presentation that developer mode brings back. */
const SIMPLE_DEFAULTS: IConfigurationDefaults = {
	overrides: {
		'breadcrumbs.enabled': false,
		'breadcrumbs.showEditorType': false,
		// The project service decorates its protected items with a lock; tabs do not repeat it.
		'workbench.editor.decorations.badges': false,
		'workbench.editor.customLabels.patterns': partEditorLabels([...PROJECT_PARTS, STRUCTURE_PART]),
		'workbench.editor.empty.hint': 'hidden',
		// No "Start Debugging F5" style hints in an empty editor area.
		'workbench.tips.enabled': false,
		'chat.titleBar.signIn.enabled': false,
		'chat.titleBar.openInAgentsWindow.enabled': false,
		// The coding-agent chat, Copilot and Codex are code-editor tools: out of sight until SAEngine's
		// own chat panel ships (G10, G12). Developer mode brings them back.
		'chat.disableAIFeatures': true,
		'extensions.ignoreRecommendations': true,
		'git.enabled': false,
		'scm.diffDecorations': 'none',
	},
	source: { id: 'saengine.simpleMode', displayName: 'SAEngine' },
};

const configurationRegistry = Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration);
// Registered while modules load, before the layout and the services read them; developer mode
// takes the simple defaults back out as soon as the workbench starts (see DeveloperModeContribution).
configurationRegistry.registerDefaultConfigurations([SHELL_DEFAULTS]);
const simpleDefaults = new ConfigurationDefaultsSwitch(configurationRegistry, SIMPLE_DEFAULTS);
simpleDefaults.set(true);

//#endregion

//#region Views and menus

const EXTENSIONS_VIEW_CONTAINER = 'workbench.view.extensions';

/** View containers that belong to code editing: every view in them is shown in developer mode only. */
const DEVELOPER_VIEW_CONTAINERS = new Set([
	// The file explorer: the project sidebar lists each part's files, so Files is a developer tool.
	'workbench.view.explorer',
	'workbench.view.scm',
	'workbench.view.debug',
	EXTENSIONS_VIEW_CONTAINER,
	'workbench.view.extension.test',
	'terminal',
	'workbench.panel.repl',
	'workbench.panel.testResults',
	'~remote.forwardedPortsContainer',
]);

/** Single code-editor views in otherwise kept containers. */
const DEVELOPER_VIEWS = new Set(['outline', 'timeline']);

/** Top-level menus of the ≡ menu that only make sense for code: Selection, Go, Run, Terminal. */
const DEVELOPER_MENUS = new Set([MenuId.MenubarSelectionMenu, MenuId.MenubarGoMenu, MenuId.MenubarDebugMenu, MenuId.MenubarTerminalMenu]);

/**
 * What the File, Edit and Help menus and the gear menu keep outside developer mode (G9): SAEngine's
 * own commands and these. Everything else in them is a code-editor item.
 */
const SIMPLE_MENU_ITEMS: ReadonlyMap<MenuId, ReadonlySet<string>> = new Map([
	[MenuId.MenubarFileMenu, new Set([
		'workbench.action.files.save', 'workbench.action.files.saveAll', 'workbench.action.files.revert',
		'workbench.action.closeActiveEditor', 'workbench.action.closeWindow', 'workbench.action.newWindow',
		'workbench.action.quit', MenuId.MenubarPreferencesMenu.id,
	])],
	[MenuId.MenubarEditMenu, new Set([
		'undo', 'redo', 'editor.action.clipboardCutAction', 'editor.action.clipboardCopyAction',
		'editor.action.clipboardPasteAction', 'actions.find', 'editor.action.startFindReplaceAction',
	])],
	[MenuId.MenubarHelpMenu, new Set(['workbench.action.showAboutDialog', 'workbench.action.showCommands'])],
	[MenuId.MenubarPreferencesMenu, new Set([
		'workbench.action.openSettings', 'workbench.action.openGlobalKeybindings', 'ThemesSubMenu',
	])],
	[MenuId.GlobalActivity, new Set([
		'workbench.action.showCommands', 'workbench.action.openSettings', 'workbench.action.openGlobalKeybindings',
		'ThemesSubMenu',
	])],
]);

function keptInSimpleMode(menu: MenuId, id: string): boolean {
	return id.startsWith('saengine.') || !!SIMPLE_MENU_ITEMS.get(menu)?.has(id);
}

/**
 * Adds "developer mode" to the condition of the code-editor views. The containers are
 * `hideIfEmpty`, so they leave the activity bar along with their views.
 */
class DeveloperViewsGate extends ViewsGate {

	constructor() {
		const viewContainersRegistry = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry);
		super(DeveloperModeContext, DEVELOPER_VIEW_CONTAINERS, DEVELOPER_VIEWS, viewContainersRegistry, Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry));
		this.anchorExtensions(viewContainersRegistry);
	}

	/**
	 * The Extensions views depend on context keys that only exist once the Extensions view is
	 * open, so on their own they would keep the container out of the activity bar even in
	 * developer mode. An empty, never shown view keeps it there while developer mode is on.
	 */
	private anchorExtensions(viewContainersRegistry: IViewContainersRegistry): void {
		const container = viewContainersRegistry.get(EXTENSIONS_VIEW_CONTAINER);
		if (!container) {
			return;
		}
		this.registerGated([{
			id: 'saengine.extensionsAnchor',
			name: localize2('saengine.extensionsAnchor', "Extensions"),
			ctorDescriptor: new SyncDescriptor(AnchorView),
			when: ContextKeyExpr.and(DeveloperModeContext, ActiveViewletContext.notEqualsTo(EXTENSIONS_VIEW_CONTAINER)),
			canToggleVisibility: false,
			canMoveView: false,
			order: Number.MAX_SAFE_INTEGER,
		}], container);
	}
}

/** An empty view that is only ever active while its container is closed (see `anchorExtensions`). */
class AnchorView extends ViewPane { }

//#endregion

/** Status bar items of the text editor and of code tools; hidden unless in developer mode. */
const DEVELOPER_STATUS_ENTRIES = [
	'status.editor.selection',
	'status.editor.indentation',
	'status.editor.encoding',
	'status.editor.eol',
	'status.editor.mode',
	'status.editor.info',
	'status.languageStatus',
	'status.problems',
	'status.debug',
	'status.host',
	'status.forwardedPorts',
	// AI status items (G12); the chat itself is off in simple mode (chat.disableAIFeatures).
	'chat.statusBarEntry',
	'codex.statusBarEntry',
	// The API tests' sample item ("Hello", "Hover World"), when a dev build loads that extension (G12).
	'vscode.vscode-api-tests.myStaticItem',
];

/** Where simple mode remembers the user's own visibility of the developer items. */
const DEVELOPER_ITEMS_SNAPSHOT_KEY = 'saengine.shell.developerItemsVisibility';

/** Applies `saengine.developerMode`: context key, configuration defaults, views, status bar, accounts. */
class DeveloperModeContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.developerMode';

	private readonly context: IContextKey<boolean>;

	constructor(
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@IStorageService private readonly storageService: IStorageService,
		@ILifecycleService lifecycleService: ILifecycleService,
	) {
		super();
		this.context = DeveloperModeContext.bindTo(contextKeyService);
		this._register(new DeveloperViewsGate());
		gateSubmenus(MenuId.MenubarMainMenu, DEVELOPER_MENUS, DeveloperModeContext);
		for (const menu of SIMPLE_MENU_ITEMS.keys()) {
			this._register(gateMenuItems(menu, id => keptInSimpleMode(menu, id), DeveloperModeContext));
		}

		this.apply();
		void lifecycleService.when(LifecyclePhase.Restored).then(() => this.applyToParts());
		this._register(configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.apply();
				this.applyToParts();
			}
		}));
	}

	private get developerMode(): boolean {
		return this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
	}

	private apply(): void {
		const developerMode = this.developerMode;
		this.context.set(developerMode);
		simpleDefaults.set(!developerMode);
	}

	/**
	 * The status bar and the accounts entry keep their visibility per profile, as the user set it.
	 * Simple mode remembers that choice before it hides them and developer mode gives it back.
	 */
	private applyToParts(): void {
		applyDeveloperItems(this.developerMode, DEVELOPER_STATUS_ENTRIES, {
			isEntryVisible: id => this.statusbarService.isEntryVisible(id),
			updateEntryVisibility: (id, visible) => this.statusbarService.updateEntryVisibility(id, visible),
			isAccountsVisible: () => isAccountsActionVisible(this.storageService),
			setAccountsVisible: visible => setAccountsActionVisible(this.storageService, visible),
			readSnapshot: () => parseDeveloperItemsSnapshot(this.storageService.get(DEVELOPER_ITEMS_SNAPSHOT_KEY, StorageScope.PROFILE)),
			writeSnapshot: snapshot => {
				if (snapshot) {
					this.storageService.store(DEVELOPER_ITEMS_SNAPSHOT_KEY, JSON.stringify(snapshot), StorageScope.PROFILE, StorageTarget.MACHINE);
				} else {
					this.storageService.remove(DEVELOPER_ITEMS_SNAPSHOT_KEY, StorageScope.PROFILE);
				}
			},
		});
	}
}

registerWorkbenchContribution2(DeveloperModeContribution.ID, DeveloperModeContribution, WorkbenchPhase.BlockStartup);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.toggleDeveloperMode',
			title: localize2('saengine.toggleDeveloperMode', "Toggle Developer Mode"),
			category: localize2('saengine.category', "SAEngine"),
			toggled: DeveloperModeContext,
			f1: true,
			menu: { id: MenuId.MenubarHelpMenu, group: '5_tools', order: 0 },
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		const configurationService = accessor.get(IConfigurationService);
		return configurationService.updateValue(DEVELOPER_MODE_SETTING, configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) !== true, ConfigurationTarget.USER);
	}
});

//#region User manual

/**
 * Where the user manual is: `resources/saengine/manual` in a packaged app, `docs/manual` of the
 * repository in a build from sources (the app root is its `workbench` folder).
 */
function manualFolders(): URI[] {
	const appRoot = dirname(FileAccess.asFileUri(''));
	return [joinPath(appRoot, 'resources', 'saengine', 'manual'), joinPath(dirname(appRoot), 'docs', 'manual')];
}

/** The manual's chapters online, for builds that do not carry the manual. */
const MANUAL_ONLINE = 'https://github.com/princekhan7748/saengine/tree/main/docs/manual';

/**
 * Opens the user manual: a chapter (`01-soil-report`, `tutorials/01-sample-project`) in the
 * Markdown preview, or the whole manual as PDF. A build without the manual offers it online.
 */
async function openManual(accessor: ServicesAccessor, chapter?: string): Promise<void> {
	const fileService = accessor.get(IFileService);
	const commandService = accessor.get(ICommandService);
	const openerService = accessor.get(IOpenerService);
	const notificationService = accessor.get(INotificationService);
	const name = chapter && /^[\w/-]+$/.test(chapter) ? `${chapter}.md` : 'SAEngine-User-Manual.pdf';
	for (const folder of manualFolders()) {
		const file = joinPath(folder, name);
		if (await fileService.exists(file)) {
			if (name.endsWith('.md')) {
				await commandService.executeCommand('markdown.showPreview', file);
			} else {
				await openerService.open(file, { openExternal: true });
			}
			return;
		}
	}
	notificationService.prompt(Severity.Info, localize('saengine.manual.missing', "This build of SAEngine does not include the user manual."), [{
		label: localize('saengine.manual.online', "Read It Online"),
		run: () => openerService.open(URI.parse(chapter ? `${MANUAL_ONLINE}/${name}` : MANUAL_ONLINE), { openExternal: true }),
	}]);
}

CommandsRegistry.registerCommand(OPEN_MANUAL_COMMAND, (accessor, chapter?: unknown) => openManual(accessor, typeof chapter === 'string' ? chapter : undefined));

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.help.userManual',
			title: localize2('saengine.userManual', "User Manual"),
			category: localize2('help', "Help"),
			f1: true,
			menu: { id: MenuId.MenubarHelpMenu, group: '1_welcome', order: 1 },
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return openManual(accessor);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.help.tutorial',
			title: localize2('saengine.tutorial', "Tutorial: the Sample Project"),
			category: localize2('help', "Help"),
			f1: true,
			menu: { id: MenuId.MenubarHelpMenu, group: '1_welcome', order: 2 },
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return openManual(accessor, 'tutorials/01-sample-project');
	}
});

//#endregion

//#region Run all

// F5 runs everything, as in the analysis programs engineers know (G19); in developer mode F5 debugs.
KeybindingsRegistry.registerKeybindingRule({
	id: RUN_ALL_COMMAND,
	primary: KeyCode.F5,
	when: ContextKeyExpr.and(ProjectOpenContext, DeveloperModeContext.negate()),
	weight: KeybindingWeight.WorkbenchContrib + 10,
});

MenuRegistry.appendMenuItem(MenuId.TitleBar, {
	command: {
		id: RUN_ALL_COMMAND,
		title: localize2('saengine.runAll', "Run All"),
		tooltip: localize('saengine.runAll.tooltip', "Run the analysis and the design of the project"),
		icon: Codicon.play,
	},
	when: ProjectOpenContext,
	group: 'navigation',
	order: -1,
});

/** The primary action of the window: an icon and a label in button colours. */
class RunAllTitleBarItem extends BaseActionViewItem {

	private label: HTMLElement | undefined;

	constructor(action: IAction, options: IBaseActionViewItemOptions) {
		super(undefined, action, options);
	}

	override render(container: HTMLElement): void {
		super.render(container);
		container.classList.add('saengine-run-all');
		container.setAttribute('role', 'button');
		const content = append(container, $('.saengine-run-all-content'));
		append(content, $(ThemeIcon.asCSSSelector(Codicon.play)));
		this.label = append(content, $('span.saengine-run-all-label'));
		this.updateLabel();
		this.updateEnabled();
	}

	protected override updateLabel(): void {
		if (this.label) {
			this.label.textContent = this.action.label;
		}
		this.element?.setAttribute('aria-label', this.action.label);
	}

	protected override updateEnabled(): void {
		this.element?.classList.toggle('disabled', !this.action.enabled);
	}
}

class RunAllTitleBarContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.runAllTitleBar';

	constructor(
		@IActionViewItemService actionViewItemService: IActionViewItemService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(actionViewItemService.register(MenuId.TitleBar, RUN_ALL_COMMAND, (action, options) => instantiationService.createInstance(RunAllTitleBarItem, action, options)));
	}
}

registerWorkbenchContribution2(RunAllTitleBarContribution.ID, RunAllTitleBarContribution, WorkbenchPhase.BlockStartup);

//#endregion
