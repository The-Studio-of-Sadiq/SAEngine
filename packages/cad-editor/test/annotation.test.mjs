import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadCadEditor() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-annotation-')), 'model.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/annotationGeometry.ts';
				export * from './src/annotationCommands.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' },
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('annotation placement helpers use expected rotated anchor and grid coordinates', async () => {
	const { justifiedTextAnchor, centerMarkSegments, tableGrid } = await loadCadEditor();
	const a = justifiedTextAnchor({ x: 0, y: 0, z: 0 }, 10, 2, 'center', 'middle', Math.PI / 2);
	assert.ok(Math.abs(a.x - 1) < 1e-9 && Math.abs(a.y + 5) < 1e-9); // rotate (-5,-1) by 90 degrees
	// AutoCAD cross of size 2.5: ±2.5 along each axis
	assert.deepEqual(centerMarkSegments({ x: 0, y: 0, z: 0 }, 2.5), [
		{ start: { x: -2.5, y: 0, z: 0 }, end: { x: 2.5, y: 0, z: 0 } },
		{ start: { x: 0, y: -2.5, z: 0 }, end: { x: 0, y: 2.5, z: 0 } },
	]);
	assert.deepEqual(tableGrid(3, 2, 10, 5, { x: 0, y: 0, z: 0 }), [
		{ start: { x: 0, y: 0, z: 0 }, end: { x: 10, y: 0, z: 0 } },
		{ start: { x: 0, y: -10, z: 0 }, end: { x: 10, y: -10, z: 0 } },
		{ start: { x: 0, y: -20, z: 0 }, end: { x: 10, y: -20, z: 0 } },
		{ start: { x: 0, y: -30, z: 0 }, end: { x: 10, y: -30, z: 0 } },
		{ start: { x: 0, y: 0, z: 0 }, end: { x: 0, y: -30, z: 0 } },
		{ start: { x: 5, y: 0, z: 0 }, end: { x: 5, y: -30, z: 0 } },
		{ start: { x: 10, y: 0, z: 0 }, end: { x: 10, y: -30, z: 0 } },
	]);
});

test('centerMark with negative DIMCEN generates cross ±size and extension segments to radius+size', async () => {
	const { centerMarkSegments } = await loadCadEditor();
	// Hand-computed AutoCAD exact geometry:
	// For circle center (0,0,0), radius r=100, DIMCEN=-2.5:
	// Size s = |-2.5| = 2.5.
	// Cross arms from center are ±s: [-2.5, 2.5].
	// Gap between cross and extension line is equal to size s = 2.5.
	// Extension lines start at s + gap = 2.5 + 2.5 = 5.0.
	// Extension lines extend beyond circle perimeter by s = 2.5, ending at r + s = 100 + 2.5 = 102.5.
	const segments = centerMarkSegments({ x: 0, y: 0, z: 0 }, -2.5, 100);
	assert.deepEqual(segments, [
		// Horizontal cross
		{ start: { x: -2.5, y: 0, z: 0 }, end: { x: 2.5, y: 0, z: 0 } },
		// Vertical cross
		{ start: { x: 0, y: -2.5, z: 0 }, end: { x: 0, y: 2.5, z: 0 } },
		// +X extension segment: 2.5+gap (5.0) to 100+2.5 (102.5)
		{ start: { x: 5, y: 0, z: 0 }, end: { x: 102.5, y: 0, z: 0 } },
		// -X extension segment: -(2.5+gap) (-5.0) to -(100+2.5) (-102.5)
		{ start: { x: -5, y: 0, z: 0 }, end: { x: -102.5, y: 0, z: 0 } },
		// +Y extension segment: 2.5+gap (5.0) to 100+2.5 (102.5)
		{ start: { x: 0, y: 5, z: 0 }, end: { x: 0, y: 102.5, z: 0 } },
		// -Y extension segment: -(2.5+gap) (-5.0) to -(100+2.5) (-102.5)
		{ start: { x: 0, y: -5, z: 0 }, end: { x: 0, y: -102.5, z: 0 } },
	]);
});

