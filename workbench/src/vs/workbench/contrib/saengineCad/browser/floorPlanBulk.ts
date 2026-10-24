/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { gridsOf, MemberGroup, storiesOf } from './floorPlanDrawing.js';
import { anchor, distanceToSegment, insidePolygon, members, nextId, resolvePoint } from './floorPlanEdits.js';
import { IMemberRef, insideRect, IRect } from './floorPlanSelection.js';
import { familyOf } from './floorPlanTypical.js';

/*
 * Edits of many members at once on the floor plan (`05 Floor Plan/floor-plan.json`): delete,
 * change type, move, copy (an array when repeated), mirror about a grid line, rotate, copy to
 * other stories, and the fill tools that place columns, beams, walls or slabs on every grid
 * intersection, segment or bay inside a window. Members stay on grid points: a moved or copied
 * point keeps its nearest intersection plus an offset (see {@link anchor}). Each edit returns
 * the whole new model, written by the editor as one undoable edit. Nothing is placed twice: a
 * copy or fill landing on a member already there is skipped and counted.
 */

type Json = { [key: string]: unknown };

export type BulkResult =
	| { readonly ok: true; readonly layout: Json; readonly ids: readonly IMemberRef[]; readonly placed: number; readonly skipped: number }
	| { readonly ok: false; readonly error: string };

/** Distance [mm] within which two points are the same place. */
const SAME = 1;

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function clone(layout: unknown): Json {
	return JSON.parse(JSON.stringify(isObject(layout) ? layout : {})) as Json;
}

function find(layout: Json, ref: IMemberRef): Json | undefined {
	return members(layout, ref.group).find(m => m.id === ref.id);
}

const rising = (group: MemberGroup) => group === 'columns' || group === 'walls';
const rotatable = (group: MemberGroup) => group === 'columns' || group === 'footings';

/** The resolved points of a member: its location, its ends, or its slab corners. */
function pointsOf(layout: Json, group: MemberGroup, member: Json): CadPoint[] | undefined {
	const raw = group === 'columns' || group === 'footings' ? [member.at]
		: group === 'slabs' ? (Array.isArray(member.boundary) ? member.boundary : [])
			: [member.start, member.end];
	const points = raw.map(p => resolvePoint(layout, p));
	return points.length && points.every(p => p) ? points as CadPoint[] : undefined;
}

/** The member with every point moved by `map` and re-anchored to the grid; undefined when a point is off the grid. */
function transform(layout: Json, group: MemberGroup, member: Json, map: (p: CadPoint) => CadPoint): Json | undefined {
	const move = (value: unknown) => {
		const at = resolvePoint(layout, value);
		return at && anchor(layout, map(at));
	};
	const result: Json = { ...JSON.parse(JSON.stringify(member)) };
	const keys = group === 'columns' || group === 'footings' ? ['at'] : group === 'slabs' ? [] : ['start', 'end'];
	for (const key of keys) {
		const moved = move(member[key]);
		if (!moved) {
			return undefined;
		}
		result[key] = moved;
	}
	if (group === 'slabs') {
		const corners = (Array.isArray(member.boundary) ? member.boundary : []).map(move);
		if (!corners.length || corners.some(c => !c)) {
			return undefined;
		}
		result.boundary = corners;
	}
	return result;
}

/** Where a member is in height: its story, or the stories a column or wall rises between. */
function levelKey(group: MemberGroup, member: Json): string {
	return rising(group) ? `${member.base}/${member.top}` : String(member.story);
}

function samePoints(a: readonly CadPoint[], b: readonly CadPoint[], ordered: boolean): boolean {
	if (a.length !== b.length) {
		return false;
	}
	if (ordered) {
		const near = (p: CadPoint, q: CadPoint) => Math.hypot(p[0] - q[0], p[1] - q[1]) < SAME;
		return a.every((p, i) => near(p, b[i])) || a.every((p, i) => near(p, b[b.length - 1 - i]));
	}
	return a.every(p => b.some(q => Math.hypot(p[0] - q[0], p[1] - q[1]) < SAME));
}

