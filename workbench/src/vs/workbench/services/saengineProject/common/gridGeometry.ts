/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * The geometry of the floor plan's grid systems, for drawing and snapping: the main orthogonal
 * grid (`grids.x`, `grids.y`) and the other systems of `grids.systems` (rotated orthogonal,
 * radial, single angled lines). The engine has the same rules in
 * `saengine.library.grid_geometry`, which the building model, drawings and exporters use.
 *
 * A grid point names two lines and is where they cross: two straight lines at their crossing,
 * a ray and a ring at the ring's radius out along the ray, another line and a ring at the
 * crossing nearer the line's first point. Units: mm and degrees, anticlockwise from X.
 */

export type GridRole = 'x' | 'y' | 'ray' | 'ring' | 'line';
export type GridSystemKind = 'orthogonal' | 'radial' | 'lines';
type Point = [number, number];

/** One grid line of any system. */
export interface IGridAxis {
	readonly label: string;
	/** The system's id; '' for the main grid. */
	readonly system: string;
	readonly role: GridRole;
	/** A point on a straight line (its drawn start is at `extent[0]` from it); a ring's centre. */
	readonly origin: Point;
	/** Unit direction of a straight line. */
	readonly direction: Point;
	/** A ring's radius. */
	readonly radius: number;
	/** The angle [°] of the system's local x axis: a column on this line turns by it. */
	readonly orientation: number;
	/** Drawn extent along a straight line (parameters from `origin`). */
	readonly extent: Point;
	/** Where a ring's label bubble goes [°]. */
	readonly bubbleAngle: number;
}

/** How far grid lines run past the last crossing line [mm]. */
export const GRID_OVERRUN = 1500;

/** A grid point that names an unknown line or two lines that do not cross. */
export class GridError extends Error { }

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value);
const list = (value: unknown): Json[] => Array.isArray(value) ? value.filter(isObject) : [];
const num = (value: unknown): number | undefined => typeof value === 'number' && Number.isFinite(value) ? value : undefined;
const pair = (value: unknown): Point | undefined => Array.isArray(value) && num(value[0]) !== undefined && num(value[1]) !== undefined ? [value[0] as number, value[1] as number] : undefined;
const unit = (degrees: number): Point => [Math.cos(degrees * Math.PI / 180), Math.sin(degrees * Math.PI / 180)];

function span(values: readonly number[]): Point {
	return values.length ? [Math.min(...values) - GRID_OVERRUN, Math.max(...values) + GRID_OVERRUN] : [-GRID_OVERRUN, GRID_OVERRUN];
}

function lines(value: unknown): { label: string; position: number }[] {
	return list(value).filter(g => typeof g.label === 'string' && num(g.position) !== undefined).map(g => ({ label: g.label as string, position: g.position as number }));
}

function orthogonal(system: string, origin: Point, angle: number, xs: unknown, ys: unknown): IGridAxis[] {
	const [ex, ey] = [unit(angle), unit(angle + 90)];
	const [x, y] = [lines(xs), lines(ys)];
	const xSpan = span(y.map(g => g.position));
	const ySpan = span(x.map(g => g.position));
	return [
		...x.map((g): IGridAxis => ({ label: g.label, system, role: 'x', origin: [origin[0] + g.position * ex[0], origin[1] + g.position * ex[1]], direction: ey, radius: 0, orientation: angle, extent: xSpan, bubbleAngle: 0 })),
		...y.map((g): IGridAxis => ({ label: g.label, system, role: 'y', origin: [origin[0] + g.position * ey[0], origin[1] + g.position * ey[1]], direction: ex, radius: 0, orientation: angle, extent: ySpan, bubbleAngle: 0 })),
	];
}

/** The middle of the widest angle between neighbouring rays (where ring labels go). */
function largestGap(angles: readonly number[], fallback: number): number {
	if (!angles.length) {
		return fallback;
	}
	const ordered = angles.map(a => ((a % 360) + 360) % 360).sort((a, b) => a - b);
	let best = { gap: -1, start: 0 };
	ordered.forEach((a, i) => {
		const gap = ((ordered[(i + 1) % ordered.length] - a) % 360 + 360) % 360 || 360;
		if (gap > best.gap || (gap === best.gap && a > best.start)) {
			best = { gap, start: a };
		}
	});
	return best.start + best.gap / 2;
}

