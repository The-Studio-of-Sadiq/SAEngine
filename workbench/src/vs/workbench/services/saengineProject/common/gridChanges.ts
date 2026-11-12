/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/** The parts of a floor plan (`floor-plan.json`) this compares; anything else is ignored. */
interface ILayout {
	readonly grids?: { readonly x?: unknown; readonly y?: unknown };
	readonly stories?: unknown;
}

interface ILine { readonly label: string; readonly position: number }
interface IStoryEntry { readonly id: string; readonly name?: string; readonly elevation: number }

function lines(value: unknown): ILine[] {
	return Array.isArray(value) ? value.filter((l): l is ILine => typeof l?.label === 'string' && typeof l?.position === 'number') : [];
}

function stories(value: unknown): IStoryEntry[] {
	return Array.isArray(value) ? value.filter((s): s is IStoryEntry => typeof s?.id === 'string' && typeof s?.elevation === 'number') : [];
}

/**
 * What changed in the grid lines and stories between two versions of the floor plan, in words
 * ("grid line C moved from 12000 to 13000 mm", "story L4 added"), for "Undid …" and "Redid …"
 * messages. Empty when the grids and stories are the same. Used by Grids & Stories; the Floor
 * Plan can use it for the same message on its side.
 */
export function describeGridChanges(before: ILayout | undefined, after: ILayout | undefined): string[] {
	const changes: string[] = [];
	for (const axis of ['x', 'y'] as const) {
		const old = new Map(lines(before?.grids?.[axis]).map(l => [l.label, l.position]));
		const now = new Map(lines(after?.grids?.[axis]).map(l => [l.label, l.position]));
		for (const [label, position] of now) {
			const was = old.get(label);
			if (was === undefined) {
				changes.push(localize('gridChanges.lineAdded', "grid line {0} added at {1} mm", label, position));
			} else if (was !== position) {
				changes.push(localize('gridChanges.lineMoved', "grid line {0} moved from {1} to {2} mm", label, was, position));
			}
		}
		for (const label of old.keys()) {
			if (!now.has(label)) {
				changes.push(localize('gridChanges.lineRemoved', "grid line {0} removed", label));
			}
		}
	}
	const old = new Map(stories(before?.stories).map(s => [s.id, s]));
	const now = new Map(stories(after?.stories).map(s => [s.id, s]));
	for (const [id, story] of now) {
		const was = old.get(id);
		if (!was) {
			changes.push(localize('gridChanges.storyAdded', "story {0} added at {1} mm", story.name ?? id, story.elevation));
		} else if (was.elevation !== story.elevation) {
			changes.push(localize('gridChanges.storyMoved', "story {0} moved from {1} to {2} mm", story.name ?? id, was.elevation, story.elevation));
		} else if ((was.name ?? '') !== (story.name ?? '')) {
			changes.push(localize('gridChanges.storyRenamed', "story {0} renamed to {1}", was.name ?? id, story.name ?? id));
		}
	}
	for (const [id, story] of old) {
		if (!now.has(id)) {
			changes.push(localize('gridChanges.storyRemoved', "story {0} removed", story.name ?? id));
		}
	}
	return changes;
}
