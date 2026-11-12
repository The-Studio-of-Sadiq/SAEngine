/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken, CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { Disposable, IReference } from '../../../../base/common/lifecycle.js';
import { ResourceMap } from '../../../../base/common/map.js';
import { extUriBiasedIgnorePathCase, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { Range } from '../../../../editor/common/core/range.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { UndoRedoGroup } from '../../../../platform/undoRedo/common/undoRedo.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IHostService } from '../../host/browser/host.js';
import { IPathService } from '../../path/common/pathService.js';
import { ITextFileService } from '../../textfile/common/textfiles.js';
import { ACTIONS_CANCEL_COMMAND, ACTIONS_LIST_COMMAND, ACTIONS_RUN_COMMAND, ActionKind, IActionInfo, IActionStep, IActionsOutcome, IActionsRunOptions, IActionsRunRequest, ISaengineActionsService, minimalEdit, PROJECT_CREATE_ACTION, readBatchResult, readCatalogue, stepNames, stepNeedsWrite } from '../common/saengineActions.js';
import { DEFAULT_PROJECTS_FOLDER, ISaengineProjectService, projectFolderName } from '../common/saengineProject.js';

/**
 * Applies new texts to text models as ONE undo step over every file (Ctrl+Z in any of them, or
 * Undo of a change set, reverts them all), each as the one small edit between the old and the
 * new text, so the rest of a document (and the co-editing peers' cursors) stays put. Texts with
 * `\n` line ends take the model's own.
 */
export function applyTextsAsOneStep(edits: readonly { readonly model: ITextModel; readonly text: string }[]): ITextModel[] {
	const group = new UndoRedoGroup();
	const changed: ITextModel[] = [];
	for (const { model, text } of edits) {
		const wanted = text.replace(/\r?\n/g, model.getEOL());
		const edit = minimalEdit(model.getValue(), wanted);
		if (!edit) {
			continue;
		}
		model.pushStackElement();
		model.pushEditOperations([], [{ range: Range.fromPositions(model.getPositionAt(edit.start), model.getPositionAt(edit.end)), text: edit.text }], () => null, group);
		model.pushStackElement();
		changed.push(model);
	}
	return changed;
}

/** A project-relative path the engine gave, or undefined when it would leave the project. */
function insideProject(path: string): string[] | undefined {
	const segments = path.replace(/\\/g, '/').split('/').filter(s => s.length > 0);
	if (!segments.length || /^[a-zA-Z]:/.test(path) || /^[\\/]/.test(path) || segments.some(s => s === '.' || s === '..' || s.includes(':') || s.includes('\0'))) {
		return undefined;
	}
	return segments;
}

export class SaengineActionsService extends Disposable implements ISaengineActionsService {

	declare readonly _serviceBrand: undefined;

