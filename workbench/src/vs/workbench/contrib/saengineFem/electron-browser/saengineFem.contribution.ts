/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { isAbsolute } from '../../../../base/common/path.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { IModelService } from '../../../../editor/common/services/model.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { IBoqComputeRequest, IBuildingIfcRequest, IFemDeriveRequest, IFemSolverService, IMepServiceParams, ISoilBearingRequest, IStructureGeometry, IStructureScriptResult, LibraryFileKind, MepServiceMethod } from '../../../../platform/saengine/common/femSolver.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions, ConfigurationScope, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceTrustRequestService } from '../../../../platform/workspace/common/workspaceTrust.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { Extensions as OutputExtensions, IOutputChannelRegistry } from '../../../services/output/common/output.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { resultsFolder } from '../browser/femResultsBar.js';
import { MAP_TILE_ATTRIBUTION_SETTING, MAP_TILE_URL_SETTING, QGIS_PROGRAM_SETTING } from '../../saengineSoil/browser/soilDocument.js';
import { OSM_TILE_URL } from '../../saengineSoil/browser/soilMap.js';
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
			// A program SAEngine starts: only from this machine's settings, never from a project's
			// .vscode/settings.json (a received project could name any program there).
			scope: ConfigurationScope.MACHINE,
			restricted: true,
			markdownDescription: localize('saengine.python.path', "Python 3.12 interpreter with the `saengine` and `opensees-studio` packages installed. When empty, an installed SAEngine uses its bundled Python (`resources/python`), and SAEngine run from the sources uses the `.venv` next to them."),
		},
		// The map's tiles are fetched from this address: only from this machine's settings, so a
		// received project cannot send the site's position to a server of its choosing.
		[MAP_TILE_URL_SETTING]: {
			type: 'string',
			default: OSM_TILE_URL,
			scope: ConfigurationScope.MACHINE,
			restricted: true,
			markdownDescription: localize('saengine.map.tileUrl', "Address of the map tiles of 1 Soil Report's site map, with `{z}`, `{x}` and `{y}` (for example `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, the default). OpenStreetMap's tiles are © OpenStreetMap contributors (ODbL) and are for light use under its [tile usage policy](https://operations.osmfoundation.org/policies/tiles/): SAEngine shows the attribution, identifies itself and lets the tiles be cached. For heavy use, an office-wide installation or offline work, use your own tile server or a commercial provider and set its address and attribution here. Without a connection the map shows the coordinates and the building outline only."),
		},
		[MAP_TILE_ATTRIBUTION_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.MACHINE,
			markdownDescription: localize('saengine.map.tileAttribution', "The attribution shown on the site map for the tiles of `#saengine.map.tileUrl#` when it is not OpenStreetMap (OpenStreetMap's own attribution is always shown for its tiles)."),
		},
		[QGIS_PROGRAM_SETTING]: {
			type: 'string',
			default: '',
			// A program SAEngine starts: only from this machine's settings.
			scope: ConfigurationScope.MACHINE,
			restricted: true,
			markdownDescription: localize('saengine.qgis.program', "The QGIS that **Open in QGIS** starts (the full path of `qgis-bin.exe`, `qgis-ltr-bin.exe` or an OSGeo4W `qgis.bat`). When empty, an installed QGIS is looked for (the Windows uninstall entries, Program Files and OSGeo4W). QGIS is not part of SAEngine."),
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
	const solver = accessor.get(IFemSolverService);
	// The foundations are 9 Substructure's (once it is no longer the placeholder): the editors
	// ask for the building model's IFC, and get the project's foundations with it.
	const texts = projectTexts(accessor);
	const substructureText = request.substructureText ?? await texts('substructure');
	const settingsText = request.settingsText ?? await texts('settings');
	// The coordination model of 7 MEP (equipment, plinths, sleeves, shafts) is in the 3D view too.
	const mepText = request.mepText ?? await texts('mep');
	return solver.buildingIfc(python, { ...request, substructureText, settingsText, mepText });
});

/**
 * Reads the open project's part files by part id, with their unsaved edits (undefined without a
 * project or file). Take it from the accessor before the first await.
 */
function projectTexts(accessor: ServicesAccessor): (part: string) => Promise<string | undefined> {
	const root = accessor.get(ISaengineProjectService).project?.root;
	const fileService = accessor.get(IFileService);
	const modelService = accessor.get(IModelService);
	return async id => {
		const part = partById(id);
		if (!root || !part?.mainFile) {
			return undefined;
		}
		const resource = joinPath(root, part.folder, part.mainFile);
		const model = modelService.getModel(resource);
		if (model) {
			return model.getValue();
		}
		try {
			return (await fileService.readFile(resource)).value.toString();
		} catch {
			return undefined;
		}
	};
}

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

