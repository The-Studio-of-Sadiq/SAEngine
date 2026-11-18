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
		stdin: { contents: "export * from '@mlightcad/data-model'; export * from './src/blockGeometry.ts';", resolveDir: process.cwd() },
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
	const { AcDbAttribute, AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbLine, AcGePoint3d, blockTransform } = await load();
	const db = new AcDbDatabase();
	const block = new AcDbBlockTableRecord({ name: 'B1', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(10, 0, 0), new AcGePoint3d(0, 10, 0)));
	const tx = db.transactionManager.startTransaction(); db.tables.blockTable.add(block); tx.commit();
	const ref = new AcDbBlockReference('B1'); ref.position = new AcGePoint3d(100, 100, 0); ref.scaleFactors = new AcGePoint3d(2, 2, 1); ref.rotation = Math.PI / 2;
	const line = block.newIterator().next(); line.transformBy(blockTransform(ref));
	assert.deepEqual([line.startPoint.x, line.startPoint.y, line.endPoint.x, line.endPoint.y], [100, 120, 80, 100]);
	const attr = new AcDbAttribute(); attr.position = new AcGePoint3d(10, 0, 0); ref.appendAttributes(attr); attr.transformBy(blockTransform(ref));
	assert.deepEqual([attr.position.x, attr.position.y], [100, 120]);
});

test('block definition and insert attributes survive DXF round trip', async () => {
	const { AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord, AcDbDatabase, AcDbFileType, AcDbLine, AcGePoint3d } = await load();
	const db = new AcDbDatabase();
	const block = new AcDbBlockTableRecord({ name: 'ROUNDTRIP', origin: new AcGePoint3d(0, 0, 0) });
	block.appendEntity(new AcDbLine(new AcGePoint3d(0, 0, 0), new AcGePoint3d(5, 0, 0)));
	const def = new AcDbAttributeDefinition(); def.tag = 'CODE'; def.prompt = 'Code'; def.textString = 'default'; def.position = new AcGePoint3d(1, 1, 0); def.height = 2; block.appendEntity(def);
	const tx = db.transactionManager.startTransaction(); db.tables.blockTable.add(block); tx.commit();
	const ref = new AcDbBlockReference('ROUNDTRIP'); ref.position = new AcGePoint3d(12, 13, 0); ref.scaleFactors = new AcGePoint3d(2, 3, 1); ref.rotation = Math.PI / 4;
	const attr = new AcDbAttribute(); attr.tag = 'CODE'; attr.textString = 'A-42'; attr.position = new AcGePoint3d(10, 10, 0); attr.height = 2; ref.appendAttributes(attr);
	const tx2 = db.transactionManager.startTransaction(); db.tables.blockTable.modelSpace.appendEntity(ref); tx2.commit();
	const out = db.dxfOut(undefined, 6); const text = typeof out === 'string' ? out : new TextDecoder().decode(out);
	const reread = new AcDbDatabase(); await reread.read(text, { readOnly: false }, AcDbFileType.DXF);
	const roundBlock = reread.tables.blockTable.getAt('ROUNDTRIP'); assert.ok(roundBlock);
	const roundRef = reread.tables.blockTable.modelSpace.newIterator().toArray().find(e => e instanceof AcDbBlockReference); assert.ok(roundRef);
	assert.deepEqual([roundRef.position.x, roundRef.position.y, roundRef.scaleFactors.x, roundRef.scaleFactors.y, roundRef.rotation], [12, 13, 2, 3, Math.PI / 4]);
	assert.equal(Array.from(roundRef.attributeIterator())[0]?.textString, 'A-42');
	assert.ok(Array.from(roundBlock.newIterator()).some(e => e instanceof AcDbAttributeDefinition));
});