/** Whether a member like `candidate` (same group, level and place) is in the model already. */
export function exists(layout: Json, group: MemberGroup, candidate: Json, except?: string): boolean {
	const points = pointsOf(layout, group, candidate);
	if (!points) {
		return false;
	}
	const level = levelKey(group, candidate);
	return members(layout, group).some(m => m.id !== except && levelKey(group, m) === level && samePoints(points, pointsOf(layout, group, m) ?? [], group !== 'slabs'));
}

/**
 * Adds a copy of each member, mapped by `map` and moved to `story` (when given), with a new id;
 * copies that would land on a member already there, or off the grid, are skipped.
 */
function addCopies(layout: Json, items: readonly { readonly group: MemberGroup; readonly member: Json }[], map: (p: CadPoint) => CadPoint, story?: string, rotation?: (degrees: number) => number): { placed: IMemberRef[]; skipped: number } {
	const below = story ? storyBelow(layout, story) : undefined;
	const placed: IMemberRef[] = [];
	let skipped = 0;
	for (const { group, member } of items) {
		const copy = transform(layout, group, member, map);
		if (!copy || (story && rising(group) && !below) || (story && group === 'footings')) {
			skipped++;
			continue;
		}
		if (story) {
			if (rising(group)) {
				copy.base = below;
				copy.top = story;
			} else {
				copy.story = story;
			}
		}
		if (rotation && rotatable(group)) {
			copy.rotation = normalize(rotation(Number(copy.rotation) || 0));
		}
		if (group === 'slabs' && Array.isArray(copy.boundary) && rotation) {
			copy.boundary = [...copy.boundary].reverse(); // a mirrored outline runs the other way round
		}
		if (exists(layout, group, copy)) {
			skipped++;
			continue;
		}
		const id = nextId(layout, group);
		layout[group] = [...members(layout, group), { ...copy, id }];
		placed.push({ group, id });
	}
	return { placed, skipped };
}

function normalize(degrees: number): number {
	return Number((((degrees % 360) + 360) % 360).toFixed(3));
}

function storyBelow(layout: unknown, story: string): string | undefined {
	const ids = storiesOf(layout).map(s => s.id);
	const index = ids.indexOf(story);
	return index > 0 ? ids[index - 1] : undefined;
}

function itemsOf(layout: Json, refs: readonly IMemberRef[]): { group: MemberGroup; member: Json }[] {
	return refs.map(ref => ({ group: ref.group, member: find(layout, ref) })).filter((i): i is { group: MemberGroup; member: Json } => !!i.member);
}

const nothingSelected = (): BulkResult => ({ ok: false, error: localize('bulk.nothing', "Select members first.") });

// ───────────────────────────── edits of the selection ─────────────────────────────

/** The model without the selected members. */
export function deleteMembers(layout: unknown, refs: readonly IMemberRef[]): BulkResult {
	if (!refs.length) {
		return nothingSelected();
	}
	const next = clone(layout);
	for (const group of new Set(refs.map(r => r.group))) {
		const ids = new Set(refs.filter(r => r.group === group).map(r => r.id));
		next[group] = members(next, group).filter(m => !ids.has(m.id as string));
	}
	return { ok: true, layout: next, ids: [], placed: 0, skipped: 0 };
}

/** Gives the selected members of `group` object type `type`. */
export function changeTypes(layout: unknown, refs: readonly IMemberRef[], group: MemberGroup, type: string): BulkResult {
	const targets = refs.filter(r => r.group === group);
	if (!targets.length) {
		return nothingSelected();
	}
	if (!type) {
		return { ok: false, error: localize('edit.noType', "Choose an object type.") };
	}
	const next = clone(layout);
	const ids = new Set(targets.map(r => r.id));
	next[group] = members(next, group).map(m => ids.has(m.id as string) ? { ...m, type } : m);
	return { ok: true, layout: next, ids: targets, placed: 0, skipped: 0 };
}

