import assert from 'node:assert/strict';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { mkdtemp } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-constraints-test-')), 'constraints.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/constraintModel.ts';
				export * from './src/constraintSolver.ts';
				export { solveAndUpdateDatabase } from './src/constraintCommands.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' }, plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('expression parser: \'2*(d1+3)/4\' with d1=5 -> 4', async () => {
	const { evaluateExpression, evaluateAllParameters } = await load();
	const res = evaluateExpression('2*(d1+3)/4', { d1: 5 });
	assert.equal(res, 4);

	// Parameter dependencies
	const params = {
		d1: { name: 'd1', expression: '100', value: 0 },
		d2: { name: 'd2', expression: 'd1/2', value: 0 },
	};
	const resolved = evaluateAllParameters(params);
	assert.equal(resolved.d1, 100);
	assert.equal(resolved.d2, 50);
});

test('a line (0,0)-(10,1) with Horizontal -> endpoint y equal (the end that moves least / start kept fixed if Fixed)', async () => {
	const { solveGeometricConstraints } = await load();

	// 1. Without fixed start: least movement moves both endpoints equally (y -> 0.5)
	const line1 = {
		kind: 'line',
		id: 'L1',
		start: [0, 0],
		end: [10, 1],
	};
	const res1 = solveGeometricConstraints(
		[line1],
		[{ id: 'c1', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L1', feature: 'whole' }] }],
	);
	assert.ok(res1.success);
	const solvedL1 = res1.entities[0];
	assert.ok(Math.abs(solvedL1.start[1] - solvedL1.end[1]) < 1e-6, 'Endpoints y must be equal');
	assert.ok(Math.abs(solvedL1.start[1] - 0.5) < 1e-4, 'Least movement moves start y from 0 to 0.5');
	assert.ok(Math.abs(solvedL1.end[1] - 0.5) < 1e-4, 'Least movement moves end y from 1 to 0.5');

	// 2. With fixed start: start kept at (0, 0), end moves to y = 0
	const line2 = {
		kind: 'line',
		id: 'L2',
		start: [0, 0],
		end: [10, 1],
		fixedStart: true,
	};
	const res2 = solveGeometricConstraints(
		[line2],
		[{ id: 'c2', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L2', feature: 'whole' }] }],
	);
	assert.ok(res2.success);
	const solvedL2 = res2.entities[0];
	assert.deepEqual(solvedL2.start, [0, 0], 'Start kept fixed at (0,0)');
	assert.equal(solvedL2.end[0], 10, 'End x unchanged');
	assert.ok(Math.abs(solvedL2.end[1]) < 1e-6, 'End y moved to 0');
});

test('two lines with Perpendicular + Coincident at a corner -> dot product 0', async () => {
	const { solveGeometricConstraints } = await load();

	// Line 1 along X axis (fixed), Line 2 at 45 degrees
	const l1 = {
		kind: 'line',
		id: 'L1',
		start: [0, 0],
		end: [10, 0],
		fixed: true,
	};
	const l2 = {
		kind: 'line',
		id: 'L2',
		start: [0, 0],
		end: [10, 10],
	};

	const res = solveGeometricConstraints(
		[l1, l2],
		[
			{ id: 'c1', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L1', feature: 'start' }, { entityId: 'L2', feature: 'start' }] },
			{ id: 'c2', type: 'geometric', kind: 'perpendicular', refs: [{ entityId: 'L1', feature: 'whole' }, { entityId: 'L2', feature: 'whole' }] },
		],
	);
	assert.ok(res.success);
	const s1 = res.entities[0];
	const s2 = res.entities[1];
	const dx1 = s1.end[0] - s1.start[0], dy1 = s1.end[1] - s1.start[1];
	const dx2 = s2.end[0] - s2.start[0], dy2 = s2.end[1] - s2.start[1];
	const dot = dx1 * dx2 + dy1 * dy2;
	assert.ok(Math.abs(dot) < 1e-6, `Dot product must be 0 (got ${dot})`);
});

test('rectangle of 4 lines with coincident corners, two horizontal, two vertical, d1 = 100 width and d2 = d1/2 height -> corners (0,0),(100,0),(100,50),(0,50) when the first corner is Fixed', async () => {
	const { solveGeometricConstraints, evaluateAllParameters } = await load();

	const params = {
		d1: { name: 'd1', expression: '100', value: 100 },
		d2: { name: 'd2', expression: 'd1/2', value: 50 },
	};
	const paramVals = evaluateAllParameters(params);

	// 4 lines forming initial rough rectangle:
	// L1: bottom (0,0)-(10,0)
	// L2: right (10,0)-(10,5)
	// L3: top (10,5)-(0,5)
	// L4: left (0,5)-(0,0)
	const lines = [
		{ kind: 'line', id: 'L1', start: [0, 0], end: [10, 0], fixedStart: true },
		{ kind: 'line', id: 'L2', start: [10, 0], end: [10, 5] },
		{ kind: 'line', id: 'L3', start: [10, 5], end: [0, 5] },
		{ kind: 'line', id: 'L4', start: [0, 5], end: [0, 0] },
	];

	const constraints = [
		// Corners coincident
		{ id: 'c1', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L1', feature: 'end' }, { entityId: 'L2', feature: 'start' }] },
		{ id: 'c2', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L2', feature: 'end' }, { entityId: 'L3', feature: 'start' }] },
		{ id: 'c3', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L3', feature: 'end' }, { entityId: 'L4', feature: 'start' }] },
		{ id: 'c4', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L4', feature: 'end' }, { entityId: 'L1', feature: 'start' }] },
		// Orientations
		{ id: 'h1', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L1', feature: 'whole' }] },
		{ id: 'h2', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L3', feature: 'whole' }] },
		{ id: 'v1', type: 'geometric', kind: 'vertical', refs: [{ entityId: 'L2', feature: 'whole' }] },
		{ id: 'v2', type: 'geometric', kind: 'vertical', refs: [{ entityId: 'L4', feature: 'whole' }] },
		// Dimensions
		{ id: 'dim1', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L1', feature: 'whole' }], name: 'd1', expression: '100', value: 100 },
		{ id: 'dim2', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L4', feature: 'whole' }], name: 'd2', expression: 'd1/2', value: 50 },
	];

	const res = solveGeometricConstraints(lines, constraints, paramVals);
	assert.ok(res.success, `Solver failed: ${res.error}`);

	const [l1, l2, l3, l4] = res.entities;
	// Verify corners: (0,0), (100,0), (100,50), (0,50)
	assert.ok(Math.abs(l1.start[0] - 0) < 1e-4 && Math.abs(l1.start[1] - 0) < 1e-4, 'Corner 1 at (0,0)');
	assert.ok(Math.abs(l1.end[0] - 100) < 1e-4 && Math.abs(l1.end[1] - 0) < 1e-4, 'Corner 2 at (100,0)');
	assert.ok(Math.abs(l2.end[0] - 100) < 1e-4 && Math.abs(l2.end[1] - 50) < 1e-4, 'Corner 3 at (100,50)');
	assert.ok(Math.abs(l3.end[0] - 0) < 1e-4 && Math.abs(l3.end[1] - 50) < 1e-4, 'Corner 4 at (0,50)');
});

test('changing d1 to 200 -> height 100', async () => {
	const { solveGeometricConstraints, evaluateAllParameters } = await load();

	const params = {
		d1: { name: 'd1', expression: '200', value: 200 },
		d2: { name: 'd2', expression: 'd1/2', value: 100 },
	};
	const paramVals = evaluateAllParameters(params);

	// Start from previous rectangle solution
	const lines = [
		{ kind: 'line', id: 'L1', start: [0, 0], end: [100, 0], fixedStart: true },
		{ kind: 'line', id: 'L2', start: [100, 0], end: [100, 50] },
		{ kind: 'line', id: 'L3', start: [100, 50], end: [0, 50] },
		{ kind: 'line', id: 'L4', start: [0, 50], end: [0, 0] },
	];

	const constraints = [
		{ id: 'c1', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L1', feature: 'end' }, { entityId: 'L2', feature: 'start' }] },
		{ id: 'c2', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L2', feature: 'end' }, { entityId: 'L3', feature: 'start' }] },
		{ id: 'c3', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L3', feature: 'end' }, { entityId: 'L4', feature: 'start' }] },
		{ id: 'c4', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L4', feature: 'end' }, { entityId: 'L1', feature: 'start' }] },
		{ id: 'h1', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L1', feature: 'whole' }] },
		{ id: 'h2', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L3', feature: 'whole' }] },
		{ id: 'v1', type: 'geometric', kind: 'vertical', refs: [{ entityId: 'L2', feature: 'whole' }] },
		{ id: 'v2', type: 'geometric', kind: 'vertical', refs: [{ entityId: 'L4', feature: 'whole' }] },
		{ id: 'dim1', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L1', feature: 'whole' }], name: 'd1', expression: '200', value: 200 },
		{ id: 'dim2', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L4', feature: 'whole' }], name: 'd2', expression: 'd1/2', value: 100 },
	];

	const res = solveGeometricConstraints(lines, constraints, paramVals);
	assert.ok(res.success, `Solver failed: ${res.error}`);

	const [l1, l2, l3, l4] = res.entities;
	assert.ok(Math.abs(l1.end[0] - 200) < 1e-4, 'Width is 200');
	const height = Math.abs(l4.start[1] - l4.end[1]);
	assert.ok(Math.abs(height - 100) < 1e-4, `Height must be 100 (got ${height})`);
});

test('adding a second width constraint d3 = 120 to the solved rectangle -> over-constrained error', async () => {
	const { solveGeometricConstraints } = await load();

	// Rectangle already has d1 = 200 on L1 (bottom) and horizontal/vertical/coincident
	const lines = [
		{ kind: 'line', id: 'L1', start: [0, 0], end: [200, 0], fixedStart: true },
		{ kind: 'line', id: 'L2', start: [200, 0], end: [200, 100] },
		{ kind: 'line', id: 'L3', start: [200, 100], end: [0, 100] },
		{ kind: 'line', id: 'L4', start: [0, 100], end: [0, 0] },
	];

	const constraints = [
		{ id: 'c1', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L1', feature: 'end' }, { entityId: 'L2', feature: 'start' }] },
		{ id: 'c2', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L2', feature: 'end' }, { entityId: 'L3', feature: 'start' }] },
		{ id: 'c3', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L3', feature: 'end' }, { entityId: 'L4', feature: 'start' }] },
		{ id: 'c4', type: 'geometric', kind: 'coincident', refs: [{ entityId: 'L4', feature: 'end' }, { entityId: 'L1', feature: 'start' }] },
		{ id: 'h1', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L1', feature: 'whole' }] },
		{ id: 'h2', type: 'geometric', kind: 'horizontal', refs: [{ entityId: 'L3', feature: 'whole' }] },
		{ id: 'v1', type: 'geometric', kind: 'vertical', refs: [{ entityId: 'L2', feature: 'whole' }] },
		{ id: 'v2', type: 'geometric', kind: 'vertical', refs: [{ entityId: 'L4', feature: 'whole' }] },
		{ id: 'dim1', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L1', feature: 'whole' }], name: 'd1', expression: '200', value: 200 },
		{ id: 'dim2', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L4', feature: 'whole' }], name: 'd2', expression: '100', value: 100 },
		// Conflicting constraint: width d3 = 120 on top line L3
		{ id: 'dim3', type: 'dimensional', kind: 'aligned', refs: [{ entityId: 'L3', feature: 'whole' }], name: 'd3', expression: '120', value: 120 },
	];

	const res = solveGeometricConstraints(lines, constraints, { d1: 200, d2: 100, d3: 120 });
	assert.equal(res.success, false, 'Expected solver to fail due to over-constraint');
	assert.ok(res.error?.includes('would over-constrain the geometry'), `Expected over-constrained error message, got: ${res.error}`);
});

test('circle tangent to a line at distance -> |centre-to-line distance| = r', async () => {
	const { solveGeometricConstraints } = await load();

	// Line along X-axis (y = 0) fixed
	const line = {
		kind: 'line',
		id: 'L1',
		start: [0, 0],
		end: [10, 0],
		fixed: true,
	};
	// Circle with center at (5, 10), radius 4 (fixed radius)
	const circle = {
		kind: 'circle',
		id: 'C1',
		center: [5, 10],
		radius: 4,
		fixedRadius: true,
	};

	const res = solveGeometricConstraints(
		[line, circle],
		[{ id: 't1', type: 'geometric', kind: 'tangent', refs: [{ entityId: 'L1', feature: 'whole' }, { entityId: 'C1', feature: 'whole' }] }],
	);
	assert.ok(res.success, `Solver failed: ${res.error}`);

	const solvedCircle = res.entities[1];
	// Center-to-line distance: line is y=0, so distance is |center.y|
	const dist = Math.abs(solvedCircle.center[1]);
	assert.ok(Math.abs(dist - solvedCircle.radius) < 1e-4, `|centre-to-line distance| must equal r (${dist} vs ${solvedCircle.radius})`);
});

test('DXF round trip keeps constraints and parameters', async () => {
	const {
		AcDbDatabase, AcDbLine, AcGePoint3d, acdbHostApplicationServices,
		saveConstraintsToDatabase, loadConstraintsFromDatabase,
	} = await load();

	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	db.tables.blockTable.modelSpace.appendEntity(line);

	const initialStore = {
		version: 1,
		type: 'SAENGINE_CONSTRAINTS',
		constraints: [
			{ id: 'c1', type: 'geometric', kind: 'horizontal', refs: [{ entityId: String(line.objectId), feature: 'whole' }] },
			{ id: 'd1', type: 'dimensional', kind: 'aligned', refs: [{ entityId: String(line.objectId), feature: 'whole' }], name: 'd1', expression: '100', value: 100 },
		],
		parameters: {
			d1: { name: 'd1', expression: '100', value: 100 },
			d2: { name: 'd2', expression: 'd1/2', value: 50, isUser: true },
		},
	};

	saveConstraintsToDatabase(db, initialStore);

	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	assert.ok(dxf.includes('SAENGINE_CONSTRAINTS'), 'DXF output must contain SAENGINE_CONSTRAINTS');

	const db2 = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db2;
	await db2.read(new TextEncoder().encode(dxf).buffer);

	const loadedStore = loadConstraintsFromDatabase(db2);
	assert.equal(loadedStore.type, 'SAENGINE_CONSTRAINTS');
	assert.equal(loadedStore.constraints.length, 2);
	assert.equal(loadedStore.constraints[0].kind, 'horizontal');
	assert.equal(loadedStore.constraints[1].kind, 'aligned');
	assert.equal(loadedStore.parameters.d1.value, 100);
	assert.equal(loadedStore.parameters.d2.expression, 'd1/2');
	assert.equal(loadedStore.parameters.d2.isUser, true);
});

test('solving in the drawing keeps entity ids, so a second solve still applies', async () => {
	const { AcDbDatabase, AcDbLine, AcGePoint3d, acdbHostApplicationServices, solveAndUpdateDatabase, loadConstraintsFromDatabase } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;
	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 1, 0));
	db.tables.blockTable.modelSpace.appendEntity(line);
	const id = String(line.objectId);
	const store = {
		version: 1, type: 'SAENGINE_CONSTRAINTS',
		constraints: [
			{ id: 'c0', type: 'geometric', kind: 'fix', refs: [{ entityId: id, feature: 'start' }] },
			{ id: 'c1', type: 'geometric', kind: 'horizontal', refs: [{ entityId: id, feature: 'whole' }] },
			{ id: 'd1', type: 'dimensional', kind: 'aligned', refs: [{ entityId: id, feature: 'whole' }], name: 'd1', expression: 'd1', value: 20 },
		],
		parameters: { d1: { name: 'd1', expression: '20', value: 20 } },
	};
	const ctx = {
		database: {
			native: db,
			replace: () => { throw new Error('the solver must edit in place'); },
			get: i => db.tables.blockTable.modelSpace.getIdAt(i), add: () => { }, erase: () => { }, all: () => db.tables.blockTable.modelSpace.newIterator().toArray(),
		},
		transaction: async fn => fn(),
		message: () => { },
	};
	await solveAndUpdateDatabase(ctx, store);
	const first = db.tables.blockTable.modelSpace.getIdAt(id);
	const r = p => Math.round(p * 1000) / 1000;
	assert.deepEqual([r(first.endPoint.x), r(first.endPoint.y)], [20, 0]);
	const stored = loadConstraintsFromDatabase(db);
	stored.parameters.d1 = { name: 'd1', expression: '30', value: 30 };
	await solveAndUpdateDatabase(ctx, stored);
	const second = db.tables.blockTable.modelSpace.getIdAt(id);
	assert.equal(String(second.objectId), id);
	assert.deepEqual([r(second.endPoint.x), r(second.endPoint.y)], [30, 0]);
});
