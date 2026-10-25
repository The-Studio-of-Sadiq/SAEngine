/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { idError, IMep, IMepContext, IMepProblem, nextId, Point, storyExtent } from './mepDocument.js';
import {
	CheckStatus, duplicates, IMepCheck, isPoint, isRecord, mergeProposals, num, optionalNumber, optionalString, readCheck, record, recordList, records, storyBetween, strings, worst,
} from './mepRead.js';
import { IOpeningResult, readOpeningResults } from './hvacDocument.js';
import { allIds, ITank, tankOutline } from './plumbingDocument.js';

/*
 * The fire protection section of the MEP part (`fire` in `07 MEP/mep.json`), as the structural
 * engineer coordinates it (BNBC 2020 Part 4): each storey's use, which decides the systems the
 * building needs; the standpipe and sprinkler risers and the fire mains (their sleeves through
 * the slabs and beams); the fire pumps (their weight, vibrating) and their room; the fire tanks
 * (designed as the plumbing tanks; an overhead one loads the floor). The backend decides, sizes
 * and checks them (`saengine.fire.*`); this module reads and writes the section, checks it
 * against the building, and reads the backend's answers defensively. It holds no UI.
 */

/** The report: requirements, sprinklers, hydraulics, water, pumps, tank designs, sleeves: `{ projectRoot, mepText }`. */
export const FIRE_REPORT_COMMAND = 'saengine.fire.report';
/** The fire tanks and pumps the backend proposes: `{ projectRoot, mepText }` → `{ tanks, pumps, notes }`. */
export const FIRE_PROPOSE_COMMAND = 'saengine.fire.proposals';
/** The sleeves the risers and mains need through slabs and beams: `{ projectRoot, mepText }` → `{ openings, notes }`. */
export const FIRE_OPENINGS_COMMAND = 'saengine.fire.openings';

export type FireRiserSystem = 'standpipe' | 'sprinkler' | 'combined';
export const FIRE_RISER_SYSTEMS: readonly FireRiserSystem[] = ['standpipe', 'sprinkler', 'combined'];

export type FirePumpDuty = 'main' | 'standby' | 'jockey';
export const FIRE_PUMP_DUTIES: readonly FirePumpDuty[] = ['main', 'standby', 'jockey'];

export type FireHazard = 'lightI' | 'lightII' | 'ordinaryI' | 'ordinaryII' | 'ordinaryIII' | 'extra';
export const FIRE_HAZARDS: readonly FireHazard[] = ['lightI', 'lightII', 'ordinaryI', 'ordinaryII', 'ordinaryIII', 'extra'];

export type FireSystem = 'extinguishers' | 'manualAlarm' | 'automaticAlarm' | 'hydrant' | 'sprinklers' | 'special';
export type FireStatus = 'required' | 'performance' | 'recommended' | 'notRequired';

export const HOSES = ['small', 'large', 'firstAid'] as const;
export const PIPE_MATERIALS = ['steel', 'GI', 'copper'] as const;
export const STORAGES = ['dedicated', 'plumbingReserve'] as const;
export const PUMP_TYPES = ['endSuction', 'splitCase', 'verticalTurbine'] as const;
export const STANDBYS = ['diesel', 'electric'] as const;
export const CONSTRUCTIONS = ['typeIA', 'modifiedIA', 'other'] as const;
export const CORRIDORS = ['central', 'singleOpen'] as const;
export const CEILINGS = ['beams', 'openJoists', 'other'] as const;

export interface IFireBuilding {
	construction?: string;
	corridor?: string;
	dwellingUnits?: number;
	occupantLoad?: number;
	falseCeiling?: number;
	[key: string]: unknown;
}

export interface IFireSupply {
	hose?: string;
	material?: string;
	storage?: string;
	pumpType?: string;
	standby?: string;
	fireEngineOnCover?: boolean;
	fireEngineWeight?: number;
	[key: string]: unknown;
}

export interface IFireStory {
	story: string;
	occupancy?: string;
	/** Gross floor area [m²]; else the story's slabs. */
	area?: number;
	/** Largest single effective undivided space [m²]; else the floor area. */
	undivided?: number;
	hazard?: FireHazard | string;
	/** Sprinklers on this story; undefined: where Part 4 requires them. */
	sprinklered?: boolean;
	ceiling?: string;
	[key: string]: unknown;
}

