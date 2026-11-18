import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-inquiry-')), 'geom.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/inquiryGeometry.ts', 'utf8'), sourcefile: 'inquiryGeometry.ts', loader: 'ts' },
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('rectangle closed polyline area and perimeter', async () => {
	const g = await load();
	assert.deepEqual(g.polylineMetrics([[0, 0], [1000, 0], [1000, 500], [0, 500]], [], true), { length: 3000, area: 500000 });
});

test('bulge one contributes exact semicircle area', async () => {
	const g = await load();
	const m = g.polylineMetrics([[0, 0], [100, 0], [100, 100], [0, 100]], [1, 0, 0, 0], true);
	assert.ok(Math.abs(m.area - (10000 + Math.PI * 2500 / 2)) < 1e-8);
});

test('circle metrics radius 100', async () => {
	const g = await load();
	assert.ok(Math.abs(g.circleMetrics(100).area - 31415.9265359) < 1e-5);
	assert.ok(Math.abs(g.circleMetrics(100).circumference - 628.3185307) < 1e-5);
});

test('quarter arc length radius 100', async () => {
	const g = await load();
	const a = g.arcFromBulge([100, 0], [0, 100], Math.tan(Math.PI / 8));
	assert.ok(Math.abs(a.radius * Math.abs(a.sweep) - 157.0796327) < 1e-6);
});

test('divide line into four intervals', async () => {
	const g = await load();
	assert.deepEqual(g.divideCurve([{ start: [0, 0], end: [100, 0] }], 4), [[25, 0], [50, 0], [75, 0]]);
});

test('divide quarter arc into two intervals', async () => {
	const g = await load();
	const pts = g.divideCurve([{ start: [100, 0], end: [0, 100], bulge: Math.tan(Math.PI / 8) }], 2);
	assert.ok(Math.abs(pts[0][0] - Math.SQRT1_2 * 100) < 1e-8);
	assert.ok(Math.abs(pts[0][1] - Math.SQRT1_2 * 100) < 1e-8);
});

test('measure line from start at spacing 30', async () => {
	const g = await load();
	assert.deepEqual(g.measureCurve([{ start: [0, 0], end: [100, 0] }], 30), [[30, 0], [60, 0], [90, 0]]);
});

test('ellipse metrics hand-computed: a=200 b=100 area 62831.85', async () => {
	const g = await load();
	const m = g.ellipseMetrics(200, 100);
	// Exact area: π · 200 · 100 = 20000π ≈ 62831.85307179586
	assert.equal(Number(m.area.toFixed(2)), 62831.85);
	// Ramanujan's perimeter check: h = (100/300)^2 = 1/9; P ≈ π · 300 · (1 + 3*(1/9)/(10 + sqrt(4 - 3/9))) ≈ 968.8448
	assert.ok(Math.abs(m.perimeter - 968.8448) < 0.01);
});

test('quarter arc r=100 chord-closed segment area hand-computed: 2853.98', async () => {
	const g = await load();
	const m = g.arcSegmentMetrics(100, Math.PI / 2);
	// Exact area: π · 100² / 4 − 100² / 2 = 2500π - 5000 ≈ 2853.981633974483
	assert.equal(Number(m.area.toFixed(2)), 2853.98);
	// Chord: 2 · 100 · sin(π/4) = 100 · √2 ≈ 141.421356
	assert.ok(Math.abs(m.chord - 100 * Math.SQRT2) < 1e-8);
	// Arc length: 100 · (π/2) = 50π ≈ 157.079633
	assert.ok(Math.abs(m.arcLength - 50 * Math.PI) < 1e-8);
	// Perimeter = arcLength + chord ≈ 298.500989
	assert.ok(Math.abs(m.perimeter - (50 * Math.PI + 100 * Math.SQRT2)) < 1e-8);
});

