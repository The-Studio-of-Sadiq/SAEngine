/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ISaengineProject, partById } from '../../../services/saengineProject/common/saengineProject.js';

/**
 * The cost and embodied carbon of the bill (`saengine.boq.costing`): the schedule of rates and
 * the carbon factors are files of the project beside `boq.json`, made from the shipped sample
 * (made-up example rates) and factors (public sources, cited per factor) when first edited.
 */

/** Command pricing the bill: `{boqText, ratesText?, carbonText?}` → {@link IBoqCostResult}. Internal. */
export const BOQ_COST_COMMAND = 'saengine.boq.cost';
/** Command returning the texts the rates and carbon files start from: `{rates, carbon}`. Internal. */
export const BOQ_TEMPLATES_COMMAND = 'saengine.boq.templates';
/** Command writing the bill, its costing and carbon to an Excel workbook (target URI, texts). Internal. */
export const BOQ_WRITE_XLSX_COMMAND = 'saengine.boq.writeXlsx';

/** The schedule of rates and the carbon factors, in `10 BOQ`. */
export const BOQ_RATES_FILE = 'rates.json';
export const BOQ_CARBON_FILE = 'carbon-factors.json';

export type BoqCostPart = 'Superstructure' | 'Substructure' | 'Architecture' | 'MEP';

export interface IBoqCostLine {
	readonly code: string;
	readonly group: string;
	readonly description: string;
	readonly quantity: number;
	readonly unit: string;
	readonly rateCode?: string | null;
	readonly rateDescription?: string | null;
	readonly rateUnit?: string | null;
	readonly rate?: number | null;
	readonly amount?: number | null;
	readonly status: 'priced' | 'not rated' | 'no rate item' | 'unit mismatch';
}

export interface IBoqCarbonLine {
	readonly id: string;
	readonly material: string;
	readonly factor: number | null;
	readonly mass: number;
	readonly carbon?: number | null;
	readonly source: string;
}

export interface IBoqCosting {
	readonly currency: string;
	readonly rateSchedule: string;
	readonly lines: readonly IBoqCostLine[];
	readonly groups: Readonly<Record<string, number>>;
	readonly parts: Readonly<Partial<Record<BoqCostPart, number>>>;
	readonly total: number;
	readonly carbon: readonly IBoqCarbonLine[];
	readonly carbonParts: Readonly<Partial<Record<BoqCostPart, number>>>;
	readonly carbonTotal: number;
	readonly notes: readonly string[];
}

export interface IBoqCostResult {
	readonly costing?: IBoqCosting;
	/** Priced by the shipped sample's made-up rates: the project has no `rates.json`. */
	readonly sampleRates?: boolean;
	readonly problems?: readonly string[];
}

/** A file of `10 BOQ` beside `boq.json`. */
export function boqFile(project: ISaengineProject, name: string): URI | undefined {
	const part = partById('boq');
	return part ? joinPath(project.root, part.folder, name) : undefined;
}

/** The text of a file of `10 BOQ`, or undefined when there is none. */
export async function readBoqFile(project: ISaengineProject, name: string, fileService: IFileService): Promise<string | undefined> {
	const resource = boqFile(project, name);
	if (!resource) {
		return undefined;
	}
	try {
		return (await fileService.readFile(resource)).value.toString();
	} catch {
		return undefined;
	}
}

/**
 * The project's schedule of rates or carbon factors, written from the shipped template when the
 * file is missing. Returns the file.
 */
export async function ensureBoqFile(project: ISaengineProject, kind: 'rates' | 'carbon', fileService: IFileService, commandService: ICommandService): Promise<URI | undefined> {
	const resource = boqFile(project, kind === 'rates' ? BOQ_RATES_FILE : BOQ_CARBON_FILE);
	if (!resource) {
		return undefined;
	}
	if (!(await fileService.exists(resource))) {
		const templates = await commandService.executeCommand<{ readonly rates: string; readonly carbon: string }>(BOQ_TEMPLATES_COMMAND);
		if (!templates) {
			return undefined;
		}
		await fileService.writeFile(resource, VSBuffer.fromString(kind === 'rates' ? templates.rates : templates.carbon));
	}
	return resource;
}

/** An amount of money, grouped, with two decimals: "1,234,567.89". */
export function formatMoney(amount: number): string {
	return amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** kg CO2e as tonnes CO2e: "16.29 t CO2e". */
export function formatCarbon(kg: number): string {
	return localize('boq.carbonTonnes', "{0} t CO2e", (kg / 1000).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
}
