/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, NeverShowAgainScope, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import {
	ARCHIVE_EXPORT_COMMAND, ARCHIVE_EXTENSION, ARCHIVE_IMPORT_COMMAND, ARCHIVE_INSPECT_COMMAND, archiveSummaryLines, CAD_OPEN_COMMAND, DEFAULT_EXPORT_OPTIONS, defaultArchiveName, exportArgs,
	formatSize, IArchiveExportOptions, IExportArchiveCommandArgs, importArgs, IOpenArchiveCommandArgs, projectNameForArchive, readArchiveManifest, readProblems, uniqueFolderName,
} from './projectArchiveModel.js';
import { COMPONENTS_ADD_COMMAND } from '../../saengineUpdate/common/components.js';
import { ProjectOpener } from './projectOpener.js';
import { saveProjectEdits } from './projectEdits.js';
import { IWorkingCopyService } from '../../../services/workingCopy/common/workingCopyService.js';
import { IHostService } from '../../../services/host/browser/host.js';

/** The last archive written from this project (workspace storage), for the Exports page. */
export const LAST_ARCHIVE_STORAGE_KEY = 'saengine.project.lastArchive';
/** The export options last chosen (application storage). */
const OPTIONS_STORAGE_KEY = 'saengine.project.archiveOptions';

export interface ILastArchive {
	readonly path: string;
	readonly size?: number;
	readonly time: number;
}

export function readLastArchive(raw: string | undefined): ILastArchive | undefined {
	try {
		const value = raw ? JSON.parse(raw) : undefined;
		return value && typeof value.path === 'string' && typeof value.time === 'number' ? { path: value.path, time: value.time, size: typeof value.size === 'number' ? value.size : undefined } : undefined;
	} catch {
		return undefined;
	}
}

/** The answer of a command, or undefined when the backend has not registered it. */
function hasCommand(id: string): boolean {
	return !!CommandsRegistry.getCommand(id);
}

/**
 * The project archive (`.civil`) and the CAD hand-off: Export Project, Open Project Archive and
 * Open DXF in CAD. The paths can be given as arguments (tests); anything left out is asked.
 */
