/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { basename } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ImportReportInput } from './importReportInput.js';
import { ProjectOpener } from './projectOpener.js';
import {
	defaultImportName, detectFormat, IImportReport, IImportStructuralCommandArgs, ILastImport, importFilters, IStructuralImportArgs, LAST_IMPORT_STORAGE_KEY, readImportResult, readLastImport,
	STRUCTURAL_IMPORT_COMMAND, uniqueImportName,
} from './structuralImportModel.js';

/** What {@link StructuralImportFlows.importStructural} answers: the new project and its report. */
export interface IStructuralImportOutcome {
	readonly root: string;
	readonly report: IImportReport;
}

/**
 * Import from ETABS, STAAD.Pro or SAP2000: pick the file, the folder and the project's name,
 * import, show the report, open the project. The paths and the name can be given as arguments
 * (tests); anything left out is asked.
 */
export class StructuralImportFlows {

	private readonly opener: ProjectOpener;

	constructor(
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProgressService private readonly progressService: IProgressService,
		@IFileService private readonly fileService: IFileService,
		@IStorageService private readonly storageService: IStorageService,
		@IEditorService private readonly editorService: IEditorService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		this.opener = instantiationService.createInstance(ProjectOpener);
	}

	/** The last import, if it is stored. */
	lastImport(): ILastImport | undefined {
		return readLastImport(this.storageService.get(LAST_IMPORT_STORAGE_KEY, StorageScope.APPLICATION));
	}

	private storeImport(entry: ILastImport): void {
		this.storageService.store(LAST_IMPORT_STORAGE_KEY, JSON.stringify(entry), StorageScope.APPLICATION, StorageTarget.MACHINE);
	}

	/** Opens the report of `entry` (by default the last import's); false when there is none. */
	async showReport(entry: ILastImport | undefined = this.lastImport()): Promise<boolean> {
		if (!entry) {
			this.notificationService.info(localize('import.noReport', "There is no import report yet. Import a model from ETABS, STAAD.Pro or SAP2000 first."));
			return false;
		}
		await this.editorService.openEditor(new ImportReportInput(entry), { pinned: true });
		return true;
	}

	/** The report opens once more in the new project's window; this clears that. */
	takePendingReport(projectRoot: string, same: (a: string, b: string) => boolean): ILastImport | undefined {
		const entry = this.lastImport();
		if (!entry?.pending || !same(entry.root, projectRoot)) {
			return undefined;
		}
		const shown = { ...entry, pending: false };
		this.storeImport(shown);
		return shown;
	}

	private async folderNames(parent: URI): Promise<Set<string>> {
		const names = new Set<string>();
		try {
			for (const child of (await this.fileService.resolve(parent)).children ?? []) {
				names.add(child.name.toLowerCase());
			}
		} catch {
			// A new folder: nothing taken.
		}
		return names;
	}

	private async askName(file: URI, destParent: URI): Promise<string | undefined> {
		const taken = await this.folderNames(destParent);
		const value = uniqueImportName(defaultImportName(basename(file)), candidate => taken.has(candidate.toLowerCase()));
		const name = await this.quickInputService.input({
			title: localize('import.nameTitle', "Name the Imported Project"),
			prompt: localize('import.namePrompt', "The project is created in {0}.", destParent.fsPath),
			value,
			ignoreFocusLost: true,
			validateInput: async input => this.opener.validateName(input)
				?? (taken.has(input.trim().toLowerCase()) ? localize('import.nameTaken', "{0} already exists in this folder.", input.trim()) : undefined),
		});
		return name?.trim() || undefined;
	}

	async importStructural(args: IImportStructuralCommandArgs = {}): Promise<IStructuralImportOutcome | undefined> {
		if (!CommandsRegistry.getCommand(STRUCTURAL_IMPORT_COMMAND)) {
			this.notificationService.info(localize('import.unavailable', "Importing from ETABS, STAAD.Pro or SAP2000 is not available in this build of SAEngine yet."));
			return undefined;
		}
		let file = args.path ? URI.file(args.path) : undefined;
		if (!file) {
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('import.openTitle', "Import from ETABS, STAAD or SAP2000"),
				canSelectFiles: true,
				canSelectFolders: false,
				canSelectMany: false,
				filters: importFilters(),
			});
			file = picked?.[0];
			if (!file) {
				return undefined;
			}
		}
		if (!detectFormat(basename(file))) {
			this.notificationService.error(localize('import.unknownFile', "{0} is not an ETABS (.e2k), STAAD.Pro (.std) or SAP2000 (.s2k) text file. Export the model as text from that program first.", basename(file)));
			return undefined;
		}
		let destParent = args.destParent ? URI.file(args.destParent) : undefined;
		if (!destParent) {
			destParent = await this.opener.browseForLocation(await this.opener.defaultLocation(), localize('import.destinationTitle', "Choose Where to Put the Imported Project"));
			if (!destParent) {
				return undefined;
			}
		}
		const name = args.name ?? await this.askName(file, destParent);
		if (!name) {
			return undefined;
		}
		const request: IStructuralImportArgs = { path: file.fsPath, destParent: destParent.fsPath, name };
		let result;
		try {
			result = readImportResult(await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('import.importing', "Importing {0}...", basename(file)),
			}, () => this.commandService.executeCommand(STRUCTURAL_IMPORT_COMMAND, request)));
		} catch (error) {
			this.notificationService.error(localize('import.failed', "{0} could not be imported: {1}", basename(file), toErrorMessage(error)));
			return undefined;
		}
		if (!result.root) {
			this.notificationService.error(localize('import.failed', "{0} could not be imported: {1}", basename(file),
				result.problems.join(' ') || localize('import.noProject', "no project was written.")));
			return undefined;
		}
		const entry: ILastImport = { root: result.root, file: file.fsPath, time: Date.now(), report: result.report, pending: true };
		this.storeImport(entry);
		if (args.open) {
			// The report opens in the project's window.
			await this.opener.open(URI.file(result.root));
		} else {
			await this.showReport(entry);
		}
		return { root: result.root, report: result.report };
	}
}
