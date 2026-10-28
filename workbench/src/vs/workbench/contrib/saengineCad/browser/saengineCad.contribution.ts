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
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { ISaengineProjectService, PROJECT_PARTS, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { CadEditorPane } from './cadEditor.js';
import { CadEditorInput, CadEditorInputSerializer } from './cadEditorInput.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ArchitectureEditor } from './architectureEditor.js';
import { ArchitectureEditorInput, ArchitectureEditorInputSerializer } from './architectureEditorInput.js';
import { ARCHITECTURE_FILE, newArchitecture } from './architectureModel.js';
import { FloorPlanEditor } from './floorPlanEditor.js';
import { FloorPlanEditorInput, FloorPlanEditorInputSerializer } from './floorPlanEditorInput.js';
// Integrator glue: the Members Table registers its editor, command, undo/redo and working-copy handler.
import './floorPlanTable.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(CadEditorPane, CadEditorInput.EDITOR_ID, localize('cadEditor', "CAD Drawing")),
	[new SyncDescriptor(CadEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(CadEditorInput.ID, CadEditorInputSerializer);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(FloorPlanEditor, FloorPlanEditorInput.EDITOR_ID, localize('floorPlanEditor', "Floor Plan")),
	[new SyncDescriptor(FloorPlanEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FloorPlanEditorInput.ID, FloorPlanEditorInputSerializer);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(ArchitectureEditor, ArchitectureEditorInput.EDITOR_ID, localize('architectureEditor', "Architecture")),
	[new SyncDescriptor(ArchitectureEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(ArchitectureEditorInput.ID, ArchitectureEditorInputSerializer);

const FLOOR_PLAN_PART = PROJECT_PARTS.find(p => p.id === 'floorPlan')!;

class CadEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.cadEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@IInstantiationService instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			'*.dxf',
			{
				id: CadEditorInput.EDITOR_ID,
				label: localize('cadEditor.label', "CAD Drawing Editor"),
				detail: localize('cadEditor.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{ singlePerResource: true },
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(CadEditorInput, resource),
					options,
				}),
			}
		));

		// The project's floor plan opens as the plan view of its building model.
		this._register(editorResolverService.registerEditor(
			`**/${FLOOR_PLAN_PART.mainFile}`,
			{
				id: FloorPlanEditorInput.EDITOR_ID,
				label: localize('floorPlanEditor.label', "Floor Plan"),
				detail: localize('cadEditor.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isFloorPlan(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(FloorPlanEditorInput, resource),
					options,
				}),
			}
		));

		// The architecture beside it opens in the Architecture editor (6 BIM's Architecture entry).
		this._register(editorResolverService.registerEditor(
			`**/${ARCHITECTURE_FILE}`,
			{
				id: ArchitectureEditorInput.EDITOR_ID,
				label: localize('architectureEditor.label', "Architecture"),
				detail: localize('cadEditor.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isArchitecture(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(ArchitectureEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isArchitecture(resource: URI): boolean {
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && this.projectService.project?.type !== 'structure' && isEqual(resource, joinPath(root, FLOOR_PLAN_PART.folder, ARCHITECTURE_FILE));
	}

	private isFloorPlan(resource: URI): boolean {
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		// A special structure has no floor plan: a floor-plan.json left from before is a plain file.
		return !!root && this.projectService.project?.type !== 'structure' && isEqual(resource, joinPath(root, FLOOR_PLAN_PART.folder, FLOOR_PLAN_PART.mainFile!));
	}
}

registerWorkbenchContribution2(CadEditorResolverContribution.ID, CadEditorResolverContribution, WorkbenchPhase.BlockStartup);

/** Ctrl+Z / Ctrl+Y in the floor plan (and the architecture) undo and redo its edits to the file. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof FloorPlanEditor || pane instanceof ArchitectureEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 110;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-floor-plan', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-floor-plan', accessor => undoRedo(accessor, true));

/** The CAD command line of the floor plan, hidden until asked for (also ":" in the plan). */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.floorPlan.toggleCommandLine',
			title: localize2('floorPlan.toggleCommandLine', "Toggle Command Line"),
			category: localize2('floorPlan.category', "Floor Plan"),
			f1: true,
			precondition: ActiveEditorContext.isEqualTo(FloorPlanEditor.ID),
		});
	}

	run(accessor: ServicesAccessor): void {
		const pane = accessor.get(IEditorService).activeEditorPane;
		if (pane instanceof FloorPlanEditor) {
			pane.toggleCommandLine();
		}
	}
});

