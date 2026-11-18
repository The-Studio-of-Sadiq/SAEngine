import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-pick-drafting-')), 'pick-drafting.mjs');
	await esbuild.build({
		stdin: {
			contents: `
				export * from '@mlightcad/data-model';
				export * from './src/selectionGeometry.ts';
				export { applyGenerated } from './src/generated.ts';
			`,
			resolveDir: process.cwd(),
		},
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' },
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

test('pickDrafting and pickDraftingWindow return user line and exclude overlapping generated entity', async () => {
	const m = await load();
	const db = new m.AcDbDatabase();
	m.acdbHostApplicationServices().workingDatabase = db;

	// User drafting line on layer 'DRAFT'
	const userLine = new m.AcDbLine(new m.AcGePoint3d(0, 0, 0), new m.AcGePoint3d(100, 0, 0));
	userLine.layer = 'DRAFT';
	db.tables.blockTable.modelSpace.appendEntity(userLine);
	const userLineId = String(userLine.objectId);

	// Overlapping generated entity on locked/generated layer 'S-BEAM'
	const generatedDrawing = {
		layers: [{ name: 'S-BEAM', color: 3 }],
		entities: [{ kind: 'line', layer: 'S-BEAM', start: [0, 0], end: [100, 0] }],
	};
	const generatedIds = m.applyGenerated(db, new Set(), generatedDrawing);
	const generatedLayers = new Set(['S-BEAM']);

	// 1. Point pick within tolerance of overlapping lines (point at [50, 2], tolerance 5)
	const pickPoint = [50, 2];
	const pickedWithDb = m.pickDrafting(db, pickPoint, 5, { generated: generatedIds, generatedLayers });
	assert.deepEqual(pickedWithDb, [userLineId], 'pickDrafting with db must return user line and exclude generated');

	// Also test pickDrafting using workingDatabase
	const pickedImplicit = m.pickDrafting(pickPoint, 5, { generated: generatedIds, generatedLayers });
	assert.deepEqual(pickedImplicit, [userLineId], 'pickDrafting with workingDatabase must return user line and exclude generated');

	// Point outside tolerance should return empty
	const farPick = m.pickDrafting(db, [50, 20], 5, { generated: generatedIds, generatedLayers });
	assert.deepEqual(farPick, []);

	// 2. Window selection enclosing both user line and generated line
	const winStart = [-10, -10];
	const winEnd = [110, 10];
	const winWithDb = m.pickDraftingWindow(db, winStart, winEnd, 'window', { generated: generatedIds, generatedLayers });
	assert.deepEqual(winWithDb, [userLineId], 'pickDraftingWindow (window) must return user line and exclude generated');

	// Implicit workingDatabase
	const winImplicit = m.pickDraftingWindow(winStart, winEnd, 'window', { generated: generatedIds, generatedLayers });
	assert.deepEqual(winImplicit, [userLineId], 'pickDraftingWindow implicit workingDatabase must return user line');

	// Crossing selection
	const crossStart = [20, -10];
	const crossEnd = [80, 10];
	const crossWithDb = m.pickDraftingWindow(db, crossStart, crossEnd, 'crossing', { generated: generatedIds, generatedLayers });
	assert.deepEqual(crossWithDb, [userLineId], 'pickDraftingWindow (crossing) must return user line and exclude generated');

	// 3. Nearest-first ordering with multiple user lines
	const nearLine = new m.AcDbLine(new m.AcGePoint3d(0, 1, 0), new m.AcGePoint3d(100, 1, 0));
	nearLine.layer = 'DRAFT';
	const farLine = new m.AcDbLine(new m.AcGePoint3d(0, 4, 0), new m.AcGePoint3d(100, 4, 0));
	farLine.layer = 'DRAFT';
	db.tables.blockTable.modelSpace.appendEntity([nearLine, farLine]);
	const nearId = String(nearLine.objectId);
	const farId = String(farLine.objectId);

	// Pick at [50, 0.9]: nearLine is at dist 0.1, userLine at dist 0.9, farLine at dist 3.1
	const multiPick = m.pickDrafting(db, [50, 0.9], 5, { generated: generatedIds, generatedLayers });
	assert.equal(multiPick[0], nearId, 'Nearest entity must be first');
	assert.equal(multiPick[1], userLineId, 'Second nearest entity must be second');
	assert.equal(multiPick[2], farId, 'Third nearest entity must be third');

	// 4. Locked layer exclusion
	const lockedLayer = new m.AcDbLayerTableRecord({ name: 'LOCKED', standardFlags: 0x04 });
	lockedLayer.isLocked = true;
	db.tables.layerTable.add(lockedLayer);
	const lockedLine = new m.AcDbLine(new m.AcGePoint3d(0, 0, 0), new m.AcGePoint3d(100, 0, 0));
	lockedLine.layer = 'LOCKED';
	db.tables.blockTable.modelSpace.appendEntity(lockedLine);
	const lockedHits = m.pickDrafting(db, [50, 0], 5, { generated: generatedIds, generatedLayers });
	assert.ok(!lockedHits.includes(String(lockedLine.objectId)), 'Entities on locked layers must not be picked');
});
