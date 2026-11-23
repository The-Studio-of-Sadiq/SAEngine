/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
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
import { ArchitectureEditor, ArchTool } from './architectureEditor.js';
import { ArchitectureEditorInput, ArchitectureEditorInputSerializer } from './architectureEditorInput.js';
import { ARCHITECTURE_FILE, newArchitecture } from './architectureModel.js';
import { FloorPlanEditor, FloorPlanTool } from './floorPlanEditor.js';
import { FloorPlanEditorInput, FloorPlanEditorInputSerializer } from './floorPlanEditorInput.js';
import { MembersTableEditor } from './floorPlanTable.js';
// Integrator glue: the Members Table registers its editor, command, undo/redo and working-copy handler.
import './floorPlanTables.js';
import './cadDraftRibbon.contribution.js';

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
			icon: Codicon.terminal,
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

/** Shows or hides the floor plan's grid lines (the grid stays; snapping to it still works). */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.floorPlan.toggleGridLines',
			title: localize2('floorPlan.toggleGridLines', "Toggle Grid Lines"),
			category: localize2('floorPlan.category', "Floor Plan"),
			icon: Codicon.symbolNumeric,
			f1: true,
			precondition: ActiveEditorContext.isEqualTo(FloorPlanEditor.ID),
		});
	}

	run(accessor: ServicesAccessor): void {
		const pane = accessor.get(IEditorService).activeEditorPane;
		if (pane instanceof FloorPlanEditor) {
			pane.toggleGridLines();
		}
	}
});

/** Focus the floor plan's Properties panel (AutoCAD PROPERTIES / PR / Ctrl+1). */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.floorPlan.properties',
			title: localize2('floorPlan.properties', "Focus Properties"),
			category: localize2('floorPlan.category', "Floor Plan"),
			f1: true,
			precondition: ActiveEditorContext.isEqualTo(FloorPlanEditor.ID),
			keybinding: {
				weight: KeybindingWeight.WorkbenchContrib,
				primary: KeyMod.CtrlCmd | KeyCode.Digit1,
				when: ActiveEditorContext.isEqualTo(FloorPlanEditor.ID),
			},
		});
	}

	run(accessor: ServicesAccessor): void {
		const pane = accessor.get(IEditorService).activeEditorPane;
		if (pane instanceof FloorPlanEditor) {
			pane.focusProperties();
		}
	}
});

/*
 * Integrator glue: the floor plan's selection and bulk tools in the command palette. The keys
 * (Ctrl+A, Ctrl+C, Ctrl+V, Delete, ":") are the editor's own (FloorPlanEditor.onKey), so these
 * commands carry no keybindings that would run twice.
 */
const BULK_COMMANDS: readonly { readonly id: 'selectAll' | 'selectByType' | 'copyToStories' | 'mirror' | 'deleteSelection'; readonly title: ReturnType<typeof localize2>; readonly icon: ThemeIcon }[] = [
	{ id: 'copyToStories', title: localize2('floorPlan.cmd.copyToStories', "Copy Selection to Stories..."), icon: Codicon.copy },
	{ id: 'mirror', title: localize2('floorPlan.cmd.mirror', "Mirror Selection..."), icon: Codicon.mirror },
	{ id: 'selectAll', title: localize2('floorPlan.cmd.selectAll', "Select All on Story"), icon: Codicon.selection },
	{ id: 'selectByType', title: localize2('floorPlan.cmd.selectByType', "Select by Type..."), icon: Codicon.filter },
	{ id: 'deleteSelection', title: localize2('floorPlan.cmd.deleteSelection', "Delete Selection"), icon: Codicon.clearAll },
];
for (const command of BULK_COMMANDS) {
	const fullId = `saengine.floorPlan.bulk.${command.id}`;
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: fullId,
				title: command.title,
				category: localize2('floorPlan.category', "Floor Plan"),
				icon: command.icon,
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

// ─────────────────────── Contextual Ribbon Commands: Plan & Architecture (U4) ───────────────────────

const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

async function activeFloorPlanEditor(accessor: ServicesAccessor): Promise<FloorPlanEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	if (editorService.activeEditorPane instanceof FloorPlanEditor) {
		return editorService.activeEditorPane;
	}
	const project = accessor.get(ISaengineProjectService).project;
	if (!project || !FLOOR_PLAN_PART.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, FLOOR_PLAN_PART.folder, FLOOR_PLAN_PART.mainFile), options: { pinned: true } });
	return pane instanceof FloorPlanEditor ? pane : undefined;
}

