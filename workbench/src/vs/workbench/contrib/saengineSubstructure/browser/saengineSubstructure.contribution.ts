/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './substructureDataPanels.contribution.js';
import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { OPEN_PLANNED_FEATURE_COMMAND } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { SubstructureEditor } from './substructureEditor.js';
import { SubstructureEditorInput, SubstructureEditorInputSerializer } from './substructureEditorInput.js';
import { defaultCodeName } from '../../../services/saengineProject/common/activeCodePack.js';
import { registerPartEditor } from '../../saengineProject/browser/projectParts.js';

/** Opens the substructure editor and sizes all foundations (the sizing assistant). */
export const SUBSTRUCTURE_SIZE_ALL_COMMAND = 'saengine.substructure.sizeAll';
/** Opens the substructure editor and imports the building model's footings. */
export const SUBSTRUCTURE_IMPORT_FOOTINGS_COMMAND = 'saengine.substructure.importFootings';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SubstructureEditor, SubstructureEditor.ID, localize('substructureEditorPane', "SAEngine Substructure")),
	[new SyncDescriptor(SubstructureEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(SubstructureEditorInput.ID, SubstructureEditorInputSerializer);

/** Opens the project's `09 Substructure/substructure.json` in the substructure editor. */
class SubstructureEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.substructureEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('substructure');
		if (!part?.mainFile) {
			return;
		}
		this._register(registerPartEditor(part.id, SubstructureEditor.ID));
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: SubstructureEditor.ID,
				label: localize('substructureEditor.label', "Substructure"),
				detail: localize('substructureEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isSubstructure(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(SubstructureEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isSubstructure(resource: URI): boolean {
		const part = partById('substructure');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(SubstructureEditorResolverContribution.ID, SubstructureEditorResolverContribution, WorkbenchPhase.BlockStartup);

/**
 * Ctrl+Z / Ctrl+Y in the substructure editor undo the file's text edits; inside a text field the
 * field's own undo still applies.
 */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof SubstructureEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

UndoCommand.addImplementation(110, 'saengine-substructure', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-substructure', accessor => undoRedo(accessor, true));

/** The substructure editor, opened on the project's file if it is not the active editor. */
async function substructureEditor(accessor: ServicesAccessor): Promise<SubstructureEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	const project = accessor.get(ISaengineProjectService).project;
	if (editorService.activeEditorPane instanceof SubstructureEditor) {
		return editorService.activeEditorPane;
	}
	const part = partById('substructure');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof SubstructureEditor ? pane : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SUBSTRUCTURE_SIZE_ALL_COMMAND,
			title: localize2('saengine.substructure.sizeAll', "Size Footings"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.wand,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await (await substructureEditor(accessor))?.sizeAll();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SUBSTRUCTURE_IMPORT_FOOTINGS_COMMAND,
			title: localize2('saengine.substructure.importFootings', "Import Footings from the Building Model into the Substructure"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.cloudDownload,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await (await substructureEditor(accessor))?.migrate();
	}
});

function registerFoundationCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	icon: ThemeIcon,
	runWithEditor: (editor: SubstructureEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.category', "SAEngine"),
				icon,
				f1: true,
				precondition: ContextKeyExpr.has('saengineProjectOpen'),
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await substructureEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
}

registerFoundationCommand('saengine.substructure.addFooting', localize2('fdn.rib.addFootingTitle', "Add Footing under Selected Columns"), Codicon.add, e => e.addFootings());
registerFoundationCommand('saengine.substructure.addRaft', localize2('fdn.rib.addRaftTitle', "Add Raft Foundation"), Codicon.primitiveSquare, e => e.addRaft());
registerFoundationCommand('saengine.substructure.addStrip', localize2('fdn.rib.addStripTitle', "Add Strip Footing"), Codicon.layoutPanel, e => e.addStrip());
registerFoundationCommand('saengine.substructure.selectUncovered', localize2('fdn.rib.uncoveredTitle', "Select Columns without a Foundation"), Codicon.selection, e => e.selectUncovered());

registerFoundationCommand('saengine.substructure.addPileCap', localize2('fdn.rib.addCapTitle', "Add Pile Cap under Selected Columns"), Codicon.circleLargeOutline, e => e.addPileCaps());
registerFoundationCommand('saengine.substructure.placePiles', localize2('fdn.rib.placePilesTitle', "Place Piles Tool"), Codicon.circleFilled, e => e.togglePileTool());
registerFoundationCommand('saengine.substructure.pileGrid', localize2('fdn.rib.pileGridTitle', "Edit Pile Grid"), Codicon.symbolNumeric, e => e.editPileGrid());
registerFoundationCommand('saengine.substructure.pileGroup', localize2('fdn.rib.pileGroupTitle', "Place Pile Group under Selected Columns"), Codicon.location, e => e.placeGroups());
registerFoundationCommand('saengine.substructure.makeCap', localize2('fdn.rib.makeCapTitle', "Make Pile Cap from Selected Piles"), Codicon.package, e => e.makeCap());
registerFoundationCommand('saengine.substructure.addPileType', localize2('fdn.rib.addPileTypeTitle', "Add Pile Type"), Codicon.newFile, e => e.addPileType());

registerFoundationCommand('saengine.substructure.gradeBeam', localize2('fdn.rib.gradeBeamTitle', "Draw Grade Beam Tool"), Codicon.arrowBoth, e => e.toggleBeamTool());
registerFoundationCommand('saengine.substructure.addTieBeam', localize2('fdn.rib.addTieTitle', "Add Tie Beam between Selected Foundations"), Codicon.dash, e => e.addTieBeam());
registerFoundationCommand('saengine.substructure.connectBeams', localize2('fdn.rib.connectTitle', "Connect Grade Beams along Grid Lines"), Codicon.gitMerge, e => e.connectBeams());
registerFoundationCommand('saengine.substructure.delete', localize2('fdn.rib.deleteTitle', "Delete Selected Foundation or Pile"), Codicon.trash, e => e.deleteSelection());

registerFoundationCommand('saengine.substructure.saveAndCheck', localize2('fdn.rib.saveCheckTitle', "Save and Check Foundations"), Codicon.checkAll, e => e.saveAndCheck());
registerFoundationCommand('saengine.substructure.recompute', localize2('fdn.rib.recomputeTitle', "Check Foundations Again"), Codicon.refresh, e => e.computeReport());

registerFoundationCommand('saengine.substructure.viewPlan', localize2('fdn.rib.viewPlanTitle', "Substructure View: Plan"), Codicon.symbolStructure, e => e.showView('plan'));
registerFoundationCommand('saengine.substructure.viewData', localize2('fdn.rib.viewDataTitle', "Substructure View: Data"), Codicon.table, e => e.showView('data'));
registerFoundationCommand('saengine.substructure.viewResults', localize2('fdn.rib.viewResultsTitle', "Substructure View: Results"), Codicon.graphLine, e => e.showView('results'));

registerFoundationCommand('saengine.substructure.addRetainingWall', localize2('fdn.rib.addRetWallTitle', "Add Retaining Wall"), Codicon.layoutSidebarLeft, e => e.addRetainingWall());
registerFoundationCommand('saengine.substructure.addExcavation', localize2('fdn.rib.addExcTitle', "Add Excavation Support"), Codicon.debugPause, e => e.addExcavation());
registerFoundationCommand('saengine.substructure.addSlope', localize2('fdn.rib.addSlopeTitle', "Add Slope Stability Entry"), Codicon.graph, e => e.addSlope());
registerFoundationCommand('saengine.substructure.addGroundSlab', localize2('fdn.rib.addGSlabTitle', "Add Slab on Grade"), Codicon.browser, e => e.addGroundSlab());
registerFoundationCommand('saengine.substructure.addMachine', localize2('fdn.rib.addMachineTitle', "Add Machine Foundation"), Codicon.settingsGear, e => e.addMachineFoundation());

for (const [id, title, featureId] of [
	['saengine.substructure.piledRaft', localize2('fdn.rib.piledRaftTitle', "Piled Raft Interaction (Planned)"), 'substructure.piledRaft'],
	['saengine.substructure.pileGroupInteraction', localize2('fdn.rib.groupIntTitle', "Pile Group Interaction Factors (Planned)"), 'substructure.pileGroupInteraction'],
] as const) {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.category', "SAEngine"),
				icon: Codicon.lightbulb,
				f1: true,
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			await accessor.get(ICommandService).executeCommand(OPEN_PLANNED_FEATURE_COMMAND, featureId);
		}
	});
}

