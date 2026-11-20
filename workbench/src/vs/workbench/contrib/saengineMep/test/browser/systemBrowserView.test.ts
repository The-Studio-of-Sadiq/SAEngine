/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { DisposableStore } from '../../../../../base/common/lifecycle.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { ISystemBrowserState, readSystemsReport, renderSystemBrowser } from '../../browser/systemBrowserView.js';

suite('SAEngine MEP System Browser', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads systems report, filters by classification and selects elements on click', () => {
		const report = readSystemsReport({
			systems: [
				{
					id: 'SYS1',
					name: 'AHU1 (Supply air)',
					classification: 'supplyAir',
					classificationLabel: 'Supply air',
					domain: 'duct',
					sources: ['AHU1'],
					elements: ['AHU1', 'D_TRUNK', 'AT1'],
					elementCount: 3,
					airFlowLps: 450,
					criticalPathLength: 15,
					warnings: 0,
				},
				{
					id: 'SYS2',
					name: 'T1 (Domestic cold water)',
					classification: 'domesticColdWater',
					classificationLabel: 'Domestic cold water',
					domain: 'pipe',
					sources: ['T1'],
					elements: ['T1', 'P50'],
					elementCount: 2,
					waterFlowLps: 2,
					criticalPathLength: 3,
					warnings: 1,
				},
			],
			issues: [
				{
					id: 'SI1',
					kind: 'sizeMismatch',
					severity: 'warning',
					message: 'P50 to P40: size mismatch (50 mm vs 40 mm)',
					elements: ['P50', 'P40'],
					story: 'L1',
					point: [3000, 0, 2700],
					system: 'SYS2',
					classification: 'domesticColdWater',
				},
			],
			elements: {
				AHU1: { id: 'AHU1', kind: 'ahu', discipline: 'hvac', story: 'L1', domain: 'duct', classification: 'supplyAir', isSource: true, isTerminal: false },
				D_TRUNK: { id: 'D_TRUNK', kind: 'duct', discipline: 'hvac', story: 'L1', domain: 'duct', classification: 'supplyAir', isSource: false, isTerminal: false },
				AT1: { id: 'AT1', kind: 'supplyDiffuser', discipline: 'hvac', story: 'L1', domain: 'duct', classification: 'supplyAir', isSource: false, isTerminal: true, flow: 450 },
				T1: { id: 'T1', kind: 'tank:overhead', discipline: 'plumbing', story: 'L1', domain: 'pipe', classification: 'domesticColdWater', isSource: true, isTerminal: false },
				P50: { id: 'P50', kind: 'pipe', discipline: 'plumbing', story: 'L1', domain: 'pipe', classification: 'domesticColdWater', isSource: false, isTerminal: false, flow: 2 },
			},
			unassigned: [],
			summary: { systems: 2, elements: 5, connectors: 6, connections: 3, issues: 1 },
		});
		assert.ok(report);
		assert.strictEqual(report.systems.length, 2);

		const container = mainWindow.document.createElement('div');
		const disposables = new DisposableStore();
		const selected: string[] = [];
		const state: ISystemBrowserState = { report, state: 'ok', filter: 'supplyAir' };
		renderSystemBrowser(container, state, {
			recompute: () => { },
			exportBcf: () => { },
			selectElement: id => selected.push(id),
			rerender: () => { },
		}, disposables);

		assert.strictEqual(container.querySelectorAll('.sys-node').length, 1);
		assert.strictEqual(container.querySelectorAll('.sys-issue').length, 0);
		const buttons = container.querySelectorAll<HTMLButtonElement>('.sys-element-btn');
		assert.strictEqual(buttons.length, 3);
		buttons[2].click();
		assert.deepStrictEqual(selected, ['AT1']);
		disposables.dispose();
	});
});
