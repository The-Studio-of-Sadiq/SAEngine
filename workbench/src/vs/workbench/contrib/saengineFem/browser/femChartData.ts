/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * What the FEM results' charts, member windows and tables show, worked out from the backend's
 * answers (`saengine.fem.story_response`, `saengine.fem.member_detail`): plain data, no DOM.
 * Values stay in the model's units (SAEngine: m, N, N·m); the views format them.
 */

import { safeIntl } from '../../../../base/common/date.js';
import { localize } from '../../../../nls.js';
import { FemTableCell } from '../../../../platform/saengine/common/femSolver.js';

/** `(model: URI) => IFemStoryResponse`: the storey response and curves of the last run. */
export const FEM_STORY_RESPONSE_COMMAND = 'saengine.fem.storyResponse';
/** `(model: URI, member: string) => IFemMemberForces`. */
export const FEM_MEMBER_FORCES_COMMAND = 'saengine.fem.memberForces';
/** `(model: URI, member?: string) => IFemColumnInteraction`: slow the first time after a run. */
export const FEM_COLUMN_INTERACTION_COMMAND = 'saengine.fem.columnInteraction';
/** `(target: URI, sheets: IFemSheet[]) => { path, sheets }`: an Excel workbook. */
export const FEM_EXPORT_XLSX_COMMAND = 'saengine.fem.exportXlsx';

export type FemAxis2 = 'X' | 'Y';

export interface IFemStoreyRow {
	readonly name: string;
	/** Elevation of the level [m]. */
	readonly z: number;
	/** Height of the storey below the level [m]; null at the base. */
	readonly height: number | null;
	readonly dispX: number | null;
	readonly dispY: number | null;
	readonly avgDispX: number | null;
	readonly avgDispY: number | null;
	/** The storey below the level: largest drift ratio, null at the base. */
	readonly driftX: number | null;
	readonly driftY: number | null;
	/** Force at the level, shear in the storey below it. */
	readonly forceX: number | null;
	readonly forceY: number | null;
	readonly shearX: number | null;
	readonly shearY: number | null;
	/** Overturning moment at the level from the forces above it. */
	readonly overturningX: number | null;
	readonly overturningY: number | null;
}

export interface IFemStoryResult {
	readonly key: string;
	readonly label: string;
	readonly kind: 'static' | 'combination' | 'spectrum' | 'service';
	/** Bottom up, the base first. */
	readonly storeys: readonly IFemStoreyRow[];
	/** Sum over the supports: Fx, Fy, Fz, Mx, My, Mz; null for a response spectrum case. */
	readonly baseReaction: readonly number[] | null;
	/**
	 * A response spectrum case: the factor its storey forces, shears and overturning are scaled
	 * by (the spectrum design's 0.85·V/V_rs, BNBC 2020 Part 6 Sec 2.5.9.4); null when unscaled.
	 */
	readonly forceScale?: number | null;
	/** A service wind combination (kind 'service'): its wind direction and the code pack's storey drift (Δ/h) and top sway (/H) limits. */
	readonly direction?: 'X' | 'Y';
	readonly windDriftLimit?: number | null;
	readonly swayLimit?: number | null;
}

/** A storey of the response spectrum design's drift check (Cd·δ/I with the accidental torsion). */
export interface IFemDesignDrift {
	readonly direction: FemAxis2;
	readonly bottom: number;
	readonly top: number;
	readonly ratio: number;
	readonly allowableRatio: number;
	readonly ok: boolean;
}

/** One suite of time histories of the linear time-history design (B19). */
export interface IFemTimeHistorySuite {
	readonly key: 'X' | 'Y' | 'XY';
	readonly part: string;
	readonly count: number;
	readonly rule: 'max' | 'mean';
	readonly enough: boolean;
	readonly complete: boolean;
	readonly used: boolean;
	readonly cases: readonly { readonly id: number; readonly name: string; readonly baseShear: { readonly x: number; readonly y: number } }[];
	/** The suite's mean spectrum against the code's criterion over its period range. */
	readonly check: { readonly period: number; readonly periods: readonly number[]; readonly mean: readonly number[]; readonly target: readonly number[]; readonly ratio: number; readonly least: number; readonly governing: number; readonly ok: boolean; readonly shortfall: number } | null;
	readonly shortfall?: number;
	readonly vHistory?: { readonly x: number; readonly y: number };
	readonly vStatic?: { readonly x: number; readonly y: number };
	readonly factor?: number;
}

