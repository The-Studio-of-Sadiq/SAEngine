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
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
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
import { registerRibbonItemHint, RibbonButtonSize, RibbonMenus } from '../../saengineRibbon/browser/ribbonRegistry.js';
import { CadEditorPane } from './cadEditor.js';
import { CadEditorInput, CadEditorInputSerializer } from './cadEditorInput.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ArchitectureEditor, ArchTool } from './architectureEditor.js';
import { ArchitectureEditorInput, ArchitectureEditorInputSerializer } from './architectureEditorInput.js';
import { ARCHITECTURE_FILE, newArchitecture } from './architectureModel.js';
import { FloorPlanEditor, FloorPlanTool } from './floorPlanEditor.js';
import { FloorPlanEditorInput, FloorPlanEditorInputSerializer } from './floorPlanEditorInput.js';
// Integrator glue: the Members Table registers its editor, command, undo/redo and working-copy handler.
import './floorPlanTable.js';
import './floorPlanTables.js';
import './cadDraftRibbon.contribution.js';
import { registerPartEditor } from '../../saengineProject/browser/projectParts.js';

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
		this._register(registerPartEditor(FLOOR_PLAN_PART.id, FloorPlanEditorInput.EDITOR_ID));
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
			menu: { id: RibbonMenus.Plan, group: '3_Loads', order: 4 },
		});
	}

	run(accessor: ServicesAccessor): void {
		const pane = accessor.get(IEditorService).activeEditorPane;
		if (pane instanceof FloorPlanEditor) {
			pane.toggleGridLines();
		}
	}
});
registerRibbonItemHint('saengine.floorPlan.toggleGridLines', { size: 'small', label: localize('plan.rib.gridLines', "Grid Lines") }, RibbonMenus.Plan);

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
const BULK_COMMANDS: readonly { readonly id: 'selectAll' | 'selectByType' | 'copyToStories' | 'mirror' | 'deleteSelection'; readonly title: ReturnType<typeof localize2>; readonly shortLabel: string; readonly icon: ThemeIcon; readonly order: number }[] = [
	{ id: 'copyToStories', title: localize2('floorPlan.cmd.copyToStories', "Copy Selection to Stories..."), shortLabel: localize('plan.rib.copyStories', "Copy to Stories"), icon: Codicon.copy, order: 5 },
	{ id: 'mirror', title: localize2('floorPlan.cmd.mirror', "Mirror Selection..."), shortLabel: localize('plan.rib.mirror', "Mirror"), icon: Codicon.mirror, order: 6 },
	{ id: 'selectAll', title: localize2('floorPlan.cmd.selectAll', "Select All on Story"), shortLabel: localize('plan.rib.selectAll', "Select All"), icon: Codicon.selection, order: 7 },
	{ id: 'selectByType', title: localize2('floorPlan.cmd.selectByType', "Select by Type..."), shortLabel: localize('plan.rib.selectType', "Select by Type"), icon: Codicon.filter, order: 8 },
	{ id: 'deleteSelection', title: localize2('floorPlan.cmd.deleteSelection', "Delete Selection"), shortLabel: localize('plan.rib.delSel', "Delete Selected"), icon: Codicon.clearAll, order: 9 },
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
				menu: { id: RibbonMenus.Plan, group: '2_Edit', order: command.order },
			});
		}

		async run(accessor: ServicesAccessor): Promise<void> {
			const pane = accessor.get(IEditorService).activeEditorPane;
			if (pane instanceof FloorPlanEditor) {
				await pane.runBulkAction(command.id);
			}
		}
	});
	registerRibbonItemHint(fullId, { size: 'small', label: command.shortLabel }, RibbonMenus.Plan);
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
	shortLabel: string,
	icon: ThemeIcon,
	menuId: MenuId,
	group: string,
	order: number,
	size: RibbonButtonSize | undefined,
	runWithEditor: (editor: FloorPlanEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('floorPlan.category', "Floor Plan"),
				icon,
				f1: false,
				precondition: projectOpen,
				menu: { id: menuId, group, order },
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await activeFloorPlanEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
	if (size) {
		registerRibbonItemHint(id, { size, label: shortLabel }, menuId);
	}
}

