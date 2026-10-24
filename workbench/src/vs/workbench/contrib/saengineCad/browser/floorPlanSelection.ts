/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { IMemberShape, MemberGroup } from './floorPlanDrawing.js';
import { insidePolygon, members } from './floorPlanEdits.js';

/*
 * Selecting members on the plan of one story, as in AutoCAD and ETABS: a click picks one member,
 * Ctrl+click toggles one, and a window dragged over the plan picks many. A window dragged from
 * left to right selects the members fully inside it; dragged from right to left (a crossing
 * window) it selects every member it touches.
 */

type Json = { [key: string]: unknown };

/** A member of the floor plan, by its group and id. */
export interface IMemberRef {
	readonly group: MemberGroup;
	readonly id: string;
}

/** An axis-aligned rectangle in drawing units. */
export interface IRect {
	readonly min: CadPoint;
	readonly max: CadPoint;
}

export type WindowMode = 'window' | 'crossing';

/** The groups in the order the status line and properties list them. */
export const GROUP_ORDER: readonly MemberGroup[] = ['columns', 'beams', 'walls', 'slabs', 'footings'];

export function sameMember(a: IMemberRef, b: IMemberRef): boolean {
	return a.group === b.group && a.id === b.id;
}

/** The rectangle spanned by two corners of a dragged window. */
export function rectOf(a: CadPoint, b: CadPoint): IRect {
	return { min: [Math.min(a[0], b[0]), Math.min(a[1], b[1])], max: [Math.max(a[0], b[0]), Math.max(a[1], b[1])] };
}

/** A window dragged to the right selects what is inside it; to the left, what it crosses. */
export function windowMode(start: CadPoint, end: CadPoint): WindowMode {
	return end[0] >= start[0] ? 'window' : 'crossing';
}

export function insideRect([x, y]: CadPoint, { min, max }: IRect): boolean {
	return min[0] <= x && x <= max[0] && min[1] <= y && y <= max[1];
}

function segmentsCross(a: CadPoint, b: CadPoint, c: CadPoint, d: CadPoint): boolean {
	const side = (p: CadPoint, q: CadPoint, r: CadPoint) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
	return side(a, b, c) !== side(a, b, d) && side(c, d, a) !== side(c, d, b);
}

function corners({ min, max }: IRect): CadPoint[] {
	return [[min[0], min[1]], [max[0], min[1]], [max[0], max[1]], [min[0], max[1]]];
}

/** Whether a member's outline is fully inside `rect` (window) or touches it (crossing). */
export function shapeInWindow(shape: IMemberShape, rect: IRect, mode: WindowMode): boolean {
	const outline = shape.outline;
	if (outline.kind === 'circle') {
		const [cx, cy] = outline.center;
		const r = outline.radius;
		if (mode === 'window') {
			return insideRect([cx - r, cy - r], rect) && insideRect([cx + r, cy + r], rect);
		}
		const nx = Math.max(rect.min[0], Math.min(cx, rect.max[0]));
		const ny = Math.max(rect.min[1], Math.min(cy, rect.max[1]));
		return Math.hypot(cx - nx, cy - ny) <= r;
	}
	const points = outline.points;
	if (mode === 'window') {
		return points.every(p => insideRect(p, rect));
	}
	if (points.some(p => insideRect(p, rect))) {
		return true;
	}
	const box = corners(rect);
	if (box.some(p => insidePolygon(p, points))) {
		return true;
	}
	return points.some((p, i) => {
		const q = points[(i + 1) % points.length];
		return box.some((c, j) => segmentsCross(p, q, c, box[(j + 1) % box.length]));
	});
}

/** The members a window selects. */
export function selectInWindow(shapes: readonly IMemberShape[], start: CadPoint, end: CadPoint): IMemberRef[] {
	const rect = rectOf(start, end);
	const mode = windowMode(start, end);
	return unique(shapes.filter(s => shapeInWindow(s, rect, mode)).map(({ group, id }) => ({ group, id })));
}

function unique(refs: readonly IMemberRef[]): IMemberRef[] {
	const seen = new Set<string>();
	return refs.filter(r => {
		const key = `${r.group}:${r.id}`;
		if (seen.has(key)) {
			return false;
		}
		seen.add(key);
		return true;
	});
}

/** `current` with `refs` added (`mode` add), toggled (Ctrl+click) or replacing it. */
export function combine(current: readonly IMemberRef[], refs: readonly IMemberRef[], mode: 'replace' | 'add' | 'toggle'): IMemberRef[] {
	if (mode === 'replace') {
		return unique(refs);
	}
	if (mode === 'add') {
		return unique([...current, ...refs]);
	}
	const toggled = current.filter(c => !refs.some(r => sameMember(r, c)));
	return unique([...toggled, ...refs.filter(r => !current.some(c => sameMember(r, c)))]);
}