/** The linear time-history design of a run (B19): suites, drifts, notes, clauses. */
export interface IFemTimeHistoryDesign {
	readonly use: boolean;
	readonly suites: readonly IFemTimeHistorySuite[];
	readonly drift: readonly (IFemDesignDrift & { readonly suite: string; readonly height: number; readonly elasticDrift: number; readonly designDrift: number })[];
	readonly notes: readonly string[];
	readonly clauses: { readonly [key: string]: string };
}

export interface IFemModeRow {
	readonly number: number;
	readonly period: number | null;
	readonly frequency: number | null;
	/** Mass participation ratios (0 … 1) and their running sums; null when not known. */
	readonly uX: number | null;
	readonly uY: number | null;
	readonly sumUX: number | null;
	readonly sumUY: number | null;
}

/**
 * The target displacement of a pushover by the code pack's method (`fem/pushover_target.py`):
 * lengths in m, forces in N, periods in s, Sa in g.
 */
export interface IFemPushoverTarget {
	readonly available: boolean;
	readonly reason?: string;
	readonly method?: string;
	readonly T1?: number;
	readonly Te?: number;
	readonly Vy?: number;
	readonly dy?: number;
	readonly Sa?: number;
	readonly C0?: number;
	readonly C1?: number;
	readonly Rd?: number;
	readonly W?: number;
	readonly target?: number;
	readonly bilinear?: readonly (readonly number[])[];
	readonly pushedTo?: number;
	readonly required?: number;
	readonly reached?: boolean;
	readonly noDropTo?: number;
	readonly noDrop?: boolean | null;
	readonly targetStep?: number | null;
	readonly ok?: boolean;
	readonly clauses?: { readonly [key: string]: string };
	readonly note?: string;
	readonly notes?: readonly string[];
}

/** One member's governing fibre at the target displacement (`fem/acceptance.py`). */
export interface IFemAcceptanceRow {
	readonly member: string;
	readonly element: number;
	readonly end: 'i' | 'j';
	readonly fibre: 'concrete' | 'bar' | 'steel';
	readonly strain: number;
	readonly limit: number;
	readonly ratio: number;
	readonly gravity: boolean;
	readonly ok: boolean;
}

export interface IFemPushoverAcceptance {
	readonly available: boolean;
	readonly reason?: string;
	readonly step?: number;
	readonly rows?: readonly IFemAcceptanceRow[];
	readonly failed?: number;
	readonly ok?: boolean;
	readonly share?: number;
	readonly residual?: number;
	readonly clause?: string;
	readonly note?: string;
	readonly notes?: readonly string[];
}

export interface IFemPushoverCurve {
	readonly key: string;
	readonly label: string;
	readonly displacement: readonly number[];
	readonly shear: readonly number[];
	readonly target?: IFemPushoverTarget;
	readonly acceptance?: IFemPushoverAcceptance;
}

export interface IFemStoryResponse {
	readonly levels: readonly { readonly z: number; readonly name: string }[];
	readonly results: readonly IFemStoryResult[];
	readonly modal: { readonly case: string; readonly modes: readonly IFemModeRow[]; readonly required: number } | null;
	readonly spectrum: { readonly name: string; readonly periods: readonly number[]; readonly accelerations: readonly number[]; readonly damping: number | null } | null;
	readonly driftLimit: { readonly ratio: number; readonly cd: number | null; readonly importance: number | null; readonly clause: string } | null;
	/** The response spectrum design of this run, when it has been worked out. */
	readonly spectrumDesign?: { readonly scale: { readonly X: number; readonly Y: number }; readonly drift: readonly IFemDesignDrift[]; readonly clause: string; readonly timeHistory?: IFemTimeHistoryDesign | null } | null;
	readonly pushover: readonly IFemPushoverCurve[];
	readonly histories: readonly { readonly key: string; readonly label: string; readonly node: number; readonly time: readonly number[]; readonly displacement: readonly (readonly number[])[] }[];
	readonly notes: readonly string[];
}

export interface IFemMemberResult {
	readonly key: string;
	readonly label: string;
	readonly kind: 'static' | 'combination';
	/** N, Vy, Vz, T, My, Mz at each station (member axes, tension positive). */
	readonly forces: readonly (readonly number[])[];
	/** Local u1, u2, u3 relative to the chord between the ends. */
	readonly deflection: readonly (readonly number[])[];
}

