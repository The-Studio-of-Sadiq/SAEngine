/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { compareFileNames } from '../../../../base/common/comparers.js';
import { localize } from '../../../../nls.js';
import { MemberGroup, storiesOf } from './floorPlanDrawing.js';
import { changeMemberType, TOOL_GROUP, TOOL_KINDS } from './floorPlanEdits.js';
import { familyOf, inSync } from './floorPlanTypical.js';

/*
 * The Members Table's model: a row for every member placed on the floor plan
 * (`05 Floor Plan/floor-plan.json`), filtering, sorting, CSV, and the edits the table makes
 * (object type and story of the selected rows). Every edit returns a new model, as the floor
 * plan's own edits do (floorPlanEdits.ts), so the editor writes it as one undoable edit.
 */

type Json = { [key: string]: unknown };

export const MEMBER_GROUPS: readonly MemberGroup[] = ['columns', 'beams', 'walls', 'slabs', 'footings'];

export const GROUP_LABELS: { readonly [group in MemberGroup]: string } = {
	columns: localize('group.column', "Column"),
	beams: localize('group.beam', "Beam"),
	walls: localize('group.wall', "Wall"),
	slabs: localize('group.slab', "Slab"),
	footings: localize('group.footing', "Footing"),
};

/** One placed member. */
export interface IMemberRow {
	readonly group: MemberGroup;
	readonly id: string;
	readonly type: string;
	/** The story whose plan shows it: a beam's, slab's or footing's story; a column's or wall's top. */
	readonly story: string;
	/** Columns and walls: the story they rise from. */
	readonly base?: string;
	/** "Level 1", or "Base – Level 1" for columns and walls. */
	readonly storyLabel: string;
	/** Elevation of {@link story}, for sorting [mm]. */
	readonly elevation: number;
	/** Where it is, in grid labels: "A-1", "A-1 (+150, 0)", "A-1 → B-1", "A–B / 1–2". */
	readonly location: string;
}

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function members(layout: unknown, group: MemberGroup): Json[] {
	const list = isObject(layout) ? layout[group] : undefined;
	return Array.isArray(list) ? list.filter(isObject) : [];
}

const RISING = new Set<MemberGroup>(['columns', 'walls']);

/** A grid point in labels: "A-1", with its offset in mm when it has one. */
export function formatPoint(value: unknown): string {
	if (!isObject(value)) {
		return '?';
	}
	const [dx, dy] = [Number(value.dx) || 0, Number(value.dy) || 0];
	const at = `${value.x}-${value.y}`;
	const signed = (v: number) => v > 0 ? `+${v}` : String(v);
	return dx || dy ? `${at} (${signed(dx)}, ${signed(dy)})` : at;
}

function formatBoundary(boundary: unknown): string {
	const points = Array.isArray(boundary) ? boundary.filter(isObject) : [];
	const plain = points.every(p => !p.dx && !p.dy);
	const xs = [...new Set(points.map(p => String(p.x)))];
	const ys = [...new Set(points.map(p => String(p.y)))];
	if (points.length === 4 && plain && xs.length === 2 && ys.length === 2) {
		return `${xs.join('–')} / ${ys.join('–')}`;
	}
	return points.map(formatPoint).join(' · ');
}

function location(group: MemberGroup, member: Json): string {
	switch (group) {
		case 'columns':
		case 'footings':
			return formatPoint(member.at);
		case 'slabs':
			return formatBoundary(member.boundary);
		default:
			return `${formatPoint(member.start)} → ${formatPoint(member.end)}`;
	}
}

