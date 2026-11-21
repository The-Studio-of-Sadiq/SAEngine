/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { ICommandAction } from '../../../../../platform/action/common/action.js';
import { IMenuItem, isIMenuItem, isISubmenuItem, ISubmenuItem, MenuId, MenuItemAction, MenuRegistry, SubmenuItemAction } from '../../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../../platform/commands/common/commands.js';
import { IContextKeyService } from '../../../../../platform/contextkey/common/contextkey.js';
import { CAD_DRAFT_COMMANDS, DRAFT_RIBBON_GROUPS, DraftRibbonSubmenus } from '../../../saengineCad/browser/cadDraftCommands.js';
import '../../../saengineCad/browser/cadDraftRibbon.contribution.js';
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
	RibbonMenus,
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

	test('Draft ribbon registers all 9 AutoCAD groups in order and highlights the 11 most-used large buttons', () => {
		const rawItems = MenuRegistry.getMenuItems(RibbonMenus.Draft);
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

		const groups = buildRibbonGroups(grouped, [], { menuId: RibbonMenus.Draft });
		assert.deepStrictEqual(
			groups.map(g => g.key),
			DRAFT_RIBBON_GROUPS.map(g => g.key),
		);

		const largeIds: string[] = [];
		for (const group of groups) {
			for (const col of group.columns) {
				if (col.kind === 'large') {
					largeIds.push(col.item.kind === 'action' ? col.item.action.id : col.item.action.item.submenu.id);
				}
			}
		}
		assert.deepStrictEqual(largeIds, [
			'saengine.cad.line',
			'saengine.cad.pline',
			DraftRibbonSubmenus.DrawCircle.id,
			'saengine.cad.move',
			'saengine.cad.copy',
			'saengine.cad.trim',
			DraftRibbonSubmenus.AnnotText.id,
			DraftRibbonSubmenus.AnnotDimension.id,
			DraftRibbonSubmenus.AnnotHatch.id,
			'saengine.cad.layer',
			'saengine.cad.insert',
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

		// Collect every command ID reachable from RibbonMenus.Draft (direct or submenu).
		const reachableDraftCommandIds = new Set<string>();
		for (const entry of MenuRegistry.getMenuItems(RibbonMenus.Draft)) {
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
});
