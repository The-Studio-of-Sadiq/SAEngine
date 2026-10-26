/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import {
	EQUIPMENT_PRESETS, idError, IEquipment, IMep, IMepContext, IMepProblem, IOpening, newEquipment, nextId, openingPoint, Point, shaftOnStory, storyElements, storyExtent,
} from './mepDocument.js';
import {
	CheckStatus, duplicates, IMepCheck, isRecord, mergeProposals, noteOf, num, optionalNumber, optionalString, problemsOf, readChecks, record, recordList, records,
	roofStory, statusOf, storyAbove, storyBetween, strings, worst,
} from './mepRead.js';
import { allIds } from './plumbingDocument.js';

/*
 * The HVAC section of the MEP part (`hvac` in `07 MEP/mep.json`), as the structural engineer
 * coordinates it: the system and design conditions (for the cooling load the backend computes
 * with EnergyPlus, or estimates), the envelope, the use of each storey, the plant (its weight
 * on the floors, on the roof) and the ducts (their openings through the beams and the floors,
 * their shafts). The backend sizes and checks them (`saengine.hvac.*`); this module reads and
 * writes the section, checks it against the building, and reads the backend's answers
 * defensively. It holds no UI.
 */

/** The report: loads per story, airflow, ducts, plant, openings and shafts: `{ projectRoot, mepText }`. */
export const HVAC_REPORT_COMMAND = 'saengine.hvac.report';
/** Runs the cooling load calculation (EnergyPlus as a separate process, else an estimate); can take ~30 s: `{ projectRoot, mepText }`, then a cancellation token. */
export const HVAC_LOADS_COMMAND = 'saengine.hvac.loads';
/** The plant the backend proposes: `{ projectRoot, mepText }` → `{ plant, notes }`. */
export const HVAC_PROPOSE_PLANT_COMMAND = 'saengine.hvac.proposePlant';
/** The openings the ducts need through beams, slabs and walls: `{ projectRoot, mepText }` → `{ openings, notes }`. */
export const HVAC_DUCT_OPENINGS_COMMAND = 'saengine.hvac.ductOpenings';
/** The envelope's constructions: `{ wall: [{key, label, u}], roof: [...], glazing: [{key, label, u, shgc}] }`. */
export const HVAC_CONSTRUCTIONS_COMMAND = 'saengine.hvac.constructions';
/** The tables the backend knows (optional): `{ cities: [...], uses: [...] }` (BNBC Tables 8.2.2 and 8.2.3). */
export const HVAC_TABLES_COMMAND = 'saengine.hvac.tables';

export type HvacSystem = 'vrf' | 'chilledWater' | 'split' | 'packaged' | 'none';
export const HVAC_SYSTEMS: readonly HvacSystem[] = ['vrf', 'chilledWater', 'split', 'packaged', 'none'];

export type PlantKind = 'chiller' | 'coolingTower' | 'ahu' | 'fcu' | 'vrfOutdoor' | 'splitOutdoor' | 'pump' | 'exhaustFan' | 'freshAirUnit';
export const PLANT_KINDS: readonly PlantKind[] = ['vrfOutdoor', 'splitOutdoor', 'chiller', 'coolingTower', 'ahu', 'fcu', 'freshAirUnit', 'exhaustFan', 'pump'];

export type DuctSystem = 'supply' | 'return' | 'exhaust' | 'freshAir' | 'kitchenExhaust' | 'smoke';
export const DUCT_SYSTEMS: readonly DuctSystem[] = ['supply', 'return', 'exhaust', 'freshAir', 'kitchenExhaust', 'smoke'];

export type DuctShape = 'rect' | 'round';
export const DUCT_SHAPES: readonly DuctShape[] = ['rect', 'round'];

export type Shading = 'none' | 'overhang' | 'blinds';
export const SHADINGS: readonly Shading[] = ['none', 'overhang', 'blinds'];

export const FACADES = ['N', 'E', 'S', 'W'] as const;
export type Facade = typeof FACADES[number];

export interface IHvacDesign {
	/** A key of BNBC Table 8.2.2 (e.g. "dhaka"). */
	city?: string;
	/** Overrides [°C]; else the table's. */
	outdoorDB?: number;
	outdoorWB?: number;
	indoorDB?: number;
	/** [%] */
	indoorRH?: number;
	dailyRange?: number;
	[key: string]: unknown;
}

export interface IHvacEnvelope {
	wall?: string;
	roof?: string;
	glazing?: string;
	/** Overrides [W/m²K]. */
	uWall?: number;
	uRoof?: number;
	uGlazing?: number;
	shgc?: number;
	shading?: Shading | string;
	[key: string]: unknown;
}

export interface IHvacStory {
	story: string;
	conditioned?: boolean;
	/** A key of BNBC Table 8.2.3. */
	use?: string;
	occupants?: number;
	/** [W/m²] */
	lighting?: number;
	equipment?: number;
	/** Window-to-wall ratio per facade, 0 to 1. */
	glazing?: { N?: number; E?: number; S?: number; W?: number;[key: string]: unknown };
	[key: string]: unknown;
}

export interface IPlant {
	id: string;
	kind: PlantKind | string;
	story: string;
	x: number;
	y: number;
	length?: number;
	width?: number;
	height?: number;
	/** Cooling [kW], or airflow [m³/s] for fans. */
	capacity?: number;
	/** [kN] */
	operatingWeight?: number;
	sized?: boolean;
	serves?: string[];
	[key: string]: unknown;
}

export interface IDuctRiser {
	fromStory: string;
	toStory: string;
	[key: string]: unknown;
}

export interface IDuct {
	id: string;
	system: DuctSystem | string;
	shape: DuctShape | string;
	width?: number;
	height?: number;
	diameter?: number;
	story: string;
	/** Horizontal run in plan [mm]; a riser stands at its first point. */
	path: Point[];
	/** Underside above the story's floor [mm]; else just below the slab soffit. */
	bottom?: number;
	riser?: IDuctRiser;
	shaft?: string;
	/** [m³/s] */
	flow?: number;
	[key: string]: unknown;
}

export interface IHvac {
	system?: HvacSystem | string;
	design: IHvacDesign;
	envelope: IHvacEnvelope;
	stories: IHvacStory[];
	plant: IPlant[];
	ducts: IDuct[];
	[key: string]: unknown;
}

/** Fills in what an HVAC section lacks, in place, keeping unknown fields; undefined when it is not an object. */
export function normalizeHvac(value: unknown): IHvac | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const hvac = value as IHvac;
	hvac.design = isRecord(hvac.design) ? hvac.design : {};
	hvac.envelope = isRecord(hvac.envelope) ? hvac.envelope : {};
	hvac.stories = recordList<IHvacStory>(hvac.stories);
	hvac.plant = recordList<IPlant>(hvac.plant);
	hvac.ducts = recordList<IDuct>(hvac.ducts);
	for (const duct of hvac.ducts) {
		duct.path = Array.isArray(duct.path) ? duct.path.filter((p): p is Point => Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number') : [];
	}
	return hvac;
}

/** The HVAC section, created (empty) on the first HVAC edit: an old file is written back unchanged until then. */
export function ensureHvac(document: IMep): IHvac {
	const existing = normalizeHvac(document.hvac);
	if (existing) {
		return existing;
	}
	const hvac: IHvac = { design: {}, envelope: {}, stories: [], plant: [], ducts: [] };
	document.hvac = hvac;
	return hvac;
}

