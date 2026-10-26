/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { idError, IMep, IMepContext, IMepProblem, nextId, Point, storyExtent, usedIds } from './mepDocument.js';
import {
	CheckStatus, duplicates, IMepCheck, isPoint, isRecord, noteOf, num, optionalNumber, optionalString, readCheck, record, recordList, records, statusOf, strings, worst,
} from './mepRead.js';

export { statusOf };

/*
 * The plumbing section of the MEP part (`plumbing` in `07 MEP/mep.json`), as the structural
 * engineer coordinates it: the fixtures and population of each storey (for the demand), the
 * risers and stacks (for their sleeves and shafts), the tanks (their loads and RC design), the
 * roof drains (rainwater leaders), and the supply. The backend sizes and checks them
 * (`saengine.plumbing.*`); this module reads and writes the section, checks it against the
 * building, and reads the backend's answers defensively. It holds no UI.
 */

/** The occupancies of BNBC Table 8.5.1 the backend knows: `[{ key, label, lpcd }]`. */
export const PLUMBING_OCCUPANCIES_COMMAND = 'saengine.plumbing.occupancies';
/** Demand, storage, riser and stack sizes, leaders, septic tank, tank design, hydraulics: `{ projectRoot, mepText }`. */
export const PLUMBING_REPORT_COMMAND = 'saengine.plumbing.report';
/** The tanks the backend proposes: `{ projectRoot, mepText }` → `{ tanks, notes }`. */
export const PLUMBING_SIZE_TANKS_COMMAND = 'saengine.plumbing.sizeTanks';
/** The sleeves the risers and stacks need through the floors: `{ projectRoot, mepText }` → `{ openings, notes }`. */
export const PLUMBING_SLEEVES_COMMAND = 'saengine.plumbing.sleeves';

export type PlumbingSystem = 'coldWater' | 'hotWater' | 'soil' | 'waste' | 'soilWaste' | 'vent' | 'rainwater' | 'pumpMain';
export const PLUMBING_SYSTEMS: readonly PlumbingSystem[] = ['coldWater', 'hotWater', 'soil', 'waste', 'soilWaste', 'vent', 'rainwater', 'pumpMain'];

export type TankKind = 'overhead' | 'underground' | 'septic' | 'rainwater' | 'soakWell';
export const TANK_KINDS: readonly TankKind[] = ['overhead', 'underground', 'septic', 'rainwater', 'soakWell'];

export type TankConstruction = 'rc' | 'masonry' | 'prefab';
export const TANK_CONSTRUCTIONS: readonly TankConstruction[] = ['rc', 'masonry', 'prefab'];

export type SupplySource = 'mains' | 'deepTubewell';
export const SUPPLY_SOURCES: readonly SupplySource[] = ['mains', 'deepTubewell'];

export const PIPE_MATERIALS: readonly string[] = ['uPVC', 'GI', 'PPR', 'HDPE', 'CI'];

export type FixtureKey = 'wc' | 'urinal' | 'basin' | 'shower' | 'bathtub' | 'kitchenSink' | 'floorDrain' | 'washingMachine' | 'bidet';
export const FIXTURES: readonly FixtureKey[] = ['wc', 'urinal', 'basin', 'shower', 'bathtub', 'kitchenSink', 'floorDrain', 'washingMachine', 'bidet'];

export interface IOtherFixture {
	name: string;
	supplyUnits?: number;
	drainageUnits?: number;
	count: number;
	[key: string]: unknown;
}

export interface IFixtures {
	wc?: number;
	urinal?: number;
	basin?: number;
	shower?: number;
	bathtub?: number;
	kitchenSink?: number;
	floorDrain?: number;
	washingMachine?: number;
	bidet?: number;
	other?: IOtherFixture[];
	[key: string]: unknown;
}

export interface IPlumbingStory {
	story: string;
	occupancy?: string;
	population?: number;
	fixtures: IFixtures;
	[key: string]: unknown;
}

export interface IRiser {
	id: string;
	system: PlumbingSystem | string;
	x: number;
	y: number;
	fromStory: string;
	toStory: string;
	shaft?: string;
	serves?: string[];
	diameter?: number;
	material?: string;
	[key: string]: unknown;
}

export interface ITank {
	id: string;
	kind: TankKind | string;
	/** Overhead: the story it stands on; null for a tank in the ground. */
	story: string | null;
	x: number;
	y: number;
	length?: number;
	width?: number;
	/** Soak well [mm]. */
	diameter?: number;
	waterDepth?: number;
	freeboard?: number;
	compartments?: number;
	construction?: TankConstruction | string;
	walls?: number;
	base?: number;
	roof?: number;
	material?: string;
	rebar?: string;
	/** Ground tanks: the top relative to the ground [mm]. */
	topLevel?: number;
	/** Dimensions proposed by SAEngine (editable). */
	sized?: boolean;
	[key: string]: unknown;
}

export interface IRoofDrain {
	id: string;
	x: number;
	y: number;
	story: string;
	/** Catchment [m²]; else the backend splits the roof slab by the nearest drain. */
	area?: number;
	[key: string]: unknown;
}

export interface ISupply {
	source?: SupplySource | string;
	mainsHead?: number;
	pumpHours?: number;
	minResidualHead?: number;
	[key: string]: unknown;
}

export interface IRoof {
	rainfallIntensity?: number;
	drains: IRoofDrain[];
	[key: string]: unknown;
}

export interface IPlumbing {
	supply: ISupply;
	stories: IPlumbingStory[];
	risers: IRiser[];
	tanks: ITank[];
	roof: IRoof;
	[key: string]: unknown;
}

/**
 * Fills in the lists a plumbing section lacks, in place, keeping unknown fields; undefined
 * when `value` is not an object (the caller reports it). The file keeps no plumbing section
 * until the first plumbing edit, so an old file is written back unchanged.
 */
export function normalizePlumbing(value: unknown): IPlumbing | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const plumbing = value as IPlumbing;
	plumbing.supply = isRecord(plumbing.supply) ? plumbing.supply : {};
	plumbing.stories = recordList<IPlumbingStory>(plumbing.stories);
	for (const story of plumbing.stories) {
		story.fixtures = isRecord(story.fixtures) ? story.fixtures : {};
		if (story.fixtures.other !== undefined) {
			story.fixtures.other = recordList<IOtherFixture>(story.fixtures.other);
		}
	}
	plumbing.risers = recordList<IRiser>(plumbing.risers);
	plumbing.tanks = recordList<ITank>(plumbing.tanks);
	plumbing.roof = isRecord(plumbing.roof) ? plumbing.roof : { drains: [] };
	plumbing.roof.drains = recordList<IRoofDrain>(plumbing.roof.drains);
	return plumbing;
}

