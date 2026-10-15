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

/** A rule violation in a library file, reported against the entry at `index` (none: the whole file). */
/** Project files the Python models check. */
export type LibraryFileKind = 'materials' | 'objects' | 'settings' | 'floorPlan' | 'bim';

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
}

export interface IFemDerivation {
	/** The `model.osmodel` text. */
	readonly text?: string;
	/** What the model leaves out or simplifies. */
	readonly notes?: readonly string[];
	readonly summary?: { readonly [key: string]: number };
	readonly problems?: readonly string[];
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
	/** Runs the model rules on a project file; `companionText` is the file it references (materials for objects, objects for the floor plan and bim). */
	checkLibrary(python: string, kind: LibraryFileKind, text: string, companionText?: string): Promise<readonly ILibraryProblem[]>;

	/**
	 * The building model generated from the floor plan, keeping the model's own elements
	 * (see `saengine.library.bim`). Problems are returned when either file has errors.
	 */
	generateBuilding(python: string, floorPlanText: string, bimText: string | undefined): Promise<IGeneratedBuilding>;

	/** The building model as IFC (IfcOpenShell), with each element's IFC GlobalId. */
	buildingIfc(python: string, request: IBuildingIfcRequest): Promise<IBuildingIfc>;

	/** The analysis model derived from the building model, with the project settings' loads. */
	deriveFem(python: string, request: IFemDeriveRequest): Promise<IFemDerivation>;
}
