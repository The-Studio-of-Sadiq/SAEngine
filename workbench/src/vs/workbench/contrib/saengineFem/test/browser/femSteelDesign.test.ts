/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IFemDesignCheck, IFemDesignElement, IFemDesignReport } from '../../browser/femDesign.js';
import { DesignProposalModel, describeSteelProposal, IFemDesignProposal, steelProposalOf } from '../../browser/femDesignProposal.js';
import { FemDetailingItem } from '../../browser/femSeismicDetailing.js';
import { describeSteelSummary, FemSteelElement, governingSteelCheck, isConnectionCheck, ltbZone, steelSection } from '../../browser/femSteelDesign.js';

function check(fields: Partial<IFemDesignCheck> & Record<string, unknown>): IFemDesignCheck {
	return { name: 'Check', demand: 1, capacity: 2, unit: '', utilisation: 0.5, combination: null, ok: true, note: '', flag: false, ...fields } as IFemDesignCheck;
}

/** The items as lines, to compare in one snapshot. */
function lines(items: readonly FemDetailingItem[]): string[] {
	return items.map(item => {
		switch (item.kind) {
			case 'heading': return `# ${item.text}`;
			case 'subheading': return `## ${item.text}`;
			case 'note': return `> ${item.text}`;
			case 'row': return `${item.name}: ${item.value}${item.ok === false ? ' !' : ''}`;
			case 'check': return `[${item.ok ? 'ok' : 'FAIL'}] ${item.name} ${item.value} (${item.detail})`;
		}
	});
}

/*
 * Stand-in data (the backend's steel design is written in the same round; the values are
 * illustrative, not worked to the code): beam B7, a W16X31 of A992 (Fy 345 MPa), Lb 3,000 mm
 * between Lp 1,520 and Lr 4,460 mm: inelastic lateral-torsional buckling with Cb 1.14.
 * Its shear tab at both ends passes; brace BR1 (SHS) fails its gusset's block shear.
 */
const B7: FemSteelElement = {
	id: 'B7', kind: 'beam', type: 'W16X31', members: [7], ok: true, utilisation: 0.86,
	checks: [
		check({ name: 'Flexure, lateral-torsional buckling', demand: 152.4, capacity: 177.2, unit: 'kN·m', utilisation: 0.86, combination: '1.2D+1.6L', clause: 'BNBC 2020 Part 6 Sec 10.6.2' }),
		check({ name: 'Shear', demand: 98, capacity: 591, unit: 'kN', utilisation: 0.166, combination: '1.2D+1.6L' }),
		check({ name: 'Connection: bolt shear', demand: 98, capacity: 190, unit: 'kN', utilisation: 0.516, combination: '1.2D+1.6L' }),
	],
	steel: {
		section: 'W16X31', family: 'W', material: 'A992', Fy: 345, Fu: 450, mass: 46.1,
		sectionClass: { flange: 'compact', web: 'compact', flangeRatio: 6.3, flangeLimits: [9.2, 24.1] },
		lengths: { L: 6000, Lb: 3000, Lp: 1520, Lr: 4460 },
		Cb: 1.14,
		connections: [{
			name: 'Shear tab', end: 'both', description: '3 M20 8.8 bolts, 10 mm plate, 6 mm fillet welds',
			checks: [
				check({ name: 'Bolt shear', demand: 98, capacity: 190, unit: 'kN', utilisation: 0.516, combination: '1.2D+1.6L' }),
				check({ name: 'Weld', demand: 98, capacity: 260, unit: 'kN', utilisation: 0.377, combination: '1.2D+1.6L' }),
			],
			assumptions: ['simple (pinned) end', 'eccentricity 75 mm to the bolt line'],
		}],
	},
} as FemSteelElement;

const BR1: FemSteelElement = {
	id: 'BR1', kind: 'brace', type: 'SHS 100x100x5', members: [21], ok: false, utilisation: 1.12,
	checks: [check({ name: 'Compression, flexural buckling', demand: 310, capacity: 352, unit: 'kN', utilisation: 0.88, combination: '0.9D+1.0E', clause: 'BNBC 2020 Part 6 Sec 10.5.3' })],
	steel: {
		section: 'SHS 100x100x5', family: 'SHS', material: 'A500 Gr B', Fy: 315,
		sectionClass: { compression: 'nonslender' },
		lengths: { L: 5000, Kx: 1, Ky: 1, KLr: 128.2, KLrLimit: 200 },
		connections: [{ name: 'Gusset plate', end: 'i', checks: [check({ name: 'Block shear', demand: 310, capacity: 277, unit: 'kN', utilisation: 1.12, combination: '0.9D+1.0E', ok: false })] }],
	},
} as FemSteelElement;