/** The RC member design checks of the model's last run. Internal: the results bar calls it by id. */
CommandsRegistry.registerCommand('saengine.fem.design', async (accessor, model: URI) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).getDesignReport(python, resultsFolder(model).fsPath, model.fsPath);
});

/** The bill of quantities of the building model. Internal: the BOQ editor calls it by id. */
CommandsRegistry.registerCommand('saengine.boq.compute', async (accessor, args: IBoqComputeRequest) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).computeBoq(python, args);
});

/**
 * The soil report's results (`saengine.soil.soil_report`, returned as it is: the editor reads
 * it). Internal: the Soil Report editor calls it by id.
 */
CommandsRegistry.registerCommand('saengine.soil.compute', async (accessor, args: { soilText: string; settingsText?: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).soilReport(python, args.soilText, args.settingsText);
});

/**
 * Boreholes of a CSV or Excel file merged into the soil report: `{text, problems?}` with the
 * import's remarks (beyond the boreholes added) as `problems`, or `{problems}` when nothing
 * was imported. Internal: the Soil Report editor calls it by id.
 */
CommandsRegistry.registerCommand('saengine.soil.import', async (accessor, args: { path: string; soilText?: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const result = await accessor.get(IFemSolverService).importSoil(python, args.path, args.soilText);
	if (!result.text) {
		return { problems: result.problems ?? [] };
	}
	const remarks = (result.notes ?? []).filter(note => !/: added \(/.test(note));
	return { text: result.text, notes: result.notes ?? [], problems: remarks.length ? remarks : undefined };
});

/** Writes the borehole import template. Internal: the Soil Report editor calls it by id. */
CommandsRegistry.registerCommand('saengine.soil.template', async (accessor, args: { path: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).soilTemplate(python, args.path);
});

/** Net allowable bearing pressure of one footing from the soil report (lengths in mm). */
CommandsRegistry.registerCommand('saengine.soil.allowableBearing', async (accessor, request: ISoilBearingRequest) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).soilAllowableBearing(python, request);
});

/**
 * Where the site class and the allowable bearing pressure come from (the soil report or the
 * settings). Internal: the Project Settings editor calls it by id.
 */
CommandsRegistry.registerCommand('saengine.soil.sources', async (accessor, args: { soilText?: string; settingsText?: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).soilSources(python, args.soilText, args.settingsText);
});

/** The PDF design report of the project. Internal: the report command calls it by id. */
CommandsRegistry.registerCommand('saengine.report.build', async (accessor, args: { projectRoot: string; outPdf?: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).buildReport(python, args.projectRoot, args.outPdf);
});

/** What the Substructure editor asks the backend: the project folder (its saved files are read), and the columns to size. */
interface ISubstructureCommandArgs {
	readonly projectRoot: string;
	readonly columns?: readonly string[];
}

/** A backend answer of only `{problems}` becomes an error the caller shows. */
function orThrow<T extends object>(result: T): T {
	const { problems, foundations, substructure } = result as { problems?: unknown; foundations?: unknown; substructure?: unknown };
	if (Array.isArray(problems) && problems.length && foundations === undefined && substructure === undefined) {
		throw new Error(problems.map(String).join(' '));
	}
	return result;
}

/**
 * Part 9 Substructure: the design checks of the saved substructure, the sizing assistant, the
 * building model's footings as foundations (nothing written), and the one-time move of those
 * footings into a placeholder `substructure.json`. Internal: the Substructure editor and Run All
 * call them by id.
 */
CommandsRegistry.registerCommand('saengine.substructure.report', async (accessor, args: ISubstructureCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return orThrow(await accessor.get(IFemSolverService).substructureReport(python, args.projectRoot));
});

CommandsRegistry.registerCommand('saengine.substructure.size', async (accessor, args: ISubstructureCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return orThrow(await accessor.get(IFemSolverService).substructureSize(python, args.projectRoot, args.columns));
});

CommandsRegistry.registerCommand('saengine.substructure.migrate', async (accessor, args: ISubstructureCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return orThrow(await accessor.get(IFemSolverService).substructureMigrate(python, args.projectRoot));
});

CommandsRegistry.registerCommand('saengine.substructure.ensureMigrated', async (accessor, args: ISubstructureCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).substructureEnsure(python, args.projectRoot);
});

/** A backend answer of only `{problems}` (no report) becomes an error the caller shows. */
function problemsOrResult<T extends object>(result: T, keys: readonly string[]): T {
	const record = result as { readonly [key: string]: unknown };
	const problems = record.problems;
	if (Array.isArray(problems) && problems.length && keys.every(key => record[key] === undefined)) {
		throw new Error(problems.map(String).join(' '));
	}
	return result;
}

