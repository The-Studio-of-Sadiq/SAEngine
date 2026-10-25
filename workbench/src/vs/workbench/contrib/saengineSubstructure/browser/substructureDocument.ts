/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IGridLine } from '../../../services/saengineProject/common/gridLabels.js';
import { centroid, polygonArea } from '../../../../platform/saengine/common/geometry.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';

/*
 * The substructure document (`09 Substructure/substructure.json`, schema
 * `saengine.substructure/1`): the foundations under the building's columns (isolated, combined
 * and strip footings, pile caps on piles, rafts), the pile types and the tie beams, with the
 * design options. Everything here is plain data and pure functions (no services) so that it can
 * be tested without a workbench: reading and writing the file, the column bases and grid read
 * from the building model, the footprints drawn in the plan, the pile layouts, the checks of the
 * document and the reading of the backend's design report.
 */

export const SUBSTRUCTURE_SCHEMA_ID = 'saengine.substructure/1';

/** Backend command: the design report of the project's substructure ({@link ISubstructureReportRequest}). */
export const SUBSTRUCTURE_REPORT_COMMAND = 'saengine.substructure.report';
/** Backend command: proposed foundation sizes from the reactions and the soil report ({@link ISubstructureRequest}). */
export const SUBSTRUCTURE_SIZE_COMMAND = 'saengine.substructure.size';
/** Backend command: the footings of the building model as foundations ({@link ISubstructureRequest}). */
export const SUBSTRUCTURE_MIGRATE_COMMAND = 'saengine.substructure.migrate';
/**
 * Backend command: writes the building model's footings into `substructure.json` while it is
 * still the placeholder of a project from before Part 9 ({@link ISubstructureRequest}; answers
 * {@link ISubstructureMigration}). The editor runs it when it opens, Run All before it designs.
 */
export const SUBSTRUCTURE_ENSURE_COMMAND = 'saengine.substructure.ensureMigrated';

/** What {@link SUBSTRUCTURE_ENSURE_COMMAND} answers. */
export interface ISubstructureMigration {
	readonly migrated: boolean;
	readonly count: number;
	readonly notes: readonly string[];
	readonly problems?: readonly string[];
}

/** The design checks' summary the editor writes beside the file, for the project's part list ("2 fail"). */
export const SUBSTRUCTURE_SUMMARY_FILE = 'substructure.results/summary.json';

export type FoundationType = 'isolated' | 'combined' | 'strip' | 'pileCap' | 'raft';
export const FOUNDATION_TYPES: readonly FoundationType[] = ['isolated', 'combined', 'strip', 'pileCap', 'raft'];

export type PileKind = 'bored' | 'driven';
export const PILE_KINDS: readonly PileKind[] = ['bored', 'driven'];

/** A plan point [x, y] in mm on the project's axes. */
export type Point = [number, number];

export interface IBarMesh {
	dia: number;
	spacing: number;
}

/** Bottom and top bar layers in the foundation's local x and y (as the object library's). */
export interface IPlanarReinforcement {
	material?: string;
	cover?: number;
	bottomX?: IBarMesh;
	bottomY?: IBarMesh;
	topX?: IBarMesh;
	topY?: IBarMesh;
	[key: string]: unknown;
}

export const MESH_KEYS = ['bottomX', 'bottomY', 'topX', 'topY'] as const;
export type MeshKey = typeof MESH_KEYS[number];

export interface IFoundation {
	id: string;
	type: FoundationType;
	/** Building model column ids it carries (a raft: every column base inside the outline when empty). */
	columns?: string[];
	/** Plan centre [mm] (isolated, combined, pile cap); the columns' centroid when not given. */
	center?: Point;
	/** Rotation of the local x axis [°]. */
	rotation?: number;
	length?: number;
	width?: number;
	thickness?: number;
	/** Centre line of a strip footing [mm]. */
	path?: Point[];
	/** Outline of a raft [mm]. */
	outline?: Point[];
	/** Underside of the foundation on the project datum [mm]. */
	foundingLevel?: number;
	material?: string;
	reinforcement?: IPlanarReinforcement;
	/** Pile type id (pile cap). */
	pileType?: string;
	/** Pile offsets from the cap centre in its local axes [mm] (pile cap). */
	piles?: Point[];
	note?: string;
	[key: string]: unknown;
}

export interface IPileType {
	id: string;
	kind: PileKind;
	diameter: number;
	length: number;
	material?: string;
	reinforcement?: unknown;
	[key: string]: unknown;
}

export interface ITieBeam {
	id: string;
	from: string;
	to: string;
	/** Beam object type id. */
	type?: string;
	/** Top of the tie beam [mm]; the foundations' top when not given. */
	level?: number;
	[key: string]: unknown;
}

export type PileCapacitySource = 'soilReport' | 'bnbcSpt';

export interface ISubstructureDesign {
	pileCapacity?: PileCapacitySource;
	factorOfSafety?: { pileCompression?: number; pileUplift?: number; pileLoadTest?: boolean; bearing?: number;[key: string]: unknown };
	raftMeshSize?: number;
	/** Raft springs: the soil report's modulus of subgrade reaction, or a value [kN/m³]. */
	springsFrom?: 'soilReport' | number;
	[key: string]: unknown;
}

export interface ISubstructure {
	schema: string;
	foundations: IFoundation[];
	pileTypes: IPileType[];
	tieBeams: ITieBeam[];
	design: ISubstructureDesign;
	[key: string]: unknown;
}

/** BNBC 2020 Part 6 Table 6.3.10a: permanent structure (25 to 100 years), normal control. */
export const PILE_FACTOR_OF_SAFETY = 2.5;
/**
 * BNBC 2020 Part 6 Sec 3.10.1.18 (bored piles by Sec 3.10.4.10): the least overall factor of
 * safety of a pile in compression, without and with a load test at the site.
 */
export const PILE_FS_NO_LOAD_TEST = 3.0;
export const PILE_FS_LOAD_TEST = 2.0;
/** The least factor of safety with the BNBC SPT relations, as the backend applies it. */
export const PILE_FS_SPT = 3.5;

/**
 * The overall factors of safety of a pile the design uses (as the backend's
 * `FactorsOfSafety.for_method`): the given or default compression factor raised to 3.0 without a
 * load test at the site (2.0 with one), both raised to 3.5 with the BNBC SPT relations. `raised`
 * says why the compression factor is above the one given, if it is.
 */
export function pileFactorsUsed(design: ISubstructureDesign): { readonly compression: number; readonly uplift: number; readonly given: number; readonly raised?: 'loadTest' | 'spt' } {
	const fs = design.factorOfSafety ?? {};
	const given = typeof fs.pileCompression === 'number' ? fs.pileCompression : PILE_FACTOR_OF_SAFETY;
	const uplift = typeof fs.pileUplift === 'number' ? fs.pileUplift : PILE_FACTOR_OF_SAFETY;
	const least = Math.max(given, fs.pileLoadTest === true ? PILE_FS_LOAD_TEST : PILE_FS_NO_LOAD_TEST);
	const spt = design.pileCapacity === 'bnbcSpt';
	const compression = spt ? Math.max(least, PILE_FS_SPT) : least;
	const raised = compression <= given ? undefined : spt && compression === PILE_FS_SPT ? 'spt' : 'loadTest';
	return { compression, uplift: spt ? Math.max(uplift, PILE_FS_SPT) : uplift, given, raised };
}
/** Default raft mesh size [mm]. */
export const RAFT_MESH_SIZE = 500;
/** Founding level below the ground when neither the foundation nor the settings give one [mm]. */
export const DEFAULT_DEPTH = 1500;

// ───────────────────────────── reading and writing ─────────────────────────────

export function newSubstructure(): ISubstructure {
	return { schema: SUBSTRUCTURE_SCHEMA_ID, foundations: [], pileTypes: [], tieBeams: [], design: {} };
}

