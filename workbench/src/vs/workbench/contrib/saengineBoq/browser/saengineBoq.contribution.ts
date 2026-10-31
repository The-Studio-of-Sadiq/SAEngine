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
import { BOQ_EXPORT_CSV_COMMAND, BOQ_EXPORT_XLSX_COMMAND, exportBoqCsv, exportBoqXlsx, readProjectBoq } from './boqExport.js';
import { BOQ_RATES_FILE, BOQ_CARBON_FILE, ensureBoqFile } from './boqCosting.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';

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

/** The bill as it is now (unsaved edits included) as text, or undefined when it was not measured. */
async function projectBoqText(accessor: ServicesAccessor): Promise<string | undefined> {
	const project = accessor.get(ISaengineProjectService).project;
	const part = partById('boq');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const document = await readProjectBoq(project, accessor.get(ITextModelService));
	return document ? JSON.stringify(document) : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: BOQ_EXPORT_XLSX_COMMAND,
			title: localize2('saengine.boq.exportXlsx', "Export Bill of Quantities to Excel (with Costing and Carbon)..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.export,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const services = {
			textModelService: accessor.get(ITextModelService),
			fileService: accessor.get(IFileService),
			fileDialogService: accessor.get(IFileDialogService),
			notificationService: accessor.get(INotificationService),
			openerService: accessor.get(IOpenerService),
			commandService: accessor.get(ICommandService),
		};
		if (!project) {
			return;
		}
		const text = await projectBoqText(accessor);
		if (!text) {
			services.notificationService.info(localize('boq.exportNotMeasured', "Measure the bill of quantities from the building model before exporting it."));
			return;
		}
		await exportBoqXlsx(text, project, services);
	}
});

for (const [kind, id, title, file] of [
	['rates', 'saengine.boq.editRates', localize2('saengine.boq.editRates', "Edit Schedule of Rates"), BOQ_RATES_FILE],
	['carbon', 'saengine.boq.editCarbon', localize2('saengine.boq.editCarbon', "Edit Embodied Carbon Factors"), BOQ_CARBON_FILE],
] as const) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title, category: localize2('saengine.category', "SAEngine"), f1: true, precondition: ContextKeyExpr.has('saengineProjectOpen') });
		}

		/** Opens `10 BOQ/<file>`, made from the shipped template when the project has none. */
		override async run(accessor: ServicesAccessor): Promise<void> {
			const project = accessor.get(ISaengineProjectService).project;
			const notificationService = accessor.get(INotificationService);
			const editorService = accessor.get(IEditorService);
			if (!project) {
				return;
			}
			try {
				const resource = await ensureBoqFile(project, kind, accessor.get(IFileService), accessor.get(ICommandService));
				if (resource) {
					await editorService.openEditor({ resource, options: { pinned: true } });
				}
			} catch (error) {
				notificationService.error(localize('boq.editFileFailed', "{0} could not be created: {1}", file, String(error)));
			}
		}
	});
}
