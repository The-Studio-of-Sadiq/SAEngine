/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { Action, Separator, SubmenuAction } from '../../../../../base/common/actions.js';
import { Codicon } from '../../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../../base/common/lifecycle.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { ICommandAction } from '../../../../../platform/action/common/action.js';
import { IMenuItem, isIMenuItem, isISubmenuItem, ISubmenuItem, MenuId, MenuItemAction, MenuRegistry, SubmenuItemAction } from '../../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../../platform/commands/common/commands.js';
import { ContextKeyExpression, ContextKeyValue, IContext, IContextKeyService } from '../../../../../platform/contextkey/common/contextkey.js';
import { ActiveEditorContext } from '../../../../common/contextkeys.js';
import { CAD_DRAFT_COMMANDS, DRAFT_RIBBON_GROUPS, DraftRibbonSubmenus } from '../../../saengineCad/browser/cadDraftCommands.js';
import '../../../saengineCad/browser/cadDraftRibbon.contribution.js';
import '../../browser/ribbonActions.contribution.js';
import {
	collectControlCollapsedActions,
	controlVisibilitySignature,
	dedupeEditorFrameActions,
	hasVisibleControls,
	RibbonInlineRowControl,
	RibbonSegmentedModel,
	RibbonSelectModel,
	RibbonSliderModel,
	RibbonToggleModel,
} from '../../browser/ribbonControls.js';
import {
	buildRibbonGroups,
	computeCollapsedRibbonGroups,
	getRibbonCustomGroups,
	getRibbonGroupLabel,
	getRibbonItemHint,
	getVisibleRibbonTabs,
	packRibbonColumns,
	parseRibbonGroup,
	registerRibbonCustomGroup,
	registerRibbonGroupLabel,
	registerRibbonItemHint,
	resolveActiveTabForEditor,
	resolveDataPanelPart,
	resolveEditorToolbarTargetTab,
	RIBBON_TABS,
	RibbonMenus,
	RibbonTabId,
	SAENGINE_DATA_PANEL_PART_CONTEXT,
	SAENGINE_SUB_VIEW_CONTEXT,
	SAENGINE_EDITOR_IDS,
} from '../../browser/ribbonRegistry.js';

const fakeContextKeyService = {
	contextMatchesRules: () => true,
} as unknown as IContextKeyService;

