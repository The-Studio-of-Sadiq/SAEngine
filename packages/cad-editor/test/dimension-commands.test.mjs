import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadDataModel() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-editor-test-')), 'data-model.mjs');
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

async function loadDimensionGeometry() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-dim-geom-')), 'dimGeom.mjs');
	await esbuild.build({
		stdin: {
			contents: await import('node:fs/promises').then(fs => fs.readFile('src/dimensionGeometry.ts', 'utf8')),
			sourcefile: 'dimensionGeometry.ts',
			loader: 'ts',
			resolveDir: path.resolve('src'),
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('pure geometry: angular dimension angle between two lines', async () => {
	const { angleBetweenLines } = await loadDimensionGeometry();

	// 1. Perpendicular lines at origin: (0,0)->(10,0) and (0,0)->(0,10)
	// Expected angle: 90 degrees = π/2 ≈ 1.570796 rad
	const perp = angleBetweenLines([0, 0], [10, 0], [0, 0], [0, 10]);
	assert.ok(perp);
	assert.deepEqual(perp.vertex, [0, 0]);
	assert.equal(Math.round(perp.angleDeg), 90);
	assert.ok(Math.abs(perp.angleRad - Math.PI / 2) < 1e-6);

	// 2. 60-degree angle: (0,0)->(10,0) and (0,0)->(5, 5*sqrt(3))
	// Expected angle: 60 degrees = π/3 ≈ 1.047198 rad
	const sixty = angleBetweenLines([0, 0], [10, 0], [0, 0], [5, 5 * Math.sqrt(3)]);
	assert.ok(sixty);
	assert.deepEqual(sixty.vertex, [0, 0]);
	assert.equal(Math.round(sixty.angleDeg), 60);
	assert.ok(Math.abs(sixty.angleRad - Math.PI / 3) < 1e-6);

	// 3. Translated intersection: horizontal at y=10, vertical at x=15
	// Intersection at (15, 10), angle = 90 degrees
	const translated = angleBetweenLines([0, 10], [20, 10], [15, 0], [15, 30]);
	assert.ok(translated);
	assert.deepEqual(translated.vertex, [15, 10]);
	assert.equal(Math.round(translated.angleDeg), 90);

	// 4. Parallel lines: should return undefined
	const parallel = angleBetweenLines([0, 0], [10, 0], [0, 5], [10, 5]);
	assert.equal(parallel, undefined);
});

test('pure geometry: radius and diameter values', async () => {
	const { calculateRadius, calculateDiameter } = await loadDimensionGeometry();

	// Circle centered at (10, 20), chord point at (13, 24)
	// dx = 3, dy = 4 -> radius = sqrt(3^2 + 4^2) = 5
	const r = calculateRadius([10, 20], [13, 24]);
	assert.equal(r, 5);

	// Opposite chord point at (7, 16)
	// diameter = sqrt((13-7)^2 + (24-16)^2) = sqrt(6^2 + 8^2) = 10
	const d = calculateDiameter([13, 24], [7, 16]);
	assert.equal(d, 10);
});

test('pure geometry: arc length with verified hand-computed values', async () => {
	const { calculateArcLength } = await loadDimensionGeometry();

	// Quarter circle: radius = 10, start = 0, end = π/2
	// Expected: 10 * (π/2) = 5π ≈ 15.707963
	const len1 = calculateArcLength(10, 0, Math.PI / 2);
	assert.ok(Math.abs(len1 - 5 * Math.PI) < 1e-6);

	// 120-degree arc: radius = 6, start = π/6 (30°), end = 5π/6 (150°)
	// Sweep = 2π/3. Expected: 6 * (2π/3) = 4π ≈ 12.566371
	const len2 = calculateArcLength(6, Math.PI / 6, 5 * Math.PI / 6);
	assert.ok(Math.abs(len2 - 4 * Math.PI) < 1e-6);

	// Wrap-around 90-degree arc: radius = 4, start = 7π/4 (315°), end = π/4 (45°)
	// Sweep = π/2. Expected: 4 * (π/2) = 2π ≈ 6.283185
	const len3 = calculateArcLength(4, 7 * Math.PI / 4, Math.PI / 4);
	assert.ok(Math.abs(len3 - 2 * Math.PI) < 1e-6);
});

test('pure geometry: ordinate X/Y datum selection by leader direction', async () => {
	const { determineOrdinateDatum, calculateOrdinateMeasurement } = await loadDimensionGeometry();

	const feature = [120, 80];

	// Leader displaced mostly vertically: dx = 2, dy = 100 -> dy >= dx -> X datum
	const datumX = determineOrdinateDatum(feature, [122, 180]);
	assert.equal(datumX, 'X');
	assert.equal(calculateOrdinateMeasurement(feature, datumX), 120);

	// Leader displaced mostly horizontally: dx = 100, dy = 2 -> dx > dy -> Y datum
	const datumY = determineOrdinateDatum(feature, [220, 82]);
	assert.equal(datumY, 'Y');
	assert.equal(calculateOrdinateMeasurement(feature, datumY), 80);
});

test('pure geometry: baseline offset and continue positions', async () => {
	const { calculateBaselineOffset, calculateContinueDimLinePoint } = await loadDimensionGeometry();

	// Horizontal base dimension: (0, 0) to (100, 0), dimLine at (50, 10).
	// Spacing = 7.5 mm. Normal points upward (+Y).
	const baseDimPt = [50, 10];
	const p1 = [0, 0];
	const p2 = [100, 0];

	const step1 = calculateBaselineOffset(baseDimPt, p1, p2, 7.5, 1);
	assert.deepEqual(step1, [50, 17.5]);

	const step2 = calculateBaselineOffset(baseDimPt, p1, p2, 7.5, 2);
	assert.deepEqual(step2, [50, 25.0]);

	// Continue dimension from p2=(100,0) to nextPt=(160,0).
	// Midpoint is (130, 0). With normal offset 10, new dimLinePoint is (130, 10).
	const contPt = calculateContinueDimLinePoint(p1, p2, baseDimPt, [160, 0]);
	assert.deepEqual(contPt, [130, 10]);
});

test('pure geometry: QDIM coordinate extraction and sorting', async () => {
	const { extractAndSortCoordinates } = await loadDimensionGeometry();

	const points = [
		[30, 10],
		[0, 5],
		[10, 20],
		[30, 10],
		[20, 0],
	];

	const xCoords = extractAndSortCoordinates(points, 'X');
	assert.deepEqual(xCoords, [0, 10, 20, 30]);

	const yCoords = extractAndSortCoordinates(points, 'Y');
	assert.deepEqual(yCoords, [0, 5, 10, 20]);
});

test('DXF round trip: all dimension entities preserve type and measurement through dxfOut and read', async () => {
	const dm = await loadDataModel();
	const {
		AcDbDatabase,
		AcDbFileType,
		AcGePoint3d,
		AcDbAlignedDimension,
		AcDbRotatedDimension,
		AcDbRadialDimension,
		AcDbDiametricDimension,
		AcDbArcDimension,
		AcDbOrdinateDimension,
		AcDb3PointAngularDimension,
	} = dm;

	const db = new AcDbDatabase();
	const ms = db.tables.blockTable.modelSpace;
	const p = (x, y, z = 0) => new AcGePoint3d(x, y, z);

	// 1. DIMALIGNED
	const dal = new AcDbAlignedDimension(p(0, 0), p(30, 40), p(15, 25));
	dal.measurement = 50.0;
	ms.appendEntity(dal);

	// 2. DIMROTATED / DIMLINEAR
	const rot = new AcDbRotatedDimension(p(0, 0), p(100, 0), p(50, 20));
	rot.rotation = 0;
	rot.measurement = 100.0;
	ms.appendEntity(rot);

	// 3. DIMRADIUS
	const rad = new AcDbRadialDimension(p(0, 0), p(25, 0), 10);
	rad.measurement = 25.0;
	ms.appendEntity(rad);

	// 4. DIMDIAMETER
	const dia = new AcDbDiametricDimension(p(25, 0), p(-25, 0), 10);
	dia.measurement = 50.0;
	ms.appendEntity(dia);

	// 5. DIMARC
	const arc = new AcDbArcDimension(p(0, 0), p(10, 0), p(0, 10), p(7, 7));
	arc.measurement = 15.708;
	ms.appendEntity(arc);

	// 6. DIMORDINATE
	const ord = new AcDbOrdinateDimension(p(123.45, 67.89), p(123.45, 100));
	ord.measurement = 123.45;
	ord.dimensionType = 70;
	ms.appendEntity(ord);

	// 7. DIMANGULAR (3-point / 2-line)
	const ang = new AcDb3PointAngularDimension(p(0, 0), p(10, 0), p(0, 10), p(5, 5));
	ang.measurement = 1.570796;
	ms.appendEntity(ang);

	const dxf = db.dxfOut(undefined, 6);
	assert.ok(typeof dxf === 'string' && dxf.length > 0);

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	const readEntities = db2.tables.blockTable.modelSpace.newIterator().toArray();

	assert.equal(readEntities.length, 7);

	// Map each read entity by its constructor typeName or subclass marker
	const results = readEntities.map(e => ({
		typeName: e.constructor.typeName,
		dxfTypeName: e.dxfTypeName,
		measurement: e.measurement,
	}));

	assert.equal(results[0].typeName, 'AlignedDimension');
	assert.ok(Math.abs(results[0].measurement - 50.0) < 1e-4);

	assert.equal(results[1].typeName, 'RotatedDimension');
	assert.ok(Math.abs(results[1].measurement - 100.0) < 1e-4);

	assert.equal(results[2].typeName, 'RadialDimension');
	assert.ok(Math.abs(results[2].measurement - 25.0) < 1e-4);

	assert.equal(results[3].typeName, 'DiametricDimension');
	assert.ok(Math.abs(results[3].measurement - 50.0) < 1e-4);

	assert.equal(results[4].typeName, 'ArcDimension');
	assert.ok(Math.abs(results[4].measurement - 15.708) < 1e-4);

	assert.equal(results[5].typeName, 'OrdinateDimension');
	assert.ok(Math.abs(results[5].measurement - 123.45) < 1e-4);

	assert.equal(results[6].typeName, '3PointAngularDimension');
	assert.ok(Math.abs(results[6].measurement - 1.570796) < 1e-4);
});
