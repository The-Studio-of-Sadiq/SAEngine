/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { workbenchInstantiationService } from '../../../../test/browser/workbenchTestServices.js';
import { DEFAULT_FLOOR_PLAN, FLOOR_PLAN_SCHEMA } from '../../../../services/saengineProject/common/projectLibraries.generated.js';
import { nextGridLine, nextLetters, nextStory } from '../../browser/gridsEditor.js';
import { JsonObject, SchemaForm } from '../../browser/schemaForm.js';

suite('SAEngine - Grids and stories editor', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	test('grid lines continue their labels and spacing', () => {
		const x = [{ label: 'A', position: 0 }, { label: 'B', position: 7500 }];
		assert.deepStrictEqual({
			letters: ['A', 'Z', 'AZ', 'ZZ'].map(nextLetters),
			x: nextGridLine(x, 'x', new Set(['A', 'B'])),
			firstX: nextGridLine([], 'x', new Set()),
			oneY: nextGridLine([{ label: '1', position: 0 }], 'y', new Set(['1'])),
			skipsUsed: nextGridLine([{ label: '1', position: 0 }, { label: '2', position: 4000 }], 'y', new Set(['1', '2', '3'])),
		}, {
			letters: ['B', 'AA', 'BA', 'AAA'],
			x: { label: 'C', position: 15000 },
			firstX: { label: 'A', position: 0 },
			oneY: { label: '2', position: 5000 },
			skipsUsed: { label: '4', position: 8000 },
		});
	});

	test('stories continue at the last story height', () => {
		const name = (n: number) => `Level ${n}`;
		assert.deepStrictEqual({
			third: nextStory([{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 4000 }], name),
			first: nextStory([], name),
		}, {
			third: { id: 'L2', name: 'Level 2', elevation: 8000 },
			first: { id: 'L0', name: 'Level 0', elevation: 0 },
		});
	});

	test('grid lines and stories render as tables and Add uses the editor\'s next entry', () => {
		const document: JsonObject = JSON.parse(JSON.stringify(DEFAULT_FLOOR_PLAN));
		const changes: string[] = [];
		const form = workbenchInstantiationService(undefined, store).createInstance(SchemaForm, {
			root: FLOOR_PLAN_SCHEMA,
			template: () => ({}),
			references: () => undefined,
			validate: () => undefined,
			changed: path => changes.push(path),
			mode: () => undefined,
			newItem: path => path === 'grids.x' ? { label: 'C', position: 12000 } : undefined,
		});
		store.add({ dispose: () => form.dispose() });
		const container = mainWindow.document.createElement('div');
		form.render(container, FLOOR_PLAN_SCHEMA, document, ['columns', 'beams', 'walls', 'slabs', 'footings']);

		const headers = [...container.querySelectorAll('.form-table')].map(t => [...t.querySelectorAll('.form-table-header')].map(h => h.textContent).filter(Boolean));
		const addX = [...container.querySelectorAll<HTMLElement>('.form-array-add .monaco-button')][0];
		addX.click();

		assert.deepStrictEqual({
			headers,
			x: (document.grids as JsonObject).x,
			changes,
		}, {
			headers: [['Label', 'Position (mm)'], ['Label', 'Position (mm)'], ['ID', 'Name', 'Elevation (mm)']],
			x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }, { label: 'C', position: 12000 }],
			changes: ['grids.x'],
		});
	});
});
