/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

// Alpha 9 L4 and L6 (written in the week without test runs, owner 2026-11-05: not run yet).

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IFemDesignElement } from '../../browser/femDesign.js';
import { connectionFeItems, hasFeCheck } from '../../browser/femConnectionFe.js';
import { cableSheet, hasStability, pathSeries, stabilityHelp } from '../../browser/femNonlinearStability.js';

suite('FEM nonlinear stability and connection FE check', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('the path is drawn as λ against the control displacement in mm', () => {
		const found = { available: true, path: [[0, 0], [1, 0.002], [2.1, 0.01]], limitFactor: 2.1, limitReached: true, alphaCr: 2.5, ratio: 0.84, required: 1, ok: true, analysis: 'GMNIA', combination: 'U1', imperfection: { kind: 'eigenmode' as const, amplitude: 0.004, governs: 'bow of C1' } };
		assert.ok(hasStability(found));
		assert.deepStrictEqual(pathSeries(found)[0].points, [[0, 0], [2, 1], [10, 2.1]]);
		const help = stabilityHelp(found);
		assert.ok(help.includes('λu = 2.100'));
		assert.ok(help.includes('αcr = 2.500'));
		assert.ok(help.includes('4.0 mm'));
	});

	test('a still rising path is a lower bound; cables are tabled in kN and mm', () => {
		const found = {
			available: true, limitFactor: 1.4, limitReached: false, ok: true, required: 1,
			cables: [{ cable: 'G1', pretension: 20000, maxTension: 35000, minTension: 21000, sag: 0.125, slack: 0, segments: 8, resistance: 100000, utilisation: 0.35 }],
		};
		assert.ok(stabilityHelp(found).includes('lower bound'));
		const sheet = cableSheet(found);
		assert.deepStrictEqual(sheet.rows[0], ['G1', 20, 35, 21, 125, '0 / 8', 100, 0.35]);
		assert.strictEqual(hasStability({ available: false, reason: 'not run yet' }), false);
	});

	test('the FE check is offered for end plates and fin plates only', () => {
		const element = (kind: string) => ({ id: 'B1', kind: 'beam', type: 'SB', members: [1], checks: [], steel: { section: 'IPE 300', connections: [{ name: 'x', kind, checks: [] }] } }) as unknown as IFemDesignElement;
		assert.strictEqual(hasFeCheck(element('endPlate')), true);
		assert.strictEqual(hasFeCheck(element('finPlate')), true);
		assert.strictEqual(hasFeCheck(element('gusset')), false);
	});

	test('the FE check lists the strain, the stiffness class and the checks, worst first', () => {
		const items = connectionFeItems({
			plasticStrain: 0.012, plasticStrainLimit: 0.05, loadShare: 1, stiffness: 5200, code: 'EN',
			forces: { V: 150, N: 0, M: 0, combination: 'U1' },
			classification: { class: 'pinned', ratio: 0.3 },
			checks: [
				{ name: 'bolt shear', demand: 25, capacity: 90, unit: 'kN', utilisation: 0.28, combination: 'U1', ok: true, note: '', flag: false },
				{ name: 'weld force per length', demand: 900, capacity: 1300, unit: 'N/mm', utilisation: 0.69, combination: 'U1', ok: true, note: '', flag: false },
			],
		});
		const text = items.map(i => i.kind === 'row' ? `${i.name}: ${i.value}` : i.kind === 'check' ? i.name : i.text);
		assert.ok(text.includes('Plastic strain: 1.20 % (limit 5.0 %)'));
		assert.ok(text.some(t => t.includes('pinned')));
		assert.ok(text.indexOf('weld force per length') < text.indexOf('bolt shear'));
		assert.ok(connectionFeItems({ error: 'no forces' }).some(i => i.kind === 'note' && i.text.includes('no forces')));
	});
});
