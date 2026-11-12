/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { describeGridChanges } from '../../common/gridChanges.js';

suite('SAEngine - Grid changes', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	const plan = {
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }],
		columns: [{ id: 'C1' }],
	};

	test('says what moved, was added, removed or renamed', () => {
		const after = {
			grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6500 }, { label: 'C', position: 12000 }], y: [] },
			stories: [{ id: 'BASE', name: 'Ground', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3600 }, { id: 'L2', name: 'Level 2', elevation: 6800 }],
		};
		assert.deepStrictEqual(describeGridChanges(plan, after), [
			'grid line B moved from 6000 to 6500 mm',
			'grid line C added at 12000 mm',
			'grid line 1 removed',
			'story Base renamed to Ground',
			'story Level 1 moved from 3200 to 3600 mm',
			'story Level 2 added at 6800 mm',
		]);
	});

	test('member edits are not grid changes', () => {
		const withoutColumns = { ...plan, columns: [] };
		assert.deepStrictEqual(describeGridChanges(plan, withoutColumns), []);
	});
});
