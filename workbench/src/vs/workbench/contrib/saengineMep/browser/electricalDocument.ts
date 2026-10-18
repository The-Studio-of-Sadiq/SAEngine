/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { EQUIPMENT_PRESETS, idError, IMep, IMepContext, IMepProblem, newEquipment, nextId, Point, shaftOnStory, storyExtent } from './mepDocument.js';
import {
	CheckStatus, duplicates, IMepCheck, isPoint, isRecord, mergeProposals, noteOf, num, optionalNumber, optionalString, problemsOf, readChecks, record, recordList, records, roofStory,
	statusOf, storyBetween, storyFloorArea, strings, worst,
} from './mepRead.js';
import { footprintsOn, IOpeningResult, IShaftResult, readOpeningResults, readShaftResults } from './hvacDocument.js';
import { allIds } from './plumbingDocument.js';

/*
 * The electrical section of the MEP part (`electrical` in `07 MEP/mep.json`), as the structural
 * engineer coordinates it: the demand of each storey (for the substation, the generator and the
 * rooms they need), the equipment (transformers, generators, fuel tanks, batteries: their weight
 * on the floors, the vibrating ones), the rising mains and cable trays (their openings and
 * shafts), and the lightning protection through the structure (the columns whose bars are the
 * down conductors, the foundation earthing). The backend sizes and checks them
 * (`saengine.electrical.*`); this module reads and writes the section, checks it against the
 * building, and reads the backend's answers defensively. It holds no UI.
 */

/** The report: demand, sources, rooms, risers, trays, lightning, openings: `{ projectRoot, mepText }`. */
export const ELECTRICAL_REPORT_COMMAND = 'saengine.electrical.report';
/** The equipment the backend proposes (transformer, generator, UPS...): `{ projectRoot, mepText }` → `{ equipment, notes }`. */
export const ELECTRICAL_PROPOSE_COMMAND = 'saengine.electrical.proposeEquipment';
/** The openings the risers and trays need through slabs, beams and walls: `{ projectRoot, mepText }` → `{ openings, notes }`. */
export const ELECTRICAL_OPENINGS_COMMAND = 'saengine.electrical.openings';
/** The occupancies the backend knows (optional): `[{ key, label, nonAc, ac, source }]` (BNBC Table 8.1.17). */
export const ELECTRICAL_USES_COMMAND = 'saengine.electrical.uses';

export type Voltage = '11kV' | '33kV' | '0.4kV';
export const VOLTAGES: readonly Voltage[] = ['0.4kV', '11kV', '33kV'];

export type ElecKind = 'transformer' | 'switchgear' | 'lvPanel' | 'generator' | 'fuelTank' | 'ups' | 'battery' | 'capacitorBank' | 'distributionBoard' | 'solarPv';
export const ELEC_KINDS: readonly ElecKind[] = ['transformer', 'switchgear', 'lvPanel', 'generator', 'fuelTank', 'ups', 'battery', 'capacitorBank', 'distributionBoard', 'solarPv'];

export type ElecRiserKind = 'busbar' | 'cableTray' | 'cableLadder' | 'conduitBank';
export const ELEC_RISER_KINDS: readonly ElecRiserKind[] = ['busbar', 'cableTray', 'cableLadder', 'conduitBank'];

export type LightningLevel = 'I' | 'II' | 'III' | 'IV';
export const LIGHTNING_LEVELS: readonly LightningLevel[] = ['I', 'II', 'III', 'IV'];

export type DownConductors = 'structuralRebar' | 'dedicated';
export const DOWN_CONDUCTORS: readonly DownConductors[] = ['structuralRebar', 'dedicated'];

export type Earthing = 'foundation' | 'rods' | 'ring';
export const EARTHINGS: readonly Earthing[] = ['foundation', 'rods', 'ring'];

export interface IElecSupply {
	utility?: string;
	voltage?: Voltage | string;
	generator?: boolean;
	ups?: boolean;
	[key: string]: unknown;
}

export interface IElecStory {
	story: string;
	/** A key of BNBC Table 8.1.17. */
	use?: string;
	/** [W/m²] */
	lighting?: number;
	power?: number;
	/** [kW] */
	other?: number;
	[key: string]: unknown;
}

export interface IElecEquipment {
	id: string;
	kind: ElecKind | string;
	story: string;
	x: number;
	y: number;
	length?: number;
	width?: number;
	height?: number;
	/** kVA, kW, kVAr, kWh or L by kind ({@link ratingUnit}). */
	rating?: number;
	/** [kN] */
	operatingWeight?: number;
	vibrating?: boolean;
	sized?: boolean;
	[key: string]: unknown;
}

export interface IElecRiser {
	id: string;
	kind: ElecRiserKind | string;
	x: number;
	y: number;
	/** Plan size [mm]. */
	width?: number;
	depth?: number;
	fromStory: string;
	toStory: string;
	shaft?: string;
	[key: string]: unknown;
}

export interface ITray {
	id: string;
	story: string;
	path: Point[];
	width: number;
	height: number;
	/** Underside above the story's floor [mm]; else just below the slab soffit. */
	bottom?: number;
	[key: string]: unknown;
}

export interface ILightning {
	enabled: boolean;
	level?: LightningLevel | string;
	downConductors?: DownConductors | string;
	earthing?: Earthing | string;
	/** Air terminals [x, y, z] mm; else the backend proposes them. */
	airTerminals?: [number, number, number][];
	[key: string]: unknown;
}

export interface IElectrical {
	supply: IElecSupply;
	stories: IElecStory[];
	equipment: IElecEquipment[];
	risers: IElecRiser[];
	trays: ITray[];
	lightning: ILightning;
	[key: string]: unknown;
}

function isPoint3(value: unknown): value is [number, number, number] {
	return Array.isArray(value) && value.length >= 2 && value.slice(0, 3).every(v => typeof v === 'number');
}

