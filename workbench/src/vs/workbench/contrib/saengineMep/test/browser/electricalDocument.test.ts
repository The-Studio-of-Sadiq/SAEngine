/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IMep, newMep, parseMep, readMepContext, serializeMep } from '../../browser/mepDocument.js';
import { renderPlan } from '../../browser/mepPlan.js';
import {
	checkElectrical, connectedLoads, electricalExtent, electricalFailures, electricalOf, electricalSummary, ensureElectrical, hasElectrical, mergeProposedEquipment, newElecEquipment, newElecRiser,
	newTray, readElectricalReport, readElecUses, readProposedEquipment, STATIC_ELEC_USES,
} from '../../browser/electricalDocument.js';
import { renderElectrical } from '../../browser/electricalPlan.js';
import { renderElectricalReport } from '../../browser/electricalResults.js';
import { allIds } from '../../browser/plumbingDocument.js';
import { ensureHvac } from '../../browser/hvacDocument.js';

/*
 * Synthetic data only: a one-bay frame on a 6 m x 5 m grid, stories at 0 (base), 3 m (L1) and
 * 6 m (roof), 150 mm slabs at L1 and the roof, four corner columns, a 1 m square shaft from the
 * base to the roof. Expected values worked by hand.
 */

const BIM = JSON.stringify({
	schema: 'saengine.bim/2',
	stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3000 }, { id: 'ROOF', name: 'Roof', elevation: 6000 }],
	elements: [
		{ id: 'C1', kind: 'column', type: 'C400', position: [0, 0], bottom: 0, top: 6000 },
		{ id: 'C2', kind: 'column', type: 'C400', position: [6000, 0], bottom: 0, top: 6000 },
		{ id: 'C3', kind: 'column', type: 'C400', position: [6000, 5000], bottom: 0, top: 6000 },
		{ id: 'C4', kind: 'column', type: 'C400', position: [0, 5000], bottom: 0, top: 6000 },
		{ id: 'S1', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 3000 },
		{ id: 'S2', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 6000 },
	],
});
const OBJECTS = JSON.stringify({ objects: [{ id: 'C400', kind: 'column', profile: { shape: 'rectangle', xDim: 400, yDim: 400 } }, { id: 'S150', kind: 'slab', thickness: 150 }] });
const CONTEXT = readMepContext({ bim: BIM, objects: OBJECTS });

/** A transformer and a generator on the base, a busbar riser in the shaft, a tray on L1, lightning protection on. */
function setUp(): IMep {
	const document = newMep();
	document.shafts.push({ id: 'SH1', outline: [[4000, 1000], [5000, 1000], [5000, 2000], [4000, 2000]], fromStory: 'BASE', toStory: 'ROOF' });
	const electrical = ensureElectrical(document);
	electrical.supply = { voltage: '11kV', generator: true };
	electrical.stories.push({ story: 'L1', use: 'office', lighting: 10, power: 75, other: 5 });
	electrical.equipment.push(newElecEquipment(document, CONTEXT, 'transformer', 'L1'));
	electrical.equipment.push(newElecEquipment(document, CONTEXT, 'generator', 'L1'));
	electrical.risers.push(newElecRiser(document, CONTEXT, 'busbar', 'L1'));
	electrical.trays.push(newTray(document, 'L1', [[500, 2500], [5500, 2510]]));
	electrical.lightning = { enabled: true, level: 'II', downConductors: 'structuralRebar', earthing: 'ring' };
	return document;
}

