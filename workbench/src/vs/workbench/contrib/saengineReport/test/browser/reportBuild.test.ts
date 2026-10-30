/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IReportBuildResult, reportProblems, reportStepMessage, reportWrittenMessage } from '../../browser/reportBuild.js';

suite('SAEngine - Design report', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('problems of a result', () => {
		const written: IReportBuildResult = { path: 'C:\\p\\11 Exports\\report.pdf', pages: 9, warnings: [] };
		assert.deepStrictEqual([
			reportProblems(written),
			reportProblems({ problems: ['There are no analysis results: run the analysis first.'] }),
			reportProblems(undefined).length,
			reportProblems({ pages: 2 }).length,
		], [
			[],
			['There are no analysis results: run the analysis first.'],
			1,
			1,
		]);
	});

	test('message of a written report', () => {
		assert.deepStrictEqual([
			reportWrittenMessage({ path: 'r.pdf', pages: 9, warnings: [] }),
			reportWrittenMessage({ path: 'r.pdf', pages: 9, warnings: ['a', 'b'] }),
			reportWrittenMessage({ path: 'r.pdf' }),
		], [
			'Design report written (9 pages).',
			'Design report written (9 pages) with 2 warning(s); they are listed in its Limitations section.',
			'Design report written.',
		]);
	});

	test('members not designed are named, not passed off as "written" (N-R3)', () => {
		const incomplete: IReportBuildResult = { path: 'r.pdf', pages: 9, status: { state: 'incomplete', headline: 'DESIGN INCOMPLETE: 28 columns and 120 slabs are not designed (no reinforcement); the others pass.', notDesigned: { column: 28, slab: 120 } } };
		assert.deepStrictEqual([
			reportStepMessage(incomplete),
			reportStepMessage({ path: 'r.pdf', status: { state: 'pass', headline: 'Design checks pass: all 10 members.' } }),
			reportWrittenMessage(incomplete),
		], [
			{ message: 'written; DESIGN INCOMPLETE: 28 columns and 120 slabs are not designed (no reinforcement); the others pass.', warning: true },
			{ message: 'written', warning: false },
			'Design report written (9 pages). DESIGN INCOMPLETE: 28 columns and 120 slabs are not designed (no reinforcement); the others pass.',
		]);
	});
});
