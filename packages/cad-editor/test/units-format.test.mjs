import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { readFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { threeExamples, trustedTypes } from '../plugins.mjs';

const rootDir = path.resolve(import.meta.dirname, '..');
const srcDir = path.resolve(rootDir, 'src');

async function loadFormat() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-units-format-')), 'unitsFormat.mjs');
	await esbuild.build({
		stdin: {
			contents: await readFile(path.join(srcDir, 'unitsFormat.ts'), 'utf8'),
			sourcefile: 'unitsFormat.ts',
			loader: 'ts',
			resolveDir: rootDir,
		},
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

async function loadDataModel() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-editor-test-')), 'data-model.mjs');
	await esbuild.build({
		stdin: { contents: "export * from '@mlightcad/data-model';", resolveDir: rootDir },
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

test('formatLength(1234.5678, Decimal, 2) = 1234.57', async () => {
	const { formatLength, LinearUnits } = await loadFormat();
	const formatted = formatLength(1234.5678, LinearUnits.Decimal, 2);
	assert.equal(formatted, '1234.57');
});

test('Architectural 30.5 inches prec 4 (1/16) -> 2\'-6 1/2"', async () => {
	const { formatLength, LinearUnits } = await loadFormat();
	const formatted = formatLength(30.5, LinearUnits.Architectural, 4);
	assert.equal(formatted, "2'-6 1/2\"");
});

test('formatAngle(pi/4, DMS, 4) -> 45d0\'0"', async () => {
	const { formatAngle, AngularUnits } = await loadFormat();
	const formatted = formatAngle(Math.PI / 4, AngularUnits.DegMinSec, 4);
	assert.equal(formatted, "45d0'0\"");
});

test('Surveyor\'s for 30° with ANGBASE 0 CCW -> N 60d E', async () => {
	const { formatAngle, AngularUnits } = await loadFormat();
	const rad30 = 30 * Math.PI / 180;
	const formatted = formatAngle(rad30, AngularUnits.Surveyors, 0, 0, 0);
	assert.equal(formatted, 'N 60d E');
});

test('Scientific format length', async () => {
	const { formatLength, LinearUnits } = await loadFormat();
	const formatted = formatLength(1234.56, LinearUnits.Scientific, 2);
	assert.equal(formatted, '1.23E+03');
});

test('Engineering format length (feet and decimal inches)', async () => {
	const { formatLength, LinearUnits } = await loadFormat();
	const formatted = formatLength(30.5, LinearUnits.Engineering, 2);
	assert.equal(formatted, "2'-6.50\"");
});

test('Fractional format length', async () => {
	const { formatLength, LinearUnits } = await loadFormat();
	const formatted = formatLength(30.5, LinearUnits.Fractional, 4);
	assert.equal(formatted, '30 1/2');
});

test('Angle in Gradians and Radians', async () => {
	const { formatAngle, AngularUnits } = await loadFormat();
	const g = formatAngle(Math.PI / 2, AngularUnits.Grads, 2);
	assert.equal(g, '100.00g');
	const r = formatAngle(Math.PI, AngularUnits.Radians, 3);
	assert.equal(r, '3.142r');
});

test('Drawing sysvars survive DXF round trip', async () => {
	const { AcDbDatabase, AcDbFileType } = await loadDataModel();
	const db = new AcDbDatabase();
	db.insunits = 4; // mm
	db.lunits = 4;   // Architectural
	db.luprec = 4;
	db.aunits = 1;   // DMS
	db.auprec = 2;
	db.angbase = Math.PI / 2; // North base
	db.angdir = 1;   // clockwise

	const dxf = db.dxfOut();
	assert.equal(dxf.includes('$INSUNITS'), true);
	assert.equal(dxf.includes('$LUNITS'), true);
	assert.equal(dxf.includes('$LUPREC'), true);
	assert.equal(dxf.includes('$AUNITS'), true);
	assert.equal(dxf.includes('$AUPREC'), true);
	assert.equal(dxf.includes('$ANGBASE'), true);
	assert.equal(dxf.includes('$ANGDIR'), true);

	const db2 = new AcDbDatabase();
	await db2.read(dxf, { readOnly: false }, AcDbFileType.DXF);
	assert.equal(db2.insunits, 4);
	assert.equal(db2.lunits, 4);
	assert.equal(db2.luprec, 4);
	assert.equal(db2.aunits, 1);
	assert.equal(db2.auprec, 2);
	assert.ok(db2.angbase === 90 || Math.abs(db2.angbase - Math.PI / 2) < 1e-3);
	assert.equal(db2.angdir, 1);
});
