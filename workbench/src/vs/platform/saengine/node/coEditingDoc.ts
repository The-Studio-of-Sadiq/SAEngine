/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type * as Yjs from 'yjs';

/*
 * A part document (JSON) as a shared Yjs document, so that edits merge object by object:
 *
 * - An object is a Y.Map of its fields; a field edited by two engineers keeps the later edit.
 * - A list of objects that all have a unique string `id` (members, storeys, grids, columns) is a
 *   Y.Map from id to object plus a Y.Array with the ids' order. Two engineers adding members
 *   both keep theirs, and a member deleted by one and edited by the other stays deleted.
 * - Any other list (coordinates, bar lists) is one value, like a number or a string.
 *
 * `writeJson` changes the Yjs document into the given JSON with the fewest changes, comparing with
 * what the document holds now; `readJson` gives the document back as JSON.
 */

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type JsonObject = { [key: string]: Json };

/** The marker field of a list-of-objects-by-id. */
const KIND = '\u0000kind';
const ID_LIST = 'idList';
const ITEMS = 'items';
const ORDER = 'order';
/** A document whose top level is not an object is kept under this key. */
const ROOT_VALUE = '\u0000value';

export const ROOT_NAME = 'part';

function isObject(value: Json | undefined): value is JsonObject {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function has(object: JsonObject, key: string): boolean {
	return Object.prototype.hasOwnProperty.call(object, key);
}

/** A list of objects that all have a distinct string id. */
function isIdList(value: Json | undefined): value is JsonObject[] {
	if (!Array.isArray(value) || value.length === 0) {
		return false;
	}
	const ids = new Set<string>();
	for (const item of value) {
		if (!isObject(item) || typeof item.id !== 'string' || ids.has(item.id)) {
			return false;
		}
		ids.add(item.id);
	}
	return true;
}

function sameJson(a: Json | undefined, b: Json | undefined): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}

export interface IJsonDocs {
	/** The part as JSON; `template` (the window's JSON) keeps its key order. Undefined: an empty room. */
	readJson(doc: Yjs.Doc, template?: Json): Json | undefined;
	/** Changes the document into `next` with the fewest changes, in one transaction. */
	writeJson(doc: Yjs.Doc, next: Json, origin?: unknown): void;
}

