/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femResultsView.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { safeIntl } from '../../../../base/common/date.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { FemTableCell, IFemResultList } from '../../../../platform/saengine/common/femSolver.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { EditorInputCapabilities, IEditorOpenContext, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { ChartColor, IChartSeries, renderChart, renderSheet } from './femChart.js';
import { baseReactionTable, closedPmCurve, defaultChartResult, describeMode, elasticDriftLimit, orderLike, extremes, FEM_COLUMN_INTERACTION_COMMAND, floorSpectrumCurves, IFemFloorSpectra, FEM_MEMBER_FORCES_COMMAND, FEM_STORY_RESPONSE_COMMAND, FemAxis2, IFemColumnDiagram, IFemColumnShortening, hingeRowsOf, IFemHingeRow, IFemPushoverAcceptance, IFemPushoverCurve, IFemPushoverTarget, IFemColumnInteraction, IFemDamperDesign, IFemDeviceSuite, IFemIsolationDesign, IFemMemberForces, IFemNonlinearHingeRow, IFemNonlinearHistory, IFemStoryResponse, IFemStoryResult, IFemTimeHistoryDesign, isEarthquakeResult, MemberComponent, memberEnvelope, memberValues, modalTable, modesToReach, profilePeak, spectrumAt, storeyProfile, StoreyQuantity, storeyQuantityLabel, STOREY_QUANTITIES } from './femChartData.js';
import { IFemDesignRequired, IFemSteelRequirement, resultsFolder, runDesignRequired } from './femDesign.js';
import { cableSheet, FEM_NONLINEAR_STABILITY_COMMAND, hasStability, IFemNonlinearStability, pathSeries, pathXLabel, stabilityHelp } from './femNonlinearStability.js';
import { FEM_SPECIAL_STRUCTURES_COMMAND, hasSpecialStructures, IFemSpecialStructures, specialHelp, specialSeries, specialSheet } from './femSpecialStructures.js';
import { assessmentHelp, assessmentTitle, checklistSheet, FEM_EXISTING_ASSESSMENT_COMMAND, hasExistingAssessment, hazardSheet, IFemExistingAssessment, memberSheet, strengthSheet } from './femExisting.js';
import { appendPlannedChips, FemPlanned } from './femPlannedFeatures.js';
import { errorSummary, FEM_RESULT_LIST_COMMAND, IFemRunTracker } from './femResultsBar.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';
import { activeCodeName, defaultClause } from '../../../services/saengineProject/common/activeCodePack.js';
import { activeDisplayUnits, displayFactor, displayUnit, IDisplayUnits, SI_UNITS_SETTING, toDisplay } from '../../../services/saengineProject/common/displayUnits.js';

const chartsIcon = registerIcon('saengine-fem-results-label-icon', Codicon.graph, localize('femResultsLabelIcon', "Icon of the analysis charts and member pages."));

/** The page of the results view: the charts of the run, or one member's details. */
export type FemResultsPage = { readonly kind: 'charts' } | { readonly kind: 'member'; readonly member: string };

function pageKey(page: FemResultsPage): string {
	return page.kind === 'charts' ? 'charts' : `member:${page.member}`;
}

/** Opening the results view at a result: its label as the 3D view's result picker shows it. */
export interface IFemResultsEditorOptions extends IEditorOptions {
	readonly result?: string;
}

/** The analysis charts (`page: charts`) or a member's detail (`page: member`) of an analysis model's last run. */
export class FemResultsInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.femResults';
	/** A member's page: its own input type, so the navigator files it under Model and Analysis (where the member is picked), not under the charts. */
	static readonly MEMBER_ID = 'workbench.input.saengine.femMember';
	static readonly EDITOR_ID = 'workbench.editor.saengine.femResults';

	/** What the tab shows, kept while another tab of its group is shown. */
	readonly state: { picked?: string; directions?: string; response?: IFemStoryResponse; member?: IFemMemberForces } = {};

	constructor(readonly model: URI, readonly page: FemResultsPage) {
		super();
	}

	override get resource(): URI | undefined {
		return undefined;
	}

	override get typeId(): string {
		return this.page.kind === 'member' ? FemResultsInput.MEMBER_ID : FemResultsInput.ID;
	}

	override get editorId(): string {
		return FemResultsInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly;
	}

	override getName(): string {
		return this.page.kind === 'charts'
			? localize('femResults.chartsTab', "Analysis Charts")
			: localize('femResults.memberTab', "Member {0}", this.page.member);
	}

	override getIcon(): ThemeIcon {
		return chartsIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof FemResultsInput && other.model.toString() === this.model.toString() && pageKey(other.page) === pageKey(this.page);
	}
}

export class FemResultsInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: FemResultsInput): string {
		return JSON.stringify({ model: editor.model.toJSON(), page: editor.page });
	}

	deserialize(_instantiationService: IInstantiationService, serialized: string): FemResultsInput {
		const { model, page } = JSON.parse(serialized);
		return new FemResultsInput(URI.revive(model), page?.kind === 'member' && typeof page.member === 'string' ? { kind: 'member', member: page.member } : { kind: 'charts' });
	}
}

// ───────────────────────────── units ─────────────────────────────

interface IUnit {
	readonly scale: number;
	readonly unit: string;
}

/** How the model's values are shown on the charts: SAEngine's SI models as mm, kN, kN·m and g. */
export interface IChartUnits {
	readonly length: IUnit;
	readonly force: IUnit;
	readonly moment: IUnit;
	readonly acceleration: IUnit;
	/** C13b: levels, elevations and distances along a member (the model's m; ft in US units). */
	readonly level: IUnit;
}

/**
 * The chart units of a model's unit system; `display` (C13): the project's display units the
 * charts, legends and readouts show (SI: mm, kN, kN·m). Tables that convert their columns
 * themselves (femChartData.inDisplayUnits) take the SI units (the default).
 */
export function chartUnits(units: string | undefined, display: IDisplayUnits = SI_UNITS_SETTING): IChartUnits {
	if (units?.startsWith('SI')) {
		const shown = (scale: number, unit: string): IUnit => ({ scale: scale * displayFactor(unit, display), unit: displayUnit(unit, display) });
		return {
			length: shown(1000, 'mm'),
			force: shown(1e-3, 'kN'),
			moment: shown(1e-3, 'kN·m'),
			acceleration: { scale: 1 / 9.80665, unit: 'g' },
			level: shown(1, 'm'),
		};
	}
	return { length: { scale: 1, unit: '' }, force: { scale: 1, unit: '' }, moment: { scale: 1, unit: '' }, acceleration: { scale: 1, unit: '' }, level: { scale: 1, unit: 'm' } };
}

/** C13b: a level or a distance [m] as the charts' readouts write it: "3.00 m" (SI), "9.84 ft". */
function levelText(value: number, unit: IUnit): string {
	return unit.unit ? `${(value * unit.scale).toFixed(2)} ${unit.unit}` : value.toFixed(2);
}

function withUnit(label: string, unit: IUnit): string {
	return unit.unit ? `${label} [${unit.unit}]` : label;
}

function fixed(value: number, digits: number): string {
	return formatNumber(value, { decimals: digits });
}

const AXIS_COLORS: { readonly [axis in FemAxis2]: ChartColor } = { X: 'blue', Y: 'orange' };

/** Which directions the storey charts show. */
type Directions = 'XY' | 'X' | 'Y';

const DIRECTIONS: readonly { readonly value: Directions; readonly label: string }[] = [
	{ value: 'XY', label: localize('femResults.dirBoth', "X and Y") },
	{ value: 'X', label: localize('femResults.dirX', "X only") },
	{ value: 'Y', label: localize('femResults.dirY', "Y only") },
];

const ENVELOPE = '__envelope__';

/** A file the backend keeps beside the results once it has worked it out (then it is quick to read). */
const INTERACTION_CACHE = 'column-interaction.json';
const REQUIRED_CACHE = 'design-required.json';

/**
 * The results of an analysis model's last run as an engineer reads them in ETABS or SAP2000:
 *
 * - the Analysis Charts page: the storey response of a case or combination (displacement,
 *   inter-storey drift with the BNBC limit, storey shear, storey forces, overturning moment, X
 *   and Y), the modal periods and mass participation against the 90 % line, the design response
 *   spectrum with the modal periods on it, the base reactions, and the pushover and time-history
 *   curves of a run that has them;
 * - a member's page (a frame member picked in the 3D view): its axial force, shears, torsion,
 *   moments and deflection along it for a case, a combination or the envelope, with the largest
 *   and least values and where they are; a column's P-M interaction diagrams with the demand of
 *   every combination; a beam's required and provided steel.
 *
 * Both follow the run: a new run's results are read again.
 */
export class FemResultsEditor extends EditorPane {

	static readonly ID = FemResultsInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private body!: HTMLElement;
	private resultPicker!: SelectBox;
	private directionPicker!: SelectBox;
	private resultGroup!: HTMLElement;
	private directionGroup!: HTMLElement;

	private units = chartUnits(undefined);
	/** The model's units in SAEngine's SI (mm, kN, kN·m), for the tables that convert to the display units themselves. */
	private siUnits = chartUnits(undefined);
	private response: IFemStoryResponse | undefined;
	private member: IFemMemberForces | undefined;
	private interaction: IFemColumnDiagram | undefined;
	/** The model and member (`<model>#<member>`) whose diagrams the engine is working out. */
	private interactionPending: string | undefined;
	private interactionState: 'idle' | 'loading' | 'none' | 'failed' = 'idle';
	private interactionProblem: string | undefined;
	private required: readonly IFemSteelRequirement[] | undefined;
	private requiredState: 'idle' | 'loading' | 'failed' = 'idle';
	/** Alpha 9 P4: the existing building's assessment of the run (none for a new building). */
	private existing: IFemExistingAssessment | undefined;
	private existingState: 'idle' | 'loading' | 'failed' = 'idle';
	private existingProblem: string | undefined;
	/** Alpha 9 L4: the nonlinear stability analysis (GMNIA, cables) kept beside the run, or being made. */
	private stability: IFemNonlinearStability | undefined;
	private stabilityState: 'idle' | 'loading' | 'running' | 'failed' = 'idle';
	private stabilityProblem: string | undefined;
	/** Alpha 9 L9: the bridges and special structures of Project Settings, kept or being computed. */
	private special: IFemSpecialStructures | undefined;
	private specialState: 'idle' | 'loading' | 'running' | 'failed' = 'idle';
	private specialProblem: string | undefined;
	private problem: string | undefined;
	private loading = false;
	/** The 3D view's result list: its order, and whether the model changed after the run. */
	private listKeys: readonly string[] = [];
	private stale = false;
	private picked: string | undefined;
	/** A result asked for by its label (the 3D view's), picked once the results are read. */
	private requested: string | undefined;
	private directions: Directions = 'XY';
	private request = 0;
	private pickerKeys: string[] = [];