for (const [order, tool, title, shortLabel, icon, size] of [
	[1, 'select', localize2('plan.rib.selectTitle', "Select Structural Members"), localize('plan.rib.select', "Select"), Codicon.inspect, 'small'],
	[2, 'column', localize2('plan.rib.columnTitle', "Place Column"), localize('plan.rib.column', "Column"), Codicon.primitiveSquare, 'large'],
	[3, 'beam', localize2('plan.rib.beamTitle', "Place Beam"), localize('plan.rib.beam', "Beam"), Codicon.dash, 'large'],
	[4, 'wall', localize2('plan.rib.wallTitle', "Place Structural Wall"), localize('plan.rib.wall', "Wall"), Codicon.splitHorizontal, 'large'],
	[5, 'slab', localize2('plan.rib.slabTitle', "Place Slab in Bay"), localize('plan.rib.slab', "Slab"), Codicon.layout, 'large'],
	[6, 'polygonSlab', localize2('plan.rib.polySlabTitle', "Draw Polygon Slab"), localize('plan.rib.polySlab', "Polygon Slab"), Codicon.symbolConstant, 'small'],
	[7, 'fill', localize2('plan.rib.fillTitle', "Fill Grid with Members"), localize('plan.rib.fill', "Fill Grid"), Codicon.table, 'small'],
] as readonly [number, FloorPlanTool, ReturnType<typeof localize2>, string, ThemeIcon, RibbonButtonSize][]) {
	registerPlanCommand(`saengine.floorPlan.tool.${tool}`, title, shortLabel, icon, RibbonMenus.Plan, '1_Place', order, size, e => e.selectTool(tool));
}
registerPlanCommand('saengine.floorPlan.openSubstructure', localize2('plan.rib.footingsTitle', "Place Footings in 9 Substructure"), localize('plan.rib.footings', "Footings"), Codicon.layers, RibbonMenus.Plan, '1_Place', 8, 'small', e => e.openSubstructurePart());

for (const [order, tool, title, shortLabel, icon] of [
	[1, 'move', localize2('plan.rib.moveTitle', "Move Member"), localize('plan.rib.move', "Move"), Codicon.move],
	[2, 'rotate', localize2('plan.rib.rotateTitle', "Rotate Column"), localize('plan.rib.rotate', "Rotate"), Codicon.refresh],
	[3, 'delete', localize2('plan.rib.deleteTitle', "Delete Member Tool"), localize('plan.rib.delete', "Delete"), Codicon.trash],
] as readonly [number, FloorPlanTool, ReturnType<typeof localize2>, string, ThemeIcon][]) {
	registerPlanCommand(`saengine.floorPlan.tool.${tool}`, title, shortLabel, icon, RibbonMenus.Plan, '2_Edit', order, 'small', e => e.selectTool(tool));
}
registerPlanCommand('saengine.floorPlan.gridSystems', localize2('plan.rib.gridSystemsTitle', "Grid Systems..."), localize('plan.rib.gridSystems', "Grid Systems..."), Codicon.compass, RibbonMenus.Plan, '2_Edit', 5, 'large', e => e.openGridSystems());
registerPlanCommand('saengine.floorPlan.typicalFloors', localize2('plan.rib.typicalTitle', "Configure Typical Floors"), localize('plan.rib.typical', "Typical Floors"), Codicon.layers, RibbonMenus.Plan, '2_Edit', 4, 'large', e => e.openTypicalFloors());

