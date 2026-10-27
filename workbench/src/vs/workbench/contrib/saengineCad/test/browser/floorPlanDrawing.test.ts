/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import type { CadEntitySpec } from '@saengine/cad-editor';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { DEFAULT_FLOOR_PLAN, DEFAULT_OBJECTS } from '../../../../services/saengineProject/common/projectLibraries.generated.js';
import { storiesOf } from '../../../../services/saengineProject/common/floorPlanMembers.js';
import { floorPlanDrawing, profileOutline } from '../../browser/floorPlanDrawing.js';

/** One line per entity, rounded, so a whole plan reads as a snapshot. */
function describe(entity: CadEntitySpec): string {
	const r = (n: number) => Math.round(n);
	const p = ([x, y]: readonly [number, number]) => `${r(x)},${r(y)}`;
	switch (entity.kind) {
		case 'line': return `${entity.layer} line ${p(entity.start)} ${p(entity.end)}`;
		case 'circle': return `${entity.layer} circle ${p(entity.center)} r${r(entity.radius)}`;
		case 'polyline': return `${entity.layer} polyline ${entity.points.map(p).join(' ')}${entity.closed ? ' closed' : ''}`;
		case 'text': return `${entity.layer} text ${p(entity.position)} "${entity.text}"`;
	}
}

