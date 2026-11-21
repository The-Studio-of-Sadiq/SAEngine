/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { MenuId, MenuItemAction, SubmenuItemAction } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr, ContextKeyExpression, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';

/** Context key active while a Floor Plan or CAD drawing editor is focused. */
export const SAENGINE_DRAFT_CONTEXT = 'saengineDraftActive';

export const DraftActiveContext = new RawContextKey<boolean>(
	SAENGINE_DRAFT_CONTEXT,
	false,
	localize('saengine.draftActive', "Whether a SAEngine Floor Plan or CAD drawing editor is active")
);

/** Context key identifying the engineering domain of an active SAEngine U3 data panel editor. */
export const SAENGINE_DATA_PANEL_PART_CONTEXT = 'saengineDataPanelPart';

export const DataPanelPartContext = new RawContextKey<string>(
	SAENGINE_DATA_PANEL_PART_CONTEXT,
	'',
	localize('saengine.dataPanelPart', "The engineering domain of the active SAEngine U3 data panel")
);

/** SAEngine editor pane IDs used in contextual ribbon `when` rules (plain strings: no cross-contrib imports). */
export const SAENGINE_EDITOR_IDS = {
	soil: 'workbench.editor.saengine.soil',
	settings: 'workbench.editor.saengine.settings',
	codePacks: 'workbench.editor.saengine.codePacks',
	library: 'workbench.editor.saengine.library',
	sectionDesigner: 'workbench.editor.saengine.sectionDesigner',
	floorPlan: 'workbench.editor.saengine.floorPlan',
	grids: 'workbench.editor.saengine.grids',
	membersTable: 'workbench.editor.saengine.membersTable',
	structureModeler: 'workbench.editor.saengine.structureModeler',
	structure: 'workbench.editor.saengine.structure',
	cad: 'workbench.editor.saengine.cad',
	architecture: 'workbench.editor.saengine.architecture',
	building: 'workbench.editor.saengine.building',
	mep: 'workbench.editor.saengine.mep',
	femModel: 'workbench.editor.saengine.femModel',
	femResults: 'workbench.editor.saengine.femResults',
	femCfdWind: 'workbench.editor.saengine.femCfdWind',
	femDesignProposal: 'workbench.editor.saengine.femDesignProposal',
	femStrutAndTie: 'workbench.editor.saengine.femStrutAndTie',
	substructure: 'workbench.editor.saengine.substructure',
	boq: 'workbench.editor.saengine.boq',
	rates: 'workbench.editor.saengine.rates',
	exports: 'workbench.editor.saengine.exports',
	drawingPreview: 'workbench.editor.saengine.drawingPreview',
	reportTemplate: 'workbench.editor.saengine.reportTemplate',
	worksheet: 'workbench.editor.saengine.worksheet',
	officeTools: 'workbench.editor.saengine.officeTools',
	studies: 'workbench.editor.saengine.studies',
	graph: 'workbench.editor.saengine.graph',
	dataPanel: 'workbench.editor.saengine.dataPanel',
	overview: 'workbench.editor.saengine.overview',
} as const;

export type RibbonTabId =
	| 'home'
	| 'project'
	| 'soil'
	| 'settings'
	| 'library'
	| 'plan'
	| 'draft'
	| 'annotate'
	| 'blocksParametric'
	| 'architecture'
	| 'bim3d'
	| 'mep'
	| 'analyze'
	| 'results'
	| 'design'
	| 'foundations'
	| 'boq'
	| 'output'
	| 'documents'
	| 'studies';

/**
 * MenuId per ribbon tab. Other contributions add buttons via `registerAction2` or
 * `MenuRegistry.appendMenuItem` using `group: '<order>_<GroupName>'`, e.g. `'3_Electrical'`.
 */
