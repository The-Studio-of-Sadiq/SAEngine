/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ViewContainerLocation } from '../../../common/views.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IPaneCompositePartService } from '../../../services/panecomposite/browser/panecomposite.js';
import { NEW_BUILDING_COMMAND } from './newBuildingModel.js';
import { NewBuildingOpener, NewBuildingWizard, NewBuildingWizardInput } from './newBuildingWizard.js';
import { PROJECT_MENU } from './projectMenu.js';
import { DEVELOPER_MODE_SETTING } from './projectNavigatorView.js';
import { PROJECT_VIEW_CONTAINER_ID } from './saengineNavigator.contribution.js';

/*
 * New Building from Grid (start page, ≡ File, the sidebar's ≡ menu): the wizard here; the
 * backend's `saengine.library.generateBuilding` writes the project.
 */

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(NewBuildingWizard, NewBuildingWizardInput.EDITOR_ID, localize('saengineNewBuildingEditor', "SAEngine New Building")),
	[new SyncDescriptor(NewBuildingWizardInput)]
);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: NEW_BUILDING_COMMAND,
			title: localize2('saengine.newBuilding', "New Building from Grid..."),
			metadata: { description: localize2('saengine.newBuilding.description', "Creates a new project with a whole building (columns, beams, walls, slabs and footings on every storey) from its grids and storeys.") },
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
			icon: Codicon.symbolStructure,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '1_new', order: 1 },
				{ id: PROJECT_MENU, group: '1_project', order: 5 },
			],
		});
	}

	/** `{spec?}`: a building specification to fill the form with (the AI assistant's proposal). */
	override async run(accessor: ServicesAccessor, arg?: unknown): Promise<void> {
		const paneComposites = accessor.get(IPaneCompositePartService);
		const developerMode = accessor.get(IConfigurationService).getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
		const editorService = accessor.get(IEditorService);
		const spec = typeof arg === 'object' && arg !== null ? (arg as { spec?: unknown }).spec : undefined;
		if (typeof spec === 'object' && spec !== null && !Array.isArray(spec)) {
			// Already open: close it, so the form opens again with the specification.
			for (const open of editorService.findEditors(NewBuildingWizardInput.instance)) {
				await editorService.closeEditor(open);
			}
			NewBuildingWizardInput.instance.prefill = spec as { readonly [key: string]: unknown };
		}
		await editorService.openEditor(NewBuildingWizardInput.instance, { pinned: true });
		// The side bar keeps (or comes back to) the project's parts, not Search or Explorer (as a project opens).
		const active = paneComposites.getActivePaneComposite(ViewContainerLocation.Sidebar)?.getId();
		if (!developerMode && !active?.startsWith('workbench.view.saengine.')) {
			await paneComposites.openPaneComposite(PROJECT_VIEW_CONTAINER_ID, ViewContainerLocation.Sidebar, false);
		}
	}
});

registerWorkbenchContribution2('workbench.contrib.saengineNewBuildingOpener', NewBuildingOpener, WorkbenchPhase.AfterRestored);