/** Fills in what an electrical section lacks, in place, keeping unknown fields; undefined when it is not an object. */
export function normalizeElectrical(value: unknown): IElectrical | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const electrical = value as IElectrical;
	electrical.supply = isRecord(electrical.supply) ? electrical.supply : {};
	electrical.stories = recordList<IElecStory>(electrical.stories);
	electrical.equipment = recordList<IElecEquipment>(electrical.equipment);
	electrical.risers = recordList<IElecRiser>(electrical.risers);
	electrical.trays = recordList<ITray>(electrical.trays);
	for (const tray of electrical.trays) {
		tray.path = Array.isArray(tray.path) ? tray.path.filter(isPoint) : [];
	}
	electrical.lightning = isRecord(electrical.lightning) ? electrical.lightning as ILightning : { enabled: false };
	if (typeof electrical.lightning.enabled !== 'boolean') {
		electrical.lightning.enabled = !!electrical.lightning.enabled;
	}
	if (electrical.lightning.airTerminals !== undefined) {
		electrical.lightning.airTerminals = Array.isArray(electrical.lightning.airTerminals) ? electrical.lightning.airTerminals.filter(isPoint3) : [];
	}
	return electrical;
}

/** The electrical section, created (empty) on the first electrical edit. */
export function ensureElectrical(document: IMep): IElectrical {
	const existing = normalizeElectrical(document.electrical);
	if (existing) {
		return existing;
	}
	const electrical: IElectrical = { supply: {}, stories: [], equipment: [], risers: [], trays: [], lightning: { enabled: false } };
	document.electrical = electrical;
	return electrical;
}

export function electricalOf(document: IMep): IElectrical | undefined {
	return normalizeElectrical(document.electrical);
}

export function hasElectrical(document: IMep): boolean {
	const e = electricalOf(document);
	return !!e && (e.stories.length + e.equipment.length + e.risers.length + e.trays.length > 0 || e.lightning.enabled || !!e.supply.voltage);
}

// ───────────────────────────── labels ─────────────────────────────

export function elecKindLabel(kind: string): string {
	switch (kind) {
		case 'transformer': return localize('elec.kind.transformer', "Transformer");
		case 'switchgear': return localize('elec.kind.switchgear', "HT switchgear");
		case 'lvPanel': return localize('elec.kind.lvPanel', "LT panel");
		case 'generator': return localize('elec.kind.generator', "Generator");
		case 'fuelTank': return localize('elec.kind.fuelTank', "Fuel tank");
		case 'ups': return localize('elec.kind.ups', "UPS");
		case 'battery': return localize('elec.kind.battery', "Battery bank");
		case 'capacitorBank': return localize('elec.kind.capacitorBank', "Capacitor bank (PFI)");
		case 'distributionBoard': return localize('elec.kind.distributionBoard', "Distribution board");
		case 'solarPv': return localize('elec.kind.solarPv', "Solar PV array");
		default: return kind;
	}
}

export function elecLetters(kind: string): string {
	switch (kind) {
		case 'transformer': return 'TX';
		case 'switchgear': return 'HT';
		case 'lvPanel': return 'LT';
		case 'generator': return 'G';
		case 'fuelTank': return 'FT';
		case 'ups': return 'UPS';
		case 'battery': return 'BAT';
		case 'capacitorBank': return 'PFI';
		case 'distributionBoard': return 'DB';
		case 'solarPv': return 'PV';
		default: return '?';
	}
}

/** The unit of an equipment's rating by its kind. */
export function ratingUnit(kind: string): string {
	switch (kind) {
		case 'capacitorBank': return localize('elec.unit.kvar', "kVAr");
		case 'solarPv': return localize('elec.unit.kwp', "kWp");
		case 'battery': return localize('elec.unit.kwh', "kWh");
		case 'fuelTank': return localize('elec.unit.litre', "L");
		default: return localize('elec.unit.kva', "kVA");
	}
}

export function riserKindLabel(kind: string): string {
	switch (kind) {
		case 'busbar': return localize('elec.riser.busbar', "Busbar trunking (rising main)");
		case 'cableTray': return localize('elec.riser.cableTray', "Cable tray");
		case 'cableLadder': return localize('elec.riser.cableLadder', "Cable ladder");
		case 'conduitBank': return localize('elec.riser.conduitBank', "Conduit bank");
		default: return kind;
	}
}

export function riserLetters(kind: string): string {
	switch (kind) {
		case 'busbar': return 'BB';
		case 'cableTray': return 'CT';
		case 'cableLadder': return 'CL';
		case 'conduitBank': return 'CB';
		default: return '?';
	}
}

export function voltageLabel(voltage: string): string {
	switch (voltage) {
		case '0.4kV': return localize('elec.v.lv', "0.4 kV (LT connection)");
		case '11kV': return localize('elec.v.11', "11 kV (own substation)");
		case '33kV': return localize('elec.v.33', "33 kV (own substation)");
		default: return voltage;
	}
}

export function downConductorsLabel(value: string): string {
	return value === 'structuralRebar' ? localize('elec.dc.rebar', "Column reinforcement (bonded)") : value === 'dedicated' ? localize('elec.dc.dedicated', "Dedicated conductors") : value;
}

export function earthingLabel(value: string): string {
	switch (value) {
		case 'foundation': return localize('elec.earth.foundation', "Foundation earth electrode");
		case 'rods': return localize('elec.earth.rods', "Earth rods");
		case 'ring': return localize('elec.earth.ring', "Ring earth electrode");
		default: return value;
	}
}

// ───────────────────────────── BNBC Table 8.1.17 ─────────────────────────────

export interface IElecUse {
	readonly key: string;
	readonly label: string;
	/** Minimum unit load [W/m²] without and with air-conditioning. */
	readonly nonAc?: number;
	readonly ac?: number;
	readonly source?: string;
}

/**
 * The occupancies of BNBC 2020 Part 8 Table 8.1.17 (Minimum Load Densities, PDF part 2 pp. 766
 * and 767, Gazette pp. 4547 and 4548): the unit load without and with A/C. The keys are the
 * backend's (saengine.electrical.tables); its list ({@link ELECTRICAL_USES_COMMAND}) replaces this.
 */