export interface IFemMemberForces {
	readonly member: string;
	readonly kind: 'column' | 'beam' | 'brace';
	readonly length: number;
	readonly elements: readonly string[];
	/** The section's name (the object type's), when the model names it. */
	readonly section?: string | null;
	/** Distance of each station from the member's start [m]. */
	readonly stations: readonly number[];
	readonly results: readonly IFemMemberResult[];
	readonly notes: readonly string[];
}

export interface IFemColumnDiagram {
	readonly type: string;
	readonly assumedBars: boolean;
	readonly phiPnMax: number;
	readonly phiTension: number;
	/** [P kN, φMn kN·m] from tension to φPn,max, about the section's x and y axes. */
	readonly curves: { readonly x: readonly (readonly number[])[]; readonly y: readonly (readonly number[])[] };
	/** The φMnx-φMny contour [kN·m] at the governing axial force. */
	readonly contour: readonly (readonly number[])[] | null;
	readonly governing: { readonly utilisation: number; readonly P: number; readonly combination: string; readonly where: string } | null;
	readonly points: readonly { readonly combination: string; readonly where: string; readonly P: number; readonly Mx: number; readonly My: number }[];
}

export interface IFemColumnInteraction {
	readonly columns: { readonly [member: string]: IFemColumnDiagram };
	readonly notes: readonly string[];
}

/** A table as the tables panel shows it and the export writes it. */
export interface IFemSheet {
	readonly name: string;
	readonly columns: readonly string[];
	readonly rows: readonly (readonly FemTableCell[])[];
	readonly notes?: readonly string[];
}

/**
 * A table cell as the views show it: numbers to four significant digits (whole numbers as they
 * are). The CSV and Excel exports keep full precision ({@link exportCell}).
 */
export function formatCell(value: FemTableCell): string {
	if (typeof value === 'number') {
		// No exponents and no "-0": what is below a millionth of the unit shown is zero.
		return Number.isInteger(value) ? String(value) : Math.abs(value) < 1e-6 ? '0' : Number(value.toPrecision(4)).toString();
	}
	return value;
}

/**
 * The decimals of a table column: four significant digits of its largest value (at most six
 * decimals), so every row of the column reads alike; undefined for a column of whole numbers.
 */
export function columnDecimals(rows: readonly (readonly FemTableCell[])[], column: number): number | undefined {
	let largest = 0;
	let fractional = false;
	for (const row of rows) {
		const value = row[column];
		if (typeof value === 'number' && Number.isFinite(value)) {
			largest = Math.max(largest, Math.abs(value));
			fractional ||= !Number.isInteger(value);
		}
	}
	if (!fractional) {
		return undefined;
	}
	return largest > 0 ? Math.min(6, Math.max(0, 3 - Math.floor(Math.log10(largest)))) : 3;
}

/** A table cell with `decimals` decimals (no "-0"), or as {@link formatCell} without them. */
export function formatFixedCell(value: FemTableCell, decimals: number | undefined): string {
	if (typeof value !== 'number' || decimals === undefined) {
		return formatCell(value);
	}
	const text = value.toFixed(decimals);
	return Number(text) === 0 ? (0).toFixed(decimals) : text;
}

/** A number as the exports keep it: six significant digits (no float noise), no "-0". */
export function exportNumber(value: number): number {
	const rounded = Number.isInteger(value) ? value : Math.abs(value) < 1e-9 ? 0 : Number(value.toPrecision(6));
	return rounded === 0 ? 0 : rounded;
}

/** A table cell as the CSV export writes it ({@link exportNumber}). */
export function exportCell(value: FemTableCell): string {
	return typeof value === 'number' ? String(exportNumber(value)) : value;
}

// ───────────────────────────── table units ─────────────────────────────

/** The SI units of the result tables and the units the views and exports show them in. */
const DISPLAY_UNITS: { readonly [unit: string]: { readonly unit: string; readonly scale: number } } = {
	'm': { unit: 'mm', scale: 1e3 },
	'N': { unit: 'kN', scale: 1e-3 },
	'N·m': { unit: 'kN·m', scale: 1e-3 },
	'N/m': { unit: 'kN/m', scale: 1e-3 },
	'N·m/m': { unit: 'kN·m/m', scale: 1e-3 },
	'Pa': { unit: 'MPa', scale: 1e-6 },
};

