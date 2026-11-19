import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadCadEditor() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-styles-audit-')), 'model.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/stylesAuditCommands.ts';
				export * from './src/annotationCommands.ts';
				export * from './src/commands.ts';
				export * from './src/index.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		mainFields: ['module', 'main'],
		define: { define: 'undefined' },
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('-MLSTYLE New with two elements offset ±0.5 round trips through DXF', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbMlineStyle, AcCmColor,
		mlstyleCommand,
	} = await loadCadEditor();

	const db = new AcDbDatabase();
	db.createDefaultData();

	const inputs = ['New', 'OFFSET_STYLE', 2, 0.5, -0.5, 'None', 'No'];
	let inputIdx = 0;

	const mockCtx = {
		database: {
			native: db,
			add() {},
			erase() {},
			replace() {},
			all: () => [],
		},
		message() {},
		async getKeyword() {
			return inputs[inputIdx++];
		},
		async getString() {
			return String(inputs[inputIdx++]);
		},
		async getInteger() {
			return Number(inputs[inputIdx++]);
		},
		async getDouble() {
			return Number(inputs[inputIdx++]);
		},
	};

	await mlstyleCommand(mockCtx);

	assert.ok(db.objects.mlineStyle.has('OFFSET_STYLE'), 'db should contain OFFSET_STYLE');
	const style = db.objects.mlineStyle.getAt('OFFSET_STYLE');
	assert.equal(style.elements.length, 2);
	assert.equal(style.elements[0].offset, 0.5);
	assert.equal(style.elements[1].offset, -0.5);

	// DXF round trip
	const out = db.dxfOut(undefined, 6);
	const dxf = typeof out === 'string' ? out : new TextDecoder().decode(out);
	assert.ok(dxf.includes('OFFSET_STYLE'), 'DXF should contain OFFSET_STYLE');

	const reopened = new AcDbDatabase();
	await reopened.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	assert.ok(reopened.objects.mlineStyle.has('OFFSET_STYLE'), 'Reopened db should contain OFFSET_STYLE');
	const reopenedStyle = reopened.objects.mlineStyle.getAt('OFFSET_STYLE');
	assert.equal(reopenedStyle.elements.length, 2);
	assert.equal(reopenedStyle.elements[0].offset, 0.5);
	assert.equal(reopenedStyle.elements[1].offset, -0.5);
});

test('-TABLESTYLE New text height 3.5 -> a new TABLE uses 3.5', async () => {
	const {
		AcDbDatabase, AcDbMText, tablestyleCommand, tableCommand, getCurrentTableStyle,
	} = await loadCadEditor();

	const db = new AcDbDatabase();
	db.createDefaultData();

	// Create table style with text height 3.5
	const tsInputs = ['New', 'STYLE35', 'Standard', 3.5, 'MiddleCenter', 1.5, 0.25];
	let tsIdx = 0;

	const tsMockCtx = {
		database: {
			native: db,
			add() {},
			erase() {},
			replace() {},
			all: () => [],
		},
		message() {},
		async getKeyword() { return tsInputs[tsIdx++]; },
		async getString() { return String(tsInputs[tsIdx++]); },
		async getDouble() { return Number(tsInputs[tsIdx++]); },
		async getInteger() { return Number(tsInputs[tsIdx++]); },
	};

	await tablestyleCommand(tsMockCtx);

	const curStyle = getCurrentTableStyle(db);
	assert.equal(curStyle.name, 'STYLE35');
	assert.equal(curStyle.textHeight, 3.5);

	// Run TABLE command
	const addedEntities = [];
	const tableInputs = {
		point: { x: 0, y: 0, z: 0 },
		rows: 2,
		cols: 2,
		rh: 10,
		cw: 25,
		header: 'Yes',
		headerStrings: ['Header 1', 'Header 2'],
	};
	let headerStrIdx = 0;

	const tableMockCtx = {
		database: {
			native: db,
			add(ents) {
				if (Array.isArray(ents)) addedEntities.push(...ents);
				else addedEntities.push(ents);
			},
			erase() {},
			replace() {},
			all: () => addedEntities,
		},
		message() {},
		async getPoint() { return tableInputs.point; },
		async getInteger(prompt) {
			if (prompt.includes('rows')) return tableInputs.rows;
			return tableInputs.cols;
		},
		async getDouble(prompt) {
			if (prompt.includes('Row')) return tableInputs.rh;
			return tableInputs.cw;
		},
		async getKeyword() { return tableInputs.header; },
		async getString() { return tableInputs.headerStrings[headerStrIdx++]; },
	};

	await tableCommand(tableMockCtx);

	const mtexts = addedEntities.filter(e => e instanceof AcDbMText);
	assert.ok(mtexts.length > 0, 'Table command should generate MText headers');
	for (const mt of mtexts) {
		assert.equal(mt.height, 3.5, 'Table MText height should match table style text height (3.5)');
	}
});

