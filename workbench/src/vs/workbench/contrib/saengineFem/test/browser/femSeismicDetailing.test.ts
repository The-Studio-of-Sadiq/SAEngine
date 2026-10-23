/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IFemDesignCheck, IFemDesignElement } from '../../browser/femDesign.js';
import { describeBars, describeTransverseSpacing } from '../../browser/femDesignProposal.js';
import { columnEndJoints, describeJointsSummary, describeScwb, describeJointVerdict, detailingGroup, detailingSection, FemDetailingElement, FemDetailingReport, generalChecks, IFemDetailingModel, IFemJoint, jointAtNode, jointColouring, jointGoverning, jointItems, jointsOf, jointsOfMember, scwbUtilisation } from '../../browser/femSeismicDetailing.js';

function check(fields: Partial<IFemDesignCheck> & Record<string, unknown>): IFemDesignCheck {
	return { name: 'Check', demand: 1, capacity: 2, unit: '', utilisation: 0.5, combination: null, ok: true, note: '', flag: false, ...fields } as IFemDesignCheck;
}

/*
 * Synthetic data, worked by hand (BNBC 2020 Part 6 Sec 8.3). A special moment frame in SDC D:
 *
 * Beam B1 300 × 500 mm, d = 444 mm, Ø20 bars, Ø10 hoops:
 * - width 300 ≥ 250 mm (8.3.4.1(d)(i), p1091): 250 / 300 = 0.83;
 * - ρ = 0.0105 ≤ 0.025 (8.3.4.2(a), p1091): 0.0105 / 0.025 = 0.42;
 * - hoops in lo (8.3.4.3(b), p1093): so = min(d/4 = 111, 8 × 20 = 160, 24 × 10 = 240, 300)
 *   = 111 mm, provided 150 mm: 150 / 111 = 1.35, fails; lo = 2h = 1,000 mm (8.3.4.3(a)(i));
 *   elsewhere d/2 = 222 mm (8.3.4.3(c));
 * - capacity shear Ve = 185.0 kN against φVn = 240.0 kN: 0.77.
 *
 * Joints (z up; storeys at 3.2 and 6.4 m): J1 at node 2 (C0 below, beam B1), J2 at node 3
 * (C1 below, beam B2). C0 and B1 are each split into two analysis segments (C0: 10 from the base
 * to node 6, 12 from node 6 up to J1; B1: 20 from J1 to node 7, 22 from node 7 on), so the joints
 * view colours only the segments touching the joint's node (12 and 20), not the far ones.
 * Strong column / weak beam ΣMnc ≥ 1.2 ΣMnb (8.3.5.2(b), Eq 6.8.5, p1096):
 * - J1 along X: 600 / 400 = 1.50, 1.2 / 1.5 = 0.80; along Y 1.10: 1.2 / 1.1 = 1.09, fails;
 *   joint shear 850 / 1,020 = 0.83: governs Y, 1.09;
 * - J2 along X 2.00: 1.2 / 2 = 0.60; joint shear 300 / 600 = 0.50: governs X, 0.60.
 */
