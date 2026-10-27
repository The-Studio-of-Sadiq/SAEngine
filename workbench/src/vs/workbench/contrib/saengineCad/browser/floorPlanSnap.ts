/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { gridsOf } from './floorPlanDrawing.js';
import { resolvePoint } from './floorPlanEdits.js';

/*
 * Object snaps for the ends of beams and walls, as in AutoCAD: grid intersections, member ends,
 * midpoints, intersections, the perpendicular from the last point, the nearest point on a member,
 * grid lines, else a free point. A beam may so end on another beam (a secondary beam) or in the
 * air (a cantilever). Points on a member are stored to 0.001 mm (see `anchor`), so the analysis
 * model's mesh joins the two members there and splits the supporting one.
 */

type Json = { readonly [key: string]: unknown };

export type SnapKind = 'node' | 'endpoint' | 'midpoint' | 'intersection' | 'perpendicular' | 'nearest' | 'gridLine' | 'free';

export interface ISnap {
	readonly kind: SnapKind;
	readonly point: CadPoint;
	/** The member the point is on (end, midpoint, perpendicular, nearest), for the status line. */
	readonly on?: string;
	/** Whether the point lies on a member and must be stored exactly, not rounded to the mm. */
	readonly exact: boolean;
}

/** A straight member on the plan a point can snap to. */
export interface ISnapSegment {
	readonly id: string;
	readonly start: CadPoint;
	readonly end: CadPoint;
}

export const SNAP_NAMES: { readonly [kind in SnapKind]: string } = {
	node: localize('snap.node', "Grid intersection"),
	endpoint: localize('snap.endpoint', "Endpoint"),
	midpoint: localize('snap.midpoint', "Midpoint"),
	intersection: localize('snap.intersection', "Intersection"),
	perpendicular: localize('snap.perpendicular', "Perpendicular"),
	nearest: localize('snap.nearest', "Nearest"),
	gridLine: localize('snap.gridLine', "On grid line"),
	free: localize('snap.free', "Free point"),
};

/** The order point snaps win in when two are equally near (AutoCAD's markers take the nearest). */
const PRIORITY: readonly SnapKind[] = ['node', 'endpoint', 'intersection', 'midpoint', 'perpendicular'];

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isObject) : [];
}

const distance = (a: CadPoint, b: CadPoint) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** The parameter (0 at the start, 1 at the end) of the point on `segment` nearest to `p`, unclamped. */
function parameter(p: CadPoint, { start, end }: ISnapSegment): number {
	const [dx, dy] = [end[0] - start[0], end[1] - start[1]];
	const length2 = dx * dx + dy * dy;
	return length2 ? ((p[0] - start[0]) * dx + (p[1] - start[1]) * dy) / length2 : 0;
}

function at({ start, end }: ISnapSegment, t: number): CadPoint {
	return [start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1])];
}

/** Where two segments cross, inside both, if they do. */
function crossing(a: ISnapSegment, b: ISnapSegment): CadPoint | undefined {
	const [rx, ry] = [a.end[0] - a.start[0], a.end[1] - a.start[1]];
	const [sx, sy] = [b.end[0] - b.start[0], b.end[1] - b.start[1]];
	const denominator = rx * sy - ry * sx;
	if (Math.abs(denominator) < 1e-9) {
		return undefined;
	}
	const [qx, qy] = [b.start[0] - a.start[0], b.start[1] - a.start[1]];
	const t = (qx * sy - qy * sx) / denominator;
	const u = (qx * ry - qy * rx) / denominator;
	return t >= -1e-9 && t <= 1 + 1e-9 && u >= -1e-9 && u <= 1 + 1e-9 ? at(a, t) : undefined;
}

/**
 * The beams on `story` and the walls rising to it, as segments between their resolved points:
 * what a beam end on that story can rest on.
 */
