/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { formatPoint, location, onPlanOf, rises, storiesOf } from '../../common/floorPlanMembers.js';
import { gridLabel, nextGridLabel, nextLetters } from '../../common/gridLabels.js';

suite('SAEngine - Floor plan members and grid labels', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const layout = {
		stories: [
			{ id: 'L2', name: 'Level 2', elevation: 6400 },
			{ id: 'BASE', name: 'Base', elevation: 0 },
			{ id: 'L1', elevation: 3200 },
			{ id: 'BAD', name: 'No elevation' },
		],
	};

	test('stories lowest first, named by their id when unnamed, without broken ones', () => {
		assert.deepStrictEqual(storiesOf(layout).map(s => `${s.id}:${s.name}:${s.elevation}`), ['BASE:Base:0', 'L1:L1:3200', 'L2:Level 2:6400']);
		assert.deepStrictEqual(storiesOf(undefined), []);
	});

	test('locations in grid labels', () => {
		const bay = [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'B', y: '2' }, { x: 'A', y: '2' }];
		assert.deepStrictEqual([
			formatPoint({ x: 'C', y: '3', dy: -200 }),
			formatPoint({ x: 'A', y: '1', dx: 150 }),
			formatPoint(undefined),
			location('columns', { at: { x: 'A', y: '1' } }),
			location('footings', { at: { x: 'B', y: '2' } }),
			location('beams', { start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }),
			location('slabs', { boundary: bay }),
			location('slabs', { boundary: bay.slice(0, 3) }),
		], ['C-3 (0, -200)', 'A-1 (+150, 0)', '?', 'A-1', 'B-2', 'A-1 → B-1', 'A–B / 1–2', 'A-1 · B-1 · B-2']);
	});

	test('a column shows on the plans it rises through; a beam on its own story', () => {
		const stories = storiesOf(layout);
		const [base, l1, l2] = stories;
		const column = { base: 'BASE', top: 'L2' };
		const beam = { story: 'L1' };
		assert.deepStrictEqual({
			rises: [rises('columns'), rises('walls'), rises('beams'), rises('footings')],
			column: [base, l1, l2].map(s => onPlanOf('columns', column, s, stories)),
			beam: [base, l1, l2].map(s => onPlanOf('beams', beam, s, stories)),
			brokenColumn: onPlanOf('columns', { base: 'NOPE', top: 'L2' }, l2, stories),
		}, {
			rises: [true, true, false, false],
			column: [false, true, true],
			beam: [false, true, false],
			brokenColumn: false,
		});
	});

	test('grid labels: letters across X, numbers along Y, and the label after one', () => {
		assert.deepStrictEqual({
			x: [0, 1, 25, 26, 27].map(i => gridLabel('x', i)),
			y: gridLabel('y', 2),
			letters: ['A', 'Z', 'AZ', 'ZZ'].map(nextLetters),
			next: ['3', 'b', 'AZ', 'A1'].map(nextGridLabel),
		}, {
			x: ['A', 'B', 'Z', 'AA', 'AB'],
			y: '3',
			letters: ['B', 'AA', 'BA', 'AAA'],
			next: ['4', 'C', 'BA', 'A11'],
		});
	});
});