/** The global axes of the solver's numbered directions (U1 = Ux, M3 = Mz). */
const AXIS_NAMES: { readonly [digit: string]: string } = { '1': 'x', '2': 'y', '3': 'z' };

/** The SI unit of a quantity named in a column or cell of a table giving its units in the title. */
function quantityUnit(name: string): string | undefined {
	if (/^(F[xyz]|N|V[yz23]?)$/.test(name)) {
		return 'N';
	}
	if (/^(M[xyz23]|T)$/.test(name)) {
		return 'N·m';
	}
	return /^U[xyz]$/.test(name) ? 'm' : undefined;
}

export interface IFemTableLike {
	readonly name: string;
	readonly title: string;
	readonly columns: readonly string[];
	readonly rows: readonly (readonly FemTableCell[])[];
	readonly notes: readonly string[];
}

/**
 * A result table as the engineer reads it: lengths in mm, forces in kN, moments in kN·m,
 * stresses in MPa (the solver writes N, m, Pa), and the solver's numbered axes named (U1 -> Ux,
 * F3 -> Fz) so the cases' and the combinations' tables have the same columns. Tables of other
 * unit systems are returned as they are.
 */
export function displayTable<T extends IFemTableLike>(table: T, units: string | undefined): T {
	if (!units?.startsWith('SI')) {
		return table;
	}
	const titleUnits = /\((N|m), /.test(table.title);
	// Member forces are in the member's local axes: V2, V3, M2, M3 as the 3D view names them.
	const local = /element|envelope/i.test(table.name);
	const localName = (name: string) => local ? name.replace(/^([VM])([yz])\b/, (_, q: string, a: string) => q + (a === 'y' ? '2' : '3')) : name;
	const scales: (number | undefined)[] = [];
	const columns = table.columns.map((column, k) => {
		const named = localName(column.replace(/^([UFMR])([123])\b/, (_, q: string, d: string) => q + AXIS_NAMES[d]));
		const bracket = /^(.*)\[([^\]]+)\]$/.exec(named);
		const unit = bracket ? DISPLAY_UNITS[bracket[2]] : titleUnits ? DISPLAY_UNITS[quantityUnit(named.replace(/ (min|max)$/, '')) ?? ''] : undefined;
		scales[k] = unit?.scale;
		if (!unit) {
			return !bracket && titleUnits && /^R[xyz]( min| max)?$/.test(named) ? `${named} [rad]` : named;
		}
		return bracket ? `${bracket[1]}[${unit.unit}]` : `${named} [${unit.unit}]`;
	});
	// Long tables: a unit (or a force's name) per row, its value(s) in other columns.
	const unitColumn = table.columns.indexOf('Unit');
	const nameColumn = local ? table.columns.findIndex(c => c === 'Force' || c === 'Component') : -1;
	const forceColumn = titleUnits ? table.columns.indexOf('Force') : -1;
	const valueColumns = table.columns.map((c, k) => /^(Value|Min|Max)$/.test(c) ? k : -1).filter(k => k >= 0);
	const rows = table.rows.map(row => {
		const perRow = unitColumn >= 0 ? DISPLAY_UNITS[String(row[unitColumn])] : forceColumn >= 0 ? DISPLAY_UNITS[quantityUnit(String(row[forceColumn])) ?? ''] : undefined;
		return row.map((cell, k) => {
			if (k === unitColumn && perRow) {
				return perRow.unit;
			}
			if (k === nameColumn && typeof cell === 'string') {
				return localName(cell);
			}
			const scale = perRow && valueColumns.includes(k) ? perRow.scale : scales[k];
			return typeof cell === 'number' && scale !== undefined ? cell * scale : cell;
		});
	});
	const title = table.title.replace(/\(N, N·m\)/, '(kN, kN·m)').replace(/\(m, rad\)/, '(mm, rad)');
	return { ...table, title, columns, rows };
}

/**
 * A reactions table with the supports only (the rigid diaphragms' constraint forces at their
 * master nodes are no reactions) and a Total row (the sum of each column).
 */
