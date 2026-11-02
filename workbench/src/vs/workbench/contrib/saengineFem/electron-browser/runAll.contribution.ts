/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IntervalTimer, RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IEngineBusy, IEngineJob, IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
import { ISaenginePartStatusService } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { FEM_RESULT_TABLES_COMMAND, FEM_RUN_CASES_COMMAND, FEM_SHOW_LOG_COMMAND, IFemRunOptions } from '../browser/femResultsBar.js';
import { FemAnalysisRunner } from './femAnalysisRunner.js';
import { CANCEL_RUN_ALL_COMMAND_ID, IRunAllService, RESTART_ENGINE_COMMAND_ID, RUN_ALL_COMMAND_ID, RunAllRunningContext, RunAllService } from './runAll.js';

const category = localize2('saengine.category', "SAEngine");

/** Set by the SAEngine model contribution while a project is open. */
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

registerSingleton(IRunAllService, RunAllService, InstantiationType.Delayed);

/**
 * Runs the analysis of a model with the progress reported to the caller (the FEM editor's
 * toolbar and status line). Internal: the FEM editor calls it by id.
 */
CommandsRegistry.registerCommand(FEM_RUN_CASES_COMMAND, async (accessor, model: URI, options?: IFemRunOptions) => {
	const runner = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner);
	const runAll = accessor.get(IRunAllService);
	// N-X9: an out-of-date model is derived first, so the run solves what the parts say now.
	options?.onProgress?.({ fraction: 0, message: localize('femRun.deriving', "Deriving the analysis model") });
	const derived = await runAll.deriveIfStale(model);
	if (!derived.ok) {
		return { status: 'invalid' as const, cases: 0, message: localize('femRun.deriveFailed', "The analysis model could not be derived again: {0}", derived.message ?? '') };
	}
	return runner.run(model, options);
});

/** The result tables of a model's last run. Internal: the FEM editor's tables panel calls it by id. */
CommandsRegistry.registerCommand(FEM_RESULT_TABLES_COMMAND, (accessor, model: URI) =>
	accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resultTables(model));

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CANCEL_RUN_ALL_COMMAND_ID,
			title: localize2('runAll.stop', "Stop Run All"),
			category,
			icon: Codicon.debugStop,
			f1: true,
			precondition: RunAllRunningContext,
		});
	}

	override run(accessor: ServicesAccessor): void {
		accessor.get(IRunAllService).cancel();
	}
});

// While Run All runs, the title bar's Run All becomes Stop (G6).
MenuRegistry.appendMenuItem(MenuId.TitleBar, {
	command: {
		id: CANCEL_RUN_ALL_COMMAND_ID,
		title: localize2('runAll.stopShort', "Stop"),
		tooltip: localize('runAll.stopTooltip', "Stop Run All (the step going is stopped; the engine restarts when it is working on it)"),
		icon: Codicon.debugStop,
	},
	when: ContextKeyExpr.and(projectOpen, RunAllRunningContext),
	group: 'navigation',
	order: -1,
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: RESTART_ENGINE_COMMAND_ID,
			title: localize2('restartEngine', "Restart Engine"),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const runAll = accessor.get(IRunAllService);
		const notificationService = accessor.get(INotificationService);
		if (runAll.running) {
			runAll.cancel(); // its step's work ends with the engine
		}
		await runAll.restartEngine();
		notificationService.info(localize('restartEngine.done', "The SAEngine engine was stopped; it starts again with the next request."));
	}
});

/** The model of the active editor, or the one given. */
function modelOf(accessor: ServicesAccessor, resource: unknown): URI | undefined {
	const model = URI.isUri(resource) ? resource : EditorResourceAccessor.getOriginalUri(accessor.get(IEditorService).activeEditor);
	return model?.path.toLowerCase().endsWith('.osmodel') ? model : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.fem.runSelectedCases',
			title: localize2('femRunSelectedCases', "Run Selected Analysis Cases..."),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor, resource?: URI): Promise<void> {
		const notificationService = accessor.get(INotificationService);
		const runner = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner);
		const model = modelOf(accessor, resource);
		if (!model) {
			notificationService.info(localize('femRunSelectedCases.noModel', "Open an .osmodel file to run its analysis."));
			return;
		}
		await runner.run(model, { pick: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: FEM_SHOW_LOG_COMMAND,
			title: localize2('femShowLog', "Show Analysis Log"),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).showLog();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: RUN_ALL_COMMAND_ID,
			title: localize2('runAll', "Run All"),
			category,
			icon: Codicon.runAll,
			f1: true,
			precondition: projectOpen,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IRunAllService).run();
	}
});

