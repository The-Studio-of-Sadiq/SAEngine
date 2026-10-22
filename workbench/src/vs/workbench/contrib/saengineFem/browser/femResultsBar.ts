/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { FemResultDisplay, FemResultQuantity, FemSelection, FemValueQuantity } from '@saengine/fem-viewer';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { RunOnceScheduler, timeout } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, IDisposable, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ResourceMap } from '../../../../base/common/map.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { IFemResultEntry, IFemResultList, IFemResultView } from '../../../../platform/saengine/common/femSolver.js';
import { defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { EditorFrame, IEditorFrameIconButton, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { describeDesignSummary, describeSlenderness, describeSteel, describeSteelRatio, designElementOf, designInputs, designKindLabel, designUtilisation, formatCheckValues, formatUtilisation, IFemDesignReport, IFemDesignRequired, IFemSteelRequirement, isOtherFailure, isSecondOrderRequired, isSlendernessCheck, otherFailureElements, requiredSteelOf, resultsFolder, runDesign, runDesignRequired, secondOrderRequiredMembers, shortElements, slendernessHeading, sortedChecks, tooSmallElements, writeDesignSummary } from './femDesign.js';
import { describeScaleOnResult, describeSecondOrder, FemAxis, IFemSecondOrder, isFirstOrderReference, IFemSeismicDesign, runSecondOrder, runSeismicDesign, seismicSection, spectrumAxis, storeyAmplificationRows } from './femSeismicDesign.js';
import { FemSsiPanel } from './femSsi.js';

export { resultsFolder } from './femDesign.js';

/** Desktop commands reading a run's results with the Python backend (see `saengine.fem.resultList`). */
const LIST_COMMAND = 'saengine.fem.resultList';
const VIEW_COMMAND = 'saengine.fem.resultView';

/**
 * The frames a result steps through: a time history's moments, a pushover's steps, a staged
 * (construction sequence) static case's stages; none for the others.
 */
function framesOf(entry: IFemResultEntry): NonNullable<IFemResultEntry['frames']> {
	return entry.kind === 'history' || entry.kind === 'pushover' || entry.kind === 'static' ? entry.frames ?? [] : [];
}

type Show = FemResultQuantity | 'none';

interface IShowOption {
	readonly show: Show;
	readonly label: string;
}

const MODEL_ONLY: IShowOption = { show: 'none', label: localize('femResults.modelOnly', "Model Only") };
const STATIC_OPTIONS: readonly IShowOption[] = [
	MODEL_ONLY,
	{ show: 'deformed', label: localize('femResults.deformed', "Deflected Shape") },
	{ show: 'reactions', label: localize('femResults.reactions', "Support Reactions") },
	{ show: 'N', label: localize('femResults.axial', "Axial Force N") },
	{ show: 'Vy', label: localize('femResults.shearY', "Shear Force Vy") },
	{ show: 'Vz', label: localize('femResults.shearZ', "Shear Force Vz") },
	{ show: 'T', label: localize('femResults.torsion', "Torsion T") },
	{ show: 'My', label: localize('femResults.momentY', "Moment My") },
	{ show: 'Mz', label: localize('femResults.momentZ', "Moment Mz") },
];
/** Shell section forces per unit length, offered when the model has shells. */
const SHELL_OPTIONS: readonly IShowOption[] = [
	{ show: 'M11', label: localize('femResults.m11', "Shell Moment M11") },
	{ show: 'M22', label: localize('femResults.m22', "Shell Moment M22") },
	{ show: 'M12', label: localize('femResults.m12', "Shell Twisting Moment M12") },
	{ show: 'N11', label: localize('femResults.n11', "Shell Membrane Force N11") },
	{ show: 'N22', label: localize('femResults.n22', "Shell Membrane Force N22") },
	{ show: 'N12', label: localize('femResults.n12', "Shell Membrane Shear N12") },
	{ show: 'Q13', label: localize('femResults.q13', "Shell Transverse Shear Q13") },
	{ show: 'Q23', label: localize('femResults.q23', "Shell Transverse Shear Q23") },
];
/**
 * The reinforced-concrete design checks of the run, enveloped over the load combinations:
 * independent of the result picked, offered with every static case and combination.
 */
const DESIGN_OPTION: IShowOption = { show: 'utilisation', label: localize('femResults.design', "Design Utilisation") };
const SHELL_COMPONENTS: readonly Show[] = ['N11', 'N22', 'N12', 'M11', 'M22', 'M12', 'Q13', 'Q23'];
/** Solid stresses, offered when the result has solids with stresses. */
const SOLID_OPTIONS: readonly IShowOption[] = [
	{ show: 'SVM', label: localize('femResults.svm', "Solid Stress, von Mises") },
	{ show: 'S11', label: localize('femResults.s11', "Solid Stress σxx") },
	{ show: 'S22', label: localize('femResults.s22', "Solid Stress σyy") },
	{ show: 'S33', label: localize('femResults.s33', "Solid Stress σzz") },
];
/** Index of each solid stress in a solid's `stress`. */
const SOLID_COMPONENTS: { readonly [show: string]: number } = { S11: 0, S22: 1, S33: 2, SVM: 6 };
const MODAL_OPTIONS: readonly IShowOption[] = [
	MODEL_ONLY,
	{ show: 'deformed', label: localize('femResults.modeShape', "Mode Shape") },
];
/** Response spectrum results are peak displacements only: no signs, forces or reactions. */
const SPECTRUM_OPTIONS: readonly IShowOption[] = [
	MODEL_ONLY,
	{ show: 'deformed', label: localize('femResults.peakDisplacements', "Peak Displacements") },
];
/** A time history at one moment: no reactions are recorded. */
const HISTORY_OPTIONS = STATIC_OPTIONS.filter(o => o.show !== 'reactions');

/** Size of the capacity curve drawn in the properties panel [px]. */
const CURVE_WIDTH = 240;
const CURVE_HEIGHT = 110;

/** Pause between frames while a time history plays [ms]. */
const FRAME_INTERVAL = 60;
const COMPONENTS: readonly Show[] = ['N', 'Vy', 'Vz', 'T', 'My', 'Mz'];

/** Steps of the scale multiplier offered by the − and + buttons. */
const SCALES = [0.25, 0.5, 1, 2, 4, 8, 16];

type Quantity = FemValueQuantity;

/**
 * Values in the units the user reads: SAEngine models are in SI (m, N), shown as mm, kN and
 * kN·m. Models in other units show their own values.
 */
export function resultFormatter(units: string | undefined): (quantity: Quantity, value: number) => string {
	if (units?.startsWith('SI')) {
		return (quantity, value) => {
			switch (quantity) {
				case 'length': return localize('femResults.mm', "{0} mm", (value * 1000).toFixed(2));
				case 'force': return localize('femResults.kN', "{0} kN", (value / 1000).toFixed(1));
				case 'moment': return localize('femResults.kNm', "{0} kN·m", (value / 1000).toFixed(1));
				case 'forcePerLength': return localize('femResults.kNperM', "{0} kN/m", (value / 1000).toFixed(1));
				case 'momentPerLength': return localize('femResults.kNmPerM', "{0} kN·m/m", (value / 1000).toFixed(2));
				case 'stress': return localize('femResults.MPa', "{0} MPa", (value / 1e6).toFixed(2));
			}
		};
	}
	return (_quantity, value) => Number(value.toPrecision(4)).toString();
}

/*
 * Desktop commands of the analysis runner (electron-browser/runAll.contribution.ts), called by
 * the FEM editor by id: running the cases with the progress shown in the editor, the result
 * tables of the last run, and its log.
 */

/** `(model: URI, options?: IFemRunOptions) => IFemRunOutcome`: runs the analysis of `model`. */
export const FEM_RUN_CASES_COMMAND = 'saengine.fem.runCases';
/** `(model: URI) => IFemCaseResults[]`: the result tables of `model`'s last run. */
export const FEM_RESULT_TABLES_COMMAND = 'saengine.fem.resultTables';
/** Opens the "SAEngine Analysis" output channel holding the log of the last run. */
export const FEM_SHOW_LOG_COMMAND = 'saengine.fem.showLog';

/** Where a run is, for a progress bar and a status line. */
export interface IFemRunProgress {
	/** Share of the run done, 0..1. */
	readonly fraction: number;
	/** "Dead load: step 3 of 10". */
	readonly message: string;
}

export interface IFemRunOptions {
	/** Ask which cases to run ("Run Selected Cases..."); by default all cases run. */
	readonly pick?: boolean;
	/** Receives the progress; without it, progress shows in the status bar. */
	readonly onProgress?: (progress: IFemRunProgress) => void;
	readonly token?: CancellationToken;
	/** Report problems only in the outcome, without notifications (Run All reports them itself). */
	readonly quiet?: boolean;
}

/** How a run ended. `message` says why for every status but `done` and `cancelled`. */
export interface IFemRunOutcome {
	/** `busy`: a run of the same model was already going, so this one did not start. */
	readonly status: 'done' | 'cancelled' | 'failed' | 'invalid' | 'empty' | 'unavailable' | 'busy';
	/** Number of cases run. */
	readonly cases: number;
	readonly message?: string;
}

/** A run of one model's analysis that is going, as {@link IFemRunTracker} knows it. */
export interface IFemRun {
	readonly model: URI;
	/** Where it is; undefined until the solver reports. */
	readonly progress: IFemRunProgress | undefined;
	/** Stops the run. */
	cancel(): void;
}

/** What the runner holds while its run goes: reports the progress, and ends the run when disposed. */
export interface IFemRunHandle extends IDisposable {
	report(progress: IFemRunProgress): void;
}

export const IFemRunTracker = createDecorator<IFemRunTracker>('saengineFemRunTracker');

/**
 * The analysis runs going, one per model at most: the runner takes a model's run before it clears
 * the results, so a second run (the editor's Run, the palette, Run All) cannot start meanwhile,
 * and the FEM editor shows (and can stop) a run started elsewhere.
 */
export interface IFemRunTracker {
	readonly _serviceBrand: undefined;
	/** A run of the model started, reported progress or ended. */
	readonly onDidChange: Event<URI>;
	/** The run of `model` going, if any. */
	get(model: URI): IFemRun | undefined;
	/** Takes the run of `model`: undefined when one is already going. */
	begin(model: URI, cancel: () => void): IFemRunHandle | undefined;
}

export class FemRunTracker extends Disposable implements IFemRunTracker {
	declare readonly _serviceBrand: undefined;

	private readonly runs = new ResourceMap<{ model: URI; progress: IFemRunProgress | undefined; cancel(): void }>();
	private readonly _onDidChange = this._register(new Emitter<URI>());
	readonly onDidChange = this._onDidChange.event;

	get(model: URI): IFemRun | undefined {
		return this.runs.get(model);
	}

	begin(model: URI, cancel: () => void): IFemRunHandle | undefined {
		if (this.runs.has(model)) {
			return undefined;
		}
		const run = { model, progress: undefined as IFemRunProgress | undefined, cancel };
		this.runs.set(model, run);
		this._onDidChange.fire(model);
		let ended = false;
		return {
			report: progress => {
				if (!ended) {
					run.progress = progress;
					this._onDidChange.fire(model);
				}
			},
			dispose: () => {
				if (!ended) {
					ended = true;
					this.runs.delete(model);
					this._onDidChange.fire(model);
				}
			},
		};
	}
}

/** Registered here, beside its interface, so the FEM editor has it in every window. */
registerSingleton(IFemRunTracker, FemRunTracker, InstantiationType.Delayed);

/**
 * The one line of an error from the backend that says what went wrong ("ValueError: unknown
 * result case:10"), for a status line or a notification. The backend's errors carry its stderr
 * (logs, Python tracebacks) after the message: those belong in the log. The line is the first one
 * that is not a traceback header or an (indented) traceback frame.
 */
export function errorSummary(error: unknown): string {
	const text = error instanceof Error ? error.message : String(error);
	const line = text.split(/\r?\n/).find(l => l.trim().length > 0 && !/^\s/.test(l) && !l.startsWith('Traceback ('));
	return (line ?? text).trim();
}

/** "13 members pass, 3 fail · largest utilisation 2.62 in F1 · 1 not checked · BNBC 2020": the status line's design summary. */
function designStatus(report: IFemDesignReport): string {
	const { passed, failed, skipped, maxUtilisation, governing } = report.summary;
	if (!report.elements.length) {
		return describeDesignSummary(report);
	}
	return [
		localize('femResults.designCounts', "{0} members pass, {1} fail", passed, failed),
		...(maxUtilisation !== null && governing ? [localize('femResults.designMax', "largest utilisation {0} in {1}", formatUtilisation(maxUtilisation), governing)] : []),
		...(skipped ? [localize('femResults.designSkippedCount', "{0} not checked", skipped)] : []),
		report.code,
	].join(' · ');
}

/** What the FEM editor does for the results controls. */
export interface IFemResultsHost {
	/** Draws a result in the 3D view; undefined shows the model alone. */
	setDisplay(view: IFemResultView | undefined, display: FemResultDisplay | undefined): void;
	/** The status, the legend, the properties or the toolbar's actions changed. */
	changed(): void;
	/** Runs the analysis again (offered when the results are out of date). */
	run(): void;
}

/** Adds a name/value row to a property sheet. */
export function propertyRow(container: HTMLElement, name: string, value: string): void {
	const row = append(container, $('.sa-props-row'));
	append(row, $('span.name', undefined, name));
	append(row, $('span.value', undefined, value));
}

/** Adds a heading to a property sheet. */
export function propertyHeading(container: HTMLElement, text: string): void {
	append(container, $('.sa-props-heading', undefined, text));
}

/** Adds a muted note to a property sheet. */
export function propertyNote(container: HTMLElement, text: string): void {
	append(container, $('.sa-props-note', undefined, text));
}

/**
 * The results of the last run in the FEM editor's toolbar: which result to show in 3D (a case,
 * a load combination of the project settings, or a mode) and what of it (deflected shape, a force
 * diagram, the reactions, the design utilisation), with the inline controls a result needs (mode,
 * stage/time/step slider and play, scale). What matters goes to the status line, the selected
 * node's or member's values to the properties panel, the colour scale to a legend over the view.
 */
export class FemResultsBar extends Disposable {

	private readonly resultGroup: HTMLElement;
	private readonly showGroup: HTMLElement;
	private readonly resultPicker: SelectBox;
	private readonly modePicker: SelectBox;
	private readonly showPicker: SelectBox;
	private readonly modeContainer: HTMLElement;
	private readonly animateButton: IEditorFrameIconButton;
	private readonly timeContainer: HTMLElement;
	private readonly timeSlider: HTMLInputElement;
	private readonly timeLabel: HTMLElement;
	private readonly timeCaption: HTMLElement;
	private readonly playButton: IEditorFrameIconButton;
	private readonly scaleContainer: HTMLElement;
	private readonly scaleLabel: HTMLElement;
	private playing = false;
	private playToken = 0;
	private readonly watch = this._register(new DisposableStore());
	private readonly resultsWatch = this._register(new MutableDisposable());
	private readonly reload = this._register(new RunOnceScheduler(() => void this.load(), 400));
	/** The design checks' own inputs (reinforcement, materials, combinations) changed. */
	// An edited input (the project settings: response spectrum design, orthogonal rule, torsion)
	// changes the seismic design as well as the checks: read both again, the seismic design first.
	private readonly redesign = this._register(new RunOnceScheduler(() => {
		void this.loadExtras(true);
		this.refreshDesign();
	}, 400));

	private resource: URI | undefined;
	private format = resultFormatter(undefined);
	private list: IFemResultList = { results: [], stale: false };
	private key: string | undefined;
	private mode = 1;
	private show: Show = 'deformed';
	/** What was shown before the design utilisation was toggled on. */
	private showBeforeDesign: Show = 'deformed';
	private scale = 1;
	private animate = true;
	private view: IFemResultView | undefined;
	private selection: FemSelection | undefined;
	private problem: string | undefined;
	private readonly views = new Map<string, IFemResultView>();
	private request = 0;
	private _version = 0;
	/** The run and result list last read (see `load`). */
	private signature: string | undefined;
	/** The design checks of the current run, once asked for (the "Design Utilisation" option). */
	private design: IFemDesignReport | undefined;
	/** The steel the members require, read with the checks when the backend offers it. */
	private required: IFemDesignRequired | undefined;
	/** The required steel is being worked out (after the checks show). */
	private requiredLoading = false;
	private designProblem: string | undefined;
	private designLoading = false;
	private designToken = 0;
	/** The soil springs' section of the properties panel (models on soil springs). */
	private readonly ssi: FemSsiPanel;
	/** The response spectrum scaled for design, when the project designs from it. */
	private seismic: IFemSeismicDesign | undefined;
	/** What the second-order (P-Delta) analysis changed, when the run is second order. */
	private secondOrder: IFemSecondOrder | undefined;
	private extrasToken = 0;
	/**
	 * Settles once the run's response spectrum design has been worked out (or failed, or is not
	 * offered): the design checks wait for it, since their RS combinations read what it writes.
	 */
	private seismicReady: Promise<unknown> = Promise.resolve();

	constructor(
		frame: EditorFrame,
		/** Where the legend goes: a corner of the 3D view. */
		private readonly legend: HTMLElement,
		private readonly host: IFemResultsHost,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IContextViewService contextViewService: IContextViewService,
	) {
		super();
		this.ssi = this._register(new FemSsiPanel(() => this.host.changed(), commandService, fileService, model => dirname(dirname(model))));
		const group = (slot: HTMLElement, className: string) => append(slot, $(`.fem-results-group.${className}`));

		this.resultGroup = group(frame.titleSlot, 'result');
		this.resultPicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.resultAria', "Analysis result shown") }));
		this.resultPicker.render(append(this.resultGroup, $('.fem-results-select.result')));
		this._register(this.resultPicker.onDidSelect(({ index }) => {
			this.stopPlaying();
			this.key = this.list.results[index]?.key;
			this.mode = this.firstFrame();
			void this.showResult();
		}));

		this.showGroup = group(frame.titleSlot, 'show');
		this.showPicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.showAria', "What to show of the result") }));
		this.showPicker.render(append(this.showGroup, $('.fem-results-select.show')));
		this._register(this.showPicker.onDidSelect(({ index }) => this.setShow(this.showOptions()[index]?.show ?? 'none')));

		// A modal result: the mode shown, and whether its shape oscillates.
		this.modeContainer = group(frame.controlsSlot, 'mode');
		append(this.modeContainer, $('span.sa-frame-label', undefined, localize('femResults.mode', "Mode")));
		this.modePicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.modeAria', "Mode shown") }));
		this.modePicker.render(append(this.modeContainer, $('.fem-results-select.mode')));
		this._register(this.modePicker.onDidSelect(({ index }) => {
			this.mode = index + 1;
			void this.showResult();
		}));
		this.animateButton = this._register(frame.createIconButton(this.modeContainer, Codicon.debugPause, localize('femResults.animate', "Animate the Mode Shape"), () => {
			this.animate = !this.animate;
			this.render();
		}));

		// A time history, a pushover or a staged case: the moment, step or stage shown, and playing it.
		this.timeContainer = group(frame.controlsSlot, 'time');
		this.timeCaption = append(this.timeContainer, $('span.sa-frame-label', undefined, localize('femResults.time', "Time")));
		this.timeSlider = append(this.timeContainer, $<HTMLInputElement>('input.fem-results-time', { type: 'range', min: '1', step: '1', 'aria-label': localize('femResults.timeAria', "Moment of the time history shown") }));
		this._register(addDisposableListener(this.timeSlider, EventType.INPUT, () => {
			this.stopPlaying();
			this.mode = Number(this.timeSlider.value);
			void this.showResult();
		}));
		this.timeLabel = append(this.timeContainer, $('span.fem-results-time-label'));
		this.playButton = this._register(frame.createIconButton(this.timeContainer, Codicon.play, localize('femResults.play', "Play"), () => this.playing ? this.stopPlaying() : void this.play()));
		this._register(toDisposable(() => this.stopPlaying()));

		// How large the deflections and diagrams are drawn.
		this.scaleContainer = group(frame.controlsSlot, 'scale');
		this._register(frame.createIconButton(this.scaleContainer, Codicon.remove, localize('femResults.smaller', "Draw Smaller"), () => this.step(-1)));
		this.scaleLabel = append(this.scaleContainer, $('span.fem-results-scale'));
		this._register(frame.createIconButton(this.scaleContainer, Codicon.add, localize('femResults.larger', "Draw Larger"), () => this.step(1)));

		this.render();
	}

	/** Counts the result lists read: changes when a new run's results arrive. */
	get version(): number {
		return this._version;
	}

	/** A run's results are there to show. */
	get hasResults(): boolean {
		return !!this.entry;
	}

	/** The design utilisation can be shown (a static case or a combination is picked). */
	get canShowDesign(): boolean {
		return this.showOptions().includes(DESIGN_OPTION);
	}

	get showsDesign(): boolean {
		return this.show === 'utilisation';
	}

	/** Shows the design utilisation, or what was shown before it. */
	toggleDesign(): void {
		this.setShow(this.show === 'utilisation' ? this.showBeforeDesign : 'utilisation');
	}

	/** The label of the result picked ("1.2D + 1.6L + 0.5Lr"): the name of its result tables too. */
	get resultLabel(): string | undefined {
		return this.entry?.label;
	}

	/** Picks the result labelled `label` (the tables panel's case picker follows the toolbar and leads it). */
	selectResult(label: string): void {
		const entry = this.list.results.find(r => r.label === label);
		if (!entry || entry.key === this.key) {
			return;
		}
		this.stopPlaying();
		this.key = entry.key;
		this.mode = this.firstFrame();
		void this.showResult();
	}

	/** Follows the results of `resource` when it is an analysis model (`.osmodel`). */
	setResource(resource: URI | undefined, units: string | undefined): void {
		this.format = resultFormatter(units);
		if (resource?.toString() === this.resource?.toString()) {
			this.render();
			return;
		}
		this.stopPlaying();
		this.resource = resource;
		this.ssi.setResource(resource);
		this.watch.clear();
		this.resultsWatch.clear();
		this.list = { results: [], stale: false };
		this.signature = undefined;
		this.key = undefined;
		this.views.clear();
		this.view = undefined;
		this.clearDesign();
		this.clearExtras();
		if (resource) {
			// A run deletes and writes again the results folder beside the model: watch the model's
			// folder for it, and the results folder for its manifest (written last).
			const results = resultsFolder(resource);
			const watchResults = () => {
				const store = new DisposableStore();
				const watcher = store.add(this.fileService.createWatcher(results, { recursive: false, excludes: [] }));
				store.add(watcher.onDidChange(e => {
					if (e.contains(joinPath(results, 'manifest.json'))) {
						this.reload.schedule();
					}
				}));
				this.resultsWatch.value = store;
			};
			const watcher = this.fileService.createWatcher(dirname(resource), { recursive: false, excludes: [] });
			this.watch.add(watcher);
			this.watch.add(watcher.onDidChange(e => {
				if (e.contains(results)) {
					watchResults();
					this.reload.schedule();
				} else if (e.contains(resource)) {
					this.reload.schedule();
				}
			}));
			watchResults();
			// The design checks also read the project's object types, materials, settings and
			// building model: editing the bars changes them without a new run.
			for (const input of designInputs(resource)) {
				const folder = this.fileService.createWatcher(dirname(input), { recursive: false, excludes: [] });
				this.watch.add(folder);
				this.watch.add(folder.onDidChange(e => {
					if (e.contains(input)) {
						this.redesign.schedule();
					}
				}));
			}
			void this.load();
		} else {
			this.render();
		}
	}

	setSelection(selection: FemSelection | undefined): void {
		this.selection = selection;
		this.host.changed();
	}

	private setShow(show: Show): void {
		if (show === 'utilisation' && this.show !== 'utilisation') {
			this.showBeforeDesign = this.show;
		}
		this.show = show;
		if (this.show === 'utilisation') {
			if (this.designProblem) {
				this.clearDesign(); // choosing it again retries
			}
			void this.loadDesign();
		}
		this.render();
	}

	private async load(): Promise<void> {
		const resource = this.resource;
		if (!resource) {
			return;
		}
		let list: IFemResultList;
		try {
			list = await this.commandService.executeCommand<IFemResultList>(LIST_COMMAND, resource) ?? { results: [], stale: false };
		} catch {
			list = { results: [], stale: false }; // no backend, or no run yet
		}
		// The run's identity: its manifest is written last. Files written beside it later (the
		// design summary) change the folder but not the run, and keep what was read of it.
		const manifest = await this.fileService.stat(joinPath(resultsFolder(resource), 'manifest.json')).then(s => s.mtime, () => 0);
		if (resource !== this.resource) {
			return;
		}
		const signature = `${manifest}|${JSON.stringify(list)}`;
		if (signature === this.signature) {
			return;
		}
		this.signature = signature;
		this.list = list;
		this._version++;
		this.views.clear();
		this.clearDesign();
		void this.loadExtras();
		if (this.show === 'utilisation') {
			void this.loadDesign();
		}
		if (!list.results.some(r => r.key === this.key)) {
			this.stopPlaying();
			this.key = list.results[0]?.key;
			this.mode = this.firstFrame();
		}
		await this.showResult();
	}

	private get entry(): IFemResultEntry | undefined {
		return this.list.results.find(r => r.key === this.key);
	}

	private showOptions(): readonly IShowOption[] {
		switch (this.entry?.kind) {
			case undefined: return [];
			case 'modal': return MODAL_OPTIONS;
			case 'spectrum': return SPECTRUM_OPTIONS;
			case 'history': return [...HISTORY_OPTIONS, ...(this.view?.solids?.some(s => s.stress) ? SOLID_OPTIONS : [])];
			case 'pushover': return [...STATIC_OPTIONS, ...(this.view?.solids?.some(s => s.stress) ? SOLID_OPTIONS : [])];
		}
		const solids = this.view?.solids?.some(s => s.stress) ? SOLID_OPTIONS : [];
		return [...STATIC_OPTIONS, ...(this.view?.shells?.length ? SHELL_OPTIONS : []), ...solids, DESIGN_OPTION];
	}

	private clearDesign(): void {
		this.design = undefined;
		this.required = undefined;
		this.requiredLoading = false;
		this.designProblem = undefined;
		this.designLoading = false;
		this.designToken++;
	}

	private clearExtras(): void {
		this.seismic = undefined;
		this.secondOrder = undefined;
		this.seismicReady = Promise.resolve();
		this.extrasToken++;
	}

	/**
	 * Reads the run's response spectrum design and second-order analysis, when the backend
	 * offers them: quiet without them (first-order run, no spectrum, older backend, failure).
	 * `keep`: a refresh after an input changed, keeping the values shown until the new ones come.
	 */
	private async loadExtras(keep = false): Promise<void> {
		const resource = this.resource;
		if (!resource || !this.list.results.length) {
			this.clearExtras();
			return;
		}
		if (keep) {
			// A refresh: what is shown stays until the new values arrive (no flicker).
			this.extrasToken++;
		} else {
			this.clearExtras();
		}
		const token = this.extrasToken;
		// Set before the first await, so a design started right after this call waits for it.
		const seismicRun = runSeismicDesign(this.commandService, resource).catch(() => undefined);
		this.seismicReady = seismicRun;
		const [seismic, secondOrder] = await Promise.all([
			seismicRun,
			runSecondOrder(this.commandService, resource).catch(() => undefined),
		]);
		if (token !== this.extrasToken || resource !== this.resource) {
			return;
		}
		this.seismic = seismic ?? undefined;
		this.secondOrder = secondOrder ?? undefined;
		this.host.changed();
	}

	/** Drops the design checks and, while they are shown, runs them again. */
	private refreshDesign(): void {
		if (!this.design && !this.designProblem && !this.designLoading) {
			return; // never asked for
		}
		this.clearDesign();
		if (this.show === 'utilisation') {
			void this.loadDesign();
		}
		this.render();
	}

	/** Runs the design checks of the current run once (new results or inputs clear them). */
	private async loadDesign(): Promise<void> {
		const resource = this.resource;
		if (!resource || this.design || this.designProblem || this.designLoading) {
			return;
		}
		const token = ++this.designToken;
		this.designLoading = true;
		let report: IFemDesignReport | undefined;
		let problem: string | undefined;
		// The response spectrum design writes the summary the design's RS combinations read: run
		// after it, or the first design after a run could fall back to the static EX / EY.
		await this.seismicReady;
		if (token !== this.designToken || resource !== this.resource) {
			return; // the results changed meanwhile (clearDesign reset the loading state)
		}
		// The required steel is extra: without it (no backend yet, or it failed) the checks still show.
		const required = runDesignRequired(this.commandService, resource).catch(() => undefined);
		try {
			report = await runDesign(this.commandService, resource);
			if (!report) {
				problem = localize('femResults.designUnavailable', "The design checks are not available.");
			}
		} catch (error) {
			problem = localize('femResults.designFailed', "The design checks failed: {0}", errorSummary(error));
		}
		if (token !== this.designToken || resource !== this.resource) {
			return; // the results changed meanwhile
		}
		this.design = report;
		this.designProblem = problem;
		this.designLoading = false;
		if (report) {
			// The project's part list reads the verdict from beside the results.
			void writeDesignSummary(this.fileService, resource, report).catch(() => undefined);
		}
		// The required steel takes longer (it sizes bars): it joins the checks when it comes, and
		// the checks shown meanwhile say it is on its way.
		this.requiredLoading = !!report;
		this.render();
		const steel = report ? await required : undefined;
		if (token === this.designToken && resource === this.resource) {
			this.required = steel;
			this.requiredLoading = false;
			this.render();
		}
	}

	private async showResult(): Promise<void> {
		const resource = this.resource;
		const entry = this.entry;
		this.problem = undefined;
		if (!resource || !entry) {
			this.view = undefined;
			this.render();
			return;
		}
		const framed = entry.kind === 'modal' || framesOf(entry).length > 0;
		const id = `${entry.key}/${framed ? this.mode : 0}`;
		let view = this.views.get(id);
		if (!view) {
			const request = ++this.request;
			try {
				view = await this.commandService.executeCommand<IFemResultView>(VIEW_COMMAND, resource, entry.key, framed ? this.mode : undefined);
			} catch (error) {
				this.view = undefined;
				this.problem = localize('femResults.failed', "The result could not be read: {0}", errorSummary(error));
				this.render();
				return;
			}
			if (request !== this.request || resource !== this.resource) {
				return;
			}
			if (view) {
				this.views.set(id, view);
			}
		}
		this.view = view;
		if (!this.showOptions().some(o => o.show === this.show)) {
			this.show = 'deformed';
		}
		this.render();
	}

	/** The frame a result opens at: a time history's peak, a staged case's last stage, else the first. */
	private firstFrame(): number {
		const entry = this.entry;
		return entry && framesOf(entry).length ? entry.peak ?? 1 : 1;
	}

	/** Plays the time history from the frame shown, looping, until stopped. */
	private async play(): Promise<void> {
		const token = ++this.playToken;
		this.playing = true;
		this.render();
		while (token === this.playToken) {
			const count = this.entry ? framesOf(this.entry).length : 0;
			if (!count) {
				break;
			}
			this.mode = this.mode >= count ? 1 : this.mode + 1;
			await this.showResult();
			await timeout(FRAME_INTERVAL);
		}
	}

	private stopPlaying(): void {
		if (this.playing) {
			this.playing = false;
			this.playToken++;
			this.render();
		}
	}

	private step(direction: number): void {
		const index = SCALES.indexOf(this.scale);
		this.scale = SCALES[Math.max(0, Math.min(SCALES.length - 1, index + direction))];
		this.render();
	}

	private render(): void {
		const entry = this.entry;
		this.resultGroup.classList.toggle('hidden', !entry);
		this.showGroup.classList.toggle('hidden', !entry);
		const modal = entry?.kind === 'modal';
		this.modeContainer.classList.toggle('hidden', !modal);
		const frames = entry ? framesOf(entry) : [];
		this.timeContainer.classList.toggle('hidden', !frames.length);
		const scalable = !!entry && this.show !== 'none' && this.show !== 'utilisation' && SOLID_COMPONENTS[this.show] === undefined && !SHELL_COMPONENTS.includes(this.show);
		this.scaleContainer.classList.toggle('hidden', !scalable);
		if (entry) {
			this.resultPicker.setOptions(this.list.results.map<ISelectOptionItem>(r => ({ text: r.label })), this.list.results.indexOf(entry));
			if (modal) {
				const modes = entry.modes ?? [];
				this.modePicker.setOptions(modes.map<ISelectOptionItem>(m => ({
					text: m.period === null ? String(m.number) : localize('femResults.modeOption', "{0} (T = {1} s)", m.number, m.period.toFixed(3)),
				})), Math.max(0, this.mode - 1));
				const animatable = this.show === 'deformed';
				this.animateButton.element.classList.toggle('hidden', !animatable);
				this.animateButton.setIcon(this.animate ? Codicon.debugPause : Codicon.play);
				this.animateButton.setTitle(this.animate ? localize('femResults.stopAnimation', "Stop Animating the Mode Shape") : localize('femResults.animate', "Animate the Mode Shape"));
			}
			if (frames.length) {
				this.timeSlider.max = String(frames.length);
				this.timeSlider.value = String(this.mode);
				const frame = frames[this.mode - 1];
				this.timeCaption.textContent = entry.kind === 'pushover' ? localize('femResults.step', "Step")
					: entry.kind === 'static' ? localize('femResults.stage', "Stage") : localize('femResults.time', "Time");
				this.timeSlider.setAttribute('aria-label', entry.kind === 'pushover' ? localize('femResults.stepAria', "Step of the pushover shown")
					: entry.kind === 'static' ? localize('femResults.stageAria', "Construction stage shown") : localize('femResults.timeAria', "Moment of the time history shown"));
				this.timeLabel.textContent = entry.kind === 'pushover'
					? localize('femResults.pushoverAt', "roof {0}, base shear {1}", this.format('length', frame?.displacement ?? 0), this.format('force', frame?.shear ?? 0))
					: entry.kind === 'static'
						? localize('femResults.stageOf', "{0} ({1} of {2})", frame?.stage ?? '', this.mode, frames.length)
						: localize('femResults.timeOf', "{0} of {1} s", (frame?.time ?? 0).toFixed(2), (frames[frames.length - 1].time ?? 0).toFixed(2));
				this.playButton.setIcon(this.playing ? Codicon.debugPause : Codicon.play);
				this.playButton.setTitle(this.playing ? localize('femResults.pause', "Pause") : localize('femResults.play', "Play"));
			}
			const options = this.showOptions();
			this.showPicker.setOptions(options.map<ISelectOptionItem>(o => ({ text: o.label })), Math.max(0, options.findIndex(o => o.show === this.show)));
			this.scaleLabel.textContent = `×${this.scale}`;
		}
		const view = this.view;
		this.host.setDisplay(
			view && this.show !== 'none' ? view : undefined,
			view && this.show !== 'none' ? {
				show: this.show,
				scale: this.scale,
				animate: this.animate,
				format: this.format,
				utilisation: this.show === 'utilisation' && this.design ? designUtilisation(this.design) : undefined,
			} : undefined,
		);
		this.renderLegend();
		this.host.changed();
	}

	// ───────────────────────────── status line ─────────────────────────────

	/** What the status line says about the result shown; undefined without results. */
	status(): IEditorFrameStatus | undefined {
		const entry = this.entry;
		if (!entry) {
			return undefined;
		}
		if (this.problem) {
			return { severity: 'error', text: this.problem };
		}
		if (this.list.stale) {
			return {
				severity: 'warning',
				text: localize('femResults.stale', "The model changed after this analysis ran."),
				link: { label: localize('femResults.runAgain', "Run Analysis"), run: () => this.host.run() },
			};
		}
		if (this.show === 'utilisation') {
			if (this.designProblem) {
				return { severity: 'error', text: this.designProblem };
			}
			if (!this.design) {
				return { busy: true, text: localize('femResults.designRunning', "Checking the members against the load combinations...") };
			}
			const secondOrderRequired = secondOrderRequiredMembers(this.design);
			return secondOrderRequired.length
				? { severity: 'warning', text: localize('femResults.designSecondOrderStatus', "{0} · second-order analysis required: {1}", designStatus(this.design), secondOrderRequired.join(', ')) }
				: { text: designStatus(this.design) };
		}
		const solidComponent = SOLID_COMPONENTS[this.show];
		if (solidComponent !== undefined) {
			return { text: localize('femResults.solidStress', "Tension positive; constant in each tetrahedron.") };
		}
		if (SHELL_COMPONENTS.includes(this.show)) {
			return { text: localize('femResults.shellAxes', "Local 1 runs along X on slabs and along the wall on walls.") };
		}
		if (entry.kind === 'pushover') {
			const frames = entry.frames ?? [];
			const peak = frames.reduce<typeof frames[number] | undefined>((best, f) => !best || Math.abs(f.shear ?? 0) > Math.abs(best.shear ?? 0) ? f : best, undefined);
			if (peak && this.show !== 'reactions' && !COMPONENTS.includes(this.show)) {
				return {
					text: localize('femResults.peakShear', "Largest base shear {0} at roof {1}.",
						this.format('force', Math.abs(peak.shear ?? 0)), this.format('length', Math.abs(peak.displacement ?? 0))),
				};
			}
		}
		const text = this.describeOverall();
		// The response spectrum's scaling for design; the drift amplification of a second-order run.
		const axis = entry.kind === 'spectrum' ? spectrumAxis(entry.label) : undefined;
		const scaled = axis ? describeScaleOnResult(this.seismic, axis) : undefined;
		const secondOrder = (entry.kind === 'static' || entry.kind === 'combination') && this.show !== 'none' && !isFirstOrderReference(entry.label)
			? describeSecondOrder(this.secondOrder)
			: undefined;
		// The temperature case: its member forces include the fixed-end forces added back.
		const thermal = /^T:/.test(entry.label) && this.show !== 'deformed' && this.show !== 'none'
			? localize('femResults.thermalNote', "Temperature T: forces include the members' fixed-end forces (added back); analysed without the rigid diaphragms.")
			: undefined;
		const shown = [text, scaled, secondOrder, thermal].filter(t => !!t).join(' ');
		return shown ? { text: shown } : undefined;
	}

	/** The values that matter for what is shown, over the whole model. */
	private describeOverall(): string | undefined {
		const view = this.view;
		if (!view) {
			return undefined;
		}
		const format = this.format;
		if (view.kind === 'modal') {
			const mode = this.entry?.modes?.[this.mode - 1];
			return mode?.period !== null && mode?.period !== undefined
				? localize('femResults.modePeriod', "Mode {0}: period {1} s, frequency {2} Hz.", mode.number, mode.period.toFixed(3), (1 / mode.period).toFixed(2))
				: undefined;
		}
		const component = COMPONENTS.indexOf(this.show);
		const quantity: Quantity = component >= 0 && component < 3 ? 'force' : 'moment';
		switch (this.show) {
			case 'deformed': {
				let largest: readonly number[] | undefined;
				for (const node of view.nodes) {
					if (!largest || Math.hypot(node[1], node[2], node[3]) > Math.hypot(largest[1], largest[2], largest[3])) {
						largest = node;
					}
				}
				return largest && localize('femResults.largestDisplacement', "Largest displacement {0} at node {1} (x {2}, y {3}, z {4}).",
					format('length', Math.hypot(largest[1], largest[2], largest[3])), largest[0], format('length', largest[1]), format('length', largest[2]), format('length', largest[3]));
			}
			case 'reactions': {
				const total = [1, 2, 3].map(i => view.reactions.reduce((sum, r) => sum + r[i], 0));
				return localize('femResults.totalReaction', "Total reaction: Fx {0}, Fy {1}, Fz {2}.", format('force', total[0]), format('force', total[1]), format('force', total[2]));
			}
			case 'none':
				return localize('femResults.modelShown', "{0}: choose what to show of it.", view.label);
			default: {
				let largest: { value: number; name: string } | undefined;
				for (const element of view.elements) {
					for (const forces of element.forces ?? []) {
						if (!largest || Math.abs(forces[component]) > Math.abs(largest.value)) {
							largest = { value: forces[component], name: element.name };
						}
					}
				}
				return largest && localize('femResults.largestForce', "Largest {0}: {1} in {2}. Select an element for its values.", this.show, format(quantity, largest.value), largest.name);
			}
		}
	}

	// ───────────────────────────── legend ─────────────────────────────

	/** The colour scale over the 3D view: utilisation bands, or a contour's range. */
	private renderLegend(): void {
		clearNode(this.legend);
		let shown = false;
		if (this.entry && this.show === 'utilisation' && this.design) {
			// The colours of the 3D view's utilisation bands.
			append(this.legend, $('.fem-legend-title', undefined, localize('femResults.utilisation', "Utilisation")));
			for (const [band, label] of [
				['pass', localize('femResults.designPass', "below 0.9")],
				['warn', localize('femResults.designWarn', "0.9 to 1.0")],
				['fail', localize('femResults.designFail', "above 1.0")],
			]) {
				const row = append(this.legend, $('.fem-legend-row'));
				append(row, $(`span.fem-design-swatch.${band}`));
				append(row, $('span', undefined, label));
			}
			shown = true;
		} else if (this.entry) {
			const contour = this.contourRange();
			if (contour) {
				append(this.legend, $('.fem-legend-title', undefined, this.showOptions().find(o => o.show === this.show)?.label ?? ''));
				const row = append(this.legend, $('.fem-legend-row'));
				append(row, $('span', undefined, contour.min));
				append(row, $('span.fem-results-scale-bar'));
				append(row, $('span', undefined, contour.max));
				shown = true;
			}
		}
		this.legend.classList.toggle('visible', shown);
	}

	/** The lowest and highest value of a shell or solid contour, as the 3D view colours it. */
	private contourRange(): { readonly min: string; readonly max: string } | undefined {
		const solidComponent = SOLID_COMPONENTS[this.show];
		if (solidComponent !== undefined) {
			const stresses = (this.view?.solids ?? []).flatMap(s => s.stress ? [s.stress[solidComponent]] : []);
			return stresses.length ? { min: this.format('stress', Math.min(...stresses)), max: this.format('stress', Math.max(...stresses)) } : undefined;
		}
		const shellComponent = SHELL_COMPONENTS.indexOf(this.show);
		const values = shellComponent >= 0 ? (this.view?.shells ?? []).flatMap(s => s.forces ? [s.forces[shellComponent]] : []) : [];
		if (!values.length) {
			return undefined;
		}
		const quantity: Quantity = shellComponent >= 3 && shellComponent < 6 ? 'momentPerLength' : 'forcePerLength';
		return { min: this.format(quantity, Math.min(...values)), max: this.format(quantity, Math.max(...values)) };
	}

	// ───────────────────────────── properties ─────────────────────────────

	/**
	 * The result's part of the properties panel: the selected node's or member's values (or its
	 * design checks), and a pushover's capacity curve. Returns false without results.
	 */
	renderProperties(container: HTMLElement): boolean {
		const entry = this.entry;
		const view = this.view;
		if (!entry) {
			return false;
		}
		const selection = this.selection;
		if (this.show === 'utilisation') {
			this.renderDesignProperties(container, selection);
		} else if (selection && view && view.kind !== 'modal') {
			this.renderSelection(container, selection, view);
		} else {
			propertyNote(container, selection
				? localize('femResults.modalSelection', "A mode shape has no values to report: its amplitude is arbitrary.")
				: localize('femResults.selectHint', "Select a node or a member in the view for its values."));
		}
		propertyHeading(container, localize('femResults.resultHeading', "Result"));
		propertyRow(container, localize('femResults.resultName', "Shown"), entry.label);
		if (entry.kind === 'modal') {
			const mode = entry.modes?.[this.mode - 1];
			if (mode) {
				propertyRow(container, localize('femResults.modeNumber', "Mode"), String(mode.number));
				if (mode.period !== null) {
					propertyRow(container, localize('femResults.period', "Period"), localize('femResults.seconds', "{0} s", mode.period.toFixed(3)));
				}
			}
		}
		if (entry.kind === 'modal' || entry.kind === 'spectrum') {
			this.renderSeismic(container, entry.kind === 'spectrum' ? spectrumAxis(entry.label) : undefined, false);
		}
		if ((entry.kind === 'static' || entry.kind === 'combination') && this.show !== 'utilisation' && !isFirstOrderReference(entry.label)) {
			this.renderSecondOrder(container);
		}
		if (entry.kind === 'pushover') {
			propertyHeading(container, localize('femResults.curveHeading', "Capacity Curve"));
			this.renderCurve(container, entry.frames ?? []);
		}
		if (!selection && this.show !== 'utilisation') {
			this.ssi.render(container);
		}
		return true;
	}

	private renderSelection(container: HTMLElement, selection: FemSelection, view: IFemResultView): void {
		const format = this.format;
		if (selection.kind === 'node') {
			propertyHeading(container, localize('femResults.nodeHeading', "Node {0}", selection.id));
			const node = view.nodes.find(n => n[0] === selection.id);
			if (node) {
				propertyRow(container, localize('femResults.ux', "Displacement x"), format('length', node[1]));
				propertyRow(container, localize('femResults.uy', "Displacement y"), format('length', node[2]));
				propertyRow(container, localize('femResults.uz', "Displacement z"), format('length', node[3]));
				propertyRow(container, localize('femResults.uTotal', "Total"), format('length', Math.hypot(node[1], node[2], node[3])));
			}
			const reaction = view.reactions.find(r => r[0] === selection.id);
			if (reaction) {
				propertyHeading(container, localize('femResults.reactionHeading', "Support Reaction"));
				propertyRow(container, 'Fx', format('force', reaction[1]));
				propertyRow(container, 'Fy', format('force', reaction[2]));
				propertyRow(container, 'Fz', format('force', reaction[3]));
			}
			return;
		}
		const element = view.elements.find(e => e.id === selection.id);
		const shell = element ? undefined : view.shells?.find(s => s.id === selection.id);
		propertyHeading(container, element?.name ?? shell?.name ?? localize('femResults.elementHeading', "Element {0}", selection.id));
		if (element?.forces?.length) {
			// Every section force along the member: smallest, largest and at both ends.
			for (const [index, name] of COMPONENTS.entries()) {
				const values = element.forces.map(f => f[index]);
				const quantity: Quantity = index < 3 ? 'force' : 'moment';
				const value = localize('femResults.range', "{0} to {1}", format(quantity, Math.min(...values)), format(quantity, Math.max(...values)));
				propertyRow(container, name, value);
			}
			const component = COMPONENTS.indexOf(this.show);
			if (component >= 0) {
				const quantity: Quantity = component < 3 ? 'force' : 'moment';
				propertyNote(container, localize('femResults.ends', "{0} at end i {1}, at end j {2}.", this.show,
					format(quantity, element.forces[0][component]), format(quantity, element.forces[element.forces.length - 1][component])));
			}
		} else if (shell?.forces?.length) {
			for (const [index, name] of SHELL_COMPONENTS.entries()) {
				const quantity: Quantity = index >= 3 && index < 6 ? 'momentPerLength' : 'forcePerLength';
				propertyRow(container, name, format(quantity, shell.forces[index]));
			}
		} else {
			propertyNote(container, localize('femResults.noForces', "No section forces are recorded for this element."));
		}
	}

	/** The selected member's design checks, the governing first; or why it was not checked. */
	private renderDesignProperties(container: HTMLElement, selection: FemSelection | undefined): void {
		const report = this.design;
		if (!report) {
			propertyNote(container, this.designProblem ?? localize('femResults.designRunning', "Checking the members against the load combinations..."));
			return;
		}
		if (selection?.kind !== 'element') {
			propertyHeading(container, localize('femResults.designHeading', "Design Checks"));
			propertyRow(container, localize('femResults.designCode', "Code"), report.code);
			propertyRow(container, localize('femResults.designPassed', "Pass"), String(report.summary.passed));
			propertyRow(container, localize('femResults.designFailed2', "Fail"), String(report.summary.failed));
			if (report.summary.skipped) {
				propertyRow(container, localize('femResults.designSkipped', "Not checked"), String(report.summary.skipped));
			}
			if (report.summary.maxUtilisation !== null && report.summary.governing) {
				propertyRow(container, localize('femResults.designLargest', "Largest"), localize('femResults.designLargestValue', "{0} in {1}", formatUtilisation(report.summary.maxUtilisation), report.summary.governing));
			}
			const steel = this.required?.summary;
			if (steel) {
				// Members, not the backend's rows (one per zone, strip and layer).
				const short = shortElements(this.required);
				propertyRow(container, localize('femResults.steelShortCount', "Steel short"), short.length
					? localize('femResults.steelShortMembers', "{0} ({1})", short.length, short.length > 6 ? localize('femResults.steelShortMore', "{0}, ...", short.slice(0, 6).join(', ')) : short.join(', '))
					: '0');
				// The backend's summary.tooSmall also holds footings failing bearing or resultant,
				// which bars cannot fix but a larger section is not the only answer to.
				const tooSmall = tooSmallElements(this.required);
				if (tooSmall.length) {
					propertyRow(container, localize('femResults.steelTooSmallCount', "Too small"), tooSmall.join(', '));
				}
				const others = otherFailureElements(this.required);
				if (others.length) {
					propertyRow(container, localize('femResults.steelOtherFailures', "Other checks fail"), others.join(', '));
				}
				if (steel.assumed?.length) {
					propertyRow(container, localize('femResults.steelNoBars', "No bars yet"), steel.assumed.join(', '));
				}
			}
			const secondOrderRequired = secondOrderRequiredMembers(report);
			if (secondOrderRequired.length) {
				propertyRow(container, localize('femResults.secondOrderRequiredCount', "Second-order analysis required"), secondOrderRequired.join(', '));
			}
			this.renderSeismic(container, undefined, true);
			propertyNote(container, localize('femResults.designSelect', "Select a member, or a slab's shell, for its checks."));
			return;
		}
		const element = designElementOf(report, selection.id);
		if (!element) {
			const name = this.view?.elements.find(e => e.id === selection.id)?.name ?? this.view?.shells?.find(s => s.id === selection.id)?.name;
			const id = name?.split('#')[0];
			const skipped = id !== undefined ? report.skipped.find(s => s.id === id) : undefined;
			const steel = requiredSteelOf(this.required, id);
			if (steel.length) {
				// A member without bars yet: the steel it needs, not an error.
				propertyHeading(container, localize('femResults.memberHeading', "{0} ({1} {2})", id, designKindLabel(steel[0].kind), steel[0].type));
				propertyNote(container, localize('femResults.noBarsYet', "No bars entered yet: the steel it requires is shown. Design Reinforcement proposes bars."));
				this.renderSteel(container, steel, false);
				return;
			}
			propertyHeading(container, id ?? localize('femResults.elementHeading', "Element {0}", selection.id));
			propertyNote(container, skipped
				? localize('femResults.notChecked', "Not checked ({0}): {1}.", skipped.type, skipped.reason)
				: localize('femResults.noDesign', "This element is not designed (only reinforced-concrete beams, columns and slabs are)."));
			if (skipped && this.requiredLoading) {
				propertyNote(container, localize('femResults.steelLoading', "Working out the steel required..."));
			}
			return;
		}
		propertyHeading(container, localize('femResults.memberHeading', "{0} ({1} {2})", element.id, designKindLabel(element.kind), element.type));
		const verdict = append(container, $(`.fem-design-verdict.${element.ok ? 'pass' : 'fail'}`));
		append(verdict, $('span', undefined, element.ok ? localize('femResults.passes', "Passes") : localize('femResults.fails', "Fails")));
		append(verdict, $('span.value', undefined, formatUtilisation(element.utilisation)));
		const checks = sortedChecks(element);
		for (const check of checks) {
			const secondOrder = isSecondOrderRequired(check);
			const row = append(container, $(`.fem-design-check${check.ok ? '' : '.fail'}${check.flag ? '.flag' : ''}${secondOrder ? '.second-order' : ''}`));
			const head = append(row, $('.fem-design-check-head'));
			append(head, $('span.name', undefined, check.name));
			append(head, $('span.value', undefined, secondOrder ? localize('femResults.secondOrderRequired', "second-order analysis required") : formatUtilisation(check.utilisation)));
			append(row, $('.fem-design-check-detail', undefined, check.combination
				? localize('femResults.checkUnder', "{0}, {1}", formatCheckValues(check), check.combination)
				: formatCheckValues(check)));
			if (secondOrder && check.note) {
				// The reason: moment magnification is not allowed (or not enough) for it.
				append(row, $('.fem-design-check-detail', undefined, check.note));
			}
		}
		const governing = checks.find(c => !c.flag);
		if (governing?.note) {
			propertyNote(container, localize('femResults.governing', "Governing: {0}.", governing.note));
		}
		// A column's slenderness about each axis: how its moments are magnified for it.
		for (const check of checks.filter(isSlendernessCheck)) {
			const rows = describeSlenderness(check);
			if (rows.length) {
				propertyHeading(container, slendernessHeading(check));
				// Names kept on one line ("k lu / r"): the values wrap instead.
				const section = append(container, $('.fem-slenderness'));
				for (const row of rows) {
					propertyRow(section, row.name, row.value);
				}
			}
		}
		this.renderSteel(container, requiredSteelOf(this.required, element.id), true);
		if (this.requiredLoading) {
			propertyNote(container, localize('femResults.steelLoading', "Working out the steel required..."));
		}
	}

	/**
	 * The steel a member requires next to the steel provided, per quantity (its governing zone,
	 * strip or layer), with the combination that governs it. `heading`: under a heading of its
	 * own, below the member's checks.
	 */
	private renderSteel(container: HTMLElement, rows: readonly IFemSteelRequirement[], heading: boolean): void {
		if (!rows.length) {
			return;
		}
		if (heading) {
			propertyHeading(container, localize('femResults.steelHeading', "Required Steel"));
		}
		for (const steel of rows) {
			if (isOtherFailure(steel)) {
				// A check bars cannot fix (a footing's bearing): the failure, not a quantity of steel.
				const row = append(container, $('.fem-design-check.fem-design-steel.fail'));
				const head = append(row, $('.fem-design-check-head'));
				append(head, $('span.name', undefined, localize('femResults.otherCheck', "Other check")));
				append(head, $('span.value', undefined, localize('femResults.otherCheckFails', "fails")));
				append(row, $('.fem-design-check-steel', undefined, describeSteel(steel)));
				append(row, $('.fem-design-check-detail', undefined, localize('femResults.otherCheckHint', "Bars do not fix this: change the size or the depth.")));
				continue;
			}
			const verdict = steel.tooSmall ? 'fail' : steel.ok === null ? 'required-only' : steel.ok ? 'pass' : 'fail';
			const row = append(container, $(`.fem-design-check.fem-design-steel.${verdict}`));
			const head = append(row, $('.fem-design-check-head'));
			append(head, $('span.name', undefined, steel.quantity));
			append(head, $('span.value', undefined, steel.tooSmall
				? localize('femResults.steelTooSmall', "section too small")
				: steel.ok === null ? localize('femResults.steelRequired', "required")
					: steel.ok ? localize('femResults.steelEnough', "enough") : localize('femResults.steelShort', "short")));
			append(row, $('.fem-design-check-steel', undefined, describeSteel(steel)));
			const ratio = describeSteelRatio(steel);
			if (ratio) {
				append(row, $('.fem-design-check-steel', undefined, ratio));
			}
			const where = [steel.location, ...(steel.combination ? [steel.combination] : [])];
			append(row, $('.fem-design-check-detail', undefined, where.join(', ')));
			if (steel.notes && (steel.tooSmall || steel.ok === false)) {
				append(row, $('.fem-design-check-detail', undefined, steel.notes));
			}
		}
	}

	/**
	 * The response spectrum scaled for design: the factor of each direction (or of `axis` only),
	 * the orthogonal rule and accidental torsion, the drift; with `combinations`, the design
	 * combinations with the scaled spectrum as E. Nothing when the project does not design from it
	 * (the backend returns null). When it does but the run has no spectrum (`available: false`),
	 * the heading with the backend's notes only, saying why (e.g. enable the response spectrum).
	 */
	private renderSeismic(container: HTMLElement, axis: FemAxis | undefined, combinations: boolean): void {
		for (const item of seismicSection(this.seismic, axis, combinations)) {
			switch (item.kind) {
				case 'heading': propertyHeading(container, item.text); break;
				case 'note': propertyNote(container, item.text); break;
				case 'row': propertyRow(container, item.name, item.value); break;
				case 'combination': {
					const row = append(container, $('.fem-seismic-combination'));
					append(row, $('.sa-props-row', undefined, item.name));
					if (item.detail) {
						append(row, $('.fem-design-check-detail', undefined, item.detail));
					}
					break;
				}
			}
		}
	}

	/** The drift amplification per storey of a second-order (P-Delta) run; nothing for a first-order one. */
	private renderSecondOrder(container: HTMLElement): void {
		const secondOrder = this.secondOrder;
		const note = describeSecondOrder(secondOrder);
		if (!secondOrder || !note) {
			return;
		}
		propertyHeading(container, localize('femResults.secondOrderHeading', "Second Order"));
		propertyNote(container, note);
		for (const row of storeyAmplificationRows(secondOrder)) {
			propertyRow(container, row.name, row.value);
		}
		for (const text of secondOrder?.notes ?? []) {
			propertyNote(container, text);
		}
	}

	/** A pushover's capacity curve (base shear against roof displacement), marking the step shown. */
	private renderCurve(container: HTMLElement, frames: NonNullable<IFemResultEntry['frames']>): void {
		const points = frames.map(f => [Math.abs(f.displacement ?? 0), Math.abs(f.shear ?? 0)]);
		const dMax = Math.max(...points.map(p => p[0])) || 1;
		const vMax = Math.max(...points.map(p => p[1])) || 1;
		const xy = (p: readonly number[]) => `${(p[0] / dMax * (CURVE_WIDTH - 4) + 2).toFixed(1)},${(CURVE_HEIGHT - 2 - p[1] / vMax * (CURVE_HEIGHT - 4)).toFixed(1)}`;
		const svg = append(container, $('.fem-results-curve', { title: localize('femResults.curveTitle', "Capacity curve: base shear against roof displacement") }));
		const ns = 'http://www.w3.org/2000/svg';
		const document = container.ownerDocument;
		const root = document.createElementNS(ns, 'svg');
		root.setAttribute('width', String(CURVE_WIDTH));
		root.setAttribute('height', String(CURVE_HEIGHT));
		const line = document.createElementNS(ns, 'polyline');
		line.setAttribute('points', points.map(xy).join(' '));
		line.setAttribute('class', 'curve');
		root.appendChild(line);
		const at = points[this.mode - 1];
		if (at) {
			const [cx, cy] = xy(at).split(',');
			const marker = document.createElementNS(ns, 'circle');
			marker.setAttribute('cx', cx);
			marker.setAttribute('cy', cy);
			marker.setAttribute('r', '3');
			marker.setAttribute('class', 'marker');
			root.appendChild(marker);
		}
		svg.appendChild(root);
		propertyRow(container, localize('femResults.peakShearName', "Largest base shear"), this.format('force', vMax));
		propertyRow(container, localize('femResults.peakRoofName', "At roof"), this.format('length', points.find(p => p[1] === vMax)?.[0] ?? 0));
	}
}
