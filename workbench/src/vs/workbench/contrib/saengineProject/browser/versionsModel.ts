/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { ALL_PARTS, IProjectPart } from '../../../services/saengineProject/common/saengineProject.js';
import { partName } from './projectParts.js';
import { formatDate } from '../../../services/saengineProject/common/formatting.js';

/*
 * Versions: the engineer-facing history of a project, kept by the backend on top of git. This
 * file holds what the UI makes of the backend's answers (free of DOM and services, so that it can
 * be tested on its own): the command ids and their arguments, the answers read leniently (the
 * backend may grow fields), and the texts the Versions editor and the sidebar show.
 */

// ───────────────────────────── backend commands ─────────────────────────────

/** `{projectRoot}` -> {@link IVersionsStatus} (read with {@link readStatus}). */
export const VERSIONS_STATUS_COMMAND = 'saengine.versions.status';
/** `{projectRoot, limit}` -> `{versions: [...]}` or `[...]` (read with {@link readVersions}). */
export const VERSIONS_LIST_COMMAND = 'saengine.versions.list';
/** `{projectRoot, message, author, issued, label}` -> the new version. */
export const VERSIONS_SAVE_COMMAND = 'saengine.versions.save';
/** `{projectRoot, from, to}` (`to` omitted: the current files) -> {@link IVersionDiff} (read with {@link readDiff}). */
export const VERSIONS_DIFF_COMMAND = 'saengine.versions.diff';
/** `{projectRoot, version, parts}` (`parts` omitted: all) -> `{restored: [...], problems}`. */
export const VERSIONS_RESTORE_COMMAND = 'saengine.versions.restore';
/** `{projectRoot, version, label}` -> the version, now issued. */
export const VERSIONS_MARK_ISSUED_COMMAND = 'saengine.versions.markIssued';

export interface IVersionsStatusArgs { readonly projectRoot: string }
export interface IVersionsListArgs { readonly projectRoot: string; readonly limit: number }
export interface IVersionsSaveArgs { readonly projectRoot: string; readonly message: string; readonly author?: string; readonly issued: boolean; readonly label?: string }
export interface IVersionsDiffArgs { readonly projectRoot: string; readonly from: string; readonly to?: string }
export interface IVersionsRestoreArgs { readonly projectRoot: string; readonly version: string; readonly parts?: readonly string[] }
export interface IVersionsMarkIssuedArgs { readonly projectRoot: string; readonly version: string; readonly label: string }

/** How many versions the editor lists. */
export const VERSIONS_LIMIT = 200;

export function saveArgs(projectRoot: string, message: string, options: { readonly author?: string; readonly issued?: boolean; readonly label?: string } = {}): IVersionsSaveArgs {
	const label = options.label?.trim();
	const author = options.author?.trim();
	return {
		projectRoot,
		message: message.trim(),
		...(author ? { author } : {}),
		issued: !!options.issued,
		...(options.issued && label ? { label } : {}),
	};
}

/** Compares `from` with `to`, or with the current files when `to` is undefined. */
export function diffArgs(projectRoot: string, from: string, to?: string): IVersionsDiffArgs {
	return to ? { projectRoot, from, to } : { projectRoot, from };
}

/** Restores `parts` (part ids) of `version`; all parts when `parts` is undefined or covers every changed part. */
export function restoreArgs(projectRoot: string, version: string, parts?: readonly string[], allParts?: readonly string[]): IVersionsRestoreArgs {
	const all = !parts || (allParts !== undefined && allParts.every(p => parts.includes(p)));
	return all ? { projectRoot, version } : { projectRoot, version, parts: [...parts] };
}

export function markIssuedArgs(projectRoot: string, version: string, label: string): IVersionsMarkIssuedArgs {
	return { projectRoot, version, label: label.trim() };
}

// ───────────────────────────── the answers ─────────────────────────────

export interface IVersionEntry {
	/** The id the backend takes back (a commit hash). */
	readonly id: string;
	/** The engineer's number (1 for the first version), if the backend numbers them. */
	readonly number?: number;
	readonly message: string;
	readonly author?: string;
	/** When it was saved [ms since the epoch]. */
	readonly time?: number;
	readonly issued: boolean;
	/** The issue label ("Rev B", "Issued for construction"). */
	readonly label?: string;
	/**
	 * Every issue label it carries, oldest first (`label` is the latest). Labels are only ever
	 * added: an issue is a record, so marking a version again adds a label beside the old ones.
	 */
	readonly labels: readonly string[];
	/** The parts it changed (part ids). */
	readonly parts: readonly string[];
}

