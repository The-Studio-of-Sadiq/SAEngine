import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
	const dir = await mkdtemp(path.join(tmpdir(), 'fem-contour-'));
	const outfile = path.join(dir, 'contourMath.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/contourMath.ts', 'utf8'), sourcefile: 'contourMath.ts', loader: 'ts' },
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	const mod = await import(pathToFileURL(outfile).href);
	return { mod, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

test('corners take the mean of the shells of one member that share the node', async () => {
	const { mod, cleanup } = await load();
	try {
		// Two slab shells side by side (shared edge 2-5) and a wall shell on node 5 too.
		//  1 - 2 - 3
		//  | a | b |
		//  4 - 5 - 6
		const shells = [
			{ name: 'S1', nodes: [1, 2, 5, 4] },
			{ name: 'S1#2', nodes: [2, 3, 6, 5] },
			{ name: 'W1', nodes: [5, 6, 9, 8] },
		];
		const corners = mod.cornerValues(shells, [10, 20, 100]);
		assert.deepEqual(corners[0], [10, 15, 15, 10]);
		assert.deepEqual(corners[1], [15, 20, 20, 15]);
		// The wall is not averaged with the slab it meets.
		assert.deepEqual(corners[2], [100, 100, 100, 100]);
	} finally {
		await cleanup();
	}
});

test('member of a shell is its name before #', async () => {
	const { mod, cleanup } = await load();
	try {
		assert.equal(mod.memberName('S2#14'), 'S2');
		assert.equal(mod.memberName('S2'), 'S2');
		assert.equal(mod.memberName(undefined), '');
	} finally {
		await cleanup();
	}
});
