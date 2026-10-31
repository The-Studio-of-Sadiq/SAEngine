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
import { disposableTimeout, RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { basename, joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IStorageService, StorageScope } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { EXPORT_DXF_FOLDER, EXPORT_IFC_FOLDER, exportKind, ISaenginePartStatusService, REPORT_FILE, reportAnalysisStale, WORD_REPORT_FILE } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { DRAWINGS_GENERATE_COMMAND } from './drawingsModel.js';
import { DrawingsSection } from './drawingsSection.js';
import { EditorFrame, IEditorFrameStatus } from './editorFrame.js';
import { ExportsEditorInput } from './exportsEditorInput.js';
import { LAST_ARCHIVE_STORAGE_KEY, readLastArchive } from './projectArchiveFlows.js';
import { ARCHIVE_EXPORT_COMMAND, ARCHIVE_IMPORT_COMMAND, CAD_OPEN_COMMAND, EXPORT_ARCHIVE_UI_COMMAND, lastArchiveDescription, OPEN_ARCHIVE_UI_COMMAND, OPEN_DXF_IN_CAD_UI_COMMAND } from './projectArchiveModel.js';
import { partName } from './projectParts.js';
import { formatDate } from '../../../services/saengineProject/common/formatting.js';

/*
 * The commands that make the exports. Each belongs to the part that owns the data; this page only
 * runs them. When a command is not registered (the part's module offers the export only from its
 * own editor), the page opens that part's editor instead.
 */

/** Prints the design report (saengineReport). */
export const PRINT_REPORT_COMMAND = 'saengine.report.print';
/** Writes the same design report as Word, `11 Exports/report.docx` (saengineReport). */
export const EXPORT_WORD_REPORT_COMMAND = 'saengine.report.exportWord';
/** Writes the IFC of the building model to `11 Exports/IFC/<project>.ifc` (building model editor, part 6). */
export const EXPORT_IFC_COMMAND = 'saengine.bim.exportIfc';
/** Writes the plan of every story to `11 Exports/Floor Plan/<story>.dxf` (floor plan editor, part 5). */
export const EXPORT_DXF_COMMAND = 'saengine.floorPlan.exportDxf';
/** Exports the bill of quantities as CSV (saengineBoq). */
export const EXPORT_BOQ_CSV_COMMAND = 'saengine.boq.exportCsv';
/**
 * Writes the building as an ETABS text model to `11 Exports/ETABS/<project>.e2k` with its export
 * report beside it (`saengine.exporters.etabs`): `{projectRoot}` -> `{path, reportPath, report}`
 * or `{error}`.
 */
export const EXPORT_E2K_COMMAND = 'saengine.export.e2k';
/** The folder of `11 Exports` the ETABS export writes to. */
export const EXPORT_E2K_FOLDER = 'ETABS';
/** The file explorer's "Reveal in File Explorer" (desktop only). */
const REVEAL_IN_OS_COMMAND = 'revealFileInOS';

type ExportKind = 'report' | 'word' | 'ifc' | 'dxf' | 'e2k' | 'csv';

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
	/** Why the file made is out of date, if it is. */
	readonly stale?: string;
	/** What the row says while the export runs. */
	readonly runningLabel: string;
}

/** The ETABS export's answer, read defensively. */
export interface IE2kExportOutcome {
	readonly path?: string;
	readonly reportPath?: string;
	/** The report as text to read (Markdown), beside the JSON one. */
	readonly readablePath?: string;
	/** "120 frames, 36 areas exported", from the report's counts. */
	readonly exported: string;
	/** How many kinds of item were approximated, and left out. */
	readonly approximated: number;
	readonly skipped: number;
	readonly warnings: number;
	readonly error?: string;
}