export function hvacOf(document: IMep): IHvac | undefined {
	return normalizeHvac(document.hvac);
}

export function hasHvac(document: IMep): boolean {
	const h = hvacOf(document);
	return !!h && (h.stories.length + h.plant.length + h.ducts.length > 0 || !!h.system || !!h.design.city);
}

// ───────────────────────────── labels ─────────────────────────────

export function hvacSystemLabel(system: string): string {
	switch (system) {
		case 'vrf': return localize('hvac.sys.vrf', "VRF (variable refrigerant flow)");
		case 'chilledWater': return localize('hvac.sys.chilledWater', "Chilled water (chillers and AHUs)");
		case 'split': return localize('hvac.sys.split', "Split units");
		case 'packaged': return localize('hvac.sys.packaged', "Packaged units");
		case 'none': return localize('hvac.sys.none', "None (ventilation only)");
		default: return system;
	}
}

export function plantKindLabel(kind: string): string {
	switch (kind) {
		case 'chiller': return localize('hvac.plant.chiller', "Chiller");
		case 'coolingTower': return localize('hvac.plant.coolingTower', "Cooling tower");
		case 'ahu': return localize('hvac.plant.ahu', "Air handling unit");
		case 'fcu': return localize('hvac.plant.fcu', "Fan coil unit");
		case 'vrfOutdoor': return localize('hvac.plant.vrfOutdoor', "VRF outdoor unit");
		case 'splitOutdoor': return localize('hvac.plant.splitOutdoor', "Split outdoor unit");
		case 'pump': return localize('hvac.plant.pump', "Pump");
		case 'exhaustFan': return localize('hvac.plant.exhaustFan', "Exhaust fan");
		case 'freshAirUnit': return localize('hvac.plant.freshAirUnit', "Fresh air unit");
		default: return kind;
	}
}

/** The plan symbol's letters of a plant kind. */
export function plantLetters(kind: string): string {
	switch (kind) {
		case 'chiller': return 'CH';
		case 'coolingTower': return 'CT';
		case 'ahu': return 'AHU';
		case 'fcu': return 'FCU';
		case 'vrfOutdoor': return 'ODU';
		case 'splitOutdoor': return 'SOU';
		case 'pump': return 'P';
		case 'exhaustFan': return 'EF';
		case 'freshAirUnit': return 'FAU';
		default: return '?';
	}
}

/** Fans give their airflow [m³/s]; the rest their cooling [kW]. */
export function isFan(kind: string): boolean {
	return kind === 'exhaustFan' || kind === 'freshAirUnit';
}

export function capacityUnit(kind: string): string {
	return isFan(kind) ? localize('hvac.unit.m3s', "m³/s") : localize('hvac.unit.kw', "kW");
}

export function ductSystemLabel(system: string): string {
	switch (system) {
		case 'supply': return localize('hvac.duct.supply', "Supply air");
		case 'return': return localize('hvac.duct.return', "Return air");
		case 'exhaust': return localize('hvac.duct.exhaust', "Exhaust air");
		case 'freshAir': return localize('hvac.duct.freshAir', "Fresh air");
		case 'kitchenExhaust': return localize('hvac.duct.kitchenExhaust', "Kitchen exhaust");
		case 'smoke': return localize('hvac.duct.smoke', "Smoke extract");
		default: return system;
	}
}

export function ductLetters(system: string): string {
	switch (system) {
		case 'supply': return 'SA';
		case 'return': return 'RA';
		case 'exhaust': return 'EA';
		case 'freshAir': return 'FA';
		case 'kitchenExhaust': return 'KE';
		case 'smoke': return 'SE';
		default: return '?';
	}
}

export function ductShapeLabel(shape: string): string {
	return shape === 'rect' ? localize('hvac.shape.rect', "Rectangular") : shape === 'round' ? localize('hvac.shape.round', "Round") : shape;
}

export function shadingLabel(shading: string): string {
	switch (shading) {
		case 'none': return localize('hvac.shading.none', "None");
		case 'overhang': return localize('hvac.shading.overhang', "Overhangs");
		case 'blinds': return localize('hvac.shading.blinds', "Internal blinds");
		default: return shading;
	}
}

// ───────────────────────────── BNBC tables (static until the backend lists them) ─────────────────────────────

export interface IHvacCity {
	readonly key: string;
	readonly label: string;
	/** Cooling design dry bulb and mean coincident wet bulb at 2 % [°C] (Sec 2.12.2.1). */
	readonly db?: number;
	readonly wb?: number;
	/** Mean daily range [°C]. */
	readonly range?: number;
}

export interface IHvacUse {
	readonly key: string;
	readonly label: string;
	/** Outdoor air per person [L/s], per floor area [L/s·m²], default occupant density [per 100 m²]. */
	readonly perPerson?: number;
	readonly perArea?: number;
	readonly density?: number;
	readonly source?: string;
}

export interface IConstruction {
	readonly key: string;
	readonly label: string;
	/** [W/m²K] from the backend. */
	readonly u?: number;
	readonly shgc?: number;
}

export interface IConstructions {
	readonly wall: readonly IConstruction[];
	readonly roof: readonly IConstruction[];
	readonly glazing: readonly IConstruction[];
}

/**
 * The envelope's constructions until the backend lists them ({@link HVAC_CONSTRUCTIONS_COMMAND}):
 * the backend's keys and names (saengine.hvac.constructions, EnergyPlus data sets); the U-values
 * are the backend's (the editor shows none of its own).
 */
export const STATIC_CONSTRUCTIONS: IConstructions = {
	wall: [
		{ key: 'brick250', label: localize('hvac.cons.brick250', "250 mm brick wall, 12 mm plaster both sides") },
		{ key: 'brick125', label: localize('hvac.cons.brick125', "125 mm brick wall, 12 mm plaster both sides") },
	],
	roof: [
		{ key: 'rcLimeTerracing', label: localize('hvac.cons.limeTerracing', "100 mm lime terracing on 150 mm RC slab") },
		{ key: 'rcInsulated', label: localize('hvac.cons.rcInsulated', "Screed on 50 mm EPS insulation on 150 mm RC slab") },
	],
	glazing: [
		{ key: 'singleClear', label: localize('hvac.cons.singleClear', "Single clear glass 6 mm") },
		{ key: 'doubleClear', label: localize('hvac.cons.doubleClear', "Double clear glass 6 / 13 air / 6 mm") },
	],
};

function readKeyed<T extends { key: string; label: string }>(list: unknown, make: (key: string, label: string, o: Record<string, unknown>) => T): T[] {
	return records<Record<string, unknown>>(list).map(o => {
		const key = typeof o.key === 'string' ? o.key : typeof o.id === 'string' ? o.id : '';
		const label = typeof o.label === 'string' ? o.label : typeof o.name === 'string' ? o.name : key;
		return make(key, label, o);
	}).filter(o => o.key);
}

/** The backend's constructions: `{ wall, roof, glazing }`, or a list with `element` per item. */
export function readConstructions(raw: unknown): IConstructions | undefined {
	const source = isRecord(raw) && isRecord(raw.constructions) ? raw.constructions : raw;
	const extra = (key: string, label: string, o: Record<string, unknown>): IConstruction => ({ key, label, u: optionalNumber(o.u ?? o.uValue), shgc: optionalNumber(o.shgc) });
	let result: IConstructions;
	if (Array.isArray(source)) {
		const of = (element: string) => readKeyed<IConstruction>(source.filter(o => isRecord(o) && (o.element === element || o.kind === element)), extra);
		result = { wall: of('wall'), roof: of('roof'), glazing: of('glazing') };
	} else if (isRecord(source)) {
		result = { wall: readKeyed<IConstruction>(source.wall ?? source.walls, extra), roof: readKeyed<IConstruction>(source.roof ?? source.roofs, extra), glazing: readKeyed<IConstruction>(source.glazing, extra) };
	} else {
		return undefined;
	}
	return result.wall.length + result.roof.length + result.glazing.length ? result : undefined;
}

