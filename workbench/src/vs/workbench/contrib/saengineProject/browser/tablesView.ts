/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/tablesView.css';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewDescriptorService, IViewsRegistry, ViewContainerLocation } from '../../../common/views.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { activeTableId, ISaengineTable, ISaengineTableDescriptor, SaengineTableRegistry } from './modelLayoutModel.js';

/*
 * The Tables panel below the model view: one tab per table of the project (members, storeys,
 * and whatever a part registers), each filtered on the storey the model view shows and
 * selecting what the model view, the Properties panel and the Model Explorer show
 * (modelSelection.ts). A part registers its table with `SaengineTables.register`; the table
 * itself stays the part's (the Members Table editor and its tab are one implementation).
 */

export const TABLES_VIEW_ID = 'saengine.tables';
export const TABLES_VIEW_CONTAINER_ID = 'workbench.panel.saengineTables';

/** The tables of the Tables panel: a part registers its own with `SaengineTables.register`. */
export const SaengineTables = new SaengineTableRegistry();

const ACTIVE_TAB_KEY = 'saengine.tables.activeTab';

interface IOpenTable {
	readonly descriptor: ISaengineTableDescriptor;
	readonly element: HTMLElement;
	readonly table: ISaengineTable;
}

export class TablesView extends ViewPane {

	static readonly ID = TABLES_VIEW_ID;