function contextFor(values: { readonly [key: string]: ContextKeyValue | undefined }): Pick<IContextKeyService, 'contextMatchesRules'> {
	const context: IContext = {
		getValue<T extends ContextKeyValue = ContextKeyValue>(key: string): T | undefined {
			return values[key] as T | undefined;
		},
	};
	return {
		contextMatchesRules: (rules: ContextKeyExpression | undefined) => !rules || rules.evaluate(context),
	};
}

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
		const previousSolverLabel = getRibbonGroupLabel('Solver');
		const previousHomeCustomGroups = [...getRibbonCustomGroups('home')];
		const labelDisposable = registerRibbonGroupLabel('Solver', 'Analysis Solver');
		const customDisposable = registerRibbonCustomGroup({
			tabId: 'home',
			group: '20_TestWorkflow',
			label: 'Test Workflow',
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

			assert.deepStrictEqual(groups.map(g => `${g.order}:${g.label}`), ['1:Project', '3:Workflow', '10:Analysis Solver', '20:Test Workflow']);
			assert.strictEqual(groups[3].custom?.group, '20_TestWorkflow');

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
		assert.strictEqual(getRibbonGroupLabel('Solver'), previousSolverLabel);
		assert.deepStrictEqual(getRibbonCustomGroups('home'), previousHomeCustomGroups);
	});

	test('RIBBON_TABS defines Home, Project, and 18 contextual engineering tabs', () => {
		assert.deepStrictEqual(
			RIBBON_TABS.map(t => t.id),
			[
				'home', 'project', 'soil', 'settings', 'library', 'plan',
				'draft', 'annotate', 'blocksParametric', 'architecture', 'bim3d', 'mep',
				'analyze', 'results', 'design', 'foundations', 'boq', 'output', 'documents', 'studies',
			]
		);
		const home = RIBBON_TABS.find(t => t.id === 'home');
		assert.ok(home && !home.contextual && !home.when);
		const project = RIBBON_TABS.find(t => t.id === 'project');
		assert.ok(project && !project.contextual && project.when);
		for (const tab of RIBBON_TABS) {
			if (tab.id !== 'home' && tab.id !== 'project') {
				assert.strictEqual(tab.contextual, true, `Expected ${tab.id} to be contextual`);
				assert.ok(tab.when, `Expected ${tab.id} to have a when rule`);
			}
		}
		assert.ok(RIBBON_TABS.find(t => t.id === 'draft')?.contextualTag);
	});

	test('getVisibleRibbonTabs shows only contextual tabs for soil, floor plan, CAD, FEM and other editors', () => {
		const visibleIds = (editorId: string, panelPart = '', subView = '') => getVisibleRibbonTabs(contextFor({
			[ActiveEditorContext.key]: editorId,
			[SAENGINE_DATA_PANEL_PART_CONTEXT]: panelPart,
			[SAENGINE_SUB_VIEW_CONTEXT]: subView,
		})).map(t => t.id);

		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.soil), ['home', 'soil']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.settings, '', 'settings.project'), ['home', 'settings']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.codePacks, '', 'settings.packages'), ['home', 'settings']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.library), ['home', 'library']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.sectionDesigner), ['home', 'library']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.floorPlan), ['home', 'plan', 'draft', 'annotate', 'blocksParametric']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.grids), ['home', 'plan']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.membersTable), ['home', 'plan']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.structureModeler), ['home', 'plan']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.structure), ['home', 'plan']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.cad), ['home', 'draft', 'annotate', 'blocksParametric']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.architecture), ['home', 'architecture']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.building, '', 'bim.3d'), ['home', 'bim3d']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.mep, '', 'mep.coordination'), ['home', 'mep']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.femModel, '', 'fem.model'), ['home', 'analyze']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.femModel, '', 'fem.pushover'), ['home', 'analyze']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.femResults, '', 'fem.charts'), ['home', 'results']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.femCfdWind, '', 'fem.model'), ['home', 'analyze']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.femDesignProposal, '', 'fem.design'), ['home', 'design']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.femStrutAndTie, '', 'fem.design'), ['home', 'design']);

		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.substructure), ['home', 'foundations']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.boq), ['home', 'boq']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.rates), ['home', 'boq']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.exports), ['home', 'output']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.drawingPreview), ['home', 'documents']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.reportTemplate), ['home', 'documents']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.worksheet), ['home', 'documents']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.officeTools), ['home', 'studies']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.studies), ['home', 'studies']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.graph), ['home', 'studies']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.overview), ['home', 'project']);
		assert.deepStrictEqual(visibleIds(''), ['home', 'project']);

		// U3 data panels show the contextual tabs of their owning part.
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.dataPanel, resolveDataPanelPart('saengine.mep.electrical.boards', 'mep'), 'mep.electrical'), ['home', 'mep']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.dataPanel, resolveDataPanelPart('saengine.analyze.runDerive', 'fem'), 'fem.model'), ['home', 'analyze']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.dataPanel, resolveDataPanelPart('saengine.drawings.scopeBoxes', 'exports')), ['home', 'documents']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.dataPanel, resolveDataPanelPart('saengine.bim.exportIfcOptions', 'exports')), ['home', 'output']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.dataPanel, resolveDataPanelPart('saengine.studies.annualEnergy', 'mep')), ['home', 'studies']);
		assert.deepStrictEqual(visibleIds(SAENGINE_EDITOR_IDS.dataPanel, resolveDataPanelPart('saengine.manage.verificationManual', 'fem'), 'fem.model'), ['home', 'analyze']);
	});

	test('MEP coordination shows only its groups and has no duplicate command ids across ribbon tabs', () => {
		const context = contextFor({
			[ActiveEditorContext.key]: SAENGINE_EDITOR_IDS.mep,
			[SAENGINE_SUB_VIEW_CONTEXT]: 'mep.coordination',
		});
		const visibleGroups = MenuRegistry.getMenuItems(RibbonMenus.MEP)
			.filter(item => !item.when || context.contextMatchesRules(item.when))
			.map(item => item.group)
			.filter((group): group is string => !!group);
		assert.deepStrictEqual([...new Set(visibleGroups)], ['1_Coordination']);

		const duplicateIdsFor = (ribbonContext: Pick<IContextKeyService, 'contextMatchesRules'>) => {
			const occurrences = new Map<string, string[]>();
			const collect = (menuId: MenuId, tabId: string, visited: Set<string>) => {
				if (visited.has(menuId.id)) {
					return;
				}
				visited.add(menuId.id);
				for (const item of MenuRegistry.getMenuItems(menuId)) {
					if (item.when && !ribbonContext.contextMatchesRules(item.when)) {
						continue;
					}
					if (isIMenuItem(item)) {
						const tabs = occurrences.get(item.command.id) ?? [];
						tabs.push(tabId);
						occurrences.set(item.command.id, tabs);
					} else if (isISubmenuItem(item)) {
						collect(item.submenu, tabId, visited);
					}
				}
			};
			for (const tab of getVisibleRibbonTabs(ribbonContext)) {
				collect(tab.menuId, tab.id, new Set<string>());
			}
			return [...occurrences.entries()]
				.filter(([, tabs]) => tabs.length > 1)
				.map(([commandId, tabs]) => `${commandId} (${tabs.join(', ')})`)
				.sort();
		};
		assert.deepStrictEqual(duplicateIdsFor(context), []);
		assert.deepStrictEqual(duplicateIdsFor(contextFor({
			[ActiveEditorContext.key]: SAENGINE_EDITOR_IDS.overview,
		})), []);
	});

	test('resolveActiveTabForEditor selects first contextual tab and remembers last tab per editor', () => {
		const tabsFor = (editorId: string, subView = '') => getVisibleRibbonTabs(contextFor({
			[ActiveEditorContext.key]: editorId,
			[SAENGINE_SUB_VIEW_CONTEXT]: subView,
		}));
		const empty = new Map<string, RibbonTabId>();

		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.soil, tabsFor(SAENGINE_EDITOR_IDS.soil), empty), 'soil');
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.floorPlan, tabsFor(SAENGINE_EDITOR_IDS.floorPlan), empty), 'plan');
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.femModel, tabsFor(SAENGINE_EDITOR_IDS.femModel, 'fem.model'), empty), 'analyze');
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.overview, tabsFor(SAENGINE_EDITOR_IDS.overview), empty), 'home');

		const remembered = new Map<string, RibbonTabId>([
			[SAENGINE_EDITOR_IDS.femModel, 'results'],
			[SAENGINE_EDITOR_IDS.floorPlan, 'draft'],
			[SAENGINE_EDITOR_IDS.soil, 'home'],
			[SAENGINE_EDITOR_IDS.overview, 'project'],
		]);
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.femModel, tabsFor(SAENGINE_EDITOR_IDS.femModel, 'fem.model'), remembered), 'analyze');
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.floorPlan, tabsFor(SAENGINE_EDITOR_IDS.floorPlan), remembered), 'draft');
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.soil, tabsFor(SAENGINE_EDITOR_IDS.soil), remembered), 'home');
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.overview, tabsFor(SAENGINE_EDITOR_IDS.overview), remembered), 'project');

		// Falls back to first contextual tab when remembered tab is no longer visible.
		const stale = new Map<string, RibbonTabId>([[SAENGINE_EDITOR_IDS.soil, 'design']]);
		assert.strictEqual(resolveActiveTabForEditor(SAENGINE_EDITOR_IDS.soil, tabsFor(SAENGINE_EDITOR_IDS.soil), stale), 'soil');
	});

	test('computeCollapsedRibbonGroups collapses smallest-priority groups first until toolbar fits', () => {
		const groups = [
			{ key: 'Draw', order: 1, collapsePriority: 40, collapsible: true, expandedWidth: 650, collapsedWidth: 80 },
			{ key: 'Workflow', order: 2, collapsePriority: 5, collapsible: false, expandedWidth: 300, collapsedWidth: 80 },
			{ key: 'Modify', order: 2, collapsePriority: 30, collapsible: true, expandedWidth: 700, collapsedWidth: 80 },
			{ key: 'Layers', order: 3, collapsePriority: 20, collapsible: true, expandedWidth: 420, collapsedWidth: 80 },
			{ key: 'Properties', order: 4, collapsePriority: 10, collapsible: true, expandedWidth: 200, collapsedWidth: 80 },
		];

		// All fit (sum = 2270 + 20 chrome = 2290)
		assert.deepStrictEqual([...computeCollapsedRibbonGroups(groups, 2300, 20)], []);

		// Properties (200->80 saves 120 -> 2170) + Layers (420->80 saves 340 -> 1830) needed to fit 1900; non-collapsible Workflow skipped
		assert.deepStrictEqual([...computeCollapsedRibbonGroups(groups, 1900, 20)], ['Properties', 'Layers']);

		// Tight width collapses Properties, Layers, Modify (1830 - 620 = 1210)
		assert.deepStrictEqual([...computeCollapsedRibbonGroups(groups, 1300, 20)], ['Properties', 'Layers', 'Modify']);
	});

	test('Draft, Annotate, and Blocks & Parametric tabs register their AutoCAD groups and large buttons', () => {
		const buildTabGroups = (menuId: MenuId) => {
			const rawItems = MenuRegistry.getMenuItems(menuId);
			const rawGrouped = new Map<string, (IMenuItem | ISubmenuItem)[]>();

			for (const item of rawItems) {
				const groupKey = item.group ?? '';
				let list = rawGrouped.get(groupKey);
				if (!list) {
					list = [];
					rawGrouped.set(groupKey, list);
				}
				list.push(item);
			}

			const grouped: [string, (MenuItemAction | SubmenuItemAction)[]][] = [];
			for (const [groupKey, items] of rawGrouped) {
				items.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
				const actions: (MenuItemAction | SubmenuItemAction)[] = [];
				for (const item of items) {
					if (isISubmenuItem(item)) {
						const subItems = MenuRegistry.getMenuItems(item.submenu)
							.filter(isIMenuItem)
							.sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
							.map(sub => makeMenuAction(sub.command.id, typeof sub.command.title === 'string' ? sub.command.title : sub.command.title.value));
						actions.push(new SubmenuItemAction(item, undefined, subItems));
					} else if (isIMenuItem(item)) {
						actions.push(makeMenuAction(item.command.id, typeof item.command.title === 'string' ? item.command.title : item.command.title.value));
					}
				}
				grouped.push([groupKey, actions]);
			}

			return buildRibbonGroups(grouped, [], { menuId });
		};

		const largeIdsOf = (menuId: MenuId) => {
			const groups = buildTabGroups(menuId);
			const ids: string[] = [];
			for (const group of groups) {
				for (const col of group.columns) {
					if (col.kind === 'large') {
						ids.push(col.item.kind === 'action' ? col.item.action.id : col.item.action.item.submenu.id);
					}
				}
			}
			return { groups, ids };
		};

		const draft = largeIdsOf(RibbonMenus.Draft);
		assert.deepStrictEqual(
			draft.groups.map(g => g.key),
			DRAFT_RIBBON_GROUPS.filter(g => g.menuId === RibbonMenus.Draft).map(g => g.key),
		);
		assert.deepStrictEqual(draft.ids, [
			'saengine.cad.line',
			'saengine.cad.pline',
			DraftRibbonSubmenus.DrawCircle.id,
			'saengine.cad.move',
			'saengine.cad.copy',
			'saengine.cad.trim',
			'saengine.cad.layer',
		]);

		const annotate = largeIdsOf(RibbonMenus.Annotate);
		assert.deepStrictEqual(
			annotate.groups.map(g => g.key),
			DRAFT_RIBBON_GROUPS.filter(g => g.menuId === RibbonMenus.Annotate).map(g => g.key),
		);
		assert.deepStrictEqual(annotate.ids, [
			DraftRibbonSubmenus.AnnotText.id,
			'saengine.cad.mtext',
			DraftRibbonSubmenus.AnnotDimension.id,
			DraftRibbonSubmenus.AnnotLeader.id,
			'saengine.cad.table',
		]);

		const blocksParam = largeIdsOf(RibbonMenus.BlocksParametric);
		assert.deepStrictEqual(
			blocksParam.groups.map(g => g.key),
			DRAFT_RIBBON_GROUPS.filter(g => g.menuId === RibbonMenus.BlocksParametric).map(g => g.key),
		);
		assert.deepStrictEqual(blocksParam.ids, [
			'saengine.cad.insert',
			DraftRibbonSubmenus.ParamGeometric.id,
			DraftRibbonSubmenus.ParamDimensional.id,
			DraftRibbonSubmenus.UtilMeasure.id,
		]);
	});

	test('Every command mirrored from COMMANDS.md has a registered Draft ribbon action and menu entry', () => {
		// Mirrored from packages/cad-editor/COMMANDS.md (available commands + library commands).
		const COMMANDS_MD_LIST: readonly { readonly cmd: string; readonly actionId: string }[] = [
			// Draw
			{ cmd: 'LINE', actionId: 'saengine.cad.line' },
			{ cmd: 'XLINE', actionId: 'saengine.cad.xline' },
			{ cmd: 'RAY', actionId: 'saengine.cad.ray' },
			{ cmd: 'MLINE', actionId: 'saengine.cad.mline' },
			{ cmd: 'PLINE', actionId: 'saengine.cad.pline' },
			{ cmd: 'POLYGON', actionId: 'saengine.cad.polygon' },
			{ cmd: 'RECTANG', actionId: 'saengine.cad.rectang' },
			{ cmd: 'ARC', actionId: 'saengine.cad.arc' },
			{ cmd: 'ARCX', actionId: 'saengine.cad.arcx' },
			{ cmd: 'CIRCLE', actionId: 'saengine.cad.circle' },
			{ cmd: 'CIRCLEX', actionId: 'saengine.cad.circlex' },
			{ cmd: 'TTR', actionId: 'saengine.cad.ttr' },
			{ cmd: 'TTT', actionId: 'saengine.cad.ttt' },
			{ cmd: 'DONUT', actionId: 'saengine.cad.donut' },
			{ cmd: 'SPLINE', actionId: 'saengine.cad.spline' },
			{ cmd: 'ELLIPSE', actionId: 'saengine.cad.ellipse' },
			{ cmd: 'POINT', actionId: 'saengine.cad.point' },
			{ cmd: 'DIVIDE', actionId: 'saengine.cad.divide' },
			{ cmd: 'MEASURE', actionId: 'saengine.cad.measure' },
			{ cmd: 'REVCLOUD', actionId: 'saengine.cad.revcloud' },
			{ cmd: 'WIPEOUT', actionId: 'saengine.cad.wipeout' },
			{ cmd: 'REGION', actionId: 'saengine.cad.region' },
			{ cmd: 'UNION', actionId: 'saengine.cad.union' },
			{ cmd: 'SUBTRACT', actionId: 'saengine.cad.subtract' },
			{ cmd: 'INTERSECT', actionId: 'saengine.cad.intersect' },
			{ cmd: 'MASSPROP', actionId: 'saengine.cad.massprop' },
			{ cmd: 'BOUNDARY', actionId: 'saengine.cad.boundary' },
			// Annotation & Dimensioning
			{ cmd: 'HATCH', actionId: 'saengine.cad.hatch' },
			{ cmd: 'HATCHEDIT', actionId: 'saengine.cad.hatchedit' },
			{ cmd: 'GRADIENT', actionId: 'saengine.cad.gradient' },
			{ cmd: 'TABLE', actionId: 'saengine.cad.table' },
			{ cmd: 'MTEXT', actionId: 'saengine.cad.mtext' },
			{ cmd: 'TEXT', actionId: 'saengine.cad.text' },
			{ cmd: 'TEXTEDIT', actionId: 'saengine.cad.textedit' },
			{ cmd: 'MLEADER', actionId: 'saengine.cad.mleader' },
			{ cmd: 'QLEADER', actionId: 'saengine.cad.qleader' },
			{ cmd: 'DIMLINEAR', actionId: 'saengine.cad.dimlinear' },
			{ cmd: 'DIMALIGNED', actionId: 'saengine.cad.dimaligned' },
			{ cmd: 'DIMRADIUS', actionId: 'saengine.cad.dimradius' },
			{ cmd: 'DIMDIAMETER', actionId: 'saengine.cad.dimdiameter' },
			{ cmd: 'DIMANGULAR', actionId: 'saengine.cad.dimangular' },
			{ cmd: 'DIMARC', actionId: 'saengine.cad.dimarc' },
			{ cmd: 'DIMORDINATE', actionId: 'saengine.cad.dimordinate' },
			{ cmd: 'DIMCONTINUE', actionId: 'saengine.cad.dimcontinue' },
			{ cmd: 'DIMBASELINE', actionId: 'saengine.cad.dimbaseline' },
			{ cmd: 'QDIM', actionId: 'saengine.cad.qdim' },
			{ cmd: 'DIMSTYLE', actionId: 'saengine.cad.dimstyle' },
			{ cmd: 'DIMEDIT', actionId: 'saengine.cad.dimedit' },
			{ cmd: 'DIMTEDIT', actionId: 'saengine.cad.dimtedit' },
			{ cmd: 'DIMOVERRIDE', actionId: 'saengine.cad.dimoverride' },
			{ cmd: 'DIMSPACE', actionId: 'saengine.cad.dimspace' },
			{ cmd: 'DIMBREAK', actionId: 'saengine.cad.dimbreak' },
			{ cmd: 'DIMJOGGED', actionId: 'saengine.cad.dimjogged' },
			{ cmd: 'DIMJOGLINE', actionId: 'saengine.cad.dimjogline' },
			{ cmd: 'DIMREASSOCIATE', actionId: 'saengine.cad.dimreassociate' },
			{ cmd: 'DIMDISASSOCIATE', actionId: 'saengine.cad.dimdisassociate' },
			{ cmd: 'TOLERANCE', actionId: 'saengine.cad.tolerance' },
			{ cmd: 'CENTERMARK', actionId: 'saengine.cad.centermark' },
			{ cmd: 'CENTERLINE', actionId: 'saengine.cad.centerline' },
			// Modify
			{ cmd: 'MOVE', actionId: 'saengine.cad.move' },
			{ cmd: 'COPY', actionId: 'saengine.cad.copy' },
			{ cmd: 'ROTATE', actionId: 'saengine.cad.rotate' },
			{ cmd: 'SCALE', actionId: 'saengine.cad.scale' },
			{ cmd: 'STRETCH', actionId: 'saengine.cad.stretch' },
			{ cmd: 'MIRROR', actionId: 'saengine.cad.mirror' },
			{ cmd: 'OFFSET', actionId: 'saengine.cad.offset' },
			{ cmd: 'TRIM', actionId: 'saengine.cad.trim' },
			{ cmd: 'EXTEND', actionId: 'saengine.cad.extend' },
			{ cmd: 'FILLET', actionId: 'saengine.cad.fillet' },
			{ cmd: 'CHAMFER', actionId: 'saengine.cad.chamfer' },
			{ cmd: 'BLEND', actionId: 'saengine.cad.blend' },
			{ cmd: 'ARRAYRECT', actionId: 'saengine.cad.arrayrect' },
			{ cmd: 'ARRAYPOLAR', actionId: 'saengine.cad.arraypolar' },
			{ cmd: 'ARRAYPATH', actionId: 'saengine.cad.arraypath' },
			{ cmd: 'ARRAY', actionId: 'saengine.cad.array' },
			{ cmd: 'ARRAYEDIT', actionId: 'saengine.cad.arrayedit' },
			{ cmd: 'ARRAYCLOSE', actionId: 'saengine.cad.arrayclose' },
			{ cmd: 'BREAK', actionId: 'saengine.cad.break' },
			{ cmd: 'BREAKATPOINT', actionId: 'saengine.cad.breakatpoint' },
			{ cmd: 'JOIN', actionId: 'saengine.cad.join' },
			{ cmd: 'EXPLODE', actionId: 'saengine.cad.explode' },
			{ cmd: 'LENGTHEN', actionId: 'saengine.cad.lengthen' },
			{ cmd: 'ALIGN', actionId: 'saengine.cad.align' },
			{ cmd: 'PEDIT', actionId: 'saengine.cad.pedit' },
			{ cmd: 'SPLINEDIT', actionId: 'saengine.cad.splinedit' },
			{ cmd: 'OVERKILL', actionId: 'saengine.cad.overkill' },
			{ cmd: 'ERASE', actionId: 'saengine.cad.erase' },
			{ cmd: 'UNDO', actionId: 'saengine.cad.undo' },
			{ cmd: 'REDO', actionId: 'saengine.cad.redo' },
			// Blocks, Attributes, Xref, Groups
			{ cmd: 'BLOCK', actionId: 'saengine.cad.block' },
			{ cmd: 'INSERT', actionId: 'saengine.cad.insert' },
			{ cmd: 'WBLOCK', actionId: 'saengine.cad.wblock' },
			{ cmd: 'BEDIT', actionId: 'saengine.cad.bedit' },
			{ cmd: 'BSAVE', actionId: 'saengine.cad.bsave' },
			{ cmd: 'BSAVEAS', actionId: 'saengine.cad.bsaveas' },
			{ cmd: 'BCLOSE', actionId: 'saengine.cad.bclose' },
			{ cmd: 'REFEDIT', actionId: 'saengine.cad.refedit' },
			{ cmd: 'REFCLOSE', actionId: 'saengine.cad.refclose' },
			{ cmd: 'XREF', actionId: 'saengine.cad.xref' },
			{ cmd: 'ATTDEF', actionId: 'saengine.cad.attdef' },
			{ cmd: 'ATTEDIT', actionId: 'saengine.cad.attedit' },
			{ cmd: 'ATTSYNC', actionId: 'saengine.cad.attsync' },
			{ cmd: 'BPARAMETER', actionId: 'saengine.cad.bparameter' },
			{ cmd: '-DYNPROP', actionId: 'saengine.cad.dynprop' },
			{ cmd: 'GROUP', actionId: 'saengine.cad.group' },
			{ cmd: 'UNGROUP', actionId: 'saengine.cad.ungroup' },
			// Layers
			{ cmd: 'LAYER', actionId: 'saengine.cad.layer' },
			{ cmd: 'LAYCUR', actionId: 'saengine.cad.laycur' },
			{ cmd: 'LAYISO', actionId: 'saengine.cad.layiso' },
			{ cmd: 'LAYUNISO', actionId: 'saengine.cad.layuniso' },
			{ cmd: 'LAYOFF', actionId: 'saengine.cad.layoff' },
			{ cmd: 'LAYFRZ', actionId: 'saengine.cad.layfrz' },
			{ cmd: 'LAYON', actionId: 'saengine.cad.layon' },
			{ cmd: 'LAYTHW', actionId: 'saengine.cad.laythw' },
			{ cmd: 'LAYMCUR', actionId: 'saengine.cad.laymcur' },
			{ cmd: 'LAYMRG', actionId: 'saengine.cad.laymrg' },
			{ cmd: 'LAYDEL', actionId: 'saengine.cad.laydel' },
			{ cmd: 'LAYLCK', actionId: 'saengine.cad.laylck' },
			{ cmd: 'LAYULK', actionId: 'saengine.cad.layulk' },
			{ cmd: 'LAYERP', actionId: 'saengine.cad.layerp' },
			{ cmd: 'LAYERCLOSE', actionId: 'saengine.cad.layerclose' },
			{ cmd: 'LAYWALK', actionId: 'saengine.cad.laywalk' },
			// Properties
			{ cmd: 'MATCHPROP', actionId: 'saengine.cad.matchprop' },
			{ cmd: 'CHPROP', actionId: 'saengine.cad.chprop' },
			{ cmd: 'PROPERTIES', actionId: 'saengine.cad.properties' },
			{ cmd: 'COLOR', actionId: 'saengine.cad.color' },
			{ cmd: 'LWEIGHT', actionId: 'saengine.cad.lweight' },
			{ cmd: 'LINETYPE', actionId: 'saengine.cad.linetype' },
			{ cmd: 'LTSCALE', actionId: 'saengine.cad.ltscale' },
			{ cmd: 'CELTSCALE', actionId: 'saengine.cad.celtscale' },
			// Selection, Fields, Find, Inquiry, Styles, Maintenance, View
			{ cmd: 'SELECT', actionId: 'saengine.cad.select' },
			{ cmd: 'SELECTALL', actionId: 'saengine.cad.selectall' },
			{ cmd: 'QSELECT', actionId: 'saengine.cad.qselect' },
			{ cmd: 'SELECTSIMILAR', actionId: 'saengine.cad.selectsimilar' },
			{ cmd: 'LASSO', actionId: 'saengine.cad.lasso' },
			{ cmd: 'SELECTIONCYCLING', actionId: 'saengine.cad.selectioncycling' },
			{ cmd: 'FIND', actionId: 'saengine.cad.find' },
			{ cmd: 'FIELD', actionId: 'saengine.cad.field' },
			{ cmd: 'UPDATEFIELD', actionId: 'saengine.cad.updatefield' },
			{ cmd: 'DIST', actionId: 'saengine.cad.dist' },
			{ cmd: 'AREA', actionId: 'saengine.cad.area' },
			{ cmd: 'ID', actionId: 'saengine.cad.id' },
			{ cmd: 'LIST', actionId: 'saengine.cad.list' },
			{ cmd: 'MEASUREGEOM', actionId: 'saengine.cad.measuregeom' },
			{ cmd: 'UNITS', actionId: 'saengine.cad.units' },
			{ cmd: 'STYLE', actionId: 'saengine.cad.style' },
			{ cmd: 'MLSTYLE', actionId: 'saengine.cad.mlstyle' },
			{ cmd: 'TABLESTYLE', actionId: 'saengine.cad.tablestyle' },
			{ cmd: 'MLEADERSTYLE', actionId: 'saengine.cad.mleaderstyle' },
			{ cmd: 'PURGE', actionId: 'saengine.cad.purge' },
			{ cmd: 'AUDIT', actionId: 'saengine.cad.audit' },
			{ cmd: 'RECOVER', actionId: 'saengine.cad.recover' },
			{ cmd: 'DATAEXTRACTION', actionId: 'saengine.cad.dataextraction' },
			{ cmd: 'ZOOM', actionId: 'saengine.cad.zoom' },
			{ cmd: 'PAN', actionId: 'saengine.cad.pan' },
			{ cmd: 'REGEN', actionId: 'saengine.cad.regen' },
			{ cmd: 'DRAWORDER', actionId: 'saengine.cad.draworder' },
			{ cmd: 'TEXTTOFRONT', actionId: 'saengine.cad.texttofront' },
			{ cmd: 'HATCHTOBACK', actionId: 'saengine.cad.hatchtoback' },
			// Parametric
			{ cmd: 'GEOMCONSTRAINT', actionId: 'saengine.cad.geomconstraint' },
			{ cmd: 'GCCOINCIDENT', actionId: 'saengine.cad.gccoincident' },
			{ cmd: 'GCCOLLINEAR', actionId: 'saengine.cad.gccollinear' },
			{ cmd: 'GCCONCENTRIC', actionId: 'saengine.cad.gcconcentric' },
			{ cmd: 'GCPARALLEL', actionId: 'saengine.cad.gcparallel' },
			{ cmd: 'GCPERPENDICULAR', actionId: 'saengine.cad.gcperpendicular' },
			{ cmd: 'GCHORIZONTAL', actionId: 'saengine.cad.gchorizontal' },
			{ cmd: 'GCVERTICAL', actionId: 'saengine.cad.gcvertical' },
			{ cmd: 'GCTANGENT', actionId: 'saengine.cad.gctangent' },
			{ cmd: 'GCEQUAL', actionId: 'saengine.cad.gcequal' },
			{ cmd: 'GCSYMMETRIC', actionId: 'saengine.cad.gcsymmetric' },
			{ cmd: 'GCFIX', actionId: 'saengine.cad.gcfix' },
			{ cmd: 'DIMCONSTRAINT', actionId: 'saengine.cad.dimconstraint' },
			{ cmd: 'DCLINEAR', actionId: 'saengine.cad.dclinear' },
			{ cmd: 'DCHORIZONTAL', actionId: 'saengine.cad.dchorizontal' },
			{ cmd: 'DCVERTICAL', actionId: 'saengine.cad.dcvertical' },
			{ cmd: 'DCALIGNED', actionId: 'saengine.cad.dcaligned' },
			{ cmd: 'DCANGULAR', actionId: 'saengine.cad.dcangular' },
			{ cmd: 'DCRADIAL', actionId: 'saengine.cad.dcradial' },
			{ cmd: 'DCDIAMETER', actionId: 'saengine.cad.dcdiameter' },
			{ cmd: 'AUTOCONSTRAIN', actionId: 'saengine.cad.autoconstrain' },
			{ cmd: 'PARAMETERS', actionId: 'saengine.cad.parameters' },
			{ cmd: 'DELCONSTRAINT', actionId: 'saengine.cad.delconstraint' },
			{ cmd: 'CONSTRAINTBAR', actionId: 'saengine.cad.constraintbar' },
		];

		// Collect every command ID reachable from the contextual CAD tabs (direct or submenu).
		const reachableDraftCommandIds = new Set<string>();
		for (const cadMenuId of [RibbonMenus.Draft, RibbonMenus.Annotate, RibbonMenus.BlocksParametric]) {
			for (const entry of MenuRegistry.getMenuItems(cadMenuId)) {
				if (isIMenuItem(entry)) {
					reachableDraftCommandIds.add(entry.command.id);
				} else if (isISubmenuItem(entry)) {
					for (const sub of MenuRegistry.getMenuItems(entry.submenu)) {
						if (isIMenuItem(sub)) {
							reachableDraftCommandIds.add(sub.command.id);
						}
					}
				}
			}
		}

		for (const { cmd, actionId } of COMMANDS_MD_LIST) {
			assert.ok(CommandsRegistry.getCommand(actionId), `Missing registered command ${actionId} for CAD command ${cmd}`);
			assert.ok(reachableDraftCommandIds.has(actionId), `Missing Draft ribbon menu button ${actionId} for CAD command ${cmd}`);
		}

		const seenIds = new Set<string>();
		for (const spec of CAD_DRAFT_COMMANDS) {
			assert.ok(!seenIds.has(spec.id), `Duplicate Draft CAD action id: ${spec.id}`);
			seenIds.add(spec.id);
			assert.ok(spec.icon.id, `Missing Codicon for ${spec.id}`);
			assert.ok(spec.tooltip.value.toUpperCase().includes(spec.canonicalName.replace(/^-/, '')), `Tooltip for ${spec.id} should mention ${spec.canonicalName}`);
		}
	});

	test('RibbonSelectModel manages items, selection, headings, disabled state, and visibility', () => {
		const store = new DisposableStore();
		try {
			const events: string[] = [];
			let changes = 0;
			const select = store.add(new RibbonSelectModel({
				id: 'test.select',
				ariaLabel: 'Story',
				label: 'Story',
				items: [
					{ id: 'h1', label: 'Group', isHeading: true },
					{ id: 's1', label: 'Story 1' },
					{ id: 's2', label: 'Story 2', disabled: true },
					{ id: 's3', label: 'Story 3' },
				],
			}));
			store.add(select.onDidChange(() => { changes++; }));
			store.add(select.onDidSelect(e => events.push(`${e.id}@${e.index}`)));

			assert.strictEqual(select.selectedId, 's1');
			assert.strictEqual(select.selectedIndex, 1);

			select.select('h1', true);
			select.select('s2', true);
			assert.strictEqual(select.selectedId, 's1');
			assert.deepStrictEqual(events, []);

			select.select(3, true);
			assert.strictEqual(select.selectedId, 's3');
			assert.deepStrictEqual(events, ['s3@3']);

			select.disabled = true;
			select.select('s1', true);
			assert.strictEqual(select.selectedId, 's3');

			// Programmatic sync via setter works silently even while disabled.
			select.selectedId = 's1';
			assert.strictEqual(select.selectedId, 's1');
			assert.deepStrictEqual(events, ['s3@3']);

			select.visible = false;
			assert.strictEqual(select.visible, false);
			select.setItems([{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], 'b');
			assert.strictEqual(select.selectedId, 'b');
			assert.ok(changes >= 4);
		} finally {
			store.dispose();
		}
	});

	test('RibbonSegmentedModel, RibbonToggleModel, and RibbonSliderModel sync state and fire user events', () => {
		const store = new DisposableStore();
		try {
			const segEvents: string[] = [];
			const seg = store.add(new RibbonSegmentedModel({
				id: 'test.seg',
				ariaLabel: 'View',
				items: [
					{ id: 'plan', label: 'Plan' },
					{ id: '3d', label: '3D' },
				],
				selectedId: 'plan',
			}));
			store.add(seg.onDidSelect(id => segEvents.push(id)));
			seg.setItemDisabled('3d', true);
			seg.select('3d', true);
			assert.strictEqual(seg.selectedId, 'plan');
			seg.setItemDisabled('3d', false);
			seg.select('3d', true);
			assert.strictEqual(seg.selectedId, '3d');
			seg.disabled = true;
			seg.selectedId = undefined;
			assert.strictEqual(seg.selectedId, undefined);
			assert.deepStrictEqual(segEvents, ['3d']);

			const toggleEvents: boolean[] = [];
			const toggle = store.add(new RibbonToggleModel({ id: 'test.toggle', label: 'Labels', checked: false }));
			store.add(toggle.onDidToggle(val => toggleEvents.push(val)));
			toggle.setChecked(true, true);
			toggle.disabled = true;
			toggle.setChecked(false, true);
			assert.strictEqual(toggle.checked, true);
			toggle.checked = false;
			assert.strictEqual(toggle.checked, false);
			assert.deepStrictEqual(toggleEvents, [true]);

			const sliderValues: number[] = [];
			const slider = store.add(new RibbonSliderModel({ id: 'test.slider', label: 'Scale', ariaLabel: 'Scale', min: -2, max: 4, step: 0.5, value: 0, resetValue: 0 }));
			store.add(slider.onDidChangeValue(v => sliderValues.push(v)));
			slider.setValue(10, true);
			assert.strictEqual(slider.value, 4);
			slider.value = -5;
			assert.strictEqual(slider.value, -2);
			slider.setRange(0, 10, 1);
			slider.value = 3;
			assert.strictEqual(slider.value, 3);
			assert.deepStrictEqual(sliderValues, [4]);
		} finally {
			store.dispose();
		}
	});

	test('Ribbon control helpers compute visibility, collapse actions, dedupe editor actions, and resolve target tab', () => {
		const store = new DisposableStore();
		try {
			const select = store.add(new RibbonSelectModel({
				id: 'test.collapse.select',
				ariaLabel: 'Result',
				label: 'Result',
				items: [
					{ id: 'h', label: 'Static', isHeading: true },
					{ id: 'dl', label: 'Dead' },
					{ id: 'll', label: 'Live' },
				],
				selectedId: 'dl',
			}));
			const toggle = store.add(new RibbonToggleModel({ id: 'test.collapse.toggle', label: 'Labels', icon: Codicon.tag, checked: true }));
			const hidden = store.add(new RibbonToggleModel({ id: 'test.collapse.hidden', label: 'Hidden', visible: false }));
			const slider = store.add(new RibbonSliderModel({ id: 'test.collapse.slider', label: 'Scale', ariaLabel: 'Scale', min: -1, max: 2, value: 0, resetValue: 0, valueText: '1x' }));
			const row = store.add(new RibbonInlineRowControl({ id: 'test.collapse.row', controls: [toggle, hidden] }));

			assert.strictEqual(hasVisibleControls([hidden]), false);
			assert.strictEqual(hasVisibleControls([row]), true);
			assert.strictEqual(controlVisibilitySignature([select, row, slider]), '1,1(1,0),1');

			const collapsed = collectControlCollapsedActions([select, row, slider], store);
			assert.strictEqual(collapsed.length, 3);
			assert.ok(collapsed[0] instanceof SubmenuAction);
			assert.strictEqual(collapsed[1].id, 'test.collapse.toggle');
			assert.ok(collapsed[2] instanceof SubmenuAction);

			const a1 = store.add(new Action('cmd.keep', 'Keep'));
			const a2 = store.add(new Action('cmd.dup', 'Dup'));
			const a3 = store.add(new Action('cmd.sec', 'Secondary'));
			const deduped = dedupeEditorFrameActions(
				[a2, new Separator(), a1],
				[new Separator(), a2, new Separator(), a3, new Separator()],
				new Set(['cmd.dup']),
			);
			assert.deepStrictEqual(deduped.primary.map(a => a.id), ['cmd.keep']);
			assert.deepStrictEqual(deduped.secondary.map(a => a.id), ['cmd.sec']);

			const femTabs = getVisibleRibbonTabs(contextFor({
				[ActiveEditorContext.key]: SAENGINE_EDITOR_IDS.femModel,
				[SAENGINE_SUB_VIEW_CONTEXT]: 'fem.model',
			}));
			assert.strictEqual(resolveEditorToolbarTargetTab(femTabs), 'analyze');
			const overviewTabs = getVisibleRibbonTabs(contextFor({ [ActiveEditorContext.key]: SAENGINE_EDITOR_IDS.overview }));
			assert.strictEqual(resolveEditorToolbarTargetTab(overviewTabs), 'project');
		} finally {
			store.dispose();
		}
	});
});