export const RibbonMenus = {
	Home: MenuId.for('SaengineRibbon.Home'),
	Project: MenuId.for('SaengineRibbon.Project'),
	Soil: MenuId.for('SaengineRibbon.Soil'),
	Settings: MenuId.for('SaengineRibbon.Settings'),
	Library: MenuId.for('SaengineRibbon.Library'),
	Plan: MenuId.for('SaengineRibbon.Plan'),
	Draft: MenuId.for('SaengineRibbon.Draft'),
	Annotate: MenuId.for('SaengineRibbon.Annotate'),
	BlocksParametric: MenuId.for('SaengineRibbon.BlocksParametric'),
	Architecture: MenuId.for('SaengineRibbon.Architecture'),
	Bim3D: MenuId.for('SaengineRibbon.Bim3D'),
	MEP: MenuId.for('SaengineRibbon.MEP'),
	Analyze: MenuId.for('SaengineRibbon.Analyze'),
	Results: MenuId.for('SaengineRibbon.Results'),
	Design: MenuId.for('SaengineRibbon.Design'),
	Foundations: MenuId.for('SaengineRibbon.Foundations'),
	BOQ: MenuId.for('SaengineRibbon.BOQ'),
	Output: MenuId.for('SaengineRibbon.Output'),
	Documents: MenuId.for('SaengineRibbon.Documents'),
	Studies: MenuId.for('SaengineRibbon.Studies'),
} as const;

export interface IRibbonTabDescriptor {
	readonly id: RibbonTabId;
	readonly label: string;
	readonly menuId: MenuId;
	readonly contextual?: boolean;
	readonly contextualTag?: string;
	readonly when?: ContextKeyExpression;
}

function anyOf(exprs: readonly [ContextKeyExpression, ...ContextKeyExpression[]]): ContextKeyExpression {
	return ContextKeyExpr.or(...exprs) ?? exprs[0];
}

function allOf(exprs: readonly [ContextKeyExpression, ...ContextKeyExpression[]]): ContextKeyExpression {
	return ContextKeyExpr.and(...exprs) ?? exprs[0];
}

function editorWhen(editorIds: readonly [string, ...string[]], dataPanelPart?: string): ContextKeyExpression {
	const checks: [ContextKeyExpression, ...ContextKeyExpression[]] = [
		ActiveEditorContext.isEqualTo(editorIds[0]),
		...editorIds.slice(1).map(id => ActiveEditorContext.isEqualTo(id)),
	];
	if (dataPanelPart) {
		const panelExpr = ContextKeyExpr.and(
			ActiveEditorContext.isEqualTo(SAENGINE_EDITOR_IDS.dataPanel),
			DataPanelPartContext.isEqualTo(dataPanelPart),
		);
		if (panelExpr) {
			checks.push(panelExpr);
		}
	}
	return anyOf(checks);
}

const SPECIALIZED_EDITOR_IDS: readonly [string, ...string[]] = [
	SAENGINE_EDITOR_IDS.soil,
	SAENGINE_EDITOR_IDS.settings,
	SAENGINE_EDITOR_IDS.codePacks,
	SAENGINE_EDITOR_IDS.library,
	SAENGINE_EDITOR_IDS.sectionDesigner,
	SAENGINE_EDITOR_IDS.floorPlan,
	SAENGINE_EDITOR_IDS.grids,
	SAENGINE_EDITOR_IDS.membersTable,
	SAENGINE_EDITOR_IDS.structureModeler,
	SAENGINE_EDITOR_IDS.structure,
	SAENGINE_EDITOR_IDS.cad,
	SAENGINE_EDITOR_IDS.architecture,
	SAENGINE_EDITOR_IDS.building,
	SAENGINE_EDITOR_IDS.mep,
	SAENGINE_EDITOR_IDS.femModel,
	SAENGINE_EDITOR_IDS.femResults,
	SAENGINE_EDITOR_IDS.femCfdWind,
	SAENGINE_EDITOR_IDS.femDesignProposal,
	SAENGINE_EDITOR_IDS.femStrutAndTie,
	SAENGINE_EDITOR_IDS.substructure,
	SAENGINE_EDITOR_IDS.boq,
	SAENGINE_EDITOR_IDS.rates,
	SAENGINE_EDITOR_IDS.exports,
	SAENGINE_EDITOR_IDS.drawingPreview,
	SAENGINE_EDITOR_IDS.reportTemplate,
	SAENGINE_EDITOR_IDS.worksheet,
	SAENGINE_EDITOR_IDS.officeTools,
	SAENGINE_EDITOR_IDS.studies,
	SAENGINE_EDITOR_IDS.graph,
];