export function supportReactions<T extends IFemTableLike>(table: T, supports: ReadonlySet<number>): T {
	if (!/reaction/i.test(table.name) || table.columns[0] !== 'Node') {
		return table;
	}
	const own = table.rows.filter(r => typeof r[0] === 'number' && supports.has(r[0]));
	const rows: (readonly FemTableCell[])[] = [...own];
	if (own.length) {
		const total: FemTableCell[] = [localize('femTable.total', "Total")];
		for (let k = 1; k < table.columns.length; k++) {
			total.push(own.reduce<number>((sum, r) => sum + (typeof r[k] === 'number' ? r[k] as number : 0), 0));
		}
		rows.push(total);
	}
	return { ...table, rows };
}

// ───────────────────────────── storey response ─────────────────────────────

export type StoreyQuantity = 'disp' | 'drift' | 'force' | 'shear' | 'overturning';

export const STOREY_QUANTITIES: readonly StoreyQuantity[] = ['disp', 'drift', 'shear', 'force', 'overturning'];

export function storeyQuantityLabel(quantity: StoreyQuantity): string {
	switch (quantity) {
		case 'disp': return localize('femChart.disp', "Storey Displacement");
		case 'drift': return localize('femChart.drift', "Inter-Storey Drift Ratio");
		case 'force': return localize('femChart.force', "Storey Forces");
		case 'shear': return localize('femChart.shear', "Storey Shear");
		case 'overturning': return localize('femChart.overturning', "Overturning Moment");
	}
}

/** A point of a storey profile: the value and the elevation [m] it is drawn at. */
export interface IProfilePoint {
	readonly value: number;
	readonly z: number;
	readonly level: string;
}

function rowValue(row: IFemStoreyRow, quantity: StoreyQuantity, axis: FemAxis2): number | null {
	switch (quantity) {
		case 'disp': return axis === 'X' ? row.dispX : row.dispY;
		case 'drift': return axis === 'X' ? row.driftX : row.driftY;
		case 'force': return axis === 'X' ? row.forceX : row.forceY;
		case 'shear': return axis === 'X' ? row.shearX : row.shearY;
		case 'overturning': return axis === 'X' ? row.overturningX : row.overturningY;
	}
}

/**
 * The profile of `quantity` up the building, as ETABS draws its story response plots: values at
 * the levels (displacements, forces, overturning), or constant over each storey (shear, drift:
 * a vertical segment from the storey's bottom to its top level).
 */
export function storeyProfile(result: IFemStoryResult, quantity: StoreyQuantity, axis: FemAxis2): IProfilePoint[] {
	const rows = result.storeys;
	const points: IProfilePoint[] = [];
	const perStorey = quantity === 'shear' || quantity === 'drift';
	rows.forEach((row, k) => {
		const value = rowValue(row, quantity, axis);
		if (value === null) {
			return;
		}
		if (perStorey && k > 0) {
			points.push({ value, z: rows[k - 1].z, level: row.name }, { value, z: row.z, level: row.name });
		} else if (!perStorey) {
			points.push({ value, z: row.z, level: row.name });
		}
	});
	return points;
}

/**
 * The largest magnitude of a profile and where it is (undefined for an empty profile). Of a
 * storey value (drawn from the storey's bottom to its top) the top: the level it is reported at.
 */
export function profilePeak(points: readonly IProfilePoint[]): IProfilePoint | undefined {
	let best: IProfilePoint | undefined;
	for (const p of points) {
		if (!best || Math.abs(p.value) > Math.abs(best.value) || (Math.abs(p.value) === Math.abs(best.value) && p.level === best.level)) {
			best = p;
		}
	}
	return best;
}

/**
 * The drift ratio the analysis may reach: BNBC 2020's allowable design drift Δa/hsx divided by
 * Cd/I (the design drift is Cd·δ/I, Part 6 Sec 2.5.7.1). Undefined without the limit.
 */
export function elasticDriftLimit(limit: IFemStoryResponse['driftLimit']): number | undefined {
	if (!limit) {
		return undefined;
	}
	const amplification = limit.cd && limit.importance ? limit.cd / limit.importance : 1;
	return limit.ratio / amplification;
}

/** Whether a result has lateral storey forces or shears (an empty 1.4D plot has none). */
export function isLateralResult(result: IFemStoryResult): boolean {
	return result.storeys.some(s => [s.shearX, s.shearY, s.forceX, s.forceY].some(v => v !== null && Math.abs(v) > 1e-9));
}

/**
 * The result the charts open at: a lateral one, since gravity has no storey response to plot.
 * The response spectrum case first (what the design uses), then an earthquake or wind case,
 * then any result with lateral forces, else the first.
 */
