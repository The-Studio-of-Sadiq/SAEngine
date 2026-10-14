/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize, localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { IViewContainersRegistry, IViewsRegistry, Extensions as ViewContainerExtensions, ViewContainerLocation } from '../../../common/views.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { STRUCTURAL_ENGINEERING_VIEW_ID, StructuralEngineeringView } from './structuralEngineeringView.js';

const category = localize2('structuralEngineering.category', "Structural Engineering");
const viewIcon = registerIcon(
	'structural-engineering-view-icon',
	Codicon.tools,
	localize('structuralEngineering.viewIcon', "Structural Engineering view icon."),
);

const viewContainer = Registry.as<IViewContainersRegistry>(ViewContainerExtensions.ViewContainersRegistry).registerViewContainer({
	id: 'workbench.viewContainer.structuralEngineering',
	title: category,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [
		'workbench.viewContainer.structuralEngineering',
		{ mergeViewWithContainerWhenSingleView: true },
	]),
	icon: viewIcon,
	alwaysUseContainerInfo: true,
	order: 6,
}, ViewContainerLocation.Sidebar, { isDefault: true });

Registry.as<IViewsRegistry>(ViewContainerExtensions.ViewsRegistry).registerViews([{
	id: STRUCTURAL_ENGINEERING_VIEW_ID,
	name: localize2('structuralEngineering.viewTitle', "Engineering Workspace"),
	ctorDescriptor: new SyncDescriptor(StructuralEngineeringView),
	canToggleVisibility: true,
	canMoveView: true,
	containerIcon: viewIcon,
}], viewContainer);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'structuralEngineering.openWorkbench',
			title: localize2('structuralEngineering.openWorkbench', "Open Workbench"),
			category,
			f1: true,
		});
	}

	override run(accessor: ServicesAccessor) {
		return accessor.get(IViewsService).openView(STRUCTURAL_ENGINEERING_VIEW_ID, true);
	}
});

// Run Analysis and Configure Python Runtime are implemented in contrib/saengineFem (desktop).
const placeholders = [
	{
		id: 'structuralEngineering.createProject',
		title: localize2('structuralEngineering.createProject', "Create Engineering Project"),
		message: localize('structuralEngineering.createProjectPlaceholder', "Engineering project creation is not implemented yet."),
	},
	{
		id: 'structuralEngineering.openProject',
		title: localize2('structuralEngineering.openProject', "Open Engineering Project"),
		message: localize('structuralEngineering.openProjectPlaceholder', "Opening engineering projects is not implemented yet."),
	},
];

for (const placeholder of placeholders) {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: placeholder.id,
				title: placeholder.title,
				category,
			});
		}

		override run(accessor: ServicesAccessor): void {
			void accessor.get(INotificationService).info(placeholder.message);
		}
	});
}