const SPECIALIZED_PANEL_PARTS: readonly [string, ...string[]] = [
	'soil',
	'settings',
	'library',
	'plan',
	'architecture',
	'bim3d',
	'mep',
	'fem',
	'foundations',
	'boq',
	'output',
	'documents',
	'studies',
];

const NOT_SPECIALIZED_PANEL = allOf([
	DataPanelPartContext.notEqualsTo(SPECIALIZED_PANEL_PARTS[0]),
	...SPECIALIZED_PANEL_PARTS.slice(1).map(part => DataPanelPartContext.notEqualsTo(part)),
]);

const PROJECT_TAB_WHEN: ContextKeyExpression = allOf([
	ActiveEditorContext.notEqualsTo(SPECIALIZED_EDITOR_IDS[0]),
	...SPECIALIZED_EDITOR_IDS.slice(1).map(id => ActiveEditorContext.notEqualsTo(id)),
	anyOf([ActiveEditorContext.notEqualsTo(SAENGINE_EDITOR_IDS.dataPanel), NOT_SPECIALIZED_PANEL]),
]);

const DRAFT_WHEN = editorWhen([SAENGINE_EDITOR_IDS.floorPlan, SAENGINE_EDITOR_IDS.cad]);
const FEM_WHEN = editorWhen([
	SAENGINE_EDITOR_IDS.femModel,
	SAENGINE_EDITOR_IDS.femResults,
	SAENGINE_EDITOR_IDS.femCfdWind,
	SAENGINE_EDITOR_IDS.femDesignProposal,
	SAENGINE_EDITOR_IDS.femStrutAndTie,
], 'fem');

