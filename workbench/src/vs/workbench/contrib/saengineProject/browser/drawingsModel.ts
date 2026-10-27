/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { isAbsolute } from '../../../../base/common/path.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import type { IDrawingPreviewSheet } from './drawingPreviewInput.js';
import { readProblemsBySeverity } from './projectArchiveModel.js';

/*
 * The structural drawings of part 11: sheets generated from the model and its design (framing
 * plans, schedules, details), each a DXF for LibreCAD and a page of one PDF set, with the bar
 * bending schedule as CSV. The backend draws them; this file holds the command ids, their
 * arguments and what the UI makes of the answers (free of DOM and services, so that it can be
 * tested on its own).
 */

/** `{projectRoot, sheets?, size?}` -> `{sheets: [{number, title, dxf, pdfPage, png}], pdf, bbsCsv, notes, problems}`. */
export const DRAWINGS_GENERATE_COMMAND = 'saengine.drawings.generate';
/** `{projectRoot}` -> the answer of the last generation, with `stale` when the model or design changed since. */
export const DRAWINGS_LIST_COMMAND = 'saengine.drawings.list';

/** The sheet sizes offered (ISO A series); A1 is the default. */
export const SHEET_SIZES = ['A1', 'A2', 'A3'] as const;
export type SheetSize = typeof SHEET_SIZES[number];
export const DEFAULT_SHEET_SIZE: SheetSize = 'A1';

export interface IDrawingsGenerateArgs {
	readonly projectRoot: string;
	/** The sheet numbers to draw again; left out for all. */
	readonly sheets?: readonly string[];
	readonly size?: SheetSize;
}

/** The arguments of {@link DRAWINGS_GENERATE_COMMAND}: an empty selection draws every sheet. */
export function generateArgs(projectRoot: string, options: { readonly sheets?: readonly string[]; readonly size?: SheetSize } = {}): IDrawingsGenerateArgs {
	const sheets = options.sheets?.filter(s => !!s.trim());
	return {
		projectRoot,
		...(sheets?.length ? { sheets } : {}),
		...(options.size ? { size: options.size } : {}),
	};
}

export interface IDrawingSheet {
	/** The sheet number on the title block ("S-101"). */
	readonly number: string;
	readonly title: string;
	readonly dxf?: URI;
	/** The sheet's page in the PDF set, from 1. */
	readonly pdfPage?: number;
	/** A picture of the sheet, for the thumbnail and the preview. */
	readonly png?: URI;
	readonly size?: string;
	readonly scale?: string;
	/** Drawn before the last change of the model or design. */
	readonly stale: boolean;
}

export interface IDrawingSet {
	readonly sheets: readonly IDrawingSheet[];
	/** All sheets in one PDF. */
	readonly pdf?: URI;
	/** The bar bending schedule. */
	readonly bbsCsv?: URI;
	/** When it was generated (ms since the epoch). */
	readonly generatedAt?: number;
	readonly size?: string;
	/** Some sheet is out of date. */
	readonly stale: boolean;
	/** What changed since, as the backend says it ("the design changed"). */
	readonly staleReason?: string;
	readonly notes: readonly string[];
	readonly problems: readonly string[];
}

type Bag = { readonly [key: string]: unknown };

function isBag(value: unknown): value is Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(...values: unknown[]): string | undefined {
	for (const value of values) {
		if (typeof value === 'string' && value.trim()) {
			return value.trim();
		}
		if (typeof value === 'number' && Number.isFinite(value)) {
			return String(value);
		}
	}
	return undefined;
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.map(v => isBag(v) ? text(v.message, v.text) : text(v)).filter((v): v is string => !!v) : (text(value) ? [text(value)!] : []);
}

/** A path of an answer: absolute, or relative to the project's root. */
export function resolveProjectPath(root: URI, path: unknown): URI | undefined {
	const value = text(path);
	if (!value) {
		return undefined;
	}
	if (isAbsolute(value) || /^[a-zA-Z]:[\\/]/.test(value) || value.startsWith('\\\\')) {
		return URI.file(value);
	}
	return joinPath(root, ...value.split(/[\\/]+/).filter(Boolean));
}

/** A time of an answer: ISO text, or seconds (as Python writes it) or milliseconds since the epoch. */
export function readTime(value: unknown): number | undefined {
	if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
		return value < 1e11 ? Math.round(value * 1000) : value;
	}
	if (typeof value === 'string' && value.trim()) {
		const time = Date.parse(value);
		return Number.isNaN(time) ? undefined : time;
	}
	return undefined;
}

