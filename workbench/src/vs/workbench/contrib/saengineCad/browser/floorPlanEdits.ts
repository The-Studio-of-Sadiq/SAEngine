/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { polygonArea } from '../../../../platform/saengine/common/geometry.js';
import { formatPoint, storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { distanceToSegment, gridsOf, ID_CHARS, IMemberShape, insidePolygon, MemberGroup, planLabel } from './floorPlanDrawing.js';

/*
 * Edits to the floor plan (`05 Floor Plan/floor-plan.json`): placing members on grid
 * intersections and bays, and removing them. Each edit returns a new model, or why it cannot be
 * made, so every edit keeps the model valid.
 */

type Json = { [key: string]: unknown };

export type PlacementTool = 'column' | 'beam' | 'wall' | 'slab' | 'footing';

export const TOOL_GROUP: { readonly [tool in PlacementTool]: MemberGroup } = {
	column: 'columns',
	beam: 'beams',
	wall: 'walls',
	slab: 'slabs',
	footing: 'footings',
};

/** Object kinds (from `04 Objects`) each tool places. */
export const TOOL_KINDS: { readonly [tool in PlacementTool]: readonly string[] } = {
	column: ['column'],
	beam: ['beam'],
	wall: ['wall'],
	slab: ['slab'],
	footing: ['footing', 'pileCap'],
};

/** Member ids are the group's letter and the next free number: C1, C2, B1, ... */
const ID_PREFIX: { readonly [group in MemberGroup]: string } = {
	columns: 'C',
	beams: 'B',
	walls: 'W',
	slabs: 'S',
	footings: 'F',
};

/** A grid intersection: the labels of its lines and where it is. */
export interface IGridNode {
	readonly x: string;
	readonly y: string;
	readonly point: CadPoint;
}

/** A bay: the region between two neighbouring lines on each axis. */
export interface IBay {
	readonly x: readonly [string, string];
	readonly y: readonly [string, string];
	readonly corners: readonly CadPoint[];
}

export type EditResult = { readonly ok: true; readonly layout: Json; readonly id: string } | { readonly ok: false; readonly error: string };

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function members(layout: Json, group: MemberGroup): Json[] {
	const list = layout[group];
	return Array.isArray(list) ? list.filter(isObject) : [];
}

function sameNode(value: unknown, node: Pick<IGridNode, 'x' | 'y'>): boolean {
	return isObject(value) && value.x === node.x && value.y === node.y && !value.dx && !value.dy;
}

function gridPoint(node: Pick<IGridNode, 'x' | 'y'>): Json {
	return { x: node.x, y: node.y };
}

/** The grid intersection within `tolerance` of `point`, if any (the nearest one). */
export function snapToGrid(layout: unknown, point: CadPoint, tolerance: number): IGridNode | undefined {
	const grids = gridsOf(layout);
	let best: IGridNode | undefined;
	let bestDistance = tolerance;
	for (const [x, px] of grids.x) {
		for (const [y, py] of grids.y) {
			const distance = Math.hypot(point[0] - px, point[1] - py);
			if (distance <= bestDistance) {
				best = { x, y, point: [px, py] };
				bestDistance = distance;
			}
		}
	}
	return best;
}

/** The bay `point` lies in, if it is inside the grid. */
export function bayAt(layout: unknown, point: CadPoint): IBay | undefined {
	const grids = gridsOf(layout);
	const span = (lines: ReadonlyMap<string, number>, value: number): [[string, number], [string, number]] | undefined => {
		const sorted = [...lines].sort((a, b) => a[1] - b[1]);
		for (let i = 1; i < sorted.length; i++) {
			if (sorted[i - 1][1] <= value && value <= sorted[i][1]) {
				return [sorted[i - 1], sorted[i]];
			}
		}
		return undefined;
	};
	const sx = span(grids.x, point[0]);
	const sy = span(grids.y, point[1]);
	if (!sx || !sy) {
		return undefined;
	}
	const [[x0, px0], [x1, px1]] = sx;
	const [[y0, py0], [y1, py1]] = sy;
	return { x: [x0, x1], y: [y0, y1], corners: [[px0, py0], [px1, py0], [px1, py1], [px0, py1]] };
}

export { distanceToSegment, insidePolygon } from './floorPlanDrawing.js';

const PICK_ORDER: readonly MemberGroup[] = ['columns', 'footings', 'walls', 'beams', 'slabs'];

/**
 * The member under `point`: inside its outline or within `tolerance` of it. Columns win over
 * footings, walls, beams and slabs, so the smaller member on top of a larger one can be picked.
 */
export function pickMember(shapes: readonly IMemberShape[], point: CadPoint, tolerance: number): IMemberShape | undefined {
	const hits = shapes.filter(({ outline }) => {
		if (outline.kind === 'circle') {
			return Math.hypot(point[0] - outline.center[0], point[1] - outline.center[1]) <= outline.radius + tolerance;
		}
		const points = outline.points;
		return insidePolygon(point, points) || points.some((p, i) => distanceToSegment(point, p, points[(i + 1) % points.length]) <= tolerance);
	});
	hits.sort((a, b) => PICK_ORDER.indexOf(a.group) - PICK_ORDER.indexOf(b.group));
	return hits[0];
}

/** The next free id of `group`: its letter and the lowest unused number. */
export function nextId(layout: Json, group: MemberGroup): string {
	const used = new Set(PICK_ORDER.flatMap(g => members(layout, g).map(m => m.id)));
	let n = 1;
	while (used.has(`${ID_PREFIX[group]}${n}`)) {
		n++;
	}
	return `${ID_PREFIX[group]}${n}`;
}

/**
 * The id of a copy of member `sourceId` on `story`: its plan label and the story ("B5-L3"),
 * else (taken) the next free id. Ids stay unique in the floor plan; the plan shows the label.
 */
export function copyId(layout: Json, group: MemberGroup, sourceId: string, story: string): string {
	const id = `${planLabel(layout, sourceId)}-${story.replace(ID_CHARS, '')}`;
	const used = PICK_ORDER.some(g => members(layout, g).some(m => m.id === id));
	return used || id.length > 64 ? nextId(layout, group) : id;
}

function append(layout: unknown, group: MemberGroup, member: Json): EditResult {
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	const id = nextId(next, group);
	next[group] = [...members(next, group), { id, ...member }];
	return { ok: true, layout: next, id };
}

const label = (node: Pick<IGridNode, 'x' | 'y'>) => `${node.x}-${node.y}`;

/** A column at `node`, from the story below `story` up to it. */
export function placeColumn(layout: unknown, type: string, story: string, node: IGridNode): EditResult {
	const stories = storiesOf(layout);
	const index = stories.findIndex(s => s.id === story);
	if (index < 1) {
		return { ok: false, error: localize('place.columnBase', "Columns rise to a story from the one below; choose a story above {0}.", stories[0]?.name ?? '') };
	}
	const base = stories[index - 1].id;
	const elevation = new Map(stories.map(s => [s.id, s.elevation]));
	const level = stories[index].elevation;
	const clash = members(layout as Json, 'columns').some(c => sameNode(c.at, node)
		&& (elevation.get(c.base as string) ?? Infinity) < level && level <= (elevation.get(c.top as string) ?? -Infinity));
	if (clash) {
		return { ok: false, error: localize('place.columnExists', "There is already a column at {0} on this story.", label(node)) };
	}
	return append(layout, 'columns', { type, at: gridPoint(node), base, top: story, rotation: 0 });
}

/** An end of a beam or wall to place: a point, stored exactly (to 0.001 mm) when it lies on a member. */
export interface ILinearEnd {
	readonly point: CadPoint;
	readonly exact?: boolean;
}

/**
 * A beam on `story`, or a wall from the story below up to it, between two points: grid
 * intersections, points on other members (a secondary beam) or free points (a cantilever).
 * Each end is stored against its nearest intersection (see {@link anchor}).
 */
export function placeLinear(layout: unknown, tool: 'beam' | 'wall', type: string, story: string, start: ILinearEnd, end: ILinearEnd): EditResult {
	if (Math.hypot(start.point[0] - end.point[0], start.point[1] - end.point[1]) < 1) {
		return { ok: false, error: localize('place.samePoint', "Choose a different end point.") };
	}
	const [from, to] = [anchor(layout, start.point, start.exact), anchor(layout, end.point, end.exact)];
	if (!from || !to) {
		return { ok: false, error: localize('edit.noGrid', "The floor plan needs grid lines on both axes first.") };
	}
	const group = TOOL_GROUP[tool];
	const near = (value: unknown, point: CadPoint) => {
		const p = resolvePoint(layout, value);
		return !!p && Math.hypot(p[0] - point[0], p[1] - point[1]) < 1;
	};
	const ends = (m: Json) => (near(m.start, start.point) && near(m.end, end.point)) || (near(m.start, end.point) && near(m.end, start.point));
	const [a, b] = [formatPoint(from), formatPoint(to)];
	if (tool === 'beam') {
		if (members(layout as Json, group).some(m => m.story === story && ends(m))) {
			return { ok: false, error: localize('place.beamExists', "There is already a beam from {0} to {1} on this story.", a, b) };
		}
		return append(layout, group, { type, story, start: from, end: to });
	}
	const stories = storiesOf(layout);
	const index = stories.findIndex(s => s.id === story);
	if (index < 1) {
		return { ok: false, error: localize('place.wallBase', "Walls rise to a story from the one below; choose a story above {0}.", stories[0]?.name ?? '') };
	}
	const elevation = new Map(stories.map(s => [s.id, s.elevation]));
	const level = stories[index].elevation;
	const clash = members(layout as Json, group).some(w => ends(w)
		&& (elevation.get(w.base as string) ?? Infinity) < level && level <= (elevation.get(w.top as string) ?? -Infinity));
	if (clash) {
		return { ok: false, error: localize('place.wallExists', "There is already a wall from {0} to {1} on this story.", a, b) };
	}
	return append(layout, group, { type, base: stories[index - 1].id, top: story, start: from, end: to });
}

/** A slab filling `bay` on `story`. */
export function placeSlab(layout: unknown, type: string, story: string, bay: IBay): EditResult {
	const corners = [{ x: bay.x[0], y: bay.y[0] }, { x: bay.x[1], y: bay.y[0] }, { x: bay.x[1], y: bay.y[1] }, { x: bay.x[0], y: bay.y[1] }];
	const key = (points: readonly unknown[]) => points.filter(isObject).map(p => `${p.x}-${p.y}`).sort().join(' ');
	const own = key(corners);
	if (members(layout as Json, 'slabs').some(s => s.story === story && Array.isArray(s.boundary) && key(s.boundary) === own)) {
		return { ok: false, error: localize('place.slabExists', "There is already a slab in this bay on this story.") };
	}
	return append(layout, 'slabs', { type, story, boundary: corners.map(gridPoint) });
}

/** A footing (or pile cap) at `node`, its top at `story`. */
export function placeFooting(layout: unknown, type: string, story: string, node: IGridNode): EditResult {
	if (members(layout as Json, 'footings').some(f => f.story === story && sameNode(f.at, node))) {
		return { ok: false, error: localize('place.footingExists', "There is already a footing at {0} on this story.", label(node)) };
	}
	return append(layout, 'footings', { type, story, at: gridPoint(node), rotation: 0 });
}

/** The model without member `id` of `group`. */
export function removeMember(layout: unknown, group: MemberGroup, id: string): Json {
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	next[group] = members(next, group).filter(m => m.id !== id);
	return next;
}

// ───────────────────────────── free points, move, rotate, polygon slabs ─────────────────────────────

/**
 * Where a click lands: on a grid intersection when within `tolerance` of one, else on a grid
 * line's coordinate for each axis within `tolerance` of a line, else where it is (to the mm).
 */
export function snapPoint(layout: unknown, point: CadPoint, tolerance: number): CadPoint {
	const node = snapToGrid(layout, point, tolerance);
	if (node) {
		return node.point;
	}
	const grids = gridsOf(layout);
	const near = (lines: ReadonlyMap<string, number>, value: number) => {
		let best: number | undefined;
		for (const position of lines.values()) {
			if (Math.abs(position - value) <= tolerance && (best === undefined || Math.abs(position - value) < Math.abs(best - value))) {
				best = position;
			}
		}
		return best ?? Math.round(value);
	};
	return [near(grids.x, point[0]), near(grids.y, point[1])];
}

/**
 * A point as the floor plan stores it: its nearest grid intersection plus an offset in whole
 * millimetres (no offset on the intersection itself), so it follows the grid when lines move.
 * An `exact` point (on another member) keeps 0.001 mm so that it stays on that member: the
 * analysis model joins two members only where they meet.
 */
export function anchor(layout: unknown, point: CadPoint, exact = false): Json | undefined {
	const node = snapToGrid(layout, point, Infinity);
	if (!node) {
		return undefined;
	}
	const round = (v: number) => (exact ? Math.round(v * 1000) / 1000 : Math.round(v)) || 0;
	const dx = round(point[0] - node.point[0]);
	const dy = round(point[1] - node.point[1]);
	return { x: node.x, y: node.y, ...(dx ? { dx } : {}), ...(dy ? { dy } : {}) };
}

/** Where a grid point of the floor plan is. */
export function resolvePoint(layout: unknown, value: unknown): CadPoint | undefined {
	if (!isObject(value)) {
		return undefined;
	}
	const grids = gridsOf(layout);
	const x = grids.x.get(value.x as string);
	const y = grids.y.get(value.y as string);
	return x === undefined || y === undefined ? undefined : [x + (Number(value.dx) || 0), y + (Number(value.dy) || 0)];
}

/** The point a member is moved by: a column's or footing's location, a line's start, a slab's first corner. */
export function basePoint(layout: unknown, group: MemberGroup, id: string): CadPoint | undefined {
	const member = isObject(layout) ? members(layout, group).find(m => m.id === id) : undefined;
	if (!member) {
		return undefined;
	}
	const first = group === 'columns' || group === 'footings' ? member.at
		: group === 'slabs' ? (Array.isArray(member.boundary) ? member.boundary[0] : undefined)
			: member.start;
	return resolvePoint(layout, first);
}

function changeMember(layout: unknown, group: MemberGroup, id: string, change: (member: Json) => Json | string): EditResult {
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	const list = members(next, group);
	const index = list.findIndex(m => m.id === id);
	if (index < 0) {
		return { ok: false, error: localize('edit.missing', "{0} no longer exists.", id) };
	}
	const changed = change(list[index]);
	if (typeof changed === 'string') {
		return { ok: false, error: changed };
	}
	list[index] = changed;
	next[group] = list;
	return { ok: true, layout: next, id };
}

/**
 * Moves a member by `delta` (mm). Each of its points is re-anchored to the grid intersection
 * nearest to where it lands, so a member moved onto another bay belongs to that bay's lines.
 */
export function moveMember(layout: unknown, group: MemberGroup, id: string, delta: CadPoint): EditResult {
	if (!delta[0] && !delta[1]) {
		return { ok: false, error: localize('edit.noMove', "Choose a different point to move to.") };
	}
	const move = (value: unknown): Json | undefined => {
		const at = resolvePoint(layout, value);
		return at && anchor(layout, [at[0] + delta[0], at[1] + delta[1]]);
	};
	return changeMember(layout, group, id, member => {
		const keys = group === 'columns' || group === 'footings' ? ['at'] : group === 'slabs' ? [] : ['start', 'end'];
		const result: Json = { ...member };
		for (const key of keys) {
			const moved = move(member[key]);
			if (!moved) {
				return localize('edit.badPoint', "{0} refers to a grid line that does not exist.", id);
			}
			result[key] = moved;
		}
		if (group === 'slabs') {
			const corners = (Array.isArray(member.boundary) ? member.boundary : []).map(move);
			if (corners.some(c => !c)) {
				return localize('edit.badPoint', "{0} refers to a grid line that does not exist.", id);
			}
			result.boundary = corners;
		}
		return result;
	});
}

/** Why a member other than a column does not rotate on the floor plan. */
export function notRotatableMessage(): string {
	return localize('edit.notRotatable', "Only columns rotate here; beams, walls and slabs follow their points, and footings turn in 9 Substructure.");
}

/** Sets the rotation of a column, in degrees (kept within 0–360). */
export function rotateMember(layout: unknown, group: MemberGroup, id: string, degrees: number): EditResult {
	if (group !== 'columns') {
		return { ok: false, error: group === 'footings' ? footingsOwnedMessage() : notRotatableMessage() };
	}
	if (!Number.isFinite(degrees)) {
		return { ok: false, error: localize('edit.badAngle', "Enter an angle in degrees.") };
	}
	const angle = Number((((degrees % 360) + 360) % 360).toFixed(3));
	return changeMember(layout, group, id, member => ({ ...member, rotation: angle }));
}

/** Why the floor plan does not change footings: since Part 9 they are placed and edited in 9 Substructure. */
export function footingsOwnedMessage(): string {
	return localize('edit.footingsOwned', "Footings are placed and edited in 9 Substructure.");
}

export type TypeEditResult =
	| { readonly ok: true; readonly layout: Json; readonly changed: readonly { readonly group: MemberGroup; readonly id: string }[]; readonly skipped: readonly string[] }
	| { readonly ok: false; readonly error: string };

/**
 * Gives the members `refs` object type `type` (of a kind their group places: see {@link TOOL_KINDS}).
 * Members that are gone, footings ({@link footingsOwnedMessage}) and members of a group that
 * `accepts` says cannot take the type are skipped and named; with none changed, the edit is
 * refused. Typical floors are not repeated here: see floorPlanTypical.ts.
 */
export function setMembersType(layout: unknown, refs: readonly { readonly group: MemberGroup; readonly id: string }[], type: string, accepts: (group: MemberGroup) => boolean = () => true): TypeEditResult {
	if (!refs.length) {
		return { ok: false, error: localize('edit.noMembers', "Select the members to change.") };
	}
	if (!type) {
		return { ok: false, error: localize('edit.noType', "Choose an object type.") };
	}
	const typeNone = localize('edit.typeNone', "{0} cannot be given to the selected members.", type);
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	const changed: { group: MemberGroup; id: string }[] = [];
	const skipped: string[] = [];
	let reason: string | undefined;
	for (const ref of refs) {
		const member = members(next, ref.group).find(m => m.id === ref.id);
		reason = !member ? localize('edit.missing', "{0} no longer exists.", ref.id)
			: ref.group === 'footings' ? footingsOwnedMessage()
				: !accepts(ref.group) ? typeNone
					: undefined;
		if (!member || reason) {
			skipped.push(ref.id);
			continue;
		}
		member.type = type;
		changed.push({ group: ref.group, id: ref.id });
	}
	if (!changed.length) {
		return { ok: false, error: refs.length === 1 && reason ? reason : typeNone };
	}
	return { ok: true, layout: next, changed, skipped };
}

/** Gives a member another object type: {@link setMembersType} for one member. */
export function changeMemberType(layout: unknown, group: MemberGroup, id: string, type: string): EditResult {
	const result = setMembersType(layout, [{ group, id }], type);
	return result.ok ? { ok: true, layout: result.layout, id } : result;
}

/** A slab bounded by `points` (in order around it) on `story`. */
export function placePolygonSlab(layout: unknown, type: string, story: string, points: readonly CadPoint[]): EditResult {
	const distinct = points.filter((p, i) => i === 0 || Math.hypot(p[0] - points[i - 1][0], p[1] - points[i - 1][1]) >= 1);
	if (distinct.length >= 2 && Math.hypot(distinct[0][0] - distinct[distinct.length - 1][0], distinct[0][1] - distinct[distinct.length - 1][1]) < 1) {
		distinct.pop();
	}
	if (distinct.length < 3 || polygonArea(distinct) < 1e4) {
		return { ok: false, error: localize('edit.polygonTooSmall', "A slab needs at least three corners around an area.") };
	}
	const boundary = distinct.map(p => anchor(layout, p));
	if (boundary.some(b => !b)) {
		return { ok: false, error: localize('edit.noGrid', "The floor plan needs grid lines on both axes first.") };
	}
	return append(layout, 'slabs', { type, story, boundary });
}

/** The part of polygon `points` on the left of the line `a`→`b` (`side` 1) or its right (-1). */
function clipToSide(points: readonly CadPoint[], a: CadPoint, b: CadPoint, side: 1 | -1): CadPoint[] {
	const s = (p: CadPoint) => side * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]));
	const out: CadPoint[] = [];
	for (let i = 0; i < points.length; i++) {
		const [p, q] = [points[i], points[(i + 1) % points.length]];
		const [sp, sq] = [s(p), s(q)];
		if (sp >= 0) {
			out.push(p);
		}
		if ((sp > 0 && sq < 0) || (sp < 0 && sq > 0)) {
			const t = sp / (sp - sq);
			out.push([p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]);
		}
	}
	return out;
}