suite('SAEngine MEP electrical', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('an old file stays as it was; the electrical section is created on the first edit', () => {
		const text = serializeMep(newMep());
		const parsed = parseMep(text);
		const document = parsed.kind === 'document' ? parsed.document : newMep();
		assert.deepStrictEqual({ electrical: electricalOf(document), has: hasElectrical(document), text: serializeMep(document) === text }, { electrical: undefined, has: false, text: true });
		ensureElectrical(document);
		assert.deepStrictEqual(document.electrical, { supply: {}, stories: [], equipment: [], risers: [], trays: [], lightning: { enabled: false } });
		const partial = parseMep(JSON.stringify({ schema: 'saengine.mep/1', electrical: { lightning: { enabled: 1, airTerminals: [[0, 0, 1500], [1]] }, extra: 1 } }));
		assert.deepStrictEqual(partial.kind === 'document' ? electricalOf(partial.document) : undefined, {
			lightning: { enabled: true, airTerminals: [[0, 0, 1500]] }, extra: 1, supply: {}, stories: [], equipment: [], risers: [], trays: [],
		});
	});

	test('places the equipment, the riser in the shaft and the tray; one ID space with the HVAC', () => {
		const document = setUp();
		const electrical = electricalOf(document)!;
		// The substation kinds on the lowest story, from the equipment presets (transformer 2.2 x 1.5 m, 40 kN; generator 4.5 x 1.6 m, 65 kN, vibrating).
		// The busbar (300 x 200) by the shaft's top-left corner, 100 mm clear: x = 4000 + 150 + 100 = 4250, y = 2000 - 100 - 100 = 1800.
		ensureHvac(document).plant.push({ id: 'TX9', kind: 'ahu', story: 'L1', x: 0, y: 0 });
		assert.deepStrictEqual({
			equipment: electrical.equipment.map(e => [e.id, e.kind, e.story, e.length, e.width, e.operatingWeight, e.vibrating ?? false]),
			riser: electrical.risers.map(r => [r.id, r.kind, r.x, r.y, r.width, r.depth, r.fromStory, r.toStory, r.shaft]),
			tray: electrical.trays.map(t => [t.id, t.story, t.path, t.width, t.height]),
			ids: allIds(document),
		}, {
			equipment: [['TX1', 'transformer', 'BASE', 2200, 1500, 40, false], ['GEN1', 'generator', 'BASE', 4500, 1600, 65, true]],
			riser: [['ER1', 'busbar', 4250, 1800, 300, 200, 'BASE', 'ROOF', 'SH1']],
			tray: [['CT1', 'L1', [[500, 2500], [5500, 2500]], 300, 100]],
			ids: ['SH1', 'TX9', 'TX1', 'GEN1', 'ER1', 'CT1'],
		});
		// The transformer clear of the generator on the 6 x 5 m footprint of the base (its floor: the slab above).
		const [tx, gen] = electrical.equipment;
		const apart = Math.abs(tx.x - gen.x) >= (2200 + 4500) / 2 || Math.abs(tx.y - gen.y) >= (1500 + 1600) / 2;
		assert.strictEqual(apart, true);
	});

	test('connected loads from the densities over the floor area', () => {
		const document = setUp();
		// L1: 30 m² x (10 + 75) W/m² = 2.55 kW, + 5 kW other = 7.55 kW.
		assert.deepStrictEqual(connectedLoads(document, CONTEXT).map(l => [l.story, l.area, Number(l.lighting.toFixed(3)), Number(l.power.toFixed(3)), l.other, Number(l.total.toFixed(3))]),
			[['L1', 30, 0.3, 2.25, 5, 7.55]]);
		assert.deepStrictEqual(STATIC_ELEC_USES.find(u => u.key === 'office'), { key: 'office', label: 'Office and commercial multi-storeyed', nonAc: 28, ac: 75, source: 'Table 8.1.17' });
	});

	test('checks the contract rules', () => {
		const document = setUp();
		const electrical = electricalOf(document)!;
		electrical.supply.voltage = '230V';
		electrical.stories.push({ story: 'L1', lighting: -1 });
		electrical.equipment[1].operatingWeight = undefined;
		electrical.risers[0].toStory = 'BASE';
		electrical.trays[0].path = [[0, 0]];
		electrical.lightning.level = 'V';
		assert.deepStrictEqual(checkElectrical(document, CONTEXT).map(p => `${p.severity} ${p.path}`), [
			'error electrical.supply.voltage',
			'error electrical.stories.1.story',
			'error electrical.stories.1.lighting',
			'warning electrical.equipment.1.operatingWeight',
			'error electrical.risers.0.toStory',
			'error electrical.trays.0.path',
			'error electrical.lightning.level',
		]);
	});

	test('merges the proposed equipment and reads the report; the status line', () => {
		const document = setUp();
		const proposed = readProposedEquipment([{ id: 'TX1', kind: 'transformer', story: 'BASE', x: 0, y: 0, rating: 500, operatingWeight: 22 }, { kind: 'ups', story: 'L1', x: 1000, y: 1000, rating: 20 }])!;
		const touched = mergeProposedEquipment(document, proposed.equipment);
		const report = readElectricalReport(REPORT)!;
		assert.deepStrictEqual({
			touched: touched.map(e => [e.id, e.kind, e.rating, e.operatingWeight, e.sized]),
			stories: report.stories.map(s => [s.story, s.connected, s.kva]),
			total: report.total,
			sources: report.sources.map(s => [s.kind, s.id, s.required, s.provided, s.status]),
			down: report.lightning?.downConductors,
			lightning: [report.lightning?.risk, report.lightning?.decision, report.lightning?.mesh.length, report.lightning?.earthing, report.lightning?.structuralNotes],
			runs: [...report.risers, ...report.trays].map(r => [r.id, r.size, r.fill === undefined ? undefined : Number(r.fill.toFixed(4)), r.status]),
			openings: report.openings.map(o => [o.id, o.host, o.size, o.status, o.proposed?.id]),
			failed: electricalFailures(report),
			summary: electricalSummary(document, report),
			uses: readElecUses({ uses: [{ key: 'office', label: 'Office', nonAc: 28, ac: 75 }, { label: 'none' }] }),
		}, {
			touched: [['TX1', 'transformer', 500, 22, true], ['EL1', 'ups', 20, undefined, true]],
			stories: [['L1', 7.55, 7.106]],
			// The connected load is the backend's: the stories' 7.55 kW with the plant's 3 kW and the lift's 7.5 kW.
			total: { connected: 18.05, stories: 7.55, hvac: 3, motors: 7.5, extra: 0, demand: 14.44, kva: 16.988, current: 24.52 },
			sources: [['transformer', undefined, 16.988, 100, 'ok'], ['generator', undefined, 15, 10, 'fail']],
			down: [
				{ id: 'DC1', column: 'C1', columns: ['C1'], x: 0, y: 0, foundation: 'F1', note: 'conductor: column reinforcement; earthed through foundation F1; test joint 1 m above the ground' },
				{ id: 'DC2', column: 'C3', columns: ['C3'], x: 6000, y: 5000, foundation: undefined, note: 'conductor: column reinforcement; test joint 1 m above the ground' },
			],
			lightning: [47, 'recommended', 2, 'Ring earth electrode; resistance at most 10 ohm; clearance to other metal 3.10 m, else bond it', ['Down-conductor column lines: C1, C3.']],
			// The busbar carries 10.26 A of its 100 A; the tray crosses B9 where no web opening fits.
			runs: [['ER1', '300 × 200, 100 A', 0.1026, 'ok'], ['CT1', undefined, undefined, 'fail']],
			openings: [['PE-ER1-L1', 'S1', '350 × 350', 'ok', 'PE-ER1-L1']],
			failed: 1,
			summary: '11kV · 3 equipment · 1 riser · 1 tray · lightning protection level II · 17 kVA · 1 check fails',
			uses: [{ key: 'office', label: 'Office', nonAc: 28, ac: 75, source: undefined }],
		});
	});

	test('draws the services and the lightning protection on the plans, and the report page', () => {
		const document = setUp();
		const report = readElectricalReport(REPORT)!;
		const draw = (story: string) => {
			const container = mainWindow.document.createElement('div');
			renderPlan(container, document, CONTEXT, {
				width: 600, height: 400, story, layer: 'electrical', extraExtent: electricalExtent(document, CONTEXT, story),
				overlay: (root, view) => renderElectrical(root, view, document, CONTEXT, { story, report, selection: { kind: 'elecRiser', index: 0 } }),
			});
			return container;
		};
		const base = draw('BASE');
		const l1 = draw('L1');
		const roof = draw('ROOF');
		assert.deepStrictEqual({
			baseEquipment: [...base.querySelectorAll('[data-elec-equipment]')].map(e => e.getAttribute('class')),
			risers: [base, l1, roof].map(c => c.querySelectorAll('.elec-riser.selected').length),
			trays: [base, l1, roof].map(c => c.querySelectorAll('[data-tray]').length),
			roofEdge: roof.querySelectorAll('.elec-lps-edge').length,
			terminals: roof.querySelectorAll('.elec-air-terminal.proposed').length,
			down: [base, l1, roof].map(c => c.querySelectorAll('.elec-down-conductor').length),
			ring: base.querySelectorAll('.elec-earth-ring').length,
		}, {
			// The generator fails its check (15 kVA needed, 10 given): its footprint is marked.
			baseEquipment: ['elec-equipment kind-transformer', 'elec-equipment kind-generator vibrating failed'],
			risers: [1, 1, 1],
			trays: [0, 1, 0],
			roofEdge: 1,
			terminals: 2,
			down: [2, 0, 2],
			ring: 1,
		});

		const page = mainWindow.document.createElement('div');
		renderElectricalReport(page, report, { storyName: id => id, row: body => body.appendChild(mainWindow.document.createElement('tr')), tableHead: () => { } });
		assert.deepStrictEqual({
			sections: [...page.querySelectorAll('.mep-section-title')].map(e => e.textContent),
			columns: page.querySelector('.elec-dc-list')?.textContent,
			failedRows: page.querySelectorAll('tr.failed').length,
		}, {
			sections: ['Demand by story', 'Transformer, generator and UPS', 'Rooms', 'Risers', 'Cable trays', 'Lightning protection', 'Openings for risers and trays', 'Checks', 'Notes', 'Method'],
			columns: 'C1, C3',
			// The generator's row, its capacity check and the tray crossing where no opening fits.
			failedRows: 3,
		});
	});
});

