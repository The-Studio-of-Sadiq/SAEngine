/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { codeOverrides, filterCodeValues, formatCodeValue, parseCodeValue, readCodeValues, setCodeOverride } from '../../browser/codeValuesModel.js';
import { JsonObject } from '../../browser/schemaForm.js';
import { settingsSections } from '../../browser/settingsEditor.js';
import { SETTINGS_SCHEMA } from '../../../../services/saengineProject/common/projectLibraries.generated.js';

suite('SAEngine - Code values (project overrides of the code pack)', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('the overrides have their own section, Code Values', () => {
		const section = settingsSections(SETTINGS_SCHEMA).find(s => s.id === 'codeOverrides');
		assert.deepStrictEqual(section && { title: section.title, keys: section.keys }, { title: 'Code Values', keys: ['codeOverrides'] });
	});

	test('reads the backend answer tolerantly', () => {
		assert.strictEqual(readCodeValues({ ok: false, message: 'no' }), undefined);
		assert.strictEqual(readCodeValues(undefined), undefined);
		const values = readCodeValues({
			id: 'bnbc2020', name: 'BNBC 2020', missing: null,
			tables: [{ name: 'factors', overridden: true }, { nope: 1 }],
			overrides: [{ path: 'factors.phi.shear', packValue: 0.75, value: 0.7 }],
			problems: [{ path: 'factors.phi.joint', message: 'must be a number' }],
			rows: [{ path: 'factors.phi.shear', table: 'factors', value: 0.7, packValue: 0.75, overridden: true }, { value: 1 }],
		});
		assert.ok(values);
		assert.strictEqual(values.missing, undefined);
		assert.deepStrictEqual(values.tables, [{ name: 'factors', title: 'factors', section: '', overridden: true, generic: false }]);
		assert.deepStrictEqual(values.rows.map(r => [r.path, r.overridden, r.generic, r.label]), [['factors.phi.shear', true, false, '']]);
		assert.deepStrictEqual(values.problems, [{ path: 'factors.phi.joint', message: 'must be a number', packValue: null }]);
		assert.deepStrictEqual(values.fallbacks, []);
	});

	test('a project value is typed like the pack value', () => {
		assert.deepStrictEqual(parseCodeValue('0.7', 0.75), { value: 0.7 });
		assert.ok(parseCodeValue('high', 0.75).error);
		assert.deepStrictEqual(parseCodeValue('  ', 0.75), { value: undefined });
		assert.deepStrictEqual(parseCodeValue('false', true), { value: false });
		assert.ok(parseCodeValue('no', true).error);
		assert.deepStrictEqual(parseCodeValue('SD', 'L'), { value: 'SD' });
		assert.deepStrictEqual(parseCodeValue('[1, 2]', [3]), { value: [1, 2] });
		assert.ok(parseCodeValue('{"a": 1}', [3]).error);
		assert.deepStrictEqual(parseCodeValue('{"D": 1.4}', { D: 1.2 }), { value: { D: 1.4 } });
		assert.deepStrictEqual(parseCodeValue('2', null), { value: 2 });
		assert.strictEqual(formatCodeValue([1, 2]), '[1,2]');
		assert.strictEqual(formatCodeValue(null), '–');
	});

	test('setting and resetting an override edits only codeOverrides', () => {
		const document: JsonObject = { codePack: 'bnbc2020' };
		assert.ok(setCodeOverride(document, 'factors.phi.shear', 0.7));
		assert.ok(!setCodeOverride(document, 'factors.phi.shear', 0.7));
		assert.deepStrictEqual(codeOverrides(document), { 'factors.phi.shear': 0.7 });
		assert.ok(setCodeOverride(document, 'factors.phi.shear', undefined));
		assert.deepStrictEqual(document, { codePack: 'bnbc2020' });
		assert.ok(!setCodeOverride(document, 'factors.phi.shear', undefined));
	});

	test('the filter matches words of the path', () => {
		const row = (path: string, description = '') => ({ path, table: 'factors', value: 1, packValue: 1, overridden: false, generic: false, note: '', label: '', description, unit: '', clause: '', group: '' });
		const rows = [row('factors.phi.shear'), row('factors.phi.tension', 'Tension-controlled sections.'), row('factors.phi.shearSeismic')];
		assert.deepStrictEqual(filterCodeValues(rows, 'SHEAR').map(r => r.path), ['factors.phi.shear', 'factors.phi.shearSeismic']);
		assert.deepStrictEqual(filterCodeValues(rows, 'phi seis').map(r => r.path), ['factors.phi.shearSeismic']);
		assert.strictEqual(filterCodeValues(rows, '').length, 3);
		// SL-1: the description's words find a value too.
		assert.deepStrictEqual(filterCodeValues(rows, 'controlled').map(r => r.path), ['factors.phi.tension']);
	});
});
