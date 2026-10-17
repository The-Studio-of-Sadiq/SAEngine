/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi } from '@saengine/cad-editor';
import { $, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { acquireCadEditor, cadBackground, releaseCadEditor } from './cadHost.js';
import { CadEditorInput } from './cadEditorInput.js';

/**
 * The 2D CAD editor for DXF drawings, built on mlightcad. The pane holds the window's one
 * mlightcad editor only while it shows a drawing; unsaved changes stay with the input when
 * another editor takes the pane.
 */
export class CadEditorPane extends EditorPane {

	private container!: HTMLElement;
	private host!: HTMLElement;
	private message!: HTMLElement;
	private editor: CadEditorApi | undefined;
	private readonly inputDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IFileService private readonly fileService: IFileService,
	) {
		super(CadEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.saengine-cad-editor'));
		this.host = append(this.container, $('.cad-host'));
		this.message = append(this.container, $('.cad-message'));
	}

	override async setInput(input: CadEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		this.stashAndRelease();
		await super.setInput(input, options, context, token);
		this.showMessage(undefined);

		let editor: CadEditorApi;
		try {
			editor = this.editor = await acquireCadEditor(this.host, { background: cadBackground(this.themeService.getColorTheme()) });
		} catch (error) {
			this.showMessage(localize('cad.loadFailed', "The CAD editor could not start: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			this.stashAndRelease();
			return;
		}

		const load = async (fromDisk: boolean) => {
			const content = (!fromDisk && input.unsavedDxf) || (await this.fileService.readFile(input.resource)).value.toString();
			const opened = content.trim() ? await editor.openDxf(input.getName(), content) : await editor.newDrawing();
			if (!opened) {
				this.showMessage(localize('cad.openFailed', "{0} could not be opened as a DXF drawing.", input.getName()));
			}
		};
		await load(false);
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
	}

	override updateStyles(): void {
		super.updateStyles();
		this.editor?.setBackground(cadBackground(this.themeService.getColorTheme()));
	}

	override dispose(): void {
		this.stashAndRelease();
		super.dispose();
	}

	/** Keeps unsaved changes with the input and gives the mlightcad editor back. */
	private stashAndRelease(): void {
		const input = this.input as CadEditorInput | undefined;
		if (input?.source && input.isDirty()) {
			input.unsavedDxf = input.source.toDxf();
		}
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
