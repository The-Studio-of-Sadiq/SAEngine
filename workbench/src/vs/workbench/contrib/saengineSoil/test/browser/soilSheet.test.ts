/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IBorehole, ISoilSample } from '../../browser/soilDocument.js';
import { consolidationResult, directShearResult, grainSizeResult, labSheet, triaxialResult } from '../../browser/soilLabTests.js';
import { deriveN, formatTsv, ISheet, matchOption, moveCell, parseTsv, pasteAddsRows, pasteWrites, SampleSheet, sampleRows, StrataSheet } from '../../browser/soilSheet.js';

/** A synthetic borehole: a clay over a sand, one legacy SPT record (N only) with its sample. */
function borehole(): IBorehole {
	return {
		id: 'BH-1', x: 0, y: 0, waterTable: 1500, depth: 9000,
		layers: [
			{ top: 0, bottom: 3000, description: 'Soft grey silty clay', soilType: 'clay', uscs: 'CL' },
			{ top: 3000, bottom: 9000, description: 'Loose silty fine sand', soilType: 'sand', uscs: 'SM' },
		],
		spt: [{ depth: 1500, N: 3 }],
		samples: [{ depth: 1500, number: 'D-1', type: 'SPT', moisture: 32 }],
	};
}

/** Every row of a sheet as the grid shows it. */
function shown(sheet: ISheet, columns: readonly string[]): string[][] {
	const rows: string[][] = [];
	for (let row = 0; row < sheet.rowCount(); row++) {
		rows.push(columns.map(id => sheet.text(row, sheet.columns.find(c => c.id === id)!)));
	}
	return rows;
}

function column(sheet: ISheet, id: string) {
	return sheet.columns.find(c => c.id === id)!;
}