export interface IFireRiser {
	id: string;
	system: FireRiserSystem | string;
	x: number;
	y: number;
	fromStory: string;
	toStory: string;
	shaft?: string;
	/** Nominal [mm]; else sized. */
	diameter?: number;
	[key: string]: unknown;
}

export interface IFireMain {
	id: string;
	story: string;
	path: Point[];
	diameter?: number;
	bottom?: number;
	[key: string]: unknown;
}

export interface IFirePump {
	id: string;
	duty: FirePumpDuty | string;
	story: string;
	x: number;
	y: number;
	length?: number;
	width?: number;
	height?: number;
	/** Rated flow [l/min]. */
	flow?: number;
	/** Rated head [m]. */
	head?: number;
	/** [kW] */
	power?: number;
	operatingWeight?: number;
	sized?: boolean;
	equipment?: string;
	[key: string]: unknown;
}

export interface IFirePumpRoom {
	story: string;
	outline: Point[];
	[key: string]: unknown;
}

export interface IFire {
	building: IFireBuilding;
	supply: IFireSupply;
	/** A hydrant system; undefined: where Part 4 requires one. */
	hydrant?: boolean;
	/** Automatic detection; undefined: where Part 4 requires it. */
	detection?: boolean;
	stories: IFireStory[];
	risers: IFireRiser[];
	mains: IFireMain[];
	tanks: ITank[];
	pumps: IFirePump[];
	pumpRoom?: IFirePumpRoom;
	[key: string]: unknown;
}

/** Fills in what a fire section lacks, in place, keeping unknown fields; undefined when it is not an object. */
export function normalizeFire(value: unknown): IFire | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const fire = value as IFire;
	fire.building = isRecord(fire.building) ? fire.building : {};
	fire.supply = isRecord(fire.supply) ? fire.supply : {};
	fire.stories = recordList<IFireStory>(fire.stories);
	fire.risers = recordList<IFireRiser>(fire.risers);
	fire.mains = recordList<IFireMain>(fire.mains);
	for (const main of fire.mains) {
		main.path = Array.isArray(main.path) ? main.path.filter(isPoint) : [];
	}
	fire.tanks = recordList<ITank>(fire.tanks);
	fire.pumps = recordList<IFirePump>(fire.pumps);
	if (fire.pumpRoom !== undefined) {
		if (isRecord(fire.pumpRoom)) {
			fire.pumpRoom.outline = Array.isArray(fire.pumpRoom.outline) ? fire.pumpRoom.outline.filter(isPoint) : [];
		} else {
			delete fire.pumpRoom;
		}
	}
	return fire;
}

/** The fire section, created (empty) on the first fire edit. */
export function ensureFire(document: IMep): IFire {
	const existing = normalizeFire(document.fire);
	if (existing) {
		return existing;
	}
	const fire: IFire = { building: {}, supply: {}, stories: [], risers: [], mains: [], tanks: [], pumps: [] };
	document.fire = fire;
	return fire;
}

export function fireOf(document: IMep): IFire | undefined {
	return normalizeFire(document.fire);
}

export function hasFire(document: IMep): boolean {
	const f = fireOf(document);
	return !!f && f.stories.length + f.risers.length + f.mains.length + f.tanks.length + f.pumps.length > 0;
}

// ───────────────────────────── labels ─────────────────────────────

export function fireRiserLabel(system: string): string {
	switch (system) {
		case 'standpipe': return localize('fire.riser.standpipe', "Standpipe (hydrant) riser");
		case 'sprinkler': return localize('fire.riser.sprinkler', "Sprinkler riser");
		case 'combined': return localize('fire.riser.combined', "Combined standpipe and sprinkler riser");
		default: return system;
	}
}

/** The plan symbol's letters of a riser. */
export function fireRiserLetters(system: string): string {
	return system === 'sprinkler' ? 'SR' : system === 'combined' ? 'CR' : 'SP';
}

export function firePumpLabel(duty: string): string {
	switch (duty) {
		case 'main': return localize('fire.pump.main', "Main fire pump");
		case 'standby': return localize('fire.pump.standby', "Standby fire pump");
		case 'jockey': return localize('fire.pump.jockey', "Jockey (pressurising) pump");
		default: return duty;
	}
}

export function firePumpLetters(duty: string): string {
	return duty === 'standby' ? 'FPS' : duty === 'jockey' ? 'JP' : 'FP';
}

