/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { keepMaterialDefaults, projectMaterial } from '../../common/materialDefaults.js';

suite('SAEngine - Material defaults', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	const materials = [
		{ id: 'C20.7', category: 'concrete' },
		{ id: 'C27.6', category: 'concrete' },
		{ id: 'B420DWR', category: 'rebar' },
		{ id: 'B500DWR', category: 'rebar' },
	];

	test('the project\'s concrete and rebar: its defaults, else the first of each', () => {
		const chosen = { materials, defaults: { concrete: 'C27.6', rebar: 'B500DWR' } };
		assert.deepStrictEqual(
			[projectMaterial(chosen, 'concrete'), projectMaterial(chosen, 'rebar'), projectMaterial({ materials }, 'rebar'), projectMaterial({ materials, defaults: { rebar: 'C27.6' } }, 'rebar'), projectMaterial(undefined, 'rebar')],
			['C27.6', 'B500DWR', 'B420DWR', 'B420DWR', undefined],
		);
	});

	test('defaults follow a rename and are dropped with their material', () => {
		const renamed = { materials: materials.map(m => m.id === 'B500DWR' ? { ...m, id: 'B500' } : m), defaults: { concrete: 'C27.6', rebar: 'B500DWR' } };
		const changedRename = keepMaterialDefaults(renamed, 'B500DWR', 'B500');
		const deleted: Record<string, unknown> = { materials: materials.filter(m => m.id !== 'C27.6'), defaults: { concrete: 'C27.6' } };
		const changedDelete = keepMaterialDefaults(deleted);
		const recategorised = { materials: materials.map(m => m.id === 'B500DWR' ? { ...m, category: 'steel' } : m), defaults: { concrete: 'C27.6', rebar: 'B500DWR' } };
		keepMaterialDefaults(recategorised);
		const untouched = { materials, defaults: { rebar: 'B500DWR' } };
		assert.deepStrictEqual(
			[changedRename, renamed.defaults, changedDelete, deleted.defaults, recategorised.defaults, keepMaterialDefaults(untouched), untouched.defaults],
			[true, { concrete: 'C27.6', rebar: 'B500' }, true, undefined, { concrete: 'C27.6' }, false, { rebar: 'B500DWR' }],
		);
	});
});
