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
	checkFire, ensureFire, fireExtent, fireFailures, fireOf, fireSummary, fireSummaryFile, hasFire, mergeFireProposals, newFireRiser, readFireProposals, readFireReport,
} from '../../browser/fireDocument.js';
import { renderFire } from '../../browser/firePlan.js';
import { renderFireReport } from '../../browser/fireResults.js';
import { allIds } from '../../browser/plumbingDocument.js';
import { ensureElectrical } from '../../browser/electricalDocument.js';

/*
 * Synthetic data only: a one-bay frame on a 6 m x 5 m grid, stories at 0 (base), 3 m (L1) and
 * 6 m (roof), 150 mm slabs at L1 and the roof, four corner columns. Expected values worked by
 * hand.
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

/** Offices on the base and L1, a standpipe from the base to L1, a pump set on the base, a ground fire tank and an overhead one. */
function setUp(): IMep {
	const document = newMep();
	const fire = ensureFire(document);
	fire.stories.push({ story: 'BASE', occupancy: 'office' }, { story: 'L1', occupancy: 'office', area: 30 });
	fire.risers.push(newFireRiser(document, CONTEXT, 'standpipe', 'L1'));
	fire.pumps.push({ id: 'FP1', duty: 'main', story: 'BASE', x: 3000, y: 2500, flow: 946, head: 30, operatingWeight: 4.5 });
	fire.tanks.push({ id: 'FT1', kind: 'underground', story: null, x: -3000, y: 2500, length: 3000, width: 2000, waterDepth: 2000, sized: true });
	fire.tanks.push({ id: 'FT2', kind: 'overhead', story: 'ROOF', x: 3000, y: 2500, length: 2000, width: 1500, waterDepth: 1200 });
	return document;
}

