/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { CancellationToken } from '../../../../../base/common/cancellation.js';
import { joinPath } from '../../../../../base/common/resources.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { MCP } from '../../../../../platform/mcp/common/modelContextProtocol.js';
import { ActionKind, IActionStep } from '../../../../services/saengineProject/common/saengineActions.js';
import { actionsWindow, DESIGN_SUMMARY, FLOOR_PLAN_FILE, readText, SETTINGS_FILE } from '../../../../services/saengineProject/test/browser/actionsFixture.js';
import { AiActionTools } from '../../browser/aiActionTools.js';
import { IAiChangeSet, SaengineAiChangeSetService } from '../../browser/aiChangeSets.js';
import { runAssistant } from '../../common/aiAssistant.js';
import { diffJson, planFile } from '../../common/aiChangeSet.js';
import { AiTurn, IAiToolCall, IAiToolResult, IProviderAnswer, parseAnthropic } from '../../common/aiProviders.js';

suite('SAEngine - AI actions', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	async function setup(options: { readonly project: boolean; readonly accept?: boolean }) {
		const window = await actionsWindow(store, { project: options.project });
		const changeSets = store.add(new SaengineAiChangeSetService(window.projectService, window.textModels, window.fileService, window.textModels.undoRedo, window.commandService));
		const engineer = { confirmed: [] as string[][], reviewed: [] as IAiChangeSet[] };
		const tools = new AiActionTools(
			async (steps: readonly IActionStep[]) => { engineer.confirmed.push(steps.map(s => s.action)); return true; },
			async changeSet => {
				engineer.reviewed.push(changeSet);
				if (options.accept !== false) {
					await changeSets.accept(changeSet.id);
				} else {
					changeSets.reject(changeSet.id);
				}
			},
			100,
			window.service,
			changeSets,
		);
		const run = async (call: IAiToolCall): Promise<IAiToolResult> => {
			let result: MCP.CallToolResult;
			switch (call.name) {
				case 'list_actions': result = await tools.listActions(call.args.kind as ActionKind | undefined); break;
				case 'describe_action': result = await tools.describeAction(call.args.name as string); break;
				case 'run_actions': result = await tools.runActions(call.args, 'assistant'); break;
				default: throw new Error(call.name);
			}
			const first = result.content[0];
			return { id: call.id, name: call.name, text: first?.type === 'text' ? first.text : '', isError: !!result.isError };
		};
		return { window, changeSets, engineer, tools, run };
	}

	/** One answer of a scripted model: tool calls, or the final text. */
	function answer(calls: { name: string; input: object }[] | string): IProviderAnswer {
		return typeof calls === 'string'
			? parseAnthropic({ content: [{ type: 'text', text: calls }], stop_reason: 'end_turn' })
			: parseAnthropic({ content: calls.map((c, i) => ({ type: 'tool_use', id: `t${i}`, ...c })), stop_reason: 'tool_use' });
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
		const seen: IAiToolResult[][] = [];
		const script: ((last: readonly IAiToolResult[]) => IProviderAnswer)[] = [
			() => answer([{ name: 'list_actions', input: {} }]),
			() => answer([{ name: 'describe_action', input: { name: 'storeys.set' } }]),
			() => answer([{ name: 'run_actions', input: { title: 'Create the project', steps: [{ action: 'project.create', params: { name: 'Plot 12' } }] } }]),
			// A storey of 30 m: the guardrail refuses it and nothing changes.
			() => answer([{ name: 'run_actions', input: { title: 'The building', steps: model([3200, 30000, 3000]) } }]),
			last => {
				assert.ok(last[0].isError && last[0].text.includes('heights[1] = 30000: a storey height is between 2000 and 6000 mm'), last[0].text);
				return answer([{ name: 'run_actions', input: { title: 'The building', steps: model([3200, 3000, 3000]) } }]);
			},
			() => answer([{ name: 'run_actions', input: { title: 'Run All', steps: [{ action: 'run.all' }] } }]),
			() => answer([{ name: 'run_actions', input: { steps: [{ action: 'results.summary' }] } }]),
			last => {
				const summary = JSON.parse(last[0].text);
				return answer(`Run All checked ${summary.results[0].data.checked} members; ${summary.results[0].data.failed} fails (${summary.results[0].data.governing}). Please check the results.`);
			},
		];
		let step = 0;
		const turns: AiTurn[] = [{ role: 'user', text: 'Build a 3-storey RC frame, 2x1 bays, in this folder and design it.' }];
		const added = await runAssistant(turns, {
			send: async conversation => {
				const last = conversation.at(-1);
				const results = last?.role === 'tools' ? last.results : [];
				seen.push([...results]);
				return script[step++](results);
			},
			runTool: call => run(call),
			onEvent: () => { },
		}, CancellationToken.None);

		assert.strictEqual(step, script.length);
		const final = added.at(-1);
		assert.ok(final?.role === 'assistant' && final.text === 'Run All checked 13 members; 1 fails (B3). Please check the results.', JSON.stringify(final));
		// The catalogue and the description reached the model.
		assert.ok(seen[1][0].text.includes('"storeys.set"') && seen[2][0].text.includes('"heights"'));
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
