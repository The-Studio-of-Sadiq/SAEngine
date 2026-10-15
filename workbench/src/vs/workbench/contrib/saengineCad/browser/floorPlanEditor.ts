/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi, CadEntitySpec, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
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
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { newFloorPlan } from '../../../services/saengineProject/common/partSources.js';
import { acquireCadEditor, releaseCadEditor } from './cadHost.js';
import { floorPlanDrawing, IFloorPlan, IMemberShape, storiesOf } from './floorPlanDrawing.js';
import { bayAt, EditResult, IGridNode, pickMember, placeColumn, placeFooting, placeLinear, placeSlab, PlacementTool, removeMember, snapToGrid, TOOL_KINDS } from './floorPlanEdits.js';
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

type Tool = 'select' | PlacementTool | 'delete';

const TOOLS: readonly { readonly tool: Tool; readonly label: string; readonly icon: ThemeIcon; readonly hint: string }[] = [
	{ tool: 'select', label: localize('tool.select', "Select"), icon: Codicon.inspect, hint: '' },
	{ tool: 'column', label: localize('tool.column', "Column"), icon: Codicon.primitiveSquare, hint: localize('hint.column', "Click a grid intersection to place a column rising to this story.") },
	{ tool: 'beam', label: localize('tool.beam', "Beam"), icon: Codicon.dash, hint: localize('hint.beam', "Click two grid intersections; beams chain until you press Esc or right-click.") },
	{ tool: 'wall', label: localize('tool.wall', "Wall"), icon: Codicon.splitHorizontal, hint: localize('hint.wall', "Click two grid intersections; walls chain until you press Esc or right-click.") },
	{ tool: 'slab', label: localize('tool.slab', "Slab"), icon: Codicon.layout, hint: localize('hint.slab', "Click inside a bay to place a slab on this story.") },
	{ tool: 'footing', label: localize('tool.footing', "Footing"), icon: Codicon.symbolStructure, hint: localize('hint.footing', "Click a grid intersection to place a footing at this story.") },
	{ tool: 'delete', label: localize('tool.delete', "Delete"), icon: Codicon.trash, hint: localize('hint.delete', "Click a member on this story to delete it.") },
];

const PREVIEW_LAYERS: readonly CadLayerSpec[] = [
	{ name: 'SAENGINE-PREVIEW', color: 2, description: 'Placement preview' },
	{ name: 'SAENGINE-PREVIEW-DELETE', color: 1, description: 'Member to delete' },
];

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
	private hover: CadPoint | undefined;
	private notice: string | undefined;

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
	) {
		super(FloorPlanEditor.ID, group, telemetryService, themeService, storageService);
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
			if (this.tool !== 'select' && this.tool !== 'delete' && this.typeIds[index]) {
				this.types.set(this.tool, this.typeIds[index]);
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
			this.inputDisposables.add(model.onDidChangeContent(() => this.renderScheduler.schedule()));
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
		this.renderPlan();
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
		this.chainStart = undefined;
		if (this.editor) {
			releaseCadEditor(this.editor);
			this.editor = undefined;
		}
	}

	// ───────────────────────────── tools ─────────────────────────────

	private setTool(tool: Tool): void {
		this.tool = tool;
		this.chainStart = undefined;
		this.notice = undefined;
		this.updateToolbar();
		this.updateStatus();
		this.schedulePreview();
		this.root.focus();
	}

	/** Esc: drops the first point of a beam or wall, then the tool. */
	private cancel(): void {
		if (this.chainStart) {
			this.chainStart = undefined;
			this.schedulePreview();
		} else {
			this.setTool('select');
		}
	}

	private get placementTool(): PlacementTool | undefined {
		return this.tool === 'select' || this.tool === 'delete' ? undefined : this.tool;
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
			if (this.chainStart) {
				e.preventDefault();
				this.chainStart = undefined;
				this.schedulePreview();
			}
		}, true));
	}

	private snap(point: CadPoint): IGridNode | undefined {
		return this.editor ? snapToGrid(parse(this.planModel), point, SNAP_PIXELS * this.editor.unitsPerPixel()) : undefined;
	}

	private click(point: CadPoint): void {
		const input = this.input as FloorPlanEditorInput | undefined;
		const layout = parse(this.planModel);
		const story = input?.story;
		if (this.tool === 'select' || !story || !isObject(layout) || layout.schema !== FLOOR_PLAN_SCHEMA_ID) {
			return;
		}
		if (this.tool === 'delete') {
			const shape = this.plan && this.editor ? pickMember(this.plan.members, point, PICK_PIXELS * this.editor.unitsPerPixel()) : undefined;
			if (shape) {
				this.write(removeMember(layout, shape.group, shape.id));
				this.setNotice(localize('floorPlan.deleted', "Deleted {0}.", shape.id));
			}
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
		model.pushStackElement();
		model.pushEditOperations([], [{ range: model.getFullModelRange(), text: JSON.stringify(value, undefined, '\t') + '\n' }], () => null);
		model.pushStackElement();
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
		if (this.placementTool && this.typeIds.length === 0) {
			const open = this.statusDisposables.add(new Button(append(this.status, $('.floor-plan-link')), { ...defaultButtonStyles, secondary: true }));
			open.label = localize('floorPlan.openObjects', "Open Object Types");
			this.statusDisposables.add(open.onDidClick(() => this.openPart('objects')));
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