test('TEXT, MTEXT, style, and MLEADER survive DXF round trip', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbText, AcDbMText, AcDbMLeader,
		AcDbTextStyleTableRecord, AcGePoint3d, AcDbMLeaderContentType,
	} = await loadCadEditor();
	const db = new AcDbDatabase();
	db.ensureTextStyleDefaults();
	db.tables.textStyleTable.add(new AcDbTextStyleTableRecord({ name: 'P10', fileName: 'Arial', textSize: 0, xScale: 1, obliquingAngle: 0 }));
	const text = new AcDbText();
	text.textString = 'hello text';
	text.position = new AcGePoint3d(1, 2, 0);
	text.height = 2.5;
	text.styleName = 'P10';
	const mt = new AcDbMText();
	mt.contents = 'hello\\Pmultiline';
	mt.location = new AcGePoint3d(3, 4, 0);
	mt.height = 2.5;
	mt.styleName = 'P10';
	const ml = new AcDbMLeader();
	ml.contentType = AcDbMLeaderContentType.MTextContent;
	ml.addLeader({ leaderLines: [{ vertices: [new AcGePoint3d(0, 0, 0), new AcGePoint3d(2, 0, 0)] }] });
	ml.contents = 'leader text';
	ml.textLocation = new AcGePoint3d(2, 0, 0);
	ml.textStyleName = 'P10';
	db.tables.blockTable.modelSpace.appendEntity([text, mt, ml]);
	const out = db.dxfOut(undefined, 6);
	const dxf = typeof out === 'string' ? out : new TextDecoder().decode(out);
	const reopened = new AcDbDatabase();
	await reopened.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	const entities = reopened.tables.blockTable.modelSpace.newIterator().toArray();
	assert.equal(entities.find(e => e instanceof AcDbText)?.textString, 'hello text');
	assert.equal(entities.find(e => e instanceof AcDbMText)?.contents, 'hello\\Pmultiline');
	assert.ok(reopened.tables.textStyleTable.has('P10'));
	assert.equal(entities.find(e => e instanceof AcDbMLeader)?.contents, 'leader text');
});

test('TEXT/DTEXT prompt sequence places consecutive lines below with 1.5*H spacing', async () => {
	const { AcDbDatabase, AcDbText, textCommand } = await loadCadEditor();
	const db = new AcDbDatabase();
	db.ensureTextStyleDefaults();
	const addedEntities = [];

	const strings = ['First Line', 'Second Line', ''];
	let stringIndex = 0;
	const mockCtx = {
		database: {
			native: db,
			add(e) {
				if (Array.isArray(e)) addedEntities.push(...e);
				else addedEntities.push(e);
			},
		},
		async getPointPick(prompt, opts) {
			assert.equal(prompt, 'Specify start point of text or [Justify/Style]:');
			return { status: 'ok', point: { x: 10, y: 20, z: 0 } };
		},
		async getString(prompt, opts) {
			if (prompt.startsWith('Specify height')) {
				return '2.0';
			}
			if (prompt.startsWith('Specify rotation angle')) {
				return '0';
			}
			if (prompt === 'Enter text:') {
				return strings[stringIndex++] ?? '';
			}
			throw new Error(`Unexpected getString prompt: ${prompt}`);
		},
	};

	await textCommand(mockCtx);
	assert.equal(addedEntities.length, 2);
	const [line1, line2] = addedEntities;
	assert.ok(line1 instanceof AcDbText);
	assert.ok(line2 instanceof AcDbText);
	assert.equal(line1.textString, 'First Line');
	assert.equal(line1.position.x, 10);
	assert.equal(line1.position.y, 20);
	assert.equal(line1.height, 2.0);

	// Line 2 is spaced down by 1.5 * height = 1.5 * 2.0 = 3.0 below line 1: y = 20 - 3 = 17
	assert.equal(line2.textString, 'Second Line');
	assert.equal(line2.position.x, 10);
	assert.equal(line2.position.y, 17);
	assert.equal(line2.height, 2.0);
});

