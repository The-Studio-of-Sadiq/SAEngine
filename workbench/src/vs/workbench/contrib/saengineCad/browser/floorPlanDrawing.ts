/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEntitySpec, CadGeneratedDrawing, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
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
	slabs: 'S-SLAB',
	footings: 'S-FNDN',
	labels: 'S-ANNO-IDEN',
} as const;

const LAYERS: readonly CadLayerSpec[] = [
	{ name: FLOOR_PLAN_LAYERS.grid, color: 8, linetype: 'CENTER', description: 'Grid lines' },
	{ name: FLOOR_PLAN_LAYERS.gridLabels, color: 7, description: 'Grid bubbles and labels' },
	{ name: FLOOR_PLAN_LAYERS.columns, color: 4, description: 'Columns' },
	{ name: FLOOR_PLAN_LAYERS.beams, color: 3, linetype: 'DASHED', description: 'Beams (below the slab)' },
	{ name: FLOOR_PLAN_LAYERS.walls, color: 5, description: 'Walls' },
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


/** Where a drawn member is in plan, for picking it with the mouse. */
export interface IMemberShape {
	readonly group: MemberGroup;
	readonly id: string;
	readonly outline: { readonly kind: 'polygon'; readonly points: readonly CadPoint[] } | { readonly kind: 'circle'; readonly center: CadPoint; readonly radius: number };
}

export interface IFloorPlan {
	readonly drawing: CadGeneratedDrawing;
	/** The members drawn on the plan. */
	readonly members: readonly IMemberShape[];
	/** Members that could not be drawn, e.g. with an unknown object type or grid line. */
	readonly problems: readonly string[];
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

function centroid(points: readonly CadPoint[]): CadPoint {
	return [points.reduce((s, p) => s + p[0], 0) / points.length, points.reduce((s, p) => s + p[1], 0) / points.length];
}

/** The stories of the model, lowest first. */
export function storiesOf(layout: unknown): { readonly id: string; readonly name: string; readonly elevation: number }[] {
	return list(isObject(layout) ? layout.stories : undefined)
		.filter(s => typeof s.id === 'string' && num(s.elevation) !== undefined)
		.map(s => ({ id: s.id as string, name: typeof s.name === 'string' && s.name ? s.name : s.id as string, elevation: s.elevation as number }))
		.sort((a, b) => a.elevation - b.elevation);
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
 * The plan of story `storyId`: grids with bubbles, the columns and walls rising to it (plans
 * look down from just below the level), and the beams, slabs and footings at its level.
 */
export function floorPlanDrawing(layout: unknown, objects: unknown, storyId: string): IFloorPlan {
	const model = isObject(layout) ? layout : {};
	const { x: xLines, y: yLines } = gridsOf(model);
	const elevation = new Map(storiesOf(model).map(s => [s.id, s.elevation]));
	const level = elevation.get(storyId);
	const types = new Map(list(isObject(objects) ? objects.objects : undefined).filter(o => typeof o.id === 'string').map(o => [o.id as string, o]));

	const entities: CadEntitySpec[] = [];
	const problems: string[] = [];
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
	const bubble = (label: string, center: CadPoint) => {
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
		return { drawing: { layers: LAYERS, entities }, members, problems };
	}

	// ── members ──
	const point = (member: Json, value: unknown): CadPoint | undefined => {
		const p = isObject(value) ? value as unknown as IGridPoint : undefined;
		const x = p && xLines.get(p.x);
		const y = p && yLines.get(p.y);
		if (x === undefined || y === undefined) {
			problems.push(`${member.id}: grid point ${p ? `${p.x}-${p.y}` : '?'} does not exist`);
			return undefined;
		}
		return [x + (num(p!.dx) ?? 0), y + (num(p!.dy) ?? 0)];
	};
	const typeOf = (member: Json): Json | undefined => {
		const type = typeof member.type === 'string' ? types.get(member.type) : undefined;
		if (!type) {
			problems.push(`${member.id}: unknown object type '${member.type}'`);
		}
		return type;
	};
	const label = (member: Json, position: CadPoint) => {
		if (typeof member.id === 'string') {
			entities.push({ kind: 'text', layer: FLOOR_PLAN_LAYERS.labels, position, height: LABEL_TEXT, text: member.id });
		}
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
		entities.push({ kind: 'text', layer: FLOOR_PLAN_LAYERS.labels, position: centroid(points), height: LABEL_TEXT, text: thickness ? `${slab.id} (${thickness})` : String(slab.id) });
	}
	for (const beam of list(model.beams).filter(b => b.story === storyId)) {
		const type = typeOf(beam);
		const [start, end] = [point(beam, beam.start), point(beam, beam.end)];
		const width = type && isObject(type.profile) ? profileWidth(type.profile) : undefined;
		if (!start || !end || !width) {
			continue;
		}
		const outline = band(FLOOR_PLAN_LAYERS.beams, start, end, width, BEAM_LINETYPE_SCALE);
		if (outline) {
			shape('beams', beam, { kind: 'polygon', points: outline });
		}
		label(beam, centroid([start, end]));
	}
	for (const wall of list(model.walls).filter(spans)) {
		const type = typeOf(wall);
		const [start, end] = [point(wall, wall.start), point(wall, wall.end)];
		const thickness = type && num(type.thickness);
		if (!start || !end || !thickness) {
			continue;
		}
		const outline = band(FLOOR_PLAN_LAYERS.walls, start, end, thickness);
		if (outline) {
			shape('walls', wall, { kind: 'polygon', points: outline });
		}
	}
	for (const column of list(model.columns).filter(spans)) {
		const type = typeOf(column);
		const at = point(column, column.at);
		const outline = type && isObject(type.profile) ? profileOutline(type.profile) : undefined;
		if (!at || !outline) {
			continue;
		}
		if (outline.kind === 'circle') {
			entities.push({ kind: 'circle', layer: FLOOR_PLAN_LAYERS.columns, center: at, radius: outline.radius });
			shape('columns', column, { kind: 'circle', center: at, radius: outline.radius });
		} else {
			const points = translate(outline.points, at, num(column.rotation) ?? 0);
			entities.push({ kind: 'polyline', layer: FLOOR_PLAN_LAYERS.columns, points, closed: true });
			shape('columns', column, { kind: 'polygon', points });
		}
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
		label(footing, at);
	}
	return { drawing: { layers: LAYERS, entities }, members, problems };
}
