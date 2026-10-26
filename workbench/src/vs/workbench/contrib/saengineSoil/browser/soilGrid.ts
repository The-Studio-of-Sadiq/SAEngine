/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType, isHTMLInputElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { formatTsv, ICellPosition, ISheet, ISheetColumn, ISheetWrite, ISheetWriteResult, matchOption, moveCell, parseTsv, pasteAddsRows, pasteWrites, SheetMove } from './soilSheet.js';

/*
 * A spreadsheet-like grid over an ISheet (soilSheet.ts): one cell is active, a range may be
 * selected, typing starts an edit, Enter / Tab / the arrows move, Delete clears, Ctrl+C copies
 * the range as Excel does and Ctrl+V pastes a block copied from Excel at the active cell. Column
 * groups can be collapsed. The grid writes through the sheet and tells its owner, which stores
 * the report (one undoable edit) and renders the grid again with the same state.
 */

/** What survives the grid being rendered again: the cells, the collapsed groups, the scroll. */
export interface IGridState {
	active: ICellPosition;
	/** The other corner of the selected range (the active cell when undefined). */
	anchor?: ICellPosition;
	/** Whole rows are selected (by their row headers): Delete then removes them. */
	rowSelection?: boolean;
	readonly collapsed: Set<string>;
	/** The column a run of Tabs started in: Enter goes back to it on the next row (as in Excel). */
	tabStart?: number;
	scrollTop?: number;
	scrollLeft?: number;
}

export function newGridState(collapsed: readonly string[] = []): IGridState {
	return { active: { row: 0, column: 0 }, collapsed: new Set(collapsed) };
}

export interface IGridOptions {
	readonly sheet: ISheet;
	readonly state: IGridState;
	readonly ariaLabel: string;
	/** Whether the grid ends with a row to type a new entry into. */
	readonly newRow?: boolean;
	/** After cells were written (or rows removed): store the report and render again. */
	readonly onDidWrite: (result: ISheetWriteResult) => void;
	/** The active row changed (without a write). */
	readonly onDidChangeActiveRow?: (row: number) => void;
	/** The grid's own height limit [px]; it scrolls inside it. */
	readonly maxHeight?: number;
}

interface IEditing {
	readonly position: ICellPosition;
	readonly input: HTMLInputElement | HTMLSelectElement;
	/** `enter`: started by typing, the arrows commit and move; `edit`: F2 or a double click, the arrows move the caret. */
	readonly mode: 'enter' | 'edit';
	readonly disposables: DisposableStore;
}

export class SoilGrid extends Disposable {

	readonly element: HTMLElement;
	private readonly scroller: HTMLElement;
	private readonly messageElement: HTMLElement;
	private readonly confirmElement: HTMLElement;
	private readonly cells = new Map<string, HTMLTableCellElement>();
	private readonly rowElements: HTMLElement[] = [];
	private readonly renderDisposables = this._register(new DisposableStore());
	private readonly editing = this._register(new MutableDisposable<DisposableStore>());
	private edit: IEditing | undefined;
	private dragging = false;
	private pendingPaste: ((ok: boolean) => void) | undefined;
	private readonly confirmDisposables = this._register(new DisposableStore());

