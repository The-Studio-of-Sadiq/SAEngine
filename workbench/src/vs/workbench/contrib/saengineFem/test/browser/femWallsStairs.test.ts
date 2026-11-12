/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { designKindLabel, formatCheckValues, IFemDesignCheck, IFemDesignReport } from '../../browser/femDesign.js';
import { boundaryItems, describePierForces, describeStaircaseVerdict, describeWallsSummary, FemStaircaseElement, FemWallElement, governingPier, hasParts, ownChecks, pierDiagram, pierOfShell, staircasesOf, staircaseSection, wallSection } from '../../browser/femWallsStairs.js';

function check(fields: Partial<IFemDesignCheck> & Record<string, unknown>): IFemDesignCheck {
	return { name: 'Check', demand: 1, capacity: 2, unit: '', utilisation: 0.5, combination: null, ok: true, note: '', flag: false, ...fields } as IFemDesignCheck;
}

/*
 * Synthetic data, worked by hand. Wall W1, 3,000 × 200 mm, two storeys (piers P1 bottom, P2 top):
 * - P1 under 1.2D+1.0L+1.0E: P 1,250 kN, V2 310 kN, M3 2,400 kN·m. In-plane shear (Sec 8.3.6.4):
 *   Acv = 3,000 × 200 = 600,000 mm²; αc = 0.17 (hw/lw ≥ 2), √f'c = √28 = 5.29 MPa, ρt = 0.0025,
 *   fy = 420 MPa: Vn = 600,000 (0.17 × 5.29 + 0.0025 × 420) / 1,000 = 1,169.6 kN; φ = 0.60 (shear
 *   of a special wall controlled by shear), φVn = 701.8 kN: 310 / 701.8 = 0.44. P-M 0.81 (given).
 *   Boundary elements, displacement based (Sec 8.3.6.6(b)): c = 820 mm against lw / (600 δu/hw)
 *   with δu/hw = 0.0082: 3,000 / (600 × 0.0082) = 610 mm: required; length max(c - 0.1 lw, c/2) =
 *   max(520, 410) = 520 mm.
 * - P2: P 600 kN, V2 -180 kN, M3 900 kN·m; shear 180 / 701.8 = 0.26, P-M 0.35.
 * Coupling beam CB1: ln = 1,200 mm, h = 800 mm, ln / h = 1.50 < 2: diagonal bars.
 */
const P1_SHEAR = check({ name: 'In-plane shear', demand: 310, capacity: 701.8, unit: 'kN', utilisation: 0.4417, combination: '1.2D+1.0L+1.0E', clause: 'Sec 8.3.6.4' });
const P1_PM = check({ name: 'P-M interaction', demand: 0.81, capacity: 1, utilisation: 0.81, combination: '1.2D+1.0L+1.0E' });
const P2_SHEAR = check({ name: 'In-plane shear', demand: 180, capacity: 701.8, unit: 'kN', utilisation: 0.2565, combination: '0.9D+1.0E', clause: 'Sec 8.3.6.4' });
const P2_PM = check({ name: 'P-M interaction', demand: 0.35, capacity: 1, utilisation: 0.35, combination: '0.9D+1.0E' });
const MIN_STEEL = check({ name: 'Minimum web steel ρt', demand: 0.0025, capacity: 0.0025, utilisation: 1, clause: 'Sec 8.3.6.2' });
const CB_SHEAR = check({ name: 'Diagonal bars shear', demand: 420, capacity: 560, unit: 'kN', utilisation: 0.75, combination: '1.2D+1.0L+1.0E', clause: 'Sec 8.3.6.7' });

const W1: FemWallElement = {
	id: 'W1', kind: 'wall', type: 'Wall200', members: [101, 102, 201, 202], utilisation: 1, ok: true,
	checks: [P1_SHEAR, P1_PM, P2_SHEAR, P2_PM, MIN_STEEL, CB_SHEAR],
	wallType: 'special', curtains: 2, curtainsRequired: 2,
	boundary: { required: true, length: 520, method: 'displacement', reason: 'c = 820 mm ≥ lw / (600 δu/hw) = 610 mm', clause: 'Sec 8.3.6.6(b)' },
	piers: [
		{ id: 'P1', storey: 'Storey 1', lw: 3000, tw: 200, members: [101, 102], forces: { combination: '1.2D+1.0L+1.0E', P: 1250, V2: 310, M3: 2400 }, checks: [P1_SHEAR, P1_PM] },
		{ id: 'P2', storey: 'Storey 2', lw: 3000, tw: 200, members: [201, 202], forces: { combination: '0.9D+1.0E', P: 600, V2: -180, M3: 900 }, checks: [P2_SHEAR, P2_PM] },
	],
	couplingBeams: [{ id: 'CB1', storey: 'Storey 1', ln: 1200, h: 800, diagonal: true, checks: [CB_SHEAR] }],
};