/** The backend's tables: `{ cities, uses }`; each list may be missing. */
export function readHvacTables(raw: unknown): { cities?: IHvacCity[]; uses?: IHvacUse[] } {
	const source = record(raw);
	// `db` / `wb` at 2 %, or a station's `cooling: { '2': [DB, MWB] }` (saengine.hvac.tables Station).
	const design = (o: Record<string, unknown>, i: number) => {
		const pair = record(o.cooling)['2'];
		return Array.isArray(pair) ? optionalNumber(pair[i]) : undefined;
	};
	const cities = readKeyed<IHvacCity>(source.cities, (key, label, o) => ({ key, label, db: optionalNumber(o.db ?? o.outdoorDB) ?? design(o, 0), wb: optionalNumber(o.wb ?? o.outdoorWB) ?? design(o, 1), range: optionalNumber(o.range ?? o.dailyRange) }));
	const uses = readKeyed<IHvacUse>(source.uses, (key, label, o) => ({
		key, label, perPerson: optionalNumber(o.perPerson), perArea: optionalNumber(o.perArea), density: optionalNumber(o.density), source: optionalString(o.source),
	}));
	return { cities: cities.length ? cities : undefined, uses: uses.length ? uses : undefined };
}

// ───────────────────────────── geometry ─────────────────────────────

/** A plant item's footprint (centred on x, y, length along x). */
export function plantOutline(plant: IPlant): Point[] {
	const hx = Math.max(100, num(plant.length, 1000)) / 2;
	const hy = Math.max(100, num(plant.width, 1000)) / 2;
	const x = num(plant.x);
	const y = num(plant.y);
	return [[x - hx, y - hy], [x + hx, y - hy], [x + hx, y + hy], [x - hx, y + hy]];
}

/** A duct's size across, in plan [mm]: its width, else its diameter. */
export function ductPlanWidth(duct: IDuct): number {
	return duct.shape === 'round' ? num(duct.diameter, num(duct.width, 300)) : num(duct.width, num(duct.diameter, 300));
}

/** A duct's depth [mm]: its height, else its diameter. */
export function ductDepth(duct: IDuct): number {
	return duct.shape === 'round' ? num(duct.diameter, num(duct.height, 300)) : num(duct.height, num(duct.diameter, 300));
}

export function isRiserDuct(duct: IDuct): boolean {
	return isRecord(duct.riser);
}

/** Whether a duct is drawn on `storyId`: a horizontal run on its story, a riser on each story it passes. */
export function ductOnStory(duct: IDuct, context: IMepContext, storyId: string): boolean {
	if (duct.riser) {
		return storyBetween(context, storyId, duct.riser.fromStory, duct.riser.toStory);
	}
	return duct.story === storyId;
}

/** The soffit of the floor above a story: that floor's level less its slab [mm, absolute]; undefined at the top. */
function soffit(context: IMepContext, storyId: string): number | undefined {
	const above = storyAbove(context, storyId);
	if (!above) {
		return undefined;
	}
	const slabs = storyElements(context, above.id).slabs;
	const thickness = slabs.length ? Math.max(...slabs.map(s => s.thickness)) : 0;
	return above.elevation - thickness;
}

/** The underside and top of a horizontal duct [mm, absolute]: its `bottom`, else just below the slab soffit. */
export function ductLevels(duct: IDuct, context: IMepContext): { bottom: number; top: number } | undefined {
	const story = context.stories.find(s => s.id === duct.story);
	if (!story) {
		return undefined;
	}
	const depth = ductDepth(duct);
	if (duct.bottom !== undefined) {
		const bottom = story.elevation + num(duct.bottom);
		return { bottom, top: bottom + depth };
	}
	const top = soffit(context, duct.story);
	return top === undefined ? undefined : { bottom: top - depth, top };
}

/** Where a horizontal run crosses a beam's axis: the point and the distance along the beam [mm]. */
export interface IDuctCrossing {
	readonly duct: string;
	readonly beam: string;
	readonly point: Point;
	/** From the beam's start to the crossing [mm]. */
	readonly distance: number;
	/** The angle between the duct and the beam [°], 90 square across. */
	readonly angle: number;
	/** An opening of the file through the beam at the crossing. */
	readonly opening?: string;
}

function segmentIntersection(a: Point, b: Point, c: Point, d: Point): { point: Point; t: number; u: number } | undefined {
	const r: Point = [b[0] - a[0], b[1] - a[1]];
	const s: Point = [d[0] - c[0], d[1] - c[1]];
	const denominator = r[0] * s[1] - r[1] * s[0];
	if (Math.abs(denominator) < 1e-9) {
		return undefined;
	}
	const t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / denominator;
	const u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / denominator;
	if (t < -1e-9 || t > 1 + 1e-9 || u < -1e-9 || u > 1 + 1e-9) {
		return undefined;
	}
	return { point: [a[0] + t * r[0], a[1] + t * r[1]], t, u };
}

/**
 * The beams a horizontal duct passes through: the beams of the floor above its story whose depth
 * it is at (its levels overlap the beam's, from the soffit of the beam to the top of the slab),
 * with the opening of the file through each at the crossing (within half the duct and 100 mm).
 * A duct that runs below the beams crosses none. The backend's duct openings check them.
 */
export function ductCrossings(duct: IDuct, document: IMep, context: IMepContext): IDuctCrossing[] {
	if (duct.riser || duct.path.length < 2) {
		return [];
	}
	const above = storyAbove(context, duct.story);
	if (!above) {
		return [];
	}
	const levels = ductLevels(duct, context);
	const crossings: IDuctCrossing[] = [];
	for (const beam of storyElements(context, above.id).beams) {
		if (levels && (levels.top <= beam.elevation - beam.depth + 1 || levels.bottom >= beam.elevation - 1)) {
			continue;
		}
		const span = Math.hypot(beam.end[0] - beam.start[0], beam.end[1] - beam.start[1]) || 1;
		for (let i = 1; i < duct.path.length; i++) {
			const hit = segmentIntersection(duct.path[i - 1], duct.path[i], beam.start, beam.end);
			if (!hit) {
				continue;
			}
			const along = hit.u * span;
			const a = duct.path[i - 1];
			const b = duct.path[i];
			const cos = Math.abs(((b[0] - a[0]) * (beam.end[0] - beam.start[0]) + (b[1] - a[1]) * (beam.end[1] - beam.start[1])) / ((Math.hypot(b[0] - a[0], b[1] - a[1]) || 1) * span));
			const reach = ductPlanWidth(duct) / 2 + 100;
			const opening = document.openings.find(o => {
				const point = o.host === beam.id ? openingPoint(o, context) : undefined;
				return !!point && Math.hypot(point[0] - hit.point[0], point[1] - hit.point[1]) <= reach;
			});
			crossings.push({ duct: duct.id, beam: beam.id, point: hit.point, distance: Math.round(along), angle: Math.round(Math.acos(Math.min(1, cos)) * 180 / Math.PI), opening: opening?.id });
		}
	}
	return crossings;
}

