/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { DEFAULT_CODE_TABLES } from './projectLibraries.generated.js';

/**
 * The code pack the open project follows, as the editors name it. SAEngine is not built around
 * one code: the project's settings choose a code pack (`codePack`), and the text the editors
 * show names that pack. It is set by the workbench contribution that reads the project's
 * settings and asks the backend for the pack (saengineModel/browser/projectCodeStiffness.ts) and
 * by the Project Settings editor when the pack is changed there.
 */
let active: { readonly id: string | undefined; readonly name: string | undefined } = { id: undefined, name: undefined };

/** The id of the pack a project without `codePack` follows (saengine.codes.registry.DEFAULT_PACK). */
export const DEFAULT_CODE_PACK_ID = 'bnbc2020';

/** Records the open project's pack (undefined: no project, or not known yet). */
export function setActiveCodePack(id: string | undefined, name: string | undefined): void {
	active = { id, name };
}

/** The display name of the code pack the open project follows, e.g. "BNBC 2020" for the default pack. */
export function activeCodeName(): string {
	if (active.name) {
		return active.name;
	}
	return !active.id || active.id === DEFAULT_CODE_PACK_ID ? DEFAULT_CODE_TABLES.edition : active.id;
}

/**
 * The name of the default pack, whose tables the editors use for their previews and whose clause
 * numbers their help texts quote (e.g. "BNBC 2020"). Help that cites a clause number names this
 * pack, not the active one, because the number is the default pack's.
 */
export function defaultCodeName(): string {
	return DEFAULT_CODE_TABLES.edition;
}