export type ParsedSubstructure =
	| { readonly kind: 'document'; readonly document: ISubstructure }
	/** The stub a new project starts with: shown as an empty document, written on the first edit. */
	| { readonly kind: 'placeholder'; readonly document: ISubstructure }
	| { readonly kind: 'error'; readonly message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoint(value: unknown): value is Point {
	return Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number';
}

/** Reads the file's text; lists and objects it lacks are filled in, unknown fields are kept. */
export function parseSubstructure(text: string): ParsedSubstructure {
	if (!text.trim()) {
		return { kind: 'placeholder', document: newSubstructure() };
	}
	let value: unknown;
	try {
		value = JSON.parse(text);
	} catch (error) {
		return { kind: 'error', message: localize('sub.invalidJson', "This file contains invalid JSON ({0}). Fix it in the text editor; the substructure editor will not change it until then.", String(error)) };
	}
	if (!isRecord(value)) {
		return { kind: 'error', message: localize('sub.notObject', "This file does not contain a JSON object.") };
	}
	if (value.part === 'substructure' && Object.keys(value).every(key => key === 'schema' || key === 'part')) {
		return { kind: 'placeholder', document: newSubstructure() };
	}
	if (value.schema !== SUBSTRUCTURE_SCHEMA_ID) {
		return { kind: 'error', message: localize('sub.unexpected', "This file is not a SAEngine substructure ({0}).", SUBSTRUCTURE_SCHEMA_ID) };
	}
	for (const list of ['foundations', 'pileTypes', 'tieBeams']) {
		if (value[list] !== undefined && !Array.isArray(value[list])) {
			return { kind: 'error', message: localize('sub.badList', "The substructure's {0} are not a list.", list) };
		}
	}
	const document = value as ISubstructure;
	document.foundations = (document.foundations ?? []).filter(isRecord) as IFoundation[];
	document.pileTypes = (document.pileTypes ?? []).filter(isRecord) as IPileType[];
	document.tieBeams = (document.tieBeams ?? []).filter(isRecord) as ITieBeam[];
	document.design = isRecord(document.design) ? document.design : {};
	for (const foundation of document.foundations) {
		if (foundation.columns !== undefined) {
			foundation.columns = Array.isArray(foundation.columns) ? foundation.columns.filter(c => typeof c === 'string') : [];
		}
		for (const key of ['path', 'outline', 'piles'] as const) {
			if (foundation[key] !== undefined) {
				foundation[key] = Array.isArray(foundation[key]) ? foundation[key]!.filter(isPoint) : [];
			}
		}
		if (foundation.center !== undefined && !isPoint(foundation.center)) {
			delete foundation.center;
		}
	}
	return { kind: 'document', document };
}

export function serializeSubstructure(document: ISubstructure): string {
	return JSON.stringify(document, undefined, '\t') + '\n';
}

// ───────────────────────────── the project around it ─────────────────────────────

/** A column at the base of the building, where a foundation carries it. */
export interface IColumnBase {
	readonly id: string;
	readonly x: number;
	readonly y: number;
	readonly rotation: number;
	/** Section size along the column's local x and y [mm] (a circle: its diameter twice). */
	readonly xDim: number;
	readonly yDim: number;
	readonly circle: boolean;
	readonly bottom: number;
	readonly type: string;
}

/** A wall standing on the base level, for strip footings. */
export interface IWallBase {
	readonly id: string;
	readonly start: Point;
	readonly end: Point;
	readonly thickness: number;
}

/** What the substructure is drawn and checked against, read from the other parts. */
export interface ISiteContext {
	readonly columns: readonly IColumnBase[];
	readonly walls: readonly IWallBase[];
	readonly grids: { readonly x: readonly IGridLine[]; readonly y: readonly IGridLine[] };
	readonly boreholes: readonly { readonly id: string; readonly x: number; readonly y: number }[];
	/** Finished ground level [mm] (project settings, foundation). */
	readonly groundLevel: number;
	/** The base level of the building [mm]. */
	readonly baseLevel: number;
	/** Beam object types, for the tie beams. */
	readonly beamTypes: readonly { readonly id: string; readonly name: string }[];
	/** Concrete material ids. */
	readonly materials: readonly string[];
	readonly defaultMaterial?: string;
	/** The reinforcement bars' material (from a footing or slab type, else the first rebar). */
	readonly barMaterial?: string;
	/** Rebar material ids. */
	readonly barMaterials?: readonly string[];
}

export const EMPTY_CONTEXT: ISiteContext = { columns: [], walls: [], grids: { x: [], y: [] }, boreholes: [], groundLevel: 0, baseLevel: 0, beamTypes: [], materials: [] };

function parseJson(text: string | undefined): Record<string, unknown> | undefined {
	if (!text) {
		return undefined;
	}
	try {
		const value = JSON.parse(text);
		return isRecord(value) ? value : undefined;
	} catch {
		return undefined;
	}
}

function records(value: unknown): Record<string, unknown>[] {
	return Array.isArray(value) ? value.filter(isRecord) : [];
}

function num(value: unknown, fallback = 0): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** The texts of the parts the substructure is drawn against (any may be missing). */
export interface ISiteTexts {
	readonly bim?: string;
	readonly objects?: string;
	readonly floorPlan?: string;
	readonly settings?: string;
	readonly soil?: string;
	readonly materials?: string;
}

/**
 * The column bases (the columns standing on the building's lowest level, with their sections
 * from the object library), walls on that level, grid, boreholes, ground level and the object
 * types the substructure uses.
 */
export function readSiteContext(texts: ISiteTexts): ISiteContext {
	const bim = parseJson(texts.bim);
	const objects = records(parseJson(texts.objects)?.objects);
	const byId = new Map(objects.map(o => [String(o.id), o]));
	const elements = records(bim?.elements);
	const stories = records(bim?.stories);
	const columnElements = elements.filter(e => e.kind === 'column' && isPoint(e.position));
	const storyBase = stories.length ? Math.min(...stories.map(s => num(s.elevation))) : undefined;
	const lowest = columnElements.length ? Math.min(...columnElements.map(c => num(c.bottom))) : 0;
	const baseLevel = storyBase ?? lowest;
	const base = Math.max(baseLevel, lowest);
	const columns: IColumnBase[] = columnElements.filter(c => num(c.bottom) <= base + 1).map(c => {
		const profile = byId.get(String(c.type))?.profile;
		const shape = isRecord(profile) ? profile : {};
		const circle = shape.shape === 'circle';
		const xDim = circle ? 2 * num(shape.radius, 200) : num(shape.xDim, 400);
		const yDim = circle ? xDim : num(shape.yDim, 400);
		const position = c.position as Point;
		return { id: String(c.id), x: position[0], y: position[1], rotation: num(c.rotation), xDim, yDim, circle, bottom: num(c.bottom), type: String(c.type ?? '') };
	});
	const walls: IWallBase[] = elements.filter(e => e.kind === 'wall' && isPoint(e.start) && isPoint(e.end) && num(e.bottom) <= base + 1).map(w => ({
		id: String(w.id), start: w.start as Point, end: w.end as Point, thickness: num(byId.get(String(w.type))?.thickness, 200),
	}));
	const grids = parseJson(texts.floorPlan)?.grids;
	const gridLines = (value: unknown) => records(value).filter(g => typeof g.position === 'number').map(g => ({ label: String(g.label ?? ''), position: num(g.position) }));
	const soil = parseJson(texts.soil);
	const boreholes = records(soil?.boreholes).filter(b => typeof b.x === 'number' && typeof b.y === 'number').map(b => ({ id: String(b.id ?? ''), x: num(b.x), y: num(b.y) }));
	const foundation = parseJson(texts.settings)?.foundation;
	const groundLevel = isRecord(foundation) ? num(foundation.groundLevel) : 0;
	const beamTypes = objects.filter(o => o.kind === 'beam').map(o => ({ id: String(o.id), name: String(o.name ?? o.id) }));
	const materialRecords = records(parseJson(texts.materials)?.materials);
	const concrete = materialRecords.filter(m => m.kind === 'concrete' || m.type === 'concrete' || m.category === 'concrete').map(m => String(m.id));
	const rebar = materialRecords.filter(m => m.kind === 'rebar' || m.type === 'rebar' || m.category === 'rebar').map(m => String(m.id));
	const used =[...new Set(objects.map(o => o.material).filter((m): m is string => typeof m === 'string'))];
	const footingType = objects.find(o => o.kind === 'footing' || o.kind === 'pileCap');
	const defaultMaterial = typeof footingType?.material === 'string' ? footingType.material : concrete[0] ?? used[0];
	const barSource = [footingType, ...objects].map(o => o?.reinforcement).find(r => isRecord(r) && typeof r.material === 'string') as Record<string, unknown> | undefined;
	return {
		columns, walls,
		grids: { x: gridLines(isRecord(grids) ? grids.x : undefined), y: gridLines(isRecord(grids) ? grids.y : undefined) },
		boreholes, groundLevel, baseLevel, beamTypes,
		materials: concrete.length ? concrete : used,
		defaultMaterial,
		barMaterial: typeof barSource?.material === 'string' ? barSource.material : rebar[0],
		barMaterials: rebar,
	};
}

// ───────────────────────────── geometry ─────────────────────────────

/** The columns a foundation names that are column bases. */
export function carriedColumns(foundation: IFoundation, context: ISiteContext): IColumnBase[] {
	const ids = new Set(foundation.columns ?? []);
	return context.columns.filter(c => ids.has(c.id));
}

/** The plan centre of a foundation: its own, else its columns' centroid, else its outline's or path's. */
export function foundationCenter(foundation: IFoundation, context: ISiteContext): Point | undefined {
	if (foundation.center) {
		return foundation.center;
	}
	const columns = carriedColumns(foundation, context);
	return centroid(columns.map(c => [c.x, c.y] as const)) ?? centroid(foundation.outline ?? []) ?? centroid(foundation.path ?? []);
}

/** Rotates the local offset (dx, dy) by `degrees` and moves it to `center`. */
export function toGlobal(center: readonly [number, number], dx: number, dy: number, degrees = 0): Point {
	const a = degrees * Math.PI / 180;
	const c = Math.cos(a);
	const s = Math.sin(a);
	return [center[0] + dx * c - dy * s, center[1] + dx * s + dy * c];
}

/**
 * The plan outline of a foundation [mm]: the rectangle of an isolated or combined footing or a
 * pile cap, a raft's outline, a strip footing's band along its path (as one polygon per
 * segment); empty when it has no size or position.
 */
export function foundationOutlines(foundation: IFoundation, context: ISiteContext): Point[][] {
	if (foundation.type === 'raft') {
		return (foundation.outline?.length ?? 0) >= 3 ? [foundation.outline!] : [];
	}
	if (foundation.type === 'strip') {
		const path = foundation.path ?? [];
		const half = num(foundation.width) / 2;
		const bands: Point[][] = [];
		for (let i = 1; i < path.length; i++) {
			const [a, b] = [path[i - 1], path[i]];
			const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
			if (!length || !half) {
				continue;
			}
			const nx = -(b[1] - a[1]) / length * half;
			const ny = (b[0] - a[0]) / length * half;
			bands.push([[a[0] + nx, a[1] + ny], [b[0] + nx, b[1] + ny], [b[0] - nx, b[1] - ny], [a[0] - nx, a[1] - ny]]);
		}
		return bands;
	}
	const center = foundationCenter(foundation, context);
	const length = num(foundation.length);
	const width = num(foundation.width);
	if (!center || length <= 0 || width <= 0) {
		return [];
	}
	const rotation = num(foundation.rotation);
	return [[
		toGlobal(center, -length / 2, -width / 2, rotation), toGlobal(center, length / 2, -width / 2, rotation),
		toGlobal(center, length / 2, width / 2, rotation), toGlobal(center, -length / 2, width / 2, rotation),
	]];
}

/** The plan positions of a pile cap's piles [mm]. */
export function pilePositions(foundation: IFoundation, context: ISiteContext): Point[] {
	const center = foundationCenter(foundation, context);
	if (foundation.type !== 'pileCap' || !center) {
		return [];
	}
	return (foundation.piles ?? []).map(([dx, dy]) => toGlobal(center, dx, dy, num(foundation.rotation)));
}

/** The pile counts of the layout presets. */
export const PILE_LAYOUTS = [2, 3, 4, 5, 6, 9] as const;

/** Rounds to a whole mm (layout offsets). */
function mm(value: number): number {
	return Math.round(value);
}

/**
 * The pile offsets of a preset layout of `count` piles of `diameter` at a centre-to-centre
 * spacing of three diameters (the spacing BNBC 2020 Part 6 Sec 3.10.1.30, written for driven
 * precast piles, generally asks for friction piles; used as the start for bored piles too): a row of 2, a triangle of 3, squares of 4, 5 (with a centre pile)
 * and 9, and two rows of 3.
 */
export function pileLayout(count: number, diameter: number): Point[] {
	const s = 3 * diameter;
	switch (count) {
		case 2: return [[-s / 2, 0], [s / 2, 0]].map(([x, y]) => [mm(x), mm(y)]);
		case 3: {
			const r = s / Math.sqrt(3);
			return [[0, r], [-s / 2, -r / 2], [s / 2, -r / 2]].map(([x, y]) => [mm(x), mm(y)]);
		}
		case 4: return [[-s / 2, -s / 2], [s / 2, -s / 2], [s / 2, s / 2], [-s / 2, s / 2]].map(([x, y]) => [mm(x), mm(y)]);
		case 5: {
			// The corners at s from the centre pile: s/√2 along each axis.
			const a = s / Math.SQRT2;
			return [[-a, -a], [a, -a], [0, 0], [a, a], [-a, a]].map(([x, y]) => [mm(x), mm(y)]);
		}
		case 6: return [-s, 0, s].flatMap(x => [-s / 2, s / 2].map(y => [mm(x), mm(y)] as Point));
		case 9: return [-s, 0, s].flatMap(y => [-s, 0, s].map(x => [mm(x), mm(y)] as Point));
		default: return [];
	}
}

/** The edge distance of a cap beyond the piles' side [mm] (BNBC 2020 Part 6 Sec 3.10.1.30, driven precast piles: at least 100). */
export const CAP_EDGE = 150;

/** Rounds up to a multiple of `step`. */
function roundUp(value: number, step: number): number {
	return Math.ceil(value / step - 1e-9) * step;
}

/** The cap size around piles of `diameter` at `piles`: their extent plus the pile radius and {@link CAP_EDGE}, in 50 mm steps. */
export function capSize(piles: readonly Point[], diameter: number): { length: number; width: number; thickness: number } {
	const extentX = Math.max(0, ...piles.map(p => Math.abs(p[0])));
	const extentY = Math.max(0, ...piles.map(p => Math.abs(p[1])));
	const edge = diameter / 2 + CAP_EDGE;
	return {
		length: roundUp(2 * (extentX + edge), 50),
		width: roundUp(2 * (extentY + edge), 50),
		thickness: Math.max(600, roundUp(2 * diameter, 50)),
	};
}

/** The smallest centre-to-centre distance between piles [mm]; undefined for fewer than two. */
export function minPileSpacing(piles: readonly Point[]): number | undefined {
	let min: number | undefined;
	for (let i = 0; i < piles.length; i++) {
		for (let j = i + 1; j < piles.length; j++) {
			const d = Math.hypot(piles[i][0] - piles[j][0], piles[i][1] - piles[j][1]);
			min = min === undefined ? d : Math.min(min, d);
		}
	}
	return min;
}

/** The founding level a foundation without its own is designed at [mm]. */
export function defaultFoundingLevel(context: ISiteContext): number {
	return context.groundLevel - DEFAULT_DEPTH;
}

// ───────────────────────────── new foundations ─────────────────────────────

/** The next free id `<prefix><n>` (F1, F2, ...; P1; TB1). */
export function nextId(prefix: string, used: Iterable<string>): string {
	const taken = new Set(used);
	for (let n = 1; ; n++) {
		if (!taken.has(`${prefix}${n}`)) {
			return `${prefix}${n}`;
		}
	}
}

/** The reinforcement a new foundation starts with: 12 mm bars at 150 both ways at the bottom, 75 mm cover. */
export function defaultReinforcement(context: ISiteContext): IPlanarReinforcement {
	const reinforcement: IPlanarReinforcement = { cover: 75, bottomX: { dia: 12, spacing: 150 }, bottomY: { dia: 12, spacing: 150 } };
	return context.barMaterial ? { material: context.barMaterial, ...reinforcement } : reinforcement;
}

function base(document: ISubstructure, context: ISiteContext, type: FoundationType, columns: readonly IColumnBase[], extra: Partial<IFoundation>): IFoundation {
	const foundation: IFoundation = { id: nextId('F', document.foundations.map(f => f.id)), type, columns: columns.map(c => c.id), ...extra };
	if (context.defaultMaterial) {
		foundation.material = context.defaultMaterial;
	}
	foundation.reinforcement = defaultReinforcement(context);
	return foundation;
}

/**
 * A footing under `columns`: an isolated 1.5 m square under one column, a combined footing over
 * two or more (their extent plus 750 mm each side, along the line through the first and last).
 */
export function newFooting(document: ISubstructure, context: ISiteContext, columns: readonly IColumnBase[]): IFoundation {
	if (columns.length <= 1) {
		return base(document, context, 'isolated', columns, { length: 1500, width: 1500, thickness: 450 });
	}
	const first = columns[0];
	const last = columns.reduce((far, c) => Math.hypot(c.x - first.x, c.y - first.y) > Math.hypot(far.x - first.x, far.y - first.y) ? c : far, first);
	const rotation = Math.round(Math.atan2(last.y - first.y, last.x - first.x) * 180 / Math.PI);
	const center = centroid(columns.map(c => [c.x, c.y] as const))!;
	const a = -rotation * Math.PI / 180;
	const local = columns.map(c => [(c.x - center[0]) * Math.cos(a) - (c.y - center[1]) * Math.sin(a), (c.x - center[0]) * Math.sin(a) + (c.y - center[1]) * Math.cos(a)]);
	const spanX = Math.max(...local.map(p => Math.abs(p[0])));
	const spanY = Math.max(...local.map(p => Math.abs(p[1])));
	const footing = base(document, context, 'combined', columns, {
		center: [Math.round(center[0]), Math.round(center[1])],
		length: roundUp(2 * spanX + 1500, 50), width: roundUp(Math.max(1500, 2 * spanY + 1500), 50), thickness: 600,
	});
	if (rotation) {
		footing.rotation = rotation;
	}
	return footing;
}

/** A pile cap of `pileType` with the layout of `count` piles under `columns`. */
export function newPileCap(document: ISubstructure, context: ISiteContext, columns: readonly IColumnBase[], pileType: IPileType, count = 4): IFoundation {
	const piles = pileLayout(count, pileType.diameter);
	return base(document, context, 'pileCap', columns, { ...capSize(piles, pileType.diameter), pileType: pileType.id, piles });
}

/** A pile type to start with: bored, 500 mm, 18 m. */
export function newPileType(document: ISubstructure, context: ISiteContext): IPileType {
	const pile: IPileType = { id: nextId('P', document.pileTypes.map(p => p.id)), kind: 'bored', diameter: 500, length: 18000 };
	if (context.defaultMaterial) {
		pile.material = context.defaultMaterial;
	}
	return pile;
}

/** A raft over the extent of `columns` plus `margin` [mm] each side, 600 mm thick. */
export function newRaft(document: ISubstructure, context: ISiteContext, columns: readonly IColumnBase[], margin = 1000): IFoundation | undefined {
	if (!columns.length) {
		return undefined;
	}
	const x0 = Math.min(...columns.map(c => c.x)) - margin;
	const x1 = Math.max(...columns.map(c => c.x)) + margin;
	const y0 = Math.min(...columns.map(c => c.y)) - margin;
	const y1 = Math.max(...columns.map(c => c.y)) + margin;
	return base(document, context, 'raft', columns, { outline: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], thickness: 600 });
}

