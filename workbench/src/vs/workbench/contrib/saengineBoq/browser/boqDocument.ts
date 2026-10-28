/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { csvText } from '../../../../platform/saengine/common/csv.js';
import { boqSourceStamp, recordedStamp } from '../../../services/saengineProject/common/partSources.js';
import { architectureHasContent } from '../../../services/saengineProject/common/partStatus.js';

/*
 * The bill of quantities (`10 BOQ/boq.json`, schema `saengine.boq/1`), measured by the Python
 * models (`saengine.boq.quantities`) from the building model, the object types, the materials and
 * the substructure (its foundations, with their earthwork dug from the project settings' ground).
 * The editor never edits the bill: it is measured again on request.
 */

export const BOQ_SCHEMA_ID = 'saengine.boq/1';

/** Desktop command measuring the bill (registered where the Python backend is). */
export const BOQ_COMPUTE_COMMAND = 'saengine.boq.compute';

export type BoqGroup = 'earthwork' | 'concrete' | 'masonry' | 'finishes' | 'reinforcement' | 'formwork' | 'steel' | 'mep' | 'materials';
export type BoqUnit = 'm3' | 'm2' | 'kg' | 'nr' | 'm' | 'cft' | 'bag' | 'l';

export interface IBoqBreakdownEntry {
	readonly element: string;
	readonly story?: string;
	readonly detail?: string;
	readonly quantity: number;
}

export interface IBoqItem {
	readonly code: string;
	readonly group: BoqGroup;
	readonly description: string;
	readonly quantity: number;
	readonly unit: BoqUnit;
	readonly material?: string;
	readonly kind?: string;
	readonly diameter?: number;
	readonly byStory?: { readonly [story: string]: number };
	readonly breakdown?: readonly IBoqBreakdownEntry[];
}

export interface IBoqDocument {
	readonly schema: typeof BOQ_SCHEMA_ID;
	readonly source?: { readonly [part: string]: string | undefined };
	readonly items: readonly IBoqItem[];
	readonly notes?: readonly string[];
	/** What the bill could not measure (no bars on a type, a tank not designed, ...): while there are any the bill is incomplete. */
	readonly problems?: readonly string[];
}

/**
 * What the bill could not measure, as its warning rows show them; their count is the part's
 * problem count (an incomplete bill is not "measured").
 */
export function boqProblems(document: IBoqDocument | undefined): readonly string[] {
	return document?.problems ?? [];
}

/** Arguments of {@link BOQ_COMPUTE_COMMAND}: the texts of the source files. */
export interface IBoqComputeArgs {
	readonly bimText: string;
	readonly objectsText: string;
	readonly materialsText: string;
	/** Once it is no longer the placeholder, its foundations are measured (not the building model's footings). */
	readonly substructureText?: string;
	/** The ground level the foundations' earthwork is dug from. */
	readonly settingsText?: string;
	/** `07 MEP/mep.json`: the equipment plinths, the sleeves and openings counted, the plumbing's tanks, pipes and fixtures. */
	readonly mepText?: string;
	/** The project folder, where the plumbing tanks' last designs give their bars. */
	readonly projectRoot?: string;
	/** `05 Floor Plan/architecture.json`: its brickwork, plaster, finishes, doors and windows. */
	readonly architectureText?: string;
}

/** Result of {@link BOQ_COMPUTE_COMMAND}: the new text of `boq.json`, or why it could not be measured. */
export interface IBoqComputeResult {
	readonly text?: string;
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
}

/**
 * The parts the bill is measured from, by the part ids its `source` records them under:
 * `required` ones must exist; the substructure may be missing (a project from before Part 9);
 * an `optional` source counts only when the bill recorded it (the settings matter only for the
 * earthwork of the substructure's foundations, and of them only the ground level counts: see
 * `boqSourceStamp`).
 */
export const BOQ_SOURCES: readonly { readonly part: string; readonly label: string; readonly required?: boolean; readonly optional?: boolean }[] = [
	{ part: 'bim', label: localize('boq.source.bim', "Building Model"), required: true },
	{ part: 'objects', label: localize('boq.source.objects', "Object Types"), required: true },
	{ part: 'materials', label: localize('boq.source.materials', "Materials"), required: true },
	{ part: 'substructure', label: localize('boq.source.substructure', "Substructure") },
	{ part: 'mep', label: localize('boq.source.mep', "MEP") },
	{ part: 'settings', label: localize('boq.source.groundLevel', "Ground Level (Project Settings)"), optional: true },
	// Its walls, rooms, doors and windows (`saengine.boq.architecture`): recorded once it has a wall or a room.
	{ part: 'architecture', label: localize('boq.source.architecture', "Architecture"), optional: true },
];

