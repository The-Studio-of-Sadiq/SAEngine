/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { mkdtemp } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-layers-test-')), 'layers.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/index.ts';
				export * from './src/layerCommands.ts';
				export * from './src/properties.ts';
				export * from './src/linetypes.ts';
				export * from './src/commands.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' }, plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('add layer A with ACI 1, setCurrent A -> new LINE added via database helper lands on A', async () => {
	const { AcDbDatabase, AcDbLine, AcGePoint3d, acdbHostApplicationServices, ensureLayer, setCurrentLayer } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	ensureLayer(db, 'A', { color: 1 });
	assert.equal(db.tables.layerTable.getAt('A')?.color.colorIndex, 1);

	setCurrentLayer(db, 'A');
	assert.equal(db.clayer, 'A');

	// Simulate database helper (database.add in commands.ts)
	const dbHelper = {
		add: entity => {
			const list = Array.isArray(entity) ? entity : [entity];
			const curLayer = db.clayer || '0';
			for (const e of list) {
				if (!e._layer || !e.layer) e.layer = curLayer;
			}
			db.tables.blockTable.modelSpace.appendEntity(list);
		},
	};

	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 10, 0));
	dbHelper.add(line);
	assert.equal(line.layer, 'A');
});

test('delete of current layer refused', async () => {
	const { AcDbDatabase, acdbHostApplicationServices, ensureLayer, setCurrentLayer, deleteLayer } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	ensureLayer(db, 'MY_CURRENT_LAYER');
	setCurrentLayer(db, 'MY_CURRENT_LAYER');

	assert.throws(() => {
		deleteLayer(db, 'MY_CURRENT_LAYER', new Set());
	}, /Cannot delete protected layer/);
});

test('rename of layer 0 refused', async () => {
	const { AcDbDatabase, acdbHostApplicationServices, setLayer } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	assert.throws(() => {
		setLayer(db, '0', { name: 'RENAMED_ZERO' }, new Set());
	}, /Cannot rename protected layer/);
});

test('LAYMRG A->B moves entities and deletes A', async () => {
	const { AcDbDatabase, AcDbLine, AcGePoint3d, acdbHostApplicationServices, ensureLayer, mergeLayers } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	ensureLayer(db, 'LAYER_A');
	ensureLayer(db, 'LAYER_B');

	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	line.layer = 'LAYER_A';
	db.tables.blockTable.modelSpace.appendEntity(line);
	assert.equal(line.layer, 'LAYER_A');
	assert.equal(db.tables.layerTable.has('LAYER_A'), true);

	mergeLayers(db, 'LAYER_A', 'LAYER_B', new Set());

	assert.equal(line.layer, 'LAYER_B');
	assert.equal(db.tables.layerTable.has('LAYER_A'), false);
	assert.equal(db.tables.layerTable.has('LAYER_B'), true);
});

test('MATCHPROP copies colour/layer/linetype from source to destination', async () => {
	const {
		AcDbDatabase, AcDbLine, AcGePoint3d, AcCmColor, AcCmColorMethod,
		acdbHostApplicationServices, copyProperties,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const src = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(1, 1, 0));
	src.layer = 'SOURCE_LAYER';
	src.color = new AcCmColor(AcCmColorMethod.ByACI, 3);
	src.lineType = 'DASHED';
	src.lineWeight = 25;
	src.linetypeScale = 2.0;

	const dst = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(2, 2, 0));
	dst.layer = '0';
	dst.color = new AcCmColor(AcCmColorMethod.ByLayer, 256);
	dst.lineType = 'Continuous';

	copyProperties(src, dst);

	assert.equal(dst.layer, 'SOURCE_LAYER');
	assert.equal(dst.color.colorIndex, 3);
	assert.equal(dst.lineType, 'DASHED');
	assert.equal(dst.lineWeight, 25);
	assert.equal(dst.linetypeScale, 2.0);
});

