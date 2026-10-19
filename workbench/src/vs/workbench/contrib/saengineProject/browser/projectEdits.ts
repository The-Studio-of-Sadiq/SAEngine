/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { extUriBiasedIgnorePathCase } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { SaveReason } from '../../../common/editor.js';
import { ALL_PARTS, IProjectPart } from '../../../services/saengineProject/common/saengineProject.js';
import { IWorkingCopy } from '../../../services/workingCopy/common/workingCopy.js';
import { IWorkingCopyService } from '../../../services/workingCopy/common/workingCopyService.js';
import { PROJECT_FILES_PART } from './versionsModel.js';

/*
 * The project's unsaved edits: part files changed in an editor but not saved yet (auto-save is off
 * in SAEngine). The backend (versions, archive) reads the files on disk, so Save Version, Export
 * Project and Restore first save these, as Run All does, and the sidebar counts them as changed.
 */

/**
 * The part a file of the project belongs to: the part whose folder holds it, 'project' for a
 * file at the project's root, or the top-level folder's name for any other folder (as the
 * versions backend names it). Undefined for a file outside the project.
 */
export function partOfResource(root: URI, resource: URI, parts: readonly IProjectPart[] = ALL_PARTS): string | undefined {
	if (!extUriBiasedIgnorePathCase.isEqualOrParent(resource, root)) {
		return undefined;
	}
	const path = extUriBiasedIgnorePathCase.relativePath(root, resource);
	if (!path) {
		return undefined;
	}
	const slash = path.indexOf('/');
	if (slash < 0) {
		return PROJECT_FILES_PART;
	}
	const folder = path.slice(0, slash);
	return (parts.find(p => p.folder.toLowerCase() === folder.toLowerCase()) ?? ALL_PARTS.find(p => p.folder.toLowerCase() === folder.toLowerCase()))?.id ?? folder;
}

/** The working copies (editors) of the project at `root` with edits not saved to disk yet. */
export function unsavedEdits(workingCopyService: IWorkingCopyService, root: URI): IWorkingCopy[] {
	return workingCopyService.dirtyWorkingCopies.filter(copy => partOfResource(root, copy.resource) !== undefined);
}

/** The parts (ids, in the order first met) that have edits not saved yet. */
export function editedParts(copies: readonly IWorkingCopy[], root: URI, parts?: readonly IProjectPart[]): string[] {
	const ids: string[] = [];
	for (const copy of copies) {
		const part = partOfResource(root, copy.resource, parts);
		if (part !== undefined && !ids.includes(part)) {
			ids.push(part);
		}
	}
	return ids;
}

/**
 * Saves the project's unsaved edits so that the backend reads what the engineer sees. Returns the
 * files that could not be saved (a conflict the engineer cancelled, a read-only file): the caller
 * stops rather than work on stale files.
 */
export async function saveProjectEdits(workingCopyService: IWorkingCopyService, root: URI): Promise<URI[]> {
	const failed: URI[] = [];
	for (const copy of unsavedEdits(workingCopyService, root)) {
		let saved = false;
		try {
			saved = await copy.save({ reason: SaveReason.EXPLICIT });
		} catch {
			saved = false;
		}
		if (!saved || copy.isDirty()) {
			failed.push(copy.resource);
		}
	}
	return failed;
}
