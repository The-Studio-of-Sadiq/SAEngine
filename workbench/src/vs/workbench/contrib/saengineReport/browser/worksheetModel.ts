/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Calculation worksheets (`11 Exports/worksheets/<id>.json`, `saengine.library.worksheet`): a
 * kind of hand calculation and the values entered for it. The backend
 * (`saengine.report.worksheets`) makes the calculation with SAEngine's design functions; the
 * worksheets marked to print go into the design report's "Calculation worksheets" section.
 */

/** Calls the backend: `(method, params)`; registered with the RPC. */
export const WORKSHEETS_REQUEST_COMMAND_ID = 'saengine.worksheets.request';

/** The user-facing commands. */
export const NEW_WORKSHEET_COMMAND_ID = 'saengine.worksheets.new';
export const OPEN_WORKSHEETS_COMMAND_ID = 'saengine.worksheets.open';

/** The file schema (`saengine.library.worksheet.SCHEMA_ID`). */
export const WORKSHEET_SCHEMA_ID = 'saengine.worksheet/1';

/** Where a project keeps its worksheets (`WORKSHEETS_FOLDER`), in `11 Exports`. */
export const WORKSHEETS_FOLDER = 'worksheets';

export type WorksheetMethod = 'worksheets/kinds' | 'worksheets/calculate' | 'worksheets/list' | 'worksheets/create';

/** One input of a kind. */
export interface IWorksheetInput {
	readonly name: string;
	readonly label: string;
	readonly kind: 'number' | 'choice' | 'bool';
	readonly default: number | string | boolean;
	readonly unit: string;
	readonly help: string;
	readonly group: string;
	readonly choices?: readonly { readonly value: string; readonly label: string }[];
	readonly minimum?: number;
	readonly maximum?: number;
}

/** A kind of worksheet (`worksheets/kinds`). */
export interface IWorksheetKind {
	readonly id: string;
	readonly title: string;
	readonly group: string;
	readonly summary: string;
	readonly inputs: readonly IWorksheetInput[];
	readonly references: readonly string[];
}

export interface IWorksheetStep {
	readonly heading?: string;
	readonly label?: string;
	readonly value?: string;
	readonly unit?: string;
	readonly formula?: string;
	readonly clause?: string;
}

export interface IWorksheetCheck {
	readonly label: string;
	readonly demand: string;
	readonly capacity: string;
	readonly sense: string;
	readonly unit: string;
	readonly utilisation: number | null;
	readonly ok: boolean;
	readonly clause: string;
}

/** A calculation (`worksheets/calculate`). */
export interface IWorksheetResult {
	readonly kind: string;
	readonly title?: string;
	readonly steps?: readonly IWorksheetStep[];
	readonly checks?: readonly IWorksheetCheck[];
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
	readonly ok?: boolean;
	readonly utilisation?: number | null;
	readonly references?: readonly string[];
}

/** A worksheet of the project (`worksheets/list`). */
export interface IWorksheetInfo {
	readonly id: string;
	readonly title: string;
	readonly kind: string;
	readonly print: boolean;
	readonly path: string;
	readonly ok: boolean | null;
	readonly utilisation: number | null;
	readonly problems: readonly string[];
}

/** A worksheet id from a title: lower case, digits and hyphens ("Beam B12 flexure" → "beam-b12-flexure"). */
export function worksheetId(title: string): string {
	return title.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}

/** The kinds by menu group, in their order. */
export function kindsByGroup(kinds: readonly IWorksheetKind[]): Map<string, IWorksheetKind[]> {
	const groups = new Map<string, IWorksheetKind[]>();
	for (const kind of kinds) {
		const list = groups.get(kind.group) ?? [];
		list.push(kind);
		groups.set(kind.group, list);
	}
	return groups;
}

/** The value of an input as the file stores it, or undefined when the text is not one. */
export function parseInput(input: IWorksheetInput, text: string | boolean): number | string | boolean | undefined {
	if (input.kind === 'bool') {
		return Boolean(text);
	}
	if (input.kind === 'choice') {
		return String(text);
	}
	const value = Number(String(text).trim().replace(/,/g, ''));
	return String(text).trim() !== '' && Number.isFinite(value) ? value : undefined;
}