export interface IVersionsStatus {
	/** Whether the project keeps versions yet (the first save starts it). */
	readonly initialized: boolean;
	/** The latest version. */
	readonly head?: IVersionEntry;
	/** Parts changed since the latest version (part ids). */
	readonly changedParts: readonly string[];
	readonly problems: readonly string[];
	/** The status could not be asked (the command failed): `problems` says why. */
	readonly failed?: boolean;
}

export type ChangeKind = 'added' | 'removed' | 'changed';

export interface IVersionChange {
	readonly kind: ChangeKind;
	/** What changed, in words ("Column C3 section") or as the JSON path. */
	readonly label: string;
	/**
	 * Whether `label` is the backend's own sentence (diff.py's `what`: "Beam B5: section B300x500 →
	 * B300x600", "Grid line A removed"), which already says the values; otherwise the label is a
	 * bare path and the values are shown under it.
	 */
	readonly described: boolean;
	/** The values, when they are plain (a number, a text); an item or a list is left out. */
	readonly before?: string;
	readonly after?: string;
}

export interface IVersionPartDiff {
	/** The part id ('' for files outside the parts, 'project' for the project file and root files). */
	readonly part: string;
	/** The backend's name of the part ("Floor Plan", "Project"), if it gave one. */
	readonly title?: string;
	readonly changes: readonly IVersionChange[];
}

export interface IVersionDiff {
	readonly from?: string;
	readonly to?: string;
	readonly parts: readonly IVersionPartDiff[];
	readonly problems: readonly string[];
}

type Bag = { readonly [key: string]: unknown };

function isBag(value: unknown): value is Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(...values: unknown[]): string | undefined {
	for (const value of values) {
		if (typeof value === 'string' && value.trim()) {
			return value.trim();
		}
		if (typeof value === 'number' && Number.isFinite(value)) {
			return String(value);
		}
	}
	return undefined;
}

function problemsOf(value: unknown): string[] {
	const problems = isBag(value) ? value.problems : undefined;
	return Array.isArray(problems) ? problems.map(p => isBag(p) ? str(p.message, p.text) ?? JSON.stringify(p) : String(p)) : [];
}

/** A time as seconds or milliseconds since the epoch, or an ISO date. */
export function readTime(value: unknown): number | undefined {
	if (typeof value === 'number' && Number.isFinite(value)) {
		// Seconds until the year 5138; milliseconds after 1973.
		return value < 1e11 ? value * 1000 : value;
	}
	if (typeof value === 'string' && value.trim()) {
		const time = Date.parse(value);
		return Number.isNaN(time) ? undefined : time;
	}
	return undefined;
}

/** A part id from an id, a folder name ("05 Floor Plan") or a path inside one ("05 Floor Plan/floor-plan.json"). */
export function readPart(value: unknown): string | undefined {
	const text = str(value);
	if (text === undefined) {
		return undefined;
	}
	const byId = ALL_PARTS.find(part => part.id === text);
	if (byId) {
		return byId.id;
	}
	const head = text.replace(/\\/g, '/').split('/')[0];
	return ALL_PARTS.find(part => part.folder.toLowerCase() === head.toLowerCase())?.id ?? text;
}

function readParts(value: unknown): string[] {
	if (!Array.isArray(value)) {
		return [];
	}
	const parts: string[] = [];
	for (const item of value) {
		const part = readPart(isBag(item) ? item.part ?? item.id ?? item.folder : item);
		if (part !== undefined && !parts.includes(part)) {
			parts.push(part);
		}
	}
	return parts;
}

/** "Engineer A <a@example.com>" (git's author) -> "Engineer A"; the address alone when there is no name. */
function withoutEmail(author: string): string {
	const name = author.replace(/<[^>]*>/g, '').trim();
	return name || author.replace(/[<>]/g, '').trim();
}

