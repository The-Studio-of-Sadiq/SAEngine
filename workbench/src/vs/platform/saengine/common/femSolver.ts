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
	readonly modes?: readonly { readonly number: number; readonly period: number | null }[];
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
export type LibraryFileKind = 'materials' | 'objects' | 'settings' | 'floorPlan' | 'structure' | 'bim';

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
}

export interface IBuildingIfc {
	/** IFC4 file text. */
	readonly text?: string;
	/** Element id -> IFC GlobalId. */
	readonly ids?: { readonly [elementId: string]: string };
	/** Elements left out, with why. */
	readonly skipped?: readonly string[];
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
}

export interface IFemDerivation {
	/** The `model.osmodel` text. */
	readonly text?: string;
	/** The `pushover.osmodel` text (frames as fiber elements), when the settings ask for pushovers. */
	readonly pushoverText?: string;
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

/**
 * Hosts the SAEngine Python backend (in the shared process): analysis runs through the
 * opensees-studio CLI, and queries through a long-lived `python -m saengine.rpc` server.
 */
export interface IFemSolverService {
	readonly _serviceBrand: undefined;

	readonly onDidRunEvent: Event<IFemRunEventMessage>;
	readonly onDidRunExit: Event<IFemRunExit>;

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
	checkLibrary(python: string, kind: LibraryFileKind, text: string, companionText?: string): Promise<readonly ILibraryProblem[]>;

	/**
	 * The building model generated from the floor plan, keeping the model's own elements
	 * (see `saengine.library.bim`). Problems are returned when either file has errors.
	 */
	generateBuilding(python: string, floorPlanText: string, bimText: string | undefined): Promise<IGeneratedBuilding>;

	/** The building model of a special structure, from its structural model (`structure.json`). */
	generateBuildingFromStructure(python: string, structureText: string, bimText: string | undefined): Promise<IGeneratedBuilding>;

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

	/** Builds the PDF design report of the project (`saengine.report`), by default in `11 Exports`. */
	buildReport(python: string, projectRoot: string, outPdf?: string): Promise<IReportBuild>;

	/**
	 * Everything computed from the soil report (`saengine.soil.soil_report`): per borehole and
	 * for the project, or `{problems}`. Plain JSON, read by the Soil Report editor.
	 */
	soilReport(python: string, soilText: string, settingsText?: string): Promise<object>;

	/** Net allowable bearing pressure of one footing from the soil report. */
	soilAllowableBearing(python: string, request: ISoilBearingRequest): Promise<ISoilBearing>;

	/** The soil report with the boreholes of a CSV or Excel file merged in. */
	importSoil(python: string, path: string, soilText?: string): Promise<ISoilImport>;

	/** Writes the borehole import template (.csv or .xlsx by the extension of `path`). */
	soilTemplate(python: string, path: string): Promise<ISoilTemplate>;

	/** Where the site class and the allowable bearing pressure come from, for Project Settings. */
	soilSources(python: string, soilText: string | undefined, settingsText: string | undefined): Promise<ISoilSources>;

	/**
	 * The design checks of the project's saved substructure (`saengine.substructure.substructure_report`),
	 * plain JSON read by the Substructure editor, or `{problems}`.
	 */
	substructureReport(python: string, projectRoot: string): Promise<object>;

	/** Footings proposed by the sizing assistant for `columns` (default: those without a foundation), or `{problems}`. */
	substructureSize(python: string, projectRoot: string, columns?: readonly string[]): Promise<object>;

	/** The saved substructure with the building model's footings added, nothing written (`{substructure, notes, count}`), or `{problems}`. */
	substructureMigrate(python: string, projectRoot: string): Promise<object>;

	/** Writes the building model's footings into `substructure.json` while it is still the placeholder. */
	substructureEnsure(python: string, projectRoot: string): Promise<ISubstructureMigration>;
}