/** A tie beam between two foundations, of the first beam type. */
export function newTieBeam(document: ISubstructure, context: ISiteContext, from: string, to: string): ITieBeam {
	const beam: ITieBeam = { id: nextId('TB', document.tieBeams.map(t => t.id)), from, to };
	if (context.beamTypes[0]) {
		beam.type = context.beamTypes[0].id;
	}
	return beam;
}

/** Sets a pile cap's layout to `count` piles of its pile type, sizing the cap around them. */
export function applyPileLayout(foundation: IFoundation, pileType: IPileType, count: number): void {
	foundation.piles = pileLayout(count, pileType.diameter);
	Object.assign(foundation, capSize(foundation.piles, pileType.diameter));
}

/** The column bases no foundation carries (a raft carries those inside its outline). */
export function uncoveredColumns(document: ISubstructure, context: ISiteContext): IColumnBase[] {
	return context.columns.filter(c => !document.foundations.some(f => f.columns?.includes(c.id) || f.type === 'raft' && !(f.columns?.length) && f.outline && insidePolygon([c.x, c.y], f.outline)));
}

/** Whether `point` is inside the polygon (even-odd). */
export function insidePolygon(point: readonly [number, number], polygon: readonly (readonly [number, number])[]): boolean {
	let inside = false;
	for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
		const [xi, yi] = polygon[i];
		const [xj, yj] = polygon[j];
		if ((yi > point[1]) !== (yj > point[1]) && point[0] < (xj - xi) * (point[1] - yi) / (yj - yi) + xi) {
			inside = !inside;
		}
	}
	return inside;
}

