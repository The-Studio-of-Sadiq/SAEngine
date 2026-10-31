/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { basename, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { ISaengineProject, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { BOQ_CARBON_FILE, BOQ_RATES_FILE, BOQ_WRITE_XLSX_COMMAND, readBoqFile } from './boqCosting.js';
import { IBoqDocument, parseBoq, toCsv } from './boqDocument.js';

/** Command exporting the open project's bill of quantities as CSV (asks where to write it). */
export const BOQ_EXPORT_CSV_COMMAND = 'saengine.boq.exportCsv';

/** Command exporting the bill, its costing and embodied carbon to Excel (asks where to write it). */
export const BOQ_EXPORT_XLSX_COMMAND = 'saengine.boq.exportXlsx';

/** Where the CSV and the workbook go by default, in the project's Exports folder. */
export const BOQ_CSV_FILE = 'boq.csv';
export const BOQ_XLSX_FILE = 'boq.xlsx';

export interface IBoqExportServices {
	readonly textModelService: ITextModelService;
	readonly fileService: IFileService;
	readonly fileDialogService: IFileDialogService;
	readonly notificationService: INotificationService;
	readonly openerService: IOpenerService;
	readonly commandService: ICommandService;
}

/** Command id of the file explorer's "Reveal in File Explorer" (desktop only). */
const REVEAL_IN_OS_COMMAND_ID = 'revealFileInOS';

/** The project's bill as it is now (unsaved edits included), or undefined when it was not measured. */
export async function readProjectBoq(project: ISaengineProject, textModelService: ITextModelService): Promise<IBoqDocument | undefined> {
	const part = partById('boq');
	if (!part?.mainFile) {
		return undefined;
	}
	try {
		const reference = await textModelService.createModelReference(joinPath(project.root, part.folder, part.mainFile));
		try {
			return parseBoq(reference.object.textEditorModel.getValue());
		} finally {
			reference.dispose();
		}
	} catch {
		return undefined;
	}
}

/**
 * Asks where to write `document` as CSV (the project's `11 Exports/boq.csv` by default) and
 * writes it. Returns the file written, if any.
 */
export async function exportBoqCsv(document: IBoqDocument, project: ISaengineProject | undefined, services: IBoqExportServices): Promise<URI | undefined> {
	const exports = partById('exports');
	const target = await services.fileDialogService.showSaveDialog({
		title: localize('boq.exportTitle', "Export Bill of Quantities"),
		defaultUri: project && exports ? joinPath(project.root, exports.folder, BOQ_CSV_FILE) : undefined,
		filters: [{ name: localize('boq.csvFiles', "CSV Files"), extensions: ['csv'] }],
	});
	if (!target) {
		return undefined;
	}
	try {
		await services.fileService.writeFile(target, VSBuffer.fromString(toCsv(document)));
		services.notificationService.prompt(Severity.Info, localize('boq.exported', "Exported the bill of quantities to {0}.", basename(target)), [
			{ label: localize('boq.openExported', "Open"), run: () => services.openerService.open(target, { openExternal: true }) },
			{ label: localize('boq.revealExported', "Reveal in File Explorer"), run: () => services.commandService.executeCommand(REVEAL_IN_OS_COMMAND_ID, target) },
		]);
		return target;
	} catch (error) {
		services.notificationService.error(localize('boq.exportFailed', "The bill of quantities could not be exported: {0}", String(error)));
		return undefined;
	}
}

/** What {@link BOQ_WRITE_XLSX_COMMAND} answers. */
interface IBoqXlsxResult {
	readonly path?: string;
	readonly problems?: readonly string[];
	readonly error?: string;
}

/**
 * Asks where to write the bill as an Excel workbook (the project's `11 Exports/boq.xlsx` by
 * default) and writes it with its costing by the project's schedule of rates (`10 BOQ/rates.json`,
 * the sample's made-up rates when there is none) and its embodied carbon: summary, bill with its
 * breakdown, costing, carbon, schedule of rates and notes. `boqText`: the bill as it is now
 * (unsaved edits included). Returns the file written, if any.
 */
export async function exportBoqXlsx(boqText: string, project: ISaengineProject, services: IBoqExportServices): Promise<URI | undefined> {
	const exports = partById('exports');
	const target = await services.fileDialogService.showSaveDialog({
		title: localize('boq.exportXlsxTitle', "Export Bill of Quantities to Excel"),
		defaultUri: exports ? joinPath(project.root, exports.folder, BOQ_XLSX_FILE) : undefined,
		filters: [{ name: localize('boq.xlsxFiles', "Excel Workbooks"), extensions: ['xlsx'] }],
	});
	if (!target) {
		return undefined;
	}
	try {
		const [ratesText, carbonText] = await Promise.all([
			readBoqFile(project, BOQ_RATES_FILE, services.fileService),
			readBoqFile(project, BOQ_CARBON_FILE, services.fileService),
		]);
		const result = await services.commandService.executeCommand<IBoqXlsxResult>(BOQ_WRITE_XLSX_COMMAND, target, { boqText, ratesText, carbonText, title: project.name });
		const problems = result?.problems?.length ? result.problems.join(' ') : result?.error;
		if (problems || !result?.path) {
			services.notificationService.error(localize('boq.exportXlsxFailed', "The bill of quantities could not be exported: {0}", problems ?? localize('boq.noAnswer', "no answer from the engine")));
			return undefined;
		}
		const notice = ratesText
			? localize('boq.exportedXlsx', "Exported the bill of quantities with its costing and embodied carbon to {0}.", basename(target))
			: localize('boq.exportedXlsxSample', "Exported the bill of quantities to {0}. It is priced by the sample's made-up rates: enter your own in the rate schedule.", basename(target));
		services.notificationService.prompt(Severity.Info, notice, [
			{ label: localize('boq.openExported', "Open"), run: () => services.openerService.open(target, { openExternal: true }) },
			{ label: localize('boq.revealExported', "Reveal in File Explorer"), run: () => services.commandService.executeCommand(REVEAL_IN_OS_COMMAND_ID, target) },
		]);
		return target;
	} catch (error) {
		services.notificationService.error(localize('boq.exportXlsxFailed', "The bill of quantities could not be exported: {0}", String(error)));
		return undefined;
	}
}
