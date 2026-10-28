/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { alignedRotation, guessRole, gridPoints, IDrawingInfo, IDrawingLayer, importsOf, initialRoles, roleCounts, snapPoint } from '../../browser/architectureDrawingImport.js';
import { IArchitecture, newArchitecture } from '../../browser/architectureModel.js';

suite('SAEngine - Architecture drawing import', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	function layer(name: string, counts: Partial<IDrawingLayer['counts']> = {}): IDrawingLayer {
		const full = { lines: 0, arcs: 0, blocks: 0, texts: 0, other: 0, ...counts };
		return { name, counts: full, total: full.lines + full.arcs + full.blocks + full.texts + full.other, blocks: [], texts: [] };
	}
	const lines = { lines: 40 };
	const blocks = { blocks: 6, arcs: 0 };
	const texts = { texts: 8 };

	test('common layer names are guessed', () => {
		const cases: [IDrawingLayer, string][] = [
			[layer('A-WALL', lines), 'walls'],
			[layer('WALL', lines), 'walls'],
			[layer('Walls', lines), 'walls'],
			[layer('A-WALL-INT', lines), 'walls'],
			[layer('BRICK WALL', lines), 'walls'],
			[layer('PARTITION', lines), 'walls'],
			[layer('A-DOOR', blocks), 'doors'],
			[layer('DOORS', blocks), 'doors'],
			[layer('door', { arcs: 4, lines: 4 }), 'doors'],
			[layer('WINDOW', blocks), 'windows'],
			[layer('A-GLAZ', blocks), 'windows'],
			[layer('WIN', lines), 'windows'],
			[layer('Glazing', lines), 'windows'],
			[layer('TEXT', texts), 'rooms'],
			[layer('ROOM', texts), 'rooms'],
			[layer('A-AREA-IDEN', texts), 'rooms'],
			[layer('ROOM-NAME', texts), 'rooms'],
		];
		for (const [l, role] of cases) {
			assert.strictEqual(guessRole(l), role, l.name);
		}
	});

	test('what is not a wall, door, window or room name is ignored', () => {
		const cases: IDrawingLayer[] = [
			layer('A-WALL-PATT', { other: 30 }),
			layer('WALL-HATCH', lines),
			layer('DIM', lines),
			layer('A-ANNO-DIMS', lines),
			layer('FURNITURE', lines),
			layer('GRID', lines),
			layer('S-COL', lines),
			layer('COLUMN', lines),
			layer('A-DOOR-FRAME', lines),
			layer('STAIR', lines),
			layer('Defpoints', lines),
			layer('0', { texts: 2 }),
			layer('LAYER1', lines),
			layer('A-WALL'),
		];
		for (const l of cases) {
			assert.strictEqual(guessRole(l), 'ignore', l.name);
		}
	});

	test('a name is only taken when the layer has what the role reads', () => {
		assert.strictEqual(guessRole(layer('A-DOOR', { lines: 5 })), 'ignore', 'doors need blocks or arcs');
		assert.strictEqual(guessRole(layer('ROOM', lines)), 'ignore', 'room names need texts');
		assert.strictEqual(guessRole(layer('WALL', texts)), 'ignore', 'walls need lines');
	});

	const info: IDrawingInfo = {
		layers: [layer('A-WALL', lines), layer('MY-DOORS-X', blocks), layer('NAMES', texts), layer('EMPTY')],
		unit: 'mm', unitGuessed: false, extents: [[0, 0], [1000, 1000]],
		preview: { 'A-WALL': [[0, 0, 1000, 0, 1000, 1000]] }, labels: [], warnings: [],
	};

	function withImports(imports: object[]): IArchitecture {
		return { ...newArchitecture(), imports } as IArchitecture;
	}

	test('the mapping is guessed without an earlier import', () => {
		const { roles, remembered } = initialRoles(info, newArchitecture(), 'Drawings/plan.dxf');
		assert.strictEqual(remembered, false);
		assert.deepStrictEqual([...roles], [['A-WALL', 'walls'], ['MY-DOORS-X', 'doors'], ['NAMES', 'rooms'], ['EMPTY', 'ignore']]);
	});

	test('the mapping of this file is remembered, then other imports of the project', () => {
		const arch = withImports([
			{ file: 'other.dxf', story: 'L1', layers: { 'MY-DOORS-X': 'windows', 'NAMES': 'ignore' }, items: [] },
			{ file: 'Drawings\\PLAN.dxf', story: 'L1', layers: { 'NAMES': 'rooms', 'A-WALL': 'ignore' }, items: ['AW1'] },
		]);
		const { roles, remembered } = initialRoles(info, arch, 'Drawings/plan.dxf');
		assert.strictEqual(remembered, true);
		// This file's own mapping wins over the other import's; the rest from the other import.
		assert.strictEqual(roles.get('A-WALL'), 'ignore');
		assert.strictEqual(roles.get('NAMES'), 'rooms');
		assert.strictEqual(roles.get('MY-DOORS-X'), 'windows');
		assert.deepStrictEqual(importsOf(arch, 'drawings/plan.dxf').map(r => r.file), ['Drawings\\PLAN.dxf', 'other.dxf']);
		assert.deepStrictEqual(roleCounts(roles, info), { walls: 0, doors: 0, windows: 1, rooms: 1, ignore: 1 });
	});

	test('grid points, picking and two-point rotation', () => {
		const plan = { grids: { x: [{ label: 'B', position: 4000 }, { label: 'A', position: 0 }], y: [{ label: '1', position: 0 }, { label: '2', position: 3000 }] } };
		assert.deepStrictEqual(gridPoints(plan).map(g => [g.label, ...g.point]), [['A-1', 0, 0], ['A-2', 0, 3000], ['B-1', 4000, 0], ['B-2', 4000, 3000]]);
		assert.deepStrictEqual(gridPoints({}), [{ label: '0, 0', point: [0, 0] }]);
		assert.deepStrictEqual(snapPoint(info, [990, 15], 20), [1000, 0]);
		assert.strictEqual(snapPoint(info, [500, 500], 20), undefined);
		const grid = { ...info, preview: { 'S-GRID': [[-500, 0, 4000, 0], [0, -500, 0, 3000]] } };
		assert.deepStrictEqual(snapPoint(grid, [12, -9], 30), [0, 0], 'grid lines crossing');
		assert.strictEqual(Math.round(alignedRotation([0, 0], [0, 0], [10, 10], [4000, 0])), -45);
		assert.strictEqual(Math.abs(Math.round(alignedRotation([5, 5], [0, 0], [5, 0], [0, 3000]))), 180);
	});
});