export const RIBBON_TABS: readonly IRibbonTabDescriptor[] = [
	{ id: 'home', label: localize('ribbon.tab.home', "Home"), menuId: RibbonMenus.Home },
	{
		id: 'project',
		label: localize('ribbon.tab.project', "Project"),
		menuId: RibbonMenus.Project,
		when: PROJECT_TAB_WHEN,
	},
	{
		id: 'soil',
		label: localize('ribbon.tab.soil', "Soil Report"),
		menuId: RibbonMenus.Soil,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.soil], 'soil'),
	},
	{
		id: 'settings',
		label: localize('ribbon.tab.settings', "Settings"),
		menuId: RibbonMenus.Settings,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.settings, SAENGINE_EDITOR_IDS.codePacks], 'settings'),
	},
	{
		id: 'library',
		label: localize('ribbon.tab.library', "Library"),
		menuId: RibbonMenus.Library,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.library, SAENGINE_EDITOR_IDS.sectionDesigner], 'library'),
	},
	{
		id: 'plan',
		label: localize('ribbon.tab.plan', "Plan"),
		menuId: RibbonMenus.Plan,
		contextual: true,
		when: editorWhen([
			SAENGINE_EDITOR_IDS.floorPlan,
			SAENGINE_EDITOR_IDS.grids,
			SAENGINE_EDITOR_IDS.membersTable,
			SAENGINE_EDITOR_IDS.structureModeler,
			SAENGINE_EDITOR_IDS.structure,
		], 'plan'),
	},
	{
		id: 'draft',
		label: localize('ribbon.tab.draft', "Draft"),
		menuId: RibbonMenus.Draft,
		contextual: true,
		contextualTag: localize('ribbon.tab.draftTag', "CAD"),
		when: DRAFT_WHEN,
	},
	{
		id: 'annotate',
		label: localize('ribbon.tab.annotate', "Annotate"),
		menuId: RibbonMenus.Annotate,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'blocksParametric',
		label: localize('ribbon.tab.blocksParametric', "Blocks & Parametric"),
		menuId: RibbonMenus.BlocksParametric,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'architecture',
		label: localize('ribbon.tab.architecture', "Architecture"),
		menuId: RibbonMenus.Architecture,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.architecture], 'architecture'),
	},
	{
		id: 'bim3d',
		label: localize('ribbon.tab.bim3d', "3D View"),
		menuId: RibbonMenus.Bim3D,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.building], 'bim3d'),
	},
	{
		id: 'mep',
		label: localize('ribbon.tab.mep', "MEP"),
		menuId: RibbonMenus.MEP,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.mep], 'mep'),
	},
	{
		id: 'analyze',
		label: localize('ribbon.tab.analyze', "Analyze"),
		menuId: RibbonMenus.Analyze,
		contextual: true,
		when: FEM_WHEN,
	},
	{
		id: 'results',
		label: localize('ribbon.tab.results', "Results"),
		menuId: RibbonMenus.Results,
		contextual: true,
		when: FEM_WHEN,
	},
	{
		id: 'design',
		label: localize('ribbon.tab.design', "Design"),
		menuId: RibbonMenus.Design,
		contextual: true,
		when: FEM_WHEN,
	},
	{
		id: 'foundations',
		label: localize('ribbon.tab.foundations', "Foundations"),
		menuId: RibbonMenus.Foundations,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.substructure], 'foundations'),
	},
	{
		id: 'boq',
		label: localize('ribbon.tab.boq', "BOQ"),
		menuId: RibbonMenus.BOQ,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.boq, SAENGINE_EDITOR_IDS.rates], 'boq'),
	},
	{
		id: 'output',
		label: localize('ribbon.tab.output', "Output"),
		menuId: RibbonMenus.Output,
		contextual: true,
		when: editorWhen([SAENGINE_EDITOR_IDS.exports], 'output'),
	},
	{
		id: 'documents',
		label: localize('ribbon.tab.documents', "Documents"),
		menuId: RibbonMenus.Documents,
		contextual: true,
		when: editorWhen([
			SAENGINE_EDITOR_IDS.drawingPreview,
			SAENGINE_EDITOR_IDS.reportTemplate,
			SAENGINE_EDITOR_IDS.worksheet,
		], 'documents'),
	},
	{
		id: 'studies',
		label: localize('ribbon.tab.studies', "Studies"),
		menuId: RibbonMenus.Studies,
		contextual: true,
		when: editorWhen([
			SAENGINE_EDITOR_IDS.officeTools,
			SAENGINE_EDITOR_IDS.studies,
			SAENGINE_EDITOR_IDS.graph,
		], 'studies'),
	},
];

/** Maps a U3 data panel id and optional `part` descriptor property to a contextual ribbon domain key. */
export function resolveDataPanelPart(panelId: string | undefined, descriptorPart: string | undefined): string {
	if (!panelId) {
		return '';
	}
	if (panelId.startsWith('saengine.studies.')) {
		return 'studies';
	}
	if (panelId.startsWith('saengine.drawings.')) {
		return 'documents';
	}
	switch (descriptorPart) {
		case 'exports': return 'output';
		case 'substructure': return 'foundations';
		case 'bim': return 'bim3d';
		case 'floorPlan':
		case 'structure': return 'plan';
		case 'materials':
		case 'objects': return 'library';
		default: return descriptorPart ?? '';
	}
}

/** Returns the ribbon tabs whose `when` rule matches the current context key state. */
export function getVisibleRibbonTabs(
	contextKeyService: Pick<IContextKeyService, 'contextMatchesRules'>,
	tabs: readonly IRibbonTabDescriptor[] = RIBBON_TABS,
): readonly IRibbonTabDescriptor[] {
	return tabs.filter(tab => !tab.when || contextKeyService.contextMatchesRules(tab.when));
}

