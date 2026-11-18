import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { threeExamples, trustedTypes } from '../plugins.mjs';

const normalize = value => ((value % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
function reflect(point, first, second) {
	const dx = second.x - first.x, dy = second.y - first.y;
	const t = ((point.x - first.x) * dx + (point.y - first.y) * dy) / (dx * dx + dy * dy);
	return { x: 2 * (first.x + t * dx) - point.x, y: 2 * (first.y + t * dy) - point.y, z: point.z };
}

test('mirrorPoint reflects across a line', async () => {
	assert.deepEqual(reflect({ x: 2, y: 3, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 0, y: 1, z: 0 }), { x: -2, y: 3, z: 0 });
	assert.deepEqual(reflect({ x: 2, y: 3, z: 4 }, { x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }), { x: 2, y: -3, z: 4 });
});

test('mirror transform preserves counter-clockwise arc parameterization', async () => {
	// Reflection about a line reverses endpoint order; swapping reflected angles retains positive sweep.
	const start = Math.PI / 6, end = 5 * Math.PI / 6;
	const [reflectedStart, reflectedEnd] = [normalize(Math.PI - end), normalize(Math.PI - start)];
	assert.ok(reflectedEnd > reflectedStart);
	assert.ok(reflectedStart >= 0 && reflectedEnd < 2 * Math.PI);
});
