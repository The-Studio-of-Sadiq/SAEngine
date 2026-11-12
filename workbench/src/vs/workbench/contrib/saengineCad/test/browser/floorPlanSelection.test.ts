/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IMemberShape } from '../../browser/floorPlanDrawing.js';
import { combine, commonFields, prune, selectAll, selectByType, selectInWindow, selectionSummary, typesOnPlan, windowMode } from '../../browser/floorPlanSelection.js';

suite('SAEngine - Floor plan selection', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const square = (x: number, y: number, half: number) => [[x - half, y - half], [x + half, y - half], [x + half, y + half], [x - half, y + half]] as [number, number][];
	const shapes: IMemberShape[] = [
		{ group: 'columns', id: 'C1', outline: { kind: 'polygon', points: square(0, 0, 200) } },
		{ group: 'columns', id: 'C2', outline: { kind: 'circle', center: [6000, 0], radius: 250 } },
		{ group: 'beams', id: 'B1', outline: { kind: 'polygon', points: [[0, -150], [6000, -150], [6000, 150], [0, 150]] } },
		{ group: 'slabs', id: 'S1', outline: { kind: 'polygon', points: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]] } },
	];
	const layout = {
		columns: [{ id: 'C1', type: 'C400', rotation: 90 }, { id: 'C2', type: 'C400', rotation: 90 }],
		beams: [{ id: 'B1', type: 'B300' }],
		slabs: [{ id: 'S1', type: 'S150' }],
	};
	const ids = (refs: readonly { id: string }[]) => refs.map(r => r.id);

	test('a window to the right selects what is inside it, to the left what it crosses', () => {
		assert.deepStrictEqual({
			modes: [windowMode([0, 0], [10, 10]), windowMode([10, 0], [0, 10])],
			// Around C1 and half of B1: only C1 is fully inside.
			window: ids(selectInWindow(shapes, [-500, -500], [3000, 500])),
			// The same box dragged the other way touches C1, B1 and the slab.
			crossing: ids(selectInWindow(shapes, [3000, 500], [-500, -500])),
			// A small crossing box inside the slab (no outline point in it) still touches it.
			insideSlab: ids(selectInWindow(shapes, [3100, 2600], [2900, 2400])),
			// A crossing box near the circle's edge but outside it misses it.
			nearCircle: ids(selectInWindow(shapes, [6400, 400], [6200, 200])),
			everything: ids(selectInWindow(shapes, [-1000, -1000], [7000, 6000])),
		}, {
			modes: ['window', 'crossing'],
			window: ['C1'],
			crossing: ['C1', 'B1', 'S1'],
			insideSlab: ['S1'],
			nearCircle: [],
			everything: ['C1', 'C2', 'B1', 'S1'],
		});
	});

	test('selections combine, toggle, prune and summarise', () => {
		const one = [{ group: 'columns' as const, id: 'C1' }];
		const two = combine(one, [{ group: 'beams', id: 'B1' }], 'add');
		assert.deepStrictEqual({
			add: ids(two),
			toggleOff: ids(combine(two, [{ group: 'columns', id: 'C1' }], 'toggle')),
			toggleOn: ids(combine(two, [{ group: 'slabs', id: 'S1' }], 'toggle')),
			replace: ids(combine(two, [{ group: 'slabs', id: 'S1' }], 'replace')),
			pruned: ids(prune([...two, { group: 'beams', id: 'B9' }], shapes)),
			all: ids(selectAll(shapes)),
			byType: ids(selectByType(layout, shapes, 'C400')),
			types: typesOnPlan(layout, shapes),
			summary: selectionSummary([...selectAll(shapes), { group: 'columns', id: 'C3' }]),
			none: selectionSummary([]),
		}, {
			add: ['C1', 'B1'],
			toggleOff: ['B1'],
			toggleOn: ['C1', 'B1', 'S1'],
			replace: ['S1'],
			pruned: ['C1', 'B1'],
			all: ['C1', 'C2', 'B1', 'S1'],
			byType: ['C1', 'C2'],
			types: [{ type: 'C400', group: 'columns', count: 2 }, { type: 'B300', group: 'beams', count: 1 }, { type: 'S150', group: 'slabs', count: 1 }],
			summary: 'Selected 5: 3 columns, 1 beam, 1 slab',
			none: '',
		});
	});

	test('a multi-selection shows the type and rotation its members share', () => {
		const columns = commonFields(layout, [{ group: 'columns', id: 'C1' }, { group: 'columns', id: 'C2' }]);
		const mixed = commonFields({ ...layout, beams: [{ id: 'B1', type: 'B300' }, { id: 'B2', type: 'B250' }] }, [{ group: 'columns', id: 'C1' }, { group: 'beams', id: 'B1' }, { group: 'beams', id: 'B2' }]);
		assert.deepStrictEqual({
			columns: { types: [...columns.types], rotation: columns.rotation, rotatable: columns.rotatable },
			mixed: { types: [...mixed.types], rotation: mixed.rotation, rotatable: mixed.rotatable },
		}, {
			columns: { types: [['columns', 'C400']], rotation: 90, rotatable: true },
			mixed: { types: [['columns', 'C400'], ['beams', undefined]], rotation: undefined, rotatable: false },
		});
	});
});