function radial(system: string, origin: Point, angle: number, rays: unknown, rings: unknown): IGridAxis[] {
	const rayList = list(rays).filter(r => typeof r.label === 'string' && num(r.angle) !== undefined);
	const ringList = list(rings).filter(r => typeof r.label === 'string' && (num(r.radius) ?? 0) > 0);
	const reach = (ringList.length ? Math.max(...ringList.map(r => r.radius as number)) : 0) + GRID_OVERRUN;
	const angles = rayList.map(r => angle + (r.angle as number));
	const labelAt = largestGap(angles, angle - 90);
	return [
		...rayList.map((r, i): IGridAxis => ({ label: r.label as string, system, role: 'ray', origin, direction: unit(angles[i]), radius: 0, orientation: angles[i], extent: [0, reach], bubbleAngle: 0 })),
		...ringList.map((r): IGridAxis => ({ label: r.label as string, system, role: 'ring', origin, direction: [0, 0], radius: r.radius as number, orientation: angle, extent: [0, 0], bubbleAngle: labelAt })),
	];
}

function free(system: string, items: unknown): IGridAxis[] {
	const out: IGridAxis[] = [];
	for (const g of list(items)) {
		const start = pair([g.x1, g.y1]);
		if (typeof g.label !== 'string' || !start) {
			continue;
		}
		// Through a second point, else `length` along `angle`.
		const angle = num(g.angle) ?? 0;
		const reach = num(g.length) ?? 20000;
		const end: Point = pair([g.x2, g.y2]) ?? [start[0] + reach * Math.cos(angle * Math.PI / 180), start[1] + reach * Math.sin(angle * Math.PI / 180)];
		const length = Math.hypot(end[0] - start[0], end[1] - start[1]);
		if (length <= 1e-9) {
			continue;
		}
		const direction: Point = [(end[0] - start[0]) / length, (end[1] - start[1]) / length];
		// Like an X line, whose direction is the local y axis: the local x axis is 90° before it.
		const orientation = Math.atan2(direction[1], direction[0]) * 180 / Math.PI - 90;
		out.push({ label: g.label, system, role: 'line', origin: start, direction, radius: 0, orientation, extent: [0, length], bubbleAngle: 0 });
	}
	return out;
}

/** Whether `axis` is a ring (a circle) rather than a straight line. */
export function isCircle(axis: IGridAxis): boolean {
	return axis.role === 'ring';
}

/** A straight line's drawn segment, from its start (its first bubble) to its end. */
export function segment(axis: IGridAxis): [Point, Point] {
	const at = (t: number): Point => [axis.origin[0] + t * axis.direction[0], axis.origin[1] + t * axis.direction[1]];
	return [at(axis.extent[0]), at(axis.extent[1])];
}

/** Whether a grid point names `b` first: Y before X and ring before ray are swapped. */
function swapped(a: IGridAxis, b: IGridAxis): boolean {
	return a.system === b.system && ((a.role === 'y' && b.role === 'x') || (a.role === 'ring' && b.role === 'ray'));
}

function within(axis: IGridAxis, [x, y]: Point): boolean {
	if (isCircle(axis)) {
		return true;
	}
	const t = (x - axis.origin[0]) * axis.direction[0] + (y - axis.origin[1]) * axis.direction[1];
	return axis.extent[0] - 1e-6 <= t && t <= axis.extent[1] + 1e-6;
}

function lineRing(line: IGridAxis, ring: IGridAxis, name: string): Point {
	const [ox, oy] = [line.origin[0] - ring.origin[0], line.origin[1] - ring.origin[1]];
	const [dx, dy] = line.direction;
	const b = ox * dx + oy * dy;
	const c = ox * ox + oy * oy - ring.radius * ring.radius;
	const disc = b * b - c;
	if (disc < -1e-6) {
		throw new GridError(`grid point ${name}: the line does not reach the ring`);
	}
	const root = Math.sqrt(Math.max(disc, 0));
	const roots = [-b - root, -b + root];
	let t: number;
	if (line.role === 'ray') {
		const ahead = roots.filter(r => r >= -1e-6);
		if (!ahead.length) {
			throw new GridError(`grid point ${name}: the ray does not reach the ring`);
		}
		t = Math.min(...ahead);
	} else {
		t = Math.abs(roots[0]) <= Math.abs(roots[1]) ? roots[0] : roots[1];
	}
	return [line.origin[0] + t * dx, line.origin[1] + t * dy];
}

/** The grid lines of a floor plan's `grids` (its JSON), by label. */
export class GridGeometry {
	readonly axes: readonly IGridAxis[];
	private readonly byLabel: ReadonlyMap<string, IGridAxis>;

	/** The geometry of the `grids` of the floor plan `layout`. */
	static ofPlan(layout: unknown): GridGeometry {
		return new GridGeometry(isObject(layout) ? layout.grids : undefined);
	}

