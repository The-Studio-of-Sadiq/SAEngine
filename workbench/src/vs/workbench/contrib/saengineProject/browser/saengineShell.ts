/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { isISubmenuItem, MenuId, MenuRegistry } from '../../../../platform/actions/common/actions.js';
import { IConfigurationDefaults, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ContextKeyExpr, ContextKeyExpression } from '../../../../platform/contextkey/common/contextkey.js';
import { IViewContainersRegistry, IViewDescriptor, IViewsRegistry, ViewContainer } from '../../../common/views.js';
import { IProjectPart } from '../../../services/saengineProject/common/saengineProject.js';

/*
 * The building blocks of the SAEngine window chrome (see saengineShell.contribution.ts), kept free
 * of side effects so that they can be tested on their own.
 */

/** The part main files take their part's name as their editor title, e.g. "Soil Report" for soil-report.json. */
export function partEditorLabels(parts: readonly IProjectPart[]): Record<string, string> {
	const labels: Record<string, string> = {};
	for (const part of parts) {
		if (part.mainFile) {
			labels[`**/${part.folder}/${part.mainFile}`] = part.folder.replace(/^\d+\s+/, '');
		}
	}
	return labels;
}

/**
 * A set of configuration defaults that can be taken out again and put back, e.g. the simple
 * presentation that developer mode replaces with the stock one.
 */
export class ConfigurationDefaultsSwitch {

	private registered = false;

	constructor(
		private readonly registry: IConfigurationRegistry,
		private readonly defaults: IConfigurationDefaults,
	) { }

	get enabled(): boolean {
		return this.registered;
	}

	set(enabled: boolean): void {
		if (enabled === this.registered) {
			return;
		}
		if (enabled) {
			this.registry.registerDefaultConfigurations([this.defaults]);
		} else {
			this.registry.deregisterDefaultConfigurations([this.defaults]);
		}
		this.registered = enabled;
	}
}

/**
 * Adds a condition to the views of some containers, and to some single views. A view descriptor
 * cannot be changed once registered, so each one is registered again with the extended condition.
 * Views registered later are gated as they come.
 */
export class ViewsGate extends Disposable {

	private readonly gated = new WeakSet<IViewDescriptor>();

	constructor(
		private readonly condition: ContextKeyExpression,
		private readonly containers: ReadonlySet<string>,
		private readonly views: ReadonlySet<string>,
		viewContainersRegistry: IViewContainersRegistry,
		private readonly viewsRegistry: IViewsRegistry,
	) {
		super();
		for (const container of viewContainersRegistry.all) {
			this.gate(viewsRegistry.getViews(container), container);
		}
		this._register(viewsRegistry.onViewsRegistered(added => {
			for (const { views, viewContainer } of added) {
				this.gate(views, viewContainer);
			}
		}));
	}

	/** Registers views whose own condition already includes the gate's. */
	registerGated(views: IViewDescriptor[], container: ViewContainer): void {
		for (const view of views) {
			this.gated.add(view);
		}
		this.viewsRegistry.registerViews(views, container);
	}

	private gate(views: readonly IViewDescriptor[], container: ViewContainer): void {
		const wholeContainer = this.containers.has(container.id);
		const toGate = views.filter(view => !this.gated.has(view) && (wholeContainer || this.views.has(view.id)));
		if (!toGate.length) {
			return;
		}
		const replacements = toGate.map(view => ({ ...view, when: ContextKeyExpr.and(view.when, this.condition) }));
		for (const view of replacements) {
			this.gated.add(view);
		}
		this.viewsRegistry.deregisterViews(toGate, container);
		this.viewsRegistry.registerViews(replacements, container);
	}
}

/**
 * Adds a condition to some submenus of a menu. The menu registry has no API to change a
 * contributed item, so the condition of the item itself is extended; call this before the menu
 * is built.
 */
export function gateSubmenus(menu: MenuId, submenus: ReadonlySet<MenuId>, condition: ContextKeyExpression): void {
	for (const item of MenuRegistry.getMenuItems(menu)) {
		if (isISubmenuItem(item) && submenus.has(item.submenu)) {
			const gated: { when?: ContextKeyExpression } = item;
			gated.when = ContextKeyExpr.and(item.when, condition);
		}
	}
}

/** What the user had chosen for the developer items before simple mode hid them. */
export interface IDeveloperItemsSnapshot {
	readonly entries: Record<string, boolean>;
	readonly accounts: boolean;
}

/** The places where the status bar and the accounts entry keep their (per profile) visibility. */
export interface IDeveloperItemsHost {
	isEntryVisible(id: string): boolean;
	updateEntryVisibility(id: string, visible: boolean): void;
	isAccountsVisible(): boolean;
	setAccountsVisible(visible: boolean): void;
	readSnapshot(): IDeveloperItemsSnapshot | undefined;
	writeSnapshot(snapshot: IDeveloperItemsSnapshot | undefined): void;
}

/**
 * Hides the code-editor status bar items and the accounts entry in simple mode, and gives them
 * back as the user had them in developer mode. The visibility of these items is the user's own
 * choice (status bar context menu), so simple mode remembers it before hiding them and developer
 * mode restores it; in developer mode without such a memory nothing is touched (stock behaviour).
 */
export function applyDeveloperItems(developerMode: boolean, entries: readonly string[], host: IDeveloperItemsHost): void {
	const snapshot = host.readSnapshot();
	if (developerMode) {
		if (!snapshot) {
			return;
		}
		for (const id of entries) {
			const visible = snapshot.entries[id] ?? true;
			if (host.isEntryVisible(id) !== visible) {
				host.updateEntryVisibility(id, visible);
			}
		}
		if (host.isAccountsVisible() !== snapshot.accounts) {
			host.setAccountsVisible(snapshot.accounts);
		}
		host.writeSnapshot(undefined);
		return;
	}

	if (!snapshot) {
		const visibility: Record<string, boolean> = {};
		for (const id of entries) {
			visibility[id] = host.isEntryVisible(id);
		}
		host.writeSnapshot({ entries: visibility, accounts: host.isAccountsVisible() });
	}
	for (const id of entries) {
		if (host.isEntryVisible(id)) {
			host.updateEntryVisibility(id, false);
		}
	}
	if (host.isAccountsVisible()) {
		host.setAccountsVisible(false);
	}
}

/** Reads a stored {@link IDeveloperItemsSnapshot}; anything malformed counts as none. */
export function parseDeveloperItemsSnapshot(raw: string | undefined): IDeveloperItemsSnapshot | undefined {
	if (!raw) {
		return undefined;
	}
	try {
		const value = JSON.parse(raw);
		if (value && typeof value === 'object' && typeof value.accounts === 'boolean' && value.entries && typeof value.entries === 'object') {
			const entries: Record<string, boolean> = {};
			for (const [id, visible] of Object.entries(value.entries)) {
				if (typeof visible === 'boolean') {
					entries[id] = visible;
				}
			}
			return { entries, accounts: value.accounts };
		}
	} catch {
		// fall through
	}
	return undefined;
}
