/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femModelEditor.css';
import type { FemModel, FemResultDisplay, FemSelection, FemViewer, FemViewerTheme } from '@saengine/fem-viewer';
import { $, addDisposableListener, append, Dimension, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { csvText } from '../../../../platform/saengine/common/csv.js';
import { IFemCaseResults, IFemResultTable, IFemResultView } from '../../../../platform/saengine/common/femSolver.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { chartsBlue, chartsGreen, chartsLines, chartsOrange, chartsRed, chartsYellow } from '../../../../platform/theme/common/colors/chartsColors.js';
import { editorBackground, editorForeground } from '../../../../platform/theme/common/colors/editorColors.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { FemDerivation, IFemDeriveOutcome } from './femDerivationBar.js';
import { DESIGN_REINFORCEMENT_COMMAND } from './femDesign.js';
import { FemModelEditorInput } from './femModelEditorInput.js';
import { errorSummary, FEM_RESULT_TABLES_COMMAND, FEM_RUN_CASES_COMMAND, FEM_SHOW_CHARTS_COMMAND, FEM_SHOW_LOG_COMMAND, FEM_SHOW_MEMBER_COMMAND, FemResultsBar, IFemRun, IFemRunOptions, IFemRunOutcome, IFemRunTracker } from './femResultsBar.js';
import { baseReactionTable, exportCell, FEM_EXPORT_XLSX_COMMAND, FEM_STORY_RESPONSE_COMMAND, filterRows, formatCell, IFemSheet, IFemStoryResponse, modalTable, sortRows, storeyTable, workbookSheets } from './femChartData.js';
import { renderSheetRows } from './femChart.js';
import { chartUnits } from './femResultsView.js';
import { cameraOf, FemViewChoice, IFilterModel, viewChoices, visibleElements } from './femViewFilter.js';
import { loadViewerModule } from './viewerModule.js';

/** The building member an analysis element belongs to (`C3#2` -> `C3`). */
export function memberOf(name: string): string {
	return name.split('#')[0];
}

/** Rows of a result table drawn at once; the export has them all. */
const MAX_TABLE_ROWS = 500;

/** All result tables as CSV: per table a heading row (case, table), its columns and its rows. */
export function resultTablesCsv(cases: readonly IFemCaseResults[]): string {
	const lines: string[][] = [];
	for (const c of cases) {
		for (const table of c.tables) {
			if (lines.length) {
				lines.push([]);
			}
			lines.push([c.caseName, table.title]);
			lines.push([...table.columns]);
			lines.push(...table.rows.map(row => row.map(exportCell)));
		}
	}
	return csvText(lines);
}

/**
 * The result tables of the last run under the 3D view: a case, one of its tables, and its rows
 * (the first {@link MAX_TABLE_ROWS} of those the filter keeps, sorted by the column clicked;
 * Export has them all). A Summary entry after the cases holds the storey response, the base
 * reactions and the modal participation of every result.
 */
class FemTablesPanel extends Disposable {

	readonly element: HTMLElement;
	private readonly casePicker: SelectBox;
	private readonly tablePicker: SelectBox;
	private readonly filterBox: InputBox;
	private readonly count: HTMLElement;
	private readonly body: HTMLElement;
	private readonly scrollable: DomScrollableElement;
	private readonly caption: HTMLElement;
	private cases: readonly IFemCaseResults[] = [];
	/** The summary tables (storey response, base reactions, modes), read after the cases. */
	private summary: IFemCaseResults | undefined;
	private caseIndex = 0;
	private tableIndex = 0;
	private request = 0;
	private filter = '';
	private sort: { readonly column: number; readonly descending: boolean } | undefined;
	/** The result picked in the toolbar: its tables are shown. */
	private followed: string | undefined;
	/** The listeners of the table drawn (built again with every sort and filter). */
	private readonly tableStore = this._register(new DisposableStore());

	constructor(
		container: HTMLElement,
		onClose: () => void,
		/** A case or combination was picked here: the toolbar shows its result too. */
		private readonly onPick: (label: string) => void,
		@ICommandService private readonly commandService: ICommandService,
		@IContextViewService contextViewService: IContextViewService,
	) {
		super();
		this.element = append(container, $('.fem-tables'));
		const header = append(this.element, $('.fem-tables-header'));
		this.casePicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femTables.caseAria', "Analysis case of the table") }));
		this.casePicker.render(append(header, $('.fem-tables-select.case')));
		this._register(this.casePicker.onDidSelect(({ index }) => {
			this.caseIndex = index;
			this.tableIndex = 0;
			this.sort = undefined;
			this.render();
			const picked = this.allCases[index];
			if (picked && picked !== this.summary) {
				this.onPick(picked.caseName);
			}
		}));
		this.tablePicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femTables.tableAria', "Result table shown") }));
		this.tablePicker.render(append(header, $('.fem-tables-select.table')));
		this._register(this.tablePicker.onDidSelect(({ index }) => {
			this.tableIndex = index;
			this.sort = undefined;
			this.render();
		}));
		this.filterBox = this._register(new InputBox(append(header, $('.fem-tables-filter')), contextViewService, {
			placeholder: localize('femTables.filter', "Filter rows, e.g. C3 1.4D"),
			ariaLabel: localize('femTables.filterAria', "Show only the rows containing every word typed"),
			inputBoxStyles: defaultInputBoxStyles,
		}));
		this._register(this.filterBox.onDidChange(value => {
			this.filter = value;
			this.renderBody();
			this.layout();
		}));
		this.count = append(header, $('span.fem-tables-count'));
		this.caption = append(header, $('span.fem-tables-count.fem-tables-caption'));
		append(header, $('.fem-tables-spacer'));
		const close = append(header, $<HTMLButtonElement>('button.sa-frame-icon-button', { type: 'button', title: localize('femTables.close', "Hide Tables"), 'aria-label': localize('femTables.close', "Hide Tables") }));
		append(close, $(ThemeIcon.asCSSSelector(Codicon.close)));
		this._register(addDisposableListener(close, EventType.CLICK, () => onClose()));
		this.body = $('.fem-tables-body', { tabIndex: 0 });
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Auto, vertical: ScrollbarVisibility.Auto, useShadows: false }));
		append(this.element, this.scrollable.getDomNode());
	}

	/** The cases, then the summary when it has been read. */
	private get allCases(): readonly IFemCaseResults[] {
		return this.summary ? [...this.cases, this.summary] : this.cases;
	}

	/** The panel's size or content changed: the scrollbars follow. */
	layout(): void {
		this.scrollable.scanDomNode();
	}

	/**
	 * Shows the tables of the result the toolbar shows (cases and load combinations have tables
	 * under the same name). A result without tables keeps the panel where it is and says so.
	 */
	follow(resultLabel: string | undefined): void {
		this.followed = resultLabel;
		if (this.applyFollowed()) {
			this.render();
		} else {
			this.renderCaption();
		}
	}

	/** Moves to the followed result's tables; true when it moved. */
	private applyFollowed(): boolean {
		const index = this.followed === undefined ? -1 : this.cases.findIndex(c => c.caseName === this.followed);
		if (index < 0 || index === this.caseIndex) {
			return false;
		}
		this.caseIndex = index;
		this.tableIndex = 0;
		this.sort = undefined;
		return true;
	}

	private renderCaption(): void {
		const missing = this.followed !== undefined && this.cases.length > 0 && !this.cases.some(c => c.caseName === this.followed);
		this.caption.textContent = missing ? localize('femTables.noTablesFor', "{0} has no result tables.", this.followed) : '';
		this.caption.classList.toggle('hidden', !missing);
	}

	/** Shows only a note (while a run replaces the results): the tables are read again after it. */
	showNote(text: string): void {
		this.request++; // drops a read still going
		this.element.classList.add('waiting');
		this.cases = [];
		this.summary = undefined;
		this.casePicker.setOptions([]);
		this.tablePicker.setOptions([]);
		this.count.textContent = '';
		this.renderCaption();
		clearNode(this.body);
		append(this.body, $('.fem-tables-note', undefined, text));
		this.layout();
	}

	/** Reads the tables of `model`'s last run again, then its summary tables. */
	async load(model: URI, units: string | undefined): Promise<void> {
		const request = ++this.request;
		clearNode(this.body);
		this.count.textContent = '';
		append(this.body, $('.fem-tables-note', undefined, localize('femTables.loading', "Reading the result tables...")));
		this.layout();
		let cases: readonly IFemCaseResults[];
		try {
			cases = await this.commandService.executeCommand<readonly IFemCaseResults[]>(FEM_RESULT_TABLES_COMMAND, model) ?? [];
		} catch (error) {
			if (request === this.request) {
				clearNode(this.body);
				append(this.body, $('.fem-tables-note', undefined, localize('femTables.failed', "The result tables could not be read: {0}", errorSummary(error))));
				this.layout();
			}
			return;
		}
		if (request !== this.request) {
			return;
		}
		this.cases = cases;
		this.summary = undefined;
		this.caseIndex = Math.min(this.caseIndex, Math.max(0, cases.length - 1));
		this.tableIndex = Math.min(this.tableIndex, Math.max(0, (cases[this.caseIndex]?.tables.length ?? 1) - 1));
		this.applyFollowed();
		this.render();
		const summary = await summaryTables(this.commandService, model, units).catch(() => undefined);
		if (request === this.request && summary) {
			this.summary = summary;
			this.render(false);
		}
	}

	/** The summary tables of the last read, for the export. */
	get summarySheets(): readonly IFemResultTable[] {
		return this.summary?.tables ?? [];
	}

	private render(scrollTop = true): void {
		this.element.classList.remove('waiting');
		this.renderBody();
		this.layout();
		if (scrollTop) {
			this.scrollable.setScrollPosition({ scrollTop: 0, scrollLeft: 0 });
		}
	}

	/** Draws the table; returns its heading buttons (sort by a column). */
	private renderBody(): HTMLButtonElement[] {
		this.tableStore.clear();
		clearNode(this.body);
		this.renderCaption();
		const all = this.allCases;
		const results = all[this.caseIndex];
		this.casePicker.setOptions(all.map<ISelectOptionItem>(c => ({ text: c.caseName })), this.caseIndex);
		this.tablePicker.setOptions((results?.tables ?? []).map<ISelectOptionItem>(t => ({ text: t.title })), this.tableIndex);
		const table = results?.tables[this.tableIndex];
		if (!table) {
			this.count.textContent = '';
			append(this.body, $('.fem-tables-note', undefined, localize('femTables.none', "There are no result tables: run the analysis first.")));
			return [];
		}
		const sort = this.sort;
		const sorted = sort ? sortRows(table.rows, sort.column, sort.descending) : [...table.rows];
		const rows = filterRows(sorted, this.filter, formatCell);
		this.count.textContent = rows.length > MAX_TABLE_ROWS
			? localize('femTables.countLimited', "first {0} of {1} rows", MAX_TABLE_ROWS, rows.length)
			: rows.length === table.rows.length
				? localize('femTables.count', "{0} rows", table.rows.length)
				: localize('femTables.countFiltered', "{0} of {1} rows", rows.length, table.rows.length);
		for (const note of [...results.warnings, ...table.notes]) {
			append(this.body, $('.fem-tables-note', undefined, note));
		}
		const element = append(this.body, $('table.fem-table'));
		const head = append(append(element, $('thead')), $('tr'));
		const buttons: HTMLButtonElement[] = [];
		table.columns.forEach((column, index) => {
			const sorting = sort?.column === index;
			const th = append(head, $('th', { 'aria-sort': sorting ? (sort.descending ? 'descending' : 'ascending') : 'none' }));
			const button = append(th, $<HTMLButtonElement>('button.fem-table-sort', {
				type: 'button',
				title: localize('femTables.sortBy', "Sort by {0}", column),
			}));
			buttons.push(button);
			append(button, $('span', undefined, column));
			if (sorting) {
				append(button, $(ThemeIcon.asCSSSelector(sort.descending ? Codicon.arrowDown : Codicon.arrowUp)));
			}
			this.tableStore.add(addDisposableListener(button, EventType.CLICK, () => {
				this.sort = sorting && !sort.descending ? { column: index, descending: true } : sorting ? undefined : { column: index, descending: false };
				const focus = this.renderBody();
				this.layout();
				focus[index]?.focus(); // keyboard users keep their place
			}));
		});
		renderSheetRows(append(element, $('tbody')), rows.slice(0, MAX_TABLE_ROWS));
		return buttons;
	}
}

