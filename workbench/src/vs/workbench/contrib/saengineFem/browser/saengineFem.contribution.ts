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