/** Every member drawn on the plan (Ctrl+A). */
export function selectAll(shapes: readonly IMemberShape[]): IMemberRef[] {
	return unique(shapes.map(({ group, id }) => ({ group, id })));
}

/** The members on the plan of object type `type`. */
export function selectByType(layout: unknown, shapes: readonly IMemberShape[], type: string): IMemberRef[] {
	const model = (typeof layout === 'object' && layout !== null ? layout : {}) as Json;
	return selectAll(shapes).filter(ref => members(model, ref.group).some(m => m.id === ref.id && m.type === type));
}

/** The object types of the members on the plan, with how many of each, most used first. */
export function typesOnPlan(layout: unknown, shapes: readonly IMemberShape[]): { readonly type: string; readonly group: MemberGroup; readonly count: number }[] {
	const model = (typeof layout === 'object' && layout !== null ? layout : {}) as Json;
	const counts = new Map<string, { type: string; group: MemberGroup; count: number }>();
	for (const ref of selectAll(shapes)) {
		const type = members(model, ref.group).find(m => m.id === ref.id)?.type;
		if (typeof type === 'string') {
			const entry = counts.get(type) ?? { type, group: ref.group, count: 0 };
			entry.count++;
			counts.set(type, entry);
		}
	}
	return [...counts.values()].sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
}

/** The selection kept to the members still drawn on the plan (after an edit, undo or another story). */
export function prune(selection: readonly IMemberRef[], shapes: readonly IMemberShape[]): IMemberRef[] {
	return selection.filter(r => shapes.some(s => sameMember(s, r)));
}

/** How many members of each group are selected, in {@link GROUP_ORDER}. */
export function countByGroup(selection: readonly IMemberRef[]): [MemberGroup, number][] {
	return GROUP_ORDER.map(g => [g, selection.filter(r => r.group === g).length] as [MemberGroup, number]).filter(([, n]) => n > 0);
}

function groupCount(group: MemberGroup, n: number): string {
	switch (group) {
		case 'columns': return n === 1 ? localize('sel.column', "1 column") : localize('sel.columns', "{0} columns", n);
		case 'beams': return n === 1 ? localize('sel.beam', "1 beam") : localize('sel.beams', "{0} beams", n);
		case 'walls': return n === 1 ? localize('sel.wall', "1 wall") : localize('sel.walls', "{0} walls", n);
		case 'slabs': return n === 1 ? localize('sel.slab', "1 slab") : localize('sel.slabs', "{0} slabs", n);
		case 'footings': return n === 1 ? localize('sel.footing', "1 footing") : localize('sel.footings', "{0} footings", n);
	}
}

/** "Selected 5: 3 columns, 2 beams" for the status line; empty when nothing is selected. */
export function selectionSummary(selection: readonly IMemberRef[]): string {
	if (!selection.length) {
		return '';
	}
	const kinds = countByGroup(selection).map(([g, n]) => groupCount(g, n)).join(', ');
	return localize('sel.summary', "Selected {0}: {1}", selection.length, kinds);
}

/** What the selected members share, for the properties of a multi-selection. */
export interface ICommonFields {
	/** Per group: the object type all its selected members have, or undefined when they differ. */
	readonly types: ReadonlyMap<MemberGroup, string | undefined>;
	/** The rotation all selected columns and footings have, when only those are selected and they agree. */
	readonly rotation: number | undefined;
	/** Whether every selected member is a column or footing. */
	readonly rotatable: boolean;
}

export function commonFields(layout: unknown, selection: readonly IMemberRef[]): ICommonFields {
	const model = (typeof layout === 'object' && layout !== null ? layout : {}) as Json;
	const found = selection.map(r => ({ ref: r, member: members(model, r.group).find(m => m.id === r.id) })).filter(f => f.member);
	const types = new Map<MemberGroup, string | undefined>();
	for (const [group] of countByGroup(selection)) {
		const values = new Set(found.filter(f => f.ref.group === group).map(f => f.member!.type));
		const [only] = values;
		types.set(group, values.size === 1 && typeof only === 'string' ? only : undefined);
	}
	const rotatable = selection.length > 0 && selection.every(r => r.group === 'columns' || r.group === 'footings');
	const rotations = new Set(found.map(f => Number(f.member!.rotation) || 0));
	const [rotation] = rotations;
	return { types, rotation: rotatable && rotations.size === 1 ? rotation : undefined, rotatable };
}
