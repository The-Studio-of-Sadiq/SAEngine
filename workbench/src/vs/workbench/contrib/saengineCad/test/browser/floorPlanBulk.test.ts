/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { BulkResult, bulkNotice, copyMembers, copyToClipboard, copyToStories, deleteMembers, fill, mirrorMembers, moveMembers, parseCommand, paste, rotateMembers } from '../../browser/floorPlanBulk.js';
import { inSync } from '../../browser/floorPlanTypical.js';

suite('SAEngine - Floor plan bulk edits', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const empty = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }, { label: 'C', position: 12000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }, { id: 'L2', name: 'Level 2', elevation: 6400 }, { id: 'L3', name: 'Level 3', elevation: 9600, similarTo: 'L2' }],
		columns: [], beams: [], walls: [], slabs: [], footings: [],
	};
	type Layout = { [key: string]: unknown };
	const ok = (result: BulkResult): Extract<BulkResult, { ok: true }> => {
		if (!result.ok) {
			assert.fail(result.error);
		}
		return result;
	};
	const list = (layout: Layout, group: string) => layout[group] as { [key: string]: unknown }[];
	const error = (result: BulkResult) => result.ok ? 'ok' : result.error;

	test('fill places columns, beams, slabs and walls on the grid inside a window and skips what is there', () => {
		const columns = ok(fill(empty, 'columns', 'C400', 'L1', { min: [-100, -100], max: [6100, 5100] }));
		const again = ok(fill(columns.layout, 'columns', 'C400', 'L1'));
		const beams = ok(fill(again.layout, 'beams', 'B300', 'L1'));
		const slabs = ok(fill(beams.layout, 'slabs', 'S150', 'L1', { min: [-1, -1], max: [6001, 5001] }));
		const walls = ok(fill(slabs.layout, 'walls', 'W200', 'L1', undefined, 'y'));
		assert.deepStrictEqual({
			columns: [columns.placed, columns.skipped, again.placed, again.skipped],
			at: list(again.layout, 'columns').map(c => `${c.id}@${(c.at as Layout).x}${(c.at as Layout).y} ${c.base}->${c.top}`),
			beams: [beams.placed, beams.skipped, list(beams.layout, 'beams')[0]],
			slabs: [slabs.placed, list(slabs.layout, 'slabs')[0]],
			walls: [walls.placed, list(walls.layout, 'walls')[0]],
			notice: bulkNotice(again, 'placed'),
			refused: [
				error(fill(empty, 'columns', 'C400', 'BASE')),
				error(fill(empty, 'slabs', 'S150', 'L1', { min: [100, 100], max: [200, 200] })),
				error(fill(empty, 'beams', '', 'L1')),
			],
		}, {
			columns: [4, 0, 2, 4],
			at: ['C1@A1 BASE->L1', 'C2@A2 BASE->L1', 'C3@B1 BASE->L1', 'C4@B2 BASE->L1', 'C5@C1 BASE->L1', 'C6@C2 BASE->L1'],
			beams: [7, 0, { id: 'B1', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }],
			slabs: [1, { id: 'S1', type: 'S150', story: 'L1', boundary: [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'B', y: '2' }, { x: 'A', y: '2' }] }],
			walls: [3, { id: 'W1', type: 'W200', base: 'BASE', top: 'L1', start: { x: 'A', y: '1' }, end: { x: 'A', y: '2' } }],
			notice: 'Placed 2, skipped 4 existing.',
			refused: [
				'Columns and walls rise to a story from the one below; choose a higher story.',
				'No whole bay is inside the window.',
				'Define an object type for this fill in Object Types first.',
			],
		});
	});

	test('a long beam covers the segments under it, so fill does not double it', () => {
		const long = { ...empty, beams: [{ id: 'B1', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'C', y: '1' } }] };
		const result = ok(fill(long, 'beams', 'B300', 'L1', undefined, 'x'));
		assert.deepStrictEqual([result.placed, result.skipped], [2, 2]);
	});

	test('move, copy (array), mirror, rotate and delete act on the whole selection', () => {
		const base = ok(fill(empty, 'columns', 'C400', 'L1', { min: [-1, -1], max: [1, 5001] })).layout; // C1 at A1, C2 at A2
		const refs = [{ group: 'columns' as const, id: 'C1' }, { group: 'columns' as const, id: 'C2' }];
		const moved = ok(moveMembers(base, refs, [250, 0]));
		const array = ok(copyMembers(base, refs, [6000, 0], 2));
		const mirrored = ok(mirrorMembers(ok(rotateMembers(base, refs, 30)).layout, refs, 'x', 'B'));
		const onLine = ok(mirrorMembers(ok(copyMembers(base, refs, [6000, 0])).layout, [{ group: 'columns', id: 'C3' }], 'x', 'B'));
		const flipped = ok(mirrorMembers(base, [{ group: 'columns', id: 'C1' }], 'y', '2', false));
		const deleted = ok(deleteMembers(base, [refs[0]]));
		assert.deepStrictEqual({
			moved: list(moved.layout, 'columns').map(c => c.at),
			array: [array.placed, array.skipped, list(array.layout, 'columns').map(c => `${c.id}@${(c.at as Layout).x}${(c.at as Layout).y}`)],
			mirrored: list(mirrored.layout, 'columns').map(c => `${c.id}@${(c.at as Layout).x}${(c.at as Layout).y}/${c.rotation}`),
			onLine: [onLine.placed, onLine.skipped],
			flipped: list(flipped.layout, 'columns').map(c => `${c.id}@${(c.at as Layout).x}${(c.at as Layout).y}`),
			deleted: list(deleted.layout, 'columns').map(c => c.id),
			rotateBeam: error(rotateMembers(base, [{ group: 'beams', id: 'B1' }], 90)),
			copyOnTop: error(copyMembers(base, refs, [0, 0])),
		}, {
			moved: [{ x: 'A', y: '1', dx: 250 }, { x: 'A', y: '2', dx: 250 }],
			array: [4, 0, ['C1@A1', 'C2@A2', 'C3@B1', 'C4@B2', 'C5@C1', 'C6@C2']],
			mirrored: ['C1@A1/30', 'C2@A2/30', 'C3@C1/150', 'C4@C2/150'],
			onLine: [0, 1],
			flipped: ['C1@A2', 'C2@A2'],
			deleted: ['C2'],
			rotateBeam: 'Only columns rotate here; beams, walls and slabs follow their points, and footings turn in 9 Substructure.',
			copyOnTop: 'Give the copy a distance; a copy on top of the original is skipped.',
		});
	});

	test('a selection moves and mirrors as one rigid group; a blocked member stays where it was', () => {
		const grids = { x: [...empty.grids.x, { label: 'D', position: 18000 }], y: empty.grids.y };
		const at = (x: string, y: string) => ({ x, y });
		const frame = {
			...empty, grids,
			columns: [{ id: 'C1', type: 'C400', base: 'BASE', top: 'L1', at: at('A', '1') }, { id: 'C2', type: 'C400', base: 'BASE', top: 'L1', at: at('B', '1') }, { id: 'C3', type: 'C400', base: 'BASE', top: 'L1', at: at('C', '1') }],
			beams: [{ id: 'B1', type: 'B300', story: 'L1', start: at('A', '1'), end: at('B', '1') }, { id: 'B2', type: 'B300', story: 'L1', start: at('B', '1'), end: at('C', '1') }],
		};
		const all = [...frame.columns.map(c => ({ group: 'columns' as const, id: c.id })), ...frame.beams.map(b => ({ group: 'beams' as const, id: b.id }))];
		const shown = (layout: Layout) => [
			...list(layout, 'columns').map(c => `${c.id}:${c.type}@${(c.at as Layout).x}${(c.at as Layout).y}`),
			...list(layout, 'beams').map(b => `${b.id}:${(b.start as Layout).x}${(b.start as Layout).y}-${(b.end as Layout).x}${(b.end as Layout).y}`),
		].join(' ');
		const moved = ok(moveMembers(frame, all, [6000, 0]));
		// Members of the group never block one another; only a member outside it does (C9 at B2).
		const blocker = { ...frame, columns: [...frame.columns, { id: 'C9', type: 'C600', base: 'BASE', top: 'L1', at: at('B', '2') }] };
		const partly = ok(moveMembers(blocker, [{ group: 'columns', id: 'C1' }, { group: 'columns', id: 'C2' }], [6000, 5000]));
		const mirrorFrame = {
			...empty,
			columns: [{ id: 'C1', type: 'C600', base: 'BASE', top: 'L1', at: at('A', '1') }, { id: 'C2', type: 'C400', base: 'BASE', top: 'L1', at: at('C', '1') }, { id: 'C3', type: 'C400', base: 'BASE', top: 'L1', at: at('A', '2') }],
		};
		const mirrored = ok(mirrorMembers(mirrorFrame, [{ group: 'columns', id: 'C1' }, { group: 'columns', id: 'C3' }], 'x', 'B', false));
		assert.deepStrictEqual({
			moved: [moved.placed, moved.skipped, shown(moved.layout)],
			partly: [partly.placed, partly.skipped, shown(partly.layout)],
			mirrored: [mirrored.placed, mirrored.skipped, shown(mirrored.layout)],
		}, {
			moved: [5, 0, 'C1:C400@B1 C2:C400@C1 C3:C400@D1 B1:B1-C1 B2:C1-D1'],
			partly: [1, 1, 'C1:C400@A1 C2:C400@C2 C3:C400@C1 C9:C600@B2 B1:A1-B1 B2:B1-C1'],
			mirrored: [1, 1, 'C1:C600@A1 C2:C400@C1 C3:C400@C2'],
		});
	});

	test('a move off the grid lines keeps the nearest intersection and an offset', () => {
		const base = ok(fill(empty, 'beams', 'B300', 'L1', { min: [-1, -1], max: [6001, 1] })).layout;
		const moved = ok(moveMembers(base, [{ group: 'beams', id: 'B1' }], [3500, 1200]));
		assert.deepStrictEqual(list(moved.layout, 'beams')[0], { id: 'B1', type: 'B300', story: 'L1', start: { x: 'B', y: '1', dx: -2500, dy: 1200 }, end: { x: 'C', y: '1', dx: -2500, dy: 1200 } });
	});

	test('copy to stories follows the typical floors; paste places at a base point', () => {
		const base = ok(fill(ok(fill(empty, 'columns', 'C400', 'L1')).layout, 'beams', 'B300', 'L1', { min: [-1, -1], max: [6001, 1] })).layout;
		const refs = [{ group: 'columns' as const, id: 'C1' }, { group: 'beams' as const, id: 'B1' }];
		const copied = ok(copyToStories(base, refs, 'L1', ['L2']));
		const twice = ok(copyToStories(copied.layout, refs, 'L1', ['L3']));
		const clipboard = copyToClipboard(base, [{ group: 'beams', id: 'B1' }])!;
		const pasted = ok(paste(base, clipboard, 'L2', [6000, 5000]));
		assert.deepStrictEqual({
			copied: [copied.placed, copied.skipped, copied.ids.map(r => r.id)],
			stories: list(copied.layout, 'columns').filter(c => c.top !== 'L1').map(c => `${c.base}->${c.top}`),
			typicalInSync: inSync(copied.layout, ['L2', 'L3']),
			twice: [twice.placed, twice.skipped],
			clipboard: clipboard.base,
			pasted: list(pasted.layout, 'beams').map(b => [b.story, b.start, b.end]),
			sameStory: error(copyToStories(base, refs, 'L1', ['L1'])),
		}, {
			copied: [4, 0, ['C7', 'B2', 'C8', 'B3']],
			stories: ['L1->L2', 'L2->L3'],
			typicalInSync: true,
			twice: [0, 4],
			clipboard: [0, 0],
			pasted: [['L1', { x: 'A', y: '1' }, { x: 'B', y: '1' }], ['L2', { x: 'B', y: '2' }, { x: 'C', y: '2' }]],
			sameStory: 'Choose other stories than this one and its typical floor.',
		});
	});

	test('the command line reads floor plan commands and leaves the rest to the CAD editor', () => {
		assert.deepStrictEqual([
			'select all', 'select type C400', 'select c1 b2', 'fill columns', 'fill walls x A-1 C-2', 'fill beams A-1 Q-9',
			'copy 6000,0', 'array @6000, 0 x 3', 'array 6000 0', 'move -150 200', 'mirror B', 'mirror y 2 move', 'mirror Z',
			'rotate 90', 'rotate to 45', 'tostories', 'tostories all', 'tostories level 2', 'tostories L2 L3', 'delete', 'line', '',
		].map(text => parseCommand(text, empty)), [
			{ kind: 'select', what: 'all' },
			{ kind: 'select', what: 'type', type: 'C400' },
			{ kind: 'select', what: 'ids', ids: ['C1', 'B2'] },
			{ kind: 'fill', fill: 'columns', direction: 'both' },
			{ kind: 'fill', fill: 'walls', direction: 'x', rect: { min: [0, 0], max: [12000, 5000] } },
			{ kind: 'error', message: 'Name the window by two grid points, e.g. fill beams A-1 C-3.' },
			{ kind: 'copy', delta: [6000, 0], times: 1 },
			{ kind: 'array', delta: [6000, 0], times: 3 },
			{ kind: 'error', message: 'array dx, dy times (mm)' },
			{ kind: 'move', delta: [-150, 200] },
			{ kind: 'mirror', axis: 'x', label: 'B', keep: true },
			{ kind: 'mirror', axis: 'y', label: '2', keep: false },
			{ kind: 'error', message: 'There is no grid line Z.' },
			{ kind: 'rotate', degrees: 90, absolute: false },
			{ kind: 'rotate', degrees: 45, absolute: true },
			{ kind: 'tostories' },
			{ kind: 'tostories', stories: ['L1', 'L2', 'L3'] },
			{ kind: 'tostories', stories: ['L2'] },
			{ kind: 'tostories', stories: ['L2', 'L3'] },
			{ kind: 'delete' },
			undefined,
			undefined,
		]);
	});
});