/** Every member of the floor plan, in plan order: groups, then stories from the bottom, then ids. */
export function memberRows(layout: unknown): IMemberRow[] {
	const stories = storiesOf(layout);
	const byId = new Map(stories.map(s => [s.id, s]));
	const name = (id: string) => byId.get(id)?.name ?? id;
	const rows: IMemberRow[] = [];
	for (const group of MEMBER_GROUPS) {
		for (const member of members(layout, group)) {
			if (typeof member.id !== 'string') {
				continue;
			}
			const story = String((RISING.has(group) ? member.top : member.story) ?? '');
			const base = RISING.has(group) ? String(member.base ?? '') : undefined;
			rows.push({
				group,
				id: member.id,
				type: typeof member.type === 'string' ? member.type : '',
				story,
				base,
				storyLabel: base !== undefined ? localize('row.span', "{0} – {1}", name(base), name(story)) : name(story),
				elevation: byId.get(story)?.elevation ?? Number.NaN,
				location: location(group, member),
			});
		}
	}
	return sortRows(rows, { key: 'group', descending: false });
}

/** What the table shows: undefined fields show everything. */
export interface IRowFilter {
	/** Members on the plan of this story: at it, or rising through it to their top. */
	readonly story?: string;
	readonly group?: MemberGroup;
	readonly type?: string;
	/** Text in the id, type or location (case-insensitive). */
	readonly text?: string;
}

export function filterRows(layout: unknown, rows: readonly IMemberRow[], filter: IRowFilter): IMemberRow[] {
	const elevation = new Map(storiesOf(layout).map(s => [s.id, s.elevation]));
	const level = filter.story ? elevation.get(filter.story) : undefined;
	const text = filter.text?.trim().toLowerCase();
	return rows.filter(row => {
		if (filter.group && row.group !== filter.group) {
			return false;
		}
		if (filter.type && row.type !== filter.type) {
			return false;
		}
		if (filter.story) {
			if (row.base !== undefined && level !== undefined) {
				const bottom = elevation.get(row.base) ?? Infinity;
				const top = elevation.get(row.story) ?? -Infinity;
				if (!(bottom < level && level <= top)) {
					return false;
				}
			} else if (row.story !== filter.story) {
				return false;
			}
		}
		return !text || [row.id, row.type, row.location].some(value => value.toLowerCase().includes(text));
	});
}

export type SortKey = 'id' | 'group' | 'type' | 'story' | 'location';

export interface ISort {
	readonly key: SortKey;
	readonly descending: boolean;
}


/** Rows sorted by `sort.key`, then by group, story and id (ids naturally: C2 before C10). */
export function sortRows(rows: readonly IMemberRow[], sort: ISort): IMemberRow[] {
	const byGroup = (a: IMemberRow, b: IMemberRow) => MEMBER_GROUPS.indexOf(a.group) - MEMBER_GROUPS.indexOf(b.group);
	const byStory = (a: IMemberRow, b: IMemberRow) => (Number.isNaN(a.elevation) ? Infinity : a.elevation) - (Number.isNaN(b.elevation) ? Infinity : b.elevation) || compareFileNames(a.story, b.story);
	const byId = (a: IMemberRow, b: IMemberRow) => compareFileNames(a.id, b.id);
	const primary: (a: IMemberRow, b: IMemberRow) => number = {
		id: byId,
		group: byGroup,
		type: (a: IMemberRow, b: IMemberRow) => compareFileNames(a.type, b.type),
		story: byStory,
		location: (a: IMemberRow, b: IMemberRow) => compareFileNames(a.location, b.location),
	}[sort.key];
	const sign = sort.descending ? -1 : 1;
	return [...rows].sort((a, b) => sign * primary(a, b) || byGroup(a, b) || byStory(a, b) || byId(a, b));
}

/** The object types a member of `group` can take (kinds as the floor plan's tools place them), as [id, name]. */
export function typeOptions(objects: unknown, group: MemberGroup): [string, string][] {
	const tool = (Object.keys(TOOL_GROUP) as (keyof typeof TOOL_GROUP)[]).find(t => TOOL_GROUP[t] === group);
	const kinds = new Set(tool ? TOOL_KINDS[tool] : []);
	const list = isObject(objects) && Array.isArray(objects.objects) ? objects.objects.filter(isObject) : [];
	return list.filter(o => typeof o.id === 'string' && kinds.has(o.kind as string))
		.map(o => [o.id as string, typeof o.name === 'string' && o.name ? o.name : o.id as string]);
}