export const STATIC_ELEC_USES: readonly IElecUse[] = [
	{ key: 'residenceSingle', label: localize('elec.use.single', "Residence: single family"), nonAc: 20, ac: 75, source: 'Table 8.1.17' },
	{ key: 'residenceMulti', label: localize('elec.use.multi', "Residence: multi-family (not hotels)"), nonAc: 20, ac: 75, source: 'Table 8.1.17' },
	{ key: 'hospital', label: localize('elec.use.hospital', "Hospitals"), nonAc: 32, ac: 80, source: 'Table 8.1.17' },
	{ key: 'hotel', label: localize('elec.use.hotel', "Hotels, apartment houses (no electric cooking)"), nonAc: 24, ac: 75, source: 'Table 8.1.17' },
	{ key: 'office', label: localize('elec.use.office', "Office and commercial multi-storeyed"), nonAc: 28, ac: 75, source: 'Table 8.1.17' },
	{ key: 'industrial', label: localize('elec.use.industrial', "Industrial (without the machines)"), nonAc: 16, source: 'Table 8.1.17' },
	{ key: 'departmentStore', label: localize('elec.use.departmentStore', "Departmental stores"), nonAc: 28, ac: 75, source: 'Table 8.1.17' },
	{ key: 'bank', label: localize('elec.use.bank', "Banks"), nonAc: 20, ac: 75, source: 'Table 8.1.17' },
	{ key: 'restaurant', label: localize('elec.use.restaurant', "Restaurants (no electric cooking)"), nonAc: 16, ac: 75, source: 'Table 8.1.17' },
	{ key: 'barber', label: localize('elec.use.barber', "Barber shops and beauty parlours"), nonAc: 32, ac: 75, source: 'Table 8.1.17' },
	{ key: 'school', label: localize('elec.use.school', "Schools and colleges"), nonAc: 12, ac: 70, source: 'Table 8.1.17' },
	{ key: 'parking', label: localize('elec.use.parking', "Parking area in commercial buildings"), nonAc: 4, source: 'Table 8.1.17' },
	{ key: 'warehouse', label: localize('elec.use.warehouse', "Warehouses, large storage areas"), nonAc: 2, source: 'Table 8.1.17' },
];

export function readElecUses(raw: unknown): IElecUse[] | undefined {
	const list = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.uses) ? raw.uses : undefined;
	if (!list) {
		return undefined;
	}
	const uses = list.filter(isRecord).map(o => {
		const key = typeof o.key === 'string' ? o.key : typeof o.id === 'string' ? o.id : '';
		return {
			key, label: typeof o.label === 'string' ? o.label : key, nonAc: optionalNumber(o.nonAc), ac: optionalNumber(o.ac), source: optionalString(o.source),
		};
	}).filter(o => o.key);
	return uses.length ? uses : undefined;
}

// ───────────────────────────── geometry and new items ─────────────────────────────

function round(value: number, step = 50): number {
	return Math.round(value / step) * step;
}

export function elecOutline(item: { x: number; y: number; length?: number; width?: number }): Point[] {
	const hx = Math.max(100, num(item.length, 1000)) / 2;
	const hy = Math.max(100, num(item.width, 1000)) / 2;
	const x = num(item.x);
	const y = num(item.y);
	return [[x - hx, y - hy], [x + hx, y - hy], [x + hx, y + hy], [x - hx, y + hy]];
}

export function riserOutline(riser: IElecRiser): Point[] {
	return elecOutline({ x: riser.x, y: riser.y, length: riser.width ?? 300, width: riser.depth ?? 200 });
}

export function elecRiserOnStory(riser: IElecRiser, context: IMepContext, storyId: string): boolean {
	return storyBetween(context, storyId, riser.fromStory, riser.toStory);
}

/** Typical footprints to start from [mm] (to edit to the supplier's data); the transformer and generator from the equipment presets. */
const ELEC_FOOTPRINT: { readonly [K in ElecKind]: readonly [number, number, number] } = {
	transformer: [0, 0, 0], generator: [0, 0, 0],
	switchgear: [2400, 1200, 2200], lvPanel: [3000, 1000, 2200], fuelTank: [2000, 1200, 1500], ups: [1200, 800, 1900], battery: [2000, 800, 1600],
	capacitorBank: [1200, 800, 2000], distributionBoard: [800, 300, 1200], solarPv: [6000, 4000, 300],
};

const ELEC_PREFIX: { readonly [K in ElecKind]: string } = {
	transformer: 'TX', switchgear: 'HT', lvPanel: 'LT', generator: 'GEN', fuelTank: 'FT', ups: 'UPS', battery: 'BAT', capacitorBank: 'PFI', distributionBoard: 'DB', solarPv: 'PV',
};

/** Kinds that stand in the substation or generator room on the lowest story; solar PV on the roof. */
const GROUND_KINDS: readonly string[] = ['transformer', 'switchgear', 'lvPanel', 'generator', 'fuelTank', 'capacitorBank'];

/**
 * A new electrical equipment of `kind`: the substation and generator kinds on the lowest story,
 * solar PV on the roof, the rest on `story`; at the free place nearest the middle of the floor
 * (the equipment's placement). Typical sizes; the weight of the transformer and generator from
 * the equipment presets, of the rest left for the supplier's data.
 */
export function newElecEquipment(document: IMep, context: IMepContext, kind: ElecKind, story: string | undefined): IElecEquipment {
	const target = GROUND_KINDS.includes(kind) ? context.stories[0]?.id ?? story : kind === 'solarPv' ? roofStory(context)?.id ?? story : story ?? context.stories[0]?.id;
	const preset = EQUIPMENT_PRESETS.find(p => p.kind === kind);
	const [length, width, height] = preset ? [preset.length, preset.width, preset.height] : ELEC_FOOTPRINT[kind];
	const equipment: IElecEquipment = {
		id: nextId(ELEC_PREFIX[kind], allIds(document)), kind, story: target ?? '', x: 0, y: 0, length, width, height, sized: false,
		...(preset ? { operatingWeight: preset.operatingWeight } : {}), ...(preset?.vibrating || kind === 'generator' ? { vibrating: true } : {}),
	};
	if (!target) {
		return equipment;
	}
	const placed = newEquipment({ ...document, equipment: footprintsOn(document, target) }, context, {
		kind: 'other', name: '', length, width, height, operatingWeight: 1, emptyWeight: 1,
	}, target);
	equipment.x = placed.x;
	equipment.y = placed.y;
	if (placed.rotation) {
		equipment.length = width;
		equipment.width = length;
	}
	return equipment;
}