/**
 * Fixed base against soil springs: derives and runs the fixed-base model beside the soil-spring
 * model (`08 FEM/model-fixed.osmodel`, whose run the foundation design reads) and compares them.
 * Internal: the FEM results bar and Run All call it by id.
 */
CommandsRegistry.registerCommand('saengine.fem.ssiCompare', async (accessor, args: { readonly projectRoot: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).ssiCompare(python, args.projectRoot), ['periods']);
});

/** What the MEP editor asks the backend: the project folder (its saved files are read) and the editor's text of `mep.json`. */
interface IMepCommandArgs {
	readonly projectRoot: string;
	readonly mepText?: string;
	readonly allowance?: number;
	readonly path?: string;
}

/**
 * Part 7 MEP: the coordination report (equipment loads, opening checks, clashes), the sleeves
 * that would coordinate the clashes, and what an MEP IFC model holds. Internal: the MEP editor
 * and Run All call them by id.
 */
CommandsRegistry.registerCommand('saengine.mep.report', async (accessor, args: IMepCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).mepReport(python, args.projectRoot, args.mepText), ['equipment', 'openings', 'clashes']);
});

CommandsRegistry.registerCommand('saengine.mep.suggestSleeves', async (accessor, args: IMepCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).mepSuggestSleeves(python, args.projectRoot, args.mepText, args.allowance), ['openings']);
});

CommandsRegistry.registerCommand('saengine.mep.importIfc', async (accessor, args: IMepCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).mepImportIfc(python, args.projectRoot, args.path ?? ''), ['path', 'elements']);
});

/**
 * Part 7 plumbing (BNBC 2020 Part 8): the report (sizing, the tanks' design, the hydraulics, the
 * missing sleeves), the tanks and sleeves SAEngine proposes, and Table 8.5.1's occupancies.
 * Internal: the MEP editor's Plumbing view and Run All call them by id.
 */
CommandsRegistry.registerCommand('saengine.plumbing.report', async (accessor, args: IMepCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).plumbingReport(python, args.projectRoot, args.mepText), ['demand', 'checks']);
});

CommandsRegistry.registerCommand('saengine.plumbing.sizeTanks', async (accessor, args: IMepCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).plumbingSizeTanks(python, args.projectRoot, args.mepText), ['tanks']);
});

CommandsRegistry.registerCommand('saengine.plumbing.sleeves', async (accessor, args: IMepCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return problemsOrResult(await accessor.get(IFemSolverService).plumbingSleeves(python, args.projectRoot, args.mepText), ['openings']);
});

CommandsRegistry.registerCommand('saengine.plumbing.occupancies', async accessor => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).plumbingOccupancies(python);
});

/**
 * Part 7 HVAC (BNBC 2020 Part 8 Chapter 2) and electrical (Chapter 1): the reports, the plant,
 * equipment and openings SAEngine proposes, and their tables. Internal: the MEP editor's HVAC
 * and Electrical views and Run All call them by id. `saengine.hvac.report` never starts
 * EnergyPlus (it is asked after every edit); `saengine.hvac.loads` runs it (a separate process
 * the backend runs in a worker thread) and stops it when its token is cancelled.
 */
function registerMepService(id: string, method: MepServiceMethod, keys: readonly string[]): void {
	CommandsRegistry.registerCommand(id, async (accessor, args?: IMepCommandArgs) => {
		const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
		const params: IMepServiceParams = args ? { projectRoot: args.projectRoot, mepText: args.mepText } : {};
		return problemsOrResult(await accessor.get(IFemSolverService).mepService(python, method, params), keys);
	});
}

registerMepService('saengine.hvac.report', 'mep/hvacReport', ['zones', 'air']);
registerMepService('saengine.hvac.proposePlant', 'mep/hvacProposePlant', ['plant']);
registerMepService('saengine.hvac.ductOpenings', 'mep/hvacDuctOpenings', ['openings']);
registerMepService('saengine.hvac.tables', 'mep/hvacTables', ['cities']);
registerMepService('saengine.hvac.constructions', 'mep/hvacConstructions', ['wall']);
registerMepService('saengine.electrical.report', 'mep/electricalReport', ['demand', 'checks']);
registerMepService('saengine.electrical.proposeEquipment', 'mep/electricalProposeEquipment', ['equipment']);
registerMepService('saengine.electrical.openings', 'mep/electricalOpenings', ['openings']);
registerMepService('saengine.electrical.uses', 'mep/electricalUses', ['uses']);

CommandsRegistry.registerCommand('saengine.hvac.loads', async (accessor, args: IMepCommandArgs, token?: CancellationToken) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const solver = accessor.get(IFemSolverService);
	const cancel = token?.onCancellationRequested(() => {
		solver.mepService(python, 'mep/hvacCancelLoads', {}).catch(() => { /* the run ends anyway */ });
	});
	try {
		return problemsOrResult(await solver.mepService(python, 'mep/hvacLoads', { projectRoot: args.projectRoot, mepText: args.mepText }), ['zones', 'air']);
	} finally {
		cancel?.dispose();
	}
});

