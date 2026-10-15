/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi, CadEntitySpec, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { basename, dirname, joinPath, relativePath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { newFloorPlan } from '../../../services/saengineProject/common/partSources.js';
import { acquireCadEditor, releaseCadEditor } from './cadHost.js';
import { floorPlanDrawing, IFloorPlan, IMemberShape, storiesOf, storyOfSelection } from './floorPlanDrawing.js';
import { ISaengineModelSelectionService } from '../../../services/saengineProject/common/modelSelection.js';
import { basePoint, bayAt, EditResult, IGridNode, moveMember, pickMember, placeColumn, placeFooting, placeLinear, placePolygonSlab, placeSlab, PlacementTool, removeMember, rotateMember, snapPoint, snapToGrid, TOOL_KINDS } from './floorPlanEdits.js';
import { FloorPlanEditorInput, siblingPartFile } from './floorPlanEditorInput.js';

const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';

/** The grids and stories form for the same file (registered by the library editors). */
const GRIDS_EDITOR_ID = 'workbench.editor.saengine.grids';

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
	{ tool: 'footing', label: localize('tool.footing', "Footing"), icon: Codicon.symbolStructure, hint: localize('hint.footing', "Click a grid intersection to place a footing at this story.") },
	{ tool: 'move', label: localize('tool.move', "Move"), icon: Codicon.move, hint: localize('hint.move', "Click the member to move.") },
	{ tool: 'rotate', label: localize('tool.rotate', "Rotate"), icon: Codicon.refresh, hint: localize('hint.rotate', "Click a column or footing to rotate.") },
	{ tool: 'delete', label: localize('tool.delete', "Delete"), icon: Codicon.trash, hint: localize('hint.delete', "Click a member on this story to delete it.") },
];

const PREVIEW_LAYERS: readonly CadLayerSpec[] = [
	{ name: 'SAENGINE-PREVIEW', color: 2, description: 'Placement preview' },
	{ name: 'SAENGINE-PREVIEW-DELETE', color: 1, description: 'Member to delete' },
	{ name: 'SAENGINE-SELECTION', color: 4, description: 'Selected member' },
];

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
 * The floor plan (`floor-plan.json`) in the CAD editor, one story at a time. The floor plan owns
 * the building's layout: this editor places and deletes members as undoable edits of its text
 * model, which the Grids & Stories form edits too. Object types come from `objects.json`, read
 * only, so edits there show up as they are made.
 */
export class FloorPlanEditor extends EditorPane {

	static readonly ID = FloorPlanEditorInput.EDITOR_ID;

	private root!: HTMLElement;
	private toolbar!: HTMLElement;
	private cad!: HTMLElement;
	private host!: HTMLElement;
	private message!: HTMLElement;
	private status!: HTMLElement;
	private storyPicker!: SelectBox;
	private typePicker!: SelectBox;
	private typeContainer!: HTMLElement;
	private underlayGroup!: HTMLElement;
	private readonly underlayControls = this._register(new DisposableStore());
	/** What the editor shows as underlay now (story, file and placement), to reload only on change. */
	private underlayKey: string | undefined;
	private underlayProblem: string | undefined;
	private readonly toolButtons = new Map<Tool, Button>();
	private dimension: Dimension | undefined;