/** Moves the selected members by `delta` [mm], each point re-anchored to its nearest grid intersection. */
export function moveMembers(layout: unknown, refs: readonly IMemberRef[], delta: CadPoint): BulkResult {
	if (!refs.length) {
		return nothingSelected();
	}
	if (!delta[0] && !delta[1]) {
		return { ok: false, error: localize('edit.noMove', "Choose a different point to move to.") };
	}
	const done = relocate(layout, refs, (l, group, member) => transform(l, group, member, ([x, y]) => [x + delta[0], y + delta[1]]));
	if (!done.placed.length) {
		return { ok: false, error: localize('bulk.moveBlocked', "Nothing moved: every member would land on another or off the grid.") };
	}
	return { ok: true, layout: done.layout, ids: done.placed, placed: done.placed.length, skipped: done.skipped };
}

/**
 * Replaces each selected member by `relocated(member)` (same id) as one rigid group: collisions
 * are checked against the model with the whole selection in its new place, so members of the
 * group never block one another. A member whose new place is off the grid or taken by a member
 * outside the group stays where it is, unchanged; members that would then land on it stay too.
 */
function relocate(layout: unknown, refs: readonly IMemberRef[], relocated: (layout: Json, group: MemberGroup, member: Json) => Json | undefined): { layout: Json; placed: IMemberRef[]; skipped: number } {
	const source = clone(layout);
	const key = (r: IMemberRef) => `${r.group}:${r.id}`;
	const items = refs.map(ref => ({ ref, member: find(source, ref) })).filter((i): i is { ref: IMemberRef; member: Json } => !!i.member);
	const moved = new Map<string, Json>();
	for (const { ref, member } of items) {
		const next = relocated(source, ref.group, member);
		if (next) {
			moved.set(key(ref), next);
		}
	}
	const build = (): Json => {
		const next = clone(source);
		for (const group of new Set(items.map(i => i.ref.group))) {
			next[group] = members(next, group).map(m => moved.get(`${group}:${m.id}`) ?? m);
		}
		return next;
	};
	let trial = build();
	for (let changed = true; changed;) {
		changed = false;
		for (const { ref } of items) {
			const next = moved.get(key(ref));
			if (next && exists(trial, ref.group, next, ref.id)) {
				moved.delete(key(ref)); // stays in place
				changed = true;
			}
		}
		if (changed) {
			trial = build();
		}
	}
	const placed = items.filter(i => moved.has(key(i.ref))).map(i => i.ref);
	return { layout: trial, placed, skipped: items.length - placed.length };
}

/** Copies the selected members `times` times, each copy `delta` [mm] further on (an array). */
export function copyMembers(layout: unknown, refs: readonly IMemberRef[], delta: CadPoint, times = 1): BulkResult {
	if (!refs.length) {
		return nothingSelected();
	}
	if (!delta[0] && !delta[1]) {
		return { ok: false, error: localize('bulk.noCopyDistance', "Give the copy a distance; a copy on top of the original is skipped.") };
	}
	if (!Number.isInteger(times) || times < 1 || times > 100) {
		return { ok: false, error: localize('bulk.badTimes', "Copy 1 to 100 times.") };
	}
	const next = clone(layout);
	const items = itemsOf(next, refs);
	const ids: IMemberRef[] = [];
	let skipped = 0;
	for (let k = 1; k <= times; k++) {
		const done = addCopies(next, items, ([x, y]) => [x + k * delta[0], y + k * delta[1]]);
		ids.push(...done.placed);
		skipped += done.skipped;
	}
	return { ok: true, layout: next, ids, placed: ids.length, skipped };
}

/**
 * Mirrors the selected members about grid line `label` of `axis` (an `x` line runs along Y).
 * By default the mirror image is a copy beside the originals, as AutoCAD's MIRROR keeps them;
 * with `keep` false the originals are replaced.
 */
