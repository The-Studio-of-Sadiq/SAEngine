/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { extUriBiasedIgnorePathCase, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IPartStatus, PartState, REPORT_FILE } from '../../../services/saengineProject/common/partStatus.js';
import { IProjectPart, ISaengineProject } from '../../../services/saengineProject/common/saengineProject.js';

/*
 * The project's parts as the sidebar and the overview show them: numbered in workflow order
 * and grouped under small headings. The parts and their folders are the project service's.
 */

export interface IPartEntry {
	/** 1-based number of the part in the workflow. */
	readonly number: number;
	readonly part: IProjectPart;
	/** The part's name: its folder without the number ("05 Floor Plan" -> "Floor Plan"). */
	readonly name: string;
}

export interface IPartGroup {
	readonly id: string;
	readonly label: string;
	readonly parts: readonly IPartEntry[];
}

const GROUPS: readonly { readonly id: string; readonly label: () => string; readonly parts: readonly string[] }[] = [
	{ id: 'site', label: () => localize('partGroup.site', "Site"), parts: ['soil', 'settings'] },
	{ id: 'library', label: () => localize('partGroup.library', "Library"), parts: ['materials', 'objects'] },
	{ id: 'model', label: () => localize('partGroup.model', "Model"), parts: ['floorPlan', 'structure', 'bim', 'mep'] },
	{ id: 'analysis', label: () => localize('partGroup.analysis', "Analysis and design"), parts: ['fem', 'substructure'] },
	{ id: 'outputs', label: () => localize('partGroup.outputs', "Outputs"), parts: ['boq', 'exports'] },
];

export function partName(part: IProjectPart): string {
	return part.folder.replace(/^\d+\s+/, '');
}

/** The groups of `parts` (a project's parts, in workflow order); a part outside every group gets its own. */
export function partGroups(parts: readonly IProjectPart[]): IPartGroup[] {
	const entries = parts.map((part, index) => ({ number: index + 1, part, name: partName(part) }));
	const groups: IPartGroup[] = GROUPS.map(group => ({
		id: group.id,
		label: group.label(),
		parts: entries.filter(entry => group.parts.includes(entry.part.id)),
	}));
	for (const entry of entries) {
		if (!GROUPS.some(group => group.parts.includes(entry.part.id))) {
			groups.push({ id: entry.part.id, label: entry.name, parts: [entry] });
		}
	}
	return groups.filter(group => group.parts.length);
}

/** The file the part's editor opens, if it has one. */
export function partResource(project: ISaengineProject, part: IProjectPart): URI | undefined {
	return part.mainFile ? joinPath(project.root, part.folder, part.mainFile) : undefined;
}

/** CSS class of the status dot of a part in `state` (colours from the design tokens). */
export function stateClass(state: PartState | undefined): string {
	switch (state) {
		case 'done': return 'sa-state-ok';
		case 'inProgress':
		case 'stale': return 'sa-state-warn';
		case 'failed':
		case 'error': return 'sa-state-fail';
		default: return 'sa-state-idle';
	}
}

/** Words for screen readers and tooltips for a part in `state`. */
export function stateLabel(status: IPartStatus | undefined): string {
	switch (status?.state) {
		case 'done': return localize('partState.done', "Done");
		case 'inProgress': return localize('partState.inProgress', "In progress");
		case 'stale': return localize('partState.stale', "Out of date");
		case 'failed': return localize('partState.failed', "Design checks fail");
		case 'error': return localize('partState.error', "Invalid file");
		default: return localize('partState.notStarted', "Not started");
	}
}

/** The short muted text of a part: its status text, or the state in the same lower-case words. */
export function stateText(status: IPartStatus | undefined): string {
	if (status?.text) {
		return status.text;
	}
	switch (status?.state) {
		case 'done': return localize('partText.done', "done");
		case 'inProgress': return localize('partText.inProgress', "in progress");
		case 'stale': return localize('partText.stale', "stale");
		case 'failed': return localize('partText.failed', "checks fail");
		case 'error': return localize('partText.error', "invalid file");
		default: return localize('partText.notStarted', "not started");
	}
}

/** How many trailing path segments (the project folder and its parents) always stay visible. */
const PATH_TAIL_SEGMENTS = 3;

/**
 * The path of a project folder as `head` + `tail`: home-relative (`~`), with the last folders
 * in `tail`. Shown with the head cut in the middle, so projects of the same name stay apart.
 */
export function splitProjectPath(root: URI, userHome: URI | undefined): { readonly head: string; readonly tail: string } {
	const relative = userHome && extUriBiasedIgnorePathCase.isEqualOrParent(root, userHome) ? extUriBiasedIgnorePathCase.relativePath(userHome, root) : undefined;
	const sep = root.fsPath.includes('\\') ? '\\' : '/';
	const path = relative !== undefined ? ['~', ...relative.split('/').filter(Boolean)].join(sep) : root.fsPath;
	const segments = path.split(/[\\/]/);
	if (segments.length <= PATH_TAIL_SEGMENTS) {
		return { head: '', tail: path };
	}
	const tail = segments.slice(-PATH_TAIL_SEGMENTS).join(sep);
	return { head: path.slice(0, path.length - tail.length), tail };
}

/** Appends the project folder's path (see {@link splitProjectPath}) as `span.sa-path`. */
export function appendProjectPath(parent: HTMLElement, root: URI, userHome: URI | undefined): HTMLElement {
	const { head, tail } = splitProjectPath(root, userHome);
	const element = append(parent, $('span.sa-path'));
	append(element, $('span.sa-path-head', undefined, head));
	append(element, $('span.sa-path-tail', undefined, tail));
	return element;
}

const PRINT_REPORT_COMMAND = 'saengine.report.print';

/**
 * Opens the editor of a part: its main file, with the editor registered for it. Part 11 has no
 * main file: its design report opens in the system's PDF viewer, or is printed if there is none.
 */
export async function openPart(project: ISaengineProject, part: IProjectPart, services: {
	readonly editorService: IEditorService;
	readonly fileService: IFileService;
	readonly openerService: IOpenerService;
	readonly commandService: ICommandService;
}, options?: { readonly preserveFocus?: boolean }): Promise<void> {
	const resource = partResource(project, part);
	if (resource) {
		await services.editorService.openEditor({ resource, options: { pinned: true, preserveFocus: options?.preserveFocus } });
		return;
	}
	const report = joinPath(project.root, part.folder, REPORT_FILE);
	if (await services.fileService.exists(report)) {
		await services.openerService.open(report, { openExternal: true });
	} else {
		await services.commandService.executeCommand(PRINT_REPORT_COMMAND);
	}
}
