/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { IFieldSpec } from '../../saengineSoil/browser/soilDocument.js';
import { IMep, IMepContext, Point } from './mepDocument.js';
import type { MepSelection } from './mepPlan.js';
import { ITableColumn } from './mepResults.js';

/*
 * What the discipline views of the MEP editor (hvacView.ts, electricalView.ts) need from the
 * editor to build their Data tables and properties: its inputs (a valid value is stored and
 * saved after a pause, an invalid one is marked; problems mark them by their dotted path), its
 * sections, rows and property rows, and the edit callbacks. The editor implements it; the views
 * hold no state of their own.
 */

export interface IMepFormHost {
	readonly document: IMep;
	readonly context: IMepContext;
	/** The story shown in the plan. */
	readonly story: string | undefined;
	section(title: string, count: number | undefined, add?: { label: string; run: () => void }): HTMLElement;
	tableHead(table: HTMLElement, columns: readonly ITableColumn[]): void;
	selectableRow(body: HTMLElement, selection: MepSelection): HTMLElement;
	removeButton(row: HTMLElement, run: () => void): void;
	textInput(field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key: string, placeholder?: string): HTMLInputElement;
	/** `allowNone`: an empty first option, labelled with the string when one is given (the default the backend applies). */
	selectInput(options: readonly { value: string; label: string }[], current: string, store: (value: string) => void, key: string, label: string, allowNone?: boolean | string): HTMLSelectElement;
	checkbox(checked: boolean, store: (value: boolean) => void, label: string): HTMLInputElement;
	yesNo(current: boolean, store: (value: boolean) => void, key: string, label: string): HTMLSelectElement;
	fieldRow(panel: HTMLElement, field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key: string, placeholder?: string): void;
	propertyRow(panel: HTMLElement, label: string, control: HTMLElement, unit?: string, title?: string): void;
	/** Stores `value` into `target[key]` (deletes it when empty) and saves after a pause. */
	setField(target: { [key: string]: unknown }, key: string, value: number | string | undefined): void;
	/** Stores a choice (deletes it when empty) and saves at once. */
	setOptional(target: { [key: string]: unknown }, key: string, value: string): void;
	/** After an edit in place: structural edits save and re-render at once, typing is batched. */
	changed(structural: boolean): void;
	/** Shows `story` in the plan (an item moved to it stays in view). */
	followStory(story: string): void;
	storyOptions(): { value: string; label: string }[];
	storyName(id: string | undefined): string;
	/** A storey's use from 07 MEP's Storey use, as a link that opens that table (the one place it is edited). */
	storyUseLink(cell: HTMLElement, use: string): void;
	/** The plan's path editor: a polyline as "x y; x y" in m. */
	pathInput(path: readonly Point[], store: (path: Point[]) => void, key: string, label: string, minPoints: number): HTMLInputElement;
}

/** A grid of labelled settings (the plumbing's supply grid): `setting(label, control, unit?, title?)` adds one. */
export function settingsGrid(section: HTMLElement): (label: string, control: HTMLElement, unit?: string, title?: string) => void {
	const grid = append(section, $('.plb-settings'));
	return (label, control, unit, title) => {
		const element = append(grid, $('label.plb-setting', title ? { title } : undefined));
		append(element, $('span.plb-setting-label', undefined, label));
		const wrapper = append(element, $('span.plb-setting-control'));
		append(wrapper, control);
		if (unit) {
			append(wrapper, $('span.mep-unit', undefined, unit));
		}
	};
}

/** The rows of a per-story table: the building's stories from the top down, then any the file names that the building lacks. */
export function storyRowIds(context: IMepContext, listed: readonly { story: string }[]): string[] {
	const known = new Set(context.stories.map(s => s.id));
	return [...context.stories.map(s => s.id).reverse(), ...listed.map(r => r.story).filter(id => !known.has(id))];
}

export const UNIT_MM = localize('mepForm.unit.mm', "mm");
export const UNIT_M = localize('mepForm.unit.m', "m");
export const UNIT_KN = localize('mepForm.unit.kn', "kN");

/** The fields every item of the services shares: its ID and plan position (m shown, mm stored). */
export const ITEM_FIELDS = {
	id: { key: 'id', label: localize('mepForm.f.id', "ID"), kind: 'text', required: true, width: 64 },
	x: { key: 'x', label: 'X', unit: UNIT_M, kind: 'length', required: true, title: localize('mepForm.f.xTitle', "Plan position of the centre"), width: 72 },
	y: { key: 'y', label: 'Y', unit: UNIT_M, kind: 'length', required: true, title: localize('mepForm.f.yTitle', "Plan position of the centre"), width: 72 },
	length: { key: 'length', label: localize('mepForm.f.length', "Length"), unit: UNIT_MM, kind: 'number', min: 1, title: localize('mepForm.f.lengthTitle', "Footprint along x"), width: 72 },
	width: { key: 'width', label: localize('mepForm.f.width', "Width"), unit: UNIT_MM, kind: 'number', min: 1, title: localize('mepForm.f.widthTitle', "Footprint along y"), width: 72 },
	height: { key: 'height', label: localize('mepForm.f.height', "Height"), unit: UNIT_MM, kind: 'number', min: 1, width: 72 },
	operatingWeight: { key: 'operatingWeight', label: localize('mepForm.f.operating', "Operating weight"), unit: UNIT_KN, kind: 'number', min: 0.001, title: localize('mepForm.f.operatingTitle', "Weight in operation with its contents, from the supplier: a load on the floor"), width: 84 },
	bottom: { key: 'bottom', label: localize('mepForm.f.bottom', "Underside"), unit: UNIT_MM, kind: 'number', min: 0, title: localize('mepForm.f.bottomTitle', "Underside above the story's floor; empty: just below the slab soffit"), width: 80 },
} satisfies { [key: string]: IFieldSpec };