/** The section's plumbing, created (empty) on the first plumbing edit. */
export function ensurePlumbing(document: IMep): IPlumbing {
	const existing = normalizePlumbing(document.plumbing);
	if (existing) {
		return existing;
	}
	const plumbing: IPlumbing = { supply: {}, stories: [], risers: [], tanks: [], roof: { drains: [] } };
	document.plumbing = plumbing;
	return plumbing;
}

/** The plumbing of the document as read, without creating it. */
export function plumbingOf(document: IMep): IPlumbing | undefined {
	return normalizePlumbing(document.plumbing);
}

export function hasPlumbing(document: IMep): boolean {
	const p = plumbingOf(document);
	return !!p && (p.stories.length + p.risers.length + p.tanks.length + p.roof.drains.length > 0);
}

/**
 * Every ID of the file: equipment, openings, shafts, the plumbing's risers, tanks and drains, the
 * HVAC's plant and ducts and the electrical equipment, risers and trays share one space.
 */
export function allIds(document: IMep): string[] {
	const p = plumbingOf(document);
	const hvac = record(document.hvac);
	const electrical = record(document.electrical);
	const fire = record(document.fire);
	const listed = [hvac.plant, hvac.ducts, electrical.equipment, electrical.risers, electrical.trays, fire.risers, fire.mains, fire.tanks, fire.pumps]
		.flatMap(list => records<Record<string, unknown>>(list).map(item => item.id).filter((id): id is string => typeof id === 'string'));
	return [...usedIds(document), ...(p ? [...p.risers, ...p.tanks, ...p.roof.drains].map(item => item.id) : []), ...listed];
}

// ───────────────────────────── labels ─────────────────────────────

/** The plan symbol's letters of a system. */
export function systemLetters(system: string): string {
	switch (system) {
		case 'coldWater': return 'CW';
		case 'hotWater': return 'HW';
		case 'soil': return 'S';
		case 'waste': return 'W';
		case 'soilWaste': return 'SW';
		case 'vent': return 'V';
		case 'rainwater': return 'RW';
		case 'pumpMain': return 'PM';
		default: return '?';
	}
}

export function systemLabel(system: string): string {
	switch (system) {
		case 'coldWater': return localize('plb.sys.coldWater', "Cold water riser");
		case 'hotWater': return localize('plb.sys.hotWater', "Hot water riser");
		case 'soil': return localize('plb.sys.soil', "Soil stack");
		case 'waste': return localize('plb.sys.waste', "Waste stack");
		case 'soilWaste': return localize('plb.sys.soilWaste', "Soil and waste stack");
		case 'vent': return localize('plb.sys.vent', "Vent stack");
		case 'rainwater': return localize('plb.sys.rainwater', "Rainwater leader");
		case 'pumpMain': return localize('plb.sys.pumpMain', "Pumping main");
		default: return system;
	}
}

export function tankKindLabel(kind: string): string {
	switch (kind) {
		case 'overhead': return localize('plb.tank.overhead', "Overhead tank");
		case 'underground': return localize('plb.tank.underground', "Underground reservoir");
		case 'septic': return localize('plb.tank.septic', "Septic tank");
		case 'rainwater': return localize('plb.tank.rainwater', "Rainwater tank");
		case 'soakWell': return localize('plb.tank.soakWell', "Soak well");
		default: return kind;
	}
}

export function constructionLabel(construction: string): string {
	switch (construction) {
		case 'rc': return localize('plb.cons.rc', "Reinforced concrete");
		case 'masonry': return localize('plb.cons.masonry', "Brick masonry");
		case 'prefab': return localize('plb.cons.prefab', "Prefabricated");
		default: return construction;
	}
}

export function sourceLabel(source: string): string {
	return source === 'mains' ? localize('plb.src.mains', "City main") : source === 'deepTubewell' ? localize('plb.src.dtw', "Deep tubewell") : source;
}

export function fixtureLabel(fixture: FixtureKey): string {
	switch (fixture) {
		case 'wc': return localize('plb.fx.wc', "WC");
		case 'urinal': return localize('plb.fx.urinal', "Urinal");
		case 'basin': return localize('plb.fx.basin', "Basin");
		case 'shower': return localize('plb.fx.shower', "Shower");
		case 'bathtub': return localize('plb.fx.bathtub', "Bathtub");
		case 'kitchenSink': return localize('plb.fx.kitchenSink', "Kitchen sink");
		case 'floorDrain': return localize('plb.fx.floorDrain', "Floor drain");
		case 'washingMachine': return localize('plb.fx.washingMachine', "Washing machine");
		case 'bidet': return localize('plb.fx.bidet', "Bidet");
	}
}

/** Ground tanks have no story: they are drawn on the lowest story's plan. */
export function isGroundTank(tank: ITank): boolean {
	return tank.kind !== 'overhead';
}

// ───────────────────────────── occupancies ─────────────────────────────

export interface IOccupancy {
	readonly key: string;
	readonly label: string;
	/** Daily water consumption per person, full facility [litres per capita per day]. */
	readonly lpcd?: number;
	/** Where it comes from ("BNBC Table 8.5.1(d) E1"). */
	readonly source?: string;
	/** Its BNBC Part 3 occupancy group ("E1"), when the backend gives it. */
	readonly group?: string;
}

/** The backend's occupancy list, read defensively: `[...]` or `{ occupancies: [...] }`. */
export function readOccupancies(raw: unknown): IOccupancy[] | undefined {
	const list = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.occupancies) ? raw.occupancies : undefined;
	if (!list) {
		return undefined;
	}
	const occupancies = list.filter(isRecord).map(o => {
		const key = typeof o.key === 'string' ? o.key : typeof o.id === 'string' ? o.id : '';
		const label = typeof o.label === 'string' ? o.label : typeof o.name === 'string' ? o.name : key;
		const lpcd = typeof o.lpcd === 'number' ? o.lpcd : typeof o.consumption === 'number' ? o.consumption : undefined;
		return { key, label, lpcd, source: typeof o.source === 'string' ? o.source : typeof o.table === 'string' ? o.table : undefined, group: typeof o.group === 'string' ? o.group : undefined };
	}).filter(o => o.key);
	return occupancies.length ? occupancies : undefined;
}