/** Typical plan sizes of a riser to start from [mm]. */
const RISER_SIZE: { readonly [K in ElecRiserKind]: readonly [number, number] } = {
	busbar: [300, 200], cableTray: [600, 100], cableLadder: [600, 150], conduitBank: [300, 300],
};

/**
 * A new riser of `kind`: in the first shaft through `story` (by its side, set off by the risers
 * already there), else at the middle of the floor; from the lowest story to the top.
 */
export function newElecRiser(document: IMep, context: IMepContext, kind: ElecRiserKind, story: string): IElecRiser {
	const [width, depth] = RISER_SIZE[kind];
	const shaft = document.shafts.find(s => shaftOnStory(s, context, story) && s.outline.length >= 3);
	const count = (electricalOf(document)?.risers ?? []).length;
	let point: Point;
	if (shaft) {
		const xs = shaft.outline.map(p => p[0]);
		const ys = shaft.outline.map(p => p[1]);
		point = [round(Math.min(...xs) + width / 2 + 100 + (count % 2) * (width + 100)), round(Math.max(...ys) - depth / 2 - 100 - Math.floor(count / 2) * (depth + 100))];
	} else {
		const extent = storyExtent(context, story);
		const xs = extent.map(p => p[0]);
		const ys = extent.map(p => p[1]);
		point = extent.length ? [round((Math.min(...xs) + Math.max(...xs)) / 2 + count * 600), round((Math.min(...ys) + Math.max(...ys)) / 2)] : [0, 0];
	}
	return {
		id: nextId('ER', allIds(document)), kind, x: point[0], y: point[1], width, depth,
		fromStory: context.stories[0]?.id ?? story, toStory: context.stories[context.stories.length - 1]?.id ?? story, ...(shaft ? { shaft: shaft.id } : {}),
	};
}

/** A new cable tray on `story` along `path` (from the plan). */
export function newTray(document: IMep, story: string, path: Point[]): ITray {
	return { id: nextId('CT', allIds(document)), story, path: path.map(p => [round(p[0]), round(p[1])] as Point), width: 300, height: 100 };
}

/** The storey's row of the electrical table, created on the first edit. */
export function elecStoryRow(electrical: IElectrical, story: string): IElecStory {
	let row = electrical.stories.find(s => s.story === story);
	if (!row) {
		row = { story };
		electrical.stories.push(row);
	}
	return row;
}

const EQUIPMENT_SIZE_KEYS = ['kind', 'length', 'width', 'height', 'rating', 'operatingWeight', 'vibrating'] as const;

/** The equipment the backend proposes: a list, or `{ equipment, notes }`. */
export function readProposedEquipment(raw: unknown): { equipment: IElecEquipment[]; notes: string[] } | undefined {
	if (Array.isArray(raw)) {
		raw = { equipment: raw };
	}
	if (!isRecord(raw)) {
		return undefined;
	}
	const equipment = records<IElecEquipment>(raw.equipment).filter(e => typeof e.kind === 'string').map(e => ({
		...e, id: typeof e.id === 'string' ? e.id : '', story: typeof e.story === 'string' ? e.story : '', x: num(e.x), y: num(e.y),
	}));
	return { equipment, notes: [...strings(raw.notes), ...problemsOf(raw)] };
}

export function mergeProposedEquipment(document: IMep, proposals: readonly IElecEquipment[]): IElecEquipment[] {
	const electrical = ensureElectrical(document);
	return mergeProposals(electrical.equipment, proposals, EQUIPMENT_SIZE_KEYS, () => allIds(document), 'EL');
}

/**
 * The connected load of each storey from its densities and its floor area [kW], without any
 * diversity: what the editor shows without the backend. The demand is the backend's.
 */
export function connectedLoads(document: IMep, context: IMepContext): { story: string; area: number; lighting: number; power: number; other: number; total: number }[] {
	const electrical = electricalOf(document);
	return (electrical?.stories ?? []).map(row => {
		const area = storyFloorArea(context, row.story);
		const lighting = num(row.lighting) * area / 1000;
		const power = num(row.power) * area / 1000;
		const other = num(row.other);
		return { story: row.story, area, lighting, power, other, total: lighting + power + other };
	});
}

// ───────────────────────────── checks ─────────────────────────────