/** The architecture's file beside the floor plan (`05 Floor Plan/architecture.json`), a source of the bill that is not a part of its own. */
export const BOQ_ARCHITECTURE_FILE = 'architecture.json';

/**
 * The arguments of {@link BOQ_COMPUTE_COMMAND} from the sources' texts by part id (and the
 * project folder, for the plumbing tanks' bars); without them, the labels of the required
 * sources that are missing.
 */
export function boqComputeArgs(texts: ReadonlyMap<string, string | undefined>, projectRoot?: string): { readonly args?: IBoqComputeArgs; readonly missing: readonly string[] } {
	const bimText = texts.get('bim');
	const objectsText = texts.get('objects');
	const materialsText = texts.get('materials');
	if (bimText === undefined || objectsText === undefined || materialsText === undefined) {
		return { missing: BOQ_SOURCES.filter(s => s.required && texts.get(s.part) === undefined).map(s => s.label) };
	}
	return { args: { bimText, objectsText, materialsText, substructureText: texts.get('substructure'), settingsText: texts.get('settings'), mepText: texts.get('mep'), architectureText: texts.get('architecture'), ...(projectRoot ? { projectRoot } : {}) }, missing: [] };
}

/** The groups of the bill in their order, with their titles. */
export const BOQ_GROUPS: readonly { readonly group: BoqGroup; readonly title: string }[] = [
	{ group: 'earthwork', title: localize('boq.group.earthwork', "Earthwork") },
	{ group: 'concrete', title: localize('boq.group.concrete', "Concrete") },
	{ group: 'masonry', title: localize('boq.group.masonry', "Masonry") },
	{ group: 'finishes', title: localize('boq.group.finishes', "Plaster, Finishes, Doors and Windows") },
	{ group: 'reinforcement', title: localize('boq.group.reinforcement', "Reinforcement by Bar Diameter") },
	{ group: 'formwork', title: localize('boq.group.formwork', "Formwork") },
	{ group: 'steel', title: localize('boq.group.steel', "Structural Steel") },
	{ group: 'mep', title: localize('boq.group.mep', "MEP Coordination") },
	{ group: 'materials', title: localize('boq.group.materials', "Materials: Cement, Sand, Stone Chips and Water") },
];

/**
 * The items of `group` whose quantities add up to a meaningful total: excavation and backfill are
 * the same earth measured twice, so the earthwork's total is the excavation's; the materials'
 * total is their cement in kg (sand and stone are different materials, the bags the same cement).
 */
export function totalledItems(group: BoqGroup, items: readonly IBoqItem[]): readonly IBoqItem[] {
	switch (group) {
		case 'earthwork': return items.filter(i => i.kind === 'excavation');
		case 'materials': return items.filter(i => i.kind === 'cement');
		// The plaster to walls (m²) stands for the group; tiles, doors and windows are other things.
		case 'finishes': return items.filter(i => i.kind === 'plaster');
		default: return items;
	}
}

/** The bill in `text`, or undefined when it is not a measured bill (invalid JSON, the new-project placeholder, ...). */
export function parseBoq(text: string): IBoqDocument | undefined {
	try {
		const value = JSON.parse(text);
		if (typeof value === 'object' && value !== null && value.schema === BOQ_SCHEMA_ID && Array.isArray(value.items)) {
			return value as IBoqDocument;
		}
	} catch {
		// Not JSON: not a bill.
	}
	return undefined;
}

/**
 * The source parts whose current text differs from the one the bill was measured from; a
 * required part whose text is unknown (missing file) counts as changed, and so does a missing
 * substructure the bill was measured with.
 */
export function changedSources(document: IBoqDocument | undefined, texts: ReadonlyMap<string, string | undefined>): string[] {
	return BOQ_SOURCES.filter(({ part, required, optional }) => {
		const recorded = recordedStamp(document, part);
		if (optional && recorded === undefined) {
			return false;
		}
		const text = texts.get(part);
		if (text === undefined) {
			return required || recorded !== undefined;
		}
		return recorded !== boqSourceStamp(part, text);
	}).map(s => s.part).concat(
		// The architecture also once it has a wall or a room a bill measured without it lacks.
		recordedStamp(document, 'architecture') === undefined && architectureHasContent(texts.get('architecture')) ? ['architecture'] : [],
	);
}

/**
 * Whether the bill left the bars of a plumbing tank unmeasured because the tank had no design
 * yet (the backend's note, `saengine.boq.quantities.TANK_BARS_PENDING`): once the plumbing report
 * has designed the tanks, measuring again adds them although no source file changed.
 */
