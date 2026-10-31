/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEntitySpec, CadGeneratedDrawing, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { centroid } from '../../../../platform/saengine/common/geometry.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { MemberGroup, ModelSelection } from '../../../services/saengineProject/common/modelSelection.js';

export type { MemberGroup };

/*
 * The drawing of one story of the floor plan (`05 Floor Plan/floor-plan.json`), with member
 * outlines from the object types (`04 Objects/objects.json`). The drawing is regenerated from
 * the file on every change and never edited directly; edits go to the file. Layer names follow the US National CAD
 * Standard's structural discipline ("S-GRID", "S-COLS", ...).
 */

export const FLOOR_PLAN_LAYERS = {
	grid: 'S-GRID',
	gridLabels: 'S-GRID-IDEN',
	columns: 'S-COLS',
	beams: 'S-BEAM',
	walls: 'S-WALL',
	/** Non-structural walls (brick partitions): their weight is a line load on the beam under them. */
	partitions: 'S-WALL-PRTN',
	slabs: 'S-SLAB',
	footings: 'S-FNDN',
	labels: 'S-ANNO-IDEN',
	/** The plot (property line) and its buildable envelope from 01 Soil Report: a read-only underlay. */
	plot: 'C-PROP',
	envelope: 'C-PROP-SETB',
} as const;

const LAYERS: readonly CadLayerSpec[] = [
	{ name: FLOOR_PLAN_LAYERS.plot, color: 9, description: 'Plot boundary (01 Soil Report)' },
	{ name: FLOOR_PLAN_LAYERS.envelope, color: 9, linetype: 'DASHED', description: 'Buildable envelope inside the setbacks' },
	{ name: FLOOR_PLAN_LAYERS.grid, color: 8, linetype: 'CENTER', description: 'Grid lines' },
	{ name: FLOOR_PLAN_LAYERS.gridLabels, color: 7, description: 'Grid bubbles and labels' },
	{ name: FLOOR_PLAN_LAYERS.columns, color: 4, description: 'Columns' },
	{ name: FLOOR_PLAN_LAYERS.beams, color: 3, linetype: 'DASHED', description: 'Beams (below the slab)' },
	{ name: FLOOR_PLAN_LAYERS.walls, color: 5, description: 'Walls' },
	{ name: FLOOR_PLAN_LAYERS.partitions, color: 8, linetype: 'DASHED', description: 'Partition walls (non-structural)' },
	{ name: FLOOR_PLAN_LAYERS.slabs, color: 6, description: 'Slab edges' },
	{ name: FLOOR_PLAN_LAYERS.footings, color: 30, description: 'Footings and pile caps' },
	{ name: FLOOR_PLAN_LAYERS.labels, color: 7, description: 'Member labels' },
];

/** Drawing sizes for a 1:100 plan [mm]: 8 mm bubbles, 3.5 mm grid text, 2.5 mm member text. */
const BUBBLE_RADIUS = 400;
const BUBBLE_TEXT = 350;
const LABEL_TEXT = 250;
/** Distance the grid lines run past the outermost lines before the bubble. */
const GRID_OVERRUN = 1500;
/** Linetype scale for the template's inch-based CENTER/DASHED patterns. */
const GRID_LINETYPE_SCALE = 200;
const BEAM_LINETYPE_SCALE = 100;

// Loosely typed views of the JSON files: the drawing must survive any half-edited model, so
// every field is checked where it is used and bad members are reported, not thrown.
type Json = { readonly [key: string]: unknown };

interface IGridPoint { readonly x: string; readonly y: string; readonly dx?: number; readonly dy?: number }


/** Characters a member id may have (`saengine.library.materials.Id`). */
export const ID_CHARS = /[^A-Za-z0-9._-]/g;

/**
 * The label of member `id` on the plan: its id without the story it was copied to ("B5-L3" is
 * B5 on L3), so a member at one place keeps one label up the building, as on drawings.
 */
