/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { MenuId, MenuItemAction, SubmenuItemAction } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpression, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';

/** Context key active while a Floor Plan or CAD drawing editor is focused. */
export const SAENGINE_DRAFT_CONTEXT = 'saengineDraftActive';

export const DraftActiveContext = new RawContextKey<boolean>(
	SAENGINE_DRAFT_CONTEXT,
	false,
	localize('saengine.draftActive', "Whether a SAEngine Floor Plan or CAD drawing editor is active")
);

export type RibbonTabId =
	| 'home'
	| 'define'
	| 'model'
	| 'draft'
	| 'annotate'
	| 'blocksParametric'
	| 'loads'
	| 'analyze'
	| 'design'
	| 'mep'
	| 'documents'
	| 'output'
	| 'studies'
	| 'collaborate'
	| 'manage';

/**
 * MenuId per ribbon tab. Other contributions add buttons via `registerAction2` or
 * `MenuRegistry.appendMenuItem` using `group: '<order>_<GroupName>'`, e.g. `'3_Electrical'`.
 */
export const RibbonMenus = {
	Home: MenuId.for('SaengineRibbon.Home'),
	Define: MenuId.for('SaengineRibbon.Define'),
	Model: MenuId.for('SaengineRibbon.Model'),
	Draft: MenuId.for('SaengineRibbon.Draft'),
	Annotate: MenuId.for('SaengineRibbon.Annotate'),
	BlocksParametric: MenuId.for('SaengineRibbon.BlocksParametric'),
	Loads: MenuId.for('SaengineRibbon.Loads'),
	Analyze: MenuId.for('SaengineRibbon.Analyze'),
	Design: MenuId.for('SaengineRibbon.Design'),
	MEP: MenuId.for('SaengineRibbon.MEP'),
	Documents: MenuId.for('SaengineRibbon.Documents'),
	Output: MenuId.for('SaengineRibbon.Output'),
	Studies: MenuId.for('SaengineRibbon.Studies'),
	Collaborate: MenuId.for('SaengineRibbon.Collaborate'),
	Manage: MenuId.for('SaengineRibbon.Manage'),
} as const;

export interface IRibbonTabDescriptor {
	readonly id: RibbonTabId;
	readonly label: string;
	readonly menuId: MenuId;
	readonly contextual?: boolean;
	readonly contextualTag?: string;
	readonly when?: ContextKeyExpression;
}

export const RIBBON_TABS: readonly IRibbonTabDescriptor[] = [
	{ id: 'home', label: localize('ribbon.tab.home', "Home"), menuId: RibbonMenus.Home },
	{ id: 'define', label: localize('ribbon.tab.define', "Define"), menuId: RibbonMenus.Define },
	{ id: 'model', label: localize('ribbon.tab.model', "Model"), menuId: RibbonMenus.Model },
	{
		id: 'draft',
		label: localize('ribbon.tab.draft', "Draft"),
		menuId: RibbonMenus.Draft,
		contextual: true,
		contextualTag: localize('ribbon.tab.draftTag', "CAD"),
		when: DraftActiveContext,
	},
	{
		id: 'annotate',
		label: localize('ribbon.tab.annotate', "Annotate"),
		menuId: RibbonMenus.Annotate,
		contextual: true,
		when: DraftActiveContext,
	},
	{
		id: 'blocksParametric',
		label: localize('ribbon.tab.blocksParametric', "Blocks & Parametric"),
		menuId: RibbonMenus.BlocksParametric,
		contextual: true,
		when: DraftActiveContext,
	},
	{ id: 'loads', label: localize('ribbon.tab.loads', "Loads"), menuId: RibbonMenus.Loads },
	{ id: 'analyze', label: localize('ribbon.tab.analyze', "Analyze"), menuId: RibbonMenus.Analyze },
	{ id: 'design', label: localize('ribbon.tab.design', "Design"), menuId: RibbonMenus.Design },
	{ id: 'mep', label: localize('ribbon.tab.mep', "MEP"), menuId: RibbonMenus.MEP },
	{ id: 'documents', label: localize('ribbon.tab.documents', "Documents"), menuId: RibbonMenus.Documents },
	{ id: 'output', label: localize('ribbon.tab.output', "Output"), menuId: RibbonMenus.Output },
	{ id: 'studies', label: localize('ribbon.tab.studies', "Studies"), menuId: RibbonMenus.Studies },
	{ id: 'collaborate', label: localize('ribbon.tab.collaborate', "Collaborate"), menuId: RibbonMenus.Collaborate },
	{ id: 'manage', label: localize('ribbon.tab.manage', "Manage"), menuId: RibbonMenus.Manage },
];

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