export function awaitsTankDesigns(document: IBoqDocument | undefined): boolean {
	return !!document?.notes?.some(note => note.includes(TANK_BARS_PENDING));
}

/** The words of the bill's note on a plumbing tank whose bars wait for its design. */
const TANK_BARS_PENDING = 'its bars are not measured: it has no current design';

/**
 * The total rows of a group in the table: only like with like. The earthwork (excavation and
 * backfill are the same earth twice), the MEP coordination (counts and lengths of different
 * things) and the finishes (plaster, tiles, doors) have none; the materials total each material (cement in kg, bags, sand, ...) that is on
 * more than one line (cement of two types), never sand with stone.
 */
export function totalRows(group: BoqGroup, items: readonly IBoqItem[]): { readonly label?: string; readonly unit: BoqUnit; readonly total: number }[] {
	switch (group) {
		case 'earthwork':
		case 'mep':
		// Plaster, tiles and doors are different things: no total.
		case 'finishes':
			return [];
		case 'materials': {
			const byKind = new Map<string, IBoqItem[]>();
			for (const item of items) {
				const key = `${item.kind ?? item.description}|${item.unit}`;
				byKind.set(key, [...byKind.get(key) ?? [], item]);
			}
			return [...byKind.values()].filter(same => same.length > 1).map(same => ({
				label: same[0].description.replace(/\s*\(.*\)/, ''),
				unit: same[0].unit,
				total: same.reduce((sum, item) => sum + item.quantity, 0),
			}));
		}
		default:
			return totals(items);
	}
}

/** The total of each unit among `items`, in the order the units first appear. */
export function totals(items: readonly IBoqItem[]): { readonly unit: BoqUnit; readonly total: number }[] {
	const sums = new Map<BoqUnit, number>();
	for (const item of items) {
		sums.set(item.unit, (sums.get(item.unit) ?? 0) + item.quantity);
	}
	return [...sums].map(([unit, total]) => ({ unit, total }));
}

export function unitLabel(unit: string): string {
	switch (unit) {
		case 'm3': return 'm³';
		case 'm2': return 'm²';
		case 'bag': return localize('boq.unit.bags', "bags");
		case 'sft': return 'sft';
		case 'rft': return 'rft';
		default: return unit;
	}
}

/** Imperial factors of the metric units the bill measures in: cubic, square and running feet. */
const IMPERIAL: { readonly [unit: string]: { readonly unit: string; readonly factor: number } } = {
	m3: { unit: 'cft', factor: 35.3147 },
	m2: { unit: 'sft', factor: 10.7639 },
	m: { unit: 'rft', factor: 3.28084 },
};

/** `quantity` in `unit`, or in feet (cft, sft, rft) when `imperial`; other units are unchanged. */
export function displayQuantity(quantity: number, unit: string, imperial: boolean): { readonly quantity: number; readonly unit: string } {
	const to = imperial ? IMPERIAL[unit] : undefined;
	return to ? { quantity: quantity * to.factor, unit: to.unit } : { quantity, unit };
}

/** A quantity as the bill shows it: volumes to the litre, areas and masses to two decimals, counts whole. */
export function formatQuantity(quantity: number, unit: string): string {
	return quantity.toFixed(unit === 'm3' ? 3 : unit === 'nr' ? 0 : 2);
}

/** A quantity with its unit, in feet when `imperial` (see {@link displayQuantity}). */
export function quantityText(quantity: number, unit: string, imperial = false): string {
	const shown = displayQuantity(quantity, unit, imperial);
	return `${formatQuantity(shown.quantity, shown.unit)} ${unitLabel(shown.unit)}`;
}

/**
 * The bill as CSV (RFC 4180): one `item` row per item, followed by an `element` row per entry
 * of its breakdown. Item quantities and element quantities are in separate columns, so summing
 * either column (or a SUMIF by code over it) gives the bill's quantities without counting
 * anything twice.
 */
export function toCsv(document: IBoqDocument): string {
	const rows: (string | number | undefined)[][] = [['Row', 'Code', 'Group', 'Description', 'Element', 'Story', 'Detail', 'Item Quantity', 'Element Quantity', 'Unit']];
	for (const item of document.items) {
		rows.push(['item', item.code, item.group, item.description, '', '', '', item.quantity, '', item.unit]);
		for (const entry of item.breakdown ?? []) {
			rows.push(['element', item.code, item.group, item.description, entry.element, entry.story, entry.detail, '', entry.quantity, item.unit]);
		}
	}
	return csvText(rows);
}
