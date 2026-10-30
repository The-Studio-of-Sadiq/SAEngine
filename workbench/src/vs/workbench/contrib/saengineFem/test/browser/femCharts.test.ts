/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IFemResultEntry } from '../../../../../platform/saengine/common/femSolver.js';
import { niceTicks, renderChart, renderSheet, tickText } from '../../browser/femChart.js';
import { closedPmCurve, defaultChartResult, displayTable, exportCell, formatCell, isLateralResult, orderLike, supportReactions, describeMode, elasticDriftLimit, extremes, filterRows, IFemColumnDiagram, IFemMemberForces, IFemStoryResponse, IFemStoryResult, isEarthquakeResult, memberEnvelope, memberValues, modalTable, modesToReach, profilePeak, sortRows, spectrumAt, storeyProfile, storeyTable, workbookSheets } from '../../browser/femChartData.js';
import { defaultResult, deflectionMagnification, modeText, resultOptions, scaleText } from '../../browser/femResultsBar.js';
import { groupedOptions } from '../../browser/femModelEditor.js';
import { chartUnits, memberNames } from '../../browser/femResultsView.js';
import { cameraOf, freeTopColumns, gridLines, IFilterModel, modelLevels, viewChoices, visibleElements } from '../../browser/femViewFilter.js';

const row = (name: string, z: number, values: Partial<Record<string, number | null>>) => ({
	name, z, height: null, dispX: null, dispY: null, avgDispX: null, avgDispY: null, driftX: null, driftY: null,
	forceX: null, forceY: null, shearX: null, shearY: null, overturningX: null, overturningY: null, ...values,
});

const EX: IFemStoryResult = {
	key: 'case:7', label: 'EX: Earthquake in X', kind: 'static', baseReaction: [-30000, 0, 0, 0, 0, 0],
	storeys: [
		row('Base', 0, { dispX: 0, overturningX: 160000 }),
		row('Level 1', 3, { dispX: 0.003, driftX: 0.001, forceX: 10000, shearX: 30000, overturningX: 60000 }),
		row('Level 2', 6, { dispX: 0.0075, driftX: 0.0015, forceX: 20000, shearX: 20000, overturningX: 0 }),
	],
};