	private catalogue: Promise<readonly IActionInfo[]> | undefined;
	/** The models the service changed, kept so their undo stack and unsaved text stay. */
	private readonly references = new ResourceMap<IReference<IResolvedTextEditorModel>>();

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IFileService private readonly fileService: IFileService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IProgressService private readonly progressService: IProgressService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IPathService private readonly pathService: IPathService,
		@IHostService private readonly hostService: IHostService,
	) {
		super();
		this._register(this.projectService.onDidChangeProject(() => this.releaseAll()));
	}

	async listActions(kind?: ActionKind): Promise<readonly IActionInfo[]> {
		if (!this.catalogue) {
			this.catalogue = this.backend<unknown>(ACTIONS_LIST_COMMAND, {}).then(readCatalogue);
			// A failed request is asked again next time (the engine may have been restarting).
			this.catalogue.catch(() => this.catalogue = undefined);
		}
		const all = await this.catalogue;
		return kind ? all.filter(info => info.kind === kind) : all;
	}

	async describe(name: string): Promise<IActionInfo | undefined> {
		return (await this.listActions()).find(info => info.name === name);
	}

	async needsWrite(steps: readonly IActionStep[]): Promise<boolean> {
		const catalogue = await this.listActions();
		return steps.some(step => stepNeedsWrite(step, catalogue));
	}

	async run(steps: readonly IActionStep[], options: IActionsRunOptions, token: CancellationToken = CancellationToken.None): Promise<IActionsOutcome> {
		if (!steps.length) {
			throw new Error(localize('actions.noSteps', "The batch has no steps."));
		}
		const write = await this.needsWrite(steps);
		const root = await this.root(steps, write && options.apply);
		if (!root) {
			const results = [{ ok: false, message: localize('actions.noLocation', "No folder was chosen for the new project: nothing was created."), created: [], warnings: [], problems: [], written: [] }];
			return { ok: false, results, changes: {}, failedStep: 0, written: [], cancelled: true, ran: false, applied: [] };
		}
		if (write && options.apply) {
			const outcome = await this.runWritten(root.folder, steps, token);
			if (root.created && outcome.ok) {
				// The new project opens in this window, as the New Project wizard opens it.
				await this.hostService.openWindow([{ folderUri: root.folder }], { forceReuseWindow: true });
				return { ...outcome, createdIn: root.folder.fsPath };
			}
			if (outcome.ok && !this.projectService.project && steps[0].action === PROJECT_CREATE_ACTION) {
				// Created in the open folder: open it now rather than wait for the file watcher,
				// so the next request (the AI's next batch) finds the project.
				await this.projectService.refresh();
			}
			return outcome;
		}
		return this.runInMemory(root.folder, steps, options);
	}

	private async runInMemory(root: URI, steps: readonly IActionStep[], options: IActionsRunOptions): Promise<IActionsOutcome> {
		const request: IActionsRunRequest = { projectRoot: root.fsPath, steps, overrides: this.overrides(root), write: false };
		const result = readBatchResult(await this.backend<unknown>(ACTIONS_RUN_COMMAND, request));
		if (!result.ok || !options.apply) {
			return { ...result, ran: false, applied: [] };
		}
		const applied = await this.applyChanges(root, result.changes);
		return { ...result, ran: false, applied };
	}

	/**
	 * The project the batch works on: the open one, or for creating a project the window's
	 * folder (the project then opens in this window as it appears). A window without a folder
	 * asks where to create it (`created`: a new subfolder named after the project, opened in the
	 * window afterwards); undefined when the engineer chose none.
	 */
	private async root(steps: readonly IActionStep[], write: boolean): Promise<{ readonly folder: URI; readonly created?: boolean } | undefined> {
		const project = this.projectService.project;
		if (project) {
			return { folder: project.root };
		}
		const folder = this.contextService.getWorkspace().folders[0]?.uri;
		const create = steps[0]?.action === PROJECT_CREATE_ACTION;
		if (create && folder) {
			return { folder };
		}
		if (!create) {
			throw new Error(localize('actions.noProject', "No SAEngine project is open in this window."));
		}
		if (!write) {
			throw new Error(localize('actions.createNeedsWrite', "project.create writes the new project: run it (not as a preview)."));
		}
		const name = typeof steps[0].params?.name === 'string' ? steps[0].params.name : '';
		const subfolder = projectFolderName(name);
		if (!/[\p{L}\p{N}]/u.test(subfolder)) {
			throw new Error(localize('actions.badName', "project.create needs a name with a letter or digit: the project's folder is named after it."));
		}
		const location = await this.chooseLocation();
		if (!location) {
			return undefined;
		}
		const target = joinPath(location, subfolder);
		if (await this.fileService.exists(target)) {
			const stat = await this.fileService.resolve(target);
			if (!stat.isDirectory || stat.children?.length) {
				throw new Error(localize('actions.folderTaken', "{0} exists already and is not empty: choose another location or name for the project.", target.fsPath));
			}
		}
		return { folder: target, created: true };
	}

	/** Asks where to create a new project: the folder picker opens at Documents/SAEngine Projects (or the nearest folder that exists). */
	private async chooseLocation(): Promise<URI | undefined> {
		const home = await this.pathService.userHome();
		// The first that exists; else the home folder.
		let start = home;
		for (const candidate of [joinPath(home, ...DEFAULT_PROJECTS_FOLDER), joinPath(home, DEFAULT_PROJECTS_FOLDER[0])]) {
			if (await this.fileService.exists(candidate)) {
				start = candidate;
				break;
			}
		}
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('actions.chooseLocation', "Choose Where to Create the Project"),
			canSelectFolders: true,
			canSelectFiles: false,
			canSelectMany: false,
			defaultUri: start,
		});
		return picked?.[0];
	}

	/** The unsaved texts of the project's files, by path relative to the project (the engine's overrides). */
	private overrides(root: URI): { [path: string]: string } {
		const overrides: { [path: string]: string } = {};
		for (const model of this.textFileService.files.models) {
			if (!model.isDirty() || !extUriBiasedIgnorePathCase.isEqualOrParent(model.resource, root)) {
				continue;
			}
			const path = extUriBiasedIgnorePathCase.relativePath(root, model.resource);
			if (path) {
				overrides[path] = model.textEditorModel.getValue();
			}
		}
		return overrides;
	}

	/**
	 * A batch with a step that writes: the project is saved (the engine reads the files, as Run
	 * All does), the engine runs and writes, and the files it changed are read again. Cancel on
	 * the progress (or `token`) stops it before its next step (`actions/cancel`).
	 */
	private async runWritten(root: URI, steps: readonly IActionStep[], token: CancellationToken): Promise<IActionsOutcome> {
		const stop = new CancellationTokenSource(token);
		let running = false;
		const listener = stop.token.onCancellationRequested(() => {
			if (running) {
				// The engine stops at its next step boundary and answers what was done.
				this.backend<unknown>(ACTIONS_CANCEL_COMMAND, {}).catch(() => undefined);
			}
		});
		try {
			return await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('actions.running', "Running {0}", stepNames(steps)),
				cancellable: localize('actions.stop', "Stop"),
			}, () => this.writeAndRun(root, steps, stop.token, () => running = true), () => stop.cancel());
		} finally {
			listener.dispose();
			stop.dispose();
		}
	}

	private async writeAndRun(root: URI, steps: readonly IActionStep[], token: CancellationToken, started: () => void): Promise<IActionsOutcome> {
		await this.saveProject(root);
		if (token.isCancellationRequested) {
			const results = [{ ok: false, message: localize('actions.stoppedBefore', "Stopped before it started: nothing was run."), created: [], warnings: [], problems: [], written: [] }];
			return { ok: false, results, changes: {}, failedStep: 0, written: [], cancelled: true, ran: false, applied: [] };
		}
		started();
		const request: IActionsRunRequest = { projectRoot: root.fsPath, steps, write: true };
		const result = readBatchResult(await this.backend<unknown>(ACTIONS_RUN_COMMAND, request));
		// What the engine wrote, even for a failed batch (a run step writes the steps before it first).
		const applied: string[] = [];
		for (const path of new Set([...Object.keys(result.changes), ...result.written])) {
			const segments = insideProject(path);
			const model = segments && this.textFileService.files.get(joinPath(root, ...segments));
			// Saved before the run, so nothing of the engineer's is lost by reading the file again.
			if (model && !model.isDirty()) {
				await model.resolve({ forceReadFromFile: true });
				applied.push(segments.join('/'));
			}
		}
		return { ...result, ran: true, applied };
	}

	private async saveProject(root: URI): Promise<void> {
		for (const model of this.textFileService.files.models) {
			if (model.isDirty() && extUriBiasedIgnorePathCase.isEqualOrParent(model.resource, root)) {
				await this.textFileService.save(model.resource);
			}
		}
	}

	/**
	 * The engine's new texts into the part files' text models, as one undo step: unsaved until the
	 * engineer saves, shown at once in every editor and shared by live co-editing. Every model is
	 * resolved before any is changed, so a file that cannot be opened changes nothing. A file the
	 * project does not have yet is written as it is (there is nothing to undo to).
	 */
	private async applyChanges(root: URI, changes: { readonly [path: string]: string }): Promise<string[]> {
		const existing: { path: string; model: ITextModel; text: string }[] = [];
		const created: { path: string; resource: URI; text: string }[] = [];
		for (const [path, text] of Object.entries(changes)) {
			const segments = insideProject(path);
			if (!segments) {
				throw new Error(localize('actions.outside', "The engine changed {0}, which is not a file of the project; nothing was applied.", path));
			}
			const resource = joinPath(root, ...segments);
			if (this.references.has(resource) || this.textFileService.files.get(resource) || await this.fileService.exists(resource)) {
				existing.push({ path: segments.join('/'), model: (await this.model(resource)).textEditorModel, text });
			} else {
				created.push({ path: segments.join('/'), resource, text });
			}
		}
		for (const file of created) {
			await this.fileService.writeFile(file.resource, VSBuffer.fromString(file.text));
		}
		const changed = new Set(applyTextsAsOneStep(existing));
		return [...existing.filter(e => changed.has(e.model)).map(e => e.path), ...created.map(c => c.path)];
	}

	private async model(resource: URI): Promise<IResolvedTextEditorModel> {
		let reference = this.references.get(resource);
		if (!reference) {
			reference = await this.textModelService.createModelReference(resource);
			this.references.set(resource, reference);
		}
		return reference.object;
	}

	private async backend<T>(command: string, args: object): Promise<T> {
		if (!CommandsRegistry.getCommand(command)) {
			throw new Error(localize('actions.noEngine', "The SAEngine engine is not available in this window."));
		}
		return await this.commandService.executeCommand<T>(command, args) as T;
	}

	private releaseAll(): void {
		for (const reference of this.references.values()) {
			reference.dispose();
		}
		this.references.clear();
	}

	override dispose(): void {
		this.releaseAll();
		super.dispose();
	}
}

registerSingleton(ISaengineActionsService, SaengineActionsService, InstantiationType.Delayed);
