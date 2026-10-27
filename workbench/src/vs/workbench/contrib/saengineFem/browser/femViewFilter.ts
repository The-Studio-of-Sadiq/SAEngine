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
	| { readonly kind: 'storey'; readonly bottom: number; readonly top: number; readonly name: string };

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
	if (view.kind === 'all') {
		return undefined;
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
		default: return '3d';
	}
}

/** The View picker's choices: 3D, each level's plan, each grid line's elevation, each storey. */
export function viewChoices(model: IFilterModel, names?: ReadonlyMap<number, string>): { readonly choice: FemViewChoice; readonly label: string }[] {
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
	return choices;
}
