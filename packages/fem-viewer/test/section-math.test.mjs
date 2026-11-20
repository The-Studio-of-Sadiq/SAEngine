import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
	const dir = await mkdtemp(path.join(tmpdir(), 'fem-section-'));
	const outfile = path.join(dir, 'sectionMath.mjs');
	await esbuild.build({
		stdin: { contents: await readFile('src/sectionMath.ts', 'utf8'), sourcefile: 'sectionMath.ts', loader: 'ts' },
		outfile,
		bundle: true,
		format: 'esm',
		platform: 'node',
		logLevel: 'error',
	});
	const mod = await import(pathToFileURL(outfile).href);
	return { mod, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

test('boxToClipPlanes keeps interior points and rejects points outside every face', async () => {
	const { mod, cleanup } = await load();
	try {
		const box = { minX: -2, maxX: 5, minY: 0, maxY: 8, minZ: -3, maxZ: 4 };
		const planes = mod.boxToClipPlanes(box);
		assert.equal(planes.length, 6);
		assert.equal(mod.isPointInClipPlanes([1, 4, 0], planes), true);
		assert.equal(mod.isPointInClipPlanes([-2, 0, -3], planes), true);
		assert.equal(mod.isPointInClipPlanes([-2.1, 4, 0], planes), false);
		assert.equal(mod.isPointInClipPlanes([5.1, 4, 0], planes), false);
		assert.equal(mod.isPointInClipPlanes([1, -0.1, 0], planes), false);
		assert.equal(mod.isPointInClipPlanes([1, 8.1, 0], planes), false);
		assert.equal(mod.isPointInClipPlanes([1, 4, -3.1], planes), false);
		assert.equal(mod.isPointInClipPlanes([1, 4, 4.1], planes), false);
	} finally {
		await cleanup();
	}
});

test('moveFace prevents inversion across opposite face', async () => {
	const { mod, cleanup } = await load();
	try {
		const box = { minX: 0, maxX: 10, minY: 0, maxY: 10, minZ: 0, maxZ: 10 };
		const movedMin = mod.moveFace(box, 'minX', 15, 0.5);
		assert.equal(movedMin.minX, 9.5);
		assert.equal(movedMin.maxX, 10);
		const movedMax = mod.moveFace(box, 'maxY', -4, 0.5);
		assert.equal(movedMax.maxY, 0.5);
		assert.equal(movedMax.minY, 0);
	} finally {
		await cleanup();
	}
});

test('padBox and dragAxisParameter compute exact face shifts', async () => {
	const { mod, cleanup } = await load();
	try {
		const padded = mod.padBox({ minX: 1, maxX: 3, minY: 2, maxY: 6, minZ: -1, maxZ: 5 }, 0.5);
		assert.deepEqual(padded, { minX: 0.5, maxX: 3.5, minY: 1.5, maxY: 6.5, minZ: -1.5, maxZ: 5.5 });

		// Ray from (3, 4, 0) along (1/sqrt(2), -1/sqrt(2), 0) crosses X axis at x = 7.
		const s = Math.SQRT1_2;
		const t = mod.dragAxisParameter([3, 4, 0], [s, -s, 0], [0, 0, 0], [1, 0, 0]);
		assert.ok(t !== undefined && Math.abs(t - 7) < 1e-9);

		// Parallel ray returns undefined.
		assert.equal(mod.dragAxisParameter([0, 2, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]), undefined);
	} finally {
		await cleanup();
	}
});

test('flipPlaneSpec reverses kept half-space', async () => {
	const { mod, cleanup } = await load();
	try {
		const plane = { id: 'p1', normal: [0, 1, 0], point: [0, 3, 0], axis: 'y', flipped: false };
		const eq1 = mod.planeSpecToEquation(plane);
		assert.equal(mod.isPointInClipPlanes([0, 5, 0], [eq1]), true);
		assert.equal(mod.isPointInClipPlanes([0, 1, 0], [eq1]), false);

		const flipped = mod.flipPlaneSpec(plane);
		const eq2 = mod.planeSpecToEquation(flipped);
		assert.equal(flipped.flipped, true);
		assert.equal(mod.isPointInClipPlanes([0, 5, 0], [eq2]), false);
		assert.equal(mod.isPointInClipPlanes([0, 1, 0], [eq2]), true);
	} finally {
		await cleanup();
	}
});

test('projectBoxToScene and sceneBoxToProject round-trip with Y/-Z swap and offset', async () => {
	const { mod, cleanup } = await load();
	try {
		const scale = 0.001;
		const offset = [1.5, -0.5, 2.2];
		const boxMm = { minX: 1000, maxX: 6000, minY: 2000, maxY: 9000, minZ: -3000, maxZ: 12000 };
		const scene = mod.projectBoxToScene(boxMm, scale, offset);
		assert.ok(Math.abs(scene.minX - 2.5) < 1e-9);
		assert.ok(Math.abs(scene.maxX - 7.5) < 1e-9);
		assert.ok(Math.abs(scene.minY - (-3.5)) < 1e-9);
		assert.ok(Math.abs(scene.maxY - 11.5) < 1e-9);
		assert.ok(Math.abs(scene.minZ - (2.2 - 9)) < 1e-9);
		assert.ok(Math.abs(scene.maxZ - (2.2 - 2)) < 1e-9);

		const back = mod.sceneBoxToProject(scene, scale, offset);
		for (const key of ['minX', 'maxX', 'minY', 'maxY', 'minZ', 'maxZ']) {
			assert.ok(Math.abs(back[key] - boxMm[key]) < 1e-6);
		}

		const specMm = { id: 'p1', normal: [0, 1, 0], point: [3000, 4000, 1500], axis: 'y', flipped: false };
		const specScene = mod.projectPlaneToScene(specMm, scale, offset);
		const specBack = mod.scenePlaneToProject(specScene, scale, offset);
		assert.ok(Math.abs(specBack.normal[1] - 1) < 1e-9);
		assert.ok(Math.abs(specBack.point[0] - 3000) < 1e-6);
		assert.ok(Math.abs(specBack.point[1] - 4000) < 1e-6);
		assert.ok(Math.abs(specBack.point[2] - 1500) < 1e-6);
	} finally {
		await cleanup();
	}
});
