/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { DeferredPromise } from '../../../../base/common/async.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, IReference } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { generateUuid } from '../../../../base/common/uuid.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { applyTextsAsOneStep } from '../../../services/saengineProject/browser/saengineActionsService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { changesByFile, diffJson, IAiChangeSetProposal, IPlannedFile, planFile } from '../common/aiChangeSet.js';
import { safeRelativePath } from '../common/aiTools.js';

/*
 * The change sets AI assistants propose (the built-in assistant and MCP clients alike): planned
 * against the documents as the engineer sees them (unsaved edits included), shown in the
 * assistant's view for the engineer to accept or reject, and applied through the shared text
 * models in one undo group over every file, as the design proposal applies its bars. Undo in
 * the preview (or Ctrl+Z in any of the files) reverts the whole set.
 */

export type ChangeSetState = 'pending' | 'accepted' | 'rejected' | 'undone' | 'failed' | 'stale';

/** Who proposed it: the built-in assistant or an MCP client (named in AI Activity). */
export type ChangeSetSource = 'assistant' | 'mcp';

export interface IAiChangeSet {
	readonly id: string;
	readonly title: string;
	readonly source: ChangeSetSource;
	readonly files: readonly (IPlannedFile & { readonly resource: URI; readonly created?: boolean })[];
	/** What the set does in the engineer's words: each action's message, for a set of actions. */
	readonly summary?: readonly string[];
	readonly state: ChangeSetState;
	/** Why it failed or went stale. */
	readonly problem?: string;
	/** Settles once the engineer decides (accepted, rejected) or it can no longer be applied. */
	readonly decision: Promise<ChangeSetState>;
}

export const ISaengineAiChangeSetService = createDecorator<ISaengineAiChangeSetService>('saengineAiChangeSetService');

export interface ISaengineAiChangeSetService {
	readonly _serviceBrand: undefined;
	readonly changeSets: readonly IAiChangeSet[];
	readonly onDidChange: Event<IAiChangeSet | undefined>;
	/** Plans the proposal (throws with the problem when it cannot be applied) and shows it. */
	propose(proposal: IAiChangeSetProposal, source: ChangeSetSource): Promise<IAiChangeSet>;
	/**
	 * A set of whole new texts (a batch of actions the engine worked out, already checked by its
	 * guardrails), previewed value by value and applied like any other set.
	 */
	proposeTexts(proposal: IAiTextsProposal, source: ChangeSetSource): Promise<IAiChangeSet>;
	accept(id: string): Promise<void>;
	reject(id: string): void;
	undo(id: string): Promise<void>;
	canUndo(id: string): boolean;
	/** Drops the decided ones from the list. */
	clearDecided(): void;
}

/** New texts of project files (relative path -> text) with what they do. */
export interface IAiTextsProposal {
	readonly title: string;
	readonly texts: { readonly [file: string]: string };
	readonly summary?: readonly string[];
}

interface IChangeSetEntry {
	id: string;
	title: string;
	source: ChangeSetSource;
	files: (IPlannedFile & { readonly resource: URI; version: number; readonly created?: boolean })[];
	summary?: readonly string[];
	state: ChangeSetState;
	problem?: string;
	readonly deferred: DeferredPromise<ChangeSetState>;
	readonly decision: Promise<ChangeSetState>;
	/** After accept: each model's version, so Undo reverts only this set. */
	applied?: { readonly resource: URI; readonly version: number }[];
	/** After accept: the files the set created, with the text written, so Undo removes them again. */
	created?: { readonly resource: URI; readonly text: string }[];
}

/** The full check of the editors (`saengine.library.check`). */
const LIBRARY_CHECK_COMMAND = 'saengine.library.check';

/** The parts whose files the full check (and so the input guardrails) knows. */
const CHECKED_KINDS = new Set(['materials', 'objects', 'settings', 'floorPlan', 'structure', 'bim']);

/**
 * The errors the full check finds in `after` that `before` did not have, for a project file
 * (`file`, project-relative) of a part the check knows; empty for any other file, and when the
 * backend is not there (web).
 */
export async function refusedValues(commandService: ICommandService, file: string, before: string, after: string): Promise<string[]> {
	const part = PROJECT_PARTS.find(p => p.mainFile && `${p.folder}/${p.mainFile}` === file && CHECKED_KINDS.has(p.id));
	if (!part) {
		return [];
	}
	const errors = async (text: string) => {
		const problems = await commandService.executeCommand<readonly { message: string; path?: string; severity?: string }[]>(LIBRARY_CHECK_COMMAND, part.id, text).catch(() => undefined);
		return (problems ?? []).filter(p => (p.severity ?? 'error') === 'error').map(p => p.path ? `${p.path}: ${p.message}` : p.message);
	};
	const old = new Set(await errors(before));
	return (await errors(after)).filter(e => !old.has(e)).map(e => `${file}: ${e}`);
}

/** Most change sets kept in the list. */
const MAX_KEPT = 20;