// ───────────────────────────── bar meshes ─────────────────────────────

/** "12@150" for a mesh of 12 mm bars at 150 mm. */
export function formatMesh(mesh: IBarMesh | undefined): string {
	return mesh && typeof mesh.dia === 'number' && typeof mesh.spacing === 'number' ? `${formatNumber(mesh.dia, 1)}@${formatNumber(mesh.spacing, 0)}` : '';
}

/** Reads "12@150" (also "T12@150", "Ø12 @ 150", "12/150"); empty clears it. */
export function parseMesh(text: string): { value?: IBarMesh; error?: string } {
	const trimmed = text.trim();
	if (!trimmed) {
		return {};
	}
	const match = /^[A-Za-zØø#]*\s*(?<dia>\d+(?:\.\d+)?)\s*(?:@|\/|mm\s*@)\s*(?<spacing>\d+(?:\.\d+)?)\s*(?:mm)?$/.exec(trimmed);
	const dia = Number(match?.groups?.dia);
	const spacing = Number(match?.groups?.spacing);
	if (!match || !(dia > 0) || !(spacing > 0)) {
		return { error: localize('sub.v.mesh', "Write the bars as diameter@spacing in mm, e.g. 12@150.") };
	}
	if (spacing < dia + 25) {
		return { error: localize('sub.v.meshTight', "{0} mm bars at {1} mm leave less than 25 mm between them.", formatNumber(dia, 1), formatNumber(spacing, 0)) };
	}
	return { value: { dia, spacing } };
}

/** Reads a list of column ids: "C1, C2 C3". */
export function parseIdList(text: string): string[] {
	return [...new Set(text.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean))];
}

// ───────────────────────────── labels ─────────────────────────────

export function foundationTypeLabel(type: FoundationType | string): string {
	switch (type) {
		case 'isolated': return localize('sub.type.isolated', "Isolated footing");
		case 'combined': return localize('sub.type.combined', "Combined footing");
		case 'strip': return localize('sub.type.strip', "Strip footing");
		case 'pileCap': return localize('sub.type.pileCap', "Pile cap");
		case 'raft': return localize('sub.type.raft', "Raft");
		default: return String(type);
	}
}

export function pileKindLabel(kind: PileKind | string): string {
	switch (kind) {
		case 'bored': return localize('sub.pile.bored', "Bored (cast in situ)");
		case 'driven': return localize('sub.pile.driven', "Driven (precast)");
		default: return String(kind);
	}
}

/** "1.5 × 1.5 × 0.45 m", "4 piles · 2.4 × 2.4 m", "raft 0.6 m", for lists and the plan. */
export function foundationSize(foundation: IFoundation): string {
	const m = (value: number | undefined) => formatNumber(num(value) / 1000, 2);
	switch (foundation.type) {
		case 'raft':
			return localize('sub.size.raft', "{0} m thick", m(foundation.thickness));
		case 'strip':
			return localize('sub.size.strip', "{0} m wide × {1} m", m(foundation.width), m(foundation.thickness));
		case 'pileCap': {
			const count = foundation.piles?.length ?? 0;
			const piles = count === 1 ? localize('sub.size.onePile', "1 pile") : localize('sub.size.piles', "{0} piles", count);
			return localize('sub.size.cap', "{0} · {1} × {2} m", piles, m(foundation.length), m(foundation.width));
		}
		default:
			return localize('sub.size.footing', "{0} × {1} × {2} m", m(foundation.length), m(foundation.width), m(foundation.thickness));
	}
}

// ───────────────────────────── checks of the document ─────────────────────────────

/** A problem of the document: the list and row it is in, and the field ("foundations.2.length"). */
export interface ISubstructureProblem {
	readonly path: string;
	readonly message: string;
	readonly severity: 'error' | 'warning';
}