/**
 * Slab `slabId` split in two along the line of beam or wall `memberId` (a member across it): the
 * slab keeps its id, type and properties on one side, a new slab like it takes the other. The
 * corners where the line cuts the edges are stored exactly, so both slabs meet on the member.
 */
export function splitSlab(layout: unknown, slabId: string, memberId: string): EditResult {
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	const slab = members(next, 'slabs').find(s => s.id === slabId);
	const member = [...members(next, 'beams'), ...members(next, 'walls')].find(m => m.id === memberId);
	const corners = slab && Array.isArray(slab.boundary) ? slab.boundary.map(c => resolvePoint(next, c)) : [];
	const [a, b] = member ? [resolvePoint(next, member.start), resolvePoint(next, member.end)] : [undefined, undefined];
	if (!slab || !member || !a || !b || corners.length < 3 || corners.some(c => !c)) {
		return { ok: false, error: localize('edit.splitMissing', "{0} or {1} no longer exists.", slabId, memberId) };
	}
	const halves = ([1, -1] as const).map(side => clipToSide(corners as CadPoint[], a, b, side));
	if (halves.some(h => h.length < 3 || Math.abs(polygonArea(h)) < 1e4)) {
		return { ok: false, error: localize('edit.splitNotAcross', "{0} does not run across {1}.", memberId, slabId) };
	}
	const boundary = (points: readonly CadPoint[]) => points.map(p => anchor(next, p, true)!);
	const other: Json = { ...slab, boundary: boundary(halves[1]) };
	delete other.id;
	slab.boundary = boundary(halves[0]);
	return append(next, 'slabs', other);
}
