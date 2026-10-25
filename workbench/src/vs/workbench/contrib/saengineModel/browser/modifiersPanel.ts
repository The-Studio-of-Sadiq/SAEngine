/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modifiersPanel.css';
import { $, addDisposableListener, append, EventType, getActiveElement, isHTMLElement } from '../../../../base/browser/dom.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { ModifierPart, setUnappliedField } from './modifierProblems.js';
import { checkField, commitField, FieldGroup, Framing, FRAMINGS, framingLabel, IFieldRow, IModifiersView } from './modifiersModel.js';

/*
 * The "Stiffness modifiers" and "Design overwrites" groups (see modifiersModel.ts), rendered into
 * the floor plan's Properties panel or the object type editor's form. Each field shows its own
 * value, or, empty, the inherited one greyed (the placeholder) with where it comes from beside
 * it. A typed value is stored when the field is left (Tab, a click elsewhere, the panel or the
 * window closing), on Enter and before a save; the owner writes it as one undoable edit and
 * renders again. Until then the field is marked "not applied"; a value that cannot be stored
 * stays in its field, marked, and counts as a problem of the part (modifierProblems.ts).
 */

export interface IModifiersPanelOptions {
	readonly contextViewService: IContextViewService;
	/** Stores a field (`value` undefined clears it) on every target, as one edit. */
	readonly apply: (group: FieldGroup, key: string, value: number | Framing | undefined) => void;
	/** Clears a whole group on every target, as one edit. */
	readonly reset: (group: FieldGroup) => void;
	/** False shows the values read-only (the floor plan when it cannot be edited). */
	readonly editable?: boolean;
}

/** A field typed in but not stored when its panel was rendered again: kept for the new panel. */
interface ICarried {
	readonly id: string;
	readonly text: string;
	readonly focused: boolean;
	readonly selection: readonly [number, number];
	/** Stores the text, when the new panel does not show the field (its targets changed). */
	readonly commit: () => void;
}

let carried: ICarried | undefined;
/** The field to focus when the owner renders again after a store (Tab to the next field, Enter). */
let focusAfterStore: string | undefined;
/** The field just stored, shown as applied in the panels rendered soon after it. */
let justApplied: { readonly id: string; readonly at: number } | undefined;
/** How long a stored field shows as applied [ms]. */
const APPLIED_SHOWN = 2500;
/** The field being stored: the owner renders again meanwhile, and its old panel is let go quietly. */
let storing: string | undefined;

/** The fields with text not stored yet, each with what stores it. */
const pendingFields = new Map<string, () => void>();

/**
 * Stores every field with a typed value not yet stored (before a save, so Ctrl+S in a field
 * keeps what was typed). Values that cannot be stored stay in their fields.
 */
export function flushModifierFields(): void {
	for (const store of [...pendingFields.values()]) {
		store();
	}
}

function fieldId(view: IModifiersView, group: FieldGroup, key: string): string {
	return `${view.scope}|${group}|${key}`;
}

/** Renders both groups (a group with no field for the target's kind is left out). Listeners go to `store`. */
export function renderModifiers(container: HTMLElement, view: IModifiersView, store: DisposableStore, options: IModifiersPanelOptions): HTMLElement {
	const root = append(container, $('.sa-modifiers'));
	const part: ModifierPart = view.level === 'type' ? 'objects' : 'floorPlan';
	if (view.modifiers.length) {
		renderGroup(root, view, part, 'modifiers', localize('modifiers.heading', "Stiffness Modifiers"), view.modifiers, view.hasModifiers, view.note, store, options);
	}
	if (view.overwrites.length) {
		renderGroup(root, view, part, 'designOverwrites', localize('overwrites.heading', "Design Overwrites"), view.overwrites, view.hasOverwrites, localize('overwrites.note', "Empty: worked out by the design checks."), store, options);
	}
	return root;
}

/** The state line of a group: what is typed but not applied, what cannot be stored, what was just applied. */
class GroupStatus {
	private readonly dirty = new Set<string>();
	private readonly errors = new Set<string>();

	constructor(private readonly element: HTMLElement, private readonly section: HTMLElement) { }

	set(key: string, state: 'clean' | 'dirty' | 'error'): void {
		this.dirty.delete(key);
		this.errors.delete(key);
		if (state !== 'clean') {
			(state === 'dirty' ? this.dirty : this.errors).add(key);
		}
		this.render();
	}