export function hazardLabel(hazard: string): string {
	switch (hazard) {
		case 'lightI': return localize('fire.hazard.lightI', "Light hazard-I");
		case 'lightII': return localize('fire.hazard.lightII', "Light hazard-II");
		case 'ordinaryI': return localize('fire.hazard.ordinaryI', "Ordinary hazard-I");
		case 'ordinaryII': return localize('fire.hazard.ordinaryII', "Ordinary hazard-II");
		case 'ordinaryIII': return localize('fire.hazard.ordinaryIII', "Ordinary hazard-III");
		case 'extra': return localize('fire.hazard.extra', "Extra hazard");
		default: return hazard;
	}
}

export function fireStatusLabel(status: string): string {
	switch (status) {
		case 'required': return localize('fire.status.required', "Required");
		case 'performance': return localize('fire.status.performance', "Performance based");
		case 'recommended': return localize('fire.status.recommended', "Recommended");
		case 'notRequired': return localize('fire.status.notRequired', "Not required");
		default: return status;
	}
}

/** The label of a choice of the fire section's settings. */
export function fireChoiceLabel(value: string): string {
	switch (value) {
		case 'small': return localize('fire.c.small', "Small stream hose (63 or 50 mm)");
		case 'large': return localize('fire.c.large', "Large stream hose (100 mm)");
		case 'firstAid': return localize('fire.c.firstAid', "First-aid hose (38 mm)");
		case 'steel': return localize('fire.c.steel', "Black steel");
		case 'GI': return localize('fire.c.gi', "Galvanised steel");
		case 'copper': return localize('fire.c.copper', "Copper");
		case 'dedicated': return localize('fire.c.dedicated', "Dedicated fire tanks");
		case 'plumbingReserve': return localize('fire.c.plumbingReserve', "Fire reserve in the plumbing tanks");
		case 'endSuction': return localize('fire.c.endSuction', "End suction centrifugal");
		case 'splitCase': return localize('fire.c.splitCase', "Split case centrifugal");
		case 'verticalTurbine': return localize('fire.c.verticalTurbine', "Vertical turbine");
		case 'diesel': return localize('fire.c.diesel', "Diesel engine");
		case 'electric': return localize('fire.c.electric', "Electric, alternate supply");
		case 'typeIA': return localize('fire.c.typeIA', "Type I-A (monolithic RC)");
		case 'modifiedIA': return localize('fire.c.modifiedIA', "Modified Type I-A");
		case 'other': return localize('fire.c.other', "Other");
		case 'central': return localize('fire.c.central', "Central corridor");
		case 'singleOpen': return localize('fire.c.singleOpen', "Single loaded open corridor (3 m+)");
		case 'beams': return localize('fire.c.beams', "Floor on beams or girders");
		case 'openJoists': return localize('fire.c.openJoists', "Open wood joists");
		default: return value;
	}
}

// ───────────────────────────── geometry and new items ─────────────────────────────

function round(value: number, step = 50): number {
	return Math.round(value / step) * step;
}

export function fireRiserOnStory(riser: IFireRiser, context: IMepContext, storyId: string): boolean {
	return storyBetween(context, storyId, riser.fromStory, riser.toStory);
}

/** A pump's footprint: its size, else a typical 1.5 × 0.8 m set. */
export function pumpOutline(pump: IFirePump): Point[] {
	const hx = Math.max(100, num(pump.length, 1500)) / 2;
	const hy = Math.max(100, num(pump.width, 800)) / 2;
	const x = num(pump.x);
	const y = num(pump.y);
	return [[x - hx, y - hy], [x + hx, y - hy], [x + hx, y + hy], [x - hx, y + hy]];
}

/** The story a fire tank is drawn on: its own (overhead), else the lowest. */
export function fireTankStory(tank: ITank, context: IMepContext): string | undefined {
	return tank.kind === 'overhead' ? tank.story ?? undefined : context.stories[0]?.id;
}

/**
 * A new riser of `system` from the lowest story to the one below the roof, at `story`'s plan:
 * 1 m in from a corner of the floor not taken yet (in practice at a stair landing, Sec 4.2.3.9).
 */
