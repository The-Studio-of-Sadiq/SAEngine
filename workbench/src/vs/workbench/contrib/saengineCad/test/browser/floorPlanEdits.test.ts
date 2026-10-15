/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { floorPlanDrawing } from '../../browser/floorPlanDrawing.js';
import { anchor, basePoint, bayAt, EditResult, moveMember, pickMember, placeColumn, placeFooting, placeLinear, placePolygonSlab, placeSlab, removeMember, rotateMember, snapPoint, snapToGrid } from '../../browser/floorPlanEdits.js';

suite('SAEngine - Floor plan edits', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const empty = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }, { label: 'C', position: 12000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }, { id: 'L2', name: 'Level 2', elevation: 6400 }],
		columns: [], beams: [], walls: [], slabs: [], footings: [],
	};
	const A1 = { x: 'A', y: '1', point: [0, 0] as const };
	const B1 = { x: 'B', y: '1', point: [6000, 0] as const };
	const outcome = (result: EditResult) => result.ok ? result.id : result.error;
	const model = (result: EditResult) => {
		assert.ok(result.ok, result.ok ? '' : result.error);
		return result.layout;
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
		let layout = model(placeColumn(empty, 'C400', 'L1', A1));
		layout = model(placeLinear(layout, 'beam', 'B300', 'L1', A1, B1));
		layout = model(placeSlab(layout, 'S150', 'L1', bayAt(empty, [100, 100])!));
		const plan = floorPlanDrawing(layout, objects, 'L1');
		const pick = (x: number, y: number) => pickMember(plan.members, [x, y], 50)?.id;
		assert.deepStrictEqual({
			picks: [pick(0, 0), pick(3000, 100), pick(3000, 2500), pick(-5000, -5000)],
			afterDelete: removeMember(layout, 'beams', 'B1').beams,
			columnsKept: removeMember(layout, 'beams', 'B1').columns,
		}, {
			picks: ['C1', 'B1', 'S1', undefined],
			afterDelete: [],
			columnsKept: layout.columns,
		});
	});

	test('free points snap to intersections or grid lines and are stored against the nearest intersection', () => {
		assert.deepStrictEqual({
			intersection: snapPoint(empty, [5950, 40], 100),
			onLineX: snapPoint(empty, [6040, 2500.4], 100),
			free: snapPoint(empty, [3000.4, 2499.6], 100),
			anchors: [anchor(empty, [6000, 0]), anchor(empty, [6150, -200]), anchor(empty, [2900.6, 2600])],
		}, {
			intersection: [6000, 0],
			onLineX: [6000, 2500],
			free: [3000, 2500],
			anchors: [{ x: 'B', y: '1' }, { x: 'B', y: '1', dx: 150, dy: -200 }, { x: 'A', y: '2', dx: 2901, dy: -2400 }],
		});
	});

	test('moving re-anchors every point, rotation is for columns and footings, polygon slabs need an area', () => {
		let layout = model(placeColumn(empty, 'C400', 'L1', A1));
		layout = model(placeLinear(layout, 'beam', 'B300', 'L1', A1, B1));
		const movedColumn = model(moveMember(layout, 'columns', 'C1', [6150, 0]));
		const movedBeam = model(moveMember(layout, 'beams', 'B1', [0, 5000]));
		const rotated = model(rotateMember(layout, 'columns', 'C1', -90));
		const polygon = model(placePolygonSlab(layout, 'S150', 'L1', [[0, 0], [6000, 0], [2900, 4000], [0, 0]]));
		assert.deepStrictEqual({
			column: (movedColumn.columns as { at: unknown }[])[0].at,
			beam: (movedBeam.beams as { start: unknown; end: unknown }[]).map(b => [b.start, b.end]),
			base: [basePoint(movedColumn, 'columns', 'C1'), basePoint(movedBeam, 'beams', 'B1')],
			rotation: (rotated.columns as { rotation: unknown }[])[0].rotation,
			polygon: (polygon.slabs as { id: string; boundary: unknown }[]).map(s => [s.id, s.boundary]),
			refused: [
				outcome(rotateMember(layout, 'beams', 'B1', 90)),
				outcome(moveMember(layout, 'columns', 'C1', [0, 0])),
				outcome(moveMember(layout, 'columns', 'C9', [10, 0])),
				outcome(placePolygonSlab(layout, 'S150', 'L1', [[0, 0], [6000, 0], [12000, 0]])),
			],
		}, {
			column: { x: 'B', y: '1', dx: 150 },
			beam: [[{ x: 'A', y: '2' }, { x: 'B', y: '2' }]],
			base: [[6150, 0], [0, 5000]],
			rotation: 270,
			polygon: [['S1', [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'A', y: '2', dx: 2900, dy: -1000 }]]],
			refused: [
				'Only columns and footings rotate; beams, walls and slabs follow their points.',
				'Choose a different point to move to.',
				'C9 no longer exists.',
				'A slab needs at least three corners around an area.',
			],
		});
	});
});
