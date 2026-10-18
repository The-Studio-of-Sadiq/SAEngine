/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IMep, newMep, parseMep, readMepContext, readSleeveSuggestions, serializeMep } from '../../browser/mepDocument.js';
import { renderPlan } from '../../browser/mepPlan.js';
import {
	checkPlumbing, ensurePlumbing, fixtureTotals, hasPlumbing, IPlumbing, mergeSizedTanks, newRiser, newRoofDrain, newTank, plumbingOf, plumbingSummary, plumbingSummaryFile, readOccupancies,
	readPlumbingReport, readSizedTanks, riserOnStory, STATIC_OCCUPANCIES, storyRow, tankCapacity, tankOutline, tankStory,
} from '../../browser/plumbingDocument.js';
import { plumbingExtent, renderPlumbing } from '../../browser/plumbingPlan.js';
import { renderPlumbingReport } from '../../browser/plumbingResults.js';

/*
 * Synthetic data only: a one-bay frame on a 6 m x 5 m grid with three stories (base, L1 at
 * 3 m, roof at 6 m) and a slab on L1 and the roof. Expected values are worked by hand.
 */

const BIM = JSON.stringify({
	schema: 'saengine.bim/2',
	stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3000 }, { id: 'ROOF', name: 'Roof', elevation: 6000 }],
	elements: [
		{ id: 'C1', kind: 'column', type: 'C400', position: [0, 0], bottom: 0, top: 6000 },
		{ id: 'C2', kind: 'column', type: 'C400', position: [6000, 5000], bottom: 0, top: 6000 },
		{ id: 'S1', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 3000 },
		{ id: 'S2', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 6000 },
	],
});
const OBJECTS = JSON.stringify({ objects: [{ id: 'C400', kind: 'column', profile: { shape: 'rectangle', xDim: 400, yDim: 400 } }, { id: 'S150', kind: 'slab', thickness: 150 }] });
const MATERIALS = JSON.stringify({ materials: [{ id: 'M25', category: 'concrete', mechanical: { density: 2400 } }] });
const CONTEXT = readMepContext({ bim: BIM, objects: OBJECTS, materials: MATERIALS });

/** Two storeys of flats, a CW riser and a soil stack, an overhead tank on the roof, a reservoir and a septic tank. */
function setUp(): IMep {
	const document = newMep();
	const plumbing = ensurePlumbing(document);
	plumbing.supply = { source: 'mains', mainsHead: 5, pumpHours: 8 };
	plumbing.stories.push(
		{ story: 'L1', occupancy: 'residentialFlat', population: 10, fixtures: { wc: 4, basin: 4, shower: 2, kitchenSink: 2 } },
		{ story: 'ROOF', occupancy: 'residentialFlat', population: 8, fixtures: { wc: 3, basin: 3, shower: 2, kitchenSink: 1, other: [{ name: 'Tap', count: 2 }] } },
	);
	plumbing.risers.push(newRiser(document, CONTEXT, 'coldWater', 'L1'));
	plumbing.risers.push(newRiser(document, CONTEXT, 'soil', 'L1'));
	plumbing.tanks.push(newTank(document, CONTEXT, 'overhead', 'ROOF'));
	plumbing.tanks.push(newTank(document, CONTEXT, 'underground', undefined));
	plumbing.tanks.push(newTank(document, CONTEXT, 'septic', undefined));
	return document;
}

