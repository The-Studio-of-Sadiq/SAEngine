/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/propertySheet.css';
import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IPropertySheet, PropertyAction } from './modelData.js';
import { OPEN_OWNER_LABELS } from './projectDocuments.js';

/*
 * A property sheet (see `propertySheet`) in the properties panel of the SAEngine editor frame:
 * a title, then per section a heading and name/value rows (the frame's `sa-props-*` styles).
 */

/** A heading of the properties panel. */
export function propertyHeading(container: HTMLElement, text: string, detail?: string): HTMLElement {
	const heading = append(container, $('.sa-props-heading'));
	append(heading, $('span', undefined, text));
	if (detail) {
		append(heading, $('span.sa-props-detail', undefined, detail));
	}
	return heading;
}

/** A name/value row; `problem` marks the value with a warning. */
export function propertyRow(container: HTMLElement, name: string, value: string | HTMLElement, problem?: boolean): HTMLElement {
	const row = append(container, $('.sa-props-row'));
	append(row, $('span.name', undefined, name));
	const cell = append(row, $('span.value'));
	if (problem) {
		cell.classList.add('problem');
		append(cell, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
	}
	if (typeof value === 'string') {
		append(cell, $('span', undefined, value));
	} else {
		append(cell, value);
	}
	return row;
}

/** A muted note under the rows. */
export function propertyNote(container: HTMLElement, text: string): HTMLElement {
	return append(container, $('.sa-props-note', undefined, text));
}

/** A link in the panel ("Edit in Object Types"); its listeners go to `store`. */
export function propertyLink(container: HTMLElement, label: string, run: () => void, store: DisposableStore): HTMLElement {
	const link = append(container, $<HTMLAnchorElement>('a.sa-props-link', { role: 'button', tabIndex: 0 }, label));
	store.add(addDisposableListener(link, EventType.CLICK, () => run()));
	store.add(addDisposableListener(link, EventType.KEY_DOWN, e => {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			run();
		}
	}));
	return link;
}

/**
 * Renders `sheet` into `container`. `skip` leaves out actions the editor offers itself (the
 * floor plan does not link to itself); `onAction` runs the others.
 */
export function renderPropertySheet(container: HTMLElement, sheet: IPropertySheet, store: DisposableStore, onAction: (action: PropertyAction) => void, skip: readonly PropertyAction[] = []): void {
	propertyHeading(container, sheet.title, sheet.subtitle);
	for (const section of sheet.sections) {
		append(container, $('.sa-props-section', undefined, section.title));
		for (const row of section.rows) {
			propertyRow(container, row.label, row.value, row.problem);
		}
	}
	const actions = sheet.actions.filter(action => !skip.includes(action));
	if (actions.length) {
		const links = append(container, $('.sa-props-links'));
		for (const action of actions) {
			propertyLink(links, OPEN_OWNER_LABELS[action], () => onAction(action), store);
		}
	}
}

// ───────────────────────────── values with units ─────────────────────────────

/** `[mm]` or `[°]` in a schema description (not a list of names such as `[x, y]`). */
const BRACKET_UNIT = /\[(?<unit>[^\],\s]+)\]/;
/** `[x, y] in mm.`: the unit after "in" at the end of a description. */
const TRAILING_UNIT = /\bin (?<unit>[^\s.]+)\.?$/;

function unitOfDescription(description: string | undefined): string | undefined {
	const unit = description?.match(BRACKET_UNIT)?.groups?.unit ?? description?.match(TRAILING_UNIT)?.groups?.unit;
	return unit && unit !== '-' ? unit : undefined;
}

function resolveSchema(root: IJSONSchema, schema: IJSONSchema | undefined): IJSONSchema | undefined {
	const ref = schema?.$ref?.match(/^#\/(?:\$defs|definitions)\/(?<name>.+)$/)?.groups?.name;
	return ref ? (root.$defs ?? root.definitions)?.[ref] : schema;
}

/**
 * The unit of property `key` of definition `definition` in `root` (`mm`, `°`), read from the
 * schema descriptions as the forms show it: the property's own, then its definition's (a point
 * is "[mm]"), then its items' for a list.
 */
export function schemaUnit(root: IJSONSchema, definition: string, key: string): string | undefined {
	const owner = (root.$defs ?? root.definitions)?.[definition];
	const property = owner?.properties?.[key];
	if (!property) {
		return undefined;
	}
	const items = Array.isArray(property.items) ? property.items[0] : property.items;
	const candidates = [property, resolveSchema(root, property), items, resolveSchema(root, items)];
	for (const candidate of candidates) {
		const unit = unitOfDescription(candidate?.description);
		if (unit) {
			return unit;
		}
	}
	return undefined;
}

function formatNumber(value: number, unit: string | undefined): string {
	// Lengths in whole millimetres, like the floor plan; anything else to two decimals.
	return String(unit === 'mm' ? Math.round(value) : Math.round(value * 100) / 100);
}

function withUnit(text: string, unit: string | undefined): string {
	if (!unit) {
		return text;
	}
	return unit === '°'
		? localize('property.valueDegrees', "{0}°", text)
		: localize('property.valueUnit', "{0} {1}", text, unit);
}

type SheetValue = string | number | boolean | null | undefined | object;

/** The numbers of a point (`[x, y]` or `{ x, y, z }`), or undefined when `value` is no point. */
function pointNumbers(value: SheetValue): number[] | undefined {
	const numbers = Array.isArray(value) ? value : value && typeof value === 'object' ? Object.values(value) : undefined;
	return numbers && numbers.length && numbers.every(n => typeof n === 'number') ? numbers as number[] : undefined;
}

/**
 * A value of a model element as one line for the properties panel, with its unit: "3200 mm",
 * "15°", "20704, 0, 14611 mm" for a point, "(0, 0), (6000, 0) mm" for an outline.
 */
export function formatPropertyValue(value: SheetValue, unit: string | undefined): string {
	if (typeof value === 'number') {
		return withUnit(formatNumber(value, unit), unit);
	}
	if (value === null || value === undefined) {
		return '';
	}
	if (typeof value !== 'object') {
		return String(value);
	}
	const point = pointNumbers(value);
	if (point) {
		return withUnit(point.map(n => formatNumber(n, unit)).join(', '), unit);
	}
	if (Array.isArray(value)) {
		const points = value.map(pointNumbers);
		if (points.length && points.every(p => !!p)) {
			return withUnit(points.map(p => `(${p!.map(n => formatNumber(n, unit)).join(', ')})`).join(', '), unit);
		}
		return value.map(v => formatPropertyValue(v, unit)).join(' | ');
	}
	return Object.entries(value).map(([k, v]) => `${k} ${formatPropertyValue(v, unit)}`).join(', ');
}
