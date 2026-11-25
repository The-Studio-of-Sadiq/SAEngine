/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/engineDataPanel.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Action, IAction } from '../../../../base/common/actions.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { safeIntl } from '../../../../base/common/date.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { basename } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { csvText } from '../../../../platform/saengine/common/csv.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineActionsService } from '../../../services/saengineProject/common/saengineActions.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from './editorFrame.js';
import { EngineDataPanelInput } from './engineDataPanelInput.js';
import {
	DataPanelRow,
	DataPanelValues,
	formatCell,
	getEngineDataPanel,
	IDataPanelContext,
	IDataPanelField,
	IDataPanelFieldOption,
	IDataPanelResult,
	IDataPanelTable,
	IEngineDataPanelDescriptor,
	statusTone,
	toCsvRows,
} from './engineDataPanelRegistry.js';

const collator = safeIntl.Collator(undefined, { numeric: true, sensitivity: 'base' });
let uniqueControlId = 0;

/**
 * Reusable EditorFrame-based results & data panel editor shared by U3 feature panels: renders
 * optional parameter inputs, Run/Recompute & Export CSV toolbar actions, metric cards, filterable
 * multi-tab sortable tables and a row/notes Properties side panel.
 */
export class EngineDataPanelEditor extends EditorPane {

	static readonly ID = EngineDataPanelInput.EDITOR_ID;

	private frame!: EditorFrame;
	private host!: HTMLElement;
	private readonly bodyStore = this._register(new DisposableStore());
	private readonly fieldStore = this._register(new DisposableStore());

	private descriptor: IEngineDataPanelDescriptor | undefined;
	private values: DataPanelValues = {};
	private dynamicOptions: { [key: string]: readonly IDataPanelFieldOption[] } = {};
	private result: IDataPanelResult | undefined;
	private activeTableId: string | undefined;
	private selectedRow: DataPanelRow | undefined;
	private filterText = '';
	private busy = false;
	private runSequence = 0;

