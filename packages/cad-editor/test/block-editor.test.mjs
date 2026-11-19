import assert from 'node:assert/strict';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { mkdtemp } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-block-editor-test-')), 'blockEditor.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/blockGeometry.ts';
				export * from './src/blockCommands.ts';
				export * from './src/blockEditor.ts';
				export * from './src/xrefCommands.ts';
				export * from './src/dynamicBlocks.ts';
				export * from './src/commands.ts';
				export { applyGenerated, dxfOut } from './src/generated.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' }, plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

function createMockCtx(db, overrides = {}) {
	const space = db.tables.blockTable.modelSpace;
	return {
		database: {
			native: db,
			all: () => space.newIterator().toArray(),
			add: (e) => {
				const list = Array.isArray(e) ? e : [e];
				space.appendEntity(list);
				const session = globalThis.__saengineActiveBlockEditorSession;
				if (session) {
					for (const item of list) {
						session.editEntityIds.add(String(item.objectId));
					}
				}
			},
			erase: (id) => {
				const ent = space.getIdAt(id);
				if (ent) ent.erase();
			},
			replace: (id, entity) => {
				const old = space.getIdAt(id);
				if (old) old.erase();
				space.appendEntity(entity);
				const session = globalThis.__saengineActiveBlockEditorSession;
				if (session) {
					session.editEntityIds.add(String(entity.objectId));
				}
			},
			get: (id) => space.getIdAt(id),
		},
		getString: async () => '',
		getKeyword: async () => '',
		getPoint: async () => ({ x: 0, y: 0, z: 0 }),
		getEntity: async () => { throw new Error('No entity'); },
		getEntityPick: async () => ({ status: 'cancel' }),
		getDouble: async () => 0,
		getAngle: async () => 0,
		transaction: async (fn) => fn(),
		message: () => {},
		...overrides,
	};
}

test('BEDIT on block B adding a line then BCLOSE Save updates definition and reference geometry', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, beditCommand, bcloseCommand, blockTransform,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	// Block B has a line (0,0)-(10,0)
	const blockB = new AcDbBlockTableRecord({ name: 'B', origin: new AcGePoint3d(0, 0, 0) });
	blockB.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0)));
	db.tables.blockTable.add(blockB);

	// Reference at (100,0) rotated 90°
	const ref = new AcDbBlockReference('B');
	ref.position = new AcGePoint3d(100, 0, 0);
	ref.rotation = Math.PI / 2;
	db.tables.blockTable.modelSpace.appendEntity(ref);

	const ctx = createMockCtx(db, {
		getString: async (prompt) => {
			if (prompt.includes('Enter block name')) return 'B';
			return '';
		},
	});

	await beditCommand(ctx);

	// Add line (0,0)-(0,5) in model space while in BEDIT
	const newLine = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 5, 0));
	ctx.database.add(newLine);

	// BCLOSE Save
	const closeCtx = createMockCtx(db, {
		getKeyword: async () => 'Save',
	});
	await bcloseCommand(closeCtx);

	// Definition has 2 entities
	const defEntities = Array.from(blockB.newIterator());
	assert.equal(defEntities.length, 2);

	// A reference at (100,0) rotated 90° shows a line endpoint at (95,0)
	const xform = blockTransform(ref);
	const line2Transformed = defEntities[1].clone();
	line2Transformed.transformBy(xform);
	assert.equal(Math.round(line2Transformed.endPoint.x), 95);
	assert.equal(Math.round(line2Transformed.endPoint.y), 0);
});

