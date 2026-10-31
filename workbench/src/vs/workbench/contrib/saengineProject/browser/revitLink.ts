/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { basename, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem, IQuickPickSeparator } from '../../../../platform/quickinput/common/quickInput.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';

/*
 * The Revit link (part 11). SAEngine writes and reads one neutral exchange file
 * (`saengine.structuralExchange/1`, docs/revit-link.md); a separate Revit add-in moves it in and
 * out of Revit. SAEngine never loads Revit's API.
 */

/** Backend: writes `11 Exports/Revit/<project>.exchange.json` (`{projectRoot}`). */
export const REVIT_EXPORT_COMMAND = 'saengine.revit.export';
/** Backend: the changes in a file written back from Revit (`{projectRoot, path}`). */
export const REVIT_PREVIEW_COMMAND = 'saengine.revit.preview';
/** Backend: applies the picked changes to the floor plan (`{projectRoot, path, changes}`). */
export const REVIT_APPLY_COMMAND = 'saengine.revit.apply';
/** UI: Export for Revit, with its progress and notice. */
export const REVIT_EXPORT_UI_COMMAND = 'saengine.revit.exportUi';
/** UI: Import Changes from Revit... (file, preview, pick, apply). */
export const REVIT_IMPORT_UI_COMMAND = 'saengine.revit.importUi';
/** The folder of `11 Exports` the exchange files go to. */
export const EXPORT_REVIT_FOLDER = 'Revit';
/** The exchange files' ending. */
export const EXCHANGE_SUFFIX = '.exchange.json';

const REVEAL_IN_OS_COMMAND = 'revealFileInOS';

export interface IRevitChangeDetail {
	readonly field: string;
	readonly from: string;
	readonly to: string;
}

export interface IRevitChange {
	readonly id: string;
	readonly action: 'add' | 'modify' | 'remove';
	readonly target: 'level' | 'grid' | 'element';
	readonly kind: string;
	readonly title: string;
	readonly details: readonly IRevitChangeDetail[];
	readonly applicable: boolean;
	readonly reason?: string;
}

export interface IRevitPreview {
	readonly changes: readonly IRevitChange[];
	readonly notes: readonly string[];
	readonly source?: string;
	readonly error?: string;
}

type Bag = { readonly [key: string]: unknown };

