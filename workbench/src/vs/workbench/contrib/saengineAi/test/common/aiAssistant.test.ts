/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { AGENT_NAME, agentFile, systemPrompt, TOOL_SET_NAME } from '../../common/aiAssistant.js';
import { planFile, previewRows, readProposal } from '../../common/aiChangeSet.js';
import { AI_TOOLS, chatTools, sendsProjectData } from '../../common/aiTools.js';

suite('SAEngine - AI assistant', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const formatting = { tabSize: 1, insertSpaces: false, eol: '\n' };

	test('the chat gets the read, explain, screenshot and action tools, never the ones that edit directly or run commands', () => {
		const names = chatTools().map(t => t.name);
		for (const name of ['list_actions', 'describe_action', 'run_actions', 'search_code', 'explain_results', 'read_results', 'get_project', 'read_active_document', 'screenshot', 'propose_changes']) {
			assert.ok(names.includes(name), name);
		}
		for (const name of ['run_command', 'list_commands', 'show_message', 'annotate_drawings']) {
			assert.ok(!names.includes(name), name);
		}
		// What sends project data asks the project's consent first; code passages and the catalogue do not.
		const tool = (name: string) => AI_TOOLS.find(t => t.name === name);
		assert.deepStrictEqual(['get_project', 'read_active_document', 'read_results', 'explain_results', 'screenshot', 'run_actions'].map(name => sendsProjectData(tool(name))), [true, true, true, true, true, true]);
		assert.deepStrictEqual(['search_code', 'list_actions', 'describe_action', 'open_part'].map(name => sendsProjectData(tool(name))), [false, false, false, false]);
	});

	test('the SAEngine agent: the playbook, the rules, and only SAEngine\'s tool set', () => {
		assert.match(systemPrompt(), /project\.create[\s\S]*run\.all/);
		assert.match(systemPrompt(), /checked by the engineer/);
		assert.match(systemPrompt(), /change set the engineer accepts or rejects/);
		const file = agentFile();
		const header = file.slice(0, file.indexOf('\n---\n', 4));
		assert.ok(header.startsWith('---\n'));
		assert.match(header, new RegExp(`^name: ${AGENT_NAME}$`, 'm'));
		assert.match(header, new RegExp(`^tools: \\["${TOOL_SET_NAME}"\\]$`, 'm'));
		assert.ok(file.endsWith(`${systemPrompt()}\n`));
	});

	test('change sets: checked, planned with before and after, previewed value by value', () => {
		assert.ok(readProposal({ title: 'x', changes: [{ file: '../x.json', path: ['a'], value: 1 }] }).problems.length);
		assert.ok(readProposal({ title: 'x', changes: [{ file: '08 FEM/model.results/design-summary.json', path: ['a'], value: 1 }] }).problems.length);
		const { proposal } = readProposal({ title: 'Taller storey', changes: [{ file: '05 Floor Plan/floor-plan.json', path: ['stories', 1, 'elevation'], value: 3200, reason: 'Typical storey' }] });
		assert.ok(proposal);
		const planned = planFile('05 Floor Plan/floor-plan.json', '{\n\t"stories": [{"elevation": 0}, {"elevation": 3000}]\n}', proposal.changes, formatting);
		assert.deepStrictEqual([planned.changes[0].before, planned.changes[0].after, planned.changes[0].noop], [3000, 3200, false]);
		assert.deepStrictEqual(JSON.parse(planned.newText).stories[1].elevation, 3200);
		assert.throws(() => planFile('a.json', '{', proposal.changes, formatting));
		assert.deepStrictEqual(previewRows([planned]), { rows: [{ file: '05 Floor Plan/floor-plan.json', value: 'stories[1].elevation', before: '3000', after: '3200', reason: 'Typical storey', noop: false }], more: 0 });
		assert.strictEqual(previewRows([planned, planned, planned], 2).more, 1);
	});
});
