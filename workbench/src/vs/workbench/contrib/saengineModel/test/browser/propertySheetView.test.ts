/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { BIM_SCHEMA, STRUCTURE_SCHEMA } from '../../../../services/saengineProject/common/projectLibraries.generated.js';
import { formatPropertyValue, schemaUnit } from '../../browser/propertySheetView.js';

suite('SAEngine - Property values with units', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('values of the structural model and the building model carry the schema units', () => {
		const member = { type: 'BM', start: { x: 20704.4, y: 0, z: 14611 }, end: { x: 23385, y: 0, z: 13521 }, rotation: 15 };
		const column = { kind: 'column', position: [6000, 0], bottom: 0, top: 3200, rotation: 90, source: 'C1' };
		const slab = { kind: 'slab', boundary: [[0, 0], [6000, 0], [6000, 5000]], elevation: 3200 };
		const format = (schema: typeof BIM_SCHEMA, definition: string, item: object) =>
			Object.entries(item).map(([key, value]) => `${key}: ${formatPropertyValue(value, schemaUnit(schema, definition, key))}`);
		assert.deepStrictEqual({
			member: format(STRUCTURE_SCHEMA, 'Member', member),
			column: format(BIM_SCHEMA, 'ColumnElement', column),
			slab: format(BIM_SCHEMA, 'SlabElement', slab),
		}, {
			member: ['type: BM', 'start: 20704, 0, 14611 mm', 'end: 23385, 0, 13521 mm', 'rotation: 15°'],
			column: ['kind: column', 'position: 6000, 0 mm', 'bottom: 0 mm', 'top: 3200 mm', 'rotation: 90°', 'source: C1'],
			slab: ['kind: slab', 'boundary: (0, 0), (6000, 0), (6000, 5000) mm', 'elevation: 3200 mm'],
		});
	});
});
