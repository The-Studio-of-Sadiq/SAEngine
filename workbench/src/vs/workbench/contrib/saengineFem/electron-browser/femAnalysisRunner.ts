/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { DeferredPromise } from '../../../../base/common/async.js';
import { CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { join } from '../../../../base/common/path.js';
import { isWindows } from '../../../../base/common/platform.js';
import { basename, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { FemRunEvent, FemRunExitCode, IFemCaseResults, IFemResultTable, IFemRunExit, IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { formatCell } from '../browser/femChartData.js';
import { resultsFolder } from '../browser/femDesign.js';
import { errorSummary, IFemRunOptions, IFemRunOutcome, IFemRunTracker } from '../browser/femResultsBar.js';
import { INativeWorkbenchEnvironmentService } from '../../../services/environment/electron-browser/environmentService.js';
import { IOutputService } from '../../../services/output/common/output.js';

export const FEM_OUTPUT_CHANNEL_ID = 'saengine.fem.analysis';
export const FEM_PYTHON_SETTING = 'saengine.python.path';

/** How many rows of each result table the output summary prints. */
const MAX_SUMMARY_ROWS = 12;

interface ICasePick extends IQuickPickItem {
	readonly caseId: number;
}

/**
 * Runs the analysis cases of one `.osmodel` file: validates the model, runs all its cases (or
 * those picked), reports progress quietly (to the caller, or the status bar) and logs the solver
 * output and the result tables to the "SAEngine Analysis" output channel, which opens only on
 * request ("Show Log"). Only a failure notifies.
 */
export class FemAnalysisRunner {

	constructor(
		@IFemSolverService private readonly solverService: IFemSolverService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@INativeWorkbenchEnvironmentService private readonly environmentService: INativeWorkbenchEnvironmentService,
		@IFileService private readonly fileService: IFileService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProgressService private readonly progressService: IProgressService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@IOutputService private readonly outputService: IOutputService,
		@ICommandService private readonly commandService: ICommandService,
		@IFemRunTracker private readonly runTracker: IFemRunTracker,
	) { }

	/**
	 * The interpreter set in `saengine.python.path`; else, in an installed build, the Python
	 * bundled by the installer at `<install>/resources/python` (the app root is
	 * `<install>/resources/app`); else, running from sources, the repository `.venv` next to the
	 * workbench folder. The renderer cannot check files, so the layout decides: an installed
	 * build always carries its bundled Python (scripts/build-installer.ps1).
	 */
	resolvePython(): string {
		const configured = this.configurationService.getValue<string>(FEM_PYTHON_SETTING)?.trim();
		if (configured) {
			return configured;
		}
		if (this.environmentService.isBuilt) {
			const bundled = join(this.environmentService.appRoot, '..', 'python');
			return isWindows ? join(bundled, 'python.exe') : join(bundled, 'bin', 'python3');
		}
		const venv = join(this.environmentService.appRoot, '..', '.venv');
		return isWindows ? join(venv, 'Scripts', 'python.exe') : join(venv, 'bin', 'python');
	}

	async checkRuntime(): Promise<void> {
		const python = this.resolvePython();
		try {
			const info = await this.solverService.getBackendInfo(python);
			this.notificationService.info(localize('femRuntime.ok', "SAEngine backend ready: Python {0}, OpenSeesPy {1}, opensees-studio {2} ({3}).", info.python, info.openseespy ?? '?', info.openseesStudio ?? '?', python));
		} catch (error) {
			this.reportBackendError(python, error);
		}
	}

	/** The result tables of `model`'s last run, for the FEM editor's tables panel and export. */
	resultTables(model: URI): Promise<readonly IFemCaseResults[]> {
		return this.solverService.getResultTables(this.resolvePython(), resultsFolder(model).fsPath, model.fsPath);
	}

	/** Opens the output channel holding the log of the last run. */
	async showLog(): Promise<void> {
		await this.outputService.showChannel(FEM_OUTPUT_CHANNEL_ID);
	}

	/**
	 * Runs the analysis of `model`: all its cases, or those picked when `options.pick`. One run per
	 * model at a time: while one goes (from the editor, the palette or Run All), another returns
	 * `busy` without touching the results.
	 */
	async run(model: URI, options: IFemRunOptions = {}): Promise<IFemRunOutcome> {
		const cancellation = new CancellationTokenSource(options.token);
		const tracked = this.runTracker.begin(model, () => cancellation.cancel());
		if (!tracked) {
			cancellation.dispose();
			const message = localize('femRun.busy', "The analysis of this model is already running.");
			if (!options.quiet) {
				this.notificationService.info(message);
			}
			return { status: 'busy', cases: 0, message };
		}
		try {
			const onProgress = options.onProgress;
			return await this.runTracked(model, {
				...options,
				token: cancellation.token,
				onProgress: progress => {
					tracked.report(progress);
					onProgress?.(progress);
				},
			}, !!onProgress);
		} finally {
			tracked.dispose();
			cancellation.dispose();
		}
	}

	private async runTracked(model: URI, options: IFemRunOptions, callerShowsProgress: boolean): Promise<IFemRunOutcome> {
		const python = this.resolvePython();
		const projectPath = model.fsPath;

		let validation;
		try {
			validation = await this.solverService.validateProject(python, projectPath);
		} catch (error) {
			if (!options.quiet) {
				this.reportBackendError(python, error);
			}
			return { status: 'unavailable', cases: 0, message: errorSummary(error) };
		}
		if (!validation.ok || !validation.summary) {
			const message = localize('femRun.invalid', "The model cannot be analyzed: {0}", validation.errors.join('; '));
			if (!options.quiet) {
				this.notificationService.error(message);
			}
			return { status: 'invalid', cases: 0, message };
		}
		if (!validation.summary.analyses.length) {
			const message = localize('femRun.noCases', "The model defines no analysis cases.");
			if (!options.quiet) {
				this.notificationService.info(message);
			}
			return { status: 'empty', cases: 0, message };
		}

		let caseIds = validation.summary.analyses.map(c => c.id);
		if (options.pick) {
			const picks: ICasePick[] = validation.summary.analyses.map(c => ({
				caseId: c.id,
				label: c.name,
				description: caseTypeLabel(c.type),
				picked: true,
			}));
			const selected = await this.quickInputService.pick(picks, {
				canPickMany: true,
				title: localize('femRun.pickTitle', "Run Selected Cases"),
				placeHolder: localize('femRun.pickPlaceholder', "Select the analysis cases to run"),
			});
			if (!selected?.length) {
				return { status: 'cancelled', cases: 0 };
			}
			caseIds = selected.map(s => s.caseId);
		}
		if (options.token?.isCancellationRequested) {
			return { status: 'cancelled', cases: 0 };
		}

		const outDir = resultsFolder(model);
		await this.clearPreviousResults(outDir);

		const output = this.outputService.getChannel(FEM_OUTPUT_CHANNEL_ID);
		// replace() rather than clear(): clear() resets asynchronously and would also drop the lines appended right after it.
		output?.replace(localize('femRun.header', "Analyzing {0} ({1} nodes, {2} elements)\n", projectPath, validation.summary.nodes, validation.summary.elements));

		const exit = await this.runWithProgress(python, projectPath, caseIds, outDir.fsPath, line => output?.append(line + '\n'), options, callerShowsProgress);

		if (exit.result.cancelled) {
			output?.append(localize('femRun.cancelled', "Analysis cancelled.\n"));
			return { status: 'cancelled', cases: 0 };
		}
		if (exit.result.exitCode !== FemRunExitCode.Ok) {
			const message = exit.lastError ?? localize('femRun.crashed', "The solver process exited unexpectedly (exit code {0}).", String(exit.result.exitCode));
			if (!options.quiet) {
				this.notificationService.notify({
					severity: Severity.Error,
					message: localize('femRun.failed', "Analysis failed: {0}", message),
					actions: { primary: [this.showLogAction()] },
				});
			}
			return { status: 'failed', cases: 0, message };
		}

		// The log keeps the result tables; the FEM editor shows them in its tables panel.
		try {
			const results = await this.solverService.getResultTables(python, outDir.fsPath, projectPath);
			output?.append(formatResults(results));
		} catch (error) {
			output?.append(localize('femRun.tablesFailed', "Could not read the results: {0}\n", String(error)));
		}
		output?.append(localize('femRun.done', "Analysis complete: {0} case(s). Results are in {1}.\n", caseIds.length, basename(outDir)));
		return { status: 'done', cases: caseIds.length };
	}

	private async runWithProgress(python: string, project: string, caseIds: number[], outDir: string, log: (line: string) => void, options: IFemRunOptions, callerShowsProgress: boolean): Promise<{ result: IFemRunExit; lastError?: string }> {
		const disposables = new DisposableStore();
		const done = new DeferredPromise<IFemRunExit>();
		let runId: string | undefined;
		let cancelled = false;
		let lastError: string | undefined;
		let report: ((message: string) => void) | undefined;
		const pending: { runId: string; event: FemRunEvent }[] = [];
		const caseNames = new Map<number, string>();
		const caseProgress = new Map<number, number>();
		const fraction = () => [...caseProgress.values()].reduce((sum, f) => sum + f, 0) / caseIds.length;

		const handle = (event: FemRunEvent) => {
			switch (event.type) {
				case 'log':
					log(event.message);
					break;
				case 'stderr':
					log(event.text);
					break;
				case 'error':
					lastError = event.message;
					log(event.traceback ?? event.message);
					break;
				case 'case_started':
					caseNames.set(event.case_id, event.case_name);
					caseProgress.set(event.case_id, 0);
					report?.(localize('femRun.caseStarted', "{0} ({1})", event.case_name, caseTypeLabel(event.case_type)));
					break;
				case 'progress':
					caseProgress.set(event.case_id, event.total > 0 ? event.step / event.total : 1);
					report?.(localize('femRun.step', "{0}: step {1} of {2}", caseNames.get(event.case_id) ?? '', event.step, event.total));
					break;
				case 'case_finished':
					caseProgress.set(event.case_id, 1);
					report?.(localize('femRun.caseFinished', "{0} finished", event.case_name));
					break;
			}
		};

		// Events can arrive before startRun() resolves with the run id, so buffer until then.
		disposables.add(this.solverService.onDidRunEvent(e => {
			if (runId === undefined) {
				pending.push(e);
			} else if (e.runId === runId) {
				handle(e.event);
			}
		}));
		disposables.add(this.solverService.onDidRunExit(e => {
			if (e.runId === runId) {
				done.complete(e);
			}
		}));
		if (options.token) {
			disposables.add(options.token.onCancellationRequested(() => {
				cancelled = true;
				if (runId) {
					void this.solverService.cancelRun(runId);
				}
			}));
		}

		const start = async () => {
			runId = await this.solverService.startRun({ python, project, caseIds, outDir });
			if (cancelled) {
				void this.solverService.cancelRun(runId);
			}
			for (const e of pending.splice(0)) {
				if (e.runId === runId) {
					handle(e.event);
				}
			}
			await done.p;
		};

		try {
			// The tracker (and so an open FEM editor) always gets the progress.
			const onProgress = options.onProgress;
			const tell = (message: string) => onProgress?.({ fraction: fraction(), message });
			tell(localize('femRun.starting', "Starting the solver"));
			if (callerShowsProgress) {
				report = tell;
				await start();
			} else {
				// No caller to show it: the status bar too, quietly.
				await this.progressService.withProgress({
					location: ProgressLocation.Window,
					title: localize('femRun.progressTitle', "Running analysis"),
				}, async progress => {
					report = message => {
						tell(message);
						progress.report({ message });
					};
					await start();
				});
			}
			return { result: await done.p, lastError };
		} finally {
			disposables.dispose();
		}
	}

	/** Removes the previous run's output, but only if it is one (it has a `manifest.json`). */
	private async clearPreviousResults(outDir: URI): Promise<void> {
		if (await this.fileService.exists(joinPath(outDir, 'manifest.json'))) {
			await this.fileService.del(outDir, { recursive: true, useTrash: false });
		}
	}

	private reportBackendError(python: string, error: unknown): void {
		this.notificationService.notify({
			severity: Severity.Error,
			message: localize('femRuntime.failed', "The SAEngine Python backend is not available ({0}): {1}. Set \"{2}\" to a Python 3.12 interpreter with saengine installed.", python, error instanceof Error ? error.message : String(error), FEM_PYTHON_SETTING),
			actions: {
				primary: [{
					id: 'saengine.fem.openPythonSetting',
					label: localize('femRuntime.openSetting', "Open Setting"),
					tooltip: '',
					class: undefined,
					enabled: true,
					run: () => this.commandService.executeCommand('workbench.action.openSettings', FEM_PYTHON_SETTING),
				}],
			},
		});
	}

	private showLogAction() {
		return {
			id: 'saengine.fem.showLogFromNotification',
			label: localize('femRun.showLog', "Show Log"),
			tooltip: '',
			class: undefined,
			enabled: true,
			run: () => this.showLog(),
		};
	}
}

/** "Static", "Modal", ... of an opensees-studio case type ("StaticCase"). */
function caseTypeLabel(type: string): string {
	return type.replace(/Case$/, '');
}

function formatTable(table: IFemResultTable): string {
	const rows = table.rows.slice(0, MAX_SUMMARY_ROWS).map(row => row.map(formatCell));
	const widths = table.columns.map((c, i) => Math.max(c.length, ...rows.map(r => (r[i] ?? '').length)));
	const line = (cells: readonly string[]) => cells.map((c, i) => c.padStart(widths[i])).join('  ');
	const out = [`  ${table.title}`, ...table.notes.map(n => `  ! ${n}`), `  ${line(table.columns)}`, ...rows.map(r => `  ${line(r)}`)];
	if (table.rows.length > rows.length) {
		out.push(localize('femRun.moreRows', "  ... {0} more row(s)", table.rows.length - rows.length));
	}
	return out.join('\n');
}

function formatResults(cases: readonly IFemCaseResults[]): string {
	const parts: string[] = [];
	for (const c of cases) {
		parts.push(`\n== ${localize('femRun.caseHeader', "Case #{0} '{1}' ({2})", c.caseId, c.caseName, c.resultType)}${c.earlyStop ? ' ' + localize('femRun.earlyStop', "[stopped early]") : ''}`);
		parts.push(...c.warnings.map(w => `  ! ${w}`));
		parts.push(...c.tables.map(formatTable));
	}
	return parts.join('\n') + '\n';
}