const B1: FemDetailingElement = {
	id: 'B1', kind: 'beam', type: 'B300x500', members: [20, 22], utilisation: 1.3514, ok: false,
	checks: [
		check({ name: 'Flexure (sagging)', demand: 120, capacity: 180, unit: 'kN·m', utilisation: 0.6667 }),
		check({ name: 'Detailing: width', demand: 250, capacity: 300, unit: 'mm', utilisation: 0.8333, clause: 'Sec 8.3.4.1(d)(i)' }),
		check({ name: 'Detailing: longitudinal steel ratio', demand: 0.0105, capacity: 0.025, utilisation: 0.42, clause: 'Sec 8.3.4.2(a)' }),
		check({ name: 'Detailing: hoop spacing in lo', demand: 150, capacity: 111, unit: 'mm', utilisation: 1.3514, ok: false, clause: 'Sec 8.3.4.3(b)', note: 'so = min(d/4, 8 db, 24 dh, 300 mm) = 111 mm' }),
		check({ name: 'Detailing: lap splice away from joints', demand: 2000, capacity: 1000, unit: 'mm', utilisation: 0, flag: true }),
	],
	detailing: { frameType: 'special', sdc: 'D', zones: { lo: 1000, so: 111, outside: 222 }, Ve: 185, phiVn: 240 },
};
const C0: FemDetailingElement = { id: 'C0', kind: 'column', type: 'C500', members: [10, 12], utilisation: 0.7, ok: true, checks: [check({ name: 'P-M interaction', utilisation: 0.7 })] };
const C1: FemDetailingElement = { ...C0, id: 'C1', members: [11], detailing: { frameType: 'SMF', sdc: 'D' } };
const B2: FemDetailingElement = { ...C0, id: 'B2', kind: 'beam', type: 'B300x500', members: [21] };
const J1: IFemJoint = { id: 'J1', node: 2, column: 'C0', beams: ['B1'], type: 'exterior', scwb: { x: { sumMnc: 600, sumMnb: 400 }, y: 1.1 }, shear: { Vj: 850, phiVn: 1020 }, notes: ['Confined on 2 faces'] };
const J2: IFemJoint = { id: 'J2', node: '3', column: 'C1', beams: ['B2'], type: 'corner', scwb: { x: 2 }, shear: { Vj: 300, phiVn: 600 } };

const REPORT: FemDetailingReport = {
	code: 'BNBC 2020', method: [], combinations: [], skipped: [], notes: [],
	elements: [C0, C1, B1, B2],
	summary: { checked: 4, passed: 3, failed: 1, skipped: 0, maxUtilisation: 1.3514, governing: 'B1' },
	joints: [J1, J2],
};

const MODEL: IFemDetailingModel = {
	nodes: [
		{ id: 1, coords: [0, 0, 0] }, { id: 2, coords: [0, 0, 3.2] }, { id: 3, coords: [0, 0, 6.4] },
		{ id: 4, coords: [5, 0, 3.2] }, { id: 5, coords: [5, 0, 6.4] },
		{ id: 6, coords: [0, 0, 1.6] }, { id: 7, coords: [2.5, 0, 3.2] },
	],
	elements: [
		{ id: 10, nodes: [1, 6] }, { id: 12, nodes: [6, 2] }, { id: 11, nodes: [2, 3] },
		{ id: 20, nodes: [2, 7] }, { id: 22, nodes: [7, 4] }, { id: 21, nodes: [3, 5] },
	],
};

