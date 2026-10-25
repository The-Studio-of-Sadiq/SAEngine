/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saveStatus.css';
import { $ } from '../../../../base/browser/dom.js';
import { status } from '../../../../base/browser/ui/aria/aria.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { FileOperation, IFileService } from '../../../../platform/files/common/files.js';
import { ILabelService } from '../../../../platform/label/common/label.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { GroupModelChangeKind } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { AutoSaveMode, IFilesConfigurationService } from '../../../services/filesConfiguration/common/filesConfigurationService.js';
import { IStatusbarEntry, IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { ITextFileService, TextFileEditorModelState } from '../../../services/textfile/common/textfiles.js';
import { IWorkingCopy } from '../../../services/workingCopy/common/workingCopy.js';
import { IWorkingCopyService } from '../../../services/workingCopy/common/workingCopyService.js';
import { ISaveStatus, SaveStatusKind, SaveStatusModel } from '../common/saveStatusModel.js';

const SAVE_ALL_COMMAND_ID = 'saveAll';
const SHOW_FAILURES_COMMAND_ID = 'saengine.saveStatus.showFailures';
const ENTRY_ID = 'saengine-save-status';
/** Lists at most this many documents in the tooltip. */
const MAX_LISTED = 8;

/**
 * The save status at the right of the status bar: "Saved", "Unsaved changes (n)" (click saves
 * all), "Saving…" with a thin progress bar, or "Save failed" (click for details).
 *
 * Built on the working copy service, so every document backed by a working copy counts: the
 * SAEngine part editors keep their part file's text model as the document. Editors with their
 * own dirty state and no working copy (the DXF drawing editor) count through the editor service.
 * Saves are seen from start to end through a text file save participant; other writes into the
 * project (results of Run All, exports) show as a short save once written.
 */
class SaveStatusContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengineSaveStatus';

	private readonly model = this._register(new SaveStatusModel());
	private readonly entry: IStatusbarEntryAccessor;
	/** The thin bar along the bottom of the entry (coloured by `progressBar.background`). */
	private readonly progressContainer = $('.saengine-save-progress', { 'aria-hidden': 'true' }, $('.saengine-save-progress-bit'));
	private readonly render = this._register(new RunOnceScheduler(() => this.update(), 0));
	/** Editors with their own dirty state (no working copy), by id. */
	private readonly dirtyEditors = new Set<string>();
	private shown: SaveStatusKind | undefined;

	constructor(
		@IStatusbarService statusbarService: IStatusbarService,
		@IWorkingCopyService private readonly workingCopyService: IWorkingCopyService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IFilesConfigurationService private readonly filesConfigurationService: IFilesConfigurationService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService fileService: IFileService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@ILabelService private readonly labelService: ILabelService,
	) {
		super();
		this.entry = this._register(statusbarService.addEntry(this.entryFor(this.model.status(Date.now())), ENTRY_ID, StatusbarAlignment.RIGHT, 102));
		this._register(this.model.onDidChange(() => this.render.schedule()));

		// Unsaved documents
		for (const workingCopy of this.workingCopyService.dirtyWorkingCopies) {
			this.trackDirty(workingCopy);
		}
		this._register(this.workingCopyService.onDidChangeDirty(workingCopy => this.trackDirty(workingCopy)));
		this._register(this.workingCopyService.onDidUnregister(workingCopy => this.model.remove(this.key(workingCopy))));
		this._register(this.filesConfigurationService.onDidChangeAutoSaveConfiguration(() => this.trackAllDirty()));
		this._register(this.filesConfigurationService.onDidChangeAutoSaveDisabled(() => this.trackAllDirty()));
		this._register(this.editorService.onDidEditorsChange(e => {
			if (e.event.kind === GroupModelChangeKind.EDITOR_DIRTY || e.event.kind === GroupModelChangeKind.EDITOR_CLOSE) {
				this.trackDirtyEditors();
			}
		}));

		// Saves: start (save participant), end, outcome
		this._register(this.textFileService.files.addSaveParticipant({
			ordinal: -1000,
			participate: async model => {
				const id = this.key(model);
				this.model.saveStarted(id, Date.now());
				// The save is registered as running only once its task is created: join it after this turn.
				queueMicrotask(() => {
					const running = model.hasState(TextFileEditorModelState.PENDING_SAVE) ? model.joinState(TextFileEditorModelState.PENDING_SAVE) : undefined;
					Promise.resolve(running).catch(() => { }).finally(() => this.model.saveEnded(id, Date.now()));
				});
			}
		}));
		this._register(this.workingCopyService.onDidSave(e => this.model.saved(this.key(e.workingCopy), Date.now())));
		this._register(this.textFileService.files.onDidSaveError(model => this.model.saveFailed(this.key(model), this.label(model.resource))));

		// Other writes into the project (results, exports, drawings without a working copy)
		this._register(fileService.onDidRunOperation(e => {
			if ((e.isOperation(FileOperation.WRITE) || e.isOperation(FileOperation.CREATE)) && !this.textFileService.files.get(e.resource) && this.contextService.isInsideWorkspace(e.resource)) {
				this.model.wrote(Date.now());
			}
		}));

		this._register(CommandsRegistry.registerCommand(SHOW_FAILURES_COMMAND_ID, accessor => this.showFailures(accessor.get(INotificationService), accessor.get(ICommandService))));
		this.update();
	}

	private key(workingCopy: IWorkingCopy): string {
		return `${workingCopy.typeId}|${workingCopy.resource.toString()}`;
	}

	private label(resource: URI): string {
		return this.labelService.getUriLabel(resource, { relative: true });
	}

	private autoSaves(resource: URI): boolean {
		const mode = this.filesConfigurationService.getAutoSaveMode(resource).mode;
		return mode === AutoSaveMode.AFTER_SHORT_DELAY || mode === AutoSaveMode.AFTER_LONG_DELAY;
	}

	private trackDirty(workingCopy: IWorkingCopy): void {
		this.model.setDirty(this.key(workingCopy), this.label(workingCopy.resource), workingCopy.isDirty(), this.autoSaves(workingCopy.resource));
	}

	private trackAllDirty(): void {
		for (const workingCopy of this.workingCopyService.dirtyWorkingCopies) {
			this.trackDirty(workingCopy);
		}
	}

	private trackDirtyEditors(): void {
		const dirty = new Map<string, URI>();
		for (const editor of this.editorService.editors) {
			const resource = editor.resource;
			if (resource && editor.isDirty() && !this.workingCopyService.has(resource)) {
				dirty.set(`editor|${editor.typeId}|${resource.toString()}`, resource);
			}
		}
		for (const id of this.dirtyEditors) {
			if (!dirty.has(id)) {
				this.dirtyEditors.delete(id);
				this.model.setDirty(id, '', false);
			}
		}
		for (const [id, resource] of dirty) {
			this.dirtyEditors.add(id);
			this.model.setDirty(id, this.label(resource), true);
		}
	}

	private update(): void {
		const now = Date.now();
		const state = this.model.status(now);
		this.entry.update(this.entryFor(state));

		this.progressContainer.classList.toggle('active', state.kind === SaveStatusKind.Saving);
		this.progressContainer.classList.toggle('pending', state.autoSavePending);
		if (state.showSavingUntil !== undefined) {
			this.render.schedule(state.showSavingUntil - now + 1);
		}

		if (state.kind !== this.shown) {
			const announcement = this.announcementFor(state, this.shown);
			this.shown = state.kind;
			if (announcement) {
				status(announcement);
			}
		}
	}

	/** Spoken (aria-live polite) when the status changes; typing alone is not announced each time. */
	private announcementFor(state: ISaveStatus, previous: SaveStatusKind | undefined): string | undefined {
		switch (state.kind) {
			case SaveStatusKind.Saved: return previous === undefined ? undefined : localize('saveStatus.announceSaved', "All changes saved");
			case SaveStatusKind.Saving: return state.autoSavePending ? undefined : localize('saveStatus.announceSaving', "Saving");
			case SaveStatusKind.Unsaved: return previous === SaveStatusKind.Saved || previous === undefined ? undefined : localize('saveStatus.announceUnsaved', "Unsaved changes: {0}", state.unsaved.length);
			case SaveStatusKind.Failed: return localize('saveStatus.announceFailed', "Save failed: {0}", state.failed.join(', '));
		}
	}

	private entryFor(state: ISaveStatus): IStatusbarEntry {
		const name = localize('saveStatus.name', "Save Status");
		const content = this.progressContainer;
		switch (state.kind) {
			case SaveStatusKind.Saved: {
				const text = localize('saveStatus.saved', "Saved");
				return {
					name, content, text: `$(check) ${text}`, ariaLabel: text,
					tooltip: state.lastSaved !== undefined
						? localize('saveStatus.savedTooltip', "All changes saved. Last saved at {0}.", new Date(state.lastSaved).toLocaleTimeString())
						: localize('saveStatus.savedTooltipNever', "All changes saved."),
				};
			}
			case SaveStatusKind.Unsaved: {
				const text = localize('saveStatus.unsaved', "Unsaved changes ({0})", state.unsaved.length);
				return {
					name, content, text: `$(circle-filled) ${text}`, ariaLabel: localize('saveStatus.unsavedAria', "Unsaved changes ({0}). Click to save all.", state.unsaved.length),
					tooltip: [localize('saveStatus.unsavedTooltip', "Unsaved changes:"), ...this.list(state.unsaved), '', localize('saveStatus.unsavedClick', "Click to save all.")].join('\n'),
					command: { id: SAVE_ALL_COMMAND_ID, title: localize('saveStatus.saveAll', "Save All") },
				};
			}
			case SaveStatusKind.Saving: {
				const text = localize('saveStatus.saving', "Saving…");
				return {
					name, content, text: state.autoSavePending ? `$(circle-filled) ${text}` : text, ariaLabel: text,
					tooltip: state.autoSavePending
						? [localize('saveStatus.autoSaveTooltip', "Auto save will save shortly:"), ...this.list(state.unsaved)].join('\n')
						: localize('saveStatus.savingTooltip', "Saving changes to the project."),
				};
			}
			case SaveStatusKind.Failed: {
				const text = localize('saveStatus.failed', "Save failed — click for details");
				return {
					name, content, text: `$(error) ${text}`, ariaLabel: text, kind: 'error',
					tooltip: [localize('saveStatus.failedTooltip', "Could not save:"), ...this.list(state.failed)].join('\n'),
					command: { id: SHOW_FAILURES_COMMAND_ID, title: localize('saveStatus.showFailures', "Show Save Failures") },
				};
			}
		}
	}

	private list(labels: readonly string[]): string[] {
		const listed = labels.slice(0, MAX_LISTED).map(label => `• ${label}`);
		if (labels.length > MAX_LISTED) {
			listed.push(localize('saveStatus.more', "and {0} more", labels.length - MAX_LISTED));
		}
		return listed;
	}

	private showFailures(notificationService: INotificationService, commandService: ICommandService): void {
		const failed = this.model.status(Date.now()).failed;
		if (!failed.length) {
			return;
		}
		notificationService.prompt(Severity.Error,
			localize('saveStatus.failedDetails', "Could not save {0}. The changes are kept in the editor; check that the file is not read-only, locked by another program or on a full disk, then save again.", failed.join(', ')),
			[
				{ label: localize('saveStatus.retry', "Save Again"), run: () => commandService.executeCommand(SAVE_ALL_COMMAND_ID) },
				{ label: localize('saveStatus.dismiss', "Dismiss"), run: () => this.model.clearFailures() },
			]);
	}
}

registerWorkbenchContribution2(SaveStatusContribution.ID, SaveStatusContribution, WorkbenchPhase.AfterRestored);
