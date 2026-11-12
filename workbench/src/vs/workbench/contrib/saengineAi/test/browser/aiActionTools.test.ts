/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { VSBuffer } from '../../../../../base/common/buffer.js';
import { CancellationTokenSource } from '../../../../../base/common/cancellation.js';
import { joinPath } from '../../../../../base/common/resources.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { MCP } from '../../../../../platform/mcp/common/modelContextProtocol.js';
import { ActionKind, IActionStep } from '../../../../services/saengineProject/common/saengineActions.js';
import { actionsWindow, DESIGN_SUMMARY, FLOOR_PLAN_FILE, readText, SETTINGS_FILE } from '../../../../services/saengineProject/test/browser/actionsFixture.js';
import { AiActionTools } from '../../browser/aiActionTools.js';
import { IAiChangeSet, SaengineAiChangeSetService } from '../../browser/aiChangeSets.js';
import { diffJson, planFile } from '../../common/aiChangeSet.js';

/** A tool call of the (scripted) model and the tool's answer. */
interface IToolCall { readonly id: string; readonly name: string; readonly args: Record<string, unknown> }
interface IToolAnswer { readonly text: string; readonly isError: boolean }

suite('SAEngine - AI actions', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	async function setup(options: { readonly project: boolean; readonly accept?: boolean }) {
		const window = await actionsWindow(store, { project: options.project });
		const changeSets = store.add(new SaengineAiChangeSetService(window.projectService, window.textModels, window.fileService, window.textModels.undoRedo, window.commandService));
		const engineer = { confirmed: [] as string[][], reviewed: [] as IAiChangeSet[] };
		const tools = new AiActionTools(
			{
				confirmRun: async (steps: readonly IActionStep[]) => { engineer.confirmed.push(steps.map(s => s.action)); return true; },
				showChangeSet: async changeSet => {
					engineer.reviewed.push(changeSet);
					if (options.accept !== false) {
						await changeSets.accept(changeSet.id);
					} else {
						changeSets.reject(changeSet.id);
					}
				},
			},
			100,
			window.service,
			changeSets,
		);
		const run = async (call: IToolCall): Promise<IToolAnswer> => {
			let result: MCP.CallToolResult;
			switch (call.name) {
				case 'list_actions': result = await tools.listActions(call.args.kind as ActionKind | undefined); break;
				case 'describe_action': result = await tools.describeAction(call.args.name as string); break;
				case 'run_actions': result = await tools.runActions(call.args, 'assistant'); break;
				default: throw new Error(call.name);
			}
			const first = result.content[0];
			return { text: first?.type === 'text' ? first.text : '', isError: !!result.isError };
		};
		return { window, changeSets, engineer, tools, run };
	}

	const model = (heights: number[]) => [
		{ action: 'settings.site', params: { location: 'dhaka', siteClass: 'SC' } },
		{ action: 'grid.set', params: { x: [6000, 6000], y: [5000] } },
		{ action: 'storeys.set', params: { heights } },
		{ action: 'columns.place', params: { at: 'all', type: 'C400' } },
		{ action: 'beams.place', params: { along: 'all grid lines' } },
		{ action: 'slabs.place', params: { panels: 'all' } },
		{ action: 'load.area.set', params: { SD: 1.5, L: 2 } },
		{ action: 'foundations.generate', params: {} },
	];

	test('end to end: a scripted model builds a designed 3-storey building in an empty folder', async () => {
		const { window, changeSets, engineer, run } = await setup({ project: false });
		// The model's tool calls, each after reading the answer of the one before.
		const catalogue = await run({ id: '1', name: 'list_actions', args: {} });
		const described = await run({ id: '2', name: 'describe_action', args: { name: 'storeys.set' } });
		await run({ id: '3', name: 'run_actions', args: { title: 'Create the project', steps: [{ action: 'project.create', params: { name: 'Plot 12' } }] } });
		// A storey of 30 m: the guardrail refuses it and nothing changes.
		const refused = await run({ id: '4', name: 'run_actions', args: { title: 'The building', steps: model([3200, 30000, 3000]) } });
		assert.ok(refused.isError && refused.text.includes('heights[1] = 30000: a storey height is between 2000 and 6000 mm'), refused.text);
		await run({ id: '5', name: 'run_actions', args: { title: 'The building', steps: model([3200, 3000, 3000]) } });
		await run({ id: '6', name: 'run_actions', args: { title: 'Run All', steps: [{ action: 'run.all' }] } });
		const summary = JSON.parse((await run({ id: '7', name: 'run_actions', args: { steps: [{ action: 'results.summary' }] } })).text);
		assert.deepStrictEqual([summary.results[0].data.checked, summary.results[0].data.failed, summary.results[0].data.governing], [13, 1, 'B3']);

		// The catalogue and the description reached the model.
		assert.ok(catalogue.text.includes('"storeys.set"') && described.text.includes('"heights"'));
		// The engineer agreed to creating the project and to Run All, and reviewed one change set (the refused batch never reached them).
		assert.deepStrictEqual(engineer.confirmed, [['project.create'], ['run.all']]);
		assert.strictEqual(engineer.reviewed.length, 1);
		const set = engineer.reviewed[0];
		assert.strictEqual(set.title, 'The building');
		assert.strictEqual(set.state, 'accepted');
		assert.deepStrictEqual(set.summary?.slice(0, 3), ['Site: dhaka, site class SC.', 'Grid: 3 x lines, 2 y lines.', '3 storeys.']);
		assert.deepStrictEqual(set.files.map(f => f.file).sort(), [SETTINGS_FILE, FLOOR_PLAN_FILE].sort());
		// Applied through the text models, saved by Run All, then the run's results.
		const plan = JSON.parse(await readText(window, FLOOR_PLAN_FILE));
		assert.deepStrictEqual([plan.stories.length, plan.columns.length, plan.beams.length, plan.slabs.length, plan.footings.length], [3, 6, 7, 2, 6]);
		assert.deepStrictEqual(plan.loads, { SD: 1.5, L: 2 });
		assert.deepStrictEqual(JSON.parse(await readText(window, DESIGN_SUMMARY)), { checked: 13, passed: 12, failed: 1, governing: 'B3' });
		assert.deepStrictEqual(window.textFiles.saved.sort(), [joinPath(window.root, ...SETTINGS_FILE.split('/')).path, joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')).path].sort());
		assert.ok(changeSets.changeSets.length === 1);
	});

	test('rejected edits change nothing; edits and runs are never in one batch', async () => {
		const { window, engineer, run } = await setup({ project: false, accept: false });
		await run({ id: '1', name: 'run_actions', args: { steps: [{ action: 'project.create', params: { name: 'Plot' } }] } });
		const before = await readText(window, FLOOR_PLAN_FILE);

		const rejected = JSON.parse((await run({ id: '2', name: 'run_actions', args: { steps: model([3000, 3000, 3000]) } })).text);
		assert.strictEqual(rejected.decision, 'rejected');
		const planModel = window.textModels.models.get(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')));
		assert.strictEqual(planModel?.getValue(), before);

		const mixed = await run({ id: '3', name: 'run_actions', args: { steps: [{ action: 'grid.set', params: { x: [6000], y: [6000] } }, { action: 'run.all' }] } });
		assert.ok(mixed.isError && /batch of their own/.test(mixed.text), mixed.text);
		const unknown = await run({ id: '4', name: 'run_actions', args: { steps: [{ action: 'columns.explode' }] } });
		assert.ok(unknown.isError && /Unknown action\(s\): columns\.explode/.test(unknown.text));
		assert.deepStrictEqual(engineer.confirmed, [['project.create']]);
	});

	test('a change set that creates a file is undone by removing the file again', async () => {
		const { window, changeSets } = await setup({ project: true });
		await window.fileService.writeFile(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')), VSBuffer.fromString('{"schema": 1, "columns": []}\n'));
		const created = '06 Building Model/notes.json';
		const set = await changeSets.proposeTexts({ title: 'Notes and a column', texts: { [created]: '{"a": 1}\n', [FLOOR_PLAN_FILE]: '{"schema": 1, "columns": [{"id": "C1"}]}\n' } }, 'assistant');
		await changeSets.accept(set.id);
		const file = joinPath(window.root, ...created.split('/'));
		assert.ok(await window.fileService.exists(file));
		assert.ok(changeSets.canUndo(set.id));
		await changeSets.undo(set.id);
		assert.strictEqual(changeSets.changeSets[0].state, 'undone');
		assert.ok(!await window.fileService.exists(file));
		assert.deepStrictEqual(JSON.parse(window.textModels.models.get(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')))!.getValue()).columns, []);

		// Only a created file: undone too; one changed since stays, and the set says why.
		const only = await changeSets.proposeTexts({ title: 'Notes', texts: { [created]: '{"a": 1}\n' } }, 'assistant');
		await changeSets.accept(only.id);
		assert.ok(changeSets.canUndo(only.id));
		await window.fileService.writeFile(file, VSBuffer.fromString('{"a": 2}\n'));
		await changeSets.undo(only.id);
		assert.strictEqual(changeSets.changeSets[0].state, 'accepted');
		assert.match(changeSets.changeSets[0].problem ?? '', /changed since/);
		assert.ok(await window.fileService.exists(file));
	});

	test('a run the engineer stops answers what was done, and the catalogue says which actions write', async () => {
		const { window, tools } = await setup({ project: true });
		await window.fileService.writeFile(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')), VSBuffer.fromString('{"schema": 1, "columns": [], "beams": []}\n'));
		const source = new CancellationTokenSource();
		window.engine.onRun = () => source.cancel();
		const stopped = await tools.runActions({ steps: [{ action: 'run.all' }] }, 'assistant', undefined, source.token);
		source.dispose();
		const text = stopped.content[0].type === 'text' ? stopped.content[0].text : '';
		assert.ok(stopped.isError && text.startsWith('The engineer stopped the batch'), text);
		assert.ok(text.includes('"cancelled": true'), text);
		const catalogue = (await tools.listActions(undefined)).content[0];
		const listed = JSON.parse(catalogue.type === 'text' ? catalogue.text : '{}');
		assert.ok(listed.actions.some((a: { name: string; writes: boolean }) => a.name === 'run.all' && a.writes));
	});

	test('a change set worked out on whole texts previews value by value and plans again on a newer document', () => {
		const before = { stories: [{ id: 'L1', height: 3000 }], columns: [], name: 'x', old: 1 };
		const after = { stories: [{ id: 'L1', height: 3200 }, { id: 'L2', height: 3000 }], columns: [{ id: 'C1' }], name: 'x', added: true };
		const changes = diffJson('a.json', before, after);
		assert.deepStrictEqual(changes.map(c => [c.path.join('.'), c.remove ? 'remove' : JSON.stringify(c.value)]), [
			['stories.0.height', '3200'],
			['stories.1', '{"id":"L2","height":3000}'],
			['columns.0', '{"id":"C1"}'],
			['added', 'true'],
			['old', 'remove'],
		]);
		const formatting = { tabSize: 1, insertSpaces: false, eol: '\n' };
		assert.deepStrictEqual(JSON.parse(planFile('a.json', JSON.stringify(before), changes, formatting).newText), after);
		// The engineer typed meanwhile: the set still applies on top of it.
		const typed = { ...before, name: 'typed' };
		assert.deepStrictEqual(JSON.parse(planFile('a.json', JSON.stringify(typed), changes, formatting).newText), { ...after, name: 'typed' });
		// Arrays changed in the middle are one change.
		assert.deepStrictEqual(diffJson('a.json', { a: [1, 2, 3, 4] }, { a: [9, 8, 7, 4] }).map(c => c.path), [['a']]);
	});
});
