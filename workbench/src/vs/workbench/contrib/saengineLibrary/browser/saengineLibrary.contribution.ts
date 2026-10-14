/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize } from '../../../../nls.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { LibraryEditor } from './libraryEditor.js';
import { LibraryEditorInput, LibraryEditorInputSerializer, LibraryKind } from './libraryEditorInput.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(LibraryEditor, LibraryEditorInput.EDITOR_ID, localize('libraryEditor', "SAEngine Library Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(LibraryEditorInput.ID, LibraryEditorInputSerializer);

/**
 * Opens the project's `03 Materials/materials.json` and `04 Objects/objects.json` in the
 * visual editor by default. Other files with the same names are not affected, and the JSON
 * stays reachable on purpose through "Reopen Editor With...".
 */
class LibraryEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.libraryEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		for (const kind of ['materials', 'objects'] as const) {
			const part = PROJECT_PARTS.find(p => p.id === kind);
			if (!part?.mainFile) {
				continue;
			}
			this._register(editorResolverService.registerEditor(
				`**/${part.mainFile}`,
				{
					id: LibraryEditorInput.EDITOR_ID,
					label: kind === 'materials' ? localize('materialsEditorLabel', "Materials Editor") : localize('objectsEditorLabel', "Object Types Editor"),
					detail: localize('libraryEditorDetail', "SAEngine"),
					priority: RegisteredEditorPriority.default,
				},
				{
					singlePerResource: true,
					canSupportResource: resource => this.kindOf(resource) === kind,
				},
				{
					createEditorInput: ({ resource, options }) => ({
						editor: instantiationService.createInstance(LibraryEditorInput, resource, kind),
						options,
					}),
				}
			));
		}
	}

	private kindOf(resource: URI): LibraryKind | undefined {
		const project = this.projectService.project;
		if (!project) {
			return undefined;
		}
		for (const kind of ['materials', 'objects'] as const) {
			const part = PROJECT_PARTS.find(p => p.id === kind);
			if (part?.mainFile && isEqual(resource, joinPath(project.root, part.folder, part.mainFile))) {
				return kind;
			}
		}
		return undefined;
	}
}

registerWorkbenchContribution2(LibraryEditorResolverContribution.ID, LibraryEditorResolverContribution, WorkbenchPhase.BlockStartup);

/**
 * Ctrl+Z / Ctrl+Y in the visual editor undo the file's text edits; inside a text field the
 * field's own undo still applies.
 */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof LibraryEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 110;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-library', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-library', accessor => undoRedo(accessor, true));
