/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import './media/soilEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isHTMLInputElement } from '../../../../base/browser/dom.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { BNBC } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import {
	BOREHOLE_FIELDS, bearingSummary, boreholeDepth, boreholeGround, checkSoilReport, choiceTitle, DESIGN_CHOICES, DESIGN_DEFAULTS, DESIGN_FIELDS, formatField, formatNumber, hasLiquefiable, IBearingCell, IBearingResult, IBorehole, IBoreholeResult, IFieldSpec,
	ISoilComputeRequest, ISoilImportRequest, ISoilImportResult, ISoilProblem, ISoilReport, ISoilResults, ISoilTemplateRequest, ISoilTemplateResult, LAYER_FIELDS, newBorehole, parseField,
	IChoiceSpec, ISiteClassFlag, parseSoilReport, readSoilResults, REPORT_FIELDS, resultsBasis, SAMPLE_FIELDS, serializeSoilReport, SOIL_COMPUTE_COMMAND, SOIL_IMPORT_COMMAND, SOIL_TEMPLATE_COMMAND, SOIL_TYPES, siteFlagMeaning, siteFlagsOf, soilSummary, soilTypeLabel, SPT_FIELDS,
} from './soilDocument.js';
import { SoilEditorInput } from './soilEditorInput.js';
import { appendSoilPatterns, appendSoilSwatch, renderBoreholeLog, renderFence, renderLiquefactionChart } from './soilLog.js';

type View = 'log' | 'data' | 'results';

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: 'log', label: localize('soil.viewLog', "Log"), icon: Codicon.layers },
	{ view: 'data', label: localize('soil.viewData', "Data"), icon: Codicon.table },
	{ view: 'results', label: localize('soil.viewResults', "Results"), icon: Codicon.graphLine },
];

/** The state of the results: not asked yet, being computed, computed, or no backend / failed. */
type ResultsState = 'idle' | 'computing' | 'ok' | 'missing' | 'error';

/** A row of a data table: the list it is in, for the problem paths ("layers.2.top"). */
type RowList = 'layers' | 'spt' | 'samples';

let instanceCount = 0;

/**
 * The soil report (`01 Soil Report/soil-report.json`) on the shared editor frame. Boreholes are
 * listed on the left; the Log view draws the selected one (strata, water table, SPT N against
 * depth) or the fence of all of them, the Data view edits their layers, SPT records and lab
 * samples, and the Results view shows what the backend computes from them: the site class, the
 * allowable bearing pressure by footing size, the liquefaction screening, the modulus of
 * subgrade reaction and the pile design parameters. The JSON text model stays the document:
 * every edit is one undoable text edit, so save, dirty state and undo come from the text file.
 */
export class SoilEditor extends EditorPane {

	static readonly ID = SoilEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private list!: HTMLElement;
	private viewElement!: HTMLElement;
	private readonly viewButtons = new Map<View, HTMLButtonElement>();
	private readonly patternPrefix = `saengine-soil-${++instanceCount}`;