/** A plain value as text (numbers without float noise: 6600.000000100001 -> "6600"); undefined for an item or a list. */
function plainValue(value: unknown): string | undefined {
	if (typeof value === 'number' && Number.isFinite(value)) {
		return String(Number(value.toPrecision(10)));
	}
	if (typeof value === 'string' || typeof value === 'boolean') {
		return String(value);
	}
	return undefined;
}

export function readVersion(value: unknown): IVersionEntry | undefined {
	if (!isBag(value)) {
		return undefined;
	}
	const id = str(value.id, value.version, value.sha, value.commit, value.hash);
	if (!id) {
		return undefined;
	}
	const number = typeof value.number === 'number' ? value.number : typeof value.index === 'number' ? value.index : undefined;
	const issuedValue = value.issued;
	const issuedBag = isBag(issuedValue) ? issuedValue : undefined;
	const label = str(issuedBag?.label, value.label, value.issuedLabel, value.issued_label, value.tag);
	const labels = Array.isArray(value.labels) ? value.labels.map(l => str(l)).filter((l): l is string => !!l) : [];
	if (label && !labels.includes(label)) {
		labels.push(label);
	}
	return {
		id,
		number,
		message: str(value.message, value.summary, value.subject) ?? '',
		author: str(value.authorName, value.author_name, typeof value.author === 'string' ? withoutEmail(value.author) : value.author),
		time: readTime(value.time ?? value.timestamp ?? value.date ?? value.saved),
		issued: issuedValue === true || !!issuedBag || (typeof issuedValue === 'string' && !!issuedValue.trim()),
		label: label ?? (typeof issuedValue === 'string' ? str(issuedValue) : undefined),
		labels,
		parts: readParts(value.parts ?? value.changedParts ?? value.changed_parts ?? value.partsChanged ?? value.parts_changed),
	};
}

/**
 * The versions in an answer of `saengine.versions.list` (`{versions}` or a list), in the backend's
 * order: the history, newest first. Not re-sorted by time: a version's time is the clock of the
 * machine that saved it, and projects travel between engineers' machines, so times can disagree
 * with the history.
 */
export function readVersions(value: unknown): IVersionEntry[] {
	const list = Array.isArray(value) ? value : isBag(value) && Array.isArray(value.versions) ? value.versions : [];
	return list.map(readVersion).filter((v): v is IVersionEntry => !!v);
}

export function readStatus(value: unknown): IVersionsStatus {
	if (!isBag(value)) {
		return { initialized: false, changedParts: [], problems: [] };
	}
	const head = readVersion(value.head ?? value.latest ?? value.current);
	const changed = readParts(value.changedParts ?? value.changed_parts ?? value.changed ?? value.parts);
	return {
		initialized: typeof value.initialized === 'boolean' ? value.initialized : !!head,
		head,
		changedParts: changed,
		problems: problemsOf(value),
	};
}

function readChange(value: unknown): IVersionChange | undefined {
	if (typeof value === 'string') {
		return { kind: 'changed', label: value, described: true };
	}
	if (!isBag(value)) {
		return undefined;
	}
	const rawKind = str(value.kind, value.op, value.type, value.change)?.toLowerCase();
	const kind: ChangeKind = rawKind === 'added' || rawKind === 'add' || rawKind === 'new'
		? 'added'
		: rawKind === 'removed' || rawKind === 'remove' || rawKind === 'deleted' || rawKind === 'delete'
			? 'removed'
			: 'changed';
	const path = Array.isArray(value.path) ? value.path.map(String).join('.') : str(value.path, value.pointer);
	const words = str(value.what, value.label, value.text, value.description, value.title);
	const label = words ?? path;
	if (!label) {
		return undefined;
	}
	return {
		kind,
		label,
		described: words !== undefined,
		before: plainValue(value.before ?? value.old ?? value.from),
		after: plainValue(value.after ?? value.new ?? value.to),
	};
}

/**
 * The semantic diff in an answer of `saengine.versions.diff`: `{parts: [{part, changes}]}`, or a
 * flat `{changes: [{part, ...}]}`, grouped by part in workflow order.
 */