test('AUDIT on an entity whose layer was removed reports 1 error and with fix moves it to layer 0', async () => {
	const {
		AcDbDatabase, AcDbLine, AcDbLayerTableRecord, AcGePoint3d, auditDrawing,
	} = await loadCadEditor();

	const db = new AcDbDatabase();
	db.createDefaultData();

	// Add custom layer
	const layerRec = new AcDbLayerTableRecord();
	layerRec.name = 'LAYER_TO_REMOVE';
	db.tables.layerTable.add(layerRec);

	// Add line on that layer
	const line = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	line.layer = 'LAYER_TO_REMOVE';
	db.tables.blockTable.modelSpace.appendEntity(line);

	// Remove layer
	db.tables.layerTable.remove('LAYER_TO_REMOVE');
	assert.equal(db.tables.layerTable.has('LAYER_TO_REMOVE'), false);

	// Run audit without fix
	const unfixed = auditDrawing(db, false);
	assert.equal(unfixed.errorCount, 1, 'Should report 1 error');
	assert.equal(unfixed.fixedCount, 0, 'Should have fixed 0');
	assert.equal(line.layer, 'LAYER_TO_REMOVE');

	// Run audit with fix
	const fixed = auditDrawing(db, true);
	assert.equal(fixed.errorCount, 1, 'Should report 1 error');
	assert.equal(fixed.fixedCount, 1, 'Should have fixed 1 error');
	assert.equal(line.layer, '0', 'Line should be moved to layer 0');
});

test('DATAEXTRACTION of 3 lines lengths 10, 20, 30 on layer A -> CSV header "Type,Layer,Length" and total length 60, and 2 inserts of block DOOR -> one row Count 2', async () => {
	const {
		AcDbDatabase, AcDbLine, AcDbBlockReference, AcGePoint3d, dataExtraction,
	} = await loadCadEditor();

	const db = new AcDbDatabase();
	db.createDefaultData();

	// Part A: 3 lines lengths 10, 20, 30 on layer A
	const l1 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	l1.layer = 'A';
	const l2 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 20, 0));
	l2.layer = 'A';
	const l3 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 0, 30));
	l3.layer = 'A';

	const lineCsv = dataExtraction(db, {
		entities: [l1, l2, l3],
		properties: ['Type', 'Layer', 'Length'],
	});

	const lineRows = lineCsv.trim().split('\n');
	assert.equal(lineRows[0], 'Type,Layer,Length');
	assert.equal(lineRows.length, 4);

	const totalLength = lineRows.slice(1).reduce((sum, r) => sum + Number(r.split(',')[2]), 0);
	assert.equal(totalLength, 60, 'Total length of lines should be 60');

	// Part B: 2 inserts of block DOOR -> one row Count 2
	const b1 = new AcDbBlockReference();
	b1.blockName = 'DOOR';
	const b2 = new AcDbBlockReference();
	b2.blockName = 'DOOR';

	const blockCsv = dataExtraction(db, {
		entities: [b1, b2],
		properties: ['Count', 'Name'],
	});

	const blockRows = blockCsv.trim().split('\n');
	assert.equal(blockRows[0], 'Count,Name');
	assert.equal(blockRows.length, 2, 'Should collapse identical blocks into exactly one data row');
	assert.equal(blockRows[1], '2,DOOR', 'Data row should have Count 2 and Name DOOR');
});

