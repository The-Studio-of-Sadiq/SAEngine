/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/ribbon.css';
import { $, addDisposableListener, append, clearNode, EventType, isHTMLElement } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { IAction } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { Disposable, DisposableStore, IDisposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, IMenu, IMenuService, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IContextKey, IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IBannerService } from '../../../services/banner/browser/bannerService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import {
	buildRibbonGroups,
	DraftActiveContext,
	getRibbonCustomGroups,
	getRibbonGroupLabel,
	getRibbonItemHint,
	IRibbonTabDescriptor,
	onDidChangeRibbonRegistry,
	RIBBON_TABS,
	RibbonItem,
	RibbonTabId,
} from './ribbonRegistry.js';

const RIBBON_TABS_HEIGHT = 26;
const RIBBON_PANEL_HEIGHT = 92;
const RIBBON_EXPANDED_HEIGHT = RIBBON_TABS_HEIGHT + RIBBON_PANEL_HEIGHT;

const STORAGE_COLLAPSED_KEY = 'saengine.ribbon.collapsed';
const STORAGE_ACTIVE_TAB_KEY = 'saengine.ribbon.activeTab';

const TOGGLE_COLLAPSE_COMMAND_ID = 'saengine.ribbon.toggleCollapse';
const FOCUS_RIBBON_COMMAND_ID = 'saengine.ribbon.focus';

/** Editor pane IDs that activate the contextual Draft tab (strings: no cross-contrib imports). */
const DRAFT_EDITOR_IDS: ReadonlySet<string> = new Set([
	'workbench.editor.saengine.floorPlan',
	'workbench.editor.saengine.cad',
]);

let ribbonInstance: SaengineRibbonContribution | undefined;

