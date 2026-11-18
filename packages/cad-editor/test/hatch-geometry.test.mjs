import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadHatchGeometry() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-hatch-geom-')), 'hatchGeom.mjs');
	await esbuild.build({
		stdin: {
			contents: "export * from './src/hatchGeometry.ts';",
			resolveDir: process.cwd(),
			loader: 'ts',
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

async function loadDataModel() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-hatch-dm-')), 'data-model.mjs');
	await esbuild.build({
		stdin: { contents: "export * from '@mlightcad/data-model';", resolveDir: process.cwd() },
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

test('boundary detection inside a 1000x500 rectangle made of 4 separate lines yields loop with area 500000', async () => {
	const geom = await loadHatchGeometry();
	const segments = [
		{ start: [0, 0], end: [1000, 0], bulge: 0 },
		{ start: [1000, 0], end: [1000, 500], bulge: 0 },
		{ start: [1000, 500], end: [0, 500], bulge: 0 },
		{ start: [0, 500], end: [0, 0], bulge: 0 },
	];

	const loop = geom.findMinimalEnclosingLoop(segments, [500, 250]);
	assert.ok(loop, 'Loop should be detected');
	assert.equal(loop.closed, true);
	assert.equal(loop.vertices.length, 4);
	assert.equal(loop.area, 500000);

	// Verify hand-computed corners (in CCW order)
	const pts = loop.vertices.map(v => [Math.round(v.x), Math.round(v.y)]);
	assert.deepEqual(
		new Set(pts.map(p => `${p[0]},${p[1]}`)),
		new Set(['0,0', '1000,0', '1000,500', '0,500']),
	);
});

test('boundary detection in a room formed by two crossing walls and a rectangle', async () => {
	const geom = await loadHatchGeometry();
	// Rectangle 1000x800 with crossing walls at x=400 and y=300
	const segments = [
		// Outer rectangle
		{ start: [0, 0], end: [1000, 0], bulge: 0 },
		{ start: [1000, 0], end: [1000, 800], bulge: 0 },
		{ start: [1000, 800], end: [0, 800], bulge: 0 },
		{ start: [0, 800], end: [0, 0], bulge: 0 },
		// Internal walls
		{ start: [0, 300], end: [1000, 300], bulge: 0 },
		{ start: [400, 0], end: [400, 800], bulge: 0 },
	];

	// Pick point (200, 150) inside the bottom-left room: [0, 400] x [0, 300]
	// Expected loop: (0,0), (400,0), (400,300), (0,300).
	// Hand-computed area = 400 * 300 = 120000.
	const loop1 = geom.findMinimalEnclosingLoop(segments, [200, 150]);
	assert.ok(loop1, 'Loop 1 should be detected');
	assert.equal(loop1.area, 120000);
	const pts1 = loop1.vertices.map(v => `${Math.round(v.x)},${Math.round(v.y)}`);
	assert.deepEqual(
		new Set(pts1),
		new Set(['0,0', '400,0', '400,300', '0,300']),
	);

	// Pick point (700, 550) inside the top-right room: [400, 1000] x [300, 800]
	// Width = 600, Height = 500, Hand-computed area = 600 * 500 = 300000.
	const loop2 = geom.findMinimalEnclosingLoop(segments, [700, 550]);
	assert.ok(loop2, 'Loop 2 should be detected');
	assert.equal(loop2.area, 300000);
	const pts2 = loop2.vertices.map(v => `${Math.round(v.x)},${Math.round(v.y)}`);
	assert.deepEqual(
		new Set(pts2),
		new Set(['400,300', '1000,300', '1000,800', '400,800']),
	);
});

test('a circle island inside a rectangle with Select objects produces two loops', async () => {
	const geom = await loadHatchGeometry();
	const dm = await loadDataModel();

	// Outer rectangle: 1000 x 1000 polyline
	const rect = new dm.AcDbPolyline();
	rect.closed = true;
	rect.addVertexAt(0, new dm.AcGePoint2d(0, 0));
	rect.addVertexAt(1, new dm.AcGePoint2d(1000, 0));
	rect.addVertexAt(2, new dm.AcGePoint2d(1000, 1000));
	rect.addVertexAt(3, new dm.AcGePoint2d(0, 1000));

	// Inner circle: center (500, 500), radius 200
	const circle = new dm.AcDbCircle(new dm.AcGePoint3d(500, 500, 0), 200);

	const detected = geom.detectLoopsFromObjects([rect, circle]);
	assert.ok(detected, 'Loops should be detected');

	// Outer loop has area 1,000,000
	assert.equal(detected.outer.area, 1000000);
	assert.equal(detected.outer.closed, true);

	// Island loop has area π * 200^2 ≈ 125663.7
	assert.equal(detected.islands.length, 1);
	const expectedCircleArea = Math.PI * 200 * 200;
	assert.ok(
		Math.abs(detected.islands[0].area - expectedCircleArea) < 1e-3,
		`Circle area ${detected.islands[0].area} should match ${expectedCircleArea}`,
	);

	// Total 2 loops
	const totalLoops = [detected.outer, ...detected.islands];
	assert.equal(totalLoops.length, 2);
});

test('DXF round trip of an AcDbHatch preserves pattern name, scale, angle, and loops', async () => {
	const dm = await loadDataModel();
	const { AcDbDatabase, AcDbFileType, AcDbHatch, AcDbHatchPatternType, AcGePolyline2d, acdbHostApplicationServices } = dm;

	const db1 = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db1;
	const hatch = new AcDbHatch();
	hatch.patternName = 'ANSI31';
	hatch.patternType = AcDbHatchPatternType.Predefined;
	hatch.patternScale = 2.5;
	hatch.patternAngle = Math.PI / 4; // 45 degrees

	const polylineLoop = new AcGePolyline2d();
	polylineLoop.closed = true;
	polylineLoop.addVertexAt(0, { x: 0, y: 0, bulge: 0 });
	polylineLoop.addVertexAt(1, { x: 500, y: 0, bulge: 0 });
	polylineLoop.addVertexAt(2, { x: 500, y: 300, bulge: 0 });
	polylineLoop.addVertexAt(3, { x: 0, y: 300, bulge: 0 });
	hatch.add(polylineLoop);

	db1.tables.blockTable.modelSpace.appendEntity(hatch);

	const output = db1.dxfOut(undefined, 6);
	const dxfText = typeof output === 'string' ? output : new TextDecoder().decode(output);

	// Read into a new database
	const db2 = new AcDbDatabase();
	await db2.read(dxfText, { readOnly: false }, AcDbFileType.DXF);

	const entities = db2.tables.blockTable.modelSpace.newIterator().toArray();
	const savedHatch = entities.find(e => e.dxfTypeName === 'HATCH');

	assert.ok(savedHatch, 'HATCH entity must be found after DXF round trip');
	assert.equal(savedHatch.patternName, 'ANSI31');
	assert.equal(savedHatch.patternScale, 2.5);
	assert.ok(
		Math.abs(savedHatch.patternAngle - Math.PI / 4) < 1e-4,
		`Pattern angle ${savedHatch.patternAngle} should be ~π/4`,
	);

	// Loop count kept
	const loops = savedHatch._geo?.loops;
	assert.ok(loops, 'Loops must exist on round-tripped hatch');
	assert.equal(loops.length, 1, 'Loop count must be 1');
	assert.equal(loops[0].numberOfVertices, 4, 'Loop vertex count must be 4');
});