/**
 * Picks the ribbon tab to show after switching editors: returns the remembered tab for
 * `editorKey` if still visible, otherwise the first contextual tab, falling back to the first visible tab.
 */
export function resolveActiveTabForEditor(
	editorKey: string,
	visibleTabs: readonly IRibbonTabDescriptor[],
	rememberedByEditor: ReadonlyMap<string, RibbonTabId>,
): RibbonTabId {
	const remembered = rememberedByEditor.get(editorKey);
	if (remembered && visibleTabs.some(tab => tab.id === remembered)) {
		return remembered;
	}
	return visibleTabs.find(tab => tab.contextual)?.id ?? visibleTabs[0]?.id ?? 'home';
}

export type RibbonButtonSize = 'large' | 'small';

export interface IRibbonItemHint {
	readonly size?: RibbonButtonSize;
	readonly label?: string;
	readonly primaryCommandId?: string;
	readonly renderCustom?: (container: HTMLElement, instantiationService: IInstantiationService, action: MenuItemAction) => IDisposable;
}

export interface IRibbonCustomGroup {
	readonly tabId: RibbonTabId;
	readonly group: string;
	readonly label: string;
	readonly render: (container: HTMLElement, instantiationService: IInstantiationService) => IDisposable;
}

const itemHints = new Map<string, IRibbonItemHint>();
const scopedItemHints = new Map<string, IRibbonItemHint>();
const groupLabels = new Map<string, string>();
const groupPriorities = new Map<string, number>();
const customGroups = new Map<RibbonTabId, IRibbonCustomGroup[]>();
const registryChangeEmitter = new Emitter<void>();

export const onDidChangeRibbonRegistry: Event<void> = registryChangeEmitter.event;

function scopedHintKey(menuId: MenuId, id: string): string {
	return `${menuId.id}\0${id}`;
}