test('REFEDIT on reference adding a line from world (100,0) to (100,20) saves (0,0)-(20,0) into definition', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, refeditCommand, refcloseCommand,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const blockB = new AcDbBlockTableRecord({ name: 'B_REF', origin: new AcGePoint3d(0, 0, 0) });
	blockB.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0)));
	db.tables.blockTable.add(blockB);

	const ref = new AcDbBlockReference('B_REF');
	ref.position = new AcGePoint3d(100, 0, 0);
	ref.rotation = Math.PI / 2;
	db.tables.blockTable.modelSpace.appendEntity(ref);

	const ctx = createMockCtx(db, {
		getEntity: async () => ref,
	});

	await refeditCommand(ctx);

	// Add line from world (100,0) to (100,20)
	const worldLine = new AcDbLine(new AcGePoint3d(100, 0, 0), new AcGePoint3d(100, 20, 0));
	ctx.database.add(worldLine);

	const closeCtx = createMockCtx(db, {
		getKeyword: async () => 'Save',
	});
	await refcloseCommand(closeCtx);

	// Definition gets (0,0)-(20,0) via inverse transform T^-1 = R(-90°) * T(-100, 0)
	const defEntities = Array.from(blockB.newIterator());
	const addedLine = defEntities.find(e => e instanceof AcDbLine && (Math.round(e.endPoint.x) === 20 || Math.round(e.startPoint.x) === 20));
	assert.ok(addedLine, 'Definition must contain line with endpoint x=20');
	assert.equal(Math.round(addedLine.startPoint.x), 0);
	assert.equal(Math.round(addedLine.startPoint.y), 0);
	assert.equal(Math.round(addedLine.endPoint.x), 20);
	assert.equal(Math.round(addedLine.endPoint.y), 0);
});

test('ATTSYNC adds a new tag with its default to both references and keeps existing edited values', async () => {
	const {
		AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord,
		AcDbDatabase, AcGePoint3d, acdbHostApplicationServices, attsyncCommand,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const block = new AcDbBlockTableRecord({ name: 'ATT_BLK', origin: new AcGePoint3d(0, 0, 0) });
	const def1 = new AcDbAttributeDefinition();
	def1.tag = 'TAG1';
	def1.textString = 'DEFAULT1';
	def1.position = new AcGePoint3d(1, 1, 0);
	def1.height = 2;
	block.appendEntity(def1);
	db.tables.blockTable.add(block);

	// Ref 1 with edited attribute TAG1 = 'EDITED_VAL'
	const ref1 = new AcDbBlockReference('ATT_BLK');
	ref1.position = new AcGePoint3d(10, 10, 0);
	const attr1 = new AcDbAttribute();
	attr1.tag = 'TAG1';
	attr1.textString = 'EDITED_VAL';
	attr1.position = new AcGePoint3d(11, 11, 0);
	attr1.height = 2;
	ref1.appendAttributes(attr1);
	db.tables.blockTable.modelSpace.appendEntity(ref1);

	// Ref 2 with default TAG1 = 'DEFAULT1'
	const ref2 = new AcDbBlockReference('ATT_BLK');
	ref2.position = new AcGePoint3d(50, 50, 0);
	const attr2 = new AcDbAttribute();
	attr2.tag = 'TAG1';
	attr2.textString = 'DEFAULT1';
	attr2.position = new AcGePoint3d(51, 51, 0);
	attr2.height = 2;
	ref2.appendAttributes(attr2);
	db.tables.blockTable.modelSpace.appendEntity(ref2);

	// Add new definition TAG2 to block definition
	const def2 = new AcDbAttributeDefinition();
	def2.tag = 'TAG2';
	def2.textString = 'DEFAULT2';
	def2.position = new AcGePoint3d(2, 2, 0);
	def2.height = 2;
	block.appendEntity(def2);

	// Run ATTSYNC
	const ctx = createMockCtx(db, {
		getString: async () => 'ATT_BLK',
	});
	await attsyncCommand(ctx);

	const attrs1 = Array.from(ref1.attributeIterator());
	const attrs2 = Array.from(ref2.attributeIterator());

	assert.equal(attrs1.length, 2);
	assert.equal(attrs2.length, 2);

	// ref1 kept edited value for TAG1 and got default for TAG2
	assert.equal(attrs1.find(a => a.tag === 'TAG1')?.textString, 'EDITED_VAL');
	assert.equal(attrs1.find(a => a.tag === 'TAG2')?.textString, 'DEFAULT2');

	// ref2 has default for both
	assert.equal(attrs2.find(a => a.tag === 'TAG1')?.textString, 'DEFAULT1');
	assert.equal(attrs2.find(a => a.tag === 'TAG2')?.textString, 'DEFAULT2');
});

test('Bind of an xref turns it into a normal block with the same entities', async () => {
	const {
		AcDbBlockTableRecord, AcDbBlockTableRecordFlag, AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, bindXref,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const xrefRecord = new AcDbBlockTableRecord({
		name: 'EXT_REF',
		pathName: 'path/to/ext.dxf',
		flags: AcDbBlockTableRecordFlag.Xref | AcDbBlockTableRecordFlag.Resolved,
		origin: new AcGePoint3d(0, 0, 0),
	});
	xrefRecord.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(50, 50, 0)));
	db.tables.blockTable.add(xrefRecord);

	assert.equal(xrefRecord.isXref, true);
	assert.equal(xrefRecord.pathName, 'path/to/ext.dxf');

	bindXref(db, 'EXT_REF');

	assert.equal(xrefRecord.isXref, false);
	assert.equal(xrefRecord.pathName, '');
	assert.equal((xrefRecord.flags & AcDbBlockTableRecordFlag.Xref), 0);
	const ents = Array.from(xrefRecord.newIterator());
	assert.equal(ents.length, 1);
	assert.ok(ents[0] instanceof AcDbLine);
});