suite('SAEngine - FEM charts', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('storey profiles: values at the levels, shears and drifts over their storeys', () => {
		assert.deepStrictEqual(storeyProfile(EX, 'disp', 'X').map(p => [p.value, p.z]), [[0, 0], [0.003, 3], [0.0075, 6]]);
		assert.deepStrictEqual(storeyProfile(EX, 'shear', 'X').map(p => [p.value, p.z]), [[30000, 0], [30000, 3], [20000, 3], [20000, 6]]);
		assert.deepStrictEqual(storeyProfile(EX, 'drift', 'X').map(p => p.level), ['Level 1', 'Level 1', 'Level 2', 'Level 2']);
		assert.deepStrictEqual(storeyProfile(EX, 'force', 'Y'), []);
		assert.strictEqual(profilePeak(storeyProfile(EX, 'overturning', 'X'))?.value, 160000);
	});

	test('the drift limit is the allowable design drift over Cd/I, for earthquake results', () => {
		assert.strictEqual(elasticDriftLimit({ ratio: 0.02, cd: 5, importance: 1.25, clause: '' }), 0.005);
		assert.strictEqual(elasticDriftLimit({ ratio: 0.02, cd: null, importance: null, clause: '' }), 0.02);
		assert.strictEqual(elasticDriftLimit(null), undefined);
		assert.deepStrictEqual(['EX: Earthquake in X', '0.9D + 1.0EY', 'RX: Response spectrum X', '1.2D + 1.6L', 'WX: Wind in X', 'EQ-free'].map(isEarthquakeResult), [true, true, true, false, false, false]);
	});

	test('modal: the mode reaching 90 %, captions, the spectrum at a period', () => {
		const modes = [
			{ number: 1, period: 0.5, frequency: 2, uX: 0.7, uY: 0.01, sumUX: 0.7, sumUY: 0.01 },
			{ number: 2, period: 0.4, frequency: 2.5, uX: 0.01, uY: 0.8, sumUX: 0.71, sumUY: 0.81 },
			{ number: 3, period: 0.2, frequency: 5, uX: 0.2, uY: 0.1, sumUX: 0.91, sumUY: 0.91 },
		];
		assert.strictEqual(modesToReach(modes, 'X', 0.9), 3);
		assert.strictEqual(modesToReach(modes.slice(0, 2), 'Y', 0.9), undefined);
		assert.strictEqual(describeMode(modes[1], 2), 'Mode 2: T = 0.400 s, UX 1.0 %, UY 80.0 %');
		assert.strictEqual(modeText({ number: 2, period: 0.121, ux: 0.033, uy: 0 }), 'Mode 2: T = 0.121 s, UX 3.3 %, UY 0.0 %');
		assert.strictEqual(modeText({ number: 1, period: 0.5 }), 'Mode 1: T = 0.500 s');
		const spectrum = { name: 'BNBC', periods: [0, 0.1, 1], accelerations: [1, 2, 0.2], damping: 0.05 };
		assert.deepStrictEqual([spectrumAt(spectrum, 0.05), spectrumAt(spectrum, 0.55), spectrumAt(spectrum, 3)].map(v => Number(v.toFixed(9))), [1.5, 1.1, 0.2]);
		const table = modalTable({ case: 'Modal', modes, required: 0.9 });
		assert.deepStrictEqual(table.rows[0], [1, 0.5, 2, 70, 1, 70, 1]);
	});

	test('members: values, envelope and extremes along the member', () => {
		const detail: IFemMemberForces = {
			member: 'B1', kind: 'beam', length: 2, elements: ['B1'], stations: [0, 1, 2], notes: [],
			results: [
				{ key: 'case:1', label: 'D', kind: 'static', forces: [[0, 1, 0, 0, 5, 0], [0, 0, 0, 0, -3, 0], [0, -1, 0, 0, 5, 0]], deflection: [[0, 0, 0], [0, 0, -0.002], [0, 0, 0]] },
				{ key: 'combination:1', label: '1.4D', kind: 'combination', forces: [[0, 1.4, 0, 0, 7, 0], [0, 0, 0, 0, -4.2, 0], [0, -1.4, 0, 0, 7, 0]], deflection: [[0, 0, 0], [0, 0, -0.0028], [0, 0, 0]] },
				{ key: 'combination:2', label: '0.9D', kind: 'combination', forces: [[0, 0.9, 0, 0, 4.5, 0], [0, 0, 0, 0, -2.7, 0], [0, -0.9, 0, 0, 4.5, 0]], deflection: [[0, 0, 0], [0, 0, -0.0018], [0, 0, 0]] },
			],
		};
		assert.deepStrictEqual(memberValues(detail.results[0], 'My'), [5, -3, 5]);
		assert.deepStrictEqual(memberValues(detail.results[0], 'u3'), [0, -0.002, 0]);
		const envelope = memberEnvelope(detail, 'My');
		assert.deepStrictEqual([envelope.max, envelope.min, envelope.minBy[1]], [[7, -2.7, 7], [4.5, -4.2, 4.5], '1.4D']);
		assert.deepStrictEqual(extremes(detail.stations, [5, -3, 5]), { max: { value: 5, at: 0 }, min: { value: -3, at: 1 } });
	});

	test('a P-M curve is closed to the axis at both ends', () => {
		const diagram: IFemColumnDiagram = {
			type: 'C400', assumedBars: false, phiPnMax: 3000, phiTension: 1000, contour: null, governing: null, points: [],
			curves: { x: [[-1000, 0], [500, 300], [3000, 150]], y: [] },
		};
		assert.deepStrictEqual(closedPmCurve(diagram, 'x'), [[0, -1000], [0, -1000], [300, 500], [150, 3000], [0, 3000]]);
		assert.deepStrictEqual(closedPmCurve(diagram, 'y'), []);
	});

	test('tables: storeys in kN and mm, sorting, filtering, workbook sheets', () => {
		const response: IFemStoryResponse = {
			levels: [], results: [EX], modal: null, spectrum: null, driftLimit: null, pushover: [], histories: [], notes: [],
		};
		const table = storeyTable(response, { length: v => v * 1000, force: v => v / 1000, moment: v => v / 1000 });
		assert.deepStrictEqual(table.rows[0].slice(0, 9), ['EX: Earthquake in X', 'Level 2', 6, 7.5, '', 0.0015, '', 20, '']);
		assert.strictEqual(table.rows.length, 3);

		const rows = [['C10', 3], ['C2', -1], ['B1', ''], ['C1', 10]];
		assert.deepStrictEqual(sortRows(rows, 0, false).map(r => r[0]), ['B1', 'C1', 'C2', 'C10']);
		assert.deepStrictEqual(sortRows(rows, 1, true).map(r => r[0]), ['C1', 'C10', 'C2', 'B1']);
		assert.deepStrictEqual(filterRows([['C3', '1.4D'], ['C3', '0.9D + EX'], ['B1', '1.4D']], 'c3 1.4').map(r => r[1]), ['1.4D']);
		assert.strictEqual(filterRows(rows, '  ').length, 4);

		const sheets = workbookSheets([
			{ caseName: 'D', tables: [{ name: 'Displacements', title: 'Node displacements', columns: ['Node', 'ux'], rows: [[1, 0.1]], notes: ['m'] }] },
			{ caseName: '1.4D', tables: [{ name: 'Displacements', title: 'Node displacements', columns: ['Node', 'ux'], rows: [[1, 0.14]], notes: ['m'] }] },
		], [table]);
		assert.deepStrictEqual(sheets.map(s => s.name), ['Storey response', 'Displacements']);
		assert.deepStrictEqual(sheets[1].rows, [['D', 1, 0.1], ['1.4D', 1, 0.14]]);
		assert.deepStrictEqual(sheets[1].columns, ['Result', 'Node', 'ux']);
	});

	test('result tables in kN, mm and kN·m, named axes, supports only with a total', () => {
		const si = 'SI (m, N, kg, s, Pa)';
		const node = displayTable({ name: 'Reactions', title: 'Final-step reactions', columns: ['Node', 'F1 [N]', 'F3 [N]', 'M2 [N·m]', 'R1 [rad]'], rows: [[1, 1500, -20000, 3000, 0.001]], notes: [] }, si);
		assert.deepStrictEqual(node.columns, ['Node', 'Fx [kN]', 'Fz [kN]', 'My [kN·m]', 'Rx [rad]']);
		assert.deepStrictEqual(node.rows, [[1, 1.5, -20, 3, 0.001]]);
		const disp = displayTable({ name: 'Displacements', title: 'Displacements (m, rad)', columns: ['Node', 'Ux', 'Rz'], rows: [[2, 0.0021, 0.01]], notes: [] }, si);
		assert.deepStrictEqual([disp.title, disp.columns, disp.rows[0][1]], ['Displacements (mm, rad)', ['Node', 'Ux [mm]', 'Rz [rad]'], 2.1]);
		// Member forces in the member's axes: V2, M3, the unit per row converted.
		const long = displayTable({ name: 'Element forces', title: 'Final-step element forces', columns: ['Element', 'Type', 'Component', 'Unit', 'Value'], rows: [[7, 'Frame', 'Vy i', 'N', 2500], [7, 'Frame', 'Mz i', 'N·m', 4000]], notes: [] }, si);
		assert.deepStrictEqual(long.rows, [[7, 'Frame', 'V2 i', 'kN', 2.5], [7, 'Frame', 'M3 i', 'kN·m', 4]]);
		const envelope = displayTable({ name: 'Envelope', title: 'Element end forces, min and max (N, N·m)', columns: ['Element', 'End', 'Force', 'Min', 'Max'], rows: [['B1', 'i', 'Mz', -5000, 6000]], notes: [] }, si);
		assert.deepStrictEqual(envelope.rows, [['B1', 'i', 'M3', -5, 6]]);
		assert.strictEqual(displayTable(node, 'US (in, kip)'), node);

		const reactions = supportReactions({ name: 'Reactions', title: '', columns: ['Node', 'Fx [kN]', 'Fz [kN]'], rows: [[1, 1, 10], [2, -0.5, 20], [423, 7, 0], ['Total', 7.5, 30]], notes: [] }, new Set([1, 2]));
		assert.deepStrictEqual(reactions.rows, [[1, 1, 10], [2, -0.5, 20], ['Total', 0.5, 30]]);

		// Sheets of one name with different columns say what they hold.
		const sheets = workbookSheets([
			{ caseName: 'D', resultType: 'StaticResults', tables: [{ name: 'Element forces', title: '', columns: ['Element', 'Value'], rows: [[1, 0.1]], notes: [] }] },
			{ caseName: '1.4D', resultType: 'Combination', tables: [{ name: 'Element forces', title: '', columns: ['Element', 'End', 'N'], rows: [[1, 'i', 0.30000000000000004]], notes: [] }] },
		]);
		assert.deepStrictEqual(sheets.map(s => s.name), ['Element forces (cases)', 'Element forces (combinations)']);
		assert.deepStrictEqual(sheets[1].rows, [['1.4D', 1, 'i', 0.3]]);
	});

	test('the charts open at a lateral result, listed as the 3D view lists them', () => {
		const gravity: IFemStoryResult = { key: 'combination:1', label: '1.4D', kind: 'combination', baseReaction: null, storeys: [row('Base', 0, {}), row('Level 1', 3, { shearX: 0, dispX: 0.0001 })] };
		const rx: IFemStoryResult = { ...EX, key: 'case:9', label: 'RX: Response spectrum X', kind: 'spectrum' };
		assert.strictEqual(defaultChartResult([gravity, EX])?.key, EX.key);
		assert.strictEqual(defaultChartResult([gravity, EX, rx])?.key, rx.key);
		assert.strictEqual(defaultChartResult([gravity])?.key, gravity.key);
		assert.strictEqual(isLateralResult(gravity), false);
		assert.deepStrictEqual(orderLike([gravity, EX, rx], ['case:7', 'case:9']).map(r => r.key), ['case:7', 'case:9', 'combination:1']);
		// A storey's peak drift is marked at its top level, where it is reported.
		assert.strictEqual(profilePeak(storeyProfile(EX, 'drift', 'X'))?.z, 6);
	});

	test('a member chart spans its length exactly', () => {
		const parent = mainWindow.document.createElement('div');
		const figure = renderChart(parent, { title: 'M3', xLabel: 'x', yLabel: 'M', series: [{ name: 'M', color: 'blue', points: [[0, 1], [3.2, -1]] }], xDomain: [0, 3.2] });
		const ticks = [...figure.querySelectorAll('.fem-chart-tick')].map(t => t.textContent);
		assert.ok(ticks.includes('3.2') && !ticks.includes('4') && !ticks.includes('3.5'), ticks.join(' '));
	});

	test('the 3D view draws deflections at 6 % of the model size: the true magnification', () => {
		const model = { nodes: [{ id: 1, coords: [0, 0, 0] }, { id: 2, coords: [3, 0, 4] }], elements: [] };
		const view = { label: 'D', kind: 'static' as const, nodes: [], reactions: [], elements: [{ id: 1, name: 'C1', y: [], z: [], displacements: [[0, 0, 0], [0.003, 0, -0.004]] }] };
		assert.ok(Math.abs(deflectionMagnification(model, view, 1)! - 60) < 1e-9);
		assert.ok(Math.abs(deflectionMagnification(model, view, 2)! - 120) < 1e-9);
		assert.strictEqual(deflectionMagnification(undefined, view, 1), undefined);
	});

	test('a new run opens at the earthquake in X, else the first combination, else the first static case', () => {
		const entry = (key: string, kind: IFemResultEntry['kind'], label = key): IFemResultEntry => ({ key, label, kind });
		assert.strictEqual(defaultResult([entry('case:1', 'static', 'D: Dead'), entry('case:7', 'static', 'EX: Earthquake in X'), entry('combination:1', 'combination')])?.key, 'case:7');
		assert.strictEqual(defaultResult([entry('case:10', 'modal'), entry('case:1', 'static'), entry('combination:1', 'combination')])?.key, 'combination:1');
		assert.strictEqual(defaultResult([entry('case:10', 'modal'), entry('case:1', 'static')])?.key, 'case:1');
		assert.strictEqual(defaultResult([entry('case:10', 'modal')])?.key, 'case:10');
		assert.strictEqual(defaultResult([]), undefined);
	});

	test('the result pickers file the results under headings', () => {
		const entry = (key: string, kind: IFemResultEntry['kind']): IFemResultEntry => ({ key, label: key, kind });
		const picked = resultOptions([entry('case:1', 'static'), entry('case:2', 'static'), entry('combination:1', 'combination'), entry('case:3', 'modal')]);
		assert.deepStrictEqual(picked.rows, [-1, 0, 1, -1, 2, -1, 3]);
		assert.deepStrictEqual(picked.options.map(o => !!o.isDisabled), [true, false, false, true, false, true, false]);
		const tables = groupedOptions([
			{ key: 'case:1', label: 'D', group: 'case', warnings: [], tables: [] },
			{ key: 'combination:1', label: '1.4D + 1.4SD', group: 'combination', warnings: [], tables: [] },
			{ key: 'combination:2', label: '1.2D', group: 'combination', warnings: [], tables: [] },
		]);
		assert.deepStrictEqual(tables.rows, [-1, 0, -1, 1, 2]);
	});

	test('the members to pick: frame members by name, naturally sorted', () => {
		assert.deepStrictEqual(memberNames([
			{ name: 'C10', nodes: [1, 2] }, { name: 'C3#2', nodes: [2, 3] }, { name: 'C3', nodes: [3, 4] }, { name: 'B1', nodes: [4, 5] },
			{ name: 'S1', nodes: [1, 2, 3, 4] }, { name: 'C3/embed#2', nodes: [5, 6] }, { nodes: [6, 7] },
		]), ['B1', 'C3', 'C10']);
	});

	test('chart units, scale text, ticks', () => {
		assert.deepStrictEqual(chartUnits('SI (m, N, kg, s, Pa)').force, { scale: 1e-3, unit: 'kN' });
		assert.deepStrictEqual(chartUnits(undefined).length, { scale: 1, unit: '' });
		assert.deepStrictEqual([scaleText(1), scaleText(Math.pow(2, 0.5)), scaleText(0.125), scaleText(32)], ['×1', '×1.4', '×0.13', '×32']);
		assert.deepStrictEqual(niceTicks(0, 0.0072), [0, 0.002, 0.004, 0.006, 0.008]);
		assert.deepStrictEqual(niceTicks(-45, 130), [-50, 0, 50, 100, 150]);
		assert.deepStrictEqual(niceTicks(0, 0.868), [0, 0.2, 0.4, 0.6, 0.8, 1]); // up to the largest value, not below it
		assert.deepStrictEqual([tickText(0), tickText(1234.5678), tickText(0.00012), tickText(250000)], ['0', '1235', '1.2e-4', '2.5e+5']);
	});

	test('a chart is drawn as SVG with its legend and caption', () => {
		const parent = mainWindow.document.createElement('div');
		const figure = renderChart(parent, {
			title: 'Storey Shear', xLabel: 'Shear [kN]', yLabel: 'Elevation [m]',
			series: [{ name: 'X', color: 'blue', points: [[30, 0], [30, 3], [20, 3], [20, 6]] }, { name: 'Y', color: 'orange', style: 'points', points: [[1, 1]] }],
			guides: [{ axis: 'x', value: 25, label: 'limit' }],
			caption: 'X: largest 30 kN at Level 1',
		});
		const svg = figure.querySelector('svg')!;
		assert.strictEqual(svg.getAttribute('role'), 'img');
		assert.ok(svg.getAttribute('aria-label')!.includes('largest 30 kN'));
		assert.strictEqual(figure.querySelectorAll('.fem-chart-series').length, 2);
		assert.strictEqual(figure.querySelectorAll('.fem-chart-guide').length, 1);
		assert.deepStrictEqual([...figure.querySelectorAll('.fem-chart-legend-item')].map(e => e.textContent), ['X', 'Y', 'limit']);
		assert.strictEqual(figure.querySelector('figcaption')?.textContent, 'X: largest 30 kN at Level 1');
		// Every marker says its values.
		assert.ok([...figure.querySelectorAll('circle title')].every(t => (t.textContent ?? '').length > 0));
	});

	test('tables: four significant digits on screen, six in the exports, no exponents or -0', () => {
		assert.deepStrictEqual(
			[formatCell(0.000123456), formatCell(12345.678), formatCell(3), formatCell(1.5), formatCell('C3#2'), exportCell(0.000123456789), exportCell('C3')],
			['0.0001235', '12350', '3', '1.5', 'C3#2', '0.000123457', 'C3'],
		);
		assert.deepStrictEqual([formatCell(-3.2e-11), formatCell(1.2e-9), exportCell(0.30000000000000004), exportCell(-1e-12)], ['0', '0', '0.3', '0']);
		const parent = mainWindow.document.createElement('div');
		renderSheet(parent, { name: 'Modes', columns: ['Mode', 'T [s]'], rows: [[1, 0.876543], ['2', 0.5]], notes: ['Mass participation from the eigen solver.'] });
		assert.deepStrictEqual({
			head: [...parent.querySelectorAll('th')].map(th => th.textContent),
			cells: [...parent.querySelectorAll('td')].map(td => `${td.className}:${td.textContent}`),
			note: parent.querySelector('.fem-results-note')?.textContent,
		}, {
			head: ['Mode', 'T [s]'],
			cells: ['number:1', 'number:0.8765', ':2', 'number:0.5'],
			note: 'Mass participation from the eigen solver.',
		});
	});
});