export function newFireRiser(document: IMep, context: IMepContext, system: FireRiserSystem, story: string): IFireRiser {
	const points = storyExtent(context, story);
	const xs = points.length ? points.map(p => p[0]) : [0, 10000];
	const ys = points.length ? points.map(p => p[1]) : [0, 10000];
	const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
	const corners: Point[] = [[x0 + 1000, y0 + 1000], [x1 - 1000, y1 - 1000], [x1 - 1000, y0 + 1000], [x0 + 1000, y1 - 1000]];
	const taken = fireOf(document)?.risers ?? [];
	const free = corners.find(c => !taken.some(r => Math.hypot(num(r.x) - c[0], num(r.y) - c[1]) < 500)) ?? [(x0 + x1) / 2, (y0 + y1) / 2];
	const stories = context.stories;
	const top = stories.length > 1 ? stories[stories.length - 2].id : story;
	return {
		id: nextId('FR', allIds(document)), system, x: round(free[0]), y: round(free[1]),
		fromStory: stories[0]?.id ?? story, toStory: top,
	};
}

/** The fire row of `story`, created on its first edit. */
export function fireStoryRow(fire: IFire, story: string): IFireStory {
	let row = fire.stories.find(s => s.story === story);
	if (!row) {
		row = { story };
		fire.stories.push(row);
	}
	return row;
}

// ───────────────────────────── proposals ─────────────────────────────

const TANK_KEYS = ['kind', 'length', 'width', 'waterDepth', 'freeboard', 'compartments'] as const;
const PUMP_KEYS = ['duty', 'flow', 'head', 'power', 'length', 'width', 'height', 'operatingWeight'] as const;

export function readFireProposals(raw: unknown): { tanks: ITank[]; pumps: IFirePump[]; notes: string[] } | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	return {
		tanks: records<ITank>(raw.tanks).filter(t => typeof t.id === 'string' && typeof t.x === 'number' && typeof t.y === 'number'),
		pumps: records<IFirePump>(raw.pumps).filter(p => typeof p.id === 'string' && typeof p.story === 'string' && typeof p.x === 'number' && typeof p.y === 'number'),
		notes: strings(raw.notes),
	};
}

/** Merges the proposed tanks and pumps into the fire section; the items added or changed. */
export function mergeFireProposals(document: IMep, tanks: readonly ITank[], pumps: readonly IFirePump[]): (ITank | IFirePump)[] {
	const fire = ensureFire(document);
	const ids = () => allIds(document);
	return [
		...mergeProposals(fire.tanks, tanks.map(t => ({ ...t, story: t.story ?? null })), TANK_KEYS, ids, 'FT'),
		...mergeProposals(fire.pumps, pumps, PUMP_KEYS, ids, 'FP'),
	];
}

// ───────────────────────────── checks ─────────────────────────────