/*
 * Staircase ST1 in the shape of `saengine.design.stairs.design_stair`: one flight F1 between beams,
 * rise 1,980 mm in 12 risers of 165 mm, treads 250 mm, waist 150 mm, f'c 25 MPa, fy 420 MPa,
 * Ø12 @ 275 mm (411.3 mm²/m), d = 150 - 20 - 6 = 124 mm:
 * - 2R + T = 2 × 165 + 250 = 580 mm against at least 610 mm: 610 / 580 = 1.05, fails;
 * - riser 165 mm against at most 229 mm: 0.72; tread for the riser reported only;
 * - span 3,000 mm, wu = 1.2 × (D) + 1.6 × 4.8 = 16.53 kN/m², Mu = 16.53 × 3.0² / 8 = 18.59 kN·m/m;
 *   a = 411.3 × 420 / (0.85 × 25 × 1,000) = 8.13 mm, φMn = 0.9 × 411.3 × 420 × (124 - 4.07) /
 *   10⁶ = 18.64 kN·m/m: 0.997; Vu = 16.53 × 3.0 / 2 = 24.79 kN/m against φVc = 0.75 × 0.17 × 5 ×
 *   124 = 79.05 kN/m: 0.31; minimum thickness l/20 / 1.15 = 130.4 mm, reported.
 */
const TWO_R_T = check({ name: '2R + T (BNBC Part 3 Sec 1.14.5.2, p. 69)', demand: 580, capacity: 610, unit: 'mm', utilisation: 1.052, ok: false, note: 'R = 165.0 mm (rise / 12), T = 250 mm' });
const RISER = check({ name: 'Riser height (Part 4 Table 4.3.5, p. 310)', demand: 165, capacity: 229, unit: 'mm', utilisation: 0.721, note: 'largest riser of Table 4.3.5: 229 mm' });
const PAIRED = check({ name: 'Tread for the riser (Part 4 Table 4.3.5, p. 310)', demand: 311, capacity: 250, unit: 'mm', utilisation: 1.244, ok: false, flag: true });
const FLEX = check({ name: 'F1: flexure (bottom)', demand: 18.59, capacity: 18.64, unit: 'kN·m/m', utilisation: 0.997, combination: '1.2D + 1.6L', note: 'Ø12 @ 275, d = 124 mm' });
const SHEAR = check({ name: 'F1: one-way shear', demand: 24.79, capacity: 79.05, unit: 'kN/m', utilisation: 0.314 });
const STRAIN = check({ name: 'F1: net tensile strain', demand: 0.08, capacity: 0.43, unit: 'c/d', utilisation: 0.18 });
const THICK = check({ name: 'F1: min. thickness (Table 6.6.1)', demand: 130.43, capacity: 150, unit: 'mm', utilisation: 0.87, flag: true });
const ST1: FemStaircaseElement = {
	id: 'ST1', kind: 'staircase', type: 'Stair150', members: [], utilisation: 1.052, ok: false,
	checks: [TWO_R_T, RISER, PAIRED, FLEX, SHEAR, STRAIN, THICK],
	flights: [{ name: 'F1', risers: 12, riser: 165, going: 2750, span: 3000, rule: 'Sec 6.7.1.1(a): centre to centre of beams', meanThickness: 262.22 }],
	parts: [{ name: 'F1', kind: 'flight', span: 3000, h: 150, wu: 16.526, mu: 18.592, muTop: 0, vu: 24.789, combination: '1.2D + 1.6L' }],
	loads: { finish: 1.2, live: 4.8, unitWeight: 23.536, source: '' },
};

const REPORT: IFemDesignReport = {
	code: 'BNBC 2020', method: [], combinations: [], skipped: [], notes: [],
	elements: [W1, ST1, { id: 'B1', kind: 'beam', type: 'B300', members: [5], checks: [], utilisation: 0.5, ok: true }],
	summary: { checked: 3, passed: 2, failed: 1, skipped: 0, maxUtilisation: 1.0357, governing: 'ST1' },
};

