/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi, CadEntitySpec, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow, isEditableElement, isHTMLElement, isHTMLInputElement } from '../../../../base/browser/dom.js';
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
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextMenuService, IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
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
import { ISaenginePartStatusService } from '../../../services/saengineProject/common/partStatus.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { IPlotCheckRequest, IPlotCheckResult, IPlotWarning, SOIL_PLOT_CHECK_COMMAND } from '../../saengineSoil/browser/soilDocument.js';
import { IProjectDocuments, PropertyAction, propertySheet } from '../../saengineModel/browser/modelData.js';
import { openOwner } from '../../saengineModel/browser/projectDocuments.js';
import { propertyLink, renderPropertySheet } from '../../saengineModel/browser/propertySheetView.js';
import { editNotice, IMemberRef as IModifierMemberRef, memberTargets, modifiersView, readCodeStiffness, resetMembersGroup, setMembersField } from '../../saengineModel/browser/modifiersModel.js';
import { renderModifiers } from '../../saengineModel/browser/modifiersPanel.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameIconButton } from '../../saengineProject/browser/editorFrame.js';
import { DWG_TO_DXF_COMMAND, OPEN_DXF_IN_CAD_UI_COMMAND } from '../../saengineProject/browser/projectArchiveModel.js';
import { acquireCadEditor, cadBackground, forCanvas, isLightCanvas, releaseCadEditor } from './cadHost.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { floorPlanDrawing, gridsOf, IFloorPlan, IMemberShape, storyOfSelection } from './floorPlanDrawing.js';
import { basePoint, bayAt, changeMemberType, EditResult, footingsOwnedMessage, notRotatableMessage, IGridNode, moveMember, pickMember, placeColumn, placeLinear, placePolygonSlab, placeSlab, PlacementTool, removeMember, rotateMember, setMembersType, snapPoint, snapToGrid, TOOL_GROUP, TOOL_KINDS } from './floorPlanEdits.js';
import { FloorPlanEditorInput, siblingPartFile } from './floorPlanEditorInput.js';
import { ISnap, nearMisses, SNAP_NAMES, snapLinear, snapMarker, squareMarker, typedEnd } from './floorPlanSnap.js';
import { addObjectType, NEW_TYPE_PROMPTS, NewTypeKind, validateSize } from './floorPlanTypes.js';
import { FloorPlanLoadsFile, FloorPlanLoadsPanel, LOAD_LAYER_SPECS, loadsDrawing } from './floorPlanLoads.js';
import { copyStory, familyDiffersMessage, familyNote, familyOf, inSync, masterOf, repeatFamily, setSimilar } from './floorPlanTypical.js';
import { BulkResult, bulkNotice, BulkVerb, COMMAND_HELP, copyMembers, copyToClipboard, copyToStories, deleteMembers, fill, FillDirection, FillKind, FloorPlanCommand, IFloorPlanClipboard, mirrorMembers, moveMembers, parseCommand, paste, rotateMembers } from './floorPlanBulk.js';
import { combine, commonFields, countByGroup, IMemberRef, IRect, prune, rectOf, sameMember, selectAll, selectByType, selectInWindow, selectionSummary, typesOnPlan, windowMode } from './floorPlanSelection.js';

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
/** Linetype scale of a crossing window's dashes per screen pixel. */
const WINDOW_DASH_PIXELS = 20;
/** Mouse travel below which a press counts as a click rather than a pan [px]. */
const CLICK_PIXELS = 5;

type Tool = 'select' | PlacementTool | 'polygonSlab' | 'fill' | 'move' | 'rotate' | 'delete';

const TOOLS: readonly { readonly tool: Tool; readonly label: string; readonly icon: ThemeIcon; readonly hint: string }[] = [
	{ tool: 'select', label: localize('tool.select', "Select"), icon: Codicon.inspect, hint: localize('hint.select', "Click to select, Ctrl+click to add or remove; drag a window left to right for members inside it, right to left for members it touches.") },
	{ tool: 'column', label: localize('tool.column', "Column"), icon: Codicon.primitiveSquare, hint: localize('hint.column', "Click a grid intersection to place a column rising to this story.") },
	{ tool: 'beam', label: localize('tool.beam', "Beam"), icon: Codicon.dash, hint: localize('hint.beam', "Click the start and end: they snap to grid intersections, columns, beam ends, midpoints, intersections, perpendiculars and any point on a beam (secondary beams); elsewhere is a free end (cantilevers). Type a length for the end. Beams chain until Esc or right-click.") },
	{ tool: 'wall', label: localize('tool.wall', "Wall"), icon: Codicon.splitHorizontal, hint: localize('hint.wall', "Click the start and end (they snap like beam ends); type a length for the end. Walls chain until Esc or right-click.") },
	{ tool: 'slab', label: localize('tool.slab', "Slab"), icon: Codicon.layout, hint: localize('hint.slab', "Click inside a bay to place a slab on this story.") },
	{ tool: 'polygonSlab', label: localize('tool.polygonSlab', "Polygon Slab"), icon: Codicon.symbolConstant, hint: localize('hint.polygonSlab', "Click the slab's corners; finish on the first corner, with Enter or a right-click. Corners snap to intersections and grid lines.") },
	{ tool: 'fill', label: localize('tool.fill', "Fill"), icon: Codicon.table, hint: localize('hint.fill', "Drag a window over the grid to place members on every intersection, segment or bay inside it.") },
	{ tool: 'move', label: localize('tool.move', "Move"), icon: Codicon.move, hint: localize('hint.move', "Click the member to move.") },
	{ tool: 'rotate', label: localize('tool.rotate', "Rotate"), icon: Codicon.refresh, hint: localize('hint.rotate', "Click a column to rotate it (footings turn in 9 Substructure).") },
	{ tool: 'delete', label: localize('tool.delete', "Delete"), icon: Codicon.trash, hint: localize('hint.delete', "Click a member on this story to delete it.") },
];

const PREVIEW_LAYERS: readonly CadLayerSpec[] = [
	{ name: 'SAENGINE-PREVIEW', color: 2, description: 'Placement preview' },
	{ name: 'SAENGINE-PREVIEW-DELETE', color: 1, description: 'Member to delete' },
	{ name: 'SAENGINE-SELECTION', color: 2, description: 'Selected members (yellow, as CAD highlights; orange on a light canvas)' },
	{ name: 'SAENGINE-WINDOW', color: 5, description: 'Selection window (members inside)' },
	{ name: 'SAENGINE-CROSSING', color: 3, linetype: 'DASHED', description: 'Crossing window (members touched)' },
];

/** The fill tool's choices: what it places, and along which grid segments. */
const FILL_CHOICES: readonly { readonly kind: FillKind; readonly direction: FillDirection; readonly label: string }[] = [
	{ kind: 'columns', direction: 'both', label: localize('fill.columns', "Columns at Intersections") },
	{ kind: 'beams', direction: 'both', label: localize('fill.beams', "Beams on Grid Segments") },
	{ kind: 'beams', direction: 'x', label: localize('fill.beamsX', "Beams along X") },
	{ kind: 'beams', direction: 'y', label: localize('fill.beamsY', "Beams along Y") },
	{ kind: 'slabs', direction: 'both', label: localize('fill.slabs', "Slabs in Bays") },
	{ kind: 'walls', direction: 'both', label: localize('fill.walls', "Walls on Grid Segments") },
	{ kind: 'walls', direction: 'x', label: localize('fill.wallsX', "Walls along X") },
	{ kind: 'walls', direction: 'y', label: localize('fill.wallsY', "Walls along Y") },
];

/** Plural names of the member groups, for the properties of a multi-selection. */
const GROUP_LABEL: { readonly [group in IMemberRef['group']]: string } = {
	columns: localize('group.columns', "columns"),
	beams: localize('group.beams', "beams"),
	walls: localize('group.walls', "walls"),
	slabs: localize('group.slabs', "slabs"),
	footings: localize('group.footings', "footings"),
};

const FILL_TOOL: { readonly [kind in FillKind]: PlacementTool } = { columns: 'column', beams: 'beam', walls: 'wall', slabs: 'slab' };

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

