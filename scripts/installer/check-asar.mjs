/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/
// @ts-check

/**
 * Checks that files are present in a packaged app's node_modules.asar.
 * Usage (from the workbench folder, whose node_modules provides the 'asar' package):
 *   node check-asar.mjs <path to node_modules.asar> <path inside the archive>...
 * Exits with 1 and names the missing files when any is absent.
 */

import { createRequire } from 'module';
import path from 'path';

const require = createRequire(path.join(process.cwd(), 'package.json'));
const asar = require('asar');

const [archive, ...expected] = process.argv.slice(2);
if (!archive || expected.length === 0) {
	console.error('usage: node check-asar.mjs <node_modules.asar> <path inside the archive>...');
	process.exit(2);
}

const listed = new Set(asar.listPackage(archive).map((/** @type {string} */ entry) => entry.replace(/\\/g, '/').replace(/^\//, '')));
const missing = expected.filter(file => !listed.has(file));
for (const file of expected) {
	console.log(`${missing.includes(file) ? 'MISSING' : 'ok     '} ${file}`);
}
if (missing.length > 0) {
	console.error(`${archive} lacks ${missing.length} file(s): the SAEngine viewers would not load in the packaged app.`);
	process.exit(1);
}