suite('SAEngine FEM walls and stairs', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('the pier of a selected shell, the governing pier, and the forces', () => {
		assert.deepStrictEqual({
			selected: pierOfShell(W1, 202)?.id,
			none: pierOfShell(W1, 999)?.id,
			governing: governingPier(W1)?.id,
			forces: describePierForces(W1.piers![0].forces),
			partial: describePierForces({ V2: 12 }),
			empty: describePierForces({}),
		}, {
			selected: 'P2',
			none: undefined,
			governing: 'P1',
			forces: 'P 1,250.0 kN · V2 310.0 kN · M3 2,400.0 kN·m',
			partial: 'V2 12.0 kN',
			empty: undefined,
		});
	});

	test('the wall-level checks are those not repeated in its piers and coupling beams', () => {
		assert.deepStrictEqual(ownChecks(W1).map(c => c.name), ['Minimum web steel ρt']);
		const bare: FemWallElement = { ...W1, piers: [] };
		assert.deepStrictEqual(ownChecks(bare).length, 6);
	});

	test('a wall section: type, curtains, boundary, the selected and governing piers, coupling beams', () => {
		assert.deepStrictEqual(wallSection(W1, 201), [
			{ kind: 'heading', text: 'Wall' },
			{ kind: 'row', name: 'Type', value: 'Special structural wall' },
			{ kind: 'row', name: 'Curtains', value: '2 provided, 2 required', ok: true },
			{ kind: 'row', name: 'Boundary elements', value: 'required, 520 mm from each end' },
			{ kind: 'note', text: 'displacement-based · c = 820 mm ≥ lw / (600 δu/hw) = 610 mm · Sec 8.3.6.6(b)' },
			{ kind: 'heading', text: 'Pier at Selection' },
			{ kind: 'subheading', text: 'Storey 2 (lw 3,000 mm, tw 200 mm)' },
			{ kind: 'row', name: 'Forces', value: 'P 600.0 kN · V2 -180.0 kN · M3 900.0 kN·m' },
			{ kind: 'row', name: 'Governing combination', value: '0.9D+1.0E' },
			{ kind: 'check', name: 'P-M interaction', value: '0.35', detail: '0.35 against 1 · 0.9D+1.0E', ok: true },
			{ kind: 'check', name: 'In-plane shear', value: '0.26', detail: '180.0 kN against 701.8 kN · Sec 8.3.6.4 · 0.9D+1.0E', ok: true },
			{ kind: 'heading', text: 'Governing Pier' },
			{ kind: 'subheading', text: 'Storey 1 (lw 3,000 mm, tw 200 mm)' },
			{ kind: 'row', name: 'Forces', value: 'P 1,250.0 kN · V2 310.0 kN · M3 2,400.0 kN·m' },
			{ kind: 'row', name: 'Governing combination', value: '1.2D+1.0L+1.0E' },
			{ kind: 'check', name: 'P-M interaction', value: '0.81', detail: '0.81 against 1 · 1.2D+1.0L+1.0E', ok: true },
			{ kind: 'check', name: 'In-plane shear', value: '0.44', detail: '310.0 kN against 701.8 kN · Sec 8.3.6.4 · 1.2D+1.0L+1.0E', ok: true },
			{ kind: 'heading', text: 'Coupling Beams' },
			{ kind: 'subheading', text: 'CB1 · Storey 1 — 0.75' },
			{ kind: 'row', name: 'ln / h', value: '1.50 (1,200 mm / 800 mm)' },
			{ kind: 'row', name: 'Reinforcement', value: 'diagonal bars' },
			{ kind: 'check', name: 'Diagonal bars shear', value: '0.75', detail: '420.0 kN against 560.0 kN · Sec 8.3.6.7 · 1.2D+1.0L+1.0E', ok: true },
		]);
	});

	test('the governing pier alone when the selection is not in a pier; nothing for a bare wall', () => {
		const items = wallSection(W1, undefined);
		assert.deepStrictEqual(items.filter(i => i.kind === 'heading').map(i => i.kind === 'heading' ? i.text : ''), ['Wall', 'Governing Pier', 'Coupling Beams']);
		assert.deepStrictEqual(wallSection({ id: 'W2', kind: 'wall', type: 'Wall', members: [], checks: [], utilisation: 0, ok: true }, 1), []);
	});

	test('boundary elements not required, and without a verdict', () => {
		assert.deepStrictEqual(boundaryItems({ required: false, method: 'stress', reason: 'σ = 4.1 MPa ≤ 0.2 f\'c = 5.6 MPa' }), [
			{ kind: 'row', name: 'Boundary elements', value: 'not required' },
			{ kind: 'note', text: 'stress-based · σ = 4.1 MPa ≤ 0.2 f\'c = 5.6 MPa' },
		]);
		assert.deepStrictEqual(boundaryItems({ length: 300 }), []);
	});

	test('the pier diagram: top storey first, the largest of each force, the selected pier', () => {
		assert.deepStrictEqual(pierDiagram(W1, 101), {
			bars: [
				{ label: 'Storey 2', P: 600, V2: -180, M3: 900, utilisation: 0.35, ok: true, selected: false, governing: false },
				{ label: 'Storey 1', P: 1250, V2: 310, M3: 2400, utilisation: 0.81, ok: true, selected: true, governing: true },
			],
			max: { P: 1250, V2: 310, M3: 2400 },
		});
		assert.strictEqual(pierDiagram({ ...W1, piers: [{ id: 'P9' }] }, undefined), undefined);
	});

	test('a staircase section: geometry checks, loads, each part with its steps, demands and checks', () => {
		assert.deepStrictEqual(staircaseSection(ST1), [
			{ kind: 'heading', text: 'Geometry' },
			{ kind: 'check', name: '2R + T (BNBC Part 3 Sec 1.14.5.2, p. 69)', value: '1.05', detail: '580 mm against 610 mm', ok: false, note: 'R = 165.0 mm (rise / 12), T = 250 mm' },
			{ kind: 'check', name: 'Riser height (Part 4 Table 4.3.5, p. 310)', value: '0.72', detail: '165 mm against 229 mm', ok: true, note: 'largest riser of Table 4.3.5: 229 mm' },
			{ kind: 'check', name: 'Tread for the riser (Part 4 Table 4.3.5, p. 310)', value: 'reported', detail: '311 mm against 250 mm', ok: true },
			{ kind: 'heading', text: 'Loads' },
			{ kind: 'row', name: 'Finish', value: '1.2 kN/m²' },
			{ kind: 'row', name: 'Live', value: '4.8 kN/m²' },
			{ kind: 'row', name: 'Concrete', value: '23.5 kN/m³' },
			{ kind: 'heading', text: 'Flights and Landings' },
			{ kind: 'subheading', text: 'Flight F1 (span 3,000 mm, h 150 mm)' },
			{ kind: 'row', name: 'Steps', value: '12 risers of 165.0 mm, going 2,750 mm' },
			{ kind: 'row', name: 'Mean thickness', value: '262 mm' },
			{ kind: 'row', name: 'Demands', value: 'wu 16.53 kN/m² · Mu 18.59 kN·m/m · Vu 24.79 kN/m' },
			{ kind: 'row', name: 'Governing combination', value: '1.2D + 1.6L' },
			{ kind: 'note', text: 'Span: Sec 6.7.1.1(a): centre to centre of beams' },
			{ kind: 'check', name: 'flexure (bottom)', value: '0.997', detail: '18.6 kN·m/m against 18.6 kN·m/m · 1.2D + 1.6L', ok: true, note: 'Ø12 @ 275, d = 124 mm' },
			{ kind: 'check', name: 'one-way shear', value: '0.31', detail: '24.8 kN/m against 79.0 kN/m', ok: true },
			{ kind: 'check', name: 'net tensile strain', value: '0.18', detail: '0.08 c/d against 0.43 c/d', ok: true },
			{ kind: 'check', name: 'min. thickness (Table 6.6.1)', value: 'reported', detail: '130 mm against 150 mm', ok: true },
		]);
		const flat: FemStaircaseElement = { ...ST1, flights: null, parts: null };
		assert.deepStrictEqual({
			own: ownChecks(ST1),
			// Without parts (an older backend): a flat list, nothing of the parts' section.
			flat: [hasParts(flat), ownChecks(flat).length, staircaseSection(flat)],
			// Only flights (no parts): their names still find the checks.
			flightsOnly: staircaseSection({ ...ST1, parts: null }).filter(i => i.kind === 'subheading'),
		}, {
			own: [],
			flat: [false, 7, []],
			flightsOnly: [{ kind: 'subheading', text: 'Flight F1 (span 3,000 mm)' }],
		});
	});

	test('the report summary: walls counted, stairs listed, kinds labelled', () => {
		assert.deepStrictEqual({
			walls: describeWallsSummary(REPORT),
			noWalls: describeWallsSummary({ ...REPORT, elements: [] }),
			stairs: staircasesOf(REPORT).map(describeStaircaseVerdict),
			parts: REPORT.elements.map(hasParts),
			kinds: REPORT.elements.map(e => designKindLabel(e.kind)),
		}, {
			walls: '1 checked, 0 fail',
			noWalls: undefined,
			stairs: ['ST1 (Stair150) fails, 1.05'],
			parts: [true, true, false],
			kinds: ['wall', 'staircase', 'beam'],
		});
	});

	test('ratios in the general list share their decimals (ρ 0.0124 against 0.0025, not 0.01)', () => {
		assert.deepStrictEqual([
			formatCheckValues(MIN_STEEL),
			formatCheckValues(check({ demand: 0.0124, capacity: 0.0025 })),
			formatCheckValues(check({ demand: 0.0149, capacity: 0.04 })),
			formatCheckValues(check({ demand: 0.11, capacity: 0.38 })),
			formatCheckValues(check({ demand: 0, capacity: 0.43 })),
		], ['0.0025 against 0.0025', '0.0124 against 0.0025', '0.015 against 0.040', '0.11 against 0.38', '0.00 against 0.43']);
	});
});