export function mirrorMembers(layout: unknown, refs: readonly IMemberRef[], axis: 'x' | 'y', label: string, keep = true): BulkResult {
	if (!refs.length) {
		return nothingSelected();
	}
	const line = gridsOf(layout)[axis].get(label);
	if (line === undefined) {
		return { ok: false, error: localize('bulk.noLine', "There is no grid line {0}.", label) };
	}
	const map = ([x, y]: CadPoint): CadPoint => axis === 'x' ? [2 * line - x, y] : [x, 2 * line - y];
	const turn = (degrees: number) => axis === 'x' ? 180 - degrees : -degrees;
	if (!keep) {
		// The originals make way for their images, which keep their ids; a blocked one stays as it was.
		const done = relocate(layout, refs, (l, group, member) => {
			const image = transform(l, group, member, map);
			if (image && rotatable(group)) {
				image.rotation = normalize(turn(Number(image.rotation) || 0));
			}
			if (image && group === 'slabs' && Array.isArray(image.boundary)) {
				image.boundary = [...image.boundary].reverse();
			}
			return image;
		});
		return !done.placed.length ? { ok: false, error: localize('bulk.mirrorBlocked', "Nothing mirrored: every image would land on another member or off the grid.") }
			: { ok: true, layout: done.layout, ids: done.placed, placed: done.placed.length, skipped: done.skipped };
	}
	const target = clone(layout);
	const items = itemsOf(target, refs);
	const done = addCopies(target, items, map, undefined, turn);
	return { ok: true, layout: target, ids: done.placed, placed: done.placed.length, skipped: done.skipped };
}

/** Rotates the selected columns and footings by `degrees`, or to `degrees` with `absolute`; other members are skipped. */
export function rotateMembers(layout: unknown, refs: readonly IMemberRef[], degrees: number, absolute = false): BulkResult {
	if (!Number.isFinite(degrees)) {
		return { ok: false, error: localize('edit.badAngle', "Enter an angle in degrees.") };
	}
	const turning = refs.filter(r => rotatable(r.group));
	if (!turning.length) {
		return { ok: false, error: localize('edit.notRotatable', "Only columns and footings rotate; beams, walls and slabs follow their points.") };
	}
	const next = clone(layout);
	for (const ref of turning) {
		const member = find(next, ref);
		if (member) {
			member.rotation = normalize(absolute ? degrees : (Number(member.rotation) || 0) + degrees);
		}
	}
	return { ok: true, layout: next, ids: turning, placed: turning.length, skipped: refs.length - turning.length };
}

/**
 * Copies the selected members of `source`'s plan to the same places on each story of `targets`,
 * and on the stories of their typical floors, so families stay alike. Columns and walls rise from
 * the story below each target; footings stay where they are (9 Substructure places them).
 */
export function copyToStories(layout: unknown, refs: readonly IMemberRef[], source: string, targets: readonly string[]): BulkResult {
	if (!refs.length) {
		return nothingSelected();
	}
	const next = clone(layout);
	const own = new Set(familyOf(next, source));
	const stories = new Set<string>();
	for (const target of targets) {
		for (const story of familyOf(next, target)) {
			if (!own.has(story)) {
				stories.add(story);
			}
		}
	}
	if (!stories.size) {
		return { ok: false, error: localize('bulk.noStories', "Choose other stories than this one and its typical floor.") };
	}
	const items = itemsOf(next, refs);
	const ids: IMemberRef[] = [];
	let skipped = 0;
	for (const story of storiesOf(next).map(s => s.id).filter(id => stories.has(id))) {
		const done = addCopies(next, items, p => p, story);
		ids.push(...done.placed);
		skipped += done.skipped;
	}
	return { ok: true, layout: next, ids, placed: ids.length, skipped };
}

/** What Ctrl+C keeps: copies of the members and the base point they are placed by. */
export interface IFloorPlanClipboard {
	readonly items: readonly { readonly group: MemberGroup; readonly member: Json }[];
	readonly base: CadPoint;
}