	private model: ITextModel | undefined;
	private report: ISoilReport | undefined;
	private parseError: string | undefined;
	private problems: ISoilProblem[] = [];
	private applying = false;
	private view: View = 'log';
	private fence = false;
	/** The selected borehole's index in the report (ids may repeat); undefined selects the report itself. */
	private selected: number | undefined;
	private results: ISoilResults | undefined;
	private resultsState: ResultsState = 'idle';
	private resultsError: string | undefined;
	private computeVersion = 0;
	/** What keeps the toolbar's progress bar on (a computation, an import). */
	private readonly busy = new Set<string>();
	private actionsKey: string | undefined;
	private lastSize = '';
	/** The inputs of the data view by problem key ("0|layers.0.top": borehole index and path). */
	private readonly inputs = new Map<string, HTMLElement>();
	/** The inputs of the properties panel by problem key ("0|id"). */
	private readonly propertyInputs = new Map<string, HTMLElement>();
	/** The report object and borehole the properties panel was built for: its inputs write into them. */
	private propertiesFor: { report: ISoilReport | undefined; selected: number | undefined } | undefined;
	/** Whether inputs being created belong to the properties panel (their listeners and keys). */
	private renderingProperties = false;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly viewDisposables = this._register(new DisposableStore());
	private readonly listDisposables = this._register(new DisposableStore());
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private readonly emptyDisposables = this._register(new DisposableStore());
	private readonly settings = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 300));
	private readonly computeScheduler = this._register(new RunOnceScheduler(() => void this.compute(), 700));
	private readonly layoutScheduler = this._register(new RunOnceScheduler(() => this.onMainResized(), 50));

	private readonly addAction = this._register(new Action('saengine.soil.editor.add', localize('soil.addBorehole', "Add Borehole"), ThemeIcon.asClassName(Codicon.add), true, async () => this.addBorehole()));
	private readonly importAction = this._register(new Action('saengine.soil.editor.import', localize('soil.import', "Import CSV/Excel..."), ThemeIcon.asClassName(Codicon.cloudDownload), true, () => this.importFile()));
	private readonly templateAction = this._register(new Action('saengine.soil.editor.template', localize('soil.template', "Save Template..."), ThemeIcon.asClassName(Codicon.notebookTemplate), true, () => this.saveTemplate()));
	private readonly deleteAction = this._register(new Action('saengine.soil.editor.delete', localize('soil.deleteBorehole', "Delete Borehole"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteBorehole()));
	private readonly fenceAction = this._register(new Action('saengine.soil.editor.fence', localize('soil.fence', "Show All Boreholes Side by Side"), ThemeIcon.asClassName(Codicon.splitHorizontal), true, async () => this.toggleFence()));
	private readonly duplicateAction = this._register(new Action('saengine.soil.editor.duplicate', localize('soil.duplicate', "Duplicate Borehole"), undefined, false, async () => this.duplicateBorehole()));
	private readonly recomputeAction = this._register(new Action('saengine.soil.editor.recompute', localize('soil.recompute', "Compute Results Again"), undefined, true, async () => this.compute()));
	private readonly openTextAction = this._register(new Action('saengine.soil.editor.openText', localize('soil.openText', "Open as Text"), undefined, true, () => this.openAsText()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@INotificationService private readonly notificationService: INotificationService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(SoilEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.renderActions();
			}
		}));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			// The backend registers its commands when it starts: compute as soon as it can.
			if (id === SOIL_COMPUTE_COMMAND && this.resultsState === 'missing') {
				this.computeScheduler.schedule(0);
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: SoilEditor.ID,
			ariaLabel: localize('soil.toolbar', "Soil Report"),
			properties: { title: localize('soil.properties', "Properties"), defaultWidth: 280 },
		}));
		frame.element.classList.add('saengine-soil-editor');
		frame.setTitle(localize('soil.title', "Soil Report"));
		frame.setHelp(localize('soil.help', "The boreholes of the site investigation: strata, SPT blow counts and lab test results, entered here or imported from a CSV or Excel file. From them SAEngine finds the site class (BNBC 2020), the allowable bearing pressure for a range of footing sizes, the liquefaction screening from SPT, the modulus of subgrade reaction and the pile design parameters per layer for the substructure. Depths are in m below the borehole's ground."));

		const views = append(frame.controlsSlot, $('.sa-segmented', { role: 'tablist', 'aria-label': localize('soil.viewsAria', "Soil report view") }));
		for (const { view, label, icon } of VIEWS) {
			const button = append(views, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }));
			append(button, $(ThemeIcon.asCSSSelector(icon)));
			append(button, $('span', undefined, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.showView(view)));
			this.viewButtons.set(view, button);
		}

		const body = append(frame.main, $('.soil-body'));
		appendSoilPatterns(body, this.patternPrefix);
		this.list = append(body, $('.soil-list', { role: 'listbox', tabIndex: 0, 'aria-label': localize('soil.listAria', "Boreholes") }));
		this.viewElement = append(body, $('.soil-view', { tabIndex: -1 }));
		this._register(addDisposableListener(this.list, EventType.KEY_DOWN, e => this.onListKey(e)));
		this._register(frame.onDidLayoutMain(() => this.layoutScheduler.schedule()));
		this.updateViewButtons();
	}

	override async setInput(input: SoilEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.settings.clear();
		this.model = undefined;
		this.results = undefined;
		this.resultsState = 'idle';
		this.selected = undefined;
		const reference = await input.resolve();
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
		this.model = reference.object.textEditorModel;
		this.inputDisposables.add(this.model.onDidChangeContent(() => {
			if (!this.applying) {
				this.load(); // undo/redo, revert, external edits
			}
		}));
		// The project settings give the PGA (seismic zone and site class) for the liquefaction screening.
		const part = partById('settings');
		if (part?.mainFile) {
			try {
				const settings = await this.textModelService.createModelReference(joinPath(dirname(dirname(input.resource)), part.folder, part.mainFile));
				if (this.input !== input) {
					settings.dispose();
					return;
				}
				this.settings.value = settings;
				this.inputDisposables.add(settings.object.textEditorModel.onDidChangeContent(() => this.computeScheduler.schedule()));
			} catch {
				// Without settings the backend uses its defaults or the report's PGA.
			}
		}
		this.load();
	}

	override clearInput(): void {
		this.flush();
		this.inputDisposables.clear();
		this.settings.clear();
		this.computeScheduler.cancel();
		this.model = undefined;
		this.report = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.list?.focus();
	}

	override dispose(): void {
		this.flush();
		super.dispose();
	}

	/** The soil report's file. */
	get resource(): URI | undefined {
		return (this.input as SoilEditorInput | undefined)?.resource;
	}

	private get developerMode(): boolean {
		return this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
	}

	private get borehole(): IBorehole | undefined {
		return this.selected === undefined ? undefined : this.report?.boreholes[this.selected];
	}

	/** A borehole's results: the backend answers in the report's order; by id when they no longer line up. */
	private resultOf(borehole: IBorehole): IBoreholeResult | undefined {
		const index = this.report?.boreholes.indexOf(borehole) ?? -1;
		const byIndex = index >= 0 ? this.results?.boreholes?.[index] : undefined;
		return byIndex?.id === borehole.id ? byIndex : this.results?.boreholes?.find(b => b.id === borehole.id);
	}

	/** Turns the toolbar's progress bar on or off for one holder; it shows while any holds it. */
	private setBusy(holder: string, busy: boolean): void {
		const was = this.busy.size > 0;
		if (busy) {
			this.busy.add(holder);
		} else {
			this.busy.delete(holder);
		}
		if (this.busy.size > 0 && !was) {
			this.frame.showProgress();
		} else if (!this.busy.size && was) {
			this.frame.hideProgress();
		}
	}

	// ───────────────────────────── document ─────────────────────────────

	private load(): void {
		if (!this.model) {
			return;
		}
		const parsed = parseSoilReport(this.model.getValue());
		if (parsed.kind === 'error') {
			this.report = undefined;
			this.parseError = parsed.message;
		} else {
			this.report = parsed.report;
			this.parseError = undefined;
			const count = this.report.boreholes.length;
			if (this.selected !== undefined && this.selected >= count) {
				this.selected = count ? count - 1 : undefined;
			}
			if (this.selected === undefined && count && !this.reportSelectedOnPurpose) {
				this.selected = 0;
			}
		}
		this.problems = this.report ? checkSoilReport(this.report) : [];
		this.render();
		this.computeScheduler.schedule(this.resultsState === 'idle' ? 0 : undefined);
	}

	/** The engineer picked "Report" in the list: keep it when the file reloads. */
	private reportSelectedOnPurpose = false;

	/** Writes the report to the text model as one undoable edit. */
	private commit(): void {
		this.commitScheduler.cancel();
		const model = this.model;
		if (!model || !this.report || model.isDisposed()) {
			return;
		}
		const text = serializeSoilReport(this.report);
		if (text === model.getValue()) {
			return;
		}
		this.applying = true;
		try {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null);
			model.pushStackElement();
		} finally {
			this.applying = false;
		}
		this.computeScheduler.schedule();
	}

	private flush(): void {
		if (this.commitScheduler.isScheduled()) {
			this.commit();
		}
	}

	/** After an edit in place: structural edits save and re-render at once, typing is batched. */
	private changed(structural: boolean): void {
		if (!this.report) {
			return;
		}
		this.problems = checkSoilReport(this.report);
		if (structural) {
			this.commit();
			this.render();
		} else {
			this.commitScheduler.schedule();
			this.renderList();
			this.renderProblems();
			this.renderStatus();
		}
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Adds a borehole beside the last one and selects it in the Data view. */
	addBorehole(): void {
		if (!this.report) {
			return;
		}
		const borehole = newBorehole(this.report);
		this.report.boreholes.push(borehole);
		this.selected = this.report.boreholes.length - 1;
		this.reportSelectedOnPurpose = false;
		this.view = this.view === 'results' ? 'data' : this.view;
		this.changed(true);
	}

	private deleteBorehole(): void {
		const borehole = this.borehole;
		if (!this.report || !borehole) {
			return;
		}
		const index = this.report.boreholes.indexOf(borehole);
		this.report.boreholes.splice(index, 1);
		this.selected = this.report.boreholes.length ? Math.min(index, this.report.boreholes.length - 1) : undefined;
		this.changed(true);
	}

	private duplicateBorehole(): void {
		const borehole = this.borehole;
		if (!this.report || !borehole) {
			return;
		}
		const copy: IBorehole = JSON.parse(JSON.stringify(borehole));
		copy.id = newBorehole(this.report).id;
		copy.x = borehole.x + 5000;
		const index = this.report.boreholes.indexOf(borehole) + 1;
		this.report.boreholes.splice(index, 0, copy);
		this.selected = index;
		this.changed(true);
	}

	/** Shows the log of one borehole (from the fence). */
	private openLog(index: number): void {
		this.fence = false;
		this.selected = index;
		this.reportSelectedOnPurpose = false;
		this.render();
	}

	private toggleFence(): void {
		this.fence = !this.fence;
		this.render();
	}

	private select(index: number | undefined): void {
		if (index === this.selected) {
			return;
		}
		this.flush();
		this.selected = index;
		this.reportSelectedOnPurpose = index === undefined;
		this.render();
	}

	private showView(view: View): void {
		this.flush();
		this.view = view;
		this.render();
	}

	/**
	 * Imports boreholes from a CSV or Excel file (asks for it when `file` is not given): the backend
	 * merges them into the report, which is replaced as one undoable edit.
	 */
	async importFile(file?: URI): Promise<void> {
		this.flush();
		const model = this.model;
		if (!model || !this.report) {
			return;
		}
		if (!CommandsRegistry.getCommand(SOIL_IMPORT_COMMAND)) {
			this.notificationService.info(localize('soil.importNoBackend', "Importing needs the SAEngine backend, which is not available in this window."));
			return;
		}
		if (!file) {
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('soil.importTitle', "Import Boreholes"),
				canSelectFiles: true,
				canSelectMany: false,
				filters: [
					{ name: localize('soil.importFilter', "Borehole Data (CSV, Excel)"), extensions: ['csv', 'xlsx', 'xls'] },
					{ name: localize('soil.allFiles', "All Files"), extensions: ['*'] },
				],
				defaultUri: this.resource && dirname(this.resource),
			});
			file = picked?.[0];
		}
		if (!file || this.model !== model) {
			return;
		}
		const before = new Set(this.report.boreholes.map(b => b.id));
		let result: ISoilImportResult | undefined;
		this.setBusy('import', true);
		try {
			const request: ISoilImportRequest = { path: file.fsPath, soilText: serializeSoilReport(this.report) };
			result = await this.commandService.executeCommand<ISoilImportResult>(SOIL_IMPORT_COMMAND, request);
		} catch (error) {
			this.notificationService.error(localize('soil.importFailed', "{0} could not be imported: {1}", basename(file), String(error)));
			return;
		} finally {
			this.setBusy('import', false);
		}
		if (!result?.text) {
			this.notificationService.warn(localize('soil.importProblems', "{0} could not be imported: {1}", basename(file), (result?.problems ?? []).join('; ')));
			return;
		}
		const parsed = parseSoilReport(result.text);
		if (parsed.kind !== 'report' || this.model !== model) {
			return;
		}
		this.report = parsed.report;
		const added = parsed.report.boreholes.filter(b => !before.has(b.id));
		const first = added[0] ?? parsed.report.boreholes[0];
		this.selected = first ? parsed.report.boreholes.indexOf(first) : undefined;
		this.changed(true);
		if (result.problems?.length) {
			this.notificationService.warn(localize('soil.importedWithProblems', "Imported {0} with notes: {1}", basename(file), result.problems.join('; ')));
		} else {
			this.notificationService.info(localize('soil.imported', "Imported {0}: {1} new borehole(s).", basename(file), added.length));
		}
	}

	/** Writes a CSV or Excel template for the boreholes (asks where when `file` is not given). */
	async saveTemplate(file?: URI): Promise<void> {
		if (!CommandsRegistry.getCommand(SOIL_TEMPLATE_COMMAND)) {
			this.notificationService.info(localize('soil.templateNoBackend', "Saving a template needs the SAEngine backend, which is not available in this window."));
			return;
		}
		if (!file) {
			const folder = this.resource ? dirname(this.resource) : undefined;
			file = await this.fileDialogService.showSaveDialog({
				title: localize('soil.templateTitle', "Save Borehole Template"),
				defaultUri: folder ? joinPath(folder, 'boreholes-template.xlsx') : undefined,
				filters: [
					{ name: localize('soil.templateExcel', "Excel Workbook"), extensions: ['xlsx'] },
					{ name: localize('soil.templateCsv', "CSV"), extensions: ['csv'] },
				],
			});
		}
		if (!file) {
			return;
		}
		try {
			const request: ISoilTemplateRequest = { path: file.fsPath };
			const result = await this.commandService.executeCommand<ISoilTemplateResult>(SOIL_TEMPLATE_COMMAND, request);
			if (result?.problems?.length) {
				this.notificationService.warn(localize('soil.templateProblems', "The template could not be saved: {0}", result.problems.join('; ')));
			} else {
				this.notificationService.info(localize('soil.templateSaved', "Saved the borehole template to {0}. Fill it in and import it.", basename(file)));
			}
		} catch (error) {
			this.notificationService.error(localize('soil.templateFailed', "The template could not be saved: {0}", String(error)));
		}
	}

	private async openAsText(): Promise<void> {
		const resource = this.resource;
		if (resource) {
			this.flush();
			await this.editorService.openEditor({ resource, options: { override: DEFAULT_EDITOR_ASSOCIATION.id, pinned: true } }, this.group);
		}
	}

	/** Asks the backend for the results of the current report (debounced after every edit). */
	async compute(): Promise<void> {
		const model = this.model;
		const report = this.report;
		const version = ++this.computeVersion;
		if (!model || !report || !report.boreholes.length) {
			this.setBusy('compute', false); // an earlier computation may still be on its way
			this.results = undefined;
			this.resultsState = 'idle';
			this.renderResultsDependent();
			return;
		}
		if (!CommandsRegistry.getCommand(SOIL_COMPUTE_COMMAND)) {
			this.setBusy('compute', false);
			this.results = undefined;
			this.resultsState = 'missing';
			this.renderResultsDependent();
			return;
		}
		this.flush();
		this.resultsState = this.results ? 'ok' : 'computing';
		this.setBusy('compute', true);
		let results: ISoilResults | undefined;
		let error: string | undefined;
		try {
			const request: ISoilComputeRequest = { soilText: model.getValue(), settingsText: this.settings.value?.object.textEditorModel.getValue() };
			results = readSoilResults(await this.commandService.executeCommand<unknown>(SOIL_COMPUTE_COMMAND, request));
			if (!results) {
				error = localize('soil.computeEmpty', "The backend gave no results.");
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		if (version !== this.computeVersion) {
			return; // a newer computation is on its way and turns the progress bar off
		}
		this.setBusy('compute', false);
		this.results = results;
		this.resultsState = results ? 'ok' : 'error';
		this.resultsError = error;
		this.renderResultsDependent();
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		if (!this.frame) {
			return;
		}
		this.updateViewButtons();
		this.renderActions();
		this.renderEmpty();
		this.renderList();
		this.renderView();
		this.renderProperties();
		this.renderStatus();
	}

	/** The parts that show results: the Results view, N60 in the log and data views, and the status. */
	private renderResultsDependent(): void {
		if (this.view === 'results' || this.view === 'log' || this.view === 'data' && this.selected !== undefined) {
			this.renderView();
		}
		this.renderProperties();
		this.renderStatus();
	}

	private onMainResized(): void {
		const size = `${this.viewElement.clientWidth}x${this.viewElement.clientHeight}`;
		if (size !== this.lastSize && this.view !== 'data') {
			this.renderView();
		}
	}

	private updateViewButtons(): void {
		const usable = !!this.report;
		for (const [view, button] of this.viewButtons) {
			const active = view === this.view;
			button.classList.toggle('active', active);
			button.setAttribute('aria-selected', String(active));
			button.disabled = !usable;
		}
	}

	private renderActions(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const usable = !!this.report;
		const hasBorehole = !!this.borehole;
		this.addAction.enabled = this.importAction.enabled = usable;
		this.deleteAction.enabled = this.duplicateAction.enabled = hasBorehole;
		this.recomputeAction.enabled = !!this.report?.boreholes.length;
		this.deleteAction.label = hasBorehole ? localize('soil.deleteNamed', "Delete {0}", this.borehole!.id) : localize('soil.deleteBorehole', "Delete Borehole");
		this.fenceAction.checked = this.fence;
		const primary: IAction[] = usable ? [
			this.addAction,
			this.importAction,
			this.templateAction,
			...(this.view === 'log' && (this.report?.boreholes.length ?? 0) > 1 ? [this.fenceAction] : []),
			this.deleteAction,
			frame.togglePropertiesAction,
		] : [frame.togglePropertiesAction];
		const secondary: IAction[] = usable ? [this.duplicateAction, this.recomputeAction] : [];
		if (this.developerMode || this.parseError) {
			if (secondary.length) {
				secondary.push(new Separator());
			}
			secondary.push(this.openTextAction);
		}
		const key = `${primary.map(a => a.id).join()}|${secondary.map(a => a.id).join()}`;
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			frame.setActions(primary, secondary);
		}
	}

	private renderEmpty(): void {
		this.emptyDisposables.clear();
		if (this.parseError) {
			this.frame.setEmpty({
				icon: Codicon.warning,
				title: localize('soil.cannotShow', "The soil report cannot be shown"),
				text: this.parseError,
				actions: [{ label: localize('soil.openText', "Open as Text"), primary: true, run: () => void this.openAsText() }],
			});
		} else if (this.report && !this.report.boreholes.length) {
			this.frame.setEmpty({
				icon: Codicon.layers,
				title: localize('soil.emptyTitle', "No boreholes yet"),
				text: localize('soil.emptyText', "Add the boreholes of the site investigation: their strata, SPT blow counts and lab results. SAEngine then finds the site class, the allowable bearing pressure, the liquefaction risk and the pile parameters."),
				actions: [
					{ label: localize('soil.addBorehole', "Add Borehole"), icon: Codicon.add, primary: true, run: () => this.addBorehole() },
					{ label: localize('soil.import', "Import CSV/Excel..."), icon: Codicon.cloudDownload, run: () => void this.importFile() },
				],
				link: { label: localize('soil.emptyTemplate', "Save a template to fill in"), run: () => void this.saveTemplate() },
			});
		} else {
			this.frame.setEmpty(undefined);
		}
	}

	// ───────────────────────────── borehole list ─────────────────────────────

	private renderList(): void {
		this.listDisposables.clear();
		clearNode(this.list);
		const report = this.report;
		if (!report) {
			return;
		}
		const item = (index: number | undefined, name: string, detail: string, icon: ThemeIcon) => {
			const selected = index === this.selected;
			const element = append(this.list, $('.soil-list-item', { role: 'option', 'aria-selected': String(selected) }));
			element.classList.toggle('selected', selected);
			append(element, $(`span.soil-list-icon${ThemeIcon.asCSSSelector(icon)}`));
			const text = append(element, $('.soil-list-text'));
			append(text, $('span.soil-list-name', undefined, name));
			append(text, $('span.soil-list-detail', undefined, detail));
			const warning = this.problems.some(p => p.severity === 'error' && p.index === index);
			if (warning) {
				append(element, $(`span.soil-list-warning${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			}
			this.listDisposables.add(addDisposableListener(element, EventType.CLICK, () => this.select(index)));
		};
		item(undefined, localize('soil.reportItem', "Report"), report.report.title || soilSummary(report), Codicon.book);
		if (report.boreholes.length) {
			append(this.list, $('.soil-list-heading', undefined, localize('soil.boreholes', "Boreholes")));
		}
		report.boreholes.forEach((borehole, index) => {
			const siteClass = this.resultOf(borehole)?.siteClass?.class;
			const detail = siteClass
				? localize('soil.listDetailClass', "{0} m · {1}", formatNumber(boreholeDepth(borehole) / 1000, 1), siteClass)
				: borehole.layers.length === 1
					? localize('soil.listDetailOne', "{0} m · 1 layer", formatNumber(boreholeDepth(borehole) / 1000, 1))
					: localize('soil.listDetail', "{0} m · {1} layers", formatNumber(boreholeDepth(borehole) / 1000, 1), borehole.layers.length);
			item(index, borehole.id || localize('soil.unnamed', "(no id)"), detail, Codicon.circleSmallFilled);
		});
	}

	private onListKey(e: KeyboardEvent): void {
		// The report, then the boreholes: -1 stands for the report.
		const count = this.report?.boreholes.length ?? 0;
		const index = this.selected ?? -1;
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			const next = Math.max(-1, Math.min(count - 1, index + (e.key === 'ArrowDown' ? 1 : -1)));
			this.select(next < 0 ? undefined : next);
			this.list.focus();
		}
	}

	// ───────────────────────────── views ─────────────────────────────

	private renderView(): void {
		this.viewDisposables.clear();
		this.inputs.clear();
		const scroll = this.viewElement.scrollTop;
		clearNode(this.viewElement);
		this.viewElement.className = `soil-view ${this.view}`;
		this.lastSize = `${this.viewElement.clientWidth}x${this.viewElement.clientHeight}`;
		const report = this.report;
		if (!report || !report.boreholes.length) {
			return;
		}
		switch (this.view) {
			case 'log': this.renderLogView(report); break;
			case 'data': this.renderDataView(report); break;
			case 'results': this.renderResultsView(report); break;
		}
		this.viewElement.scrollTop = scroll;
		this.renderProblems();
	}

	private renderLegend(container: HTMLElement, report: ISoilReport, results: boolean): void {
		const legend = append(container, $('.soil-legend'));
		const used = SOIL_TYPES.filter(type => report.boreholes.some(b => b.layers.some(l => l.soilType === type)));
		for (const type of used) {
			const item = append(legend, $('span.soil-legend-item'));
			appendSoilSwatch(item, this.patternPrefix, type);
			append(item, $('span', undefined, soilTypeLabel(type)));
		}
		append(legend, $('span.soil-legend-gap'));
		const water = append(legend, $('span.soil-legend-item.water'));
		append(water, $('span.soil-legend-mark', undefined, '▽'));
		append(water, $('span', undefined, localize('soil.legendWater', "Water table")));
		const n = append(legend, $('span.soil-legend-item.n'));
		append(n, $('span.soil-legend-mark', undefined, '●'));
		append(n, $('span', undefined, localize('soil.legendN', "SPT N")));
		if (results) {
			const n60 = append(legend, $('span.soil-legend-item.n60'));
			append(n60, $('span.soil-legend-mark', undefined, '■'));
			append(n60, $('span', undefined, localize('soil.legendN60', "N60 (hammer energy {0}%)", formatNumber(report.design.hammerEnergy ?? DESIGN_DEFAULTS.hammerEnergy))));
		}
	}

	private renderLogView(report: ISoilReport): void {
		const borehole = this.borehole;
		const width = Math.max(0, this.viewElement.clientWidth - 40);
		const height = Math.max(0, this.viewElement.clientHeight - 116);
		const fence = this.fence || !borehole;
		const header = append(this.viewElement, $('.soil-view-header'));
		if (fence) {
			append(header, $('span.soil-view-title', undefined, localize('soil.fenceTitle', "All boreholes")));
			append(header, $('span.soil-view-subtitle', undefined, localize('soil.fenceSubtitle', "on the project datum; click one to open its log")));
		} else {
			append(header, $('span.soil-view-title', undefined, borehole.id));
			const parts = [localize('soil.logDepth', "{0} m deep", formatNumber(boreholeDepth(borehole) / 1000, 2))];
			if (typeof borehole.waterTable === 'number') {
				parts.push(localize('soil.logWater', "water table {0} m", formatNumber(borehole.waterTable / 1000, 2)));
			}
			parts.push(localize('soil.logGround', "ground level {0} m", formatNumber(boreholeGround(report, borehole) / 1000, 2)));
			append(header, $('span.soil-view-subtitle', undefined, parts.join(' · ')));
		}
		const result = borehole ? this.resultOf(borehole) : undefined;
		this.renderLegend(this.viewElement, report, !fence && !!result?.spt?.some(s => typeof s.N60 === 'number'));
		const canvas = append(this.viewElement, $('.soil-canvas'));
		if (fence) {
			renderFence(canvas, report, { width, height, patternPrefix: this.patternPrefix, selected: this.selected, onSelect: index => this.openLog(index) });
		} else {
			renderBoreholeLog(canvas, report, borehole, { width, height, patternPrefix: this.patternPrefix, result, hammerEnergy: report.design.hammerEnergy });
		}
	}

	// ───────────────────────────── data view ─────────────────────────────

	private renderDataView(report: ISoilReport): void {
		const borehole = this.borehole;
		if (!borehole) {
			this.renderBoreholeSummary(report);
			return;
		}
		const header = append(this.viewElement, $('.soil-view-header'));
		append(header, $('span.soil-view-title', undefined, borehole.id));
		append(header, $('span.soil-view-subtitle', undefined, localize('soil.dataSubtitle', "Depths in m below the borehole's ground; the borehole's position, water table and depth are in Properties.")));

		this.renderTable(borehole, 'layers', localize('soil.layers', "Layers"), LAYER_FIELDS, localize('soil.addLayer', "Add Layer"), () => {
			const last = [...borehole.layers].sort((a, b) => a.bottom - b.bottom).pop();
			const top = last?.bottom ?? 0;
			return { top, bottom: top + 3000, description: '', soilType: last?.soilType ?? 'clay' };
		});
		const sptResults = this.resultOf(borehole)?.spt ?? [];
		const sptAt = (row: { [key: string]: unknown }) => sptResults.find(s => Math.abs(s.depth - Number(row.depth)) <= 1);
		this.renderTable(borehole, 'spt', localize('soil.sptRecords', "SPT"), SPT_FIELDS, localize('soil.addSpt', "Add SPT Record"), () => {
			const last = [...borehole.spt].sort((a, b) => a.depth - b.depth).pop();
			return { depth: last ? last.depth + 1500 : 1500, N: last?.N ?? 0 };
		}, sptResults.length ? [
			{ label: 'N60', title: localize('soil.n60Title', "N corrected to 60% hammer energy (computed)"), value: (row: { [key: string]: unknown }) => sptAt(row)?.N60 },
			{ label: '(N1)60', title: localize('soil.n160Title', "N60 corrected to an effective overburden of 100 kPa (computed)"), value: (row: { [key: string]: unknown }) => sptAt(row)?.N160 },
		] : []);
		this.renderTable(borehole, 'samples', localize('soil.samples', "Lab samples"), SAMPLE_FIELDS, localize('soil.addSample', "Add Sample"), () => {
			const last = [...borehole.samples].sort((a, b) => a.depth - b.depth).pop();
			return { depth: last ? last.depth + 3000 : 1500, type: last?.type ?? 'UD' };
		});
	}

	/** With the report selected: one row per borehole, a click selects it. */
	private renderBoreholeSummary(report: ISoilReport): void {
		const header = append(this.viewElement, $('.soil-view-header'));
		append(header, $('span.soil-view-title', undefined, localize('soil.allBoreholes', "Boreholes")));
		append(header, $('span.soil-view-subtitle', undefined, localize('soil.summarySubtitle', "Select a borehole to edit its layers, SPT records and lab samples.")));
		const table = append(this.viewElement, $('table.soil-table.soil-summary'));
		const head = append(append(table, $('thead')), $('tr'));
		for (const [label, unit] of [[localize('soil.f.id', "ID"), ''], ['X', 'm'], ['Y', 'm'], [localize('soil.f.groundLevel', "Ground level"), 'm'], [localize('soil.f.waterTable', "Water table"), 'm'], [localize('soil.f.depthShort', "Depth"), 'm'], [localize('soil.layers', "Layers"), ''], [localize('soil.sptRecords', "SPT"), ''], [localize('soil.samples', "Lab samples"), '']]) {
			const th = append(head, $(unit || label !== localize('soil.f.id', "ID") ? 'th.number' : 'th'));
			append(th, $('span', undefined, label));
			if (unit) {
				append(th, $('span.soil-unit', undefined, unit));
			}
		}
		const body = append(table, $('tbody'));
		report.boreholes.forEach((borehole, index) => {
			const row = append(body, $('tr.soil-summary-row', { tabIndex: 0 }));
			const cells = [
				borehole.id,
				formatNumber(borehole.x / 1000, 2),
				formatNumber(borehole.y / 1000, 2),
				formatNumber(boreholeGround(report, borehole) / 1000, 2),
				typeof borehole.waterTable === 'number' ? formatNumber(borehole.waterTable / 1000, 2) : '—',
				formatNumber(boreholeDepth(borehole) / 1000, 2),
				String(borehole.layers.length), String(borehole.spt.length), String(borehole.samples.length),
			];
			cells.forEach((text, i) => append(row, $(i ? 'td.number' : 'td', undefined, text)));
			this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.select(index)));
			this.viewDisposables.add(addDisposableListener(row, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter') {
					this.select(index);
				}
			}));
		});
	}

	private renderTable(
		borehole: IBorehole,
		list: RowList,
		title: string,
		fields: readonly IFieldSpec[],
		addLabel: string,
		create: () => { [key: string]: unknown },
		computed: readonly { readonly label: string; readonly title: string; readonly value: (row: { [key: string]: unknown }) => number | undefined }[] = [],
	): void {
		const rows = borehole[list] as { [key: string]: unknown }[];
		const boreholeIndex = this.report?.boreholes.indexOf(borehole);
		const section = append(this.viewElement, $('.soil-section'));
		const heading = append(section, $('.soil-section-heading'));
		append(heading, $('span.soil-section-title', undefined, title));
		append(heading, $('span.soil-section-count', undefined, String(rows.length)));
		const add = append(heading, $<HTMLButtonElement>('button.soil-add', { type: 'button' }));
		append(add, $(ThemeIcon.asCSSSelector(Codicon.add)));
		append(add, $('span', undefined, addLabel));
		this.viewDisposables.add(addDisposableListener(add, EventType.CLICK, () => {
			rows.push(create());
			if (list !== 'samples') {
				rows.sort((a, b) => Number(list === 'layers' ? a.top : a.depth) - Number(list === 'layers' ? b.top : b.depth));
			}
			this.changed(true);
			const index = rows.length - 1;
			this.inputs.get(this.problemKey(boreholeIndex, `${list}.${index}.${fields[0].key}`))?.focus();
		}));

		const scroller = append(section, $('.soil-table-scroll'));
		const width = fields.reduce((sum, field) => sum + (field.width ?? 64), 0) + computed.length * 60 + 28;
		const table = append(scroller, $('table.soil-table', { 'aria-label': title, style: `width: ${width}px` }));
		const colgroup = append(table, $('colgroup'));
		const head = append(append(table, $('thead')), $('tr'));
		for (const field of fields) {
			append(colgroup, $('col', { style: `width: ${field.width ?? 64}px` }));
			const th = append(head, $(field.kind === 'text' || field.kind === 'soilType' ? 'th' : 'th.number', { title: field.title ?? '' }));
			append(th, $('span', undefined, field.label));
			if (field.unit) {
				append(th, $('span.soil-unit', undefined, field.unit));
			}
		}
		for (const column of computed) {
			append(colgroup, $('col', { style: 'width: 60px' }));
			const th = append(head, $('th.computed', { title: column.title }));
			append(th, $('span', undefined, column.label));
		}
		append(colgroup, $('col', { style: 'width: 28px' }));
		append(head, $('th'));
		const body = append(table, $('tbody'));
		rows.forEach((row, index) => {
			const tr = append(body, $('tr'));
			for (const field of fields) {
				const td = append(tr, $('td'));
				append(td, this.createInput(field, row[field.key], value => {
					if (value === undefined) {
						delete row[field.key];
					} else {
						row[field.key] = value;
					}
					this.changed(field.kind === 'soilType');
				}, this.problemKey(boreholeIndex, `${list}.${index}.${field.key}`)));
			}
			for (const column of computed) {
				const value = column.value(row);
				append(tr, $('td.number.computed', undefined, typeof value === 'number' ? formatNumber(value, 1) : ''));
			}
			const remove = append(append(tr, $('td.soil-row-actions')), $<HTMLButtonElement>('button.soil-remove', { type: 'button', title: localize('soil.removeRow', "Remove"), 'aria-label': localize('soil.removeRow', "Remove") }));
			append(remove, $(ThemeIcon.asCSSSelector(Codicon.trash)));
			this.viewDisposables.add(addDisposableListener(remove, EventType.CLICK, () => {
				rows.splice(index, 1);
				this.changed(true);
			}));
		});
		if (!rows.length) {
			append(append(body, $('tr')), $('td.soil-muted', { colspan: String(fields.length + computed.length + 1) }, localize('soil.noRows', "None yet.")));
		}
	}

	private problemKey(boreholeIndex: number | undefined, path: string): string {
		return `${boreholeIndex ?? ''}|${path}`;
	}

	/**
	 * An input for a field: what the engineer types is checked at once; a valid value is stored
	 * (and saved after a pause), an invalid one is marked and not stored.
	 */
	private createInput(field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key?: string, placeholder?: string): HTMLElement {
		if (field.kind === 'soilType') {
			const select = $<HTMLSelectElement>('select.soil-select', { 'aria-label': field.label });
			for (const type of SOIL_TYPES) {
				const option = append(select, $<HTMLOptionElement>('option', { value: type }, soilTypeLabel(type)));
				option.selected = type === value;
			}
			this.inputStore.add(addDisposableListener(select, EventType.CHANGE, () => store(select.value)));
			if (key) {
				this.inputMap.set(key, select);
			}
			return select;
		}
		const numeric = field.kind !== 'text';
		const input = $<HTMLInputElement>(`input.soil-input${numeric ? '.number' : ''}`, { type: 'text', spellcheck: 'false', 'aria-label': field.unit ? `${field.label} (${field.unit})` : field.label });
		input.value = formatField(field, value);
		if (placeholder) {
			input.placeholder = placeholder;
		}
		const disposables = this.inputStore;
		disposables.add(addDisposableListener(input, EventType.INPUT, () => {
			const parsed = parseField(field, input.value);
			input.classList.toggle('invalid', !!parsed.error);
			input.title = parsed.error ?? '';
			input.setAttribute('aria-invalid', String(!!parsed.error));
			if (!parsed.error) {
				store(parsed.value);
			}
		}));
		disposables.add(addDisposableListener(input, EventType.BLUR, () => {
			if (!input.classList.contains('invalid')) {
				this.flush();
			}
		}));
		if (key) {
			this.inputMap.set(key, input);
		}
		return input;
	}

	/** Where the listeners of the inputs being created go: the properties panel's store, or the view's. */
	private get inputStore(): DisposableStore {
		return this.renderingProperties ? this.propertiesDisposables : this.viewDisposables;
	}

	private get inputMap(): Map<string, HTMLElement> {
		return this.renderingProperties ? this.propertyInputs : this.inputs;
	}

	/** Marks the inputs that a check found a problem in (without re-rendering, so typing keeps focus). */
	private renderProblems(): void {
		for (const [key, input] of [...this.inputs, ...this.propertyInputs]) {
			if (input.classList.contains('invalid')) {
				continue;
			}
			const [index, path] = key.split('|');
			const problem = this.problems.find(p => String(p.index ?? '') === index && p.path === path);
			input.classList.toggle('warning', !!problem);
			input.title = problem?.message ?? '';
		}
	}

	// ───────────────────────────── results view ─────────────────────────────

	private renderResultsView(report: ISoilReport): void {
		const view = this.viewElement;
		if (this.resultsState === 'missing' || this.resultsState === 'error' || this.resultsState === 'computing' && !this.results) {
			const state = append(view, $('.soil-results-state'));
			const icon = this.resultsState === 'computing' ? ThemeIcon.modify(Codicon.loading, 'spin') : this.resultsState === 'error' ? Codicon.warning : Codicon.debugDisconnect;
			append(state, $(`span.soil-results-state-icon${ThemeIcon.asCSSSelector(icon)}`));
			append(state, $('.soil-results-state-title', undefined, this.resultsState === 'computing'
				? localize('soil.computing', "Computing the results...")
				: this.resultsState === 'error' ? localize('soil.computeFailed', "The results could not be computed")
					: localize('soil.backendMissing', "Backend not available")));
			append(state, $('.soil-results-state-text', undefined, this.resultsState === 'error'
				? this.resultsError ?? ''
				: this.resultsState === 'missing' ? localize('soil.backendMissingText', "The site class, bearing capacity, liquefaction screening and pile parameters are computed by the SAEngine Python backend, which is not running in this window. The boreholes can still be edited; the results appear once the backend is available.") : ''));
			return;
		}
		const results = this.results;
		if (!results) {
			return;
		}
		const header = append(view, $('.soil-view-header'));
		append(header, $('span.soil-view-title', undefined, localize('soil.resultsTitle', "Results")));
		append(header, $('span.soil-view-subtitle', undefined, localize('soil.resultsSubtitle', "Computed from the boreholes and the project settings; not stored in the report.")));

		this.renderBasis(view, report, results);
		const flags = this.renderSiteClass(view, report, results);
		this.renderBearing(view, report, results);
		this.renderSettlement(view, report, results);
		this.renderLiquefaction(view, report, results);
		this.renderSubgrade(view, report);
		this.renderPiles(view, report);

		// A note that repeats a site class flag keeps only what it adds to it.
		const notes = [...(results.notes ?? []).map(n => {
			const flag = flags.find(f => f.note && n.startsWith(f.note));
			return flag ? n.slice(flag.note.length).trim() : n;
		}).filter(Boolean), ...this.boreholeNotes()];
		if (results.problems?.length || notes.length) {
			const section = this.resultSection(view, localize('soil.resultNotes', "Notes"));
			for (const problem of results.problems ?? []) {
				append(section, $('p.soil-note.warning', undefined, problem));
			}
			for (const note of notes) {
				append(section, $('p.soil-note', undefined, note));
			}
		}
	}

	private resultSection(view: HTMLElement, title: string, detail?: string): HTMLElement {
		const section = append(view, $('.soil-section.result'));
		const heading = append(section, $('.soil-section-heading'));
		append(heading, $('span.soil-section-title', undefined, title));
		if (detail) {
			append(heading, $('span.soil-section-detail', undefined, detail));
		}
		return section;
	}

	private simpleTable(container: HTMLElement, headers: readonly (readonly [string, string?])[], rows: readonly (readonly string[])[], numeric: (column: number) => boolean = column => column > 0): HTMLTableElement {
		const table = append(container, $<HTMLTableElement>('table.soil-table.soil-result-table'));
		const head = append(append(table, $('thead')), $('tr'));
		headers.forEach(([label, unit], column) => {
			const th = append(head, $(numeric(column) ? 'th.number' : 'th'));
			append(th, $('span', undefined, label));
			if (unit) {
				append(th, $('span.soil-unit', undefined, unit));
			}
		});
		const body = append(table, $('tbody'));
		for (const row of rows) {
			const tr = append(body, $('tr'));
			row.forEach((text, column) => append(tr, $(numeric(column) ? 'td.number' : 'td', undefined, text)));
		}
		return table;
	}

	/** What the results were computed with: the practice, the liquefaction method, amax and its source. */
	private renderBasis(view: HTMLElement, report: ISoilReport, results: ISoilResults): void {
		const section = this.resultSection(view, localize('soil.basis', "Basis"), localize('soil.basisDetail', "the options and the earthquake the results below were computed with"));
		const list = append(section, $('dl.soil-basis'));
		for (const row of resultsBasis(report.design, results)) {
			append(list, $('dt', undefined, row.label));
			const value = append(list, $('dd'));
			append(value, $('span.soil-basis-value', undefined, row.value));
			if (row.detail) {
				append(value, $('span.soil-basis-detail', undefined, row.detail));
			}
		}
	}

	/** The site class, its averages per borehole and the S1 / S2 warnings; returns the warnings shown. */
	private renderSiteClass(view: HTMLElement, report: ISoilReport, results: ISoilResults): readonly ISiteClassFlag[] {
		const section = this.resultSection(view, localize('soil.siteClass', "Site class"), localize('soil.siteClassDetail', "BNBC 2020 Table 6.2.13, harmonic mean SPT N or undrained strength of the top 30 m"));
		const governing = results.siteClass;
		if (governing) {
			const tile = append(section, $('.soil-tile'));
			append(tile, $('span.soil-tile-value', undefined, governing.class));
			const text = append(tile, $('.soil-tile-text'));
			append(text, $('span.soil-tile-title', undefined, BNBC.siteClasses[governing.class] ?? localize('soil.siteClassNamed', "Site class {0}", governing.class)));
			append(text, $('span.soil-tile-detail', undefined, this.averageText(governing.nBar, governing.suBar, governing.depth, governing.borehole)));
			if (governing.note) {
				append(text, $('span.soil-tile-detail', undefined, governing.note));
			}
		}
		const flags = siteFlagsOf(results);
		for (const flag of flags) {
			const row = append(section, $('.soil-flag', { role: 'note' }));
			append(row, $(`span.soil-flag-icon${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			const text = append(row, $('.soil-flag-text'));
			// The backend's note says it all; a flag the editor derived gets the code's meaning.
			append(text, $('span.soil-flag-title', undefined, flag.note || siteFlagMeaning(flag.class) || localize('soil.flagOther', "{0} possible.", flag.class)));
			if (flag.boreholes?.length) {
				append(text, $('span.soil-flag-detail', undefined, localize('soil.flagBoreholes', "Boreholes: {0}.", flag.boreholes.join(', '))));
			}
		}
		const rows = report.boreholes.map(b => {
			const site = this.resultOf(b)?.siteClass;
			return [b.id, site?.class ?? '—', typeof site?.nBar === 'number' ? formatNumber(site.nBar, 1) : '—', typeof site?.suBar === 'number' ? formatNumber(site.suBar, 0) : '—', typeof site?.depth === 'number' ? formatNumber(site.depth / 1000, 1) : '—'];
		});
		this.simpleTable(section, [[localize('soil.borehole', "Borehole")], [localize('soil.class', "Class")], ['N̄'], ['s̄u', 'kPa'], [localize('soil.over', "Over"), 'm']], rows, column => column > 1);
		return flags;
	}

	/** The reference footing's settlement per borehole, beside BNBC 2020 Table 6.3.8's permissible settlement when the backend gives it. */
	private renderSettlement(view: HTMLElement, report: ISoilReport, results: ISoilResults): void {
		const rows = (results.boreholes ?? []).filter(b => b.settlement);
		if (!rows.length) {
			return;
		}
		const permissibleOf = (b: IBoreholeResult) => b.settlement?.permissible ?? results.permissibleSettlement;
		const anyPermissible = rows.some(b => typeof permissibleOf(b) === 'number');
		const limit = report.design.allowableSettlement ?? DESIGN_DEFAULTS.allowableSettlement;
		const section = this.resultSection(view, localize('soil.settlement', "Settlement"), localize('soil.settlementDetail', "reference footing under its qa · design limit {0} mm", formatNumber(limit)));
		const mm = localize('soil.unit.mm', "mm");
		const headers: (readonly [string, string?])[] = [
			[localize('soil.borehole', "Borehole")], ['B', 'm'], ['Df', 'm'], ['q', 'kPa'],
			[localize('soil.immediate', "Immediate"), mm], [localize('soil.consolidation', "Consolidation"), mm], [localize('soil.total', "Total"), mm],
		];
		if (anyPermissible) {
			headers.push([localize('soil.permissible', "Permissible (BNBC Table 6.3.8)"), mm]);
		}
		const dash = (value: number | undefined, decimals: number) => typeof value === 'number' ? formatNumber(value, decimals) : '—';
		const table = this.simpleTable(section, headers, rows.map(b => {
			const s = b.settlement!;
			const cells = [b.id, dash(s.B === undefined ? undefined : s.B / 1000, 2), dash(s.Df === undefined ? undefined : s.Df / 1000, 2), dash(s.q, 0), dash(s.immediate, 1), dash(s.consolidation, 1), dash(s.total, 1)];
			if (anyPermissible) {
				cells.push(dash(permissibleOf(b), 0));
			}
			return cells;
		}));
		rows.forEach((b, i) => {
			const permissible = permissibleOf(b);
			table.tBodies[0]?.rows[i]?.classList.toggle('soil-over-limit', typeof permissible === 'number' && b.settlement!.total > permissible);
		});
		const source = results.permissibleSettlementSource ?? rows.map(b => b.settlement?.permissibleSource).find(Boolean);
		if (source) {
			append(section, $('p.soil-note', undefined, source));
		}
	}

	private averageText(nBar: number | null | undefined, suBar: number | null | undefined, depth: number | undefined, borehole: string | undefined): string {
		const parts: string[] = [];
		if (typeof nBar === 'number') {
			parts.push(localize('soil.nBar', "N̄ {0}", formatNumber(nBar, 1)));
		}
		if (typeof suBar === 'number') {
			parts.push(localize('soil.suBar', "s̄u {0} kPa", formatNumber(suBar, 0)));
		}
		if (typeof depth === 'number') {
			parts.push(localize('soil.overDepth', "over {0} m", formatNumber(depth / 1000, 1)));
		}
		if (borehole) {
			parts.push(localize('soil.governedBy', "governed by {0}", borehole));
		}
		return parts.join(' · ');
	}

	/** The selected borehole's table, or with the report selected the lowest of all boreholes. */
	private renderBearing(view: HTMLElement, report: ISoilReport, results: ISoilResults): void {
		const own = this.borehole ? this.resultOf(this.borehole)?.bearing : undefined;
		const bearing: IBearingResult | undefined = own?.cells.length ? own : results.bearing;
		if (!bearing?.cells.length) {
			return;
		}
		const design = report.design;
		const which = bearing === own && this.borehole
			? localize('soil.bearingOf', "{0}; select Report for the lowest of all boreholes", this.borehole.id)
			: localize('soil.bearingAll', "the lowest of the {0} boreholes", report.boreholes.length);
		const section = this.resultSection(view, localize('soil.bearing', "Allowable bearing pressure"), localize('soil.bearingDetail', "net, kPa · FS {0} · settlement ≤ {1} mm · {2}",
			formatNumber(design.factorOfSafety ?? DESIGN_DEFAULTS.factorOfSafety), formatNumber(design.allowableSettlement ?? DESIGN_DEFAULTS.allowableSettlement), which));
		const widths = [...new Set(bearing.cells.map(c => c.B))].sort((a, b) => a - b);
		const depths = [...new Set(bearing.cells.map(c => c.Df))].sort((a, b) => a - b);
		const table = append(section, $('table.soil-table.soil-bearing'));
		const head = append(append(table, $('thead')), $('tr'));
		const corner = append(head, $('th'));
		append(corner, $('span', undefined, localize('soil.dfB', "Df \\ B")));
		append(corner, $('span.soil-unit', undefined, 'm'));
		for (const width of widths) {
			append(head, $('th.number', undefined, formatNumber(width / 1000, 2)));
		}
		const body = append(table, $('tbody'));
		const governing = bearing.governing;
		let missing = false;
		for (const depth of depths) {
			const tr = append(body, $('tr'));
			append(tr, $('th.row', undefined, formatNumber(depth / 1000, 2)));
			for (const width of widths) {
				const cell = bearing.cells.find(c => c.B === width && c.Df === depth);
				const td = append(tr, $('td.number'));
				if (!cell) {
					continue;
				}
				if (typeof cell.qa !== 'number') {
					missing = true;
					append(td, $('span.soil-muted', undefined, '—'));
				} else {
					append(td, $('span', undefined, formatNumber(cell.qa, 0)));
					if (cell.governs === 'settlement') {
						append(td, $('sup.soil-governs', undefined, 's'));
					}
				}
				td.title = this.bearingTitle(cell);
				td.classList.toggle('governing', !!governing && governing.B === cell.B && governing.Df === cell.Df);
			}
		}
		const notes = [localize('soil.bearingLegend', "s: settlement governs; otherwise shear (bearing capacity / FS).")];
		if (missing) {
			notes.push(localize('soil.bearingMissing', "—: no value (a layer at that depth has no strength; see the notes)."));
		}
		if (governing) {
			notes.push(localize('soil.bearingGoverning', "Highlighted: {0}{1}.", bearingSummary(governing), governing.borehole && bearing !== own ? ` (${governing.borehole})` : ''));
		}
		append(section, $('p.soil-note', undefined, notes.join(' ')));
		if (bearing.method) {
			append(section, $('p.soil-note', undefined, bearing.method));
		}
	}

	private bearingTitle(cell: IBearingCell): string {
		const parts = [bearingSummary(cell)];
		if (typeof cell.qBearing === 'number') {
			parts.push(localize('soil.qBearing', "shear: bearing capacity / FS {0} kPa", formatNumber(cell.qBearing, 0)));
		}
		if (typeof cell.qSettlement === 'number') {
			parts.push(localize('soil.qSettlement', "settlement limit {0} kPa", formatNumber(cell.qSettlement, 0)));
		}
		if (cell.borehole) {
			parts.push(localize('soil.cellBorehole', "from {0}", cell.borehole));
		}
		return parts.join('\n');
	}

	/** "6–11.5 m silt, 11.5–21 m sand", or "none". */
	private liquefiableText(result: IBoreholeResult): string {
		const liquefaction = result.liquefaction;
		const layers = (liquefaction?.liquefiableLayers ?? []).map(l => localize('soil.liquefiableLayer', "{0}–{1} m{2}", formatNumber(l.top / 1000, 1), formatNumber(l.bottom / 1000, 1), l.soilType ? ` ${soilTypeLabel(l.soilType).toLowerCase()}` : ''));
		if (layers.length) {
			return layers.join(', ');
		}
		const points = (liquefaction?.points ?? []).filter(p => p.liquefiable).map(p => formatNumber(p.depth / 1000, 1));
		return points.length ? localize('soil.liquefiablePoints', "at {0} m", points.join(', ')) : localize('soil.none', "none");
	}

	private renderLiquefaction(view: HTMLElement, report: ISoilReport, results: ISoilResults): void {
		const boreholes = (results.boreholes ?? []).filter(b => b.liquefaction);
		if (!boreholes.length) {
			return;
		}
		const pga = typeof results.pga === 'number' ? localize('soil.pga', "amax {0} g", formatNumber(results.pga, 3)) : undefined;
		const magnitude = report.design.liquefaction?.magnitude ?? DESIGN_DEFAULTS.magnitude;
		const section = this.resultSection(view, localize('soil.liquefaction', "Liquefaction screening"),
			[localize('soil.magnitude', "Mw {0}", formatNumber(magnitude, 1)), pga].filter(Boolean).join(' · '));
		const row = append(section, $('.soil-liquefaction-row'));
		const charted = boreholes.filter(b => b.liquefaction!.points.some(p => typeof p.FS === 'number'));
		if (charted.length) {
			const chart = append(row, $('.soil-chart'));
			const maxDepth = Math.max(...report.boreholes.map(b => boreholeDepth(b)), 1000);
			renderLiquefactionChart(chart, charted, { width: Math.min(460, Math.max(280, this.viewElement.clientWidth * 0.45)), height: 340, maxDepth });
			const legend = append(chart, $('.soil-series-legend'));
			charted.forEach((b, i) => {
				const item = append(legend, $('span.soil-legend-item'));
				append(item, $(`span.soil-series-dot.soil-series-${i % 6}`));
				append(item, $('span', undefined, b.id));
			});
		}
		const rows = boreholes.map(b => {
			const liquefaction = b.liquefaction!;
			const lpi = liquefaction.LPI;
			const minFs = Math.min(...liquefaction.points.map(p => typeof p.FS === 'number' ? p.FS : Infinity));
			return [b.id, Number.isFinite(minFs) ? formatNumber(minFs, 2) : '—', typeof lpi === 'number' ? formatNumber(lpi, 1) : '—', liquefaction.category ?? (typeof lpi === 'number' ? this.lpiRisk(lpi) : '—'), this.liquefiableText(b)];
		});
		const tables = append(row, $('.soil-liquefaction-tables'));
		const table = this.simpleTable(tables, [[localize('soil.borehole', "Borehole")], [localize('soil.minFs', "Min FS")], ['LPI'], [localize('soil.risk', "Risk")], [localize('soil.liquefiable', "Liquefiable")]], rows, column => column === 1 || column === 2);
		boreholes.forEach((b, i) => table.tBodies[0]?.rows[i]?.classList.toggle('soil-liquefiable-row', hasLiquefiable(b)));
		append(tables, $('p.soil-note', undefined, localize('soil.lpiNote', "LPI (Iwasaki et al. 1978); risk 0 very low, up to 5 low, 5 to 15 high, above 15 very high (Iwasaki et al. 1982). Screened: saturated, non-clay-like soil above 20 m.")));
		const method = boreholes.find(b => b.liquefaction?.method)?.liquefaction?.method;
		if (method) {
			append(tables, $('p.soil-note', undefined, method));
		}
	}

	private lpiRisk(lpi: number): string {
		return lpi <= 0 ? localize('soil.risk.veryLow', "very low")
			: lpi <= 5 ? localize('soil.risk.low', "low")
				: lpi <= 15 ? localize('soil.risk.high', "high")
					: localize('soil.risk.veryHigh', "very high");
	}

	private renderSubgrade(view: HTMLElement, report: ISoilReport): void {
		const rows = report.boreholes.map(b => ({ b, r: this.resultOf(b) })).filter(({ r }) => typeof r?.ks === 'number');
		if (!rows.length) {
			return;
		}
		const method = rows.find(({ r }) => r?.ksMethod)?.r?.ksMethod;
		const section = this.resultSection(view, localize('soil.ks', "Modulus of subgrade reaction"), method);
		this.simpleTable(section, [[localize('soil.borehole', "Borehole")], ['ks', localize('soil.unit.knm3', "kN/m³")]], rows.map(({ b, r }) => [b.id, formatNumber(r!.ks!, 0)]));
		const note = rows.find(({ r }) => r?.ksNote)?.r?.ksNote;
		if (note) {
			append(section, $('p.soil-note', undefined, note));
		}
	}

	private renderPiles(view: HTMLElement, report: ISoilReport): void {
		const borehole = this.borehole ?? report.boreholes.find(b => this.resultOf(b)?.piles?.length);
		const piles = borehole ? this.resultOf(borehole)?.piles : undefined;
		if (!borehole || !piles?.length) {
			return;
		}
		const section = this.resultSection(view, localize('soil.piles', "Pile design parameters"), localize('soil.pilesDetail', "{0} · per layer, for the substructure; select another borehole on the left", borehole.id));
		this.simpleTable(section, [
			[localize('soil.f.top', "Top"), 'm'], [localize('soil.f.bottom', "Bottom"), 'm'], [localize('soil.f.soilType', "Soil type")],
			[localize('soil.fs', "Skin friction fs"), 'kPa'], [localize('soil.qb', "End bearing qb"), 'kPa'], [localize('soil.method', "Method")],
		], piles.map(p => [
			formatNumber(p.top / 1000, 2), formatNumber(p.bottom / 1000, 2), soilTypeLabel(p.soilType),
			typeof p.fs === 'number' ? formatNumber(p.fs, 0) : '—', typeof p.qb === 'number' ? formatNumber(p.qb, 0) : '—', p.method ?? p.note ?? '',
		]), column => column < 2 || column === 3 || column === 4);
	}

	/** The notes the backend gives per borehole (missing strengths, assumed fines, ...). */
	private boreholeNotes(): string[] {
		const notes: string[] = [];
		for (const result of this.results?.boreholes ?? []) {
			const own = [...result.bearing?.notes ?? [], ...(result.liquefaction?.notes ?? []).filter(n => !n.startsWith('amax')), ...result.notes ?? []];
			for (const note of new Set(own)) {
				notes.push(`${result.id}: ${note}`);
			}
		}
		return notes;
	}

	// ───────────────────────────── properties panel ─────────────────────────────

	private renderProperties(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		const report = this.report;
		// Keep the focused input when only results changed. When the file was reloaded (undo, redo,
		// revert, an external edit) the inputs write into the old report object: rebuild them and
		// give the focus back to the same field.
		const active = panel.ownerDocument.activeElement;
		const focused = active && panel.contains(active) && (isHTMLInputElement(active) || active.tagName === 'SELECT') ? active : undefined;
		const sameModel = this.propertiesFor?.report === report && this.propertiesFor?.selected === this.selected;
		if (focused && sameModel) {
			return;
		}
		const focusedKey = focused ? [...this.propertyInputs].find(([, input]) => input === focused)?.[0] : undefined;
		this.propertiesDisposables.clear();
		this.propertyInputs.clear();
		clearNode(panel);
		this.propertiesFor = { report, selected: this.selected };
		if (!report) {
			appendPropertyNote(panel, this.parseError ?? localize('soil.propsNone', "No soil report."));
			return;
		}
		this.renderingProperties = true;
		try {
			const borehole = this.borehole;
			if (borehole) {
				this.renderBoreholeProperties(panel, report, borehole);
			} else {
				this.renderReportProperties(panel, report);
			}
		} finally {
			this.renderingProperties = false;
		}
		const shown = this.problems.filter(p => this.selected === undefined || p.index === this.selected);
		if (shown.length) {
			appendPropertyHeading(panel, localize('soil.problems', "Problems ({0})", shown.length));
			for (const problem of shown) {
				appendPropertyNote(panel, problem.message).classList.add(problem.severity);
			}
		}
		this.renderProblems();
		if (focusedKey) {
			this.propertyInputs.get(focusedKey)?.focus();
		}
	}

	private propertyInput(panel: HTMLElement, field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key: string, placeholder?: string): void {
		const control = $('.soil-prop-control');
		append(control, this.createInput(field, value, store, key, placeholder));
		if (field.unit) {
			append(control, $('span.soil-prop-unit', undefined, field.unit));
		}
		const row = appendPropertyRow(panel, field.label, control);
		row.classList.add('soil-prop-row');
		if (field.title) {
			row.title = field.title;
		}
	}

	private renderBoreholeProperties(panel: HTMLElement, report: ISoilReport, borehole: IBorehole): void {
		appendPropertyHeading(panel, localize('soil.boreholeHeading', "Borehole {0}", borehole.id));
		for (const field of BOREHOLE_FIELDS) {
			const placeholder = field.key === 'groundLevel' ? formatNumber(report.groundLevel / 1000, 3) : undefined;
			this.propertyInput(panel, field, borehole[field.key], value => {
				// An id already in use is stored too: the check marks it (here and in the list), and
				// the borehole stays selectable because selection goes by position.
				if (value === undefined) {
					delete borehole[field.key];
				} else {
					borehole[field.key] = value;
				}
				this.changed(false);
			}, this.problemKey(this.selected, field.key), placeholder);
		}
		const result = this.resultOf(borehole);
		appendPropertyHeading(panel, localize('soil.contents', "Records"));
		appendPropertyRow(panel, localize('soil.layers', "Layers"), String(borehole.layers.length));
		appendPropertyRow(panel, localize('soil.sptRecords', "SPT"), String(borehole.spt.length));
		appendPropertyRow(panel, localize('soil.samples', "Lab samples"), String(borehole.samples.length));
		if (result) {
			appendPropertyHeading(panel, localize('soil.resultsTitle', "Results"));
			if (result.siteClass) {
				appendPropertyRow(panel, localize('soil.siteClass', "Site class"), result.siteClass.class);
				if (typeof result.siteClass.nBar === 'number') {
					appendPropertyRow(panel, 'N̄', formatNumber(result.siteClass.nBar, 1));
				}
			}
			if (result.settlement) {
				const permissible = result.settlement.permissible ?? this.results?.permissibleSettlement;
				appendPropertyRow(panel, localize('soil.settlement', "Settlement"), typeof permissible === 'number'
					? localize('soil.settlementPermissible', "{0} mm (permissible {1} mm)", formatNumber(result.settlement.total, 1), formatNumber(permissible, 0))
					: localize('soil.settlementValue', "{0} mm", formatNumber(result.settlement.total, 1)));
			}
			if (typeof result.ks === 'number') {
				appendPropertyRow(panel, 'ks', localize('soil.ksValue', "{0} kN/m³", formatNumber(result.ks, 0)));
			}
			if (typeof result.liquefaction?.LPI === 'number') {
				appendPropertyRow(panel, 'LPI', `${formatNumber(result.liquefaction.LPI, 1)} (${result.liquefaction.category ?? this.lpiRisk(result.liquefaction.LPI)})`);
			}
			if (result.liquefaction) {
				appendPropertyRow(panel, localize('soil.liquefiable', "Liquefiable"), this.liquefiableText(result));
			}
		}
	}

	private renderReportProperties(panel: HTMLElement, report: ISoilReport): void {
		appendPropertyHeading(panel, localize('soil.reportHeading', "Report"));
		for (const field of REPORT_FIELDS) {
			this.propertyInput(panel, field, report.report[field.key], value => {
				if (value === undefined) {
					delete report.report[field.key];
				} else {
					report.report[field.key] = value;
				}
				this.changed(false);
			}, `props|report.${field.key}`);
		}
		this.propertyInput(panel, { key: 'groundLevel', label: localize('soil.f.groundLevel', "Ground level"), unit: localize('soil.unit.m', "m"), kind: 'length', required: true, title: localize('soil.f.reportGroundTitle', "Elevation of the existing ground on the project datum, for boreholes without their own") },
			report.groundLevel, value => {
				report.groundLevel = typeof value === 'number' ? value : 0;
				this.changed(false);
			}, 'props|groundLevel');

		appendPropertyHeading(panel, localize('soil.designHeading', "Design"));
		const design = report.design;
		for (const spec of DESIGN_CHOICES) {
			this.choiceInput(panel, spec, design[spec.key], value => {
				(design as Record<string, unknown>)[spec.key] = value;
				this.changed(false);
				this.flush(); // a pick is complete: save and recompute without waiting for a blur
			});
		}
		const liquefaction = () => design.liquefaction ??= {};
		for (const field of DESIGN_FIELDS) {
			const isLiquefaction = field.key === 'magnitude' || field.key === 'pga';
			const value = isLiquefaction ? design.liquefaction?.[field.key] : design[field.key];
			const placeholder = field.key === 'pga' ? localize('soil.pgaPlaceholder', "from settings") : undefined;
			this.propertyInput(panel, field, value, next => {
				const target: { [key: string]: unknown } = isLiquefaction ? liquefaction() : design;
				if (next === undefined) {
					if (field.key === 'pga') {
						target.pga = null;
					} else {
						delete target[field.key];
					}
				} else {
					target[field.key] = next;
				}
				this.changed(false);
			}, `props|design.${field.key}`, placeholder);
		}
		appendPropertyNote(panel, localize('soil.designNote', "Empty values use the defaults: textbook practice, Idriss & Boulanger 2014, hammer energy 60%, factor of safety 3, settlement 25 mm, magnitude 7.5."));
	}

	/** A design option picked from a list; the row's hover says what each option does. */
	private choiceInput(panel: HTMLElement, spec: IChoiceSpec, value: unknown, store: (value: string) => void): void {
		const select = $<HTMLSelectElement>('select.soil-select.soil-prop-select', { 'aria-label': spec.label });
		const current = typeof value === 'string' && value ? value : spec.defaultValue;
		const options = spec.options.some(o => o.value === current) ? spec.options : [...spec.options, { value: current, label: current, title: '' }];
		for (const option of options) {
			const element = append(select, $<HTMLOptionElement>('option', { value: option.value }, option.label));
			element.title = option.title;
			element.selected = option.value === current;
		}
		this.propertiesDisposables.add(addDisposableListener(select, EventType.CHANGE, () => store(select.value)));
		this.propertyInputs.set(`props|design.${spec.key}`, select);
		const control = $('.soil-prop-control');
		append(control, select);
		const row = appendPropertyRow(panel, spec.label, control);
		row.classList.add('soil-prop-row');
		row.title = choiceTitle(spec);
	}

	// ───────────────────────────── status line ─────────────────────────────

	private renderStatus(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const report = this.report;
		if (!report) {
			frame.setStatus(this.parseError ? { severity: 'warning', text: this.parseError } : undefined);
			return;
		}
		if (!report.boreholes.length) {
			frame.setStatus({ text: localize('soil.statusEmpty', "No boreholes yet.") });
			return;
		}
		const parts = [soilSummary(report).replace(/^./, c => c.toUpperCase())];
		const results = this.results;
		if (this.resultsState === 'missing') {
			parts.push(localize('soil.statusNoBackend', "results need the backend"));
		} else if (results) {
			if (results.siteClass) {
				parts.push(localize('soil.statusSiteClass', "site class {0}", results.siteClass.class));
			}
			if (results.bearing?.governing) {
				parts.push(bearingSummary(results.bearing.governing));
			}
			const liquefiable = (results.boreholes ?? []).filter(hasLiquefiable).map(b => b.id);
			if (liquefiable.length) {
				parts.push(localize('soil.statusLiquefiable', "liquefiable layers in {0}", liquefiable.join(', ')));
			}
		} else if (this.resultsState === 'error') {
			parts.push(localize('soil.statusFailed', "results could not be computed"));
		}
		const errors = this.problems.filter(p => p.severity === 'error').length;
		const warnings = this.problems.length - errors;
		const status: IEditorFrameStatus = {
			text: parts.join('  ·  '),
			severity: errors ? 'error' : warnings || this.resultsState === 'error' ? 'warning' : undefined,
			busy: this.resultsState === 'computing',
			link: this.problems.length ? {
				label: localize('soil.statusProblems', "{0} problem(s)", this.problems.length),
				run: () => this.revealFirstProblem(),
			} : this.resultsState === 'ok' && this.view !== 'results' ? {
				label: localize('soil.statusShowResults', "Results"),
				run: () => this.showView('results'),
			} : undefined,
		};
		frame.setStatus(status);
	}

	private revealFirstProblem(): void {
		const problem = this.problems[0];
		if (!problem) {
			return;
		}
		this.selected = problem.index ?? this.selected;
		this.view = problem.path && problem.path.includes('.') ? 'data' : this.view;
		this.frame.setPropertiesVisible(true);
		this.render();
		const key = problem.path ? this.problemKey(problem.index, problem.path) : undefined;
		const input = key ? this.inputs.get(key) ?? this.propertyInputs.get(key) : undefined;
		input?.focus();
	}
}