export function checkElectrical(document: IMep, context: IMepContext, uses: readonly IElecUse[] = STATIC_ELEC_USES): IMepProblem[] {
	const electrical = electricalOf(document);
	if (!electrical) {
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
			add(path, 'error', localize('elec.p.noId', "An item of the electrical services has no ID."));
		} else if (idError(id)) {
			add(path, 'error', localize('elec.p.badId', "The ID '{0}' is not valid: {1}", id, idError(id)));
		} else if (repeated.has(id)) {
			add(path, 'error', localize('elec.p.duplicate', "The ID {0} is used twice.", id));
		}
	};
	const positive = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && value > 0);
	const nonNegative = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && value >= 0);
	const shafts = new Set(document.shafts.map(s => s.id));

	if (electrical.supply.voltage !== undefined && !(VOLTAGES as readonly unknown[]).includes(electrical.supply.voltage)) {
		add('electrical.supply.voltage', 'error', localize('elec.p.voltage', "The supply voltage must be one of {0}.", VOLTAGES.join(', ')));
	}
	electrical.stories.forEach((row, i) => {
		const path = (field: string) => `electrical.stories.${i}.${field}`;
		if (!known(row.story)) {
			add(path('story'), 'error', localize('elec.p.rowStory', "Electrical: the building model has no story '{0}'.", String(row.story ?? '')));
		} else if (electrical.stories.findIndex(s => s.story === row.story) < i) {
			add(path('story'), 'error', localize('elec.p.rowTwice', "Electrical: story {0} is listed twice.", row.story));
		}
		if (row.use !== undefined && !uses.some(u => u.key === row.use)) {
			add(path('use'), 'warning', localize('elec.p.use', "{0}: '{1}' is not an occupancy of BNBC Table 8.1.17.", row.story, String(row.use)));
		}
		for (const key of ['lighting', 'power', 'other'] as const) {
			if (!nonNegative(row[key])) {
				add(path(key), 'error', localize('elec.p.load', "{0}: the {1} load cannot be negative.", row.story, key));
			}
		}
	});
	electrical.equipment.forEach((e, i) => {
		const path = (field: string) => `electrical.equipment.${i}.${field}`;
		checkId(path('id'), e.id);
		if (!(ELEC_KINDS as readonly unknown[]).includes(e.kind)) {
			add(path('kind'), 'error', localize('elec.p.kind', "{0}: '{1}' is not a kind of electrical equipment ({2}).", e.id, String(e.kind), ELEC_KINDS.join(', ')));
		}
		if (!known(e.story)) {
			add(path('story'), 'error', localize('elec.p.story', "{0}: the building model has no story '{1}'.", e.id, String(e.story ?? '')));
		}
		for (const key of ['length', 'width', 'height', 'rating'] as const) {
			if (!positive(e[key])) {
				add(path(key), 'error', localize('elec.p.positive', "{0}: the {1} must be above 0, or left empty.", e.id, key));
			}
		}
		if (e.operatingWeight === undefined) {
			add(path('operatingWeight'), 'warning', localize('elec.p.weight', "{0}: give its operating weight from the supplier (or let SAEngine propose the equipment): it loads the floor.", e.id));
		} else if (!positive(e.operatingWeight)) {
			add(path('operatingWeight'), 'error', localize('elec.p.weightPositive', "{0}: the operating weight must be above 0.", e.id));
		}
	});
	electrical.risers.forEach((r, i) => {
		const path = (field: string) => `electrical.risers.${i}.${field}`;
		checkId(path('id'), r.id);
		if (!(ELEC_RISER_KINDS as readonly unknown[]).includes(r.kind)) {
			add(path('kind'), 'error', localize('elec.p.riserKind', "{0}: '{1}' is not a kind of riser ({2}).", r.id, String(r.kind), ELEC_RISER_KINDS.join(', ')));
		}
		for (const key of ['width', 'depth'] as const) {
			if (r[key] !== undefined && !(num(r[key]) > 0)) {
				add(path(key), 'error', localize('elec.p.riserSize', "{0}: the riser's width and depth must be above 0, or left empty to have them sized.", r.id));
				break;
			}
		}
		for (const end of ['fromStory', 'toStory'] as const) {
			if (!known(r[end])) {
				add(path(end), 'error', localize('elec.p.riserStory', "{0}: the building model has no story '{1}'.", r.id, String(r[end] ?? '')));
			}
		}
		const from = elevation(r.fromStory);
		const to = elevation(r.toStory);
		if (from !== undefined && to !== undefined && to <= from) {
			add(path('toStory'), 'error', localize('elec.p.riserOrder', "{0}: its top story must be above the story it starts at.", r.id));
		}
		if (r.shaft && !shafts.has(r.shaft)) {
			add(path('shaft'), 'error', localize('elec.p.shaft', "{0}: there is no shaft '{1}'.", r.id, r.shaft));
		}
	});
	electrical.trays.forEach((t, i) => {
		const path = (field: string) => `electrical.trays.${i}.${field}`;
		checkId(path('id'), t.id);
		if (!known(t.story)) {
			add(path('story'), 'error', localize('elec.p.trayStory', "{0}: the building model has no story '{1}'.", t.id, String(t.story ?? '')));
		}
		if (t.path.length < 2) {
			add(path('path'), 'error', localize('elec.p.trayPath', "{0}: a tray run needs at least two points.", t.id));
		}
		if (!(num(t.width) > 0 && num(t.height) > 0)) {
			add(path('width'), 'error', localize('elec.p.traySize', "{0}: give the tray's width and height.", t.id));
		}
		if (t.bottom !== undefined && !(typeof t.bottom === 'number' && t.bottom >= 0)) {
			add(path('bottom'), 'error', localize('elec.p.trayBottom', "{0}: the underside above the floor cannot be negative.", t.id));
		}
	});
	const lightning = electrical.lightning;
	if (lightning.level !== undefined && !(LIGHTNING_LEVELS as readonly unknown[]).includes(lightning.level)) {
		add('electrical.lightning.level', 'error', localize('elec.p.level', "The protection level must be I, II, III or IV."));
	}
	if (lightning.downConductors !== undefined && !(DOWN_CONDUCTORS as readonly unknown[]).includes(lightning.downConductors)) {
		add('electrical.lightning.downConductors', 'error', localize('elec.p.downConductors', "The down conductors must be the structural rebar or dedicated conductors."));
	}
	if (lightning.earthing !== undefined && !(EARTHINGS as readonly unknown[]).includes(lightning.earthing)) {
		add('electrical.lightning.earthing', 'error', localize('elec.p.earthing', "The earthing must be foundation, rods or ring."));
	}
	return problems;
}

// ───────────────────────────── the backend's report ─────────────────────────────

/*
 * `saengine.electrical.report` answers E1's `electrical.report.electrical_report` as it is:
 * `{ demand: { stories: [{ story, area, connected, demand (kW), kva, notes }], storiesKw, hvacKw,
 * motorsKw, extraKw, connected, maximumDemand, kva, current, loadFactor, powerFactor, growth, notes },
 * supply: { substation, voltage, transformers: { count, rating, total, required, utilisation,
 * substationArea, note }, generator: { kva, kw, required, utilisation, fuel, fuelHours, roomArea,
 * note } | null, ups: { kva, load, autonomy, upsWeight, batteryWeight } | null }, rooms: [checks],
 * risers: [{ id, kind, current, rating, width, depth, ok, notes }], trays: [beam crossings { tray,
 * beam, passesBelow, fits }], lightning: { risk: { indices, total, decision, note }, required,
 * level, downConductors: [{ id, x, y, columns, foundation, testBox, conductor }], airTerminals,
 * roofConductors: [polyline], earth: { limit, resistance, clearance, arrangement }, structuralNotes,
 * notes }, equipment (proposed), openings (the proposed 07 MEP openings the file lacks), checks,
 * summary, notes, problems, method }`. Loads in kW, kVA; areas in m²; lengths in mm.
 */