suite('SAEngine MEP fire', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('an old file stays as it was; the fire section is created on the first edit', () => {
		const text = serializeMep(newMep());
		const parsed = parseMep(text);
		const document = parsed.kind === 'document' ? parsed.document : newMep();
		assert.deepStrictEqual({ fire: fireOf(document), has: hasFire(document), text: serializeMep(document) === text }, { fire: undefined, has: false, text: true });
		ensureFire(document);
		assert.deepStrictEqual(document.fire, { building: {}, supply: {}, stories: [], risers: [], mains: [], tanks: [], pumps: [] });
		const partial = parseMep(JSON.stringify({ schema: 'saengine.mep/1', fire: { mains: [{ id: 'M', story: 'L1', path: [[0, 0], [1]] }], pumpRoom: 3, extra: 1 } }));
		assert.deepStrictEqual(partial.kind === 'document' ? fireOf(partial.document) : undefined, {
			mains: [{ id: 'M', story: 'L1', path: [[0, 0]] }], extra: 1, building: {}, supply: {}, stories: [], risers: [], tanks: [], pumps: [],
		});
	});

	test('places a riser at a free corner; one ID space with the other services', () => {
		const document = setUp();
		ensureElectrical(document).risers.push({ id: 'FR2', kind: 'busbar', x: 0, y: 0, fromStory: 'BASE', toStory: 'L1' });
		const fire = ensureFire(document);
		const second = newFireRiser(document, CONTEXT, 'sprinkler', 'L1');
		assert.deepStrictEqual({
			first: [fire.risers[0].id, fire.risers[0].x, fire.risers[0].y, fire.risers[0].fromStory, fire.risers[0].toStory],
			// FR2 is the electrical riser's: the next free ID; the first riser's corner is taken.
			second: [second.id, second.x, second.y],
			ids: allIds(document).filter(id => id.startsWith('F')),
			extent: fireExtent(document, CONTEXT, 'BASE').length,
		}, {
			first: ['FR1', 1000, 1000, 'BASE', 'L1'],
			second: ['FR3', 5000, 4000],
			ids: ['FR2', 'FR1', 'FT1', 'FT2', 'FP1'],
			// the riser's point, the pump's four corners and the ground tank's four
			extent: 9,
		});
	});

	test('checks the contract rules', () => {
		const document = setUp();
		const fire = ensureFire(document);
		fire.stories.push({ story: 'L9', area: -1 });
		fire.risers.push({ id: 'FR1', system: 'drencher', x: 0, y: 0, fromStory: 'L1', toStory: 'BASE', shaft: 'SH9' });
		fire.tanks.push({ id: 'FT3', kind: 'septic', story: null, x: 0, y: 0, length: 1000, width: 1000, waterDepth: 0 });
		fire.pumps.push({ id: 'FP2', duty: 'main', story: 'L7', x: 0, y: 0, equipment: 'E9' });
		assert.deepStrictEqual(checkFire(document, CONTEXT).map(p => [p.path, p.severity]), [
			['fire.stories.2.story', 'error'], ['fire.stories.2.area', 'error'],
			['fire.risers.0.id', 'error'], ['fire.risers.1.id', 'error'], ['fire.risers.1.system', 'error'], ['fire.risers.1.toStory', 'error'], ['fire.risers.1.shaft', 'error'],
			['fire.tanks.2.kind', 'error'], ['fire.tanks.2.waterDepth', 'error'],
			['fire.pumps.1.story', 'error'], ['fire.pumps.1.equipment', 'error'],
		]);
	});

	test('merges the proposed pumps and tank and reads the report; the status line', () => {
		const document = setUp();
		const proposals = readFireProposals({
			tanks: [{ id: 'FT1', kind: 'underground', x: -3000, y: 2500, length: 4000, width: 2000, waterDepth: 2000, sized: true }],
			pumps: [{ id: 'FP1', duty: 'main', story: 'BASE', x: 3000, y: 2500, flow: 1136, head: 30 }, { id: 'FPS1', duty: 'standby', story: 'BASE', x: 4500, y: 2500, flow: 1136, head: 30 }, { story: 'BASE' }],
			notes: ['n'],
		})!;
		const touched = mergeFireProposals(document, proposals.tanks, proposals.pumps);
		const report = readFireReport(REPORT)!;
		assert.deepStrictEqual({
			touched: touched.map(t => [t.id, t.length, t.flow, t.sized]),
			systems: report.systems.map(s => [s.system, s.status, s.provided]),
			stories: report.stories.map(s => [s.story, s.hazard, s.extinguishers, s.heads]),
			water: [report.demand?.flow, report.demand?.volume, report.hydraulics?.pumpHead, report.hydraulics?.standpipe?.outlets[0].pressure],
			pumps: report.pumps.map(p => [p.duty, p.flow, p.ids]),
			checks: report.checks.map(c => [c.name, c.status, c.clause]),
			openings: report.openings.map(o => [o.id, o.host, o.proposed?.id]),
			failed: fireFailures(report),
			summary: fireSummary(document, report),
			file: fireSummaryFile(document, report),
		}, {
			// FT1 longer; FP1 a larger flow; the standby pump added; the pump without an ID or plan point dropped.
			touched: [['FT1', 4000, undefined, true], ['FP1', undefined, 1136, true], ['FPS1', undefined, 1136, true]],
			systems: [['extinguishers', 'notRequired', false], ['manualAlarm', 'required', true], ['hydrant', 'required', true]],
			stories: [['BASE', 'lightI', 1, undefined], ['L1', 'lightI', 1, undefined]],
			// 1000 l/min for 30 min = 30 m³ (Table 4.4.1, light hazard-I, up to 51 m)
			water: [1000, 30, 31.2, 300],
			pumps: [['main', 1136, ['FP1']]],
			checks: [['Fire reservoir', 'ok', 'Part 4 Sec 4.2.2.3, part1 p325'], ['Secondary (standby) fire pump', 'fail', 'Part 4 Sec 4.2.2.5, part1 p325-326']],
			openings: [['FS-FR1-L1', 'S1', 'FS-FR1-L1']],
			failed: 1,
			summary: 'Required: manual fire alarm, hydrant (standpipe) system · 2 stories · 1 riser · 1000 l/min, 30 m³ · 1 check fails',
			file: { risers: 1, pumps: 2, tanks: 2, flow: 1000, reservoir: 30, required: ['manualAlarm', 'hydrant'], openingsToAdd: 1, failed: 1 },
		});
	});

	test('draws the fire protection on the plans, and the report page', () => {
		const document = setUp();
		const report = readFireReport(REPORT)!;
		const draw = (story: string) => {
			const container = mainWindow.document.createElement('div');
			renderPlan(container, document, CONTEXT, {
				width: 600, height: 400, story, layer: 'fire', extraExtent: fireExtent(document, CONTEXT, story),
				overlay: (root, view) => renderFire(root, view, document, CONTEXT, { story, report, selection: { kind: 'fireRiser', index: 0 } }),
			});
			return container;
		};
		const [base, l1, roof] = ['BASE', 'L1', 'ROOF'].map(draw);
		assert.deepStrictEqual({
			risers: [base, l1, roof].map(c => c.querySelectorAll('.fire-riser.selected').length),
			letters: base.querySelector('.fire-riser-letters')?.textContent,
			pumps: [base, l1, roof].map(c => c.querySelectorAll('[data-fire-pump]').length),
			tanks: [base, l1, roof].map(c => [...c.querySelectorAll('[data-fire-tank]')].map(t => t.getAttribute('class'))),
		}, {
			risers: [1, 1, 0],
			letters: 'SP',
			pumps: [1, 0, 0],
			tanks: [['fire-tank ground sized'], [], ['fire-tank']],
		});

		const page = mainWindow.document.createElement('div');
		renderFireReport(page, report, { storyName: id => id, row: body => body.appendChild(mainWindow.document.createElement('tr')), tableHead: () => { } });
		assert.deepStrictEqual({
			sections: [...page.querySelectorAll('.mep-section-title')].map(e => e.textContent),
			statuses: [...page.querySelectorAll('.fire-status')].map(e => e.textContent),
			failedRows: page.querySelectorAll('tr.failed').length,
		}, {
			sections: ['Systems required', 'Floors', 'Fire water and hydraulics', 'Pump sets', 'Fire tanks', 'Hangers and riser supports', 'Sleeves still missing', 'Checks', 'Test pressures', 'Notes', 'Method'],
			statuses: ['Not required', 'Required', 'Required'],
			failedRows: 1,
		});
	});
});