// ───────────────────────────── totals and capacities ─────────────────────────────

/** The fixture counts of every storey added up, `other` fixtures as one count. */
export function fixtureTotals(plumbing: IPlumbing): { [K in FixtureKey | 'other' | 'population']: number } {
	const totals = { population: 0, other: 0, wc: 0, urinal: 0, basin: 0, shower: 0, bathtub: 0, kitchenSink: 0, floorDrain: 0, washingMachine: 0, bidet: 0 };
	for (const row of plumbing.stories) {
		totals.population += num(row.population);
		for (const key of FIXTURES) {
			totals[key] += num(row.fixtures[key]);
		}
		totals.other += (row.fixtures.other ?? []).reduce((sum, o) => sum + num(o.count), 0);
	}
	return totals;
}

/** A tank's water volume to its water depth [m³]; undefined without its sizes. */
export function tankCapacity(tank: ITank): number | undefined {
	const depth = num(tank.waterDepth);
	if (!(depth > 0)) {
		return undefined;
	}
	if (tank.kind === 'soakWell' || (tank.diameter && !tank.length)) {
		const d = num(tank.diameter);
		return d > 0 ? Math.PI * d * d / 4 * depth / 1e9 : undefined;
	}
	const l = num(tank.length);
	const w = num(tank.width);
	return l > 0 && w > 0 ? l * w * depth / 1e9 : undefined;
}

/** A tank's plan outline: the inside footprint grown by the walls (a soak well: a 24-gon). */
export function tankOutline(tank: ITank): Point[] {
	const wall = Math.max(0, num(tank.walls));
	const cx = num(tank.x);
	const cy = num(tank.y);
	if (tank.kind === 'soakWell' || (tank.diameter && !tank.length)) {
		const r = Math.max(100, num(tank.diameter, 1200) / 2 + wall);
		return Array.from({ length: 24 }, (_, i) => [cx + r * Math.cos(i * Math.PI / 12), cy + r * Math.sin(i * Math.PI / 12)] as Point);
	}
	const hx = Math.max(100, num(tank.length, 1000) / 2 + wall);
	const hy = Math.max(100, num(tank.width, 1000) / 2 + wall);
	return [[cx - hx, cy - hy], [cx + hx, cy - hy], [cx + hx, cy + hy], [cx - hx, cy + hy]];
}

/** Whether a riser is drawn on `storyId`'s plan: from its lowest story up to its top one. */
export function riserOnStory(riser: IRiser, context: IMepContext, storyId: string): boolean {
	const elevation = (id: string) => context.stories.find(s => s.id === id)?.elevation;
	const at = elevation(storyId);
	const from = elevation(riser.fromStory);
	const to = elevation(riser.toStory);
	if (at === undefined || from === undefined || to === undefined) {
		return riser.fromStory === storyId || riser.toStory === storyId;
	}
	return at >= Math.min(from, to) - 1 && at <= Math.max(from, to) + 1;
}

/** The story a tank is drawn on: its own (overhead), else the lowest story. */
export function tankStory(tank: ITank, context: IMepContext): string | undefined {
	return isGroundTank(tank) ? context.stories[0]?.id : tank.story ?? undefined;
}

// ───────────────────────────── new items ─────────────────────────────

function round(value: number, step = 50): number {
	return Math.round(value / step) * step;
}

function extentBox(context: IMepContext, story: string | undefined): [number, number, number, number] {
	const points = story ? storyExtent(context, story) : [];
	const all = points.length ? points : context.stories.flatMap(s => storyExtent(context, s.id));
	if (!all.length) {
		return [0, 10000, 0, 10000];
	}
	return [Math.min(...all.map(p => p[0])), Math.max(...all.map(p => p[0])), Math.min(...all.map(p => p[1])), Math.max(...all.map(p => p[1]))];
}

/**
 * A new riser or stack of `system` at `story`'s plan: near the middle of the floor, set off by
 * 600 mm from the risers already there, running from the lowest story to the top one (a soil
 * or waste stack drains down to the lowest; a leader comes down from the roof).
 */
export function newRiser(document: IMep, context: IMepContext, system: PlumbingSystem, story: string | undefined): IRiser {
	const plumbing = plumbingOf(document);
	const [x0, x1, y0, y1] = extentBox(context, story);
	const count = plumbing?.risers.length ?? 0;
	const prefix = system === 'coldWater' || system === 'hotWater' || system === 'pumpMain' ? 'R' : system === 'rainwater' ? 'RWP' : 'ST';
	return {
		id: nextId(prefix, allIds(document)),
		system,
		x: round((x0 + x1) / 2 + (count % 4) * 600),
		y: round((y0 + y1) / 2 + Math.floor(count / 4) * 600),
		fromStory: context.stories[0]?.id ?? story ?? '',
		toStory: context.stories[context.stories.length - 1]?.id ?? story ?? '',
	};
}

/**
 * A new tank of `kind`, to start from: an overhead tank on `story` (the roof by default) at the
 * middle of its floor; a reservoir, septic tank, rainwater tank or soak well in the ground beside
 * the building (to its left, each 1 m below the ground tanks already there), 1 m clear of it.
 * Sizes are typical, for the engineer to edit or for {@link PLUMBING_SIZE_TANKS_COMMAND} to propose.
 */
