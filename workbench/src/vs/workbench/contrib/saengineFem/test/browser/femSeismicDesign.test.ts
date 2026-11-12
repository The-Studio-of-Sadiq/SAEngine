/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IFemDesignCheck, IFemDesignElement, IFemDesignReport, describeSlenderness, formatCheckValues, isSecondOrderRequired, isSlendernessCheck, secondOrderRequiredMembers, slendernessHeading, sortedChecks } from '../../browser/femDesign.js';
import { combinationDetail, combinationName, describeDesignDrift, describeDrift, describeOrthogonal, describeScale, describeScaleOnResult, describeSecondOrder, describeTorsion, IFemSecondOrder, IFemSeismicDesign, isFirstOrderReference, seismicSection, spectrumAxis, storeyAmplificationRows, storeyDriftRows } from '../../browser/femSeismicDesign.js';

function check(fields: Partial<IFemDesignCheck> & Record<string, unknown>): IFemDesignCheck {
	return { name: 'Check', demand: 1, capacity: 2, unit: '', utilisation: 0.5, combination: null, ok: true, note: '', flag: false, ...fields } as IFemDesignCheck;
}

function column(id: string, checks: IFemDesignCheck[]): IFemDesignElement {
	return { id, kind: 'column', type: 'C400', members: [1], checks, utilisation: Math.max(...checks.map(c => c.utilisation)), ok: checks.every(c => c.ok) };
}

/*
 * Synthetic data, worked by hand. A 400 mm column, r = 0.3 × 400 = 120 mm:
 * - nonsway, lu = 4.0 m, k = 0.85: k lu / r = 0.85 × 4000 / 120 = 28.3 > 34 - 12 × 1 = 22.0;
 *   δns = 1.12: M2 = 85 kN·m -> 95.2 kN·m;
 * - neglected, lu = 3.2 m: 0.85 × 3200 / 120 = 22.7 ≤ 24.4;
 * - sway, k = 1.3: 1.3 × 3200 / 120 = 34.7, Q = 0.071: δs = 1 / (1 - 0.071) = 1.08.
 * Response spectrum base shear 1,080 kN against a static 1,500 kN: 0.85 × 1,500 / 1,080 = 1.18.
 */
const seismic: IFemSeismicDesign = {
	available: true,
	scale: { x: 1.18, y: 1, vStatic: { x: 1500, y: 1500 }, vDynamic: { x: 1080, y: 1400 }, fraction: 0.85, clause: 'BNBC 2020 Part 6 Sec 2.5.9.4' },
	category: 'D',
	orthogonal: true,
	// Floor at 3.2 m: 600 kN static force along X, extent 20 m: 600 × 0.05 × 20 = 600 kN·m; no
	// static force along Y, so no moment (the backend still lists the floor).
	torsion: { X: [{ z: 3.2, force: 600, L: 20, moment: 600 }], Y: [{ z: 3.2, force: 0, L: 15, moment: 0 }] },
	clauses: { orthogonal: 'Sec 2.5.13.1(b)' },
	combinations: ['1.2D + 1.0L ± 1.0E(RS EX + 0.3EY)', { name: '0.9D ± 1.0E(RS EX + 0.3EY)', clause: 'Sec 2.7.3.1 no. 7' }],
	drift: [
		{ direction: 'X', bottom: 0, top: 3.2, ratio: 0.0041, allowableRatio: 0.02, ok: true },
		{ direction: 'Y', bottom: 0, top: 3.2, ratio: 0.0038, allowableRatio: 0.02, ok: true },
		{ direction: 'X', bottom: 3.2, top: 6.4, ratio: 0.0052, allowableRatio: 0.02, ok: true },
		{ direction: 'Y', bottom: 3.2, top: 6.4, ratio: 0.0062, allowableRatio: 0.02, ok: true },
	],
};

