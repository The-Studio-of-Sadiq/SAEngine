/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import {
	ARCH_TYPE_CATEGORIES,
	ArchTypeCategory,
	deleteArchType,
	duplicateArchType,
	IArchTypeEntry,
	listArchTypes,
	renameArchType,
	updateArchType,
} from './architectureComponents.js';
import type { IArchitecture } from './architectureModel.js';

const CATEGORY_LABELS: { readonly [cat in ArchTypeCategory]: string } = {
	wall: localize('typesLib.cat.wall', "Wall types"),
	door: localize('typesLib.cat.door', "Door types"),
	window: localize('typesLib.cat.window', "Window types"),
	finish: localize('typesLib.cat.finish', "Finish types"),
	roof: localize('typesLib.cat.roof', "Roof types"),
	railing: localize('typesLib.cat.railing', "Railing types"),
	ceiling: localize('typesLib.cat.ceiling', "Ceiling types"),
	curtainWall: localize('typesLib.cat.curtainWall', "Curtain wall types"),
	component: localize('typesLib.cat.component', "Component types"),
};

/**
 * Unified Types Browser panel over the Architecture editor: filters by type category, shows
 * usage counts, duplicates, renames (cascading id edits to instances), edits parametric fields,
 * refuses to delete types in use, and triggers office-standards library JSON import/export.
 */
export class ArchitectureTypesPanel extends Disposable {

	readonly element: HTMLElement;
	private readonly _onDidChange = this._register(new Emitter<IArchitecture>());
	readonly onDidChange = this._onDidChange.event;
	private readonly _onDidExport = this._register(new Emitter<void>());
	readonly onDidExport = this._onDidExport.event;
	private readonly _onDidImport = this._register(new Emitter<void>());
	readonly onDidImport = this._onDidImport.event;
	private readonly _onDidClose = this._register(new Emitter<void>());
	readonly onDidClose = this._onDidClose.event;

	private arch: IArchitecture;
	private filter: ArchTypeCategory | 'all' = 'all';
	private selected: { readonly category: ArchTypeCategory; readonly id: string } | undefined;
	private statusText: string | undefined;
	private statusIsError = false;

	private readonly categoryPicker: SelectBox;
	private readonly listHost: HTMLElement;
	private readonly detailHost: HTMLElement;
	private readonly messageHost: HTMLElement;
	private readonly listDisposables = this._register(new DisposableStore());
	private readonly detailDisposables = this._register(new DisposableStore());

	constructor(
		parent: HTMLElement,
		arch: IArchitecture,
		private readonly contextViewService: IContextViewService,
	) {
		super();
		this.arch = arch;

		this.element = append(parent, $('.sa-types-browser', { role: 'dialog', 'aria-label': localize('typesLib.aria', "Architectural Types Library") }));
		this._register({ dispose: () => this.element.remove() });

		const header = append(this.element, $('.sa-tb-header'));
		const titleBlock = append(header, $('.sa-tb-title'));
		append(titleBlock, $('h2', undefined, localize('typesLib.title', "Types Library")));
		append(titleBlock, $('.sa-tb-sub', undefined, localize('typesLib.sub', "Duplicate, rename, edit parameters, delete unused types, and import or export office standards JSON.")));

		const headerActions = append(header, $('.sa-tb-actions'));
		const filterOptions = [{ text: localize('typesLib.all', "All categories") }, ...ARCH_TYPE_CATEGORIES.map(c => ({ text: CATEGORY_LABELS[c] }))];
		this.categoryPicker = this._register(new SelectBox(filterOptions, 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('typesLib.filterAria', "Filter by category") }));
		const filterWrap = append(headerActions, $('.sa-tb-filter'));
		this.categoryPicker.render(filterWrap);
		this._register(this.categoryPicker.onDidSelect(({ index }) => {
			this.filter = index === 0 ? 'all' : ARCH_TYPE_CATEGORIES[index - 1];
			this.render();
		}));

		const importBtn = this._register(new Button(headerActions, { ...defaultButtonStyles, secondary: true }));
		importBtn.label = localize('typesLib.import', "Import JSON...");
		this._register(importBtn.onDidClick(() => this._onDidImport.fire()));

		const exportBtn = this._register(new Button(headerActions, { ...defaultButtonStyles, secondary: true }));
		exportBtn.label = localize('typesLib.export', "Export JSON...");
		this._register(exportBtn.onDidClick(() => this._onDidExport.fire()));