export function readE2kExport(value: unknown): IE2kExportOutcome {
	const record = typeof value === 'object' && value !== null ? value as { readonly [key: string]: unknown } : {};
	const report = typeof record.report === 'object' && record.report !== null ? record.report as { readonly [key: string]: unknown } : {};
	const exported = typeof report.exported === 'object' && report.exported !== null ? report.exported as { readonly [key: string]: unknown } : {};
	const length = (key: string) => Array.isArray(report[key]) ? (report[key] as unknown[]).length : 0;
	const outcome = {
		exported: Object.entries(exported).filter(([, n]) => typeof n === 'number' && n > 0).map(([what, n]) => `${n} ${countWords(what)}`).join(', '),
		approximated: length('approximated'),
		skipped: length('skipped'),
		warnings: length('warnings'),
	};
	if (typeof record.error === 'string' && record.error) {
		return { ...outcome, error: record.error };
	}
	if (typeof record.path !== 'string') {
		return { ...outcome, error: localize('exports.e2kNoAnswer', "The backend did not say where it wrote the file.") };
	}
	return {
		...outcome, path: record.path,
		...(typeof record.reportPath === 'string' ? { reportPath: record.reportPath } : {}),
		...(typeof record.readablePath === 'string' ? { readablePath: record.readablePath } : {}),
	};
}

/** "memberLineLoads" -> "member line loads", as the export report's counts are keyed. */
function countWords(key: string): string {
	return key.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
}

/** How long the page says a file is opening in the system's viewer (it starts in a few seconds). */
const OPENING_STATUS_MS = 6000;

