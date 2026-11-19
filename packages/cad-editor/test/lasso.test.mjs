import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-lasso-')), 'lasso.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/selectionGeometry.ts';
				export { applyGenerated } from './src/generated.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' },
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('pickDraftingPolygon: window with concave L selects inside line and not line in notch; crossing and fence select crossed lines', async () => {
	const m = await load();
	const db = new m.AcDbDatabase();
	m.acdbHostApplicationServices().workingDatabase = db;

	// Concave L-shaped polygon vertices:
	// Branch 1: [0, 0] -> [30, 0] -> [30, 10]
	// Notch cutout corner: [10, 10]
	// Branch 2: [10, 30] -> [0, 30]
	const lShape = [
		[0, 0],
		[30, 0],
		[30, 10],
		[10, 10],
		[10, 30],
		[0, 30],
	];

	// Line 1: fully inside the bottom branch of L
	const insideLine = new m.AcDbLine(new m.AcGePoint3d(2, 2, 0), new m.AcGePoint3d(8, 2, 0));
	insideLine.layer = 'DRAFT';

	// Line 2: fully inside the L's notch cutout (outside the polygon, in [10, 30] x [10, 30])
	const notchLine = new m.AcDbLine(new m.AcGePoint3d(15, 15, 0), new m.AcGePoint3d(25, 25, 0));
	notchLine.layer = 'DRAFT';

	// Line 3: crosses the lasso edge (from inside [5, 5] across x=10 to [15, 5])
	const crossLine = new m.AcDbLine(new m.AcGePoint3d(5, 5, 0), new m.AcGePoint3d(15, 5, 0));
	crossLine.layer = 'DRAFT';

	// Line 4: crossed by an open fence path
	const fenceLine = new m.AcDbLine(new m.AcGePoint3d(15, 5, 0), new m.AcGePoint3d(25, 5, 0));
	fenceLine.layer = 'DRAFT';

	db.tables.blockTable.modelSpace.appendEntity([insideLine, notchLine, crossLine, fenceLine]);

	const insideId = String(insideLine.objectId);
	const notchId = String(notchLine.objectId);
	const crossId = String(crossLine.objectId);
	const fenceLineId = String(fenceLine.objectId);

	// 1. Window lasso selection: concave L-shape
	const winHits = m.pickDraftingPolygon(db, lShape, 'window');
	assert.ok(winHits.includes(insideId), 'Line fully inside the L must be selected by window');
	assert.ok(!winHits.includes(notchId), 'Line inside the L notch must NOT be selected by window');

	// 2. Crossing lasso selection: touches crossLine
	const crossHits = m.pickDraftingPolygon(db, lShape, 'crossing');
	assert.ok(crossHits.includes(insideId), 'Inside line is also selected by crossing');
	assert.ok(crossHits.includes(crossId), 'Line crossing the lasso edge must be selected by crossing');
	assert.ok(!crossHits.includes(notchId), 'Line inside the notch is not touched by crossing lasso');

	// 3. Fence lasso selection: open path [ [20, -5], [20, 15] ] crosses fenceLine (at [20, 5])
	const fencePath = [
		[20, -5],
		[20, 15],
	];
	const fenceHits = m.pickDraftingPolygon(db, fencePath, 'fence');
	assert.ok(fenceHits.includes(fenceLineId), 'Line crossed by open fence path must be selected');
	assert.ok(!fenceHits.includes(insideId), 'Line not crossed by fence path must not be selected');
	assert.ok(!fenceHits.includes(notchId), 'Line not crossed by fence path must not be selected');
});

test('pickDraftingAll at a point where a circle and a line overlap returns both, nearest first (verified by computing)', async () => {
	const m = await load();
	const db = new m.AcDbDatabase();
	m.acdbHostApplicationServices().workingDatabase = db;

	// Circle at center [50, 50] with radius 10
	const circle = new m.AcDbCircle(new m.AcGePoint3d(50, 50, 0), 10);
	circle.layer = 'GEOM';

	// Line from [40, 50] to [60, 50] along y = 50
	const line = new m.AcDbLine(new m.AcGePoint3d(40, 50, 0), new m.AcGePoint3d(60, 50, 0));
	line.layer = 'DRAFT';

	db.tables.blockTable.modelSpace.appendEntity([circle, line]);

	const circleId = String(circle.objectId);
	const lineId = String(line.objectId);

	// Computation Check A: Pick point at [50, 52] with tolerance 10
	// Distance to line (y = 50): |52 - 50| = 2.0
	// Distance to circle (center [50, 50], r = 10): |hypot(0, 2) - 10| = |2 - 10| = 8.0
	// Since 2.0 < 8.0, Line is nearer than Circle.
	const hitsA = m.pickDraftingAll(db, [50, 52], 10);
	assert.equal(hitsA.length, 2, 'Both overlapping entities must be returned');
	assert.equal(hitsA[0].id, lineId, 'Line must be first (distance = 2.0 vs circle distance = 8.0)');
	assert.equal(hitsA[1].id, circleId, 'Circle must be second');
	assert.ok(Math.abs(hitsA[0].distance - 2.0) < 1e-6);
	assert.ok(Math.abs(hitsA[1].distance - 8.0) < 1e-6);

	// Computation Check B: Pick point at [50, 59] with tolerance 10
	// Distance to line (y = 50): |59 - 50| = 9.0
	// Distance to circle (center [50, 50], r = 10): |hypot(0, 9) - 10| = |9 - 10| = 1.0
	// Since 1.0 < 9.0, Circle is nearer than Line.
	const hitsB = m.pickDraftingAll(db, [50, 59], 10);
	assert.equal(hitsB.length, 2, 'Both overlapping entities must be returned');
	assert.equal(hitsB[0].id, circleId, 'Circle must be first (distance = 1.0 vs line distance = 9.0)');
	assert.equal(hitsB[1].id, lineId, 'Line must be second');
	assert.ok(Math.abs(hitsB[0].distance - 1.0) < 1e-6);
	assert.ok(Math.abs(hitsB[1].distance - 9.0) < 1e-6);
});
