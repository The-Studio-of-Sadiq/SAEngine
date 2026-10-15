/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { BoqEditor } from './boqEditor.js';
import { BoqEditorInput, BoqEditorInputSerializer } from './boqEditorInput.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(BoqEditor, BoqEditor.ID, localize('boqEditorPane', "SAEngine Bill of Quantities")),
	[new SyncDescriptor(BoqEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(BoqEditorInput.ID, BoqEditorInputSerializer);

/** Opens the project's `10 BOQ/boq.json` in the bill of quantities editor. */
class BoqEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.boqEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('boq');
		if (!part?.mainFile) {
			return;
		}
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: BoqEditor.ID,
				label: localize('boqEditor.label', "Bill of Quantities"),
				detail: localize('boqEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isBoq(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(BoqEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isBoq(resource: URI): boolean {
		const part = partById('boq');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(BoqEditorResolverContribution.ID, BoqEditorResolverContribution, WorkbenchPhase.BlockStartup);