/*
 * A report in the shape E1's `electrical.report.electrical_report` returns (the keys as it writes
 * them, checked against its output for the synthetic eight-storey case), with values worked by hand
 * for the set-up above: L1 30 m² x 85 W/m² + 5 kW = 7.55 kW; the air-conditioning plant 3 kW and a
 * 7.5 kW lift motor bring the connected load to 18.05 kW; maximum demand 0.8 x 18.05 = 14.44 kW,
 * / 0.85 = 16.988 kVA. The generator gives 10 kVA of the 15 kVA needed: its check fails.
 */
const REPORT = {
	demand: {
		stories: [{ story: 'L1', name: 'Level 1', use: 'office', area: 30, density: 85, other: 5, connected: 7.55, demand: 6.04, kva: 7.106, notes: [] }],
		hvac: [{ id: 'ODU1', kind: 'vrfOutdoor', story: 'ROOF', kw: 3, note: 'estimate' }], motors: [{ id: 'LIFT', kind: 'lift', power: 7.5, count: 1, kw: 7.5, essential: true }], extra: [],
		storiesKw: 7.55, hvacKw: 3, motorsKw: 7.5, extraKw: 0, connected: 18.05, loadFactor: 0.8, growth: 0, powerFactor: 0.85, maximumDemand: 14.44, kva: 16.988, current: 24.52, notes: ['d'],
	},
	supply: {
		substation: false, voltage: '11kV',
		transformers: { count: 1, rating: 100, total: 100, required: 16.988, utilisation: 0.17, transformerArea: null, substationArea: null, note: '' },
		generator: { kva: 10, kw: 8, required: 15, utilisation: 1.5, fuelHours: 8, fuel: 17.28, roomArea: null, note: '' },
		ups: null, standbyLifts: false,
	},
	rooms: [{ name: 'TX1 room height', demand: 3000, capacity: 3350, unit: 'mm', utilisation: 0.896, ok: true, note: 'h' }],
	risers: [{ id: 'ER1', kind: 'busbar', stories: ['BASE', 'L1', 'ROOF'], fed: ['L1'], current: 10.26, segments: [], rating: 100, width: 300, depth: 200, weightPerM: 0.1, ok: true, notes: ['busbar'] }],
	trays: [{ tray: 'CT1', beam: 'B9', point: [3000, 2500], passesBelow: false, fits: false }],
	lightning: {
		risk: { indices: { A: 7 }, total: 47, decision: 'recommended', note: 'risk index 47 at or above the marginal 40' }, required: true, enabled: true, level: 'II',
		downConductors: [
			{ id: 'DC1', x: 0, y: 0, columns: ['C1'], foundation: 'F1', testBox: 1000, conductor: 'column reinforcement' },
			{ id: 'DC2', x: 6000, y: 5000, columns: ['C3'], foundation: null, testBox: 1000, conductor: 'column reinforcement' },
		],
		downConductorsNeeded: 2, airTerminals: [[0, 0, 6600], [6000, 5000, 6600]], airTerminalsProposed: true,
		roofConductors: [[[0, 0], [6000, 0], [6000, 5000]]],
		earth: { limit: 10, systemEarth: 1, resistance: 10, clearance: 3.1, electrodeSpacing: 1800, arrangement: 'ring' },
		checks: [], structuralNotes: ['Down-conductor column lines: C1, C3.'], notes: ['l'],
	},
	equipment: [],
	openings: [{ id: 'PE-ER1-L1', host: 'S1', kind: 'opening', shape: 'rectangle', width: 350, height: 350, position: { x: 4250, y: 1800 }, service: '100 A busbar ER1' }],
	checks: [
		{ name: 'Transformer capacity', demand: 16.988, capacity: 100, unit: 'kVA', utilisation: 0.17, ok: true, note: 't' },
		{ name: 'Generator capacity', demand: 15, capacity: 10, unit: 'kVA', utilisation: 1.5, ok: false, note: 'g' },
		{ name: 'TX1 room height', demand: 3000, capacity: 3350, unit: 'mm', utilisation: 0.896, ok: true, note: 'h' },
		{ name: 'Down conductors', demand: 2, capacity: 2, unit: '', utilisation: 1, ok: true, note: 'c' },
	],
	summary: ['s'], notes: ['n'], problems: [], method: ['m'], storeys: 1, height: 6,
};