export class SaengineRibbonContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.ribbon';

	private readonly root = $('.sa-ribbon');
	private readonly tabsBar = append(this.root, $('.sa-ribbon-tabs-bar'));
	private readonly tablist = append(this.tabsBar, $('.sa-ribbon-tablist'));
	private readonly tabsActions = append(this.tabsBar, $('.sa-ribbon-tabs-actions'));
	private readonly collapseBtn = append(this.tabsActions, $<HTMLButtonElement>('button.sa-ribbon-collapse-btn'));
	private readonly panelsEl = append(this.root, $('.sa-ribbon-panels'));

	private readonly strip = this._register(new MutableDisposable<IDisposable>());
	private readonly tabsDisposables = this._register(new DisposableStore());
	private readonly collapseHover = this._register(new MutableDisposable<IDisposable>());
	private readonly activeMenu = this._register(new MutableDisposable<IMenu>());
	private readonly menuListener = this._register(new MutableDisposable<IDisposable>());
	private readonly panelDisposables = this._register(new DisposableStore());
	private readonly panelScheduler = this._register(new RunOnceScheduler(() => this.renderActivePanel(), 40));

	private readonly draftContext: IContextKey<boolean>;
	private readonly tabContextKeys: ReadonlySet<string>;

	private tabButtons: HTMLButtonElement[] = [];
	private activeTabId: RibbonTabId;
	private collapsed: boolean;
	private toolbarFocusIndex = 0;

	constructor(
		@IBannerService private readonly bannerService: IBannerService,
		@IMenuService private readonly menuService: IMenuService,
		@IContextKeyService private readonly contextKeyService: IContextKeyService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IHoverService private readonly hoverService: IHoverService,
		@IKeybindingService private readonly keybindingService: IKeybindingService,
		@IStorageService private readonly storageService: IStorageService,
		@IEditorService private readonly editorService: IEditorService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super();
		ribbonInstance = this;
		this._register({
			dispose: () => {
				if (ribbonInstance === this) {
					ribbonInstance = undefined;
				}
			},
		});

		this.root.setAttribute('role', 'navigation');
		this.root.setAttribute('aria-label', localize('ribbon.aria', "Engineering ribbon"));

		this.tablist.setAttribute('role', 'tablist');
		this.tablist.setAttribute('aria-label', localize('ribbon.tabsAria', "Ribbon tabs"));

		this.collapseBtn.type = 'button';

		const keys = new Set<string>();
		for (const tab of RIBBON_TABS) {
			if (tab.when) {
				for (const key of tab.when.keys()) {
					keys.add(key);
				}
			}
		}
		this.tabContextKeys = keys;
		this.draftContext = DraftActiveContext.bindTo(this.contextKeyService);

		this.collapsed = this.storageService.getBoolean(STORAGE_COLLAPSED_KEY, StorageScope.PROFILE, false);
		const savedTab = this.storageService.get(STORAGE_ACTIVE_TAB_KEY, StorageScope.WORKSPACE, 'home') as RibbonTabId;
		this.activeTabId = RIBBON_TABS.some(t => t.id === savedTab) ? savedTab : 'home';

		this._register(addDisposableListener(this.tablist, EventType.KEY_DOWN, e => this.onTablistKeyDown(new StandardKeyboardEvent(e))));
		this._register(addDisposableListener(this.collapseBtn, EventType.CLICK, () => this.toggleCollapse()));
		this._register(this.editorService.onDidActiveEditorChange(() => this.updateDraftContext()));
		this._register(this.contextKeyService.onDidChangeContext(e => {
			if (e.affectsSome(this.tabContextKeys)) {
				this.renderTabs();
			}
		}));
		this._register(this.projectService.onDidChangeProject(() => this.panelScheduler.schedule()));
		this._register(onDidChangeRibbonRegistry(() => this.panelScheduler.schedule()));

		this.updateDraftContext();
		this.applyCollapseState();
		this.renderTabs();
		this.bindActiveTabMenu();
		this.mountStrip();
	}

	private updateDraftContext(): void {
		const activeId = this.editorService.activeEditorPane?.getId();
		this.draftContext.set(!!activeId && DRAFT_EDITOR_IDS.has(activeId));
	}

	private visibleTabs(): readonly IRibbonTabDescriptor[] {
		return RIBBON_TABS.filter(tab => !tab.when || this.contextKeyService.contextMatchesRules(tab.when));
	}

	private mountStrip(): void {
		const height = this.collapsed ? RIBBON_TABS_HEIGHT : RIBBON_EXPANDED_HEIGHT;
		this.strip.value = this.bannerService.showStrip(this.root, height);
	}

	toggleCollapse(): void {
		this.collapsed = !this.collapsed;
		this.storageService.store(STORAGE_COLLAPSED_KEY, this.collapsed, StorageScope.PROFILE, StorageTarget.USER);
		this.applyCollapseState();
		this.mountStrip();
	}

	focusTabs(): void {
		const selected = this.tabButtons.find(b => b.getAttribute('aria-selected') === 'true') ?? this.tabButtons[0];
		selected?.focus();
	}

	private applyCollapseState(): void {
		this.root.classList.toggle('sa-ribbon-collapsed', this.collapsed);
		clearNode(this.collapseBtn);
		const icon = this.collapsed ? Codicon.chevronDown : Codicon.chevronUp;
		append(this.collapseBtn, $(`span${ThemeIcon.asCSSSelector(icon)}`)).setAttribute('aria-hidden', 'true');
		const label = this.collapsed
			? localize('ribbon.expand', "Expand the Ribbon")
			: localize('ribbon.collapse', "Collapse the Ribbon");
		const key = this.keybindingService.lookupKeybinding(TOGGLE_COLLAPSE_COMMAND_ID)?.getLabel();
		const tip = key ? `${label} (${key})` : label;
		this.collapseBtn.setAttribute('aria-label', label);
		this.collapseBtn.setAttribute('aria-expanded', String(!this.collapsed));
		this.collapseHover.value = this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), this.collapseBtn, tip);
	}

	private selectTab(tabId: RibbonTabId, options?: { readonly expand?: boolean; readonly focus?: boolean }): void {
		const changed = this.activeTabId !== tabId;
		this.activeTabId = tabId;
		this.storageService.store(STORAGE_ACTIVE_TAB_KEY, tabId, StorageScope.WORKSPACE, StorageTarget.MACHINE);
		if (options?.expand && this.collapsed) {
			this.collapsed = false;
			this.storageService.store(STORAGE_COLLAPSED_KEY, false, StorageScope.PROFILE, StorageTarget.USER);
			this.applyCollapseState();
			this.mountStrip();
		}
		this.renderTabs();
		if (changed) {
			this.bindActiveTabMenu();
		}
		if (options?.focus) {
			const btn = this.tabButtons.find(b => b.dataset.tabId === tabId);
			btn?.focus();
			btn?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
		}
	}

	private renderTabs(): void {
		const tabs = this.visibleTabs();
		if (!tabs.some(t => t.id === this.activeTabId)) {
			this.activeTabId = tabs[0]?.id ?? 'home';
			this.bindActiveTabMenu();
		}
		const activeElement = this.tablist.ownerDocument.activeElement;
		const hadTabFocus = this.tablist.contains(activeElement);

		this.tabsDisposables.clear();
		clearNode(this.tablist);
		this.tabButtons = [];

		for (const tab of tabs) {
			const selected = tab.id === this.activeTabId;
			const button = append(this.tablist, $<HTMLButtonElement>('button.sa-ribbon-tab'));
			button.type = 'button';
			button.id = `sa-ribbon-tab-${tab.id}`;
			button.dataset.tabId = tab.id;
			button.setAttribute('role', 'tab');
			button.setAttribute('aria-selected', String(selected));
			button.tabIndex = selected ? 0 : -1;
			if (tab.contextual) {
				button.classList.add('sa-ribbon-tab-contextual');
			}
			append(button, $('span', undefined, tab.label));
			if (tab.contextual && tab.contextualTag) {
				append(button, $('span.sa-ribbon-ctx-tag', undefined, tab.contextualTag));
			}

			this.tabsDisposables.add(addDisposableListener(button, EventType.CLICK, () => {
				this.selectTab(tab.id, { expand: true });
				button.scrollIntoView({ block: 'nearest', inline: 'nearest' });
			}));
			this.tabsDisposables.add(addDisposableListener(button, EventType.DBLCLICK, () => {
				if (this.activeTabId === tab.id) {
					this.toggleCollapse();
				}
			}));
			this.tabButtons.push(button);
		}

		if (hadTabFocus) {
			this.focusTabs();
		}
	}

	private bindActiveTabMenu(): void {
		this.menuListener.clear();
		this.activeMenu.clear();
		const descriptor = RIBBON_TABS.find(t => t.id === this.activeTabId) ?? RIBBON_TABS[0];
		const menu = this.menuService.createMenu(descriptor.menuId, this.contextKeyService, { emitEventsForSubmenuChanges: true });
		this.activeMenu.value = menu;
		this.menuListener.value = menu.onDidChange(() => this.panelScheduler.schedule());
		this.renderActivePanel();
	}

	private renderActivePanel(): void {
		const menu = this.activeMenu.value;
		if (!menu) {
			return;
		}
		const descriptor = RIBBON_TABS.find(t => t.id === this.activeTabId) ?? RIBBON_TABS[0];
		const hadPanelFocus = this.panelsEl.contains(this.panelsEl.ownerDocument.activeElement);

		this.panelDisposables.clear();
		clearNode(this.panelsEl);

		const panel = append(this.panelsEl, $('div.sa-ribbon-panel'));
		panel.id = `sa-ribbon-panel-${descriptor.id}`;
		panel.setAttribute('role', 'tabpanel');
		panel.setAttribute('aria-labelledby', `sa-ribbon-tab-${descriptor.id}`);

		const toolbar = append(panel, $('div.sa-ribbon-toolbar'));
		toolbar.setAttribute('role', 'toolbar');
		toolbar.setAttribute('aria-label', descriptor.label);

		const actions = menu.getActions({ renderShortTitle: true });
		const groups = buildRibbonGroups(actions, getRibbonCustomGroups(descriptor.id), {
			menuId: descriptor.menuId,
			hintLookup: getRibbonItemHint,
			labelLookup: getRibbonGroupLabel,
		});

		groups.forEach((group, index) => {
			if (index > 0) {
				const sep = append(toolbar, $('div.sa-ribbon-group-sep'));
				sep.setAttribute('role', 'separator');
				sep.setAttribute('aria-orientation', 'vertical');
			}
			const groupEl = append(toolbar, $('div.sa-ribbon-group'));
			groupEl.setAttribute('role', 'group');
			const labelId = `sa-ribbon-grp-${descriptor.id}-${index}`;
			groupEl.setAttribute('aria-labelledby', labelId);

			const itemsEl = append(groupEl, $('div.sa-ribbon-items'));
			const labelEl = append(groupEl, $('div.sa-ribbon-group-label', undefined, group.label));
			labelEl.id = labelId;

			if (group.custom) {
				this.panelDisposables.add(group.custom.render(itemsEl, this.instantiationService));
				return;
			}

			for (const column of group.columns) {
				if (column.kind === 'large') {
					this.renderItem(itemsEl, column.item);
				} else {
					const stackEl = append(itemsEl, $('div.sa-ribbon-stack'));
					for (const item of column.items) {
						this.renderItem(stackEl, item);
					}
				}
			}
		});

		const buttons = this.collectToolbarButtons(toolbar);
		this.toolbarFocusIndex = Math.min(this.toolbarFocusIndex, Math.max(0, buttons.length - 1));
		buttons.forEach((button, idx) => {
			button.tabIndex = idx === this.toolbarFocusIndex ? 0 : -1;
		});

		this.panelDisposables.add(addDisposableListener(toolbar, EventType.FOCUS_IN, e => {
			const target = e.target;
			if (isHTMLElement(target) && target.tagName === 'BUTTON') {
				const liveButtons = this.collectToolbarButtons(toolbar);
				const idx = liveButtons.indexOf(target);
				if (idx >= 0) {
					this.toolbarFocusIndex = idx;
					liveButtons.forEach((b, i) => b.tabIndex = i === idx ? 0 : -1);
				}
			}
		}));
		this.panelDisposables.add(addDisposableListener(toolbar, EventType.KEY_DOWN, e => this.onToolbarKeyDown(toolbar, new StandardKeyboardEvent(e))));

		if (hadPanelFocus && buttons.length) {
			buttons[this.toolbarFocusIndex]?.focus();
		}
	}

	private collectToolbarButtons(container: HTMLElement, out: HTMLElement[] = []): HTMLElement[] {
		let child = container.firstElementChild;
		while (child) {
			if (isHTMLElement(child)) {
				if (child.tagName === 'BUTTON') {
					out.push(child);
				} else {
					this.collectToolbarButtons(child, out);
				}
			}
			child = child.nextElementSibling;
		}
		return out;
	}

	private renderItem(container: HTMLElement, item: RibbonItem): void {
		if (item.kind === 'action') {
			if (item.renderCustom) {
				this.panelDisposables.add(item.renderCustom(container, this.instantiationService, item.action));
				return;
			}
			const action = item.action;
			const icon = ThemeIcon.isThemeIcon(action.item.icon) ? action.item.icon : Codicon.symbolMisc;
			const button = append(container, $<HTMLButtonElement>(`button.sa-ribbon-btn.sa-ribbon-btn-${item.size}`));
			button.type = 'button';
			append(button, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(icon)}`)).setAttribute('aria-hidden', 'true');
			append(button, $('span.sa-ribbon-btn-label', undefined, item.label));

			if (action.checked !== undefined) {
				button.setAttribute('aria-pressed', String(action.checked));
			}
			if (!action.enabled) {
				button.setAttribute('aria-disabled', 'true');
				button.classList.add('sa-ribbon-disabled');
			}

			const fullTitle = typeof action.item.title === 'string' ? action.item.title : action.item.title.value;
			const tip = this.buildTooltip(action.id, fullTitle, action.tooltip, action.enabled);
			button.setAttribute('aria-label', fullTitle);
			this.panelDisposables.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip));

			this.panelDisposables.add(addDisposableListener(button, EventType.CLICK, () => {
				if (button.getAttribute('aria-disabled') === 'true') {
					return;
				}
				void action.run();
			}));
			return;
		}

		const submenu = item.action;
		if (item.isSplit && item.primaryAction) {
			const primary = item.primaryAction;
			const split = append(container, $(`div.sa-ribbon-split.sa-ribbon-split-${item.size}`));
			const hasEnabledChild = submenu.actions.some(a => a.enabled);
			if (!primary.enabled && !hasEnabledChild) {
				split.classList.add('sa-ribbon-disabled');
			}

			const mainBtn = append(split, $<HTMLButtonElement>(`button.sa-ribbon-btn.sa-ribbon-btn-${item.size}.sa-ribbon-split-main`));
			mainBtn.type = 'button';
			const icon = ThemeIcon.isThemeIcon(submenu.item.icon)
				? submenu.item.icon
				: ThemeIcon.isThemeIcon(primary.item.icon) ? primary.item.icon : Codicon.symbolMisc;
			append(mainBtn, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(icon)}`)).setAttribute('aria-hidden', 'true');
			append(mainBtn, $('span.sa-ribbon-btn-label', undefined, item.label));
			if (!primary.enabled) {
				mainBtn.setAttribute('aria-disabled', 'true');
				mainBtn.classList.add('sa-ribbon-disabled');
			}
			const primaryTitle = typeof primary.item.title === 'string' ? primary.item.title : primary.item.title.value;
			const mainTip = this.buildTooltip(primary.id, primaryTitle, primary.tooltip, primary.enabled);
			mainBtn.setAttribute('aria-label', primaryTitle);
			this.panelDisposables.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), mainBtn, mainTip));
			this.panelDisposables.add(addDisposableListener(mainBtn, EventType.CLICK, () => {
				if (mainBtn.getAttribute('aria-disabled') === 'true') {
					return;
				}
				void primary.run();
			}));

			const dropBtn = append(split, $<HTMLButtonElement>('button.sa-ribbon-split-drop'));
			dropBtn.type = 'button';
			dropBtn.setAttribute('aria-haspopup', 'menu');
			dropBtn.setAttribute('aria-expanded', 'false');
			const dropLabel = localize('ribbon.moreOptions', "{0} options", item.label);
			dropBtn.setAttribute('aria-label', dropLabel);
			append(dropBtn, $(`span${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');
			if (!hasEnabledChild) {
				dropBtn.setAttribute('aria-disabled', 'true');
			}
			this.panelDisposables.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), dropBtn, dropLabel));
			this.panelDisposables.add(addDisposableListener(dropBtn, EventType.CLICK, () => {
				if (dropBtn.getAttribute('aria-disabled') === 'true') {
					return;
				}
				this.openSubmenu(split, dropBtn, submenu.actions);
			}));
			return;
		}

		// Pure dropdown button
		const button = append(container, $<HTMLButtonElement>(`button.sa-ribbon-btn.sa-ribbon-btn-${item.size}.sa-ribbon-dropdown`));
		button.type = 'button';
		button.setAttribute('aria-haspopup', 'menu');
		button.setAttribute('aria-expanded', 'false');
		const icon = ThemeIcon.isThemeIcon(submenu.item.icon) ? submenu.item.icon : Codicon.symbolMisc;
		append(button, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(icon)}`)).setAttribute('aria-hidden', 'true');
		append(button, $('span.sa-ribbon-btn-label', undefined, item.label));
		append(button, $(`span.sa-ribbon-caret${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');

		const enabled = submenu.actions.some(a => a.enabled);
		if (!enabled) {
			button.setAttribute('aria-disabled', 'true');
			button.classList.add('sa-ribbon-disabled');
		}
		const submenuTitle = typeof submenu.item.title === 'string' ? submenu.item.title : submenu.item.title.value;
		const tip = this.buildTooltip(undefined, submenuTitle, undefined, enabled);
		button.setAttribute('aria-label', submenuTitle);
		this.panelDisposables.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip));
		this.panelDisposables.add(addDisposableListener(button, EventType.CLICK, () => {
			if (button.getAttribute('aria-disabled') === 'true') {
				return;
			}
			this.openSubmenu(button, button, submenu.actions);
		}));
	}

	private openSubmenu(anchor: HTMLElement, trigger: HTMLElement, actions: readonly IAction[]): void {
		trigger.setAttribute('aria-expanded', 'true');
		this.contextMenuService.showContextMenu({
			getAnchor: () => anchor,
			getActions: () => actions,
			getKeyBinding: action => this.keybindingService.lookupKeybinding(action.id),
			onHide: () => trigger.setAttribute('aria-expanded', 'false'),
		});
	}

	private buildTooltip(commandId: string | undefined, fullTitle: string, detail: string | undefined, enabled: boolean): string {
		const key = commandId ? this.keybindingService.lookupKeybinding(commandId)?.getLabel() : undefined;
		const lines = [key ? `${fullTitle} (${key})` : fullTitle];
		let extra = detail && detail !== fullTitle ? detail : undefined;
		if (!extra && commandId) {
			const desc = MenuRegistry.getCommand(commandId)?.metadata?.description;
			const descText = typeof desc === 'string' ? desc : desc?.value;
			if (descText && descText !== fullTitle) {
				extra = descText;
			}
		}
		if (extra) {
			lines.push(extra);
		}
		if (!enabled && !this.projectService.project) {
			lines.push(localize('ribbon.needsProject', "Open a SAEngine project to use this command."));
		}
		return lines.join('\n');
	}

	private onTablistKeyDown(event: StandardKeyboardEvent): void {
		const count = this.tabButtons.length;
		if (!count) {
			return;
		}
		const currentIndex = this.tabButtons.findIndex(b => b === this.tablist.ownerDocument.activeElement);
		if (currentIndex < 0) {
			return;
		}
		const rtl = this.tablist.ownerDocument.defaultView?.getComputedStyle(this.tablist).direction === 'rtl';
		let nextIndex: number | undefined;
		if (event.equals(KeyCode.RightArrow)) {
			nextIndex = (currentIndex + (rtl ? -1 : 1) + count) % count;
		} else if (event.equals(KeyCode.LeftArrow)) {
			nextIndex = (currentIndex + (rtl ? 1 : -1) + count) % count;
		} else if (event.equals(KeyCode.Home)) {
			nextIndex = 0;
		} else if (event.equals(KeyCode.End)) {
			nextIndex = count - 1;
		} else if (event.equals(KeyCode.DownArrow)) {
			event.preventDefault();
			event.stopPropagation();
			if (this.collapsed) {
				this.toggleCollapse();
			}
			const first = this.collectToolbarButtons(this.panelsEl)[0];
			first?.focus();
			return;
		}
		if (nextIndex !== undefined) {
			event.preventDefault();
			event.stopPropagation();
			const targetTabId = this.tabButtons[nextIndex].dataset.tabId as RibbonTabId | undefined;
			if (targetTabId) {
				this.selectTab(targetTabId, { focus: true });
			}
		}
	}

	private onToolbarKeyDown(toolbar: HTMLElement, event: StandardKeyboardEvent): void {
		if (event.browserEvent.defaultPrevented) {
			return;
		}
		const buttons = this.collectToolbarButtons(toolbar);
		const count = buttons.length;
		if (!count) {
			return;
		}
		const active = toolbar.ownerDocument.activeElement;
		const activeIdx = isHTMLElement(active) && active.tagName === 'BUTTON'
			? buttons.indexOf(active)
			: -1;
		const current = activeIdx >= 0 ? activeIdx : Math.min(this.toolbarFocusIndex, count - 1);
		const rtl = toolbar.ownerDocument.defaultView?.getComputedStyle(toolbar).direction === 'rtl';
		let nextIndex: number | undefined;
		if (event.equals(KeyCode.RightArrow)) {
			nextIndex = (current + (rtl ? -1 : 1) + count) % count;
		} else if (event.equals(KeyCode.LeftArrow)) {
			nextIndex = (current + (rtl ? 1 : -1) + count) % count;
		} else if (event.equals(KeyCode.Home)) {
			nextIndex = 0;
		} else if (event.equals(KeyCode.End)) {
			nextIndex = count - 1;
		} else if (event.equals(KeyCode.UpArrow)) {
			event.preventDefault();
			event.stopPropagation();
			this.focusTabs();
			return;
		}
		if (nextIndex !== undefined) {
			event.preventDefault();
			event.stopPropagation();
			buttons[nextIndex]?.focus();
		}
	}
}

registerWorkbenchContribution2(SaengineRibbonContribution.ID, SaengineRibbonContribution, WorkbenchPhase.AfterRestored);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: TOGGLE_COLLAPSE_COMMAND_ID,
			title: localize2('ribbon.toggleCollapse', "Toggle Ribbon Collapse"),
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
			keybinding: {
				primary: KeyMod.CtrlCmd | KeyCode.F1,
				weight: KeybindingWeight.WorkbenchContrib,
			},
		});
	}

	override run(_accessor: ServicesAccessor): void {
		ribbonInstance?.toggleCollapse();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: FOCUS_RIBBON_COMMAND_ID,
			title: localize2('ribbon.focus', "Focus Engineering Ribbon"),
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
		});
	}

	override run(_accessor: ServicesAccessor): void {
		ribbonInstance?.focusTabs();
	}
});
