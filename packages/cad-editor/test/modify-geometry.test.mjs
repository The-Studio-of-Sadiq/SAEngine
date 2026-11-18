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

async function loadModifyGeometry() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-modify-test-')), 'modifyGeometry.mjs');
	await esbuild.build({
		entryPoints: [path.resolve('src/modifyGeometry.ts')],
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('fillet of A [-50,0]->[500,0] and B [0,-50]->[0,500] with r=100 and positive picks', async () => {
	const { filletLines } = await loadModifyGeometry();
	const l1 = { kind: 'line', start: [-50, 0], end: [500, 0] };
	const l2 = { kind: 'line', start: [0, -50], end: [0, 500] };
	const res = filletLines(l1, l2, 100, [300, 0], [0, 300]);

	assert.ok(res);
	assert.deepEqual(res.lines[0].start, [100, 0]);
	assert.deepEqual(res.lines[0].end, [500, 0]);
	assert.deepEqual(res.lines[1].start, [0, 100]);
	assert.deepEqual(res.lines[1].end, [0, 500]);
	assert.ok(res.arc);
	assert.deepEqual(res.arc.center, [100, 100]);
	assert.equal(res.arc.radius, 100);
	assert.equal(res.arc.startAngle, 180);
	assert.equal(res.arc.endAngle, 270);
});

test('fillet of A [-50,0]->[500,0] and B [0,-50]->[0,500] with r=0 meets at corner [0,0]', async () => {
	const { filletLines } = await loadModifyGeometry();
	const l1 = { kind: 'line', start: [-50, 0], end: [500, 0] };
	const l2 = { kind: 'line', start: [0, -50], end: [0, 500] };
	const res = filletLines(l1, l2, 0, [300, 0], [0, 300]);

	assert.ok(res);
	assert.deepEqual(res.lines[0].start, [0, 0]);
	assert.deepEqual(res.lines[0].end, [500, 0]);
	assert.deepEqual(res.lines[1].start, [0, 0]);
	assert.deepEqual(res.lines[1].end, [0, 500]);
	assert.equal(res.arc, undefined);
});

test('fillet with picks on negative sides produces center [-100,-100], start 0, end 90', async () => {
	const { filletLines } = await loadModifyGeometry();
	const l1 = { kind: 'line', start: [-500, 0], end: [50, 0] };
	const l2 = { kind: 'line', start: [0, -500], end: [0, 50] };
	const res = filletLines(l1, l2, 100, [-300, 0], [0, -300]);

	assert.ok(res);
	assert.deepEqual(res.lines[0].start, [-500, 0]);
	assert.deepEqual(res.lines[0].end, [-100, 0]);
	assert.deepEqual(res.lines[1].start, [0, -500]);
	assert.deepEqual(res.lines[1].end, [0, -100]);
	assert.ok(res.arc);
	assert.deepEqual(res.arc.center, [-100, -100]);
	assert.equal(res.arc.radius, 100);
	assert.equal(res.arc.startAngle, 0);
	assert.equal(res.arc.endAngle, 90);
});

test('chamfer of A [0,0]->[500,0] and B [0,0]->[0,500] with d1=d2=100', async () => {
	const { chamferLines } = await loadModifyGeometry();
	const l1 = { kind: 'line', start: [0, 0], end: [500, 0] };
	const l2 = { kind: 'line', start: [0, 0], end: [0, 500] };
	const res = chamferLines(l1, l2, 100, 100, [300, 0], [0, 300]);

	assert.ok(res);
	assert.deepEqual(res.lines[0].start, [100, 0]);
	assert.deepEqual(res.lines[0].end, [500, 0]);
	assert.deepEqual(res.lines[1].start, [0, 100]);
	assert.deepEqual(res.lines[1].end, [0, 500]);
	assert.ok(res.chamferLine);
	assert.deepEqual(res.chamferLine.start, [100, 0]);
	assert.deepEqual(res.chamferLine.end, [0, 100]);
});

test('trim of line [0,0]->[100,0] with cutters x=25 and x=75 picked at [50,0]', async () => {
	const { trimLine } = await loadModifyGeometry();
	const line = { kind: 'line', start: [0, 0], end: [100, 0] };
	const cutters = [
		{ kind: 'line', start: [25, -50], end: [25, 50] },
		{ kind: 'line', start: [75, -50], end: [75, 50] },
	];
	const pieces = trimLine(line, cutters, [50, 0]);

	assert.equal(pieces.length, 2);
	assert.deepEqual(pieces[0].start, [0, 0]);
	assert.deepEqual(pieces[0].end, [25, 0]);
	assert.deepEqual(pieces[1].start, [75, 0]);
	assert.deepEqual(pieces[1].end, [100, 0]);
});

test('extend of line [0,0]->[10,0] to boundary x=20 extends end to [20,0]', async () => {
	const { extendLine } = await loadModifyGeometry();
	const line = { kind: 'line', start: [0, 0], end: [10, 0] };
	const boundaries = [
		{ kind: 'line', start: [20, -50], end: [20, 50] },
	];
	const extended = extendLine(line, boundaries, [8, 0]);

	assert.ok(extended);
	assert.deepEqual(extended.start, [0, 0]);
	assert.deepEqual(extended.end, [20, 0]);
});

test('circle trimmed to an arc', async () => {
	const { trimCircle } = await loadModifyGeometry();
	const circle = { kind: 'circle', center: [0, 0], radius: 100 };
	const cutters = [
		{ kind: 'line', start: [-120, 0], end: [120, 0] },
	];
	// Pick top half at [0, 100] (angle 90°): top half removed, bottom arc remains
	const arc = trimCircle(circle, cutters, [0, 100]);
	assert.ok(arc);
	assert.deepEqual(arc.center, [0, 0]);
	assert.equal(arc.radius, 100);
	assert.equal(arc.startAngle, 180);
	assert.equal(arc.endAngle, 0);

	// Pick bottom half at [0, -100] (angle 270°): bottom half removed, top arc remains
	const topArc = trimCircle(circle, cutters, [0, -100]);
	assert.ok(topArc);
	assert.deepEqual(topArc.center, [0, 0]);
	assert.equal(topArc.radius, 100);
	assert.equal(topArc.startAngle, 0);
	assert.equal(topArc.endAngle, 180);
});

test('trimArc removes picked interval', async () => {
	const { trimArc } = await loadModifyGeometry();
	const arc = { kind: 'arc', center: [0, 0], radius: 100, startAngle: 0, endAngle: 180 };
	const cutters = [{ kind: 'line', start: [0, -10], end: [0, 110] }];
	// Cutter hits at [0, 100] (angle 90). Pick at [50, 86.6] (angle 60)
	const pieces = trimArc(arc, cutters, [50, 86.6]);
	assert.equal(pieces.length, 1);
	assert.equal(pieces[0].startAngle, 90);
	assert.equal(pieces[0].endAngle, 180);
});

test('extendArc extends end nearest pick to boundary', async () => {
	const { extendArc } = await loadModifyGeometry();
	const arc = { kind: 'arc', center: [0, 0], radius: 100, startAngle: 45, endAngle: 90 };
	const boundaries = [{ kind: 'line', start: [-200, 0], end: [200, 0] }];
	// Pick near startAngle 45
	const extended = extendArc(arc, boundaries, [71, 71]);
	assert.ok(extended);
	assert.equal(extended.startAngle, 0);
	assert.equal(extended.endAngle, 90);
});

test('trimPolyline trims open polyline end segment', async () => {
	const { trimPolyline } = await loadModifyGeometry();
	const poly = { kind: 'polyline', points: [[0, 0], [100, 0], [100, 100]], closed: false };
	const cutters = [{ kind: 'line', start: [50, -20], end: [50, 20] }];
	const pieces = trimPolyline(poly, cutters, [25, 0]);
	assert.equal(pieces.length, 1);
	assert.deepEqual(pieces[0].points, [[50, 0], [100, 0], [100, 100]]);
});

test('extendPolyline extends open polyline end to boundary', async () => {
	const { extendPolyline } = await loadModifyGeometry();
	const poly = { kind: 'polyline', points: [[0, 0], [10, 0], [10, 10]], closed: false };
	const boundaries = [{ kind: 'line', start: [-20, -50], end: [-20, 50] }];
	const extended = extendPolyline(poly, boundaries, [0, 0]);
	assert.ok(extended);
	assert.deepEqual(extended.points, [[-20, 0], [10, 0], [10, 10]]);
});
