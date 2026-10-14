/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Checkbox } from '../../../../base/browser/ui/toggle/toggle.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
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

/**
 * Renders a form for a JSON value from its JSON Schema, with the workbench's own widgets.
 * Every edit is validated against the schema before it is applied, so the value only ever
 * holds schema-valid data; switching a union or adding an optional group inserts a template.
 */
export class SchemaForm {

	private readonly disposables = new DisposableStore();

	constructor(
		private readonly ctx: ISchemaFormContext,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IHoverService private readonly hoverService: IHoverService,
	) { }

	render(container: HTMLElement, schema: IJSONSchema, value: JsonObject, skip: readonly string[] = []): void {
		this.disposables.clear();
		this.renderObject(container, this.resolve(schema).schema, value, '', skip);
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
			if (items.schema.type === 'object' && items.defName) {
				this.renderObjectArray(container, title, resolved.schema, items, owner, key, path);
			} else {
				this.renderPrimitiveArray(container, title, description, resolved.schema, items.schema, owner, key, path);
			}
			return;
		}
		this.renderField(container, title, description, schema, owner, key, path, !!inner);
	}

	private renderGroup(container: HTMLElement, title: string, resolved: IResolved, owner: JsonObject, key: string, path: string, optional: boolean): void {
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

	private renderObjectArray(container: HTMLElement, title: string, schema: IJSONSchema, items: IResolved, owner: JsonObject, key: string, path: string): void {
		const group = append(container, $('.form-group'));
		const header = append(group, $('.form-group-header'));
		append(header, $('span.form-group-title', undefined, title));

		const list = Array.isArray(owner[key]) ? owner[key] as JsonValue[] : [];
		const min = schema.minItems ?? 0;
		list.forEach((entry, i) => {
			if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
				return;
			}
			const row = append(group, $('.form-array-row'));
			this.renderObject(append(row, $('.form-array-fields')), items.schema, entry, `${path}.${i}`);
			const remove = this.disposables.add(new Button(row, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('schemaForm.remove', "Remove") }));
			remove.label = `$(${Codicon.trash.id})`;
			remove.enabled = list.length > min;
			this.disposables.add(remove.onDidClick(() => {
				list.splice(i, 1);
				owner[key] = list;
				this.ctx.changed(path, true);
			}));
		});

		if (schema.maxItems === undefined || list.length < schema.maxItems) {
			const add = this.disposables.add(new Button(append(group, $('.form-array-add')), { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			add.label = `$(${Codicon.add.id}) ${localize('schemaForm.add', "Add {0}", humanize(items.defName!))}`;
			this.disposables.add(add.onDidClick(() => {
				owner[key] = [...list, this.ctx.template(items.defName!)];
				this.ctx.changed(path, true);
			}));
		}
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
		if (enumValues) {
			const values = [...(optional ? [null] : []), ...enumValues];
			if (value !== undefined && value !== null && !values.includes(value)) {
				values.push(value); // keep showing a value that is no longer allowed, e.g. a deleted material
			}
			const options = values.map(v => ({
				text: v === null ? localize('schemaForm.notSet', "(not set)") : String(v),
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
			const checkbox = this.disposables.add(new Checkbox(title, value === true, defaultCheckboxStyles));
			row.control.appendChild(checkbox.domNode);
			this.disposables.add(checkbox.onChange(() => {
				owner[key] = checkbox.checked;
				this.ctx.changed(path, false);
			}));
			return;
		}

		this.input(row.control, schema, value === undefined || value === null ? '' : String(value), optional, path, title, parsed => {
			if (parsed === undefined) {
				delete owner[key];
			} else {
				owner[key] = parsed;
			}
		});
		const unit = description?.match(UNIT)?.[1];
		if (unit && unit !== '-') {
			append(row.control, $('span.form-unit', undefined, unit));
		}
	}

	// ───────────────────────────── widgets ─────────────────────────────

	private fieldRow(container: HTMLElement, title: string, description: string | undefined): { control: HTMLElement } {
		const row = append(container, $('.form-field'));
		const label = append(row, $('label.form-label', undefined, title));
		const help = description?.replace(UNIT, '').replace(/\s+\./, '.').trim();
		if (help && help !== '.') {
			this.disposables.add(this.hoverService.setupDelayedHover(label, { content: help }));
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
		this.disposables.add(box.onDidChange(text => {
			if (check(text) !== undefined) {
				return;
			}
			const trimmed = text.trim();
			apply(optional && trimmed === '' ? undefined : numeric ? Number(trimmed) : trimmed);
			this.ctx.changed(path, false);
		}));
	}

	private iconButton(container: HTMLElement, icon: typeof Codicon.add, title: string, run: () => void): void {
		const button = this.disposables.add(new Button(container, { ...defaultButtonStyles, secondary: true, supportIcons: true, title }));
		button.label = `$(${icon.id})`;
		this.disposables.add(button.onDidClick(run));
	}
}
