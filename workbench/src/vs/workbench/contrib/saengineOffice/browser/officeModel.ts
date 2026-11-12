/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Alpha 9 L11, the office tools: what the backend answers (`saengine.rpc.office`), the project
 * files they keep, and the pure helpers of their views (the Gantt chart's layout, the project's
 * extents, the phase of an element).
 */

/** The command that forwards an office tools method to the backend: `(method, params)`. */
export const OFFICE_REQUEST_COMMAND = 'saengine.office.request';

export const SCHEDULE_FILE = '10 BOQ/construction-schedule.json';
export const PRODUCTIVITY_FILE = '10 BOQ/productivity.json';
export const TAKEOFF_FILE = '10 BOQ/takeoff.json';
export const TERRAIN_FILE = '01 Soil Report/terrain.json';
export const ENVIRONMENT_FILE = '06 BIM/environment.json';
export const PHASING_FILE = '06 BIM/phasing.json';
export const FABRICATION_FILE = '07 MEP/fabrication.json';

/** The tools of the Office Tools editor, one tab each. */
export type OfficeTool = 'schedule' | 'cost' | 'takeoff' | 'site' | 'fabrication' | 'phasing';
export const OFFICE_TOOLS: readonly OfficeTool[] = ['schedule', 'cost', 'takeoff', 'site', 'fabrication', 'phasing'];

export interface IProblems {
	readonly problems?: readonly string[];
}

// ─────────────────────────────── 4D programme ───────────────────────────────

export interface IScheduleLink {
	readonly from: string;
	readonly type: 'FS' | 'SS';
	readonly lag: number;
	readonly user?: boolean;
}

export interface IScheduleActivity {
	readonly id: string;
	name: string;
	readonly category: string;
	readonly level?: string;
	readonly zone?: string;
	readonly elements: readonly string[];
	readonly quantities?: readonly { readonly rate?: string; readonly description: string; readonly quantity: number; readonly unit: string; readonly days: number }[];
	readonly days: number;
	duration?: number;
	start?: string;
	links: IScheduleLink[];
	renamed?: boolean;
	readonly earlyStart?: string;
	readonly earlyFinish?: string;
	readonly totalFloat?: number;
	readonly critical?: boolean;
}

export interface ISchedule {
	readonly schema: string;
	start: string;
	readonly workDays: readonly string[];
	readonly holidays: readonly string[];
	readonly cycleDays: number;
	activities: IScheduleActivity[];
	readonly finish?: string;
	readonly notes?: readonly string[];
	readonly source?: { readonly [part: string]: string };
}

export type ElementDates = { readonly [element: string]: { readonly start: string; readonly finish: string; readonly activity: string } };

export interface IScheduleAnswer extends IProblems {
	readonly schedule?: ISchedule;
	readonly elementDates?: ElementDates;
	readonly path?: string;
}

