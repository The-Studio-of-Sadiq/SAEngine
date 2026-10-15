/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { recordedStamp, sourceStamp } from '../../../services/saengineProject/common/partSources.js';

/*
 * The bill of quantities (`10 BOQ/boq.json`, schema `saengine.boq/1`), measured by the Python
 * models (`saengine.boq.quantities`) from the building model, the object types and the materials.
 * The editor never edits the bill: it is measured again on request.
 */

export const BOQ_SCHEMA_ID = 'saengine.boq/1';

/** Desktop command measuring the bill (registered where the Python backend is). */
export const BOQ_COMPUTE_COMMAND = 'saengine.boq.compute';

export type BoqGroup = 'concrete' | 'masonry' | 'reinforcement' | 'formwork' | 'steel';
export type BoqUnit = 'm3' | 'm2' | 'kg';

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
}

/** Arguments of {@link BOQ_COMPUTE_COMMAND}: the texts of the three source files. */
export interface IBoqComputeArgs {
	readonly bimText: string;
	readonly objectsText: string;
	readonly materialsText: string;
}

/** Result of {@link BOQ_COMPUTE_COMMAND}: the new text of `boq.json`, or why it could not be measured. */
export interface IBoqComputeResult {
	readonly text?: string;
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
}

/** The parts the bill is measured from, by the part ids its `source` records them under. */
export const BOQ_SOURCES: readonly { readonly part: string; readonly label: string }[] = [
	{ part: 'bim', label: localize('boq.source.bim', "Building Model") },
	{ part: 'objects', label: localize('boq.source.objects', "Object Types") },
	{ part: 'materials', label: localize('boq.source.materials', "Materials") },
];

/** The groups of the bill in their order, with their titles. */
export const BOQ_GROUPS: readonly { readonly group: BoqGroup; readonly title: string }[] = [
	{ group: 'concrete', title: localize('boq.group.concrete', "Concrete") },
	{ group: 'masonry', title: localize('boq.group.masonry', "Masonry") },
	{ group: 'reinforcement', title: localize('boq.group.reinforcement', "Reinforcement by Bar Diameter") },
	{ group: 'formwork', title: localize('boq.group.formwork', "Formwork") },
	{ group: 'steel', title: localize('boq.group.steel', "Structural Steel") },
];

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
 * The source parts whose current text differs from the one the bill was measured from;
 * a part whose text is unknown (missing file) counts as changed.
 */
export function changedSources(document: IBoqDocument | undefined, texts: ReadonlyMap<string, string | undefined>): string[] {
	return BOQ_SOURCES.filter(({ part }) => {
		const text = texts.get(part);
		return text === undefined || recordedStamp(document, part) !== sourceStamp(text);
	}).map(s => s.part);
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
		default: return unit;
	}
}

/** A quantity as the bill shows it: volumes to the litre, areas and masses to two decimals. */
export function formatQuantity(quantity: number, unit: string): string {
	return quantity.toFixed(unit === 'm3' ? 3 : 2);
}

function csvField(value: string | number | undefined): string {
	const text = value === undefined ? '' : String(value);
	return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
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
	return rows.map(row => row.map(csvField).join(',')).join('\r\n') + '\r\n';
}
