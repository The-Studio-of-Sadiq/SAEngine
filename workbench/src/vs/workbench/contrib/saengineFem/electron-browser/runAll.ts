/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationError } from '../../../../base/common/errors.js';
import { CancellationToken, CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
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
import { awaitsTankDesigns, BOQ_COMPUTE_COMMAND, BOQ_SOURCES, boqComputeArgs, changedSources, IBoqComputeResult, parseBoq } from '../../saengineBoq/browser/boqDocument.js';
import { BUILD_REPORT_COMMAND_ID, IReportBuildRequest, IReportBuildResult, reportProblems } from '../../saengineReport/browser/reportBuild.js';
import { ISubstructureMigration, ISubstructureReport, ISubstructureRequest, parseSubstructure, readSubstructureReport, SUBSTRUCTURE_ENSURE_COMMAND, SUBSTRUCTURE_REPORT_COMMAND, SUBSTRUCTURE_SUMMARY_FILE, substructureSummaryFile } from '../../saengineSubstructure/browser/substructureDocument.js';
import { IMepContextTexts, IMepReport, IMepRequest, isOpenClash, MEP_REPORT_COMMAND, MEP_SOURCE_PARTS, MEP_SUMMARY_FILE, mepSummaryFile, parseMep, readMepReport } from '../../saengineMep/browser/mepDocument.js';
import { hasPlumbing, IPlumbingReport, PLUMBING_REPORT_COMMAND, plumbingFailures, plumbingSummaryFile, readPlumbingReport } from '../../saengineMep/browser/plumbingDocument.js';
import { hasHvac, HVAC_REPORT_COMMAND, hvacFailures, hvacSummaryFile, IHvacReport, readHvacReport } from '../../saengineMep/browser/hvacDocument.js';
import { ELECTRICAL_REPORT_COMMAND, electricalFailures, electricalSummaryFile, hasElectrical, IElectricalReport, readElectricalReport } from '../../saengineMep/browser/electricalDocument.js';
import { FIRE_REPORT_COMMAND, fireFailures, fireSummaryFile, hasFire, IFireReport, readFireReport } from '../../saengineMep/browser/fireDocument.js';
import { DRAWINGS_GENERATE_COMMAND, DRAWINGS_LIST_COMMAND, readDrawingSet } from '../../saengineProject/browser/drawingsModel.js';
import { DERIVATION_INPUTS, deriveAnalysisModel, derivationState, partFile, SSI_FILE } from '../browser/femDerivationBar.js';
import { SSI_COMPARE_COMMAND } from '../browser/femSsi.js';
import { IFemDesignReport, IFemDesignRequired, runDesign, runDesignRequired, shortElements, tooSmallElements, writeDesignSummary } from '../browser/femDesign.js';
import { errorSummary } from '../browser/femResultsBar.js';
import { FemAnalysisRunner } from './femAnalysisRunner.js';

/** Command id of Run All, and of cancelling it (the status bar entry runs it). */
export const RUN_ALL_COMMAND_ID = 'saengine.runAll';
export const CANCEL_RUN_ALL_COMMAND_ID = 'saengine.runAll.cancel';

const STATUS_ENTRY_ID = 'saengine.runAll.status';

type StepId = 'derive' | 'analysis' | 'ssi' | 'design' | 'substructure' | 'mep' | 'boq' | 'report' | 'drawings';


/** The steps of Run All, in order, with the names the status bar gives them. */
const STEPS: readonly { readonly id: StepId; readonly label: string }[] = [
	{ id: 'derive', label: localize('runAll.step.derive', "analysis model") },
	{ id: 'analysis', label: localize('runAll.step.analysis', "analysis") },
	{ id: 'ssi', label: localize('runAll.step.ssi', "fixed-base run for the soil springs") },
	{ id: 'design', label: localize('runAll.step.design', "design checks") },
	{ id: 'substructure', label: localize('runAll.step.substructure', "foundation design") },
	{ id: 'mep', label: localize('runAll.step.mep', "MEP coordination, plumbing, HVAC, electrical and fire checks") },
	{ id: 'boq', label: localize('runAll.step.boq', "bill of quantities") },
	{ id: 'report', label: localize('runAll.step.report', "report") },
	{ id: 'drawings', label: localize('runAll.step.drawings', "drawings") },
];

/** What Run All's drawings step did: drew the set again, found it current, or found none generated yet. */
type DrawingsOutcome = { readonly kind: 'drawn'; readonly sheets: number } | { readonly kind: 'current' } | { readonly kind: 'none' };

/** A step that could not be done: Run All stops and says which. */
class StepFailure extends Error { }

/** A discipline's report of 7 MEP in Run All, with the openings it still needs (reported, not added). */
interface IServiceCheck<T> {
	readonly report: T;
	readonly missingOpenings: number;
}

/** What Run All's MEP step checked. */
interface IMepChecks {
	readonly mep: IMepReport;
	readonly plumbing?: IPlumbingReport;
	readonly hvac?: IServiceCheck<IHvacReport>;
	readonly electrical?: IServiceCheck<IElectricalReport>;
	readonly fire?: IServiceCheck<IFireReport>;
}

function record(value: unknown): { readonly [key: string]: unknown } {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as { readonly [key: string]: unknown } : {};
}

/** How many openings a backend report proposes (its `openings`: those not in 07 MEP yet). */
function openingsOf(raw: unknown): number {
	const openings = record(raw).openings;
	return Array.isArray(openings) ? openings.length : 0;
}

export const IRunAllService = createDecorator<IRunAllService>('saengineRunAllService');

/**
 * Brings the open project's outputs up to date in one go: derives the analysis model if it is
 * out of date, runs all analysis cases (and, on soil springs, the fixed-base model the foundations
 * are designed from, with the comparison of the two), runs the design checks (writing
 * `08 FEM/model.results/design-summary.json`), designs the foundations of 9 Substructure (moving
 * the building model's footings there first while it is still the placeholder; writing
 * `09 Substructure/substructure.results/summary.json`), checks the MEP coordination of 7 MEP
 * and its plumbing (the sleeves still missing are reported, not added; writing
 * `07 MEP/mep.results/summary.json`), measures the bill of quantities if it is
 * out of date, builds the design report and draws the structural drawings of `11 Exports/Drawings`
 * again when a set was generated before and is out of date (a project whose drawings were never
 * generated skips the step: the first set, seconds to minutes of work, is started from the
 * Exports page). Progress is one status bar entry (click to cancel); the end is one quiet
 * summary, or one error naming the step that failed.
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
			await this.compareSoilSprings(project);
			this.check(token);

			step = 3;
			report();
			const design = await this.design(model);
			this.check(token);

			step = 4;
			report();
			const foundations = await this.designSubstructure(project);
			this.check(token);

			step = 5;
			report();
			const mep = await this.checkMep(project);
			this.check(token);

			step = 6;
			report();
			const boqUpdated = await this.measure(project, token, !!mep?.plumbing);

			step = 7;
			report();
			const pdf = await this.buildReport(project);
			this.check(token);

			step = 8;
			report();
			const drawings = await this.drawings(project, design.report);
			this.check(token);

			this.showSummary(design, foundations, mep, derived, boqUpdated, pdf, drawings);
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

	/**
	 * Saves the project's edited part files: the steps read them from disk (the soil report too:
	 * the derivation takes the site class, and the footing design qa, from the saved file).
	 */
	private async saveSources(project: ISaengineProject): Promise<void> {
		const ids = [...new Set([...DERIVATION_INPUTS, ...BOQ_SOURCES.map(s => s.part), 'substructure', 'soil', 'mep'])];
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
			return false;
		}
		this.check(token);
		const outcome = await deriveAnalysisModel(this.commandService, this.fileService, project.root, texts);
		if (!outcome.ok) {
			throw new StepFailure(outcome.message);
		}
		return true;
	}

	/**
	 * The design checks, then (design mode) the steel each element requires, which the backend
	 * keeps beside the results (`design-required.json`) for the Properties panel and the report.
	 * The required steel is a note when it cannot be worked out: the checks are the verdict.
	 * Mirrors `_design` of `saengine.pipeline.run_all`.
	 */
	private async design(model: URI): Promise<{ readonly report: IFemDesignReport; readonly required: IFemDesignRequired | undefined }> {
		const report = await runDesign(this.commandService, model);
		if (!report) {
			throw new StepFailure(localize('runAll.designUnavailable', "The design checks are not available."));
		}
		await writeDesignSummary(this.fileService, model, report);
		let required: IFemDesignRequired | undefined;
		try {
			required = await runDesignRequired(this.commandService, model);
		} catch {
			required = undefined;
		}
		return { report, required };
	}

	/**
	 * Designs the foundations of 9 Substructure: moves the building model's footings there first
	 * while it is still the placeholder (projects from before Part 9), then checks the saved file
	 * and writes the summary the part list shows. Undefined when there are no foundations.
	 */
	private async designSubstructure(project: ISaengineProject): Promise<ISubstructureReport | undefined> {
		const part = partById('substructure');
		if (!part?.mainFile) {
			return undefined;
		}
		const resource = joinPath(project.root, part.folder, part.mainFile);
		const request: ISubstructureRequest = { projectRoot: project.root.fsPath };
		const migration = await this.commandService.executeCommand<ISubstructureMigration>(SUBSTRUCTURE_ENSURE_COMMAND, request);
		if (migration?.problems?.length) {
			throw new StepFailure(migration.problems.join(' '));
		}
		let text: string;
		try {
			text = (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return undefined; // no substructure file: nothing to design
		}
		const parsed = parseSubstructure(text);
		if (parsed.kind === 'error') {
			throw new StepFailure(parsed.message);
		}
		if (parsed.kind === 'placeholder' || !parsed.document.foundations.length) {
			return undefined;
		}
		let report: ISubstructureReport | undefined;
		try {
			report = readSubstructureReport(await this.commandService.executeCommand<unknown>(SUBSTRUCTURE_REPORT_COMMAND, request));
		} catch (error) {
			throw new StepFailure(errorSummary(error));
		}
		if (!report) {
			throw new StepFailure(localize('runAll.substructureUnavailable', "The foundation design is not available."));
		}
		const summary = substructureSummaryFile(parsed.document, report, new Date());
		await this.fileService.writeFile(joinPath(dirname(resource), SUBSTRUCTURE_SUMMARY_FILE), VSBuffer.fromString(JSON.stringify(summary, undefined, '\t') + '\n'));
		return report;
	}

	/**
	 * On soil springs (the model has `08 FEM/ssi.json`): derives and runs the fixed-base model the
	 * foundations are designed from, and compares the two (`08 FEM/ssi-compare.json`).
	 */
	private async compareSoilSprings(project: ISaengineProject): Promise<void> {
		const springs = joinPath(dirname(partFile(project.root, 'fem')), SSI_FILE);
		if (!await this.fileService.exists(springs)) {
			return;
		}
		try {
			await this.commandService.executeCommand(SSI_COMPARE_COMMAND, { projectRoot: project.root.fsPath });
		} catch (error) {
			throw new StepFailure(errorSummary(error));
		}
	}

	/**
	 * Checks the MEP coordination of 7 MEP (equipment loads, openings, clashes) and its plumbing
	 * (BNBC 2020 Part 8 sizing, the tanks' design, the hydraulics, the sleeves still missing:
	 * reported, never added to the file) and writes the summary the part list shows. Undefined
	 * while the MEP file is the placeholder or empty.
	 */
	private async checkMep(project: ISaengineProject): Promise<IMepChecks | undefined> {
		const part = partById('mep');
		if (!part?.mainFile) {
			return undefined;
		}
		const resource = joinPath(project.root, part.folder, part.mainFile);
		let text: string;
		try {
			text = (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return undefined;
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
			return undefined;
		}
		const texts = await this.readParts(project, MEP_SOURCE_PARTS);
		const request: IMepRequest = { projectRoot: project.root.fsPath, mepText: text };
		let report: IMepReport | undefined;
		try {
			report = readMepReport(await this.commandService.executeCommand<unknown>(MEP_REPORT_COMMAND, request));
		} catch (error) {
			throw new StepFailure(errorSummary(error));
		}
		if (!report) {
			throw new StepFailure(localize('runAll.mepUnavailable', "The MEP coordination checks are not available."));
		}
		let plumbing: IPlumbingReport | undefined;
		if (withPlumbing) {
			try {
				plumbing = readPlumbingReport(await this.commandService.executeCommand<unknown>(PLUMBING_REPORT_COMMAND, request));
			} catch (error) {
				throw new StepFailure(errorSummary(error));
			}
			if (!plumbing) {
				throw new StepFailure(localize('runAll.plumbingUnavailable', "The plumbing checks are not available."));
			}
		}
		// HVAC: its report never starts EnergyPlus; the loads are EnergyPlus's when Calculate Loads
		// ran for this input, else the estimate (said in the summary). Openings are reported, not added.
		let hvac: IServiceCheck<IHvacReport> | undefined;
		if (withHvac) {
			hvac = await this.serviceReport(HVAC_REPORT_COMMAND, request, readHvacReport, raw => openingsOf(record(raw).air), localize('runAll.hvacUnavailable', "The HVAC checks are not available."));
		}
		let electrical: IServiceCheck<IElectricalReport> | undefined;
		if (withElectrical) {
			electrical = await this.serviceReport(ELECTRICAL_REPORT_COMMAND, request, readElectricalReport, openingsOf, localize('runAll.electricalUnavailable', "The electrical checks are not available."));
		}
		let fire: IServiceCheck<IFireReport> | undefined;
		if (withFire) {
			fire = await this.serviceReport(FIRE_REPORT_COMMAND, request, readFireReport, openingsOf, localize('runAll.fireUnavailable', "The fire checks are not available."));
		}
		const sourceTexts: IMepContextTexts = Object.fromEntries(MEP_SOURCE_PARTS.map(id => [id, texts.get(id)]));
		const summary = {
			...mepSummaryFile(document, report, text, new Date(), sourceTexts),
			...(plumbing ? { plumbing: plumbingSummaryFile(document, plumbing) } : {}),
			...(hvac ? { hvac: hvacSummaryFile(document, hvac.report) } : {}),
			...(electrical ? { electrical: electricalSummaryFile(document, electrical.report) } : {}),
			...(fire ? { fire: fireSummaryFile(document, fire.report) } : {}),
		};
		await this.fileService.writeFile(joinPath(dirname(resource), MEP_SUMMARY_FILE), VSBuffer.fromString(JSON.stringify(summary, undefined, '\t') + '\n'));
		return { mep: report, plumbing, hvac, electrical, fire };
	}

	/** A discipline's report of 7 MEP by its command, read, with the openings it still needs; a step failure when it is not available. */
	private async serviceReport<T>(command: string, request: IMepRequest, read: (raw: unknown) => T | undefined, missing: (raw: unknown) => number, unavailable: string): Promise<IServiceCheck<T>> {
		let raw: unknown;
		try {
			raw = await this.commandService.executeCommand<unknown>(command, request);
		} catch (error) {
			throw new StepFailure(errorSummary(error));
		}
		const report = read(raw);
		if (!report) {
			throw new StepFailure(unavailable);
		}
		return { report, missingOpenings: missing(raw) };
	}

	/**
	 * Measures the bill of quantities when it is not measured yet or its sources changed, or when
	 * `tanksDesigned` (the plumbing report has just designed the tanks) and the bill still waits
	 * for a tank's design to measure its bars.
	 */
	private async measure(project: ISaengineProject, token: CancellationToken, tanksDesigned: boolean): Promise<boolean> {
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
			const current = parseBoq(model.getValue());
			if (!changedSources(current, texts).length && !(tanksDesigned && awaitsTankDesigns(current))) {
				return false;
			}
			const { args, missing } = boqComputeArgs(texts, project.root.fsPath);
			if (!args) {
				throw new StepFailure(localize('runAll.boqMissing', "{0} could not be read.", missing.join(', ')));
			}
			this.check(token);
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

	/**
	 * Draws the drawings again when a set was generated before and is out of date, with the
	 * design checks just made (the backend need not run them again).
	 */
	private async drawings(project: ISaengineProject, design: IFemDesignReport): Promise<DrawingsOutcome> {
		const current = readDrawingSet(await this.commandService.executeCommand<unknown>(DRAWINGS_LIST_COMMAND, { projectRoot: project.root.fsPath }), project.root);
		if (!current?.sheets.length) {
			return { kind: 'none' };
		}
		if (!current.stale) {
			return { kind: 'current' };
		}
		const answer = readDrawingSet(await this.commandService.executeCommand<unknown>(DRAWINGS_GENERATE_COMMAND, { projectRoot: project.root.fsPath, designReportText: JSON.stringify(design) }), project.root);
		if (!answer?.sheets.length) {
			throw new StepFailure(answer?.problems.join(' ') || localize('runAll.drawingsFailed', "The drawings could not be generated."));
		}
		return { kind: 'drawn', sheets: answer.sheets.length };
	}

	/** "Done: 13 pass, 3 fail · foundations 6 pass, 1 fail · MEP: failing openings 1, open clashes 2 · plumbing: 3 checks fail, 1 floor below the minimum pressure · HVAC: failing checks 1, openings to add 0, loads not calculated: run Calculate Loads · electrical: failing checks 0, openings to add 1 · BOQ updated · report written", with Open Report. */
	private showSummary(checks: { readonly report: IFemDesignReport; readonly required: IFemDesignRequired | undefined }, foundations: ISubstructureReport | undefined, checked: IMepChecks | undefined, derived: boolean, boqUpdated: boolean, pdf: URI, drawings: DrawingsOutcome): void {
		const mep = checked?.mep;
		const failedOpenings = mep ? mep.openings.filter(o => !o.ok).length : 0;
		const openClashes = mep ? mep.clashes.filter(isOpenClash).length : 0;
		const plumbing = checked?.plumbing ? plumbingFailures(checked.plumbing) : undefined;
		const hvac = checked?.hvac;
		const electrical = checked?.electrical;
		const fire = checked?.fire;
		const design = checks.report;
		const short = shortElements(checks.required).length;
		const tooSmall = tooSmallElements(checks.required).length;
		const designText = localize('runAll.summary.design', "{0} pass, {1} fail", design.summary.passed, design.summary.failed)
			+ (short ? localize('runAll.summary.steelShort', "; steel short in {0} element(s)", short) : '')
			+ (tooSmall ? localize('runAll.summary.tooSmall', ", {0} section(s) too small", tooSmall) : '');
		const parts = [
			designText,
			...(foundations ? [localize('runAll.summary.foundations', "foundations {0} pass, {1} fail", foundations.summary.passed, foundations.summary.failed)] : []),
			...(mep ? [localize('runAll.summary.mep', "MEP: failing openings {0}, open clashes {1}", failedOpenings, openClashes)] : []),
			...(plumbing ? [localize('runAll.summary.plumbing', "plumbing: failing checks {0}, floors below the minimum pressure {1}", plumbing.items, plumbing.floorsLow)] : []),
			...(hvac ? [hvac.report.calculated === false
				? localize('runAll.summary.hvacEstimate', "HVAC: failing checks {0}, openings to add {1}, loads not calculated: run Calculate Loads", hvacFailures(hvac.report), hvac.missingOpenings)
				: localize('runAll.summary.hvac', "HVAC: failing checks {0}, openings to add {1}", hvacFailures(hvac.report), hvac.missingOpenings)] : []),
			...(electrical ? [localize('runAll.summary.electrical', "electrical: failing checks {0}, openings to add {1}", electricalFailures(electrical.report), electrical.missingOpenings)] : []),
			...(fire ? [localize('runAll.summary.fire', "fire: failing checks {0}, sleeves to add {1}", fireFailures(fire.report), fire.missingOpenings)] : []),
			...(derived ? [localize('runAll.summary.derived', "model derived")] : []),
			boqUpdated ? localize('runAll.summary.boqUpdated', "BOQ updated") : localize('runAll.summary.boqCurrent', "BOQ up to date"),
			localize('runAll.summary.report', "report written"),
			...(drawings.kind === 'drawn' ? [localize('runAll.summary.drawings', "{0} drawing sheets drawn", drawings.sheets)] : drawings.kind === 'current' ? [localize('runAll.summary.drawingsCurrent', "drawings up to date")] : []),
		];
		this.notificationService.prompt(Severity.Info, localize('runAll.done', "Done: {0}", parts.join(' · ')), [{
			label: localize('runAll.openReport', "Open Report"),
			run: () => this.openerService.open(pdf, { openExternal: true }),
		}]);
	}
}
