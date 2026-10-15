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
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { BuildingEditor } from './buildingEditor.js';
import { GridsEditor } from './gridsEditor.js';
import { SettingsEditor } from './settingsEditor.js';
import { StructureEditor } from './structureEditor.js';
import { JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditor } from './libraryEditor.js';
import { LibraryEditorInput, LibraryEditorInputSerializer, LibraryKind } from './libraryEditorInput.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(LibraryEditor, LibraryEditorInput.EDITOR_ID, localize('libraryEditor', "SAEngine Library Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(BuildingEditor, LibraryEditorInput.BUILDING_EDITOR_ID, localize('buildingEditor', "SAEngine Building Model Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(GridsEditor, LibraryEditorInput.GRIDS_EDITOR_ID, localize('gridsEditor', "SAEngine Grids and Stories Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SettingsEditor, LibraryEditorInput.SETTINGS_EDITOR_ID, localize('settingsEditorPane', "SAEngine Project Settings Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(StructureEditor, LibraryEditorInput.STRUCTURE_EDITOR_ID, localize('structureEditorPane', "SAEngine Structural Model Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(LibraryEditorInput.ID, LibraryEditorInputSerializer);

/** Project files with a visual editor; each is the main file of the project part with that id. */
const KINDS: readonly LibraryKind[] = ['settings', 'materials', 'objects', 'floorPlan', 'structure', 'bim'];

const EDITOR_LABELS: { readonly [kind in LibraryKind]: string } = {
	materials: localize('materialsEditorLabel', "Materials Editor"),
	objects: localize('objectsEditorLabel', "Object Types Editor"),
	floorPlan: localize('gridsEditorLabel', "Grids & Stories Editor"),
	settings: localize('settingsEditorLabel', "Project Settings Editor"),
	bim: localize('buildingEditorLabel', "Building Model Editor"),
	structure: localize('structureEditorLabel', "Structural Model Editor"),
};

const EDITOR_IDS: { readonly [kind in LibraryKind]: string } = {
	materials: LibraryEditorInput.EDITOR_ID,
	objects: LibraryEditorInput.EDITOR_ID,
	floorPlan: LibraryEditorInput.GRIDS_EDITOR_ID,
	settings: LibraryEditorInput.SETTINGS_EDITOR_ID,
	bim: LibraryEditorInput.BUILDING_EDITOR_ID,
	structure: LibraryEditorInput.STRUCTURE_EDITOR_ID,
};

/**
 * Opens the project's `03 Materials/materials.json`, `04 Objects/objects.json` and
 * `06 BIM/bim.json` in their visual editors by default. `05 Floor Plan/floor-plan.json` opens in
 * the plan view (Floor Plan editor) and offers its grids and stories form as an option. Other
 * files with the same names are not affected, and the JSON stays reachable on purpose through
 * "Reopen Editor With...".
 */
class LibraryEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.libraryEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		for (const kind of KINDS) {
			const part = partById(kind);
			if (!part?.mainFile) {
				continue;
			}
			this._register(editorResolverService.registerEditor(
				`**/${part.mainFile}`,
				{
					id: EDITOR_IDS[kind],
					label: EDITOR_LABELS[kind],
					detail: localize('libraryEditorDetail', "SAEngine"),
					// The floor plan opens in its plan view; the form is the alternative.
					priority: kind === 'floorPlan' ? RegisteredEditorPriority.option : RegisteredEditorPriority.default,
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
		// Project detection is asynchronous; until it finishes, a part's main file in the
		// workspace folder is matched by path so files opened at startup still get their editor.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		if (!root) {
			return undefined;
		}
		// The project's own parts only: a floor plan left in a special structure is a plain file.
		const parts = this.projectService.project ? this.projectService.parts : undefined;
		for (const kind of KINDS) {
			const part = partById(kind);
			if (parts && !parts.includes(part!)) {
				continue;
			}
			if (part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile))) {
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
	const resource = pane instanceof JsonDocumentEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 110;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-library', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-library', accessor => undoRedo(accessor, true));
