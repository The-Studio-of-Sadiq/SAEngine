/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IMep, IStory } from './mepDocument.js';

/**
 * The use of each storey, entered once in the coordination view (07 MEP `storyUses`) and read by
 * the plumbing, the HVAC and the electrical services: the backend maps a use to the row of each
 * service's BNBC table (saengine.mep.uses). The roof and plant storeys are not occupied: every
 * service leaves them out.
 */
export type StoryUseKey = 'residential' | 'office' | 'retail' | 'supermarket' | 'restaurant' | 'hotel' | 'hospital' | 'school' | 'bank' | 'assembly' | 'industrial' | 'storage' | 'parking' | 'services' | 'roof';

/** The keys of saengine.mep.uses.STORY_USES, in its order. */
export const STORY_USE_KEYS: readonly StoryUseKey[] = ['residential', 'office', 'retail', 'supermarket', 'restaurant', 'hotel', 'hospital', 'school', 'bank', 'assembly', 'industrial', 'storage', 'parking', 'services', 'roof'];

export interface IStoryUseEntry {
	story: string;
	use: StoryUseKey;
	/** Persons; undefined: each service's default for the use. */
	population?: number;
}

export function storyUseLabel(use: string): string {
	switch (use) {
		case 'residential': return localize('use.residential', "Residential flats");
		case 'office': return localize('use.office', "Offices");
		case 'retail': return localize('use.retail', "Shops");
		case 'supermarket': return localize('use.supermarket', "Supermarket");
		case 'restaurant': return localize('use.restaurant', "Restaurant");
		case 'hotel': return localize('use.hotel', "Hotel rooms");
		case 'hospital': return localize('use.hospital', "Hospital wards");
		case 'school': return localize('use.school', "School classrooms");
		case 'bank': return localize('use.bank', "Bank");
		case 'assembly': return localize('use.assembly', "Assembly hall");
		case 'industrial': return localize('use.industrial', "Light industry");
		case 'storage': return localize('use.storage', "Storage");
		case 'parking': return localize('use.parking', "Parking");
		case 'services': return localize('use.services', "Services, plant (not occupied)");
		case 'roof': return localize('use.roof', "Roof (not occupied)");
		default: return use;
	}
}

export function isOccupied(use: string): boolean {
	return use !== 'roof' && use !== 'services';
}

function isStoryUse(value: unknown): value is IStoryUseEntry {
	return typeof value === 'object' && value !== null && typeof (value as IStoryUseEntry).story === 'string' && STORY_USE_KEYS.includes((value as IStoryUseEntry).use);
}

/** The file's storey-use table (empty when it has none). */
export function storyUsesOf(document: IMep | undefined): IStoryUseEntry[] {
	const list = document?.storyUses;
	return Array.isArray(list) ? list.filter(isStoryUse) : [];
}

/** The table's entry of a storey, if the table lists it. */
export function storyUseOf(document: IMep | undefined, story: string): IStoryUseEntry | undefined {
	return storyUsesOf(document).find(entry => entry.story === story);
}

/** The file's table, created when missing (entries that are not valid are kept as they are). */
export function ensureStoryUses(document: IMep): IStoryUseEntry[] {
	if (!Array.isArray(document.storyUses)) {
		document.storyUses = [];
	}
	return document.storyUses as IStoryUseEntry[];
}

/**
 * A first table for the building's storeys (lowest first): the top storey is the roof, the
 * others take `use` (the ones the table already lists keep theirs). Returns the storeys added.
 */
export function fillStoryUses(document: IMep, stories: readonly IStory[], use: StoryUseKey): number {
	const list = ensureStoryUses(document);
	let added = 0;
	stories.forEach((story, index) => {
		if (list.some(entry => entry.story === story.id)) {
			return;
		}
		list.push({ story: story.id, use: index === stories.length - 1 && stories.length > 1 ? 'roof' : use });
		added++;
	});
	const order = new Map(stories.map((s, i) => [s.id, i]));
	list.sort((a, b) => (order.get(a.story) ?? Infinity) - (order.get(b.story) ?? Infinity));
	return added;
}

/** Copies a storey's use and population to the storeys below it (not the roof). Returns how many changed. */
export function fillDown(document: IMep, stories: readonly IStory[], from: string): number {
	const list = ensureStoryUses(document);
	const source = list.find(entry => entry.story === from);
	const index = stories.findIndex(s => s.id === from);
	if (!source || index < 0) {
		return 0;
	}
	let changed = 0;
	for (const story of stories.slice(0, index)) {
		let entry = list.find(e => e.story === story.id);
		if (entry && !isOccupied(entry.use)) {
			continue;
		}
		if (!entry) {
			entry = { story: story.id, use: source.use };
			list.push(entry);
		}
		entry.use = source.use;
		if (source.population === undefined) {
			delete entry.population;
		} else {
			entry.population = source.population;
		}
		changed++;
	}
	const order = new Map(stories.map((s, i) => [s.id, i]));
	list.sort((a, b) => (order.get(a.story) ?? Infinity) - (order.get(b.story) ?? Infinity));
	return changed;
}