/*
 * The backend's own shapes, copied from its output for its synthetic test models: beam B1 of
 * python/tests/test_design_steel_frame.py as design_steel_member gives it (checks trimmed to
 * those the panel reads), with a fin plate of design/steel_connections.py check_fin_plate
 * (three of its checks) attached as the integrator would, and one of them repeated among the
 * member's own checks.
 */
const FIN_BOLT = check({ name: 'bolt shear (most loaded bolt)', demand: 41.53, capacity: 77.75, unit: 'kN', utilisation: 0.534, combination: '1.2D+1.0WX', note: 'Eq 6.10.168; elastic method, e = 60 mm, 3 bolts' });
const T_B1 = {
	id: 'B1', kind: 'beam', type: 'BM', members: [3], utilisation: 0.27, ok: true,
	checks: [
		check({ name: 'Tension: yielding (gross section)', demand: 83.0, capacity: 2842.24, unit: 'kN', utilisation: 0.029, combination: '0.9D-1.0WX', note: 'Ag = 9154 mm², Fy = 345 MPa; B1 at 0.00 L', clause: 'BNBC 2020 Part 6 Sec 10.4.2(a), Eq 6.10.11' }),
		check({ name: 'Tension: rupture (net section)', demand: 83.0, capacity: 2780.45, unit: 'kN', utilisation: 0.03, combination: '0.9D-1.0WX', note: 'An = 9154 mm² (= Ag), U = 0.90 (Case 7, flanges connected, 3 or more fasteners per line), Ae = 8238 mm², Fu = 450 MPa; B1 at 0.00 L', clause: 'BNBC 2020 Part 6 Sec 10.4.2(b), Eqs 6.10.12-13, Table 6.10.2' }),
		check({ name: 'Flexure about x (major)', demand: 70.11, capacity: 302.53, unit: 'kN·m', utilisation: 0.232, combination: '1.2D+1.0WX', note: 'Mn = 336.1 kN·m (yielding); also lateral-torsional buckling 336.1 kN·m; flange λ = 8.9 (λp = 9.1, λr = 24.1, case 1): compact; web λ = 26.2 (λp = 90.5, λr = 137.2, case 9): compact; Lb = 6000 mm, Lp = 2759 mm, Lr = 9483 mm, Cb = 1.25; B1 = 1.02 / 1.06; B1 at 0.50 L', clause: 'BNBC 2020 Part 6 Sec 10.6.2.1, Eq 6.10.56' }),
		check({ name: 'Axial force and flexure (H1)', demand: 0.27, capacity: 1.0, unit: '', utilisation: 0.27, combination: '1.2D+1.0WX', note: 'Eq 6.10.147b: Pr = 116.4 kN (compression), Pc = 1526.8 kN, Mrx = 70.1 / Mcx = 302.5, Mry = 0.0 / Mcy = 143.5 kN·m; B1 = 1.02 / 1.06; B1 at 0.50 L', clause: 'BNBC 2020 Part 6 Sec 10.8.1, Eq 6.10.147b' }),
		check({ name: 'Slenderness KL/r (compression)', demand: 92.16, capacity: 150.0, unit: '', utilisation: 0.614, combination: '1.2D+1.0WX', note: 'K = 1 / 1, L = 6000 / 6000 mm; B1 at 0.00 L', flag: true, clause: 'BNBC 2020 Part 6 Sec 10.5.2' }),
		{ ...FIN_BOLT, utilisation: 0.95 },
	],
	section: {
		family: 'I', label: 'I 254x254x8.6/14.2', area: 9153.8, class: 'compact',
		elements: ['flange λ = 8.9 (λr = 13.5, case 3): compact', 'web λ = 26.2 (λr = 35.9, case 10): compact'],
		massPerMetre: 71.86, notes: [],
	},
	lengths: 'unbraced lengths: about x 6.00 m, about y 6.00 m, LTB 6.00 m (top flange in compression) / 6.00 m (bottom); K = 1 / 1',
	connections: [{
		connection: 'finPlate',
		checks: [
			FIN_BOLT,
			check({ name: 'plate block shear', demand: 76.49, capacity: 265.88, unit: 'kN', utilisation: 0.288, combination: '1.2D+1.0WX', note: 'Eq 6.10.178, Ubs = 1' }),
			check({ name: 'welds to the support', demand: 361.44, capacity: 916.27, unit: 'N/mm', utilisation: 0.394, combination: '1.2D+1.0WX', note: 'Eq 6.10.162-163, θ = 0 (conservative), elastic line method' }),
		],
		utilisation: 0.534, ok: true,
		assumptions: ['one vertical line of bolts in standard holes, bearing-type, single shear', 'beam web uncoped; the support strong enough for the welds'],
	}],
} as unknown as IFemDesignElement;

