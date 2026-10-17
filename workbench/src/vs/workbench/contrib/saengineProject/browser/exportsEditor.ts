/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/exportsEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { StandardMouseEvent } from '../../../../base/browser/mouseEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { EXPORT_DXF_FOLDER, EXPORT_IFC_FOLDER, exportKind, ISaenginePartStatusService, REPORT_FILE } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame, IEditorFrameStatus } from './editorFrame.js';
import { ExportsEditorInput } from './exportsEditorInput.js';
import { partName } from './projectParts.js';

/*
 * The commands that make the exports. Each belongs to the part that owns the data; this page only
 * runs them. When a command is not registered (the part's module offers the export only from its
 * own editor), the page opens that part's editor instead.
 */

/** Prints the design report (saengineReport). */
export const PRINT_REPORT_COMMAND = 'saengine.report.print';
/** Writes the IFC of the building model to `11 Exports/IFC/<project>.ifc` (building model editor, part 6). */
export const EXPORT_IFC_COMMAND = 'saengine.bim.exportIfc';
/** Writes the plan of every story to `11 Exports/Floor Plan/<story>.dxf` (floor plan editor, part 5). */
export const EXPORT_DXF_COMMAND = 'saengine.floorPlan.exportDxf';
/** Exports the bill of quantities as CSV (saengineBoq). */
export const EXPORT_BOQ_CSV_COMMAND = 'saengine.boq.exportCsv';
/** The file explorer's "Reveal in File Explorer" (desktop only). */
const REVEAL_IN_OS_COMMAND = 'revealFileInOS';

type ExportKind = 'report' | 'ifc' | 'dxf' | 'csv';

interface IExportFile {
	readonly resource: URI;
	readonly name: string;
	readonly mtime: number;
}

interface IExportKind {
	readonly kind: ExportKind;
	readonly icon: ThemeIcon;
	readonly title: string;
	readonly description: string;
	/** Where its files go, as the user sees it ("11 Exports/IFC"). */
	readonly location: string;
	/** The label of the action that makes it, and of the one that makes it again. */
	readonly makeLabel: string;
	readonly againLabel: string;
	readonly command: string;
	/** The part whose editor makes it when the command is not registered. */
	readonly fallbackPart?: string;
	/** The label of the action in that editor's More Actions (...) menu, when it differs from `makeLabel`. */
	readonly fallbackLabel?: string;
	/** Why the action cannot run yet, if it cannot. */
	readonly blocked?: string;
}

function formatTime(time: number): string {
	const date = new Date(time);
	const now = new Date();
	return date.toLocaleString(undefined, {
		day: 'numeric', month: 'short', year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
		hour: '2-digit', minute: '2-digit',
	});
}

/**
 * Part 11, on the shared editor frame: the project's exports, one row each, with what they are
 * and when they were made. A made export opens, is revealed in the file manager, or is made
 * again; a missing one offers the action that makes it. The page follows the folder on disk.
 */
export class ExportsEditor extends EditorPane {

	static readonly ID = ExportsEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private list!: HTMLElement;
	private files = new Map<ExportKind, IExportFile[]>();
	private scanned = false;
	private scanVersion = 0;
	private actionsKey: string | undefined;
	/** The first control of the list, which takes the focus. */
	private firstControl: HTMLElement | undefined;

	private readonly renderDisposables = this._register(new DisposableStore());
	private readonly projectDisposables = this._register(new DisposableStore());
	private readonly scanScheduler = this._register(new RunOnceScheduler(() => void this.scan(), 200));