test('angle between lines along +X and along (1,1) is 45 degrees', async () => {
	const g = await load();
	const ang = g.angleBetweenLines([0, 0], [100, 0], [0, 0], [50, 50]);
	assert.ok(Math.abs(ang - 45) < 1e-8);
	const angV = g.angleBetweenVectors([1, 0], [1, 1]);
	assert.ok(Math.abs(angV - 45) < 1e-8);
});

test('arc included angle for various sweeps', async () => {
	const g = await load();
	// Quarter arc: 0 to π/2 => 90°
	assert.ok(Math.abs(g.arcIncludedAngle(0, Math.PI / 2) - 90) < 1e-8);
	// Arc crossing 0: 3π/2 (270°) to π/2 (90°) => 180°
	assert.ok(Math.abs(g.arcIncludedAngle(1.5 * Math.PI, 0.5 * Math.PI) - 180) < 1e-8);
});

test('three-point angle calculation', async () => {
	const g = await load();
	// Right angle: vertex at (0,0), ray1 (10,0), ray2 (0,20) => 90°
	assert.ok(Math.abs(g.threePointAngle([0, 0], [10, 0], [0, 20]) - 90) < 1e-8);
	// 45° angle with shifted vertex (5,5)
	assert.ok(Math.abs(g.threePointAngle([5, 5], [15, 5], [10, 10]) - 45) < 1e-8);
});

test('divide and measure open polyline with bulge segment', async () => {
	const g = await load();
	// Polyline: straight line from (0,0) to (100,0) [length 100], then semicircle (bulge 1) to (100,100) [radius 50, arc length 50π ≈ 157.0796]
	// Total length: 100 + 50π ≈ 257.079633
	const segs = g.curveSegments([[0, 0], [100, 0], [100, 100]], [0, 1], false);
	const expectedLen = 100 + 50 * Math.PI;
	assert.ok(Math.abs(g.totalLength(segs) - expectedLen) < 1e-6);

	// Midpoint (count = 2) should land at length expectedLen / 2 ≈ 128.5398, which is on the bulge arc
	const pts = g.divideCurve(segs, 2);
	assert.equal(pts.length, 1);
	// Arc center is (100, 50), radius 50. Distance along arc is 28.5398 radians.
	// Angle along arc from start (angle -π/2): theta = -π/2 + 28.5398 / 50 = -1.570796 + 0.570796 = -1.0 radian.
	const midX = 100 + 50 * Math.cos(-Math.PI / 2 + (expectedLen / 2 - 100) / 50);
	const midY = 50 + 50 * Math.sin(-Math.PI / 2 + (expectedLen / 2 - 100) / 50);
	assert.ok(Math.abs(pts[0][0] - midX) < 1e-6);
	assert.ok(Math.abs(pts[0][1] - midY) < 1e-6);

	// Measure with spacing 50: at d=50 (on line), d=100 (line end), d=150 (on arc), d=200 (on arc), d=250 (on arc)
	const mPts = g.measureCurve(segs, 50);
	assert.equal(mPts.length, 5);
	assert.ok(Math.abs(mPts[0][0] - 50) < 1e-6);
	assert.ok(Math.abs(mPts[0][1] - 0) < 1e-6);
	assert.ok(Math.abs(mPts[1][0] - 100) < 1e-6);
	assert.ok(Math.abs(mPts[1][1] - 0) < 1e-6);
});

test('polylineVertices extracts points and bulges from AcDbPolyline shape', async () => {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-inquiry-ea-')), 'entityAccess.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/entityAccess.ts', 'utf8'), sourcefile: 'entityAccess.ts', loader: 'ts' },
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	const ea = await import(pathToFileURL(outfile).href);
	const mockPoly = {
		numberOfVertices: 3,
		closed: true,
		getPoint2dAt(i) {
			const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }];
			return pts[i];
		},
		_geo: {
			vertices: [{ bulge: 0.5 }, { bulge: 1 }, { bulge: 0 }],
		},
	};
	const res = ea.polylineVertices(mockPoly);
	assert.deepEqual(res, {
		points: [[0, 0], [10, 0], [10, 10]],
		bulges: [0.5, 1, 0],
		closed: true,
	});
});
