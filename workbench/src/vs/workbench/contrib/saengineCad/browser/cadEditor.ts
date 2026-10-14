/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/cadEditor.css';
import type { CadEditor as CadEditorApi } from '@saengine/cad-editor';
import { $, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { sanitizeHtml } from '../../../../base/browser/domSanitize.js';
import { createTrustedTypesPolicy } from '../../../../base/browser/trustedTypes.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { resolveAmdNodeModulePath } from '../../../../amdX.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { CadEditorInput } from './cadEditorInput.js';

type CadEditorModule = typeof import('@saengine/cad-editor');

const PACKAGE = '@saengine/cad-editor';

/** SVG icons and a few text tags: everything mlightcad's own UI writes with innerHTML. */
const CAD_UI_TAGS = ['svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'text', 'tspan', 'defs', 'use', 'span', 'strong', 'div'];
const CAD_UI_ATTRIBUTES = ['viewBox', 'd', 'fill', 'fill-rule', 'clip-rule', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'cx', 'cy', 'r', 'rx', 'ry', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'points', 'transform', 'width', 'height', 'opacity', 'xmlns', 'aria-hidden', 'class', 'font-size', 'text-anchor'];

let cadModule: Promise<CadEditorModule> | undefined;

/**
 * Loads the bundled mlightcad editor and connects it to the workbench's Trusted Types rules:
 * its HTML goes through the workbench sanitizer and its worker may only come from its own folder.
 */
function loadCadModule(): Promise<CadEditorModule> {
	if (!cadModule) {
		cadModule = (async () => {
			const module = await import(/* webpackIgnore: true */ /* @vite-ignore */ `${resolveAmdNodeModulePath(PACKAGE, 'dist/cad-editor.js')}`) as CadEditorModule;
			const workerBase = resolveAmdNodeModulePath(PACKAGE, 'dist/');
			const workerPolicy = createTrustedTypesPolicy('saengineCadWorker', {
				createScriptURL(value: string) {
					if (!value.startsWith(workerBase)) {
						throw new Error(`Refusing to start a CAD worker from ${value}`);
					}
					return value;
				},
			});
			module.setTrustedTypesHost({
				html: value => sanitizeHtml(value, { allowedTags: { augment: CAD_UI_TAGS }, allowedAttributes: { augment: CAD_UI_ATTRIBUTES } }),
				scriptUrl: value => workerPolicy?.createScriptURL(value) ?? value,
			});
			return module;
		})();
		cadModule.catch(() => cadModule = undefined);
	}
	return cadModule;
}

/**
 * The 2D CAD editor (Part 5 floor plans), built on mlightcad. mlightcad allows one live editor
 * per window, so a second drawing replaces the first in this pane.
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
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.showMessage(undefined);

		let editor: CadEditorApi;
		try {
			editor = await this.ensureEditor();
		} catch (error) {
			this.showMessage(localize('cad.loadFailed', "The CAD editor could not start: {0}", String(error)));
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}

		const load = async () => {
			const content = (await this.fileService.readFile(input.resource)).value.toString();
			const opened = content.trim() ? await editor.openDxf(input.getName(), content) : await editor.newDrawing();
			if (!opened) {
				this.showMessage(localize('cad.openFailed', "{0} could not be opened as a DXF drawing.", input.getName()));
			}
		};
		await load();
		input.source = { toDxf: () => editor.toDxf(), reload: load };
		this.inputDisposables.add(toDisposable(() => input.source = undefined));
		this.inputDisposables.add(toDisposable(editor.onDidChange(() => input.setDirty(true))));
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
	}

	override dispose(): void {
		void this.editor?.dispose();
		this.editor = undefined;
		super.dispose();
	}

	private async ensureEditor(): Promise<CadEditorApi> {
		if (!this.editor) {
			const { createCadEditor } = await loadCadModule();
			this.editor = createCadEditor({
				container: this.host,
				workerBaseUrl: resolveAmdNodeModulePath(PACKAGE, 'dist/'),
				assetBaseUrl: resolveAmdNodeModulePath(PACKAGE, 'dist/assets/'),
			});
		}
		return this.editor;
	}

	private showMessage(text: string | undefined): void {
		clearNode(this.message);
		this.message.classList.toggle('visible', !!text);
		if (text) {
			this.message.textContent = text;
		}
	}
}