export interface IDemandStory {
	readonly story: string;
	readonly area?: number;
	/** [kW] */
	readonly connected?: number;
	readonly demand?: number;
	/** [kVA] */
	readonly kva?: number;
	readonly note?: string;
}

export interface ISourceResult {
	/** transformer, generator, ups... */
	readonly kind: string;
	readonly id?: string;
	readonly required?: number;
	readonly provided?: number;
	readonly unit?: string;
	readonly status: CheckStatus;
	readonly note?: string;
}

export interface IRunResult {
	readonly id: string;
	readonly kind?: string;
	/** [A] */
	readonly current?: number;
	readonly size?: string;
	readonly fill?: number;
	readonly status: CheckStatus;
	readonly note?: string;
}

export interface IDownConductor {
	/** The backend's id of the down conductor ("DC1"). */
	readonly id?: string;
	/** The column line's column at the lowest story, for the structural drawings. */
	readonly column: string;
	/** Every column of the line, story by story. */
	readonly columns: readonly string[];
	readonly x?: number;
	readonly y?: number;
	readonly foundation?: string;
	readonly note?: string;
}

export type LightningDecision = 'required' | 'recommended' | 'notRequired';

export interface ILightningResult {
	readonly required?: boolean;
	readonly level?: string;
	/** Table 8.1.27's risk index (the sum of its indices) and what it decides. */
	readonly risk?: number;
	readonly decision?: LightningDecision;
	readonly riskNote?: string;
	readonly downConductors: readonly IDownConductor[];
	readonly downConductorsNeeded?: number;
	readonly airTerminals: readonly [number, number, number][];
	readonly airTerminalsProposed?: boolean;
	/** Roof conductors (the edge and the mesh), as segments. */
	readonly mesh: readonly (readonly [Point, Point])[];
	readonly earthing?: string;
	/** What the structural drawings say of the down-conductor columns. */
	readonly structuralNotes: readonly string[];
	readonly notes: readonly string[];
	readonly reference?: string;
}

export interface IDemandTotal {
	/** [kW] the connected load: the stories', the air-conditioning plant's, the motors' and the extra loads. */
	readonly connected?: number;
	readonly stories?: number;
	readonly hvac?: number;
	readonly motors?: number;
	readonly extra?: number;
	/** [kW] the maximum demand. */
	readonly demand?: number;
	readonly kva?: number;
	/** [A] at 400 V. */
	readonly current?: number;
}

export interface IElectricalReport {
	readonly summary: readonly string[];
	readonly stories: readonly IDemandStory[];
	readonly total?: IDemandTotal;
	readonly demandMethod?: string;
	readonly sources: readonly ISourceResult[];
	/** The room checks (substation and generator rooms: area, height, placement). */
	readonly rooms: readonly IMepCheck[];
	readonly risers: readonly IRunResult[];
	readonly trays: readonly IRunResult[];
	readonly lightning?: ILightningResult;
	readonly openings: readonly IOpeningResult[];
	readonly shafts: readonly IShaftResult[];
	readonly checks: readonly IMepCheck[];
	readonly notes: readonly string[];
	readonly problems: readonly string[];
	readonly method: readonly string[];
}

function sizeOf(r: Record<string, unknown>): string | undefined {
	const w = optionalNumber(r.width);
	const h = optionalNumber(r.height ?? r.depth);
	return optionalString(r.size) ?? (w !== undefined && h !== undefined ? `${Math.round(w)} × ${Math.round(h)}` : undefined);
}

/** A rising main: `{ id, kind, current, rating (A), width, depth, ok, notes }`; its fill is the current over the rating. */
function readRiser(r: Record<string, unknown>): IRunResult {
	const current = optionalNumber(r.current);
	const rating = optionalNumber(r.rating);
	const size = sizeOf(r);
	return {
		id: String(r.id ?? ''), kind: optionalString(r.kind), current,
		size: rating !== undefined ? [size, localize('elec.r.rating', "{0} A", Math.round(rating))].filter(Boolean).join(', ') : size,
		fill: optionalNumber(r.fill ?? r.utilisation) ?? (current !== undefined && rating ? current / rating : undefined), status: statusOf(r), note: noteOf(r),
	};
}

/** A tray's beam crossing: `{ tray, beam, passesBelow, fits }` (`electrical.risers.tray_openings`). */
function readTray(r: Record<string, unknown>): IRunResult {
	if (r.tray === undefined) {
		return { id: String(r.id ?? ''), kind: optionalString(r.kind), current: optionalNumber(r.current), size: sizeOf(r), fill: optionalNumber(r.fill ?? r.utilisation), status: statusOf(r), note: noteOf(r) };
	}
	const beam = String(r.beam ?? '');
	const below = r.passesBelow === true;
	const fits = r.fits !== false;
	return {
		id: String(r.tray), status: below || fits ? 'ok' : 'fail',
		note: below ? localize('elec.r.below', "passes below beam {0}", beam)
			: fits ? localize('elec.r.fits', "crosses beam {0}: an opening in its web", beam)
				: localize('elec.r.noFit', "crosses beam {0}: no web opening fits (see the notes)", beam),
	};
}

function checkNamed(checks: readonly IMepCheck[], name: string): IMepCheck | undefined {
	return checks.find(c => c.name === name);
}