/**
 * The drawings in an answer of {@link DRAWINGS_GENERATE_COMMAND} or {@link DRAWINGS_LIST_COMMAND}
 * (flat, or under `drawings`); undefined when none were generated yet. Staleness is the
 * backend's (`stale` on the set or a sheet, or under `stamps`).
 */
export function readDrawingSet(value: unknown, root: URI): IDrawingSet | undefined {
	const outer = isBag(value) ? value : {};
	const set = isBag(outer.drawings) ? outer.drawings : outer;
	const stamps = isBag(set.stamps) ? set.stamps : {};
	const setStale = set.stale === true || stamps.stale === true;
	const sheets: IDrawingSheet[] = [];
	for (const raw of Array.isArray(set.sheets) ? set.sheets : []) {
		if (!isBag(raw)) {
			continue;
		}
		const number = text(raw.number, raw.id, raw.name);
		if (!number) {
			continue;
		}
		const page = typeof raw.pdfPage === 'number' && Number.isInteger(raw.pdfPage) && raw.pdfPage > 0 ? raw.pdfPage : undefined;
		sheets.push({
			number,
			title: text(raw.title) ?? number,
			dxf: resolveProjectPath(root, raw.dxf),
			pdfPage: page,
			png: resolveProjectPath(root, raw.png ?? raw.preview),
			size: text(raw.size),
			scale: text(raw.scale),
			stale: setStale || raw.stale === true,
		});
	}
	const pdf = resolveProjectPath(root, set.pdf);
	const bbsCsv = resolveProjectPath(root, set.bbsCsv ?? set.bbs);
	const { errors, notes } = readProblemsBySeverity(set);
	if (!sheets.length && !pdf && !bbsCsv) {
		return errors.length || notes.length || strings(set.notes).length ? { sheets, stale: false, notes: [...strings(set.notes), ...notes], problems: errors } : undefined;
	}
	const changed = strings(stamps.changed ?? set.changed);
	return {
		sheets,
		pdf,
		bbsCsv,
		generatedAt: readTime(set.generatedAt ?? set.generated ?? stamps.generatedAt ?? set.time),
		size: text(set.size) ?? sheets.find(s => s.size)?.size,
		stale: setStale || sheets.some(s => s.stale),
		staleReason: text(set.staleReason, stamps.reason) ?? (changed.length ? localize('drawings.changedParts', "changed since: {0}", changed.join(', ')) : undefined),
		notes: [...strings(set.notes), ...notes],
		problems: errors,
	};
}

/**
 * What the section shows of a set, as text: two answers with the same key draw the same
 * (a re-list that changed nothing leaves the page, its focus and its open previews alone).
 */
export function drawingSetKey(set: IDrawingSet | undefined): string {
	// A URI's own toJSON carries cached state (fsPath, formatted), so it is written as its text.
	return set ? JSON.stringify({
		...set,
		pdf: set.pdf?.toString(), bbsCsv: set.bbsCsv?.toString(),
		sheets: set.sheets.map(s => ({ ...s, dxf: s.dxf?.toString(), png: s.png?.toString() })),
	}) : '';
}

/** The sheet as its preview shows it (undefined: it has no picture). */
export function previewSheet(sheet: IDrawingSheet, set: IDrawingSet, root: URI | undefined): IDrawingPreviewSheet | undefined {
	return sheet.png ? { number: sheet.number, title: sheet.title, png: sheet.png, dxf: sheet.dxf, pdf: set.pdf, pdfPage: sheet.pdfPage, size: sheet.size ?? set.size, scale: sheet.scale, stale: sheet.stale, root } : undefined;
}

/** The sheet of `set` whose picture is `png`, as its preview shows it. */
export function findPreviewSheet(set: IDrawingSet | undefined, png: URI, root: URI | undefined): IDrawingPreviewSheet | undefined {
	const sheet = set?.sheets.find(s => s.png?.toString() === png.toString());
	return sheet && set && previewSheet(sheet, set, root);
}

/** The sheets of `set` that the selection names, in the set's order (all when nothing is selected). */
export function selectedSheets(set: IDrawingSet | undefined, selection: ReadonlySet<string>): string[] {
	return set?.sheets.filter(s => selection.has(s.number)).map(s => s.number) ?? [];
}

/** The selection that is left after a new generation: the numbers still in the set. */
export function keepSelection(set: IDrawingSet | undefined, selection: ReadonlySet<string>): Set<string> {
	return new Set(selectedSheets(set, selection));
}