/** Every crossing of the HVAC's ducts with the beams, on `storyId` (the story the ducts run on) or all. */
export function allCrossings(document: IMep, context: IMepContext, storyId?: string): IDuctCrossing[] {
	const hvac = hvacOf(document);
	return (hvac?.ducts ?? []).filter(d => !storyId || d.story === storyId).flatMap(d => ductCrossings(d, document, context));
}

/** Whether a riser duct stands in a shaft of the file (its point inside the shaft's outline). */
export function riserInShaft(duct: IDuct, document: IMep): string | undefined {
	const point = duct.path[0];
	if (!point) {
		return undefined;
	}
	if (duct.shaft && document.shafts.some(s => s.id === duct.shaft)) {
		return duct.shaft;
	}
	const inside = (outline: readonly Point[]) => {
		const xs = outline.map(p => p[0]);
		const ys = outline.map(p => p[1]);
		return outline.length >= 3 && point[0] >= Math.min(...xs) && point[0] <= Math.max(...xs) && point[1] >= Math.min(...ys) && point[1] <= Math.max(...ys);
	};
	return document.shafts.find(s => inside(s.outline))?.id;
}

// ───────────────────────────── new items ─────────────────────────────

function round(value: number, step = 50): number {
	return Math.round(value / step) * step;
}

/** Typical footprints to start from [mm] (to edit to the supplier's data); the chiller, AHU and pump from the equipment presets. */
const PLANT_FOOTPRINT: { readonly [K in PlantKind]: readonly [number, number, number] } = {
	vrfOutdoor: [1250, 800, 1700],
	splitOutdoor: [900, 350, 700],
	chiller: [0, 0, 0],
	coolingTower: [3000, 3000, 3500],
	ahu: [0, 0, 0],
	fcu: [1200, 600, 300],
	freshAirUnit: [2000, 1200, 1200],
	exhaustFan: [800, 800, 800],
	pump: [0, 0, 0],
};

/** Kinds that usually stand on the roof. */
const ROOF_KINDS: readonly string[] = ['vrfOutdoor', 'splitOutdoor', 'coolingTower', 'chiller', 'exhaustFan'];

const PLANT_PREFIX: { readonly [K in PlantKind]: string } = {
	chiller: 'CH', coolingTower: 'CTW', ahu: 'AHU', fcu: 'FCU', vrfOutdoor: 'ODU', splitOutdoor: 'SOU', pump: 'PU', exhaustFan: 'EF', freshAirUnit: 'FAU',
};

/** The footprints already on a story: equipment, plant and electrical equipment, as equipment (for the free place). */
export function footprintsOn(document: IMep, story: string): IEquipment[] {
	const asEquipment = (item: Record<string, unknown>): IEquipment => ({
		id: String(item.id ?? ''), kind: 'other', story, x: num(item.x), y: num(item.y), length: Math.max(100, num(item.length, 1000)), width: Math.max(100, num(item.width, 1000)), operatingWeight: 0,
	});
	const hvac = hvacOf(document);
	const electrical = record(document.electrical);
	return [
		...document.equipment.filter(e => e.story === story),
		...(hvac?.plant ?? []).filter(p => p.story === story).map(asEquipment),
		...records<Record<string, unknown>>(electrical.equipment).filter(e => e.story === story).map(asEquipment),
	];
}

/**
 * A new plant item of `kind`: outdoor units, cooling towers, chillers and exhaust fans on the roof,
 * the rest on `story`; at the free place nearest the middle of the floor, clear of the equipment,
 * plant, shafts and slab openings there (the equipment's placement). Typical sizes; the weight is
 * left for the supplier's data (or {@link HVAC_PROPOSE_PLANT_COMMAND}).
 */
export function newPlant(document: IMep, context: IMepContext, kind: PlantKind, story: string | undefined): IPlant {
	const target = ROOF_KINDS.includes(kind) ? roofStory(context)?.id ?? story : story ?? roofStory(context)?.id;
	const preset = EQUIPMENT_PRESETS.find(p => p.kind === kind);
	const [length, width, height] = preset ? [preset.length, preset.width, preset.height] : PLANT_FOOTPRINT[kind];
	const id = nextId(PLANT_PREFIX[kind], allIds(document));
	const plant: IPlant = { id, kind, story: target ?? '', x: 0, y: 0, length, width, height, sized: false, ...(preset ? { operatingWeight: preset.operatingWeight } : {}) };
	if (!target) {
		return plant;
	}
	const placed = newEquipment({ ...document, equipment: footprintsOn(document, target) }, context, {
		kind: 'other', name: '', length, width, height, operatingWeight: 1, emptyWeight: 1,
	}, target);
	plant.x = placed.x;
	plant.y = placed.y;
	if (placed.rotation) {
		plant.length = width;
		plant.width = length;
	}
	return plant;
}

/** Typical duct sizes to start from [mm] per system (to size from the airflow). */
const DUCT_SIZE: { readonly [K in DuctSystem]: readonly [number, number] } = {
	supply: [600, 300], return: [600, 300], exhaust: [400, 250], freshAir: [400, 250], kitchenExhaust: [500, 400], smoke: [800, 400],
};

/** A new horizontal duct of `system` on `story` along `path` (from the plan). */
export function newDuct(document: IMep, system: DuctSystem, story: string, path: Point[]): IDuct {
	const [width, height] = DUCT_SIZE[system];
	return { id: nextId('D', allIds(document)), system, shape: 'rect', width, height, story, path: path.map(p => [round(p[0]), round(p[1])] as Point) };
}

/**
 * A new riser duct of `system`: in the first shaft through `story` (at its centre, set off by the
 * ducts already there), else at the middle of the floor; from the lowest story to the top.
 */
export function newRiserDuct(document: IMep, context: IMepContext, system: DuctSystem, story: string): IDuct {
	const [width, height] = DUCT_SIZE[system];
	const shaft = document.shafts.find(s => shaftOnStory(s, context, story) && s.outline.length >= 3);
	let point: Point;
	if (shaft) {
		const xs = shaft.outline.map(p => p[0]);
		const ys = shaft.outline.map(p => p[1]);
		const count = (hvacOf(document)?.ducts ?? []).filter(d => d.riser && riserInShaft(d, document) === shaft.id).length;
		point = [round((Math.min(...xs) + Math.max(...xs)) / 2), round((Math.min(...ys) + Math.max(...ys)) / 2 + (count % 2 ? -1 : 1) * Math.ceil(count / 2) * (height + 100))];
	} else {
		const extent = storyExtent(context, story);
		const xs = extent.map(p => p[0]);
		const ys = extent.map(p => p[1]);
		point = extent.length ? [round((Math.min(...xs) + Math.max(...xs)) / 2), round((Math.min(...ys) + Math.max(...ys)) / 2)] : [0, 0];
	}
	return {
		id: nextId('D', allIds(document)), system, shape: 'rect', width, height, story: context.stories[0]?.id ?? story, path: [point],
		riser: { fromStory: context.stories[0]?.id ?? story, toStory: context.stories[context.stories.length - 1]?.id ?? story }, ...(shaft ? { shaft: shaft.id } : {}),
	};
}

/** The storey's row of the HVAC table, created on the first edit. */
export function hvacStoryRow(hvac: IHvac, story: string): IHvacStory {
	let row = hvac.stories.find(s => s.story === story);
	if (!row) {
		row = { story };
		hvac.stories.push(row);
	}
	return row;
}

