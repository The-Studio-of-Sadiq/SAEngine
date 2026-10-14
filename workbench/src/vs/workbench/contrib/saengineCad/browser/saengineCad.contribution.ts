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
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { CadEditorPane } from './cadEditor.js';
import { CadEditorInput, CadEditorInputSerializer } from './cadEditorInput.js';
import { FloorPlanEditor } from './floorPlanEditor.js';
import { FloorPlanEditorInput, FloorPlanEditorInputSerializer } from './floorPlanEditorInput.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(CadEditorPane, CadEditorInput.EDITOR_ID, localize('cadEditor', "CAD Drawing")),
	[new SyncDescriptor(CadEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(CadEditorInput.ID, CadEditorInputSerializer);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(FloorPlanEditor, FloorPlanEditorInput.EDITOR_ID, localize('floorPlanEditor', "Floor Plan")),
	[new SyncDescriptor(FloorPlanEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(FloorPlanEditorInput.ID, FloorPlanEditorInputSerializer);

const FLOOR_PLAN_PART = PROJECT_PARTS.find(p => p.id === 'floorPlan')!;

class CadEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.cadEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@IInstantiationService instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			'*.dxf',
			{
				id: CadEditorInput.EDITOR_ID,
				label: localize('cadEditor.label', "CAD Drawing Editor"),
				detail: localize('cadEditor.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{ singlePerResource: true },
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(CadEditorInput, resource),
					options,
				}),
			}
		));

		// The project's floor plan opens as the plan view of its building model.
		this._register(editorResolverService.registerEditor(
			`**/${FLOOR_PLAN_PART.mainFile}`,
			{
				id: FloorPlanEditorInput.EDITOR_ID,
				label: localize('floorPlanEditor.label', "Floor Plan"),
				detail: localize('cadEditor.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isFloorPlan(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(FloorPlanEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isFloorPlan(resource: URI): boolean {
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && isEqual(resource, joinPath(root, FLOOR_PLAN_PART.folder, FLOOR_PLAN_PART.mainFile!));
	}
}

registerWorkbenchContribution2(CadEditorResolverContribution.ID, CadEditorResolverContribution, WorkbenchPhase.BlockStartup);

/** Ctrl+Z / Ctrl+Y in the floor plan undo and redo its edits to the building model. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof FloorPlanEditor ? pane.bimResource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 110;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-floor-plan', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-floor-plan', accessor => undoRedo(accessor, true));
