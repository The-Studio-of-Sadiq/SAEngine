/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * The parts of an analysis model the FEM editor's View picker shows, as ETABS's plan and
 * elevation views and its isolated storeys: the levels and grid lines found in the model, and
 * which elements each view draws. Plain data, no DOM.
 */

import type { FemCameraView } from '@saengine/fem-viewer';
import { safeIntl } from '../../../../base/common/date.js';
import { localize } from '../../../../nls.js';

/** The `.osmodel` fields this reads (the parsed file has them; the viewer's type does not). */
export interface IFilterModel {
	readonly nodes: readonly { readonly id: number; readonly coords: readonly number[]; readonly restraint?: readonly boolean[]; readonly mass?: readonly number[] }[];
	readonly elements: readonly { readonly id: number; readonly name?: string; readonly type: string; readonly nodes: readonly number[] }[];
	readonly mp_constraints?: readonly { readonly type?: string; readonly retained_node?: number; readonly constrained_nodes?: readonly number[] }[];
}

/** A way of looking at the model: the whole model in 3D, a plan, an elevation, or a storey. */
export type FemViewChoice =
	| { readonly kind: 'all' }
	| { readonly kind: 'plan'; readonly z: number; readonly name: string }
	| { readonly kind: 'elevation'; readonly axis: 'x' | 'y'; readonly at: number }
	| { readonly kind: 'storey'; readonly bottom: number; readonly top: number; readonly name: string }
	/**
	 * A developed elevation: the frames and walls on a plan path (x, y in metres) unfolded into
	 * one plane. The viewer finds the elements on the path (`setDevelopment`).
	 */
	| { readonly kind: 'developed'; readonly path: readonly (readonly [number, number])[]; readonly name: string };
/** Nodes within it of a level or grid line are on it [m]. */
const TOLERANCE = 0.005;

const round = (v: number) => Math.round(v * 1000) / 1000;

/**
 * The storey levels of the model, bottom up: the floors of its rigid diaphragms, the elevations
 * with two or more level elements (a roof of beams, a slab without a diaphragm) and the lowest
 * support; without diaphragms or level elements, the elevations where three or more nodes carry
 * horizontal mass.
 */
export function modelLevels(model: IFilterModel): number[] {
	const z = new Map(model.nodes.map(n => [n.id, n.coords[2] ?? 0]));
	const levels = new Set<number>();
	for (const constraint of model.mp_constraints ?? []) {
		const at = constraint.type === 'RigidDiaphragm' && constraint.retained_node !== undefined ? z.get(constraint.retained_node) : undefined;
		if (at !== undefined) {
			levels.add(round(at));
		}
	}
	const flat = new Map<number, number>();
	for (const element of model.elements) {
		const zs = element.nodes.map(id => z.get(id));
		if (zs.length >= 2 && zs.every(v => v !== undefined && Math.abs(v - zs[0]!) <= TOLERANCE)) {
			const at = round(zs[0]!);
			flat.set(at, (flat.get(at) ?? 0) + 1);
		}
	}
	const lowest = Math.min(...model.nodes.map(n => n.coords[2] ?? 0));
	for (const [at, count] of flat) {
		// Not the grade beams or the ground slab on the supports' level (that is the base).
		if (count >= 2 && at > lowest + TOLERANCE && ![...levels].some(l => Math.abs(l - at) <= TOLERANCE)) {
			levels.add(at);
		}
	}
	if (!levels.size) {
		const counts = new Map<number, number>();
		for (const node of model.nodes) {
			if ((node.mass?.[0] ?? 0) > 0 || (node.mass?.[1] ?? 0) > 0) {
				const at = round(node.coords[2] ?? 0);
				counts.set(at, (counts.get(at) ?? 0) + 1);
			}
		}
		for (const [at, count] of counts) {
			if (count >= 3) {
				levels.add(at);
			}
		}
	}
	const supports = model.nodes.filter(n => n.restraint?.some(Boolean)).map(n => n.coords[2] ?? 0);
	if (supports.length) {
		levels.add(round(Math.min(...supports)));
	}
	return [...levels].sort((a, b) => a - b);
}

/** Whether a 2-node element runs (nearly) vertically. */
function isVertical(a: readonly number[], b: readonly number[]): boolean {
	const dx = (b[0] ?? 0) - (a[0] ?? 0);
	const dy = (b[1] ?? 0) - (a[1] ?? 0);
	const dz = (b[2] ?? 0) - (a[2] ?? 0);
	return Math.abs(dz) > 0.9 * Math.hypot(dx, dy, dz);
}