export function defaultChartResult(results: readonly IFemStoryResult[]): IFemStoryResult | undefined {
	return results.find(r => r.kind === 'spectrum')
		?? results.find(r => r.kind === 'static' && isLateralResult(r) && /^(EX|EY|E|WX|WY|W)\b/.test(r.label))
		?? results.find(isLateralResult)
		?? results[0];
}

/**
 * `results` in the order of the 3D view's result list (`keys`), so both pickers list the
 * results alike; results the list lacks keep their order after the others.
 */
export function orderLike<T extends { readonly key: string }>(results: readonly T[], keys: readonly string[]): T[] {
	const rank = new Map(keys.map((k, i) => [k, i]));
	return results
		.map((r, i) => ({ r, i, k: rank.get(r.key) ?? keys.length + i }))
		.sort((a, b) => a.k - b.k)
		.map(e => e.r);
}

/** Whether a result is an earthquake load (a static E case, an RS case, or a combination with one). */
export function isEarthquakeResult(label: string): boolean {
	return /(^|[^A-Za-z])(E|EX|EY|RX|RY|Eh|Ev)([^A-Za-z]|$)/.test(label);
}

// ───────────────────────────── modal ─────────────────────────────

/** The first mode whose cumulative participation reaches `required` in an axis, or undefined. */
export function modesToReach(modes: readonly IFemModeRow[], axis: FemAxis2, required: number): number | undefined {
	return modes.find(m => (axis === 'X' ? m.sumUX : m.sumUY) !== null && (axis === 'X' ? m.sumUX! : m.sumUY!) >= required - 1e-9)?.number;
}

/** "Mode 2: T = 0.121 s, UX 3.3 %, UY 0.0 %": the caption of a mode shape. */
export function describeMode(mode: IFemModeRow | undefined, number: number): string {
	if (!mode || mode.period === null) {
		return localize('femChart.modeOnly', "Mode {0}", number);
	}
	const pct = (v: number | null) => v === null ? '–' : (100 * v).toFixed(1);
	return mode.uX === null && mode.uY === null
		? localize('femChart.modePeriod', "Mode {0}: T = {1} s", number, mode.period.toFixed(3))
		: localize('femChart.modeCaption', "Mode {0}: T = {1} s, UX {2} %, UY {3} %", number, mode.period.toFixed(3), pct(mode.uX), pct(mode.uY));
}

/** The modal periods on the design spectrum: [T, Sa(T)] by linear interpolation, clamped. */
export function spectrumAt(spectrum: NonNullable<IFemStoryResponse['spectrum']>, period: number): number {
	const p = spectrum.periods;
	const a = spectrum.accelerations;
	if (!p.length) {
		return 0;
	}
	if (period <= p[0]) {
		return a[0];
	}
	for (let k = 1; k < p.length; k++) {
		if (period <= p[k]) {
			const t = (period - p[k - 1]) / (p[k] - p[k - 1]);
			return a[k - 1] + t * (a[k] - a[k - 1]);
		}
	}
	return a[a.length - 1];
}

// ───────────────────────────── members ─────────────────────────────

export const MEMBER_COMPONENTS = ['N', 'Vy', 'Vz', 'T', 'My', 'Mz'] as const;
export type MemberComponent = typeof MEMBER_COMPONENTS[number];

/** The value at each station of one force component (or deflection u2/u3) of a result. */
export function memberValues(result: IFemMemberResult, component: MemberComponent | 'u2' | 'u3'): number[] {
	if (component === 'u2' || component === 'u3') {
		const index = component === 'u2' ? 1 : 2;
		return result.deflection.map(d => d[index]);
	}
	const index = MEMBER_COMPONENTS.indexOf(component);
	return result.forces.map(f => f[index]);
}

/** Per station the largest and least value over the combinations (the envelope). */
export function memberEnvelope(detail: IFemMemberForces, component: MemberComponent | 'u2' | 'u3'): { readonly max: number[]; readonly min: number[]; readonly maxBy: string[]; readonly minBy: string[] } {
	const combos = detail.results.filter(r => r.kind === 'combination');
	const used = combos.length ? combos : detail.results;
	const max = detail.stations.map(() => -Infinity);
	const min = detail.stations.map(() => Infinity);
	const maxBy = detail.stations.map(() => '');
	const minBy = detail.stations.map(() => '');
	for (const result of used) {
		memberValues(result, component).forEach((v, k) => {
			if (v > max[k]) {
				max[k] = v;
				maxBy[k] = result.label;
			}
			if (v < min[k]) {
				min[k] = v;
				minBy[k] = result.label;
			}
		});
	}
	return { max, min, maxBy, minBy };
}

