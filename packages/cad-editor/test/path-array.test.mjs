import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { readFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { threeExamples, trustedTypes } from '../plugins.mjs';

const rootDir = path.resolve(import.meta.dirname, '..');
const srcDir = path.resolve(rootDir, 'src');

async function loadGeom() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-path-geom-')), 'geom.mjs');
	await esbuild.build({
		stdin: {
			contents: await readFile(path.join(srcDir, 'pathGeometry.ts'), 'utf8'),
			sourcefile: 'pathGeometry.ts',
			loader: 'ts',
			resolveDir: srcDir,
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
		define: { define: 'undefined' },
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('5 items Divide along line (0,0)-(100,0) -> x = 0,25,50,75,100', async () => {
	const { linePath, computePathArrayTransforms } = await loadGeom();
	const line = linePath([0, 0], [100, 0]);
	assert.equal(line.length, 100);

	const transforms = computePathArrayTransforms(line, {
		method: 'Divide',
		itemCount: 5,
		basePoint: [0, 0],
	});

	assert.equal(transforms.length, 5);
	const xs = transforms.map(t => Math.round(t.position[0]));
	assert.deepEqual(xs, [0, 25, 50, 75, 100]);
	for (const t of transforms) {
		assert.equal(Math.round(t.position[1]), 0);
	}
});

test('Measure spacing 30 on the same line -> 0,30,60,90', async () => {
	const { linePath, computePathArrayTransforms } = await loadGeom();
	const line = linePath([0, 0], [100, 0]);

	const transforms = computePathArrayTransforms(line, {
		method: 'Measure',
		itemSpacing: 30,
		basePoint: [0, 0],
	});

	assert.equal(transforms.length, 4);
	const xs = transforms.map(t => Math.round(t.position[0]));
	assert.deepEqual(xs, [0, 30, 60, 90]);
});

test('point at half length of a semicircle arc centre (0,0) r 10 from (10,0) to (-10,0) CCW -> (0,10), tangent angle 180°', async () => {
	const { arcPath } = await loadGeom();
	// Start (10,0) is angle 0, End (-10,0) is angle PI (180 deg)
	const arc = arcPath([0, 0], 10, 0, Math.PI);
	const expectedLength = 10 * Math.PI;
	assert.equal(Math.abs(arc.length - expectedLength) < 1e-6, true);

	const half = arc.pointAndTangentAt(arc.length / 2);
	assert.equal(Math.round(half.point[0] * 1000) / 1000, 0);
	assert.equal(Math.round(half.point[1] * 1000) / 1000, 10);

	const tangentDeg = Math.round((half.tangentAngle * 180 / Math.PI) * 1000) / 1000;
	assert.equal(tangentDeg, 180);
});

test('Align on -> that item rotated 90° more than at the start', async () => {
	const { arcPath, computePathArrayTransforms } = await loadGeom();
	// Semicircle arc: start tangent is 90° (PI/2), half length tangent is 180° (PI)
	const arc = arcPath([0, 0], 10, 0, Math.PI);

	const transforms = computePathArrayTransforms(arc, {
		method: 'Divide',
		itemCount: 3, // start, middle (half length), end
		alignItems: true,
		basePoint: [10, 0],
	});

	assert.equal(transforms.length, 3);
	// Start item rotation delta = 0
	assert.equal(Math.round(transforms[0].rotationAngle * 180 / Math.PI), 0);
	// Middle item rotation delta = 90° (180° - 90°)
	assert.equal(Math.round(transforms[1].rotationAngle * 180 / Math.PI), 90);
});

test('Align off -> items are translated without rotation', async () => {
	const { arcPath, computePathArrayTransforms } = await loadGeom();
	const arc = arcPath([0, 0], 10, 0, Math.PI);

	const transforms = computePathArrayTransforms(arc, {
		method: 'Divide',
		itemCount: 3,
		alignItems: false,
		basePoint: [10, 0],
	});

	assert.equal(transforms.length, 3);
	for (const t of transforms) {
		assert.equal(t.rotationAngle, 0);
	}
});

test('Multiple rows offset perpendicularly to path tangent', async () => {
	const { linePath, computePathArrayTransforms } = await loadGeom();
	const line = linePath([0, 0], [100, 0]);

	const transforms = computePathArrayTransforms(line, {
		method: 'Measure',
		itemSpacing: 50,
		rows: 2,
		rowSpacing: 10,
		alignItems: true,
		basePoint: [0, 0],
	});

	// 2 rows * 3 items (0, 50, 100) = 6
	assert.equal(transforms.length, 6);
	const row0 = transforms.filter(t => t.row === 0);
	const row1 = transforms.filter(t => t.row === 1);
	assert.equal(row0.length, 3);
	assert.equal(row1.length, 3);

	// Line along +X has normal along +Y
	for (const t of row1) {
		assert.equal(Math.round(t.position[1]), 10);
	}
});

test('Polyline with bulge generates arc and line segments', async () => {
	const { polylinePath } = await loadGeom();
	// (0,0) to (10,0) with bulge 1 (semicircle CCW, r=5, len=5*PI), then to (10,10) straight (len=10)
	const poly = polylinePath([[0, 0], [10, 0], [10, 10]], [1, 0], false);
	const expectedLen = 5 * Math.PI + 10;
	assert.equal(Math.abs(poly.length - expectedLen) < 1e-4, true);

	// Sample start of straight segment
	const atStraight = poly.pointAndTangentAt(5 * Math.PI + 5);
	assert.equal(Math.round(atStraight.point[0]), 10);
	assert.equal(Math.round(atStraight.point[1]), 5);
});
