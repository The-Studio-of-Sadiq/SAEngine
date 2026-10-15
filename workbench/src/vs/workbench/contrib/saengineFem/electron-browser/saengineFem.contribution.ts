/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { IBuildingIfcRequest, IFemDeriveRequest, IFemSolverService, IStructureGeometry, IStructureScriptResult, LibraryFileKind } from '../../../../platform/saengine/common/femSolver.js';
import { Extensions as ConfigurationExtensions, ConfigurationScope, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceTrustRequestService } from '../../../../platform/workspace/common/workspaceTrust.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { Extensions as OutputExtensions, IOutputChannelRegistry } from '../../../services/output/common/output.js';
import { FemModelEditorInput } from '../browser/femModelEditorInput.js';
import { resultsFolder } from '../browser/femResultsBar.js';
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
CommandsRegistry.registerCommand('saengine.library.check', async (accessor, kind: LibraryFileKind, text: string, materialsText?: string) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).checkLibrary(python, kind, text, materialsText);
});

/**
 * Generates the building model (`bim.json` text) from the floor plan with the Python models.
 * Internal: the Building Model editor calls it by id.
 */
/**
 * The building model as IFC with the Python models (IfcOpenShell), for the 3D view and IFC export.
 * Internal: the Building Model editor calls it by id.
 */
CommandsRegistry.registerCommand('saengine.bim.ifc', async (accessor, request: IBuildingIfcRequest) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).buildingIfc(python, request);
});

/**
 * The analysis model derived from the building model and the project settings (`model.osmodel`
 * text). Internal: the FEM model editor calls it by id.
 */
CommandsRegistry.registerCommand('saengine.fem.derive', async (accessor, request: IFemDeriveRequest) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).deriveFem(python, request);
});

/**
 * The results of the model's last run that can be shown in 3D, and one result ready to draw.
 * Internal: the FEM model editor's results bar calls them by id.
 */
CommandsRegistry.registerCommand('saengine.fem.resultList', async (accessor, model: URI) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).getResultList(python, resultsFolder(model).fsPath, model.fsPath);
});

CommandsRegistry.registerCommand('saengine.fem.resultView', async (accessor, model: URI, key: string, mode?: number) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).getResultView(python, resultsFolder(model).fsPath, model.fsPath, key, mode);
});

CommandsRegistry.registerCommand('saengine.bim.generateFromStructure', async (accessor, structureText: string, bimText?: string) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).generateBuildingFromStructure(python, structureText, bimText);
});

CommandsRegistry.registerCommand('saengine.bim.generate', async (accessor, floorPlanText: string, bimText?: string) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).generateBuilding(python, floorPlanText, bimText);
});

/**
 * Parametric shapes, geometry import and model scripts of the 3D structural modeller.
 * Internal: the modeller calls them by id.
 */
CommandsRegistry.registerCommand('saengine.structure.shapeGeometry', async (accessor, shape: object) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).shapeGeometry(python, shape);
});

CommandsRegistry.registerCommand('saengine.structure.importGeometry', async (accessor, file: URI, options: object, objectsText?: string) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).importGeometry(python, file.fsPath, options, objectsText);
});

CommandsRegistry.registerCommand('saengine.structure.insertGeometry', async (accessor, structureText: string, geometry: IStructureGeometry) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).insertGeometry(python, structureText, geometry);
});

CommandsRegistry.registerCommand('saengine.structure.runScript', async (accessor, structureText: string, script: URI): Promise<IStructureScriptResult> => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const solver = accessor.get(IFemSolverService);
	// A script is code: only run it in a workspace the user trusts.
	const trusted = await accessor.get(IWorkspaceTrustRequestService).requestWorkspaceTrust({
		message: localize('structure.scriptTrust', "Model scripts run Python code from this project. Run them only if you trust its authors."),
	});
	if (!trusted) {
		return { error: localize('structure.scriptUntrusted', "The script was not run: the workspace is not trusted."), output: '' };
	}
	return solver.runStructureScript(python, structureText, script.fsPath);
});