/** After this long on one request the status bar says the engine is busy (N-G3). */
const ENGINE_BUSY_STATUS_MS = 10_000;
/** How often the watchdog asks a busy engine what it is doing. */
const ENGINE_JOBS_POLL_MS = 5_000;
/** How long the engine has to answer that question. */
const ENGINE_JOBS_TIMEOUT_MS = 4_000;
/** After this long without an answer while busy, it offers Restart Engine. */
const ENGINE_UNRESPONSIVE_MS = 90_000;

/**
 * The engine watchdog (N-G3 of usability walk 2, B10-21 of walk 3): a backend request that takes
 * long shows "Engine working 12 s: design checks" in the status bar, with what each request is
 * doing (`saengine/jobs`, answered by the engine's own thread while workers compute). An engine
 * that is working is not hung: Restart Engine is offered only when it has not answered for
 * {@link ENGINE_UNRESPONSIVE_MS} (the status entry's click restarts it at any time).
 */
class EngineWatchdog extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.engineWatchdog';

	private busy: IEngineBusy = { pending: 0 };
	private readonly ticker = this._register(new IntervalTimer());
	private readonly entry = this._register(new MutableDisposable<IStatusbarEntryAccessor>());
	/** The busy period a restart was already offered for (by the oldest request's start). */
	private offeredFor: number | undefined;
	/** What the engine said it works on last, and when it last answered [ms since the epoch]. */
	private jobs: readonly IEngineJob[] | undefined;
	private answered: number | undefined;
	private polling = false;
	private lastPoll = 0;
	private python: string | undefined;

	constructor(
		@IFemSolverService private readonly solverService: IFemSolverService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@INotificationService private readonly notificationService: INotificationService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super();
		this._register(solverService.onDidChangeBusy(busy => {
			this.busy = busy;
			if (busy.since === undefined) {
				this.ticker.cancel();
				this.entry.clear();
				this.jobs = this.answered = undefined;
			} else {
				this.ticker.cancelAndSet(() => this.update(), 1000);
			}
			this.update();
		}));
	}

	private update(): void {
		const since = this.busy.since;
		const elapsed = since === undefined ? 0 : Date.now() - since;
		if (since === undefined || elapsed < ENGINE_BUSY_STATUS_MS) {
			this.entry.clear();
			return;
		}
		this.poll(since);
		const seconds = Math.round(elapsed / 1000);
		const oldest = this.jobs?.[0];
		const doing = oldest?.note ?? describeEngineMethod(oldest?.method ?? this.busy.method);
		const text = localize('engineBusy.working', "Engine working {0}: {1}", formatSeconds(seconds), doing);
		const silent = this.answered === undefined ? elapsed : Date.now() - this.answered;
		const lines = (this.jobs ?? []).map(job => localize('engineBusy.job', "{0}, {1}: {2}", describeEngineMethod(job.method), formatSeconds(Math.round(job.seconds)), job.note ?? localize('engineBusy.noNote', "working")));
		const tooltip = [
			silent >= ENGINE_JOBS_POLL_MS * 3
				? localize('engineBusy.notAnswering', "The engine has not answered for {0} s.", Math.round(silent / 1000))
				: localize('engineBusy.answering', "The engine is working and answering; long design checks take minutes on a large building."),
			...lines,
			localize('engineBusy.clickRestart', "Click to restart the engine: its requests are stopped and the next one starts a new engine."),
		].join('\n');
		const entry = { name: localize('engineBusy.name', "Engine busy"), text: `$(loading~spin) ${text}`, ariaLabel: text, tooltip, command: RESTART_ENGINE_COMMAND_ID, kind: 'standard' as const };
		if (this.entry.value) {
			this.entry.value.update(entry);
		} else {
			this.entry.value = this.statusbarService.addEntry(entry, 'saengine.engineBusy', StatusbarAlignment.LEFT, -101);
		}
		// A working engine is not hung (B10-21: a restart offered during a normal 40-minute run):
		// a restart is offered only when it stopped answering.
		if (silent >= ENGINE_UNRESPONSIVE_MS && this.offeredFor !== since) {
			this.offeredFor = since;
			this.notificationService.prompt(Severity.Warning, localize('engineBusy.unresponsive', "The engine has not answered for {0} s ({1}). If it stays so, restart it: its requests are stopped and the next one starts a new engine.", Math.round(silent / 1000), describeEngineMethod(this.busy.method)), [{
				label: localize('engineBusy.restart', "Restart Engine"),
				run: () => this.commandService.executeCommand(RESTART_ENGINE_COMMAND_ID),
			}], { sticky: false });
		}
	}

	/** Asks the engine what it works on, every few seconds while it is busy. */
	private poll(since: number): void {
		if (this.polling || Date.now() - this.lastPoll < ENGINE_JOBS_POLL_MS) {
			return;
		}
		this.polling = true;
		this.lastPoll = Date.now();
		this.python ??= this.instantiationService.createInstance(FemAnalysisRunner).resolvePython();
		this.solverService.engineJobs(this.python, ENGINE_JOBS_TIMEOUT_MS).then(jobs => {
			if (jobs && this.busy.since === since) {
				this.jobs = jobs;
				this.answered = Date.now();
			}
		}, () => undefined).finally(() => this.polling = false);
	}
}

