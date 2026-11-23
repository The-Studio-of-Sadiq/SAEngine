/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
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
import { PLANNED_TAPERED_MEMBERS, SCRIPT_OUTPUT_CHANNEL_ID, StructureModelerEditor, StructureTool, StructureView } from './structureModeler.js';
import { defaultCodeName } from '../../../services/saengineProject/common/activeCodePack.js';
import { registerPartEditor } from '../../saengineProject/browser/projectParts.js';

async function activeStructureModelerEditor(accessor: ServicesAccessor): Promise<StructureModelerEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	if (editorService.activeEditorPane instanceof StructureModelerEditor) {
		return editorService.activeEditorPane;
	}
	const project = accessor.get(ISaengineProjectService).project;
	if (!project || !STRUCTURE_PART.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({
		resource: joinPath(project.root, STRUCTURE_PART.folder, STRUCTURE_PART.mainFile),
		options: { override: StructureModelerEditor.ID, pinned: true },
	});
	return pane instanceof StructureModelerEditor ? pane : undefined;
}

const structureProjectOpen = ContextKeyExpr.has('saengineProjectOpen');

function registerStructureCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	runWithEditor: (editor: StructureModelerEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.category', "SAEngine"),
				f1: true,
				precondition: structureProjectOpen,
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await activeStructureModelerEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
}

for (const [tool, title] of [
	['select', localize2('structure.cmd.select', "Structure 3D: Select")],
	['member', localize2('structure.cmd.member', "Structure 3D: Draw Member")],
	['area', localize2('structure.cmd.area', "Structure 3D: Draw Area")],
	['block', localize2('structure.cmd.block', "Structure 3D: Place Block")],
	['support', localize2('structure.cmd.support', "Structure 3D: Place Support")],
	['move', localize2('structure.cmd.move', "Structure 3D: Move Selection")],
	['copy', localize2('structure.cmd.copy', "Structure 3D: Copy Selection")],
	['mirror', localize2('structure.cmd.mirror', "Structure 3D: Mirror Selection")],
	['divide', localize2('structure.cmd.divide', "Structure 3D: Divide Member")],
	['delete', localize2('structure.cmd.delete', "Structure 3D: Delete Selection")],
] as readonly [StructureTool, ReturnType<typeof localize2>][]) {
	registerStructureCommand(`saengine.structure.tool.${tool}`, title, e => e.selectTool(tool));
}

for (const [view, title] of [
	['3d', localize2('structure.cmd.view3d', "Structure 3D: Isometric 3D View")],
	['top', localize2('structure.cmd.viewTop', "Structure 3D: Top Plan View")],
	['front', localize2('structure.cmd.viewFront', "Structure 3D: Front Elevation View")],
	['side', localize2('structure.cmd.viewSide', "Structure 3D: Side Elevation View")],
] as readonly [StructureView, ReturnType<typeof localize2>][]) {
	registerStructureCommand(`saengine.structure.view.${view}`, title, e => e.selectView(view));
}

registerStructureCommand('saengine.structure.fitView', localize2('structure.cmd.fit', "Structure 3D: Zoom to Fit"), e => e.fitView());
registerStructureCommand('saengine.structure.generateShape', localize2('structure.cmd.generateShape', "Structure 3D: Generate Parametric Shape..."), e => e.openShapeDialog());
registerStructureCommand('saengine.structure.importGeometry', localize2('structure.cmd.importGeometry', "Structure 3D: Import Geometry..."), e => e.openImportDialog());
registerStructureCommand('saengine.structure.runScript', localize2('structure.cmd.runScript', "Structure 3D: Run Python Script..."), e => e.openScriptPicker());
registerStructureCommand('saengine.structure.pickLevel', localize2('structure.cmd.pickLevel', "Structure 3D: Set Work Level..."), e => e.openLevelPicker());
registerStructureCommand('saengine.structure.openForm', localize2('structure.cmd.openForm', "Structure 3D: Edit Grids & Tables"), e => e.openGridsForm());

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
		this._register(registerPartEditor(STRUCTURE_PART.id, StructureModelerEditor.ID));
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
		localize('planned.tapered.ref1', "{0} Part 6 Chapter 10 (steel; prismatic members only)", defaultCodeName()),
		localize('planned.tapered.ref2', "AISC Design Guide 25: Frame Design Using Web-Tapered Members"),
		localize('planned.tapered.ref3', "AISC 360-16 Appendix 1 and Chapter C (stability of non-prismatic members)"),
	],
});
