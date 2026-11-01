/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../base/common/event.js';
import { createDecorator } from '../../instantiation/common/instantiation.js';

export const FEM_SOLVER_CHANNEL = 'saengineFemSolver';

export const IFemSolverService = createDecorator<IFemSolverService>('saengineFemSolverService');

export interface IFemRunRequest {
	/** Python interpreter with `opensees-studio` and `saengine` installed. */
	readonly python: string;
	/** Absolute path of the `.osmodel` file. */
	readonly project: string;
	readonly caseIds: readonly number[];
	/** Output directory for result files and `manifest.json`. */
	readonly outDir: string;
	/**
	 * Keep the results in `outDir` of the cases whose model and definition did not change
	 * (`--reuse`: the runner removes the rest of the earlier run and runs only the other cases).
	 */
	readonly reuse?: boolean;
}

/**
 * One line of the `python -m opensees_studio.run` progress protocol, plus `stderr` for
 * everything OpenSees itself prints.
 */
export type FemRunEvent =
	| { readonly type: 'log'; readonly message: string }
	| { readonly type: 'case_started'; readonly case_id: number; readonly case_type: string; readonly case_name: string }
	| { readonly type: 'progress'; readonly case_id: number; readonly step: number; readonly total: number }
	| { readonly type: 'case_finished'; readonly case_id: number; readonly case_name: string; readonly result_type: string; readonly files: readonly string[]; readonly early_stop: boolean; readonly warnings: readonly string[] }
	| { readonly type: 'error'; readonly message: string; readonly traceback?: string }
	| { readonly type: 'stderr'; readonly text: string };

export interface IFemRunEventMessage {
	readonly runId: string;
	readonly event: FemRunEvent;
}

export const enum FemRunExitCode {
	Ok = 0,
	AnalysisError = 2,
	InvalidProject = 3,
}

export interface IFemRunExit {
	readonly runId: string;
	/** See {@link FemRunExitCode}; anything else means the solver process died. */
	readonly exitCode: number | null;
	readonly cancelled: boolean;
}

export interface IFemBackendInfo {
	readonly saengine: string;
	readonly openseesStudio: string | null;
	readonly openseespy: string | null;
	readonly python: string;
}

export interface IFemProjectValidation {
	readonly ok: boolean;
	readonly errors: readonly string[];
	readonly notices: readonly string[];
	readonly summary?: {
		readonly name: string;
		readonly units: string;
		readonly ndm: number;
		readonly ndf: number;
		readonly nodes: number;
		readonly elements: number;
		readonly analyses: readonly { readonly id: number; readonly name: string; readonly type: string }[];
	};
}

export type FemTableCell = number | string;

export interface IFemResultTable {
	readonly name: string;
	readonly title: string;
	readonly columns: readonly string[];
	readonly rows: readonly (readonly FemTableCell[])[];
	readonly notes: readonly string[];
}

export interface IFemCaseResults {
	readonly caseId: number;
	readonly caseName: string;
	readonly resultType: string;
	readonly earlyStop: boolean;
	readonly warnings: readonly string[];
	readonly tables: readonly IFemResultTable[];
}

/** A result of a finished run that can be shown in 3D. */
export interface IFemResultEntry {
	/** `case:<id>` or `combination:<number>`. */
	readonly key: string;
	readonly label: string;
	readonly kind: 'static' | 'combination' | 'modal' | 'spectrum' | 'history' | 'pushover';
	readonly modes?: readonly { readonly number: number; readonly period: number | null; readonly ux?: number; readonly uy?: number }[];
	/**
	 * A time history's or a pushover's frames (up to 200 of its steps): the time, or the control
	 * displacement and base shear (the capacity curve); a staged (construction sequence) static
	 * case's stages. `peak`: where it moves most (time history), carries the most (pushover), or
	 * the last stage (the completed structure).
	 */
	readonly frames?: readonly { readonly number: number; readonly time?: number; readonly displacement?: number; readonly shear?: number; readonly stage?: string }[];
	readonly peak?: number;
}

export interface IFemResultList {
	readonly results: readonly IFemResultEntry[];
	/** The model was changed after the run. */
	readonly stale: boolean;
}

/**
 * One result ready to draw (see `saengine.fem.display`): node displacements, support reactions,
 * and per frame element its local axes with displacements and section forces at stations.
 */
export interface IFemResultView {
	readonly label: string;
	readonly kind: 'static' | 'combination' | 'modal' | 'spectrum' | 'history' | 'pushover';
	readonly nodes: readonly (readonly number[])[];
	readonly reactions: readonly (readonly number[])[];
	readonly elements: readonly {
		readonly id: number;
		readonly name: string;
		readonly y: readonly number[];
		readonly z: readonly number[];
		readonly displacements: readonly (readonly number[])[];
		readonly forces?: readonly (readonly number[])[];
	}[];
	/** Shells with their section forces per unit length at the centre (N11 … Q23, local axes). */
	readonly shells?: readonly {
		readonly id: number;
		readonly name: string;
		readonly nodes: readonly number[];
		readonly forces?: readonly number[];
	}[];
	/** Solids (four-node tetrahedra) with their stresses: s11 … s13 (global axes), von Mises. */
	readonly solids?: readonly {
		readonly id: number;
		readonly name: string;
		readonly nodes: readonly number[];
		readonly stress?: readonly number[];
	}[];
}

