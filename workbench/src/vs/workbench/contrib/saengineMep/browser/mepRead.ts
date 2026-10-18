/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IMepContext, IStory, nextId, Point, storyElements } from './mepDocument.js';

/*
 * What the services of the MEP part share (plumbing, HVAC, electrical): reading the file's
 * sections and the backend's answers defensively, the checks' status, the merge of what the
 * backend proposes, and the stories the services hang under or stand on. No UI.
 */

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function records<T>(value: unknown): T[] {
	return (Array.isArray(value) ? value.filter(isRecord) : []) as T[];
}

/** The list itself when it holds only objects (so references to it stay valid), else a cleaned copy. */
export function recordList<T>(value: unknown): T[] {
	return (Array.isArray(value) && value.every(isRecord) ? value : records<T>(value)) as T[];
}

export function num(value: unknown, fallback = 0): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function optionalNumber(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function optionalString(value: unknown): string | undefined {
	return typeof value === 'string' && value ? value : undefined;
}

export function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export function record(value: unknown): Record<string, unknown> {
	return isRecord(value) ? value : {};
}

export function isPoint(value: unknown): value is Point {
	return Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number';
}

/** `note`, else the `notes` joined. */
export function noteOf(item: Record<string, unknown>): string | undefined {
	return optionalString(item.note) ?? (strings(item.notes).join('; ') || undefined);
}

export function duplicates(ids: readonly string[]): Set<string> {
	const seen = new Set<string>();
	const repeated = new Set<string>();
	for (const id of ids) {
		if (seen.has(id)) {
			repeated.add(id);
		}
		seen.add(id);
	}
	return repeated;
}

// ───────────────────────────── checks ─────────────────────────────

export type CheckStatus = 'ok' | 'warn' | 'fail' | 'none';

/** One check of a backend report: `{ name, demand, capacity, unit, utilisation, ok|status, note }`. */
export interface IMepCheck {
	readonly name: string;
	readonly demand?: number;
	readonly capacity?: number;
	readonly unit?: string;
	readonly utilisation?: number;
	readonly status: CheckStatus;
	readonly combination?: string;
	readonly note?: string;
}

/** A status from `status` ("ok", "warn"/"warning", "fail"), else `ok`, else the utilisation. */
export function statusOf(item: Record<string, unknown>): CheckStatus {
	const s = item.status;
	if (s === 'ok' || s === 'pass') {
		return 'ok';
	}
	if (s === 'warn' || s === 'warning') {
		return 'warn';
	}
	if (s === 'fail' || s === 'failed') {
		return 'fail';
	}
	if (typeof item.ok === 'boolean') {
		return item.ok ? 'ok' : 'fail';
	}
	const u = optionalNumber(item.utilisation);
	return u === undefined ? 'none' : u > 1 ? 'fail' : u >= 0.9 ? 'warn' : 'ok';
}

export function statusRank(status: CheckStatus): number {
	return status === 'fail' ? 3 : status === 'warn' ? 2 : status === 'ok' ? 1 : 0;
}

export function worst(statuses: readonly CheckStatus[]): CheckStatus {
	return statuses.reduce<CheckStatus>((w, s) => statusRank(s) > statusRank(w) ? s : w, 'none');
}

export function readCheck(c: Record<string, unknown>): IMepCheck {
	return {
		name: String(c.name ?? c.check ?? ''), demand: optionalNumber(c.demand), capacity: optionalNumber(c.capacity), unit: optionalString(c.unit),
		utilisation: optionalNumber(c.utilisation), status: statusOf(c), combination: optionalString(c.combination), note: noteOf(c),
	};
}

export function readChecks(value: unknown): IMepCheck[] {
	return records<Record<string, unknown>>(value).map(readCheck);
}

/** The backend's problems: `problems` of the answer, as `problemsOrResult` gives them when it could not read the project. */
export function problemsOf(raw: unknown): string[] {
	return isRecord(raw) ? strings(raw.problems) : [];
}

// ───────────────────────────── proposals ─────────────────────────────

/**
 * Merges what the backend proposes into a list of the file (plant, electrical equipment). A
 * proposal with an ID of the list changes only the `keys` that differ (the position stays where
 * the engineer put it, unless the item has none) and is marked `sized`; one the list lacks is
 * added with an unused ID (`prefix` + number). Returns the items added or changed.
 */
export function mergeProposals<T extends { id: string; sized?: boolean;[key: string]: unknown }>(list: T[], proposals: readonly T[], keys: readonly string[], ids: () => string[], prefix: string): T[] {
	const touched: T[] = [];
	for (const proposal of proposals) {
		const existing = proposal.id ? list.find(item => item.id === proposal.id) : undefined;
		if (existing) {
			const changed = keys.filter(key => proposal[key] !== undefined && proposal[key] !== existing[key]);
			if (!changed.length) {
				continue;
			}
			const target: { [key: string]: unknown } = existing;
			for (const key of changed) {
				target[key] = proposal[key];
			}
			if (proposal.sized !== false) {
				existing.sized = true;
			}
			touched.push(existing);
		} else {
			const used = ids();
			const item = { ...proposal, id: proposal.id && !used.includes(proposal.id) ? proposal.id : nextId(prefix, used), sized: proposal.sized !== false };
			list.push(item);
			touched.push(item);
		}
	}
	return touched;
}

// ───────────────────────────── stories ─────────────────────────────

/** The story above `storyId` (its ceiling is that story's floor); undefined at the top. */
export function storyAbove(context: IMepContext, storyId: string): IStory | undefined {
	const index = context.stories.findIndex(s => s.id === storyId);
	return index >= 0 ? context.stories[index + 1] : undefined;
}

/** The roof: the highest story with a floor (slabs), else the top story. */
export function roofStory(context: IMepContext): IStory | undefined {
	for (let i = context.stories.length - 1; i >= 0; i--) {
		if (storyElements(context, context.stories[i].id).slabs.length) {
			return context.stories[i];
		}
	}
	return context.stories[context.stories.length - 1];
}

/** Whether `storyId` lies between two stories (inclusive), by elevation; by id when one is unknown. */
export function storyBetween(context: IMepContext, storyId: string, from: string, to: string): boolean {
	const elevation = (id: string) => context.stories.find(s => s.id === id)?.elevation;
	const at = elevation(storyId);
	const a = elevation(from);
	const b = elevation(to);
	if (at === undefined || a === undefined || b === undefined) {
		return storyId === from || storyId === to;
	}
	return at >= Math.min(a, b) - 1 && at <= Math.max(a, b) + 1;
}

/**
 * A story's floor area [m²]: its slabs, else (a ground floor on grade) the slabs of the floor
 * above it, else the area its columns span. For the summaries the editor shows without the backend.
 */
export function storyFloorArea(context: IMepContext, storyId: string): number {
	const area = (points: readonly Point[]) => {
		let sum = 0;
		for (let i = 0; i < points.length; i++) {
			const a = points[i];
			const b = points[(i + 1) % points.length];
			sum += a[0] * b[1] - b[0] * a[1];
		}
		return Math.abs(sum) / 2;
	};
	const slabs = storyElements(context, storyId).slabs;
	if (slabs.length) {
		return slabs.reduce((s, slab) => s + area(slab.boundary), 0) / 1e6;
	}
	const above = storyAbove(context, storyId);
	const ceiling = above ? storyElements(context, above.id).slabs : [];
	if (ceiling.length) {
		return ceiling.reduce((s, slab) => s + area(slab.boundary), 0) / 1e6;
	}
	const columns = storyElements(context, storyId).columns;
	if (columns.length < 2) {
		return 0;
	}
	const xs = columns.map(c => c.x);
	const ys = columns.map(c => c.y);
	return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys)) / 1e6;
}

/** The length of a polyline [mm]. */
export function pathLength(path: readonly Point[]): number {
	let length = 0;
	for (let i = 1; i < path.length; i++) {
		length += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
	}
	return length;
}

/** A label for the "backend lists it, else the static one" notes. */
export function staticListNote(what: string): string {
	return localize('mepRead.staticList', "{0}: the list SAEngine starts from; the backend's list replaces it when it is available.", what);
}
