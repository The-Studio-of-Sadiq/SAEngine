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
import { IPartSectionOptions } from '../../../services/saengineProject/common/partSections.js';
import { IPartStatus, PartState } from '../../../services/saengineProject/common/partStatus.js';
import { IProjectPart, ISaengineProject } from '../../../services/saengineProject/common/saengineProject.js';
import { ExportsEditorInput } from './exportsEditorInput.js';

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

/**
 * An entry under a part in the sidebar: one view of the part's editor (a section of it, opened
 * with `{ section }`), or an editor of its own the part has (opened by a command, or by the
 * part's file in another editor).
 */
export interface IPartSection {
	readonly id: string;
	readonly label: string;
	/** The editor's section ids this entry shows: the first is opened. */
	readonly sections?: readonly string[];
	/** The editor (by its id) that shows the part's file for this entry. */
	readonly editorId?: string;
	/** The command that opens this entry's editor, and that editor's input type. */
	readonly command?: string;
	/** The input type of the editor this entry is (the part's own editor, or the command's). */
	readonly typeId?: string;
}

/** Editor and input ids of the part editors with entries (kept as strings: no imports between the parts). */
const GRIDS_EDITOR_ID = 'workbench.editor.saengine.grids';
const FLOOR_PLAN_INPUT = 'workbench.input.saengine.floorPlan';
const MEMBERS_TABLE_INPUT = 'workbench.input.saengine.membersTable';
const FEM_MODEL_INPUT = 'workbench.input.saengine.femModel';
const FEM_RESULTS_INPUT = 'workbench.input.saengine.femResults';
const FEM_PROPOSAL_INPUT = 'workbench.input.saengine.femDesignProposal';
const ARCHITECTURE_INPUT = 'workbench.input.saengine.architecture';

/** The entries under the parts that hold several views (agreed for alpha 7); none for the others. */
export function partSections(partId: string): readonly IPartSection[] {
	switch (partId) {
		case 'settings': return [
			{ id: 'code', label: localize('partSection.settingsCode', "Code and Site"), sections: ['project', 'occupancy', 'site'] },
			{ id: 'loads', label: localize('partSection.settingsLoads', "Loads"), sections: ['areaLoads'] },
			{ id: 'seismic', label: localize('partSection.settingsSeismic', "Seismic"), sections: ['seismic'] },
			{ id: 'wind', label: localize('partSection.settingsWind', "Wind"), sections: ['wind'] },
			{ id: 'combinations', label: localize('partSection.settingsCombinations', "Combinations and Analysis"), sections: ['combinations', 'analysis'] },
			{ id: 'foundation', label: localize('partSection.settingsFoundation', "Foundation"), sections: ['foundation'] },
			{ id: 'drawings', label: localize('partSection.settingsDrawings', "Drawings"), sections: ['drawings'] },
		];
		case 'floorPlan': return [
			{ id: 'plan', label: localize('partSection.floorPlanPlan', "Plan"), typeId: FLOOR_PLAN_INPUT },
			{ id: 'grids', label: localize('partSection.floorPlanGrids', "Grids & Stories"), editorId: GRIDS_EDITOR_ID },
			{ id: 'members', label: localize('partSection.floorPlanMembers', "Members Table"), command: 'saengine.floorPlan.openMembersTable', typeId: MEMBERS_TABLE_INPUT },
		];
		case 'bim': return [
			{ id: '3d', label: localize('partSection.bim3d', "3D View"), sections: ['3d'] },
			{ id: 'additions', label: localize('partSection.bimAdditions', "Additions"), sections: ['additions'] },
			{ id: 'summary', label: localize('partSection.bimSummary', "Summary"), sections: ['summary'] },
			// Walls, doors, windows and rooms: 05 Floor Plan/architecture.json in its own editor (saengineCad).
			{ id: 'architecture', label: localize('partSection.bimArchitecture', "Architecture"), command: 'saengine.architecture.open', typeId: ARCHITECTURE_INPUT },
		];
		case 'mep': return [
			{ id: 'coordination', label: localize('partSection.mepCoordination', "Coordination"), sections: ['coordination'] },
			{ id: 'plumbing', label: localize('partSection.mepPlumbing', "Plumbing"), sections: ['plumbing'] },
			{ id: 'hvac', label: localize('partSection.mepHvac', "HVAC"), sections: ['hvac'] },
			{ id: 'electrical', label: localize('partSection.mepElectrical', "Electrical"), sections: ['electrical'] },
			{ id: 'fire', label: localize('partSection.mepFire', "Fire"), sections: ['fire'] },
		];
		case 'fem': return [
			{ id: 'model', label: localize('partSection.femModel', "Model and Analysis"), typeId: FEM_MODEL_INPUT },
			{ id: 'results', label: localize('partSection.femResults', "Analysis Charts"), command: 'saengine.fem.showCharts', typeId: FEM_RESULTS_INPUT },
			{ id: 'proposal', label: localize('partSection.femProposal', "Design Reinforcement"), command: 'saengine.fem.designReinforcement', typeId: FEM_PROPOSAL_INPUT },
		];
		default: return [];
	}
}

