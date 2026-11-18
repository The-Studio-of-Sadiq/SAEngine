import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function loadGeom() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-drafting-geom-')), 'geom.mjs');
	await esbuild.build({
		stdin: {
			contents: await import('node:fs/promises').then(fs => fs.readFile('src/draftingAidsGeometry.ts', 'utf8')),
			sourcefile: 'draftingAidsGeometry.ts',
			loader: 'ts',
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('perpendicular foot from point (3,4) to line (0,0)-(10,0) -> (3,0)', async () => {
	const { perpendicularFoot } = await loadGeom();
	const foot = perpendicularFoot({ x: 3, y: 4 }, { x: 0, y: 0 }, { x: 10, y: 0 });
	assert.equal(Math.round(foot.x * 1000) / 1000, 3);
	assert.equal(Math.round(foot.y * 1000) / 1000, 0);
});

test('tangent points from (10,0) to circle r=5 at origin -> (2.5, ±4.330)', async () => {
	const { tangentPointsToCircle } = await loadGeom();
	const tangents = tangentPointsToCircle({ x: 10, y: 0 }, { x: 0, y: 0 }, 5);
	assert.equal(tangents.length, 2);
	// Both tangent points should have x = 2.5
	const x1 = Math.round(tangents[0].x * 1000) / 1000;
	const x2 = Math.round(tangents[1].x * 1000) / 1000;
	assert.equal(x1, 2.5);
	assert.equal(x2, 2.5);

	// y should be ±4.330
	const ys = tangents.map(t => Math.round(t.y * 1000) / 1000).sort((a, b) => a - b);
	assert.equal(ys[0], -4.330);
	assert.equal(ys[1], 4.330);
});

test('polar snap of a cursor at 47° with increment 45 -> 45°', async () => {
	const { polarSnapAngle } = await loadGeom();
	const angle = polarSnapAngle(47, 45);
	assert.equal(angle, 45);

	// Additional verification
	assert.equal(polarSnapAngle(92, 45), 90);
	assert.equal(polarSnapAngle(22, 45), 0);
	assert.equal(polarSnapAngle(25, 45), 45);
});

test('ortho constraint of (10,3) from base (0,0) -> (10,0)', async () => {
	const { orthoConstraint } = await loadGeom();
	const p = orthoConstraint({ x: 10, y: 3 }, { x: 0, y: 0 });
	assert.equal(p.x, 10);
	assert.equal(p.y, 0);

	// When |dy| > |dx|, vertical constraint
	const p2 = orthoConstraint({ x: 3, y: 10 }, { x: 0, y: 0 });
	assert.equal(p2.x, 0);
	assert.equal(p2.y, 10);
});

test('snap-to-grid of (12.4, 7.6) with unit 5 -> (10, 10)', async () => {
	const { snapToGrid } = await loadGeom();
	const p = snapToGrid({ x: 12.4, y: 7.6 }, 5);
	assert.equal(p.x, 10);
	assert.equal(p.y, 10);

	const p2 = snapToGrid({ x: 13, y: 18 }, [5, 10]);
	assert.equal(p2.x, 15);
	assert.equal(p2.y, 20);
});

test('geometric centre of a 4x2 rectangle at origin -> (2,1)', async () => {
	const { geometricCenter } = await loadGeom();
	const rect = [
		{ x: 0, y: 0 },
		{ x: 4, y: 0 },
		{ x: 4, y: 2 },
		{ x: 0, y: 2 },
	];
	const center = geometricCenter(rect);
	assert.equal(Math.round(center.x * 1000) / 1000, 2);
	assert.equal(Math.round(center.y * 1000) / 1000, 1);
});

import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadAids() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-drafting-aids-')), 'aids.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/draftingAidsGeometry.ts';
				export * from './src/draftingAids.ts';
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

test('OSNAP override keywords map to expected modes', async () => {
	const { OSNAP_MODE_BY_KEYWORD, OSNAP_OVERRIDE_KEYWORDS, AcDbOsnapMode } = await loadAids();

	assert.equal(OSNAP_MODE_BY_KEYWORD.END, AcDbOsnapMode.EndPoint);
	assert.equal(OSNAP_MODE_BY_KEYWORD.MID, AcDbOsnapMode.MidPoint);
	assert.equal(OSNAP_MODE_BY_KEYWORD.CEN, AcDbOsnapMode.Center);
	assert.equal(OSNAP_MODE_BY_KEYWORD.GCE, AcDbOsnapMode.Centroid);
	assert.equal(OSNAP_MODE_BY_KEYWORD.NOD, AcDbOsnapMode.Node);
	assert.equal(OSNAP_MODE_BY_KEYWORD.QUA, AcDbOsnapMode.Quadrant);
	assert.equal(OSNAP_MODE_BY_KEYWORD.INT, AcDbOsnapMode.Intersection);
	assert.equal(OSNAP_MODE_BY_KEYWORD.INS, AcDbOsnapMode.Insertion);
	assert.equal(OSNAP_MODE_BY_KEYWORD.PER, AcDbOsnapMode.Perpendicular);
	assert.equal(OSNAP_MODE_BY_KEYWORD.TAN, AcDbOsnapMode.Tangent);
	assert.equal(OSNAP_MODE_BY_KEYWORD.NEA, AcDbOsnapMode.Nearest);
	assert.equal(OSNAP_MODE_BY_KEYWORD.NON, 0);

	for (const kw of OSNAP_OVERRIDE_KEYWORDS) {
		assert.ok(kw in OSNAP_MODE_BY_KEYWORD, `Keyword ${kw} is in map`);
	}
});

test('patched entity subGetOsnapPoints computes perpendicular and tangent with base point', async () => {
	const {
		ensureDraftingGeometryPatched,
		AcDbLine, AcDbCircle, AcDbPolyline, AcDbOsnapMode, AcGePoint3d, AcGePoint2d,
	} = await loadAids();
	ensureDraftingGeometryPatched();

	// Line perpendicular
	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	const lineSnaps = [];
	line.subGetOsnapPoints(AcDbOsnapMode.Perpendicular, { x: 5, y: 0, z: 0 }, { x: 3, y: 4, z: 0 }, lineSnaps);
	assert.equal(lineSnaps.length, 1);
	assert.equal(Math.round(lineSnaps[0].x), 3);
	assert.equal(Math.round(lineSnaps[0].y), 0);

	// Circle tangent
	const circle = new AcDbCircle(new AcGePoint3d(0, 0, 0), 5);
	const circleSnaps = [];
	circle.subGetOsnapPoints(AcDbOsnapMode.Tangent, { x: 5, y: 0, z: 0 }, { x: 10, y: 0, z: 0 }, circleSnaps);
	assert.equal(circleSnaps.length, 2);
	assert.equal(Math.round(circleSnaps[0].x * 10) / 10, 2.5);
	assert.equal(Math.round(circleSnaps[1].x * 10) / 10, 2.5);

	// Polyline centroid (geometric centre)
	const poly = new AcDbPolyline();
	poly.addVertexAt(0, new AcGePoint2d(0, 0));
	poly.addVertexAt(1, new AcGePoint2d(4, 0));
	poly.addVertexAt(2, new AcGePoint2d(4, 2));
	poly.addVertexAt(3, new AcGePoint2d(0, 2));
	poly.closed = true;

	const polySnaps = [];
	poly.subGetOsnapPoints(AcDbOsnapMode.Centroid, { x: 2, y: 1, z: 0 }, undefined, polySnaps);
	assert.equal(polySnaps.length, 1);
	assert.equal(Math.round(polySnaps[0].x), 2);
	assert.equal(Math.round(polySnaps[0].y), 1);
});