suite('SAEngine steel member checks', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('a beam: class, Lb against Lp and Lr, Cb, governing clause, shear tab', () => {
		assert.deepStrictEqual(lines(steelSection(B7)), [
			'# Steel Member',
			'Section: W16X31 (46.1 kg/m)',
			'Material: A992, Fy 345 MPa, Fu 450 MPa',
			'Flange: compact (λ 6.3, λp 9.2, λr 24.1)',
			'Web: compact',
			'Unbraced length Lb: 3,000 mm (Lp 1,520 mm, Lr 4,460 mm)',
			'Lateral-torsional buckling: Lp < Lb ≤ Lr: inelastic lateral-torsional buckling',
			'Cb: 1.14',
			'Governing: Flexure, lateral-torsional buckling 0.86 (BNBC 2020 Part 6 Sec 10.6.2)',
			'# Connections',
			'## Shear tab, both ends: passes',
			'> 3 M20 8.8 bolts, 10 mm plate, 6 mm fillet welds',
			'[ok] Bolt shear 0.52 (98.0 of 190.0 kN, 1.2D+1.6L)',
			'[ok] Weld 0.38 (98.0 of 260.0 kN, 1.2D+1.6L)',
			'> Assumes: simple (pinned) end; eccentricity 75 mm to the bolt line.',
		]);
		assert.deepStrictEqual([governingSteelCheck(B7)?.name, isConnectionCheck(B7.checks[2]), ltbZone({ section: 'x', lengths: { Lb: 1000, Lp: 1500, Lr: 4000 } })], ['Flexure, lateral-torsional buckling', true, 'yielding']);
	});

	test('a brace: KL/r against its limit, a failing gusset; the summary', () => {
		assert.deepStrictEqual(lines(steelSection(BR1)), [
			'# Steel Member',
			'Section: SHS 100x100x5',
			'Material: A500 Gr B, Fy 315 MPa',
			'In compression: nonslender',
			'Effective length factor: Kx 1.00, Ky 1.00',
			'KL / r: 128.2 ≤ 200',
			'Governing: Compression, flexural buckling 0.88 (BNBC 2020 Part 6 Sec 10.5.3)',
			'# Connections',
			'## Gusset plate, end i: fails',
			'[FAIL] Block shear 1.12 (310.0 of 277.0 kN, 0.9D+1.0E)',
		]);
		const concrete: IFemDesignElement = { id: 'C1', kind: 'column', type: 'C400', members: [1], checks: [], utilisation: 0.5, ok: true };
		const report = { elements: [B7, BR1, concrete], skipped: [] } as unknown as IFemDesignReport;
		assert.deepStrictEqual([describeSteelSummary(report), steelSection(concrete)], ['2 checked, 1 fail; connections fail at BR1', []]);
	});

	test('reads the member entry design_steel_member gives, with a fin plate of check_connection', () => {
		assert.deepStrictEqual(lines(steelSection(T_B1)), [
			'# Steel Member',
			'Section: I 254x254x8.6/14.2 (71.9 kg/m)',
			'Material: Fy 345 MPa, Fu 450 MPa',
			'Flange: compact (λ 8.9, λp 9.1, λr 24.1)',
			'Web: compact (λ 26.2, λp 90.5, λr 137.2)',
			'In compression: nonslender',
			'> unbraced lengths: about x 6.00 m, about y 6.00 m, LTB 6.00 m (top flange in compression) / 6.00 m (bottom); K = 1 / 1',
			'Unbraced length Lb: 6,000 mm (Lp 2,759 mm, Lr 9,483 mm)',
			'Lateral-torsional buckling: Lp < Lb ≤ Lr: inelastic lateral-torsional buckling',
			'Cb: 1.25',
			'Effective length factor: Kx 1.00, Ky 1.00',
			'KL / r: 92.2 ≤ 150',
			'Interaction Eq 6.10.147b: 0.27 (Pr/Pc 0.08, Mrx/Mcx 0.23, Mry/Mcy 0.00)',
			'Governing: Axial force and flexure (H1) 0.27 (BNBC 2020 Part 6 Sec 10.8.1, Eq 6.10.147b)',
			'# Connections',
			'## Fin plate (shear tab): passes',
			'[ok] bolt shear (most loaded bolt) 0.53 (41.5 of 77.8 kN, 1.2D+1.0WX)',
			'[ok] welds to the support 0.39 (361.4 of 916.3 N/mm, 1.2D+1.0WX)',
			'[ok] plate block shear 0.29 (76.5 of 265.9 kN, 1.2D+1.0WX)',
			'> Assumes: one vertical line of bolts in standard holes, bearing-type, single shear; beam web uncoped; the support strong enough for the welds.',
		]);
		// The connection's check repeated among the member's own (at 0.95) is not its governing check.
		const report = { elements: [T_B1], skipped: [] } as unknown as IFemDesignReport;
		assert.deepStrictEqual([governingSteelCheck(T_B1)?.name, describeSteelSummary(report)], ['Axial force and flexure (H1)', '1 checked, 0 fail']);
	});

	test('reads the RC-shaped entries of steel_design_proposal', () => {
		const label = (section: string, mass: number) => ({ section, family: 'SHS', text: `${section} (${mass.toFixed(1)} kg/m)`, profile: { shape: 'rectangleHollow' }, mass });
		const proposal = {
			types: [
				{
					type: 'BR-SHS', kind: 'brace', name: 'Brace SHS 150', current: label('SHS 150x150x8', 33.95), proposed: label('SHS 140x140x4', 16.76), status: 'ok',
					governingMember: 'E1', members: ['E1', 'E2'], family: 'SHS', tooSmall: null, notes: ['-17.2 kg/m against SHS 150x150x8'],
					utilisation: { 'Tension: rupture (net section)': 0.701, 'Compression: buckling': 0.927, 'Axial force and flexure (H1)': 0.927, 'Slenderness L/r (tension)': 0.24 },
				},
				{
					type: 'BR-2', kind: 'brace', name: 'Brace', current: label('SHS 150x150x8', 33.95), proposed: null, status: 'tooSmall',
					governingMember: 'E1', members: ['E1', 'E2'], utilisation: {}, family: 'SHS', notes: [],
					tooSmall: { reason: 'no SHS section passes: the largest, SHS 300x300x12.5, is at 2.00 (member E1)', suggestion: null },
				},
			],
		} as unknown as IFemDesignProposal;
		const model = new DesignProposalModel();
		model.setProposal('byType', proposal);
		assert.deepStrictEqual(model.rows().map(r => ({ current: r.current, proposed: r.proposed, tooSmall: r.tooSmall, included: r.included, family: r.steel?.family, facts: r.steel && describeSteelProposal(r.steel), warnings: r.warnings })), [
			{ current: 'SHS 150x150x8', proposed: 'SHS 140x140x4', tooSmall: false, included: true, family: 'SHS', facts: '34.0 kg/m → 16.8 kg/m (51% lighter), utilisation 0.93, governed by Compression: buckling', warnings: [] },
			{ current: 'SHS 150x150x8', proposed: 'no SHS section passes', tooSmall: true, included: false, family: 'SHS', facts: '34.0 kg/m', warnings: ['Section too small: no SHS section passes: the largest, SHS 300x300x12.5, is at 2.00 (member E1)'] },
		]);
		// A concrete type stays a bars row.
		assert.strictEqual(steelProposalOf({ type: 'B1', current: { text: '3 Ø16 bottom' }, proposed: '4 Ø16 bottom' }), undefined);
	});

	test('the proposal proposes the lightest passing section of the family', () => {
		const proposal: IFemDesignProposal = {
			types: [
				{ type: 'BR-SHS', kind: 'brace', current: null, proposed: null, status: 'ok', members: ['BR1', 'BR2'], governingMember: 'BR1', steel: { family: 'SHS', current: 'SHS 100x100x5', proposed: 'SHS 120x120x5', currentMass: 14.7, proposedMass: 17.8, currentUtilisation: 1.12, proposedUtilisation: 0.81, governingCheck: 'Compression, flexural buckling' } },
				{ type: 'B-W', kind: 'beam', current: null, proposed: null, status: 'ok', members: ['B7'], steel: { family: 'W', current: 'W16X31', proposed: 'W14X26', currentMass: 46.1, proposedMass: 38.7, currentUtilisation: 0.86, proposedUtilisation: 0.97 } },
				{ type: 'C-W', kind: 'column', current: null, proposed: null, members: ['C9'], steel: { family: 'W', current: 'W14X730', proposed: null, currentUtilisation: 1.4 } },
			],
		};
		const model = new DesignProposalModel();
		model.setProposal('byType', proposal);
		assert.deepStrictEqual(model.rows().map(r => ({ type: r.type, current: r.current, proposed: r.proposed, changed: r.changed, tooSmall: r.tooSmall, included: r.included, facts: r.steel && describeSteelProposal(r.steel) })), [
			{ type: 'BR-SHS', current: 'SHS 100x100x5', proposed: 'SHS 120x120x5', changed: true, tooSmall: false, included: true, facts: '14.7 kg/m → 17.8 kg/m (21% heavier), utilisation 1.12 → 0.81, governed by Compression, flexural buckling' },
			{ type: 'B-W', current: 'W16X31', proposed: 'W14X26', changed: true, tooSmall: false, included: true, facts: '46.1 kg/m → 38.7 kg/m (16% lighter), utilisation 0.86 → 0.97' },
			{ type: 'C-W', current: 'W14X730', proposed: 'no W section passes', changed: false, tooSmall: true, included: false, facts: 'utilisation 1.40' },
		]);
		assert.deepStrictEqual(model.applyRequest()?.types.map(t => t.apply), [true, true, false]);
	});
});
