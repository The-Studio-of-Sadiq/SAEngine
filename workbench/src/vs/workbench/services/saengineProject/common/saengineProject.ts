/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { URI } from '../../../../base/common/uri.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { BIM_SCHEMA, DEFAULT_BIM, DEFAULT_FLOOR_PLAN, DEFAULT_MATERIALS, DEFAULT_OBJECTS, DEFAULT_SETTINGS, DEFAULT_STRUCTURE, FLOOR_PLAN_SCHEMA, MATERIALS_SCHEMA, OBJECTS_SCHEMA, SETTINGS_SCHEMA, STRUCTURE_SCHEMA } from './projectLibraries.generated.js';
import { localize } from '../../../../nls.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';

export const PROJECT_MANIFEST_EXTENSION = '.saengine';
export const PROJECT_MANIFEST_SCHEMA = 1;

/**
 * What a project designs, which decides how it is modelled (Part 5): a building is laid out
 * story by story on a floor plan; a special structure (airport roof, stadium, tower, plant,
 * bridge...) is drawn in 3D as a structural model. Everything downstream is shared.
 */
export type ProjectType = 'building' | 'structure';

export const PROJECT_TYPES: readonly { readonly type: ProjectType; readonly label: string; readonly description: string }[] = [
	{
		type: 'building',
		label: localize('projectType.building', "Building"),
		description: localize('projectType.buildingDescription', "Floors on grids, story by story: houses, offices, high-rises. Part 5 is a floor plan."),
	},
	{
		type: 'structure',
		label: localize('projectType.structure', "Special Structure"),
		description: localize('projectType.structureDescription', "Drawn in 3D: airport roofs, stadiums, towers, plants, bridges. Part 5 is a 3D structural model."),
	},
];

/** JSON Schema of a part's main file, used for validation and completion in the JSON editor. */
export interface IProjectPartSchema {
	readonly id: string;
	readonly schema: IJSONSchema;
}

export interface IProjectPart {
	/** Stable id, used in the manifest and by the module that owns the part. */
	readonly id: string;
	/** Protected folder at the project root. */
	readonly folder: string;
	/** Protected main file inside {@link folder}, if the part has one. */
	readonly mainFile?: string;
	/** Initial content of {@link mainFile} for a new project. */
	readonly initialContent?: (projectName: string) => string;
	readonly schema?: IProjectPartSchema;
}

function json(value: object): () => string {
	return () => JSON.stringify(value, undefined, '\t') + '\n';
}

function placeholder(id: string): () => string {
	// Parts that are not implemented yet start with a versioned stub their module will own.
	return () => JSON.stringify({ schema: 1, part: id }, undefined, '\t') + '\n';
}

/**
 * The fixed structure of a SAEngine project, one folder per part of the workflow. Zero-padded
 * numbers keep the folders in workflow order in every file manager.
 */
export const PROJECT_PARTS: readonly IProjectPart[] = [
	{ id: 'soil', folder: '01 Soil Report', mainFile: 'soil-report.json', initialContent: placeholder('soil') },
	{
		id: 'settings', folder: '02 Project Settings', mainFile: 'project-settings.json',
		initialContent: name => json({ ...DEFAULT_SETTINGS, project: { name } })(),
		schema: { id: 'vscode://schemas/saengine/settings', schema: SETTINGS_SCHEMA },
	},
	{
		id: 'materials', folder: '03 Materials', mainFile: 'materials.json', initialContent: json(DEFAULT_MATERIALS),
		schema: { id: 'vscode://schemas/saengine/materials', schema: MATERIALS_SCHEMA },
	},
	{
		id: 'objects', folder: '04 Objects', mainFile: 'objects.json', initialContent: json(DEFAULT_OBJECTS),
		schema: { id: 'vscode://schemas/saengine/objects', schema: OBJECTS_SCHEMA },
	},
	{
		id: 'floorPlan', folder: '05 Floor Plan', mainFile: 'floor-plan.json', initialContent: json(DEFAULT_FLOOR_PLAN),
		schema: { id: 'vscode://schemas/saengine/floorPlan', schema: FLOOR_PLAN_SCHEMA },
	},
	{
		id: 'bim', folder: '06 BIM', mainFile: 'bim.json', initialContent: json(DEFAULT_BIM),
		schema: { id: 'vscode://schemas/saengine/bim', schema: BIM_SCHEMA },
	},
	{ id: 'mep', folder: '07 MEP', mainFile: 'mep.json', initialContent: placeholder('mep') },
	{
		id: 'fem', folder: '08 FEM', mainFile: 'model.osmodel',
		// opensees-studio fills every other field with its defaults.
		initialContent: name => JSON.stringify({ schema_version: 2, meta: { name } }, undefined, '\t') + '\n',
	},
	{ id: 'substructure', folder: '09 Substructure', mainFile: 'substructure.json', initialContent: placeholder('substructure') },
	{ id: 'boq', folder: '10 BOQ', mainFile: 'boq.json', initialContent: placeholder('boq') },
	{ id: 'exports', folder: '11 Exports' },
];