	private runAction!: Action;
	private exportCsvAction!: Action;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@ISaengineActionsService private readonly actionsService: ISaengineActionsService,
		@IEditorService private readonly editorService: IEditorService,
		@INotificationService private readonly notificationService: INotificationService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
	) {
		super(EngineDataPanelEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.projectService.onDidChangeProject(() => {
			if (this.descriptor?.autoRun !== false && this.input) {
				void this.runPanel();
			} else {
				this.render();
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: EngineDataPanelEditor.ID,
			ariaLabel: localize('dataPanel.aria', "SAEngine Data Panel"),
			properties: {
				title: localize('dataPanel.properties', "Details"),
				defaultVisible: true,
				defaultWidth: 280,
			},
		}));
		this.host = append(this.frame.main, $('.sa-data-panel', { tabIndex: -1 }));

		this.runAction = this._register(new Action(
			'saengine.dataPanel.run',
			localize('dataPanel.run', "Run / Recompute"),
			ThemeIcon.asClassName(Codicon.play),
			true,
			() => this.runPanel()
		));
		this.exportCsvAction = this._register(new Action(
			'saengine.dataPanel.exportCsv',
			localize('dataPanel.exportCsv', "Export CSV"),
			ThemeIcon.asClassName(Codicon.export),
			false,
			() => this.exportCsv()
		));
	}

	override async setInput(input: EngineDataPanelInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		const descriptor = getEngineDataPanel(input.panelId);
		const samePanel = this.descriptor?.id === descriptor?.id;
		this.descriptor = descriptor;
		if (!samePanel) {
			this.values = {};
			this.dynamicOptions = {};
			this.result = undefined;
			this.activeTableId = undefined;
			this.selectedRow = undefined;
			this.filterText = '';
			for (const field of descriptor?.fields ?? []) {
				this.values[field.key] = field.defaultValue;
			}
		}
		this.updateChrome();
		this.render();
		if (descriptor?.loadInitial) {
			await this.loadInitial(descriptor);
		}
		if (descriptor?.autoRun !== false && !this.result) {
			await this.runPanel();
		}
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.host?.focus();
	}

	private createContext(): IDataPanelContext {
		return {
			project: this.projectService.project,
			commandService: this.commandService,
			actionsService: this.actionsService,
			editorService: this.editorService,
			fileService: this.fileService,
			openerService: this.openerService,
			notificationService: this.notificationService,
			fileDialogService: this.fileDialogService,
			refresh: () => this.runPanel(),
			engineRequest: async <T = unknown>(method: string, params?: object) => {
				return await this.commandService.executeCommand('saengine.engine.request', method, params ?? {}) as T;
			},
		};
	}

	private async loadInitial(descriptor: IEngineDataPanelDescriptor): Promise<void> {
		if (!descriptor.loadInitial) {
			return;
		}
		try {
			const init = await descriptor.loadInitial(this.createContext(), { ...this.values });
			if (!init || this.descriptor?.id !== descriptor.id) {
				return;
			}
			if (init.options) {
				this.dynamicOptions = { ...this.dynamicOptions, ...init.options };
			}
			if (init.values) {
				for (const [k, v] of Object.entries(init.values)) {
					if (v !== undefined) {
						this.values[k] = v;
					}
				}
			}
			if (init.note) {
				this.frame.setStatus({ text: init.note, severity: 'info' });
			}
			this.render();
		} catch {
			// Initial option loading is best-effort; main run reports explicit errors.
		}
	}

	private updateChrome(): void {
		const d = this.descriptor;
		this.frame.setTitle(d?.title ?? localize('dataPanel.unknownTitle', "Data Panel"));
		this.frame.setHelp(d?.help);
		this.runAction.label = d?.runLabel ?? localize('dataPanel.run', "Run / Recompute");
		const hasRows = !!this.currentTable()?.rows.length;
		this.exportCsvAction.enabled = !this.busy && hasRows;
		const secondary: IAction[] = [];
		for (const act of d?.secondaryActions ?? []) {
			secondary.push(new Action(
				`saengine.dataPanel.sec.${act.id}`,
				act.label,
				act.icon ? ThemeIcon.asClassName(act.icon) : undefined,
				!this.busy,
				async () => { await act.run(this.createContext(), { ...this.values }, this.result); }
			));
		}
		if (this.result?.primaryAction) {
			const pa = this.result.primaryAction;
			secondary.unshift(new Action(
				`saengine.dataPanel.dyn.${pa.id}`,
				pa.label,
				pa.icon ? ThemeIcon.asClassName(pa.icon) : undefined,
				!this.busy,
				async () => { await pa.run(this.createContext(), { ...this.values }, this.result); }
			));
		}
		this.frame.setActions([this.runAction, this.exportCsvAction, this.frame.togglePropertiesAction], secondary);
	}

	async runPanel(): Promise<void> {
		const d = this.descriptor;
		if (!d) {
			return;
		}
		if (d.requiresProject !== false && !this.projectService.project) {
			this.frame.setEmpty({
				icon: Codicon.folderOpened,
				title: localize('dataPanel.noProjectTitle', "Open a SAEngine project first"),
				text: localize('dataPanel.noProjectText', "This panel needs an open project before running computations."),
				actions: [{
					label: localize('dataPanel.openProject', "Open Project..."),
					icon: Codicon.folderOpened,
					primary: true,
					run: () => void this.commandService.executeCommand('saengine.project.open'),
				}],
			});
			return;
		}
		const seq = ++this.runSequence;
		this.busy = true;
		this.runAction.enabled = false;
		this.frame.showProgress();
		this.frame.setEmpty(undefined);
		this.frame.setStatus({ text: localize('dataPanel.running', "Running {0}...", d.title), busy: true });
		this.updateChrome();
		try {
			const result = await d.run(this.createContext(), { ...this.values });
			if (seq !== this.runSequence || this.descriptor?.id !== d.id) {
				return;
			}
			this.result = result;
			if (result.updatedOptions) {
				this.dynamicOptions = { ...this.dynamicOptions, ...result.updatedOptions };
			}
			if (result.updatedValues) {
				for (const [k, v] of Object.entries(result.updatedValues)) {
					if (v !== undefined) {
						this.values[k] = v;
					}
				}
			}
			if (!this.activeTableId || !result.tables.some(t => t.id === this.activeTableId)) {
				this.activeTableId = result.tables[0]?.id;
			}
			this.selectedRow = this.currentTable()?.rows[0];
			const errCount = result.problems?.length ?? 0;
			this.frame.setStatus({
				text: result.statusText ?? (errCount
					? localize('dataPanel.doneWithProblems', "{0} completed with {1} message(s).", d.title, errCount)
					: localize('dataPanel.done', "{0} completed.", d.title)),
				severity: result.statusSeverity ?? (errCount ? 'warning' : 'info'),
				icon: errCount ? Codicon.warning : Codicon.check,
			});
		} catch (error) {
			if (seq !== this.runSequence) {
				return;
			}
			const msg = error instanceof Error ? error.message : String(error);
			this.result = { tables: [], problems: [msg] };
			this.frame.setStatus({ text: msg, severity: 'error' });
		} finally {
			if (seq === this.runSequence) {
				this.busy = false;
				this.runAction.enabled = true;
				this.frame.hideProgress();
				this.updateChrome();
				this.render();
			}
		}
	}

	private currentTable(): IDataPanelTable | undefined {
		const tables = this.result?.tables ?? [];
		return tables.find(t => t.id === this.activeTableId) ?? tables[0];
	}

	private async exportCsv(): Promise<void> {
		const table = this.currentTable();
		if (!table || !table.rows.length) {
			return;
		}
		const safe = table.title.replace(/[^a-zA-Z0-9._-]+/g, '-').toLowerCase() || 'export';
		const defaultUri = this.projectService.project
			? URI.joinPath(this.projectService.project.root, `${safe}.csv`)
			: undefined;
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('dataPanel.saveCsv', "Export Table as CSV"),
			defaultUri,
			filters: [{ name: localize('dataPanel.csvFilter', "CSV Files"), extensions: ['csv'] }],
		});
		if (!target) {
			return;
		}
		const content = '\uFEFF' + csvText(toCsvRows(table));
		await this.fileService.writeFile(target, VSBuffer.fromString(content));
		this.notificationService.info(localize('dataPanel.csvWritten', "Saved {0} ({1} row(s)).", basename(target), table.rows.length));
	}

	private render(): void {
		this.bodyStore.clear();
		this.fieldStore.clear();
		clearNode(this.host);
		this.renderProperties();

		const d = this.descriptor;
		if (!d) {
			this.frame.setEmpty({
				icon: Codicon.warning,
				title: localize('dataPanel.notRegistered', "Panel not available"),
				text: localize('dataPanel.notRegisteredText', "This SAEngine panel is not registered in this session."),
			});
			return;
		}
		if (d.requiresProject !== false && !this.projectService.project) {
			this.frame.setEmpty({
				icon: Codicon.folderOpened,
				title: localize('dataPanel.noProjectTitle', "Open a SAEngine project first"),
				text: localize('dataPanel.noProjectText', "This panel needs an open project before running computations."),
				actions: [{
					label: localize('dataPanel.openProject', "Open Project..."),
					icon: Codicon.folderOpened,
					primary: true,
					run: () => void this.commandService.executeCommand('saengine.project.open'),
				}],
			});
			return;
		}

		this.renderForm(d);

		const res = this.result;
		if (!res) {
			if (d.autoRun === false) {
				append(this.host, $('.sa-dp-banner', undefined, localize('dataPanel.readyHint', "Review options above and click \"{0}\" to compute.", d.runLabel ?? localize('dataPanel.run', "Run / Recompute"))));
			}
			return;
		}

		if (res.emptyState && (!res.tables.length || res.tables.every(t => !t.rows.length))) {
			const es = res.emptyState;
			this.frame.setEmpty({
				icon: es.icon ?? Codicon.info,
				title: es.title,
				text: es.text,
				actions: es.action ? [{
					label: es.action.label,
					icon: es.action.icon,
					primary: true,
					run: () => void es.action!.run(this.createContext(), { ...this.values }, res),
				}] : undefined,
			});
		} else {
			this.frame.setEmpty(undefined);
		}

		if (res.metrics?.length) {
			const strip = append(this.host, $('.sa-dp-metrics'));
			for (const m of res.metrics) {
				const card = append(strip, $(`.sa-dp-metric${m.tone && m.tone !== 'neutral' ? `.${m.tone}` : ''}`));
				append(card, $('.label', undefined, m.label));
				append(card, $('.value', undefined, m.value));
			}
		}

		if (res.problems?.length) {
			const banner = append(this.host, $('.sa-dp-banner', { role: 'alert' }));
			for (const p of res.problems) {
				append(banner, $('div', undefined, p));
			}
		}

		if (res.outputFiles?.length) {
			const bar = append(this.host, $('.sa-dp-files'));
			for (const f of res.outputFiles) {
				const btn = append(bar, $<HTMLButtonElement>('button.sa-dp-file-btn', { type: 'button' }));
				append(btn, $(ThemeIcon.asCSSSelector(Codicon.goToFile)));
				append(btn, $('span', undefined, f.label));
				this.bodyStore.add(addDisposableListener(btn, EventType.CLICK, () => {
					void this.openerService.open(URI.file(f.path), { openExternal: true });
				}));
			}
		}

		if (res.tables.length) {
			this.renderTables(res);
		}
	}

	private renderForm(descriptor: IEngineDataPanelDescriptor): void {
		const fields = (descriptor.fields ?? []).filter(f => !f.visibleWhen || f.visibleWhen(this.values));
		if (!fields.length && descriptor.autoRun !== false) {
			return;
		}
		const form = append(this.host, $<HTMLFormElement>('form.sa-dp-form'));
		this.fieldStore.add(addDisposableListener(form, 'submit', e => {
			e.preventDefault();
			void this.runPanel();
		}));

		for (const field of fields) {
			this.renderField(form, field, descriptor);
		}

		const submitWrap = append(form, $('.sa-dp-submit-wrap'));
		const submitBtn = this.fieldStore.add(new Button(submitWrap, { ...defaultButtonStyles, supportIcons: true }));
		submitBtn.element.setAttribute('type', 'submit');
		submitBtn.label = `$(play) ${descriptor.runLabel ?? localize('dataPanel.run', "Run / Recompute")}`;
		submitBtn.enabled = !this.busy;
	}

	private renderField(form: HTMLElement, field: IDataPanelField, descriptor: IEngineDataPanelDescriptor): void {
		const inputId = `sa-dp-f-${++uniqueControlId}`;
		const val = this.values[field.key] ?? field.defaultValue;

		if (field.type === 'checkbox') {
			const wrap = append(form, $('.sa-dp-field.checkbox'));
			const cb = append(wrap, $<HTMLInputElement>('input', { type: 'checkbox', id: inputId, name: field.key }));
			cb.checked = Boolean(val);
			append(wrap, $('label', { for: inputId, title: field.help ?? '' }, field.label));
			this.fieldStore.add(addDisposableListener(cb, EventType.CHANGE, () => {
				this.values[field.key] = cb.checked;
				this.render();
			}));
			return;
		}

		const wide = field.type === 'file' || field.type === 'folder' || field.type === 'text';
		const wrap = append(form, $(`.sa-dp-field${wide ? '.wide' : ''}`));
		append(wrap, $('label', { for: inputId, title: field.help ?? '' }, field.label));
		const row = append(wrap, $('.sa-dp-input-row'));

		if (field.type === 'select') {
			const sel = append(row, $<HTMLSelectElement>('select', { id: inputId, name: field.key }));
			const opts = this.dynamicOptions[field.key] ?? field.options ?? [];
			for (const opt of opts) {
				const optionEl = append(sel, $<HTMLOptionElement>('option', { value: opt.value }, opt.label));
				if (String(val) === opt.value) {
					optionEl.selected = true;
				}
			}
			this.fieldStore.add(addDisposableListener(sel, EventType.CHANGE, () => {
				this.values[field.key] = sel.value;
				this.render();
			}));
			return;
		}

		if (field.type === 'number') {
			const inp = append(row, $<HTMLInputElement>('input', {
				type: 'number',
				id: inputId,
				name: field.key,
				step: field.step ?? 'any',
				value: String(val),
			}));
			if (field.min !== undefined) {
				inp.min = String(field.min);
			}
			if (field.max !== undefined) {
				inp.max = String(field.max);
			}
			this.fieldStore.add(addDisposableListener(inp, EventType.INPUT, () => {
				const parsed = Number(inp.value);
				if (Number.isFinite(parsed)) {
					this.values[field.key] = parsed;
				}
			}));
			return;
		}

		const inp = append(row, $<HTMLInputElement>('input', {
			type: 'text',
			id: inputId,
			name: field.key,
			value: String(val),
			placeholder: field.placeholder ?? '',
		}));
		inp.autocapitalize = 'none';
		inp.spellcheck = false;
		this.fieldStore.add(addDisposableListener(inp, EventType.INPUT, () => {
			this.values[field.key] = inp.value;
		}));

		if (field.type === 'file' || field.type === 'folder') {
			const browseBtn = append(row, $<HTMLButtonElement>('button.sa-dp-browse', { type: 'button' }, localize('dataPanel.browse', "Browse...")));
			this.fieldStore.add(addDisposableListener(browseBtn, EventType.CLICK, async () => {
				const defaultUri = this.projectService.project?.root;
				const picked = field.saveMode
					? await this.fileDialogService.showSaveDialog({
						title: field.label,
						defaultUri,
						filters: field.filters?.map(f => ({ name: f.name, extensions: [...f.extensions] })),
					})
					: (await this.fileDialogService.showOpenDialog({
						title: field.label,
						defaultUri,
						canSelectFiles: field.type === 'file',
						canSelectFolders: field.type === 'folder',
						canSelectMany: false,
						filters: field.filters?.map(f => ({ name: f.name, extensions: [...f.extensions] })),
					}))?.[0];
				if (picked && this.descriptor?.id === descriptor.id) {
					this.values[field.key] = picked.fsPath;
					inp.value = picked.fsPath;
				}
			}));
		}
	}

	private renderTables(res: IDataPanelResult): void {
		const active = this.currentTable();
		if (!active) {
			return;
		}

		const bar = append(this.host, $('.sa-dp-table-bar'));
		const tabs = append(bar, $('.sa-dp-tabs', { role: 'tablist' }));
		for (const tbl of res.tables) {
			const isSelected = tbl.id === active.id;
			const tab = append(tabs, $<HTMLButtonElement>(`button.sa-dp-tab${isSelected ? '.active' : ''}`, {
				type: 'button',
				role: 'tab',
				'aria-selected': String(isSelected),
			}, `${tbl.title} (${tbl.rows.length})`));
			this.bodyStore.add(addDisposableListener(tab, EventType.CLICK, () => {
				this.activeTableId = tbl.id;
				this.selectedRow = tbl.rows[0];
				this.render();
			}));
		}

		const searchWrap = append(bar, $('search.sa-dp-search'));
		const filterId = `sa-dp-search-${++uniqueControlId}`;
		append(searchWrap, $('label.visually-hidden', { for: filterId }, localize('dataPanel.filterLabel', "Filter rows")));
		const filterInput = append(searchWrap, $<HTMLInputElement>('input.sa-dp-search-input', {
			type: 'search',
			id: filterId,
			value: this.filterText,
			placeholder: localize('dataPanel.filterPlaceholder', "Filter rows..."),
		}));

		if (!active.rows.length) {
			append(this.host, $('.sa-dp-banner', undefined, active.emptyMessage ?? localize('dataPanel.emptyTable', "No rows in this view.")));
			return;
		}

		const statusLive = append(this.host, $('.visually-hidden', { role: 'status', 'aria-live': 'polite' }));
		const captionId = `sa-dp-cap-${++uniqueControlId}`;
		const region = append(this.host, $('.sa-dp-table-wrap', { role: 'region', 'aria-labelledby': captionId, tabIndex: 0 }));
		const table = append(region, $<HTMLTableElement>('table.sa-dp-table'));
		append(table, $('caption.visually-hidden', { id: captionId }, active.title));
		const thead = append(table, $('thead'));
		const headRow = append(thead, $<HTMLTableRowElement>('tr'));
		const tbody = append(table, $<HTMLTableSectionElement>('tbody'));

		const columns = active.columns;
		columns.forEach((col, colIndex) => {
			const th = append(headRow, $<HTMLTableCellElement>(`th${col.align === 'right' || col.type === 'number' ? '.right' : ''}`, {
				scope: 'col',
				'data-type': col.type ?? 'string',
			}));
			const btn = append(th, $<HTMLButtonElement>('button.sa-dp-th-btn', { type: 'button' }));
			append(btn, $('span', undefined, col.title));
			append(btn, $('span.sa-dp-sort-ind', { 'aria-hidden': 'true' }));
			this.bodyStore.add(addDisposableListener(btn, EventType.CLICK, () => {
				const dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
				for (const header of headRow.cells) {
					header.removeAttribute('aria-sort');
				}
				th.setAttribute('aria-sort', dir);
				const factor = dir === 'ascending' ? 1 : -1;
				const colType = col.type ?? 'string';
				const domRows = Array.from(tbody.rows);
				domRows.sort((a, b) => {
					const ca = a.cells[colIndex];
					const cb = b.cells[colIndex];
					const va = ca?.dataset.sortValue ?? ca?.textContent?.trim() ?? '';
					const vb = cb?.dataset.sortValue ?? cb?.textContent?.trim() ?? '';
					if (colType === 'number') {
						const na = Number(va);
						const nb = Number(vb);
						const fa = Number.isFinite(na) ? na : Number.NEGATIVE_INFINITY;
						const fb = Number.isFinite(nb) ? nb : Number.NEGATIVE_INFINITY;
						return factor * (fa - fb);
					}
					return factor * collator.value.compare(va, vb);
				});
				const move = (tbody as HTMLTableSectionElement & { moveBefore?: (node: Node, child: Node | null) => void }).moveBefore;
				for (const r of domRows) {
					if (typeof move === 'function') {
						move.call(tbody, r, null);
					} else {
						tbody.appendChild(r);
					}
				}
				statusLive.textContent = localize('dataPanel.sorted', "Sorted by {0}, {1}, {2} rows", col.title, dir, domRows.length);
			}));
		});

		const rowElements: { tr: HTMLTableRowElement; searchable: string }[] = [];
		for (const row of active.rows) {
			const tr = append(tbody, $<HTMLTableRowElement>(`tr${row === this.selectedRow ? '.selected' : ''}`));
			const parts: string[] = [];
			for (const col of columns) {
				const raw = row[col.key];
				const formatted = formatCell(raw);
				parts.push(formatted);
				const td = append(tr, $<HTMLTableCellElement>(`td${col.align === 'right' || col.type === 'number' ? '.right' : ''}`));
				td.dataset.sortValue = raw === null || raw === undefined ? '' : String(raw);
				if (col.type === 'status') {
					const tone = statusTone(raw);
					append(td, $(`span.sa-dp-badge${tone !== 'neutral' ? `.${tone}` : ''}`, undefined, formatted));
				} else {
					td.textContent = formatted;
				}
			}
			rowElements.push({ tr, searchable: parts.join(' ').toLowerCase() });
			this.bodyStore.add(addDisposableListener(tr, EventType.CLICK, () => {
				for (const r of rowElements) {
					r.tr.classList.remove('selected');
				}
				tr.classList.add('selected');
				this.selectedRow = row;
				this.renderProperties();
			}));
		}

		const applyFilter = () => {
			const needle = this.filterText.trim().toLowerCase();
			for (const entry of rowElements) {
				entry.tr.hidden = !!needle && !entry.searchable.includes(needle);
			}
		};
		applyFilter();
		this.bodyStore.add(addDisposableListener(filterInput, EventType.INPUT, () => {
			this.filterText = filterInput.value;
			applyFilter();
		}));
	}

	private renderProperties(): void {
		const container = this.frame.properties;
		if (!container) {
			return;
		}
		clearNode(container);
		if (this.selectedRow) {
			appendPropertyHeading(container, localize('dataPanel.selectedRow', "Selected Item"));
			for (const [key, val] of Object.entries(this.selectedRow)) {
				const tone = statusTone(val);
				appendPropertyRow(container, key, formatCell(val), tone === 'fail');
			}
		}
		const notes = this.result?.notes ?? [];
		if (notes.length) {
			appendPropertyHeading(container, localize('dataPanel.notesHeading', "Notes"));
			for (const note of notes) {
				appendPropertyNote(container, note);
			}
		}
		const problems = this.result?.problems ?? [];
		if (problems.length) {
			appendPropertyHeading(container, localize('dataPanel.problemsHeading', "Problems"));
			for (const p of problems) {
				appendPropertyRow(container, localize('dataPanel.issueLabel', "Issue"), p, true);
			}
		}
		if (!this.selectedRow && !notes.length && !problems.length) {
			appendPropertyNote(container, localize('dataPanel.propsEmpty', "Select a row to inspect all attributes and engineering notes."));
		}
	}
}
