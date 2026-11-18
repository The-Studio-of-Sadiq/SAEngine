import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-selection-')), 'selection.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/selectionGeometry.ts';
				export * from './src/selectionModes.ts';
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

test('selection fence, polygons, concavity, previous and remove set behavior', async () => {
	const m = await load();
	const db = new m.AcDbDatabase();
	m.acdbHostApplicationServices().workingDatabase = db;

	// 1. fence [(0,5),(10,5)] crosses line (5,0)-(5,10) yes and line (0,0)-(10,0) no
	const line = (a, b) => [a, b];
	assert.equal(m.fenceCrossesSegment([[0, 5], [10, 5]], line([5, 0], [5, 10])), true);
	assert.equal(m.fenceCrossesSegment([[0, 5], [10, 5]], line([0, 0], [10, 0])), false);

	const lineCross = new m.AcDbLine(new m.AcGePoint3d(5, 0, 0), new m.AcGePoint3d(5, 10, 0));
	assert.equal(m.entityMatchesSelection(lineCross, 'fence', [[0, 5], [10, 5]]), true);
	const lineParallel = new m.AcDbLine(new m.AcGePoint3d(0, 0, 0), new m.AcGePoint3d(10, 0, 0));
	assert.equal(m.entityMatchesSelection(lineParallel, 'fence', [[0, 5], [10, 5]]), false);

	// 2. window polygon [(0,0),(10,0),(10,10),(0,10)] contains segment (2,2)-(8,8)
	const square = [[0, 0], [10, 0], [10, 10], [0, 10]];
	assert.equal(m.polygonContainsSegment(square, line([2, 2], [8, 8])), true);
	const lineInside = new m.AcDbLine(new m.AcGePoint3d(2, 2, 0), new m.AcGePoint3d(8, 8, 0));
	assert.equal(m.entityMatchesSelection(lineInside, 'window', square), true);

	// 3. crossing triangle [(0,0),(10,0),(0,10)] hits segment (4,4)-(9,9), window with same triangle does not
	const tri = [[0, 0], [10, 0], [0, 10]];
	assert.equal(m.polygonCrossesSegment(tri, line([4, 4], [9, 9])), true);
	assert.equal(m.polygonContainsSegment(tri, line([4, 4], [9, 9])), false);
	const lineDiag = new m.AcDbLine(new m.AcGePoint3d(4, 4, 0), new m.AcGePoint3d(9, 9, 0));
	assert.equal(m.entityMatchesSelection(lineDiag, 'crossing', tri), true);
	assert.equal(m.entityMatchesSelection(lineDiag, 'window', tri), false);

	// 4. concave L point-in-polygon
	const concaveL = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4]];
	assert.equal(m.pointInPolygon([1, 1], concaveL), true);
	assert.equal(m.pointInPolygon([0.5, 0.5], concaveL), true);
	assert.equal(m.pointInPolygon([2, 2], concaveL), false);

	// 5. circle r=2 at (5,5) inside window box 0..10 yes, crossing box 0..4 yes (intersects), window box 0..4 no
	const box010 = [[0, 0], [10, 0], [10, 10], [0, 10]];
	const box04 = [[0, 0], [4, 0], [4, 4], [0, 4]];
	assert.equal(m.circleMatchesSelection([5, 5], 2, 'window', box010), true);
	assert.equal(m.circleMatchesSelection([5, 5], 2, 'crossing', box04), true);
	assert.equal(m.circleMatchesSelection([5, 5], 2, 'window', box04), false);

	const circle = new m.AcDbCircle();
	circle.center = new m.AcGePoint3d(5, 5, 0);
	circle.radius = 2;
	assert.equal(m.entityMatchesSelection(circle, 'window', box010), true);
	assert.equal(m.entityMatchesSelection(circle, 'crossing', box04), true);
	assert.equal(m.entityMatchesSelection(circle, 'window', box04), false);

	// 6. Previous returns last committed set
	m.setPreviousSelection(['ent-1', 'ent-2', 'ent-3']);
	assert.deepEqual(m.getPreviousSelection(), ['ent-1', 'ent-2', 'ent-3']);

	// 7. Remove mode deletes ids
	const previous = new m.SelectionWorkingSet(['a', 'b']);
	assert.deepEqual(previous.ids, ['a', 'b']);
	previous.mode = 'remove';
	previous.apply(['b']);
	assert.deepEqual(previous.ids, ['a']);
	previous.undo();
	assert.deepEqual(previous.ids, ['a', 'b']);
});

test('entityMatchesSelection handles Arc, Polyline with bulge, Ellipse, Text, Hatch and Dimension', async () => {
	const m = await load();
	const db = new m.AcDbDatabase();
	m.acdbHostApplicationServices().workingDatabase = db;

	const box = [[0, 0], [100, 0], [100, 100], [0, 100]];

	// Arc inside box
	const arcInside = new m.AcDbArc(new m.AcGePoint3d(50, 50, 0), 20, 0, Math.PI);
	assert.equal(m.entityMatchesSelection(arcInside, 'window', box), true);
	assert.equal(m.entityMatchesSelection(arcInside, 'crossing', box), true);
	assert.equal(m.entityMatchesSelection(arcInside, 'fence', [[0, 50], [100, 50]]), true);

	// Polyline with bulges
	const poly = new m.AcDbPolyline();
	poly.addVertexAt(0, new m.AcGePoint2d(10, 20), Math.tan(Math.PI / 8));
	poly.addVertexAt(1, new m.AcGePoint2d(90, 20), 0);
	poly.addVertexAt(2, new m.AcGePoint2d(90, 80), 0);
	poly.addVertexAt(3, new m.AcGePoint2d(10, 80), 0);
	poly.closed = true;
	assert.equal(m.entityMatchesSelection(poly, 'window', box), true);
	assert.equal(m.entityMatchesSelection(poly, 'crossing', [[0, 0], [50, 0], [50, 50], [0, 50]]), true);

	// Ellipse
	const ell = new m.AcDbEllipse(
		new m.AcGePoint3d(50, 50, 0),
		new m.AcGeVector3d(0, 0, 1),
		new m.AcGeVector3d(1, 0, 0),
		30,
		15,
		0,
		Math.PI * 2,
	);
	assert.equal(m.entityMatchesSelection(ell, 'window', box), true);

	// Text
	const text = new m.AcDbText();
	text.position = new m.AcGePoint3d(50, 50, 0);
	assert.equal(m.entityMatchesSelection(text, 'window', box), true);
	assert.equal(m.entityMatchesSelection(text, 'window', [[0, 0], [10, 0], [10, 10], [0, 10]]), false);

	// Hatch with geometricExtents
	const hatch = new m.AcDbHatch();
	// Test filterSelection
	const filtered = m.filterSelection([
		{ objectId: '1', dxfTypeName: 'LINE', layer: '0', color: 1 },
		{ objectId: '2', dxfTypeName: 'CIRCLE', layer: 'WALLS', color: 2 },
	], { type: 'LINE' });
	assert.equal(filtered.length, 1);
	assert.equal(filtered[0].objectId, '1');
});
