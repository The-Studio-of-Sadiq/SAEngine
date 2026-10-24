/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { MemberGroup, storiesOf } from './floorPlanDrawing.js';
import { nextId } from './floorPlanEdits.js';

/*
 * Typical floors of the floor plan (`05 Floor Plan/floor-plan.json`), as ETABS's similar
 * stories: a story with `similarTo` repeats the plan of that master story. The members stay
 * written out on every story, so the building model and everything after it read them as
 * usual; the floor plan keeps the master and its similar stories (a family) alike by copying
 * each edit to the whole family. A copy keeps the id of the member it replaces at the same place.
 */

type Json = { [key: string]: unknown };

/** The groups a story's plan owns; footings belong to 9 Substructure. */
const GROUPS: readonly MemberGroup[] = ['columns', 'beams', 'walls', 'slabs'];

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function members(layout: Json, group: MemberGroup): Json[] {
	const list = layout[group];
	return Array.isArray(list) ? list.filter(isObject) : [];
}

function rawStories(layout: unknown): Json[] {
	return isObject(layout) && Array.isArray(layout.stories) ? layout.stories.filter(isObject) : [];
}

/** The master story `story` repeats, or undefined when it is not a similar story. */
export function masterOf(layout: unknown, story: string): string | undefined {
	const ids = new Set(storiesOf(layout).map(s => s.id));
	const similarTo = rawStories(layout).find(s => s.id === story)?.similarTo;
	return typeof similarTo === 'string' && similarTo !== story && ids.has(similarTo) ? similarTo : undefined;
}

/** The family of `story`, lowest first: its master and the stories similar to it (one story when it has none). */
export function familyOf(layout: unknown, story: string): string[] {
	const master = masterOf(layout, story) ?? story;
	return storiesOf(layout).map(s => s.id).filter(id => id === master || masterOf(layout, id) === master);
}

/** The story below `story`, which its columns and walls rise from. */
function storyBelow(layout: unknown, story: string): string | undefined {
	const ids = storiesOf(layout).map(s => s.id);
	const index = ids.indexOf(story);
	return index > 0 ? ids[index - 1] : undefined;
}

/** Whether `member` of `group` is on the plan of `story` alone: a beam or slab at it, a column or wall rising one story to it. */
function onStory(layout: unknown, group: MemberGroup, member: Json, story: string): boolean {
	if (group === 'beams' || group === 'slabs') {
		return member.story === story;
	}
	return member.top === story && member.base === storyBelow(layout, story);
}

const pointKey = (p: unknown) => isObject(p) ? `${p.x}/${p.y}/${Number(p.dx) || 0}/${Number(p.dy) || 0}` : '?';

/** Where a member is, independent of its story and id. */
function placeKey(group: MemberGroup, member: Json): string {
	switch (group) {
		case 'columns':
			return pointKey(member.at);
		case 'slabs':
			return (Array.isArray(member.boundary) ? member.boundary : []).map(pointKey).sort().join(' ');
		default:
			return [pointKey(member.start), pointKey(member.end)].sort().join(' ');
	}
}

/** The plan of `story` without ids and story references, for comparing stories. */
function signature(layout: Json, story: string): string {
	return GROUPS.flatMap(group => members(layout, group)
		.filter(m => onStory(layout, group, m, story))
		.map(m => `${group}|${placeKey(group, m)}|${m.type}|${Number(m.rotation) || 0}`))
		.sort().join('\n');
}

/** Whether every story of the family has the same plan. */
export function inSync(layout: unknown, family: readonly string[]): boolean {
	if (!isObject(layout) || family.length < 2) {
		return true;
	}
	const first = signature(layout, family[0]);
	return family.every(story => signature(layout, story) === first);
}

/**
 * The model with the plan of each story in `targets` replaced by a copy of the plan of `source`.
 * A copied member keeps the id of the target's member at the same place, if there is one.
 */
export function copyStory(layout: unknown, source: string, targets: readonly string[]): Json {
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	for (const target of targets) {
		if (target === source) {
			continue;
		}
		const below = storyBelow(next, target);
		for (const group of GROUPS) {
			const rising = group === 'columns' || group === 'walls';
			const all = members(next, group);
			const sourceMembers = all.filter(m => onStory(next, group, m, source));
			const kept = all.filter(m => !onStory(next, group, m, target));
			const reusable = new Map<string, string[]>();
			for (const old of all.filter(m => onStory(next, group, m, target))) {
				const key = placeKey(group, old);
				reusable.set(key, [...(reusable.get(key) ?? []), old.id as string]);
			}
			next[group] = kept;
			if (rising && !below) {
				continue; // nothing rises to the lowest story
			}
			for (const member of sourceMembers) {
				const id = reusable.get(placeKey(group, member))?.shift() ?? nextId(next, group);
				const copy: Json = { ...JSON.parse(JSON.stringify(member)), id };
				if (rising) {
					copy.base = below;
					copy.top = target;
				} else {
					copy.story = target;
				}
				next[group] = [...members(next, group), copy];
			}
		}
	}
	return next;
}

/**
 * The model with `similar` repeating `master` (and only those, of the stories that repeated it),
 * every story of the family made like the master. Stories that repeated a story of `similar`
 * join the family too, so no story repeats a similar story.
 */
export function setSimilar(layout: unknown, master: string, similar: readonly string[]): Json {
	const next = JSON.parse(JSON.stringify(layout)) as Json;
	const chosen = new Set(similar.filter(s => s !== master));
	const before = new Map(rawStories(next).map(s => [s.id as string, s.similarTo]));
	for (const story of rawStories(next)) {
		const id = story.id as string;
		const was = before.get(id);
		if (id === master) {
			delete story.similarTo;
		} else if (chosen.has(id) || (typeof was === 'string' && chosen.has(was))) {
			story.similarTo = master;
		} else if (was === master) {
			delete story.similarTo;
		}
	}
	return copyStory(next, master, familyOf(next, master));
}

/** How the story picker names a story of a family: "= Level 2" for a similar story, "typical, 8 more" for a master. */
export function familyNote(layout: unknown, story: string): { readonly master?: string; readonly similar: number } {
	const master = masterOf(layout, story);
	return master ? { master, similar: 0 } : { similar: familyOf(layout, story).length - 1 };
}