/** The clipboard for `refs`: base point the lower left corner of their points, on the grid when one is there. */
export function copyToClipboard(layout: unknown, refs: readonly IMemberRef[]): IFloorPlanClipboard | undefined {
	const model = clone(layout);
	const items = itemsOf(model, refs);
	const points = items.flatMap(i => pointsOf(model, i.group, i.member) ?? []);
	if (!items.length || !points.length) {
		return undefined;
	}
	return { items, base: [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))] };
}

/** Pastes the clipboard on `story` with its base point at `target`. */
export function paste(layout: unknown, clipboard: IFloorPlanClipboard, story: string, target: CadPoint): BulkResult {
	const next = clone(layout);
	const [dx, dy] = [target[0] - clipboard.base[0], target[1] - clipboard.base[1]];
	const done = addCopies(next, clipboard.items, ([x, y]) => [x + dx, y + dy], story);
	return { ok: true, layout: next, ids: done.placed, placed: done.placed.length, skipped: done.skipped };
}

// ───────────────────────────── fill tools ─────────────────────────────

export type FillKind = 'columns' | 'beams' | 'walls' | 'slabs';
/** Which grid segments a beam or wall fill takes: all, those along X (horizontal) or along Y. */
export type FillDirection = 'both' | 'x' | 'y';

function sortedLines(lines: ReadonlyMap<string, number>): [string, number][] {
	return [...lines].sort((a, b) => a[1] - b[1]);
}

/** Whether a straight member of `group` on the level of `candidate` already covers the segment a–b. */
function covered(layout: Json, group: 'beams' | 'walls', level: string, a: CadPoint, b: CadPoint): boolean {
	return members(layout, group).some(m => {
		if (levelKey(group, m) !== level) {
			return false;
		}
		const ends = pointsOf(layout, group, m);
		return !!ends && distanceToSegment(a, ends[0], ends[1]) < SAME && distanceToSegment(b, ends[0], ends[1]) < SAME;
	});
}

/**
 * Places members of object type `type` on story `story` inside `rect` (the whole grid when left
 * out): columns at every grid intersection (rising from the story below), beams or walls on
 * every grid segment between neighbouring intersections, slabs in every bay. Places already
 * taken are skipped and counted.
 */
