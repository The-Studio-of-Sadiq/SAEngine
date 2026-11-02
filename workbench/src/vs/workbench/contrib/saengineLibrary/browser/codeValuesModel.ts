/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { JsonObject, JsonValue } from './schemaForm.js';

/*
 * Project Settings > Code Values: the values of the project's code pack, each of which the
 * project may override (the setting `codeOverrides`: a value's path → the project's value). The
 * backend (`saengine.codes.overrides`) merges the overrides over the pack for every run and
 * checks them against the pack's tables; this module reads its answer tolerantly and edits the
 * overrides in the settings document.
 */

/** `{ settingsText, root?, table? }` → the pack with the overrides, and the values of `table`. */
export const CODES_VALUES_COMMAND = 'saengine.codes.values';

/** The settings key of the overrides. */
export const CODE_OVERRIDES_KEY = 'codeOverrides';

/** One value of the pack as the page lists it. */
export interface ICodeValueRow {
	/** The value's path, table first ("factors.phi.shear"). */
	readonly path: string;
	readonly table: string;
	/** The value in force (the project's when overridden). */
	readonly value: JsonValue;
	/** The code pack's own value. */
	readonly packValue: JsonValue;
	readonly overridden: boolean;
	/** The pack does not give it: a generic default (SAEngine practice). */
	readonly generic: boolean;
	/** Where a generic default comes from. */
	readonly note: string;
}

export interface ICodeValues {
	readonly id: string;
	/** The pack's display name ("BNBC 2020"). */
	readonly name: string;
	/** The pack the project asked for when it is not installed (the default pack stands in). */
	readonly missing: string | undefined;
	readonly tables: readonly { readonly name: string; readonly overridden: boolean; readonly generic: boolean }[];
	readonly overrides: readonly { readonly path: string; readonly packValue: JsonValue; readonly value: JsonValue }[];
	/** Overrides refused (not applied), with why. */
	readonly problems: readonly { readonly path: string; readonly message: string }[];
	readonly fallbacks: readonly { readonly path: string; readonly value: JsonValue; readonly note: string }[];
	readonly rows: readonly ICodeValueRow[];
}

type Raw = { readonly [key: string]: unknown };

function isRaw(value: unknown): value is Raw {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Raw[] {
	return Array.isArray(value) ? value.filter(isRaw) : [];
}

function str(value: unknown, fallback = ''): string {
	return typeof value === 'string' ? value : fallback;
}

/** `saengine.codes.values`'s answer; undefined for a refusal or no answer. */
export function readCodeValues(value: unknown): ICodeValues | undefined {
	if (!isRaw(value) || value.ok === false || typeof value.id !== 'string') {
		return undefined;
	}
	return {
		id: value.id,
		name: str(value.name, value.id),
		missing: typeof value.missing === 'string' && value.missing ? value.missing : undefined,
		tables: list(value.tables).filter(t => typeof t.name === 'string').map(t => ({ name: String(t.name), overridden: t.overridden === true, generic: t.generic === true })),
		overrides: list(value.overrides).filter(o => typeof o.path === 'string').map(o => ({ path: String(o.path), packValue: o.packValue as JsonValue, value: o.value as JsonValue })),
		problems: list(value.problems).filter(p => typeof p.path === 'string').map(p => ({ path: String(p.path), message: str(p.message) })),
		fallbacks: list(value.fallbacks).filter(f => typeof f.path === 'string').map(f => ({ path: String(f.path), value: f.value as JsonValue, note: str(f.note) })),
		rows: list(value.rows).filter(r => typeof r.path === 'string').map(r => ({
			path: String(r.path),
			table: str(r.table),
			value: r.value as JsonValue,
			packValue: r.packValue as JsonValue,
			overridden: r.overridden === true,
			generic: r.generic === true,
			note: str(r.note),
		})),
	};
}

/** A value as the page shows it: numbers as given, lists and groups as JSON. */
export function formatCodeValue(value: JsonValue | undefined): string {
	if (value === undefined || value === null) {
		return '–';
	}
	return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/**
 * The project's value typed for a pack value of `like`'s type: a number, true or false, text, or
 * JSON for a list or group. `{ value: undefined }` for an empty field (the pack's value again).
 */
export function parseCodeValue(text: string, like: JsonValue): { readonly value?: JsonValue; readonly error?: string } {
	const trimmed = text.trim();
	if (!trimmed) {
		return { value: undefined };
	}
	if (typeof like === 'number') {
		const n = Number(trimmed);
		return isFinite(n) ? { value: n } : { error: localize('codeValues.number', "Enter a number.") };
	}
	if (typeof like === 'boolean') {
		return trimmed === 'true' || trimmed === 'false' ? { value: trimmed === 'true' } : { error: localize('codeValues.boolean', "Enter true or false.") };
	}
	if (typeof like === 'string') {
		return { value: trimmed };
	}
	if (like === null) {
		// No value to follow (the pack's is empty): a number, true or false, JSON, else text.
		try {
			return { value: JSON.parse(trimmed) as JsonValue };
		} catch {
			return { value: trimmed };
		}
	}
	try {
		const value = JSON.parse(trimmed) as JsonValue;
		if (Array.isArray(like) !== Array.isArray(value) || typeof value !== typeof like) {
			return { error: Array.isArray(like) ? localize('codeValues.list', "Enter a list, as [1, 2].") : localize('codeValues.group', "Enter a group of values, as {\"a\": 1}.") };
		}
		return { value };
	} catch {
		return { error: localize('codeValues.json', "Enter the value as the pack writes it (JSON).") };
	}
}

/** The overrides of the settings `document` (empty when it has none). */
export function codeOverrides(document: JsonObject | undefined): JsonObject {
	const value = document?.[CODE_OVERRIDES_KEY];
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as JsonObject : {};
}

/** Sets (or, with `undefined`, removes) the override of `path` in the settings `document`; the key goes when none is left. Returns whether anything changed. */
export function setCodeOverride(document: JsonObject, path: string, value: JsonValue | undefined): boolean {
	const overrides = { ...codeOverrides(document) };
	if (value === undefined) {
		if (!(path in overrides)) {
			return false;
		}
		delete overrides[path];
	} else {
		if (JSON.stringify(overrides[path]) === JSON.stringify(value)) {
			return false;
		}
		overrides[path] = value;
	}
	if (Object.keys(overrides).length) {
		document[CODE_OVERRIDES_KEY] = overrides;
	} else {
		delete document[CODE_OVERRIDES_KEY];
	}
	return true;
}

/** The rows `filter` keeps (words in the path, any order, any case). */
export function filterCodeValues(rows: readonly ICodeValueRow[], filter: string): ICodeValueRow[] {
	const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
	return rows.filter(r => words.every(w => r.path.toLowerCase().includes(w)));
}