	private editor: CadEditorApi | undefined;
	private planModel: ITextModel | undefined;
	private objects: ITextModel | undefined;
	private plan: IFloorPlan | undefined;
	private storyIds: string[] = [];
	private fitPending = false;

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

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly statusDisposables = this._register(new DisposableStore());
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
		@IHoverService private readonly hoverService: IHoverService,
		@IFileService private readonly fileService: IFileService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
	) {
		super(FloorPlanEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.selectionService.onDidChangeSelection(({ source }) => {
			if (source !== SELECTION_SOURCE) {
				this.followSelection();
			}
			this.schedulePreview();
		}));
	}

	/** The floor plan file, for undo and redo. */
	get resource() {
		return (this.input as FloorPlanEditorInput | undefined)?.resource;
	}

	protected createEditor(parent: HTMLElement): void {
		this.root = append(parent, $('.saengine-floor-plan'));
		this.root.tabIndex = -1;
		this.toolbar = append(this.root, $('.floor-plan-toolbar'));

		const group = (className: string) => append(this.toolbar, $(`.floor-plan-group.${className}`));
		const stories = group('stories');
		append(stories, $('span.floor-plan-label', undefined, localize('floorPlan.story', "Story")));
		this.storyPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.storyAria', "Story shown in the floor plan") }));
		this.storyPicker.render(append(stories, $('.floor-plan-select.story')));
		this._register(this.storyPicker.onDidSelect(({ index }) => {
			const input = this.input as FloorPlanEditorInput | undefined;
			if (input && this.storyIds[index] !== input.story) {
				input.story = this.storyIds[index];
				this.chainStart = undefined;
				this.renderPlan();
			}
		}));

		const tools = group('tools');
		for (const { tool, label, icon } of TOOLS) {
			const button = this._register(new Button(append(tools, $('.floor-plan-tool')), { ...defaultButtonStyles, secondary: true, supportIcons: true, title: label }));
			button.label = `$(${icon.id}) ${label}`;
			button.element.setAttribute('aria-pressed', 'false');
			this._register(button.onDidClick(() => this.setTool(tool)));
			this.toolButtons.set(tool, button);
		}

		this.typeContainer = group('types');
		append(this.typeContainer, $('span.floor-plan-label', undefined, localize('floorPlan.type', "Type")));
		this.typePicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('floorPlan.typeAria', "Object type to place") }));
		this.typePicker.render(append(this.typeContainer, $('.floor-plan-select.type')));
		this._register(this.typePicker.onDidSelect(({ index }) => {
			const tool = this.placementTool;
			if (tool && this.typeIds[index]) {
				this.types.set(tool, this.typeIds[index]);
			}
		}));

		const actions = group('actions');
		const action = (label: string, icon: ThemeIcon, title: string, run: () => void) => {
			const button = this._register(new Button(append(actions, $('.floor-plan-action')), { ...defaultButtonStyles, secondary: true, supportIcons: true, title }));
			button.label = `$(${icon.id}) ${label}`;
			this._register(button.onDidClick(run));
		};
		action(localize('floorPlan.zoomExtents', "Zoom Extents"), Codicon.screenFull, localize('floorPlan.zoomExtentsTitle', "Fit the whole plan in the view"), () => this.editor?.zoomExtents());
		action(localize('floorPlan.editGrids', "Edit Grids & Stories"), Codicon.layers, localize('floorPlan.editGridsTitle', "Edit the grid lines and stories beside the plan"), () => this.openGrids());
		action(localize('floorPlan.exportDxf', "Export DXF"), Codicon.export, localize('floorPlan.exportDxfTitle', "Write the plan of every story to 11 Exports/Floor Plan as DXF"), () => this.exportDxf());
		this.underlayGroup = group('underlay');

		this.status = append(this.root, $('.floor-plan-status'));
		this.cad = append(this.root, $('.saengine-cad-editor'));
		this.host = append(this.cad, $('.cad-host'));
		this.message = append(this.cad, $('.cad-message'));
		this.registerMouse();
		this._register(addDisposableListener(this.root, EventType.KEY_DOWN, e => {
			if (e.key === 'Escape' && this.tool !== 'select') {
				e.preventDefault();
				e.stopPropagation();
				this.cancel();
			} else if (e.key === 'Enter' && this.tool === 'polygonSlab' && this.polygon.length) {
				e.preventDefault();
				this.finishPolygon();
			}
		}));
		this.updateToolbar();
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

		let editor: CadEditorApi;
		try {
			editor = this.editor = await acquireCadEditor(this.host);
		} catch (error) {
			this.showMessage(localize('floorPlan.loadFailed', "The CAD editor could not start: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			this.release();
			return;
		}
		if (!await editor.newDrawing({ readOnly: true })) {
			this.showMessage(localize('floorPlan.openFailed', "The floor plan drawing could not be created."));
			return;
		}
		this.fitPending = true;
		this.followSelection();
		this.renderPlan();
	}

	/** Shows the story of the item selected elsewhere (Model Explorer, Properties). */
	private followSelection(): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		const selection = this.selectionService.selection;
		const story = selection && storyOfSelection(parse(this.planModel), selection);
		if (input && story && story !== input.story) {
			input.story = story;
			this.chainStart = undefined;
			this.renderPlan();
		}
	}

	override clearInput(): void {
		this.release();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.dimension = dimension;
		this.root.style.width = `${dimension.width}px`;
		this.root.style.height = `${dimension.height}px`;
		// The toolbar wraps on narrow editors; the drawing takes the rest.
		const chrome = this.toolbar.offsetHeight + this.status.offsetHeight;
		this.cad.style.height = `${Math.max(0, dimension.height - chrome)}px`;
	}

	override focus(): void {
		super.focus();
		this.root.focus();
	}

	override dispose(): void {
		this.release();
		super.dispose();
	}

	private release(): void {
		this.renderScheduler.cancel();
		this.previewFrame.clear();
		this.inputDisposables.clear();
		this.planModel = this.objects = undefined;
		this.plan = undefined;
		this.underlayKey = undefined;
		this.underlayProblem = undefined;
		this.resetGesture();
		if (this.editor) {
			releaseCadEditor(this.editor);
			this.editor = undefined;
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
		this.root.focus();
	}

	/** Esc: drops the gesture in progress (a beam's first point, a picked member, corners), then the tool. */
	private cancel(): void {
		if (this.chainStart || this.picked || this.polygon.length) {
			this.resetGesture();
			this.notice = undefined;
			this.updateStatus();
			this.schedulePreview();
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

	/** Object types the active tool can place, as [id, name]. */
	private typesForTool(): [string, string][] {
		const tool = this.placementTool;
		const objects = parse(this.objects);
		const list = isObject(objects) && Array.isArray(objects.objects) ? objects.objects.filter(isObject) : [];
		return tool ? list
			.filter(o => typeof o.id === 'string' && TOOL_KINDS[tool].includes(o.kind as string))
			.map(o => [o.id as string, typeof o.name === 'string' && o.name ? `${o.name} (${o.id})` : o.id as string]) : [];
	}

	private updateToolbar(): void {
		for (const [tool, button] of this.toolButtons) {
			button.element.classList.toggle('active', tool === this.tool);
			button.element.setAttribute('aria-pressed', String(tool === this.tool));
		}
		const tool = this.placementTool;
		this.typeContainer.classList.toggle('hidden', !tool);
		if (tool) {
			const types = this.typesForTool();
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
		if (this.dimension) {
			this.layout(this.dimension);
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
			if (this.editor && this.tool !== 'select') {
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
	private rotationOf(shape: IMemberShape): number {
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

	private moveBy(delta: CadPoint): void {
		const picked = this.picked;
		if (!picked) {
			return;
		}
		const result = moveMember(parse(this.planModel), picked.group, picked.id, delta);
		if (result.ok) {
			this.picked = undefined;
			this.write(result.layout);
			this.selectionService.setSelection({ kind: 'member', group: picked.group, id: picked.id }, SELECTION_SOURCE);
			this.setNotice(localize('floorPlan.moved', "Moved {0} by {1}, {2} mm.", picked.id, Math.round(delta[0]), Math.round(delta[1])));
		} else {
			this.setNotice(result.error);
		}
		this.schedulePreview();
	}

	private rotateTo(degrees: number): void {
		const picked = this.picked;
		if (!picked) {
			return;
		}
		const result = rotateMember(parse(this.planModel), picked.group, picked.id, degrees);
		if (result.ok) {
			this.write(result.layout);
			this.picked = this.plan?.members.find(m => m.group === picked.group && m.id === picked.id) ?? picked;
			this.setNotice(localize('floorPlan.rotated', "Rotated {0} to {1}°.", picked.id, this.rotationOf(picked)));
		} else {
			this.setNotice(result.error);
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
			this.write(result.layout);
			this.setNotice(localize('floorPlan.placed', "Placed {0}.", result.id));
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
			// Selecting only shows the member (Properties, Model Explorer); it never changes it.
			const shape = this.plan && this.editor ? pickMember(this.plan.members, point, PICK_PIXELS * this.editor.unitsPerPixel()) : undefined;
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
				this.write(removeMember(layout, shape.group, shape.id));
				this.setNotice(localize('floorPlan.deleted', "Deleted {0}.", shape.id));
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
				result = placeFooting(layout, type, story, node);
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
			this.write(result.layout);
			this.setNotice(localize('floorPlan.placed', "Placed {0}.", result.id));
		} else {
			this.setNotice(result.error);
		}
		this.schedulePreview();
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
			stories.map(s => ({ text: `${s.name} (${s.elevation >= 0 ? '+' : ''}${s.elevation})` })),
			Math.max(0, this.storyIds.indexOf(input.story ?? '')),
		);

		this.plan = floorPlanDrawing(layout, parse(this.objects), input.story ?? '');
		this.editor.setGenerated(this.plan.drawing);
		this.renderUnderlayControls(layout, input.story);
		void this.syncUnderlay(layout, input);
		if (this.fitPending) {
			this.fitPending = false;
			this.editor.zoomExtents();
		}
		this.updateToolbar();
		this.updateStatus();
		this.schedulePreview();
	}

	private schedulePreview(): void {
		if (!this.previewFrame.value) {
			const handle = getWindow(this.root).requestAnimationFrame(() => {
				this.previewFrame.clear();
				this.renderPreview();
			});
			this.previewFrame.value = { dispose: () => getWindow(this.root).cancelAnimationFrame(handle) };
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
		editor.setPreview({ layers: PREVIEW_LAYERS, entities });
	}

	// ───────────────────────────── status ─────────────────────────────

	private setNotice(text: string): void {
		this.notice = text;
		this.updateStatus();
	}

	private updateStatus(): void {
		this.statusDisposables.clear();
		clearNode(this.status);
		const layout = parse(this.planModel);
		const plan = this.plan;
		const hint = TOOLS.find(t => t.tool === this.tool)?.hint;
		const text = (value: string) => append(this.status, $('span', undefined, value));
		if (this.planModel && isObject(layout) && layout.part === 'floorPlan') {
			// The placeholder of projects made before the floor plan owned the layout.
			text(localize('floorPlan.empty', "This project has no floor plan yet. Creating it takes over the grids, stories and members of an older building model."));
			const create = this.statusDisposables.add(new Button(append(this.status, $('.floor-plan-link')), defaultButtonStyles));
			create.label = localize('floorPlan.create', "Create Floor Plan");
			this.statusDisposables.add(create.onDidClick(() => this.createFloorPlan()));
		} else if (this.planModel && (!isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID)) {
			text(localize('floorPlan.invalidModel', "floor-plan.json is not a valid floor plan; open it as text to fix it. The plan cannot be edited until then."));
		} else if (this.notice) {
			text(this.notice);
		} else if (hint) {
			text(hint);
		} else if (this.storyIds.length === 0 && this.planModel) {
			text(localize('floorPlan.noStories', "The floor plan has no stories yet."));
		}
		if (this.picked && (this.tool === 'move' || this.tool === 'rotate')) {
			this.renderTypedInput(this.tool, this.picked);
		}
		if (this.placementTool && this.typeIds.length === 0) {
			const open = this.statusDisposables.add(new Button(append(this.status, $('.floor-plan-link')), { ...defaultButtonStyles, secondary: true }));
			open.label = localize('floorPlan.openObjects', "Open Object Types");
			this.statusDisposables.add(open.onDidClick(() => this.openPart('objects')));
		}
		if (this.underlayProblem) {
			const problem = append(this.status, $('span.floor-plan-problems'));
			append(problem, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
			append(problem, $('span', undefined, this.underlayProblem));
		}
		if (plan?.problems.length) {
			const problems = append(this.status, $('span.floor-plan-problems'));
			append(problems, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
			append(problems, $('span', undefined, localize('floorPlan.problems', "{0} member(s) could not be drawn", plan.problems.length)));
			this.statusDisposables.add(this.hoverService.setupDelayedHover(problems, { content: plan.problems.join('\n') }));
		}
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

	/** Attach, show or hide, and remove the architect's drawing under the current story. */
	private renderUnderlayControls(layout: unknown, story: string | undefined): void {
		this.underlayControls.clear();
		clearNode(this.underlayGroup);
		const underlay = this.underlayOf(layout, story);
		const button = (label: string, icon: ThemeIcon, title: string, run: () => void) => {
			const b = this.underlayControls.add(new Button(append(this.underlayGroup, $('.floor-plan-action')), { ...defaultButtonStyles, secondary: true, supportIcons: true, title }));
			b.label = `$(${icon.id}) ${label}`;
			this.underlayControls.add(b.onDidClick(run));
		};
		if (!underlay) {
			button(localize('floorPlan.attachUnderlay', "Attach Underlay"), Codicon.fileMedia, localize('floorPlan.attachUnderlayTitle', "Show an architect's DXF drawing, greyed, under this story's plan"), () => this.attachUnderlay());
			return;
		}
		const visible = underlay.visible !== false;
		button(visible ? localize('floorPlan.hideUnderlay', "Hide Underlay") : localize('floorPlan.showUnderlay', "Show Underlay"), visible ? Codicon.eyeClosed : Codicon.eye,
			localize('floorPlan.toggleUnderlayTitle', "Underlay: {0}. Its offset, scale and rotation are set in Grids & Stories.", String(underlay.file)),
			() => this.changeUnderlay(story, u => ({ ...u, visible: !visible })));
		button(localize('floorPlan.removeUnderlay', "Remove Underlay"), Codicon.close, localize('floorPlan.removeUnderlayTitle', "Stop showing {0} under this story (the file stays)", String(underlay.file)), () => this.changeUnderlay(story, undefined));
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
		}
	}

	/** Writes the structural plan of every story to `11 Exports/Floor Plan/<story>.dxf`. */
	private async exportDxf(): Promise<void> {
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
		try {
			for (const story of stories) {
				editor.setGenerated(floorPlanDrawing(layout, objects, story.id).drawing);
				const name = `${story.id} ${story.name}`.replace(/[\\/:*?"<>|]/g, '-');
				await this.fileService.writeFile(joinPath(folder, `${name}.dxf`), VSBuffer.fromString(editor.toDxf()));
			}
			this.setNotice(localize('floorPlan.exported', "Exported the plans of {0} stories to {1}/Floor Plan.", stories.length, exports.folder));
		} catch (error) {
			this.setNotice(localize('floorPlan.exportFailed', "The export failed: {0}", String(error)));
		} finally {
			this.renderPlan();
		}
	}

	/** Exact entry for the picked member: a displacement for Move, an angle for Rotate. */
	private renderTypedInput(tool: 'move' | 'rotate', picked: IMemberShape): void {
		const container = append(this.status, $('.floor-plan-typed'));
		const box = this.statusDisposables.add(new InputBox(container, this.contextViewService, {
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
			this.root.focus();
		};
		this.statusDisposables.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				apply();
			}
		}));
		const button = this.statusDisposables.add(new Button(append(this.status, $('.floor-plan-link')), { ...defaultButtonStyles, secondary: true }));
		button.label = tool === 'move' ? localize('floorPlan.applyMove', "Move") : localize('floorPlan.applyRotate', "Rotate");
		this.statusDisposables.add(button.onDidClick(apply));
		if (tool === 'rotate') {
			const quarter = this.statusDisposables.add(new Button(append(this.status, $('.floor-plan-link')), { ...defaultButtonStyles, secondary: true }));
			quarter.label = localize('floorPlan.rotate90', "+90°");
			this.statusDisposables.add(quarter.onDidClick(() => this.rotateTo(this.rotationOf(picked) + 90)));
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
