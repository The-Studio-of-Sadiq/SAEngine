/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IMep, newMep, parseMep, readMepContext, serializeMep } from '../../browser/mepDocument.js';
import { renderPlan } from '../../browser/mepPlan.js';
import { roofStory, storyAbove, storyFloorArea } from '../../browser/mepRead.js';
import {
	checkHvac, ductCrossings, ductLevels, ductOnStory, ensureHvac, hasHvac, hvacExtent, hvacFailures, hvacOf, hvacSummary, mergeProposedPlant, newDuct, newPlant, newRiserDuct, readConstructions,
	readHvacReport, readHvacTables, readProposedPlant, riserInShaft, STATIC_CITIES, STATIC_USES,
} from '../../browser/hvacDocument.js';
import { renderHvac } from '../../browser/hvacPlan.js';
import { renderHvacReport } from '../../browser/hvacResults.js';

/*
 * Synthetic data only: a one-bay frame on a 6 m x 5 m grid, stories at 0 (base), 3 m (L1) and
 * 6 m (roof); 300 x 500 beams B1 (along y = 0) and B3 (along y = 5 m) at L1, 150 mm slabs at L1
 * and the roof, a 1 m square shaft from the base to the roof. Expected values worked by hand.
 */

const BIM = JSON.stringify({
	schema: 'saengine.bim/2',
	stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3000 }, { id: 'ROOF', name: 'Roof', elevation: 6000 }],
	elements: [
		{ id: 'C1', kind: 'column', type: 'C400', position: [0, 0], bottom: 0, top: 6000 },
		{ id: 'C2', kind: 'column', type: 'C400', position: [6000, 5000], bottom: 0, top: 6000 },
		{ id: 'B1', kind: 'beam', type: 'B300x500', start: [0, 0], end: [6000, 0], elevation: 3000 },
		{ id: 'B3', kind: 'beam', type: 'B300x500', start: [0, 5000], end: [6000, 5000], elevation: 3000 },
		{ id: 'S1', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 3000 },
		{ id: 'S2', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 6000 },
	],
});
const OBJECTS = JSON.stringify({
	objects: [
		{ id: 'C400', kind: 'column', profile: { shape: 'rectangle', xDim: 400, yDim: 400 } }, { id: 'B300x500', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 500 } },
		{ id: 'S150', kind: 'slab', thickness: 150 },
	],
});
const CONTEXT = readMepContext({ bim: BIM, objects: OBJECTS });

/** VRF with two outdoor units on the roof, a supply duct under L1 crossing B3, an exhaust riser in the shaft. */
function setUp(): IMep {
	const document = newMep();
	document.shafts.push({ id: 'SH1', outline: [[4000, 1000], [5000, 1000], [5000, 2000], [4000, 2000]], fromStory: 'BASE', toStory: 'ROOF' });
	const hvac = ensureHvac(document);
	hvac.system = 'vrf';
	hvac.design = { city: 'dhaka' };
	hvac.stories.push({ story: 'BASE', conditioned: true, use: 'officeSpace', lighting: 10, equipment: 15, glazing: { N: 0.3, S: 0.4 } });
	hvac.plant.push(newPlant(document, CONTEXT, 'vrfOutdoor', 'BASE'));
	hvac.plant.push(newPlant(document, CONTEXT, 'vrfOutdoor', 'BASE'));
	hvac.ducts.push(newDuct(document, 'supply', 'BASE', [[3000, 4000], [3000, 6000]]));
	hvac.ducts.push(newRiserDuct(document, CONTEXT, 'exhaust', 'L1'));
	return document;
}