suite('SAEngine - Soil log sheet', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads cells copied from Excel: tabs, line breaks, blanks, quotes, decimals', () => {
		assert.deepStrictEqual([
			parseTsv('1.5\t\t12\r\n3.0\t4\t\r\n'),
			parseTsv('"Grey\tclay"\tCL\n"say ""soft"""\n'),
			parseTsv('"two\r\nlines"\tx'),
			parseTsv(''),
			parseTsv(' 4.50 \t 0.075 '),
		], [
			[['1.5', '', '12'], ['3.0', '4', '']],
			[['Grey\tclay', 'CL'], ['say "soft"']],
			[['two\r\nlines', 'x']],
			[],
			[['4.50', '0.075']],
		]);
		assert.strictEqual(formatTsv([['a', 'b'], ['c\td', '']]), 'a\tb\r\n"c\td"\t\r\n');
	});

	test('moves between cells as Excel does, over the shown columns only', () => {
		const visible = [0, 1, 3]; // column 2 is in a collapsed group
		const rows = 2; // and the row for a new entry below them
		assert.deepStrictEqual([
			moveCell({ row: 0, column: 1 }, 'right', visible, rows),
			moveCell({ row: 0, column: 3 }, 'right', visible, rows),
			moveCell({ row: 0, column: 3 }, 'tab', visible, rows),
			moveCell({ row: 1, column: 0 }, 'shiftTab', visible, rows),
			moveCell({ row: 0, column: 1 }, 'enter', visible, rows),
			moveCell({ row: 1, column: 1 }, 'down', visible, rows),
			moveCell({ row: 2, column: 1 }, 'down', visible, rows),
			moveCell({ row: 1, column: 1 }, 'down', visible, rows, false),
			moveCell({ row: 0, column: 1 }, 'up', visible, rows),
			moveCell({ row: 1, column: 3 }, 'home', visible, rows),
			moveCell({ row: 0, column: 0 }, 'bottom', visible, rows),
			moveCell({ row: 0, column: 2 }, 'left', visible, rows),
		], [
			{ row: 0, column: 3 },
			{ row: 0, column: 3 },
			{ row: 1, column: 0 },
			{ row: 0, column: 3 },
			{ row: 1, column: 1 },
			{ row: 2, column: 1 },
			{ row: 2, column: 1 },
			{ row: 1, column: 1 },
			{ row: 0, column: 1 },
			{ row: 1, column: 0 },
			{ row: 2, column: 0 },
			{ row: 0, column: 1 },
		]);
		assert.deepStrictEqual([pasteAddsRows(3, 4, 5), pasteAddsRows(0, 2, 5)], [2, 0]);
	});

	test('works out N from the increments: N1 + N2, refusal in N1', () => {
		assert.deepStrictEqual([
			deriveN({ N1: 6, N2: 7 }),
			deriveN({ N1: 50, refusal: true }),
			deriveN({ N1: 5 }),
			deriveN({}),
			deriveN({ N1: 22, N2: 28, refusal: true }),
			// "50/100 mm": 50 blows for 100 mm of the test drive, 150 for 300 mm.
			deriveN({ refusal: { blows: 50, penetration: 100 } }),
			deriveN({ refusal: { blows: 120, penetration: 50 } }),
		], [13, 50, undefined, undefined, 50, 150, 300]);
	});

	test('puts the SPT record and the sample of one depth in one row', () => {
		const b = borehole();
		b.spt.push({ depth: 4500, N: 8 });
		b.samples.push({ depth: 3000, type: 'UD' });
		assert.deepStrictEqual(sampleRows(b).map(r => [r.depth, !!r.spt, !!r.sample]), [[1500, true, true], [3000, false, true], [4500, true, false]]);
	});

	test('edits a legacy record into increments: its entered N stays and is flagged until deleted', () => {
		const b = borehole();
		const sheet = new SampleSheet(b);
		const before = { n: sheet.text(0, column(sheet, 'N')), readOnly: sheet.isReadOnly(0, column(sheet, 'N')) };
		const result = sheet.write([{ row: 0, column: 'seat', text: '2' }, { row: 0, column: 'N1', text: '4' }, { row: 0, column: 'N2', text: '5' }]);
		const entered = {
			spt: structuredClone(b.spt),
			n: sheet.text(0, column(sheet, 'N')),
			derived: sheet.isDerived(0, column(sheet, 'N')),
			problem: sheet.problem(0, column(sheet, 'N')),
		};
		// Deleting the entered N: N is worked out from the increments, and not stored.
		sheet.write([{ row: 0, column: 'N', text: '' }]);
		assert.deepStrictEqual({
			before,
			result,
			entered,
			spt: b.spt,
			n: sheet.text(0, column(sheet, 'N')),
			derived: sheet.isDerived(0, column(sheet, 'N')),
			readOnly: sheet.isReadOnly(0, column(sheet, 'N')),
			hint: sheet.hint(0, column(sheet, 'N')),
			to: [sheet.text(0, column(sheet, 'depthTo')), sheet.isDerived(0, column(sheet, 'depthTo'))],
		}, {
			before: { n: '3', readOnly: false },
			result: { written: 3, added: 0, errors: [], rows: new Map([[0, 0]]) },
			entered: {
				spt: [{ depth: 1500, N: 3, seat: 2, N1: 4, N2: 5 }],
				n: '3',
				derived: false,
				problem: { message: 'N 3 is entered, but N1 + N2 = 9; N 3 is used. Delete it to use N1 + N2.', severity: 'warning' },
			},
			spt: [{ depth: 1500, seat: 2, N1: 4, N2: 5 }],
			n: '9',
			derived: true,
			readOnly: false,
			hint: 'N = N1 + N2, worked out (not stored); type a value only to enter the log\'s own N.',
			to: ['1.95', true],
		});
		// Clearing the increments clears the N they gave: the record goes, the sample stays.
		sheet.write([{ row: 0, column: 'seat', text: '' }, { row: 0, column: 'N1', text: '' }, { row: 0, column: 'N2', text: '' }]);
		assert.deepStrictEqual({ spt: b.spt, samples: b.samples.length }, { spt: [], samples: 1 });
	});

	test('keeps the N of the log when it differs from N1 + N2, through edits of the row', () => {
		const b = borehole();
		b.spt = [{ depth: 1500, seat: 4, N1: 10, N2: 12, N: 25 }];
		b.samples = []; // the split spoon's recovery is then the SPT record's
		const sheet = new SampleSheet(b);
		const problem = () => sheet.problem(0, column(sheet, 'N'));
		const shownBefore = [sheet.text(0, column(sheet, 'N')), sheet.isDerived(0, column(sheet, 'N')), sheet.hint(0, column(sheet, 'N')), problem()?.severity];
		sheet.write([{ row: 0, column: 'recovery', text: '80' }]);
		assert.deepStrictEqual({ shownBefore, spt: b.spt, severity: problem()?.severity }, {
			shownBefore: ['25', false, undefined, 'warning'],
			spt: [{ depth: 1500, seat: 4, N1: 10, N2: 12, N: 25, recovery: 80 }],
			severity: 'warning',
		});
	});

	test('never stores the worked-out N: typed or pasted equal to N1 + N2, or left by an older file', () => {
		const b = borehole();
		b.spt = [{ depth: 1500, N1: 4, N2: 5, N: 9 }];
		const sheet = new SampleSheet(b);
		// The older file's N 9 was N1 + N2: correcting N2 makes it follow.
		sheet.write([{ row: 0, column: 'N2', text: '7' }]);
		const corrected = structuredClone(b.spt);
		sheet.write([{ row: 1, column: 'N1', text: '10' }, { row: 1, column: 'N2', text: '12' }, { row: 1, column: 'N', text: '22' }]);
		assert.deepStrictEqual({ corrected, spt: b.spt, n: sheet.text(1, column(sheet, 'N')) }, {
			corrected: [{ depth: 1500, N1: 4, N2: 7 }],
			spt: [{ depth: 1500, N1: 4, N2: 7 }, { depth: 3000, N1: 10, N2: 12 }],
			n: '22',
		});
	});

	test('marks red the records the backend cannot read, amber what it reads and reports', () => {
		const b = borehole();
		b.spt = [
			{ depth: 1500, N1: 10 }, // only one increment, no N
			{ depth: 3000, seat: 4 }, // only the seat
			{ depth: 4500, N1: 10, N: 20 }, // one increment, an entered N
			{ depth: 6000, seat: 4, N1: 10, N2: 12 }, // complete
		];
		b.samples = [];
		const sheet = new SampleSheet(b);
		const severities = [0, 1, 2, 3].map(row => ['N1', 'N2', 'N'].map(id => sheet.problem(row, column(sheet, id))?.severity));
		assert.deepStrictEqual(severities, [
			[undefined, 'error', undefined],
			['error', undefined, undefined],
			[undefined, 'warning', undefined],
			[undefined, undefined, undefined],
		]);
	});

	test('shows and edits the energy ratio of a test', () => {
		const b = borehole();
		b.spt.push({ depth: 3000, N: 2, energyRatio: 70 });
		const sheet = new SampleSheet(b);
		const shownBefore = sheet.text(1, column(sheet, 'energyRatio'));
		const result = sheet.write([{ row: 1, column: 'energyRatio', text: '55' }, { row: 0, column: 'energyRatio', text: '0' }]);
		assert.deepStrictEqual({ shownBefore, er: b.spt.map(s => s.energyRatio), errors: result.errors.map(e => e.column) }, {
			shownBefore: '70',
			er: [undefined, 55],
			errors: ['energyRatio'],
		});
	});

	test('pastes a block from Excel into new rows', () => {
		const b = borehole();
		const sheet = new SampleSheet(b);
		const visible = sheet.columns.map((_, i) => i);
		const block = parseTsv([
			'3.0\t3.45\tD-2\tSPT\t2\t4\t6\t10\t\t90\t\t\t\t28.5', // ER, description and USCS blank
			'4.5\t\tUD-1\tUD\t\t\t\t\t\t\t\t\t',
			'6\t6.45\tD-3\tSPT\t12\t50\t\t\tR\t60',
		].join('\r\n'));
		const writes = pasteWrites(sheet, { row: 1, column: 0 }, block, visible);
		const result = sheet.write(writes);
		assert.deepStrictEqual({
			added: result.added,
			errors: result.errors,
			rows: shown(sheet, ['depth', 'depthTo', 'number', 'type', 'seat', 'N1', 'N2', 'N', 'refusal', 'recovery', 'description', 'moisture']),
			descriptions: b.layers.map(l => l.description),
		}, {
			added: 3,
			errors: [],
			rows: [
				['1.5', '1.95', 'D-1', 'SPT', '', '', '', '3', '', '', 'Soft grey silty clay', '32'],
				['3', '3.45', 'D-2', 'SPT', '2', '4', '6', '10', '', '90', 'Loose silty fine sand', '28.5'],
				['4.5', '', 'UD-1', 'UD', '', '', '', '', '', '', 'Loose silty fine sand', ''],
				['6', '6.45', 'D-3', 'SPT', '12', '50', '', '50', 'R', '60', 'Loose silty fine sand', ''],
			],
			// The pasted blanks leave the strata's descriptions alone.
			descriptions: ['Soft grey silty clay', 'Loose silty fine sand'],
		});
		assert.deepStrictEqual(b.spt.map(s => s.depth), [1500, 3000, 6000]);
	});

	test('says where a typed row went after the depth order moved it', () => {
		const b = borehole();
		b.spt.push({ depth: 30000, N: 62 });
		const sheet = new SampleSheet(b);
		// Typed in the "New row" below the 30 m record: a depth above the others.
		const added = sheet.write([{ row: 2, column: 'depth', text: '0.75' }]);
		// The grid goes on from where the row is now; before, it went on at row 2, the 30 m record.
		const at = added.rows?.get(2);
		const next = sheet.write([{ row: at ?? 2, column: 'N1', text: '5' }]);
		const moved = new StrataSheet(b, 0).write([{ row: 0, column: 'top', text: '4' }, { row: 0, column: 'bottom', text: '6' }]);
		assert.deepStrictEqual({
			at,
			next: next.rows?.get(0),
			spt: b.spt.map(s => ({ depth: s.depth, N1: s.N1, N: s.N })),
			// A stratum whose top was changed below the next one is sorted after it.
			stratum: moved.rows?.get(0),
		}, {
			at: 0,
			next: 0,
			spt: [{ depth: 750, N1: 5, N: undefined }, { depth: 1500, N1: undefined, N: 3 }, { depth: 30000, N1: undefined, N: 62 }],
			stratum: 1,
		});
	});

	test('refuses what is not a value and keeps the rest', () => {
		const b = borehole();
		const sheet = new SampleSheet(b);
		const result = sheet.write([
			{ row: 0, column: 'moisture', text: '2,5' },
			{ row: 0, column: 'N1', text: '4.5' },
			{ row: 0, column: 'refusal', text: 'maybe' },
			{ row: 0, column: 'liquidLimit', text: '41' },
			{ row: 0, column: 'PI', text: '20' },
		]);
		assert.deepStrictEqual({
			errors: result.errors.map(e => e.column),
			written: result.written,
			ll: b.samples[0].liquidLimit,
		}, { errors: ['moisture', 'N1', 'refusal'], written: 1, ll: 41 });
	});

	test('marks refusal blows, overlapping rows and PL above LL', () => {
		const b = borehole();
		b.spt = [{ depth: 1500, N: 0, seat: 3, N1: 55 }, { depth: 1800, N: 9 }];
		b.samples = [{ depth: 1500, liquidLimit: 30, plasticLimit: 35 }];
		const sheet = new SampleSheet(b);
		const problem = (row: number, id: string) => sheet.problem(row, column(sheet, id))?.severity;
		assert.deepStrictEqual({
			n1: problem(0, 'N1'),
			n2: problem(0, 'N2'),
			pl: problem(0, 'plasticLimit'),
			ll: problem(0, 'liquidLimit'),
			overlap: problem(1, 'depth'),
			first: problem(0, 'depth'),
			pi: sheet.text(0, column(sheet, 'PI')),
		}, { n1: 'error', n2: 'warning', pl: 'error', ll: undefined, overlap: 'error', first: undefined, pi: '-5' });
	});

	test('the description and USCS of a row are its stratum\'s', () => {
		const b = borehole();
		const sheet = new SampleSheet(b);
		sheet.write([{ row: 0, column: 'description', text: 'Very soft grey clay' }, { row: 0, column: 'uscs', text: 'CH' }]);
		assert.deepStrictEqual([b.layers[0].description, b.layers[0].uscs, sheet.hint(0, column(sheet, 'uscs'))], ['Very soft grey clay', 'CH', 'Of the stratum 0–3 m']);
	});

	test('an SPT row keeps its split spoon number, recovery and refusal itself', () => {
		const b = borehole();
		b.spt.push({ depth: 4500, N1: 20, N2: 30 });
		const sheet = new SampleSheet(b);
		const result = sheet.write([
			{ row: 1, column: 'number', text: 'D-4' },
			{ row: 1, column: 'recovery', text: '85' },
			{ row: 1, column: 'refusal', text: '50/200 mm' },
			{ row: 1, column: 'N2', text: '' },
		]);
		assert.deepStrictEqual({
			errors: result.errors,
			spt: b.spt[1],
			samples: b.samples.length,
			shown: shown(sheet, ['number', 'recovery', 'refusal', 'N']),
		}, {
			errors: [],
			spt: { depth: 4500, N1: 20, sampleNumber: 'D-4', recovery: 85, refusal: { blows: 50, penetration: 200 } },
			samples: 1,
			shown: [['D-1', '', '', '3'], ['D-4', '85', '50/200', '75']],
		});
	});

	test('a refusal without increments keeps an N entered for it, and a worked-out N follows the refusal', () => {
		const b = borehole();
		b.spt.push({ depth: 4500, refusal: { blows: 50, penetration: 100 }, N: 150 });
		const sheet = new SampleSheet(b);
		sheet.write([{ row: 1, column: 'refusal', text: '50/150' }]);
		const followed = [b.spt[1].N, sheet.text(1, column(sheet, 'N'))];
		sheet.write([{ row: 1, column: 'N', text: '80' }]);
		const entered = [b.spt[1].N, sheet.text(1, column(sheet, 'N')), sheet.problem(1, column(sheet, 'N'))?.severity];
		// More than 300 blows is not a refusal the backend reads (SptRefusal.blows <= 300).
		const tooMany = sheet.write([{ row: 1, column: 'refusal', text: '500/100' }]).errors.map(e => e.column);
		assert.deepStrictEqual({ followed, entered, tooMany, refusal: b.spt[1].refusal }, {
			followed: [undefined, '100'],
			entered: [80, '80', 'warning'],
			tooMany: ['refusal'],
			refusal: { blows: 50, penetration: 150 },
		});
	});

	test('removes rows with their records', () => {
		const b = borehole();
		b.spt.push({ depth: 3000, N: 6 });
		const sheet = new SampleSheet(b);
		sheet.removeRows([0]);
		assert.deepStrictEqual({ spt: b.spt, samples: b.samples, rows: sheet.rowCount() }, { spt: [{ depth: 3000, N: 6 }], samples: [], rows: 1 });
	});

	test('edits the strata: soil types by name or a unique prefix, new layers below', () => {
		const b = borehole();
		const sheet = new StrataSheet(b, 0);
		const result = sheet.write([
			{ row: 2, column: 'top', text: '9' },
			{ row: 2, column: 'bottom', text: '12' },
			{ row: 2, column: 'soilType', text: 'gr' },
			{ row: 1, column: 'soilType', text: 's' },
			{ row: 0, column: 'soilType', text: 'Silt' },
		]);
		assert.deepStrictEqual({
			added: result.added,
			errors: result.errors.map(e => `${e.row} ${e.column}`),
			types: b.layers.map(l => l.soilType),
			last: b.layers[2],
			shown: sheet.text(2, column(sheet, 'soilType')),
			options: [matchOption(column(sheet, 'soilType').options!, 'SAND'), matchOption(column(sheet, 'soilType').options!, 'o')],
		}, {
			added: 1,
			errors: ['1 soilType'],
			types: ['silt', 'sand', 'gravel'],
			last: { top: 9000, bottom: 12000, description: '', soilType: 'gravel' },
			shown: 'Gravel',
			options: ['sand', 'organic'],
		});
	});

	test('lab test lists are made on the first entry and dropped when emptied', () => {
		const sample: ISoilSample = { depth: 1500 };
		const sheet = labSheet(sample, 'grainSize');
		const before = { rows: sheet.rowCount(), keys: Object.keys(sample) };
		sheet.write(pasteWrites(sheet, { row: 0, column: 0 }, parseTsv('4.75\t100\n0.075\t30\n2\t95\n'), [0, 1]));
		const sorted = sample.grainSize?.sieves.map(s => s.size);
		sheet.removeRows([0, 1, 2]);
		assert.deepStrictEqual({ before, sorted, after: Object.keys(sample) }, { before: { rows: 0, keys: ['depth'] }, sorted: [4.75, 2, 0.075], after: ['depth'] });
	});
});