	private readonly revealFolderAction = this._register(new Action('saengine.exports.revealFolder', localize('exports.revealFolder', "Open Exports Folder"), ThemeIcon.asClassName(Codicon.folderOpened), true, () => this.revealFolder()));
	private readonly printAction = this._register(new Action('saengine.exports.print', localize('exports.printReport', "Print Design Report"), undefined, true, () => this.make('report')));
	private readonly ifcAction = this._register(new Action('saengine.exports.ifc', localize('exports.exportIfc', "Export IFC"), undefined, true, () => this.make('ifc')));
	private readonly dxfAction = this._register(new Action('saengine.exports.dxf', localize('exports.exportDxf', "Export DXF Floor Plans"), undefined, true, () => this.make('dxf')));
	private readonly csvAction = this._register(new Action('saengine.exports.csv', localize('exports.exportCsv', "Export Bill of Quantities as CSV..."), undefined, true, () => this.make('csv')));
	private readonly refreshAction = this._register(new Action('saengine.exports.refresh', localize('exports.refresh', "Refresh"), undefined, true, () => this.scan()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@ICommandService private readonly commandService: ICommandService,
		@IEditorService private readonly editorService: IEditorService,
		@INotificationService private readonly notificationService: INotificationService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
	) {
		super(ExportsEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.projectService.onDidChangeProject(() => this.watchProject()));
		this._register(this.statusService.onDidChange(() => this.render()));
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: ExportsEditor.ID,
			ariaLabel: localize('exports.toolbar', "Exports"),
		}));
		this.frame.element.classList.add('saengine-exports-editor');
		this.frame.setTitle(localize('exports.title', "Exports"));
		this.frame.setHelp(localize('exports.help', "What the project hands over: the design report, the building model as IFC, the floor plans as DXF and the bill of quantities as CSV. Each is made from its part and written to the 11 Exports folder."));
		this.list = $('.exports-list');
		this.scrollable = this._register(new DomScrollableElement(this.list, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('exports-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
	}

	override async setInput(input: ExportsEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.watchProject();
	}

	override clearInput(): void {
		this.projectDisposables.clear();
		this.renderDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		(this.firstControl ?? this.list).focus();
	}

	private get exportsFolder(): URI | undefined {
		const project = this.projectService.project;
		const part = partById('exports');
		return project && part ? joinPath(project.root, part.folder) : undefined;
	}

	/** Follows the open project's exports folder (the workspace folder is watched already). */
	private watchProject(): void {
		this.projectDisposables.clear();
		this.files.clear();
		this.scanned = false;
		const folder = this.exportsFolder;
		if (folder && this.input) {
			this.projectDisposables.add(this.fileService.onDidFilesChange(e => {
				if (e.affects(folder)) {
					this.scanScheduler.schedule();
				}
			}));
			void this.scan();
		}
		this.render();
	}

	private async scan(): Promise<void> {
		const folder = this.exportsFolder;
		const version = ++this.scanVersion;
		if (!folder) {
			return;
		}
		const files = new Map<ExportKind, IExportFile[]>();
		const read = async (path: string) => {
			try {
				const stat = await this.fileService.resolve(path ? joinPath(folder, path) : folder, { resolveMetadata: true });
				for (const child of stat.children ?? []) {
					const kind = child.isFile ? exportKind(path ? `${path}/${child.name}` : child.name) : undefined;
					if (kind) {
						const list = files.get(kind) ?? [];
						list.push({ resource: child.resource, name: child.name, mtime: child.mtime });
						files.set(kind, list);
					}
				}
			} catch {
				// Not made yet: the folder is created by the first export.
			}
		};
		await Promise.all(['', EXPORT_IFC_FOLDER, EXPORT_DXF_FOLDER].map(read));
		if (version !== this.scanVersion) {
			return;
		}
		for (const list of files.values()) {
			list.sort((a, b) => a.name.localeCompare(b.name));
		}
		this.files = files;
		this.scanned = true;
		this.render();
	}

	/** The kinds of export the open project has, in the order the workflow makes them. */
	private kinds(project: ISaengineProject): IExportKind[] {
		const exportsFolder = partById('exports')?.folder ?? '';
		const blockedBy = (part: string, text: string) => this.statusService.statusOf(part)?.state === 'notStarted' ? text : undefined;
		const bim = partById('bim');
		const floorPlan = partById('floorPlan');
		const boq = partById('boq');
		const kinds: IExportKind[] = [
			{
				kind: 'report', icon: Codicon.filePdf,
				title: localize('exports.report', "Design report"),
				description: localize('exports.reportDescription', "The printed calculations: loads, analysis, design checks and their limitations."),
				location: `${exportsFolder}/${REPORT_FILE}`,
				makeLabel: localize('exports.printReport', "Print Design Report"),
				againLabel: localize('exports.updateReport', "Update Report"),
				command: PRINT_REPORT_COMMAND,
			},
			{
				kind: 'ifc', icon: Codicon.layers,
				title: localize('exports.ifc', "IFC building model"),
				description: localize('exports.ifcDescription', "The building model for BIM software: elements, stories and materials."),
				location: `${exportsFolder}/${EXPORT_IFC_FOLDER}`,
				makeLabel: localize('exports.exportIfc', "Export IFC"),
				againLabel: localize('exports.exportIfcAgain', "Export IFC Again"),
				command: EXPORT_IFC_COMMAND,
				fallbackPart: 'bim',
				blocked: bim ? blockedBy('bim', localize('exports.ifcBlocked', "Build the building model ({0}) first.", partName(bim))) : undefined,
			},
		];
		// Floor plans are drawn for buildings; a special structure has none (unless some were exported before).
		if (project.type === 'building' || this.files.get('dxf')?.length) {
			kinds.push({
				kind: 'dxf', icon: Codicon.layout,
				title: localize('exports.dxf', "DXF floor plans"),
				description: localize('exports.dxfDescription', "The structural plan of every story, for CAD."),
				location: `${exportsFolder}/${EXPORT_DXF_FOLDER}`,
				makeLabel: localize('exports.exportDxf', "Export DXF Floor Plans"),
				againLabel: localize('exports.exportDxfAgain', "Export Floor Plans Again"),
				command: EXPORT_DXF_COMMAND,
				fallbackPart: 'floorPlan',
				fallbackLabel: localize('exports.exportDxfInEditor', "Export DXF"),
				blocked: floorPlan && project.type === 'building' ? blockedBy('floorPlan', localize('exports.dxfBlocked', "Draw the floor plan ({0}) first.", partName(floorPlan))) : undefined,
			});
		}
		kinds.push({
			kind: 'csv', icon: Codicon.table,
			title: localize('exports.csv', "Bill of quantities (CSV)"),
			description: localize('exports.csvDescription', "Concrete, reinforcement, formwork and steel, for a spreadsheet."),
			location: `${exportsFolder}/boq.csv`,
			makeLabel: localize('exports.exportCsvShort', "Export CSV..."),
			againLabel: localize('exports.exportCsvAgain', "Export CSV Again..."),
			command: EXPORT_BOQ_CSV_COMMAND,
			fallbackPart: 'boq',
			blocked: boq ? blockedBy('boq', localize('exports.csvBlocked', "Measure the bill of quantities ({0}) first.", partName(boq))) : undefined,
		});
		return kinds;
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		if (!this.input || !this.frame) {
			return;
		}
		this.renderDisposables.clear();
		this.firstControl = undefined;
		clearNode(this.list);
		const project = this.projectService.project;
		if (!project) {
			this.frame.setEmpty({ icon: Codicon.export, title: localize('exports.noProject', "No project is open") });
			this.frame.setStatus(undefined);
			this.updateActions(undefined);
			return;
		}
		this.frame.setEmpty(undefined);
		const kinds = this.kinds(project);
		for (const kind of kinds) {
			this.renderKind(kind);
		}
		this.updateActions(kinds);
		this.frame.setStatus(this.status());
		this.scrollable.scanDomNode();
	}

	private updateActions(kinds: readonly IExportKind[] | undefined): void {
		const has = (kind: ExportKind) => !!kinds?.some(k => k.kind === kind);
		this.printAction.label = this.files.get('report')?.length ? localize('exports.updateReport', "Update Report") : localize('exports.printReport', "Print Design Report");
		this.printAction.enabled = has('report');
		this.ifcAction.enabled = has('ifc');
		this.dxfAction.enabled = has('dxf');
		this.csvAction.enabled = has('csv') && !kinds?.find(k => k.kind === 'csv')?.blocked;
		this.revealFolderAction.enabled = !!kinds;
		const secondary: IAction[] = [this.printAction, this.ifcAction, ...(has('dxf') ? [this.dxfAction] : []), this.csvAction, new Separator(), this.refreshAction];
		const key = secondary.map(a => a.id).join();
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			this.frame.setActions([this.revealFolderAction], secondary);
		}
	}

	private status(): IEditorFrameStatus {
		if (!this.scanned) {
			return { busy: true, text: localize('exports.scanning', "Looking for the exports...") };
		}
		const all = [...this.files.values()].flat();
		if (!all.length) {
			return { text: localize('exports.none', "Nothing has been exported yet. Exports are written to {0}.", partById('exports')?.folder ?? '') };
		}
		const latest = Math.max(...all.map(f => f.mtime));
		return {
			text: all.length === 1
				? localize('exports.countOne', "1 file in {0}, made {1}.", partById('exports')?.folder ?? '', formatTime(latest))
				: localize('exports.count', "{0} files in {1}, the latest made {2}.", all.length, partById('exports')?.folder ?? '', formatTime(latest)),
		};
	}

	private renderKind(kind: IExportKind): void {
		const files = this.files.get(kind.kind) ?? [];
		const made = files.length > 0;
		const section = append(this.list, $('section.exports-kind', { 'aria-label': kind.title }));
		section.classList.toggle('made', made);
		const row = append(section, $('.exports-row'));
		append(row, $(`span.exports-icon${ThemeIcon.asCSSSelector(kind.icon)}`));
		const text = append(row, $('.exports-text'));
		append(text, $('.exports-title', undefined, kind.title));
		append(text, $('.exports-description', undefined, made || !kind.blocked ? kind.description : kind.blocked));
		const when = append(row, $('.exports-when'));
		const actions = append(row, $('.exports-actions'));
		this.renderDisposables.add(addDisposableListener(row, EventType.CONTEXT_MENU, (e: MouseEvent) => {
			e.preventDefault();
			this.showContextMenu(kind, files.length === 1 ? files[0] : undefined, e);
		}));

		if (!made) {
			when.textContent = this.scanned ? localize('exports.notMade', "Not made yet") : '';
			when.classList.add('muted');
			const button = this.renderDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			button.label = kind.makeLabel;
			button.enabled = !kind.blocked || kind.kind !== 'csv';
			this.renderDisposables.add(button.onDidClick(() => this.make(kind.kind)));
			this.firstControl ??= button.element;
			return;
		}

		const again = this.renderDisposables.add(this.frame.createIconButton(actions, Codicon.refresh, kind.againLabel, () => void this.make(kind.kind)));
		this.firstControl ??= again.element;
		if (files.length === 1) {
			// One file: the row is the file.
			const file = files[0];
			when.textContent = formatTime(file.mtime);
			this.renderFileButtons(actions, file, kind);
			return;
		}
		when.textContent = localize('exports.fileCount', "{0} files", files.length);
		when.classList.add('muted');
		const list = append(section, $('ul.exports-files'));
		for (const file of files) {
			const item = append(list, $('li.exports-file'));
			append(item, $('span.exports-file-name', undefined, file.name));
			append(item, $('span.exports-when', undefined, formatTime(file.mtime)));
			this.renderFileButtons(append(item, $('.exports-actions')), file, kind);
			this.renderDisposables.add(addDisposableListener(item, EventType.CONTEXT_MENU, (e: MouseEvent) => {
				e.preventDefault();
				e.stopPropagation();
				this.showContextMenu(kind, file, e);
			}));
		}
	}

	private renderFileButtons(container: HTMLElement, file: IExportFile, kind: IExportKind): void {
		this.renderDisposables.add(this.frame.createIconButton(container, kind.kind === 'dxf' ? Codicon.goToFile : Codicon.linkExternal, localize('exports.openFile', "Open {0}", file.name), () => void this.openFile(file, kind)));
		if (CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
			this.renderDisposables.add(this.frame.createIconButton(container, Codicon.folderOpened, localize('exports.reveal', "Reveal in File Explorer"), () => void this.reveal(file.resource)));
		}
	}

	private showContextMenu(kind: IExportKind, file: IExportFile | undefined, e: MouseEvent): void {
		const actions: IAction[] = [];
		if (file) {
			actions.push(new Action('saengine.exports.open', localize('exports.open', "Open"), undefined, true, () => this.openFile(file, kind)));
			if (CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
				actions.push(new Action('saengine.exports.reveal', localize('exports.reveal', "Reveal in File Explorer"), undefined, true, () => this.reveal(file.resource)));
			}
			actions.push(new Separator());
		}
		actions.push(new Action('saengine.exports.make', this.files.get(kind.kind)?.length ? kind.againLabel : kind.makeLabel, undefined, true, () => this.make(kind.kind)));
		const event = new StandardMouseEvent(getWindow(this.list), e);
		this.contextMenuService.showContextMenu({ getAnchor: () => event, getActions: () => actions });
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Runs the command that makes `kind`, or opens the editor of the part that makes it. */
	private async make(kindId: ExportKind): Promise<void> {
		const project = this.projectService.project;
		const kind = project && this.kinds(project).find(k => k.kind === kindId);
		if (!project || !kind) {
			return;
		}
		try {
			if (CommandsRegistry.getCommand(kind.command)) {
				await this.commandService.executeCommand(kind.command);
				return;
			}
			const part = kind.fallbackPart ? partById(kind.fallbackPart) : undefined;
			if (part?.mainFile) {
				await this.editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
				this.notificationService.info(localize('exports.useEditorMore', "{0}: choose \"{1}\" from this editor's More Actions (...) menu.", partName(part), kind.fallbackLabel ?? kind.makeLabel));
			}
		} catch (error) {
			this.notificationService.error(localize('exports.failed', "{0} failed: {1}", kind.makeLabel, toErrorMessage(error)));
		}
	}

	/** Drawings open in SAEngine's CAD editor; the report, IFC and CSV in the system's own application. */
	private async openFile(file: IExportFile, kind: IExportKind): Promise<void> {
		if (kind.kind === 'dxf') {
			await this.editorService.openEditor({ resource: file.resource, options: { pinned: true } });
		} else {
			await this.openerService.open(file.resource, { openExternal: true });
		}
	}

	private async reveal(resource: URI): Promise<void> {
		await this.commandService.executeCommand(REVEAL_IN_OS_COMMAND, resource);
	}

	/** Opens the exports folder in the system's file manager (created if no export made it yet). */
	private async revealFolder(): Promise<void> {
		const folder = this.exportsFolder;
		if (!folder) {
			return;
		}
		try {
			if (!await this.fileService.exists(folder)) {
				await this.fileService.createFolder(folder);
			}
			await this.openerService.open(folder, { openExternal: true });
		} catch (error) {
			this.notificationService.error(toErrorMessage(error));
		}
	}
}
