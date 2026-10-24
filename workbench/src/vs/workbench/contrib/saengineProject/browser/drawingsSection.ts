/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/drawings.css';
import { $, addDisposableListener, append, clearNode, EventType, getActiveElement, getWindow, isHTMLElement } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Checkbox } from '../../../../base/browser/ui/toggle/toggle.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { parse } from '../../../../base/common/json.js';
import { Disposable, DisposableMap, DisposableStore, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { defaultButtonStyles, defaultCheckboxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { IWorkingCopyService } from '../../../services/workingCopy/common/workingCopyService.js';
import { DrawingPreviewInput, IDrawingPreviewSheet } from './drawingPreviewInput.js';
import {
	drawingSetKey, drawingSettingsRows, drawingsDescription, DRAWINGS_GENERATE_COMMAND, DRAWINGS_LIST_COMMAND, findPreviewSheet, generateArgs, generateLabel, IDrawingSet, IDrawingSettings, IDrawingSheet,
	keepSelection, previewSheet, readDrawingSet, readDrawingSettings, selectedSheets, SHEET_SIZES, SheetSize,
} from './drawingsModel.js';
import { EditorFrame } from './editorFrame.js';
import { CAD_OPEN_COMMAND, OPEN_DXF_IN_CAD_UI_COMMAND } from './projectArchiveModel.js';
import { saveProjectEdits } from './projectEdits.js';

const REVEAL_IN_OS_COMMAND = 'revealFileInOS';
/** Project Settings (part 2), where the title block is filled in (`drawings.*`). */
const OPEN_SETTINGS_COMMAND = 'saengine.project.openSettings';

function formatTime(time: number): string {
	const date = new Date(time);
	const now = new Date();
	return date.toLocaleString(undefined, {
		day: 'numeric', month: 'short', year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
		hour: '2-digit', minute: '2-digit',
	});
}

interface IThumbnail extends IDisposable {
	readonly url: string;
	readonly key: string;
	readonly png: URI;
}

/**
 * Part 11's Drawings: the structural drawing sheets generated from the model and its design,
 * with their title block settings. It lives in the exports list as one section that renders
 * itself: the exports page appends {@link element} where it belongs and calls {@link setProject}.
 *
 * The heading (with the size and the Generate button) is built once and updated in place; the
 * settings are rebuilt only when they change, and the sheet list only when the backend's answer
 * changes, giving the focus back to the same control. Ticking sheets changes nothing but the
 * ticks and the button, so the keyboard stays where it is.
 */
export class DrawingsSection extends Disposable {

	readonly element: HTMLElement;

	private root: URI | undefined;
	private set: IDrawingSet | undefined;
	private settings: IDrawingSettings = readDrawingSettings(undefined);
	private listed = false;
	private busy = false;
	private size: SheetSize | undefined;
	private selection = new Set<string>();
	private settingsOpen = true;
	private listVersion = 0;

	private readonly description: HTMLElement;
	private readonly when: HTMLElement;
	private readonly picker: SelectBox;
	private pickerIndex = -1;
	private readonly generateButton: Button;
	private readonly settingsBlock: HTMLElement;
	private readonly setSlot: HTMLElement;
	/** What the sheet list was built from (undefined: not built). */
	private renderedSetKey: string | undefined;
	private allCheck: Checkbox | undefined;
	private readonly sheetChecks = new Map<string, Checkbox>();
	/** The thumbnail pictures on the page, by the sheet picture they show. */
	private readonly thumbImages = new Map<string, HTMLImageElement[]>();
	/** The section's controls by a name that stays the same when they are built again. */
	private readonly focusTargets = new Map<string, { readonly element: HTMLElement; focus(): void }>();

	private readonly _onDidChange = this._register(new Emitter<void>());
	/** The section's height may have changed (the page's scrollbar follows). */
	readonly onDidChange: Event<void> = this._onDidChange.event;

	private readonly settingsDisposables = this._register(new DisposableStore());
	private readonly setDisposables = this._register(new DisposableStore());
	private readonly projectDisposables = this._register(new DisposableStore());
	/** Thumbnail blob URLs by picture (with the time of the generation they belong to). */
	private readonly thumbnails = this._register(new DisposableMap<string, IThumbnail>());
	private readonly listScheduler = this._register(new RunOnceScheduler(() => void this.list(), 1500));
	private readonly settingsScheduler = this._register(new RunOnceScheduler(() => void this.readSettings(), 300));

	constructor(
		private readonly frame: EditorFrame,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@IEditorService private readonly editorService: IEditorService,
		@INotificationService private readonly notificationService: INotificationService,
		@IContextViewService contextViewService: IContextViewService,
		@IWorkingCopyService private readonly workingCopyService: IWorkingCopyService,
	) {
		super();
		this.element = $('section.exports-kind.exports-drawings', { 'aria-label': localize('drawings.title', "Structural drawings") });
		this.element.hidden = true;

		const row = append(this.element, $('.exports-row'));
		append(row, $(`span.exports-icon${ThemeIcon.asCSSSelector(Codicon.symbolRuler)}`));
		const text = append(row, $('.exports-text'));
		append(text, $('.exports-title', undefined, localize('drawings.title', "Structural drawings")));
		this.description = append(text, $('.exports-description'));
		this.when = append(row, $('.exports-when'));
		const actions = append(row, $('.exports-actions.drawings-generate'));
		this.picker = this._register(new SelectBox(SHEET_SIZES.map(s => ({ text: s })), 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('drawings.sizeAria', "Sheet size") }));
		this.picker.render(this.named(append(actions, $('.drawings-size')), 'size', () => this.picker.focus()));
		this._register(this.picker.onDidSelect(e => {
			this.size = SHEET_SIZES[e.index];
			this.pickerIndex = e.index;
		}));
		this.generateButton = this._register(new Button(actions, { ...defaultButtonStyles, supportIcons: true }));
		this.named(this.generateButton.element, 'generate');
		this._register(this.generateButton.onDidClick(() => void this.generate()));

		this.settingsBlock = append(this.element, $('.drawings-settings'));
		this.setSlot = append(this.element, $('.drawings-set'));

		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === DRAWINGS_LIST_COMMAND) {
				void this.list();
			} else if (id === DRAWINGS_GENERATE_COMMAND || id === CAD_OPEN_COMMAND || id === REVEAL_IN_OS_COMMAND) {
				this.update();
			}
		}));
	}

	private get available(): boolean {
		return !!CommandsRegistry.getCommand(DRAWINGS_GENERATE_COMMAND);
	}

	private get settingsFile(): URI | undefined {
		const part = partById('settings');
		return this.root && part?.mainFile ? joinPath(this.root, part.folder, part.mainFile) : undefined;
	}

	/** Follows the project at `root` (undefined: none open): its last drawings and its settings. */
	setProject(root: URI | undefined): void {
		if (root?.toString() === this.root?.toString()) {
			return;
		}
		this.projectDisposables.clear();
		this.thumbnails.clearAndDisposeAll();
		this.root = root;
		this.set = undefined;
		this.listed = false;
		this.selection.clear();
		this.size = undefined;
		this.settings = readDrawingSettings(undefined);
		if (root) {
			this.projectDisposables.add(this.fileService.onDidFilesChange(e => {
				const settingsFile = this.settingsFile;
				if (settingsFile && e.contains(settingsFile)) {
					this.settingsScheduler.schedule();
				}
				// A sheet picture written again (at the same path): its thumbnail is read again.
				for (const [id, thumbnail] of [...this.thumbnails]) {
					if (e.contains(thumbnail.png)) {
						this.thumbnails.deleteAndDispose(id);
						void this.showThumbnail(thumbnail.png);
					}
				}
				// The drawings go out of date when the model or the design changes: ask the backend again.
				if (!this.busy && e.affects(root)) {
					this.listScheduler.schedule();
				}
			}));
			void this.readSettings();
			void this.list();
		}
		this.renderSettings();
		this.update(true);
	}

	/**
	 * Notes the control that has the focus in the section; the returned function gives it back
	 * to the same control (after the page or the section was built again).
	 */
	captureFocus(): () => void {
		const active = getActiveElement();
		let name: string | undefined;
		for (const [key, target] of this.focusTargets) {
			if (active && target.element.contains(active) && this.element.contains(target.element)) {
				name = key;
			}
		}
		if (!name) {
			return () => { };
		}
		return () => {
			// Controls built again are found under their names; the ones gone are forgotten.
			for (const [key, target] of [...this.focusTargets]) {
				if (!this.element.contains(target.element)) {
					this.focusTargets.delete(key);
				}
			}
			const target = this.focusTargets.get(name);
			if (target && !this.element.contains(getActiveElement())) {
				target.focus();
			}
		};
	}

	/** Gives a control a name that outlives a rebuild of its part (see {@link captureFocus}). */
	private named<T extends HTMLElement>(element: T, name: string, focus: () => void = () => element.focus()): T {
		this.focusTargets.set(name, { element, focus });
		return element;
	}

	private async readSettings(): Promise<void> {
		const file = this.settingsFile;
		if (!file) {
			return;
		}
		let settings: IDrawingSettings;
		try {
			settings = readDrawingSettings(parse((await this.fileService.readFile(file)).value.toString()));
		} catch {
			settings = readDrawingSettings(undefined);
		}
		if (file.toString() === this.settingsFile?.toString()) {
			const changed = JSON.stringify(settings) !== JSON.stringify(this.settings);
			this.settings = settings;
			if (changed) {
				this.renderSettings();
				this.update();
			}
		}
	}

	/** The last generation, as the backend has it (with its staleness). */
	private async list(): Promise<void> {
		const root = this.root;
		if (!root || !CommandsRegistry.getCommand(DRAWINGS_LIST_COMMAND)) {
			this.listed = true;
			this.update();
			return;
		}
		const version = ++this.listVersion;
		let set: IDrawingSet | undefined;
		try {
			set = readDrawingSet(await this.commandService.executeCommand(DRAWINGS_LIST_COMMAND, { projectRoot: root.fsPath }), root);
		} catch {
			set = undefined;
		}
		if (version !== this.listVersion || root.toString() !== this.root?.toString()) {
			return;
		}
		const wasListed = this.listed;
		this.listed = true;
		if (wasListed && drawingSetKey(set) === drawingSetKey(this.set)) {
			return; // the same answer: the page stays as it is
		}
		this.setDrawings(set);
		this.update();
	}

	private setDrawings(set: IDrawingSet | undefined): void {
		this.set = set;
		this.selection = keepSelection(set, this.selection);
		this.updatePreviews();
	}

	/** Open previews follow the new generation (title, staleness); an unchanged sheet is left alone. */
	private updatePreviews(): void {
		const set = this.set;
		if (!set) {
			return;
		}
		for (const editor of this.editorService.editors) {
			if (editor instanceof DrawingPreviewInput) {
				const next = findPreviewSheet(set, editor.sheet.png, this.root);
				if (next) {
					editor.update(next);
				}
			}
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	/** Brings the page up to date: the heading in place, the sheet list when its answer changed (or `rebuild`). */
	private update(rebuild = false): void {
		this.element.hidden = !this.root;
		if (!this.root) {
			this.setDisposables.clear();
			clearNode(this.setSlot);
			this.renderedSetKey = undefined;
			return;
		}
		this.updateHeading();
		const key = `${drawingSetKey(this.set)}|${!!CommandsRegistry.getCommand(CAD_OPEN_COMMAND)}|${!!CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)}`;
		if (rebuild || key !== this.renderedSetKey) {
			const restoreFocus = this.captureFocus();
			this.renderedSetKey = key;
			this.renderSet();
			restoreFocus();
		}
		this.updateSelection();
		this._onDidChange.fire();
	}

	private updateHeading(): void {
		const set = this.set;
		const available = this.available;
		this.element.classList.toggle('made', !!set?.sheets.length);
		this.element.classList.toggle('stale', !!set?.stale);
		this.description.textContent = this.busy ? localize('drawings.generating', "Generating the drawings...") : drawingsDescription(set, available);
		this.description.classList.toggle('stale', !!set?.stale && !this.busy);
		if (set?.generatedAt) {
			this.when.textContent = formatTime(set.generatedAt);
			this.when.classList.remove('muted');
		} else {
			this.when.textContent = this.listed && available ? localize('drawings.notMade', "Not made yet") : '';
			this.when.classList.add('muted');
		}
		const index = Math.max(0, SHEET_SIZES.indexOf(this.size ?? this.settings.sheetSize));
		if (index !== this.pickerIndex) {
			this.pickerIndex = index;
			this.picker.select(index);
		}
		this.picker.setEnabled(available && !this.busy);
	}

	/** The ticks and what the Generate button says about them (nothing is built again). */
	private updateSelection(): void {
		const set = this.set;
		const selected = selectedSheets(set, this.selection).length;
		this.generateButton.label = generateLabel(set, selected);
		this.generateButton.enabled = this.available && !this.busy;
		this.generateButton.secondary = !!set?.sheets.length && !set.stale && !selected;
		if (this.allCheck) {
			this.allCheck.checked = !!set?.sheets.length && set.sheets.every(s => this.selection.has(s.number));
		}
		for (const [number, check] of this.sheetChecks) {
			check.checked = this.selection.has(number);
		}
	}

	/** The title block and sheet settings; filled in under Project Settings (`drawings.*`). */
	private renderSettings(): void {
		const restoreFocus = this.captureFocus();
		this.settingsDisposables.clear();
		const block = this.settingsBlock;
		clearNode(block);
		block.classList.toggle('closed', !this.settingsOpen);
		const header = this.named(append(block, $<HTMLButtonElement>('button.drawings-settings-toggle', { type: 'button', 'aria-expanded': String(this.settingsOpen) })), 'settings');
		const chevron = append(header, $(ThemeIcon.asCSSSelector(this.settingsOpen ? Codicon.chevronDown : Codicon.chevronRight)));
		append(header, $('span', undefined, localize('drawings.settingsTitle', "Title block and sheets")));
		this.settingsDisposables.add(addDisposableListener(header, EventType.CLICK, () => {
			// Folded in place: the button keeps the focus.
			this.settingsOpen = !this.settingsOpen;
			block.classList.toggle('closed', !this.settingsOpen);
			header.setAttribute('aria-expanded', String(this.settingsOpen));
			chevron.className = ThemeIcon.asClassName(this.settingsOpen ? Codicon.chevronDown : Codicon.chevronRight);
			this._onDidChange.fire();
		}));
		const link = this.named(append(block, $<HTMLAnchorElement>('a.drawings-settings-link', { role: 'button', tabindex: '0' }, localize('drawings.editSettings', "Edit in Project Settings"))), 'settings-link');
		const openSettings = () => void this.commandService.executeCommand(OPEN_SETTINGS_COMMAND);
		this.settingsDisposables.add(addDisposableListener(link, EventType.CLICK, openSettings));
		this.settingsDisposables.add(addDisposableListener(link, EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				openSettings();
			}
		}));
		const grid = append(block, $('dl.drawings-settings-grid'));
		for (const { name, value } of drawingSettingsRows(this.settings)) {
			append(grid, $('dt', undefined, name));
			const cell = append(grid, $('dd', undefined, value ?? localize('drawings.notSet', "not set")));
			cell.classList.toggle('muted', value === undefined);
		}
		if (!this.settings.present) {
			append(block, $('.drawings-settings-note', undefined, localize('drawings.settingsDefaults', "The project settings have no drawing settings yet: the sheets use the project's name, number and engineer and these defaults.")));
		}
		restoreFocus();
		this._onDidChange.fire();
	}

	/** The sheet list and the set's files. */
	private renderSet(): void {
		this.setDisposables.clear();
		clearNode(this.setSlot);
		this.allCheck = undefined;
		this.sheetChecks.clear();
		this.thumbImages.clear();
		const set = this.set;
		if (set?.sheets.length) {
			this.renderSheets(set);
		}
		if (set) {
			this.renderFooter(set);
		}
	}

	private renderSheets(set: IDrawingSet): void {
		const list = append(this.setSlot, $('ul.drawings-sheets', { 'aria-label': localize('drawings.sheetList', "Drawing sheets") }));
		const all = this.allCheck = this.setDisposables.add(new Checkbox(localize('drawings.selectAll', "Select all sheets"), set.sheets.every(s => this.selection.has(s.number)), defaultCheckboxStyles));
		const head = append(list, $('li.drawings-sheet.drawings-sheet-head'));
		append(head, this.named(all.domNode, 'check:*'));
		append(head, $('span.drawings-thumb-head'));
		append(head, $('span.drawings-sheet-number', undefined, localize('drawings.number', "Sheet")));
		append(head, $('span.drawings-sheet-title', undefined, localize('drawings.sheetTitle', "Title")));
		append(head, $('span.drawings-sheet-size', undefined, localize('drawings.size', "Size")));
		append(head, $('span.drawings-sheet-state', undefined, localize('drawings.state', "Status")));
		append(head, $('span.exports-actions'));
		this.setDisposables.add(all.onChange(() => {
			const current = this.set;
			this.selection = all.checked && current ? new Set(current.sheets.map(s => s.number)) : new Set();
			this.updateSelection();
		}));
		for (const sheet of set.sheets) {
			this.renderSheet(list, sheet, set);
		}
	}

	private renderSheet(list: HTMLElement, sheet: IDrawingSheet, set: IDrawingSet): void {
		const item = append(list, $('li.drawings-sheet'));
		item.classList.toggle('stale', sheet.stale);
		const check = this.setDisposables.add(new Checkbox(localize('drawings.selectSheet', "Select sheet {0}", sheet.number), this.selection.has(sheet.number), defaultCheckboxStyles));
		this.sheetChecks.set(sheet.number, check);
		append(item, this.named(check.domNode, `check:${sheet.number}`));
		this.setDisposables.add(check.onChange(() => {
			if (check.checked) {
				this.selection.add(sheet.number);
			} else {
				this.selection.delete(sheet.number);
			}
			this.updateSelection();
		}));
		const preview = previewSheet(sheet, set, this.root);
		const thumb = this.named(append(item, $<HTMLButtonElement>('button.drawings-thumb', { type: 'button', 'aria-label': localize('drawings.previewSheet', "Preview {0}", sheet.number) })), `thumb:${sheet.number}`);
		if (preview) {
			const image = append(thumb, $<HTMLImageElement>('img', { alt: '', draggable: 'false' }));
			const id = preview.png.toString();
			this.thumbImages.set(id, [...this.thumbImages.get(id) ?? [], image]);
			void this.showThumbnail(preview.png);
			this.setDisposables.add(addDisposableListener(thumb, EventType.CLICK, () => void this.openPreview(preview)));
		} else {
			thumb.disabled = true;
			thumb.classList.add('missing');
		}
		append(item, $('span.drawings-sheet-number', undefined, sheet.number));
		const title = append(item, $('span.drawings-sheet-title', undefined, sheet.title));
		if (sheet.scale) {
			append(title, $('span.drawings-sheet-scale', undefined, sheet.scale));
		}
		append(item, $('span.drawings-sheet-size', undefined, sheet.size ?? set.size ?? ''));
		append(item, $('span.drawings-sheet-state', undefined, sheet.stale ? localize('drawings.outOfDate', "Out of date — regenerate") : localize('drawings.current', "Current")));
		const actions = append(item, $('.exports-actions'));
		if (preview) {
			const button = this.setDisposables.add(this.frame.createIconButton(actions, Codicon.preview, localize('drawings.preview', "Preview"), () => void this.openPreview(preview)));
			this.named(button.element, `preview:${sheet.number}`);
		}
		if (sheet.dxf) {
			const dxf = sheet.dxf;
			const label = CommandsRegistry.getCommand(CAD_OPEN_COMMAND) ? localize('drawings.openInLibreCad', "Open in LibreCAD") : localize('drawings.openInCadProgram', "Open in CAD Program");
			const button = this.setDisposables.add(this.frame.createIconButton(actions, Codicon.linkExternal, label, () => void this.commandService.executeCommand(OPEN_DXF_IN_CAD_UI_COMMAND, dxf)));
			this.named(button.element, `cad:${sheet.number}`);
		}
		const file = sheet.dxf ?? sheet.png;
		if (file && CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
			const button = this.setDisposables.add(this.frame.createIconButton(actions, Codicon.folderOpened, localize('drawings.reveal', "Reveal in File Explorer"), () => void this.commandService.executeCommand(REVEAL_IN_OS_COMMAND, file)));
			this.named(button.element, `reveal:${sheet.number}`);
		}
		this.setDisposables.add(addDisposableListener(item, EventType.DBLCLICK, e => {
			if (preview && !(isHTMLElement(e.target) && e.target.closest('button, .monaco-custom-toggle'))) {
				void this.openPreview(preview);
			}
		}));
	}

	private renderFooter(set: IDrawingSet): void {
		const footer = append(this.setSlot, $('.drawings-footer'));
		const links = append(footer, $('.drawings-files'));
		const fileButton = (resource: URI | undefined, label: string, icon: ThemeIcon, name: string) => {
			const button = this.setDisposables.add(new Button(links, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			this.named(button.element, name);
			button.label = `$(${icon.id}) ${label}`;
			button.enabled = !!resource;
			if (resource) {
				this.setDisposables.add(button.onDidClick(() => void this.openExternal(resource)));
			}
		};
		fileButton(set.pdf, localize('drawings.openPdf', "Open PDF Set"), Codicon.filePdf, 'pdf');
		fileButton(set.bbsCsv, localize('drawings.bbsCsv', "Bar Bending Schedule (CSV)"), Codicon.table, 'bbs');
		const folder = set.pdf ?? set.bbsCsv ?? set.sheets.find(s => s.dxf)?.dxf;
		if (folder && CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
			const button = this.setDisposables.add(this.frame.createIconButton(links, Codicon.folderOpened, localize('drawings.revealSet', "Reveal Drawings in File Explorer"), () => void this.commandService.executeCommand(REVEAL_IN_OS_COMMAND, folder)));
			this.named(button.element, 'reveal-set');
		}
		if (set.problems.length || set.notes.length) {
			const messages = append(footer, $('ul.drawings-messages'));
			for (const problem of set.problems) {
				const item = append(messages, $('li.error'));
				append(item, $(ThemeIcon.asCSSSelector(Codicon.error)));
				append(item, $('span', undefined, problem));
			}
			for (const note of set.notes) {
				const item = append(messages, $('li'));
				append(item, $(ThemeIcon.asCSSSelector(Codicon.info)));
				append(item, $('span', undefined, note));
			}
		}
	}

	/** Shows a sheet's picture in its thumbnails on the page. */
	private async showThumbnail(png: URI): Promise<void> {
		const id = png.toString();
		const url = await this.thumbnail(png, this.set?.generatedAt);
		for (const image of this.thumbImages.get(id) ?? []) {
			const thumb = image.parentElement;
			if (url) {
				image.src = url;
				thumb?.classList.remove('missing');
			} else {
				image.removeAttribute('src');
				thumb?.classList.add('missing');
			}
		}
	}

	/**
	 * The thumbnail of a sheet's picture, read once per generation; read again when the picture
	 * changes on disk or is drawn again (also when the backend gives no generation time).
	 */
	private async thumbnail(png: URI, generatedAt: number | undefined): Promise<string | undefined> {
		const id = png.toString();
		const key = `${id}@${generatedAt ?? ''}`;
		const cached = this.thumbnails.get(id);
		if (cached?.key === key) {
			return cached.url;
		}
		try {
			const content = await this.fileService.readFile(png);
			const targetWindow = getWindow(this.element);
			const url = targetWindow.URL.createObjectURL(new Blob([content.value.buffer as Uint8Array<ArrayBuffer>], { type: 'image/png' }));
			if (this.thumbnails.get(id)?.key === key) {
				targetWindow.URL.revokeObjectURL(url);
				return this.thumbnails.get(id)?.url;
			}
			const entry = toDisposable(() => targetWindow.URL.revokeObjectURL(url));
			this.thumbnails.set(id, Object.assign(entry, { url, key, png }));
			return url;
		} catch {
			return undefined;
		}
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Draws all sheets, or the selected ones, at the chosen size. */
	async generate(): Promise<void> {
		const root = this.root;
		if (!root || this.busy || !this.available) {
			return;
		}
		const unsaved = await saveProjectEdits(this.workingCopyService, root);
		if (unsaved.length) {
			this.notificationService.warn(localize('drawings.unsaved', "Save your changes first: {0} could not be saved.", unsaved.map(u => u.fsPath).join(', ')));
			return;
		}
		const sheets = selectedSheets(this.set, this.selection);
		this.busy = true;
		this.listScheduler.cancel();
		this.frame.showProgress();
		this.update();
		try {
			const result = await this.commandService.executeCommand(DRAWINGS_GENERATE_COMMAND, generateArgs(root.fsPath, { sheets, size: this.size ?? this.settings.sheetSize }));
			if (root.toString() !== this.root?.toString()) {
				return;
			}
			const generated = readDrawingSet(result, root);
			// The pictures just drawn are read again, whatever time the backend gave.
			for (const sheet of generated?.sheets ?? []) {
				if (sheet.png) {
					this.thumbnails.deleteAndDispose(sheet.png.toString());
				}
			}
			if (generated?.sheets.length && sheets.length && this.set) {
				// Some sheets drawn again: the others stay as they were.
				const byNumber = new Map(generated.sheets.map(s => [s.number, s]));
				const previous = this.set;
				const merged = [...previous.sheets.map(s => byNumber.get(s.number) ?? s), ...generated.sheets.filter(s => !previous.sheets.some(o => o.number === s.number))];
				this.setDrawings({ ...previous, ...generated, sheets: merged, stale: merged.some(s => s.stale) });
			} else {
				this.setDrawings(generated);
			}
			this.selection.clear();
			if (generated?.problems.length) {
				this.notificationService.warn(localize('drawings.problems', "The drawings were generated with problems: {0}", generated.problems.join(' ')));
			}
		} catch (error) {
			this.notificationService.error(localize('drawings.failed', "Generate Drawings failed: {0}", toErrorMessage(error)));
		} finally {
			this.busy = false;
			this.frame.hideProgress();
			if (root.toString() === this.root?.toString()) {
				this.update(true);
				// The backend's own view of it (with the stamps), now that the files are written.
				void this.list();
			}
		}
	}

	private async openPreview(sheet: IDrawingPreviewSheet): Promise<void> {
		const existing = this.editorService.editors.find((e): e is DrawingPreviewInput => e instanceof DrawingPreviewInput && e.sheet.png.toString() === sheet.png.toString());
		existing?.update(sheet);
		await this.editorService.openEditor(existing ?? new DrawingPreviewInput(sheet), { pinned: true });
	}

	private async openExternal(resource: URI): Promise<void> {
		try {
			await this.openerService.open(resource, { openExternal: true });
		} catch (error) {
			this.notificationService.error(toErrorMessage(error));
		}
	}
}