const FloorPlanConvertSubmenu = MenuId.for('saengine.ribbon.plan.convert');
registerRibbonItemHint(FloorPlanConvertSubmenu.id, { size: 'small' }, RibbonMenus.Plan);
MenuRegistry.appendMenuItem(RibbonMenus.Plan, {
	submenu: FloorPlanConvertSubmenu,
	title: localize2('plan.rib.convertSub', "Convert Draft"),
	icon: Codicon.arrowSwap,
	group: '2_Edit',
	order: 10,
});
registerPlanCommand('saengine.floorPlan.convert.beam', localize2('plan.rib.convBeam', "Convert Draft Lines to Beams"), localize('plan.rib.convBeamShort', "Convert to Beams"), Codicon.dash, FloorPlanConvertSubmenu, '1_convert', 1, undefined, e => e.convertDrafting('beam'));
registerPlanCommand('saengine.floorPlan.convert.wall', localize2('plan.rib.convWall', "Convert Draft Lines to Walls"), localize('plan.rib.convWallShort', "Convert to Walls"), Codicon.splitHorizontal, FloorPlanConvertSubmenu, '1_convert', 2, undefined, e => e.convertDrafting('wall'));
registerPlanCommand('saengine.floorPlan.convert.slab', localize2('plan.rib.convSlab', "Convert Draft Polygon to Slab"), localize('plan.rib.convSlabShort', "Convert to Slab"), Codicon.layout, FloorPlanConvertSubmenu, '1_convert', 3, undefined, e => e.convertDrafting('slab'));

registerPlanCommand('saengine.floorPlan.loads.line', localize2('plan.rib.lineLoadTitle', "Add Line Load on Selected Beams"), localize('plan.rib.lineLoad', "Line Load"), Codicon.arrowDown, RibbonMenus.Plan, '3_Loads', 1, 'small', e => e.openMemberLineLoad());
registerPlanCommand('saengine.floorPlan.loads.point', localize2('plan.rib.pointLoadTitle', "Add Point Load on Selected Member"), localize('plan.rib.pointLoad', "Point Load"), Codicon.arrowSmallDown, RibbonMenus.Plan, '3_Loads', 2, 'small', e => e.openMemberPointLoad());
registerPlanCommand('saengine.floorPlan.zoomExtents', localize2('plan.rib.zoomTitle', "Zoom Floor Plan to Extents"), localize('plan.rib.zoom', "Zoom Extents"), Codicon.screenFull, RibbonMenus.Plan, '3_Loads', 3, 'small', e => e.zoomToExtents());

registerPlanCommand('saengine.floorPlan.underlay.attach', localize2('plan.rib.attachUnderlayTitle', "Attach Architectural Underlay..."), localize('plan.rib.attachUnderlay', "Attach Underlay"), Codicon.fileMedia, RibbonMenus.Plan, '4_Underlay', 1, 'large', e => e.attachUnderlayFile());
registerPlanCommand('saengine.floorPlan.underlay.toggle', localize2('plan.rib.toggleUnderlayTitle', "Show or Hide Underlay"), localize('plan.rib.toggleUnderlay', "Show / Hide"), Codicon.eye, RibbonMenus.Plan, '4_Underlay', 2, 'small', e => e.toggleUnderlayVisibility());