test("properties.get on two lines with different colours -> color 'varies', same layer -> that layer", async () => {
	const {
		AcDbDatabase, AcDbLine, AcGePoint3d, AcCmColor, AcCmColorMethod,
		acdbHostApplicationServices, getProperties,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const line1 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	line1.layer = 'SHARED_LAYER';
	line1.color = new AcCmColor(AcCmColorMethod.ByACI, 1);
	db.tables.blockTable.modelSpace.appendEntity(line1);

	const line2 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 10, 0));
	line2.layer = 'SHARED_LAYER';
	line2.color = new AcCmColor(AcCmColorMethod.ByACI, 2);
	db.tables.blockTable.modelSpace.appendEntity(line2);

	const props = getProperties(db, [String(line1.objectId), String(line2.objectId)]);
	assert.equal(props.color, 'varies');
	assert.equal(props.layer, 'SHARED_LAYER');
});

test('DASHED pattern in acadiso.lin (mm) = dash 12.7, gap -6.35, total 19.05', async () => {
	const { ACADISO_LINETYPES, createLinetypeRecord } = await load();
	const def = ACADISO_LINETYPES.DASHED;
	assert(def, 'DASHED definition must exist in ACADISO_LINETYPES');
	assert.equal(def.pattern[0], 12.7, 'DASHED dash element must be 12.7 mm');
	assert.equal(def.pattern[1], -6.35, 'DASHED gap element must be -6.35 mm');
	const computedTotal = Math.round((Math.abs(def.pattern[0]) + Math.abs(def.pattern[1])) * 100) / 100;
	assert.equal(computedTotal, 19.05, 'Computed total pattern length must be 19.05 mm');
	assert.equal(def.totalPatternLength, 19.05, 'Definition totalPatternLength must be 19.05 mm');

	const record = createLinetypeRecord('DASHED');
	assert(record, 'createLinetypeRecord should create record for DASHED');
	assert.equal(record.name, 'DASHED');
	assert.equal(record.patternLength, 19.05);
});

test('DXF round trip keeps layer colour, linetype, lineweight, frozen/locked flags', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbLayerTableRecord, AcCmColor, AcCmColorMethod,
		AcGiLineWeight, acdbHostApplicationServices,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const rec = new AcDbLayerTableRecord({
		name: 'ROUNDTRIP_LAYER',
		color: new AcCmColor(AcCmColorMethod.ByACI, 1),
		linetype: 'DASHED',
		lineWeight: AcGiLineWeight.LineWeight030,
		isOff: false,
		isPlottable: true,
		standardFlags: 0x01 | 0x04,
	});
	rec.isFrozen = true;
	rec.isLocked = true;
	db.tables.layerTable.add(rec);

	db.version = 'AC1032'; // AutoCAD 2018 format
	const dxf = db.dxfOut(undefined, 6, 'AC1032');
	const text = typeof dxf === 'string' ? dxf : new TextDecoder().decode(dxf);

	const db2 = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db2;
	await db2.read(text, { readOnly: false }, AcDbFileType.DXF);

	const layer2 = db2.tables.layerTable.getAt('ROUNDTRIP_LAYER');
	assert(layer2, 'Layer must exist after DXF round trip');
	assert.equal(layer2.color.colorIndex, 1, 'Color index must survive round trip');
	assert.equal(layer2.linetype, 'DASHED', 'Linetype must survive round trip');
	assert.equal(layer2.lineWeight, AcGiLineWeight.LineWeight030, 'Lineweight must survive round trip');
	assert.equal(layer2.isFrozen, true, 'isFrozen flag must survive round trip');
	assert.equal(layer2.isLocked, true, 'isLocked flag must survive round trip');
});

