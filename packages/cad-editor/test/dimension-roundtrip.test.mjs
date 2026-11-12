// Round-trips linear dimensions through mlightcad's data model, with SAEngine's patches applied.
// Input: test/fixtures/dimensions.dxf, written by ezdxf (rotated 0°, rotated 90°, aligned).
import assert from 'node:assert/strict';
import { readFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { threeExamples, trustedTypes } from '../plugins.mjs';

async function loadDataModel() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-editor-test-')), 'data-model.mjs');
	await esbuild.build({
		stdin: { contents: "export * from '@mlightcad/data-model';", resolveDir: process.cwd() },
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
		define: { define: 'undefined' },
		plugins: [trustedTypes, threeExamples],
	});
	return import(pathToFileURL(outfile).href);
}

/** Group-code pairs of every DIMENSION entity in DXF text. */
function dimensions(dxf) {
	const lines = dxf.split(/\r?\n/);
	const pairs = [];
	for (let i = 0; i + 1 < lines.length; i += 2) {
		pairs.push([lines[i].trim(), lines[i + 1].trim()]);
	}
	const result = [];
	for (let i = 0; i < pairs.length; i++) {
		if (pairs[i][0] === '0' && pairs[i][1] === 'DIMENSION') {
			const entity = [];
			for (let j = i + 1; j < pairs.length && pairs[j][0] !== '0'; j++) {
				entity.push(pairs[j]);
			}
			result.push(entity);
		}
	}
	return result;
}

const point = (entity, code) => [code, code + 10].map(c => Number(entity.find(([k]) => k === String(c))?.[1]));
const markers = entity => entity.filter(([k]) => k === '100').map(([, v]) => v);

test('linear dimensions keep their extension-line points through load and save', async () => {
	const { AcDbDatabase, AcDbFileType } = await loadDataModel();
	const input = await readFile(new URL('./fixtures/dimensions.dxf', import.meta.url), 'utf8');
	const database = new AcDbDatabase();
	await database.read(input, { readOnly: false }, AcDbFileType.DXF);
	const output = database.dxfOut(undefined, 6);
	const text = typeof output === 'string' ? output : new TextDecoder().decode(output);

	const saved = dimensions(text).map(d => ({ markers: markers(d).slice(2), p13: point(d, 13), p14: point(d, 14) }));
	assert.deepEqual(saved, [
		{ markers: ['AcDbAlignedDimension', 'AcDbRotatedDimension'], p13: [0, 0], p14: [6000, 0] },
		{ markers: ['AcDbAlignedDimension', 'AcDbRotatedDimension'], p13: [0, 0], p14: [0, 5000] },
		{ markers: ['AcDbAlignedDimension'], p13: [0, 0], p14: [3000, 4000] },
	]);
});
