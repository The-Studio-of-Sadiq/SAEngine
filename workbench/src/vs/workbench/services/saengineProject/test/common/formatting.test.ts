/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { DATE_TIME, formatDate, formatNumber, TIME } from '../../common/formatting.js';

/** Bengali digits ০–৯: ৪ (four) reads as 8. */
const BENGALI_DIGIT = /[০-৯]/;

suite('SAEngine - Formatting', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('the runtime has Bengali locale data, so the tests below can fail', () => {
		// Without bn data the guards below would pass vacuously.
		assert.match((4).toLocaleString('bn-BD'), BENGALI_DIGIT);
		assert.match(new Date(2026, 9, 24).toLocaleDateString('bn-BD'), BENGALI_DIGIT);
	});

	test('engineering numbers use ASCII digits and a "." decimal point', () => {
		assert.strictEqual(formatNumber(1234.5), '1,235');
		assert.strictEqual(formatNumber(1234.56, { decimals: 1 }), '1,234.6');
		assert.strictEqual(formatNumber(80, { decimals: 1 }), '80.0');
		assert.strictEqual(formatNumber(12.25, { maxDecimals: 2 }), '12.25');
		assert.strictEqual(formatNumber(12, { maxDecimals: 2 }), '12');
		assert.strictEqual(formatNumber(1234, { grouping: false }), '1234');
		assert.strictEqual(formatNumber(-4.44, { decimals: 1 }), '-4.4');
	});

	test('dates under a Bengali UI language keep ASCII digits', () => {
		const time = new Date(2026, 9, 24, 14, 4, 8).getTime();
		for (const options of [DATE_TIME, TIME, { day: 'numeric', month: 'short' } as const]) {
			const text = formatDate(time, options, 'bn-BD');
			assert.doesNotMatch(text, BENGALI_DIGIT, text);
		}
		assert.match(formatDate(time, { day: 'numeric' }, 'bn-BD'), /24/);
	});

	test('dates follow the UI language for month names', () => {
		const time = new Date(2026, 9, 24).getTime();
		assert.strictEqual(formatDate(time, { day: 'numeric', month: 'short', year: 'numeric' }, 'en-GB'), '24 Oct 2026');
		assert.strictEqual(formatDate(time, { day: 'numeric', month: 'short', year: 'numeric' }, 'en-US'), 'Oct 24, 2026');
		assert.doesNotMatch(formatDate(time, { month: 'long' }, 'bn-BD'), /October/);
	});

	test('an unknown UI language falls back instead of throwing', () => {
		assert.match(formatDate(new Date(2026, 9, 24).getTime(), { day: 'numeric' }, 'not a locale!'), /24/);
	});
});