export class ProjectArchiveFlows {

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IDialogService private readonly dialogService: IDialogService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProgressService private readonly progressService: IProgressService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@IStorageService private readonly storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IWorkingCopyService private readonly workingCopyService: IWorkingCopyService,
		@IHostService private readonly hostService: IHostService,
	) { }

	private notAvailable(): void {
		this.notificationService.info(localize('archive.unavailable', "Project archives are not available in this build of SAEngine."));
	}

	private storedOptions(): IArchiveExportOptions {
		try {
			const value = JSON.parse(this.storageService.get(OPTIONS_STORAGE_KEY, StorageScope.APPLICATION, '{}'));
			return {
				includeResults: typeof value.includeResults === 'boolean' ? value.includeResults : DEFAULT_EXPORT_OPTIONS.includeResults,
				includeVersions: typeof value.includeVersions === 'boolean' ? value.includeVersions : DEFAULT_EXPORT_OPTIONS.includeVersions,
				includeExports: typeof value.includeExports === 'boolean' ? value.includeExports : DEFAULT_EXPORT_OPTIONS.includeExports,
			};
		} catch {
			return DEFAULT_EXPORT_OPTIONS;
		}
	}

	/** What goes into the archive: versions, results and exports, each on or off (the last choice preselected). */
	async askExportOptions(): Promise<IArchiveExportOptions | undefined> {
		interface IOptionItem extends IQuickPickItem { readonly option: keyof IArchiveExportOptions }
		const stored = this.storedOptions();
		const items: IOptionItem[] = [
			{
				option: 'includeVersions',
				label: localize('archive.includeVersions', "Include Versions"),
				detail: localize('archive.includeVersionsDetail', "The saved versions and issues, so the receiver can compare and restore them."),
				picked: stored.includeVersions,
			},
			{
				option: 'includeResults',
				label: localize('archive.includeResults', "Include Results"),
				detail: localize('archive.includeResultsDetail', "The analysis and design results (larger). Without them the receiver runs Run All once."),
				picked: stored.includeResults,
			},
			{
				option: 'includeExports',
				label: localize('archive.includeExports', "Include Exports"),
				detail: localize('archive.includeExportsDetail', "The design report and the generated drawings of 11 Exports (often most of the size). Without them the receiver prints and generates them again."),
				picked: stored.includeExports,
			},
		];
		const picked = await this.quickInputService.pick(items, {
			canPickMany: true,
			title: localize('archive.exportTitle', "Export Project"),
			placeHolder: localize('archive.optionsPlaceholder', "The project's parts are always included. Also include:"),
			ignoreFocusLost: true,
		});
		if (!picked) {
			return undefined;
		}
		const options = { includeResults: picked.some(i => i.option === 'includeResults'), includeVersions: picked.some(i => i.option === 'includeVersions'), includeExports: picked.some(i => i.option === 'includeExports') };
		this.storageService.store(OPTIONS_STORAGE_KEY, JSON.stringify(options), StorageScope.APPLICATION, StorageTarget.USER);
		return options;
	}

	/** Writes the open project to a `.civil` file. Returns the file written. */
	async exportProject(args: IExportArchiveCommandArgs = {}): Promise<URI | undefined> {
		const project = this.projectService.project;
		if (!project) {
			this.notificationService.info(localize('archive.noProject', "Open a project to export it."));
			return undefined;
		}
		if (!hasCommand(ARCHIVE_EXPORT_COMMAND)) {
			this.notAvailable();
			return undefined;
		}
		let options: IArchiveExportOptions | undefined = args.includeResults !== undefined && args.includeVersions !== undefined
			? { includeResults: args.includeResults, includeVersions: args.includeVersions, includeExports: args.includeExports ?? DEFAULT_EXPORT_OPTIONS.includeExports }
			: undefined;
		if (!options) {
			const asked = await this.askExportOptions();
			if (!asked) {
				return undefined;
			}
			options = { includeResults: args.includeResults ?? asked.includeResults, includeVersions: args.includeVersions ?? asked.includeVersions, includeExports: args.includeExports ?? asked.includeExports };
		}
		let target = args.outPath ? URI.file(args.outPath) : undefined;
		if (!target) {
			target = await this.fileDialogService.showSaveDialog({
				title: localize('archive.saveTitle', "Export Project"),
				// Next to the project folder, not in it: an archive never holds another one.
				defaultUri: joinPath(dirname(project.root), defaultArchiveName(project.name, new Date())),
				filters: [{ name: localize('archive.filter', "SAEngine project (*.civil)"), extensions: [ARCHIVE_EXTENSION] }],
			});
			if (!target) {
				return undefined;
			}
		}
		// The backend archives the files on disk: save the edits still open in editors first (as Run
		// All does), so that the archive holds what the engineer sees.
		const unsaved = await saveProjectEdits(this.workingCopyService, project.root);
		if (unsaved.length) {
			this.notificationService.error(localize('archive.saveEditsFailed', "The project was not exported: {0} could not be saved first.", unsaved.map(file => basename(file)).join(', ')));
			return undefined;
		}
		const request = exportArgs(project.root.fsPath, target.fsPath, options);
		try {
			const result = await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('archive.exporting', "Exporting {0}...", project.name),
			}, () => this.commandService.executeCommand(ARCHIVE_EXPORT_COMMAND, request));
			const bag = (typeof result === 'object' && result !== null ? result : {}) as { readonly path?: unknown; readonly size?: unknown };
			const problems = readProblems(result);
			if (typeof bag.path !== 'string') {
				throw new Error(problems.join(' ') || localize('archive.noFile', "No file was written."));
			}
			const written = URI.file(bag.path);
			const size = typeof bag.size === 'number' ? bag.size : undefined;
			this.storageService.store(LAST_ARCHIVE_STORAGE_KEY, JSON.stringify({ path: bag.path, size, time: Date.now() }), StorageScope.WORKSPACE, StorageTarget.MACHINE);
			const text = localize('archive.exported', "Exported {0} ({1}).", basename(written), formatSize(size));
			if (problems.length) {
				this.notificationService.warn(localize('archive.exportedProblems', "{0} {1}", text, problems.join(' ')));
			} else {
				this.notificationService.info(text);
			}
			return written;
		} catch (error) {
			this.notificationService.error(localize('archive.exportFailed', "The project could not be exported: {0}", toErrorMessage(error)));
			return undefined;
		}
	}

	/**
	 * Opens a `.civil` file: shows what it holds, asks where to unpack it, unpacks it and opens
	 * the project. Returns the project folder.
	 */
	async openArchive(args: IOpenArchiveCommandArgs = {}): Promise<URI | undefined> {
		if (!hasCommand(ARCHIVE_INSPECT_COMMAND) || !hasCommand(ARCHIVE_IMPORT_COMMAND)) {
			this.notAvailable();
			return undefined;
		}
		const opener = this.instantiationService.createInstance(ProjectOpener);
		let file = args.path ? URI.file(args.path) : undefined;
		if (!file) {
			// Where the last archive of this project was written, if any (archives arrive there too).
			const last = readLastArchive(this.storageService.get(LAST_ARCHIVE_STORAGE_KEY, StorageScope.WORKSPACE));
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('archive.openTitle', "Open Project Archive"),
				defaultUri: last ? dirname(URI.file(last.path)) : undefined,
				canSelectFiles: true,
				canSelectFolders: false,
				canSelectMany: false,
				filters: [{ name: localize('archive.filter', "SAEngine project (*.civil)"), extensions: [ARCHIVE_EXTENSION] }],
			});
			file = picked?.[0];
			if (!file) {
				return undefined;
			}
		}

		let manifest;
		try {
			manifest = readArchiveManifest(await this.commandService.executeCommand(ARCHIVE_INSPECT_COMMAND, { path: file.fsPath }));
		} catch (error) {
			this.notificationService.error(localize('archive.inspectFailed', "{0} could not be read: {1}", basename(file), toErrorMessage(error)));
			return undefined;
		}
		const unreadable = manifest.ok === false || (!manifest.parts.length && manifest.problems.length > 0);
		const lines = archiveSummaryLines(manifest, basename(file));

		let destParent = args.destParent ? URI.file(args.destParent) : undefined;
		if (unreadable) {
			await this.dialogService.error(localize('archive.notProject', "{0} is not a SAEngine project archive.", basename(file)), lines.join('\n'));
			return undefined;
		}
		if (!destParent) {
			const { confirmed } = await this.dialogService.confirm({
				message: localize('archive.openMessage', "Open {0}?", manifest.name ?? basename(file)),
				detail: [...lines, '', localize('archive.openDetail', "The project is unpacked into a new folder you choose, then opened.")].join('\n'),
				primaryButton: localize('archive.chooseFolder', "&&Choose Folder..."),
			});
			if (!confirmed) {
				return undefined;
			}
			// Next to the archive: where the engineer saved or received it.
			destParent = await opener.browseForLocation(dirname(file), localize('archive.destinationTitle', "Choose Where to Put the Project"));
			if (!destParent) {
				return undefined;
			}
		}

		const wanted = args.name ?? projectNameForArchive(basename(file), manifest.name);
		const existing = new Set<string>();
		try {
			for (const child of (await this.fileService.resolve(destParent)).children ?? []) {
				existing.add(child.name.toLowerCase());
			}
		} catch {
			// A new folder: nothing taken.
		}
		const name = args.name ?? uniqueFolderName(wanted, candidate => existing.has(candidate.toLowerCase()));
		try {
			const result = await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('archive.importing', "Unpacking {0}...", basename(file)),
			}, () => this.commandService.executeCommand(ARCHIVE_IMPORT_COMMAND, importArgs(file.fsPath, destParent.fsPath, name)));
			const bag = (typeof result === 'object' && result !== null ? result : {}) as { readonly root?: unknown };
			const problems = readProblems(result);
			if (typeof bag.root !== 'string') {
				throw new Error(problems.join(' ') || localize('archive.noProjectWritten', "No project was unpacked."));
			}
			if (problems.length) {
				this.notificationService.warn(localize('archive.importedProblems', "Unpacked {0}: {1}", name, problems.join(' ')));
			}
			const root = URI.file(bag.root);
			if (args.open !== false) {
				await this.openUnpacked(root, opener);
			}
			return root;
		} catch (error) {
			this.notificationService.error(localize('archive.importFailed', "The project could not be unpacked: {0}", toErrorMessage(error)));
			return undefined;
		}
	}

	/**
	 * Opens the project unpacked from an archive. With a project open in this window, asks whether
	 * to replace it or open a new window, rather than closing it unasked.
	 */
	private async openUnpacked(root: URI, opener: ProjectOpener): Promise<void> {
		const open = this.projectService.project;
		if (!open) {
			await opener.open(root);
			return;
		}
		const { result } = await this.dialogService.prompt<'this' | 'new' | undefined>({
			message: localize('archive.whereOpen', "Open {0}?", basename(root)),
			detail: localize('archive.whereOpenDetail', "It was unpacked to {0}. {1} is open in this window.", root.fsPath, open.name),
			buttons: [
				{ label: localize('archive.openNewWindow', "Open in &&New Window"), run: () => 'new' },
				{ label: localize('archive.openThisWindow', "Open in &&This Window"), run: () => 'this' },
			],
			cancelButton: { label: localize('archive.openLater', "Not Now"), run: () => undefined },
		});
		if (result === 'new') {
			await this.hostService.openWindow([{ folderUri: root }], { forceNewWindow: true });
		} else if (result === 'this') {
			await opener.open(root);
		} else {
			this.notificationService.info(localize('archive.unpackedOnly', "Unpacked to {0}. Open it with Open Project when you need it.", root.fsPath));
		}
	}

	/** Opens a DXF in LibreCAD (bundled) or the system's DXF program; asks which DXF when not given. */
	async openDxfInCad(resource?: URI): Promise<boolean> {
		let file = resource;
		if (!file) {
			const project = this.projectService.project;
			const exportsPart = partById('exports');
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('cad.openTitle', "Open DXF in CAD"),
				canSelectFiles: true,
				canSelectFolders: false,
				canSelectMany: false,
				defaultUri: project && exportsPart ? joinPath(project.root, exportsPart.folder) : undefined,
				filters: [{ name: localize('cad.filter', "DXF drawings (*.dxf)"), extensions: ['dxf'] }],
			});
			file = picked?.[0];
			if (!file) {
				return false;
			}
		}
		if (!hasCommand(CAD_OPEN_COMMAND)) {
			// Without the bundled LibreCAD, the system's own DXF program.
			return this.openerService.open(file, { openExternal: true });
		}
		try {
			const result = await this.commandService.executeCommand(CAD_OPEN_COMMAND, { path: file.fsPath });
			const bag = (typeof result === 'object' && result !== null ? result : {}) as { readonly ok?: unknown; readonly program?: unknown };
			if (bag.ok === false) {
				const problems = readProblems(result);
				throw new Error(problems.join(' ') || localize('cad.noProgram', "No program for DXF drawings was found."));
			}
			if (bag.program === 'system' && hasCommand(COMPONENTS_ADD_COMMAND)) {
				// No LibreCAD: a state, said once, with the way to add it.
				this.notificationService.prompt(Severity.Info,
					localize('cad.noLibreCad', "LibreCAD is not installed, so {0} opened in the program Windows uses for DXF files. The setup's CAD editor component adds LibreCAD.", basename(file)),
					[{ label: localize('cad.addLibreCad', "Add Component..."), run: () => this.commandService.executeCommand(COMPONENTS_ADD_COMMAND, 'librecad') }],
					{ neverShowAgain: { id: 'saengine.cad.noLibreCad', scope: NeverShowAgainScope.APPLICATION } });
			}
			return true;
		} catch (error) {
			this.notificationService.error(localize('cad.openFailed', "{0} could not be opened in CAD: {1}", basename(file), toErrorMessage(error)));
			return false;
		}
	}
}
