/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IntervalTimer } from '../../../../base/common/async.js';
import { CancellationError, isCancellationError } from '../../../../base/common/errors.js';
import { CancellationToken, CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { Event } from '../../../../base/common/event.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { IReference } from '../../../../base/common/lifecycle.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { createDecorator, IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { INotificationService, IPromptChoice, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { recordedStamp, sourceStamp, upstreamPart } from '../../../services/saengineProject/common/partSources.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { awaitsTankDesigns, BOQ_COMPUTE_COMMAND, BOQ_SOURCES, boqComputeArgs, changedSources, IBoqComputeResult, parseBoq } from '../../saengineBoq/browser/boqDocument.js';
import { BUILD_REPORT_COMMAND_ID, IReportBuildRequest, IReportBuildResult, reportProblems, reportStepMessage } from '../../saengineReport/browser/reportBuild.js';
import { ISubstructureRequest, parseSubstructure, readSubstructureReport, SUBSTRUCTURE_SUMMARY_FILE, substructureSummaryFile } from '../../saengineSubstructure/browser/substructureDocument.js';
import { IMepContextTexts, IMepReport, IMepRequest, isOpenClash, MEP_REPORT_COMMAND, MEP_SOURCE_PARTS, MEP_SUMMARY_FILE, mepSummaryFile, parseMep, readMepReport } from '../../saengineMep/browser/mepDocument.js';
import { hasPlumbing, IPlumbingReport, PLUMBING_REPORT_COMMAND, plumbingFailures, plumbingSummaryFile, readPlumbingReport } from '../../saengineMep/browser/plumbingDocument.js';
import { hasHvac, HVAC_REPORT_COMMAND, hvacFailures, hvacSummaryFile, readHvacReport } from '../../saengineMep/browser/hvacDocument.js';
import { ELECTRICAL_REPORT_COMMAND, electricalFailures, electricalSummaryFile, hasElectrical, readElectricalReport } from '../../saengineMep/browser/electricalDocument.js';
import { FIRE_REPORT_COMMAND, fireFailures, fireSummaryFile, hasFire, readFireReport } from '../../saengineMep/browser/fireDocument.js';
import { DRAWINGS_GENERATE_COMMAND, DRAWINGS_LIST_COMMAND, readDrawingSet } from '../../saengineProject/browser/drawingsModel.js';
import { ARCHITECTURE_DERIVATION_SOURCE, DERIVATION_INPUTS, deriveAnalysisModel, derivationState, FACES_FILE, LOADS_DERIVATION_SOURCE, partFile, SSI_FILE, THERMAL_FILE } from '../browser/femDerivationBar.js';
import { SSI_COMPARE_COMMAND } from '../browser/femSsi.js';
import { DESIGN_REINFORCEMENT_COMMAND, DESIGN_SUMMARY_FILE, IFemDesignReport, IFemDesignRequired, resultsFolder, runDesign, runDesignRequired, shortElements, tooSmallElements, writeDesignSummary } from '../browser/femDesign.js';
import { errorSummary, IFemRunOutcome, IFemRunTracker } from '../browser/femResultsBar.js';
import { FemModelEditorInput } from '../browser/femModelEditorInput.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { FemAnalysisRunner } from './femAnalysisRunner.js';

/** Internal command of the mesh convergence check (`saengine.fem.mesh_check`). */
const MESH_CHECK_COMMAND = 'saengine.fem.meshCheck';

/** What the mesh check answers (read defensively). */
interface IMeshCheck {
	readonly warning?: boolean;
	readonly maxChangePercent?: number;
	readonly coarseSize_mm?: number;
	readonly skipped?: string;
}

/** Desktop commands that build the building model from its source (see the building editor). */
const BIM_GENERATE_COMMAND = 'saengine.bim.generate';
const BIM_GENERATE_FROM_STRUCTURE_COMMAND = 'saengine.bim.generateFromStructure';

/** Command id of Run All, and of stopping it (the status bar entry and the title bar's Stop run it). */
export const RUN_ALL_COMMAND_ID = 'saengine.runAll';
export const CANCEL_RUN_ALL_COMMAND_ID = 'saengine.runAll.cancel';
/** Command id of Restart Engine: stops the Python backend; the next request starts a new one. */
export const RESTART_ENGINE_COMMAND_ID = 'saengine.restartEngine';

/** Set while Run All runs: the title bar shows Stop in place of Run All. */
export const RunAllRunningContext = new RawContextKey<boolean>('saengineRunAllRunning', false, localize('runAll.runningContext', "Whether SAEngine's Run All is running"));

/**
 * Beside the analysis results: the stamp of the model they were computed from (and of the run's
 * manifest), so a model derived again to the same analysis keeps them. The Python side
 * (`saengine.pipeline.run_all`) reads and writes the same file.
 */
export const ANALYSIS_INPUTS_FILE = 'analysis-inputs.json';
const RESULTS_MANIFEST = 'manifest.json';

/** After this long on one backend step the status says the engine is busy, and how to stop it. */
const ENGINE_BUSY_MS = 60_000;

const STATUS_ENTRY_ID = 'saengine.runAll.status';

type StepId = 'bim' | 'derive' | 'analysis' | 'ssi' | 'substructure' | 'design' | 'mep' | 'boq' | 'report' | 'drawings';

interface IStep {
	readonly id: StepId;
	readonly label: string;
	/** The steps it needs: when one of them does not succeed, it is not run. */
	readonly needs: readonly StepId[];
}

/**
 * The steps of Run All, in order. The foundations come before the design checks: the minimum
 * bars they may add are written to the substructure file, which the design checks read too, so
 * after them the kept checks would be stale and the report would check every member again.
 * Mirrors `STEPS` and `STEP_NEEDS` of `saengine.pipeline.run_all`.
 */
export const RUN_ALL_STEPS: readonly IStep[] = [
	{ id: 'bim', label: localize('runAll.step.bim', "building model"), needs: [] },
	{ id: 'derive', label: localize('runAll.step.derive', "analysis model"), needs: ['bim'] },
	{ id: 'analysis', label: localize('runAll.step.analysis', "analysis"), needs: ['derive'] },
	{ id: 'ssi', label: localize('runAll.step.ssi', "fixed-base run for the soil springs"), needs: ['analysis'] },
	{ id: 'substructure', label: localize('runAll.step.substructure', "foundation design"), needs: ['analysis'] },
	{ id: 'design', label: localize('runAll.step.design', "design checks"), needs: ['analysis'] },
	{ id: 'mep', label: localize('runAll.step.mep', "MEP checks"), needs: ['bim'] },
	{ id: 'boq', label: localize('runAll.step.boq', "bill of quantities"), needs: ['bim'] },
	{ id: 'report', label: localize('runAll.step.report', "report"), needs: ['design'] },
	{ id: 'drawings', label: localize('runAll.step.drawings', "drawings"), needs: ['design'] },
];

/**
 * How a step ended: done; done with something to look at (bars added, members not checked, a
 * mesh warning); nothing to do (up to date, nothing to check); could not be done; not run (a
 * step it needs did not succeed); stopped by the engineer.
 */
export type StepStatus = 'ok' | 'warning' | 'skipped' | 'failed' | 'notRun' | 'cancelled';

export interface IStepOutcome {
	readonly id: StepId;
	readonly label: string;
	readonly status: StepStatus;
	readonly message: string;
	/** Wall-clock time of the step. */
	readonly seconds: number;
	/** Checks of this step that fail (members, foundations, MEP checks): the engineer's work, not the step's failure. */
	readonly failing?: number;
}

/** What a step that ran says. */
interface IStepResult {
	readonly status: 'ok' | 'warning' | 'skipped';
	readonly message: string;
	readonly failing?: number;
}

/** A step that could not be done: its outcome is `failed`, and the steps that need it are not run. */
class StepFailure extends Error { }

/** A discipline's report of 7 MEP in Run All, with the openings it still needs (reported, not added). */
interface IServiceCheck<T> {
	readonly report: T;
	readonly missingOpenings: number;
}

/** What one run found along the way, for the summary and the later steps. */
interface IRunContext {
	readonly project: ISaengineProject;
	readonly model: URI;
	readonly token: CancellationToken;
	design?: IFemDesignReport;
	required?: IFemDesignRequired;
	tanksDesigned?: boolean;
	pdf?: URI;
	/** Object types the design checks skipped for want of bars. */
	noBars?: boolean;
	/** The analysis failed in the solver: Show Log helps. */
	analysisLog?: boolean;
}

function record(value: unknown): { readonly [key: string]: unknown } {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as { readonly [key: string]: unknown } : {};
}

/** How many openings a backend report proposes (its `openings`: those not in 07 MEP yet). */
function openingsOf(raw: unknown): number {
	const openings = record(raw).openings;
	return Array.isArray(openings) ? openings.length : 0;
}

/** The members of a building model's text (0 for a placeholder or an unreadable file). */
export function bimMembers(text: string | undefined): number {
	try {
		const elements = record(text ? JSON.parse(text) : undefined).elements;
		return Array.isArray(elements) ? elements.length : 0;
	} catch {
		return 0;
	}
}

/**
 * The stamp of an analysis model's text without its `meta` (its name and the stamps of the
 * sources it was derived from): what the solver computes from. The Python side
 * (`saengine.fem.derive.model_stamp`) computes the same.
 */
export function femModelStamp(text: string): string {
	let document: unknown;
	try {
		document = JSON.parse(text);
	} catch {
		return sourceStamp(text);
	}
	if (typeof document !== 'object' || document === null || Array.isArray(document)) {
		return sourceStamp(text);
	}
	return sourceStamp(JSON.stringify(Object.fromEntries(Object.entries(document).filter(([key]) => key !== 'meta'))));
}

/**
 * The stamp of what the solver computes from: the model ({@link femModelStamp}) and its side
 * files by name (the temperature case, the soil springs, the support faces; undefined when
 * missing). `saengine.pipeline.run_all.analysis_inputs_stamp` computes the same.
 */
export function analysisInputsStamp(modelText: string, sideTexts: readonly (readonly [string, string | undefined])[]): string {
	return sourceStamp([femModelStamp(modelText), ...sideTexts.map(([name, text]) => `${name}=${text === undefined ? '' : sourceStamp(text)}`)].join('\n'));
}

/** "4:05" of seconds; "1:02:10" past an hour. */
export function formatDuration(seconds: number): string {
	const total = Math.max(0, Math.round(seconds));
	const s = total % 60;
	const m = Math.floor(total / 60) % 60;
	const h = Math.floor(total / 3600);
	const pad = (n: number) => String(n).padStart(2, '0');
	return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** One line of the step summary: "✓ 3. analysis: up to date (0:01)". */
export function outcomeLine(outcome: IStepOutcome, index: number): string {
	const mark = { ok: '✓', warning: '⚠', skipped: '–', failed: '✗', notRun: '·', cancelled: '■' }[outcome.status];
	const time = outcome.status === 'notRun' || (outcome.status === 'cancelled' && !outcome.seconds) ? '' : ` (${formatDuration(outcome.seconds)})`;
	return `${mark} ${index + 1}. ${outcome.label}: ${outcome.message}${time}`;
}

/**
 * The severity of a run's end: an error when a step failed; a warning when a step warned or
 * checks fail; information when all is done, or when the engineer stopped it.
 */
export function runSeverity(outcomes: readonly IStepOutcome[]): Severity {
	if (outcomes.some(o => o.status === 'failed')) {
		return Severity.Error;
	}
	if (outcomes.some(o => o.status === 'cancelled')) {
		return Severity.Info;
	}
	return outcomes.some(o => o.status === 'warning' || (o.failing ?? 0) > 0) ? Severity.Warning : Severity.Info;
}

export const IRunAllService = createDecorator<IRunAllService>('saengineRunAllService');

/**
 * Brings the open project's outputs up to date in one go, step by step ({@link RUN_ALL_STEPS}):
 * builds the building model when its source changed, derives the analysis model when out of
 * date, runs the analysis unless its results were computed from the same model, compares the
 * soil springs with a fixed base, designs the foundations (minimum bars for those without), runs
 * the design checks, checks MEP, measures the bill, builds the report and redraws a generated set
 * of drawings. Each step ends ok, with a warning, with nothing to do, failed, or not run (it
 * needs a step that failed); a failed step never leaves its previous summary looking current.
 * Progress is one status bar entry (the step, its detail, the time; click to stop); Run All in
 * the title bar becomes Stop. The end is one notification whose severity says how it went, with
 * the steps one click away.
 */
export interface IRunAllService {
	readonly _serviceBrand: undefined;
	readonly running: boolean;
	/** The outcome of each step of the last run (empty before the first). */
	readonly lastOutcomes: readonly IStepOutcome[];
	run(): Promise<void>;
	cancel(): void;
	/** Stops the backend (a design check that takes too long); the next request starts it again. */
	restartEngine(): Promise<void>;
}

export class RunAllService implements IRunAllService {

	declare readonly _serviceBrand: undefined;

	private cancellation: CancellationTokenSource | undefined;
	private status: IStatusbarEntryAccessor | undefined;
	private readonly runningKey: IContextKey<boolean>;
	private readonly ticker = new IntervalTimer();
	/** The step going: its index, when it started, what it reports and whether the backend is doing it. */
	private current: { index: number; started: number; detail?: string; backend: boolean } | undefined;
	private runStarted = 0;
	private _lastOutcomes: IStepOutcome[] = [];

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@INotificationService private readonly notificationService: INotificationService,
		@IOpenerService private readonly openerService: IOpenerService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IEditorService private readonly editorService: IEditorService,
		@IDialogService private readonly dialogService: IDialogService,
		@IFemSolverService private readonly solverService: IFemSolverService,
		@IFemRunTracker private readonly runTracker: IFemRunTracker,
		@ILogService private readonly logService: ILogService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		this.runningKey = RunAllRunningContext.bindTo(contextKeyService);
	}

	get running(): boolean {
		return !!this.cancellation;
	}

	get lastOutcomes(): readonly IStepOutcome[] {
		return this._lastOutcomes;
	}

	cancel(): void {
		if (this.cancellation && !this.cancellation.token.isCancellationRequested) {
			this.cancellation.cancel();
			this.showStatus();
		}
	}

	async restartEngine(): Promise<void> {
		await this.solverService.restartBackend(this.python());
	}

	private python(): string {
		return this.instantiationService.createInstance(FemAnalysisRunner).resolvePython();
	}

	async run(): Promise<void> {
		const project = this.projectService.project;
		if (!project) {
			this.notificationService.info(localize('runAll.noProject', "Open a SAEngine project to run it."));
			return;
		}
		if (this.cancellation) {
			// A second Run All (F5, the palette) says what is going, and offers to stop it.
			const step = this.current ? RUN_ALL_STEPS[this.current.index] : undefined;
			this.notificationService.prompt(Severity.Info, step
				? localize('runAll.alreadyRunning', "Run All is already running: step {0} of {1} ({2}), {3} so far.", this.current!.index + 1, RUN_ALL_STEPS.length, step.label, formatDuration((Date.now() - this.runStarted) / 1000))
				: localize('runAll.alreadyRunningStart', "Run All is already running."), [{
					label: localize('runAll.stop', "Stop"),
					run: () => this.cancel(),
				}]);
			return;
		}
		const cancellation = this.cancellation = new CancellationTokenSource();
		this.runningKey.set(true);
		this.runStarted = Date.now();
		this.current = undefined;
		this.showStatus();
		this.ticker.cancelAndSet(() => this.showStatus(), 1000);
		const context: IRunContext = { project, model: partFile(project.root, 'fem'), token: cancellation.token };
		const outcomes: IStepOutcome[] = [];
		try {
			await this.saveSources(project);
			const blocked = new Map<StepId, StepId>(); // step -> the failed step it waits for
			for (const [index, step] of RUN_ALL_STEPS.entries()) {
				const waits = step.needs.map(n => blocked.get(n)).find(n => n !== undefined);
				if (cancellation.token.isCancellationRequested) {
					outcomes.push({ id: step.id, label: step.label, status: 'cancelled', message: localize('runAll.notRunStopped', "not run: Run All was stopped"), seconds: 0 });
					continue;
				}
				if (waits) {
					blocked.set(step.id, waits);
					outcomes.push({ id: step.id, label: step.label, status: 'notRun', message: localize('runAll.notRun', "not run: it needs the {0} step, which did not succeed", RUN_ALL_STEPS.find(s => s.id === waits)!.label), seconds: 0 });
					continue;
				}
				const started = Date.now();
				this.current = { index, started, backend: false };
				this.showStatus();
				let outcome: IStepOutcome;
				try {
					const result = await this.runStep(step.id, context);
					outcome = { id: step.id, label: step.label, ...result, seconds: (Date.now() - started) / 1000 };
				} catch (error) {
					const seconds = (Date.now() - started) / 1000;
					if (cancellation.token.isCancellationRequested && (isCancellationError(error) || error instanceof CancellationError)) {
						outcome = { id: step.id, label: step.label, status: 'cancelled', message: localize('runAll.stopped', "stopped (you pressed Stop)"), seconds };
					} else {
						outcome = { id: step.id, label: step.label, status: 'failed', message: error instanceof StepFailure ? error.message : errorSummary(error), seconds };
						blocked.set(step.id, step.id);
						await this.removeSummary(step.id, context);
					}
				}
				outcomes.push(outcome);
				this.logService.info(`[saengine] Run All step ${index + 1} ${step.id}: ${outcome.status} in ${outcome.seconds.toFixed(1)} s: ${outcome.message}`);
			}
		} catch (error) {
			// Saving the sources failed: nothing ran.
			outcomes.push({ id: 'bim', label: localize('runAll.save', "saving the project"), status: 'failed', message: errorSummary(error), seconds: 0 });
		} finally {
			this.ticker.cancel();
			cancellation.dispose();
			this.cancellation = undefined;
			this.current = undefined;
			this.runningKey.set(false);
			this.status?.dispose();
			this.status = undefined;
		}
		this._lastOutcomes = outcomes;
		const seconds = (Date.now() - this.runStarted) / 1000;
		this.logService.info(`[saengine] Run All took ${seconds.toFixed(1)} s`);
		this.showSummary(context, outcomes, seconds);
	}

	private runStep(id: StepId, context: IRunContext): Promise<IStepResult> {
		switch (id) {
			case 'bim': return this.buildBim(context);
			case 'derive': return this.derive(context);
			case 'analysis': return this.analyse(context);
			case 'ssi': return this.compareSoilSprings(context);
			case 'substructure': return this.designSubstructure(context);
			case 'design': return this.design(context);
			case 'mep': return this.checkMep(context);
			case 'boq': return this.measure(context);
			case 'report': return this.buildReport(context);
			case 'drawings': return this.drawings(context);
		}
	}

	/**
	 * Waits for `work`, a request the backend is working on; a Stop does not wait: it restarts
	 * the backend, so the work ends there too, and the step ends as stopped.
	 */
	private backend<T>(context: IRunContext, work: Promise<T>): Promise<T> {
		if (this.current) {
			this.current.backend = true;
		}
		const token = context.token;
		if (token.isCancellationRequested) {
			return Promise.reject(new CancellationError());
		}
		return new Promise<T>((resolve, reject) => {
			const listener = token.onCancellationRequested(() => {
				listener.dispose();
				void this.restartEngine();
				reject(new CancellationError());
			});
			work.then(value => {
				listener.dispose();
				if (this.current) {
					this.current.backend = false;
				}
				resolve(value);
			}, error => {
				listener.dispose();
				reject(error);
			});
		});
	}

	private check(token: CancellationToken): void {
		if (token.isCancellationRequested) {
			throw new CancellationError();
		}
	}

	/** One status bar entry: "Run All 6/10: design checks · 2:05", the detail and the steps so far in its tooltip. */
	private showStatus(): void {
		if (!this.cancellation) {
			return;
		}
		const now = Date.now();
		const stopping = this.cancellation.token.isCancellationRequested;
		const step = this.current ? RUN_ALL_STEPS[this.current.index] : undefined;
		const elapsed = formatDuration((now - (this.current?.started ?? this.runStarted)) / 1000);
		const text = stopping
			? localize('runAll.statusStopping', "Run All: stopping…")
			: step
				? localize('runAll.status', "Run All {0}/{1}: {2} · {3}", this.current!.index + 1, RUN_ALL_STEPS.length, step.label, elapsed)
				: localize('runAll.statusSaving', "Run All: saving the project");
		const lines = [text];
		if (this.current?.detail && !stopping) {
			lines.push(this.current.detail);
		}
		if (this.current?.backend && now - this.current.started > ENGINE_BUSY_MS && !stopping) {
			lines.push(localize('runAll.engineBusy', "The engine has been working on this for {0}. Stop ends it (the engine restarts).", elapsed));
		}
		lines.push(localize('runAll.total', "Total {0}.", formatDuration((now - this.runStarted) / 1000)));
		lines.push(localize('runAll.clickToStop', "Click to stop."));
		const entry = {
			name: localize('runAll.statusName', "Run All"),
			text: `$(sync~spin) ${this.current?.detail && !stopping ? `${text} · ${this.current.detail}` : text}`,
			ariaLabel: lines.join(' '),
			tooltip: lines.join('\n'),
			command: CANCEL_RUN_ALL_COMMAND_ID,
		};
		if (this.status) {
			this.status.update(entry);
		} else {
			this.status = this.statusbarService.addEntry(entry, STATUS_ENTRY_ID, StatusbarAlignment.LEFT, -100);
		}
	}

	private report(detail: string | undefined): void {
		if (this.current) {
			this.current.detail = detail;
			this.showStatus();
		}
	}

	/**
	 * Saves the project's edited part files: the steps read them from disk (the soil report too:
	 * the derivation takes the site class, and the footing design qa, from the saved file).
	 */
	private async saveSources(project: ISaengineProject): Promise<void> {
		const ids = [...new Set(['floorPlan', 'structure', ...DERIVATION_INPUTS, ...BOQ_SOURCES.map(s => s.part), 'substructure', 'soil', 'mep'])];
		for (const id of ids) {
			const part = partById(id);
			const file = part?.mainFile && joinPath(project.root, part.folder, part.mainFile);
			if (file && this.textFileService.isDirty(file)) {
				await this.textFileService.save(file);
			}
		}
	}

	/** The current text of each part in `ids`, by id (undefined when a file is missing). */
	private async readParts(project: ISaengineProject, ids: readonly string[]): Promise<Map<string, string | undefined>> {
		const texts = new Map<string, string | undefined>();
		for (const id of ids) {
			const part = partById(id);
			if (!part?.mainFile && id !== LOADS_DERIVATION_SOURCE.part && id !== ARCHITECTURE_DERIVATION_SOURCE.part) {
				texts.set(id, undefined);
				continue;
			}
			texts.set(id, await this.readText(part?.mainFile ? joinPath(project.root, part.folder, part.mainFile) : partFile(project.root, id)));
		}
		return texts;
	}

	private async readText(resource: URI): Promise<string | undefined> {
		try {
			return (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return undefined;
		}
	}

	/**
	 * Step 1 (G4): builds the building model from the floor plan (or the structural model) when it
	 * was never built or its source changed, through the text model as the building editor does.
	 * A building model without members stops here (G3): there is nothing to analyse.
	 */
	private async buildBim(context: IRunContext): Promise<IStepResult> {
		const { project } = context;
		const bim = partById('bim');
		const upstream = upstreamPart('bim', this.projectService.parts);
		if (!bim?.mainFile || !upstream) {
			throw new StepFailure(localize('runAll.noBimPart', "This project has no building model."));
		}
		const sourceName = upstream === 'structure' ? localize('runAll.structureModel', "5 Structural Model") : localize('runAll.floorPlan', "5 Floor Plan");
		const resource = joinPath(project.root, bim.folder, bim.mainFile);
		const texts = await this.readParts(project, [upstream, 'bim']);
		const source = texts.get(upstream);
		let text = texts.get('bim');
		if (source === undefined) {
			throw new StepFailure(localize('runAll.noBimSource', "{0} could not be read.", sourceName));
		}
		let document: unknown;
		try {
			document = text !== undefined ? JSON.parse(text) : undefined;
		} catch {
			document = undefined;
		}
		let result: IStepResult;
		if (recordedStamp(document, upstream) === sourceStamp(source)) {
			result = { status: 'skipped', message: localize('runAll.bimCurrent', "up to date") };
		} else {
			const generated = await this.backend(context, this.commandService.executeCommand<{ readonly text?: string; readonly problems?: readonly string[] }>(upstream === 'structure' ? BIM_GENERATE_FROM_STRUCTURE_COMMAND : BIM_GENERATE_COMMAND, source, text));
			if (!generated?.text) {
				throw new StepFailure(localize('runAll.bimProblems', "Fix the {0} first: {1}", sourceName, (generated?.problems ?? []).join('; ')));
			}
			await this.writeThroughModel(resource, generated.text);
			text = generated.text;
			result = { status: 'ok', message: localize('runAll.bimBuilt', "built from {0}", sourceName) };
		}
		const members = bimMembers(text);
		if (!members) {
			throw new StepFailure(localize('runAll.nothingToAnalyse', "Nothing to analyse: the building model has no members. Draw the grids, columns and beams in {0} first.", sourceName));
		}
		return { ...result, message: localize('runAll.bimMembers', "{0}; {1} elements", result.message, members) };
	}

	/** Replaces a part file's text through its text model (an open editor updates in place) and saves it. */
	private async writeThroughModel(resource: URI, text: string): Promise<void> {
		const reference: IReference<IResolvedTextEditorModel> = await this.textModelService.createModelReference(resource);
		try {
			const model = reference.object.textEditorModel;
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null);
			model.pushStackElement();
			await this.textFileService.save(resource);
		} finally {
			reference.dispose();
		}
	}

	/** Step 2: derives the analysis model when it is not derived yet or its sources changed. */
	private async derive(context: IRunContext): Promise<IStepResult> {
		const { project, token } = context;
		const texts = await this.readParts(project, DERIVATION_INPUTS);
		let description: unknown;
		try {
			const content = await this.fileService.readFile(partFile(project.root, 'fem'));
			description = JSON.parse(content.value.toString())?.meta?.description;
		} catch {
			description = undefined; // no model yet
		}
		const state = derivationState(description, texts);
		if (state.derived && !state.changed.length) {
			return { status: 'skipped', message: localize('runAll.modelCurrent', "up to date") };
		}
		this.check(token);
		const outcome = await this.backend(context, deriveAnalysisModel(this.commandService, this.fileService, project.root, texts));
		if (!outcome.ok) {
			throw new StepFailure(outcome.message);
		}
		return {
			status: 'ok',
			message: state.changed.length && state.derived
				? localize('runAll.derivedChanged', "{0} (changed: {1})", outcome.message, state.changed.join(', '))
				: outcome.message,
		};
	}

	/** The stamp of what the solver computes from now (undefined when the model cannot be read). */
	private async analysisStamp(model: URI): Promise<string | undefined> {
		const text = await this.readText(model);
		if (text === undefined) {
			return undefined;
		}
		const sides: [string, string | undefined][] = [];
		for (const name of [THERMAL_FILE, SSI_FILE, FACES_FILE]) {
			sides.push([name, await this.readText(joinPath(dirname(model), name))]);
		}
		return analysisInputsStamp(text, sides);
	}

	/**
	 * Step 3: runs every analysis case, unless the results were computed from the same model (X28,
	 * X19: a model derived again from a change the analysis does not take, such as bars or the
	 * engineer's name, keeps its results; the manifest is written again unchanged so the part list
	 * sees results as new as the model). Then the mesh convergence check, a warning at most.
	 */
	private async analyse(context: IRunContext): Promise<IStepResult> {
		const { model, token, project } = context;
		const results = resultsFolder(model);
		const stamp = await this.analysisStamp(model);
		const manifest = await this.readText(joinPath(results, RESULTS_MANIFEST));
		let kept: { stamp?: unknown; manifest?: unknown } | undefined;
		try {
			kept = JSON.parse((await this.readText(joinPath(results, ANALYSIS_INPUTS_FILE))) ?? 'null') ?? undefined;
		} catch {
			kept = undefined;
		}
		if (stamp && manifest !== undefined && kept?.stamp === stamp && kept.manifest === sourceStamp(manifest)) {
			await this.fileService.writeFile(joinPath(results, RESULTS_MANIFEST), VSBuffer.fromString(manifest));
			return { status: 'skipped', message: localize('runAll.resultsCurrent', "results current: the analysis model did not change") };
		}
		const runner = this.instantiationService.createInstance(FemAnalysisRunner);
		const run = () => runner.run(model, { quiet: true, token, onProgress: progress => this.report(progress.message) });
		let outcome: IFemRunOutcome = await run();
		if (outcome.status === 'busy') {
			// G7: a run of this model started elsewhere (the FEM view): wait for it, then run.
			this.report(localize('runAll.waitingForRun', "waiting for the analysis started in the FEM view"));
			while (this.runTracker.get(model)) {
				await Promise.race([Event.toPromise(this.runTracker.onDidChange), new Promise<void>(resolve => {
					const listener = token.onCancellationRequested(() => {
						listener.dispose();
						resolve();
					});
				})]);
				this.check(token);
			}
			outcome = await run();
		}
		if (outcome.status === 'cancelled') {
			if (token.isCancellationRequested) {
				throw new CancellationError();
			}
			// G7: not the engineer's Stop of Run All: say what stopped it.
			throw new StepFailure(localize('runAll.analysisStoppedElsewhere', "The analysis was stopped outside Run All (Stop in the FEM view)."));
		}
		if (outcome.status !== 'done') {
			context.analysisLog = outcome.status === 'failed';
			throw new StepFailure(outcome.message ?? outcome.status);
		}
		const done = await this.readText(joinPath(results, RESULTS_MANIFEST));
		if (stamp && done !== undefined) {
			await this.fileService.writeFile(joinPath(results, ANALYSIS_INPUTS_FILE), VSBuffer.fromString(JSON.stringify({ stamp, manifest: sourceStamp(done) }) + '\n'));
		}
		this.report(localize('runAll.meshCheck', "mesh check"));
		const mesh = await this.checkMesh(context, project);
		const message = localize('runAll.analysed', "{0} case(s) analysed", outcome.cases);
		return mesh ? { status: 'warning', message: `${message}; ${mesh}` } : { status: 'ok', message };
	}

	/**
	 * The mesh convergence check (`analysis.meshCheck`, `saengine.fem.mesh_check`): a warning
	 * when a beam's gravity end moment changes by more than 5 % on a mesh twice as coarse; never
	 * fails the step (mirrors `_analysis` of `saengine.pipeline.run_all`).
	 */
	private async checkMesh(context: IRunContext, project: ISaengineProject): Promise<string | undefined> {
		let result: IMeshCheck | undefined;
		try {
			result = await this.backend(context, this.commandService.executeCommand<IMeshCheck>(MESH_CHECK_COMMAND, { projectRoot: project.root.fsPath }));
		} catch (error) {
			if (context.token.isCancellationRequested) {
				throw error;
			}
			return localize('runAll.meshCheckFailed', "the mesh check could not be run: {0}", errorSummary(error));
		}
		return result?.warning
			? localize('runAll.meshWarning', "mesh not converged: the beams' gravity end moments change by up to {0} % on a mesh twice as coarse ({1} mm); make Mesh Size smaller in Project Settings, Analysis model", (result.maxChangePercent ?? 0).toFixed(1), result.coarseSize_mm ?? 0)
			: undefined;
	}

	/**
	 * Step 4: on soil springs (the model has `08 FEM/ssi.json`): derives and runs the fixed-base
	 * model the foundations are designed from, and compares the two (`08 FEM/ssi-compare.json`).
	 */
	private async compareSoilSprings(context: IRunContext): Promise<IStepResult> {
		const springs = joinPath(dirname(context.model), SSI_FILE);
		if (!await this.fileService.exists(springs)) {
			return { status: 'skipped', message: localize('runAll.noSprings', "the supports are not soil springs") };
		}
		await this.backend(context, this.commandService.executeCommand(SSI_COMPARE_COMMAND, { projectRoot: context.project.root.fsPath }));
		return { status: 'ok', message: localize('runAll.springsCompared', "fixed base compared with the soil springs") };
	}

	/**
	 * Step 5 (U3): designs the foundations of 9 Substructure (`saengine.substructure.run.
	 * design_foundations`): the building model's footings moved in while the file is the
	 * placeholder, the minimum mesh for foundations without bars (a warning names them), then the
	 * checks; writes the summary the part list shows.
	 */
	private async designSubstructure(context: IRunContext): Promise<IStepResult> {
		const { project } = context;
		const part = partById('substructure');
		if (!part?.mainFile) {
			return { status: 'skipped', message: localize('runAll.noSubstructure', "no substructure") };
		}
		const resource = joinPath(project.root, part.folder, part.mainFile);
		const request: ISubstructureRequest = { projectRoot: project.root.fsPath };
		const raw = record(await this.backend(context, this.solverService.substructureDesign(this.python(), request.projectRoot)));
		if (Array.isArray(raw.problems) && raw.problems.length && !Array.isArray(raw.foundations)) {
			throw new StepFailure(raw.problems.join(' '));
		}
		const text = await this.readText(resource);
		if (text === undefined) {
			return { status: 'skipped', message: localize('runAll.noSubstructureFile', "no substructure file") };
		}
		const parsed = parseSubstructure(text);
		if (parsed.kind === 'error') {
			throw new StepFailure(parsed.message);
		}
		if (parsed.kind === 'placeholder' || !parsed.document.foundations.length) {
			return { status: 'skipped', message: localize('runAll.noFoundations', "no foundations to design") };
		}
		const report = readSubstructureReport(raw);
		if (!report) {
			throw new StepFailure(localize('runAll.substructureUnavailable', "The foundation design is not available."));
		}
		const summary = substructureSummaryFile(parsed.document, report, new Date());
		await this.fileService.writeFile(joinPath(dirname(resource), SUBSTRUCTURE_SUMMARY_FILE), VSBuffer.fromString(JSON.stringify(summary, undefined, '\t') + '\n'));
		const added = record(raw.summary).barsAdded;
		const notes: string[] = [];
		if (Array.isArray(added) && added.length) {
			notes.push(localize('runAll.barsAdded', "minimum bars given to {0}: review them", added.join(', ')));
		}
		if (summary.status === 'incomplete') {
			notes.push(summary.unsupported.length
				? localize('runAll.foundationsIncomplete', "{0} of {1} checked; no foundation under {2}", summary.checked, summary.total, summary.unsupported.join(', '))
				: localize('runAll.foundationsPartly', "{0} of {1} checked", summary.checked, summary.total));
		}
		const message = localize('runAll.foundations', "{0} pass, {1} fail", summary.passed, summary.failed);
		return { status: notes.length ? 'warning' : 'ok', message: [message, ...notes].join('; '), failing: summary.failed };
	}

	/**
	 * Step 6: the design checks, then (design mode) the steel each element requires, kept beside
	 * the results (`design-required.json`). A run that checked nothing fails (G1): it is not
	 * "0 pass, 0 fail". Members of types without bars are named (X29). Mirrors `_design` of
	 * `saengine.pipeline.run_all`.
	 */
	private async design(context: IRunContext): Promise<IStepResult> {
		const { model } = context;
		const report = await this.backend(context, runDesign(this.commandService, model));
		if (!report?.summary) {
			throw new StepFailure(localize('runAll.designUnavailable', "The design checks are not available."));
		}
		const noBars = report.summary.noBars ?? [];
		context.noBars = noBars.length > 0;
		// The members alone: the totals also count the joints and the building's seismic checks.
		if (!(report.summary.elements?.checked ?? report.summary.checked)) {
			throw new StepFailure(noBars.length
				? localize('runAll.designNoBars', "The design checks checked nothing: the object types {0} have no bars (8 FEM, Design Reinforcement proposes them).", noBars.join(', '))
				: localize('runAll.designNothing', "The design checks checked nothing: {0}", report.notes.slice(0, 2).join(' ') || localize('runAll.designNothingWhy', "no member could be checked.")));
		}
		await writeDesignSummary(this.fileService, model, report);
		context.design = report;
		try {
			context.required = await this.backend(context, runDesignRequired(this.commandService, model));
		} catch (error) {
			if (context.token.isCancellationRequested) {
				throw error;
			}
			context.required = undefined; // the checks are the verdict
		}
		const short = shortElements(context.required).length;
		const tooSmall = tooSmallElements(context.required).length;
		const notes = [
			...(short ? [localize('runAll.steelShort', "steel short in {0} element(s)", short)] : []),
			...(tooSmall ? [localize('runAll.tooSmall', "{0} section(s) too small", tooSmall)] : []),
			...(noBars.length ? [localize('runAll.noBars', "not checked for want of bars: {0}", noBars.join(', '))] : []),
		];
		const message = localize('runAll.designChecks', "{0} pass, {1} fail", report.summary.passed, report.summary.failed);
		return { status: noBars.length ? 'warning' : 'ok', message: [message, ...notes].join('; '), failing: report.summary.failed };
	}

	/**
	 * Step 7: the MEP coordination of 7 MEP (equipment loads, openings, clashes) and its plumbing,
	 * HVAC, electrical and fire checks (openings still missing are reported, never added), with
	 * the summary the part list shows. Nothing to do while the MEP file is the placeholder or empty.
	 */
	private async checkMep(context: IRunContext): Promise<IStepResult> {
		const { project } = context;
		const part = partById('mep');
		if (!part?.mainFile) {
			return { status: 'skipped', message: localize('runAll.noMep', "no MEP") };
		}
		const resource = joinPath(project.root, part.folder, part.mainFile);
		const text = await this.readText(resource);
		if (text === undefined) {
			return { status: 'skipped', message: localize('runAll.noMepFile', "no MEP file") };
		}
		const parsed = parseMep(text);
		if (parsed.kind === 'error') {
			throw new StepFailure(parsed.message);
		}
		const document = parsed.document;
		const withPlumbing = hasPlumbing(document);
		const withHvac = hasHvac(document);
		const withElectrical = hasElectrical(document);
		const withFire = hasFire(document);
		if (parsed.kind === 'placeholder' || (!document.equipment.length && !document.openings.length && !document.shafts.length && !document.ifcModels.length && !withPlumbing && !withHvac && !withElectrical && !withFire)) {
			return { status: 'skipped', message: localize('runAll.mepEmpty', "nothing to check in 7 MEP") };
		}
		const texts = await this.readParts(project, MEP_SOURCE_PARTS);
		const request: IMepRequest = { projectRoot: project.root.fsPath, mepText: text };
		const report: IMepReport | undefined = readMepReport(await this.backend(context, this.commandService.executeCommand<unknown>(MEP_REPORT_COMMAND, request)));
		if (!report) {
			throw new StepFailure(localize('runAll.mepUnavailable', "The MEP coordination checks are not available."));
		}
		let plumbing: IPlumbingReport | undefined;
		if (withPlumbing) {
			plumbing = readPlumbingReport(await this.backend(context, this.commandService.executeCommand<unknown>(PLUMBING_REPORT_COMMAND, request)));
			if (!plumbing) {
				throw new StepFailure(localize('runAll.plumbingUnavailable', "The plumbing checks are not available."));
			}
			context.tanksDesigned = true;
		}
		// HVAC: its report never starts EnergyPlus; the loads are EnergyPlus's when Calculate Loads
		// ran for this input, else the estimate (said in the summary). Openings are reported, not added.
		const hvac = withHvac ? await this.serviceReport(context, HVAC_REPORT_COMMAND, request, readHvacReport, raw => openingsOf(record(raw).air), localize('runAll.hvacUnavailable', "The HVAC checks are not available.")) : undefined;
		const electrical = withElectrical ? await this.serviceReport(context, ELECTRICAL_REPORT_COMMAND, request, readElectricalReport, openingsOf, localize('runAll.electricalUnavailable', "The electrical checks are not available.")) : undefined;
		const fire = withFire ? await this.serviceReport(context, FIRE_REPORT_COMMAND, request, readFireReport, openingsOf, localize('runAll.fireUnavailable', "The fire checks are not available.")) : undefined;
		const sourceTexts: IMepContextTexts = Object.fromEntries(MEP_SOURCE_PARTS.map(id => [id, texts.get(id)]));
		const summary = {
			...mepSummaryFile(document, report, text, new Date(), sourceTexts),
			...(plumbing ? { plumbing: plumbingSummaryFile(document, plumbing) } : {}),
			...(hvac ? { hvac: hvacSummaryFile(document, hvac.report) } : {}),
			...(electrical ? { electrical: electricalSummaryFile(document, electrical.report) } : {}),
			...(fire ? { fire: fireSummaryFile(document, fire.report) } : {}),
		};
		await this.fileService.writeFile(joinPath(dirname(resource), MEP_SUMMARY_FILE), VSBuffer.fromString(JSON.stringify(summary, undefined, '\t') + '\n'));

		const failedOpenings = report.openings.filter(o => !o.ok).length;
		const openClashes = report.clashes.filter(isOpenClash).length;
		const plumbingFailed = plumbing ? plumbingFailures(plumbing) : undefined;
		const parts = [localize('runAll.mep', "failing openings {0}, open clashes {1}", failedOpenings, openClashes)];
		let failing = failedOpenings;
		if (plumbingFailed) {
			parts.push(localize('runAll.plumbing', "plumbing: failing checks {0}, floors below the minimum pressure {1}", plumbingFailed.items, plumbingFailed.floorsLow));
			failing += plumbingFailed.items + plumbingFailed.floorsLow;
		}
		const notes: string[] = [];
		if (hvac) {
			parts.push(localize('runAll.hvac', "HVAC: failing checks {0}, openings to add {1}", hvacFailures(hvac.report), hvac.missingOpenings));
			failing += hvacFailures(hvac.report);
			if (hvac.report.calculated === false) {
				notes.push(localize('runAll.hvacEstimate', "HVAC loads not calculated: run Calculate Loads"));
			}
		}
		if (electrical) {
			parts.push(localize('runAll.electrical', "electrical: failing checks {0}, openings to add {1}", electricalFailures(electrical.report), electrical.missingOpenings));
			failing += electricalFailures(electrical.report);
		}
		if (fire) {
			parts.push(localize('runAll.fire', "fire: failing checks {0}, sleeves to add {1}", fireFailures(fire.report), fire.missingOpenings));
			failing += fireFailures(fire.report);
		}
		return { status: notes.length || openClashes ? 'warning' : 'ok', message: [...parts, ...notes].join('; '), failing };
	}

	/** A discipline's report of 7 MEP by its command, read, with the openings it still needs; a step failure when it is not available. */
	private async serviceReport<T>(context: IRunContext, command: string, request: IMepRequest, read: (raw: unknown) => T | undefined, missing: (raw: unknown) => number, unavailable: string): Promise<IServiceCheck<T>> {
		const raw = await this.backend(context, this.commandService.executeCommand<unknown>(command, request));
		const report = read(raw);
		if (!report) {
			throw new StepFailure(unavailable);
		}
		return { report, missingOpenings: missing(raw) };
	}

	/**
	 * Step 8: measures the bill of quantities when it is not measured yet or its sources changed,
	 * or when the plumbing report has just designed the tanks and the bill still waits for a
	 * tank's design to measure its bars.
	 */
	private async measure(context: IRunContext): Promise<IStepResult> {
		const { project, token } = context;
		const boq = partById('boq');
		if (!boq?.mainFile) {
			return { status: 'skipped', message: localize('runAll.noBoq', "no bill of quantities") };
		}
		const texts = await this.readParts(project, BOQ_SOURCES.map(s => s.part));
		const resource = joinPath(project.root, boq.folder, boq.mainFile);
		// Through the text model, as the bill's editor does: an open bill updates in place.
		let reference: IReference<IResolvedTextEditorModel>;
		try {
			reference = await this.textModelService.createModelReference(resource);
		} catch (error) {
			throw new StepFailure(localize('runAll.boqUnreadable', "The bill of quantities could not be read: {0}", errorSummary(error)));
		}
		try {
			const model = reference.object.textEditorModel;
			const current = parseBoq(model.getValue());
			if (!changedSources(current, texts).length && !(context.tanksDesigned && awaitsTankDesigns(current))) {
				return { status: 'skipped', message: localize('runAll.boqCurrent', "up to date") };
			}
			const { args, missing } = boqComputeArgs(texts, project.root.fsPath);
			if (!args) {
				throw new StepFailure(localize('runAll.boqMissing', "{0} could not be read.", missing.join(', ')));
			}
			this.check(token);
			const result = await this.backend(context, this.commandService.executeCommand<IBoqComputeResult>(BOQ_COMPUTE_COMMAND, args));
			if (!result?.text) {
				throw new StepFailure((result?.problems ?? []).join('; ') || localize('runAll.boqFailed', "The bill could not be measured."));
			}
			this.check(token);
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: result.text }], () => null);
			model.pushStackElement();
			await this.textFileService.save(resource);
			return { status: 'ok', message: localize('runAll.boqUpdated', "measured") };
		} finally {
			reference.dispose();
		}
	}

	/** Step 9: the design report (`11 Exports/report.pdf`). */
	private async buildReport(context: IRunContext): Promise<IStepResult> {
		const request: IReportBuildRequest = { projectRoot: context.project.root.fsPath };
		const result = await this.backend(context, this.commandService.executeCommand<IReportBuildResult>(BUILD_REPORT_COMMAND_ID, request));
		const problems = reportProblems(result);
		if (problems.length || !result?.path) {
			throw new StepFailure(problems.join(' ') || localize('runAll.reportFailed', "The report could not be built."));
		}
		context.pdf = URI.file(result.path);
		const { message, warning } = reportStepMessage(result);
		return { status: warning ? 'warning' : 'ok', message };
	}

	/**
	 * Step 10: draws the drawings again when a set was generated before and is out of date, with
	 * the design checks just made (the backend need not run them again). The first set is started
	 * from 11 Exports.
	 */
	private async drawings(context: IRunContext): Promise<IStepResult> {
		const { project } = context;
		const current = readDrawingSet(await this.backend(context, this.commandService.executeCommand<unknown>(DRAWINGS_LIST_COMMAND, { projectRoot: project.root.fsPath })), project.root);
		if (!current?.sheets.length) {
			return { status: 'skipped', message: localize('runAll.drawingsNone', "not generated yet: generate the first set in 11 Exports, Drawings") };
		}
		if (!current.stale) {
			return { status: 'skipped', message: localize('runAll.drawingsCurrent', "up to date") };
		}
		const answer = readDrawingSet(await this.backend(context, this.commandService.executeCommand<unknown>(DRAWINGS_GENERATE_COMMAND, { projectRoot: project.root.fsPath, designReportText: JSON.stringify(context.design) })), project.root);
		if (!answer?.sheets.length) {
			throw new StepFailure(answer?.problems.join(' ') || localize('runAll.drawingsFailed', "The drawings could not be generated."));
		}
		return { status: 'ok', message: localize('runAll.drawingsDrawn', "{0} sheets drawn", answer.sheets.length) };
	}

	/**
	 * After a failed step, removes the summary it would have written: the part list must not
	 * show the previous run's verdict as the current one (G1).
	 */
	private async removeSummary(id: StepId, { project, model }: IRunContext): Promise<void> {
		const target = id === 'design' ? joinPath(resultsFolder(model), DESIGN_SUMMARY_FILE)
			: id === 'substructure' && partById('substructure')?.folder ? joinPath(project.root, partById('substructure')!.folder, SUBSTRUCTURE_SUMMARY_FILE)
				: id === 'mep' && partById('mep')?.folder ? joinPath(project.root, partById('mep')!.folder, MEP_SUMMARY_FILE)
					: undefined;
		if (target && await this.fileService.exists(target)) {
			try {
				await this.fileService.del(target);
			} catch (error) {
				this.logService.warn(`[saengine] Run All could not remove ${target.fsPath}: ${errorSummary(error)}`);
			}
		}
	}

	/**
	 * The end of a run (G1, G17): one notification whose severity says how it went (error: a step
	 * failed; warning: checks fail or a step warned; information: all done, or stopped), with short
	 * counts and the steps one click away. It never switches the editor (G6): Show Results does.
	 */
	private showSummary(context: IRunContext, outcomes: readonly IStepOutcome[], seconds: number): void {
		const severity = runSeverity(outcomes);
		const failed = outcomes.filter(o => o.status === 'failed');
		const notRun = outcomes.filter(o => o.status === 'notRun').length;
		const cancelled = outcomes.find(o => o.status === 'cancelled');
		const time = formatDuration(seconds);
		let message: string;
		if (failed.length) {
			const first = failed[0];
			message = localize('runAll.failedSummary', "Run All: step {0} of {1} ({2}) failed: {3}", RUN_ALL_STEPS.findIndex(s => s.id === first.id) + 1, RUN_ALL_STEPS.length, first.label, first.message);
			if (failed.length > 1) {
				message += ' ' + localize('runAll.moreFailed', "{0} more step(s) failed.", failed.length - 1);
			}
			if (notRun) {
				message += ' ' + localize('runAll.notRunCount', "{0} step(s) not run.", notRun);
			}
		} else if (cancelled) {
			message = localize('runAll.cancelled', "Run All stopped at step {0} of {1} ({2}) after {3}.", RUN_ALL_STEPS.findIndex(s => s.id === cancelled.id) + 1, RUN_ALL_STEPS.length, cancelled.label, time);
		} else {
			const counts: string[] = [];
			const of = (id: StepId) => outcomes.find(o => o.id === id && (o.status === 'ok' || o.status === 'warning'));
			const design = of('design');
			if (design && context.design) {
				counts.push(localize('runAll.short.design', "design {0} pass, {1} fail", context.design.summary.passed, context.design.summary.failed));
			}
			const foundations = of('substructure');
			if (foundations) {
				counts.push(localize('runAll.short.foundations', "foundations {0} fail", foundations.failing ?? 0));
			}
			const mep = of('mep');
			if (mep?.failing) {
				counts.push(localize('runAll.short.mep', "MEP {0} fail", mep.failing));
			}
			const warnings = outcomes.filter(o => o.status === 'warning').length;
			if (warnings) {
				counts.push(localize('runAll.short.warnings', "{0} step(s) with notes", warnings));
			}
			message = localize('runAll.done', "Run All done in {0}: {1}", time, counts.join(' · ') || localize('runAll.short.allCurrent', "everything up to date"));
		}
		const choices: IPromptChoice[] = [{
			label: localize('runAll.showSteps', "Show Steps"),
			run: () => this.showSteps(outcomes, seconds),
		}];
		// Types without bars: the proposal is one click away (the engineer accepts the bars; Run All never writes them).
		if (context.noBars) {
			choices.push({ label: localize('runAll.designReinforcement', "Design Reinforcement"), run: () => this.commandService.executeCommand(DESIGN_REINFORCEMENT_COMMAND, context.model) });
		}
		if (context.analysisLog) {
			choices.push({ label: localize('runAll.showLog', "Show Log"), run: () => this.instantiationService.createInstance(FemAnalysisRunner).showLog() });
		}
		if (outcomes.some(o => (o.id === 'analysis' || o.id === 'design') && (o.status === 'ok' || o.status === 'warning' || o.status === 'skipped'))) {
			choices.push({ label: localize('runAll.showResults', "Show Results"), run: () => this.showResults(context.model) });
		}
		const pdf = context.pdf;
		if (pdf) {
			choices.push({ label: localize('runAll.openReport', "Open Report"), run: () => this.openerService.open(pdf, { openExternal: true }) });
		}
		this.notificationService.prompt(severity, message, choices, { sticky: severity !== Severity.Info });
	}

	/** Every step of the run, how it ended and how long it took. */
	private async showSteps(outcomes: readonly IStepOutcome[], seconds: number): Promise<void> {
		await this.dialogService.info(
			localize('runAll.stepsTitle', "Run All: {0} in total", formatDuration(seconds)),
			outcomes.map((o, i) => outcomeLine(o, i)).join('\n'),
		);
	}

	/** Opens the analysis model's results in the 3D view (the FEM editor picks a design combination). */
	private async showResults(model: URI): Promise<void> {
		try {
			await this.editorService.openEditor(new FemModelEditorInput(model), { pinned: true });
		} catch {
			// The summary still says what was done; the results are in 8 FEM.
		}
	}
}
