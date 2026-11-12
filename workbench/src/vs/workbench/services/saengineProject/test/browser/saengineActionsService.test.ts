/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { VSBuffer } from '../../../../../base/common/buffer.js';
import { CancellationTokenSource } from '../../../../../base/common/cancellation.js';
import { Schemas } from '../../../../../base/common/network.js';
import { joinPath } from '../../../../../base/common/resources.js';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { ACTIONS_CANCEL_COMMAND, ACTIONS_RUN_COMMAND, describeFailure, IActionsRunRequest, minimalEdit, readBatchResult, readCatalogue, readSteps } from '../../common/saengineActions.js';
import { actionsWindow, DESIGN_SUMMARY, FLOOR_PLAN_FILE, readText, SETTINGS_FILE, writeText } from './actionsFixture.js';

suite('SAEngine - Actions service', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	const emptyPlan = { schema: 1, grids: { x: [], y: [] }, stories: [], columns: [], beams: [], slabs: [], footings: [], loads: {} };

	async function openProject() {
		const window = await actionsWindow(store, { project: true });
		await writeText(window, SETTINGS_FILE, { schema: 1, project: { name: 'Plot' }, site: {} });
		await writeText(window, FLOOR_PLAN_FILE, emptyPlan);
		return window;
	}

	function lastRun(window: Awaited<ReturnType<typeof openProject>>): IActionsRunRequest {
		return window.engine.requests.filter(r => r.command === ACTIONS_RUN_COMMAND).at(-1)!.args as IActionsRunRequest;
	}

	test('the catalogue and kinds', async () => {
		const window = await openProject();
		const all = await window.service.listActions();
		assert.ok(all.some(a => a.name === 'grid.set' && a.kind === 'edit' && a.paramsSchema.properties?.x));
		assert.deepStrictEqual((await window.service.listActions('run')).map(a => a.name), ['run.all']);
		assert.strictEqual((await window.service.describe('storeys.set'))?.summary, 'Set the storeys by their heights.');
		assert.strictEqual(await window.service.describe('nope'), undefined);
		assert.strictEqual(await window.service.needsWrite([{ action: 'grid.set' }]), false);
		assert.strictEqual(await window.service.needsWrite([{ action: 'project.summary' }, { action: 'run.all' }]), true);
		// The catalogue is asked once.
		assert.strictEqual(window.engine.requests.filter(r => r.command !== ACTIONS_RUN_COMMAND).length, 1);
	});

	test('edits: the unsaved texts go as overrides, the answer is applied as one undo step and stays unsaved', async () => {
		const window = await openProject();
		const settings = await window.textFiles.open(joinPath(window.root, ...SETTINGS_FILE.split('/')), JSON.stringify({ schema: 1, project: { name: 'Plot (typed)' }, site: {} }, undefined, '\t') + '\n');
		const outcome = await window.service.run([
			{ action: 'settings.site', params: { location: 'dhaka', siteClass: 'SC' } },
			{ action: 'grid.set', params: { x: [6000, 6000], y: [5000] } },
			{ action: 'storeys.set', params: { heights: [3200, 3000, 3000] } },
			{ action: 'columns.place', params: { at: 'all' } },
		], { apply: true });

		assert.strictEqual(outcome.ok, true);
		assert.strictEqual(outcome.ran, false);
		assert.deepStrictEqual([...outcome.applied].sort(), [SETTINGS_FILE, FLOOR_PLAN_FILE].sort());
		assert.deepStrictEqual(outcome.results[3].created, ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']);
		const request = lastRun(window);
		assert.strictEqual(request.write, false);
		// Only the unsaved model is an override; the engine kept the engineer's typing.
		assert.deepStrictEqual(Object.keys(request.overrides ?? {}), [SETTINGS_FILE]);
		assert.strictEqual(JSON.parse(settings.getValue()).project.name, 'Plot (typed)');
		assert.deepStrictEqual(JSON.parse(settings.getValue()).site, { location: 'dhaka', siteClass: 'SC' });
		const plan = window.textModels.models.get(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')))!;
		assert.strictEqual(JSON.parse(plan.getValue()).columns.length, 6);
		// Nothing written: the files on disk are as they were until the engineer saves.
		assert.deepStrictEqual(JSON.parse(await readText(window, FLOOR_PLAN_FILE)), emptyPlan);

		// One undo step reverts both files.
		await window.textModels.undoRedo.undo(plan.uri);
		assert.deepStrictEqual(JSON.parse(plan.getValue()), emptyPlan);
		assert.strictEqual(JSON.parse(settings.getValue()).project.name, 'Plot (typed)');
		assert.deepStrictEqual(JSON.parse(settings.getValue()).site, {});
	});

	test('a failed batch changes nothing and says which value was refused', async () => {
		const window = await openProject();
		const plan = await window.textFiles.open(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')));
		const before = plan.getValue();
		const steps = [
			{ action: 'grid.set', params: { x: [6000], y: [5000] } },
			{ action: 'storeys.set', params: { heights: [3200, 30000] } },
			{ action: 'columns.place', params: { at: 'all' } },
		];
		const outcome = await window.service.run(steps, { apply: true });
		assert.strictEqual(outcome.ok, false);
		assert.strictEqual(outcome.failedStep, 1);
		assert.deepStrictEqual(outcome.applied, []);
		assert.deepStrictEqual(outcome.changes, {});
		assert.strictEqual(plan.getValue(), before);
		assert.strictEqual(window.textModels.undoRedo.canUndo(plan.uri), false);
		assert.strictEqual(describeFailure(steps, outcome), 'Step 2 (storeys.set) failed: The storeys were not set.\n- heights[1] = 30000: a storey height is between 2000 and 6000 mm');
	});

	test('a preview (apply: false) changes nothing', async () => {
		const window = await openProject();
		const plan = await window.textFiles.open(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')));
		const outcome = await window.service.run([{ action: 'grid.set', params: { x: [6000], y: [5000] } }], { apply: false });
		assert.strictEqual(outcome.ok, true);
		assert.deepStrictEqual(Object.keys(outcome.changes), [FLOOR_PLAN_FILE]);
		assert.deepStrictEqual(outcome.applied, []);
		assert.deepStrictEqual(JSON.parse(plan.getValue()), emptyPlan);
	});

	test('runs: the project is saved first, the engine writes, the files are read again', async () => {
		const window = await openProject();
		await window.service.run([{ action: 'grid.set', params: { x: [6000], y: [5000] } }, { action: 'columns.place', params: { at: 'all' } }], { apply: true });
		const plan = window.textModels.models.get(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')))!;
		assert.ok(window.textFiles.isDirty(plan.uri));

		const outcome = await window.service.run([{ action: 'run.all' }], { apply: true });
		assert.strictEqual(outcome.ok, true, JSON.stringify(outcome.results));
		assert.strictEqual(outcome.ran, true);
		assert.deepStrictEqual(window.textFiles.saved, [plan.uri.path]);
		const request = lastRun(window);
		assert.strictEqual(request.write, true);
		assert.strictEqual(request.overrides, undefined);
		// The engine read the saved floor plan from disk: 4 columns, no beams.
		assert.deepStrictEqual(JSON.parse(await readText(window, DESIGN_SUMMARY)).checked, 4);
	});

	test('writes decides which batches run on disk, not the action names', async () => {
		const window = await openProject();
		const all = await window.service.listActions();
		assert.deepStrictEqual(all.filter(a => a.writes).map(a => a.name), ['project.create', 'run.all']);
		assert.strictEqual(await window.service.needsWrite([{ action: 'project.create', params: { name: 'Plot' } }]), true);
		// An engine before the flag: its run actions and project.create write.
		const old = readCatalogue([{ name: 'project.create', kind: 'edit' }, { name: 'run.step', kind: 'run' }, { name: 'grid.set', kind: 'edit' }]);
		assert.deepStrictEqual(old.map(a => a.writes), [true, true, false]);
		const flagged = readCatalogue([{ name: 'export.x', kind: 'run', writes: false }]);
		assert.strictEqual(flagged[0].writes, false);
	});

	test('Stop: a cancelled run stops before its next step and says what was done', async () => {
		const window = await openProject();
		const source = new CancellationTokenSource();
		window.engine.onRun = () => source.cancel();
		const outcome = await window.service.run([{ action: 'run.all' }, { action: 'results.summary' }], { apply: true }, source.token);
		source.dispose();
		assert.strictEqual(outcome.ok, false);
		assert.strictEqual(outcome.cancelled, true);
		assert.strictEqual(outcome.failedStep, 0);
		assert.ok(window.engine.requests.some(r => r.command === ACTIONS_CANCEL_COMMAND));
		assert.match(describeFailure([{ action: 'run.all' }], outcome), /^Step 1 \(run\.all\) was stopped: Stopped/);
	});

	test('the files saved before a run step are named, and a failure says they were kept', () => {
		const result = readBatchResult({ ok: false, results: [{ ok: true, message: 'a' }, { ok: false, message: 'No results.', written: ['05 Floor Plan\\floor-plan.json'] }], failed_step: 1, written: ['05 Floor Plan\\floor-plan.json'] });
		assert.deepStrictEqual(result.results[1].written, [FLOOR_PLAN_FILE]);
		assert.strictEqual(result.cancelled, false);
		assert.match(describeFailure([{ action: 'grid.set' }, { action: 'run.all' }], result), /Written before it and kept: 05 Floor Plan\/floor-plan\.json\.$/);
	});

	test('project.create in a window without a folder asks where, creates a subfolder named after the project and opens it', async () => {
		const window = await actionsWindow(store, { project: false, noFolder: true });
		const projects = URI.from({ scheme: Schemas.inMemory, path: '/home/Documents/SAEngine Projects' });
		await window.fileService.createFolder(projects);
		window.host.pick = projects;
		const outcome = await window.service.run([{ action: 'project.create', params: { name: 'Plot 12/A' } }], { apply: true });
		assert.strictEqual(outcome.ok, true, JSON.stringify(outcome.results));
		// The picker opened at Documents/SAEngine Projects.
		assert.strictEqual(window.host.dialogs[0].defaultUri?.path, projects.path);
		assert.strictEqual(window.host.dialogs[0].canSelectFolders, true);
		const folder = joinPath(projects, 'Plot 12-A');
		assert.strictEqual(lastRun(window).projectRoot, folder.fsPath);
		assert.ok(await window.fileService.exists(joinPath(folder, ...SETTINGS_FILE.split('/'))));
		assert.strictEqual(outcome.createdIn, folder.fsPath);
		assert.strictEqual(window.host.opened[0].folderUri?.path, folder.path);
	});

	test('project.create without a folder: cancelling the picker creates nothing, a taken folder is refused', async () => {
		const window = await actionsWindow(store, { project: false, noFolder: true });
		// The in-memory file system outlives a test: make sure Documents is not there.
		const documents = URI.from({ scheme: Schemas.inMemory, path: '/home/Documents' });
		if (await window.fileService.exists(documents)) {
			await window.fileService.del(documents, { recursive: true });
		}
		const cancelled = await window.service.run([{ action: 'project.create', params: { name: 'Plot' } }], { apply: true });
		assert.strictEqual(cancelled.ok, false);
		assert.match(cancelled.results[0].message, /No folder was chosen/);
		// Documents/SAEngine Projects does not exist: the picker opens at the home folder.
		assert.strictEqual(window.host.dialogs[0].defaultUri?.path, '/home');
		const home = URI.from({ scheme: Schemas.inMemory, path: '/home' });
		await window.fileService.writeFile(joinPath(home, 'Plot', 'notes.txt'), VSBuffer.fromString('x'));
		window.host.pick = home;
		await assert.rejects(() => window.service.run([{ action: 'project.create', params: { name: 'Plot' } }], { apply: true }), /exists already and is not empty/);
		assert.deepStrictEqual(window.host.opened, []);
		assert.ok(!window.engine.requests.some(r => r.command === ACTIONS_RUN_COMMAND));
	});

	test('project.create with an empty folder open works in it, as before', async () => {
		const window = await actionsWindow(store, { project: false });
		const outcome = await window.service.run([{ action: 'project.create', params: { name: 'Plot' } }], { apply: true });
		assert.strictEqual(outcome.ok, true);
		assert.strictEqual(lastRun(window).projectRoot, window.root.fsPath);
		assert.deepStrictEqual(window.host.dialogs, []);
		assert.deepStrictEqual(window.host.opened, []);
	});

	test('a change outside the project is refused before anything is applied', async () => {
		const window = await openProject();
		const plan = await window.textFiles.open(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')));
		window.engine.handle = async () => ({ ok: true, results: [{ ok: true, message: 'x' }], changes: { [FLOOR_PLAN_FILE]: '{}\n', '../other/evil.json': '{}' }, failed_step: null });
		await assert.rejects(() => window.service.run([{ action: 'grid.set' }], { apply: true }), /not a file of the project/);
		assert.deepStrictEqual(JSON.parse(plan.getValue()), emptyPlan);
	});

	test('reading the engine', () => {
		assert.deepStrictEqual(readCatalogue({ actions: [{ name: 'a.b', kind: 'query', summary: 's', parts: ['x'], paramsSchema: { type: 'object' } }, { kind: 'edit' }]}), [{ name: 'a.b', kind: 'query', writes: false, summary: 's', parts: ['x'], paramsSchema: { type: 'object' } }]);
		// A refusal of the backend is a failed batch with its message, and never carries changes.
		const refused = readBatchResult({ ok: false, code: 'noProject', message: 'No project at C.' });
		assert.deepStrictEqual([refused.ok, refused.failedStep, refused.results[0].message], [false, 0, 'No project at C.']);
		assert.deepStrictEqual(readBatchResult({ ok: false, results: [{ ok: false, message: 'm', problems: ['plain'] }], changes: { 'a.json': '{}' }, failed_step: 0 }).changes, {});
		assert.deepStrictEqual(readSteps({ steps: [{ action: ' grid.set ' }] }), [{ action: 'grid.set', params: {} }]);
		assert.throws(() => readSteps([]));
		assert.throws(() => readSteps([{ params: {} }]), /step 1 has no "action"/);
	});

	test('the one small edit between two texts', () => {
		const apply = (before: string, after: string) => {
			const edit = minimalEdit(before, after);
			return edit ? before.slice(0, edit.start) + edit.text + before.slice(edit.end) : before;
		};
		for (const [before, after] of [['{"a": 1}', '{"a": 2}'], ['abc', 'abc'], ['', 'x'], ['x', ''], ['a\r\nb', 'a\r\nc\r\nb'], ['aaa', 'aa'], ['😀a', '😃a']]) {
			assert.strictEqual(apply(before, after), after, `${before} -> ${after}`);
		}
		assert.deepStrictEqual(minimalEdit('{"a": 1, "b": 2}', '{"a": 1, "b": 3}'), { start: 14, end: 15, text: '3' });
	});
});