suite('SAEngine MEP HVAC', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('an old file stays as it was; the HVAC is created on the first HVAC edit', () => {
		const text = serializeMep(newMep());
		const parsed = parseMep(text);
		const document = parsed.kind === 'document' ? parsed.document : newMep();
		assert.deepStrictEqual({ hvac: hvacOf(document), has: hasHvac(document), text: serializeMep(document) === text }, { hvac: undefined, has: false, text: true });
		ensureHvac(document);
		assert.deepStrictEqual(document.hvac, { design: {}, envelope: {}, stories: [], plant: [], ducts: [] });
		const partial = parseMep(JSON.stringify({ schema: 'saengine.mep/1', hvac: { ducts: [{ id: 'D1', path: [[0, 0], 'x', [1, 2]] }, 3], extra: 1 } }));
		const read = partial.kind === 'document' ? hvacOf(partial.document) : undefined;
		assert.deepStrictEqual(read, { ducts: [{ id: 'D1', path: [[0, 0], [1, 2]] }], extra: 1, design: {}, envelope: {}, stories: [], plant: [] });
	});

	test('places plant on the roof, ducts on their story and the riser in the shaft', () => {
		const document = setUp();
		const hvac = hvacOf(document)!;
		// The roof: the highest story with slabs. ODU1 at the middle of its 6 x 5 m floor (3.0, 2.5 m); ODU2 (1250 x 800) clear of it:
		// the nearest grid point (250 mm) with y outside 2100..2900 is 1000 mm away, (3.0, 1.5 m) before (3.0, 3.5 m).
		// The riser: at the centre of SH1 (4.5, 1.5 m), from the base to the roof.
		assert.deepStrictEqual({
			roof: roofStory(CONTEXT)?.id, above: storyAbove(CONTEXT, 'BASE')?.id,
			plant: hvac.plant.map(p => [p.id, p.kind, p.story, p.x, p.y, p.length, p.width, p.operatingWeight]),
			ducts: hvac.ducts.map(d => [d.id, d.system, d.story, d.width, d.height, d.path, d.riser ?? null, d.shaft ?? null]),
			riserIn: riserInShaft(hvac.ducts[1], document), onL1: ductOnStory(hvac.ducts[1], CONTEXT, 'L1'), runOnL1: ductOnStory(hvac.ducts[0], CONTEXT, 'L1'),
		}, {
			roof: 'ROOF', above: 'L1',
			plant: [['ODU1', 'vrfOutdoor', 'ROOF', 3000, 2500, 1250, 800, undefined], ['ODU2', 'vrfOutdoor', 'ROOF', 3000, 1500, 1250, 800, undefined]],
			ducts: [
				['D1', 'supply', 'BASE', 600, 300, [[3000, 4000], [3000, 6000]], null, null],
				['D2', 'exhaust', 'BASE', 400, 250, [[4500, 1500]], { fromStory: 'BASE', toStory: 'ROOF' }, 'SH1'],
			],
			riserIn: 'SH1', onL1: true, runOnL1: false,
		});
		// Floor areas: L1 its slab (30 m²); the base (no slab) the floor above it.
		assert.deepStrictEqual([storyFloorArea(CONTEXT, 'L1'), storyFloorArea(CONTEXT, 'BASE')], [30, 30]);
	});

	test('finds where a duct crosses the beams of the floor above, and the opening there', () => {
		const document = setUp();
		const duct = hvacOf(document)!.ducts[0];
		// Under L1: soffit 3000 - 150 = 2850, the 300 deep duct 2550..2850; B3's soffit 3000 - 500 = 2500: crossed at x = 3 m.
		assert.deepStrictEqual({ levels: ductLevels(duct, CONTEXT), crossings: ductCrossings(duct, document, CONTEXT) }, {
			levels: { bottom: 2550, top: 2850 },
			crossings: [{ duct: 'D1', beam: 'B3', point: [3000, 5000], distance: 3000, angle: 90, opening: undefined }],
		});
		document.openings.push({ id: 'OP1', host: 'B3', kind: 'opening', shape: 'rectangle', width: 700, height: 350, position: { distance: 3100, elevation: 250 } });
		assert.deepStrictEqual(ductCrossings(duct, document, CONTEXT).map(c => c.opening), ['OP1']);
		// Run on the floor (0..300 above it): below the beams, it crosses none.
		duct.bottom = 0;
		assert.deepStrictEqual(ductCrossings(duct, document, CONTEXT), []);
	});

	test('checks the contract rules', () => {
		const document = setUp();
		const hvac = hvacOf(document)!;
		hvac.design = { city: 'atlantis', outdoorDB: 30, outdoorWB: 32, indoorRH: 120 };
		hvac.stories[0].glazing = { N: 1.5 };
		hvac.plant[1].id = 'ODU1';
		hvac.ducts[0].path = [[0, 0]];
		hvac.ducts[1].shaft = 'SH9';
		assert.deepStrictEqual(checkHvac(document, CONTEXT).map(p => `${p.severity} ${p.path}`), [
			'warning hvac.design.city',
			'error hvac.design.outdoorWB',
			'error hvac.design.indoorRH',
			'error hvac.stories.0.glazing.N',
			'error hvac.plant.0.id',
			'warning hvac.plant.0.operatingWeight',
			'error hvac.plant.1.id',
			'warning hvac.plant.1.operatingWeight',
			'error hvac.ducts.0.path',
			'error hvac.ducts.1.shaft',
		]);
		assert.deepStrictEqual([STATIC_CITIES.find(c => c.key === 'dhaka'), STATIC_USES.find(u => u.key === 'officeSpace')?.perPerson],
			[{ key: 'dhaka', label: 'Dhaka', db: 34.5, wb: 27.0, range: 5.0 }, 2.5]);
	});

	test('merges the proposed plant: changed sizes only, the position stays; new ones get unused IDs', () => {
		const document = setUp();
		const proposed = readProposedPlant({
			plant: [{ id: 'ODU1', kind: 'vrfOutdoor', story: 'ROOF', x: 0, y: 0, capacity: 14, operatingWeight: 2.9 }, { kind: 'ahu', story: 'L1', x: 1000, y: 1000, operatingWeight: 18 }, { id: 'x' }],
			notes: ['n'],
		})!;
		const touched = mergeProposedPlant(document, proposed.plant);
		assert.deepStrictEqual({
			notes: proposed.notes,
			touched: touched.map(p => [p.id, p.kind, p.story, p.x, p.y, p.capacity, p.operatingWeight, p.sized]),
			again: mergeProposedPlant(document, [proposed.plant[0]]).length,
		}, {
			notes: ['n'],
			touched: [['ODU1', 'vrfOutdoor', 'ROOF', 3000, 2500, 14, 2.9, true], ['AC1', 'ahu', 'L1', 1000, 1000, undefined, 18, true]],
			again: 0,
		});
	});

	test('reads the backend report and the tables; the status line', () => {
		const document = setUp();
		const report = readHvacReport(REPORT)!;
		// L1: 3.0 + 0.75 = 3.75 kW over 30 m² = 125 W/m²; roof 4.75 kW over 25 m² = 190 W/m²; in all 7.25 + 1.25 = 8.5 kW over 55 m².
		// The duct's velocity check is its utilisation; the crossing of B3 that no checked opening can pass fails on its depth (2.7).
		// The failures are counted from the checks (the conflict is the one failing check), not again from the rows.
		assert.deepStrictEqual({
			engine: [report.engine, report.estimate],
			stories: report.stories.map(s => [s.story, s.total, s.density, s.supply, s.freshAir, s.exhaust]),
			total: { ...report.total, supply: Number(report.total?.supply?.toFixed(3)) },
			peak: [report.coincident, report.peak, report.tons],
			ducts: report.ducts.map(d => [d.id, d.size, d.load, d.utilisation, d.status]),
			shafts: report.shafts.map(s => [s.id, s.required, s.provided, s.status]),
			plant: report.plant.map(p => [p.id, p.kind, p.provided, p.weight]),
			failed: hvacFailures(report),
			openings: report.openings.map(o => [o.id, o.host, o.duct, o.size, o.check, o.utilisation, o.status]),
			summary: hvacSummary(document, CONTEXT, report),
			estimate: readHvacReport({ engine: 'estimate', zones: [] })?.estimate,
			nested: readHvacReport({ loads: { engine: 'estimate', zones: REPORT.zones, total: 8.5 }, air: REPORT.air })?.stories.map(s => [s.story, s.supply]),
			bad: readHvacReport('x'),
		}, {
			engine: ['EnergyPlus version 26.2.0', false],
			stories: [['L1', 3.75, 125, 0.3, 0.05, 0.05], ['ROOF', 4.75, 190, 0.36, 0.04, 0]],
			total: { sensible: 7.25, latent: 1.25, total: 8.5, area: 55, supply: 0.66, freshAir: 0.09 },
			peak: [8.1, '21/5 15:00', 2.417],
			ducts: [['D1', '600 × 300', 0.3, 0.222, 'ok']],
			shafts: [['SH1', 0.16, 1.0, 'ok']],
			plant: [['ODU1', 'vrfOutdoor', 8.5, 2.6]],
			failed: 1,
			openings: [['HD-D1-B3-1', 'B3', 'D1', '750 × 450', 'Opening depth for the net-section method (h/3)', 2.7, 'fail']],
			nested: [['L1', 0.3], ['ROOF', 0.36]],
			summary: 'VRF (variable refrigerant flow) · 2 plant items · 2 ducts · 1 beam crossing without an opening · 9 kW cooling · 1 check fails',
			estimate: true,
			bad: undefined,
		});
		assert.deepStrictEqual({
			constructions: readConstructions({ wall: [{ key: 'brick250', label: 'Brick', u: 2.1 }], roof: [], glazing: [{ id: 'g', name: 'Glass', u: 5.7, shgc: 0.8 }] }),
			list: readConstructions([{ key: 'r', label: 'Roof', element: 'roof', u: 1.5 }])?.roof,
			none: readConstructions({}),
			tables: readHvacTables({ cities: [{ key: 'dhaka', label: 'Dhaka', db: 34.5, wb: 27.0, range: 5 }, { key: 'sylhet', name: 'Sylhet', cooling: { '0.4': [35.5, 27.0], '2': [34.0, 26.5] }, range: 5.5 }] }),
		}, {
			constructions: { wall: [{ key: 'brick250', label: 'Brick', u: 2.1, shgc: undefined }], roof: [], glazing: [{ key: 'g', label: 'Glass', u: 5.7, shgc: 0.8 }] },
			list: [{ key: 'r', label: 'Roof', u: 1.5, shgc: undefined }],
			none: undefined,
			tables: { cities: [{ key: 'dhaka', label: 'Dhaka', db: 34.5, wb: 27.0, range: 5 }, { key: 'sylhet', label: 'Sylhet', db: 34.0, wb: 26.5, range: 5.5 }], uses: undefined },
		});
	});

	test('draws the HVAC on the plan under the ceiling, and the report page', () => {
		const document = setUp();
		const draw = (story: string) => {
			const container = mainWindow.document.createElement('div');
			renderPlan(container, document, CONTEXT, {
				width: 600, height: 400, story, layer: 'hvac', ceiling: storyAbove(CONTEXT, story)?.id, extraExtent: hvacExtent(document, CONTEXT, story), selection: { kind: 'duct', index: 0 },
				overlay: (root, view) => renderHvac(root, view, document, CONTEXT, { story, selection: { kind: 'duct', index: 0 } }),
			});
			return container;
		};
		const base = draw('BASE');
		const roof = draw('ROOF');
		assert.deepStrictEqual({
			ceilingBeams: [...base.querySelectorAll('.mep-beam.ceiling')].map(e => e.getAttribute('data-element')),
			ducts: [...base.querySelectorAll('[data-duct]')].map(e => e.getAttribute('class')),
			open: base.querySelectorAll('.hvac-crossing.open').length,
			plantOnRoof: [...roof.querySelectorAll('[data-plant]')].map(e => e.getAttribute('data-plant')),
			plantOnBase: base.querySelectorAll('[data-plant]').length,
		}, {
			ceilingBeams: ['B1', 'B3'],
			ducts: ['hvac-duct sys-supply selected', 'hvac-riser-duct sys-exhaust'],
			open: 1,
			plantOnRoof: ['0', '1'],
			plantOnBase: 0,
		});

		const page = mainWindow.document.createElement('div');
		renderHvacReport(page, readHvacReport(REPORT)!, { storyName: id => id, row: body => body.appendChild(mainWindow.document.createElement('tr')), tableHead: () => { } });
		assert.deepStrictEqual({
			engine: page.querySelector('.hvac-engine-value')?.textContent,
			sections: [...page.querySelectorAll('.mep-section-title')].map(e => e.textContent),
			bars: page.querySelectorAll('rect.mep-bar').length,
			failedRows: page.querySelectorAll('tr.failed').length,
		}, {
			engine: 'EnergyPlus version 26.2.0',
			sections: ['Cooling load by story', 'Airflow and ducts', 'Plant', 'Duct openings', 'Shafts', 'Checks', 'Notes', 'Method'],
			bars: 4,
			// The opening B3 needs, and the check of the ducts through the beams.
			failedRows: 2,
		});
	});
});