	private tabs: HTMLElement | undefined;
	private tablesBody: HTMLElement | undefined;
	private empty: HTMLElement | undefined;
	private readonly tabStore = this._register(new DisposableStore());
	private readonly open = new Map<string, IOpenTable>();
	private readonly tabButtons = new Map<string, HTMLElement>();
	private active: string | undefined;
	private size: { width: number; height: number } = { width: 0, height: 0 };

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IStorageService private readonly storageService: IStorageService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this._register(toDisposable(() => this.closeTables()));
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		container.classList.add('saengine-tables-view');
		this.tabs = append(container, $('.sa-tables-tabs', { role: 'tablist', 'aria-label': localize('tables.aria', "Tables") }));
		this.tablesBody = append(container, $('.sa-tables-body'));
		this.empty = append(this.tablesBody, $('.sa-tables-empty'));
		this._register(addDisposableListener(this.tabs, EventType.KEY_DOWN, e => this.onTabKey(new StandardKeyboardEvent(e))));
		this._register(SaengineTables.onDidChange(() => this.renderTables()));
		this._register(this.projectService.onDidChangeProject(() => {
			this.closeTables(); // the tables of another project
			this.renderTables();
		}));
		this._register(this.onDidChangeBodyVisibility(visible => this.open.get(this.active ?? '')?.table.setVisible?.(visible)));
		this.renderTables();
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
		const tabsHeight = this.tabs?.offsetHeight ?? 0;
		this.size = { width, height: Math.max(0, height - tabsHeight) };
		this.open.get(this.active ?? '')?.table.layout(this.size.width, this.size.height);
	}

	override focus(): void {
		super.focus();
		const table = this.open.get(this.active ?? '')?.table;
		if (table?.focus) {
			table.focus();
		} else {
			this.tabButtons.get(this.active ?? '')?.focus();
		}
	}

	/** Shows the tab of table `id` (a part's "Show in Tables"). */
	showTable(id: string): void {
		const ids = SaengineTables.tablesOf(this.projectService.project).map(d => d.id);
		if (ids.includes(id)) {
			this.active = id;
			this.storageService.store(ACTIVE_TAB_KEY, id, StorageScope.WORKSPACE, StorageTarget.MACHINE);
			this.renderTables();
		}
	}

	private renderTables(): void {
		const tabs = this.tabs;
		const body = this.tablesBody;
		if (!tabs || !body || !this.empty) {
			return;
		}
		this.tabStore.clear();
		this.tabButtons.clear();
		clearNode(tabs);
		const descriptors = SaengineTables.tablesOf(this.projectService.project);
		for (const id of [...this.open.keys()]) {
			if (!descriptors.some(d => d.id === id)) {
				this.closeTable(id);
			}
		}
		this.active = activeTableId(descriptors.map(d => d.id), this.active ?? this.storageService.get(ACTIVE_TAB_KEY, StorageScope.WORKSPACE));
		this.empty.classList.toggle('visible', !descriptors.length);
		this.empty.textContent = this.projectService.project
			? localize('tables.none', "This project has no tables yet.")
			: localize('tables.noProject', "Open a project to see its members and storeys as tables.");
		tabs.classList.toggle('hidden', descriptors.length < 1);

		for (const descriptor of descriptors) {
			const selected = descriptor.id === this.active;
			const tab = append(tabs, $<HTMLButtonElement>('button.sa-tables-tab', {
				type: 'button', role: 'tab', id: `sa-tables-tab-${descriptor.id}`,
				'aria-selected': String(selected), tabIndex: selected ? 0 : -1,
			}, descriptor.label()));
			tab.classList.toggle('checked', selected);
			this.tabButtons.set(descriptor.id, tab);
			this.tabStore.add(addDisposableListener(tab, EventType.CLICK, () => this.showTable(descriptor.id)));
		}

		for (const [id, open] of this.open) {
			const shown = id === this.active;
			if (open.element.classList.contains('hidden') === shown) {
				open.element.classList.toggle('hidden', !shown);
				open.table.setVisible?.(shown && this.isBodyVisible());
			}
		}
		const descriptor = descriptors.find(d => d.id === this.active);
		if (descriptor && !this.open.has(descriptor.id)) {
			const element = append(body, $('.sa-tables-table', { role: 'tabpanel', 'aria-labelledby': `sa-tables-tab-${descriptor.id}` }));
			const table = descriptor.create(element, this.instantiationService);
			this.open.set(descriptor.id, { descriptor, element, table });
			table.setVisible?.(this.isBodyVisible());
		}
		if (this.size.width && this.size.height) {
			this.open.get(this.active ?? '')?.table.layout(this.size.width, this.size.height);
		}
	}

	/** Left and Right (Home, End) move between the tabs, as in a tab list. */
	private onTabKey(event: StandardKeyboardEvent): void {
		const descriptors = SaengineTables.tablesOf(this.projectService.project);
		const index = descriptors.findIndex(d => d.id === this.active);
		let next: number | undefined;
		if (event.equals(KeyCode.RightArrow)) {
			next = (index + 1) % descriptors.length;
		} else if (event.equals(KeyCode.LeftArrow)) {
			next = (index - 1 + descriptors.length) % descriptors.length;
		} else if (event.equals(KeyCode.Home)) {
			next = 0;
		} else if (event.equals(KeyCode.End)) {
			next = descriptors.length - 1;
		}
		if (next !== undefined && descriptors[next]) {
			event.preventDefault();
			event.stopPropagation();
			this.showTable(descriptors[next].id);
			this.tabButtons.get(descriptors[next].id)?.focus();
		}
	}

	private closeTable(id: string): void {
		const open = this.open.get(id);
		if (open) {
			open.table.dispose();
			open.element.remove();
			this.open.delete(id);
		}
	}

	private closeTables(): void {
		for (const id of [...this.open.keys()]) {
			this.closeTable(id);
		}
	}
}

const tablesViewIcon = registerIcon('saengine-tables-view-icon', Codicon.table, localize('tablesViewIcon', "View icon of the SAEngine Tables."));

const tablesContainer = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry).registerViewContainer({
	id: TABLES_VIEW_CONTAINER_ID,
	title: localize2('tables', "Tables"),
	icon: tablesViewIcon,
	order: -2,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [TABLES_VIEW_CONTAINER_ID, { mergeViewWithContainerWhenSingleView: true }]),
	storageId: TABLES_VIEW_CONTAINER_ID,
}, ViewContainerLocation.Panel, { doNotRegisterOpenCommand: true });

Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry).registerViews([{
	id: TABLES_VIEW_ID,
	name: localize2('tables', "Tables"),
	containerIcon: tablesViewIcon,
	ctorDescriptor: new SyncDescriptor(TablesView),
	canToggleVisibility: false,
	canMoveView: true,
	order: 0,
}], tablesContainer);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.showTables',
			title: localize2('saengine.showTables', "Show Tables"),
			metadata: { description: localize2('saengine.showTables.description', "Opens the Tables below the model view: members, storeys and the other tables of the project.") },
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IViewsService).openView(TABLES_VIEW_ID, true);
	}
});
