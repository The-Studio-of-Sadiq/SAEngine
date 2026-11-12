/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	bimOpeningOutline, checkMep, convexOverlap, EQUIPMENT_PRESETS, equipmentOutline, equipmentPressure, equipmentSupport, findHost, guessDiscipline, IEquipment, IMep, isPartlyChecked, MEP_SCHEMA_ID, mepSummary, mepSummaryFile, newEquipment, newMep, newShaft, newSleeve, openingPoint, parseMep,
	plinthWeight, readMepContext, readMepReport, readSleeveSuggestions, serializeMep, shaftOnStory, sleeveForClash, storyElements, storyLoads,
} from '../../browser/mepDocument.js';
import { renderPlan } from '../../browser/mepPlan.js';

/*
 * Synthetic data only: a one-bay, two-story frame on a 6 m x 5 m grid with 300 x 500 beams, a
 * 150 mm slab per floor, a wall and a slab opening. Expected values are worked by hand.
 */

const BIM = JSON.stringify({
	schema: 'saengine.bim/2',
	stories: [{ id: 'L1', name: 'Level 1', elevation: 3000 }, { id: 'BASE', name: 'Base', elevation: 0 }, { id: 'ROOF', name: 'Roof', elevation: 6000 }],
	elements: [
		{ id: 'C1', kind: 'column', type: 'C400', position: [0, 0], bottom: 0, top: 3000 },
		{ id: 'C2', kind: 'column', type: 'C400', position: [6000, 0], bottom: 0, top: 3000 },
		{ id: 'C3', kind: 'column', type: 'C400', position: [0, 5000], bottom: 3000, top: 6000 },
		{ id: 'B1', kind: 'beam', type: 'B300x500', start: [0, 0], end: [6000, 0], elevation: 3000 },
		{ id: 'B2', kind: 'beam', type: 'B300x500', start: [0, 5000], end: [6000, 5000], elevation: 6000 },
		{ id: 'W1', kind: 'wall', type: 'W200', start: [6000, 0], end: [6000, 5000], bottom: 0, top: 3000 },
		{ id: 'S1', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 3000 },
		{ id: 'S2', kind: 'slab', type: 'S150', boundary: [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], elevation: 6000 },
	],
	additions: { slabOpenings: [{ id: 'O1', host: 'S1', x: 1000, y: 1000, xDim: 800, yDim: 600, rotation: 0 }] },
});

const OBJECTS = JSON.stringify({
	schema: 'saengine.objects/1',
	objects: [
		{ id: 'C400', kind: 'column', profile: { shape: 'rectangle', xDim: 400, yDim: 400 } },
		{ id: 'B300x500', kind: 'beam', profile: { shape: 'rectangle', xDim: 300, yDim: 500 } },
		{ id: 'W200', kind: 'wall', thickness: 200 },
		{ id: 'S150', kind: 'slab', thickness: 150 },
	],
});

const FLOOR_PLAN = JSON.stringify({ grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] } });

const MATERIALS = JSON.stringify({ materials: [{ id: 'M25', category: 'concrete', mechanical: { density: 2400 } }, { id: 'G60', category: 'rebar', mechanical: { density: 7850 } }] });

const CONTEXT = readMepContext({ bim: BIM, objects: OBJECTS, floorPlan: FLOOR_PLAN, materials: MATERIALS });

function tank(overrides: Partial<IEquipment> = {}): IEquipment {
	// x 1000..5000, y 1500..4500: on S1 and clear of its opening O1 (x 600..1400, y 700..1300).
	return { id: 'EQ1', name: 'Tank', kind: 'tank', story: 'L1', x: 3000, y: 3000, length: 4000, width: 3000, operatingWeight: 240, ...overrides };
}

function mep(overrides: Partial<IMep> = {}): IMep {
	return { ...newMep(), ...overrides };
}

