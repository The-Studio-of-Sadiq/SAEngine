/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	countRows, defaultImportName, describeCarried, describeImportSummary, describeItem, describeNotCarried, formatLabel, importFilters, needsReview, readImportResult, readLastImport, sameFolder, uniqueImportName,
} from '../../browser/structuralImportModel.js';

/*
 * Synthetic answers of `saengine.import.structural` (stand-in data: the backend's importers are
 * written in the same round): a three-storey ETABS frame in kip-ft.
 */
const ANSWER = {
	root: 'C:\\Projects\\Office Frame',
	report: {
		format: 'etabs',
		units: 'kip-ft -> kN-m',
		counts: { stories: 3, columns: 24, beams: 36, braces: 4, slabs: 9, walls: 0, sections: 7, materials: 3, loads: 58, combinations: 6, joints: 48, links: 0 },
		approximated: [
			{ kind: 'section', message: 'Tapered sections imported as their mid section', count: 2, examples: ['TAP1', 'TAP2'] },
			'Diaphragm D1 taken as rigid',
		],
		skipped: [
			{ kind: 'link', reason: 'Link elements are not supported', items: ['LK1', 'LK2', 'LK3', 'LK4', 'LK5', 'LK6', 'LK7'] },
		],
		warnings: [{ message: 'Load pattern WIND has no loads' }],
	},
};

/*
 * The report the ETABS importer writes for its synthetic test model
 * (python/tests/data/import/two_story_frame.e2k: read_e2k(...).report.to_dict(), copied as it is).
 */
const E2K_REPORT = {
	schema: 'saengine.importReport/1',
	source: { program: 'ETABS', file: 'two_story_frame.e2k', version: '21.0.0', units: 'kn-m', materials: 3 },
	imported: { stories: 3, gridLines: 5, columns: 12, beams: 14, braces: 1, slabs: 4, walls: 1, supports: 6, areaLoads: 2, combinations: 3, objectTypes: 5, materials: 3 },
	approximated: [
		{ what: 'beam bars left to SAEngine\'s design (e2k gives covers only)', count: 1, examples: ['B300x500'] },
		{ what: 'end releases ignored (members are continuous)', count: 1, examples: ['D1-Story1'] },
		{ what: 'wind and seismic patterns: SAEngine applies its own BNBC loads in their place', count: 2, examples: ['EQX', 'EQY'] },
		{ what: 'combinations with the same factors as another one dropped', count: 1, examples: ['U4'] },
	],
	skipped: [
		{ what: 'sections named from a steel database without their dimensions', count: 1, examples: ['W14X90 (W14X90)'] },
		{ what: 'point loads', count: 1, examples: ['5-Story2 Live'] },
		{ what: 'frame loads', count: 1, examples: ['B3-Story1 SDL'] },
		{ what: 'envelope, SRSS and absolute combinations', count: 1, examples: ['ENV (Envelope)'] },
	],
	warnings: ['Wind and earthquake loads are SAEngine\'s own from the BNBC settings: check the site, occupancy and structural system in 02 Project Settings.'],
	loads: { carriedKN: { D: 180.0, L: 120.0, Lr: 60.0 }, notCarriedKN: { L: 20.0, D: 60.0 } },
};