/** The largest and the least value of a diagram and where they are [m from the start]. */
export function extremes(stations: readonly number[], values: readonly number[]): { readonly max: { readonly value: number; readonly at: number }; readonly min: { readonly value: number; readonly at: number } } | undefined {
	if (!values.length) {
		return undefined;
	}
	let hi = 0;
	let lo = 0;
	values.forEach((v, k) => {
		if (v > values[hi]) {
			hi = k;
		}
		if (v < values[lo]) {
			lo = k;
		}
	});
	return { max: { value: values[hi], at: stations[hi] }, min: { value: values[lo], at: stations[lo] } };
}

/**
 * A P-M curve closed into the diagram engineers draw: from pure tension along the computed
 * capacities up to φPn,max, then the cap to the P axis.
 */
export function closedPmCurve(diagram: IFemColumnDiagram, axis: 'x' | 'y'): number[][] {
	const curve = diagram.curves[axis].map(p => [p[1], p[0]]); // [M, P]
	if (!curve.length) {
		return [];
	}
	return [[0, curve[0][1]], ...curve, [0, diagram.phiPnMax]];
}

// ───────────────────────────── tables ─────────────────────────────

/** The storey response of every result as one table (SI as the model; kN, mm in the views). */
export function storeyTable(response: IFemStoryResponse, format: { length(v: number): number; force(v: number): number; moment(v: number): number }): IFemSheet {
	const columns = [
		localize('femTable.result', "Result"), localize('femTable.level', "Level"), localize('femTable.elevation', "Elevation [m]"),
		localize('femTable.dispX', "Ux max [mm]"), localize('femTable.dispY', "Uy max [mm]"),
		localize('femTable.driftX', "Drift X"), localize('femTable.driftY', "Drift Y"),
		localize('femTable.shearX', "Shear X [kN]"), localize('femTable.shearY', "Shear Y [kN]"),
		localize('femTable.forceX', "Force X [kN]"), localize('femTable.forceY', "Force Y [kN]"),
		localize('femTable.otmX', "Overturning (X forces) [kN·m]"), localize('femTable.otmY', "Overturning (Y forces) [kN·m]"),
	];
	const rows: FemTableCell[][] = [];
	const cell = (v: number | null, f: (v: number) => number): FemTableCell => v === null ? '' : f(v);
	const same = (v: number) => v;
	for (const result of response.results) {
		for (const row of [...result.storeys].reverse()) {
			rows.push([
				result.label, row.name, row.z,
				cell(row.dispX, format.length), cell(row.dispY, format.length),
				cell(row.driftX, same), cell(row.driftY, same),
				cell(row.shearX, format.force), cell(row.shearY, format.force),
				cell(row.forceX, format.force), cell(row.forceY, format.force),
				cell(row.overturningX, format.moment), cell(row.overturningY, format.moment),
			]);
		}
	}
	return { name: localize('femTable.storeys', "Storey response"), columns, rows, notes: response.notes };
}

/** The modal periods and mass participation (in %) as a table. */
export function modalTable(modal: NonNullable<IFemStoryResponse['modal']>): IFemSheet {
	const pct = (v: number | null): FemTableCell => v === null ? '' : 100 * v;
	return {
		name: localize('femTable.modal', "Modal participation"),
		columns: [
			localize('femTable.mode', "Mode"), localize('femTable.period', "Period [s]"), localize('femTable.frequency', "Frequency [Hz]"),
			localize('femTable.ux', "UX [%]"), localize('femTable.uy', "UY [%]"), localize('femTable.sumUx', "Sum UX [%]"), localize('femTable.sumUy', "Sum UY [%]"),
		],
		rows: modal.modes.map(m => [m.number, m.period ?? '', m.frequency ?? '', pct(m.uX), pct(m.uY), pct(m.sumUX), pct(m.sumUY)]),
		notes: [localize('femTable.modalNote', "BNBC 2020 Part 6 Sec 2.5.9.2: the modes included must reach {0} % of the mass in each direction.", Math.round(100 * modal.required))],
	};
}

