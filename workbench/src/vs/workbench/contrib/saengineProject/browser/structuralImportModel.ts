/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';

/*
 * Importing a model of another structural program (ETABS .e2k, STAAD.Pro .std, SAP2000 .s2k)
 * into a new SAEngine project. The backend parses the file and writes the project; this file
 * holds the command ids, their arguments and what the UI makes of the answer, the import report
 * (free of DOM and services, so that it can be tested on its own).
 */

/** `{path, destParent, name}` -> `{root, report}` (read with {@link readImportResult}). */
export const STRUCTURAL_IMPORT_COMMAND = 'saengine.import.structural';

/** The UI command (start page, ≡ File menu): `{path, destParent, name, open}`; any left out is asked. */
export const IMPORT_STRUCTURAL_UI_COMMAND = 'saengine.project.importStructural';
/** Opens the report of the last import again. */
export const SHOW_IMPORT_REPORT_COMMAND = 'saengine.project.showImportReport';

/** The last import (application storage): its project, file, time and report. */
export const LAST_IMPORT_STORAGE_KEY = 'saengine.project.lastImport';

export type StructuralFormat = 'etabs' | 'staad' | 'sap2000';

export interface IStructuralFormatInfo {
	readonly format: StructuralFormat;
	readonly label: string;
	/** File extensions without the dot, lower case. */
	readonly extensions: readonly string[];
}

/**
 * The programs SAEngine imports from, for the file dialog's filters and the labels only: which
 * format a file is, and whether it can be read, the backend decides (`importers/project.py`
 * `FORMATS`).
 */
export const STRUCTURAL_FORMATS: readonly IStructuralFormatInfo[] = [
	{ format: 'etabs', label: localize('import.etabs', "ETABS"), extensions: ['e2k', '$et'] },
	{ format: 'staad', label: localize('import.staad', "STAAD.Pro"), extensions: ['std'] },
	{ format: 'sap2000', label: localize('import.sap2000', "SAP2000"), extensions: ['s2k', '$2k'] },
];

/** The file dialog's filters: all three together first, then each program's own. */
export function importFilters(): { name: string; extensions: string[] }[] {
	return [
		{ name: localize('import.filterAll', "ETABS, STAAD.Pro or SAP2000 text files"), extensions: STRUCTURAL_FORMATS.flatMap(f => [...f.extensions]) },
		...STRUCTURAL_FORMATS.map(f => ({ name: localize('import.filterOne', "{0} (*.{1})", f.label, f.extensions.join(', *.')), extensions: [...f.extensions] })),
	];
}

/** "ETABS", "STAAD.Pro", "SAP2000"; the backend's own name for another format. */
export function formatLabel(format: string | undefined): string {
	const key = format?.toLowerCase();
	return STRUCTURAL_FORMATS.find(f => f.format === key || f.label.toLowerCase() === key)?.label ?? format ?? localize('import.unknownFormat', "unknown format");
}