export function planLabel(layout: unknown, id: string): string {
	const dash = id.lastIndexOf('-');
	if (dash <= 0) {
		return id;
	}
	const suffix = id.slice(dash + 1);
	return storiesOf(layout).some(s => s.id.replace(ID_CHARS, '') === suffix) ? id.slice(0, dash) : id;
}

/** Where a drawn member is in plan, for picking it with the mouse. */
export interface IMemberShape {
	readonly group: MemberGroup;
	readonly id: string;
	readonly outline: { readonly kind: 'polygon'; readonly points: readonly CadPoint[] } | { readonly kind: 'circle'; readonly center: CadPoint; readonly radius: number };
}

/** The plot and its buildable envelope in project mm (`saengine.soil.plotCheck`), drawn under every story. */
export interface IPlotUnderlay {
	readonly plot?: readonly (readonly number[])[] | null;
	readonly envelope?: readonly (readonly number[])[] | null;
}

/** The plot's lines, first in the drawing so the model draws over them. */
function plotEntities(underlay: IPlotUnderlay | undefined): CadEntitySpec[] {
	const ring = (points: readonly (readonly number[])[] | null | undefined): CadPoint[] =>
		(points ?? []).filter(p => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])).map(p => [p[0], p[1]]);
	const entities: CadEntitySpec[] = [];
	const plot = ring(underlay?.plot);
	if (plot.length >= 3) {
		entities.push({ kind: 'polyline', layer: FLOOR_PLAN_LAYERS.plot, points: plot, closed: true });
	}
	const envelope = ring(underlay?.envelope);
	if (plot.length >= 3 && envelope.length >= 3) {
		entities.push({ kind: 'polyline', layer: FLOOR_PLAN_LAYERS.envelope, points: envelope, closed: true, linetypeScale: BEAM_LINETYPE_SCALE });
	}
	return entities;
}

export interface IFloorPlan {
	readonly drawing: CadGeneratedDrawing;
	/** The members drawn on the plan. */
	readonly members: readonly IMemberShape[];
	/** Members that could not be drawn, e.g. with an unknown object type or grid line. */
	readonly problems: readonly string[];
	/** Members drawn but likely wrong: a slab on nothing, a slab with a beam across it. */
	readonly warnings: readonly string[];
	/** Quick fixes for the warnings: split a slab along the beam or wall across it. */
	readonly fixes?: readonly ISlabSplit[];
}

/** A slab with a beam or structural wall across it, to split along it. */
export interface ISlabSplit {
	readonly slab: string;
	readonly member: string;
	/** "Split S1 along B6". */
	readonly label: string;
}

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isObject) : [];
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function insidePolygon([x, y]: CadPoint, points: readonly CadPoint[]): boolean {
	let inside = false;
	for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
		const [xi, yi] = points[i];
		const [xj, yj] = points[j];
		if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) {
			inside = !inside;
		}
	}
	return inside;
}

export function distanceToSegment([px, py]: CadPoint, [ax, ay]: CadPoint, [bx, by]: CadPoint): number {
	const [dx, dy] = [bx - ax, by - ay];
	const t = dx || dy ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))) : 0;
	return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function rotate([x, y]: CadPoint, degrees: number): CadPoint {
	const a = degrees * Math.PI / 180;
	return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
}

function translate(points: readonly CadPoint[], [ox, oy]: CadPoint, degrees = 0): CadPoint[] {
	return points.map(p => {
		const [x, y] = rotate(p, degrees);
		return [ox + x, oy + y];
	});
}

function rectangle(width: number, depth: number): CadPoint[] {
	const [w, d] = [width / 2, depth / 2];
	return [[-w, -d], [w, -d], [w, d], [-w, d]];
}

/**
 * Outline of a profile (as in `objects.json`, IFC parameterised profiles) centred on its bounding
 * box, or a circle radius. Fillets are left out at plan scale.
 */
