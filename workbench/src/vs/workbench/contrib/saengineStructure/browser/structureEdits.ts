/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { ModelerEntity, ModelPoint } from '@saengine/fem-viewer';
import { localize } from '../../../../nls.js';
import { isJson, Json, json, list, point } from './structureGeometry.js';

/*
 * Edits of the structural model (`structure.json`) made by the 3D modeller. Each takes the
 * current document and returns a new one (the input is not changed), or why it cannot.
 */

export type EditResult =
	| { readonly ok: true; readonly doc: Json; readonly ids: readonly string[] }
	| { readonly ok: false; readonly error: string };

/** Points closer than this are the same point (mm), as in the Python model. */
const TOLERANCE = 1;

const LISTS: { readonly [kind in ModelerEntity['kind']]: 'members' | 'areas' | 'supports' } = {
	member: 'members',
	area: 'areas',
	support: 'supports',
};

function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value));
}

function distance(a: ModelPoint, b: ModelPoint): number {
	return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function add(a: ModelPoint, d: ModelPoint): ModelPoint {
	return [a[0] + d[0], a[1] + d[1], a[2] + d[2]];
}

/** The next free id with `prefix` among members, areas and supports (one namespace for elements). */
export function nextId(doc: Json, prefix: string, taken: ReadonlySet<string> = new Set()): string {
	const used = new Set([...list(doc.members), ...list(doc.areas), ...list(doc.supports)].map(e => String(e.id)));
	let n = 1;
	while (used.has(`${prefix}${n}`) || taken.has(`${prefix}${n}`)) {
		n++;
	}
	return `${prefix}${n}`;
}

function withList(doc: Json, name: 'members' | 'areas' | 'supports'): [Json, Json[]] {
	const copy = clone(doc);
	const items = list(copy[name]);
	copy[name] = items;
	return [copy, items];
}

export function addMember(doc: Json, type: string, start: ModelPoint, end: ModelPoint): EditResult {
	if (!type) {
		return { ok: false, error: localize('edit.noMemberType', "Add a beam, column or brace type in Object Types first.") };
	}
	if (distance(start, end) < TOLERANCE) {
		return { ok: false, error: localize('edit.zeroMember', "Pick an end away from the start.") };
	}
	const [copy, members] = withList(doc, 'members');
	const id = nextId(doc, 'M');
	members.push({ id, type, start: json(start), end: json(end) });
	return { ok: true, doc: copy, ids: [id] };
}

/** The unit normal of a polygon (Newell's method), or undefined when it has no area. */
export function polygonNormal(points: readonly ModelPoint[]): ModelPoint | undefined {
	let nx = 0, ny = 0, nz = 0;
	for (let i = 0; i < points.length; i++) {
		const a = points[i];
		const b = points[(i + 1) % points.length];
		nx += (a[1] - b[1]) * (a[2] + b[2]);
		ny += (a[2] - b[2]) * (a[0] + b[0]);
		nz += (a[0] - b[0]) * (a[1] + b[1]);
	}
	const size = Math.hypot(nx, ny, nz);
	return size < TOLERANCE * TOLERANCE ? undefined : [nx / size, ny / size, nz / size];
}

export function addArea(doc: Json, type: string, outline: readonly ModelPoint[]): EditResult {
	if (!type) {
		return { ok: false, error: localize('edit.noAreaType', "Add a slab or wall type in Object Types first.") };
	}
	const normal = polygonNormal(outline);
	if (outline.length < 3 || !normal) {
		return { ok: false, error: localize('edit.noArea', "An area needs at least three corners that are not in a line.") };
	}
	const off = outline.some(p => Math.abs((p[0] - outline[0][0]) * normal[0] + (p[1] - outline[0][1]) * normal[1] + (p[2] - outline[0][2]) * normal[2]) > TOLERANCE);
	if (off) {
		return { ok: false, error: localize('edit.notFlat', "The corners of an area must lie in one plane.") };
	}
	const [copy, areas] = withList(doc, 'areas');
	const id = nextId(doc, 'A');
	areas.push({ id, type, outline: outline.map(json) });
	return { ok: true, doc: copy, ids: [id] };
}

export function addSupport(doc: Json, at: ModelPoint, fixity: 'fixed' | 'pinned'): EditResult {
	if (list(doc.supports).some(s => distance(point(s.at), at) < TOLERANCE)) {
		return { ok: false, error: localize('edit.supportExists', "There is a support at this point already.") };
	}
	const [copy, supports] = withList(doc, 'supports');
	const id = nextId(doc, 'SP');
	supports.push({ id, at: json(at), fixity });
	return { ok: true, doc: copy, ids: [id] };
}

/** Every point of an element, moved through `move`. */
function transform(element: Json, kind: ModelerEntity['kind'], move: (p: ModelPoint) => ModelPoint): Json {
	const result = clone(element);
	if (kind === 'member') {
		result.start = json(move(point(element.start)));
		result.end = json(move(point(element.end)));
	} else if (kind === 'area') {
		result.outline = list(element.outline).map(p => json(move(point(p))));
		result.openings = list(element.openings).map(o => ({ ...o, outline: list(o.outline).map(p => json(move(point(p)))) }));
		if (!list(element.openings).length) {
			delete result.openings;
		}
	} else {
		result.at = json(move(point(element.at)));
	}
	return result;
}

function selected(doc: Json, entities: readonly ModelerEntity[]): { kind: ModelerEntity['kind']; index: number; element: Json }[] {
	const result = [];
	for (const entity of entities) {
		const items = list(doc[LISTS[entity.kind]]);
		const index = items.findIndex(e => e.id === entity.id);
		if (index >= 0) {
			result.push({ kind: entity.kind, index, element: items[index] });
		}
	}
	return result;
}

export function moveElements(doc: Json, entities: readonly ModelerEntity[], delta: ModelPoint): EditResult {
	const picked = selected(doc, entities);
	if (!picked.length) {
		return { ok: false, error: localize('edit.nothingSelected', "Select what to change first.") };
	}
	const copy = clone(doc);
	for (const { kind, index, element } of picked) {
		(copy[LISTS[kind]] as Json[])[index] = transform(element, kind, p => add(p, delta));
	}
	return { ok: true, doc: copy, ids: picked.map(p => String(p.element.id)) };
}

/** Copies of the selection, `count` times, each `delta` further than the one before. */
export function copyElements(doc: Json, entities: readonly ModelerEntity[], delta: ModelPoint, count = 1): EditResult {
	return replicate(doc, entities, Array.from({ length: Math.max(1, Math.floor(count)) }, (_, k) => (p: ModelPoint) => add(p, [delta[0] * (k + 1), delta[1] * (k + 1), delta[2] * (k + 1)])));
}

/** Mirrored copies of the selection about the vertical plane through `a` and `b` (in plan). */
export function mirrorElements(doc: Json, entities: readonly ModelerEntity[], a: ModelPoint, b: ModelPoint): EditResult {
	const dx = b[0] - a[0];
	const dy = b[1] - a[1];
	const length = Math.hypot(dx, dy);
	if (length < TOLERANCE) {
		return { ok: false, error: localize('edit.noMirrorLine', "Pick a second point of the mirror line away from the first, in plan.") };
	}
	const [ux, uy] = [dx / length, dy / length];
	const mirror = (p: ModelPoint): ModelPoint => {
		const t = (p[0] - a[0]) * ux + (p[1] - a[1]) * uy;
		const fx = a[0] + t * ux;
		const fy = a[1] + t * uy;
		return [2 * fx - p[0], 2 * fy - p[1], p[2]];
	};
	return replicate(doc, entities, [mirror]);
}

function replicate(doc: Json, entities: readonly ModelerEntity[], moves: readonly ((p: ModelPoint) => ModelPoint)[]): EditResult {
	const picked = selected(doc, entities);
	if (!picked.length) {
		return { ok: false, error: localize('edit.nothingSelected', "Select what to change first.") };
	}
	const copy = clone(doc);
	const ids: string[] = [];
	const taken = new Set<string>();
	for (const move of moves) {
		for (const { kind, element } of picked) {
			const prefix = kind === 'member' ? 'M' : kind === 'area' ? 'A' : 'SP';
			if (kind === 'support' && list(copy.supports).some(s => distance(point(s.at), move(point(element.at))) < TOLERANCE)) {
				continue; // never two supports at one point
			}
			const id = nextId(copy, prefix, taken);
			taken.add(id);
			const items = list(copy[LISTS[kind]]);
			items.push({ ...transform(element, kind, move), id });
			copy[LISTS[kind]] = items;
			ids.push(id);
		}
	}
	return { ok: true, doc: copy, ids };
}

/** Splits a member into `parts` equal members (the first keeps its id). */
export function divideMember(doc: Json, id: string, parts: number): EditResult {
	const count = Math.floor(parts);
	if (count < 2) {
		return { ok: false, error: localize('edit.divideCount', "Divide into at least 2 parts.") };
	}
	const members = list(doc.members);
	const index = members.findIndex(m => m.id === id);
	if (index < 0) {
		return { ok: false, error: localize('edit.pickMember', "Pick a member to divide.") };
	}
	const member = members[index];
	const [start, end] = [point(member.start), point(member.end)];
	const at = (k: number): ModelPoint => [start[0] + (end[0] - start[0]) * k / count, start[1] + (end[1] - start[1]) * k / count, start[2] + (end[2] - start[2]) * k / count];
	const copy = clone(doc);
	const result = list(copy.members);
	const pieces: Json[] = [];
	const taken = new Set<string>();
	for (let k = 0; k < count; k++) {
		const pieceId = k === 0 ? id : nextId(copy, 'M', taken);
		taken.add(pieceId);
		pieces.push({ ...clone(member), id: pieceId, start: json(at(k)), end: json(at(k + 1)) });
	}
	result.splice(index, 1, ...pieces);
	copy.members = result;
	return { ok: true, doc: copy, ids: pieces.map(p => String(p.id)) };
}

export function removeElements(doc: Json, entities: readonly ModelerEntity[]): EditResult {
	const picked = selected(doc, entities);
	if (!picked.length) {
		return { ok: false, error: localize('edit.nothingSelected', "Select what to change first.") };
	}
	const copy = clone(doc);
	for (const name of ['members', 'areas', 'supports'] as const) {
		const doomed = new Set(picked.filter(p => LISTS[p.kind] === name).map(p => String(p.element.id)));
		copy[name] = list(copy[name]).filter(e => !doomed.has(String(e.id)));
	}
	return { ok: true, doc: copy, ids: picked.map(p => String(p.element.id)) };
}

/** "dx, dy, dz" or "dx, dy, dz, n" typed by the engineer (mm); undefined when it does not parse. */
export function parseOffset(text: string): { delta: ModelPoint; count?: number } | undefined {
	const values = text.split(/[,\s]+/).filter(Boolean).map(Number);
	if ((values.length !== 3 && values.length !== 4) || values.some(v => !Number.isFinite(v))) {
		return undefined;
	}
	return { delta: [values[0], values[1], values[2]], count: values.length === 4 ? values[3] : undefined };
}

/** Whether `value` is a structural model the modeller can edit. */
export function isStructure(value: unknown): value is Json {
	return isJson(value) && value.schema === 'saengine.structure/1';
}