/** The fields of a plant item the backend's proposal may change (not its ID, story or position). */
const PLANT_SIZE_KEYS = ['kind', 'length', 'width', 'height', 'capacity', 'operatingWeight', 'serves'] as const;

/** The plant the backend proposes: a list, or `{ plant, notes }`. */
export function readProposedPlant(raw: unknown): { plant: IPlant[]; notes: string[] } | undefined {
	if (Array.isArray(raw)) {
		raw = { plant: raw };
	}
	if (!isRecord(raw)) {
		return undefined;
	}
	const plant = records<IPlant>(raw.plant).filter(p => typeof p.kind === 'string').map(p => ({
		...p, id: typeof p.id === 'string' ? p.id : '', story: typeof p.story === 'string' ? p.story : '', x: num(p.x), y: num(p.y),
	}));
	return { plant, notes: [...strings(raw.notes), ...problemsOf(raw)] };
}

/** Merges the proposed plant into the file: one edit; see {@link mergeProposals}. */
export function mergeProposedPlant(document: IMep, proposals: readonly IPlant[]): IPlant[] {
	const hvac = ensureHvac(document);
	return mergeProposals(hvac.plant, proposals, PLANT_SIZE_KEYS, () => allIds(document), 'AC');
}

// ───────────────────────────── checks ─────────────────────────────

/** What is missing or inconsistent in the HVAC section (the contract's rules), as problems with dotted paths. */
/** `cities`, `uses`: the backend's Tables 8.2.2 and 8.2.3 ({@link HVAC_TABLES_COMMAND}); empty until they arrive, when the keys are not checked. */
export function checkHvac(document: IMep, context: IMepContext, cities: readonly IHvacCity[] = [], uses: readonly IHvacUse[] = []): IMepProblem[] {
	const hvac = hvacOf(document);
	if (!hvac) {
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
			add(path, 'error', localize('hvac.p.noId', "An item of the HVAC has no ID."));
		} else if (idError(id)) {
			add(path, 'error', localize('hvac.p.badId', "The ID '{0}' is not valid: {1}", id, idError(id)));
		} else if (repeated.has(id)) {
			add(path, 'error', localize('hvac.p.duplicate', "The ID {0} is used twice.", id));
		}
	};
	const positive = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && value > 0);
	const nonNegative = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && value >= 0);

	if (hvac.system !== undefined && !(HVAC_SYSTEMS as readonly unknown[]).includes(hvac.system)) {
		add('hvac.system', 'error', localize('hvac.p.system', "The system must be one of {0}.", HVAC_SYSTEMS.join(', ')));
	}
	const design = hvac.design;
	if (design.city !== undefined && cities.length && !cities.some(c => c.key === design.city)) {
		add('hvac.design.city', 'warning', localize('hvac.p.city', "'{0}' is not a station of BNBC Table 8.2.2; give the outdoor conditions yourself.", String(design.city)));
	}
	for (const key of ['outdoorDB', 'outdoorWB', 'indoorDB'] as const) {
		const v = design[key];
		if (v !== undefined && !(typeof v === 'number' && v > 0 && v < 60)) {
			add(`hvac.design.${key}`, 'error', localize('hvac.p.temperature', "A design temperature must be between 0 and 60 °C."));
		}
	}
	if (typeof design.outdoorWB === 'number' && typeof design.outdoorDB === 'number' && design.outdoorWB > design.outdoorDB) {
		add('hvac.design.outdoorWB', 'error', localize('hvac.p.wetBulb', "The outdoor wet bulb cannot be above the dry bulb."));
	}
	if (design.indoorRH !== undefined && !(typeof design.indoorRH === 'number' && design.indoorRH > 0 && design.indoorRH < 100)) {
		add('hvac.design.indoorRH', 'error', localize('hvac.p.rh', "The indoor relative humidity must be between 0 and 100 %."));
	}
	if (!positive(design.dailyRange)) {
		add('hvac.design.dailyRange', 'error', localize('hvac.p.range', "The daily range must be above 0, or left empty for the table's."));
	}
	const envelope = hvac.envelope;
	for (const key of ['uWall', 'uRoof', 'uGlazing'] as const) {
		if (!positive(envelope[key])) {
			add(`hvac.envelope.${key}`, 'error', localize('hvac.p.u', "A U-value must be above 0, or left empty for the construction's."));
		}
	}
	if (envelope.shgc !== undefined && !(typeof envelope.shgc === 'number' && envelope.shgc > 0 && envelope.shgc < 1)) {
		add('hvac.envelope.shgc', 'error', localize('hvac.p.shgc', "The solar heat gain coefficient must be between 0 and 1."));
	}
	if (envelope.shading !== undefined && !(SHADINGS as readonly unknown[]).includes(envelope.shading)) {
		add('hvac.envelope.shading', 'error', localize('hvac.p.shading', "The shading must be none, overhang or blinds."));
	}

	hvac.stories.forEach((row, i) => {
		const path = (field: string) => `hvac.stories.${i}.${field}`;
		if (!known(row.story)) {
			add(path('story'), 'error', localize('hvac.p.rowStory', "HVAC: the building model has no story '{0}'.", String(row.story ?? '')));
		} else if (hvac.stories.findIndex(s => s.story === row.story) < i) {
			add(path('story'), 'error', localize('hvac.p.rowTwice', "HVAC: story {0} is listed twice.", row.story));
		}
		if (row.use !== undefined && uses.length && !uses.some(u => u.key === row.use)) {
			add(path('use'), 'warning', localize('hvac.p.use', "{0}: '{1}' is not a use of BNBC Table 8.2.3.", row.story, String(row.use)));
		}
		if (row.occupants !== undefined && !(Number.isInteger(row.occupants) && row.occupants >= 0)) {
			add(path('occupants'), 'error', localize('hvac.p.occupants', "{0}: the occupants must be a whole number, 0 or more.", row.story));
		}
		for (const key of ['lighting', 'equipment'] as const) {
			if (!nonNegative(row[key])) {
				add(path(key), 'error', localize('hvac.p.density', "{0}: the {1} density cannot be negative.", row.story, key));
			}
		}
		for (const facade of FACADES) {
			const ratio = row.glazing?.[facade];
			if (ratio !== undefined && !(typeof ratio === 'number' && ratio >= 0 && ratio <= 0.9)) {
				add(path(`glazing.${facade}`), 'error', localize('hvac.p.wwr', "{0}: the window-to-wall ratio of the {1} facade must be between 0 and 0.9.", row.story, facade));
			}
		}
	});

	hvac.plant.forEach((p, i) => {
		const path = (field: string) => `hvac.plant.${i}.${field}`;
		checkId(path('id'), p.id);
		if (!(PLANT_KINDS as readonly unknown[]).includes(p.kind)) {
			add(path('kind'), 'error', localize('hvac.p.kind', "{0}: '{1}' is not a kind of plant ({2}).", p.id, String(p.kind), PLANT_KINDS.join(', ')));
		}
		if (!known(p.story)) {
			add(path('story'), 'error', localize('hvac.p.plantStory', "{0}: the building model has no story '{1}'.", p.id, String(p.story ?? '')));
		}
		for (const key of ['length', 'width', 'height', 'capacity'] as const) {
			if (!positive(p[key])) {
				add(path(key), 'error', localize('hvac.p.plantPositive', "{0}: the {1} must be above 0, or left empty.", p.id, key));
			}
		}
		if (p.operatingWeight === undefined) {
			add(path('operatingWeight'), 'warning', localize('hvac.p.weight', "{0}: give its operating weight from the supplier (or let SAEngine propose the plant): it loads the floor.", p.id));
		} else if (!positive(p.operatingWeight)) {
			add(path('operatingWeight'), 'error', localize('hvac.p.weightPositive', "{0}: the operating weight must be above 0.", p.id));
		}
		for (const story of p.serves ?? []) {
			if (!known(story)) {
				add(path('serves'), 'error', localize('hvac.p.serves', "{0}: it serves story '{1}', which the building model does not have.", p.id, String(story)));
			}
		}
	});

	const shafts = new Set(document.shafts.map(s => s.id));
	hvac.ducts.forEach((d, i) => {
		const path = (field: string) => `hvac.ducts.${i}.${field}`;
		checkId(path('id'), d.id);
		if (!(DUCT_SYSTEMS as readonly unknown[]).includes(d.system)) {
			add(path('system'), 'error', localize('hvac.p.ductSystem', "{0}: '{1}' is not a duct system ({2}).", d.id, String(d.system), DUCT_SYSTEMS.join(', ')));
		}
		if (!(DUCT_SHAPES as readonly unknown[]).includes(d.shape)) {
			add(path('shape'), 'error', localize('hvac.p.ductShape', "{0}: the shape must be rect or round.", d.id));
		} else if (d.shape === 'round' ? !(num(d.diameter) > 0) : !(num(d.width) > 0 && num(d.height) > 0)) {
			add(path(d.shape === 'round' ? 'diameter' : 'width'), 'error', d.shape === 'round'
				? localize('hvac.p.ductDiameter', "{0}: give the round duct's diameter.", d.id)
				: localize('hvac.p.ductSize', "{0}: give the duct's width and height.", d.id));
		}
		if (!known(d.story)) {
			add(path('story'), 'error', localize('hvac.p.ductStory', "{0}: the building model has no story '{1}'.", d.id, String(d.story ?? '')));
		}
		if (d.riser) {
			for (const end of ['fromStory', 'toStory'] as const) {
				if (!known(d.riser[end])) {
					add(path(`riser.${end}`), 'error', localize('hvac.p.riserStory', "{0}: the building model has no story '{1}'.", d.id, String(d.riser[end] ?? '')));
				}
			}
			const from = elevation(d.riser.fromStory);
			const to = elevation(d.riser.toStory);
			if (from !== undefined && to !== undefined && to <= from) {
				add(path('riser.toStory'), 'error', localize('hvac.p.riserOrder', "{0}: its top story must be above the story it starts at.", d.id));
			}
			if (!d.path.length) {
				add(path('path'), 'error', localize('hvac.p.riserPoint', "{0}: a riser duct needs its plan position.", d.id));
			}
		} else if (d.path.length < 2) {
			add(path('path'), 'error', localize('hvac.p.path', "{0}: a duct run needs at least two points.", d.id));
		}
		if (d.shaft && !shafts.has(d.shaft)) {
			add(path('shaft'), 'error', localize('hvac.p.shaft', "{0}: there is no shaft '{1}'.", d.id, d.shaft));
		}
		if (d.bottom !== undefined && !(typeof d.bottom === 'number' && d.bottom >= 0)) {
			add(path('bottom'), 'error', localize('hvac.p.bottom', "{0}: the underside above the floor cannot be negative.", d.id));
		}
		const levels = d.riser ? undefined : ductLevels(d, context);
		const story = context.stories.find(s => s.id === d.story);
		if (levels && story && levels.bottom < story.elevation) {
			add(path('height'), 'warning', localize('hvac.p.tooDeep', "{0}: the duct is deeper than the story is high.", d.id));
		}
		if (!positive(d.flow)) {
			add(path('flow'), 'error', localize('hvac.p.flow', "{0}: the airflow must be above 0, or left empty.", d.id));
		}
	});
	return problems;
}

