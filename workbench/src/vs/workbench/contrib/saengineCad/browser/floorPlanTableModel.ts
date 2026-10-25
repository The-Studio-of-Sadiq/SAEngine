/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { compareFileNames } from '../../../../base/common/comparers.js';
import { localize } from '../../../../nls.js';
import { csvText } from '../../../../platform/saengine/common/csv.js';
import { location, onPlanOf, rises, storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { MemberGroup, sectionLabel } from './floorPlanDrawing.js';
import { footingsOwnedMessage, resolvePoint, setMembersType, TOOL_GROUP, TOOL_KINDS } from './floorPlanEdits.js';
import { familyDiffersMessage, placedEdit, placeKey, repeatOnFamilies } from './floorPlanTypical.js';

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
	/** Its object type's size: "300×500", "Ø500", "t 150" (slabs, walls); '' when unknown. */
	readonly section: string;
	/** Length of a beam or wall in plan, height of a column [mm]; undefined for slabs and footings. */
	readonly length?: number;
}

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function members(layout: unknown, group: MemberGroup): Json[] {
	const list = isObject(layout) ? layout[group] : undefined;
	return Array.isArray(list) ? list.filter(isObject) : [];
}

/** Every member of the floor plan, in plan order: groups, then stories from the bottom, then ids. */
export function memberRows(layout: unknown, objects?: unknown): IMemberRow[] {
	const stories = storiesOf(layout);
	const byId = new Map(stories.map(s => [s.id, s]));
	const types = new Map((isObject(objects) && Array.isArray(objects.objects) ? objects.objects.filter(isObject) : []).map(o => [o.id, o]));
	const lengthOf = (group: MemberGroup, member: Json): number | undefined => {
		if (group === 'columns') {
			const [base, top] = [byId.get(String(member.base))?.elevation, byId.get(String(member.top))?.elevation];
			return base !== undefined && top !== undefined ? top - base : undefined;
		}
		if (group === 'beams' || group === 'walls') {
			const [a, b] = [resolvePoint(layout, member.start), resolvePoint(layout, member.end)];
			return a && b ? Math.round(Math.hypot(b[0] - a[0], b[1] - a[1])) : undefined;
		}
		return undefined;
	};
	const name = (id: string) => byId.get(id)?.name ?? id;
	const rows: IMemberRow[] = [];
	for (const group of MEMBER_GROUPS) {
		for (const member of members(layout, group)) {
			if (typeof member.id !== 'string') {
				continue;
			}
			const story = String((rises(group) ? member.top : member.story) ?? '');
			const base = rises(group) ? String(member.base ?? '') : undefined;
			rows.push({
				group,
				id: member.id,
				type: typeof member.type === 'string' ? member.type : '',
				story,
				base,
				storyLabel: base !== undefined ? localize('row.span', "{0} – {1}", name(base), name(story)) : name(story),
				elevation: byId.get(story)?.elevation ?? Number.NaN,
				location: location(group, member),
				section: sectionLabel(types.get(member.type)) ?? '',
				length: lengthOf(group, member),
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
	const stories = storiesOf(layout);
	const story = filter.story ? stories.find(s => s.id === filter.story) : undefined;
	const text = filter.text?.trim().toLowerCase();
	return rows.filter(row => {
		if (filter.group && row.group !== filter.group) {
			return false;
		}
		if (filter.type && row.type !== filter.type) {
			return false;
		}
		if (filter.story) {
			const member = row.base !== undefined ? { base: row.base, top: row.story } : { story: row.story };
			if (row.base !== undefined && story ? !onPlanOf(row.group, member, story, stories) : row.story !== filter.story) {
				return false;
			}
		}
		return !text || [row.id, row.type, row.location].some(value => value.toLowerCase().includes(text));
	});
}

export type SortKey = 'id' | 'group' | 'type' | 'section' | 'length' | 'story' | 'location';

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
		section: (a: IMemberRow, b: IMemberRow) => compareFileNames(a.section, b.section),
		length: (a: IMemberRow, b: IMemberRow) => (a.length ?? Infinity) - (b.length ?? Infinity),
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
	return rises(group) ? stories.slice(1) : stories;
}

export type TableEdit = { readonly ok: true; readonly layout: Json; readonly changed: number; readonly skipped: readonly string[] } | { readonly ok: false; readonly error: string };

export interface IRowRef {
	readonly group: MemberGroup;
	readonly id: string;
}

/**
 * Gives the members `refs` object type `type` (floorPlanEdits.setMembersType); members whose group
 * cannot take it, and footings, are skipped. On a typical floor the type repeats at the same place
 * on every story of its family, and the edit is refused when their plans differ, as in the floor
 * plan (floorPlanTypical.repeatOnFamilies).
 */
export function setRowsType(layout: unknown, objects: unknown, refs: readonly IRowRef[], type: string): TableEdit {
	const result = setMembersType(layout, refs, type, group => typeOptions(objects, group).some(([id]) => id === type));
	if (!result.ok) {
		return result;
	}
	const edits = result.changed.flatMap(ref => {
		const member = members(result.layout, ref.group).find(m => m.id === ref.id);
		const edit = member && placedEdit(result.layout, ref.group, member);
		return edit ? [edit] : [];
	});
	const next = repeatOnFamilies(layout, result.layout, edits, { type });
	if (!next) {
		return { ok: false, error: familyDiffersMessage() };
	}
	return { ok: true, layout: next, changed: result.changed.length, skipped: result.skipped };
}

/**
 * Puts the members `refs` on `story`. Beams and slabs move to it; columns and walls then rise to
 * it, over as many stories as before. A member is skipped (and named) when that would put it
 * below the base or onto another member at the same place; footings are skipped too (9
 * Substructure places them).
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
		if (!member || ref.group === 'footings') {
			skipped.push(ref.id);
			continue;
		}
		let update: Json;
		if (rises(ref.group)) {
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
			if (!rises(ref.group)) {
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
		return { ok: false, error: refs.every(ref => ref.group === 'footings') ? footingsOwnedMessage() : skipped.length
			? localize('table.storyNone', "The selected members cannot go on {0}: it would put them below the base or onto another member.", stories[index].name)
			: localize('table.storySame', "The selected members are on {0} already.", stories[index].name) };
	}
	return { ok: true, layout: next, changed, skipped };
}

/** The rows as CSV (RFC 4180), as the table shows them. */
export function membersCsv(rows: readonly IMemberRow[], storyName: (id: string) => string): string {
	const lines = [['ID', 'Kind', 'Object Type', 'Section (mm)', 'Length (mm)', 'Story', 'Base', 'Location']];
	for (const row of rows) {
		lines.push([row.id, GROUP_LABELS[row.group], row.type, row.section, row.length === undefined ? '' : String(row.length), storyName(row.story), row.base !== undefined ? storyName(row.base) : '', row.location]);
	}
	return csvText(lines);
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