/** Characters Windows does not allow in a folder name (as ProjectOpener.validateName). */
const INVALID_NAME = /[\\/:*?"<>|]/g;

/** The project name a file suggests: its name without the extension, made a valid folder name. */
export function defaultImportName(fileName: string): string {
	const base = fileName.replace(/^.*[\\/]/, '');
	const dot = base.lastIndexOf('.');
	const stem = (dot >= 0 ? base.slice(0, dot) : base).replace(INVALID_NAME, ' ').replace(/\s+/g, ' ').trim().replace(/[. ]+$/, '');
	return stem || localize('import.defaultName', "Imported Model");
}

/** `wanted`, or `wanted (2)`, `wanted (3)`, ... whichever is not taken. */
export function uniqueImportName(wanted: string, taken: (name: string) => boolean): string {
	if (!taken(wanted)) {
		return wanted;
	}
	for (let n = 2; ; n++) {
		const candidate = `${wanted} (${n})`;
		if (!taken(candidate)) {
			return candidate;
		}
	}
}

export interface IStructuralImportArgs {
	readonly path: string;
	readonly destParent: string;
	readonly name: string;
}

/** The arguments of {@link IMPORT_STRUCTURAL_UI_COMMAND}: any left out is asked; `open: true` opens the project without showing the report first. */
export interface IImportStructuralCommandArgs {
	readonly path?: string;
	readonly destParent?: string;
	readonly name?: string;
	readonly open?: boolean;
}

/** What was imported, by kind. */
export interface IImportCounts {
	readonly stories: number;
	readonly columns: number;
	readonly beams: number;
	readonly braces: number;
	readonly slabs: number;
	readonly walls: number;
	readonly sections: number;
	readonly materials: number;
	readonly loads: number;
	readonly combinations: number;
	/** Other kinds the backend counts (joints, supports, load patterns, ...). */
	readonly [kind: string]: number;
}

/** One line of the report's approximated, skipped or warnings lists. */
export interface IImportReportItem {
	/** What it is about ("section", "area load", "link"), when the backend says. */
	readonly kind: string | undefined;
	readonly message: string;
	/** How many items it covers (1 when the backend does not count them). */
	readonly count: number;
	/** A few of the items' names, from the file ("W14X90", "F12", "LINK1"). */
	readonly examples: readonly string[];
}

/** The import report, as the backend gives it, read with {@link readImportReport}. */
export interface IImportReport {
	readonly format: string | undefined;
	/** The file's units ("kip-ft", "kN-m") and what they were converted to, as the backend says. */
	readonly units: string | undefined;
	readonly counts: IImportCounts;
	readonly approximated: readonly IImportReportItem[];
	readonly skipped: readonly IImportReportItem[];
	/** What SAEngine makes its own in place of the file's (wind and earthquake loads from BNBC 2020): not lost. */
	readonly replaced: readonly IImportReportItem[];
	readonly warnings: readonly IImportReportItem[];
	/** The file it was imported from, when the backend says. */
	readonly source: string | undefined;
	/** The program's version, when the backend says ("21.0.0"). */
	readonly version: string | undefined;
	/** Load totals [kN] by SAEngine load case: carried over to the project, and not carried over. */
	readonly loads: { readonly carried: IImportLoadTotals; readonly notCarried: IImportLoadTotals; readonly replaced: IImportLoadTotals };
	/** Report lines the UI could not read (a shape it does not know): shown as a warning, never dropped silently. */
	readonly unread: number;
}

/** Load totals [kN] by SAEngine load case ("D", "L", "Lr"). */
export interface IImportLoadTotals {
	readonly [loadCase: string]: number;
}

export interface IStructuralImportResult {
	/** The new project's folder; undefined when nothing was written. */
	readonly root: string | undefined;
	readonly report: IImportReport;
	/** Why nothing was written (the backend's `problems` or `error`). */
	readonly problems: readonly string[];
}

/** The counts the report always shows, in this order. */
export const MAIN_COUNTS = ['stories', 'columns', 'beams', 'braces', 'slabs', 'walls', 'sections', 'materials', 'loads', 'combinations'] as const;

function bagOf(value: unknown): { readonly [key: string]: unknown } {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as { readonly [key: string]: unknown } : {};
}

function stringOf(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() ? value : undefined;
}

function countOf(value: unknown): number {
	return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : 0;
}

/** One report item: text, or `{what|message|text|reason, kind, count, examples|items|ids}` (the importers' ImportReport gives `{what, count, examples}`). */
function readItem(value: unknown): IImportReportItem | undefined {
	if (typeof value === 'string') {
		return value.trim() ? { kind: undefined, message: value, count: 1, examples: [] } : undefined;
	}
	const bag = bagOf(value);
	const message = stringOf(bag.what) ?? stringOf(bag.message) ?? stringOf(bag.text) ?? stringOf(bag.reason);
	const kind = stringOf(bag.kind) ?? stringOf(bag.type);
	if (!message && !kind) {
		return undefined;
	}
	const list = [bag.examples, bag.items, bag.ids].find(Array.isArray) as unknown[] | undefined;
	const examples = (list ?? []).map(e => typeof e === 'number' ? String(e) : stringOf(e)).filter((e): e is string => !!e);
	const count = typeof bag.count === 'number' ? countOf(bag.count) : Math.max(1, examples.length);
	return { kind, message: message ?? '', count, examples };
}

/** The items of a list, and how many of its entries could not be read. */
function readItems(value: unknown): { items: IImportReportItem[]; unread: number } {
	if (!Array.isArray(value)) {
		return { items: [], unread: 0 };
	}
	const items = value.map(readItem).filter((i): i is IImportReportItem => !!i);
	return { items, unread: value.length - items.length };
}

/**
 * The importers' names for the main counts, where they differ: they count object types
 * (04 Objects, one per section) and area loads (the loads carried over as loads).
 */
const COUNT_ALIASES: { readonly [kind: string]: string } = { sections: 'objectTypes', loads: 'areaLoads' };

function readLoadTotals(value: unknown): IImportLoadTotals {
	const totals: { [loadCase: string]: number } = {};
	for (const [loadCase, kN] of Object.entries(bagOf(value))) {
		if (typeof kN === 'number' && Number.isFinite(kN)) {
			totals[loadCase] = kN;
		}
	}
	return totals;
}

/**
 * The report of a backend answer, missing fields empty. Reads the importers' own report
 * (saengine.importers.common.ImportReport.to_dict: `source {program, file, version, units}`,
 * `imported {...counts}`, items `{what, count, examples}`, `loads {carriedKN, notCarriedKN}`)
 * and a flat shape (`format`, `units`, `counts`, items `{kind, message}`).
 */
export function readImportReport(value: unknown): IImportReport {
	const bag = bagOf(value);
	const source = bagOf(bag.source);
	const rawCounts = { ...bagOf(bag.imported), ...bagOf(bag.counts) };
	const counts: { [kind: string]: number } = {};
	const aliased = new Set<string>();
	for (const kind of MAIN_COUNTS) {
		const alias = COUNT_ALIASES[kind];
		if (typeof rawCounts[kind] !== 'number' && alias && typeof rawCounts[alias] === 'number') {
			counts[kind] = countOf(rawCounts[alias]);
			aliased.add(alias);
		} else {
			counts[kind] = countOf(rawCounts[kind]);
		}
	}
	for (const [kind, count] of Object.entries(rawCounts)) {
		if (!(MAIN_COUNTS as readonly string[]).includes(kind) && !aliased.has(kind) && typeof count === 'number') {
			counts[kind] = countOf(count);
		}
	}
	const approximated = readItems(bag.approximated);
	const skipped = readItems(bag.skipped);
	const replaced = readItems(bag.replaced);
	const warnings = readItems(bag.warnings);
	const loads = bagOf(bag.loads);
	return {
		format: stringOf(bag.format) ?? stringOf(source.program),
		units: stringOf(bag.units) ?? stringOf(source.units),
		counts: counts as IImportCounts,
		approximated: approximated.items,
		skipped: skipped.items,
		replaced: replaced.items,
		warnings: warnings.items,
		source: stringOf(bag.source) ?? stringOf(source.file) ?? stringOf(bag.path),
		version: stringOf(bag.version) ?? stringOf(source.version),
		loads: {
			carried: readLoadTotals(loads.carriedKN ?? loads.carried),
			notCarried: readLoadTotals(loads.notCarriedKN ?? loads.notCarried),
			replaced: readLoadTotals(loads.replacedByBnbcKN),
		},
		unread: approximated.unread + skipped.unread + replaced.unread + warnings.unread,
	};
}

/** The answer of {@link STRUCTURAL_IMPORT_COMMAND}. */
export function readImportResult(value: unknown): IStructuralImportResult {
	const bag = bagOf(value);
	const problems = [
		...(Array.isArray(bag.problems) ? bag.problems.map(p => stringOf(p)).filter((p): p is string => !!p) : []),
		...(stringOf(bag.error) ? [bag.error as string] : []),
	];
	return { root: stringOf(bag.root), report: readImportReport(bag.report), problems };
}

/** The label of a count: "Stories", "Columns", ...; another kind as the backend names it. */
export function countLabel(kind: string): string {
	switch (kind) {
		case 'stories': return localize('import.count.stories', "Stories");
		case 'columns': return localize('import.count.columns', "Columns");
		case 'beams': return localize('import.count.beams', "Beams");
		case 'braces': return localize('import.count.braces', "Braces");
		case 'slabs': return localize('import.count.slabs', "Slabs");
		case 'walls': return localize('import.count.walls', "Walls");
		case 'sections': return localize('import.count.sections', "Sections");
		case 'materials': return localize('import.count.materials', "Materials");
		case 'loads': return localize('import.count.loads', "Loads");
		case 'combinations': return localize('import.count.combinations', "Load combinations");
		case 'joints': return localize('import.count.joints', "Joints");
		case 'supports': return localize('import.count.supports', "Supports");
		case 'loadPatterns': return localize('import.count.loadPatterns', "Load patterns");
		default: {
			// camelCase -> "Camel case"
			const words = kind.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
			return words.charAt(0).toUpperCase() + words.slice(1);
		}
	}
}

export interface IImportCountRow {
	readonly kind: string;
	readonly label: string;
	readonly count: number;
}

/** The counts as rows: the main kinds in their order (zeros kept), then the others that are not zero. */
export function countRows(report: IImportReport): IImportCountRow[] {
	const main = MAIN_COUNTS.map(kind => ({ kind, label: countLabel(kind), count: report.counts[kind] ?? 0 }));
	const others = Object.keys(report.counts)
		.filter(kind => !(MAIN_COUNTS as readonly string[]).includes(kind) && report.counts[kind] > 0)
		.map(kind => ({ kind, label: countLabel(kind), count: report.counts[kind] }));
	return [...main, ...others];
}

/** The members imported (columns, beams, braces). */
export function memberCount(report: IImportReport): number {
	return (report.counts.columns ?? 0) + (report.counts.beams ?? 0) + (report.counts.braces ?? 0) + (report.counts.inclinedMembers ?? 0);
}

function total(items: readonly IImportReportItem[]): number {
	return items.reduce((sum, item) => sum + item.count, 0);
}

/**
 * "Imported from ETABS: 3 stories, 42 members, 6 slabs. 4 approximated, 2 skipped." The
 * approximated and skipped totals count the items, not the lines.
 */
export function describeImportSummary(report: IImportReport): string {
	const parts = [
		localize('import.summaryStories', "{0} stories", report.counts.stories ?? 0),
		localize('import.summaryMembers', "{0} members", memberCount(report)),
		localize('import.summarySlabs', "{0} slabs", report.counts.slabs ?? 0),
		...(report.counts.walls === 1 ? [localize('import.summaryWall', "1 wall")] : []),
		...(report.counts.walls > 1 ? [localize('import.summaryWalls', "{0} walls", report.counts.walls)] : []),
	];
	const head = localize('import.summary', "Imported from {0}: {1}.", formatLabel(report.format), parts.join(', '));
	const approximated = total(report.approximated);
	const skipped = total(report.skipped);
	const lost = notCarriedTotal(report);
	const tail = [
		...(lost > 0 ? [localize('import.summaryNotCarried', "{0} kN of load not carried over", formatKN(lost))] : []),
		...(approximated ? [localize('import.summaryApproximated', "{0} approximated", approximated)] : []),
		...(skipped ? [localize('import.summarySkipped', "{0} skipped", skipped)] : []),
		...(report.warnings.length === 1 ? [localize('import.summaryWarning', "1 warning")] : []),
		...(report.warnings.length > 1 ? [localize('import.summaryWarnings', "{0} warnings", report.warnings.length)] : []),
	];
	return tail.length ? localize('import.summaryTail', "{0} {1}.", head, tail.join(', ')) : head;
}

/** The total [kN] of the file's loads that were not carried over. */
export function notCarriedTotal(report: IImportReport): number {
	return Object.values(report.loads.notCarried).reduce((sum, kN) => sum + Math.abs(kN), 0);
}

function formatKN(kN: number): string {
	return formatNumber(kN, { maxDecimals: 1 });
}

function describeLoadTotals(totals: IImportLoadTotals): string | undefined {
	const rows = Object.entries(totals).filter(([, kN]) => Math.abs(kN) > 0).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
	return rows.length ? rows.map(([loadCase, kN]) => localize('import.loadCaseKN', "{0} {1} kN", loadCase, formatKN(kN))).join(', ') : undefined;
}

/** "D 60 kN, L 20 kN": the load not carried over by SAEngine load case, largest first; undefined when none. */
export function describeNotCarried(report: IImportReport): string | undefined {
	return describeLoadTotals(report.loads.notCarried);
}

/** "WX 120 kN, EX 300 kN": the file's wind and earthquake loads SAEngine replaces with its own (BNBC 2020); undefined when none. */
export function describeReplaced(report: IImportReport): string | undefined {
	return describeLoadTotals(report.loads.replaced);
}

/** "D 180 kN, L 120 kN": the load carried over by SAEngine load case; undefined when the backend does not say. */
export function describeCarried(report: IImportReport): string | undefined {
	return describeLoadTotals(report.loads.carried);
}

/** Whether the import needs the engineer's review: anything approximated, skipped or warned about, load not carried over, or report lines the UI could not read. */
export function needsReview(report: IImportReport): boolean {
	return report.approximated.length + report.skipped.length + report.warnings.length + report.unread > 0 || notCarriedTotal(report) > 0;
}

/** At most this many examples are listed per line. */
const MAX_EXAMPLES = 5;

/** A report line as text: "[section] Tapered sections imported as their mid section (3: T1, T2, T3)". */
export function describeItem(item: IImportReportItem): string {
	const examples = item.examples.length > MAX_EXAMPLES
		? localize('import.examplesMore', "{0}, ...", item.examples.slice(0, MAX_EXAMPLES).join(', '))
		: item.examples.join(', ');
	const counted = item.count > 1 || examples
		? examples ? localize('import.itemCountExamples', "{0}: {1}", item.count, examples) : String(item.count)
		: undefined;
	const message = item.message || (item.kind ?? '');
	return counted ? localize('import.item', "{0} ({1})", message, counted) : message;
}

/** The last import, as stored: undefined when there is none or it cannot be read. */
export interface ILastImport {
	readonly root: string;
	readonly file: string | undefined;
	readonly time: number;
	readonly report: IImportReport;
	/** The report opens once more in the new project's window. */
	readonly pending: boolean;
}

export function readLastImport(raw: string | undefined): ILastImport | undefined {
	try {
		const value = bagOf(raw ? JSON.parse(raw) : undefined);
		const root = stringOf(value.root);
		if (!root || typeof value.time !== 'number') {
			return undefined;
		}
		return { root, file: stringOf(value.file), time: value.time, report: readImportReport(value.report), pending: value.pending === true };
	} catch {
		return undefined;
	}
}

/** Whether two folder paths are the same folder (Windows: case and separators do not matter). */
export function sameFolder(a: string, b: string): boolean {
	const norm = (p: string) => p.replace(/[\\/]+$/, '').replace(/\\/g, '/').toLowerCase();
	return norm(a) === norm(b);
}
