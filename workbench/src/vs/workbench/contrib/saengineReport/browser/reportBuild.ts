/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/**
 * Builds the printed design report (`11 Exports/report.pdf`) of a project with the Python
 * backend (`saengine.report.build_report`). Registered by the integration that owns the RPC.
 */
export const BUILD_REPORT_COMMAND_ID = 'saengine.report.build';

/** Argument of {@link BUILD_REPORT_COMMAND_ID}. */
export interface IReportBuildRequest {
	/** File system path of the project root (the folder holding the `.saengine` manifest). */
	readonly projectRoot: string;
	/** Where to write the PDF; `<project>/11 Exports/report.pdf` when omitted. */
	readonly outPdf?: string;
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
	if (typeof result.pages === 'number') {
		return warnings
			? localize('report.writtenPagesWarnings', "Design report written ({0} pages) with {1} warning(s); they are listed in its Limitations section.", result.pages, warnings)
			: localize('report.writtenPages', "Design report written ({0} pages).", result.pages);
	}
	return warnings
		? localize('report.writtenWarnings', "Design report written with {0} warning(s); they are listed in its Limitations section.", warnings)
		: localize('report.written', "Design report written.");
}
