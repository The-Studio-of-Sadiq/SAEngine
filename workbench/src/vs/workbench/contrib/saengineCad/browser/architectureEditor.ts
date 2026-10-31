/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi, CadEntitySpec, CadGeneratedDrawing, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isEditableElement, isHTMLElement } from '../../../../base/browser/dom.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, IReference } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath, relativePath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { IPartSectionOptions } from '../../../services/saengineProject/common/partSections.js';
import { BNBC } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { propertyLink } from '../../saengineModel/browser/propertySheetView.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { addCurtainWall, addOpening, addRailing, addRamp, addRoof, addRoom, addSeparator, addWall, ARCH_LAYER_SPECS, ArchKind, architectureDrawing, centreLine, curtainWeight, elevationsOf, findRoom, IArchDrawing, IArchitecture, IArchRef, IArchWall, ICurtainWall, IDoor, IRailing, IRamp, IRoof, IRoom, itemOf, IWindow, openingSize, parseArchitecture, pathLength, pickItem, pointAlong, projectOnto, railingOf, rampGradient, removeItem, roofWeight, storyCounts, structureUnder, updateItem, wallLevels, wallsOnStory, wallSnapSegments, wallThickness, wallWeight } from './architectureModel.js';
import { signedArea } from '../../../../platform/saengine/common/geometry.js';
import { IDrawingImportOptions, IDrawingInfo } from './architectureDrawingImport.js';
import { DrawingImportPanel } from './architectureDrawingImportPanel.js';
import { ArchitectureEditorInput } from './architectureEditorInput.js';
import { acquireCadEditor, cadBackground, forCanvas, isLightCanvas, releaseCadEditor } from './cadHost.js';
import { FLOOR_PLAN_LAYERS, floorPlanDrawing } from './floorPlanDrawing.js';
import { siblingPartFile } from './floorPlanEditorInput.js';
import { ISnap, SNAP_NAMES, snapLinear, snapMarker, squareMarker } from './floorPlanSnap.js';

/** Screen distances: snapping, picking and marker size [px]; travel below which a press is a click. */
const SNAP_PIXELS = 24;
const PICK_PIXELS = 6;
const MARKER_PIXELS = 8;
const CLICK_PIXELS = 5;
/** How far from a wall's centre (beyond half its thickness) a door or window still finds it [px]. */
const HOST_PIXELS = 30;
/** Below this editor width [px] the toolbar moves Undo, Redo and the structure toggle to "...". */
const COMPACT_WIDTH = 900;

/** The 3D view of 6 BIM's part editor (`bim.json` with `{ section: '3d' }`). */
const BIM_3D_SECTION = '3d';

type Tool = 'select' | 'wall' | 'door' | 'window' | 'room' | 'separator' | 'curtainWall' | 'roof' | 'ramp' | 'railing' | 'delete';

/** Tools that draw a chain of points (a wall's path, a roof's outline). */
const CHAIN_TOOLS: ReadonlySet<Tool> = new Set(['wall', 'curtainWall', 'railing', 'roof']);
/** Tools that place an item of a type picked in the toolbar. */
const TYPED_TOOLS: ReadonlySet<Tool> = new Set(['wall', 'door', 'window', 'curtainWall', 'roof', 'railing']);

const TOOLS: readonly { readonly tool: Tool; readonly label: string; readonly icon: ThemeIcon; readonly hint: string }[] = [
	{ tool: 'select', label: localize('archTool.select', "Select"), icon: Codicon.inspect, hint: localize('archHint.select', "Click a wall, door, window, room or separator to see and change it; Delete removes it.") },
	{ tool: 'wall', label: localize('archTool.wall', "Wall"), icon: Codicon.splitHorizontal, hint: localize('archHint.wall', "Click the wall's points: they snap to the grid, columns, beams and other walls. Click the first point to close a loop; Enter, a double-click or a right-click ends the wall.") },
	{ tool: 'door', label: localize('archTool.door', "Door"), icon: Codicon.signIn, hint: localize('archHint.door', "Click on a wall to put a door there (centred on the click).") },
	{ tool: 'window', label: localize('archTool.window', "Window"), icon: Codicon.window, hint: localize('archHint.window', "Click on a wall to put a window there (centred on the click).") },
	{ tool: 'room', label: localize('archTool.room', "Room"), icon: Codicon.symbolNamespace, hint: localize('archHint.room', "Click inside walls to make a room; its boundary is found from the walls and room separators around the point.") },
	{ tool: 'separator', label: localize('archTool.separator', "Room Separator"), icon: Codicon.dash, hint: localize('archHint.separator', "Click the start and end of a line that bounds rooms where there is no wall.") },
	{ tool: 'curtainWall', label: localize('archTool.curtainWall', "Curtain Wall"), icon: Codicon.layoutPanelJustify, hint: localize('archHint.curtainWall', "Click the curtain wall's points along its centre line: they snap as a wall's do. Enter, a double-click or a right-click ends it.") },
	{ tool: 'roof', label: localize('archTool.roof', "Roof"), icon: Codicon.home, hint: localize('archHint.roof', "Click the roof's corners in turn; click the first corner again (or press Enter) to close it. Give its pitch in the properties panel.") },
	{ tool: 'ramp', label: localize('archTool.ramp', "Ramp"), icon: Codicon.arrowUp, hint: localize('archHint.ramp', "Click the ramp's low end, then its high end (centre line). Give its rise and width in the properties panel.") },
	{ tool: 'railing', label: localize('archTool.railing', "Railing"), icon: Codicon.symbolArray, hint: localize('archHint.railing', "Click the railing's points along its path; Enter, a double-click or a right-click ends it.") },
	{ tool: 'delete', label: localize('archTool.delete', "Delete"), icon: Codicon.trash, hint: localize('archHint.delete', "Click an item to delete it (a wall goes with its doors and windows).") },
];

const KIND_NAMES: { readonly [kind in ArchKind]: string } = {
	walls: localize('archKind.wall', "Wall"),
	doors: localize('archKind.door', "Door"),
	windows: localize('archKind.window', "Window"),
	rooms: localize('archKind.room', "Room"),
	separators: localize('archKind.separator', "Room separator"),
	curtainWalls: localize('archKind.curtainWall', "Curtain wall"),
	roofs: localize('archKind.roof', "Roof"),
	ramps: localize('archKind.ramp', "Ramp"),
	railings: localize('archKind.railing', "Railing"),
};

const PREVIEW_LAYERS: readonly CadLayerSpec[] = [
	{ name: 'SAENGINE-PREVIEW', color: 2, description: 'Placement preview' },
	{ name: 'SAENGINE-PREVIEW-DELETE', color: 1, description: 'Item to delete' },
	{ name: 'SAENGINE-SELECTION', color: 2, description: 'Selected item' },
];

/** The structure under the architecture: grey, the grid as it is. */
const STRUCTURE_GREY = { dark: 251, light: 254 };
const GRID_LAYERS: ReadonlySet<string> = new Set([FLOOR_PLAN_LAYERS.grid, FLOOR_PLAN_LAYERS.gridLabels]);

/** The walls, doors, windows and rooms of a count, each "1 wall" or "3 walls". */
function itemCounts(counts: { readonly walls?: number; readonly doors?: number; readonly windows?: number; readonly rooms?: number }): [string, string, string, string] {
	const { walls = 0, doors = 0, windows = 0, rooms = 0 } = counts;
	return [
		walls === 1 ? localize('arch.oneWall', "1 wall") : localize('arch.nWalls', "{0} walls", walls),
		doors === 1 ? localize('arch.oneDoor', "1 door") : localize('arch.nDoors', "{0} doors", doors),
		windows === 1 ? localize('arch.oneWindow', "1 window") : localize('arch.nWindows', "{0} windows", windows),
		rooms === 1 ? localize('arch.oneRoom', "1 room") : localize('arch.nRooms', "{0} rooms", rooms),
	];
}

function parse(model: ITextModel | undefined): unknown {
	try {
		return model ? JSON.parse(model.getValue()) : undefined;
	} catch {
		return undefined;
	}
}

/** The result of `saengine.architecture.importIfc` and `saengine.architecture.importDrawing`. */
interface IImportResult {
	readonly architecture?: object;
	readonly summary?: IImportSummary;
	readonly problems?: readonly string[];
}

interface IImportSummary {
	readonly adopted: { readonly [kind: string]: number };
	readonly skipped: readonly string[];
	readonly notes: readonly string[];
	/** Items of an earlier import of the same drawing onto the same story that this one replaced. */
	readonly replaced?: number;
}

/**
 * The architecture (`05 Floor Plan/architecture.json`) in the CAD editor, one story at a time,
 * on the floor plan's grids with the structure greyed underneath, in the shared editor frame:
 * the story and the tools in the toolbar, the selected item's properties (or the story's) in the
 * properties panel, the tool hint, counts and cursor in the status line. Walls, doors, windows,
 * rooms and room separators are drawn with the floor plan's snaps; every edit is an undoable edit
 * of the file's text model. The floor plan and object types are read only.
 */
export class ArchitectureEditor extends EditorPane {

	static readonly ID = ArchitectureEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private host!: HTMLElement;
	private message!: HTMLElement;
	private storyPicker!: SelectBox;
	private typePicker!: SelectBox;
	private typeGroup!: HTMLElement;

