/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { CancellationToken } from '../../../../../base/common/cancellation.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { readScopes, runAssistant, systemPrompt } from '../../common/aiAssistant.js';
import { planFile, readProposal } from '../../common/aiChangeSet.js';
import { AiTurn, anthropicRequest, openAiRequest, parseAnthropic, parseOpenAi, providerUrl } from '../../common/aiProviders.js';
import { assistantTools } from '../../common/aiTools.js';

suite('SAEngine - AI assistant', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const formatting = { tabSize: 1, insertSpaces: false, eol: '\n' };

	test('the Anthropic request keeps thinking blocks and sends tool results in one turn', () => {
		const raw = [{ type: 'thinking', thinking: '', signature: 'sig' }, { type: 'tool_use', id: 't1', name: 'search_code', input: { query: 'cover' } }];
		const turns: AiTurn[] = [
			{ role: 'user', text: 'Minimum cover?' },
			{ role: 'assistant', text: '', toolCalls: [{ id: 't1', name: 'search_code', args: { query: 'cover' } }], raw, provider: 'anthropic' },
			{ role: 'tools', results: [{ id: 't1', name: 'search_code', text: '{}' }] },
		];
		const request = anthropicRequest({ provider: 'anthropic', model: 'claude-opus-5-5', effort: 'high', apiKey: 'k' }, 'system', turns, []);
		const body = request.body as { messages: { role: string; content: unknown }[]; fallbacks?: string; thinking: unknown };
		assert.deepStrictEqual(body.messages[1].content, raw);
		assert.deepStrictEqual(body.messages[2], { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't1', content: '{}' }] });
		assert.strictEqual(body.fallbacks, 'default');
		assert.deepStrictEqual(body.thinking, { type: 'adaptive' });
		assert.strictEqual(request.headers['x-api-key'], 'k');
	});

	test('answers of both providers', () => {
		const anthropic = parseAnthropic({ content: [{ type: 'text', text: 'Hi' }, { type: 'tool_use', id: 'a', name: 'get_project', input: {} }], stop_reason: 'tool_use' });
		assert.deepStrictEqual([anthropic.text, anthropic.stop, anthropic.toolCalls.length], ['Hi', 'tools', 1]);
		assert.strictEqual(parseAnthropic({ content: [], stop_reason: 'refusal' }).stop, 'refusal');
		const openai = parseOpenAi({ choices: [{ message: { content: null, tool_calls: [{ id: 'c', type: 'function', function: { name: 'search_code', arguments: '{"query":"R"}' } }] }, finish_reason: 'tool_calls' }] });
		assert.deepStrictEqual(openai.toolCalls, [{ id: 'c', name: 'search_code', args: { query: 'R' } }]);
		assert.strictEqual(providerUrl({ provider: 'openaiCompatible', endpoint: 'http://localhost:11434/v1/' }), 'http://localhost:11434/v1/chat/completions');
		const request = openAiRequest({ provider: 'openaiCompatible', model: 'm', endpoint: 'http://localhost:1/v1', effort: 'high' }, 's', [{ role: 'user', text: 'q' }], []);
		assert.strictEqual(request.headers['authorization'], undefined);
	});

	test('the loop runs tools until the model answers', async () => {
		let calls = 0;
		const added = await runAssistant([{ role: 'user', text: 'q' }], {
			send: async () => ++calls === 1
				? parseAnthropic({ content: [{ type: 'tool_use', id: 't', name: 'search_code', input: { query: 'q' } }], stop_reason: 'tool_use' })
				: parseAnthropic({ content: [{ type: 'text', text: 'Answer' }], stop_reason: 'end_turn' }),
			runTool: async call => ({ id: call.id, name: call.name, text: 'passages' }),
			onEvent: () => { },
		}, CancellationToken.None);
		assert.deepStrictEqual(added.map(t => t.role), ['assistant', 'tools', 'assistant']);
	});

	test('scopes decide the tools and the prompt', () => {
		const none = assistantTools(new Set()).map(t => t.name);
		assert.ok(none.includes('search_code') && none.includes('propose_changes'));
		assert.ok(!none.includes('read_results') && !none.includes('get_project'));
		assert.ok(!assistantTools(new Set(['project', 'document', 'results'])).some(t => t.name === 'set_json_value' || t.name === 'run_command' || t.name === 'screenshot'));
		assert.match(systemPrompt(new Set()), /not allowed you to read the project overview, the open document, the results/);
		assert.deepStrictEqual([...readScopes(undefined)], ['project', 'results']);
		assert.deepStrictEqual([...readScopes('["document","bogus"]')], ['document']);
	});

	test('change sets: checked, planned with before and after', () => {
		assert.ok(readProposal({ title: 'x', changes: [{ file: '../x.json', path: ['a'], value: 1 }] }).problems.length);
		assert.ok(readProposal({ title: 'x', changes: [{ file: '08 FEM/model.results/design-summary.json', path: ['a'], value: 1 }] }).problems.length);
		const { proposal } = readProposal({ title: 'Taller storey', changes: [{ file: '05 Floor Plan/floor-plan.json', path: ['stories', 1, 'elevation'], value: 3200 }] });
		assert.ok(proposal);
		const planned = planFile('05 Floor Plan/floor-plan.json', '{\n\t"stories": [{"elevation": 0}, {"elevation": 3000}]\n}', proposal.changes, formatting);
		assert.deepStrictEqual([planned.changes[0].before, planned.changes[0].after, planned.changes[0].noop], [3000, 3200, false]);
		assert.deepStrictEqual(JSON.parse(planned.newText).stories[1].elevation, 3200);
		assert.throws(() => planFile('a.json', '{', proposal.changes, formatting));
	});
});
