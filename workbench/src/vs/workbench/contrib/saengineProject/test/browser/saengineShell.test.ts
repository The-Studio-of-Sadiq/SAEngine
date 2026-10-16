/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { localize2 } from '../../../../../nls.js';
import { MenuId, MenuRegistry } from '../../../../../platform/actions/common/actions.js';
import { Extensions as ConfigurationExtensions, IConfigurationNode, IConfigurationRegistry } from '../../../../../platform/configuration/common/configurationRegistry.js';
import { ContextKeyExpr } from '../../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../../platform/instantiation/common/descriptors.js';
import { Registry } from '../../../../../platform/registry/common/platform.js';
import { ViewPane } from '../../../../browser/parts/views/viewPane.js';
import { ViewPaneContainer } from '../../../../browser/parts/views/viewPaneContainer.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewDescriptor, IViewsRegistry, ViewContainerLocation } from '../../../../common/views.js';
import { PROJECT_PARTS, STRUCTURE_PART } from '../../../../services/saengineProject/common/saengineProject.js';
import { applyDeveloperItems, ConfigurationDefaultsSwitch, gateSubmenus, IDeveloperItemsHost, IDeveloperItemsSnapshot, parseDeveloperItemsSnapshot, partEditorLabels, ViewsGate } from '../../browser/saengineShell.js';

const DEVELOPER = ContextKeyExpr.has('saengineDeveloperModeTest');

class TestView extends ViewPane { }

/** Status bar and accounts visibility in memory, as the user (or simple mode) left them. */
class TestHost implements IDeveloperItemsHost {
	readonly hidden = new Set<string>();
	accounts = true;
	snapshot: IDeveloperItemsSnapshot | undefined;
	isEntryVisible(id: string): boolean { return !this.hidden.has(id); }
	updateEntryVisibility(id: string, visible: boolean): void {
		if (visible) {
			this.hidden.delete(id);
		} else {
			this.hidden.add(id);
		}
	}
	isAccountsVisible(): boolean { return this.accounts; }
	setAccountsVisible(visible: boolean): void { this.accounts = visible; }
	readSnapshot(): IDeveloperItemsSnapshot | undefined { return this.snapshot; }
	writeSnapshot(snapshot: IDeveloperItemsSnapshot | undefined): void { this.snapshot = snapshot; }
	state() { return { hidden: [...this.hidden].sort(), accounts: this.accounts, remembered: !!this.snapshot }; }
}