/** A rule violation in a library file, reported against the entry at `index` (none: the whole file). */
/** Project files the Python models check. */
export type LibraryFileKind = 'materials' | 'objects' | 'settings' | 'floorPlan' | 'structure' | 'bim' | 'reportTemplate' | 'worksheet';

export interface IGeneratedBuilding {
	/** The new `bim.json` text, when it could be generated. */
	readonly text?: string;
	readonly problems?: readonly string[];
}

export interface IBuildingIfcRequest {
	readonly bimText: string;
	readonly objectsText: string;
	readonly materialsText?: string;
	/** Name of the IFC project, e.g. the SAEngine project's name. */
	readonly name: string;
	/** `09 Substructure/substructure.json`: once it is no longer the placeholder, its foundations replace the building model's footings. */
	readonly substructureText?: string;
	/** The project settings: the ground level foundations without a founding level are founded from. */
	readonly settingsText?: string;
	/** `07 MEP/mep.json`: its equipment, plinths, sleeves, openings and shafts are in the model too. */
	readonly mepText?: string;
	/** `05 Floor Plan/architecture.json`: its walls, doors, windows, rooms and finishes are in the model too (ids `arch:<id>`). */
	readonly architectureText?: string;
	/**
	 * The project's folder: when given, the reinforcement cages of its beams and columns are in the
	 * model too (IfcReinforcingBar, ids `rebar:<element>/<n>`), detailed as the drawings detail them.
	 */
	readonly projectRoot?: string;
}

export interface IBuildingIfc {
	/** IFC4 file text. */
	readonly text?: string;
	/** Element id -> IFC GlobalId. */
	readonly ids?: { readonly [elementId: string]: string };
	/** Elements left out, with why. */
	readonly skipped?: readonly string[];
	/** The story each architecture element (`arch:<id>` in {@link ids}) stands on. */
	readonly architectureStories?: { readonly [elementId: string]: string };
	/** Why no IFC could be written (the building model or object types have errors). */
	readonly problems?: readonly string[];
}

export interface IFemDeriveRequest {
	readonly bimText: string;
	readonly objectsText: string;
	readonly materialsText: string;
	readonly settingsText: string;
	/** Folder the model is written to (`08 FEM`): time-history records are read from the project. */
	readonly modelFolder?: string;
	/** The soil report (site class "From the soil report"); when not given, the project's file beside `modelFolder` is read. */
	readonly soilText?: string;
	/** `07 MEP/mep.json` (openings, shafts and equipment loads); when not given, the project's file beside `modelFolder` is read. */
	readonly mepText?: string;
	/** `09 Substructure/substructure.json` (the foundations of soil springs); when not given, the project's file is read. */
	readonly substructureText?: string;
	/** `05 Floor Plan/loads.json` (line and point loads on members); when not given, the project's file is read. */
	readonly loadsText?: string;
	/** `05 Floor Plan/architecture.json` (its walls' and rooms' loads); when not given, the project's file is read. */
	readonly architectureText?: string;
}

export interface IFemDerivation {
	/** The `model.osmodel` text. */
	readonly text?: string;
	/** The `pushover.osmodel` text (frames as fiber elements), when the settings ask for pushovers. */
	readonly pushoverText?: string;
	/** The temperature case's fixed-end forces (`08 FEM/thermal.json`), when the settings have the case T. */
	readonly thermalText?: string;
	/** The soil springs of the column bases (`08 FEM/ssi.json`), when the supports are soil springs. */
	readonly ssiText?: string;
	/** What the model leaves out or simplifies. */
	readonly notes?: readonly string[];
	readonly summary?: { readonly [key: string]: number };
	readonly problems?: readonly string[];
}

type Xyz = readonly [number, number, number];

/**
 * Members, areas and supports to add to a structural model, from a parametric shape or an
 * imported file (see `saengine.library.shapes.Geometry`). Points are [x, y, z] in mm.
 */
export interface IStructureGeometry {
	readonly members: readonly { readonly start: Xyz; readonly end: Xyz; readonly type: string }[];
	readonly areas: readonly { readonly outline: readonly Xyz[]; readonly openings: readonly (readonly Xyz[])[]; readonly type: string }[];
	readonly supports: readonly { readonly at: Xyz; readonly fixity: 'fixed' | 'pinned' }[];
	/** What was left out, and why. */
	readonly notes: readonly string[];
}

/** Geometry, or why there is none (invalid parameters, an unreadable file). */
export type StructureGeometryResult = IStructureGeometry | { readonly problems: readonly string[] };

export interface IStructureEdit {
	/** The new `structure.json` text. */
	readonly text?: string;
	/** Ids of the new members, areas and supports. */
	readonly ids?: readonly string[];
	/** Elements left out because the model already had them. */
	readonly skipped?: number;
	readonly problems?: readonly string[];
}

