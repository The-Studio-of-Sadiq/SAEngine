/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { EditResult, placeLinear, resolvePoint } from '../../browser/floorPlanEdits.js';
import { nearMisses, snapLinear, typedEnd } from '../../browser/floorPlanSnap.js';

suite('SAEngine - Floor plan snaps', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const plan = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }],
		columns: [{ id: 'C1', type: 'C400', at: { x: 'A', y: '1', dx: 300 }, base: 'BASE', top: 'L1' }],
		beams: [
			{ id: 'B1', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } },
			{ id: 'B2', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '2' } },
		],
		walls: [], slabs: [], footings: [],
	};
	const model = (result: EditResult) => {
		assert.ok(result.ok, result.ok ? '' : result.error);
		return result.layout;
	};

	test('ends snap to intersections, columns, midpoints, perpendiculars and points on beams, else they are free', () => {
		const snap = (point: [number, number], from?: [number, number]) => {
			const s = snapLinear(plan, 'L1', point, 200, from);
			return [s.kind, s.on ?? '', Math.round(s.point[0] * 1000) / 1000, Math.round(s.point[1] * 1000) / 1000, s.exact];
		};
		assert.deepStrictEqual({
			node: snap([5950, 4980]),
			column: snap([310, 80]),
			midpoint: snap([3050, 30]),
			perpendicular: snap([2440, 2060], [0, 5000]),
			nearest: snap([4500, 150]),
			gridLine: snap([5960, 2500]),
			free: snap([7500.4, 2500.6]),
		}, {
			node: ['node', '', 6000, 5000, false],
			column: ['endpoint', 'C1', 300, 0, true],
			midpoint: ['midpoint', 'B1', 3000, 0, true],
			// The foot of the perpendicular from A-2 onto the diagonal B2.
			perpendicular: ['perpendicular', 'B2', 2459.016, 2049.18, true],
			nearest: ['nearest', 'B1', 4500, 0, true],
			gridLine: ['gridLine', '', 6000, 2500, false],
			free: ['free', '', 7500, 2501, false],
		});
	});

	test('a secondary beam on a diagonal beam is stored on it, a cantilever is free, a near miss is reported', () => {
		const foot = snapLinear(plan, 'L1', [2440, 2060], 200, [0, 5000]);
		const secondary = model(placeLinear(plan, 'beam', 'B300', 'L1', { point: [0, 5000] }, foot));
		const stored = (secondary.beams as { id: string; end: unknown }[]).find(b => b.id === 'B3')!.end;
		const end = resolvePoint(secondary, stored)!;
		// On the line of B2 (y = 5/6 x) to well under a micrometre, so the analysis model joins them.
		assert.ok(Math.abs(end[1] - end[0] * 5 / 6) < 1e-3, JSON.stringify(stored));
		const cantilever = model(placeLinear(plan, 'beam', 'B300', 'L1', { point: [6000, 0] }, { point: [7500, 0] }));
		assert.deepStrictEqual((cantilever.beams as { id: string; end: unknown }[]).find(b => b.id === 'B3')!.end, { x: 'B', y: '1', dx: 1500 });
		const short = model(placeLinear(plan, 'beam', 'B300', 'L1', { point: [3000, 5000] }, { point: [3000, 20] }));
		assert.deepStrictEqual([nearMisses(secondary, 'L1'), nearMisses(cantilever, 'L1'), nearMisses(short, 'L1').length], [[], [], 1]);
	});

	test('a typed end is a length toward the cursor (held to an axis within 5°) or an offset', () => {
		assert.deepStrictEqual([
			typedEnd([0, 0], '1500', [800, 40]),
			typedEnd([0, 0], '1000', [0, -10]),
			typedEnd([0, 0], '1000', [1000, 1000]),
			typedEnd([100, 100], '@1500, -200', undefined),
			typedEnd([0, 0], 'abc', undefined),
		], [
			[1500, 0],
			[0, -1000],
			[707.107, 707.107],
			[1600, -100],
			undefined,
		]);
	});
});