suite('SAEngine - window shell', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	test('part main files take the part name as editor title', () => {
		assert.deepStrictEqual(partEditorLabels([...PROJECT_PARTS, STRUCTURE_PART]), {
			'**/01 Soil Report/soil-report.json': 'Soil Report',
			'**/02 Project Settings/project-settings.json': 'Project Settings',
			'**/03 Materials/materials.json': 'Materials',
			'**/04 Objects/objects.json': 'Objects',
			'**/05 Floor Plan/floor-plan.json': 'Floor Plan',
			'**/06 BIM/bim.json': 'BIM',
			'**/07 MEP/mep.json': 'MEP',
			'**/08 FEM/model.osmodel': 'FEM',
			'**/09 Substructure/substructure.json': 'Substructure',
			'**/10 BOQ/boq.json': 'BOQ',
			'**/05 Structural Model/structure.json': 'Structural Model',
		});
	});

	test('simple defaults are swapped in and out', () => {
		const registry = Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration);
		const node: IConfigurationNode = { id: 'saengineShellTest', properties: { 'saengineShellTest.value': { type: 'string', default: 'stock' } } };
		registry.registerConfiguration(node);
		try {
			const value = () => registry.getConfigurationProperties()['saengineShellTest.value'].default;
			const defaults = new ConfigurationDefaultsSwitch(registry, { overrides: { 'saengineShellTest.value': 'simple' }, source: { id: 'saengineShellTest' } });
			const seen = [value()];
			defaults.set(true);
			seen.push(value());
			defaults.set(true);
			seen.push(value());
			defaults.set(false);
			seen.push(value());
			defaults.set(true);
			seen.push(value());
			defaults.set(false);
			assert.deepStrictEqual(seen, ['stock', 'simple', 'simple', 'stock', 'simple']);
		} finally {
			registry.deregisterConfigurations([node]);
		}
	});

	test('code-editor views get the developer mode condition, also when registered later', () => {
		const containers = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry);
		const views = Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry);
		const devContainer = containers.registerViewContainer({ id: 'saengineShellTest.dev', title: localize2('dev', "Dev"), ctorDescriptor: new SyncDescriptor(ViewPaneContainer) }, ViewContainerLocation.Sidebar);
		const keptContainer = containers.registerViewContainer({ id: 'saengineShellTest.kept', title: localize2('kept', "Kept"), ctorDescriptor: new SyncDescriptor(ViewPaneContainer) }, ViewContainerLocation.Sidebar);
		const view = (id: string, when?: string): IViewDescriptor => ({ id, name: localize2('view', "View"), ctorDescriptor: new SyncDescriptor(TestView), when: when ? ContextKeyExpr.has(when) : undefined });
		try {
			views.registerViews([view('saengineShellTest.scm', 'scmProvider')], devContainer);
			views.registerViews([view('saengineShellTest.outline'), view('saengineShellTest.files')], keptContainer);
			store.add(new ViewsGate(DEVELOPER, new Set([devContainer.id]), new Set(['saengineShellTest.outline']), containers, views));
			views.registerViews([view('saengineShellTest.later')], devContainer);

			const conditions = (container: typeof devContainer) => Object.fromEntries(views.getViews(container).map(v => [v.id, v.when?.serialize()]));
			assert.deepStrictEqual({ dev: conditions(devContainer), kept: conditions(keptContainer) }, {
				dev: { 'saengineShellTest.scm': 'saengineDeveloperModeTest && scmProvider', 'saengineShellTest.later': 'saengineDeveloperModeTest' },
				kept: { 'saengineShellTest.outline': 'saengineDeveloperModeTest', 'saengineShellTest.files': undefined },
			});
		} finally {
			views.deregisterViews(views.getViews(devContainer), devContainer);
			views.deregisterViews(views.getViews(keptContainer), keptContainer);
			containers.deregisterViewContainer(devContainer);
			containers.deregisterViewContainer(keptContainer);
		}
	});

	test('code-only menus get the developer mode condition', () => {
		const parent = new MenuId('saengineShellTest.main');
		const code = new MenuId('saengineShellTest.go');
		const kept = new MenuId('saengineShellTest.file');
		store.add(MenuRegistry.appendMenuItem(parent, { submenu: code, title: 'Go', when: ContextKeyExpr.has('saengineShellTest.menu') }));
		store.add(MenuRegistry.appendMenuItem(parent, { submenu: kept, title: 'File' }));
		gateSubmenus(parent, new Set([code]), DEVELOPER);
		assert.deepStrictEqual(MenuRegistry.getMenuItems(parent).map(item => item.when?.serialize()), ['saengineDeveloperModeTest && saengineShellTest.menu', undefined]);
	});

	test('developer items follow the mode and keep what the user chose', () => {
		const entries = ['status.editor.selection', 'status.editor.encoding', 'status.problems'];
		const host = new TestHost();
		const steps: ReturnType<TestHost['state']>[] = [];

		// Developer mode from the start: stock, nothing touched; the user hides Encoding.
		applyDeveloperItems(true, entries, host);
		host.updateEntryVisibility('status.editor.encoding', false);
		applyDeveloperItems(true, entries, host); // next start
		steps.push(host.state());

		// Simple mode hides everything, also across restarts.
		applyDeveloperItems(false, entries, host);
		applyDeveloperItems(false, entries, host);
		steps.push(host.state());

		// Developer mode gives back the user's own choice: Encoding stays hidden.
		applyDeveloperItems(true, entries, host);
		steps.push(host.state());

		assert.deepStrictEqual(steps, [
			{ hidden: ['status.editor.encoding'], accounts: true, remembered: false },
			{ hidden: [...entries].sort(), accounts: false, remembered: true },
			{ hidden: ['status.editor.encoding'], accounts: true, remembered: false },
		]);
	});

	test('a malformed stored snapshot counts as none', () => {
		assert.deepStrictEqual([
			parseDeveloperItemsSnapshot(undefined),
			parseDeveloperItemsSnapshot('not json'),
			parseDeveloperItemsSnapshot('{"entries":{}}'),
			parseDeveloperItemsSnapshot('{"entries":{"a":false,"b":"x"},"accounts":false}'),
		], [undefined, undefined, undefined, { entries: { a: false }, accounts: false }]);
	});
});