suite('SAEngine - FEM view filters', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	// Two bays in X, one in Y, one storey 3 m high on a rigid diaphragm.
	const model: IFilterModel = {
		nodes: [
			{ id: 1, coords: [0, 0, 0], restraint: [true] }, { id: 2, coords: [5, 0, 0], restraint: [true] }, { id: 3, coords: [10, 0, 0], restraint: [true] },
			{ id: 4, coords: [0, 4, 0], restraint: [true] }, { id: 5, coords: [5, 4, 0], restraint: [true] }, { id: 6, coords: [10, 4, 0], restraint: [true] },
			{ id: 11, coords: [0, 0, 3] }, { id: 12, coords: [5, 0, 3] }, { id: 13, coords: [10, 0, 3] },
			{ id: 14, coords: [0, 4, 3] }, { id: 15, coords: [5, 4, 3] }, { id: 16, coords: [10, 4, 3] },
			{ id: 20, coords: [5, 2, 3] },
		],
		elements: [
			{ id: 1, name: 'C1', type: 'ElasticBeamColumn', nodes: [1, 11] }, { id: 2, name: 'C2', type: 'ElasticBeamColumn', nodes: [2, 12] },
			{ id: 3, name: 'C3', type: 'ElasticBeamColumn', nodes: [3, 13] }, { id: 4, name: 'C4', type: 'ElasticBeamColumn', nodes: [4, 14] },
			{ id: 5, name: 'C5', type: 'ElasticBeamColumn', nodes: [5, 15] }, { id: 6, name: 'C6', type: 'ElasticBeamColumn', nodes: [6, 16] },
			{ id: 7, name: 'B1', type: 'ElasticBeamColumn', nodes: [11, 12] }, { id: 8, name: 'B1#2', type: 'ElasticBeamColumn', nodes: [12, 13] },
			{ id: 9, name: 'B2', type: 'ElasticBeamColumn', nodes: [12, 15] },
			{ id: 10, name: 'S1', type: 'Shell', nodes: [11, 12, 15, 14] },
		],
		mp_constraints: [{ type: 'RigidDiaphragm', retained_node: 20 }],
	};

	test('levels from the diaphragms and the supports; grid lines shared by columns', () => {
		assert.deepStrictEqual(modelLevels(model), [0, 3]);
		// A roof of beams without a diaphragm is a level too; a column standing on it is free at the top.
		const roof: IFilterModel = {
			...model,
			nodes: [...model.nodes, { id: 31, coords: [0, 0, 6] }, { id: 32, coords: [5, 0, 6] }, { id: 33, coords: [10, 0, 6] }, { id: 34, coords: [10, 0, 7.5] }],
			elements: [...model.elements,
			{ id: 21, name: 'C11', type: 'ElasticBeamColumn', nodes: [11, 31] }, { id: 22, name: 'C12', type: 'ElasticBeamColumn', nodes: [12, 32] },
			{ id: 23, name: 'R1', type: 'ElasticBeamColumn', nodes: [31, 32] }, { id: 24, name: 'R1#2', type: 'ElasticBeamColumn', nodes: [32, 33] },
			{ id: 25, name: 'C20', type: 'ElasticBeamColumn', nodes: [13, 34] },
			],
		};
		assert.deepStrictEqual(modelLevels(roof), [0, 3, 6]);
		assert.deepStrictEqual(freeTopColumns(roof), ['C20']);
		assert.deepStrictEqual(freeTopColumns(model), []);
		assert.deepStrictEqual(gridLines(model), { x: [0, 5, 10], y: [0, 4] });
		const massOnly: IFilterModel = { ...model, mp_constraints: [], nodes: model.nodes.map(n => n.coords[2] === 3 ? { ...n, mass: [100, 100, 0] } : n) };
		assert.deepStrictEqual(modelLevels(massOnly), [0, 3]);
	});

	test('a plan, an elevation and a storey show their elements', () => {
		assert.strictEqual(visibleElements(model, { kind: 'all' }), undefined);
		assert.deepStrictEqual([...visibleElements(model, { kind: 'plan', z: 3, name: 'Roof' })!].sort((a, b) => a - b), [7, 8, 9, 10]);
		assert.deepStrictEqual([...visibleElements(model, { kind: 'elevation', axis: 'y', at: 0 })!].sort((a, b) => a - b), [1, 2, 3, 7, 8]);
		assert.deepStrictEqual([...visibleElements(model, { kind: 'elevation', axis: 'x', at: 5 })!].sort((a, b) => a - b), [2, 5, 9]);
		assert.strictEqual(visibleElements(model, { kind: 'storey', bottom: 0, top: 3, name: 'Roof' })!.size, 10);
		assert.deepStrictEqual([cameraOf({ kind: 'plan', z: 3, name: '' }), cameraOf({ kind: 'elevation', axis: 'x', at: 0 }), cameraOf({ kind: 'elevation', axis: 'y', at: 0 }), cameraOf({ kind: 'all' })], ['top', 'side', 'front', '3d']);
		assert.deepStrictEqual(viewChoices(model).map(v => v.choice.kind), ['all', 'plan', 'elevation', 'elevation', 'elevation', 'elevation', 'elevation', 'storey']);
	});
});