suite('SAEngine structural import model', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('names the project from the file', () => {
		assert.deepStrictEqual(
			[defaultImportName('C:\\m\\Office: Block A.e2k'), defaultImportName('/m/frame.std'), defaultImportName('.e2k'), formatLabel('staad'), formatLabel('robot')],
			['Office Block A', 'frame', 'Imported Model', 'STAAD.Pro', 'robot'],
		);
		const taken = new Set(['frame', 'frame (2)']);
		assert.strictEqual(uniqueImportName('frame', n => taken.has(n)), 'frame (3)');
		assert.deepStrictEqual(importFilters()[0].extensions, ['e2k', '$et', 'std', 's2k', '$2k']);
	});

	test('reads the report: counts, approximated, skipped, warnings', () => {
		const result = readImportResult(ANSWER);
		assert.deepStrictEqual({
			root: result.root,
			problems: result.problems,
			counts: countRows(result.report).map(r => `${r.label} ${r.count}`),
			approximated: result.report.approximated.map(describeItem),
			skipped: result.report.skipped.map(describeItem),
			warnings: result.report.warnings.map(describeItem),
			summary: describeImportSummary(result.report),
			review: needsReview(result.report),
		}, {
			root: 'C:\\Projects\\Office Frame',
			problems: [],
			counts: ['Stories 3', 'Columns 24', 'Beams 36', 'Braces 4', 'Inclined members 0', 'Slabs 9', 'Walls 0', 'Sections 7', 'Materials 3', 'Area loads 58', 'Load cases 0', 'Load combinations 6', 'Supports 0', 'Joints 48'],
			approximated: ['Tapered sections imported as their mid section (2: TAP1, TAP2)', 'Diaphragm D1 taken as rigid'],
			skipped: ['Link elements are not supported (7: LK1, LK2, LK3, LK4, LK5, ...)'],
			warnings: ['Load pattern WIND has no loads'],
			summary: 'Imported from ETABS: 3 stories, 64 frame members, 9 slabs. 3 approximated, 7 skipped, 1 warning.',
			review: true,
		});
	});

	test('reads the importers\' own report (ImportReport.to_dict) and says what load was not carried over', () => {
		const result = readImportResult({ root: 'C:\\Projects\\two_story_frame', report: E2K_REPORT });
		const report = result.report;
		const read = {
			facts: [formatLabel(report.format), report.version, report.units, report.source, report.unread],
			counts: countRows(report).map(r => `${r.label} ${r.count}`),
			approximated: report.approximated.map(describeItem),
			skipped: report.skipped.map(describeItem),
			warnings: report.warnings.length,
			notCarried: describeNotCarried(report),
			carried: describeCarried(report),
			summary: describeImportSummary(report),
			review: needsReview(report),
		};
		assert.deepStrictEqual(read, {
			facts: ['ETABS', '21.0.0', 'kn-m', 'two_story_frame.e2k', 0],
			counts: ['Stories 3', 'Columns 12', 'Beams 14', 'Braces 1', 'Inclined members 0', 'Slabs 4', 'Walls 1', 'Sections 5', 'Materials 3', 'Area loads 2', 'Load cases 0', 'Load combinations 3', 'Supports 6', 'Grid lines 5'],
			approximated: [
				'beam bars left to SAEngine\'s design (e2k gives covers only) (1: B300x500)',
				'end releases ignored (members are continuous) (1: D1-Story1)',
				'wind and seismic patterns: SAEngine applies its own BNBC loads in their place (2: EQX, EQY)',
				'combinations with the same factors as another one dropped (1: U4)',
			],
			skipped: [
				'sections named from a steel database without their dimensions (1: W14X90 (W14X90))',
				'point loads (1: 5-Story2 Live)',
				'frame loads (1: B3-Story1 SDL)',
				'envelope, SRSS and absolute combinations (1: ENV (Envelope))',
			],
			warnings: 1,
			notCarried: 'D 60 kN, L 20 kN',
			carried: 'D 180 kN, L 120 kN, Lr 60 kN',
			summary: 'Imported from ETABS: 3 stories, 27 frame members, 4 slabs, 1 wall. 80 kN of load not carried over, 5 approximated, 4 skipped, 1 warning.',
			review: true,
		});
		// Stored as read, it reads back the same (the last import in application storage).
		assert.deepStrictEqual(readLastImport(JSON.stringify({ root: 'C:\\P', time: 1, report }))?.report, report);
		// Lines of a shape the UI does not know are counted, not dropped, and the import needs review.
		const odd = readImportResult({ report: { skipped: [{ id: 7 }], imported: {} } }).report;
		assert.deepStrictEqual([odd.unread, needsReview(odd)], [1, true]);
		assert.deepStrictEqual(['STAAD.Pro', 'SAP2000'].map(formatLabel), ['STAAD.Pro', 'SAP2000']);
	});

	test('a failed import has no root and says why; a missing report is empty', () => {
		const result = readImportResult({ problems: ['Line 12: unknown unit "furlong"'], error: 'parse failed' });
		assert.deepStrictEqual({ root: result.root, problems: result.problems, review: needsReview(result.report), summary: describeImportSummary(result.report) }, {
			root: undefined,
			problems: ['Line 12: unknown unit "furlong"', 'parse failed'],
			review: false,
			summary: 'Imported from unknown format: 0 stories, 0 frame members, 0 slabs.',
		});
	});

	test('stores the last import and compares folders', () => {
		const raw = JSON.stringify({ root: 'C:\\P\\A', file: 'C:\\m\\a.std', time: 5, report: ANSWER.report, pending: true });
		const entry = readLastImport(raw);
		assert.deepStrictEqual([entry?.root, entry?.pending, entry?.report.counts.beams, readLastImport('{'), readLastImport(undefined)], ['C:\\P\\A', true, 36, undefined, undefined]);
		assert.deepStrictEqual([sameFolder('C:\\P\\A\\', 'c:/p/a'), sameFolder('C:\\P\\A', 'C:\\P\\AB')], [true, false]);
	});
});