// ───────────────────────────── the backend's report ─────────────────────────────

/*
 * `saengine.hvac.report` answers H1's report (python/src/saengine/hvac/): `{ engine, loads:
 * { stories: [...], total }, airflow, ducts, plant, openings, shafts, checks, summary, notes,
 * problems, method }`; every part is read defensively and a missing one leaves its section out.
 * Loads are in kW (W/m² for the density), airflow in m³/s, areas in m².
 */

export interface IStoryLoadRow {
	readonly story: string;
	/** Conditioned floor area [m²]. */
	readonly area?: number;
	/** [kW] */
	readonly sensible?: number;
	readonly latent?: number;
	readonly total?: number;
	/** [W/m²] */
	readonly density?: number;
	/** Supply and outdoor air [m³/s]. */
	readonly supply?: number;
	readonly freshAir?: number;
	readonly exhaust?: number;
	readonly note?: string;
}

export interface IHvacItemResult {
	readonly id: string;
	readonly kind?: string;
	readonly system?: string;
	/** What it carries or gives: the flow [m³/s] of a duct, the capacity of a plant item. */
	readonly load?: number;
	readonly required?: number;
	readonly provided?: number;
	readonly unit?: string;
	/** A duct's velocity [m/s]. */
	readonly velocity?: number;
	/** The size the backend gives ("600 × 300"). */
	readonly size?: string;
	/** [kN] */
	readonly weight?: number;
	readonly utilisation?: number;
	readonly status: CheckStatus;
	readonly note?: string;
}

export interface IOpeningResult {
	readonly id: string;
	readonly host?: string;
	readonly duct?: string;
	readonly size?: string;
	readonly check?: string;
	readonly utilisation?: number;
	readonly status: CheckStatus;
	readonly note?: string;
	/** An opening the backend proposes and the file lacks. */
	readonly proposed?: IOpening;
}

export interface IShaftResult {
	readonly id: string;
	/** [m²] */
	readonly required?: number;
	readonly provided?: number;
	readonly status: CheckStatus;
	readonly note?: string;
}

export interface IHvacReport {
	/** "EnergyPlus version 26.2.0", or "estimate". */
	readonly engine: string;
	readonly estimate: boolean;
	readonly summary: readonly string[];
	readonly stories: readonly IStoryLoadRow[];
	readonly total?: { readonly sensible?: number; readonly latent?: number; readonly total?: number; readonly area?: number; readonly supply?: number; readonly freshAir?: number };
	/** The total in tons of refrigeration, as the backend converts it. */
	readonly tons?: number;
	/** EnergyPlus's coincident peak of all zones [kW] (for central plant); the total is the sum of the zones' own peaks. */
	readonly coincident?: number;
	/** When the coincident peak occurs ("21/5 15:00"). */
	readonly peak?: string;
	readonly ducts: readonly IHvacItemResult[];
	readonly plant: readonly IHvacItemResult[];
	readonly openings: readonly IOpeningResult[];
	readonly shafts: readonly IShaftResult[];
	readonly checks: readonly IMepCheck[];
	readonly notes: readonly string[];
	readonly problems: readonly string[];
	readonly method: readonly string[];
	/** When the loads ran (ISO), for the engine line. */
	readonly computed?: string;
	/** False when EnergyPlus is there but has not run for this input (the estimate is shown): run Calculate Loads. */
	readonly calculated?: boolean;
	/** Whether the backend found EnergyPlus (undefined: it did not say); without it Calculate Loads gives the estimate. */
	readonly energyPlusFound?: boolean;
	/** The Table 8.2.2 station the loads used (entered, else the nearest to the site of Project Settings). */
	readonly station?: string;
	/** Openings of 7 MEP (`HD-`, `HR-`) no duct crosses any more: the engineer removes them. */
	readonly stale: readonly string[];
}

