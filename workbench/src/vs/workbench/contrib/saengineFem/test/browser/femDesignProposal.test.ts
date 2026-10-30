/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { describeDesignCounts, describeEngineError, describeNotChecked, describeSteel, describeSteelRatio, designArguments, IFemDesignReport, IFemDesignRequired, IFemSteelRequirement, isOtherFailure, otherFailureElements, requiredSteelOf, shortElements, tooSmallElements } from '../../browser/femDesign.js';
import { countFailing, describeBars, describeBeforeAfter, describeChange, describeFailing, describeTransverseSpacing, DesignProposalModel, failingItems, IFemDesignProposal, notFixedBy, proposalEdits } from '../../browser/femDesignProposal.js';

const B1_CURRENT = { material: 'B500', cover: 40, longitudinal: [{ position: 'top' as const, count: 3, dia: 16 }, { position: 'bottom' as const, count: 3, dia: 16 }], transverse: { type: 'stirrup' as const, dia: 10, spacing: 200, legs: 2 } };
const B1_PROPOSED = { material: 'B500', cover: 40, longitudinal: [{ position: 'top' as const, count: 4, dia: 20 }, { position: 'bottom' as const, count: 3, dia: 16 }], transverse: { type: 'stirrup' as const, dia: 10, spacing: 150, legs: 2 }, text: '4 Ø20 top, 3 Ø16 bottom, Ø10 @ 150' };

/**
 * As `saengine.design.proposal` reports it: B1 needs heavier bars (B3 governs, B4 needs much
 * less), B2 keeps its bars, C1 is too small. Foundations are 9 Substructure's (none here).
 */
const BY_TYPE: IFemDesignProposal = {
	mode: 'byType',
	types: [
		{ type: 'B1', kind: 'beam', name: 'Beam 250×500', current: { ...B1_CURRENT, text: '3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200' }, proposed: B1_PROPOSED, status: 'ok', governingMember: 'B3', members: ['B3', 'B4', 'B5'], overDesigned: ['B4'], tooSmall: null, notes: ['εt ≥ 0.004'] },
		{ type: 'B2', kind: 'beam', name: 'B2', current: { text: '3 Ø16 top, 3 Ø16 bottom' }, proposed: { text: '3 Ø16 top, 3 Ø16 bottom' }, status: 'unchanged', governingMember: 'B7', members: ['B7'], overDesigned: [], tooSmall: null, notes: [] },
		{ type: 'C1', kind: 'column', name: 'Column 250×250', current: null, proposed: null, status: 'tooSmall', governingMember: 'C2', members: ['C2'], overDesigned: [], tooSmall: { reason: 'no layout with ρ up to 0.08 carries the demand', suggestion: 'try 300 x 300 mm (+50 mm)' }, notes: [] },
	],
	newTypes: [],
	reassign: [],
	warnings: ['No bars entered on C1: checked with assumed bars.', 'C1: section too small — no layout with ρ up to 0.08 carries the demand'],
	notes: ['Foundations are designed in 9 Substructure: its Size Footings proposes their size and bars.'],
};

/**
 * The same, split, as the backend reports it: B4 moves to a new lighter type B1-2; B1 still
 * lists all its members and those over-designed by its single-type bars (`byType`), and its own
 * bars are designed for B3 and B5 only (B4 needed closer stirrups).
 */
const SPLIT: IFemDesignProposal = {
	...BY_TYPE,
	mode: 'splitTypes',
	types: [{ ...BY_TYPE.types[0], proposed: { text: '4 Ø20 top, 3 Ø16 bottom, Ø10 @ 200' }, byType: B1_PROPOSED, notes: ['split bars'] }, BY_TYPE.types[1]],
	newTypes: [{ type: 'B1-2', from: 'B1', kind: 'beam', name: 'Beam 250×500 (2)', proposed: { text: '3 Ø16 top, 2 Ø16 bottom, Ø10 @ 200' }, governingMember: 'B4', members: ['B4'] }],
	reassign: [{ member: 'B4', from: 'B1', to: 'B1-2', source: 'FB4' }],
	warnings: [],
};

