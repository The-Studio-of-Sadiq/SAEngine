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

/** Keys of the project settings the analysis model does not take: the project's details and the drawings' title block. */
const SETTINGS_INFO_KEYS = new Set(['project', 'drawings']);

/**
 * The stamp an analysis model records for the project settings `text` (key `settings`): of the
 * settings without the project's details and the drawings' title block, so typing the engineer's
 * name or a revision leaves the model current. The Python side
 * (`saengine.fem.derive.settings_stamp`) computes the same; a text that is not a JSON object gets
 * the stamp of its text.
 */
export function femSettingsStamp(text: string): string {
	let document: unknown;
	try {
		document = JSON.parse(text);
	} catch {
		return sourceStamp(text);
	}
	if (typeof document !== 'object' || document === null || Array.isArray(document)) {
		return sourceStamp(text);
	}
	return sourceStamp(JSON.stringify(Object.fromEntries(Object.entries(document).filter(([key]) => !SETTINGS_INFO_KEYS.has(key)))));
}

/**
 * Whether the analysis model's source `part` with `text` is still the one it recorded as
 * `recorded`. The settings count without the project's details ({@link femSettingsStamp}); a
 * model derived before that recorded the whole file's stamp, which stays current while the file
 * is unchanged.
 */
export function femSourceCurrent(part: string, text: string, recorded: string | undefined): boolean {
	return recorded === sourceStamp(text) || (part === 'settings' && recorded === femSettingsStamp(text));
}

/** What the analysis model takes from the MEP file (see {@link mepModelStamp}). */
const MEP_MODEL_KEYS = ['contentsAs', 'equipment', 'openings', 'shafts'];
/** Labels of the MEP file's items, which the analysis model does not take. */
const MEP_LABELS = new Set(['name', 'service']);

/**
 * The stamp an analysis model records for the MEP file `text` (key `mep`): of what the model
 * takes from it (its contents setting, equipment, openings and shafts, without the items' names
 * and service labels, and the plumbing's overhead tanks as `plumbingTanks`, the HVAC plant as
 * `hvacPlant`, the electrical equipment as `electricalEquipment` (with the supply's
 * `transformerType`), the fire pumps as `firePumps` (with the supply's `standby` as
 * `fireStandby`) and the overhead fire tanks as `fireTanks` when there are any),
 * so editing an IFC model's entry or a label leaves the model current. The
 * Python side (`saengine.fem.derive.mep_stamp`) computes the same; a text that is not a JSON
 * object gets the stamp of its text.
 */
export function mepModelStamp(text: string): string {
	let document: unknown;
	try {
		document = JSON.parse(text);
	} catch {
		return sourceStamp(text);
	}
	if (typeof document !== 'object' || document === null || Array.isArray(document)) {
		return sourceStamp(text);
	}
	const source = document as { readonly [key: string]: unknown };
	const content: { [key: string]: unknown } = {};
	for (const key of MEP_MODEL_KEYS) {
		if (!Object.prototype.hasOwnProperty.call(source, key)) {
			continue;
		}
		const value = source[key];
		content[key] = Array.isArray(value)
			? value.map(item => typeof item === 'object' && item !== null && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).filter(([name]) => !MEP_LABELS.has(name))) : item)
			: value;
	}
	// The plumbing's overhead tanks load the model too (stamped only when there are any).
	const plumbing = source.plumbing;
	const tanks = typeof plumbing === 'object' && plumbing !== null && !Array.isArray(plumbing) ? (plumbing as { readonly tanks?: unknown }).tanks : undefined;
	const overhead = Array.isArray(tanks) ? tanks.filter(t => typeof t === 'object' && t !== null && !Array.isArray(t) && (t as { readonly kind?: unknown }).kind === 'overhead') : [];
	if (overhead.length) {
		content.plumbingTanks = overhead;
	}
	// The HVAC plant and the electrical equipment load the model as equipment too.
	const unlabelled = (items: readonly unknown[]) => items.map(item => typeof item === 'object' && item !== null && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).filter(([name]) => !MEP_LABELS.has(name))) : item);
	const section = (value: unknown) => typeof value === 'object' && value !== null && !Array.isArray(value) ? value as { readonly [key: string]: unknown } : undefined;
	const plant = section(source.hvac)?.plant;
	if (Array.isArray(plant) && plant.length) {
		content.hvacPlant = unlabelled(plant);
	}
	const electrical = section(source.electrical);
	const equipment = electrical?.equipment;
	if (Array.isArray(equipment) && equipment.length) {
		content.electricalEquipment = unlabelled(equipment);
		const supply = section(electrical?.supply);
		if (supply && Object.prototype.hasOwnProperty.call(supply, 'transformerType')) {
			content.transformerType = supply.transformerType;
		}
	}
	// The fire pumps and the overhead fire tanks load the model too.
	const fire = section(source.fire);
	const pumps = fire?.pumps;
	if (Array.isArray(pumps) && pumps.length) {
		content.firePumps = unlabelled(pumps);
		const supply = section(fire?.supply);
		if (supply && Object.prototype.hasOwnProperty.call(supply, 'standby')) {
			content.fireStandby = supply.standby;
		}
	}
	const fireTanks = fire?.tanks;
	const fireOverhead = Array.isArray(fireTanks) ? fireTanks.filter(t => typeof t === 'object' && t !== null && !Array.isArray(t) && (t as { readonly kind?: unknown }).kind === 'overhead') : [];
	if (fireOverhead.length) {
		content.fireTanks = fireOverhead;
	}
	return sourceStamp(JSON.stringify(content));
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
