/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IFemSeismicDesign, seismicSection, towerRows } from '../../browser/femSeismicDesign.js';

suite('SAEngine FEM - towers on a podium', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	const design: IFemSeismicDesign = {
		available: true,
		towers: {
			podium: 3.2,
			towers: [
				{
					id: 'T1',
					name: 'Tower 1',
					period: { X: { period: 1.236, mode: 2, massRatio: 0.71 }, Y: { period: 1.1, mode: 3 } },
					baseShear: { X: { static: 1500, dynamic: 1200, scale: 1.0625 }, Y: { static: 1500, dynamic: 1400, scale: 1 } },
					drift: [
						{ direction: 'X', bottom: 3.2, top: 6.4, ratio: 0.004, ok: true },
						{ direction: 'Y', bottom: 3.2, top: 6.4, ratio: 0.0062, ok: true },
					],
					torsionalIrregularity: [{ direction: 'X', bottom: 3.2, top: 6.4, ratio: 1.31, irregular: true, extreme: false }],
				},
			],
		},
	};

	test('one row per tower: periods, scaled shear, largest drift and torsion', () => {
		const [row] = towerRows(design);
		assert.strictEqual(row.name, 'Tower 1');
		assert.ok(row.value.includes('1.24 s X'), row.value);
		assert.ok(row.value.includes('× 1.06'), row.value);
		assert.ok(row.value.includes('0.62 % Y'), row.value);
		assert.ok(row.value.includes('1.31 X (irregular)'), row.value);
	});

	test('the seismic section lists the towers under their own heading', () => {
		const items = seismicSection(design, undefined, false);
		const heading = items.findIndex(i => i.kind === 'heading' && i.text === 'Towers on the Podium');
		assert.ok(heading > 0);
		assert.deepStrictEqual(items[heading + 1], { kind: 'row', name: 'Tower 1', value: towerRows(design)[0].value });
	});

	test('no towers, no rows', () => {
		assert.deepStrictEqual(towerRows({ available: true }), []);
		assert.deepStrictEqual(towerRows({ ...design, available: false }), []);
	});
});
