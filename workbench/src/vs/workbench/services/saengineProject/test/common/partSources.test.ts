/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { floorPlanStamp, newFloorPlan, recordedStamp, sourceStamp, upstreamCurrent, upstreamPart } from '../../common/partSources.js';
import { projectParts } from '../../common/saengineProject.js';
import { DEFAULT_FLOOR_PLAN } from '../../common/projectLibraries.generated.js';

suite('SAEngine - Part sources', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('the floor plan stamp leaves out the underlays, as the Python side does', () => {
		// R2-10 (OI-24): the same plan and digest as python/tests/test_rewalk2_minors.py.
		const plan = {
			schema: 'saengine.floorPlan/1',
			grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000.5 }], y: [] },
			stories: [{ id: 'L1', name: 'Level 1', elevation: 3600 }],
			columns: [],
			underlays: [{ file: 'plan.dxf', story: 'L1', scale: 1.0 }],
		};
		const text = JSON.stringify(plan, null, '	');
		const moved = JSON.stringify({ ...plan, underlays: [{ file: 'other.pdf', story: 'L1' }] });
		const changed = JSON.stringify({ ...plan, stories: [{ id: 'L1', name: 'Level 1', elevation: 3500 }] });
		assert.deepStrictEqual({
			stamp: floorPlanStamp(text),
			moved: floorPlanStamp(moved) === floorPlanStamp(text),
			changed: floorPlanStamp(changed) === floorPlanStamp(text),
			current: [upstreamCurrent('floorPlan', floorPlanStamp(text), moved), upstreamCurrent('floorPlan', sourceStamp(text), text), upstreamCurrent('floorPlan', sourceStamp(text), moved), upstreamCurrent('structure', floorPlanStamp(text), moved), upstreamCurrent('floorPlan', undefined, text)],
		}, {
			stamp: '0a246b6025a9f94811161541eb2aa347b6392c2e',
			moved: true,
			changed: false,
			current: [true, true, false, false, false],
		});
	});

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
