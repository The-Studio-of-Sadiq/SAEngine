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
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { IUndoRedoService, UndoRedoGroup } from '../../../../platform/undoRedo/common/undoRedo.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { changesByFile, IAiChangeSetProposal, IPlannedFile, planFile } from '../common/aiChangeSet.js';

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
	readonly files: readonly (IPlannedFile & { readonly resource: URI })[];
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
	accept(id: string): Promise<void>;
	reject(id: string): void;
	undo(id: string): Promise<void>;
	canUndo(id: string): boolean;
	/** Drops the decided ones from the list. */
	clearDecided(): void;
}

interface IChangeSetEntry {
	id: string;
	title: string;
	source: ChangeSetSource;
	files: (IPlannedFile & { readonly resource: URI; version: number })[];
	state: ChangeSetState;
	problem?: string;
	readonly deferred: DeferredPromise<ChangeSetState>;
	readonly decision: Promise<ChangeSetState>;
	/** After accept: each model's version, so Undo reverts only this set. */
	applied?: { readonly resource: URI; readonly version: number }[];
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
		const deferred = new DeferredPromise<ChangeSetState>();
		const entry: IChangeSetEntry = { id: generateUuid(), title: proposal.title, source, files, state: 'pending', deferred, decision: deferred.p };
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

	async accept(id: string): Promise<void> {
		const entry = this.entries.find(e => e.id === id);
		if (!entry || entry.state !== 'pending') {
			return;
		}
		try {
			// The documents may have changed since the proposal: plan again on what is there now.
			const texts: { resource: URI; text: string }[] = [];
			for (const file of entry.files) {
				const model = (await this.model(file.resource)).textEditorModel;
				let text = file.newText;
				if (model.getAlternativeVersionId() !== file.version) {
					const options = model.getOptions();
					text = planFile(file.file, model.getValue(), file.changes.map(c => c.change), { tabSize: options.tabSize, insertSpaces: options.insertSpaces, eol: model.getEOL() }).newText;
				}
				texts.push({ resource: file.resource, text });
			}
			const group = new UndoRedoGroup();
			const applied: { resource: URI; version: number }[] = [];
			for (const { resource, text } of texts) {
				const model = (await this.model(resource)).textEditorModel;
				if (model.getValue() === text) {
					continue;
				}
				model.pushStackElement();
				model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null, group);
				model.pushStackElement();
				applied.push({ resource, version: model.getAlternativeVersionId() });
			}
			entry.applied = applied;
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
		if (!entry || entry.state !== 'accepted' || !entry.applied?.length) {
			return false;
		}
		return entry.applied.every(file => {
			const reference = this.references.get(file.resource.toString());
			return reference?.object.textEditorModel.getAlternativeVersionId() === file.version && this.undoRedoService.canUndo(file.resource);
		});
	}

	async undo(id: string): Promise<void> {
		const entry = this.entries.find(e => e.id === id);
		if (!entry || !this.canUndo(id)) {
			return;
		}
		// One undo: the group reverts the other files too.
		await this.undoRedoService.undo(entry.applied![0].resource);
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
