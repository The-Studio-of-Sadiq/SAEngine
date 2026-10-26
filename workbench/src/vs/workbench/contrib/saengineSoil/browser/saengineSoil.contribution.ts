/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { SoilEditor } from './soilEditor.js';
import { SoilEditorInput, SoilEditorInputSerializer } from './soilEditorInput.js';
import { SOIL_ADD_BOREHOLE_COMMAND, SOIL_IMPORT_FILE_COMMAND, SOIL_SAVE_TEMPLATE_COMMAND } from './soilDocument.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SoilEditor, SoilEditor.ID, localize('soilEditorPane', "SAEngine Soil Report")),
	[new SyncDescriptor(SoilEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(SoilEditorInput.ID, SoilEditorInputSerializer);

/** Opens the project's `01 Soil Report/soil-report.json` in the soil report editor. */
class SoilEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.soilEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('soil');
		if (!part?.mainFile) {
			return;
		}
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: SoilEditor.ID,
				label: localize('soilEditor.label', "Soil Report"),
				detail: localize('soilEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isSoilReport(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(SoilEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isSoilReport(resource: URI): boolean {
		const part = partById('soil');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(SoilEditorResolverContribution.ID, SoilEditorResolverContribution, WorkbenchPhase.BlockStartup);

/**
 * Ctrl+Z / Ctrl+Y in the soil report editor undo the file's text edits, wherever the keyboard
 * is in it (the list, a grid, a button), and say what was undone; inside a text field the
 * field's own undo still applies.
 */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	if (!(pane instanceof SoilEditor) || !pane.resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	return pane.undoRedo(redo);
}

UndoCommand.addImplementation(110, 'saengine-soil', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-soil', accessor => undoRedo(accessor, true));

/** The soil report editor, opened on the project's report if it is not the active editor. */
async function soilEditor(accessor: ServicesAccessor): Promise<SoilEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	const project = accessor.get(ISaengineProjectService).project;
	if (editorService.activeEditorPane instanceof SoilEditor) {
		return editorService.activeEditorPane;
	}
	const part = partById('soil');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof SoilEditor ? pane : undefined;
}

/** A file argument: a URI, or a file system path (scripts and tests pass one to skip the dialog). */
function fileArgument(file: URI | string | undefined): URI | undefined {
	return typeof file === 'string' ? URI.file(file) : URI.isUri(file) ? file : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SOIL_IMPORT_FILE_COMMAND,
			title: localize2('saengine.soil.importFile', "Import Boreholes from CSV/Excel..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.cloudDownload,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor, file?: URI | string): Promise<void> {
		const target = fileArgument(file);
		await (await soilEditor(accessor))?.importFile(target);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SOIL_SAVE_TEMPLATE_COMMAND,
			title: localize2('saengine.soil.saveTemplate', "Save Borehole Template..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.notebookTemplate,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor, file?: URI | string): Promise<void> {
		const target = fileArgument(file);
		await (await soilEditor(accessor))?.saveTemplate(target);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SOIL_ADD_BOREHOLE_COMMAND,
			title: localize2('saengine.soil.addBorehole', "Add Borehole to the Soil Report"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.add,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		(await soilEditor(accessor))?.addBorehole();
	}
});