/**
 * The summary of a run as tables (a pseudo case after the cases): the storey response of every
 * case and combination, their base reactions, and the modal periods and mass participation.
 */
async function summaryTables(commandService: ICommandService, model: URI, units: string | undefined): Promise<IFemCaseResults | undefined> {
	const response = await commandService.executeCommand<IFemStoryResponse>(FEM_STORY_RESPONSE_COMMAND, model);
	if (!response) {
		return undefined;
	}
	const u = chartUnits(units);
	const sheets: IFemSheet[] = [
		storeyTable(response, { length: v => v * u.length.scale, force: v => v * u.force.scale, moment: v => v * u.moment.scale }),
		baseReactionTable(response, { force: v => v * u.force.scale, moment: v => v * u.moment.scale }),
		...(response.modal ? [modalTable(response.modal)] : []),
	];
	return {
		caseId: -1,
		caseName: localize('femTables.summary', "Summary: Storeys, Base Reactions, Modes"),
		resultType: 'summary',
		earlyStop: false,
		warnings: [],
		tables: sheets.map(s => ({ name: s.name, title: s.name, columns: s.columns, rows: s.rows, notes: s.notes ?? [] })),
	};
}

/**
 * The analysis model (`08 FEM/model.osmodel`) in 3D, in the shared editor frame: one toolbar
 * (result and what to show of it, the inline controls a result needs, Derive when the model is
 * out of date, Run, Design Utilisation, Tables, Properties, and an overflow for the rest), the
 * view with its legend, the result tables under it on request, the selection's values in the
 * properties panel, and one status line.
 */
