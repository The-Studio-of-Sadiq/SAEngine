/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	addLineLoads, addPointLoad, defaultWallHeight, emptyLoads, IMemberLoads, isPoint, LOAD_LAYERS, loadRows, loadsDrawing, loadsOnStory, loadsText, loadValue, parseArchitectureLoads, parseLoads,
	removeLoads, updateLoad, wallLineLoad, wallWeight,
} from '../../browser/floorPlanLoads.js';

suite('SAEngine - Floor plan loads', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	type Json = { [key: string]: unknown };
	const A1 = { x: 'A', y: '1' }, B1 = { x: 'B', y: '1' }, B2 = { x: 'B', y: '2' };
	/** Base and three levels 3.2 m apart; L2 and L3 repeat L1 when `typical`. A 6 m beam A1-B1 and a 5 m beam B1-B2 on each level. */
	const layout = (typical = true): Json => ({
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: ['BASE', 'L1', 'L2', 'L3'].map((id, i) => ({ id, name: id === 'BASE' ? 'Base' : `Level ${i}`, elevation: 3200 * i, ...(typical && i > 1 ? { similarTo: 'L1' } : {}) })),
		columns: [1, 2, 3].map(k => ({ id: `C${k}`, type: 'C400', at: A1, base: k === 1 ? 'BASE' : `L${k - 1}`, top: `L${k}` })),
		beams: [1, 2, 3].flatMap(k => [
			{ id: `B${k}1`, type: 'B300', story: `L${k}`, start: A1, end: B1 },
			{ id: `B${k}2`, type: 'B300', story: `L${k}`, start: B2, end: B1 },
		]),
		walls: [], slabs: [], footings: [],
	});
	const objects = { objects: [{ id: 'B300', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 500 } }] };

	test('a wall type × height in kN/m, by hand (BNBC Table 6.2.2)', () => {
		const [bw125, bw250] = emptyLoads().wallTypes;
		assert.deepStrictEqual({
			bw125: wallWeight(bw125).toFixed(4),
			bw250: wallWeight(bw250).toFixed(4),
			// (19.1 x 0.25 + 23 x 2 x 0.0125) kN/m² x 2.7 m x 0.8
			wall: wallLineLoad(bw250, 2700, 20).toFixed(4),
			// The story height above (3200) less the beam's depth (500); a parapet on the roof.
			heights: [defaultWallHeight(layout(), objects, 'B11'), defaultWallHeight(layout(), objects, 'B31')],
		}, { bw125: '2.9625', bw250: '5.3500', wall: '11.5560', heights: [2700, 1000] });
	});

	test('line loads on selected beams follow the typical floor, stored on its master', () => {
		const plan = layout();
		const edit = addLineLoads(emptyLoads(), plan, ['B21', 'B22'], { case: 'SD', wall: { type: 'BW250', height: 2700 } });
		const only = addLineLoads(edit.loads, plan, ['B32'], { case: 'D', value: 4, thisStoryOnly: true });
		const loads = only.loads;
		assert.deepStrictEqual({
			ids: [...edit.ids, ...only.ids],
			stored: loads.loads.map(l => `${l.id}:${l.story}:${l.member}`),
			L2: loadsOnStory(loads, plan, 'L2').map(s => `${s.load.id}@${s.member}${s.inherited ? ' (typical)' : ''}`),
			L3: loadsOnStory(loads, plan, 'L3').map(s => `${s.load.id}@${s.member}`),
			notTypical: loadsOnStory(loads, layout(false), 'L2').map(s => s.load.id),
			rows: loadRows(loads, plan).map(r => [r.id, r.storyName, r.stories, r.member, r.kind, r.case, r.valueLabel, r.source, r.total?.toFixed(2)]),
		}, {
			ids: ['LL1', 'LL2', 'LL3'],
			stored: ['LL1:L1:B11', 'LL2:L1:B12', 'LL3:L3:B32'],
			L2: ['LL1@B21 (typical)', 'LL2@B22 (typical)'],
			L3: ['LL1@B31', 'LL2@B32', 'LL3@B32'],
			notTypical: [],
			rows: [
				['LL1', 'Level 1', 3, 'B11', 'line', 'SD', '14.44 kN/m', 'BW250 × 2.7 m', (5.35 * 2.7 * 6 * 3).toFixed(2)],
				['LL2', 'Level 1', 3, 'B12', 'line', 'SD', '14.44 kN/m', 'BW250 × 2.7 m', (5.35 * 2.7 * 5 * 3).toFixed(2)],
				['LL3', 'Level 3', 1, 'B32', 'line', 'D', '4 kN/m', 'explicit', '20.00'],
			],
		});
	});

	test('point loads on a beam and at a column joint; bad input refused', () => {
		const plan = layout(false);
		const onBeam = addPointLoad(emptyLoads(), plan, { group: 'beams', id: 'B11' }, 'L1', { case: 'SD', value: 30, distance: 2000 });
		const atJoint = addPointLoad(onBeam.loads, plan, { group: 'columns', id: 'C2' }, 'L2', { case: 'L', value: 12 });
		assert.deepStrictEqual({
			loads: atJoint.loads.loads,
			refused: [
				addPointLoad(emptyLoads(), plan, { group: 'columns', id: 'C2' }, 'L3', { case: 'SD', value: 1 }).problems.length,
				addPointLoad(emptyLoads(), plan, { group: 'slabs', id: 'S1' }, 'L1', { case: 'SD', value: 1 }).problems.length,
				addLineLoads(emptyLoads(), plan, ['B11'], { case: 'SD' }).problems.length,
				addLineLoads(emptyLoads(), plan, ['C1'], { case: 'SD', value: 2 }).problems.length,
			],
		}, {
			loads: [
				{ id: 'PL1', kind: 'point', story: 'L1', member: 'B11', case: 'SD', value: 30, distance: 2000 },
				{ id: 'PL2', kind: 'point', story: 'L2', member: 'C2', case: 'L', value: 12 },
			],
			refused: [1, 1, 1, 1],
		});
	});

	test('editing, deleting and reading back the file', () => {
		const plan = layout();
		let loads: IMemberLoads = addLineLoads(emptyLoads(), plan, ['B11'], { case: 'SD', wall: { type: 'BW125', height: 3000, openings: 10 } }).loads;
		loads = addLineLoads(loads, plan, ['B12'], { case: 'SD', value: 3 }).loads;
		loads = updateLoad(updateLoad(loads, 'LL1', { height: 2000, case: 'D' }), 'LL2', { value: 5 });
		const read = parseLoads(loadsText(loads));
		assert.deepStrictEqual({
			values: read.loads.loads.map(l => loadValue(l, read.loads)?.toFixed(4)),
			cases: read.loads.loads.map(l => l.case),
			afterDelete: removeLoads(read.loads, ['LL1']).loads.map(l => l.id),
			missing: parseLoads(undefined).loads.loads.length,
			broken: !!parseLoads('{').problem,
		}, {
			values: [(2.9625 * 2 * 0.9).toFixed(4), '5.0000'],
			cases: ['D', 'SD'],
			afterDelete: ['LL2'],
			missing: 0,
			broken: true,
		});
	});

	test('the plan shows each load beside its beam with its value', () => {
		const plan = layout();
		let loads = addLineLoads(emptyLoads(), plan, ['B11'], { case: 'SD', value: 10 }).loads;
		loads = addLineLoads(loads, plan, ['B11'], { case: 'SD', value: 2 }).loads;
		loads = addPointLoad(loads, plan, { group: 'beams', id: 'B11' }, 'L1', { case: 'SD', value: 30, distance: 3000 }).loads;
		const entities = loadsDrawing(loads, plan, 'L2');
		const texts = entities.filter(e => e.kind === 'text').map(e => e.kind === 'text' ? e.text : '');
		const lines = entities.filter(e => e.kind === 'line' && e.layer === LOAD_LAYERS.loads);
		// Beam A1-B1 runs along +x: its label is above it, so its line loads are drawn below (-y), the second further out (N-F9).
		const offsets = lines.filter(e => e.kind === 'line' && e.start[1] === e.end[1]).map(e => e.kind === 'line' ? Math.round(e.start[1]) : 0);
		// The point load's symbol is on the label's side (above), beyond the label.
		const circles = entities.filter(e => e.kind === 'circle').map(e => e.kind === 'circle' ? e.center.map(Math.round) : []);
		assert.deepStrictEqual({ texts, offsets, circles }, {
			texts: ['10 kN/m', '2 kN/m', '30 kN'],
			offsets: [-450, -850],
			circles: [[3000, 610]],
		});
	});

	test('a point load on a reversed beam of a typical floor keeps its place', () => {
		const plan = layout();
		// On L2 the beam at B1-B2 runs the other way from the master's (L1: B2 to B1).
		(plan.beams as Json[])[3] = { id: 'B22', type: 'B300', story: 'L2', start: B1, end: B2 };
		const loads = addPointLoad(emptyLoads(), plan, { group: 'beams', id: 'B22' }, 'L2', { case: 'SD', value: 30, distance: 1000 }).loads;
		const at = (story: string) => loadsDrawing(loads, plan, story).filter(e => e.kind === 'line').map(e => e.kind === 'line' ? e.end.map(Math.round) : [])[0];
		assert.deepStrictEqual({ stored: loads.loads, L1: at('L1'), L2: at('L2') }, {
			// 1000 mm from B1 is 4000 mm from B2, the master beam's start.
			stored: [{ id: 'PL1', kind: 'point', story: 'L1', member: 'B12', case: 'SD', value: 30, distance: 4000 }],
			L1: [6000, 1000],
			L2: [6000, 1000],
		});
	});

	test('the default wall height stops at the soffit of the beam above', () => {
		const plan = layout(false);
		(plan.beams as Json[])[2] = { id: 'B21', type: 'B600', story: 'L2', start: A1, end: B1 };
		const deeper = { objects: [...objects.objects, { id: 'B600', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 600 } }] };
		// Under B21 (600 deep) on L2: 3200 - 600; under B22 (500 deep): 3200 - 500.
		assert.deepStrictEqual([defaultWallHeight(plan, deeper, 'B11'), defaultWallHeight(plan, deeper, 'B12')], [2600, 2700]);
	});

	test('a wall worked out per beam and story follows typical floors of different heights (N-F2)', () => {
		// L2 is 3.6 m high (L3 at 10.0 m, the roof); B21 (on L2, where L1's walls stop) is 600 deep.
		const plan = layout();
		(plan.stories as Json[])[3] = { id: 'L3', name: 'Level 3', elevation: 10000, similarTo: 'L1' };
		(plan.beams as Json[])[2] = { id: 'B21', type: 'B600', story: 'L2', start: A1, end: B1 };
		const deeper = { objects: [...objects.objects, { id: 'B600', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 600 } }] };
		const edit = addLineLoads(emptyLoads(), plan, ['B21', 'B22'], { case: 'SD', wall: { type: 'BW250', height: 1, openings: 20, auto: true } }, deeper);
		const fixed = addLineLoads(emptyLoads(), plan, ['B11'], { case: 'SD', wall: { type: 'BW250', height: 2700 } }, deeper).loads;
		const skip = addLineLoads(emptyLoads(), plan, ['B11'], { case: 'SD', wall: { type: 'BW250', height: 1, auto: true, skipRoof: true } }, deeper).loads;
		const text = (loads: IMemberLoads, story: string) => loadsDrawing(loads, plan, story, deeper).filter(e => e.kind === 'text').map(e => e.kind === 'text' ? e.text : '');
		const rows = loadRows(edit.loads, plan, deeper);
		assert.deepStrictEqual({
			// Each beam's own height on its master (L1), not the first beam's: under B21 (600) and B22 (500).
			stored: edit.loads.loads.map(l => !isPoint(l) && l.wall ? `${l.member} ${l.wall.height}` : ''),
			L1: text(edit.loads, 'L1'),
			L2: text(edit.loads, 'L2'),
			roof: text(edit.loads, 'L3'),
			typedEverywhere: [text(fixed, 'L2'), text(fixed, 'L3')],
			skipped: text(skip, 'L3'),
			heights: rows[0].heights,
			total: rows[0].total?.toFixed(2),
		}, {
			stored: ['B11 2600', 'B12 2700'],
			// 5.35 kN/m² × h × 0.8: 2.6 m and 2.7 m on L1; 3.6 m - 0.5 m on L2; a 1 m parapet with no openings on the roof.
			L1: [(5.35 * 2.6 * 0.8).toFixed(2), (5.35 * 2.7 * 0.8).toFixed(2)].map(v => `${Number(v)} kN/m`),
			L2: [(5.35 * 3.1 * 0.8).toFixed(2), (5.35 * 3.1 * 0.8).toFixed(2)].map(v => `${Number(v)} kN/m`),
			roof: ['5.35 kN/m', '5.35 kN/m'],
			typedEverywhere: [['14.44 kN/m'], ['14.44 kN/m']],
			skipped: [],
			heights: '2.6 m on Level 1, 3.1 m on Level 2, 1 m parapet on Level 3',
			total: ((5.35 * 2.6 * 0.8 + 5.35 * 3.1 * 0.8 + 5.35) * 6).toFixed(2),
		});
		// A typed height turns it off; "auto" turns it on again.
		const typed = updateLoad(edit.loads, 'LL1', { height: 2500 });
		assert.deepStrictEqual([(typed.loads[0] as { wall?: object }).wall, (updateLoad(typed, 'LL1', { auto: true }).loads[0] as { wall?: object }).wall],
			[{ type: 'BW250', height: 2500, openings: 20 }, { type: 'BW250', height: 2500, openings: 20, auto: true }]);
		assert.strictEqual(parseLoads(loadsText(edit.loads)).problem, undefined);
	});

	test('a loads file that does not read fully is reported, and its entries are not dropped silently', () => {
		const good = { id: 'LL1', story: 'L1', member: 'B11', value: 3 };
		const parsed = (loads: unknown[]) => parseLoads(JSON.stringify({ schema: 'saengine.memberLoads/1', loads }));
		assert.deepStrictEqual({
			ok: parsed([good]).problem,
			missingId: !!parsed([good, { story: 'L1', member: 'B12', value: 3 }]).problem,
			badValue: !!parsed([{ ...good, value: '3' }]).problem,
			badCase: !!parsed([{ ...good, case: 'W' }]).problem,
			wallAndValue: !!parsed([{ ...good, wall: { type: 'BW250', height: 2700 } }]).problem,
			notList: !!parseLoads('{"loads": {}}').problem,
			trailingComma: !!parseLoads('{"loads": [],}').problem,
		}, { ok: undefined, missingId: true, badValue: true, badCase: true, wallAndValue: true, notList: true, trailingComma: true });
	});

	test('reads the architecture\'s loads kept with the last derivation', () => {
		const kept = JSON.stringify({
			key: 'v|d', notes: [], summary: {
				weight_kN: 1, architectureLoads: {
					mode: 'architecture', walledStories: ['L1'],
					walls: [{ wall: 'W1', story: 'L1', type: 'B250', on: 'beam', member: 'B11', length_m: 6, height_m: 3, openings_m2: 2.1, load_kNm: 14.178, total_kN: 85.065 }],
					rooms: [{ room: 'R1', name: 'Office', story: 'L1', area_m2: 20, use: 'office', live_kNm2: 2.4 }],
				},
			},
		});
		const loads = parseArchitectureLoads(kept, true);
		assert.deepStrictEqual({
			walls: loads?.walls.map(w => `${w.wall} ${w.on} ${w.member} ${w.load_kNm}`),
			rooms: loads?.rooms.map(r => `${r.room} ${r.live_kNm2}`),
			stories: loads?.walledStories,
			stale: loads?.stale,
			none: parseArchitectureLoads(JSON.stringify({ summary: {} })),
			bad: parseArchitectureLoads('{'),
		}, { walls: ['W1 beam B11 14.178'], rooms: ['R1 2.4'], stories: ['L1'], stale: true, none: undefined, bad: undefined });
	});
});