export function readDiff(value: unknown): IVersionDiff {
	if (!isBag(value)) {
		return { parts: [], problems: [] };
	}
	const groups = new Map<string, IVersionChange[]>();
	const titles = new Map<string, string>();
	const add = (part: string, change: IVersionChange | undefined) => {
		if (change) {
			const list = groups.get(part) ?? [];
			list.push(change);
			groups.set(part, list);
		}
	};
	const parts = value.parts;
	if (Array.isArray(parts)) {
		for (const entry of parts) {
			if (!isBag(entry)) {
				continue;
			}
			const part = readPart(entry.part ?? entry.id ?? entry.folder) ?? '';
			const title = str(entry.title);
			if (title) {
				titles.set(part, title);
			}
			const changes = Array.isArray(entry.changes) ? entry.changes : [];
			if (!changes.length) {
				// A part that changed without details (a binary file, a cache).
				add(part, { kind: entry.kind === 'added' ? 'added' : entry.kind === 'removed' ? 'removed' : 'changed', label: str(entry.summary, entry.text) ?? localize('versions.partChanged', "Changed"), described: true });
			}
			for (const change of changes) {
				add(part, readChange(change));
			}
		}
	} else if (isBag(parts)) {
		for (const [key, changes] of Object.entries(parts)) {
			for (const change of Array.isArray(changes) ? changes : []) {
				add(readPart(key) ?? key, readChange(change));
			}
		}
	}
	if (Array.isArray(value.changes)) {
		for (const change of value.changes) {
			// A file outside the part folders (the project file, notes) goes under "Other files".
			const ofFile = isBag(change) && change.part === undefined ? readPart(change.file) : undefined;
			const part = !isBag(change) ? '' : change.part !== undefined ? readPart(change.part) ?? '' : ALL_PARTS.some(p => p.id === ofFile) ? ofFile! : '';
			add(part, readChange(change));
		}
	}
	return {
		from: str(value.from),
		to: str(value.to),
		parts: sortByWorkflow([...groups].map(([part, changes]) => titles.has(part) ? { part, title: titles.get(part), changes } : { part, changes })),
		problems: problemsOf(value),
	};
}

function workflowIndex(part: string): number {
	const index = ALL_PARTS.findIndex(p => p.id === part);
	return index < 0 ? ALL_PARTS.length : index;
}

function sortByWorkflow<T extends { readonly part: string }>(items: T[]): T[] {
	return items.sort((a, b) => workflowIndex(a.part) - workflowIndex(b.part));
}

// ───────────────────────────── the texts ─────────────────────────────

/** The backend's part id of the project file (`<name>.saengine`) and the other files at the project's root. */
export const PROJECT_FILES_PART = 'project';

/**
 * "Floor Plan" for a part id; "Project file" for {@link PROJECT_FILES_PART}, "Other files" for '';
 * the backend's `title`, else the id itself, for anything else.
 */
export function partLabel(part: string, parts: readonly IProjectPart[] = ALL_PARTS, title?: string): string {
	if (!part) {
		return localize('versions.otherFiles', "Other files");
	}
	if (part === PROJECT_FILES_PART) {
		return localize('versions.projectFiles', "Project file");
	}
	const known = parts.find(p => p.id === part) ?? ALL_PARTS.find(p => p.id === part);
	return known ? partName(known) : title ?? part;
}

/** "v12", or the short id when the backend does not number its versions. */
export function versionName(version: IVersionEntry): string {
	return version.number !== undefined ? localize('versions.number', "v{0}", version.number) : version.id.slice(0, 7);
}

/** "v12 · Column sizes after the wind check". */
export function versionTitle(version: IVersionEntry): string {
	return version.message ? localize('versions.title', "{0} · {1}", versionName(version), version.message) : versionName(version);
}

/** "Issued · Rev B" / "Issued · Rev A, Rev B" (every label, oldest first) / "Issued". */
export function issuedBadge(version: IVersionEntry): string | undefined {
	if (!version.issued) {
		return undefined;
	}
	const labels = version.labels.length ? version.labels : version.label ? [version.label] : [];
	return labels.length ? localize('versions.issuedLabel', "Issued · {0}", labels.join(', ')) : localize('versions.issued', "Issued");
}

/** Whether `version` already carries the issue label `label` (labels compare as the backend does: trimmed, case kept). */
export function hasIssueLabel(version: IVersionEntry, label: string): boolean {
	const wanted = label.trim();
	return version.labels.includes(wanted) || version.label === wanted;
}