test('Linear+Stretch parameter set to 20 on a 10-long block stretches reference line end to 20 while definition stays 10', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, setDynamicBlockDef, setDynamicBlockProps,
		regenerateDynamicBlockReference,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const block = new AcDbBlockTableRecord({ name: 'STRETCH_BLK', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0)));
	db.tables.blockTable.add(block);

	setDynamicBlockDef(db, block, {
		params: [
			{
				type: 'linear',
				name: 'Distance',
				startPoint: { x: 0, y: 0, z: 0 },
				endPoint: { x: 10, y: 0, z: 0 },
				defaultDistance: 10,
				action: 'stretch',
			},
		],
	});

	const ref = new AcDbBlockReference('STRETCH_BLK');
	ref.position = new AcGePoint3d(0, 0, 0);
	db.tables.blockTable.modelSpace.appendEntity(ref);

	// Set parameter to 20
	setDynamicBlockProps(db, ref, { originalBlockName: 'STRETCH_BLK', values: { Distance: 20 } });
	const anonRecord = regenerateDynamicBlockReference(db, ref);

	// Definition stays 10
	const defLine = Array.from(block.newIterator())[0];
	assert.equal(defLine.endPoint.x, 10);

	// Anonymous block stretches line end to x=20
	const anonLine = Array.from(anonRecord.newIterator())[0];
	assert.equal(anonLine.startPoint.x, 0);
	assert.equal(anonLine.endPoint.x, 20);
});

test('Flip mirrors about the flip line', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, setDynamicBlockDef, setDynamicBlockProps,
		regenerateDynamicBlockReference,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const block = new AcDbBlockTableRecord({ name: 'FLIP_BLK', origin: new AcGePoint3d(0, 0, 0) });
	// Line from (0,0) to (10,5)
	block.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 5, 0)));
	db.tables.blockTable.add(block);

	// Flip about X-axis (line y=0 from (0,0) to (10,0))
	setDynamicBlockDef(db, block, {
		params: [
			{
				type: 'flip',
				name: 'Flip',
				lineStart: { x: 0, y: 0, z: 0 },
				lineEnd: { x: 10, y: 0, z: 0 },
				defaultState: 0,
				action: 'flip',
			},
		],
	});

	const ref = new AcDbBlockReference('FLIP_BLK');
	db.tables.blockTable.modelSpace.appendEntity(ref);

	setDynamicBlockProps(db, ref, { originalBlockName: 'FLIP_BLK', values: { Flip: 1 } });
	const anonRecord = regenerateDynamicBlockReference(db, ref);

	const mirroredLine = Array.from(anonRecord.newIterator())[0];
	assert.equal(mirroredLine.startPoint.x, 0);
	assert.equal(mirroredLine.startPoint.y, 0);
	assert.equal(mirroredLine.endPoint.x, 10);
	assert.equal(mirroredLine.endPoint.y, -5);
});