/** The JSON mapping over a loaded Yjs (see `coEditingLibs.ts`). */
export function jsonDocs(Y: typeof Yjs): IJsonDocs {

	const isIdListMap = (value: unknown): value is Yjs.Map<unknown> => value instanceof Y.Map && value.get(KIND) === ID_LIST;

	/** A Yjs value for a JSON value (not yet in a document). */
	const toY = (value: Json): unknown => {
		if (isIdList(value)) {
			const list = new Y.Map<unknown>();
			list.set(KIND, ID_LIST);
			const items = new Y.Map<unknown>();
			for (const item of value) {
				items.set(item.id as string, toY(item));
			}
			list.set(ITEMS, items);
			const order = new Y.Array<string>();
			order.push(value.map(item => item.id as string));
			list.set(ORDER, order);
			return list;
		}
		if (isObject(value)) {
			const map = new Y.Map<unknown>();
			for (const [key, field] of Object.entries(value)) {
				map.set(key, toY(field));
			}
			return map;
		}
		// Lists that are not lists of objects by id, and plain values, are one value.
		return value;
	};

	/** The JSON of a Yjs value; `template` keeps its key order. */
	const fromY = (value: unknown, template?: Json): Json => {
		if (isIdListMap(value)) {
			const items = value.get(ITEMS) as Yjs.Map<unknown>;
			const order = (value.get(ORDER) as Yjs.Array<string>).toArray();
			const byId = new Map<string, Json>();
			if (Array.isArray(template)) {
				for (const item of template) {
					if (isObject(item) && typeof item.id === 'string') {
						byId.set(item.id, item);
					}
				}
			}
			const result: Json[] = [];
			const seen = new Set<string>();
			// Concurrent additions can repeat an id in the order; the first one counts.
			for (const id of [...order, ...items.keys()]) {
				if (seen.has(id) || !items.has(id)) {
					continue;
				}
				seen.add(id);
				result.push(fromY(items.get(id), byId.get(id)));
			}
			return result;
		}
		if (value instanceof Y.Map) {
			const result: JsonObject = {};
			const keys = [...value.keys()];
			const ordered = isObject(template) ? [...Object.keys(template).filter(k => value.has(k)), ...keys.filter(k => !has(template, k))] : keys;
			for (const key of ordered) {
				result[key] = fromY(value.get(key), isObject(template) ? template[key] : undefined);
			}
			return result;
		}
		return value as Json;
	};

	const writeObject = (map: Yjs.Map<unknown>, next: JsonObject): void => {
		for (const key of [...map.keys()]) {
			if (!has(next, key)) {
				map.delete(key);
			}
		}
		for (const [key, value] of Object.entries(next)) {
			writeField(map, key, value);
		}
	};

	const writeField = (map: Yjs.Map<unknown>, key: string, value: Json): void => {
		const current = map.get(key);
		if (isIdList(value) && isIdListMap(current)) {
			writeIdList(current, value);
		} else if (isObject(value) && current instanceof Y.Map && !isIdListMap(current)) {
			writeObject(current, value);
		} else if (current === undefined || current instanceof Y.AbstractType || !sameJson(current as Json, value)) {
			map.set(key, toY(value));
		}
	};

	const writeIdList = (list: Yjs.Map<unknown>, next: JsonObject[]): void => {
		const items = list.get(ITEMS) as Yjs.Map<unknown>;
		const order = list.get(ORDER) as Yjs.Array<string>;
		const nextIds = next.map(item => item.id as string);
		const keep = new Set(nextIds);
		for (const id of [...items.keys()]) {
			if (!keep.has(id)) {
				items.delete(id);
			}
		}
		for (const item of next) {
			const id = item.id as string;
			const current = items.get(id);
			if (current instanceof Y.Map && !isIdListMap(current)) {
				writeObject(current, item);
			} else {
				items.set(id, toY(item));
			}
		}
		// The order is only rewritten when the ids' order or set changed.
		const all = order.toArray();
		const currentOrder = all.filter((id, index) => keep.has(id) && all.indexOf(id) === index);
		if (all.length !== nextIds.length || currentOrder.some((id, index) => id !== nextIds[index])) {
			order.delete(0, order.length);
			order.push(nextIds);
		}
	};

	return {
		readJson(doc, template) {
			const root = doc.getMap<unknown>(ROOT_NAME);
			if (root.size === 0) {
				return undefined;
			}
			if (root.has(ROOT_VALUE)) {
				return fromY(root.get(ROOT_VALUE), template);
			}
			return fromY(root, template);
		},
		writeJson(doc, next, origin) {
			const root = doc.getMap<unknown>(ROOT_NAME);
			doc.transact(() => {
				if (isObject(next)) {
					if (root.has(ROOT_VALUE)) {
						root.delete(ROOT_VALUE);
					}
					writeObject(root, next);
				} else {
					for (const key of [...root.keys()]) {
						if (key !== ROOT_VALUE) {
							root.delete(key);
						}
					}
					writeField(root, ROOT_VALUE, next);
				}
			}, origin);
		},
	};
}

/** The indentation of a JSON text: a tab, or the first indented line's spaces (a tab by default). */
export function detectIndent(text: string): string {
	const match = /\n([ \t]+)\S/.exec(text);
	if (!match) {
		return '\t';
	}
	return match[1].startsWith('\t') ? '\t' : match[1];
}

/** The JSON as the part file holds it: the window's indentation, line ends and final new line. */
export function formatJson(value: Json, like: string): string {
	const text = JSON.stringify(value, undefined, detectIndent(like));
	const eol = like.includes('\r\n') ? '\r\n' : '\n';
	const withEol = eol === '\n' ? text : text.replace(/\n/g, '\r\n');
	return /\r?\n\s*$/.test(like) ? withEol + eol : withEol;
}

/** The JSON of a part file's text, or undefined when the text is not JSON (mid-edit in a text editor). */
export function parseJson(text: string): Json | undefined {
	try {
		return JSON.parse(text) as Json;
	} catch {
		return undefined;
	}
}