export interface IStructureScriptResult extends IStructureEdit {
	/** Whether the script cleared the model before adding to it. */
	readonly cleared?: boolean;
	/** Why the script failed (with the line), when it did. */
	readonly error?: string;
	/** What the script printed. */
	readonly output: string;
}

/** The bill of quantities: the new `boq.json` text, or why it could not be measured. */
export interface IBoqComputation {
	readonly text?: string;
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
}

/** The texts the bill of quantities is measured from (`substructureText` and `settingsText` are optional). */
export interface IBoqComputeRequest {
	readonly bimText: string;
	readonly objectsText: string;
	readonly materialsText: string;
	/** `09 Substructure/substructure.json`: once it is no longer the placeholder, its foundations are measured instead of the building model's footings. */
	readonly substructureText?: string;
	/** The project settings: the ground level the foundations' earthwork is dug from. */
	readonly settingsText?: string;
	/** `07 MEP/mep.json`: the equipment plinths, the sleeves and openings counted, the plumbing's tanks, pipes and fixtures. */
	readonly mepText?: string;
	/** The project folder: the plumbing tanks' last designs (`07 MEP/mep.results/tank-designs.json`) give their bars. */
	readonly projectRoot?: string;
	/** `05 Floor Plan/architecture.json`: brickwork, plaster, finishes, doors and windows; when not given, the project's file is read. */
	readonly architectureText?: string;
}

/** The building model's footings moved into a placeholder `substructure.json` (`saengine.substructure.handover`). */
export interface ISubstructureMigration {
	readonly migrated: boolean;
	readonly count: number;
	readonly notes: readonly string[];
	readonly problems?: readonly string[];
}

/** The PDF design report: where it was written, or why it could not be built. */
export interface IReportBuild {
	readonly path?: string;
	readonly pages?: number;
	readonly warnings?: readonly string[];
	readonly problems?: readonly string[];
}

/** What the design report is written as, and which report template it follows. */
export interface IReportBuildOptions {
	/** `pdf` (default) or `docx` (Word). */
	readonly format?: 'pdf' | 'docx';
	/** The report template's id; the one the project settings name when omitted. */
	readonly template?: string;
}

/** A report template the project can print (`saengine.library.report_template.list_templates`). */
export interface IReportTemplateInfo {
	readonly id: string;
	readonly name: string;
	/** Built into SAEngine, or a file of the project (`path`). */
	readonly source: 'builtIn' | 'project';
	readonly path?: string;
}

/** The report templates of a project and the one its settings name. */
export interface IReportTemplates {
	readonly templates: readonly IReportTemplateInfo[];
	readonly current: string;
}

/** A CSV or Excel file's boreholes merged into the soil report, or why it could not be read. */
export interface ISoilImport {
	/** The whole soil report with the file's boreholes in it. */
	readonly text?: string;
	/** What the import did ("BH-1: added (3 layers, …)"). */
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
}

/** The borehole import template written, or why it could not be. */
export interface ISoilTemplate {
	readonly path?: string;
	readonly problems?: readonly string[];
}

/** Net allowable bearing pressure of one footing (`saengine.soil.allowable_bearing`). Lengths in mm. */
export interface ISoilBearingRequest {
	readonly soilText: string;
	readonly settingsText?: string;
	readonly x: number;
	readonly y: number;
	/** Underside of the footing in the project datum. */
	readonly foundingLevel: number;
	readonly b: number;
	readonly l: number;
	/** The project folder, so a code pack stored in the project (02 Project Settings/code-packs) is found. */
	readonly projectRoot?: string;
}

export interface ISoilBearing {
	/** [kPa]; null when the soil report gives none there (see `notes`). */
	readonly qa_kpa?: number | null;
	readonly qa_shear?: number | null;
	readonly qa_settlement?: number | null;
	readonly borehole?: string | null;
	readonly Df?: number;
	readonly method?: string;
	readonly note?: string;
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
}

/** The soil report's site class (`saengine.library.settings.soil_site_class`). */
export interface ISoilSiteClass {
	readonly class: string | null;
	readonly boreholes: number;
	/** "SD (N̄ = 12 over 30 m, BH-2)". */
	readonly label: string;
	readonly note: string;
	readonly borehole?: string;
	readonly problems?: readonly string[];
}

/** Where the site class and the allowable bearing pressure of the project come from. */
export interface ISoilSources {
	readonly site: {
		/** The class the analysis uses. */
		readonly class: string;
		readonly source: 'soilReport' | 'entered';
		readonly entered: string;
		/** "from 1 Soil Report: SD (N̄ = 12 over 30 m, BH-2)" or "SC (entered)". */
		readonly label: string;
		readonly note: string;
	};
	readonly soil: ISoilSiteClass;
	readonly bearing: {
		readonly source: 'override' | 'soilReport' | 'none';
		readonly override?: number | null;
		readonly boreholes: number;
		readonly note: string;
		/** When qa is from the soil report and the Foundation's ground level differs from a borehole's ground. */
		readonly levels?: string | null;
	};
}