test('properties.get and properties.set for line geometry in place', async () => {
	const {
		AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, getProperties, setProperties,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const line = new AcDbLine(new AcGePoint3d(10, 20, 0), new AcGePoint3d(50, 20, 0));
	line.layer = '0';
	db.tables.blockTable.modelSpace.appendEntity(line);
	const id = String(line.objectId);

	const initial = getProperties(db, [id]);
	assert.equal(initial.primaryType, 'Line');
	assert.equal(initial.startX, 10);
	assert.equal(initial.startY, 20);
	assert.equal(initial.endX, 50);
	assert.equal(initial.endY, 20);
	assert.equal(initial.length, 40);

	// Modify start and end points in place
	setProperties(db, [id], { startX: 15, endY: 60 });
	assert.equal(String(line.objectId), id, 'Entity ID must not change');
	assert.equal(line.startPoint.x, 15);
	assert.equal(line.startPoint.y, 20);
	assert.equal(line.endPoint.x, 50);
	assert.equal(line.endPoint.y, 60);

	const updated = getProperties(db, [id]);
	assert.equal(updated.startX, 15);
	assert.equal(updated.endY, 60);
});

test('properties.get and properties.set for polyline, circle and text in place', async () => {
	const {
		AcDbDatabase, AcDbCircle, AcDbPolyline, AcDbText, AcGePoint2d, AcGePoint3d,
		acdbHostApplicationServices, getProperties, setProperties,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	// Circle
	const circle = new AcDbCircle(new AcGePoint3d(100, 100, 0), 25);
	db.tables.blockTable.modelSpace.appendEntity(circle);
	const circleId = String(circle.objectId);

	const circleProps = getProperties(db, [circleId]);
	assert.equal(circleProps.primaryType, 'Circle');
	assert.equal(circleProps.radius, 25);
	assert.equal(circleProps.center[0], 100);
	assert.equal(circleProps.center[1], 100);
	assert(Math.abs(circleProps.circumference - 2 * Math.PI * 25) < 1e-4);

	setProperties(db, [circleId], { centerX: 150, radius: 30 });
	assert.equal(circle.center.x, 150);
	assert.equal(circle.radius, 30);

	// Polyline
	const poly = new AcDbPolyline();
	poly.addVertexAt(0, new AcGePoint2d(0, 0));
	poly.addVertexAt(1, new AcGePoint2d(10, 0));
	poly.addVertexAt(2, new AcGePoint2d(10, 10));
	poly.closed = false;
	db.tables.blockTable.modelSpace.appendEntity(poly);
	const polyId = String(poly.objectId);

	const polyProps = getProperties(db, [polyId]);
	assert.equal(polyProps.primaryType, 'Polyline');
	assert.equal(polyProps.closed, false);
	assert.equal(polyProps.vertices.length, 3);

	setProperties(db, [polyId], { closed: true, globalWidth: 2.5 });
	assert.equal(poly.closed, true);
	assert.equal(String(poly.objectId), polyId);

	const updatedPolyProps = getProperties(db, [polyId]);
	assert.equal(updatedPolyProps.closed, true);
	assert.equal(updatedPolyProps.globalWidth, 2.5);

	// Text
	const text = new AcDbText();
	text.textString = 'Sample Note';
	text.height = 3.5;
	text.rotation = 0;
	db.tables.blockTable.modelSpace.appendEntity(text);
	const textId = String(text.objectId);

	const textProps = getProperties(db, [textId]);
	assert.equal(textProps.primaryType, 'Text');
	assert.equal(textProps.text, 'Sample Note');
	assert.equal(textProps.textHeight, 3.5);

	setProperties(db, [textId], { text: 'Updated Note', textHeight: 5.0 });
	assert.equal(text.textString, 'Updated Note');
	assert.equal(text.height, 5.0);

	// Mixed selection summary
	const mixed = getProperties(db, [circleId, polyId, textId]);
	assert.equal(mixed.primaryType, 'Mixed');
	assert.equal(mixed.totalCount, 3);
	assert.equal(mixed.types.length, 3);
});