/** The stories a member of `group` can be put on: any for beams, slabs and footings; above the lowest for columns and walls. */
export function storyOptions(layout: unknown, group: MemberGroup): { readonly id: string; readonly name: string }[] {
	const stories = storiesOf(layout);
	return RISING.has(group) ? stories.slice(1) : stories;
}

export type TableEdit = { readonly ok: true; readonly layout: Json; readonly changed: number; readonly skipped: readonly string[] } | { readonly ok: false; readonly error: string };

export interface IRowRef {
	readonly group: MemberGroup;
	readonly id: string;
}

/** A type edit of a member on the plan of one story: where it is, so it can be repeated on typical floors. */
interface IPlacedEdit {
	readonly group: MemberGroup;
	readonly key: string;
	readonly story: string;
}

/** The story below `story`, which its columns and walls rise from. */
function storyBelow(layout: unknown, story: string): string | undefined {
	const ids = storiesOf(layout).map(s => s.id);
	const index = ids.indexOf(story);
	return index > 0 ? ids[index - 1] : undefined;
}

/** Whether `member` is on the plan of `story` alone, as typical floors compare them (floorPlanTypical.ts). */
function onStory(layout: unknown, group: MemberGroup, member: Json, story: string): boolean {
	return RISING.has(group) ? member.top === story && member.base === storyBelow(layout, story) : member.story === story;
}

/**
 * Repeats type edits on typical floors: every edited member on a story of a typical-floor family
 * whose plans were alike before the edit gets the same type at the same place on every story of
 * that family (as the floor plan does). Edits on several stories of one family all apply; families
 * that already differed are left as they are.
 */
function repeatOnTypicalFloors(before: unknown, after: Json, edits: readonly IPlacedEdit[], type: string): Json {
	const synced = new Map<string, readonly string[]>();
	const familyFor = (story: string) => {
		let family = synced.get(story);
		if (!family) {
			const all = familyOf(before, story);
			family = all.length > 1 && inSync(before, all) ? all : [];
			all.forEach(s => synced.set(s, family!));
		}
		return family;
	};
	const next = JSON.parse(JSON.stringify(after)) as Json;
	for (const edit of edits) {
		for (const story of familyFor(edit.story)) {
			for (const member of members(next, edit.group)) {
				if (onStory(next, edit.group, member, story) && placeKey(edit.group, member) === edit.key) {
					member.type = type;
				}
			}
		}
	}
	return next;
}

/** Gives the members `refs` object type `type`; members whose group cannot take it are skipped. */
export function setRowsType(layout: unknown, objects: unknown, refs: readonly IRowRef[], type: string): TableEdit {
	if (!refs.length) {
		return { ok: false, error: localize('table.noRows', "Select the members to change.") };
	}
	let next = layout as Json;
	const skipped: string[] = [];
	const edits: IPlacedEdit[] = [];
	let changed = 0;
	for (const ref of refs) {
		if (!typeOptions(objects, ref.group).some(([id]) => id === type)) {
			skipped.push(ref.id);
			continue;
		}
		const result = changeMemberType(next, ref.group, ref.id, type);
		if (!result.ok) {
			skipped.push(ref.id);
			continue;
		}
		const member = members(result.layout, ref.group).find(m => m.id === ref.id);
		const story = member && (RISING.has(ref.group) ? member.top : member.story);
		if (member && typeof story === 'string' && ref.group !== 'footings' && onStory(result.layout, ref.group, member, story)) {
			edits.push({ group: ref.group, key: placeKey(ref.group, member), story });
		}
		next = result.layout;
		changed++;
	}
	if (!changed) {
		return { ok: false, error: localize('table.typeNone', "{0} cannot be given to the selected members.", type) };
	}
	return { ok: true, layout: repeatOnTypicalFloors(layout, next, edits, type), changed, skipped };
}