function sizeText(item: Record<string, unknown>): string | undefined {
	const text = optionalString(item.size);
	if (text) {
		return text;
	}
	if (isRecord(item.size)) {
		return sizeText(item.size);
	}
	const w = optionalNumber(item.width);
	const h = optionalNumber(item.height);
	const d = optionalNumber(item.diameter);
	return w !== undefined && h !== undefined ? `${Math.round(w)} × ${Math.round(h)}` : d !== undefined ? `Ø${Math.round(d)}` : undefined;
}

function readItem(item: Record<string, unknown>): IHvacItemResult {
	return {
		id: String(item.id ?? ''), kind: optionalString(item.kind), system: optionalString(item.system),
		load: optionalNumber(item.flow ?? item.load ?? item.capacity), required: optionalNumber(item.required), provided: optionalNumber(item.provided ?? item.capacity),
		unit: optionalString(item.unit), velocity: optionalNumber(item.velocity), size: sizeText(item), weight: optionalNumber(item.operatingWeight ?? item.weight),
		utilisation: optionalNumber(item.utilisation), status: statusOf(item), note: noteOf(item),
	};
}

/** The check of a list that governs: the highest utilisation of those that are not flags. */
function governing(checks: unknown): { name?: string; utilisation?: number; note?: string } {
	let best: Record<string, unknown> | undefined;
	for (const c of records<Record<string, unknown>>(checks)) {
		if (c.flag === true || optionalNumber(c.utilisation) === undefined) {
			continue;
		}
		if (!best || num(c.utilisation) > num(best.utilisation)) {
			best = c;
		}
	}
	return best ? { name: optionalString(best.name), utilisation: optionalNumber(best.utilisation), note: noteOf(best) } : {};
}

function isOpening(value: unknown): value is IOpening {
	return isRecord(value) && typeof value.id === 'string' && typeof value.host === 'string';
}

/**
 * The openings of a backend report. The backends (`hvac.openings.duct_openings`, `hvac.air.hvac_air`,
 * `electrical.risers`) give `openings` as the proposed 07 MEP openings that pass their checks (each one
 * not in the file yet) and `conflicts` as the crossings no checked opening can pass
 * (`{ duct | tray, beam, opening: <the 07 MEP opening tried>, checks, notes, options }`); a crossing
 * through an opening of the file is `ok`. A row with its own `ok` / `status` / `utilisation` is read as is.
 */
export function readOpeningResults(value: unknown, conflicts?: unknown): IOpeningResult[] {
	const passing = records<Record<string, unknown>>(value).map(o => {
		const check = governing(o.checks);
		const proposed = isOpening(o.opening) ? o.opening : isOpening(o) && isRecord(o.position) ? o as unknown as IOpening : undefined;
		const explicit = o.status !== undefined || typeof o.ok === 'boolean' || optionalNumber(o.utilisation) !== undefined;
		return {
			id: String(o.id ?? proposed?.id ?? ''), host: optionalString(o.host ?? o.beam), duct: optionalString(o.duct ?? o.tray ?? o.riser ?? o.service), size: sizeText(isRecord(o.opening) ? o.opening : o),
			check: optionalString(o.check ?? o.governing) ?? check.name, utilisation: optionalNumber(o.utilisation) ?? check.utilisation,
			status: explicit ? statusOf(o) : 'ok' as CheckStatus, note: noteOf(o), proposed,
		};
	});
	const failing = records<Record<string, unknown>>(conflicts).map(c => {
		const tried = record(c.opening);
		const check = governing(c.checks);
		const notes = [...strings(c.notes), ...(check.note ? [check.note] : []), ...records<Record<string, unknown>>(c.options).map(o => optionalString(o.option ?? o.name ?? o.note) ?? '').filter(Boolean)];
		return {
			id: String(tried.id ?? c.existing ?? `${c.duct ?? c.tray ?? ''}-${c.beam ?? ''}`), host: optionalString(c.beam ?? tried.host), duct: optionalString(c.duct ?? c.tray ?? c.riser),
			size: sizeText(tried), check: check.name, utilisation: check.utilisation, status: 'fail' as CheckStatus, note: notes.join('; ') || undefined,
		};
	});
	return [...passing, ...failing];
}

/** Shafts: `{ id, need | required, area | provided (m²), ok }` (`hvac.air.shaft_needs`). */
export function readShaftResults(value: unknown): IShaftResult[] {
	return records<Record<string, unknown>>(value).map(s => ({
		id: String(s.id ?? s.shaft ?? s.story ?? ''), required: optionalNumber(s.need ?? s.required ?? s.requiredArea), provided: optionalNumber(s.area ?? s.provided),
		status: statusOf(s), note: noteOf(s),
	}));
}

/** The engine line's text: the EnergyPlus version, else an estimate. */
export function engineOf(raw: Record<string, unknown>): { engine: string; estimate: boolean } {
	const engine = optionalString(raw.engine) ?? optionalString(record(raw.loads).engine) ?? '';
	const estimate = !engine || /estimat/i.test(engine) || raw.estimate === true;
	return { engine: engine || 'estimate', estimate };
}

/** A story's exhaust [m³/s]: a number, or `hvac.air.story_exhaust`'s `{ toilet, kitchen, general }`. */
function exhaustOf(value: unknown): number | undefined {
	if (isRecord(value)) {
		const parts = [value.toilet, value.kitchen, value.general].map(optionalNumber).filter((n): n is number => n !== undefined);
		return parts.length ? parts.reduce((s, n) => s + n, 0) : undefined;
	}
	return optionalNumber(value);
}

/**
 * The backend's HVAC report, read defensively; undefined when it is not one. It reads H1's answers
 * as they are: the load calculation (`hvac.report.hvac_loads`: `{ engine, zones: [{ story, area,
 * sensible, latent, total (kW), density (W/m²), supply | airflow, freshAir | outdoorAir (m³/s) }],
 * total, sensible, latent, airflow, outdoorAir (numbers), building: { total, month, day, time }?,
 * notes, problems, method }`) and the air side (`hvac.air.hvac_air`: `{ zones: [{ story, airflow,
 * outdoorAir, exhaust: { toilet, kitchen, general } }], ducts: [{ id, system, flow, size: { shape,
 * width, height | diameter }, velocity, ok, note }], shafts: [{ id, area, need, ok }], plant (the
 * proposed 07 MEP plant), openings, conflicts, checks, notes, problems }`), either merged at the top
 * level, or the loads at the top and the air side under `air`, or each under `loads` / `air`.
 */
