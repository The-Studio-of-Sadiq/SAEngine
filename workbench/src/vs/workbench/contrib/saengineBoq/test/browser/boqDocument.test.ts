/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { sourceStamp } from '../../../../services/saengineProject/common/partSources.js';
import { changedSources, IBoqDocument, parseBoq, toCsv, totals } from '../../browser/boqDocument.js';

suite('SAEngine - Bill of quantities', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const document: IBoqDocument = {
		schema: 'saengine.boq/1',
		source: { bim: sourceStamp('{"a": 1}\n'), objects: sourceStamp('o'), materials: sourceStamp('m') },
		items: [
			{
				code: 'C.01', group: 'concrete', description: 'Concrete C24.1 in columns', quantity: 2.048, unit: 'm3',
				byStory: { L1: 2.048 },
				breakdown: [{ element: 'C1', story: 'L1', quantity: 1.024 }, { element: 'C2', story: 'L1', quantity: 1.024 }],
			},
			{ code: 'C.02', group: 'concrete', description: 'Concrete C24.1 in "beams", ground', quantity: 3, unit: 'm3', breakdown: [] },
		],
		notes: [],
	};

	test('reads a measured bill, tells which sources changed, totals and exports it', () => {
		assert.deepStrictEqual({
			parsed: parseBoq(JSON.stringify(document))?.items.length,
			placeholder: parseBoq('{"schema": 1, "part": "boq"}'),
			invalid: parseBoq('{'),
			current: changedSources(document, new Map([['bim', '{"a": 1}\r\n'], ['objects', 'o'], ['materials', 'm']])),
			changed: changedSources(document, new Map([['bim', '{"a": 2}'], ['objects', 'o']])),
			never: changedSources(undefined, new Map([['bim', ''], ['objects', 'o'], ['materials', 'm']])),
			totals: totals(document.items),
			csv: toCsv(document).split('\r\n'),
		}, {
			parsed: 2,
			placeholder: undefined,
			invalid: undefined,
			current: [],
			changed: ['bim', 'materials'],
			never: ['bim', 'objects', 'materials'],
			totals: [{ unit: 'm3', total: 5.048 }],
			csv: [
				'Row,Code,Group,Description,Element,Story,Detail,Item Quantity,Element Quantity,Unit',
				'item,C.01,concrete,Concrete C24.1 in columns,,,,2.048,,m3',
				'element,C.01,concrete,Concrete C24.1 in columns,C1,L1,,,1.024,m3',
				'element,C.01,concrete,Concrete C24.1 in columns,C2,L1,,,1.024,m3',
				'item,C.02,concrete,"Concrete C24.1 in ""beams"", ground",,,,3,,m3',
				'',
			],
		});
	});
});