/** The base reactions of the static cases and combinations. */
export function baseReactionTable(response: IFemStoryResponse, format: { force(v: number): number; moment(v: number): number }): IFemSheet {
	return {
		name: localize('femTable.base', "Base reactions"),
		columns: [
			localize('femTable.result', "Result"),
			'Fx [kN]', 'Fy [kN]', 'Fz [kN]', 'Mx [kN·m]', 'My [kN·m]', 'Mz [kN·m]',
		],
		rows: response.results.filter(r => r.baseReaction).map(r => [
			r.label,
			...r.baseReaction!.slice(0, 3).map(format.force),
			...r.baseReaction!.slice(3, 6).map(format.moment),
		]),
	};
}

// ───────────────────────────── sorting and filtering ─────────────────────────────

/** Rows sorted by a column (numbers numerically, text naturally), stable. */
export function sortRows<T extends readonly FemTableCell[]>(rows: readonly T[], column: number, descending: boolean): T[] {
	const collator = safeIntl.Collator(undefined, { numeric: true, sensitivity: 'base' }).value;
	return rows
		.map((row, index) => ({ row, index }))
		.sort((a, b) => {
			const x = a.row[column];
			const y = b.row[column];
			// Numbers, then text, then blank cells, whichever way the column is sorted.
			const rank = (v: FemTableCell | undefined) => typeof v === 'number' ? 0 : v === undefined || v === '' ? 2 : 1;
			const ranks = rank(x) - rank(y);
			if (ranks) {
				return ranks;
			}
			const order = typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(String(x ?? ''), String(y ?? ''));
			return (descending ? -order : order) || a.index - b.index;
		})
		.map(e => e.row);
}

/**
 * Rows matching a filter: every word of it must appear in some cell of the row (case
 * insensitive), so "C3 1.4D" finds member C3's rows under 1.4D.
 */
export function filterRows<T extends readonly FemTableCell[]>(rows: readonly T[], filter: string, format: (cell: FemTableCell) => string = String): T[] {
	const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) {
		return [...rows];
	}
	return rows.filter(row => {
		const cells = row.map(c => format(c).toLowerCase());
		return words.every(w => cells.some(c => c.includes(w)));
	});
}

/**
 * The tables of every case and combination as workbook sheets: one sheet per kind of table
 * (displacements, reactions, element forces, ...) with the result in a first column, so Excel's
 * filters find a member under every combination; then the summary tables.
 */
export function workbookSheets(cases: readonly { readonly caseName: string; readonly resultType?: string; readonly tables: readonly IFemTableLike[] }[], summary: readonly IFemSheet[] = []): IFemSheet[] {
	const sheets = new Map<string, { name: string; kinds: Set<string>; columns: string[]; rows: FemTableCell[][]; notes: Set<string> }>();
	for (const c of cases) {
		for (const table of c.tables) {
			const key = `${table.name}|${table.columns.join('|')}`;
			let sheet = sheets.get(key);
			if (!sheet) {
				sheet = { name: table.name || table.title, kinds: new Set(), columns: [localize('femTable.result', "Result"), ...table.columns], rows: [], notes: new Set() };
				sheets.set(key, sheet);
			}
			sheet.kinds.add(c.resultType === 'Combination' ? localize('femTable.ofCombinations', "combinations")
				: c.resultType === 'Envelope' ? localize('femTable.ofEnvelopes', "envelopes") : localize('femTable.ofCases', "cases"));
			for (const row of table.rows) {
				sheet.rows.push([c.caseName, ...row]);
			}
			table.notes.forEach(n => sheet!.notes.add(n));
		}
	}
	// Tables of one name with different columns (the cases' and the combinations' element
	// forces) are told apart by what they hold rather than numbered.
	const all = [...sheets.values()];
	const named = (s: typeof all[number]) => all.filter(o => o.name === s.name).length > 1 ? `${s.name} (${[...s.kinds].join(', ')})` : s.name;
	const rounded = (rows: readonly (readonly FemTableCell[])[]) => rows.map(r => r.map(c => typeof c === 'number' ? exportNumber(c) : c));
	return [
		...summary.map(s => ({ ...s, rows: rounded(s.rows) })),
		...all.map(s => ({ name: named(s), columns: s.columns, rows: rounded(s.rows), notes: [...s.notes] })),
	];
}
