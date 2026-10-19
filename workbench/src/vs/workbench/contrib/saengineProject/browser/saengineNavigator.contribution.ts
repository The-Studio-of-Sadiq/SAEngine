/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import '../../../services/saengineProject/browser/partStatusService.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, IDisposable, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ConfigurationTarget, IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewsRegistry, ViewContainerLocation } from '../../../common/views.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IWorkbenchLayoutService, Parts } from '../../../services/layout/browser/layoutService.js';
import { ILifecycleService } from '../../../services/lifecycle/common/lifecycle.js';
import { IPaneCompositePartService } from '../../../services/panecomposite/browser/panecomposite.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { ExportsEditor } from './exportsEditor.js';
import { ExportsEditorInput, ExportsEditorInputSerializer } from './exportsEditorInput.js';
import { PLACEHOLDER_PARTS, PlaceholderEditor, placeholderPartOf } from './placeholderEditor.js';
import { PlaceholderEditorInput, PlaceholderEditorInputSerializer } from './placeholderEditorInput.js';
import { DEVELOPER_MODE_SETTING, ProjectNavigatorView } from './projectNavigatorView.js';
import { ProjectOpener } from './projectOpener.js';
import { ProjectOverviewEditor } from './projectOverviewEditor.js';
import { ProjectOverviewInput } from './projectOverviewInput.js';
import { openPart } from './projectParts.js';
import { PROJECT_MENU } from './projectMenu.js';
import { StartEditorInput } from './startEditorInput.js';
import './projectPlatform.contribution.js';

const category = localize2('saengine.category', "SAEngine");
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

/** The side bar of the model views (Model Explorer, Properties). */
const MODEL_VIEW_CONTAINER_ID = 'workbench.view.saengine.model';
const REVEAL_IN_OS_COMMAND_ID = 'revealFileInOS';

// --- The project sidebar ---------------------------------------------------------------------

export const PROJECT_VIEW_CONTAINER_ID = 'workbench.view.saengine.project';

const projectViewIcon = registerIcon('saengine-project-view-icon', Codicon.project, localize('projectViewIcon', "View icon of the SAEngine project sidebar."));

const container = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry).registerViewContainer({
	id: PROJECT_VIEW_CONTAINER_ID,
	title: localize2('project', "Project"),
	icon: projectViewIcon,
	// Above the Explorer (0) at the top of the activity bar.
	order: -1,
	hideIfEmpty: true,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [PROJECT_VIEW_CONTAINER_ID, { mergeViewWithContainerWhenSingleView: true }]),
	storageId: PROJECT_VIEW_CONTAINER_ID,
	openCommandActionDescriptor: {
		id: PROJECT_VIEW_CONTAINER_ID,
		title: localize2('showProject', "Project"),
		order: -1,
	},
}, ViewContainerLocation.Sidebar, { isDefault: true });

Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry).registerViews([{
	id: ProjectNavigatorView.ID,
	name: localize2('projectParts', "Parts"),
	containerIcon: projectViewIcon,
	ctorDescriptor: new SyncDescriptor(ProjectNavigatorView),
	when: projectOpen,
	canToggleVisibility: false,
	canMoveView: true,
	order: 0,
}], container);

// --- The project overview --------------------------------------------------------------------

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(ProjectOverviewEditor, ProjectOverviewInput.EDITOR_ID, localize('saengineOverviewEditor', "SAEngine Project Overview")),
	[new SyncDescriptor(ProjectOverviewInput)]
);

// --- Part 11: the exports page ---------------------------------------------------------------

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(ExportsEditor, ExportsEditor.ID, localize('saengineExportsEditor', "SAEngine Exports")),
	[new SyncDescriptor(ExportsEditorInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(ExportsEditorInput.ID, ExportsEditorInputSerializer);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.showExports',
			title: localize2('saengine.showExports', "Exports"),
			category,
			icon: Codicon.export,
			f1: true,
			precondition: projectOpen,
		});
	}

	override run(accessor: ServicesAccessor): Promise<unknown> {
		return accessor.get(IEditorService).openEditor(ExportsEditorInput.instance, { pinned: true });
	}
});

