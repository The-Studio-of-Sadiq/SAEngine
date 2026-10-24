/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { dxfCommandTarget, EXPORT_ARCHIVE_UI_COMMAND, IExportArchiveCommandArgs, IOpenArchiveCommandArgs, OPEN_ARCHIVE_UI_COMMAND, OPEN_DXF_IN_CAD_UI_COMMAND } from './projectArchiveModel.js';
import { ProjectArchiveFlows } from './projectArchiveFlows.js';
import { PROJECT_MENU, ProjectOpenContext } from './projectMenu.js';
import { ProjectNavigatorView } from './projectNavigatorView.js';
import { VersionsEditor } from './versionsEditor.js';
import { VersionsEditorInput, VersionsEditorInputSerializer } from './versionsEditorInput.js';
import { ISaveVersionCommandArgs, VersionsFlows } from './versionsFlows.js';
import './versionsService.js';
import './structuralImport.contribution.js';
import './newBuildingWizard.contribution.js';

/*
 * The project as a whole: its archive (`.civil`), its versions and the CAD hand-off of its
 * drawings. The work is the backend's (see projectArchiveModel.ts and versionsModel.ts for the
 * command ids); these are the menu entries, the Versions editor and the UI commands.
 */

const category = localize2('saengine.category', "SAEngine");

/** UI commands of the versions (the backend's are `saengine.versions.*`). */
export const SHOW_VERSIONS_COMMAND = 'saengine.project.showVersions';
export const SAVE_VERSION_COMMAND = 'saengine.project.saveVersion';

function asBag<T>(value: unknown): Partial<T> {
	return typeof value === 'object' && value !== null && !URI.isUri(value) ? value as Partial<T> : {};
}

// --- The project archive ----------------------------------------------------------------------

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: EXPORT_ARCHIVE_UI_COMMAND,
			title: localize2('saengine.exportProject', "Export Project..."),
			metadata: { description: localize2('saengine.exportProject.description', "Writes the open project into one .civil file, to send or keep. Arguments: {outPath, includeResults, includeVersions}.") },
			category,
			f1: true,
			icon: Codicon.package,
			precondition: ProjectOpenContext,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '4_save_print', order: 0, when: ProjectOpenContext },
				{ id: PROJECT_MENU, group: '3_share', order: 1 },
			],
		});
	}

	override run(accessor: ServicesAccessor, args?: IExportArchiveCommandArgs): Promise<URI | undefined> {
		return accessor.get(IInstantiationService).createInstance(ProjectArchiveFlows).exportProject(asBag<IExportArchiveCommandArgs>(args));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: OPEN_ARCHIVE_UI_COMMAND,
			title: localize2('saengine.openArchive', "Open Project Archive..."),
			metadata: { description: localize2('saengine.openArchive.description', "Unpacks a .civil file into a new project folder and opens it. Arguments: {path, destParent, name, open}.") },
			category,
			f1: true,
			menu: { id: MenuId.MenubarFileMenu, group: '2_open', order: 1 },
		});
	}

	override run(accessor: ServicesAccessor, args?: IOpenArchiveCommandArgs | string): Promise<URI | undefined> {
		const bag = typeof args === 'string' ? { path: args } : asBag<IOpenArchiveCommandArgs>(args);
		return accessor.get(IInstantiationService).createInstance(ProjectArchiveFlows).openArchive(bag);
	}
});

// --- CAD --------------------------------------------------------------------------------------

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: OPEN_DXF_IN_CAD_UI_COMMAND,
			title: localize2('saengine.openDxfInCad', "Open DXF in CAD..."),
			metadata: { description: localize2('saengine.openDxfInCad.description', "Opens a DXF drawing in LibreCAD (bundled), else in the system's DXF program. Argument: a file URI, a path or {path}.") },
			category,
			f1: true,
			menu: { id: MenuId.MenubarFileMenu, group: '4_save_print', order: 3, when: ProjectOpenContext },
		});
	}

	override run(accessor: ServicesAccessor, target?: unknown): Promise<boolean> {
		return accessor.get(IInstantiationService).createInstance(ProjectArchiveFlows).openDxfInCad(dxfCommandTarget(target));
	}
});

// --- Versions ---------------------------------------------------------------------------------

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(VersionsEditor, VersionsEditor.ID, localize('saengineVersionsEditor', "SAEngine Versions")),
	[new SyncDescriptor(VersionsEditorInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(VersionsEditorInput.ID, VersionsEditorInputSerializer);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SHOW_VERSIONS_COMMAND,
			title: localize2('saengine.showVersions', "Versions"),
			metadata: { description: localize2('saengine.showVersions.description', "Shows the project's versions: compare, restore and issue them.") },
			category,
			f1: true,
			icon: Codicon.history,
			precondition: ProjectOpenContext,
			menu: [
				{ id: MenuId.ViewTitle, group: 'navigation', order: 0, when: ContextKeyExpr.equals('view', ProjectNavigatorView.ID) },
				{ id: PROJECT_MENU, group: '1_project', order: 3 },
			],
		});
	}

	override run(accessor: ServicesAccessor): Promise<unknown> {
		return accessor.get(IEditorService).openEditor(VersionsEditorInput.instance, { pinned: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SAVE_VERSION_COMMAND,
			title: localize2('saengine.saveVersion', "Save Version..."),
			metadata: { description: localize2('saengine.saveVersion.description', "Saves the current files of the project as a version. Arguments: {message, issued, label, author}; any left out is asked.") },
			category,
			f1: true,
			precondition: ProjectOpenContext,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '4_save_print', order: 2, when: ProjectOpenContext },
				{ id: PROJECT_MENU, group: '1_project', order: 4 },
			],
		});
	}

	override run(accessor: ServicesAccessor, args?: ISaveVersionCommandArgs): Promise<unknown> {
		return accessor.get(IInstantiationService).createInstance(VersionsFlows).save(asBag<ISaveVersionCommandArgs>(args));
	}
});

// Opening an archive needs no open project; from the sidebar's ≡ menu it sits beside Export.
MenuRegistry.appendMenuItem(PROJECT_MENU, {
	command: { id: OPEN_ARCHIVE_UI_COMMAND, title: localize2('saengine.openArchiveShort', "Open Project Archive...") },
	group: '3_share',
	order: 2,
});