test('TEXT/DTEXT skips height prompt if style has a fixed height', async () => {
	const { AcDbDatabase, AcDbText, AcDbTextStyleTableRecord, textCommand } = await loadCadEditor();
	const db = new AcDbDatabase();
	db.ensureTextStyleDefaults();
	const fixedRec = new AcDbTextStyleTableRecord({ name: 'FixedHeight' });
	fixedRec.textSize = 3.5;
	db.tables.textStyleTable.add(fixedRec);
	db.textstyle = 'FixedHeight';

	const addedEntities = [];
	let heightPromptCalled = false;
	const strings = ['Fixed Height Text', ''];
	let stringIdx = 0;

	const mockCtx = {
		database: {
			native: db,
			add(e) { addedEntities.push(e); },
		},
		async getPointPick() {
			return { status: 'ok', point: { x: 0, y: 0, z: 0 } };
		},
		async getString(prompt) {
			if (prompt.startsWith('Specify height')) {
				heightPromptCalled = true;
				return '99';
			}
			if (prompt.startsWith('Specify rotation angle')) return '0';
			if (prompt === 'Enter text:') return strings[stringIdx++] ?? '';
			throw new Error(`Unexpected prompt: ${prompt}`);
		},
	};

	await textCommand(mockCtx);
	assert.equal(heightPromptCalled, false, 'Height prompt must be skipped when style has fixed height');
	assert.equal(addedEntities.length, 1);
	assert.equal(addedEntities[0].height, 3.5);
	assert.equal(addedEntities[0].styleName, 'FixedHeight');
});

test('TEXT/DTEXT Justify option sets alignment mode and alignment point', async () => {
	const { AcDbDatabase, AcDbTextHorizontalMode, AcDbTextVerticalMode, textCommand } = await loadCadEditor();
	const db = new AcDbDatabase();
	db.ensureTextStyleDefaults();
	const addedEntities = [];

	let pickStep = 0;
	const mockCtx = {
		database: {
			native: db,
			add(e) { addedEntities.push(e); },
		},
		async getPointPick() {
			if (pickStep === 0) {
				pickStep++;
				return { status: 'keyword', keyword: 'Justify' };
			}
			return { status: 'cancel' };
		},
		async getKeyword(prompt, kws) {
			assert.ok(kws.includes('MC'));
			assert.ok(kws.includes('TL'));
			assert.ok(kws.includes('Fit'));
			return 'MC';
		},
		async getPoint(prompt) {
			assert.equal(prompt, 'Specify justification point:');
			return { x: 50, y: 60, z: 0 };
		},
		async getString(prompt) {
			if (prompt.startsWith('Specify height')) return '2.5';
			if (prompt.startsWith('Specify rotation angle')) return '0';
			if (prompt === 'Enter text:') return 'Centered';
			throw new Error(`Unexpected prompt: ${prompt}`);
		},
	};

	let stringCalls = 0;
	mockCtx.getString = async (prompt) => {
		if (prompt.startsWith('Specify height')) return '2.5';
		if (prompt.startsWith('Specify rotation angle')) return '0';
		if (prompt === 'Enter text:') {
			stringCalls++;
			return stringCalls === 1 ? 'Centered' : '';
		}
		throw new Error(`Unexpected prompt: ${prompt}`);
	};

	await textCommand(mockCtx);
	assert.equal(addedEntities.length, 1);
	const t = addedEntities[0];
	assert.equal(t.horizontalMode, AcDbTextHorizontalMode.CENTER);
	assert.equal(t.verticalMode, AcDbTextVerticalMode.MIDDLE);
	assert.equal(t.alignmentPoint.x, 50);
	assert.equal(t.alignmentPoint.y, 60);
});

test('TEXT/DTEXT Style option validates style existence', async () => {
	const { AcDbDatabase, textCommand } = await loadCadEditor();
	const db = new AcDbDatabase();
	db.ensureTextStyleDefaults();

	const mockCtx = {
		database: { native: db, add() {} },
		async getPointPick() {
			return { status: 'keyword', keyword: 'Style' };
		},
		async getString(prompt) {
			if (prompt === 'Enter style name:') return 'NoSuchStyle';
			return '';
		},
	};

	await assert.rejects(async () => {
		await textCommand(mockCtx);
	}, /Text style "NoSuchStyle" does not exist/);
});

