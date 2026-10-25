/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { formatPoint } from '../../../../services/saengineProject/common/floorPlanMembers.js';
import { filterRows, memberRows, membersCsv, rowKey, rowRange, setRowsStory, setRowsType, sortRows, storyOptions, typeOptions } from '../../browser/floorPlanTableModel.js';

suite('SAEngine - Members table', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const layout = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }, { id: 'L2', name: 'Level 2', elevation: 6400 }],
		columns: [
			{ id: 'C10', type: 'C400', at: { x: 'A', y: '1', dx: 150 }, base: 'BASE', top: 'L1', rotation: 0 },
			{ id: 'C2', type: 'C400', at: { x: 'B', y: '1' }, base: 'BASE', top: 'L2', rotation: 0 },
		],
		beams: [
			{ id: 'B1', type: 'B300', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } },
			{ id: 'B2', type: 'B300', story: 'L2', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } },
		],
		walls: [],
		slabs: [{ id: 'S1', type: 'S150', story: 'L1', boundary: [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'B', y: '2' }, { x: 'A', y: '2' }] }],
		footings: [{ id: 'F1', type: 'F1500', story: 'BASE', at: { x: 'A', y: '1' }, rotation: 0 }],
	};
	const objects = {
		objects: [
			{ id: 'C400', name: 'Column 400', kind: 'column' },
			{ id: 'C500', name: 'Column 500', kind: 'column' },
			{ id: 'B300', name: 'Beam 300', kind: 'beam' },
			{ id: 'B350', name: 'Beam 350', kind: 'beam' },
			{ id: 'S150', name: 'Slab 150', kind: 'slab' },
			{ id: 'F1500', name: 'Footing', kind: 'footing' },
			{ id: 'PC4', name: 'Pile cap', kind: 'pileCap' },
		],
	};
	const ids = (rows: readonly { readonly id: string }[]) => rows.map(r => r.id);

	test('rows: every member with its story or span and its grid location', () => {
		assert.deepStrictEqual(memberRows(layout).map(r => [r.id, r.group, r.type, r.storyLabel, r.location]), [
			['C10', 'columns', 'C400', 'Base – Level 1', 'A-1 (+150, 0)'],
			['C2', 'columns', 'C400', 'Base – Level 2', 'B-1'],
			['B1', 'beams', 'B300', 'Level 1', 'A-1 → B-1'],
			['B2', 'beams', 'B300', 'Level 2', 'A-1 → B-1'],
			['S1', 'slabs', 'S150', 'Level 1', 'A–B / 1–2'],
			['F1', 'footings', 'F1500', 'Base', 'A-1'],
		]);
		assert.strictEqual(formatPoint({ x: 'C', y: '3', dy: -200 }), 'C-3 (0, -200)');
	});

	test('filters by story (columns rising through it count), kind, type and text; sorts naturally', () => {
		const rows = memberRows(layout);
		assert.deepStrictEqual({
			level2: ids(filterRows(layout, rows, { story: 'L2' })),
			level1Columns: ids(filterRows(layout, rows, { story: 'L1', group: 'columns' })),
			type: ids(filterRows(layout, rows, { type: 'B300' })),
			text: ids(filterRows(layout, rows, { text: 'b-1' })),
			byId: ids(sortRows(rows, { key: 'id', descending: false })),
			byStoryDown: ids(sortRows(rows, { key: 'story', descending: true })),
		}, {
			level2: ['C2', 'B2'],
			level1Columns: ['C10', 'C2'],
			type: ['B1', 'B2'],
			text: ['C2', 'B1', 'B2'],
			byId: ['B1', 'B2', 'C2', 'C10', 'F1', 'S1'],
			byStoryDown: ['C2', 'B2', 'C10', 'B1', 'S1', 'F1'],
		});
	});

	test('type and story options follow the group', () => {
		assert.deepStrictEqual({
			column: typeOptions(objects, 'columns'),
			footing: typeOptions(objects, 'footings').map(([id]) => id),
			columnStories: storyOptions(layout, 'columns').map(s => s.id),
			beamStories: storyOptions(layout, 'beams').map(s => s.id),
		}, {
			column: [['C400', 'Column 400'], ['C500', 'Column 500']],
			footing: ['F1500', 'PC4'],
			columnStories: ['L1', 'L2'],
			beamStories: ['BASE', 'L1', 'L2'],
		});
	});

	test('type edits change the selected rows that can take the type, skipping the rest', () => {
		const edit = setRowsType(layout, objects, [{ group: 'columns', id: 'C10' }, { group: 'columns', id: 'C2' }, { group: 'beams', id: 'B1' }], 'C500');
		assert.ok(edit.ok);
		assert.deepStrictEqual({
			types: memberRows(edit.layout).map(r => `${r.id}:${r.type}`),
			changed: edit.changed,
			skipped: edit.skipped,
			none: setRowsType(layout, objects, [{ group: 'beams', id: 'B1' }], 'C500').ok,
		}, {
			types: ['C10:C500', 'C2:C500', 'B1:B300', 'B2:B300', 'S1:S150', 'F1:F1500'],
			changed: 2,
			skipped: ['B1'],
			none: false,
		});
	});

	test('type edits on a typical floor repeat on its family', () => {
		const typical = {
			...layout,
			stories: [...layout.stories.slice(0, 2), { ...layout.stories[2], similarTo: 'L1' }],
			columns: [], slabs: [], footings: [],
		};
		const edit = setRowsType(typical, objects, [{ group: 'beams', id: 'B1' }], 'B350');
		assert.ok(edit.ok);
		assert.deepStrictEqual(memberRows(edit.layout).map(r => `${r.id}:${r.story}:${r.type}`), ['B1:L1:B350', 'B2:L2:B350']);
	});

	test('type edits on two stories of one family all apply on every story of it', () => {
		const stories = [...layout.stories, { id: 'L3', name: 'Level 3', elevation: 9600 }].map(s => s.id === 'L2' || s.id === 'L3' ? { ...s, similarTo: 'L1' } : s);
		const below: { [story: string]: string } = { L1: 'BASE', L2: 'L1', L3: 'L2' };
		let n = 0;
		const columns = ['L1', 'L2', 'L3'].flatMap(top => ['A', 'B'].map(x => ({ id: `C${++n}`, type: 'C400', at: { x, y: '1' }, base: below[top], top, rotation: 0 })));
		const typical = { ...layout, stories, columns, beams: [], slabs: [], footings: [] };
		// C1 is A-1 on L1, C4 is B-1 on L2.
		const edit = setRowsType(typical, objects, [{ group: 'columns', id: 'C1' }, { group: 'columns', id: 'C4' }], 'C500');
		assert.ok(edit.ok);
		assert.deepStrictEqual({ types: memberRows(edit.layout).map(r => `${r.id}:${r.type}`), changed: edit.changed, skipped: edit.skipped }, {
			types: ['C1:C500', 'C2:C500', 'C3:C500', 'C4:C500', 'C5:C500', 'C6:C500'],
			changed: 2,
			skipped: [],
		});
	});

	test('type edits on a typical floor whose stories differ are refused, as on the floor plan', () => {
		const typical = {
			...layout,
			stories: [...layout.stories.slice(0, 2), { ...layout.stories[2], similarTo: 'L1' }],
			beams: [layout.beams[0], { ...layout.beams[1], type: 'B350' }],
			columns: [], slabs: [], footings: [],
		};
		const edit = setRowsType(typical, objects, [{ group: 'beams', id: 'B1' }], 'B350');
		assert.deepStrictEqual(edit, { ok: false, error: 'The stories of this typical floor differ; copy the typical floor to them first.' });
	});

	test('footings are listed but not edited: 9 Substructure owns them', () => {
		const typeEdit = setRowsType(layout, objects, [{ group: 'footings', id: 'F1' }], 'PC4');
		const storyEdit = setRowsStory(layout, [{ group: 'footings', id: 'F1' }], 'L1');
		const mixed = setRowsType(layout, objects, [{ group: 'footings', id: 'F1' }, { group: 'columns', id: 'C2' }], 'C500');
		assert.deepStrictEqual({
			typeEdit,
			storyEdit,
			mixed: mixed.ok ? [mixed.changed, mixed.skipped] : mixed.error,
		}, {
			typeEdit: { ok: false, error: 'Footings are placed and edited in 9 Substructure.' },
			storyEdit: { ok: false, error: 'Footings are placed and edited in 9 Substructure.' },
			mixed: [1, ['F1']],
		});
	});

	test('story edits refuse a column whose new span overlaps another at the same place', () => {
		const stacked = {
			...layout,
			columns: [
				{ id: 'C1', type: 'C400', at: { x: 'A', y: '1' }, base: 'BASE', top: 'L2', rotation: 0 },
				{ id: 'C2', type: 'C400', at: { x: 'A', y: '1' }, base: 'L2', top: 'L3', rotation: 0 },
				{ id: 'C3', type: 'C400', at: { x: 'B', y: '1' }, base: 'BASE', top: 'L1', rotation: 0 },
				{ id: 'C4', type: 'C400', at: { x: 'B', y: '1' }, base: 'L1', top: 'L3', rotation: 0 },
			],
			stories: [...layout.stories, { id: 'L3', name: 'Level 3', elevation: 9600 }],
		};
		// C2 down to L1 (BASE–L1) would stand inside C1 (BASE–L2); C4 down to L2 (BASE–L2) would overlap C3 (BASE–L1).
		assert.deepStrictEqual([setRowsStory(stacked, [{ group: 'columns', id: 'C2' }], 'L1').ok, setRowsStory(stacked, [{ group: 'columns', id: 'C4' }], 'L2').ok], [false, false]);
	});

	test('story edits move members; columns keep their span; clashes and the base are refused', () => {
		const moved = setRowsStory(layout, [{ group: 'columns', id: 'C10' }, { group: 'slabs', id: 'S1' }], 'L2');
		assert.ok(moved.ok);
		assert.deepStrictEqual(memberRows(moved.layout).filter(r => r.id === 'C10' || r.id === 'S1').map(r => `${r.id}:${r.base ?? ''}:${r.story}`), ['C10:L1:L2', 'S1::L2']);
		const clash = setRowsStory(layout, [{ group: 'beams', id: 'B1' }], 'L2');
		const tooLow = setRowsStory(layout, [{ group: 'columns', id: 'C2' }], 'L1');
		assert.deepStrictEqual([clash.ok, tooLow.ok, setRowsStory(layout, [{ group: 'beams', id: 'B1' }], 'NOPE').ok], [false, false, false]);
	});

	test('CSV and shift-click ranges', () => {
		const rows = memberRows(layout).slice(0, 3);
		assert.deepStrictEqual({
			csv: membersCsv(rows, id => id === 'L1' ? 'Level 1' : id).split('\r\n'),
			range: rowRange(rows, rowKey(rows[2]), rowKey(rows[0])),
			noAnchor: rowRange(rows, undefined, rowKey(rows[1])),
		}, {
			csv: [
				'ID,Kind,Object Type,Section (mm),Length (mm),Story,Base,Location',
				'C10,Column,C400,,3200,Level 1,BASE,"A-1 (+150, 0)"',
				'C2,Column,C400,,6400,L2,BASE,B-1',
				'B1,Beam,B300,,6000,Level 1,,A-1 → B-1',
				'',
			],
			range: ['columns/C10', 'columns/C2', 'beams/B1'],
			noAnchor: ['columns/C2'],
		});
	});
});
