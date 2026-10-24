/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modifiersPanel.css';
import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { checkField, commitField, FieldGroup, Framing, FRAMINGS, framingLabel, IFieldRow, IModifiersView } from './modifiersModel.js';

/*
 * The "Stiffness modifiers" and "Design overwrites" groups (see modifiersModel.ts), rendered into
 * the floor plan's Properties panel or the object type editor's form. Each field shows its own
 * value, or, empty, the inherited one greyed (the placeholder) with where it comes from beside
 * it. Enter stores a field; the owner writes it as one undoable edit and renders again.
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

/** Renders both groups (a group with no field for the target's kind is left out). Listeners go to `store`. */
export function renderModifiers(container: HTMLElement, view: IModifiersView, store: DisposableStore, options: IModifiersPanelOptions): HTMLElement {
	const root = append(container, $('.sa-modifiers'));
	if (view.modifiers.length) {
		renderGroup(root, 'modifiers', localize('modifiers.heading', "Stiffness Modifiers"), view.modifiers, view.hasModifiers, view.note, store, options);
	}
	if (view.overwrites.length) {
		renderGroup(root, 'designOverwrites', localize('overwrites.heading', "Design Overwrites"), view.overwrites, view.hasOverwrites, localize('overwrites.note', "Empty: worked out by the design checks."), store, options);
	}
	return root;
}

function renderGroup(container: HTMLElement, group: FieldGroup, title: string, rows: readonly IFieldRow[], hasOwn: boolean, note: string, store: DisposableStore, options: IModifiersPanelOptions): void {
	const section = append(container, $('.sa-modifiers-group', { role: 'group', 'aria-label': title }));
	const heading = append(section, $('.sa-modifiers-heading'));
	append(heading, $('span', undefined, title));
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
		renderRow(section, row, store, options);
	}
	append(section, $('.sa-modifiers-note', undefined, note));
}

function renderRow(container: HTMLElement, row: IFieldRow, store: DisposableStore, options: IModifiersPanelOptions): void {
	const line = append(container, $('.sa-modifiers-row'));
	line.classList.toggle('own', row.own);
	line.dataset.key = row.key;
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
	store.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
		if (e.key === 'Enter') {
			e.preventDefault();
			e.stopPropagation();
			const commit = commitField(row, box.value);
			if (commit.error) {
				box.showMessage({ content: commit.error, type: MessageType.ERROR });
				return;
			}
			if (commit.unchanged) {
				return;
			}
			options.apply(row.group, row.key, commit.value);
		} else if (e.key === 'Escape') {
			box.value = row.value;
		}
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