registerWorkbenchContribution2(EngineWatchdog.ID, EngineWatchdog, WorkbenchPhase.AfterRestored);

/** "2:05" from seconds. */
function formatSeconds(seconds: number): string {
	const minutes = Math.floor(seconds / 60);
	return minutes ? `${minutes}:${String(seconds % 60).padStart(2, '0')}` : localize('engineBusy.seconds', "{0} s", seconds);
}

/** What a backend method does, for the engine's status ("design/report" -> "design checks"). */
function describeEngineMethod(method: string | undefined): string {
	switch (method) {
		case 'design/report': return localize('engineBusy.method.report', "design checks");
		case 'design/required': return localize('engineBusy.method.required', "required steel");
		case 'design/proposal': return localize('engineBusy.method.proposal', "proposing bars");
		case 'fem/columnInteraction': return localize('engineBusy.method.interaction', "interaction diagrams");
		case 'report/build': return localize('engineBusy.method.buildReport', "printing the report");
		case 'drawings/generate': return localize('engineBusy.method.drawings', "drawings");
		case 'substructure/design': return localize('engineBusy.method.foundations', "foundation design");
		case 'fem/derive': return localize('engineBusy.method.derive', "deriving the analysis model");
		default: return method ?? localize('engineBusy.method.unknown', "a request");
	}
}

/** How long the part statuses settle before the background MEP check runs [ms]. */
const MEP_CHECK_DELAY = 3_000;

/**
 * N-E7: when 7 MEP has services that were never checked (or changed since), checks them in the
 * background, once per saved MEP text, so the part list says what fails without a visit to the
 * Coordination page. Never while Run All runs (its MEP step does the same).
 */
class MepBackgroundCheck extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.mepBackgroundCheck';

	private readonly scheduler = this._register(new RunOnceScheduler(() => void this.check(), MEP_CHECK_DELAY));
	/** The MEP status text a check was already made for (with the project), so a failing check is not repeated. */
	private checkedFor: string | undefined;

	constructor(
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IRunAllService private readonly runAll: IRunAllService,
		@IFileService private readonly fileService: IFileService,
	) {
		super();
		this._register(statusService.onDidChange(() => this.scheduler.schedule()));
		this.scheduler.schedule();
	}

	private async check(): Promise<void> {
		const status = this.statusService.statusOf('mep');
		const project = this.projectService.project;
		const part = partById('mep');
		// "not checked", "plumbing not checked", ...: in progress without a current summary.
		if (!project || !part?.mainFile || this.runAll.running || status?.state !== 'inProgress' || !/not checked/.test(status.text)) {
			return;
		}
		let text: string;
		try {
			text = (await this.fileService.readFile(joinPath(project.root, part.folder, part.mainFile))).value.toString();
		} catch {
			return;
		}
		const key = `${project.root.toString()}|${text}`;
		if (key === this.checkedFor) {
			return;
		}
		this.checkedFor = key;
		await this.runAll.checkMepInBackground();
	}
}

registerWorkbenchContribution2(MepBackgroundCheck.ID, MepBackgroundCheck, WorkbenchPhase.Eventually);