export interface ILibraryProblem {
	readonly index: number | null;
	readonly path: string;
	readonly message: string;
}

/** What the backend is working on: its open requests and the oldest one. */
export interface IEngineBusy {
	/** Requests sent and not answered yet. */
	readonly pending: number;
	/** When the oldest of them was sent [ms since the epoch]; undefined when idle. */
	readonly since?: number;
	/** The method of the oldest ("design/report"). */
	readonly method?: string;
}

/**
 * Hosts the SAEngine Python backend (in the shared process): analysis runs through the
 * opensees-studio CLI, and queries through a long-lived `python -m saengine.rpc` server.
 */
export interface IFemSolverService {
	readonly _serviceBrand: undefined;

	readonly onDidRunEvent: Event<IFemRunEventMessage>;
	readonly onDidRunExit: Event<IFemRunExit>;
	/** Fires when a backend request starts or ends (or a restart drops them): the engine watchdog (N-G3). */
	readonly onDidChangeBusy: Event<IEngineBusy>;

	/** Starts an analysis run and returns its id; progress arrives through the events. */
	startRun(request: IFemRunRequest): Promise<string>;
	cancelRun(runId: string): Promise<void>;

	getBackendInfo(python: string): Promise<IFemBackendInfo>;
	validateProject(python: string, project: string): Promise<IFemProjectValidation>;
	getResultTables(python: string, outDir: string, project: string): Promise<readonly IFemCaseResults[]>;
	/** The results of a run that can be shown in 3D. */
	getResultList(python: string, outDir: string, project: string): Promise<IFemResultList>;
	/** One result's deflected shape, force diagrams and reactions (`mode`: modal results). */
	getResultView(python: string, outDir: string, project: string, key: string, mode?: number): Promise<IFemResultView>;
	/** Runs the model rules on a project file; `companionText` is the file it references (materials for objects, objects for the floor plan and bim). */
	checkLibrary(python: string, kind: LibraryFileKind, text: string, companionText?: string, projectRoot?: string): Promise<readonly ILibraryProblem[]>;

	/**
	 * The building model generated from the floor plan, keeping the model's own elements
	 * (see `saengine.library.bim`). Problems are returned when either file has errors.
	 */
	generateBuilding(python: string, floorPlanText: string, bimText: string | undefined, projectRoot?: string): Promise<IGeneratedBuilding>;

	/** The building model of a special structure, from its structural model (`structure.json`). */
	generateBuildingFromStructure(python: string, structureText: string, bimText: string | undefined, projectRoot?: string): Promise<IGeneratedBuilding>;

	/** The building model as IFC (IfcOpenShell), with each element's IFC GlobalId. */
	buildingIfc(python: string, request: IBuildingIfcRequest): Promise<IBuildingIfc>;

	/** The analysis model derived from the building model, with the project settings' loads. */
	deriveFem(python: string, request: IFemDeriveRequest): Promise<IFemDerivation>;

	/** The members, areas and supports of a parametric shape (`saengine.library.shapes`). */
	shapeGeometry(python: string, shape: object): Promise<StructureGeometryResult>;

	/** The geometry of a DXF, IFC or Rhino file, typed with `options` (`saengine.library.importers`). */
	importGeometry(python: string, path: string, options: object, objectsText: string | undefined): Promise<StructureGeometryResult>;

	/** The structural model with `geometry` added, leaving out what it already has. */
	insertGeometry(python: string, structureText: string, geometry: IStructureGeometry): Promise<IStructureEdit>;

	/** Runs a structural model script on the model (in its own Python process). */
	runStructureScript(python: string, structureText: string, scriptPath: string): Promise<IStructureScriptResult>;

	/** The RC member design checks of a run (`saengine.design`); the report is plain JSON. */
	getDesignReport(python: string, outDir: string, project: string): Promise<object>;

	/** The bill of quantities of the building model and the substructure (`saengine.boq`). */
	computeBoq(python: string, request: IBoqComputeRequest): Promise<IBoqComputation>;

	/** Builds the design report of the project (`saengine.report`), PDF or Word, by default in `11 Exports`. */
	buildReport(python: string, projectRoot: string, outPdf?: string, options?: IReportBuildOptions): Promise<IReportBuild>;

	/** The report templates the project can print. */
	reportTemplates(python: string, projectRoot: string): Promise<IReportTemplates>;

	/** Writes a new report template into the project, a copy of `base`: its path, or the problems. */
	createReportTemplate(python: string, projectRoot: string, id: string, base?: string, name?: string): Promise<{ readonly path?: string; readonly existing?: boolean; readonly problems?: readonly string[] }>;

	/**
	 * Everything computed from the soil report (`saengine.soil.soil_report`): per borehole and
	 * for the project, or `{problems}`. Plain JSON, read by the Soil Report editor.
	 */
	soilReport(python: string, soilText: string, settingsText?: string, projectRoot?: string): Promise<object>;

	/** Net allowable bearing pressure of one footing from the soil report. */
	soilAllowableBearing(python: string, request: ISoilBearingRequest): Promise<ISoilBearing>;

