/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

// Each test bundles its sources into a fresh cad-* folder in the temp directory (about 8 MB).
// They were never removed and filled the disk; remove those older than ten minutes before a run,
// so a run in progress elsewhere keeps its own.
import { readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const cutoff = Date.now() - 10 * 60 * 1000;
let removed = 0;
for (const name of await readdir(tmpdir())) {
	if (!name.startsWith('cad-')) {
		continue;
	}
	const dir = path.join(tmpdir(), name);
	try {
		const info = await stat(dir);
		if (info.isDirectory() && info.mtimeMs < cutoff) {
			await rm(dir, { recursive: true, force: true });
			removed++;
		}
	} catch {
		// Gone already or in use: leave it.
	}
}
if (removed) {
	console.log(`removed ${removed} old test bundle folder(s) from ${tmpdir()}`);
}