/** Registers display hints (size, short label, split primary command) for a command or submenu id. */
export function registerRibbonItemHint(id: string, hint: IRibbonItemHint, menuId?: MenuId): IDisposable {
	const map = menuId ? scopedItemHints : itemHints;
	const key = menuId ? scopedHintKey(menuId, id) : id;
	const previous = map.get(key);
	map.set(key, hint);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (map.get(key) === hint) {
			if (previous !== undefined) {
				map.set(key, previous);
			} else {
				map.delete(key);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonItemHint(id: string, menuId?: MenuId): IRibbonItemHint | undefined {
	if (menuId) {
		const scoped = scopedItemHints.get(scopedHintKey(menuId, id));
		if (scoped) {
			return scoped;
		}
	}
	return itemHints.get(id);
}

/** Registers a localized group label for a group key (the suffix after `<order>_`). */
export function registerRibbonGroupLabel(groupKey: string, label: string): IDisposable {
	const previous = groupLabels.get(groupKey);
	groupLabels.set(groupKey, label);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (groupLabels.get(groupKey) === label) {
			if (previous !== undefined) {
				groupLabels.set(groupKey, previous);
			} else {
				groupLabels.delete(groupKey);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonGroupLabel(groupKey: string): string | undefined {
	return groupLabels.get(groupKey);
}

/** Registers a collapse priority for a group key (smaller values collapse first when space is tight). */
export function registerRibbonGroupPriority(groupKey: string, priority: number): IDisposable {
	const previous = groupPriorities.get(groupKey);
	groupPriorities.set(groupKey, priority);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (groupPriorities.get(groupKey) === priority) {
			if (previous !== undefined) {
				groupPriorities.set(groupKey, previous);
			} else {
				groupPriorities.delete(groupKey);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonGroupPriority(groupKey: string): number | undefined {
	return groupPriorities.get(groupKey);
}

/** Registers a custom-rendered ribbon group (such as Home's Workflow stepper). */
export function registerRibbonCustomGroup(group: IRibbonCustomGroup): IDisposable {
	let list = customGroups.get(group.tabId);
	if (!list) {
		list = [];
		customGroups.set(group.tabId, list);
	}
	list.push(group);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		const entries = customGroups.get(group.tabId);
		if (!entries) {
			return;
		}
		const idx = entries.indexOf(group);
		if (idx >= 0) {
			entries.splice(idx, 1);
			if (!entries.length) {
				customGroups.delete(group.tabId);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonCustomGroups(tabId: RibbonTabId): readonly IRibbonCustomGroup[] {
	return customGroups.get(tabId) ?? [];
}

/** Maximum small buttons stacked vertically in one ribbon column. */
export const RIBBON_SMALL_STACK_MAX = 3;

export interface IParsedRibbonGroup {
	readonly raw: string;
	readonly order: number;
	readonly key: string;
	readonly label: string;
}

/** Parses `<order>_<GroupName>` menu group identifiers into sort order, key, and display label. */
export function parseRibbonGroup(rawGroup: string, labelLookup: (key: string) => string | undefined = getRibbonGroupLabel): IParsedRibbonGroup {
	if (rawGroup === 'navigation') {
		return { raw: rawGroup, order: -1, key: 'navigation', label: labelLookup('navigation') ?? localize('ribbon.group.general', "General") };
	}
	if (!rawGroup) {
		return { raw: rawGroup, order: Number.MAX_SAFE_INTEGER, key: '', label: labelLookup('') ?? localize('ribbon.group.more', "More") };
	}
	const match = /^(\d+)_(.+)$/.exec(rawGroup);
	if (match) {
		const order = Number(match[1]);
		const key = match[2];
		return { raw: rawGroup, order, key, label: labelLookup(key) ?? key };
	}
	return { raw: rawGroup, order: 100, key: rawGroup, label: labelLookup(rawGroup) ?? rawGroup };
}

export type RibbonColumn<T> =
	| { readonly kind: 'large'; readonly item: T }
	| { readonly kind: 'stack'; readonly items: readonly T[] };

/** Packs ribbon items into standalone large columns and vertical stacks of up to 3 small items. */
export function packRibbonColumns<T extends { readonly size: RibbonButtonSize }>(items: readonly T[]): readonly RibbonColumn<T>[] {
	const columns: RibbonColumn<T>[] = [];
	let stack: T[] = [];
	const flushStack = () => {
		if (stack.length) {
			columns.push({ kind: 'stack', items: stack });
			stack = [];
		}
	};
	for (const item of items) {
		if (item.size === 'large') {
			flushStack();
			columns.push({ kind: 'large', item });
		} else {
			stack.push(item);
			if (stack.length >= RIBBON_SMALL_STACK_MAX) {
				flushStack();
			}
		}
	}
	flushStack();
	return columns;
}

export interface IRibbonActionItem {
	readonly kind: 'action';
	readonly action: MenuItemAction;
	readonly size: RibbonButtonSize;
	readonly label: string;
	readonly renderCustom?: (container: HTMLElement, instantiationService: IInstantiationService, action: MenuItemAction) => IDisposable;
}

export interface IRibbonSubmenuItem {
	readonly kind: 'submenu';
	readonly action: SubmenuItemAction;
	readonly size: RibbonButtonSize;
	readonly label: string;
	readonly isSplit: boolean;
	readonly primaryAction: MenuItemAction | undefined;
}

export type RibbonItem = IRibbonActionItem | IRibbonSubmenuItem;

export interface IRibbonGroupModel {
	readonly raw: string;
	readonly key: string;
	readonly label: string;
	readonly order: number;
	readonly collapsePriority: number;
	readonly columns: readonly RibbonColumn<RibbonItem>[];
	readonly custom?: IRibbonCustomGroup;
}

export interface IRibbonGroupCollapseInput {
	readonly key: string;
	readonly order: number;
	readonly collapsePriority: number;
	readonly collapsible: boolean;
	readonly expandedWidth: number;
	readonly collapsedWidth: number;
}

/**
 * Selects the smallest-priority collapsible groups to collapse into dropdown buttons
 * so the ribbon fits within `availableWidth` without a horizontal scrollbar.
 */
export function computeCollapsedRibbonGroups(
	groups: readonly IRibbonGroupCollapseInput[],
	availableWidth: number,
	chromeWidth = 0,
): ReadonlySet<string> {
	const collapsed = new Set<string>();
	if (availableWidth <= 0) {
		return collapsed;
	}

	let totalWidth = chromeWidth;
	for (const group of groups) {
		totalWidth += group.expandedWidth;
	}
	if (totalWidth <= availableWidth) {
		return collapsed;
	}

	const candidates = groups
		.filter(group => group.collapsible && group.expandedWidth > group.collapsedWidth)
		.sort((a, b) => a.collapsePriority - b.collapsePriority || b.order - a.order);

	for (const candidate of candidates) {
		if (totalWidth <= availableWidth) {
			break;
		}
		collapsed.add(candidate.key);
		totalWidth -= candidate.expandedWidth - candidate.collapsedWidth;
	}

	return collapsed;
}

function resolvePrimaryAction(action: SubmenuItemAction, primaryCommandId: string | undefined): MenuItemAction | undefined {
	const items = action.actions.filter((candidate): candidate is MenuItemAction => candidate instanceof MenuItemAction);
	if (primaryCommandId) {
		const explicit = items.find(candidate => candidate.id === primaryCommandId);
		if (explicit) {
			return explicit;
		}
	}
	return items.find(candidate => candidate.enabled) ?? items[0];
}

/** Builds sorted ribbon group models from menu action groups and custom groups. */
export function buildRibbonGroups(
	menuGroups: readonly [string, readonly (MenuItemAction | SubmenuItemAction)[]][],
	tabCustomGroups: readonly IRibbonCustomGroup[],
	options?: {
		readonly menuId?: MenuId;
		readonly hintLookup?: (id: string, menuId?: MenuId) => IRibbonItemHint | undefined;
		readonly labelLookup?: (key: string) => string | undefined;
		readonly priorityLookup?: (key: string) => number | undefined;
	}
): readonly IRibbonGroupModel[] {
	const menuId = options?.menuId;
	const hintLookup = options?.hintLookup ?? getRibbonItemHint;
	const labelLookup = options?.labelLookup ?? getRibbonGroupLabel;
	const priorityLookup = options?.priorityLookup ?? getRibbonGroupPriority;
	const groups: IRibbonGroupModel[] = [];

	for (const [rawGroup, actions] of menuGroups) {
		if (!actions.length) {
			continue;
		}
		const parsed = parseRibbonGroup(rawGroup, labelLookup);
		const defaultSize: RibbonButtonSize = actions.length <= 2 ? 'large' : 'small';
		const items: RibbonItem[] = actions.map(action => {
			if (action instanceof SubmenuItemAction) {
				const hint = hintLookup(action.item.submenu.id, menuId);
				const isSplit = !!action.item.isSplitButton;
				return {
					kind: 'submenu',
					action,
					size: hint?.size ?? defaultSize,
					label: hint?.label ?? action.label,
					isSplit,
					primaryAction: isSplit ? resolvePrimaryAction(action, hint?.primaryCommandId) : undefined,
				};
			}
			const hint = hintLookup(action.id, menuId);
			return {
				kind: 'action',
				action,
				size: hint?.size ?? defaultSize,
				label: hint?.label ?? action.label,
				renderCustom: hint?.renderCustom,
			};
		});
		groups.push({
			raw: parsed.raw,
			key: parsed.key,
			label: parsed.label,
			order: parsed.order,
			collapsePriority: priorityLookup(parsed.key) ?? -parsed.order,
			columns: packRibbonColumns(items),
		});
	}

	for (const custom of tabCustomGroups) {
		const parsed = parseRibbonGroup(custom.group, labelLookup);
		groups.push({
			raw: parsed.raw,
			key: parsed.key,
			label: custom.label,
			order: parsed.order,
			collapsePriority: priorityLookup(parsed.key) ?? -parsed.order,
			columns: [],
			custom,
		});
	}

	groups.sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
	return groups;
}
