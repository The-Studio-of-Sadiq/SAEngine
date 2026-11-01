/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femModelEditor.css';
import type { FemMeasureMode, FemMeasurement, FemModel, FemResultDisplay, FemSelection, FemViewer, FemViewerTheme } from '@saengine/fem-viewer';
import { $, addDisposableListener, append, Dimension, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken, CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
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
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { csvText } from '../../../../platform/saengine/common/csv.js';
import { FemTableCell, IFemCaseResults, IFemResultTable, IFemResultView } from '../../../../platform/saengine/common/femSolver.js';
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
import { FemDerivation, IFemDeriveOutcome, IFemWindSummary } from './femDerivationBar.js';
import { DESIGN_REINFORCEMENT_COMMAND, designKindLabel, IFemDesignReport, sortedChecks } from './femDesign.js';
import { FemModelEditorInput } from './femModelEditorInput.js';
import { appendPlannedChips, FemPlanned } from './femPlannedFeatures.js';
import { errorSummary, FEM_RUN_CASES_COMMAND, FEM_SHOW_CHARTS_COMMAND, FEM_SHOW_LOG_COMMAND, FEM_SHOW_MEMBER_COMMAND, FemResultsBar, IFemRun, IFemRunOptions, IFemRunOutcome, IFemRunTracker } from './femResultsBar.js';
import { baseReactionTable, displayTable, exportCell, FEM_STORY_RESPONSE_COMMAND, filterRows, formatCell, IFemSheet, IFemStoryResponse, modalTable, sortRows, storeyTable, supportReactions } from './femChartData.js';
import { renderSheetRows } from './femChart.js';
import { jointGoverning, jointGoverningName, jointHeading, jointOk, jointsOf } from './femSeismicDetailing.js';
import { chartUnits } from './femResultsView.js';
import { cameraOf, FemViewChoice, formatPlanPath, freeTopColumns, gridLines, IFilterModel, parsePlanPath, perimeterPath, viewChoices, visibleElements } from './femViewFilter.js';
import { loadViewerModule } from './viewerModule.js';

/** The building member an analysis element belongs to (`C3#2` -> `C3`). */
export function memberOf(name: string): string {
	return name.split('#')[0];
}

/** Rows of a result table drawn at once; the export has them all. */
const MAX_TABLE_ROWS = 500;

interface IFemModelNodes {
	readonly nodes: readonly { readonly id: number; readonly restraint?: readonly (boolean | number)[] }[];
	readonly mp_constraints?: readonly { readonly retained_node?: number }[];
}

/** The rigid diaphragms' master nodes: restrained out of plane by the solver, not supports. */
function diaphragmMasters(model: IFemModelNodes): Set<number> {
	return new Set((model.mp_constraints ?? []).map(c => c.retained_node).filter((n): n is number => typeof n === 'number'));
}

/** The supports of a model: restrained nodes other than the diaphragms' master nodes. */
export function supportNodes(model: IFemModelNodes): Set<number> {
	const masters = diaphragmMasters(model);
	return new Set(model.nodes.filter(n => n.restraint?.some(Boolean) && !masters.has(n.id)).map(n => n.id));
}

/** The model as the 3D view draws it: the diaphragms' master nodes are not drawn as supports. */
export function displayModel<T extends IFemModelNodes>(model: T): T {
	const masters = diaphragmMasters(model);
	return masters.size ? { ...model, nodes: model.nodes.map(n => masters.has(n.id) ? { ...n, restraint: n.restraint?.map(() => false) } : n) } : model;
}

/**
 * The design checks of a run as a table: every checked member and beam-column joint, the
 * failing first, then by utilisation; the members not checked last, with the reason. A row
 * picks its member in 3D (a joint's row its column, whose properties list its joints).
 */
export function designChecksCase(report: IFemDesignReport): IFemCaseResults {
	const checked: { readonly ok: boolean; readonly utilisation: number; readonly row: FemTableCell[] }[] = report.elements.map(e => {
		const governing = sortedChecks(e)[0];
		return {
			ok: e.ok, utilisation: e.utilisation, row: [
				e.id, designKindLabel(e.kind), e.type, Number(e.utilisation.toFixed(3)),
				e.ok ? localize('femTables.pass', "pass") : localize('femTables.fail', "FAIL"),
				governing?.name ?? '', governing?.combination ?? '',
			],
		};
	});
	const joints = jointsOf(report);
	for (const joint of joints) {
		const governing = jointGoverning(joint);
		const ok = jointOk(joint);
		const utilisation = governing && Number.isFinite(governing.utilisation) ? governing.utilisation : ok ? 0 : Infinity;
		checked.push({
			ok, utilisation, row: [
				joint.column ?? joint.id, jointHeading(joint), '', Number.isFinite(utilisation) ? Number(utilisation.toFixed(3)) : '∞',
				ok ? localize('femTables.pass', "pass") : localize('femTables.fail', "FAIL"),
				jointGoverningName(joint) ?? '', '',
			],
		});
	}
	checked.sort((a, b) => Number(a.ok) - Number(b.ok) || b.utilisation - a.utilisation);
	const rows = checked.map(c => c.row);
	for (const skipped of report.skipped) {
		rows.push([skipped.id, designKindLabel(skipped.kind), skipped.type, '', localize('femTables.notChecked', "not checked"), skipped.reason, '']);
	}
	const membersFailed = report.elements.filter(e => !e.ok).length;
	const jointsFailed = joints.filter(j => !jointOk(j)).length;
	return {
		caseId: -2,
		caseName: joints.length
			? localize('femTables.designChecksJoints', "Design Checks: {0} of {1} members fail, {2} of {3} joints", membersFailed, report.elements.length, jointsFailed, joints.length)
			: localize('femTables.designChecks', "Design Checks: {0} fail of {1}", membersFailed, report.elements.length),
		resultType: 'summary',
		earlyStop: false,
		warnings: [],
		tables: [{
			name: localize('femTables.designTable', "Design checks"),
			title: localize('femTables.designTable', "Design checks"),
			columns: [
				localize('femTables.member', "Member"), localize('femTables.kind', "Kind"), localize('femTables.type', "Object type"),
				localize('femTables.utilisation', "Utilisation"), localize('femTables.result', "Result"),
				localize('femTables.governing', "Governing check"), localize('femTables.combination', "Combination"),
			],
			rows,
			notes: [localize('femTables.designNote', "The checks of Design Utilisation ({0}). Click a row to select the member in the view and see its checks.", report.code)],
		}],
	};
}

/** Reads the index of a run's result tables (fem/result_tables.py): `{results}`. */
export const FEM_TABLE_INDEX_COMMAND = 'saengine.fem.tableIndex';
/** Reads one table of one result: `(model, key, table id)`. */
export const FEM_TABLE_COMMAND = 'saengine.fem.table';
/** Streams the chosen tables to a workbook: `(model, target, {keys?, tables?, extra?, onProgress?}, token)`. */
export const FEM_EXPORT_TABLES_COMMAND = 'saengine.fem.exportTables';

/** Where a result's tables are listed: the run's cases, the combinations, the spectrum design, the envelope, then the design checks and the summary. */
export type FemTableGroup = 'case' | 'combination' | 'spectrum' | 'envelope' | 'design' | 'summary';

/** A result with tables, as the backend's index lists it; its tables are read when shown. */
export interface IFemTableEntry {
	readonly key: string;
	readonly label: string;
	readonly group: FemTableGroup;
	readonly warnings: readonly string[];
	readonly tables: readonly { readonly id: string; readonly title: string }[];
}

export function tableGroupLabel(group: FemTableGroup): string {
	switch (group) {
		case 'case': return localize('femTables.groupCases', "Load cases");
		case 'combination': return localize('femTables.groupCombinations', "Load combinations");
		case 'spectrum': return localize('femTables.groupSpectrum', "Response spectrum design combinations");
		case 'envelope': return localize('femTables.groupEnvelope', "Envelope");
		case 'design': return localize('femTables.groupDesign', "Design");
		case 'summary': return localize('femTables.groupSummary', "Summary");
	}
}

/**
 * The picker's options for `entries`: a heading (disabled) before each group, then its results.
 * `rows[k]` is the entry of option k, or -1 for a heading.
 */
export function groupedOptions(entries: readonly IFemTableEntry[]): { readonly options: ISelectOptionItem[]; readonly rows: number[] } {
	const options: ISelectOptionItem[] = [];
	const rows: number[] = [];
	let group: FemTableGroup | undefined;
	entries.forEach((entry, index) => {
		if (entry.group !== group) {
			group = entry.group;
			options.push({ text: `── ${tableGroupLabel(group)} ──`, isDisabled: true });
			rows.push(-1);
		}
		options.push({ text: entry.label });
		rows.push(index);
	});
	return { options, rows };
}

/** A pseudo result whose tables were worked out here (the design checks, the summary). */
function localEntry(results: IFemCaseResults, key: string, group: FemTableGroup): { entry: IFemTableEntry; tables: readonly IFemResultTable[] } {
	return {
		entry: { key, label: results.caseName, group, warnings: results.warnings, tables: results.tables.map((t, k) => ({ id: String(k), title: t.title })) },
		tables: results.tables,
	};
}

/** A run's tables as the panel and the exports show them: in kN, mm, kN·m; reactions at the supports. */
export function displayCases(cases: readonly IFemCaseResults[], units: string | undefined, supports: ReadonlySet<number>): IFemCaseResults[] {
	return cases.map(c => ({ ...c, tables: c.tables.map(t => supports.size ? supportReactions(displayTable(t, units), supports) : displayTable(t, units)) }));
}

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
	/** The run's results with tables (the backend's index); their tables are read when shown. */
	private entries: readonly IFemTableEntry[] = [];
	/** The tables read so far, by `key|table id` (the design checks' and the summary's too). */
	private readonly loaded = new Map<string, IFemResultTable>();
	/** The tables being read, by `key|table id`. */
	private readonly reading = new Set<string>();
	/** Why a table could not be read, by `key|table id`. */
	private readonly failed = new Map<string, string>();
	/** The summary tables (storey response, base reactions, modes), read after the index. */
	private summary: IFemTableEntry | undefined;
	/** The design checks as a table, once Design Utilisation has run them. */
	private design: IFemTableEntry | undefined;
	private designReport: IFemDesignReport | undefined;
	private model: URI | undefined;
	private units: string | undefined;
	private supports: ReadonlySet<number> = new Set();
	/** The picker's option k shows entry `optionRows[k]` (-1: a group's heading). */
	private optionRows: number[] = [];
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
		onExport: () => void,
		/** A design checks row or a member's row was clicked: select that member (building model id) in the view. */
		private readonly onPickMember: (member: string) => void,
		@ICommandService private readonly commandService: ICommandService,
		@IContextViewService contextViewService: IContextViewService,
	) {
		super();
		this.element = append(container, $('.fem-tables'));
		const header = append(this.element, $('.fem-tables-header'));
		this.casePicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femTables.caseAria', "Analysis case of the table") }));
		this.casePicker.render(append(header, $('.fem-tables-select.case')));
		this._register(this.casePicker.onDidSelect(({ index }) => {
			const row = this.optionRows[index] ?? -1;
			if (row < 0) {
				this.renderBody(); // a heading: the picker shows the result it showed
				return;
			}
			this.caseIndex = row;
			this.tableIndex = 0;
			this.sort = undefined;
			this.render();
			const picked = this.allEntries[row];
			if (picked && (picked.group === 'case' || picked.group === 'combination')) {
				this.onPick(picked.label);
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
		// The tables to Excel: where the engineer looks for it.
		const exportButton = this._register(new Button(header, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('femTables.exportTitle', "Export the tables you choose, of every result or of the one shown, to an Excel workbook, or the table shown to a CSV file") }));
		exportButton.label = `$(${Codicon.export.id}) ${localize('femTables.export', "Export to Excel...")}`;
		exportButton.element.classList.add('fem-tables-export');
		this._register(exportButton.onDidClick(() => onExport()));
		const close = append(header, $<HTMLButtonElement>('button.sa-frame-icon-button', { type: 'button', title: localize('femTables.close', "Hide Tables"), 'aria-label': localize('femTables.close', "Hide Tables") }));
		append(close, $(ThemeIcon.asCSSSelector(Codicon.close)));
		this._register(addDisposableListener(close, EventType.CLICK, () => onClose()));
		this.body = $('.fem-tables-body', { tabIndex: 0 });
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Auto, vertical: ScrollbarVisibility.Auto, useShadows: false }));
		append(this.element, this.scrollable.getDomNode());
	}

	/** The results, then the design checks and the summary when they are there. */
	private get allEntries(): readonly IFemTableEntry[] {
		return [...this.entries, ...(this.design ? [this.design] : []), ...(this.summary ? [this.summary] : [])];
	}

	/** The results of the index (the export's choices). */
	get results(): readonly IFemTableEntry[] {
		return this.entries;
	}

	/** The result and table shown, with the table once it has been read. */
	get shown(): { readonly entry: IFemTableEntry; readonly title: string; readonly table: IFemResultTable | undefined } | undefined {
		const entry = this.allEntries[this.caseIndex];
		const wanted = entry?.tables[this.tableIndex];
		return entry && wanted ? { entry, title: wanted.title, table: this.loaded.get(`${entry.key}|${wanted.id}`) } : undefined;
	}

	/** The run's design checks (or none yet): listed after the results while there are tables. */
	setDesign(report: IFemDesignReport | undefined): void {
		if (report === this.designReport) {
			return;
		}
		const showing = this.allEntries[this.caseIndex];
		this.designReport = report;
		if (report) {
			const { entry, tables } = localEntry(designChecksCase(report), 'design', 'design');
			tables.forEach((t, k) => this.loaded.set(`design|${k}`, t));
			this.design = entry;
		} else {
			this.design = undefined;
		}
		if (this.entries.length) {
			// Stay on the table shown (the design entry comes before the summary).
			const index = showing ? this.allEntries.findIndex(c => c.key === showing.key) : -1;
			this.caseIndex = index >= 0 ? index : Math.min(this.caseIndex, this.allEntries.length - 1);
			this.render(false);
		}
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

	/** Moves to the followed result's tables (the same table: member forces stay member forces); true when it moved. */
	private applyFollowed(): boolean {
		const index = this.followed === undefined ? -1 : this.entries.findIndex(c => c.label === this.followed && c.tables.length > 0);
		if (index < 0 || index === this.caseIndex) {
			return false;
		}
		const table = this.allEntries[this.caseIndex]?.tables[this.tableIndex];
		this.caseIndex = index;
		this.tableIndex = Math.max(0, table ? this.entries[index].tables.findIndex(t => t.id === table.id) : 0);
		this.sort = undefined;
		return true;
	}

	private renderCaption(): void {
		const missing = this.followed !== undefined && this.entries.length > 0 && !this.entries.some(c => c.label === this.followed && c.tables.length > 0);
		this.caption.textContent = missing ? localize('femTables.noTablesFor', "{0} has no result tables.", this.followed) : '';
		this.caption.classList.toggle('hidden', !missing);
	}

	/** Shows only a note (while a run replaces the results): the tables are read again after it. */
	showNote(text: string): void {
		this.request++; // drops a read still going
		this.element.classList.add('waiting');
		this.entries = [];
		this.summary = undefined;
		this.clearTables();
		this.casePicker.setOptions([]);
		this.tablePicker.setOptions([]);
		this.count.textContent = '';
		this.renderCaption();
		clearNode(this.body);
		append(this.body, $('.fem-tables-note', undefined, text));
		this.layout();
	}

	/** Forgets the tables read of the last run (the design checks stay: they come with the report). */
	private clearTables(): void {
		for (const key of [...this.loaded.keys()]) {
			if (!key.startsWith('design|')) {
				this.loaded.delete(key);
			}
		}
		this.reading.clear();
		this.failed.clear();
	}

	/** Reads the index of `model`'s last run again (its tables are read when shown), then its summary tables. */
	async load(model: URI, units: string | undefined, supports: ReadonlySet<number>): Promise<void> {
		const request = ++this.request;
		this.model = model;
		this.units = units;
		this.supports = supports;
		clearNode(this.body);
		this.count.textContent = '';
		append(this.body, $('.fem-tables-note', undefined, localize('femTables.loading', "Reading the result tables...")));
		this.layout();
		let entries: readonly IFemTableEntry[];
		try {
			const index = await this.commandService.executeCommand<{ readonly results: readonly IFemTableEntry[] }>(FEM_TABLE_INDEX_COMMAND, model);
			entries = (index?.results ?? []).filter(r => r.tables.length > 0 || r.warnings.length > 0);
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
		this.entries = entries;
		this.summary = undefined;
		this.clearTables();
		this.caseIndex = Math.min(this.caseIndex, Math.max(0, entries.length - 1));
		this.tableIndex = Math.min(this.tableIndex, Math.max(0, (entries[this.caseIndex]?.tables.length ?? 1) - 1));
		this.applyFollowed();
		this.render();
		const summary = await summaryTables(this.commandService, model, units).catch(() => undefined);
		if (request === this.request && summary) {
			const { entry, tables } = localEntry(summary, 'summary', 'summary');
			tables.forEach((t, k) => this.loaded.set(`summary|${k}`, t));
			this.summary = entry;
			this.render(false);
		}
	}

	/** The summary tables of the last read, for the export. */
	get summarySheets(): readonly IFemResultTable[] {
		return (this.summary?.tables ?? []).map(t => this.loaded.get(`summary|${t.id}`)).filter((t): t is IFemResultTable => !!t);
	}

	/** Reads one table of a result, then draws it if it is still the one shown. */
	private async read(entry: IFemTableEntry, id: string): Promise<void> {
		const key = `${entry.key}|${id}`;
		const model = this.model;
		if (!model || this.reading.has(key)) {
			return;
		}
		const request = this.request;
		this.reading.add(key);
		try {
			const raw = await this.commandService.executeCommand<IFemResultTable>(FEM_TABLE_COMMAND, model, entry.key, id);
			if (request !== this.request || !raw) {
				return;
			}
			// OpenSees Studio's tables come in model units (SAEngine's in kN and mm already).
			const table = displayTable(raw, this.units);
			this.loaded.set(key, this.supports.size ? supportReactions(table, this.supports) : table);
		} catch (error) {
			if (request === this.request) {
				this.failed.set(key, errorSummary(error));
			}
		} finally {
			this.reading.delete(key);
		}
		if (request === this.request && this.shown?.entry === entry) {
			this.render(false);
		}
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
		const all = this.allEntries;
		const results = all[this.caseIndex];
		const grouped = groupedOptions(all);
		this.optionRows = grouped.rows;
		this.casePicker.setOptions(grouped.options, Math.max(0, grouped.rows.indexOf(this.caseIndex)));
		this.tablePicker.setOptions((results?.tables ?? []).map<ISelectOptionItem>(t => ({ text: t.title })), this.tableIndex);
		if (!results) {
			this.count.textContent = '';
			append(this.body, $('.fem-tables-note', undefined, localize('femTables.none', "There are no result tables: run the analysis first.")));
			return [];
		}
		for (const warning of results.warnings) {
			append(this.body, $('.fem-tables-note', undefined, warning));
		}
		const wanted = results.tables[this.tableIndex];
		if (!wanted) {
			this.count.textContent = '';
			return [];
		}
		const key = `${results.key}|${wanted.id}`;
		const table = this.loaded.get(key);
		if (!table) {
			this.count.textContent = '';
			const problem = this.failed.get(key);
			append(this.body, $('.fem-tables-note', undefined, problem
				? localize('femTables.tableFailed', "{0} could not be read: {1}", wanted.title, problem)
				: localize('femTables.readingTable', "Working out {0} of {1}...", wanted.title, results.label)));
			if (!problem) {
				void this.read(results, wanted.id);
			}
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
		for (const note of table.notes) {
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
		const tbody = append(element, $('tbody'));
		renderSheetRows(tbody, rows.slice(0, MAX_TABLE_ROWS));
		// A design check's row or a member's row selects its member: it can be found and picked.
		if (results.group === 'design' || table.columns[0] === 'Member') {
			element.classList.add('pickable');
			[...tbody.children].forEach((tr, k) => {
				const member = String(rows[k]?.[0] ?? '');
				tr.setAttribute('tabindex', '0');
				tr.setAttribute('title', localize('femTables.pickMember', "Select {0} in the view", member));
				this.tableStore.add(addDisposableListener(tr, EventType.CLICK, () => this.onPickMember(member)));
				this.tableStore.add(addDisposableListener(tr, EventType.KEY_DOWN, e => {
					if (e.key === 'Enter' || e.key === ' ') {
						e.preventDefault();
						this.onPickMember(member);
					}
				}));
			});
		}
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

/** A length in metres, to the millimetre. */
function metres(value: number): string {
	return localize('femEditor.metres', "{0} m", value.toFixed(3));
}

/** The column lines along one axis, for a message: `0, 5, 10`. */
function gridList(model: IFilterModel, axis: 'x' | 'y'): string {
	return gridLines(model)[axis].map(v => String(v)).join(', ');
}

/** The status line while measuring: what to click next, or the value measured. */
export function measureText(mode: Exclude<FemMeasureMode, 'off'>, m: FemMeasurement | undefined): string {
	if (m?.length !== undefined) {
		return localize('femEditor.measuredLength', "Distance {0} (Δx {1}, Δy {2}, Δz {3}). Click to measure again; Escape clears.", metres(m.length), (m.dx ?? 0).toFixed(3), (m.dy ?? 0).toFixed(3), (m.dz ?? 0).toFixed(3));
	}
	if (m?.angle !== undefined) {
		return localize('femEditor.measuredAngle', "Angle {0}°. Click to measure again; Escape clears.", m.angle.toFixed(2));
	}
	if (mode === 'area' && m && m.points.length >= 3) {
		return m.complete
			? localize('femEditor.measuredArea', "Area {0} m², perimeter {1}. Click to measure again; Escape clears.", (m.area ?? 0).toFixed(3), metres(m.perimeter ?? 0))
			: localize('femEditor.measuringArea', "Area so far {0} m². Click the next corner, or the first point to close.", (m.area ?? 0).toFixed(3));
	}
	const picked = m?.points.length ?? 0;
	switch (mode) {
		case 'distance':
			return picked ? localize('femEditor.distanceSecond', "Click the second point.") : localize('femEditor.distanceFirst', "Measure distance: click the first point (nodes snap).");
		case 'angle':
			return picked === 0 ? localize('femEditor.angleFirst', "Measure angle: click a point on the first arm (nodes snap).")
				: picked === 1 ? localize('femEditor.angleVertex', "Click the vertex.") : localize('femEditor.angleThird', "Click a point on the second arm.");
		case 'area':
			return localize('femEditor.areaPoints', "Measure area: click the corners in turn (nodes snap), then the first point again to close.");
	}
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
	/** The model's supports (not the diaphragms' master nodes): the reactions tables show these. */
	private supports: ReadonlySet<number> = new Set();
	/** Columns standing free at the top (cantilevers): flagged in the properties panel. */
	private freeTop: readonly string[] = [];
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
	/** The mesh's own nodes (inside members split into pieces, of the wall and slab meshes): hidden unless asked for. */
	private readonly meshNodesAction = this._register(new Action('saengine.fem.editor.meshNodes', localize('femEditor.meshNodes', "Show Mesh Nodes"), undefined, true, async () => {
		this.meshNodesAction.checked = !this.meshNodesAction.checked;
		this.viewer?.setMeshNodes(!!this.meshNodesAction.checked);
	}));
	/** Clicks in the view measure (snapping to nodes) instead of selecting. */
	private readonly measureActions: { readonly [mode in Exclude<FemMeasureMode, 'off'>]: Action } = {
		distance: this._register(new Action('saengine.fem.editor.measureDistance', localize('femEditor.measureDistance', "Measure Distance"), undefined, true, async () => this.setMeasureMode('distance'))),
		angle: this._register(new Action('saengine.fem.editor.measureAngle', localize('femEditor.measureAngle', "Measure Angle"), undefined, true, async () => this.setMeasureMode('angle'))),
		area: this._register(new Action('saengine.fem.editor.measureArea', localize('femEditor.measureArea', "Measure Area"), undefined, true, async () => this.setMeasureMode('area'))),
	};
	private readonly exportAnimationAction = this._register(new Action('saengine.fem.editor.exportAnimation', localize('femEditor.exportAnimation', "Export Animation..."), undefined, true, () => this.exportAnimation()));
	private measureMode: FemMeasureMode = 'off';
	private measurement: FemMeasurement | undefined;
	/** The plan path of the custom developed elevation, once given. */
	private customPath: [number, number][] | undefined;
	private recording = false;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly viewerDisposable = this._register(new MutableDisposable());
	private readonly pill = this._register(new MutableDisposable());
	private readonly emptyStore = this._register(new MutableDisposable());
	private readonly propertiesStore = this._register(new MutableDisposable());
	private readonly plannedStore = this._register(new MutableDisposable());
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
		@IProgressService private readonly progressService: IProgressService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
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
		this.tables = this._register(this.instantiationService.createInstance(FemTablesPanel, frame.main, () => this.setTablesVisible(false), label => this.results?.selectResult(label), () => void this.exportTables(), member => this.pickDesignMember(member)));
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
		this._register(viewPicker.onDidSelect(({ index }) => index === this.views.length
			? void this.askDevelopedPath() // the last entry: "Developed Elevation: Custom Path..."
			: this.setView(this.views[index]?.choice ?? { kind: 'all' })));
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
	 * Exports result tables. To an Excel workbook: the tables and the results the engineer picks
	 * (every case and combination, or the one shown), one sheet per kind of table with the
	 * result in its first column, and the summary (storeys, base reactions, modes); streamed by
	 * the backend with its progress shown, and stoppable. To a CSV file: the table shown.
	 */
	private async exportTables(): Promise<void> {
		const resource = this.resource;
		const panel = this.tables;
		if (!resource || !panel) {
			return;
		}
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('femEditor.exportTitle', "Export Result Tables"),
			defaultUri: joinPath(dirname(resource), 'results.xlsx'),
			filters: [
				{ name: localize('femEditor.xlsxFiles', "Excel Workbooks"), extensions: ['xlsx'] },
				{ name: localize('femEditor.csvFiles', "CSV Files (the table shown)"), extensions: ['csv'] },
			],
		});
		if (!target) {
			return;
		}
		if (!/\.xlsx$/i.test(target.path)) {
			const shown = panel.shown;
			if (!shown?.table) {
				this.notificationService.info(localize('femEditor.csvNothing', "Show the table to export in Result Tables first: a CSV file holds the table shown."));
				return;
			}
			await this.fileService.writeFile(target, VSBuffer.fromString(resultTablesCsv([{ caseId: 0, caseName: shown.entry.label, resultType: shown.entry.group, earlyStop: false, warnings: [], tables: [shown.table] }])));
			this.notificationService.prompt(Severity.Info, localize('femEditor.exportedCsv', "Exported {0} of {1} to {2}.", shown.title, shown.entry.label, target.fsPath), [{
				label: localize('femEditor.revealExport', "Show in Folder"),
				run: () => this.commandService.executeCommand('revealFileInOS', target),
			}]);
			return;
		}
		const choice = await this.pickExport(panel);
		if (!choice) {
			return;
		}
		const extra: IFemSheet[] = choice.summary ? panel.summarySheets.map(s => ({ name: s.title, columns: s.columns, rows: s.rows, notes: s.notes })) : [];
		const source = new CancellationTokenSource();
		try {
			const written = await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('femEditor.exporting', "Exporting the result tables to {0}", basename(target)),
				cancellable: true,
			}, progress => {
				let reported = 0;
				return this.commandService.executeCommand<{ readonly sheets?: number; readonly rows?: number; readonly cancelled?: boolean }>(FEM_EXPORT_TABLES_COMMAND, resource, target, {
					keys: choice.keys,
					tables: choice.tables,
					extra,
					onProgress: (done: number, total: number, message: string) => {
						const share = total ? Math.round(100 * done / total) : 0;
						progress.report({ message: localize('femEditor.exportingStep', "{0} ({1} of {2} tables)", message, done, total), increment: share - reported });
						reported = share;
					},
				}, source.token);
			}, () => source.cancel());
			if (written?.cancelled) {
				this.notificationService.info(localize('femEditor.exportStopped', "The export was stopped; {0} was not written.", basename(target)));
				return;
			}
			this.notificationService.prompt(Severity.Info, localize('femEditor.exported', "Exported {0} sheets, {1} rows of results (kN, mm, kN·m) to {2}.", written?.sheets ?? 0, written?.rows ?? 0, target.fsPath), [{
				label: localize('femEditor.revealExport', "Show in Folder"),
				run: () => this.commandService.executeCommand('revealFileInOS', target),
			}]);
		} catch (error) {
			this.notificationService.error(localize('femEditor.exportFailed', "The result tables could not be exported: {0}", errorSummary(error)));
		} finally {
			source.dispose();
		}
	}

	/** The tables and results to export, picked by the engineer (all of them is large on a tall building). */
	private async pickExport(panel: FemTablesPanel): Promise<{ readonly keys?: string[]; readonly tables: string[]; readonly summary: boolean } | undefined> {
		const results = panel.results;
		const titles = new Map<string, string>();
		for (const result of results) {
			for (const table of result.tables) {
				if (!titles.has(table.id)) {
					titles.set(table.id, table.title);
				}
			}
		}
		const usual = new Set(['reactions', 'members', 'modal:0']);
		interface ITableItem extends IQuickPickItem { readonly id: string }
		const tableItems: ITableItem[] = [...titles].map(([id, title]) => ({ id, label: title, picked: usual.has(id) }));
		tableItems.push({ id: 'summary', label: localize('femEditor.exportSummary', "Summary: storeys, base reactions, modes"), picked: true });
		const tables = await this.quickInputService.pick(tableItems, {
			canPickMany: true,
			title: localize('femEditor.exportTablesTitle', "Tables to Export"),
			placeHolder: localize('femEditor.exportTablesHint', "Each becomes a sheet with the results in its first column; member forces of every combination of a tall building are a large file"),
		});
		if (!tables?.length) {
			return undefined;
		}
		const shown = panel.shown?.entry;
		interface IScopeItem extends IQuickPickItem { readonly keys?: string[] }
		const groups = (wanted: readonly FemTableGroup[]) => results.filter(r => wanted.includes(r.group)).map(r => r.key);
		const scopes: IScopeItem[] = [
			{ label: localize('femEditor.exportAll', "Every case and combination"), description: localize('femEditor.exportAllCount', "{0} results", results.length) },
			{ label: localize('femEditor.exportCombinations', "The load combinations"), keys: groups(['combination', 'spectrum', 'envelope']) },
			{ label: localize('femEditor.exportCases', "The load cases"), keys: groups(['case']) },
			...(shown && shown.group !== 'design' && shown.group !== 'summary' ? [{ label: localize('femEditor.exportShown', "The result shown: {0}", shown.label), keys: [shown.key] }] : []),
		];
		const scope = await this.quickInputService.pick(scopes, { title: localize('femEditor.exportScopeTitle', "Results to Export") });
		if (!scope) {
			return undefined;
		}
		return { keys: scope.keys, tables: tables.map(t => t.id).filter(id => id !== 'summary'), summary: tables.some(t => t.id === 'summary') };
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
			this.meshNodesAction,
			new Separator(),
			this.measureActions.distance,
			this.measureActions.angle,
			this.measureActions.area,
			this.exportAnimationAction,
		];
		for (const [mode, action] of Object.entries(this.measureActions)) {
			action.checked = this.measureMode === mode;
			action.enabled = this.nodeCount > 0;
		}
		// A deflected shape (a mode shape or a static case's) can be recorded moving.
		this.exportAnimationAction.enabled = hasResults && this.shownResult?.display.show === 'deformed' && !this.recording;
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

		// The tables follow the results while shown, with the design checks once run.
		const resource = this.resource;
		this.tables?.follow(results.resultLabel);
		this.tables?.setDesign(results.designReport);
		if (this.tablesVisible && running) {
			// The run replaces the results: no old tables meanwhile.
			if (this.tablesVersion !== -2) {
				this.tablesVersion = -2;
				this.tables?.showNote(localize('femTables.running', "The result tables are shown when the analysis has finished."));
			}
		} else if (this.tablesVisible && resource && hasResults && results.version !== this.tablesVersion) {
			this.tablesVersion = results.version;
			void this.tables?.load(resource, this.units, this.supports);
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
		if (this.recording) {
			return { busy: true, text: localize('femEditor.recording', "Recording the animation...") };
		}
		if (this.measureMode !== 'off') {
			return {
				text: measureText(this.measureMode, this.measurement),
				link: { label: localize('femEditor.measureDone', "Stop Measuring"), run: () => this.setMeasureMode('off') },
			};
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
		this.renderMeasurement(panel);
		this.results?.renderProperties(panel);
		this.renderMemberLink(panel);
		appendPropertyHeading(panel, localize('femEditor.modelHeading', "Model"));
		appendPropertyRow(panel, localize('femEditor.nodes', "Nodes"), String(this.nodeCount));
		appendPropertyRow(panel, localize('femEditor.elements', "Elements"), String(this.elementCount));
		if (this.units) {
			// What the engineer reads: the results are shown in kN, mm, kN·m whatever the solver uses.
			appendPropertyRow(panel, localize('femEditor.units', "Units"), this.units.startsWith('SI') ? localize('femEditor.unitsShown', "kN, mm, kN·m (solved in m, N)") : this.units);
		}
		if (this.freeTop.length) {
			appendPropertyNote(panel, localize('femEditor.freeTop', "Free at the top (nothing frames into it): {0}. It sways as a cantilever, with an effective length of about twice its height; check it is meant to stand free.", this.freeTop.join(', ')));
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
		if (last?.ok && last.wind) {
			this.appendWind(panel, last.wind);
		}
		if (last?.ok && last.notes.length) {
			appendPropertyHeading(panel, localize('femEditor.notesHeading', "Derivation Notes"));
			for (const note of last.notes) {
				appendPropertyNote(panel, note);
			}
		}
		this.renderPlanned(panel);
	}

	/** The measurement taken in the view: its value and the points picked. */
	private renderMeasurement(panel: HTMLElement): void {
		const m = this.measurement;
		if (this.measureMode === 'off' || !m) {
			return;
		}
		const developed = this.view.kind === 'developed';
		appendPropertyHeading(panel, localize('femEditor.measurement', "Measurement"));
		if (m.length !== undefined) {
			appendPropertyRow(panel, localize('femEditor.measureLength', "Length"), metres(m.length));
			appendPropertyRow(panel, developed ? localize('femEditor.measureAlong', "Δ along path") : 'Δx', metres(m.dx ?? 0));
			if (!developed) {
				appendPropertyRow(panel, 'Δy', metres(m.dy ?? 0));
			}
			appendPropertyRow(panel, 'Δz', metres(m.dz ?? 0));
		}
		if (m.angle !== undefined) {
			appendPropertyRow(panel, localize('femEditor.measureAngleRow', "Angle"), `${m.angle.toFixed(2)}°`);
		}
		if (m.area !== undefined) {
			appendPropertyRow(panel, localize('femEditor.measureAreaRow', "Area"), localize('femEditor.squareMetres', "{0} m²", m.area.toFixed(3)));
			appendPropertyRow(panel, localize('femEditor.measurePerimeter', "Perimeter"), metres(m.perimeter ?? 0));
			if (!m.complete) {
				appendPropertyNote(panel, localize('femEditor.measureAreaOpen', "Click the first point again to close the polygon."));
			}
		}
		m.points.forEach((p, k) => appendPropertyRow(panel, localize('femEditor.measurePoint', "Point {0}", k + 1),
			developed ? `s ${p[0].toFixed(3)}, z ${p[2].toFixed(3)} m` : `${p[0].toFixed(3)}, ${p[1].toFixed(3)}, ${p[2].toFixed(3)} m`));
		if (developed) {
			appendPropertyNote(panel, localize('femEditor.measureDeveloped', "Measured in the developed elevation: s is the distance along the path."));
		}
	}

	/** Chips to the analyses and systems planned after this MVP (see `FemPlanned`). */
	private renderPlanned(panel: HTMLElement): void {
		const store = new DisposableStore();
		store.add(appendPlannedChips(panel, localize('femEditor.plannedAnalyses', "Planned Analyses"), [
			FemPlanned.stagedConstructionLoads, FemPlanned.creepShrinkageForces, FemPlanned.wallShortening,
			FemPlanned.pushoverHinges, FemPlanned.performancePoint,
		], this.commandService));
		store.add(appendPlannedChips(panel, localize('femEditor.plannedSystems', "Planned: Dampers, Existing Buildings"), [
			FemPlanned.dampers, FemPlanned.existingAssessment, FemPlanned.retrofit,
		], this.commandService));
		this.plannedStore.value = store;
	}

	/** The wind's gust factor per direction and its cladding pressures by zone (BNBC 2020 Part 6 Sec 2.4.8, 2.4.11.5). */
	private appendWind(panel: HTMLElement, wind: IFemWindSummary): void {
		const gust = wind.gust;
		const cladding = wind.cladding;
		if (!cladding && !gust) {
			return;
		}
		appendPropertyHeading(panel, localize('femEditor.windHeading', "Wind"), cladding ? localize('femEditor.windQh', "qh {0} kN/m² at h = {1} m", cladding.qh_kPa.toFixed(2), cladding.h_m.toFixed(1)) : undefined);
		for (const axis of ['X', 'Y'] as const) {
			const g = gust?.[axis];
			if (g) {
				appendPropertyRow(panel, localize('femEditor.windGust', "Gust factor {0}", axis), g.flexible
					? localize('femEditor.windGustFlexible', "Gf {0} (flexible, n1 {1} Hz)", g.G.toFixed(3), g.n1_Hz.toFixed(2))
					: localize('femEditor.windGustRigid', "G {0} (rigid, n1 {1} Hz)", g.G.toFixed(2), g.n1_Hz.toFixed(2)));
			}
		}
		if (!cladding) {
			return;
		}
		const kPa = (v: number | null) => v === null ? '' : `${v > 0 ? '+' : ''}${v.toFixed(2)}`;
		for (const zone of cladding.zones) {
			const name = zone.surface === 'wall'
				? localize('femEditor.windWallZone', "Wall zone {0}", zone.zone)
				: localize('femEditor.windRoofZone', "Roof zone {0}", zone.zone);
			const values = [kPa(zone.pPos_kPa), kPa(zone.pNeg_kPa)].filter(v => v).join(' / ');
			appendPropertyRow(panel, name, localize('femEditor.windZoneValue', "{0} kN/m²", values));
		}
		if (cladding.parapet) {
			appendPropertyRow(panel, localize('femEditor.windParapet', "Parapet"), localize('femEditor.windParapetValue', "A {0}, B {1} kN/m²", cladding.parapet.caseA_kPa.toFixed(2), cladding.parapet.caseB_kPa.toFixed(2)));
		}
		appendPropertyNote(panel, localize('femEditor.windCladdingNote', "Components and cladding (BNBC 2020 Part 6 Sec 2.4.11.5): p = qh·[(GCp) − (±GCpi)], GCpi ±{0}; zones 5 and 3 lie within a = {1} m of corners, zone 2 of roof edges. Effective wind area: {2}.",
			cladding.GCpi.toFixed(2), cladding.a_m.toFixed(2), cladding.area_m2 ? localize('femEditor.windArea', "{0} m²", cladding.area_m2.toFixed(2)) : localize('femEditor.windAreaSmallest', "the smallest (largest pressures)")));
	}

	/**
	 * Selects a checked member (building model id, `B5`) in the view from the design checks
	 * table, with Design Utilisation shown so the properties give its checks.
	 */
	/** Selects a member picked in the tables: a design check's (shown with the design), or a member forces row's. */
	private pickDesignMember(member: string): void {
		const checked = this.results?.designReport?.elements.find(e => e.id === member);
		const id = checked?.members[0] ?? this.femModel?.elements.find(e => memberOf(e.name ?? '') === member)?.id;
		if (id === undefined) {
			return; // not in the analysis model
		}
		if (checked && !this.results?.showsDesign) {
			this.results?.toggleDesign();
		}
		const selection: FemSelection = { kind: 'element', id };
		this.viewer?.setSelection(selection);
		this._onDidChangeSelection.fire(selection);
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
		store.add(button.onDidClick(() => this.commandService.executeCommand(FEM_SHOW_MEMBER_COMMAND, resource, member, this.results?.resultLabel)));
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
				onMeasure: measurement => {
					this.measurement = measurement;
					this.updateChrome();
				},
			});
			this.viewer = viewer;
			viewer.setMeshNodes(!!this.meshNodesAction.checked);
			viewer.setMeasureMode(this.measureMode);
			if (this.shownResult) {
				viewer.setResults(this.shownResult.view, this.shownResult.display);
			}
			if (this.view.kind !== 'all' && this.femModel) {
				this.applyView(this.view, true);
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
		this.supports = supportNodes(model as unknown as IFemModelNodes);
		this.freeTop = freeTopColumns(model as unknown as IFilterModel);
		this.elementCount = model.elements.length;
		this.derivation?.setDescription(meta?.description);
		this.results?.setResource(input.resource, this.units);
		this.results?.setModel(model);
		this.viewer?.setModel(displayModel(model as unknown as IFemModelNodes) as unknown as FemModel);
		this.updateViews(model as unknown as IFilterModel);
		if (wasEmpty && this.nodeCount) {
			// A model derived into an empty file: frame it (the first fit framed nothing).
			void this.viewer?.fit();
		}
		this.updateChrome();
	}

	/** The View picker's choices for `model`, keeping the view shown when the model still has it. */
	private updateViews(model: IFilterModel): void {
		this.views = viewChoices(model, undefined, this.customPath);
		const key = JSON.stringify(this.view);
		const index = Math.max(0, this.views.findIndex(v => JSON.stringify(v.choice) === key));
		this.viewPicker?.setOptions([
			...this.views.map<ISelectOptionItem>(v => ({ text: v.label })),
			{ text: localize('femEditor.developedCustomPath', "Developed Elevation: Custom Path...") },
		], index);
		this.applyView(this.views[index]?.choice ?? { kind: 'all' }, false);
	}

	/**
	 * Asks for the plan path of a developed elevation (points along the frames to unfold, such
	 * as a facade's column lines) and shows it; the picker goes back to the view shown when
	 * none is given.
	 */
	private async askDevelopedPath(): Promise<void> {
		const model = this.femModel as unknown as IFilterModel | undefined;
		const initial = this.customPath ?? (model ? perimeterPath(model) : undefined);
		const text = await this.quickInputService.input({
			title: localize('femEditor.developedTitle', "Developed Elevation"),
			prompt: localize('femEditor.developedPrompt', "Plan points along the frames to unfold, in metres: x, y; x, y; ... The frames and walls standing on the path are laid out in one plane, in the order walked."),
			placeHolder: '0, 0; 12, 0; 12, 9',
			value: initial ? formatPlanPath(initial) : '',
			validateInput: async value => {
				const parsed = parsePlanPath(value);
				return 'error' in parsed ? parsed.error : undefined;
			},
		});
		const parsed = text === undefined ? undefined : parsePlanPath(text);
		if (!parsed || 'error' in parsed || !model) {
			this.updateViews(model ?? { nodes: [], elements: [] }); // the picker shows the view shown
			return;
		}
		this.customPath = parsed.path;
		this.view = { kind: 'developed', path: parsed.path, name: 'custom' };
		this.updateViews(model);
		this.applyView(this.view, true);
		if (this.viewer && !this.viewer.setDevelopment(parsed.path)?.size) {
			this.notificationService.info(localize('femEditor.developedEmpty', "No frame or wall stands on that path. Give points on the column lines (x = {0} m; y = {1} m).",
				gridList(model, 'x'), gridList(model, 'y')));
		}
	}

	private setMeasureMode(mode: FemMeasureMode): void {
		const next = this.measureMode === mode ? 'off' : mode; // its menu item again: stop measuring
		this.measureMode = next;
		this.measurement = undefined;
		this.viewer?.setMeasureMode(next);
		this.updateChrome();
		this.viewport?.focus(); // Escape clears the measurement
	}

	/**
	 * Records the deflected shape shown moving (a mode shape oscillating, a static case's shape
	 * growing and back) as a WebM video of the view, at the view's size.
	 */
	private async exportAnimation(): Promise<void> {
		const resource = this.resource;
		const viewer = this.viewer;
		const shown = this.shownResult;
		if (!resource || !viewer || shown?.display.show !== 'deformed' || this.recording) {
			this.notificationService.info(localize('femEditor.animationNeedsShape', "Show a deflected shape (a mode shape or a case's deformed shape) to export it as an animation."));
			return;
		}
		const name = shown.view.label.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'animation';
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('femEditor.exportAnimationTitle', "Export Animation"),
			defaultUri: joinPath(dirname(resource), `${name}.webm`),
			filters: [{ name: localize('femEditor.webmFiles', "WebM Videos"), extensions: ['webm'] }],
		});
		if (!target) {
			return;
		}
		this.recording = true;
		this.updateChrome();
		try {
			const video = await viewer.recordAnimation({ seconds: 6.4, fps: 30 });
			if (!video) {
				this.notificationService.error(localize('femEditor.animationFailed', "The animation could not be recorded: this view cannot record video."));
				return;
			}
			await this.fileService.writeFile(target, VSBuffer.wrap(new Uint8Array(await video.arrayBuffer())));
			this.notificationService.prompt(Severity.Info, localize('femEditor.animationExported', "Exported the animation of {0} to {1}.", shown.view.label, target.fsPath), [{
				label: localize('femEditor.revealExport', "Show in Folder"),
				run: () => this.commandService.executeCommand('revealFileInOS', target),
			}]);
		} catch (error) {
			this.notificationService.error(localize('femEditor.animationFailed2', "The animation could not be exported: {0}", errorSummary(error)));
		} finally {
			this.recording = false;
			this.updateChrome();
		}
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
		// A developed elevation: the viewer unfolds the path and finds the elements on it.
		const onPath = this.viewer.setDevelopment(choice.kind === 'developed' ? choice.path : undefined);
		const visible = choice.kind === 'developed' ? new Set(onPath ?? []) : visibleElements(model, choice);
		if (changed) {
			this.measurement = undefined; // measured in the other drawing
		}
		this.viewer.setVisibleElements(visible);
		this.results?.setVisible(visible);
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
