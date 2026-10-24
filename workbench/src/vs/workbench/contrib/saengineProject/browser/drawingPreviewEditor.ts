/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/drawings.css';
import { $, addDisposableListener, append, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { DrawingPreviewInput } from './drawingPreviewInput.js';
import { DRAWINGS_LIST_COMMAND, findPreviewSheet, fitView, IPreviewView, readDrawingSet, zoomAt, zoomLabel } from './drawingsModel.js';
import { EditorFrame } from './editorFrame.js';
import { CAD_OPEN_COMMAND, OPEN_DXF_IN_CAD_UI_COMMAND } from './projectArchiveModel.js';

const REVEAL_IN_OS_COMMAND = 'revealFileInOS';
const ZOOM_STEP = 1.25;

/**
 * A generated drawing sheet as its picture: zoom with the wheel or the toolbar, pan by dragging,
 * double-click to fit. The sheet itself is edited in LibreCAD (its DXF) and printed from the PDF.
 */
export class DrawingPreviewEditor extends EditorPane {

	static readonly ID = DrawingPreviewInput.EDITOR_ID;

	private frame!: EditorFrame;
	private viewport!: HTMLElement;
	private image!: HTMLImageElement;
	private view: IPreviewView = { zoom: 1, x: 0, y: 0 };
	private fitted = true;
	private viewWidth = 0;
	private viewHeight = 0;
	private loadVersion = 0;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly imageDisposables = this._register(new DisposableStore());
	private readonly dragDisposable = this._register(new MutableDisposable<DisposableStore>());

	private readonly zoomInAction = this._register(new Action('saengine.drawingPreview.zoomIn', localize('drawingPreview.zoomIn', "Zoom In"), ThemeIcon.asClassName(Codicon.zoomIn), true, () => this.zoomBy(ZOOM_STEP)));
	private readonly zoomOutAction = this._register(new Action('saengine.drawingPreview.zoomOut', localize('drawingPreview.zoomOut', "Zoom Out"), ThemeIcon.asClassName(Codicon.zoomOut), true, () => this.zoomBy(1 / ZOOM_STEP)));
	private readonly fitAction = this._register(new Action('saengine.drawingPreview.fit', localize('drawingPreview.fit', "Fit Sheet"), ThemeIcon.asClassName(Codicon.screenNormal), true, () => this.fit()));
	private readonly actualAction = this._register(new Action('saengine.drawingPreview.actual', localize('drawingPreview.actualSize', "Actual Pixels"), undefined, true, () => this.actualSize()));
	private readonly cadAction = this._register(new Action('saengine.drawingPreview.cad', localize('drawingPreview.openInLibreCad', "Open in LibreCAD"), ThemeIcon.asClassName(Codicon.linkExternal), true, () => this.openInCad()));
	private readonly pdfAction = this._register(new Action('saengine.drawingPreview.pdf', localize('drawingPreview.openPdf', "Open PDF Set"), undefined, true, () => this.openPdf()));
	private readonly revealAction = this._register(new Action('saengine.drawingPreview.reveal', localize('drawingPreview.reveal', "Reveal in File Explorer"), undefined, true, () => this.reveal()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IFileService private readonly fileService: IFileService,
		@ICommandService private readonly commandService: ICommandService,
		@IOpenerService private readonly openerService: IOpenerService,
		@INotificationService private readonly notificationService: INotificationService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
	) {
		super(DrawingPreviewEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: DrawingPreviewEditor.ID,
			ariaLabel: localize('drawingPreview.toolbar', "Drawing sheet"),
		}));
		this.frame.element.classList.add('saengine-drawing-preview');
		this.viewport = append(this.frame.main, $('.drawing-preview-viewport', { tabindex: '0', role: 'img' }));
		this.image = append(this.viewport, $<HTMLImageElement>('img.drawing-preview-image', { draggable: 'false', alt: '' }));
		this._register(this.frame.onDidLayoutMain(() => this.measure()));
		this.registerGestures();
	}

	private registerGestures(): void {
		this._register(addDisposableListener(this.viewport, EventType.MOUSE_WHEEL, (e: WheelEvent) => {
			e.preventDefault();
			const rect = this.viewport.getBoundingClientRect();
			this.setView(zoomAt(this.view, Math.pow(1.0015, -e.deltaY), e.clientX - rect.left, e.clientY - rect.top), false);
		}, { passive: false }));
		this._register(addDisposableListener(this.viewport, EventType.DBLCLICK, () => this.fit()));
		this._register(addDisposableListener(this.viewport, EventType.POINTER_DOWN, (e: PointerEvent) => {
			if (e.button !== 0) {
				return;
			}
			const start = { x: e.clientX, y: e.clientY, view: this.view };
			this.viewport.setPointerCapture(e.pointerId);
			this.viewport.classList.add('panning');
			const drag = this.dragDisposable.value = new DisposableStore();
			drag.add(addDisposableListener(this.viewport, EventType.POINTER_MOVE, (m: PointerEvent) => {
				this.setView({ zoom: start.view.zoom, x: start.view.x + m.clientX - start.x, y: start.view.y + m.clientY - start.y }, false);
			}));
			const end = () => {
				this.viewport.classList.remove('panning');
				this.dragDisposable.clear();
			};
			drag.add(addDisposableListener(this.viewport, EventType.POINTER_UP, end));
			drag.add(addDisposableListener(this.viewport, 'pointercancel', end));
		}));
		this._register(addDisposableListener(this.viewport, EventType.KEY_DOWN, (e: KeyboardEvent) => {
			const step = 48;
			const moves: { [key: string]: () => void } = {
				'+': () => this.zoomBy(ZOOM_STEP), '=': () => this.zoomBy(ZOOM_STEP), '-': () => this.zoomBy(1 / ZOOM_STEP), '0': () => this.fit(),
				ArrowLeft: () => this.pan(step, 0), ArrowRight: () => this.pan(-step, 0), ArrowUp: () => this.pan(0, step), ArrowDown: () => this.pan(0, -step),
			};
			const move = moves[e.key];
			if (move && !e.ctrlKey && !e.altKey && !e.metaKey) {
				e.preventDefault();
				move();
			}
		}));
	}

	override async setInput(input: DrawingPreviewInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		let png = input.sheet.png.toString();
		this.inputDisposables.add(input.onDidChangeSheet(sheet => {
			if (sheet.png.toString() !== png) {
				// Another picture: read it (a new picture at the same path comes as a file change).
				png = sheet.png.toString();
				void this.load(input);
			} else {
				// Only its title, files or staleness: the picture stays as it is.
				this.showSheet(input);
				if (this.image.naturalWidth) {
					this.setView(this.view, this.fitted);
				}
			}
		}));
		// The preview asks the backend itself whether its sheet went out of date (the Exports page
		// may not be open, as after a restore with the window).
		const staleness = this.inputDisposables.add(new RunOnceScheduler(() => void this.refreshSheet(input), 1500));
		this.inputDisposables.add(this.fileService.onDidFilesChange(e => {
			if (e.contains(input.sheet.png)) {
				void this.load(input);
			}
			const root = input.sheet.root;
			if (root && e.affects(root)) {
				staleness.schedule();
			}
		}));
		this.inputDisposables.add(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === DRAWINGS_LIST_COMMAND) {
				void this.refreshSheet(input);
			}
		}));
		void this.refreshSheet(input);
		this.inputDisposables.add(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === CAD_OPEN_COMMAND) {
				this.updateActions(input);
			}
		}));
		this.fitted = true;
		await this.load(input);
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.imageDisposables.clear();
		this.image?.removeAttribute('src');
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.viewport.focus();
	}

	private get sheetInput(): DrawingPreviewInput | undefined {
		return this.input instanceof DrawingPreviewInput ? this.input : undefined;
	}

	/** Reads the sheet's picture from disk into a blob URL (file URLs are not loaded by the workbench). */
	private async load(input: DrawingPreviewInput): Promise<void> {
		const version = ++this.loadVersion;
		const sheet = input.sheet;
		this.showSheet(input);
		this.frame.setStatus({ busy: true, text: localize('drawingPreview.loading', "Loading the sheet...") });
		try {
			const content = await this.fileService.readFile(sheet.png);
			if (version !== this.loadVersion) {
				return;
			}
			this.imageDisposables.clear();
			const targetWindow = getWindow(this.viewport);
			const url = targetWindow.URL.createObjectURL(new Blob([content.value.buffer as Uint8Array<ArrayBuffer>], { type: 'image/png' }));
			this.imageDisposables.add(toDisposable(() => targetWindow.URL.revokeObjectURL(url)));
			await new Promise<void>((resolve, reject) => {
				this.image.onload = () => resolve();
				this.image.onerror = () => reject(new Error(localize('drawingPreview.badImage', "The picture of the sheet could not be read.")));
				this.image.src = url;
			});
			if (version !== this.loadVersion) {
				return;
			}
			this.frame.setEmpty(undefined);
			this.measure();
			if (this.fitted) {
				this.fit();
			} else {
				this.setView(this.view, false);
			}
		} catch (error) {
			if (version !== this.loadVersion) {
				return;
			}
			this.image.removeAttribute('src');
			this.frame.setEmpty({
				icon: Codicon.fileMedia,
				title: localize('drawingPreview.missing', "The picture of sheet {0} is not there", sheet.number),
				text: localize('drawingPreview.missingText', "Generate the drawings again on the Exports page. ({0})", toErrorMessage(error)),
			});
			this.frame.setStatus(undefined);
		}
	}

	/** The sheet as the backend has it now (its staleness); an unchanged answer changes nothing. */
	private async refreshSheet(input: DrawingPreviewInput): Promise<void> {
		const root = input.sheet.root;
		if (!root || !CommandsRegistry.getCommand(DRAWINGS_LIST_COMMAND)) {
			return;
		}
		try {
			const set = readDrawingSet(await this.commandService.executeCommand(DRAWINGS_LIST_COMMAND, { projectRoot: root.fsPath }), root);
			const next = findPreviewSheet(set, input.sheet.png, root);
			if (next && this.input === input) {
				input.update(next);
			}
		} catch {
			// the backend could not tell: the sheet stays as it was
		}
	}

	/** The sheet's title and toolbar (without reading its picture). */
	private showSheet(input: DrawingPreviewInput): void {
		const sheet = input.sheet;
		this.frame.setTitle(localize('drawingPreview.title', "{0}  {1}", sheet.number, sheet.title));
		this.viewport.setAttribute('aria-label', localize('drawingPreview.aria', "Sheet {0}, {1}", sheet.number, sheet.title));
		this.updateActions(input);
	}

	private updateActions(input: DrawingPreviewInput): void {
		const sheet = input.sheet;
		this.cadAction.enabled = !!sheet.dxf;
		this.cadAction.label = CommandsRegistry.getCommand(CAD_OPEN_COMMAND) ? localize('drawingPreview.openInLibreCad', "Open in LibreCAD") : localize('drawingPreview.openInCadProgram', "Open in CAD Program");
		this.pdfAction.enabled = !!sheet.pdf;
		this.revealAction.enabled = !!CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND);
		this.frame.setActions([this.zoomOutAction, this.zoomInAction, this.fitAction, this.cadAction], [this.actualAction, this.pdfAction, this.revealAction]);
	}

	private measure(): void {
		this.viewWidth = this.viewport.clientWidth;
		this.viewHeight = this.viewport.clientHeight;
		if (this.fitted && this.image.naturalWidth) {
			this.fit();
		}
	}

	private fit(): void {
		this.setView(fitView(this.image.naturalWidth, this.image.naturalHeight, this.viewWidth, this.viewHeight), true);
	}

	private actualSize(): void {
		this.setView(zoomAt(this.view, 1 / this.view.zoom, this.viewWidth / 2, this.viewHeight / 2), false);
	}

	private zoomBy(factor: number): void {
		this.setView(zoomAt(this.view, factor, this.viewWidth / 2, this.viewHeight / 2), false);
	}

	private pan(dx: number, dy: number): void {
		this.setView({ ...this.view, x: this.view.x + dx, y: this.view.y + dy }, false);
	}

	private setView(view: IPreviewView, fitted: boolean): void {
		this.view = view;
		this.fitted = fitted;
		this.image.style.width = `${this.image.naturalWidth * view.zoom}px`;
		this.image.style.height = `${this.image.naturalHeight * view.zoom}px`;
		this.image.style.transform = `translate(${view.x}px, ${view.y}px)`;
		const sheet = this.sheetInput?.sheet;
		if (sheet && this.image.naturalWidth) {
			const parts = [sheet.size, sheet.scale, localize('drawingPreview.pixels', "{0} × {1} px", this.image.naturalWidth, this.image.naturalHeight), zoomLabel(view)].filter((p): p is string => !!p);
			const status = parts.join(' · ');
			this.frame.setStatus(sheet.stale
				? { severity: 'warning', icon: Codicon.warning, text: localize('drawingPreview.stale', "Out of date — regenerate on the Exports page. {0}", status) }
				: { text: status });
		}
	}

	private async openInCad(): Promise<void> {
		const dxf = this.sheetInput?.sheet.dxf;
		if (dxf) {
			await this.commandService.executeCommand(OPEN_DXF_IN_CAD_UI_COMMAND, dxf);
		}
	}

	private async openPdf(): Promise<void> {
		const pdf = this.sheetInput?.sheet.pdf;
		if (pdf) {
			try {
				await this.openerService.open(pdf, { openExternal: true });
			} catch (error) {
				this.notificationService.error(toErrorMessage(error));
			}
		}
	}

	private async reveal(): Promise<void> {
		const sheet = this.sheetInput?.sheet;
		if (sheet) {
			await this.commandService.executeCommand(REVEAL_IN_OS_COMMAND, sheet.dxf ?? sheet.png);
		}
	}
}
