/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/**
 * Builds the printed design report (`11 Exports/report.pdf`, or `report.docx` for Word) of a
 * project with the Python backend (`saengine.report.build_report`). Registered by the
 * integration that owns the RPC.
 */
export const BUILD_REPORT_COMMAND_ID = 'saengine.report.build';

/** The report templates of a project (`{templates, current}`); registered with the RPC. */
export const REPORT_TEMPLATES_COMMAND_ID = 'saengine.report.templates';

/** Writes a new report template into the project (`{projectRoot, id, base?, name?}`); registered with the RPC. */
export const CREATE_REPORT_TEMPLATE_COMMAND_ID = 'saengine.report.createTemplate';

/** The user-facing commands: print the PDF, export Word, configure, and choose the project's template. */
export const PRINT_REPORT_COMMAND_ID = 'saengine.report.print';
export const EXPORT_WORD_REPORT_COMMAND_ID = 'saengine.report.exportWord';
export const CONFIGURE_REPORT_COMMAND_ID = 'saengine.report.configure';
export const USE_REPORT_TEMPLATE_COMMAND_ID = 'saengine.report.useTemplate';

/** Where a project keeps its report templates (`saengine.library.report_template.TEMPLATES_FOLDER`), in `11 Exports`. */
export const REPORT_TEMPLATES_FOLDER = 'report-templates';

/** What the design report is written as. */
export type ReportFormat = 'pdf' | 'docx';

/** Argument of {@link BUILD_REPORT_COMMAND_ID}. */
export interface IReportBuildRequest {
	/** File system path of the project root (the folder holding the `.saengine` manifest). */
	readonly projectRoot: string;
	/** Where to write the report; `<project>/11 Exports/report.pdf` (`.docx`) when omitted. */
	readonly outPdf?: string;
	/** `pdf` (default) or `docx`. */
	readonly format?: ReportFormat;
	/** The report template's id; the project settings' (Design report → Template) when omitted. */
	readonly template?: string;
}

/** A report template the project can print. */
export interface IReportTemplateInfo {
	readonly id: string;
	readonly name: string;
	readonly source: 'builtIn' | 'project';
	/** File system path of a project template. */
	readonly path?: string;
}

/** Result of {@link REPORT_TEMPLATES_COMMAND_ID}. */
export interface IReportTemplates {
	readonly templates: readonly IReportTemplateInfo[];
	/** The template the project settings name. */
	readonly current: string;
}

/** A template id from a name: lower case, digits and hyphens ("Client Summary" → "client-summary"). */
export function templateId(name: string): string {
	return name.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}

/** Result of {@link BUILD_REPORT_COMMAND_ID}: the PDF written, or the problems that stopped it. */
export interface IReportBuildResult {
	/** File system path of the PDF written. */
	readonly path?: string;
	readonly pages?: number;
	/** What the report could not include or flags (stale inputs, failing elements, ...). */
	readonly warnings?: readonly string[];
	/** Why no report was written, e.g. "There are no analysis results: run the analysis first." */
	readonly problems?: readonly string[];
	/** The design result its cover leads with (`saengine.report.build.design_status`). */
	readonly status?: IReportStatus;
	readonly format?: ReportFormat;
	/** The report template it followed. */
	readonly template?: string;
}

/** The design result of a report: what its cover banner and `report.summary.json` say. */
export interface IReportStatus {
	readonly state: 'pass' | 'fail' | 'incomplete' | 'unchecked';
	readonly headline: string;
	/** Members left without reinforcement, by kind: `{ column: 28, slab: 120 }`. */
	readonly notDesigned?: { readonly [kind: string]: number };
}

/**
 * The words of Run All's report step: "written", and the cover's headline when the design fails
 * or members are not designed (the step must not read as a clean pass then).
 */
export function reportStepMessage(result: IReportBuildResult): { readonly message: string; readonly warning: boolean } {
	const headline = warningHeadline(result);
	return headline
		? { message: localize('report.writtenHeadline', "written; {0}", headline), warning: true }
		: { message: localize('report.writtenStep', "written"), warning: false };
}

/** How many members the report counts as not designed (no reinforcement), of every kind. */
export function notDesignedCount(result: IReportBuildResult): number {
	return Object.values(result.status?.notDesigned ?? {}).reduce((sum, n) => sum + (typeof n === 'number' ? n : 0), 0);
}

/** The cover's headline when the design fails or members are not designed. */
function warningHeadline(result: IReportBuildResult): string | undefined {
	const status = result.status;
	return status && (status.state === 'fail' || status.state === 'incomplete') && status.headline ? status.headline : undefined;
}

/** The problems of a result, or of an unusable one; empty when a PDF was written. */
export function reportProblems(result: IReportBuildResult | undefined): string[] {
	if (!result || typeof result !== 'object') {
		return [localize('report.noResult', "The report builder returned no result.")];
	}
	if (result.problems?.length) {
		return [...result.problems];
	}
	if (typeof result.path !== 'string' || !result.path) {
		return [localize('report.noPath', "The report builder did not say where it wrote the report.")];
	}
	return [];
}

/** The message shown when the report was written. */
export function reportWrittenMessage(result: IReportBuildResult): string {
	const headline = warningHeadline(result);
	const written = writtenMessage(result);
	return headline ? `${written} ${headline}` : written;
}

function writtenMessage(result: IReportBuildResult): string {
	const warnings = result.warnings?.length ?? 0;
	if (result.format === 'docx') {
		return warnings
			? localize('report.writtenWordWarnings', "Design report written as Word with {0} warning(s); they are listed in its Limitations section.", warnings)
			: localize('report.writtenWord', "Design report written as Word.");
	}
	if (typeof result.pages === 'number') {
		return warnings
			? localize('report.writtenPagesWarnings', "Design report written ({0} pages) with {1} warning(s); they are listed in its Limitations section.", result.pages, warnings)
			: localize('report.writtenPages', "Design report written ({0} pages).", result.pages);
	}
	return warnings
		? localize('report.writtenWarnings', "Design report written with {0} warning(s); they are listed in its Limitations section.", warnings)
		: localize('report.written', "Design report written.");
}