const FloorPlanUnderlaySubmenu = MenuId.for('saengine.ribbon.plan.underlay');
registerRibbonItemHint(FloorPlanUnderlaySubmenu.id, { size: 'small' }, RibbonMenus.Plan);
MenuRegistry.appendMenuItem(RibbonMenus.Plan, {
	submenu: FloorPlanUnderlaySubmenu,
	title: localize2('plan.rib.underlaySub', "Underlay Tools"),
	icon: Codicon.compass,
	group: '4_Underlay',
	order: 3,
});
registerPlanCommand('saengine.floorPlan.underlay.calibrate', localize2('plan.rib.calUnderlay', "Calibrate Underlay Scale..."), localize('plan.rib.calUnderlayShort', "Calibrate Scale..."), Codicon.symbolRuler, FloorPlanUnderlaySubmenu, '1_underlay', 1, undefined, e => e.beginUnderlayPick('calibrate'));
registerPlanCommand('saengine.floorPlan.underlay.move', localize2('plan.rib.moveUnderlay', "Move Underlay"), localize('plan.rib.moveUnderlayShort', "Move Underlay"), Codicon.move, FloorPlanUnderlaySubmenu, '1_underlay', 2, undefined, e => e.beginUnderlayPick('move'));
registerPlanCommand('saengine.floorPlan.underlay.rotate', localize2('plan.rib.rotUnderlay', "Rotate Underlay..."), localize('plan.rib.rotUnderlayShort', "Rotate Underlay..."), Codicon.refresh, FloorPlanUnderlaySubmenu, '1_underlay', 3, undefined, e => e.beginUnderlayPick('rotate'));
registerPlanCommand('saengine.floorPlan.underlay.align', localize2('plan.rib.alignUnderlay', "Align Underlay to Grid"), localize('plan.rib.alignUnderlayShort', "Align to Grid"), Codicon.compass, FloorPlanUnderlaySubmenu, '1_underlay', 4, undefined, e => e.beginUnderlayPick('align'));
registerPlanCommand('saengine.floorPlan.underlay.page', localize2('plan.rib.pageUnderlay', "Select PDF Underlay Page..."), localize('plan.rib.pageUnderlayShort', "Underlay Page..."), Codicon.filePdf, FloorPlanUnderlaySubmenu, '1_underlay', 5, undefined, e => e.selectUnderlayPage());
registerPlanCommand('saengine.floorPlan.underlay.lock', localize2('plan.rib.lockUnderlay', "Lock or Unlock Underlay"), localize('plan.rib.lockUnderlayShort', "Lock / Unlock Underlay"), Codicon.lock, FloorPlanUnderlaySubmenu, '1_underlay', 6, undefined, e => e.toggleUnderlayLocked());
registerPlanCommand('saengine.floorPlan.underlay.remove', localize2('plan.rib.removeUnderlay', "Remove Underlay"), localize('plan.rib.removeUnderlayShort', "Remove Underlay"), Codicon.trash, FloorPlanUnderlaySubmenu, '1_underlay', 7, undefined, e => e.removeUnderlayFile());

registerPlanCommand('saengine.floorPlan.workbook.export', localize2('plan.rib.expXlsxTitle', "Export Floor Plan to Excel..."), localize('plan.rib.expXlsx', "Export Excel"), Codicon.export, RibbonMenus.Plan, '5_ModelData', 4, 'small', e => e.exportWorkbook());
registerPlanCommand('saengine.floorPlan.workbook.import', localize2('plan.rib.impXlsxTitle', "Import Floor Plan from Excel..."), localize('plan.rib.impXlsx', "Import Excel"), Codicon.cloudDownload, RibbonMenus.Plan, '5_ModelData', 5, 'small', e => e.importWorkbook());


function registerArchCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	shortLabel: string,
	icon: ThemeIcon,
	group: string,
	order: number,
	size: RibbonButtonSize,
	runWithEditor: (editor: ArchitectureEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.bimCategory', "BIM"),
				icon,
				f1: false,
				precondition: projectOpen,
				menu: { id: RibbonMenus.Architecture, group, order },
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await activeArchitectureEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
	registerRibbonItemHint(id, { size, label: shortLabel }, RibbonMenus.Architecture);
}

