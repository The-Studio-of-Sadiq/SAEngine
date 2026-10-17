/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { StringSHA1 } from '../../../../base/common/hash.js';
import { DEFAULT_FLOOR_PLAN } from './projectLibraries.generated.js';

/*
 * How the parts of a project connect. Each part owns its main file and is the only one that
 * writes it; it reads the files of the parts upstream of it, never writes them. A file derived
 * from upstream files records, under `source`, the stamp of each upstream file it was built
 * from, so its editor can tell when an upstream file has changed since and offer to update.
 * Nothing is regenerated without the engineer asking.
 */

/**
 * The parts each derived part can be built from, by part id (one-way: upstream to downstream).
 * A project has one of them: the building model comes from the floor plan of a building or the
 * structural model of a special structure (see `upstreamPart`).
 */
export const UPSTREAM_PARTS: { readonly [part: string]: readonly string[] } = {
	bim: ['floorPlan', 'structure'],
};

/** The part `part` is built from in a project with `parts`, if any. */
export function upstreamPart(part: string, parts: readonly { readonly id: string }[]): string | undefined {
	return UPSTREAM_PARTS[part]?.find(id => parts.some(p => p.id === id));
}

/**
 * The stamp of an upstream file: SHA-1 of its text with line endings normalised. The Python
 * side (`saengine.library.bim.source_stamp`) computes the same.
 */
export function sourceStamp(text: string): string {
	const sha = new StringSHA1();
	sha.update(text.replace(/\r\n/g, '\n'));
	return sha.digest();
}

/**
 * The stamp of the finished ground level of the project settings in `settingsText` (to the
 * micrometre; 0 when not set), the only setting the bill of quantities depends on. The Python
 * side (`saengine.library.bim.ground_level_stamp`) computes the same. A text that is not valid
 * JSON gets the stamp of its text, which no bill records.
 */
export function groundLevelStamp(settingsText: string): string {
	let ground = 0;
	try {
		const settings = JSON.parse(settingsText);
		const value = typeof settings === 'object' && settings !== null ? settings.foundation?.groundLevel : undefined;
		if (typeof value === 'number') {
			ground = value;
		}
	} catch {
		return sourceStamp(settingsText);
	}
	return sourceStamp(`groundLevel=${Math.floor(ground * 1000 + 0.5)}`);
}

/**
 * The stamp the bill of quantities records for its source part `part` with text `text`: the
 * ground level's for the project settings, the whole file's otherwise.
 */
export function boqSourceStamp(part: string, text: string): string {
	return part === 'settings' ? groundLevelStamp(text) : sourceStamp(text);
}

/** The stamp a derived document recorded for upstream part `part`, if any. */
export function recordedStamp(document: unknown, part: string): string | undefined {
	if (typeof document !== 'object' || document === null) {
		return undefined;
	}
	const source = (document as { source?: unknown }).source;
	const stamp = typeof source === 'object' && source !== null ? (source as { [part: string]: unknown })[part] : undefined;
	return typeof stamp === 'string' ? stamp : undefined;
}

const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';
const LEGACY_BIM_SCHEMA_ID = 'saengine.bim/1';

/**
 * The content of a new floor plan. Projects made before the floor plan owned the layout kept
 * grids, stories and members in `bim.json` (`saengine.bim/1`); given that file's text, its
 * layout moves to the floor plan unchanged.
 */
export function newFloorPlan(legacyBimText: string | undefined): object {
	try {
		const legacy = legacyBimText ? JSON.parse(legacyBimText) : undefined;
		if (typeof legacy === 'object' && legacy !== null && legacy.schema === LEGACY_BIM_SCHEMA_ID) {
			return { ...legacy, schema: FLOOR_PLAN_SCHEMA_ID };
		}
	} catch {
		// Not JSON: start from the default layout.
	}
	return JSON.parse(JSON.stringify(DEFAULT_FLOOR_PLAN));
}