// --- Parts not built yet: their calm page -----------------------------------------------------

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(PlaceholderEditor, PlaceholderEditor.ID, localize('saenginePlaceholderEditor', "SAEngine Part (Not Built Yet)")),
	[new SyncDescriptor(PlaceholderEditorInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(PlaceholderEditorInput.ID, PlaceholderEditorInputSerializer);

/**
 * Opens the main files of the parts that are not built yet (1 Soil Report, 7 MEP,
 * 9 Substructure) on their page. Registered as the default editor rather than exclusive, so
 * "Reopen Editor With..." and the page's "Open as JSON" still reach the text; a part's real
 * editor replaces this by registering for its file and dropping the part from PLACEHOLDER_PARTS.
 */
class PlaceholderEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.placeholderEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IWorkspaceContextService contextService: IWorkspaceContextService,
	) {
		super();
		for (const { part: id } of PLACEHOLDER_PARTS) {
			const part = partById(id);
			if (!part?.mainFile) {
				continue;
			}
			this._register(editorResolverService.registerEditor(
				`**/${part.folder}/${part.mainFile}`,
				{
					id: PlaceholderEditor.ID,
					label: localize('placeholderEditor.label', "SAEngine Part"),
					detail: localize('placeholderEditor.detail', "SAEngine"),
					priority: RegisteredEditorPriority.default,
				},
				{
					singlePerResource: true,
					// Project detection is asynchronous; until it finishes, match by the workspace folder.
					canSupportResource: resource => placeholderPartOf(resource, projectService.project?.root ?? contextService.getWorkspaceFolder(resource)?.uri) === id,
				},
				{
					createEditorInput: ({ resource, options }) => ({ editor: new PlaceholderEditorInput(resource, id), options }),
				}
			));
		}
	}
}

registerWorkbenchContribution2(PlaceholderEditorResolverContribution.ID, PlaceholderEditorResolverContribution, WorkbenchPhase.BlockStartup);

function openOverview(editorService: IEditorService): Promise<unknown> {
	return editorService.openEditor(ProjectOverviewInput.instance, { pinned: true });
}

// --- The sidebar header's ≡ menu and the commands in it -------------------------------------

const projectMenu = PROJECT_MENU;

MenuRegistry.appendMenuItem(MenuId.ViewTitle, {
	submenu: projectMenu,
	title: localize2('projectMenu', "Project"),
	icon: Codicon.menu,
	group: 'navigation',
	order: 1,
	when: ContextKeyExpr.equals('view', ProjectNavigatorView.ID),
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.showOverview',
			title: localize2('saengine.showOverview', "Project Overview"),
			category,
			icon: Codicon.dashboard,
			f1: true,
			precondition: projectOpen,
			menu: { id: projectMenu, group: '1_project', order: 1 },
		});
	}

	override run(accessor: ServicesAccessor): Promise<unknown> {
		return openOverview(accessor.get(IEditorService));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.openSettings',
			title: localize2('saengine.openProjectSettings', "Project Settings"),
			category,
			f1: true,
			precondition: projectOpen,
			menu: { id: projectMenu, group: '1_project', order: 2 },
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const part = partById('settings');
		if (project && part) {
			await openPart(project, part, {
				editorService: accessor.get(IEditorService),
				fileService: accessor.get(IFileService),
				openerService: accessor.get(IOpenerService),
				commandService: accessor.get(ICommandService),
			});
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.revealInOS',
			title: localize2('saengine.revealProject', "Open Folder in File Explorer"),
			category,
			f1: true,
			precondition: projectOpen,
			menu: { id: projectMenu, group: '2_folder', order: 1 },
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		if (project) {
			await accessor.get(ICommandService).executeCommand(REVEAL_IN_OS_COMMAND_ID, project.root);
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.openSample',
			title: localize2('saengine.openSample', "Open Sample Project..."),
			category,
			f1: true,
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(IInstantiationService).createInstance(ProjectOpener).openSample();
	}
});

// --- Opening a project -----------------------------------------------------------------------

/**
 * When a project opens: the project sidebar shows (unless developer mode left another one
 * open), the overview opens if no editor was restored, and the project joins the recent ones.
 */
class ProjectWindowContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.projectWindow';

	private handled: string | undefined;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IEditorService private readonly editorService: IEditorService,
		@IPaneCompositePartService private readonly paneCompositeService: IPaneCompositePartService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
	) {
		super();
		this._register(this.projectService.onDidChangeProject(project => void this.onProject(project)));
		void this.onProject(this.projectService.project);
	}

	private async onProject(project: ISaengineProject | undefined): Promise<void> {
		if (!project || this.handled === project.root.toString()) {
			return;
		}
		this.handled = project.root.toString();
		this.instantiationService.createInstance(ProjectOpener).recordOpened(project.root);

		// Developer mode keeps whichever side bar was open; otherwise the project opens on its parts
		// (or the model views, the other SAEngine side bar).
		const developerMode = this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
		const active = this.paneCompositeService.getActivePaneComposite(ViewContainerLocation.Sidebar)?.getId();
		if (!developerMode && active !== PROJECT_VIEW_CONTAINER_ID && active !== MODEL_VIEW_CONTAINER_ID) {
			await this.paneCompositeService.openPaneComposite(PROJECT_VIEW_CONTAINER_ID, ViewContainerLocation.Sidebar, false);
		}

		const editors = this.editorService.editors.filter(editor => !(editor instanceof StartEditorInput));
		if (!editors.length) {
			await openOverview(this.editorService);
		}
	}
}

registerWorkbenchContribution2(ProjectWindowContribution.ID, ProjectWindowContribution, WorkbenchPhase.AfterRestored);

// --- The start page fills the window ---------------------------------------------------------

/** Settings overridden in memory (never written) while the start page fills the window. */
const START_MODE_SETTINGS: readonly [string, unknown][] = [
	['workbench.activityBar.location', 'hidden'],
	['workbench.statusBar.visible', false],
	['workbench.editor.showTabs', 'none'],
	// Without tabs the editor actions (split, close, ...) would move into the title bar.
	['workbench.editor.editorActionsLocation', 'hidden'],
	// No side bar or panel to toggle.
	['workbench.layoutControl.enabled', false],
];

const START_MODE_PARTS = [Parts.SIDEBAR_PART, Parts.PANEL_PART, Parts.AUXILIARYBAR_PART] as const;

/**
 * While no project is open and the start page is the active editor, the start page is the
 * whole window: the side bars, panel, activity bar, status bar and tabs are hidden, and come
 * back as they were once it closes (or a project opens).
 */
class StartLayoutContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.startLayout';

	private readonly startMode = this._register(new MutableDisposable());

	constructor(
		@IEditorService private readonly editorService: IEditorService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkbenchLayoutService private readonly layoutService: IWorkbenchLayoutService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ILifecycleService lifecycleService: ILifecycleService,
	) {
		super();
		// The window's layout is saved as it was before the start page filled it.
		this._register(lifecycleService.onWillShutdown(() => this.startMode.clear()));
		this._register(this.editorService.onDidActiveEditorChange(() => this.update()));
		this._register(this.projectService.onDidChangeProject(() => this.update()));
		this.update();
	}

	private update(): void {
		const wanted = !this.projectService.project && this.editorService.activeEditor instanceof StartEditorInput;
		if (wanted && !this.startMode.value) {
			this.startMode.value = this.enter();
		} else if (!wanted) {
			this.startMode.clear();
		}
	}

	private enter(): IDisposable {
		const hidden = START_MODE_PARTS.filter(part => this.layoutService.isVisible(part));
		for (const part of hidden) {
			this.layoutService.setPartHidden(true, part);
		}
		for (const [key, value] of START_MODE_SETTINGS) {
			void this.configurationService.updateValue(key, value, ConfigurationTarget.MEMORY);
		}
		this.layoutService.mainContainer.classList.add('saengine-start-mode');
		return toDisposable(() => {
			this.layoutService.mainContainer.classList.remove('saengine-start-mode');
			for (const [key] of START_MODE_SETTINGS) {
				void this.configurationService.updateValue(key, undefined, ConfigurationTarget.MEMORY);
			}
			for (const part of hidden) {
				this.layoutService.setPartHidden(false, part);
			}
		});
	}
}

registerWorkbenchContribution2(StartLayoutContribution.ID, StartLayoutContribution, WorkbenchPhase.AfterRestored);