/** The label of the Generate button for the set and the selection. */
export function generateLabel(set: IDrawingSet | undefined, selected: number): string {
	if (selected > 0) {
		return selected === 1
			? localize('drawings.generateOne', "Generate 1 Sheet")
			: localize('drawings.generateSome', "Generate {0} Sheets", selected);
	}
	return set?.sheets.length ? localize('drawings.regenerate', "Regenerate Drawings") : localize('drawings.generate', "Generate Drawings");
}

/** The line under the section's title: what is there, or what is wrong with it. */
export function drawingsDescription(set: IDrawingSet | undefined, available: boolean): string {
	if (!available) {
		return localize('drawings.unavailable', "Drawing generation is not available in this build of SAEngine yet.");
	}
	if (!set?.sheets.length) {
		return localize('drawings.description', "Framing plans, column and beam schedules, slab, footing, wall and stair details with a title block, as DXF for LibreCAD and one PDF set, with the bar bending schedule.");
	}
	const count = set.sheets.length === 1 ? localize('drawings.oneSheet', "1 sheet") : localize('drawings.sheets', "{0} sheets", set.sheets.length);
	const outOfDate = set.sheets.filter(s => s.stale).length;
	if (outOfDate) {
		const which = outOfDate === set.sheets.length
			? localize('drawings.allStale', "out of date — regenerate")
			: localize('drawings.someStale', "{0} out of date — regenerate", outOfDate);
		return set.staleReason ? localize('drawings.countStaleReason', "{0}, {1} ({2})", count, which, set.staleReason) : localize('drawings.countStale', "{0}, {1}", count, which);
	}
	const current = set.size ? localize('drawings.countSize', "{0}, {1}, current", count, set.size) : localize('drawings.countCurrent', "{0}, current", count);
	if (!set.problems.length) {
		return current;
	}
	// Failing detailing or design checks (errors of the backend): not ready to issue.
	const problems = set.problems.length === 1 ? localize('drawings.oneProblem', "1 problem") : localize('drawings.problemCount', "{0} problems", set.problems.length);
	return localize('drawings.countProblems', "{0}; {1} to resolve before issue (listed below)", current, problems);
}

// ───────────────────────────── drawing settings ─────────────────────────────

/**
 * The title block and sheet settings: `drawings.*` of `02 Project Settings/project-settings.json`,
 * with the project's number and engineer (`project.*`) when the drawings do not name their own.
 */
export interface IDrawingSettings {
	readonly firm?: string;
	readonly engineer?: string;
	readonly checkedBy?: string;
	readonly approvedBy?: string;
	readonly projectNumber?: string;
	readonly revision?: { readonly code: string; readonly date?: string; readonly description?: string };
	readonly sheetSize: SheetSize;
	/** "1:100" */
	readonly planScale: string;
	/** "1:25" */
	readonly detailScale: string;
	/** The project settings have a `drawings` section. */
	readonly present: boolean;
	/**
	 * Where the drawings' own values differ from Project's (the engineer, the project number), as
	 * sentences: the sheets print the drawings' value, the report Project's.
	 */
	readonly conflicts: readonly string[];
}

export const DEFAULT_PLAN_SCALE = '1:100';
export const DEFAULT_DETAIL_SCALE = '1:25';

/** A scale as "1:n" from 100, "100", "1:100" or "1/100". */
export function readScale(value: unknown): string | undefined {
	const raw = text(value);
	if (!raw) {
		return undefined;
	}
	const match = /^(?:1\s*[:/]\s*)?(?<denominator>\d+(?:\.\d+)?)$/.exec(raw);
	const denominator = match?.groups ? Number(match.groups.denominator) : NaN;
	return Number.isFinite(denominator) && denominator > 0 ? `1:${denominator}` : undefined;
}

export function readSheetSize(value: unknown): SheetSize | undefined {
	const raw = text(value)?.toUpperCase();
	return SHEET_SIZES.find(size => size === raw);
}

