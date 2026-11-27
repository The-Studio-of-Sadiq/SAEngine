/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { GridGeometry, gridShapes } from '../../common/gridGeometry.js';

/** The same grids as python/tests/test_grid_systems.py: the engine and the workbench agree. */
const GRIDS = {
	x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }],
	y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }],
	systems: [
		{ id: 'G2', kind: 'orthogonal', originX: 10000, originY: 2000, angle: 30, x: [{ label: 'P', position: 0 }, { label: 'Q', position: 6000 }], y: [{ label: '7', position: 0 }, { label: '8', position: 4000 }] },
		{ id: 'R1', kind: 'radial', originX: -5000, originY: 1000, angle: 10, rays: [{ label: 'R0', angle: 0 }, { label: 'R45', angle: 45 }], rings: [{ label: 'C1', radius: 4000 }, { label: 'C2', radius: 8000 }] },
		{ id: 'L1', kind: 'lines', lines: [{ label: 'S', x1: 0, y1: -1000, angle: 45, length: 9000 }] },
	],
};

function near(actual: readonly number[] | undefined, expected: readonly number[]): void {
	assert.ok(actual, 'no point');
	assert.ok(actual.every((v, i) => Math.abs(v - expected[i]) < 1e-6), `${actual} != ${expected}`);
}

suite('SAEngine grid geometry', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	const deg = (d: number) => d * Math.PI / 180;
	const g = new GridGeometry(GRIDS);

	test('a rotated system: its intersections by hand, and offsets along the plan axes', () => {
		const x = 10000 + 6000 * Math.cos(deg(30)) - 4000 * Math.sin(deg(30));
		const y = 2000 + 6000 * Math.sin(deg(30)) + 4000 * Math.cos(deg(30));
		near(g.intersection('Q', '8'), [x, y]);
		near(g.intersection('P', '7'), [10000, 2000]);
		near(g.point({ x: 'Q', y: '8', dx: 100, dy: -50 }), [x + 100, y - 50]);
		assert.ok(Math.abs(g.orientation('Q') - 30) < 1e-9);
	});

	test('a radial system: ray and ring, named ray first', () => {
		near(g.intersection('R45', 'C2'), [-5000 + 8000 * Math.cos(deg(55)), 1000 + 8000 * Math.sin(deg(55))]);
		near(g.intersection('R0', 'C1'), [-5000 + 4000 * Math.cos(deg(10)), 1000 + 4000 * Math.sin(deg(10))]);
		assert.ok(Math.abs(g.orientation('R45') - 55) < 1e-9);
		assert.throws(() => g.intersection('C1', 'R0'), /ray then the ring/);
		assert.throws(() => g.intersection('C1', 'C2'), /two rings/);
	});

	test('a single angled line crosses the main grid', () => {
		near(g.intersection('B', 'S'), [6000, 5000]);
		near(g.intersection('S', '1'), [1000, 0]);
		assert.ok(Math.abs(g.orientation('S') + 45) < 1e-9);
		assert.strictEqual(g.point({ x: 'A', y: 'nope' }), undefined);
	});

	test('intersections for snapping, and finding the grid point at a place', () => {
		const found = new Set(g.intersections().map(i => `${i.first}-${i.second}`));
		for (const name of ['A-1', 'Q-8', 'R45-C2', 'B-S']) {
			assert.ok(found.has(name), name);
		}
		assert.ok(!found.has('C1-R0'));
		const [x, y] = g.intersection('Q', '8');
		assert.deepStrictEqual(g.find(x + 20, y - 20), { first: 'Q', second: '8' });
	});

	test('an old plan is one orthogonal system at 0°', () => {
		const old = GridGeometry.ofPlan({ grids: { x: GRIDS.x, y: GRIDS.y } });
		assert.ok(old.orthogonalOnly);
		near(old.point({ x: 'B', y: '2' }), [6000, 5000]);
		assert.ok(!g.orthogonalOnly);
	});

	test('#300: grid shapes put bubbles at both ends of a line, the outer end of a ray and outside a ring', () => {
		const shapes = new Map(gridShapes(g.axes.filter(a => a.system), 400).map(s => [s.label, s]));
		const ray = g.axis('R45')!;
		const [, end] = shapes.get('R45')!.segment!;
		assert.strictEqual(shapes.get('R45')!.bubbles.length, 1);
		near(shapes.get('R45')!.bubbles[0], [end[0] + 400 * ray.direction[0], end[1] + 400 * ray.direction[1]]);
		assert.strictEqual(shapes.get('Q')!.bubbles.length, 2);
		const ring = shapes.get('C2')!;
		assert.ok(ring.circle && !ring.segment);
		const [bx, by] = ring.bubbles[0];
		assert.ok(Math.abs(Math.hypot(bx - ring.circle.center[0], by - ring.circle.center[1]) - (ring.circle.radius + 400)) < 1e-6);
	});
});