export function fill(layout: unknown, kind: FillKind, type: string, story: string, rect?: IRect, direction: FillDirection = 'both'): BulkResult {
	if (!type) {
		return { ok: false, error: localize('bulk.noType', "Define an object type for this fill in Object Types first.") };
	}
	const next = clone(layout);
	const below = storyBelow(next, story);
	if ((kind === 'columns' || kind === 'walls') && !below) {
		return { ok: false, error: localize('bulk.fillBase', "Columns and walls rise to a story from the one below; choose a higher story.") };
	}
	const grids = gridsOf(next);
	const xs = sortedLines(grids.x);
	const ys = sortedLines(grids.y);
	const inside = (p: CadPoint) => !rect || insideRect(p, rect);
	const ids: IMemberRef[] = [];
	let skipped = 0;
	let candidates = 0;
	const add = (group: MemberGroup, member: Json) => {
		const id = nextId(next, group);
		next[group] = [...members(next, group), { id, ...member }];
		ids.push({ group, id });
	};
	if (kind === 'columns') {
		const level = storiesOf(next).find(s => s.id === story)!.elevation;
		const elevation = new Map(storiesOf(next).map(s => [s.id, s.elevation]));
		for (const [x, px] of xs) {
			for (const [y, py] of ys) {
				if (!inside([px, py])) {
					continue;
				}
				candidates++;
				const taken = members(next, 'columns').some(c => {
					const at = resolvePoint(next, c.at);
					return at && Math.hypot(at[0] - px, at[1] - py) < SAME
						&& (elevation.get(c.base as string) ?? Infinity) < level && level <= (elevation.get(c.top as string) ?? -Infinity);
				});
				if (taken) {
					skipped++;
				} else {
					add('columns', { type, at: { x, y }, base: below, top: story, rotation: 0 });
				}
			}
		}
	} else if (kind === 'slabs') {
		for (let i = 1; i < xs.length; i++) {
			for (let j = 1; j < ys.length; j++) {
				const [[x0, px0], [x1, px1]] = [xs[i - 1], xs[i]];
				const [[y0, py0], [y1, py1]] = [ys[j - 1], ys[j]];
				if (!inside([px0, py0]) || !inside([px1, py1])) {
					continue;
				}
				candidates++;
				const centre: CadPoint = [(px0 + px1) / 2, (py0 + py1) / 2];
				const taken = members(next, 'slabs').some(s => s.story === story && insidePolygon(centre, pointsOf(next, 'slabs', s) ?? []));
				if (taken) {
					skipped++;
				} else {
					add('slabs', { type, story, boundary: [{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }] });
				}
			}
		}
	} else {
		const level = kind === 'walls' ? `${below}/${story}` : story;
		const segments: [Json, Json, CadPoint, CadPoint][] = [];
		if (direction !== 'y') {
			for (const [y, py] of ys) {
				for (let i = 1; i < xs.length; i++) {
					segments.push([{ x: xs[i - 1][0], y }, { x: xs[i][0], y }, [xs[i - 1][1], py], [xs[i][1], py]]);
				}
			}
		}
		if (direction !== 'x') {
			for (const [x, px] of xs) {
				for (let j = 1; j < ys.length; j++) {
					segments.push([{ x, y: ys[j - 1][0] }, { x, y: ys[j][0] }, [px, ys[j - 1][1]], [px, ys[j][1]]]);
				}
			}
		}
		for (const [start, end, a, b] of segments) {
			if (!inside(a) || !inside(b)) {
				continue;
			}
			candidates++;
			if (covered(next, kind, level, a, b)) {
				skipped++;
			} else {
				add(kind, kind === 'walls' ? { type, base: below, top: story, start, end } : { type, story, start, end });
			}
		}
	}
	if (!candidates) {
		return { ok: false, error: kind === 'slabs' ? localize('bulk.noBays', "No whole bay is inside the window.")
			: kind === 'columns' ? localize('bulk.noNodes', "No grid intersection is inside the window.")
				: localize('bulk.noSegments', "No grid segment is inside the window.") };
	}
	return { ok: true, layout: next, ids, placed: ids.length, skipped };
}

/** What a bulk edit did, for its notice. */
export type BulkVerb = 'placed' | 'copied' | 'moved' | 'mirrored' | 'rotated';

/** "Placed 12, skipped 3 existing." and the like, for the status line. */
export function bulkNotice(result: Extract<BulkResult, { ok: true }>, verb: BulkVerb): string {
	const n = result.placed;
	const m = result.skipped;
	switch (verb) {
		case 'placed': return m ? localize('bulk.placedSkipped', "Placed {0}, skipped {1} existing.", n, m) : localize('bulk.placed', "Placed {0}.", n);
		case 'copied': return m ? localize('bulk.copiedSkipped', "Copied {0}, skipped {1} (already there or off the grid).", n, m) : localize('bulk.copied', "Copied {0}.", n);
		case 'moved': return m ? localize('bulk.movedSkipped', "Moved {0}, kept {1} in place (would land on another member or off the grid).", n, m) : localize('bulk.moved', "Moved {0}.", n);
		case 'mirrored': return m ? localize('bulk.mirroredSkipped', "Mirrored {0}, skipped {1} (already there).", n, m) : localize('bulk.mirrored', "Mirrored {0}.", n);
		case 'rotated': return m ? localize('bulk.rotatedSkipped', "Rotated {0}; {1} beams, walls or slabs do not rotate.", n, m) : localize('bulk.rotated', "Rotated {0}.", n);
	}
}

// ───────────────────────────── command line ─────────────────────────────