/** Part 5 of a special structure: the 3D structural model instead of the floor plan. */
export const STRUCTURE_PART: IProjectPart = {
	id: 'structure', folder: '05 Structural Model', mainFile: 'structure.json', initialContent: json(DEFAULT_STRUCTURE),
	schema: { id: 'vscode://schemas/saengine/structure', schema: STRUCTURE_SCHEMA },
};

/** Every part a project of either type can have. */
export const ALL_PARTS: readonly IProjectPart[] = [...PROJECT_PARTS, STRUCTURE_PART];

/** The parts of a project of `type`, in workflow order. */
export function projectParts(type: ProjectType): readonly IProjectPart[] {
	return type === 'structure' ? PROJECT_PARTS.map(p => p.id === 'floorPlan' ? STRUCTURE_PART : p) : PROJECT_PARTS;
}

/** The part with `id`, whichever project type has it. */
export function partById(id: string): IProjectPart | undefined {
	return ALL_PARTS.find(p => p.id === id);
}

export interface IProjectManifest {
	readonly schema: number;
	readonly name: string;
	readonly created: string;
	/** What the project designs; missing in projects created before there was a choice. */
	readonly type?: ProjectType;
	readonly parts: readonly string[];
}

export function createManifest(name: string, type: ProjectType = 'building'): IProjectManifest {
	return {
		schema: PROJECT_MANIFEST_SCHEMA,
		name,
		created: new Date().toISOString(),
		type,
		parts: projectParts(type).map(p => p.id),
	};
}

export interface ISaengineProject {
	readonly root: URI;
	readonly manifest: URI;
	readonly name: string;
	readonly type: ProjectType;
}

export const ISaengineProjectService = createDecorator<ISaengineProjectService>('saengineProjectService');

/**
 * Knows the SAEngine project open in the workspace and guards its core structure: the
 * manifest, the part folders and each part's main file can be neither deleted, renamed nor
 * moved, and are recreated if they disappear from disk.
 */
export interface ISaengineProjectService {
	readonly _serviceBrand: undefined;

	/** The project at the first workspace folder, once detected. */
	readonly project: ISaengineProject | undefined;
	readonly onDidChangeProject: Event<ISaengineProject | undefined>;

	/** The parts of the open project (Part 5 depends on its type); the building parts without one. */
	readonly parts: readonly IProjectPart[];

	/** True for the project's core items: manifest, part folders and part main files. */
	isProtected(resource: URI): boolean;

	/** The project whose root is `folder`, if `folder` contains a manifest. */
	findProject(folder: URI): Promise<ISaengineProject | undefined>;

	/**
	 * Creates the project structure in `folder` (created if missing). Existing files are
	 * left untouched, so this also turns an existing folder into a project.
	 */
	createProject(folder: URI, name: string, type?: ProjectType): Promise<ISaengineProject>;

	/**
	 * Changes what the open project designs. The new Part 5 folder and file are created; the
	 * other one stays on disk with its files (no longer a core item).
	 */
	setProjectType(type: ProjectType): Promise<void>;
}
