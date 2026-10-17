/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	applyPileLayout, applyProposal, capSize, carriedAlready, checkSubstructure, foundationOutlines, governingCheck, IFoundation, importFoundations, ISiteContext, ISubstructure, maxPressure, minPileSpacing, newFooting, newPileCap, newRaft, newSubstructure, newTieBeam, parseIdList, parseMesh, parseSubstructure, pileFactorsUsed, pileLayout, pilePositions,
	proposalFor, readSiteContext, readSizingProposal, readSubstructureReport, SUBSTRUCTURE_SCHEMA_ID, substructureSummary, substructureSummaryFile, uncoveredColumns, utilisationBand,
} from '../../browser/substructureDocument.js';
import { renderPlan, renderRaftHeatMap } from '../../browser/substructurePlan.js';

/*
 * Synthetic data only: a two-bay frame of 400 x 600 columns on a 6 m x 5 m grid, one column
 * on the first floor (not a base), and two boreholes. Expected values are worked by hand.
 */

const BIM = JSON.stringify({
	schema: 'saengine.bim/2',
	stories: [{ id: 'BASE', elevation: 0 }, { id: 'L1', elevation: 3000 }],
	elements: [
		{ id: 'C1', kind: 'column', type: 'C400x600', position: [0, 0], bottom: 0, top: 3000 },
		{ id: 'C2', kind: 'column', type: 'C400x600', position: [6000, 0], bottom: 0, top: 3000, rotation: 90 },
		{ id: 'C3', kind: 'column', type: 'C500R', position: [0, 5000], bottom: 0, top: 3000 },
		{ id: 'C4', kind: 'column', type: 'C400x600', position: [6000, 5000], bottom: 0, top: 3000 },
		{ id: 'C9', kind: 'column', type: 'C400x600', position: [3000, 0], bottom: 3000, top: 6000 },
		{ id: 'W1', kind: 'wall', type: 'W200', start: [6000, 0], end: [6000, 5000], bottom: 0, top: 3000 },
	],
});

const OBJECTS = JSON.stringify({
	schema: 'saengine.objects/1',
	objects: [
		{ id: 'C400x600', kind: 'column', material: 'M25', profile: { shape: 'rectangle', xDim: 400, yDim: 600 } },
		{ id: 'C500R', kind: 'column', material: 'M25', profile: { shape: 'circle', radius: 250 } },
		{ id: 'B300x500', name: 'Beam 300x500', kind: 'beam', material: 'M25', profile: { shape: 'rectangle', xDim: 300, yDim: 500 } },
		{ id: 'W200', kind: 'wall', material: 'M25', thickness: 200 },
		{ id: 'F1515', kind: 'footing', material: 'M25', length: 1500, width: 1500, thickness: 450, reinforcement: { material: 'G60', cover: 75 } },
	],
});

const CONTEXT: ISiteContext = readSiteContext({
	bim: BIM,
	objects: OBJECTS,
	floorPlan: JSON.stringify({ grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] } }),
	settings: JSON.stringify({ foundation: { groundLevel: -300 } }),
	soil: JSON.stringify({ boreholes: [{ id: 'BH-1', x: -2000, y: -2000 }, { id: 'BH-2', x: 8000, y: 7000 }] }),
	materials: JSON.stringify({ materials: [{ id: 'M25', category: 'concrete' }, { id: 'G60', category: 'rebar' }] }),
});

function document(foundations: IFoundation[] = []): ISubstructure {
	return { ...newSubstructure(), foundations, pileTypes: [{ id: 'P1', kind: 'bored', diameter: 500, length: 18000, material: 'M25' }] };
}