function pointKey(value: unknown): string {
	return isObject(value) ? `${value.x}/${value.y}/${Number(value.dx) || 0}/${Number(value.dy) || 0}` : '?';
}

function placeKey(group: MemberGroup, member: Json): string {
	switch (group) {
		case 'columns':
		case 'footings':
			return pointKey(member.at);
		case 'slabs':
			return (Array.isArray(member.boundary) ? member.boundary : []).map(pointKey).sort().join(' ');
		default:
			return [pointKey(member.start), pointKey(member.end)].sort().join(' ');
	}
}

/**
 * Puts the members `refs` on `story`. Beams, slabs and footings move to it; columns and walls
 * then rise to it, over as many stories as before. A member is skipped (and named) when that
 * would put it below the base or onto another member at the same place.
 */
export function setRowsStory(layout: unknown, refs: readonly IRowRef[], story: string): TableEdit {
	const stories = storiesOf(layout);
	const index = stories.findIndex(s => s.id === story);
	if (index < 0) {
		return { ok: false, error: localize('table.noStory', "There is no story {0}.", story) };
	}
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	const ids = stories.map(s => s.id);
	const skipped: string[] = [];
	let changed = 0;
	for (const ref of refs) {
		const list = members(next, ref.group);
		const member = list.find(m => m.id === ref.id);
		if (!member) {
			skipped.push(ref.id);
			continue;
		}
		let update: Json;
		if (RISING.has(ref.group)) {
			const span = Math.max(1, ids.indexOf(member.top as string) - ids.indexOf(member.base as string));
			if (index - span < 0) {
				skipped.push(ref.id);
				continue;
			}
			update = { base: ids[index - span], top: story };
		} else {
			update = { story };
		}
		const key = placeKey(ref.group, member);
		// Columns and walls clash when their story spans overlap (base exclusive, top inclusive).
		const range = (bottom: unknown, top: unknown): [number, number] => [ids.indexOf(bottom as string), ids.indexOf(top as string)];
		const [low, high] = range(update.base, update.top);
		const clash = list.some(other => {
			if (other === member || placeKey(ref.group, other) !== key) {
				return false;
			}
			if (!RISING.has(ref.group)) {
				return other.story === story;
			}
			const [otherLow, otherHigh] = range(other.base, other.top);
			return low < otherHigh && otherLow < high;
		});
		if (clash) {
			skipped.push(ref.id);
			continue;
		}
		if (Object.entries(update).every(([k, v]) => member[k] === v)) {
			continue;
		}
		Object.assign(member, update);
		changed++;
	}
	if (!changed) {
		return { ok: false, error: skipped.length
			? localize('table.storyNone', "The selected members cannot go on {0}: it would put them below the base or onto another member.", stories[index].name)
			: localize('table.storySame', "The selected members are on {0} already.", stories[index].name) };
	}
	return { ok: true, layout: next, changed, skipped };
}

function csvField(value: string): string {
	return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/** The rows as CSV (RFC 4180), as the table shows them. */
export function membersCsv(rows: readonly IMemberRow[], storyName: (id: string) => string): string {
	const lines = [['ID', 'Kind', 'Object Type', 'Story', 'Base', 'Location']];
	for (const row of rows) {
		lines.push([row.id, GROUP_LABELS[row.group], row.type, storyName(row.story), row.base !== undefined ? storyName(row.base) : '', row.location]);
	}
	return lines.map(line => line.map(csvField).join(',')).join('\r\n') + '\r\n';
}

/** The row range from `anchor` to `target` (shift-click), by key `group/id`. */
export function rowRange(rows: readonly IMemberRow[], anchor: string | undefined, target: string): string[] {
	const keys = rows.map(rowKey);
	const [a, b] = [anchor === undefined ? -1 : keys.indexOf(anchor), keys.indexOf(target)];
	if (a < 0 || b < 0) {
		return b < 0 ? [] : [target];
	}
	return keys.slice(Math.min(a, b), Math.max(a, b) + 1);
}

export function rowKey(row: IRowRef): string {
	return `${row.group}/${row.id}`;
}