export type FloorPlanCommand =
	| { readonly kind: 'select'; readonly what: 'all' } | { readonly kind: 'select'; readonly what: 'none' } | { readonly kind: 'select'; readonly what: 'type'; readonly type: string } | { readonly kind: 'select'; readonly what: 'ids'; readonly ids: readonly string[] }
	| { readonly kind: 'fill'; readonly fill: FillKind; readonly direction: FillDirection; readonly rect?: IRect }
	| { readonly kind: 'copy' | 'array'; readonly delta: CadPoint; readonly times: number }
	| { readonly kind: 'move'; readonly delta: CadPoint }
	| { readonly kind: 'mirror'; readonly axis: 'x' | 'y'; readonly label: string; readonly keep: boolean }
	| { readonly kind: 'rotate'; readonly degrees: number; readonly absolute: boolean }
	| { readonly kind: 'tostories'; readonly stories?: readonly string[] }
	| { readonly kind: 'delete' }
	| { readonly kind: 'error'; readonly message: string };

/** The command words the floor plan answers on the command line; the rest go to the CAD editor. */
export const FLOOR_PLAN_COMMANDS = ['select', 'fill', 'copy', 'move', 'mirror', 'array', 'tostories', 'rotate', 'delete'] as const;

const NUMBER = String.raw`[-+]?(?:\d+\.?\d*|\.\d+)`;
const DISPLACEMENT = new RegExp(String.raw`^@?\s*(?<dx>${NUMBER})\s*[,;\s]\s*(?<dy>${NUMBER})(?:\s+(?:x\s*)?(?<times>\d+))?$`, 'i');

/** A grid point named by its line labels, "A-1" (or "A/1"), as a point. */
function gridPointNamed(layout: unknown, name: string): CadPoint | undefined {
	const grids = gridsOf(layout);
	for (let i = 1; i < name.length - 1; i++) {
		if (name[i] === '-' || name[i] === '/') {
			const x = grids.x.get(name.slice(0, i));
			const y = grids.y.get(name.slice(i + 1));
			if (x !== undefined && y !== undefined) {
				return [x, y];
			}
		}
	}
	return undefined;
}

/**
 * Reads a floor plan command typed on the command line, or undefined when the text is not one
 * (it then goes to the CAD editor's own commands):
 * `select all|none|type <type>|<id>...`, `fill columns|beams|slabs|walls [x|y] [A-1 C-3]`,
 * `copy dx,dy [n]`, `array dx,dy n`, `move dx,dy`, `mirror [x|y] <line> [move]`,
 * `rotate [to] <degrees>`, `tostories [all|<story>...]`, `delete`.
 */
