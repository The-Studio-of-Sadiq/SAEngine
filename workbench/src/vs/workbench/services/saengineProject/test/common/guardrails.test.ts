/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { blockRange, checkTypedField, guardrailError, setResolvedGuardrails } from '../../common/guardrails.js';
import { deleteDetail, needsBulkConfirmation } from '../../common/confirmDelete.js';

suite('SAEngine input guardrails', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	teardown(() => setResolvedGuardrails(undefined));

	const plan = {
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }],
	};

	test('a storey height or grid spacing outside physical sense is refused as typed, with the reason', () => {
		const low = guardrailError('floorPlan', plan, 'stories.1.elevation', '400');
		assert.ok(low?.includes('400 mm is below 1000 mm'), low);
		assert.ok(low?.includes('Base to Level 1'), low);
		assert.strictEqual(guardrailError('floorPlan', plan, 'stories.1.elevation', '3000'), undefined);
		assert.ok(guardrailError('floorPlan', plan, 'grids.x.1.position', '50'));
		// Unusual but possible: a warning, not refused.
		assert.strictEqual(checkTypedField('floorPlan', plan, 'stories.1.elevation', '9000')?.severity, 'warning');
		assert.strictEqual(guardrailError('floorPlan', plan, 'stories.1.elevation', '9000'), undefined);
	});

	test('material strengths: practice limits before the backend, the pack\'s once it answers', () => {
		const rebar = { id: 'B', category: 'rebar', steel: { fy: 420 } };
		assert.strictEqual(guardrailError('materials', rebar, 'steel.fy', '600'), undefined);
		assert.ok(guardrailError('materials', rebar, 'steel.fy', '4200'));
		setResolvedGuardrails([{ id: 'reinforcementStrength', kind: 'materials', paths: ['steel.fy'], when: { category: ['rebar'] }, what: 'fy of reinforcement', unit: 'MPa', block: [{ max: 550, reason: 'above the code limit', source: 'Code X 1.2' }] }]);
		assert.ok(guardrailError('materials', rebar, 'steel.fy', '600')?.includes('(Code X 1.2)'));
		// Another category is not checked by this rule.
		assert.strictEqual(guardrailError('materials', { ...rebar, category: 'steel' }, 'steel.fy', '600'), undefined);
	});

	test('a cover deeper than half the member is refused', () => {
		const column = { id: 'C', kind: 'column', profile: { shape: 'rectangle', xDim: 300, yDim: 400 }, reinforcement: { cover: 40 } };
		assert.ok(guardrailError('objects', column, 'reinforcement.cover', '150')?.includes('no concrete inside'));
		assert.strictEqual(guardrailError('objects', column, 'reinforcement.cover', '40'), undefined);
	});

	test('the wizard reads the same ranges', () => {
		assert.deepStrictEqual([blockRange('storeyHeight').min, blockRange('storeyHeight').max], [1000, 30000]);
		assert.strictEqual(blockRange('storeyCount').max, 200);
	});

	test('delete confirmation: threshold and what it says', () => {
		assert.strictEqual(needsBulkConfirmation(3), false);
		assert.strictEqual(needsBulkConfirmation(10), true);
		const detail = deleteDetail({ items: Array.from({ length: 14 }, (_, i) => `B${i + 1}`), recovery: 'undo' });
		assert.ok(detail.includes('and 2 more'), detail);
		assert.ok(detail.includes('Ctrl+Z'), detail);
		assert.ok(deleteDetail({ recovery: 'never' }).includes('cannot be undone'));
	});
});
