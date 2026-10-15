/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { addArea, addMember, addSupport, copyElements, divideMember, EditResult, mirrorElements, moveElements, parseOffset, removeElements } from '../../browser/structureEdits.js';
import { gridGeometry, Json, list, modelerScene } from '../../browser/structureGeometry.js';

function ok(result: EditResult): Json {
	if (!result.ok) {
		assert.fail(result.error);
	}
	return result.doc;
}

const EMPTY: Json = { schema: 'saengine.structure/1', grids: [], members: [], areas: [], supports: [] };

suite('SAEngine - Structural model edits', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('grid systems give lines, intersections and levels', () => {
		const cartesian = gridGeometry([{
			kind: 'cartesian', id: 'G1', origin: { x: 0, y: 0, z: 0 }, rotation: 0,
			x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }],
			y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }],
			z: [{ label: 'Z0', position: 0 }, { label: 'Z1', position: 4000 }],
		}]);
		const cylindrical = gridGeometry([{
			kind: 'cylindrical', id: 'G2', origin: { x: 0, y: 0, z: 0 },
			radii: [{ label: 'R1', position: 10000 }], angles: [{ label: 'A0', angle: 0 }, { label: 'A90', angle: 90 }],
			z: [{ label: 'Z0', position: 0 }],
		}]);
		assert.deepStrictEqual({
			cartesian: { points: cartesian.points.length, lines: cartesian.lines.length, levels: cartesian.levels },
			cylindrical: { points: cylindrical.points.map(p => p.map(v => Math.round(v))) },
		}, {
			cartesian: { points: 8, lines: 8, levels: [{ label: 'Z0', z: 0 }, { label: 'Z1', z: 4000 }] },
			cylindrical: { points: [[0, 0, 0], [10000, 0, 0], [0, 10000, 0]] },
		});
	});

	test('draws members, areas and supports with fresh ids', () => {
		let doc = ok(addMember(EMPTY, 'COL', [0, 0, 0], [0, 0, 4000]));
		doc = ok(addMember(doc, 'BM', [0, 0, 4000], [6000, 0, 4000]));
		doc = ok(addArea(doc, 'RS', [[0, 0, 4000], [6000, 0, 4000], [6000, 5000, 4000], [0, 5000, 4000]]));
		doc = ok(addSupport(doc, [0, 0, 0], 'fixed'));
		const scene = modelerScene(doc, new Map([['COL', 'column'], ['BM', 'beam'], ['RS', 'slab']]));
		assert.deepStrictEqual({
			members: scene.members.map(m => `${m.id}:${m.kind}`),
			areas: scene.areas.map(a => `${a.id}:${a.kind}:${a.outline.length}`),
			supports: scene.supports.map(s => `${s.id}:${s.fixity}`),
			errors: [
				addMember(doc, 'BM', [0, 0, 0], [0, 0, 0]).ok,
				addArea(doc, 'RS', [[0, 0, 0], [1000, 0, 0], [2000, 0, 0]]).ok,
				addArea(doc, 'RS', [[0, 0, 0], [1000, 0, 0], [1000, 1000, 500], [0, 1000, 0]]).ok,
				addSupport(doc, [0, 0, 0], 'pinned').ok,
				addMember(doc, '', [0, 0, 0], [1, 1, 1]).ok,
			],
		}, {
			members: ['M1:column', 'M2:beam'],
			areas: ['A1:slab:4'],
			supports: ['SP1:fixed'],
			errors: [false, false, false, false, false],
		});
	});

	test('moves, copies in an array, mirrors, divides and removes', () => {
		let doc = ok(addMember(EMPTY, 'COL', [0, 0, 0], [0, 0, 4000]));
		doc = ok(addSupport(doc, [0, 0, 0], 'fixed'));
		const column = [{ kind: 'member' as const, id: 'M1' }, { kind: 'support' as const, id: 'SP1' }];

		const moved = ok(moveElements(doc, column, [1000, 0, 0]));
		const array = ok(copyElements(doc, column, [6000, 0, 0], 3));
		const mirrored = ok(mirrorElements(ok(moveElements(doc, column, [1000, 2000, 0])), column, [0, 0, 0], [5000, 0, 0]));
		const divided = ok(divideMember(doc, 'M1', 4));
		const removed = ok(removeElements(doc, [{ kind: 'support', id: 'SP1' }]));
		const ends = (d: Json) => list(d.members).map(m => `${m.id}@${(m.start as Json).x},${(m.start as Json).y},${(m.start as Json).z}-${(m.end as Json).z}`);
		assert.deepStrictEqual({
			moved: ends(moved),
			array: { members: ends(array), supports: list(array.supports).map(s => `${s.id}@${(s.at as Json).x}`) },
			mirrored: ends(mirrored),
			divided: ends(divided),
			removed: [list(removed.members).length, list(removed.supports).length],
		}, {
			moved: ['M1@1000,0,0-4000'],
			array: { members: ['M1@0,0,0-4000', 'M2@6000,0,0-4000', 'M3@12000,0,0-4000', 'M4@18000,0,0-4000'], supports: ['SP1@0', 'SP2@6000', 'SP3@12000', 'SP4@18000'] },
			mirrored: ['M1@1000,2000,0-4000', 'M2@1000,-2000,0-4000'],
			divided: ['M1@0,0,0-1000', 'M2@0,0,1000-2000', 'M3@0,0,2000-3000', 'M4@0,0,3000-4000'],
			removed: [1, 0],
		});
	});

	test('reads typed offsets', () => {
		assert.deepStrictEqual(
			[parseOffset('6000, 0, 0'), parseOffset('0 5000 0 3'), parseOffset('1, 2'), parseOffset('a, b, c')],
			[{ delta: [6000, 0, 0], count: undefined }, { delta: [0, 5000, 0], count: 3 }, undefined, undefined],
		);
	});
});
