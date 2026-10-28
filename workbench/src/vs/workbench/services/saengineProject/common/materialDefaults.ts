/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/** The categories a project names its material of choice for (`03 Materials/materials.json` `defaults`). */
export type DefaultCategory = 'concrete' | 'rebar';

const CATEGORIES: readonly DefaultCategory[] = ['concrete', 'rebar'];

interface IMaterialsDocument {
	materials?: unknown;
	defaults?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function entries(document: unknown): { id: string; category: unknown }[] {
	const list = isRecord(document) && Array.isArray((document as IMaterialsDocument).materials) ? (document as IMaterialsDocument).materials as unknown[] : [];
	return list.filter(isRecord).filter(m => typeof m.id === 'string').map(m => ({ id: m.id as string, category: m.category }));
}

/**
 * The project's concrete or reinforcing bars: the materials file's `defaults` entry (New Building
 * from Grid records the wizard's choice there), else the first material of the category, as
 * `MaterialLibrary.default_concrete` / `default_rebar` in Python.
 */
export function projectMaterial(document: unknown, category: DefaultCategory): string | undefined {
	const ids = entries(document).filter(m => m.category === category).map(m => m.id);
	const defaults = isRecord(document) && isRecord(document.defaults) ? document.defaults : undefined;
	const chosen = defaults?.[category];
	return typeof chosen === 'string' && ids.includes(chosen) ? chosen : ids[0];
}

/**
 * Keeps the materials file's `defaults` valid after an edit of its list (in place): a default
 * whose material was renamed from `renamedFrom` follows it, and one that no longer names a
 * material of its category (deleted, or its category changed) is dropped, as is an empty
 * `defaults`. Returns whether anything changed.
 */
export function keepMaterialDefaults(document: Record<string, unknown>, renamedFrom?: string, renamedTo?: string): boolean {
	const defaults = document.defaults;
	if (!isRecord(defaults)) {
		return false;
	}
	const list = entries(document);
	let changed = false;
	for (const category of CATEGORIES) {
		const chosen = defaults[category];
		if (chosen === undefined) {
			continue;
		}
		if (renamedFrom !== undefined && renamedTo !== undefined && chosen === renamedFrom && list.some(m => m.id === renamedTo && m.category === category)) {
			defaults[category] = renamedTo;
			changed = true;
		} else if (typeof chosen !== 'string' || !list.some(m => m.id === chosen && m.category === category)) {
			delete defaults[category];
			changed = true;
		}
	}
	if (!Object.keys(defaults).length) {
		delete document.defaults;
		changed = true;
	}
	return changed;
}
