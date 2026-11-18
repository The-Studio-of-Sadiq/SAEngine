import assert from 'node:assert/strict';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { mkdtemp } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-block-test-')), 'blocks.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/blockGeometry.ts';
				export * from './src/blockCommands.ts';
				export * from './src/commands.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' }, plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('block point transform applies base, scale, rotation and insertion point', async () => {
	const { transformBlockPoint } = await load();
	assert.deepEqual(transformBlockPoint({ x: 10, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 100, y: 100, z: 0 }, 2, 2, Math.PI / 2), { x: 100, y: 120, z: 0 });
});

test('insert transform moves block line endpoints and attributes', async () => {
	const { AcDbAttribute, AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d, blockTransform, acdbHostApplicationServices } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;
	const block = new AcDbBlockTableRecord({ name: 'B1', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(10, 0, 0), new AcGePoint3d(0, 10, 0)));
	const tx = db.transactionManager.startTransaction(); db.tables.blockTable.add(block); tx.commit();
	const ref = new AcDbBlockReference('B1'); ref.position = new AcGePoint3d(100, 100, 0); ref.scaleFactors = new AcGePoint3d(2, 2, 1); ref.rotation = Math.PI / 2;
	const line = block.newIterator().next().value; line.transformBy(blockTransform(ref));
	assert.deepEqual([line.startPoint.x, line.startPoint.y, line.endPoint.x, line.endPoint.y], [100, 120, 80, 100]);
	const attr = new AcDbAttribute(); attr.position = new AcGePoint3d(10, 0, 0); ref.appendAttributes(attr); attr.transformBy(blockTransform(ref));
	assert.deepEqual([attr.position.x, attr.position.y], [100, 120]);
});

test('block definition and insert attributes survive DXF round trip', async () => {
	const { AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbFileType, AcDbLine, AcGePoint3d, acdbHostApplicationServices } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;
	const block = new AcDbBlockTableRecord({ name: 'ROUNDTRIP', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(5, 0, 0)));
	const def = new AcDbAttributeDefinition(); def.tag = 'CODE'; def.prompt = 'Code'; def.textString = 'default'; def.position = new AcGePoint3d(1, 1, 0); def.height = 2; block.appendEntity(def);
	db.tables.blockTable.add(block);
	const ref = new AcDbBlockReference('ROUNDTRIP'); ref.position = new AcGePoint3d(12, 13, 0); ref.scaleFactors = new AcGePoint3d(2, 3, 1); ref.rotation = Math.PI / 4;
	const attr = new AcDbAttribute(); attr.tag = 'CODE'; attr.textString = 'A-42'; attr.position = new AcGePoint3d(10, 10, 0); attr.height = 2; ref.appendAttributes(attr);
	db.tables.blockTable.modelSpace.appendEntity(ref);
	const out = db.dxfOut(undefined, 6); const text = typeof out === 'string' ? out : new TextDecoder().decode(out);
	const reread = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = reread;
	await reread.read(text, { readOnly: false }, AcDbFileType.DXF);
	const roundBlock = reread.tables.blockTable.getAt('ROUNDTRIP'); assert.ok(roundBlock);
	const roundRef = reread.tables.blockTable.modelSpace.newIterator().toArray().find(e => e instanceof AcDbBlockReference); assert.ok(roundRef);
	assert.deepEqual([roundRef.position.x, roundRef.position.y, roundRef.scaleFactors.x, roundRef.scaleFactors.y, roundRef.rotation], [12, 13, 2, 3, Math.PI / 4]);
	assert.equal(Array.from(roundRef.attributeIterator())[0]?.textString, 'A-42');
	assert.ok(Array.from(roundBlock.newIterator()).some(e => e instanceof AcDbAttributeDefinition));
});

test('WBLOCK outputs standalone DXF that reads back with entities and block table record', async () => {
	const { AcDbDatabase, AcDbFileType, AcDbLine, AcGePoint3d, acdbHostApplicationServices, wblockCommand } = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;
	const line = new AcDbLine(new AcGePoint3d(10, 20, 0), new AcGePoint3d(50, 60, 0));
	db.tables.blockTable.modelSpace.appendEntity(line);

	let emittedName = '';
	let emittedDxf = '';
	const mockCtx = {
		database: {
			native: db,
			all: () => db.tables.blockTable.modelSpace.newIterator().toArray(),
			add: (e) => db.tables.blockTable.modelSpace.appendEntity(Array.isArray(e) ? e : [e]),
			erase: () => {},
		},
		getString: async (prompt) => {
			if (prompt.includes('output block name')) return 'WBLOCK_EXPORT';
			if (prompt.includes('existing block name')) return '';
			throw new Error(`Unexpected getString: ${prompt}`);
		},
		getPoint: async () => ({ x: 10, y: 20, z: 0 }),
		getSelection: async () => [line],
		onWblock: (name, dxfText) => {
			emittedName = name;
			emittedDxf = dxfText;
		},
		message: () => {},
	};

	await wblockCommand(mockCtx);
	assert.equal(emittedName, 'WBLOCK_EXPORT');
	assert.ok(emittedDxf && emittedDxf.length > 0);

	const reread = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = reread;
	await reread.read(emittedDxf, { readOnly: false }, AcDbFileType.DXF);

	// Block record must exist in blockTable
	const blockRecord = reread.tables.blockTable.getAt('WBLOCK_EXPORT');
	assert.ok(blockRecord, 'Block record WBLOCK_EXPORT must be in blockTable');
	const blockEntities = Array.from(blockRecord.newIterator());
	assert.equal(blockEntities.length, 1);
	const blkLine = blockEntities[0];
	assert.ok(blkLine instanceof AcDbLine);
	assert.deepEqual([blkLine.startPoint.x, blkLine.startPoint.y, blkLine.endPoint.x, blkLine.endPoint.y], [0, 0, 40, 40]);

	// ModelSpace entities must also be present
	const modelEntities = reread.tables.blockTable.modelSpace.newIterator().toArray();
	assert.equal(modelEntities.length, 1);
	const msLine = modelEntities[0];
	assert.ok(msLine instanceof AcDbLine);
	assert.deepEqual([msLine.startPoint.x, msLine.startPoint.y, msLine.endPoint.x, msLine.endPoint.y], [0, 0, 40, 40]);
});