export function profileOutline(profile: Json): { readonly kind: 'polygon'; readonly points: CadPoint[] } | { readonly kind: 'circle'; readonly radius: number } | undefined {
	const n = (key: string) => num(profile[key]);
	switch (profile.shape) {
		case 'rectangle':
		case 'rectangleHollow': {
			const [w, d] = [n('xDim'), n('yDim')];
			return w && d ? { kind: 'polygon', points: rectangle(w, d) } : undefined;
		}
		case 'circle':
		case 'circleHollow': {
			const r = n('radius');
			return r ? { kind: 'circle', radius: r } : undefined;
		}
		case 'I': {
			const [b, h, tw, tf] = [n('overallWidth'), n('overallDepth'), n('webThickness'), n('flangeThickness')];
			if (!b || !h || !tw || !tf) {
				return undefined;
			}
			const [x, y, w] = [b / 2, h / 2, tw / 2];
			return { kind: 'polygon', points: [[-x, -y], [x, -y], [x, -y + tf], [w, -y + tf], [w, y - tf], [x, y - tf], [x, y], [-x, y], [-x, y - tf], [-w, y - tf], [-w, -y + tf], [-x, -y + tf]] };
		}
		case 'T': {
			const [b, h, tw, tf] = [n('flangeWidth'), n('depth'), n('webThickness'), n('flangeThickness')];
			if (!b || !h || !tw || !tf) {
				return undefined;
			}
			const [x, y, w] = [b / 2, h / 2, tw / 2];
			return { kind: 'polygon', points: [[-w, -y], [w, -y], [w, y - tf], [x, y - tf], [x, y], [-x, y], [-x, y - tf], [-w, y - tf]] };
		}
		case 'L': {
			const [b, h, t] = [n('width'), n('depth'), n('thickness')];
			if (!b || !h || !t) {
				return undefined;
			}
			const [x, y] = [b / 2, h / 2];
			return { kind: 'polygon', points: [[-x, -y], [x, -y], [x, -y + t], [-x + t, -y + t], [-x + t, y], [-x, y]] };
		}
		case 'U': {
			const [b, h, tw, tf] = [n('flangeWidth'), n('depth'), n('webThickness'), n('flangeThickness')];
			if (!b || !h || !tw || !tf) {
				return undefined;
			}
			const [x, y] = [b / 2, h / 2];
			return { kind: 'polygon', points: [[-x, -y], [x, -y], [x, -y + tf], [-x + tw, -y + tf], [-x + tw, y - tf], [x, y - tf], [x, y], [-x, y]] };
		}
	}
	return undefined;
}

/** Width of a member's profile across its axis in plan. */
function profileWidth(profile: Json): number | undefined {
	const outline = profileOutline(profile);
	if (!outline) {
		return undefined;
	}
	if (outline.kind === 'circle') {
		return 2 * outline.radius;
	}
	const xs = outline.points.map(p => p[0]);
	return Math.max(...xs) - Math.min(...xs);
}

/**
 * The story whose plan shows `selection`: the story itself, or a member's story (the top story
 * of columns and walls, which plans show from the story they rise to).
 */
export function storyOfSelection(layout: unknown, selection: ModelSelection): string | undefined {
	if (selection.kind === 'story') {
		return selection.id;
	}
	if (selection.kind !== 'member' || !isObject(layout)) {
		return undefined;
	}
	const member = list(layout[selection.group]).find(m => m.id === selection.id);
	const story = member && (selection.group === 'columns' || selection.group === 'walls' ? member.top : member.story);
	return typeof story === 'string' ? story : undefined;
}

/** Grid line positions by label, per axis. */
export function gridsOf(layout: unknown): { readonly x: ReadonlyMap<string, number>; readonly y: ReadonlyMap<string, number> } {
	const grids = isObject(layout) && isObject(layout.grids) ? layout.grids : {};
	const lines = (axis: 'x' | 'y') => new Map(list(grids[axis])
		.filter(g => typeof g.label === 'string' && num(g.position) !== undefined)
		.map(g => [g.label as string, g.position as number]));
	return { x: lines('x'), y: lines('y') };
}