export class FemModelEditor extends EditorPane {

	private frame: EditorFrame | undefined;
	private titleText: HTMLElement | undefined;
	private viewport: HTMLElement | undefined;
	private legend: HTMLElement | undefined;
	private empty: HTMLElement | undefined;
	private message: HTMLElement | undefined;
	private tables: FemTablesPanel | undefined;
	private tablesVisible = false;
	private tablesVersion = -1;
	private viewer: FemViewer | undefined;
	private derivation: FemDerivation | undefined;
	private results: FemResultsBar | undefined;
	/** The result drawn over the model, kept for a viewer created later. */
	private shownResult: { readonly view: IFemResultView; readonly display: FemResultDisplay } | undefined;
	private nodeCount = 0;
	/** The open input's model has been read (until then the status says it is being read). */
	private modelRead = false;
	private elementCount = 0;
	private units: string | undefined;
	private lastDerivation: IFemDeriveOutcome | undefined;
	private actionsKey = '';
	/** What the "Out of date" pill says, to build it again only when that changes. */
	private pillKey: string | undefined;

	private readonly deriveAction = this._register(new Action('saengine.fem.editor.derive', localize('femEditor.derive', "Derive from Building Model"), ThemeIcon.asClassName(Codicon.refresh), true, () => this.derive()));
	private readonly deriveAgainAction = this._register(new Action('saengine.fem.editor.deriveAgain', localize('femEditor.deriveAgain', "Derive Again"), undefined, true, () => this.derive()));
	private readonly runAction = this._register(new Action('saengine.fem.editor.run', localize('femEditor.run', "Run Analysis"), ThemeIcon.asClassName(Codicon.play), true, () => this.running ? this.running.cancel() : this.run({})));
	private readonly runSelectedAction = this._register(new Action('saengine.fem.editor.runSelected', localize('femEditor.runSelected', "Run Selected Cases..."), undefined, true, () => this.run({ pick: true })));
	private readonly designAction = this._register(new Action('saengine.fem.editor.design', localize('femEditor.design', "Design Utilisation"), ThemeIcon.asClassName(Codicon.checklist), true, async () => this.results?.toggleDesign()));
	private readonly reinforceAction = this._register(new Action('saengine.fem.editor.designReinforcement', localize('femEditor.designReinforcement', "Design Reinforcement"), ThemeIcon.asClassName(Codicon.symbolRuler), true, async () => {
		const resource = this.resource;
		if (resource) {
			await this.commandService.executeCommand(DESIGN_REINFORCEMENT_COMMAND, resource);
		}
	}));
	private readonly chartsAction = this._register(new Action('saengine.fem.editor.charts', localize('femEditor.charts', "Analysis Charts"), ThemeIcon.asClassName(Codicon.graph), true, async () => {
		const resource = this.resource;
		if (resource) {
			await this.commandService.executeCommand(FEM_SHOW_CHARTS_COMMAND, resource);
		}
	}));
	private readonly tablesAction = this._register(new Action('saengine.fem.editor.tables', localize('femEditor.tables', "Result Tables"), ThemeIcon.asClassName(Codicon.table), true, async () => this.setTablesVisible(!this.tablesVisible)));
	private readonly exportAction = this._register(new Action('saengine.fem.editor.export', localize('femEditor.export', "Export Result Tables..."), undefined, true, () => this.exportTables()));
	private readonly showLogAction = this._register(new Action('saengine.fem.editor.showLog', localize('femEditor.showLog', "Show Log"), undefined, true, () => this.commandService.executeCommand(FEM_SHOW_LOG_COMMAND)));
	private readonly fitAction = this._register(new Action('saengine.fem.editor.fit', localize('femEditor.fit', "Zoom to Fit"), undefined, true, async () => this.viewer?.fit()));

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly viewerDisposable = this._register(new MutableDisposable());
	private readonly pill = this._register(new MutableDisposable());
	private readonly emptyStore = this._register(new MutableDisposable());
	private readonly propertiesStore = this._register(new MutableDisposable());
	/** The model shown and the node or element picked in it (for the member details). */
	private femModel: FemModel | undefined;
	private selection: FemSelection | undefined;
	/** The View picker: the whole model, a plan, an elevation or a storey. */
	private viewPicker: SelectBox | undefined;
	private views: { readonly choice: FemViewChoice; readonly label: string }[] = [];
	private view: FemViewChoice = { kind: 'all' };