/*
 * Integrator glue: the floor plan's selection and bulk tools in the command palette. The keys
 * (Ctrl+A, Ctrl+C, Ctrl+V, Delete, ":") are the editor's own (FloorPlanEditor.onKey), so these
 * commands carry no keybindings that would run twice.
 */
const BULK_COMMANDS: readonly { readonly id: 'selectAll' | 'selectByType' | 'copyToStories' | 'mirror' | 'deleteSelection'; readonly title: ReturnType<typeof localize2> }[] = [
	{ id: 'selectAll', title: localize2('floorPlan.cmd.selectAll', "Select All on Story") },
	{ id: 'selectByType', title: localize2('floorPlan.cmd.selectByType', "Select by Type...") },
	{ id: 'copyToStories', title: localize2('floorPlan.cmd.copyToStories', "Copy Selection to Stories...") },
	{ id: 'mirror', title: localize2('floorPlan.cmd.mirror', "Mirror Selection...") },
	{ id: 'deleteSelection', title: localize2('floorPlan.cmd.deleteSelection', "Delete Selection") },
];
for (const command of BULK_COMMANDS) {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: `saengine.floorPlan.bulk.${command.id}`,
				title: command.title,
				category: localize2('floorPlan.category', "Floor Plan"),
				f1: true,
				precondition: ActiveEditorContext.isEqualTo(FloorPlanEditor.ID),
			});
		}

		async run(accessor: ServicesAccessor): Promise<void> {
			const pane = accessor.get(IEditorService).activeEditorPane;
			if (pane instanceof FloorPlanEditor) {
				await pane.runBulkAction(command.id);
			}
		}
	});
}

/** Exports every story's structural plan as DXF (the Exports page runs it): opens 5 Floor Plan and exports from it. */
CommandsRegistry.registerCommand('saengine.floorPlan.exportDxf', async (accessor: ServicesAccessor) => {
	const project = accessor.get(ISaengineProjectService).project;
	const part = partById('floorPlan');
	const editorService = accessor.get(IEditorService);
	if (!project || !part?.mainFile) {
		return;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile) });
	if (pane instanceof FloorPlanEditor) {
		await pane.exportDxf();
	}
});

/** The id of the command that opens the architecture (6 BIM's sidebar entry runs it by id). */
export const OPEN_ARCHITECTURE_COMMAND = 'saengine.architecture.open';

/**
 * Opens the project's architecture (`05 Floor Plan/architecture.json`) in the Architecture
 * editor, creating the file with the default wall, door, window and finish types first.
 */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: OPEN_ARCHITECTURE_COMMAND,
			title: localize2('saengine.openArchitecture', "Architecture"),
			category: localize2('saengine.bimCategory', "BIM"),
			metadata: { description: localize2('saengine.openArchitecture.description', "Draws the architect's walls, doors, windows and rooms on the floor plan's grids.") },
			f1: true,
		});
	}

	/** `at`: a story and an item (a wall) to show selected, from the Floor Plan's Loads list. */
	async run(accessor: ServicesAccessor, at?: { readonly story?: string; readonly id?: string }): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const fileService = accessor.get(IFileService);
		const editorService = accessor.get(IEditorService);
		const instantiationService = accessor.get(IInstantiationService);
		if (!project || project.type === 'structure') {
			return;
		}
		const resource = joinPath(project.root, FLOOR_PLAN_PART.folder, ARCHITECTURE_FILE);
		if (!await fileService.exists(resource)) {
			await fileService.writeFile(resource, VSBuffer.fromString(JSON.stringify(newArchitecture(), undefined, '\t') + '\n'));
		}
		const open = editorService.findEditors(resource).map(e => e.editor).find((e): e is ArchitectureEditorInput => e instanceof ArchitectureEditorInput);
		const input = open ?? instantiationService.createInstance(ArchitectureEditorInput, resource);
		await editorService.openEditor(input, { pinned: true });
		if (at) {
			input.requestReveal(at.story, at.id);
		}
	}
});
