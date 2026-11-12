/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { csvField, csvText } from '../../common/csv.js';
import { centroid, polygonArea, signedArea } from '../../common/geometry.js';

suite('SAEngine - Shared CSV and plan geometry', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('CSV fields are quoted only when they must be; rows end in CRLF, an empty row is a blank line', () => {
		assert.deepStrictEqual(
			[csvField('plain'), csvField('a,b'), csvField('say "hi"'), csvField('two\nlines'), csvField(1.5), csvField(undefined), csvField('')],
			['plain', '"a,b"', '"say ""hi"""', '"two\nlines"', '1.5', '', ''],
		);
		assert.strictEqual(csvText([['Case', 'Table'], [], ['C1', 2.5, undefined]]), 'Case,Table\r\n\r\nC1,2.5,\r\n');
		assert.strictEqual(csvText([]), '\r\n');
	});

	test('polygon area is signed anticlockwise positive; the area and centroid do not care which way round', () => {
		const square = [[0, 0], [4, 0], [4, 2], [0, 2]] as const;
		const clockwise = [...square].reverse();
		assert.deepStrictEqual({
			ccw: signedArea(square),
			cw: signedArea(clockwise),
			area: [polygonArea(square), polygonArea(clockwise)],
			centroid: centroid(square),
			none: [signedArea([]), centroid([])],
		}, {
			ccw: 8,
			cw: -8,
			area: [8, 8],
			centroid: [2, 1],
			none: [0, undefined],
		});
	});
});