test('DXF round trip keeps dynamic parameters and visibility states', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbFileType, AcDbLine,
		AcGePoint3d, acdbHostApplicationServices, setDynamicBlockDef, getDynamicBlockDef,
		setDynamicBlockProps, getDynamicBlockProps,
	} = await load();
	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	const block = new AcDbBlockTableRecord({ name: 'DYN_ROUNDTRIP', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0)));
	db.tables.blockTable.add(block);

	setDynamicBlockDef(db, block, {
		params: [
			{
				type: 'linear',
				name: 'Length',
				startPoint: { x: 0, y: 0, z: 0 },
				endPoint: { x: 10, y: 0, z: 0 },
				defaultDistance: 10,
				action: 'stretch',
			},
			{
				type: 'visibility',
				name: 'Mode',
				states: ['State1', 'State2'],
				defaultState: 'State1',
				stateVisibility: { State1: [0], State2: [] },
			},
		],
	});

	const ref = new AcDbBlockReference('DYN_ROUNDTRIP');
	ref.position = new AcGePoint3d(5, 5, 0);
	db.tables.blockTable.modelSpace.appendEntity(ref);

	setDynamicBlockProps(db, ref, {
		originalBlockName: 'DYN_ROUNDTRIP',
		values: { Length: 15, Mode: 'State2' },
	});

	const dxfOutResult = db.dxfOut(undefined, 6);
	const text = typeof dxfOutResult === 'string' ? dxfOutResult : new TextDecoder().decode(dxfOutResult);

	const reread = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = reread;
	await reread.read(text, { readOnly: false }, AcDbFileType.DXF);

	const roundBlock = reread.tables.blockTable.getAt('DYN_ROUNDTRIP');
	assert.ok(roundBlock);
	const roundDef = getDynamicBlockDef(roundBlock);
	assert.ok(roundDef);
	assert.equal(roundDef.params.length, 2);
	assert.equal(roundDef.params[0].type, 'linear');
	assert.equal(roundDef.params[0].name, 'Length');
	assert.equal(roundDef.params[1].type, 'visibility');
	assert.deepEqual(roundDef.params[1].states, ['State1', 'State2']);

	const roundRef = reread.tables.blockTable.modelSpace.newIterator().toArray().find(e => e instanceof AcDbBlockReference);
	assert.ok(roundRef);
	const roundProps = getDynamicBlockProps(roundRef);
	assert.ok(roundProps);
	assert.equal(roundProps.originalBlockName, 'DYN_ROUNDTRIP');
	assert.equal(roundProps.values.Length, 15);
	assert.equal(roundProps.values.Mode, 'State2');
});