/** What is missing or contradictory in the document, before any design. */
export function checkSubstructure(document: ISubstructure, context: ISiteContext): ISubstructureProblem[] {
	const problems: ISubstructureProblem[] = [];
	const error = (path: string, message: string) => problems.push({ path, message, severity: 'error' });
	const warning = (path: string, message: string) => problems.push({ path, message, severity: 'warning' });
	const duplicates = (list: readonly { id: string }[], name: string) => {
		const seen = new Set<string>();
		list.forEach((item, index) => {
			if (!item.id) {
				error(`${name}.${index}.id`, localize('sub.p.noId', "A row of the {0} has no id.", name));
			} else if (seen.has(item.id)) {
				error(`${name}.${index}.id`, localize('sub.p.duplicate', "{0} is used twice.", item.id));
			}
			seen.add(item.id);
		});
	};
	duplicates(document.foundations, 'foundations');
	duplicates(document.pileTypes, 'pileTypes');
	duplicates(document.tieBeams, 'tieBeams');

	// The rules of the backend's schema (library/substructure.py) are errors: a document that
	// breaks one is refused there as a whole, so no foundation of it would be checked.
	const columnIds = new Set(context.columns.map(c => c.id));
	const wallIds = new Set(context.walls.map(w => w.id));
	const carriedBy = new Map<string, string>();
	const pileTypes = new Map(document.pileTypes.map(p => [p.id, p]));
	const concrete = new Set(context.materials);
	const rebar = new Set(context.barMaterials ?? []);
	const reinforcementProblems = (owner: string, at: (field: string) => string, reinforcement: IPlanarReinforcement | undefined) => {
		if (!reinforcement) {
			return;
		}
		if (typeof reinforcement.material !== 'string' || !reinforcement.material) {
			error(at('reinforcement.material'), localize('sub.p.barMaterial', "{0}: choose the material of the bars.", owner));
		} else if (rebar.size && !rebar.has(reinforcement.material)) {
			warning(at('reinforcement.material'), localize('sub.p.barMaterialUnknown', "{0}: bar material {1} is not a rebar of 03 Materials.", owner, reinforcement.material));
		}
		if (!(num(reinforcement.cover) > 0)) {
			error(at('reinforcement.cover'), localize('sub.p.cover', "{0}: give the cover to the bars (more than 0 mm).", owner));
		}
	};
	document.foundations.forEach((f, i) => {
		const at = (field: string) => `foundations.${i}.${field}`;
		if (!FOUNDATION_TYPES.includes(f.type)) {
			error(at('type'), localize('sub.p.type', "{0}: unknown foundation type {1}.", f.id, String(f.type)));
			return;
		}
		const listed = new Set<string>();
		for (const column of f.columns ?? []) {
			if (listed.has(column)) {
				error(at('columns'), localize('sub.p.listedTwice', "{0}: {1} is listed twice.", f.id, column));
				continue;
			}
			listed.add(column);
			if (wallIds.has(column)) {
				if (f.type !== 'strip') {
					warning(at('columns'), localize('sub.p.wallOnStrip', "{0}: wall {1} can stand on a strip footing only.", f.id, column));
				}
			} else if (context.columns.length && !columnIds.has(column)) {
				warning(at('columns'), localize('sub.p.column', "{0}: column {1} does not stand on the base level of the building model.", f.id, column));
			}
			const other = carriedBy.get(column);
			if (other) {
				error(at('columns'), localize('sub.p.twice', "{0} is on {1} and on {2}: a column or wall stands on one foundation only.", column, other, f.id));
			} else {
				carriedBy.set(column, f.id);
			}
		}
		for (const field of ['length', 'width', 'thickness'] as const) {
			if (f[field] !== undefined && !(num(f[field]) > 0)) {
				error(at(field), localize('sub.p.positive', "{0}: {1} must be more than 0 mm.", f.id, field === 'length' ? localize('sub.f.length', "Length") : field === 'width' ? localize('sub.f.width', "Width") : localize('sub.f.thickness', "Thickness")));
			}
		}
		if (f.type === 'raft') {
			if ((f.outline?.length ?? 0) < 3) {
				error(at('outline'), localize('sub.p.outline', "{0}: the raft needs an outline of at least three points.", f.id));
			} else if (polygonArea(f.outline!) < 1) {
				error(at('outline'), localize('sub.p.outlineArea', "{0}: the raft's outline encloses no area.", f.id));
			}
		} else if (f.type === 'strip') {
			if ((f.path?.length ?? 0) < 2) {
				error(at('path'), localize('sub.p.path', "{0}: the strip footing needs a path of at least two points.", f.id));
			} else if (f.path!.some((p, k) => k > 0 && Math.hypot(p[0] - f.path![k - 1][0], p[1] - f.path![k - 1][1]) < 1)) {
				error(at('path'), localize('sub.p.pathPoints', "{0}: two consecutive points of the path coincide.", f.id));
			}
			if (f.width === undefined) {
				error(at('width'), localize('sub.p.width', "{0}: give the width.", f.id));
			}
			if (!(f.columns?.length)) {
				warning(at('columns'), localize('sub.p.stripCarries', "{0}: the strip footing carries no column or wall, so it is not designed.", f.id));
			}
		} else {
			for (const field of ['length', 'width'] as const) {
				if (f[field] === undefined) {
					error(at(field), localize('sub.p.size', "{0}: give the {1}.", f.id, field === 'length' ? localize('sub.f.length', "Length") : localize('sub.f.width', "Width")));
				}
			}
			if (!f.center && !(f.columns?.length)) {
				error(at('center'), localize('sub.p.where', "{0}: give its centre or the columns it carries.", f.id));
			}
		}
		if (f.thickness === undefined) {
			error(at('thickness'), localize('sub.p.thickness', "{0}: give the thickness.", f.id));
		}
		if (f.allowableBearing !== undefined && !(num(f.allowableBearing) > 0)) {
			error(at('allowableBearing'), localize('sub.p.qa', "{0}: the allowable bearing must be more than 0 kPa.", f.id));
		}
		if (f.material && concrete.size && !concrete.has(f.material)) {
			warning(at('material'), localize('sub.p.material', "{0}: concrete {1} is not in 03 Materials.", f.id, f.material));
		}
		reinforcementProblems(f.id, at, f.reinforcement);
		if (f.type === 'pileCap') {
			const pile = f.pileType ? pileTypes.get(f.pileType) : undefined;
			if (!f.pileType) {
				error(at('pileType'), localize('sub.p.noPileType', "{0}: choose the pile type.", f.id));
			} else if (!pile) {
				error(at('pileType'), localize('sub.p.pileType', "{0}: pile type {1} does not exist.", f.id, f.pileType));
			}
			if (!(f.piles?.length)) {
				error(at('piles'), localize('sub.p.piles', "{0}: lay out the piles.", f.id));
			} else if (pile && pile.diameter > 0) {
				pileProblems(f, pile, at, error, warning);
			}
		}
	});
	document.pileTypes.forEach((p, i) => {
		const at = (field: string) => `pileTypes.${i}.${field}`;
		if (!(num(p.diameter) > 0)) {
			error(at('diameter'), localize('sub.p.diameter', "{0}: give the pile diameter.", p.id));
		}
		if (!(num(p.length) > 0)) {
			error(at('length'), localize('sub.p.pileLength', "{0}: give the pile length.", p.id));
		}
		if (!PILE_KINDS.includes(p.kind)) {
			error(at('kind'), localize('sub.p.kind', "{0}: the pile is bored or driven.", p.id));
		}
		if (!p.material) {
			error(at('material'), localize('sub.p.pileMaterial', "{0}: choose the pile's concrete.", p.id));
		} else if (concrete.size && !concrete.has(p.material)) {
			warning(at('material'), localize('sub.p.material', "{0}: concrete {1} is not in 03 Materials.", p.id, p.material));
		}
	});
	const foundationIds = new Set(document.foundations.map(f => f.id));
	const beamTypes = new Set(context.beamTypes.map(b => b.id));
	document.tieBeams.forEach((t, i) => {
		for (const end of ['from', 'to'] as const) {
			if (!foundationIds.has(t[end])) {
				error(`tieBeams.${i}.${end}`, localize('sub.p.tieEnd', "{0}: foundation {1} does not exist.", t.id, t[end] || '—'));
			}
		}
		if (t.from && t.from === t.to) {
			error(`tieBeams.${i}.to`, localize('sub.p.tieSame', "{0} ties {1} to itself.", t.id, t.from));
		}
		if (!t.type) {
			error(`tieBeams.${i}.type`, context.beamTypes.length
				? localize('sub.p.tieNoType', "{0}: choose the beam type (its section and bars).", t.id)
				: localize('sub.p.tieNoBeamTypes', "{0}: choose the beam type; add a beam type in 04 Objects first.", t.id));
		} else if (context.beamTypes.length && !beamTypes.has(t.type)) {
			warning(`tieBeams.${i}.type`, localize('sub.p.tieType', "{0}: beam type {1} is not in the object library.", t.id, t.type));
		}
	});
	const design = document.design;
	if (design.pileCapacity !== undefined && design.pileCapacity !== 'soilReport' && design.pileCapacity !== 'bnbcSpt') {
		error('design.pileCapacity', localize('sub.p.capacitySource', "The pile capacity comes from the soil report or the BNBC SPT equations."));
	}
	for (const key of ['pileCompression', 'pileUplift', 'pileSkin', 'pileEndBearing', 'bearing']) {
		const value = design.factorOfSafety?.[key];
		if (value !== undefined && value !== null && !(typeof value === 'number' && value >= 1 && value <= 10)) {
			error(`design.factorOfSafety.${key}`, localize('sub.p.fs', "The factor of safety {0} must be between 1 and 10.", key));
		}
	}
	if (design.raftMeshSize !== undefined && !(typeof design.raftMeshSize === 'number' && design.raftMeshSize >= 100 && design.raftMeshSize <= 5000)) {
		error('design.raftMeshSize', localize('sub.p.mesh', "The raft mesh size must be between 100 and 5000 mm."));
	}
	if (design.springsFrom !== undefined && design.springsFrom !== 'soilReport' && !(typeof design.springsFrom === 'number' && design.springsFrom > 0)) {
		error('design.springsFrom', localize('sub.p.springs', "The subgrade modulus must be more than 0 kN/m³."));
	}
	return problems;
}

/**
 * The piles of a cap against the cap and each other. Errors (the backend refuses them): a pile
 * not wholly within the cap, piles overlapping. Warnings, BNBC 2020 Part 6 Sec 3.10.1.30 (written
 * for driven precast piles): end-bearing driven piles more than the greater of 750 mm and 2.5
 * diameters apart; friction piles generally at least 3.0 diameters; a pile's side at least
 * 100 mm from the cap's edge. For bored piles the same spacing is applied as a guide.
 */
