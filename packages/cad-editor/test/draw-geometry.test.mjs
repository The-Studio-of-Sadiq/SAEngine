/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function loadDrawGeometry() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-draw-test-')), 'drawGeometry.mjs');
	await esbuild.build({
		entryPoints: [path.resolve('src/drawGeometry.ts')],
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('circle 3P through (0,0),(2,0),(1,1) -> centre (1,0) r 1', async () => {
	const { circle3P } = await loadDrawGeometry();
	const res = circle3P([0, 0], [2, 0], [1, 1]);
	assert.ok(Math.abs(res.center[0] - 1) < 1e-8, `center.x expected 1 got ${res.center[0]}`);
	assert.ok(Math.abs(res.center[1] - 0) < 1e-8, `center.y expected 0 got ${res.center[1]}`);
	assert.ok(Math.abs(res.radius - 1) < 1e-8, `radius expected 1 got ${res.radius}`);
});

test('TTR to lines y=0 and x=0 with r=1 near (1,1) -> centre (1,1)', async () => {
	const { circleTTR } = await loadDrawGeometry();
	const lineY0 = { start: [0, 0], end: [10, 0] }; // y = 0
	const lineX0 = { start: [0, 0], end: [0, 10] }; // x = 0
	const res = circleTTR(lineY0, lineX0, 1, [1, 1], [1, 1]);
	assert.ok(Math.abs(res.center[0] - 1) < 1e-8, `center.x expected 1 got ${res.center[0]}`);
	assert.ok(Math.abs(res.center[1] - 1) < 1e-8, `center.y expected 1 got ${res.center[1]}`);
	assert.ok(Math.abs(res.radius - 1) < 1e-8, `radius expected 1 got ${res.radius}`);
});

test('arc Start-Center-Angle start (1,0) centre (0,0) angle 90 -> end (0,1)', async () => {
	const { arcStartCenterAngle } = await loadDrawGeometry();
	const res = arcStartCenterAngle([1, 0], [0, 0], Math.PI / 2);
	assert.ok(Math.abs(res.radius - 1) < 1e-8, `radius expected 1 got ${res.radius}`);
	assert.ok(Math.abs(res.startPoint[0] - 1) < 1e-8);
	assert.ok(Math.abs(res.startPoint[1] - 0) < 1e-8);
	assert.ok(Math.abs(res.endPoint[0] - 0) < 1e-8, `end.x expected 0 got ${res.endPoint[0]}`);
	assert.ok(Math.abs(res.endPoint[1] - 1) < 1e-8, `end.y expected 1 got ${res.endPoint[1]}`);
});

test('rectangle 100x50 with fillet 10 -> 4 straight segments + 4 bulges of tan(22.5°)=0.41421', async () => {
	const { rectangleFillet } = await loadDrawGeometry();
	const res = rectangleFillet([0, 0], [100, 50], 10);
	assert.equal(res.points.length, 8);
	assert.equal(res.closed, true);

	const expectedBulge = Math.tan(Math.PI / 8); // 0.41421356...
	assert.ok(Math.abs(expectedBulge - 0.41421356) < 1e-5);

	const straightSegs = res.bulges.filter(b => Math.abs(b) < 1e-8);
	const filletBulges = res.bulges.filter(b => Math.abs(b - expectedBulge) < 1e-6);

	assert.equal(straightSegs.length, 4, `expected 4 straight segments, got ${straightSegs.length}`);
	assert.equal(filletBulges.length, 4, `expected 4 fillet bulges, got ${filletBulges.length}`);
	for (const b of filletBulges) {
		assert.ok(Math.abs(b - 0.41421) < 1e-4);
	}
});

test('polygon 6 sides circumscribed about r=100 -> vertex distance 100/cos(30°)=115.47', async () => {
	const { polygonCircumscribed } = await loadDrawGeometry();
	const res = polygonCircumscribed([0, 0], 100, 6);
	assert.equal(res.points.length, 6);
	assert.equal(res.closed, true);

	const expectedDist = 100 / Math.cos(Math.PI / 6); // 115.4700538...
	assert.ok(Math.abs(expectedDist - 115.47) < 0.01);

	for (const pt of res.points) {
		const dist = Math.hypot(pt[0], pt[1]);
		assert.ok(Math.abs(dist - expectedDist) < 1e-6, `vertex distance expected ${expectedDist} got ${dist}`);
	}
});

test('donut inside 0 outside 10 -> width 5, radius 2.5', async () => {
	const { donut } = await loadDrawGeometry();
	const res = donut([0, 0], 0, 10);
	assert.equal(res.width, 5);
	assert.equal(res.meanRadius, 2.5);
	assert.equal(res.closed, true);
	assert.equal(res.points.length, 2);
	assert.deepEqual(res.bulges, [1, 1]);
	assert.equal(res.constantWidth, 5);
});

test('circle 2P through (0,0) and (10,0) -> centre (5,0) r 5', async () => {
	const { circle2P } = await loadDrawGeometry();
	const res = circle2P([0, 0], [10, 0]);
	assert.deepEqual(res.center, [5, 0]);
	assert.equal(res.radius, 5);
});

test('circle TTT incircle of triangle formed by y=0, x=0, and x+y=1', async () => {
	const { circleTTT } = await loadDrawGeometry();
	const l1 = { start: [0, 0], end: [2, 0] }; // y = 0
	const l2 = { start: [0, 0], end: [0, 2] }; // x = 0
	const l3 = { start: [1, 0], end: [0, 1] }; // x + y = 1
	const res = circleTTT(l1, l2, l3);
	// Inradius of right triangle with legs 1, 1, hypotenuse sqrt(2): r = (1 + 1 - sqrt(2)) / 2 = 1 - 1/sqrt(2) ≈ 0.292893
	const expectedR = 1 - 1 / Math.SQRT2;
	assert.ok(Math.abs(res.radius - expectedR) < 1e-6);
	assert.ok(Math.abs(res.center[0] - expectedR) < 1e-6);
	assert.ok(Math.abs(res.center[1] - expectedR) < 1e-6);
});

test('arc Start-Center-Length with chord length', async () => {
	const { arcStartCenterLength } = await loadDrawGeometry();
	// Start (10, 0), Center (0, 0), Chord 10*sqrt(2) => quarter arc 90 deg
	const res = arcStartCenterLength([10, 0], [0, 0], 10 * Math.SQRT2);
	assert.ok(Math.abs(res.radius - 10) < 1e-6);
	assert.ok(Math.abs(res.endPoint[0] - 0) < 1e-6);
	assert.ok(Math.abs(res.endPoint[1] - 10) < 1e-6);
});

test('arc Continue tangent to previous line', async () => {
	const { arcContinue } = await loadDrawGeometry();
	// Line from (0,0) to (10,0) has direction 0 rad. Tangent at (10,0) is 0 rad. End (15, 5).
	const res = arcContinue([10, 0], 0, [15, 5]);
	assert.ok(Math.abs(res.startPoint[0] - 10) < 1e-6);
	assert.ok(Math.abs(res.startPoint[1] - 0) < 1e-6);
	assert.ok(Math.abs(res.endPoint[0] - 15) < 1e-6);
	assert.ok(Math.abs(res.endPoint[1] - 5) < 1e-6);
	// Center should be (10, 5), radius 5
	assert.ok(Math.abs(res.center[0] - 10) < 1e-6);
	assert.ok(Math.abs(res.center[1] - 5) < 1e-6);
	assert.ok(Math.abs(res.radius - 5) < 1e-6);
});

test('polygon inscribed 4 sides in radius 10', async () => {
	const { polygonInscribed } = await loadDrawGeometry();
	const res = polygonInscribed([0, 0], 10, 4);
	assert.equal(res.points.length, 4);
	assert.equal(res.closed, true);
	for (const pt of res.points) {
		assert.ok(Math.abs(Math.hypot(pt[0], pt[1]) - 10) < 1e-6);
	}
});

test('rectangle dimensions 100x50', async () => {
	const { rectangleDimensions } = await loadDrawGeometry();
	const res = rectangleDimensions([0, 0], 100, 50);
	assert.equal(res.points.length, 4);
	assert.deepEqual(res.points, [[0, 0], [100, 0], [100, 50], [0, 50]]);
	assert.equal(res.closed, true);
});