suite('SAEngine MEP plumbing', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('an old file stays as it was; the plumbing is created on the first plumbing edit', () => {
		const text = serializeMep(newMep());
		const parsed = parseMep(text);
		const document = parsed.kind === 'document' ? parsed.document : newMep();
		assert.deepStrictEqual({ plumbing: plumbingOf(document), has: hasPlumbing(document), text: serializeMep(document) === text }, { plumbing: undefined, has: false, text: true });
		ensurePlumbing(document);
		assert.deepStrictEqual(document.plumbing, { supply: {}, stories: [], risers: [], tanks: [], roof: { drains: [] } });
		// A partial section is filled in, its unknown fields kept.
		const partial = parseMep(JSON.stringify({ schema: 'saengine.mep/1', plumbing: { risers: [{ id: 'R1' }, 'x'], extra: 1 } }));
		const read = partial.kind === 'document' ? plumbingOf(partial.document) : undefined;
		assert.deepStrictEqual(read, { risers: [{ id: 'R1' }], extra: 1, supply: {}, stories: [], tanks: [], roof: { drains: [] } });
	});

	test('places new risers, tanks and drains', () => {
		const document = setUp();
		const plumbing = plumbingOf(document)!;
		// Middle of the 6 x 5 m floor (3.0, 2.5 m); the second riser 600 mm along x. From the base to the roof.
		// Ground tanks beside the building on the left, 1 m clear: the reservoir (4.0 x 3.0 m inside, 200 mm walls)
		// centred at x = -1000 - 2200 = -3200, y = 5000 - 1700 = 3300; the septic tank (3.6 x 1.5 m) below it 1 m clear:
		// x = -1000 - 2000 = -3000, y = (3300 - 1700 - 1000) - 950 = -350.
		assert.deepStrictEqual({
			risers: plumbing.risers.map(r => [r.id, r.system, r.x, r.y, r.fromStory, r.toStory]),
			tanks: plumbing.tanks.map(t => [t.id, t.kind, t.story, t.x, t.y]),
			drain: newRoofDrain(document, CONTEXT, 'ROOF'),
		}, {
			risers: [['R1', 'coldWater', 3000, 2500, 'BASE', 'ROOF'], ['ST1', 'soil', 3600, 2500, 'BASE', 'ROOF']],
			tanks: [['T1', 'overhead', 'ROOF', 3000, 2500], ['T2', 'underground', null, -3200, 3300], ['ST-T1', 'septic', null, -3000, -350]],
			drain: { id: 'RD1', story: 'ROOF', x: 500, y: 500 },
		});
		// A soak well goes below the septic tank: its bottom is at -350 - 950 = -1300, so 1 m below and r = 600 + 250.
		const well = newTank(document, CONTEXT, 'soakWell', undefined);
		assert.deepStrictEqual([well.x, well.y], [-1850, -3150]);
	});

	test('capacities, totals, outlines and the stories things are drawn on', () => {
		const document = setUp();
		const plumbing = plumbingOf(document)!;
		const [overhead, reservoir] = plumbing.tanks;
		// 3.0 x 2.5 x 1.5 = 11.25 m³; 4.0 x 3.0 x 2.0 = 24 m³; a soak well of 1.2 m to 3 m: pi 0.36 x 3 = 3.393 m³.
		assert.deepStrictEqual({
			capacities: [tankCapacity(overhead), tankCapacity(reservoir), Number(tankCapacity({ id: 'W', kind: 'soakWell', story: null, x: 0, y: 0, diameter: 1200, waterDepth: 3000 })!.toFixed(3))],
			outline: tankOutline(overhead),
			totals: fixtureTotals(plumbing),
			stories: [tankStory(overhead, CONTEXT), tankStory(reservoir, CONTEXT)],
			riserOn: CONTEXT.stories.map(s => riserOnStory({ ...plumbing.risers[0], fromStory: 'L1' }, CONTEXT, s.id)),
		}, {
			capacities: [11.25, 24, 3.393],
			outline: [[1350, 1100], [4650, 1100], [4650, 3900], [1350, 3900]],
			totals: { population: 18, other: 2, wc: 7, urinal: 0, basin: 7, shower: 4, bathtub: 0, kitchenSink: 3, floorDrain: 0, washingMachine: 0, bidet: 0 },
			stories: ['ROOF', 'BASE'],
			riserOn: [false, true, true],
		});
	});

	test('checks the contract rules', () => {
		const document = setUp();
		const plumbing: IPlumbing = plumbingOf(document)!;
		assert.deepStrictEqual(checkPlumbing(document, CONTEXT), []);
		plumbing.supply.pumpHours = 30;
		plumbing.stories.push({ story: 'L1', fixtures: { wc: 1.5 } });
		plumbing.risers[1].id = 'R1';
		plumbing.risers[0].toStory = 'BASE';
		plumbing.risers[0].shaft = 'SH9';
		plumbing.tanks[0].story = null;
		plumbing.tanks[1].length = 0;
		plumbing.tanks[2].compartments = 0;
		plumbing.roof.drains.push({ id: 'RD1', story: 'NOPE', x: 0, y: 0, area: -1 });
		assert.deepStrictEqual(checkPlumbing(document, CONTEXT).map(p => p.path), [
			'plumbing.supply.pumpHours',
			'plumbing.stories.2.story',
			'plumbing.stories.2.fixtures.wc',
			'plumbing.risers.0.id',
			'plumbing.risers.0.toStory',
			'plumbing.risers.0.shaft',
			'plumbing.risers.1.id',
			'plumbing.tanks.0.story',
			'plumbing.tanks.1.length',
			'plumbing.tanks.2.compartments',
			'plumbing.roof.drains.0.story',
			'plumbing.roof.drains.0.area',
		]);
	});

	test('merges sized tanks as one edit: only changed sizes count; the position stays; new ones get unused IDs', () => {
		const document = setUp();
		const [t1, t2] = plumbingOf(document)!.tanks;
		// The backend's bare list (P1's plumbing_size_tanks): T1 repeated unchanged, T2 resized, a new rainwater tank.
		const answer = readSizedTanks([
			{ ...t1, sized: false },
			{ ...t2, x: 99, y: 99, length: 4500, sized: true },
			{ kind: 'rainwater', x: -9000, y: 0, length: 2000, width: 2000, sized: true },
			{ kind: 7 },
		])!;
		const touched = mergeSizedTanks(document, answer.tanks);
		const tanks = plumbingOf(document)!.tanks;
		assert.deepStrictEqual({
			touched: touched.map(t => t.id),
			t1: tanks[0].sized,
			t2: [tanks[1].x, tanks[1].y, tanks[1].length, tanks[1].sized],
			added: [tanks[3].id, tanks[3].kind, tanks[3].story, tanks[3].sized],
			wrapped: readSizedTanks({ tanks: [{ id: 'T9', kind: 'overhead' }], notes: ['n'] })?.notes,
			sleeves: readSleeveSuggestions([{ id: 'PS-R1-L1', host: 'S1', kind: 'sleeve', shape: 'circle', diameter: 80, position: { x: 5500, y: 4200 } }, { id: 'no host' }])?.openings.map(o => o.id),
		}, {
			touched: ['T2', 'T3'],
			t1: false,
			t2: [t2.x, t2.y, 4500, true],
			added: ['T3', 'rainwater', null, true],
			wrapped: ['n'],
			sleeves: ['PS-R1-L1'],
		});
	});

	test('reads the backend report (P1 sizing, P2 tank design, P3 hydraulics); the status line', () => {
		const document = setUp();
		const report = readPlumbingReport(REPORT)!;
		assert.deepStrictEqual({
			demand: [report.dailyDemand, report.population, report.demand.map(d => d.daily)],
			storage: [report.overheadRequired, ...report.storage.map(s => `${s.tank} ${s.required}/${s.provided} ${s.status}`)],
			risers: report.risers.map(r => `${r.id} ${r.load} ${r.loadUnit} ${r.status}`),
			leaders: report.leaders.map(l => `${l.id} ${l.area} ${l.load} ${l.status}`),
			catchments: report.catchments.map(c => [c.drain, c.area, c.leader]),
			septic: report.septic.map(s => `${s.kind} ${s.id} ${s.required}/${s.provided} ${s.status}`),
			tank: [report.tanks[0].status, report.tanks[0].capacity, report.tanks[0].reinforcement, report.tanks[0].loads],
			floors: report.floors.map(f => [f.story, f.status]),
			head: report.requiredHead,
			pump: report.pump,
			summary: plumbingSummary(document, report),
			file: plumbingSummaryFile(document, report),
			bad: readPlumbingReport('x'),
		}, {
			demand: [3240, 18, [1800, 1440]],
			storage: [1.62, 'T1 1.62/11.25 ok', 'T2 3.24/24 ok'],
			risers: ['R1 30 units ok', 'ST1 21 units fail'],
			leaders: ['RW1 30 44 ok'],
			catchments: [['RD1', 30, 75]],
			septic: ['septic ST-T1 2.88/8.1 fail', 'soakWell SW1 undefined/undefined fail'],
			tank: ['fail', 11.25, [{ location: 'Walls · horizontal · outer', bars: 'Ø10 @ 300 / Ø12 @ 300' }, { location: 'Base · X · top', bars: 'Ø10 @ 200' }], 'On its supports: 223.2 kN full, 139.3 kN empty'],
			floors: [['L1', 'ok'], ['ROOF', 'fail']],
			head: 5.6,
			pump: { flow: 0.1125, head: 15.6, power: 0.035, note: 'H = hs + hd + hf + hv' },
			// P1: ST1, septic length, soak well; P2: base; P3: residual head at the roof.
			summary: '2 storeys · 2 risers · 3 tanks · 1 floor below the minimum pressure · 5 checks fail',
			file: { risers: 2, tanks: 3, failed: 5, floorsLow: 1 },
			bad: undefined,
		});
		// Without P3, the pump comes from P1's storage (6.75 L/min = 0.1125 L/s).
		assert.deepStrictEqual(readPlumbingReport({ ...REPORT, hydraulics: undefined })?.pump, { flow: 0.1125, note: '3.24 m³ in 8 h' });
		assert.deepStrictEqual(readOccupancies({ occupancies: [{ key: 'office', label: 'Office', lpcd: 45 }, { label: 'no key' }] }), [{ key: 'office', label: 'Office', lpcd: 45, source: undefined }]);
		assert.deepStrictEqual([readOccupancies([]), STATIC_OCCUPANCIES.find(o => o.key === 'office')?.lpcd], [undefined, 45]);
	});

	test('draws the plumbing on the plan and the report page', () => {
		const document = setUp();
		storyRow(plumbingOf(document)!, 'BASE');
		const container = mainWindow.document.createElement('div');
		renderPlan(container, document, CONTEXT, {
			width: 600, height: 400, story: 'BASE', plumbing: true, extraExtent: plumbingExtent(document, CONTEXT, 'BASE'), selection: { kind: 'tank', index: 1 },
			overlay: (root, view) => renderPlumbing(root, view, document, CONTEXT, { story: 'BASE', selection: { kind: 'tank', index: 1 } }),
		});
		const attr = (selector: string, name: string) => [...container.querySelectorAll(selector)].map(e => e.getAttribute(name));
		assert.deepStrictEqual({
			risers: [...container.querySelectorAll('.plb-riser-letters')].map(e => e.textContent),
			tanks: attr('[data-tank]', 'data-tank'),
			selected: attr('.plb-tank.selected', 'data-tank'),
		}, { risers: ['CW', 'S'], tanks: ['1', '2'], selected: ['1'] });

		const page = mainWindow.document.createElement('div');
		renderPlumbingReport(page, readPlumbingReport(REPORT)!, {
			storyName: id => id,
			occupancyName: key => key,
			row: body => body.appendChild(mainWindow.document.createElement('tr')),
			tableHead: () => { },
		});
		assert.deepStrictEqual({
			sections: [...page.querySelectorAll('.mep-section-title')].map(e => e.textContent),
			bars: [...page.querySelectorAll('.plb-chart-bar')].map(e => e.getAttribute('class')),
			required: page.querySelectorAll('.plb-chart-required').length,
			cards: page.querySelectorAll('.plb-tank-card').length,
			failedRows: page.querySelectorAll('tr.failed').length,
		}, {
			sections: ['Demand and storage', 'Risers and stacks', 'Rainwater leaders', 'Septic tank and soak well', 'Checks', 'Tank design', 'Hydraulics', 'Notes', 'Method'],
			bars: ['plb-chart-bar band-ok', 'plb-chart-bar band-fail'],
			required: 2,
			cards: 1,
			// ST1, septic tank, soak well; checks: ST1, septic length, soak well; tank: base; hydraulics: roof head.
			failedRows: 8,
		});
	});
});