	constructor(container: HTMLElement, private readonly options: IGridOptions) {
		super();
		const sheet = options.sheet;
		this.element = append(container, $('.soil-grid', { 'data-sheet': sheet.id }));
		this.confirmElement = append(this.element, $('.soil-grid-confirm', { role: 'alertdialog' }));
		this.confirmElement.hidden = true;
		this.scroller = append(this.element, $('.soil-grid-scroll', { tabIndex: 0, role: 'grid', 'aria-label': options.ariaLabel, 'aria-multiselectable': 'true' }));
		if (options.maxHeight) {
			this.scroller.style.maxHeight = `${options.maxHeight}px`;
		}
		this.messageElement = append(this.element, $('.soil-grid-message', { 'aria-live': 'polite' }));
		this._register(addDisposableListener(this.scroller, EventType.KEY_DOWN, e => this.onKeyDown(e)));
		this._register(addDisposableListener(this.scroller, 'copy', e => this.onCopy(e as ClipboardEvent, false)));
		this._register(addDisposableListener(this.scroller, 'cut', e => this.onCopy(e as ClipboardEvent, true)));
		this._register(addDisposableListener(this.scroller, 'paste', e => void this.onPaste(e as ClipboardEvent)));
		this._register(addDisposableListener(this.scroller, EventType.SCROLL, () => {
			options.state.scrollTop = this.scroller.scrollTop;
			options.state.scrollLeft = this.scroller.scrollLeft;
		}));
		this._register(addDisposableListener(this.element.ownerDocument, EventType.MOUSE_UP, () => this.dragging = false));
		this.clampState();
		this.render();
	}

	override dispose(): void {
		this.pendingPaste?.(false);
		super.dispose();
	}

	get sheet(): ISheet {
		return this.options.sheet;
	}

	/** Whether the keyboard focus is in the grid (its cells or a cell being edited). */
	hasFocus(): boolean {
		const active = this.element.ownerDocument.activeElement;
		return !!active && this.element.contains(active);
	}

	isEditing(): boolean {
		return !!this.edit;
	}

	focus(): void {
		this.scroller.focus({ preventScroll: true });
		this.revealActive();
	}

	/** The columns shown, by index: a collapsed group shows none of its own. */
	visibleColumns(): number[] {
		return this.sheet.columns.map((c, i) => ({ c, i })).filter(({ c }) => !this.isCollapsed(c.group)).map(({ i }) => i);
	}

	private isCollapsed(group: string): boolean {
		return this.options.state.collapsed.has(group) && this.sheet.groups[0]?.id !== group;
	}

	private get rows(): number {
		return this.sheet.rowCount() + (this.options.newRow === false ? 0 : 1);
	}