/*
 * A report in the shapes H1's backend returns (the keys as `hvac.report.hvac_loads` and
 * `hvac.air.hvac_air` write them, checked against their output for a synthetic project): the loads
 * at the top level and the air side under `air`, as the integrator answers `saengine.hvac.report`.
 * Values for the set-up above, by hand: L1 3.0 + 0.75 = 3.75 kW over 30 m² = 125 W/m²; the roof
 * 4.25 + 0.5 = 4.75 kW over 25 m² = 190 W/m²; in all 8.5 kW, supply 0.30 + 0.36 = 0.66 m³/s.
 */
const REPORT = {
	method: ['m'], design: { station: 'dhaka', outdoorDB: 34.5, outdoorWB: 27.0, dailyRange: 5.0 }, envelope: {}, assumptions: [],
	engine: 'EnergyPlus version 26.2.0', engineLabel: 'EnergyPlus version 26.2.0',
	zones: [
		{ story: 'L1', zone: 'Z L1', use: 'officeSpace', area: 30, sensible: 3.0, latent: 0.75, total: 3.75, airflow: 0.3, outdoorAir: 0.05, density: 125, tons: 1.066, supply: 0.3, freshAir: 0.05, engine: 'EnergyPlus version 26.2.0' },
		{ story: 'ROOF', zone: 'Z ROOF', use: 'officeSpace', area: 25, sensible: 4.25, latent: 0.5, total: 4.75, airflow: 0.36, outdoorAir: 0.04, density: 190, tons: 1.351, supply: 0.36, freshAir: 0.04, engine: 'EnergyPlus version 26.2.0' },
	],
	total: 8.5, tons: 2.417, sensible: 7.25, latent: 1.25, airflow: 0.66, outdoorAir: 0.09,
	building: { total: 8.1, designDay: 'May', month: 5, day: 21, time: '15:00' },
	notes: ['n'], problems: [], stamp: 's',
	air: {
		zones: [
			{ story: 'L1', use: 'officeSpace', area: 30, sensible: 3.0, total: 3.75, airflow: 0.3, outdoorAir: 0.05, exhaust: { toilet: 0.05, kitchen: 0, general: 0, kitchenBasis: null, notes: [] }, notes: [], conditioned: true },
			{ story: 'ROOF', use: 'officeSpace', area: 25, sensible: 4.25, total: 4.75, airflow: 0.36, outdoorAir: 0.04, exhaust: { toilet: 0, kitchen: 0, general: 0, kitchenBasis: null, notes: [] }, notes: [], conditioned: true },
			{ story: 'BASE', use: null, area: 30, sensible: 0, total: null, airflow: 0, outdoorAir: 0, exhaust: {}, notes: [], conditioned: false },
		],
		ducts: [{ id: 'D1', system: 'supply', story: 'BASE', riser: false, flow: 0.3, size: { shape: 'rect', width: 600, height: 300 }, proposed: false, velocity: 1.667, friction: 0.1, ok: true, note: 'v' }],
		shafts: [{ id: 'SH1', area: 1.0, need: 0.16, ducts: [], pipes: 0, ok: true }],
		plant: [{ id: 'ODU1', kind: 'vrfOutdoor', story: 'ROOF', x: 3000, y: 2500, length: 950, width: 760, height: 1690, capacity: 8.5, operatingWeight: 2.6, sized: true }],
		openings: [],
		conflicts: [{
			duct: 'D1', beam: 'B3', story: 'BASE', at: [3000, 5000],
			opening: { id: 'HD-D1-B3-1', host: 'B3', kind: 'opening', shape: 'rectangle', position: { distance: 3000, elevation: 250 }, service: 'supply duct 600 x 300 D1', width: 750, height: 450 },
			checks: [
				{ name: 'Opening depth for the net-section method (h/3)', demand: 450, capacity: 166.7, unit: 'mm', utilisation: 2.7, ok: false, note: 'deeper', flag: false },
				{ name: 'Opening length for the net-section method (d)', demand: 750, capacity: 840, unit: 'mm', utilisation: 0.893, ok: true, note: 'longer', flag: false },
			],
			notes: [], options: [],
		}],
		checks: [
			{ name: 'Shaft SH1 area (HVAC risers)', demand: 0.16, capacity: 1.0, unit: 'm²', utilisation: 0.16, ok: true, note: 's' },
			{ name: 'Duct D1 velocity', demand: 1.667, capacity: 7.5, unit: 'm/s', utilisation: 0.222, ok: true, note: 'v' },
			{ name: 'Ducts through beams and slabs', demand: 1, capacity: 0, unit: 'ducts', utilisation: 1, ok: false, note: 'c' },
		],
		notes: ['a'], problems: [], method: { supplyDeltaT: 11 },
	},
};
