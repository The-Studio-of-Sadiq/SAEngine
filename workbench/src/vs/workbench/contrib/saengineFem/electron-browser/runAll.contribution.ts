/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IntervalTimer } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IEngineBusy, IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
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
/** After this long it offers Restart Engine. */
const ENGINE_BUSY_RESTART_MS = 60_000;

/**
 * The engine watchdog (N-G3 of usability walk 2): a backend request that takes long shows "Engine
 * busy 12 s" in the status bar (click: Restart Engine), and after a minute one notification
 * offers Restart Engine. While Run All runs its own status entry says the same, so only the
 * status bar entry shows.
 */
class EngineWatchdog extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.engineWatchdog';

	private busy: IEngineBusy = { pending: 0 };
	private readonly ticker = this._register(new IntervalTimer());
	private readonly entry = this._register(new MutableDisposable<IStatusbarEntryAccessor>());
	/** The busy period a restart was already offered for (by the oldest request's start). */
	private offeredFor: number | undefined;

	constructor(
		@IFemSolverService solverService: IFemSolverService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@INotificationService private readonly notificationService: INotificationService,
		@ICommandService private readonly commandService: ICommandService,
		@IRunAllService private readonly runAll: IRunAllService,
	) {
		super();
		this._register(solverService.onDidChangeBusy(busy => {
			this.busy = busy;
			if (busy.since === undefined) {
				this.ticker.cancel();
				this.entry.clear();
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
		const seconds = Math.round(elapsed / 1000);
		const text = localize('engineBusy.status', "Engine busy {0} s", seconds);
		const tooltip = localize('engineBusy.tooltip', "The SAEngine engine has been working on one request ({0}) for {1} s. Click to restart it: the request is stopped and the next one starts a new engine.", this.busy.method ?? '?', seconds);
		const entry = { name: localize('engineBusy.name', "Engine busy"), text: `$(loading~spin) ${text}`, ariaLabel: text, tooltip, command: RESTART_ENGINE_COMMAND_ID, kind: 'warning' as const };
		if (this.entry.value) {
			this.entry.value.update(entry);
		} else {
			this.entry.value = this.statusbarService.addEntry(entry, 'saengine.engineBusy', StatusbarAlignment.LEFT, -101);
		}
		if (elapsed >= ENGINE_BUSY_RESTART_MS && this.offeredFor !== since && !this.runAll.running) {
			this.offeredFor = since;
			this.notificationService.prompt(Severity.Warning, localize('engineBusy.prompt', "The engine has been busy for {0} s ({1}). If the app no longer responds, restart the engine: the request is stopped and the next one starts a new engine.", seconds, this.busy.method ?? '?'), [{
				label: localize('engineBusy.restart', "Restart Engine"),
				run: () => this.commandService.executeCommand(RESTART_ENGINE_COMMAND_ID),
			}], { sticky: false });
		}
	}
}

registerWorkbenchContribution2(EngineWatchdog.ID, EngineWatchdog, WorkbenchPhase.AfterRestored);