	private clampState(): void {
		const state = this.options.state;
		const visible = this.visibleColumns();
		const clamp = (p: ICellPosition): ICellPosition => ({
			row: Math.max(0, Math.min(this.rows - 1, p.row)),
			column: visible.includes(p.column) ? p.column : visible.find(c => c > p.column) ?? visible[visible.length - 1] ?? 0,
		});
		state.active = clamp(state.active);
		state.anchor = state.anchor && clamp(state.anchor);
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		this.renderDisposables.clear();
		this.cells.clear();
		this.rowElements.length = 0;
		clearNode(this.scroller);
		const sheet = this.sheet;
		const state = this.options.state;
		const table = append(this.scroller, $<HTMLTableElement>('table.soil-grid-table'));
		const colgroup = append(table, $('colgroup'));
		append(colgroup, $('col', { style: 'width: 34px' }));
		const groupRow = append(append(table, $('thead')), $('tr.soil-grid-groups'));
		const headRow = append(table.tHead!, $('tr.soil-grid-head'));
		append(groupRow, $('th.soil-grid-corner', { rowspan: '2' }));
		let width = 34;
		for (const group of sheet.groups) {
			const columns = sheet.columns.filter(c => c.group === group.id);
			if (!columns.length) {
				continue;
			}
			const collapsed = this.isCollapsed(group.id);
			const collapsible = sheet.groups.length > 1 && sheet.groups[0].id !== group.id;
			const th = append(groupRow, $('th.soil-grid-group', { colspan: String(collapsed ? 1 : columns.length) }));
			th.classList.toggle('collapsed', collapsed);
			if (collapsible) {
				const button = append(th, $<HTMLButtonElement>('button.soil-grid-group-toggle', {
					type: 'button', tabIndex: -1,
					title: collapsed ? localize('soil.grid.expand', "Show the {0} columns", group.label) : localize('soil.grid.collapse', "Hide the {0} columns", group.label),
					'aria-expanded': String(!collapsed),
				}));
				append(button, $(ThemeIcon.asCSSSelector(collapsed ? Codicon.chevronRight : Codicon.chevronDown)));
				append(button, $('span', undefined, group.label));
				this.renderDisposables.add(addDisposableListener(button, EventType.CLICK, () => this.toggleGroup(group.id)));
			} else {
				append(th, $('span', undefined, group.label));
			}
			if (collapsed) {
				append(colgroup, $('col', { style: 'width: 22px' }));
				width += 22;
				append(headRow, $('th.soil-grid-collapsed'));
				continue;
			}
			for (const column of columns) {
				append(colgroup, $('col', { style: `width: ${column.width}px` }));
				width += column.width;
				const head = append(headRow, $('th.soil-grid-column', { title: column.title ?? '' }));
				head.classList.toggle('number', column.numeric);
				head.classList.toggle('computed', !!column.computed);
				append(head, $('span', undefined, column.label));
				if (column.unit) {
					append(head, $('span.soil-unit', undefined, column.unit));
				}
			}
		}
		table.style.width = `${width}px`;

		const body = append(table, $('tbody'));
		const visible = new Set(this.visibleColumns());
		for (let row = 0; row < this.rows; row++) {
			const isNew = row >= sheet.rowCount();
			const tr = append(body, $('tr.soil-grid-row', { role: 'row' }));
			this.rowElements.push(tr);
			tr.classList.toggle('new-row', isNew);
			const header = append(tr, $('th.soil-grid-row-header', { role: 'rowheader', title: isNew ? localize('soil.grid.newRowTitle', "Type in this row to add one") : localize('soil.grid.rowTitle', "Select the row; Delete removes the selected rows") }, isNew ? '+' : String(row + 1)));
			this.renderDisposables.add(addDisposableListener(header, EventType.MOUSE_DOWN, e => {
				if (isNew) {
					return;
				}
				e.preventDefault();
				this.selectRows(row, e.shiftKey);
			}));
			for (const group of sheet.groups) {
				const columns = sheet.columns.map((c, i) => ({ c, i })).filter(({ c }) => c.group === group.id);
				if (!columns.length) {
					continue;
				}
				if (this.isCollapsed(group.id)) {
					append(tr, $('td.soil-grid-collapsed'));
					continue;
				}
				for (const { c: column, i } of columns) {
					if (!visible.has(i)) {
						continue;
					}
					const td = append(tr, $<HTMLTableCellElement>('td.soil-grid-cell', { role: 'gridcell' }));
					this.cells.set(`${row}|${i}`, td);
					this.renderCell(td, row, column);
					this.renderDisposables.add(addDisposableListener(td, EventType.MOUSE_DOWN, e => this.onCellMouseDown(e, row, i)));
					this.renderDisposables.add(addDisposableListener(td, EventType.MOUSE_ENTER, () => {
						if (this.dragging) {
							this.extendTo({ row, column: i });
						}
					}));
					this.renderDisposables.add(addDisposableListener(td, EventType.DBLCLICK, () => this.startEdit('edit')));
				}
			}
		}
		if (state.scrollTop !== undefined) {
			this.scroller.scrollTop = state.scrollTop;
		}
		if (state.scrollLeft !== undefined) {
			this.scroller.scrollLeft = state.scrollLeft;
		}
		this.updateSelection();
	}