export function checkFire(document: IMep, context: IMepContext): IMepProblem[] {
	const fire = fireOf(document);
	if (!fire) {
		return [];
	}
	const problems: IMepProblem[] = [];
	const add = (path: string, severity: 'error' | 'warning', message: string) => problems.push({ path, severity, message });
	const storyIds = new Set(context.stories.map(s => s.id));
	const known = (id: unknown) => !context.stories.length || (typeof id === 'string' && storyIds.has(id));
	const elevation = (id: string) => context.stories.find(s => s.id === id)?.elevation;
	const repeated = duplicates(allIds(document));
	const checkId = (path: string, id: unknown) => {
		if (typeof id !== 'string' || !id) {
			add(path, 'error', localize('fire.p.noId', "An item of the fire protection has no ID."));
		} else if (idError(id)) {
			add(path, 'error', localize('fire.p.badId', "The ID '{0}' is not valid: {1}", id, idError(id)));
		} else if (repeated.has(id)) {
			add(path, 'error', localize('fire.p.duplicate', "The ID {0} is used twice.", id));
		}
	};
	const positive = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && value > 0);
	const shafts = new Set(document.shafts.map(s => s.id));

	fire.stories.forEach((row, i) => {
		const path = (field: string) => `fire.stories.${i}.${field}`;
		if (!known(row.story)) {
			add(path('story'), 'error', localize('fire.p.rowStory', "Fire: the building model has no story '{0}'.", String(row.story ?? '')));
		} else if (fire.stories.findIndex(s => s.story === row.story) < i) {
			add(path('story'), 'error', localize('fire.p.rowTwice', "Fire: story {0} is listed twice.", row.story));
		}
		for (const key of ['area', 'undivided'] as const) {
			if (!positive(row[key])) {
				add(path(key), 'error', localize('fire.p.area', "{0}: the {1} must be above 0, or left empty.", row.story, key));
			}
		}
		if (row.hazard !== undefined && !(FIRE_HAZARDS as readonly unknown[]).includes(row.hazard)) {
			add(path('hazard'), 'error', localize('fire.p.hazard', "{0}: '{1}' is not a hazard of Table 4.4.1.", row.story, String(row.hazard)));
		}
	});
	fire.risers.forEach((r, i) => {
		const path = (field: string) => `fire.risers.${i}.${field}`;
		checkId(path('id'), r.id);
		if (!(FIRE_RISER_SYSTEMS as readonly unknown[]).includes(r.system)) {
			add(path('system'), 'error', localize('fire.p.system', "{0}: '{1}' is not a fire riser ({2}).", r.id, String(r.system), FIRE_RISER_SYSTEMS.join(', ')));
		}
		for (const end of ['fromStory', 'toStory'] as const) {
			if (!known(r[end])) {
				add(path(end), 'error', localize('fire.p.riserStory', "{0}: the building model has no story '{1}'.", r.id, String(r[end] ?? '')));
			}
		}
		const lo = elevation(r.fromStory);
		const hi = elevation(r.toStory);
		if (lo !== undefined && hi !== undefined && hi <= lo) {
			add(path('toStory'), 'error', localize('fire.p.riserOrder', "{0}: its top story must be above the story it starts at.", r.id));
		}
		if (r.shaft !== undefined && !shafts.has(r.shaft)) {
			add(path('shaft'), 'error', localize('fire.p.shaft', "{0}: there is no shaft '{1}'.", r.id, r.shaft));
		}
		if (!positive(r.diameter)) {
			add(path('diameter'), 'error', localize('fire.p.diameter', "{0}: the diameter must be above 0, or left empty to have it sized.", r.id));
		}
	});
	fire.mains.forEach((m, i) => {
		const path = (field: string) => `fire.mains.${i}.${field}`;
		checkId(path('id'), m.id);
		if (!known(m.story)) {
			add(path('story'), 'error', localize('fire.p.mainStory', "{0}: the building model has no story '{1}'.", m.id, String(m.story ?? '')));
		}
		if (m.path.length < 2) {
			add(path('path'), 'error', localize('fire.p.mainPath', "{0}: a main needs at least two points.", m.id));
		}
	});
	fire.tanks.forEach((t, i) => {
		const path = (field: string) => `fire.tanks.${i}.${field}`;
		checkId(path('id'), t.id);
		if (t.kind !== 'overhead' && t.kind !== 'underground') {
			add(path('kind'), 'error', localize('fire.p.tankKind', "{0}: a fire tank is overhead or underground.", t.id));
		}
		if (t.kind === 'overhead' && !known(t.story)) {
			add(path('story'), 'error', localize('fire.p.tankStory', "{0}: an overhead tank needs the story it stands on.", t.id));
		}
		for (const key of ['length', 'width', 'waterDepth'] as const) {
			if (!positive(t[key])) {
				add(path(key), 'error', localize('fire.p.tankSize', "{0}: the {1} must be above 0.", t.id, key));
			}
		}
	});
	fire.pumps.forEach((p, i) => {
		const path = (field: string) => `fire.pumps.${i}.${field}`;
		checkId(path('id'), p.id);
		if (!(FIRE_PUMP_DUTIES as readonly unknown[]).includes(p.duty)) {
			add(path('duty'), 'error', localize('fire.p.duty', "{0}: '{1}' is not a pump duty ({2}).", p.id, String(p.duty), FIRE_PUMP_DUTIES.join(', ')));
		}
		if (!known(p.story)) {
			add(path('story'), 'error', localize('fire.p.pumpStory', "{0}: the building model has no story '{1}'.", p.id, String(p.story ?? '')));
		}
		for (const key of ['length', 'width', 'flow', 'head', 'power', 'operatingWeight'] as const) {
			if (!positive(p[key])) {
				add(path(key), 'error', localize('fire.p.pumpPositive', "{0}: the {1} must be above 0, or left empty.", p.id, key));
			}
		}
		if (p.equipment !== undefined && !document.equipment.some(e => e.id === p.equipment)) {
			add(path('equipment'), 'error', localize('fire.p.equipment', "{0}: there is no equipment '{1}'.", p.id, p.equipment));
		}
	});
	if (fire.pumpRoom && !known(fire.pumpRoom.story)) {
		add('fire.pumpRoom.story', 'error', localize('fire.p.roomStory', "Fire pump room: the building model has no story '{0}'.", String(fire.pumpRoom.story ?? '')));
	}
	return problems;
}

// ───────────────────────────── the report ─────────────────────────────

