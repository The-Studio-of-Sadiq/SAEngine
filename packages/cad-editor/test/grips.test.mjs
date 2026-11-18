import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-grips-test-')), 'grips.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/gripGeometry.ts';
				export * from './src/gripEdit.ts';
				export * from './src/commands.ts';
				export * from './src/index.ts';
			`,
			resolveDir: process.cwd(),
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

function initWorkingDb(modules) {
	const { AcDbDatabase, acdbHostApplicationServices } = modules;
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;
	return db;
}

test('rotate (10,0) by 90° about (0,0) -> (0,10)', async () => {
	const { rotateGripPoint, rotatePoint } = await load();
	const fn = rotateGripPoint || rotatePoint;
	const res = fn([10, 0], [0, 0], 90);
	assert.deepEqual(res, [0, 10]);
});

test('scale (4,2) by 2 about (1,1) -> (7,3)', async () => {
	const { scaleGripPoint } = await load();
	const res = scaleGripPoint([4, 2], [1, 1], 2);
	assert.deepEqual(res, [7, 3]);
});

test('mirror (3,4) about line (0,0)-(10,0) -> (3,-4)', async () => {
	const { mirrorGripPoint } = await load();
	const res = mirrorGripPoint([3, 4], [0, 0], [10, 0]);
	assert.deepEqual(res, [3, -4]);
});

test('add vertex at segment midpoint of [(0,0),(10,0),(10,10)] after index 0 -> [(0,0),(5,0),(10,0),(10,10)]', async () => {
	const { addPolylineVertex } = await load();
	const vertices = [[0, 0], [10, 0], [10, 10]];
	const res = addPolylineVertex(vertices, 0);
	assert.deepEqual(res.vertices, [[0, 0], [5, 0], [10, 0], [10, 10]]);
});

test('remove vertex 1 of [(0,0),(10,0),(10,10)] -> [(0,0),(10,10)]', async () => {
	const { removePolylineVertex } = await load();
	const vertices = [[0, 0], [10, 0], [10, 10]];
	const res = removePolylineVertex(vertices, 1);
	assert.deepEqual(res.vertices, [[0, 0], [10, 10]]);
});

test('convert segment (0,0)-(10,0) to arc through (5,5) -> bulge = 1 (semicircle CCW)', async () => {
	const { convertSegmentToArc } = await load();
	// Chord [0,0] to [10,0] has length 10.
	// Midpoint is [5,0], distance to [5,5] is 5 (sagitta h = 5).
	// Arc radius R = (h^2 + (d/2)^2) / (2h) = (25 + 25) / 10 = 5.
	// Central angle = 180° (semicircle).
	// Bulge = tan(180° / 4) = tan(45°) = 1.
	// Cross product of (10, 0) and (5, 5) is +50 > 0 (CCW / left), so sign is +1.
	const bulge = convertSegmentToArc([0, 0], [10, 0], [5, 5]);
	assert.equal(bulge, 1);
});

test('data model: line midpoint grip translates whole line while endpoints move individually', async () => {
	const modules = await load();
	const { AcDbLine, AcGePoint3d, AcGeVector3d } = modules;
	initWorkingDb(modules);

	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	const grips = line.subGetGripPoints();
	// grips: [midpoint (5,0), startPoint (0,0), endPoint (10,0)]
	assert.equal(grips.length, 3);
	assert.deepEqual([grips[0].x, grips[0].y], [5, 0]);

	// Midpoint grip (index 0) moves the whole line
	line.subMoveGripPointsAt([0], new AcGeVector3d(0, 10, 0));
	assert.deepEqual([line.startPoint.x, line.startPoint.y], [0, 10]);
	assert.deepEqual([line.endPoint.x, line.endPoint.y], [10, 10]);

	// Endpoint grip (index 2) moves only endPoint
	line.subMoveGripPointsAt([2], new AcGeVector3d(5, 0, 0));
	assert.deepEqual([line.startPoint.x, line.startPoint.y], [0, 10]);
	assert.deepEqual([line.endPoint.x, line.endPoint.y], [15, 10]);
});

test('data model: circle center grip translates circle while quadrant grip modifies radius', async () => {
	const modules = await load();
	const { AcDbCircle, AcGePoint3d, AcGeVector3d } = modules;
	initWorkingDb(modules);

	const circle = new AcDbCircle(new AcGePoint3d(0, 0, 0), 10);
	const grips = circle.subGetGripPoints();
	// index 0 = center, index 1-4 = quadrants
	assert.equal(grips.length, 5);
	assert.deepEqual([grips[0].x, grips[0].y], [0, 0]);

	// Center grip translates circle
	circle.subMoveGripPointsAt([0], new AcGeVector3d(5, 5, 0));
	assert.deepEqual([circle.center.x, circle.center.y], [5, 5]);
	assert.equal(circle.radius, 10);

	// Quadrant grip (index 1: at 0° from center, currently [15, 5])
	// Moving by (5, 0, 0) extends radius to 15
	circle.subMoveGripPointsAt([1], new AcGeVector3d(5, 0, 0));
	assert.equal(Math.round(circle.radius), 15);
	assert.deepEqual([circle.center.x, circle.center.y], [5, 5]);
});

test('data model: arc center grip translates arc while endpoints adjust angles', async () => {
	const modules = await load();
	const { AcDbArc, AcGePoint3d, AcGeVector3d } = modules;
	initWorkingDb(modules);

	const arc = new AcDbArc(new AcGePoint3d(0, 0, 0), 10, 0, Math.PI / 2);
	const grips = arc.subGetGripPoints();
	// index 0 = center, index 1 = start, index 2 = end
	assert.equal(grips.length, 3);
	assert.deepEqual([grips[0].x, grips[0].y], [0, 0]);

	// Center grip moves whole arc
	arc.subMoveGripPointsAt([0], new AcGeVector3d(10, 20, 0));
	assert.deepEqual([arc.center.x, arc.center.y], [10, 20]);
});

test('grip sysvars: GRIPS, GRIPSIZE, GRIPOBJLIMIT can be read and updated via AcDbSysVarManager', async () => {
	const modules = await load();
	const { AcDbSystemVariables, AcDbSysVarManager } = modules;
	const db = initWorkingDb(modules);
	const sysVars = AcDbSysVarManager.instance();

	// Set sysvars
	sysVars.setVar(AcDbSystemVariables.GRIPS, 2, db);
	sysVars.setVar(AcDbSystemVariables.GRIPSIZE, 8, db);
	sysVars.setVar(AcDbSystemVariables.GRIPOBJLIMIT, 50, db);

	assert.equal(sysVars.getVar(AcDbSystemVariables.GRIPS, db), 2);
	assert.equal(sysVars.getVar(AcDbSystemVariables.GRIPSIZE, db), 8);
	assert.equal(sysVars.getVar(AcDbSystemVariables.GRIPOBJLIMIT, db), 50);

	// Turn off grips
	sysVars.setVar(AcDbSystemVariables.GRIPS, 0, db);
	assert.equal(sysVars.getVar(AcDbSystemVariables.GRIPS, db), 0);
});
