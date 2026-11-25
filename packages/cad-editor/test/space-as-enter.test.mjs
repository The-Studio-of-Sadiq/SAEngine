import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
	const outfile = path.join(await mkdtemp(path.join(tmpdir(), 'cad-space-')), 'space.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/spaceAsEnter.ts', 'utf8'), sourcefile: 'spaceAsEnter.ts', loader: 'ts' },
		outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'error',
	});
	return import(pathToFileURL(outfile).href);
}

test('Space acts as Enter in the drawing and its dynamic input, not in text editors or with modifiers', async () => {
	const { spaceActsAsEnter, installSpaceAsEnter } = await load();
	const base = { key: ' ', inDrawing: true, inTextEditor: false };
	assert.deepEqual([
		spaceActsAsEnter(base),
		spaceActsAsEnter({ ...base, key: 'a' }),
		spaceActsAsEnter({ ...base, ctrlKey: true }),
		spaceActsAsEnter({ ...base, isComposing: true }),
		spaceActsAsEnter({ ...base, inDrawing: false }),
		spaceActsAsEnter({ ...base, inTextEditor: true }),
	], [true, false, false, false, false, false]);
	// Without a window (node) installing is a no-op that can be undone twice.
	const restore = installSpaceAsEnter();
	restore();
	restore();
});