	/** The soil report with the boreholes of a CSV or Excel file merged in. */
	importSoil(python: string, path: string, soilText?: string): Promise<ISoilImport>;

	/** Writes the borehole import template (.csv or .xlsx by the extension of `path`). */
	soilTemplate(python: string, path: string): Promise<ISoilTemplate>;

	/** Where the site class and the allowable bearing pressure come from, for Project Settings. */
	soilSources(python: string, soilText: string | undefined, settingsText: string | undefined, projectRoot?: string): Promise<ISoilSources>;

	/**
	 * The design checks of the project's saved substructure (`saengine.substructure.substructure_report`),
	 * plain JSON read by the Substructure editor, or `{problems}`.
	 */
	substructureReport(python: string, projectRoot: string): Promise<object>;

	/** Footings proposed by the sizing assistant for `columns` (default: those without a foundation), with the editor's unsaved `substructureText` when given, or `{problems}`. */
	substructureSize(python: string, projectRoot: string, columns?: readonly string[], substructureText?: string): Promise<object>;

	/** The saved substructure with the building model's footings added, nothing written (`{substructure, notes, count}`), or `{problems}`. */
	substructureMigrate(python: string, projectRoot: string): Promise<object>;

	/** Writes the building model's footings into `substructure.json` while it is still the placeholder. */
	substructureEnsure(python: string, projectRoot: string): Promise<ISubstructureMigration>;

	/**
	 * Run All's foundation step (`saengine.substructure.run.design_foundations`): the footings
	 * moved in from the building model, minimum bars given to foundations without any
	 * (`summary.barsAdded`), and the design checks, as {@link substructureReport}; or `{problems}`.
	 */
	substructureDesign(python: string, projectRoot: string): Promise<object>;

	/**
	 * Stops the backend of `python` (the requests it is working on fail); the next request starts
	 * a new one. Run All's Stop and Restart Engine use it to end a design check that takes too long.
	 */
	restartBackend(python: string): Promise<void>;

	/**
	 * Fixed base against soil springs (`saengine.fem.ssi_compare.compare`): derives and runs the
	 * fixed-base model beside the soil-spring one and compares periods, base shears and drifts;
	 * plain JSON (also written to `08 FEM/ssi-compare.json`), or `{problems}`.
	 */
	ssiCompare(python: string, projectRoot: string): Promise<object>;

	/**
	 * The mesh convergence check of Run All (`saengine.fem.mesh_check`): the beams' gravity end
	 * moments on the project's mesh and on one twice as coarse (also written to
	 * `08 FEM/model.results/mesh-check.json`); `{skipped}` when not needed, or `{problems}`.
	 */
	meshCheck(python: string, projectRoot: string): Promise<object>;

	/** The MEP coordination report of the project (`saengine.mep.mep_report`), plain JSON read by the MEP editor, or `{problems}`. */
	mepReport(python: string, projectRoot: string, mepText?: string): Promise<object>;

	/** The sleeves and openings that would coordinate the clashes (`{openings, notes}`), or `{problems}`. */
	mepSuggestSleeves(python: string, projectRoot: string, mepText?: string, allowance?: number): Promise<object>;

	/** What an MEP IFC model in the project holds (`path` project-relative), or `{problems}`. */
	mepImportIfc(python: string, projectRoot: string, path: string): Promise<object>;

	/** Runs the coordination's clash tests (`tests`: their ids, else the enabled ones) and merges the clashes into its issues (`{coordination, tests, counts, clashes, notes}`), or `{problems}`. */
	mepCoordinate(python: string, projectRoot: string, mepText?: string, tests?: readonly string[]): Promise<object>;

	/** Writes the coordination issues to the BCF 3.0 file `path` (`{path, topics}`), or `{problems}`. */
	mepExportBcf(python: string, projectRoot: string, path: string, mepText?: string, issues?: readonly string[]): Promise<object>;

	/** Merges the topics of the BCF file `path` into the coordination issues (`{coordination, counts}`), or `{problems}`. */
	mepImportBcf(python: string, projectRoot: string, path: string, mepText?: string): Promise<object>;

	/** Checks the models against the coordination's IDS files and merges the failures into its issues (`{coordination, results, counts, notes}`), or `{problems}`. */
	mepCheckIds(python: string, projectRoot: string, mepText?: string): Promise<object>;

	/**
	 * The plumbing report of 7 MEP (`saengine.plumbing.project.full_report`): BNBC 2020 Part 8
	 * sizing, the tanks' RC design (`tankDesigns`), the hydraulics, the sleeves still missing;
	 * plain JSON, or `{problems}`.
	 */
	/** `designs: 'cached'`: the quick first pass, the tank designs not yet cached listed as pending. */
	plumbingReport(python: string, projectRoot: string, mepText?: string, designs?: boolean | 'cached'): Promise<object>;

	/** The tanks SAEngine proposes (`{tanks, notes}`, 7 MEP's `plumbing.tanks` format), or `{problems}`. */
	plumbingSizeTanks(python: string, projectRoot: string, mepText?: string): Promise<object>;

