/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { DeferredPromise } from '../../../../base/common/async.js';
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
import { resultsFolder } from '../browser/femResultsBar.js';
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
 * Runs the analysis cases of one `.osmodel` file: validates the model, asks which cases to
 * run, streams solver progress to a notification and the output channel, and prints the
 * result tables when the run finishes.
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
	) { }

	/**
	 * The interpreter set in `saengine.python.path`, else the repository `.venv` next to
	 * the workbench sources (development layout).
	 */
	resolvePython(): string {
		const configured = this.configurationService.getValue<string>(FEM_PYTHON_SETTING)?.trim();
		if (configured) {
			return configured;
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

	async run(model: URI): Promise<void> {
		const python = this.resolvePython();
		const projectPath = model.fsPath;

		let validation;
		try {
			validation = await this.solverService.validateProject(python, projectPath);
		} catch (error) {
			this.reportBackendError(python, error);
			return;
		}
		if (!validation.ok || !validation.summary) {
			this.notificationService.error(localize('femRun.invalid', "The model cannot be analyzed: {0}", validation.errors.join('; ')));
			return;
		}
		if (!validation.summary.analyses.length) {
			this.notificationService.info(localize('femRun.noCases', "The model defines no analysis cases."));
			return;
		}

		const picks: ICasePick[] = validation.summary.analyses.map(c => ({
			caseId: c.id,
			label: c.name,
			description: c.type.replace(/Case$/, ''),
			detail: localize('femRun.caseId', "Case #{0}", c.id),
			picked: true,
		}));
		const selected = await this.quickInputService.pick(picks, {
			canPickMany: true,
			title: localize('femRun.pickTitle', "Run Analysis: {0}", basename(model)),
			placeHolder: localize('femRun.pickPlaceholder', "Select the analysis cases to run"),
		});
		if (!selected?.length) {
			return;
		}

		const outDir = resultsFolder(model);
		await this.clearPreviousResults(outDir);

		const output = this.outputService.getChannel(FEM_OUTPUT_CHANNEL_ID);
		// replace() rather than clear(): clear() resets asynchronously and would also drop the lines appended right after it.
		output?.replace(localize('femRun.header', "Analyzing {0} ({1} nodes, {2} elements)\n", projectPath, validation.summary.nodes, validation.summary.elements));
		void this.outputService.showChannel(FEM_OUTPUT_CHANNEL_ID, true);

		const caseIds = selected.map(s => s.caseId);
		const exit = await this.runWithProgress(python, projectPath, caseIds, outDir.fsPath, line => output?.append(line + '\n'));

		if (exit.result.cancelled) {
			output?.append(localize('femRun.cancelled', "Analysis cancelled.\n"));
			return;
		}
		if (exit.result.exitCode !== FemRunExitCode.Ok) {
			const message = exit.lastError ?? localize('femRun.crashed', "The solver process exited unexpectedly (exit code {0}).", String(exit.result.exitCode));
			this.notificationService.notify({
				severity: Severity.Error,
				message: localize('femRun.failed', "Analysis failed: {0}", message),
				actions: { primary: [this.showOutputAction()] },
			});
			return;
		}

		try {
			const results = await this.solverService.getResultTables(python, outDir.fsPath, projectPath);
			output?.append(formatResults(results));
		} catch (error) {
			output?.append(localize('femRun.tablesFailed', "Could not read the results: {0}\n", String(error)));
		}
		this.notificationService.notify({
			severity: Severity.Info,
			message: localize('femRun.done', "Analysis complete: {0} case(s). Results are in {1}.", caseIds.length, basename(outDir)),
			actions: { primary: [this.showOutputAction()] },
		});
	}

	private async runWithProgress(python: string, project: string, caseIds: number[], outDir: string, log: (line: string) => void): Promise<{ result: IFemRunExit; lastError?: string }> {
		const disposables = new DisposableStore();
		const done = new DeferredPromise<IFemRunExit>();
		let runId: string | undefined;
		let lastError: string | undefined;
		let report: ((message: string, increment?: number) => void) | undefined;
		const pending: { runId: string; event: FemRunEvent }[] = [];
		const caseNames = new Map<number, string>();
		const share = 100 / caseIds.length;
		const caseProgress = new Map<number, number>();

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
					report?.(localize('femRun.caseStarted', "{0} ({1})", event.case_name, event.case_type.replace(/Case$/, '')));
					break;
				case 'progress': {
					const fraction = event.total > 0 ? event.step / event.total : 1;
					const previous = caseProgress.get(event.case_id) ?? 0;
					caseProgress.set(event.case_id, fraction);
					report?.(localize('femRun.step', "{0}: step {1} of {2}", caseNames.get(event.case_id) ?? '', event.step, event.total), (fraction - previous) * share);
					break;
				}
				case 'case_finished':
					report?.(localize('femRun.caseFinished', "{0} finished", event.case_name), (1 - (caseProgress.get(event.case_id) ?? 0)) * share);
					caseProgress.set(event.case_id, 1);
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

		try {
			await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('femRun.progressTitle', "Running analysis"),
				cancellable: true,
			}, async progress => {
				report = (message, increment) => progress.report({ message, increment });
				runId = await this.solverService.startRun({ python, project, caseIds, outDir });
				for (const e of pending.splice(0)) {
					if (e.runId === runId) {
						handle(e.event);
					}
				}
				await done.p;
			}, () => {
				if (runId) {
					void this.solverService.cancelRun(runId);
				}
			});
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

	private showOutputAction() {
		return {
			id: 'saengine.fem.showOutput',
			label: localize('femRun.showOutput', "Show Output"),
			tooltip: '',
			class: undefined,
			enabled: true,
			run: () => this.outputService.showChannel(FEM_OUTPUT_CHANNEL_ID),
		};
	}
}

function formatCell(value: number | string): string {
	if (typeof value === 'number') {
		return Number.isInteger(value) ? String(value) : value.toPrecision(6);
	}
	return value;
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