/**
 * `saengine.fire.report` answers `saengine.fire.report.fire_report` as it is: what Part 4
 * requires and why (`requirements.systems` with their clauses), each floor's sprinklers and
 * devices, the water and the reservoir, the hydraulic calculation, the pump sets and their room,
 * the fire tanks' designs, the hanger and support loads, the sleeves still missing, the checks.
 */
export interface IFireSystemResult {
	readonly system: FireSystem | string;
	readonly label: string;
	readonly status: FireStatus | string;
	readonly provided: boolean;
	readonly reasons: readonly string[];
}

export interface IFireStoryResult {
	readonly story: string;
	readonly occupancy?: string;
	readonly group?: string;
	readonly hazard?: string;
	readonly area?: number;
	readonly sprinklered: boolean;
	readonly heads?: number;
	readonly designHeads?: number;
	readonly extinguishers?: number;
	readonly callPoints?: number;
	readonly detectors?: number;
}

export interface IFirePumpResult {
	readonly duty: string;
	readonly label: string;
	readonly flow?: number;
	readonly head?: number;
	readonly power?: number;
	readonly count?: number;
	readonly length?: number;
	readonly width?: number;
	readonly operatingWeight?: number;
	readonly ids: readonly string[];
}

export interface IFireCheck extends IMepCheck {
	readonly clause?: string;
}

export interface IFireReport {
	readonly summary: readonly string[];
	readonly highRise?: boolean;
	readonly highRiseNote?: string;
	readonly firePlan: readonly string[];
	readonly systems: readonly IFireSystemResult[];
	readonly rules: readonly { readonly group: string; readonly clause: string; readonly text: string }[];
	readonly stories: readonly IFireStoryResult[];
	readonly demand?: { readonly standpipe?: number; readonly sprinkler?: number; readonly flow?: number; readonly duration?: number; readonly volume?: number; readonly hand?: string; readonly notes: readonly string[] };
	readonly hydraulics?: {
		readonly flow?: number; readonly pumpHead?: number; readonly governing?: string; readonly maxVelocity?: number; readonly prvStories: readonly string[];
		readonly standpipe?: { readonly first?: string; readonly flow?: number; readonly outlets: readonly { riser: string; story: string; flow?: number; pressure?: number }[] };
		readonly sprinkler?: { readonly story?: string; readonly riser?: string; readonly heads?: number; readonly headFlow?: number; readonly least?: number; readonly most?: number; readonly sprinklerFlow?: number; readonly leastPressure?: number; readonly designArea?: number; readonly density?: number };
		readonly suction?: { readonly waterLevel?: number; readonly pumpLevel?: number; readonly lift?: number };
	};
	readonly pumps: readonly IFirePumpResult[];
	readonly pumpRoom?: { readonly length?: number; readonly width?: number; readonly area?: number; readonly provided?: number; readonly note?: string };
	readonly storage?: { readonly required?: number; readonly provided?: number; readonly tanks: readonly { id: string; kind?: string; volume?: number }[]; readonly notes: readonly string[] };
	readonly tankDesigns: readonly { readonly id: string; readonly error?: string; readonly failed: number }[];
	readonly supports: readonly { readonly size?: number; readonly kind: string; readonly spacing?: number; readonly load?: number; readonly basis?: string }[];
	readonly tests: readonly { readonly system: string; readonly pressure?: number; readonly note?: string }[];
	readonly openings: readonly IOpeningResult[];
	readonly quantities: { readonly heads?: number; readonly extinguishers?: number; readonly callPoints?: number; readonly detectors?: number; readonly pipes: readonly { size?: number; length?: number }[] };
	readonly checks: readonly IFireCheck[];
	readonly notes: readonly string[];
	readonly problems: readonly string[];
	readonly method: readonly string[];
}

