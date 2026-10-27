/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { copyStory, familyNote, familyOf, inSync, masterOf, onStory as ownStory, placedEdit, placeKey, repeatFamily, repeatOnFamilies, setSimilar, storyBelow } from '../../browser/floorPlanTypical.js';

suite('SAEngine - Floor plan typical floors', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	type Json = { [key: string]: unknown };
	const A1 = { x: 'A', y: '1' }, B1 = { x: 'B', y: '1' }, B2 = { x: 'B', y: '2' }, A2 = { x: 'A', y: '2' };
	const plan = (stories: Json[], members: Partial<Record<'columns' | 'beams' | 'walls' | 'slabs' | 'footings', Json[]>> = {}) => ({
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories,
		columns: [], beams: [], walls: [], slabs: [], footings: [],
		...members,
	});
	const stories = (similar: { [id: string]: string } = {}) => ['BASE', 'L1', 'L2', 'L3', 'L4', 'L5'].map((id, i) => ({
		id, name: id === 'BASE' ? 'Base' : `Level ${i}`, elevation: 3200 * i, ...(similar[id] ? { similarTo: similar[id] } : {}),
	}));
	/** A typical bay on `story`: four columns, a beam and a slab. */
	const bay = (story: string, below: string, n: number) => ({
		columns: [A1, B1, B2, A2].map((at, i) => ({ id: `C${n + i}`, type: 'C500', at, base: below, top: story, rotation: 0 })),
		beams: [{ id: `B${n}`, type: 'B300', story, start: A1, end: B1 }],
		slabs: [{ id: `S${n}`, type: 'S150', story, boundary: [A1, B1, B2, A2] }],
	});
	const onStory = (layout: Json, story: string) => (['columns', 'beams', 'slabs'] as const).flatMap(group =>
		(layout[group] as Json[]).filter(m => m.story === story || m.top === story).map(m => `${m.id}:${m.type}`));

	test('families: a master and the stories similar to it, broken references ignored', () => {
		const layout = plan([...stories({ L3: 'L2', L4: 'L2' }), { id: 'X', name: 'X', elevation: 99999, similarTo: 'NOPE' }]);
		assert.deepStrictEqual({
			family: familyOf(layout, 'L4'),
			ofMaster: familyOf(layout, 'L2'),
			alone: familyOf(layout, 'L5'),
			master: masterOf(layout, 'L3'),
			broken: masterOf(layout, 'X'),
			notes: [familyNote(layout, 'L2'), familyNote(layout, 'L3'), familyNote(layout, 'L5')],
		}, {
			family: ['L2', 'L3', 'L4'],
			ofMaster: ['L2', 'L3', 'L4'],
			alone: ['L5'],
			master: 'L2',
			broken: undefined,
			notes: [{ similar: 2 }, { master: 'L2', similar: 0 }, { similar: 0 }],
		});
	});

	test('setSimilar copies the typical floor up, with the columns rising from each story below', () => {
		const typical = bay('L2', 'L1', 1);
		const layout = setSimilar(plan(stories(), typical), 'L2', ['L3', 'L4']);
		const columns = (layout.columns as Json[]).filter(c => c.top === 'L4');
		assert.deepStrictEqual({
			similarTo: (layout.stories as Json[]).map(s => s.similarTo ?? null),
			L4: onStory(layout, 'L4'),
			base: columns.map(c => c.base),
			total: (layout.columns as Json[]).length,
			inSync: inSync(layout, ['L2', 'L3', 'L4']),
		}, {
			similarTo: [null, null, null, 'L2', 'L2', null],
			// Copies keep the master's labels, with their story: C1 on L4 is C1-L4.
			L4: ['C1-L4:C500', 'C2-L4:C500', 'C3-L4:C500', 'C4-L4:C500', 'B1-L4:B300', 'S1-L4:S150'],
			base: ['L3', 'L3', 'L3', 'L3'],
			total: 12,
			inSync: true,
		});
	});

	test('a copy keeps the ids of the members already at the same place and drops the rest', () => {
		const L2 = bay('L2', 'L1', 1);
		const L3 = {
			columns: [{ id: 'C40', type: 'C400', at: A1, base: 'L2', top: 'L3', rotation: 90 }],
			beams: [{ id: 'B40', type: 'B300', story: 'L3', start: A2, end: B2 }],
			slabs: [],
		};
		const layout = copyStory(plan(stories(), { columns: [...L2.columns, ...L3.columns], beams: [...L2.beams, ...L3.beams], slabs: L2.slabs }), 'L2', ['L3']);
		const L3columns = (layout.columns as Json[]).filter(c => c.top === 'L3');
		assert.deepStrictEqual({
			L3: onStory(layout, 'L3'),
			rotation: L3columns.find(c => c.id === 'C40')?.rotation,
			L2: onStory(layout, 'L2'),
		}, {
			L3: ['C40:C500', 'C2-L3:C500', 'C3-L3:C500', 'C4-L3:C500', 'B1-L3:B300', 'S1-L3:S150'],
			rotation: 0,
			L2: ['C1:C500', 'C2:C500', 'C3:C500', 'C4:C500', 'B1:B300', 'S1:S150'],
		});
	});

	test('columns over several stories and footings are left alone; a family edit shows in inSync', () => {
		const tall = { id: 'C99', type: 'C500', at: A1, base: 'BASE', top: 'L3', rotation: 0 };
		const footing = { id: 'F1', type: 'F1', story: 'BASE', at: A1, rotation: 0 };
		const layout = setSimilar(plan(stories(), { ...bay('L2', 'L1', 1), columns: [...bay('L2', 'L1', 1).columns, tall], footings: [footing] }), 'L2', ['L3']);
		const edited = { ...layout, beams: [...(layout.beams as Json[]), { id: 'B9', type: 'B300', story: 'L3', start: B1, end: B2 }] };
		assert.deepStrictEqual({
			tall: (layout.columns as Json[]).find(c => c.id === 'C99'),
			footings: layout.footings,
			synced: inSync(layout, ['L2', 'L3']),
			afterEdit: inSync(edited, ['L2', 'L3']),
			repaired: inSync(copyStory(edited, 'L3', ['L2', 'L3']), ['L2', 'L3']),
		}, {
			tall,
			footings: [footing],
			synced: true,
			afterEdit: false,
			repaired: true,
		});
	});

	test('unpicking a story makes it independent and keeps its plan; stories of a picked master follow', () => {
		const typical = setSimilar(plan(stories(), bay('L2', 'L1', 1)), 'L2', ['L3', 'L4']);
		const fewer = setSimilar(typical, 'L2', ['L3']);
		const merged = setSimilar(typical, 'L5', ['L2']);
		assert.deepStrictEqual({
			fewer: (fewer.stories as Json[]).map(s => s.similarTo ?? null),
			kept: onStory(fewer, 'L4').length,
			merged: (merged.stories as Json[]).map(s => s.similarTo ?? null),
			emptied: onStory(merged, 'L3'),
		}, {
			fewer: [null, null, null, 'L2', null, null],
			kept: 6,
			merged: [null, null, 'L5', 'L5', 'L5', null],
			emptied: [],
		});
	});

	test('helpers: the story below, the story and place of a member, footings included', () => {
		const layout = plan(stories(), { ...bay('L1', 'BASE', 1), footings: [{ id: 'F1', type: 'F1500', story: 'BASE', at: { ...A1, dx: 100 } }] });
		const column = (layout.columns as Json[])[0];
		const footing = (layout.footings as Json[])[0];
		assert.deepStrictEqual({
			below: [storyBelow(layout, 'L1'), storyBelow(layout, 'BASE')],
			onStory: [ownStory(layout, 'columns', column, 'L1'), ownStory(layout, 'columns', column, 'L2'), ownStory(layout, 'footings', footing, 'BASE')],
			keys: [placeKey('columns', column), placeKey('footings', footing), placeKey('beams', (layout.beams as Json[])[0])],
			edits: [placedEdit(layout, 'columns', column), placedEdit(layout, 'footings', footing)],
		}, {
			below: ['BASE', undefined],
			onStory: [true, false, true],
			keys: ['A/1/0/0', 'A/1/100/0', 'A/1/0/0 B/1/0/0'],
			edits: [{ group: 'columns', key: 'A/1/0/0', story: 'L1' }, undefined],
		});
	});

	test('one rule for edits on typical floors: repeat on an alike family, refuse when its stories differ', () => {
		const alike = plan(stories({ L3: 'L2' }), { beams: [...bay('L2', 'L1', 1).beams, ...bay('L3', 'L2', 5).beams] });
		const differ = plan(stories({ L3: 'L2' }), { beams: [...bay('L2', 'L1', 1).beams, { ...bay('L3', 'L2', 5).beams[0], type: 'B350' }] });
		const edited = (layout: Json) => ({ ...layout, beams: (layout.beams as Json[]).map(b => b.id === 'B1' ? { ...b, type: 'B400' } : b) });
		const edit = placedEdit(alike, 'beams', (alike.beams as Json[])[0])!;
		const repeated = repeatOnFamilies(alike, edited(alike), [edit], { type: 'B400' });
		assert.deepStrictEqual({
			families: [repeatFamily(alike, 'L3'), repeatFamily(differ, 'L3'), repeatFamily(alike, 'L1')],
			repeated: (repeated!.beams as Json[]).map(b => `${b.id}:${b.type}`),
			refused: repeatOnFamilies(differ, edited(differ), [edit], { type: 'B400' }),
		}, {
			families: [['L2', 'L3'], undefined, ['L1']],
			repeated: ['B1:B400', 'B5:B400'],
			refused: undefined,
		});
	});
});