function formatTime(time: number): string {
	const date = new Date(time);
	const now = new Date();
	return formatDate(date, {
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
	private drawings!: DrawingsSection;
	private files = new Map<ExportKind, IExportFile[]>();
	private scanned = false;
	/** The last archive written from this project, if it is still where it was written (with its size now). */
	private archive: { readonly resource: URI; readonly size?: number; readonly time: number } | undefined;
	private scanVersion = 0;
	private actionsKey: string | undefined;
	/** The first control of the list, which takes the focus. */
	private firstControl: HTMLElement | undefined;
	/** The exports being made now: their rows say so and their buttons wait. */
	private readonly running = new Set<ExportKind>();
	/** How many elements the building model has (undefined: not read, or no building model). */
	private bimElements: number | undefined;

	private readonly renderDisposables = this._register(new DisposableStore());
	private readonly projectDisposables = this._register(new DisposableStore());
	private readonly scanScheduler = this._register(new RunOnceScheduler(() => void this.scan(), 200));

	private readonly revealFolderAction = this._register(new Action('saengine.exports.revealFolder', localize('exports.revealFolder', "Open Exports Folder"), ThemeIcon.asClassName(Codicon.folderOpened), true, () => this.revealFolder()));
	private readonly printAction = this._register(new Action('saengine.exports.print', localize('exports.printReport', "Print Design Report"), undefined, true, () => this.make('report')));
	private readonly ifcAction = this._register(new Action('saengine.exports.ifc', localize('exports.exportIfc', "Export IFC"), undefined, true, () => this.make('ifc')));
	private readonly dxfAction = this._register(new Action('saengine.exports.dxf', localize('exports.exportDxf', "Export DXF Floor Plans"), undefined, true, () => this.make('dxf')));
	private readonly csvAction = this._register(new Action('saengine.exports.csv', localize('exports.exportCsv', "Export Bill of Quantities as CSV..."), undefined, true, () => this.make('csv')));
	private readonly e2kAction = this._register(new Action('saengine.exports.e2k', localize('exports.exportE2k', "Export to ETABS (.e2k)"), undefined, true, () => this.make('e2k')));
	private readonly archiveAction = this._register(new Action('saengine.exports.archive', localize('exports.exportArchive', "Export Project (.civil)..."), undefined, true, () => this.exportArchive()));
	private readonly openArchiveAction = this._register(new Action('saengine.exports.openArchive', localize('exports.openArchive', "Open Project Archive..."), undefined, true, () => this.openArchive()));
	private readonly drawingsAction = this._register(new Action('saengine.exports.drawings', localize('exports.generateDrawings', "Generate Drawings"), undefined, true, () => this.drawings.generate()));
	private readonly refreshAction = this._register(new Action('saengine.exports.refresh', localize('exports.refresh', "Refresh"), undefined, true, () => this.scan()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService private readonly storage: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@ICommandService private readonly commandService: ICommandService,
		@IEditorService private readonly editorService: IEditorService,
		@INotificationService private readonly notificationService: INotificationService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IProgressService private readonly progressService: IProgressService,
	) {
		super(ExportsEditor.ID, group, telemetryService, themeService, storage);
		this._register(this.storage.onDidChangeValue(StorageScope.WORKSPACE, LAST_ARCHIVE_STORAGE_KEY, this._store)(() => this.scanScheduler.schedule(0)));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === ARCHIVE_EXPORT_COMMAND || id === ARCHIVE_IMPORT_COMMAND || id === CAD_OPEN_COMMAND || id === DRAWINGS_GENERATE_COMMAND || id === EXPORT_E2K_COMMAND) {
				this.render();
			}
		}));
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
		this.frame.setHelp(localize('exports.help', "What the project hands over: the design report, the building model as IFC, the floor plans as DXF, the analysis model for ETABS (.e2k), the structural drawings (DXF sheets for LibreCAD, one PDF set and the bar bending schedule) and the bill of quantities as CSV. Each is made from its part and written to the 11 Exports folder. The project archive (.civil) holds the whole project in one file."));
		this.list = $('.exports-list');
		this.scrollable = this._register(new DomScrollableElement(this.list, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('exports-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this.drawings = this._register(this.instantiationService.createInstance(DrawingsSection, this.frame));
		this._register(this.drawings.onDidChange(() => {
			this.scrollable.scanDomNode();
			// The footer counts the drawing sheets too.
			if (this.input && this.projectService.project) {
				this.frame.setStatus(this.status());
			}
		}));
	}

	override async setInput(input: ExportsEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.watchProject();
	}

	override clearInput(): void {
		this.projectDisposables.clear();
		this.drawings.setProject(undefined);
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
		this.archive = undefined;
		this.bimElements = undefined;
		this.scanned = false;
		this.drawings.setProject(this.input ? this.projectService.project?.root : undefined);
		const folder = this.exportsFolder;
		if (folder && this.input) {
			this.projectDisposables.add(this.fileService.onDidFilesChange(e => {
				if (e.affects(folder) || (this.bimFile && e.contains(this.bimFile))) {
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
					const kind = !child.isFile ? undefined
						: path === EXPORT_E2K_FOLDER ? (child.name.toLowerCase().endsWith('.e2k') ? 'e2k' : undefined)
							: !path && child.name.toLowerCase() === WORD_REPORT_FILE ? 'word'
								: exportKind(path ? `${path}/${child.name}` : child.name);
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
		const [archive, bimElements] = await Promise.all([this.findLastArchive(), this.countBimElements(), ...['', EXPORT_IFC_FOLDER, EXPORT_DXF_FOLDER, EXPORT_E2K_FOLDER].map(read)]);
		if (version !== this.scanVersion) {
			return;
		}
		this.archive = archive;
		this.bimElements = bimElements;
		for (const list of files.values()) {
			list.sort((a, b) => a.name.localeCompare(b.name));
		}
		this.files = files;
		this.scanned = true;
		this.render();
	}

	private get bimFile(): URI | undefined {
		const project = this.projectService.project;
		const part = partById('bim');
		return project && part?.mainFile ? joinPath(project.root, part.folder, part.mainFile) : undefined;
	}

	/** The elements of the building model on disk; undefined when there is none or it cannot be read. */
	private async countBimElements(): Promise<number | undefined> {
		const file = this.bimFile;
		if (!file) {
			return undefined;
		}
		try {
			const model = JSON.parse((await this.fileService.readFile(file)).value.toString());
			return Array.isArray(model?.elements) ? model.elements.length : undefined;
		} catch {
			return undefined;
		}
	}

	/**
	 * The last archive written from this project, if it is still there: it may have been saved
	 * anywhere, and moved or deleted since (then the row offers a new export).
	 */
	private async findLastArchive(): Promise<{ readonly resource: URI; readonly size?: number; readonly time: number } | undefined> {
		const last = readLastArchive(this.storage.get(LAST_ARCHIVE_STORAGE_KEY, StorageScope.WORKSPACE));
		if (!last) {
			return undefined;
		}
		const resource = URI.file(last.path);
		try {
			const stat = await this.fileService.stat(resource);
			return stat.isFile ? { resource, size: stat.size, time: last.time } : undefined;
		} catch {
			return undefined;
		}
	}

	/** The kinds of export the open project has, in the order the workflow makes them. */
	private kinds(project: ISaengineProject): IExportKind[] {
		const exportsFolder = partById('exports')?.folder ?? '';
		const blockedBy = (part: string, text: string) => this.statusService.statusOf(part)?.state === 'notStarted' ? text : undefined;
		const bim = partById('bim');
		const floorPlan = partById('floorPlan');
		const boq = partById('boq');
		const fem = partById('fem');
		// An empty building model has nothing to export, whatever its status says.
		const emptyModel = this.emptyModel();
		// A failing design is not an out-of-date analysis: its report shows the failures.
		// The PDF and the Word report are drawn from the same document: out of date for the same reasons.
		const stale = (printed: boolean) => fem && printed && reportAnalysisStale(this.statusService.statusOf('fem')?.state)
			? localize('exports.reportStale', "Out of date: the analysis ({0}) is not current, so the report does not show this model. Run the analysis and update the report.", partName(fem))
			: printed && this.statusService.statusOf('exports')?.state === 'stale'
				? localize('exports.reportStaleDesign', "Out of date: the design checks or the analysis ran after the report was printed. Update the report.")
				: undefined;
		const reportStale = stale(!!this.files.get('report')?.length);
		const wordStale = stale(!!this.files.get('word')?.length);
		const kinds: IExportKind[] = [
			{
				kind: 'report', icon: Codicon.filePdf,
				title: localize('exports.report', "Design report"),
				description: localize('exports.reportDescription', "The printed calculations: loads, analysis, design checks and their limitations."),
				location: `${exportsFolder}/${REPORT_FILE}`,
				makeLabel: localize('exports.printReport', "Print Design Report"),
				againLabel: localize('exports.updateReport', "Update Report"),
				command: PRINT_REPORT_COMMAND,
				blocked: emptyModel,
				stale: reportStale,
				runningLabel: localize('exports.reportRunning', "Printing the report..."),
			},
			{
				kind: 'word', icon: Codicon.fileText,
				title: localize('exports.wordReport', "Design report (Word)"),
				description: localize('exports.wordReportDescription', "The same report as an editable Word file, as the report template chooses (Configure Design Report)."),
				location: `${exportsFolder}/${WORD_REPORT_FILE}`,
				makeLabel: localize('exports.exportWord', "Export Word Report"),
				againLabel: localize('exports.updateWord', "Update Word Report"),
				command: EXPORT_WORD_REPORT_COMMAND,
				blocked: emptyModel,
				stale: wordStale,
				runningLabel: localize('exports.wordRunning', "Writing the Word report..."),
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
				blocked: emptyModel ?? (bim ? blockedBy('bim', localize('exports.ifcBlocked', "Build the building model ({0}) first.", partName(bim))) : undefined),
				runningLabel: localize('exports.ifcRunning', "Exporting the IFC..."),
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
				blocked: emptyModel ?? (floorPlan && project.type === 'building' ? blockedBy('floorPlan', localize('exports.dxfBlocked', "Draw the floor plan ({0}) first.", partName(floorPlan))) : undefined),
				runningLabel: localize('exports.dxfRunning', "Exporting the floor plans..."),
			});
		}
		kinds.push({
			kind: 'e2k', icon: Codicon.symbolStructure,
			title: localize('exports.e2k', "ETABS model (.e2k)"),
			description: localize('exports.e2kDescription', "The analysis model as an ETABS text file, with SAEngine's BNBC wind and earthquake story forces, and a report of what could not be carried over."),
			location: `${exportsFolder}/${EXPORT_E2K_FOLDER}`,
			makeLabel: localize('exports.exportE2k', "Export to ETABS (.e2k)"),
			againLabel: localize('exports.exportE2kAgain', "Export to ETABS Again"),
			command: EXPORT_E2K_COMMAND,
			blocked: emptyModel ?? (bim ? blockedBy('bim', localize('exports.e2kBlocked', "Build the building model ({0}) first.", partName(bim))) : undefined),
			runningLabel: localize('exports.e2kRunning', "Exporting to ETABS..."),
		});
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
			runningLabel: localize('exports.csvRunning', "Exporting the CSV..."),
		});
		return kinds;
	}

	/** Why no export can be made yet: the building model has no elements (the drawings too). */
	private emptyModel(): string | undefined {
		const bim = partById('bim');
		return this.bimElements === 0 && bim ? localize('exports.emptyModel', "The building model ({0}) has no elements yet: draw the floor plan and build the model first.", partName(bim)) : undefined;
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		if (!this.input || !this.frame) {
			return;
		}
		this.renderDisposables.clear();
		this.firstControl = undefined;
		// The drawings section is moved, not rebuilt: its focused control gets the focus back.
		const restoreDrawingsFocus = this.drawings.captureFocus();
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
		// The drawings render themselves (they follow the backend, not the folder).
		this.drawings.setBlocked(this.emptyModel());
		append(this.list, this.drawings.element);
		restoreDrawingsFocus();
		this.renderArchive(project);
		this.updateActions(kinds);
		this.frame.setStatus(this.status());
		this.scrollable.scanDomNode();
	}

	private updateActions(kinds: readonly IExportKind[] | undefined): void {
		const has = (kind: ExportKind) => !!kinds?.some(k => k.kind === kind);
		const can = (kind: ExportKind) => has(kind) && !this.running.has(kind) && !kinds?.find(k => k.kind === kind)?.blocked;
		this.printAction.label = this.files.get('report')?.length ? localize('exports.updateReport', "Update Report") : localize('exports.printReport', "Print Design Report");
		this.printAction.enabled = can('report');
		this.ifcAction.enabled = can('ifc');
		this.dxfAction.enabled = can('dxf');
		this.e2kAction.enabled = can('e2k') && !!CommandsRegistry.getCommand(EXPORT_E2K_COMMAND);
		this.csvAction.enabled = can('csv');
		this.drawingsAction.enabled = !!kinds && !!CommandsRegistry.getCommand(DRAWINGS_GENERATE_COMMAND) && !this.emptyModel();
		this.revealFolderAction.enabled = !!kinds;
		this.archiveAction.enabled = !!kinds && !!CommandsRegistry.getCommand(ARCHIVE_EXPORT_COMMAND);
		this.openArchiveAction.enabled = !!CommandsRegistry.getCommand(ARCHIVE_IMPORT_COMMAND);
		const secondary: IAction[] = [this.printAction, this.ifcAction, ...(has('dxf') ? [this.dxfAction] : []), this.e2kAction, this.drawingsAction, this.csvAction, new Separator(), this.archiveAction, this.openArchiveAction, new Separator(), this.refreshAction];
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
		const drawings = this.drawings.generated;
		const folder = partById('exports')?.folder ?? '';
		if (!all.length && !drawings) {
			return { text: localize('exports.none', "Nothing has been exported yet. Exports are written to {0}.", folder) };
		}
		const latest = formatTime(Math.max(...all.map(f => f.mtime), drawings?.time ?? 0));
		const files = all.length === 1 ? localize('exports.oneFile', "1 file") : localize('exports.files', "{0} files", all.length);
		const sheets = drawings?.sheets === 1 ? localize('exports.oneSheet', "1 drawing sheet") : localize('exports.sheets', "{0} drawing sheets", drawings?.sheets ?? 0);
		const what = !drawings ? files : !all.length ? sheets : localize('exports.filesAndSheets', "{0} and {1}", files, sheets);
		return { text: localize('exports.count', "{0} in {1}, the latest made {2}.", what, folder, latest) };
	}

	private renderKind(kind: IExportKind): void {
		const files = this.files.get(kind.kind) ?? [];
		const made = files.length > 0;
		const running = this.running.has(kind.kind);
		const section = append(this.list, $('section.exports-kind', { 'aria-label': kind.title }));
		section.classList.toggle('made', made && !kind.stale);
		section.classList.toggle('stale', made && !!kind.stale);
		const row = append(section, $('.exports-row'));
		append(row, $(`span.exports-icon${ThemeIcon.asCSSSelector(kind.icon)}`));
		const text = append(row, $('.exports-text'));
		append(text, $('.exports-title', undefined, kind.title));
		const description = made ? kind.stale ?? kind.description : kind.blocked ?? kind.description;
		append(text, $('.exports-description', { title: description }, description));
		const when = append(row, $('.exports-when'));
		const actions = append(row, $('.exports-actions'));
		this.renderDisposables.add(addDisposableListener(row, EventType.CONTEXT_MENU, (e: MouseEvent) => {
			e.preventDefault();
			this.showContextMenu(kind, files.length === 1 ? files[0] : undefined, e);
		}));
		const showRunning = () => {
			clearNode(when);
			append(when, $(`span${ThemeIcon.asCSSSelector(ThemeIcon.modify(Codicon.loading, 'spin'))}`));
			append(when, $('span', undefined, kind.runningLabel));
			when.classList.remove('muted');
		};

		if (!made) {
			when.textContent = this.scanned ? localize('exports.notMade', "Not made yet") : '';
			when.classList.add('muted');
			const button = this.renderDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			button.label = kind.makeLabel;
			button.enabled = !kind.blocked && !running;
			if (kind.blocked) {
				button.setTitle(kind.blocked);
			}
			this.renderDisposables.add(button.onDidClick(() => this.make(kind.kind)));
			this.firstControl ??= button.element;
			if (running) {
				showRunning();
			}
			return;
		}

		const again = this.textButton(actions, kind.againLabel, () => void this.make(kind.kind));
		again.enabled = !running && !kind.blocked;
		if (kind.blocked) {
			again.setTitle(kind.blocked);
		}
		this.firstControl ??= again.element;
		if (files.length === 1) {
			// One file: the row is the file.
			const file = files[0];
			when.textContent = kind.stale ? localize('exports.staleWhen', "{0}, out of date", formatTime(file.mtime)) : formatTime(file.mtime);
			if (running) {
				showRunning();
			}
			this.renderFileButtons(actions, file, kind);
			return;
		}
		when.textContent = localize('exports.fileCount', "{0} files", files.length);
		when.classList.add('muted');
		if (running) {
			showRunning();
		}
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

	/** The row's buttons say what they do in words (an icon alone was not understood). */
	private renderFileButtons(container: HTMLElement, file: IExportFile, kind: IExportKind): void {
		this.textButton(container, localize('exports.open', "Open"), () => void this.openFile(file, kind)).setTitle(localize('exports.openFile', "Open {0}", file.name));
		if (kind.kind === 'dxf') {
			this.textButton(container, this.cadLabel(), () => void this.openInCad(file));
		}
		if (CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
			this.textButton(container, localize('exports.revealShort', "Show in Folder"), () => void this.reveal(file.resource)).setTitle(localize('exports.reveal', "Reveal in File Explorer"));
		}
	}

	private textButton(container: HTMLElement, label: string, run: () => void): Button {
		const button = this.renderDisposables.add(new Button(container, { ...defaultButtonStyles, secondary: true }));
		button.label = label;
		this.renderDisposables.add(button.onDidClick(run));
		return button;
	}

	private showContextMenu(kind: IExportKind, file: IExportFile | undefined, e: MouseEvent): void {
		const actions: IAction[] = [];
		const enabled = !this.running.has(kind.kind) && !kind.blocked;
		if (file) {
			actions.push(new Action('saengine.exports.open', localize('exports.open', "Open"), undefined, true, () => this.openFile(file, kind)));
			if (kind.kind === 'dxf') {
				actions.push(new Action('saengine.exports.openInCad', this.cadLabel(), undefined, true, () => this.openInCad(file)));
			}
			if (CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
				actions.push(new Action('saengine.exports.reveal', localize('exports.reveal', "Reveal in File Explorer"), undefined, true, () => this.reveal(file.resource)));
			}
			actions.push(new Separator());
		}
		actions.push(new Action('saengine.exports.make', this.files.get(kind.kind)?.length ? kind.againLabel : kind.makeLabel, undefined, enabled, () => this.make(kind.kind)));
		const event = new StandardMouseEvent(getWindow(this.list), e);
		this.contextMenuService.showContextMenu({ getAnchor: () => event, getActions: () => actions });
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Runs the command that makes `kind`, or opens the editor of the part that makes it. */
	private async make(kindId: ExportKind): Promise<void> {
		const project = this.projectService.project;
		const kind = project && this.kinds(project).find(k => k.kind === kindId);
		if (!project || !kind || this.running.has(kindId) || kind.blocked) {
			return;
		}
		try {
			if (CommandsRegistry.getCommand(kind.command)) {
				// The row says the export is running and its buttons wait until it is done.
				this.running.add(kindId);
				this.render();
				try {
					if (kindId === 'e2k') {
						await this.exportE2k(project);
					} else {
						await this.commandService.executeCommand(kind.command);
					}
				} finally {
					this.running.delete(kindId);
					this.render();
					this.scanScheduler.schedule(0);
				}
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

	/** The ETABS export, with its progress, and a notice of what it wrote and left out. */
	private async exportE2k(project: ISaengineProject): Promise<void> {
		const answer = await this.progressService.withProgress({
			location: ProgressLocation.Notification,
			title: localize('exports.e2kProgress', "Exporting {0} to ETABS", project.name),
		}, progress => {
			progress.report({ message: localize('exports.e2kDeriving', "deriving the analysis model for the wind and earthquake story forces...") });
			return this.commandService.executeCommand(EXPORT_E2K_COMMAND, { projectRoot: project.root.fsPath });
		});
		const outcome = readE2kExport(answer);
		if (outcome.error || !outcome.path) {
			this.notificationService.error(localize('exports.e2kFailed', "The ETABS export failed: {0}", outcome.error ?? ''));
			return;
		}
		const file = URI.file(outcome.path);
		// The readable report (Markdown) when the backend wrote one, else the JSON.
		const readable = outcome.readablePath ?? outcome.reportPath;
		const report = readable ? URI.file(readable) : undefined;
		const leftOut = outcome.skipped || outcome.approximated
			? localize('exports.e2kLeftOut', "{0} kinds of item left out and {1} approximated: read the export report before using the model.", outcome.skipped, outcome.approximated)
			: localize('exports.e2kAllOut', "Nothing was left out.");
		const message = localize('exports.e2kDone', "Exported {0} to {1}/{2}{3}. {4}",
			basename(file), partById('exports')?.folder ?? '', EXPORT_E2K_FOLDER, outcome.exported ? ` (${outcome.exported})` : '', leftOut);
		this.notificationService.prompt(outcome.warnings || outcome.skipped ? Severity.Warning : Severity.Info, message, [
			...(report ? [{ label: localize('exports.e2kShowReport', "Show Export Report"), run: () => void this.showReport(report) }] : []),
			...(CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND) ? [{ label: localize('exports.reveal', "Reveal in File Explorer"), run: () => void this.reveal(file) }] : []),
		]);
	}

	/** The export report: Markdown in its preview (the built-in Markdown extension), else as text. */
	private async showReport(report: URI): Promise<void> {
		if (report.path.endsWith('.md')) {
			try {
				await this.commandService.executeCommand('markdown.showPreview', report);
				return;
			} catch {
				// No Markdown extension in this build: the text editor below.
			}
		}
		await this.editorService.openEditor({ resource: report, options: { pinned: true } });
	}

	/** Drawings open in SAEngine's CAD editor; the report, IFC and CSV in the system's own application. */
	private async openFile(file: IExportFile, kind: IExportKind): Promise<void> {
		if (kind.kind === 'dxf' || kind.kind === 'e2k') {
			await this.editorService.openEditor({ resource: file.resource, options: { pinned: true } });
		} else {
			// The system's viewer can take seconds to appear: the page says it is on its way.
			this.frame.setStatus({ busy: true, text: localize('exports.opening', "Opening {0} in the system's viewer...", file.name) });
			try {
				await this.openerService.open(file.resource, { openExternal: true });
			} finally {
				this.renderDisposables.add(disposableTimeout(() => this.frame.setStatus(this.status()), OPENING_STATUS_MS));
			}
		}
	}

	/** "Open in LibreCAD" with the bundled LibreCAD; "Open in CAD Program" with the system's. */
	private cadLabel(): string {
		return CommandsRegistry.getCommand(CAD_OPEN_COMMAND)
			? localize('exports.openInLibreCad', "Open in LibreCAD")
			: localize('exports.openInCadProgram', "Open in CAD Program");
	}

	private async openInCad(file: IExportFile): Promise<void> {
		await this.commandService.executeCommand(OPEN_DXF_IN_CAD_UI_COMMAND, file.resource);
	}

	private async exportArchive(): Promise<void> {
		try {
			await this.commandService.executeCommand(EXPORT_ARCHIVE_UI_COMMAND);
		} catch (error) {
			this.notificationService.error(toErrorMessage(error));
		}
	}

	/**
	 * The whole project as one `.civil` file, to send or keep. It is written outside the project
	 * folder (an archive never holds another one), so the row shows the last one written from here,
	 * where it is, while it is still there.
	 */
	private renderArchive(project: ISaengineProject): void {
		const last = this.archive;
		const available = !!CommandsRegistry.getCommand(ARCHIVE_EXPORT_COMMAND);
		const title = localize('exports.archive', "Project archive (.civil)");
		const section = append(this.list, $('section.exports-kind.exports-archive', { 'aria-label': title }));
		section.classList.toggle('made', !!last);
		const row = append(section, $('.exports-row'));
		append(row, $(`span.exports-icon${ThemeIcon.asCSSSelector(Codicon.package)}`));
		const text = append(row, $('.exports-text'));
		append(text, $('.exports-title', undefined, title));
		append(text, $('.exports-description', undefined, !available
			? localize('exports.archiveUnavailable', "Project archives are not available in this build of SAEngine.")
			: last
				? lastArchiveDescription(last.resource, last.size, project.root)
				: localize('exports.archiveDescription', "The whole project in one file, to send to a colleague or keep with an issue. It opens with Open Project Archive.")));
		if (last) {
			row.title = last.resource.fsPath;
		}
		const when = append(row, $('.exports-when'));
		const actions = append(row, $('.exports-actions'));
		this.renderDisposables.add(addDisposableListener(row, EventType.CONTEXT_MENU, (e: MouseEvent) => {
			e.preventDefault();
			const menu: IAction[] = [new Action('saengine.exports.archiveMake', last ? localize('exports.archiveAgain', "Export Project Again...") : localize('exports.exportArchive', "Export Project (.civil)..."), undefined, available, () => this.exportArchive())];
			if (last && CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
				menu.push(new Action('saengine.exports.archiveReveal', localize('exports.reveal', "Reveal in File Explorer"), undefined, true, () => this.reveal(last.resource)));
			}
			menu.push(new Separator(), new Action('saengine.exports.archiveOpen', localize('exports.openArchive', "Open Project Archive..."), undefined, !!CommandsRegistry.getCommand(ARCHIVE_IMPORT_COMMAND), () => this.openArchive()));
			const event = new StandardMouseEvent(getWindow(this.list), e);
			this.contextMenuService.showContextMenu({ getAnchor: () => event, getActions: () => menu });
		}));
		if (CommandsRegistry.getCommand(ARCHIVE_IMPORT_COMMAND)) {
			this.textButton(actions, localize('exports.openArchiveShort', "Open Archive..."), () => void this.openArchive()).setTitle(localize('exports.openArchiveReceived', "Open Project Archive... (one you received: unpacks and opens it)"));
		}
		if (last && available) {
			when.textContent = formatTime(last.time);
			const again = this.textButton(actions, localize('exports.archiveAgain', "Export Project Again..."), () => void this.exportArchive());
			this.firstControl ??= again.element;
			if (CommandsRegistry.getCommand(REVEAL_IN_OS_COMMAND)) {
				this.textButton(actions, localize('exports.revealShort', "Show in Folder"), () => void this.reveal(last.resource)).setTitle(localize('exports.reveal', "Reveal in File Explorer"));
			}
			return;
		}
		when.textContent = available ? localize('exports.notMade', "Not made yet") : '';
		when.classList.add('muted');
		const button = this.renderDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		button.label = localize('exports.exportArchive', "Export Project (.civil)...");
		button.enabled = available;
		this.renderDisposables.add(button.onDidClick(() => void this.exportArchive()));
		this.firstControl ??= button.element;
	}

	private async openArchive(): Promise<void> {
		try {
			await this.commandService.executeCommand(OPEN_ARCHIVE_UI_COMMAND);
		} catch (error) {
			this.notificationService.error(toErrorMessage(error));
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