test('EXPLODE transforms insert entities and turns attributes into TEXT', async () => {
	const {
		AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord,
		AcDbDatabase, AcDbLine, AcDbText, AcGePoint3d, acdbHostApplicationServices,
		explodeCommand,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const block = new AcDbBlockTableRecord({ name: 'EXP_BLK', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(10, 0, 0), new AcGePoint3d(0, 10, 0)));
	const def = new AcDbAttributeDefinition();
	def.tag = 'TAG1';
	def.textString = 'DEF';
	def.position = new AcGePoint3d(5, 5, 0);
	def.height = 2;
	block.appendEntity(def);
	db.tables.blockTable.add(block);

	const ref = new AcDbBlockReference('EXP_BLK');
	ref.position = new AcGePoint3d(100, 100, 0);
	ref.scaleFactors = new AcGePoint3d(2, 2, 1);
	ref.rotation = Math.PI / 2;

	const attr = new AcDbAttribute();
	attr.tag = 'TAG1';
	attr.textString = 'HELLO_ATTR';
	attr.position = new AcGePoint3d(90, 110, 0);
	attr.height = 4;
	attr.rotation = Math.PI / 2;
	ref.appendAttributes(attr);

	db.tables.blockTable.modelSpace.appendEntity(ref);

	const addedEntities = [];
	const erasedIds = [];
	const mockCtx = {
		database: {
			native: db,
			add(e) {
				if (Array.isArray(e)) addedEntities.push(...e);
				else addedEntities.push(e);
			},
			erase(id) {
				erasedIds.push(id);
			},
		},
		getSelection: async () => [ref],
	};

	await explodeCommand(mockCtx);

	assert.equal(erasedIds.length, 1);
	assert.equal(erasedIds[0], String(ref.objectId));

	assert.equal(addedEntities.length, 2);
	const line = addedEntities.find(e => e instanceof AcDbLine);
	const text = addedEntities.find(e => e instanceof AcDbText);
	assert.ok(line, 'Transformed line should be present');
	assert.ok(text, 'Attribute as text should be present');

	// Line endpoint [10, 0] scaled 2, rotated 90°, translated [100, 100] -> [100, 120]
	// Endpoint [0, 10] -> [80, 100]
	assert.deepEqual([line.startPoint.x, line.startPoint.y, line.endPoint.x, line.endPoint.y], [100, 120, 80, 100]);

	// Attribute text should preserve its string and position
	assert.equal(text.textString, 'HELLO_ATTR');
	assert.deepEqual([text.position.x, text.position.y], [90, 110]);
	assert.equal(text.height, 4);
});

test('PURGE deletes only unused block definitions', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcGePoint3d,
		acdbHostApplicationServices, purgeCommand,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const usedBlock = new AcDbBlockTableRecord({ name: 'USED_BLOCK', origin: new AcGePoint3d(0, 0, 0) });
	const unusedBlock = new AcDbBlockTableRecord({ name: 'UNUSED_BLOCK', origin: new AcGePoint3d(0, 0, 0) });
	db.tables.blockTable.add(usedBlock);
	db.tables.blockTable.add(unusedBlock);

	const ref = new AcDbBlockReference('USED_BLOCK');
	ref.position = new AcGePoint3d(0, 0, 0);
	db.tables.blockTable.modelSpace.appendEntity(ref);

	let messageText = '';
	const mockCtx = {
		database: {
			native: db,
			all: () => db.tables.blockTable.modelSpace.newIterator().toArray(),
		},
		transaction: async (fn) => fn(),
		message: (msg) => { messageText = msg; },
	};

	await purgeCommand(mockCtx);
	assert.ok(db.tables.blockTable.has('USED_BLOCK'), 'Used block must be kept');
	assert.ok(!db.tables.blockTable.has('UNUSED_BLOCK'), 'Unused block must be purged');
	assert.equal(messageText, 'Purged 1 unused block definition(s).');
});

test('GROUP and UNGROUP manage entity groupings in AcDbGroup dictionary', async () => {
	const {
		AcDbDatabase, AcDbLine, AcGePoint3d, acdbHostApplicationServices,
		groupCommand, ungroupCommand,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const line1 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0));
	const line2 = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 10, 0));
	db.tables.blockTable.modelSpace.appendEntity([line1, line2]);

	let msg = '';
	const mockCtx = {
		database: {
			native: db,
		},
		getString: async () => 'GROUP1',
		getSelection: async () => [line1, line2],
		transaction: async (fn) => fn(),
		message: (m) => { msg = m; },
	};

	await groupCommand(mockCtx);
	assert.ok(db.objects.group.has('GROUP1'), 'Group GROUP1 should be registered in objects.group');
	const grp = db.objects.group.getAt('GROUP1');
	assert.equal(grp.name, 'GROUP1');
	assert.deepEqual(Array.from(grp.entityIds), [line1.objectId, line2.objectId]);

	await ungroupCommand(mockCtx);
	assert.ok(!db.objects.group.has('GROUP1'), 'Group GROUP1 should be removed after UNGROUP');
});
