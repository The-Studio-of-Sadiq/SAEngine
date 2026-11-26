/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { GridGeometry, GridSystemKind } from './gridGeometry.js';

/**
 * New grid systems for `grids.systems` of the floor plan (rotated orthogonal, radial, single
 * angled lines), with ids and labels that no other grid line uses. One place for the Grids &
 * Stories editor, the floor plan's Grid Systems command and the New Project wizard.
 */

type Json = Record<string, unknown>;

/** Every grid line label of `grids` (the floor plan's `grids` object), of every system. */
export function gridLabels(grids: unknown): Set<string> {
	const labels = new Set(new GridGeometry(grids).axes.map(a => a.label));
	// Lines the geometry skips (half typed) still hold their labels.
	const add = (list: unknown) => Array.isArray(list) && list.forEach(g => typeof g?.label === 'string' && labels.add(g.label));
	const g = typeof grids === 'object' && grids !== null ? grids as Json : {};
	add(g.x);
	add(g.y);
	for (const s of Array.isArray(g.systems) ? g.systems as Json[] : []) {
		['x', 'y', 'rays', 'rings', 'lines'].forEach(key => add(s?.[key]));
	}
	return labels;
}

/** `base`, else `base` with primes ("A'", "A''"), else a number after it: a label not in `used` (which it joins). */
export function uniqueLabel(base: string, used: Set<string>): string {
	let label = base;
	for (let i = 2; used.has(label); i++) {
		label = label.length < 8 && !label.endsWith(`'''`) ? `${label}'` : `${base.slice(0, 5)}${i}`;
	}
	used.add(label);
	return label;
}

/** The options of a new grid system; numbers in mm and degrees. */
export interface INewGridSystem {
	readonly kind: GridSystemKind;
	readonly originX?: number;
	readonly originY?: number;
	readonly angle?: number;
	/** Orthogonal: X and Y bay spacings. */
	readonly xSpacings?: readonly number[];
	readonly ySpacings?: readonly number[];
	/** Radial: the angles of the rays (from the system's angle) and the ring radii. */
	readonly rayAngles?: readonly number[];
	readonly ringRadii?: readonly number[];
	/** Lines: one line from (originX, originY), to (x2, y2) or at `lineAngle`. */
	readonly x2?: number;
	readonly y2?: number;
	readonly lineAngle?: number;
}

const cumulative = (spacings: readonly number[]) => [0, ...spacings].map((_, i) => spacings.slice(0, i).reduce((a, b) => a + b, 0));

/** A new grid system for the floor plan's `grids`, its id and labels unused there. */
export function newGridSystem(grids: unknown, options: INewGridSystem): Json {
	const used = gridLabels(grids);
	const g = typeof grids === 'object' && grids !== null ? grids as Json : {};
	const ids = new Set((Array.isArray(g.systems) ? g.systems as Json[] : []).map(s => String(s?.id)));
	const prefix = options.kind === 'radial' ? 'R' : options.kind === 'lines' ? 'L' : 'G';
	let n = 1;
	while (ids.has(`${prefix}${n}`)) {
		n++;
	}
	const base: Json = { id: `${prefix}${n}`, name: '', kind: options.kind, originX: options.originX ?? 0, originY: options.originY ?? 0, angle: options.angle ?? 0 };
	if (options.kind === 'orthogonal') {
		const letters = (i: number) => String.fromCharCode(65 + (i % 26));
		return {
			...base,
			x: cumulative(options.xSpacings ?? [6000, 6000]).map((position, i) => ({ label: uniqueLabel(`${letters(i)}'`, used), position })),
			y: cumulative(options.ySpacings ?? [5000, 5000]).map((position, i) => ({ label: uniqueLabel(`${i + 1}'`, used), position })),
		};
	}
	if (options.kind === 'radial') {
		return {
			...base,
			rays: (options.rayAngles ?? [0, 30, 60, 90]).map((angle, i) => ({ label: uniqueLabel(`R${i + 1}`, used), angle })),
			rings: (options.ringRadii ?? [6000, 12000]).map((radius, i) => ({ label: uniqueLabel(`C${i + 1}`, used), radius })),
		};
	}
	const line: Json = { label: uniqueLabel('L1', used), x1: options.originX ?? 0, y1: options.originY ?? 0 };
	if (options.x2 !== undefined && options.y2 !== undefined) {
		Object.assign(line, { x2: options.x2, y2: options.y2 });
	} else {
		Object.assign(line, { angle: options.lineAngle ?? 45, length: 20000 });
	}
	return { id: base.id, name: '', kind: 'lines', lines: [line] };
}

/** The next line of a system's list (`x`, `y`, `rays`, `rings` or `lines`), after the last one. */
export function nextSystemLine(grids: unknown, list: 'x' | 'y' | 'rays' | 'rings' | 'lines', items: readonly Json[]): Json {
	const used = gridLabels(grids);
	const last = items[items.length - 1];
	const num = (value: unknown, fallback: number) => typeof value === 'number' ? value : fallback;
	const before = items[items.length - 2];
	switch (list) {
		case 'x':
		case 'y': {
			const step = last && before ? num(last.position, 0) - num(before.position, 0) : list === 'x' ? 6000 : 5000;
			return { label: uniqueLabel(list === 'x' ? `${String.fromCharCode(65 + items.length % 26)}'` : `${items.length + 1}'`, used), position: last ? num(last.position, 0) + step : 0 };
		}
		case 'rays': {
			const step = last && before ? num(last.angle, 0) - num(before.angle, 0) : 30;
			return { label: uniqueLabel(`R${items.length + 1}`, used), angle: last ? num(last.angle, 0) + step : 0 };
		}
		case 'rings': {
			const step = last && before ? num(last.radius, 0) - num(before.radius, 0) : 6000;
			return { label: uniqueLabel(`C${items.length + 1}`, used), radius: (last ? num(last.radius, 0) : 0) + (step > 0 ? step : 6000) };
		}
		default:
			return { label: uniqueLabel(`L${items.length + 1}`, used), x1: 0, y1: 0, angle: 45, length: 20000 };
	}
}