/** "just now", "5 min ago", "3 h ago", "yesterday", "4 days ago", or the date. */
export function relativeTime(time: number | undefined, now: number): string {
	if (time === undefined) {
		return '';
	}
	const seconds = Math.round((now - time) / 1000);
	if (seconds < 60) {
		return localize('versions.justNow', "just now");
	}
	const minutes = Math.round(seconds / 60);
	if (minutes < 60) {
		return localize('versions.minutesAgo', "{0} min ago", minutes);
	}
	const hours = Math.round(minutes / 60);
	if (hours < 24) {
		return localize('versions.hoursAgo', "{0} h ago", hours);
	}
	const days = Math.round(hours / 24);
	if (days === 1) {
		return localize('versions.yesterday', "yesterday");
	}
	if (days < 7) {
		return localize('versions.daysAgo', "{0} days ago", days);
	}
	const date = new Date(time);
	return formatDate(date, { day: 'numeric', month: 'short', year: date.getFullYear() === new Date(now).getFullYear() ? undefined : 'numeric' });
}

/** "Floor Plan, BIM" / "Floor Plan, BIM, FEM +2" / "No part changed". */
export function partsSummary(parts: readonly string[], max = 3): string {
	if (!parts.length) {
		return localize('versions.noParts', "No part changed");
	}
	const names = parts.slice(0, max).map(p => partLabel(p));
	return parts.length > max
		? localize('versions.partsMore', "{0} +{1}", names.join(', '), parts.length - max)
		: names.join(', ');
}

/** "Jane · 5 min ago · Floor Plan, BIM". */
export function versionDetail(version: IVersionEntry, now: number): string {
	return [version.author, relativeTime(version.time, now), version.parts.length ? partsSummary(version.parts) : undefined].filter(Boolean).join(' · ');
}

/** What the sidebar and the Versions editor say about the files against the latest version. */
export interface IUnsavedSummary {
	readonly text: string;
	/** Whether there is something to save. */
	readonly dirty: boolean;
	/** The backend's problems (a project inside another git repository, a failed status), to show with it. */
	readonly problem?: string;
}

/** The parts changed since the latest version: those the backend sees on disk, then those with edits not saved yet. */
export function pendingParts(status: IVersionsStatus | undefined, edited: readonly string[] = []): string[] {
	const parts = [...(status?.changedParts ?? [])];
	for (const part of edited) {
		if (!parts.includes(part)) {
			parts.push(part);
		}
	}
	return parts;
}

/**
 * What the files are against the latest version. `edited` are the parts with edits in an editor not
 * saved to disk yet: the backend does not see them, but Save Version saves them first, so they count.
 */
export function unsavedSummary(status: IVersionsStatus | undefined, edited: readonly string[] = []): IUnsavedSummary | undefined {
	if (!status) {
		return undefined;
	}
	const problem = status.problems.length ? status.problems.join(' ') : undefined;
	const withProblem = (summary: IUnsavedSummary): IUnsavedSummary => problem ? { ...summary, problem } : summary;
	if (status.failed) {
		return withProblem({ text: localize('versions.unreadable', "Versions could not be read"), dirty: false });
	}
	const count = pendingParts(status, edited).length;
	if (!status.initialized || !status.head) {
		// Not kept at all (e.g. inside another git repository) when the backend says why.
		return problem
			? { text: localize('versions.notKept', "Versions are not kept for this project"), dirty: false, problem }
			: { text: localize('versions.none', "No version saved yet"), dirty: true };
	}
	const name = versionName(status.head);
	if (!count) {
		return withProblem({ text: localize('versions.clean', "No changes since {0}", name), dirty: false });
	}
	return withProblem({
		text: count === 1
			? localize('versions.changedOne', "1 part changed since {0}", name)
			: localize('versions.changedMany', "{0} parts changed since {1}", count, name),
		dirty: true,
	});
}

export interface IChangeLine {
	readonly kind: ChangeKind;
	readonly text: string;
	/** "300×300 → 350×350", when the values are known. */
	readonly values?: string;
}