/** The drawing settings in the parsed project settings (any shape: missing values take the defaults). */
export function readDrawingSettings(settings: unknown): IDrawingSettings {
	const root = isBag(settings) ? settings : {};
	const drawings = isBag(root.drawings) ? root.drawings : {};
	const project = isBag(root.project) ? root.project : {};
	const scales = isBag(drawings.scales) ? drawings.scales : {};
	const revisions = Array.isArray(drawings.revisions) ? drawings.revisions : [];
	const rawRevision = drawings.revision ?? revisions[revisions.length - 1];
	const revision = isBag(rawRevision)
		? text(rawRevision.code, rawRevision.number, rawRevision.rev, rawRevision.revision)
		: text(rawRevision);
	const conflicts: string[] = [];
	const differ = (own: string | undefined, projects: string | undefined, message: (own: string, projects: string) => string) => {
		if (own && projects && own !== projects) {
			conflicts.push(message(own, projects));
		}
	};
	differ(text(drawings.engineer), text(project.engineer), (own, projects) => localize('drawings.engineerConflict', "The drawings name the engineer {0}, Project names {1}.", own, projects));
	differ(text(drawings.projectNumber), text(project.number), (own, projects) => localize('drawings.numberConflict', "The drawings' project number is {0}, Project's is {1}.", own, projects));
	return {
		firm: text(drawings.firm, drawings.firmName),
		engineer: text(drawings.engineer, project.engineer),
		checkedBy: text(drawings.checkedBy, drawings.checked),
		approvedBy: text(drawings.approvedBy, drawings.approved),
		projectNumber: text(drawings.projectNumber, project.number),
		revision: revision ? {
			code: revision,
			date: isBag(rawRevision) ? text(rawRevision.date) : text(drawings.revisionDate),
			description: isBag(rawRevision) ? text(rawRevision.description) : text(drawings.revisionDescription),
		} : undefined,
		sheetSize: readSheetSize(drawings.sheetSize ?? drawings.size) ?? DEFAULT_SHEET_SIZE,
		planScale: readScale(drawings.planScale ?? scales.plan) ?? DEFAULT_PLAN_SCALE,
		detailScale: readScale(drawings.detailScale ?? scales.detail) ?? DEFAULT_DETAIL_SCALE,
		present: isBag(root.drawings),
		conflicts,
	};
}

/** The settings as the page lists them: name and value (undefined when not set). */
export function drawingSettingsRows(settings: IDrawingSettings): { readonly name: string; readonly value: string | undefined }[] {
	const revision = settings.revision;
	return [
		{ name: localize('drawings.firm', "Firm"), value: settings.firm },
		{ name: localize('drawings.engineer', "Engineer"), value: settings.engineer },
		{ name: localize('drawings.checkedBy', "Checked by"), value: settings.checkedBy },
		{ name: localize('drawings.approvedBy', "Approved by"), value: settings.approvedBy },
		{ name: localize('drawings.projectNumber', "Project number"), value: settings.projectNumber },
		{
			name: localize('drawings.revision', "Revision"),
			value: revision ? [revision.code, revision.date, revision.description].filter(Boolean).join(' · ') : undefined,
		},
		{ name: localize('drawings.sheetSize', "Sheet size"), value: settings.sheetSize },
		{ name: localize('drawings.scales', "Scales"), value: localize('drawings.scalesValue', "plans {0}, details {1}", settings.planScale, settings.detailScale) },
	];
}

// ───────────────────────────── the preview's view ─────────────────────────────

/** The preview's zoom (screen pixels per image pixel) and the image's offset in the viewport. */
export interface IPreviewView {
	readonly zoom: number;
	readonly x: number;
	readonly y: number;
}

export const MIN_PREVIEW_ZOOM = 0.02;
export const MAX_PREVIEW_ZOOM = 8;

function clampZoom(zoom: number): number {
	return Math.max(MIN_PREVIEW_ZOOM, Math.min(MAX_PREVIEW_ZOOM, zoom));
}

/** The whole image centred in the viewport, with a small margin. */
export function fitView(imageWidth: number, imageHeight: number, viewWidth: number, viewHeight: number, margin = 16): IPreviewView {
	if (imageWidth <= 0 || imageHeight <= 0 || viewWidth <= 0 || viewHeight <= 0) {
		return { zoom: 1, x: 0, y: 0 };
	}
	const zoom = clampZoom(Math.min((viewWidth - 2 * margin) / imageWidth, (viewHeight - 2 * margin) / imageHeight));
	return { zoom, x: (viewWidth - imageWidth * zoom) / 2, y: (viewHeight - imageHeight * zoom) / 2 };
}

/** The view zoomed by `factor` about the viewport point (`px`, `py`), which stays put. */
export function zoomAt(view: IPreviewView, factor: number, px: number, py: number): IPreviewView {
	const zoom = clampZoom(view.zoom * factor);
	const ratio = zoom / view.zoom;
	return { zoom, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio };
}

/** The zoom as the toolbar shows it ("125%"). */
export function zoomLabel(view: IPreviewView): string {
	return localize('drawings.zoom', "{0}%", Math.round(view.zoom * 100));
}