async function activeArchitectureEditor(accessor: ServicesAccessor): Promise<ArchitectureEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	if (editorService.activeEditorPane instanceof ArchitectureEditor) {
		return editorService.activeEditorPane;
	}
	await accessor.get(ICommandService).executeCommand(OPEN_ARCHITECTURE_COMMAND);
	return editorService.activeEditorPane instanceof ArchitectureEditor ? editorService.activeEditorPane : undefined;
}

function registerPlanCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	icon: ThemeIcon,
	runWithEditor: (editor: FloorPlanEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('floorPlan.category', "Floor Plan"),
				icon,
				f1: true,
				precondition: projectOpen,
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await activeFloorPlanEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
}

for (const [tool, title, icon] of [
	['select', localize2('plan.rib.selectTitle', "Select Structural Members"), Codicon.inspect],
	['column', localize2('plan.rib.columnTitle', "Place Column"), Codicon.primitiveSquare],
	['beam', localize2('plan.rib.beamTitle', "Place Beam"), Codicon.dash],
	['wall', localize2('plan.rib.wallTitle', "Place Structural Wall"), Codicon.splitHorizontal],
	['slab', localize2('plan.rib.slabTitle', "Place Slab in Bay"), Codicon.layout],
	['polygonSlab', localize2('plan.rib.polySlabTitle', "Draw Polygon Slab"), Codicon.symbolConstant],
	['fill', localize2('plan.rib.fillTitle', "Fill Grid with Members"), Codicon.table],
	['move', localize2('plan.rib.moveTitle', "Move Member"), Codicon.move],
	['rotate', localize2('plan.rib.rotateTitle', "Rotate Column"), Codicon.refresh],
	['delete', localize2('plan.rib.deleteTitle', "Delete Member Tool"), Codicon.trash],
] as readonly [FloorPlanTool, ReturnType<typeof localize2>, ThemeIcon][]) {
	registerPlanCommand(`saengine.floorPlan.tool.${tool}`, title, icon, e => e.selectTool(tool));
}

