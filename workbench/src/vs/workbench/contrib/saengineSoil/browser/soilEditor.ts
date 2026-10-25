/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import './media/soilEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isHTMLInputElement } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { setProperty } from '../../../../base/common/jsonEdit.js';
import { Range } from '../../../../editor/common/core/range.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { BNBC } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import {
	BOREHOLE_FIELDS, bearingSummary, boreholeDepth, DuplicateChoice, duplicateIds, hasLabData, mergeBoreholes, terminationDepth, boreholePosition, boreholeGround, checkSoilReport, choiceTitle, DESIGN_CHOICES, DESIGN_DEFAULTS, DESIGN_FIELDS, formatField, formatNumber, hasLiquefiable, IBearingCell, IBearingResult, IBorehole, IBoreholeResult, IFieldSpec,
	ISoilComputeRequest, ISoilImportRequest, ISoilImportResult, ISoilProblem, ISoilReport, ISoilResults, ISoilTemplateRequest, ISoilTemplateResult, newBorehole, parseField,
	IChoiceSpec, ISiteClassFlag, parseSoilReport, readSoilResults, splitError, REPORT_FIELDS, resultsBasis, serializeSoilReport, SOIL_COMPUTE_COMMAND, SOIL_IMPORT_COMMAND, SOIL_TEMPLATE_COMMAND, SOIL_TYPES, siteFlagMeaning, siteFlagsOf, siltNeedsPlasticity, soilSummary, soilTypeLabel,
	GisFormat, ILatLon, IOpenInQgisRequest, IOpenInQgisResult, ISoilGisExportRequest, ISoilGisExportResult, ISoilGisImportRequest, ISoilGisImportResult, ISoilLocationRequest, ISoilLocationResult, ISoilSample, QgisProgramResult,
	MAP_TILE_ATTRIBUTION_SETTING, MAP_TILE_URL_SETTING, SOIL_GIS_EXPORT_COMMAND, SOIL_GIS_IMPORT_COMMAND, SOIL_LOCATION_COMMAND, SOIL_OPEN_IN_QGIS_COMMAND, SOIL_QGIS_PROGRAM_COMMAND,
} from './soilDocument.js';
import { SoilEditorInput } from './soilEditorInput.js';
import { canCreate, DEFAULT_VIEW, editBoreholeEntry, ENTRY_STEPS, EntryStep, entryProblems, entryStepOf, firstStepWithError, goToStep, IEntryProblem, IEntryState, newBoreholeEntry, nextStep, shownProblems, SoilView } from './soilEntry.js';
import { IGridState, newGridState, SoilGrid } from './soilGrid.js';
import { LabTest } from './soilLabTests.js';
import { SoilLabPanel } from './soilLabPanel.js';
import { appendSoilPatterns, appendSoilSwatch, renderBoreholeLog, renderFence, renderLiquefactionChart } from './soilLog.js';
import { IBnbcSuggestion, tileSource } from './soilMap.js';
import { IMapViewState, ISoilMapHost, SoilMapView } from './soilMapView.js';
import { SampleSheet, SPT_DRIVE, StrataSheet } from './soilSheet.js';

type View = SoilView;

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: 'log', label: localize('soil.viewLog', "Log"), icon: Codicon.layers },
	{ view: 'results', label: localize('soil.viewResults', "Results"), icon: Codicon.graphLine },
	{ view: 'map', label: localize('soil.viewMap', "Map"), icon: Codicon.globe },
];

/** The column groups of the sheets shown at first: the strength and consolidation of the strata are folded. */
const STRATA_COLLAPSED = ['weight', 'strength', 'index', 'consolidation'];
const SAMPLES_COLLAPSED = ['consolidation'];

/** The borehole's details on the entry screen, grouped as the consultant's log sheet heads its page. */
const DETAIL_GROUPS: readonly { readonly label: string; readonly fields: readonly string[] }[] = [
	{ label: localize('soil.entry.gBorehole', "Borehole"), fields: ['id', 'date', 'method'] },
	{ label: localize('soil.entry.gDepths', "Depths and levels"), fields: ['depth', 'waterTable', 'groundLevel'] },
	{ label: localize('soil.entry.gLocation', "Location"), fields: ['x', 'y', 'lat', 'lon', 'easting', 'northing'] },
];

/** The details the borehole cannot be created without. */
const REQUIRED_DETAILS = new Set(['id', 'depth']);

/** Below this editor width [px] the map takes the properties panel's room. */
const NARROW_WIDTH = 1500;

/** The state of the results: not asked yet, being computed, computed, or no backend / failed. */
type ResultsState = 'idle' | 'computing' | 'ok' | 'missing' | 'error';

let instanceCount = 0;

