/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ViewContainerLocation } from '../../../common/views.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IPaneCompositePartService } from '../../../services/panecomposite/browser/panecomposite.js';
import { NEW_FROM_TEMPLATE_COMMAND } from '../../saengineLibrary/common/packageTemplates.js';
import { NEW_BUILDING_COMMAND, NEW_PROJECT_COMMAND } from './newBuildingModel.js';
import { NewBuildingOpener, NewBuildingWizard, NewBuildingWizardInput, NewProjectStart } from './newBuildingWizard.js';
import { INewFromTemplateArgs, ProjectArchiveFlows } from './projectArchiveFlows.js';
import { PROJECT_MENU } from './projectMenu.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { PROJECT_VIEW_CONTAINER_ID } from './saengineNavigator.contribution.js';

/*
 * New Project... (start page, ≡ File, the sidebar's ≡ menu, the command palette): the one way to
 * start a project, the wizard here. The backend's `saengine.library.generateBuilding` writes a
 * building from the grid. The former entries New Building from Grid... and New Project from
 * Template... stay as command ids (keybindings, links, the AI assistant) that open the same wizard.
 */

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(NewBuildingWizard, NewBuildingWizardInput.EDITOR_ID, localize('saengineNewProjectEditor', "SAEngine New Project")),
	[new SyncDescriptor(NewBuildingWizardInput)]
);

interface INewProjectArgs {
	/** A building specification to fill the grid's pages with (the AI assistant's proposal). */
	readonly spec?: unknown;
	/** What to start from: the grid (default) or the first full template installed. */
	readonly startFrom?: NewProjectStart;
}

/** Opens the wizard, with `args` applied when it shows (it opens again if it is open already). */
async function openWizard(accessor: ServicesAccessor, args: INewProjectArgs): Promise<void> {
	const paneComposites = accessor.get(IPaneCompositePartService);
	const developerMode = accessor.get(IConfigurationService).getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
	const editorService = accessor.get(IEditorService);
	const spec = typeof args.spec === 'object' && args.spec !== null && !Array.isArray(args.spec) ? args.spec as { readonly [key: string]: unknown } : undefined;
	const startFrom = args.startFrom === 'grid' || args.startFrom === 'template' ? args.startFrom : undefined;
	if (spec || startFrom) {
		// Already open: close it, so the form opens again with what was asked.
		for (const open of editorService.findEditors(NewBuildingWizardInput.instance)) {
			await editorService.closeEditor(open);
		}
		NewBuildingWizardInput.instance.prefill = spec;
		NewBuildingWizardInput.instance.startFrom = startFrom;
	}
	await editorService.openEditor(NewBuildingWizardInput.instance, { pinned: true });
	// The side bar keeps (or comes back to) the project's parts, not Search or Explorer (as a project opens).
	const active = paneComposites.getActivePaneComposite(ViewContainerLocation.Sidebar)?.getId();
	if (!developerMode && !active?.startsWith('workbench.view.saengine.')) {
		await paneComposites.openPaneComposite(PROJECT_VIEW_CONTAINER_ID, ViewContainerLocation.Sidebar, false);
	}
}

function asArgs(arg: unknown): INewProjectArgs {
	return typeof arg === 'object' && arg !== null ? arg as INewProjectArgs : {};
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: NEW_PROJECT_COMMAND,
			title: localize2('saengine.newProject', "New Project..."),
			metadata: { description: localize2('saengine.newProject.description', "Opens the New Project wizard: the project, its site and use, and the grid and storeys of the building (or a building specification, a full template or an empty project from Start from). Arguments: {spec, startFrom: 'grid' | 'template'}.") },
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
			icon: Codicon.newFolder,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '1_new', order: 0 },
				{ id: PROJECT_MENU, group: '1_project', order: 5 },
			],
		});
	}

	override run(accessor: ServicesAccessor, arg?: unknown): Promise<void> {
		return openWizard(accessor, asArgs(arg));
	}
});

// Former entry "New Building from Grid...": the same wizard, on the grid; `{spec}` fills it (the AI assistant).
CommandsRegistry.registerCommand({
	id: NEW_BUILDING_COMMAND,
	metadata: { description: localize('saengine.newBuilding.alias', "Opens New Project on the grid (formerly New Building from Grid...). Arguments: {spec}.") },
	handler: (accessor, arg?: unknown) => openWizard(accessor, { spec: asArgs(arg).spec, startFrom: 'grid' }),
});

// Former entry "New Project from Template...": with a template's `path`, its check and the archive
// path (New Project's Create calls it so); without one, New Project with the template in Start from.
CommandsRegistry.registerCommand({
	id: NEW_FROM_TEMPLATE_COMMAND,
	metadata: { description: localize('saengine.newFromTemplate.alias', "Opens a full building template (an inputs-only .civil of an installed building-template package) as a new project after checking it; without a path, New Project with the first full template in Start from. Arguments: {path, author, name, destParent}.") },
	handler: async (accessor, args?: INewFromTemplateArgs | string): Promise<URI | undefined> => {
		const bag: INewFromTemplateArgs = typeof args === 'string' ? { path: args } : typeof args === 'object' && args !== null && !URI.isUri(args) ? args : {};
		if (bag.path) {
			return accessor.get(IInstantiationService).createInstance(ProjectArchiveFlows).newFromTemplate({ ...bag, path: bag.path });
		}
		await openWizard(accessor, { startFrom: 'template' });
		return undefined;
	},
});

registerWorkbenchContribution2('workbench.contrib.saengineNewBuildingOpener', NewBuildingOpener, WorkbenchPhase.AfterRestored);
