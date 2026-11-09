/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { OfficeTool } from './officeModel.js';
import { OfficeToolsEditor } from './officeToolsEditor.js';
import { OfficeToolsInput } from './officeToolsInput.js';

/*
 * Alpha 9 L11, the office tools: the 4D programme, cost-driven optimisation, PDF takeoff, the site's
 * terrain and environment studies, MEP fabrication detailing, phases and design options, in one
 * editor (a tab per tool) opened from the command palette. The BIM view's studies (render presets,
 * walk mode, stills, 4D playback, terrain, sun, phases) are in its "..." menu (bimStudies.ts).
 */

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(OfficeToolsEditor, OfficeToolsInput.EDITOR_ID, localize('officeToolsEditorPane', "SAEngine Office Tools")),
	[new SyncDescriptor(OfficeToolsInput)]
);

const COMMANDS: readonly [OfficeTool, string, ReturnType<typeof localize2>][] = [
	['schedule', 'saengine.office.schedule', localize2('saengine.office.schedule', "Office Tools: 4D Construction Programme")],
	['cost', 'saengine.office.cost', localize2('saengine.office.cost', "Office Tools: Cost-Driven Optimisation")],
	['takeoff', 'saengine.office.takeoff', localize2('saengine.office.takeoff', "Office Tools: 2D Takeoff from PDF Drawings")],
	['site', 'saengine.office.site', localize2('saengine.office.site', "Office Tools: Terrain, Sun, Daylight and Road Noise")],
	['fabrication', 'saengine.office.fabrication', localize2('saengine.office.fabrication', "Office Tools: MEP Fabrication (LOD 400)")],
	['phasing', 'saengine.office.phasing', localize2('saengine.office.phasing', "Office Tools: Phases and Design Options")],
];

for (const [tool, id, title] of COMMANDS) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title, category: localize2('saengine.category', "SAEngine"), f1: true, precondition: ContextKeyExpr.has('saengineProjectOpen') });
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editorService = accessor.get(IEditorService);
			const open = editorService.editors.find((e): e is OfficeToolsInput => e instanceof OfficeToolsInput);
			const input = open ?? new OfficeToolsInput(tool);
			input.tool = tool;
			const pane = await editorService.openEditor(input, { pinned: true });
			if (pane instanceof OfficeToolsEditor) {
				pane.show(tool);
			}
		}
	});
}