/**
 * Design mode (`saengine.design`): the steel every element requires, the bars SAEngine
 * proposes per object type and foundation, and the part files with a proposal applied.
 * Internal: the Properties panel, the Design Reinforcement page and Run All call them by id
 * (femDesign.ts). The first two design every member again (up to a minute or two): the backend
 * runs them in worker threads, and keeps the required steel beside the results while the
 * project does not change.
 */
interface IDesignCommandArgs {
	readonly outDir: string;
	readonly projectPath: string;
	readonly mode?: 'byType' | 'splitTypes';
	readonly diameters?: readonly number[];
	readonly maxSizes?: number;
}

CommandsRegistry.registerCommand('saengine.design.required', async (accessor, args: IDesignCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'design/required', { outDir: args.outDir, projectPath: args.projectPath });
});

/**
 * The earthquake design from the response spectrum of a run (scaling to 85 % of the static base
 * shear, orthogonal rule, accidental torsion, drifts; null when the project designs from the
 * static cases) and what the P-Delta analysis changed. Internal: the results bar calls them by
 * id (femSeismicDesign.ts) before the design checks.
 */
CommandsRegistry.registerCommand('saengine.fem.seismicDesign', async (accessor, args: IDesignCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'fem/seismicDesign', { outDir: args.outDir, projectPath: args.projectPath });
});

CommandsRegistry.registerCommand('saengine.fem.secondOrder', async (accessor, args: IDesignCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'fem/secondOrder', { outDir: args.outDir, projectPath: args.projectPath });
});

CommandsRegistry.registerCommand('saengine.design.proposal', async (accessor, args: IDesignCommandArgs) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const options = {
		mode: args.mode ?? 'byType',
		...(args.diameters ? { diameters: args.diameters } : {}),
		...(args.maxSizes !== undefined ? { maxSizes: args.maxSizes } : {}),
	};
	return accessor.get(IFemSolverService).engine(python, 'design/proposal', { outDir: args.outDir, projectPath: args.projectPath, options });
});

CommandsRegistry.registerCommand('saengine.design.apply', async (accessor, args: { readonly objectsText: string; readonly bimText?: string | null; readonly floorPlanText?: string; readonly substructureText?: string; readonly proposal: object }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'design/applyProposal', {
		objectsText: args.objectsText,
		// A project without a building model: the backend applies to an empty one.
		bimText: args.bimText ?? null,
		floorPlanText: args.floorPlanText,
		substructureText: args.substructureText,
		proposal: args.proposal,
	});
});

/**
 * 1 Soil Report's site map (`saengine.gis.site`): where the site, the boreholes and the
 * building are in WGS 84 with the nearest BNBC town, the GeoJSON/GeoPackage exchange with
 * QGIS, and Open in QGIS (when it is installed; QGIS is not bundled). Internal: the Soil Report
 * editor calls them by id.
 */
CommandsRegistry.registerCommand('saengine.soil.location', async (accessor, args: { readonly soilText: string; readonly bimText?: string; readonly settingsText?: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'soil/location', { soilText: args.soilText, bimText: args.bimText, settingsText: args.settingsText });
});

CommandsRegistry.registerCommand('saengine.soil.gisExport', async (accessor, args: { readonly projectRoot: string; readonly format: 'geojson' | 'gpkg'; readonly outPath: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'soil/gisExport', { projectRoot: args.projectRoot, format: args.format, outPath: args.outPath });
});

CommandsRegistry.registerCommand('saengine.soil.gisImport', async (accessor, args: { readonly path: string; readonly soilText?: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).engine(python, 'soil/gisImport', { path: args.path, soilText: args.soilText });
});

/** The QGIS Open in QGIS would start (the machine setting, else an installed one), or null. */
CommandsRegistry.registerCommand('saengine.soil.qgisProgram', async accessor => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const configured = accessor.get(IConfigurationService).getValue<string>(QGIS_PROGRAM_SETTING)?.trim();
	const solver = accessor.get(IFemSolverService);
	// The program is checked again where it is started (openInQgis): it must exist.
	if (configured && isAbsolute(configured) && await accessor.get(IFileService).exists(URI.file(configured))) {
		return configured;
	}
	const found = await solver.engine(python, 'soil/qgisProgram', {});
	return typeof found === 'string' ? found : null;
});

CommandsRegistry.registerCommand('saengine.soil.openInQgis', async (accessor, args: { readonly path: string }) => {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const program = accessor.get(IConfigurationService).getValue<string>(QGIS_PROGRAM_SETTING);
	return accessor.get(IFemSolverService).openInQgis(python, { path: args.path, program });
});