	applied(): void {
		if (!this.dirty.size && !this.errors.size) {
			this.show('applied', localize('modifiers.applied', "Applied"));
		}
	}

	private render(): void {
		if (this.errors.size) {
			this.show('error', this.errors.size === 1
				? localize('modifiers.oneProblem', "1 value cannot be used")
				: localize('modifiers.problems', "{0} values cannot be used", this.errors.size));
		} else if (this.dirty.size) {
			this.show('dirty', localize('modifiers.notApplied', "Not applied yet: Enter or leave the field"));
		} else {
			this.show(undefined, '');
		}
	}

	private show(state: 'applied' | 'dirty' | 'error' | undefined, text: string): void {
		this.element.textContent = text;
		this.element.className = `sa-modifiers-status${state ? ` ${state}` : ''}`;
		this.section.classList.toggle('has-pending', state === 'dirty' || state === 'error');
	}
}

function renderGroup(container: HTMLElement, view: IModifiersView, part: ModifierPart, group: FieldGroup, title: string, rows: readonly IFieldRow[], hasOwn: boolean, note: string, store: DisposableStore, options: IModifiersPanelOptions): void {
	const section = append(container, $('.sa-modifiers-group', { role: 'group', 'aria-label': title }));
	const heading = append(section, $('.sa-modifiers-heading'));
	append(heading, $('span.sa-modifiers-title', undefined, title));
	const status = new GroupStatus(append(heading, $('span.sa-modifiers-status', { role: 'status', 'aria-live': 'polite' })), section);
	if (hasOwn && options.editable !== false) {
		const reset = append(heading, $<HTMLAnchorElement>('a.sa-modifiers-reset', { role: 'button', tabIndex: 0, title: localize('modifiers.resetTitle', "Clear every value of this group: back to the inherited values") }, localize('modifiers.reset', "Reset")));
		store.add(addDisposableListener(reset, EventType.CLICK, () => options.reset(group)));
		store.add(addDisposableListener(reset, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				options.reset(group);
			}
		}));
	}
	for (const row of rows) {
		renderRow(section, view, part, row, status, store, options);
	}
	append(section, $('.sa-modifiers-note', undefined, note));
}