	/** The sleeves the risers and stacks still need (`{openings, notes}`), or `{problems}`. */
	plumbingSleeves(python: string, projectRoot: string, mepText?: string): Promise<object>;

	/** BNBC 2020 Part 8 Table 8.5.1's occupancies (`{occupancies}`). */
	plumbingOccupancies(python: string): Promise<object>;

	/**
	 * A method of 7 MEP's HVAC or electrical backend (see {@link MepServiceMethod}) with the
	 * project folder and the editor's unsaved `07 MEP/mep.json`; plain JSON, or `{problems}`.
	 */
	mepService(python: string, method: MepServiceMethod, params: IMepServiceParams): Promise<object>;

	/**
	 * A method of the project archive or the version history (see {@link ProjectPlatformMethod});
	 * plain JSON, or `{ok: false, code, message, problems}` when the backend refuses it.
	 */
	projectPlatform(python: string, method: ProjectPlatformMethod, params: object): Promise<object>;

	/**
	 * Opens a DXF drawing in LibreCAD (the bundled copy, else an installed one), started directly
	 * with the drawing as its only argument (no shell). `program: null` when there is none: the
	 * caller then hands the file to the system's own DXF program.
	 */
	openInCad(request: ICadOpenRequest): Promise<ICadOpenResult>;

	/**
	 * The LibreCAD {@link openInCad} would start (`configured`: the `saengine.cad.program`
	 * setting), or undefined: the state of the setup's *CAD editor* component.
	 */
	cadProgram(configured?: string): Promise<ICadProgram | undefined>;

	/**
	 * Runs a SAEngine setup the user chose, to add optional components: only when the file's
	 * SHA-256 equals `request.sha256`, with `/COMPONENTS=<components>` (Inno Setup installs those and
	 * the core, and removes the components left out), started directly (no shell) and left running.
	 * Nothing is downloaded.
	 */
	runSetup(request: ISetupRunRequest): Promise<ISetupRunResult>;

	/**
	 * A method of the design mode or the site map (see {@link EngineMethod}); the backend's
	 * answer as it is (plain JSON).
	 */
	engine(python: string, method: EngineMethod, params: object): Promise<unknown>;

	/**
	 * Opens a GeoPackage or GeoJSON file in QGIS: `request.program` (the machine setting) when
	 * it names an existing program, else the QGIS the backend finds installed. Started directly
	 * (no shell); a `.bat` launcher through `%ComSpec%` with the line the backend quotes.
	 * `program: null` when there is no QGIS.
	 */
	openInQgis(python: string, request: IQgisOpenRequest): Promise<IQgisOpenResult>;
}

/**
 * The design mode (`saengine.design`) and the site map (`saengine.gis.site`):
 * `design/required` `{outDir, projectPath, options?}`, `design/proposal` `{outDir, projectPath,
 * options?}`, `design/applyProposal` `{objectsText, bimText?, proposal, floorPlanText?,
 * substructureText?}`, `soil/location` `{soilText, bimText?, settingsText?}`, `soil/plotCheck`
 * `{soilText, floorPlanText, objectsText?}` (the floor plan against the plot), `soil/gisExport`
 * `{projectRoot, format, outPath}`, `soil/gisImport` `{path, soilText?}` and
 * `soil/qgisProgram` `{}` (a launcher path or null); the earthquake design from the response
 * spectrum `fem/seismicDesign` `{outDir, projectPath}` (null when the project designs from the
 * static cases) and the P-Delta drift amplification `fem/secondOrder` `{outDir, projectPath}`;
 * the structural drawings of `11 Exports/Drawings` (`saengine.pipeline.drawings`):
 * `drawings/generate` `{projectRoot, sheets?, size?, designReportText?}` (in a worker thread),
 * `drawings/list` `{projectRoot}`, `drawings/progress` `{projectRoot}`, `drawings/issue` (an issue of the set) and
 * `drawings/dwg` `{projectRoot, sheets?}` (the sheets as DWG); a new project from an
 * ETABS, STAAD.Pro or SAP2000 text file `import/structural` `{path, destParent, name?, overwrite?}`
 * (`{root, name, format, report, problems, files}` or `{error, problems}`; in a worker thread), the
 * project as an ETABS text model `export/e2k` `{projectRoot, outPath?, units?, lateral?}` (`{path,
 * reportPath, report}` or `{error}`; in a worker thread) and
 * the standard steel section table `library/steelSections` `{}`; a new building generated from its
 * grids and storeys `library/generateBuilding` `{spec, destParent, name?, overwrite?, site?}` (`{root, name,
 * notes, summary, settingsPatch, files}` or `{error}`; in a worker thread); the bill of quantities
 * priced by the schedule of rates with its embodied carbon `boq/cost` `{boqText, ratesText?,
 * carbonText?}`, the texts the project's rates and carbon factors start from `boq/templates` `{}`,
 * and the bill, its costing and carbon written to Excel `boq/exportXlsx` `{path, boqText,
 * ratesText?, carbonText?, title?}` (in a worker thread).
 */
