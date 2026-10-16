/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationError } from '../../../../base/common/errors.js';
import { CancellationToken, CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { IReference } from '../../../../base/common/lifecycle.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { createDecorator, IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { BOQ_COMPUTE_COMMAND, BOQ_SOURCES, changedSources, IBoqComputeArgs, IBoqComputeResult, parseBoq } from '../../saengineBoq/browser/boqDocument.js';
import { BUILD_REPORT_COMMAND_ID, IReportBuildRequest, IReportBuildResult, reportProblems } from '../../saengineReport/browser/reportBuild.js';
import { DERIVATION_SOURCES, deriveAnalysisModel, derivationState, partFile } from '../browser/femDerivationBar.js';
import { IFemDesignReport, runDesign, writeDesignSummary } from '../browser/femDesign.js';
import { errorSummary } from '../browser/femResultsBar.js';
import { FemAnalysisRunner } from './femAnalysisRunner.js';

/** Command id of Run All, and of cancelling it (the status bar entry runs it). */
export const RUN_ALL_COMMAND_ID = 'saengine.runAll';
export const CANCEL_RUN_ALL_COMMAND_ID = 'saengine.runAll.cancel';

const STATUS_ENTRY_ID = 'saengine.runAll.status';

type StepId = 'derive' | 'analysis' | 'design' | 'boq' | 'report';

/** The steps of Run All, in order, with the names the status bar gives them. */
const STEPS: readonly { readonly id: StepId; readonly label: string }[] = [
	{ id: 'derive', label: localize('runAll.step.derive', "analysis model") },
	{ id: 'analysis', label: localize('runAll.step.analysis', "analysis") },
	{ id: 'design', label: localize('runAll.step.design', "design checks") },
	{ id: 'boq', label: localize('runAll.step.boq', "bill of quantities") },
	{ id: 'report', label: localize('runAll.step.report', "report") },
];

/** A step that could not be done: Run All stops and says which. */
class StepFailure extends Error { }

export const IRunAllService = createDecorator<IRunAllService>('saengineRunAllService');

/**
 * Brings the open project's outputs up to date in one go: derives the analysis model if it is
 * out of date, runs all analysis cases, runs the design checks (writing
 * `08 FEM/model.results/design-summary.json`), measures the bill of quantities if it is out of
 * date and builds the design report. Progress is one status bar entry (click to cancel); the end
 * is one quiet summary, or one error naming the step that failed.
 */
export interface IRunAllService {
	readonly _serviceBrand: undefined;
	readonly running: boolean;
	run(): Promise<void>;
	cancel(): void;
}

export class RunAllService implements IRunAllService {

	declare readonly _serviceBrand: undefined;

	private cancellation: CancellationTokenSource | undefined;
	private status: IStatusbarEntryAccessor | undefined;

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
	) { }

	get running(): boolean {
		return !!this.cancellation;
	}

	cancel(): void {
		this.cancellation?.cancel();
	}

	async run(): Promise<void> {
		const project = this.projectService.project;
		if (!project) {
			this.notificationService.info(localize('runAll.noProject', "Open a SAEngine project to run it."));
			return;
		}
		if (this.cancellation) {
			return; // already running: the status bar shows it
		}
		const cancellation = this.cancellation = new CancellationTokenSource();
		const token = cancellation.token;
		let step = 0;
		const report = (detail?: string) => this.showStatus(step, detail);
		try {
			await this.saveSources(project);

			step = 0;
			report();
			const derived = await this.derive(project, token);

			step = 1;
			report();
			const model = partFile(project.root, 'fem');
			const runner = this.instantiationService.createInstance(FemAnalysisRunner);
			const outcome = await runner.run(model, { quiet: true, token, onProgress: progress => report(progress.message) });
			if (outcome.status === 'cancelled') {
				throw new CancellationError();
			}
			if (outcome.status !== 'done') {
				throw new StepFailure(outcome.message ?? outcome.status);
			}

			step = 2;
			report();
			const design = await this.design(model);
			this.check(token);

			step = 3;
			report();
			const boqUpdated = await this.measure(project, token);

			step = 4;
			report();
			const pdf = await this.buildReport(project);
			this.check(token);

			this.showSummary(design, derived, boqUpdated, pdf);
		} catch (error) {
			if (error instanceof CancellationError || token.isCancellationRequested) {
				this.notificationService.notify({ severity: Severity.Info, message: localize('runAll.cancelled', "Run All cancelled at step {0} of {1} ({2}).", step + 1, STEPS.length, STEPS[step].label) });
			} else {
				this.notificationService.notify({
					severity: Severity.Error,
					message: localize('runAll.failed', "Run All stopped at step {0} of {1} ({2}): {3}", step + 1, STEPS.length, STEPS[step].label, errorSummary(error)),
					actions: STEPS[step].id === 'analysis' ? {
						primary: [{
							id: 'saengine.runAll.showLog',
							label: localize('runAll.showLog', "Show Log"),
							tooltip: '',
							class: undefined,
							enabled: true,
							run: () => this.instantiationService.createInstance(FemAnalysisRunner).showLog(),
						}],
					} : undefined,
				});
			}
		} finally {
			cancellation.dispose();
			this.cancellation = undefined;
			this.status?.dispose();
			this.status = undefined;
		}
	}

	private check(token: CancellationToken): void {
		if (token.isCancellationRequested) {
			throw new CancellationError();
		}
	}

	/** One status bar entry: "Running 2 of 5: analysis", the solver's progress in its tooltip. */
	private showStatus(step: number, detail: string | undefined): void {
		const text = localize('runAll.status', "Running {0} of {1}: {2}", step + 1, STEPS.length, STEPS[step].label);
		const entry = {
			name: localize('runAll.statusName', "Run All"),
			text: `$(sync~spin) ${text}`,
			ariaLabel: detail ? `${text}: ${detail}` : text,
			tooltip: detail
				? localize('runAll.tooltipDetail', "{0}: {1}. Click to cancel.", text, detail)
				: localize('runAll.tooltip', "{0}. Click to cancel.", text),
			command: CANCEL_RUN_ALL_COMMAND_ID,
		};
		if (this.status) {
			this.status.update(entry);
		} else {
			this.status = this.statusbarService.addEntry(entry, STATUS_ENTRY_ID, StatusbarAlignment.LEFT, -100);
		}
	}

	/** Saves the project's edited part files: the steps read them from disk. */
	private async saveSources(project: ISaengineProject): Promise<void> {
		const ids = [...new Set([...DERIVATION_SOURCES.map(s => s.part), ...BOQ_SOURCES.map(s => s.part)])];
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
			if (!part?.mainFile) {
				texts.set(id, undefined);
				continue;
			}
			try {
				const content = await this.fileService.readFile(joinPath(project.root, part.folder, part.mainFile));
				texts.set(id, content.value.toString());
			} catch {
				texts.set(id, undefined);
			}
		}
		return texts;
	}

	/** Derives the analysis model when it is not derived yet or its sources changed. */
	private async derive(project: ISaengineProject, token: CancellationToken): Promise<boolean> {
		const texts = await this.readParts(project, DERIVATION_SOURCES.map(s => s.part));
		let description: unknown;
		try {
			const content = await this.fileService.readFile(partFile(project.root, 'fem'));
			description = JSON.parse(content.value.toString())?.meta?.description;
		} catch {
			description = undefined; // no model yet
		}
		const state = derivationState(description, texts);
		if (state.derived && !state.changed.length) {
			return false;
		}
		this.check(token);
		const outcome = await deriveAnalysisModel(this.commandService, this.fileService, project.root, texts);
		if (!outcome.ok) {
			throw new StepFailure(outcome.message);
		}
		return true;
	}

	private async design(model: URI): Promise<IFemDesignReport> {
		const report = await runDesign(this.commandService, model);
		if (!report) {
			throw new StepFailure(localize('runAll.designUnavailable', "The design checks are not available."));
		}
		await writeDesignSummary(this.fileService, model, report);
		return report;
	}

	/** Measures the bill of quantities when it is not measured yet or its sources changed. */
	private async measure(project: ISaengineProject, token: CancellationToken): Promise<boolean> {
		const boq = partById('boq');
		if (!boq?.mainFile) {
			return false;
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
			if (!changedSources(parseBoq(model.getValue()), texts).length) {
				return false;
			}
			const [bimText, objectsText, materialsText] = BOQ_SOURCES.map(s => texts.get(s.part));
			if (bimText === undefined || objectsText === undefined || materialsText === undefined) {
				const missing = BOQ_SOURCES.filter(s => texts.get(s.part) === undefined).map(s => s.label);
				throw new StepFailure(localize('runAll.boqMissing', "{0} could not be read.", missing.join(', ')));
			}
			this.check(token);
			const args: IBoqComputeArgs = { bimText, objectsText, materialsText };
			const result = await this.commandService.executeCommand<IBoqComputeResult>(BOQ_COMPUTE_COMMAND, args);
			if (!result?.text) {
				throw new StepFailure((result?.problems ?? []).join('; ') || localize('runAll.boqFailed', "The bill could not be measured."));
			}
			this.check(token);
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: result.text }], () => null);
			model.pushStackElement();
			await this.textFileService.save(resource);
			return true;
		} finally {
			reference.dispose();
		}
	}

	private async buildReport(project: ISaengineProject): Promise<URI> {
		const request: IReportBuildRequest = { projectRoot: project.root.fsPath };
		const result = await this.commandService.executeCommand<IReportBuildResult>(BUILD_REPORT_COMMAND_ID, request);
		const problems = reportProblems(result);
		if (problems.length || !result?.path) {
			throw new StepFailure(problems.join(' ') || localize('runAll.reportFailed', "The report could not be built."));
		}
		return URI.file(result.path);
	}

	/** "Done: 13 pass, 3 fail · BOQ updated · report written", with Open Report. */
	private showSummary(design: IFemDesignReport, derived: boolean, boqUpdated: boolean, pdf: URI): void {
		const parts = [
			localize('runAll.summary.design', "{0} pass, {1} fail", design.summary.passed, design.summary.failed),
			...(derived ? [localize('runAll.summary.derived', "model derived")] : []),
			boqUpdated ? localize('runAll.summary.boqUpdated', "BOQ updated") : localize('runAll.summary.boqCurrent', "BOQ up to date"),
			localize('runAll.summary.report', "report written"),
		];
		this.notificationService.prompt(Severity.Info, localize('runAll.done', "Done: {0}", parts.join(' · ')), [{
			label: localize('runAll.openReport', "Open Report"),
			run: () => this.openerService.open(pdf, { openExternal: true }),
		}]);
	}
}