// Planned features of 9 Substructure (MVP: methods BNBC 2020 does not give itself).

registerPlannedFeature({
	id: 'substructure.piledRaft',
	part: 'substructure',
	title: localize('planned.piledRaft.title', "Piled Raft"),
	summary: localize('planned.piledRaft.summary', "A raft and its piles sharing the load: the raft on the soil's springs and the piles as springs of their own, with the interaction between them, so fewer piles carry the building within the settlement limits."),
	steps: [
		localize('planned.piledRaft.s1', "Place the piles under a raft of 9 Substructure."),
		localize('planned.piledRaft.s2', "Model the raft on soil springs and the piles as nonlinear springs with pile-soil-pile and pile-raft interaction."),
		localize('planned.piledRaft.s3', "Find the share of the load the piles carry, the settlements and the raft's moments."),
	],
	inputs: [
		{ label: localize('planned.piledRaft.i1', "Pile spring model"), example: localize('planned.piledRaft.i1e', "Load-transfer (t-z, q-z)") },
		{ label: localize('planned.piledRaft.i2', "Target pile share"), unit: '%', example: '60' },
	],
	outputs: [
		localize('planned.piledRaft.o1', "Pile loads and the raft's contact pressure"),
		localize('planned.piledRaft.o2', "Settlement and differential settlement against {0} Table 6.3.8", defaultCodeName()),
		localize('planned.piledRaft.o3', "Raft moments and pile design forces"),
	],
	references: [
		'Poulos (2001), Piled raft foundations: design and applications, Géotechnique 51(2)',
		'ISSMGE Combined Pile-Raft Foundation Guideline (2013)',
	],
});

