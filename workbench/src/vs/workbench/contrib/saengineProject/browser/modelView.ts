/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IWorkbenchLayoutService, Parts } from '../../../services/layout/browser/layoutService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { openPart } from './projectParts.js';
import { PROPERTIES_VIEW_ID } from './propertiesDock.js';
import { TABLES_VIEW_ID } from './tablesView.js';
import { MODEL_LAYOUT_VERSION, ModelViewKind, modelViewPart, needsModelLayout } from './modelLayoutModel.js';

/*
 * The model view: the building model in the centre of the window, as plan, 3D or analysis model
 * (with its plans and elevations), the three existing editors of one model. The Project tree
 * opens each editor; the selection follows between them (modelSelection.ts).
 *
 *   ┌ parts ┐┌ Plan | 3D | Analysis ─ model view ──────────┐┌ Properties ┐
 *   │       ││                                             ││ selection  │
 *   │       │├ Tables (Members, Storeys) ──────────────────┤│            │
 *   └───────┘└─────────────────────────────────────────────┘└────────────┘
 */

export type { ModelViewKind } from './modelLayoutModel.js';

/** Opens the model view: `plan` (default), `3d` or `analysis`. */
export const SHOW_MODEL_VIEW_COMMAND = 'saengine.showModelView';

async function showModelView(accessor: ServicesAccessor, kind: ModelViewKind = 'plan', options?: { readonly preserveFocus?: boolean }): Promise<boolean> {
	const project = accessor.get(ISaengineProjectService).project;
	const part = project && partById(modelViewPart(kind, project));
	if (!project || !part) {
		return false;
	}
	await openPart(project, part, {
		editorService: accessor.get(IEditorService),
		fileService: accessor.get(IFileService),
		openerService: accessor.get(IOpenerService),
		commandService: accessor.get(ICommandService),
	}, options);
	return true;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SHOW_MODEL_VIEW_COMMAND,
			title: localize2('saengine.showModelView', "Show Model View"),
			metadata: { description: localize2('saengine.showModelView.description', "Opens the building model in the centre: the plan, the 3D view or the analysis model.") },
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
		});
	}

	override run(accessor: ServicesAccessor, kind?: ModelViewKind): Promise<boolean> {
		return showModelView(accessor, kind === '3d' || kind === 'analysis' ? kind : 'plan');
	}
});

const MODEL_LAYOUT_KEY = 'saengine.layout.version';

/** The Properties panel's width and the Tables' height the first time [px]: room for the model at 1366×768. */
const PROPERTIES_WIDTH = 280;
const TABLES_HEIGHT = 240;

/**
 * The first time a project opens after this layout came in, the Properties panel opens on the
 * right and the Tables below the model view; after that the window keeps what the engineer made
 * of it (a closed panel stays closed).
 */
export class ModelLayoutContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.modelLayout';

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IStorageService private readonly storageService: IStorageService,
		@IViewsService private readonly viewsService: IViewsService,
		@IWorkbenchLayoutService private readonly layoutService: IWorkbenchLayoutService,
	) {
		super();
		this._register(projectService.onDidChangeProject(() => void this.apply()));
		void this.apply();
	}

	private async apply(): Promise<void> {
		if (!this.projectService.project || !needsModelLayout(this.storageService.getNumber(MODEL_LAYOUT_KEY, StorageScope.PROFILE, 0))) {
			return;
		}
		this.storageService.store(MODEL_LAYOUT_KEY, MODEL_LAYOUT_VERSION, StorageScope.PROFILE, StorageTarget.USER);
		await this.viewsService.openView(PROPERTIES_VIEW_ID, false);
		await this.viewsService.openView(TABLES_VIEW_ID, false);
		const window = this.layoutService.mainContainerDimension;
		this.layoutService.setSize(Parts.AUXILIARYBAR_PART, { width: Math.min(PROPERTIES_WIDTH, Math.round(window.width * 0.25)), height: this.layoutService.getSize(Parts.AUXILIARYBAR_PART).height });
		this.layoutService.setSize(Parts.PANEL_PART, { width: this.layoutService.getSize(Parts.PANEL_PART).width, height: Math.min(TABLES_HEIGHT, Math.round(window.height * 0.32)) });
	}
}

registerWorkbenchContribution2(ModelLayoutContribution.ID, ModelLayoutContribution, WorkbenchPhase.AfterRestored);
