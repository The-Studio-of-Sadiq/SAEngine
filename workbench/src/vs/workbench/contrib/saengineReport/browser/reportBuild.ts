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