	private renderCell(td: HTMLTableCellElement, row: number, column: ISheetColumn): void {
		const sheet = this.sheet;
		const isNew = row >= sheet.rowCount();
		const text = isNew ? '' : sheet.text(row, column);
		td.textContent = text;
		td.classList.toggle('number', column.numeric);
		const readOnly = !isNew && sheet.isReadOnly(row, column) || !!column.computed;
		td.classList.toggle('readonly', readOnly);
		td.classList.toggle('derived', !isNew && sheet.isDerived(row, column));
		const problem = isNew ? undefined : sheet.problem(row, column);
		td.classList.toggle('error', problem?.severity === 'error');
		td.classList.toggle('warning', problem?.severity === 'warning');
		td.setAttribute('aria-invalid', String(!!problem));
		td.setAttribute('aria-readonly', String(readOnly));
		const hint = isNew ? undefined : sheet.hint(row, column);
		td.title = [problem?.message, hint].filter(Boolean).join('\n');
		if (isNew && this.visibleColumns()[0] === sheet.columns.indexOf(column)) {
			td.classList.add('placeholder');
			td.textContent = localize('soil.grid.newRow', "New row");
		}
	}

	private toggleGroup(group: string): void {
		const collapsed = this.options.state.collapsed;
		if (collapsed.has(group)) {
			collapsed.delete(group);
		} else {
			collapsed.add(group);
		}
		this.cancelEdit();
		this.clampState();
		this.render();
		this.focus();
	}

	// ───────────────────────────── selection ─────────────────────────────

	private range(): { top: number; bottom: number; left: number; right: number } {
		const { active, anchor } = this.options.state;
		const other = anchor ?? active;
		return {
			top: Math.min(active.row, other.row), bottom: Math.max(active.row, other.row),
			left: Math.min(active.column, other.column), right: Math.max(active.column, other.column),
		};
	}

	/** The visible columns of the selected range, in order. */
	private rangeColumns(): number[] {
		const { left, right } = this.range();
		return this.visibleColumns().filter(c => c >= left && c <= right);
	}

	private updateSelection(): void {
		const state = this.options.state;
		const range = this.range();
		for (const [key, td] of this.cells) {
			const [row, column] = key.split('|').map(Number);
			const inRange = row >= range.top && row <= range.bottom && column >= range.left && column <= range.right;
			const active = row === state.active.row && column === state.active.column;
			td.classList.toggle('selected', inRange && !active || inRange && !!state.anchor);
			td.classList.toggle('active', active);
			td.setAttribute('aria-selected', String(inRange));
		}
		const activeCell = this.cells.get(`${state.active.row}|${state.active.column}`);
		if (activeCell) {
			activeCell.id = activeCell.id || `soil-grid-${this.sheet.id}-${Math.random().toString(36).slice(2)}`;
			this.scroller.setAttribute('aria-activedescendant', activeCell.id);
		}
		this.rowElements.forEach((tr, row) => tr.classList.toggle('row-selected', !!state.rowSelection && row >= range.top && row <= range.bottom));
		this.showMessage();
	}

	/** The line under the grid: the active cell's problem, or what it is. */
	private showMessage(error?: string): void {
		const state = this.options.state;
		const column = this.sheet.columns[state.active.column];
		const problem = error ?? (column && state.active.row < this.sheet.rowCount() ? this.sheet.problem(state.active.row, column)?.message : undefined);
		this.messageElement.textContent = problem ?? '';
		this.messageElement.classList.toggle('error', !!problem);
		this.messageElement.hidden = !problem;
	}

	private setActive(position: ICellPosition, extend: boolean): void {
		const state = this.options.state;
		const previousRow = state.active.row;
		if (extend) {
			state.anchor ??= state.active;
		} else {
			state.anchor = undefined;
			state.rowSelection = false;
		}
		state.active = position;
		this.updateSelection();
		this.revealActive();
		if (position.row !== previousRow) {
			this.options.onDidChangeActiveRow?.(position.row);
		}
	}

	private extendTo(position: ICellPosition): void {
		const state = this.options.state;
		state.anchor ??= state.active;
		state.active = position;
		this.updateSelection();
	}

