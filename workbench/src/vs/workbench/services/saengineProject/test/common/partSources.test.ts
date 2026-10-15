/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { newFloorPlan, recordedStamp, sourceStamp, upstreamPart } from '../../common/partSources.js';
import { projectParts } from '../../common/saengineProject.js';
import { DEFAULT_FLOOR_PLAN } from '../../common/projectLibraries.generated.js';

suite('SAEngine - Part sources', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('stamps match the Python models and ignore line endings', () => {
		assert.deepStrictEqual({
			// The same digest as `saengine.library.bim.source_stamp` (python/tests/test_bim.py).
			python: sourceStamp('{"schema": "é"}\r\n'),
			lineEndings: sourceStamp('a\r\nb\n') === sourceStamp('a\nb\n'),
			recorded: [recordedStamp({ source: { floorPlan: 'abc' } }, 'floorPlan'), recordedStamp({}, 'floorPlan'), recordedStamp('x', 'floorPlan')],
		}, {
			python: '15e949281f1007c264631f2230d308c121022828',
			lineEndings: true,
			recorded: ['abc', undefined, undefined],
		});
	});

	test('the building model is built from the floor plan or the structural model', () => {
		assert.deepStrictEqual(
			[upstreamPart('bim', projectParts('building')), upstreamPart('bim', projectParts('structure')), upstreamPart('settings', projectParts('building'))],
			['floorPlan', 'structure', undefined],
		);
	});

	test('a new floor plan takes over the layout of an older building model', () => {
		const legacy = { schema: 'saengine.bim/1', grids: { x: [{ label: 'A', position: 0 }], y: [] }, stories: [], columns: [{ id: 'C1' }] };
		assert.deepStrictEqual({
			migrated: newFloorPlan(JSON.stringify(legacy)),
			fresh: newFloorPlan(JSON.stringify({ schema: 1, part: 'bim' })),
			broken: newFloorPlan('{'),
		}, {
			migrated: { ...legacy, schema: 'saengine.floorPlan/1' },
			fresh: DEFAULT_FLOOR_PLAN,
			broken: DEFAULT_FLOOR_PLAN,
		});
	});
});
