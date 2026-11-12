/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
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
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { ITextFileService } from '../../textfile/common/textfiles.js';
import { ACTIONS_LIST_COMMAND, ACTIONS_RUN_COMMAND, ActionKind, IActionInfo, IActionStep, IActionsOutcome, IActionsRunOptions, IActionsRunRequest, ISaengineActionsService, minimalEdit, PROJECT_CREATE_ACTION, readBatchResult, readCatalogue, stepNames, stepNeedsWrite } from '../common/saengineActions.js';
import { ISaengineProjectService } from '../common/saengineProject.js';

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

	async run(steps: readonly IActionStep[], options: IActionsRunOptions): Promise<IActionsOutcome> {
		if (!steps.length) {
			throw new Error(localize('actions.noSteps', "The batch has no steps."));
		}
		const root = this.root(steps);
		const write = await this.needsWrite(steps);
		if (write && options.apply) {
			return this.runWritten(root, steps);
		}
		const request: IActionsRunRequest = { projectRoot: root.fsPath, steps, overrides: this.overrides(root), write: false };
		const result = readBatchResult(await this.backend<unknown>(ACTIONS_RUN_COMMAND, request));
		if (!result.ok || !options.apply) {
			return { ...result, ran: false, applied: [] };
		}
		const applied = await this.applyChanges(root, result.changes);
		return { ...result, ran: false, applied };
	}

	/**
	 * The project the batch works on: the open one, or for creating a project the window's empty
	 * folder (the project then opens in this window as it appears).
	 */
	private root(steps: readonly IActionStep[]): URI {
		const project = this.projectService.project;
		if (project) {
			return project.root;
		}
		const folder = this.contextService.getWorkspace().folders[0]?.uri;
		if (steps[0]?.action === PROJECT_CREATE_ACTION && folder) {
			return folder;
		}
		throw new Error(steps[0]?.action === PROJECT_CREATE_ACTION
			? localize('actions.noFolder', "Open an empty folder first (File > Open Folder): the project is created in it.")
			: localize('actions.noProject', "No SAEngine project is open in this window."));
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
	 * A batch with a run step: the project is saved (the engine reads the files, as Run All
	 * does), the engine runs and writes, and the files it changed are read again.
	 */
	private async runWritten(root: URI, steps: readonly IActionStep[]): Promise<IActionsOutcome> {
		return this.progressService.withProgress({
			location: ProgressLocation.Notification,
			title: localize('actions.running', "Running {0}", stepNames(steps)),
		}, async () => {
			await this.saveProject(root);
			const request: IActionsRunRequest = { projectRoot: root.fsPath, steps, write: true };
			const result = readBatchResult(await this.backend<unknown>(ACTIONS_RUN_COMMAND, request));
			if (!result.ok) {
				return { ...result, ran: true, applied: [] };
			}
			const applied: string[] = [];
			for (const path of Object.keys(result.changes)) {
				const segments = insideProject(path);
				const model = segments && this.textFileService.files.get(joinPath(root, ...segments));
				// Saved before the run, so nothing of the engineer's is lost by reading the file again.
				if (model && !model.isDirty()) {
					await model.resolve({ forceReadFromFile: true });
					applied.push(segments.join('/'));
				}
			}
			return { ...result, ran: true, applied };
		});
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