function pileProblems(f: IFoundation, pile: IPileType, at: (field: string) => string, error: (path: string, message: string) => void, warning: (path: string, message: string) => void): void {
	const piles = f.piles ?? [];
	const d = pile.diameter;
	const length = num(f.length);
	const width = num(f.width);
	if (length > 0 && width > 0) {
		const outside = piles.find(([x, y]) => Math.abs(x) > length / 2 - d / 2 + 1e-6 || Math.abs(y) > width / 2 - d / 2 + 1e-6);
		if (outside) {
			error(at('piles'), localize('sub.p.pileOutside', "{0}: the pile at {1}, {2} mm does not lie within the cap.", f.id, formatNumber(outside[0], 0), formatNumber(outside[1], 0)));
			return;
		}
	}
	const spacing = minPileSpacing(piles);
	if (spacing !== undefined && spacing < d - 1e-6) {
		error(at('piles'), localize('sub.p.pileOverlap', "{0}: two piles overlap: their centres are {1} mm apart, less than the diameter.", f.id, formatNumber(spacing, 0)));
		return;
	}
	if (spacing !== undefined) {
		const endBearing = Math.max(750, 2.5 * d);
		if (pile.kind === 'driven' && spacing <= endBearing) {
			warning(at('piles'), localize('sub.p.spacingDriven', "{0}: driven piles {1} mm apart; BNBC 2020 Part 6 Sec 3.10.1.30 asks end-bearing driven piles to be more than {2} mm apart (the greater of 750 mm and 2.5 diameters), friction piles generally 3 diameters ({3} mm).", f.id, formatNumber(spacing, 0), formatNumber(endBearing, 0), formatNumber(3 * d, 0)));
		} else if (spacing < 3 * d - 1) {
			warning(at('piles'), pile.kind === 'driven'
				? localize('sub.p.spacingFriction', "{0}: driven piles {1} mm apart; BNBC 2020 Part 6 Sec 3.10.1.30 generally asks friction piles to be at least 3 diameters ({2} mm) apart.", f.id, formatNumber(spacing, 0), formatNumber(3 * d, 0))
				: localize('sub.p.spacingBored', "{0}: bored piles {1} mm apart, less than 3 diameters ({2} mm), the spacing BNBC 2020 Part 6 Sec 3.10.1.30 generally asks for driven friction piles; check that their zones of support do not overlap.", f.id, formatNumber(spacing, 0), formatNumber(3 * d, 0)));
		}
	}
	if (length > 0 && width > 0) {
		const edge = Math.min(...piles.map(([x, y]) => Math.min(length / 2 - Math.abs(x), width / 2 - Math.abs(y)))) - d / 2;
		if (edge < 100 - 0.5) {
			warning(at('length'), pile.kind === 'driven'
				? localize('sub.p.edge', "{0}: a pile's side is {1} mm from the cap's edge; BNBC 2020 Part 6 Sec 3.10.1.30 asks for at least 100 mm.", f.id, formatNumber(edge, 0))
				: localize('sub.p.edgeBored', "{0}: a pile's side is {1} mm from the cap's edge, less than the 100 mm BNBC 2020 Part 6 Sec 3.10.1.30 asks for driven piles.", f.id, formatNumber(edge, 0)));
		}
	}
}

// ───────────────────────────── the design report (backend) ─────────────────────────────

/** What the editor asks the backend: the project, and the document as it is in the editor (maybe unsaved). */
export interface ISubstructureRequest {
	/** The project folder (file system path). */
	readonly projectRoot: string;
	/** The substructure's text when the editor holds unsaved edits; the backend may ignore it and read the file. */
	readonly substructureText?: string;
	/** Sizing only: the columns to size footings for (propose(ctx, columns)); all uncovered when not given. */
	readonly columns?: readonly string[];
}

export type ISubstructureReportRequest = ISubstructureRequest;

/** One check of a foundation, in the format of the superstructure's design checks. */
export interface ISubstructureCheck {
	readonly name: string;
	readonly demand: number | null;
	readonly capacity: number | null;
	readonly unit: string;
	readonly utilisation: number | null;
	readonly combination: string | null;
	readonly ok: boolean;
	readonly note: string;
	/** Reported only: does not make the foundation fail. */
	readonly flag: boolean;
}

/** The loads on one pile of a cap [kN]. */
export interface IPileLoad {
	/** Its number in the cap, from 1. */
	readonly number: number;
	/** Offset from the cap's centre in its local axes [mm]. */
	readonly u?: number;
	readonly v?: number;
	/** Largest service compression. */
	readonly compression?: number;
	/** Least service load: negative when the pile pulls out. */
	readonly least?: number;
	/** Largest factored compression. */
	readonly factored?: number;
	/** Allowable compression of the pile. */
	readonly capacity?: number;
	readonly utilisation?: number;
	readonly combination?: string;
}

/** A point of a raft's results: contact pressure and settlement at a plan point. */
export interface IRaftPoint {
	readonly x: number;
	readonly y: number;
	readonly pressure?: number;
	readonly settlement?: number;
}

export interface IRaftResult {
	readonly points: readonly IRaftPoint[];
	/** Spacing of the points [mm]. */
	readonly meshSize?: number;
	/** The largest gross contact pressure (the backend's raft summary is gross: with the overburden) [kPa]. */
	readonly maxPressure?: number;
	readonly allowablePressure?: number;
	readonly maxSettlement?: number;
	readonly differentialSettlement?: number;
	readonly angularDistortion?: number;
	readonly combination?: string;
}

/** One pile type's capacity at one borehole [kN]. */
export interface IPileCapacity {
	readonly pileType: string;
	readonly borehole?: string;
	readonly skin?: number;
	readonly base?: number;
	readonly ultimate?: number;
	readonly compression?: number;
	readonly uplift?: number;
	readonly method?: string;
	readonly note?: string;
}

export interface IFoundationResult {
	readonly id: string;
	/** The foundation type, or "tieBeam". */
	readonly type: string;
	readonly checks: readonly ISubstructureCheck[];
	readonly utilisation: number | null;
	readonly ok: boolean;
	/** The designed sizes [mm]. */
	readonly sizes?: { readonly length?: number; readonly width?: number; readonly thickness?: number };
	/** Net bearing pressure under the service loads [kPa] against the allowable. */
	readonly pressure?: { readonly max?: number; readonly allowable?: number; readonly combination?: string; readonly source?: string };
	readonly piles?: readonly IPileLoad[];
	/** A pile cap's single pile capacity at its borehole. */
	readonly capacity?: IPileCapacity;
	readonly raft?: IRaftResult;
	readonly notes?: readonly string[];
}

export interface ISubstructureReport {
	readonly foundations: readonly IFoundationResult[];
	readonly tieBeams: readonly IFoundationResult[];
	/** Foundations and tie beams not designed, and why. */
	readonly skipped: readonly { readonly id: string; readonly type: string; readonly reason: string }[];
	readonly pileCapacities: readonly IPileCapacity[];
	readonly summary: { readonly checked: number; readonly passed: number; readonly failed: number; readonly maxUtilisation: number | null; readonly governing: string | null };
	readonly notes: readonly string[];
	readonly method: readonly string[];
	/**
	 * The stamp of each part file the design read, by part id ("" for a missing file), when the
	 * backend gives them: the part list compares them to tell when the checks are out of date.
	 */
	readonly sources?: { readonly [part: string]: string };
}

