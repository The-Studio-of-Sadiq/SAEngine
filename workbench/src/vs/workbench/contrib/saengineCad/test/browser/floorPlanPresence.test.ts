/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IMemberShape } from '../../browser/floorPlanDrawing.js';
import { nearestAci, offsetPolygon, presenceDrawing } from '../../browser/floorPlanPresence.js';

suite('SAEngine - Floor plan co-editing presence', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const round = (points: readonly (readonly [number, number])[]) => points.map(([x, y]) => [Math.round(x), Math.round(y)]);

	test('a colleague\'s colour is drawn in the nearest AutoCAD colour', () => {
		// The colleague colours of the co-editing engine: blue, red, green, purple, orange, cyan.
		assert.deepStrictEqual(['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf', undefined, 'teal'].map(nearestAci), [5, 1, 3, 6, 30, 4, 6, 6]);
	});

	test('the outline runs outside the member, whichever way its corners go', () => {
		const square: [number, number][] = [[0, 0], [100, 0], [100, 100], [0, 100]];
		assert.deepStrictEqual(round(offsetPolygon(square, 10)), [[-10, -10], [110, -10], [110, 110], [-10, 110]]);
		assert.deepStrictEqual(round(offsetPolygon([...square].reverse(), 10)), [[-10, 110], [110, 110], [110, -10], [-10, -10]]);
	});

	test('each colleague\'s selected members on this storey are outlined in their colour, with their name above', () => {
		const members: IMemberShape[] = [
			{ group: 'columns', id: 'C1', outline: { kind: 'polygon', points: [[-200, -300], [200, -300], [200, 300], [-200, 300]] } },
			{ group: 'columns', id: 'C2', outline: { kind: 'circle', center: [6000, 0], radius: 250 } },
		];
		const drawing = presenceDrawing(members, [
			{ name: 'Rahim', color: '#d62728', selection: ['C1'] },
			{ name: 'Karim', color: '#1f77b4', selection: ['C2', 'B9'] },
			{ name: 'Elsewhere', color: '#2ca02c', selection: ['C9'] },
		]);
		assert.deepStrictEqual(drawing.layers.map(l => [l.name, l.color]), [['SAENGINE-PRESENCE-1', 1], ['SAENGINE-PRESENCE-5', 5]]);
		assert.deepStrictEqual(drawing.entities.map(e => e.kind === 'polyline' ? [e.layer, round(e.points)] : e.kind === 'circle' ? [e.layer, e.center, e.radius] : e.kind === 'text' ? [e.layer, round([e.position]), e.text] : []), [
			['SAENGINE-PRESENCE-1', [[-320, -420], [320, -420], [320, 420], [-320, 420]]],
			['SAENGINE-PRESENCE-1', [[0, 640]], 'Rahim'],
			['SAENGINE-PRESENCE-5', [6000, 0], 370],
			['SAENGINE-PRESENCE-5', [[6000, 590]], 'Karim'],
		]);
	});
});
