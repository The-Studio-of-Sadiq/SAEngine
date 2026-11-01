/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize } from '../../../../nls.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { Extensions as OutputExtensions, IOutputChannelRegistry } from '../../../services/output/common/output.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { ISaengineProjectService, STRUCTURE_PART } from '../../../services/saengineProject/common/saengineProject.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { PLANNED_TAPERED_MEMBERS, SCRIPT_OUTPUT_CHANNEL_ID, StructureModelerEditor } from './structureModeler.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(StructureModelerEditor, StructureModelerEditor.ID, localize('structureModeler', "SAEngine Structural Model 3D")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IOutputChannelRegistry>(OutputExtensions.OutputChannels).registerChannel({
	id: SCRIPT_OUTPUT_CHANNEL_ID,
	label: localize('structureScripts', "SAEngine Scripts"),
	log: false,
});

/** Opens a special structure's `05 Structural Model/structure.json` in the 3D modeller. */
class StructureModelerResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.structureModelerResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			`**/${STRUCTURE_PART.mainFile}`,
			{
				id: StructureModelerEditor.ID,
				label: localize('structureModeler.label', "Structural Model 3D"),
				detail: localize('structureModeler.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isStructure(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(LibraryEditorInput, resource, 'structure', StructureModelerEditor.ID),
					options,
				}),
			}
		));
	}

	private isStructure(resource: URI): boolean {
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && this.projectService.project?.type !== 'building' && isEqual(resource, joinPath(root, STRUCTURE_PART.folder, STRUCTURE_PART.mainFile!));
	}
}

registerWorkbenchContribution2(StructureModelerResolverContribution.ID, StructureModelerResolverContribution, WorkbenchPhase.BlockStartup);

/** Undo and redo in the modeller undo and redo its edits to the file. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof StructureModelerEditor ? (pane.input as LibraryEditorInput | undefined)?.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 10000;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-structure-modeler', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-structure-modeler', accessor => undoRedo(accessor, true));

// ───────────────────────────── planned features ─────────────────────────────
// Remove a registration in the PR that builds its feature.

// T29: tapered (web-tapered) and haunched members of portal frames. BNBC 2020 Part 6 Chapter 10
// designs prismatic members only; web-tapered members need AISC Design Guide 25.
registerPlannedFeature({
	id: PLANNED_TAPERED_MEMBERS,
	part: 'structure',
	title: localize('planned.tapered.title', "Tapered and Haunched Members"),
	summary: localize('planned.tapered.summary', "Web-tapered columns and rafters and haunched rafter ends for portal frames (pre-engineered buildings): a depth that varies along the member, analysed as a chain of stepped elements and designed by a web-tapered member method. Today's portal frames use prismatic members."),
	steps: [
		localize('planned.tapered.step1', "Give a column or rafter type a start depth and an end depth (or a haunch length and depth at its ends)."),
		localize('planned.tapered.step2', "The analysis model splits each tapered member into short prismatic pieces with the depth at their middles."),
		localize('planned.tapered.step3', "The design checks every piece for local buckling, and the whole member for flexural and lateral-torsional buckling by the tapered member method."),
		localize('planned.tapered.step4', "The member schedule and the BOQ list the plate sizes along the member."),
	],
	inputs: [
		{ label: localize('planned.tapered.start', "Web depth at the start"), unit: 'mm', example: '300' },
		{ label: localize('planned.tapered.end', "Web depth at the end"), unit: 'mm', example: '900' },
		{ label: localize('planned.tapered.haunchLength', "Haunch length"), unit: 'mm', example: '2400' },
		{ label: localize('planned.tapered.pieces', "Analysis pieces per member"), example: '8' },
	],
	outputs: [
		localize('planned.tapered.out1', "Stepped analysis members along each tapered member"),
		localize('planned.tapered.out2', "Tapered member design ratios in the steel design table"),
		localize('planned.tapered.out3', "Plate schedule of the built-up members"),
	],
	references: [
		localize('planned.tapered.ref1', "BNBC 2020 Part 6 Chapter 10 (steel; prismatic members only)"),
		localize('planned.tapered.ref2', "AISC Design Guide 25: Frame Design Using Web-Tapered Members"),
		localize('planned.tapered.ref3', "AISC 360-16 Appendix 1 and Chapter C (stability of non-prismatic members)"),
	],
});
