/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { CadEditorPane } from './cadEditor.js';
import { CadEditorInput, CadEditorInputSerializer } from './cadEditorInput.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(CadEditorPane, CadEditorInput.EDITOR_ID, localize('cadEditor', "CAD Drawing")),
	[new SyncDescriptor(CadEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(CadEditorInput.ID, CadEditorInputSerializer);

class CadEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.cadEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@IInstantiationService instantiationService: IInstantiationService,
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
	}
}

registerWorkbenchContribution2(CadEditorResolverContribution.ID, CadEditorResolverContribution, WorkbenchPhase.BlockStartup);