export function newTank(document: IMep, context: IMepContext, kind: TankKind, story: string | undefined): ITank {
	const id = nextId(kind === 'septic' ? 'ST-T' : kind === 'soakWell' ? 'SW' : 'T', allIds(document));
	const roofStory = story ?? context.stories[context.stories.length - 1]?.id ?? null;
	const [x0, x1, y0, y1] = extentBox(context, kind === 'overhead' ? roofStory ?? undefined : undefined);
	if (kind === 'overhead') {
		return { id, kind, story: roofStory, x: round((x0 + x1) / 2), y: round((y0 + y1) / 2), length: 3000, width: 2500, waterDepth: 1500, freeboard: 300, compartments: 2, construction: 'rc', walls: 150, base: 150, roof: 125, sized: false };
	}
	const tank: ITank = kind === 'soakWell'
		? { id, kind, story: null, x: 0, y: 0, diameter: 1200, waterDepth: 3000, construction: 'masonry', walls: 250, topLevel: 0, sized: false }
		: {
			id, kind, story: null, x: 0, y: 0, length: kind === 'septic' ? 3600 : 4000, width: kind === 'septic' ? 1500 : 3000, waterDepth: kind === 'septic' ? 1500 : 2000,
			freeboard: 300, compartments: kind === 'septic' ? 2 : 1, construction: 'rc', walls: 200, base: 200, roof: 150, topLevel: 0, sized: false,
		};
	// Beside the building on the left, 1 m clear of it and 1 m below the ground tanks already there.
	const outline = tankOutline(tank);
	const halfX = Math.max(...outline.map(p => p[0]));
	const halfY = Math.max(...outline.map(p => p[1]));
	const others = (plumbingOf(document)?.tanks ?? []).filter(isGroundTank).flatMap(tankOutline);
	const top = others.length ? Math.min(...others.map(p => p[1])) - 1000 : y1;
	tank.x = round(x0 - 1000 - halfX);
	tank.y = round(top - halfY);
	return tank;
}

/** A new roof drain on `story`: at a free corner of its floor, 500 mm in. */
export function newRoofDrain(document: IMep, context: IMepContext, story: string): IRoofDrain {
	const [x0, x1, y0, y1] = extentBox(context, story);
	const drains = plumbingOf(document)?.roof.drains.filter(d => d.story === story) ?? [];
	const corners: Point[] = [[x0 + 500, y0 + 500], [x1 - 500, y0 + 500], [x1 - 500, y1 - 500], [x0 + 500, y1 - 500]];
	const free = corners.find(c => !drains.some(d => Math.hypot(num(d.x) - c[0], num(d.y) - c[1]) < 300)) ?? [(x0 + x1) / 2, (y0 + y1) / 2];
	return { id: nextId('RD', allIds(document)), story, x: round(free[0]), y: round(free[1]) };
}

/** The storey's row of the fixtures table, created on the first edit. */
export function storyRow(plumbing: IPlumbing, story: string): IPlumbingStory {
	let row = plumbing.stories.find(s => s.story === story);
	if (!row) {
		row = { story, fixtures: {} };
		plumbing.stories.push(row);
	}
	return row;
}

/** The fields of a tank the sizing may change (not its ID, position, story or `sized`). */
const SIZE_KEYS = ['kind', 'length', 'width', 'diameter', 'waterDepth', 'freeboard', 'compartments', 'construction', 'walls', 'base', 'roof', 'material', 'rebar', 'topLevel'] as const;

/**
 * Merges the backend's proposed tanks into the file. A proposal with an ID of the file changes
 * only the sizes that differ (the position stays where the engineer put it) and is marked
 * `sized` only when something changed and the backend says so; one the file lacks is added
 * with an unused ID. A proposal that repeats a tank of the file unchanged is left out.
 * Returns the tanks added or changed.
 */
export function mergeSizedTanks(document: IMep, proposed: readonly ITank[]): ITank[] {
	const plumbing = ensurePlumbing(document);
	const touched: ITank[] = [];
	for (const proposal of proposed) {
		const existing = proposal.id ? plumbing.tanks.find(t => t.id === proposal.id) : undefined;
		if (existing) {
			const changed = SIZE_KEYS.filter(key => proposal[key] !== undefined && proposal[key] !== existing[key]);
			if (!changed.length) {
				continue;
			}
			const target: { [key: string]: unknown } = existing;
			for (const key of changed) {
				target[key] = proposal[key];
			}
			if (proposal.sized !== false) {
				existing.sized = true;
			}
			touched.push(existing);
		} else {
			const ids = allIds(document);
			const tank: ITank = { ...proposal, id: proposal.id && !ids.includes(proposal.id) ? proposal.id : nextId('T', ids), sized: proposal.sized !== false };
			plumbing.tanks.push(tank);
			touched.push(tank);
		}
	}
	return touched;
}

/**
 * The tanks the backend proposes and its notes: `saengine.plumbing.sizeTanks` answers a bare
 * list of tanks (P1's `plumbing_size_tanks`) or `{ tanks, notes }`.
 */
export function readSizedTanks(raw: unknown): { tanks: ITank[]; notes: string[] } | undefined {
	if (Array.isArray(raw)) {
		raw = { tanks: raw };
	}
	if (!isRecord(raw)) {
		return undefined;
	}
	const tanks = records<ITank>(raw.tanks).filter(t => typeof t.kind === 'string').map(t => ({
		...t, id: typeof t.id === 'string' ? t.id : '', story: typeof t.story === 'string' ? t.story : null, x: num(t.x), y: num(t.y),
	}));
	return { tanks, notes: strings(raw.notes) };
}

// ───────────────────────────── checks ─────────────────────────────

