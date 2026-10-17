/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, DisposableResizeObserver, EventType, getWindow } from '../../../../base/browser/dom.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Checkbox } from '../../../../base/browser/ui/toggle/toggle.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IConfigurationPropertySchema } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { defaultButtonStyles, defaultCheckboxStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { createValidator } from '../../../services/preferences/common/preferencesValidation.js';

export type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];
export interface JsonObject { [key: string]: JsonValue }

export interface ISchemaFormContext {
	/** The schema document holding the `$defs` that `$ref`s point to. */
	readonly root: IJSONSchema;
	/** A valid starting value for a definition, used when adding or switching. */
	template(defName: string): JsonObject;
	/** Allowed ids for a reference field, by dotted path from the item (`reinforcement.material`). */
	references(path: string): readonly string[] | undefined;
	/** Extra rules for a string field: an error message, or undefined. */
	validate(path: string, value: string): string | undefined;
	/** The item changed in place. `structural` changes (added/removed groups) need a re-render. */
	changed(path: string, structural: boolean): void;
	/**
	 * Rules the schema cannot express: 'hidden' for a field that does not apply to this item,
	 * 'required' for an optional field this item must have.
	 */
	mode(path: string): 'hidden' | 'required' | undefined;
	/**
	 * The entry "Add" appends to an array (`path` without indices), e.g. the next grid line at the
	 * previous spacing; undefined uses the definition's template.
	 */
	newItem?(path: string, list: readonly JsonValue[]): JsonObject | undefined;
}

/** How {@link SchemaForm.render} lays the form out. */
export interface ISchemaFormRenderOptions {
	/**
	 * The top-level groups and lists render without their heading (their section's title says
	 * what they are), e.g. one section of the project settings.
	 */
	readonly flat?: boolean;
}

interface IResolved {
	readonly schema: IJSONSchema;
	readonly defName?: string;
}

interface IBranch {
	readonly defName: string;
	readonly schema: IJSONSchema;
	readonly value: string;
}

const UNIT = /\[([^\]]+)\]/;

/** A table column's heading: the field's title with the unit from its description, "Elevation (mm)". */
function columnHeading(title: string, description: string | undefined): string {
	const unit = description?.match(UNIT)?.[1];
	return unit && unit !== '-' ? `${title} (${unit})` : title;
}

/** Engineering names of IFC profile shapes, which the schema stores as short codes. */
const SHAPE_LABELS: { readonly [shape: string]: string } = {
	I: localize('shape.i', "I-section"),
	T: localize('shape.t', "T-section"),
	L: localize('shape.l', "Angle (L)"),
	U: localize('shape.u', "Channel (U)"),
	rectangleHollow: localize('shape.rhs', "Rectangular hollow (RHS)"),
	circleHollow: localize('shape.chs', "Circular hollow (CHS)"),
};

/** "pileCap" -> "Pile cap", "I" -> "I-section". */
export function humanize(value: string): string {
	if (SHAPE_LABELS[value]) {
		return SHAPE_LABELS[value];
	}
	const words = value.replace(/([a-z])([A-Z])/g, '$1 $2').split(' ');
	return [words[0].charAt(0).toUpperCase() + words[0].slice(1), ...words.slice(1).map(w => w.toLowerCase())].join(' ');
}

const SMALL_WORDS = new Set(['a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to', 'with']);