suite('SAEngine - Soil lab tests', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const round = (value: number | undefined, decimals = 4) => value === undefined ? undefined : Number(value.toFixed(decimals));

	test('grain size: fines, D10, D30, D60, Cu and Cc on the log of the size', () => {
		// D60 between 0.425 mm (70%) and 0.075 mm (30%): log D = log 0.075 + 0.75 (log 0.425 − log 0.075) → 0.27546 mm.
		// D10 between 0.075 mm (30%) and 0.002 mm (5%): log D = log 0.002 + 0.2 (log 0.075 − log 0.002) → 0.0041289 mm.
		const r = grainSizeResult([{ size: 0.002, passing: 5 }, { size: 4.75, passing: 100 }, { size: 2, passing: 95 }, { size: 0.425, passing: 70 }, { size: 0.075, passing: 30 }]);
		assert.deepStrictEqual({ fines: r.fines, D10: round(r.D10, 7), D30: r.D30, D60: round(r.D60, 5), Cu: round(r.Cu, 2), Cc: round(r.Cc, 3) },
			{ fines: 30, D10: 0.0041289, D30: 0.075, D60: 0.27546, Cu: 66.71, Cc: 4.946 });
	});

	test('consolidation: Cc of the steepest loading step, Cr of the unloading', () => {
		// 100 → 200 kPa: Δe 0.06 over log 2 → Cc 0.1993; 800 → 50 kPa: Δe 0.04 over log 16 → Cr 0.0332.
		const r = consolidationResult([
			{ pressure: 25, e: 0.95 }, { pressure: 50, e: 0.94 }, { pressure: 100, e: 0.92 }, { pressure: 200, e: 0.86 },
			{ pressure: 400, e: 0.80 }, { pressure: 800, e: 0.74 }, { pressure: 200, e: 0.76 }, { pressure: 50, e: 0.78 },
		]);
		assert.deepStrictEqual({ Cc: round(r.Cc), Cr: round(r.Cr), e0: r.e0 }, { Cc: 0.1993, Cr: 0.0332, e0: 0.95 });
	});

	test('shear: the Mohr-Coulomb line of direct shear and triaxial tests', () => {
		// Direct shear on τ = 15 + 0.5 σ: c′ 15 kPa, φ′ = atan 0.5 = 26.565°.
		const direct = directShearResult([{ normal: 50, shear: 40 }, { normal: 100, shear: 65 }, { normal: 200, shear: 115 }]);
		// c′ 10 kPa, φ′ 30°: σ1 = 3 σ3 + 2 · 10 · √3, so σ3 100 → Δσ 234.641, σ3 200 → Δσ 434.641.
		const cd = triaxialResult('CD', [{ cell: 100, deviator: 234.641016 }, { cell: 200, deviator: 434.641016 }]);
		// The same effective stresses through the pore pressures of a CU test.
		const cu = triaxialResult('CU', [{ cell: 150, deviator: 234.641016, porePressure: 50 }, { cell: 300, deviator: 434.641016, porePressure: 100 }]);
		const uu = triaxialResult('UU', [{ cell: 50, deviator: 60 }, { cell: 100, deviator: 64 }, { cell: 150, deviator: 62 }]);
		assert.deepStrictEqual({
			direct: [round(direct.c, 3), round(direct.phi, 3)],
			cd: [round(cd.c, 3), round(cd.phi, 3)],
			cu: [round(cu.c, 3), round(cu.phi, 3)],
			uu: uu.cu,
			one: directShearResult([{ normal: 50, shear: 40 }]),
		}, { direct: [15, 26.565], cd: [10, 30], cu: [10, 30], uu: 31, one: {} });
	});
});