/** What is missing or inconsistent in the plumbing section (the contract's rules), as problems with dotted paths. */
export function checkPlumbing(document: IMep, context: IMepContext): IMepProblem[] {
	const plumbing = plumbingOf(document);
	if (!plumbing) {
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
			add(path, 'error', localize('plb.p.noId', "An item of the plumbing has no ID."));
		} else if (idError(id)) {
			add(path, 'error', localize('plb.p.badId', "The ID '{0}' is not valid: {1}", id, idError(id)));
		} else if (repeated.has(id)) {
			add(path, 'error', localize('plb.p.duplicate', "The ID {0} is used twice.", id));
		}
	};
	const positive = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && value > 0);
	const count = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && Number.isInteger(value) && value >= 0);

	const supply = plumbing.supply;
	if (supply.source !== undefined && !(SUPPLY_SOURCES as readonly unknown[]).includes(supply.source)) {
		add('plumbing.supply.source', 'error', localize('plb.p.source', "The water source must be the city main or a deep tubewell."));
	}
	if (supply.mainsHead !== undefined && !(num(supply.mainsHead, -1) >= 0)) {
		add('plumbing.supply.mainsHead', 'error', localize('plb.p.mainsHead', "The residual head of the main cannot be negative."));
	}
	if (supply.pumpHours !== undefined && !(num(supply.pumpHours) > 0 && num(supply.pumpHours) <= 24)) {
		add('plumbing.supply.pumpHours', 'error', localize('plb.p.pumpHours', "The pumping hours must be above 0 and at most 24 a day."));
	}
	if (!positive(supply.minResidualHead)) {
		add('plumbing.supply.minResidualHead', 'error', localize('plb.p.minHead', "The minimum residual head must be above 0, or left empty for the code's."));
	}

	plumbing.stories.forEach((row, i) => {
		const path = (field: string) => `plumbing.stories.${i}.${field}`;
		if (!known(row.story)) {
			add(path('story'), 'error', localize('plb.p.rowStory', "Fixtures: the building model has no story '{0}'.", String(row.story ?? '')));
		} else if (plumbing.stories.findIndex(s => s.story === row.story) < i) {
			add(path('story'), 'error', localize('plb.p.rowTwice', "Fixtures: story {0} is listed twice.", row.story));
		}
		if (row.population !== undefined && !(num(row.population, -1) >= 0)) {
			add(path('population'), 'error', localize('plb.p.population', "{0}: the population cannot be negative.", row.story));
		}
		for (const key of FIXTURES) {
			if (!count(row.fixtures[key])) {
				add(path(`fixtures.${key}`), 'error', localize('plb.p.fixture', "{0}: the number of {1} must be a whole number, 0 or more.", row.story, fixtureLabel(key)));
			}
		}
		(row.fixtures.other ?? []).forEach((o, j) => {
			if (!o.name || !count(o.count)) {
				add(path(`fixtures.other.${j}`), 'error', localize('plb.p.other', "{0}: another fixture needs a name and a count.", row.story));
			}
		});
	});

	const shafts = new Set(document.shafts.map(s => s.id));
	plumbing.risers.forEach((r, i) => {
		const path = (field: string) => `plumbing.risers.${i}.${field}`;
		checkId(path('id'), r.id);
		if (!(PLUMBING_SYSTEMS as readonly unknown[]).includes(r.system)) {
			add(path('system'), 'error', localize('plb.p.system', "{0}: '{1}' is not a system ({2}).", r.id, String(r.system), PLUMBING_SYSTEMS.join(', ')));
		}
		for (const end of ['fromStory', 'toStory'] as const) {
			if (!known(r[end])) {
				add(path(end), 'error', localize('plb.p.riserStory', "{0}: the building model has no story '{1}'.", r.id, String(r[end] ?? '')));
			}
		}
		const from = elevation(r.fromStory);
		const to = elevation(r.toStory);
		if (from !== undefined && to !== undefined && to <= from) {
			add(path('toStory'), 'error', localize('plb.p.riserOrder', "{0}: its top story must be above the story it starts at.", r.id));
		}
		if (r.shaft && !shafts.has(r.shaft)) {
			add(path('shaft'), 'error', localize('plb.p.shaft', "{0}: there is no shaft '{1}'.", r.id, r.shaft));
		}
		for (const story of r.serves ?? []) {
			if (!known(story)) {
				add(path('serves'), 'error', localize('plb.p.serves', "{0}: it serves story '{1}', which the building model does not have.", r.id, String(story)));
			}
		}
		if (!positive(r.diameter)) {
			add(path('diameter'), 'error', localize('plb.p.diameter', "{0}: give a diameter above 0, or leave it empty to have it sized.", r.id));
		}
		if (r.material !== undefined && !PIPE_MATERIALS.includes(r.material)) {
			add(path('material'), 'warning', localize('plb.p.material', "{0}: '{1}' is not one of the pipe materials ({2}).", r.id, r.material, PIPE_MATERIALS.join(', ')));
		}
	});

	plumbing.tanks.forEach((t, i) => {
		const path = (field: string) => `plumbing.tanks.${i}.${field}`;
		checkId(path('id'), t.id);
		if (!(TANK_KINDS as readonly unknown[]).includes(t.kind)) {
			add(path('kind'), 'error', localize('plb.p.tankKind', "{0}: '{1}' is not a kind of tank ({2}).", t.id, String(t.kind), TANK_KINDS.join(', ')));
		}
		if (t.kind === 'overhead' && !t.story) {
			add(path('story'), 'error', localize('plb.p.tankStoryNeeded', "{0}: an overhead tank needs the story it stands on.", t.id));
		} else if (t.story && !known(t.story)) {
			add(path('story'), 'error', localize('plb.p.tankStory', "{0}: the building model has no story '{1}'.", t.id, t.story));
		}
		if (t.kind === 'soakWell') {
			if (!(num(t.diameter) > 0)) {
				add(path('diameter'), 'error', localize('plb.p.soakDiameter', "{0}: give the soak well's diameter.", t.id));
			}
		} else {
			for (const field of ['length', 'width'] as const) {
				if (!(num(t[field]) > 0)) {
					add(path(field), 'error', localize('plb.p.tankSize', "{0}: give its inside length and width above 0 (or size the tanks).", t.id));
					break;
				}
			}
		}
		for (const field of ['waterDepth', 'walls', 'base', 'roof'] as const) {
			if (!positive(t[field])) {
				add(path(field), 'error', localize('plb.p.tankPositive', "{0}: the {1} must be above 0, or left empty.", t.id, field));
			}
		}
		if (t.freeboard !== undefined && !(num(t.freeboard, -1) >= 0)) {
			add(path('freeboard'), 'error', localize('plb.p.freeboard', "{0}: the freeboard cannot be negative.", t.id));
		}
		if (t.compartments !== undefined && !(Number.isInteger(t.compartments) && t.compartments >= 1)) {
			add(path('compartments'), 'error', localize('plb.p.compartments', "{0}: give one compartment or more.", t.id));
		}
		if (t.construction !== undefined && !(TANK_CONSTRUCTIONS as readonly unknown[]).includes(t.construction)) {
			add(path('construction'), 'error', localize('plb.p.construction', "{0}: the construction must be rc, masonry or prefab.", t.id));
		}
		if (t.material && context.concretes.length && !context.concretes.some(c => c.id === t.material)) {
			add(path('material'), 'warning', localize('plb.p.concrete', "{0}: 03 Materials has no concrete '{1}'.", t.id, t.material));
		}
	});

	if (!positive(plumbing.roof.rainfallIntensity)) {
		add('plumbing.roof.rainfallIntensity', 'error', localize('plb.p.rainfall', "The rainfall intensity must be above 0, or left empty for the default."));
	}
	plumbing.roof.drains.forEach((d, i) => {
		const path = (field: string) => `plumbing.roof.drains.${i}.${field}`;
		checkId(path('id'), d.id);
		if (!known(d.story)) {
			add(path('story'), 'error', localize('plb.p.drainStory', "{0}: the building model has no story '{1}'.", d.id, String(d.story ?? '')));
		}
		if (!positive(d.area)) {
			add(path('area'), 'error', localize('plb.p.drainArea', "{0}: the catchment must be above 0 m², or left empty to split the roof.", d.id));
		}
	});
	return problems;
}