/**
 * The size of an object type in mm, as drawings give it: "300×500" (width × depth), "Ø500",
 * "t 150" for a slab or wall, "2000×1500" for a footing; undefined when it has none.
 */
export function sectionLabel(type: Json | undefined): string | undefined {
	if (!type) {
		return undefined;
	}
	const profile = isObject(type.profile) ? type.profile : undefined;
	const n = (key: string) => profile ? num(profile[key]) : undefined;
	if (profile?.shape === 'rectangle' && n('xDim') && n('yDim')) {
		return `${n('xDim')}×${n('yDim')}`;
	}
	if ((profile?.shape === 'circle' || profile?.shape === 'circleHollow') && n('radius')) {
		return `Ø${2 * n('radius')!}`;
	}
	if (num(type.thickness)) {
		return `t ${num(type.thickness)}`;
	}
	return num(type.length) && num(type.width) ? `${num(type.length)}×${num(type.width)}` : undefined;
}

/** A label's extent on the plan: centred on its position, about 0.84 text heights per character. */
interface LabelBox { readonly x0: number; readonly x1: number; readonly y0: number; readonly y1: number }

function labelBox(position: CadPoint, value: string): LabelBox {
	const [halfWidth, halfHeight] = [value.length * LABEL_TEXT * 0.42, LABEL_TEXT * 0.6];
	return { x0: position[0] - halfWidth, x1: position[0] + halfWidth, y0: position[1] - halfHeight, y1: position[1] + halfHeight };
}

