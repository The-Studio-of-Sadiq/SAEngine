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
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { IFemResultEntry, IFemResultList, IFemResultView } from '../../../../platform/saengine/common/femSolver.js';
import { defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameIconButton, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { appendPlannedFeatureChip } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { describeDesignCounts, describeEngineError, describeDesignSummary, describeSlenderness, describeSteel, describeSteelRatio, designElementOf, designInputs, designKindLabel, designUtilisation, formatCheckValues, formatUtilisation, IFemDesignReport, IFemDesignRequired, IFemSteelRequirement, isOtherFailure, isSecondOrderRequired, isSlendernessCheck, otherFailureElements, PLANNED_STM_GENERAL, requiredSteelOf, resultsFolder, runDesign, runDesignRequired, secondOrderRequiredMembers, shortElements, slabRebar, slendernessHeading, sortedChecks, tooSmallElements, writeDesignSummary } from './femDesign.js';
import { describeScaleOnResult, describeSecondOrder, FemAxis, IFemSecondOrder, isFirstOrderReference, IFemSeismicDesign, runSecondOrder, runSeismicDesign, seismicSection, spectrumAxis, storeyAmplificationRows } from './femSeismicDesign.js';
import { FemSsiPanel } from './femSsi.js';
import { describeJointsSummary, describeJointVerdict, detailingSection, FemDetailingItem, generalChecks, IFemDetailingModel, IFemJoint, jointAtNode, jointColouring, jointHeading, jointItems, jointNodeUtilisation, jointOk, jointsOf, jointsOfMember } from './femSeismicDetailing.js';
import { describeSteelSummary, memberConnectionChecks, steelSection } from './femSteelDesign.js';
import { appendPlannedChips, FemPlanned, STEEL_CONNECTIONS_PLANNED, STEEL_SHEDS_PLANNED, STEEL_STABILITY_PLANNED } from './femPlannedFeatures.js';
import { timberSection } from './femTimberDesign.js';
import { checkItems, describeStaircaseVerdict, describeWallsSummary, formatPierForce, IFemPierDiagram, isStaircase, isWall, ownChecks, pierDiagram, staircasesOf, staircaseSection, wallSection } from './femWallsStairs.js';

export { resultsFolder } from './femDesign.js';

/** Desktop commands reading a run's results with the Python backend (see `saengine.fem.resultList`). */
export const FEM_RESULT_LIST_COMMAND = 'saengine.fem.resultList';
const LIST_COMMAND = FEM_RESULT_LIST_COMMAND;
const VIEW_COMMAND = 'saengine.fem.resultView';

/**
 * The frames a result steps through: a time history's moments, a pushover's steps, a staged
 * (construction sequence) static case's stages; none for the others.
 */
function framesOf(entry: IFemResultEntry): NonNullable<IFemResultEntry['frames']> {
	return entry.kind === 'history' || entry.kind === 'pushover' || entry.kind === 'static' ? entry.frames ?? [] : [];
}

/**
 * The result a new run opens at: the first load combination of the project settings (what the
 * members are designed for), else the first static case, else the first result.
 */
export function defaultResult(results: readonly IFemResultEntry[]): IFemResultEntry | undefined {
	// A lateral case first: the sway is what the engineer looks at first (gravity alone shows little).
	const lateral = results.find(r => r.kind === 'static' && /^EX\b/.test(r.label));
	return lateral ?? results.find(r => r.kind === 'combination') ?? results.find(r => r.kind === 'static') ?? results[0];
}

/** Where the result picker files a result: the load cases, the combinations, the dynamic results. */
export function resultGroupLabel(entry: IFemResultEntry): string {
	return entry.kind === 'static' ? localize('femResults.groupCases', "Load cases")
		: entry.kind === 'combination' ? localize('femResults.groupCombinations', "Load combinations")
			: localize('femResults.groupDynamic', "Modal, spectrum and time history");
}

/** The picker's options: a heading (disabled) before each group of results; `rows[k]`: the result of option k, -1 for a heading. */
export function resultOptions(results: readonly IFemResultEntry[]): { readonly options: ISelectOptionItem[]; readonly rows: number[] } {
	const options: ISelectOptionItem[] = [];
	const rows: number[] = [];
	let group: string | undefined;
	results.forEach((entry, index) => {
		const label = resultGroupLabel(entry);
		if (label !== group) {
			group = label;
			options.push({ text: `── ${label} ──`, isDisabled: true });
			rows.push(-1);
		}
		options.push({ text: entry.label });
		rows.push(index);
	});
	return { options, rows };
}

/** What the results bar keeps of a model across restarts (workspace storage): the result and what of it was shown. */
const VIEW_STATE_KEY = 'saengine.fem.results.viewState';

/** `joints`: the beam-column joints' checks, drawn as utilisation of the members framing in. */
/** A slab layer's rebar contour (the design's steel per shell), drawn as shell values. */
type RebarShow = 'rebarBottomX' | 'rebarBottomY' | 'rebarTopX' | 'rebarTopY';
type Show = FemResultQuantity | 'none' | 'joints' | RebarShow;
/** The rebar contours in the order of `SLAB_REBAR_LAYERS`. */
const REBAR_SHOWS: readonly RebarShow[] = ['rebarBottomX', 'rebarBottomY', 'rebarTopX', 'rebarTopY'];

function isRebarShow(show: Show): show is RebarShow {
	return (REBAR_SHOWS as readonly Show[]).includes(show);
}

/** Whether `show` draws design checks (members' utilisation, or the joints'). */
function isDesignShow(show: Show): boolean {
	return show === 'utilisation' || show === 'joints' || isRebarShow(show);
}

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
	// Named by the member's local axes, as the member details and the tables name them.
	{ show: 'Vy', label: localize('femResults.shearY', "Shear Force V2") },
	{ show: 'Vz', label: localize('femResults.shearZ', "Shear Force V3") },
	{ show: 'T', label: localize('femResults.torsion', "Torsion T") },
	{ show: 'My', label: localize('femResults.momentY', "Moment M2") },
	{ show: 'Mz', label: localize('femResults.momentZ', "Moment M3") },
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
/**
 * The beam-column joints of the moment frames (joint shear, strong column / weak beam: BNBC 2020
 * Part 6 Sec 8.3.5.2, 8.3.7), coloured by their governing check; a joint's node selects it.
 */
const JOINTS_OPTION: IShowOption = { show: 'joints', label: localize('femResults.joints', "Joint Checks") };
/**
 * The steel each slab layer needs, shell by shell, from the design's Wood-Armer moments
 * enveloped over the combinations (rebar intensity contours), offered when the model has shells.
 */
const REBAR_OPTIONS: readonly IShowOption[] = [
	{ show: 'rebarBottomX', label: localize('femResults.rebarBottomX', "Slab Steel Required, Bottom X") },
	{ show: 'rebarBottomY', label: localize('femResults.rebarBottomY', "Slab Steel Required, Bottom Y") },
	{ show: 'rebarTopX', label: localize('femResults.rebarTopX', "Slab Steel Required, Top X") },
	{ show: 'rebarTopY', label: localize('femResults.rebarTopY', "Slab Steel Required, Top Y") },
];
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
/** The section forces as the member details name them (local axes 2 and 3). */
const COMPONENT_NAMES: readonly string[] = ['N', 'V2', 'V3', 'T', 'M2', 'M3'];

/** The scale slider: the multiplier is 2 to the slider's value, ×1/8 to ×32. */
const SCALE_MIN_EXPONENT = -3;
const SCALE_MAX_EXPONENT = 5;
const SCALE_STEP = 0.25;

/** "×1.4": the scale multiplier as the slider shows it. */
export function scaleText(scale: number): string {
	return `×${scale >= 10 ? scale.toFixed(0) : scale >= 1 ? Number(scale.toFixed(1)).toString() : Number(scale.toPrecision(2)).toString()}`;
}

/** The share of the model's size the largest deflection is drawn at, at scale ×1 (the 3D view's). */
const DEFORMED_SHARE = 0.06;

/**
 * How many times the 3D view magnifies the deflections: it draws the largest one (of the frame
 * members' stations and the shells' and solids' nodes) at {@link DEFORMED_SHARE} of the model's
 * diagonal, times the scale slider. Undefined without a deflection.
 */
export function deflectionMagnification(model: IFemDetailingModel | undefined, view: IFemResultView, scale: number): number | undefined {
	if (!model?.nodes.length) {
		return undefined;
	}
	const lo = [Infinity, Infinity, Infinity];
	const hi = [-Infinity, -Infinity, -Infinity];
	for (const node of model.nodes) {
		for (let a = 0; a < 3; a++) {
			lo[a] = Math.min(lo[a], node.coords[a] ?? 0);
			hi[a] = Math.max(hi[a], node.coords[a] ?? 0);
		}
	}
	const size = Math.max(Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]), 1);
	let peak = 0;
	for (const element of view.elements) {
		for (const d of element.displacements) {
			peak = Math.max(peak, Math.hypot(d[0], d[1], d[2]));
		}
	}
	const moved = new Map(view.nodes.map(n => [n[0], n]));
	for (const surface of [...(view.shells ?? []), ...(view.solids ?? [])]) {
		for (const id of surface.nodes) {
			const d = moved.get(id);
			peak = Math.max(peak, d ? Math.hypot(d[1], d[2], d[3]) : 0);
		}
	}
	return peak > 0 ? scale * DEFORMED_SHARE * size / peak : undefined;
}