suite('SAEngine - FEM slenderness and seismic design', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('a column\'s slenderness: lu, k, r, k lu / r, storey, magnifiers and M2 magnified', () => {
		const nonsway = check({
			name: 'Slenderness about y (nonsway, δns = 1.12)', combination: '1.2D + 1.6L',
			slenderness: { lu: 4000, k: 0.85, r: 120, klu_r: 28.33, sway: false, Q: 0.021, deltaNs: 1.12, deltaS: null, M2: 85, M2magnified: 95.2, limit: 22, axis: 'y', Cm: 1, Pc: 4210, neglected: false },
		});
		const neglected = check({ name: 'Slenderness about z (nonsway, neglected)', flag: true, slenderness: { lu: 3200, k: 0.85, r: 120, klu_r: 22.67, sway: false, limit: 24.4, neglected: true } });
		// The fields directly on the check (the backend may flatten them).
		const sway = check({ name: 'Slenderness (sway, δs = 1.08)', lu: 3200, k: 1.3, r: 120, klu_r: 34.67, sway: true, Q: 0.071, deltaNs: 1, deltaS: 1.08, M2: 120, storey: 'Storey 2' });
		const pDelta = check({ name: 'Slenderness about y (sway, P-Δ analysis, δns = 1.00)', slenderness: { lu: 3200, k: 1.3, r: 120, klu_r: 34.67, sway: true, deltaNs: 1, secondOrder: 'pDelta' } });
		const old = check({ name: 'Slenderness k lu / r', demand: 26.7, capacity: 22, flag: true });
		const rows = (c: IFemDesignCheck) => describeSlenderness(c).map(r => `${r.name}: ${r.value}`);
		assert.deepStrictEqual({
			nonsway: rows(nonsway),
			neglected: rows(neglected),
			sway: rows(sway),
			pDelta: rows(pDelta).slice(4),
			old: describeSlenderness(old),
			slenderness: [nonsway, sway, old, check({ name: 'Shear' })].map(isSlendernessCheck),
			headings: [nonsway, neglected, sway, old].map(slendernessHeading),
		}, {
			nonsway: [
				'Unbraced length lu: 4,000 mm',
				'Effective length factor k: 0.85',
				'Radius of gyration r: 120 mm',
				'k lu / r: 28.3 > 22.0: moments magnified',
				'Frame: nonsway, Q = 0.021',
				'Moment magnifier: δns = 1.12',
				'Cm, Pc: 1.00, 4,210 kN',
				'Moment M2: 85.0 kN·m → 95.2 kN·m',
				'Governing combination: 1.2D + 1.6L',
			],
			neglected: [
				'Unbraced length lu: 3,200 mm',
				'Effective length factor k: 0.85',
				'Radius of gyration r: 120 mm',
				'k lu / r: 22.7 ≤ 24.4: slenderness neglected',
				'Frame: nonsway',
			],
			sway: [
				'Unbraced length lu: 3,200 mm',
				'Effective length factor k: 1.30',
				'Radius of gyration r: 120 mm',
				'k lu / r: 34.7',
				'Storey: Storey 2',
				'Frame: sway, Q = 0.071',
				'Moment magnifier: δns = 1.00, δs = 1.08',
				'Moment M2: 120.0 kN·m',
			],
			pDelta: ['Frame: sway', 'Moment magnifier: sway moments from the P-Delta analysis, δns = 1.00'],
			old: [],
			slenderness: [true, true, true, false],
			headings: ['Slenderness about y', 'Slenderness about z', 'Slenderness', 'Slenderness'],
		});
	});

	test('"second-order analysis required": by k lu / r over 100, or by δs (then k lu / r still magnifies)', () => {
		// lu = 6.0 m, k = 2.1: 2.1 × 6000 / 120 = 105.0 > 100.
		const tooSlender = check({ name: 'Slenderness about y (sway)', ok: false, secondOrderRequired: true, slenderness: { lu: 6000, k: 2.1, r: 120, klu_r: 105, sway: true, limit: 22, neglected: false } });
		// k lu / r = 34.7 ≤ 100, but δs = 1 / (1 - 0.38) = 1.62 > 1.5.
		const deltaS = check({ name: 'Slenderness about y (sway, δs = 1.62)', ok: false, secondOrderRequired: true, slenderness: { lu: 3200, k: 1.3, r: 120, klu_r: 34.67, sway: true, deltaS: 1.62, limit: 22, neglected: false } });
		// Flattened onto the check: neglected and the axis survive.
		const flat = check({ name: 'Slenderness about z (nonsway, neglected)', flag: true, lu: 3200, k: 0.85, r: 120, klu_r: 22.67, sway: false, limit: 24.4, neglected: true, axis: 'z', Cm: 1, Pc: 3900 });
		// Required for an unstable storey: the reason is the check's note.
		const unstable = check({ name: 'Slenderness about y (sway)', ok: false, note: 'ΣPu >= 0.75 ΣPc (1.2D + 1.0L + 1.0EX): the storey is unstable; second-order analysis required', slenderness: { lu: 3200, k: 1.3, r: 120, klu_r: 34.67, sway: true, limit: 22, neglected: false } });
		const kluR = (c: IFemDesignCheck) => describeSlenderness(c)[3].value;
		const secondOrder = (c: IFemDesignCheck) => describeSlenderness(c).filter(r => r.name === 'Second-order analysis').map(r => r.value);
		assert.deepStrictEqual({
			values: [tooSlender, deltaS, flat].map(kluR),
			secondOrder: [tooSlender, deltaS, unstable, flat].map(secondOrder),
			flatHeading: slendernessHeading(flat),
		}, {
			values: ['105.0 > 100.0: second-order analysis required', '34.7 > 22.0: moments magnified', '22.7 ≤ 24.4: slenderness neglected'],
			secondOrder: [[], ['required: δs = 1.62 > 1.5'], ['required (see the check)'], []],
			flatHeading: 'Slenderness about z',
		});
	});

	test('"second-order analysis required" is a failure, sorted with the strength checks', () => {
		const required = check({ name: 'Slenderness about y (sway, δs = 1.62, δns = 1.00)', ok: false, utilisation: 1.08, secondOrderRequired: true, note: 'δs = 1/(1 - Q) = 1.62 > 1.5: second-order analysis required' });
		const byNote = check({ name: 'Slenderness', ok: false, utilisation: 1.05, note: 'k lu / r = 105 > 100: a nonlinear second-order analysis is required' });
		const passing = check({ name: 'Slenderness (nonsway, δns = 1.00)', note: 'second-order analysis required only above 100' });
		// Neglected: rated against its limit 39.4 (utilisation 21.83 / 39.4 = 0.55), not against 100.
		const neglected = check({ name: 'Slenderness about y (nonsway, neglected)', flag: true, demand: 21.83, capacity: 100, utilisation: 0.55, slenderness: { lu: 3000, k: 0.873, r: 120, klu_r: 21.83, sway: false, limit: 39.4, neglected: true } });
		const report: IFemDesignReport = {
			code: 'BNBC 2020', method: [], combinations: [], skipped: [], notes: [],
			elements: [column('C1', [check({ name: 'Shear' }), required]), column('C2', [byNote]), column('C3', [passing])],
			summary: { checked: 3, passed: 1, failed: 2, skipped: 0, maxUtilisation: 1.08, governing: 'C1' },
		};
		assert.deepStrictEqual({
			members: secondOrderRequiredMembers(report),
			flags: [required, byNote, passing].map(isSecondOrderRequired),
			order: sortedChecks(report.elements[0]).map(c => c.name),
			none: secondOrderRequiredMembers(undefined),
			values: [neglected, required].map(formatCheckValues),
		}, {
			members: ['C1', 'C2'], flags: [true, true, false], order: [required.name, 'Shear'], none: [],
			values: ['k lu / r 21.83 against 39.40 (slenderness may be neglected)', '1.00 against 2.00'],
		});
	});

	test('the response spectrum scaled to the share of the static base shear', () => {
		const bare: IFemSeismicDesign = { scale: { x: 1.25, y: null, vStatic: null, vDynamic: null, fraction: 0.85, clause: 'BNBC' }, combinations: [] };
		assert.deepStrictEqual({
			x: describeScale(seismic, 'x'),
			y: describeScale(seismic, 'y'),
			bare: describeScale(bare, 'x'),
			noY: describeScale(bare, 'y'),
			unavailable: describeScale({ ...seismic, available: false }, 'x'),
			absent: describeScale(undefined, 'x'),
			axes: ['RX: Response spectrum X', 'RY: Response spectrum Y', 'EY', 'Response spectrum X', 'EXTRA', 'D: Dead load'].map(spectrumAxis),
			combinations: seismic.combinations!.map(c => [combinationName(c), combinationDetail(c)]),
			orthogonal: [describeOrthogonal(seismic), describeOrthogonal({ orthogonal: false }), describeOrthogonal({})],
			torsion: [
				describeTorsion(seismic),
				describeTorsion({ torsion: { X: [], Y: [] } }),
				describeTorsion({ torsion: { X: [{ z: 3.2, force: 0, L: 20, moment: 0 }], Y: [{ z: 3.2, force: 500, L: 0, moment: 0 }] } }),
				describeTorsion(undefined),
			],
			// Only an X spectrum case: the backend gives Y scale 1 and no dynamic base shear.
			oneDirection: describeScale({ ...seismic, scale: { ...seismic.scale!, y: 1, vDynamic: { x: 1080, y: 0 } } }, 'y'),
			noStatic: describeScale({ ...seismic, scale: { ...seismic.scale!, x: 1, vStatic: { x: 0, y: 1500 } } }, 'x'),
			// On the spectrum result itself: its values are unscaled.
			onResult: [describeScaleOnResult(seismic, 'x'), describeScaleOnResult(seismic, 'y')],
		}, {
			x: 'EX scaled × 1.18 to 85 % of the static base shear (dynamic 1,080 kN, static 1,500 kN), BNBC 2020 Part 6 Sec 2.5.9.4.',
			y: 'EY not scaled: its base shear is at least 85 % of the static one (dynamic 1,400 kN, static 1,500 kN), BNBC 2020 Part 6 Sec 2.5.9.4.',
			bare: 'EX scaled × 1.25 to 85 % of the static base shear, BNBC.',
			noY: undefined,
			unavailable: undefined,
			absent: undefined,
			axes: ['x', 'y', 'y', 'x', undefined, undefined],
			combinations: [['1.2D + 1.0L ± 1.0E(RS EX + 0.3EY)', undefined], ['0.9D ± 1.0E(RS EX + 0.3EY)', 'Sec 2.7.3.1 no. 7']],
			orthogonal: ['100 % + 30 % (Sec 2.5.13.1(b))', 'one direction at a time', undefined],
			torsion: ['5 % eccentricity, static torsion cases AX', undefined, undefined, undefined],
			oneDirection: undefined,
			noStatic: 'EX not scaled: there is no equivalent static base shear to compare it with.',
			onResult: [
				'EX scaled × 1.18 to 85 % of the static base shear (dynamic 1,080 kN, static 1,500 kN), BNBC 2020 Part 6 Sec 2.5.9.4. Shown unscaled: the factor applies to the design forces, not to these results or the drifts.',
				'EY not scaled: its base shear is at least 85 % of the static one (dynamic 1,400 kN, static 1,500 kN), BNBC 2020 Part 6 Sec 2.5.9.4.',
			],
		});
	});

	test('the drift from the scaled spectrum, and the drift amplification of a P-Delta run', () => {
		const pDelta: IFemSecondOrder = {
			method: 'pDelta', stiffness: 'aci', cases: [
				{ case: 'EX', storeys: [{ from: 0, to: 3.2, ratio: 1.03 }, { from: 3.2, to: 6.4, ratio: 1.06 }] },
				{ case: 'EY', storeys: [{ from: 0, to: 3.2, ratio: 1.04 }, { from: 3.2, to: 6.4, ratio: 1.08 }] },
			],
		};
		assert.deepStrictEqual({
			drift: describeDrift(seismic),
			exceeds: describeDrift({ drift: [{ direction: 'X', bottom: 0, top: 3.2, ratio: 0.025, allowableRatio: 0.02, ok: false }] }),
			designDrift: describeDesignDrift({ ...seismic, amplification: 4.5 }),
			// Fixed decimals, so 0.10 % and 0.37 % line up.
			small: storeyDriftRows({ drift: [{ direction: 'X', bottom: 3.2, top: 6.4, ratio: 0.001 }, { direction: 'Y', bottom: 3.2, top: 6.4, ratio: 0.0037 }] }),
			storeys: storeyDriftRows(seismic),
			noDrift: describeDrift({ ...seismic, drift: null }),
			secondOrder: describeSecondOrder(pDelta),
			noCases: describeSecondOrder({ cases: [] }),
			firstOrder: describeSecondOrder({ method: 'none', cases: pDelta.cases }),
			absent: describeSecondOrder(undefined),
			amplification: storeyAmplificationRows(pDelta),
			firstOrderRows: storeyAmplificationRows({ method: 'none', cases: pDelta.cases }),
			references: ['EX-1: Earthquake X, first order (P-Delta reference)', 'EX: Earthquake X', 'DL-1: Dead load 1'].map(isFirstOrderReference),
		}, {
			drift: 'Largest drift 0.62 % (allowed 2.00 %) at 3.2 to 6.4 m, Y.',
			exceeds: 'Largest drift 2.50 % (allowed 2.00 %) at 0 to 3.2 m, X: exceeds the allowed drift.',
			designDrift: 'Largest drift 0.62 % (allowed 2.00 %) at 3.2 to 6.4 m, Y. Design drift = spectrum drift × Cd / I (Cd / I = 4.50).',
			small: [{ name: '3.2 to 6.4 m', value: '0.10 % X, 0.37 % Y' }],
			storeys: [{ name: '0 to 3.2 m', value: '0.41 % X, 0.38 % Y' }, { name: '3.2 to 6.4 m', value: '0.52 % X, 0.62 % Y' }],
			noDrift: undefined,
			secondOrder: 'Second order (P-Delta, cracked section stiffness): storey drifts amplified up to × 1.08 (EY, 3.2 to 6.4 m).',
			noCases: 'Second order (P-Delta).',
			firstOrder: undefined,
			absent: undefined,
			amplification: [{ name: '0 to 3.2 m', value: '× 1.03 EX, × 1.04 EY' }, { name: '3.2 to 6.4 m', value: '× 1.06 EX, × 1.08 EY' }],
			firstOrderRows: [],
			references: [true, false, false],
		});
	});

	test('the seismic design section: full, without a spectrum (heading and why), and absent', () => {
		const lines = (design: IFemSeismicDesign | undefined, combinations: boolean) =>
			seismicSection(design, 'x', combinations).map(i => i.kind === 'row' ? `${i.name}: ${i.value}` : i.kind === 'combination' ? `+ ${i.name}${i.detail ? ` (${i.detail})` : ''}` : `${i.kind}: ${i.text}`);
		const unavailable: IFemSeismicDesign = { available: false, notes: ['No response spectrum results: enable Response spectrum in the analysis settings.'] };
		assert.deepStrictEqual({
			result: lines({ ...seismic, drift: seismic.drift!.slice(0, 2), notes: ['ρ = 1.0'] }, false),
			summary: lines(seismic, true).slice(-3),
			unavailable: lines(unavailable, true),
			absent: lines(undefined, true),
		}, {
			result: [
				'heading: Seismic Design (Response Spectrum)',
				'note: EX scaled × 1.18 to 85 % of the static base shear (dynamic 1,080 kN, static 1,500 kN), BNBC 2020 Part 6 Sec 2.5.9.4.',
				'Seismic Design Category: D',
				'note: Orthogonal effects: 100 % + 30 % (Sec 2.5.13.1(b)).',
				'note: Accidental torsion: 5 % eccentricity, static torsion cases AX.',
				'note: Largest drift 0.41 % (allowed 2.00 %) at 0 to 3.2 m, X.',
				'0 to 3.2 m: 0.41 % X, 0.38 % Y',
				'note: ρ = 1.0',
			],
			summary: [
				'heading: Seismic Combinations',
				'+ 1.2D + 1.0L ± 1.0E(RS EX + 0.3EY)',
				'+ 0.9D ± 1.0E(RS EX + 0.3EY) (Sec 2.7.3.1 no. 7)',
			],
			unavailable: ['heading: Seismic Design (Response Spectrum)', 'note: No response spectrum results: enable Response spectrum in the analysis settings.'],
			absent: [],
		});
	});
});
