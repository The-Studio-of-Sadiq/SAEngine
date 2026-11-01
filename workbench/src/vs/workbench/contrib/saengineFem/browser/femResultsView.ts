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
import { IFemResultList } from '../../../../platform/saengine/common/femSolver.js';
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
import { baseReactionTable, closedPmCurve, defaultChartResult, describeMode, elasticDriftLimit, orderLike, extremes, FEM_COLUMN_INTERACTION_COMMAND, FEM_MEMBER_FORCES_COMMAND, FEM_STORY_RESPONSE_COMMAND, FemAxis2, IFemColumnDiagram, IFemColumnInteraction, IFemMemberForces, IFemStoryResponse, IFemStoryResult, IFemTimeHistoryDesign, isEarthquakeResult, MemberComponent, memberEnvelope, memberValues, modalTable, modesToReach, profilePeak, spectrumAt, storeyProfile, StoreyQuantity, storeyQuantityLabel, STOREY_QUANTITIES } from './femChartData.js';
import { IFemDesignRequired, IFemSteelRequirement, resultsFolder, runDesignRequired } from './femDesign.js';
import { appendPlannedChips, FemPlanned } from './femPlannedFeatures.js';
import { errorSummary, FEM_RESULT_LIST_COMMAND, IFemRunTracker } from './femResultsBar.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';

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
}

