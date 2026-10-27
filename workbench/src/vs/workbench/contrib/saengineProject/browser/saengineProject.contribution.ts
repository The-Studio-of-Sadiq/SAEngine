/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/projectFlow.css';
import './saengineShell.contribution.js';
import './truncatedText.contribution.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceContextService, WorkbenchState } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ProjectOpener } from './projectOpener.js';
import { StartEditor } from './startEditor.js';
import { StartEditorInput } from './startEditorInput.js';

const category = localize2('saengine.category', "SAEngine");

// SAEngine opens its own start page; VS Code's welcome page and onboarding stay out of the way.
// The window chrome and developer mode are in saengineShell.contribution.ts.
Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerDefaultConfigurations([{
	overrides: {
		'workbench.startupEditor': 'none',
		'workbench.welcomePage.experimentalOnboarding': false,
		'files.associations': { '*.saengine': 'json' },
	},
}]);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(StartEditor, StartEditorInput.EDITOR_ID, localize('saengineStartEditor', "SAEngine Start")),
	[new SyncDescriptor(StartEditorInput)]
);

function openStart(editorService: IEditorService): Promise<unknown> {
	return editorService.openEditor(StartEditorInput.instance, { pinned: true });
}

/** Shows the start page when SAEngine opens without a project: no folder, or a folder that is not one. */
class StartWindowContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.startWindow';

	constructor(
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IEditorService private readonly editorService: IEditorService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super();
		void this.showIfNoProject();
	}

	private async showIfNoProject(): Promise<void> {
		const folder = this.contextService.getWorkbenchState() === WorkbenchState.EMPTY ? undefined : this.contextService.getWorkspace().folders[0]?.uri;
		if (!folder || !await this.projectService.findProject(folder)) {
			await openStart(this.editorService);
		}
	}
}

registerWorkbenchContribution2(StartWindowContribution.ID, StartWindowContribution, WorkbenchPhase.AfterRestored);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.showStart',
			title: localize2('saengine.showStart', "Show Start Window"),
			category,
			f1: true,
		});
	}

	override run(accessor: ServicesAccessor): Promise<unknown> {
		return openStart(accessor.get(IEditorService));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.new',
			title: localize2('saengine.newProject', "New Project..."),
			category,
			f1: true,
			menu: { id: MenuId.MenubarFileMenu, group: '1_new', order: 0 },
		});
	}

	override run(accessor: ServicesAccessor): Promise<unknown> {
		// The form lives in the start window.
		return openStart(accessor.get(IEditorService));
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.project.open',
			title: localize2('saengine.openProject', "Open Project..."),
			category,
			f1: true,
			menu: { id: MenuId.MenubarFileMenu, group: '2_open', order: 0 },
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(IInstantiationService).createInstance(ProjectOpener).pickAndOpen();
	}
});
