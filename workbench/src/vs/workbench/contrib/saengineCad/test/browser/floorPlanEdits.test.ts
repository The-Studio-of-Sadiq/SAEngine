/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { floorPlanDrawing } from '../../browser/floorPlanDrawing.js';
import { bayAt, EditResult, pickMember, placeColumn, placeFooting, placeLinear, placeSlab, removeMember, snapToGrid } from '../../browser/floorPlanEdits.js';

suite('SAEngine - Floor plan edits', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const empty = {
		schema: 'saengine.bim/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }, { label: 'C', position: 12000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }, { id: 'L2', name: 'Level 2', elevation: 6400 }],
		columns: [], beams: [], walls: [], slabs: [], footings: [],
	};
	const A1 = { x: 'A', y: '1', point: [0, 0] as const };
	const B1 = { x: 'B', y: '1', point: [6000, 0] as const };
	const outcome = (result: EditResult) => result.ok ? result.id : result.error;
	const model = (result: EditResult) => {
		assert.ok(result.ok, result.ok ? '' : result.error);
		return result.bim;
	};

	test('snapping finds the nearest intersection within the tolerance and bays the lines around a point', () => {
		assert.deepStrictEqual({
			near: snapToGrid(empty, [5900, 150], 300),
			far: snapToGrid(empty, [3000, 2500], 300),
			bay: bayAt(empty, [7000, 100]),
			outside: bayAt(empty, [-10, 100]),
		}, {
			near: { x: 'B', y: '1', point: [6000, 0] },
			far: undefined,
			bay: { x: ['B', 'C'], y: ['1', '2'], corners: [[6000, 0], [12000, 0], [12000, 5000], [6000, 5000]] },
			outside: undefined,
		});
	});

	test('members get the next free id, rise from the story below and are not placed twice', () => {
		const one = model(placeColumn(empty, 'C400', 'L1', A1));
		const two = model(placeColumn(one, 'C400', 'L2', A1));
		const beam = model(placeLinear(two, 'beam', 'B300', 'L1', A1, B1));
		const wall = model(placeLinear(beam, 'wall', 'W200', 'L2', A1, B1));
		const slab = model(placeSlab(wall, 'S150', 'L1', bayAt(empty, [100, 100])!));
		const footing = model(placeFooting(slab, 'F1', 'BASE', A1));
		assert.deepStrictEqual({
			columns: two.columns,
			beam: beam.beams,
			wall: wall.walls,
			slab: slab.slabs,
			footing: footing.footings,
			refused: [
				outcome(placeColumn(two, 'C400', 'L1', A1)),
				outcome(placeColumn(empty, 'C400', 'BASE', A1)),
				outcome(placeLinear(beam, 'beam', 'B300', 'L1', B1, A1)),
				outcome(placeLinear(beam, 'beam', 'B300', 'L1', A1, A1)),
				outcome(placeSlab(slab, 'S150', 'L1', bayAt(empty, [10, 10])!)),
				outcome(placeFooting(footing, 'F1', 'BASE', A1)),
			],
		}, {
			columns: [
				{ id: 'C1', type: 'C400', at: { x: 'A', y: '1' }, base: 'BASE', top: 'L1', rotation: 0 },
				{ id: 'C2', type: 'C400', at: { x: 'A', y: '1' }, base: 'L1', top: 'L2', rotation: 0 },
			],
			beam: [{ id: 'B1', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }],
			wall: [{ id: 'W1', type: 'W200', base: 'L1', top: 'L2', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }],
			slab: [{ id: 'S1', type: 'S150', story: 'L1', boundary: [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'B', y: '2' }, { x: 'A', y: '2' }] }],
			footing: [{ id: 'F1', type: 'F1', story: 'BASE', at: { x: 'A', y: '1' }, rotation: 0 }],
			refused: [
				'There is already a column at A-1 on this story.',
				'Columns rise to a story from the one below; choose a story above Base.',
				'There is already a beam from B-1 to A-1 on this story.',
				'Choose a different end point.',
				'There is already a slab in this bay on this story.',
				'There is already a footing at A-1 on this story.',
			],
		});
	});

	test('a click picks the column over the beam and slab under it, and deletion removes only that member', () => {
		const objects = {
			objects: [
				{ id: 'C400', kind: 'column', profile: { shape: 'rectangle', xDim: 400, yDim: 400 } },
				{ id: 'B300', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 500 } },
				{ id: 'S150', kind: 'slab', thickness: 150 },
			],
		};
		let bim = model(placeColumn(empty, 'C400', 'L1', A1));
		bim = model(placeLinear(bim, 'beam', 'B300', 'L1', A1, B1));
		bim = model(placeSlab(bim, 'S150', 'L1', bayAt(empty, [100, 100])!));
		const plan = floorPlanDrawing(bim, objects, 'L1');
		const pick = (x: number, y: number) => pickMember(plan.members, [x, y], 50)?.id;
		assert.deepStrictEqual({
			picks: [pick(0, 0), pick(3000, 100), pick(3000, 2500), pick(-5000, -5000)],
			afterDelete: removeMember(bim, 'beams', 'B1').beams,
			columnsKept: removeMember(bim, 'beams', 'B1').columns,
		}, {
			picks: ['C1', 'B1', 'S1', undefined],
			afterDelete: [],
			columnsKept: bim.columns,
		});
	});
});