/** The column lines: plan coordinates (x, then y) that two or more columns share, ascending. */
export function gridLines(model: IFilterModel): { readonly x: number[]; readonly y: number[] } {
	const coords = new Map(model.nodes.map(n => [n.id, n.coords]));
	const x = new Map<number, Set<string>>();
	const y = new Map<number, Set<string>>();
	for (const element of model.elements) {
		const [a, b] = element.nodes.map(id => coords.get(id));
		if (element.nodes.length !== 2 || !a || !b || !isVertical(a, b)) {
			continue;
		}
		const column = `${round(a[0] ?? 0)},${round(a[1] ?? 0)}`;
		const cx = round(a[0] ?? 0);
		const cy = round(a[1] ?? 0);
		(x.get(cx) ?? x.set(cx, new Set()).get(cx)!).add(column);
		(y.get(cy) ?? y.set(cy, new Set()).get(cy)!).add(column);
	}
	const shared = (lines: Map<number, Set<string>>) => [...lines].filter(([, columns]) => columns.size >= 2).map(([at]) => at).sort((p, q) => p - q);
	return { x: shared(x), y: shared(y) };
}

/**
 * The columns standing free at the top: the top node of a vertical member that nothing else
 * frames into and no diaphragm ties (a cantilever column, a column of a floor not modelled).
 * They sway as cantilevers (an effective length of about twice their height), which the
 * engineer should know before reading their checks; members by name, naturally sorted.
 */
export function freeTopColumns(model: IFilterModel): string[] {
	const coords = new Map(model.nodes.map(n => [n.id, n.coords]));
	const uses = new Map<number, number>();
	for (const element of model.elements) {
		for (const id of new Set(element.nodes)) {
			uses.set(id, (uses.get(id) ?? 0) + 1);
		}
	}
	const restrained = new Set(model.nodes.filter(n => n.restraint?.some(Boolean)).map(n => n.id));
	// Nodes a rigid diaphragm ties to its floor are braced by it; a diaphragm that does not list
	// its nodes ties every node at the level of its retained node.
	const tied = new Set<number>();
	for (const c of model.mp_constraints ?? []) {
		if (c.constrained_nodes) {
			c.constrained_nodes.forEach(id => tied.add(id));
			continue;
		}
		const at = c.retained_node !== undefined ? coords.get(c.retained_node)?.[2] : undefined;
		if (at !== undefined) {
			model.nodes.filter(n => Math.abs((n.coords[2] ?? 0) - at) <= TOLERANCE).forEach(n => tied.add(n.id));
		}
	}
	const names = new Set<string>();
	for (const element of model.elements) {
		const [a, b] = element.nodes.map(id => coords.get(id));
		if (element.nodes.length !== 2 || !a || !b || !isVertical(a, b)) {
			continue;
		}
		const top = (b[2] ?? 0) > (a[2] ?? 0) ? element.nodes[1] : element.nodes[0];
		if (uses.get(top) === 1 && !restrained.has(top) && !tied.has(top)) {
			names.add((element.name ?? String(element.id)).split('#')[0]);
		}
	}
	return [...names].sort(safeIntl.Collator(undefined, { numeric: true }).value.compare);
}

/** The elements a view draws (undefined: all of them). */
export function visibleElements(model: IFilterModel, view: FemViewChoice): Set<number> | undefined {
	if (view.kind === 'all' || view.kind === 'developed') {
		return undefined; // a developed elevation's elements: the viewer's `setDevelopment`
	}
	const coords = new Map(model.nodes.map(n => [n.id, n.coords]));
	const out = new Set<number>();
	for (const element of model.elements) {
		const points = element.nodes.map(id => coords.get(id)).filter((c): c is readonly number[] => !!c);
		if (!points.length || points.length !== element.nodes.length) {
			continue;
		}
		const zs = points.map(c => c[2] ?? 0);
		let keep: boolean;
		switch (view.kind) {
			case 'plan':
				keep = zs.every(z => Math.abs(z - view.z) <= TOLERANCE);
				break;
			case 'elevation': {
				const index = view.axis === 'x' ? 0 : 1;
				keep = points.every(c => Math.abs((c[index] ?? 0) - view.at) <= TOLERANCE);
				break;
			}
			case 'storey':
				// Its columns, walls and braces, and the floor at its top (not the one below).
				keep = zs.every(z => z >= view.bottom - TOLERANCE && z <= view.top + TOLERANCE) && !zs.every(z => Math.abs(z - view.bottom) <= TOLERANCE);
				break;
		}
		if (keep) {
			out.add(element.id);
		}
	}
	return out;
}

