/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	arcThroughPoints,
	conversionSteps,
	IDraftArc,
	IDraftCircle,
	IDraftLine,
	IDraftPolyline,
	parseDraftPoint,
	toPointRef,
} from '../../browser/floorPlanDrafting.js';
import { gridsOf } from '../../browser/floorPlanDrawing.js';

suite('SAEngine - Floor plan drafting', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const line1: IDraftLine = {
		kind: 'line',
		id: 'D1',
		story: 'L1',
		start: [0, 0],
		end: [6000, 5000],
	};

	const polylineClosed: IDraftPolyline = {
		kind: 'polyline',
		id: 'D3',
		story: 'L1',
		points: [[0, 0], [1000, 0], [1000, 500], [0, 500]],
		closed: true,
	};

	const arc1: IDraftArc = {
		kind: 'arc',
		id: 'D4',
		story: 'BASE',
		center: [3000, 2500],
		radius: 500,
		startAngle: 0,
		endAngle: 90,
	};

	const circle1: IDraftCircle = {
		kind: 'circle',
		id: 'D5',
		story: 'L1',
		center: [1000, 1000],
		radius: 250,
	};

	test('draft conversion names the nearest grid lines and preserves offsets to 1 mm', () => {
		const grids = gridsOf({ grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] } });
		assert.deepStrictEqual(toPointRef([6100, 4900], grids), { x: 'B', y: '2', dx: 100, dy: -100 });
		assert.strictEqual(toPointRef([1, 2], { x: new Map(), y: new Map() }), undefined);
		assert.deepStrictEqual(conversionSteps([line1], 'beam', 'B250', 'L1', grids).steps, [
			{ action: 'beams.place', params: { type: 'B250', between: [[{ x: 'A', y: '1', dx: 0, dy: 0 }, { x: 'B', y: '2', dx: 0, dy: 0 }]], storeys: ['L1'] } },
			{ action: 'drafting.delete', params: { ids: ['D1'] } },
		]);
		assert.deepStrictEqual(conversionSteps([polylineClosed], 'slab', 'S125', 'L1', grids).steps, [
			{ action: 'slabs.place', params: { type: 'S125', panels: [[{ x: 'A', y: '1', dx: 0, dy: 0 }, { x: 'A', y: '1', dx: 1000, dy: 0 }, { x: 'A', y: '1', dx: 1000, dy: 500 }, { x: 'A', y: '1', dx: 0, dy: 500 }]], storeys: ['L1'] } },
			{ action: 'drafting.delete', params: { ids: ['D3'] } },
		]);
		assert.deepStrictEqual(conversionSteps([circle1], 'beam', 'B250', 'L1', grids).skipped, ['D5']);
	});

	test('draft conversion handles CAD selected entities with handle and points', () => {
		const grids = gridsOf({ grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] } });
		const selectedLine = { handle: '2F', kind: 'line', points: [[0, 0], [6000, 0]] as const };
		const selectedPolyClosed = { handle: '3A', kind: 'polyline', points: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]] as const, closed: true };

		const beamRes = conversionSteps([selectedLine], 'beam', 'B300', 'L1', grids);
		assert.deepStrictEqual(beamRes.steps[0], {
			action: 'beams.place',
			params: { type: 'B300', between: [[{ x: 'A', y: '1', dx: 0, dy: 0 }, { x: 'B', y: '1', dx: 0, dy: 0 }]], storeys: ['L1'] },
		});

		const slabRes = conversionSteps([selectedPolyClosed], 'slab', 'S150', 'L1', grids);
		assert.deepStrictEqual(slabRes.steps[0], {
			action: 'slabs.place',
			params: { type: 'S150', panels: [[{ x: 'A', y: '1', dx: 0, dy: 0 }, { x: 'B', y: '1', dx: 0, dy: 0 }, { x: 'B', y: '2', dx: 0, dy: 0 }, { x: 'A', y: '2', dx: 0, dy: 0 }]], storeys: ['L1'] },
		});
	});

	test('arcThroughPoints stores the CCW arc containing the middle point', () => {
		// 359.9999° is 0°: compare angles around the circle.
		const angleOff = (angle: number, expected: number) => { const d = ((angle - expected) % 360 + 360) % 360; return Math.min(d, 360 - d); };
		const first = arcThroughPoints([1000, 0], [707.107, 707.107], [0, 1000]);
		assert.ok(first);
		assert.ok(Math.abs(first.center[0]) < 0.001 && Math.abs(first.center[1]) < 0.001);
		assert.ok(Math.abs(first.radius - 1000) < 0.001);
		assert.ok(angleOff(first.startAngle, 0) < 0.001 && angleOff(first.endAngle, 90) < 0.001);
		const reversed = arcThroughPoints([0, 1000], [707.107, 707.107], [1000, 0]);
		assert.ok(reversed);
		assert.ok(Math.abs(reversed.center[0]) < 0.001 && Math.abs(reversed.center[1]) < 0.001);
		assert.ok(Math.abs(reversed.radius - 1000) < 0.001);
		assert.ok(angleOff(reversed.startAngle, 0) < 0.001 && angleOff(reversed.endAngle, 90) < 0.001);
		assert.strictEqual(arcThroughPoints([0, 0], [1, 1], [2, 2]), undefined);
	});

	test('parseDraftPoint reads absolute, relative, polar, and direct distance points', () => {
		assert.deepStrictEqual(parseDraftPoint('120, 240', [10, 20], [1, 0]), [120, 240]);
		assert.deepStrictEqual(parseDraftPoint('@120,-40', [10, 20], [1, 0]), [130, -20]);
		const polar = parseDraftPoint('@100<30', [10, 20], [1, 0]);
		assert.ok(polar);
		assert.ok(Math.abs(polar[0] - 96.6025403784) < 1e-8 && Math.abs(polar[1] - 70) < 1e-8);
		assert.deepStrictEqual(parseDraftPoint('50', [10, 20], [3, 4]), [40, 60]);
		assert.strictEqual(parseDraftPoint('50', [10, 20], [0, 0]), undefined);
	});
});
