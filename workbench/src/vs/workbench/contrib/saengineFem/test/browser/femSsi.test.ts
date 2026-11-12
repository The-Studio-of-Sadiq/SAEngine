/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { comparisonStale, formatDrift, formatStiffness, readSsiComparison, readSsiSprings } from '../../browser/femSsi.js';

suite('SAEngine - FEM soil springs', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const springs = {
		shearModulusRatio: 0.49,
		springs: [{ foundation: 'F1', type: 'isolated', columns: ['C1'], position: [0, 0, -500], Kx: 151000.5, Ky: 160000, Kz: 210000, Krx: 52000, Kry: 81000, Krz: 70000, units: {}, basis: [] }],
		fixedColumns: ['C2', 'C3'],
		notes: ['soil springs: G/G0 = 0.49'],
		nodes: {},
	};

	test('reads the springs and a comparison, defensively', () => {
		const comparison = {
			...springs,
			periods: [{ mode: 1, fixed: 0.3125, ssi: 0.3322, ratio: 1.063 }],
			baseShear: [{ case: 'EX', fixed: 85.85, ssi: 85.85 }],
			drift: [{ case: 'EX', fixed: 0.000202, ssi: 0.000211 }],
			storeyDrift: [{ case: 'EX', level: 3.2, fixed: 0.000053, ssi: 0.000161 }],
			computed: '2026-10-17T12:00:00+00:00',
		};
		assert.deepStrictEqual({
			springs: readSsiSprings(springs),
			comparison: readSsiComparison(comparison)?.periods,
			drift: readSsiComparison(comparison)?.storeyDrift,
			notCompared: readSsiComparison(springs),
			notSprings: readSsiSprings({ periods: [] }),
			junk: readSsiSprings('x'),
		}, {
			springs: { springs: [{ foundation: 'F1', type: 'isolated', columns: ['C1'], k: [151000.5, 160000, 210000, 52000, 81000, 70000] }], shearModulusRatio: 0.49, fixedColumns: ['C2', 'C3'], notes: ['soil springs: G/G0 = 0.49'] },
			comparison: [{ mode: 1, fixed: 0.3125, ssi: 0.3322, ratio: 1.063 }],
			drift: [{ case: 'EX', level: 3.2, fixed: 0.000053, ssi: 0.000161 }],
			notCompared: undefined,
			notSprings: undefined,
			junk: undefined,
		});
	});

	test('a comparison older than the model or its results is stale', () => {
		assert.deepStrictEqual(
			[comparisonStale(300, 100, 200), comparisonStale(300, 400, 200), comparisonStale(300, 100, 400), comparisonStale(undefined, 100, 200), comparisonStale(300, 100, undefined)],
			[false, true, true, true, true],
		);
	});

	test('formats drifts as 1/n and stiffnesses in three figures', () => {
		assert.deepStrictEqual(
			[formatDrift(0.0002), formatDrift(-0.004), formatDrift(0), formatStiffness(151000.5), formatStiffness(5200.4)],
			['1/5000', '1/250', '0', '1.51e+5', '5200'],
		);
	});
});
