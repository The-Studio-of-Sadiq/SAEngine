/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/
// @ts-check

/**
 * Drives an installed SAEngine window over the Chrome DevTools Protocol (smoke-test.ps1 starts
 * it with --remote-debugging-port). Run from the workbench folder, whose node_modules provides
 * 'chrome-remote-interface':
 *   node smoke-app.mjs <port> <install dir>
 *
 * Checks, in the real renderer of the packaged app:
 *   1. the workbench starts;
 *   2. the FEM viewer bundle loads from node_modules.asar (the URL the workbench imports);
 *   3. "SAEngine: Check Python Runtime" finds the bundled Python and its backend answers.
 * Prints one line per check; exits with 1 on the first failure.
 */

import { createRequire } from 'module';
import path from 'path';

const require = createRequire(path.join(process.cwd(), 'package.json'));
const CDP = require('chrome-remote-interface');

const [portText, installDir] = process.argv.slice(2);
const port = Number(portText);
if (!port || !installDir) {
	console.error('usage: node smoke-app.mjs <port> <install dir>');
	process.exit(2);
}

/** @param {number} ms */
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

/**
 * @param {() => Promise<boolean>} condition
 * @param {number} timeoutMs
 * @param {string} what
 */
async function waitFor(condition, timeoutMs, what) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		try {
			if (await condition()) {
				return;
			}
		} catch {
			// not ready yet
		}
		await sleep(500);
	}
	throw new Error(`timed out after ${timeoutMs / 1000} s waiting for ${what}`);
}

/** @type {any} */
let target;
await waitFor(async () => {
	const targets = await CDP.List({ port });
	target = targets.find((/** @type {any} */ t) => t.type === 'page' && /workbench\.html/.test(t.url));
	return !!target;
}, 90_000, 'the workbench window');

const client = await CDP({ port, target });
const { Runtime, Input } = client;

/** @param {string} expression */
async function evaluate(expression) {
	const { result, exceptionDetails } = await Runtime.evaluate({ expression, awaitPromise: true, returnByValue: true });
	if (exceptionDetails) {
		throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
	}
	return result.value;
}

/** @param {string} key @param {string} code @param {number} keyCode */
async function press(key, code, keyCode) {
	await Input.dispatchKeyEvent({ type: 'keyDown', key, code, windowsVirtualKeyCode: keyCode });
	await Input.dispatchKeyEvent({ type: 'keyUp', key, code, windowsVirtualKeyCode: keyCode });
}

let failed = false;
try {
	const started = Date.now();
	await waitFor(() => evaluate(`!!document.querySelector('.monaco-workbench .part.statusbar')`), 90_000, 'the workbench to render');
	console.log(`ok      workbench rendered (${((Date.now() - started) / 1000).toFixed(1)} s after the window appeared)`);

	const appRoot = path.join(installDir, 'resources', 'app').replace(/\\/g, '/');
	const viewerUrl = `vscode-file://vscode-app/${appRoot}/node_modules.asar/@saengine/fem-viewer/dist/fem-viewer.js`;
	const exports = await evaluate(`import(${JSON.stringify(viewerUrl)}).then(m => Object.keys(m).length)`);
	if (!(exports > 0)) {
		throw new Error(`the FEM viewer bundle loaded without exports from ${viewerUrl}`);
	}
	console.log(`ok      FEM viewer bundle imports from node_modules.asar (${exports} exports)`);

	// The SAEngine start page opens as a modal over the workbench and keeps the keyboard focus:
	// close it first (Escape), or the command palette never receives the command text.
	await sleep(2000);
	await press('Escape', 'Escape', 27);
	await sleep(500);
	await evaluate(`document.querySelector('.monaco-workbench').focus(), true`);
	await press('F1', 'F1', 112);
	await waitFor(() => evaluate(`!!document.querySelector('.quick-input-widget input:focus')`), 15_000, 'the command palette');
	await Input.insertText({ text: 'Check Python Runtime' });
	await waitFor(async () => /Check Python Runtime/.test(await evaluate(`document.querySelector('.quick-input-list .monaco-list-row')?.textContent ?? ''`)), 15_000, 'the Check Python Runtime command in the palette');
	await press('Enter', 'Enter', 13);
	/** @type {string} */
	let message = '';
	await waitFor(async () => {
		message = await evaluate(`[...document.querySelectorAll('.notification-list-item-message')].map(e => e.textContent).join(' | ')`);
		return /SAEngine backend ready|backend is not available/.test(message);
	}, 120_000, 'the runtime check notification');
	if (!/SAEngine backend ready/.test(message)) {
		throw new Error(`Check Python Runtime: ${message}`);
	}
	const expected = path.join(installDir, 'resources', 'python', 'python.exe').toLowerCase();
	if (!message.toLowerCase().includes(expected)) {
		throw new Error(`the runtime check did not use the bundled Python ${expected}: ${message}`);
	}
	console.log(`ok      ${message}`);
} catch (error) {
	failed = true;
	console.error(`FAILED  ${error instanceof Error ? error.message : String(error)}`);
} finally {
	await client.close();
}
process.exit(failed ? 1 : 0);
