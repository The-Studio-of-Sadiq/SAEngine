/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { ContextKeyExpr, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewsRegistry, ViewContainerLocation } from '../../../common/views.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ModelExplorerView } from './modelExplorerView.js';
import { ProjectCodeStiffnessContribution } from './projectCodeStiffness.js';
import { PropertiesView } from './propertiesView.js';

/** True while a SAEngine project is open. */
const ProjectOpenContext = new RawContextKey<boolean>('saengineProjectOpen', false, localize('saengineProjectOpen', "Whether a SAEngine project is open"));

const VIEW_CONTAINER_ID = 'workbench.view.saengine.model';

/** The project sidebar (saengineNavigator.contribution.ts): the parts, then the model tree. */
const PROJECT_VIEW_CONTAINER_ID = 'workbench.view.saengine.project';

/** Developer mode (`saengine.developerMode`, see saengineShell.contribution.ts). */
const DeveloperModeContext = ContextKeyExpr.has('saengineDeveloperMode');

const modelViewIcon = registerIcon('saengine-model-view-icon', Codicon.symbolStructure, localize('modelViewIcon', "View icon of the SAEngine model views."));
const explorerViewIcon = registerIcon('saengine-model-explorer-view-icon', Codicon.listTree, localize('modelExplorerViewIcon', "View icon of the Model Explorer."));
const propertiesViewIcon = registerIcon('saengine-properties-view-icon', Codicon.symbolProperty, localize('propertiesViewIcon', "View icon of the Properties view."));

const viewContainers = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry);
const viewsRegistry = Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry);

/*
 * The model tree lives in the project sidebar, under the parts, collapsed until opened: it
 * selects members for the Floor Plan, BIM and the analysis wherever they are open. The editors
 * show the selection's properties in their own properties panel, so the separate Properties view
 * and its "Model" side bar (an extra icon) are only there in developer mode.
 */
const modelContainer = viewContainers.registerViewContainer({
	id: VIEW_CONTAINER_ID,
	title: localize2('model', "Model"),
	icon: modelViewIcon,
	order: 2,
	hideIfEmpty: true,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [VIEW_CONTAINER_ID, { mergeViewWithContainerWhenSingleView: false }]),
	storageId: VIEW_CONTAINER_ID,
}, ViewContainerLocation.Sidebar);

function registerExplorer(): void {
	const projectContainer = viewContainers.get(PROJECT_VIEW_CONTAINER_ID);
	viewsRegistry.registerViews([{
		id: ModelExplorerView.ID,
		name: localize2('modelExplorer', "Model Explorer"),
		containerIcon: explorerViewIcon,
		ctorDescriptor: new SyncDescriptor(ModelExplorerView),
		when: ProjectOpenContext,
		canMoveView: true,
		canToggleVisibility: true,
		collapsed: true,
		// Opened, it takes a third of the sidebar: the Parts list above keeps most of it at 1366×768.
		weight: 10,
		order: 10,
	}], projectContainer ?? modelContainer);
}

// The project sidebar is registered by the project contribution; it may load after this one.
if (viewContainers.get(PROJECT_VIEW_CONTAINER_ID)) {
	registerExplorer();
} else {
	const listener = viewContainers.onDidRegister(({ viewContainer }) => {
		if (viewContainer.id === PROJECT_VIEW_CONTAINER_ID) {
			listener.dispose();
			registerExplorer();
		}
	});
}

viewsRegistry.registerViews([{
	id: PropertiesView.ID,
	name: localize2('properties', "Properties"),
	containerIcon: propertiesViewIcon,
	ctorDescriptor: new SyncDescriptor(PropertiesView),
	when: ContextKeyExpr.and(ProjectOpenContext, DeveloperModeContext),
	canMoveView: true,
	weight: 40,
	order: 2,
}], modelContainer);

/** Keeps `saengineProjectOpen` in step with the project service. */
class ProjectOpenContextContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.projectOpenContext';

	constructor(
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		super();
		const key = ProjectOpenContext.bindTo(contextKeyService);
		key.set(!!projectService.project);
		this._register(projectService.onDidChangeProject(project => key.set(!!project)));
	}
}

registerWorkbenchContribution2(ProjectOpenContextContribution.ID, ProjectOpenContextContribution, WorkbenchPhase.BlockRestore);

registerWorkbenchContribution2(ProjectCodeStiffnessContribution.ID, ProjectCodeStiffnessContribution, WorkbenchPhase.AfterRestored);
