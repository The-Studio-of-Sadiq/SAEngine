/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { relativePath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ISaengineProject, projectParts } from './saengineProject.js';

/*
 * The project's part folders read as a flowchart in the Explorer: one node per part, in workflow
 * order, with arrows pointing down from "01 Soil Report" to "11 Exports".
 */

/** Height of the connector above every part folder but the first [px]. */
export const PROJECT_FLOW_GAP = 14;

export interface IProjectFlowPosition {
	/** Index of the part in the workflow. */
	readonly part: number;
	/** The part folder itself (a flowchart node), rather than something inside it. */
	readonly node: boolean;
	/** Path segments below the project root: 1 for a part folder, more for its contents. */
	readonly level: number;
	readonly first: boolean;
	readonly last: boolean;
}

/** Where `resource` sits in the project's flow, if it is a part folder or inside one. */
export function projectFlowPosition(project: ISaengineProject | undefined, resource: URI): IProjectFlowPosition | undefined {
	if (!project) {
		return undefined;
	}
	const path = relativePath(project.root, resource);
	if (!path || path.startsWith('..')) {
		return undefined;
	}
	const segments = path.split('/');
	const parts = projectParts(project.type);
	const part = parts.findIndex(p => p.folder === segments[0]);
	if (part < 0) {
		return undefined;
	}
	return { part, node: segments.length === 1, level: segments.length, first: part === 0, last: part === parts.length - 1 };
}