export function readHvacReport(raw: unknown): IHvacReport | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const loads = isRecord(raw.loads) ? raw.loads : raw;
	const air = isRecord(raw.air) ? raw.air : raw;
	const airRows = new Map(records<Record<string, unknown>>(air.zones).map(r => [String(r.story ?? ''), r]));
	const loadRows = records<Record<string, unknown>>(loads.zones);
	const rows = [...loadRows, ...[...airRows.values()].filter(r => !loadRows.some(l => l.story === r.story) && optionalNumber(r.total) !== undefined)];
	const stories: IStoryLoadRow[] = rows.map(r => {
		const story = String(r.story ?? '');
		const flow = airRows.get(story) ?? r;
		const area = optionalNumber(r.area);
		const total = optionalNumber(r.total) ?? (optionalNumber(r.sensible) !== undefined ? num(r.sensible) + num(r.latent) : undefined);
		return {
			story, area, sensible: optionalNumber(r.sensible), latent: optionalNumber(r.latent), total,
			density: optionalNumber(r.density) ?? (total !== undefined && area ? total * 1000 / area : undefined),
			supply: optionalNumber(flow.airflow ?? flow.supply ?? r.supply), freshAir: optionalNumber(flow.outdoorAir ?? flow.freshAir ?? r.freshAir), exhaust: exhaustOf(flow.exhaust), note: noteOf(r),
		};
	});
	const sum = (key: 'sensible' | 'latent' | 'total' | 'area' | 'supply' | 'freshAir') => stories.some(s => s[key] !== undefined) ? stories.reduce((s, r) => s + num(r[key]), 0) : undefined;
	// The loads' own totals; the air side's supply where it raised a zone's to its outdoor air.
	const airSupply = airRows.size ? sum('supply') : undefined;
	const building = record(loads.building);
	const peak = optionalNumber(building.total) !== undefined
		? [building.day !== undefined && building.month !== undefined ? `${building.day}/${building.month}` : '', optionalString(building.time) ?? ''].filter(Boolean).join(' ') || undefined
		: undefined;
	const checksByName = new Map(readChecks(air.checks).map(c => [c.name, c]));
	const { engine, estimate } = engineOf(raw);
	const stale = strings(air.stale);
	const notes = [...strings(loads.notes), ...(air !== loads ? strings(air.notes) : [])];
	if (stale.length) {
		notes.push(localize('hvac.staleOpenings', "Openings no duct crosses any more (remove them from the openings): {0}", stale.join(', ')));
	}
	const problems = [...strings(loads.problems), ...(air !== loads ? strings(air.problems) : [])];
	return {
		engine, estimate, energyPlusFound: typeof loads.energyPlusFound === 'boolean' ? loads.energyPlusFound : undefined,
		station: optionalString(record(loads.design).station),
		summary: strings(raw.summary),
		stories,
		total: {
			sensible: optionalNumber(loads.sensible) ?? sum('sensible'), latent: optionalNumber(loads.latent) ?? sum('latent'),
			total: optionalNumber(loads.total) ?? sum('total'), area: sum('area'),
			supply: airSupply ?? optionalNumber(loads.airflow) ?? sum('supply'), freshAir: optionalNumber(loads.outdoorAir) ?? sum('freshAir'),
		},
		tons: optionalNumber(loads.tons),
		coincident: optionalNumber(building.total),
		peak,
		ducts: records<Record<string, unknown>>(air.ducts).map(d => {
			const item = readItem(d);
			const velocity = checksByName.get(`Duct ${item.id} velocity`);
			return { ...item, utilisation: item.utilisation ?? velocity?.utilisation };
		}),
		plant: records<Record<string, unknown>>(air.plant).map(readItem),
		openings: readOpeningResults(air.openings, air.conflicts),
		shafts: readShaftResults(air.shafts),
		checks: [...(air !== loads ? readChecks(loads.checks) : []), ...readChecks(air.checks)],
		notes: [...new Set(notes)],
		problems: [...new Set(problems)],
		method: [...strings(loads.method), ...(air !== loads ? strings(air.method) : [])],
		computed: optionalString(loads.computed ?? raw.computed),
		calculated: typeof loads.calculated === 'boolean' ? loads.calculated : undefined,
		stale,
	};
}

/**
 * What a report's failures are counted from: its checks, which already hold the ducts' velocities,
 * the shafts' areas, the openings' conflicts and the plant's checks (each counted once); the
 * ducts, plant, openings and shafts themselves only when the report has no checks.
 */
function verdicts(report: IHvacReport): readonly { readonly status: CheckStatus }[] {
	return report.checks.length ? report.checks : [...report.ducts, ...report.plant, ...report.openings, ...report.shafts];
}

/** The HVAC's failures in a report. */
export function hvacFailures(report: IHvacReport): number {
	return verdicts(report).filter(c => c.status === 'fail').length;
}

export function hvacWorst(report: IHvacReport): CheckStatus {
	return worst(verdicts(report).map(c => c.status));
}

/** The status line: "VRF · 2 plant · 1 duct · 1 crossing without an opening · 2 checks fail". */
export function hvacSummary(document: IMep, context: IMepContext, report: IHvacReport | undefined): string {
	const hvac = hvacOf(document);
	if (!hvac) {
		return localize('hvac.sum.none', "No HVAC yet");
	}
	const parts: string[] = [];
	if (hvac.system) {
		parts.push(hvacSystemLabel(String(hvac.system)));
	}
	const n = (count: number, one: string, many: string) => parts.push(count === 1 ? one : many);
	n(hvac.plant.length, localize('hvac.sum.plantOne', "1 plant item"), localize('hvac.sum.plant', "{0} plant items", hvac.plant.length));
	n(hvac.ducts.length, localize('hvac.sum.ductOne', "1 duct"), localize('hvac.sum.ducts', "{0} ducts", hvac.ducts.length));
	const open = allCrossings(document, context).filter(c => !c.opening).length;
	if (open) {
		n(open, localize('hvac.sum.crossingOne', "1 beam crossing without an opening"), localize('hvac.sum.crossings', "{0} beam crossings without an opening", open));
	}
	if (report) {
		if (report.total?.total !== undefined) {
			parts.push(localize('hvac.sum.load', "{0} kW cooling", report.total.total.toFixed(0)));
		}
		const failed = hvacFailures(report);
		if (failed) {
			n(failed, localize('hvac.sum.fail', "1 check fails"), localize('hvac.sum.fails', "{0} checks fail", failed));
		}
	}
	return parts.join(' · ');
}

/** The HVAC part of the part list's summary (`mep.results/summary.json`, key `hvac`). */
export interface IHvacSummary {
	readonly plant: number;
	readonly ducts: number;
	/** [kW] */
	readonly cooling?: number;
	readonly engine: string;
	readonly failed: number;
}

export function hvacSummaryFile(document: IMep, report: IHvacReport): IHvacSummary {
	const hvac = hvacOf(document);
	return { plant: hvac?.plant.length ?? 0, ducts: hvac?.ducts.length ?? 0, ...(report.total?.total !== undefined ? { cooling: report.total.total } : {}), engine: report.engine, failed: hvacFailures(report) };
}

/** The plant's operating weights per story [kN], summed from the file. */
export function plantWeights(document: IMep): Map<string, number> {
	const weights = new Map<string, number>();
	for (const p of hvacOf(document)?.plant ?? []) {
		weights.set(p.story, (weights.get(p.story) ?? 0) + num(p.operatingWeight));
	}
	return weights;
}

/** The plant's plan points of `story`, for the plan's extent. */
export function hvacExtent(document: IMep, context: IMepContext, story: string): Point[] {
	const hvac = hvacOf(document);
	if (!hvac) {
		return [];
	}
	return [
		...hvac.plant.filter(p => p.story === story).flatMap(plantOutline),
		...hvac.ducts.filter(d => ductOnStory(d, context, story)).flatMap(d => d.riser ? d.path.slice(0, 1) : d.path),
	];
}

/** The equipment footprint of a plant item, for the shared placement and pressure helpers. */
export function plantAsEquipment(plant: IPlant): IEquipment {
	return { id: plant.id, kind: 'other', story: plant.story, x: num(plant.x), y: num(plant.y), length: num(plant.length, 1000), width: num(plant.width, 1000), operatingWeight: num(plant.operatingWeight) };
}