/** The transformers, the generator and the UPS of `supply`, each with its capacity check. */
function readSources(supply: Record<string, unknown>, checks: readonly IMepCheck[]): ISourceResult[] {
	const kva = localize('elec.r.kva', "kVA");
	const sources: ISourceResult[] = [];
	const tx = record(supply.transformers);
	if (optionalNumber(tx.count)) {
		const check = checkNamed(checks, 'Transformer capacity');
		const area = optionalNumber(tx.substationArea);
		sources.push({
			kind: 'transformer', required: optionalNumber(tx.required), provided: optionalNumber(tx.total), unit: kva, status: check?.status ?? statusOf(tx),
			note: [
				localize('elec.r.txNote', "{0} × {1} kVA", num(tx.count), num(tx.rating)),
				area !== undefined ? localize('elec.r.substation', "substation room {0} m²", area) : '',
				optionalString(tx.note) ?? '', check?.note ?? '',
			].filter(Boolean).join('; '),
		});
	}
	const gen = record(supply.generator);
	if (optionalNumber(gen.kva)) {
		const check = checkNamed(checks, 'Generator capacity');
		const room = optionalNumber(gen.roomArea);
		const fuel = optionalNumber(gen.fuel);
		sources.push({
			kind: 'generator', required: optionalNumber(gen.required), provided: optionalNumber(gen.kva), unit: kva, status: check?.status ?? statusOf(gen),
			note: [
				fuel !== undefined ? localize('elec.r.fuel', "fuel {0} l for {1} h", Math.round(fuel), num(gen.fuelHours)) : '',
				room !== undefined ? localize('elec.r.genRoom', "generator room {0} m²", room) : '',
				optionalString(gen.note) ?? '', check?.note ?? '',
			].filter(Boolean).join('; '),
		});
	}
	const ups = record(supply.ups);
	if (optionalNumber(ups.kva)) {
		const load = optionalNumber(ups.load);
		sources.push({
			kind: 'ups', required: load !== undefined ? load / 0.9 : undefined, provided: optionalNumber(ups.kva), unit: kva, status: 'ok',
			note: localize('elec.r.ups', "{0} kW for {1} min; UPS {2} kN, batteries {3} kN", num(load), num(ups.autonomy), num(ups.upsWeight).toFixed(1), num(ups.batteryWeight).toFixed(1)),
		});
	}
	return sources;
}

function readDownConductor(d: unknown): IDownConductor | undefined {
	if (typeof d === 'string') {
		return d ? { column: d, columns: [d] } : undefined;
	}
	if (!isRecord(d)) {
		return undefined;
	}
	const columns = strings(d.columns);
	const column = columns[0] ?? optionalString(d.column) ?? optionalString(d.id);
	if (!column) {
		return undefined;
	}
	const foundation = optionalString(d.foundation);
	const conductor = optionalString(d.conductor);
	const testBox = optionalNumber(d.testBox);
	const note = noteOf(d) ?? ([
		conductor ? localize('elec.r.dcConductor', "conductor: {0}", conductor) : '',
		foundation ? localize('elec.r.dcFoundation', "earthed through foundation {0}", foundation) : '',
		testBox !== undefined ? localize('elec.r.dcTest', "test joint {0} m above the ground", testBox / 1000) : '',
	].filter(Boolean).join('; ') || undefined);
	return { id: optionalString(d.id), column, columns: columns.length ? columns : [column], x: optionalNumber(d.x), y: optionalNumber(d.y), foundation, note };
}

/** Polylines `[[x, y], ...]` (`roofConductors`) or segments `[[x, y], [x, y]]` (`mesh`) as segments. */
function segments(value: unknown): [Point, Point][] {
	const out: [Point, Point][] = [];
	for (const line of Array.isArray(value) ? value : []) {
		const points = Array.isArray(line) ? line.filter(isPoint) : [];
		for (let i = 1; i < points.length; i++) {
			out.push([points[i - 1], points[i]]);
		}
	}
	return out;
}

function readLightning(lightning: Record<string, unknown>): ILightningResult {
	const risk = record(lightning.risk);
	const decision = risk.decision === 'required' || risk.decision === 'recommended' || risk.decision === 'notRequired' ? risk.decision : undefined;
	const earth = record(lightning.earth);
	const arrangement = optionalString(earth.arrangement) ?? optionalString(lightning.earthing);
	const limit = optionalNumber(earth.limit);
	const clearance = optionalNumber(earth.clearance);
	const earthing = arrangement !== undefined || limit !== undefined ? [
		arrangement ? earthingLabel(arrangement) : '',
		limit !== undefined ? localize('elec.r.earthLimit', "resistance at most {0} ohm", limit) : '',
		clearance !== undefined ? localize('elec.r.clearance', "clearance to other metal {0} m, else bond it", clearance.toFixed(2)) : '',
	].filter(Boolean).join('; ') : undefined;
	return {
		required: typeof lightning.required === 'boolean' ? lightning.required : undefined,
		level: optionalString(lightning.level),
		risk: optionalNumber(risk.total) ?? optionalNumber(lightning.risk), decision, riskNote: optionalString(risk.note),
		downConductors: (Array.isArray(lightning.downConductors) ? lightning.downConductors : []).map(readDownConductor).filter((d): d is IDownConductor => !!d),
		downConductorsNeeded: optionalNumber(lightning.downConductorsNeeded),
		airTerminals: (Array.isArray(lightning.airTerminals) ? lightning.airTerminals : []).filter(isPoint3).map(p => [p[0], p[1], num(p[2])] as [number, number, number]),
		airTerminalsProposed: typeof lightning.airTerminalsProposed === 'boolean' ? lightning.airTerminalsProposed : undefined,
		mesh: [...segments(lightning.roofConductors), ...segments(lightning.mesh)],
		earthing,
		structuralNotes: strings(lightning.structuralNotes),
		notes: strings(lightning.notes),
		reference: optionalString(lightning.reference),
	};
}

