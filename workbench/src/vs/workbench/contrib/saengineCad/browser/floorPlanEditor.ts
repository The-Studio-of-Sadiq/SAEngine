/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi, CadEntitySpec, CadGeneratedDrawing, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow, isEditableElement } from '../../../../base/browser/dom.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, IReference, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath, relativePath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService, ModelSelection } from '../../../services/saengineProject/common/modelSelection.js';
import { newFloorPlan } from '../../../services/saengineProject/common/partSources.js';
import { PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { IProjectDocuments, PropertyAction, propertySheet } from '../../saengineModel/browser/modelData.js';
import { openOwner } from '../../saengineModel/browser/projectDocuments.js';
import { propertyHeading, propertyLink, propertyNote, propertyRow, renderPropertySheet } from '../../saengineModel/browser/propertySheetView.js';
import { EditorFrame, IEditorFrameIconButton } from '../../saengineProject/browser/editorFrame.js';
import { acquireCadEditor, cadBackground, isLightCanvas, releaseCadEditor } from './cadHost.js';
import { floorPlanDrawing, IFloorPlan, IMemberShape, storiesOf, storyOfSelection } from './floorPlanDrawing.js';
import { basePoint, bayAt, changeMemberType, EditResult, IGridNode, moveMember, pickMember, placeColumn, placeLinear, placePolygonSlab, placeSlab, PlacementTool, removeMember, rotateMember, snapPoint, snapToGrid, TOOL_GROUP, TOOL_KINDS } from './floorPlanEdits.js';
import { FloorPlanEditorInput, siblingPartFile } from './floorPlanEditorInput.js';
import { copyStory, familyNote, familyOf, inSync, masterOf, setSimilar } from './floorPlanTypical.js';

const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';

/** The grids and stories form for the same file (registered by the library editors). */
const GRIDS_EDITOR_ID = 'workbench.editor.saengine.grids';

/** Below this editor width [px] the toolbar keeps the tools and moves the rest to its "..." menu. */
const COMPACT_WIDTH = 950;
/** Below this width [px] Move, Rotate and Delete go to "..." too. */
const NARROW_WIDTH = 700;

/** Screen distances: how close a click must be to a grid intersection or member, and marker size [px]. */
const SNAP_PIXELS = 24;
const PICK_PIXELS = 6;
const MARKER_PIXELS = 8;
/** Mouse travel below which a press counts as a click rather than a pan [px]. */
const CLICK_PIXELS = 5;

type Tool = 'select' | PlacementTool | 'polygonSlab' | 'move' | 'rotate' | 'delete';

const TOOLS: readonly { readonly tool: Tool; readonly label: string; readonly icon: ThemeIcon; readonly hint: string }[] = [
	{ tool: 'select', label: localize('tool.select', "Select"), icon: Codicon.inspect, hint: '' },
	{ tool: 'column', label: localize('tool.column', "Column"), icon: Codicon.primitiveSquare, hint: localize('hint.column', "Click a grid intersection to place a column rising to this story.") },
	{ tool: 'beam', label: localize('tool.beam', "Beam"), icon: Codicon.dash, hint: localize('hint.beam', "Click two grid intersections; beams chain until you press Esc or right-click.") },
	{ tool: 'wall', label: localize('tool.wall', "Wall"), icon: Codicon.splitHorizontal, hint: localize('hint.wall', "Click two grid intersections; walls chain until you press Esc or right-click.") },
	{ tool: 'slab', label: localize('tool.slab', "Slab"), icon: Codicon.layout, hint: localize('hint.slab', "Click inside a bay to place a slab on this story.") },
	{ tool: 'polygonSlab', label: localize('tool.polygonSlab', "Polygon Slab"), icon: Codicon.symbolConstant, hint: localize('hint.polygonSlab', "Click the slab's corners; finish on the first corner, with Enter or a right-click. Corners snap to intersections and grid lines.") },
	{ tool: 'move', label: localize('tool.move', "Move"), icon: Codicon.move, hint: localize('hint.move', "Click the member to move.") },
	{ tool: 'rotate', label: localize('tool.rotate', "Rotate"), icon: Codicon.refresh, hint: localize('hint.rotate', "Click a column or footing to rotate.") },
	{ tool: 'delete', label: localize('tool.delete', "Delete"), icon: Codicon.trash, hint: localize('hint.delete', "Click a member on this story to delete it.") },
];

const PREVIEW_LAYERS: readonly CadLayerSpec[] = [
	{ name: 'SAENGINE-PREVIEW', color: 2, description: 'Placement preview' },
	{ name: 'SAENGINE-PREVIEW-DELETE', color: 1, description: 'Member to delete' },
	{ name: 'SAENGINE-SELECTION', color: 4, description: 'Selected member' },
];

/**
 * Layer colours (AutoCAD Color Index) as drawn on a light canvas: the bright yellow, green, cyan
 * and magenta of a dark CAD screen are unreadable on white, so the screen shows deeper shades of
 * the same hues. Exported DXF keeps the standard colours.
 */
const LIGHT_CANVAS_COLORS: { readonly [aci: number]: number } = {
	2: 30,   // yellow -> orange (previews)
	3: 94,   // green -> dark green (beams)
	4: 144,  // cyan -> deep azure (columns, selection)
	6: 212,  // magenta -> deep magenta (slabs)
	30: 34,  // orange -> brown (footings)
};

function forCanvas(drawing: CadGeneratedDrawing, light: boolean): CadGeneratedDrawing {
	return light ? { ...drawing, layers: drawing.layers.map(layer => ({ ...layer, color: LIGHT_CANVAS_COLORS[layer.color] ?? layer.color })) } : drawing;
}

/** "150, -200", "150 -200" or "@150,-200" (AutoCAD's relative form) as a displacement in mm. */
function parseDisplacement(text: string): CadPoint | undefined {
	const parts = text.trim().replace(/^@/, '').split(/[\s,;]+/).filter(Boolean).map(Number);
	return parts.length === 2 && parts.every(Number.isFinite) ? [parts[0], parts[1]] : undefined;
}

/** The selection service's name for this editor. */
const SELECTION_SOURCE = 'floorPlan';

function parse(model: ITextModel | undefined): unknown {
	try {
		return model ? JSON.parse(model.getValue()) : undefined;
	} catch {
		return undefined;
	}
}

function isObject(value: unknown): value is { readonly [key: string]: unknown } {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function outlineEntities(shape: IMemberShape, layer: string): CadEntitySpec[] {
	const outline = shape.outline;
	return outline.kind === 'circle'
		? [{ kind: 'circle', layer, center: outline.center, radius: outline.radius }]
		: [{ kind: 'polyline', layer, points: outline.points, closed: true }];
}

/**
 * The floor plan (`floor-plan.json`) in the CAD editor, one story at a time, in the shared editor
 * frame: the story and the drawing tools in the toolbar (the rest in its overflow menu), the plan,
 * the selected member's properties (or the story's) in the properties panel, and the tool hint,
 * counts and cursor position in the status line. The floor plan owns the building's layout: this
 * editor places and deletes members as undoable edits of its text model, which the Grids &
 * Stories form edits too. Object types come from `objects.json`, read only, so edits there show
 * up as they are made.
 */
export class FloorPlanEditor extends EditorPane {

	static readonly ID = FloorPlanEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private cad!: HTMLElement;
	private host!: HTMLElement;
	private message!: HTMLElement;
	private storyPicker!: SelectBox;
	private typePicker!: SelectBox;
	private typeGroup!: HTMLElement;
	private typedGroup!: HTMLElement;
	private readonly typedControls = this._register(new DisposableStore());
	/** Tool and picked member the typed controls were built for. */
	private typedKey = '';
	/** What the editor shows as underlay now (story, file and placement), to reload only on change. */
	private underlayKey: string | undefined;
	private underlayProblem: string | undefined;

	private editor: CadEditorApi | undefined;
	private planModel: ITextModel | undefined;
	private objects: ITextModel | undefined;
	/** Optional, for the properties panel: material names and the building model's state. */
	private materials: ITextModel | undefined;
	private bim: ITextModel | undefined;
	private plan: IFloorPlan | undefined;
	private storyIds: string[] = [];
	private fitPending = false;
	private lightCanvas = false;

	private tool: Tool = 'select';
	/** Object type chosen per tool. */
	private readonly types = new Map<PlacementTool, string>();
	private typeIds: string[] = [];
	/** First point of a beam or wall being placed. */
	private chainStart: IGridNode | undefined;
	/** Member picked by the Move or Rotate tool. */
	private picked: IMemberShape | undefined;
	/** Corners of the polygon slab being drawn. */
	private polygon: CadPoint[] = [];
	private hover: CadPoint | undefined;
	private notice: string | undefined;
	/** Set while this editor writes the floor plan. */
	private writing = false;
	private actionsKey = '';
	/** A narrow editor keeps the tools, Zoom Extents and the panel toggle; the rest goes to "...". */
	private compact = false;
	/** A very narrow editor also moves Move, Rotate and Delete to "...". */
	private narrow = false;

	private readonly toolActions = new Map<Tool, Action>();
	private readonly undoAction = this._register(new Action('saengine.floorPlan.undo', localize('floorPlan.undo', "Undo"), ThemeIcon.asClassName(Codicon.discard), false, () => this.undoRedo(false)));
	private readonly redoAction = this._register(new Action('saengine.floorPlan.redo', localize('floorPlan.redo', "Redo"), ThemeIcon.asClassName(Codicon.redo), false, () => this.undoRedo(true)));
	private readonly zoomAction = this._register(new Action('saengine.floorPlan.zoomExtents', localize('floorPlan.zoomExtents', "Zoom Extents"), ThemeIcon.asClassName(Codicon.screenFull), true, async () => this.editor?.zoomExtents()));
	private readonly underlayAction = this._register(new Action('saengine.floorPlan.toggleUnderlay', localize('floorPlan.hideUnderlay', "Hide Underlay"), ThemeIcon.asClassName(Codicon.eye), false, async () => this.toggleUnderlay()));
	private readonly commandLineAction = this._register(new Action('saengine.floorPlan.commandLine', localize('floorPlan.showCommandLine', "Show Command Line (:)"), ThemeIcon.asClassName(Codicon.terminal), true, async () => this.toggleCommandLine()));
	private readonly gridsAction = this._register(new Action('saengine.floorPlan.editGrids', localize('floorPlan.editGrids', "Edit Grids and Stories"), undefined, true, async () => this.openGrids()));
	private readonly attachUnderlayAction = this._register(new Action('saengine.floorPlan.attachUnderlay', localize('floorPlan.attachUnderlay', "Attach Underlay..."), undefined, false, () => this.attachUnderlay()));
	private readonly removeUnderlayAction = this._register(new Action('saengine.floorPlan.removeUnderlay', localize('floorPlan.removeUnderlay', "Remove Underlay"), undefined, false, async () => this.changeUnderlay((this.input as FloorPlanEditorInput | undefined)?.story, undefined)));
	private readonly exportAction = this._register(new Action('saengine.floorPlan.exportDxf', localize('floorPlan.exportDxf', "Export DXF"), undefined, false, () => this.exportDxf()));
	/** Footings are placed in 9 Substructure since Part 9: the floor plan's Footing tool opens it. */
	private readonly foundationsAction = this._register(new Action('saengine.floorPlan.openSubstructure', localize('floorPlan.openSubstructure', "Place Footings in 9 Substructure"), ThemeIcon.asClassName(Codicon.symbolStructure), true, async () => this.openPart('substructure')));
	/** Typical floors: a master story and the stories that repeat its plan. */
	private readonly typicalAction = this._register(new Action('saengine.floorPlan.typicalFloors', localize('floorPlan.typicalFloors', "Typical Floors..."), ThemeIcon.asClassName(Codicon.layers), false, () => this.editTypicalFloors()));
	private readonly objectsAction = this._register(new Action('saengine.floorPlan.openObjects', localize('floorPlan.openObjects', "Open Object Types"), undefined, true, async () => this.openPart('objects')));
	private readonly createAction = this._register(new Action('saengine.floorPlan.create', localize('floorPlan.create', "Create Floor Plan"), undefined, true, () => this.createFloorPlan()));

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private readonly chromeDisposable = this._register(new MutableDisposable());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.renderPlan(), 150));
	private readonly previewFrame = this._register(new MutableDisposable());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IEditorService private readonly editorService: IEditorService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IFileService private readonly fileService: IFileService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
	) {
		super(FloorPlanEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.selectionService.onDidChangeSelection(({ source }) => {
			if (source !== SELECTION_SOURCE) {
				this.followSelection();
			}
			this.schedulePreview();
			this.renderProperties();
		}));
	}

	/** The floor plan file, for undo and redo. */
	get resource() {
		return (this.input as FloorPlanEditorInput | undefined)?.resource;
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: FloorPlanEditor.ID,
			ariaLabel: localize('floorPlan.toolbar', "Floor Plan"),
			properties: { title: localize('floorPlan.properties', "Properties") },
		}));
		frame.element.classList.add('saengine-floor-plan');
		frame.element.tabIndex = -1;

		this.storyPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.storyAria', "Story shown in the floor plan") }));
		this.storyPicker.render(append(frame.titleSlot, $('.floor-plan-select.story')));
		this._register(this.storyPicker.onDidSelect(({ index }) => {
			const input = this.input as FloorPlanEditorInput | undefined;
			if (input && this.storyIds[index] !== input.story) {
				input.story = this.storyIds[index];
				this.resetGesture();
				this.renderPlan();
			}
		}));

		// Inline controls of the active tool: the object type to place, the typed move or angle.
		this.typeGroup = append(frame.controlsSlot, $('.floor-plan-inline.hidden'));
		append(this.typeGroup, $('span.sa-frame-label', undefined, localize('floorPlan.type', "Type")));
		this.typePicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.typeAria', "Object type to place") }));
		this.typePicker.render(append(this.typeGroup, $('.floor-plan-select.type')));
		this._register(this.typePicker.onDidSelect(({ index }) => {
			const tool = this.placementTool;
			if (tool && this.typeIds[index]) {
				this.types.set(tool, this.typeIds[index]);
			}
		}));
		this.typedGroup = append(frame.controlsSlot, $('.floor-plan-inline.hidden'));

		for (const { tool, label, icon } of TOOLS) {
			this.toolActions.set(tool, this._register(new Action(`saengine.floorPlan.tool.${tool}`, label, ThemeIcon.asClassName(icon), true, async () => this.setTool(tool))));
		}

		this.cad = append(frame.main, $('.saengine-cad-editor'));
		this.host = append(this.cad, $('.cad-host'));
		this.message = append(this.cad, $('.cad-message'));
		this.registerMouse();
		this._register(addDisposableListener(frame.element, EventType.KEY_DOWN, e => this.onKey(e)));
		this.lightCanvas = isLightCanvas(this.themeService.getColorTheme());
		this.updateToolbar();
		this.updateStatus();
		this.renderProperties();
	}

	override async setInput(input: FloorPlanEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		this.release();
		await super.setInput(input, options, context, token);
		this.showMessage(undefined);

		let references: IReference<IResolvedTextEditorModel>[];
		try {
			references = await Promise.all([input.resource, siblingPartFile(input.resource, 'objects')].map(r => this.textModelService.createModelReference(r)));
		} catch (error) {
			this.showMessage(localize('floorPlan.noModel', "The building model could not be read: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			references.forEach(r => r.dispose());
			return;
		}
		references.forEach(r => this.inputDisposables.add(r));
		[this.planModel, this.objects] = references.map(r => r.object.textEditorModel);
		for (const model of [this.planModel, this.objects]) {
			this.inputDisposables.add(model.onDidChangeContent(() => {
				if (!this.writing) {
					// Undo, redo or another editor changed the plan: the last notice is stale.
					this.notice = undefined;
				}
				this.renderScheduler.schedule();
			}));
		}
		void this.trackOptional(input);

		let editor: CadEditorApi;
		try {
			const theme = this.themeService.getColorTheme();
			editor = this.editor = await acquireCadEditor(this.host, {
				// The editor's own toolbar has undo and redo; the command line opens on request.
				chrome: { commandLine: false, shortcutToolbar: false },
				background: cadBackground(theme),
			});
		} catch (error) {
			this.showMessage(localize('floorPlan.loadFailed', "The CAD editor could not start: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			this.release();
			return;
		}
		this.chromeDisposable.value = toDisposable(editor.onDidChangeChrome(() => this.updateToolbar()));
		if (!await editor.newDrawing({ readOnly: true })) {
			this.showMessage(localize('floorPlan.openFailed', "The floor plan drawing could not be created."));
			return;
		}
		this.fitPending = true;
		this.followSelection();
		this.renderPlan();
	}

	/** The materials and the building model, for the properties panel; neither is required. */
	private async trackOptional(input: FloorPlanEditorInput): Promise<void> {
		for (const id of ['materials', 'bim'] as const) {
			try {
				const reference = await this.textModelService.createModelReference(siblingPartFile(input.resource, id));
				if (this.input !== input) {
					reference.dispose();
					return;
				}
				this.inputDisposables.add(reference);
				const model = reference.object.textEditorModel;
				this[id] = model;
				this.inputDisposables.add(model.onDidChangeContent(() => this.renderProperties()));
			} catch {
				// Not there (yet): the panel says less.
			}
		}
		this.renderProperties();
	}

	/** Shows the story of the item selected elsewhere (Model Explorer, BIM). */
	private followSelection(): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		const selection = this.selectionService.selection;
		const story = selection && storyOfSelection(parse(this.planModel), selection);
		if (input && story && story !== input.story) {
			input.story = story;
			this.resetGesture();
			this.renderPlan();
		}
	}

	override clearInput(): void {
		this.release();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		const compact = dimension.width < COMPACT_WIDTH;
		const narrow = dimension.width < NARROW_WIDTH;
		if (compact !== this.compact || narrow !== this.narrow) {
			this.compact = compact;
			this.narrow = narrow;
			this.updateToolbar();
		}
		this.frame.layout(dimension.width, dimension.height);
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
		if (this.editor && this.planModel) {
			this.renderPlan();
		}
	}

	override dispose(): void {
		this.release();
		super.dispose();
	}

	private release(): void {
		this.renderScheduler.cancel();
		this.previewFrame.clear();
		this.chromeDisposable.clear();
		this.inputDisposables.clear();
		this.planModel = this.objects = this.materials = this.bim = undefined;
		this.plan = undefined;
		this.underlayKey = undefined;
		this.underlayProblem = undefined;
		this.resetGesture();
		if (this.editor) {
			releaseCadEditor(this.editor);
			this.editor = undefined;
		}
	}

	// ───────────────────────────── commands ─────────────────────────────

	/** Shows or hides the CAD command line ("Type command"); hidden until asked for. */
	toggleCommandLine(): void {
		const editor = this.editor;
		if (!editor) {
			return;
		}
		const visible = !editor.getChrome().commandLine;
		editor.setChrome({ commandLine: visible });
		if (visible) {
			getWindow(this.frame.element).setTimeout(() => editor.focusCommandLine(), 0);
		} else {
			this.frame.element.focus();
		}
	}

	private async undoRedo(redo: boolean): Promise<void> {
		const resource = this.resource;
		if (resource) {
			await (redo ? this.undoRedoService.redo(resource) : this.undoRedoService.undo(resource));
		}
		this.updateToolbar();
	}

	private onKey(e: KeyboardEvent): void {
		if (e.key === 'Escape' && (this.tool !== 'select' || this.chainStart || this.picked || this.polygon.length)) {
			e.preventDefault();
			e.stopPropagation();
			this.cancel();
		} else if (e.key === 'Enter' && this.tool === 'polygonSlab' && this.polygon.length) {
			e.preventDefault();
			this.finishPolygon();
		} else if (isEditableElement(e.target as HTMLElement)) {
			return; // typing in a field, the command line or a picker
		} else if (e.key === ':') {
			e.preventDefault();
			this.toggleCommandLine();
		} else if (e.key === 'Delete' && this.tool === 'select') {
			const selection = this.selectionService.selection;
			if (selection?.kind === 'member' && this.plan?.members.some(m => m.group === selection.group && m.id === selection.id)) {
				e.preventDefault();
				this.deleteMember(selection.group, selection.id);
			}
		}
	}

	// ───────────────────────────── tools ─────────────────────────────

	/** Drops a half-done gesture: a beam's first point, a picked member, a polygon's corners. */
	private resetGesture(): void {
		this.chainStart = undefined;
		this.picked = undefined;
		this.polygon = [];
	}

	private setTool(tool: Tool): void {
		this.tool = tool;
		this.resetGesture();
		this.notice = undefined;
		this.updateToolbar();
		this.updateStatus();
		this.schedulePreview();
		this.renderProperties();
		this.frame.element.focus();
	}

	/** Esc: drops the gesture in progress (a beam's first point, a picked member, corners), then the tool. */
	private cancel(): void {
		if (this.chainStart || this.picked || this.polygon.length) {
			this.resetGesture();
			this.notice = undefined;
			this.updateToolbar();
			this.updateStatus();
			this.schedulePreview();
			this.renderProperties();
		} else {
			this.setTool('select');
		}
	}

	/** The tool whose object types the Type picker offers. */
	private get placementTool(): PlacementTool | undefined {
		switch (this.tool) {
			case 'select': case 'delete': case 'move': case 'rotate': return undefined;
			case 'polygonSlab': return 'slab';
			default: return this.tool;
		}
	}

	/** Object types of these kinds, as [id, name]. */
	private typesOfKinds(kinds: readonly string[]): [string, string][] {
		const objects = parse(this.objects);
		const list = isObject(objects) && Array.isArray(objects.objects) ? objects.objects.filter(isObject) : [];
		return list
			.filter(o => typeof o.id === 'string' && kinds.includes(o.kind as string))
			.map(o => [o.id as string, typeof o.name === 'string' && o.name ? `${o.name} (${o.id})` : o.id as string]);
	}

	private get layoutState(): 'none' | 'placeholder' | 'invalid' | 'ok' {
		const layout = parse(this.planModel);
		if (!this.planModel) {
			return 'none';
		}
		if (isObject(layout) && layout.part === 'floorPlan') {
			return 'placeholder';
		}
		return isObject(layout) && layout.schema === FLOOR_PLAN_SCHEMA_ID ? 'ok' : 'invalid';
	}

	/** Brings the toolbar's buttons, the overflow menu and the inline controls up to date. */
	private updateToolbar(): void {
		const frame = this.frame;
		const state = this.layoutState;
		const editable = state === 'ok';
		for (const [tool, action] of this.toolActions) {
			action.checked = tool === this.tool;
			action.enabled = editable || tool === 'select';
		}
		const resource = this.resource;
		this.undoAction.enabled = !!resource && this.undoRedoService.canUndo(resource);
		this.redoAction.enabled = !!resource && this.undoRedoService.canRedo(resource);

		const input = this.input as FloorPlanEditorInput | undefined;
		const underlay = this.underlayOf(parse(this.planModel), input?.story);
		const visible = underlay?.visible !== false;
		this.underlayAction.enabled = editable && !!underlay;
		this.underlayAction.checked = !!underlay && visible;
		this.underlayAction.label = !underlay ? localize('floorPlan.noUnderlay', "Show Underlay (none attached: see More Actions)")
			: visible ? localize('floorPlan.hideUnderlayFile', "Hide Underlay ({0})", String(underlay.file)) : localize('floorPlan.showUnderlayFile', "Show Underlay ({0})", String(underlay.file));
		this.underlayAction.class = ThemeIcon.asClassName(underlay && !visible ? Codicon.eyeClosed : Codicon.eye);
		this.attachUnderlayAction.enabled = editable && !!input?.story;
		this.attachUnderlayAction.label = underlay ? localize('floorPlan.replaceUnderlay', "Replace Underlay...") : localize('floorPlan.attachUnderlay', "Attach Underlay...");
		this.removeUnderlayAction.enabled = editable && !!underlay;
		this.typicalAction.enabled = editable && storiesOf(parse(this.planModel)).length > 2;
		this.exportAction.enabled = editable && !!this.editor;
		const commandLine = !!this.editor?.getChrome().commandLine;
		this.commandLineAction.enabled = !!this.editor;
		this.commandLineAction.checked = commandLine;
		this.commandLineAction.label = commandLine ? localize('floorPlan.hideCommandLine', "Hide Command Line (:)") : localize('floorPlan.showCommandLine', "Show Command Line (:)");

		const tools = (names: readonly Tool[]) => names.map(name => this.toolActions.get(name)!);
		const primary: IAction[] = [
			...tools(['select']),
			new Separator(),
			...tools(['column', 'beam', 'wall', 'slab', 'polygonSlab']), this.foundationsAction,
			new Separator(),
			this.typicalAction,
			new Separator(),
			...(this.narrow ? [] : [...tools(['move', 'rotate', 'delete']), new Separator()]),
			...(this.compact ? [] : [this.undoAction, this.redoAction, new Separator()]),
			this.zoomAction, ...(this.compact ? [] : [this.underlayAction, this.commandLineAction]), frame.togglePropertiesAction,
		];
		const secondary: IAction[] = [
			...(state === 'placeholder' ? [this.createAction, new Separator()] : []),
			this.gridsAction,
			this.objectsAction,
			new Separator(),
			this.attachUnderlayAction,
			this.removeUnderlayAction,
			new Separator(),
			this.exportAction,
			...(this.compact ? [new Separator(), this.undoAction, this.redoAction, new Separator(), this.underlayAction, this.commandLineAction] : []),
			...(this.narrow ? [new Separator(), ...tools(['move', 'rotate', 'delete'])] : []),
		];
		const key = `${state}|${this.compact}|${this.narrow}`;
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			frame.setActions(primary, secondary);
		}

		// The object type the placement tool places.
		const tool = this.placementTool;
		this.typeGroup.classList.toggle('hidden', !tool);
		if (tool) {
			const types = this.typesOfKinds(TOOL_KINDS[tool]);
			this.typeIds = types.map(([id]) => id);
			let chosen = this.types.get(tool);
			if (!chosen || !this.typeIds.includes(chosen)) {
				chosen = this.typeIds[0];
				if (chosen) {
					this.types.set(tool, chosen);
				}
			}
			this.typePicker.setOptions(types.length ? types.map(([, name]) => ({ text: name })) : [{ text: localize('floorPlan.noTypes', "(none defined)") }], Math.max(0, this.typeIds.indexOf(chosen ?? '')));
		}
		this.updateTypedControls();
	}

	/** Exact entry for the picked member in the toolbar: a displacement for Move, an angle for Rotate. */
	private updateTypedControls(): void {
		const picked = this.picked;
		const tool = this.tool;
		const key = picked && (tool === 'move' || tool === 'rotate') ? `${tool}|${picked.group}|${picked.id}` : '';
		if (key === this.typedKey) {
			return;
		}
		this.typedKey = key;
		this.typedControls.clear();
		clearNode(this.typedGroup);
		this.typedGroup.classList.toggle('hidden', !key);
		if (!picked || (tool !== 'move' && tool !== 'rotate')) {
			return;
		}
		const box = this.typedControls.add(new InputBox(append(this.typedGroup, $('.floor-plan-typed')), this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			placeholder: tool === 'move' ? localize('floorPlan.displacementHint', "Δx, Δy in mm, e.g. 150, 0") : localize('floorPlan.angleHint', "Angle in degrees"),
			ariaLabel: tool === 'move' ? localize('floorPlan.displacementAria', "Displacement of {0} in millimetres", picked.id) : localize('floorPlan.angleAria', "Angle of {0} in degrees", picked.id),
		}));
		if (tool === 'rotate') {
			box.value = String(this.rotationOf(picked));
		}
		const apply = () => {
			if (tool === 'move') {
				const delta = parseDisplacement(box.value);
				if (delta) {
					this.moveBy(delta);
				} else {
					this.setNotice(localize('floorPlan.badDisplacement', "Type the displacement as two numbers in mm, e.g. 150, -200."));
				}
			} else {
				this.rotateTo(Number(box.value));
			}
			this.frame.element.focus();
		};
		this.typedControls.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				apply();
			}
		}));
		this.typedControls.add(this.frame.createIconButton(this.typedGroup, Codicon.check, tool === 'move' ? localize('floorPlan.applyMove', "Move") : localize('floorPlan.applyRotate', "Rotate"), apply));
		if (tool === 'rotate') {
			const quarter: IEditorFrameIconButton = this.typedControls.add(this.frame.createIconButton(this.typedGroup, Codicon.refresh, localize('floorPlan.rotate90', "Turn 90°"), () => this.rotateTo(this.rotationOf(picked) + 90)));
			quarter.element.classList.add('floor-plan-quarter');
		}
	}

	// ───────────────────────────── mouse ─────────────────────────────

	private registerMouse(): void {
		let down: { x: number; y: number } | undefined;
		this._register(addDisposableListener(this.host, EventType.POINTER_DOWN, e => {
			down = e.button === 0 ? { x: e.clientX, y: e.clientY } : undefined;
		}, true));
		this._register(addDisposableListener(this.host, EventType.POINTER_UP, e => {
			const start = down;
			down = undefined;
			if (e.button === 0 && start && Math.hypot(e.clientX - start.x, e.clientY - start.y) < CLICK_PIXELS && this.editor) {
				this.click(this.editor.toWorld(e.clientX, e.clientY));
			}
		}, true));
		this._register(addDisposableListener(this.host, EventType.POINTER_MOVE, e => {
			if (this.editor) {
				this.hover = this.editor.toWorld(e.clientX, e.clientY);
				this.schedulePreview();
			}
		}));
		this._register(addDisposableListener(this.host, EventType.POINTER_LEAVE, () => {
			this.hover = undefined;
			this.schedulePreview();
		}));
		this._register(addDisposableListener(this.host, EventType.CONTEXT_MENU, e => {
			if (this.tool === 'polygonSlab' && this.polygon.length >= 3) {
				e.preventDefault();
				this.finishPolygon();
			} else if (this.chainStart || this.picked || this.polygon.length) {
				e.preventDefault();
				this.cancel();
			}
		}, true));
	}

	private snap(point: CadPoint): IGridNode | undefined {
		return this.editor ? snapToGrid(parse(this.planModel), point, SNAP_PIXELS * this.editor.unitsPerPixel()) : undefined;
	}

	/** A free point: on an intersection or grid line when near one, else to the mm. */
	private snapFree(point: CadPoint): CadPoint {
		return this.editor ? snapPoint(parse(this.planModel), point, SNAP_PIXELS * this.editor.unitsPerPixel()) : point;
	}

	private pick(point: CadPoint): IMemberShape | undefined {
		return this.plan && this.editor ? pickMember(this.plan.members, point, PICK_PIXELS * this.editor.unitsPerPixel()) : undefined;
	}

	/** The rotation a column or footing has now, in degrees. */
	private rotationOf(shape: { readonly group: string; readonly id: string }): number {
		const layout = parse(this.planModel);
		const list = isObject(layout) && Array.isArray(layout[shape.group]) ? (layout[shape.group] as unknown[]).filter(isObject) : [];
		return Number(list.find(m => m.id === shape.id)?.rotation) || 0;
	}

	/** Moves the picked member so its base point lands on `target`. */
	private moveTo(target: CadPoint): void {
		const picked = this.picked;
		const layout = parse(this.planModel);
		const base = picked && basePoint(layout, picked.group, picked.id);
		if (picked && base) {
			this.moveBy([target[0] - base[0], target[1] - base[1]]);
		}
	}

	private moveBy(delta: CadPoint, member: { readonly group: IMemberShape['group']; readonly id: string } | undefined = this.picked): void {
		if (!member) {
			return;
		}
		const result = moveMember(parse(this.planModel), member.group, member.id, delta);
		if (result.ok) {
			this.picked = undefined;
			if (!this.writeEdit(result.layout, this.storyOfMember(member))) {
				return;
			}
			this.selectionService.setSelection({ kind: 'member', group: member.group, id: member.id }, SELECTION_SOURCE);
			this.setNotice(localize('floorPlan.moved', "Moved {0} by {1}, {2} mm.", member.id, Math.round(delta[0]), Math.round(delta[1])));
		} else {
			this.setNotice(result.error);
		}
		this.updateToolbar();
		this.schedulePreview();
	}

	private rotateTo(degrees: number, member: { readonly group: IMemberShape['group']; readonly id: string } | undefined = this.picked): void {
		if (!member) {
			return;
		}
		const result = rotateMember(parse(this.planModel), member.group, member.id, degrees);
		if (result.ok) {
			if (!this.writeEdit(result.layout, this.storyOfMember(member))) {
				return;
			}
			if (this.picked) {
				this.picked = this.plan?.members.find(m => m.group === member.group && m.id === member.id) ?? this.picked;
			}
			this.setNotice(localize('floorPlan.rotated', "Rotated {0} to {1}°.", member.id, this.rotationOf(member)));
		} else {
			this.setNotice(result.error);
		}
		this.schedulePreview();
	}

	private deleteMember(group: IMemberShape['group'], id: string): void {
		const layout = parse(this.planModel);
		if (!isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID) {
			return;
		}
		if (!this.writeEdit(removeMember(layout, group, id), this.storyOfMember({ group, id }))) {
			return;
		}
		const selection = this.selectionService.selection;
		if (selection?.kind === 'member' && selection.group === group && selection.id === id) {
			this.selectionService.setSelection(undefined, SELECTION_SOURCE);
		}
		this.setNotice(localize('floorPlan.deleted', "Deleted {0}.", id));
	}

	private finishPolygon(): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		const type = this.types.get('slab');
		const corners = this.polygon;
		this.polygon = [];
		if (!input?.story || !type) {
			this.setNotice(localize('floorPlan.needSlabType', "Define a slab type in Object Types first."));
			return;
		}
		const result = placePolygonSlab(parse(this.planModel), type, input.story, corners);
		if (result.ok) {
			if (this.writeEdit(result.layout, input.story)) {
				this.setNotice(localize('floorPlan.placed', "Placed {0}.", result.id));
			}
		} else {
			this.setNotice(result.error);
		}
		this.schedulePreview();
	}

	private click(point: CadPoint): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		const layout = parse(this.planModel);
		const story = input?.story;
		if (this.tool === 'select') {
			// Selecting shows the member (properties panel, Model Explorer); it never changes it.
			const shape = this.pick(point);
			this.selectionService.setSelection(shape ? { kind: 'member', group: shape.group, id: shape.id } : undefined, SELECTION_SOURCE);
			this.schedulePreview();
			return;
		}
		if (!story || !isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID) {
			return;
		}
		if (this.tool === 'delete') {
			const shape = this.pick(point);
			if (shape) {
				this.deleteMember(shape.group, shape.id);
			}
			return;
		}
		if (this.tool === 'move') {
			if (this.picked) {
				this.moveTo(this.snapFree(point));
			} else {
				this.picked = this.pick(point);
				this.setNotice(this.picked
					? localize('floorPlan.moveTarget', "Click where {0} goes (its {1} is the base point), or type the displacement.", this.picked.id, this.picked.group === 'columns' || this.picked.group === 'footings' ? localize('base.location', "location") : this.picked.group === 'slabs' ? localize('base.corner', "first corner") : localize('base.start', "start"))
					: localize('floorPlan.pickMember', "Click a member on this story."));
				this.updateToolbar();
				this.renderProperties();
			}
			this.schedulePreview();
			return;
		}
		if (this.tool === 'rotate') {
			const shape = this.pick(point);
			if (shape && this.picked && shape.group === this.picked.group && shape.id === this.picked.id) {
				this.rotateTo(this.rotationOf(shape) + 90);
			} else if (shape && shape.group !== 'columns' && shape.group !== 'footings') {
				this.picked = undefined;
				this.setNotice(localize('edit.notRotatable', "Only columns and footings rotate; beams, walls and slabs follow their points."));
			} else {
				this.picked = shape;
				this.setNotice(shape
					? localize('floorPlan.rotateHow', "Type the angle of {0}, or click it again to turn it 90°.", shape.id)
					: localize('floorPlan.pickRotatable', "Click a column or footing on this story."));
			}
			this.updateToolbar();
			this.renderProperties();
			this.schedulePreview();
			return;
		}
		if (this.tool === 'polygonSlab') {
			const corner = this.snapFree(point);
			const first = this.polygon[0];
			const closing = first && this.editor && Math.hypot(corner[0] - first[0], corner[1] - first[1]) <= SNAP_PIXELS * this.editor.unitsPerPixel();
			if (closing && this.polygon.length >= 3) {
				this.finishPolygon();
			} else if (!closing) {
				this.polygon.push(corner);
				this.setNotice(localize('floorPlan.corners', "{0} corner(s); finish on the first corner, with Enter or a right-click.", this.polygon.length));
			}
			this.schedulePreview();
			return;
		}
		const tool = this.tool;
		const type = this.types.get(tool);
		if (!type) {
			this.setNotice(localize('floorPlan.needType', "Define a {0} type in Object Types first.", TOOLS.find(t => t.tool === tool)!.label.toLowerCase()));
			return;
		}
		let result: EditResult | undefined;
		if (tool === 'slab') {
			const bay = bayAt(layout, point);
			result = bay ? placeSlab(layout, type, story, bay) : { ok: false, error: localize('floorPlan.outsideGrid', "Click inside a bay of the grid.") };
		} else {
			const node = this.snap(point);
			if (!node) {
				this.setNotice(localize('floorPlan.needNode', "Click closer to a grid intersection."));
				return;
			}
			if (tool === 'column') {
				result = placeColumn(layout, type, story, node);
			} else if (tool === 'footing') {
				this.openPart('substructure'); // footings are placed in 9 Substructure
				return;
			} else if (!this.chainStart) {
				this.chainStart = node;
				this.schedulePreview();
				return;
			} else {
				result = placeLinear(layout, tool, type, story, this.chainStart, node);
				if (result.ok || node.x !== this.chainStart.x || node.y !== this.chainStart.y) {
					this.chainStart = node; // keep chaining from the end point
				}
			}
		}
		if (result.ok) {
			if (this.writeEdit(result.layout, story)) {
				this.setNotice(localize('floorPlan.placed', "Placed {0}.", result.id));
			}
		} else {
			this.setNotice(result.error);
		}
		this.schedulePreview();
	}

	/** The story whose plan shows a member (a column's or wall's top story). */
	private storyOfMember(member: { readonly group: IMemberShape['group']; readonly id: string }): string | undefined {
		return storyOfSelection(parse(this.planModel), { kind: 'member', group: member.group, id: member.id });
	}

	/**
	 * Writes a member edit made on the plan of `story`, repeated on the other stories of its
	 * typical-floor family. Refuses (with a notice) when the family's plans differ, as after a
	 * story was made similar in Grids & Stories: the status bar offers to copy the master first.
	 */
	private writeEdit(layout: object, story: string | undefined): boolean {
		const before = parse(this.planModel);
		const family = story ? familyOf(before, story) : [];
		if (family.length > 1) {
			if (!inSync(before, family)) {
				this.setNotice(localize('floorPlan.familyDiffers', "The stories of this typical floor differ; copy the typical floor to them first."));
				return false;
			}
			layout = copyStory(layout, story!, family);
		}
		this.write(layout);
		return true;
	}

	/** " = Level 2" after a story that repeats Level 2, " (typical)" after a typical floor. */
	private familyLabel(layout: unknown, story: string): string {
		const note = familyNote(layout, story);
		const name = note.master && storiesOf(layout).find(s => s.id === note.master)?.name;
		return name ? ` = ${name}` : note.similar ? localize('floorPlan.typicalSuffix', " (typical)") : '';
	}

	/** Copies the typical floor of `story`'s family to its similar stories, as one undoable edit. */
	private syncFamily(story: string): void {
		const layout = parse(this.planModel);
		const master = masterOf(layout, story) ?? story;
		this.write(copyStory(layout, master, familyOf(layout, master)));
		this.setNotice(localize('floorPlan.familySynced', "Copied the typical floor to its similar stories."));
	}

	/** Asks for the typical floor and the stories that repeat it, then copies its plan to them. */
	private async editTypicalFloors(): Promise<void> {
		const input = this.input as FloorPlanEditorInput | undefined;
		const layout = parse(this.planModel);
		const stories = storiesOf(layout).slice(1); // nothing rises to the lowest story
		if (!input || stories.length < 2) {
			return;
		}
		const name = new Map(stories.map(s => [s.id, s.name]));
		const level = (elevation: number) => `${elevation >= 0 ? '+' : ''}${elevation}`;
		type Item = IQuickPickItem & { readonly story: string };
		const current = masterOf(layout, input.story ?? '') ?? input.story;
		const masters: Item[] = stories.map(s => {
			const size = masterOf(layout, s.id) ? 1 : familyOf(layout, s.id).length;
			return { story: s.id, label: s.name, description: level(s.elevation), detail: size > 1 ? localize('typical.repeats', "Typical floor of {0} stories", size) : undefined };
		});
		const master = await this.quickInputService.pick(masters, {
			title: localize('typical.title', "Typical Floors"),
			placeHolder: localize('typical.pickMaster', "The typical floor: the story whose plan the others repeat"),
			activeItem: masters.find(m => m.story === current),
		});
		if (!master) {
			return;
		}
		const others: Item[] = stories.filter(s => s.id !== master.story).map(s => ({ story: s.id, label: s.name, description: level(s.elevation), picked: masterOf(layout, s.id) === master.story }));
		const similar = await this.quickInputService.pick(others, {
			title: localize('typical.title', "Typical Floors"),
			placeHolder: localize('typical.pickSimilar', "Stories that repeat {0} (their plans are replaced by its plan)", master.label),
			canPickMany: true,
		});
		if (!similar) {
			return;
		}
		this.write(setSimilar(parse(this.planModel), master.story, similar.map(s => s.story)));
		const names = similar.map(s => name.get(s.story) ?? s.story);
		this.setNotice(!names.length ? localize('typical.none', "{0} is not a typical floor now.", master.label)
			: names.length === 1 ? localize('typical.one', "{0} repeats {1} now; edits on either apply to both.", names[0], master.label)
				: localize('typical.many', "{0} stories ({1} to {2}) repeat {3} now; edits on any of them apply to all.", names.length, names[0], names[names.length - 1], master.label));
	}

	/** Replaces the floor plan with `value` as one undoable edit. */
	private write(value: object): void {
		const model = this.planModel;
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
		this.renderPlan();
	}

	// ───────────────────────────── drawing ─────────────────────────────

	/** Regenerates the plan of the selected story from the current models. */
	private renderPlan(): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		if (!input || !this.editor || !this.planModel) {
			return;
		}
		const layout = parse(this.planModel);
		const stories = storiesOf(layout);
		this.storyIds = stories.map(s => s.id);
		if (!input.story || !this.storyIds.includes(input.story)) {
			// The first floor above the lowest level: the plan most people look at first.
			input.story = this.storyIds[Math.min(1, this.storyIds.length - 1)];
		}
		this.storyPicker.setOptions(
			stories.length ? stories.map(s => ({ text: `${s.name} (${s.elevation >= 0 ? '+' : ''}${s.elevation})${this.familyLabel(layout, s.id)}` })) : [{ text: localize('floorPlan.noStoriesOption', "(no stories)") }],
			Math.max(0, this.storyIds.indexOf(input.story ?? '')),
		);

		this.plan = floorPlanDrawing(layout, parse(this.objects), input.story ?? '');
		this.editor.setGenerated(forCanvas(this.plan.drawing, this.lightCanvas));
		void this.syncUnderlay(layout, input);
		if (this.fitPending) {
			this.fitPending = false;
			this.editor.zoomExtents();
		}
		this.updateToolbar();
		this.updateStatus();
		this.renderProperties();
		this.schedulePreview();
	}

	private schedulePreview(): void {
		if (!this.previewFrame.value && this.frame) {
			const handle = getWindow(this.frame.element).requestAnimationFrame(() => {
				this.previewFrame.clear();
				this.renderPreview();
				this.updateStatus();
			});
			this.previewFrame.value = { dispose: () => getWindow(this.frame.element).cancelAnimationFrame(handle) };
		}
	}

	/** Snap marker, rubber band, bay or member under the mouse for the active tool. */
	private renderPreview(): void {
		const editor = this.editor;
		if (!editor) {
			return;
		}
		const entities: CadEntitySpec[] = [];
		const [layer, deleteLayer] = PREVIEW_LAYERS.map(l => l.name);
		const units = editor.unitsPerPixel();
		const marker = ([x, y]: CadPoint) => {
			const r = MARKER_PIXELS * units;
			entities.push({ kind: 'polyline', layer, closed: true, points: [[x - r, y - r], [x + r, y - r], [x + r, y + r], [x - r, y + r]] });
		};
		const point = this.hover;
		if (this.chainStart) {
			marker(this.chainStart.point);
		}
		if (point && this.tool !== 'select') {
			if (this.tool === 'delete') {
				const shape = this.plan && pickMember(this.plan.members, point, PICK_PIXELS * units);
				if (shape) {
					entities.push(...outlineEntities(shape, deleteLayer));
				}
			} else if (this.tool === 'move' || this.tool === 'rotate') {
				const picked = this.picked;
				const base = picked && basePoint(parse(this.planModel), picked.group, picked.id);
				if (this.tool === 'move' && picked && base) {
					// The picked member drawn where it would land, and the move as a rubber band.
					const target = this.snapFree(point);
					const [dx, dy] = [target[0] - base[0], target[1] - base[1]];
					const outline = picked.outline;
					entities.push(...outlineEntities(outline.kind === 'circle'
						? { ...picked, outline: { ...outline, center: [outline.center[0] + dx, outline.center[1] + dy] } }
						: { ...picked, outline: { ...outline, points: outline.points.map(([x, y]) => [x + dx, y + dy] as CadPoint) } }, layer));
					entities.push({ kind: 'line', layer, start: base, end: target });
					marker(target);
				} else {
					const shape = this.plan && pickMember(this.plan.members, point, PICK_PIXELS * units);
					if (shape && (this.tool === 'move' || shape.group === 'columns' || shape.group === 'footings')) {
						entities.push(...outlineEntities(shape, layer));
					}
				}
			} else if (this.tool === 'polygonSlab') {
				const corner = this.snapFree(point);
				const points = [...this.polygon, corner];
				this.polygon.forEach(marker);
				marker(corner);
				if (points.length >= 2) {
					entities.push({ kind: 'polyline', layer, points, closed: points.length >= 3 });
				}
			} else if (this.tool === 'slab') {
				const bay = bayAt(parse(this.planModel), point);
				if (bay) {
					entities.push({ kind: 'polyline', layer, closed: true, points: bay.corners });
				}
			} else {
				const node = this.snap(point);
				if (node) {
					marker(node.point);
				}
				if (this.chainStart) {
					entities.push({ kind: 'line', layer, start: this.chainStart.point, end: node?.point ?? point });
				}
			}
		}
		const selection = this.selectionService.selection;
		const selected = this.picked ?? (selection?.kind === 'member' ? this.plan?.members.find(m => m.group === selection.group && m.id === selection.id) : undefined);
		if (selected) {
			entities.push(...outlineEntities(selected, PREVIEW_LAYERS[2].name));
		}
		editor.setPreview(forCanvas({ layers: PREVIEW_LAYERS, entities }, this.lightCanvas));
	}

	// ───────────────────────────── status line ─────────────────────────────

	private setNotice(text: string): void {
		this.notice = text;
		this.updateStatus();
	}

	/** One line: what to do now (or what just happened), the story's counts and the cursor position. */
	private updateStatus(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const state = this.layoutState;
		if (state === 'placeholder') {
			// The placeholder of projects made before the floor plan owned the layout.
			frame.setStatus({
				text: localize('floorPlan.empty', "This project has no floor plan yet. Creating it takes over the grids, stories and members of an older building model."),
				link: { label: localize('floorPlan.create', "Create Floor Plan"), run: () => void this.createFloorPlan() },
			});
			return;
		}
		if (state === 'invalid') {
			frame.setStatus({ severity: 'error', text: localize('floorPlan.invalidModel', "floor-plan.json is not a valid floor plan; open it as text to fix it. The plan cannot be edited until then.") });
			return;
		}
		const plan = this.plan;
		const parts: string[] = [];
		const hint = TOOLS.find(t => t.tool === this.tool)?.hint;
		const lead = this.notice ?? (hint || (this.planModel && this.storyIds.length === 0 ? localize('floorPlan.noStories', "The floor plan has no stories yet.") : undefined));
		if (lead) {
			parts.push(lead);
		}
		if (plan) {
			parts.push(localize('floorPlan.count', "{0} members on this story", plan.members.length));
		}
		const problems = (plan?.problems.length ?? 0) + (this.underlayProblem ? 1 : 0);
		if (problems) {
			parts.push(this.underlayProblem && !plan?.problems.length ? this.underlayProblem : localize('floorPlan.problems', "{0} member(s) could not be drawn", plan?.problems.length ?? 0));
		}
		if (this.hover) {
			parts.push(localize('floorPlan.cursor', "x {0}, y {1} mm", Math.round(this.hover[0]), Math.round(this.hover[1])));
		}
		const noTypes = !!this.placementTool && this.typeIds.length === 0;
		const story = (this.input as FloorPlanEditorInput | undefined)?.story;
		const layout = parse(this.planModel);
		const family = story ? familyOf(layout, story) : [];
		const differs = family.length > 1 && !inSync(layout, family);
		if (family.length > 1) {
			const master = storiesOf(layout).find(s => s.id === family[0])?.name ?? family[0];
			parts.splice(lead ? 1 : 0, 0, differs
				? localize('floorPlan.familyOutOfSync', "Typical floor {0}: its {1} stories differ", master, family.length)
				: localize('floorPlan.familyStatus', "Typical floor {0}: edits repeat on all {1} stories", master, family.length));
		}
		frame.setStatus({
			text: parts.join('  ·  '),
			severity: problems || differs ? 'warning' : undefined,
			link: differs && story ? { label: localize('floorPlan.copyTypical', "Copy the typical floor to them"), run: () => this.syncFamily(story) }
				: noTypes ? { label: localize('floorPlan.openObjects', "Open Object Types"), run: () => this.openPart('objects') }
				: problems ? { label: localize('floorPlan.showProblems', "Details"), run: () => this.frame.setPropertiesVisible(true) }
					: undefined,
		});
	}

	// ───────────────────────────── properties panel ─────────────────────────────

	private documents(): IProjectDocuments {
		return {
			floorPlan: parse(this.planModel),
			floorPlanText: this.planModel?.getValue(),
			objects: parse(this.objects),
			materials: parse(this.materials),
			bim: parse(this.bim),
		};
	}

	/**
	 * The selected member's properties, with what this editor can change about it (type, rotation,
	 * position); with nothing selected, the story's.
	 */
	private renderProperties(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		this.propertiesDisposables.clear();
		clearNode(panel);
		if (!this.planModel) {
			return;
		}
		const docs = this.documents();
		const input = this.input as FloorPlanEditorInput | undefined;
		const selected: ModelSelection | undefined = this.picked ? { kind: 'member', group: this.picked.group, id: this.picked.id } : this.selectionService.selection;
		const sheet = selected && propertySheet(selected, docs);
		const run = (action: PropertyAction, objectType?: string) => {
			const root = dirname(dirname(this.resource!));
			switch (action) {
				case 'editGrids': this.openGrids(); break;
				case 'editObjectType': void openOwner(objectType ? { kind: 'objectType', id: objectType } : undefined, 'objects', root, this.editorService); break;
			}
		};
		if (sheet && selected) {
			renderPropertySheet(panel, sheet, this.propertiesDisposables, action => run(action, sheet.objectType), ['showInFloorPlan']);
			if (selected.kind === 'member' && this.layoutState === 'ok') {
				this.renderMemberEdits(panel, selected);
			}
		} else {
			const story = input?.story;
			const storySheet = story ? propertySheet({ kind: 'story', id: story }, docs) : undefined;
			if (storySheet) {
				renderPropertySheet(panel, storySheet, this.propertiesDisposables, action => run(action), ['showInFloorPlan']);
			}
			const underlay = this.underlayOf(docs.floorPlan, story);
			if (underlay) {
				append(panel, $('.sa-props-section', undefined, localize('floorPlan.underlaySection', "Underlay")));
				propertyRow(panel, localize('floorPlan.underlayFile', "File"), String(underlay.file));
				propertyRow(panel, localize('floorPlan.underlayShown', "Shown"), underlay.visible === false ? localize('no', "No") : localize('yes', "Yes"));
			}
			propertyNote(panel, localize('floorPlan.selectHint', "Select a member in the plan to see and change its properties."));
		}
		const problems = [...(this.plan?.problems ?? []), ...(this.underlayProblem ? [this.underlayProblem] : [])];
		if (problems.length) {
			propertyHeading(panel, localize('floorPlan.problemsHeading', "Problems"));
			for (const problem of problems) {
				propertyNote(panel, problem);
			}
		}
	}

	/** Type, rotation and position of the selected member, changed as undoable edits. */
	private renderMemberEdits(panel: HTMLElement, member: Extract<ModelSelection, { kind: 'member' }>): void {
		const layout = parse(this.planModel);
		const list = isObject(layout) && Array.isArray(layout[member.group]) ? (layout[member.group] as unknown[]).filter(isObject) : [];
		const current = list.find(m => m.id === member.id);
		if (!current) {
			return;
		}
		const store = this.propertiesDisposables;
		append(panel, $('.sa-props-section', undefined, localize('floorPlan.editSection', "Change")));
		const tool = (Object.keys(TOOL_GROUP) as PlacementTool[]).find(t => TOOL_GROUP[t] === member.group);
		const types = tool ? this.typesOfKinds(TOOL_KINDS[tool]) : [];
		if (types.length) {
			const cell = $('.floor-plan-prop-control');
			const picker = store.add(new SelectBox(types.map(([, name]) => ({ text: name })), Math.max(0, types.findIndex(([id]) => id === current.type)), this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.memberTypeAria', "Object type of {0}", member.id) }));
			picker.render(cell);
			store.add(picker.onDidSelect(({ index }) => {
				const type = types[index]?.[0];
				if (type && type !== current.type) {
					const result = changeMemberType(parse(this.planModel), member.group, member.id, type);
					if (result.ok) {
						if (!this.writeEdit(result.layout, this.storyOfMember(member))) {
							return;
						}
						this.setNotice(localize('floorPlan.typeChanged', "{0} is a {1} now.", member.id, type));
					} else {
						this.setNotice(result.error);
					}
				}
			}));
			propertyRow(panel, localize('floorPlan.memberType', "Type"), cell).classList.add('editable');
		}
		const input = (label: string, value: string, placeholder: string, apply: (text: string) => void) => {
			const cell = $('.floor-plan-prop-control');
			const box = store.add(new InputBox(cell, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, placeholder, ariaLabel: `${label} ${member.id}` }));
			box.value = value;
			store.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter') {
					e.preventDefault();
					e.stopPropagation();
					apply(box.value);
				}
			}));
			propertyRow(panel, label, cell).classList.add('editable');
		};
		if (member.group === 'columns' || member.group === 'footings') {
			input(localize('floorPlan.rotation', "Rotation (°)"), String(this.rotationOf(member)), localize('floorPlan.angleHint', "Angle in degrees"), text => this.rotateTo(Number(text), member));
		}
		input(localize('floorPlan.moveBy', "Move by (mm)"), '', localize('floorPlan.displacementHint', "Δx, Δy in mm, e.g. 150, 0"), text => {
			const delta = parseDisplacement(text);
			if (delta) {
				this.moveBy(delta, member);
			} else {
				this.setNotice(localize('floorPlan.badDisplacement', "Type the displacement as two numbers in mm, e.g. 150, -200."));
			}
		});
		propertyNote(panel, localize('floorPlan.editNote', "Press Enter to apply. Each change is one undoable edit."));
		const links = append(panel, $('.sa-props-links'));
		propertyLink(links, localize('floorPlan.deleteMember', "Delete {0}", member.id), () => this.deleteMember(member.group, member.id), store);
	}

	/** Writes the first floor plan: the layout of an older `bim.json`, or the default grid. */
	private async createFloorPlan(): Promise<void> {
		const input = this.input as FloorPlanEditorInput | undefined;
		if (!input) {
			return;
		}
		let legacy: string | undefined;
		try {
			legacy = (await this.fileService.readFile(siblingPartFile(input.resource, 'bim'))).value.toString();
		} catch {
			legacy = undefined;
		}
		if (this.input === input) {
			this.fitPending = true;
			this.write(newFloorPlan(legacy));
		}
	}

	/** The grids and stories form, beside the plan so its edits show in the plan as they are made. */
	private openGrids(): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		if (input) {
			void this.editorService.openEditor({ resource: input.resource, options: { override: GRIDS_EDITOR_ID } }, SIDE_GROUP);
		}
	}

	// ───────────────────────────── underlays and export ─────────────────────────────

	/** The underlay of `story` in the floor plan, if it has one. */
	private underlayOf(layout: unknown, story: string | undefined): { readonly [key: string]: unknown } | undefined {
		const list = isObject(layout) && Array.isArray(layout.underlays) ? layout.underlays.filter(isObject) : [];
		return list.find(u => u.story === story);
	}

	private toggleUnderlay(): void {
		const story = (this.input as FloorPlanEditorInput | undefined)?.story;
		const underlay = this.underlayOf(parse(this.planModel), story);
		if (underlay) {
			const visible = underlay.visible !== false;
			this.changeUnderlay(story, u => ({ ...u, visible: !visible }));
		}
	}

	/** Picks a DXF and attaches it to the current story; files from elsewhere are copied into the project. */
	private async attachUnderlay(): Promise<void> {
		const input = this.input as FloorPlanEditorInput | undefined;
		const story = input?.story;
		if (!input || !story) {
			return;
		}
		const folder = dirname(input.resource);
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('floorPlan.pickUnderlay', "Attach an Architect's Drawing"),
			canSelectFiles: true,
			canSelectMany: false,
			filters: [{ name: localize('floorPlan.dxfFiles', "DXF Drawings"), extensions: ['dxf'] }],
			defaultUri: folder,
		});
		const source = picked?.[0];
		if (!source || this.input !== input) {
			return;
		}
		let file = relativePath(folder, source);
		if (!file || file.startsWith('..')) {
			// Keep the project self-contained: underlays live in 05 Floor Plan/Underlays.
			const underlays = joinPath(folder, 'Underlays');
			let target = joinPath(underlays, basename(source));
			for (let n = 2; await this.fileService.exists(target); n++) {
				target = joinPath(underlays, basename(source).replace(/(\.dxf)$/i, ` (${n})$1`));
			}
			await this.fileService.copy(source, target);
			file = relativePath(folder, target)!;
		}
		this.changeUnderlay(story, () => ({ story, file }));
	}

	/** Replaces (or with `undefined` removes) the underlay of `story`. */
	private changeUnderlay(story: string | undefined, change: ((underlay: { readonly [key: string]: unknown }) => object) | undefined): void {
		const layout = parse(this.planModel);
		if (!story || !isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID) {
			return;
		}
		const list = Array.isArray(layout.underlays) ? layout.underlays.filter(isObject) : [];
		const current = list.find(u => u.story === story);
		const others = list.filter(u => u !== current);
		const next = change ? [...others, change(current ?? { story })] : others;
		this.write({ ...layout, underlays: next });
	}

	/** Loads the current story's underlay into the CAD editor when it changed. */
	private async syncUnderlay(layout: unknown, input: FloorPlanEditorInput): Promise<void> {
		const editor = this.editor;
		const underlay = this.underlayOf(layout, input.story);
		const shown = underlay && underlay.visible !== false ? underlay : undefined;
		const key = shown ? JSON.stringify([shown.file, shown.dx, shown.dy, shown.scale, shown.rotation]) : '';
		if (!editor || key === this.underlayKey) {
			return;
		}
		this.underlayKey = key;
		this.underlayProblem = undefined;
		if (!shown) {
			await editor.setUnderlay(undefined);
			return;
		}
		const file = String(shown.file);
		let dxf: string;
		try {
			dxf = (await this.fileService.readFile(joinPath(dirname(input.resource), file))).value.toString();
		} catch {
			this.underlayProblem = localize('floorPlan.underlayMissing', "The underlay {0} could not be read.", file);
			await editor.setUnderlay(undefined);
			this.updateStatus();
			this.renderProperties();
			return;
		}
		if (this.editor !== editor || this.underlayKey !== key) {
			return;
		}
		const num = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback;
		try {
			await editor.setUnderlay({ name: basename(URI.file(file)), dxf, offset: [num(shown.dx, 0), num(shown.dy, 0)], scale: num(shown.scale, 1), rotation: num(shown.rotation, 0) });
		} catch (error) {
			this.underlayProblem = localize('floorPlan.underlayFailed', "The underlay {0} could not be shown: {1}", file, String(error));
			this.updateStatus();
			this.renderProperties();
		}
	}

	/** Writes the structural plan of every story to `11 Exports/Floor Plan/<story>.dxf`. */
	async exportDxf(): Promise<void> {
		const input = this.input as FloorPlanEditorInput | undefined;
		const editor = this.editor;
		const layout = parse(this.planModel);
		if (!input || !editor || !isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID) {
			return;
		}
		const exports = PROJECT_PARTS.find(p => p.id === 'exports')!;
		const folder = joinPath(dirname(dirname(input.resource)), exports.folder, 'Floor Plan');
		const objects = parse(this.objects);
		const stories = storiesOf(layout);
		editor.setPreview({ layers: [], entities: [] });
		this.frame.showProgress();
		try {
			for (const story of stories) {
				// The standard layer colours, whatever the screen shows.
				editor.setGenerated(floorPlanDrawing(layout, objects, story.id).drawing);
				const name = `${story.id} ${story.name}`.replace(/[\\/:*?"<>|]/g, '-');
				await this.fileService.writeFile(joinPath(folder, `${name}.dxf`), VSBuffer.fromString(editor.toDxf()));
			}
			this.setNotice(localize('floorPlan.exported', "Exported the plans of {0} stories to {1}/Floor Plan.", stories.length, exports.folder));
		} catch (error) {
			this.setNotice(localize('floorPlan.exportFailed', "The export failed: {0}", String(error)));
		} finally {
			this.frame.hideProgress();
			this.renderPlan();
		}
	}

	private openPart(id: string): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		if (input) {
			this.editorService.openEditor({ resource: siblingPartFile(input.resource, id) });
		}
	}

	private showMessage(text: string | undefined): void {
		clearNode(this.message);
		this.message.classList.toggle('visible', !!text);
		if (text) {
			this.message.textContent = text;
		}
	}
}