/** A mode with its period and mass participation, as the mode picker and the caption say it. */
export function modeText(mode: { readonly number: number; readonly period: number | null; readonly ux?: number; readonly uy?: number }): string {
	if (mode.period === null) {
		return localize('femResults.modeOnly', "Mode {0}", mode.number);
	}
	return mode.ux === undefined || mode.uy === undefined
		? localize('femResults.modePeriodCaption', "Mode {0}: T = {1} s", mode.number, mode.period.toFixed(3))
		: localize('femResults.modeShareCaption', "Mode {0}: T = {1} s, UX {2} %, UY {3} %", mode.number, mode.period.toFixed(3), (100 * mode.ux).toFixed(1), (100 * mode.uy).toFixed(1));
}

type Quantity = FemValueQuantity;

/**
 * Values in the units the user reads: SAEngine models are in SI (m, N), shown as mm, kN and
 * kN·m. Models in other units show their own values.
 */
export function resultFormatter(units: string | undefined): (quantity: Quantity, value: number) => string {
	// Steel per width comes from the design in mm²/m, whatever the model's units.
	const steel = (value: number) => localize('femResults.mm2PerM', "{0} mm²/m", Math.round(value).toString());
	if (units?.startsWith('SI')) {
		// "-0.0" reads as a value: what rounds to zero is shown as 0.
		const fixed = (v: number, digits: number) => {
			const text = v.toFixed(digits);
			return /^-0(\.0+)?$/.test(text) ? text.slice(1) : text;
		};
		return (quantity, value) => {
			switch (quantity) {
				case 'length': return localize('femResults.mm', "{0} mm", fixed(value * 1000, 2));
				case 'force': return localize('femResults.kN', "{0} kN", fixed(value / 1000, 1));
				case 'moment': return localize('femResults.kNm', "{0} kN·m", fixed(value / 1000, 1));
				case 'forcePerLength': return localize('femResults.kNperM', "{0} kN/m", fixed(value / 1000, 1));
				case 'momentPerLength': return localize('femResults.kNmPerM', "{0} kN·m/m", fixed(value / 1000, 2));
				case 'stress': return localize('femResults.MPa', "{0} MPa", fixed(value / 1e6, 2));
				case 'areaPerLength': return steel(value);
			}
		};
	}
	return (quantity, value) => quantity === 'areaPerLength' ? steel(value) : Number(value.toPrecision(4)).toString();
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
/** `(model?: URI)`: opens the Analysis Charts of the last run. */
export const FEM_SHOW_CHARTS_COMMAND = 'saengine.fem.showCharts';
/** `(model: URI, member: string)`: opens a member's details (forces along it, P-M, steel). */
export const FEM_SHOW_MEMBER_COMMAND = 'saengine.fem.showMember';

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
	return describeEngineError((line ?? text).trim());
}

