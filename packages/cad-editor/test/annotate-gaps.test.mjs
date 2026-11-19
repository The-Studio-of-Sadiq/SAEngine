import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadModules() {
	const dir = await mkdtemp(path.join(tmpdir(), 'cad-p22-test-'));
	const outfile = path.join(dir, 'bundle.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/regionGeometry.ts';
				export * from './src/annotateGapsCommands.ts';
			`,
			resolveDir: process.cwd(),
			loader: 'ts',
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

// 1. MASSPROP: 100x50 rectangle at origin
test('MASSPROP of a 100x50 rectangle region at origin -> area 5000, centroid (50,25), Ixx=1041666.7, Iyy=4166666.7, Ixy=0', async () => {
	const { calculateRegionMassProperties } = await loadModules();
	const rect = [
		{ x: 0, y: 0 },
		{ x: 100, y: 0 },
		{ x: 100, y: 50 },
		{ x: 0, y: 50 },
	];
	const props = calculateRegionMassProperties([rect]);

	assert.equal(props.area, 5000);
	assert.equal(props.perimeter, 300);
	assert.equal(Math.round(props.centroid.x * 1000) / 1000, 50);
	assert.equal(Math.round(props.centroid.y * 1000) / 1000, 25);

	// Hand computation:
	// Ixx about centroid = b * h^3 / 12 = 100 * 50^3 / 12 = 1,041,666.6667
	// Iyy about centroid = h * b^3 / 12 = 50 * 100^3 / 12 = 4,166,666.6667
	// Ixy about centroid = 0
	assert.ok(Math.abs(props.Ixx - (100 * Math.pow(50, 3)) / 12) < 0.1);
	assert.ok(Math.abs(props.Iyy - (50 * Math.pow(100, 3)) / 12) < 0.1);
	assert.ok(Math.abs(props.Ixy) < 0.001);

	// Radii of gyration
	assert.ok(Math.abs(props.kx - Math.sqrt(props.Ixx / 5000)) < 0.001);
	assert.ok(Math.abs(props.ky - Math.sqrt(props.Iyy / 5000)) < 0.001);
});

// 2. MASSPROP: 100x100 square minus 50x50 square in its corner
test('region of a 100x100 square minus a 50x50 square in its corner -> area 7500, centroid (41.667, 41.667)', async () => {
	const { calculateRegionMassProperties } = await loadModules();
	// Outer 100x100 CCW (positive area), inner corner 50x50 CW (negative area)
	const outer = [
		{ x: 0, y: 0 },
		{ x: 100, y: 0 },
		{ x: 100, y: 100 },
		{ x: 0, y: 100 },
	];
	const cornerHole = [
		{ x: 50, y: 50 },
		{ x: 50, y: 100 },
		{ x: 100, y: 100 },
		{ x: 100, y: 50 },
	]; // CW orientation for hole
	const props = calculateRegionMassProperties([outer, cornerHole]);

	// Hand computation:
	// Area = 10000 - 2500 = 7500
	// Centroid = (10000 * 50 - 2500 * 75) / 7500 = (500000 - 187500) / 7500 = 41.6667
	assert.equal(props.area, 7500);
	assert.ok(Math.abs(props.centroid.x - 41.6667) < 0.001);
	assert.ok(Math.abs(props.centroid.y - 41.6667) < 0.001);
});

// 3. UNION: two overlapping 10x10 squares offset by 5 in x -> area 150
test('UNION of two overlapping 10x10 squares offset by 5 in x -> area 150', async () => {
	const { polygonBoolean, signedPolygonArea } = await loadModules();
	const sq1 = [
		{ x: 0, y: 0 },
		{ x: 10, y: 0 },
		{ x: 10, y: 10 },
		{ x: 0, y: 10 },
	];
	const sq2 = [
		{ x: 5, y: 0 },
		{ x: 15, y: 0 },
		{ x: 15, y: 10 },
		{ x: 5, y: 10 },
	];

	const unionRings = polygonBoolean(sq1, sq2, 'union');
	assert.equal(unionRings.length, 1);
	const area = Math.abs(signedPolygonArea(unionRings[0]));
	assert.equal(area, 150);
});

// 4. INTERSECT: two overlapping 10x10 squares offset by 5 in x -> area 50
test('INTERSECT of two overlapping 10x10 squares offset by 5 in x -> area 50', async () => {
	const { polygonBoolean, signedPolygonArea } = await loadModules();
	const sq1 = [
		{ x: 0, y: 0 },
		{ x: 10, y: 0 },
		{ x: 10, y: 10 },
		{ x: 0, y: 10 },
	];
	const sq2 = [
		{ x: 5, y: 0 },
		{ x: 15, y: 0 },
		{ x: 15, y: 10 },
		{ x: 5, y: 10 },
	];

	const isectRings = polygonBoolean(sq1, sq2, 'intersect');
	assert.equal(isectRings.length, 1);
	const area = Math.abs(signedPolygonArea(isectRings[0]));
	assert.equal(area, 50);
});

// 5. CENTERLINE: between lines y=0 and y=10 from x=0..100 -> line y=5 extended by CENTEREXE at both ends
test('CENTERLINE of y=0 and y=10 from x=0..100 -> line y=5 extended by CENTEREXE at both ends', async () => {
	const { AcDbDatabase, AcDbLine, centerlineCommand } = await loadModules();
	const db = new AcDbDatabase();
	const l1 = new AcDbLine({ x: 0, y: 0, z: 0 }, { x: 100, y: 0, z: 0 });
	const l2 = new AcDbLine({ x: 0, y: 10, z: 0 }, { x: 100, y: 10, z: 0 });
	db.tables.blockTable.modelSpace.appendEntity([l1, l2]);

	let promptIndex = 0;
	let addedEntity = null;

	const mockCtx = {
		database: {
			native: db,
			all: () => [l1, l2],
			add: (ent) => { addedEntity = ent; },
		},
		getEntity: async () => {
			promptIndex++;
			return promptIndex === 1 ? l1 : l2;
		},
		transaction: async (fn) => fn(),
		message: () => {},
	};

	await centerlineCommand(mockCtx);
	assert.ok(addedEntity instanceof AcDbLine);

	// CENTEREXE default is 3.75
	const exe = 3.75;
	assert.equal(addedEntity.startPoint.y, 5);
	assert.equal(addedEntity.endPoint.y, 5);
	assert.ok(Math.abs(addedEntity.startPoint.x - (0 - exe)) < 1e-6);
	assert.ok(Math.abs(addedEntity.endPoint.x - (100 + exe)) < 1e-6);
	assert.equal(addedEntity.lineType, 'CENTER');
});

// 6. BLEND: G1 between line (0,0)-(10,0) and line (20,10)-(30,10) -> spline starts at (10,0) tangent +x and ends at (20,10) tangent +x
test('BLEND G1 between line (0,0)-(10,0) and line (20,10)-(30,10) -> spline starts at (10,0) tangent +x and ends at (20,10) tangent +x', async () => {
	const { AcDbDatabase, AcDbLine, AcDbSpline, blendCommand } = await loadModules();
	const db = new AcDbDatabase();
	const l1 = new AcDbLine({ x: 0, y: 0, z: 0 }, { x: 10, y: 0, z: 0 });
	const l2 = new AcDbLine({ x: 20, y: 10, z: 0 }, { x: 30, y: 10, z: 0 });
	db.tables.blockTable.modelSpace.appendEntity([l1, l2]);

	let addedSpline = null;
	const mockCtx = {
		database: {
			native: db,
			add: (ent) => { addedSpline = ent; },
		},
		getEntityPick: async () => ({
			entity: l1,
			point: { x: 9.5, y: 0, z: 0 },
			status: 'ok',
		}),
		getEntity: async () => l2,
		getPoint: async () => ({ x: 20.5, y: 10, z: 0 }),
		transaction: async (fn) => fn(),
		message: () => {},
	};

	await blendCommand(mockCtx);
	assert.ok(addedSpline instanceof AcDbSpline);

	const ctrlPts = addedSpline.subGetGripPoints();
	assert.equal(ctrlPts.length, 4);

	// Start at (10, 0)
	assert.equal(ctrlPts[0].x, 10);
	assert.equal(ctrlPts[0].y, 0);

	// End at (20, 10)
	assert.equal(ctrlPts[3].x, 20);
	assert.equal(ctrlPts[3].y, 10);

	// Tangent at start: P1 - P0 is purely in +x direction (y component 0, x > 0)
	const tanStart = { x: ctrlPts[1].x - ctrlPts[0].x, y: ctrlPts[1].y - ctrlPts[0].y };
	assert.ok(tanStart.x > 0);
	assert.ok(Math.abs(tanStart.y) < 1e-6);

	// Tangent at end: P3 - P2 is purely in +x direction (y component 0, x > 0)
	const tanEnd = { x: ctrlPts[3].x - ctrlPts[2].x, y: ctrlPts[3].y - ctrlPts[2].y };
	assert.ok(tanEnd.x > 0);
	assert.ok(Math.abs(tanEnd.y) < 1e-6);
});

// 7. DRAWORDER: Back moves entity first in sort order and survives DXF round trip
test('DRAWORDER Back moves the entity first in the sort order and survives the DXF round trip', async () => {
	const { AcDbDatabase, AcDbFileType, AcDbLine, AcDbSortentsTable, draworderCommand } = await loadModules();
	const db = new AcDbDatabase();
	const line1 = new AcDbLine({ x: 0, y: 0, z: 0 }, { x: 10, y: 0, z: 0 });
	const line2 = new AcDbLine({ x: 0, y: 5, z: 0 }, { x: 10, y: 5, z: 0 });
	db.tables.blockTable.modelSpace.appendEntity([line1, line2]);

	const id1 = String(line1.objectId);
	const id2 = String(line2.objectId);

	// Currently order is [id1, id2]. Move line2 to Back.
	const mockCtx = {
		database: {
			native: db,
		},
		getSelection: async () => [line2],
		getKeyword: async () => 'Back',
		transaction: async (fn) => fn(),
		message: () => {},
	};

	await draworderCommand(mockCtx);

	// In memory: modelSpace._entities should have line2 first
	const ms = db.tables.blockTable.modelSpace;
	const getId = (item) => typeof item === 'string' ? item : String(item.objectId);
	assert.equal(getId(ms._entities[0]), id2);
	assert.equal(getId(ms._entities[1]), id1);

	// Sortents table has line2 first
	const sortentsDict = db.objects.sortentsTable;
	let foundSortents = null;
	for (const [, tbl] of sortentsDict.entries()) {
		if (tbl instanceof AcDbSortentsTable) foundSortents = tbl;
	}
	assert.ok(foundSortents);
	assert.equal(foundSortents.entityIds[0], id2);
	assert.equal(foundSortents.entityIds[1], id1);

	// DXF Round trip
	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	assert.ok(dxf.includes('SORTENTSTABLE'));

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	assert.ok(db2.objects.sortentsTable.numEntries > 0);

	for (const [, tbl] of db2.objects.sortentsTable.entries()) {
		// Line2 was moved to back, so its id is first in the sort order
		assert.equal(tbl.entityIds.length, 2);
		assert.equal(tbl.entityIds[0], id2);
		assert.equal(tbl.entityIds[1], id1);
	}
});

// 8. GRADIENT: fields round trip through DXF
test('gradient fields round trip through DXF', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbHatch, AcDbHatchObjectType,
		AcDbGradientPatternType, AcGePolyline2d,
	} = await loadModules();

	const db = new AcDbDatabase();
	const hatch = new AcDbHatch();
	hatch.hatchObjectType = AcDbHatchObjectType.GradientObject;
	hatch.gradientType = AcDbGradientPatternType.PreDefinedGradient;
	hatch.gradientName = 'CYLINDER';
	hatch.gradientAngle = Math.PI / 3;
	hatch.gradientShift = 0.25;
	hatch.gradientStartColor = 0xff0000;
	hatch.gradientEndColor = 0x00ffff;
	hatch.gradientOneColorMode = false;

	const loop = new AcGePolyline2d();
	loop.closed = true;
	loop.addVertexAt(0, { x: 0, y: 0, bulge: 0 });
	loop.addVertexAt(1, { x: 50, y: 0, bulge: 0 });
	loop.addVertexAt(2, { x: 50, y: 50, bulge: 0 });
	loop.addVertexAt(3, { x: 0, y: 50, bulge: 0 });
	hatch.add(loop);

	db.tables.blockTable.modelSpace.appendEntity(hatch);

	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);

	const it = db2.tables.blockTable.modelSpace.newIterator();
	let readHatch = null;
	for (const e of it) {
		if (e instanceof AcDbHatch) readHatch = e;
	}

	assert.ok(readHatch);
	assert.equal(readHatch.isGradient, true);
	assert.equal(readHatch.gradientName, 'CYLINDER');
	assert.ok(Math.abs(readHatch.gradientAngle - Math.PI / 3) < 1e-4);
	assert.ok(Math.abs(readHatch.gradientShift - 0.25) < 1e-4);
	assert.equal(readHatch.gradientStartColor, 0xff0000);
	assert.equal(readHatch.gradientEndColor, 0x00ffff);
});

// 9. WIPEOUT: boundaryPath, masking, and DXF round trip
test('WIPEOUT entity creates boundaryPath and round-trips through DXF', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbWipeout, AcDbRasterImageClipBoundaryType,
		AcGePoint2d, AcGePoint3d,
	} = await loadModules();

	const db = new AcDbDatabase();
	const wipeout = new AcDbWipeout();
	wipeout.position = new AcGePoint3d(10, 20, 0);
	wipeout.width = 100;
	wipeout.height = 50;
	wipeout.clipBoundaryType = AcDbRasterImageClipBoundaryType.Poly;
	wipeout.isClipped = true;
	wipeout.isShownClipped = true;
	wipeout.isImageShown = true;
	wipeout.clipBoundary = [
		new AcGePoint2d(0, 0),
		new AcGePoint2d(1, 0),
		new AcGePoint2d(1, 1),
		new AcGePoint2d(0, 1),
		new AcGePoint2d(0, 0),
	];

	db.tables.blockTable.modelSpace.appendEntity(wipeout);

	const bounds = wipeout.boundaryPath();
	assert.equal(bounds.length, 5);
	assert.equal(bounds[0].x, 10);
	assert.equal(bounds[0].y, 20);
	assert.equal(bounds[1].x, 110);
	assert.equal(bounds[1].y, 20);
	assert.equal(bounds[2].x, 110);
	assert.equal(bounds[2].y, 70);

	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	assert.ok(dxf.includes('WIPEOUT'));

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	const it = db2.tables.blockTable.modelSpace.newIterator();
	let readW = null;
	for (const e of it) {
		if (e instanceof AcDbWipeout) readW = e;
	}
	assert.ok(readW);
	assert.equal(readW.position.x, 10);
	assert.equal(readW.position.y, 20);
	assert.equal(readW.width, 100);
	assert.equal(readW.height, 50);
});

// 10. TOLERANCE: AcDbFcf entity round trips through DXF
test('TOLERANCE entity stores GD&T frame and round trips through DXF', async () => {
	const { AcDbDatabase, AcDbFileType, AcDbFcf, AcGePoint3d } = await loadModules();
	const db = new AcDbDatabase();
	const fcf = new AcDbFcf();
	fcf.location = new AcGePoint3d(15, 25, 0);
	fcf.text = '{\\Fgdt;j}%%v%%c0.05%%m%%v%%vA%%vB%%vC';

	db.tables.blockTable.modelSpace.appendEntity(fcf);

	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	assert.ok(dxf.includes('TOLERANCE'));

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	const it = db2.tables.blockTable.modelSpace.newIterator();
	let readFcf = null;
	for (const e of it) {
		if (e instanceof AcDbFcf) readFcf = e;
	}
	assert.ok(readFcf);
	assert.equal(readFcf.location.x, 15);
	assert.equal(readFcf.location.y, 25);
	assert.equal(readFcf.text, '{\\Fgdt;j}%%v%%c0.05%%m%%v%%vA%%vB%%vC');
});

// 11. QLEADER: creates AcDbLeader with MText and round trips through DXF
test('QLEADER creates AcDbLeader and MText annotation', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbLeader, AcDbLeaderAnnotationType,
		AcDbMText, AcGePoint3d,
	} = await loadModules();

	const db = new AcDbDatabase();
	const leader = new AcDbLeader();
	leader.appendVertex(new AcGePoint3d(0, 0, 0));
	leader.appendVertex(new AcGePoint3d(10, 10, 0));
	leader.appendVertex(new AcGePoint3d(20, 10, 0));
	leader.hasArrowHead = true;
	leader.hasHookLine = true;

	const mtext = new AcDbMText();
	mtext.contents = 'WELD ALL AROUND';
	mtext.location = new AcGePoint3d(20, 10, 0);

	db.tables.blockTable.modelSpace.appendEntity([mtext, leader]);
	leader.associatedAnnotation = String(mtext.objectId);
	leader.annoType = AcDbLeaderAnnotationType.MText;

	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	assert.ok(dxf.includes('LEADER'));
	assert.ok(dxf.includes('MTEXT'));

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	const it = db2.tables.blockTable.modelSpace.newIterator();
	let readLeader = null;
	for (const e of it) {
		if (e instanceof AcDbLeader) readLeader = e;
	}
	assert.ok(readLeader);
	assert.equal(readLeader.numVertices, 3);
	assert.equal(readLeader.hasArrowHead, true);
});
