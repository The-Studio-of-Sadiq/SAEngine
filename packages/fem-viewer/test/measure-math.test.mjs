import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
	const dir = await mkdtemp(path.join(tmpdir(), 'fem-measure-'));
	const outfile = path.join(dir, 'measureMath.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/measureMath.ts', 'utf8'), sourcefile: 'measureMath.ts', loader: 'ts' },
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	const mod = await import(pathToFileURL(outfile).href);
	return { mod, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

test('chooseSnap enforces vertex > midpoint > edge > face priority within thresholds', async () => {
	const { mod, cleanup } = await load();
	try {
		const candidates = [
			{ point: [0, 0, 0], kind: 'face', screenDistancePx: 0, depth: 0.1 },
			{ point: [50, 0, 0], kind: 'edge', screenDistancePx: 3, depth: 0.2 },
			{ point: [100, 0, 0], kind: 'midpoint', screenDistancePx: 8, depth: 0.2 },
			{ point: [200, 0, 0], kind: 'vertex', screenDistancePx: 12, depth: 0.3 },
		];
		const chosen = mod.chooseSnap(candidates);
		assert.equal(chosen?.kind, 'vertex');
		assert.deepEqual(chosen?.point, [200, 0, 0]);

		// When vertex is outside 14 px, midpoint wins.
		const chosenMid = mod.chooseSnap([
			...candidates.slice(0, 3),
			{ point: [200, 0, 0], kind: 'vertex', screenDistancePx: 18, depth: 0.1 },
		]);
		assert.equal(chosenMid?.kind, 'midpoint');

		// When only face is in range, face wins.
		const chosenFace = mod.chooseSnap([
			{ point: [10, 20, 30], kind: 'face', screenDistancePx: 0, depth: 0.2 },
			{ point: [50, 0, 0], kind: 'edge', screenDistancePx: 15, depth: 0.1 },
		]);
		assert.equal(chosenFace?.kind, 'face');
	} finally {
		await cleanup();
	}
});

test('extractFaceSnapCandidates snaps near triangle vertex, edge midpoint, and face interior', async () => {
	const { mod, cleanup } = await load();
	try {
		const verts = [[0, 0, 0], [1000, 0, 0], [0, 1000, 0]];
		const edges = [[[0, 0, 0], [1000, 0, 0]], [[1000, 0, 0], [0, 1000, 0]], [[0, 1000, 0], [0, 0, 0]]];
		// Simple orthographic screen projection: 1 px per 10 mm.
		const project = p => ({ x: p[0] / 10, y: p[1] / 10, depth: p[2], visible: true });

		// Cursor near vertex (1000, 0, 0) -> (100, 0) px
		const c1 = mod.extractFaceSnapCandidates([980, 10, 0], verts, edges, project, 99, 2, [0, 0, 1]);
		assert.equal(mod.chooseSnap(c1)?.kind, 'vertex');
		assert.deepEqual(mod.chooseSnap(c1)?.point, [1000, 0, 0]);

		// Cursor near midpoint (500, 0, 0) -> (50, 0) px
		const c2 = mod.extractFaceSnapCandidates([510, 10, 0], verts, edges, project, 51, 2, [0, 0, 1]);
		assert.equal(mod.chooseSnap(c2)?.kind, 'midpoint');
		assert.deepEqual(mod.chooseSnap(c2)?.point, [500, 0, 0]);

		// Cursor inside face (300, 300, 0) -> (30, 30) px
		const c3 = mod.extractFaceSnapCandidates([300, 300, 0], verts, edges, project, 30, 30, [0, 0, 1]);
		assert.equal(mod.chooseSnap(c3)?.kind, 'face');
	} finally {
		await cleanup();
	}
});

test('distancePointToPlane computes exact perpendicular distance and foot point', async () => {
	const { mod, cleanup } = await load();
	try {
		// Plane z = 3000 with normal (0, 0, 1), point (100, 200, 4250) -> distance 1250, foot (100, 200, 3000)
		const p1 = mod.distancePointToPlane([100, 200, 4250], [500, -100, 3000], [0, 0, 2]);
		assert.ok(Math.abs(p1.distance - 1250) < 1e-9);
		assert.deepEqual(p1.foot, [100, 200, 3000]);

		// Slanted 45-deg plane: x + y = 0, point (1000, 1000, 500) -> dist = 2000 / sqrt(2) = 1000*sqrt(2)
		const p2 = mod.distancePointToPlane([1000, 1000, 500], [0, 0, 0], [1, 1, 0]);
		assert.ok(Math.abs(p2.distance - 1000 * Math.SQRT2) < 1e-6);
		assert.ok(Math.abs(p2.foot[0]) < 1e-9 && Math.abs(p2.foot[1]) < 1e-9 && Math.abs(p2.foot[2] - 500) < 1e-9);
	} finally {
		await cleanup();
	}
});

test('angleBetweenEdges computes 90, 135, and skew edge angles', async () => {
	const { mod, cleanup } = await load();
	try {
		const right = mod.angleBetweenEdges([[0, 0, 0], [1000, 0, 0]], [[0, 0, 0], [0, 1000, 0]]);
		assert.equal(right.sharedVertex, true);
		assert.ok(Math.abs(right.angleDeg - 90) < 1e-9);

		// Shared vertex at (1000, 0, 0): edge A goes left (-1, 0), edge B goes (+1, +1) -> 135 degrees
		const obtuse = mod.angleBetweenEdges([[0, 0, 0], [1000, 0, 0]], [[1000, 0, 0], [2000, 1000, 0]]);
		assert.equal(obtuse.sharedVertex, true);
		assert.ok(Math.abs(obtuse.angleDeg - 135) < 1e-9);

		// Non-intersecting skew lines: 60 degrees
		const skew = mod.angleBetweenEdges([[0, 0, 0], [100, 0, 0]], [[0, 50, 200], [50, 50 + 50 * Math.sqrt(3), 200]]);
		assert.equal(skew.sharedVertex, false);
		assert.ok(Math.abs(skew.angleDeg - 60) < 1e-9);
	} finally {
		await cleanup();
	}
});

test('chainMetrics and formatMm compute segment sum and mm labels', async () => {
	const { mod, cleanup } = await load();
	try {
		const res = mod.chainMetrics([[0, 0, 0], [3000, 0, 0], [3000, 4000, 0], [3000, 4000, 1200]]);
		assert.deepEqual(res.segments, [3000, 4000, 1200]);
		assert.equal(res.total, 8200);
		assert.equal(mod.formatMm(3250.01), '3250 mm');
		assert.equal(mod.formatMm(12.46), '12.5 mm');
	} finally {
		await cleanup();
	}
});