// ───────────────────────────── the backend's report ─────────────────────────────

/*
 * `saengine.plumbing.report` answers P1's `plumbing_report` (python/src/saengine/plumbing/
 * report.py): `{ demand, storage, risers, stacks, drains, rainwater, septic, tanks (the
 * proposals), sleeves, checks, summary, notes, problems, method }`. The integrator adds the
 * tanks' RC design as `tankDesigns` (P2's `design_tank` of each tank) and the supply's
 * hydraulics as `hydraulics` (P3's `water_hydraulics`). Every part is read defensively: a
 * missing one leaves its section out.
 */

export type PlumbingStatus = CheckStatus;

export interface IDemandRow {
	readonly story: string;
	readonly occupancy?: string;
	readonly population?: number;
	readonly lpcd?: number;
	/** [L/day] */
	readonly daily?: number;
	readonly supplyUnits?: number;
	readonly drainageUnits?: number;
}

export interface IStorageRow {
	/** The tank's kind ("overhead", "underground"). */
	readonly kind: string;
	readonly tank?: string;
	/** [m³] */
	readonly required?: number;
	readonly provided?: number;
	readonly status: PlumbingStatus;
	readonly note?: string;
}

export interface ISizedItem {
	readonly id: string;
	readonly system?: string;
	/** Fixture units, or the flow it carries. */
	readonly load?: number;
	readonly loadUnit?: string;
	/** The size the code needs [mm]. */
	readonly required?: number;
	/** The size given or proposed [mm]. */
	readonly diameter?: number;
	/** Catchment [m²] (leaders). */
	readonly area?: number;
	readonly status: PlumbingStatus;
	readonly note?: string;
}

/** One check: P1's and P3's `{ name, demand, capacity, unit, utilisation, ok, note }`, P2's with its `combination`. */
export type IPlumbingCheck = IMepCheck;

export interface ITankDesign {
	readonly id: string;
	readonly kind?: string;
	/** [m³] */
	readonly capacity?: number;
	readonly checks: readonly IPlumbingCheck[];
	/** The bars, one line per member, direction and face. */
	readonly reinforcement: readonly { readonly location: string; readonly bars: string }[];
	/** Its loads on the supports (overhead tank), as text. */
	readonly loads?: string;
	/** Concrete, formwork and reinforcement, as text. */
	readonly quantities?: string;
	readonly status: PlumbingStatus;
	readonly notes: readonly string[];
}

export interface ISepticResult {
	readonly id: string;
	readonly kind: 'septic' | 'soakWell';
	readonly population?: number;
	/** Liquid volume [m³] (septic tank) or the soak well's capacity. */
	readonly required?: number;
	readonly provided?: number;
	/** Inside sizes [mm]. */
	readonly length?: number;
	readonly width?: number;
	readonly depth?: number;
	readonly diameter?: number;
	readonly status: PlumbingStatus;
	readonly note?: string;
}

export interface IFloorHead {
	readonly story: string;
	readonly riser?: string;
	/** [m] */
	readonly elevation?: number;
	/** Residual head at the floor's highest outlet [m]. */
	readonly head: number;
	readonly required?: number;
	readonly status: PlumbingStatus;
}

export interface ICatchment {
	readonly drain: string;
	/** [m²] */
	readonly area?: number;
	readonly outline: readonly Point[];
	/** The leader's size [mm]. */
	readonly leader?: number;
	readonly note?: string;
}

export interface IPlumbingReport {
	readonly summary: readonly string[];
	readonly demand: readonly IDemandRow[];
	/** [L/day] */
	readonly dailyDemand?: number;
	readonly population?: number;
	readonly storage: readonly IStorageRow[];
	/** Storage the code needs [m³]. */
	readonly overheadRequired?: number;
	readonly undergroundRequired?: number;
	readonly fireReserve?: number;
	readonly risers: readonly ISizedItem[];
	readonly leaders: readonly ISizedItem[];
	readonly catchments: readonly ICatchment[];
	readonly septic: readonly ISepticResult[];
	/** P1's checks: storage, risers, stacks, drains, rainwater, septic tank, soak well, separations, shafts. */
	readonly checks: readonly IPlumbingCheck[];
	/** P2: the tanks' RC design. */
	readonly tanks: readonly ITankDesign[];
	/** Tanks whose design is still running (the quick first pass gives only the cached designs). */
	readonly tankDesignsPending: number;
	/** P3: the hydraulics' checks (heads, velocities, the city main). */
	readonly hydraulicChecks: readonly IPlumbingCheck[];
	readonly floors: readonly IFloorHead[];
	readonly requiredHead?: number;
	/** Flow [L/s], head [m], shaft power and the standard motor chosen [kW]. */
	readonly pump?: { readonly flow?: number; readonly head?: number; readonly power?: number; readonly motor?: number; readonly note?: string };
	/** The backend's references for the sections (BNBC table and page). */
	readonly references: { readonly demand?: string; readonly storage?: string; readonly rainwater?: string; readonly septic?: string; readonly soakWell?: string };
	readonly notes: readonly string[];
	readonly problems: readonly string[];
	readonly method: readonly string[];
	readonly sources?: { readonly [part: string]: string };
}

const UNITS = localize('plb.unit.units', "units");
const LPM = localize('plb.unit.lpm', "L/min");

/** A riser, stack or leader of P1: `{ id, system, units, flow, area, diameter, required, ok, notes }`. */
function sized(item: Record<string, unknown>): ISizedItem {
	const units = optionalNumber(item.units);
	const flow = optionalNumber(item.flow);
	return {
		id: String(item.id ?? ''), system: optionalString(item.system),
		load: units ?? flow, loadUnit: units !== undefined ? UNITS : flow !== undefined ? LPM : undefined,
		required: optionalNumber(item.required), diameter: optionalNumber(item.diameter), area: optionalNumber(item.area), status: statusOf(item), note: noteOf(item),
	};
}

