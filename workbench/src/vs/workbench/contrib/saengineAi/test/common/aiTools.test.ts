/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { AI_TOOLS, ALLOWED_COMMANDS, checkCommand, safeRelativePath, toMcpTool, validateArguments, visibleTools } from '../../common/aiTools.js';

suite('SAEngine - AI tools', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const tool = (name: string) => AI_TOOLS.find(t => t.name === name)!;

	test('tool schemas are well formed', () => {
		const names = AI_TOOLS.map(t => t.name);
		assert.strictEqual(new Set(names).size, names.length);
		for (const t of AI_TOOLS) {
			assert.match(t.name, /^[a-z][a-z_]{2,63}$/, t.name);
			assert.ok(t.description.length > 20, t.name);
			assert.strictEqual(t.inputSchema.type, 'object', t.name);
			assert.strictEqual(t.inputSchema.additionalProperties, false, t.name);
			for (const required of t.inputSchema.required ?? []) {
				assert.ok(t.inputSchema.properties?.[required], `${t.name}.${required}`);
			}
			assert.ok(!(t.edits && t.readOnly), t.name);
			const mcp = toMcpTool(t);
			assert.deepStrictEqual(mcp.annotations?.readOnlyHint, !!t.readOnly);
			assert.doesNotThrow(() => JSON.parse(JSON.stringify(mcp)));
		}
	});

	test('edit tools are offered only while edits are allowed', () => {
		const edits = AI_TOOLS.filter(t => t.edits).map(t => t.name);
		assert.deepStrictEqual(edits, ['set_json_value']);
		assert.ok(visibleTools(false).every(t => !t.edits));
		assert.deepStrictEqual(visibleTools(true).length, AI_TOOLS.length);
	});

	test('the command allow-list', () => {
		assert.deepStrictEqual([
			checkCommand('saengine.runAll', false).ok,
			checkCommand('saengine.fem.designReinforcement', false).ok,
			checkCommand('saengine.report.print', false).ok,
			checkCommand('saengine.substructure.sizeAll', true).ok,
			checkCommand('undo', true).ok,
		], [true, true, true, true, true]);
		// Edits need the engineer's permission.
		assert.deepStrictEqual(checkCommand('saengine.substructure.sizeAll', false), { ok: false, reason: 'editsNotAllowed' });
		assert.deepStrictEqual(checkCommand('undo', false), { ok: false, reason: 'editsNotAllowed' });
		// Never: shells, tasks, extensions, settings, deleting files, the backend commands that take paths.
		for (const id of ['workbench.action.terminal.new', 'workbench.action.terminal.sendSequence', 'workbench.action.tasks.runTask', 'workbench.extensions.installExtension',
			'workbench.action.openSettingsJson', 'deleteFile', 'saengine.design.apply', 'saengine.report.build', 'saengine.library.generateBuilding', 'saengine.structure.runScript',
			'saengine.ai.allowEdits', 'saengine.ai.allowControl', 'SAENGINE.RUNALL', ' saengine.runAll', '']) {
			assert.deepStrictEqual(checkCommand(id, true), { ok: false, reason: 'notAllowed' }, id);
		}
		// The assistant cannot widen its own access.
		assert.ok(ALLOWED_COMMANDS.every(c => !c.id.startsWith('saengine.ai.')));
		assert.strictEqual(new Set(ALLOWED_COMMANDS.map(c => c.id)).size, ALLOWED_COMMANDS.length);
	});

	test('arguments are checked against the schema', () => {
		assert.deepStrictEqual({
			ok: validateArguments(tool('open_part'), { part: 'soil' }),
			missing: validateArguments(tool('open_part'), {}),
			badEnum: validateArguments(tool('open_part'), { part: 'kitchen' }),
			unknown: validateArguments(tool('get_project'), { x: 1 }),
			notObject: validateArguments(tool('get_project'), [1]),
			range: validateArguments(tool('read_active_document'), { maxChars: 5 }),
			integer: validateArguments(tool('read_active_document'), { maxChars: 1500.5 }),
			long: validateArguments(tool('show_message'), { message: 'x'.repeat(501) }),
			path: validateArguments(tool('set_json_value'), { file: 'a.json', path: ['stories', 0, true], value: 1 }),
			anyValue: validateArguments(tool('set_json_value'), { file: 'a.json', path: ['a'], value: { nested: [null] } }),
		}, {
			ok: [],
			missing: ['missing "part"'],
			badEnum: [`"part" must be one of ${tool('open_part').inputSchema.properties!.part.enum!.map(v => JSON.stringify(v)).join(', ')}`],
			unknown: ['unknown argument "x"'],
			notObject: ['arguments must be an object'],
			range: ['"maxChars" must be between 1000 and 2000000'],
			integer: ['"maxChars" must be integer'],
			long: ['"message" is longer than 500 characters'],
			path: ['"path[2]" must be string or integer'],
			anyValue: [],
		});
	});

	test('paths stay inside the project', () => {
		assert.deepStrictEqual(
			['04 Objects/objects.json', '04 Objects\\objects.json', './a.json', '../a.json', 'a/../../b.json', '/etc/passwd', '\\\\server\\share', 'C:/Windows/win.ini', 'c:x.json', 'a/b:c.json', '', '//'].map(safeRelativePath),
			['04 Objects/objects.json', '04 Objects/objects.json', undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined]);
	});
});