/** The camera a view looks with: a plan from above, an elevation along its grid line's normal. */
export function cameraOf(view: FemViewChoice): FemCameraView {
	switch (view.kind) {
		case 'plan': return 'top';
		case 'elevation': return view.axis === 'x' ? 'side' : 'front';
		case 'developed': return 'front'; // unfolded into the x-z plane
		default: return '3d';
	}
}

/**
 * The outer column lines walked round, as a developed elevation's path: from the lowest x and y
 * anticlockwise in plan and back to the start. Undefined without two lines each way.
 */
export function perimeterPath(model: IFilterModel): [number, number][] | undefined {
	const { x, y } = gridLines(model);
	if (x.length < 2 || y.length < 2) {
		return undefined;
	}
	const x0 = x[0];
	const x1 = x[x.length - 1];
	const y0 = y[0];
	const y1 = y[y.length - 1];
	return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
}

/**
 * A plan path typed as `x, y; x, y; ...` (metres; spaces or semicolons between points), or the
 * reason it is not one.
 */
export function parsePlanPath(text: string): { readonly path: [number, number][] } | { readonly error: string } {
	const points = text.split(/[;\n]+/).map(p => p.trim()).filter(p => p.length);
	const path: [number, number][] = [];
	for (const point of points) {
		const values = point.split(/[,\s]+/).filter(v => v.length).map(Number);
		if (values.length !== 2 || values.some(v => !Number.isFinite(v))) {
			return { error: localize('femView.pathPoint', "\"{0}\" is not a point: give x, y in metres.", point) };
		}
		path.push([values[0], values[1]]);
	}
	if (path.length < 2) {
		return { error: localize('femView.pathShort', "Give at least two points, such as 0, 0; 12, 0; 12, 9.") };
	}
	if (path.every(p => Math.hypot(p[0] - path[0][0], p[1] - path[0][1]) <= TOLERANCE)) {
		return { error: localize('femView.pathLength', "The points are all in one place: the path has no length.") };
	}
	return { path };
}

/** A plan path as typed (the inverse of {@link parsePlanPath}). */
export function formatPlanPath(path: readonly (readonly [number, number])[]): string {
	const n = (v: number) => String(round(v));
	return path.map(([x, y]) => `${n(x)}, ${n(y)}`).join('; ');
}

/**
 * The View picker's choices: 3D, each level's plan, each grid line's elevation, each storey,
 * the perimeter developed, and the developed elevation along `custom` when one was given.
 */
export function viewChoices(model: IFilterModel, names?: ReadonlyMap<number, string>, custom?: readonly (readonly [number, number])[]): { readonly choice: FemViewChoice; readonly label: string }[] {
	const levels = modelLevels(model);
	const nameOf = (z: number, k: number) => names?.get(z) ?? (k === 0 ? localize('femView.base', "Base") : localize('femView.level', "Level {0}", k));
	const grids = gridLines(model);
	const choices: { choice: FemViewChoice; label: string }[] = [{ choice: { kind: 'all' }, label: localize('femView.all', "3D View: Whole Model") }];
	levels.forEach((z, k) => {
		if (k > 0) {
			choices.push({ choice: { kind: 'plan', z, name: nameOf(z, k) }, label: localize('femView.plan', "Plan: {0} (z = {1} m)", nameOf(z, k), z.toFixed(2)) });
		}
	});
	for (const x of grids.x) {
		choices.push({ choice: { kind: 'elevation', axis: 'x', at: x }, label: localize('femView.elevationX', "Elevation: x = {0} m", x.toFixed(2)) });
	}
	for (const y of grids.y) {
		choices.push({ choice: { kind: 'elevation', axis: 'y', at: y }, label: localize('femView.elevationY', "Elevation: y = {0} m", y.toFixed(2)) });
	}
	levels.forEach((z, k) => {
		if (k > 0) {
			choices.push({ choice: { kind: 'storey', bottom: levels[k - 1], top: z, name: nameOf(z, k) }, label: localize('femView.storey', "Storey Below {0} (isolated)", nameOf(z, k)) });
		}
	});
	const perimeter = perimeterPath(model);
	if (perimeter) {
		choices.push({ choice: { kind: 'developed', path: perimeter, name: 'perimeter' }, label: localize('femView.developedPerimeter', "Developed Elevation: Perimeter") });
	}
	if (custom) {
		choices.push({ choice: { kind: 'developed', path: custom, name: 'custom' }, label: localize('femView.developedCustom', "Developed Elevation: {0}", formatPlanPath(custom)) });
	}
	return choices;
}