export function snapSegments(layout: unknown, story: string): ISnapSegment[] {
	const model = isObject(layout) ? layout : {};
	const segments: ISnapSegment[] = [];
	const add = (member: Json) => {
		const start = resolvePoint(model, member.start);
		const end = resolvePoint(model, member.end);
		if (typeof member.id === 'string' && start && end && distance(start, end) > 0) {
			segments.push({ id: member.id, start, end });
		}
	};
	list(model.beams).filter(b => b.story === story).forEach(add);
	list(model.walls).filter(w => w.top === story).forEach(add);
	return segments;
}

/** The columns rising to `story`, where they are: beam ends snap to them as endpoints. */
function columnPoints(layout: unknown, story: string): { readonly id: string; readonly point: CadPoint }[] {
	const model = isObject(layout) ? layout : {};
	const elevation = new Map(storiesOf(model).map(s => [s.id, s.elevation]));
	const level = elevation.get(story);
	if (level === undefined) {
		return [];
	}
	return list(model.columns).flatMap(c => {
		const base = elevation.get(c.base as string);
		const top = elevation.get(c.top as string);
		const point = resolvePoint(model, c.at);
		return typeof c.id === 'string' && point && base !== undefined && top !== undefined && base < level && level <= top ? [{ id: c.id, point }] : [];
	});
}

/**
 * Where a beam or wall end clicked at `point` on `story` lands. Within `tolerance` of it, the
 * nearest of: a grid intersection, a column, a member's end or midpoint, an intersection of two
 * members or of a member and a grid line, and (with `from`, the other end) the perpendicular from
 * `from` onto a member. Else the nearest point on a member within `tolerance`, else a grid line
 * within half of it (on each axis), else the point itself to the mm.
 */
export function snapLinear(layout: unknown, story: string, point: CadPoint, tolerance: number, from?: CadPoint): ISnap {
	const segments = snapSegments(layout, story);
	const grids = gridsOf(layout);
	const candidates: ISnap[] = [];
	for (const [, x] of grids.x) {
		for (const [, y] of grids.y) {
			candidates.push({ kind: 'node', point: [x, y], exact: false });
		}
	}
	for (const column of columnPoints(layout, story)) {
		candidates.push({ kind: 'endpoint', point: column.point, on: column.id, exact: true });
	}
	const gridLines: ISnapSegment[] = [];
	const [xs, ys] = [[...grids.x.values()], [...grids.y.values()]];
	if (xs.length && ys.length) {
		const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
		const reach = Math.max(x1 - x0, y1 - y0, 1) * 10; // grid lines reach well past the grid
		xs.forEach(x => gridLines.push({ id: '', start: [x, y0 - reach], end: [x, y1 + reach] }));
		ys.forEach(y => gridLines.push({ id: '', start: [x0 - reach, y], end: [x1 + reach, y] }));
	}
	segments.forEach((segment, i) => {
		candidates.push({ kind: 'endpoint', point: segment.start, on: segment.id, exact: true });
		candidates.push({ kind: 'endpoint', point: segment.end, on: segment.id, exact: true });
		candidates.push({ kind: 'midpoint', point: at(segment, 0.5), on: segment.id, exact: true });
		for (const other of [...segments.slice(i + 1), ...gridLines]) {
			const cross = crossing(segment, other);
			if (cross) {
				candidates.push({ kind: 'intersection', point: cross, on: segment.id, exact: true });
			}
		}
		if (from) {
			const t = parameter(from, segment);
			const foot = at(segment, t);
			if (t > 1e-6 && t < 1 - 1e-6 && distance(foot, from) > 1) {
				candidates.push({ kind: 'perpendicular', point: foot, on: segment.id, exact: true });
			}
		}
	});
	let best: ISnap | undefined;
	let bestDistance = tolerance;
	for (const candidate of candidates) {
		const d = distance(candidate.point, point);
		const tie = best && Math.abs(d - bestDistance) < 1e-6 && PRIORITY.indexOf(candidate.kind) < PRIORITY.indexOf(best.kind);
		if (d < bestDistance - 1e-6 || tie || (!best && d <= tolerance)) {
			best = candidate;
			bestDistance = d;
		}
	}
	if (best) {
		return best;
	}
	let nearest: ISnap | undefined;
	let nearestDistance = tolerance;
	for (const segment of segments) {
		const foot = at(segment, Math.max(0, Math.min(1, parameter(point, segment))));
		const d = distance(foot, point);
		if (d <= nearestDistance) {
			nearest = { kind: 'nearest', point: foot, on: segment.id, exact: true };
			nearestDistance = d;
		}
	}
	if (nearest) {
		return nearest;
	}
	const line = (positions: readonly number[], value: number) => positions.find(p => Math.abs(p - value) <= tolerance / 2);
	const [gx, gy] = [line(xs, point[0]), line(ys, point[1])];
	if (gx !== undefined || gy !== undefined) {
		return { kind: 'gridLine', point: [gx ?? Math.round(point[0]), gy ?? Math.round(point[1])], exact: false };
	}
	return { kind: 'free', point: [Math.round(point[0]), Math.round(point[1])], exact: false };
}

