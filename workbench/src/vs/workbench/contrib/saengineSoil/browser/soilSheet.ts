/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatField, formatNumber, IBorehole, IFieldSpec, ISoilLayer, ISoilProblem, ISoilSample, ISptRecord, LAYER_FIELDS, parseField, SOIL_TYPES, soilTypeLabel } from './soilDocument.js';

/*
 * The log sheet of a borehole as a spreadsheet: the model behind the grid (soilGrid.ts), free of
 * the DOM so it can be tested. Two sheets: the strata (the layers, one row each) and the samples
 * and SPT in the consultant's order (one row per test depth: the SPT record and the lab sample
 * at that depth side by side). Cells are read and written as the text the engineer sees (depths
 * in m); a write parses the text, stores the value in the borehole and keeps the lists in order.
 */

/** A group of columns with one header over them; groups other than the first can be collapsed. */
export interface ISheetGroup {
	readonly id: string;
	readonly label: string;
	readonly title?: string;
}

export interface ISheetOption {
	readonly value: string;
	readonly label: string;
}

export interface ISheetColumn {
	readonly id: string;
	readonly group: string;
	readonly label: string;
	readonly unit?: string;
	readonly title?: string;
	/** Width in the grid [px]. */
	readonly width: number;
	readonly numeric: boolean;
	/** Worked out from other cells: never edited, shown greyed. */
	readonly computed?: boolean;
	/** The values to pick from (the cell also takes their labels and unique prefixes). */
	readonly options?: readonly ISheetOption[];
}

export interface ICellPosition {
	readonly row: number;
	/** Index into the sheet's columns. */
	readonly column: number;
}

/** A cell to write as typed; a row at or past the end adds a row. */
export interface ISheetWrite {
	readonly row: number;
	readonly column: string;
	readonly text: string;
	/** From a pasted block: a blank cell then leaves a value shared by rows (a stratum's) alone. */
	readonly paste?: boolean;
}

export interface ISheetCellError {
	readonly row: number;
	readonly column: string;
	readonly message: string;
}

export interface ISheetWriteResult {
	/** Cells stored. */
	readonly written: number;
	/** Rows added. */
	readonly added: number;
	/** Cells refused, with why. */
	readonly errors: readonly ISheetCellError[];
	/**
	 * Where each written row is after the write: the sheets keep their rows in depth order, so a
	 * row whose depth was typed (a new one, or a changed one) can move. Rows not listed stay put.
	 */
	readonly rows?: ReadonlyMap<number, number>;
}

export interface ISheet {
	readonly id: string;
	readonly label: string;
	readonly columns: readonly ISheetColumn[];
	readonly groups: readonly ISheetGroup[];
	rowCount(): number;
	/** What the cell shows. */
	text(row: number, column: ISheetColumn): string;
	/** What an edit of the cell starts from. */
	editText(row: number, column: ISheetColumn): string;
	isReadOnly(row: number, column: ISheetColumn): boolean;
	/** Whether the cell shows a value worked out, not entered (greyed). */
	isDerived(row: number, column: ISheetColumn): boolean;
	/** A cell's error or warning (red or amber, with its hover). */
	problem(row: number, column: ISheetColumn): { readonly message: string; readonly severity: 'error' | 'warning' } | undefined;
	/** A hover for a read-only cell: why it cannot be edited. */
	hint(row: number, column: ISheetColumn): string | undefined;
	write(writes: readonly ISheetWrite[]): ISheetWriteResult;
	removeRows(rows: readonly number[]): void;
}

// ───────────────────────────── text: Excel's clipboard ─────────────────────────────

/**
 * Cells copied from Excel (or any spreadsheet): rows by line, cells by tab. A cell with a tab,
 * a line break or a quote comes in quotes with the quotes doubled. The line break after the last
 * row is not a row; blank cells stay blank.
 */
export function parseTsv(text: string): string[][] {
	const rows: string[][] = [];
	let row: string[] = [];
	let cell = '';
	let quoted = false;
	let atStart = true;
	for (let i = 0; i < text.length; i++) {
		const ch = text[i];
		if (quoted) {
			if (ch === '"') {
				if (text[i + 1] === '"') {
					cell += '"';
					i++;
				} else {
					quoted = false;
				}
			} else {
				cell += ch;
			}
			continue;
		}
		if (ch === '"' && atStart) {
			quoted = true;
			atStart = false;
			continue;
		}
		if (ch === '\t') {
			row.push(cell);
			cell = '';
			atStart = true;
		} else if (ch === '\n' || ch === '\r') {
			if (ch === '\r' && text[i + 1] === '\n') {
				i++;
			}
			row.push(cell);
			rows.push(row);
			row = [];
			cell = '';
			atStart = true;
		} else {
			cell += ch;
			atStart = false;
		}
	}
	if (cell || row.length) {
		row.push(cell);
		rows.push(row);
	}
	return rows.map(r => r.map(c => c.trim()));
}