test('BEDIT & REFEDIT keep stashed and generated entities without erasing, toDxf during session equals start, Discard is byte-identical, Save changes only block definition', async () => {
	const {
		AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d,
		acdbHostApplicationServices, beditCommand, bcloseCommand, refeditCommand, refcloseCommand,
		getActiveBlockEditingInfo, getActiveBlockEditorSession, onDidChangeBlockEditorSession,
		toDxf,
	} = await load();

	const db = new AcDbDatabase();
	acdbHostApplicationServices().workingDatabase = db;

	// Define block "DOOR" with a line (0,0)-(10,0)
	const blockDoor = new AcDbBlockTableRecord({ name: 'DOOR', origin: new AcGePoint3d(0, 0, 0) });
	blockDoor.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(10, 0, 0)));
	db.tables.blockTable.add(blockDoor);

	// User line on layer 0
	const userLine = new AcDbLine(new AcGePoint3d(10, 10, 0), new AcGePoint3d(20, 20, 0));
	userLine.layer = '0';
	db.tables.blockTable.modelSpace.appendEntity(userLine);

	// Generated entity on generated layer
	globalThis.__saengineGeneratedLayers = new Set(['S-BEAM', 'SAENGINE-GEN']);
	const genLine = new AcDbLine(new AcGePoint3d(100, 100, 0), new AcGePoint3d(200, 100, 0));
	genLine.layer = 'S-BEAM';
	db.tables.blockTable.modelSpace.appendEntity(genLine);

	// Block reference to DOOR at (50, 50)
	const ref = new AcDbBlockReference('DOOR');
	ref.position = new AcGePoint3d(50, 50, 0);
	db.tables.blockTable.modelSpace.appendEntity(ref);

	const isEntityInModel = (e) => db.tables.blockTable.modelSpace.getIdAt(e.objectId) !== undefined;
	const getModelEntities = () => db.tables.blockTable.modelSpace.newIterator().toArray();

	// Initial non-erased entities count = 3 (userLine, genLine, ref)
	assert.equal(getModelEntities().length, 3);
	assert.equal(isEntityInModel(userLine), true);
	assert.equal(isEntityInModel(genLine), true);
	assert.equal(isEntityInModel(ref), true);

	const initialDxf = toDxf(db);
	const initialDxfExclude = toDxf(db, { excludeGenerated: true });
	assert.ok(initialDxf.includes('S-BEAM'), 'Initial DXF includes generated layer S-BEAM');
	assert.ok(!initialDxfExclude.includes('S-BEAM'), 'Initial DXF with excludeGenerated excludes S-BEAM');

	// Helper to extract the ENTITIES section of a DXF string
	function extractEntitiesSection(dxf) {
		const match = dxf.match(/SECTION\r?\n\s*2\r?\nENTITIES\r?\n([\s\S]*?)\r?\n\s*0\r?\nENDSEC/);
		return match ? match[1] : '';
	}

	// -------------------------------------------------------------
	// 1. BEDIT: No entity erased, toDxf during session equals start
	// -------------------------------------------------------------
	const editingEvents = [];
	const unsub = onDidChangeBlockEditorSession(info => editingEvents.push(info));

	const beditCtx = createMockCtx(db, {
		getString: async () => 'DOOR',
	});
	await beditCommand(beditCtx);

	// Event fired on enter
	assert.deepEqual(getActiveBlockEditingInfo(), { mode: 'bedit', blockName: 'DOOR' });
	assert.equal(editingEvents.length, 1);
	assert.deepEqual(editingEvents[0], { mode: 'bedit', blockName: 'DOOR' });

	// No stashed or generated entity was erased!
	assert.equal(isEntityInModel(userLine), true, 'User line must NOT be erased during BEDIT');
	assert.equal(isEntityInModel(genLine), true, 'Generated entity must NOT be erased during BEDIT');
	assert.equal(isEntityInModel(ref), true, 'Reference must NOT be erased during BEDIT');

	const beditSession = getActiveBlockEditorSession();
	assert.ok(beditSession);
	const nonWorkingDuringBedit = getModelEntities().filter(e => !beditSession.editEntityIds.has(String(e.objectId)));
	assert.equal(nonWorkingDuringBedit.length, 3, 'Model space must retain all 3 pre-session entities without erasing');

	// toDxf() during session equals pre-session DXF
	assert.equal(toDxf(db), initialDxf, 'toDxf() during BEDIT must equal pre-session DXF');
	assert.equal(toDxf(db, { excludeGenerated: true }), initialDxfExclude, 'toDxf({ excludeGenerated: true }) during BEDIT must equal pre-session');

	// Draw an entity in model space during BEDIT
	const beditNewLine = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 15, 0));
	beditCtx.database.add(beditNewLine);

	// Even with in-progress block edits, toDxf() remains unchanged
	assert.equal(toDxf(db), initialDxf, 'toDxf() during BEDIT after draw must still equal pre-session DXF');

	// -------------------------------------------------------------
	// 2. BCLOSE Discard: toDxf equals the original exactly
	// -------------------------------------------------------------
	const discardCtx = createMockCtx(db, {
		getKeyword: async () => 'Discard',
	});
	await bcloseCommand(discardCtx);

	assert.equal(getActiveBlockEditingInfo(), undefined);
	assert.equal(editingEvents.length, 2);
	assert.equal(editingEvents[1], undefined);

	assert.equal(getModelEntities().length, 3);
	assert.equal(isEntityInModel(userLine), true);
	assert.equal(isEntityInModel(genLine), true);
	assert.equal(isEntityInModel(ref), true);

	const discardDxf = toDxf(db);
	assert.equal(discardDxf, initialDxf, 'BCLOSE Discard must leave DXF output byte-identical to original');
	assert.equal(toDxf(db, { excludeGenerated: true }), initialDxfExclude);

	// -------------------------------------------------------------
	// 3. BCLOSE Save: only the block definition differs
	// -------------------------------------------------------------
	await beditCommand(beditCtx);
	assert.deepEqual(getActiveBlockEditingInfo(), { mode: 'bedit', blockName: 'DOOR' });

	const beditSaveLine = new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(0, 25, 0));
	beditCtx.database.add(beditSaveLine);

	const saveCtx = createMockCtx(db, {
		getKeyword: async () => 'Save',
	});
	await bcloseCommand(saveCtx);

	assert.equal(getActiveBlockEditingInfo(), undefined);
	assert.equal(getModelEntities().length, 3);
	assert.equal(isEntityInModel(userLine), true);
	assert.equal(isEntityInModel(genLine), true);
	assert.equal(isEntityInModel(ref), true);

	const saveDxf = toDxf(db);
	assert.notEqual(saveDxf, initialDxf, 'BCLOSE Save must change DXF');
	// Block definition changed: blockDoor now has 2 entities
	const doorEntities = Array.from(blockDoor.newIterator());
	assert.equal(doorEntities.length, 2, 'Block definition DOOR now has 2 entities');
	// ENTITIES section (model space entities) remains identical
	assert.equal(extractEntitiesSection(saveDxf), extractEntitiesSection(initialDxf), 'Model-space ENTITIES section must be identical after BCLOSE Save');

	// -------------------------------------------------------------
	// 4. REFEDIT: Hide reference, toDxf rule, Discard byte-identical, Save updates definition
	// -------------------------------------------------------------
	const preRefDxf = toDxf(db);
	const preRefDxfExclude = toDxf(db, { excludeGenerated: true });

	const refCtx = createMockCtx(db, {
		getEntity: async () => ref,
	});
	await refeditCommand(refCtx);

	assert.deepEqual(getActiveBlockEditingInfo(), { mode: 'refedit', blockName: 'DOOR' });
	assert.equal(isEntityInModel(ref), true, 'Block reference must NOT be erased during REFEDIT (must be hidden)');
	assert.equal(isEntityInModel(userLine), true);
	assert.equal(isEntityInModel(genLine), true);

	const refSession = getActiveBlockEditorSession();
	assert.ok(refSession);
	const nonWorkingDuringRefedit = getModelEntities().filter(e => !refSession.editEntityIds.has(String(e.objectId)));
	assert.equal(nonWorkingDuringRefedit.length, 3, 'Model space retains all 3 entities during REFEDIT');

	// toDxf() during REFEDIT equals pre-REFEDIT DXF
	assert.equal(toDxf(db), preRefDxf, 'toDxf() during REFEDIT must equal pre-REFEDIT DXF');
	assert.equal(toDxf(db, { excludeGenerated: true }), preRefDxfExclude);

	// Add an entity during REFEDIT
	const refNewLine = new AcDbLine(new AcGePoint3d(50, 50, 0), new AcGePoint3d(50, 80, 0));
	refCtx.database.add(refNewLine);
	assert.equal(toDxf(db), preRefDxf, 'toDxf() during REFEDIT after draw still equals pre-REFEDIT DXF');

	// REFCLOSE Discard
	const refDiscardCtx = createMockCtx(db, {
		getKeyword: async () => 'Discard',
	});
	await refcloseCommand(refDiscardCtx);

	assert.equal(getActiveBlockEditingInfo(), undefined);
	assert.equal(getModelEntities().length, 3);
	assert.equal(isEntityInModel(ref), true);
	assert.equal(toDxf(db), preRefDxf, 'REFCLOSE Discard must leave DXF byte-identical');

	// REFCLOSE Save
	await refeditCommand(refCtx);
	const refSaveLine = new AcDbLine(new AcGePoint3d(50, 50, 0), new AcGePoint3d(50, 100, 0));
	refCtx.database.add(refSaveLine);

	const refSaveCtx = createMockCtx(db, {
		getKeyword: async () => 'Save',
	});
	await refcloseCommand(refSaveCtx);

	assert.equal(getActiveBlockEditingInfo(), undefined);
	assert.equal(getModelEntities().length, 3);
	assert.equal(isEntityInModel(ref), true);

	const refSaveDxf = toDxf(db);
	assert.notEqual(refSaveDxf, preRefDxf, 'REFCLOSE Save must update DXF');
	assert.equal(extractEntitiesSection(refSaveDxf), extractEntitiesSection(preRefDxf), 'Model-space ENTITIES section must be identical after REFCLOSE Save');

	unsub();
	delete globalThis.__saengineGeneratedLayers;
});
