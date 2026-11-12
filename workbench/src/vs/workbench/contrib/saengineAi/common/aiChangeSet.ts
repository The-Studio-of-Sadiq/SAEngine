/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { findNodeAtLocation, getNodeValue, JSONPath, parseTree, ParseError } from '../../../../base/common/json.js';
import { applyEdits, removeProperty, setProperty } from '../../../../base/common/jsonEdit.js';
import { FormattingOptions } from '../../../../base/common/jsonFormatter.js';
import { safeRelativePath } from './aiTools.js';

/*
 * A change set an AI assistant proposes: edits to the project's JSON part files that the
 * engineer previews and accepts (or rejects) as one undoable step. Nothing is applied by the
 * proposal itself. Pure: checking the proposal and working out each file's new text and the
 * values before and after, so it is unit tested; the window applies the texts through the text
 * models (one undo group over every file), as the design proposal does.
 */

/** Most changes in one set: a bigger edit is a new building (the wizard) or a script. */
export const MAX_CHANGES = 200;
/** Folders an assistant never edits: results and exports are SAEngine's own output. */
const READ_ONLY_FOLDERS = [/(^|\/)model\.results(\/|$)/i, /^11 Exports(\/|$)/i, /(^|\/)\.saengine(\/|$)/i, /(^|\/)\.git(\/|$)/i];

export interface IAiChange {
	/** A `.json` file relative to the project folder. */
	readonly file: string;
	readonly path: JSONPath;
	/** The new value; absent with `remove`. */
	readonly value?: unknown;
	readonly remove?: boolean;
	/** Why, in the assistant's words, shown to the engineer. */
	readonly reason?: string;
}

export interface IAiChangeSetProposal {
	readonly title: string;
	readonly changes: readonly IAiChange[];
}

/** The proposal as the assistant sent it, checked: the changes or the problems. */
export function readProposal(raw: unknown): { readonly proposal?: IAiChangeSetProposal; readonly problems: string[] } {
	const bag = typeof raw === 'object' && raw !== null ? raw as Record<string, unknown> : {};
	const problems: string[] = [];
	const title = typeof bag.title === 'string' && bag.title.trim() ? bag.title.trim().slice(0, 200) : undefined;
	if (!title) {
		problems.push('"title" is missing');
	}
	if (!Array.isArray(bag.changes) || bag.changes.length === 0) {
		problems.push('"changes" must be a non-empty list');
		return { problems };
	}
	if (bag.changes.length > MAX_CHANGES) {
		problems.push(`at most ${MAX_CHANGES} changes in one set`);
		return { problems };
	}
	const changes: IAiChange[] = [];
	bag.changes.forEach((item, index) => {
		const change = typeof item === 'object' && item !== null ? item as Record<string, unknown> : {};
		const where = `changes[${index}]`;
		const file = typeof change.file === 'string' ? safeRelativePath(change.file) : undefined;
		if (!file || !/\.json$/i.test(file)) {
			problems.push(`${where}: "file" must be a .json file inside the project`);
			return;
		}
		if (READ_ONLY_FOLDERS.some(pattern => pattern.test(file))) {
			problems.push(`${where}: ${file} is SAEngine's output and is not edited`);
			return;
		}
		const path = change.path;
		if (!Array.isArray(path) || path.length === 0 || !path.every(p => typeof p === 'string' || (typeof p === 'number' && Number.isInteger(p) && p >= -1))) {
			problems.push(`${where}: "path" must be a non-empty list of property names and array indexes`);
			return;
		}
		const remove = change.remove === true;
		if (!remove && !Object.prototype.hasOwnProperty.call(change, 'value')) {
			problems.push(`${where}: give "value", or "remove": true`);
			return;
		}
		changes.push({
			file,
			path: path as JSONPath,
			...(remove ? { remove: true } : { value: change.value }),
			...(typeof change.reason === 'string' && change.reason.trim() ? { reason: change.reason.trim().slice(0, 500) } : {}),
		});
	});
	return problems.length ? { problems } : { proposal: { title: title!, changes }, problems };
}

/** One change as the preview shows it. */
export interface IPlannedChange {
	readonly change: IAiChange;
	readonly before: unknown;
	/** Whether the property is there before (else it is added). */
	readonly existed: boolean;
	readonly after: unknown;
	/** It would change nothing. */
	readonly noop: boolean;
}

export interface IPlannedFile {
	readonly file: string;
	readonly newText: string;
	readonly changes: readonly IPlannedChange[];
}

/**
 * The new text of one file with its changes applied in order (each through the JSON editor, so
 * the formatting and comments of the rest stay), with the values before and after. Throws when
 * the file is not valid JSON now.
 */
export function planFile(file: string, text: string, changes: readonly IAiChange[], formatting: FormattingOptions): IPlannedFile {
	const errors: ParseError[] = [];
	parseTree(text, errors);
	if (errors.length) {
		throw new Error(`${file} is not valid JSON now`);
	}
	let current = text;
	const planned: IPlannedChange[] = [];
	for (const change of changes) {
		const before = valueAt(current, change.path);
		const edits = change.remove ? removeProperty(current, change.path, formatting) : setProperty(current, change.path, change.value, formatting);
		const next = applyEdits(current, edits);
		const after = valueAt(next, change.path);
		planned.push({
			change,
			before: before.value,
			existed: before.found,
			after: change.remove ? undefined : after.value,
			noop: next === current,
		});
		current = next;
	}
	return { file, newText: current, changes: planned };
}

export function valueAt(text: string, path: JSONPath): { readonly found: boolean; readonly value: unknown } {
	const root = parseTree(text);
	const node = root ? findNodeAtLocation(root, path) : undefined;
	return node ? { found: true, value: getNodeValue(node) } : { found: false, value: undefined };
}

/** The changes grouped by file, in the order the files first appear. */
export function changesByFile(changes: readonly IAiChange[]): Map<string, IAiChange[]> {
	const byFile = new Map<string, IAiChange[]>();
	for (const change of changes) {
		const key = change.file.toLowerCase();
		const list = byFile.get(key) ?? [];
		list.push(change);
		byFile.set(key, list);
	}
	return byFile;
}

/** A value for the preview: short JSON, cut when long. */
export function previewValue(value: unknown, found = true, length = 120): string {
	if (!found) {
		return '—';
	}
	const text = value === undefined ? '—' : JSON.stringify(value);
	return text.length > length ? `${text.slice(0, length)}…` : text;
}

/** A path for the preview: `stories[0].height`. */
export function previewPath(path: JSONPath): string {
	return path.map((segment, index) => typeof segment === 'number' ? `[${segment}]` : index === 0 ? segment : `.${segment}`).join('');
}