export type EngineMethod =
	| 'design/required' | 'design/proposal' | 'design/applyProposal'
	| 'fem/seismicDesign' | 'fem/secondOrder'
	| 'fem/storyResponse' | 'fem/memberForces' | 'fem/columnInteraction' | 'fem/exportXlsx'
	| 'fem/tableIndex' | 'fem/table' | 'fem/exportTables' | 'fem/exportProgress' | 'fem/exportCancel'
	| 'soil/location' | 'soil/plotCheck' | 'soil/gisExport' | 'soil/gisImport' | 'soil/qgisProgram'
	| 'drawings/generate' | 'drawings/list' | 'drawings/progress' | 'drawings/issue' | 'drawings/dwg'
	| 'import/structural' | 'export/e2k' | 'library/steelSections' | 'library/generateBuilding'
	// The Revit link's exchange file (`saengine.exporters.revit_link`, in a worker thread):
	// `revit/export` `{projectRoot, outPath?}`, `revit/preview` `{projectRoot, path}` and
	// `revit/apply` `{projectRoot, path, changes}`.
	| 'revit/export' | 'revit/preview' | 'revit/apply'
	| 'section/analyse' | 'architecture/importIfc' | 'architecture/inspectDrawing' | 'architecture/importDrawing' | 'architecture/check' | 'architecture/ramps'
	| 'boq/cost' | 'boq/templates' | 'boq/exportXlsx'
	// Calculation worksheets (`saengine.report.worksheets`): `worksheets/kinds` `{}`,
	// `worksheets/calculate` `{kind, inputs, projectRoot?}`, `worksheets/list` `{projectRoot}`,
	// `worksheets/create` `{projectRoot, kind, id, title?}`.
	| 'worksheets/kinds' | 'worksheets/calculate' | 'worksheets/list' | 'worksheets/create'
	// Strut-and-tie models of D-regions (`saengine.design.stm_model`): `design/strutAndTie`
	// `{model, projectPath?}` and `design/strutAndTieTemplate` `{template, parameters?}`.
	| 'design/strutAndTie' | 'design/strutAndTieTemplate';

export interface IQgisOpenRequest {
	/** Absolute path of the `.gpkg`, `.geojson` or `.json` file. */
	readonly path: string;
	/** A QGIS launcher to prefer (the `saengine.qgis.program` setting); used only when it exists. */
	readonly program?: string;
	/** Only find the program and say what would be started; nothing is started. */
	readonly dryRun?: boolean;
}

export interface IQgisOpenResult {
	readonly ok: boolean;
	/** The program started (or that would be), or null when no QGIS was found. */
	readonly program: string | null;
	/** The arguments it is started with. */
	readonly args: readonly string[];
	readonly pid?: number;
	readonly problems?: readonly string[];
}

/**
 * The project archive (`.civil`, `saengine.project.archive`) and the version history
 * (`saengine.project.versions`): `project/exportArchive` `{projectRoot, outPath, includeResults?,
 * includeVersions?, includeExports?, note?, saengineVersion?}`, `project/inspectArchive` `{path,
 * currentVersion?, verify?}`, `project/importArchive` `{path, destParent, name?, overwrite?,
 * currentVersion?, migrate?}`, `versions/status` `{projectRoot}`, `versions/list` `{projectRoot,
 * limit?}`, `versions/save` `{projectRoot, message, author?, issued?, label?}`, `versions/diff`
 * `{projectRoot, fromVersion?, toVersion?}` (not `from`: the backend sees params as Python names), `versions/restore` `{projectRoot, version, parts?, author?, commit?}`
 * and `versions/markIssued` `{projectRoot, version, label, author?}`.
 */
