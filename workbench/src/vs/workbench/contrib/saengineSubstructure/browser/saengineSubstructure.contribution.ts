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
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { SubstructureEditor } from './substructureEditor.js';
import { SubstructureEditorInput, SubstructureEditorInputSerializer } from './substructureEditorInput.js';

/** Opens the substructure editor and sizes all foundations (the sizing assistant). */
export const SUBSTRUCTURE_SIZE_ALL_COMMAND = 'saengine.substructure.sizeAll';
/** Opens the substructure editor and imports the building model's footings. */
export const SUBSTRUCTURE_IMPORT_FOOTINGS_COMMAND = 'saengine.substructure.importFootings';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SubstructureEditor, SubstructureEditor.ID, localize('substructureEditorPane', "SAEngine Substructure")),
	[new SyncDescriptor(SubstructureEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(SubstructureEditorInput.ID, SubstructureEditorInputSerializer);

/** Opens the project's `09 Substructure/substructure.json` in the substructure editor. */
class SubstructureEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.substructureEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('substructure');
		if (!part?.mainFile) {
			return;
		}
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: SubstructureEditor.ID,
				label: localize('substructureEditor.label', "Substructure"),
				detail: localize('substructureEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isSubstructure(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(SubstructureEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isSubstructure(resource: URI): boolean {
		const part = partById('substructure');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(SubstructureEditorResolverContribution.ID, SubstructureEditorResolverContribution, WorkbenchPhase.BlockStartup);

/**
 * Ctrl+Z / Ctrl+Y in the substructure editor undo the file's text edits; inside a text field the
 * field's own undo still applies.
 */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof SubstructureEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

UndoCommand.addImplementation(110, 'saengine-substructure', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-substructure', accessor => undoRedo(accessor, true));

/** The substructure editor, opened on the project's file if it is not the active editor. */
async function substructureEditor(accessor: ServicesAccessor): Promise<SubstructureEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	const project = accessor.get(ISaengineProjectService).project;
	if (editorService.activeEditorPane instanceof SubstructureEditor) {
		return editorService.activeEditorPane;
	}
	const part = partById('substructure');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof SubstructureEditor ? pane : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SUBSTRUCTURE_SIZE_ALL_COMMAND,
			title: localize2('saengine.substructure.sizeAll', "Size Footings"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.wand,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await (await substructureEditor(accessor))?.sizeAll();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SUBSTRUCTURE_IMPORT_FOOTINGS_COMMAND,
			title: localize2('saengine.substructure.importFootings', "Import Footings from the Building Model into the Substructure"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.cloudDownload,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await (await substructureEditor(accessor))?.migrate();
	}
});