suite('SAEngine - Substructure', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the placeholder, a document and broken files', () => {
		const parsed = parseSubstructure(JSON.stringify({ schema: SUBSTRUCTURE_SCHEMA_ID, foundations: [{ id: 'F1', type: 'isolated', center: 'x', piles: [[0, 0], 'bad'] }], extra: 1 }));
		assert.deepStrictEqual({
			placeholder: parseSubstructure('{"schema": 1, "part": "substructure"}').kind,
			empty: parseSubstructure('').kind,
			document: parsed.kind === 'document' ? { f: parsed.document.foundations, lists: [parsed.document.pileTypes, parsed.document.tieBeams], design: parsed.document.design, kept: parsed.document.extra } : undefined,
			invalid: parseSubstructure('{').kind,
			other: parseSubstructure('{"schema": "saengine.bim/2"}').kind,
			badList: parseSubstructure(JSON.stringify({ schema: SUBSTRUCTURE_SCHEMA_ID, foundations: {} })).kind,
		}, {
			placeholder: 'placeholder',
			empty: 'placeholder',
			document: { f: [{ id: 'F1', type: 'isolated', piles: [[0, 0]] }], lists: [[], []], design: {}, kept: 1 },
			invalid: 'error',
			other: 'error',
			badList: 'error',
		});
	});

	test('reads the column bases, walls, grid, boreholes and object types of the project', () => {
		assert.deepStrictEqual({
			columns: CONTEXT.columns.map(c => [c.id, c.x, c.y, c.xDim, c.yDim, c.circle, c.rotation]),
			walls: CONTEXT.walls,
			grid: CONTEXT.grids.x.map(g => g.label).concat(CONTEXT.grids.y.map(g => g.label)),
			boreholes: CONTEXT.boreholes.map(b => b.id),
			ground: CONTEXT.groundLevel,
			beams: CONTEXT.beamTypes,
			materials: CONTEXT.materials,
			defaultMaterial: CONTEXT.defaultMaterial,
			bars: CONTEXT.barMaterial,
			rebar: CONTEXT.barMaterials,
		}, {
			// C9 stands on the first floor: not a base.
			columns: [['C1', 0, 0, 400, 600, false, 0], ['C2', 6000, 0, 400, 600, false, 90], ['C3', 0, 5000, 500, 500, true, 0], ['C4', 6000, 5000, 400, 600, false, 0]],
			walls: [{ id: 'W1', start: [6000, 0], end: [6000, 5000], thickness: 200 }],
			grid: ['A', 'B', '1', '2'],
			boreholes: ['BH-1', 'BH-2'],
			ground: -300,
			beams: [{ id: 'B300x500', name: 'Beam 300x500' }],
			materials: ['M25'],
			defaultMaterial: 'M25',
			bars: 'G60',
			rebar: ['G60'],
		});
	});

	test('pile layouts are 3 diameters apart and the cap leaves 150 mm beyond the piles', () => {
		const d = 500;
		const layouts = [2, 3, 4, 5, 6, 9].map(n => {
			const piles = pileLayout(n, d);
			return { n: piles.length, spacing: Math.round(minPileSpacing(piles)!), cap: capSize(piles, d) };
		});
		assert.deepStrictEqual(layouts, [
			// 2: ±750 along x; cap 2 (750 + 250 + 150) = 2300 by 2 (250 + 150) = 800; thickness max(600, 2 D) = 1000.
			{ n: 2, spacing: 1500, cap: { length: 2300, width: 800, thickness: 1000 } },
			// 3: a triangle of side 1500, its vertices 866 from the centre: y from -433 to 866.
			{ n: 3, spacing: 1500, cap: { length: 2300, width: 2550, thickness: 1000 } },
			{ n: 4, spacing: 1500, cap: { length: 2300, width: 2300, thickness: 1000 } },
			// 5: the corners 1500 / √2 = 1061 along each axis from the centre pile.
			{ n: 5, spacing: 1500, cap: { length: 2950, width: 2950, thickness: 1000 } },
			{ n: 6, spacing: 1500, cap: { length: 3800, width: 2300, thickness: 1000 } },
			{ n: 9, spacing: 1500, cap: { length: 3800, width: 3800, thickness: 1000 } },
		]);
	});

	test('new footings, pile caps, rafts and tie beams', () => {
		const doc = document();
		const [c1, c2, c3, c4] = CONTEXT.columns;
		const isolated = newFooting(doc, CONTEXT, [c1]);
		doc.foundations.push(isolated);
		const combined = newFooting(doc, CONTEXT, [c1, c2]);
		doc.foundations.push(combined);
		const cap = newPileCap(doc, CONTEXT, [c3], doc.pileTypes[0], 4);
		doc.foundations.push(cap);
		const raft = newRaft(doc, CONTEXT, [c1, c2, c3, c4])!;
		const tie = newTieBeam(doc, CONTEXT, 'F1', 'F3');
		assert.deepStrictEqual({
			isolated: [isolated.id, isolated.type, isolated.columns, isolated.length, isolated.width, isolated.thickness, isolated.material, isolated.reinforcement],
			// Two columns 6 m apart: 6000 + 2 × 750 = 7500 long, 1500 wide, centred between them.
			combined: [combined.id, combined.type, combined.center, combined.rotation, combined.length, combined.width, combined.thickness],
			cap: [cap.id, cap.pileType, cap.piles?.length, cap.length, cap.width, cap.thickness],
			capPiles: pilePositions(cap, CONTEXT),
			raft: [raft.id, raft.outline, raft.thickness],
			tie,
		}, {
			isolated: ['F1', 'isolated', ['C1'], 1500, 1500, 450, 'M25', { material: 'G60', cover: 75, bottomX: { dia: 12, spacing: 150 }, bottomY: { dia: 12, spacing: 150 } }],
			combined: ['F2', 'combined', [3000, 0], undefined, 7500, 1500, 600],
			cap: ['F3', 'P1', 4, 2300, 2300, 1000],
			capPiles: [[-750, 4250], [750, 4250], [750, 5750], [-750, 5750]],
			raft: ['F4', [[-1000, -1000], [7000, -1000], [7000, 6000], [-1000, 6000]], 600],
			tie: { id: 'TB1', from: 'F1', to: 'F3', type: 'B300x500' },
		});
	});

	test('footprints: a rotated footing, a strip along its path, a raft outline', () => {
		const round = (outlines: number[][][]) => outlines.map(o => o.map(p => p.map(v => Math.round(v) + 0)));
		assert.deepStrictEqual({
			rotated: round(foundationOutlines({ id: 'F1', type: 'isolated', center: [1000, 1000], rotation: 90, length: 2000, width: 1000, thickness: 400 }, CONTEXT)),
			strip: round(foundationOutlines({ id: 'S1', type: 'strip', path: [[0, 0], [4000, 0]], width: 1000, thickness: 400 }, CONTEXT)),
			raft: foundationOutlines({ id: 'R1', type: 'raft', outline: [[0, 0], [1, 0]], thickness: 600 }, CONTEXT),
			noSize: foundationOutlines({ id: 'F2', type: 'isolated', columns: ['C1'] }, CONTEXT),
		}, {
			rotated: [[[1500, 0], [1500, 2000], [500, 2000], [500, 0]]],
			strip: [[[0, 500], [4000, 500], [4000, -500], [0, -500]]],
			raft: [],
			noSize: [],
		});
	});

	test('checks the document against the building model and the backend schema', () => {
		const doc = document([
			{ id: 'F1', type: 'isolated', columns: ['C1'], length: 1500, width: 1500, thickness: 450 },
			{ id: 'F1', type: 'isolated', columns: ['C1', 'C7'], length: 0, width: 1500, thickness: 450 },
			{ id: 'F3', type: 'pileCap', columns: ['C3'], length: 1600, width: 1600, thickness: 900, pileType: 'P1', piles: [[-500, 0], [500, 0]] },
			{ id: 'F4', type: 'pileCap', columns: ['C4'], length: 2300, width: 2300, thickness: 1000, pileType: 'P9', piles: [] },
			{ id: 'R1', type: 'raft', thickness: 600, outline: [[0, 0], [1, 1]] },
			// A pile 700 mm off a 1600 mm cap's centre: its side 950 mm out, past the 800 mm edge.
			{ id: 'F5', type: 'pileCap', center: [0, 0], length: 1600, width: 1600, thickness: 900, pileType: 'P1', piles: [[700, 0]] },
			// Driven 400 mm piles 900 apart: end bearing asks more than max(750, 2.5 × 400) = 1000.
			{ id: 'F6', type: 'pileCap', center: [3000, 3000], length: 2000, width: 1200, thickness: 900, pileType: 'P2', piles: [[-450, 0], [450, 0]] },
			{ id: 'F7', type: 'isolated', center: [3000, 0], length: 1500, width: 1500, thickness: 450, reinforcement: { cover: 0 } },
			{ id: 'S1', type: 'strip', columns: ['W1'], path: [[6000, 0], [6000, 5000]], width: 900, thickness: 450 },
			{ id: 'F8', type: 'isolated', columns: ['W1'], length: 1500, width: 1500, thickness: 450 },
		]);
		doc.pileTypes.push({ id: 'P2', kind: 'driven', diameter: 400, length: 12000 });
		doc.tieBeams.push({ id: 'TB1', from: 'F1', to: 'F9', type: 'B999' }, { id: 'TB2', from: 'F3', to: 'F4' });
		doc.design = { factorOfSafety: { pileCompression: 12 }, raftMeshSize: 9000 };
		const problems = checkSubstructure(doc, CONTEXT);
		assert.deepStrictEqual({
			problems: problems.map(p => `${p.severity} ${p.path}`),
			bored: problems.find(p => p.path === 'foundations.2.piles')?.message,
			driven: problems.find(p => p.path === 'foundations.6.piles')?.message,
			uncovered: uncoveredColumns(doc, CONTEXT).map(c => c.id),
			carried: carriedAlready(doc, ['C1', 'C2', 'W1']),
		}, {
			problems: [
				'error foundations.1.id',
				// C1 is on F1 already: the backend refuses the whole file.
				'error foundations.1.columns',
				'warning foundations.1.columns',
				'error foundations.1.length',
				// Piles 1000 mm apart: less than 3 × 500.
				'warning foundations.2.piles',
				// A pile's side 50 mm from the cap's edge (800 - 500 - 250): less than 100.
				'warning foundations.2.length',
				'error foundations.3.pileType',
				'error foundations.3.piles',
				'error foundations.4.outline',
				'error foundations.5.piles',
				'warning foundations.6.piles',
				'error foundations.7.reinforcement.material',
				'error foundations.7.reinforcement.cover',
				// A wall on an isolated footing, and on the strip already.
				'warning foundations.9.columns',
				'error foundations.9.columns',
				'error pileTypes.1.material',
				'error tieBeams.0.to',
				'warning tieBeams.0.type',
				'error tieBeams.1.type',
				'error design.factorOfSafety.pileCompression',
				'error design.raftMeshSize',
			],
			bored: 'F3: bored piles 1000 mm apart, less than 3 diameters (1500 mm), the spacing BNBC 2020 Part 6 Sec 3.10.1.30 generally asks for driven friction piles; check that their zones of support do not overlap.',
			driven: 'F6: driven piles 900 mm apart; BNBC 2020 Part 6 Sec 3.10.1.30 asks end-bearing driven piles to be more than 1000 mm apart (the greater of 750 mm and 2.5 diameters), friction piles generally 3 diameters (1200 mm).',
			uncovered: ['C2'],
			carried: [{ id: 'C1', foundation: 'F1' }, { id: 'W1', foundation: 'S1' }],
		});
	});

	test('reads bar meshes and column lists', () => {
		assert.deepStrictEqual([
			parseMesh('12@150'), parseMesh(' T16 @ 200 '), parseMesh('Ø10/125'), parseMesh(''), parseMesh('12-150').error !== undefined, parseMesh('25@40').error !== undefined,
			parseIdList('C1, C2 C3;C1'),
		], [
			{ value: { dia: 12, spacing: 150 } }, { value: { dia: 16, spacing: 200 } }, { value: { dia: 10, spacing: 125 } }, {}, true, true,
			['C1', 'C2', 'C3'],
		]);
	});

	test('applies a pile layout and a sizing proposal by the columns it carries', () => {
		const reinforcement = { material: 'G60', cover: 75, bottomX: { dia: 16, spacing: 150 } };
		// F1 is an unsaved pile cap; the backend, which reads the saved file, proposes "F1" for C4.
		const doc = document([
			{ id: 'F1', type: 'pileCap', columns: ['C1'], pileType: 'P1', piles: [], thickness: 800 },
			{ id: 'F2', type: 'isolated', columns: ['C2'], length: 1500, width: 1500, thickness: 450, material: 'M25', reinforcement },
			{ id: 'F3', type: 'isolated', columns: ['C3'], length: 1500, width: 1500, thickness: 450 },
		]);
		doc.tieBeams.push({ id: 'TB1', from: 'F2', to: 'F3', type: 'B300x500' }, { id: 'TB2', from: 'F1', to: 'F3', type: 'B300x500' });
		applyPileLayout(doc.foundations[0], doc.pileTypes[0], 2);
		const proposal = readSizingProposal({
			foundations: [
				{ id: 'F1', type: 'isolated', columns: ['C4'], length: 1800, width: 1800, thickness: 450 },
				{ id: 'F2', type: 'combined', columns: ['C2', 'C3'], center: [3000, 2500], length: 7500, width: 2000, thickness: 600 },
			],
			pileTypes: [{ id: 'P1', kind: 'driven', diameter: 400, length: 12000, material: 'M25' }],
			notes: ['sized for qa 150 kPa'],
		})!;
		const changed = applyProposal(doc, proposal);
		assert.deepStrictEqual({
			cap: doc.foundations[0],
			changed,
			ids: doc.foundations.map(f => f.id),
			// F2 and F3 become one combined footing, which keeps F2's id, concrete and bars.
			f2: doc.foundations[1],
			ties: doc.tieBeams,
			// A different pile type with a taken id comes in under a free one.
			pileTypes: doc.pileTypes.map(p => `${p.id} ${p.kind}`),
			notes: proposal.notes,
			// A backend that sized more than asked: only the columns asked about are kept.
			only: proposalFor(proposal, ['C4']).foundations.map(f => f.columns),
			notAProposal: readSizingProposal({ text: 'no' }),
		}, {
			cap: { id: 'F1', type: 'pileCap', columns: ['C1'], pileType: 'P1', piles: [[-750, 0], [750, 0]], length: 2300, width: 800, thickness: 1000 },
			changed: ['F4', 'F2'],
			ids: ['F1', 'F2', 'F4'],
			f2: { id: 'F2', type: 'combined', columns: ['C2', 'C3'], center: [3000, 2500], length: 7500, width: 2000, thickness: 600, material: 'M25', reinforcement },
			ties: [{ id: 'TB2', from: 'F1', to: 'F2', type: 'B300x500' }],
			pileTypes: ['P1 bored', 'P2 driven'],
			notes: ['sized for qa 150 kPa'],
			only: [['C4']],
			notAProposal: undefined,
		});
	});

	test('imports only the footings the backend added to the saved file', () => {
		// In the editor: F1 lengthened (unsaved), F5 deleted (unsaved), F6 and F7 added (unsaved).
		const doc = document([
			{ id: 'F1', type: 'isolated', columns: ['C1'], length: 2500, width: 2500, thickness: 450 },
			{ id: 'F6', type: 'isolated', columns: ['C3'], length: 1500, width: 1500, thickness: 450 },
			{ id: 'F7', type: 'isolated', columns: ['C4'], length: 1500, width: 1500, thickness: 450 },
		]);
		// The backend returns the saved file (F1, F5) with the building model's footings added.
		const imported = readSizingProposal({
			substructure: {
				schema: SUBSTRUCTURE_SCHEMA_ID,
				foundations: [
					{ id: 'F1', type: 'isolated', columns: ['C1'], length: 1800, width: 1800, thickness: 450 },
					{ id: 'F5', type: 'isolated', columns: ['C2'], length: 1500, width: 1500, thickness: 450 },
					{ id: 'F6', type: 'isolated', columns: ['C3'], length: 1600, width: 1600, thickness: 450 },
					{ id: 'F7', type: 'isolated', columns: ['C2'], length: 1700, width: 1700, thickness: 450 },
					{ id: 'F8', type: 'pileCap', center: [3000, 3000], length: 1000, width: 1000, thickness: 800, pileType: 'P1', piles: [[0, 0]] },
				],
				pileTypes: [{ id: 'P1', kind: 'driven', diameter: 400, length: 12000, material: 'M25' }],
			},
			notes: [], count: 3,
		})!;
		const result = importFoundations(doc, imported, new Set(['F1', 'F5']));
		assert.deepStrictEqual({
			result,
			ids: doc.foundations.map(f => `${f.id} ${f.columns?.join() ?? ''} ${f.length}`),
			f8PileType: doc.foundations.find(f => f.id === 'F8')?.pileType,
			pileTypes: doc.pileTypes.map(p => p.id),
		}, {
			// F6 stands under C3, which F6 here carries; F7's id is taken here: it becomes F2.
			result: { added: ['F2', 'F8'], skipped: ['F6'] },
			ids: ['F1 C1 2500', 'F6 C3 1500', 'F7 C4 1500', 'F2 C2 1700', 'F8  1000'],
			f8PileType: 'P2',
			pileTypes: ['P1', 'P2'],
		});
	});

	test('reads the design report and sums it up for the status line', () => {
		const raw = {
			foundations: [
				{
					id: 'F1', type: 'isolated', utilisation: 1.12, ok: false,
					checks: [
						{ name: 'Bearing (service)', demand: 142, capacity: 150, unit: 'kPa', utilisation: 0.947, combination: 'D + L', ok: true, note: '' },
						{ name: 'Punching shear', demand: 560, capacity: 500, unit: 'kN', utilisation: 1.12, combination: '1.2D + 1.6L', ok: false, note: '', flag: false },
					],
					pressure: { net: 142, qa: 150, combination: 'D + L', source: 'BH-1' },
				},
				{
					id: 'F3', type: 'pileCap', checks: [{ name: 'Minimum steel', demand: 1, capacity: 2, unit: '', utilisation: 2, ok: false, note: '', flag: true }], ok: true,
					piles: [{ index: 1, u: -750, v: 0, serviceMax: 400.5, serviceMin: -12, strengthMax: 560 }],
					capacity: { pileType: 'P1', borehole: 'BH-1', Qs: 600, Qb: 400, Qult: 1000, Qa: 400, Ta: 240 },
				},
			],
			tieBeams: [{ id: 'TB1', type: 'tieBeam', checks: [], utilisation: 0.3, ok: true }],
			skipped: [{ id: 'R1', type: 'raft', reason: 'rafts are not designed yet' }],
			summary: { checked: 3, passed: 2, failed: 1, maxUtilisation: 1.12, governing: 'F1' },
			notes: ['C2: no foundation under it'],
			method: ['ACI 318-19'],
			sources: { substructure: 'abc', soil: '', other: 1 },
		};
		const report = readSubstructureReport(raw)!;
		const doc = document([{ id: 'F1', type: 'isolated', columns: ['C1'] }, { id: 'F3', type: 'pileCap', columns: ['C3'] }]);
		assert.deepStrictEqual({
			f1: [report.foundations[0].utilisation, report.foundations[0].ok, report.foundations[0].pressure],
			// A flagged check does not count towards the utilisation.
			f3: [report.foundations[1].utilisation, report.foundations[1].ok, report.foundations[1].piles],
			capacities: report.pileCapacities,
			ties: report.tieBeams.map(t => t.id),
			skipped: report.skipped,
			summary: report.summary,
			text: substructureSummary(doc, report),
			noReport: substructureSummary(doc, undefined),
			bands: [0.5, 0.9, 1, 1.001, null].map(utilisationBand),
			notReport: readSubstructureReport({ checked: 1 }),
			// A check only reported (a deep cap's flexure) never governs.
			governing: report.foundations.map(f => governingCheck(f)?.name),
			// The part list's summary keeps the stamps of the files the checks read.
			file: substructureSummaryFile(doc, report, new Date(0)),
		}, {
			f1: [1.12, false, { max: 142, allowable: 150, combination: 'D + L', source: 'BH-1' }],
			f3: [null, true, [{ number: 1, u: -750, v: 0, compression: 400.5, least: -12, factored: 560, capacity: undefined, utilisation: undefined, combination: undefined }]],
			capacities: [{ pileType: 'P1', borehole: 'BH-1', skin: 600, base: 400, ultimate: 1000, compression: 400, uplift: 240, method: undefined, note: undefined }],
			ties: ['TB1'],
			skipped: [{ id: 'R1', type: 'raft', reason: 'rafts are not designed yet' }],
			summary: { checked: 3, passed: 2, failed: 1, maxUtilisation: 1.12, governing: 'F1' },
			text: '2 foundations · 1 fail · max pressure 142 kPa (qa 150)',
			noReport: '2 foundations',
			bands: ['ok', 'warn', 'warn', 'fail', 'none'],
			notReport: undefined,
			governing: ['Punching shear', undefined],
			file: { foundations: 2, checked: 3, passed: 2, failed: 1, maxUtilisation: 1.12, governing: 'F1', computed: '1970-01-01T00:00:00.000Z', source: { substructure: 'abc', soil: '' } },
		});
	});

	test('the pile factors of safety the design uses, as the backend raises them', () => {
		assert.deepStrictEqual([
			pileFactorsUsed({}),
			pileFactorsUsed({ factorOfSafety: { pileLoadTest: true } }),
			pileFactorsUsed({ factorOfSafety: { pileCompression: 1.5, pileLoadTest: true } }),
			pileFactorsUsed({ factorOfSafety: { pileCompression: 3.2, pileUplift: 3 } }),
			pileFactorsUsed({ pileCapacity: 'bnbcSpt', factorOfSafety: { pileLoadTest: true } }),
		], [
			// BNBC 2020 Part 6 Sec 3.10.1.18: at least 3.0 without a load test at the site, 2.0 with one.
			{ compression: 3, uplift: 2.5, given: 2.5, raised: 'loadTest' },
			{ compression: 2.5, uplift: 2.5, given: 2.5, raised: undefined },
			{ compression: 2, uplift: 2.5, given: 1.5, raised: 'loadTest' },
			{ compression: 3.2, uplift: 3, given: 3.2, raised: undefined },
			{ compression: 3.5, uplift: 3.5, given: 2.5, raised: 'spt' },
		]);
	});

	test('reads the raft and pile cap results of the backend', () => {
		const report = readSubstructureReport({
			foundations: [
				{
					id: 'R1', type: 'raft', checks: [], utilisation: 0.5, ok: true, pressure: { net: 75.5, qa: 150 },
					raft: { nodes: [[0, 0], [500, 0]], elements: [], pressure: [80, 95.5], settlement: [12, 14.25], meshSize: 500, summary: { maxPressure: 95.5, maxPressureCombination: 'D + L', maxSettlement: 14.25, maxDifferential: 2.25, maxAngularDistortion: 0.0045 } },
				},
				{
					id: 'PC1', type: 'pileCap', checks: [], utilisation: 0.5, ok: true, sizes: { pileType: 'P1' },
					pile: { Qs: 600, Qb: 400, Qult: 1000, Qa: 400, Ta: 240, methodText: 'per layer' }, capacityTable: { borehole: 'BH-2', rows: [] },
				},
			],
		})!;
		assert.deepStrictEqual({ raft: report.foundations[0].raft, capacity: report.pileCapacities, max: maxPressure(report) }, {
			raft: {
				points: [{ x: 0, y: 0, pressure: 80, settlement: 12 }, { x: 500, y: 0, pressure: 95.5, settlement: 14.25 }], meshSize: 500,
				maxPressure: 95.5, allowablePressure: undefined, maxSettlement: 14.25, differentialSettlement: 2.25, angularDistortion: 0.0045, combination: 'D + L',
			},
			capacity: [{ pileType: 'P1', borehole: 'BH-2', skin: 600, base: 400, ultimate: 1000, compression: 400, uplift: 240, method: 'per layer', note: undefined }],
			// The raft's net pressure against qa, not its gross maximum (95.5 with the overburden).
			max: { pressure: 75.5, allowable: 150, id: 'R1' },
		});
	});

	test('draws the plan and a raft heat map', () => {
		const container = mainWindow.document.createElement('div');
		const doc = document([
			{ id: 'F1', type: 'isolated', columns: ['C1'], length: 1500, width: 1500, thickness: 450 },
			{ id: 'F2', type: 'pileCap', columns: ['C3'], length: 2300, width: 2300, thickness: 1000, pileType: 'P1', piles: pileLayout(4, 500) },
			{ id: 'S1', type: 'strip', path: [[6000, 0], [6000, 5000]], width: 1000, thickness: 450 },
		]);
		doc.tieBeams.push({ id: 'TB1', from: 'F1', to: 'F2', type: 'B300x500' });
		const plan = renderPlan(container, doc, CONTEXT, { width: 800, height: 600, selectedFoundations: new Set([1]), selectedColumns: new Set(['C4']), proposals: [{ id: 'F1', type: 'isolated', columns: ['C1'], length: 2000, width: 2000, thickness: 500 }], bands: new Map([['F1', 'fail' as const]]) });
		const raftContainer = mainWindow.document.createElement('div');
		const range = renderRaftHeatMap(raftContainer, { id: 'R1', type: 'raft', outline: [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], thickness: 600 }, {
			points: [{ x: 250, y: 250, pressure: 80 }, { x: 750, y: 250, pressure: 100 }, { x: 250, y: 750, pressure: 120 }, { x: 750, y: 750, pressure: 140 }],
		}, CONTEXT, 'pressure', { width: 300, height: 200 });
		assert.deepStrictEqual({
			foundations: plan.querySelectorAll('[data-foundation]').length,
			selected: plan.querySelectorAll('.sub-foundation.selected').length,
			failing: plan.querySelectorAll('.sub-foundation.band-fail').length,
			piles: plan.querySelectorAll('.sub-pile').length,
			columns: plan.querySelectorAll('[data-column]').length,
			selectedColumns: plan.querySelectorAll('.sub-column.selected').length,
			ties: plan.querySelectorAll('[data-tie]').length,
			boreholes: plan.querySelectorAll('.sub-borehole').length,
			grid: plan.querySelectorAll('.sub-grid-line').length,
			proposals: plan.querySelectorAll('.sub-proposal').length,
			heatCells: raftContainer.querySelectorAll('.sub-heat-cell').length,
			hottest: raftContainer.querySelectorAll('.sub-heat-7').length,
			range,
		}, {
			foundations: 3, selected: 1, failing: 1, piles: 4, columns: 4, selectedColumns: 1, ties: 1, boreholes: 2, grid: 4, proposals: 1,
			heatCells: 4, hottest: 1, range: { min: 80, max: 140 },
		});
	});
});