for (const [group, order, tool, title, shortLabel, icon, size] of [
	['1_Build', 1, 'select', localize2('arch.rib.selectTitle', "Select Architectural Element"), localize('arch.rib.select', "Select"), Codicon.inspect, 'small'],
	['1_Build', 2, 'wall', localize2('arch.rib.wallTitle', "Draw Wall"), localize('arch.rib.wall', "Wall"), Codicon.splitHorizontal, 'large'],
	['1_Build', 3, 'door', localize2('arch.rib.doorTitle', "Place Door"), localize('arch.rib.door', "Door"), Codicon.signIn, 'large'],
	['1_Build', 4, 'window', localize2('arch.rib.windowTitle', "Place Window"), localize('arch.rib.window', "Window"), Codicon.window, 'large'],
	['1_Build', 5, 'curtainWall', localize2('arch.rib.curtainTitle', "Draw Curtain Wall"), localize('arch.rib.curtain', "Curtain Wall"), Codicon.layoutPanelJustify, 'small'],
	['1_Build', 6, 'delete', localize2('arch.rib.deleteTitle', "Delete Element Tool"), localize('arch.rib.delete', "Delete"), Codicon.trash, 'small'],
	['2_RoomsAndRoofs', 1, 'room', localize2('arch.rib.roomTitle', "Place Room"), localize('arch.rib.room', "Room"), Codicon.symbolNamespace, 'large'],
	['2_RoomsAndRoofs', 2, 'separator', localize2('arch.rib.sepTitle', "Draw Room Separator"), localize('arch.rib.sep', "Separator"), Codicon.dash, 'small'],
	['2_RoomsAndRoofs', 3, 'ceiling', localize2('arch.rib.ceilTitle', "Place Ceiling"), localize('arch.rib.ceil', "Ceiling"), Codicon.layers, 'small'],
	['2_RoomsAndRoofs', 4, 'roof', localize2('arch.rib.roofTitle', "Draw Roof"), localize('arch.rib.roof', "Roof"), Codicon.home, 'large'],
	['2_RoomsAndRoofs', 5, 'ramp', localize2('arch.rib.rampTitle', "Draw Ramp"), localize('arch.rib.ramp', "Ramp"), Codicon.arrowUp, 'small'],
	['2_RoomsAndRoofs', 6, 'railing', localize2('arch.rib.railingTitle', "Draw Railing"), localize('arch.rib.railing', "Railing"), Codicon.symbolArray, 'small'],
	['3_ComponentsAndMass', 1, 'component', localize2('arch.rib.compTitle', "Place Component"), localize('arch.rib.comp', "Component"), Codicon.symbolProperty, 'large'],
	['3_ComponentsAndMass', 2, 'mass', localize2('arch.rib.massTitle', "Draw Conceptual Mass"), localize('arch.rib.mass', "Mass"), Codicon.package, 'large'],
] as readonly [string, number, ArchTool, ReturnType<typeof localize2>, string, ThemeIcon, RibbonButtonSize][]) {
	registerArchCommand(`saengine.architecture.tool.${tool}`, title, shortLabel, icon, group, order, size, e => e.selectTool(tool));
}

registerArchCommand('saengine.architecture.toggleStructure', localize2('arch.rib.structTitle', "Show or Hide Structure Overlay"), localize('arch.rib.struct', "Structure Overlay"), Codicon.eye, '3_ComponentsAndMass', 3, 'small', e => e.toggleStructureOverlay());
registerArchCommand('saengine.architecture.zoomExtents', localize2('arch.rib.zoomTitle', "Zoom Architecture to Extents"), localize('arch.rib.zoom', "Zoom Extents"), Codicon.screenFull, '3_ComponentsAndMass', 4, 'small', e => e.zoomToExtents());
registerArchCommand('saengine.architecture.open3d', localize2('arch.rib.open3dTitle', "Show Architecture in 3D View"), localize('arch.rib.open3d', "3D View"), Codicon.globe, '3_ComponentsAndMass', 5, 'small', e => e.open3dView());
registerArchCommand('saengine.architecture.openFloorPlan', localize2('arch.rib.floorPlanTitle', "Open Structural Floor Plan"), localize('arch.rib.floorPlan', "Floor Plan"), Codicon.layoutPanel, '3_ComponentsAndMass', 6, 'small', e => e.openFloorPlanView());

registerArchCommand('saengine.architecture.typesLibrary', localize2('arch.rib.typesTitle', "Open Architectural Types Library"), localize('arch.rib.types', "Types Library"), Codicon.library, '4_TypesAndImport', 1, 'large', e => e.openTypesLibraryPanel());
registerArchCommand('saengine.architecture.importIfc', localize2('arch.rib.impIfcTitle', "Import Architect's IFC..."), localize('arch.rib.impIfc', "Import IFC"), Codicon.cloudDownload, '4_TypesAndImport', 2, 'small', e => e.importIfcFile());
registerArchCommand('saengine.architecture.importDrawing', localize2('arch.rib.impDwgTitle', "Import Architect's DWG/DXF..."), localize('arch.rib.impDwg', "Import DWG/DXF"), Codicon.fileMedia, '4_TypesAndImport', 3, 'small', e => e.importDrawingFile());