	private editor: CadEditorApi | undefined;
	private archModel: ITextModel | undefined;
	private planModel: ITextModel | undefined;
	private objects: ITextModel | undefined;
	private arch: IArchitecture | undefined;
	private parseError: string | undefined;
	private drawing: IArchDrawing | undefined;
	private storyIds: string[] = [];
	private fitPending = false;
	private userView = false;
	private lightCanvas = false;
	private compact = false;
	private showStructure = true;

	private tool: Tool = 'select';
	/** The type each placing tool places. */
	private readonly types = new Map<Tool, string>();
	private typeIds: string[] = [];
	/** Points of the wall being drawn, or the start of a separator. */
	private chain: CadPoint[] = [];
	private hover: CadPoint | undefined;
	private hoverSnap: ISnap | undefined;
	private selected: IArchRef | undefined;
	private notice: string | undefined;
	private lastImport: { readonly file: string; readonly summary: IImportSummary } | undefined;
	/** The layer-mapping step of a DWG/DXF import, while it is open. */
	private drawingImport: DrawingImportPanel | undefined;
	private propertiesBeforeImport = false;
	private writing = false;
	private actionsKey = '';

	private readonly toolActions = new Map<Tool, Action>();
	private readonly undoAction = this._register(new Action('saengine.architecture.undo', localize('arch.undo', "Undo"), ThemeIcon.asClassName(Codicon.discard), true, () => this.undoRedo(false)));
	private readonly redoAction = this._register(new Action('saengine.architecture.redo', localize('arch.redo', "Redo"), ThemeIcon.asClassName(Codicon.redo), true, () => this.undoRedo(true)));
	private readonly zoomAction = this._register(new Action('saengine.architecture.zoomExtents', localize('arch.zoomExtents', "Zoom Extents"), ThemeIcon.asClassName(Codicon.screenFull), true, async () => {
		this.userView = false;
		this.editor?.zoomExtents();
	}));
	private readonly structureAction = this._register(new Action('saengine.architecture.toggleStructure', localize('arch.hideStructure', "Hide Structure"), ThemeIcon.asClassName(Codicon.eye), true, async () => {
		this.showStructure = !this.showStructure;
		this.render();
	}));
	private readonly importAction = this._register(new Action('saengine.architecture.importIfc', localize('arch.importIfc', "Import Architect's IFC..."), ThemeIcon.asClassName(Codicon.cloudDownload), true, () => this.importIfc()));
	private readonly importDrawingAction = this._register(new Action('saengine.architecture.importDrawing', localize('arch.importDrawing', "Import Architect's DWG/DXF..."), ThemeIcon.asClassName(Codicon.fileMedia), true, () => this.importDrawing()));
	private readonly view3dAction = this._register(new Action('saengine.architecture.open3d', localize('arch.open3d', "Show in 3D View"), ThemeIcon.asClassName(Codicon.globe), true, () => this.open3d()));
	private readonly textAction = this._register(new Action('saengine.architecture.openText', localize('arch.openText', "Edit Types as Text"), undefined, true, () => this.openText()));
	private readonly floorPlanAction = this._register(new Action('saengine.architecture.openFloorPlan', localize('arch.openFloorPlan', "Open Floor Plan"), undefined, true, () => this.openFloorPlan()));

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.render(), 120));
	private readonly fitScheduler = this._register(new RunOnceScheduler(() => this.editor?.zoomExtents(), 100));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IEditorService private readonly editorService: IEditorService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super(ArchitectureEditor.ID, group, telemetryService, themeService, storageService);
	}

	get resource() {
		return (this.input as ArchitectureEditorInput | undefined)?.resource;
	}

	private get story(): string | undefined {
		return (this.input as ArchitectureEditorInput | undefined)?.story;
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: ArchitectureEditor.ID,
			ariaLabel: localize('arch.toolbar', "Architecture"),
			properties: { title: localize('arch.properties', "Properties") },
		}));
		frame.element.classList.add('saengine-floor-plan', 'saengine-architecture');
		frame.element.tabIndex = -1;

		this.storyPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('arch.storyAria', "Story shown") }));
		this.storyPicker.render(append(frame.titleSlot, $('.floor-plan-select.story')));
		this._register(this.storyPicker.onDidSelect(({ index }) => {
			const input = this.input as ArchitectureEditorInput | undefined;
			if (input && this.storyIds[index] && this.storyIds[index] !== input.story) {
				input.story = this.storyIds[index];
				this.chain = [];
				this.selected = undefined;
				this.render();
			}
		}));
		this.typeGroup = append(frame.controlsSlot, $('.floor-plan-inline.hidden'));
		append(this.typeGroup, $('span.sa-frame-label', undefined, localize('arch.type', "Type")));
		this.typePicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('arch.typeAria', "Type to place") }));
		this.typePicker.render(append(this.typeGroup, $('.floor-plan-select.type')));
		this._register(this.typePicker.onDidSelect(({ index }) => {
			if (this.typeIds[index]) {
				this.types.set(this.tool, this.typeIds[index]);
				this.updateStatus();
			}
		}));

		for (const { tool, label, icon } of TOOLS) {
			this.toolActions.set(tool, this._register(new Action(`saengine.architecture.tool.${tool}`, label, ThemeIcon.asClassName(icon), true, async () => this.setTool(tool))));
		}

		const cad = append(frame.main, $('.saengine-cad-editor'));
		this.host = append(cad, $('.cad-host'));
		this.message = append(cad, $('.cad-message'));
		this.registerMouse();
		this._register(addDisposableListener(frame.element, EventType.KEY_DOWN, e => this.onKey(e)));
		this.lightCanvas = isLightCanvas(this.themeService.getColorTheme());
		this.updateToolbar();
	}

	override async setInput(input: ArchitectureEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		this.release();
		await super.setInput(input, options, context, token);
		this.showMessage(undefined);
		const floorPlan = joinPath(dirname(input.resource), PROJECT_PARTS.find(p => p.id === 'floorPlan')!.mainFile!);
		let references: IReference<IResolvedTextEditorModel>[];
		try {
			references = await Promise.all([input.resource, floorPlan, siblingPartFile(floorPlan, 'objects')].map(r => this.textModelService.createModelReference(r)));
		} catch (error) {
			this.showMessage(localize('arch.noModel', "The architecture or the floor plan could not be read: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			references.forEach(r => r.dispose());
			return;
		}
		references.forEach(r => this.inputDisposables.add(r));
		[this.archModel, this.planModel, this.objects] = references.map(r => r.object.textEditorModel);
		this.inputDisposables.add(input.onDidRequestReveal(() => this.render()));
		for (const model of [this.archModel, this.planModel, this.objects]) {
			this.inputDisposables.add(model.onDidChangeContent(() => {
				if (!this.writing) {
					this.notice = undefined;
				}
				this.renderScheduler.schedule();
			}));
		}
		try {
			const editor = this.editor = await acquireCadEditor(this.host, {
				chrome: { commandLine: false, shortcutToolbar: false },
				background: cadBackground(this.themeService.getColorTheme()),
			});
			if (token.isCancellationRequested || this.input !== input) {
				this.release();
				return;
			}
			if (!await editor.newDrawing({ readOnly: true })) {
				this.showMessage(localize('arch.openFailed', "The architecture drawing could not be created."));
				return;
			}
		} catch (error) {
			this.showMessage(localize('arch.loadFailed', "The CAD editor could not start: {0}", String(error)));
			return;
		}
		this.fitPending = true;
		this.userView = false;
		this.render();
	}

	override clearInput(): void {
		this.release();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		const compact = dimension.width < COMPACT_WIDTH;
		if (compact !== this.compact) {
			this.compact = compact;
			this.actionsKey = '';
			this.updateToolbar();
		}
		this.frame.layout(dimension.width, dimension.height);
		if (!this.userView) {
			this.fitScheduler.schedule();
		}
	}

	override focus(): void {
		super.focus();
		this.frame.element.focus();
	}

	override updateStyles(): void {
		super.updateStyles();
		const theme = this.themeService.getColorTheme();
		this.lightCanvas = isLightCanvas(theme);
		this.editor?.setBackground(cadBackground(theme));
		if (this.editor && this.archModel) {
			this.render();
		}
	}

	override dispose(): void {
		this.release();
		super.dispose();
	}

	private release(): void {
		this.renderScheduler.cancel();
		this.inputDisposables.clear();
		this.archModel = this.planModel = this.objects = undefined;
		this.arch = undefined;
		this.drawing = undefined;
		this.chain = [];
		this.selected = undefined;
		this.lastImport = undefined;
		this.closeDrawingImport();
		if (this.editor) {
			releaseCadEditor(this.editor);
			this.editor = undefined;
		}
	}

	// ───────────────────────────── input ─────────────────────────────

	private registerMouse(): void {
		let down: { x: number; y: number } | undefined;
		const onCanvas = (e: MouseEvent) => isHTMLElement(e.target) && e.target.tagName === 'CANVAS';
		this._register(addDisposableListener(this.host, EventType.WHEEL, () => this.userView = true, { passive: true }));
		this._register(addDisposableListener(this.host, EventType.POINTER_DOWN, e => {
			if (e.button === 1) {
				this.userView = true;
			}
			down = e.button === 0 && onCanvas(e) ? { x: e.clientX, y: e.clientY } : undefined;
		}, true));
		this._register(addDisposableListener(this.host, EventType.POINTER_UP, e => {
			const start = down;
			down = undefined;
			if (e.button === 0 && start && this.editor && Math.hypot(e.clientX - start.x, e.clientY - start.y) < CLICK_PIXELS) {
				this.click(this.editor.toWorld(e.clientX, e.clientY), e.detail >= 2);
			}
		}, true));
		this._register(addDisposableListener(this.host, EventType.POINTER_MOVE, e => {
			if (this.editor) {
				this.hover = this.editor.toWorld(e.clientX, e.clientY);
				this.renderPreview();
			}
		}));
		this._register(addDisposableListener(this.host, EventType.POINTER_LEAVE, () => {
			this.hover = undefined;
			this.renderPreview();
		}));
		this._register(addDisposableListener(this.host, EventType.CONTEXT_MENU, e => {
			if (this.chain.length) {
				e.preventDefault();
				e.stopPropagation();
				if (CHAIN_TOOLS.has(this.tool) && this.chain.length >= (this.tool === 'roof' ? 3 : 2)) {
					this.finishWall(false);
				} else {
					this.cancel();
				}
			}
		}, true));
	}

	private onKey(e: KeyboardEvent): void {
		if (this.drawingImport?.element.contains(e.target as Node)) {
			return;
		}
		const ctrl = e.ctrlKey || e.metaKey;
		if (e.key === 'Escape' && (this.chain.length || this.tool !== 'select' || this.selected)) {
			e.preventDefault();
			e.stopPropagation();
			this.cancel();
		} else if (isEditableElement(e.target as HTMLElement)) {
			return;
		} else if (e.key === 'Enter' && CHAIN_TOOLS.has(this.tool) && this.chain.length >= (this.tool === 'roof' ? 3 : 2)) {
			e.preventDefault();
			this.finishWall(false);
		} else if (e.key === 'Delete' && this.selected) {
			e.preventDefault();
			this.deleteItem(this.selected);
		} else if (ctrl && !e.altKey && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) {
			e.preventDefault();
			e.stopPropagation();
			void this.undoRedo(e.key.toLowerCase() === 'y' || e.shiftKey);
		}
	}

	private setTool(tool: Tool): void {
		this.tool = tool;
		this.chain = [];
		this.notice = undefined;
		if (tool !== 'select') {
			this.selected = undefined;
			this.renderProperties();
		}
		this.updateToolbar();
		this.updateStatus();
		this.renderPreview();
	}

	private cancel(): void {
		if (this.chain.length) {
			this.chain = [];
		} else if (this.tool !== 'select') {
			this.setTool('select');
			return;
		} else {
			this.selected = undefined;
			this.renderProperties();
		}
		this.updateStatus();
		this.renderPreview();
	}

	private elevations(): Map<string, number> {
		return elevationsOf(parse(this.planModel));
	}

	/** Where a wall or separator point at `point` lands: the floor plan's snaps, the architecture's walls included. */
	private snap(point: CadPoint): ISnap {
		const story = this.story ?? '';
		const units = this.editor?.unitsPerPixel() ?? 1;
		const extra = this.arch ? wallSnapSegments(this.arch, story, this.elevations()) : [];
		return snapLinear(parse(this.planModel), story, point, SNAP_PIXELS * units, this.chain[this.chain.length - 1], extra);
	}

	/** The wall a door or window at `point` goes into: the nearest whose centre line is within reach. */
	private hostAt(point: CadPoint): { readonly wall: IArchWall; readonly offset: number } | undefined {
		const story = this.story;
		if (!this.arch || !story) {
			return undefined;
		}
		const reach = HOST_PIXELS * (this.editor?.unitsPerPixel() ?? 1);
		let best: { wall: IArchWall; offset: number; distance: number } | undefined;
		for (const { wall, centre, thickness } of wallsOnStory(this.arch, story, this.elevations())) {
			if (wall.base !== story) {
				continue;
			}
			const hit = projectOnto(centre, point);
			if (hit.distance <= thickness / 2 + reach && (!best || hit.distance < best.distance)) {
				best = { wall, offset: hit.offset, distance: hit.distance };
			}
		}
		return best;
	}

	private click(point: CadPoint, double: boolean): void {
		const story = this.story;
		const arch = this.arch;
		if (!story || !arch || this.parseError) {
			return;
		}
		const tolerance = PICK_PIXELS * (this.editor?.unitsPerPixel() ?? 1);
		switch (this.tool) {
			case 'select': {
				const shape = this.drawing && pickItem(this.drawing.shapes, point, tolerance);
				this.selected = shape && { kind: shape.kind, id: shape.id };
				this.renderProperties();
				this.updateStatus();
				this.renderPreview();
				return;
			}
			case 'delete': {
				const shape = this.drawing && pickItem(this.drawing.shapes, point, tolerance);
				if (shape) {
					this.deleteItem({ kind: shape.kind, id: shape.id });
				}
				return;
			}
			case 'wall': case 'curtainWall': case 'railing': case 'roof': {
				const p = this.snap(point).point;
				const first = this.chain[0];
				if (first && this.chain.length >= 3 && Math.hypot(p[0] - first[0], p[1] - first[1]) <= SNAP_PIXELS * (this.editor?.unitsPerPixel() ?? 1)) {
					this.chain.push(first);
					this.finishWall(true);
					return;
				}
				const last = this.chain[this.chain.length - 1];
				if (!last || last[0] !== p[0] || last[1] !== p[1]) {
					this.chain.push(p);
				}
				if (double && this.chain.length >= (this.tool === 'roof' ? 3 : 2)) {
					this.finishWall(false);
					return;
				}
				this.updateStatus();
				this.renderPreview();
				return;
			}
			case 'ramp': {
				const p = this.snap(point).point;
				if (!this.chain.length) {
					this.chain = [p];
					this.renderPreview();
					return;
				}
				const start = this.chain[0];
				this.chain = [];
				const result = addRamp(arch, story, start, p);
				this.apply(result, id => localize('arch.addedRamp', "Added ramp {0}: give its rise and width in the properties panel.", id));
				if (result.ok) {
					this.selected = { kind: 'ramps', id: result.id };
					this.renderProperties();
				}
				return;
			}
			case 'separator': {
				const p = this.snap(point).point;
				if (!this.chain.length) {
					this.chain = [p];
					this.renderPreview();
					return;
				}
				const start = this.chain[0];
				this.chain = [];
				this.apply(addSeparator(arch, story, start, p), id => localize('arch.addedSeparator', "Added room separator {0}.", id));
				return;
			}
			case 'door': case 'window': {
				const host = this.hostAt(point);
				const type = this.types.get(this.tool);
				if (!host) {
					this.setNotice(localize('arch.noHost', "Click on a wall of this story: doors and windows sit in walls."));
					return;
				}
				if (!type) {
					this.setNotice(localize('arch.noOpeningTypes', "There is no type to place; add one in the file's text (Edit Types as Text)."));
					return;
				}
				const kind = this.tool === 'door' ? 'doors' : 'windows';
				this.apply(addOpening(arch, kind, type, host.wall.id, host.offset), id => kind === 'doors'
					? localize('arch.addedDoor', "Added door {0} ({1}) in wall {2}.", id, type, host.wall.id)
					: localize('arch.addedWindow', "Added window {0} ({1}) in wall {2}.", id, type, host.wall.id));
				return;
			}
			case 'room': {
				this.apply(addRoom(arch, story, point, this.elevations()), id => localize('arch.addedRoom', "Added room {0}: name it in the properties panel.", id), true);
				return;
			}
		}
	}

	private finishWall(closed: boolean): void {
		const story = this.story;
		const arch = this.arch;
		const path = this.chain;
		this.chain = [];
		const tool = this.tool;
		const type = this.types.get(tool);
		if (!story || !arch || path.length < 2) {
			this.renderPreview();
			return;
		}
		if (tool !== 'wall') {
			if (!type) {
				this.setNotice(localize('arch.noTypeToPlace', "There is no type to place; add one in the file's text (Edit Types as Text)."));
				return;
			}
			const length = Math.round(pathLength(path));
			if (tool === 'curtainWall') {
				this.apply(addCurtainWall(arch, type, story, path, this.elevations()), id => localize('arch.addedCurtainWall', "Added curtain wall {0}, {1} mm.", id, length));
			} else if (tool === 'railing') {
				this.apply(addRailing(arch, type, story, path), id => localize('arch.addedRailing', "Added railing {0}, {1} mm.", id, length));
			} else if (tool === 'roof') {
				const result = addRoof(arch, type, story, path);
				this.apply(result, id => localize('arch.addedRoof', "Added roof {0}: give its pitch in the properties panel.", id));
				if (result.ok) {
					this.selected = { kind: 'roofs', id: result.id };
					this.renderProperties();
				}
			}
			return;
		}
		if (!type) {
			this.setNotice(localize('arch.noWallTypeToPlace', "There is no wall type to place; add one in the file's text (Edit Types as Text)."));
			return;
		}
		// A straight wall over a beam or wall of the floor plan records what it stands on.
		const under = path.length === 2 ? structureUnder(parse(this.planModel), story, path[0], path[1]) : undefined;
		this.apply(addWall(arch, type, story, path, this.elevations(), under), id => {
			const length = Math.round(pathLength(path));
			return closed ? localize('arch.addedLoop', "Added wall {0}: a closed loop of {1} mm.", id, length)
				: under ? localize('arch.addedWallOn', "Added wall {0}, {1} mm, on {2}.", id, length, under)
					: localize('arch.addedWall', "Added wall {0}, {1} mm.", id, length);
		});
	}

	private deleteItem(ref: IArchRef): void {
		if (!this.arch) {
			return;
		}
		const hosted = ref.kind === 'walls' ? [...this.arch.doors, ...this.arch.windows].filter(o => o.wall === ref.id).length : 0;
		this.write(removeItem(this.arch, ref));
		if (this.selected?.id === ref.id) {
			this.selected = undefined;
		}
		this.setNotice(hosted
			? localize('arch.deletedWithOpenings', "Deleted {0} {1} with its {2} doors and windows.", KIND_NAMES[ref.kind], ref.id, hosted)
			: localize('arch.deleted', "Deleted {0} {1}.", KIND_NAMES[ref.kind], ref.id));
		this.renderProperties();
	}

	private apply(result: ReturnType<typeof addWall>, notice: (id: string) => string, select = false): void {
		if (!result.ok) {
			this.setNotice(result.error);
			this.renderPreview();
			return;
		}
		this.write(result.value);
		this.setNotice(notice(result.id));
		if (select) {
			this.selected = { kind: 'rooms', id: result.id };
			this.renderProperties();
		}
	}

	/** Replaces the file's text with `value` as one undoable edit. */
	private write(value: IArchitecture): void {
		const model = this.archModel;
		if (!model || model.isDisposed()) {
			return;
		}
		this.writing = true;
		try {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: JSON.stringify(value, undefined, '\t') + '\n' }], () => null);
			model.pushStackElement();
		} finally {
			this.writing = false;
		}
		this.renderScheduler.cancel();
		this.render();
	}

	private async undoRedo(redo: boolean): Promise<void> {
		const resource = this.resource;
		const model = this.archModel;
		if (!resource || !model) {
			return;
		}
		const version = model.getAlternativeVersionId();
		await (redo ? this.undoRedoService.redo(resource) : this.undoRedoService.undo(resource));
		if (!model.isDisposed()) {
			const changed = model.getAlternativeVersionId() !== version;
			this.setNotice(changed ? (redo ? localize('arch.redid', "Redid the last edit.") : localize('arch.undid', "Undid the last edit."))
				: (redo ? localize('arch.nothingToRedo', "Nothing to redo.") : localize('arch.nothingToUndo', "Nothing to undo.")));
		}
	}

	// ───────────────────────────── drawing ─────────────────────────────

	private render(): void {
		const input = this.input as ArchitectureEditorInput | undefined;
		if (!input || !this.editor || !this.archModel) {
			return;
		}
		const layout = parse(this.planModel);
		const stories = storiesOf(layout);
		this.storyIds = stories.map(s => s.id);
		if (!input.story || !this.storyIds.includes(input.story)) {
			// The first floor above the lowest level, as the floor plan opens.
			input.story = this.storyIds[Math.min(1, this.storyIds.length - 1)];
		}
		this.storyPicker.setOptions(
			stories.length ? stories.map(s => ({ text: `${s.name} (${s.elevation >= 0 ? '+' : ''}${s.elevation})` })) : [{ text: localize('arch.noStoriesOption', "(no stories)") }],
			Math.max(0, this.storyIds.indexOf(input.story ?? '')),
		);
		const parsed = parseArchitecture(this.archModel.getValue());
		this.parseError = parsed.kind === 'error' ? parsed.message : undefined;
		this.arch = parsed.kind === 'ok' ? parsed.value : undefined;
		const story = input.story ?? '';
		const elevations = elevationsOf(layout);
		this.drawing = this.arch ? architectureDrawing(this.arch, story, elevations) : undefined;
		if (input.reveal) {
			// A wall linked from the Floor Plan's Loads list: selected, its properties shown.
			const shape = this.drawing?.shapes.find(s => s.id === input.reveal);
			this.selected = shape && { kind: shape.kind, id: shape.id };
			input.reveal = undefined;
		}
		if (this.selected && !this.drawing?.shapes.some(s => s.kind === this.selected!.kind && s.id === this.selected!.id)) {
			this.selected = undefined;
		}

		const structure = floorPlanDrawing(layout, parse(this.objects), story).drawing;
		const grey = this.lightCanvas ? STRUCTURE_GREY.light : STRUCTURE_GREY.dark;
		const underneath: CadGeneratedDrawing = {
			layers: structure.layers.map(l => GRID_LAYERS.has(l.name) ? l : { ...l, color: grey }),
			entities: structure.entities.filter(e => this.showStructure || GRID_LAYERS.has(e.layer)),
		};
		const architecture = forCanvas({ layers: ARCH_LAYER_SPECS, entities: this.drawing?.entities ?? [] }, this.lightCanvas);
		this.editor.setGenerated({
			layers: [...forCanvas({ layers: underneath.layers.filter(l => GRID_LAYERS.has(l.name)), entities: [] }, this.lightCanvas).layers, ...underneath.layers.filter(l => !GRID_LAYERS.has(l.name)), ...architecture.layers],
			entities: [...underneath.entities, ...architecture.entities],
		});
		if (this.fitPending) {
			this.fitPending = false;
			this.editor.zoomExtents();
			this.fitScheduler.schedule();
		}
		this.showMessage(this.parseError);
		this.updateToolbar();
		this.updateStatus();
		this.renderProperties();
		this.renderPreview();
	}

	private renderPreview(): void {
		const editor = this.editor;
		if (!editor) {
			return;
		}
		const units = editor.unitsPerPixel();
		const [layer, deleteLayer, selectionLayer] = PREVIEW_LAYERS.map(l => l.name);
		const entities: CadEntitySpec[] = [];
		const outline = (points: readonly CadPoint[], closed: boolean, on: string) => entities.push({ kind: 'polyline', layer: on, points, closed });
		const point = this.hover;
		const story = this.story ?? '';
		this.hoverSnap = undefined;
		this.chain.forEach(p => entities.push(squareMarker(p, MARKER_PIXELS * units / 2, layer)));
		if (this.chain.length >= 2) {
			outline(this.chain, false, layer);
		}
		if (point && this.arch) {
			if (CHAIN_TOOLS.has(this.tool) || this.tool === 'separator' || this.tool === 'ramp') {
				const snap = this.hoverSnap = this.snap(point);
				entities.push(...snapMarker(snap, MARKER_PIXELS * units, layer));
				const last = this.chain[this.chain.length - 1];
				if (last) {
					entities.push({ kind: 'line', layer, start: last, end: snap.point });
				}
			} else if (this.tool === 'door' || this.tool === 'window') {
				const host = this.hostAt(point);
				const type = this.types.get(this.tool);
				const kind = this.tool === 'door' ? 'doors' : 'windows';
				const size = type && openingSize(this.arch, kind, { id: '', type, wall: '', offset: 0 });
				if (host && size) {
					const wallType = this.arch.wallTypes.find(t => t.id === host.wall.type);
					const centre = centreLine(host.wall, wallType);
					const t = wallThickness(wallType) / 2;
					const at = Math.min(Math.max(host.offset, size.width / 2), pathLength(centre) - size.width / 2);
					const { point: [cx, cy], direction: [dx, dy] } = pointAlong(centre, at);
					const corner = (u: number, v: number): CadPoint => [cx + dx * u - dy * v, cy + dy * u + dx * v];
					outline([corner(-size.width / 2, -t), corner(size.width / 2, -t), corner(size.width / 2, t), corner(-size.width / 2, t)], true, layer);
				}
			} else if (this.tool === 'room') {
				const room = findRoom(this.arch, story, point, this.elevations());
				if (room) {
					outline(room.net, true, layer);
				}
			} else if (this.tool === 'delete' || this.tool === 'select') {
				const shape = this.drawing && pickItem(this.drawing.shapes, point, PICK_PIXELS * units);
				if (shape && this.tool === 'delete') {
					outline(shape.points, shape.closed, deleteLayer);
				}
			}
		}
		const selected = this.selected && this.drawing?.shapes.find(s => s.kind === this.selected!.kind && s.id === this.selected!.id);
		if (selected) {
			outline(selected.points, selected.closed, selectionLayer);
		}
		editor.setPreview(forCanvas({ layers: PREVIEW_LAYERS, entities }, this.lightCanvas));
		this.updateStatus();
	}

	// ───────────────────────────── chrome ─────────────────────────────

	private updateToolbar(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const editable = !!this.arch && !this.parseError && this.storyIds.length > 0;
		for (const [tool, action] of this.toolActions) {
			action.checked = tool === this.tool;
			action.enabled = editable || tool === 'select';
		}
		const resource = this.resource;
		this.undoAction.enabled = !!resource && this.undoRedoService.canUndo(resource);
		this.redoAction.enabled = !!resource && this.undoRedoService.canRedo(resource);
		this.structureAction.checked = this.showStructure;
		this.structureAction.label = this.showStructure ? localize('arch.hideStructure', "Hide Structure") : localize('arch.showStructure', "Show Structure");
		this.structureAction.class = ThemeIcon.asClassName(this.showStructure ? Codicon.eye : Codicon.eyeClosed);
		this.importAction.enabled = editable;
		this.importDrawingAction.enabled = editable && !this.drawingImport;

		const tools = (names: readonly Tool[]) => names.map(name => this.toolActions.get(name)!);
		const primary: IAction[] = [
			...tools(['select']),
			new Separator(),
			...tools(['wall', 'door', 'window', 'room', 'separator']),
			new Separator(),
			...tools(['curtainWall', 'roof', 'ramp', 'railing']),
			new Separator(),
			...tools(['delete']),
			...(this.compact ? [] : [this.undoAction, this.redoAction]),
			new Separator(),
			this.zoomAction, ...(this.compact ? [] : [this.structureAction]), this.view3dAction, frame.togglePropertiesAction,
		];
		const secondary: IAction[] = [
			this.importDrawingAction,
			this.importAction,
			new Separator(),
			this.textAction,
			this.floorPlanAction,
			...(this.compact ? [new Separator(), this.undoAction, this.redoAction, this.structureAction] : []),
		];
		const key = `${this.compact}`;
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			frame.setActions(primary, secondary);
		}

		const placing = TYPED_TOOLS.has(this.tool);
		this.typeGroup.classList.toggle('hidden', !placing);
		if (placing && this.arch) {
			const typesOf: { readonly [tool: string]: readonly { readonly id: string; readonly name: string }[] } = {
				wall: this.arch.wallTypes, door: this.arch.doorTypes, window: this.arch.windowTypes,
				curtainWall: this.arch.curtainWallTypes, roof: this.arch.roofTypes, railing: this.arch.railingTypes,
			};
			const types = typesOf[this.tool] ?? [];
			this.typeIds = types.map(t => t.id);
			let chosen = this.types.get(this.tool);
			if (!chosen || !this.typeIds.includes(chosen)) {
				chosen = this.typeIds[0];
				if (chosen) {
					this.types.set(this.tool, chosen);
				}
			}
			const label = (t: { readonly id: string; readonly name: string }) => {
				const wall = this.arch!.wallTypes.find(w => w.id === t.id);
				return this.tool === 'wall' && wall ? `${t.id}: ${t.name} (${wallThickness(wall)} mm)` : `${t.id}: ${t.name}`;
			};
			this.typePicker.setOptions(types.length ? types.map(t => ({ text: label(t) })) : [{ text: localize('arch.noTypes', "(none defined)") }], Math.max(0, this.typeIds.indexOf(chosen ?? '')));
		}
	}

	private setNotice(text: string): void {
		this.notice = text;
		this.updateStatus();
		this.updateToolbar();
	}

	private updateStatus(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		if (this.parseError) {
			frame.setStatus({ severity: 'error', text: this.parseError, link: { label: localize('arch.openText', "Edit Types as Text"), run: () => void this.openText() } });
			return;
		}
		const parts: string[] = [];
		const lead = this.notice ?? (this.storyIds.length === 0 ? localize('arch.noStories', "The floor plan has no stories yet: add them in Grids & Stories first.") : TOOLS.find(t => t.tool === this.tool)?.hint);
		if (lead) {
			parts.push(lead);
		}
		const story = this.story;
		if (this.arch && story) {
			const counts = storyCounts(this.arch, story, this.elevations());
			parts.push(localize('arch.counts', "{0}, {1}, {2}, {3} on this story", ...itemCounts(counts)));
		}
		const problems = this.drawing?.problems ?? [];
		if (problems.length) {
			parts.push(problems.length === 1 ? problems[0] : localize('arch.problems', "{0} problems", problems.length));
		}
		const snap = this.hoverSnap;
		if (snap) {
			const last = this.chain[this.chain.length - 1];
			const label = snap.on ? `${SNAP_NAMES[snap.kind]} (${snap.on})` : SNAP_NAMES[snap.kind];
			parts.push(last ? localize('arch.snapLength', "{0}: {1} mm", label, Math.round(Math.hypot(snap.point[0] - last[0], snap.point[1] - last[1]))) : label);
		} else if (this.hover) {
			parts.push(localize('arch.cursor', "x {0}, y {1} mm", Math.round(this.hover[0]), Math.round(this.hover[1])));
		}
		frame.setStatus({
			text: parts.join('  ·  '),
			severity: problems.length ? 'warning' : undefined,
			link: problems.length ? { label: localize('arch.details', "Details"), run: () => this.frame.setPropertiesVisible(true) } : undefined,
		});
	}

	private showMessage(text: string | undefined): void {
		this.message.textContent = text ?? '';
		this.message.classList.toggle('visible', !!text);
	}

	// ───────────────────────────── properties ─────────────────────────────

	private renderProperties(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		this.propertiesDisposables.clear();
		clearNode(panel);
		const arch = this.arch;
		const story = this.story;
		if (!arch || !story) {
			return;
		}
		const ref = this.selected;
		const item = ref && itemOf(arch, ref);
		if (!ref || !item) {
			this.renderStory(panel, arch, story);
			return;
		}
		appendPropertyHeading(panel, KIND_NAMES[ref.kind], ref.id);
		const change = (fields: { readonly [field: string]: unknown }, notice: string) => {
			this.write(updateItem(arch, ref, fields));
			this.setNotice(notice);
		};
		const elevations = this.elevations();
		switch (ref.kind) {
			case 'walls': {
				const wall = item as unknown as IArchWall;
				const type = arch.wallTypes.find(t => t.id === wall.type);
				this.selectRow(panel, localize('arch.wallType', "Wall type"), arch.wallTypes.map(t => ({ id: t.id, text: `${t.id}: ${t.name}` })), wall.type, id => change({ type: id }, localize('arch.changedType', "{0} is now {1}.", wall.id, id)));
				if (type) {
					appendPropertyRow(panel, localize('arch.thickness', "Thickness"), localize('arch.mm', "{0} mm", wallThickness(type)));
					appendPropertyRow(panel, localize('arch.weight', "Weight"), localize('arch.kNm2', "{0} kN/m²", wallWeight(type).toFixed(2)));
				}
				appendPropertyRow(panel, localize('arch.length', "Length"), localize('arch.mm', "{0} mm", Math.round(pathLength(centreLine(wall, type)))));
				const levels = wallLevels(wall, elevations);
				const stories = storiesOf(parse(this.planModel));
				appendPropertyRow(panel, localize('arch.base', "Base"), stories.find(s => s.id === wall.base)?.name ?? wall.base);
				const above = stories.filter(s => s.elevation > (elevations.get(wall.base) ?? Infinity));
				this.selectRow(panel, localize('arch.top', "Top"), [{ id: '', text: localize('arch.topNext', "Next story up") }, ...above.map(s => ({ id: s.id, text: s.name })), { id: '#height', text: localize('arch.topHeight', "A height...") }],
					wall.height !== undefined ? '#height' : wall.top ?? '', id => id === '#height'
					? change({ top: undefined, height: Math.max(100, Math.round((levels?.top ?? 3000) - (levels?.bottom ?? 0))) }, localize('arch.heightSet', "{0} has its own height now.", wall.id))
					: change({ top: id || undefined, height: undefined }, localize('arch.topSet', "{0} rises to {1}.", wall.id, id || localize('arch.nextStory', "the next story"))));
				if (wall.height !== undefined || !levels) {
					this.inputRow(panel, localize('arch.heightMm', "Height (mm)"), String(wall.height ?? ''), text => {
						const value = Number(text);
						if (Number.isFinite(value) && value > 0) {
							change({ height: Math.round(value), top: undefined }, localize('arch.heightChanged', "{0} is {1} mm high.", wall.id, Math.round(value)));
						}
					});
				} else {
					appendPropertyRow(panel, localize('arch.height', "Height"), localize('arch.mm', "{0} mm", Math.round(levels.top - levels.bottom)));
				}
				this.inputRow(panel, localize('arch.baseOffset', "Base offset (mm)"), String(wall.baseOffset ?? 0), text => {
					const value = Number(text);
					if (Number.isFinite(value)) {
						change({ baseOffset: value ? Math.round(value) : undefined }, localize('arch.baseOffsetChanged', "{0} starts {1} mm above its story.", wall.id, Math.round(value)));
					}
				});
				this.inputRow(panel, localize('arch.sitsOn', "Sits on (floor-plan member)"), wall.structuralRef ?? '', text => change({ structuralRef: text.trim() || undefined }, localize('arch.sitsOnChanged', "{0} sits on {1}.", wall.id, text.trim() || '-')));
				const hosted = [...arch.doors, ...arch.windows].filter(o => o.wall === wall.id).map(o => o.id);
				if (hosted.length) {
					appendPropertyRow(panel, localize('arch.openings', "Doors and windows"), hosted.join(', '));
				}
				appendPropertyNote(panel, localize('arch.wallNote', "Architectural walls add no stiffness to the analysis; their weight loads the beams or slabs under them (superimposed dead load, see the Floor Plan's Loads list)."));
				break;
			}
			case 'doors': case 'windows': {
				const opening = item as unknown as IDoor & IWindow;
				const types: readonly { readonly id: string; readonly name: string }[] = ref.kind === 'doors' ? arch.doorTypes : arch.windowTypes;
				this.selectRow(panel, ref.kind === 'doors' ? localize('arch.doorType', "Door type") : localize('arch.windowType', "Window type"), types.map(t => ({ id: t.id, text: `${t.id}: ${t.name}` })), opening.type, id => change({ type: id }, localize('arch.changedType', "{0} is now {1}.", opening.id, id)));
				const size = openingSize(arch, ref.kind, opening);
				if (size) {
					appendPropertyRow(panel, localize('arch.size', "Size"), localize('arch.sizeValue', "{0} x {1} mm", size.width, size.height));
				}
				appendPropertyRow(panel, localize('arch.hostWall', "Wall"), opening.wall);
				this.inputRow(panel, localize('arch.offset', "Offset along the wall (mm)"), String(opening.offset), text => {
					const value = Number(text);
					if (Number.isFinite(value) && value >= 0) {
						change({ offset: Math.round(value) }, localize('arch.offsetChanged', "{0} is {1} mm along its wall.", opening.id, Math.round(value)));
					}
				});
				if (ref.kind === 'windows') {
					this.inputRow(panel, localize('arch.sill', "Sill (mm, empty: the type's)"), opening.sill === undefined ? '' : String(opening.sill), text => {
						const value = text.trim() === '' ? undefined : Number(text);
						if (value === undefined || (Number.isFinite(value) && value >= 0)) {
							change({ sill: value === undefined ? undefined : Math.round(value) }, localize('arch.sillChanged', "{0}'s sill is {1}.", opening.id, value === undefined ? localize('arch.typeSill', "its type's") : `${Math.round(value)} mm`));
						}
					});
				} else {
					this.selectRow(panel, localize('arch.swing', "Swing"), [{ id: '', text: localize('arch.swingNormal', "This side") }, { id: 'flip', text: localize('arch.swingFlip', "Other side") }], opening.flip ? 'flip' : '', id => change({ flip: id ? true : undefined }, localize('arch.flipped', "{0} swings to the other side.", opening.id)));
				}
				break;
			}
			case 'rooms': {
				const room = item as unknown as IRoom;
				this.inputRow(panel, localize('arch.roomName', "Name"), room.name, text => text.trim() && change({ name: text.trim() }, localize('arch.renamed', "{0} is now {1}.", room.id, text.trim())));
				this.inputRow(panel, localize('arch.roomNumber', "Number"), room.number ?? '', text => change({ number: text.trim() || undefined }, localize('arch.renumbered', "{0} is number {1}.", room.id, text.trim() || '-')));
				const outline = this.drawing?.rooms.get(room.id);
				appendPropertyRow(panel, localize('arch.area', "Net area"), outline ? localize('arch.roomArea', "{0} m²", outline.area.toFixed(2)) : localize('arch.notEnclosedShort', "not enclosed"), !outline);
				const uses = Object.entries(BNBC.areaUses);
				this.selectRow(panel, localize('arch.occupancy', "Occupancy"), [{ id: '', text: localize('arch.none', "(none)") }, ...uses.map(([id, use]) => ({ id, text: localize('arch.useLive', "{0} ({1} kPa)", use.name, use.live) }))], room.occupancy ?? '', id => change({ occupancy: id || undefined }, localize('arch.occupancyChanged', "{0}: {1}.", room.id, id ? BNBC.areaUses[id]?.name ?? id : localize('arch.noOccupancy', "no occupancy"))));
				for (const [field, kind, label] of [['floorFinish', 'floor', localize('arch.floorFinish', "Floor finish")], ['wallFinish', 'wall', localize('arch.wallFinish', "Wall finish")], ['ceilingFinish', 'ceiling', localize('arch.ceilingFinish', "Ceiling finish")]] as const) {
					const finishes = arch.finishTypes.filter(f => f.kind === kind);
					this.selectRow(panel, label, [{ id: '', text: localize('arch.none', "(none)") }, ...finishes.map(f => ({ id: f.id, text: `${f.name} (${f.thickness} mm)` }))], room[field] ?? '', id => change({ [field]: id || undefined }, localize('arch.finishChanged', "{0}: {1} {2}.", room.id, label, id || '-')));
				}
				this.selectRow(panel, localize('arch.wet', "Wet area"), [{ id: '', text: localize('arch.no', "No") }, { id: 'yes', text: localize('arch.yes', "Yes (toilet, kitchen)") }], room.wet ? 'yes' : '', id => change({ wet: id ? true : undefined }, id ? localize('arch.isWet', "{0} is a wet area.", room.id) : localize('arch.isDry', "{0} is a dry area.", room.id)));
				appendPropertyNote(panel, localize('arch.roomNote', "The analysis model takes the room's floor finish (instead of the floor's flat finish) and its occupancy's live load over its area; the bill measures its finishes."));
				break;
			}
			case 'separators': {
				appendPropertyNote(panel, localize('arch.separatorNote', "Bounds rooms where there is no wall, e.g. between a kitchen and a dining area."));
				break;
			}
			case 'curtainWalls': {
				const wall = item as unknown as ICurtainWall;
				const type = arch.curtainWallTypes.find(t => t.id === wall.type);
				this.selectRow(panel, localize('arch.curtainType', "Curtain wall type"), arch.curtainWallTypes.map(t => ({ id: t.id, text: `${t.id}: ${t.name}` })), wall.type, id => change({ type: id }, localize('arch.changedType', "{0} is now {1}.", wall.id, id)));
				if (type) {
					appendPropertyRow(panel, localize('arch.weight', "Weight"), localize('arch.kNm2', "{0} kN/m²", curtainWeight(type).toFixed(2)));
					appendPropertyRow(panel, localize('arch.grid', "Mullions, transoms"), localize('arch.gridValue', "{0} mm, {1} mm", type.mullionSpacing ?? 1500, type.transomSpacing ?? 1500));
				}
				appendPropertyRow(panel, localize('arch.length', "Length"), localize('arch.mm', "{0} mm", Math.round(pathLength(wall.path))));
				const levels = wallLevels(wall, elevations);
				appendPropertyRow(panel, localize('arch.height', "Height"), levels ? localize('arch.mm', "{0} mm", Math.round(levels.top - levels.bottom)) : localize('arch.noHeight', "none: give a height"), !levels);
				this.inputRow(panel, localize('arch.heightOwn', "Height (mm, empty: to the next story)"), wall.height === undefined ? '' : String(wall.height), text => {
					const value = text.trim() === '' ? undefined : Number(text);
					if (value === undefined || (Number.isFinite(value) && value > 0)) {
						change({ height: value === undefined ? undefined : Math.round(value), top: undefined }, localize('arch.curtainHeightChanged', "{0}'s height: {1}.", wall.id, value === undefined ? localize('arch.nextStory', "the next story") : `${Math.round(value)} mm`));
					}
				});
				appendPropertyNote(panel, localize('arch.curtainNote', "A facade of glazing on a mullion grid: its weight loads the beams or slab edges under it (superimposed dead load); it bounds rooms as a wall does, but is not a partition."));
				break;
			}
			case 'roofs': {
				const roof = item as unknown as IRoof;
				const type = arch.roofTypes.find(t => t.id === roof.type);
				this.selectRow(panel, localize('arch.roofType', "Roof type"), arch.roofTypes.map(t => ({ id: t.id, text: `${t.id}: ${t.name}` })), roof.type, id => change({ type: id }, localize('arch.changedType', "{0} is now {1}.", roof.id, id)));
				const plan = Math.abs(signedArea(roof.outline)) / 1e6;
				const slope = roof.slope ?? 0;
				appendPropertyRow(panel, localize('arch.planArea', "Plan area"), localize('arch.roomArea', "{0} m²", plan.toFixed(2)));
				if (type) {
					// Per m² of plan: the covering's weight along the slope over the cosine (saengine.fem.architecture_loads).
					appendPropertyRow(panel, localize('arch.covering', "Covering"), localize('arch.coveringValue', "{0} kN/m² of plan", (roofWeight(type) / Math.cos(slope * Math.PI / 180)).toFixed(2)));
				}
				this.inputRow(panel, localize('arch.slope', "Pitch (°, 0: flat)"), String(slope), text => {
					const value = Number(text);
					if (Number.isFinite(value) && value >= 0 && value < 90) {
						change({ slope: value || undefined }, localize('arch.slopeChanged', "{0} is pitched {1}°.", roof.id, value));
					}
				});
				if (slope) {
					this.inputRow(panel, localize('arch.direction', "Rises towards (° from x)"), String(roof.direction ?? 90), text => {
						const value = Number(text);
						if (Number.isFinite(value)) {
							change({ direction: value }, localize('arch.directionChanged', "{0} rises towards {1}°.", roof.id, value));
						}
					});
				}
				this.occupancyRow(panel, roof.id, roof.occupancy, change);
				appendPropertyNote(panel, localize('arch.roofNote', "Its covering is superimposed dead load over its outline on this story's slab, instead of the floor's flat finish there (rooms on the roof keep theirs); an occupancy gives its live load (BNBC 2020 Part 6 Table 6.2.3)."));
				break;
			}
			case 'ramps': {
				const ramp = item as unknown as IRamp;
				const run = Math.hypot(ramp.end[0] - ramp.start[0], ramp.end[1] - ramp.start[1]);
				const gradient = rampGradient(ramp);
				appendPropertyRow(panel, localize('arch.run', "Run"), localize('arch.mm', "{0} mm", Math.round(run)));
				appendPropertyRow(panel, localize('arch.gradient', "Gradient"), gradient > 0 ? localize('arch.gradientValue', "1 in {0} ({1} %)", (1 / gradient).toFixed(1), (gradient * 100).toFixed(1)) : localize('arch.gradientLevel', "level"));
				const positive = (field: string, label: string, value: number | undefined, min: number) => this.inputRow(panel, label, String(value ?? ''), text => {
					const n = Number(text);
					if (Number.isFinite(n) && n >= min) {
						change({ [field]: Math.round(n) }, localize('arch.fieldChanged', "{0}: {1} {2}.", ramp.id, label, Math.round(n)));
					}
				});
				positive('rise', localize('arch.rise', "Rise (mm)"), ramp.rise ?? 0, 0);
				positive('width', localize('arch.width', "Width (mm)"), ramp.width ?? 1500, 1);
				const floors = arch.finishTypes.filter(f => f.kind === 'floor');
				this.selectRow(panel, localize('arch.floorFinish', "Floor finish"), [{ id: '', text: localize('arch.none', "(none)") }, ...floors.map(f => ({ id: f.id, text: `${f.name} (${f.thickness} mm)` }))], ramp.finish ?? '', id => change({ finish: id || undefined }, localize('arch.finishChanged', "{0}: {1} {2}.", ramp.id, localize('arch.floorFinish', "Floor finish"), id || '-')));
				this.inputRow(panel, localize('arch.fill', "Fill unit weight (kN/m³, 0: none)"), String(ramp.fillUnitWeight ?? 16), text => {
					const n = Number(text);
					if (Number.isFinite(n) && n >= 0) {
						change({ fillUnitWeight: n }, localize('arch.fillChanged', "{0}'s fill weighs {1} kN/m³.", ramp.id, n));
					}
				});
				this.occupancyRow(panel, ramp.id, ramp.occupancy, change);
				appendPropertyNote(panel, localize('arch.rampNote', "A ramp built up on the floor: its filling (half its rise deep on average) and finish are superimposed dead load over its footprint, with its occupancy's live load. A turning ramp is several straight ramps with landings."));
				break;
			}
			case 'railings': {
				const railing = item as unknown as IRailing;
				const type = arch.railingTypes.find(t => t.id === railing.type);
				this.selectRow(panel, localize('arch.railingType', "Railing type"), arch.railingTypes.map(t => ({ id: t.id, text: `${t.id}: ${t.name}` })), railing.type, id => change({ type: id }, localize('arch.changedType', "{0} is now {1}.", railing.id, id)));
				const values = railingOf(type);
				appendPropertyRow(panel, localize('arch.railingHeight', "Height"), localize('arch.mm', "{0} mm", values.height));
				appendPropertyRow(panel, localize('arch.weight', "Weight"), localize('arch.kNm', "{0} kN/m", values.weight.toFixed(2)));
				appendPropertyRow(panel, localize('arch.length', "Length"), localize('arch.mm', "{0} mm", Math.round(pathLength(railing.path))));
				appendPropertyNote(panel, localize('arch.railingNote', "Its weight loads the beam or slab edge under it (superimposed dead load). The horizontal load a guard resists is for the railing's own design, not the frame's."));
				break;
			}
		}
		propertyLink(panel, localize('arch.deleteItem', "Delete {0}", ref.id), () => this.deleteItem(ref), this.propertiesDisposables);
	}

	/** Nothing selected: the story's counts, the types, and the last IFC import's summary. */
	private renderStory(panel: HTMLElement, arch: IArchitecture, story: string): void {
		const name = storiesOf(parse(this.planModel)).find(s => s.id === story)?.name ?? story;
		appendPropertyHeading(panel, name);
		const counts = storyCounts(arch, story, this.elevations());
		appendPropertyRow(panel, localize('arch.walls', "Walls"), String(counts.walls));
		appendPropertyRow(panel, localize('arch.doors', "Doors"), String(counts.doors));
		appendPropertyRow(panel, localize('arch.windows', "Windows"), String(counts.windows));
		appendPropertyRow(panel, localize('arch.rooms', "Rooms"), String(counts.rooms));
		const rooms = this.drawing ? [...this.drawing.rooms.values()] : [];
		if (rooms.length) {
			appendPropertyRow(panel, localize('arch.roomsArea', "Room area"), localize('arch.roomArea', "{0} m²", rooms.reduce((sum, r) => sum + r.area, 0).toFixed(2)));
		}
		for (const problem of this.drawing?.problems ?? []) {
			appendPropertyRow(panel, localize('arch.problem', "Problem"), problem, true);
		}
		appendPropertyHeading(panel, localize('arch.wallTypes', "Wall types"));
		for (const type of arch.wallTypes) {
			appendPropertyRow(panel, type.id, localize('arch.wallTypeRow', "{0}: {1} mm, {2} kN/m²", type.name, wallThickness(type), wallWeight(type).toFixed(2)));
		}
		appendPropertyHeading(panel, localize('arch.openingTypes', "Door and window types"));
		for (const type of [...arch.doorTypes, ...arch.windowTypes]) {
			appendPropertyRow(panel, type.id, localize('arch.openingTypeRow', "{0}: {1} x {2} mm", type.name, type.width, type.height));
		}
		appendPropertyHeading(panel, localize('arch.finishTypes', "Finish types"));
		for (const type of arch.finishTypes) {
			// The floor finish's weight replaces the floor's flat finish in its rooms (saengine.fem.architecture_loads).
			const weight = type.thickness / 1000 * type.unitWeight;
			appendPropertyRow(panel, type.id, type.sunkFilling
				? localize('arch.finishSunkRow', "{0}: {1} mm, {2} kN/m² (+{3} kN/m² sunk filling in wet rooms)", type.name, type.thickness, weight.toFixed(2), (type.sunkFilling / 1000 * (type.sunkUnitWeight ?? 16)).toFixed(2))
				: localize('arch.finishRow', "{0}: {1} mm, {2} kN/m²", type.name, type.thickness, weight.toFixed(2)));
		}
		if (arch.curtainWallTypes.length || arch.roofTypes.length || arch.railingTypes.length) {
			appendPropertyHeading(panel, localize('arch.extraTypes', "Curtain wall, roof and railing types"));
			for (const type of arch.curtainWallTypes) {
				appendPropertyRow(panel, type.id, localize('arch.curtainTypeRow', "{0}: {1} kN/m²", type.name, curtainWeight(type).toFixed(2)));
			}
			for (const type of arch.roofTypes) {
				appendPropertyRow(panel, type.id, localize('arch.roofTypeRow', "{0}: {1} kN/m²", type.name, roofWeight(type).toFixed(2)));
			}
			for (const type of arch.railingTypes) {
				const values = railingOf(type);
				appendPropertyRow(panel, type.id, localize('arch.railingTypeRow', "{0}: {1} mm high, {2} kN/m", type.name, values.height, values.weight.toFixed(2)));
			}
		}
		propertyLink(panel, localize('arch.editTypes', "Edit the types as text"), () => void this.openText(), this.propertiesDisposables);
		const last = this.lastImport;
		if (last) {
			const summary = last.summary;
			appendPropertyHeading(panel, localize('arch.lastImport', "Last import"), last.file);
			const labels: { readonly [kind: string]: string } = {
				walls: localize('arch.walls', "Walls"), doors: localize('arch.doors', "Doors"), windows: localize('arch.windows', "Windows"),
				rooms: localize('arch.rooms', "Rooms"), types: localize('arch.newTypes', "New types"),
			};
			for (const [kind, count] of Object.entries(summary.adopted)) {
				appendPropertyRow(panel, labels[kind] ?? kind, String(count));
			}
			if (summary.replaced) {
				appendPropertyRow(panel, localize('arch.replaced', "Replaced"), localize('arch.replacedItems', "{0} items of the earlier import", summary.replaced));
			}
			for (const skipped of summary.skipped) {
				appendPropertyRow(panel, localize('arch.skipped', "Skipped"), skipped, true);
			}
			for (const note of summary.notes) {
				appendPropertyNote(panel, note);
			}
		}
	}

	/** The occupancy (an area use of the code pack, for the live load) of a roof or ramp. */
	private occupancyRow(panel: HTMLElement, id: string, occupancy: string | undefined, change: (fields: { readonly [field: string]: unknown }, notice: string) => void): void {
		const uses = Object.entries(BNBC.areaUses);
		this.selectRow(panel, localize('arch.occupancy', "Occupancy"), [{ id: '', text: localize('arch.none', "(none)") }, ...uses.map(([use, value]) => ({ id: use, text: localize('arch.useLive', "{0} ({1} kPa)", value.name, value.live) }))], occupancy ?? '',
			picked => change({ occupancy: picked || undefined }, localize('arch.occupancyChanged', "{0}: {1}.", id, picked ? BNBC.areaUses[picked]?.name ?? picked : localize('arch.noOccupancy', "no occupancy"))));
	}

	private inputRow(panel: HTMLElement, label: string, value: string, apply: (text: string) => void): void {
		const cell = $('.floor-plan-prop-control');
		const box = this.propertiesDisposables.add(new InputBox(cell, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: label }));
		box.value = value;
		const commit = () => {
			if (box.value !== value) {
				apply(box.value);
			}
		};
		this.propertiesDisposables.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				commit();
			}
		}));
		this.propertiesDisposables.add(addDisposableListener(box.inputElement, EventType.BLUR, commit));
		appendPropertyRow(panel, label, cell).classList.add('editable');
	}

	private selectRow(panel: HTMLElement, label: string, options: readonly { readonly id: string; readonly text: string }[], value: string, apply: (id: string) => void): void {
		const cell = $('.floor-plan-prop-control');
		const index = Math.max(0, options.findIndex(o => o.id === value));
		const select = this.propertiesDisposables.add(new SelectBox(options.map(o => ({ text: o.text })), index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
		select.render(cell);
		this.propertiesDisposables.add(select.onDidSelect(({ index: picked }) => {
			if (options[picked] && options[picked].id !== value) {
				apply(options[picked].id);
			}
		}));
		appendPropertyRow(panel, label, cell).classList.add('editable');
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Adopts an architect's IFC (walls, doors, windows, spaces) into this file, with a summary. */
	private async importIfc(): Promise<void> {
		const input = this.input as ArchitectureEditorInput | undefined;
		const model = this.archModel;
		const plan = this.planModel;
		if (!input || !model || !plan) {
			return;
		}
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('arch.pickIfc', "Import an Architect's IFC"),
			canSelectFiles: true,
			canSelectMany: false,
			filters: [{ name: localize('arch.ifcFiles', "IFC models"), extensions: ['ifc'] }],
			defaultUri: dirname(input.resource),
		});
		const source = picked?.[0];
		if (!source || this.input !== input) {
			return;
		}
		this.frame.showProgress();
		this.setNotice(localize('arch.importing', "Reading {0}...", source.path.split('/').pop() ?? ''));
		let result: IImportResult | undefined;
		try {
			result = await this.commandService.executeCommand<IImportResult>('saengine.architecture.importIfc', { path: source.fsPath, architectureText: model.getValue(), floorPlanText: plan.getValue() });
		} catch (error) {
			result = { problems: [String(error)] };
		} finally {
			this.frame.hideProgress();
		}
		if (this.input !== input) {
			return;
		}
		if (!result?.architecture || !result.summary) {
			const problem = result?.problems?.join(' ') ?? localize('arch.importNoAnswer', "the backend gave no answer");
			this.setNotice(localize('arch.importFailed', "The IFC could not be imported: {0}", problem));
			return;
		}
		const parsed = parseArchitecture(JSON.stringify(result.architecture));
		if (parsed.kind !== 'ok') {
			this.setNotice(parsed.message);
			return;
		}
		this.write(parsed.value);
		this.lastImport = { file: basename(source), summary: result.summary };
		const { adopted, skipped } = result.summary;
		const text = localize('arch.imported', "Adopted {0}, {1}, {2} and {3}; {4} skipped.", ...itemCounts(adopted), skipped.length);
		this.setNotice(text);
		this.selected = undefined;
		this.renderProperties();
		this.frame.setPropertiesVisible(true);
		this.notificationService.notify({ severity: skipped.length ? Severity.Warning : Severity.Info, message: text });
	}

	/**
	 * Adopts an architect's DWG/DXF plan: reads its layers, opens the layer-mapping step over the
	 * drawing, then imports with the mapping chosen as one undoable edit, with a summary.
	 */
	private async importDrawing(): Promise<void> {
		const input = this.input as ArchitectureEditorInput | undefined;
		if (!input || !this.archModel || !this.planModel || !this.arch || this.drawingImport) {
			return;
		}
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('arch.pickDrawing', "Import an Architect's DWG/DXF"),
			canSelectFiles: true,
			canSelectMany: false,
			filters: [{ name: localize('arch.drawingFiles', "Drawings (DWG, DXF)"), extensions: ['dwg', 'dxf'] }],
			defaultUri: dirname(input.resource),
		});
		const source = picked?.[0];
		if (!source || this.input !== input) {
			return;
		}
		this.frame.showProgress();
		this.setNotice(localize('arch.readingDrawing', "Reading the layers of {0}...", basename(source)));
		let info: IDrawingInfo | undefined;
		try {
			info = await this.commandService.executeCommand<IDrawingInfo>('saengine.architecture.inspectDrawing', { path: source.fsPath });
		} catch (error) {
			this.setNotice(localize('arch.drawingFailed', "The drawing could not be read: {0}", String(error)));
			return;
		} finally {
			this.frame.hideProgress();
		}
		if (this.input !== input || !this.arch || this.drawingImport) {
			return;
		}
		if (!info || info.problems?.length || !Array.isArray(info.layers)) {
			this.setNotice(localize('arch.drawingFailed', "The drawing could not be read: {0}", info?.problems?.join(' ') ?? localize('arch.importNoAnswer', "the backend gave no answer")));
			return;
		}
		// Recorded relative to the project folder when the drawing is in it, else by its full path.
		const inProject = relativePath(dirname(dirname(input.resource)), source);
		const panel = this.drawingImport = new DrawingImportPanel(this.frame.main, {
			info,
			name: basename(source),
			source: inProject && !inProject.startsWith('..') ? inProject : source.fsPath,
			arch: this.arch,
			floorPlan: parse(this.planModel),
			stories: storiesOf(parse(this.planModel)).map(s => ({ id: s.id, name: s.name })),
			story: input.story ?? '',
		}, this.contextViewService);
		panel.onDidCancel(() => {
			this.closeDrawingImport();
			this.setNotice(localize('arch.drawingCancelled', "Import cancelled."));
		});
		panel.onDidAccept(options => void this.runDrawingImport(input, source, options));
		this.setNotice(localize('arch.mapLayers', "Say what each layer of {0} holds, place it and press Import.", basename(source)));
		// The mapping step takes the whole editor; the properties come back when it closes.
		this.propertiesBeforeImport = this.frame.isPropertiesVisible;
		this.frame.setPropertiesVisible(false);
		this.updateToolbar();
		panel.focus();
	}

	private async runDrawingImport(input: ArchitectureEditorInput, source: URI, options: IDrawingImportOptions): Promise<void> {
		const panel = this.drawingImport;
		const model = this.archModel;
		const plan = this.planModel;
		if (!panel || !model || !plan) {
			return;
		}
		panel.setBusy(true);
		this.frame.showProgress();
		let result: IImportResult | undefined;
		try {
			result = await this.commandService.executeCommand<IImportResult>('saengine.architecture.importDrawing', { path: source.fsPath, architectureText: model.getValue(), floorPlanText: plan.getValue(), options });
		} catch (error) {
			result = { problems: [String(error)] };
		} finally {
			this.frame.hideProgress();
			panel.setBusy(false);
		}
		if (this.input !== input || this.drawingImport !== panel) {
			return;
		}
		const parsed = result?.architecture && result.summary ? parseArchitecture(JSON.stringify(result.architecture)) : undefined;
		if (!result?.summary || !parsed || parsed.kind !== 'ok') {
			const problem = parsed?.kind === 'error' ? parsed.message : result?.problems?.join(' ') ?? localize('arch.importNoAnswer', "the backend gave no answer");
			panel.setProblem(localize('arch.drawingImportFailed', "The drawing could not be imported: {0}", problem));
			return;
		}
		this.closeDrawingImport();
		input.story = options.story;
		this.selected = undefined;
		this.fitPending = true;
		this.userView = false;
		this.write(parsed.value);
		this.lastImport = { file: basename(source), summary: result.summary };
		const { adopted, skipped, replaced } = result.summary;
		const name = basename(source);
		const text = replaced
			? localize('arch.drawingReimported', "Adopted {0}, {1}, {2} and {3} from {4}, replacing its earlier import; {5} skipped.", ...itemCounts(adopted), name, skipped.length)
			: localize('arch.drawingImported', "Adopted {0}, {1}, {2} and {3} from {4}; {5} skipped.", ...itemCounts(adopted), name, skipped.length);
		this.setNotice(text);
		this.renderProperties();
		this.frame.setPropertiesVisible(true);
		this.notificationService.notify({ severity: skipped.length ? Severity.Warning : Severity.Info, message: text });
	}

	private closeDrawingImport(): void {
		const panel = this.drawingImport;
		if (panel) {
			this.drawingImport = undefined;
			panel.dispose();
			if (this.propertiesBeforeImport) {
				this.frame.setPropertiesVisible(true);
			}
			this.updateToolbar();
			this.frame.element.focus();
		}
	}

	private async open3d(): Promise<void> {
		const resource = this.resource;
		const bim = PROJECT_PARTS.find(p => p.id === 'bim')!;
		if (resource) {
			const options: IPartSectionOptions = { pinned: true, section: BIM_3D_SECTION };
			await this.editorService.openEditor({ resource: joinPath(dirname(dirname(resource)), bim.folder, bim.mainFile!), options });
		}
	}

	private async openText(): Promise<void> {
		const resource = this.resource;
		if (resource) {
			await this.editorService.openEditor({ resource, options: { pinned: true, override: 'default' } });
		}
	}

	private async openFloorPlan(): Promise<void> {
		const resource = this.resource;
		if (resource) {
			await this.editorService.openEditor({ resource: joinPath(dirname(resource), PROJECT_PARTS.find(p => p.id === 'floorPlan')!.mainFile!), options: { pinned: true } });
		}
	}
}