export interface IChangeGroup {
	readonly part: string;
	readonly title: string;
	/** "3 changes". */
	readonly count: string;
	readonly lines: readonly IChangeLine[];
	/** Lines not shown (beyond `maxLines`). */
	readonly more: number;
}

function shorten(text: string, max = 48): string {
	return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** The diff as the Versions editor shows it: a group per part, at most `maxLines` lines each. */
export function changeGroups(diff: IVersionDiff, maxLines = 50): IChangeGroup[] {
	return diff.parts.filter(p => p.changes.length).map(({ part, title, changes }) => ({
		part,
		title: partLabel(part, ALL_PARTS, title),
		count: changes.length === 1 ? localize('versions.changeOne', "1 change") : localize('versions.changeMany', "{0} changes", changes.length),
		lines: changes.slice(0, maxLines).map(change => ({
			kind: change.kind,
			text: change.label,
			// The backend's words carry the values already ("Beam B5: section B300x500 → B300x600",
			// "Grid line A removed"); a bare path gets its plain values under it.
			values: change.described || (change.after !== undefined && change.label.includes(change.after)) ? undefined
				: change.kind === 'changed' && change.before !== undefined && change.after !== undefined
				? localize('versions.values', "{0} → {1}", shorten(change.before), shorten(change.after))
				: change.kind === 'added' && change.after !== undefined ? shorten(change.after)
					: change.kind === 'removed' && change.before !== undefined ? shorten(change.before) : undefined,
		})),
		more: Math.max(0, changes.length - maxLines),
	}));
}

/** "v11 → current files", "v11 → v12". */
export function compareTitle(from: IVersionEntry, to: IVersionEntry | undefined): string {
	return to
		? localize('versions.compareTwo', "{0} → {1}", versionName(from), versionName(to))
		: localize('versions.compareCurrent', "{0} → current files", versionName(from));
}

/**
 * The confirmation of a restore: what it replaces, in words. As the backend's `versions.restore()`
 * does it: the unsaved changes (anywhere in the project) are first saved as a version of their own
 * ("Before restoring version N"), the chosen parts are replaced, and the restore is saved as a new
 * version, so nothing is lost and no version is rewritten. `unsavedParts` must include the parts
 * with edits still open in an editor: the restore flow saves those to disk first, so that the
 * backend keeps them too.
 */
export function restoreConfirmation(version: IVersionEntry, parts: readonly string[], unsavedParts: readonly string[]): { readonly message: string; readonly detail: string } {
	const names = parts.map(p => partLabel(p)).join(', ');
	const unsaved = unsavedParts.map(p => partLabel(p)).join(', ');
	const detail = [
		localize('versions.restoreDetail', "These parts will be replaced by their state in {0}: {1}.", versionName(version), names),
		unsavedParts.length
			? localize('versions.restoreKeepsUnsaved', "Your unsaved changes (in {0}) are first saved as a version of their own, so nothing is lost.", unsaved)
			: undefined,
		localize('versions.restoreRecorded', "The restore is then saved as a new version; the earlier versions stay as they are."),
	].filter(Boolean).join('\n\n');
	return {
		message: localize('versions.restoreMessage', "Restore {0}?", versionTitle(version)),
		detail,
	};
}

// ───────────────────────────── selection ─────────────────────────────

/**
 * The selection after a click on `id`: a plain click selects it alone; a click with Ctrl (or
 * Shift) adds it, keeping at most two, or takes it out again.
 */
export function nextSelection(selected: readonly string[], id: string, additive: boolean): string[] {
	if (!additive) {
		return [id];
	}
	if (selected.includes(id)) {
		return selected.filter(s => s !== id);
	}
	return [...selected, id].slice(-2);
}

/**
 * What the selection compares: one version with the current files, or two versions, the older
 * (lower in the newest-first list) first.
 */
export function compareRange(versions: readonly IVersionEntry[], selected: readonly string[]): { readonly from: IVersionEntry; readonly to?: IVersionEntry } | undefined {
	const picked = selected.map(id => ({ index: versions.findIndex(v => v.id === id), id })).filter(p => p.index >= 0).sort((a, b) => b.index - a.index);
	if (!picked.length) {
		return undefined;
	}
	const from = versions[picked[0].index];
	return picked.length > 1 ? { from, to: versions[picked[1].index] } : { from };
}