/*
 * A report in the shape `saengine.fire.report.fire_report` returns (the keys as it writes them),
 * with values worked by hand for the set-up above: offices E1 up to 2 storeys and 500 m², with the
 * hydrant chosen: standpipe 1000 l/min for 30 min (light hazard-I, Table 4.4.1) = 30 m³.
 */
const REPORT = {
	requirements: {
		highRise: false, tall: false, storeys: 2, height: 6, topOccupied: 3, highRiseNote: '2 storeys above ground: not high-rise',
		systems: [
			{ system: 'extinguishers', label: 'Portable fire extinguishers', status: 'notRequired', provided: false, reasons: [] },
			{ system: 'manualAlarm', label: 'Manual fire alarm', status: 'required', provided: true, reasons: ['E1: ... (Part 4 Sec 5.7(ii))'] },
			{ system: 'hydrant', label: 'Hydrant (standpipe) system', status: 'required', provided: true, reasons: ['E1: ... hydrant chosen'] },
		],
		rules: [{ group: 'E1', clause: 'Part 4 Sec 5.7(ii), part1 p350-351', text: 'manual alarm with extinguishers or hydrants', required: ['manualAlarm'], anyOf: ['extinguishers', 'hydrant'] }],
		firePlan: { required: false, reasons: [] }, notes: [],
	},
	stories: [
		{ story: 'BASE', occupancy: 'office', group: 'E1', hazard: 'lightI', area: 30, level: 0, sprinklered: false, extinguishers: 1, callPoints: 1, detectors: 0, sprinklers: null },
		{ story: 'L1', occupancy: 'office', group: 'E1', hazard: 'lightI', area: 30, level: 3, sprinklered: false, extinguishers: 1, callPoints: 1, detectors: 0, sprinklers: null },
	],
	hazard: 'lightI', height: 6,
	demand: { hazard: 'lightI', standpipe: 1000, sprinkler: 0, flow: 1000, duration: 30, volume: 30, notes: ['d'] },
	hydraulics: {
		header: 100, risers: [{ id: 'FR1', system: 'standpipe', size: 100, given: false, floors: 2 }], flow: 1000, sourceHead: 28, governing: 'standpipe', maxVelocity: 2.03, pumpHead: 31.2,
		prvStories: [], suction: { waterLevel: -3.2, pumpLevel: 0.5, lift: 0 },
		standpipe: { first: 'FR1', flow: 1000, sourceHead: 28, outlets: [{ riser: 'FR1', story: 'L1', node: 'FR1:L1:OUT', flow: 1000, pressure: 300 }], pipes: [], required: 300 },
		sprinkler: null,
	},
	pumps: [{ duty: 'main', label: 'Main fire pump', flow: 1136, head: 31.2, power: 15, count: 1, length: 1450, width: 650, height: 1000, operatingWeight: 3.3, ids: ['FP1'] }],
	pumpRoom: { length: 4300, width: 4450, area: 19.1, note: 'n' },
	storage: { required: 30, provided: 32, tanks: [{ id: 'FT1', kind: 'underground', volume: 12 }, { id: 'FT2', kind: 'overhead', volume: 20 }], notes: [] },
	tankDesigns: [{ id: 'FT1', kind: 'underground', checks: [{ name: 'Flotation', ok: true }] }],
	supports: [{ size: 100, kind: 'support', spacing: 6, load: 2.5, basis: 'b' }],
	testPressures: [{ system: 'standpipe', pressure: 1400, note: 't' }],
	openings: [{ id: 'FS-FR1-L1', host: 'S1', kind: 'sleeve', shape: 'circle', diameter: 200, position: { x: 1000, y: 1000 }, service: 'DN100 standpipe riser FR1' }],
	crossings: [], proposals: { tanks: [], pumps: [] },
	quantities: { pipes: [{ size: 100, length: 4.5 }], heads: 0, extinguishers: 2, callPoints: 2, detectors: 0 },
	checks: [
		{ name: 'Fire reservoir', demand: 30, capacity: 32, unit: 'm³', utilisation: 0.9375, ok: true, note: '', clause: 'Part 4 Sec 4.2.2.3, part1 p325' },
		{ name: 'Secondary (standby) fire pump', demand: 1, capacity: 0, unit: 'sets', utilisation: null, ok: false, note: 'a secondary pump', clause: 'Part 4 Sec 4.2.2.5, part1 p325-326' },
	],
	summary: ['s'], notes: ['note'], problems: [], method: ['m'],
};
