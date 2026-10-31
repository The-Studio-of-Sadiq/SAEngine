/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { PROJECT_MENU } from '../../saengineProject/browser/projectMenu.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { PACKAGES_SHOW_COMMAND } from '../common/packageIndex.js';
import { CodePacksEditor, IInstallCodePackArgs, INewCodePackArgs, IShowPackagesArgs } from './codePacksEditor.js';
import { CodePacksEditorInput, CodePacksEditorInputSerializer } from './codePacksEditorInput.js';

const category = localize2('saengine.category', "SAEngine");

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(CodePacksEditor, CodePacksEditor.ID, localize('saengineCodePacksEditor', "SAEngine Packages")),
	[new SyncDescriptor(CodePacksEditorInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(CodePacksEditorInput.ID, CodePacksEditorInputSerializer);

async function openPage(accessor: ServicesAccessor): Promise<CodePacksEditor | undefined> {
	const pane = await accessor.get(IEditorService).openEditor(CodePacksEditorInput.instance, { pinned: true });
	return pane instanceof CodePacksEditor ? pane : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PACKAGES_SHOW_COMMAND,
			title: localize2('saengine.packages.show', "Packages..."),
			category,
			icon: Codicon.package,
			f1: true,
			menu: { id: PROJECT_MENU, group: '1_project', order: 7 },
		});
	}

	/** `args` (optional): `{ tab: 'installed' | 'browse' | 'updates', kind }`. */
	override async run(accessor: ServicesAccessor, args?: IShowPackagesArgs): Promise<void> {
		(await openPage(accessor))?.show(args);
	}
});

// The page's earlier name: kept so links, keybindings and scripts that open Code Packs still work.
CommandsRegistry.registerCommand('saengine.codePacks.show', (accessor, args?: IShowPackagesArgs) => accessor.get(ICommandService).executeCommand(PACKAGES_SHOW_COMMAND, args));

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.codePacks.new',
			title: localize2('saengine.codePacks.new', "New Code Pack..."),
			category,
			f1: true,
		});
	}

	/** `args` (optional): `{ id, name, extends, scope }`, asked for when missing. */
	override async run(accessor: ServicesAccessor, args?: INewCodePackArgs): Promise<void> {
		await (await openPage(accessor))?.newPack(args);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.codePacks.install',
			title: localize2('saengine.codePacks.install', "Install Package from File..."),
			category,
			f1: true,
		});
	}

	/** `args` (optional): `{ path, scope }`; without a path a folder or .zip is picked. */
	override async run(accessor: ServicesAccessor, args?: IInstallCodePackArgs): Promise<void> {
		await (await openPage(accessor))?.install(args);
	}
});