function boxesOverlap(a: LabelBox, b: LabelBox): boolean {
	return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

/** "B5 300×500", "C1 Ø500": a label with its section's size in mm, when the type has one. */
function withSize(label: string, type: Json | undefined): string {
	const size = type && isObject(type.profile) ? sectionLabel(type) : undefined;
	return size ? `${label} ${size}` : label;
}

/**
 * Why slab `id` (corners `points`) may be wrong: nothing under it at all (no beam or wall along
 * an edge, no column under it), or a beam or wall across it, where the slab is not split.
 */
function slabWarnings(id: string, points: readonly CadPoint[], supports: readonly ISupport[], columns: readonly CadPoint[]): { readonly warnings: string[]; readonly across?: string } {
	const onEdge = (p: CadPoint) => points.some((q, i) => distanceToSegment(p, q, points[(i + 1) % points.length]) <= 1);
	const warnings: string[] = [];
	const edgeHeld = points.some((q, i) => {
		const r = points[(i + 1) % points.length];
		const mid: CadPoint = [(q[0] + r[0]) / 2, (q[1] + r[1]) / 2];
		// A beam or wall along the edge (not one that only ends on it).
		const along = ([a, b]: readonly [CadPoint, CadPoint]) => Math.abs((b[0] - a[0]) * (r[1] - q[1]) - (b[1] - a[1]) * (r[0] - q[0])) <= 1e-6 * Math.hypot(b[0] - a[0], b[1] - a[1]) * Math.hypot(r[0] - q[0], r[1] - q[1]);
		return supports.some(support => along(support.line) && distanceToSegment(mid, support.line[0], support.line[1]) <= 1);
	});
	if (!edgeHeld && !columns.some(c => insidePolygon(c, points) || onEdge(c))) {
		warnings.push(localize('plan.slabUnsupported', "{0}: no beam, wall or column supports it; place beams along its edges or columns under it.", id));
	}
	// A partition (a non-structural wall) stands on the slab: it is a load, not a support to split at.
	const across = supports.find(({ line: [a, b], partition }) => !partition && [0.25, 0.5, 0.75].some(t => {
		const p: CadPoint = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
		return insidePolygon(p, points) && !onEdge(p);
	}));
	if (across) {
		warnings.push(localize('plan.slabCrossed2', "{0}: {1} runs across it, but the slab is not split there; split it along {1} (Properties, Warnings).", id, across.label));
	}
	return { warnings, across: across?.id };
}

/** What a slab may rest on: a beam on the story or a wall rising to it. */
interface ISupport {
	readonly id: string;
	readonly label: string;
	readonly line: readonly [CadPoint, CadPoint];
	/** A non-structural wall (a partition): not split at. */
	readonly partition: boolean;
}

/**
 * The plan of story `storyId`: grids with bubbles, the columns and walls rising to it (plans
 * look down from just below the level), and the beams, slabs and footings at its level; under
 * them, the site's plot and buildable envelope when `underlay` gives them.
 */
export function floorPlanDrawing(layout: unknown, objects: unknown, storyId: string, underlay?: IPlotUnderlay): IFloorPlan {
	const model = isObject(layout) ? layout : {};
	const { x: xLines, y: yLines } = gridsOf(model);
	const elevation = new Map(storiesOf(model).map(s => [s.id, s.elevation]));
	const level = elevation.get(storyId);
	const types = new Map(list(isObject(objects) ? objects.objects : undefined).filter(o => typeof o.id === 'string').map(o => [o.id as string, o]));

	const entities: CadEntitySpec[] = plotEntities(underlay);
	const problems: string[] = [];
	const warnings: string[] = [];
	const members: IMemberShape[] = [];
	const shape = (group: MemberGroup, member: Json, outline: IMemberShape['outline']) => {
		if (typeof member.id === 'string') {
			members.push({ group, id: member.id, outline });
		}
	};

	// ── grids ──
	const xs = [...xLines.values()];
	const ys = [...yLines.values()];
	const [minX, maxX] = xs.length ? [Math.min(...xs), Math.max(...xs)] : [0, 0];
	const [minY, maxY] = ys.length ? [Math.min(...ys), Math.max(...ys)] : [0, 0];
	/** The grid bubbles, which member labels keep clear of too. */
	const bubbles: LabelBox[] = [];
	const bubble = (label: string, center: CadPoint) => {
		bubbles.push({ x0: center[0] - BUBBLE_RADIUS, x1: center[0] + BUBBLE_RADIUS, y0: center[1] - BUBBLE_RADIUS, y1: center[1] + BUBBLE_RADIUS });
		entities.push({ kind: 'circle', layer: FLOOR_PLAN_LAYERS.gridLabels, center, radius: BUBBLE_RADIUS });
		entities.push({ kind: 'text', layer: FLOOR_PLAN_LAYERS.gridLabels, position: center, height: BUBBLE_TEXT, text: label });
	};
	for (const [label, x] of xLines) {
		const [y0, y1] = [minY - GRID_OVERRUN, maxY + GRID_OVERRUN];
		entities.push({ kind: 'line', layer: FLOOR_PLAN_LAYERS.grid, start: [x, y0], end: [x, y1], linetypeScale: GRID_LINETYPE_SCALE });
		bubble(label, [x, y0 - BUBBLE_RADIUS]);
		bubble(label, [x, y1 + BUBBLE_RADIUS]);
	}
	for (const [label, y] of yLines) {
		const [x0, x1] = [minX - GRID_OVERRUN, maxX + GRID_OVERRUN];
		entities.push({ kind: 'line', layer: FLOOR_PLAN_LAYERS.grid, start: [x0, y], end: [x1, y], linetypeScale: GRID_LINETYPE_SCALE });
		bubble(label, [x0 - BUBBLE_RADIUS, y]);
		bubble(label, [x1 + BUBBLE_RADIUS, y]);
	}
	if (level === undefined) {
		return { drawing: { layers: LAYERS, entities }, members, problems, warnings };
	}

	// ── members ──
	const resolve = (value: unknown): CadPoint | undefined => {
		const p = isObject(value) ? value as unknown as IGridPoint : undefined;
		const x = p && xLines.get(p.x);
		const y = p && yLines.get(p.y);
		return x === undefined || y === undefined ? undefined : [x + (num(p!.dx) ?? 0), y + (num(p!.dy) ?? 0)];
	};
	const point = (member: Json, value: unknown): CadPoint | undefined => {
		const at = resolve(value);
		if (!at) {
			const p = isObject(value) ? value : undefined;
			problems.push(`${member.id}: grid point ${p ? `${p.x}-${p.y}` : '?'} does not exist`);
		}
		return at;
	};
	const typeOf = (member: Json): Json | undefined => {
		const type = typeof member.type === 'string' ? types.get(member.type) : undefined;
		if (!type) {
			problems.push(`${member.id}: unknown object type '${member.type}'`);
		}
		return type;
	};
	/** A member's label on the plan: one per place up the building (see {@link planLabel}). */
	const labelOf = (member: Json) => typeof member.id === 'string' ? planLabel(model, member.id) : '?';
	/** The boxes of the labels drawn so far, which later labels keep clear of. */
	const placed: LabelBox[] = [...bubbles];
	const text = (position: CadPoint, value: string) => {
		entities.push({ kind: 'text', layer: FLOOR_PLAN_LAYERS.labels, position, height: LABEL_TEXT, text: value });
		placed.push(labelBox(position, value));
	};
	const free = (position: CadPoint, value: string) => {
		const box = labelBox(position, value);
		return placed.every(other => !boxesOverlap(box, other));
	};
	/**
	 * Where a line member's label goes: beside it (above, left of a vertical one) at its middle,
	 * else on its other side, else further along it, clear of the labels and bubbles placed so far.
	 */
	const besideLine = (start: CadPoint, end: CadPoint, width: number, name: string, normal: CadPoint): CadPoint => {
		let [nx, ny] = normal;
		if (ny < -1e-9 || (Math.abs(ny) <= 1e-9 && nx > 0)) {
			[nx, ny] = [-nx, -ny];
		}
		const offset = width / 2 + LABEL_TEXT * 0.9 + Math.abs(nx) * name.length * LABEL_TEXT * 0.32;
		const candidates = [0.5, 0.3, 0.7].flatMap(t => [1, -1].map(side => {
			const at: CadPoint = [start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1])];
			return [at[0] + side * nx * offset, at[1] + side * ny * offset] as CadPoint;
		}));
		return candidates.find(c => free(c, name)) ?? candidates[0];
	};
	/** Columns and walls cross a plan when they start below the level and reach it. */
	const spans = (member: Json) => {
		const base = elevation.get(member.base as string);
		const top = elevation.get(member.top as string);
		return base !== undefined && top !== undefined && base < level && level <= top;
	};
	const band = (layer: string, start: CadPoint, end: CadPoint, width: number, linetypeScale?: number): CadPoint[] | undefined => {
		const [dx, dy] = [end[0] - start[0], end[1] - start[1]];
		const length = Math.hypot(dx, dy);
		if (!length) {
			return undefined;
		}
		const [nx, ny] = [-dy / length * width / 2, dx / length * width / 2];
		const points: CadPoint[] = [[start[0] + nx, start[1] + ny], [end[0] + nx, end[1] + ny], [end[0] - nx, end[1] - ny], [start[0] - nx, start[1] - ny]];
		entities.push({ kind: 'polyline', layer, closed: true, linetypeScale, points });
		return points;
	};

	// The beams on the story and the walls rising to it: what slabs rest on, and what labels keep clear of.
	const beams = list(model.beams).filter(b => b.story === storyId);
	const walls = list(model.walls).filter(spans);
	const supports: ISupport[] = [];
	for (const member of [...beams, ...walls]) {
		const [start, end] = [resolve(member.start), resolve(member.end)];
		const type = typeof member.type === 'string' ? types.get(member.type) : undefined;
		if (start && end && typeof member.id === 'string') {
			supports.push({ id: member.id, label: labelOf(member), line: [start, end], partition: walls.includes(member) && type?.structural === false });
		}
	}
	const fixes: ISlabSplit[] = [];
	const columnPoints = list(model.columns).filter(spans).map(c => resolve(c.at)).filter((p): p is CadPoint => !!p);
	const clear = (p: CadPoint) => supports.every(({ line: [a, b] }) => distanceToSegment(p, a, b) > LABEL_TEXT * 1.2);

	/** Slab labels go last: they move about the slab's centre, off the beams and their labels. */
	const slabLabels: { readonly center: CadPoint; readonly name: string }[] = [];
	for (const slab of list(model.slabs).filter(s => s.story === storyId)) {
		const type = typeOf(slab);
		const corners = list(slab.boundary).map(c => point(slab, c));
		if (!type || corners.length < 3 || corners.some(c => !c)) {
			continue;
		}
		const points = corners as CadPoint[];
		entities.push({ kind: 'polyline', layer: FLOOR_PLAN_LAYERS.slabs, points, closed: true });
		shape('slabs', slab, { kind: 'polygon', points });
		const thickness = num(type.thickness);
		slabLabels.push({ center: centroid(points)!, name: thickness ? `${labelOf(slab)} (${thickness})` : labelOf(slab) });
		const checked = slabWarnings(labelOf(slab), points, supports, columnPoints);
		warnings.push(...checked.warnings);
		if (checked.across && typeof slab.id === 'string') {
			const member = supports.find(s => s.id === checked.across)!;
			fixes.push({ slab: slab.id, member: member.id, label: localize('plan.splitSlab', "Split {0} along {1}", labelOf(slab), member.label) });
		}
	}
	for (const beam of beams) {
		const type = typeOf(beam);
		const [start, end] = [point(beam, beam.start), point(beam, beam.end)];
		const width = type && isObject(type.profile) ? profileWidth(type.profile) : undefined;
		if (!start || !end || !width) {
			continue;
		}
		const outline = band(FLOOR_PLAN_LAYERS.beams, start, end, width, BEAM_LINETYPE_SCALE);
		if (!outline) {
			continue;
		}
		shape('beams', beam, { kind: 'polygon', points: outline });
		// Beside the beam (above it, left of a vertical one), not struck through by its lines.
		const name = withSize(labelOf(beam), type);
		const length = Math.hypot(end[0] - start[0], end[1] - start[1]);
		let [nx, ny] = [-(end[1] - start[1]) / length, (end[0] - start[0]) / length];
		if (ny < -1e-9 || (Math.abs(ny) <= 1e-9 && nx > 0)) {
			[nx, ny] = [-nx, -ny];
		}
		text(besideLine(start, end, width, name, [nx, ny]), name);
	}
	// At the centre, moved up or down off a beam that crosses it and off the beams' labels.
	for (const { center, name } of slabLabels) {
		const candidates = [0, 1.5, -1.5, 3, -3, 4.5, -4.5].map(k => [center[0], center[1] + k * LABEL_TEXT] as CadPoint).filter(clear);
		text(candidates.find(c => free(c, name)) ?? candidates[0] ?? center, name);
	}
	for (const wall of walls) {
		const type = typeOf(wall);
		const [start, end] = [point(wall, wall.start), point(wall, wall.end)];
		const thickness = type && num(type.thickness);
		if (!start || !end || !thickness) {
			continue;
		}
		// A partition (non-structural) is drawn dashed and grey: it is weight, not structure.
		const partition = type?.structural === false;
		const outline = band(partition ? FLOOR_PLAN_LAYERS.partitions : FLOOR_PLAN_LAYERS.walls, start, end, thickness, partition ? BEAM_LINETYPE_SCALE : undefined);
		if (outline) {
			shape('walls', wall, { kind: 'polygon', points: outline });
			const name = partition ? localize('plan.partitionLabel', "{0} partition t {1}", labelOf(wall), thickness) : `${labelOf(wall)} t ${thickness}`;
			const length = Math.hypot(end[0] - start[0], end[1] - start[1]);
			text(besideLine(start, end, thickness, name, [-(end[1] - start[1]) / length, (end[0] - start[0]) / length]), name);
		}
	}
	for (const column of list(model.columns).filter(spans)) {
		const type = typeOf(column);
		const at = point(column, column.at);
		const outline = type && isObject(type.profile) ? profileOutline(type.profile) : undefined;
		if (!at || !outline) {
			continue;
		}
		let corner: CadPoint;
		if (outline.kind === 'circle') {
			entities.push({ kind: 'circle', layer: FLOOR_PLAN_LAYERS.columns, center: at, radius: outline.radius });
			shape('columns', column, { kind: 'circle', center: at, radius: outline.radius });
			corner = [at[0] + outline.radius, at[1] + outline.radius];
		} else {
			const points = translate(outline.points, at, num(column.rotation) ?? 0);
			entities.push({ kind: 'polyline', layer: FLOOR_PLAN_LAYERS.columns, points, closed: true });
			shape('columns', column, { kind: 'polygon', points });
			corner = [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
		}
		// Above and right of the column, clear of the grid lines through it; another corner when a
		// beam's label is already there.
		const name = withSize(labelOf(column), type);
		const [halfWidth, low] = [corner[0] - at[0], corner[1] - at[1]];
		const dx = halfWidth + LABEL_TEXT * 0.4 + name.length * LABEL_TEXT * 0.32;
		const dy = low + LABEL_TEXT * 0.9;
		const candidates: CadPoint[] = [[at[0] + dx, at[1] + dy], [at[0] + dx, at[1] - dy], [at[0] - dx, at[1] + dy], [at[0] - dx, at[1] - dy]];
		text(candidates.find(c => free(c, name)) ?? candidates[0], name);
	}
	for (const footing of list(model.footings).filter(f => f.story === storyId)) {
		const type = typeOf(footing);
		const at = point(footing, footing.at);
		const [length, width] = [type && num(type.length), type && num(type.width)];
		if (!at || !length || !width) {
			continue;
		}
		const points = translate(rectangle(length, width), at, num(footing.rotation) ?? 0);
		entities.push({ kind: 'polyline', layer: FLOOR_PLAN_LAYERS.footings, points, closed: true });
		shape('footings', footing, { kind: 'polygon', points });
		text(at, labelOf(footing));
	}
	return { drawing: { layers: LAYERS, entities }, members, problems, warnings, fixes };
}

