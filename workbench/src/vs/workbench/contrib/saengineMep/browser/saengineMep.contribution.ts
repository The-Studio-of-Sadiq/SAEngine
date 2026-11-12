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
import { MepEditor } from './mepEditor.js';
import { MepEditorInput, MepEditorInputSerializer } from './mepEditorInput.js';

/** Opens the MEP editor and asks the backend for the sleeves the MEP IFC models' clashes need. */
export const MEP_SUGGEST_SLEEVES_EDITOR_COMMAND = 'saengine.mep.editor.suggestSleeves';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(MepEditor, MepEditor.ID, localize('mepEditorPane', "SAEngine MEP")),
	[new SyncDescriptor(MepEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(MepEditorInput.ID, MepEditorInputSerializer);

/** Opens the project's `07 MEP/mep.json` in the MEP editor. */
class MepEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.mepEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('mep');
		if (!part?.mainFile) {
			return;
		}
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: MepEditor.ID,
				label: localize('mepEditor.label', "MEP"),
				detail: localize('mepEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isMep(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(MepEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isMep(resource: URI): boolean {
		const part = partById('mep');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(MepEditorResolverContribution.ID, MepEditorResolverContribution, WorkbenchPhase.BlockStartup);

/** Ctrl+Z / Ctrl+Y in the MEP editor undo the file's text edits; inside a text field the field's own undo still applies. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof MepEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

UndoCommand.addImplementation(110, 'saengine-mep', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-mep', accessor => undoRedo(accessor, true));

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: MEP_SUGGEST_SLEEVES_EDITOR_COMMAND,
			title: localize2('saengine.mep.suggestSleevesTitle', "Suggest Sleeves from the MEP Clashes"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.wand,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const editorService = accessor.get(IEditorService);
		const project = accessor.get(ISaengineProjectService).project;
		const active = editorService.activeEditorPane;
		const part = partById('mep');
		const pane = active instanceof MepEditor ? active
			: project && part?.mainFile ? await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } }) : undefined;
		if (pane instanceof MepEditor) {
			await pane.suggestSleeves();
		}
	}
});