/** "Load combinations" -> "Load Combinations" (title-style, as the part names and buttons). */
export function titleCase(text: string): string {
	return text.split(' ').map((word, i) => i > 0 && SMALL_WORDS.has(word) ? word : word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

/**
 * Renders a form for a JSON value from its JSON Schema, with the workbench's own widgets.
 * Every edit is validated against the schema before it is applied, so the value only ever
 * holds schema-valid data; switching a union or adding an optional group inserts a template.
 */
export class SchemaForm {

	private readonly disposables = new DisposableStore();
	/** While rendering a table row, fields render as bare cells (no label, no unit). */
	private inlineCells = false;
	/** Top-level groups and lists render without their heading (see {@link ISchemaFormRenderOptions}). */
	private flat = false;

	constructor(
		private readonly ctx: ISchemaFormContext,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IHoverService private readonly hoverService: IHoverService,
	) { }

	render(container: HTMLElement, schema: IJSONSchema, value: JsonObject, skip: readonly string[] = [], options: ISchemaFormRenderOptions = {}): void {
		this.disposables.clear();
		this.flat = !!options.flat;
		this.renderObject(container, this.resolve(schema).schema, value, '', skip);
	}

	/** Whether the group or list at `path` renders without its heading. */
	private headless(path: string, optional: boolean): boolean {
		return this.flat && !optional && !path.includes('.');
	}

	dispose(): void {
		this.disposables.dispose();
	}

	// ───────────────────────────── schema helpers ─────────────────────────────

	private resolve(schema: IJSONSchema): IResolved {
		const ref = schema.$ref;
		if (ref?.startsWith('#/$defs/')) {
			const defName = ref.slice('#/$defs/'.length);
			const target = this.ctx.root.$defs?.[defName];
			if (target) {
				return { schema: target, defName };
			}
		}
		return { schema };
	}

	/** For `X | null` (an optional field), the X; otherwise undefined. */
	private optional(schema: IJSONSchema): IJSONSchema | undefined {
		const branches = schema.anyOf;
		if (branches?.length === 2 && branches.some(b => b.type === 'null')) {
			return branches.find(b => b.type !== 'null');
		}
		return undefined;
	}

	/** The alternatives of a discriminated union (`oneOf` of definitions sharing a const field). */
	private union(schema: IJSONSchema): { key: string; branches: IBranch[] } | undefined {
		if (!schema.oneOf?.length) {
			return undefined;
		}
		const resolved = schema.oneOf.map(s => this.resolve(s));
		const first = resolved[0].schema.properties ?? {};
		const key = Object.keys(first).find(k => resolved.every(r => r.schema.properties?.[k]?.const !== undefined));
		if (!key || resolved.some(r => !r.defName)) {
			return undefined;
		}
		return { key, branches: resolved.map(r => ({ defName: r.defName!, schema: r.schema, value: String(r.schema.properties![key].const) })) };
	}

	private enumValues(schema: IJSONSchema): readonly JsonValue[] | undefined {
		return schema.enum ?? this.resolve(schema).schema.enum;
	}

	// ───────────────────────────── renderers ─────────────────────────────

	private renderObject(container: HTMLElement, schema: IJSONSchema, value: JsonObject, path: string, skip: readonly string[] = []): void {
		for (const [key, property] of Object.entries(schema.properties ?? {})) {
			if (property.const !== undefined || skip.includes(key)) {
				continue; // fixed values (schema id, union discriminators) are not edited here
			}
			this.renderProperty(container, key, property, value, path ? `${path}.${key}` : key);
		}
	}

	private renderProperty(container: HTMLElement, key: string, property: IJSONSchema, owner: JsonObject, path: string): void {
		const mode = this.ctx.mode(path);
		if (mode === 'hidden') {
			return;
		}
		const inner = mode === 'required' ? undefined : this.optional(property);
		const schema = inner ?? this.optional(property) ?? property;
		const title = property.title ?? this.resolve(schema).schema.title ?? humanize(key);
		const description = property.description ?? this.resolve(schema).schema.description;

		const union = this.union(schema);
		if (union) {
			this.renderUnion(container, title, union, owner, key, path, !!inner);
			return;
		}
		const resolved = this.resolve(schema);
		if (resolved.schema.type === 'object' && resolved.defName) {
			this.renderGroup(container, title, resolved, owner, key, path, !!inner);
			return;
		}
		if (resolved.schema.type === 'array' && resolved.schema.items && !Array.isArray(resolved.schema.items)) {
			const items = this.resolve(resolved.schema.items);
			const itemUnion = this.union(resolved.schema.items);
			if (itemUnion) {
				this.renderUnionArray(container, title, resolved.schema, itemUnion, owner, key, path);
			} else if (items.schema.type === 'object' && items.defName) {
				this.renderObjectArray(container, title, resolved.schema, items, owner, key, path);
			} else {
				this.renderPrimitiveArray(container, title, description, resolved.schema, items.schema, owner, key, path);
			}
			return;
		}
		this.renderField(container, title, description, schema, owner, key, path, !!inner);
	}

	private renderGroup(container: HTMLElement, title: string, resolved: IResolved, owner: JsonObject, key: string, path: string, optional: boolean): void {
		if (this.headless(path, optional)) {
			if (owner[key] === undefined && resolved.defName) {
				owner[key] = this.ctx.template(resolved.defName);
			}
			const value = owner[key];
			if (value && typeof value === 'object' && !Array.isArray(value)) {
				this.renderObject(container, resolved.schema, value, path);
			}
			return;
		}
		const group = append(container, $('.form-group'));
		const header = append(group, $('.form-group-header'));
		if (optional) {
			const include = this.disposables.add(new Checkbox(title, owner[key] !== undefined && owner[key] !== null, defaultCheckboxStyles));
			header.appendChild(include.domNode);
			this.disposables.add(include.onChange(() => {
				if (include.checked) {
					owner[key] = this.ctx.template(resolved.defName!);
				} else {
					delete owner[key];
				}
				this.ctx.changed(path, true);
			}));
		}
		append(header, $('span.form-group-title', undefined, title));
		if (!optional && owner[key] === undefined && resolved.defName) {
			// Files written before the section existed: its defaults, saved with the next edit.
			owner[key] = this.ctx.template(resolved.defName);
		}
		const value = owner[key];
		if (value && typeof value === 'object' && !Array.isArray(value)) {
			this.renderObject(append(group, $('.form-group-body')), resolved.schema, value, path);
		}
	}

	private renderUnion(container: HTMLElement, title: string, union: { key: string; branches: IBranch[] }, owner: JsonObject, key: string, path: string, optional: boolean): void {
		const group = append(container, $('.form-group'));
		const header = append(group, $('.form-group-header'));
		append(header, $('span.form-group-title', undefined, title));

		const value = owner[key];
		const current = value && typeof value === 'object' && !Array.isArray(value) ? value : undefined;
		const options = [...(optional ? [{ text: localize('schemaForm.none', "None") }] : []), ...union.branches.map(b => ({ text: humanize(b.value) }))];
		const index = current ? union.branches.findIndex(b => b.value === current[union.key]) : -1;
		const select = this.disposables.add(new SelectBox(options, index + (optional ? 1 : 0), this.contextViewService, defaultSelectBoxStyles, { ariaLabel: title }));
		select.render(append(header, $('.form-group-select')));
		this.disposables.add(select.onDidSelect(e => {
			const branch = union.branches[e.index - (optional ? 1 : 0)];
			if (branch) {
				owner[key] = this.ctx.template(branch.defName);
			} else {
				delete owner[key];
			}
			this.ctx.changed(path, true);
		}));

		const branch = index >= 0 ? union.branches[index] : undefined;
		if (current && branch) {
			this.renderObject(append(group, $('.form-group-body')), branch.schema, current, path);
		}
	}

	/** A list whose entries are each one of several kinds (e.g. rectangular or cylindrical grids). */
	private renderUnionArray(container: HTMLElement, title: string, schema: IJSONSchema, union: { key: string; branches: IBranch[] }, owner: JsonObject, key: string, path: string): void {
		const group = append(container, $('.form-group'));
		if (!this.headless(path, false)) {
			const header = append(group, $('.form-group-header'));
			append(header, $('span.form-group-title', undefined, title));
		}
		const list = Array.isArray(owner[key]) ? owner[key] as JsonValue[] : [];
		// The entries are edited in place: the list stands in for an object keyed by index.
		const entries = list as unknown as JsonObject;
		list.forEach((entry, i) => {
			const row = append(group, $('.form-array-row'));
			const fields = append(row, $('.form-array-fields'));
			const name = entry && typeof entry === 'object' && !Array.isArray(entry) && typeof entry.id === 'string' ? entry.id : String(i + 1);
			this.renderUnion(fields, name, union, entries, String(i), `${path}.${i}`, false);
			this.iconButton(row, Codicon.trash, localize('schemaForm.remove', "Remove"), () => {
				list.splice(i, 1);
				owner[key] = list;
				this.ctx.changed(path, true);
			}, list.length > (schema.minItems ?? 0));
		});
		if (schema.maxItems === undefined || list.length < schema.maxItems) {
			const add = this.disposables.add(new Button(append(group, $('.form-array-add')), { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			add.label = `$(${Codicon.add.id}) ${localize('schemaForm.add', "Add {0}", titleCase(title))}`;
			this.disposables.add(add.onDidClick(() => {
				const entry = this.ctx.newItem?.(path.replace(/\.\d+(?=\.|$)/g, ''), list) ?? this.ctx.template(union.branches[0].defName);
				owner[key] = [...list, entry];
				this.ctx.changed(path, true);
			}));
		}
	}

	private renderObjectArray(container: HTMLElement, title: string, schema: IJSONSchema, items: IResolved, owner: JsonObject, key: string, path: string): void {
		const group = append(container, $('.form-group'));
		if (!this.headless(path, false)) {
			const header = append(group, $('.form-group-header'));
			append(header, $('span.form-group-title', undefined, title));
		}

		const list = Array.isArray(owner[key]) ? owner[key] as JsonValue[] : [];
		const min = schema.minItems ?? 0;
		const remove = (parent: HTMLElement, i: number) => {
			this.iconButton(parent, Codicon.trash, localize('schemaForm.remove', "Remove"), () => {
				list.splice(i, 1);
				owner[key] = list;
				this.ctx.changed(path, true);
			}, list.length > min);
		};

		const columns = this.flatColumns(items.schema);
		if (columns) {
			// Rows of simple values (grid lines, stories, bar groups) read best as a table.
			const table = append(group, $('.form-table'));
			table.style.gridTemplateColumns = `${columns.map(c => c.width).join(' ')} auto`;
			for (const column of columns) {
				const text = columnHeading(column.title, column.description);
				const cell = append(table, $('.form-table-header', undefined, text));
				// The whole heading (and its description) on hover: narrow columns cut it short.
				const help = column.description?.replace(UNIT, '').replace(/\s+\./, '.').trim();
				this.disposables.add(this.hoverService.setupDelayedHover(cell, { content: help && help !== '.' ? `${text}: ${help}` : text }));
			}
			append(table, $('.form-table-header'));
			list.forEach((entry, i) => {
				if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
					return;
				}
				this.inlineCells = true;
				try {
					this.renderObject(table, items.schema, entry, `${path}.${i}`);
				} finally {
					this.inlineCells = false;
				}
				remove(append(table, $('.form-table-actions')), i);
			});
			this.stackWhenNarrow(group, table);
		} else {
			list.forEach((entry, i) => {
				if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
					return;
				}
				const row = append(group, $('.form-array-row'));
				this.renderObject(append(row, $('.form-array-fields')), items.schema, entry, `${path}.${i}`);
				remove(row, i);
			});
		}

		if (schema.maxItems === undefined || list.length < schema.maxItems) {
			const add = this.disposables.add(new Button(append(group, $('.form-array-add')), { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			add.label = `$(${Codicon.add.id}) ${localize('schemaForm.add', "Add {0}", titleCase(humanize(items.defName!)))}`;
			this.disposables.add(add.onDidClick(() => {
				const entry = this.ctx.newItem?.(path.replace(/\.\d+(?=\.|$)/g, ''), list) ?? this.ctx.template(items.defName!);
				owner[key] = [...list, entry];
				this.ctx.changed(path, true);
			}));
		}
	}

	/**
	 * A table whose columns do not fit their group (a narrow editor, or the properties panel taking
	 * the width) shows each row as label/field pairs instead of scrolling sideways; it goes back to
	 * columns once the group is as wide as the columns need again.
	 */
	private stackWhenNarrow(group: HTMLElement, table: HTMLElement): void {
		const targetWindow = getWindow(group);
		let needed = 0;
		let frame: number | undefined;
		const update = () => {
			frame = undefined;
			const available = group.clientWidth;
			if (!table.isConnected || available === 0) {
				return; // hidden: measured again once it is shown
			}
			if (!table.classList.contains('stacked')) {
				if (table.scrollWidth > available + 1) {
					needed = table.scrollWidth;
					table.classList.add('stacked');
				}
			} else if (available >= needed) {
				table.classList.remove('stacked');
			}
		};
		const observer = this.disposables.add(new DisposableResizeObserver('SchemaForm.stackWhenNarrow', () => {
			// After layout, so changing the table's shape does not resize what is being observed mid-pass.
			frame ??= targetWindow.requestAnimationFrame(update);
		}, targetWindow));
		this.disposables.add(observer.observe(group));
		this.disposables.add(toDisposable(() => frame !== undefined && targetWindow.cancelAnimationFrame(frame)));
	}

	/** Titles of an object's fields when every field is a simple value; otherwise undefined. */
	private flatColumns(schema: IJSONSchema): { title: string; description?: string; width: string }[] | undefined {
		const columns: { title: string; description?: string; width: string }[] = [];
		for (const [key, property] of Object.entries(schema.properties ?? {})) {
			if (property.const !== undefined) {
				continue;
			}
			const inner = this.optional(property) ?? property;
			const resolved = this.resolve(inner).schema;
			const simple = ['string', 'number', 'integer', 'boolean'].includes(String(resolved.type)) || !!resolved.enum;
			if (!simple || inner.oneOf) {
				return undefined;
			}
			// Numbers in fixed narrow columns; names and choices take the room that is left, so long
			// combination names ("1.2D + 1.6L + 0.5Lr") stay readable.
			const numeric = resolved.type === 'number' || resolved.type === 'integer';
			const width = resolved.type === 'boolean' ? 'max-content' : numeric && !resolved.enum ? '64px' : 'minmax(88px, 220px)';
			columns.push({ title: property.title ?? resolved.title ?? humanize(key), description: property.description ?? resolved.description, width });
		}
		return columns.length ? columns : undefined;
	}

	private renderPrimitiveArray(container: HTMLElement, title: string, description: string | undefined, schema: IJSONSchema, item: IJSONSchema, owner: JsonObject, key: string, path: string): void {
		const row = this.fieldRow(container, title, description);
		const list = Array.isArray(owner[key]) ? owner[key] as JsonValue[] : [];
		const parts = append(row.control, $('.form-inline-array'));
		list.forEach((entry, i) => {
			if (i > 0) {
				append(parts, $('span.form-inline-separator', undefined, ':'));
			}
			this.input(append(parts, $('.form-inline-input')), item, String(entry ?? ''), false, `${path}.${i}`, title, parsed => {
				list[i] = parsed!;
				owner[key] = list;
			});
		});
		const min = schema.minItems ?? 0;
		const max = schema.maxItems ?? Number.MAX_SAFE_INTEGER;
		if (list.length > min) {
			this.iconButton(parts, Codicon.remove, localize('schemaForm.removePart', "Remove part"), () => {
				list.pop();
				owner[key] = list;
				this.ctx.changed(path, true);
			});
		}
		if (list.length < max) {
			this.iconButton(parts, Codicon.add, localize('schemaForm.addPart', "Add part"), () => {
				owner[key] = [...list, 1];
				this.ctx.changed(path, true);
			});
		}
	}

	private renderField(container: HTMLElement, title: string, description: string | undefined, schema: IJSONSchema, owner: JsonObject, key: string, path: string, optional: boolean): void {
		const row = this.fieldRow(container, title, description);
		const value = owner[key];

		const references = this.ctx.references(path.replace(/\.\d+(?=\.|$)/g, ''));
		const enumValues = references ?? this.enumValues(schema);
		// Readable names for enum values ("RC special moment frame" for "rcSmf"), when the schema has them.
		const labels = references ? undefined : schema.enumDescriptions ?? this.resolve(schema).schema.enumDescriptions;
		const label = (v: JsonValue) => {
			const index = this.enumValues(schema)?.indexOf(v) ?? -1;
			if (labels && index >= 0 && labels[index]) {
				return labels[index];
			}
			// Plain words of the schema ("perimeter", "pileCap") read as words; ids stay as they are.
			return !references && typeof v === 'string' && /^[a-z][a-zA-Z]*$/.test(v) ? humanize(v) : String(v);
		};
		if (enumValues) {
			const values = [...(optional ? [null] : []), ...enumValues];
			if (value !== undefined && value !== null && !values.includes(value)) {
				values.push(value); // keep showing a value that is no longer allowed, e.g. a deleted material
			}
			const options = values.map(v => ({
				text: v === null ? localize('schemaForm.notSet', "(not set)") : label(v),
				description: references && v !== null && !references.includes(v as string) ? localize('schemaForm.missing', "Not defined") : undefined,
			}));
			const select = this.disposables.add(new SelectBox(options, Math.max(0, values.indexOf(value ?? null)), this.contextViewService, defaultSelectBoxStyles, { ariaLabel: title }));
			select.render(row.control);
			this.disposables.add(select.onDidSelect(e => {
				const selected = values[e.index];
				if (selected === null) {
					delete owner[key];
				} else {
					owner[key] = selected;
				}
				this.ctx.changed(path, false);
			}));
			return;
		}

		if (schema.type === 'boolean') {
			const checkbox = this.disposables.add(new Checkbox(title, value === true || (value === undefined && schema.default === true), defaultCheckboxStyles));
			row.control.appendChild(checkbox.domNode);
			this.disposables.add(checkbox.onChange(() => {
				owner[key] = checkbox.checked;
				this.ctx.changed(path, false);
			}));
			return;
		}

		const unit = description?.match(UNIT)?.[1];
		const suffix = unit && unit !== '-' && !this.inlineCells ? unit : undefined;
		const wrap = suffix ? append(row.control, $('.form-input-unit')) : row.control;
		this.input(wrap, schema, value === undefined || value === null ? '' : String(value), optional, path, title, parsed => {
			if (parsed === undefined) {
				delete owner[key];
			} else {
				owner[key] = parsed;
			}
		});
		if (suffix) {
			// A muted suffix inside the field, so fields with and without units line up.
			append(wrap, $('span.form-unit', { 'aria-hidden': 'true' }, suffix));
		}
	}

	// ───────────────────────────── widgets ─────────────────────────────

	private fieldRow(container: HTMLElement, title: string, description: string | undefined): { control: HTMLElement } {
		if (this.inlineCells) {
			const cell = append(container, $('.form-control.form-cell'));
			// The column heading, shown only when a narrow table stacks its rows (see renderObjectArray).
			append(cell, $('span.form-cell-label', { 'aria-hidden': 'true' }, columnHeading(title, description)));
			return { control: cell };
		}
		const row = append(container, $('.form-field'));
		const head = append(row, $('.form-label-cell'));
		const label = append(head, $('label.form-label', undefined, title));
		const help = description?.replace(UNIT, '').replace(/\s+\./, '.').trim();
		if (help && help !== '.') {
			// The description behind a quiet "?" beside the label (and on the label itself).
			const icon = append(head, $(`span.form-help${ThemeIcon.asCSSSelector(Codicon.question)}`, { 'aria-hidden': 'true' }));
			this.disposables.add(this.hoverService.setupDelayedHover(label, { content: help }));
			this.disposables.add(this.hoverService.setupDelayedHover(icon, { content: help }));
		}
		return { control: append(row, $('.form-control')) };
	}

	/**
	 * A text input that applies a value only when it is valid for `schema`; invalid input shows
	 * the validation message and leaves the stored value unchanged.
	 */
	private input(container: HTMLElement, schema: IJSONSchema, initial: string, optional: boolean, path: string, title: string, apply: (value: JsonValue | undefined) => void): void {
		const numeric = schema.type === 'number' || schema.type === 'integer';
		// Empty optional fields are handled below, so the leaf is validated as non-nullable.
		const leaf: IConfigurationPropertySchema = { ...schema };
		const validator = createValidator(leaf);
		const check = (text: string): string | undefined => {
			const trimmed = text.trim();
			if (optional && trimmed === '') {
				return undefined;
			}
			if (numeric && trimmed !== '' && !isFinite(Number(trimmed))) {
				return localize('schemaForm.number', "Enter a number.");
			}
			if (schema.type === 'integer' && trimmed !== '' && !Number.isInteger(Number(trimmed))) {
				return localize('schemaForm.integer', "Enter a whole number.");
			}
			return validator(numeric && trimmed !== '' ? Number(trimmed) : trimmed) || (!numeric ? this.ctx.validate(path, trimmed) : undefined) || undefined;
		};
		const box = this.disposables.add(new InputBox(container, this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			ariaLabel: title,
			validationOptions: { validation: text => { const error = check(text); return error ? { content: error, type: MessageType.ERROR } : null; } },
		}));
		box.value = initial;
		if (schema.default !== undefined && schema.default !== null && typeof schema.default !== 'object') {
			// An empty field means the schema's default (an underlay's offset 0, scale 1): show it
			// greyed in the field. Set on the element, not as the InputBox placeholder, which would
			// also show it as the hover of a field that has a value.
			box.inputElement.placeholder = String(schema.default);
		}
		this.disposables.add(box.onDidChange(text => {
			if (check(text) !== undefined) {
				return;
			}
			const trimmed = text.trim();
			apply(optional && trimmed === '' ? undefined : numeric ? Number(trimmed) : trimmed);
			this.ctx.changed(path, false);
		}));
	}

	/** A small borderless icon button (remove a row, add a part), with a hover. */
	private iconButton(container: HTMLElement, icon: ThemeIcon, title: string, run: () => void, enabled = true): void {
		const button = append(container, $<HTMLButtonElement>('button.form-icon-button', { type: 'button', 'aria-label': title }));
		append(button, $(ThemeIcon.asCSSSelector(icon)));
		button.disabled = !enabled;
		this.disposables.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, title));
		this.disposables.add(addDisposableListener(button, EventType.CLICK, () => run()));
	}
}