suite('SAEngine - FEM seismic detailing', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('a beam\'s detailing section groups its checks, with the hoop zones and Ve', () => {
		assert.deepStrictEqual(detailingSection(REPORT, B1, MODEL), [
			{ kind: 'heading', text: 'Seismic Detailing' },
			{ kind: 'row', name: 'Frame', value: 'Special moment frame (SDC D)' },
			{ kind: 'subheading', text: 'Dimensions' },
			{ kind: 'check', name: 'Width', value: '0.83', detail: '250 mm against 300 mm · Sec 8.3.4.1(d)(i)', ok: true },
			{ kind: 'subheading', text: 'Longitudinal Bars' },
			{ kind: 'check', name: 'Longitudinal steel ratio', value: '0.42', detail: '0.0105 against 0.025 · Sec 8.3.4.2(a)', ok: true },
			{ kind: 'subheading', text: 'Transverse Zones' },
			{ kind: 'row', name: 'Hoop zone lo', value: '1,000 mm from each joint face, hoops at 111 mm (so)' },
			{ kind: 'row', name: 'Elsewhere', value: 'hoops at 222 mm' },
			{ kind: 'check', name: 'Hoop spacing in lo', value: '1.35', detail: '150 mm against 111 mm · Sec 8.3.4.3(b)', ok: false, note: 'so = min(d/4, 8 db, 24 dh, 300 mm) = 111 mm' },
			{ kind: 'subheading', text: 'Splices' },
			{ kind: 'check', name: 'Lap splice away from joints', value: 'reported', detail: '2,000 mm against 1,000 mm', ok: true },
			{ kind: 'subheading', text: 'Shear' },
			{ kind: 'row', name: 'Capacity shear Ve', value: '185.0 kN against φVn 240.0 kN (0.77)', ok: true },
		]);
		assert.deepStrictEqual(generalChecks(B1.checks).map(c => c.name), ['Flexure (sagging)']);
	});

	test('a column\'s section gives the strong-column / weak-beam ratios at its top and bottom joints', () => {
		assert.deepStrictEqual(detailingSection(REPORT, C1, MODEL), [
			{ kind: 'heading', text: 'Seismic Detailing' },
			{ kind: 'row', name: 'Frame', value: 'Special moment frame (SDC D)' },
			{ kind: 'subheading', text: 'Strong Column / Weak Beam' },
			{ kind: 'row', name: 'Top (J2)', value: 'X: ΣMnc / ΣMnb = 2.00 ≥ 1.2', ok: true },
			{ kind: 'row', name: 'Bottom (J1)', value: 'X: ΣMnc / ΣMnb = 1.50 ≥ 1.2 (ΣMnc 600, ΣMnb 400 kN·m); Y: ΣMnc / ΣMnb = 1.10 < 1.2', ok: false },
		]);
		// Without the model: the joints naming it as their column only.
		assert.deepStrictEqual(columnEndJoints(REPORT, C1, undefined), { top: J2 });
	});

	test('a report without seismic detailing shows nothing of it', () => {
		const plain: IFemDesignElement = { ...C0, checks: [check({ name: 'Detailing is not a prefix here' })] };
		const report = { ...REPORT, joints: undefined };
		assert.deepStrictEqual([detailingSection(report, plain, undefined), jointsOf(report), jointColouring(report, MODEL)], [[], [], {}]);
		assert.strictEqual(describeJointsSummary(report), 'No beam-column joints are checked: the joint shear and strong-column/weak-beam checks apply to special moment frames (BNBC 2020 Part 6 Sec 8.3.5.2, 8.3.7).');
	});

	test('joints: governing check, colours of the members framing in, summary and selection', () => {
		assert.deepStrictEqual({
			governing: [jointGoverning(J1)?.check, jointGoverning(J2)?.check],
			scwb: [scwbUtilisation(J1.scwb?.x), scwbUtilisation({ ratio: 1.5, utilisation: 0.9 }), scwbUtilisation(null)],
			colours: jointColouring(REPORT, MODEL),
			// Without the model, the whole members.
			coloursNoModel: jointColouring(REPORT, undefined),
			summary: describeJointsSummary(REPORT),
			atNode3: jointAtNode(REPORT, 3, MODEL)?.id,
			atNode1: jointAtNode(REPORT, 1, MODEL)?.id,
			ofB1: jointsOfMember(REPORT, 'B1').map(j => j.id),
			verdict: describeJointVerdict(J1),
		}, {
			governing: ['scwbY', 'scwbX'],
			scwb: [0.7999999999999999, 0.9, undefined],
			// Only the segments touching each joint's node: 12 (not 10) of C0, 20 (not 22) of B1.
			colours: { 12: 1.2 / 1.1, 20: 1.2 / 1.1, 11: 0.6, 21: 0.6 },
			// Without the model every segment of the joint's members.
			coloursNoModel: { 10: 1.2 / 1.1, 12: 1.2 / 1.1, 20: 1.2 / 1.1, 22: 1.2 / 1.1, 11: 0.6, 21: 0.6 },
			summary: '2 joints: 1 pass, 1 fail · largest utilisation 1.09 at J1 (strong column / weak beam along Y)',
			atNode3: 'J2',
			atNode1: undefined,
			ofB1: ['J1'],
			verdict: { ok: false, utilisation: '1.09', governing: 'strong column / weak beam along Y' },
		});
	});

	test('a joint\'s rows', () => {
		assert.deepStrictEqual(jointItems(J1), [
			{ kind: 'row', name: 'Column', value: 'C0' },
			{ kind: 'row', name: 'Beams', value: 'B1' },
			{ kind: 'row', name: 'Joint shear', value: '850.0 kN against φVn 1,020.0 kN (0.83)', ok: true },
			{ kind: 'row', name: 'SCWB along X', value: 'ΣMnc / ΣMnb = 1.50 ≥ 1.2 (ΣMnc 600, ΣMnb 400 kN·m)', ok: true },
			{ kind: 'row', name: 'SCWB along Y', value: 'ΣMnc / ΣMnb = 1.10 < 1.2', ok: false },
			{ kind: 'note', text: 'Confined on 2 faces' },
		]);
	});

	test('a strong-column / weak-beam ratio near the limit never reads against its verdict', () => {
		// 1.196 fails 1.2: shown rounded down, 1.19 < 1.2 (not "1.20 < 1.2"); 1.2 itself passes;
		// 1.15 (114.999... × 100 in floating point) still reads 1.15; 1.247 against 1.25 reads 1.24.
		assert.deepStrictEqual([1.196, 1.2, 1.15, 1.5049, { ratio: 1.247, required: 1.25 }].map(scwb => describeScwb(scwb)), [
			{ value: 'ΣMnc / ΣMnb = 1.19 < 1.2', ok: false },
			{ value: 'ΣMnc / ΣMnb = 1.20 ≥ 1.2', ok: true },
			{ value: 'ΣMnc / ΣMnb = 1.15 < 1.2', ok: false },
			{ value: 'ΣMnc / ΣMnb = 1.50 ≥ 1.2', ok: true },
			{ value: 'ΣMnc / ΣMnb = 1.24 < 1.25', ok: false },
		]);
	});

	test('a strong-column / weak-beam ratio the rule does not require is reported, not failed', () => {
		const scwb = { ratio: 0.902, required: 1.2, notRequired: true };
		assert.deepStrictEqual([describeScwb(scwb), scwbUtilisation(scwb)], [
			{ value: 'ΣMnc / ΣMnb = 0.90, not required (Pu ≤ 0.1 Ag f\'c, Sec 8.3.5.2(a))', ok: true },
			0,
		]);
	});

	test('detailing checks are grouped by their names', () => {
		const names = ['Detailing: clear span to depth ln/d', 'Detailing: Ash in lo', 'Detailing: tie spacing so', 'Detailing: lap splice in centre half', 'Detailing: shear Ve', 'Detailing: strong column at joint', 'Detailing: concrete strength'];
		assert.deepStrictEqual(names.map(name => detailingGroup(check({ name }))), ['dimensions', 'transverse', 'transverse', 'splices', 'shear', 'joints', 'other']);
	});

	test('the proposal shows hoop zones when the backend proposes them', () => {
		const transverse = { type: 'stirrup' as const, dia: 10, spacing: 150, legs: 4 };
		assert.deepStrictEqual([
			describeTransverseSpacing(transverse),
			describeTransverseSpacing({ ...transverse, zone: { spacing: 100, length: 600 } }),
			describeTransverseSpacing({ ...transverse, zone: { spacing: 100, length: null } }),
			describeBars({ longitudinal: [{ position: 'top', count: 4, dia: 20 }], transverse: { ...transverse, zone: { spacing: 100, length: 1000 } } }),
		], [
			'150',
			'100 over 600 at each end, 150 elsewhere',
			'100 within lo at each end, 150 elsewhere',
			'4 Ø20 top, Ø10 @ 100 over 1000 at each end, 150 elsewhere (4 legs)',
		]);
	});
});