suite('SAEngine MEP document', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the placeholder as an empty file and keeps unknown fields', () => {
		assert.deepStrictEqual(parseMep('{"schema": 1, "part": "mep"}'), { kind: 'placeholder', document: newMep() });
		assert.strictEqual(parseMep('{').kind, 'error');
		assert.strictEqual(parseMep('{"schema": "other"}').kind, 'error');
		const parsed = parseMep(JSON.stringify({ schema: MEP_SCHEMA_ID, equipment: [tank()], openings: [{ id: 'OP1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150 }], shafts: [{ id: 'SH1', outline: [[0, 0], 'x', [1, 1]], fromStory: 'L1', toStory: 'ROOF' }], extra: 7 }));
		assert.strictEqual(parsed.kind, 'document');
		const document = parsed.kind === 'document' ? parsed.document : newMep();
		assert.deepStrictEqual({ position: document.openings[0].position, outline: document.shafts[0].outline, models: document.ifcModels, extra: document.extra }, { position: {}, outline: [[0, 0], [1, 1]], models: [], extra: 7 });
		assert.strictEqual(serializeMep(document).endsWith('}\n'), true);
	});

	test('reads the building: stories by elevation, sections from the object types, the floor of a story', () => {
		const l1 = storyElements(CONTEXT, 'L1');
		assert.deepStrictEqual({
			stories: CONTEXT.stories.map(s => s.id),
			beam: CONTEXT.beams[0],
			slab: CONTEXT.slabs[0].thickness,
			unitWeight: Number(CONTEXT.concretes[0].unitWeight.toFixed(3)),
			concretes: CONTEXT.concretes.map(c => c.id),
			l1: { columns: l1.columns.map(c => c.id), beams: l1.beams.map(b => b.id), walls: l1.walls.map(w => w.id), slabs: l1.slabs.map(s => s.id), openings: l1.slabOpenings.map(o => o.id) },
			roof: storyElements(CONTEXT, 'ROOF').beams.map(b => b.id),
		}, {
			stories: ['BASE', 'L1', 'ROOF'],
			beam: { id: 'B1', start: [0, 0], end: [6000, 0], elevation: 3000, width: 300, depth: 500, type: 'B300x500' },
			slab: 150,
			// 2400 kg/m³ × 9.80665 m/s² = 23.536 kN/m³
			unitWeight: 23.536,
			concretes: ['M25'],
			// C1, C2 end at L1, C3 starts there; W1 stands below it.
			l1: { columns: ['C1', 'C2', 'C3'], beams: ['B1'], walls: ['W1'], slabs: ['S1'], openings: ['O1'] },
			roof: ['B2'],
		});
	});

	test('places openings on their hosts', () => {
		const onBeam = { id: 'OP1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { distance: 1500, elevation: 250 } };
		const onWall = { id: 'OP2', host: 'W1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { x: 2000, y: 1200 } };
		const inSlab = { id: 'OP3', host: 'S1', kind: 'opening', shape: 'rectangle', width: 600, height: 400, position: { x: 4000, y: 3000 } };
		assert.deepStrictEqual([openingPoint(onBeam, CONTEXT), openingPoint(onWall, CONTEXT), openingPoint(inSlab, CONTEXT), openingPoint({ ...onBeam, host: 'X9' }, CONTEXT)],
			[[1500, 0], [6000, 2000], [4000, 3000], undefined]);
		assert.deepStrictEqual(findHost(CONTEXT, 'W1')?.kind, 'wall');
	});

	test('loads: pressure over the footprint, plinth weight, per story', () => {
		const chiller = { ...tank({ id: 'EQ2', kind: 'chiller', length: 6000, width: 2300, operatingWeight: 85, plinth: { height: 150, material: 'M25' } }) };
		const document = mep({ equipment: [tank(), chiller, tank({ id: 'EQ3', story: 'ROOF', operatingWeight: 30 })] });
		assert.deepStrictEqual({
			// 240 kN over 4 m × 3 m = 20 kPa
			pressure: equipmentPressure(tank()),
			// 6.0 × 2.3 × 0.15 = 2.07 m³ × 23.536 kN/m³ = 48.72 kN
			plinth: Number(plinthWeight(chiller, CONTEXT).toFixed(2)),
			none: plinthWeight(tank(), CONTEXT),
			stories: storyLoads(document, CONTEXT).map(s => ({ ...s, plinths: Number(s.plinths.toFixed(2)) })),
		}, {
			pressure: 20,
			plinth: 48.72,
			none: 0,
			stories: [{ story: 'L1', count: 2, operating: 325, plinths: 48.72 }, { story: 'ROOF', count: 1, operating: 30, plinths: 0 }],
		});
	});

	test('new items: equipment on the slab clear of the others and of openings, sleeves at mid-span and mid-depth, a shaft to the top', () => {
		const document = mep();
		const first = newEquipment(document, CONTEXT, EQUIPMENT_PRESETS[0], 'L1');
		document.equipment.push(first);
		const second = newEquipment(document, CONTEXT, EQUIPMENT_PRESETS[0], 'L1');
		const o1 = bimOpeningOutline(CONTEXT.slabOpenings[0]);
		// A 2.2 x 1.5 m transformer beside a 4 x 3 m tank at (2000, 2500), x 0..4000, y 1000..4000: it
		// fits only in the 2 m wide strip x 4000..6000, turned (1.5 m along x, 2.2 m along y).
		const crowded = mep({ equipment: [tank({ x: 2000, y: 2500 })] });
		const transformer = newEquipment(crowded, CONTEXT, EQUIPMENT_PRESETS[4], 'L1');
		assert.deepStrictEqual({
			// The middle of the L1 floor (3000, 2500) puts the 4 x 3 m tank over O1; 500 mm up (on a
			// 250 mm grid, x first) it is clear: x 1000..5000, y 1500..4500.
			first: { id: first.id, x: first.x, y: first.y, rotation: first.rotation, story: first.story },
			firstOnSlab: equipmentSupport(first, CONTEXT),
			secondId: second.id,
			// No room left on S1 for a second tank: it goes where it is clear of the first and of O1.
			secondClear: !convexOverlap(equipmentOutline(first), equipmentOutline(second)) && !convexOverlap(o1, equipmentOutline(second)),
			transformer: { x: transformer.x, y: transformer.y, rotation: transformer.rotation, onSlab: equipmentSupport(transformer, CONTEXT).onSlab === equipmentSupport(transformer, CONTEXT).points },
			beam: newSleeve(document, CONTEXT, 'B1'),
			wall: newSleeve(document, CONTEXT, 'W1')?.position,
			slab: newSleeve(document, CONTEXT, 'S1')?.position,
			none: newSleeve(document, CONTEXT, 'C1'),
			shaft: newShaft(document, CONTEXT, 'L1'),
		}, {
			first: { id: 'EQ1', x: 3000, y: 3000, rotation: undefined, story: 'L1' },
			// 40 x 30 cells of 100 mm, all on S1
			firstOnSlab: { points: 1200, onSlab: 1200, slabs: ['S1'], overOpenings: [] },
			secondId: 'EQ2',
			secondClear: true,
			// x 4000..5500, y 1400..3600: against the tank's edge, nearest the middle (3000, 2500)
			transformer: { x: 4750, y: 2500, rotation: 90, onSlab: true },
			beam: { id: 'OP1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150, service: '', position: { distance: 3000, elevation: 250 } },
			wall: { x: 2500, y: 1500 },
			slab: { x: 3000, y: 2500 },
			none: undefined,
			// It cuts the L1 floor, so it starts at the story below (BASE, not cut).
			shaft: { id: 'SH1', outline: [[2250, 1750], [3750, 1750], [3750, 3250], [2250, 3250]], fromStory: 'BASE', toStory: 'ROOF', service: '' },
		});
		// Stories BASE, L1, ROOF: the floor of the story it starts at is not cut.
		assert.deepStrictEqual({
			fromBase: CONTEXT.stories.map(s => shaftOnStory(newShaft(document, CONTEXT, 'L1'), CONTEXT, s.id)),
			fromL1: CONTEXT.stories.map(s => shaftOnStory({ ...newShaft(document, CONTEXT, 'L1'), fromStory: 'L1' }, CONTEXT, s.id)),
			onTop: newShaft(document, CONTEXT, 'ROOF').fromStory,
		}, { fromBase: [false, true, true], fromL1: [false, false, true], onTop: 'L1' });
	});

	test('checks the file against the building model', () => {
		const document = mep({
			equipment: [
				tank(), tank({ x: 9000 }), tank({ id: 'EQ3', story: 'L9', operatingWeight: 0 }),
				tank({ id: 'EQ4', emptyWeight: 300, plinth: { height: 150 } }), tank({ id: 'EQ5', plinth: { height: 150, material: 'M99' } }),
				tank({ id: 'EQ6', y: 2500 }), tank({ id: 'EQ7', x: 4500 }), tank({ id: 'EQ 8', emptyWeight: 0 }),
			],
			openings: [
				{ id: 'OP1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 200, position: { distance: 3000, elevation: 50 } },
				{ id: 'OP2', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { distance: 5950, elevation: 250 } },
				{ id: 'OP3', host: 'S1', kind: 'opening', shape: 'rectangle', width: 600, height: 400, position: { x: 7000, y: 3000 } },
				{ id: 'OP4', host: 'X9', kind: 'sleeve', shape: 'circle', diameter: 150, position: {} },
				{ id: 'OP5', host: 'W1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { x: 2500, y: 1500 } },
				{ id: 'OP6', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { distance: 3000 } },
			],
			shafts: [
				{ id: 'SH1', outline: [[0, 0], [1000, 0]], fromStory: 'L1', toStory: 'L7' },
				{ id: 'EQ5', outline: [[0, 0], [1000, 0], [1000, 1000]], fromStory: 'ROOF', toStory: 'L1' },
			],
			ifcModels: [{ path: 'MEP/ducts.dwg', discipline: 'mechanical', visible: true }, { path: 'MEP/a.ifc', discipline: 'hvac', visible: true }],
		});
		const problems = checkMep(document, CONTEXT);
		assert.deepStrictEqual(problems.filter(p => /^EQ[67] /.test(p.message)).map(p => p.message), [
			// O1 (x 600..1400, y 700..1300) under cells x 1050..1350 (4) and y 1050..1250 (3) of the 40 x 30 at y 2500
			'EQ6 stands partly over opening O1 of slab S1: 12 of its 1200 load points are on no slab, and the rest carry its whole load.',
			// x 2500..6500 on a 6 m slab: the cells x 6050..6450 (5 columns of 30)
			'EQ7 stands partly off the slabs of L1: 150 of its 1200 load points are on no slab, and the rest carry its whole load.',
		]);
		assert.deepStrictEqual(problems.map(p => `${p.severity} ${p.path}`), [
			// EQ1 twice
			'error equipment.0.id',
			'error equipment.1.id',
			// x = 9 m is past the 6 m slab of L1
			'warning equipment.1.x',
			'error equipment.2.story',
			'error equipment.2.operatingWeight',
			// 300 kN empty > 240 kN operating; a plinth needs its concrete
			'error equipment.3.emptyWeight',
			'error equipment.3.plinth.material',
			// EQ5 is also the ID of a shaft (one ID space); 03 Materials has no M99
			'error equipment.4.id',
			'warning equipment.4.plinth.material',
			'warning equipment.5.x',
			'warning equipment.6.x',
			// a space in the ID, and an empty weight of 0 (the backend needs one above 0)
			'error equipment.7.id',
			'error equipment.7.emptyWeight',
			// a 200 mm sleeve centred 50 mm above the bottom pokes 50 mm out of the beam
			'error openings.0.position.elevation',
			// 5950 + 75 > 6000 mm
			'error openings.1.position.distance',
			'error openings.2.position.x',
			'error openings.3.host',
			// a beam sleeve needs its height above the bottom too
			'error openings.5.position.elevation',
			'error shafts.0.outline',
			'error shafts.0.toStory',
			'error shafts.1.id',
			// ROOF is above L1: the top story must be above the one it starts at
			'error shafts.1.toStory',
			'warning ifcModels.0.path',
			'error ifcModels.1.discipline',
		]);
	});

	test('a sleeve for a clash: the proposal of the backend under a free ID, none where it is to be rerouted', () => {
		const document = mep({ openings: [{ id: 'OP-B1-1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { distance: 500, elevation: 250 } }] });
		const sleeve = { id: 'OP-B1-1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 175, position: { distance: 2000, elevation: 300 }, service: 'DN100 drain' };
		const clash = { id: 'CL1', mep: 'guid-1', mepName: 'DN100 drain', structural: 'B1', kind: 'hard', status: 'clash' as const, point: [2000, 40, 2800] as [number, number, number], size: 114, sleeve };
		assert.deepStrictEqual({
			proposed: sleeveForClash(document, clash),
			alongTheBeam: sleeveForClash(document, { ...clash, sleeve: undefined, size: undefined, note: 'runs along beam B1: reroute' }),
		}, { proposed: { ...sleeve, id: 'OP1' }, alongTheBeam: undefined });
	});

	test('reads the report defensively and sums it up', () => {
		const report = readMepReport({
			equipment: [{ id: 'EQ1', story: 'L1', load: 240, pressure: 20 }, { story: 'L1' }],
			stories: [{ story: 'L1', count: 1, load: 240 }],
			openings: [
				{ id: 'OP1', utilisation: 1.2 }, { id: 'OP2', utilisation: 0.4, ok: true }, { id: 'OP3', ok: false }, { id: 'OP4', utilisation: 0, ok: true, checked: false },
				// Only its size and spacing were checked: no analysis results
				{ id: 'OP5', utilisation: 0.6, ok: true, checked: true, note: 'OP5: no analysis results; shear and flexure at it are not checked' },
				{ id: 'OP6', utilisation: 0.5, ok: true, checked: true, strengthChecked: true, checks: [{ name: 'Depth', note: 'within h/4' }] },
			],
			clashes: [{ mep: 'g1', structural: 'B1', status: 'clash', kind: 'hard', point: [1, 2, 3] }, { mep: 'g2', structural: 'S1', status: 'coordinated', opening: 'OP2' }, { id: 'X3', mep: 'g3', structural: 'C1', status: 'clash', kind: 'clearance' }],
			notes: ['n', 3],
		});
		assert.ok(report);
		assert.deepStrictEqual({
			equipment: report.equipment.length,
			ok: report.openings.map(o => `${o.ok} ${o.checked} ${o.strengthChecked} ${o.utilisation}`),
			partly: report.openings.filter(isPartlyChecked).map(o => o.id),
			clashes: report.clashes.map(c => `${c.id} ${c.status} ${c.point?.join(',') ?? '-'}`),
			notes: report.notes,
		}, {
			equipment: 1,
			ok: ['false true true 1.2', 'true true true 0.4', 'false true true null', 'true false false null', 'true true false 0.6', 'true true true 0.5'],
			partly: ['OP4', 'OP5'],
			clashes: ['CL1 clash 1,2,3', 'CL2 coordinated -', 'X3 clash -'], notes: ['n'],
		});
		const document = mep({ equipment: [tank(), tank({ id: 'EQ2' })], openings: [] });
		assert.strictEqual(mepSummary(document, report), '2 equipment · 2 openings fail · 2 openings not fully checked · 1 clash');
		assert.strictEqual(mepSummary(mep({ equipment: [tank()], shafts: [newShaft(mep(), CONTEXT, 'L1')] }), undefined), '1 equipment · 1 shaft');
		const summary = mepSummaryFile(document, report, '{}', new Date(Date.UTC(2026, 9, 17)), { bim: BIM, objects: OBJECTS, materials: MATERIALS });
		assert.deepStrictEqual({ ...summary, source: Object.entries(summary.source).map(([part, stamp]) => `${part} ${stamp.length}`) }, {
			equipment: 2, openings: 0, openingsFailed: 2, openingsPartial: 2, clashes: 3, clashesOpen: 1, computed: '2026-10-17T00:00:00.000Z',
			// SHA-1 stamps (40 hex digits); no settings file given: ''
			source: ['settings 0', 'materials 40', 'objects 40', 'bim 40', 'mep 40'],
		});
		assert.strictEqual(readMepReport([]), undefined);
		assert.deepStrictEqual(readSleeveSuggestions({ openings: [{ id: 'OP9', host: 'B1', position: { distance: 10 } }, { id: 'bad' }] })?.openings.map(o => `${o.id} ${o.kind} ${o.shape}`), ['OP9 sleeve circle']);
	});

	test('guesses the discipline of an IFC model from its name', () => {
		assert.deepStrictEqual(['07 MEP/IFC/Plumbing.ifc', 'Sprinklers.ifc', 'Lighting-L2.ifc', 'HVAC.ifc'].map(guessDiscipline), ['plumbing', 'fire', 'electrical', 'mechanical']);
	});

	test('draws a story: its floor, equipment, shafts, sleeves and clashes', () => {
		const container = mainWindow.document.createElement('div');
		const document = mep({
			equipment: [tank(), tank({ id: 'EQ2', story: 'ROOF' })],
			openings: [{ id: 'OP1', host: 'B1', kind: 'sleeve', shape: 'circle', diameter: 150, position: { distance: 1500, elevation: 250 } }, { id: 'OP2', host: 'B2', kind: 'sleeve', shape: 'circle', diameter: 150, position: { distance: 1500, elevation: 250 } }],
			shafts: [newShaft(mep(), CONTEXT, 'L1')],
		});
		const view = renderPlan(container, document, CONTEXT, { width: 600, height: 400, story: 'L1', selection: { kind: 'equipment', index: 0 }, clashes: [{ id: 'CL1', point: [100, 100], open: true }] });
		const ids = (selector: string, attribute: string) => [...container.querySelectorAll(selector)].map(e => e.getAttribute(attribute));
		assert.deepStrictEqual({
			equipment: ids('[data-equipment]', 'data-equipment'),
			selected: ids('.mep-equipment.selected', 'data-equipment'),
			openings: ids('[data-opening]', 'data-opening'),
			shafts: ids('[data-shaft]', 'data-shaft'),
			elements: ids('[data-element]', 'data-element'),
			clashes: ids('[data-clash]', 'data-clash'),
			bimOpenings: container.querySelectorAll('.mep-bim-opening').length,
			positiveScale: view.scale > 0,
		}, {
			equipment: ['0'],
			selected: ['0'],
			openings: ['0'],
			shafts: ['0'],
			elements: ['S1', 'W1', 'B1', 'C1', 'C2', 'C3'],
			clashes: ['CL1'],
			bimOpenings: 1,
			positiveScale: true,
		});
	});
});
