/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { Extensions as ConfigurationExtensions, ConfigurationScope, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { Extensions as OutputExtensions, IOutputChannelRegistry } from '../../../services/output/common/output.js';
import { FemModelEditorInput } from '../browser/femModelEditorInput.js';
import { FEM_OUTPUT_CHANNEL_ID, FEM_PYTHON_SETTING, FemAnalysisRunner } from './femAnalysisRunner.js';

const category = localize2('saengine.category', "SAEngine");

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengine',
	title: localize('saengine.configurationTitle', "SAEngine"),
	type: 'object',
	properties: {
		[FEM_PYTHON_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.MACHINE_OVERRIDABLE,
			markdownDescription: localize('saengine.python.path', "Python 3.12 interpreter with the `saengine` and `opensees-studio` packages installed. When empty, the `.venv` next to the SAEngine sources is used."),
		},
	},
});

Registry.as<IOutputChannelRegistry>(OutputExtensions.OutputChannels).registerChannel({
	id: FEM_OUTPUT_CHANNEL_ID,
	label: localize('femAnalysisOutput', "SAEngine Analysis"),
	log: false,
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.fem.runAnalysis',
			title: localize2('femRunAnalysis', "Run Analysis"),
			category,
			icon: Codicon.play,
			f1: true,
			menu: {
				id: MenuId.EditorTitle,
				group: 'navigation',
				when: ActiveEditorContext.isEqualTo(FemModelEditorInput.EDITOR_ID),
			},
		});
	}

	override async run(accessor: ServicesAccessor, resource?: URI): Promise<void> {
		const editorService = accessor.get(IEditorService);
		const notificationService = accessor.get(INotificationService);
		const runner = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner);

		const model = URI.isUri(resource) ? resource : EditorResourceAccessor.getOriginalUri(editorService.activeEditor);
		if (!model || !model.path.toLowerCase().endsWith('.osmodel')) {
			notificationService.info(localize('femRunAnalysis.noModel', "Open an .osmodel file to run its analysis."));
			return;
		}
		await runner.run(model);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.checkPythonRuntime',
			title: localize2('femCheckRuntime', "Check Python Runtime"),
			category,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).checkRuntime();
	}
});

/**
 * Full rule check of a library file by the Python models, for the visual library editors.
 * Internal: the editors call it by id so they also work where no Python backend exists.
 */
CommandsRegistry.registerCommand('saengine.library.check', async (accessor, kind: 'materials' | 'objects', text: string, materialsText?: string) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).checkLibrary(python, kind, text, materialsText);
});
