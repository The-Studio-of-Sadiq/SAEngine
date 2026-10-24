/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { ISaengineProject, ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ImportReportEditor } from './importReportEditor.js';
import { ImportReportInput } from './importReportInput.js';
import { PROJECT_MENU } from './projectMenu.js';
import { StructuralImportFlows } from './structuralImportFlows.js';
import { IImportStructuralCommandArgs, IMPORT_STRUCTURAL_UI_COMMAND, sameFolder, SHOW_IMPORT_REPORT_COMMAND } from './structuralImportModel.js';

/*
 * Import from ETABS, STAAD.Pro or SAP2000 (≡ File menu, the sidebar's ≡ menu, the start page):
 * the backend's `saengine.import.structural` writes the project; this is the UI around it and
 * the import report.
 */

const category = localize2('saengine.category', "SAEngine");

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(ImportReportEditor, ImportReportInput.EDITOR_ID, localize('saengineImportReportEditor', "SAEngine Import Report")),
	[new SyncDescriptor(ImportReportInput)]
);

function asBag(value: unknown): IImportStructuralCommandArgs {
	if (typeof value === 'string') {
		return { path: value };
	}
	if (URI.isUri(value)) {
		return { path: value.fsPath };
	}
	return typeof value === 'object' && value !== null ? value as IImportStructuralCommandArgs : {};
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: IMPORT_STRUCTURAL_UI_COMMAND,
			title: localize2('saengine.importStructural', "Import from ETABS, STAAD or SAP2000..."),
			metadata: { description: localize2('saengine.importStructural.description', "Creates a new project from an ETABS (.e2k), STAAD.Pro (.std) or SAP2000 (.s2k) text file and shows what was imported. Arguments: {path, destParent, name, open}.") },
			category,
			f1: true,
			icon: Codicon.cloudDownload,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '2_open', order: 2 },
				{ id: PROJECT_MENU, group: '3_share', order: 3 },
			],
		});
	}

	override run(accessor: ServicesAccessor, args?: unknown): Promise<unknown> {
		return accessor.get(IInstantiationService).createInstance(StructuralImportFlows).importStructural(asBag(args));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SHOW_IMPORT_REPORT_COMMAND,
			title: localize2('saengine.showImportReport', "Show Import Report"),
			metadata: { description: localize2('saengine.showImportReport.description', "Shows the report of the last import from ETABS, STAAD.Pro or SAP2000.") },
			category,
			f1: true,
		});
	}

	override run(accessor: ServicesAccessor): Promise<boolean> {
		return accessor.get(IInstantiationService).createInstance(StructuralImportFlows).showReport();
	}
});

MenuRegistry.appendMenuItem(PROJECT_MENU, {
	command: { id: SHOW_IMPORT_REPORT_COMMAND, title: localize2('saengine.showImportReportShort', "Show Import Report") },
	group: '3_share',
	order: 4,
});

/** Opens the import report once more in the new project's window, beside the model. */
class ImportReportReopener extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengineImportReportReopener';

	private readonly flows: StructuralImportFlows;

	constructor(
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this.flows = instantiationService.createInstance(StructuralImportFlows);
		this.check(projectService.project);
		this._register(projectService.onDidChangeProject(project => this.check(project)));
	}

	private check(project: ISaengineProject | undefined): void {
		const entry = project && this.flows.takePendingReport(project.root.fsPath, sameFolder);
		if (entry) {
			void this.flows.showReport(entry);
		}
	}
}

registerWorkbenchContribution2(ImportReportReopener.ID, ImportReportReopener, WorkbenchPhase.AfterRestored);