export function parseCommand(text: string, layout: unknown): FloorPlanCommand | undefined {
	const words = text.trim().split(/\s+/).filter(Boolean);
	const word = words[0]?.toLowerCase();
	if (!word || !(FLOOR_PLAN_COMMANDS as readonly string[]).includes(word)) {
		return undefined;
	}
	const rest = words.slice(1);
	const restText = text.trim().slice(words[0].length).trim();
	const usage = (message: string): FloorPlanCommand => ({ kind: 'error', message });
	switch (word) {
		case 'select': {
			const what = rest[0]?.toLowerCase();
			if (what === 'all' || what === 'none') {
				return { kind: 'select', what };
			}
			if (what === 'type' && rest[1]) {
				return { kind: 'select', what: 'type', type: rest[1] };
			}
			return rest.length ? { kind: 'select', what: 'ids', ids: rest.map(r => r.toUpperCase()) } : usage(localize('cmd.selectUsage', "select all | none | type <type> | <id> ..."));
		}
		case 'fill': {
			const kinds: { [word: string]: FillKind } = { column: 'columns', columns: 'columns', beam: 'beams', beams: 'beams', wall: 'walls', walls: 'walls', slab: 'slabs', slabs: 'slabs' };
			const fillKind = kinds[rest[0]?.toLowerCase() ?? ''];
			if (!fillKind) {
				return usage(localize('cmd.fillUsage', "fill columns | beams | slabs | walls [x | y] [A-1 C-3]"));
			}
			let args = rest.slice(1);
			let direction: FillDirection = 'both';
			if (args[0] && /^[xy]$/i.test(args[0]) && (fillKind === 'beams' || fillKind === 'walls')) {
				direction = args[0].toLowerCase() as FillDirection;
				args = args.slice(1);
			}
			if (!args.length) {
				return { kind: 'fill', fill: fillKind, direction };
			}
			const [a, b] = args.map(name => gridPointNamed(layout, name));
			if (args.length !== 2 || !a || !b) {
				return usage(localize('cmd.fillWindow', "Name the window by two grid points, e.g. fill {0} A-1 C-3.", fillKind));
			}
			return { kind: 'fill', fill: fillKind, direction, rect: { min: [Math.min(a[0], b[0]), Math.min(a[1], b[1])], max: [Math.max(a[0], b[0]), Math.max(a[1], b[1])] } };
		}
		case 'copy':
		case 'array':
		case 'move': {
			const match = DISPLACEMENT.exec(restText);
			if (!match?.groups) {
				return usage(word === 'move' ? localize('cmd.moveUsage', "move dx, dy (mm)") : word === 'copy' ? localize('cmd.copyUsage', "copy dx, dy [times] (mm)") : localize('cmd.arrayUsage', "array dx, dy times (mm)"));
			}
			const delta: CadPoint = [Number(match.groups.dx), Number(match.groups.dy)];
			if (word === 'move') {
				return { kind: 'move', delta };
			}
			const times = match.groups.times ? Number(match.groups.times) : word === 'array' ? NaN : 1;
			return Number.isFinite(times) ? { kind: word, delta, times } : usage(localize('cmd.arrayUsage', "array dx, dy times (mm)"));
		}
		case 'mirror': {
			let args = rest;
			const keep = args[args.length - 1]?.toLowerCase() !== 'move';
			if (!keep) {
				args = args.slice(0, -1);
			}
			let axis: 'x' | 'y' | undefined;
			if (args.length === 2 && /^[xy]$/i.test(args[0])) {
				axis = args[0].toLowerCase() as 'x' | 'y';
				args = args.slice(1);
			}
			const label = args[0];
			if (args.length !== 1 || !label) {
				return usage(localize('cmd.mirrorUsage', "mirror [x | y] <grid line> [move]"));
			}
			const grids = gridsOf(layout);
			const onX = grids.x.has(label);
			const onY = grids.y.has(label);
			axis = axis ?? (onX && !onY ? 'x' : onY && !onX ? 'y' : undefined);
			if (!axis) {
				return usage(onX && onY ? localize('cmd.mirrorAmbiguous', "Grid line {0} is on both axes: mirror x {0} or mirror y {0}.", label) : localize('bulk.noLine', "There is no grid line {0}.", label));
			}
			return { kind: 'mirror', axis, label, keep };
		}
		case 'rotate': {
			const absolute = rest[0]?.toLowerCase() === 'to';
			const degrees = Number(absolute ? rest[1] : rest[0]);
			return rest.length && Number.isFinite(degrees) ? { kind: 'rotate', degrees, absolute } : usage(localize('cmd.rotateUsage', "rotate <degrees> | rotate to <degrees>"));
		}
		case 'tostories': {
			if (!rest.length) {
				return { kind: 'tostories' };
			}
			const stories = storiesOf(layout);
			if (rest.length === 1 && rest[0].toLowerCase() === 'all') {
				return { kind: 'tostories', stories: stories.slice(1).map(s => s.id) };
			}
			const whole = stories.find(s => s.name.toLowerCase() === restText.toLowerCase());
			if (whole) {
				return { kind: 'tostories', stories: [whole.id] }; // a name with spaces, "Level 2"
			}
			const ids = rest.map(r => stories.find(s => s.id.toLowerCase() === r.toLowerCase() || s.name.toLowerCase() === r.toLowerCase())?.id);
			const unknown = rest.filter((_, i) => !ids[i]);
			return unknown.length ? usage(localize('cmd.unknownStory', "No story {0}.", unknown.join(', '))) : { kind: 'tostories', stories: ids as string[] };
		}
		case 'delete':
			return { kind: 'delete' };
	}
	return undefined;
}
