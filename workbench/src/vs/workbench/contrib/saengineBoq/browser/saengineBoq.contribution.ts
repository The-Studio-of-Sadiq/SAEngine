/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { BoqEditor } from './boqEditor.js';
import { BoqEditorInput, BoqEditorInputSerializer } from './boqEditorInput.js';
import { BOQ_EXPORT_CSV_COMMAND, exportBoqCsv, readProjectBoq } from './boqExport.js';

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

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: BOQ_EXPORT_CSV_COMMAND,
			title: localize2('saengine.boq.exportCsv', "Export Bill of Quantities as CSV..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.export,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const textModelService = accessor.get(ITextModelService);
		const fileService = accessor.get(IFileService);
		const fileDialogService = accessor.get(IFileDialogService);
		const notificationService = accessor.get(INotificationService);
		const openerService = accessor.get(IOpenerService);
		const commandService = accessor.get(ICommandService);
		if (!project) {
			return;
		}
		const document = await readProjectBoq(project, textModelService);
		if (!document) {
			notificationService.info(localize('boq.exportNotMeasured', "Measure the bill of quantities from the building model before exporting it."));
			return;
		}
		await exportBoqCsv(document, project, { textModelService, fileService, fileDialogService, notificationService, openerService, commandService });
	}
});