/**
 * The end of a beam or wall from `start` given by typed text: a length in mm along `toward`
 * (the cursor; along an axis when within 5° of one, +x without a cursor), or "Δx, Δy" (also
 * AutoCAD's "@Δx,Δy").
 */
export function typedEnd(start: CadPoint, text: string, toward: CadPoint | undefined): CadPoint | undefined {
	const parts = text.trim().replace(/^@/, '').split(/[\s,;]+/).filter(Boolean).map(Number);
	if (parts.length === 2 && parts.every(Number.isFinite) && (parts[0] || parts[1])) {
		return [start[0] + parts[0], start[1] + parts[1]];
	}
	if (parts.length !== 1 || !Number.isFinite(parts[0]) || parts[0] <= 0) {
		return undefined;
	}
	let angle = toward && distance(toward, start) > 0 ? Math.atan2(toward[1] - start[1], toward[0] - start[0]) : 0;
	const quarter = Math.PI / 2;
	const axis = Math.round(angle / quarter) * quarter;
	if (Math.abs(angle - axis) <= 5 * Math.PI / 180) {
		angle = axis;
	}
	const round = (v: number) => Math.round(v * 1000) / 1000;
	return [round(start[0] + parts[0] * Math.cos(angle)), round(start[1] + parts[0] * Math.sin(angle))];
}

/**
 * Beam ends on `story` that stop just short of (or just past) another beam or wall, within
 * `reach` mm but not on it: they look connected on the plan, but the analysis model leaves them
 * apart (a cantilever on nothing). One line per end.
 */
export function nearMisses(layout: unknown, story: string, reach = 50): string[] {
	const segments = snapSegments(layout, story);
	const columns = columnPoints(layout, story);
	const grids = gridsOf(layout);
	const nodes: CadPoint[] = [...grids.x.values()].flatMap(x => [...grids.y.values()].map(y => [x, y] as CadPoint));
	const problems: string[] = [];
	const model = isObject(layout) ? layout : {};
	for (const beam of list(model.beams).filter(b => b.story === story)) {
		for (const key of ['start', 'end'] as const) {
			const end = resolvePoint(model, beam[key]);
			if (!end || columns.some(c => distance(c.point, end) <= 1) || nodes.some(n => distance(n, end) <= 1)) {
				continue;
			}
			for (const segment of segments) {
				if (segment.id === beam.id) {
					continue;
				}
				const foot = at(segment, Math.max(0, Math.min(1, parameter(end, segment))));
				const gap = distance(foot, end);
				if (gap > 0.01 && gap <= reach) {
					problems.push(localize('snap.nearMiss', "{0}: its {1} is {2} mm from {3} and not connected to it; move the end onto {3} (snap to it) or away from it.", String(beam.id), key === 'start' ? localize('snap.start', "start") : localize('snap.end', "end"), Math.round(gap * 10) / 10, segment.id));
					break;
				}
			}
		}
	}
	return problems;
}
