/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/drawingImport.css';
import type { CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { alignedRotation, DRAWING_ROLES, DRAWING_UNITS, DrawingRole, DrawingUnit, gridPoints, IDrawingImportOptions, IDrawingImportRecord, IDrawingInfo, IDrawingLayer, importsOf, initialRoles, roleCounts, snapPoint } from './architectureDrawingImport.js';
import { IArchitecture, wallThickness } from './architectureModel.js';

const SVG = 'http://www.w3.org/2000/svg';
/** A click on the preview snaps to a drawing vertex this close [px]. */
const PICK_PIXELS = 12;
/** Pointer travel below which a press on the preview is a click, not a pan [px]. */
const CLICK_PIXELS = 4;

const ROLE_NAMES: { readonly [role in DrawingRole]: string } = {
	walls: localize('drawingRole.walls', "Walls"),
	doors: localize('drawingRole.doors', "Doors"),
	windows: localize('drawingRole.windows', "Windows"),
	rooms: localize('drawingRole.rooms', "Room names"),
	ignore: localize('drawingRole.ignore', "Ignore"),
};

const UNIT_NAMES: { readonly [unit in DrawingUnit]: string } = {
	mm: localize('drawingUnit.mm', "Millimetres"),
	cm: localize('drawingUnit.cm', "Centimetres"),
	m: localize('drawingUnit.m', "Metres"),
	ft: localize('drawingUnit.ft', "Feet"),
	in: localize('drawingUnit.in', "Inches"),
};

export interface IDrawingImportPanelOptions {
	readonly info: IDrawingInfo;
	/** The file's name, shown. */
	readonly name: string;
	/** The file as recorded in architecture.json. */
	readonly source: string;
	readonly arch: IArchitecture;
	readonly floorPlan: unknown;
	readonly stories: readonly { readonly id: string; readonly name: string }[];
	readonly story: string;
}

type PointKey = 'base' | 'base2';

/**
 * The layer-mapping step of "Import Architect's DWG/DXF...", over the Architecture editor's
 * drawing: the drawing's layers with what each holds (guessed or remembered), its unit, the story
 * and the placement (a drawing point at a grid point, a rotation or a second pair of points), the
 * wall type for single centre lines, and a preview coloured by role where points are picked.
 */
export class DrawingImportPanel extends Disposable {

	readonly element: HTMLElement;
	private readonly _onDidAccept = this._register(new Emitter<IDrawingImportOptions>());
	readonly onDidAccept = this._onDidAccept.event;
	private readonly _onDidCancel = this._register(new Emitter<void>());
	readonly onDidCancel = this._onDidCancel.event;

	private readonly roles: Map<string, DrawingRole>;
	private unit: DrawingUnit;
	private story: string;
	private wallType: string | undefined;
	private base: CadPoint = [0, 0];
	private base2: CadPoint | undefined;
	private target = 0;
	private target2 = 1;
	private rotation = 0;
	private twoPoints = false;
	private picking: PointKey | undefined;

	private readonly grid: readonly { readonly label: string; readonly point: CadPoint }[];
	private readonly formDisposables = this._register(new DisposableStore());
	private readonly form: HTMLElement;
	private readonly message: HTMLElement;
	private readonly svg: SVGSVGElement;
	private readonly layerGroups = new Map<string, SVGGElement>();
	private readonly pickButtons = new Map<PointKey, HTMLElement>();
	private readonly markers: SVGGElement;
	private readonly hint: HTMLElement;
	private readonly legend: HTMLElement;
	private view: [number, number, number, number] = [0, 0, 1, 1];
	private importButton: Button | undefined;
	private notes: readonly string[] = [];
	private problem: string | undefined;

	constructor(
		parent: HTMLElement,
		private readonly options: IDrawingImportPanelOptions,
		private readonly contextViewService: IContextViewService,
	) {
		super();
		const { info, arch, source } = options;
		const { roles, remembered } = initialRoles(info, arch, source);
		this.roles = roles;
		this.grid = gridPoints(options.floorPlan);
		this.story = options.story;
		const earlier = importsOf(arch, source).find(r => r.story === options.story) ?? importsOf(arch, source)[0];
		this.unit = (earlier?.unit && DRAWING_UNITS.includes(earlier.unit) && earlier.unit) || info.unit;
		this.applyRecord(earlier);
		const thinnest = [...arch.wallTypes].sort((a, b) => wallThickness(a) - wallThickness(b))[0];
		this.wallType = thinnest?.id;

		this.element = append(parent, $('.sa-drawing-import', { role: 'dialog', 'aria-label': localize('drawingImport.aria', "Import an architect's drawing") }));
		this._register({ dispose: () => this.element.remove() });
		const side = append(this.element, $('.sa-di-form'));
		const heading = append(side, $('.sa-di-heading'));
		append(heading, $('h2', undefined, localize('drawingImport.title', "Import {0}", options.name)));
		append(heading, $('.sa-di-sub', undefined, localize('drawingImport.sub', "Say what each layer holds and where the drawing goes; the walls, doors, windows and room names are read from the layers you map.")));
		this.message = append(side, $('.sa-di-message', { role: 'status' }));
		this.form = append(side, $('.sa-di-fields'));
		const actions = append(side, $('.sa-di-actions'));
		this.importButton = this._register(new Button(actions, { ...defaultButtonStyles, title: localize('drawingImport.importTitle', "Read the mapped layers into the architecture") }));
		this.importButton.label = localize('drawingImport.import', "Import");
		this._register(this.importButton.onDidClick(() => this.accept()));
		const cancel = this._register(new Button(actions, { ...defaultButtonStyles, secondary: true }));
		cancel.label = localize('drawingImport.cancel', "Cancel");
		this._register(cancel.onDidClick(() => this._onDidCancel.fire()));

		const preview = append(this.element, $('.sa-di-preview'));
		this.legend = append(preview, $('.sa-di-legend'));
		this.svg = append(preview, document.createElementNS(SVG, 'svg')) as SVGSVGElement;
		this.svg.setAttribute('class', 'sa-di-svg');
		this.svg.setAttribute('role', 'img');
		this.svg.setAttribute('aria-label', localize('drawingImport.previewAria', "Preview of the drawing, coloured by what each layer holds"));
		this.markers = document.createElementNS(SVG, 'g');
		this.hint = append(preview, $('.sa-di-hint'));
		this.drawPreview();
		this.registerPreviewInput();
		this._register(addDisposableListener(this.element, EventType.KEY_DOWN, e => {
			if (e.key === 'Escape') {
				e.preventDefault();
				e.stopPropagation();
				if (this.picking) {
					this.picking = undefined;
					this.update();
				} else {
					this._onDidCancel.fire();
				}
			}
		}));

		const notes: string[] = [];
		const done = importsOf(arch, source).filter(r => r.story === this.story);
		if (done.length) {
			notes.push(localize('drawingImport.again', "This file was imported onto this story before: importing it again replaces the {0} items it made.", done[0].items?.length ?? 0));
		}
		if (remembered) {
			notes.push(localize('drawingImport.remembered', "Layers are mapped as in this project's earlier import."));
		}
		if (info.unitGuessed) {
			notes.push(localize('drawingImport.unitGuessed', "The drawing does not say its unit: {0} is a guess from its size; check it.", UNIT_NAMES[info.unit]));
		}
		notes.push(...info.warnings);
		this.notes = notes;
		this.renderForm();
		this.update();
	}

	/** Shows a problem (the backend's) above the fields. */
	setProblem(text: string | undefined): void {
		this.problem = text;
		this.update();
	}

	setBusy(busy: boolean): void {
		if (this.importButton) {
			this.importButton.enabled = !busy;
			this.importButton.label = busy ? localize('drawingImport.importing', "Importing...") : localize('drawingImport.import', "Import");
		}
	}

	focus(): void {
		this.importButton?.focus();
	}

	/** The placement of an earlier import of this file. */
	private applyRecord(record: IDrawingImportRecord | undefined): void {
		if (!record) {
			return;
		}
		if (record.base) {
			this.base = [record.base[0], record.base[1]];
		}
		const at = record.at;
		const index = at ? this.grid.findIndex(g => Math.abs(g.point[0] - at[0]) < 1 && Math.abs(g.point[1] - at[1]) < 1) : -1;
		if (index >= 0) {
			this.target = index;
		}
		this.rotation = record.rotation ?? 0;
	}

	// ───────────────────────────── form ─────────────────────────────

	private renderForm(): void {
		this.formDisposables.clear();
		this.pickButtons.clear();
		clearNode(this.form);
		const { info } = this.options;

		append(this.form, $('h3', undefined, localize('drawingImport.layers', "Layers")));
		const table = append(this.form, $('.sa-di-layers', { role: 'table', 'aria-label': localize('drawingImport.layersAria', "Layers of the drawing") }));
		const head = append(table, $('.sa-di-row.head', { role: 'row' }));
		append(head, $('span', { role: 'columnheader' }, localize('drawingImport.layer', "Layer")));
		append(head, $('span', { role: 'columnheader' }, localize('drawingImport.holds', "On it")));
		append(head, $('span', { role: 'columnheader' }, localize('drawingImport.role', "Read as")));
		for (const layer of info.layers.filter(l => l.total > 0)) {
			const row = append(table, $('.sa-di-row', { role: 'row', 'data-layer': layer.name }));
			append(row, $('span.name', { role: 'cell', title: layer.name }, layer.name));
			const what = describe(layer);
			append(row, $('span.what', { role: 'cell', title: [what, ...layer.blocks.map(b => localize('drawingImport.blockName', "block {0}", b)), ...layer.texts.map(t => `"${t}"`)].join('\n') }, what));
			const cell = append(row, $('span.role', { role: 'cell' }));
			this.select(cell, localize('drawingImport.roleOf', "What layer {0} holds", layer.name), DRAWING_ROLES.map(r => ({ id: r, text: ROLE_NAMES[r] })), this.roles.get(layer.name) ?? 'ignore', id => {
				this.roles.set(layer.name, id as DrawingRole);
				this.update();
			});
			this.formDisposables.add(addDisposableListener(row, EventType.MOUSE_ENTER, () => this.highlight(layer.name)));
			this.formDisposables.add(addDisposableListener(row, EventType.MOUSE_LEAVE, () => this.highlight(undefined)));
		}
		const empty = info.layers.filter(l => l.total === 0).length;
		if (empty) {
			append(this.form, $('.sa-di-note', undefined, localize('drawingImport.emptyLayers', "{0} empty layers not listed.", empty)));
		}

		append(this.form, $('h3', undefined, localize('drawingImport.placement', "Units and placement")));
		const unitLabel = (u: DrawingUnit) => u === info.unit
			? (info.unitGuessed ? localize('drawingImport.unitGuess', "{0} (guessed)", UNIT_NAMES[u]) : localize('drawingImport.unitFile', "{0} (from the drawing)", UNIT_NAMES[u]))
			: UNIT_NAMES[u];
		this.field(localize('drawingImport.unit', "Drawing unit"), cell => this.select(cell, localize('drawingImport.unit', "Drawing unit"), DRAWING_UNITS.map(u => ({ id: u, text: unitLabel(u) })), this.unit, id => {
			this.unit = id as DrawingUnit;
			this.update();
		}));
		this.field(localize('drawingImport.story', "Story"), cell => this.select(cell, localize('drawingImport.story', "Story"), this.options.stories.map(s => ({ id: s.id, text: s.name })), this.story, id => {
			this.story = id;
			this.update();
		}));
		this.pointField('base', localize('drawingImport.base', "Drawing point"), localize('drawingImport.baseHint', "The drawing's point that goes on the grid point below (pick it on the preview, e.g. the corner at grid A-1)."));
		this.field(localize('drawingImport.target', "Goes to grid point"), cell => this.select(cell, localize('drawingImport.target', "Goes to grid point"), this.grid.map((g, i) => ({ id: String(i), text: `${g.label} (${Math.round(g.point[0])}, ${Math.round(g.point[1])})` })), String(this.target), id => {
			this.target = Number(id);
			this.update();
		}));
		this.field(localize('drawingImport.turn', "Rotation from"), cell => this.select(cell, localize('drawingImport.turn', "Rotation from"), [
			{ id: 'angle', text: localize('drawingImport.angle', "An angle") },
			{ id: 'points', text: localize('drawingImport.twoPoints', "A second pair of points") },
		], this.twoPoints ? 'points' : 'angle', id => {
			this.twoPoints = id === 'points';
			this.target2 = Math.min(Math.max(this.target2, 0), this.grid.length - 1);
			this.renderForm();
			this.update();
		}));
		if (this.twoPoints) {
			this.pointField('base2', localize('drawingImport.base2', "Second drawing point"), localize('drawingImport.base2Hint', "A second point of the drawing, e.g. the corner at another grid point; the drawing turns so it lies towards that grid point."));
			this.field(localize('drawingImport.target2', "Towards grid point"), cell => this.select(cell, localize('drawingImport.target2', "Towards grid point"), this.grid.map((g, i) => ({ id: String(i), text: `${g.label} (${Math.round(g.point[0])}, ${Math.round(g.point[1])})` })), String(this.target2), id => {
				this.target2 = Number(id);
				this.update();
			}));
		} else {
			this.field(localize('drawingImport.rotation', "Rotation (°, anticlockwise)"), cell => this.input(cell, localize('drawingImport.rotation', "Rotation (°, anticlockwise)"), String(this.rotation), text => {
				const value = Number(text);
				if (Number.isFinite(value)) {
					this.rotation = value;
					this.update();
				}
			}));
		}

		append(this.form, $('h3', undefined, localize('drawingImport.walls', "Walls")));
		const types = this.options.arch.wallTypes;
		this.field(localize('drawingImport.singleLines', "Single lines are"), cell => this.select(cell, localize('drawingImport.singleLines', "Single lines are"), types.map(t => ({ id: t.id, text: `${t.id}: ${t.name} (${wallThickness(t)} mm)` })), this.wallType ?? '', id => this.wallType = id));
		append(this.form, $('.sa-di-note', undefined, localize('drawingImport.wallNote', "Pairs of parallel lines 50 to 600 mm apart are walls of that thickness (matched to a wall type, or a new one); a single line on a wall layer, 1 m or longer, is a wall centre line of the type above.")));
	}

	private field(label: string, build: (cell: HTMLElement) => void, hint?: string): HTMLElement {
		const row = append(this.form, $('.sa-di-field'));
		append(row, $('label', undefined, label));
		const cell = append(row, $('.control'));
		build(cell);
		if (hint) {
			append(row, $('.sa-di-note', undefined, hint));
		}
		return row;
	}

	private pointField(key: PointKey, label: string, hint: string): void {
		const row = this.field(label, cell => {
			const value = () => this[key] ?? this.base;
			const x = this.input(cell, localize('drawingImport.x', "{0} x", label), format(value()[0]), text => this.setPoint(key, 0, text));
			x.element.classList.add('coord');
			const y = this.input(cell, localize('drawingImport.y', "{0} y", label), format(value()[1]), text => this.setPoint(key, 1, text));
			y.element.classList.add('coord');
			const pick = this.formDisposables.add(new Button(cell, { ...defaultButtonStyles, secondary: true, title: localize('drawingImport.pickTitle', "Click the point on the preview (it snaps to the drawing's corners and ends)") }));
			pick.label = localize('drawingImport.pick', "Pick");
			pick.element.classList.add('pick');
			this.pickButtons.set(key, pick.element);
			this.formDisposables.add(pick.onDidClick(() => {
				this.picking = this.picking === key ? undefined : key;
				this.update();
			}));
		}, hint);
		row.classList.add('point');
	}

	private setPoint(key: PointKey, axis: 0 | 1, text: string): void {
		const value = Number(text);
		if (!Number.isFinite(value)) {
			return;
		}
		const [x, y] = this[key] ?? this.base;
		this[key] = axis === 0 ? [value, y] : [x, value];
		this.update();
	}

	private select(cell: HTMLElement, label: string, options: readonly { readonly id: string; readonly text: string }[], value: string, apply: (id: string) => void): SelectBox {
		const index = Math.max(0, options.findIndex(o => o.id === value));
		const select = this.formDisposables.add(new SelectBox(options.map(o => ({ text: o.text })), index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
		select.render(cell);
		this.formDisposables.add(select.onDidSelect(({ index: picked }) => {
			if (options[picked]) {
				apply(options[picked].id);
			}
		}));
		return select;
	}

	private input(cell: HTMLElement, label: string, value: string, apply: (text: string) => void): InputBox {
		const box = this.formDisposables.add(new InputBox(cell, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: label }));
		box.value = value;
		this.formDisposables.add(box.onDidChange(text => apply(text)));
		return box;
	}

	// ───────────────────────────── preview ─────────────────────────────

	private drawPreview(): void {
		const { info } = this.options;
		const [[x0, y0], [x1, y1]] = info.extents ?? [[0, 0], [1, 1]];
		const pad = Math.max(x1 - x0, y1 - y0, 1e-6) * 0.03;
		this.view = [x0 - pad, -y1 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad];
		this.applyView();
		const size = Math.max(this.view[2], this.view[3]);
		for (const layer of info.layers) {
			const shapes = info.preview[layer.name] ?? [];
			const labels = info.labels.filter(l => l.layer === layer.name);
			if (!shapes.length && !labels.length) {
				continue;
			}
			const group = document.createElementNS(SVG, 'g');
			group.dataset.layer = layer.name;
			for (const shape of shapes) {
				const line = document.createElementNS(SVG, 'polyline');
				const points: string[] = [];
				for (let i = 0; i + 1 < shape.length; i += 2) {
					points.push(`${shape[i]},${-shape[i + 1]}`);
				}
				line.setAttribute('points', points.join(' '));
				group.appendChild(line);
			}
			for (const label of labels) {
				const text = document.createElementNS(SVG, 'text');
				text.setAttribute('x', String(label.at[0]));
				text.setAttribute('y', String(-label.at[1]));
				text.setAttribute('font-size', String(size / 70));
				text.textContent = label.text.split('\n')[0].slice(0, 30);
				group.appendChild(text);
			}
			this.layerGroups.set(layer.name, group);
			this.svg.appendChild(group);
		}
		this.svg.appendChild(this.markers);
	}

	private applyView(): void {
		this.svg.setAttribute('viewBox', this.view.join(' '));
	}

	/** Drawing units per screen pixel. */
	private unitsPerPixel(): number {
		const rect = this.svg.getBoundingClientRect();
		return rect.width && rect.height ? Math.max(this.view[2] / rect.width, this.view[3] / rect.height) : 1;
	}

	private toDrawing(e: MouseEvent): CadPoint {
		const matrix = this.svg.getScreenCTM();
		if (!matrix) {
			return [0, 0];
		}
		const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(matrix.inverse());
		return [p.x, -p.y];
	}

	private registerPreviewInput(): void {
		let down: { x: number; y: number; view: [number, number, number, number]; panning: boolean } | undefined;
		this._register(addDisposableListener(this.svg, EventType.WHEEL, (e: WheelEvent) => {
			e.preventDefault();
			const [px, py] = this.toDrawing(e);
			const factor = e.deltaY > 0 ? 1.2 : 1 / 1.2;
			const [vx, vy, vw, vh] = this.view;
			const sy = -py;
			this.view = [px - (px - vx) * factor, sy - (sy - vy) * factor, vw * factor, vh * factor];
			this.applyView();
			this.update();
		}, { passive: false }));
		this._register(addDisposableListener(this.svg, EventType.POINTER_DOWN, (e: PointerEvent) => {
			down = { x: e.clientX, y: e.clientY, view: [...this.view], panning: false };
			this.svg.setPointerCapture?.(e.pointerId);
		}));
		this._register(addDisposableListener(this.svg, EventType.POINTER_MOVE, (e: PointerEvent) => {
			if (!down) {
				return;
			}
			const dx = e.clientX - down.x;
			const dy = e.clientY - down.y;
			if (!down.panning && Math.hypot(dx, dy) < CLICK_PIXELS) {
				return;
			}
			down.panning = true;
			const scale = this.unitsPerPixel();
			this.view = [down.view[0] - dx * scale, down.view[1] - dy * scale, down.view[2], down.view[3]];
			this.applyView();
		}));
		this._register(addDisposableListener(this.svg, EventType.POINTER_UP, (e: PointerEvent) => {
			const start = down;
			down = undefined;
			if (!start || start.panning) {
				this.update();
				return;
			}
			const key = this.picking;
			if (!key) {
				return;
			}
			const at = this.toDrawing(e);
			const snapped = snapPoint(this.options.info, at, PICK_PIXELS * this.unitsPerPixel()) ?? at;
			this[key] = [round(snapped[0]), round(snapped[1])];
			this.picking = key === 'base' && this.twoPoints && !this.base2 ? 'base2' : undefined;
			this.renderForm();
			this.update();
		}));
	}

	private highlight(layer: string | undefined): void {
		for (const [name, group] of this.layerGroups) {
			group.classList.toggle('highlight', name === layer);
		}
	}

	private update(): void {
		const { info } = this.options;
		for (const [name, group] of this.layerGroups) {
			group.setAttribute('class', `role-${this.roles.get(name) ?? 'ignore'}`);
		}
		// Markers at the picked points, a constant size on screen.
		clearNode(this.markers as unknown as HTMLElement);
		const r = 7 * this.unitsPerPixel();
		const mark = (point: CadPoint | undefined, cls: string, label: string) => {
			if (!point) {
				return;
			}
			const g = document.createElementNS(SVG, 'g');
			g.setAttribute('class', `marker ${cls}`);
			const circle = document.createElementNS(SVG, 'circle');
			circle.setAttribute('cx', String(point[0]));
			circle.setAttribute('cy', String(-point[1]));
			circle.setAttribute('r', String(r));
			g.appendChild(circle);
			for (const [ax, ay, bx, by] of [[-2, 0, 2, 0], [0, -2, 0, 2]]) {
				const line = document.createElementNS(SVG, 'line');
				line.setAttribute('x1', String(point[0] + ax * r));
				line.setAttribute('y1', String(-point[1] + ay * r));
				line.setAttribute('x2', String(point[0] + bx * r));
				line.setAttribute('y2', String(-point[1] + by * r));
				g.appendChild(line);
			}
			const text = document.createElementNS(SVG, 'text');
			text.setAttribute('x', String(point[0] + r * 1.5));
			text.setAttribute('y', String(-point[1] - r * 1.5));
			text.setAttribute('font-size', String(r * 2));
			text.textContent = label;
			g.appendChild(text);
			this.markers.appendChild(g);
		};
		mark(this.base, 'first', this.grid[this.target]?.label ?? '');
		if (this.twoPoints) {
			mark(this.base2, 'second', this.grid[this.target2]?.label ?? '');
		}

		this.svg.classList.toggle('picking', !!this.picking);
		for (const [key, pick] of this.pickButtons) {
			pick.classList.toggle('active', key === this.picking);
		}
		this.hint.textContent = this.picking
			? (this.picking === 'base' ? localize('drawingImport.pickBase', "Click the drawing's point that goes on grid point {0}. Esc stops picking.", this.grid[this.target]?.label ?? '')
				: localize('drawingImport.pickBase2', "Click the drawing's point that lies towards grid point {0}.", this.grid[this.target2]?.label ?? ''))
			: localize('drawingImport.previewHint', "Wheel to zoom, drag to pan. Hover a layer to find it here.");

		const counts = roleCounts(this.roles, info);
		clearNode(this.legend);
		for (const role of DRAWING_ROLES) {
			const item = append(this.legend, $(`span.sa-di-key.role-${role}`));
			append(item, $('span.swatch'));
			append(item, $('span', undefined, localize('drawingImport.legend', "{0} ({1})", ROLE_NAMES[role], counts[role])));
		}

		clearNode(this.message);
		const lines = [...this.notes];
		let blocked: string | undefined;
		if (!counts.walls && !counts.doors && !counts.windows && !counts.rooms) {
			blocked = localize('drawingImport.nothingMapped', "Map at least one layer to walls, doors, windows or room names.");
		} else if (!counts.walls && (counts.doors || counts.windows || counts.rooms)) {
			lines.push(localize('drawingImport.noWalls', "No layer is read as walls: doors and windows need walls to sit in, rooms need walls around them (unless the story has them already)."));
		}
		if (this.twoPoints && !this.base2) {
			blocked = localize('drawingImport.needSecond', "Pick the second drawing point, or take the rotation from an angle.");
		}
		if (this.twoPoints && this.target2 === this.target) {
			blocked = localize('drawingImport.sameTargets', "The two grid points must differ.");
		}
		if (this.problem) {
			append(this.message, $('.sa-di-problem', undefined, this.problem));
		}
		if (blocked) {
			append(this.message, $('.sa-di-problem', undefined, blocked));
		}
		for (const line of lines) {
			append(this.message, $('.sa-di-note', undefined, line));
		}
		if (this.importButton) {
			this.importButton.enabled = !blocked;
		}
	}

	private accept(): void {
		const target = this.grid[this.target]?.point ?? [0, 0];
		const align = this.twoPoints && this.base2 ? { base: this.base2, at: this.grid[this.target2]?.point ?? [0, 0] } : undefined;
		const layers: { [layer: string]: DrawingRole } = {};
		for (const layer of this.options.info.layers) {
			if (layer.total) {
				layers[layer.name] = this.roles.get(layer.name) ?? 'ignore';
			}
		}
		this.problem = undefined;
		this._onDidAccept.fire({
			layers,
			unit: this.unit,
			story: this.story,
			base: this.base,
			at: target,
			rotation: align ? alignedRotation(this.base, target, align.base, align.at) : this.rotation,
			align,
			source: this.options.source,
			wallType: this.wallType,
		});
	}
}

function describe(layer: IDrawingLayer): string {
	const c = layer.counts;
	const parts: string[] = [];
	if (c.lines) { parts.push(localize('drawingImport.lines', "{0} lines", c.lines)); }
	if (c.arcs) { parts.push(localize('drawingImport.arcs', "{0} arcs", c.arcs)); }
	if (c.blocks) { parts.push(localize('drawingImport.blocks', "{0} blocks", c.blocks)); }
	if (c.texts) { parts.push(localize('drawingImport.texts', "{0} texts", c.texts)); }
	if (c.other) { parts.push(localize('drawingImport.other', "{0} other", c.other)); }
	return parts.join(', ');
}

function round(value: number): number {
	return Math.round(value * 1e4) / 1e4;
}

function format(value: number): string {
	return String(round(value));
}
