/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { URI } from '../../../../base/common/uri.js';
import { localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { PROJECT_MENU, ProjectOpenContext } from './projectMenu.js';
import { REVIT_EXPORT_UI_COMMAND, REVIT_IMPORT_UI_COMMAND, RevitLinkFlows } from './revitLink.js';

/*
 * The Revit link's commands (Command Palette, the sidebar's ≡ menu and the Exports page): the
 * exchange file for Revit, and the changes made in Revit back with a preview.
 */

const category = localize2('saengine.category', "SAEngine");

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: REVIT_EXPORT_UI_COMMAND,
			title: localize2('saengine.revitExport', "Export for Revit"),
			metadata: { description: localize2('saengine.revitExport.description', "Writes the analytical model and the designed bars as a SAEngine exchange file for the Revit add-in (11 Exports/Revit).") },
			category,
			f1: true,
			precondition: ProjectOpenContext,
			menu: [{ id: PROJECT_MENU, group: '3_share', order: 5, when: ProjectOpenContext }],
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(IInstantiationService).createInstance(RevitLinkFlows).export();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: REVIT_IMPORT_UI_COMMAND,
			title: localize2('saengine.revitImport', "Import Changes from Revit..."),
			metadata: { description: localize2('saengine.revitImport.description', "Reads an exchange file written back by the Revit add-in, previews the changes and applies the ones you keep to the floor plan.") },
			category,
			f1: true,
			precondition: ProjectOpenContext,
			menu: [{ id: PROJECT_MENU, group: '3_share', order: 6, when: ProjectOpenContext }],
		});
	}

	override run(accessor: ServicesAccessor, args?: unknown): Promise<void> {
		const path = typeof args === 'string' ? args : URI.isUri(args) ? args.fsPath : undefined;
		return accessor.get(IInstantiationService).createInstance(RevitLinkFlows).import(path);
	}
});