/**
 * `dxf` without the entities of its ENTITIES section on `layers`: a plan exported from the floor
 * plan (11 Exports) attached as an underlay brings the plan's own grids, labels and loads, which
 * the live plan draws already (doubled, and the labels of another story's members).
 */
export function withoutLayers(dxf: string, layers: ReadonlySet<string>): string {
	const lines = dxf.split(/\r?\n/);
	const out: string[] = [];
	let inEntities = false;
	let entity: string[] | undefined;
	let drop = false;
	const flush = () => {
		if (entity && !drop) {
			out.push(...entity);
		}
		entity = undefined;
		drop = false;
	};
	for (let i = 0; i + 1 < lines.length; i += 2) {
		const [code, value] = [lines[i].trim(), lines[i + 1]];
		if (code === '0') {
			flush();
			if (value.trim() === 'ENDSEC') {
				inEntities = false;
			}
			if (inEntities) {
				entity = [lines[i], value];
				continue;
			}
		} else if (code === '2' && value.trim() === 'ENTITIES' && out[out.length - 1]?.trim() === 'SECTION') {
			inEntities = true;
		} else if (entity) {
			entity.push(lines[i], value);
			if (code === '8' && layers.has(value.trim())) {
				drop = true;
			}
			continue;
		}
		out.push(lines[i], value);
	}
	flush();
	return out.join('\n');
}

/** The layers of the floor plan's own drawing that an exported plan used as an underlay leaves out. */
export const PLAN_ANNOTATION_LAYERS: ReadonlySet<string> = new Set([FLOOR_PLAN_LAYERS.grid, FLOOR_PLAN_LAYERS.gridLabels, FLOOR_PLAN_LAYERS.labels, 'S-LOAD', 'S-LOAD-IDEN']);