registerPlannedFeature({
	id: 'substructure.pileGroupInteraction',
	part: 'substructure',
	title: localize('planned.groupInteraction.title', "Pile Group Settlement by Interaction Factors"),
	summary: localize('planned.groupInteraction.summary', "The settlement of each pile of a group from elastic interaction factors, so a cap's differential settlement and its piles' load sharing are found, in addition to the settlement checked now: each pile's own (axial shortening, tip and skin friction), the group's short-term settlement by its width or number of piles, and its long-term settlement as an equivalent raft. The code pack gives no interaction factors."),
	steps: [
		localize('planned.groupInteraction.s1', "Find each pile's single-pile settlement under its load from the soil's modulus."),
		localize('planned.groupInteraction.s2', "Add the interaction of the other piles by their spacing (interaction factors)."),
		localize('planned.groupInteraction.s3', "Solve for the loads of a rigid cap or the settlements of a flexible one."),
	],
	inputs: [
		{ label: localize('planned.groupInteraction.i1', "Soil modulus"), unit: 'MPa', example: '30' },
		{ label: localize('planned.groupInteraction.i2', "Cap"), example: localize('planned.groupInteraction.i2e', "Rigid") },
	],
	outputs: [
		localize('planned.groupInteraction.o1', "Settlement of each pile and the cap's tilt"),
		localize('planned.groupInteraction.o2', "Group settlement ratio and efficiency"),
	],
	references: [
		'Poulos & Davis (1980), Pile Foundation Analysis and Design',
		`Default code pack, ${defaultCodeName()} Part 6 Sec 3.10.5 (single pile, group ratio and equivalent raft, checked now; no interaction factors)`,
	],
});
