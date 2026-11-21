/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi } from '@saengine/cad-editor';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow, isEditableElement } from '../../../../base/browser/dom.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IContextKey, IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { DraftActiveContext } from '../../saengineRibbon/browser/ribbonRegistry.js';
import { CAD_COMMAND_LINE_STORAGE_KEY, ICadEditorPane, notifyActiveCadEditorChanged } from './activeCadEditor.js';
import { dockCadCommandLine } from './cadCommandLineDock.js';
import { acquireCadEditor, cadBackground, releaseCadEditor } from './cadHost.js';
import { CadEditorInput } from './cadEditorInput.js';
import { FloorPlanCadBar } from './floorPlanCadBar.js';

/**
 * The 2D CAD editor for DXF drawings, built on mlightcad. The pane holds the window's one
 * mlightcad editor only while it shows a drawing; unsaved changes stay with the input when
 * another editor takes the pane.
 */
export class CadEditorPane extends EditorPane implements ICadEditorPane {

	private container!: HTMLElement;
	private host!: HTMLElement;
	private message!: HTMLElement;
	private cadBar!: FloorPlanCadBar;
	private editor: CadEditorApi | undefined;
	private _scopedContextKeyService: IContextKeyService | undefined;
	private draftActiveContext: IContextKey<boolean> | undefined;
	private readonly viewStorage: IStorageService;
	private readonly inputDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IFileService private readonly fileService: IFileService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IContextKeyService private readonly contextKeyService: IContextKeyService,
	) {
		super(CadEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
		this.viewStorage = storageService;
	}

	override get scopedContextKeyService(): IContextKeyService | undefined {
		return this._scopedContextKeyService;
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.saengine-cad-editor'));
		this.container.tabIndex = -1;
		this._scopedContextKeyService = this._register(this.contextKeyService.createScoped(this.container));
		this.draftActiveContext = DraftActiveContext.bindTo(this._scopedContextKeyService);

		this.host = append(this.container, $('.cad-host'));
		this.message = append(this.container, $('.cad-message'));
		this.cadBar = this._register(this.instantiationService.createInstance(FloorPlanCadBar, this.container));

		this._register(addDisposableListener(this.host, EventType.POINTER_MOVE, e => {
			if (!this.editor) {
				return;
			}
			try {
				this.cadBar.setCursor(this.editor.toWorld(e.clientX, e.clientY));
			} catch {
				// Ignore cursor queries before drawing view initializes.
			}
		}));
		this._register(addDisposableListener(this.host, EventType.POINTER_LEAVE, () => {
			this.cadBar.setCursor(undefined);
		}));
		this._register(addDisposableListener(this.container, EventType.KEY_DOWN, e => {
			if (isEditableElement(e.target as HTMLElement)) {
				return;
			}
			if (e.key === ':') {
				e.preventDefault();
				e.stopPropagation();
				this.toggleCadCommandLine();
			}
		}));
	}

	override async setInput(input: CadEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		this.stashAndRelease();
		await super.setInput(input, options, context, token);
		this.showMessage(undefined);

		let editor: CadEditorApi;
		try {
			const showCommandLine = this.viewStorage.getBoolean(CAD_COMMAND_LINE_STORAGE_KEY, StorageScope.WORKSPACE, true);
			editor = this.editor = await acquireCadEditor(this.host, {
				chrome: { commandLine: showCommandLine, shortcutToolbar: false },
				background: cadBackground(this.themeService.getColorTheme()),
			});
		} catch (error) {
			this.showMessage(localize('cad.loadFailed', "The CAD editor could not start: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			this.stashAndRelease();
			return;
		}

		this.inputDisposables.add(dockCadCommandLine(this.host));
		this.inputDisposables.add(toDisposable(editor.onDidChangeChrome(() => {
			this.viewStorage.store(CAD_COMMAND_LINE_STORAGE_KEY, editor.getChrome().commandLine, StorageScope.WORKSPACE, StorageTarget.MACHINE);
		})));
		this.cadBar.setEditor(editor);

		const load = async (fromDisk: boolean) => {
			const content = (!fromDisk && input.unsavedDxf) || (await this.fileService.readFile(input.resource)).value.toString();
			const opened = content.trim() ? await editor.openDxf(input.getName(), content) : await editor.newDrawing();
			if (!opened) {
				this.showMessage(localize('cad.openFailed', "{0} could not be opened as a DXF drawing.", input.getName()));
			}
		};
		await load(false);
		this.cadBar.updateProperties();
		this.draftActiveContext?.set(true);
		notifyActiveCadEditorChanged(editor);

		input.unsavedDxf = undefined;
		input.source = { toDxf: () => editor.toDxf(), reload: () => load(true) };
		this.inputDisposables.add(toDisposable(() => input.source = undefined));
		this.inputDisposables.add(toDisposable(editor.onDidChange(() => input.setDirty(true))));
	}

	override clearInput(): void {
		this.stashAndRelease();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
		this.cadBar.layout(dimension.width);
	}

	override focus(): void {
		super.focus();
		this.container?.focus();
	}

	override updateStyles(): void {
		super.updateStyles();
		this.editor?.setBackground(cadBackground(this.themeService.getColorTheme()));
	}

	override dispose(): void {
		this.stashAndRelease();
		super.dispose();
	}

	public getCadEditor(): CadEditorApi | undefined {
		return this.editor;
	}

	public async executeCadCommand(command: string): Promise<void> {
		if (!this.editor) {
			return;
		}
		try {
			await this.editor.execute(command);
		} catch {
			// Interactive CAD prompts throw on cancellation.
		}
	}

	public focusCadProperties(): void {
		void this.executeCadCommand('CHPROP');
	}

	public toggleCadCommandLine(): void {
		const editor = this.editor;
		if (!editor) {
			return;
		}
		const visible = !editor.getChrome().commandLine;
		this.viewStorage.store(CAD_COMMAND_LINE_STORAGE_KEY, visible, StorageScope.WORKSPACE, StorageTarget.MACHINE);
		editor.setChrome({ commandLine: visible });
		if (visible) {
			getWindow(this.container).setTimeout(() => editor.focusCommandLine(), 0);
		} else {
			this.container.focus();
		}
	}

	public async showCadLayerPicker(): Promise<void> {
		await this.cadBar?.showLayerPicker();
	}

	/** Keeps unsaved changes with the input and gives the mlightcad editor back. */
	private stashAndRelease(): void {
		const input = this.input as CadEditorInput | undefined;
		if (input?.source && input.isDirty()) {
			input.unsavedDxf = input.source.toDxf();
		}
		this.draftActiveContext?.set(false);
		this.cadBar?.setEditor(undefined);
		notifyActiveCadEditorChanged(undefined);
		this.inputDisposables.clear();
		if (this.editor) {
			releaseCadEditor(this.editor);
			this.editor = undefined;
		}
	}

	private showMessage(text: string | undefined): void {
		clearNode(this.message);
		this.message.classList.toggle('visible', !!text);
		if (text) {
			this.message.textContent = text;
		}
	}
}
