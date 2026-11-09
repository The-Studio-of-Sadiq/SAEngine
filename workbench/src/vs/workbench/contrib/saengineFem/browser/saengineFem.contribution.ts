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
import { INotificationService } from '../../../../platform/notification/common/notification.js';
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
import { DESIGN_REINFORCEMENT_COMMAND, STRUT_AND_TIE_COMMAND } from './femDesign.js';
import { CFD_WIND_COMMAND, FemCfdWindEditor, FemCfdWindInput, FemCfdWindInputSerializer } from './femCfdWind.js';
import { FemPlanned } from './femPlannedFeatures.js';
import { FemDesignProposalEditor } from './femDesignProposalEditor.js';
import { FemDesignProposalInput, FemDesignProposalInputSerializer } from './femDesignProposalInput.js';
import { FemModelEditor } from './femModelEditor.js';
import { FemStrutAndTieEditor } from './femStrutAndTieEditor.js';
import { FemStrutAndTieInput, FemStrutAndTieInputSerializer } from './femStrutAndTieInput.js';
import { FemModelEditorInput, FemModelEditorInputSerializer } from './femModelEditorInput.js';
import { PUSHOVER_FILE } from './femDerivationBar.js';
import { FEM_SHOW_CHARTS_COMMAND, FEM_SHOW_MEMBER_COMMAND } from './femResultsBar.js';
import { FemResultsEditor, FemResultsInput, FemResultsInputSerializer, IFemResultsEditorOptions, memberNames } from './femResultsView.js';
import { defaultCodeName } from '../../../services/saengineProject/common/activeCodePack.js';

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
	EditorPaneDescriptor.create(FemStrutAndTieEditor, FemStrutAndTieInput.EDITOR_ID, localize('femStrutAndTieEditor', "Strut-and-Tie Models")),
	[new SyncDescriptor(FemStrutAndTieInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FemStrutAndTieInput.ID, FemStrutAndTieInputSerializer);

// Alpha 9 L3: the CFD wind tunnel (an optional link to the user's own OpenFOAM).
Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(FemCfdWindEditor, FemCfdWindInput.EDITOR_ID, localize('femCfdWindEditor', "CFD Wind Tunnel")),
	[new SyncDescriptor(FemCfdWindInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FemCfdWindInput.ID, FemCfdWindInputSerializer);

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

/** Command id of opening the pushover model (`08 FEM/pushover.osmodel`, W4B-3). */
export const FEM_OPEN_PUSHOVER_COMMAND = 'saengine.fem.openPushover';

/**
 * W4B-3: opens the pushover model (`08 FEM/pushover.osmodel`) in the FEM editor, where it is
 * run and its capacity curve, hinges and target displacement shown; or says how to get one.
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: FEM_OPEN_PUSHOVER_COMMAND,
			title: localize2('saengine.fem.openPushover', "Open Pushover Model"),
			metadata: { description: localize2('saengine.fem.openPushover.description', "Opens 08 FEM/pushover.osmodel, the nonlinear model derived when Pushover is ticked in Project Settings, Analysis model; Run All runs it after the design checks.") },
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
			precondition: ProjectOpenContext,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const fem = partById('fem');
		if (!project || !fem) {
			return;
		}
		const model = joinPath(project.root, fem.folder, PUSHOVER_FILE);
		if (!await accessor.get(IFileService).exists(model)) {
			accessor.get(INotificationService).info(localize('saengine.fem.noPushover', "There is no pushover model: tick Pushover in Project Settings, Analysis model, give the object types bars (fiber sections need them) and derive the analysis model again (or Run All)."));
			return;
		}
		await accessor.get(IEditorService).openEditor(new FemModelEditorInput(model), { pinned: true });
	}
});

/**
 * Alpha 9 L3: opens CFD Wind Tunnel: the building's wind by a steady CFD simulation with the
 * user's own OpenFOAM (found in WSL on Windows; never bundled or downloaded), run only when the
 * user presses Run; pressure coefficients, storey forces and the code comparison.
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CFD_WIND_COMMAND,
			title: localize2('saengine.fem.cfdWind', "CFD Wind Tunnel"),
			metadata: { description: localize2('saengine.fem.cfdWind.description', "Wind pressure coefficients and storey forces of the building by a steady CFD simulation (OpenFOAM, installed separately), per wind direction, compared with the code's wind; optionally the wind cases of the analysis. Engineer-supplied loads that need validation.") },
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.symbolEvent,
			f1: true,
			precondition: ProjectOpenContext,
			menu: { id: PROJECT_MENU, group: '1_project', order: 7 },
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		if (project) {
			await accessor.get(IEditorService).openEditor(new FemCfdWindInput(project.root), { pinned: true });
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

/**
 * Opens Strut-and-Tie Models: strut-and-tie models of any D-region of `model` (by default the
 * project's `08 FEM/model.osmodel`), drawn and checked with the code pack's procedure, at the
 * model named `region` when given.
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: STRUT_AND_TIE_COMMAND,
			title: localize2('saengine.strutAndTie', "Strut-and-Tie Models"),
			metadata: { description: localize2('saengine.strutAndTie.description', "Draws and checks strut-and-tie models of D-regions (dapped ends, corbels, frame corners, openings) with the project's code pack. Arguments: the analysis model (URI; by default the project's) and the name of a model to show.") },
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.symbolStructure,
			f1: true,
			precondition: ProjectOpenContext,
		});
	}

	override async run(accessor: ServicesAccessor, model?: URI, region?: string): Promise<void> {
		const target = analysisModel(accessor, model);
		if (target) {
			await accessor.get(IEditorService).openEditor(new FemStrutAndTieInput(target, typeof region === 'string' ? region : undefined), { pinned: true });
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

// T17 / B25 / P2: the construction sequence's staged dead load, the column and wall shortening with
// the code pack's creep and shrinkage models and the creep and shrinkage forces case CS
// (fem/staged.py, fem/concrete_time.py) are built. Still planned: the construction loads and
// shoring of the partly built structure.
registerPlannedFeature({
	id: FemPlanned.stagedConstructionLoads,
	part: 'fem',
	title: localize('planned.stagedLoads.title', "Construction Loads and Shoring"),
	summary: localize('planned.stagedLoads.summary', "Applies the erection and construction loads to the partly built structure stage by stage (wet concrete, formwork, stacked materials, equipment), with the shores and props that carry fresh floors added and removed at each stage. Today's construction sequence stages the self-weight only; the column shortening takes the finishes and sustained live load in time."),
	steps: [
		localize('planned.stagedLoads.step1', "Define the construction loads and the shoring of each stage."),
		localize('planned.stagedLoads.step2', "Analyse the stages in sequence, adding and removing the shores."),
		localize('planned.stagedLoads.step3', "Check the members of each stage under its construction loads."),
	],
	inputs: [
		{ label: localize('planned.stagedLoads.load', "Construction live load"), unit: 'kN/m²' },
		{ label: localize('planned.stagedLoads.shores', "Shored floors below the one cast"), example: '2' },
	],
	outputs: [
		localize('planned.stagedLoads.out1', "Member forces of every construction stage"),
		localize('planned.stagedLoads.out2', "Shore loads per floor"),
	],
	references: [
		localize('planned.stagedLoads.ref1', "The code pack requires erection and construction loads to be considered but gives no values"),
		localize('planned.stagedLoads.ref2', "ACI 347.2R (shoring and reshoring of multistorey buildings)"),
	],
});

// T21 / B20 / P3: the pushover's target displacement (coefficient, ASCE 41 coefficient, FEMA 440,
// N2), the hinges with their performance levels and the member acceptance follow the code
// pack's methods (fem/pushover_target.py, fem/hinges.py, fem/acceptance.py). Still planned:
// walls with openings as nonlinear piers and spandrels.
registerPlannedFeature({
	id: FemPlanned.fibreWalls,
	part: 'fem',
	title: localize('planned.fibreWalls.title', "Nonlinear Walls with Openings"),
	summary: localize('planned.fibreWalls.summary', "Models walls with openings as nonlinear piers and spandrels (coupling beams) in the pushover model. Today walls without openings become fibre wall elements, and walls with openings stay elastic shells, with a note."),
	steps: [
		localize('planned.fibreWalls.step1', "Split each wall with openings into piers and spandrels from its openings."),
		localize('planned.fibreWalls.step2', "Give the piers fibre sections and the spandrels diagonal or flexural models from their bars."),
		localize('planned.fibreWalls.step3', "Check their strains and shear in the member acceptance."),
	],
	outputs: [
		localize('planned.fibreWalls.out1', "Pier and spandrel forces per step"),
		localize('planned.fibreWalls.out2', "Their acceptance in the member acceptance table"),
	],
	references: [
		localize('planned.fibreWalls.ref1', "ASCE/SEI 41-17 Sec 10.7 (concrete shear walls and coupling beams)"),
	],
});

// T22 / P4: the assessment and retrofit of existing RC and steel buildings are built
// (fem/existing_building.py, the code pack's existing table: knowledge factors, as-built
// strengths from tests, condition, linear and nonlinear procedures, jackets, FRP, added walls
// and braces, before and after). Still planned: masonry buildings.
registerPlannedFeature({
	id: FemPlanned.existingMasonry,
	part: 'fem',
	title: localize('planned.existingMasonry.title', "Assessment of Existing Masonry Buildings"),
	summary: localize('planned.existingMasonry.summary', "Assesses an existing unreinforced or confined masonry building: the piers' rocking, sliding and diagonal tension strengths from the tested masonry, the in-plane and out-of-plane checks, and strengthening by jackets, FRP and ties. Built today: existing reinforced concrete and steel buildings (Project Settings, Analysis model, Existing building)."),
	steps: [
		localize('planned.existingMasonry.step1', "Enter the masonry's tested strengths (in-place shear, prisms) and the knowledge level."),
		localize('planned.existingMasonry.step2', "Find each pier's strength by its governing mode from the run's forces."),
		localize('planned.existingMasonry.step3', "Check the walls out of plane and the diaphragms' ties."),
	],
	outputs: [
		localize('planned.existingMasonry.out1', "Pier strengths and their governing modes"),
		localize('planned.existingMasonry.out2', "Strengthening and the re-assessment"),
	],
	references: [
		localize('planned.existingMasonry.ref1', "ASCE/SEI 41-17 Ch 11 (masonry)"),
		localize('planned.existingMasonry.ref2', "EN 1998-3:2005 Annex C (masonry buildings)"),
	],
});

// T35 / B36 / P5: the nonlinear time history design, record scaling and frequency-domain spectral
// matching are built (fem/nonlinear_history.py, fem/records.py, fem/spectral_matching.py);
// searching open record databases and time-domain wavelet matching stay planned.
registerPlannedFeature({
	id: FemPlanned.recordSearch,
	part: 'fem',
	title: localize('planned.records.title', "Record Search and Wavelet Matching"),
	summary: localize('planned.records.summary', "Picks ground-motion records from open databases, with their licences checked, and matches them in the time domain with wavelets. Built today: importing records (PEER .AT2, two columns, CSV) with their magnitude, distance and Vs30, scaling a suite to the code pack's target, and spectral matching in the frequency domain (Project Settings, Analysis, Time history: modification). SAEngine bundles no third-party records."),
	steps: [
		localize('planned.records.step1', "Search an open record database by magnitude, distance and site class."),
		localize('planned.records.step2', "Download the chosen records with their licence terms."),
		localize('planned.records.step3', "Match each record to the target in the time domain with wavelets."),
	],
	inputs: [
		{ label: localize('planned.records.range', "Magnitude and distance ranges") },
		{ label: localize('planned.records.method', "Method"), example: localize('planned.records.methodExample', "Spectral matching in the time domain") },
	],
	outputs: [
		localize('planned.records.out1', "Records with their source and licence"),
	],
	references: [
		localize('planned.records.ref1', "ASCE/SEI 7-22 Sec 16.2 (ground motion selection and modification)"),
		localize('planned.records.ref2', "Al Atik and Abrahamson (2010), spectral matching in the time domain"),
	],
});

// T36 / alpha 9 P6: seismic isolators (B37, an option of the column types) and supplemental
// dampers (an option of the brace types) are built: saengine.fem.isolation, saengine.fem.dampers.

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
	summary: localize('fem.planned.tendonLosses.summary', "The PT checks already work out the long-term loss of each tendon group from the code pack's lump values (creep and shrinkage of the concrete, relaxation of the strand). This planned method steps through time instead, stage by stage, for staged stressing and losses at any age."),
	steps: [
		localize('fem.planned.tendonLosses.step1', "Take the precompression and the sustained stress at the tendons from the PT checks, per stressing stage."),
		localize('fem.planned.tendonLosses.step2', "Step through time with the creep and shrinkage of the concrete and the relaxation of the strand, the stress at each step from the one before."),
		localize('fem.planned.tendonLosses.step3', "Use the loss found at each age for the service and strength checks, instead of the lump loss."),
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

// T27: the steel connection methods the code pack does not give (base plate thickness,
// end-plate moment connections by yield lines). B26 built the anchors in concrete and the
// anchor rod tension of moment bases.
registerPlannedFeature({
	id: FemPlanned.basePlateDesign,
	part: 'fem',
	title: localize('planned.basePlateThickness.title', "Base Plate Thickness"),
	summary: localize('planned.basePlateThickness.summary', "Sizes the base plate thickness of a steel column by the cantilever method, from the bearing stress and the anchor rod tension. Today the base plate is checked for bearing (with the base moment), the anchor rods' tension, steel and anchorage in the concrete, and the welds; the code pack gives no plate thickness method."),
	steps: [
		localize('planned.basePlateThickness.step1', "Take the bearing length and stress and the anchor rod tension the base plate checks already find."),
		localize('planned.basePlateThickness.step2', "Work out the plate thickness from the cantilevers m, n and λn' and from the anchor rod tension."),
		localize('planned.basePlateThickness.step3', "Propose the plate size and thickness, and draw the base detail."),
	],
	inputs: [
		{ label: localize('planned.basePlateDesign.size', "Plate N × B"), unit: 'mm', example: '450 × 350' },
		{ label: localize('planned.basePlateDesign.thickness', "Plate thickness"), unit: 'mm', example: '30' },
	],
	outputs: [
		localize('planned.basePlateDesign.out1', "Required plate thickness and the plate bending check per combination"),
		localize('planned.basePlateDesign.out3', "A base plate detail on the steel drawings"),
	],
	references: [
		localize('planned.basePlateThickness.ref1', "The active code pack's column base clauses (bearing on concrete; no plate thickness method)"),
		localize('planned.basePlateDesign.ref2', "AISC Design Guide 1 (base plate and anchor rod design)"),
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
		localize('planned.endPlateMoment.ref1', "{0} Part 6 Sec 10.10 (bolts and welds; no yield-line method)", defaultCodeName()),
		localize('planned.endPlateMoment.ref2', "AISC Design Guide 4 and 16 (end-plate moment connections)"),
		localize('planned.endPlateMoment.ref3', "AISC 358 (prequalified connections)"),
	],
});

// T30: cold-formed steel purlins and girts. Alpha 9 C12: lipped C and Z members (the 04 Objects
// profiles "C" and "Z") are designed by the code pack's coldFormed table (AISI S100, EN 1993-1-3,
// IS 801; BNBC 2020 has no cold-formed provisions); the purlin and girt systems stay planned.
registerPlannedFeature({
	id: FemPlanned.coldFormedSteel,
	part: 'fem',
	title: localize('planned.coldFormed.title', "Cold-Formed Purlins and Girts"),
	summary: localize('planned.coldFormed.summary', "Cold-formed lipped C and Z members are designed as steel members by the code pack's cold-formed method (effective widths, distortional buckling, member resistances). Planned: the purlin and girt systems of steel sheds: the restraint from the sheeting, laps and continuity over the frames, web crippling at the supports, the wind uplift case and the schedule."),
	steps: [
		localize('planned.coldFormed.step1', "Pick a C or Z section, its span arrangement (simple, lapped or continuous) and the sag rods."),
		localize('planned.coldFormed.step2', "Take the roof and wall loads with the wind pressure and uplift from the cladding areas."),
		localize('planned.coldFormed.step3', "Check the members with the sheeting restraint, the laps and web crippling at the supports, for downward load and uplift."),
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
		localize('planned.coldFormed.ref1', "{0} Part 6 Chapter 10 (hot-rolled and built-up steel; no cold-formed provisions: the US, Eurocodes and IS packs design C and Z members)", defaultCodeName()),
		localize('planned.coldFormed.ref2', "AISI S100 (North American specification for cold-formed steel structural members)"),
	],
});

// T44 / P8: composite beams (studs, deck, partial connection, construction stage, camber,
// longitudinal shear), encased and filled columns and composite slabs on steel deck are designed
// by the code pack's composite and compositeSlab tables; their fire resistance stays planned.
registerPlannedFeature({
	id: FemPlanned.compositeFire,
	part: 'fem',
	title: localize('planned.compositeFire.title', "Fire Resistance of Composite Members"),
	summary: localize('planned.compositeFire.summary', "Checks composite beams, encased and concrete-filled columns and composite slabs on steel deck in a standard fire: the temperatures of the steel, the bars and the concrete over the fire rating, and the reduced resistances. Today the composite members are designed at normal temperature; steel members alone are checked in fire where the code pack has a steel fire method."),
	steps: [
		localize('planned.compositeFire.step1', "Give the fire rating and the protection of each composite member type."),
		localize('planned.compositeFire.step2', "Find the temperatures of the section's parts from the code pack's tables or a heat transfer."),
		localize('planned.compositeFire.step3', "Check the members under the fire combination with the reduced strengths."),
	],
	inputs: [
		{ label: localize('planned.compositeFire.rating', "Fire rating"), unit: 'min', example: '90' },
		{ label: localize('planned.compositeFire.protection', "Protection"), example: localize('planned.compositeFire.protectionExample', "None (filled column)") },
	],
	outputs: [
		localize('planned.compositeFire.out1', "Utilisation of each composite member in fire"),
	],
	references: [
		localize('planned.compositeFire.ref1', "EN 1994-1-2 (structural fire design of composite members)"),
		localize('planned.compositeFire.ref2', "AISC 360 Appendix 4 (structural design for fire conditions)"),
	],
});

// Alpha 9 L7: steel joists, castellated and cellular beams, aluminium joints (EN 1999), glass,
// tensile membranes and concrete-filled composite plate walls are designed by the code pack's
// tables (04 Objects); aluminium by the US Aluminum Design Manual and membrane cutting patterns
// stay planned.
registerPlannedFeature({
	id: FemPlanned.aluminiumAdm,
	part: 'fem',
	title: localize('planned.aluminiumAdm.title', "Aluminium by the Aluminum Design Manual"),
	summary: localize('planned.aluminiumAdm.summary', "Aluminium members and joints are designed today by a code pack with partial-factor aluminium rules (EN 1999-1-1 in the Eurocodes pack). Planned: the US Aluminum Design Manual's member and connection checks in the US pack (its buckling constants by alloy and temper, element slenderness limits, welded members)."),
	steps: [
		localize('planned.aluminiumAdm.step1', "Pick the alloy and temper of the US pack's aluminium table."),
		localize('planned.aluminiumAdm.step2', "Check the members by the manual's limit states and the joints by its bolt and weld rules."),
	],
	inputs: [
		{ label: localize('planned.aluminiumAdm.alloy', "Alloy and temper"), example: '6061-T6' },
	],
	outputs: [
		localize('planned.aluminiumAdm.out1', "Aluminium member and joint utilisations by the US pack"),
	],
	references: [
		localize('planned.aluminiumAdm.ref1', "Aluminum Design Manual 2020 (Specification for Aluminum Structures)"),
	],
});

registerPlannedFeature({
	id: FemPlanned.membranePatterns,
	part: 'fem',
	title: localize('planned.membranePatterns.title', "Membrane Cutting Patterns and Free Shapes"),
	summary: localize('planned.membranePatterns.summary', "Tensile membranes and cable nets on four corners are form found, loaded and checked today (04 Objects, membrane types). Planned: boundaries of any number of corners, masts and ridge cables inside the surface, and the cutting patterns of the fabric with its compensation."),
	steps: [
		localize('planned.membranePatterns.step1', "Draw the boundary, the masts and the ridge and valley cables."),
		localize('planned.membranePatterns.step2', "Find the form and check it under the code pack's cases."),
		localize('planned.membranePatterns.step3', "Cut the surface into panels along geodesic seams and flatten them with the compensation."),
	],
	inputs: [
		{ label: localize('planned.membranePatterns.width', "Fabric width"), unit: 'mm', example: '2500' },
		{ label: localize('planned.membranePatterns.compensation', "Compensation"), unit: '%', example: '1.0' },
	],
	outputs: [
		localize('planned.membranePatterns.out1', "Cutting patterns as DXF"),
	],
	references: [
		localize('planned.membranePatterns.ref1', "TensiNet European Design Guide for Tensile Surface Structures"),
	],
});

// Alpha 9 L9: bridges (traffic loads moved along influence lines, girders by the code pack's
// concrete methods, bearings, joints and load rating), lattice towers, silos, chimneys, cooling
// towers, offshore jackets and piping are built (Project Settings, Bridges and Special
// Structures; results in the analysis charts). What stays planned:
registerPlannedFeature({
	id: FemPlanned.bridgeStages,
	part: 'fem',
	title: localize('planned.bridgeStages.title', "Bridge Construction Stages, Substructure and Fatigue"),
	summary: localize('planned.bridgeStages.summary', "Girder and slab bridges are analysed and checked today for the code pack's traffic (line girders or a deck grillage), with their bearings, joints and load rating. Planned: staged (non-composite then composite) and segmental construction with creep and shrinkage, the deck slab's own design, skewed and curved decks, cantilever overhangs, fatigue and deflection of the girders, piers and abutments in 9 Substructure, and the choice of bearing and joint products."),
	steps: [
		localize('planned.bridgeStages.step1', "Set the construction stages and the times the girders are made composite."),
		localize('planned.bridgeStages.step2', "Follow the stresses stage by stage with creep, shrinkage and relaxation."),
		localize('planned.bridgeStages.step3', "Design the deck slab, the piers and the abutments for the bearings' reactions."),
	],
	inputs: [
		{ label: localize('planned.bridgeStages.stage', "Stage duration"), unit: 'd', example: '28' },
		{ label: localize('planned.bridgeStages.skew', "Skew angle"), unit: '°', example: '15' },
	],
	outputs: [
		localize('planned.bridgeStages.out1', "Stresses at every stage and the long-term state"),
		localize('planned.bridgeStages.out2', "Fatigue stress ranges and the deck slab's bars"),
	],
	references: [
		localize('planned.bridgeStages.ref1', "AASHTO LRFD Bridge Design Specifications; EN 1992-2; IRC:112"),
	],
});

registerPlannedFeature({
	id: FemPlanned.specialStructuresMore,
	part: 'fem',
	title: localize('planned.specialStructuresMore.title', "More of the Special Structures"),
	summary: localize('planned.specialStructuresMore.summary', "Lattice towers, silos, chimneys, cooling towers, offshore jackets and piping are designed today by the code packs that cover them. Planned: guyed masts and transmission towers (ASCE 10, IS 802), ice on towers, silo hoppers and eccentric discharge, the US and Indian packs' silo and chimney rules (ACI 313, ACI 307, IS 4998), cooling tower buckling, offshore fatigue, buoyancy and pile-soil interaction, and the flexibility of pipe bends and branch connections (ASME B31.1, B31.4, B31.8)."),
	steps: [
		localize('planned.specialStructuresMore.step1', "Add the structure's form and its code's loads to the code pack."),
		localize('planned.specialStructuresMore.step2', "Check it under the pack's combinations as the built structures are."),
	],
	inputs: [
		{ label: localize('planned.specialStructuresMore.ice', "Ice thickness"), unit: 'mm', example: '12' },
	],
	outputs: [
		localize('planned.specialStructuresMore.out1', "The added structures' checks in the analysis charts and the report"),
	],
	references: [
		localize('planned.specialStructuresMore.ref1', "ASCE 10-15; IS 802; ACI 313; ACI 307; API RP 2A; ASME B31.1"),
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

// T31 / B34: confined masonry is built (design/confined_masonry.py, Sec 7.11).
