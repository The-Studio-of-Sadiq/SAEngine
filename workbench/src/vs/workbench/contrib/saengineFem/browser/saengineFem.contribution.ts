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
import { CRACK_WIDTHS_FEATURE, CRACKED_SLAB_DEFLECTION_FEATURE, DESIGN_REINFORCEMENT_COMMAND } from './femDesign.js';
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

// ── Planned features (MVP: methods beyond BNBC 2020, shown but not computed) ──

registerPlannedFeature({
	id: CRACKED_SLAB_DEFLECTION_FEATURE,
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
	id: CRACK_WIDTHS_FEATURE,
	part: 'fem',
	title: localize('fem.planned.crackWidths.title', "Crack Widths of Beams, Slabs and Walls"),
	summary: localize('fem.planned.crackWidths.summary', "Calculated crack widths under service loads for beams, slabs and walls, checked against exposure limits. Today crack widths are checked for water tanks only."),
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
