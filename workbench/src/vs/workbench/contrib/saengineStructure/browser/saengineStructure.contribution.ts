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
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, STRUCTURE_PART } from '../../../services/saengineProject/common/saengineProject.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { StructureModelerEditor } from './structureModeler.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(StructureModelerEditor, StructureModelerEditor.ID, localize('structureModeler', "SAEngine Structural Model 3D")),
	[new SyncDescriptor(LibraryEditorInput)]
);

/** Opens a special structure's `05 Structural Model/structure.json` in the 3D modeller. */
class StructureModelerResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.structureModelerResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			`**/${STRUCTURE_PART.mainFile}`,
			{
				id: StructureModelerEditor.ID,
				label: localize('structureModeler.label', "Structural Model 3D"),
				detail: localize('structureModeler.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isStructure(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(LibraryEditorInput, resource, 'structure', StructureModelerEditor.ID),
					options,
				}),
			}
		));
	}

	private isStructure(resource: URI): boolean {
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && this.projectService.project?.type !== 'building' && isEqual(resource, joinPath(root, STRUCTURE_PART.folder, STRUCTURE_PART.mainFile!));
	}
}

registerWorkbenchContribution2(StructureModelerResolverContribution.ID, StructureModelerResolverContribution, WorkbenchPhase.BlockStartup);

/** Undo and redo in the modeller undo and redo its edits to the file. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof StructureModelerEditor ? (pane.input as LibraryEditorInput | undefined)?.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 10000;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-structure-modeler', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-structure-modeler', accessor => undoRedo(accessor, true));
