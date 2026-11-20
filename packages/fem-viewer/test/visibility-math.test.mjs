import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
	const dir = await mkdtemp(path.join(tmpdir(), 'fem-vis-'));
	const outfile = path.join(dir, 'visibilityMath.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/visibilityMath.ts', 'utf8'), sourcefile: 'visibilityMath.ts', loader: 'ts' },
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	const mod = await import(pathToFileURL(outfile).href);
	return { mod, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

const ELEMENTS = [
	{ id: 'C1', category: 'column' },
	{ id: 'C2', category: 'column' },
	{ id: 'B1', category: 'beam' },
	{ id: 'S1', category: 'slab' },
];

test('temporary HH, HI, HC, IC, HR transitions and permanent hide survival', async () => {
	const { mod, cleanup } = await load();
	try {
		let state = mod.emptyVisibilityState();
		state = mod.hideElementsPermanent(state, ['S1']);
		state = mod.hideElementsTemp(state, ['B1']);

		let vis = mod.computeElementVisibility(ELEMENTS, state);
		assert.deepEqual([...vis.hidden], ['B1', 'S1']);

		// HR resets temporary hides, keeps permanent hide S1.
		state = mod.resetTemporaryVisibility(state);
		vis = mod.computeElementVisibility(ELEMENTS, state);
		assert.deepEqual([...vis.hidden], ['S1']);

		// Isolate category 'column' (IC).
		state = mod.isolateCategoriesTemp(state, ['column']);
		vis = mod.computeElementVisibility(ELEMENTS, state);
		assert.deepEqual([...vis.hidden], ['B1', 'S1']);

		// Hide category 'column' (HC) while S1 is permanently hidden.
		state = mod.resetTemporaryVisibility(state);
		state = mod.hideCategoriesTemp(state, ['column']);
		vis = mod.computeElementVisibility(ELEMENTS, state);
		assert.deepEqual([...vis.hidden], ['C1', 'C2', 'S1']);

		// Isolate element C1 (HI): hides C2, B1, S1.
		state = mod.resetTemporaryVisibility(state);
		state = mod.isolateElementsTemp(state, ['C1']);
		vis = mod.computeElementVisibility(ELEMENTS, state);
		assert.deepEqual([...vis.hidden], ['C2', 'B1', 'S1']);
	} finally {
		await cleanup();
	}
});

test('revealHidden highlights user-hidden elements while external filters stay hidden', async () => {
	const { mod, cleanup } = await load();
	try {
		let state = mod.emptyVisibilityState();
		state = mod.hideElementsPermanent(state, ['B1', 'S1']);
		state = { ...state, revealHidden: true };
		const externalHidden = new Set(['S1']); // e.g. story filter or hidden legend layer

		const vis = mod.computeElementVisibility(ELEMENTS, state, externalHidden);
		assert.deepEqual([...vis.hidden], ['S1']);
		assert.deepEqual([...vis.revealed], ['B1']);

		// Unhide B1 permanently.
		state = mod.unhideElementsPermanent(state, ['B1']);
		const vis2 = mod.computeElementVisibility(ELEMENTS, state, externalHidden);
		assert.deepEqual([...vis2.hidden], ['S1']);
		assert.deepEqual([...vis2.revealed], []);

		// Apply temporary isolate to permanent.
		state = mod.isolateElementsTemp(state, ['C1']);
		state = mod.applyTemporaryToPermanent(state, ELEMENTS);
		const summary = mod.summarizeVisibility(state);
		assert.equal(summary.hasTemporary, false);
		assert.ok(state.permanentHiddenElements.includes('C2'));
		assert.ok(state.permanentHiddenElements.includes('B1'));
	} finally {
		await cleanup();
	}
});