test('CENTERMARK draws center mark and extension lines using drawing DIMCEN', async () => {
	const { AcDbDatabase, AcDbCircle, AcDbLine, centerMarkCommand } = await loadCadEditor();
	const db = new AcDbDatabase();
	db.ensureDatabaseDefaults();
	// Set negative DIMCEN on drawing
	db.dimcen = -2.5;

	const circle = new AcDbCircle({ x: 10, y: 20, z: 0 }, 100);
	circle.layer = '0';
	db.tables.blockTable.modelSpace.appendEntity(circle);

	const addedLines = [];
	const mockCtx = {
		database: {
			native: db,
			add(entities) {
				if (Array.isArray(entities)) addedLines.push(...entities);
				else addedLines.push(entities);
			},
		},
		async getEntity(prompt) {
			assert.equal(prompt, 'Select circle or arc:');
			return circle;
		},
	};

	await centerMarkCommand(mockCtx);
	// 2 cross lines + 4 extension lines = 6 lines
	assert.equal(addedLines.length, 6);
	assert.ok(addedLines.every(e => e instanceof AcDbLine));

	// Cross lines at center (10, 20):
	// Horizontal cross: [10 - 2.5, 20] to [10 + 2.5, 20] = [7.5, 20] to [12.5, 20]
	assert.deepEqual(
		{ start: { x: addedLines[0].startPoint.x, y: addedLines[0].startPoint.y }, end: { x: addedLines[0].endPoint.x, y: addedLines[0].endPoint.y } },
		{ start: { x: 7.5, y: 20 }, end: { x: 12.5, y: 20 } }
	);
	// Vertical cross: [10, 20 - 2.5] to [10, 20 + 2.5] = [10, 17.5] to [10, 22.5]
	assert.deepEqual(
		{ start: { x: addedLines[1].startPoint.x, y: addedLines[1].startPoint.y }, end: { x: addedLines[1].endPoint.x, y: addedLines[1].endPoint.y } },
		{ start: { x: 10, y: 17.5 }, end: { x: 10, y: 22.5 } }
	);
	// +X extension: [10 + 5.0, 20] to [10 + 102.5, 20] = [15, 20] to [112.5, 20]
	assert.deepEqual(
		{ start: { x: addedLines[2].startPoint.x, y: addedLines[2].startPoint.y }, end: { x: addedLines[2].endPoint.x, y: addedLines[2].endPoint.y } },
		{ start: { x: 15, y: 20 }, end: { x: 112.5, y: 20 } }
	);
	// -X extension: [10 - 5.0, 20] to [10 - 102.5, 20] = [5, 20] to [-92.5, 20]
	assert.deepEqual(
		{ start: { x: addedLines[3].startPoint.x, y: addedLines[3].startPoint.y }, end: { x: addedLines[3].endPoint.x, y: addedLines[3].endPoint.y } },
		{ start: { x: 5, y: 20 }, end: { x: -92.5, y: 20 } }
	);
	// +Y extension: [10, 20 + 5.0] to [10, 20 + 102.5] = [10, 25] to [10, 122.5]
	assert.deepEqual(
		{ start: { x: addedLines[4].startPoint.x, y: addedLines[4].startPoint.y }, end: { x: addedLines[4].endPoint.x, y: addedLines[4].endPoint.y } },
		{ start: { x: 10, y: 25 }, end: { x: 10, y: 122.5 } }
	);
	// -Y extension: [10, 20 - 5.0] to [10, 20 - 102.5] = [10, 15] to [10, -82.5]
	assert.deepEqual(
		{ start: { x: addedLines[5].startPoint.x, y: addedLines[5].startPoint.y }, end: { x: addedLines[5].endPoint.x, y: addedLines[5].endPoint.y } },
		{ start: { x: 10, y: 15 }, end: { x: 10, y: -82.5 } }
	);
});