/** Days from `a` to `b` (ISO dates). */
export function daysBetween(a: string, b: string): number {
	return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/** `day` (ISO) plus `days`. */
export function addDays(day: string, days: number): string {
	return new Date(Date.parse(`${day}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);
}

export interface IGanttBar {
	readonly activity: IScheduleActivity;
	readonly row: number;
	/** Calendar days from the programme's start to the bar's start, and its length (≥ 1). */
	readonly offset: number;
	readonly length: number;
}

export interface IGanttLayout {
	readonly bars: readonly IGanttBar[];
	readonly totalDays: number;
	/** Week ticks: days from the start, with the date. */
	readonly ticks: readonly { readonly offset: number; readonly label: string }[];
	/** The links to draw: from bar row/end to bar row/start. */
	readonly links: readonly { readonly from: number; readonly to: number; readonly type: 'FS' | 'SS' }[];
}

/** The Gantt chart of a scheduled programme: a row per activity, in calendar days. */
export function ganttLayout(schedule: ISchedule): IGanttLayout {
	const start = schedule.start;
	const rows = new Map<string, number>();
	const bars: IGanttBar[] = [];
	for (const activity of schedule.activities) {
		const from = activity.earlyStart ?? start;
		const to = activity.earlyFinish ?? from;
		const offset = Math.max(daysBetween(start, from), 0);
		const length = Math.max(daysBetween(from, to) + 1, 1);
		rows.set(activity.id, bars.length);
		bars.push({ activity, row: bars.length, offset, length });
	}
	const totalDays = Math.max(1, ...bars.map(b => b.offset + b.length));
	const ticks: { offset: number; label: string }[] = [];
	const step = totalDays > 400 ? 28 : totalDays > 120 ? 14 : 7;
	for (let d = 0; d <= totalDays; d += step) {
		ticks.push({ offset: d, label: addDays(start, d).slice(5) });
	}
	const links: { from: number; to: number; type: 'FS' | 'SS' }[] = [];
	for (const bar of bars) {
		for (const link of bar.activity.links) {
			const from = rows.get(link.from);
			if (from !== undefined) {
				links.push({ from, to: bar.row, type: link.type });
			}
		}
	}
	return { bars, totalDays, ticks, links };
}

/** The element dates of a programme (for the 4D playback), as the backend makes them. */
export function elementDates(schedule: ISchedule): ElementDates {
	const out: { [element: string]: { start: string; finish: string; activity: string } } = {};
	for (const activity of schedule.activities) {
		if (!activity.earlyStart || !activity.earlyFinish) {
			continue;
		}
		for (const element of activity.elements) {
			const known = out[element];
			if (!known || known.start > activity.earlyStart) {
				out[element] = { start: activity.earlyStart, finish: activity.earlyFinish, activity: activity.id };
			}
		}
	}
	return out;
}

// ─────────────────────────────── cost optimisation ───────────────────────────────

export interface ICostOption {
	readonly label: string;
	readonly cost?: number;
	readonly passes?: boolean;
	readonly priced?: boolean;
	readonly reason?: string;
	readonly quantities?: { readonly [name: string]: number };
}

export interface ICostGroup {
	readonly type: string;
	readonly kind: string;
	readonly name?: string;
	readonly members?: readonly string[];
	readonly length?: number;
	readonly current?: ICostOption | null;
	readonly best?: ICostOption | null;
	readonly delta?: number | null;
	readonly status?: 'cheaper' | 'unchanged' | 'noPassingOption';
	readonly evaluated?: number;
	readonly pruned?: number;
	readonly notes?: readonly string[];
	readonly skipped?: string;
}

export interface ICostOptimisation extends IProblems {
	readonly currency?: string;
	readonly rateSchedule?: string;
	readonly groups?: readonly ICostGroup[];
	readonly total?: { readonly current: number; readonly best: number; readonly delta: number };
	readonly notes?: readonly string[];
	readonly limits?: readonly string[];
}

// ─────────────────────────────── PDF takeoff ───────────────────────────────

export type Point2 = [number, number];

export interface ITakeoffSheet {
	readonly id: string;
	file: string;
	page: number;
	name?: string;
	calibration?: { readonly a: Point2; readonly b: Point2; readonly length: number };
	scale?: number;
}

export interface ITakeoffItem {
	readonly id: string;
	sheet: string;
	kind: 'length' | 'area' | 'count';
	points: Point2[];
	description: string;
	group: string;
	height?: number;
	depth?: number;
	multiplier?: number;
	deduct?: boolean;
}

export interface ITakeoff {
	schema: 'saengine.takeoff/1';
	sheets: ITakeoffSheet[];
	items: ITakeoffItem[];
}

export function emptyTakeoff(): ITakeoff {
	return { schema: 'saengine.takeoff/1', sheets: [], items: [] };
}

/** True mm per paper mm of a sheet: its calibration, else its drawing scale. */
export function sheetScale(sheet: ITakeoffSheet): number | undefined {
	if (sheet.calibration) {
		const { a, b, length } = sheet.calibration;
		const paper = Math.hypot(b[0] - a[0], b[1] - a[1]);
		return paper > 0 ? length / paper : undefined;
	}
	return sheet.scale;
}

/** An item's quantity in its bill unit (as `saengine.boq.takeoff.measure`), or undefined. */
export function measureItem(item: ITakeoffItem, sheet: ITakeoffSheet): { readonly quantity: number; readonly unit: string } | undefined {
	const k = sheetScale(sheet);
	if (k === undefined) {
		return undefined;
	}
	let quantity: number;
	let unit: string;
	if (item.kind === 'count') {
		quantity = item.points.length;
		unit = 'nr';
	} else if (item.kind === 'length') {
		let length = 0;
		for (let i = 1; i < item.points.length; i++) {
			length += Math.hypot(item.points[i][0] - item.points[i - 1][0], item.points[i][1] - item.points[i - 1][1]);
		}
		quantity = length * k / 1000;
		unit = 'm';
		if (item.height) {
			quantity *= item.height / 1000;
			unit = 'm2';
		}
	} else {
		let twice = 0;
		const n = item.points.length;
		for (let i = 0; i < n; i++) {
			const [x1, y1] = item.points[i];
			const [x2, y2] = item.points[(i + 1) % n];
			twice += x1 * y2 - x2 * y1;
		}
		quantity = Math.abs(twice) / 2 * k * k / 1e6;
		unit = 'm2';
		if (item.depth) {
			quantity *= item.depth / 1000;
			unit = 'm3';
		}
	}
	quantity *= item.multiplier ?? 1;
	return { quantity: item.deduct ? -quantity : quantity, unit };
}

/** The next free id with `prefix` ("T1", "T2", ...). */
export function nextId(prefix: string, taken: Iterable<string>): string {
	const used = new Set(taken);
	let n = 1;
	while (used.has(`${prefix}${n}`)) {
		n++;
	}
	return `${prefix}${n}`;
}

// ─────────────────────────────── phasing ───────────────────────────────

export type PhaseState = 'existing' | 'new' | 'demolished' | 'temporary';

export interface IPhasing {
	readonly phases: readonly { readonly id: string; readonly name: string }[];
	readonly defaultPhase: string;
	readonly elements: { readonly [element: string]: { readonly created: string; readonly demolished?: string | null } };
	readonly optionSets?: readonly { readonly id: string; readonly name: string; readonly options: readonly { readonly id: string; readonly name: string; readonly version: string; readonly note?: string }[] }[];
}

export const DEFAULT_PHASING: IPhasing = {
	phases: [{ id: 'existing', name: 'Existing' }, { id: 'new', name: 'New construction' }],
	defaultPhase: 'new',
	elements: {},
};

/** The phasing of a `phasing.json` text (the default when empty or not valid). */
export function parsePhasing(text: string | undefined): IPhasing {
	if (!text?.trim()) {
		return DEFAULT_PHASING;
	}
	try {
		const data = JSON.parse(text);
		if (data && Array.isArray(data.phases) && data.phases.length) {
			return { phases: data.phases, defaultPhase: data.defaultPhase ?? 'new', elements: data.elements ?? {}, optionSets: data.optionSets };
		}
	} catch {
		// the default below
	}
	return DEFAULT_PHASING;
}

/**
 * The elements standing in `phase` with their state, as `saengine.project.phasing.visible_in`:
 * built before it and still there (existing), built in it (new), taken down in it (demolished),
 * both (temporary); the others are left out.
 */
export function phaseStates(phasing: IPhasing, elements: Iterable<string>, phase: string): { [element: string]: PhaseState } {
	const order = (id: string) => phasing.phases.findIndex(p => p.id === id);
	const p = order(phase);
	const out: { [element: string]: PhaseState } = {};
	for (const element of elements) {
		const ph = phasing.elements[element] ?? { created: phasing.defaultPhase };
		const created = order(ph.created);
		const demolished = ph.demolished ? order(ph.demolished) : undefined;
		if (created < 0 || created > p || (demolished !== undefined && demolished < p)) {
			continue;
		}
		if (created === p) {
			out[element] = demolished === p ? 'temporary' : 'new';
		} else {
			out[element] = demolished === p ? 'demolished' : 'existing';
		}
	}
	return out;
}

// ─────────────────────────────── the building's extents ───────────────────────────────

/** The building model's extents [mm] (plan points of its elements, its levels): the BIM view's project frame. */
export function bimExtents(bimText: string | undefined): { readonly min: readonly number[]; readonly max: readonly number[] } | undefined {
	if (!bimText) {
		return undefined;
	}
	let data: { stories?: { elevation?: number }[]; elements?: { [key: string]: unknown }[] };
	try {
		data = JSON.parse(bimText);
	} catch {
		return undefined;
	}
	const min = [Infinity, Infinity, Infinity];
	const max = [-Infinity, -Infinity, -Infinity];
	const add = (x: unknown, y: unknown, z?: unknown) => {
		if (typeof x === 'number' && typeof y === 'number') {
			min[0] = Math.min(min[0], x); max[0] = Math.max(max[0], x);
			min[1] = Math.min(min[1], y); max[1] = Math.max(max[1], y);
		}
		if (typeof z === 'number') {
			min[2] = Math.min(min[2], z); max[2] = Math.max(max[2], z);
		}
	};
	for (const story of data.stories ?? []) {
		add(undefined, undefined, story.elevation);
	}
	for (const e of data.elements ?? []) {
		for (const key of ['position', 'start', 'end']) {
			const p = e[key];
			if (Array.isArray(p)) {
				add(p[0], p[1], p[2]);
			}
		}
		for (const key of ['boundary', 'outline']) {
			const ring = e[key];
			if (Array.isArray(ring)) {
				ring.forEach(p => Array.isArray(p) && add(p[0], p[1], p[2]));
			}
		}
		add(undefined, undefined, e.bottom);
		add(undefined, undefined, e.top);
	}
	return Number.isFinite(min[0]) && Number.isFinite(min[2]) ? { min, max } : undefined;
}