/**
 * A report in the backend's shape (P1 `plumbing_report`, with P2's `design_tank` as
 * `tankDesigns` and P3's `water_hydraulics` as `hydraulics`), trimmed, for the set-up above.
 * Hand values: L1 10 x 180 = 1800 L/d, roof 8 x 180 = 1440 L/d, 3240 L/d in all; overhead
 * 1/2 x 3.24 = 1.62 m³, underground 3.24 m³; pump 3240 L / 8 h = 6.75 L/min = 0.1125 L/s;
 * septic tank 18 x 120 + 18 x 40 = 2880 L against 3.6 x 1.5 x 1.5 = 8.1 m³; leader 30 m² x
 * 88 mm/h / 60 = 44 L/min.
 */
const REPORT = {
	demand: { stories: [{ story: 'L1', occupancy: 'residentialFlat', lpcd: 180, population: 10, daily: 1800 }, { story: 'ROOF', occupancy: 'residentialFlat', lpcd: 180, population: 8, daily: 1440 }], population: 18, daily: 3240, method: 'Tables 8.5.1(a)-(d)' },
	storage: {
		daily: 3.24, fireReserve: 0, overhead: 1.62, underground: 3.24, reference: 'Sec 5.9.1.2(c)', notes: [],
		tanks: [{ id: 'T1', kind: 'overhead', required: 1.62, provided: 11.25, drain: 50, overflow: 50, notes: [] }, { id: 'T2', kind: 'underground', required: 3.24, provided: 24, drain: 50, overflow: 50, notes: [] }],
		pump: { flow: 6.75, hours: 8, note: '3.24 m³ in 8 h' }, heads: { minResidualHead: 5.6 },
	},
	risers: [
		{ id: 'R1', system: 'coldWater', units: 30, flow: 90, diameter: 40, required: 40, ok: true, notes: ['down-feed'] },
		{ id: 'ST1', system: 'soil', units: 21, flow: null, diameter: 100, required: 150, ok: false, notes: [] },
	],
	rainwater: {
		intensity: 88, reference: 'Table 8.7.2',
		drains: [{ id: 'RD1', story: 'ROOF', area: 30, source: 'entered', flow: 44, leader: 75, ok: true }],
		leaders: [{ id: 'RW1', system: 'rainwater', units: null, area: 30, flow: 44, diameter: 75, required: 75, ok: true, notes: [] }],
	},
	septic: {
		persons: 18, volume: 2880, provided: 8100, length: 3600, width: 1500, waterDepth: 1500, compartments: 2, notes: ['V = 2880 L'], reference: 'Appendix S',
		soakWell: { ok: false, diameter: 1500, waterDepth: 1500, notes: ['water table too high'], reference: 'Table 8.6.10' },
	},
	tanks: [{ id: 'T1', kind: 'overhead', story: 'ROOF', x: 0, y: 0, sized: false }, { id: 'ST-T1', kind: 'septic', story: null, x: 0, y: 0 }, { id: 'SW1', kind: 'soakWell', story: null, x: 0, y: 0 }],
	checks: [
		{ name: 'T1 volume', demand: 1.62, capacity: 11.25, unit: 'm³', utilisation: 0.144, ok: true, note: '' },
		{ name: 'T2 volume', demand: 3.24, capacity: 24, unit: 'm³', utilisation: 0.135, ok: true, note: '' },
		{ name: 'ST1 fixture units', demand: 21, capacity: 20, unit: 'units', utilisation: 1.05, ok: false, note: '' },
		{ name: 'Septic tank liquid volume', demand: 2880, capacity: 8100, unit: 'l', utilisation: 0.356, ok: true, note: '' },
		{ name: 'Septic tank length', demand: 4500, capacity: 3600, unit: 'mm', utilisation: 1.25, ok: false, note: '' },
		{ name: 'Soak well', demand: 1, capacity: null, unit: '', utilisation: null, ok: false, note: 'water table too high' },
	],
	tankDesigns: [{
		id: 'T1', kind: 'overhead', geometry: { kind: 'overhead', capacity: 11.25 },
		checks: [
			{ name: 'East: horizontal bars, outer face', demand: 183, capacity: 262, unit: 'mm²/m', utilisation: 0.7, combination: '1.4D + 1.4F', ok: true, note: '' },
			{ name: 'Base: X bars, top face', demand: 288, capacity: 262, unit: 'mm²/m', utilisation: 1.1, combination: '1.4D + 1.4F', ok: false, note: '' },
		],
		walls: [
			{ name: 'East', direction: 'horizontal', face: 'outer', bars: 'Ø10 @ 300' },
			{ name: 'West', direction: 'horizontal', face: 'outer', bars: 'Ø10 @ 300' },
			{ name: 'North', direction: 'horizontal', face: 'outer', bars: 'Ø12 @ 300' },
		],
		base: [{ name: 'Base', direction: 'X', face: 'top', bars: 'Ø10 @ 200' }],
		roof: [],
		supportLoads: { empty: 139.3, full: 223.2 }, quantities: { concrete: 5.49, formwork: 54.1, reinforcement: 343 }, notes: ['n'],
	}],
	hydraulics: {
		floors: [
			{ story: 'ROOF', riser: 'R1', elevation: 6, head: 1.7, required: 5.6, pressureOk: false, ok: false },
			{ story: 'L1', riser: 'R1', elevation: 3, head: 7, required: 5.6, pressureOk: true, ok: true },
		],
		pump: { flow: 0.1125, tdh: 15.6, shaftPower: 0.035, note: 'H = hs + hd + hf + hv' },
		checks: [
			{ name: 'Residual head at the fixture, ROOF (R1)', demand: 5.6, capacity: 1.7, unit: 'm', utilisation: 3.29, ok: false, note: '' },
			{ name: 'Velocity in R1', demand: 0.5, capacity: 0.75, unit: 'm/s', utilisation: 0.67, ok: true, note: '' },
		],
		notes: ['h'], problems: [],
	},
	summary: ['Population 18'], notes: [], problems: [], method: ['m'],
};
