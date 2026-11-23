/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/ribbon.css';
import { $, addDisposableListener, append, clearNode, DisposableResizeObserver, EventType, getWindow, isHTMLElement } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { Disposable, DisposableStore, IDisposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { basename } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, IMenu, IMenuService, isIMenuItem, isISubmenuItem, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextKey, IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { IBannerService } from '../../../services/banner/browser/bannerService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IPartSectionPane, isPartSectionPane } from '../../../services/saengineProject/common/partSections.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { getEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';
import { frameOfContainer } from '../../saengineProject/browser/modelLayoutModel.js';
import {
	collectControlCollapsedActions,
	dedupeEditorFrameActions,
	hasVisibleControls,
	IEditorRibbonFrame,
	IRibbonControlServices,
	ISaengineRibbonToolbarService,
	renderRibbonActionButton,
	renderRibbonControlStack,
	renderRibbonHelpButton,
	renderRibbonPill,
} from './ribbonControls.js';
import {
	buildRibbonGroups,
	computeCollapsedRibbonGroups,
	DataPanelPartContext,
	DraftActiveContext,
	getRibbonCustomGroups,
	getRibbonGroupLabel,
	getRibbonGroupPriority,
	getRibbonGroupWhen,
	getRibbonItemHint,
	getVisibleRibbonTabs,
	IRibbonCustomGroup,
	IRibbonGroupModel,
	IRibbonTabDescriptor,
	onDidChangeRibbonRegistry,
	packRibbonColumns,
	resolveActiveTabForEditor,
	resolveDataPanelPart,
	resolveDataPanelSubView,
	resolveEditorToolbarTargetTab,
	RIBBON_TABS,
	RibbonButtonSize,
	RibbonItem,
	RibbonTabId,
	SAENGINE_EDITOR_IDS,
	SubViewContext,
} from './ribbonRegistry.js';

const RIBBON_TABS_HEIGHT = 26;
const RIBBON_PANEL_HEIGHT = 92;
const RIBBON_EXPANDED_HEIGHT = RIBBON_TABS_HEIGHT + RIBBON_PANEL_HEIGHT;

const STORAGE_COLLAPSED_KEY = 'saengine.ribbon.collapsed';
const STORAGE_TABS_BY_EDITOR_KEY = 'saengine.ribbon.activeTabsByEditor';

const TOGGLE_COLLAPSE_COMMAND_ID = 'saengine.ribbon.toggleCollapse';
const FOCUS_RIBBON_COMMAND_ID = 'saengine.ribbon.focus';

/** Editor pane IDs that activate the contextual CAD Draft tabs. */
const DRAFT_EDITOR_IDS: ReadonlySet<string> = new Set([
	SAENGINE_EDITOR_IDS.floorPlan,
	SAENGINE_EDITOR_IDS.cad,
]);

let ribbonInstance: SaengineRibbonContribution | undefined;

interface IRenderedRibbonGroup {
	readonly model: IRibbonGroupModel;
	readonly tabId: RibbonTabId;
	readonly index: number;
	readonly groupEl: HTMLElement;
	readonly disposables: DisposableStore;
	readonly collapsible: boolean;
	expandedWidth: number;
	collapsedWidth: number | undefined;
	collapsed: boolean;
}

interface IActivePanelLayout {
	readonly toolbar: HTMLElement;
	readonly sepEls: readonly HTMLElement[];
	readonly groups: readonly IRenderedRibbonGroup[];
}

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
	private readonly resizeScheduler = this._register(new RunOnceScheduler(() => this.relayoutGroups(), 16));

	private readonly draftContext: IContextKey<boolean>;
	private readonly dataPanelPartContext: IContextKey<string>;
	private readonly subViewContext: IContextKey<string>;
	private readonly tabContextKeys: ReadonlySet<string>;
	private readonly activeSubViewPane = this._register(new MutableDisposable<IDisposable>());
	private readonly lastTabByEditor = new Map<string, RibbonTabId>();

	private tabButtons: HTMLButtonElement[] = [];
	private activeTabId: RibbonTabId = 'home';
	private lastEditorKey: string | undefined;
	private lastSubView = '';
	private activeFrame: IEditorRibbonFrame | undefined;
	private activeSectionPane: IPartSectionPane | undefined;
	private menuBound = false;
	private syncingEditor = false;
	private collapsed: boolean;
	private toolbarFocusIndex = 0;
	private activePanelLayout: IActivePanelLayout | undefined;

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
		@ISaengineRibbonToolbarService private readonly ribbonToolbarService: ISaengineRibbonToolbarService,
		@ICommandService private readonly commandService: ICommandService,
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

		const keys = new Set<string>([ActiveEditorContext.key, DataPanelPartContext.key, SubViewContext.key]);
		for (const tab of RIBBON_TABS) {
			if (tab.when) {
				for (const key of tab.when.keys()) {
					keys.add(key);
				}
			}
		}
		this.tabContextKeys = keys;
		this.draftContext = DraftActiveContext.bindTo(this.contextKeyService);
		this.dataPanelPartContext = DataPanelPartContext.bindTo(this.contextKeyService);
		this.subViewContext = SubViewContext.bindTo(this.contextKeyService);

		this.collapsed = this.storageService.getBoolean(STORAGE_COLLAPSED_KEY, StorageScope.PROFILE, false);
		this.loadTabMemory();

		this._register(addDisposableListener(this.tablist, EventType.KEY_DOWN, e => this.onTablistKeyDown(new StandardKeyboardEvent(e))));
		this._register(addDisposableListener(this.collapseBtn, EventType.CLICK, () => this.toggleCollapse()));
		this._register(this.editorService.onDidActiveEditorChange(() => this.syncActiveEditor(true)));
		this._register(this.contextKeyService.onDidChangeContext(e => {
			if (e.affectsSome(this.tabContextKeys)) {
				this.syncActiveEditor(true);
			}
		}));
		this._register(this.projectService.onDidChangeProject(() => this.panelScheduler.schedule()));
		this._register(onDidChangeRibbonRegistry(() => this.panelScheduler.schedule()));
		this._register(this.ribbonToolbarService.onDidChangeFrames(() => this.syncActiveFrame()));
		this._register(this.ribbonToolbarService.onDidChangeToolbar(frame => {
			if (frame === this.activeFrame) {
				this.panelScheduler.schedule();
			}
		}));
		const resizeObserver = this._register(new DisposableResizeObserver('saengine.ribbon', () => this.resizeScheduler.schedule(), getWindow(this.panelsEl)));
		resizeObserver.observe(this.panelsEl);

		this.syncActiveEditor(true);
		this.applyCollapseState();
		if (!this.menuBound) {
			this.bindActiveTabMenu();
		}
		this.mountStrip();
	}

	private loadTabMemory(): void {
		const raw = this.storageService.get(STORAGE_TABS_BY_EDITOR_KEY, StorageScope.WORKSPACE);
		if (!raw) {
			return;
		}
		try {
			const parsed: unknown = JSON.parse(raw);
			if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
				const validTabs = new Set<string>(RIBBON_TABS.map(t => t.id));
				for (const [editorKey, tabId] of Object.entries(parsed as { readonly [k: string]: unknown })) {
					if (typeof tabId === 'string' && validTabs.has(tabId)) {
						this.lastTabByEditor.set(editorKey, tabId as RibbonTabId);
					}
				}
			}
		} catch {
			// Ignore malformed persisted tab history.
		}
	}

	private saveTabMemory(): void {
		const serialized = JSON.stringify(Object.fromEntries(this.lastTabByEditor));
		this.storageService.store(STORAGE_TABS_BY_EDITOR_KEY, serialized, StorageScope.WORKSPACE, StorageTarget.MACHINE);
	}

	private activeDataPanelId(): string | undefined {
		const resource = this.editorService.activeEditor?.resource;
		if (resource?.scheme === 'saengine-panel') {
			return resource.path.replace(/^\/+/, '');
		}
		return undefined;
	}

	private syncActiveEditor(autoSwitch: boolean): void {
		if (this.syncingEditor) {
			return;
		}
		this.syncingEditor = true;
		try {
			const activeId = this.editorService.activeEditorPane?.getId() ?? '';
			const pane = this.editorService.activeEditorPane;
			const sectionPane = isPartSectionPane(pane) ? pane : undefined;
			if (sectionPane !== this.activeSectionPane) {
				this.activeSectionPane = sectionPane;
				this.activeSubViewPane.value = sectionPane?.onDidChangePartSection(() => this.syncActiveEditor(false));
			}
			const panelId = activeId === SAENGINE_EDITOR_IDS.dataPanel ? this.activeDataPanelId() : undefined;
			const panelPart = panelId ? resolveDataPanelPart(panelId, getEngineDataPanel(panelId)?.part) : '';

			const subView = this.activeSubView(activeId, sectionPane, panelId);
			const subViewChanged = subView !== this.lastSubView;
			this.lastSubView = subView;

			this.contextKeyService.bufferChangeEvents(() => {
				this.draftContext.set(DRAFT_EDITOR_IDS.has(activeId));
				this.dataPanelPartContext.set(panelPart);
				this.subViewContext.set(subView);
			});

			const contextEditorId = this.contextKeyService.getContextKeyValue<string>(ActiveEditorContext.key) ?? activeId;
			const editorKey = contextEditorId === SAENGINE_EDITOR_IDS.dataPanel && (subView || panelPart)
				? `${contextEditorId}:${subView || panelPart}`
				: contextEditorId;
			const editorChanged = editorKey !== this.lastEditorKey;
			this.lastEditorKey = editorKey;

			const tabs = getVisibleRibbonTabs(this.contextKeyService);
			const nextTab = (autoSwitch && editorChanged) || !tabs.some(t => t.id === this.activeTabId)
				? resolveActiveTabForEditor(editorKey, tabs, this.lastTabByEditor, subView)
				: this.activeTabId;
			const tabChanged = nextTab !== this.activeTabId;
			this.activeTabId = nextTab;

			const nextFrame = pane instanceof EditorPane ? frameOfContainer(this.ribbonToolbarService.frames, pane.getContainer()) : undefined;
			const frameChanged = nextFrame !== this.activeFrame;
			this.activeFrame = nextFrame;

			this.renderTabs(tabs);
			if (tabChanged) {
				this.bindActiveTabMenu();
			} else if (frameChanged || subViewChanged) {
				this.panelScheduler.schedule();
			}
		} finally {
			this.syncingEditor = false;
		}
	}

	private activeSubView(editorId: string, pane: IPartSectionPane | undefined, panelId?: string): string {
		if (pane?.ribbonSubView) {
			return pane.ribbonSubView;
		}
		switch (editorId) {
			case SAENGINE_EDITOR_IDS.dataPanel: return resolveDataPanelSubView(panelId);
			case SAENGINE_EDITOR_IDS.floorPlan: return 'plan.plan';
			case SAENGINE_EDITOR_IDS.grids: return 'plan.grids';
			case SAENGINE_EDITOR_IDS.membersTable: return 'plan.members';
			case SAENGINE_EDITOR_IDS.building: return `bim.${pane?.partSection ?? '3d'}`;
			case SAENGINE_EDITOR_IDS.settings: return `settings.${pane?.partSection ?? 'project'}`;
			case SAENGINE_EDITOR_IDS.codePacks: return 'settings.packages';
			case SAENGINE_EDITOR_IDS.femModel:
				return this.editorService.activeEditor?.resource && basename(this.editorService.activeEditor.resource) === 'pushover.osmodel' ? 'fem.pushover' : 'fem.model';
			case SAENGINE_EDITOR_IDS.femResults: return 'fem.charts';
			case SAENGINE_EDITOR_IDS.femDesignProposal:
			case SAENGINE_EDITOR_IDS.femStrutAndTie: return 'fem.design';
			case SAENGINE_EDITOR_IDS.femCfdWind: return 'fem.model';
			default: return '';
		}
	}

	private syncActiveFrame(): void {
		const pane = this.editorService.activeEditorPane;
		const nextFrame = pane instanceof EditorPane ? frameOfContainer(this.ribbonToolbarService.frames, pane.getContainer()) : undefined;
		if (nextFrame !== this.activeFrame) {
			this.activeFrame = nextFrame;
			this.panelScheduler.schedule();
		}
	}

	private visibleTabs(): readonly IRibbonTabDescriptor[] {
		return getVisibleRibbonTabs(this.contextKeyService);
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
		if (!this.collapsed) {
			this.resizeScheduler.schedule();
		}
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
		this.lastTabByEditor.set(this.lastEditorKey ?? '', tabId);
		this.saveTabMemory();
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

	private renderTabs(tabs: readonly IRibbonTabDescriptor[] = this.visibleTabs()): void {
		if (!tabs.some(t => t.id === this.activeTabId)) {
			this.activeTabId = resolveActiveTabForEditor(this.lastEditorKey ?? '', tabs, this.lastTabByEditor, this.lastSubView);
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
		this.menuBound = true;
		this.menuListener.clear();
		this.activeMenu.clear();
		const descriptor = RIBBON_TABS.find(t => t.id === this.activeTabId) ?? RIBBON_TABS[0];
		const menu = this.menuService.createMenu(descriptor.menuId, this.contextKeyService, { emitEventsForSubmenuChanges: true });
		this.activeMenu.value = menu;
		this.menuListener.value = menu.onDidChange(() => this.panelScheduler.schedule());
		this.renderActivePanel();
	}

	private collectMenuCommandIds(menuId: MenuId, out: Set<string>, visited = new Set<string>()): void {
		if (visited.has(menuId.id)) {
			return;
		}
		visited.add(menuId.id);
		for (const item of MenuRegistry.getMenuItems(menuId)) {
			if (item.group) {
				const groupWhen = getRibbonGroupWhen(menuId, item.group);
				if (groupWhen && !this.contextKeyService.contextMatchesRules(groupWhen)) {
					continue;
				}
			}
			if (item.when && !this.contextKeyService.contextMatchesRules(item.when)) {
				continue;
			}
			if (isIMenuItem(item)) {
				out.add(item.command.id);
			} else if (isISubmenuItem(item)) {
				this.collectMenuCommandIds(item.submenu, out, visited);
			}
		}
	}

	private buildEditorFrameGroups(
		frame: IEditorRibbonFrame,
		activeTabId: RibbonTabId,
		targetTabId: RibbonTabId,
		existingCommandIds: ReadonlySet<string>,
	): IRibbonCustomGroup[] {
		const services: IRibbonControlServices = {
			hoverService: this.hoverService,
			contextMenuService: this.contextMenuService,
			commandService: this.commandService,
		};
		const groups: IRibbonCustomGroup[] = [];

		if (activeTabId === targetTabId) {
			if (hasVisibleControls(frame.viewControls)) {
				groups.push({
					tabId: activeTabId,
					group: '0_1_EditorView',
					label: localize('ribbon.grp.view', "View"),
					icon: Codicon.eye,
					collapsible: true,
					collapsePriority: 120,
					getCollapsedActions: store => collectControlCollapsedActions(frame.viewControls, store),
					render: container => renderRibbonControlStack(container, frame.viewControls, services),
				});
			}

			if (hasVisibleControls(frame.toolControls)) {
				groups.push({
					tabId: activeTabId,
					group: '0_2_EditorTool',
					label: localize('ribbon.grp.tool', "Tool"),
					icon: Codicon.tools,
					collapsible: true,
					collapsePriority: 115,
					getCollapsedActions: store => collectControlCollapsedActions(frame.toolControls, store),
					render: container => renderRibbonControlStack(container, frame.toolControls, services),
				});
			}

			const deduped = dedupeEditorFrameActions(frame.primaryActions, frame.secondaryActions, existingCommandIds);
			const primaryButtons = deduped.primary.filter(a => !(a instanceof Separator));
			const secondaryItems = deduped.secondary.filter(a => !(a instanceof Separator));
			if (primaryButtons.length > 0 || secondaryItems.length > 0 || frame.pills.length > 0) {
				const firstIcon = this.iconOfAction(primaryButtons[0] ?? secondaryItems[0]) ?? Codicon.symbolMisc;
				groups.push({
					tabId: activeTabId,
					group: '0_3_EditorActions',
					label: frame.title,
					icon: firstIcon,
					collapsible: true,
					collapsePriority: 85,
					getCollapsedActions: store => {
						const out: IAction[] = [...primaryButtons];
						if (deduped.secondary.length) {
							if (out.length) {
								out.push(new Separator());
							}
							out.push(...deduped.secondary);
						}
						for (const pill of frame.pills) {
							if (pill.run) {
								const run = pill.run;
								out.push(store.add(new Action(pill.id, pill.text, pill.icon ? ThemeIcon.asClassName(pill.icon) : undefined, true, async () => run())));
							}
						}
						return out;
					},
					render: container => {
						const store = new DisposableStore();
						const useLargePrimary = primaryButtons.length <= 2 && secondaryItems.length === 0 && frame.pills.length === 0;
						const packed = packRibbonColumns(primaryButtons.map(action => ({
							action,
							size: (useLargePrimary ? 'large' : 'small') as RibbonButtonSize,
						})));
						for (const col of packed) {
							if (col.kind === 'large') {
								store.add(renderRibbonActionButton(container, col.item.action, 'large', services));
							} else {
								const stackEl = append(container, $('div.sa-ribbon-stack'));
								for (const entry of col.items) {
									store.add(renderRibbonActionButton(stackEl, entry.action, 'small', services));
								}
							}
						}
						if (secondaryItems.length > 0 || frame.pills.length > 0) {
							const extraStack = append(container, $('div.sa-ribbon-stack'));
							for (const pill of frame.pills) {
								store.add(renderRibbonPill(extraStack, pill, services));
							}
							if (secondaryItems.length <= 2 && primaryButtons.length <= 2 && frame.pills.length === 0) {
								for (const action of secondaryItems) {
									store.add(renderRibbonActionButton(extraStack, action, 'small', services));
								}
							} else if (secondaryItems.length > 0) {
								const moreBtn = append(extraStack, $<HTMLButtonElement>('button.sa-ribbon-btn.sa-ribbon-btn-small.sa-ribbon-dropdown'));
								moreBtn.type = 'button';
								moreBtn.setAttribute('aria-haspopup', 'menu');
								moreBtn.setAttribute('aria-expanded', 'false');
								const moreLabel = localize('ribbon.moreActions', "More");
								moreBtn.setAttribute('aria-label', moreLabel);
								append(moreBtn, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(Codicon.ellipsis)}`)).setAttribute('aria-hidden', 'true');
								append(moreBtn, $('span.sa-ribbon-btn-label', undefined, moreLabel));
								append(moreBtn, $(`span.sa-ribbon-caret${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');
								store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), moreBtn, localize('ribbon.moreActionsTip', "More actions for {0}", frame.title)));
								store.add(addDisposableListener(moreBtn, EventType.CLICK, () => {
									this.openSubmenu(moreBtn, moreBtn, deduped.secondary);
								}));
							}
						}
						return store;
					},
				});
			}

			if (frame.help) {
				const help = frame.help;
				groups.push({
					tabId: activeTabId,
					group: '999_EditorHelp',
					label: localize('ribbon.grp.help', "Help"),
					icon: Codicon.question,
					collapsible: true,
					collapsePriority: 5,
					getCollapsedActions: store => [
						store.add(new Action('saengine.ribbon.editorHelp', localize('ribbon.help.action', "Help: {0}", frame.title), ThemeIcon.asClassName(Codicon.question), true, async () => {
							if (help.chapter) {
								await this.commandService.executeCommand(help.openManualCommand, help.chapter);
							}
						})),
					],
					render: container => renderRibbonHelpButton(container, help, services),
				});
			}
		}

		for (const tabGroup of frame.tabGroups) {
			if (tabGroup.tabId !== activeTabId) {
				continue;
			}
			if ((tabGroup.isVisible && !tabGroup.isVisible()) || !hasVisibleControls(tabGroup.controls)) {
				continue;
			}
			groups.push({
				tabId: activeTabId,
				group: tabGroup.group,
				label: tabGroup.label,
				icon: tabGroup.icon ?? Codicon.settings,
				collapsible: true,
				collapsePriority: tabGroup.collapsePriority ?? 110,
				getCollapsedActions: store => collectControlCollapsedActions(tabGroup.controls, store),
				render: container => renderRibbonControlStack(container, tabGroup.controls, services),
			});
		}

		return groups;
	}

	private iconOfAction(action: IAction | undefined): ThemeIcon | undefined {
		if (!action?.class) {
			return undefined;
		}
		const match = /\bcodicon-([a-z0-9-]+)\b/i.exec(action.class);
		return match ? ThemeIcon.fromId(match[1]) : undefined;
	}

	private renderActivePanel(): void {
		const menu = this.activeMenu.value;
		if (!menu) {
			return;
		}
		const descriptor = RIBBON_TABS.find(t => t.id === this.activeTabId) ?? RIBBON_TABS[0];
		const hadPanelFocus = this.panelsEl.contains(this.panelsEl.ownerDocument.activeElement);

		this.activePanelLayout = undefined;
		this.panelDisposables.clear();
		clearNode(this.panelsEl);

		const panel = append(this.panelsEl, $('div.sa-ribbon-panel'));
		panel.id = `sa-ribbon-panel-${descriptor.id}`;
		panel.setAttribute('role', 'tabpanel');
		panel.setAttribute('aria-labelledby', `sa-ribbon-tab-${descriptor.id}`);

		const toolbar = append(panel, $('div.sa-ribbon-toolbar'));
		toolbar.setAttribute('role', 'toolbar');
		toolbar.setAttribute('aria-label', descriptor.label);

		const activeFrame = this.activeFrame;
		const activeFrameActionsById = new Map<string, IAction>();
		let frameCustomGroups: IRibbonCustomGroup[] = [];
		if (activeFrame) {
			for (const action of [...activeFrame.primaryActions, ...activeFrame.secondaryActions]) {
				if (!(action instanceof Separator) && !activeFrameActionsById.has(action.id)) {
					activeFrameActionsById.set(action.id, action);
				}
			}
			const visibleTabs = this.visibleTabs();
			const targetTabId = resolveEditorToolbarTargetTab(visibleTabs, this.lastEditorKey ?? '', this.lastSubView);
			const existingCommandIds = new Set<string>();
			for (const tab of visibleTabs) {
				this.collectMenuCommandIds(tab.menuId, existingCommandIds);
			}
			frameCustomGroups = this.buildEditorFrameGroups(activeFrame, descriptor.id, targetTabId, existingCommandIds);
		}

		const actions = menu.getActions({ renderShortTitle: true }).filter(([rawGroup]) => {
			const when = getRibbonGroupWhen(descriptor.menuId, rawGroup);
			return !when || this.contextKeyService.contextMatchesRules(when);
		});
		const customGroups = getRibbonCustomGroups(descriptor.id).filter(group => {
			const when = getRibbonGroupWhen(descriptor.menuId, group.group);
			return !when || this.contextKeyService.contextMatchesRules(when);
		});
		const groups = buildRibbonGroups(actions, [...customGroups, ...frameCustomGroups], {
			menuId: descriptor.menuId,
			hintLookup: getRibbonItemHint,
			labelLookup: getRibbonGroupLabel,
			priorityLookup: getRibbonGroupPriority,
		});

		const sepEls: HTMLElement[] = [];
		const renderedGroups: IRenderedRibbonGroup[] = [];

		groups.forEach((group, index) => {
			if (index > 0) {
				const sep = append(toolbar, $('div.sa-ribbon-group-sep'));
				sep.setAttribute('role', 'separator');
				sep.setAttribute('aria-orientation', 'vertical');
				sepEls.push(sep);
			}
			const groupEl = append(toolbar, $('div.sa-ribbon-group'));
			groupEl.setAttribute('role', 'group');
			groupEl.setAttribute('aria-labelledby', `sa-ribbon-grp-${descriptor.id}-${index}`);

			const disposables = this.panelDisposables.add(new DisposableStore());
			this.renderExpandedGroup(groupEl, descriptor.id, index, group, disposables, activeFrameActionsById);

			renderedGroups.push({
				model: group,
				tabId: descriptor.id,
				index,
				groupEl,
				disposables,
				collapsible: group.custom ? !!group.custom.collapsible : group.columns.length > 0,
				expandedWidth: groupEl.offsetWidth,
				collapsedWidth: undefined,
				collapsed: false,
			});
		});

		this.activePanelLayout = { toolbar, sepEls, groups: renderedGroups };
		this.relayoutGroups();

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

		if (hadPanelFocus) {
			const buttons = this.collectToolbarButtons(toolbar);
			buttons[this.toolbarFocusIndex]?.focus();
		}
	}

	private renderExpandedGroup(
		groupEl: HTMLElement,
		tabId: RibbonTabId,
		index: number,
		group: IRibbonGroupModel,
		store: DisposableStore,
		activeFrameActionsById: ReadonlyMap<string, IAction>,
	): void {
		const itemsEl = append(groupEl, $('div.sa-ribbon-items'));
		const labelEl = append(groupEl, $('div.sa-ribbon-group-label', undefined, group.label));
		labelEl.id = `sa-ribbon-grp-${tabId}-${index}`;

		if (group.custom) {
			store.add(group.custom.render(itemsEl, this.instantiationService));
			return;
		}

		for (const column of group.columns) {
			if (column.kind === 'large') {
				this.renderItem(itemsEl, column.item, store, activeFrameActionsById);
			} else {
				const stackEl = append(itemsEl, $('div.sa-ribbon-stack'));
				for (const item of column.items) {
					this.renderItem(stackEl, item, store, activeFrameActionsById);
				}
			}
		}
	}

	private renderCollapsedGroup(
		groupEl: HTMLElement,
		tabId: RibbonTabId,
		index: number,
		group: IRibbonGroupModel,
		store: DisposableStore,
	): void {
		const button = append(groupEl, $<HTMLButtonElement>('button.sa-ribbon-btn.sa-ribbon-btn-large.sa-ribbon-dropdown.sa-ribbon-group-collapse-btn'));
		button.type = 'button';
		button.setAttribute('aria-haspopup', 'menu');
		button.setAttribute('aria-expanded', 'false');
		button.setAttribute('aria-label', group.label);

		const icon = this.getGroupIcon(group);
		append(button, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(icon)}`)).setAttribute('aria-hidden', 'true');
		const labelSpan = append(button, $('span.sa-ribbon-btn-label', undefined, group.label));
		labelSpan.id = `sa-ribbon-grp-${tabId}-${index}`;
		append(button, $(`span.sa-ribbon-caret${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');

		store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, group.label));
		store.add(addDisposableListener(button, EventType.CLICK, () => {
			const menuStore = new DisposableStore();
			const groupActions = this.collectGroupActions(group, menuStore);
			if (!groupActions.length) {
				menuStore.dispose();
				return;
			}
			this.openSubmenu(button, button, groupActions, () => menuStore.dispose());
		}));
	}

	private getGroupIcon(group: IRibbonGroupModel): ThemeIcon {
		if (group.custom?.icon) {
			return group.custom.icon;
		}
		for (const column of group.columns) {
			if (column.kind === 'large') {
				return this.getItemIcon(column.item);
			}
		}
		const firstCol = group.columns[0];
		if (firstCol && firstCol.kind === 'stack' && firstCol.items.length) {
			return this.getItemIcon(firstCol.items[0]);
		}
		return Codicon.symbolMisc;
	}

	private getItemIcon(item: RibbonItem): ThemeIcon {
		if (item.kind === 'action') {
			return ThemeIcon.isThemeIcon(item.action.item.icon) ? item.action.item.icon : Codicon.symbolMisc;
		}
		if (ThemeIcon.isThemeIcon(item.action.item.icon)) {
			return item.action.item.icon;
		}
		if (item.primaryAction && ThemeIcon.isThemeIcon(item.primaryAction.item.icon)) {
			return item.primaryAction.item.icon;
		}
		return Codicon.symbolMisc;
	}

	private collectGroupActions(group: IRibbonGroupModel, store: DisposableStore): readonly IAction[] {
		if (group.custom?.getCollapsedActions) {
			return group.custom.getCollapsedActions(store);
		}
		const actions: IAction[] = [];
		for (const column of group.columns) {
			if (column.kind === 'large') {
				actions.push(column.item.action);
			} else {
				for (const item of column.items) {
					actions.push(item.action);
				}
			}
		}
		return actions;
	}

	private setGroupCollapsed(entry: IRenderedRibbonGroup, collapsed: boolean): void {
		if (entry.collapsed === collapsed) {
			return;
		}
		entry.disposables.clear();
		clearNode(entry.groupEl);
		entry.collapsed = collapsed;
		entry.groupEl.classList.toggle('sa-ribbon-group-collapsed', collapsed);
		if (collapsed) {
			this.renderCollapsedGroup(entry.groupEl, entry.tabId, entry.index, entry.model, entry.disposables);
			entry.collapsedWidth = entry.groupEl.offsetWidth;
		} else {
			const activeActions = new Map<string, IAction>();
			if (this.activeFrame) {
				for (const action of [...this.activeFrame.primaryActions, ...this.activeFrame.secondaryActions]) {
					if (!(action instanceof Separator) && !activeActions.has(action.id)) {
						activeActions.set(action.id, action);
					}
				}
			}
			this.renderExpandedGroup(entry.groupEl, entry.tabId, entry.index, entry.model, entry.disposables, activeActions);
			entry.expandedWidth = entry.groupEl.offsetWidth;
		}
	}

	private relayoutGroups(): void {
		const layout = this.activePanelLayout;
		if (!layout || this.collapsed) {
			return;
		}
		const availableWidth = this.panelsEl.clientWidth;
		if (availableWidth <= 0) {
			return;
		}

		for (const entry of layout.groups) {
			if (!entry.collapsed && entry.expandedWidth === 0) {
				entry.expandedWidth = entry.groupEl.offsetWidth;
			}
		}

		const style = getWindow(layout.toolbar).getComputedStyle(layout.toolbar);
		const paddingX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
		let sepWidth = 0;
		for (const sep of layout.sepEls) {
			sepWidth += sep.offsetWidth;
		}

		const collapsedSet = computeCollapsedRibbonGroups(
			layout.groups.map(entry => ({
				key: entry.model.key,
				order: entry.model.order,
				collapsePriority: entry.model.collapsePriority,
				collapsible: entry.collapsible,
				expandedWidth: entry.expandedWidth,
				collapsedWidth: entry.collapsedWidth ?? Math.min(entry.expandedWidth, 96),
			})),
			availableWidth,
			paddingX + sepWidth,
		);

		for (const entry of layout.groups) {
			this.setGroupCollapsed(entry, collapsedSet.has(entry.model.key));
		}

		// Re-check actual DOM width in case an estimated collapsedWidth was smaller than rendered text.
		while (layout.toolbar.scrollWidth > availableWidth) {
			const next = layout.groups
				.filter(entry => entry.collapsible && !entry.collapsed && entry.expandedWidth > (entry.collapsedWidth ?? 0))
				.sort((a, b) => a.model.collapsePriority - b.model.collapsePriority || b.model.order - a.model.order)[0];
			if (!next) {
				break;
			}
			const beforeWidth = layout.toolbar.scrollWidth;
			this.setGroupCollapsed(next, true);
			if (layout.toolbar.scrollWidth >= beforeWidth) {
				break;
			}
		}

		this.updateToolbarTabIndexes(layout.toolbar);
	}

	private updateToolbarTabIndexes(toolbar: HTMLElement): void {
		const buttons = this.collectToolbarButtons(toolbar);
		this.toolbarFocusIndex = Math.min(this.toolbarFocusIndex, Math.max(0, buttons.length - 1));
		buttons.forEach((button, idx) => {
			button.tabIndex = idx === this.toolbarFocusIndex ? 0 : -1;
		});
	}

	private collectToolbarButtons(container: HTMLElement, out: HTMLElement[] = []): HTMLElement[] {
		let child = container.firstElementChild;
		while (child) {
			if (isHTMLElement(child) && !child.classList.contains('sa-ribbon-ctrl-hidden') && !child.classList.contains('hidden')) {
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

	private renderItem(
		container: HTMLElement,
		item: RibbonItem,
		store: DisposableStore,
		activeFrameActionsById: ReadonlyMap<string, IAction>,
	): void {
		if (item.kind === 'action') {
			if (item.renderCustom) {
				store.add(item.renderCustom(container, this.instantiationService, item.action));
				return;
			}
			const action = item.action;
			const liveAction = activeFrameActionsById.get(action.id);
			const baseIcon = ThemeIcon.isThemeIcon(action.item.icon) ? action.item.icon : Codicon.symbolMisc;
			const button = append(container, $<HTMLButtonElement>(`button.sa-ribbon-btn.sa-ribbon-btn-${item.size}`));
			button.type = 'button';
			const iconEl = append(button, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(baseIcon)}`));
			iconEl.setAttribute('aria-hidden', 'true');
			append(button, $('span.sa-ribbon-btn-label', undefined, item.label));

			const fullTitle = typeof action.item.title === 'string' ? action.item.title : action.item.title.value;
			const hover = store.add(new MutableDisposable<IDisposable>());
			const syncActionState = () => {
				const icon = (liveAction ? this.iconOfAction(liveAction) : undefined) ?? baseIcon;
				iconEl.className = `sa-ribbon-icon ${ThemeIcon.asClassName(icon)}`;
				const checked = liveAction?.checked !== undefined ? liveAction.checked : action.checked;
				if (checked !== undefined) {
					button.setAttribute('aria-pressed', String(checked));
				} else {
					button.removeAttribute('aria-pressed');
				}
				const enabled = action.enabled && (liveAction ? liveAction.enabled : true);
				if (!enabled) {
					button.setAttribute('aria-disabled', 'true');
					button.classList.add('sa-ribbon-disabled');
				} else {
					button.removeAttribute('aria-disabled');
					button.classList.remove('sa-ribbon-disabled');
				}
				const titleText = liveAction?.label || fullTitle;
				const detailText = liveAction?.tooltip || action.tooltip;
				const tip = this.buildTooltip(action.id, titleText, detailText, enabled);
				button.setAttribute('aria-label', titleText);
				hover.value = this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip);
			};

			syncActionState();
			if (liveAction instanceof Action) {
				store.add(liveAction.onDidChange(syncActionState));
			}

			store.add(addDisposableListener(button, EventType.CLICK, () => {
				if (button.getAttribute('aria-disabled') === 'true') {
					return;
				}
				void (liveAction ?? action).run();
			}));
			return;
		}

		const submenu = item.action;
		if (item.isSplit && item.primaryAction) {
			const primary = item.primaryAction;
			const livePrimary = activeFrameActionsById.get(primary.id);
			const split = append(container, $(`div.sa-ribbon-split.sa-ribbon-split-${item.size}`));
			const hasEnabledChild = submenu.actions.some(a => a.enabled);

			const mainBtn = append(split, $<HTMLButtonElement>(`button.sa-ribbon-btn.sa-ribbon-btn-${item.size}.sa-ribbon-split-main`));
			mainBtn.type = 'button';
			const baseIcon = ThemeIcon.isThemeIcon(submenu.item.icon)
				? submenu.item.icon
				: ThemeIcon.isThemeIcon(primary.item.icon) ? primary.item.icon : Codicon.symbolMisc;
			const iconEl = append(mainBtn, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(baseIcon)}`));
			iconEl.setAttribute('aria-hidden', 'true');
			append(mainBtn, $('span.sa-ribbon-btn-label', undefined, item.label));

			const primaryTitle = typeof primary.item.title === 'string' ? primary.item.title : primary.item.title.value;
			const mainHover = store.add(new MutableDisposable<IDisposable>());
			const syncPrimaryState = () => {
				const icon = (livePrimary ? this.iconOfAction(livePrimary) : undefined) ?? baseIcon;
				iconEl.className = `sa-ribbon-icon ${ThemeIcon.asClassName(icon)}`;
				const enabled = primary.enabled && (livePrimary ? livePrimary.enabled : true);
				split.classList.toggle('sa-ribbon-disabled', !enabled && !hasEnabledChild);
				if (!enabled) {
					mainBtn.setAttribute('aria-disabled', 'true');
					mainBtn.classList.add('sa-ribbon-disabled');
				} else {
					mainBtn.removeAttribute('aria-disabled');
					mainBtn.classList.remove('sa-ribbon-disabled');
				}
				const titleText = livePrimary?.label || primaryTitle;
				const mainTip = this.buildTooltip(primary.id, titleText, livePrimary?.tooltip || primary.tooltip, enabled);
				mainBtn.setAttribute('aria-label', titleText);
				mainHover.value = this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), mainBtn, mainTip);
			};

			syncPrimaryState();
			if (livePrimary instanceof Action) {
				store.add(livePrimary.onDidChange(syncPrimaryState));
			}

			store.add(addDisposableListener(mainBtn, EventType.CLICK, () => {
				if (mainBtn.getAttribute('aria-disabled') === 'true') {
					return;
				}
				void (livePrimary ?? primary).run();
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
			store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), dropBtn, dropLabel));
			store.add(addDisposableListener(dropBtn, EventType.CLICK, () => {
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
		store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip));
		store.add(addDisposableListener(button, EventType.CLICK, () => {
			if (button.getAttribute('aria-disabled') === 'true') {
				return;
			}
			this.openSubmenu(button, button, submenu.actions);
		}));
	}

	private openSubmenu(anchor: HTMLElement, trigger: HTMLElement, actions: readonly IAction[], onHideDispose?: () => void): void {
		trigger.setAttribute('aria-expanded', 'true');
		this.contextMenuService.showContextMenu({
			getAnchor: () => anchor,
			getActions: () => actions,
			getKeyBinding: action => this.keybindingService.lookupKeybinding(action.id),
			onHide: () => {
				trigger.setAttribute('aria-expanded', 'false');
				onHideDispose?.();
			},
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
		const target = event.target;
		if (isHTMLElement(target) && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')) {
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
