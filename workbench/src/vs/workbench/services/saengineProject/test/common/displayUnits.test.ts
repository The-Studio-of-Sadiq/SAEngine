/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { displayUnit, feetInches, formatQuantity, fromDisplay, headingWithUnit, IDisplayUnits, parseList, parseQuantity, readDisplayUnits, SI_UNITS_SETTING, toDisplay } from '../../common/displayUnits.js';

const US: IDisplayUnits = { system: 'USCustomary', choices: {} };

function close(actual: number | undefined, expected: number, message?: string): void {
	assert.ok(actual !== undefined && Math.abs(actual - expected) <= 1e-9 * Math.max(1, Math.abs(expected)), `${message ?? ''} ${actual} ≠ ${expected}`);
}

suite('SAEngine - display units (C13)', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('conversion pins, both ways (NIST SP 811 definitions)', () => {
		const pins: [number, string, number, string][] = [
			[1, 'm', 3.280839895, 'ft'],
			[25.4, 'mm', 1, 'in'],
			[4.4482216152605, 'kN', 1, 'kip'],
			[6.894757293168, 'MPa', 1, 'ksi'],
			[0.04788025898, 'kN/m²', 1, 'psf'],
			[1.3558179483314, 'kN·m', 1, 'kip·ft'],
			[14.593902937206, 'kN/m', 1, 'kip/ft'],
			[645.16, 'mm²', 1, 'in²'],
			[1, 'm³', 35.314666721, 'ft³'],
			[0.45359237, 'kg', 1, 'lb'],
		];
		for (const [si, siUnit, us, usUnit] of pins) {
			assert.strictEqual(displayUnit(siUnit, US), usUnit);
			close(toDisplay(si, siUnit, US), us, siUnit);
			close(fromDisplay(us, siUnit, US), si, siUnit);
		}
		assert.strictEqual(toDisplay(250, 'mm', SI_UNITS_SETTING), 250);
		assert.strictEqual(displayUnit('°C', US), '°C');
	});

	test('choices, text and typed values', () => {
		const lbf = readDisplayUnits({ system: 'USCustomary', force: 'lbf', volume: 'yd³' });
		assert.strictEqual(displayUnit('kN', lbf), 'lbf');
		assert.strictEqual(displayUnit('m³', lbf), 'yd³');
		assert.strictEqual(formatQuantity(250, 'mm', { units: US }), '9.84 in');
		assert.strictEqual(formatQuantity(28, 'MPa', { units: US }), '4.06 ksi');
		assert.strictEqual(formatQuantity(250, 'mm', { units: SI_UNITS_SETTING }), '250 mm');
		assert.strictEqual(feetInches(3810), '12\'-6"');
		assert.strictEqual(feetInches(165.1), '6 1/2"');
		assert.strictEqual(headingWithUnit('Mass (kg)', US), 'Mass (lb)');
		close(parseQuantity('12\'-6"', 'mm', US), 3810);
		close(parseQuantity('6 1/2"', 'mm', US), 165.1);
		close(parseQuantity('10', 'mm', US), 254);
		close(parseQuantity('300 mm', 'mm', US), 300);
		close(parseQuantity('4 ksi', 'MPa', US), 27.579029172672);
		assert.strictEqual(parseQuantity('abc', 'mm', US), undefined);
		assert.deepStrictEqual(parseList('150, -200', 'mm', SI_UNITS_SETTING), [150, -200]);
		const typed = parseList('5\'-0", 0', 'mm', US);
		close(typed?.[0], 1524);
		assert.strictEqual(typed?.[1], 0);
	});
});