	private readonly inputStore = this._register(new DisposableStore());
	private readonly renderStore = this._register(new DisposableStore());
	// A run rewrites its manifest as cases finish: read the results again once it has ended.
	private readonly reload = this._register(new RunOnceScheduler(() => {
		const input = this.typed;
		if (input && !this.runTracker.get(input.model)) {
			void this.load();
		}
	}, 600));
	private readonly refreshAction = this._register(new Action('saengine.fem.results.refresh', localize('femResults.refresh', "Read the Results Again"), ThemeIcon.asClassName(Codicon.refresh), true, async () => this.load()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IFileService private readonly fileService: IFileService,
		@IFemRunTracker private readonly runTracker: IFemRunTracker,
	) {
		super(FemResultsEditor.ID, group, telemetryService, themeService, storageService);
	}

	private get typed(): FemResultsInput | undefined {
		return this.input instanceof FemResultsInput ? this.input : undefined;
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: FemResultsEditor.ID,
			ariaLabel: localize('femResults.toolbar', "Analysis Results"),
		}));
		this.frame.element.classList.add('saengine-fem-results-view');

		this.resultGroup = append(this.frame.controlsSlot, $('.fem-results-view-group'));
		append(this.resultGroup, $('span.sa-frame-label', undefined, localize('femResults.result', "Result")));
		this.resultPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.resultPickAria', "Load case or combination shown") }));
		this.resultPicker.render(append(this.resultGroup, $('.fem-results-view-select.result')));
		this._register(this.resultPicker.onDidSelect(({ index }) => {
			this.setPicked(this.pickerKeys[index]);
			this.render();
		}));

		this.directionGroup = append(this.frame.controlsSlot, $('.fem-results-view-group'));
		append(this.directionGroup, $('span.sa-frame-label', undefined, localize('femResults.direction', "Direction")));
		this.directionPicker = this._register(new SelectBox(DIRECTIONS.map<ISelectOptionItem>(d => ({ text: d.label })), 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.directionAria', "Directions shown") }));
		this.directionPicker.render(append(this.directionGroup, $('.fem-results-view-select.direction')));
		this._register(this.directionPicker.onDidSelect(({ index }) => {
			this.directions = DIRECTIONS[index]?.value ?? 'XY';
			if (this.typed) {
				this.typed.state.directions = this.directions;
			}
			this.render();
		}));

		this.frame.setActions([this.refreshAction]);
		this.body = $('.fem-results-view-body', { tabIndex: 0 });
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode());
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this._register(addDisposableListener(this.body, EventType.KEY_DOWN, e => this.onKeyDown(new StandardKeyboardEvent(e))));
	}

	/** Page Up/Down, Home/End, the arrows and Space scroll the page, as in a document. */
	private onKeyDown(event: StandardKeyboardEvent): void {
		const target = event.target as HTMLElement;
		if (target !== this.body && target.closest('button, input, select, textarea, a')) {
			return;
		}
		const { height, scrollHeight } = this.scrollable.getScrollDimensions();
		const top = this.scrollable.getScrollPosition().scrollTop;
		const page = Math.max(40, height - 40);
		let next: number | undefined;
		switch (event.keyCode) {
			case KeyCode.PageDown: next = top + page; break;
			case KeyCode.PageUp: next = top - page; break;
			case KeyCode.Space: next = event.shiftKey ? top - page : top + page; break;
			case KeyCode.DownArrow: next = top + 40; break;
			case KeyCode.UpArrow: next = top - 40; break;
			case KeyCode.Home: next = 0; break;
			case KeyCode.End: next = scrollHeight; break;
		}
		if (next !== undefined) {
			event.preventDefault();
			event.stopPropagation();
			this.scrollable.setScrollPosition({ scrollTop: Math.max(0, Math.min(next, scrollHeight - height)) });
		}
	}

	override async setInput(input: FemResultsInput, options: IFemResultsEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputStore.clear();
		// Shown again: what was read is shown at once while it is read again (a busy backend
		// can take a minute to answer).
		this.response = input.state.response;
		this.member = input.state.member;
		this.interaction = undefined;
		this.required = undefined;
		this.interactionState = 'idle';
		this.requiredState = 'idle';
		// Shown again (another tab was in front): the result and directions it showed.
		this.picked = input.state.picked;
		this.requested = options?.result;
		this.directions = DIRECTIONS.find(d => d.value === input.state.directions)?.value ?? 'XY';
		this.directionPicker.select(DIRECTIONS.findIndex(d => d.value === this.directions));
		this.frame.setTitle(input.getName());
		// A new run deletes and writes the results folder again: its manifest is written last.
		const folder = resultsFolder(input.model);
		const watcher = this.fileService.createWatcher(folder, { recursive: false, excludes: [] });
		this.inputStore.add(watcher);
		this.inputStore.add(watcher.onDidChange(e => {
			if (e.contains(joinPath(folder, 'manifest.json'))) {
				this.reload.schedule();
			}
		}));
		const parentWatcher = this.fileService.createWatcher(joinPath(folder, '..'), { recursive: false, excludes: [] });
		this.inputStore.add(parentWatcher);
		this.inputStore.add(parentWatcher.onDidChange(e => {
			if (e.contains(folder)) {
				this.reload.schedule();
			}
		}));
		this.inputStore.add(this.runTracker.onDidChange(model => {
			if (model.toString() === input.model.toString() && !this.runTracker.get(model)) {
				this.reload.schedule(); // the run ended
			}
		}));
		// Not awaited: the editor opens at once and says what it is working out (the storey
		// response of a large model takes a while); a later load supersedes this one.
		void this.load();
	}

	/** Opened again at a result (a member picked in 3D under another combination). */
	override setOptions(options: IFemResultsEditorOptions | undefined): void {
		super.setOptions(options);
		if (options?.result) {
			this.requested = options.result;
			this.render();
		}
	}

	override clearInput(): void {
		this.inputStore.clear();
		this.request++;
		super.clearInput();
	}

	private setPicked(key: string | undefined): void {
		this.picked = key;
		if (this.typed) {
			this.typed.state.picked = key;
		}
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
		this.scrollable.scanDomNode();
	}

	override focus(): void {
		super.focus();
		this.body.focus();
	}

	// ───────────────────────────── loading ─────────────────────────────

	private async load(): Promise<void> {
		const input = this.typed;
		if (!input) {
			return;
		}
		const request = ++this.request;
		this.loading = true;
		this.problem = undefined;
		this.render();
		try {
			const meta = await this.readUnits(input.model);
			this.units = chartUnits(meta, activeDisplayUnits());
			this.siUnits = chartUnits(meta);
			// The 3D view's list: the same order in both pickers, and whether the results are stale.
			const list = await this.commandService.executeCommand<IFemResultList>(FEM_RESULT_LIST_COMMAND, input.model).catch(() => undefined);
			this.listKeys = list?.results.map(r => r.key) ?? [];
			this.stale = !!list?.stale;
			if (input.page.kind === 'charts') {
				const response = await this.commandService.executeCommand<IFemStoryResponse>(FEM_STORY_RESPONSE_COMMAND, input.model);
				if (request !== this.request) {
					return;
				}
				this.response = input.state.response = response;
				this.existing = undefined;
				this.existingState = 'idle';
				this.stability = undefined;
				this.stabilityState = 'idle';
				this.special = undefined;
				this.specialState = 'idle';
			} else {
				const member = await this.commandService.executeCommand<IFemMemberForces>(FEM_MEMBER_FORCES_COMMAND, input.model, input.page.member);
				if (request !== this.request) {
					return;
				}
				this.member = input.state.member = member;
				this.interaction = undefined;
				// The diagrams still being worked out for this member stay "loading" (B10-29 of
				// usability walk 3: the page refreshed during the wait and fell back to the button
				// with no message while the engine went on).
				this.interactionState = this.interactionPending === `${input.model.toString()}#${input.page.member}` ? 'loading' : 'idle';
				this.required = undefined;
				this.requiredState = 'idle';
			}
		} catch (error) {
			if (request === this.request) {
				this.problem = errorSummary(error);
			}
		}
		if (request !== this.request) {
			return;
		}
		this.loading = false;
		this.render();
		if (input.page.kind === 'charts' && this.response) {
			void this.loadExisting();
			void this.loadStability(false);
			void this.loadSpecial(false);
		}
		// What the backend has already worked out for this run is shown at once; working it out
		// takes minutes, so that waits for the engineer's click.
		if (input.page.kind === 'member' && this.member) {
			const folder = resultsFolder(input.model);
			if (this.member.kind === 'column' && await this.fileService.exists(joinPath(folder, INTERACTION_CACHE))) {
				void this.loadInteraction();
			}
			if (this.member.kind === 'beam' && await this.fileService.exists(joinPath(folder, REQUIRED_CACHE))) {
				void this.loadRequired();
			}
		}
	}

	private async readUnits(model: URI): Promise<string | undefined> {
		try {
			const content = await this.fileService.readFile(model);
			const parsed = JSON.parse(content.value.toString());
			return typeof parsed?.meta?.units === 'string' ? parsed.meta.units : undefined;
		} catch {
			return undefined;
		}
	}

	private async loadInteraction(): Promise<void> {
		const input = this.typed;
		if (!input || input.page.kind !== 'member' || this.interactionState === 'loading') {
			return;
		}
		const member = input.page.member;
		const model = input.model.toString();
		// The page may refresh during the minutes this takes (the results' files change): the
		// answer still belongs to it while it shows the same member of the same model (N-X16 of
		// usability walk 2: 282 s of work, then the button again and nothing shown).
		const current = () => {
			const shown = this.typed;
			return !!shown && shown.page.kind === 'member' && shown.page.member === member && shown.model.toString() === model;
		};
		this.interactionState = 'loading';
		const pending = this.interactionPending = `${model}#${member}`;
		this.render();
		try {
			const answer = await this.commandService.executeCommand<IFemColumnInteraction>(FEM_COLUMN_INTERACTION_COMMAND, input.model, member);
			if (this.interactionPending === pending) {
				this.interactionPending = undefined;
			}
			if (!current()) {
				return;
			}
			this.interaction = answer?.columns[member];
			this.interactionState = this.interaction ? 'idle' : 'none';
		} catch (error) {
			if (this.interactionPending === pending) {
				this.interactionPending = undefined;
			}
			if (!current()) {
				return;
			}
			this.interactionState = 'failed';
			this.interactionProblem = errorSummary(error);
		}
		this.render();
	}

	/**
	 * Alpha 9 P4: the existing building's assessment of the run, worked out after the charts
	 * show (the linear procedure forms every member's demands, seconds to a minute); a new
	 * building answers at once with none.
	 */
	private async loadExisting(): Promise<void> {
		const input = this.typed;
		if (!input || input.page.kind !== 'charts' || this.existingState === 'loading') {
			return;
		}
		const request = this.request;
		this.existingState = 'loading';
		try {
			const found = await this.commandService.executeCommand<IFemExistingAssessment>(FEM_EXISTING_ASSESSMENT_COMMAND, input.model);
			if (request !== this.request) {
				return;
			}
			this.existing = found;
			this.existingState = 'idle';
		} catch (error) {
			if (request !== this.request) {
				return;
			}
			this.existingState = 'failed';
			this.existingProblem = errorSummary(error);
		}
		this.render();
	}

	/**
	 * Alpha 9 L4: the nonlinear stability analysis of the run: the one kept beside the results
	 * at once (`run` false), a new one on the engineer's click (minutes).
	 */
	private async loadStability(run: boolean): Promise<void> {
		const input = this.typed;
		if (!input || input.page.kind !== 'charts' || this.stabilityState === 'loading' || this.stabilityState === 'running') {
			return;
		}
		const request = this.request;
		this.stabilityState = run ? 'running' : 'loading';
		if (run) {
			this.render();
		}
		try {
			const found = await this.commandService.executeCommand<IFemNonlinearStability>(FEM_NONLINEAR_STABILITY_COMMAND, input.model, run);
			if (request !== this.request) {
				return;
			}
			this.stability = found;
			this.stabilityState = 'idle';
		} catch (error) {
			if (request !== this.request) {
				return;
			}
			this.stabilityState = 'failed';
			this.stabilityProblem = errorSummary(error);
		}
		this.render();
	}

	/**
	 * Alpha 9 L9: the bridges and special structures of Project Settings: the last run kept
	 * beside the analysis model at once (`run` false), a new one on the engineer's click.
	 */
	private async loadSpecial(run: boolean): Promise<void> {
		const input = this.typed;
		if (!input || input.page.kind !== 'charts' || this.specialState === 'loading' || this.specialState === 'running') {
			return;
		}
		const request = this.request;
		this.specialState = run ? 'running' : 'loading';
		if (run) {
			this.render();
		}
		try {
			const found = await this.commandService.executeCommand<IFemSpecialStructures>(FEM_SPECIAL_STRUCTURES_COMMAND, input.model, run);
			if (request !== this.request) {
				return;
			}
			this.special = found;
			this.specialState = 'idle';
		} catch (error) {
			if (request !== this.request) {
				return;
			}
			this.specialState = 'failed';
			this.specialProblem = errorSummary(error);
		}
		this.render();
	}

	/** Alpha 9 L9: each bridge and special structure's checks, tables and charts. */
	private renderSpecial(): void {
		const found = this.special;
		if (!found?.configured && this.specialState !== 'running' && this.specialState !== 'failed') {
			return; // none in the project settings
		}
		const title = localize('femResults.specialHeading', "Bridges and Special Structures");
		const section = this.section(title, found ? specialHelp(found) : undefined);
		if (this.specialState === 'running') {
			append(section, $('.fem-results-note', undefined, localize('femResults.specialRunning', "Computing the bridges and special structures... (a deck grillage takes a while)")));
			return;
		}
		if (this.specialState === 'failed') {
			append(section, $('.fem-results-note', undefined, localize('femResults.specialFailed', "They could not be computed: {0}", this.specialProblem ?? '')));
		} else if (found && !found.available && found.reason) {
			append(section, $('.fem-results-note', undefined, localize('femResults.specialNone', "No results: {0}", found.reason)));
		}
		if (hasSpecialStructures(found)) {
			for (const structure of found.sections) {
				append(section, $('h3.fem-results-subheading', undefined, structure.title));
				if (structure.error) {
					append(section, $('.fem-results-note', undefined, localize('femResults.specialError', "Not computed: {0}", structure.error)));
					continue;
				}
				if (structure.charts.length) {
					const grid = this.grid(section);
					for (const chart of structure.charts) {
						renderChart(grid, { title: chart.title, xLabel: chart.xLabel, yLabel: chart.yLabel, series: specialSeries(chart) });
					}
				}
				for (const sheet of structure.sheets) {
					if (sheet.rows.length) {
						append(section, $('.fem-results-help', undefined, sheet.name));
						renderSheet(section, specialSheet(sheet));
					}
				}
				if (structure.notes.length) {
					append(section, $('.fem-results-note', undefined, structure.notes.join(' ')));
				}
			}
		}
		const button = this.renderStore.add(new Button(section, { ...defaultButtonStyles, supportIcons: true }));
		button.label = `$(${Codicon.graph.id}) ${hasSpecialStructures(found) ? localize('femResults.specialAgain', "Compute the Bridges and Special Structures Again") : localize('femResults.specialRun', "Compute the Bridges and Special Structures")}`;
		this.renderStore.add(button.onDidClick(() => void this.loadSpecial(true)));
	}

	/** Alpha 9 L4: the load-displacement path, λu against αcr, and the cables' sag and tension. */
	private renderStability(): void {
		const found = this.stability;
		if (!found?.configured && this.stabilityState !== 'running' && this.stabilityState !== 'failed') {
			return; // not set in the project settings: nothing to offer
		}
		const title = localize('femResults.stabilityHeading', "Nonlinear Stability (GMNIA) and Cables");
		const section = this.section(title, hasStability(found) ? stabilityHelp(found) : localize('femResults.stabilityAbout', "Nonlinear buckling with imperfections of the steel frames and the large-displacement analysis of cables, under the combination set in Project Settings, Analysis, Nonlinear stability."));
		if (this.stabilityState === 'running') {
			append(section, $('.fem-results-note', undefined, localize('femResults.stabilityRunning', "Following the load-displacement path... (minutes for a large model)")));
			return;
		}
		if (this.stabilityState === 'failed') {
			append(section, $('.fem-results-note', undefined, localize('femResults.stabilityFailed', "The nonlinear stability analysis could not be made: {0}", this.stabilityProblem ?? '')));
		} else if (found && !found.available && found.reason && found.reason !== 'not run yet') {
			append(section, $('.fem-results-note', undefined, localize('femResults.stabilityNone', "No analysis: {0}", found.reason)));
		}
		if (hasStability(found)) {
			const guides = [{ axis: 'y' as const, value: found.required ?? 1, label: localize('femResults.stabilityRequired', "required"), color: 'foreground' as const }];
			if (found.alphaCr) {
				guides.push({ axis: 'y' as const, value: found.alphaCr, label: 'αcr', color: 'foreground' as const });
			}
			renderChart(this.grid(section), {
				title: localize('femResults.stabilityPath', "Load-Displacement Path"),
				xLabel: pathXLabel(found),
				yLabel: localize('femResults.stabilityFactor', "Load factor λ"),
				series: pathSeries(found),
				guides,
				caption: localize('femResults.stabilityCaption', "λu = {0}", (found.limitFactor ?? 0).toFixed(3)),
			});
			if (found.cables?.length) {
				renderSheet(section, cableSheet(found));
			}
			if (found.notes?.length) {
				append(section, $('.fem-results-note', undefined, found.notes.join(' ')));
			}
		}
		const button = this.renderStore.add(new Button(section, { ...defaultButtonStyles, supportIcons: true }));
		button.label = `$(${Codicon.graph.id}) ${hasStability(found) ? localize('femResults.stabilityAgain', "Run the Nonlinear Stability Analysis Again") : localize('femResults.stabilityRun', "Run the Nonlinear Stability Analysis")}`;
		this.renderStore.add(button.onDidClick(() => void this.loadStability(true)));
	}

	/** Alpha 9 P4: the existing building's assessment and its retrofit's before and after. */
	private renderExisting(): void {
		if (this.existingState === 'failed') {
			const section = this.section(localize('femResults.existingHeading', "Existing Building"));
			append(section, $('.fem-results-note', undefined, localize('femResults.existingFailed', "The assessment could not be worked out: {0}", this.existingProblem ?? '')));
			return;
		}
		const found = this.existing;
		if (!hasExistingAssessment(found)) {
			return;
		}
		if (!found.available) {
			const section = this.section(localize('femResults.existingHeading', "Existing Building"));
			append(section, $('.fem-results-note', undefined, localize('femResults.existingNone', "No assessment: {0}", found.reason ?? '')));
			return;
		}
		const section = this.section(assessmentTitle(found), assessmentHelp(found));
		if (found.strengths?.length) {
			renderSheet(section, strengthSheet(found));
		}
		if (found.hazards?.length) {
			renderSheet(section, hazardSheet(found));
		}
		const members = memberSheet(found);
		renderSheet(section, { ...members, notes: [...(members.notes ?? []), ...(found.notes ?? [])] });
		if (found.checklist?.length) {
			renderSheet(section, checklistSheet(found));
		}
		// What stays planned: masonry buildings.
		this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.existingMasonry], this.commandService));
	}

	private async loadRequired(): Promise<void> {
		const input = this.typed;
		if (!input || input.page.kind !== 'member' || this.requiredState === 'loading') {
			return;
		}
		const request = this.request;
		const member = input.page.member;
		this.requiredState = 'loading';
		this.render();
		let required: IFemDesignRequired | undefined;
		try {
			required = await runDesignRequired(this.commandService, input.model);
		} catch {
			required = undefined;
		}
		if (request !== this.request) {
			return;
		}
		this.requiredState = required ? 'idle' : 'failed';
		this.required = required?.elements.filter(row => row.element === member);
		this.render();
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		this.renderStore.clear();
		clearNode(this.body);
		const input = this.typed;
		if (!input) {
			return;
		}
		this.frame.setStatus(this.status());
		if (this.loading && !this.response && !this.member) {
			this.frame.showProgress();
		} else {
			this.frame.hideProgress();
		}
		if (this.problem && !(this.response || this.member)) {
			this.frame.setEmpty({
				icon: Codicon.graph,
				title: localize('femResults.noResults', "No results to chart"),
				text: this.problem,
			});
			this.updatePickers([]);
			this.scrollable.scanDomNode();
			return;
		}
		this.frame.setEmpty(undefined);
		if (input.page.kind === 'charts') {
			this.renderCharts();
		} else {
			this.renderMember(input.page.member);
		}
		this.scrollable.scanDomNode();
	}

	private status(): IEditorFrameStatus | undefined {
		if (this.loading) {
			return {
				busy: true,
				text: this.typed?.page.kind === 'member'
					? localize('femResults.readingMember', "Reading the member's forces from the last run...")
					: localize('femResults.readingCharts', "Working out the storey response of every case and combination..."),
			};
		}
		if (this.problem) {
			return { severity: 'error', text: this.problem };
		}
		const notes = this.response?.notes ?? this.member?.notes ?? [];
		if (this.stale) {
			return { severity: 'warning', text: [localize('femResults.staleStatus', "The model changed after this analysis ran: these results are out of date until it is run again."), ...notes].join(' ') };
		}
		return notes.length ? { text: notes.join(' ') } : undefined;
	}

	/**
	 * The result picker's options; the result shown stays picked, else the one asked for (by
	 * its label), else `fallback`, else the first.
	 */
	private updatePickers(options: readonly { readonly key: string; readonly label: string }[], fallback?: string): void {
		this.pickerKeys = options.map(o => o.key);
		if (options.length && this.requested !== undefined) {
			const asked = options.find(o => o.label === this.requested);
			this.requested = undefined;
			if (asked) {
				this.setPicked(asked.key);
			}
		}
		let index = this.pickerKeys.indexOf(this.picked ?? '');
		if (index < 0) {
			index = Math.max(0, this.pickerKeys.indexOf(fallback ?? ''));
		}
		if (options.length) {
			this.setPicked(this.pickerKeys[index]);
		}
		this.resultPicker.setOptions(options.map<ISelectOptionItem>(o => ({ text: o.label })), index);
		this.resultGroup.classList.toggle('hidden', !options.length);
	}

	/** A length or force of the model in the charts' units, with the unit. */
	private format(kind: 'length' | 'force', value: number): string {
		const unit = this.units[kind];
		const text = fixed(value * unit.scale, kind === 'length' ? 1 : 0);
		return unit.unit ? `${text} ${unit.unit}` : text;
	}

	/**
	 * A pushover: its capacity curve with the bilinear fit and the target displacement (and the
	 * 125 % and 150 % marks the code pack sets), the values of the target displacement, and the
	 * members' acceptance at the target, by the code pack's methods.
	 */
	private renderPushover(curve: IFemPushoverCurve): void {
		const section = this.section(localize('femResults.pushoverHeading', "Pushover: {0}", curve.label));
		const length = this.units.length.scale, force = this.units.force.scale;
		const start = curve.displacement[0] ?? 0;
		const target = curve.target?.available ? curve.target : undefined;
		const series: IChartSeries[] = [{ name: curve.label, color: 'blue', points: curve.displacement.map((d, k) => [d * length, Math.abs(curve.shear[k]) * force]) }];
		const guides: { axis: 'x'; value: number; label: string; color?: ChartColor }[] = [];
		if (target?.bilinear && target.target !== undefined) {
			series.push({ name: localize('femResults.bilinear', "Bilinear fit"), color: 'orange', style: 'dashed', points: target.bilinear.map(p => [(start + p[0]) * length, p[1] * force]) });
			// P3: FEMA 440 finds a performance point; the other methods a target displacement.
			const mark = target.method === 'equivalentLinearization' ? localize('femResults.performanceMark', "performance point") : localize('femResults.targetMark', "δt");
			guides.push({ axis: 'x', value: (start + target.target) * length, label: target.hazards?.length ? `${mark} ${target.hazards[0].id}` : mark, color: 'red' });
			for (const hazard of (target.hazards ?? []).slice(1)) {
				if (!hazard.beyondCurve) {
					guides.push({ axis: 'x', value: (start + hazard.target) * length, label: `δt ${hazard.id}`, color: 'red' });
				}
			}
			if (target.noDropTo !== undefined && target.noDropTo !== null) {
				guides.push({ axis: 'x', value: (start + target.noDropTo) * length, label: localize('femResults.noDropMark', "no drop"), color: 'foreground' });
			}
			if (target.required !== undefined) {
				guides.push({ axis: 'x', value: (start + target.required) * length, label: localize('femResults.pushToMark', "push to"), color: 'foreground' });
			}
		}
		renderChart(this.grid(section), {
			title: localize('femResults.capacity', "Capacity Curve"),
			xLabel: withUnit(localize('femResults.controlDisp', "Control displacement"), this.units.length),
			yLabel: withUnit(localize('femResults.baseShear', "Base shear"), this.units.force),
			series,
			guides,
			caption: target?.target !== undefined ? localize('femResults.targetCaption', "Target displacement δt = {0}", this.format('length', target.target)) : undefined,
		});
		if (curve.target && !curve.target.available) {
			append(section, $('.fem-results-note', undefined, localize('femResults.noTarget', "No target displacement: {0}", curve.target.reason ?? '')));
		}
		if (target) {
			const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no");
			const clauses = target.clauses ?? {};
			const value = (v: number | undefined, digits: number) => v === undefined ? '' : v.toFixed(digits);
			renderSheet(section, {
				name: localize('femResults.targetTable', "Target displacement"),
				columns: [localize('femResults.quantityCol', "Quantity"), localize('femResults.valueCol', "Value"), localize('femResults.clauseCol', "Clause")],
				rows: target.method !== undefined && target.method !== 'coefficient' ? this.otherTargetRows(target) : [
					[localize('femResults.t1', "Period of the first increment T1 [s]"), value(target.T1, 3), ''],
					[localize('femResults.vy', "Effective yield strength Vy"), this.format('force', target.Vy ?? 0), ''],
					[localize('femResults.dy', "Effective yield displacement δy"), this.format('length', target.dy ?? 0), ''],
					[localize('femResults.te', "Effective period Te [s]"), value(target.Te, 3), clauses.period ?? ''],
					[localize('femResults.sa', "Spectral acceleration Sa(Te) [g]"), value(target.Sa, 3), ''],
					[localize('femResults.c0', "C0"), value(target.C0, 3), clauses.c0 ?? ''],
					[localize('femResults.rd', "Rd"), value(target.Rd, 3), clauses.rd ?? ''],
					[localize('femResults.c1', "C1"), value(target.C1, 3), clauses.c1 ?? ''],
					[localize('femResults.dt', "Target displacement δt"), this.format('length', target.target ?? 0), clauses.target ?? ''],
					[localize('femResults.pushedTo', "Pushed to (at least {0})", this.format('length', target.required ?? 0)), this.format('length', target.pushedTo ?? 0) + ' ' + (target.reached ? yes : no), clauses.pushTo ?? ''],
					[localize('femResults.noDrop', "No drop of the base shear up to {0}", this.format('length', target.noDropTo ?? 0)), target.noDrop === null || target.noDrop === undefined ? localize('femResults.notReached', "not reached") : target.noDrop ? yes : no, clauses.noDrop ?? ''],
				],
				notes: [...(target.notes ?? []), ...(target.note ? [target.note] : [])],
			});
		}
		const acceptance = curve.acceptance;
		const hinges = hingeRowsOf(acceptance);
		if (acceptance && hinges) {
			this.renderHinges(section, acceptance, hinges);
		} else if (acceptance?.available && acceptance.rows) {
			const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no");
			const kinds: { [kind: string]: string } = {
				concrete: localize('femResults.fibreConcrete', "concrete"),
				bar: localize('femResults.fibreBar', "reinforcing bar"),
				steel: localize('femResults.fibreSteel', "steel"),
			};
			renderSheet(section, {
				name: localize('femResults.acceptanceTable', "Member acceptance at the target displacement ({0} of {1} members fail)", acceptance.failed ?? 0, acceptance.rows.length),
				columns: [localize('femResults.memberCol', "Member"), localize('femResults.endCol', "End"), localize('femResults.fibreCol', "Fibre"), localize('femResults.strainCol', "Strain"), localize('femResults.limitCol', "Limit"), localize('femResults.ratioCol', "Ratio"), localize('femResults.okCol', "OK")],
				rows: acceptance.rows.map(r => [r.member, r.end, kinds[r.fibre] ?? r.fibre, r.strain, r.limit, r.ratio, r.ok ? yes : no]),
				notes: [...(acceptance.clause ? [acceptance.clause] : []), ...(acceptance.notes ?? []), ...(acceptance.note ? [acceptance.note] : [])],
			});
		} else if (acceptance && !acceptance.available) {
			append(section, $('.fem-results-note', undefined, localize('femResults.noAcceptance', "No member acceptance: {0}", acceptance.reason ?? '')));
		}
		// What stays planned: walls with openings as nonlinear piers and spandrels.
		this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.fibreWalls], this.commandService));
	}

	/** P3: the rows of a target displacement found by another method than `coefficient`. */
	private otherTargetRows(target: IFemPushoverTarget): FemTableCell[][] {
		const clauses = target.clauses ?? {};
		const value = (v: number | undefined, digits: number) => v === undefined ? '' : v.toFixed(digits);
		const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no");
		const rows: FemTableCell[][] = [[localize('femResults.t1', "Period of the first increment T1 [s]"), value(target.T1, 3), '']];
		if (target.method === 'n2') {
			rows.push(
				[localize('femResults.gamma', "Transformation factor Γ"), value(target.Gamma, 3), clauses.sdof ?? ''],
				[localize('femResults.mStar', "Equivalent mass m* [t]"), value(target.mStar === undefined ? undefined : target.mStar / 1e3, 1), clauses.sdof ?? ''],
				[localize('femResults.fyStar', "Yield force Fy*"), this.format('force', target.FyStar ?? 0), clauses.idealisation ?? ''],
				[localize('femResults.dyStar', "Yield displacement dy*"), this.format('length', target.dyStar ?? 0), clauses.idealisation ?? ''],
				[localize('femResults.tStar', "Period T* [s]"), value(target.Tstar, 3), clauses.period ?? ''],
				[localize('femResults.se', "Elastic spectral acceleration Se(T*) [g]"), value(target.Se, 3), ''],
				[localize('femResults.det', "Elastic displacement det*"), this.format('length', target.det ?? 0), clauses.target ?? ''],
				[localize('femResults.qu', "qu"), value(target.qu, 2), clauses.target ?? ''],
				[localize('femResults.dtStar', "dt*"), this.format('length', target.dtStar ?? 0), clauses.target ?? ''],
			);
		} else {
			rows.push(
				[localize('femResults.vy', "Effective yield strength Vy"), this.format('force', target.Vy ?? 0), ''],
				[localize('femResults.dy', "Effective yield displacement δy"), this.format('length', target.dy ?? 0), ''],
				[localize('femResults.te', "Effective period Te [s]"), value(target.Te, 3), clauses.period ?? ''],
				[localize('femResults.sa', "Spectral acceleration Sa(Te) [g]"), value(target.Sa, 3), ''],
			);
			if (target.method === 'displacementCoefficient') {
				rows.push(
					[localize('femResults.c0', "C0"), value(target.C0, 3), clauses.c0 ?? ''],
					[localize('femResults.mu', "Strength ratio μ"), value(target.mu, 2), clauses.rd ?? ''],
					[localize('femResults.c1Site', "C1 (site factor a = {0})", value(target.a, 0)), value(target.C1, 3), clauses.c1 ?? ''],
					[localize('femResults.c2', "C2"), value(target.C2, 3), clauses.c2 ?? ''],
					[localize('femResults.cm', "Cm"), value(target.Cm, 2), ''],
				);
			} else {
				rows.push(
					[localize('femResults.t0', "Initial period T0 [s]"), value(target.T0, 3), clauses.damping ?? ''],
					[localize('femResults.ductility', "Ductility μ"), value(target.mu, 2), clauses.damping ?? ''],
					[localize('femResults.beta', "Effective damping βeff [%]"), value(target.beta, 1), clauses.damping ?? ''],
					[localize('femResults.reduction', "Spectral reduction B"), value(target.B, 3), clauses.damping ?? ''],
					[localize('femResults.pf', "PF, α1"), `${value(target.PF, 3)}, ${value(target.alpha1, 3)}`, clauses.sdof ?? ''],
				);
			}
		}
		rows.push(
			[target.method === 'equivalentLinearization' ? localize('femResults.performancePoint', "Performance point δt") : localize('femResults.dt', "Target displacement δt"), this.format('length', target.target ?? 0), clauses.target ?? ''],
			[localize('femResults.pushedTo', "Pushed to (at least {0})", this.format('length', target.required ?? 0)), this.format('length', target.pushedTo ?? 0) + ' ' + (target.reached ? yes : no), clauses.pushTo ?? ''],
		);
		for (const hazard of (target.hazards ?? []).slice(1)) {
			rows.push([localize('femResults.hazardTarget', "Target displacement at {0} ({1})", hazard.label || hazard.id, hazard.level), this.format('length', hazard.target) + (hazard.beyondCurve ? ' ' + localize('femResults.beyondCurve', "(beyond the curve)") : ''), clauses.hazards ?? '']);
		}
		return rows;
	}

	/**
	 * P3: the hinges (`fem/hinges.py`) at the target displacement: each hazard level against its
	 * performance level, and the hinges by their ratio to the level checked, with their state.
	 */
	private renderHinges(section: HTMLElement, acceptance: IFemPushoverAcceptance, rows: readonly IFemHingeRow[]): void {
		const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no");
		const level = acceptance.checkedLevel ?? '';
		const labels = new Map((acceptance.levels ?? []).map(l => [l.id, l.label]));
		const hazards = acceptance.hazards ?? [];
		if (hazards.length) {
			renderSheet(section, {
				name: localize('femResults.hazardTable', "Performance by hazard level"),
				columns: [localize('femResults.hazardCol', "Hazard level"), localize('femResults.performanceLevelCol', "Performance level"), localize('femResults.failedCol', "Hinges exceeding"), localize('femResults.worstCol', "Largest ratio"), localize('femResults.okCol', "OK")],
				rows: hazards.map(h => [h.label || h.id, labels.get(h.level) ?? h.level, h.available ? (h.failed ?? 0) : localize('femResults.notReached', "not reached"), h.worst === null || h.worst === undefined ? '' : Number(h.worst.toFixed(3)), h.ok === null || h.ok === undefined ? '' : h.ok ? yes : no]),
			});
		}
		const covered = rows.filter(r => r.covered);
		const failed = covered.filter(r => !r.ok).length;
		const limit = (r: IFemHingeRow) => r.limits?.[level];
		renderSheet(section, {
			name: localize('femResults.hingeTable', "Hinges at the target displacement against {0} ({1} of {2} exceed it)", labels.get(level) ?? level, failed, covered.length),
			columns: [
				localize('femResults.hingeCol', "Hinge"), localize('femResults.componentCol', "Component"), localize('femResults.stateCol', "State"), localize('femResults.backboneCol', "Backbone"),
				localize('femResults.demandCol', "Demand"), localize('femResults.limitCol', "Limit"), localize('femResults.ratioCol', "Ratio"), localize('femResults.okCol', "OK"),
			],
			rows: rows.map(r => r.covered
				? [r.hinge, r.component, r.state ?? '', r.backbone ?? '', Number(r.demand.toPrecision(4)), limit(r) === undefined ? '' : Number(limit(r)!.toPrecision(4)), r.ratio === null ? '' : Number(r.ratio.toFixed(3)), r.ok ? yes : no]
				: [r.hinge, r.component, localize('femResults.notCovered', "not covered"), '', Number(r.demand.toPrecision(4)), '', '', r.reason ?? '']),
			notes: [
				localize('femResults.hingeMeasure', "Demand and limit are in the hinge's own measure: plastic or chord rotation [rad] for concrete, multiples of θy (or of a brace's yield or buckling deformation) for steel, the storey drift ratio for walls controlled by shear. State: the lowest performance level the hinge still meets; backbone: B (not yielded), B-C (up to a), C-E (up to b), E+ (beyond b)."),
				...(acceptance.clause ? [acceptance.clause] : []), ...(acceptance.notes ?? []), ...(acceptance.note ? [acceptance.note] : []),
			],
		});
	}

	private section(title: string, help?: string): HTMLElement {
		const section = append(this.body, $('section.fem-results-section'));
		append(section, $('h2.fem-results-heading', undefined, title));
		if (help) {
			append(section, $('.fem-results-help', undefined, help));
		}
		return section;
	}

	private grid(section: HTMLElement): HTMLElement {
		return append(section, $('.fem-results-grid'));
	}

	// ───────────────────────────── the charts page ─────────────────────────────

	private renderCharts(): void {
		const response = this.response;
		this.directionGroup.classList.remove('hidden');
		if (!response) {
			this.updatePickers([]);
			return;
		}
		// As the 3D view lists them; a lateral result first, since gravity has no storey response.
		const ordered = orderLike(response.results, this.listKeys);
		this.updatePickers(ordered.map(r => ({ key: r.key, label: r.label })), defaultChartResult(ordered)?.key);
		const result = ordered.find(r => r.key === this.picked);
		if (result) {
			this.renderStoreys(response, result);
		} else {
			append(this.section(localize('femResults.storeyHeading', "Storey Response")), $('.fem-results-note', undefined, localize('femResults.noStoreys', "The run has no static case, combination or response spectrum case to plot.")));
		}
		if (response.modal) {
			this.renderModal(response);
		}
		if (response.spectrum) {
			this.renderSpectrum(response);
		}
		const reactions = baseReactionTable(response, { force: v => v * this.siUnits.force.scale, moment: v => v * this.siUnits.moment.scale });
		if (reactions.rows.length) {
			const section = this.section(localize('femResults.baseHeading', "Base Reactions"), localize('femResults.baseHelp', "The support reactions of each static case and combination (the supports push on the structure): forces summed, moments about the supports' centroid at the base."));
			renderSheet(section, reactions);
		}
		for (const curve of response.pushover) {
			this.renderPushover(curve);
		}
		for (const history of response.histories) {
			const section = this.section(localize('femResults.historyHeading', "Time History: {0}", history.label));
			renderChart(this.grid(section), {
				title: localize('femResults.roof', "Roof Displacement (node {0})", history.node),
				xLabel: localize('femResults.time', "Time [s]"),
				yLabel: withUnit(localize('femResults.displacement', "Displacement"), this.units.length),
				series: (['X', 'Y'] as const).map((axis, a) => ({ name: axis, color: AXIS_COLORS[axis], points: history.time.map((t, k) => [t, history.displacement[k][a] * this.units.length.scale]) })),
			});
			this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.recordSearch], this.commandService));
		}
		const historyDesign = response.spectrumDesign?.timeHistory;
		if (historyDesign) {
			this.renderTimeHistoryDesign(historyDesign);
		}
		if (response.columnShortening) {
			this.renderColumnShortening(response.columnShortening);
		}
		if (response.nonlinearHistory) {
			this.renderNonlinearHistory(response.nonlinearHistory);
		}
		if (response.floorSpectra) {
			this.renderFloorSpectra(response.floorSpectra);
		}
		if (response.isolation) {
			this.renderIsolation(response.isolation);
		}
		if (response.dampers) {
			this.renderDampers(response.dampers);
		}
		this.renderExisting();
		this.renderStability();
		this.renderSpecial();
	}

	/**
	 * B37 / alpha 9 P6: the isolation design beside the model: the displacements of the
	 * isolation system (each property bound where the code pack's procedure takes both), the
	 * forces below and above it, the checks and each isolator's displacement.
	 */
	private renderIsolation(found: IFemIsolationDesign): void {
		const section = this.section(
			localize('femResults.isolationHeading', "Seismic Isolation"),
			localize('femResults.isolationHelp', "The isolation system under the columns of the isolator types (04 Objects, column types), by the code pack in force: its displacement and effective period, the force below the isolators (Vb) and above them (Vs), the checks and each isolator's displacement. The nonlinear time history shows the isolators' hysteresis per record."),
		);
		const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no"), dash = '-';
		const mm = (v: number) => this.format('length', v / 1e3);
		const kn = (v: number) => this.format('force', v * 1e3);
		const levels: [string, typeof found.design][] = found.procedure === 'singleLevel'
			? Object.entries(found.bounds ?? { [localize('femResults.isolationLevel', "level")]: found.maximum })
			: [[localize('femResults.isolationDesignLevel', "design (DD)"), found.design], [localize('femResults.isolationMaximumLevel', "maximum (DM)"), found.maximum]];
		renderSheet(section, {
			name: localize('femResults.isolationLevels', "Isolation system"),
			columns: [
				localize('femResults.isolationCase', "Case"), localize('femResults.isolationD', "D"), localize('femResults.isolationT', "T [s]"),
				localize('femResults.isolationBeta', "β [%]"), localize('femResults.isolationB', "B"), localize('femResults.isolationK', "k min / max [kN/m]"),
			],
			rows: levels.map(([name, level]) => [name, mm(level.D_mm), level.T.toFixed(2), (100 * level.beta).toFixed(1), level.B.toFixed(2), `${level.kMin_kNm.toFixed(0)} / ${level.kMax_kNm.toFixed(0)}`]),
			notes: [localize('femResults.isolationTotal', "Total displacement with torsion: {0}{1}.", mm(found.total.DTM_mm), found.total.demand_mm !== undefined && found.total.demand_mm !== found.total.DTM_mm ? localize('femResults.isolationDemand', " (the units' demand {0})", mm(found.total.demand_mm)) : '')],
		});
		renderSheet(section, {
			name: localize('femResults.isolationForces', "Forces below (Vb) and above (Vs) the isolators"),
			columns: [
				localize('femResults.directionCol', "Direction"), 'R', 'RI', 'Vb', localize('femResults.isolationVst', "Vst"), 'Vs', localize('femResults.isolationGoverns', "Governs"),
			],
			rows: (['X', 'Y'] as const).map(axis => {
				const f = found.forces[axis];
				return [axis, f.R.toFixed(2), f.RI.toFixed(2), kn(f.Vb_kN), f.Vst_kN !== undefined ? kn(f.Vst_kN) : dash, kn(f.Vs_kN), f.governs];
			}),
		});
		renderSheet(section, {
			name: localize('femResults.isolationChecks', "Checks"),
			columns: [localize('femResults.isolationCheckCol', "Check"), localize('femResults.valueCol', "Value"), localize('femResults.limitCol', "Limit"), localize('femResults.okCol', "OK")],
			rows: found.checks.map(c => [c.label, c.value ?? dash, c.limit ?? dash, c.ok === null ? dash : c.ok ? yes : no]),
			notes: [found.staticAnalysis.permitted
				? localize('femResults.isolationStatic', "The equivalent lateral force procedure is permitted (if the structure above is regular).")
				: localize('femResults.isolationNoStatic', "The equivalent lateral force procedure is not permitted: use the response spectrum or a time history.")],
		});
		// Walk 4 W4B-5: the same conditions and requirements as the report, not only its verdict.
		const okText = (ok: boolean | null) => ok === null ? localize('femResults.isolationByEngineer', "engineer to confirm") : ok ? yes : no;
		renderSheet(section, {
			name: localize('femResults.isolationStaticConditions', "Where the equivalent lateral force procedure is permitted"),
			columns: [localize('femResults.isolationConditionId', "Condition"), localize('femResults.isolationConditionText', "Requirement"), localize('femResults.okCol', "OK")],
			rows: found.staticAnalysis.conditions.map(c => [c.id, c.label, okText(c.ok)]),
		});
		if (found.requirements?.length) {
			renderSheet(section, {
				name: localize('femResults.isolationRequirements', "Requirements of the isolation system"),
				columns: [localize('femResults.isolationRequirementId', "Item"), localize('femResults.isolationRequirementText', "Requirement"), localize('femResults.isolationRequirementCheck', "Checked by"), localize('femResults.okCol', "OK")],
				rows: found.requirements.map(r => [r.id, r.text, r.check, okText(r.ok)]),
			});
		}
		renderSheet(section, {
			name: localize('femResults.isolationUnits', "Isolators"),
			columns: [
				localize('femResults.isolationColumn', "Column"), localize('femResults.isolationKind', "Isolator"), localize('femResults.isolationKmax', "k max [kN/m]"),
				localize('femResults.isolationUnitTotal', "Total displacement"), localize('femResults.isolationCapacity', "Capacity"),
			],
			rows: found.units.map(u => [u.column, u.kind, u.kDmax_kNm.toFixed(0), mm(u.DTM_mm), u.capacity_mm === null ? dash : mm(u.capacity_mm)]),
		});
		for (const note of found.notes ?? []) {
			append(section, $('.fem-results-note', undefined, note));
		}
	}

	/**
	 * Alpha 9 P6: the supplemental dampers beside the model: the added effective damping and
	 * the damped base shear of each direction, and the damper schedule (stroke, velocity, force
	 * and energy at the code pack's earthquake level, against the devices' capacities).
	 */
	private renderDampers(found: IFemDamperDesign): void {
		const section = this.section(
			localize('femResults.dampersHeading', "Supplemental Dampers"),
			localize('femResults.dampersHelp', "The dampers in the braces of the damper types (04 Objects, brace types), by the code pack in force: the effective damping they add, the damped base shear the earthquake cases are scaled to, and each damper's stroke, velocity, force and energy. The nonlinear time history shows the dampers' hysteresis per record."),
		);
		if (!found.available) {
			append(section, $('.fem-results-note', undefined, localize('femResults.noDampers', "No damped design: {0}", found.reason ?? '')));
			return;
		}
		const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no"), dash = '-';
		const kn = (v: number | undefined) => v === undefined ? dash : this.format('force', v * 1e3);
		const pct = (v: number | undefined) => v === undefined ? dash : (100 * v).toFixed(1);
		const axes = Object.entries(found.byAxis ?? {}).filter(([, a]) => a.available);
		renderSheet(section, {
			name: localize('femResults.dampersDamping', "Effective damping and the damped base shear"),
			columns: [
				localize('femResults.directionCol', "Direction"), localize('femResults.dampersT1', "T1 / T1D [s]"), localize('femResults.dampersMu', "μD"),
				localize('femResults.dampersBetaI', "βI [%]"), localize('femResults.dampersBetaV', "βV [%]"), localize('femResults.dampersBetaH', "βH [%]"),
				localize('femResults.dampersB', "B"), localize('femResults.dampersVfixed', "V fixed"), localize('femResults.dampersVmin', "V min"), localize('femResults.dampersV', "V design"),
			],
			rows: axes.map(([axis, a]) => [
				axis, `${(a.T1 ?? 0).toFixed(2)} / ${(a.T1D ?? 0).toFixed(2)}`, (a.mu ?? 1).toFixed(2), pct(a.betaI), pct(a.betaV), pct(a.betaH),
				(a.B1D ?? 1).toFixed(2), kn(a.Vfixed_kN), kn(a.Vmin_kN), kn(a.Vdesign_kN),
			]),
		});
		const mm = (v: number | undefined) => v === undefined ? dash : this.format('length', v / 1e3);
		const okText = (v: boolean | null | undefined) => v === null || v === undefined ? dash : v ? yes : no;
		renderSheet(section, {
			name: localize('femResults.dampersSchedule', "Damper schedule at {0} × the design displacement", found.mceFactor ?? 1),
			columns: [
				localize('femResults.dampersBrace', "Brace"), localize('femResults.dampersKind', "Damper"), localize('femResults.directionCol', "Direction"),
				localize('femResults.dampersStroke', "Stroke"), localize('femResults.dampersVelocity', "Velocity [m/s]"), localize('femResults.dampersForce', "Force"),
				localize('femResults.dampersEnergy', "Energy per cycle [kJ]"), localize('femResults.dampersStrokeOk', "Stroke OK"), localize('femResults.dampersForceOk', "Force OK"),
			],
			rows: found.devices.filter(d => d.strokeMCE_mm !== undefined).map(d => [
				d.member, d.kind, d.axis ?? dash, mm(d.strokeMCE_mm), (d.velocityMCE_ms ?? 0).toFixed(3), kn(d.forceMCE_kN), (d.energy_kJ ?? 0).toFixed(2), okText(d.strokeOk), okText(d.forceOk),
			]),
		});
		for (const note of found.notes ?? []) {
			append(section, $('.fem-results-note', undefined, note));
		}
	}

	/** Alpha 9 P6: the isolators and dampers of a nonlinear suite, and the hysteresis loops of those that dissipate most. */
	private renderDevices(section: HTMLElement, key: string, devices: IFemDeviceSuite): void {
		if (!devices.rows.length) {
			return;
		}
		renderSheet(section, {
			name: localize('femResults.nlthDevices', "Suite {0}: isolators and dampers ({1} over the records)", key, devices.rule === 'mean' ? localize('femResults.ruleMean', "mean") : localize('femResults.ruleMax', "largest")),
			columns: [
				localize('femResults.deviceKind', "Device"), localize('femResults.deviceName', "Column or brace"), localize('femResults.recordCol', "Governing record"),
				localize('femResults.deviceDisplacement', "Displacement"), localize('femResults.deviceForce', "Force"), localize('femResults.deviceVelocity', "Velocity [m/s]"), localize('femResults.deviceEnergy', "Energy [kJ]"),
			],
			rows: devices.rows.map(r => [
				r.kind === 'isolator' ? localize('femResults.deviceIsolator', "isolator") : localize('femResults.deviceDamper', "damper"),
				r.name, r.record.replace(/^NTH: /, ''), this.format('length', r.displacement_mm / 1e3), this.format('force', r.force_kN * 1e3), r.velocity_ms.toFixed(3), r.energy_kJ.toFixed(1),
			]),
		});
		const colors: ChartColor[] = ['blue', 'orange', 'green', 'red'];
		for (const [k, loop] of devices.loops.entries()) {
			renderChart(this.grid(section), {
				title: localize('femResults.deviceLoop', "Hysteresis: {0} {1} ({2})", loop.kind === 'isolator' ? localize('femResults.deviceIsolator', "isolator") : localize('femResults.deviceDamper', "damper"), loop.name, loop.record.replace(/^NTH: /, '')),
				xLabel: withUnit(localize('femResults.deviceDeformation', "Deformation"), this.units.length),
				yLabel: withUnit(localize('femResults.deviceForceAxis', "Force"), this.units.force),
				series: [{ name: loop.name, color: colors[k % colors.length], points: loop.u_mm.map((u, i) => [u / 1e3 * this.units.length.scale, loop.F_kN[i] * 1e3 * this.units.force.scale] as [number, number]) }],
			});
		}
	}

	/**
	 * B36: the nonlinear time histories of `nonlinear-history.osmodel`: the suites and their
	 * spectrum check, the storey drifts against the code pack's limit and the members'
	 * deformations over the records, by the code pack's rules.
	 */
	private renderNonlinearHistory(found: IFemNonlinearHistory): void {
		const section = this.section(
			localize('femResults.nlthHeading', "Nonlinear Time History"),
			localize('femResults.nlthHelp', "The records run through the frames and walls as fibre elements after the gravity loads, scaled or spectrally matched to the target spectrum of the code pack in force (Project Settings, Analysis, Time history: modification). The nonlinear results are used as they come: a suite whose mean spectrum falls short must be scaled again (set the period T in the project settings and derive again)."),
		);
		if (!found.available) {
			append(section, $('.fem-results-note', undefined, localize('femResults.noNlth', "No nonlinear time history design: {0}", found.reason ?? '')));
			return;
		}
		const yes = localize('femResults.yes', "yes"), no = localize('femResults.no', "no");
		const clauses = found.clauses ?? {};
		renderSheet(section, {
			name: localize('femResults.nlthSuites', "Suites"),
			columns: [
				localize('femResults.suiteCol', "Suite"), localize('femResults.recordsCol', "Records"), localize('femResults.ruleCol', "Design value"),
				localize('femResults.periodCol', "T [s]"), localize('femResults.checkCol', "Spectrum check"), localize('femResults.ranCol', "Ran to the end"), localize('femResults.usedCol', "Usable"),
			],
			rows: (found.suites ?? []).map(s => [
				s.key, s.count,
				s.rule === 'mean' ? localize('femResults.ruleMean', "mean") : localize('femResults.ruleMax', "largest"),
				s.period ? s.period.toFixed(3) : '-',
				s.check ? localize('femResults.checkValue', "{0} at {1} s", s.check.least.toFixed(3), s.check.governing.toFixed(2)) : '-',
				s.complete ? yes : no, s.used ? yes : no,
			]),
			notes: [clauses.groundMotion, clauses.response].filter((c): c is string => !!c),
		});
		// P5: the records of the suites (metadata, applied PGA, matching) and each suite's mean
		// spectrum against the criterion.
		const records = (found.suites ?? []).flatMap(s => s.cases.map(c => ({ suite: s, record: c })));
		if (records.length) {
			const dash = '-';
			renderSheet(section, {
				name: localize('femResults.nlthRecords', "Records"),
				columns: [
					localize('femResults.nlthRecordCol', "Record"), localize('femResults.suiteCol', "Suite"), localize('femResults.magnitudeCol', "Mw"),
					localize('femResults.nlthDistanceCol', "R [km]"), localize('femResults.vs30Col', "Vs30 [m/s]"), localize('femResults.pgaCol', "PGA [g]"),
					localize('femResults.matchingCol', "Modification"), localize('femResults.sourceCol', "Source"),
				],
				rows: records.map(({ suite, record }) => [
					record.name.replace(/^NTH: /, ''), suite.key,
					record.magnitude ?? dash, record.distance ?? dash, record.vs30 ?? dash,
					record.pga?.length ? record.pga.map(v => v.toFixed(3)).join(' / ') : dash,
					record.matching?.length
						? localize('femResults.matchedWithin', "matched within {0}", record.matching.map(m => `${(m.misfit * 100).toFixed(0)} %`).join(' / '))
						: suite.modification === 'matching' ? localize('femResults.matchedNone', "matched") : localize('femResults.scaled', "scaled"),
					record.source || dash,
				]),
			});
		}
		for (const suite of found.suites ?? []) {
			const check = suite.check;
			if (!check?.periods?.length || !check.mean || !check.target) {
				continue;
			}
			const goal = check.target.map(v => v * check.ratio);
			renderChart(this.grid(section), {
				title: localize('femResults.nlthSpectrum', "Suite {0}: mean spectrum and {1} × the target", suite.key, check.ratio),
				xLabel: localize('femResults.nlthPeriodAxis', "Period [s]"),
				yLabel: localize('femResults.nlthSaAxis', "Sa [g]"),
				series: [
					{ name: localize('femResults.meanSpectrum', "mean of the records"), color: 'blue', points: check.periods.map((t, k) => [t, check.mean![k]] as [number, number]) },
					{ name: localize('femResults.criterion', "criterion"), color: 'red', points: check.periods.map((t, k) => [t, goal[k]] as [number, number]) },
				],
			});
		}
		const limit = found.limit;
		const drift = found.drift ?? [];
		if (drift.length && limit) {
			const colors: ChartColor[] = ['blue', 'orange', 'green'];
			const names = [...new Set(drift.map(d => `${d.suite} ${d.direction}`))];
			renderChart(this.grid(section), {
				title: localize('femResults.nlthDrift', "Storey Drift Ratio"),
				xLabel: localize('femResults.driftRatio', "Drift ratio [%]"),
				yLabel: withUnit(localize('femResults.levelName', "Level"), this.units.level),
				series: names.map((name, k) => ({
					name,
					color: colors[k % colors.length],
					points: drift.filter(d => `${d.suite} ${d.direction}` === name).flatMap(d => [[d.ratio * 100, d.bottom * this.units.level.scale], [d.ratio * 100, d.top * this.units.level.scale]] as [number, number][]),
				})),
				guides: [{ axis: 'x', value: limit.ratio * 100, label: localize('femResults.nlthLimit', "limit"), color: 'red' }],
			});
			renderSheet(section, {
				name: localize('femResults.nlthDriftTable', "Storey drift ({0} × the allowable {1} % = {2} %)", limit.factor, (limit.allowable * 100).toFixed(2), (limit.ratio * 100).toFixed(3)),
				columns: [
					localize('femResults.suiteCol', "Suite"), localize('femResults.directionCol', "Direction"), localize('femResults.storeyCol', "Storey"),
					localize('femResults.driftCol', "Drift"), localize('femResults.ratioPctCol', "Ratio [%]"), localize('femResults.okCol', "OK"),
				],
				rows: drift.map(d => [d.suite, d.direction, this.units.level.scale === 1 ? `${d.bottom} – ${d.top} m` : `${levelText(d.bottom, this.units.level)} – ${levelText(d.top, this.units.level)}`, this.format('length', d.drift), (d.ratio * 100).toFixed(3), d.ok ? yes : no]),
				notes: [clauses.drift].filter((c): c is string => !!c),
			});
		}
		const acceptance = found.acceptance;
		if (acceptance?.method === 'hingeRotation') {
			// P5: the code pack's pushover hinges, read from each record.
			const level = acceptance.level ?? '';
			const rows = acceptance.rows as unknown as readonly IFemNonlinearHingeRow[];
			renderSheet(section, {
				name: localize('femResults.nlthHinges', "Member hinges over the records at {0} ({1} of {2} members fail)", level || localize('femResults.lastLevel', "the last level"), acceptance.failed, rows.length),
				columns: [
					localize('femResults.memberCol', "Member"), localize('femResults.suiteCol', "Suite"), localize('femResults.recordCol', "Governing record"), localize('femResults.endCol', "End"),
					localize('femResults.hingeCol', "Hinge"), localize('femResults.demandCol', "Demand"), localize('femResults.limitCol', "Limit"), localize('femResults.ratioCol', "Ratio"), localize('femResults.okCol', "OK"),
				],
				rows: rows.map(r => [r.member, r.suite, r.record, r.end, r.component, r.demand, r.limits?.[level] ?? '-', r.ratio, r.ok ? yes : no]),
				notes: [acceptance.clause].filter((c): c is string => !!c),
			});
		} else if (acceptance) {
			const kinds: { [kind: string]: string } = {
				concrete: localize('femResults.fibreConcrete', "concrete"),
				bar: localize('femResults.fibreBar', "reinforcing bar"),
				steel: localize('femResults.fibreSteel', "steel"),
			};
			renderSheet(section, {
				name: localize('femResults.nlthAcceptance', "Member deformations over the records ({0} of {1} members fail)", acceptance.failed, acceptance.rows.length),
				columns: [
					localize('femResults.memberCol', "Member"), localize('femResults.suiteCol', "Suite"), localize('femResults.recordCol', "Governing record"), localize('femResults.endCol', "End"),
					localize('femResults.fibreCol', "Fibre"), localize('femResults.strainCol', "Strain"), localize('femResults.limitCol', "Limit"), localize('femResults.ratioCol', "Ratio"), localize('femResults.okCol', "OK"),
				],
				rows: acceptance.rows.map(r => [r.member, r.suite, r.record, r.end, kinds[r.fibre] ?? r.fibre, r.strain, r.limit, r.ratio, r.ok ? yes : no]),
				notes: [acceptance.clause].filter((c): c is string => !!c),
			});
		}
		const forced = found.forceControlled;
		if (forced?.rows.length) {
			const actions: { [action: string]: string } = {
				columnAxial: localize('femResults.columnAxial', "column compression"),
				shear: localize('femResults.memberShear', "shear"),
			};
			const dash = '-';
			renderSheet(section, {
				name: localize('femResults.nlthForces', "Force-controlled actions: γ·(Fu − Fg) + Fg against the design strength ({0} of {1} fail)", forced.failed, forced.rows.length),
				columns: [
					localize('femResults.memberCol', "Member"), localize('femResults.actionCol', "Action"), localize('femResults.classCol', "Class"), localize('femResults.suiteCol', "Suite"),
					localize('femResults.fuCol', "Fu [kN]"), localize('femResults.fgCol', "Fg [kN]"), localize('femResults.forceDemandCol', "Demand [kN]"), localize('femResults.strengthCol', "Strength [kN]"),
					localize('femResults.ratioCol', "Ratio"), localize('femResults.okCol', "OK"),
				],
				rows: forced.rows.map(r => [r.member, actions[r.action] ?? r.action, `${r.category} (γ = ${r.factor})`, r.suite, r.Fu, r.Fg, r.demand, r.capacity ?? dash, r.ratio ?? dash, r.ok === null ? dash : r.ok ? yes : no]),
				notes: [forced.clause].filter((c): c is string => !!c),
			});
		}
		// Alpha 9 P6: the isolators and dampers over the records.
		for (const suite of found.suites ?? []) {
			if (suite.devices) {
				this.renderDevices(section, suite.key, suite.devices);
			}
		}
		for (const note of found.notes ?? []) {
			append(section, $('.fem-results-note', undefined, note));
		}
		this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.recordSearch], this.commandService));
	}

	/** B25: the column shortening with the code pack's creep and shrinkage, line by line. */
	private renderColumnShortening(found: IFemColumnShortening): void {
		const section = this.section(
			localize('femResults.shorteningHeading', "Column Shortening"),
			localize('femResults.shorteningHelp', "Elastic, creep and shrinkage shortening of each concrete column line (and wall, when the settings take walls), storey by storey in time, by the creep and shrinkage model of the code pack in force. After casting: what the storeys below shorten after a floor is cast level, which the floors and the beams between lines feel."),
		);
		if (!found.available || !found.lines) {
			append(section, $('.fem-results-note', undefined, localize('femResults.noShortening', "No column shortening: {0}", found.reason ?? '')));
			this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.stagedConstructionLoads], this.commandService));
			return;
		}
		if (found.model) {
			const method = found.model.analysis === 'ageAdjusted'
				? localize('femResults.shorteningAaem', "age-adjusted effective modulus, χ = {0}", found.model.chi ?? '')
				: localize('femResults.shorteningSuperposition', "superposition of each load's creep");
			append(section, $('.fem-results-note', undefined, localize('femResults.shorteningModel', "Models: {0}; analysis by {1}.", found.model.name, method)));
		}
		const length = this.units.length.scale;
		const colors: ChartColor[] = ['blue', 'orange', 'green', 'red', 'purple', 'yellow'];
		// The lines that shorten most at the top, at most six on the charts.
		const top = (rows: readonly { readonly total: number }[]) => rows.length ? rows[rows.length - 1].total : 0;
		const shown = [...found.lines].sort((a, b) => top(b.rows) - top(a.rows)).slice(0, colors.length);
		renderChart(this.grid(section), {
			title: localize('femResults.shorteningProfile', "Shortening after Casting at the End of the Service Life"),
			xLabel: withUnit(localize('femResults.shortening', "Shortening"), this.units.length),
			yLabel: withUnit(localize('femResults.levelName', "Level"), this.units.level),
			series: shown.map((line, k) => ({ name: line.line, color: colors[k], points: line.rows.map(r => [r.afterCasting * length, r.z * this.units.level.scale]) })),
		});
		const history = found.history;
		if (history) {
			const shownNames = new Set(shown.map(l => l.line));
			renderChart(this.grid(section), {
				title: localize('femResults.shorteningHistory', "Top of the Line in Time"),
				xLabel: localize('femResults.days', "Days from the start of construction"),
				yLabel: withUnit(localize('femResults.shortening', "Shortening"), this.units.length),
				series: history.lines.filter(l => shownNames.has(l.line)).map((l, k) => ({ name: l.line, color: colors[k % colors.length], points: history.days.map((d, i) => [d, l.values[i] * length]) })),
			});
		}
		const clauses = found.clauses ?? {};
		const inputs = found.inputs;
		const value = (v: number) => this.format('length', v);
		renderSheet(section, {
			name: localize('femResults.shorteningTable', "Shortening per column line and level"),
			columns: [
				localize('femResults.lineCol', "Column line"), localize('femResults.levelCol', "Level"),
				localize('femResults.elasticCol', "Elastic"), localize('femResults.creepCol', "Creep"), localize('femResults.shrinkageCol', "Shrinkage"),
				localize('femResults.totalCol', "Total"), localize('femResults.afterCol', "After casting"),
			],
			rows: found.lines.flatMap(line => line.rows.map(r => [line.line, r.level, value(r.elastic), value(r.creep), value(r.shrinkage), value(r.total), value(r.afterCasting)])),
			notes: [
				...(inputs ? [localize('femResults.shorteningInputs', "Relative humidity {0} % ({1}), floor cycle {2} days, finishes and {3} % of the live load {4} days after completion, column steel ratio {5} %, service life {6} years{7}.",
					inputs.humidity, inputs.exposure, inputs.cycle, Math.round(inputs.sustainedLive * 100), inputs.superimposedAfter, (inputs.steelRatio * 100).toFixed(2), inputs.serviceLife,
					inputs.staged ? localize('femResults.shorteningStaged', ", dead load by the construction sequence") : localize('femResults.shorteningAtOnce', ", dead load at completion"))] : []),
				...[clauses.creep, clauses.creepFigure, clauses.creepDevelopment, clauses.shrinkageFigure, clauses.reinforced, clauses.phased, clauses.effects].filter((c): c is string => !!c),
				...(found.notes ?? []),
			],
		});
		if (found.differential?.length) {
			renderSheet(section, {
				name: localize('femResults.differentialTable', "Differential shortening of the beams between column lines"),
				columns: [
					localize('femResults.beamCol', "Beam"), localize('femResults.levelCol', "Level"), withUnit(localize('femResults.spanCol', "Span"), this.units.length),
					localize('femResults.differenceCol', "Differential"), localize('femResults.rotationCol', "Δ/L"), withUnit(localize('femResults.momentCol', "6EIΔ/L²"), this.units.moment),
				],
				rows: found.differential.map(r => [r.beam, r.level, fixed(r.length * length, 0), value(r.difference), `1/${r.rotation > 0 ? Math.round(1 / r.rotation) : '∞'}`, fixed(r.moment * this.units.moment.scale, 1)]),
				notes: [localize('femResults.differentialNote', "The indicative end moment of a beam fixed at both ends, with its section's E and I, without relief by its own creep.")],
			});
		}
		// Alpha 9 P2: adjacent members, the pre-sets, the creep and shrinkage forces case.
		if (found.pairs?.length) {
			renderSheet(section, {
				name: localize('femResults.pairsTable', "Differential shortening between adjacent columns and walls"),
				columns: [
					localize('femResults.lineA', "Line"), localize('femResults.lineB', "Neighbour"), withUnit(localize('femResults.distanceCol', "Distance"), this.units.length),
					localize('femResults.levelCol', "Level"), localize('femResults.differenceCol', "Differential"), localize('femResults.rotationCol', "Δ/L"),
				],
				rows: found.pairs.map(r => [r.a, r.b, fixed(r.distance * length, 0), r.level, value(r.difference), `1/${r.slope > 0 ? Math.round(1 / r.slope) : '∞'}`]),
				notes: [localize('femResults.pairsNote', "Each line with its nearest neighbour, and each column with its nearest wall: the largest difference of their shortening after casting over the levels.")],
			});
		}
		if (found.camber?.length) {
			renderSheet(section, {
				name: localize('femResults.camberTable', "Pre-set (camber) of the levels at casting"),
				columns: [
					localize('femResults.lineCol', "Column line"), localize('femResults.levelCol', "Level"),
					localize('femResults.presetCol', "Cast higher by"), localize('femResults.storeyPresetCol', "Storey longer by"), localize('femResults.relativeCol', "Relative to the least"),
				],
				rows: found.camber.map(r => [r.line, r.level, value(r.preset), value(r.storey), value(r.relative)]),
				notes: [localize('femResults.camberNote', "Cast each level higher by its shortening after casting; the storey below it is made longer by the increase over the level below. Relative: over the line that shortens least at that level (often the core), for a correction relative to it.")],
			});
		}
		const induced = found.induced;
		if (induced) {
			renderSheet(section, {
				name: localize('femResults.redistributionTable', "Creep and shrinkage forces CS: axial force change at the base"),
				columns: [
					localize('femResults.lineCol', "Column line"), localize('femResults.kindCol', "Kind"),
					localize('femResults.forceChange', "Compression change"), localize('femResults.shareCol', "Of D + SD"),
				],
				rows: induced.redistribution.map(r => [r.line, r.kind === 'wall' ? localize('femResults.kindWall', "wall") : localize('femResults.kindColumn', "column"), this.format('force', r.force), `${(r.share * 100).toFixed(1)} %`]),
				notes: [
					localize('femResults.redistributionNote', "Columns {0}, walls {1} in all: the load the creep and shrinkage move between the columns and the walls (compression positive).", this.format('force', induced.columns), this.format('force', induced.walls)),
					...(induced.relaxation ? [localize('femResults.relaxationNote', "The forces are relaxed by the age-adjusted effective modulus, 1 / (1 + χ φ̄) = {0}.", induced.relaxation.toFixed(2))] : []),
				],
			});
			if (induced.beams.length) {
				renderSheet(section, {
					name: localize('femResults.inducedBeams', "Creep and shrinkage forces CS: the largest beam end moments"),
					columns: [localize('femResults.beamCol', "Beam"), localize('femResults.levelCol', "Level"), withUnit(localize('femResults.momentCol2', "Moment"), this.units.moment)],
					rows: induced.beams.map(r => [r.beam, r.level, fixed(r.moment * this.units.moment.scale, 1)]),
					notes: [localize('femResults.inducedNote', "The case CS is a load case of the run: its forces in every member and slab are in the results, and the combinations take it with the code pack's factor.")],
				});
			}
		}
		// What stays planned: construction loads and shoring.
		this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.stagedConstructionLoads], this.commandService));
	}

	/** The linear time-history design (B19): each suite's spectrum against the code's criterion, the suites' base shears and factors, the drifts. */
	private renderTimeHistoryDesign(design: IFemTimeHistoryDesign): void {
		const clauses = [design.clauses.records, design.clauses.response].filter(c => !!c).join('; ');
		const section = this.section(
			localize('femResults.thDesignHeading', "Time History Design"),
			design.use
				? localize('femResults.thDesignUsed', "The earthquake in the design combinations comes from these suites ({0}).", clauses)
				: localize('femResults.thDesignShown', "The suites against the code pack's criteria ({0}). Choose Linear time history under Earthquake design forces in Project Settings to design with them.", clauses),
		);
		const yes = localize('femResults.yes', "yes");
		const no = localize('femResults.no', "no");
		for (const suite of design.suites) {
			const check = suite.check;
			if (!check) {
				continue;
			}
			renderChart(this.grid(section), {
				title: localize('femResults.thSuiteChart', "Suite {0}: mean spectrum, T = {1} s", suite.key, check.period.toFixed(3)),
				xLabel: localize('femResults.period', "Period [s]"),
				yLabel: localize('femResults.thSa', "Sa [g]"),
				series: [
					{ name: localize('femResults.thMean', "Mean of the suite"), color: 'blue', points: check.periods.map((t, k) => [t, check.mean[k]]) },
					{ name: localize('femResults.thTarget', "{0} × design spectrum", check.ratio), color: 'red', points: check.periods.map((t, k) => [t, check.ratio * check.target[k]]) },
				],
				caption: check.ok ? undefined : localize('femResults.thShort', "Short of the criterion by {0}: the suite's responses are scaled up by it.", check.shortfall.toFixed(3)),
			});
		}
		renderSheet(section, {
			name: localize('femResults.thSuites', "Suites"),
			columns: [
				localize('femResults.thSuite', "Suite"),
				localize('femResults.thCount', "Records"),
				localize('femResults.thRule', "Design value"),
				localize('femResults.thLeast', "Least mean / criterion"),
				withUnit(localize('femResults.thVth', "Vth"), this.units.force),
				withUnit(localize('femResults.thV', "V static"), this.units.force),
				localize('femResults.thFactor', "Factor"),
				localize('femResults.thUsed', "Used"),
			],
			rows: design.suites.map(s => {
				const axis = s.key === 'Y' ? 'y' : 'x';
				const force = (kn: number | undefined) => kn === undefined ? '' : kn * 1e3 * this.units.force.scale;
				return [
					s.key,
					s.count,
					s.rule === 'mean' ? localize('femResults.thMeanRule', "mean") : localize('femResults.thMaxRule', "largest"),
					s.check ? s.check.least : '',
					force(s.vHistory?.[axis]),
					force(s.vStatic?.[axis]),
					s.factor ?? '',
					s.used ? yes : no,
				];
			}),
			notes: design.notes,
		});
		if (design.drift.length) {
			renderSheet(section, {
				name: localize('femResults.thDrift', "Storey drift (Cd/I)"),
				columns: [
					localize('femResults.thSuite', "Suite"),
					localize('femResults.direction', "Direction"),
					localize('femResults.storey', "Storey"),
					localize('femResults.thDriftRatio', "Drift [%]"),
					localize('femResults.thAllowable', "Allowable [%]"),
					localize('femResults.okCol', "OK"),
				],
				rows: design.drift.map(d => [d.suite, d.direction, `${d.bottom} to ${d.top} m`, 100 * d.ratio, 100 * d.allowableRatio, d.ok ? yes : no]),
				notes: design.clauses.drift ? [design.clauses.drift] : undefined,
			});
		}
	}

	private axes(): FemAxis2[] {
		return this.directions === 'XY' ? ['X', 'Y'] : [this.directions];
	}

	private storeyUnit(quantity: StoreyQuantity): IUnit {
		switch (quantity) {
			case 'disp': return this.units.length;
			case 'drift': return { scale: 1, unit: '' };
			case 'force':
			case 'shear': return this.units.force;
			case 'overturning': return this.units.moment;
		}
	}

	private renderStoreys(response: IFemStoryResponse, result: IFemStoryResult): void {
		const spectrum = result.kind === 'spectrum';
		const scale = result.forceScale ?? undefined;
		const section = this.section(
			localize('femResults.storeyHeadingOf', "Storey Response: {0}", result.label),
			!spectrum
				? localize('femResults.storeyHelp', "Displacements are the largest at each level; drift is the largest inter-storey drift ratio over the plan positions; forces are the lateral loads at the levels.")
				: scale !== undefined
					? localize('femResults.spectrumScaledHelp', "Peak values of the response spectrum case (no signs). Storey forces, shears and overturning are scaled by {0} to 0.85·V as the design uses them ({1}); displacements and drifts are unscaled, as {2} requires for drift. Drifts combine the modal drifts, as the spectrum design does.", scale.toFixed(3), response.spectrumDesign?.clause ?? defaultClause('Part 6 Sec 2.5.9.4'), activeCodeName())
					: localize('femResults.spectrumUnscaledHelp', "Peak values of the response spectrum case (no signs), unscaled: the response spectrum design (Design Utilisation) has not been worked out for this run, so the forces are not yet scaled to 0.85·V ({0}). Drifts combine the modal drifts, as the spectrum design does.", defaultClause('Part 6 Sec 2.5.9.4')),
		);
		const grid = this.grid(section);
		const limit = elasticDriftLimit(response.driftLimit);
		for (const quantity of STOREY_QUANTITIES) {
			const unit = this.storeyUnit(quantity);
			// A spectrum case's values say whether they are at the design level.
			const forceLike = quantity === 'force' || quantity === 'shear' || quantity === 'overturning';
			const title = !spectrum ? storeyQuantityLabel(quantity)
				: forceLike && scale !== undefined ? localize('femResults.scaledTitle', "{0} (scaled ×{1})", storeyQuantityLabel(quantity), scale.toFixed(2))
					: localize('femResults.unscaledTitle', "{0} (unscaled)", storeyQuantityLabel(quantity));
			const series: IChartSeries[] = [];
			const captions: string[] = [];
			const marks: { x: number; y: number; text: string; color: ChartColor }[] = [];
			for (const axis of this.axes()) {
				const profile = storeyProfile(result, quantity, axis);
				if (!profile.length) {
					continue;
				}
				const show = (v: number) => quantity === 'drift' ? v.toFixed(5) : fixed(v * unit.scale, quantity === 'disp' ? 2 : 1);
				series.push({
					name: axis,
					color: AXIS_COLORS[axis],
					// Storey forces act at the levels: a line through them, each level marked.
					style: 'line',
					points: profile.map(p => [p.value * unit.scale, p.z * this.units.level.scale]),
					tooltips: profile.map(p => `${axis}, ${p.level} (${levelText(p.z, this.units.level)}): ${[show(p.value), unit.unit].filter(Boolean).join(' ')}`),
				});
				const peak = profilePeak(profile);
				if (peak && Math.abs(peak.value) > 0) {
					captions.push(localize('femResults.peakCaption', "{0}: largest {1} at {2}", axis, [show(peak.value), unit.unit].filter(Boolean).join(' '), peak.level));
					marks.push({ x: peak.value * unit.scale, y: peak.z * this.units.level.scale, text: show(peak.value), color: AXIS_COLORS[axis] });
				}
			}
			const guides = quantity === 'drift' && limit !== undefined && (isEarthquakeResult(result.label) || spectrum)
				? [{ axis: 'x' as const, value: limit, label: localize('femResults.driftLimit', "{1} limit {0}", limit.toFixed(5), activeCodeName()), color: 'red' as const }]
				: [];
			// B9: a service wind combination: the code pack's storey drift limit for loads other than earthquake, and the top sway limit.
			if (result.kind === 'service' && quantity === 'drift' && typeof result.windDriftLimit === 'number') {
				guides.push({ axis: 'x' as const, value: result.windDriftLimit, label: localize('femResults.windDriftLimit', "Wind drift limit {0}", result.windDriftLimit.toFixed(4)), color: 'red' as const });
				captions.push(localize('femResults.windDriftCaption', "Limit: storey drift Δ/h ≤ {0} under the service wind combination (loads other than earthquake).", result.windDriftLimit));
			}
			if (result.kind === 'service' && quantity === 'disp' && typeof result.swayLimit === 'number' && response.levels.length > 1) {
				const height = response.levels[response.levels.length - 1].z - response.levels[0].z;
				const allowed = result.swayLimit * height;
				captions.push(localize('femResults.swayCaption', "Top sway limit: H × {0} = {1} {2} along {3}.", result.swayLimit, fixed(allowed * unit.scale, 1), unit.unit, result.direction ?? '–'));
			}
			if (quantity === 'drift' && response.driftLimit && guides.length && result.kind !== 'service') {
				captions.push(localize('femResults.driftLimitCaption', "Limit: Δa/hsx = {0} (Table 6.2.21) on the design drift Cd·δ/I, so {1} on the analysis drift (Cd = {2}, I = {3}).", response.driftLimit.ratio, limit!.toFixed(5), response.driftLimit.cd ?? '–', response.driftLimit.importance ?? '–'));
			}
			if (quantity === 'drift' && spectrum) {
				// The design check's own figure (with the accidental torsion), the one the
				// Design Utilisation reports, so the two never seem to disagree.
				for (const axis of this.axes()) {
					const rows = (response.spectrumDesign?.drift ?? []).filter(d => d.direction === axis);
					const worst = rows.reduce<typeof rows[number] | undefined>((w, d) => !w || d.ratio > w.ratio ? d : w, undefined);
					if (worst) {
						const verdict = worst.ok ? localize('femResults.ok', "OK") : localize('femResults.notOk', "exceeded");
						captions.push(this.units.level.scale === 1
							? localize('femResults.designDriftCaption', "{0}: design drift Cd·δ/I with the accidental torsion {1} % between {2} and {3} m (allowable {4} %, {5}).", axis, (100 * worst.ratio).toFixed(2), worst.bottom, worst.top, (100 * worst.allowableRatio).toFixed(2), verdict)
							// C13b: the levels in the display unit
							: localize('femResults.designDriftCaptionShown', "{0}: design drift Cd·δ/I with the accidental torsion {1} % between {2} and {3} (allowable {4} %, {5}).", axis, (100 * worst.ratio).toFixed(2), levelText(worst.bottom, this.units.level), levelText(worst.top, this.units.level), (100 * worst.allowableRatio).toFixed(2), verdict));
					}
				}
			}
			renderChart(grid, {
				title,
				xLabel: withUnit(storeyQuantityLabel(quantity), unit),
				yLabel: withUnit(localize('femResults.elevationName', "Elevation"), this.units.level),
				series,
				guides,
				marks,
				include: { x: [0], y: response.levels.map(l => l.z * this.units.level.scale) },
				caption: captions.join(' · ') || localize('femResults.zeroCaption', "No {0} in this result.", storeyQuantityLabel(quantity).toLowerCase()),
				height: 320,
			});
		}
	}

	private renderModal(response: IFemStoryResponse): void {
		const modal = response.modal!;
		const section = this.section(localize('femResults.modalHeading', "Modal Periods and Mass Participation"), localize('femResults.modalHelp', "{0}: include enough modes to reach the mass participation the code asks in each direction (90 % in most codes).", defaultClause('Part 6 Sec 2.5.9.2')));
		const grid = this.grid(section);
		const required = 100 * modal.required;
		const series: IChartSeries[] = [];
		const captions: string[] = [];
		for (const axis of this.axes()) {
			const share = (m: typeof modal.modes[number]) => axis === 'X' ? m.uX : m.uY;
			const sum = (m: typeof modal.modes[number]) => axis === 'X' ? m.sumUX : m.sumUY;
			const offset = this.directions === 'XY' ? (axis === 'X' ? -0.18 : 0.18) : 0;
			series.push({
				name: localize('femResults.modalShare', "U{0} of the mode", axis),
				color: AXIS_COLORS[axis],
				style: 'bars',
				bar: { offset, width: this.directions === 'XY' ? 0.34 : 0.6 },
				points: modal.modes.filter(m => share(m) !== null).map(m => [m.number, 100 * share(m)!]),
			});
			series.push({
				name: localize('femResults.modalSum', "Cumulative U{0}", axis),
				color: AXIS_COLORS[axis],
				style: 'dashed',
				points: modal.modes.filter(m => sum(m) !== null).map(m => [m.number, 100 * sum(m)!]),
			});
			const reached = modesToReach(modal.modes, axis, modal.required);
			const last = modal.modes[modal.modes.length - 1];
			captions.push(reached !== undefined
				? localize('femResults.reached', "{0} reaches {1} % at mode {2}", axis, required, reached)
				: localize('femResults.massNotReached', "{0} reaches only {1} % with {2} modes", axis, last && sum(last) !== null ? (100 * sum(last)!).toFixed(1) : '–', modal.modes.length));
		}
		renderChart(grid, {
			title: localize('femResults.participation', "Mass Participation"),
			xLabel: localize('femResults.mode', "Mode"),
			integerX: true,
			yLabel: localize('femResults.percent', "Mass [%]"),
			series,
			guides: [{ axis: 'y', value: required, label: localize('femResults.requiredLine', "{0} % required", required), color: 'red' }],
			include: { x: [0.5, modal.modes.length + 0.5], y: [0, 100] },
			caption: captions.join(' · '),
		});
		renderChart(grid, {
			title: localize('femResults.periods', "Periods"),
			xLabel: localize('femResults.mode', "Mode"),
			integerX: true,
			yLabel: localize('femResults.period', "Period [s]"),
			series: [{
				name: localize('femResults.period', "Period [s]"), color: 'purple', style: 'bars', bar: { offset: 0, width: 0.6 },
				points: modal.modes.filter(m => m.period !== null).map(m => [m.number, m.period!]),
				tooltips: modal.modes.filter(m => m.period !== null).map(m => describeMode(m, m.number)),
			}],
			include: { x: [0.5, modal.modes.length + 0.5] },
			caption: modal.modes[0] ? describeMode(modal.modes[0], 1) : undefined,
		});
		renderSheet(section, modalTable(modal));
	}

	/**
	 * Alpha 9 L5: the floor response spectra at the chosen floors, a chart per direction at the
	 * code pack's component damping (broadened); the table of every damping is in the Summary.
	 */
	private renderFloorSpectra(found: IFemFloorSpectra): void {
		const section = this.section(
			localize('femResults.floorSpectraHeading', "Floor Response Spectra"),
			localize('femResults.floorSpectraHelp', "In-structure spectra of the floors chosen in Project Settings (Analysis, Floor response spectra), by the code pack's method, the peaks broadened. With Use for the components on, the nonstructural components take their forces from them."),
		);
		if (!found.available) {
			append(section, $('.fem-results-note', undefined, localize('femResults.noFloorSpectra', "No floor response spectra: {0}", found.reason ?? '')));
			return;
		}
		const periods = found.periods ?? [];
		const damping = found.componentDamping ?? found.damping?.[0] ?? 0.05;
		const palette: ChartColor[] = ['blue', 'orange', 'green', 'red', 'purple', 'yellow'];
		const grid = this.grid(section);
		for (const direction of ['X', 'Y'] as const) {
			const curves = floorSpectrumCurves(found, direction, damping);
			if (!curves.length) {
				continue;
			}
			renderChart(grid, {
				title: localize('femResults.floorSpectraTitle', "Floor Spectra in {0}, {1} % Damping", direction, Math.round(damping * 1000) / 10),
				xLabel: localize('femResults.periodAxis', "Period T [s]"),
				yLabel: localize('femResults.floorSaAxis', "Sa [g]"),
				series: curves.map((c, k) => ({ name: c.name, color: palette[k % palette.length], points: periods.map((t, i) => [t, c.sa[i]]) })),
				caption: localize('femResults.floorSpectraCaption', "Highest floor peak {0} g ({1})", Math.max(...curves.map(c => c.peak)).toFixed(3), curves[curves.length - 1].name),
			});
		}
		const notes = [found.clause ?? '', ...(found.notes ?? [])].filter(Boolean);
		if (notes.length) {
			append(section, $('.fem-results-help', undefined, notes.join(' · ')));
		}
	}

	private renderSpectrum(response: IFemStoryResponse): void {
		const spectrum = response.spectrum!;
		const unit = this.units.acceleration;
		const section = this.section(localize('femResults.spectrumHeading', "Design Response Spectrum"), spectrum.name);
		const modes = (response.modal?.modes ?? []).filter(m => m.period !== null);
		const marks = modes.slice(0, 3).map(m => ({ x: m.period!, y: spectrumAt(spectrum, m.period!) * unit.scale, text: `T${m.number}`, color: 'orange' as ChartColor }));
		renderChart(this.grid(section), {
			title: localize('femResults.spectrumTitle', "Sa(T) with the Modal Periods"),
			xLabel: localize('femResults.periodAxis', "Period T [s]"),
			yLabel: withUnit(localize('femResults.saAxis', "Sa"), unit),
			series: [
				{ name: localize('femResults.spectrumSeries', "Design spectrum"), color: 'blue', points: spectrum.periods.map((t, k) => [t, spectrum.accelerations[k] * unit.scale]) },
				{
					name: localize('femResults.modesSeries', "Modes"), color: 'orange', style: 'points',
					points: modes.map(m => [m.period!, spectrumAt(spectrum, m.period!) * unit.scale]),
					tooltips: modes.map(m => `${describeMode(m, m.number)}; Sa = ${fixed(spectrumAt(spectrum, m.period!) * unit.scale, 3)} ${unit.unit}`),
				},
			],
			marks,
			caption: modes[0] ? localize('femResults.spectrumCaption', "T1 = {0} s: Sa = {1} {2}", modes[0].period!.toFixed(3), fixed(spectrumAt(spectrum, modes[0].period!) * unit.scale, 3), unit.unit) : undefined,
		});
	}

	// ───────────────────────────── a member's page ─────────────────────────────

	private renderMember(member: string): void {
		this.directionGroup.classList.add('hidden');
		const detail = this.member;
		if (!detail) {
			this.updatePickers([]);
			return;
		}
		const combos = detail.results.filter(r => r.kind === 'combination');
		const options = [
			...(combos.length ? [{ key: ENVELOPE, label: localize('femResults.envelope', "Envelope of the combinations") }] : []),
			...orderLike(detail.results, this.listKeys).map(r => ({ key: r.key, label: r.label })),
		];
		this.updatePickers(options);
		const envelope = this.picked === ENVELOPE;
		const result = detail.results.find(r => r.key === this.picked);

		const kind = detail.kind === 'column' ? localize('femResults.column', "Column") : detail.kind === 'beam' ? localize('femResults.beam', "Beam") : localize('femResults.brace', "Brace");
		const facts = append(this.body, $('.fem-results-facts'));
		for (const [name, value] of [
			[localize('femResults.kind', "Member"), `${member} · ${kind}`],
			...(detail.section ? [[localize('femResults.section', "Section"), detail.section]] : []),
			[localize('femResults.length', "Length"), `${detail.length.toFixed(3)} m`],
			[localize('femResults.elements', "Analysis elements"), detail.elements.join(', ')],
			[localize('femResults.shown', "Shown"), envelope ? localize('femResults.envelope', "Envelope of the combinations") : result?.label ?? ''],
		]) {
			const fact = append(facts, $('.fem-results-fact'));
			append(fact, $('span.name', undefined, name));
			append(fact, $('span.value', undefined, value));
		}

		const forces = this.section(localize('femResults.forcesHeading', "Forces Along the Member"), detail.kind === 'column'
			? localize('femResults.columnAxes', "From the bottom of the column (0 m) up. Member axes: 1 along it; tension positive; V2 and M3 act in the local 1-2 plane, V3 and M2 in the 1-3 plane; values signed as computed.")
			: localize('femResults.beamAxes', "From the member's start (0 m). Member axes: 1 along it; tension positive; the gravity bending is M3 (the 1-2 plane), sagging positive (tension at the bottom), hogging negative; M2 is the bending across."));
		const grid = this.grid(forces);
		const components: readonly { readonly c: MemberComponent | 'u2' | 'u3'; readonly title: string; readonly unit: IUnit }[] = [
			{ c: 'N', title: localize('femResults.axial', "Axial Force N"), unit: this.units.force },
			{ c: 'Vy', title: localize('femResults.shear2', "Shear V2"), unit: this.units.force },
			{ c: 'Vz', title: localize('femResults.shear3', "Shear V3"), unit: this.units.force },
			{ c: 'T', title: localize('femResults.torsion', "Torsion T"), unit: this.units.moment },
			{ c: 'My', title: localize('femResults.moment2', "Moment M2"), unit: this.units.moment },
			{ c: 'Mz', title: localize('femResults.moment3', "Moment M3"), unit: this.units.moment },
			{ c: 'u2', title: localize('femResults.deflection2', "Deflection u2 (relative to the chord)"), unit: this.units.length },
			{ c: 'u3', title: localize('femResults.deflection3', "Deflection u3 (relative to the chord)"), unit: this.units.length },
		];
		// C13b: the stations in the display unit of levels (m in SI, ft in US units)
		const level = this.units.level;
		const x = detail.stations.map(s => s * level.scale);
		const atText = (v: number) => level.scale === 1 ? v.toFixed(2) : `${v.toFixed(2)} ${level.unit}`;
		for (const { c, title, unit } of components) {
			const digits = unit === this.units.length ? 3 : 1;
			const show = (v: number) => `${fixed(v * unit.scale, digits)} ${unit.unit}`;
			let series: IChartSeries[];
			let caption: string;
			if (envelope) {
				const env = memberEnvelope(detail, c);
				series = [
					{ name: localize('femResults.max', "Max"), color: 'blue', style: 'area', points: x.map((s, k) => [s, env.max[k] * unit.scale]), tooltips: x.map((s, k) => `${s.toFixed(2)} ${level.unit}: ${show(env.max[k])} (${env.maxBy[k]})`) },
					{ name: localize('femResults.min', "Min"), color: 'red', style: 'area', points: x.map((s, k) => [s, env.min[k] * unit.scale]), tooltips: x.map((s, k) => `${s.toFixed(2)} ${level.unit}: ${show(env.min[k])} (${env.minBy[k]})`) },
				];
				const hi = extremes(x, env.max);
				const lo = extremes(x, env.min);
				caption = hi && lo ? (level.scale === 1 ? localize('femResults.envelopeCaption', "Max {0} at {1} m; min {2} at {3} m", show(hi.max.value), atText(hi.max.at), show(lo.min.value), atText(lo.min.at)) : localize('femResults.envelopeCaptionShown', "Max {0} at {1}; min {2} at {3}", show(hi.max.value), atText(hi.max.at), show(lo.min.value), atText(lo.min.at))) : '';
			} else if (result) {
				const values = memberValues(result, c);
				series = [{ name: result.label, color: 'blue', style: 'area', points: x.map((s, k) => [s, values[k] * unit.scale]), tooltips: x.map((s, k) => `${s.toFixed(2)} ${level.unit}: ${show(values[k])}`) }];
				const e = extremes(x, values);
				caption = e ? (level.scale === 1 ? localize('femResults.extremesCaption', "Max {0} at {1} m; min {2} at {3} m", show(e.max.value), atText(e.max.at), show(e.min.value), atText(e.min.at)) : localize('femResults.extremesCaptionShown', "Max {0} at {1}; min {2} at {3}", show(e.max.value), atText(e.max.at), show(e.min.value), atText(e.min.at))) : '';
			} else {
				continue;
			}
			const marks = series.flatMap(s => {
				const values = s.points.map(p => p[1]);
				const e = extremes(s.points.map(p => p[0]), values);
				if (!e) {
					return [];
				}
				const pick = Math.abs(e.max.value) >= Math.abs(e.min.value) ? e.max : e.min;
				return Math.abs(pick.value) > 1e-9 ? [{ x: pick.at, y: pick.value, text: fixed(pick.value, digits), color: s.color }] : [];
			});
			renderChart(grid, {
				title,
				xLabel: withUnit(localize('femResults.stationName', "Distance along the member"), level),
				yLabel: withUnit(title.split(' (')[0], unit),
				series,
				marks,
				include: { x: [0, detail.length * level.scale], y: [0] },
				xDomain: [0, detail.length * level.scale],
				caption,
				height: 220,
			});
		}

		if (detail.kind === 'column') {
			this.renderInteraction(member);
		} else if (detail.kind === 'beam') {
			this.renderRequired(member, detail);
		}
	}

	private renderInteraction(member: string): void {
		const section = this.section(localize('femResults.pmHeading', "P–M Interaction"), localize('femResults.pmHelp', "φ-factored capacities of the column's section and bars (SAEngine's design checks: the strength design of {0}) with the demand of every load combination: the largest axial force and the largest moments of each.", defaultClause('Part 6 Chapter 6')));
		const diagram = this.interaction;
		if (!diagram) {
			const note = this.interactionState === 'loading'
				? localize('femResults.pmLoadingNote', "Working out the interaction diagrams of the run's columns with the design checks (a few minutes the first time after a run; then they are kept beside the results). The status bar's engine entry says what the engine is doing...")
				: this.interactionState === 'none'
					? localize('femResults.pmNone', "{0} is not designed as a concrete column (no bars, steel, or not in the design checks).", member)
					: this.interactionState === 'failed'
						? localize('femResults.pmFailed', "The interaction diagram could not be worked out: {0}", this.interactionProblem ?? '')
						: localize('femResults.pmIdle', "The design checks work out the diagrams of all the columns at once: a few minutes the first time after a run.");
			append(section, $('.fem-results-note', undefined, note));
			if (this.interactionState === 'idle' || this.interactionState === 'failed') {
				const button = this.renderStore.add(new Button(section, { ...defaultButtonStyles, supportIcons: true }));
				button.label = `$(${Codicon.graph.id}) ${localize('femResults.pmButton', "Work Out the Interaction Diagrams")}`;
				this.renderStore.add(button.onDidClick(() => void this.loadInteraction()));
			}
			return;
		}
		if (diagram.assumedBars) {
			append(section, $('.fem-results-note.warning', undefined, localize('femResults.pmAssumed', "Object type {0} has no bars: the diagram is of the bars the design checks assume.", diagram.type)));
		}
		const grid = this.grid(section);
		// C13b: forces and moments in the display units (kN and kN·m in SI)
		const display = activeDisplayUnits();
		const F = (v: number) => toDisplay(v, 'kN', display);
		const M = (v: number) => toDisplay(v, 'kN·m', display);
		const fu = displayUnit('kN', display);
		const mu = displayUnit('kN·m', display);
		for (const axis of ['x', 'y'] as const) {
			const moment = (p: typeof diagram.points[number]) => axis === 'x' ? p.Mx : p.My;
			renderChart(grid, {
				title: axis === 'x' ? localize('femResults.pmX', "P–Mx (about the section's x axis)") : localize('femResults.pmY', "P–My (about the section's y axis)"),
				xLabel: localize('femResults.phiMUnit', "φMn, Mu [{0}]", mu),
				yLabel: localize('femResults.phiPUnit', "φPn, Pu [{0}] (compression +)", fu),
				series: [
					{ name: localize('femResults.capacitySeries', "φ capacity"), color: 'blue', points: closedPmCurve(diagram, axis).map(([m, p]) => [M(m), F(p)]) },
					{
						name: localize('femResults.demands', "Demands"), color: 'orange', style: 'points',
						points: diagram.points.map(p => [M(moment(p)), F(p.P)]),
						tooltips: diagram.points.map(p => `${p.combination}, ${p.where}: Pu ${fixed(F(p.P), 1)} ${fu}, M${axis} ${fixed(M(moment(p)), 1)} ${mu}`),
					},
				],
				caption: diagram.governing ? localize('femResults.pmGoverningUnit', "Governing: {0} at {1}, Pu = {2} {4}, utilisation {3}", diagram.governing.combination, diagram.governing.where, fixed(F(diagram.governing.P), 1), diagram.governing.utilisation.toFixed(2), fu) : undefined,
				height: 320,
			});
		}
		if (diagram.contour?.length && diagram.governing) {
			const governing = diagram.governing;
			const near = diagram.points.filter(p => p.combination === governing.combination);
			renderChart(grid, {
				title: localize('femResults.biaxialUnit', "Mx–My at Pu = {0} {1} (biaxial)", fixed(F(governing.P), 1), fu),
				xLabel: localize('femResults.mxUnit', "Mx [{0}]", mu),
				yLabel: localize('femResults.myUnit', "My [{0}]", mu),
				equalAxes: true,
				series: [
					{ name: localize('femResults.contour', "φ capacity at Pu"), color: 'blue', points: [...diagram.contour, diagram.contour[0]].map(p => [M(p[0]), M(p[1])]) },
					{
						name: governing.combination, color: 'orange', style: 'points',
						points: near.map(p => [M(p.Mx), M(p.My)]),
						tooltips: near.map(p => `${p.combination}, ${p.where}: Pu ${fixed(F(p.P), 1)} ${fu}, Mx ${fixed(M(p.Mx), 1)}, My ${fixed(M(p.My), 1)} ${mu}`),
					},
				],
				caption: localize('femResults.biaxialCaption', "The contour is the capacity at the governing combination's axial force; its demands are shown (absolute moments)."),
				height: 320,
			});
		}
	}

	private renderRequired(member: string, detail: IFemMemberForces): void {
		const section = this.section(localize('femResults.steelHeading', "Reinforcement: Required and Provided"), localize('femResults.steelHelp', "The steel the design checks require at the beam's start, middle and end (As,min included) against the bars entered."));
		const rows = this.required;
		if (!rows) {
			const loading = this.requiredState === 'loading';
			append(section, $('.fem-results-note', undefined, loading
				? localize('femResults.steelLoading', "Working out the steel the members require (up to a minute or two the first time after a run)...")
				: this.requiredState === 'failed' ? localize('femResults.steelFailed', "The required steel is not available.") : localize('femResults.steelIdle', "The design checks size the steel of every member at once.")));
			if (!loading) {
				const button = this.renderStore.add(new Button(section, { ...defaultButtonStyles, supportIcons: true }));
				button.label = `$(${Codicon.symbolRuler.id}) ${localize('femResults.steelButton', "Work Out the Required Steel")}`;
				this.renderStore.add(button.onDidClick(() => void this.loadRequired()));
			}
			return;
		}
		if (!rows.length) {
			append(section, $('.fem-results-note', undefined, localize('femResults.steelNone', "The design checks have no steel for {0}.", member)));
			return;
		}
		// C13b: the stations and the areas in the display units (m and mm² in SI)
		const level = this.units.level;
		const display = activeDisplayUnits();
		const area = (v: number) => toDisplay(v, 'mm²', display);
		const areaUnit = displayUnit('mm²', display);
		const digits = areaUnit === 'mm²' ? 0 : 2;
		const at = (location: string) => /start/i.test(location) ? 0 : /end/i.test(location) ? detail.length * level.scale : /mid/i.test(location) ? detail.length * level.scale / 2 : undefined;
		const series: IChartSeries[] = [];
		const colors: ChartColor[] = ['blue', 'orange', 'green', 'purple'];
		const quantities = [...new Set(rows.filter(r => r.unit === 'mm²' && at(r.location) !== undefined).map(r => r.quantity))];
		quantities.forEach((quantity, k) => {
			const mine = rows.filter(r => r.quantity === quantity && at(r.location) !== undefined).sort((a, b) => at(a.location)! - at(b.location)!);
			series.push({ name: localize('femResults.requiredSeries', "{0}: required", quantity), color: colors[k % colors.length], points: mine.map(r => [at(r.location)!, area(r.required)]), tooltips: mine.map(r => `${r.location}, ${quantity}: required ${fixed(area(r.required), digits)} ${areaUnit} (${r.combination ?? ''})`) });
			const provided = mine.filter(r => r.provided !== null);
			if (provided.length) {
				series.push({ name: localize('femResults.providedSeries', "{0}: provided", quantity), color: colors[k % colors.length], style: 'dashed', points: provided.map(r => [at(r.location)!, area(r.provided!)]), tooltips: provided.map(r => `${r.location}, ${quantity}: provided ${fixed(area(r.provided!), digits)} ${areaUnit}`) });
			}
		});
		if (series.length) {
			renderChart(this.grid(section), {
				title: localize('femResults.steelChart', "Longitudinal Steel Along the Span"),
				xLabel: withUnit(localize('femResults.stationName', "Distance along the member"), level),
				yLabel: withUnit(localize('femResults.areaName', "Steel area"), { scale: 1, unit: areaUnit }),
				series,
				include: { x: [0, detail.length * level.scale] },
				xDomain: [0, detail.length * level.scale],
				caption: rows.some(r => r.ok === false) ? localize('femResults.steelShort', "Bars short of the requirement: {0}", rows.filter(r => r.ok === false).map(r => `${r.location} ${r.quantity}`).join(', ')) : undefined,
			});
		}
		renderSheet(section, {
			name: localize('femResults.steelTable', "Steel required"),
			columns: [localize('femResults.location', "Location"), localize('femResults.quantity', "Quantity"), localize('femResults.requiredCol', "Required"), localize('femResults.providedCol', "Provided"), localize('femResults.unitCol', "Unit"), localize('femResults.combinationCol', "Combination"), localize('femResults.okCol', "OK")],
			rows: rows.map(r => [r.location, r.quantity, toDisplay(r.required, r.unit, display), typeof r.provided === 'number' ? toDisplay(r.provided, r.unit, display) : (r.provided ?? ''), displayUnit(r.unit, display), r.combination ?? '', r.ok === null ? '' : r.ok ? localize('femResults.yes', "yes") : localize('femResults.no', "no")]),
		});
	}
}

/**
 * The frame members of an analysis model by name (`C3#2` is part of `C3`), sorted naturally;
 * the struts tying frames into solids are left out.
 */
export function memberNames(elements: readonly { readonly name?: string; readonly nodes?: readonly number[] }[]): string[] {
	const names = new Set<string>();
	for (const element of elements) {
		if (element.nodes?.length === 2 && element.name && !/\/embed(#\d+)?$/.test(element.name)) {
			names.add(element.name.split('#')[0]);
		}
	}
	return [...names].sort(safeIntl.Collator(undefined, { numeric: true }).value.compare);
}