function optionalNumber(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function nullableNumber(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function optionalString(value: unknown): string | undefined {
	return typeof value === 'string' ? value : undefined;
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((s): s is string => typeof s === 'string') : typeof value === 'string' ? [value] : [];
}

function readCheck(raw: Record<string, unknown>): ISubstructureCheck {
	const utilisation = nullableNumber(raw.utilisation);
	return {
		name: String(raw.name ?? ''),
		demand: nullableNumber(raw.demand),
		capacity: nullableNumber(raw.capacity),
		unit: typeof raw.unit === 'string' ? raw.unit : '',
		utilisation,
		combination: typeof raw.combination === 'string' ? raw.combination : null,
		ok: typeof raw.ok === 'boolean' ? raw.ok : utilisation === null || utilisation <= 1,
		note: typeof raw.note === 'string' ? raw.note : '',
		flag: raw.flag === true,
	};
}

function readRaft(raw: unknown): IRaftResult | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	let points: IRaftPoint[] = records(raw.points).filter(p => typeof p.x === 'number' && typeof p.y === 'number').map(p => ({
		x: num(p.x), y: num(p.y), pressure: optionalNumber(p.pressure), settlement: optionalNumber(p.settlement),
	}));
	// Also accepted: nodes [[x, y], ...] with values per node.
	if (!points.length && Array.isArray(raw.nodes)) {
		const pressure = Array.isArray(raw.pressure) ? raw.pressure : [];
		const settlement = Array.isArray(raw.settlement) ? raw.settlement : [];
		points = [];
		(raw.nodes as unknown[]).forEach((node, i) => {
			if (isPoint(node)) {
				points.push({ x: node[0], y: node[1], pressure: optionalNumber(pressure[i]), settlement: optionalNumber(settlement[i]) });
			}
		});
	}
	// The maxima directly on the raft, or in its `summary` (the backend's raft design).
	const summary = isRecord(raw.summary) ? raw.summary : {};
	return {
		points,
		meshSize: optionalNumber(raw.meshSize),
		maxPressure: optionalNumber(raw.maxPressure ?? summary.maxPressure),
		allowablePressure: optionalNumber(raw.allowablePressure ?? summary.allowablePressure),
		maxSettlement: optionalNumber(raw.maxSettlement ?? summary.maxSettlement),
		differentialSettlement: optionalNumber(raw.differentialSettlement ?? summary.maxDifferential),
		angularDistortion: optionalNumber(raw.angularDistortion ?? summary.maxAngularDistortion),
		combination: optionalString(raw.combination) ?? optionalString(summary.maxPressureCombination),
	};
}

/**
 * One capacity row: the editor's own names (skin, base, ultimate, compression, uplift) or the
 * soil module's (Qs, Qb, Qult, Qa, Ta, methodText).
 */
function readCapacity(row: Record<string, unknown>, pileType: string, borehole: string | undefined): IPileCapacity {
	return {
		pileType,
		borehole,
		skin: optionalNumber(row.skin ?? row.Qs),
		base: optionalNumber(row.base ?? row.Qb),
		ultimate: optionalNumber(row.ultimate ?? row.Qult),
		compression: optionalNumber(row.compression ?? row.allowable ?? row.Qa),
		uplift: optionalNumber(row.uplift ?? row.Ta),
		method: optionalString(row.method) ?? optionalString(row.methodText),
		note: optionalString(row.note),
	};
}

function readResult(f: Record<string, unknown>): IFoundationResult {
	const checks = records(f.checks).map(readCheck);
	const utilisations = checks.filter(c => !c.flag).map(c => c.utilisation).filter((u): u is number => u !== null);
	const utilisation = nullableNumber(f.utilisation) ?? (utilisations.length ? Math.max(...utilisations) : null);
	const pressure = isRecord(f.pressure) ? f.pressure : undefined;
	const sizes = isRecord(f.sizes) ? f.sizes : undefined;
	const id = String(f.id ?? '');
	// A pile cap's single pile: `capacity`, or the backend's `pile` with the borehole of its `capacityTable`.
	const capacity = isRecord(f.capacity) ? f.capacity : isRecord(f.pile) ? f.pile : undefined;
	const table = isRecord(f.capacityTable) ? f.capacityTable : undefined;
	const pileType = optionalString(capacity?.pileType) ?? (isRecord(f.sizes) ? optionalString(f.sizes.pileType) : undefined) ?? optionalString(f.pileType) ?? '';
	return {
		id,
		type: String(f.type ?? ''),
		checks,
		utilisation,
		ok: typeof f.ok === 'boolean' ? f.ok : checks.every(c => c.ok || c.flag),
		sizes: sizes ? { length: optionalNumber(sizes.length), width: optionalNumber(sizes.width), thickness: optionalNumber(sizes.thickness) } : undefined,
		pressure: pressure ? {
			max: optionalNumber(pressure.max ?? pressure.net),
			allowable: optionalNumber(pressure.allowable ?? pressure.qa),
			combination: optionalString(pressure.combination),
			source: optionalString(pressure.source),
		} : undefined,
		piles: Array.isArray(f.piles) ? records(f.piles).map((p, index) => {
			const least = optionalNumber(p.serviceMin ?? p.least);
			const uplift = optionalNumber(p.uplift);
			return {
				number: optionalNumber(p.index) ?? index + 1,
				u: optionalNumber(p.u ?? p.dx ?? p.x), v: optionalNumber(p.v ?? p.dy ?? p.y),
				compression: optionalNumber(p.serviceMax ?? p.compression ?? p.load),
				least: least ?? (uplift !== undefined ? -uplift : undefined),
				factored: optionalNumber(p.strengthMax ?? p.factored),
				capacity: optionalNumber(p.capacity),
				utilisation: optionalNumber(p.utilisation),
				combination: optionalString(p.combination),
			};
		}) : undefined,
		capacity: capacity ? readCapacity(capacity, pileType, optionalString(capacity.borehole) ?? optionalString(table?.borehole)) : undefined,
		raft: readRaft(f.raft),
		notes: strings(f.notes),
	};
}

/** Reads the backend's design report; undefined when it is not one. */
export function readSubstructureReport(raw: unknown): ISubstructureReport | undefined {
	if (!isRecord(raw) || !Array.isArray(raw.foundations)) {
		return undefined;
	}
	const foundations = records(raw.foundations).map(readResult);
	const tieBeams = records(raw.tieBeams).map(readResult);
	// Pile capacities: a flat list of rows, or per pile type a list per borehole (`boreholes` or
	// `capacities`), or capacity tables ({borehole, rows}); else the pile caps' own capacities.
	const pileCapacities: IPileCapacity[] = [];
	for (const entry of records(raw.pileCapacities ?? raw.pileCapacity)) {
		const pileType = String(entry.pileType ?? entry.id ?? '');
		const nested = Array.isArray(entry.boreholes) ? records(entry.boreholes) : Array.isArray(entry.capacities) ? records(entry.capacities) : undefined;
		if (nested) {
			for (const row of nested) {
				pileCapacities.push(readCapacity(row, String(row.pileType ?? pileType), optionalString(row.borehole) ?? optionalString(row.id)));
			}
		} else {
			pileCapacities.push(readCapacity(entry, pileType, optionalString(entry.borehole)));
		}
	}
	if (!pileCapacities.length) {
		const seen = new Set<string>();
		for (const f of foundations) {
			const key = `${f.capacity?.pileType}|${f.capacity?.borehole}`;
			if (f.capacity && !seen.has(key)) {
				seen.add(key);
				pileCapacities.push(f.capacity);
			}
		}
	}
	const skipped = records(raw.skipped).map(s => ({ id: String(s.id ?? ''), type: String(s.type ?? ''), reason: String(s.reason ?? '') }));
	const summary = isRecord(raw.summary) ? raw.summary : {};
	const designed = [...foundations, ...tieBeams];
	const failed = designed.filter(f => !f.ok).length;
	const worst = designed.reduce<IFoundationResult | undefined>((w, f) => f.utilisation !== null && (w?.utilisation ?? -1) < f.utilisation ? f : w, undefined);
	return {
		foundations,
		tieBeams,
		skipped,
		pileCapacities,
		summary: {
			checked: optionalNumber(summary.checked) ?? designed.length,
			passed: optionalNumber(summary.passed) ?? designed.length - failed,
			failed: optionalNumber(summary.failed) ?? failed,
			maxUtilisation: nullableNumber(summary.maxUtilisation) ?? worst?.utilisation ?? null,
			governing: typeof summary.governing === 'string' ? summary.governing : worst?.id ?? null,
		},
		notes: strings(raw.notes),
		method: strings(raw.method),
		sources: isRecord(raw.sources) ? Object.fromEntries(Object.entries(raw.sources).filter((e): e is [string, string] => typeof e[1] === 'string')) : undefined,
	};
}

/** What the sizing assistant proposes: foundations to put in place of those with the same id. */
export interface ISizingProposal {
	readonly foundations: readonly IFoundation[];
	readonly pileTypes: readonly IPileType[];
	readonly notes: readonly string[];
}

/**
 * Reads the sizing assistant's answer ({foundations, pileTypes?, notes?}) or the import of the
 * building model's footings ({substructure: the whole document, notes}); undefined when it is not one.
 */
export function readSizingProposal(raw: unknown): ISizingProposal | undefined {
	const value = isRecord(raw) && isRecord(raw.document) ? raw.document : isRecord(raw) && isRecord(raw.substructure) ? raw.substructure : raw;
	if (!isRecord(value) || !Array.isArray(value.foundations)) {
		return undefined;
	}
	const parsed = parseSubstructure(JSON.stringify({ ...value, schema: SUBSTRUCTURE_SCHEMA_ID }));
	if (parsed.kind !== 'document') {
		return undefined;
	}
	return { foundations: parsed.document.foundations, pileTypes: parsed.document.pileTypes, notes: strings(isRecord(raw) ? raw.notes : undefined) };
}

/**
 * Adds `pileTypes` to `document`: one equal to a pile type there is reused, one whose id is taken
 * by a different one gets a new id. Returns the ids to use, by the given id.
 */
function addPileTypes(document: ISubstructure, pileTypes: readonly IPileType[]): Map<string, string> {
	const ids = new Map<string, string>();
	for (const pile of pileTypes) {
		const same = document.pileTypes.find(p => p.kind === pile.kind && p.diameter === pile.diameter && p.length === pile.length && p.material === pile.material);
		if (same) {
			ids.set(pile.id, same.id);
			continue;
		}
		const id = document.pileTypes.some(p => p.id === pile.id) ? nextId('P', document.pileTypes.map(p => p.id)) : pile.id;
		document.pileTypes.push({ ...pile, id });
		ids.set(pile.id, id);
	}
	return ids;
}

/** Sets a proposed or imported foundation's pile type to the id it has in the document. */
function withPileType(foundation: IFoundation, ids: Map<string, string>): IFoundation {
	return foundation.pileType && ids.has(foundation.pileType) ? { ...foundation, pileType: ids.get(foundation.pileType) } : foundation;
}

/**
 * Keeps of the sizing assistant's `proposal` the foundations for `columns` (when the request
 * named columns): a backend that sized other columns too would otherwise replace foundations
 * the engineer did not ask about.
 */
export function proposalFor(proposal: ISizingProposal, columns: readonly string[] | undefined): ISizingProposal {
	if (!columns) {
		return proposal;
	}
	const wanted = new Set(columns);
	return { ...proposal, foundations: proposal.foundations.filter(f => (f.columns ?? []).length > 0 && f.columns!.every(c => wanted.has(c))) };
}

/**
 * Puts the sizing assistant's `proposal` into `document`. The backend picks the proposals' ids
 * against the saved file, so they mean nothing here: each proposed foundation is placed by the
 * columns it carries. It replaces the foundations that carry any of them (the first one's id
 * stays, so its tie beams stay; tie beams of the others move to it), keeping their concrete and
 * reinforcement when the proposal has none; a proposal for columns no foundation carries is
 * added with a free id. The editor asks for whole foundations (all the columns of each), so a
 * replaced foundation's columns are all in the proposal. Returns the ids of the foundations placed.
 */
export function applyProposal(document: ISubstructure, proposal: ISizingProposal): string[] {
	const pileIds = addPileTypes(document, proposal.pileTypes);
	const placed: string[] = [];
	for (const raw of proposal.foundations) {
		const proposed = withPileType(raw, pileIds);
		const columns = new Set(proposed.columns ?? []);
		const replaced = document.foundations.filter(f => !placed.includes(f.id) && (f.columns ?? []).some(c => columns.has(c)));
		if (replaced.length) {
			const [kept, ...others] = replaced;
			const foundation: IFoundation = { ...proposed, id: kept.id };
			if (foundation.material === undefined && kept.material !== undefined) {
				foundation.material = kept.material;
			}
			if (foundation.reinforcement === undefined && kept.reinforcement !== undefined) {
				foundation.reinforcement = kept.reinforcement;
			}
			const gone = new Set(others.map(f => f.id));
			document.foundations[document.foundations.indexOf(kept)] = foundation;
			document.foundations = document.foundations.filter(f => !gone.has(f.id));
			for (const tie of document.tieBeams) {
				tie.from = gone.has(tie.from) ? kept.id : tie.from;
				tie.to = gone.has(tie.to) ? kept.id : tie.to;
			}
			document.tieBeams = document.tieBeams.filter(t => t.from !== t.to);
			placed.push(kept.id);
		} else {
			const taken = document.foundations.map(f => f.id);
			const id = proposed.id && !taken.includes(proposed.id) ? proposed.id : nextId('F', taken);
			document.foundations.push({ ...proposed, id });
			placed.push(id);
		}
	}
	return placed;
}

/**
 * Puts the footings imported from the building model into `document`. The backend returns the
 * whole saved file with the imported footings added, so only the foundations whose id is not in
 * the saved file (`savedIds`) are imported ones; the rest are the saved foundations, which the
 * editor's own (maybe edited, maybe deleted) ones stand for. An imported footing under a column
 * a foundation already carries is left out; one whose id is taken gets a free id.
 */
export function importFoundations(document: ISubstructure, imported: ISizingProposal, savedIds: ReadonlySet<string>): { added: string[]; skipped: string[] } {
	const added: string[] = [];
	const skipped: string[] = [];
	const fresh = imported.foundations.filter(f => !savedIds.has(f.id));
	const carried = new Set(document.foundations.flatMap(f => f.columns ?? []));
	const usedPiles = new Set(fresh.filter(f => !(f.columns ?? []).some(c => carried.has(c))).map(f => f.pileType).filter(Boolean));
	const pileIds = addPileTypes(document, imported.pileTypes.filter(p => usedPiles.has(p.id)));
	for (const raw of fresh) {
		if ((raw.columns ?? []).some(c => carried.has(c))) {
			skipped.push(raw.id);
			continue;
		}
		const taken = document.foundations.map(f => f.id);
		const id = taken.includes(raw.id) ? nextId('F', taken) : raw.id;
		document.foundations.push({ ...withPileType(raw, pileIds), id });
		for (const c of raw.columns ?? []) {
			carried.add(c);
		}
		added.push(id);
	}
	return { added, skipped };
}

/** The check that governs a result: the highest utilisation of the checks that count (not the ones only reported). */
export function governingCheck(result: IFoundationResult | undefined): ISubstructureCheck | undefined {
	let governing: ISubstructureCheck | undefined;
	for (const check of result?.checks ?? []) {
		if (!check.flag && (!governing || (check.utilisation ?? -1) > (governing.utilisation ?? -1))) {
			governing = check;
		}
	}
	return governing;
}

/** The columns and walls of `ids` a foundation of `document` already carries, with that foundation. */
export function carriedAlready(document: ISubstructure, ids: readonly string[]): { id: string; foundation: string }[] {
	return ids.flatMap(id => {
		const on = document.foundations.find(f => f.columns?.includes(id));
		return on ? [{ id, foundation: on.id }] : [];
	});
}

/** The colour band of a utilisation, as in the superstructure's design: below 0.9, 0.9 to 1.0, above 1.0. */
export function utilisationBand(utilisation: number | null | undefined): 'ok' | 'warn' | 'fail' | 'none' {
	if (typeof utilisation !== 'number' || !Number.isFinite(utilisation)) {
		return 'none';
	}
	return utilisation > 1 ? 'fail' : utilisation >= 0.9 ? 'warn' : 'ok';
}

/** A utilisation to two decimals, or three where two would hide which colour band it is in. */
export function formatUtilisation(value: number): string {
	const short = value.toFixed(2);
	return Number(short) !== value && (short === '1.00' || short === '0.90') ? value.toFixed(3) : short;
}

/** The largest service pressure of all footings with the allowable at that footing. */
export function maxPressure(report: ISubstructureReport): { pressure: number; allowable?: number; id: string } | undefined {
	let best: { pressure: number; allowable?: number; id: string } | undefined;
	for (const f of report.foundations) {
		// The net pressure against qa of every foundation (a raft's too, not its gross maximum).
		const pressure = f.pressure?.max;
		if (typeof pressure === 'number' && (!best || pressure > best.pressure)) {
			best = { pressure, allowable: f.pressure?.allowable, id: f.id };
		}
	}
	return best;
}

/** "6 foundations · 2 fail · max pressure 142 kPa (qa 150)" for the status line. */
export function substructureSummary(document: ISubstructure, report: ISubstructureReport | undefined): string {
	const count = document.foundations.length;
	const parts = [count === 1 ? localize('sub.oneFoundation', "1 foundation") : localize('sub.foundations', "{0} foundations", count)];
	if (report) {
		const failed = report.summary.failed;
		parts.push(failed ? localize('sub.fail', "{0} fail", failed) : localize('sub.allPass', "all pass"));
		const pressure = maxPressure(report);
		if (pressure) {
			parts.push(typeof pressure.allowable === 'number'
				? localize('sub.maxPressureQa', "max pressure {0} kPa (qa {1})", formatNumber(pressure.pressure, 0), formatNumber(pressure.allowable, 0))
				: localize('sub.maxPressure', "max pressure {0} kPa", formatNumber(pressure.pressure, 0)));
		}
	}
	return parts.join(' · ');
}

/** Content of {@link SUBSTRUCTURE_SUMMARY_FILE}, read by the project's part list. */
export interface ISubstructureSummaryFile {
	readonly foundations: number;
	readonly checked: number;
	readonly passed: number;
	readonly failed: number;
	readonly maxUtilisation: number | null;
	readonly governing: string | null;
	/** ISO time the checks were computed. */
	readonly computed: string;
	/** The stamps of the part files the checks read, by part id (see {@link ISubstructureReport.sources}). */
	readonly source?: { readonly [part: string]: string };
}

export function substructureSummaryFile(document: ISubstructure, report: ISubstructureReport, computed: Date): ISubstructureSummaryFile {
	const { checked, passed, failed, maxUtilisation, governing } = report.summary;
	return { foundations: document.foundations.length, checked, passed, failed, maxUtilisation, governing, computed: computed.toISOString(), source: report.sources };
}