/** Cells as Excel pastes them back: tabs and line breaks, quoting where needed. */
export function formatTsv(cells: readonly (readonly string[])[]): string {
	const quote = (cell: string) => /[\t\r\n"]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
	return cells.map(row => row.map(quote).join('\t')).join('\r\n') + '\r\n';
}

// ───────────────────────────── navigation ─────────────────────────────

export type SheetMove = 'up' | 'down' | 'left' | 'right' | 'tab' | 'shiftTab' | 'enter' | 'shiftEnter' | 'home' | 'end' | 'top' | 'bottom';

/**
 * The cell a key moves to. `visible` are the columns shown (collapsed groups left out), in order;
 * `rows` counts the row for a new entry below the last when `newRow` is set. Tab runs along the
 * row and wraps to the next one, Enter goes down, the arrows stop at the edges.
 */
export function moveCell(position: ICellPosition, move: SheetMove, visible: readonly number[], rowCount: number, newRow = true): ICellPosition {
	const rows = rowCount + (newRow ? 1 : 0);
	if (!visible.length || rows <= 0) {
		return position;
	}
	let at = visible.indexOf(position.column);
	if (at < 0) {
		at = Math.max(0, visible.findIndex(c => c > position.column));
	}
	let row = Math.max(0, Math.min(rows - 1, position.row));
	switch (move) {
		case 'up': row = Math.max(0, row - 1); break;
		case 'down': case 'enter': row = Math.min(rows - 1, row + 1); break;
		case 'shiftEnter': row = Math.max(0, row - 1); break;
		case 'left': at = Math.max(0, at - 1); break;
		case 'right': at = Math.min(visible.length - 1, at + 1); break;
		case 'home': at = 0; break;
		case 'end': at = visible.length - 1; break;
		case 'top': row = 0; break;
		case 'bottom': row = rows - 1; break;
		case 'tab':
			if (at < visible.length - 1) {
				at++;
			} else if (row < rows - 1) {
				at = 0;
				row++;
			}
			break;
		case 'shiftTab':
			if (at > 0) {
				at--;
			} else if (row > 0) {
				at = visible.length - 1;
				row--;
			}
			break;
	}
	return { row, column: visible[at] };
}

/** How a block of `height` rows pasted at `row` fits: the rows it adds past the end. */
export function pasteAddsRows(row: number, height: number, rowCount: number): number {
	return Math.max(0, row + height - rowCount);
}

/**
 * The writes of a block pasted with its top left at `at`: the block's columns go to the visible
 * columns from there on (cells past the last column are dropped), skipping computed columns.
 */
export function pasteWrites(sheet: ISheet, at: ICellPosition, block: readonly (readonly string[])[], visible: readonly number[]): ISheetWrite[] {
	const start = Math.max(0, visible.indexOf(at.column));
	const writes: ISheetWrite[] = [];
	block.forEach((cells, r) => {
		cells.forEach((text, c) => {
			const column = sheet.columns[visible[start + c]];
			if (column && !column.computed) {
				writes.push({ row: at.row + r, column: column.id, text, paste: true });
			}
		});
	});
	return writes;
}

// ───────────────────────────── shared cell helpers ─────────────────────────────

/** A value picked by its value, its label, or a prefix of either that only one option has. */
export function matchOption(options: readonly ISheetOption[], text: string): string | undefined {
	const lower = text.trim().toLowerCase();
	if (!lower) {
		return undefined;
	}
	const exact = options.find(o => o.value.toLowerCase() === lower || o.label.toLowerCase() === lower);
	if (exact) {
		return exact.value;
	}
	const prefixed = options.filter(o => o.value.toLowerCase().startsWith(lower) || o.label.toLowerCase().startsWith(lower));
	return prefixed.length === 1 ? prefixed[0].value : undefined;
}

function setOrDelete(target: { [key: string]: unknown }, key: string, value: unknown): void {
	if (value === undefined) {
		delete target[key];
	} else {
		target[key] = value;
	}
}

const M = localize('soil.unit.m', "m");
const PERCENT = '%';

/** A column read from a field spec of soilDocument.ts. */
function fieldColumn(spec: IFieldSpec, group: string, extra: Partial<ISheetColumn> = {}): ISheetColumn {
	return {
		id: spec.key, group, label: spec.label, unit: spec.unit, title: spec.title,
		width: Math.max(52, Math.min(spec.width ?? 60, 240)), numeric: spec.kind !== 'text' && spec.kind !== 'soilType', ...extra,
	};
}

const SOIL_TYPE_OPTIONS: readonly ISheetOption[] = SOIL_TYPES.map(type => ({ value: type, label: soilTypeLabel(type) }));

// ───────────────────────────── strata ─────────────────────────────

const STRATA_GROUPS: readonly ISheetGroup[] = [
	{ id: 'stratum', label: localize('soil.sheet.g.stratum', "Stratum") },
	{ id: 'weight', label: localize('soil.sheet.g.weight', "Unit weight") },
	{ id: 'strength', label: localize('soil.sheet.g.strength', "Strength") },
	{ id: 'index', label: localize('soil.sheet.g.index', "Index") },
	{ id: 'consolidation', label: localize('soil.sheet.g.consolidation', "Consolidation") },
];

const STRATA_GROUP_OF: { readonly [key: string]: string } = {
	top: 'stratum', bottom: 'stratum', soilType: 'stratum', uscs: 'stratum', description: 'stratum',
	unitWeight: 'weight', saturatedUnitWeight: 'weight',
	cu: 'strength', c: 'strength', phi: 'strength', E: 'strength',
	finesContent: 'index', plasticityIndex: 'index', liquidLimit: 'index',
	Cc: 'consolidation', Cr: 'consolidation', e0: 'consolidation', OCR: 'consolidation',
};

/** The layer fields in the order of the sheet: the stratum first (description last of it). */
const STRATA_ORDER = ['top', 'bottom', 'soilType', 'uscs', 'description', 'unitWeight', 'saturatedUnitWeight', 'cu', 'c', 'phi', 'E', 'finesContent', 'plasticityIndex', 'liquidLimit', 'Cc', 'Cr', 'e0', 'OCR'];

const STRATA_FIELDS: readonly IFieldSpec[] = STRATA_ORDER.map(key => LAYER_FIELDS.find(f => f.key === key)!).filter(Boolean);

/** The strata of a borehole: one row per layer, in the file's order (top down). */
export class StrataSheet implements ISheet {

	readonly id = 'strata';
	readonly label = localize('soil.sheet.strata', "Strata");
	readonly groups = STRATA_GROUPS;
	readonly columns: readonly ISheetColumn[] = STRATA_FIELDS.map(spec => fieldColumn(spec, STRATA_GROUP_OF[spec.key] ?? 'stratum', spec.kind === 'soilType' ? { options: SOIL_TYPE_OPTIONS, width: 84 } : spec.key === 'description' ? { width: 240 } : {}));

	/**
	 * @param problems the report's problems (checkSoilReport): those of this borehole's layers mark their cells.
	 */
	constructor(
		private readonly borehole: IBorehole,
		private readonly boreholeIndex: number,
		private readonly problems: readonly ISoilProblem[] = [],
	) { }

	rowCount(): number {
		return this.borehole.layers.length;
	}

	private spec(column: ISheetColumn): IFieldSpec {
		return STRATA_FIELDS.find(f => f.key === column.id)!;
	}

	text(row: number, column: ISheetColumn): string {
		const layer = this.borehole.layers[row];
		if (!layer) {
			return '';
		}
		const value = layer[column.id];
		return column.options ? (column.options.find(o => o.value === value)?.label ?? String(value ?? '')) : formatField(this.spec(column), value);
	}

	editText(row: number, column: ISheetColumn): string {
		return this.text(row, column);
	}

	isReadOnly(): boolean {
		return false;
	}

	isDerived(): boolean {
		return false;
	}

	problem(row: number, column: ISheetColumn): { message: string; severity: 'error' | 'warning' } | undefined {
		const path = `layers.${row}.${column.id}`;
		const found = this.problems.find(p => p.index === this.boreholeIndex && p.path === path);
		return found ? { message: found.message, severity: found.severity } : undefined;
	}

	hint(): string | undefined {
		return undefined;
	}

	write(writes: readonly ISheetWrite[]): ISheetWriteResult {
		const layers = this.borehole.layers;
		const targets = new Map<number, ISoilLayer>();
		const errors: ISheetCellError[] = [];
		let added = 0;
		let written = 0;
		const layerAt = (row: number): ISoilLayer => {
			let layer = targets.get(row) ?? layers[row];
			if (!layer) {
				const previous = layers[layers.length - 1];
				const top = previous ? previous.bottom : 0;
				layer = { top, bottom: top + 1000, description: '', soilType: previous?.soilType ?? 'clay' };
				layers.push(layer);
				added++;
			}
			targets.set(row, layer);
			return layer;
		};
		// New rows are only made for a row that has something to write.
		for (const w of [...writes].sort((a, b) => a.row - b.row)) {
			const column = this.columns.find(c => c.id === w.column);
			if (!column) {
				continue;
			}
			if (w.row >= layers.length && !targets.has(w.row) && !w.text.trim()) {
				continue;
			}
			let parsed;
			if (column.options) {
				const value = matchOption(column.options, w.text);
				parsed = value ? { value } : { error: localize('soil.v.soilType', "Pick one of: {0}.", SOIL_TYPES.join(', ')) };
			} else {
				parsed = parseField(this.spec(column), w.text);
			}
			if (parsed.error) {
				errors.push({ row: w.row, column: w.column, message: parsed.error });
				continue;
			}
			setOrDelete(layerAt(w.row), column.id, parsed.value);
			written++;
		}
		layers.sort((a, b) => a.top - b.top);
		const rows = new Map<number, number>();
		for (const [row, layer] of targets) {
			rows.set(row, layers.indexOf(layer));
		}
		return { written, added, errors, rows };
	}

	removeRows(rows: readonly number[]): void {
		const remove = new Set(rows.map(r => this.borehole.layers[r]).filter(Boolean));
		this.borehole.layers = this.borehole.layers.filter(l => !remove.has(l));
	}
}

// ───────────────────────────── samples and SPT ─────────────────────────────

/** One row of the samples sheet: what was done at one depth. */
export interface ISampleRow {
	depth: number;
	spt?: ISptRecord;
	sample?: ISoilSample;
}

/** Two depths closer than this are one row [mm]. */
const SAME_DEPTH = 1;

/** The length of the SPT drive: the seating drive and the two counted increments [mm]. */
export const SPT_DRIVE = 450;

/** Blows in one 150 mm increment that stop the test (ASTM D1586 refusal). */
export const REFUSAL_BLOWS = 50;

/** The rows of a borehole: its SPT records and samples, side by side where at the same depth. */
export function sampleRows(borehole: IBorehole): ISampleRow[] {
	const rows: ISampleRow[] = borehole.spt.map(spt => ({ depth: spt.depth, spt }));
	for (const sample of borehole.samples) {
		const row = rows.find(r => !r.sample && Math.abs(r.depth - sample.depth) <= SAME_DEPTH);
		if (row) {
			row.sample = sample;
		} else {
			rows.push({ depth: sample.depth, sample });
		}
	}
	return rows.sort((a, b) => a.depth - b.depth);
}

/**
 * The field N of the increments: N1 + N2, the blows of the second and third 150 mm. With
 * refusal in the second increment the third is not driven and counts as 0. Undefined until the
 * increments that count are given.
 */
export function deriveN(spt: Pick<ISptRecord, 'N1' | 'N2' | 'refusal'>): number | undefined {
	const refusal = spt.refusal;
	if (typeof refusal === 'object' && refusal && refusal.penetration > 0) {
		// "50/100 mm": the blows at the same rate for 300 mm, at most 300.
		return Math.min(300, Math.round(refusal.blows * 300 / refusal.penetration));
	}
	if (refusal === true && (typeof spt.N1 === 'number' || typeof spt.N2 === 'number')) {
		return (spt.N1 ?? 0) + (spt.N2 ?? 0);
	}
	return typeof spt.N1 === 'number' && typeof spt.N2 === 'number' ? spt.N1 + spt.N2 : undefined;
}

/**
 * The N of a record: as entered, else worked out from its increments or refusal. As in the
 * backend (library/soil.py SptRecord), the worked-out N is never stored, so a later correction of
 * the increments or the refusal changes it; an entered N that differs is kept, used and flagged.
 */
export function sptBlows(spt: ISptRecord): number | undefined {
	return typeof spt.N === 'number' ? spt.N : deriveN(spt);
}

/** Whether the record gives any of the increments N1, N2. */
function hasIncrements(spt: ISptRecord | undefined): boolean {
	return typeof spt?.N1 === 'number' || typeof spt?.N2 === 'number';
}

/** The results of the backend at a depth, for the computed N60 columns. */
export type SptResultAt = (depth: number) => { readonly N60?: number; readonly N160?: number } | undefined;

const DEPTH_SPEC: IFieldSpec = { key: 'depth', label: localize('soil.sheet.from', "From"), unit: M, kind: 'depth', min: 0, required: true };
const DEPTH_TO_SPEC: IFieldSpec = { key: 'depthTo', label: localize('soil.sheet.to', "To"), unit: M, kind: 'depth', min: 0 };
const BLOWS = (key: string, label: string, title: string): IFieldSpec => ({ key, label, kind: 'integer', min: 0, max: 300, title });

const SAMPLE_COLUMN_SPECS: readonly { readonly spec: IFieldSpec; readonly group: string; readonly target: 'row' | 'sample' | 'spt' | 'layer' | 'computed'; readonly width?: number; readonly options?: readonly ISheetOption[] }[] = [
	{ spec: DEPTH_SPEC, group: 'sample', target: 'row', width: 58 },
	{ spec: DEPTH_TO_SPEC, group: 'sample', target: 'row', width: 58 },
	{ spec: { key: 'number', label: localize('soil.sheet.number', "No."), kind: 'text', title: localize('soil.sheet.numberTitle', "The sample's number on the log, e.g. D-3 or UD-1") }, group: 'sample', target: 'sample', width: 56 },
	{ spec: { key: 'type', label: localize('soil.f.sampleType', "Type"), kind: 'text', title: localize('soil.f.sampleTypeTitle', "UD (undisturbed), SPT (split spoon), D (disturbed)...") }, group: 'sample', target: 'sample', width: 52 },
	{ spec: BLOWS('seat', localize('soil.sheet.seat', "Seat"), localize('soil.sheet.seatTitle', "Blows of the seating drive, the first 150 mm (not counted in N)")), group: 'spt', target: 'spt', width: 48 },
	{ spec: BLOWS('N1', 'N1', localize('soil.sheet.n1Title', "Blows of the second 150 mm")), group: 'spt', target: 'spt', width: 46 },
	{ spec: BLOWS('N2', 'N2', localize('soil.sheet.n2Title', "Blows of the third 150 mm")), group: 'spt', target: 'spt', width: 46 },
	{ spec: { key: 'N', label: 'N', kind: 'integer', min: 0, max: 300, title: localize('soil.sheet.nTitle', "Field N: worked out as N1 + N2 (blows for 300 mm, greyed) unless the log gives its own N; an entered N that differs is used and flagged") }, group: 'spt', target: 'spt', width: 46 },
	{ spec: { key: 'refusal', label: localize('soil.sheet.refusal', "Ref."), kind: 'text', title: localize('soil.sheet.refusalTitle', "Refusal: the test stopped at 50 blows in an increment (ASTM D1586). Type R, yes or x; Delete clears it.") }, group: 'spt', target: 'spt', width: 40 },
	{ spec: { key: 'recovery', label: localize('soil.sheet.recovery', "Rec."), unit: PERCENT, kind: 'number', min: 0, max: 100, title: localize('soil.sheet.recoveryTitle', "Recovery: the length recovered over the length driven") }, group: 'spt', target: 'sample', width: 46 },
	{ spec: { key: 'energyRatio', label: 'ER', unit: PERCENT, kind: 'number', min: 30, max: 100, title: localize('soil.sheet.erTitle', "Hammer energy ratio of this test; overrides the report's hammer energy for N60. Empty: the report's.") }, group: 'spt', target: 'spt', width: 40 },
	{ spec: { key: 'description', label: localize('soil.f.description', "Description"), kind: 'text', title: localize('soil.sheet.descriptionTitle', "The description of the stratum at this depth; editing it edits the stratum") }, group: 'stratum', target: 'layer', width: 220 },
	{ spec: { key: 'uscs', label: localize('soil.f.uscs', "USCS"), kind: 'text', title: localize('soil.f.uscsTitle', "Unified Soil Classification System group symbol (ASTM D2487), e.g. CL, ML, SM") }, group: 'stratum', target: 'layer', width: 50 },
	{ spec: { key: 'moisture', label: 'w', unit: PERCENT, kind: 'number', min: 0, max: 1000, title: localize('soil.f.wTitle', "Natural moisture content") }, group: 'index', target: 'sample' },
	{ spec: { key: 'unitWeight', label: 'γ', unit: localize('soil.unit.knm3', "kN/m³"), kind: 'number', min: 5, max: 30, title: localize('soil.sheet.gammaTitle', "Bulk unit weight") }, group: 'index', target: 'sample' },
	{ spec: { key: 'liquidLimit', label: 'LL', unit: PERCENT, kind: 'number', min: 0, max: 500, title: localize('soil.f.llTitle', "Liquid limit") }, group: 'index', target: 'sample' },
	{ spec: { key: 'plasticLimit', label: 'PL', unit: PERCENT, kind: 'number', min: 0, max: 500, title: localize('soil.sheet.plTitle', "Plastic limit") }, group: 'index', target: 'sample' },
	{ spec: { key: 'PI', label: 'PI', unit: PERCENT, kind: 'number', title: localize('soil.sheet.piTitle', "Plasticity index PI = LL − PL (computed)") }, group: 'index', target: 'computed' },
	{ spec: { key: 'finesContent', label: 'FC', unit: PERCENT, kind: 'number', min: 0, max: 100, title: localize('soil.f.fcTitle', "Fines content (passing 75 µm)") }, group: 'index', target: 'sample' },
	{ spec: { key: 'cu', label: 'cu', unit: localize('soil.unit.kpa', "kPa"), kind: 'number', min: 0, max: 2000, title: localize('soil.f.cuSampleTitle', "Undrained shear strength (unconfined compression or UU triaxial)") }, group: 'strength', target: 'sample' },
	{ spec: { key: 'c', label: 'c′', unit: localize('soil.unit.kpa', "kPa"), kind: 'number', min: 0, max: 500, title: localize('soil.f.cTitle', "Effective cohesion") }, group: 'strength', target: 'sample' },
	{ spec: { key: 'phi', label: 'φ′', unit: '°', kind: 'number', min: 0, max: 50, title: localize('soil.f.phiTitle', "Effective friction angle") }, group: 'strength', target: 'sample' },
	{ spec: { key: 'Cc', label: 'Cc', kind: 'number', min: 0, max: 10, title: localize('soil.f.ccTitle', "Compression index") }, group: 'consolidation', target: 'sample' },
	{ spec: { key: 'e0', label: 'e0', kind: 'number', min: 0, max: 20, title: localize('soil.f.e0Title', "Initial void ratio") }, group: 'consolidation', target: 'sample' },
];

const SAMPLE_GROUPS: readonly ISheetGroup[] = [
	{ id: 'sample', label: localize('soil.sheet.g.sample', "Sample") },
	{ id: 'spt', label: localize('soil.sheet.g.spt', "SPT") },
	{ id: 'stratum', label: localize('soil.sheet.g.stratum', "Stratum") },
	{ id: 'index', label: localize('soil.sheet.g.index', "Index") },
	{ id: 'strength', label: localize('soil.sheet.g.strength', "Strength") },
	{ id: 'consolidation', label: localize('soil.sheet.g.consolidation', "Consolidation") },
];

const REFUSAL_WORDS = new Set(['r', 'ref', 'refusal', 'y', 'yes', 'x', '1', 'true', '✓']);

/** A refusal typed as the consultant writes it: "50/100" or "50/100 mm" (blows / penetration). */
function parseRefusal(text: string): { blows: number; penetration: number } | undefined {
	const match = /^(?<blows>\d+)\s*\/\s*(?<penetration>\d+(?:\.\d+)?)\s*(?:mm)?$/.exec(text.trim());
	const blows = Number(match?.groups?.blows);
	const penetration = Number(match?.groups?.penetration);
	// As the backend's SptRefusal: 1 to 300 blows, a penetration short of the 300 mm test drive.
	return match && Number.isInteger(blows) && blows >= 1 && blows <= 300 && penetration > 0 && penetration < 300 ? { blows, penetration } : undefined;
}

function refusalText(refusal: ISptRecord['refusal']): string {
	return typeof refusal === 'object' && refusal ? `${refusal.blows}/${formatNumber(refusal.penetration)}` : refusal ? 'R' : '';
}
const NO_WORDS = new Set(['n', 'no', '0', 'false', '-', '—']);

/**
 * The samples and SPT of a borehole in the consultant's order: depth from–to, sample number and
 * type, the SPT increments with N worked out, refusal, recovery, the stratum's description and
 * USCS, then the lab values. A row is the SPT record and the sample at one depth.
 */
export class SampleSheet implements ISheet {

	readonly id = 'samples';
	readonly label = localize('soil.sheet.samples', "Samples and SPT");
	readonly groups = SAMPLE_GROUPS;
	readonly columns: readonly ISheetColumn[];
	private rows: ISampleRow[];
	private readonly problems = new Map<string, { message: string; severity: 'error' | 'warning' }>();

	constructor(
		private readonly borehole: IBorehole,
		private readonly resultAt?: SptResultAt,
	) {
		const columns: ISheetColumn[] = SAMPLE_COLUMN_SPECS.map(({ spec, group, target, width, options }) => fieldColumn(spec, group, { width: width ?? 50, computed: target === 'computed', options }));
		if (resultAt) {
			// The backend's corrected values, after N.
			const at = columns.findIndex(c => c.id === 'N') + 1;
			columns.splice(at, 0,
				{ id: 'N60', group: 'spt', label: 'N60', width: 46, numeric: true, computed: true, title: localize('soil.n60Title', "N corrected to 60% hammer energy (computed)") },
				{ id: 'N160', group: 'spt', label: '(N1)60', width: 50, numeric: true, computed: true, title: localize('soil.n160Title', "N60 corrected to an effective overburden of 100 kPa (computed)") },
			);
		}
		this.columns = columns;
		this.rows = sampleRows(borehole);
		this.validate();
	}

	rowCount(): number {
		return this.rows.length;
	}

	/** The row's records (for the lab test panel). */
	rowAt(row: number): ISampleRow | undefined {
		return this.rows[row];
	}

	/** The row of a sample (after a re-render the sample object is the way back to its row). */
	rowOf(sample: ISoilSample | undefined): number {
		return sample ? this.rows.findIndex(r => r.sample === sample) : -1;
	}

	private spec(column: ISheetColumn) {
		return SAMPLE_COLUMN_SPECS.find(s => s.spec.key === column.id);
	}

	/** The stratum a depth is in (its top inclusive), or the last one at its bottom. */
	private layerAt(depth: number): ISoilLayer | undefined {
		const layers = this.borehole.layers;
		return layers.find(l => l.top <= depth + SAME_DEPTH && depth < l.bottom - SAME_DEPTH) ?? layers.find(l => Math.abs(l.bottom - depth) <= SAME_DEPTH);
	}

	/** The bottom of the row: the sample's, the SPT's, or the end of the SPT drive. */
	private depthTo(row: ISampleRow): { value?: number; derived: boolean } {
		const own = row.sample?.depthTo ?? row.spt?.depthTo;
		if (typeof own === 'number') {
			return { value: own, derived: false };
		}
		return row.spt ? { value: row.depth + SPT_DRIVE, derived: true } : { derived: true };
	}

	private value(row: ISampleRow, column: ISheetColumn): { value?: unknown; derived: boolean } {
		switch (column.id) {
			case 'depth': return { value: row.depth, derived: false };
			case 'depthTo': return this.depthTo(row);
			case 'N': return { value: row.spt ? sptBlows(row.spt) : undefined, derived: !!row.spt && typeof row.spt.N !== 'number' };
			case 'refusal': return { value: refusalText(row.spt?.refusal), derived: false };
			case 'number': return { value: row.sample?.number ?? row.spt?.sampleNumber, derived: false };
			case 'recovery': return { value: row.sample?.recovery ?? row.spt?.recovery, derived: false };
			case 'PI': {
				const ll = row.sample?.liquidLimit;
				const pl = row.sample?.plasticLimit;
				return { value: typeof ll === 'number' && typeof pl === 'number' ? Math.round((ll - pl) * 100) / 100 : undefined, derived: true };
			}
			case 'N60': return { value: this.resultAt?.(row.depth)?.N60, derived: true };
			case 'N160': return { value: this.resultAt?.(row.depth)?.N160, derived: true };
		}
		const target = this.spec(column)?.target;
		if (target === 'layer') {
			return { value: this.layerAt(row.depth)?.[column.id], derived: false };
		}
		return { value: (target === 'spt' ? row.spt : row.sample)?.[column.id], derived: false };
	}

	text(row: number, column: ISheetColumn): string {
		const r = this.rows[row];
		if (!r) {
			return '';
		}
		const { value } = this.value(r, column);
		if (column.id === 'N60' || column.id === 'N160') {
			return typeof value === 'number' ? formatNumber(value, 1) : '';
		}
		const spec = this.spec(column)?.spec;
		return spec ? formatField(spec, value) : String(value ?? '');
	}

	editText(row: number, column: ISheetColumn): string {
		const r = this.rows[row];
		return r && this.value(r, column).derived && column.id === 'depthTo' ? '' : this.text(row, column);
	}

	isReadOnly(row: number, column: ISheetColumn): boolean {
		if (column.computed) {
			return true;
		}
		const r = this.rows[row];
		if (!r) {
			return false; // the row for a new entry
		}
		if (this.spec(column)?.target === 'layer') {
			return !this.layerAt(r.depth);
		}
		return false;
	}

	isDerived(row: number, column: ISheetColumn): boolean {
		const r = this.rows[row];
		return column.computed === true || !!r && this.value(r, column).derived && this.text(row, column) !== '';
	}

	problem(row: number, column: ISheetColumn): { message: string; severity: 'error' | 'warning' } | undefined {
		return this.problems.get(`${row}|${column.id}`);
	}

	hint(row: number, column: ISheetColumn): string | undefined {
		const r = this.rows[row];
		if (column.id === 'N' && r?.spt && typeof r.spt.N !== 'number' && deriveN(r.spt) !== undefined) {
			return typeof r.spt.refusal === 'object'
				? localize('soil.sheet.nFromRefusal', "N worked out from the refusal, scaled to 300 mm (not stored); type a value only to enter the log's own N.")
				: localize('soil.sheet.nDerived', "N = N1 + N2, worked out (not stored); type a value only to enter the log's own N.");
		}
		if (this.spec(column)?.target === 'layer') {
			const layer = r ? this.layerAt(r.depth) : undefined;
			return layer
				? localize('soil.sheet.ofStratum', "Of the stratum {0}–{1} m", formatNumber(layer.top / 1000, 2), formatNumber(layer.bottom / 1000, 2))
				: localize('soil.sheet.noStratum', "No stratum at this depth: add one in Strata.");
		}
		if (column.id === 'depthTo' && r && this.depthTo(r).derived && r.spt) {
			return localize('soil.sheet.toDerived', "The end of the SPT drive (from + 0.45 m) unless given.");
		}
		return undefined;
	}

	/** The checks of the sheet: refusal blows, overlapping rows, the limits. */
	private validate(): void {
		this.problems.clear();
		const set = (row: number, column: string, message: string, severity: 'error' | 'warning' = 'error') => {
			if (!this.problems.has(`${row}|${column}`)) {
				this.problems.set(`${row}|${column}`, { message, severity });
			}
		};
		let previousTo: number | undefined;
		this.rows.forEach((r, i) => {
			for (const key of ['seat', 'N1', 'N2'] as const) {
				const blows = r.spt?.[key];
				if (typeof blows === 'number' && blows > REFUSAL_BLOWS) {
					set(i, key, localize('soil.sheet.overRefusal', "{0} blows in one 150 mm increment: the test stops at refusal, {1} blows (ASTM D1586). Enter {1} and mark the refusal.", blows, REFUSAL_BLOWS));
				}
			}
			const to = this.depthTo(r).value;
			if (typeof to === 'number' && to <= r.depth) {
				set(i, 'depthTo', localize('soil.sheet.toAbove', "The bottom must be below the top ({0} m).", formatNumber(r.depth / 1000, 2)));
			}
			if (previousTo !== undefined && r.depth < previousTo - SAME_DEPTH) {
				set(i, 'depth', localize('soil.sheet.overlap', "Overlaps the row above, which goes down to {0} m.", formatNumber(previousTo / 1000, 2)));
			}
			if (typeof to === 'number') {
				previousTo = Math.max(previousTo ?? to, to);
			}
			const ll = r.sample?.liquidLimit;
			const pl = r.sample?.plasticLimit;
			if (typeof ll === 'number' && typeof pl === 'number' && pl > ll) {
				set(i, 'plasticLimit', localize('soil.sheet.plOverLl', "The plastic limit {0}% is above the liquid limit {1}%.", formatNumber(pl), formatNumber(ll)));
			}
			const spt = r.spt;
			if (spt) {
				const derived = deriveN(spt);
				const entered = typeof spt.N === 'number' ? spt.N : undefined;
				const refusal = typeof spt.refusal === 'object' ? spt.refusal : undefined;
				// Red: what the backend rejects (the whole report cannot be read until it is fixed).
				const unreadable = localize('soil.sheet.unreadable', "Until then the report cannot be read: its results, site class and bearing wait for this row.");
				if (entered === undefined && derived === undefined) {
					if (hasIncrements(spt)) {
						set(i, typeof spt.N1 === 'number' ? 'N2' : 'N1', localize('soil.sheet.incomplete', "Give both increments N1 and N2, or mark the refusal. {0}", unreadable));
					} else {
						set(i, 'N1', localize('soil.sheet.noN', "Give the increments N1 and N2 (or N, or the refusal). {0}", unreadable));
					}
				}
				if (refusal && typeof spt.N2 === 'number') {
					set(i, 'N2', localize('soil.sheet.refusalN2', "A refusal stops the drive before the third 150 mm: N2 stays empty."));
				} else if (refusal && typeof spt.N1 === 'number' && (spt.N1 > refusal.blows || refusal.penetration <= 150)) {
					set(i, 'refusal', localize('soil.sheet.refusalN1', "N1 {0} does not fit the refusal {1}/{2} mm: N1 is part of its blows, and needs the first 150 mm of the test drive completed.", spt.N1, refusal.blows, formatNumber(refusal.penetration)));
				} else if (entered !== undefined && spt.refusal !== true && (typeof spt.N1 === 'number') !== (typeof spt.N2 === 'number')) {
					set(i, typeof spt.N1 === 'number' ? 'N2' : 'N1', localize('soil.sheet.oneIncrement', "Only one of the increments N1, N2 is given; the entered N {0} is used.", entered), 'warning');
				}
				if (entered !== undefined && derived !== undefined && entered !== derived) {
					set(i, 'N', refusal
						? localize('soil.sheet.nMismatchRefusal', "N {0} is entered, but the refusal {1}/{2} mm scales to {3} over 300 mm; N {0} is used. Delete it to use {3}.", entered, refusal.blows, formatNumber(refusal.penetration), derived)
						: localize('soil.sheet.nMismatch', "N {0} is entered, but N1 + N2 = {1}; N {0} is used. Delete it to use N1 + N2.", entered, derived), 'warning');
				}
			}
		});
	}

	write(writes: readonly ISheetWrite[]): ISheetWriteResult {
		const borehole = this.borehole;
		const targets = new Map<number, ISampleRow>();
		const created: ISampleRow[] = [];
		const errors: ISheetCellError[] = [];
		let written = 0;
		const ordered = [...writes].sort((a, b) => a.row - b.row);
		// N as worked out before the writes: a stored N equal to it (from an older file or an import)
		// was the worked-out one, and follows the corrected increments; another N was entered.
		const nBefore = new Map(borehole.spt.map(spt => [spt, deriveN(spt)]));
		// The records whose N is written now.
		const nWritten = new Set<ISptRecord>();
		const rowAt = (index: number): ISampleRow => {
			let row = targets.get(index) ?? this.rows[index];
			if (!row) {
				// A new row: below the last, 1.5 m on (the usual SPT spacing) unless its depth is written.
				const last = created[created.length - 1] ?? this.rows[this.rows.length - 1];
				const depthWrite = ordered.find(w => w.row === index && w.column === 'depth');
				const parsed = depthWrite ? parseField(DEPTH_SPEC, depthWrite.text) : undefined;
				const depth = typeof parsed?.value === 'number' ? parsed.value : last ? last.depth + 1500 : 1500;
				row = { depth };
				created.push(row);
			}
			targets.set(index, row);
			return row;
		};
		const sptOf = (row: ISampleRow): ISptRecord => {
			if (!row.spt) {
				row.spt = { depth: row.depth };
				borehole.spt.push(row.spt);
			}
			return row.spt;
		};
		const sampleOf = (row: ISampleRow): ISoilSample => {
			if (!row.sample) {
				row.sample = { depth: row.depth };
				borehole.samples.push(row.sample);
			}
			return row.sample;
		};
		for (const w of ordered) {
			const column = this.columns.find(c => c.id === w.column);
			const entry = SAMPLE_COLUMN_SPECS.find(s => s.spec.key === w.column);
			if (!column || !entry || column.computed) {
				continue;
			}
			const isNew = w.row >= this.rows.length && !targets.has(w.row);
			if (isNew && !w.text.trim()) {
				continue;
			}
			if (!isNew && this.isReadOnly(w.row, column)) {
				errors.push({ row: w.row, column: w.column, message: this.hint(w.row, column) ?? localize('soil.sheet.readOnly', "This cell is worked out.") });
				continue;
			}
			// Refusal: a mark, not a number.
			if (column.id === 'refusal') {
				const word = w.text.trim().toLowerCase();
				const recorded = parseRefusal(word);
				if (word && !recorded && !REFUSAL_WORDS.has(word) && !NO_WORDS.has(word)) {
					errors.push({ row: w.row, column: w.column, message: localize('soil.sheet.refusalValue', "Type R (or yes, x) for refusal, or the blows and penetration as 50/100; leave it empty otherwise.") });
					continue;
				}
				const row = rowAt(w.row);
				if (recorded) {
					sptOf(row).refusal = recorded;
				} else if (REFUSAL_WORDS.has(word)) {
					sptOf(row).refusal = true;
				} else if (row.spt) {
					delete row.spt.refusal;
				}
				written++;
				continue;
			}
			const parsed = parseField(entry.spec, w.text);
			if (parsed.error) {
				errors.push({ row: w.row, column: w.column, message: parsed.error });
				continue;
			}
			const value = parsed.value;
			const row = rowAt(w.row);
			// An SPT row without a lab sample keeps its split spoon's number and recovery itself.
			if ((column.id === 'number' || column.id === 'recovery') && !row.sample && row.spt) {
				setOrDelete(row.spt, column.id === 'number' ? 'sampleNumber' : 'recovery', value);
				written++;
				continue;
			}
			switch (entry.target) {
				case 'row':
					if (column.id === 'depth') {
						row.depth = value as number;
						if (row.spt) {
							row.spt.depth = row.depth;
						}
						if (row.sample) {
							row.sample.depth = row.depth;
						}
					} else if (value === undefined) {
						delete row.sample?.depthTo;
						delete row.spt?.depthTo;
					} else {
						(row.sample ?? row.spt ?? sampleOf(row)).depthTo = value as number;
					}
					break;
				case 'spt':
					if (value === undefined && !row.spt) {
						break;
					}
					setOrDelete(sptOf(row), column.id, value);
					if (column.id === 'N') {
						nWritten.add(sptOf(row));
					}
					break;
				case 'sample':
					if (value === undefined && !row.sample) {
						break;
					}
					setOrDelete(sampleOf(row), column.id, value);
					break;
				case 'layer': {
					if (value === undefined && w.paste) {
						break; // a blank in a pasted block does not clear the stratum of several rows
					}
					const layer = this.layerAt(row.depth);
					if (!layer) {
						errors.push({ row: w.row, column: w.column, message: localize('soil.sheet.noStratum', "No stratum at this depth: add one in Strata.") });
						continue;
					}
					if (column.id === 'description') {
						layer.description = typeof value === 'string' ? value : '';
					} else {
						setOrDelete(layer, column.id, value);
					}
					break;
				}
			}
			written++;
		}
		// A new row with only its depth keeps a sample, so it is not lost.
		for (const row of created) {
			if (!row.spt && !row.sample) {
				sampleOf(row);
			}
		}
		this.tidy([...targets.values()], nBefore, nWritten);
		this.rows = sampleRows(borehole);
		this.validate();
		// The rows are rebuilt in depth order: find each written row again by its records.
		const rows = new Map<number, number>();
		for (const [index, target] of targets) {
			const at = this.rows.findIndex(r => (!!target.spt && r.spt === target.spt) || (!!target.sample && r.sample === target.sample));
			if (at >= 0) {
				rows.set(index, at);
			}
		}
		return { written, added: created.length, errors, rows };
	}

	/**
	 * After writes: no worked-out N stored (an N typed or pasted equal to the worked-out one, or a
	 * stored N equal to the one worked out before, is dropped so that it follows the increments;
	 * an entered N that differs stays), empty records dropped, lists top down.
	 */
	private tidy(rows: readonly ISampleRow[], nBefore: ReadonlyMap<ISptRecord, number | undefined>, nWritten: ReadonlySet<ISptRecord>): void {
		const borehole = this.borehole;
		for (const row of rows) {
			const spt = row.spt;
			if (spt) {
				if (typeof spt.N === 'number') {
					const worked = nWritten.has(spt) ? deriveN(spt) : nBefore.get(spt);
					if (worked !== undefined && spt.N === worked) {
						delete (spt as { N?: number }).N;
					}
				}
				const empty = !hasIncrements(spt) && typeof spt.seat !== 'number' && !spt.refusal && typeof spt.N !== 'number'
					&& spt.sampleNumber === undefined && spt.recovery === undefined;
				if (empty) {
					borehole.spt = borehole.spt.filter(s => s !== spt);
					row.spt = undefined;
				}
			}
			const sample = row.sample;
			if (sample && row.spt && Object.keys(sample).every(key => key === 'depth')) {
				borehole.samples = borehole.samples.filter(s => s !== sample);
				row.sample = undefined;
			}
		}
		borehole.spt.sort((a, b) => a.depth - b.depth);
		borehole.samples.sort((a, b) => a.depth - b.depth);
	}

	removeRows(rows: readonly number[]): void {
		const remove = rows.map(r => this.rows[r]).filter(Boolean);
		const spt = new Set(remove.map(r => r.spt).filter(Boolean));
		const samples = new Set(remove.map(r => r.sample).filter(Boolean));
		this.borehole.spt = this.borehole.spt.filter(s => !spt.has(s));
		this.borehole.samples = this.borehole.samples.filter(s => !samples.has(s));
		this.rows = sampleRows(this.borehole);
		this.validate();
	}
}