export class SaengineAiChangeSetService extends Disposable implements ISaengineAiChangeSetService {

	declare readonly _serviceBrand: undefined;

	private readonly entries: IChangeSetEntry[] = [];
	private readonly references = new Map<string, IReference<IResolvedTextEditorModel>>();

	private readonly _onDidChange = this._register(new Emitter<IAiChangeSet | undefined>());
	readonly onDidChange = this._onDidChange.event;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IFileService private readonly fileService: IFileService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super();
		this._register(this.projectService.onDidChangeProject(() => {
			// Another project: the pending sets were planned on files that are gone.
			for (const entry of this.entries) {
				if (entry.state === 'pending') {
					this.settle(entry, 'stale', localize('changeSet.projectClosed', "The project was closed."));
				}
			}
			this.releaseAll();
		}));
	}

	get changeSets(): readonly IAiChangeSet[] {
		return this.entries;
	}

	async propose(proposal: IAiChangeSetProposal, source: ChangeSetSource): Promise<IAiChangeSet> {
		const project = this.projectService.project;
		if (!project) {
			throw new Error(localize('changeSet.noProject', "No project is open."));
		}
		const files: IChangeSetEntry['files'] = [];
		for (const changes of changesByFile(proposal.changes).values()) {
			const file = changes[0].file;
			const resource = joinPath(project.root, ...file.split('/'));
			if (!await this.fileService.exists(resource)) {
				throw new Error(localize('changeSet.noFile', "The project has no file {0}.", file));
			}
			const model = (await this.model(resource)).textEditorModel;
			const options = model.getOptions();
			const planned = planFile(file, model.getValue(), changes, { tabSize: options.tabSize, insertSpaces: options.insertSpaces, eol: model.getEOL() });
			files.push({ ...planned, resource, version: model.getAlternativeVersionId() });
		}
		if (files.every(file => file.changes.every(change => change.noop))) {
			throw new Error(localize('changeSet.noop', "Every change already holds: nothing to propose."));
		}
		await this.checkGuardrails(files);
		return this.add(proposal.title, source, files);
	}

	async proposeTexts(proposal: IAiTextsProposal, source: ChangeSetSource): Promise<IAiChangeSet> {
		const project = this.projectService.project;
		if (!project) {
			throw new Error(localize('changeSet.noProject', "No project is open."));
		}
		const files: IChangeSetEntry['files'] = [];
		for (const [path, newText] of Object.entries(proposal.texts)) {
			const file = safeRelativePath(path);
			if (!file) {
				throw new Error(localize('changeSet.outside', "{0} is not a file of the project.", path));
			}
			const resource = joinPath(project.root, ...file.split('/'));
			let after: unknown;
			try {
				after = JSON.parse(newText);
			} catch {
				throw new Error(localize('changeSet.notJson', "The new text of {0} is not JSON.", file));
			}
			if (!await this.fileService.exists(resource)) {
				// A file the project does not have yet: written as it is on accept.
				files.push({ file, newText, resource, version: 0, created: true, changes: [{ change: { file, path: [file], value: after }, before: undefined, existed: false, after, noop: false }] });
				continue;
			}
			const model = (await this.model(resource)).textEditorModel;
			const text = model.getValue();
			let before: unknown;
			try {
				before = JSON.parse(text);
			} catch {
				throw new Error(localize('changeSet.invalidNow', "{0} is not valid JSON now; fix it first.", file));
			}
			const options = model.getOptions();
			// The values before and after, for the preview (and to plan again on a newer document).
			const planned = planFile(file, text, diffJson(file, before, after), { tabSize: options.tabSize, insertSpaces: options.insertSpaces, eol: model.getEOL() });
			if (planned.changes.length) {
				// Applied as the engine formatted it while the document stays as it was planned on.
				files.push({ ...planned, newText, resource, version: model.getAlternativeVersionId() });
			}
		}
		if (!files.length) {
			throw new Error(localize('changeSet.noop', "Every change already holds: nothing to propose."));
		}
		return this.add(proposal.title, source, files, proposal.summary);
	}

	private add(title: string, source: ChangeSetSource, files: IChangeSetEntry['files'], summary?: readonly string[]): IAiChangeSet {
		const deferred = new DeferredPromise<ChangeSetState>();
		const entry: IChangeSetEntry = { id: generateUuid(), title, source, files, summary, state: 'pending', deferred, decision: deferred.p };
		this.entries.unshift(entry);
		while (this.entries.length > MAX_KEPT) {
			const dropped = this.entries.pop()!;
			if (dropped.state === 'pending') {
				this.settle(dropped, 'stale', undefined, false);
			}
		}
		this._onDidChange.fire(entry);
		return entry;
	}

	/**
	 * U2: the assistant's values meet the same rules as the engineer's. Each project file the set
	 * changes is checked as the editors check it (`saengine.library.check`, the input guardrails
	 * among its rules); an error the file did not have before refuses the whole set, with the
	 * reason, so the assistant can correct it ({@link refusedValues}).
	 */
	private async checkGuardrails(files: readonly (IPlannedFile & { readonly resource: URI })[]): Promise<void> {
		const refused: string[] = [];
		for (const file of files) {
			const before = (await this.model(file.resource)).textEditorModel.getValue();
			refused.push(...await refusedValues(this.commandService, file.file, before, file.newText));
		}
		if (refused.length) {
			throw new Error(localize('changeSet.guardrails', "SAEngine refuses these values (the same rules as for the engineer): {0}", refused.slice(0, 10).join('; ')));
		}
	}

	async accept(id: string): Promise<void> {
		const entry = this.entries.find(e => e.id === id);
		if (!entry || entry.state !== 'pending') {
			return;
		}
		try {
			// The documents may have changed since the proposal: plan again on what is there now.
			const texts: { model: ITextModel; text: string }[] = [];
			const created: { resource: URI; text: string }[] = [];
			for (const file of entry.files) {
				if (file.created) {
					if (await this.fileService.exists(file.resource)) {
						throw new Error(localize('changeSet.fileAppeared', "{0} was created meanwhile; ask again.", file.file));
					}
					created.push({ resource: file.resource, text: file.newText });
					continue;
				}
				const model = (await this.model(file.resource)).textEditorModel;
				let text = file.newText;
				if (model.getAlternativeVersionId() !== file.version) {
					const options = model.getOptions();
					text = planFile(file.file, model.getValue(), file.changes.map(c => c.change), { tabSize: options.tabSize, insertSpaces: options.insertSpaces, eol: model.getEOL() }).newText;
				}
				texts.push({ model, text });
			}
			for (const file of created) {
				await this.fileService.writeFile(file.resource, VSBuffer.fromString(file.text));
			}
			entry.created = created;
			// One undo step over every file, each as its one small edit (co-editing shares it).
			entry.applied = applyTextsAsOneStep(texts).map(model => ({ resource: model.uri, version: model.getAlternativeVersionId() }));
			this.settle(entry, 'accepted');
		} catch (error) {
			this.settle(entry, 'failed', localize('changeSet.failed', "The change set could not be applied: {0}", error instanceof Error ? error.message : String(error)));
		}
	}

	reject(id: string): void {
		const entry = this.entries.find(e => e.id === id);
		if (entry?.state === 'pending') {
			this.settle(entry, 'rejected');
		}
	}

	canUndo(id: string): boolean {
		const entry = this.entries.find(e => e.id === id);
		if (!entry || entry.state !== 'accepted' || (!entry.applied?.length && !entry.created?.length)) {
			return false;
		}
		return (entry.applied ?? []).every(file => {
			const reference = this.references.get(file.resource.toString());
			return reference?.object.textEditorModel.getAlternativeVersionId() === file.version && this.undoRedoService.canUndo(file.resource);
		});
	}

	async undo(id: string): Promise<void> {
		const entry = this.entries.find(e => e.id === id);
		if (!entry || !this.canUndo(id)) {
			return;
		}
		// The files the set created go too, unless they were changed since (then they stay, and say so).
		const created = entry.created ?? [];
		const changed: string[] = [];
		for (const file of created) {
			const model = this.references.get(file.resource.toString())?.object.textEditorModel;
			const now = model ? model.getValue() : await this.fileService.readFile(file.resource).then(content => content.value.toString(), () => undefined);
			if (now !== undefined && now !== file.text) {
				changed.push(file.resource.path);
			}
		}
		if (changed.length) {
			entry.problem = localize('changeSet.createdChanged', "Not undone: {0} changed since the set created it.", changed.join(', '));
			this._onDidChange.fire(entry);
			return;
		}
		if (entry.applied?.length) {
			// One undo: the group reverts the other files too.
			await this.undoRedoService.undo(entry.applied[0].resource);
		}
		for (const file of created) {
			if (await this.fileService.exists(file.resource)) {
				// To the recycle bin where there is one: removing a file is not undoable otherwise.
				await this.fileService.del(file.resource, { useTrash: true }).catch(() => this.fileService.del(file.resource));
			}
		}
		entry.state = 'undone';
		this._onDidChange.fire(entry);
	}

	clearDecided(): void {
		for (let i = this.entries.length - 1; i >= 0; i--) {
			if (this.entries[i].state !== 'pending') {
				this.entries.splice(i, 1);
			}
		}
		this._onDidChange.fire(undefined);
	}

	private settle(entry: IChangeSetEntry, state: ChangeSetState, problem?: string, fire = true): void {
		entry.state = state;
		entry.problem = problem;
		entry.deferred.complete(state);
		if (fire) {
			this._onDidChange.fire(entry);
		}
	}

	private async model(resource: URI): Promise<IResolvedTextEditorModel> {
		const key = resource.toString();
		let reference = this.references.get(key);
		if (!reference) {
			reference = await this.textModelService.createModelReference(resource);
			this.references.set(key, reference);
		}
		return reference.object;
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