function renderRow(container: HTMLElement, view: IModifiersView, part: ModifierPart, row: IFieldRow, status: GroupStatus, store: DisposableStore, options: IModifiersPanelOptions): void {
	const id = fieldId(view, row.group, row.key);
	const line = append(container, $('.sa-modifiers-row'));
	line.classList.toggle('own', row.own);
	line.dataset.key = row.key;
	line.dataset.field = id;
	const label = append(line, $('.sa-modifiers-label'));
	append(label, $('span.sa-modifiers-name', { title: row.hint }, row.label));
	const source = append(label, $('span.sa-modifiers-source', undefined, row.source));
	const control = append(line, $('.sa-modifiers-control'));
	if (row.warning) {
		line.classList.add('warning');
		source.title = row.warning;
		append(source, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-label', row.warning);
	}
	if (options.editable === false) {
		append(control, $('span.sa-modifiers-readonly', undefined, row.value || row.placeholder)).classList.toggle('inherited', !row.value);
		return;
	}
	if (row.key === 'framing') {
		renderFraming(control, row, store, options);
		return;
	}
	const box = store.add(new InputBox(control, options.contextViewService, {
		inputBoxStyles: defaultInputBoxStyles,
		placeholder: row.placeholder,
		ariaLabel: row.label,
		tooltip: row.hint,
		validationOptions: {
			validation: text => {
				const check = checkField(row.group, row.key, text);
				return check.error ? { content: check.error, type: MessageType.ERROR }
					: check.warning ? { content: check.warning, type: MessageType.WARNING }
						: null;
			},
		},
	}));
	box.value = row.value;
	const input = box.inputElement;

	/** Marks the field: typed and not stored, or not storable (a problem of the part), or as stored. */
	const mark = (): 'clean' | 'dirty' | 'error' => {
		const commit = commitField(row, box.value);
		const state = commit.error ? 'error' : commit.unchanged ? 'clean' : 'dirty';
		line.classList.toggle('dirty', state === 'dirty');
		line.classList.toggle('invalid', state === 'error');
		status.set(row.key, state);
		setUnappliedField(id, part, commit.error ? `${row.label}: ${box.value.trim()}: ${commit.error}` : undefined);
		if (state === 'dirty') {
			pendingFields.set(id, () => store_());
		} else {
			pendingFields.delete(id);
		}
		return state;
	};
	/** Stores the typed value; false when it cannot be stored (the error stays shown). */
	const store_ = (focusNext?: string): boolean => {
		const commit = commitField(row, box.value);
		if (commit.error) {
			box.showMessage({ content: commit.error, type: MessageType.ERROR });
			return false;
		}
		if (commit.unchanged) {
			return true;
		}
		pendingFields.delete(id);
		setUnappliedField(id, part, undefined);
		justApplied = { id, at: Date.now() };
		focusAfterStore = focusNext;
		storing = id;
		try {
			options.apply(row.group, row.key, commit.value);
		} finally {
			storing = focusAfterStore = undefined;
		}
		return true;
	};

	// What was typed before the owner rendered again (an edit elsewhere, the plan redrawn).
	if (carried?.id === id) {
		const kept = carried;
		carried = undefined;
		box.value = kept.text;
		if (kept.focused) {
			input.focus();
			input.setSelectionRange(kept.selection[0], kept.selection[1]);
		}
	} else if (focusAfterStore === id) {
		input.focus();
		input.select();
	}
	if (justApplied?.id === id && Date.now() - justApplied.at < APPLIED_SHOWN) {
		line.classList.add('applied');
		status.applied();
	}
	if (box.value !== row.value) {
		mark();
	}

	store.add(addDisposableListener(input, EventType.INPUT, () => mark()));
	store.add(addDisposableListener(input, EventType.KEY_DOWN, e => {
		if (e.key === 'Enter') {
			e.preventDefault();
			e.stopPropagation();
			store_(id);
		} else if (e.key === 'Escape') {
			box.value = row.value;
			mark();
		}
	}));
	store.add(addDisposableListener(input, EventType.BLUR, e => {
		if (storing || mark() !== 'dirty') {
			return;
		}
		// Tab or a click to another field of the panel: focus it again in the panel rendered
		// after the store; the window losing focus: this field, for when it comes back.
		const next = isHTMLElement(e.relatedTarget) ? e.relatedTarget.closest<HTMLElement>('.sa-modifiers-row')?.dataset.field : undefined;
		const windowLeft = !input.ownerDocument.hasFocus();
		store_(next ?? (windowLeft ? id : undefined));
	}));
	store.add(toDisposable(() => {
		pendingFields.delete(id);
		setUnappliedField(id, part, undefined);
		const commit = commitField(row, box.value);
		const focused = getActiveElement() === input;
		if (storing === id || commit.unchanged && !focused) {
			return;
		}
		// The panel is rendered again (or closed) while a value is typed: the next panel takes
		// it over when it shows this field; else a value that can be stored is stored then.
		carried = {
			id,
			text: box.value,
			focused,
			selection: [input.selectionStart ?? box.value.length, input.selectionEnd ?? box.value.length],
			commit: () => {
				if (!commit.error && !commit.unchanged) {
					options.apply(row.group, row.key, commit.value);
				}
			},
		};
		queueMicrotask(() => {
			const left = carried;
			if (left?.id === id) {
				carried = undefined;
				left.commit();
			}
		});
	}));
}

function renderFraming(control: HTMLElement, row: IFieldRow, store: DisposableStore, options: IModifiersPanelOptions): void {
	// Auto first; "(various)" first when the selection differs, so no choice is made by rendering.
	const choices: (Framing | undefined)[] = [...(row.various ? [undefined] : []), ...FRAMINGS];
	const current = row.various ? 0 : Math.max(0, choices.indexOf((row.value || 'auto') as Framing));
	const inherited = row.own ? undefined : row.placeholder;
	const select = store.add(new SelectBox(choices.map(choice => ({
		text: choice === undefined ? localize('field.various', "(various)")
			: choice === 'auto' && inherited && inherited !== framingLabel('auto') ? localize('overwrites.framingInherited', "Inherited: {0}", inherited)
				: framingLabel(choice),
	})), current, options.contextViewService, defaultSelectBoxStyles, { ariaLabel: row.label }));
	select.render(control);
	store.add(select.onDidSelect(({ index }) => {
		const choice = choices[index];
		if (choice !== undefined && index !== current) {
			options.apply(row.group, row.key, choice);
		}
	}));
}