/** Whether the active editor (its input `editor`, its pane `section`) shows `entry`. */
export function isSectionActive(entry: IPartSection, editor: { readonly typeId: string; readonly editorId: string | undefined } | undefined, section: string | undefined): boolean {
	if (!editor) {
		return false;
	}
	if (entry.editorId) {
		return editor.editorId === entry.editorId;
	}
	if (entry.typeId) {
		return editor.typeId === entry.typeId && editor.editorId !== GRIDS_EDITOR_ID;
	}
	return !!section && !!entry.sections?.includes(section);
}

/** Whether the active editor is one of a part's own editors without the part's file (results, tables). */
export function isPartEditor(partId: string, editor: { readonly typeId: string } | undefined): boolean {
	return !!editor && partSections(partId).some(entry => entry.command && entry.typeId === editor.typeId);
}

/** Opens `entry` of `part`. */
export async function openPartSection(project: ISaengineProject, part: IProjectPart, entry: IPartSection, services: {
	readonly editorService: IEditorService;
	readonly commandService: ICommandService;
}, options?: { readonly preserveFocus?: boolean }): Promise<void> {
	const resource = partResource(project, part);
	if (entry.command) {
		await services.commandService.executeCommand(entry.command);
	} else if (resource) {
		const section: IPartSectionOptions = { pinned: false, preserveFocus: options?.preserveFocus, override: entry.editorId, section: entry.sections?.[0] };
		await services.editorService.openEditor({ resource, options: section });
	}
}

/** The file the part's editor opens, if it has one. */
export function partResource(project: ISaengineProject, part: IProjectPart): URI | undefined {
	return part.mainFile ? joinPath(project.root, part.folder, part.mainFile) : undefined;
}

/** CSS class of the status dot of a part in `state` (colours from the design tokens). */
export function stateClass(state: PartState | undefined): string {
	switch (state) {
		case 'done': return 'sa-state-ok';
		case 'defaults': return 'sa-state-info';
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
		case 'defaults': return localize('partState.defaults', "Defaults, not reviewed yet");
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
		case 'defaults': return localize('partText.defaults', "defaults");
		case 'inProgress': return localize('partText.inProgress', "in progress");
		case 'stale': return localize('partText.stale', "stale");
		case 'failed': return localize('partText.failed', "checks fail");
		case 'error': return localize('partText.error', "invalid file");
		default: return localize('partText.notStarted', "not started");
	}
}

/** How many trailing path segments (the project folder and its parents) always stay visible. */
const PATH_TAIL_SEGMENTS = 2;

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

/**
 * Opens the editor of a part: its main file, with the editor registered for it. Part 11 has no
 * main file: it opens the exports page. Parts open as preview tabs, so browsing the parts reuses
 * one tab; a tab is kept once it is edited or double-clicked (G14).
 */
export async function openPart(project: ISaengineProject, part: IProjectPart, services: {
	readonly editorService: IEditorService;
	readonly fileService: IFileService;
	readonly openerService: IOpenerService;
	readonly commandService: ICommandService;
}, options?: { readonly preserveFocus?: boolean }): Promise<void> {
	const resource = partResource(project, part);
	if (resource) {
		await services.editorService.openEditor({ resource, options: { pinned: false, preserveFocus: options?.preserveFocus } });
	} else if (part.id === 'exports') {
		await services.editorService.openEditor(ExportsEditorInput.instance, { pinned: false, preserveFocus: options?.preserveFocus });
	}
}