function memberLabel(member: 'walls' | 'base' | 'roof'): string {
	switch (member) {
		case 'walls': return localize('plb.member.walls', "Walls");
		case 'base': return localize('plb.member.base', "Base");
		default: return localize('plb.member.roof', "Roof");
	}
}

/** P2's `design_tank` result: `{ id, kind, geometry, checks, walls, base, roof, supportLoads, quantities, notes }` (or `{ id, error }`). */
function readTankDesign(t: Record<string, unknown>): ITankDesign {
	const checks = records<Record<string, unknown>>(t.checks).map(readCheck);
	const reinforcement: { location: string; bars: string }[] = [];
	for (const member of ['walls', 'base', 'roof'] as const) {
		const groups = new Map<string, string[]>();
		for (const layer of records<Record<string, unknown>>(t[member])) {
			const bars = optionalString(layer.bars);
			if (!bars) {
				continue;
			}
			const location = [memberLabel(member), optionalString(layer.direction), optionalString(layer.face)].filter(Boolean).join(' · ');
			const list = groups.get(location) ?? [];
			if (!list.includes(bars)) {
				list.push(bars);
			}
			groups.set(location, list);
		}
		for (const [location, bars] of groups) {
			reinforcement.push({ location, bars: bars.join(' / ') });
		}
	}
	const geometry = record(t.geometry);
	const support = record(t.supportLoads);
	const full = optionalNumber(support.full);
	const empty = optionalNumber(support.empty);
	const q = record(t.quantities);
	const concrete = optionalNumber(q.concrete);
	const notes = strings(t.notes);
	const error = optionalString(t.error);
	if (error) {
		notes.unshift(localize('plb.designError', "The design did not run: {0}", error));
	}
	return {
		id: String(t.id ?? ''), kind: optionalString(t.kind ?? geometry.kind), capacity: optionalNumber(geometry.capacity ?? t.capacity), checks, reinforcement,
		loads: full !== undefined ? localize('plb.designLoads', "On its supports: {0} kN full, {1} kN empty", full.toFixed(1), empty === undefined ? '?' : empty.toFixed(1)) : undefined,
		quantities: concrete !== undefined ? localize('plb.designQuantities', "Concrete {0} m³ · formwork {1} m² · reinforcement {2} kg", concrete.toFixed(2), String(optionalNumber(q.formwork)?.toFixed(1) ?? '?'), String(optionalNumber(q.reinforcement) ?? '?')) : undefined,
		status: worst(checks.map(c => c.status)), notes,
	};
}

/** The backend's plumbing report, read defensively; undefined when it is not one. */
export function readPlumbingReport(raw: unknown): IPlumbingReport | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const demand = record(raw.demand);
	const storage = record(raw.storage);
	const rainwater = record(raw.rainwater);
	const septic = isRecord(raw.septic) ? raw.septic : undefined;
	const hydraulics = record(raw.hydraulics);
	const checks = records<Record<string, unknown>>(raw.checks).map(readCheck);
	const proposals = records<Record<string, unknown>>(raw.tanks);
	const idsOf = (kind: string) => proposals.filter(t => t.kind === kind).map(t => String(t.id ?? ''));

	// Storage: each tank with its share of the volume and P1's "<id> volume" check.
	const storageRows = records<Record<string, unknown>>(storage.tanks).map(r => {
		const tank = optionalString(r.id);
		const required = optionalNumber(r.required);
		const provided = optionalNumber(r.provided);
		const check = checks.find(c => tank !== undefined && c.name === `${tank} volume`);
		const drain = optionalNumber(r.drain);
		const overflow = optionalNumber(r.overflow);
		const pipes = drain !== undefined && overflow !== undefined ? localize('plb.storagePipes', "drain Ø{0}, overflow Ø{1} mm", drain, overflow) : undefined;
		return {
			kind: String(r.kind ?? ''), tank, required, provided,
			status: check?.status ?? (required !== undefined && provided !== undefined ? (provided >= required - 1e-9 ? 'ok' : 'fail') : 'none') as PlumbingStatus,
			note: [pipes, ...strings(r.notes)].filter(Boolean).join('; ') || undefined,
		};
	});

	// Septic tank and soak well.
	const septicRows: ISepticResult[] = [];
	if (septic) {
		const own = checks.filter(c => c.name.startsWith('Septic tank'));
		const volume = optionalNumber(septic.volume);
		const provided = optionalNumber(septic.provided);
		septicRows.push({
			id: idsOf('septic')[0] ?? '', kind: 'septic', population: optionalNumber(septic.persons ?? septic.population),
			required: volume === undefined ? undefined : volume / 1000, provided: provided === undefined ? undefined : provided / 1000,
			length: optionalNumber(septic.length), width: optionalNumber(septic.width), depth: optionalNumber(septic.waterDepth ?? septic.depth),
			status: own.length ? worst(own.map(c => c.status)) : volume !== undefined && provided !== undefined ? (provided >= volume ? 'ok' : 'fail') : 'none',
			note: noteOf(septic),
		});
		if (isRecord(septic.soakWell)) {
			const well = septic.soakWell;
			septicRows.push({
				id: idsOf('soakWell')[0] ?? '', kind: 'soakWell', diameter: optionalNumber(well.diameter), depth: optionalNumber(well.waterDepth),
				status: statusOf(well), note: noteOf(well),
			});
		}
	}

	// Hydraulics (P3): the head at each floor; the required head also from P1.
	const heads = record(storage.heads);
	const hydraulicFloors = records<Record<string, unknown>>(hydraulics.floors).filter(f => typeof f.head === 'number');
	const requiredHead = optionalNumber(hydraulics.requiredHead) ?? optionalNumber(heads.minResidualHead) ?? optionalNumber(hydraulicFloors[0]?.required);
	const p3Pump = isRecord(hydraulics.pump) ? hydraulics.pump : undefined;
	const p1Pump = isRecord(storage.pump) ? storage.pump : undefined;
	let pump: IPlumbingReport['pump'];
	if (p3Pump) {
		pump = { flow: optionalNumber(p3Pump.flow), head: optionalNumber(p3Pump.tdh ?? p3Pump.head), power: optionalNumber(p3Pump.shaftPower ?? p3Pump.power), ...(optionalNumber(p3Pump.motor) !== undefined ? { motor: optionalNumber(p3Pump.motor) } : {}), note: optionalString(p3Pump.note) };
	} else if (p1Pump) {
		const lpm = optionalNumber(p1Pump.flow);
		pump = { flow: lpm === undefined ? undefined : lpm / 60, note: optionalString(p1Pump.note) };
	}

	return {
		summary: strings(raw.summary),
		demand: records<Record<string, unknown>>(demand.stories).map(r => ({
			story: String(r.story ?? ''), occupancy: optionalString(r.occupancy), population: optionalNumber(r.population), lpcd: optionalNumber(r.lpcd), daily: optionalNumber(r.daily),
			supplyUnits: optionalNumber(r.supplyUnits), drainageUnits: optionalNumber(r.drainageUnits),
		})),
		dailyDemand: optionalNumber(demand.daily),
		population: optionalNumber(demand.population),
		storage: storageRows,
		overheadRequired: optionalNumber(storage.overhead),
		undergroundRequired: optionalNumber(storage.underground),
		fireReserve: optionalNumber(storage.fireReserve),
		risers: records<Record<string, unknown>>(raw.risers).map(sized),
		leaders: records<Record<string, unknown>>(rainwater.leaders).map(sized),
		catchments: records<Record<string, unknown>>(rainwater.drains).map(c => ({
			drain: String(c.id ?? c.drain ?? ''), area: optionalNumber(c.area), outline: Array.isArray(c.outline) ? c.outline.filter(isPoint) : [],
			leader: optionalNumber(c.leader), note: optionalString(c.source ?? c.note),
		})),
		septic: septicRows,
		checks,
		tanks: records<Record<string, unknown>>(raw.tankDesigns).filter(t => t.pending !== true).map(readTankDesign),
		tankDesignsPending: records<Record<string, unknown>>(raw.tankDesigns).filter(t => t.pending === true).length,
		hydraulicChecks: records<Record<string, unknown>>(hydraulics.checks).map(readCheck),
		floors: hydraulicFloors.map(f => {
			const head = num(f.head);
			const required = optionalNumber(f.required) ?? requiredHead;
			const status: PlumbingStatus = typeof f.pressureOk === 'boolean' ? (f.pressureOk ? 'ok' : 'fail') : required === undefined ? 'none' : head < required ? 'fail' : 'ok';
			return { story: String(f.story ?? ''), riser: optionalString(f.riser), elevation: optionalNumber(f.elevation), head, required, status };
		}).sort((a, b) => (a.elevation ?? 0) - (b.elevation ?? 0)),
		requiredHead,
		pump,
		references: {
			demand: optionalString(demand.method), storage: optionalString(storage.reference), rainwater: optionalString(rainwater.reference),
			septic: optionalString(septic?.reference), soakWell: optionalString(record(septic?.soakWell).reference),
		},
		notes: [...strings(raw.notes), ...strings(storage.notes), ...strings(rainwater.notes), ...strings(hydraulics.notes)],
		problems: [...strings(raw.problems), ...strings(hydraulics.problems)],
		method: strings(raw.method),
		sources: isRecord(raw.sources) ? Object.fromEntries(Object.entries(raw.sources).filter((e): e is [string, string] => typeof e[1] === 'string')) : undefined,
	};
}