export function chartUnits(units: string | undefined): IChartUnits {
	if (units?.startsWith('SI')) {
		return {
			length: { scale: 1000, unit: 'mm' },
			force: { scale: 1e-3, unit: 'kN' },
			moment: { scale: 1e-3, unit: 'kN·m' },
			acceleration: { scale: 1 / 9.80665, unit: 'g' },
		};
	}
	return { length: { scale: 1, unit: '' }, force: { scale: 1, unit: '' }, moment: { scale: 1, unit: '' }, acceleration: { scale: 1, unit: '' } };
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
	private response: IFemStoryResponse | undefined;
	private member: IFemMemberForces | undefined;
	private interaction: IFemColumnDiagram | undefined;
	private interactionState: 'idle' | 'loading' | 'none' | 'failed' = 'idle';
	private interactionProblem: string | undefined;
	private required: readonly IFemSteelRequirement[] | undefined;
	private requiredState: 'idle' | 'loading' | 'failed' = 'idle';
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
			this.units = chartUnits(meta);
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
			} else {
				const member = await this.commandService.executeCommand<IFemMemberForces>(FEM_MEMBER_FORCES_COMMAND, input.model, input.page.member);
				if (request !== this.request) {
					return;
				}
				this.member = input.state.member = member;
				this.interaction = undefined;
				this.interactionState = 'idle';
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
		this.render();
		try {
			const answer = await this.commandService.executeCommand<IFemColumnInteraction>(FEM_COLUMN_INTERACTION_COMMAND, input.model, member);
			if (!current()) {
				return;
			}
			this.interaction = answer?.columns[member];
			this.interactionState = this.interaction ? 'idle' : 'none';
		} catch (error) {
			if (!current()) {
				return;
			}
			this.interactionState = 'failed';
			this.interactionProblem = errorSummary(error);
		}
		this.render();
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
		const reactions = baseReactionTable(response, { force: v => v * this.units.force.scale, moment: v => v * this.units.moment.scale });
		if (reactions.rows.length) {
			const section = this.section(localize('femResults.baseHeading', "Base Reactions"), localize('femResults.baseHelp', "The sum of the support reactions of each static case and combination (the supports push on the structure)."));
			renderSheet(section, reactions);
		}
		for (const curve of response.pushover) {
			const section = this.section(localize('femResults.pushoverHeading', "Pushover: {0}", curve.label));
			renderChart(this.grid(section), {
				title: localize('femResults.capacity', "Capacity Curve"),
				xLabel: withUnit(localize('femResults.controlDisp', "Control displacement"), this.units.length),
				yLabel: withUnit(localize('femResults.baseShear', "Base shear"), this.units.force),
				series: [{ name: curve.label, color: 'blue', points: curve.displacement.map((d, k) => [d * this.units.length.scale, Math.abs(curve.shear[k]) * this.units.force.scale]) }],
			});
			// Where the performance point and the hinge states will show.
			this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.performancePoint, FemPlanned.pushoverHinges, FemPlanned.fibreWalls], this.commandService));
		}
		for (const history of response.histories) {
			const section = this.section(localize('femResults.historyHeading', "Time History: {0}", history.label));
			renderChart(this.grid(section), {
				title: localize('femResults.roof', "Roof Displacement (node {0})", history.node),
				xLabel: localize('femResults.time', "Time [s]"),
				yLabel: withUnit(localize('femResults.displacement', "Displacement"), this.units.length),
				series: (['X', 'Y'] as const).map((axis, a) => ({ name: axis, color: AXIS_COLORS[axis], points: history.time.map((t, k) => [t, history.displacement[k][a] * this.units.length.scale]) })),
			});
			this.renderStore.add(appendPlannedChips(section, undefined, [FemPlanned.nonlinearTimeHistory, FemPlanned.recordScaling], this.commandService));
		}
		const historyDesign = response.spectrumDesign?.timeHistory;
		if (historyDesign) {
			this.renderTimeHistoryDesign(historyDesign);
		}
	}

	/** The linear time-history design (B19): each suite's spectrum against the code's criterion, the suites' base shears and factors, the drifts. */
	private renderTimeHistoryDesign(design: IFemTimeHistoryDesign): void {
		const clauses = [design.clauses['records'], design.clauses['response']].filter(c => !!c).join('; ');
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
				notes: design.clauses['drift'] ? [design.clauses['drift']] : undefined,
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
					? localize('femResults.spectrumScaledHelp', "Peak values of the response spectrum case (no signs). Storey forces, shears and overturning are scaled by {0} to 0.85·V as the design uses them ({1}); displacements and drifts are unscaled, as BNBC requires for drift. Drifts combine the modal drifts, as the spectrum design does.", scale.toFixed(3), response.spectrumDesign?.clause ?? 'BNBC 2020 Part 6 Sec 2.5.9.4')
					: localize('femResults.spectrumUnscaledHelp', "Peak values of the response spectrum case (no signs), unscaled: the response spectrum design (Design Utilisation) has not been worked out for this run, so the forces are not yet scaled to 0.85·V (BNBC 2020 Part 6 Sec 2.5.9.4). Drifts combine the modal drifts, as the spectrum design does."),
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
					points: profile.map(p => [p.value * unit.scale, p.z]),
					tooltips: profile.map(p => `${axis}, ${p.level} (${p.z.toFixed(2)} m): ${[show(p.value), unit.unit].filter(Boolean).join(' ')}`),
				});
				const peak = profilePeak(profile);
				if (peak && Math.abs(peak.value) > 0) {
					captions.push(localize('femResults.peakCaption', "{0}: largest {1} at {2}", axis, [show(peak.value), unit.unit].filter(Boolean).join(' '), peak.level));
					marks.push({ x: peak.value * unit.scale, y: peak.z, text: show(peak.value), color: AXIS_COLORS[axis] });
				}
			}
			const guides = quantity === 'drift' && limit !== undefined && (isEarthquakeResult(result.label) || spectrum)
				? [{ axis: 'x' as const, value: limit, label: localize('femResults.driftLimit', "BNBC limit {0}", limit.toFixed(5)), color: 'red' as const }]
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
						captions.push(localize('femResults.designDriftCaption', "{0}: design drift Cd·δ/I with the accidental torsion {1} % between {2} and {3} m (allowable {4} %, {5}).", axis, (100 * worst.ratio).toFixed(2), worst.bottom, worst.top, (100 * worst.allowableRatio).toFixed(2), worst.ok ? localize('femResults.ok', "OK") : localize('femResults.notOk', "exceeded")));
					}
				}
			}
			renderChart(grid, {
				title,
				xLabel: withUnit(storeyQuantityLabel(quantity), unit),
				yLabel: localize('femResults.elevation', "Elevation [m]"),
				series,
				guides,
				marks,
				include: { x: [0], y: response.levels.map(l => l.z) },
				caption: captions.join(' · ') || localize('femResults.zeroCaption', "No {0} in this result.", storeyQuantityLabel(quantity).toLowerCase()),
				height: 320,
			});
		}
	}

	private renderModal(response: IFemStoryResponse): void {
		const modal = response.modal!;
		const section = this.section(localize('femResults.modalHeading', "Modal Periods and Mass Participation"), localize('femResults.modalHelp', "BNBC 2020 Part 6 Sec 2.5.9.2: include enough modes to reach 90 % of the mass in each direction."));
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
				: localize('femResults.notReached', "{0} reaches only {1} % with {2} modes", axis, last && sum(last) !== null ? (100 * sum(last)!).toFixed(1) : '–', modal.modes.length));
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

	private renderSpectrum(response: IFemStoryResponse): void {
		const spectrum = response.spectrum!;
		const unit = this.units.acceleration;
		const section = this.section(localize('femResults.spectrumHeading', "Design Response Spectrum"), spectrum.name);
		const modes = (response.modal?.modes ?? []).filter(m => m.period !== null);
		const marks = modes.slice(0, 3).map(m => ({ x: m.period!, y: spectrumAt(spectrum, m.period!) * unit.scale, text: `T${m.number}`, color: 'orange' as ChartColor }));
		renderChart(this.grid(section), {
			title: localize('femResults.spectrumTitle', "Sa(T) with the Modal Periods"),
			xLabel: localize('femResults.periodAxis', "Period T [s]"),
			yLabel: withUnit(localize('femResults.sa', "Sa"), unit),
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
			: localize('femResults.beamAxes', "From the member's start (0 m). Member axes: 1 along it; tension positive; sagging M2 negative (tension at the bottom), hogging positive."));
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
		const x = detail.stations;
		for (const { c, title, unit } of components) {
			const digits = unit === this.units.length ? 3 : 1;
			const show = (v: number) => `${fixed(v * unit.scale, digits)} ${unit.unit}`;
			let series: IChartSeries[];
			let caption: string;
			if (envelope) {
				const env = memberEnvelope(detail, c);
				series = [
					{ name: localize('femResults.max', "Max"), color: 'blue', style: 'area', points: x.map((s, k) => [s, env.max[k] * unit.scale]), tooltips: x.map((s, k) => `${s.toFixed(2)} m: ${show(env.max[k])} (${env.maxBy[k]})`) },
					{ name: localize('femResults.min', "Min"), color: 'red', style: 'area', points: x.map((s, k) => [s, env.min[k] * unit.scale]), tooltips: x.map((s, k) => `${s.toFixed(2)} m: ${show(env.min[k])} (${env.minBy[k]})`) },
				];
				const hi = extremes(x, env.max);
				const lo = extremes(x, env.min);
				caption = hi && lo ? localize('femResults.envelopeCaption', "Max {0} at {1} m; min {2} at {3} m", show(hi.max.value), hi.max.at.toFixed(2), show(lo.min.value), lo.min.at.toFixed(2)) : '';
			} else if (result) {
				const values = memberValues(result, c);
				series = [{ name: result.label, color: 'blue', style: 'area', points: x.map((s, k) => [s, values[k] * unit.scale]), tooltips: x.map((s, k) => `${s.toFixed(2)} m: ${show(values[k])}`) }];
				const e = extremes(x, values);
				caption = e ? localize('femResults.extremesCaption', "Max {0} at {1} m; min {2} at {3} m", show(e.max.value), e.max.at.toFixed(2), show(e.min.value), e.min.at.toFixed(2)) : '';
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
				xLabel: localize('femResults.station', "Distance along the member [m]"),
				yLabel: withUnit(title.split(' (')[0], unit),
				series,
				marks,
				include: { x: [0, detail.length], y: [0] },
				xDomain: [0, detail.length],
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
		const section = this.section(localize('femResults.pmHeading', "P–M Interaction"), localize('femResults.pmHelp', "φ-factored capacities of the column's section and bars (SAEngine's design checks, ACI 318-19 as BNBC 2020 Part 6 adopts) with the demand of every load combination: the largest axial force and the largest moments of each."));
		const diagram = this.interaction;
		if (!diagram) {
			const note = this.interactionState === 'loading'
				? localize('femResults.pmLoading', "Working out the interaction diagrams of the run's columns with the design checks (a few minutes the first time after a run; then they are kept beside the results)...")
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
		for (const axis of ['x', 'y'] as const) {
			const moment = (p: typeof diagram.points[number]) => axis === 'x' ? p.Mx : p.My;
			renderChart(grid, {
				title: axis === 'x' ? localize('femResults.pmX', "P–Mx (about the section's x axis)") : localize('femResults.pmY', "P–My (about the section's y axis)"),
				xLabel: localize('femResults.phiM', "φMn, Mu [kN·m]"),
				yLabel: localize('femResults.phiP', "φPn, Pu [kN] (compression +)"),
				series: [
					{ name: localize('femResults.capacitySeries', "φ capacity"), color: 'blue', points: closedPmCurve(diagram, axis) },
					{
						name: localize('femResults.demands', "Demands"), color: 'orange', style: 'points',
						points: diagram.points.map(p => [moment(p), p.P]),
						tooltips: diagram.points.map(p => `${p.combination}, ${p.where}: Pu ${fixed(p.P, 1)} kN, M${axis} ${fixed(moment(p), 1)} kN·m`),
					},
				],
				caption: diagram.governing ? localize('femResults.pmGoverning', "Governing: {0} at {1}, Pu = {2} kN, utilisation {3}", diagram.governing.combination, diagram.governing.where, fixed(diagram.governing.P, 1), diagram.governing.utilisation.toFixed(2)) : undefined,
				height: 320,
			});
		}
		if (diagram.contour?.length && diagram.governing) {
			const governing = diagram.governing;
			const near = diagram.points.filter(p => p.combination === governing.combination);
			renderChart(grid, {
				title: localize('femResults.biaxial', "Mx–My at Pu = {0} kN (biaxial)", fixed(governing.P, 1)),
				xLabel: localize('femResults.mx', "Mx [kN·m]"),
				yLabel: localize('femResults.my', "My [kN·m]"),
				equalAxes: true,
				series: [
					{ name: localize('femResults.contour', "φ capacity at Pu"), color: 'blue', points: [...diagram.contour, diagram.contour[0]].map(p => [p[0], p[1]]) },
					{
						name: governing.combination, color: 'orange', style: 'points',
						points: near.map(p => [p.Mx, p.My]),
						tooltips: near.map(p => `${p.combination}, ${p.where}: Pu ${fixed(p.P, 1)} kN, Mx ${fixed(p.Mx, 1)}, My ${fixed(p.My, 1)} kN·m`),
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
		const at = (location: string) => /start/i.test(location) ? 0 : /end/i.test(location) ? detail.length : /mid/i.test(location) ? detail.length / 2 : undefined;
		const series: IChartSeries[] = [];
		const colors: ChartColor[] = ['blue', 'orange', 'green', 'purple'];
		const quantities = [...new Set(rows.filter(r => r.unit === 'mm²' && at(r.location) !== undefined).map(r => r.quantity))];
		quantities.forEach((quantity, k) => {
			const mine = rows.filter(r => r.quantity === quantity && at(r.location) !== undefined).sort((a, b) => at(a.location)! - at(b.location)!);
			series.push({ name: localize('femResults.requiredSeries', "{0}: required", quantity), color: colors[k % colors.length], points: mine.map(r => [at(r.location)!, r.required]), tooltips: mine.map(r => `${r.location}, ${quantity}: required ${fixed(r.required, 0)} mm² (${r.combination ?? ''})`) });
			const provided = mine.filter(r => r.provided !== null);
			if (provided.length) {
				series.push({ name: localize('femResults.providedSeries', "{0}: provided", quantity), color: colors[k % colors.length], style: 'dashed', points: provided.map(r => [at(r.location)!, r.provided!]), tooltips: provided.map(r => `${r.location}, ${quantity}: provided ${fixed(r.provided!, 0)} mm²`) });
			}
		});
		if (series.length) {
			renderChart(this.grid(section), {
				title: localize('femResults.steelChart', "Longitudinal Steel Along the Span"),
				xLabel: localize('femResults.station', "Distance along the member [m]"),
				yLabel: localize('femResults.area', "Steel area [mm²]"),
				series,
				include: { x: [0, detail.length] },
				xDomain: [0, detail.length],
				caption: rows.some(r => r.ok === false) ? localize('femResults.steelShort', "Bars short of the requirement: {0}", rows.filter(r => r.ok === false).map(r => `${r.location} ${r.quantity}`).join(', ')) : undefined,
			});
		}
		renderSheet(section, {
			name: localize('femResults.steelTable', "Steel required"),
			columns: [localize('femResults.location', "Location"), localize('femResults.quantity', "Quantity"), localize('femResults.requiredCol', "Required"), localize('femResults.providedCol', "Provided"), localize('femResults.unitCol', "Unit"), localize('femResults.combinationCol', "Combination"), localize('femResults.okCol', "OK")],
			rows: rows.map(r => [r.location, r.quantity, r.required, r.provided ?? '', r.unit, r.combination ?? '', r.ok === null ? '' : r.ok ? localize('femResults.yes', "yes") : localize('femResults.no', "no")]),
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
