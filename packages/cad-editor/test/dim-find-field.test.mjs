/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-dim-find-field-')), 'bundle.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
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

test('DIMSPACE with spacing 10 on three horizontal dims at y=10, 13, 40 from base y=10 -> y=10, 20, 30', async () => {
	const { AcDbRotatedDimension, AcGePoint3d, spaceDimensions } = await load();

	const baseDim = new AcDbRotatedDimension(
		new AcGePoint3d(0, 0, 0),
		new AcGePoint3d(100, 0, 0),
		new AcGePoint3d(50, 10, 0),
	);
	baseDim.rotation = 0;

	const dim2 = new AcDbRotatedDimension(
		new AcGePoint3d(0, 0, 0),
		new AcGePoint3d(100, 0, 0),
		new AcGePoint3d(50, 13, 0),
	);
	dim2.rotation = 0;

	const dim3 = new AcDbRotatedDimension(
		new AcGePoint3d(0, 0, 0),
		new AcGePoint3d(100, 0, 0),
		new AcGePoint3d(50, 40, 0),
	);
	dim3.rotation = 0;

	spaceDimensions(baseDim, [dim2, dim3], 10);

	assert.equal(baseDim.dimLinePoint.y, 10);
	assert.equal(dim2.dimLinePoint.y, 20);
	assert.equal(dim3.dimLinePoint.y, 30);
});

test('DIMTEDIT Angle 30° -> text rotation π/6', async () => {
	const { AcDbRotatedDimension, AcGePoint3d } = await load();

	const dim = new AcDbRotatedDimension(
		new AcGePoint3d(0, 0, 0),
		new AcGePoint3d(100, 0, 0),
		new AcGePoint3d(50, 20, 0),
	);

	const angleDeg = 30;
	dim.textRotation = (angleDeg * Math.PI) / 180;

	assert.ok(Math.abs(dim.textRotation - Math.PI / 6) < 1e-6);
});

test('DIMOVERRIDE DIMTXT 5 round trips through DXF', async () => {
	const {
		AcDbDatabase,
		AcDbFileType,
		AcDbRotatedDimension,
		AcGePoint3d,
		applyDimOverride,
		getDimOverrides,
	} = await load();

	const db = new AcDbDatabase();
	const dim = new AcDbRotatedDimension(
		new AcGePoint3d(0, 0, 0),
		new AcGePoint3d(100, 0, 0),
		new AcGePoint3d(50, 20, 0),
	);
	db.tables.blockTable.modelSpace.appendEntity(dim);

	applyDimOverride(db, dim, 'DIMTXT', 5);

	const dxf = db.dxfOut();
	assert.ok(dxf.includes('DSTYLE'));

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	const readDim = db2.tables.blockTable.modelSpace.newIterator().next().value;
	assert.ok(readDim);

	const overrides = getDimOverrides(readDim);
	assert.equal(overrides.DIMTXT, 5);
});

test('ARRAY rectangular 2x3 then ARRAYEDIT columns 4 -> 8 items and the group round trips through DXF', async () => {
	const {
		AcDbDatabase,
		AcDbFileType,
		AcDbLine,
		AcGePoint3d,
		createRectangularArray,
		updateRectangularArray,
	} = await load();

	const db = new AcDbDatabase();
	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	db.tables.blockTable.modelSpace.appendEntity(line);

	const { group, def } = createRectangularArray(db, [line], 2, 3, 50, 100);
	assert.equal(group.entityIds.length, 6);

	const { group: updatedGroup, totalCount } = updateRectangularArray(db, def, { columns: 4 });
	assert.equal(totalCount, 8);
	assert.equal(updatedGroup.entityIds.length, 8);

	const dxf = db.dxfOut();
	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);

	const groupInDb2 = db2.objects?.group?.getAt(def.groupName);
	assert.ok(groupInDb2);
	assert.equal(groupInDb2.entityIds.length, 8);
});

test("FIND 'BEAM' Whole words + Match case in TEXT 'BEAM B1', 'beam b2', 'BEAMS' -> 1 match", async () => {
	const { AcDbDatabase, AcDbText, findTextInDatabase } = await load();

	const db = new AcDbDatabase();
	const t1 = new AcDbText();
	t1.textString = 'BEAM B1';
	db.tables.blockTable.modelSpace.appendEntity(t1);

	const t2 = new AcDbText();
	t2.textString = 'beam b2';
	db.tables.blockTable.modelSpace.appendEntity(t2);

	const t3 = new AcDbText();
	t3.textString = 'BEAMS';
	db.tables.blockTable.modelSpace.appendEntity(t3);

	const result = findTextInDatabase(db, 'BEAM', { wholeWord: true, matchCase: true });
	assert.equal(result.totalCount, 1);
	assert.equal(result.matches[0].fullText, 'BEAM B1');
});

test("Replace 'B1' -> 'B10' in MTEXT '{\\fArial|b1;B1} span' keeps the formatting code", async () => {
	const { AcDbDatabase, AcDbMText, replaceTextInDatabase, replaceInMText, buildSearchRegex } = await load();

	const raw = '{\\fArial|b1;B1} span';
	const regex = buildSearchRegex('B1', { matchCase: true });
	const pureRes = replaceInMText(raw, regex, 'B10');
	assert.equal(pureRes.newContents, '{\\fArial|b1;B10} span');

	const db = new AcDbDatabase();
	const mtext = new AcDbMText();
	mtext.contents = raw;
	db.tables.blockTable.modelSpace.appendEntity(mtext);

	const res = replaceTextInDatabase(db, 'B1', 'B10', { matchCase: true });
	assert.equal(res.replacedOccurrences, 1);
	assert.equal(mtext.contents, '{\\fArial|b1;B10} span');
});

test('field Area of a 100x50 closed polyline with %lu2%pr2 -> 5000.00', async () => {
	const { AcDbPolyline, AcGePoint2d, evaluateField } = await load();

	const pline = new AcDbPolyline(4);
	pline.addVertexAt(0, new AcGePoint2d(0, 0));
	pline.addVertexAt(1, new AcGePoint2d(100, 0));
	pline.addVertexAt(2, new AcGePoint2d(100, 50));
	pline.addVertexAt(3, new AcGePoint2d(0, 50));
	pline.closed = true;

	const fieldCode = '%<\\AcObjProp Object(%<\\_ObjId 42>%).Area \\f "%lu2%pr2">%';
	const result = evaluateField(fieldCode, {
		getEntityById: () => pline,
	});

	assert.equal(result, '5000.00');
});

test('field Date format dd-MMM-yyyy on 2026-11-19 -> 19-Nov-2026 (inject the date)', async () => {
	const { evaluateField } = await load();

	const injectedDate = new Date('2026-11-19T12:00:00Z');
	const fieldCode = '%<\\AcVar Date \\f "dd-MMM-yyyy">%';
	const result = evaluateField(fieldCode, {
		date: injectedDate,
	});

	assert.equal(result, '19-Nov-2026');
});