suite('SAEngine - Floor plan drawing', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const objects = {
		objects: [
			{ id: 'C1', kind: 'column', profile: { shape: 'rectangle', xDim: 400, yDim: 600 } },
			{ id: 'C2', kind: 'column', profile: { shape: 'circle', radius: 250 } },
			{ id: 'B1', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 500 } },
			{ id: 'S1', kind: 'slab', thickness: 150 },
			{ id: 'F1', kind: 'footing', length: 2000, width: 1500, thickness: 500 },
		],
	};
	const layout = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }] },
		stories: [{ id: 'L1', name: 'Level 1', elevation: 3200 }, { id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L2', name: 'Level 2', elevation: 6400 }],
		columns: [
			{ id: 'c-a1', type: 'C1', at: { x: 'A', y: '1' }, base: 'BASE', top: 'L1', rotation: 90 },
			{ id: 'c-b1', type: 'C2', at: { x: 'B', y: '1', dx: 100 }, base: 'L1', top: 'L2' },
		],
		beams: [{ id: 'b-1', type: 'B1', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }],
		walls: [],
		slabs: [{ id: 's-1', type: 'S1', story: 'L1', boundary: [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'B', y: '1', dy: 3000 }] }],
		footings: [
			{ id: 'f-a1', type: 'F1', story: 'BASE', at: { x: 'A', y: '1' } },
			{ id: 'f-zz', type: 'NOPE', story: 'BASE', at: { x: 'Z', y: '1' } },
		],
	};

	test('a story shows grids, the columns rising to it and the members at its level', () => {
		const plan = floorPlanDrawing(layout, objects, 'L1');
		assert.deepStrictEqual({ entities: plan.drawing.entities.map(describe), problems: plan.problems, warnings: plan.warnings }, {
			entities: [
				'S-GRID line 0,-1500 0,1500',
				'S-GRID-IDEN circle 0,-1900 r400',
				'S-GRID-IDEN text 0,-1900 "A"',
				'S-GRID-IDEN circle 0,1900 r400',
				'S-GRID-IDEN text 0,1900 "A"',
				'S-GRID line 6000,-1500 6000,1500',
				'S-GRID-IDEN circle 6000,-1900 r400',
				'S-GRID-IDEN text 6000,-1900 "B"',
				'S-GRID-IDEN circle 6000,1900 r400',
				'S-GRID-IDEN text 6000,1900 "B"',
				'S-GRID line -1500,0 7500,0',
				'S-GRID-IDEN circle -1900,0 r400',
				'S-GRID-IDEN text -1900,0 "1"',
				'S-GRID-IDEN circle 7900,0 r400',
				'S-GRID-IDEN text 7900,0 "1"',
				'S-SLAB polyline 0,0 6000,0 6000,3000 closed',
				'S-ANNO-IDEN text 4000,1000 "s-1 (150)"',
				'S-BEAM polyline 0,150 6000,150 6000,-150 0,-150 closed',
				// Above the beam, clear of its lines, with its size.
				'S-ANNO-IDEN text 3000,375 "b-1 300×500"',
				// Rotated 90°: the 400 x 600 column is 600 wide in x; its label goes right of it, below
				// rather than above, where the beam's label already is.
				'S-COLS polyline 300,-200 300,200 -300,200 -300,-200 closed',
				'S-ANNO-IDEN text 1360,-425 "c-a1 400×600"',
			],
			problems: [],
			warnings: [],
		});
	});

	test('slabs on nothing and slabs with a beam across them are warned about', () => {
		const crossed = {
			...layout,
			columns: [],
			beams: [{ id: 'b-2', type: 'B1', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1', dy: 3000 } }],
			slabs: [
				{ id: 's-1', type: 'S1', story: 'L1', boundary: [{ x: 'A', y: '1', dy: -3000 }, { x: 'B', y: '1', dy: -3000 }, { x: 'B', y: '1', dy: 3000 }, { x: 'A', y: '1', dy: 3000 }] },
				{ id: 's-2', type: 'S1', story: 'L1', boundary: [{ x: 'A', y: '1', dx: 8000 }, { x: 'B', y: '1', dx: 4000 }, { x: 'B', y: '1', dx: 4000, dy: 2000 }] },
			],
		};
		assert.deepStrictEqual(floorPlanDrawing(crossed, objects, 'L1').warnings, [
			's-1: no beam, wall or column supports it; place beams along its edges or columns under it.',
			's-1: a beam or wall runs across it, but the slab is not split there; replace it with a Polygon Slab on each side.',
			's-2: no beam, wall or column supports it; place beams along its edges or columns under it.',
		]);
	});

	test('the base shows footings and reports members it cannot draw', () => {
		const plan = floorPlanDrawing(layout, objects, 'BASE');
		assert.deepStrictEqual({
			members: plan.drawing.entities.filter(e => !e.layer.startsWith('S-GRID')).map(describe),
			problems: plan.problems,
		}, {
			members: [
				'S-FNDN polyline -1000,-750 1000,-750 1000,750 -1000,750 closed',
				'S-ANNO-IDEN text 0,0 "f-a1"',
			],
			problems: ['f-zz: unknown object type \'NOPE\'', 'f-zz: grid point Z-1 does not exist'],
		});
	});

	test('stories sort by elevation and the default model draws without problems', () => {
		const stories = storiesOf(DEFAULT_FLOOR_PLAN);
		const plan = floorPlanDrawing(DEFAULT_FLOOR_PLAN, DEFAULT_OBJECTS, stories[1].id);
		assert.deepStrictEqual({
			stories: storiesOf(layout).map(s => s.id),
			defaultPlan: { lines: plan.drawing.entities.filter(e => e.kind === 'line').length, problems: plan.problems },
			profiles: [
				profileOutline({ shape: 'I', overallWidth: 200, overallDepth: 400, webThickness: 10, flangeThickness: 20 }),
				profileOutline({ shape: 'circleHollow', radius: 100, wallThickness: 5 }),
				profileOutline({ shape: 'rectangle', xDim: 0, yDim: 100 }),
			],
		}, {
			stories: ['BASE', 'L1', 'L2'],
			defaultPlan: { lines: 4, problems: [] },
			profiles: [
				{ kind: 'polygon', points: [[-100, -200], [100, -200], [100, -180], [5, -180], [5, 180], [100, 180], [100, 200], [-100, 200], [-100, 180], [-5, 180], [-5, -180], [-100, -180]] },
				{ kind: 'circle', radius: 100 },
				undefined,
			],
		});
	});
});