/** `shape` moved by `dx`, `dy`. */
function shifted(shape: IMemberShape, dx: number, dy: number): IMemberShape {
	const outline = shape.outline;
	return outline.kind === 'circle'
		? { ...shape, outline: { ...outline, center: [outline.center[0] + dx, outline.center[1] + dy] } }
		: { ...shape, outline: { ...outline, points: outline.points.map(([x, y]) => [x + dx, y + dy] as CadPoint) } };
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
	private static datalists = 0;

	private frame!: EditorFrame;
	private cad!: HTMLElement;
	private host!: HTMLElement;
	private message!: HTMLElement;
	/** What to do first on a plan without members; closed for the session with its X. */
	private emptyState!: HTMLElement;
	private emptyKey = '';
	private emptyDismissed = false;
	private readonly emptyDisposables = this._register(new DisposableStore());
	private storyPicker!: SelectBox;
	private typePicker!: SelectBox;
	private typeGroup!: HTMLElement;
	private typedGroup!: HTMLElement;
	private readonly typedControls = this._register(new DisposableStore());
	/** The typed length of the beam or wall being drawn, while one is. */
	private lengthBox: InputBox | undefined;
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
	/** Optional: the project settings, for the code's stiffness factors the modifiers inherit. */
	private settings: ITextModel | undefined;
	/** Optional: the soil report, whose site's plot is drawn under every story. */
	private soil: ITextModel | undefined;
	/** The backend's check of the floor plan against the plot, and the model versions it was made for. */
	private plotCheck: IPlotCheckResult | undefined;
	private plotCheckKey: string | undefined;
	private readonly plotScheduler = this._register(new RunOnceScheduler(() => void this.checkPlot(), 400));
	private plan: IFloorPlan | undefined;
	private storyIds: string[] = [];
	private fitPending = false;
	/** Set once the user zooms or pans: from then on a resize keeps their view. */
	private userView = false;
	private readonly fitScheduler = this._register(new RunOnceScheduler(() => this.editor?.zoomExtents(), 100));
	private lightCanvas = false;

	private tool: Tool = 'select';
	/** Object type chosen per tool. */
	private readonly types = new Map<PlacementTool, string>();
	private typeIds: string[] = [];
	/** First point of a beam or wall being placed. */
	private chainStart: ISnap | undefined;
	/** Where the end of the beam or wall under the mouse snaps, for the status line. */
	private hoverSnap: ISnap | undefined;
	/** Member picked by the Move or Rotate tool. */
	private picked: IMemberShape | undefined;
	/** Corners of the polygon slab being drawn. */
	private polygon: CadPoint[] = [];
	private hover: CadPoint | undefined;
	private notice: string | undefined;
	/** Set while this editor writes the floor plan. */
	private writing = false;
	/** The model versions around this editor's last write, until its notice names it. */
	private pendingWrite: { readonly before: number; readonly after: number } | undefined;
	/** What undoing (by the version it undoes from) or redoing (by the version it redoes from) does. */
	private readonly undoLabels = new Map<number, string>();
	private readonly redoLabels = new Map<number, string>();
	private actionsKey = '';
	/** A narrow editor keeps the tools, Zoom Extents and the panel toggle; the rest goes to "...". */
	private compact = false;
	/** A very narrow editor also moves Move, Rotate and Delete to "...". */
	private narrow = false;

	/** The members selected on the plan; the selection service holds the one picked last. */
	private selected: IMemberRef[] = [];
	/** The fill tool's choice in {@link FILL_CHOICES}. */
	private fillChoice = 0;
	private fillPicker!: SelectBox;
	private fillGroup!: HTMLElement;
	/** A window being dragged with the Select or Fill tool: where it started and where the mouse is. */
	private drag: { readonly start: CadPoint; readonly client: { readonly x: number; readonly y: number }; current?: CadPoint } | undefined;
	/** Members copied with Ctrl+C, with their outlines for the paste preview. */
	private clipboard: { readonly data: IFloorPlanClipboard; readonly shapes: readonly IMemberShape[] } | undefined;
	/** Set by Ctrl+V until the base point is clicked. */
	private pasting = false;

	private readonly toolActions = new Map<Tool, Action>();
	private readonly undoAction = this._register(new Action('saengine.floorPlan.undo', localize('floorPlan.undo', "Undo"), ThemeIcon.asClassName(Codicon.discard), false, () => this.undoRedo(false)));
	private readonly redoAction = this._register(new Action('saengine.floorPlan.redo', localize('floorPlan.redo', "Redo"), ThemeIcon.asClassName(Codicon.redo), false, () => this.undoRedo(true)));
	private readonly zoomAction = this._register(new Action('saengine.floorPlan.zoomExtents', localize('floorPlan.zoomExtents', "Zoom Extents"), ThemeIcon.asClassName(Codicon.screenFull), true, async () => {
		this.userView = false;
		this.editor?.zoomExtents();
	}));
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
	private readonly selectAllAction = this._register(new Action('saengine.floorPlan.selectAll', localize('floorPlan.selectAll', "Select All on Story (Ctrl+A)"), undefined, true, async () => this.select(selectAll(this.plan?.members ?? []))));
	private readonly selectTypeAction = this._register(new Action('saengine.floorPlan.selectByType', localize('floorPlan.selectByType', "Select by Type..."), undefined, true, () => this.pickSelectByType()));
	private readonly copyStoriesAction = this._register(new Action('saengine.floorPlan.copyToStories', localize('floorPlan.copyToStories', "Copy Selection to Stories..."), ThemeIcon.asClassName(Codicon.layers), false, () => this.pickCopyToStories()));
	private readonly mirrorAction = this._register(new Action('saengine.floorPlan.mirror', localize('floorPlan.mirror', "Mirror Selection..."), ThemeIcon.asClassName(Codicon.mirror), false, () => this.pickMirror()));
	/** Integrator glue: the Members Table (floorPlanTable.ts registers the command; by id, so this file does not import it). */
	private readonly membersTableAction = this._register(new Action('saengine.floorPlan.membersTable', localize('floorPlan.membersTable', "Members Table"), ThemeIcon.asClassName(Codicon.table), true, async () => { await this.commandService.executeCommand('saengine.floorPlan.openMembersTable'); }));
	private readonly deleteSelectionAction = this._register(new Action('saengine.floorPlan.deleteSelection', localize('floorPlan.deleteSelection', "Delete Selection (Delete)"), undefined, false, async () => this.runCommand({ kind: 'delete' })));

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private readonly chromeDisposable = this._register(new MutableDisposable());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.renderPlan(), 150));
	private readonly previewFrame = this._register(new MutableDisposable());
	/** Line and point loads of `05 Floor Plan/loads.json`, drawn on the plan and edited in the properties panel. */
	private readonly loadsFile: FloorPlanLoadsFile;
	private readonly loadsPanel: FloorPlanLoadsPanel;

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
		@ICommandService private readonly commandService: ICommandService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISaenginePartStatusService private readonly partStatusService: ISaenginePartStatusService,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super(FloorPlanEditor.ID, group, telemetryService, themeService, storageService);
		this.loadsFile = this._register(this.instantiationService.createInstance(FloorPlanLoadsFile));
		this.loadsPanel = this._register(this.instantiationService.createInstance(FloorPlanLoadsPanel, this.loadsFile));
		this._register(this.loadsFile.onDidChange(() => this.renderScheduler.schedule()));
		this._register(this.selectionService.onDidChangeSelection(({ source, selection }) => {
			if (source !== SELECTION_SOURCE) {
				// Selected elsewhere (Model Explorer, BIM): that member alone.
				this.selected = selection?.kind === 'member' ? [{ group: selection.group, id: selection.id }] : [];
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

		// Inline controls of the active tool: what the fill places, the object type to place, the typed move or angle.
		this.fillGroup = append(frame.controlsSlot, $('.floor-plan-inline.hidden'));
		append(this.fillGroup, $('span.sa-frame-label', undefined, localize('floorPlan.fill', "Fill")));
		this.fillPicker = this._register(new SelectBox(FILL_CHOICES.map(c => ({ text: c.label })), 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.fillAria', "What the fill tool places") }));
		this.fillPicker.render(append(this.fillGroup, $('.floor-plan-select.fill')));
		this._register(this.fillPicker.onDidSelect(({ index }) => {
			this.fillChoice = index;
			this.updateToolbar();
		}));
		this.typeGroup = append(frame.controlsSlot, $('.floor-plan-inline.hidden'));
		append(this.typeGroup, $('span.sa-frame-label', undefined, localize('floorPlan.type', "Type")));
		this.typePicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.typeAria', "Object type to place") }));
		this.typePicker.render(append(this.typeGroup, $('.floor-plan-select.type')));
		this._register(this.typePicker.onDidSelect(({ index }) => {
			const tool = this.placementTool;
			if (tool && this.typeIds[index]) {
				this.types.set(tool, this.typeIds[index]);
			} else if (tool && tool !== 'footing' && index >= this.typeIds.length) {
				void this.createType(tool);
			}
		}));
		this.typedGroup = append(frame.controlsSlot, $('.floor-plan-inline.hidden'));

		for (const { tool, label, icon } of TOOLS) {
			this.toolActions.set(tool, this._register(new Action(`saengine.floorPlan.tool.${tool}`, label, ThemeIcon.asClassName(icon), true, async () => this.setTool(tool))));
		}

		this.cad = append(frame.main, $('.saengine-cad-editor'));
		this.host = append(this.cad, $('.cad-host'));
		this.message = append(this.cad, $('.cad-message'));
		this.emptyState = append(this.cad, $('.floor-plan-empty.hidden'));
		this.registerMouse();
		this._register(addDisposableListener(frame.element, EventType.KEY_DOWN, e => this.onKey(e)));
		// The floor plan's own commands typed on the CAD command line (select, fill, copy, ...).
		this._register(addDisposableListener(getWindow(frame.element), EventType.KEY_DOWN, e => this.onCommandLineKey(e), true));
		this._register(addDisposableListener(this.host, EventType.FOCUS_IN, e => this.suggestCommands(e)));
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
		void this.trackSoil(input);
		void this.loadsFile.open(input.resource);

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
		this.userView = false;
		this.followSelection();
		this.renderPlan();
	}

	/** The materials and the building model, for the properties panel; neither is required. */
	private async trackOptional(input: FloorPlanEditorInput): Promise<void> {
		for (const id of ['materials', 'bim', 'settings'] as const) {
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

	/** The soil report, for the site's plot; not there (or a placeholder): no plot. */
	private async trackSoil(input: FloorPlanEditorInput): Promise<void> {
		try {
			const reference = await this.textModelService.createModelReference(siblingPartFile(input.resource, 'soil'));
			if (this.input !== input) {
				reference.dispose();
				return;
			}
			this.inputDisposables.add(reference);
			this.soil = reference.object.textEditorModel;
			this.inputDisposables.add(this.soil.onDidChangeContent(() => this.plotScheduler.schedule()));
			this.plotScheduler.schedule();
		} catch {
			// No soil report: no plot.
		}
	}

	/** The versions of the files the plot check reads: a new check only when one changed. */
	private plotKey(): string | undefined {
		const version = (model: ITextModel | undefined) => model && !model.isDisposed() ? model.getAlternativeVersionId() : -1;
		return this.soil && this.planModel ? `${version(this.soil)}:${version(this.planModel)}:${version(this.objects)}` : undefined;
	}

	/**
	 * Asks the backend (saengine.gis.plot) for the plot, its buildable envelope and the members
	 * outside them; the plan draws them and lists the warnings. Saved files also report the
	 * warnings as the floor plan's checks (its part status).
	 */
	private async checkPlot(): Promise<void> {
		const key = this.plotKey();
		const soil = this.soil;
		const plan = this.planModel;
		if (!key || !soil || !plan || key === this.plotCheckKey || !CommandsRegistry.getCommand(SOIL_PLOT_CHECK_COMMAND)) {
			return;
		}
		this.plotCheckKey = key;
		const soilText = soil.getValue();
		let result: IPlotCheckResult | undefined;
		if (/"saengine\.soilReport\//.test(soilText)) {
			try {
				result = await this.commandService.executeCommand<IPlotCheckResult>(SOIL_PLOT_CHECK_COMMAND, {
					soilText,
					floorPlanText: plan.getValue(),
					objectsText: this.objects?.getValue(),
				} satisfies IPlotCheckRequest) ?? undefined;
			} catch {
				result = undefined;
			}
		}
		if (this.plotKey() !== key) {
			return; // changed meanwhile: the next check follows
		}
		this.plotCheck = result;
		this.renderScheduler.schedule();
		const resources = [plan.uri, soil.uri, ...(this.objects ? [this.objects.uri] : [])];
		if (result?.plot && !resources.some(r => this.textFileService.isDirty(r))) {
			const warnings = result.warnings ?? [];
			// Members, not warnings: a column outside on two sides is one member outside.
			const members = (kind: 'outside' | 'setback') => new Set(warnings.filter(w => w.kind === kind).map(w => `${w.group}:${w.id}`)).size;
			const outside = members('outside');
			const failed = new Set(warnings.map(w => `${w.group}:${w.id}`)).size;
			void this.partStatusService.reportChecks('floorPlan', {
				problems: 0,
				failed,
				failedText: outside ? localize('floorPlan.outsidePlot', "{0} outside the plot", outside) : localize('floorPlan.inSetbacks', "{0} in setbacks", members('setback')),
				items: warnings.map(w => ({ severity: 'warning' as const, message: w.message, where: w.id })),
			}, ['floorPlan', 'soil', 'objects']);
		}
	}

	/** The plot warnings for the plan of `story`: its members, and the columns and walls rising through it. */
	private plotWarnings(layout: unknown, story: string): IPlotWarning[] {
		const levels = new Map(storiesOf(layout).map(s => [s.id, s.elevation]));
		const level = levels.get(story);
		const model = isObject(layout) ? layout : {};
		const spans = (group: string, id: string) => {
			const list = Array.isArray(model[`${group}s`]) ? model[`${group}s`] as unknown[] : [];
			const member = list.find(m => isObject(m) && m.id === id);
			const base = isObject(member) ? levels.get(member.base as string) : undefined;
			const top = isObject(member) ? levels.get(member.top as string) : undefined;
			return level !== undefined && base !== undefined && top !== undefined && base < level && level <= top;
		};
		return (this.plotCheck?.warnings ?? []).filter(w => w.story === story || (w.group === 'column' || w.group === 'wall') && spans(w.group, w.id));
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
		if (!this.userView) {
			this.fitScheduler.schedule(); // the whole plan, bubbles too, at the new size
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
		this.planModel = this.objects = this.materials = this.bim = this.settings = this.soil = undefined;
		this.plotScheduler.cancel();
		this.plotCheck = undefined;
		this.plotCheckKey = undefined;
		this.pendingWrite = undefined;
		this.undoLabels.clear();
		this.redoLabels.clear();
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
	/**
	 * Integrator glue: runs one of the selection and bulk actions of the toolbar's menu for the
	 * command palette (saengineCad.contribution.ts); false when it is not available now.
	 */
	async runBulkAction(id: 'selectAll' | 'selectByType' | 'copyToStories' | 'mirror' | 'deleteSelection'): Promise<boolean> {
		const action = {
			selectAll: this.selectAllAction,
			selectByType: this.selectTypeAction,
			copyToStories: this.copyStoriesAction,
			mirror: this.mirrorAction,
			deleteSelection: this.deleteSelectionAction,
		}[id];
		if (!action.enabled || this.layoutState !== 'ok') {
			return false;
		}
		if (id === 'selectAll') {
			this.setTool('select');
		}
		await action.run();
		return true;
	}

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

	/**
	 * Undoes or redoes the last edit of the floor plan file and says which: one of this editor's
	 * (by its notice), else one made in Grids & Stories or the text (they share the file's history).
	 */
	private async undoRedo(redo: boolean): Promise<void> {
		const resource = this.resource;
		const model = this.planModel;
		if (!resource || !model) {
			return;
		}
		const version = model.getAlternativeVersionId();
		const label = (redo ? this.redoLabels : this.undoLabels).get(version);
		await (redo ? this.undoRedoService.redo(resource) : this.undoRedoService.undo(resource));
		if (model.isDisposed()) {
			return;
		}
		const changed = model.getAlternativeVersionId() !== version;
		this.setNotice(!changed ? (redo ? localize('floorPlan.nothingToRedo', "Nothing to redo.") : localize('floorPlan.nothingToUndo', "Nothing to undo."))
			: label ? (redo ? localize('floorPlan.redid', "Redid: {0}", label) : localize('floorPlan.undid', "Undid: {0}", label))
				: redo ? localize('floorPlan.redidOther', "Redid an edit of the grids, stories or file text (made outside the plan).")
					: localize('floorPlan.undidOther', "Undid an edit of the grids, stories or file text (made outside the plan)."));
		this.updateToolbar();
	}

	private onKey(e: KeyboardEvent): void {
		const ctrl = e.ctrlKey || e.metaKey;
		if (e.key === 'Escape' && (this.tool !== 'select' || this.chainStart || this.picked || this.polygon.length || this.pasting || this.drag || this.selected.length)) {
			e.preventDefault();
			e.stopPropagation();
			this.cancel();
		} else if (e.key === 'Enter' && this.tool === 'polygonSlab' && this.polygon.length) {
			e.preventDefault();
			this.finishPolygon();
		} else if (isEditableElement(e.target as HTMLElement)) {
			return; // typing in a field, the command line or a picker
		} else if (this.lengthBox && this.chainStart && !ctrl && !e.altKey && /^[\d.@-]$/.test(e.key)) {
			// Direct distance entry: the first key starts the typed length.
			e.preventDefault();
			this.lengthBox.value = e.key;
			this.lengthBox.focus();
		} else if (e.key === ':') {
			e.preventDefault();
			this.toggleCommandLine();
		} else if (e.key === 'Delete' && this.tool === 'select' && this.selected.length) {
			e.preventDefault();
			this.runCommand({ kind: 'delete' });
		} else if (ctrl && !e.altKey && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) {
			// The plan's own undo, so it can say what it undid.
			e.preventDefault();
			e.stopPropagation();
			void this.undoRedo(e.key.toLowerCase() === 'y' || e.shiftKey);
		} else if (ctrl && !e.altKey && ['a', 'c', 'v'].includes(e.key.toLowerCase()) && this.layoutState === 'ok') {
			e.preventDefault();
			e.stopPropagation();
			const key = e.key.toLowerCase();
			if (key === 'a') {
				this.setTool('select');
				this.select(selectAll(this.plan?.members ?? []));
			} else if (key === 'c') {
				this.copySelection();
			} else {
				this.startPaste();
			}
		}
	}

	/** Enter on the CAD command line: the floor plan's commands run here, the rest in the CAD editor. */
	private onCommandLineKey(e: KeyboardEvent): void {
		const target = e.target;
		if (e.key !== 'Enter' || !isHTMLInputElement(target) || !target.classList.contains('ml-cli-text') || !this.host.contains(target)) {
			return;
		}
		const command = parseCommand(target.value, parse(this.planModel));
		if (!command) {
			return;
		}
		e.preventDefault();
		e.stopImmediatePropagation();
		target.value = '';
		if (command.kind === 'error') {
			this.setNotice(command.message);
		} else if (command.kind === 'help') {
			this.notificationService.info(localize('floorPlan.commandHelp', "Floor plan commands (type them after ':'):\n{0}\nOther words go to the CAD drawing's own commands.", COMMAND_HELP.map(c => `${c.usage}: ${c.description}`).join('\n')));
		} else if (command.kind === 'undo') {
			// The plan's undo, not the CAD drawing's own (which has nothing of the plan's).
			void this.undoRedo(command.redo);
		} else if (this.layoutState === 'ok') {
			this.runCommand(command);
		}
	}

	/** Suggestions for the CAD command line: the floor plan's commands, as the user types. */
	private suggestCommands(e: FocusEvent): void {
		const target = e.target;
		if (!isHTMLInputElement(target) || !target.classList.contains('ml-cli-text') || target.getAttribute('list')) {
			return;
		}
		const list = append(this.frame.element, $('datalist'));
		list.id = `saengine-floor-plan-commands-${FloorPlanEditor.datalists++}`;
		for (const command of COMMAND_HELP) {
			const option = append(list, $<HTMLOptionElement>('option'));
			option.value = command.usage.split(' ')[0];
			option.label = `${command.usage}: ${command.description}`;
		}
		target.setAttribute('list', list.id);
		target.placeholder = localize('floorPlan.commandPlaceholder', "Command (help lists the floor plan's)");
	}

	// ───────────────────────────── tools ─────────────────────────────

	/** Drops a half-done gesture: a beam's first point, a picked member, a polygon's corners. */
	private resetGesture(): void {
		this.chainStart = undefined;
		this.picked = undefined;
		this.polygon = [];
		this.drag = undefined;
		this.pasting = false;
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
		if (this.tool === 'select' && !this.pasting && !this.drag && this.selected.length) {
			this.select([]);
			this.notice = undefined;
			this.updateStatus();
		} else if (this.chainStart || this.picked || this.polygon.length || this.pasting || this.drag) {
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
			case 'fill': return FILL_TOOL[FILL_CHOICES[this.fillChoice].kind];
			default: return this.tool;
		}
	}

	/**
	 * Makes a concrete object type of a typed size for `kind` in `objects.json` (one undoable edit
	 * there) and chooses it for its tool; its id, or undefined when cancelled.
	 */
	private async createType(kind: NewTypeKind): Promise<string | undefined> {
		const prompt = NEW_TYPE_PROMPTS[kind];
		const text = await this.quickInputService.input({
			title: localize('floorPlan.newTypeTitle', "New {0} Type", TOOLS.find(t => t.tool === kind)?.label ?? kind),
			prompt: localize('floorPlan.newTypePrompt', "{0}. It is made of the project's concrete, without reinforcement; give it bars in 04 Objects.", prompt.prompt),
			value: prompt.value,
			validateInput: async value => validateSize(kind, value),
		});
		const model = this.objects;
		if (text === undefined || !model || model.isDisposed()) {
			this.updateToolbar();
			return undefined;
		}
		const result = addObjectType(parse(model), parse(this.materials), kind, text);
		if (!result.ok) {
			this.setNotice(result.error);
			this.updateToolbar();
			return undefined;
		}
		if (!result.existed) {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: JSON.stringify(result.objects, undefined, '\t') + '\n' }], () => null);
			model.pushStackElement();
		}
		this.types.set(kind, result.id);
		this.updateToolbar();
		this.setNotice(result.existed
			? localize('floorPlan.typeExists', "{0} was there already; it is chosen now.", result.id)
			: localize('floorPlan.typeMade', "Made object type {0} (in 04 Objects, unsaved until you save it); it is chosen now.", result.id));
		return result.id;
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
			...tools(['column', 'beam', 'wall', 'slab', 'polygonSlab', 'fill']), this.foundationsAction,
			new Separator(),
			this.typicalAction,
			new Separator(),
			...(this.narrow ? [] : [...tools(['move', 'rotate', 'delete']), new Separator()]),
			...(this.compact ? [] : [this.undoAction, this.redoAction, new Separator()]),
			this.zoomAction, ...(this.compact ? [] : [this.underlayAction, this.commandLineAction]), frame.togglePropertiesAction,
		];
		const secondary: IAction[] = [
			...(state === 'placeholder' ? [this.createAction, new Separator()] : []),
			this.selectAllAction,
			this.selectTypeAction,
			this.copyStoriesAction,
			this.mirrorAction,
			this.deleteSelectionAction,
			this.membersTableAction,
			new Separator(),
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

		this.fillGroup.classList.toggle('hidden', this.tool !== 'fill');
		const hasSelection = editable && this.selected.length > 0;
		this.copyStoriesAction.enabled = hasSelection;
		this.mirrorAction.enabled = hasSelection;
		this.deleteSelectionAction.enabled = hasSelection;
		this.selectAllAction.enabled = this.selectTypeAction.enabled = !!this.plan?.members.length;

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
			const options = [...types.map(([, name]) => ({ text: name })), ...(tool !== 'footing' ? [{ text: localize('floorPlan.newType', "New type...") }] : [])];
			this.typePicker.setOptions(options.length ? options : [{ text: localize('floorPlan.noTypes', "(none defined)") }], Math.max(0, this.typeIds.indexOf(chosen ?? '')));
		}
		this.updateTypedControls();
	}

	/** Exact entry for the picked member in the toolbar: a displacement for Move, an angle for Rotate. */
	private updateTypedControls(): void {
		const picked = this.picked;
		const tool = this.tool;
		const length = (tool === 'beam' || tool === 'wall') && !!this.chainStart;
		const key = length ? `length|${tool}` : picked && (tool === 'move' || tool === 'rotate') ? `${tool}|${picked.group}|${picked.id}` : '';
		if (key === this.typedKey) {
			return;
		}
		this.typedKey = key;
		this.typedControls.clear();
		this.lengthBox = undefined;
		clearNode(this.typedGroup);
		this.typedGroup.classList.toggle('hidden', !key);
		if (length) {
			this.renderLengthEntry();
			return;
		}
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

	/**
	 * The typed end of a beam or wall (AutoCAD's direct distance entry): a length in mm toward the
	 * cursor, or Δx, Δy from the start. Typing a digit on the plan starts it.
	 */
	private renderLengthEntry(): void {
		const box = this.lengthBox = this.typedControls.add(new InputBox(append(this.typedGroup, $('.floor-plan-typed')), this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			placeholder: localize('floorPlan.lengthHint', "Length in mm, or Δx, Δy"),
			ariaLabel: localize('floorPlan.lengthAria', "Length of the {0} from its start in millimetres, or the offset of its end", this.tool),
		}));
		const apply = () => {
			const start = this.chainStart;
			const end = start && typedEnd(start.point, box.value, this.hoverSnap?.point ?? this.hover);
			if (!start || !end) {
				this.setNotice(localize('floorPlan.badLength', "Type a length in mm (along the cursor's direction, held to an axis within 5°) or Δx, Δy, e.g. 1500 or 1500, 0."));
				return;
			}
			box.value = '';
			// On a member within 1 mm (a typed span onto a beam): stored exactly, so the two join.
			const onMember = snapLinear(parse(this.planModel), this.story ?? '', end, 1, start.point);
			this.placeEnd(onMember.exact ? onMember : { kind: 'free', point: end, exact: false });
			this.lengthBox?.focus();
		};
		this.typedControls.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				apply();
			}
		}));
		this.typedControls.add(this.frame.createIconButton(this.typedGroup, Codicon.check, localize('floorPlan.applyLength', "Place the End"), apply));
	}

	// ───────────────────────────── mouse ─────────────────────────────

	/** Whether a left drag on the canvas draws a window (Select and Fill) rather than going to the CAD editor. */
	private get windowTool(): boolean {
		return (this.tool === 'select' || this.tool === 'fill') && !this.pasting;
	}

	private registerMouse(): void {
		let down: { x: number; y: number } | undefined;
		const onCanvas = (e: MouseEvent) => isHTMLElement(e.target) && e.target.tagName === 'CANVAS';
		this._register(addDisposableListener(this.host, EventType.WHEEL, () => this.userView = true, { passive: true }));
		this._register(addDisposableListener(this.host, EventType.POINTER_DOWN, e => {
			if (e.button === 1) {
				this.userView = true; // a middle-button pan
			}
			down = e.button === 0 ? { x: e.clientX, y: e.clientY } : undefined;
			if (down && this.editor && this.windowTool && onCanvas(e)) {
				// The window is ours: the CAD editor's own box selection has nothing to select here.
				e.stopPropagation();
				this.drag = { start: this.editor.toWorld(e.clientX, e.clientY), client: down };
			}
		}, true));
		this._register(addDisposableListener(this.host, EventType.MOUSE_DOWN, e => {
			if (e.button === 0 && this.windowTool && onCanvas(e)) {
				e.stopPropagation();
			}
		}, true));
		this._register(addDisposableListener(this.host, EventType.POINTER_UP, e => {
			const start = down;
			const drag = this.drag;
			down = undefined;
			this.drag = undefined;
			if (e.button !== 0 || !start || !this.editor) {
				return;
			}
			const point = this.editor.toWorld(e.clientX, e.clientY);
			if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < CLICK_PIXELS) {
				this.click(point, e);
			} else if (drag) {
				this.finishWindow(drag.start, point, e);
			}
		}, true));
		this._register(addDisposableListener(this.host, EventType.POINTER_MOVE, e => {
			if (this.editor) {
				this.hover = this.editor.toWorld(e.clientX, e.clientY);
				if (this.drag && (e.buttons & 1) && Math.hypot(e.clientX - this.drag.client.x, e.clientY - this.drag.client.y) >= CLICK_PIXELS) {
					this.drag.current = this.hover;
				}
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
			} else if (this.chainStart || this.picked || this.polygon.length || this.pasting) {
				e.preventDefault();
				this.cancel();
			} else if (this.editor && this.layoutState === 'ok') {
				const shape = this.pick(this.editor.toWorld(e.clientX, e.clientY));
				if (shape) {
					e.preventDefault();
					e.stopPropagation();
					this.showMemberMenu(shape, e);
				}
			}
		}, true));
	}

	/** The right-click menu of a member: the properties panel's actions for it (and the selection it is in). */
	private showMemberMenu(shape: IMemberShape, e: MouseEvent): void {
		const ref = { group: shape.group, id: shape.id };
		if (!this.selected.some(r => sameMember(r, ref))) {
			this.setTool('select');
			this.select([ref]);
		}
		const many = this.selected.length > 1;
		const layout = parse(this.planModel);
		const member = isObject(layout) && Array.isArray(layout[shape.group]) ? (layout[shape.group] as unknown[]).filter(isObject).find(m => m.id === shape.id) : undefined;
		const type = typeof member?.type === 'string' ? member.type : undefined;
		const root = this.resource && dirname(dirname(this.resource));
		const action = (id: string, label: string, run: () => unknown, enabled = true) => new Action(`saengine.floorPlan.menu.${id}`, label, undefined, enabled, async () => { run(); });
		const showPanel = () => {
			this.frame.setPropertiesVisible(true);
			this.renderProperties();
		};
		const actions: IAction[] = shape.group === 'footings' ? [
			action('substructure', localize('floorPlan.editInSubstructure', "Edit in 9 Substructure"), () => this.openPart('substructure')),
		] : [
			action('properties', localize('menu.properties', "Properties"), showPanel),
			new Separator(),
			action('move', localize('menu.move', "Move {0}", shape.id), () => {
				this.setTool('move');
				this.picked = shape;
				this.setNotice(localize('floorPlan.moveTarget2', "Click where {0} goes, or type the displacement.", shape.id));
				this.updateToolbar();
				this.schedulePreview();
			}, !many),
			...(shape.group === 'columns' ? [action('rotate', localize('menu.rotate', "Rotate {0}...", shape.id), () => {
				this.setTool('rotate');
				this.picked = shape;
				this.updateToolbar();
				this.renderProperties();
			}, !many)] : []),
			action('copyStories', localize('menu.copyToStories', "Copy to Stories..."), () => void this.pickCopyToStories()),
			action('mirror', localize('menu.mirror', "Mirror..."), () => void this.pickMirror()),
			new Separator(),
			...(this.selected.some(r => r.group === 'beams') ? [action('lineLoad', localize('menu.lineLoad', "Line Load..."), () => {
				this.loadsPanel.openLineLoad(this.selected);
				showPanel();
			})] : []),
			...(!many && (shape.group === 'beams' || shape.group === 'columns') ? [action('pointLoad', localize('menu.pointLoad', "Point Load..."), () => {
				this.loadsPanel.openPointLoad(this.selected);
				showPanel();
			})] : []),
			new Separator(),
			...(type ? [
				action('selectType', localize('menu.selectType', "Select All {0} on Story", type), () => this.runCommand({ kind: 'select', what: 'type', type })),
				action('editType', localize('menu.editType', "Edit Object Type {0}", type), () => void (root && openOwner({ kind: 'objectType', id: type }, 'objects', root, this.editorService))),
			] : []),
			new Separator(),
			action('delete', many ? localize('menu.deleteMany', "Delete {0} Members", this.selected.length) : localize('menu.delete', "Delete {0}", shape.id), () => this.runCommand({ kind: 'delete' })),
		];
		this.contextMenuService.showContextMenu({
			getAnchor: () => ({ x: e.clientX, y: e.clientY }),
			getActions: () => actions,
		});
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

	/**
	 * The member under `point` that the edit tools (move, rotate, delete) may change: footings are
	 * shown on the plan but owned by 9 Substructure, so picking one says so (`notify`) and gives none.
	 */
	private pickEditable(point: CadPoint, notify = true): IMemberShape | undefined {
		const shape = this.pick(point);
		if (shape?.group !== 'footings') {
			return shape;
		}
		if (notify) {
			this.setNotice(footingsOwnedMessage());
		}
		return undefined;
	}

	/** The selection the bulk edits change: footings are left out (9 Substructure owns them). */
	private get editableSelection(): IMemberRef[] {
		return this.selected.filter(r => r.group !== 'footings');
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

	// ───────────────────────────── selection and bulk edits ─────────────────────────────

	/** Selects `refs` on the plan; the selection service gets the one picked last. */
	private select(refs: readonly IMemberRef[]): void {
		this.selected = [...refs];
		const last = refs[refs.length - 1];
		this.selectionService.setSelection(last ? { kind: 'member', group: last.group, id: last.id } : undefined, SELECTION_SOURCE);
		this.updateToolbar();
		this.updateStatus();
		this.schedulePreview();
		this.renderProperties();
	}

	/** A window dragged from `start` to `end`: selects (Select) or fills (Fill). */
	private finishWindow(start: CadPoint, end: CadPoint, modifiers: { readonly ctrlKey: boolean; readonly metaKey: boolean; readonly shiftKey: boolean }): void {
		if (this.tool === 'fill') {
			const choice = FILL_CHOICES[this.fillChoice];
			this.runFill(choice.kind, choice.direction, rectOf(start, end));
			return;
		}
		const refs = selectInWindow(this.plan?.members ?? [], start, end);
		this.select(combine(this.selected, refs, modifiers.ctrlKey || modifiers.metaKey || modifiers.shiftKey ? 'add' : 'replace'));
		this.setNotice(windowMode(start, end) === 'window'
			? localize('floorPlan.windowSelected', "Window: {0} member(s) fully inside.", refs.length)
			: localize('floorPlan.crossingSelected', "Crossing window: {0} member(s) touched.", refs.length));
	}

	private get story(): string | undefined {
		return (this.input as FloorPlanEditorInput | undefined)?.story;
	}

	/** Fills the current story inside `rect` (all of it when left out) with the chosen object type. */
	private runFill(kind: FillKind, direction: FillDirection, rect?: IRect): void {
		const story = this.story;
		const tool = FILL_TOOL[kind];
		const type = this.types.get(tool) ?? this.typesOfKinds(TOOL_KINDS[tool])[0]?.[0] ?? '';
		if (story) {
			this.applyBulk(fill(parse(this.planModel), kind, type, story, rect, direction), 'placed', true);
		}
	}

	/**
	 * Writes a bulk edit of the current story (repeated on its typical floor) as one undoable
	 * edit and says what it did; the new members become the selection with `selectResult`.
	 */
	private applyBulk(result: BulkResult, verb: BulkVerb | undefined, selectResult = false, notice?: string): void {
		if (!result.ok) {
			this.setNotice(result.error);
			return;
		}
		if (!this.writeEdit(result.layout, this.story)) {
			return;
		}
		const shapes = this.plan?.members ?? [];
		this.select(selectResult ? prune(result.ids, shapes) : prune(this.selected, shapes));
		this.setNotice(notice ?? (verb ? bulkNotice(result, verb) : ''));
	}

	/** Runs a floor plan command (from the command line, the keyboard, the menu or the properties panel) on the selection. */
	private runCommand(command: Exclude<FloorPlanCommand, { readonly kind: 'error' }>): void {
		const layout = parse(this.planModel);
		const refs = command.kind === 'select' ? this.selected : this.editableSelection;
		if (!refs.length && this.selected.length && command.kind !== 'select' && command.kind !== 'fill') {
			this.setNotice(footingsOwnedMessage()); // only footings are selected
			return;
		}
		const shapes = this.plan?.members ?? [];
		switch (command.kind) {
			case 'select': {
				const chosen = command.what === 'all' ? selectAll(shapes)
					: command.what === 'none' ? []
						: command.what === 'type' ? selectByType(layout, shapes, command.type)
							: selectAll(shapes).filter(r => command.ids.includes(r.id.toUpperCase()));
				this.notice = chosen.length || command.what === 'none' ? undefined : localize('floorPlan.noneMatched', "No member on this story matches.");
				this.select(chosen); // the status line shows what is selected
				break;
			}
			case 'fill':
				this.runFill(command.fill, command.direction, command.rect);
				break;
			case 'copy':
			case 'array':
				this.applyBulk(copyMembers(layout, refs, command.delta, command.times), 'copied');
				break;
			case 'move':
				this.applyBulk(moveMembers(layout, refs, command.delta), 'moved');
				break;
			case 'mirror':
				this.applyBulk(mirrorMembers(layout, refs, command.axis, command.label, command.keep), 'mirrored');
				break;
			case 'rotate':
				this.applyBulk(rotateMembers(layout, refs, command.degrees, command.absolute), 'rotated');
				break;
			case 'tostories':
				if (command.stories) {
					this.copyTo(command.stories);
				} else {
					void this.pickCopyToStories();
				}
				break;
			case 'delete':
				this.applyBulk(deleteMembers(layout, refs), undefined, false, localize('floorPlan.deletedMany', "Deleted {0} member(s).", refs.length));
				break;
		}
	}

	/** Copies the selection to `stories` (and their typical floors). */
	private copyTo(stories: readonly string[]): void {
		const story = this.story;
		if (!story) {
			return;
		}
		const layout = parse(this.planModel);
		const result = copyToStories(layout, this.editableSelection, story, stories);
		const names = storiesOf(layout).filter(s => stories.includes(s.id)).map(s => s.name);
		this.applyBulk(result, 'copied', false, result.ok ? localize('floorPlan.copiedToStories', "Copied {0} member(s) to {1} (and their typical floors); skipped {2} already there.", result.placed, names.join(', '), result.skipped) : undefined);
	}

	/** Asks for the stories to copy the selection to. */
	private async pickCopyToStories(): Promise<void> {
		const story = this.story;
		const layout = parse(this.planModel);
		if (!story || !this.selected.length) {
			this.setNotice(localize('bulk.nothing', "Select members first."));
			return;
		}
		const own = new Set(familyOf(layout, story));
		type Item = IQuickPickItem & { readonly story: string };
		const items: Item[] = storiesOf(layout).slice(1).filter(s => !own.has(s.id)).map(s => {
			const family = familyOf(layout, s.id).length;
			return {
				story: s.id,
				label: s.name,
				description: `${s.elevation >= 0 ? '+' : ''}${s.elevation}${this.familyLabel(layout, s.id)}`,
				detail: family > 1 ? localize('floorPlan.copyFamily', "Typical floor: the copies go to all its {0} stories", family) : undefined,
			};
		});
		const picked = await this.quickInputService.pick(items, {
			title: localize('floorPlan.copyToStoriesTitle', "Copy to Stories: {0}", selectionSummary(this.selected)),
			placeHolder: localize('floorPlan.copyToStoriesHint', "Stories to copy the selection to (columns and walls rise from the story below each)"),
			canPickMany: true,
		});
		if (picked?.length) {
			this.copyTo(picked.map(p => p.story));
		}
	}

	/** Asks for the grid line to mirror the selection about. */
	private async pickMirror(): Promise<void> {
		if (!this.selected.length) {
			this.setNotice(localize('bulk.nothing', "Select members first."));
			return;
		}
		const grids = gridsOf(parse(this.planModel));
		type Item = IQuickPickItem & { readonly axis: 'x' | 'y'; readonly line: string };
		const items: Item[] = (['x', 'y'] as const).flatMap(axis => [...grids[axis]].sort((a, b) => a[1] - b[1]).map(([line, position]) => ({
			axis,
			line,
			label: localize('floorPlan.gridLine', "Grid Line {0}", line),
			description: axis === 'x' ? localize('floorPlan.atX', "x = {0} mm", position) : localize('floorPlan.atY', "y = {0} mm", position),
		})));
		const picked = await this.quickInputService.pick(items, {
			title: localize('floorPlan.mirrorTitle', "Mirror: {0}", selectionSummary(this.selected)),
			placeHolder: localize('floorPlan.mirrorHint', "The grid line to mirror about; the originals stay (type mirror <line> move on the command line to move them)"),
		});
		if (picked) {
			this.runCommand({ kind: 'mirror', axis: picked.axis, label: picked.line, keep: true });
		}
	}

	/** Asks for an object type on the story and selects its members. */
	private async pickSelectByType(): Promise<void> {
		const layout = parse(this.planModel);
		type Item = IQuickPickItem & { readonly objectType: string };
		const names = new Map(this.typesOfKinds(['column', 'beam', 'wall', 'slab', 'footing', 'pileCap']));
		const items: Item[] = typesOnPlan(layout, this.plan?.members ?? []).map(t => ({ objectType: t.type, label: names.get(t.type) ?? t.type, description: localize('floorPlan.typeCount', "{0} on this story", t.count) }));
		const picked = await this.quickInputService.pick(items, {
			title: localize('floorPlan.selectByTypeTitle', "Select by Type"),
			placeHolder: localize('floorPlan.selectByTypeHint', "Select every member of this object type on the story"),
		});
		if (picked) {
			this.runCommand({ kind: 'select', what: 'type', type: picked.objectType });
		}
	}

	/** Ctrl+C: keeps the selection for Ctrl+V, with its lower left corner as the base point. */
	private copySelection(): void {
		const data = copyToClipboard(parse(this.planModel), this.editableSelection);
		if (!data) {
			this.setNotice(localize('bulk.nothing', "Select members first."));
			return;
		}
		this.clipboard = { data, shapes: (this.plan?.members ?? []).filter(s => this.selected.some(r => sameMember(r, s))) };
		this.setNotice(localize('floorPlan.copiedClipboard', "Copied {0}. Ctrl+V pastes them at a base point (their lower left corner), on this story or another.", selectionSummary(this.selected)));
	}

	/** Ctrl+V: the next click places the copied members' base point. */
	private startPaste(): void {
		if (!this.clipboard) {
			this.setNotice(localize('floorPlan.nothingCopied', "Copy members with Ctrl+C first."));
			return;
		}
		this.setTool('select');
		this.pasting = true;
		this.setNotice(localize('floorPlan.pasteWhere', "Click where the base point (lower left corner of the copied members) goes; Esc cancels."));
		this.schedulePreview();
	}

	private pasteAt(point: CadPoint): void {
		const story = this.story;
		const clipboard = this.clipboard;
		this.pasting = false;
		if (story && clipboard && this.layoutState === 'ok') {
			this.applyBulk(paste(parse(this.planModel), clipboard.data, story, point), 'placed', true);
		}
		this.schedulePreview();
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

	private click(point: CadPoint, modifiers?: { readonly ctrlKey: boolean; readonly metaKey: boolean; readonly shiftKey: boolean }): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		const layout = parse(this.planModel);
		const story = input?.story;
		if (this.pasting) {
			this.pasteAt(this.snapFree(point));
			return;
		}
		if (this.tool === 'select') {
			// Selecting shows the members (properties panel, Model Explorer); it never changes them.
			const shape = this.pick(point);
			const mode = modifiers?.ctrlKey || modifiers?.metaKey ? 'toggle' : modifiers?.shiftKey ? 'add' : 'replace';
			this.select(combine(this.selected, shape ? [{ group: shape.group, id: shape.id }] : [], mode));
			return;
		}
		if (!story || !isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID) {
			return;
		}
		if (this.tool === 'fill') {
			this.setNotice(localize('floorPlan.fillDrag', "Drag a window over the grid to fill it; type fill columns, beams, slabs or walls on the command line (:) to fill the whole story."));
			return;
		}
		if (this.tool === 'delete') {
			const shape = this.pickEditable(point);
			if (shape) {
				this.deleteMember(shape.group, shape.id);
			}
			return;
		}
		if (this.tool === 'move') {
			if (this.picked) {
				this.moveTo(this.snapFree(point));
			} else {
				this.picked = this.pickEditable(point, false);
				this.setNotice(this.picked
					? localize('floorPlan.moveTarget', "Click where {0} goes (its {1} is the base point), or type the displacement.", this.picked.id, this.picked.group === 'columns' ? localize('base.location', "location") : this.picked.group === 'slabs' ? localize('base.corner', "first corner") : localize('base.start', "start"))
					: this.pick(point)?.group === 'footings' ? footingsOwnedMessage() : localize('floorPlan.pickMember', "Click a member on this story."));
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
			} else if (shape?.group === 'footings') {
				this.picked = undefined;
				this.setNotice(footingsOwnedMessage());
			} else if (shape && shape.group !== 'columns') {
				this.picked = undefined;
				this.setNotice(notRotatableMessage());
			} else {
				this.picked = shape;
				this.setNotice(shape
					? localize('floorPlan.rotateHow', "Type the angle of {0}, or click it again to turn it 90°.", shape.id)
					: localize('floorPlan.pickRotatable', "Click a column on this story."));
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
		} else if (tool === 'beam' || tool === 'wall') {
			this.placeEnd(this.snapEnd(point));
			return;
		} else {
			const node = this.snap(point);
			if (!node) {
				this.setNotice(localize('floorPlan.needNode', "Click closer to a grid intersection."));
				return;
			}
			if (tool === 'column') {
				result = placeColumn(layout, type, story, node);
			} else {
				this.openPart('substructure'); // footings are placed in 9 Substructure
				return;
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

	/** Where a beam or wall end at `point` snaps (see {@link snapLinear}). */
	private snapEnd(point: CadPoint): ISnap {
		const tolerance = this.editor ? SNAP_PIXELS * this.editor.unitsPerPixel() : 0;
		return snapLinear(parse(this.planModel), this.story ?? '', point, tolerance, this.chainStart?.point);
	}

	/** The next point of the beam or wall chain: its start, else its end (which starts the next one). */
	private placeEnd(end: ISnap): void {
		const tool = this.tool;
		const story = this.story;
		const type = tool === 'beam' || tool === 'wall' ? this.types.get(tool) : undefined;
		if (!story || (tool !== 'beam' && tool !== 'wall')) {
			return;
		}
		if (!type) {
			this.setNotice(localize('floorPlan.needType', "Define a {0} type in Object Types first.", TOOLS.find(t => t.tool === tool)!.label.toLowerCase()));
			return;
		}
		const start = this.chainStart;
		if (!start) {
			this.chainStart = end;
			this.setNotice(localize('floorPlan.chainStarted', "Start: {0}. Click the end, or type its length in mm (or Δx, Δy) and press Enter.", this.snapLabel(end)));
			this.updateToolbar();
			this.schedulePreview();
			return;
		}
		const result = placeLinear(parse(this.planModel), tool, type, story, start, end);
		if (result.ok || Math.hypot(end.point[0] - start.point[0], end.point[1] - start.point[1]) >= 1) {
			this.chainStart = end; // keep chaining from the end point
		}
		if (result.ok) {
			if (this.writeEdit(result.layout, story)) {
				const kind = end.kind === 'free' || end.kind === 'gridLine' ? localize('floorPlan.freeEnd', " (a free end: a cantilever unless something is placed under it)") : '';
				this.setNotice(localize('floorPlan.placedTo', "Placed {0} to {1}{2}.", result.id, this.snapLabel(end), kind));
			}
		} else {
			this.setNotice(result.error);
		}
		this.updateToolbar();
		this.schedulePreview();
	}

	/** "Midpoint of B3", "Grid intersection", "Free point (1500, 0)". */
	private snapLabel(snap: ISnap): string {
		const name = SNAP_NAMES[snap.kind];
		return snap.on ? localize('floorPlan.snapOn', "{0} of {1}", name, snap.on) : snap.kind === 'free' || snap.kind === 'gridLine'
			? localize('floorPlan.snapAt', "{0} ({1}, {2})", name, Math.round(snap.point[0]), Math.round(snap.point[1])) : name;
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
		const family = story ? repeatFamily(parse(this.planModel), story) : [];
		if (!family) {
			this.setNotice(familyDiffersMessage());
			return false;
		}
		if (family.length > 1) {
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
		const before = model.getAlternativeVersionId();
		try {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: JSON.stringify(value, undefined, '\t') + '\n' }], () => null);
			model.pushStackElement();
		} finally {
			this.writing = false;
		}
		this.pendingWrite = { before, after: model.getAlternativeVersionId() };
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

		if (this.plotKey() !== this.plotCheckKey) {
			this.plotScheduler.schedule();
		}
		const plan = floorPlanDrawing(layout, parse(this.objects), input.story ?? '', this.plotCheck);
		const outside = this.plotWarnings(layout, input.story ?? '').map(w => w.message);
		this.plan = { ...plan, warnings: [...outside, ...plan.warnings, ...nearMisses(layout, input.story ?? '')] };
		this.selected = prune(this.selected, this.plan.members);
		const loads = loadsDrawing(this.loadsFile.read().loads, layout, input.story ?? '');
		this.editor.setGenerated(forCanvas({ layers: [...this.plan.drawing.layers, ...LOAD_LAYER_SPECS], entities: [...this.plan.drawing.entities, ...loads] }, this.lightCanvas));
		void this.syncUnderlay(layout, input);
		if (this.fitPending) {
			this.fitPending = false;
			this.editor.zoomExtents();
			this.fitScheduler.schedule(); // again once the canvas has its size
		}
		this.updateToolbar();
		this.updateStatus();
		this.renderProperties();
		this.schedulePreview();
		this.renderEmptyState(layout);
	}

	/**
	 * A plan without members: the steps to start one (grids and stories, object types, then the
	 * tools or Generate from Grid), each with its button, over the empty grid.
	 */
	private renderEmptyState(layout: unknown): void {
		const model = isObject(layout) ? layout : {};
		const count = (group: string) => Array.isArray(model[group]) ? (model[group] as unknown[]).length : 0;
		const empty = this.layoutState === 'ok' && !this.emptyDismissed && ['columns', 'beams', 'walls', 'slabs'].every(g => count(g) === 0);
		const grids = gridsOf(layout);
		const stories = storiesOf(layout).length;
		const kinds = (['column', 'beam', 'slab'] as const).map(kind => [kind, this.typesOfKinds([kind]).length] as const);
		const key = empty ? JSON.stringify([grids.x.size, grids.y.size, stories, kinds]) : '';
		if (key === this.emptyKey) {
			return;
		}
		this.emptyKey = key;
		this.emptyDisposables.clear();
		clearNode(this.emptyState);
		this.emptyState.classList.toggle('hidden', !empty);
		if (!empty) {
			return;
		}
		const card = this.emptyState;
		const head = append(card, $('.floor-plan-empty-head'));
		append(head, $('h3', undefined, localize('empty.title', "Start the floor plan")));
		this.emptyDisposables.add(this.frame.createIconButton(head, Codicon.close, localize('empty.close', "Close"), () => {
			this.emptyDismissed = true;
			this.renderEmptyState(parse(this.planModel));
		}));
		const steps = append(card, $('ol'));
		const step = (done: boolean, text: string, buttons: readonly [string, () => void][]) => {
			const item = append(steps, $('li'));
			item.classList.toggle('done', done);
			append(item, $('span', undefined, text));
			const links = append(item, $('.sa-props-links'));
			for (const [label, run] of buttons) {
				propertyLink(links, label, run, this.emptyDisposables);
			}
		};
		step(grids.x.size > 1 && grids.y.size > 1 && stories > 1,
			localize('empty.grids', "Grids and stories: {0} × {1} grid lines, {2} stories.", grids.x.size, grids.y.size, stories),
			[[localize('empty.editGrids', "Edit Grids and Stories"), () => this.openGrids()]]);
		const missing = kinds.filter(([, n]) => !n).map(([kind]) => kind);
		step(!missing.length,
			missing.length ? localize('empty.typesMissing', "Object types: none yet for {0}.", missing.join(', ')) : localize('empty.typesReady', "Object types: {0}.", kinds.map(([kind, n]) => `${n} ${kind}`).join(', ')),
			[...missing.map(kind => [localize('empty.newType', "New {0} Type...", kind), () => void this.createType(kind)] as [string, () => void]), [localize('floorPlan.openObjects', "Open Object Types"), () => this.openPart('objects')]]);
		step(false,
			localize('empty.place', "Members: Generate from Grid puts columns on every intersection, beams on every grid segment and slabs in every bay of this story; or draw them with Column, Beam, Wall, Slab and Polygon Slab in the toolbar."),
			[[localize('empty.generate', "Generate from Grid"), () => this.generateFromGrid()], [localize('empty.fill', "Fill a Window..."), () => this.setTool('fill')]]);
	}

	/** Columns, beams and slabs on the whole grid of this story, as one undoable edit. */
	private generateFromGrid(): void {
		const story = this.story;
		if (!story) {
			return;
		}
		let done: Extract<BulkResult, { ok: true }> | undefined;
		const ids: IMemberRef[] = [];
		for (const kind of ['columns', 'beams', 'slabs'] as const) {
			const tool = FILL_TOOL[kind];
			const type = this.types.get(tool) ?? this.typesOfKinds(TOOL_KINDS[tool])[0]?.[0];
			if (!type) {
				this.setNotice(localize('empty.needTypes', "Make a {0} type first (New {0} Type...).", tool));
				return;
			}
			const result = fill(done?.layout ?? parse(this.planModel), kind, type, story);
			if (!result.ok) {
				this.setNotice(result.error);
				return;
			}
			done = result;
			ids.push(...result.ids);
		}
		this.applyBulk({ ...done!, ids, placed: ids.length, skipped: 0 }, undefined, false,
			localize('empty.generated', "Generated {0} members on this story from the grid. Copy them up with Copy to Stories or Typical Floors.", ids.length));
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
		const marker = (p: CadPoint) => entities.push(squareMarker(p, MARKER_PIXELS * units, layer));
		const point = this.hover;
		this.hoverSnap = undefined;
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
					entities.push(...outlineEntities(shifted(picked, target[0] - base[0], target[1] - base[1]), layer));
					entities.push({ kind: 'line', layer, start: base, end: target });
					marker(target);
				} else {
					const shape = this.plan && pickMember(this.plan.members, point, PICK_PIXELS * units);
					if (shape && shape.group !== 'footings' && (this.tool === 'move' || shape.group === 'columns')) {
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
			} else if (this.tool === 'beam' || this.tool === 'wall') {
				// AutoCAD's object snap markers: where the end lands, before the click.
				const snap = this.hoverSnap = this.snapEnd(point);
				entities.push(...snapMarker(snap, MARKER_PIXELS * units, layer));
				if (this.chainStart) {
					entities.push({ kind: 'line', layer, start: this.chainStart.point, end: snap.point });
				}
			} else {
				const node = this.snap(point);
				if (node) {
					marker(node.point);
				}
			}
		}
		// The window being dragged: solid for a window (members inside), dashed for a crossing one.
		const drag = this.drag;
		if (drag?.current) {
			const crossing = this.tool === 'select' && windowMode(drag.start, drag.current) === 'crossing';
			const { min, max } = rectOf(drag.start, drag.current);
			entities.push({
				kind: 'polyline', layer: crossing ? PREVIEW_LAYERS[4].name : PREVIEW_LAYERS[3].name, closed: true,
				points: [[min[0], min[1]], [max[0], min[1]], [max[0], max[1]], [min[0], max[1]]],
				linetypeScale: crossing ? WINDOW_DASH_PIXELS * units : undefined,
			});
		}
		// Ctrl+V: the copied members where they would land.
		const clipboard = this.clipboard;
		if (this.pasting && clipboard && point) {
			const target = this.snapFree(point);
			const [dx, dy] = [target[0] - clipboard.data.base[0], target[1] - clipboard.data.base[1]];
			for (const shape of clipboard.shapes) {
				entities.push(...outlineEntities(shifted(shape, dx, dy), layer));
			}
			marker(target);
		}
		const selected = this.picked ? [this.picked] : (this.plan?.members ?? []).filter(m => this.selected.some(r => sameMember(r, m)));
		for (const shape of selected) {
			entities.push(...outlineEntities(shape, PREVIEW_LAYERS[2].name));
		}
		editor.setPreview(forCanvas({ layers: PREVIEW_LAYERS, entities }, this.lightCanvas));
	}

	// ───────────────────────────── status line ─────────────────────────────

	private setNotice(text: string): void {
		const write = this.pendingWrite;
		if (write && text && write.after === this.planModel?.getAlternativeVersionId()) {
			// The notice of an edit names it for Undo and Redo.
			this.pendingWrite = undefined;
			this.undoLabels.set(write.after, text.replace(/\.$/, ''));
			this.redoLabels.set(write.before, text.replace(/\.$/, ''));
		}
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
		const summary = selectionSummary(this.selected);
		if (summary) {
			parts.push(summary);
		}
		if (plan) {
			parts.push(localize('floorPlan.count', "{0} members on this story", plan.members.length));
		}
		const problems = (plan?.problems.length ?? 0) + (this.underlayProblem ? 1 : 0);
		if (problems) {
			parts.push(this.underlayProblem && !plan?.problems.length ? this.underlayProblem : localize('floorPlan.problems', "{0} member(s) could not be drawn", plan?.problems.length ?? 0));
		}
		const warnings = plan?.warnings.length ?? 0;
		if (warnings) {
			parts.push(warnings === 1 ? plan!.warnings[0] : localize('floorPlan.warnings', "{0} warnings on this story", warnings));
		}
		const snap = this.hoverSnap;
		if (snap && (this.tool === 'beam' || this.tool === 'wall')) {
			const start = this.chainStart?.point;
			const [dx, dy] = start ? [snap.point[0] - start[0], snap.point[1] - start[1]] : [0, 0];
			parts.push(start && (dx || dy)
				? localize('floorPlan.snapLength', "{0}: {1} mm at {2}°", this.snapLabel(snap), Math.round(Math.hypot(dx, dy)), Math.round(Math.atan2(dy, dx) * 180 / Math.PI))
				: this.snapLabel(snap));
		} else if (this.hover) {
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
			severity: problems || differs || warnings ? 'warning' : undefined,
			link: differs && story ? { label: localize('floorPlan.copyTypical', "Copy the typical floor to them"), run: () => this.syncFamily(story) }
				: noTypes ? { label: localize('floorPlan.openObjects', "Open Object Types"), run: () => this.openPart('objects') }
				: problems || warnings ? { label: localize('floorPlan.showProblems', "Details"), run: () => this.frame.setPropertiesVisible(true) }
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
		if (!this.picked && this.selected.length > 1) {
			this.renderSelectionEdits(panel);
			this.renderLoads(panel);
			return;
		}
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
				appendPropertyRow(panel, localize('floorPlan.underlayFile', "File"), String(underlay.file));
				appendPropertyRow(panel, localize('floorPlan.underlayShown', "Shown"), underlay.visible === false ? localize('no', "No") : localize('yes', "Yes"));
			}
			appendPropertyNote(panel, localize('floorPlan.selectHint', "Select a member in the plan to see and change its properties."));
		}
		this.renderLoads(panel);
		const problems = [...(this.plan?.problems ?? []), ...(this.underlayProblem ? [this.underlayProblem] : [])];
		if (problems.length) {
			appendPropertyHeading(panel, localize('floorPlan.problemsHeading', "Problems"));
			for (const problem of problems) {
				appendPropertyNote(panel, problem);
			}
		}
		if (this.plan?.warnings.length) {
			appendPropertyHeading(panel, localize('floorPlan.warningsHeading', "Warnings"));
			for (const warning of this.plan.warnings) {
				appendPropertyNote(panel, warning);
			}
		}
		if (this.plotCheck?.plot) {
			appendPropertyHeading(panel, localize('floorPlan.plotHeading', "Plot"));
			appendPropertyNote(panel, this.plotCheck.envelope
				? localize('floorPlan.plotNote', "The plot (grey) and the buildable envelope inside its setbacks (dashed) come from the site in 01 Soil Report.")
				: localize('floorPlan.plotNoEnvelope', "The plot (grey) comes from the site in 01 Soil Report; its setbacks leave no buildable area."));
			propertyLink(append(panel, $('.sa-props-links')), localize('floorPlan.editPlot', "Edit the Plot in 01 Soil Report"), () => this.openPart('soil'), this.propertiesDisposables);
		}
	}

	/**
	 * The stiffness modifiers and design overwrites of the selected members (their own values over
	 * their object type's and the code's), each change one undoable edit of the floor plan.
	 */
	private renderModifierGroups(panel: HTMLElement, refs: readonly IModifierMemberRef[]): void {
		const layout = parse(this.planModel);
		const objects = parse(this.objects);
		const targets = memberTargets(layout, objects, parse(this.materials), refs);
		if (!targets.length) {
			return;
		}
		const code = readCodeStiffness(parse(this.settings), undefined);
		renderModifiers(panel, modifiersView('member', targets, code), this.propertiesDisposables, {
			contextViewService: this.contextViewService,
			editable: this.layoutState === 'ok',
			apply: (group, key, value) => {
				const result = setMembersField(parse(this.planModel), refs, objects, group, key, value);
				this.applyBulk(result, undefined, false, result.ok ? editNotice(group, key, result.ids.length) : undefined);
			},
			reset: group => {
				const result = resetMembersGroup(parse(this.planModel), refs, objects, group);
				this.applyBulk(result, undefined, false, result.ok ? editNotice(group, undefined, result.ids.length) : undefined);
			},
		});
	}

	/** Line Load... and Point Load... for the selection, and the Loads list. */
	private renderLoads(panel: HTMLElement): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		this.loadsPanel.render(panel, this.propertiesDisposables, {
			layout: parse(this.planModel),
			objects: parse(this.objects),
			story: input?.story,
			selected: this.picked ? [this.picked] : this.selected,
			editable: this.layoutState === 'ok',
			notify: text => this.setNotice(text),
			rerender: () => this.renderProperties(),
			reveal: (member, story) => {
				if (input && input.story !== story) {
					input.story = story;
					this.renderPlan();
				}
				this.select([member]);
			},
		});
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
		if (member.group === 'footings') {
			// Shown on the plan for reference; 9 Substructure places and edits them.
			appendPropertyNote(panel, footingsOwnedMessage());
			propertyLink(append(panel, $('.sa-props-links')), localize('floorPlan.editInSubstructure', "Edit in 9 Substructure"), () => this.openPart('substructure'), store);
			return;
		}
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
			appendPropertyRow(panel, localize('floorPlan.memberType', "Type"), cell).classList.add('editable');
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
			appendPropertyRow(panel, label, cell).classList.add('editable');
		};
		if (member.group === 'columns') {
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
		this.renderCopyInput(panel);
		appendPropertyNote(panel, localize('floorPlan.editNote', "Press Enter to apply. Each change is one undoable edit."));
		this.renderModifierGroups(panel, [{ group: member.group, id: member.id }]);
		const links = append(panel, $('.sa-props-links'));
		this.renderBulkLinks(links);
		propertyLink(links, localize('floorPlan.deleteMember', "Delete {0}", member.id), () => this.deleteMember(member.group, member.id), store);
	}

	/** A text box in the properties panel that runs `apply` on Enter. */
	private propertyInput(panel: HTMLElement, label: string, value: string, placeholder: string, apply: (text: string) => void): void {
		const store = this.propertiesDisposables;
		const cell = $('.floor-plan-prop-control');
		const box = store.add(new InputBox(cell, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, placeholder, ariaLabel: label }));
		box.value = value;
		store.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				apply(box.value);
			}
		}));
		appendPropertyRow(panel, label, cell).classList.add('editable');
	}

	/** "Copy by (mm)": dx, dy and how many copies (an array). */
	private renderCopyInput(panel: HTMLElement): void {
		this.propertyInput(panel, localize('floorPlan.copyBy', "Copy by (mm), times"), '', localize('floorPlan.copyHint', "Δx, Δy [, n], e.g. 6000, 0, 3"), text => {
			const match = /^\s*@?\s*(?<dx>[-+]?[\d.]+)\s*[,;\s]\s*(?<dy>[-+]?[\d.]+)(?:\s*[,;\s]\s*(?<n>\d+))?\s*$/.exec(text);
			if (match?.groups) {
				this.runCommand({ kind: 'copy', delta: [Number(match.groups.dx), Number(match.groups.dy)], times: match.groups.n ? Number(match.groups.n) : 1 });
			} else {
				this.setNotice(localize('floorPlan.badCopy', "Type the copy distance as two numbers in mm and, for an array, how many copies, e.g. 6000, 0, 3."));
			}
		});
	}

	/** Mirror and Copy to Stories links for the selection. */
	private renderBulkLinks(links: HTMLElement): void {
		const store = this.propertiesDisposables;
		propertyLink(links, localize('floorPlan.mirrorLink', "Mirror..."), () => void this.pickMirror(), store);
		propertyLink(links, localize('floorPlan.copyToStoriesLink', "Copy to Stories..."), () => void this.pickCopyToStories(), store);
	}

	/**
	 * The properties of a multi-selection: how many of each kind, the object type per kind (a
	 * change applies to all of that kind), the rotation of columns and footings, and the bulk edits.
	 */
	private renderSelectionEdits(panel: HTMLElement): void {
		const layout = parse(this.planModel);
		const refs = this.selected;
		const store = this.propertiesDisposables;
		const common = commonFields(layout, refs);
		appendPropertyHeading(panel, selectionSummary(refs));
		const editable = this.layoutState === 'ok';
		for (const [group, count] of countByGroup(refs)) {
			const tool = (Object.keys(TOOL_GROUP) as PlacementTool[]).find(t => TOOL_GROUP[t] === group);
			const types = tool ? this.typesOfKinds(TOOL_KINDS[tool]) : [];
			const current = common.types.get(group);
			const label = localize('floorPlan.groupType', "Type of {0}", GROUP_LABEL[group]);
			if (!editable || !types.length || group === 'footings') {
				appendPropertyRow(panel, label, current ?? localize('floorPlan.various', "(various)"));
				continue;
			}
			const options = [...(current ? [] : [{ text: localize('floorPlan.variousTypes', "(various: choose one for all {0})", count) }]), ...types.map(([, name]) => ({ text: name }))];
			const offset = current ? 0 : 1;
			const cell = $('.floor-plan-prop-control');
			const picker = store.add(new SelectBox(options, current ? Math.max(0, types.findIndex(([id]) => id === current)) : 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
			picker.render(cell);
			store.add(picker.onDidSelect(({ index }) => {
				const type = types[index - offset]?.[0];
				if (type && type !== current) {
					const result = setMembersType(parse(this.planModel), this.selected.filter(r => r.group === group), type);
					this.applyBulk(result.ok ? { ok: true, layout: result.layout, ids: result.changed, placed: 0, skipped: result.skipped.length } : result, undefined, false, localize('floorPlan.typesChanged', "{0} {1} are {2} now.", count, GROUP_LABEL[group], type));
				}
			}));
			appendPropertyRow(panel, label, cell).classList.add('editable');
		}
		if (!editable) {
			return;
		}
		if (common.rotatable) {
			this.propertyInput(panel, localize('floorPlan.rotation', "Rotation (°)"), common.rotation === undefined ? '' : String(common.rotation), localize('floorPlan.angleAll', "Angle in degrees, for all"), text => this.runCommand({ kind: 'rotate', degrees: Number(text), absolute: true }));
		}
		this.propertyInput(panel, localize('floorPlan.moveBy', "Move by (mm)"), '', localize('floorPlan.displacementHint', "Δx, Δy in mm, e.g. 150, 0"), text => {
			const delta = parseDisplacement(text);
			if (delta) {
				this.runCommand({ kind: 'move', delta });
			} else {
				this.setNotice(localize('floorPlan.badDisplacement', "Type the displacement as two numbers in mm, e.g. 150, -200."));
			}
		});
		this.renderCopyInput(panel);
		this.renderModifierGroups(panel, refs);
		appendPropertyNote(panel, localize('floorPlan.bulkNote', "Press Enter to apply; each change is one undoable edit of all {0} members. Moved members keep their nearest grid point plus an offset.", refs.length));
		const links = append(panel, $('.sa-props-links'));
		this.renderBulkLinks(links);
		propertyLink(links, localize('floorPlan.deleteSelected', "Delete {0} Members", refs.length), () => this.runCommand({ kind: 'delete' }), store);
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

	/** Picks a DXF or DWG and attaches it to the current story; files from elsewhere are copied into the project. */
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
			filters: [{ name: localize('floorPlan.cadFiles', "Drawings (DXF, DWG)"), extensions: ['dxf', 'dwg'] }],
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
				target = joinPath(underlays, basename(source).replace(/(\.d(?:xf|wg))$/i, ` (${n})$1`));
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
			let source = joinPath(dirname(input.resource), file);
			if (/\.dwg$/i.test(file)) {
				// A DWG is shown through its DXF copy, converted (and cached) by the backend.
				const answer = await this.commandService.executeCommand<{ ok?: boolean; dxf?: string; message?: string }>(DWG_TO_DXF_COMMAND, { path: source.fsPath });
				if (!answer?.ok || typeof answer.dxf !== 'string') {
					throw new Error(answer?.message ?? localize('floorPlan.dwgUnavailable', "DWG drawings cannot be converted here."));
				}
				source = URI.file(answer.dxf);
			}
			dxf = (await this.fileService.readFile(source)).value.toString();
		} catch (error) {
			if (this.editor !== editor || this.underlayKey !== key) {
				return;
			}
			this.underlayProblem = /\.dwg$/i.test(file) && error instanceof Error && error.message
				? localize('floorPlan.underlayDwgFailed', "The underlay {0} could not be read: {1}", file, error.message)
				: localize('floorPlan.underlayMissing', "The underlay {0} could not be read.", file);
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
		const files: URI[] = [];
		try {
			for (const story of stories) {
				// The standard layer colours, whatever the screen shows.
				editor.setGenerated(floorPlanDrawing(layout, objects, story.id).drawing);
				const name = `${story.id} ${story.name}`.replace(/[\\/:*?"<>|]/g, '-');
				const file = joinPath(folder, `${name}.dxf`);
				await this.fileService.writeFile(file, VSBuffer.fromString(editor.toDxf()));
				files.push(file);
			}
			const text = localize('floorPlan.exported', "Exported the plans of {0} stories to {1}/Floor Plan.", stories.length, exports.folder);
			this.setNotice(text);
			const current = files[Math.max(0, stories.findIndex(s => s.id === input.story))];
			this.notificationService.prompt(Severity.Info, text, [
				{ label: localize('floorPlan.revealExport', "Reveal in File Explorer"), run: () => void this.commandService.executeCommand('revealFileInOS', current ?? folder) },
				...(current ? [{ label: localize('floorPlan.openExport', "Open {0} in CAD", basename(current)), run: () => void this.commandService.executeCommand(OPEN_DXF_IN_CAD_UI_COMMAND, current) }] : []),
			]);
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
