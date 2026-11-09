/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { addNode, chartBars, connect, disconnect, GRAPH_SCHEMA, IStudyDocument, isPlainNetworkUrl, officeBlocker, officeServerUrl, parseParam, parseValues, readGraph, readNodeTypes, removeNode, slugId, STUDY_SCHEMA, studyProblems, studyRows, variantCount, writeGraph } from '../../common/automationModel.js';

suite('SAEngine - automation (alpha 9 L12)', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const types = readNodeTypes({
		types: [
			{ id: 'value.number', title: 'Number', category: 'Values', inputs: [{ name: 'value', type: 'number' }], outputs: [{ name: 'value', type: 'number' }] },
			{ id: 'math.add', title: 'Add', category: 'Values', inputs: [{ name: 'a', type: 'number' }, { name: 'b', type: 'number' }], outputs: [{ name: 'result', type: 'number' }] },
			{ title: 'no id' },
		],
	});

	test('node types are read defensively', () => {
		assert.deepStrictEqual(types.map(t => t.id), ['value.number', 'math.add']);
		assert.deepStrictEqual(readNodeTypes(undefined), []);
	});

	test('a graph is read, edited and written', () => {
		const { graph, problems } = readGraph(JSON.stringify({
			schema: GRAPH_SCHEMA, name: 'g',
			nodes: [{ id: 'n1', type: 'value.number', x: 10, y: 20, params: { value: 3 } }, { id: 'n1', type: 'math.add' }, { id: 'n2', type: 'math.add' }],
			edges: [{ from: { node: 'n1', port: 'value' }, to: { node: 'n2', port: 'a' } }, { from: { node: 'n9', port: 'x' }, to: { node: 'n2', port: 'b' } }],
		}));
		assert.deepStrictEqual(problems, []);
		assert.deepStrictEqual(graph!.nodes.map(n => n.id), ['n1', 'n2']); // the duplicate id is dropped
		assert.strictEqual(graph!.edges.length, 1); // the wire from a missing node is dropped
		const added = addNode(graph!, types[1], 100, 50);
		assert.strictEqual(added.id, 'n3');
		// A wire back from n2 to n1 would make a loop.
		assert.strictEqual(connect(added.graph, { node: 'n2', port: 'result' }, { node: 'n1', port: 'value' }), undefined);
		assert.strictEqual(connect(added.graph, { node: 'n3', port: 'result' }, { node: 'n3', port: 'a' }), undefined);
		// An input takes one wire: the new one replaces the old.
		const rewired = connect(added.graph, { node: 'n3', port: 'result' }, { node: 'n2', port: 'a' })!;
		assert.deepStrictEqual(rewired.edges, [{ from: { node: 'n3', port: 'result' }, to: { node: 'n2', port: 'a' } }]);
		assert.strictEqual(disconnect(rewired, { node: 'n2', port: 'a' }).edges.length, 0);
		assert.strictEqual(removeNode(rewired, 'n3').edges.length, 0);
		assert.deepStrictEqual(readGraph(writeGraph(rewired)).graph, rewired);
		assert.deepStrictEqual(readGraph('{"schema": "other"}').graph, undefined);
	});

	test('parameters typed in the panel', () => {
		assert.deepStrictEqual([parseParam('3.5', 'number'), parseParam('', 'number'), parseParam('[1, 2]', 'json'), parseParam('abc', 'any'), parseParam('true', 'any')], [3.5, undefined, [1, 2], 'abc', true]);
	});

	test('study variants, problems and rows', () => {
		const study: IStudyDocument = {
			schema: STUDY_SCHEMA, id: slugId('Grid and Grade!'), name: 'Grid and Grade!', combine: 'all', steps: [],
			parameters: [{ kind: 'gridSpacing', values: parseValues('0.9, 1.0, 1.1', 'gridSpacing') }, { kind: 'concreteGrade', values: parseValues('C24.1, C30', 'concreteGrade') }],
		};
		assert.strictEqual(study.id, 'grid-and-grade');
		assert.deepStrictEqual(study.parameters[1].values, ['C24.1', 'C30']);
		assert.strictEqual(variantCount(study), 6);
		assert.strictEqual(variantCount({ ...study, combine: 'oneAtATime' }), 4);
		assert.deepStrictEqual(studyProblems(study), []);
		assert.deepStrictEqual(studyProblems({ ...study, parameters: [{ kind: 'storeyHeight', values: Array.from({ length: 33 }, (_, k) => 3000 + k) }] }), ['tooMany']);
		const rows = studyRows({ rows: [
			{ id: 'V01', label: 'a', ok: true, design: { maxUtilisation: 0.8, failed: 0 }, drift: 0.004, boq: { cost: 1000, steelKg: 50 } },
			{ id: 'V02', label: 'b', ok: true, design: { maxUtilisation: 1.1, failed: 2 }, boq: { cost: 800, steelKg: 40 } },
			{ id: 'V03', label: 'c', ok: false, error: 'x' },
		] });
		assert.deepStrictEqual(rows.map(r => [r.id, r.cost, r.drift]), [['V01', 1000, 0.004], ['V02', 800, undefined], ['V03', undefined, undefined]]);
		assert.deepStrictEqual(chartBars(rows, 'cost').map(b => [b.fraction, b.best]), [[1, false], [0.8, true], [0, false]]);
	});

	test('the office server is opt-in and its address checked', () => {
		assert.strictEqual(officeBlocker(false, 'https://srv:8737', true), 'disabled');
		assert.strictEqual(officeBlocker(true, 'ftp://srv', true), 'noUrl');
		assert.strictEqual(officeBlocker(true, 'https://srv:8737/', false), 'noToken');
		assert.strictEqual(officeBlocker(true, 'https://srv:8737/', true), undefined);
		assert.strictEqual(officeServerUrl(' https://srv.office.local:8737/ '), 'https://srv.office.local:8737');
		assert.strictEqual(officeServerUrl('javascript:alert(1)'), undefined);
		assert.deepStrictEqual(['http://srv:8737', 'http://127.0.0.1:8737', 'https://srv'].map(isPlainNetworkUrl), [true, false, false]);
	});
});
