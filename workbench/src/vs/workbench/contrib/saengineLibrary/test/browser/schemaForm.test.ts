/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { workbenchInstantiationService } from '../../../../test/browser/workbenchTestServices.js';
import { DEFAULT_MATERIALS, MATERIALS_SCHEMA, TEMPLATES } from '../../../../services/saengineProject/common/projectLibraries.generated.js';
import { JsonObject, SchemaForm } from '../../browser/schemaForm.js';

suite('SAEngine - SchemaForm', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	function setup(item: JsonObject) {
		const changes: string[] = [];
		const form = workbenchInstantiationService(undefined, store).createInstance(SchemaForm, {
			root: MATERIALS_SCHEMA,
			template: defName => JSON.parse(JSON.stringify(TEMPLATES[defName])),
			references: () => undefined,
			validate: () => undefined,
			changed: path => changes.push(path),
			mode: () => undefined,
		});
		store.add({ dispose: () => form.dispose() });
		const container = mainWindow.document.createElement('div');
		form.render(container, MATERIALS_SCHEMA.$defs!.Material, item, ['category']);

		const type = (label: string, text: string) => {
			const row = [...container.querySelectorAll('.form-field')].find(r => r.querySelector('.form-label')?.textContent === label);
			const input = row?.querySelector('input');
			assert.ok(input, `no input for ${label}`);
			input.value = text;
			input.dispatchEvent(new Event('input'));
		};
		return { changes, type, labels: () => [...container.querySelectorAll('.form-group-title')].map(e => e.textContent) };
	}

	function concrete(): JsonObject {
		const materials = (DEFAULT_MATERIALS as { materials: JsonObject[] }).materials;
		return JSON.parse(JSON.stringify(materials.find(m => m.id === 'C24.1')));
	}

	test('applies valid values and never invalid ones', () => {
		const item = concrete();
		const { changes, type } = setup(item);

		type('Compressive strength f\'c', '30');
		type('Compressive strength f\'c', '-5');
		type('Compressive strength f\'c', 'abc');
		type('Poisson\'s ratio ν', '0.7');
		type('ID', 'bad id!');

		assert.deepStrictEqual({
			fc: (item.concrete as JsonObject).fc,
			nu: (item.mechanical as JsonObject).nu,
			id: item.id,
			changes,
		}, { fc: 30, nu: 0.2, id: 'C24.1', changes: ['concrete.fc'] });
	});

	test('clearing an optional field removes it; a required one keeps its value', () => {
		const item = concrete();
		const { type } = setup(item);

		type('Tensile strength fr', '');
		type('Compressive strength f\'c', '');

		assert.deepStrictEqual({ ft: (item.concrete as JsonObject).ft, fc: (item.concrete as JsonObject).fc }, { ft: undefined, fc: 24.1 });
	});
});
