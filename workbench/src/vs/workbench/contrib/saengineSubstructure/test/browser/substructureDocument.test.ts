/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	addPiles, applyPileLayout, applyProposal, capAround, capPileType, capSize, carriedAlready, checkSubstructure, connectGradeBeams, deletePiles, formatSpacings, foundationOutlines, governingCheck, gridIntersections, gridLines, IFoundation, importFoundations, intersectionsInBox, ISiteContext, ISubstructure, makePileCap, maxPressure, minPileSpacing, movePiles, newFooting, newPileCap, newPileGrid, newRaft, newSubstructure, newTieBeam, parseIdList, parseMesh, parseSpacings, parseSubstructure, pileFactorsUsed, pileLayout, pileOffsets, pilePositions, pilesInBox, placePileGroup, refitCap, snapPoint, upgradePileCaps,
	checkStateText, documentSignatures, errorSummary, foundationId, minimumMesh, proposalFor, readSiteContext, substructureCheckState, uncoveredBases, readSizingProposal, readSubstructureReport, SUBSTRUCTURE_SCHEMA_ID, substructureSummary, substructureSummaryFile, uncoveredColumns, utilisationBand,
} from '../../browser/substructureDocument.js';
import { renderPlan, renderRaftHeatMap, tieBeamEnds } from '../../browser/substructurePlan.js';

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
			// Pile ids (strings) and the offsets of an earlier version are kept; the rest is dropped.
			document: { f: [{ id: 'F1', type: 'isolated', piles: [[0, 0], 'bad'] }], lists: [[], []], design: {}, kept: 1 },
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
			cap: [cap.id, capPileType(cap, doc)?.id, cap.piles, cap.center, cap.length, cap.width, cap.thickness],
			capPiles: pilePositions(cap, doc),
			raft: [raft.id, raft.outline, raft.thickness],
			tie,
		}, {
			isolated: ['F1', 'isolated', ['C1'], 1500, 1500, 450, 'M25', { material: 'G60', cover: 75, bottomX: { dia: 12, spacing: 125 }, bottomY: { dia: 12, spacing: 125 } }],
			combined: ['F2', 'combined', [3000, 0], undefined, 7500, 1500, 600],
			cap: ['F3', 'P1', ['PL1', 'PL2', 'PL3', 'PL4'], [0, 5000], 2300, 2300, 1000],
			capPiles: [[-750, 4250], [750, 4250], [750, 5750], [-750, 5750]],
			// A raft is named R1 (N-U9: as the sizing assistant names it).
			raft: ['R1', [[-1000, -1000], [7000, -1000], [7000, 6000], [-1000, 6000]], 600],
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
			{ id: 'F3', type: 'pileCap', columns: ['C3'], center: [0, 5000], length: 1600, width: 1600, thickness: 900, piles: ['PL1', 'PL2'] },
			{ id: 'F4', type: 'pileCap', columns: ['C4'], length: 2300, width: 2300, thickness: 1000, piles: [] },
			{ id: 'R1', type: 'raft', thickness: 600, outline: [[0, 0], [1, 1]] },
			// A pile 700 mm off a 1600 mm cap's centre: its side 950 mm out, past the 800 mm edge.
			{ id: 'F5', type: 'pileCap', center: [0, 0], length: 1600, width: 1600, thickness: 900, piles: ['PL3'] },
			// Driven 400 mm piles 900 apart: end bearing asks more than max(750, 2.5 × 400) = 1000.
			{ id: 'F6', type: 'pileCap', center: [3000, 3000], length: 2000, width: 1200, thickness: 900, piles: ['PL4', 'PL5'] },
			{ id: 'F7', type: 'isolated', center: [3000, 0], length: 1500, width: 1500, thickness: 450, reinforcement: { cover: 0 } },
			{ id: 'S1', type: 'strip', columns: ['W1'], path: [[6000, 0], [6000, 5000]], width: 900, thickness: 450 },
			{ id: 'F8', type: 'isolated', columns: ['W1'], length: 1500, width: 1500, thickness: 450 },
		]);
		doc.pileTypes.push({ id: 'P2', kind: 'driven', diameter: 400, length: 12000 });
		doc.piles.push(
			{ id: 'PL1', type: 'P1', position: [-500, 5000] }, { id: 'PL2', type: 'P1', position: [500, 5000] }, { id: 'PL3', type: 'P1', position: [700, 0] },
			{ id: 'PL4', type: 'P2', position: [2550, 3000] }, { id: 'PL5', type: 'P2', position: [3450, 3000] },
		);
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
				// No centre (a cap is placed over its piles) and no piles.
				'error foundations.3.center',
				'error foundations.3.piles',
				'error foundations.4.outline',
				// A pile 700 mm off a 1600 mm cap's centre: not wholly within it (the design skips the cap).
				'warning foundations.5.piles',
				'warning foundations.6.piles',
				'error foundations.7.reinforcement.material',
				'error foundations.7.reinforcement.cover',
				// A wall on an isolated footing, and on the strip already.
				'warning foundations.9.columns',
				'error foundations.9.columns',
				// Pile types without bars: checked as plain concrete (BNBC 2020 Part 6 Table 6.3.11 gives the least).
				'warning pileTypes.0.reinforcement',
				'warning pileTypes.1.reinforcement',
				'error pileTypes.1.material',
				// Piles in plan: PL1 and PL2 1000 mm apart (less than 2.5 × 500 = 1250), PL4 and PL5 900 apart (less than 1000).
				'warning piles.1.position',
				'warning piles.4.position',
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
			{ id: 'F1', type: 'pileCap', columns: ['C1'], piles: [], thickness: 800 },
			{ id: 'F2', type: 'isolated', columns: ['C2'], length: 1500, width: 1500, thickness: 450, material: 'M25', reinforcement },
			{ id: 'F3', type: 'isolated', columns: ['C3'], length: 1500, width: 1500, thickness: 450 },
		]);
		doc.tieBeams.push({ id: 'TB1', from: 'F2', to: 'F3', type: 'B300x500' }, { id: 'TB2', from: 'F1', to: 'F3', type: 'B300x500' });
		applyPileLayout(doc, CONTEXT, doc.foundations[0], doc.pileTypes[0], 2);
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
			cap: { id: 'F1', type: 'pileCap', columns: ['C1'], piles: ['PL1', 'PL2'], center: [0, 0], length: 2300, width: 800, thickness: 800 },
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
			f8PileType: capPileType(doc.foundations.find(f => f.id === 'F8')!, doc)?.id,
			f8Piles: pilePositions(doc.foundations.find(f => f.id === 'F8')!, doc),
			pileTypes: doc.pileTypes.map(p => p.id),
		}, {
			// F6 stands under C3, which F6 here carries; F7's id is taken here: it becomes F2.
			result: { added: ['F2', 'F8'], skipped: ['F6'] },
			ids: ['F1 C1 2500', 'F6 C3 1500', 'F7 C4 1500', 'F2 C2 1700', 'F8  1000'],
			f8PileType: 'P2',
			// The offset of the earlier version, placed in plan from the cap's centre.
			f8Piles: [[3000, 3000]],
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
					capacity: { pileType: 'P1', borehole: 'BH-1', Qs: 600, Qb: 400, Qult: 1000, Qa: 400, Ta: 240, base: { layer: 3, qb: 2000 } },
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
			f3: [null, true, [{ number: 1, mark: undefined, u: -750, v: 0, compression: 400.5, least: -12, factored: 560, capacity: undefined, utilisation: undefined, combination: undefined }]],
			capacities: [{ pileType: 'P1', borehole: 'BH-1', skin: 600, base: 400, ultimate: 1000, compression: 400, uplift: 240, method: undefined, note: undefined }],
			ties: ['TB1'],
			skipped: [{ id: 'R1', type: 'raft', reason: 'rafts are not designed yet' }],
			summary: { checked: 3, total: 4, passed: 2, failed: 1, maxUtilisation: 1.12, governing: 'F1', unsupported: [], status: 'fail' },
			text: '2 foundations · 2 of 2 checked · 1 fail · max pressure 142 kPa (qa 150)',
			noReport: '2 foundations',
			bands: ['ok', 'warn', 'warn', 'fail', 'none'],
			notReport: undefined,
			governing: ['Punching shear', undefined],
			file: { foundations: 2, checked: 2, total: 2, passed: 1, failed: 1, bearingUnchecked: [], unsupported: [], status: 'fail', maxUtilisation: 1.12, governing: 'F1', computed: '1970-01-01T00:00:00.000Z', source: { substructure: 'abc', soil: '' } },
		});
	});

	test('the minimum mesh of a new foundation meets As,min = 0.0018 h within the spacing limits', () => {
		const meshes = [300, 450, 500, 600, 1000].map(h => ({ h, mesh: minimumMesh(h) }));
		assert.deepStrictEqual(meshes.map(m => m.mesh), [
			// 540 mm²/m: 12@200 (565); 810: 12@125 (905); 900: 12@125 (905); 1080: 16@175 (1149); 1800: 20@150 (2094).
			{ dia: 12, spacing: 200 }, { dia: 12, spacing: 125 }, { dia: 12, spacing: 125 }, { dia: 16, spacing: 175 }, { dia: 20, spacing: 150 },
		]);
		for (const { h, mesh } of meshes) {
			assert.ok(Math.PI * mesh.dia ** 2 / 4 * 1000 / mesh.spacing >= 0.0018 * h * 1000, `h ${h}`);
		}
		// A raft starts with top bars too (it hogs between the columns).
		const raft = newRaft(document(), CONTEXT, CONTEXT.columns.slice(0, 2))!;
		assert.deepStrictEqual([raft.reinforcement?.topX, raft.reinforcement?.bottomY], [{ dia: 16, spacing: 175 }, { dia: 16, spacing: 175 }]);
	});

	test('checks of an edited foundation are stale, and all pass only when all were checked', () => {
		const result = (id: string, ok = true) => ({ id, type: 'isolated', checks: [], utilisation: 0.5, ok });
		const doc = document([
			{ id: 'F1', type: 'isolated', columns: ['C1'], length: 1500, width: 1500, thickness: 450 },
			{ id: 'F2', type: 'isolated', columns: ['C2'], length: 1500, width: 1500, thickness: 450 },
		]);
		const checkedFor = documentSignatures(doc);
		const report = readSubstructureReport({ foundations: [result('F1'), result('F2')], tieBeams: [], skipped: [], summary: {} })!;
		const all = substructureCheckState(doc, report, checkedFor, []);
		// Nothing was checked for F2: not "all pass" (U2).
		const partial = substructureCheckState(doc, readSubstructureReport({ foundations: [result('F1')], skipped: [{ id: 'F2', reason: 'no results' }] })!, checkedFor, []);
		const none = substructureCheckState(doc, readSubstructureReport({ foundations: [], skipped: [{ id: 'F1' }, { id: 'F2' }] })!, checkedFor, []);
		const uncovered = substructureCheckState(doc, report, checkedFor, ['C3']);
		// A new size after the save: F1's checks describe the old footing (U1); a note does not count.
		doc.foundations[0].length = 2500;
		doc.foundations[1].note = 'checked by hand';
		const edited = substructureCheckState(doc, report, checkedFor, []);
		assert.deepStrictEqual({
			all: [all.status, checkStateText(all)],
			partial: [partial.status, checkStateText(partial)],
			none: none.status,
			uncovered: uncovered.status,
			edited: [edited.status, edited.stale, checkStateText(edited)],
			summary: report.summary.status,
		}, {
			all: ['pass', '2 of 2 checked · all pass'],
			partial: ['incomplete', '1 of 2 checked · 1 not checked'],
			none: 'none',
			uncovered: 'incomplete',
			edited: ['incomplete', 1, '1 of 2 checked · 1 changed since checked'],
			summary: 'pass',
		});
	});

	test('a footing without its bearing check is neither checked nor passing (N-U3)', () => {
		const doc = document([
			{ id: 'F1', type: 'isolated', columns: ['C1'], length: 1500, width: 1500, thickness: 450 },
			{ id: 'F2', type: 'isolated', columns: ['C2'], length: 1500, width: 1500, thickness: 450 },
		]);
		const report = readSubstructureReport({
			foundations: [
				{ id: 'F1', type: 'isolated', checks: [], utilisation: 0.5, ok: true },
				{ id: 'F2', type: 'isolated', checks: [], utilisation: 0.4, ok: true, notChecked: ['bearing'] },
			], tieBeams: [], skipped: [], summary: {},
		})!;
		const state = substructureCheckState(doc, report, documentSignatures(doc), []);
		const file = substructureSummaryFile(doc, report, new Date(0));
		assert.deepStrictEqual({
			state: [state.status, state.checked, state.passed, state.bearingUnchecked, checkStateText(state)],
			file: [file.checked, file.passed, file.total, file.status, file.bearingUnchecked],
		}, {
			state: ['incomplete', 1, 1, ['F2'], '1 of 2 checked · 1 without a bearing check (no qa)'],
			file: [1, 1, 2, 'incomplete', ['F2']],
		});
	});

	test('a backend error as one line with the traceback as details (N-U1)', () => {
		const traceback = `saengine.codes.registry.CodePackError: code pack 'bnbc2020' cannot be used: basis: Extra inputs are not permitted Traceback (most recent call last): File "server.py", line 634, in _substructure_report`;
		assert.deepStrictEqual(errorSummary(traceback), {
			summary: `CodePackError: code pack 'bnbc2020' cannot be used: basis: Extra inputs are not permitted`,
			details: traceback,
			restart: true,
		});
		assert.deepStrictEqual(errorSummary('no analysis results'), { summary: 'no analysis results', details: undefined, restart: false });
		// A plain traceback ends with its message.
		const plain = 'Traceback (most recent call last):\n  File "server.py", line 634, in run\nValueError: no qa for B1';
		assert.deepStrictEqual(errorSummary(plain), { summary: 'ValueError: no qa for B1', details: plain, restart: false });
	});

	test('new foundations follow the ids and materials of the project (N-U9)', () => {
		const columns = [
			{ ...CONTEXT.columns[0], id: 'C-A1-L1' }, { ...CONTEXT.columns[1], id: 'C-B1-L1' },
		];
		const doc = document([{ id: 'F-A2', type: 'isolated', columns: ['C-A2-L1'], material: 'C27.6', reinforcement: { material: 'B500', cover: 75 }, length: 1500, width: 1500, thickness: 450 }]);
		const footing = newFooting(doc, CONTEXT, [columns[0]]);
		const combined = newFooting(doc, CONTEXT, columns);
		const raft = newRaft(doc, CONTEXT, columns)!;
		assert.deepStrictEqual(
			[footing.id, combined.id, raft.id, footing.material, raft.material, raft.reinforcement?.material, foundationId(doc, 'isolated', ['X1'])],
			['F-A1', 'F-A1-B1', 'R1', 'C27.6', 'C27.6', 'B500', 'F1'],
		);
		// Footings replaced by a proposed raft: the raft is named as one and their tie beams go.
		doc.foundations.push({ ...footing });
		doc.tieBeams.push({ id: 'TB1', from: 'F-A2', to: 'F-A1' });
		const placed = applyProposal(doc, { foundations: [{ ...raft, id: 'X', columns: ['C-A1-L1', 'C-A2-L1'] }], pileTypes: [], notes: [] });
		assert.deepStrictEqual([placed, doc.foundations.map(f => f.id), doc.tieBeams], [['R1'], ['R1'], []]);
	});

	test('columns and walls without a foundation', () => {
		const context: ISiteContext = { ...CONTEXT, walls: [{ id: 'W1', start: [0, 0], end: [6000, 0], thickness: 200 }] };
		const doc = document([{ id: 'F1', type: 'isolated', columns: ['C1'], length: 1500, width: 1500, thickness: 450 }]);
		assert.deepStrictEqual(uncoveredBases(doc, context), [...uncoveredColumns(doc, context).map(c => c.id), 'W1']);
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
					raft: { nodes: [[0, 0], [500, 0]], elements: [], pressure: [80, 95.5], settlement: [12, 14.25], meshSize: 500, summary: { maxPressure: 95.5, maxPressureCombination: 'D + L', maxSettlement: 14.25, maxDifferential: 2.25, maxAngularDistortion: 0.0045 }, columns: [{ id: 'C1', x: 0, y: 0, settlement: 12, pressure: 80 }] },
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
				columns: [{ id: 'C1', x: 0, y: 0, pressure: 80, settlement: 12 }],
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
			{ id: 'F2', type: 'pileCap', columns: ['C3'], length: 2300, width: 2300, thickness: 1000, pileType: 'P1', piles: pileLayout(4, 500) as unknown as string[] }, // offsets of an earlier version
			{ id: 'S1', type: 'strip', path: [[6000, 0], [6000, 5000]], width: 1000, thickness: 450 },
		]);
		// A cap of an earlier version without a centre: placed at its column's.
		upgradePileCaps(doc, CONTEXT.columns);
		doc.pileGrid = { origin: [-750, 4250], x: gridLines('x', [1500]), y: gridLines('y', [1500]) };
		addPiles(doc, 'P1', [[3000, 2500]]);
		doc.tieBeams.push({ id: 'TB1', from: 'F1', to: 'F2', type: 'B300x500' });
		const drawing = renderPlan(container, doc, CONTEXT, { width: 800, height: 600, selectedFoundations: new Set([1]), selectedColumns: new Set(['C4']), selectedPiles: new Set(['PL5']), proposals: [{ id: 'F1', type: 'isolated', columns: ['C1'], length: 2000, width: 2000, thickness: 500 }], bands: new Map([['F1', 'fail' as const]]), utilisations: new Map([['F1', 1.12]]) });
		const plan = drawing.svg;
		// The transform goes both ways: a pile's centre on the screen is its plan position.
		const [sx, sy] = drawing.toScreen([3000, 2500]);
		const back = drawing.toPlan(sx, sy).map(v => Math.round(v));
		const raftContainer = mainWindow.document.createElement('div');
		const range = renderRaftHeatMap(raftContainer, { id: 'R1', type: 'raft', outline: [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], thickness: 600 }, {
			points: [{ x: 250, y: 250, pressure: 80 }, { x: 750, y: 250, pressure: 100 }, { x: 250, y: 750, pressure: 120 }, { x: 750, y: 750, pressure: 140 }],
		}, CONTEXT, 'pressure', { width: 300, height: 200 });
		assert.deepStrictEqual({
			foundations: plan.querySelectorAll('[data-foundation]').length,
			selected: plan.querySelectorAll('.sub-foundation.selected').length,
			failing: plan.querySelectorAll('.sub-foundation.band-fail').length,
			piles: plan.querySelectorAll('[data-pile]').length,
			freePiles: plan.querySelectorAll('.sub-pile-item.free').length,
			selectedPiles: [...plan.querySelectorAll('.sub-pile-item.selected')].map(e => e.getAttribute('data-pile')),
			pileGrid: plan.querySelectorAll('.sub-pile-grid-line').length,
			back,
			columns: plan.querySelectorAll('[data-column]').length,
			selectedColumns: plan.querySelectorAll('.sub-column.selected').length,
			ties: plan.querySelectorAll('[data-tie]').length,
			boreholes: plan.querySelectorAll('.sub-borehole').length,
			grid: plan.querySelectorAll('.sub-grid-line').length,
			proposals: plan.querySelectorAll('.sub-proposal').length,
			heatCells: raftContainer.querySelectorAll('.sub-heat-cell').length,
			hottest: raftContainer.querySelectorAll('.sub-heat-7').length,
			range,
			utilisation: plan.querySelector('.sub-foundation-util')?.textContent,
			// The tie beam runs between the columns its foundations carry (C1 to C3), not their centres.
			tieEnds: tieBeamEnds(doc.foundations[0], doc.foundations[1], CONTEXT),
		}, {
			foundations: 3, selected: 1, failing: 1, piles: 5, freePiles: 1, selectedPiles: ['PL5'], pileGrid: 4, back: [3000, 2500], columns: 4, selectedColumns: 1, ties: 1, boreholes: 2, grid: 4, proposals: 1,
			heatCells: 4, hottest: 1, range: { min: 80, max: 140 },
			utilisation: '1.12',
			tieEnds: [[CONTEXT.columns[0].x, CONTEXT.columns[0].y], [CONTEXT.columns[2].x, CONTEXT.columns[2].y]],
		});
	});

	test('the pile grid: spacings, labels, crossings, a grid over the columns', () => {
		const grid = { origin: [1000, 2000] as [number, number], rotation: 90, x: gridLines('x', [1500, 1500]), y: gridLines('y', [2000]) };
		const turned = gridIntersections(grid).map(c => [c.x, c.y, ...c.point.map(v => Math.round(v) + 0)]);
		assert.deepStrictEqual({
			spacings: [parseSpacings('4@1500, 2000'), parseSpacings('  '), parseSpacings('3x').error !== undefined, parseSpacings('0').error !== undefined],
			labels: [gridLines('x', [1, 1, 1]).map(l => l.label), gridLines('y', [1]).map(l => l.label)],
			format: formatSpacings(gridLines('x', [1500, 1500, 1500, 2000])),
			// Turned 90°: the grid's x runs along the global y.
			turned,
			// Over the columns (0..6000 by 0..5000) a 3 D = 1500 spacing beyond them each way.
			fresh: (({ origin, x, y }) => ({ origin, x: x.length, y: y.length, last: [x[x.length - 1].position, y[y.length - 1].position] }))(newPileGrid(document(), CONTEXT)),
		}, {
			spacings: [{ value: [1500, 1500, 1500, 1500, 2000] }, { value: [] }, true, true],
			labels: [['a', 'b', 'c', 'd'], ['p1', 'p2']],
			format: '3@1500 2000',
			turned: [['a', 'p1', 1000, 2000], ['a', 'p2', -1000, 2000], ['b', 'p1', 1000, 3500], ['b', 'p2', -1000, 3500], ['c', 'p1', 1000, 5000], ['c', 'p2', -1000, 5000]],
			fresh: { origin: [-1500, -1500], x: 7, y: 7, last: [9000, 9000] },
		});
	});

	test('places piles: snap to grid crossings and columns, a box of crossings, a group under a column', () => {
		const doc = document();
		doc.pileGrid = { origin: [-1500, -1500], x: gridLines('x', [1500, 1500]), y: gridLines('y', [1500, 1500]) };
		const crossing = snapPoint([-1430, 60], doc, CONTEXT, 100);
		const column = snapPoint([5950, 30], doc, CONTEXT, 100);
		const free = snapPoint([2420, 2480], doc, CONTEXT, 100);
		const box = intersectionsInBox(doc.pileGrid, [-2000, -2000], [100, 100]);
		const placed = addPiles(doc, 'P1', box);
		// A group of 3 under C4 at k = 2 asks for less than the code: 2.5 D = 1250 is used.
		const group = placePileGroup(doc, [CONTEXT.columns[3]], doc.pileTypes[0], 3, 2);
		assert.deepStrictEqual({
			crossing, column, free,
			box,
			marks: placed.map(p => p.id),
			group: group.map(p => p.position),
			spacing: Math.round(minPileSpacing(group.map(p => p.position))!),
			inBox: pilesInBox(doc, [-1600, -1600], [-1400, 100]).map(p => p.id),
		}, {
			crossing: { point: [-1500, 0], kind: 'grid', label: 'a-p2' },
			column: { point: [6000, 0], kind: 'column', label: 'C2' },
			free: { point: [2400, 2500], kind: 'free' },
			box: [[-1500, -1500], [-1500, 0], [0, -1500], [0, 0]],
			marks: ['PL1', 'PL2', 'PL3', 'PL4'],
			// A triangle of side 1250 round C4 (6000, 5000): its vertices 1250 / √3 = 722 from the centre.
			group: [[6000, 5722], [5375, 4639], [6625, 4639]],
			spacing: 1250,
			inBox: ['PL1', 'PL2'],
		});
	});

	test('makes a pile cap over a pile group, eccentric to its column', () => {
		const doc = document();
		// Four piles on their own grid, 300 mm off C3 (0, 5000) in x and 150 mm in y.
		const piles = addPiles(doc, 'P1', [[-450, 4400], [1050, 4400], [1050, 5900], [-450, 5900]]);
		const { cap } = makePileCap(doc, CONTEXT, piles.map(p => p.id));
		doc.foundations.push(cap!);
		const taken = makePileCap(doc, CONTEXT, [piles[0].id]);
		doc.pileTypes.push({ id: 'P2', kind: 'driven', diameter: 400, length: 12000 });
		const other = addPiles(doc, 'P2', [[9000, 0]]);
		const mixed = makePileCap(doc, CONTEXT, [other[0].id, ...addPiles(doc, 'P1', [[10500, 0]]).map(p => p.id)]);
		assert.deepStrictEqual({
			// The cap is centred on the piles, not on C3, and takes C3 (the free column inside it).
			cap: [cap!.id, cap!.columns, cap!.piles, cap!.center, cap!.length, cap!.width, cap!.thickness],
			offsets: pileOffsets(cap!, doc),
			taken: taken.error,
			mixed: mixed.error,
			around: capAround([[0, 0], [1500, 0]], 500, 90),
		}, {
			cap: ['F1', ['C3'], ['PL1', 'PL2', 'PL3', 'PL4'], [300, 5150], 2300, 2300, 1000],
			offsets: [[-750, -750], [750, -750], [750, 750], [-750, 750]],
			taken: 'PL1 already under a pile cap (F1).',
			mixed: 'The piles of one cap are of one pile type; these are P2, P1.',
			// Two piles along the global x under a cap turned 90°: its length runs along the global y.
			around: { center: [750, 0], length: 800, width: 2300, thickness: 1000, rotation: 90 },
		});
	});

	test('moves and deletes piles; the cap fits round them again', () => {
		const doc = document();
		const cap = newPileCap(doc, CONTEXT, [CONTEXT.columns[0]], doc.pileTypes[0], 2);
		doc.foundations.push(cap);
		movePiles(doc, new Set(['PL2']), 500, 0);
		refitCap(doc, cap);
		const moved = [cap.center, cap.length, cap.width];
		const emptied = deletePiles(doc, new Set(['PL1', 'PL2']));
		assert.deepStrictEqual({ moved, emptied, piles: doc.piles, capPiles: cap.piles, problem: checkSubstructure(doc, CONTEXT).find(p => p.path === 'foundations.0.piles')?.severity }, {
			// PL1 at -750, PL2 now at 1250: 2000 apart, the cap 2000 + 500 + 300 = 2800 long, centred at 250.
			moved: [[250, 0], 2800, 800],
			emptied: ['F1'],
			piles: [],
			capPiles: [],
			problem: 'error',
		});
	});

	test('connects grade beams between the foundations along each grid line', () => {
		const doc = document();
		for (const column of CONTEXT.columns) {
			doc.foundations.push(newPileCap(doc, CONTEXT, [column], doc.pileTypes[0], 2));
		}
		doc.tieBeams.push({ id: 'TB1', from: 'F1', to: 'F2', type: 'B300x500' });
		const added = connectGradeBeams(doc, CONTEXT);
		const again = connectGradeBeams(doc, CONTEXT);
		assert.deepStrictEqual({ added: added.map(t => `${t.id} ${t.from}-${t.to}`), again }, {
			// C1-C3 on x = 0, C2-C4 on x = 6000, C3-C4 on y = 5000; C1-C2 (y = 0) is tied already.
			added: ['TB2 F1-F3', 'TB3 F2-F4', 'TB4 F3-F4'],
			again: [],
		});
	});

	test('reads a file of an earlier version: per-cap offsets become piles in plan', () => {
		const text = JSON.stringify({
			schema: SUBSTRUCTURE_SCHEMA_ID,
			foundations: [
				{ id: 'PC1', type: 'pileCap', columns: ['C1'], center: [1000, 2000], rotation: 90, length: 2300, width: 800, thickness: 900, pileType: 'P1', piles: [[-750, 0], [750, 0]] },
				{ id: 'PC2', type: 'pileCap', columns: ['C2'], length: 2300, width: 800, thickness: 900, pileType: 'P1', piles: [[-750, 0], [750, 0]] },
			],
			pileTypes: [{ id: 'P1', kind: 'bored', diameter: 500, length: 18000 }],
		});
		const withColumns = parseSubstructure(text, CONTEXT.columns);
		const without = parseSubstructure(text);
		const doc = withColumns.kind === 'document' ? withColumns.document : newSubstructure();
		const old = without.kind === 'document' ? without.document : newSubstructure();
		assert.deepStrictEqual({
			caps: doc.foundations.map(f => [f.id, f.center, f.piles, f.pileType]),
			piles: doc.piles,
			// Without the building model the cap with no centre stays as it was, and the checks say so.
			old: [old.foundations[1].piles, checkSubstructure(old, CONTEXT).find(p => p.path === 'foundations.1.piles')?.severity],
		}, {
			caps: [['PC1', [1000, 2000], ['PL1', 'PL2'], undefined], ['PC2', [6000, 0], ['PL3', 'PL4'], undefined]],
			piles: [
				{ id: 'PL1', type: 'P1', position: [1000, 1250] }, { id: 'PL2', type: 'P1', position: [1000, 2750] },
				{ id: 'PL3', type: 'P1', position: [5250, 0] }, { id: 'PL4', type: 'P1', position: [6750, 0] },
			],
			old: [[[-750, 0], [750, 0]], 'error'],
		});
	});
});