test('LAYWALK Exit restores on/off/frozen states exactly', async () => {
	const {
		AcDbDatabase, AcDbLayerTableRecord, laywalkCommand,
	} = await loadCadEditor();

	const db = new AcDbDatabase();
	db.createDefaultData();

	// Set layer 0: on, not frozen
	const l0 = db.tables.layerTable.getAt('0');
	l0.isOff = false;
	l0.isFrozen = false;

	// Create layer A: off, not frozen
	const la = new AcDbLayerTableRecord();
	la.name = 'LAYER_A';
	la.isOff = true;
	la.isFrozen = false;
	db.tables.layerTable.add(la);

	// Create layer B: on, frozen
	const lb = new AcDbLayerTableRecord();
	lb.name = 'LAYER_B';
	lb.isOff = false;
	lb.isFrozen = true;
	db.tables.layerTable.add(lb);

	const commands = ['Next', 'Next', 'Previous', 'Select', 'LAYER_A', 'Exit'];
	let cmdIdx = 0;

	const mockCtx = {
		database: {
			native: db,
			add() {},
			erase() {},
			replace() {},
			all: () => [],
		},
		message() {},
		async getKeyword() {
			return commands[cmdIdx++];
		},
		async getString() {
			return commands[cmdIdx++];
		},
	};

	await laywalkCommand(mockCtx);

	// Verify exact restoration
	assert.equal(l0.isOff, false, 'Layer 0 isOff should be restored to false');
	assert.equal(l0.isFrozen, false, 'Layer 0 isFrozen should be restored to false');
	assert.equal(la.isOff, true, 'Layer A isOff should be restored to true');
	assert.equal(la.isFrozen, false, 'Layer A isFrozen should be restored to false');
	assert.equal(lb.isOff, false, 'Layer B isOff should be restored to false');
	assert.equal(lb.isFrozen, true, 'Layer B isFrozen should be restored to true');
});

test('-MLEADERSTYLE New arrow size 3.5 and text height 4.0 -> MLEADER uses it and round trips through DXF', async () => {
	const {
		AcDbDatabase, AcDbFileType, AcDbMLeader, mleaderstyleCommand, mleaderCommand,
	} = await loadCadEditor();

	const db = new AcDbDatabase();
	db.createDefaultData();

	const mldInputs = ['New', 'MY_MLD_STYLE', 3.5, 1.8, 4.0, 'MText'];
	let mldIdx = 0;

	const mldMockCtx = {
		database: {
			native: db,
			add() {},
			erase() {},
			replace() {},
			all: () => [],
		},
		message() {},
		async getKeyword() { return mldInputs[mldIdx++]; },
		async getString() { return String(mldInputs[mldIdx++]); },
		async getDouble() { return Number(mldInputs[mldIdx++]); },
	};

	await mleaderstyleCommand(mldMockCtx);

	assert.ok(db.objects.mleaderStyle.has('MY_MLD_STYLE'), 'db should contain MY_MLD_STYLE');
	assert.equal(db.cmleaderstyle, 'MY_MLD_STYLE');

	// Create an MLEADER
	const added = [];
	const leaderMockCtx = {
		database: {
			native: db,
			add(e) { added.push(e); },
			erase() {},
			replace() {},
			all: () => added,
		},
		message() {},
		async getPoint(prompt) {
			if (prompt.includes('arrowhead')) return { x: 0, y: 0, z: 0 };
			return { x: 10, y: 10, z: 0 };
		},
		async getString() { return 'Test Leader Text'; },
	};

	await mleaderCommand(leaderMockCtx);

	const leader = added.find(e => e instanceof AcDbMLeader);
	assert.ok(leader, 'Should create AcDbMLeader');
	assert.equal(leader.arrowheadSize, 3.5, 'MLEADER arrowhead size should be 3.5');
	assert.equal(leader.textHeight, 4.0, 'MLEADER text height should be 4.0');

	// DXF round trip
	db.tables.blockTable.modelSpace.appendEntity(leader);
	const out = db.dxfOut(undefined, 6);
	const dxf = typeof out === 'string' ? out : new TextDecoder().decode(out);
	assert.ok(dxf.includes('MY_MLD_STYLE'), 'DXF should include MY_MLD_STYLE');

	const reopened = new AcDbDatabase();
	await reopened.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	assert.ok(reopened.objects.mleaderStyle.has('MY_MLD_STYLE'), 'Reopened db should contain MY_MLD_STYLE');
	const reopenedStyle = reopened.objects.mleaderStyle.getAt('MY_MLD_STYLE');
	assert.equal(reopenedStyle.arrowSize, 3.5);
	assert.equal(reopenedStyle.textHeight, 4.0);
});

