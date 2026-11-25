import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function loadGeom() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-polyedit-geom-')), 'geom.mjs');
	await esbuild.build({
		stdin: {
			contents: await readFile('src/polyEditGeometry.ts', 'utf8'),
			sourcefile: 'polyEditGeometry.ts',
			loader: 'ts',
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

async function loadModifyGeom2() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-geom2-')), 'geom.mjs');
	await esbuild.build({
		stdin: {
			contents: await readFile('src/modifyGeometry2.ts', 'utf8'),
			sourcefile: 'modifyGeometry2.ts',
			loader: 'ts',
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('arc-fit of the 3 points (0,0),(10,10),(20,0) gives two segments whose arcs both lie on the circle centred (10,0) r=10 (check bulges = tan(θ/4))', async () => {
	const { fitArcBulges } = await loadGeom();
	const { bulgeToArc } = await loadModifyGeom2();

	const points = [[0, 0], [10, 10], [20, 0]];
	const result = fitArcBulges(points, false);

	assert.equal(result.points.length, 3);
	assert.equal(result.bulges.length, 2);

	// Both segments have included angle θ = 90° (π/2).
	// Because travel from (0,0) to (10,10) to (20,0) is clockwise, signed sweep is -π/2.
	// bulge = tan(θ/4) = tan(-π/8) = -tan(22.5°) = -(√2 - 1) ≈ -0.41421356
	const expectedBulge = Math.tan((-Math.PI / 2) / 4);
	const expectedBulgeMag = Math.tan((Math.PI / 2) / 4);

	assert.ok(Math.abs(result.bulges[0] - expectedBulge) < 1e-9, `bulge[0] was ${result.bulges[0]}`);
	assert.ok(Math.abs(result.bulges[1] - expectedBulge) < 1e-9, `bulge[1] was ${result.bulges[1]}`);
	assert.ok(Math.abs(Math.abs(result.bulges[0]) - expectedBulgeMag) < 1e-9);
	assert.ok(Math.abs(Math.abs(result.bulges[1]) - expectedBulgeMag) < 1e-9);

	// Both segments must lie on the circle centered at (10,0) with radius 10
	const arc1 = bulgeToArc(result.points[0], result.points[1], result.bulges[0]);
	const arc2 = bulgeToArc(result.points[1], result.points[2], result.bulges[1]);

	assert.ok(Math.abs(arc1.center[0] - 10) < 1e-6, `arc1 center x was ${arc1.center[0]}`);
	assert.ok(Math.abs(arc1.center[1] - 0) < 1e-6, `arc1 center y was ${arc1.center[1]}`);
	assert.ok(Math.abs(arc1.radius - 10) < 1e-6, `arc1 radius was ${arc1.radius}`);

	assert.ok(Math.abs(arc2.center[0] - 10) < 1e-6, `arc2 center x was ${arc2.center[0]}`);
	assert.ok(Math.abs(arc2.center[1] - 0) < 1e-6, `arc2 center y was ${arc2.center[1]}`);
	assert.ok(Math.abs(arc2.radius - 10) < 1e-6, `arc2 radius was ${arc2.radius}`);
});

test('quadratic B-spline of (0,0),(10,10),(20,0) passes through (0,0) and (20,0) and its midpoint is (10,5)', async () => {
	const { bSplinePoint, bSplinePolyline } = await loadGeom();

	const ctrl = [[0, 0], [10, 10], [20, 0]];

	// Hand computation:
	// Quadratic Bézier/B-spline with clamped knots:
	// B(t) = (1-t)^2 P0 + 2(1-t)t P1 + t^2 P2
	// B(0) = P0 = (0,0)
	// B(0.5) = 0.25*(0,0) + 0.5*(10,10) + 0.25*(20,0) = (10, 5)
	// B(1) = P2 = (20,0)
	const pt0 = bSplinePoint(ctrl, 2, 0);
	const ptMid = bSplinePoint(ctrl, 2, 0.5);
	const pt1 = bSplinePoint(ctrl, 2, 1);

	assert.equal(Math.round(pt0[0] * 1000) / 1000, 0);
	assert.equal(Math.round(pt0[1] * 1000) / 1000, 0);

	assert.equal(Math.round(ptMid[0] * 1000) / 1000, 10);
	assert.equal(Math.round(ptMid[1] * 1000) / 1000, 5);

	assert.equal(Math.round(pt1[0] * 1000) / 1000, 20);
	assert.equal(Math.round(pt1[1] * 1000) / 1000, 0);

	// Also verify full polyline sampling
	const polyline = bSplinePolyline(ctrl, 2, 8);
	const polyStart = polyline[0];
	const polyMid = polyline[Math.floor(polyline.length / 2)];
	const polyEnd = polyline[polyline.length - 1];

	assert.equal(Math.round(polyStart[0] * 1000) / 1000, 0);
	assert.equal(Math.round(polyStart[1] * 1000) / 1000, 0);

	assert.equal(Math.round(polyMid[0] * 1000) / 1000, 10);
	assert.equal(Math.round(polyMid[1] * 1000) / 1000, 5);

	assert.equal(Math.round(polyEnd[0] * 1000) / 1000, 20);
	assert.equal(Math.round(polyEnd[1] * 1000) / 1000, 0);
});

test('OVERKILL of lines (0,0)-(10,0) and (5,0)-(15,0) -> one line (0,0)-(15,0)', async () => {
	const { mergeCollinearLines } = await loadGeom();

	const lines = [
		{ start: [0, 0], end: [10, 0] },
		{ start: [5, 0], end: [15, 0] },
	];

	const res = mergeCollinearLines(lines, { tolerance: 1e-6, combinePartialOverlap: true });

	assert.equal(res.merged.length, 1);
	assert.deepEqual(res.merged[0].start, [0, 0]);
	assert.deepEqual(res.merged[0].end, [15, 0]);
	assert.equal(res.mergedCount, 1);
	assert.equal(res.deletedCount, 1);
});

test('exact duplicate circle removed', async () => {
	const { findDuplicateEntities } = await loadGeom();

	const circles = [
		{ center: [0, 0], radius: 10, layer: '0' },
		{ center: [0, 0], radius: 10, layer: '0' },
		{ center: [20, 20], radius: 5, layer: '0' },
	];

	const areEqual = (a, b, tol) =>
		Math.hypot(a.center[0] - b.center[0], a.center[1] - b.center[1]) <= tol &&
		Math.abs(a.radius - b.radius) <= tol &&
		a.layer === b.layer;

	const { unique, duplicates } = findDuplicateEntities(circles, areEqual, 1e-6);

	assert.equal(unique.length, 2);
	assert.equal(duplicates.length, 1);
	assert.deepEqual(duplicates[0].center, [0, 0]);
	assert.equal(duplicates[0].radius, 10);
});

test('polyline vertices (0,0),(0,0),(5,0) -> (0,0),(5,0)', async () => {
	const { removeDuplicateVertices } = await loadGeom();

	const verts = [[0, 0], [0, 0], [5, 0]];
	const res = removeDuplicateVertices(verts, [0, 0], false, 1e-6);

	assert.deepEqual(res.points, [[0, 0], [5, 0]]);
	assert.equal(res.removedCount, 1);
});

test('PEDIT Join of line (0,0)-(5,0) and arc ending at (5,0) within fuzz 0.1 gives one polyline with 1 bulge', async () => {
	const { joinPolylineChains } = await loadGeom();
	const { arcToBulge } = await loadModifyGeom2();

	// Line from (0,0) to (5,0)
	const line = { points: [[0, 0], [5, 0]], bulges: [0] };

	// Arc from (10,5) to (5,0) with center (5,5) radius 5
	const arcStart = [10, 5];
	const arcEnd = [5, 0];
	const arcCenter = [5, 5];
	const b = arcToBulge(arcStart, arcEnd, arcCenter, true);
	const arc = { points: [arcStart, arcEnd], bulges: [b] };

	// Join with fuzz 0.1
	const joined = joinPolylineChains([line, arc], 0.1);

	assert.ok(joined !== null);
	assert.equal(joined.joinedCount, 1);
	assert.equal(joined.points.length, 3);
	assert.deepEqual(joined.points[0], [0, 0]);
	assert.deepEqual(joined.points[1], [5, 0]);
	assert.deepEqual(joined.points[2], [10, 5]);

	// Result has 2 segments (3 vertices), exactly 1 with a non-zero bulge
	assert.equal(joined.bulges.length, 2);
	const nonZeroBulges = joined.bulges.filter(bg => Math.abs(bg) > 1e-6);
	assert.equal(nonZeroBulges.length, 1);
	assert.ok(Math.abs(Math.abs(nonZeroBulges[0]) - Math.abs(b)) < 1e-6);

	// Also verify with small fuzz gap: line ends at (5, 0.05)
	const lineWithFuzz = { points: [[0, 0], [5, 0.05]], bulges: [0] };
	const joinedWithFuzz = joinPolylineChains([lineWithFuzz, arc], 0.1);
	assert.ok(joinedWithFuzz !== null);
	assert.equal(joinedWithFuzz.joinedCount, 1);
	assert.equal(joinedWithFuzz.bulges.filter(bg => Math.abs(bg) > 1e-6).length, 1);
});

test('OVERKILL command: identical lines (same colour) -> one kept, overlapping collinear line merged', async () => {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-overkill-cmd-')), 'ok.mjs');
	const { threeExamples, trustedTypes } = await import('../plugins.mjs');
	await esbuild.build({
		stdin: { contents: `export * from '@mlightcad/data-model'; export * from './src/polyEditCommands.ts';`, resolveDir: process.cwd() },
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' }, plugins: [trustedTypes, threeExamples],
	});
	const { AcDbDatabase, AcDbLine, AcGePoint3d, acdbHostApplicationServices, overkillCommand } = await import(pathToFileURL(outfile).href);
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;
	const space = db.tables.blockTable.modelSpace;
	const a = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	const b = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	const c = new AcDbLine(new AcGePoint3d(0, 20, 0), new AcGePoint3d(10, 20, 0));
	const d = new AcDbLine(new AcGePoint3d(5, 20, 0), new AcGePoint3d(15, 20, 0));
	space.appendEntity([a, b, c, d]);
	const messages = [];
	const ctx = {
		getSelection: async () => [a, b, c, d],
		getKeyword: async () => 'Proceed',
		getDouble: async () => 0.000001,
		transaction: async fn => fn(),
		database: { erase: id => { const e = space.getIdAt(id); if (e) { e.erase(); } } },
		message: m => messages.push(m),
	};
	await overkillCommand(ctx);
	const left = space.newIterator().toArray().filter(e => !e.isErased).map(e => [e.startPoint.x, e.startPoint.y, e.endPoint.x, e.endPoint.y].map(v => Math.round(v * 1000) / 1000));
	left.sort((p, q) => p[1] - q[1] || p[0] - q[0]);
	assert.deepEqual(left, [[0, 0, 10, 0], [0, 20, 15, 20]], messages.join(' / '));
});
