/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { URI } from '../../../../base/common/uri.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { DEFAULT_MATERIALS, DEFAULT_OBJECTS, MATERIALS_SCHEMA, OBJECTS_SCHEMA } from './projectLibraries.generated.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';

export const PROJECT_MANIFEST_EXTENSION = '.saengine';
export const PROJECT_MANIFEST_SCHEMA = 1;

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
	{ id: 'settings', folder: '02 Project Settings', mainFile: 'project-settings.json', initialContent: placeholder('settings') },
	{
		id: 'materials', folder: '03 Materials', mainFile: 'materials.json', initialContent: json(DEFAULT_MATERIALS),
		schema: { id: 'vscode://schemas/saengine/materials', schema: MATERIALS_SCHEMA },
	},
	{
		id: 'objects', folder: '04 Objects', mainFile: 'objects.json', initialContent: json(DEFAULT_OBJECTS),
		schema: { id: 'vscode://schemas/saengine/objects', schema: OBJECTS_SCHEMA },
	},
	{ id: 'floorPlan', folder: '05 Floor Plan', mainFile: 'floor-plan.json', initialContent: placeholder('floorPlan') },
	{ id: 'bim', folder: '06 BIM', mainFile: 'bim.json', initialContent: placeholder('bim') },
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

export interface IProjectManifest {
	readonly schema: number;
	readonly name: string;
	readonly created: string;
	readonly parts: readonly string[];
}

export function createManifest(name: string): IProjectManifest {
	return {
		schema: PROJECT_MANIFEST_SCHEMA,
		name,
		created: new Date().toISOString(),
		parts: PROJECT_PARTS.map(p => p.id),
	};
}

export interface ISaengineProject {
	readonly root: URI;
	readonly manifest: URI;
	readonly name: string;
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

	/** True for the project's core items: manifest, part folders and part main files. */
	isProtected(resource: URI): boolean;

	/** The project whose root is `folder`, if `folder` contains a manifest. */
	findProject(folder: URI): Promise<ISaengineProject | undefined>;

	/**
	 * Creates the project structure in `folder` (created if missing). Existing files are
	 * left untouched, so this also turns an existing folder into a project.
	 */
	createProject(folder: URI, name: string): Promise<ISaengineProject>;
}
