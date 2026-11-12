/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import * as cp from 'child_process';
import { promises as fs } from 'fs';
import * as os from 'os';
import * as path from '../../../../../base/common/path.js';
import type { MessageConnection } from 'vscode-jsonrpc/node.js';
import { IActionStep, IBatchResult, minimalEdit, readBatchResult, readCatalogue } from '../../common/saengineActions.js';

/*
 * The real engine through the RPC, as the app uses it: `python -m saengine.rpc` (JSON-RPC over
 * stdio, as the desktop backend starts it), `actions/list` and `actions/run` with the app's
 * protocol: edits worked out on the documents as the engineer sees them (overrides), applied to
 * the documents as one small edit each and saved; runs written by the engine after saving. Builds
 * a 3-storey RC frame from an empty folder to Run All.
 *
 * Needs a Python with saengine's packages: set SAENGINE_TEST_PYTHON to it, and
 * SAENGINE_TEST_PYTHONPATH to the source folders to put first on its path (separated by the
 * platform's path separator; it also works with the setup's embedded Python, which ignores
 * PYTHONPATH). Skipped without it, so CI's node tests do not need Python.
 */

const PYTHON = process.env.SAENGINE_TEST_PYTHON;
const PYTHON_PATH = (process.env.SAENGINE_TEST_PYTHONPATH ?? '').split(path.delimiter).filter(p => !!p);

(PYTHON ? suite : suite.skip)('SAEngine - Actions through the engine (integration)', function () {

	this.timeout(15 * 60 * 1000);

	let child: cp.ChildProcess;
	let connection: MessageConnection;
	let root: string;
	/** The app's open documents: path -> text, and which are unsaved. */
	const documents = new Map<string, string>();
	const unsaved = new Set<string>();

	suiteSetup(async () => {
		const { createMessageConnection, StreamMessageReader, StreamMessageWriter } = await import('vscode-jsonrpc/node.js');
		const start = `import sys, runpy; sys.path[:0] = ${JSON.stringify(PYTHON_PATH)}; runpy.run_module('saengine.rpc', run_name='__main__', alter_sys=True)`;
		child = cp.spawn(PYTHON!, ['-u', '-c', start], { env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true });
		child.stderr?.on('data', chunk => process.env.SAENGINE_TEST_VERBOSE && process.stderr.write(chunk));
		connection = createMessageConnection(new StreamMessageReader(child.stdout!), new StreamMessageWriter(child.stdin!));
		connection.listen();
		root = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'saengine-actions-')), 'Plot 12');
		await fs.mkdir(root);
	});

	suiteTeardown(async () => {
		connection?.dispose();
		child?.kill();
		if (root) {
			await fs.rm(path.dirname(root), { recursive: true, force: true });
		}
	});

	async function run(steps: IActionStep[], write: boolean): Promise<IBatchResult> {
		const overrides: { [file: string]: string } = {};
		for (const file of unsaved) {
			overrides[file] = documents.get(file)!;
		}
		return readBatchResult(await connection.sendRequest('actions/run', { projectRoot: root, steps, overrides: write ? undefined : overrides, write }));
	}

	/** What the app does with an edit batch's answer: one small edit per open document (unsaved), or a new document. */
	async function apply(changes: { readonly [file: string]: string }): Promise<void> {
		for (const [file, text] of Object.entries(changes)) {
			const before = documents.get(file) ?? await fs.readFile(path.join(root, file), 'utf8').catch(() => '');
			const edit = minimalEdit(before, text);
			const after = edit ? before.slice(0, edit.start) + edit.text + before.slice(edit.end) : before;
			assert.strictEqual(after, text);
			documents.set(file, after);
			unsaved.add(file);
		}
	}

	async function save(): Promise<void> {
		for (const file of unsaved) {
			await fs.writeFile(path.join(root, file), documents.get(file)!, 'utf8');
		}
		unsaved.clear();
	}

	test('the catalogue', async () => {
		const catalogue = readCatalogue(await connection.sendRequest('actions/list', {}));
		for (const name of ['project.create', 'grid.set', 'storeys.set', 'columns.place', 'beams.place', 'slabs.place', 'load.area.set', 'foundations.generate', 'run.all', 'results.summary']) {
			assert.ok(catalogue.some(info => info.name === name), name);
		}
		assert.ok(catalogue.every(info => info.paramsSchema && typeof info.paramsSchema === 'object'));
		assert.strictEqual(catalogue.find(info => info.name === 'run.all')?.kind, 'run');
	});

	test('a 3-storey frame from an empty folder to Run All', async () => {
		const created = await run([{ action: 'project.create', params: { name: 'Plot 12', occupancy: 'residential' } }], true);
		assert.ok(created.ok, JSON.stringify(created.results));

		// The engineer typed in the settings meanwhile (unsaved): the batch keeps it.
		const settingsFile = Object.keys(created.changes).find(file => file.endsWith('project-settings.json'))!;
		assert.ok(settingsFile, Object.keys(created.changes).join(', '));
		const typed = JSON.parse(await fs.readFile(path.join(root, settingsFile), 'utf8'));
		typed.project = { ...typed.project, engineer: 'Typed, not saved' };
		documents.set(settingsFile, JSON.stringify(typed, undefined, '\t') + '\n');
		unsaved.add(settingsFile);

		const model: IActionStep[] = [
			{ action: 'settings.site', params: { location: 'dhaka', siteClass: 'SD' } },
			{ action: 'grid.set', params: { x: [6000, 6000, 6000], y: [5000, 5000] } },
			{ action: 'storeys.set', params: { count: 3, height: 3000, typical: true } },
			{ action: 'columns.place', params: { type: 'C400x400', points: 'all', storeys: 'all' } },
			{ action: 'beams.place', params: { type: 'B250x450', between: 'all', storeys: 'all' } },
			{ action: 'slabs.place', params: { type: 'S125', panels: 'all', storeys: 'all' } },
			{ action: 'foundations.generate', params: {} },
		];

		// A storey of 30 m is refused: nothing changes and the problem names the value.
		const refused = await run([...model.slice(0, 2), { action: 'storeys.set', params: { count: 3, height: 30000 } }], false);
		assert.strictEqual(refused.ok, false);
		assert.strictEqual(refused.failedStep, 2);
		assert.deepStrictEqual(refused.changes, {});
		assert.ok(refused.results[2].problems.length, JSON.stringify(refused.results[2]));

		const built = await run(model, false);
		assert.ok(built.ok, JSON.stringify(built.results));
		assert.ok(built.results[3].created.length >= 12, JSON.stringify(built.results[3]));
		await apply(built.changes);
		assert.strictEqual(JSON.parse(documents.get(settingsFile)!).project.engineer, 'Typed, not saved');

		const summary = await run([{ action: 'project.summary' }], false);
		assert.ok(summary.ok && summary.results[0].data, JSON.stringify(summary.results));

		// Run All: the app saves, the engine runs and writes.
		await save();
		const ran = await run([{ action: 'run.all' }], true);
		assert.ok(ran.ok, JSON.stringify(ran.results));
		const results = await run([{ action: 'results.summary' }], false);
		assert.ok(results.ok && results.results[0].data, JSON.stringify(results.results));
	});
});