export function readElectricalReport(raw: unknown): IElectricalReport | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const demand = record(raw.demand);
	const stories = records<Record<string, unknown>>(demand.stories).map(r => ({
		story: String(r.story ?? ''), area: optionalNumber(r.area), connected: optionalNumber(r.connected),
		demand: optionalNumber(r.demand), kva: optionalNumber(r.kva), note: noteOf(r),
	}));
	const sum = (key: 'connected' | 'demand' | 'kva') => stories.some(s => s[key] !== undefined) ? stories.reduce((s, r) => s + num(r[key]), 0) : undefined;
	const checks = readChecks(raw.checks);
	const rooms = readChecks(raw.rooms);
	const lightning = isRecord(raw.lightning) ? readLightning(raw.lightning) : undefined;
	return {
		summary: strings(raw.summary),
		stories,
		total: {
			connected: optionalNumber(demand.connected) ?? sum('connected'), stories: optionalNumber(demand.storiesKw), hvac: optionalNumber(demand.hvacKw),
			motors: optionalNumber(demand.motorsKw), extra: optionalNumber(demand.extraKw),
			demand: optionalNumber(demand.maximumDemand) ?? sum('demand'), kva: optionalNumber(demand.kva) ?? sum('kva'), current: optionalNumber(demand.current),
		},
		demandMethod: optionalNumber(demand.loadFactor) !== undefined
			? localize('elec.r.demandMethod', "unit loads BNBC Table 8.1.17 over the floor area; maximum demand {0} × the connected load{1}; kVA = kW / {2}",
				num(demand.loadFactor), num(demand.growth) ? localize('elec.r.growth', " + {0} % growth", num(demand.growth)) : '', num(demand.powerFactor, 1))
			: undefined,
		sources: readSources(record(raw.supply), checks),
		rooms,
		risers: records<Record<string, unknown>>(raw.risers).map(readRiser),
		trays: records<Record<string, unknown>>(raw.trays).map(readTray),
		lightning,
		openings: readOpeningResults(raw.openings, raw.conflicts),
		shafts: readShaftResults(raw.shafts),
		checks,
		notes: [...strings(raw.notes), ...strings(demand.notes)],
		problems: strings(raw.problems),
		method: strings(raw.method),
	};
}

/**
 * The report's check of a piece of equipment: the source of its id, else (the backend's supply
 * names no equipment) the transformers', generator's or UPS's of its kind.
 */
export function sourceOf(report: IElectricalReport | undefined, item: { readonly id: string; readonly kind: string }): ISourceResult | undefined {
	return report?.sources.find(s => s.id === item.id) ?? report?.sources.find(s => !s.id && s.kind === item.kind);
}

/**
 * What a report's failures are counted from: its checks (which hold the transformer, generator,
 * room, shaft, riser, tray and lightning checks, each once); the rows only when it has none.
 */
function electricalVerdicts(report: IElectricalReport): readonly { readonly status: CheckStatus }[] {
	return report.checks.length ? report.checks : [...report.sources, ...report.rooms, ...report.risers, ...report.trays, ...report.openings, ...report.shafts];
}

export function electricalFailures(report: IElectricalReport): number {
	return electricalVerdicts(report).filter(c => c.status === 'fail').length;
}

export function electricalWorst(report: IElectricalReport): CheckStatus {
	return worst(electricalVerdicts(report).map(c => c.status));
}

/** The status line: "11 kV · 2 equipment · 1 riser · lightning level II · 450 kVA". */
export function electricalSummary(document: IMep, report: IElectricalReport | undefined): string {
	const electrical = electricalOf(document);
	if (!electrical) {
		return localize('elec.sum.none', "No electrical services yet");
	}
	const parts: string[] = [];
	if (electrical.supply.voltage) {
		parts.push(String(electrical.supply.voltage));
	}
	const n = (count: number, one: string, many: string) => parts.push(count === 1 ? one : many);
	n(electrical.equipment.length, localize('elec.sum.equipmentOne', "1 equipment"), localize('elec.sum.equipment', "{0} equipment", electrical.equipment.length));
	n(electrical.risers.length, localize('elec.sum.riserOne', "1 riser"), localize('elec.sum.risers', "{0} risers", electrical.risers.length));
	if (electrical.trays.length) {
		n(electrical.trays.length, localize('elec.sum.trayOne', "1 tray"), localize('elec.sum.trays', "{0} trays", electrical.trays.length));
	}
	if (electrical.lightning.enabled) {
		parts.push(electrical.lightning.level ? localize('elec.sum.lightningLevel', "lightning protection level {0}", String(electrical.lightning.level)) : localize('elec.sum.lightning', "lightning protection"));
	}
	if (report) {
		if (report.total?.kva !== undefined) {
			parts.push(localize('elec.sum.kva', "{0} kVA", report.total.kva.toFixed(0)));
		}
		const failed = electricalFailures(report);
		if (failed) {
			n(failed, localize('elec.sum.fail', "1 check fails"), localize('elec.sum.fails', "{0} checks fail", failed));
		}
	}
	return parts.join(' · ');
}

/** The electrical part of the part list's summary (`mep.results/summary.json`, key `electrical`). */
export interface IElectricalSummary {
	readonly equipment: number;
	readonly risers: number;
	/** [kVA] */
	readonly demand?: number;
	readonly downConductors: number;
	readonly failed: number;
}

export function electricalSummaryFile(document: IMep, report: IElectricalReport): IElectricalSummary {
	const electrical = electricalOf(document);
	return {
		equipment: electrical?.equipment.length ?? 0, risers: electrical?.risers.length ?? 0, ...(report.total?.kva !== undefined ? { demand: report.total.kva } : {}),
		downConductors: report.lightning?.downConductors.length ?? 0, failed: electricalFailures(report),
	};
}

/** How far the ring earth electrode is drawn outside the columns [mm] (a drawing convention, not a design value). */
export const RING_OFFSET = 1000;

/** The plan points the electrical services of `story` need in view. */
export function electricalExtent(document: IMep, context: IMepContext, story: string): Point[] {
	const electrical = electricalOf(document);
	if (!electrical) {
		return [];
	}
	// The ring earth electrode around the columns, 1 m out, on the lowest story's plan.
	const ring: Point[] = [];
	const columns = context.columns.map(c => [c.x, c.y] as Point);
	if (electrical.lightning.enabled && electrical.lightning.earthing === 'ring' && story === context.stories[0]?.id && columns.length >= 2) {
		const xs = columns.map(p => p[0]);
		const ys = columns.map(p => p[1]);
		ring.push([Math.min(...xs) - RING_OFFSET, Math.min(...ys) - RING_OFFSET], [Math.max(...xs) + RING_OFFSET, Math.max(...ys) + RING_OFFSET]);
	}
	return [
		...ring,
		...electrical.equipment.filter(e => e.story === story).flatMap(elecOutline),
		...electrical.risers.filter(r => elecRiserOnStory(r, context, story)).flatMap(riserOutline),
		...electrical.trays.filter(t => t.story === story).flatMap(t => t.path),
	];
}