	private readonly _onDidChangeSelection = this._register(new Emitter<FemSelection | undefined>());
	readonly onDidChangeSelection: Event<FemSelection | undefined> = this._onDidChangeSelection.event;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IFileService private readonly fileService: IFileService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@INotificationService private readonly notificationService: INotificationService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IFemRunTracker private readonly runTracker: IFemRunTracker,
		@IContextViewService private readonly contextViewService: IContextViewService,
	) {
		super(FemModelEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
	}

	/** The run of this model going, wherever it was started (here, the palette, Run All). */
	private get running(): IFemRun | undefined {
		const resource = this.resource;
		return resource ? this.runTracker.get(resource) : undefined;
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: FemModelEditorInput.EDITOR_ID,
			ariaLabel: localize('femEditor.toolbar', "Analysis Model"),
			properties: { title: localize('femEditor.properties', "Properties") },
		}));
		frame.element.classList.add('saengine-fem-model-editor');
		this.titleText = append(frame.titleSlot, $('span.sa-frame-title-text', undefined, localize('femEditor.title', "Analysis Model")));

		const view = append(frame.main, $('.fem-view'));
		this.viewport = append(view, $('.viewport', { tabIndex: 0 }));
		this.legend = append(view, $('.fem-legend'));
		this.empty = append(view, $('.fem-empty'));
		this.message = append(view, $('.message'));
		this.tables = this._register(this.instantiationService.createInstance(FemTablesPanel, frame.main, () => this.setTablesVisible(false), label => this.results?.selectResult(label)));
		this.tables.element.classList.add('hidden');

		this.derivation = this._register(this.instantiationService.createInstance(FemDerivation, () => this.updateChrome()));
		this.results = this._register(this.instantiationService.createInstance(FemResultsBar, frame, this.legend, {
			setDisplay: (view: IFemResultView | undefined, display: FemResultDisplay | undefined) => {
				this.shownResult = view && display ? { view, display } : undefined;
				this.viewer?.setResults(view, display);
			},
			changed: () => this.updateChrome(),
			run: () => void this.run({}),
		}));
		// What part of the model to look at, as ETABS's plan and elevation views.
		const viewGroup = append(frame.titleSlot, $('.fem-results-group.view'));
		const viewPicker = this.viewPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femEditor.viewAria', "Part of the model shown: the whole model, a plan, an elevation or one storey") }));
		viewPicker.render(append(viewGroup, $('.fem-results-select.view')));
		this._register(viewPicker.onDidSelect(({ index }) => this.setView(this.views[index]?.choice ?? { kind: 'all' })));
		this._register(this.onDidChangeSelection(selection => {
			this.selection = selection;
			this.results?.setSelection(selection);
		}));
		this._register(frame.onDidLayoutMain(() => {
			this.viewer?.layout();
			this.tables?.layout();
		}));
		this._register(this.runTracker.onDidChange(model => {
			if (this.resource?.toString() === model.toString()) {
				this.updateChrome();
			}
		}));
		this.updateChrome();
	}

	override async setInput(input: FemModelEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.lastDerivation = undefined;
		this.modelRead = false;
		this.updateChrome(); // a run of this model may already be going
		void this.derivation?.setResource(input.resource);

		const viewer = await this.ensureViewer();
		if (token.isCancellationRequested || !viewer) {
			return;
		}

		const watcher = this.fileService.createWatcher(input.resource, { recursive: false, excludes: [] });
		this.inputDisposables.add(watcher);
		this.inputDisposables.add(watcher.onDidChange(e => {
			if (e.contains(input.resource)) {
				void this.loadModel(input, CancellationToken.None);
			}
		}));

		await this.loadModel(input, token);
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		// Hidden (another tab of the group shown), not closed: keep the results read so far.
		this.results?.suspend();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame?.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.viewport?.focus();
	}

	override updateStyles(): void {
		super.updateStyles();
		this.viewer?.setTheme(this.computeTheme());
	}

	private get resource(): URI | undefined {
		return (this.input as FemModelEditorInput | undefined)?.resource;
	}

	// ───────────────────────────── actions ─────────────────────────────

	private async derive(): Promise<void> {
		const outcome = await this.derivation?.derive();
		if (!outcome) {
			return;
		}
		this.lastDerivation = outcome;
		if (!outcome.ok) {
			this.notificationService.error(localize('femEditor.deriveFailed', "The analysis model could not be derived: {0}", outcome.message));
		}
		// The facts and the notes are in the properties panel: no toast.
		this.updateChrome();
	}

	/**
	 * Runs the analysis (all cases, or those picked). Its progress shows in the toolbar and the
	 * status line through the run tracker, as does a run of this model started elsewhere; the
	 * runner refuses a second run of the same model.
	 */
	private async run(options: Pick<IFemRunOptions, 'pick'>): Promise<void> {
		const resource = this.resource;
		if (!resource || this.running) {
			return;
		}
		try {
			// onProgress: this editor shows the progress (from the tracker), not the status bar.
			const runOptions: IFemRunOptions = { pick: options.pick, onProgress: () => { } };
			await this.commandService.executeCommand<IFemRunOutcome>(FEM_RUN_CASES_COMMAND, resource, runOptions);
		} catch (error) {
			this.notificationService.error(localize('femEditor.runFailed', "The analysis could not be run: {0}", errorSummary(error)));
		}
	}

	private setTablesVisible(visible: boolean): void {
		this.tablesVisible = visible;
		this.tables?.element.classList.toggle('hidden', !visible);
		this.tablesVersion = -1; // read them again when shown
		this.updateChrome();
		this.viewer?.layout();
	}

	/**
	 * Exports every case's and combination's tables, with the summary (storeys, base reactions,
	 * modes): to an Excel workbook, one sheet per kind of table with the result in its first
	 * column, or to one CSV file.
	 */
	private async exportTables(): Promise<void> {
		const resource = this.resource;
		if (!resource) {
			return;
		}
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('femEditor.exportTitle', "Export Result Tables"),
			defaultUri: joinPath(dirname(resource), 'results.xlsx'),
			filters: [
				{ name: localize('femEditor.xlsxFiles', "Excel Workbooks"), extensions: ['xlsx'] },
				{ name: localize('femEditor.csvFiles', "CSV Files"), extensions: ['csv'] },
			],
		});
		if (!target) {
			return;
		}
		try {
			const cases = await this.commandService.executeCommand<readonly IFemCaseResults[]>(FEM_RESULT_TABLES_COMMAND, resource) ?? [];
			if (/\.xlsx$/i.test(target.path)) {
				const summary: IFemSheet[] = (this.tables?.summarySheets ?? []).map(s => ({ name: s.title, columns: s.columns, rows: s.rows, notes: s.notes }));
				await this.commandService.executeCommand(FEM_EXPORT_XLSX_COMMAND, target, workbookSheets(cases, summary));
			} else {
				await this.fileService.writeFile(target, VSBuffer.fromString(resultTablesCsv(cases)));
			}
		} catch (error) {
			this.notificationService.error(localize('femEditor.exportFailed', "The result tables could not be exported: {0}", errorSummary(error)));
		}
	}


	// ───────────────────────────── chrome ─────────────────────────────

	/** Brings the toolbar, the status line, the properties panel and the overlays up to date. */
	private updateChrome(): void {
		const frame = this.frame;
		const results = this.results;
		const derivation = this.derivation;
		if (!frame || !results || !derivation) {
			return;
		}
		const state = derivation.state;
		const stale = !!state && (!state.derived || state.changed.length > 0);
		const hasResults = results.hasResults;

		// Toolbar
		this.titleText?.classList.toggle('hidden', hasResults);
		this.deriveAction.enabled = this.deriveAgainAction.enabled = !derivation.deriving && !this.running;
		this.deriveAction.label = state?.derived ? localize('femEditor.deriveAgainLong', "Derive Again from Building Model") : localize('femEditor.derive', "Derive from Building Model");
		this.runAction.label = this.running ? localize('femEditor.stop', "Stop Analysis") : localize('femEditor.run', "Run Analysis");
		this.runAction.class = ThemeIcon.asClassName(this.running ? Codicon.debugStop : Codicon.play);
		this.runAction.enabled = this.nodeCount > 0 && !derivation.deriving;
		this.runSelectedAction.enabled = this.nodeCount > 0 && !this.running && !derivation.deriving;
		this.designAction.enabled = hasResults && results.canShowDesign;
		this.designAction.checked = results.showsDesign;
		this.reinforceAction.enabled = hasResults && results.canShowDesign && !this.running;
		this.tablesAction.enabled = hasResults;
		this.chartsAction.enabled = hasResults;
		this.tablesAction.checked = this.tablesVisible;
		this.exportAction.enabled = hasResults;
		const primary: IAction[] = [...(stale ? [this.deriveAction] : []), this.runAction, this.chartsAction, this.designAction, this.reinforceAction, this.tablesAction, frame.togglePropertiesAction];
		const secondary: IAction[] = [
			this.runSelectedAction,
			...(state && !stale ? [this.deriveAgainAction] : []),
			new Separator(),
			this.exportAction,
			this.showLogAction,
			new Separator(),
			this.fitAction,
		];
		const key = `${primary.map(a => a.id).join()}|${secondary.map(a => a.id).join()}`;
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			frame.setActions(primary, secondary);
		}

		// The "Out of date" pill: what changed since the model was derived. Built again only when
		// that changes, so its hover stays open through progress updates.
		const changed = state?.derived && state.changed.length ? state.changed.join(', ') : undefined;
		if (changed !== this.pillKey) {
			this.pillKey = changed;
			this.pill.value = changed === undefined ? undefined : frame.createPill(localize('femEditor.outOfDate', "Out of date"), {
				severity: 'warn',
				icon: Codicon.warning,
				title: localize('femEditor.outOfDateTitle', "Changed since the analysis model was derived: {0}. Click to derive it again.", changed),
				run: () => void this.derive(),
			});
		}

		// Progress
		const running = this.running;
		if (running) {
			frame.showProgress(running.progress?.fraction);
		} else if (derivation.deriving) {
			frame.showProgress();
		} else {
			frame.hideProgress();
		}

		frame.setStatus(this.status(stale));
		this.renderEmpty(stale);
		this.renderProperties();

		// The tables follow the results while shown.
		const resource = this.resource;
		this.tables?.follow(results.resultLabel);
		if (this.tablesVisible && running) {
			// The run replaces the results: no old tables meanwhile.
			if (this.tablesVersion !== -2) {
				this.tablesVersion = -2;
				this.tables?.showNote(localize('femTables.running', "The result tables are shown when the analysis has finished."));
			}
		} else if (this.tablesVisible && resource && hasResults && results.version !== this.tablesVersion) {
			this.tablesVersion = results.version;
			void this.tables?.load(resource, this.units);
		}
	}

	private status(stale: boolean): IEditorFrameStatus | undefined {
		const derivation = this.derivation;
		const running = this.running;
		if (running) {
			const progress = running.progress;
			return {
				busy: true,
				text: progress ? localize('femEditor.running', "Running the analysis: {0}", progress.message) : localize('femEditor.runningStart', "Preparing the analysis..."),
				link: { label: localize('femEditor.stopLink', "Stop"), run: () => running.cancel() },
			};
		}
		if (derivation?.deriving) {
			return { busy: true, text: localize('femEditor.deriving', "Deriving the analysis model from the building model...") };
		}
		if (!this.modelRead) {
			// Not "not derived" or "not analysed" before the model and its results are read.
			return { busy: true, text: localize('femEditor.reading', "Reading the analysis model...") };
		}
		const results = this.results?.status();
		if (results) {
			return results;
		}
		const state = derivation?.state;
		if (state && !state.derived) {
			return {
				text: localize('femEditor.notDerived', "The analysis model has not been derived from the building model yet."),
				link: { label: localize('femEditor.derive', "Derive from Building Model"), run: () => void this.derive() },
			};
		}
		if (this.nodeCount) {
			return {
				text: stale
					? localize('femEditor.notAnalysedStale', "{0} nodes, {1} elements. Not analysed yet; the model is out of date.", this.nodeCount, this.elementCount)
					: localize('femEditor.notAnalysed', "{0} nodes, {1} elements. Not analysed yet.", this.nodeCount, this.elementCount),
				link: { label: localize('femEditor.run', "Run Analysis"), run: () => void this.run({}) },
			};
		}
		return undefined;
	}

	/** The empty view of a model not derived yet: what to do first. */
	private renderEmpty(stale: boolean): void {
		const empty = this.empty;
		const state = this.derivation?.state;
		if (!empty) {
			return;
		}
		this.emptyStore.clear();
		clearNode(empty);
		const show = this.nodeCount === 0 && !!this.input && !this.message?.classList.contains('visible');
		empty.classList.toggle('visible', show);
		if (!show) {
			return;
		}
		append(empty, $('.fem-empty-title', undefined, state && !state.derived
			? localize('femEditor.emptyTitle', "No analysis model yet")
			: localize('femEditor.emptyNoNodes', "This model has no nodes")));
		append(empty, $('.fem-empty-text', undefined, state
			? localize('femEditor.emptyText', "The analysis model is derived from the building model, the object types, the materials and the project settings.")
			: localize('femEditor.emptyTextOther', "Open the project's analysis model, or add nodes and elements to this file.")));
		if (state && (stale || !state.derived)) {
			const store = new DisposableStore();
			const button = store.add(new Button(empty, { ...defaultButtonStyles, supportIcons: true }));
			button.label = `$(${Codicon.refresh.id}) ${localize('femEditor.derive', "Derive from Building Model")}`;
			button.enabled = !this.derivation?.deriving;
			store.add(button.onDidClick(() => this.derive()));
			this.emptyStore.value = store;
		}
	}

	/** The properties panel: the result's values for the selection, then the model's facts. */
	private renderProperties(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		clearNode(panel);
		this.propertiesStore.clear();
		this.results?.renderProperties(panel);
		this.renderMemberLink(panel);
		appendPropertyHeading(panel, localize('femEditor.modelHeading', "Model"));
		appendPropertyRow(panel, localize('femEditor.nodes', "Nodes"), String(this.nodeCount));
		appendPropertyRow(panel, localize('femEditor.elements', "Elements"), String(this.elementCount));
		if (this.units) {
			appendPropertyRow(panel, localize('femEditor.units', "Units"), this.units);
		}
		const state = this.derivation?.state;
		if (state) {
			appendPropertyRow(panel, localize('femEditor.derivation', "Derived"), !state.derived
				? localize('femEditor.derivationNo', "Not yet")
				: state.changed.length ? localize('femEditor.derivationStale', "Out of date") : localize('femEditor.derivationCurrent', "Up to date"));
			if (state.derived && state.changed.length) {
				appendPropertyNote(panel, localize('femEditor.changedSources', "Changed since: {0}.", state.changed.join(', ')));
			}
		}
		const last = this.lastDerivation;
		if (last?.ok && !this.results?.hasResults) {
			appendPropertyNote(panel, last.message);
		}
		if (last?.ok && last.notes.length) {
			appendPropertyHeading(panel, localize('femEditor.notesHeading', "Derivation Notes"));
			for (const note of last.notes) {
				appendPropertyNote(panel, note);
			}
		}
	}

	/**
	 * A frame member picked in the view, with results: a button to its details (forces and
	 * deflection along it, a column's interaction diagram, a beam's steel).
	 */
	private renderMemberLink(panel: HTMLElement): void {
		const selection = this.selection;
		const resource = this.resource;
		if (!resource || selection?.kind !== 'element' || !this.results?.hasResults) {
			return;
		}
		const element = this.femModel?.elements.find(e => e.id === selection.id);
		if (!element || element.nodes.length !== 2 || !element.name) {
			return;
		}
		const member = memberOf(element.name);
		const store = new DisposableStore();
		const button = store.add(new Button(append(panel, $('.fem-member-link')), { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('femEditor.memberTitle', "Forces and deflection along {0}, its interaction diagram or steel", member) }));
		button.label = `$(${Codicon.graph.id}) ${localize('femEditor.memberDetails', "Member Details: {0}", member)}`;
		store.add(button.onDidClick(() => this.commandService.executeCommand(FEM_SHOW_MEMBER_COMMAND, resource, member)));
		this.propertiesStore.value = store;
	}

	// ───────────────────────────── viewer ─────────────────────────────

	private async ensureViewer(): Promise<FemViewer | undefined> {
		if (this.viewer) {
			return this.viewer;
		}
		try {
			const { createFemViewer } = await loadViewerModule();
			if (this.viewer || !this.viewport) {
				return this.viewer;
			}
			const viewer = createFemViewer(this.viewport, {
				theme: this.computeTheme(),
				onSelectionChanged: selection => this._onDidChangeSelection.fire(selection),
			});
			this.viewer = viewer;
			if (this.shownResult) {
				viewer.setResults(this.shownResult.view, this.shownResult.display);
			}
			if (this.view.kind !== 'all' && this.femModel) {
				viewer.setVisibleElements(visibleElements(this.femModel as unknown as IFilterModel, this.view));
				void viewer.setCameraView(cameraOf(this.view));
			}
			this.viewerDisposable.value = toDisposable(() => {
				viewer.dispose();
				this.viewer = undefined;
			});
			return viewer;
		} catch (error) {
			this.showMessage(localize('femModelEditor.viewerFailed', "The FEM viewport could not be loaded: {0}", String(error)));
			return undefined;
		}
	}

	private async loadModel(input: FemModelEditorInput, token: CancellationToken): Promise<void> {
		let model: FemModel;
		try {
			const content = await this.fileService.readFile(input.resource, undefined, token);
			const parsed = JSON.parse(content.value.toString());
			// opensees-studio fills omitted lists with defaults, so a new project's model may have none yet.
			model = { ...parsed, ndm: parsed.ndm ?? 3, nodes: parsed.nodes ?? [], elements: parsed.elements ?? [] };
		} catch (error) {
			this.modelRead = true;
			if (!token.isCancellationRequested) {
				this.showMessage(localize('femModelEditor.readFailed', "Unable to read the model: {0}", String(error)));
			}
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
		this.modelRead = true;
		if (!Array.isArray(model.nodes) || !Array.isArray(model.elements)) {
			this.showMessage(localize('femModelEditor.invalid', "This file is not an OpenSees Studio model (missing nodes or elements)."));
			return;
		}
		this.showMessage(undefined);
		const meta = (model as { meta?: { description?: unknown; units?: unknown } }).meta;
		this.units = typeof meta?.units === 'string' ? meta.units : undefined;
		const wasEmpty = this.nodeCount === 0;
		this.nodeCount = model.nodes.length;
		this.femModel = model;
		this.elementCount = model.elements.length;
		this.derivation?.setDescription(meta?.description);
		this.results?.setResource(input.resource, this.units);
		this.results?.setModel(model);
		this.viewer?.setModel(model);
		this.updateViews(model as unknown as IFilterModel);
		if (wasEmpty && this.nodeCount) {
			// A model derived into an empty file: frame it (the first fit framed nothing).
			void this.viewer?.fit();
		}
		this.updateChrome();
	}

	/** The View picker's choices for `model`, keeping the view shown when the model still has it. */
	private updateViews(model: IFilterModel): void {
		this.views = viewChoices(model);
		const key = JSON.stringify(this.view);
		const index = Math.max(0, this.views.findIndex(v => JSON.stringify(v.choice) === key));
		this.viewPicker?.setOptions(this.views.map<ISelectOptionItem>(v => ({ text: v.label })), index);
		this.applyView(this.views[index]?.choice ?? { kind: 'all' }, false);
	}

	private setView(choice: FemViewChoice): void {
		this.applyView(choice, true);
	}

	/** Draws the part of the model `choice` shows; `frame`: look at it from its own camera. */
	private applyView(choice: FemViewChoice, frame: boolean): void {
		const changed = JSON.stringify(choice) !== JSON.stringify(this.view);
		this.view = choice;
		const model = this.femModel as unknown as IFilterModel | undefined;
		if (!this.viewer || !model) {
			return;
		}
		this.viewer.setVisibleElements(visibleElements(model, choice));
		if (frame || changed) {
			void this.viewer.setCameraView(cameraOf(choice));
		}
	}

	private showMessage(text: string | undefined): void {
		if (!this.message) {
			return;
		}
		clearNode(this.message);
		this.message.classList.toggle('visible', !!text);
		if (text) {
			this.message.textContent = text;
		}
		this.updateChrome();
	}

	private computeTheme(): Partial<FemViewerTheme> {
		const theme = this.themeService.getColorTheme();
		const color = (id: string) => theme.getColor(id)?.toString();
		return {
			background: color(editorBackground),
			member: color(chartsBlue),
			node: color(editorForeground),
			support: color(chartsGreen),
			selection: color(chartsYellow),
			grid: color(chartsLines),
			deformed: color(chartsOrange),
			positive: color(chartsBlue),
			negative: color(chartsRed),
			reaction: color(chartsGreen),
			pass: color(chartsGreen),
			warn: color(chartsOrange),
			fail: color(chartsRed),
		};
	}
}