registerPlanCommand('saengine.floorPlan.openSubstructure', localize2('plan.rib.footingsTitle', "Place Footings in 9 Substructure"), Codicon.layers, e => e.openSubstructurePart());
registerPlanCommand('saengine.floorPlan.typicalFloors', localize2('plan.rib.typicalTitle', "Configure Typical Floors"), Codicon.layers, e => e.openTypicalFloors());
registerPlanCommand('saengine.floorPlan.convert.beam', localize2('plan.rib.convBeam', "Convert Draft Lines to Beams"), Codicon.dash, e => e.convertDrafting('beam'));
registerPlanCommand('saengine.floorPlan.convert.wall', localize2('plan.rib.convWall', "Convert Draft Lines to Walls"), Codicon.splitHorizontal, e => e.convertDrafting('wall'));
registerPlanCommand('saengine.floorPlan.convert.slab', localize2('plan.rib.convSlab', "Convert Draft Polygon to Slab"), Codicon.layout, e => e.convertDrafting('slab'));
registerPlanCommand('saengine.floorPlan.loads.line', localize2('plan.rib.lineLoadTitle', "Add Line Load on Selected Beams"), Codicon.arrowDown, e => e.openMemberLineLoad());
registerPlanCommand('saengine.floorPlan.loads.point', localize2('plan.rib.pointLoadTitle', "Add Point Load on Selected Member"), Codicon.arrowSmallDown, e => e.openMemberPointLoad());
registerPlanCommand('saengine.floorPlan.zoomExtents', localize2('plan.rib.zoomTitle', "Zoom Floor Plan to Extents"), Codicon.screenFull, e => e.zoomToExtents());
registerPlanCommand('saengine.floorPlan.underlay.attach', localize2('plan.rib.attachUnderlayTitle', "Attach Architectural Underlay..."), Codicon.fileMedia, e => e.attachUnderlayFile());
registerPlanCommand('saengine.floorPlan.underlay.attachPointCloud', localize2('plan.rib.attachPointCloudTitle', "Attach Point Cloud Scan..."), Codicon.cloudUpload, e => e.attachPointCloudFile());
registerPlanCommand('saengine.floorPlan.underlay.toggle', localize2('plan.rib.toggleUnderlayTitle', "Show or Hide Underlay"), Codicon.eye, e => e.toggleUnderlayVisibility());
registerPlanCommand('saengine.floorPlan.underlay.calibrate', localize2('plan.rib.calUnderlay', "Calibrate Underlay Scale..."), Codicon.symbolRuler, e => e.beginUnderlayPick('calibrate'));
registerPlanCommand('saengine.floorPlan.underlay.move', localize2('plan.rib.moveUnderlay', "Move Underlay"), Codicon.move, e => e.beginUnderlayPick('move'));
registerPlanCommand('saengine.floorPlan.underlay.rotate', localize2('plan.rib.rotUnderlay', "Rotate Underlay..."), Codicon.refresh, e => e.beginUnderlayPick('rotate'));
registerPlanCommand('saengine.floorPlan.underlay.align', localize2('plan.rib.alignUnderlay', "Align Underlay to Grid"), Codicon.compass, e => e.beginUnderlayPick('align'));
registerPlanCommand('saengine.floorPlan.underlay.page', localize2('plan.rib.pageUnderlay', "Select PDF Underlay Page..."), Codicon.filePdf, e => e.selectUnderlayPage());
registerPlanCommand('saengine.floorPlan.underlay.lock', localize2('plan.rib.lockUnderlay', "Lock or Unlock Underlay"), Codicon.lock, e => e.toggleUnderlayLocked());
registerPlanCommand('saengine.floorPlan.underlay.remove', localize2('plan.rib.removeUnderlay', "Remove Underlay"), Codicon.trash, e => e.removeUnderlayFile());
registerPlanCommand('saengine.floorPlan.workbook.export', localize2('plan.rib.expXlsxTitle', "Export Floor Plan to Excel..."), Codicon.export, e => e.exportWorkbook());
registerPlanCommand('saengine.floorPlan.workbook.import', localize2('plan.rib.impXlsxTitle', "Import Floor Plan from Excel..."), Codicon.cloudDownload, e => e.importWorkbook());

function registerMembersTableCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	runWithEditor: (editor: MembersTableEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('floorPlan.category', "Floor Plan"),
				f1: true,
				precondition: ActiveEditorContext.isEqualTo(MembersTableEditor.ID),
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const pane = accessor.get(IEditorService).activeEditorPane;
			if (pane instanceof MembersTableEditor) {
				await runWithEditor(pane);
			}
		}
	});
}

registerMembersTableCommand('saengine.membersTable.filterAll', localize2('membersTable.cmd.filterAll', "Members Table: Show All Kinds"), e => e.membersTable.setKindFilter(undefined));
registerMembersTableCommand('saengine.membersTable.filterColumns', localize2('membersTable.cmd.filterColumns', "Members Table: Filter Columns"), e => e.membersTable.setKindFilter('column'));
registerMembersTableCommand('saengine.membersTable.filterBeams', localize2('membersTable.cmd.filterBeams', "Members Table: Filter Beams"), e => e.membersTable.setKindFilter('beam'));
registerMembersTableCommand('saengine.membersTable.filterWalls', localize2('membersTable.cmd.filterWalls', "Members Table: Filter Walls"), e => e.membersTable.setKindFilter('wall'));
registerMembersTableCommand('saengine.membersTable.filterSlabs', localize2('membersTable.cmd.filterSlabs', "Members Table: Filter Slabs"), e => e.membersTable.setKindFilter('slab'));
registerMembersTableCommand('saengine.membersTable.resetFilters', localize2('membersTable.cmd.resetFilters', "Members Table: Reset Filters"), e => e.membersTable.resetFilters());
registerMembersTableCommand('saengine.membersTable.selectAll', localize2('membersTable.cmd.selectAll', "Members Table: Select All Shown"), e => e.membersTable.selectAllRows());
registerMembersTableCommand('saengine.membersTable.clearSelection', localize2('membersTable.cmd.clearSelection', "Members Table: Clear Selection"), e => e.membersTable.clearSelection());
registerMembersTableCommand('saengine.membersTable.focusSearch', localize2('membersTable.cmd.focusSearch', "Members Table: Find Member"), e => e.membersTable.focusSearch());
registerMembersTableCommand('saengine.membersTable.sortById', localize2('membersTable.cmd.sortById', "Members Table: Sort by Mark"), e => e.membersTable.sortBy('id'));
registerMembersTableCommand('saengine.membersTable.sortByStory', localize2('membersTable.cmd.sortByStory', "Members Table: Sort by Story"), e => e.membersTable.sortBy('story'));
registerMembersTableCommand('saengine.membersTable.exportCsv', localize2('membersTable.cmd.exportCsv', "Members Table: Export CSV..."), e => e.membersTable.exportTableCsv());

function registerArchCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	icon: ThemeIcon,
	runWithEditor: (editor: ArchitectureEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.bimCategory', "BIM"),
				icon,
				f1: true,
				precondition: projectOpen,
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await activeArchitectureEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
}

for (const [tool, title, icon] of [
	['select', localize2('arch.rib.selectTitle', "Select Architectural Element"), Codicon.inspect],
	['wall', localize2('arch.rib.wallTitle', "Draw Wall"), Codicon.splitHorizontal],
	['door', localize2('arch.rib.doorTitle', "Place Door"), Codicon.signIn],
	['window', localize2('arch.rib.windowTitle', "Place Window"), Codicon.window],
	['curtainWall', localize2('arch.rib.curtainTitle', "Draw Curtain Wall"), Codicon.layoutPanelJustify],
	['delete', localize2('arch.rib.deleteTitle', "Delete Element Tool"), Codicon.trash],
	['room', localize2('arch.rib.roomTitle', "Place Room"), Codicon.symbolNamespace],
	['separator', localize2('arch.rib.sepTitle', "Draw Room Separator"), Codicon.dash],
	['ceiling', localize2('arch.rib.ceilTitle', "Place Ceiling"), Codicon.layers],
	['roof', localize2('arch.rib.roofTitle', "Draw Roof"), Codicon.home],
	['ramp', localize2('arch.rib.rampTitle', "Draw Ramp"), Codicon.arrowUp],
	['railing', localize2('arch.rib.railingTitle', "Draw Railing"), Codicon.symbolArray],
	['component', localize2('arch.rib.compTitle', "Place Component"), Codicon.symbolProperty],
	['mass', localize2('arch.rib.massTitle', "Draw Conceptual Mass"), Codicon.package],
] as readonly [ArchTool, ReturnType<typeof localize2>, ThemeIcon][]) {
	registerArchCommand(`saengine.architecture.tool.${tool}`, title, icon, e => e.selectTool(tool));
}

registerArchCommand('saengine.architecture.toggleStructure', localize2('arch.rib.structTitle', "Show or Hide Structure Overlay"), Codicon.eye, e => e.toggleStructureOverlay());
registerArchCommand('saengine.architecture.zoomExtents', localize2('arch.rib.zoomTitle', "Zoom Architecture to Extents"), Codicon.screenFull, e => e.zoomToExtents());
registerArchCommand('saengine.architecture.open3d', localize2('arch.rib.open3dTitle', "Show Architecture in 3D View"), Codicon.globe, e => e.open3dView());
registerArchCommand('saengine.architecture.openFloorPlan', localize2('arch.rib.floorPlanTitle', "Open Structural Floor Plan"), Codicon.layoutPanel, e => e.openFloorPlanView());
registerArchCommand('saengine.architecture.typesLibrary', localize2('arch.rib.typesTitle', "Open Architectural Types Library"), Codicon.library, e => e.openTypesLibraryPanel());
registerArchCommand('saengine.architecture.importIfc', localize2('arch.rib.impIfcTitle', "Import Architect's IFC..."), Codicon.cloudDownload, e => e.importIfcFile());
registerArchCommand('saengine.architecture.importDrawing', localize2('arch.rib.impDwgTitle', "Import Architect's DWG/DXF..."), Codicon.fileMedia, e => e.importDrawingFile());
registerArchCommand('saengine.architecture.checkRampsUi', localize2('arch.rib.checkRampsTitle', "Check Ramps Against Code Pack"), Codicon.checkAll, e => e.runRampChecks());
registerArchCommand('saengine.architecture.clearSelection', localize2('arch.rib.clearSelTitle', "Clear Architecture Selection"), Codicon.clearAll, e => e.clearSelection());
