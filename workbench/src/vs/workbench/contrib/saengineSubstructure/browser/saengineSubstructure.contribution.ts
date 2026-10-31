/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
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
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { SubstructureEditor } from './substructureEditor.js';
import { SubstructureEditorInput, SubstructureEditorInputSerializer } from './substructureEditorInput.js';

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

// Planned features of 9 Substructure (MVP: methods BNBC 2020 does not give itself).

registerPlannedFeature({
	id: 'substructure.lateralPileBroms',
	part: 'substructure',
	title: localize('planned.broms.title', "Lateral Pile Capacity (Broms)"),
	summary: localize('planned.broms.summary', "The ultimate lateral resistance of a single pile and of the group, short or long, free or fixed head, in cohesive and granular soil, from the soil report's layers; it will also give the depth to fixity the pile section is designed with."),
	steps: [
		localize('planned.broms.s1', "Take cu, φ' and the unit weights of the layers at the cap's nearest borehole from 1 Soil Report."),
		localize('planned.broms.s2', "Classify the pile as short or long and find its ultimate lateral load for the head fixity."),
		localize('planned.broms.s3', "Check the cap's horizontal force against the group's allowable lateral load."),
		localize('planned.broms.s4', "Fill in the depth to fixity and the largest shaft moment for the pile section design."),
	],
	inputs: [
		{ label: localize('planned.broms.i1', "Pile type"), example: 'P1 · Ø600' },
		{ label: localize('planned.broms.i2', "Head fixity"), example: localize('planned.broms.i2e', "Fixed in the cap") },
		{ label: localize('planned.broms.i3', "Factor of safety on lateral load"), example: '2.5' },
	],
	outputs: [
		localize('planned.broms.o1', "Allowable lateral load per pile and per group"),
		localize('planned.broms.o2', "Depth to fixity and the largest shaft moment"),
		localize('planned.broms.o3', "A lateral capacity check per pile cap in the report"),
	],
	references: [
		'Broms (1964), Lateral resistance of piles in cohesive / cohesionless soils, ASCE JSMFD',
		'BNBC 2020 Part 6 Chapter 3 (deep foundations)',
	],
});

registerPlannedFeature({
	id: 'substructure.lateralPilePy',
	part: 'substructure',
	title: localize('planned.py.title', "Laterally Loaded Piles (p-y Springs)"),
	summary: localize('planned.py.summary', "A pile modelled as a beam on nonlinear p-y springs from the soil layers, giving the head deflection, the moment and shear down the shaft and the depth to fixity, checked against a head deflection limit."),
	steps: [
		localize('planned.py.s1', "Build p-y curves for each layer (soft clay, stiff clay, sand) at the cap's nearest borehole."),
		localize('planned.py.s2', "Analyse the pile under the head shear and moment of each combination, fixed or free head."),
		localize('planned.py.s3', "Check the head deflection against the limit and design the section along the shaft."),
	],
	inputs: [
		{ label: localize('planned.py.i1', "Head deflection limit"), unit: 'mm', example: '12' },
		{ label: localize('planned.py.i2', "Spring spacing"), unit: 'mm', example: '250' },
		{ label: localize('planned.py.i3', "Cyclic loading"), example: localize('planned.py.i3e', "Static") },
	],
	outputs: [
		localize('planned.py.o1', "Deflection, moment and shear diagrams down the pile"),
		localize('planned.py.o2', "Head deflection check per pile cap"),
		localize('planned.py.o3', "Lateral springs at the pile heads for the building analysis"),
	],
	references: [
		'API RP 2GEO (p-y curves for clay and sand)',
		'Reese & Van Impe (2011), Single Piles and Pile Groups Under Lateral Loading',
		'OpenSees PySimple1 material',
	],
});

registerPlannedFeature({
	id: 'substructure.machineFoundation',
	part: 'substructure',
	title: localize('planned.machine.title', "Generator and Machine Foundations"),
	summary: localize('planned.machine.summary', "A block foundation for a generator, chiller or pump: its natural frequencies on the soil's dynamic springs kept clear of the machine's operating speed, and the vibration amplitude under the machine's unbalanced force kept within the limits."),
	steps: [
		localize('planned.machine.s1', "Enter the machine's mass, operating speed, unbalanced force and footprint."),
		localize('planned.machine.s2', "Size the block (mass ratio to the machine) and find the soil's dynamic springs and damping from the soil report."),
		localize('planned.machine.s3', "Compute the natural frequencies in each mode and the frequency ratios."),
		localize('planned.machine.s4', "Compute the amplitudes at the operating speed and check them against the limits; check bearing under the static load."),
	],
	inputs: [
		{ label: localize('planned.machine.i1', "Machine mass"), unit: 't', example: '6.5' },
		{ label: localize('planned.machine.i2', "Operating speed"), unit: 'rpm', example: '1500' },
		{ label: localize('planned.machine.i3', "Unbalanced force"), unit: 'kN', example: '2.0' },
		{ label: localize('planned.machine.i4', "Allowable amplitude"), unit: 'μm', example: '50' },
	],
	outputs: [
		localize('planned.machine.o1', "Block size and weight"),
		localize('planned.machine.o2', "Natural frequencies and frequency ratios per mode"),
		localize('planned.machine.o3', "Vibration amplitudes against the limits, in the report"),
	],
	references: [
		'ACI 351.3R (foundations for dynamic equipment)',
		'Richart, Hall & Woods (1970), Vibrations of Soils and Foundations',
		'BNBC 2020 Part 6 Chapter 3 (shallow foundations: bearing)',
	],
});

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
		localize('planned.piledRaft.o2', "Settlement and differential settlement against BNBC Table 6.3.8"),
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
	summary: localize('planned.groupInteraction.summary', "The settlement of each pile of a group from elastic interaction factors, so a cap's differential settlement and its piles' load sharing are found, in addition to the equivalent-raft group settlement of BNBC Sec 3.10.5 that is checked now."),
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
		'BNBC 2020 Part 6 Sec 3.10.5 (equivalent raft, checked now)',
	],
});
