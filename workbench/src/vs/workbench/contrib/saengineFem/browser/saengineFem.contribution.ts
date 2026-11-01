/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { PROJECT_MENU, ProjectOpenContext } from '../../saengineProject/browser/projectMenu.js';
import { DESIGN_REINFORCEMENT_COMMAND, PLANNED_STM_GENERAL } from './femDesign.js';
import { FemPlanned } from './femPlannedFeatures.js';
import { FemDesignProposalEditor } from './femDesignProposalEditor.js';
import { FemDesignProposalInput, FemDesignProposalInputSerializer } from './femDesignProposalInput.js';
import { FemModelEditor } from './femModelEditor.js';
import { FemModelEditorInput, FemModelEditorInputSerializer } from './femModelEditorInput.js';
import { FEM_SHOW_CHARTS_COMMAND, FEM_SHOW_MEMBER_COMMAND } from './femResultsBar.js';
import { FemResultsEditor, FemResultsInput, FemResultsInputSerializer, IFemResultsEditorOptions, memberNames } from './femResultsView.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(
		FemModelEditor,
		FemModelEditorInput.EDITOR_ID,
		localize('femModelEditor', "FEM Model")
	),
	[
		new SyncDescriptor(FemModelEditorInput)
	]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(
	FemModelEditorInput.ID,
	FemModelEditorInputSerializer
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(FemDesignProposalEditor, FemDesignProposalInput.EDITOR_ID, localize('femDesignProposalEditor', "Design Reinforcement")),
	[new SyncDescriptor(FemDesignProposalInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FemDesignProposalInput.ID, FemDesignProposalInputSerializer);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(FemResultsEditor, FemResultsInput.EDITOR_ID, localize('femResultsEditor', "Analysis Results")),
	[new SyncDescriptor(FemResultsInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FemResultsInput.ID, FemResultsInputSerializer);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FemResultsInput.MEMBER_ID, FemResultsInputSerializer);

/** The project's analysis model (`08 FEM/model.osmodel`), or `model` when given. */
function analysisModel(accessor: ServicesAccessor, model: unknown): URI | undefined {
	const project = accessor.get(ISaengineProjectService).project;
	const fem = partById('fem');
	return URI.isUri(model) ? model : project && fem?.mainFile ? joinPath(project.root, fem.folder, fem.mainFile) : undefined;
}

/**
 * Opens the Analysis Charts of the last run of `model` (by default the project's analysis
 * model): storey response, modal participation, spectrum, base reactions, curves.
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: FEM_SHOW_CHARTS_COMMAND,
			title: localize2('saengine.fem.showCharts', "Show Analysis Charts"),
			metadata: { description: localize2('saengine.fem.showCharts.description', "Storey displacements, drifts, shears, forces and overturning, modal participation and the design spectrum of the last analysis run. Argument: the analysis model (URI); by default the project's.") },
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.graph,
			f1: true,
			precondition: ProjectOpenContext,
			menu: { id: PROJECT_MENU, group: '1_project', order: 5 },
		});
	}

	override async run(accessor: ServicesAccessor, model?: URI): Promise<void> {
		const target = analysisModel(accessor, model);
		if (target) {
			await accessor.get(IEditorService).openEditor(new FemResultsInput(target, { kind: 'charts' }), { pinned: true });
		}
	}
});

/**
 * Picks a frame member of the analysis model (by name: `B1`, `C3`, ...) and opens its details:
 * the keyboard's way to what a click on a member in the 3D view offers.
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.fem.pickMember',
			title: localize2('saengine.fem.pickMember', "Show Member Details..."),
			metadata: { description: localize2('saengine.fem.pickMember.description', "Forces and deflection along a beam, column or brace for each case, combination or the envelope; a column's P-M interaction diagram; a beam's required and provided steel.") },
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
			precondition: ProjectOpenContext,
		});
	}

	override async run(accessor: ServicesAccessor, model?: URI): Promise<void> {
		const target = analysisModel(accessor, model);
		const quickInputService = accessor.get(IQuickInputService);
		const editorService = accessor.get(IEditorService);
		if (!target) {
			return;
		}
		let members: string[] = [];
		try {
			const parsed = JSON.parse((await accessor.get(IFileService).readFile(target)).value.toString());
			members = memberNames(parsed?.elements ?? []);
		} catch {
			members = [];
		}
		const picked = await quickInputService.pick(members.map<IQuickPickItem>(label => ({ label })), {
			placeHolder: members.length ? localize('saengine.fem.pickMember.placeholder', "Member to show (beams, columns, braces of the analysis model)") : localize('saengine.fem.pickMember.none', "The analysis model has no frame members: derive it first."),
		});
		if (picked) {
			await editorService.openEditor(new FemResultsInput(target, { kind: 'member', member: picked.label }), { pinned: true });
		}
	}
});

/**
 * `(model: URI, member: string, result?: string)`: opens a member's details (forces along it,
 * P-M, steel) at `result`, the label of the case or combination the 3D view shows. Internal.
 */
CommandsRegistry.registerCommand(FEM_SHOW_MEMBER_COMMAND, async (accessor, model: URI, member: string, result?: string) => {
	if (URI.isUri(model) && typeof member === 'string' && member) {
		const options: IFemResultsEditorOptions = { pinned: true, result: typeof result === 'string' ? result : undefined };
		await accessor.get(IEditorService).openEditor(new FemResultsInput(model, { kind: 'member', member }), options);
	}
});

/**
 * Opens Design Reinforcement: bars proposed for the object types from the last analysis run of
 * `model` (by default the project's `08 FEM/model.osmodel`).
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: DESIGN_REINFORCEMENT_COMMAND,
			title: localize2('saengine.designReinforcement', "Design Reinforcement"),
			metadata: { description: localize2('saengine.designReinforcement.description', "Proposes bars for the object types from the steel their members require, and applies them to 04 Objects. Argument: the analysis model (URI); by default the project's.") },
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.symbolRuler,
			f1: true,
			precondition: ProjectOpenContext,
			menu: { id: PROJECT_MENU, group: '1_project', order: 6 },
		});
	}

	override async run(accessor: ServicesAccessor, model?: URI): Promise<void> {
		const target = analysisModel(accessor, model);
		if (target) {
			await accessor.get(IEditorService).openEditor(new FemDesignProposalInput(target), { pinned: true });
		}
	}
});

class FemModelEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.femModelEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
	) {
		super();

		this._register(editorResolverService.registerEditor(
			'*.osmodel',
			{
				id: FemModelEditorInput.EDITOR_ID,
				label: localize('femModelEditor.label', "FEM Model Viewport"),
				detail: localize('femModelEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default
			},
			{
				singlePerResource: true
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: new FemModelEditorInput(resource),
					options
				})
			}
		));
	}
}

registerWorkbenchContribution2(FemModelEditorResolverContribution.ID, FemModelEditorResolverContribution, WorkbenchPhase.BlockStartup);

// ───────────────────────────── planned features ─────────────────────────────
// Analyses and designs that need a guide beyond BNBC 2020: shown, not computed, in this MVP.
// Remove a registration in the PR that builds its feature.

// T17: staged construction, creep, shrinkage and column shortening.
registerPlannedFeature({
	id: FemPlanned.stagedConstruction,
	part: 'fem',
	title: localize('planned.staged.title', "Staged Construction"),
	summary: localize('planned.staged.summary', "Builds the model storey by storey in time, with every gravity load applied as it arrives (self-weight, finishes, partitions, live load), and adds or removes members and supports at each stage. Today's staged case is linear and carries self-weight only."),
	steps: [
		localize('planned.staged.step1', "Define the stages from the storeys: the members, supports and loads added or removed at each, and its duration."),
		localize('planned.staged.step2', "Analyse the stages in sequence, each on the structure built so far, with time-dependent effects if chosen."),
		localize('planned.staged.step3', "Review the forces and deflections at every stage on the stage slider."),
		localize('planned.staged.step4', "Optionally use the final staged gravity state in place of the one-step gravity case in design."),
	],
	inputs: [
		{ label: localize('planned.staged.cycle', "Floor cycle"), unit: localize('planned.unit.days', "days") },
		{ label: localize('planned.staged.loads', "Loads applied per stage"), example: localize('planned.staged.loadsExample', "Self-weight, finishes, partitions") },
		{ label: localize('planned.staged.design', "Use in design"), example: localize('planned.staged.designExample', "Staged gravity state") },
	],
	outputs: [
		localize('planned.staged.out1', "Forces and deflections per stage in the results bar"),
		localize('planned.staged.out2', "Staged gravity cases for the design checks"),
		localize('planned.staged.out3', "A staged construction section in the design report"),
	],
	references: [
		localize('planned.staged.ref1', "BNBC 2020 Part 6 Chapter 6 (concrete; it gives no staged analysis procedure)"),
		localize('planned.staged.ref2', "ACI 209.2R-08 (time-dependent effects in concrete)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.creepShrinkage,
	part: 'fem',
	title: localize('planned.creep.title', "Creep and Shrinkage"),
	summary: localize('planned.creep.summary', "Adds the creep and shrinkage of concrete to the staged analysis by a chosen time-dependent model, so that forces redistribute and deflections grow with time."),
	steps: [
		localize('planned.creep.step1', "Pick the creep and shrinkage model, and the curing and exposure."),
		localize('planned.creep.step2', "Give each concrete its age at loading from the stages."),
		localize('planned.creep.step3', "Run the staged analysis with the model up to the chosen service life."),
	],
	inputs: [
		{ label: localize('planned.creep.model', "Model"), example: localize('planned.creep.modelExample', "ACI 209 or CEB-FIP") },
		{ label: localize('planned.creep.humidity', "Relative humidity"), unit: '%' },
		{ label: localize('planned.creep.curing', "Moist curing"), unit: localize('planned.unit.days', "days") },
		{ label: localize('planned.creep.life', "Service life"), unit: localize('planned.unit.years', "years") },
	],
	outputs: [
		localize('planned.creep.out1', "Long-term deflections and redistributed forces"),
		localize('planned.creep.out2', "Creep coefficient and shrinkage strain curves per concrete"),
	],
	references: [
		localize('planned.creep.ref1', "ACI 209.2R-08"),
		localize('planned.creep.ref2', "CEB-FIP Model Code 1990; fib Model Code 2010"),
	],
});
registerPlannedFeature({
	id: FemPlanned.columnShortening,
	part: 'fem',
	title: localize('planned.shortening.title', "Column Shortening"),
	summary: localize('planned.shortening.summary', "Works out the elastic, creep and shrinkage shortening of columns and walls storey by storey, and the differential shortening between neighbours that loads the beams and slabs between them."),
	steps: [
		localize('planned.shortening.step1', "Run the staged analysis with creep and shrinkage."),
		localize('planned.shortening.step2', "Read each vertical member's shortening per storey, at casting and at the end of the service life."),
		localize('planned.shortening.step3', "Compare neighbouring columns and walls, and give the level compensation to build in per storey."),
	],
	outputs: [
		localize('planned.shortening.out1', "Shortening per column and storey (elastic, creep, shrinkage)"),
		localize('planned.shortening.out2', "Differential shortening between neighbours, and the compensation per storey"),
	],
	references: [
		localize('planned.shortening.ref1', "ACI 209.2R-08"),
		localize('planned.shortening.ref2', "Fintel, Ghosh and Iyengar, Column Shortening in Tall Structures (PCA, 1987)"),
	],
});

// T21: pushover acceptance criteria and performance point.
registerPlannedFeature({
	id: FemPlanned.pushoverHinges,
	part: 'fem',
	title: localize('planned.hinges.title', "Pushover Hinges and Acceptance"),
	summary: localize('planned.hinges.summary', "Gives beams and columns plastic hinges with performance-based backbone curves, and checks each hinge's rotation against the Immediate Occupancy, Life Safety and Collapse Prevention limits. Today's pushover uses fibre frames and gives the capacity curve only."),
	steps: [
		localize('planned.hinges.step1', "Assign hinges to the members from their sections, bars and axial load."),
		localize('planned.hinges.step2', "Run the pushover with the hinges."),
		localize('planned.hinges.step3', "Colour the hinges in the view by state (B, IO, LS, CP, C, E) at each step."),
		localize('planned.hinges.step4', "Report each hinge's rotation against its acceptance limit at the performance point."),
	],
	inputs: [
		{ label: localize('planned.hinges.target', "Target performance level"), example: localize('planned.hinges.targetExample', "Life Safety") },
		{ label: localize('planned.hinges.knowledge', "Knowledge factor") },
	],
	outputs: [
		localize('planned.hinges.out1', "Hinge states in the 3D view, step by step"),
		localize('planned.hinges.out2', "A hinge acceptance table"),
		localize('planned.hinges.out3', "A pushover section in the design report"),
	],
	references: [
		localize('planned.hinges.ref1', "BNBC 2020 Part 6 Sec 2.5 (earthquake loads, pp. 609-648)"),
		localize('planned.hinges.ref2', "ASCE/SEI 41-17 Ch 7 and Ch 10 (nonlinear procedures; concrete hinges and acceptance)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.fibreWalls,
	part: 'fem',
	title: localize('planned.fibreWalls.title', "Fibre Walls in Pushover"),
	summary: localize('planned.fibreWalls.summary', "Models shear walls with fibre sections (confined and unconfined concrete, bars) in the pushover model, so walls crack and yield instead of staying elastic."),
	steps: [
		localize('planned.fibreWalls.step1', "Mesh each wall into fibre wall elements from its section and bars."),
		localize('planned.fibreWalls.step2', "Run the pushover with the walls nonlinear."),
		localize('planned.fibreWalls.step3', "Check wall strains and shear against the acceptance limits."),
	],
	outputs: [
		localize('planned.fibreWalls.out1', "Wall strains and pier forces per step"),
		localize('planned.fibreWalls.out2', "Wall acceptance in the hinge table"),
	],
	references: [
		localize('planned.fibreWalls.ref1', "ASCE/SEI 41-17 Sec 10.7 (concrete shear walls)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.performancePoint,
	part: 'fem',
	title: localize('planned.perfPoint.title', "Performance Point"),
	summary: localize('planned.perfPoint.summary', "Finds where the capacity curve meets the demand of the project's design spectrum, by the N2 method or the FEMA 440 improved procedures, and gives the target displacement at which the hinges are checked."),
	steps: [
		localize('planned.perfPoint.step1', "Convert the capacity curve to the equivalent single-degree-of-freedom system."),
		localize('planned.perfPoint.step2', "Take the demand from the project's design spectrum."),
		localize('planned.perfPoint.step3', "Find the performance point by the chosen method, and mark it on the capacity curve."),
	],
	inputs: [
		{ label: localize('planned.perfPoint.method', "Method"), example: localize('planned.perfPoint.methodExample', "N2 or FEMA 440 equivalent linearisation") },
		{ label: localize('planned.perfPoint.hazard', "Hazard level"), example: localize('planned.perfPoint.hazardExample', "Design earthquake") },
	],
	outputs: [
		localize('planned.perfPoint.out1', "The performance point on the capacity curve chart"),
		localize('planned.perfPoint.out2', "Target displacement, effective period and damping"),
	],
	references: [
		localize('planned.perfPoint.ref1', "EN 1998-1:2004 Annex B (N2 method)"),
		localize('planned.perfPoint.ref2', "FEMA 440 (2005); ATC-40 (1996)"),
	],
});

// T22: assessment and retrofit of existing RC buildings.
registerPlannedFeature({
	id: FemPlanned.existingAssessment,
	part: 'fem',
	title: localize('planned.assessment.title', "Assessment of Existing Buildings"),
	summary: localize('planned.assessment.summary', "Checks an existing RC building as built: the strengths from tests, the bars found on site, a knowledge factor for how much is known, and the member checks against the chosen performance objective."),
	steps: [
		localize('planned.assessment.step1', "Enter the as-built strengths from cores and rebound tests, and the bars found by scanning or from drawings."),
		localize('planned.assessment.step2', "Choose the knowledge level from the data collected."),
		localize('planned.assessment.step3', "Analyse with the expected strengths, linearly or by pushover."),
		localize('planned.assessment.step4', "List the deficient members and the building's overall rating."),
	],
	inputs: [
		{ label: localize('planned.assessment.fc', "Core strength"), unit: localize('planned.unit.mpa', "MPa") },
		{ label: localize('planned.assessment.fy', "Bar yield strength"), unit: localize('planned.unit.mpa', "MPa") },
		{ label: localize('planned.assessment.level', "Knowledge level"), example: localize('planned.assessment.levelExample', "Usual") },
		{ label: localize('planned.assessment.target', "Performance objective"), example: localize('planned.assessment.targetExample', "Life Safety") },
	],
	outputs: [
		localize('planned.assessment.out1', "Deficient members coloured in the 3D view"),
		localize('planned.assessment.out2', "An assessment report"),
	],
	references: [
		localize('planned.assessment.ref1', "BNBC 2020 Part 6 Chapter 6, and Chapter 8 Sec 8.3 (pp. 1088-1122), for new members"),
		localize('planned.assessment.ref2', "ASCE/SEI 41-17 Ch 3, 6 and 10 (evaluation, data collection and knowledge factor, concrete)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.retrofit,
	part: 'fem',
	title: localize('planned.retrofit.title', "Retrofit of Existing Buildings"),
	summary: localize('planned.retrofit.summary', "Strengthens the deficient members of an assessed building by RC or steel jacketing, FRP wraps and strips, or added shear walls and braces, then assesses the building again with them."),
	steps: [
		localize('planned.retrofit.step1', "Pick the deficient members from the assessment."),
		localize('planned.retrofit.step2', "Apply a scheme to each: jacket, FRP, or add walls or braces to the model."),
		localize('planned.retrofit.step3', "Design the strengthening, then run the assessment again."),
		localize('planned.retrofit.step4', "Issue the retrofit report and details."),
	],
	inputs: [
		{ label: localize('planned.retrofit.scheme', "Scheme"), example: localize('planned.retrofit.schemeExample', "RC jacket, FRP wrap, added wall") },
		{ label: localize('planned.retrofit.frp', "FRP system"), example: localize('planned.retrofit.frpExample', "Carbon sheet") },
	],
	outputs: [
		localize('planned.retrofit.out1', "Strengthened members and their checks"),
		localize('planned.retrofit.out2', "Re-assessment against the objective"),
		localize('planned.retrofit.out3', "A retrofit report and jacketing details"),
	],
	references: [
		localize('planned.retrofit.ref1', "ACI 440.2R-17 (externally bonded FRP)"),
		localize('planned.retrofit.ref2', "ACI 369.1-17 (seismic evaluation and retrofit of concrete buildings)"),
		localize('planned.retrofit.ref3', "ASCE/SEI 41-17 (retrofit measures)"),
	],
});

// T35: nonlinear time history.
registerPlannedFeature({
	id: FemPlanned.nonlinearTimeHistory,
	part: 'fem',
	title: localize('planned.nlth.title', "Nonlinear Time History"),
	summary: localize('planned.nlth.summary', "Runs ground-motion records through the model with its hinges and fibre members by direct integration, so members yield during the shaking. Today's time history is linear."),
	steps: [
		localize('planned.nlth.step1', "Pick a suite of records and scale them to the design spectrum."),
		localize('planned.nlth.step2', "Run each record with the nonlinear members and the chosen damping."),
		localize('planned.nlth.step3', "Play the response with the hinge states, and read the peak drifts and forces."),
	],
	inputs: [
		{ label: localize('planned.nlth.records', "Records"), example: localize('planned.nlth.recordsExample', "A suite from the record library") },
		{ label: localize('planned.nlth.damping', "Damping ratio"), unit: '%' },
		{ label: localize('planned.nlth.step', "Time step"), unit: localize('planned.unit.s', "s") },
	],
	outputs: [
		localize('planned.nlth.out1', "Displacement, drift and hinge histories per record"),
		localize('planned.nlth.out2', "Peak and mean response over the suite"),
	],
	references: [
		localize('planned.nlth.ref1', "BNBC 2020 Part 6 Sec 2.5 (earthquake loads, pp. 609-648)"),
		localize('planned.nlth.ref2', "ASCE/SEI 7-16 Ch 16 (nonlinear response history)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.recordScaling,
	part: 'fem',
	title: localize('planned.records.title', "Record Search and Spectral Matching"),
	summary: localize('planned.records.summary', "Picks ground-motion records from open databases, with their licences checked, and matches them in the time domain to the project's design spectrum. Scaling a suite to the code spectrum is built: Project Settings, Analysis, Time histories (Scaling). The code pack gives no method for matching or for choosing records, so this part stays planned."),
	steps: [
		localize('planned.records.step1', "Search an open record database by magnitude, distance and site class."),
		localize('planned.records.step2', "Match each record to the design spectrum in the time domain."),
		localize('planned.records.step3', "Check the matched suite with the same criterion as the scaled one."),
	],
	inputs: [
		{ label: localize('planned.records.range', "Period range"), unit: localize('planned.unit.s', "s") },
		{ label: localize('planned.records.method', "Method"), example: localize('planned.records.methodExample', "Spectral matching in the time domain") },
	],
	outputs: [
		localize('planned.records.out1', "Matched records with their source and licence"),
	],
	references: [
		localize('planned.records.ref1', "ASCE/SEI 7-16 Sec 16.2 (ground motion selection and modification)"),
		localize('planned.records.ref2', "Al Atik and Abrahamson (2010), spectral matching in the time domain"),
	],
});

// T36: base isolators and dampers.
registerPlannedFeature({
	id: FemPlanned.baseIsolation,
	part: 'fem',
	title: localize('planned.isolation.title', "Base Isolation"),
	summary: localize('planned.isolation.summary', "Places lead-rubber or friction-pendulum isolators below the columns and walls, from the solver's bundled isolator catalog, and designs the isolated building for the displacements and forces of the isolation system."),
	steps: [
		localize('planned.isolation.step1', "Place an isolation plane, and pick the isolator type and size at each support."),
		localize('planned.isolation.step2', "Work out the effective stiffness, damping and design displacement."),
		localize('planned.isolation.step3', "Analyse with the upper- and lower-bound isolator properties."),
		localize('planned.isolation.step4', "Check the isolators, and design the superstructure for the reduced forces."),
	],
	inputs: [
		{ label: localize('planned.isolation.type', "Isolator type"), example: localize('planned.isolation.typeExample', "Lead-rubber or friction pendulum") },
		{ label: localize('planned.isolation.period', "Target isolated period"), unit: localize('planned.unit.s', "s") },
	],
	outputs: [
		localize('planned.isolation.out1', "An isolator schedule and its checks"),
		localize('planned.isolation.out2', "Design displacements and the isolated base shear"),
	],
	references: [
		localize('planned.isolation.ref1', "BNBC 2020 Part 6 Sec 2.5 (earthquake loads, pp. 609-648)"),
		localize('planned.isolation.ref2', "ASCE/SEI 7-16 Ch 17 (seismically isolated structures)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.dampers,
	part: 'fem',
	title: localize('planned.dampers.title', "Viscous Dampers"),
	summary: localize('planned.dampers.summary', "Adds fluid viscous dampers in braces or between storeys, from the solver's bundled damper catalog, and sizes them for the added damping the building needs."),
	steps: [
		localize('planned.dampers.step1', "Place the dampers in the chosen bays."),
		localize('planned.dampers.step2', "Size them for a target added damping."),
		localize('planned.dampers.step3', "Check the drifts, and the damper forces and strokes, by time history."),
	],
	inputs: [
		{ label: localize('planned.dampers.target', "Target added damping"), unit: '%' },
		{ label: localize('planned.dampers.exponent', "Velocity exponent") },
	],
	outputs: [
		localize('planned.dampers.out1', "A damper schedule: coefficient, force and stroke"),
		localize('planned.dampers.out2', "Drifts with and without the dampers"),
	],
	references: [
		localize('planned.dampers.ref1', "ASCE/SEI 7-16 Ch 18 (structures with damping systems)"),
	],
});

// T44: composite beams and columns.
registerPlannedFeature({
	id: FemPlanned.compositeBeams,
	part: 'fem',
	title: localize('planned.compositeBeams.title', "Composite Beams"),
	summary: localize('planned.compositeBeams.summary', "Designs steel beams acting with the concrete slab on metal deck through shear studs: full or partial composite action, the construction stage before the concrete hardens, camber, deflection and floor vibration."),
	steps: [
		localize('planned.compositeBeams.step1', "Mark the steel beams that act compositely, and give the deck and slab."),
		localize('planned.compositeBeams.step2', "Check the bare steel beam for the construction stage."),
		localize('planned.compositeBeams.step3', "Check the composite section, choosing the studs for full or partial action."),
		localize('planned.compositeBeams.step4', "Give the camber, and check deflection and walking vibration."),
	],
	inputs: [
		{ label: localize('planned.compositeBeams.deck', "Deck profile"), example: localize('planned.compositeBeams.deckExample', "Ribs perpendicular to the beam") },
		{ label: localize('planned.compositeBeams.slab', "Slab depth above the deck"), unit: localize('planned.unit.mm', "mm") },
		{ label: localize('planned.compositeBeams.stud', "Stud diameter"), unit: localize('planned.unit.mm', "mm") },
	],
	outputs: [
		localize('planned.compositeBeams.out1', "Stud count and layout per beam"),
		localize('planned.compositeBeams.out2', "Composite checks, camber, and the vibration check"),
	],
	references: [
		localize('planned.compositeBeams.ref1', "BNBC 2020 Part 6 Chapter 10 (steel; the provisions of AISC 360-05)"),
		localize('planned.compositeBeams.ref2', "AISC 360 Ch I (composite members)"),
		localize('planned.compositeBeams.ref3', "AISC Design Guide 11 (floor vibrations)"),
	],
});
registerPlannedFeature({
	id: FemPlanned.compositeColumns,
	part: 'fem',
	title: localize('planned.compositeColumns.title', "Composite Columns"),
	summary: localize('planned.compositeColumns.summary', "Designs steel sections encased in concrete, and concrete-filled steel tubes, for axial force and bending."),
	steps: [
		localize('planned.compositeColumns.step1', "Give the steel section, the concrete around or inside it, and the bars."),
		localize('planned.compositeColumns.step2', "Work out the section's axial and flexural strength and their interaction."),
		localize('planned.compositeColumns.step3', "Check the column under every design combination."),
	],
	inputs: [
		{ label: localize('planned.compositeColumns.type', "Type"), example: localize('planned.compositeColumns.typeExample', "Encased or filled") },
	],
	outputs: [
		localize('planned.compositeColumns.out1', "The P-M interaction and the column checks"),
	],
	references: [
		localize('planned.compositeColumns.ref1', "BNBC 2020 Part 6 Chapter 10 (steel; the provisions of AISC 360-05)"),
		localize('planned.compositeColumns.ref2', "AISC 360 Ch I (composite members)"),
	],
});

// T14: cracked long-term FE deflection of slabs, and crack widths.
registerPlannedFeature({
	id: FemPlanned.crackedSlabDeflection,
	part: 'fem',
	title: localize('fem.planned.crackedDeflection.title', "Cracked Long-Term Slab Deflection (FE)"),
	summary: localize('fem.planned.crackedDeflection.summary', "Deflections of slabs from the finite element model with cracked sections, creep and shrinkage, instead of the hand method's immediate and long-term multipliers."),
	steps: [
		localize('fem.planned.crackedDeflection.step1', "Run the service load combinations on the shell model."),
		localize('fem.planned.crackedDeflection.step2', "Reduce each shell's stiffness where its moment exceeds the cracking moment, from the bars entered (effective moment of inertia per shell), and iterate."),
		localize('fem.planned.crackedDeflection.step3', "Add creep and shrinkage curvature over time for the sustained loads."),
		localize('fem.planned.crackedDeflection.step4', "Compare the deflection after the partitions are built with the limits, and draw the deflected slab as a contour."),
	],
	inputs: [
		{ label: localize('fem.planned.crackedDeflection.sustained', "Sustained share of the live load"), unit: '%', example: '25' },
		{ label: localize('fem.planned.crackedDeflection.age', "Age at loading"), unit: localize('fem.planned.days', "days"), example: '28' },
		{ label: localize('fem.planned.crackedDeflection.humidity', "Relative humidity"), unit: '%', example: '75' },
		{ label: localize('fem.planned.crackedDeflection.creep', "Creep coefficient"), example: '2.0' },
	],
	outputs: [
		localize('fem.planned.crackedDeflection.out1', "Immediate and long-term deflection contours per slab"),
		localize('fem.planned.crackedDeflection.out2', "Deflection checks against the span limits, in the design checks and the report"),
	],
	references: [
		'ACI 318-19 24.2.3, 24.2.4 (long-term deflection)',
		'ACI 435R (control of deflection in concrete structures)',
		'ACI 209.2R (creep and shrinkage models)',
	],
});

registerPlannedFeature({
	id: FemPlanned.crackWidths,
	part: 'fem',
	title: localize('fem.planned.crackWidths.title', "Crack Widths of Beams, Slabs and Walls"),
	summary: localize('fem.planned.crackWidths.summary', "Calculated crack widths under service loads for beams, slabs and walls, checked against exposure limits. Today crack widths are checked for water tanks only; beams are checked for the code pack's crack-control bar spacing and skin steel."),
	steps: [
		localize('fem.planned.crackWidths.step1', "Take the service moments and axial forces of each member and slab strip."),
		localize('fem.planned.crackWidths.step2', "Find the steel stress of the cracked section from the bars entered."),
		localize('fem.planned.crackWidths.step3', "Work out the crack spacing and width, and compare with the limit of the exposure."),
	],
	inputs: [
		{ label: localize('fem.planned.crackWidths.exposure', "Exposure class"), example: localize('fem.planned.crackWidths.exposureExample', "moderate") },
		{ label: localize('fem.planned.crackWidths.limit', "Crack width limit"), unit: 'mm', example: '0.3' },
		{ label: localize('fem.planned.crackWidths.combination', "Service combination"), example: 'D + L' },
	],
	outputs: [
		localize('fem.planned.crackWidths.out1', "Crack width per member and per slab strip, as a design check"),
		localize('fem.planned.crackWidths.out2', "Crack width contours on the slabs"),
	],
	references: [
		'EN 1992-1-1 7.3.4 (crack width calculation)',
		'ACI 224R (control of cracking in concrete structures)',
	],
});

// T15: automatic tendon layout and time-step long-term losses.
registerPlannedFeature({
	id: FemPlanned.tendonLayout,
	part: 'fem',
	title: localize('fem.planned.tendonLayout.title', "Automatic Tendon Layout"),
	summary: localize('fem.planned.tendonLayout.summary', "Proposes the bands and distributed tendons of a post-tensioned slab, their profiles and counts, from the column grid and a target balanced load, instead of entering each tendon group."),
	steps: [
		localize('fem.planned.tendonLayout.step1', "Find the column lines of the slab and place a band on each line one way and distributed tendons the other way."),
		localize('fem.planned.tendonLayout.step2', "Set each profile to the highest and lowest points the cover allows, with reverse curves over the supports."),
		localize('fem.planned.tendonLayout.step3', "Choose the tendon counts that balance the target share of the dead load and meet the precompression limits."),
		localize('fem.planned.tendonLayout.step4', "Write the tendon groups into the building model for the PT checks to verify."),
	],
	inputs: [
		{ label: localize('fem.planned.tendonLayout.balanced', "Balanced share of the self-weight"), unit: '%', example: '80' },
		{ label: localize('fem.planned.tendonLayout.precompression', "Target precompression"), unit: 'MPa', example: '1.4' },
		{ label: localize('fem.planned.tendonLayout.cover', "Cover to the tendons"), unit: 'mm', example: '25' },
	],
	outputs: [
		localize('fem.planned.tendonLayout.out1', "Tendon groups with profiles in the building model's additions"),
		localize('fem.planned.tendonLayout.out2', "A layout summary per slab"),
	],
	references: [
		'PTI DC20.9 (design of post-tensioned slabs using unbonded tendons)',
		'ACI 423.3R (recommendations for concrete members prestressed with unbonded tendons)',
	],
});

registerPlannedFeature({
	id: FemPlanned.tendonLongTermLosses,
	part: 'fem',
	title: localize('fem.planned.tendonLosses.title', "Long-Term Tendon Losses (Time-Step)"),
	summary: localize('fem.planned.tendonLosses.summary', "Works out the losses of tendon stress from creep, shrinkage and steel relaxation over time, instead of the long-term loss the engineer enters for each tendon group."),
	steps: [
		localize('fem.planned.tendonLosses.step1', "Take the precompression and the sustained stress at the tendons from the PT checks."),
		localize('fem.planned.tendonLosses.step2', "Step through time with the creep and shrinkage of the concrete and the relaxation of the strand."),
		localize('fem.planned.tendonLosses.step3', "Use the loss found for the service and strength checks."),
	],
	inputs: [
		{ label: localize('fem.planned.tendonLosses.humidity', "Relative humidity"), unit: '%', example: '75' },
		{ label: localize('fem.planned.tendonLosses.volume', "Volume / surface ratio"), unit: 'mm', example: '100' },
		{ label: localize('fem.planned.tendonLosses.relaxation', "Strand relaxation class"), example: localize('fem.planned.tendonLosses.low', "low relaxation") },
	],
	outputs: [
		localize('fem.planned.tendonLosses.out1', "Long-term loss per tendon group, with the share of each source"),
	],
	references: [
		'ACI 423.10R (estimating prestress losses)',
		'ACI 209.2R (creep and shrinkage models)',
	],
});

// Planned (T26: BNBC 2020 gives no floor vibration method; linear buckling is built, in the
// result tables of each load combination).
registerPlannedFeature({
	id: FemPlanned.floorVibration,
	part: 'fem',
	title: localize('planned.floorVibration.title', "Floor Vibration from Walking"),
	summary: localize('planned.floorVibration.summary', "Checks floors for walking-induced vibration: the floor's natural frequencies and modal masses from the model, the response to footfall, and the comparison with the comfort limits of the occupancy."),
	steps: [
		localize('planned.floorVibration.step1', "Pick the floor panels or bays to check and their occupancy (office, residence, shopping, hospital)."),
		localize('planned.floorVibration.step2', "Run a modal analysis of the floor with the live load expected in service and the damping of the fit-out."),
		localize('planned.floorVibration.step3', "Work out the peak acceleration or response factor from footfall at the critical points."),
		localize('planned.floorVibration.step4', "Compare with the occupancy's limit and report each panel."),
	],
	inputs: [
		{ label: localize('planned.floorVibration.occupancy', "Occupancy"), example: localize('planned.floorVibration.occupancyExample', "Office") },
		{ label: localize('planned.floorVibration.damping', "Damping ratio"), unit: '%', example: '3' },
		{ label: localize('planned.floorVibration.liveLoad', "Live load in service"), unit: 'kN/m²', example: '0.5' },
		{ label: localize('planned.floorVibration.walker', "Walking frequency"), unit: 'Hz', example: '1.6 – 2.2' },
	],
	outputs: [
		localize('planned.floorVibration.out1', "Floor frequencies, modal masses and peak accelerations per panel"),
		localize('planned.floorVibration.out2', "Pass or fail against the comfort limit, coloured on the plan"),
		localize('planned.floorVibration.out3', "A floor vibration section in the design report"),
	],
	references: [
		localize('planned.floorVibration.ref1', "BNBC 2020 Part 6 (no floor vibration method)"),
		localize('planned.floorVibration.ref2', "AISC Design Guide 11 (floor vibrations due to human activity)"),
		localize('planned.floorVibration.ref3', "CCIP-016 (design of floors for vibration)"),
	],
});

// T27: the steel connection methods BNBC 2020 does not give (base plate thickness and moment
// bases, anchors in concrete, end-plate moment connections by yield lines).
registerPlannedFeature({
	id: FemPlanned.basePlateDesign,
	part: 'fem',
	title: localize('planned.basePlateDesign.title', "Base Plate Thickness and Moment Bases"),
	summary: localize('planned.basePlateDesign.summary', "Sizes the base plate of a steel column by the cantilever method and designs moment bases (large eccentricity, anchor rods in tension). Today the base plate is checked for bearing on the concrete, the anchor rods' steel and the welds only."),
	steps: [
		localize('planned.basePlateDesign.step1', "Take the column base forces of every combination: axial force, shear and moments."),
		localize('planned.basePlateDesign.step2', "Find the bearing length and stress, and the anchor rod tension when the eccentricity is large."),
		localize('planned.basePlateDesign.step3', "Work out the plate thickness from the cantilevers m, n and λn' and from the anchor rod tension."),
		localize('planned.basePlateDesign.step4', "Propose the plate size, thickness and anchor layout, and draw the base detail."),
	],
	inputs: [
		{ label: localize('planned.basePlateDesign.size', "Plate N × B"), unit: 'mm', example: '450 × 350' },
		{ label: localize('planned.basePlateDesign.thickness', "Plate thickness"), unit: 'mm', example: '30' },
		{ label: localize('planned.basePlateDesign.anchors', "Anchor rods and their gauge"), example: localize('planned.basePlateDesign.anchorsExample', "4 M24 at 300 mm") },
		{ label: localize('planned.basePlateDesign.fc', "Concrete f'c"), unit: 'MPa', example: '25' },
	],
	outputs: [
		localize('planned.basePlateDesign.out1', "Required plate thickness and the plate bending check per combination"),
		localize('planned.basePlateDesign.out2', "Anchor rod forces of moment bases"),
		localize('planned.basePlateDesign.out3', "A base plate detail on the steel drawings"),
	],
	references: [
		localize('planned.basePlateDesign.ref1', "BNBC 2020 Part 6 Sec 10.10.8 (bearing on concrete; no plate thickness method)"),
		localize('planned.basePlateDesign.ref2', "AISC Design Guide 1 (base plate and anchor rod design)"),
	],
});

registerPlannedFeature({
	id: FemPlanned.anchorConcrete,
	part: 'fem',
	title: localize('planned.anchorConcrete.title', "Anchors in Concrete"),
	summary: localize('planned.anchorConcrete.summary', "Checks the concrete around the anchor rods of base plates and embedded plates: breakout, pullout, side-face blowout and pryout, in tension and shear. Today only the anchor rods' steel is checked."),
	steps: [
		localize('planned.anchorConcrete.step1', "Take the anchor group, its embedment and edge distances, and the forces on it."),
		localize('planned.anchorConcrete.step2', "Work out the breakout cones and their projected areas with the edge and group factors."),
		localize('planned.anchorConcrete.step3', "Check breakout, pullout and side-face blowout in tension, and breakout and pryout in shear."),
		localize('planned.anchorConcrete.step4', "Combine tension and shear and report the governing mode."),
	],
	inputs: [
		{ label: localize('planned.anchorConcrete.embedment', "Effective embedment hef"), unit: 'mm', example: '300' },
		{ label: localize('planned.anchorConcrete.edge', "Least edge distance"), unit: 'mm', example: '150' },
		{ label: localize('planned.anchorConcrete.cracked', "Concrete cracked"), example: localize('planned.anchorConcrete.crackedExample', "Yes") },
		{ label: localize('planned.anchorConcrete.reinforcement', "Anchor reinforcement"), example: localize('planned.anchorConcrete.reinforcementExample', "None") },
	],
	outputs: [
		localize('planned.anchorConcrete.out1', "Concrete capacities of the anchor group in tension and shear"),
		localize('planned.anchorConcrete.out2', "The governing failure mode with its check in the base plate's checks"),
	],
	references: [
		localize('planned.anchorConcrete.ref1', "BNBC 2020 Part 6 Sec 10.10.9 (anchor rods; the concrete refers out)"),
		localize('planned.anchorConcrete.ref2', "ACI 318-19 Chapter 17 (anchoring to concrete)"),
	],
});

registerPlannedFeature({
	id: FemPlanned.endPlateMoment,
	part: 'fem',
	title: localize('planned.endPlateMoment.title', "End-Plate Moment Connections"),
	summary: localize('planned.endPlateMoment.summary', "Designs flush and extended end-plate moment connections: the end plate and the column flange by yield lines, the bolts in tension with prying, and the stiffeners. Today moment connections are checked as bolted flange plates."),
	steps: [
		localize('planned.endPlateMoment.step1', "Choose the end-plate configuration: flush, extended four-bolt or eight-bolt, stiffened or not."),
		localize('planned.endPlateMoment.step2', "Find the bolt tension and the plate thickness from the yield-line mechanism of the plate."),
		localize('planned.endPlateMoment.step3', "Check the column flange by its yield lines, and the web, panel zone and stiffeners."),
		localize('planned.endPlateMoment.step4', "Check the shear bolts and welds, and draw the connection."),
	],
	inputs: [
		{ label: localize('planned.endPlateMoment.configuration', "Configuration"), example: localize('planned.endPlateMoment.configurationExample', "Extended, four bolts") },
		{ label: localize('planned.endPlateMoment.bolts', "Bolts"), example: 'M24 10.9' },
		{ label: localize('planned.endPlateMoment.plate', "End plate thickness"), unit: 'mm', example: '25' },
	],
	outputs: [
		localize('planned.endPlateMoment.out1', "End plate, bolt and column flange checks per combination"),
		localize('planned.endPlateMoment.out2', "An end-plate detail on the steel drawings"),
	],
	references: [
		localize('planned.endPlateMoment.ref1', "BNBC 2020 Part 6 Sec 10.10 (bolts and welds; no yield-line method)"),
		localize('planned.endPlateMoment.ref2', "AISC Design Guide 4 and 16 (end-plate moment connections)"),
		localize('planned.endPlateMoment.ref3', "AISC 358 (prequalified connections)"),
	],
});

// T28: AISC 341 seismic steel systems and member torsion (the direct analysis method is built:
// Project Settings → Analysis → Steel stability design method).
registerPlannedFeature({
	id: FemPlanned.steelSeismic,
	part: 'fem',
	title: localize('planned.steelSeismic.title', "Seismic Steel Systems"),
	summary: localize('planned.steelSeismic.summary', "Designs steel moment frames and braced frames for earthquakes: the width-to-thickness and bracing limits of each system, capacity design of columns and connections, panel zones, and the protected zones of special frames."),
	steps: [
		localize('planned.steelSeismic.step1', "Pick the system of each frame: special, intermediate or ordinary moment frame; special or ordinary concentrically braced frame; eccentrically braced frame."),
		localize('planned.steelSeismic.step2', "Check the members' highly or moderately ductile width-to-thickness ratios and lateral bracing."),
		localize('planned.steelSeismic.step3', "Check strong column, weak beam; the panel zones; the brace and link capacities; and the columns for the amplified seismic load."),
		localize('planned.steelSeismic.step4', "Design the connections for the expected strengths Ry Fy and report the protected zones."),
	],
	inputs: [
		{ label: localize('planned.steelSeismic.system', "Seismic system"), example: localize('planned.steelSeismic.systemExample', "Special concentrically braced frame") },
		{ label: localize('planned.steelSeismic.ry', "Ry of the steel"), example: '1.5' },
		{ label: localize('planned.steelSeismic.link', "EBF link length"), unit: 'mm', example: '900' },
	],
	outputs: [
		localize('planned.steelSeismic.out1', "Seismic checks per member and connection, in the design checks and the report"),
		localize('planned.steelSeismic.out2', "Capacity-design forces for the columns, beams and connections"),
	],
	references: [
		localize('planned.steelSeismic.ref1', "BNBC 2020 Part 6 Sec 2.5 (the steel seismic systems with R, Cd and Ω0)"),
		localize('planned.steelSeismic.ref2', "AISC 341 (seismic provisions for structural steel buildings)"),
		localize('planned.steelSeismic.ref3', "AISC 358 (prequalified moment connections)"),
	],
});

registerPlannedFeature({
	id: FemPlanned.steelTorsion,
	part: 'fem',
	title: localize('planned.steelTorsion.title', "Steel Member Torsion"),
	summary: localize('planned.steelTorsion.summary', "Checks steel members for the torsion of the analysis: St. Venant and warping stresses of open sections, the torsional strength of hollow sections, and their interaction with the axial force, bending and shear."),
	steps: [
		localize('planned.steelTorsion.step1', "Take the torsional moment along each member and its end restraint against warping."),
		localize('planned.steelTorsion.step2', "Work out the shear and normal stresses from pure and warping torsion along the member."),
		localize('planned.steelTorsion.step3', "Combine them with the stresses of the axial force, bending and shear, and compare with the limits."),
	],
	inputs: [
		{ label: localize('planned.steelTorsion.ends', "Warping restraint at the ends"), example: localize('planned.steelTorsion.endsExample', "Free") },
		{ label: localize('planned.steelTorsion.load', "Torque from"), example: localize('planned.steelTorsion.loadExample', "The analysis") },
	],
	outputs: [
		localize('planned.steelTorsion.out1', "Torsion and combined stress checks per member"),
	],
	references: [
		localize('planned.steelTorsion.ref1', "BNBC 2020 Part 6 Sec 10.8.3 (members under torsion)"),
		localize('planned.steelTorsion.ref2', "AISC Design Guide 9 (torsional analysis of structural steel members)"),
	],
});

// T30: cold-formed steel purlins and girts. BNBC 2020 Part 6 Chapter 10 covers hot-rolled and
// built-up members only; cold-formed sections need AISI S100.
registerPlannedFeature({
	id: FemPlanned.coldFormedSteel,
	part: 'fem',
	title: localize('planned.coldFormed.title', "Cold-Formed Purlins and Girts"),
	summary: localize('planned.coldFormed.summary', "Designs cold-formed C and Z purlins and girts of steel sheds: effective section properties of thin, slender elements, flexure with lateral-torsional and distortional buckling, the restraint from the sheeting, laps and continuity over the frames, and the wind uplift case."),
	steps: [
		localize('planned.coldFormed.step1', "Pick a C or Z section from the cold-formed section table, its span arrangement (simple, lapped or continuous) and the sag rods."),
		localize('planned.coldFormed.step2', "Take the roof and wall loads with the wind pressure and uplift from the cladding areas."),
		localize('planned.coldFormed.step3', "Work out the effective section, then check flexure, shear, web crippling at the supports and the combined actions, for downward load and uplift."),
		localize('planned.coldFormed.step4', "Check the deflection and list the purlins and girts with their sizes for the BOQ."),
	],
	inputs: [
		{ label: localize('planned.coldFormed.section', "Section"), example: 'Z200×2.0' },
		{ label: localize('planned.coldFormed.spacing', "Spacing"), unit: 'mm', example: '1500' },
		{ label: localize('planned.coldFormed.continuity', "Continuity"), example: localize('planned.coldFormed.continuityExample', "Lapped over the frames") },
		{ label: localize('planned.coldFormed.restraint', "Sheeting restraint"), example: localize('planned.coldFormed.restraintExample', "Through-fastened sheeting") },
	],
	outputs: [
		localize('planned.coldFormed.out1', "Purlin and girt design ratios for gravity and uplift"),
		localize('planned.coldFormed.out2', "A purlin and girt schedule"),
	],
	references: [
		localize('planned.coldFormed.ref1', "BNBC 2020 Part 6 Chapter 10 (hot-rolled and built-up steel; no cold-formed provisions)"),
		localize('planned.coldFormed.ref2', "AISI S100 (North American specification for cold-formed steel structural members)"),
	],
});

// Planned (MVP: BNBC 2020 designs deep beams, transfer girders and corbels; a general strut-and-tie
// model of any D-region needs the procedure of ACI 318 Chapter 23, which BNBC does not give).
registerPlannedFeature({
	id: PLANNED_STM_GENERAL,
	part: 'fem',
	title: localize('planned.stmGeneral.title', "Strut-and-Tie Models of Any D-Region"),
	summary: localize('planned.stmGeneral.summary', "Draw and check a strut-and-tie model for regions the deep-beam checks do not cover: dapped ends, beams and walls with openings, frame corners, continuous deep beams and corbels with several loads."),
	steps: [
		localize('planned.stmGeneral.step1', "Pick the D-region on a member and its boundary forces from the analysis."),
		localize('planned.stmGeneral.step2', "Lay out struts, ties and nodes, or start from a template (dapped end, opening, corner)."),
		localize('planned.stmGeneral.step3', "Solve the truss and check each strut, tie and node with its βs and βn."),
		localize('planned.stmGeneral.step4', "Detail the ties' anchorage and the distributed reinforcement, and print the model in the report."),
	],
	inputs: [
		{ label: localize('planned.stmGeneral.inputRegion', "D-region"), example: localize('planned.stmGeneral.exampleRegion', "Dapped end of B12") },
		{ label: localize('planned.stmGeneral.inputTemplate', "Template"), example: localize('planned.stmGeneral.exampleTemplate', "Dapped end") },
		{ label: localize('planned.stmGeneral.inputWidth', "Strut width"), unit: 'mm', example: '250' },
	],
	outputs: [
		localize('planned.stmGeneral.output1', "Truss forces and the check of every strut, tie and node"),
		localize('planned.stmGeneral.output2', "Tie bars and their anchorage"),
		localize('planned.stmGeneral.output3', "A model sketch in the design report"),
	],
	references: [
		'ACI 318-19 Chapter 23',
		'BNBC 2020 Part 6 Sec 6.2.3.2 (φ = 0.75)',
	],
});

// B6: timber joints. Nailed, bolted (wooden splice plates), split-ring and disc-dowel joints are
// checked with the code pack's timber table (saengine.design.timber.connections); wood screws and
// steel side plates stay planned: the pack gives no design values for them.
registerPlannedFeature({
	id: FemPlanned.timberConnections,
	part: 'fem',
	title: localize('fem.planned.timberScrews.title', "Timber Screwed Joints and Steel Side Plates"),
	summary: localize('fem.planned.timberScrews.summary', "Checks wood-screw joints and bolted joints with steel side plates at the ends of timber members. The active code pack gives no design values for them; nailed, bolted (wooden splice plates), split-ring and disc-dowel joints are already checked."),
	steps: [
		localize('fem.planned.timberScrews.step1', "Choose wood screws, or bolts through steel side plates, as the joint of the timber member's type."),
		localize('fem.planned.timberScrews.step2', "Take the end forces of the member under the allowable stress combinations."),
		localize('fem.planned.timberScrews.step3', "Check the fasteners' permissible loads, the load angle to the grain and the spacing, edge and end distances."),
	],
	inputs: [
		{ label: localize('fem.planned.timberScrews.fastener', "Fastener"), example: localize('fem.planned.timberScrews.screw', "No. 12 wood screws") },
		{ label: localize('fem.planned.timberScrews.plates', "Side plates"), example: localize('fem.planned.timberScrews.steelPlates', "6 mm steel") },
	],
	outputs: [
		localize('fem.planned.timberScrews.out1', "Joint capacity and utilisation per end"),
	],
	references: [
		localize('fem.planned.timberScrews.ref', "Not covered by the active code pack's timber table: it gives no screw or steel side-plate design values"),
	],
});

// T31: confined masonry (MVP: BNBC 2020 Part 6 Chapter 7 gives the plain and reinforced masonry
// walls SAEngine designs; confined masonry needs guides BNBC does not give).
registerPlannedFeature({
	id: FemPlanned.confinedMasonry,
	part: 'fem',
	title: localize('fem.planned.confinedMasonry.title', "Confined Masonry Walls"),
	summary: localize('fem.planned.confinedMasonry.summary', "Designs masonry walls built first and then confined by cast-in-place RC tie columns at their ends and openings and tie beams at each floor, the usual low-rise system where plain masonry is not permitted."),
	steps: [
		localize('fem.planned.confinedMasonry.step1', "Mark the masonry walls that are confined and place the tie columns and tie beams round each panel."),
		localize('fem.planned.confinedMasonry.step2', "Check the wall density of each storey in each direction against the seismic demand."),
		localize('fem.planned.confinedMasonry.step3', "Check each panel's in-plane shear and the tie columns' tension and shear from the panel forces."),
		localize('fem.planned.confinedMasonry.step4', "Size the tie columns' and tie beams' bars and ties, and their spacing limits."),
	],
	inputs: [
		{ label: localize('fem.planned.confinedMasonry.tieColumn', "Tie column size"), unit: 'mm', example: '250 × 250' },
		{ label: localize('fem.planned.confinedMasonry.tieBeam', "Tie beam depth"), unit: 'mm', example: '250' },
		{ label: localize('fem.planned.confinedMasonry.spacing', "Largest tie column spacing"), unit: 'mm', example: '4000' },
	],
	outputs: [
		localize('fem.planned.confinedMasonry.out1', "Wall density per storey and direction"),
		localize('fem.planned.confinedMasonry.out2', "Panel shear checks and the tie columns' and tie beams' bars"),
	],
	references: [
		'Eurocode 8 Part 1 Sec 9.5 (confined masonry)',
		'Seismic design guide for low-rise confined masonry buildings (Confined Masonry Network, EERI)',
	],
});