/** "13 members pass, 3 fail · largest utilisation 2.62 in F1 · 1 not checked · BNBC 2020": the status line's design summary. */
function designStatus(report: IFemDesignReport): string {
	const { skipped, maxUtilisation, governing } = report.summary;
	if (!report.elements.length) {
		return describeDesignSummary(report);
	}
	return [
		describeDesignCounts(report.summary),
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
	private readonly scaleSlider: HTMLInputElement;
	private readonly scaleLabel: HTMLElement;
	private readonly labelsButton: IEditorFrameIconButton;
	/** Force diagrams: every member's largest and least value labelled. */
	private memberLabels = false;
	private playing = false;
	private playToken = 0;
	private readonly watch = this._register(new DisposableStore());
	private readonly diaphragmChips = this._register(new DisposableStore());
	private readonly resultsWatch = this._register(new MutableDisposable());
	/** The "Planned" chips of the properties shown (see `FemPlanned`). */
	private readonly plannedChips = this._register(new MutableDisposable<DisposableStore>());
	private readonly reload = this._register(new RunOnceScheduler(() => void this.load(), 400));
	/** The design checks' own inputs (reinforcement, materials, combinations) changed. */
	// An edited input (the project settings: response spectrum design, orthogonal rule, torsion)
	// changes the seismic design as well as the checks: read both again, the seismic design first.
	private readonly redesign = this._register(new RunOnceScheduler(() => {
		void this.loadExtras(true);
		this.refreshDesign();
	}, 400));

	private resource: URI | undefined;
	/** The analysis model shown (its nodes and elements place the joints). */
	private model: IFemDetailingModel | undefined;
	private format = resultFormatter(undefined);
	private list: IFemResultList = { results: [], stale: false };
	private key: string | undefined;
	/** The result picker's option k shows result `resultRows[k]` (-1: a group's heading). */
	private resultRows: number[] = [];
	/** What the engineer chose to show: shown again on every result that has it (a mode shape has no forces). */
	private wantedShow: Show | undefined;
	private mode = 1;
	private show: Show = 'deformed';
	/** What was shown before the design utilisation was toggled on. */
	private showBeforeDesign: Show = 'deformed';
	private scale = 1;
	private animate = true;
	private view: IFemResultView | undefined;
	private selection: FemSelection | undefined;
	private visible: ReadonlySet<number> | undefined;
	private problem: string | undefined;
	private readonly views = new Map<string, IFemResultView>();
	private request = 0;
	/** The result list is being read and none is known yet: the status says so, not "not analysed". */
	private listing = false;
	/** The result being read from the backend while the view still shows the last one. */
	private pending: string | undefined;
	/** Hidden with its editor: the watchers are off and the results read so far are kept. */
	private suspended = false;
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
		@IStorageService private readonly storageService: IStorageService,
	) {
		super();
		this.ssi = this._register(new FemSsiPanel(() => this.host.changed(), commandService, fileService, model => dirname(dirname(model))));
		const group = (slot: HTMLElement, className: string) => append(slot, $(`.fem-results-group.${className}`));

		this.resultGroup = group(frame.titleSlot, 'result');
		this.resultPicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.resultAria', "Analysis result shown") }));
		this.resultPicker.render(append(this.resultGroup, $('.fem-results-select.result')));
		this._register(this.resultPicker.onDidSelect(({ index }) => {
			const row = this.resultRows[index] ?? -1;
			if (row < 0) {
				this.render(); // a heading: the picker shows the result it showed
				return;
			}
			this.stopPlaying();
			this.key = this.list.results[row]?.key;
			this.saveViewState();
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
		this._register(frame.createIconButton(this.modeContainer, Codicon.chevronLeft, localize('femResults.previousMode', "Previous Mode"), () => this.stepMode(-1)));
		this.modePicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.modeAria', "Mode shown") }));
		this.modePicker.render(append(this.modeContainer, $('.fem-results-select.mode')));
		this._register(this.modePicker.onDidSelect(({ index }) => {
			this.mode = index + 1;
			void this.showResult();
		}));
		this._register(frame.createIconButton(this.modeContainer, Codicon.chevronRight, localize('femResults.nextMode', "Next Mode"), () => this.stepMode(1)));
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
		append(this.scaleContainer, $('span.sa-frame-label', undefined, localize('femResults.scale', "Scale")));
		this.scaleSlider = append(this.scaleContainer, $<HTMLInputElement>('input.fem-results-scale-slider', {
			type: 'range', min: String(SCALE_MIN_EXPONENT), max: String(SCALE_MAX_EXPONENT), step: String(SCALE_STEP), value: '0',
			'aria-label': localize('femResults.scaleAria', "How large the deflections and diagrams are drawn"),
		}));
		this._register(addDisposableListener(this.scaleSlider, EventType.INPUT, () => {
			this.scale = Math.pow(2, Number(this.scaleSlider.value));
			this.render();
		}));
		this._register(addDisposableListener(this.scaleSlider, EventType.DBLCLICK, () => {
			this.scale = 1; // back to the automatic size
			this.render();
		}));
		this.scaleLabel = append(this.scaleContainer, $('span.fem-results-scale'));
		this.labelsButton = this._register(frame.createIconButton(this.scaleContainer, Codicon.symbolNumeric, localize('femResults.labelMembers', "Label Every Member's Largest and Least Value"), () => {
			this.memberLabels = !this.memberLabels;
			this.render();
		}));

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

	/** The design checks of the run, once Design Utilisation has run them. */
	get designReport(): IFemDesignReport | undefined {
		return this.design;
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
		this.saveViewState();
		this.mode = this.firstFrame();
		void this.showResult();
	}

	/** Follows the results of `resource` when it is an analysis model (`.osmodel`). */
	setResource(resource: URI | undefined, units: string | undefined): void {
		this.format = resultFormatter(units);
		if (resource?.toString() === this.resource?.toString()) {
			if (resource && this.suspended) {
				// Shown again: what was read is still shown; a run made meanwhile is read again.
				this.follow(resource);
				void this.load();
			}
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
		this.listing = false;
		this.pending = undefined;
		this.key = undefined;
		this.views.clear();
		this.view = undefined;
		this.clearDesign();
		this.clearExtras();
		if (resource) {
			this.follow(resource);
			void this.load();
		} else {
			this.render();
		}
	}

	/** Hides with the editor: stops watching the results but keeps them for when it is shown again. */
	suspend(): void {
		this.stopPlaying();
		this.watch.clear();
		this.resultsWatch.clear();
		this.suspended = true;
	}

	/** Watches the results of `resource` and the inputs of its design checks. */
	private follow(resource: URI): void {
		this.suspended = false;
		this.watch.clear();
		this.resultsWatch.clear();
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
	}

	/** The analysis model of the resource, as the editor read it: where the joints are. */
	setModel(model: IFemDetailingModel | undefined): void {
		this.model = model;
		if (this.show === 'joints' || this.show === 'deformed') {
			this.render(); // the joints' places, the deflections' magnification
		}
	}

	setSelection(selection: FemSelection | undefined): void {
		this.selection = selection;
		this.host.changed();
	}

	/**
	 * The elements the 3D view draws (a plan, an elevation, a storey; undefined: all): the
	 * legend and the status give the extremes of these.
	 */
	setVisible(elements: ReadonlySet<number> | undefined): void {
		this.visible = elements;
		this.render();
	}

	private shownElements(view: IFemResultView): IFemResultView['elements'] {
		const visible = this.visible;
		return visible ? view.elements.filter(e => visible.has(e.id)) : view.elements;
	}

	private setShow(show: Show): void {
		if (isDesignShow(show) && !isDesignShow(this.show)) {
			this.showBeforeDesign = this.show;
		}
		this.show = show;
		this.wantedShow = show;
		this.saveViewState();
		if (isDesignShow(this.show)) {
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
		if (!this.list.results.length) {
			this.listing = true;
			this.host.changed();
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
		const wasListing = this.listing;
		this.listing = false;
		if (signature === this.signature) {
			if (wasListing) {
				this.host.changed();
			}
			return;
		}
		this.signature = signature;
		this.list = list;
		this._version++;
		this.views.clear();
		this.clearDesign();
		void this.loadExtras();
		if (isDesignShow(this.show)) {
			void this.loadDesign();
		}
		if (!list.results.some(r => r.key === this.key)) {
			this.stopPlaying();
			// The result shown last time (by its label: a new run numbers its cases again), else a lateral case.
			const saved = this.key === undefined ? this.readViewState() : undefined;
			if (saved?.show && !this.wantedShow) {
				this.wantedShow = saved.show;
			}
			this.key = (saved?.result !== undefined ? list.results.find(r => r.label === saved.result) : undefined)?.key ?? defaultResult(list.results)?.key;
			this.mode = this.firstFrame();
		}
		await this.showResult();
	}

	private readViewState(): { readonly result?: string; readonly show?: Show } | undefined {
		const resource = this.resource;
		const raw = resource ? this.storageService.get(VIEW_STATE_KEY, StorageScope.WORKSPACE) : undefined;
		try {
			const all = raw ? JSON.parse(raw) : undefined;
			const state = all && typeof all === 'object' ? all[resource!.toString()] : undefined;
			return state && typeof state === 'object' ? { result: typeof state.result === 'string' ? state.result : undefined, show: typeof state.show === 'string' ? state.show as Show : undefined } : undefined;
		} catch {
			return undefined;
		}
	}

	private saveViewState(): void {
		const resource = this.resource;
		if (!resource) {
			return;
		}
		let all: { [model: string]: unknown } = {};
		try {
			all = JSON.parse(this.storageService.get(VIEW_STATE_KEY, StorageScope.WORKSPACE) ?? '{}') ?? {};
		} catch {
			all = {};
		}
		all[resource.toString()] = { result: this.entry?.label ?? this.list.results.find(r => r.key === this.key)?.label, show: this.wantedShow ?? this.show };
		this.storageService.store(VIEW_STATE_KEY, JSON.stringify(all), StorageScope.WORKSPACE, StorageTarget.MACHINE);
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
		const shells = this.view?.shells?.length ? SHELL_OPTIONS : [];
		const rebar = this.view?.shells?.length ? REBAR_OPTIONS : [];
		return [...STATIC_OPTIONS, ...shells, ...solids, DESIGN_OPTION, JOINTS_OPTION, ...rebar];
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
		if (isDesignShow(this.show)) {
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
		const request = ++this.request;
		this.pending = undefined;
		let view = this.views.get(id);
		if (!view) {
			if (!this.playing) {
				// A busy backend can take a while: say so, or the last result looks like the new one.
				this.pending = entry.label;
				this.renderLegend(); // not the last result's values under the new one's name
				this.host.changed();
			}
			try {
				view = await this.commandService.executeCommand<IFemResultView>(VIEW_COMMAND, resource, entry.key, framed ? this.mode : undefined);
			} catch (error) {
				if (request === this.request) {
					this.pending = undefined;
				}
				this.view = undefined;
				this.problem = localize('femResults.failed', "The result could not be read: {0}", errorSummary(error));
				this.render();
				return;
			}
			if (request !== this.request || resource !== this.resource) {
				return;
			}
			this.pending = undefined;
			if (view) {
				this.views.set(id, view);
			}
		}
		this.view = view;
		const options = this.showOptions();
		if (this.wantedShow && options.some(o => o.show === this.wantedShow)) {
			this.show = this.wantedShow;
		} else if (!options.some(o => o.show === this.show)) {
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

	/** Shows the previous or next mode of a modal result (wrapping around). */
	private stepMode(direction: number): void {
		const count = this.entry?.modes?.length ?? 0;
		if (!count) {
			return;
		}
		this.mode = ((this.mode - 1 + direction + count) % count) + 1;
		void this.showResult();
	}

	private render(): void {
		const entry = this.entry;
		this.resultGroup.classList.toggle('hidden', !entry);
		this.showGroup.classList.toggle('hidden', !entry);
		const modal = entry?.kind === 'modal';
		this.modeContainer.classList.toggle('hidden', !modal);
		const frames = entry ? framesOf(entry) : [];
		this.timeContainer.classList.toggle('hidden', !frames.length);
		const scalable = !!entry && this.show !== 'none' && !isDesignShow(this.show) && SOLID_COMPONENTS[this.show] === undefined && !SHELL_COMPONENTS.includes(this.show);
		this.scaleContainer.classList.toggle('hidden', !scalable);
		if (entry) {
			const grouped = resultOptions(this.list.results);
			this.resultRows = grouped.rows;
			this.resultPicker.setOptions(grouped.options, Math.max(0, grouped.rows.indexOf(this.list.results.indexOf(entry))));
			if (modal) {
				const modes = entry.modes ?? [];
				this.modePicker.setOptions(modes.map<ISelectOptionItem>(m => ({
					text: m.period === null ? String(m.number) : m.ux === undefined || m.uy === undefined
						? localize('femResults.modeOption', "{0} (T = {1} s)", m.number, m.period.toFixed(3))
						// Short enough for a laptop's toolbar: the larger share; the status line has both.
						: localize('femResults.modeOptionShare', "{0} · {1} s · {2} {3} %", m.number, m.period.toFixed(3), m.ux >= m.uy ? 'UX' : 'UY', (100 * Math.max(m.ux, m.uy)).toFixed(0)),
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
			// The slider is relative to the automatic size: say how large the deflections really are drawn.
			const magnification = this.show === 'deformed' && this.view && entry.kind !== 'modal' ? deflectionMagnification(this.model, this.view, this.scale) : undefined;
			const times = magnification === undefined ? undefined : magnification >= 10 ? magnification.toFixed(0) : magnification.toFixed(1);
			this.scaleLabel.textContent = times !== undefined
				? localize('femResults.scaleMagnified', "{0} · drawn ×{1}", scaleText(this.scale), times)
				: scaleText(this.scale);
			this.scaleLabel.title = times !== undefined
				? localize('femResults.scaleMagnifiedTitle', "The deflections are drawn {0} times their real size (the slider's {1} of the automatic size).", times, scaleText(this.scale))
				: '';
			this.scaleSlider.value = String(Math.log2(this.scale));
			const diagram = COMPONENTS.includes(this.show);
			this.labelsButton.element.classList.toggle('hidden', !diagram);
			this.labelsButton.element.classList.toggle('checked', diagram && this.memberLabels);
			this.labelsButton.element.setAttribute('aria-pressed', String(diagram && this.memberLabels));
		}
		const view = this.view;
		const show = this.show;
		this.host.setDisplay(
			view && show !== 'none' ? view : undefined,
			view && show !== 'none' ? {
				// The joints are drawn as the utilisation of the members framing into them; a slab
				// layer's rebar contour as one value per shell.
				show: show === 'joints' ? 'utilisation' : isRebarShow(show) ? 'shellValues' : show,
				scale: this.scale,
				animate: this.animate,
				memberLabels: this.memberLabels,
				format: this.format,
				utilisation: !this.design ? undefined
					: show === 'utilisation' ? designUtilisation(this.design)
						: show === 'joints' ? jointColouring(this.design, this.model) : undefined,
				// The joints as glyphs at their nodes, over the members' or the joints' colours.
				nodeUtilisation: this.design && isDesignShow(show) && !isRebarShow(show) ? jointNodeUtilisation(this.design, this.model) : undefined,
				shellValues: this.design && isRebarShow(show) ? slabRebar(this.design, REBAR_SHOWS.indexOf(show)) : undefined,
				shellValueQuantity: 'areaPerLength',
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
			return this.listing ? { busy: true, text: localize('femResults.listing', "Reading the analysis results...") } : undefined;
		}
		if (this.pending) {
			return { busy: true, text: localize('femResults.reading', "Reading {0}...", this.pending) };
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
		if (isDesignShow(this.show)) {
			if (this.designProblem) {
				return { severity: 'error', text: this.designProblem };
			}
			if (!this.design) {
				return { busy: true, text: localize('femResults.designRunning', "Checking the members against the load combinations...") };
			}
			if (isRebarShow(this.show)) {
				return { text: localize('femResults.rebarStatus', "Steel each slab layer needs for strength (Wood-Armer moments, all combinations), shell by shell; minimum steel not included. X layers run along the slab's local x.") };
			}
			if (this.show === 'joints') {
				const failing = jointsOf(this.design).some(j => !jointOk(j));
				return { ...(failing ? { severity: 'warning' as const } : {}), text: describeJointsSummary(this.design) };
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
				? localize('femResults.modePeriodStatus', "{0}; frequency {1} Hz. The shape's size is arbitrary.", modeText(mode), (1 / mode.period).toFixed(2))
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
				if (!largest) {
					return undefined;
				}
				const atNode = Math.hypot(largest[1], largest[2], largest[3]);
				// The view labels the largest along the frame members: the status names the same
				// value and member (one formatter, so label and status agree), and says when a
				// slab's or wall's node moves more.
				let frame: { value: number; name: string; d: readonly number[] } | undefined;
				for (const element of this.shownElements(view)) {
					for (const d of element.displacements) {
						const value = Math.hypot(d[0], d[1], d[2]);
						if (!frame || value > frame.value) {
							frame = { value, name: element.name.split('#')[0], d };
						}
					}
				}
				if (!frame) {
					return localize('femResults.largestDisplacement', "Largest displacement {0} at node {1} (x {2}, y {3}, z {4}).",
						format('length', atNode), largest[0], format('length', largest[1]), format('length', largest[2]), format('length', largest[3]));
				}
				const text = localize('femResults.largestMemberDisplacement', "Largest displacement {0} in {1} (x {2}, y {3}, z {4}).",
					format('length', frame.value), frame.name, format('length', frame.d[0]), format('length', frame.d[1]), format('length', frame.d[2]));
				return atNode > 1.01 * frame.value
					? `${text} ${localize('femResults.largestNodeDisplacement', "A wall or slab node moves more: {0}.", format('length', atNode))}`
					: text;
			}
			case 'reactions': {
				const total = [1, 2, 3].map(i => view.reactions.reduce((sum, r) => sum + r[i], 0));
				return localize('femResults.totalReaction', "Total reaction: Fx {0}, Fy {1}, Fz {2}.", format('force', total[0]), format('force', total[1]), format('force', total[2]));
			}
			case 'none':
				return localize('femResults.modelShown', "{0}: choose what to show of it.", view.label);
			default: {
				let largest: { value: number; name: string } | undefined;
				for (const element of this.shownElements(view)) {
					for (const forces of element.forces ?? []) {
						if (!largest || Math.abs(forces[component]) > Math.abs(largest.value)) {
							largest = { value: forces[component], name: element.name.split('#')[0] };
						}
					}
				}
				const name = this.showOptions().find(o => o.show === this.show)?.label ?? this.show;
				return largest && localize('femResults.largestForce', "Largest {0}: {1} in {2}. Select an element for its values.", name, format(quantity, largest.value), largest.name);
			}
		}
	}

	// ───────────────────────────── legend ─────────────────────────────

	/** The colour scale over the 3D view: utilisation bands, or a contour's range. */
	private renderLegend(): void {
		clearNode(this.legend);
		let shown = false;
		if (this.pending) {
			// The result asked for is being read: its values are not known yet.
		} else if (this.entry && isDesignShow(this.show) && !isRebarShow(this.show) && this.design && (this.show === 'utilisation' || jointsOf(this.design).length)) {
			// The colours of the 3D view's utilisation bands.
			append(this.legend, $('.fem-legend-title', undefined, this.show === 'joints'
				? localize('femResults.jointUtilisation', "Joint Utilisation")
				: localize('femResults.utilisation', "Utilisation")));
			for (const [band, label] of [
				['pass', localize('femResults.designPass', "below 0.9")],
				['warn', localize('femResults.designWarn', "0.9 to 1.0")],
				['fail', localize('femResults.designFail', "above 1.0")],
			]) {
				const row = append(this.legend, $('.fem-legend-row'));
				append(row, $(`span.fem-design-swatch.${band}`));
				append(row, $('span', undefined, label));
			}
			if (jointsOf(this.design).length) {
				append(this.legend, $('.fem-legend-row', undefined, localize('femResults.jointGlyphs', "Squares: beam-column joints")));
			}
			append(this.legend, $('.fem-legend-row', undefined, localize('femResults.designUncoloured', "Grey: not checked")));
			shown = true;
		} else if (this.entry) {
			const contour = this.contourRange();
			const diagram = this.diagramRange();
			const mode = this.entry.kind === 'modal' ? this.entry.modes?.[this.mode - 1] : undefined;
			if (mode && this.show === 'deformed') {
				append(this.legend, $('.fem-legend-title', undefined, modeText(mode)));
				if (mode.period !== null && mode.period > 0) {
					append(this.legend, $('.fem-legend-row', undefined, localize('femResults.modeFrequency', "f = {0} Hz; size arbitrary", (1 / mode.period).toFixed(2))));
				}
				shown = true;
			} else if (diagram) {
				append(this.legend, $('.fem-legend-title', undefined, this.showOptions().find(o => o.show === this.show)?.label ?? ''));
				for (const [kind, label] of [['positive', diagram.max], ['negative', diagram.min]] as const) {
					const row = append(this.legend, $('.fem-legend-row'));
					append(row, $(`span.fem-diagram-swatch.${kind}`));
					append(row, $('span', undefined, label));
				}
				shown = true;
			} else if (contour) {
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

	/** A force diagram's largest and least value over the members shown ("max 12.3 kN·m in B1"). */
	private diagramRange(): { readonly max: string; readonly min: string } | undefined {
		const component = COMPONENTS.indexOf(this.show);
		const view = this.view;
		if (component < 0 || !view) {
			return undefined;
		}
		let max: { value: number; name: string } | undefined;
		let min: { value: number; name: string } | undefined;
		for (const element of this.shownElements(view)) {
			for (const forces of element.forces ?? []) {
				const value = forces[component];
				if (!max || value > max.value) {
					max = { value, name: element.name };
				}
				if (!min || value < min.value) {
					min = { value, name: element.name };
				}
			}
		}
		if (!max || !min) {
			return undefined;
		}
		const quantity: Quantity = component < 3 ? 'force' : 'moment';
		return {
			max: localize('femResults.diagramMax', "max {0} in {1}", this.format(quantity, max.value), max.name.split('#')[0]),
			min: localize('femResults.diagramMin', "min {0} in {1}", this.format(quantity, min.value), min.name.split('#')[0]),
		};
	}

	/** The lowest and highest value of a shell or solid contour, as the 3D view colours it. */
	private contourRange(): { readonly min: string; readonly max: string } | undefined {
		if (isRebarShow(this.show)) {
			const values = this.design ? Object.values(slabRebar(this.design, REBAR_SHOWS.indexOf(this.show))) : [];
			return values.length ? { min: this.format('areaPerLength', Math.min(...values)), max: this.format('areaPerLength', Math.max(...values)) } : undefined;
		}
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
		this.plannedChips.value = new DisposableStore();
		if (!entry) {
			return false;
		}
		const selection = this.selection;
		if (this.show === 'utilisation') {
			this.renderDesignProperties(container, selection);
		} else if (this.show === 'joints') {
			this.renderJointProperties(container, selection);
		} else if (selection && view && view.kind !== 'modal') {
			this.renderSelection(container, selection, view);
		} else {
			appendPropertyNote(container, selection
				? localize('femResults.modalSelection', "A mode shape has no values to report: its amplitude is arbitrary.")
				: localize('femResults.selectHint', "Select a node or a member in the view for its values."));
		}
		appendPropertyHeading(container, localize('femResults.resultHeading', "Result"));
		appendPropertyRow(container, localize('femResults.resultName', "Shown"), entry.label);
		if (entry.kind === 'modal') {
			const mode = entry.modes?.[this.mode - 1];
			if (mode) {
				appendPropertyRow(container, localize('femResults.modeNumber', "Mode"), String(mode.number));
				if (mode.period !== null) {
					appendPropertyRow(container, localize('femResults.period', "Period"), localize('femResults.seconds', "{0} s", mode.period.toFixed(3)));
				}
			}
		}
		if (entry.kind === 'modal' || entry.kind === 'spectrum') {
			this.renderSeismic(container, entry.kind === 'spectrum' ? spectrumAxis(entry.label) : undefined, false);
		}
		if ((entry.kind === 'static' || entry.kind === 'combination') && !isDesignShow(this.show) && !isFirstOrderReference(entry.label)) {
			this.renderSecondOrder(container);
		}
		if (entry.kind === 'pushover') {
			appendPropertyHeading(container, localize('femResults.curveHeading', "Capacity Curve"));
			this.renderCurve(container, entry.frames ?? []);
			this.appendPlanned(container, [FemPlanned.pushoverHinges, FemPlanned.fibreWalls, FemPlanned.performancePoint]);
		} else if (entry.kind === 'modal') {
			this.appendPlanned(container, [FemPlanned.floorVibration]);
		} else if (entry.kind === 'history') {
			this.appendPlanned(container, [FemPlanned.nonlinearTimeHistory, FemPlanned.timeHistoryDesign, FemPlanned.recordScaling]);
		} else if (entry.kind === 'static' && entry.frames?.length) {
			this.appendPlanned(container, [FemPlanned.stagedConstruction, FemPlanned.creepShrinkage, FemPlanned.columnShortening]);
		}
		if (!selection && !isDesignShow(this.show)) {
			this.ssi.render(container);
		}
		return true;
	}

	/** Chips to the planned features that will extend the result shown. */
	private appendPlanned(container: HTMLElement, ids: readonly string[]): void {
		this.plannedChips.value?.add(appendPlannedChips(container, undefined, ids, this.commandService));
	}

	private renderSelection(container: HTMLElement, selection: FemSelection, view: IFemResultView): void {
		const format = this.format;
		if (selection.kind === 'node') {
			appendPropertyHeading(container, localize('femResults.nodeHeading', "Node {0}", selection.id));
			const node = view.nodes.find(n => n[0] === selection.id);
			if (node) {
				appendPropertyRow(container, localize('femResults.ux', "Displacement x"), format('length', node[1]));
				appendPropertyRow(container, localize('femResults.uy', "Displacement y"), format('length', node[2]));
				appendPropertyRow(container, localize('femResults.uz', "Displacement z"), format('length', node[3]));
				appendPropertyRow(container, localize('femResults.uTotal', "Total"), format('length', Math.hypot(node[1], node[2], node[3])));
			}
			const reaction = view.reactions.find(r => r[0] === selection.id);
			if (reaction) {
				appendPropertyHeading(container, localize('femResults.reactionHeading', "Support Reaction"));
				appendPropertyRow(container, 'Fx', format('force', reaction[1]));
				appendPropertyRow(container, 'Fy', format('force', reaction[2]));
				appendPropertyRow(container, 'Fz', format('force', reaction[3]));
			}
			return;
		}
		const element = view.elements.find(e => e.id === selection.id);
		const shell = element ? undefined : view.shells?.find(s => s.id === selection.id);
		// A meshed member's piece is headed by its member (as the legend and status name it), the piece below.
		const piece = element?.name.split('#')[1];
		appendPropertyHeading(container, element?.name.split('#')[0] ?? shell?.name ?? localize('femResults.elementHeading', "Element {0}", selection.id));
		if (piece) {
			appendPropertyNote(container, localize('femResults.elementPiece', "Analysis piece {0} of the member: its forces below.", piece));
		}
		if (element?.forces?.length) {
			// Every section force along the member: smallest, largest and at both ends.
			for (const [index, name] of COMPONENT_NAMES.entries()) {
				const values = element.forces.map(f => f[index]);
				const quantity: Quantity = index < 3 ? 'force' : 'moment';
				const value = localize('femResults.range', "{0} to {1}", format(quantity, Math.min(...values)), format(quantity, Math.max(...values)));
				appendPropertyRow(container, name, value);
			}
			const component = COMPONENTS.indexOf(this.show);
			if (component >= 0) {
				const quantity: Quantity = component < 3 ? 'force' : 'moment';
				appendPropertyNote(container, localize('femResults.ends', "{0} at end i {1}, at end j {2}.", COMPONENT_NAMES[component],
					format(quantity, element.forces[0][component]), format(quantity, element.forces[element.forces.length - 1][component])));
			}
		} else if (shell?.forces?.length) {
			for (const [index, name] of SHELL_COMPONENTS.entries()) {
				const quantity: Quantity = index >= 3 && index < 6 ? 'momentPerLength' : 'forcePerLength';
				appendPropertyRow(container, name, format(quantity, shell.forces[index]));
			}
		} else {
			appendPropertyNote(container, localize('femResults.noForces', "No section forces are recorded for this element."));
		}
	}

	/**
	 * The selected member's design checks, the governing first (a wall's with its piers and
	 * coupling beams); or why it was not checked. Without a selection, the summary and the stairs.
	 */
	private renderDesignProperties(container: HTMLElement, selection: FemSelection | undefined): void {
		const report = this.design;
		if (!report) {
			appendPropertyNote(container, this.designProblem ?? localize('femResults.designRunning', "Checking the members against the load combinations..."));
			return;
		}
		if (selection?.kind !== 'element') {
			appendPropertyHeading(container, localize('femResults.designHeading', "Design Checks"));
			appendPropertyRow(container, localize('femResults.designCode', "Code"), report.code);
			appendPropertyRow(container, localize('femResults.designPassed', "Pass"), String(report.summary.passed));
			appendPropertyRow(container, localize('femResults.designFailed2', "Fail"), String(report.summary.failed));
			if (report.summary.skipped) {
				appendPropertyRow(container, localize('femResults.designSkipped', "Not checked"), String(report.summary.skipped));
			}
			if (report.summary.maxUtilisation !== null && report.summary.governing) {
				appendPropertyRow(container, localize('femResults.designLargest', "Largest"), localize('femResults.designLargestValue', "{0} in {1}", formatUtilisation(report.summary.maxUtilisation), report.summary.governing));
			}
			const steel = this.required?.summary;
			if (steel) {
				// Members, not the backend's rows (one per zone, strip and layer).
				const short = shortElements(this.required);
				appendPropertyRow(container, localize('femResults.steelShortCount', "Steel short"), short.length
					? localize('femResults.steelShortMembers', "{0} ({1})", short.length, short.length > 6 ? localize('femResults.steelShortMore', "{0}, ...", short.slice(0, 6).join(', ')) : short.join(', '))
					: '0');
				// The backend's summary.tooSmall also holds footings failing bearing or resultant,
				// which bars cannot fix but a larger section is not the only answer to.
				const tooSmall = tooSmallElements(this.required);
				if (tooSmall.length) {
					appendPropertyRow(container, localize('femResults.steelTooSmallCount', "Too small"), tooSmall.join(', '));
				}
				const others = otherFailureElements(this.required);
				if (others.length) {
					appendPropertyRow(container, localize('femResults.steelOtherFailures', "Other checks fail"), others.join(', '));
				}
				if (steel.assumed?.length) {
					appendPropertyRow(container, localize('femResults.steelNoBars', "No bars yet"), steel.assumed.join(', '));
				}
			}
			const secondOrderRequired = secondOrderRequiredMembers(report);
			if (secondOrderRequired.length) {
				appendPropertyRow(container, localize('femResults.secondOrderRequiredCount', "Second-order analysis required"), secondOrderRequired.join(', '));
			}
			const walls = describeWallsSummary(report);
			if (walls) {
				appendPropertyRow(container, localize('femResults.designWalls', "Walls"), walls);
			}
			const steelMembers = describeSteelSummary(report);
			if (steelMembers) {
				appendPropertyRow(container, localize('femResults.designSteel', "Steel members"), steelMembers);
				this.appendPlanned(container, [...STEEL_CONNECTIONS_PLANNED, ...STEEL_STABILITY_PLANNED, ...STEEL_SHEDS_PLANNED]);
			}
			this.renderStairs(container, report);
			this.renderDiaphragms(container, report);
			this.renderTakedown(container, report);
			this.renderSeismic(container, undefined, true);
			appendPropertyNote(container, localize('femResults.designSelect', "Select a member, or a slab's shell, for its checks."));
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
				appendPropertyHeading(container, localize('femResults.memberHeading', "{0} ({1} {2})", id, designKindLabel(steel[0].kind), steel[0].type));
				appendPropertyNote(container, localize('femResults.noBarsYet', "No bars entered yet: the steel it requires is shown. Design Reinforcement proposes bars."));
				this.renderSteel(container, steel, false);
				return;
			}
			appendPropertyHeading(container, id ?? localize('femResults.elementHeading', "Element {0}", selection.id));
			appendPropertyNote(container, skipped
				? localize('femResults.notChecked', "Not checked ({0}): {1}.", skipped.type, skipped.reason)
				: localize('femResults.noDesignSteel', "This element is not designed (only reinforced-concrete beams, columns, slabs and walls, and steel beams, columns and braces are)."));
			if (skipped && this.requiredLoading) {
				appendPropertyNote(container, localize('femResults.steelLoading', "Working out the steel required..."));
			}
			return;
		}
		appendPropertyHeading(container, localize('femResults.memberHeading', "{0} ({1} {2})", element.id, designKindLabel(element.kind), element.type));
		const verdict = append(container, $(`.fem-design-verdict.${element.ok ? 'pass' : 'fail'}`));
		append(verdict, $('span', undefined, element.ok ? localize('femResults.passes', "Passes") : localize('femResults.fails', "Fails")));
		append(verdict, $('span.value', undefined, formatUtilisation(element.utilisation)));
		const checks = sortedChecks(element);
		// The seismic detailing checks count in the utilisation above, but show in their own section;
		// so do a wall's pier and coupling beam checks and a staircase's flight and geometry checks.
		const isConnection = memberConnectionChecks(element);
		for (const check of generalChecks(sortedChecks({ ...element, checks: ownChecks(element) })).filter(c => !isConnection(c))) {
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
			appendPropertyNote(container, localize('femResults.governing', "Governing: {0}.", governing.note));
		}
		if (element.kind === 'slab') {
			const prestressed = element.checks.some(c => c.name.startsWith('PT '));
			this.appendPlanned(container, [
				FemPlanned.crackedSlabDeflection,
				FemPlanned.crackWidths,
				...(prestressed ? [FemPlanned.tendonLayout, FemPlanned.tendonLongTermLosses] : []),
			]);
		}
		// A column's slenderness about each axis: how its moments are magnified for it.
		for (const check of checks.filter(isSlendernessCheck)) {
			const rows = describeSlenderness(check);
			if (rows.length) {
				appendPropertyHeading(container, slendernessHeading(check));
				// Names kept on one line ("k lu / r"): the values wrap instead.
				const section = append(container, $('.fem-slenderness'));
				for (const row of rows) {
					appendPropertyRow(section, row.name, row.value);
				}
			}
		}
		// A steel member's class, lengths, Cb and governing clause, then its connections.
		const steel = steelSection(element);
		this.renderDetailing(container, steel);
		if (steel.length) {
			this.appendPlanned(container, [FemPlanned.compositeBeams, FemPlanned.compositeColumns]);
		}
		// A timber member's section, stresses and end joint, then the joints still planned (screws).
		const timber = timberSection(element);
		this.renderDetailing(container, timber);
		if (timber.length) {
			this.appendPlanned(container, [FemPlanned.timberConnections]);
		}
		this.renderDetailing(container, detailingSection(report, element, this.model));
		if (isWall(element)) {
			const diagram = pierDiagram(element, selection.id);
			if (diagram) {
				appendPropertyHeading(container, localize('femResults.pierDiagramHeading', "Pier Forces"));
				this.renderPierDiagram(container, diagram);
			}
			this.renderDetailing(container, wallSection(element, selection.id));
			if (String(element.wallType ?? '').startsWith('masonry')) {
				this.appendPlanned(container, [FemPlanned.confinedMasonry]);
			}
		} else if (isStaircase(element)) {
			this.renderDetailing(container, staircaseSection(element));
		}
		this.renderSteel(container, requiredSteelOf(this.required, element.id), true);
		if (this.requiredLoading) {
			appendPropertyNote(container, localize('femResults.steelLoading', "Working out the steel required..."));
		}
	}

	/** Draws the items of a seismic detailing section (a member's, or a joint's). */
	private renderDetailing(container: HTMLElement, items: readonly FemDetailingItem[]): void {
		for (const item of items) {
			switch (item.kind) {
				case 'heading': appendPropertyHeading(container, item.text); break;
				case 'subheading': append(container, $('.fem-detailing-group', undefined, item.text)); break;
				case 'note': appendPropertyNote(container, item.text); break;
				case 'row': {
					const row = append(container, $(`.sa-props-row.fem-detailing-row${item.ok === false ? '.fail' : ''}`));
					append(row, $('span.name', undefined, item.name));
					append(row, $('span.value', undefined, item.value));
					break;
				}
				case 'check': {
					const row = append(container, $(`.fem-design-check${item.ok ? '' : '.fail'}`));
					const head = append(row, $('.fem-design-check-head'));
					append(head, $('span.name', undefined, item.name));
					append(head, $('span.value', undefined, item.value));
					append(row, $('.fem-design-check-detail', undefined, item.detail));
					if (item.note && !item.ok) {
						append(row, $('.fem-design-check-detail', undefined, item.note));
					}
					break;
				}
			}
		}
	}

	/**
	 * A wall's pier forces along its height: per storey (top first), bars of P, V2 and M3 under
	 * each pier's governing combination, each force scaled to its largest; the pier at the
	 * selected shell marked, a failing pier's label in the failing colour.
	 */
	private renderPierDiagram(container: HTMLElement, diagram: IFemPierDiagram): void {
		const grid = append(container, $('.fem-pier-diagram', { role: 'table', 'aria-label': localize('femResults.pierDiagramAria', "Pier forces per storey") }));
		const head = append(grid, $('.fem-pier-row.head', { role: 'row' }));
		append(head, $('span.label', { role: 'columnheader' }, localize('femResults.pierStorey', "Storey")));
		const columns = [
			['P', localize('femResults.pierP', "P"), diagram.max.P],
			['V2', localize('femResults.pierV2', "V2"), diagram.max.V2],
			['M3', localize('femResults.pierM3', "M3"), diagram.max.M3],
		] as const;
		for (const [key, name, max] of columns) {
			append(head, $('span.force', { role: 'columnheader', title: localize('femResults.pierMax', "{0}: largest {1}", name, formatPierForce(key, max)) }, name));
		}
		for (const bar of diagram.bars) {
			const row = append(grid, $(`.fem-pier-row${bar.selected ? '.selected' : ''}${bar.ok ? '' : '.fail'}`, { role: 'row' }));
			append(row, $('span.label', { role: 'rowheader', title: bar.governing ? localize('femResults.pierGoverning', "{0} (governing)", bar.label) : bar.label }, bar.label));
			for (const [key, name, max] of columns) {
				const value = bar[key];
				const cell = append(row, $('span.force', { role: 'cell', title: localize('femResults.pierValue', "{0} {1}", name, formatPierForce(key, value)) }));
				const fill = append(cell, $(`span.bar${value < 0 ? '.negative' : ''}`));
				fill.style.width = `${max > 0 ? Math.abs(value) / max * 100 : 0}%`;
			}
		}
		appendPropertyNote(container, localize('femResults.pierDiagramNote', "Each pier under its governing combination; bars scaled to the largest of each force, negative values in a second colour. Hover a bar for its value."));
	}

	/**
	 * The staircases of the design checks, under the summary: they are not in the analysis model,
	 * so they cannot be picked in the view; each opens for its geometry, flights and bars.
	 */
	private renderStairs(container: HTMLElement, report: IFemDesignReport): void {
		const stairs = staircasesOf(report);
		if (!stairs.length) {
			return;
		}
		appendPropertyHeading(container, localize('femResults.stairsHeading', "Stairs"));
		for (const stair of stairs) {
			const details = append(container, $(`details.fem-stair${stair.ok ? '' : '.fail'}`));
			append(details, $('summary', undefined, describeStaircaseVerdict(stair)));
			// A staircase shown by its parts has no checks of its own; one without parts, a flat list.
			this.renderDetailing(details, [...checkItems(generalChecks(ownChecks(stair))), ...staircaseSection(stair)]);
			this.renderSteel(details, requiredSteelOf(this.required, stair.id), true);
		}
	}

	/**
	 * The columns' gravity load takedown, under the summary: one fold per column line, a row per
	 * storey (top down) with the factored and unfactored load at the column's foot and what the
	 * storey adds.
	 */
	private renderTakedown(container: HTMLElement, report: IFemDesignReport): void {
		const lines = report.takedown?.lines ?? [];
		if (!lines.length) {
			return;
		}
		appendPropertyHeading(container, localize('femResults.takedownHeading', "Column Load Takedown"));
		for (const line of lines) {
			const foot = line.rows[line.rows.length - 1];
			const details = append(container, $('details.fem-stair'));
			append(details, $('summary', undefined, localize('femResults.takedownLine', "{0}: {1} kN factored at the base", line.line, foot ? foot.factored.toFixed(0) : '0')));
			for (const row of line.rows) {
				const added = Object.values(row.storey).reduce((sum, v) => sum + v, 0);
				appendPropertyRow(details, localize('femResults.takedownStorey', "{0} ({1})", row.story, row.column),
					localize('femResults.takedownValue', "{0} kN factored, {1} kN unfactored (+{2} kN this storey)", row.factored.toFixed(0), row.total.toFixed(0), added.toFixed(0)));
			}
		}
		if (report.takedown?.note) {
			appendPropertyNote(container, report.takedown.note);
		}
	}

	/**
	 * The floors' diaphragm chords and collectors (BNBC 2020 Part 6 Sec 2.5.5.6), under the
	 * summary: like the stairs they have no analysis elements to pick. Below them, the strut-and-tie
	 * models of other D-regions that are planned.
	 */
	private renderDiaphragms(container: HTMLElement, report: IFemDesignReport): void {
		const diaphragms = report.elements.filter(e => e.kind === 'diaphragm');
		appendPropertyHeading(container, localize('femResults.diaphragmsHeading', "Diaphragms and Deep Members"));
		for (const diaphragm of diaphragms) {
			const details = append(container, $(`details.fem-stair${diaphragm.ok ? '' : '.fail'}`));
			append(details, $('summary', undefined, diaphragm.ok
				? localize('femResults.diaphragmPasses', "{0} passes, {1}", diaphragm.id, formatUtilisation(diaphragm.utilisation))
				: localize('femResults.diaphragmFails', "{0} fails, {1}", diaphragm.id, formatUtilisation(diaphragm.utilisation))));
			this.renderDetailing(details, checkItems(diaphragm.checks));
		}
		if (!diaphragms.length) {
			appendPropertyNote(container, localize('femResults.diaphragmsNone', "No diaphragm chords or collectors: the model has no equivalent static earthquake cases (EX, EY) or no slabs."));
		}
		appendPropertyNote(container, localize('femResults.deepMembersNote', "Deep beams, transfer girders and corbels are checked with their beams: select one for its strut-and-tie and corbel checks."));
		const chips = append(container, $('.fem-planned-chips'));
		this.diaphragmChips.clear();
		this.diaphragmChips.add(appendPlannedFeatureChip(chips, PLANNED_STM_GENERAL, this.commandService));
	}

	/**
	 * The joints view's part of the properties panel: the selected joint (its node) with its
	 * members, joint shear and strong-column / weak-beam ratios; a selected member's joints; or
	 * the joints' summary.
	 */
	private renderJointProperties(container: HTMLElement, selection: FemSelection | undefined): void {
		const report = this.design;
		if (!report) {
			appendPropertyNote(container, this.designProblem ?? localize('femResults.designRunning', "Checking the members against the load combinations..."));
			return;
		}
		const joints = jointsOf(report);
		let shown: IFemJoint[] = [];
		if (selection?.kind === 'node') {
			const joint = jointAtNode(report, selection.id, this.model);
			if (!joint) {
				appendPropertyHeading(container, localize('femResults.nodeHeading', "Node {0}", selection.id));
				appendPropertyNote(container, localize('femResults.noJointAtNode', "No beam-column joint is checked at this node."));
				return;
			}
			shown = [joint];
		} else if (selection?.kind === 'element') {
			const member = designElementOf(report, selection.id);
			shown = member ? jointsOfMember(report, member.id) : [];
			if (!shown.length) {
				appendPropertyHeading(container, member?.id ?? localize('femResults.elementHeading', "Element {0}", selection.id));
				appendPropertyNote(container, localize('femResults.noJointsOfMember', "This member frames into no checked joint."));
				return;
			}
		}
		if (!shown.length) {
			appendPropertyHeading(container, localize('femResults.jointsHeading', "Joint Checks"));
			appendPropertyNote(container, describeJointsSummary(report));
			if (joints.length) {
				appendPropertyNote(container, localize('femResults.jointsSelect', "Select a joint's node, or a beam or column, for its checks."));
			}
			return;
		}
		for (const joint of shown) {
			appendPropertyHeading(container, jointHeading(joint));
			const verdict = describeJointVerdict(joint);
			const line = append(container, $(`.fem-design-verdict.${verdict.ok ? 'pass' : 'fail'}`));
			append(line, $('span', undefined, verdict.governing
				? (verdict.ok ? localize('femResults.jointPassesBy', "Passes ({0})", verdict.governing) : localize('femResults.jointFailsBy', "Fails ({0})", verdict.governing))
				: (verdict.ok ? localize('femResults.passes', "Passes") : localize('femResults.fails', "Fails"))));
			if (verdict.utilisation) {
				append(line, $('span.value', undefined, verdict.utilisation));
			}
			this.renderDetailing(container, jointItems(joint));
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
			appendPropertyHeading(container, localize('femResults.steelHeading', "Required Steel"));
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
				case 'heading': appendPropertyHeading(container, item.text); break;
				case 'note': appendPropertyNote(container, item.text); break;
				case 'row': appendPropertyRow(container, item.name, item.value); break;
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
		appendPropertyHeading(container, localize('femResults.secondOrderHeading', "Second Order"));
		appendPropertyNote(container, note);
		for (const row of storeyAmplificationRows(secondOrder)) {
			appendPropertyRow(container, row.name, row.value);
		}
		for (const text of secondOrder?.notes ?? []) {
			appendPropertyNote(container, text);
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
		appendPropertyRow(container, localize('femResults.peakShearName', "Largest base shear"), this.format('force', vMax));
		appendPropertyRow(container, localize('femResults.peakRoofName', "At roof"), this.format('length', points.find(p => p[1] === vMax)?.[0] ?? 0));
	}
}
