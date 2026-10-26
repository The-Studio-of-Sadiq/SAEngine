/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { planLabel } from '../../browser/floorPlanDrawing.js';
import { copyId } from '../../browser/floorPlanEdits.js';
import { copyStory } from '../../browser/floorPlanTypical.js';
import { addObjectType, validateSize } from '../../browser/floorPlanTypes.js';

suite('SAEngine - Floor plan new types and labels', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const materials = { materials: [{ id: 'C20.7', category: 'concrete' }, { id: 'C24.1', category: 'concrete' }, { id: 'B420', category: 'rebar' }] };

	test('a new type is concrete of the typed size, in the concrete the other types use, and never doubled', () => {
		const objects = { schema: 'saengine.objects/1', objects: [{ id: 'C400x600', kind: 'column', material: 'C24.1' }] };
		const beam = addObjectType(objects, materials, 'beam', '250 × 450');
		const slab = addObjectType({}, materials, 'slab', '125');
		assert.ok(beam.ok && slab.ok);
		assert.deepStrictEqual({
			beam: beam.objects.objects,
			slab: slab.objects,
			again: (r => r.ok && [r.id, r.existed, r.objects === beam.objects])(addObjectType(beam.objects, materials, 'beam', '250x450')),
			clash: addObjectType({ objects: [{ id: 'B250x450', kind: 'column' }] }, materials, 'beam', '250x450').ok,
			noConcrete: addObjectType({}, {}, 'wall', '200').ok,
			invalid: [validateSize('column', '400'), validateSize('slab', '125'), validateSize('beam', '20x450')].map(v => v === undefined),
		}, {
			beam: [objects.objects[0], { id: 'B250x450', name: 'Beam 250x450', kind: 'beam', material: 'C24.1', profile: { shape: 'rectangle', xDim: 250, yDim: 450 } }],
			slab: { schema: 'saengine.objects/1', objects: [{ id: 'S125', name: 'Slab 125', kind: 'slab', material: 'C20.7', thickness: 125 }] },
			again: ['B250x450', true, true],
			clash: false,
			noConcrete: false,
			invalid: [false, true, false],
		});
	});

	test('a copy on another story keeps its label on the plan', () => {
		const layout = {
			stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3000 }, { id: 'L2', name: 'Level 2', elevation: 6000 }, { id: 'L3', name: 'Level 3', elevation: 9000 }],
			grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }] },
			columns: [], walls: [], slabs: [], footings: [],
			beams: [{ id: 'B5', type: 'B', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }, { id: 'B5-L3', type: 'B', story: 'L3', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1', dx: 10 } }],
		};
		const copied = copyStory(layout, 'L1', ['L1', 'L2']);
		assert.deepStrictEqual({
			ids: (copied.beams as { id: string }[]).map(b => b.id),
			labels: ['B5', 'B5-L2', 'B5-L3', 'B5-X'].map(id => planLabel(layout, id)),
			taken: copyId(layout, 'beams', 'B5', 'L3'),
		}, {
			ids: ['B5', 'B5-L3', 'B5-L2'],
			labels: ['B5', 'B5', 'B5', 'B5-X'],
			taken: 'B1',
		});
	});
});