		const closeBtn = this._register(new Button(headerActions, { ...defaultButtonStyles }));
		closeBtn.label = localize('typesLib.close', "Close");
		this._register(closeBtn.onDidClick(() => this._onDidClose.fire()));

		this.messageHost = append(this.element, $('.sa-tb-message', { role: 'status' }));
		const body = append(this.element, $('.sa-tb-body'));
		this.listHost = append(body, $('.sa-tb-list', { role: 'listbox' }));
		this.detailHost = append(body, $('.sa-tb-detail'));

		this._register(addDisposableListener(this.element, EventType.KEY_DOWN, e => {
			if (e.key === 'Escape') {
				e.preventDefault();
				e.stopPropagation();
				this._onDidClose.fire();
			}
		}));

		this.render();
	}

	setArchitecture(arch: IArchitecture): void {
		this.arch = arch;
		this.render();
	}

	setStatus(text: string | undefined, isError = false): void {
		this.statusText = text;
		this.statusIsError = isError;
		this.renderStatus();
	}

	focus(): void {
		this.listHost.focus();
	}

	private renderStatus(): void {
		this.messageHost.textContent = this.statusText ?? '';
		this.messageHost.classList.toggle('error', this.statusIsError);
	}

	private render(): void {
		this.renderStatus();
		this.listDisposables.clear();
		clearNode(this.listHost);
		const entries = listArchTypes(this.arch, this.filter === 'all' ? undefined : this.filter);
		if (!entries.length) {
			append(this.listHost, $('.sa-tb-empty', undefined, localize('typesLib.empty', "No types in this category.")));
			this.selected = undefined;
			this.renderDetail(undefined);
			return;
		}
		if (!this.selected || !entries.some(e => e.category === this.selected!.category && e.id === this.selected!.id)) {
			this.selected = { category: entries[0].category, id: entries[0].id };
		}
		for (const entry of entries) {
			const active = this.selected?.category === entry.category && this.selected?.id === entry.id;
			const row = append(this.listHost, $('.sa-tb-row', { role: 'option', 'aria-selected': String(active), tabindex: '0' }));
			if (active) {
				row.classList.add('selected');
			}
			append(row, $('span.sa-tb-cat', undefined, CATEGORY_LABELS[entry.category].replace(/ types$/i, '')));
			append(row, $('span.sa-tb-id', undefined, entry.id));
			append(row, $('span.sa-tb-name', undefined, entry.name));
			append(row, $('span.sa-tb-usage', undefined, entry.usedBy.length ? localize('typesLib.usedCount', "{0} used", entry.usedBy.length) : localize('typesLib.unused', "unused")));
			this.listDisposables.add(addDisposableListener(row, EventType.CLICK, () => {
				this.selected = { category: entry.category, id: entry.id };
				this.setStatus(undefined);
				this.render();
			}));
		}
		const current = entries.find(e => e.category === this.selected!.category && e.id === this.selected!.id);
		this.renderDetail(current);
	}

	private renderDetail(entry: IArchTypeEntry | undefined): void {
		this.detailDisposables.clear();
		clearNode(this.detailHost);
		if (!entry) {
			return;
		}
		append(this.detailHost, $('h3', undefined, `${CATEGORY_LABELS[entry.category]} · ${entry.id}`));

		const applyArch = (next: IArchitecture, notice?: string) => {
			this.arch = next;
			this.setStatus(notice, false);
			this._onDidChange.fire(next);
			this.render();
		};

		const data = entry.data;
		let pendingId = entry.id;
		this.textRow(localize('typesLib.id', "ID"), entry.id, val => {
			pendingId = val.trim();
		});
		this.textRow(localize('typesLib.name', "Name"), entry.name, val => {
			if (val.trim() && val.trim() !== entry.name) {
				applyArch(updateArchType(this.arch, entry.category, entry.id, { name: val.trim() }), localize('typesLib.renamed', "Updated {0}.", entry.id));
			}
		});

		const renameWrap = append(this.detailHost, $('.sa-tb-btn-row'));
		const renameBtn = this.detailDisposables.add(new Button(renameWrap, { ...defaultButtonStyles, secondary: true }));
		renameBtn.label = localize('typesLib.applyRename', "Rename ID");
		this.detailDisposables.add(renameBtn.onDidClick(() => {
			if (!pendingId || pendingId === entry.id) {
				return;
			}
			const res = renameArchType(this.arch, entry.category, entry.id, pendingId);
			if (!res.ok) {
				this.setStatus(res.error, true);
				return;
			}
			this.selected = { category: entry.category, id: pendingId };
			applyArch(res.value, localize('typesLib.idRenamed', "Renamed {0} to {1} (updated instances).", entry.id, pendingId));
		}));

		const numRow = (label: string, field: string, value: unknown, min = 0) => {
			this.textRow(label, value === undefined ? '' : String(value), text => {
				const trimmed = text.trim();
				if (trimmed === '') {
					applyArch(updateArchType(this.arch, entry.category, entry.id, { [field]: undefined }));
					return;
				}
				const n = Number(trimmed);
				if (Number.isFinite(n) && n >= min) {
					applyArch(updateArchType(this.arch, entry.category, entry.id, { [field]: n }), localize('typesLib.updatedField', "Updated {0}.{1}.", entry.id, field));
				}
			});
		};
		const enumRow = (label: string, field: string, options: readonly string[], value: unknown) => {
			const cell = append(this.detailHost, $('.sa-tb-field'));
			append(cell, $('span.sa-tb-label', undefined, label));
			const current = typeof value === 'string' && options.includes(value) ? value : options[0];
			const select = this.detailDisposables.add(new SelectBox(options.map(o => ({ text: o })), Math.max(0, options.indexOf(current)), this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
			const host = append(cell, $('.sa-tb-control'));
			select.render(host);
			this.detailDisposables.add(select.onDidSelect(({ index }) => {
				const picked = options[index];
				if (picked !== undefined && picked !== value) {
					applyArch(updateArchType(this.arch, entry.category, entry.id, { [field]: picked }), localize('typesLib.updatedField', "Updated {0}.{1}.", entry.id, field));
				}
			}));
		};

		if (entry.category === 'door') {
			enumRow(localize('typesLib.style', "Style"), 'style', ['single', 'double', 'sliding'], data.style ?? 'single');
			numRow(localize('typesLib.width', "Width (mm)"), 'width', data.width, 1);
			numRow(localize('typesLib.height', "Height (mm)"), 'height', data.height, 1);
			numRow(localize('typesLib.frame', "Frame width (mm)"), 'frame', data.frame ?? 50, 1);
			numRow(localize('typesLib.leafCount', "Leaf count"), 'leafCount', data.leafCount, 1);
			enumRow(localize('typesLib.swing', "Swing"), 'swing', ['left', 'right', 'both', 'none'], data.swing ?? 'left');
			numRow(localize('typesLib.sill', "Sill height (mm)"), 'sill', data.sill ?? 0, 0);
			numRow(localize('typesLib.lintel', "Lintel depth (mm)"), 'lintel', data.lintel, 1);
		} else if (entry.category === 'window') {
			enumRow(localize('typesLib.style', "Style"), 'style', ['fixed', 'casement', 'sliding'], data.style ?? 'sliding');
			numRow(localize('typesLib.width', "Width (mm)"), 'width', data.width, 1);
			numRow(localize('typesLib.height', "Height (mm)"), 'height', data.height, 1);
			numRow(localize('typesLib.sill', "Sill height (mm)"), 'sill', data.sill ?? 900, 0);
			numRow(localize('typesLib.frame', "Frame width (mm)"), 'frame', data.frame ?? 50, 1);
			numRow(localize('typesLib.leafCount', "Leaf count"), 'leafCount', data.leafCount, 1);
			enumRow(localize('typesLib.swing', "Swing"), 'swing', ['inward', 'outward', 'left', 'right', 'none'], data.swing ?? 'none');
			numRow(localize('typesLib.lintel', "Lintel depth (mm)"), 'lintel', data.lintel, 1);
		} else if (entry.category === 'component') {
			enumRow(localize('typesLib.category', "Category"), 'category', ['furniture', 'casework', 'plumbingFixture', 'equipment', 'generic'], data.category ?? 'furniture');
			numRow(localize('typesLib.width', "Width (mm)"), 'width', data.width, 1);
			numRow(localize('typesLib.depth', "Depth (mm)"), 'depth', data.depth, 1);
			numRow(localize('typesLib.height', "Height (mm)"), 'height', data.height, 1);
			numRow(localize('typesLib.weightKg', "Weight (kg)"), 'weight', data.weight ?? 0, 0);
			this.textRow(localize('typesLib.material', "Material"), String(data.material ?? ''), val => {
				applyArch(updateArchType(this.arch, entry.category, entry.id, { material: val.trim() }), localize('typesLib.updatedField', "Updated {0}.{1}.", entry.id, 'material'));
			});
		} else if (entry.category === 'finish') {
			numRow(localize('typesLib.thickness', "Thickness (mm)"), 'thickness', data.thickness, 1);
			numRow(localize('typesLib.unitWeight', "Unit weight (kN/m³)"), 'unitWeight', data.unitWeight, 0);
			numRow(localize('typesLib.sunkFilling', "Sunk filling (mm)"), 'sunkFilling', data.sunkFilling, 0);
		} else if (entry.category === 'railing') {
			numRow(localize('typesLib.height', "Height (mm)"), 'height', data.height ?? 1000, 1);
			numRow(localize('typesLib.weightKnm', "Weight (kN/m)"), 'weight', data.weight ?? 0.3, 0);
			numRow(localize('typesLib.width', "Width (mm)"), 'width', data.width ?? 50, 1);
		} else if (entry.category === 'ceiling') {
			enumRow(localize('typesLib.ceilingKind', "Kind"), 'kind', ['gypsum', 'grid', 'plaster', 'timber', 'metal', 'other'], data.kind ?? 'gypsum');
			numRow(localize('typesLib.thickness', "Thickness (mm)"), 'thickness', data.thickness ?? 12.5, 1);
			numRow(localize('typesLib.weightKnm2', "Weight (kN/m²)"), 'weight', data.weight ?? 0.15, 0);
			numRow(localize('typesLib.gridX', "Grid X (mm)"), 'gridX', data.gridX, 1);
			numRow(localize('typesLib.gridY', "Grid Y (mm)"), 'gridY', data.gridY, 1);
		} else if (entry.category === 'curtainWall') {
			numRow(localize('typesLib.glassThickness', "Glass thickness (mm)"), 'glassThickness', data.glassThickness ?? 12, 1);
			numRow(localize('typesLib.mullionSpacing', "Mullion spacing (mm)"), 'mullionSpacing', data.mullionSpacing ?? 1500, 1);
			numRow(localize('typesLib.transomSpacing', "Transom spacing (mm)"), 'transomSpacing', data.transomSpacing ?? 1500, 1);
		}

		append(this.detailHost, $('.sa-tb-usage-info', undefined, entry.usedBy.length
			? localize('typesLib.usedBy', "Used by: {0}", entry.usedBy.join(', '))
			: localize('typesLib.notUsed', "Not referenced by any instance (safe to delete).")));

		const btns = append(this.detailHost, $('.sa-tb-btn-row'));
		const dupBtn = this.detailDisposables.add(new Button(btns, { ...defaultButtonStyles, secondary: true }));
		dupBtn.label = localize('typesLib.duplicate', "Duplicate");
		this.detailDisposables.add(dupBtn.onDidClick(() => {
			const res = duplicateArchType(this.arch, entry.category, entry.id);
			if (!res.ok) {
				this.setStatus(res.error, true);
				return;
			}
			this.selected = { category: entry.category, id: res.id };
			applyArch(res.value, localize('typesLib.duplicated', "Duplicated {0} as {1}.", entry.id, res.id));
		}));

		const delBtn = this.detailDisposables.add(new Button(btns, { ...defaultButtonStyles, secondary: true }));
		delBtn.label = localize('typesLib.delete', "Delete");
		this.detailDisposables.add(delBtn.onDidClick(() => {
			const res = deleteArchType(this.arch, entry.category, entry.id);
			if (!res.ok) {
				this.setStatus(res.error, true);
				return;
			}
			this.selected = undefined;
			applyArch(res.value, localize('typesLib.deleted', "Deleted type {0}.", entry.id));
		}));
	}

	private textRow(label: string, value: string, onCommit: (text: string) => void): void {
		const row = append(this.detailHost, $('.sa-tb-field'));
		append(row, $('span.sa-tb-label', undefined, label));
		const control = append(row, $('.sa-tb-control'));
		const box = this.detailDisposables.add(new InputBox(control, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: label }));
		box.value = value;
		const commit = () => {
			if (box.value !== value) {
				onCommit(box.value);
			}
		};
		this.detailDisposables.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				commit();
			}
		}));
		this.detailDisposables.add(addDisposableListener(box.inputElement, EventType.BLUR, commit));
	}
}
