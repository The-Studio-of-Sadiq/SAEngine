/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/libraryEditor.css';
import { $, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { recordedStamp, sourceStamp, upstreamPart } from '../../../services/saengineProject/common/partSources.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { LibraryEditorInput, LibraryKind } from './libraryEditorInput.js';
import { JsonObject, JsonValue } from './schemaForm.js';

/** A rule violation found by the Python models (see `saengine.library.check`). */
export interface IDocumentProblem {
	/** Entry the problem belongs to, by index in the document's list; null for the whole file. */
	readonly index: number | null;
	readonly path: string;
	readonly message: string;
}

/** Desktop command running the full model rules; absent where there is no Python backend. */
const CHECK_COMMAND = 'saengine.library.check';

/** The other project file each document needs for references and checks. */
const COMPANION_PART: { readonly [kind in LibraryKind]?: string } = {
	objects: 'materials',
	floorPlan: 'objects',
	structure: 'objects',
	bim: 'objects',
};

/** Names of the parts a document can be built from, for the "changed since" banner. */
const UPSTREAM_NAMES: { readonly [part: string]: string } = {
	floorPlan: localize('upstream.floorPlan', "Floor Plan"),
	structure: localize('upstream.structure', "Structural Model"),
};

export function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value));
}

export function isObject(value: JsonValue | undefined): value is JsonObject {
	return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** Why a parsed file cannot be edited visually, and optionally how to fix it. */
export interface IShapeError {
	readonly message: string;
	readonly fix?: { readonly label: string; readonly run: () => void };
}

/**
 * Base for the visual editors of SAEngine's JSON project files. The file's text model stays
 * the document: the editor parses it, edits a copy, and writes it back as one undoable edit
 * only when the edit is valid, so Save, Undo/Redo, dirty state and hot exit come from the
 * text file service. After each change the Python models check the whole file.
 *
 * A document built from upstream parts (see `upstreamPart`) records their stamps; when an
 * upstream file changes, the editor says so and offers to update, and only updates on request.
 */
export abstract class JsonDocumentEditor extends EditorPane {

	protected root!: HTMLElement;
	private banner!: HTMLElement;
	private outdated!: HTMLElement;

	protected document: JsonObject | undefined;
	protected problems: readonly IDocumentProblem[] = [];
	private model: ITextModel | undefined;
	private applying = false;

	protected readonly inputDisposables = this._register(new DisposableStore());
	protected readonly viewDisposables = this._register(new DisposableStore());
	private readonly bannerDisposables = this._register(new DisposableStore());
	private readonly outdatedDisposables = this._register(new DisposableStore());
	private readonly companionReference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly upstreamReference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 300));
	private readonly checkScheduler = this._register(new RunOnceScheduler(() => this.check(), 600));
	private checkVersion = 0;

	constructor(
		id: string,
		group: IEditorGroup,
		telemetryService: ITelemetryService,
		themeService: IThemeService,
		storageService: IStorageService,
		private readonly commandService: ICommandService,
		private readonly editorService: IEditorService,
		private readonly textModelService: ITextModelService,
		private readonly projectService: ISaengineProjectService,
	) {
		super(id, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.root = append(parent, $('.saengine-library-editor'));
		this.banner = append(this.root, $('.library-banner'));
		this.outdated = append(this.root, $('.library-banner.outdated'));
		this.createBody(append(this.root, $('.library-body')));
	}

	/** Builds the editor's own UI below the banner. */
	protected abstract createBody(container: HTMLElement): void;

	/** Why `value` is not a document this editor can edit, if it is not. */
	protected abstract shapeError(value: JsonObject): IShapeError | undefined;

	/** Renders the whole document (after load or a structural change). */
	protected abstract render(): void;

	/** Shows `problems` without rebuilding forms, so typing keeps its focus. */
	protected abstract renderProblems(): void;

	/** The companion file's text changed (also called once when it is first read). */
	protected onCompanionChanged(_text: string): void { }

	/** Rebuilds the document from its upstream part, when the engineer asks to update. */
	protected updateFromUpstream(_upstreamText: string): void { }

	/** The current text of the upstream part the document is built from, if it has one. */
	protected get upstreamText(): string | undefined {
		return this.upstreamReference.value?.object.textEditorModel.getValue();
	}

	protected get kind(): LibraryKind | undefined {
		return (this.input as LibraryEditorInput | undefined)?.kind;
	}

	/** The file's resource, for undo/redo. */
	get resource() {
		return (this.input as LibraryEditorInput | undefined)?.resource;
	}

	override async setInput(input: LibraryEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.companionReference.clear();
		this.upstreamReference.clear();

		const reference = await input.resolve();
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
		this.model = reference.object.textEditorModel;
		this.inputDisposables.add(this.model.onDidChangeContent(() => {
			if (!this.applying) {
				this.load(); // undo/redo, revert, external edits
			}
		}));
		await this.trackCompanion(input.kind);
		await this.trackUpstream(input.kind);
		this.onWillLoadInput();
		this.load();
		this.applyOptions(options);
	}

	override setOptions(options: IEditorOptions | undefined): void {
		super.setOptions(options);
		this.applyOptions(options);
	}

	/** Applies editor options (e.g. revealing an entry) after the document is shown. */
	protected applyOptions(_options: IEditorOptions | undefined): void { }

	/** Resets per-input view state before the first load. */
	protected onWillLoadInput(): void { }

	override clearInput(): void {
		this.flush();
		this.inputDisposables.clear();
		this.companionReference.clear();
		this.upstreamReference.clear();
		this.model = undefined;
		this.document = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.root.style.width = `${dimension.width}px`;
		this.root.style.height = `${dimension.height}px`;
	}

	override dispose(): void {
		this.flush();
		super.dispose();
	}

	// ───────────────────────────── document ─────────────────────────────

	protected load(): void {
		if (!this.model) {
			return;
		}
		let parsed: JsonValue;
		try {
			parsed = JSON.parse(this.model.getValue());
		} catch (error) {
			this.showDocumentError({ message: localize('jsonDocument.invalidJson', "This file contains invalid JSON ({0}). Fix it in the text editor; the visual editor will not change it until then.", String(error)) });
			return;
		}
		const shapeError = isObject(parsed) ? this.shapeError(parsed) : { message: localize('jsonDocument.notObject', "This file does not contain a JSON object.") };
		if (shapeError) {
			this.showDocumentError(shapeError);
			return;
		}
		this.showBanner(undefined);
		this.document = parsed as JsonObject;
		this.render();
		this.renderOutdated();
		this.checkScheduler.schedule();
	}

	private showDocumentError(error: IShapeError): void {
		this.document = undefined;
		this.problems = [];
		this.showBanner(error);
		this.render();
		this.renderOutdated();
	}

	/** Writes the document to the text model as one undoable edit. */
	protected commit(): void {
		this.commitScheduler.cancel();
		if (!this.model || !this.document || this.model.isDisposed()) {
			return;
		}
		const text = JSON.stringify(this.document, undefined, '\t') + '\n';
		if (text === this.model.getValue()) {
			return;
		}
		this.applying = true;
		try {
			this.model.pushStackElement();
			this.model.pushEditOperations([], [{ range: this.model.getFullModelRange(), text }], () => null);
			this.model.pushStackElement();
		} finally {
			this.applying = false;
		}
		this.checkScheduler.schedule();
	}

	/** Replaces the whole document (one undoable edit) and shows it. */
	protected replaceDocument(value: JsonObject): void {
		this.document = value;
		this.showBanner(undefined);
		this.commit();
		this.render();
		this.renderOutdated();
	}

	protected flush(): void {
		if (this.commitScheduler.isScheduled()) {
			this.commit();
		}
	}

	/** Called after the document was edited in place: structural edits re-render and save at once, typing is batched. */
	protected changed(structural: boolean): void {
		if (structural) {
			this.commit();
			this.render();
		} else {
			this.commitScheduler.schedule();
		}
	}

	private async check(): Promise<void> {
		const kind = this.kind;
		const input = this.input;
		if (!this.model || !kind || !this.document) {
			return;
		}
		const version = ++this.checkVersion;
		const companionText = this.companionReference.value?.object.textEditorModel.getValue();
		let problems: readonly IDocumentProblem[] = [];
		try {
			problems = await this.commandService.executeCommand<readonly IDocumentProblem[]>(CHECK_COMMAND, kind, this.model.getValue(), companionText) ?? [];
		} catch {
			// No backend (web) or Python is not set up: the schema checks while typing still apply.
		}
		if (version !== this.checkVersion || this.input !== input) {
			return; // a newer check is on its way
		}
		this.problems = problems;
		this.renderProblems();
	}

	/** Follows the companion file (unsaved edits included) for references and checks. */
	private async trackCompanion(kind: LibraryKind): Promise<void> {
		const project = this.projectService.project;
		const part = partById(COMPANION_PART[kind] ?? '');
		if (!project || !part?.mainFile) {
			return;
		}
		try {
			this.companionReference.value = await this.textModelService.createModelReference(joinPath(project.root, part.folder, part.mainFile));
		} catch {
			return;
		}
		const model = this.companionReference.value.object.textEditorModel;
		this.onCompanionChanged(model.getValue());
		this.inputDisposables.add(model.onDidChangeContent(() => {
			this.onCompanionChanged(model.getValue());
			this.checkScheduler.schedule();
		}));
	}

	/** Follows the upstream part the document is built from (unsaved edits included). */
	private async trackUpstream(kind: LibraryKind): Promise<void> {
		const project = this.projectService.project;
		const part = partById(upstreamPart(kind, this.projectService.parts) ?? '');
		if (!project || !part?.mainFile) {
			return;
		}
		try {
			this.upstreamReference.value = await this.textModelService.createModelReference(joinPath(project.root, part.folder, part.mainFile));
		} catch {
			return;
		}
		this.inputDisposables.add(this.upstreamReference.value.object.textEditorModel.onDidChangeContent(() => this.renderOutdated()));
	}

	/** "<Upstream> changed since this was built — Update", while the recorded stamp is stale. */
	private renderOutdated(): void {
		this.outdatedDisposables.clear();
		clearNode(this.outdated);
		const part = this.kind && upstreamPart(this.kind, this.projectService.parts);
		const text = this.upstreamText;
		const recorded = this.document && part ? recordedStamp(this.document, part) : undefined;
		const stale = !!this.document && !!part && text !== undefined && recorded !== sourceStamp(text);
		this.outdated.classList.toggle('visible', stale);
		if (!stale || !part || text === undefined) {
			return;
		}
		const name = UPSTREAM_NAMES[part] ?? part;
		append(this.outdated, $('span', undefined, recorded
			? localize('outdated.changed', "The {0} has changed since this was built from it.", name)
			: localize('outdated.never', "This has not been built from the {0} yet.", name)));
		const update = this.outdatedDisposables.add(new Button(this.outdated, defaultButtonStyles));
		update.label = localize('outdated.update', "Update from {0}", name);
		this.outdatedDisposables.add(update.onDidClick(() => this.updateFromUpstream(this.upstreamText ?? text)));
	}

	// ───────────────────────────── banner ─────────────────────────────

	private showBanner(error: IShapeError | undefined): void {
		this.bannerDisposables.clear();
		clearNode(this.banner);
		this.banner.classList.toggle('visible', !!error);
		if (!error) {
			return;
		}
		append(this.banner, $('span', undefined, error.message));
		if (error.fix) {
			const fix = this.bannerDisposables.add(new Button(this.banner, defaultButtonStyles));
			fix.label = error.fix.label;
			this.bannerDisposables.add(fix.onDidClick(() => error.fix!.run()));
		}
		const text = this.bannerDisposables.add(new Button(this.banner, { ...defaultButtonStyles, secondary: true }));
		text.label = localize('jsonDocument.openText', "Open in Text Editor");
		this.bannerDisposables.add(text.onDidClick(() => this.openAsText()));
	}

	private openAsText(): void {
		const resource = this.resource;
		if (resource) {
			void this.editorService.openEditor({ resource, options: { override: DEFAULT_EDITOR_ASSOCIATION.id } }, this.group);
		}
	}
}