export function readFireReport(raw: unknown): IFireReport | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const req = record(raw.requirements);
	const demand = isRecord(raw.demand) ? raw.demand : undefined;
	const hyd = isRecord(raw.hydraulics) ? raw.hydraulics : undefined;
	const sp = hyd && isRecord(hyd.standpipe) ? hyd.standpipe : undefined;
	const spr = hyd && isRecord(hyd.sprinkler) ? hyd.sprinkler : undefined;
	const room = isRecord(raw.pumpRoom) ? raw.pumpRoom : undefined;
	const storage = isRecord(raw.storage) ? raw.storage : undefined;
	const quantities = record(raw.quantities);
	return {
		summary: strings(raw.summary),
		highRise: typeof req.highRise === 'boolean' ? req.highRise : undefined,
		highRiseNote: optionalString(req.highRiseNote),
		firePlan: strings(record(req.firePlan).reasons),
		systems: records<Record<string, unknown>>(req.systems).map(s => ({
			system: String(s.system ?? ''), label: String(s.label ?? s.system ?? ''), status: String(s.status ?? 'notRequired'), provided: s.provided === true, reasons: strings(s.reasons),
		})),
		rules: records<Record<string, unknown>>(req.rules).map(r => ({ group: String(r.group ?? ''), clause: String(r.clause ?? ''), text: String(r.text ?? '') })),
		stories: records<Record<string, unknown>>(raw.stories).map(r => {
			const s = record(r.sprinklers);
			return {
				story: String(r.story ?? ''), occupancy: optionalString(r.occupancy), group: optionalString(r.group), hazard: optionalString(r.hazard), area: optionalNumber(r.area),
				sprinklered: r.sprinklered === true, heads: optionalNumber(s.heads), designHeads: optionalNumber(s.designHeads), extinguishers: optionalNumber(r.extinguishers),
				callPoints: optionalNumber(r.callPoints), detectors: optionalNumber(r.detectors),
			};
		}),
		demand: demand ? {
			standpipe: optionalNumber(demand.standpipe), sprinkler: optionalNumber(demand.sprinkler), flow: optionalNumber(demand.flow), duration: optionalNumber(demand.duration),
			volume: optionalNumber(demand.volume), hand: optionalString(record(demand.hand).note), notes: strings(demand.notes),
		} : undefined,
		hydraulics: hyd ? {
			flow: optionalNumber(hyd.flow), pumpHead: optionalNumber(hyd.pumpHead), governing: optionalString(hyd.governing), maxVelocity: optionalNumber(hyd.maxVelocity), prvStories: strings(hyd.prvStories),
			standpipe: sp ? {
				first: optionalString(sp.first), flow: optionalNumber(sp.flow),
				outlets: records<Record<string, unknown>>(sp.outlets).map(o => ({ riser: String(o.riser ?? ''), story: String(o.story ?? ''), flow: optionalNumber(o.flow), pressure: optionalNumber(o.pressure) })),
			} : undefined,
			sprinkler: spr ? {
				story: optionalString(spr.story), riser: optionalString(spr.riser), heads: optionalNumber(spr.heads), headFlow: optionalNumber(spr.headFlow), least: optionalNumber(spr.least),
				most: optionalNumber(spr.most), sprinklerFlow: optionalNumber(spr.sprinklerFlow), leastPressure: optionalNumber(spr.leastPressure), designArea: optionalNumber(spr.designArea),
				density: optionalNumber(spr.density),
			} : undefined,
			suction: isRecord(hyd.suction) ? { waterLevel: optionalNumber(hyd.suction.waterLevel), pumpLevel: optionalNumber(hyd.suction.pumpLevel), lift: optionalNumber(hyd.suction.lift) } : undefined,
		} : undefined,
		pumps: records<Record<string, unknown>>(raw.pumps).map(p => ({
			duty: String(p.duty ?? ''), label: String(p.label ?? p.duty ?? ''), flow: optionalNumber(p.flow), head: optionalNumber(p.head), power: optionalNumber(p.power), count: optionalNumber(p.count),
			length: optionalNumber(p.length), width: optionalNumber(p.width), operatingWeight: optionalNumber(p.operatingWeight), ids: strings(p.ids),
		})),
		pumpRoom: room ? { length: optionalNumber(room.length), width: optionalNumber(room.width), area: optionalNumber(room.area), provided: optionalNumber(room.provided), note: optionalString(room.note) } : undefined,
		storage: storage ? {
			required: optionalNumber(storage.required), provided: optionalNumber(storage.provided), notes: strings(storage.notes),
			tanks: records<Record<string, unknown>>(storage.tanks).map(t => ({ id: String(t.id ?? ''), kind: optionalString(t.kind), volume: optionalNumber(t.volume) })),
		} : undefined,
		tankDesigns: records<Record<string, unknown>>(raw.tankDesigns).map(d => ({
			id: String(d.id ?? ''), error: optionalString(d.error), failed: records<Record<string, unknown>>(d.checks).filter(c => c.ok === false).length,
		})),
		supports: records<Record<string, unknown>>(raw.supports).map(s => ({ size: optionalNumber(s.size), kind: String(s.kind ?? ''), spacing: optionalNumber(s.spacing), load: optionalNumber(s.load), basis: optionalString(s.basis) })),
		tests: records<Record<string, unknown>>(raw.testPressures).map(t => ({ system: String(t.system ?? ''), pressure: optionalNumber(t.pressure), note: optionalString(t.note) })),
		openings: readOpeningResults(raw.openings),
		quantities: {
			heads: optionalNumber(quantities.heads), extinguishers: optionalNumber(quantities.extinguishers), callPoints: optionalNumber(quantities.callPoints), detectors: optionalNumber(quantities.detectors),
			pipes: records<Record<string, unknown>>(quantities.pipes).map(p => ({ size: optionalNumber(p.size), length: optionalNumber(p.length) })),
		},
		checks: records<Record<string, unknown>>(raw.checks).map(c => ({ ...readCheck(c), clause: optionalString(c.clause) })),
		notes: strings(raw.notes),
		problems: strings(raw.problems),
		method: strings(raw.method),
	};
}

