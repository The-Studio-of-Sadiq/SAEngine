/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { test } from 'node:test';

// Every command SAEngine registers has a description for the command line's suggestions, or the
// library shows its message key (command.USER.<name>.description).
test('every registered command has a description', async () => {
	const table = await readFile('src/commandDescriptions.ts', 'utf8');
	const described = new Set([...table.matchAll(/^\t'?([-A-Z_]+)'?: '/gm)].map(m => m[1]));
	const registered = new Set();
	for (const file of await readdir('src')) {
		if (!file.endsWith('.ts')) {
			continue;
		}
		const text = await readFile(`src/${file}`, 'utf8');
		for (const m of text.matchAll(/(?:registerCommand|registerFn|reg|register)\(\s*'([-A-Z_]+)'/g)) {
			registered.add(m[1]);
		}
	}
	const missing = [...registered].filter(name => !described.has(name)).sort();
	assert.deepEqual(missing, []);
});