	constructor(grids: unknown) {
		const g = isObject(grids) ? grids : {};
		const axes = orthogonal('', [0, 0], 0, g.x, g.y);
		for (const s of list(g.systems)) {
			const id = typeof s.id === 'string' ? s.id : '?';
			const origin: Point = [num(s.originX) ?? 0, num(s.originY) ?? 0];
			const angle = num(s.angle) ?? 0;
			if (s.kind === 'orthogonal') {
				axes.push(...orthogonal(id, origin, angle, s.x, s.y));
			} else if (s.kind === 'radial') {
				axes.push(...radial(id, origin, angle, s.rays, s.rings));
			} else if (s.kind === 'lines') {
				axes.push(...free(id, s.lines));
			}
		}
		this.axes = axes;
		this.byLabel = new Map(axes.map(a => [a.label, a]));
	}

	/** Only the main grid (the plan as it was before other grid systems). */
	get orthogonalOnly(): boolean {
		return this.axes.every(a => a.system === '');
	}

	axis(label: string): IGridAxis | undefined {
		return this.byLabel.get(label);
	}

	/** The angle [°] a column on line `label` turns by: its system's local x axis. */
	orientation(label: string): number {
		return this.byLabel.get(label)?.orientation ?? 0;
	}

	/** Where the lines `first` and `second` cross (a grid point's x and y). */
	intersection(first: string, second: string): Point {
		const a = this.byLabel.get(first);
		if (!a) {
			throw new GridError(`no X grid line '${first}'`);
		}
		const b = this.byLabel.get(second);
		if (!b) {
			throw new GridError(`no Y grid line '${second}'`);
		}
		if (isCircle(a) && isCircle(b)) {
			throw new GridError(`grid point ${first}-${second}: two rings are not a grid point`);
		}
		if (a.system === b.system && (swapped(a, b) || (a.role === b.role && a.role !== 'line'))) {
			throw new GridError(`grid point ${first}-${second}: name the ${a.role === 'ray' || a.role === 'ring' ? 'ray then the ring' : 'X line then the Y line'}`);
		}
		if (isCircle(a) || isCircle(b)) {
			return isCircle(a) ? lineRing(b, a, `${first}-${second}`) : lineRing(a, b, `${first}-${second}`);
		}
		const cross = a.direction[0] * b.direction[1] - a.direction[1] * b.direction[0];
		if (Math.abs(cross) < 1e-9) {
			throw new GridError(`grid lines ${first} and ${second} are parallel`);
		}
		const [wx, wy] = [b.origin[0] - a.origin[0], b.origin[1] - a.origin[1]];
		const t = (wx * b.direction[1] - wy * b.direction[0]) / cross;
		const s = (wx * a.direction[1] - wy * a.direction[0]) / cross;
		if ((a.role === 'ray' && t < -1e-6) || (b.role === 'ray' && s < -1e-6)) {
			throw new GridError(`grid lines ${first} and ${second} do not cross (behind a ray's centre)`);
		}
		return [a.origin[0] + t * a.direction[0], a.origin[1] + t * a.direction[1]];
	}

	/** {@link intersection}, or undefined when the lines do not make a grid point. */
	tryIntersection(first: string, second: string): Point | undefined {
		try {
			return this.intersection(first, second);
		} catch {
			return undefined;
		}
	}

	/** A grid point (`{x, y, dx, dy}`) in plan coordinates, offsets along the plan's axes. */
	point(p: unknown): Point | undefined {
		if (!isObject(p) || typeof p.x !== 'string' || typeof p.y !== 'string') {
			return undefined;
		}
		const at = this.tryIntersection(p.x, p.y);
		return at && [at[0] + (num(p.dx) ?? 0), at[1] + (num(p.dy) ?? 0)];
	}

	/** Every crossing of two grid lines inside their drawn extents, named as a grid point names it. */
	intersections(): { readonly first: string; readonly second: string; readonly at: Point }[] {
		const out: { first: string; second: string; at: Point }[] = [];
		this.axes.forEach((a, i) => {
			for (const b of this.axes.slice(i + 1)) {
				const [first, second] = swapped(a, b) ? [b, a] : [a, b];
				const at = this.tryIntersection(first.label, second.label);
				if (at && within(a, at) && within(b, at)) {
					out.push({ first: first.label, second: second.label, at });
				}
			}
		});
		return out;
	}

	/** The grid point (its two labels) at plan (x, y), or undefined off the grids. */
	find(x: number, y: number, tolerance = 50): { readonly first: string; readonly second: string } | undefined {
		let best: { d: number; first: string; second: string } | undefined;
		for (const { first, second, at } of this.intersections()) {
			const d = Math.hypot(at[0] - x, at[1] - y);
			if (d <= tolerance && (!best || d < best.d)) {
				best = { d, first, second };
			}
		}
		return best && { first: best.first, second: best.second };
	}
}