export type ProjectPlatformMethod =
	| 'project/exportArchive' | 'project/inspectArchive' | 'project/importArchive'
	| 'versions/status' | 'versions/list' | 'versions/save' | 'versions/diff' | 'versions/restore' | 'versions/markIssued'
	// The office copy of the versions (`saengine.project.share`): `share/status` `{projectRoot, user?, fetch?}`,
	// `share/connect` `{projectRoot, location, author?}`, `share/disconnect` `{projectRoot}`, `share/join`
	// `{location, target}`, `share/sync` `{projectRoot, author?, resolutions?, user?}`, `share/lock`
	// `{projectRoot, part, user?, note?}`, `share/unlock` `{projectRoot, part, user?, force?}`,
	// `share/heartbeat` `{projectRoot, user?, part?, leaving?}`.
	| 'share/status' | 'share/connect' | 'share/disconnect' | 'share/join' | 'share/sync' | 'share/lock' | 'share/unlock' | 'share/heartbeat'
	// Code packs (`saengine.codes`): `codes/list` `{root?}`, `codes/show` `{id, root?}`, `codes/new`
	// `{id, name, extends, scope?, dest?, root?}`, `codes/install` `{path, scope, root?}`,
	// `codes/validate` `{path, root?}`, `codes/trust` `{id, trusted, root?}`.
	| 'codes/list' | 'codes/show' | 'codes/new' | 'codes/install' | 'codes/validate' | 'codes/trust' | 'codes/remove' | 'codes/templates' | 'codes/checkTemplate' | 'codes/codedGeometry'
	// A DWG drawing as DXF (`saengine.library.dwg`, GNU LibreDWG's dwg2dxf as a separate program):
	// `cad/convertDwg` `{path, cache?}` -> `{ok, dxf, warnings, cached}` or `{ok: false, code, message}`.
	| 'cad/convertDwg'
	// One page of an architect's PDF as DXF with its lines for object snaps (`saengine.library.pdf_underlay`):
	// `cad/convertPdf` `{path, page?, cache?}` -> `{ok, dxf, page, pages, vector, size, segments, warnings, cached}`.
	| 'cad/convertPdf'
	// The model workbook (`saengine.library.workbook`): `workbook/export` `{outPath, floorPlanText, objectsText?,
	// loadsText?}` -> `{ok, path, sheets}`; `workbook/import` `{path, floorPlanText, objectsText?, loadsText?}` ->
	// `{ok, problems, diff, texts, changed}`.
	| 'workbook/export' | 'workbook/import'
	// The setup's optional components the backend runs (`saengine.rpc.handlers.installer_components`):
	// `components/list` `{}` -> `{energyplus, libredwg}`, each `{state, path?}`.
	| 'components/list'
	// The AI assistant's code Q&A (`saengine.ai.knowledge`): `ai/searchCode` `{query, projectRoot?, limit?, docs?}`
	// -> `{pack, query, found, passages: [{id, kind, title, text, citations, score}], note}`.
	| 'ai/searchCode';

export interface ICadOpenRequest {
	/** Absolute path of the `.dxf` file. */
	readonly path: string;
	/** A CAD program to prefer (the `saengine.cad.program` setting); used only when it exists. */
	readonly program?: string;
	/** Only find the program and say what would be started; nothing is started. */
	readonly dryRun?: boolean;
}

export interface ICadOpenResult {
	readonly ok: boolean;
	/** The program started (or that would be), or null when none was found. */
	readonly program: string | null;
	/** Its arguments: the drawing's path. */
	readonly args: readonly string[];
	/** Where the program came from: the setting, the bundled copy or an installed one. */
	readonly source?: ICadProgram['source'];
	/** The process id when started. */
	readonly pid?: number;
	readonly problems?: readonly string[];
}

export interface ICadProgram {
	readonly program: string;
	/** The `saengine.cad.program` setting, the setup's copy (`resources/librecad`) or an installed LibreCAD. */
	readonly source: 'setting' | 'bundled' | 'installed';
}

/** The optional components of the SAEngine setup (`[Components]` of `workbench/build/win32/code.iss`). */
export const SETUP_COMPONENTS = ['energyplus', 'librecad', 'libredwg', 'ai', 'git', 'collaboration'] as const;
export type SetupComponent = typeof SETUP_COMPONENTS[number];

export interface ISetupRunRequest {
	/** Absolute path of the setup (`.exe`). */
	readonly setup: string;
	/** The lower-case hex SHA-256 the setup must have (from the release's `.sha256`). */
	readonly sha256: string;
	/** Every optional component the install should have afterwards. */
	readonly components: readonly SetupComponent[];
	/**
	 * The publisher whose valid Authenticode signature the setup must carry (product.json's
	 * `saengineSigning.publisher`); without it (signing not set up yet) only the SHA-256 is checked.
	 */
	readonly publisher?: string;
}

export interface ISetupRunResult {
	readonly ok: boolean;
	readonly pid?: number;
	readonly problems?: readonly string[];
}

/**
 * The HVAC and electrical methods of 7 MEP's backend (`saengine.rpc.server`):
 * `mep/hvacReport` the cooling loads (EnergyPlus's cached run of this input, else the estimate;
 * EnergyPlus is not started) with the air side under `air`; `mep/hvacLoads` the same after
 * running EnergyPlus version 26.2.0 (a separate process, up to half a minute);
 * `mep/hvacCancelLoads` stops it; `mep/hvacProposePlant`, `mep/hvacDuctOpenings`; the tables
 * `mep/hvacTables` and `mep/hvacConstructions`; `mep/electricalReport`,
 * `mep/electricalProposeEquipment`, `mep/electricalOpenings` and the table `mep/electricalUses`;
 * `mep/fireReport` (BNBC 2020 Part 4), `mep/fireProposals` and `mep/fireOpenings`.
 */
export type MepServiceMethod =
	| 'mep/hvacReport' | 'mep/hvacLoads' | 'mep/hvacCancelLoads' | 'mep/hvacProposePlant' | 'mep/hvacDuctOpenings' | 'mep/hvacTables' | 'mep/hvacConstructions'
	| 'mep/electricalReport' | 'mep/electricalProposeEquipment' | 'mep/electricalOpenings' | 'mep/electricalUses'
	| 'mep/fireReport' | 'mep/fireProposals' | 'mep/fireOpenings';

/** What a {@link MepServiceMethod} is asked about (none for the tables and the cancel). */
export interface IMepServiceParams {
	readonly projectRoot?: string;
	readonly mepText?: string;
}