export function fireFailures(report: IFireReport): number {
	return report.checks.filter(c => c.status === 'fail').length;
}

export function fireWorst(report: IFireReport): CheckStatus {
	return worst(report.checks.map(c => c.status));
}

/** The status line: "Required: hydrant, sprinklers · 2 risers · 5550 l/min, 416 m³ · 3 checks fail". */
export function fireSummary(document: IMep, report: IFireReport | undefined): string {
	const fire = fireOf(document);
	if (!fire) {
		return localize('fire.sum.none', "No fire protection yet");
	}
	const parts: string[] = [];
	const n = (count: number, one: string, many: string) => parts.push(count === 1 ? one : many);
	n(fire.stories.length, localize('fire.sum.storyOne', "1 story"), localize('fire.sum.stories', "{0} stories", fire.stories.length));
	if (fire.risers.length) {
		n(fire.risers.length, localize('fire.sum.riserOne', "1 riser"), localize('fire.sum.risers', "{0} risers", fire.risers.length));
	}
	if (report) {
		const required = report.systems.filter(s => s.status === 'required').map(s => s.label.toLowerCase());
		parts.unshift(required.length ? localize('fire.sum.required', "Required: {0}", required.join(', ')) : localize('fire.sum.nothing', "no fixed fire fighting required"));
		if (report.demand?.flow !== undefined && report.demand.volume !== undefined && report.demand.flow > 0) {
			parts.push(localize('fire.sum.water', "{0} l/min, {1} m³", report.demand.flow.toFixed(0), report.demand.volume.toFixed(0)));
		}
		const failed = fireFailures(report);
		if (failed) {
			n(failed, localize('fire.sum.fail', "1 check fails"), localize('fire.sum.fails', "{0} checks fail", failed));
		}
	}
	return parts.join(' · ');
}

/** The fire part of the part list's summary (`mep.results/summary.json`, key `fire`; as saengine.fire.summary). */
export interface IFireSummary {
	readonly risers: number;
	readonly pumps: number;
	readonly tanks: number;
	/** [l/min] */
	readonly flow?: number;
	/** [m³] */
	readonly reservoir?: number;
	readonly required: readonly string[];
	readonly openingsToAdd: number;
	readonly failed: number;
}

export function fireSummaryFile(document: IMep, report: IFireReport): IFireSummary {
	const fire = fireOf(document);
	return {
		risers: fire?.risers.length ?? 0, pumps: fire?.pumps.length ?? 0, tanks: fire?.tanks.length ?? 0,
		...(report.demand ? { flow: report.demand.flow, reservoir: report.demand.volume } : {}),
		required: report.systems.filter(s => s.status === 'required').map(s => s.system), openingsToAdd: report.openings.length, failed: fireFailures(report),
	};
}

/** The plan points the fire protection of `story` needs in view. */
export function fireExtent(document: IMep, context: IMepContext, story: string): Point[] {
	const fire = fireOf(document);
	if (!fire) {
		return [];
	}
	return [
		...fire.risers.filter(r => fireRiserOnStory(r, context, story)).map(r => [num(r.x), num(r.y)] as Point),
		...fire.pumps.filter(p => p.story === story).flatMap(pumpOutline),
		...fire.tanks.filter(t => fireTankStory(t, context) === story).flatMap(tankOutline),
		...fire.mains.filter(m => m.story === story).flatMap(m => m.path),
		...(fire.pumpRoom?.story === story ? fire.pumpRoom.outline : []),
	];
}
