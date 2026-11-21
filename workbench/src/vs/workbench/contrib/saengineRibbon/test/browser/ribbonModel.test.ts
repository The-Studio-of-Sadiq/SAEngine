/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { ICommandAction } from '../../../../../platform/action/common/action.js';
import { MenuId, MenuItemAction, SubmenuItemAction } from '../../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../../platform/commands/common/commands.js';
import { IContextKeyService } from '../../../../../platform/contextkey/common/contextkey.js';
import {
	buildRibbonGroups,
	getRibbonCustomGroups,
	getRibbonGroupLabel,
	getRibbonItemHint,
	packRibbonColumns,
	parseRibbonGroup,
	registerRibbonCustomGroup,
	registerRibbonGroupLabel,
	registerRibbonItemHint,
	RIBBON_TABS,
} from '../../browser/ribbonRegistry.js';

const fakeContextKeyService = {
	contextMatchesRules: () => true,
} as unknown as IContextKeyService;

const fakeCommandService = {
	executeCommand: async () => undefined,
} as unknown as ICommandService;

function makeMenuAction(id: string, title: string, enabled = true): MenuItemAction {
	const item: ICommandAction = { id, title };
	const action = new MenuItemAction(item, undefined, undefined, undefined, undefined, fakeContextKeyService, fakeCommandService);
	return enabled ? action : Object.assign(action, { enabled: false });
}

suite('SAEngine - ribbon model', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('parseRibbonGroup sorts navigation first, numeric prefixes numerically, and empty last', () => {
		const rawGroups = ['10_Report', '2_Loads', 'navigation', '', 'Custom', '1_Project'];
		const parsed = rawGroups.map(g => parseRibbonGroup(g, key => key === 'Loads' ? 'Gravity Loads' : undefined));
		parsed.sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
		assert.deepStrictEqual(
			parsed.map(p => `${p.key}:${p.label}`),
			['navigation:General', 'Project:Project', 'Loads:Gravity Loads', 'Report:Report', 'Custom:Custom', ':More']
		);
	});

	test('packRibbonColumns packs large items alone and small items 3 high', () => {
		const columns = packRibbonColumns([
			{ id: 's1', size: 'small' },
			{ id: 's2', size: 'small' },
			{ id: 'l1', size: 'large' },
			{ id: 's3', size: 'small' },
			{ id: 's4', size: 'small' },
			{ id: 's5', size: 'small' },
			{ id: 's6', size: 'small' },
		]);
		assert.deepStrictEqual(
			columns.map(col => col.kind === 'large' ? `L:${col.item.id}` : `S:[${col.items.map(i => i.id).join(',')}]`),
			['S:[s1,s2]', 'L:l1', 'S:[s3,s4,s5]', 'S:[s6]']
		);
	});

	test('buildRibbonGroups applies numeric group ordering, size hints, split primary actions, and custom groups', () => {
		const submenuId = MenuId.for('SaengineRibbon.TestSubmenu');
		const subPrimary = makeMenuAction('test.sub.primary', 'Primary');
		const subSecondary = makeMenuAction('test.sub.secondary', 'Secondary');
		const submenuAction = new SubmenuItemAction(
			{ title: 'Open', submenu: submenuId, isSplitButton: true },
			undefined,
			[subSecondary, subPrimary]
		);

		const hintDisposable = registerRibbonItemHint('test.a', { size: 'small', label: 'Short A' });
		const subHintDisposable = registerRibbonItemHint(submenuId.id, { size: 'large', primaryCommandId: 'test.sub.primary' });
		const labelDisposable = registerRibbonGroupLabel('Solver', 'Analysis Solver');
		const customDisposable = registerRibbonCustomGroup({
			tabId: 'home',
			group: '2_Workflow',
			label: 'Workflow',
			render: () => ({ dispose: () => undefined }),
		});

		try {
			const groups = buildRibbonGroups(
				[
					['10_Solver', [makeMenuAction('test.a', 'Alpha'), makeMenuAction('test.b', 'Beta'), makeMenuAction('test.c', 'Gamma')]],
					['1_Project', [submenuAction, makeMenuAction('test.solo', 'Solo')]],
				],
				getRibbonCustomGroups('home')
			);

			assert.deepStrictEqual(groups.map(g => `${g.order}:${g.label}`), ['1:Project', '2:Workflow', '10:Analysis Solver']);
			assert.strictEqual(groups[1].custom?.group, '2_Workflow');

			// 1_Project: submenuAction (explicit large split) + test.solo (default large because <=2 items)
			const projectCols = groups[0].columns;
			assert.strictEqual(projectCols.length, 2);
			assert.strictEqual(projectCols[0].kind, 'large');
			assert.strictEqual(projectCols[0].item.kind, 'submenu');
			if (projectCols[0].kind === 'large' && projectCols[0].item.kind === 'submenu') {
				assert.strictEqual(projectCols[0].item.isSplit, true);
				assert.strictEqual(projectCols[0].item.primaryAction?.id, 'test.sub.primary');
			}

			// 10_Solver: 3 items -> default small, test.a uses Short A label, packed into 1 stack of 3
			const solverCols = groups[2].columns;
			assert.strictEqual(solverCols.length, 1);
			assert.strictEqual(solverCols[0].kind, 'stack');
			if (solverCols[0].kind === 'stack') {
				assert.deepStrictEqual(solverCols[0].items.map(i => i.label), ['Short A', 'Beta', 'Gamma']);
			}
		} finally {
			customDisposable.dispose();
			labelDisposable.dispose();
			subHintDisposable.dispose();
			hintDisposable.dispose();
		}

		assert.strictEqual(getRibbonItemHint('test.a'), undefined);
		assert.strictEqual(getRibbonGroupLabel('Solver'), undefined);
		assert.strictEqual(getRibbonCustomGroups('home').length, 0);
	});

	test('RIBBON_TABS includes all engineering tabs with contextual Draft tab', () => {
		assert.deepStrictEqual(
			RIBBON_TABS.map(t => t.id),
			['home', 'define', 'model', 'draft', 'loads', 'analyze', 'design', 'mep', 'documents', 'output', 'studies', 'collaborate', 'manage']
		);
		const draft = RIBBON_TABS.find(t => t.id === 'draft');
		assert.strictEqual(draft?.contextual, true);
		assert.ok(draft?.when);
	});
});