	private selectRows(row: number, extend: boolean): void {
		this.commitEdit(false);
		const state = this.options.state;
		const visible = this.visibleColumns();
		const first = visible[0] ?? 0;
		const last = visible[visible.length - 1] ?? 0;
		if (extend && state.rowSelection) {
			state.active = { row, column: first };
			state.anchor = { row: state.anchor?.row ?? row, column: last };
		} else {
			state.active = { row, column: first };
			state.anchor = { row, column: last };
		}
		state.rowSelection = true;
		this.updateSelection();
		this.scroller.focus({ preventScroll: true });
		this.options.onDidChangeActiveRow?.(row);
	}

	private revealActive(): void {
		const { active } = this.options.state;
		this.cells.get(`${active.row}|${active.column}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
	}

	private onCellMouseDown(e: MouseEvent, row: number, column: number): void {
		if (e.button !== 0) {
			return;
		}
		if (this.edit && this.edit.position.row === row && this.edit.position.column === column) {
			return; // a click inside the cell being edited places the caret
		}
		this.commitEdit(false);
		this.options.state.tabStart = undefined;
		e.preventDefault();
		this.scroller.focus({ preventScroll: true });
		this.setActive({ row, column }, e.shiftKey);
		this.dragging = true;
	}

	// ───────────────────────────── keyboard ─────────────────────────────

	private onKeyDown(e: KeyboardEvent): void {
		if (this.edit) {
			return; // the editor's own keys (onEditorKey)
		}
		const ctrl = e.ctrlKey || e.metaKey;
		const move = (to: SheetMove, extend = false) => {
			e.preventDefault();
			e.stopPropagation();
			this.setActive(this.target(this.options.state.active, to), extend);
		};
		switch (e.key) {
			case 'ArrowUp': return move(ctrl ? 'top' : 'up', e.shiftKey);
			case 'ArrowDown': return move(ctrl ? 'bottom' : 'down', e.shiftKey);
			case 'ArrowLeft': return move(ctrl ? 'home' : 'left', e.shiftKey);
			case 'ArrowRight': return move(ctrl ? 'end' : 'right', e.shiftKey);
			case 'Home': return move(ctrl ? 'top' : 'home', e.shiftKey);
			case 'End': return move(ctrl ? 'bottom' : 'end', e.shiftKey);
			case 'Tab': return move(e.shiftKey ? 'shiftTab' : 'tab');
			case 'Enter':
				return move(e.shiftKey ? 'shiftEnter' : 'enter');
			case 'F2':
				e.preventDefault();
				this.startEdit('edit');
				return;
			case 'Escape':
				if (this.options.state.anchor || this.pendingPaste) {
					e.preventDefault();
					this.pendingPaste?.(false);
					this.options.state.anchor = undefined;
					this.options.state.rowSelection = false;
					this.updateSelection();
				}
				return;
			case 'Delete':
			case 'Backspace':
				e.preventDefault();
				this.clearSelection();
				return;
		}
		if (ctrl && e.key.toLowerCase() === 'a') {
			e.preventDefault();
			const visible = this.visibleColumns();
			const state = this.options.state;
			state.anchor = { row: 0, column: visible[0] ?? 0 };
			state.active = { row: Math.max(0, this.sheet.rowCount() - 1), column: visible[visible.length - 1] ?? 0 };
			this.updateSelection();
			return;
		}
		if (e.key.length === 1 && !ctrl && !e.altKey) {
			// Typing replaces the cell, as in Excel.
			e.preventDefault();
			this.startEdit('enter', e.key);
		}
	}

	// ───────────────────────────── editing ─────────────────────────────

	private startEdit(mode: 'enter' | 'edit', initial?: string): void {
		const position = this.options.state.active;
		const column = this.sheet.columns[position.column];
		const td = this.cells.get(`${position.row}|${position.column}`);
		if (!column || !td) {
			return;
		}
		const isNew = position.row >= this.sheet.rowCount();
		if (column.computed || !isNew && this.sheet.isReadOnly(position.row, column)) {
			this.showMessage(this.sheet.hint(position.row, column) ?? localize('soil.grid.computed', "This value is worked out from the others."));
			return;
		}
		this.options.state.anchor = undefined;
		this.options.state.rowSelection = false;
		this.updateSelection();
		const disposables = new DisposableStore();
		this.editing.value = disposables;
		const current = isNew ? '' : this.sheet.editText(position.row, column);
		let input: HTMLInputElement | HTMLSelectElement;
		if (column.options && initial === undefined) {
			const select = $<HTMLSelectElement>('select.soil-grid-editor', { 'aria-label': column.label });
			const value = matchOption(column.options, current);
			for (const option of column.options) {
				const element = append(select, $<HTMLOptionElement>('option', { value: option.value }, option.label));
				element.selected = option.value === value;
			}
			input = select;
		} else {
			const text = $<HTMLInputElement>('input.soil-grid-editor', { type: 'text', spellcheck: 'false', 'aria-label': column.unit ? `${column.label} (${column.unit})` : column.label });
			text.value = initial ?? current;
			text.classList.toggle('number', column.numeric);
			input = text;
		}
		td.textContent = '';
		td.classList.add('editing');
		td.appendChild(input);
		this.edit = { position, input, mode, disposables };
		disposables.add(addDisposableListener(input, EventType.KEY_DOWN, e => this.onEditorKey(e)));
		disposables.add(addDisposableListener(input, EventType.BLUR, () => {
			// Leaving the grid (or clicking elsewhere) keeps what was typed.
			if (this.edit?.input === input) {
				this.commitEdit(false);
			}
		}));
		disposables.add(addDisposableListener(input, EventType.INPUT, () => input.classList.remove('invalid')));
		input.focus();
		if (isHTMLInputElement(input)) {
			const end = input.value.length;
			input.setSelectionRange(end, end);
		}
	}

	private onEditorKey(e: KeyboardEvent): void {
		const edit = this.edit;
		if (!edit) {
			return;
		}
		e.stopPropagation();
		const commitAndMove = (move: SheetMove) => {
			e.preventDefault();
			this.commitEdit(true, move);
		};
		switch (e.key) {
			case 'Enter': return commitAndMove(e.shiftKey ? 'shiftEnter' : 'enter');
			case 'Tab': return commitAndMove(e.shiftKey ? 'shiftTab' : 'tab');
			case 'Escape':
				e.preventDefault();
				this.cancelEdit();
				this.scroller.focus({ preventScroll: true });
				return;
		}
		if (edit.mode === 'enter' && isHTMLInputElement(edit.input)) {
			switch (e.key) {
				case 'ArrowUp': return commitAndMove('up');
				case 'ArrowDown': return commitAndMove('down');
				case 'ArrowLeft': return commitAndMove('left');
				case 'ArrowRight': return commitAndMove('right');
			}
		}
	}

	/** Ends the edit without writing. */
	private cancelEdit(): void {
		const edit = this.edit;
		if (!edit) {
			return;
		}
		this.edit = undefined;
		this.editing.clear();
		const td = this.cells.get(`${edit.position.row}|${edit.position.column}`);
		const column = this.sheet.columns[edit.position.column];
		if (td && column) {
			td.classList.remove('editing');
			this.renderCell(td, edit.position.row, column);
		}
		this.showMessage();
	}

	/**
	 * Writes what was typed. Refused text keeps the editor open, red, with the reason under the
	 * grid; written text moves on (`move`) and hands the result to the owner.
	 */
	private commitEdit(refocus: boolean, move?: SheetMove): void {
		const edit = this.edit;
		if (!edit) {
			return;
		}
		const column = this.sheet.columns[edit.position.column];
		const text = edit.input.value;
		const unchanged = edit.position.row < this.sheet.rowCount() && text === this.sheet.editText(edit.position.row, column);
		if (unchanged) {
			this.cancelEdit();
			if (move) {
				this.moveAfterEdit(move, edit.position);
			}
			if (refocus) {
				this.scroller.focus({ preventScroll: true });
			}
			return;
		}
		const result = this.sheet.write([{ row: edit.position.row, column: column.id, text }]);
		const error = result.errors[0];
		if (error) {
			edit.input.classList.add('invalid');
			edit.input.title = error.message;
			edit.input.setAttribute('aria-invalid', 'true');
			this.showMessage(error.message);
			if (!refocus) {
				// The focus went elsewhere: drop the refused text rather than keep a cell open.
				this.cancelEdit();
			}
			return;
		}
		this.edit = undefined;
		this.editing.clear();
		// The row may have moved: the sheets keep depth order, so a typed depth can re-sort it.
		const row = result.rows?.get(edit.position.row);
		const from = row === undefined ? edit.position : { row, column: edit.position.column };
		if (move) {
			this.moveAfterEdit(move, from, false);
		} else if (row !== undefined && row !== edit.position.row) {
			this.options.state.active = from;
			this.options.state.anchor = undefined;
		}
		const keepFocus = refocus || this.hasFocus();
		this.options.onDidWrite(result);
		if (keepFocus && this.scroller.isConnected) {
			this.scroller.focus({ preventScroll: true });
		}
	}

	/**
	 * Where a move from `from` lands. Tab and Shift+Tab remember where their run started; Enter
	 * after them goes down to that column (as in Excel), so a row typed with Tab and finished
	 * with Enter starts the next row in the same column. Any other move ends the run.
	 */
	private target(from: ICellPosition, move: SheetMove): ICellPosition {
		const state = this.options.state;
		const step = (position: ICellPosition, to: SheetMove) => moveCell(position, to, this.visibleColumns(), this.sheet.rowCount(), this.options.newRow !== false);
		if (move === 'tab' || move === 'shiftTab') {
			const next = step(from, move);
			state.tabStart = next.row === from.row ? state.tabStart ?? from.column : undefined;
			return next;
		}
		const start = state.tabStart;
		state.tabStart = undefined;
		return move === 'enter' && start !== undefined ? step({ row: from.row, column: start }, 'enter') : step(from, move);
	}

	private moveAfterEdit(move: SheetMove, from: ICellPosition, update = true): void {
		const state = this.options.state;
		const next = this.target(from, move);
		state.active = next;
		state.anchor = undefined;
		if (update) {
			this.updateSelection();
			this.revealActive();
		}
	}

	// ───────────────────────────── clear, copy, paste ─────────────────────────────

	private clearSelection(): void {
		const state = this.options.state;
		const range = this.range();
		const rows = Math.min(range.bottom, this.sheet.rowCount() - 1);
		if (state.rowSelection) {
			const remove: number[] = [];
			for (let row = range.top; row <= rows; row++) {
				remove.push(row);
			}
			if (remove.length) {
				this.sheet.removeRows(remove);
				state.rowSelection = false;
				state.anchor = undefined;
				state.active = { row: Math.min(range.top, Math.max(0, this.sheet.rowCount() - 1)), column: state.active.column };
				this.options.onDidWrite({ written: remove.length, added: 0, errors: [] });
			}
			return;
		}
		const writes: ISheetWrite[] = [];
		for (let row = range.top; row <= rows; row++) {
			for (const c of this.rangeColumns()) {
				const column = this.sheet.columns[c];
				if (!column.computed && !this.sheet.isReadOnly(row, column) && this.sheet.text(row, column) !== '' && !this.sheet.isDerived(row, column)) {
					writes.push({ row, column: column.id, text: '' });
				}
			}
		}
		if (writes.length) {
			this.finishWrite(this.sheet.write(writes));
		}
	}

	private finishWrite(result: ISheetWriteResult): void {
		if (result.errors.length) {
			this.showMessage(result.errors.length === 1 ? result.errors[0].message : localize('soil.grid.someRefused', "{0} cells were not written: {1}", result.errors.length, result.errors[0].message));
		}
		if (result.written || result.added) {
			this.options.onDidWrite(result);
		}
	}

	/** The selected range as Excel copies it (the cells as shown, depths in m). */
	selectionText(): string {
		const range = this.range();
		const rows: string[][] = [];
		for (let row = range.top; row <= Math.min(range.bottom, this.sheet.rowCount() - 1); row++) {
			rows.push(this.rangeColumns().map(c => this.sheet.text(row, this.sheet.columns[c])));
		}
		return rows.length ? formatTsv(rows) : '';
	}

	private onCopy(e: ClipboardEvent, cut: boolean): void {
		if (this.edit || !e.clipboardData) {
			return;
		}
		const text = this.selectionText();
		if (!text) {
			return;
		}
		e.preventDefault();
		e.clipboardData.setData('text/plain', text);
		if (cut) {
			this.clearSelection();
		}
	}

	private async onPaste(e: ClipboardEvent): Promise<void> {
		if (this.edit || !e.clipboardData) {
			return;
		}
		const text = e.clipboardData.getData('text/plain');
		if (!text) {
			return;
		}
		e.preventDefault();
		await this.paste(text);
	}

	/**
	 * Pastes a block copied from Excel with its top left at the active cell. When it would add
	 * rows the grid asks first, in a line above it.
	 */
	async paste(text: string): Promise<void> {
		const block = parseTsv(text);
		if (!block.length) {
			return;
		}
		const state = this.options.state;
		const at = state.anchor ? { row: this.range().top, column: this.range().left } : state.active;
		const visible = this.visibleColumns();
		const width = Math.max(...block.map(r => r.length));
		const adds = pasteAddsRows(at.row, block.length, this.sheet.rowCount());
		if (adds > 0 && !await this.confirm(localize('soil.grid.pasteAdds', "Paste {0} rows × {1} columns from row {2}? It adds {3} row(s).", block.length, width, at.row + 1, adds))) {
			return;
		}
		const writes = pasteWrites(this.sheet, at, block, visible);
		const start = Math.max(0, visible.indexOf(at.column));
		state.active = at;
		state.anchor = { row: at.row + block.length - 1, column: visible[Math.min(visible.length - 1, start + width - 1)] };
		this.finishWrite(this.sheet.write(writes));
	}

	/** Asks in the grid's confirmation line; resolves false on Cancel, Escape or a new question. */
	private confirm(message: string): Promise<boolean> {
		this.pendingPaste?.(false);
		this.confirmDisposables.clear();
		clearNode(this.confirmElement);
		append(this.confirmElement, $(`span.soil-grid-confirm-icon${ThemeIcon.asCSSSelector(Codicon.info)}`));
		append(this.confirmElement, $('span.soil-grid-confirm-text', undefined, message));
		const ok = append(this.confirmElement, $<HTMLButtonElement>('button.soil-grid-confirm-ok', { type: 'button' }, localize('soil.grid.paste', "Paste")));
		const cancel = append(this.confirmElement, $<HTMLButtonElement>('button.soil-grid-confirm-cancel', { type: 'button' }, localize('soil.grid.cancel', "Cancel")));
		this.confirmElement.hidden = false;
		return new Promise<boolean>(resolve => {
			const done = (value: boolean) => {
				if (this.pendingPaste === done) {
					this.pendingPaste = undefined;
				}
				this.confirmDisposables.clear();
				this.confirmElement.hidden = true;
				resolve(value);
			};
			this.pendingPaste = done;
			this.confirmDisposables.add(addDisposableListener(ok, EventType.CLICK, () => {
				done(true);
			}));
			this.confirmDisposables.add(addDisposableListener(cancel, EventType.CLICK, () => {
				done(false);
				this.scroller.focus({ preventScroll: true });
			}));
			ok.focus();
		});
	}
}
