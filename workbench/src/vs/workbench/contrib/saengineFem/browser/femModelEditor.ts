/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femModelEditor.css';
import type { FemModel, FemSelection, FemViewer, FemViewerTheme } from '@saengine/fem-viewer';
import { $, append, Dimension, clearNode } from '../../../../base/browser/dom.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { resolveAmdNodeModulePath } from '../../../../amdX.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { chartsBlue, chartsGreen, chartsLines, chartsYellow } from '../../../../platform/theme/common/colors/chartsColors.js';
import { editorBackground, editorForeground } from '../../../../platform/theme/common/colors/editorColors.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { FemModelEditorInput } from './femModelEditorInput.js';

type FemViewerModule = typeof import('@saengine/fem-viewer');

let viewerModule: Promise<FemViewerModule> | undefined;

/**
 * The viewer bundles three.js and That Open Engine as a single ESM file. It is loaded by URL on
 * first use so the workbench startup bundle does not pay for it.
 */
function loadViewerModule(): Promise<FemViewerModule> {
	if (!viewerModule) {
		const url = resolveAmdNodeModulePath('@saengine/fem-viewer', 'dist/fem-viewer.js');
		viewerModule = import(/* webpackIgnore: true */ /* @vite-ignore */ `${url}`) as Promise<FemViewerModule>;
		viewerModule.catch(() => viewerModule = undefined);
	}
	return viewerModule;
}

export class FemModelEditor extends EditorPane {

	private container: HTMLElement | undefined;
	private viewport: HTMLElement | undefined;
	private message: HTMLElement | undefined;
	private viewer: FemViewer | undefined;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly viewerDisposable = this._register(new MutableDisposable());

	private readonly _onDidChangeSelection = this._register(new Emitter<FemSelection | undefined>());
	readonly onDidChangeSelection: Event<FemSelection | undefined> = this._onDidChangeSelection.event;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IFileService private readonly fileService: IFileService,
	) {
		super(FemModelEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.saengine-fem-model-editor'));
		this.viewport = append(this.container, $('.viewport'));
		this.message = append(this.container, $('.message'));
	}

	override async setInput(input: FemModelEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();

		const viewer = await this.ensureViewer();
		if (token.isCancellationRequested || !viewer) {
			return;
		}

		const watcher = this.fileService.createWatcher(input.resource, { recursive: false, excludes: [] });
		this.inputDisposables.add(watcher);
		this.inputDisposables.add(watcher.onDidChange(e => {
			if (e.contains(input.resource)) {
				void this.loadModel(input, CancellationToken.None);
			}
		}));

		await this.loadModel(input, token);
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		if (this.container) {
			this.container.style.width = `${dimension.width}px`;
			this.container.style.height = `${dimension.height}px`;
		}
		this.viewer?.layout();
	}

	override focus(): void {
		super.focus();
		this.viewport?.focus();
	}

	override updateStyles(): void {
		super.updateStyles();
		this.viewer?.setTheme(this.computeTheme());
	}

	private async ensureViewer(): Promise<FemViewer | undefined> {
		if (this.viewer) {
			return this.viewer;
		}
		try {
			const { createFemViewer } = await loadViewerModule();
			if (this.viewer || !this.viewport) {
				return this.viewer;
			}
			const viewer = createFemViewer(this.viewport, {
				theme: this.computeTheme(),
				onSelectionChanged: selection => this._onDidChangeSelection.fire(selection),
			});
			this.viewer = viewer;
			this.viewerDisposable.value = toDisposable(() => {
				viewer.dispose();
				this.viewer = undefined;
			});
			return viewer;
		} catch (error) {
			this.showMessage(localize('femModelEditor.viewerFailed', "The FEM viewport could not be loaded: {0}", String(error)));
			return undefined;
		}
	}

	private async loadModel(input: FemModelEditorInput, token: CancellationToken): Promise<void> {
		let model: FemModel;
		try {
			const content = await this.fileService.readFile(input.resource, undefined, token);
			model = JSON.parse(content.value.toString());
		} catch (error) {
			if (!token.isCancellationRequested) {
				this.showMessage(localize('femModelEditor.readFailed', "Unable to read the model: {0}", String(error)));
			}
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
		if (!Array.isArray(model.nodes) || !Array.isArray(model.elements)) {
			this.showMessage(localize('femModelEditor.invalid', "This file is not an OpenSees Studio model (missing nodes or elements)."));
			return;
		}
		this.showMessage(undefined);
		this.viewer?.setModel(model);
	}

	private showMessage(text: string | undefined): void {
		if (!this.message) {
			return;
		}
		clearNode(this.message);
		this.message.classList.toggle('visible', !!text);
		if (text) {
			this.message.textContent = text;
		}
	}

	private computeTheme(): Partial<FemViewerTheme> {
		const theme = this.themeService.getColorTheme();
		const color = (id: string) => theme.getColor(id)?.toString();
		return {
			background: color(editorBackground),
			member: color(chartsBlue),
			node: color(editorForeground),
			support: color(chartsGreen),
			selection: color(chartsYellow),
			grid: color(chartsLines),
		};
	}
}