/**
 * The plumbing's failures in a report: the failing checks (P1's sizing, storage, septic tank,
 * soak well, separations and shafts; P3's hydraulics; P2's tank design) and the floors below
 * the minimum residual head.
 */
export function plumbingFailures(report: IPlumbingReport): { items: number; floorsLow: number } {
	const failing = [...report.checks, ...report.hydraulicChecks, ...report.tanks.flatMap(t => t.checks)].filter(c => c.status === 'fail').length;
	const low = new Set(report.floors.filter(f => f.status === 'fail').map(f => f.story));
	return { items: failing, floorsLow: low.size };
}

/** The status line: "6 storeys · 4 risers · 2 tanks · 1 floor below the minimum pressure". */
export function plumbingSummary(document: IMep, report: IPlumbingReport | undefined): string {
	const plumbing = plumbingOf(document);
	if (!plumbing) {
		return localize('plb.sum.none', "No plumbing yet");
	}
	const parts: string[] = [];
	const n = (count: number, one: string, many: string) => parts.push(count === 1 ? one : many);
	n(plumbing.stories.length, localize('plb.sum.storey', "1 storey"), localize('plb.sum.storeys', "{0} storeys", plumbing.stories.length));
	n(plumbing.risers.length, localize('plb.sum.riser', "1 riser"), localize('plb.sum.risers', "{0} risers", plumbing.risers.length));
	n(plumbing.tanks.length, localize('plb.sum.tank', "1 tank"), localize('plb.sum.tanks', "{0} tanks", plumbing.tanks.length));
	if (plumbing.roof.drains.length) {
		n(plumbing.roof.drains.length, localize('plb.sum.drain', "1 roof drain"), localize('plb.sum.drains', "{0} roof drains", plumbing.roof.drains.length));
	}
	if (report) {
		const { items, floorsLow } = plumbingFailures(report);
		if (floorsLow) {
			n(floorsLow, localize('plb.sum.floorLow', "1 floor below the minimum pressure"), localize('plb.sum.floorsLow', "{0} floors below the minimum pressure", floorsLow));
		}
		if (items) {
			n(items, localize('plb.sum.fail', "1 check fails"), localize('plb.sum.fails', "{0} checks fail", items));
		}
	}
	return parts.join(' · ');
}

/** The plumbing part of the part list's summary (`mep.results/summary.json`, key `plumbing`). */
export interface IPlumbingSummary {
	readonly risers: number;
	readonly tanks: number;
	/** Failing checks: P1's (sizing, storage, septic, soak well, separations, shafts), P3's hydraulics, P2's tank design. */
	readonly failed: number;
	readonly floorsLow: number;
	/**
	 * The stamp of the soil report the results read ("" for a missing file), beyond the MEP
	 * summary's own sources: the soak well, flotation, bearing and ground tank designs depend on it.
	 */
	readonly source?: { readonly soil: string };
}

export function plumbingSummaryFile(document: IMep, report: IPlumbingReport): IPlumbingSummary {
	const plumbing = plumbingOf(document);
	const { items, floorsLow } = plumbingFailures(report);
	const soil = report.sources?.soil;
	return { risers: plumbing?.risers.length ?? 0, tanks: plumbing?.tanks.length ?? 0, failed: items, floorsLow, ...(soil !== undefined ? { source: { soil } } : {}) };
}