suite('SAEngine - FEM design proposal', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('bars read as the backend describes them, or as the drawings write them', () => {
		assert.deepStrictEqual([
			describeBars(B1_PROPOSED),
			describeBars(B1_CURRENT),
			describeBars({ longitudinal: [{ position: 'perimeter', count: 8, dia: 20 }], transverse: { type: 'tie', dia: 10, spacing: 150, legs: 4 } }),
			describeBars({ bottomX: { dia: 10, spacing: 150 }, bottomY: { dia: 10, spacing: 200 }, topX: { dia: 10, spacing: 150 } }),
			describeBars('6 Ø20 around'),
			describeBars(null),
		], [
			'4 Ø20 top, 3 Ø16 bottom, Ø10 @ 150',
			'3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200',
			'8 Ø20 around, Ø10 @ 150 (4 legs)',
			'bottom Ø10 @ 150 X, Ø10 @ 200 Y; top Ø10 @ 150 X',
			'6 Ø20 around',
			'no bars',
		]);
	});

	test('rows: changed types are included, unchanged and too-small ones stay out, warnings go to their row', () => {
		const model = new DesignProposalModel();
		model.setProposal('byType', BY_TYPE);
		assert.deepStrictEqual({
			rows: model.rows().map(r => [r.key, r.current, r.proposed, r.changed, r.tooSmall, r.included, r.governingMember, r.members.length, r.overDesigned, r.warnings]),
			general: model.generalWarnings(),
		}, {
			rows: [
				['type:B1', '3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200', '4 Ø20 top, 3 Ø16 bottom, Ø10 @ 150', true, false, true, 'B3', 3, ['B4'], []],
				['type:B2', '3 Ø16 top, 3 Ø16 bottom', '3 Ø16 top, 3 Ø16 bottom', false, false, false, 'B7', 1, [], []],
				['type:C1', 'no bars', 'no bars proposed', false, true, false, 'C2', 1, [], ['Section too small: no layout with ρ up to 0.08 carries the demand; try 300 x 300 mm (+50 mm)']],
			],
			general: ['No bars entered on C1: checked with assumed bars.'],
		});
		assert.deepStrictEqual(model.generalNotes(), ['Foundations are designed in 9 Substructure: its Size Footings proposes their size and bars.']);
	});

	test('a type none of whose members the checks checked starts left out (X12)', () => {
		const model = new DesignProposalModel();
		model.setProposal('byType', BY_TYPE);
		model.setChecks(report([{ id: 'B7', type: 'B2', ok: true }, { id: 'C2', type: 'C1', ok: false }]));
		const left = model.rows()[0];
		model.setIncluded('type:B1', true);
		assert.deepStrictEqual({ left: [left.included, left.warnings], ticked: model.rows()[0].included }, {
			left: [false, ['The design checks checked none of its members: left out unless you include it.']],
			ticked: true,
		});
	});

	test('what still fails: members by their worst check, joints, and what the rows included leave (X4)', () => {
		const checks = report([{ id: 'B5', type: 'B1', ok: false, check: 'Deflection' }, { id: 'C2', type: 'C1', ok: false, check: 'P-M interaction' }], [
			{ id: 'J1', ok: false, shear: { Vj: 900, phiVn: 600, utilisation: 1.5 } },
			{ id: 'J2', ok: false, shear: { Vj: 800, phiVn: 600, utilisation: 1.33 } },
			{ id: 'J3', ok: true, shear: { Vj: 100, phiVn: 600, utilisation: 0.17 } },
		], [
			{ name: 'System permitted in Seismic Design Category D (Table 6.2.19 row 3)', ok: false, flag: false },
			{ name: 'Height limit of the system in Category D (Table 6.2.19)', ok: false, flag: true },
		]);
		const model = new DesignProposalModel();
		model.setProposal('byType', BY_TYPE);
		assert.deepStrictEqual([
			describeFailing(failingItems(checks)),
			describeFailing(notFixedBy(model.rows(), checks)),
			failingItems(undefined),
		], [
			'System permitted in Seismic Design Category D (Table 6.2.19 row 3); B5 (Deflection); C2 (P-M interaction); joints J1, J2 (joint shear)',
			'System permitted in Seismic Design Category D (Table 6.2.19 row 3); C2 (P-M interaction); joints J1, J2 (joint shear)',
			[],
		]);
	});

	test('the design counts: members, then joints and building checks (X4)', () => {
		const base = { checked: 27, passed: 26, failed: 1, skipped: 0, maxUtilisation: 1.1, governing: 'C1' };
		assert.deepStrictEqual([
			describeDesignCounts({ ...base, elements: { checked: 18, passed: 18, failed: 0 }, joints: { checked: 6, failed: 0 }, seismicChecks: 3, seismicChecksFailed: 1 }),
			describeDesignCounts({ ...base, elements: { checked: 18, passed: 17, failed: 1 }, joints: { checked: 0, failed: 0 }, seismicChecksFailed: 0 }),
			describeDesignCounts(base),
		], [
			'18 members pass, 0 fail; 6 joints, 0 fail; 1 building check fails',
			'17 members pass, 1 fail',
			'26 members pass, 1 fail',
		]);
	});

	test('the one count of the backend: members, joints and building checks apart; not checked by reason (N-X8)', () => {
		const counts = {
			members: { total: 657, checked: 629, passed: 629, failed: 0, notChecked: 28, byKind: { column: { total: 200, checked: 172, passed: 172, failed: 0, notChecked: 28 } } },
			joints: { checked: 172, passed: 152, failed: 20 },
			building: { checked: 3, passed: 3, failed: 0 },
			notChecked: { noBars: 28, other: 0 },
		};
		const summary = { checked: 804, passed: 784, failed: 20, skipped: 28, maxUtilisation: 0.93, governing: 'C-A1-L1', counts };
		assert.deepStrictEqual([
			describeDesignCounts(summary),
			describeNotChecked(summary),
			describeNotChecked({ ...summary, counts: { ...counts, notChecked: { noBars: 12, other: 16 } } }),
			describeNotChecked({ ...summary, counts: undefined, skipped: 1 }),
		], [
			'629 members pass, 0 fail; 172 joints, 20 fail',
			'28 members not checked for want of bars',
			'28 members not checked (12 for want of bars)',
			'1 member not checked',
		]);
	});

	test('a code pack the engine cannot use says to restart it (N-X17)', () => {
		assert.ok(describeEngineError('saengine.codes.registry.CodePackError: code pack \'bnbc2020\' cannot be used: basis: Extra inputs are not permitted').startsWith('The code pack cannot be used (code pack \'bnbc2020\''));
		assert.strictEqual(describeEngineError('ValueError: unknown result case'), 'ValueError: unknown result case');
	});

	test('what still fails, counted for the line over its ids (N-X21)', () => {
		const items = [
			...['J1', 'J2', 'J3'].map(id => ({ id, type: undefined, kind: 'joint' as const, what: 'strong column / weak beam' })),
			{ id: 'B5', type: 'B1', kind: 'member' as const, what: 'Deflection' },
		];
		assert.strictEqual(countFailing(items), '3 joints (strong column / weak beam); 1 member (Deflection)');
	});

	test('a column too small for joint shear offers its strength bars, left out until ticked (N-X5)', () => {
		const strength = { material: 'B420', cover: 40, longitudinal: [{ position: 'perimeter' as const, count: 8, dia: 16 }], transverse: { type: 'tie' as const, dia: 10, spacing: 150 }, text: '8Ø16, ties Ø10 @ 150' };
		const proposal: IFemDesignProposal = {
			...BY_TYPE,
			types: [{ ...BY_TYPE.types[2], tooSmall: { reason: 'joint shear at C2@3000', suggestion: 'try 450 x 450 mm (+50 mm)' }, strengthBars: strength }],
		};
		const model = new DesignProposalModel();
		model.setProposal('byType', proposal);
		const [row] = model.rows();
		assert.deepStrictEqual([row.tooSmall, row.strengthBars, row.changed, row.included, row.proposed], [true, true, true, false, '8Ø16, ties Ø10 @ 150']);
		assert.strictEqual(model.applyRequest(), undefined);
		model.setIncluded(row.key, true);
		const request = model.applyRequest();
		assert.deepStrictEqual([request?.types[0].apply, request?.types[0].applyStrengthBars], [true, true]);
	});

	test('ties of one spacing along the member are said once (X27)', () => {
		assert.deepStrictEqual([
			describeTransverseSpacing({ dia: 10, spacing: 75, zone: { spacing: 75, length: 1200 } }),
			describeTransverseSpacing({ dia: 10, spacing: 125, zone: { spacing: 75, length: 1000 } }),
		], ['75', '75 over 1000 at each end, 125 elsewhere']);
	});

	test('toggles: a row left out is marked apply false; an unchanged row cannot be included', () => {
		const model = new DesignProposalModel();
		model.setProposal('byType', BY_TYPE);
		model.setIncluded('type:B2', true);
		const flags = () => {
			const request = model.applyRequest();
			return request && request.types.map(t => `${t.type}:${t.apply}`);
		};
		const onlyB1 = flags();
		model.setIncluded('type:B1', false);
		const none = flags();
		model.setAllIncluded(true);
		assert.deepStrictEqual({ onlyB1, none, all: flags() }, {
			onlyB1: ['B1:true', 'B2:false', 'C1:false'],
			none: undefined,
			all: ['B1:true', 'B2:false', 'C1:false'],
		});
	});

	test('mode switch: each mode keeps its proposal and toggles; a new type left out keeps its members on bars for all of them', () => {
		const model = new DesignProposalModel();
		model.setProposal('byType', BY_TYPE);
		model.setIncluded('type:B1', false);
		model.mode = 'splitTypes';
		const fetched = model.has('splitTypes');
		model.setProposal('splitTypes', SPLIT);
		const rows = () => model.rows().map(r => [r.key, r.from, r.current, r.proposed, r.included, r.members.join(' '), r.overDesigned.join(' '), r.notes.join('; ')]);
		const split = rows();
		const request = model.applyRequest();
		model.setIncluded('new:B1-2', false);
		const withoutNewRows = rows();
		const withoutNew = model.applyRequest();
		model.mode = 'byType';
		assert.deepStrictEqual({
			fetched, split,
			request: [request?.mode, request?.newTypes?.map(t => t.apply), request?.reassign?.map(r => r.apply)],
			withoutNewRows,
			withoutNew: [withoutNew?.types.map(t => t.apply), withoutNew?.newTypes?.map(t => t.apply), withoutNew?.reassign?.map(r => r.apply)],
			byType: model.applyRequest(),
		}, {
			fetched: false,
			// B4 moved: B1 shows its staying members and its split bars.
			split: [
				['type:B1', undefined, '3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200', '4 Ø20 top, 3 Ø16 bottom, Ø10 @ 200', true, 'B3 B5', '', 'split bars'],
				['type:B2', undefined, '3 Ø16 top, 3 Ø16 bottom', '3 Ø16 top, 3 Ø16 bottom', false, 'B7', '', ''],
				['new:B1-2', 'B1', '3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200', '3 Ø16 top, 2 Ø16 bottom, Ø10 @ 200', true, 'B4', '', ''],
			],
			request: ['splitTypes', [true], [true]],
			// B4 stays in B1: B1 takes the bars for all its members (which the backend applies).
			withoutNewRows: [
				['type:B1', undefined, '3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200', '4 Ø20 top, 3 Ø16 bottom, Ø10 @ 150', true, 'B3 B4 B5', 'B4', 'Bars for all its members (the new type for B4 is left out).'],
				['type:B2', undefined, '3 Ø16 top, 3 Ø16 bottom', '3 Ø16 top, 3 Ø16 bottom', false, 'B7', '', ''],
				['new:B1-2', 'B1', '3 Ø16 top, 3 Ø16 bottom, Ø10 @ 200', '3 Ø16 top, 2 Ø16 bottom, Ø10 @ 200', false, 'B4', '', ''],
			],
			withoutNew: [[true, false], [false], [false]],
			// The other mode's toggles are its own: everything was left out there.
			byType: undefined,
		});
	});

	test('a type whose split-off members stay cannot be applied without its single-type bars', () => {
		const model = new DesignProposalModel('splitTypes');
		model.setProposal('splitTypes', { ...SPLIT, types: [{ ...SPLIT.types[0], byType: undefined }, SPLIT.types[1]] });
		const both = model.rows()[0];
		model.setIncluded('new:B1-2', false);
		const row = model.rows()[0];
		assert.deepStrictEqual({
			both: [both.included, both.blocked],
			kept: [row.included, row.blocked, row.warnings],
			request: model.applyRequest(),
		}, {
			both: [true, false],
			kept: [false, true, ['Its bars were designed without B4: include their new type too, or propose with Keep Shared Types.']],
			request: undefined,
		});
	});

	test('the edit built from an apply result changes only the files given that differ', () => {
		const current = { objectsText: '{"objects":[1]}\n', bimText: '{"elements":[]}\n', floorPlanText: '{"beams":[]}\n' };
		assert.deepStrictEqual([
			proposalEdits(current, { objectsText: '{"objects":[2]}\n', bimText: current.bimText }),
			proposalEdits(current, { objectsText: '{"objects":[2]}\n', bimText: '{"elements":[1]}\n', floorPlanText: '{"beams":[1]}\n' }),
			proposalEdits(current, { objectsText: current.objectsText, bimText: null }),
			proposalEdits({ objectsText: current.objectsText, bimText: undefined }, { objectsText: current.objectsText, bimText: '{}' }),
		], [
			{ objects: '{"objects":[2]}\n' },
			{ objects: '{"objects":[2]}\n', bim: '{"elements":[1]}\n', floorPlan: '{"beams":[1]}\n' },
			{},
			{},
		]);
	});

	test('the checks before and after, and the changes as text', () => {
		const before = { summary: { checked: 15, passed: 13, failed: 2, skipped: 0, maxUtilisation: 1.4, governing: 'B3' } };
		const after = { summary: { checked: 15, passed: 15, failed: 0, skipped: 1, maxUtilisation: 0.96, governing: 'B3' } };
		assert.deepStrictEqual([
			describeBeforeAfter(before, after),
			describeBeforeAfter(undefined, before),
			describeChange('B1: 3 Ø16 top → 4 Ø20 top'),
			describeChange({ message: 'B4: type B1 → B1-2 (06 BIM)' }),
		], ['13 pass, 2 fail → 15 pass, 0 fail, 1 not checked', '13 pass, 2 fail', 'B1: 3 Ø16 top → 4 Ø20 top', 'B4: type B1 → B1-2 (06 BIM)']);
	});

	test('required steel: the governing zone of each quantity, next to the steel provided', () => {
		const row = (location: string, quantity: string, required: number, provided: number | null, ok: boolean | null, unit = 'mm²', combination: string | null = '1.2D + 1.6L'): IFemSteelRequirement => ({
			element: 'B1', kind: 'beam', type: 'B1', location, quantity, demand: 100, demandUnit: 'kN·m', required, min: null, provided, unit, combination, ok, tooSmall: false, notes: '',
		});
		const required: IFemDesignRequired = {
			elements: [
				row('start', 'top bars (hogging)', 1256.6, 603.2, false),
				row('middle', 'top bars (hogging)', 400, 603.2, true),
				row('middle', 'bottom bars (sagging)', 900, 1473, true),
				row('end', 'bottom bars (sagging)', 700, 1473, true),
				row('start', 'stirrups Av/s', 520, 785, true, 'mm²/m'),
				{ ...row('column', 'tie spacing (max)', 150, 200, false, 'mm', null), element: 'C1', kind: 'column' },
				{ ...row('column', 'longitudinal bars', 1800, null, null), element: 'C2', kind: 'column' },
				{ ...row('column', 'longitudinal bars', 1600, 2513, true), element: 'C3', kind: 'column', notes: 'Pu = 900.0 kN; ρ required = 0.0100' },
				{ ...row('column', 'longitudinal bars', 1800, 1608, false), element: 'C4', kind: 'column' },
			],
		};
		const b1 = requiredSteelOf(required, 'B1');
		assert.deepStrictEqual([
			b1.map(r => [r.location, r.quantity]),
			b1.map(describeSteel),
			requiredSteelOf(required, 'C1').map(describeSteel),
			requiredSteelOf(required, 'C2').map(describeSteel),
			requiredSteelOf(required, 'X9'),
			[...required.elements.slice(6).map(describeSteelRatio), describeSteelRatio(required.elements[0])],
			shortElements(required),
			designArguments(URI.file('/p/08 FEM/model.osmodel')),
		], [
			[['start', 'top bars (hogging)'], ['middle', 'bottom bars (sagging)'], ['start', 'stirrups Av/s']],
			['required 1,257 mm², provided 603 mm²', 'required 900 mm², provided 1,473 mm²', 'required 520 mm²/m, provided 785 mm²/m'],
			['at most 150 mm, provided 200 mm'],
			['required 1,800 mm², none provided'],
			[],
			// C3: gross area 1600 / 0.01 = 160,000 mm², provided 2513 / 160,000.
			[undefined, 'ρ required 0.0100, provided 0.0157', undefined, undefined],
			// One each, however many zones are short.
			['B1', 'C1', 'C4'],
			{ outDir: URI.file('/p/08 FEM/model.results').fsPath, projectPath: URI.file('/p/08 FEM/model.osmodel').fsPath },
		]);
	});

	test('required steel: a footing failing checks bars cannot fix is not a section too small', () => {
		// As the backend writes them: a layer row, then one row per failing service check
		// (no unit, required 0, tooSmall true, the failure in its notes).
		const footing = (quantity: string, required: number, unit: string, notes: string, tooSmall: boolean): IFemSteelRequirement => ({
			element: 'F1', kind: 'foundation', type: 'F1', location: quantity === 'other check' ? 'foundation' : 'bottom X', quantity, demand: unit ? 40 : null, demandUnit: unit ? 'kN·m/m' : '', required, min: null, provided: unit ? 754 : null, unit, combination: unit ? '1.2D + 1.6L' : null, ok: unit ? false : null, tooSmall, notes,
		});
		const required: IFemDesignRequired = {
			elements: [
				footing('bottom X bars', 900, 'mm²/m', '', false),
				footing('other check', 0, '', 'Bearing (service) fails: 180 kPa > 150 kPa', true),
				footing('other check', 0, '', 'Resultant within the base fails', true),
				{ element: 'C9', kind: 'column', type: 'C250', location: 'column', quantity: 'longitudinal bars', demand: 3000, demandUnit: 'kN', required: 0, min: null, provided: null, unit: 'mm²', combination: '1.4D', ok: null, tooSmall: true, notes: '' },
			],
			summary: { tooSmall: ['C9', 'F1'] },
		};
		const f1 = requiredSteelOf(required, 'F1');
		assert.deepStrictEqual([
			f1.map(r => [r.quantity, isOtherFailure(r), describeSteel(r)]),
			tooSmallElements(required),
			otherFailureElements(required),
			shortElements(required),
		], [
			[
				['bottom X bars', false, 'required 900 mm²/m, provided 754 mm²/m'],
				// Both failures kept, each with its text (not "required 0, none provided").
				['other check', true, 'Bearing (service) fails: 180 kPa > 150 kPa'],
				['other check', true, 'Resultant within the base fails'],
			],
			['C9'],
			['F1'],
			['F1'],
		]);
	});
});

/** A design report with these members (one failing check each when they fail) and joints. */
function report(elements: readonly { id: string; type: string; ok: boolean; check?: string }[], joints: readonly object[] = [], building: readonly object[] = []): IFemDesignReport {
	return {
		code: 'BNBC 2020', method: [], combinations: [], skipped: [], notes: [],
		elements: elements.map(e => ({
			id: e.id, kind: 'beam', type: e.type, members: [], utilisation: e.ok ? 0.5 : 1.2, ok: e.ok,
			checks: [
				{ name: 'Shear', demand: 1, capacity: 2, unit: 'kN', utilisation: 0.5, combination: null, ok: true, note: '', flag: false },
				...(e.ok ? [] : [{ name: e.check ?? 'Flexure', demand: 12, capacity: 10, unit: 'kN·m', utilisation: 1.2, combination: null, ok: false, note: '', flag: false }]),
			],
		})),
		summary: { checked: elements.length, passed: elements.filter(e => e.ok).length, failed: elements.filter(e => !e.ok).length, skipped: 0, maxUtilisation: null, governing: null },
		...{ joints, seismic: { checks: building } },
	};
}