function bag(value: unknown): Bag {
	return typeof value === 'object' && value !== null ? value as Bag : {};
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

/** The backend's preview, read defensively. */
export function readRevitPreview(value: unknown): IRevitPreview {
	const record = bag(value);
	if (typeof record.error === 'string' && record.error) {
		return { changes: [], notes: [], error: record.error };
	}
	if (!Array.isArray(record.changes)) {
		return { changes: [], notes: [], error: localize('revit.noAnswer', "The backend did not answer.") };
	}
	const changes: IRevitChange[] = [];
	for (const item of record.changes) {
		const c = bag(item);
		if (typeof c.id !== 'string' || typeof c.title !== 'string') {
			continue;
		}
		const action = c.action === 'add' || c.action === 'remove' ? c.action : 'modify';
		const target = c.target === 'level' || c.target === 'grid' ? c.target : 'element';
		const details = Array.isArray(c.details) ? c.details.map(bag).map(d => ({ field: String(d.field ?? ''), from: String(d.from ?? ''), to: String(d.to ?? '') })) : [];
		changes.push({
			id: c.id, action, target, kind: String(c.kind ?? ''), title: c.title, details,
			applicable: c.applicable === true,
			...(typeof c.reason === 'string' ? { reason: c.reason } : {}),
		});
	}
	const source = bag(record.source);
	const from = [source.application, source.version].filter(v => typeof v === 'string' && v).join(' ');
	return { changes, notes: strings(record.notes), ...(from ? { source: from } : {}) };
}

function describe(change: IRevitChange): string {
	return change.details.map(d => d.from ? `${d.field}: ${d.from} → ${d.to}` : `${d.field}: ${d.to}`).join('; ');
}

interface IChangeItem extends IQuickPickItem {
	readonly change: IRevitChange;
}

/** The Revit link's flows: the export, and the import with its change preview. */
export class RevitLinkFlows {

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProgressService private readonly progressService: IProgressService,
		@IEditorService private readonly editorService: IEditorService,
	) { }

	static available(): boolean {
		return !!CommandsRegistry.getCommand(REVIT_EXPORT_COMMAND);
	}

	private project(): ISaengineProject | undefined {
		const project = this.projectService.project;
		if (!project) {
			this.notificationService.info(localize('revit.noProject', "Open a project first."));
		} else if (!RevitLinkFlows.available()) {
			this.notificationService.info(localize('revit.unavailable', "The Revit link is not available in this build of SAEngine."));
			return undefined;
		}
		return project;
	}

	private folder(project: ISaengineProject): URI {
		return joinPath(project.root, partById('exports')?.folder ?? '11 Exports', EXPORT_REVIT_FOLDER);
	}

	/** Writes the exchange file for Revit and says what it holds. */
	async export(): Promise<void> {
		const project = this.project();
		if (!project) {
			return;
		}
		try {
			const answer = bag(await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('revit.exporting', "Exporting {0} for Revit", project.name),
			}, () => this.commandService.executeCommand(REVIT_EXPORT_COMMAND, { projectRoot: project.root.fsPath })));
			if (typeof answer.error === 'string' || typeof answer.path !== 'string') {
				this.notificationService.error(localize('revit.exportFailed', "The export for Revit failed: {0}", typeof answer.error === 'string' ? answer.error : ''));
				return;
			}
			const file = URI.file(answer.path);
			const counts = bag(answer.counts);
			const what = Object.entries(counts).filter(([, n]) => typeof n === 'number' && n > 0).map(([k, n]) => `${n} ${k === 'rebarSets' ? localize('revit.barSets', "bar sets") : k}`).join(', ');
			const notes = strings(answer.notes);
			const message = localize('revit.exported', "Wrote {0} ({1}). Open it in Revit with the SAEngine add-in.{2}", basename(file), what, notes.length ? ` ${notes.join(' ')}` : '');
			this.notificationService.prompt(notes.length ? Severity.Warning : Severity.Info, message, [
				...(CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND) ? [{ label: localize('revit.reveal', "Reveal in File Explorer"), run: () => void this.commandService.executeCommand(REVEAL_IN_OS_COMMAND, file) }] : []),
			]);
		} catch (error) {
			this.notificationService.error(localize('revit.exportFailed', "The export for Revit failed: {0}", toErrorMessage(error)));
		}
	}

	/** Picks a file written back from Revit, previews its changes and applies the ones kept ticked. */
	async import(path?: string): Promise<void> {
		const project = this.project();
		if (!project) {
			return;
		}
		try {
			if (!path) {
				const picked = await this.fileDialogService.showOpenDialog({
					title: localize('revit.importTitle', "Import Changes from Revit"),
					openLabel: localize('revit.importOpen', "&&Preview Changes"),
					canSelectFiles: true,
					canSelectFolders: false,
					canSelectMany: false,
					defaultUri: this.folder(project),
					filters: [{ name: localize('revit.filter', "SAEngine exchange file"), extensions: ['json'] }],
				});
				path = picked?.[0]?.fsPath;
			}
			if (!path) {
				return;
			}
			const filePath = path;
			const preview = readRevitPreview(await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('revit.reading', "Comparing {0} with the project", basename(URI.file(filePath))),
			}, () => this.commandService.executeCommand(REVIT_PREVIEW_COMMAND, { projectRoot: project.root.fsPath, path: filePath })));
			if (preview.error) {
				this.notificationService.error(localize('revit.previewFailed', "The file cannot be read: {0}", preview.error));
				return;
			}
			if (!preview.changes.length) {
				this.notificationService.info(localize('revit.noChanges', "No changes: the model in the file matches the project.{0}", preview.notes.length ? ` ${preview.notes.join(' ')}` : ''));
				return;
			}
			const chosen = await this.pickChanges(preview);
			if (!chosen?.length) {
				return;
			}
			const answer = bag(await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('revit.applying', "Applying {0} changes from Revit", chosen.length),
			}, () => this.commandService.executeCommand(REVIT_APPLY_COMMAND, { projectRoot: project.root.fsPath, path: filePath, changes: chosen })));
			if (typeof answer.error === 'string') {
				this.notificationService.error(localize('revit.applyFailed', "The changes were not applied: {0}", answer.error));
				return;
			}
			const applied = strings(answer.applied).length;
			const failed = Array.isArray(answer.failed) ? answer.failed.map(bag) : [];
			const failures = failed.map(f => `${String(f.id)}: ${String(f.reason)}`).join('; ');
			const notes = strings(answer.notes).join(' ');
			const message = failed.length
				? localize('revit.appliedSome', "Applied {0} changes to the floor plan; {1} could not be applied ({2}). {3}", applied, failed.length, failures, notes)
				: localize('revit.applied', "Applied {0} changes to the floor plan. {1}", applied, notes);
			const plan = partById('floorPlan');
			const planFile = plan?.mainFile ? joinPath(project.root, plan.folder, plan.mainFile) : undefined;
			this.notificationService.prompt(failed.length ? Severity.Warning : Severity.Info, message, [
				...(planFile ? [{ label: localize('revit.openPlan', "Open Floor Plan"), run: () => void this.editorService.openEditor({ resource: planFile, options: { pinned: true } }) }] : []),
			]);
		} catch (error) {
			this.notificationService.error(localize('revit.importFailed', "The import from Revit failed: {0}", toErrorMessage(error)));
		}
	}

	/** The change preview: every change, grouped, the ones SAEngine can take ticked; the others shown with the reason. */
	private async pickChanges(preview: IRevitPreview): Promise<string[] | undefined> {
		const groups: { readonly label: string; readonly test: (c: IRevitChange) => boolean }[] = [
			{ label: localize('revit.groupLevels', "Levels and grid lines"), test: c => c.applicable && c.target !== 'element' },
			{ label: localize('revit.groupAdded', "Added in Revit"), test: c => c.applicable && c.target === 'element' && c.action === 'add' },
			{ label: localize('revit.groupChanged', "Changed in Revit"), test: c => c.applicable && c.target === 'element' && c.action === 'modify' },
			{ label: localize('revit.groupRemoved', "Deleted in Revit"), test: c => c.applicable && c.target === 'element' && c.action === 'remove' },
			{ label: localize('revit.groupNot', "Not taken back"), test: c => !c.applicable },
		];
		const items: (IChangeItem | IQuickPickSeparator)[] = [];
		for (const group of groups) {
			const members = preview.changes.filter(group.test);
			if (!members.length) {
				continue;
			}
			items.push({ type: 'separator', label: `${group.label} (${members.length})` });
			for (const change of members) {
				const icon = change.action === 'add' ? Codicon.add : change.action === 'remove' ? Codicon.trash : Codicon.edit;
				items.push({
					label: `$(${icon.id}) ${change.title}`,
					description: describe(change),
					detail: change.applicable ? undefined : change.reason,
					picked: change.applicable,
					disabled: !change.applicable,
					change,
				});
			}
		}
		const applicable = preview.changes.filter(c => c.applicable).length;
		const picked = await this.quickInputService.pick(items, {
			canPickMany: true,
			title: localize('revit.previewTitle', "Changes from Revit{0}: {1} of {2} can be applied", preview.source ? ` (${preview.source})` : '', applicable, preview.changes.length),
			placeHolder: preview.notes.length ? preview.notes.join(' ') : localize('revit.previewPlaceholder', "Untick what you do not want, then press Enter to apply it to the floor plan"),
			matchOnDescription: true,
			ignoreFocusLost: true,
		});
		return picked?.filter(item => item.change.applicable).map(item => item.change.id);
	}
}