/**
 * The soil report (`01 Soil Report/soil-report.json`) on the shared editor frame. Boreholes are
 * listed on the left; a borehole is entered (and edited) on the entry screen, in the order of the
 * consultant's log sheet: details, strata, SPT and lab. The Log view draws the selected one
 * (strata, water table, SPT N against depth) or the fence of all of them, and the Results view
 * shows what the backend computes from them: the site class, the
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
	private view: View = DEFAULT_VIEW;
	private fence = false;
	/** The borehole entry screen, while it is open (it takes the place of the view). */
	private entry: IEntryState | undefined;
	/** What the entry screen focuses after its next render: its first field, or its grid. */
	private entryFocus = false;
	/** The parts of the entry screen that follow its problems without a render. */
	private entryParts: { title: HTMLElement; problems: HTMLElement; steps: Map<EntryStep, HTMLElement>; messages: Map<string, HTMLElement> } | undefined;
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
	/** The inputs of the entry screen by problem key ("0|depth": borehole index and path). */
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
	/** `06 BIM/bim.json`, read for the building's outline on the map (opened with the Map view). */
	private readonly bim = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private bimRequested = false;

	/** The log sheet's grids and the lab panel, rendered again on every edit with the same state. */
	private readonly grids: SoilGrid[] = [];
	private readonly gridStates = new Map<string, IGridState>();
	private readonly labGridStates = new Map<string, IGridState>();
	private readonly labDisposables = this._register(new DisposableStore());
	private labContainer: HTMLElement | undefined;
	private sampleSheet: SampleSheet | undefined;
	/** The sample whose lab tests are shown (kept by object, so it survives re-sorting). */
	private labSample: ISoilSample | undefined;
	private labTest: LabTest = 'grainSize';
	/** A render was skipped while a cell was being edited; done after the edit. */
	private renderPending = false;
	/** The results on screen are from before the last edit (dimmed until the new ones arrive). */
	private stale = false;
	/** The editor's width at the last layout [px]. */
	private layoutWidth = 0;
	/** The properties panel was hidden to make room (the entry screen, a narrow map). */
	private autoHidden = false;
	/** Whether the details (tracebacks) of the results' problems are shown. */
	private detailsShown = false;

	/** The site map: kept while the Map view shows, so the map is not built again on every edit. */
	private readonly mapView = this._register(new MutableDisposable<SoilMapView>());
	private readonly mapState: IMapViewState = { coordinateStyle: 'decimal' };
	private location: ISoilLocationResult | undefined;
	private locationState: 'idle' | 'computing' | 'ok' | 'missing' | 'error' = 'idle';
	private locationVersion = 0;
	private qgis: { readonly path: string; readonly version?: string } | undefined;
	private qgisAsked = false;
	private readonly locationScheduler = this._register(new RunOnceScheduler(() => void this.computeLocation(), 400));

	private readonly pendingRenderScheduler = this._register(new RunOnceScheduler(() => {
		if (this.renderPending) {
			this.renderView();
		}
	}, 100));

	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 300));
	private readonly computeScheduler = this._register(new RunOnceScheduler(() => void this.compute(), 700));
	private readonly layoutScheduler = this._register(new RunOnceScheduler(() => this.onMainResized(), 50));
	/** A borehole's lat/lon (or BTM) typed on the entry screen: its X and Y follow from the backend. */
	private readonly positionScheduler = this._register(new RunOnceScheduler(() => void this.updateDerivedPosition(), 600));

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
		@IOpenerService private readonly openerService: IOpenerService,
		@IDialogService private readonly dialogService: IDialogService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
	) {
		super(SoilEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.renderActions();
			}
			if ((e.affectsConfiguration(MAP_TILE_URL_SETTING) || e.affectsConfiguration(MAP_TILE_ATTRIBUTION_SETTING)) && this.view === 'map') {
				this.mapView.clear(); // the map is built again with the new tiles
				this.mapState.tilesFailed = false;
				this.renderView();
			}
		}));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			// The backend registers its commands when it starts: compute as soon as it can.
			if (id === SOIL_COMPUTE_COMMAND && this.resultsState === 'missing') {
				this.computeScheduler.schedule(0);
			}
			if (id === SOIL_LOCATION_COMMAND && this.locationState === 'missing') {
				this.locationScheduler.schedule(0);
			}
			if (id === SOIL_QGIS_PROGRAM_COMMAND) {
				this.qgisAsked = false;
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
		this.bim.clear();
		this.bimRequested = false;
		this.mapView.clear();
		this.model = undefined;
		this.results = undefined;
		this.resultsState = 'idle';
		this.location = undefined;
		this.locationState = 'idle';
		this.selected = undefined;
		this.entry = undefined;
		this.gridStates.clear();
		this.labSample = undefined;
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
				this.inputDisposables.add(settings.object.textEditorModel.onDidChangeContent(() => {
					this.computeScheduler.schedule();
					if (this.view === 'map') {
						this.locationScheduler.schedule(); // the BNBC suggestion follows the settings
					}
				}));
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
		this.bim.clear();
		this.mapView.clear();
		this.computeScheduler.cancel();
		this.locationScheduler.cancel();
		this.model = undefined;
		this.report = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.layoutWidth = dimension.width;
		this.frame.layout(dimension.width, dimension.height);
		this.autoProperties();
	}

	/**
	 * The properties panel makes room for the entry screen (whose grids need the width) and, on
	 * a narrow screen, for the map; it comes back after them unless the engineer changed it.
	 */
	private autoProperties(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const needsRoom = !!this.entry || this.view === 'map' && this.layoutWidth > 0 && this.layoutWidth < NARROW_WIDTH;
		if (needsRoom && frame.isPropertiesVisible && !this.autoHidden) {
			this.autoHidden = true;
			frame.setPropertiesVisible(false);
		} else if (!needsRoom && this.autoHidden) {
			this.autoHidden = false;
			frame.setPropertiesVisible(true);
		}
	}

	/** Dims the computed values until the computation for the latest edit comes back. */
	private markStale(): void {
		if (!this.stale && this.results) {
			this.stale = true;
			this.frame?.element.classList.add('soil-stale');
		}
	}

	private clearStale(): void {
		this.stale = false;
		this.frame?.element.classList.remove('soil-stale');
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
			if (this.entry && this.entry.index >= count) {
				this.entry = undefined; // undone: the borehole being entered is gone
			}
		}
		this.problems = this.report ? checkSoilReport(this.report) : [];
		this.markStale(); // undo, redo, revert: the results follow
		this.render();
		this.computeScheduler.schedule(this.resultsState === 'idle' ? 0 : undefined);
		if (this.view === 'map') {
			this.locationScheduler.schedule();
		}
	}

	/** The engineer picked "Report" in the list: keep it when the file reloads. */
	private reportSelectedOnPurpose = false;

	/** What the next commit does, for the "Undid ..." message (typing is committed after a pause). */
	private pendingLabel: string | undefined;
	/** What each undoable edit did, by the text model's alternative version id after it. */
	private readonly undoLabels = new Map<number, string>();

	/** Writes the report to the text model as one undoable edit; `label` says what it does. */
	private commit(label?: string): void {
		this.commitScheduler.cancel();
		const model = this.model;
		label ??= this.pendingLabel;
		this.pendingLabel = undefined;
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
		this.undoLabels.set(model.getAlternativeVersionId(), label ?? this.editLabel());
		this.markStale();
		this.computeScheduler.schedule();
		if (this.view === 'map') {
			this.locationScheduler.schedule();
		}
	}

	private flush(): void {
		if (this.commitScheduler.isScheduled()) {
			this.commit();
		}
	}

	/** What an edit without its own label changed: the selected borehole, or the report. */
	private editLabel(): string {
		const borehole = this.entry ? this.report?.boreholes[this.entry.index] : this.borehole;
		return borehole ? localize('soil.undo.editBorehole', "the edit of {0}", borehole.id) : localize('soil.undo.editReport', "the edit of the report");
	}

	/**
	 * Undo or redo of the file's edits (Ctrl+Z / Ctrl+Y anywhere in the editor but a text field),
	 * saying what was undone: a second undo never reverts an unrelated edit silently.
	 */
	async undoRedo(redo: boolean): Promise<void> {
		const model = this.model;
		const resource = this.resource;
		if (!model || !resource) {
			return;
		}
		this.flush();
		if (redo ? !this.undoRedoService.canRedo(resource) : !this.undoRedoService.canUndo(resource)) {
			this.notificationService.status(redo ? localize('soil.nothingToRedo', "Nothing to redo.") : localize('soil.nothingToUndo', "Nothing to undo."), { hideAfter: 3000 });
			return;
		}
		const before = this.undoLabels.get(model.getAlternativeVersionId());
		await (redo ? this.undoRedoService.redo(resource) : this.undoRedoService.undo(resource));
		const label = (redo ? this.undoLabels.get(model.getAlternativeVersionId()) : before) ?? localize('soil.undo.anEdit', "an edit of the soil report");
		this.notificationService.info(redo ? localize('soil.redid', "Redid {0}.", label) : localize('soil.undid', "Undid {0}.", label));
	}

	/** After an edit in place: structural edits save and re-render at once, typing is batched. */
	private changed(structural: boolean, label?: string): void {
		if (!this.report) {
			return;
		}
		this.problems = checkSoilReport(this.report);
		if (structural) {
			this.commit(label);
			this.render();
		} else {
			this.pendingLabel = label ?? this.pendingLabel;
			this.markStale();
			this.commitScheduler.schedule();
			this.renderList();
			this.renderProblems();
			this.updateEntryProblems();
			this.renderStatus();
		}
	}

	// ───────────────────────────── actions ─────────────────────────────

	/**
	 * Adds a borehole beside the last one, with nothing logged yet, and opens the entry screen on
	 * its details. Its log and results are drawn once it is created.
	 */
	addBorehole(): void {
		if (!this.report) {
			return;
		}
		this.leaveEntry();
		const borehole = newBorehole(this.report);
		this.report.boreholes.push(borehole);
		this.selected = this.report.boreholes.length - 1;
		this.reportSelectedOnPurpose = false;
		this.fence = false;
		this.entry = newBoreholeEntry(this.selected);
		this.entryFocus = true;
		this.changed(true, localize('soil.undo.add', "adding {0}", borehole.id));
	}

	/** Opens the entry screen on the selected borehole (the same screen as for a new one). */
	editBorehole(step?: EntryStep): void {
		const borehole = this.borehole;
		if (!this.report || !borehole || this.selected === undefined) {
			return;
		}
		this.flush();
		if (this.entry?.index !== this.selected) {
			this.entry = editBoreholeEntry(this.selected, borehole, step);
		} else if (step) {
			goToStep(this.entry, step);
		}
		this.fence = false;
		this.entryFocus = true;
		this.render();
	}

	/** Create (or Save): with no errors left the entry closes and the log and results are drawn. */
	private finishEntry(): void {
		const entry = this.entry;
		const report = this.report;
		if (!entry || !report) {
			return;
		}
		this.flush();
		const problems = entryProblems(report, entry.index);
		if (!canCreate(problems)) {
			entry.tried = true;
			goToStep(entry, firstStepWithError(problems) ?? entry.step);
			this.renderView();
			this.entryParts?.problems.focus();
			return;
		}
		this.entry = undefined;
		this.selected = entry.index;
		this.view = DEFAULT_VIEW;
		this.render();
		this.computeScheduler.schedule(0);
	}

	/** Cancel: a new borehole is removed, an edited one put back as it was (one undoable edit). */
	private cancelEntry(): void {
		const entry = this.entry;
		const report = this.report;
		if (!entry || !report) {
			return;
		}
		this.entry = undefined;
		if (entry.isNew) {
			report.boreholes.splice(entry.index, 1);
			this.selected = report.boreholes.length ? Math.min(entry.index, report.boreholes.length - 1) : undefined;
		} else if (entry.snapshot && report.boreholes[entry.index]) {
			report.boreholes[entry.index] = JSON.parse(entry.snapshot);
		}
		this.changed(true, localize('soil.undo.cancel', "cancelling the entry"));
		this.computeScheduler.schedule(0);
	}

	/** Leaves the entry screen for another borehole or view; what was entered stays (it is saved as typed). */
	private leaveEntry(): void {
		if (this.entry) {
			this.flush();
			this.entry = undefined;
			this.computeScheduler.schedule(0);
		}
	}

	private goToEntryStep(step: EntryStep): void {
		if (this.entry) {
			this.flush();
			goToStep(this.entry, step);
			this.entryFocus = true;
			this.renderView();
		}
	}

	/**
	 * Deletes the selected borehole, after asking when it has anything logged. The entry screen
	 * and the properties go with it; the list keeps the keyboard, so Ctrl+Z brings it back.
	 */
	async deleteBorehole(): Promise<void> {
		const report = this.report;
		const borehole = this.borehole;
		if (!report || !borehole) {
			return;
		}
		this.flush();
		if (borehole.layers.length + borehole.spt.length + borehole.samples.length) {
			const { confirmed } = await this.dialogService.confirm({
				type: Severity.Warning,
				message: localize('soil.deleteConfirm', "Delete borehole {0}?", borehole.id),
				detail: localize('soil.deleteConfirmDetail', "It has {0} layer(s), {1} SPT record(s) and {2} sample(s). Ctrl+Z brings it back.", borehole.layers.length, borehole.spt.length, borehole.samples.length),
				primaryButton: localize({ key: 'soil.deleteButton', comment: ['&& denotes a mnemonic'] }, "&&Delete"),
			});
			if (!confirmed || this.report !== report) {
				return;
			}
		}
		const index = report.boreholes.indexOf(borehole);
		if (index < 0) {
			return;
		}
		this.entry = undefined;
		this.entryParts = undefined;
		report.boreholes.splice(index, 1);
		this.selected = report.boreholes.length ? Math.min(index, report.boreholes.length - 1) : undefined;
		this.reportSelectedOnPurpose = this.selected === undefined;
		this.propertiesFor = undefined; // the panel is built again for what is selected now
		this.changed(true, localize('soil.undo.delete', "deleting {0}", borehole.id));
		this.list.focus();
	}

	private duplicateBorehole(): void {
		const borehole = this.borehole;
		if (!this.report || !borehole) {
			return;
		}
		this.leaveEntry();
		const copy: IBorehole = JSON.parse(JSON.stringify(borehole));
		copy.id = newBorehole(this.report).id;
		copy.x = borehole.x + 5000;
		const index = this.report.boreholes.indexOf(borehole) + 1;
		this.report.boreholes.splice(index, 0, copy);
		this.selected = index;
		this.changed(true, localize('soil.undo.duplicate', "duplicating {0} as {1}", borehole.id, copy.id));
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
		this.leaveEntry();
		this.selected = index;
		this.reportSelectedOnPurpose = index === undefined;
		this.render();
	}

	private showView(view: View): void {
		this.flush();
		this.leaveEntry();
		this.view = view;
		this.render();
		if (view === 'map') {
			this.locationScheduler.schedule(0);
			void this.findQgis();
		}
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
		// The backend reads the file on its own (an empty report with this one's design); the
		// boreholes are merged here, so an id the report already has is never replaced unasked.
		let result: ISoilImportResult | undefined;
		this.setBusy('import', true);
		try {
			const empty: ISoilReport = { ...this.report, boreholes: [] };
			const request: ISoilImportRequest = { path: file.fsPath, soilText: serializeSoilReport(empty) };
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
		const report = this.report;
		if (parsed.kind !== 'report' || this.model !== model || !report) {
			return;
		}
		const incoming = parsed.report.boreholes;
		const duplicates = duplicateIds(report, incoming);
		let choice: DuplicateChoice = 'replace';
		if (duplicates.length) {
			const picked = await this.askDuplicates(basename(file), duplicates);
			if (!picked || this.report !== report || this.model !== model) {
				return;
			}
			choice = picked;
		}
		const merged = mergeBoreholes(report, incoming, choice);
		const first = [...merged.added, ...merged.renamed.map(r => r.to), ...merged.replaced][0];
		const index = first === undefined ? -1 : report.boreholes.findIndex(b => b.id === first);
		this.selected = index >= 0 ? index : this.selected;
		this.reportSelectedOnPurpose = false;
		this.leaveEntry();
		this.changed(true, localize('soil.undo.import', "import of {0}", basename(file)));
		const parts = [localize('soil.importAdded', "{0} added", merged.added.length + merged.renamed.length)];
		if (merged.replaced.length) {
			parts.push(localize('soil.importReplaced', "{0} replaced ({1})", merged.replaced.length, merged.replaced.join(', ')));
		}
		if (merged.renamed.length) {
			parts.push(localize('soil.importRenamed', "kept both as {0}", merged.renamed.map(r => r.to).join(', ')));
		}
		if (merged.skipped.length) {
			parts.push(localize('soil.importSkipped', "{0} skipped ({1})", merged.skipped.length, merged.skipped.join(', ')));
		}
		const summary = localize('soil.imported', "Imported {0}: {1}.", basename(file), parts.join(', '));
		if (result.problems?.length) {
			this.notificationService.warn(localize('soil.importedWithNotes', "{0} Notes: {1}", summary, result.problems.join('; ')));
		} else {
			this.notificationService.info(summary);
		}
	}

	/** Asks what to do with imported boreholes whose ids the report already has; undefined cancels. */
	private async askDuplicates(file: string, ids: readonly string[]): Promise<DuplicateChoice | undefined> {
		const { result } = await this.dialogService.prompt<DuplicateChoice | undefined>({
			type: Severity.Warning,
			message: ids.length === 1
				? localize('soil.importDuplicateOne', "{0} has a borehole {1}, and so has this report.", file, ids[0])
				: localize('soil.importDuplicateMany', "{0} has boreholes this report already has: {1}.", file, ids.join(', ')),
			detail: localize('soil.importDuplicateDetail', "Keep Both adds the file's under a new id ({0}-2). Replace overwrites the report's borehole with the file's. Skip imports only the new boreholes.", ids[0]),
			// The default (Enter) loses nothing: Keep Both.
			buttons: [
				{ label: localize({ key: 'soil.importKeepBoth', comment: ['&& denotes a mnemonic'] }, "&&Keep Both"), run: () => 'keepBoth' },
				{ label: localize({ key: 'soil.importReplace', comment: ['&& denotes a mnemonic'] }, "&&Replace"), run: () => 'replace' },
				{ label: localize({ key: 'soil.importSkip', comment: ['&& denotes a mnemonic'] }, "&&Skip"), run: () => 'skip' },
			],
			cancelButton: { label: localize('soil.importCancel', "Cancel"), run: () => undefined },
		});
		return result;
	}

	/** Writes a CSV or Excel template for the boreholes (asks where when `file` is not given). */
	async saveTemplate(file?: URI): Promise<void> {
		if (!CommandsRegistry.getCommand(SOIL_TEMPLATE_COMMAND)) {
			this.notificationService.info(localize('soil.templateNoBackend', "Saving a template needs the SAEngine backend, which is not available in this window."));
			return;
		}
		if (!file) {
			// Beside the project's parts, not in the soil report's own folder (the template is a
			// working file the engineer fills in and sends around, not part of the report).
			const folder = this.resource ? dirname(dirname(this.resource)) : await this.fileDialogService.defaultFilePath();
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
				const saved = file;
				this.notificationService.prompt(Severity.Info, localize('soil.templateSaved', "Saved the borehole template to {0}. Fill it in and import it.", saved.fsPath), [
					{ label: localize('soil.templateOpen', "Open"), run: () => void this.openerService.open(saved, { openExternal: true }) },
					{ label: localize('soil.templateReveal', "Reveal in File Explorer"), run: () => void this.commandService.executeCommand('revealFileInOS', saved) },
				]);
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
			this.clearStale();
			this.renderResultsDependent();
			return;
		}
		if (!CommandsRegistry.getCommand(SOIL_COMPUTE_COMMAND)) {
			this.setBusy('compute', false);
			this.results = undefined;
			this.resultsState = 'missing';
			this.clearStale();
			this.renderResultsDependent();
			return;
		}
		if (this.entry) {
			// A borehole is being entered: its results come with Create (the entry computes as it closes).
			this.setBusy('compute', false);
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
		this.clearStale();
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
		this.autoProperties();
	}

	/** The parts that show results: the Results view, N60 in the log, and the status. */
	private renderResultsDependent(): void {
		if (!this.entry && (this.view === 'results' || this.view === 'log')) {
			this.renderView();
		}
		this.renderProperties();
		this.renderStatus();
	}

	private onMainResized(): void {
		const size = `${this.viewElement.clientWidth}x${this.viewElement.clientHeight}`;
		if (size === this.lastSize) {
			return;
		}
		if (this.entry) {
			return; // the entry screen flows with the width by itself
		}
		if (this.view === 'map') {
			this.lastSize = size;
			this.mapView.value?.layout();
		} else {
			this.renderView();
		}
	}

	private updateViewButtons(): void {
		const usable = !!this.report;
		for (const [view, button] of this.viewButtons) {
			const active = !this.entry && view === this.view;
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
		this.addAction.enabled = this.importAction.enabled = usable && !this.entry;
		this.deleteAction.enabled = this.duplicateAction.enabled = hasBorehole;
		this.recomputeAction.enabled = !!this.report?.boreholes.length;
		this.deleteAction.label = hasBorehole ? localize('soil.deleteNamed', "Delete {0}", this.borehole!.id) : localize('soil.deleteBorehole', "Delete Borehole");
		this.fenceAction.checked = this.fence;
		const primary: IAction[] = usable ? [
			this.addAction,
			this.importAction,
			this.templateAction,
			...(this.view === 'log' && !this.entry && (this.report?.boreholes.length ?? 0) > 1 ? [this.fenceAction] : []),
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
			// One format: depth, layers, and the site class once it is computed.
			const siteClass = this.resultOf(borehole)?.siteClass?.class;
			const depth = formatNumber(terminationDepth(borehole) / 1000, 1);
			const layers = borehole.layers.length === 1 ? localize('soil.listDetailOne', "{0} m · 1 layer", depth) : localize('soil.listDetail', "{0} m · {1} layers", depth, borehole.layers.length);
			const detail = !borehole.layers.length && typeof borehole.depth !== 'number'
				? localize('soil.listDetailNew', "not entered yet")
				: siteClass ? `${layers} · ${siteClass}` : layers;
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
		// A cell or a field being typed into is not taken away by a render (new results, a
		// computation finishing): the render waits for the edit to end.
		const active = this.viewElement.ownerDocument.activeElement;
		if (this.grids.some(g => g.isEditing()) || this.entry && active && this.viewElement.contains(active) && isHTMLInputElement(active) && !active.closest('.soil-grid')) {
			this.renderPending = true;
			return;
		}
		this.renderPending = false;
		const report = this.report;
		if (!this.entry && this.view === 'map' && report && this.mapView.value?.element.isConnected) {
			this.mapView.value.update(this.mapHost(report));
			return;
		}
		const focusedGrid = this.grids.find(g => g.hasFocus())?.sheet.id;
		const focusedLab = this.labContainer?.contains(active) ?? false;
		this.mapView.clear();
		this.disposeGrids();
		this.viewDisposables.clear();
		this.inputs.clear();
		this.entryParts = undefined;
		const scroll = this.viewElement.scrollTop;
		const entryStep = this.viewElement.dataset.step;
		clearNode(this.viewElement);
		const entry = this.entry;
		this.viewElement.className = entry ? 'soil-view entry' : `soil-view ${this.view}`;
		this.viewElement.dataset.step = entry?.step ?? '';
		this.lastSize = `${this.viewElement.clientWidth}x${this.viewElement.clientHeight}`;
		if (!report || !report.boreholes.length && this.view !== 'map') {
			return;
		}
		if (entry) {
			this.renderEntry(report, entry);
		} else {
			switch (this.view) {
				case 'log': this.renderLogView(report); break;
				case 'results': this.renderResultsView(report); break;
				case 'map': this.renderMapView(report); break;
			}
		}
		// Another step starts at its top; a render of the same one keeps its place.
		this.viewElement.scrollTop = entry && entryStep !== entry.step ? 0 : scroll;
		this.renderProblems();
		this.updateEntryProblems();
		if (this.entryFocus) {
			this.entryFocus = false;
			this.focusEntry();
		} else if (focusedLab) {
			this.labGrid()?.focus();
		} else if (focusedGrid) {
			this.grids.find(g => g.sheet.id === focusedGrid)?.focus();
		}
	}

	private disposeGrids(): void {
		for (const grid of this.grids.splice(0)) {
			grid.dispose();
		}
		this.labDisposables.clear();
		this.labContainer = undefined;
		this.sampleSheet = undefined;
	}

	private labGrid(): SoilGrid | undefined {
		return this.grids.find(g => this.labContainer?.contains(g.element));
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
			const parts = [localize('soil.logDepth', "{0} m deep", formatNumber(terminationDepth(borehole) / 1000, 2))];
			if (typeof borehole.waterTable === 'number') {
				parts.push(localize('soil.logWater', "water table {0} m", formatNumber(borehole.waterTable / 1000, 2)));
			}
			parts.push(localize('soil.logGround', "ground level {0} m", formatNumber(boreholeGround(report, borehole) / 1000, 2)));
			append(header, $('span.soil-view-subtitle', undefined, parts.join(' · ')));
			append(header, $('span.soil-view-gap'));
			const edit = this.viewDisposables.add(new Button(header, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('soil.editTitle', "Change the borehole's details, strata, SPT records and lab results") }));
			edit.label = `$(${Codicon.edit.id}) ${localize('soil.editBorehole', "Edit Borehole")}`;
			edit.element.classList.add('soil-edit-button');
			this.viewDisposables.add(edit.onDidClick(() => this.editBorehole()));
		}
		const result = borehole ? this.resultOf(borehole) : undefined;
		this.renderLegend(this.viewElement, report, !fence && !!result?.spt?.some(s => typeof s.N60 === 'number'));
		const canvas = append(this.viewElement, $('.soil-canvas'));
		if (fence) {
			renderFence(canvas, report, { width, height, patternPrefix: this.patternPrefix, selected: this.selected, onSelect: index => this.openLog(index) });
			if (!borehole) {
				this.renderBoreholeSummary(report);
			}
		} else {
			renderBoreholeLog(canvas, report, borehole, { width, height, patternPrefix: this.patternPrefix, result, hammerEnergy: report.design.hammerEnergy });
		}
	}

	// ───────────────────────────── entry screen ─────────────────────────────

	/**
	 * The borehole entry screen: one page in the order of the consultant's log sheet, a step at a
	 * time (details, strata, SPT and lab), with what is wrong said in plain words under the step.
	 * What is typed is saved as it is typed (one undoable edit each); the log, the SPT graph and
	 * the results are drawn after Create (or Save). Adding and editing a borehole use this screen.
	 */
	private renderEntry(report: ISoilReport, entry: IEntryState): void {
		const borehole = report.boreholes[entry.index];
		if (!borehole) {
			return;
		}
		const index = entry.index;
		const page = append(this.viewElement, $('.soil-entry'));

		const header = append(page, $('.soil-view-header'));
		const title = append(header, $('span.soil-view-title'));
		append(header, $('span.soil-view-subtitle', undefined, entry.isNew
			? localize('soil.entry.newSubtitle', "Fill in the log sheet. The log, the SPT graph and the results are drawn when you create the borehole.")
			: localize('soil.entry.editSubtitle', "Changes are kept as you type; the log and the results are drawn again when you save.")));

		const steps = append(page, $('.soil-entry-steps', { role: 'tablist', 'aria-label': localize('soil.entry.stepsAria', "Log sheet steps") }));
		const stepElements = new Map<EntryStep, HTMLElement>();
		ENTRY_STEPS.forEach((info, i) => {
			const active = info.step === entry.step;
			const button = append(steps, $<HTMLButtonElement>('button.soil-entry-step', { type: 'button', role: 'tab', 'aria-selected': String(active), title: info.detail }));
			button.classList.toggle('active', active);
			append(button, $('span.soil-entry-step-number', undefined, String(i + 1)));
			append(button, $('span.soil-entry-step-label', undefined, info.label));
			append(button, $(`span.soil-entry-step-problem${ThemeIcon.asCSSSelector(Codicon.error)}`));
			this.viewDisposables.add(addDisposableListener(button, EventType.CLICK, () => this.goToEntryStep(info.step)));
			stepElements.set(info.step, button);
		});

		const body = append(page, $('.soil-entry-body'));
		const messages = new Map<string, HTMLElement>();
		switch (entry.step) {
			case 'details': this.renderEntryDetails(body, report, borehole, index, messages); break;
			case 'strata': this.renderEntryStrata(body, borehole, index); break;
			case 'tests': this.renderEntryTests(body, report, borehole, index); break;
		}

		const problems = append(page, $('.soil-entry-problems', { tabIndex: -1, role: 'status', 'aria-live': 'polite' }));

		const footer = append(page, $('.soil-entry-footer'));
		this.entryButton(footer, localize('soil.entry.cancel', "Cancel"), true, () => this.cancelEntry(), entry.isNew
			? localize('soil.entry.cancelNewTitle', "Discard this borehole")
			: localize('soil.entry.cancelEditTitle', "Put the borehole back as it was before this edit"));
		append(footer, $('span.soil-entry-footer-gap'));
		const previous = nextStep(entry.step, -1);
		const next = nextStep(entry.step, 1);
		if (previous) {
			this.entryButton(footer, localize('soil.entry.back', "Back"), true, () => this.goToEntryStep(previous));
		}
		if (next) {
			this.entryButton(footer, localize('soil.entry.next', "Next: {0}", ENTRY_STEPS.find(s => s.step === next)!.label), false, () => this.goToEntryStep(next));
		}
		this.entryButton(footer, entry.isNew ? localize('soil.entry.create', "Create Borehole") : localize('soil.entry.save', "Save"), !!next, () => this.finishEntry());

		this.entryParts = { title, problems, steps: stepElements, messages };
	}

	private entryButton(container: HTMLElement, label: string, secondary: boolean, run: () => void, title?: string): Button {
		const button = this.viewDisposables.add(new Button(container, { ...defaultButtonStyles, secondary, title }));
		button.label = label;
		this.viewDisposables.add(button.onDidClick(run));
		return button;
	}

	/** Step 1: the borehole's details, in groups; each field says under it what is wrong with it. */
	private renderEntryDetails(body: HTMLElement, report: ISoilReport, borehole: IBorehole, index: number, messages: Map<string, HTMLElement>): void {
		const placed = boreholePosition(borehole) !== 'project';
		for (const group of DETAIL_GROUPS) {
			const section = append(body, $('.soil-entry-group'));
			append(section, $('.soil-entry-group-title', undefined, group.label));
			const fields = append(section, $('.soil-entry-fields'));
			for (const key of group.fields) {
				const field = BOREHOLE_FIELDS.find(f => f.key === key);
				if (!field) {
					continue;
				}
				const item = append(fields, $('label.soil-entry-field', { title: field.title ?? '' }));
				const label = append(item, $('span.soil-entry-field-label', undefined, field.unit ? `${field.label} (${field.unit})` : field.label));
				if (REQUIRED_DETAILS.has(key)) {
					append(label, $('span.soil-entry-required', { 'aria-hidden': 'true' }, ' *'));
				}
				const placeholder = key === 'groundLevel' ? formatNumber(report.groundLevel / 1000, 3) : undefined;
				const input = this.createInput(field, borehole[key], value => {
					if (value === undefined) {
						delete borehole[key];
					} else {
						borehole[key] = value;
					}
					if (key === 'lat' || key === 'lon' || key === 'easting' || key === 'northing') {
						this.placeBy(borehole, index);
					}
					this.changed(false);
				}, this.problemKey(index, key), placeholder);
				if ((key === 'x' || key === 'y') && placed) {
					// The borehole's own lat/lon (or BTM) place it: X and Y follow from them.
					(input as HTMLInputElement).readOnly = true;
					item.title = localize('soil.sheet.xyFromMap', "Worked out from the latitude and longitude (or BTM); clear them to place the borehole by X and Y.");
					item.classList.add('derived');
				}
				item.appendChild(input);
				messages.set(key, append(item, $('span.soil-entry-field-message')));
			}
			if (group.fields.includes('x')) {
				append(section, $('p.soil-entry-note', undefined, localize('soil.entry.locationNote', "Give X and Y on the project grid, or the latitude and longitude, or the BTM easting and northing as the survey drawing gives them. The Map view can place it too.")));
			}
		}
	}

	/** Step 2: the strata, one row per layer from the ground down, with all the width it needs. */
	private renderEntryStrata(body: HTMLElement, borehole: IBorehole, index: number): void {
		const section = append(body, $('.soil-section.soil-entry-sheet'));
		this.sheetHeading(section, localize('soil.sheet.strata', "Strata"), borehole.layers.length,
			localize('soil.entry.strataHint', "One row per layer, from the ground down"),
			localize('soil.entry.strataHelp', "Type into a cell or paste a block copied from Excel with Ctrl+V. Enter, Tab and the arrows move; Delete clears; Ctrl+Z undoes. The grey groups (unit weight, strength, index, consolidation) open with their arrows."));
		const strata = new StrataSheet(borehole, index, this.problems);
		this.addGrid(section, strata, `${index}|strata`, STRATA_COLLAPSED, localize('soil.sheet.strataAria', "Strata of {0}", borehole.id));
		for (const layer of borehole.layers.filter(l => siltNeedsPlasticity(borehole, l))) {
			const hint = append(section, $('.soil-hint'));
			append(hint, $(ThemeIcon.asCSSSelector(Codicon.info)));
			append(hint, $('span', undefined, localize('soil.sheet.siltHint', "The silt {0}–{1} m: is it plastic? Give PI or cu (here or in a sample's LL and PL).", formatNumber(layer.top / 1000, 2), formatNumber(layer.bottom / 1000, 2))));
		}
	}

	/** Step 3: the SPT records and samples in the consultant's order, then the selected sample's lab tests. */
	private renderEntryTests(body: HTMLElement, report: ISoilReport, borehole: IBorehole, index: number): void {
		const section = append(body, $('.soil-section.soil-entry-sheet'));
		const rows = new Set([...borehole.spt.map(s => s.depth), ...borehole.samples.map(s => s.depth)]).size;
		this.sheetHeading(section, localize('soil.sheet.samples', "Samples and SPT"), rows,
			localize('soil.entry.testsHint', "One row per test depth; N = N1 + N2 is worked out"),
			localize('soil.entry.testsHelp', "Seat is the first 150 mm (not counted); N1 and N2 the next two 150 mm, and N is worked out from them (greyed). Mark a refusal with R or 50/100. N60 uses the report's hammer energy ({0}%, in the Report's properties) unless the row's ER gives its own. The description and USCS are the stratum's. Paste a block from Excel with Ctrl+V.", formatNumber(report.design.hammerEnergy ?? DESIGN_DEFAULTS.hammerEnergy)));
		const sptResults = this.resultOf(borehole)?.spt ?? [];
		const samples = this.sampleSheet = new SampleSheet(borehole, sptResults.length ? depth => sptResults.find(s => Math.abs(s.depth - depth) <= 1) : undefined);
		const sampleState = this.gridState(`${index}|samples`, SAMPLES_COLLAPSED);
		// The lab panel follows the selected row; after a re-sort the sample finds its row again.
		const labRow = samples.rowOf(this.labSample);
		if (labRow >= 0) {
			sampleState.active = { row: labRow, column: sampleState.active.column };
		}
		this.addGrid(section, samples, `${index}|samples`, SAMPLES_COLLAPSED, localize('soil.sheet.samplesAria', "Samples and SPT of {0}", borehole.id), row => {
			this.labSample = samples.rowAt(row)?.sample;
			this.renderLabPanel();
		});
		this.labSample = samples.rowAt(sampleState.active.row)?.sample;

		// The lab tests of the selected sample (optional).
		this.labContainer = append(body, $('.soil-lab-container'));
		this.renderLabPanel();
	}

	/** A sheet's heading: its title, its row count, a one-line hint and the rest behind a help mark. */
	private sheetHeading(section: HTMLElement, title: string, count: number, hint: string, help: string): void {
		const heading = append(section, $('.soil-section-heading'));
		append(heading, $('span.soil-section-title', undefined, title));
		append(heading, $('span.soil-section-count', undefined, String(count)));
		append(heading, $('span.soil-section-detail', undefined, hint));
		append(heading, $(`span.soil-help${ThemeIcon.asCSSSelector(Codicon.question)}`, { title: help, 'aria-label': help, role: 'img' }));
	}

	/** Gives the entry screen the keyboard: the first field of the details, or the step's grid. */
	private focusEntry(): void {
		if (this.entry?.step === 'details') {
			const first = this.inputs.get(this.problemKey(this.entry.index, DETAIL_GROUPS[0].fields[0]));
			if (first && isHTMLInputElement(first)) {
				first.focus();
				first.select();
			}
		} else {
			this.grids[0]?.focus();
		}
	}

	/**
	 * Shows the entry's problems without a render (typing keeps its field): under the fields, in the
	 * list under the step, as marks on the steps, and the title follows the id.
	 */
	private updateEntryProblems(): void {
		const parts = this.entryParts;
		const entry = this.entry;
		const report = this.report;
		const borehole = entry && report?.boreholes[entry.index];
		if (!parts || !entry || !report || !borehole) {
			return;
		}
		parts.title.textContent = entry.isNew
			? localize('soil.entry.newTitle', "New borehole {0}", borehole.id)
			: localize('soil.entry.editTitle', "Edit borehole {0}", borehole.id);
		const problems = entryProblems(report, entry.index);
		for (const info of ENTRY_STEPS) {
			const shown = shownProblems(entry, problems, info.step).some(p => p.severity === 'error');
			parts.steps.get(info.step)?.classList.toggle('has-problem', shown);
		}
		const shown = shownProblems(entry, problems);
		for (const [key, element] of parts.messages) {
			const problem = shown.find(p => p.path === key);
			element.textContent = problem?.message ?? '';
			element.className = `soil-entry-field-message ${problem?.severity ?? ''}`;
			this.inputs.get(this.problemKey(entry.index, key))?.classList.toggle('problem', problem?.severity === 'error');
		}
		clearNode(parts.problems);
		const listed = shown.filter((p: IEntryProblem) => entry.step !== 'details' || !p.path || !parts.messages.has(p.path));
		const others = entry.tried ? problems.filter(p => p.step !== entry.step && p.severity === 'error') : [];
		for (const problem of listed) {
			const line = append(parts.problems, $(`.soil-entry-problem.${problem.severity}`));
			append(line, $(ThemeIcon.asCSSSelector(problem.severity === 'error' ? Codicon.error : Codicon.warning)));
			append(line, $('span', undefined, problem.message));
		}
		if (others.length) {
			const line = append(parts.problems, $('.soil-entry-problem.error'));
			append(line, $(ThemeIcon.asCSSSelector(Codicon.error)));
			const steps = ENTRY_STEPS.filter(s => others.some(p => p.step === s.step)).map(s => s.label).join(', ');
			append(line, $('span', undefined, localize('soil.entry.otherSteps', "Also to fix before creating it: {0}.", steps)));
		}
		parts.problems.hidden = !parts.problems.childElementCount;
	}

	private gridState(key: string, collapsed: readonly string[]): IGridState {
		let state = this.gridStates.get(key);
		if (!state) {
			state = newGridState(collapsed);
			this.gridStates.set(key, state);
		}
		return state;
	}

	private addGrid(container: HTMLElement, sheet: StrataSheet | SampleSheet, key: string, collapsed: readonly string[], ariaLabel: string, onDidChangeActiveRow?: (row: number) => void): SoilGrid {
		const grid = new SoilGrid(container, {
			sheet,
			state: this.gridState(key, collapsed),
			ariaLabel,
			onDidWrite: () => this.onSheetWrite(),
			onDidChangeActiveRow,
		});
		this.grids.push(grid);
		return grid;
	}

	/** A sheet wrote into the report: store it as one undoable edit and show it again. */
	private onSheetWrite(): void {
		if (!this.report) {
			return;
		}
		this.problems = checkSoilReport(this.report);
		this.commit();
		this.renderList();
		this.renderView();
		this.renderProperties();
		this.renderStatus();
	}

	/** The lab tests of the sample selected in the sheet. */
	private renderLabPanel(): void {
		const container = this.labContainer;
		if (!container) {
			return;
		}
		const focused = container.contains(container.ownerDocument.activeElement);
		const old = this.labGrid();
		if (old) {
			this.grids.splice(this.grids.indexOf(old), 1);
		}
		this.labDisposables.clear();
		clearNode(container);
		const sample = this.labSample;
		const row = this.sampleSheet?.rowOf(sample) ?? -1;
		const data = row >= 0 ? this.sampleSheet?.rowAt(row) : undefined;
		if (!sample || !data) {
			append(container, $('p.soil-note', undefined, localize('soil.lab.pick', "Select a row with a sample to enter its lab tests: grain size, consolidation, triaxial, direct shear.")));
			return;
		}
		const to = sample.depthTo ?? data.spt?.depthTo ?? (data.spt ? data.depth + SPT_DRIVE : undefined);
		const depth = typeof to === 'number'
			? localize('soil.lab.depthRange', "{0}–{1} m", formatNumber(data.depth / 1000, 2), formatNumber(to / 1000, 2))
			: localize('soil.lab.depthAt', "{0} m", formatNumber(data.depth / 1000, 2));
		const title = [sample.number, sample.type, depth].filter(Boolean).join(' · ');
		const panel = this.labDisposables.add(new SoilLabPanel(container, {
			sample,
			title,
			test: this.labTest,
			gridStates: this.labGridStates,
			onDidChangeTest: test => {
				this.labTest = test;
				this.renderLabPanel();
			},
			onDidWrite: () => this.onSheetWrite(),
		}));
		this.grids.push(panel.grid);
		if (focused) {
			panel.grid.focus();
		}
	}

	/** With the report selected, under the fence: one row per borehole, a click opens its log. */
	private renderBoreholeSummary(report: ISoilReport): void {
		const header = append(this.viewElement, $('.soil-view-header.soil-summary-header'));
		append(header, $('span.soil-view-title', undefined, localize('soil.allBoreholes', "Boreholes")));
		append(header, $('span.soil-view-subtitle', undefined, localize('soil.summarySubtitle', "Select a borehole to see its log; Edit Borehole there changes it.")));
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
				formatNumber(terminationDepth(borehole) / 1000, 2),
				String(borehole.layers.length), String(borehole.spt.length), String(borehole.samples.filter(hasLabData).length),
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
			if (this.renderPending) {
				this.pendingRenderScheduler.schedule();
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
			if (this.resultsState === 'error') {
				const { summary, details } = splitError(this.resultsError ?? '');
				append(state, $('.soil-results-state-text', undefined, summary));
				if (details) {
					this.appendDetails(state, [details]);
				}
				const retry = this.viewDisposables.add(new Button(state, { ...defaultButtonStyles, secondary: true }));
				retry.label = localize('soil.recompute', "Compute Results Again");
				this.viewDisposables.add(retry.onDidClick(() => void this.compute()));
			} else if (this.resultsState === 'missing') {
				append(state, $('.soil-results-state-text', undefined, localize('soil.backendMissingText', "The site class, bearing capacity, liquefaction screening and pile parameters are computed by the SAEngine Python backend, which is not running in this window. The boreholes can still be edited; the results appear once the backend is available.")));
			}
			return;
		}
		const results = this.results;
		if (!results) {
			return;
		}
		const header = append(view, $('.soil-view-header'));
		append(header, $('span.soil-view-title', undefined, localize('soil.resultsTitle', "Results")));
		append(header, $('span.soil-view-subtitle', undefined, localize('soil.resultsSubtitle', "Computed from the boreholes and the project settings; not stored in the report.")));

		if (results.skipped?.length) {
			const row = append(view, $('.soil-flag.soil-skipped', { role: 'note' }));
			append(row, $(`span.soil-flag-icon${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			const text = append(row, $('.soil-flag-text'));
			append(text, $('span.soil-flag-title', undefined, localize('soil.skipped', "Not computed: {0}. The other boreholes are; see the notes below for why.", results.skipped.join(', '))));
		}
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
			if (results.details?.length) {
				this.appendDetails(section, results.details);
			}
		}
	}

	/** A "Show details" toggle over what the backend printed (a traceback), for a bug report. */
	private appendDetails(container: HTMLElement, details: readonly string[]): void {
		const toggle = append(container, $<HTMLAnchorElement>('a.soil-details-toggle', { role: 'button', tabIndex: 0, 'aria-expanded': String(this.detailsShown) }));
		toggle.textContent = this.detailsShown ? localize('soil.hideDetails', "Hide details") : localize('soil.showDetails', "Show details");
		const pre = append(container, $('pre.soil-details'));
		pre.textContent = details.join('\n');
		pre.hidden = !this.detailsShown;
		const flip = () => {
			this.detailsShown = !this.detailsShown;
			pre.hidden = !this.detailsShown;
			toggle.textContent = this.detailsShown ? localize('soil.hideDetails', "Hide details") : localize('soil.showDetails', "Show details");
			toggle.setAttribute('aria-expanded', String(this.detailsShown));
		};
		this.viewDisposables.add(addDisposableListener(toggle, EventType.CLICK, flip));
		this.viewDisposables.add(addDisposableListener(toggle, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				flip();
			}
		}));
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
		// By N̄ and by s̄u side by side; the softer governs (Table 6.2.13), in bold.
		const sites = report.boreholes.map(b => this.resultOf(b)?.siteClass);
		const rows = report.boreholes.map((b, i) => {
			const site = sites[i];
			return [
				b.id, site?.class ?? '—',
				typeof site?.nBar === 'number' ? formatNumber(site.nBar, 1) : '—', site?.byN ?? '—',
				typeof site?.suBar === 'number' ? formatNumber(site.suBar, 0) : '—', site?.bySu ?? '—',
				typeof site?.depth === 'number' ? formatNumber(site.depth / 1000, 1) : '—',
			];
		});
		const table = this.simpleTable(section, [[localize('soil.borehole', "Borehole")], [localize('soil.class', "Class")], ['N̄'], [localize('soil.byN', "By N̄")], ['s̄u', 'kPa'], [localize('soil.bySu', "By s̄u")], [localize('soil.over', "Over"), 'm']], rows, column => column === 2 || column === 4 || column === 6);
		sites.forEach((site, i) => {
			const cells = table.tBodies[0]?.rows[i]?.cells;
			for (const column of [3, 5]) {
				const by = column === 3 ? site?.byN : site?.bySu;
				cells?.[column]?.classList.toggle('soil-governs-cell', !!by && by === site?.class);
			}
		});
		append(section, $('p.soil-note', undefined, localize('soil.byNote', "Each borehole's class is the softer of its class by N̄ and by s̄u (bold); a liquefiable borehole is S2 and uses SD meanwhile.")));
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
			if (!Number.isFinite(minFs)) {
				// Nothing screened (dry, clay, too deep): an LPI of 0 would read as "safe".
				return [b.id, '—', '—', localize('soil.noData', "no data"), localize('soil.notScreened', "no test screened")];
			}
			return [b.id, formatNumber(minFs, 2), typeof lpi === 'number' ? formatNumber(lpi, 1) : '—', liquefaction.category ?? (typeof lpi === 'number' ? this.lpiRisk(lpi) : '—'), this.liquefiableText(b)];
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

	/**
	 * The selected borehole at a glance. Its details are entered in one place, the entry screen
	 * (Edit Borehole); the panel shows them and links there.
	 */
	private renderBoreholeProperties(panel: HTMLElement, report: ISoilReport, borehole: IBorehole): void {
		appendPropertyHeading(panel, localize('soil.boreholeHeading', "Borehole {0}", borehole.id));
		const value = (key: string, fallback = '—') => {
			const field = BOREHOLE_FIELDS.find(f => f.key === key)!;
			const text = formatField(field, borehole[key]);
			return text ? (field.unit ? `${text} ${field.unit}` : text) : fallback;
		};
		appendPropertyRow(panel, localize('soil.f.termination', "Termination depth"), value('depth'));
		appendPropertyRow(panel, localize('soil.f.waterTable', "Water table"), value('waterTable', localize('soil.notMet', "not met")));
		appendPropertyRow(panel, localize('soil.f.groundLevel', "Ground level"), typeof borehole.groundLevel === 'number' ? value('groundLevel') : localize('soil.groundOfReport', "{0} m (the report's)", formatNumber(report.groundLevel / 1000, 3)));
		// One position, with what places it; the others follow from it.
		const position = boreholePosition(borehole);
		appendPropertyRow(panel, localize('soil.position', "Position"), position === 'project'
			? localize('soil.positionXY', "X {0}, Y {1} (project grid)", value('x'), value('y'))
			: position === 'wgs84'
				? localize('soil.positionLatLon', "{0}°, {1}° (latitude, longitude)", formatNumber(borehole.lat ?? NaN, 6), formatNumber(borehole.lon ?? NaN, 6))
				: localize('soil.positionBtm', "BTM {0} E, {1} N", value('easting'), value('northing')));
		if (position !== 'project') {
			appendPropertyRow(panel, localize('soil.positionGrid', "On the grid"), localize('soil.positionXYDerived', "X {0}, Y {1}", value('x'), value('y')));
		}
		if (borehole.date || borehole.method) {
			appendPropertyRow(panel, localize('soil.drilled', "Drilled"), [borehole.date, borehole.method].filter(Boolean).join(' · '));
		}
		if (!this.entry) {
			const link = append(panel, $<HTMLAnchorElement>('a.soil-prop-link', { role: 'button', tabIndex: 0 }));
			append(link, $(ThemeIcon.asCSSSelector(Codicon.edit)));
			append(link, $('span', undefined, localize('soil.editBoreholeDetails', "Edit Borehole")));
			this.propertiesDisposables.add(addDisposableListener(link, EventType.CLICK, () => this.editBorehole()));
			this.propertiesDisposables.add(addDisposableListener(link, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					this.editBorehole();
				}
			}));
		}
		const result = this.resultOf(borehole);
		appendPropertyHeading(panel, localize('soil.contents', "Records"));
		appendPropertyRow(panel, localize('soil.layers', "Layers"), String(borehole.layers.length));
		appendPropertyRow(panel, localize('soil.sptRecords', "SPT"), String(borehole.spt.length));
		appendPropertyRow(panel, localize('soil.samples', "Lab samples"), String(borehole.samples.filter(hasLabData).length));
		if (result) {
			const computed = (row: HTMLElement) => row.classList.add('soil-computed');
			appendPropertyHeading(panel, localize('soil.resultsTitle', "Results"));
			if (result.siteClass) {
				computed(appendPropertyRow(panel, localize('soil.siteClass', "Site class"), result.siteClass.class));
				if (typeof result.siteClass.nBar === 'number') {
					computed(appendPropertyRow(panel, 'N̄', formatNumber(result.siteClass.nBar, 1)));
				}
			}
			if (result.settlement) {
				const permissible = result.settlement.permissible ?? this.results?.permissibleSettlement;
				computed(appendPropertyRow(panel, localize('soil.settlement', "Settlement"), typeof permissible === 'number'
					? localize('soil.settlementPermissible', "{0} mm (permissible {1} mm)", formatNumber(result.settlement.total, 1), formatNumber(permissible, 0))
					: localize('soil.settlementValue', "{0} mm", formatNumber(result.settlement.total, 1))));
			}
			if (typeof result.ks === 'number') {
				computed(appendPropertyRow(panel, 'ks', localize('soil.ksValue', "{0} kN/m³", formatNumber(result.ks, 0))));
			}
			const screened = result.liquefaction?.points.some(p => typeof p.FS === 'number');
			if (result.liquefaction && !screened) {
				computed(appendPropertyRow(panel, 'LPI', localize('soil.noDataScreened', "no data (no test screened)")));
			} else if (typeof result.liquefaction?.LPI === 'number') {
				computed(appendPropertyRow(panel, 'LPI', `${formatNumber(result.liquefaction.LPI, 1)} (${result.liquefaction.category ?? this.lpiRisk(result.liquefaction.LPI)})`));
			}
			if (result.liquefaction && screened) {
				computed(appendPropertyRow(panel, localize('soil.liquefiable', "Liquefiable"), this.liquefiableText(result)));
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

	// ───────────────────────────── map view ─────────────────────────────

	private renderMapView(report: ISoilReport): void {
		this.mapView.value = new SoilMapView(this.viewElement, this.mapHost(report), this.mapState);
	}

	/** What the map view shows, and where its changes go. */
	private mapHost(report: ISoilReport): ISoilMapHost {
		return {
			report,
			location: this.location,
			locationState: this.locationState,
			tiles: tileSource(this.configurationService.getValue(MAP_TILE_URL_SETTING), this.configurationService.getValue(MAP_TILE_ATTRIBUTION_SETTING)),
			qgis: this.qgis,
			selected: this.selected,
			moveSite: position => this.moveSite(position),
			setRotation: degrees => {
				const site = report.site ??= {};
				if (degrees === undefined || degrees === 0) {
					delete site.rotation;
				} else {
					site.rotation = degrees;
				}
				this.changed(true);
			},
			moveBorehole: (index, position) => void this.moveBorehole(index, position),
			moveBoreholeOnGrid: (index, x, y) => {
				const borehole = report.boreholes[index];
				if (!borehole) {
					return;
				}
				borehole.x = x;
				borehole.y = y;
				// Moved in the project coordinates: its lat/lon (or BTM) now follow from them.
				delete borehole.lat;
				delete borehole.lon;
				delete borehole.easting;
				delete borehole.northing;
				delete borehole.position;
				this.selected = index;
				this.changed(true);
			},
			select: index => this.select(index),
			applyBnbc: suggestion => this.applyBnbc(suggestion),
			exportGis: format => void this.exportGis(format),
			importGis: () => void this.importGis(),
			openInQgis: () => void this.openInQgis(),
			openLink: url => void this.openerService.open(URI.parse(url), { openExternal: true }),
		};
	}

	private moveSite(position: ILatLon): void {
		if (!this.report) {
			return;
		}
		const site = this.report.site ??= {};
		site.lat = Number(position.lat.toFixed(7));
		site.lon = Number(position.lon.toFixed(7));
		this.mapState.center = { lat: site.lat, lon: site.lon };
		this.changed(true);
	}

	/**
	 * A borehole dragged on the map (or given its lat/lon): the backend works out its project
	 * x, y from the site's georeference, and both are stored as one edit.
	 */
	private async moveBorehole(index: number, position: ILatLon): Promise<void> {
		const report = this.report;
		const borehole = report?.boreholes[index];
		if (!report || !borehole) {
			return;
		}
		borehole.lat = Number(position.lat.toFixed(7));
		borehole.lon = Number(position.lon.toFixed(7));
		if (borehole.position !== undefined || typeof borehole.easting === 'number') {
			borehole.position = 'wgs84'; // the map's position places it now
		}
		this.selected = index;
		const result = await this.askLocation(serializeSoilReport(report));
		const placed = result?.boreholes?.find(b => b.id === borehole.id);
		if (this.report === report && typeof placed?.x === 'number' && typeof placed.y === 'number') {
			borehole.x = Math.round(placed.x);
			borehole.y = Math.round(placed.y);
			this.location = result;
			this.locationState = 'ok';
		}
		if (this.report === report) {
			this.changed(true);
		}
	}

	/**
	 * A latitude/longitude (or BTM) typed on the entry screen places the borehole: it becomes its
	 * one position (an imported borehole says "project" otherwise, and the typed values would be
	 * ignored), X and Y turn read-only and follow from it. Cleared, X and Y place it again.
	 */
	private placeBy(borehole: IBorehole, index: number): void {
		if (typeof borehole.lat === 'number' && typeof borehole.lon === 'number') {
			borehole.position = 'wgs84';
		} else if (typeof borehole.easting === 'number' && typeof borehole.northing === 'number') {
			borehole.position = 'btm';
		} else {
			borehole.position = 'project';
		}
		const placed = borehole.position !== 'project';
		for (const key of ['x', 'y']) {
			const input = this.inputs.get(this.problemKey(index, key));
			if (input && isHTMLInputElement(input)) {
				input.readOnly = placed;
				input.parentElement?.classList.toggle('derived', placed);
			}
		}
		if (placed) {
			this.positionScheduler.schedule(); // X and Y follow from it
		}
	}

	/**
	 * After a latitude/longitude (or BTM) is typed on the entry screen: the backend works out the
	 * borehole's X and Y, which the read-only X and Y fields then show, so the two never disagree.
	 */
	private async updateDerivedPosition(): Promise<void> {
		const report = this.report;
		const entry = this.entry;
		const borehole = entry && report?.boreholes[entry.index];
		if (!report || !entry || !borehole || boreholePosition(borehole) === 'project') {
			return;
		}
		const result = await this.askLocation(serializeSoilReport(report));
		const placed = result?.boreholes?.find(b => b.id === borehole.id);
		if (this.report !== report || typeof placed?.x !== 'number' || typeof placed.y !== 'number') {
			return;
		}
		borehole.x = Math.round(placed.x);
		borehole.y = Math.round(placed.y);
		for (const key of ['x', 'y'] as const) {
			const input = this.inputs.get(this.problemKey(entry.index, key));
			const field = BOREHOLE_FIELDS.find(f => f.key === key);
			if (input && isHTMLInputElement(input) && field) {
				input.value = formatField(field, borehole[key]);
			}
		}
		this.changed(false);
	}

	/** The backend's answer for the report's text, or undefined without a backend or on failure. */
	private async askLocation(soilText: string): Promise<ISoilLocationResult | undefined> {
		if (!CommandsRegistry.getCommand(SOIL_LOCATION_COMMAND)) {
			return undefined;
		}
		await this.openBim();
		const request: ISoilLocationRequest = {
			soilText,
			bimText: this.bim.value?.object.textEditorModel.getValue(),
			settingsText: this.settings.value?.object.textEditorModel.getValue(),
		};
		try {
			return await this.commandService.executeCommand<ISoilLocationResult>(SOIL_LOCATION_COMMAND, request) ?? undefined;
		} catch {
			return undefined;
		}
	}

	/** Where the site, the boreholes and the building are (debounced after edits while the map shows). */
	private async computeLocation(): Promise<void> {
		const model = this.model;
		if (!model || !this.report) {
			return;
		}
		const version = ++this.locationVersion;
		if (!CommandsRegistry.getCommand(SOIL_LOCATION_COMMAND)) {
			this.locationState = 'missing';
			this.location = undefined;
			this.updateMapView();
			return;
		}
		this.flush();
		this.locationState = 'computing';
		let result: ISoilLocationResult | undefined;
		let failed = false;
		try {
			await this.openBim();
			result = await this.commandService.executeCommand<ISoilLocationResult>(SOIL_LOCATION_COMMAND, {
				soilText: model.getValue(),
				bimText: this.bim.value?.object.textEditorModel.getValue(),
				settingsText: this.settings.value?.object.textEditorModel.getValue(),
			} satisfies ISoilLocationRequest) ?? undefined;
		} catch (error) {
			failed = true;
			result = { problems: [error instanceof Error ? error.message : String(error)] };
		}
		if (version !== this.locationVersion) {
			return;
		}
		this.location = result;
		this.locationState = failed || !result ? 'error' : 'ok';
		this.updateMapView();
	}

	private updateMapView(): void {
		if (this.view === 'map' && this.report) {
			this.mapView.value?.update(this.mapHost(this.report));
		}
	}

	/** The building model, for its outline; opened once, with the Map view. */
	private async openBim(): Promise<void> {
		const resource = this.resource;
		const part = partById('bim');
		if (this.bimRequested || !resource || !part?.mainFile) {
			return;
		}
		this.bimRequested = true;
		try {
			const reference = await this.textModelService.createModelReference(joinPath(dirname(dirname(resource)), part.folder, part.mainFile));
			if (this.resource !== resource) {
				reference.dispose();
				return;
			}
			this.bim.value = reference;
			this.inputDisposables.add(reference.object.textEditorModel.onDidChangeContent(() => {
				if (this.view === 'map') {
					this.locationScheduler.schedule();
				}
			}));
		} catch {
			// No building yet: the map has no outline.
		}
	}

	/** Asks the backend once for the QGIS on this computer ("Open in QGIS" shows when found). */
	private async findQgis(): Promise<void> {
		if (this.qgisAsked || !CommandsRegistry.getCommand(SOIL_QGIS_PROGRAM_COMMAND)) {
			return;
		}
		this.qgisAsked = true;
		try {
			const found = await this.commandService.executeCommand<QgisProgramResult>(SOIL_QGIS_PROGRAM_COMMAND, {});
			const path = typeof found === 'string' ? found : found?.path;
			this.qgis = path ? { path, version: typeof found === 'object' ? found?.version ?? undefined : undefined } : undefined;
		} catch {
			this.qgis = undefined;
		}
		this.updateMapView();
	}

	/**
	 * The nearest BNBC town into the project settings (only on the engineer's click): its
	 * location when the settings list it, else Custom with its Z and V; the overrides of a listed
	 * location are removed, except the wind speed when a nearer other town gives it. One undoable edit of the settings file, its formatting kept.
	 */
	applyBnbc(suggestion: IBnbcSuggestion): void {
		const model = this.settings.value?.object.textEditorModel;
		if (!model || model.isDisposed()) {
			this.notificationService.info(localize('soil.map.noSettings', "The project settings could not be opened."));
			return;
		}
		const values: [string, unknown][] = suggestion.location
			// The wind of a nearer other town (as the banner shows it) stays as the location's override.
			? [['location', suggestion.location], ['zoneCoefficient', undefined], ['windSpeed', suggestion.windSpeedOverride]]
			: [['location', 'custom'], ['zoneCoefficient', suggestion.Z], ['windSpeed', suggestion.windSpeed]];
		const options = model.getOptions();
		const formatting = { tabSize: options.tabSize, insertSpaces: options.insertSpaces, eol: model.getEOL() };
		model.pushStackElement();
		for (const [key, value] of values) {
			const edits = setProperty(model.getValue(), ['site', key], value, formatting);
			model.pushEditOperations([], edits.map(edit => {
				const start = model.getPositionAt(edit.offset);
				const end = model.getPositionAt(edit.offset + edit.length);
				return { range: new Range(start.lineNumber, start.column, end.lineNumber, end.column), text: edit.content };
			}), () => null);
		}
		model.pushStackElement();
		const name = suggestion.location ? BNBC.locations[suggestion.location]?.name ?? suggestion.location : localize('soil.map.custom', "Custom");
		this.notificationService.info(localize('soil.map.applied', "The project settings now use {0} for the seismic zone and the basic wind speed. Save the settings to keep it.", name));
	}

	private exportsFolder(): URI | undefined {
		const resource = this.resource;
		const part = partById('exports');
		return resource && part ? joinPath(dirname(dirname(resource)), part.folder) : undefined;
	}

	/** Exports the site, the boreholes and the outline for QGIS (asks where when `file` is not given). */
	async exportGis(format: GisFormat, file?: URI): Promise<URI | undefined> {
		this.flush();
		const resource = this.resource;
		if (!resource) {
			return undefined;
		}
		if (!CommandsRegistry.getCommand(SOIL_GIS_EXPORT_COMMAND)) {
			this.notificationService.info(localize('soil.gisNoBackend', "The GIS exchange needs the SAEngine backend, which is not available in this window."));
			return undefined;
		}
		const extension = format === 'gpkg' ? 'gpkg' : 'geojson';
		if (!file) {
			const folder = this.exportsFolder();
			file = await this.fileDialogService.showSaveDialog({
				title: format === 'gpkg' ? localize('soil.gisExportGpkgTitle', "Export GeoPackage") : localize('soil.gisExportGeoJsonTitle', "Export GeoJSON"),
				defaultUri: folder ? joinPath(folder, `site.${extension}`) : undefined,
				filters: [format === 'gpkg'
					? { name: localize('soil.gisGpkg', "GeoPackage"), extensions: ['gpkg'] }
					: { name: localize('soil.gisGeoJson', "GeoJSON"), extensions: ['geojson', 'json'] }],
			});
		}
		if (!file) {
			return undefined;
		}
		try {
			const request: ISoilGisExportRequest = { projectRoot: dirname(dirname(resource)).fsPath, format, outPath: file.fsPath };
			const result = await this.commandService.executeCommand<ISoilGisExportResult>(SOIL_GIS_EXPORT_COMMAND, request);
			if (!result?.path) {
				this.notificationService.warn(localize('soil.gisExportProblems', "The GIS file could not be written: {0}", (result?.problems ?? []).join('; ')));
				return undefined;
			}
			if (result.problems?.length) {
				this.notificationService.warn(localize('soil.gisExportedNotes', "Exported {0} with notes: {1}", basename(file), result.problems.join('; ')));
			} else {
				this.notificationService.info(localize('soil.gisExported', "Exported the site and the boreholes to {0}.", basename(file)));
			}
			return URI.file(result.path);
		} catch (error) {
			this.notificationService.error(localize('soil.gisExportFailed', "The GIS file could not be written: {0}", String(error)));
			return undefined;
		}
	}

	/** Imports boreholes (points) from a GeoJSON or GeoPackage file (asks for it when `file` is not given). */
	async importGis(file?: URI): Promise<void> {
		this.flush();
		const model = this.model;
		if (!model || !this.report) {
			return;
		}
		if (!CommandsRegistry.getCommand(SOIL_GIS_IMPORT_COMMAND)) {
			this.notificationService.info(localize('soil.gisNoBackend', "The GIS exchange needs the SAEngine backend, which is not available in this window."));
			return;
		}
		if (!file) {
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('soil.gisImportTitle', "Import from GIS"),
				canSelectFiles: true,
				canSelectMany: false,
				filters: [{ name: localize('soil.gisFiles', "GeoPackage, GeoJSON"), extensions: ['gpkg', 'geojson', 'json'] }],
				defaultUri: this.exportsFolder(),
			});
			file = picked?.[0];
		}
		if (!file || this.model !== model) {
			return;
		}
		const before = new Set(this.report.boreholes.map(b => b.id));
		let result: (ISoilGisImportResult & { readonly text?: string }) | undefined;
		this.setBusy('gisImport', true);
		try {
			const request: ISoilGisImportRequest = { path: file.fsPath, soilText: serializeSoilReport(this.report) };
			result = await this.commandService.executeCommand<ISoilGisImportResult>(SOIL_GIS_IMPORT_COMMAND, request);
		} catch (error) {
			this.notificationService.error(localize('soil.importFailed', "{0} could not be imported: {1}", basename(file), String(error)));
			return;
		} finally {
			this.setBusy('gisImport', false);
		}
		const text = result?.soilText ?? result?.text;
		const parsed = text ? parseSoilReport(text) : undefined;
		if (parsed?.kind !== 'report' || this.model !== model) {
			this.notificationService.warn(localize('soil.importProblems', "{0} could not be imported: {1}", basename(file), (result?.problems ?? []).join('; ')));
			return;
		}
		this.report = parsed.report;
		const added = parsed.report.boreholes.filter(b => !before.has(b.id)).length;
		this.changed(true);
		const notes = [...result?.problems ?? [], ...result?.notes ?? []];
		this.notificationService.info(notes.length
			? localize('soil.importedWithProblems', "Imported {0} with notes: {1}", basename(file), notes.join('; '))
			: localize('soil.gisImported', "Imported {0}: {1} new borehole(s), the others' positions updated.", basename(file), added));
	}

	/** Writes the GeoPackage to the exports folder and opens it in QGIS. */
	async openInQgis(): Promise<void> {
		const folder = this.exportsFolder();
		if (!folder || !this.qgis?.path || !CommandsRegistry.getCommand(SOIL_OPEN_IN_QGIS_COMMAND)) {
			return;
		}
		const file = await this.exportGis('gpkg', joinPath(folder, 'site-map.gpkg'));
		if (!file) {
			return;
		}
		try {
			const request: IOpenInQgisRequest = { path: file.fsPath };
			const result = await this.commandService.executeCommand<IOpenInQgisResult>(SOIL_OPEN_IN_QGIS_COMMAND, request);
			if (result && !result.ok && result.problems?.length) {
				this.notificationService.warn(localize('soil.qgisFailed', "QGIS could not be started: {0}", result.problems.join('; ')));
			}
		} catch (error) {
			this.notificationService.warn(localize('soil.qgisFailed', "QGIS could not be started: {0}", String(error)));
		}
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
		if (problem.index !== undefined && this.report?.boreholes[problem.index]) {
			// A borehole's problem is fixed on its entry screen, at the step it belongs to.
			if (this.entry && this.entry.index !== problem.index) {
				this.leaveEntry();
			}
			this.selected = problem.index;
			this.reportSelectedOnPurpose = false;
			const step = entryStepOf(problem.path);
			this.editBorehole(step);
			this.entry!.tried = true;
			this.updateEntryProblems();
			const input = problem.path ? this.inputs.get(this.problemKey(problem.index, problem.path)) : undefined;
			input?.focus();
			return;
		}
		this.frame.setPropertiesVisible(true);
		this.render();
		const key = problem.path ? this.problemKey(problem.index, problem.path) : undefined;
		this.propertyInputs.get(key ?? '')?.focus();
	}
}
