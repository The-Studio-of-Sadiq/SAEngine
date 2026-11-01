/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import type { CadPoint } from '@saengine/cad-editor';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { addCurtainWall, addOpening, addRailing, addRamp, addRoof, addRoom, addSeparator, addWall, ArchEdit, curtainWeight, rampGradient, roofWeight, architectureDrawing, findRoom, IArchitecture, insetPolygon, newArchitecture, offsetPath, parseArchitecture, pickItem, removeItem, storyCounts, structureUnder, updateItem, wallLevels, wallSnapSegments } from '../../browser/architectureModel.js';
import { snapLinear } from '../../browser/floorPlanSnap.js';

suite('SAEngine - Architecture', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const plan = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }, { id: 'L2', name: 'Level 2', elevation: 6400 }],
		columns: [], walls: [], slabs: [], footings: [],
		beams: [{ id: 'B1', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }],
	};
	const elevations = new Map([['BASE', 0], ['L1', 3200], ['L2', 6400]]);
	const value = (result: ArchEdit) => {
		assert.ok(result.ok, result.ok ? '' : result.error);
		return result.value;
	};
	const round = (points: readonly CadPoint[]) => points.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]);

	/** A 6 x 5 m box of 274 mm walls on L1 with a 149 mm partition at x = 3000. */
	function flat(): IArchitecture {
		let arch = newArchitecture();
		arch = value(addWall(arch, 'BW250', 'L1', [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]], elevations));
		arch = value(addWall(arch, 'BW125', 'L1', [[3000, 0], [3000, 5000]], elevations));
		return arch;
	}

	test('a new file has the default types and parses back', () => {
		const arch = newArchitecture();
		assert.deepStrictEqual(arch.wallTypes.map(t => t.id), ['BW250', 'BW125']);
		const parsed = parseArchitecture(JSON.stringify(arch));
		assert.strictEqual(parsed.kind, 'ok');
		assert.strictEqual(parseArchitecture('{"schema": "saengine.floorPlan/1"}').kind, 'error');
		assert.strictEqual(parseArchitecture('{').kind, 'error');
	});

	test('walls rise to the next story; on the top story they are 3 m high', () => {
		const arch = flat();
		assert.deepStrictEqual(wallLevels(arch.walls[0], elevations), { bottom: 3200, top: 6400 });
		const roof = value(addWall(arch, 'BW125', 'L2', [[0, 0], [1000, 0]], elevations));
		assert.deepStrictEqual(wallLevels(roof.walls[2], elevations), { bottom: 6400, top: 9400 });
		assert.strictEqual(addWall(arch, 'BW125', 'L1', [[0, 0], [0, 0]], elevations).ok, false);
		assert.strictEqual(addWall(arch, 'NOPE', 'L1', [[0, 0], [1, 0]], elevations).ok, false);
	});

	test('a location line on a face moves the centre line by half the thickness', () => {
		assert.deepStrictEqual(round(offsetPath([[0, 0], [1000, 0], [1000, 1000]], 100)), [[0, 100], [900, 100], [900, 1000]]);
	});

	test('rooms are the faces of the wall centre lines around the point, less half of each wall', () => {
		const arch = flat();
		const left = findRoom(arch, 'L1', [1500, 2500], elevations)!;
		assert.ok(left);
		assert.deepStrictEqual(round(left.gross).sort(), [[0, 0], [0, 5000], [3000, 0], [3000, 5000]].sort());
		// As saengine.library.architecture.room_boundary: (3000 - 137 - 74.5) x (5000 - 2 x 137).
		assert.strictEqual(Math.round(left.area * 1e6), Math.round((3000 - 137 - 74.5) * (5000 - 274)));
		assert.ok(findRoom(arch, 'L1', [4500, 2500], elevations));
		assert.strictEqual(findRoom(arch, 'L1', [9000, 2500], elevations), undefined);
		assert.strictEqual(findRoom(arch, 'L2', [1500, 2500], elevations), undefined, 'the walls stand on L1');
	});

	test('a wall ending at another wall\'s face still closes a room (Revit joins)', () => {
		let arch = value(addWall(newArchitecture(), 'BW250', 'L1', [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]], elevations));
		arch = value(addWall(arch, 'BW125', 'L1', [[3000, 137], [3000, 4863]], elevations));
		assert.strictEqual(Math.round(findRoom(arch, 'L1', [1500, 2500], elevations)!.gross.length), 4);
	});

	test('room separators bound open plans', () => {
		let arch = value(addWall(newArchitecture(), 'BW250', 'L1', [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]], elevations));
		assert.strictEqual(Math.round(findRoom(arch, 'L1', [1000, 1000], elevations)!.area), 27);
		arch = value(addSeparator(arch, 'L1', [2000, 0], [2000, 5000]));
		const room = findRoom(arch, 'L1', [1000, 1000], elevations)!;
		assert.strictEqual(Math.round(room.area * 1e6), Math.round((2000 - 137) * (5000 - 274)), 'no wall on the separator side');
	});

	test('inset steps where walls of two thicknesses meet in line', () => {
		const net = insetPolygon([[0, 0], [1000, 0], [2000, 0], [2000, 1000], [0, 1000]], [100, 50, 0, 0, 0]);
		assert.deepStrictEqual(round(net), [[0, 100], [1000, 100], [1000, 50], [2000, 50], [2000, 1000], [0, 1000]]);
	});

	test('doors and windows go into walls, inside them and apart', () => {
		let arch = flat();
		arch = value(addOpening(arch, 'doors', 'D2', 'AW2', 2503));
		assert.deepStrictEqual(arch.doors[0], { id: 'D1', type: 'D2', wall: 'AW2', offset: 2500 });
		const near = addOpening(arch, 'doors', 'D3', 'AW2', 2600);
		assert.ok(!near.ok && /overlap D1/.test(near.error));
		arch = value(addOpening(arch, 'windows', 'W1', 'AW1', 100));
		assert.strictEqual(arch.windows[0].offset, 750, 'kept inside the wall');
		const wide = addOpening(value(addWall(arch, 'BW125', 'L1', [[0, 0], [500, 0]], elevations)), 'windows', 'W1', 'AW3', 250);
		assert.ok(!wide.ok);
	});

	test('rooms take a pick point inside walls, numbered by story', () => {
		let arch = flat();
		arch = value(addRoom(arch, 'L1', [1500, 2500], elevations, 'Bed'));
		assert.deepStrictEqual(arch.rooms[0], { id: 'R1', story: 'L1', point: [1500, 2500], name: 'Bed', number: '101' });
		assert.ok(!addRoom(arch, 'L1', [1000, 1000], elevations).ok, 'already a room there');
		assert.ok(!addRoom(arch, 'L1', [9000, 9000], elevations).ok, 'not enclosed');
		arch = value(addRoom(arch, 'L1', [4500, 2500], elevations));
		assert.strictEqual(arch.rooms[1].number, '102');
		assert.deepStrictEqual(storyCounts(arch, 'L1', elevations), { walls: 2, doors: 0, windows: 0, rooms: 2 });
	});

	test('deleting a wall takes its doors and windows; fields change and clear', () => {
		let arch = value(addOpening(flat(), 'doors', 'D2', 'AW2', 2500));
		arch = updateItem(arch, { kind: 'doors', id: 'D1' }, { flip: true });
		assert.strictEqual(arch.doors[0].flip, true);
		arch = updateItem(arch, { kind: 'doors', id: 'D1' }, { flip: undefined });
		assert.ok(!Object.keys(arch.doors[0]).includes('flip'));
		arch = removeItem(arch, { kind: 'walls', id: 'AW2' });
		assert.deepStrictEqual([arch.walls.length, arch.doors.length], [1, 0]);
	});

	test('the drawing cuts walls at openings and picks openings before walls', () => {
		let arch = value(addOpening(flat(), 'doors', 'D2', 'AW2', 2500));
		arch = value(addRoom(arch, 'L1', [1500, 2500], elevations, 'Bed'));
		const drawing = architectureDrawing(arch, 'L1', elevations);
		assert.deepStrictEqual(drawing.problems, []);
		assert.deepStrictEqual(drawing.shapes.map(s => `${s.kind}:${s.id}`).sort(), ['doors:D1', 'rooms:R1', 'walls:AW1', 'walls:AW2']);
		// The partition's two faces are each cut in two by the door.
		const partition = drawing.entities.filter(e => e.kind === 'line' && e.layer === 'A-WALL' && Math.abs(e.start[0] - e.end[0]) < 1e-6 && Math.abs(Math.abs(e.start[0] - 3000) - 74.5) < 1e-6);
		assert.strictEqual(partition.length, 4);
		assert.ok(drawing.entities.some(e => e.kind === 'text' && e.text === '101 Bed'));
		assert.strictEqual(pickItem(drawing.shapes, [3000, 2500], 10)?.id, 'D1');
		assert.strictEqual(pickItem(drawing.shapes, [3000, 1000], 10)?.id, 'AW2');
		assert.strictEqual(pickItem(drawing.shapes, [1500, 1500], 10)?.id, 'R1');
		assert.strictEqual(architectureDrawing(arch, 'L2', elevations).shapes.length, 0);
	});

	test('the floor plan\'s snaps take the architecture\'s walls; a wall over a beam records it', () => {
		const arch = flat();
		const snap = snapLinear(plan, 'L1', [3010, 2480], 50, undefined, wallSnapSegments(arch, 'L1', elevations));
		assert.deepStrictEqual([snap.kind, snap.on, snap.point], ['midpoint', 'AW2', [3000, 2500]]);
		assert.strictEqual(structureUnder(plan, 'L1', [500, 0], [5500, 0]), 'B1');
		assert.strictEqual(structureUnder(plan, 'L1', [500, 10], [5500, 0]), undefined);
	});

	test('curtain walls, roofs, ramps and railings: added, drawn, picked and bounding rooms', () => {
		let arch = newArchitecture();
		assert.deepStrictEqual([arch.curtainWallTypes.map(t => t.id), arch.roofTypes.map(t => t.id), arch.railingTypes.map(t => t.id)], [['CW1'], ['RF1', 'RF2'], ['RL1', 'RL2']]);
		// Glass 12 mm x 25 kN/m3 + 0.15 frame = 0.45 kN/m2; RF2: 0.040 x 20.4 + 0.005 x 12 = 0.876 kN/m2.
		assert.strictEqual(Math.round(curtainWeight(arch.curtainWallTypes[0]) * 1000) / 1000, 0.45);
		assert.strictEqual(Math.round(roofWeight(arch.roofTypes[1]) * 1000) / 1000, 0.876);
		arch = value(addCurtainWall(arch, 'CW1', 'L1', [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]], elevations));
		assert.strictEqual(arch.curtainWalls[0].id, 'CW1');
		// A curtain wall closes a room as a wall does: net (6.0 - 0.15) x (5.0 - 0.15) m.
		const room = findRoom(arch, 'L1', [3000, 2500], elevations);
		assert.ok(room);
		assert.strictEqual(Math.round(room.area * 1000) / 1000, Math.round(5.85 * 4.85 * 1000) / 1000);
		arch = value(addRoof(arch, 'RF2', 'L2', [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]]));
		assert.strictEqual(arch.roofs[0].outline.length, 4);
		assert.strictEqual(addRoof(arch, 'RF2', 'L2', [[0, 0], [1000, 0], [2000, 0]]).ok, false);
		arch = value(addRamp(arch, 'L1', [1000, 2500], [3000, 2500]));
		arch = updateItem(arch, { kind: 'ramps', id: 'RP1' }, { rise: 400 });
		assert.strictEqual(rampGradient(arch.ramps[0]), 0.2);
		// What it serves (for the code pack's ramp checks) is kept with the ramp.
		const vehicle = updateItem(arch, { kind: 'ramps', id: 'RP1' }, { kind: 'vehicle', lanes: 2, transitions: true });
		assert.deepStrictEqual([vehicle.ramps[0].kind, vehicle.ramps[0].lanes, vehicle.ramps[0].transitions], ['vehicle', 2, true]);
		arch = value(addRailing(arch, 'RL1', 'L1', [[0, 5000], [6000, 5000]]));
		const drawing = architectureDrawing(arch, 'L1', elevations);
		assert.deepStrictEqual(drawing.problems, []);
		assert.deepStrictEqual(drawing.shapes.map(s => s.kind).sort(), ['curtainWalls', 'railings', 'ramps']);
		assert.strictEqual(pickItem(drawing.shapes, [2000, 2500], 10)?.id, 'RP1');
		assert.strictEqual(architectureDrawing(arch, 'L2', elevations).shapes.some(s => s.kind === 'roofs'), true);
		assert.deepStrictEqual(removeItem(arch, { kind: 'roofs', id: 'RF1' }).roofs, []);
		assert.strictEqual(parseArchitecture(JSON.stringify(arch)).kind, 'ok');
	});
});
