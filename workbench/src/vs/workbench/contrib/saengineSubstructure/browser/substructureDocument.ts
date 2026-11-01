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
 * and strip footings, pile caps on piles, rafts), the pile types, the pile grid and the piles
 * placed in plan on it (independent of the building's grid), and the tie beams, with the design
 * options. A pile cap lists the piles it stands on; its centre need not lie on its columns. Everything here is plain data and pure functions (no services) so that it can
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
/** The editor's last checks of the saved file, with the signatures they were computed for: shown when it opens again. */
export const SUBSTRUCTURE_REPORT_FILE = 'substructure.results/report.json';

export type FoundationType = 'isolated' | 'combined' | 'strip' | 'pileCap' | 'raft';
export const FOUNDATION_TYPES: readonly FoundationType[] = ['isolated', 'combined', 'strip', 'pileCap', 'raft'];

/** An isolated footing's section: one thickness, a sloped top or an upper step. */
export type FootingSection = 'flat' | 'sloped' | 'stepped';
export const FOOTING_SECTIONS: readonly FootingSection[] = ['flat', 'sloped', 'stepped'];

export type PileKind = 'bored' | 'driven' | 'drivenCastInPlace';
export const PILE_KINDS: readonly PileKind[] = ['bored', 'driven', 'drivenCastInPlace'];

/** How a bored pile's concrete is placed: in a dry bore, or by tremie under water or slurry. */
export type PilePlacement = 'dry' | 'submerged';
export const PILE_PLACEMENTS: readonly PilePlacement[] = ['dry', 'submerged'];

/** A pile load test's kind and stage. */
export type PileTestKind = 'compression' | 'uplift' | 'lateral';
export const PILE_TEST_KINDS: readonly PileTestKind[] = ['compression', 'uplift', 'lateral'];
export type PileTestStage = 'initial' | 'routine';
export const PILE_TEST_STAGES: readonly PileTestStage[] = ['initial', 'routine'];

/** How the pile head is held by the cap: fixed (bars developed into it) or free (pinned). */
export type PileFixity = 'fixed' | 'free';
export const PILE_FIXITIES: readonly PileFixity[] = ['fixed', 'free'];

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
	/**
	 * Pile cap: the ids of the piles it stands on ({@link ISubstructure.piles}). A file of an
	 * earlier version had a `pileType` and offsets from the centre: {@link upgradePileCaps}.
	 */
	piles?: string[];
	/** Isolated footings: flat, sloped or stepped (default flat). */
	section?: FootingSection;
	/** Sloped: the edge thickness; stepped: the lower step's [mm]. */
	edgeThickness?: number;
	/** The flat top of a sloped footing or the upper step, centred on the column [mm]. */
	topLength?: number;
	topWidth?: number;
	/** Footings on or near a slope: from the centre to the slope face at the base level [mm]. */
	slopeDistance?: number;
	note?: string;
	[key: string]: unknown;
}

/** A slab on grade: a ground-bearing slab under a floor load and a concentrated load. */
export interface IGroundSlab {
	id: string;
	/** Plan outline [mm]. */
	outline: Point[];
	thickness: number;
	material?: string;
	/** One layer each way for crack control (none: plain). */
	mesh?: { dia: number; spacing: number };
	meshMaterial?: string;
	/** Floor load [kPa]. */
	uniformLoad?: number;
	/** The largest post, rack-leg or wheel load, service [kN]. */
	pointLoad?: number;
	/** Side of the square contact of the concentrated load [mm]. */
	contactSide?: number;
	/** Of the compacted sub-base [kN/m³]; the design's subgrade springs value when not given. */
	subgradeModulus?: number;
	factorOfSafety?: number;
	/** Contraction joint spacing [mm]. */
	jointSpacing?: number;
	note?: string;
	[key: string]: unknown;
}

/** A pile's bars (the backend's LinearReinforcement): bars round the perimeter and ties or a spiral. */
export interface IPileReinforcement {
	material?: string;
	cover?: number;
	longitudinal?: { position: string; count: number; dia: number }[];
	transverse?: { type: 'tie' | 'spiral' | 'stirrup'; dia: number; spacing: number;[key: string]: unknown };
	[key: string]: unknown;
}

export interface IPileType {
	id: string;
	kind: PileKind;
	diameter: number;
	length: number;
	material?: string;
	reinforcement?: IPileReinforcement;
	/** Head fixity in the cap (default fixed). */
	headFixity?: PileFixity;
	/** Depth to fixity below the head [mm], from the geotechnical report; none: axial only. */
	fixityDepth?: number;
	/** Drilled shafts in sand: the code pack's K/K0 construction id (with `shaftConcreting`). */
	shaftConstruction?: string;
	/** Drilled shafts in sand: the code pack's δ/φ construction id. */
	shaftConcreting?: string;
	/** Driven cast-in-place piles tapered to the tip: its diameter [mm]. */
	tipDiameter?: number;
	/** Bored piles: concrete placed in a dry bore or by tremie (the default). */
	placement?: PilePlacement;
	/** Driven piles: driving stresses above the code pack's limit. */
	hardDriving?: boolean;
	/** Length of the cage below the cut-off [mm]; empty: the full length. */
	reinforcedLength?: number;
	/** Bored piles: depth of the temporary casing below the cut-off [mm]. */
	casingDepth?: number;
	/** Length standing unbraced in air, water or scour below the cap [mm]. */
	unbracedLength?: number;
	/** The allowable lateral movement of the pile head [mm]; empty: the code pack's. */
	lateralDeflection?: number;
	[key: string]: unknown;
}

/** A static load test of a pile type at the site: its load-movement curve. */
export interface IPileLoadTest {
	id: string;
	pileType: string;
	kind?: PileTestKind;
	test?: PileTestStage;
	/** A compression test on a group of piles. */
	group?: boolean;
	/** [load kN, movement mm] at each stage of loading. */
	points: [number, number][];
	/** Uplift tests: the load at the clear break [kN]. */
	breakLoad?: number;
	/** Under-reamed piles: the bulb's diameter [mm]. */
	bulbDiameter?: number;
	[key: string]: unknown;
}

/** A pile placed in plan: its mark (PL1, ...), pile type and the position of its centre [mm]. */
export interface IPile {
	id: string;
	type: string;
	position: Point;
	[key: string]: unknown;
}

/** A line of the pile grid at `position` [mm] from the grid's origin along the grid's own axis. */
export interface IPileGridLine {
	label: string;
	position: number;
}

/**
 * The grid the piles are set out on, independent of the building's grid: its origin and rotation
 * and named lines across its x axis (`x`, at x = position) and its y axis (`y`).
 */
export interface IPileGrid {
	origin?: Point;
	rotation?: number;
	x: IPileGridLine[];
	y: IPileGridLine[];
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

/** Soil report's unit values, the code pack's static method or its SPT relations ('bnbcSpt', the
 * SPT method's former id, is read as 'spt'). */
export type PileCapacitySource = 'soilReport' | 'static' | 'spt';

export interface ISubstructureDesign {
	pileCapacity?: PileCapacitySource;
	factorOfSafety?: { pileCompression?: number; pileUplift?: number; pileLoadTest?: boolean; bearing?: number;[key: string]: unknown };
	raftMeshSize?: number;
	/** Raft springs: the soil report's modulus of subgrade reaction, or a value [kN/m³]. */
	springsFrom?: 'soilReport' | number;
	/** Raft springs: no tension (solved iteratively, the default) or linear. */
	raftSprings?: 'noTension' | 'linear';
	/** The row of the code pack's permissible settlements (rcc when empty). */
	structureType?: string;
	/** L/H of load bearing walls for their settlement limits (2 when empty). */
	wallLengthHeight?: number;
	/** A temporary structure: the code pack's least depth of its exterior footings. */
	temporary?: boolean;
	/** The code pack's presumptive bearing row used without a soil report. */
	presumptiveSoil?: string;
	/** Check the piles for negative skin friction (default on). */
	downdrag?: boolean;
	/** Depth below the ground of the settling soil [mm]; empty: the soil report's layers. */
	downdragDepth?: number;
	/** Depth below the ground of the swelling zone in expansive soil [mm]. */
	swellingDepth?: number;
	[key: string]: unknown;
}

export interface ISubstructure {
	schema: string;
	foundations: IFoundation[];
	pileTypes: IPileType[];
	pileGrid?: IPileGrid;
	/** Every pile, placed in plan; a pile cap lists the ones it stands on. */
	piles: IPile[];
	tieBeams: ITieBeam[];
	groundSlabs: IGroundSlab[];
	/** Cantilever retaining walls and basement walls, designed per metre run (9 Substructure). */
	retainingWalls?: IRetainingWall[];
	/** Static pile load tests at the site. */
	loadTests?: IPileLoadTest[];
	design: ISubstructureDesign;
	[key: string]: unknown;
}

/** A retaining or basement wall (mm, project datum); the backend's model holds the rest. */
export interface IRetainingWall {
	id: string;
	kind?: 'cantilever' | 'basement';
	/** Plan line of the wall's soil face [[x, y], ...] mm. */
	path: Point[];
	topLevel: number;
	foundingLevel: number;
	stemTop?: number;
	stemBottom?: number;
	baseThickness?: number;
	toe?: number;
	heel?: number;
	/** Basement walls: levels of the floors that prop it [mm]. */
	supports?: number[];
	/** The wall of 6 BIM it is (its earth pressure then loads the analysis model as case H). */
	wall?: string;
	material: string;
	[key: string]: unknown;
}

/** A new cantilever wall 5 m long retaining 3 m of ground at the finished ground level. */
export function newRetainingWall(document: ISubstructure, context: ISiteContext): IRetainingWall {
	const ground = context.groundLevel;
	return {
		id: nextId('RW', (document.retainingWalls ?? []).map(w => w.id)),
		kind: 'cantilever',
		path: [[0, 0], [5000, 0]],
		topLevel: ground,
		frontLevel: ground - 3000,
		foundingLevel: ground - 3500,
		stemTop: 200,
		stemBottom: 300,
		baseThickness: 400,
		toe: 700,
		heel: 1600,
		material: context.defaultMaterial ?? context.materials[0] ?? '',
	};
}

/** BNBC 2020 Part 6 Table 6.3.10a: permanent structure (25 to 100 years), normal control. */
export const PILE_FACTOR_OF_SAFETY = 2.5;
/**
 * BNBC 2020 Part 6 Sec 3.10.1.18 (bored piles by Sec 3.10.4.10): the least overall factor of
 * safety of a pile in compression, without and with a load test at the site.
 */
export const PILE_FS_NO_LOAD_TEST = 3.0;
export const PILE_FS_LOAD_TEST = 2.0;
/** The least factor of safety with the code pack's SPT relations, as the backend applies it. */
export const PILE_FS_SPT = 3.5;

/**
 * The overall factors of safety of a pile the design uses (as the backend's
 * `FactorsOfSafety.for_method`): the given or default compression factor raised to 3.0 without a
 * load test at the site (2.0 with one), both raised to 3.5 with the SPT relations. `raised`
 * says why the compression factor is above the one given, if it is.
 */
export function pileFactorsUsed(design: ISubstructureDesign): { readonly compression: number; readonly uplift: number; readonly given: number; readonly raised?: 'loadTest' | 'spt' } {
	const fs = design.factorOfSafety ?? {};
	const given = typeof fs.pileCompression === 'number' ? fs.pileCompression : PILE_FACTOR_OF_SAFETY;
	const uplift = typeof fs.pileUplift === 'number' ? fs.pileUplift : PILE_FACTOR_OF_SAFETY;
	const least = Math.max(given, fs.pileLoadTest === true ? PILE_FS_LOAD_TEST : PILE_FS_NO_LOAD_TEST);
	const spt = design.pileCapacity === 'spt' || (design.pileCapacity as string | undefined) === 'bnbcSpt';
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
	return { schema: SUBSTRUCTURE_SCHEMA_ID, foundations: [], pileTypes: [], piles: [], tieBeams: [], groundSlabs: [], design: {} };
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

/**
 * Reads the file's text; lists and objects it lacks are filled in, unknown fields are kept. Pile
 * caps of an earlier version are read as piles placed in plan ({@link upgradePileCaps}; `columns`
 * places a cap without a centre at its columns).
 */
export function parseSubstructure(text: string, columns: readonly IColumnBase[] = []): ParsedSubstructure {
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
	for (const list of ['foundations', 'pileTypes', 'piles', 'tieBeams', 'groundSlabs', 'loadTests']) {
		if (value[list] !== undefined && !Array.isArray(value[list])) {
			return { kind: 'error', message: localize('sub.badList', "The substructure's {0} are not a list.", list) };
		}
	}
	const document = value as ISubstructure;
	document.foundations = (document.foundations ?? []).filter(isRecord) as IFoundation[];
	document.pileTypes = (document.pileTypes ?? []).filter(isRecord) as IPileType[];
	document.tieBeams = (document.tieBeams ?? []).filter(isRecord) as ITieBeam[];
	document.groundSlabs = (document.groundSlabs ?? []).filter(isRecord) as IGroundSlab[];
	document.piles = (document.piles ?? []).filter(p => isRecord(p) && typeof p.id === 'string' && isPoint(p.position)) as IPile[];
	if (document.loadTests !== undefined) {
		document.loadTests = (document.loadTests ?? []).filter(isRecord).map(test => ({ ...test, points: Array.isArray(test.points) ? test.points.filter(isPoint) : [] })) as IPileLoadTest[];
	}
	document.design = isRecord(document.design) ? document.design : {};
	if ((document.design.pileCapacity as string | undefined) === 'bnbcSpt') {
		document.design.pileCapacity = 'spt';
	}
	if (document.pileGrid !== undefined) {
		const grid = document.pileGrid as unknown;
		if (isRecord(grid)) {
			const lines = (value: unknown) => records(value).filter(g => typeof g.position === 'number').map(g => ({ label: String(g.label ?? ''), position: g.position as number }));
			document.pileGrid = { ...grid, x: lines(grid.x), y: lines(grid.y) };
			if (grid.origin !== undefined && !isPoint(grid.origin)) {
				delete document.pileGrid.origin;
			}
		} else {
			delete document.pileGrid;
		}
	}
	for (const foundation of document.foundations) {
		if (foundation.columns !== undefined) {
			foundation.columns = Array.isArray(foundation.columns) ? foundation.columns.filter(c => typeof c === 'string') : [];
		}
		for (const key of ['path', 'outline'] as const) {
			if (foundation[key] !== undefined) {
				foundation[key] = Array.isArray(foundation[key]) ? foundation[key]!.filter(isPoint) : [];
			}
		}
		if (foundation.piles !== undefined) {
			// Pile ids; the offsets of an earlier version are kept for upgradePileCaps.
			foundation.piles = Array.isArray(foundation.piles) ? (foundation.piles as unknown[]).filter(p => typeof p === 'string' || isPoint(p)) as string[] : [];
		}
		if (foundation.center !== undefined && !isPoint(foundation.center)) {
			delete foundation.center;
		}
	}
	upgradePileCaps(document, columns);
	return { kind: 'document', document };
}

/** The marks of piles: PL1, PL2, ... */
export const PILE_PREFIX = 'PL';

function round1(value: number): number {
	return Math.round(value * 10) / 10 + 0;
}

/**
 * Brings the pile caps of an earlier version (a `pileType` and pile offsets from the cap's centre
 * in its local axes) to piles placed in plan, as the backend's `upgrade_pile_caps`: each offset
 * becomes a pile PLn of the cap's pile type, the cap lists them and keeps its centre (the
 * centroid of its `columns` when it had none). A cap without a centre whose columns are not
 * known is left as it is (the checks report it). Returns whether anything changed.
 */
export function upgradePileCaps(document: ISubstructure, columns: readonly IColumnBase[] = []): boolean {
	let changed = false;
	for (const f of document.foundations) {
		const raw = (f.piles ?? []) as unknown[];
		const offsets = raw.filter(isPoint) as Point[];
		if (f.type !== 'pileCap' || (!offsets.length && f.pileType === undefined)) {
			continue;
		}
		const carried = columns.filter(c => f.columns?.includes(c.id));
		const center = f.center ?? centroid(carried.map(c => [c.x, c.y] as const));
		if (!center) {
			continue;
		}
		f.center = [round1(center[0]), round1(center[1])];
		const type = typeof f.pileType === 'string' ? f.pileType : '';
		const ids = raw.filter((p): p is string => typeof p === 'string');
		for (const [dx, dy] of offsets) {
			const id = nextId(PILE_PREFIX, document.piles.map(p => p.id));
			const [x, y] = toGlobal(f.center, dx, dy, num(f.rotation));
			document.piles.push({ id, type, position: [round1(x), round1(y)] });
			ids.push(id);
		}
		f.piles = ids;
		delete f.pileType;
		changed = true;
	}
	return changed;
}

/** Whether a pile cap still has offsets of an earlier version (no centre to place them from). */
export function hasOldPiles(foundation: IFoundation): boolean {
	return ((foundation.piles ?? []) as unknown[]).some(isPoint) || foundation.pileType !== undefined;
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
	/** Ids of the footings still drawn in the building model (Part 6), which the substructure replaces. */
	readonly bimFootings?: readonly string[];
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
		bimFootings: elements.filter(e => e.kind === 'footing').map(e => String(e.id)),
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

/** The piles a pile cap stands on, in its order (unknown ids left out). */
export function capPiles(foundation: IFoundation, document: ISubstructure): IPile[] {
	if (foundation.type !== 'pileCap') {
		return [];
	}
	const byId = new Map(document.piles.map(p => [p.id, p]));
	return (foundation.piles ?? []).flatMap(id => {
		const pile = typeof id === 'string' ? byId.get(id) : undefined;
		return pile ? [pile] : [];
	});
}

/** The plan positions of a pile cap's piles [mm]. */
export function pilePositions(foundation: IFoundation, document: ISubstructure): Point[] {
	return capPiles(foundation, document).map(p => p.position);
}

/** The pile type of a pile cap's piles (one per cap). */
export function capPileType(foundation: IFoundation, document: ISubstructure): IPileType | undefined {
	const first = capPiles(foundation, document)[0];
	return first ? document.pileTypes.find(t => t.id === first.type) : undefined;
}

/** A pile cap's piles as offsets [mm] from its centre in its local axes. */
export function pileOffsets(foundation: IFoundation, document: ISubstructure): Point[] {
	const center = foundation.center;
	if (!center) {
		return [];
	}
	return capPiles(foundation, document).map(p => toLocal(center, p.position, num(foundation.rotation)));
}

/** The point `p` in the axes turned by `degrees` about `center` (the inverse of {@link toGlobal}). */
export function toLocal(center: readonly [number, number], p: readonly [number, number], degrees = 0): Point {
	const a = degrees * Math.PI / 180;
	const dx = p[0] - center[0];
	const dy = p[1] - center[1];
	return [dx * Math.cos(a) + dy * Math.sin(a), -dx * Math.sin(a) + dy * Math.cos(a)];
}

/** The cap each pile is under: pile id → foundation id. */
export function pileCaps(document: ISubstructure): Map<string, string> {
	const caps = new Map<string, string>();
	for (const f of document.foundations) {
		if (f.type === 'pileCap') {
			for (const id of f.piles ?? []) {
				if (typeof id === 'string' && !caps.has(id)) {
					caps.set(id, f.id);
				}
			}
		}
	}
	return caps;
}

/** The pile counts of the layout presets. */
export const PILE_LAYOUTS = [2, 3, 4, 5, 6, 9] as const;
/** The standard pile groups placed under a column. */
export const PILE_GROUPS = [2, 3, 4, 5, 6] as const;
/**
 * BNBC 2020 Part 6 Sec 3.10.1.19 and 3.10.1.30: piles at least 2.5 diameters and 750 mm apart
 * centre to centre; friction piles generally 3 diameters.
 */
export const MIN_SPACING_FACTOR = 2.5;
export const MIN_PILE_SPACING = 750;
/** The spacing factor k of the pile groups (s = k · D) unless the engineer gives another. */
export const DEFAULT_SPACING_FACTOR = 3;

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
export function pileLayout(count: number, diameter: number, factor = DEFAULT_SPACING_FACTOR): Point[] {
	// Never closer than the code minimum, whatever k is asked for.
	const s = Math.max(Math.max(factor, MIN_SPACING_FACTOR) * diameter, MIN_PILE_SPACING);
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

/** The bar diameters a minimum mesh is chosen from [mm]. */
const MESH_DIAS = [12, 16, 20, 25];

/**
 * The lightest mesh with at least As,min = 0.0018 h per metre (ACI 318-19 Table 7.6.1.1 at
 * fy 420; less for stronger bars, so the mesh suits them too), at a spacing of at most
 * min(3h, 450 mm) (ACI 318-19 7.7.2.3) and at least 125 mm, in steps of 25 mm: what the
 * backend's `minimum_mesh` gives a foundation without bars.
 */
export function minimumMesh(thickness: number): IBarMesh {
	const need = 0.0018 * thickness * 1000;
	const limit = Math.floor(Math.min(3 * thickness, 450) / 25) * 25;
	for (const dia of MESH_DIAS) {
		const spacing = Math.min(Math.floor(Math.PI * dia * dia / 4 * 1000 / need / 25) * 25, limit);
		if (spacing >= 125) {
			return { dia, spacing };
		}
	}
	return { dia: 25, spacing: Math.max(Math.floor(Math.PI * 25 * 25 / 4 * 1000 / need / 25) * 25, 75) };
}

/**
 * The reinforcement a new foundation of `thickness` starts with: the minimum mesh both ways at
 * the bottom ({@link minimumMesh}), and at the top too for a raft (it hogs between the
 * columns), 75 mm cover.
 */
export function defaultReinforcement(context: ISiteContext, thickness = 450, top = false): IPlanarReinforcement {
	const mesh = minimumMesh(thickness);
	const reinforcement: IPlanarReinforcement = { cover: 75, bottomX: { ...mesh }, bottomY: { ...mesh }, ...(top ? { topX: { ...mesh }, topY: { ...mesh } } : {}) };
	return context.barMaterial ? { material: context.barMaterial, ...reinforcement } : reinforcement;
}

/** The value most of `values` have (the first of a tie); undefined for none. */
function mostCommon(values: readonly (string | undefined)[]): string | undefined {
	const counts = new Map<string, number>();
	for (const v of values) {
		if (v) {
			counts.set(v, (counts.get(v) ?? 0) + 1);
		}
	}
	let best: string | undefined;
	for (const [v, n] of counts) {
		if (best === undefined || n > counts.get(best)!) {
			best = v;
		}
	}
	return best;
}

/**
 * The id of a new foundation, in the project's scheme (N-U9): a raft `R1`, `R2`...; a footing
 * or cap under columns named like `C-A1` or `C-A1-L1` (New Building's) `F-A1`, `F-A1-B1` for
 * several (as New Building and the import name them), else `F1`, `F2`...
 */
export function foundationId(document: ISubstructure, type: FoundationType, columns: readonly string[]): string {
	const taken = document.foundations.map(f => f.id);
	if (type === 'raft') {
		return nextId('R', taken);
	}
	const grid = columns.map(c => /^C-(.+?)(?:-L\d+)?$/.exec(c)?.[1]);
	if (columns.length && grid.every(g => !!g)) {
		const id = `F-${columns.length === 1 ? grid[0] : `${grid[0]}-${grid[grid.length - 1]}`}`;
		if (!taken.includes(id)) {
			return id;
		}
	}
	return nextId('F', taken);
}

function base(document: ISubstructure, context: ISiteContext, type: FoundationType, columns: readonly IColumnBase[], extra: Partial<IFoundation>): IFoundation {
	const foundation: IFoundation = { id: foundationId(document, type, columns.map(c => c.id)), type, columns: columns.map(c => c.id), ...extra };
	// The concrete and bars the project's foundations already use, else the project's (N-U9).
	const material = mostCommon(document.foundations.map(f => f.material)) ?? context.defaultMaterial;
	if (material) {
		foundation.material = material;
	}
	const reinforcement = defaultReinforcement(context, num(foundation.thickness, 450), type === 'raft');
	const bars = mostCommon(document.foundations.map(f => f.reinforcement?.material));
	foundation.reinforcement = bars ? { ...reinforcement, material: bars } : reinforcement;
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
		center: [Math.round(center[0]) + 0, Math.round(center[1]) + 0],
		length: roundUp(2 * spanX + 1500, 50), width: roundUp(Math.max(1500, 2 * spanY + 1500), 50), thickness: 600,
	});
	if (rotation) {
		footing.rotation = rotation;
	}
	return footing;
}

/**
 * A pile cap of `pileType` over a standard group of `count` piles at `factor` diameters under
 * `columns` (centred on them, turned with the pile grid): the piles are added to the document,
 * the cap is returned (not added).
 */
export function newPileCap(document: ISubstructure, context: ISiteContext, columns: readonly IColumnBase[], pileType: IPileType, count = 4, factor = DEFAULT_SPACING_FACTOR): IFoundation {
	const piles = placePileGroup(document, columns, pileType, count, factor);
	return formCap(document, context, piles, pileType, columns);
}

/** Adds piles of `type` at `points` (marks PL1, PL2, ...); returns them. */
export function addPiles(document: ISubstructure, type: string, points: readonly Point[]): IPile[] {
	const added: IPile[] = [];
	for (const [x, y] of points) {
		const pile: IPile = { id: nextId(PILE_PREFIX, document.piles.map(p => p.id)), type, position: [Math.round(x) + 0, Math.round(y) + 0] };
		document.piles.push(pile);
		added.push(pile);
	}
	return added;
}

/**
 * Places a standard group of `count` piles of `pileType` at `factor` diameters centre to centre
 * ({@link pileLayout}) under `columns`: centred on their centroid (or on `at`), turned with the
 * pile grid. Returns the piles added.
 */
export function placePileGroup(document: ISubstructure, columns: readonly IColumnBase[], pileType: IPileType, count: number, factor = DEFAULT_SPACING_FACTOR, at?: Point): IPile[] {
	const center = at ?? centroid(columns.map(c => [c.x, c.y] as const));
	if (!center) {
		return [];
	}
	const rotation = num(document.pileGrid?.rotation);
	const offsets = count === 1 ? [[0, 0] as Point] : pileLayout(count, pileType.diameter, factor);
	return addPiles(document, pileType.id, offsets.map(([dx, dy]) => toGlobal(center, dx, dy, rotation)));
}

/**
 * The cap around piles of `diameter` at plan `points`, its sides along `rotation` [°]: the
 * piles' extent plus their radius and {@link CAP_EDGE} each side in 50 mm steps, centred on that
 * extent (not on any column), 600 mm or two diameters thick.
 */
export function capAround(points: readonly Point[], diameter: number, rotation = 0): { center: Point; length: number; width: number; thickness: number; rotation?: number } {
	const origin: Point = points[0] ?? [0, 0];
	const local = points.map(p => toLocal(origin, p, rotation));
	const [x0, x1] = [Math.min(...local.map(p => p[0])), Math.max(...local.map(p => p[0]))];
	const [y0, y1] = [Math.min(...local.map(p => p[1])), Math.max(...local.map(p => p[1]))];
	const edge = diameter / 2 + CAP_EDGE;
	const center = toGlobal(origin, (x0 + x1) / 2, (y0 + y1) / 2, rotation);
	return {
		center: [Math.round(center[0]) + 0, Math.round(center[1]) + 0],
		length: roundUp(x1 - x0 + 2 * edge, 50),
		width: roundUp(y1 - y0 + 2 * edge, 50),
		thickness: Math.max(600, roundUp(2 * diameter, 50)),
		...(rotation ? { rotation } : {}),
	};
}

/** A pile cap over `piles` (all of `pileType`) carrying `columns`. */
function formCap(document: ISubstructure, context: ISiteContext, piles: readonly IPile[], pileType: IPileType, columns: readonly IColumnBase[]): IFoundation {
	const cap = base(document, context, 'pileCap', columns, { ...capAround(piles.map(p => p.position), pileType.diameter, num(document.pileGrid?.rotation)), piles: piles.map(p => p.id) });
	cap.reinforcement = defaultReinforcement(context, num(cap.thickness, 600));
	return cap;
}

/**
 * Make Pile Cap: a cap over the piles `pileIds`, carrying `columns`, or when none are given the
 * column bases inside its outline that stand on no foundation yet. The cap's centre is the
 * centre of the pile group, so it may be eccentric to its columns (the design takes that
 * moment). Returns the cap (not added to the document), or why it cannot be made.
 */
export function makePileCap(document: ISubstructure, context: ISiteContext, pileIds: readonly string[], columns?: readonly IColumnBase[]): { cap?: IFoundation; error?: string } {
	const byId = new Map(document.piles.map(p => [p.id, p]));
	const piles = pileIds.map(id => byId.get(id)).filter((p): p is IPile => !!p);
	if (!piles.length) {
		return { error: localize('sub.makeCapNone', "Select the piles the cap is to stand on.") };
	}
	const caps = pileCaps(document);
	const capped = piles.filter(p => caps.has(p.id));
	if (capped.length) {
		return { error: localize('sub.makeCapTaken', "{0} already under a pile cap ({1}).", capped.map(p => p.id).join(', '), [...new Set(capped.map(p => caps.get(p.id)))].join(', ')) };
	}
	const types = [...new Set(piles.map(p => p.type))];
	if (types.length > 1) {
		return { error: localize('sub.makeCapTypes', "The piles of one cap are of one pile type; these are {0}.", types.join(', ')) };
	}
	const pileType = document.pileTypes.find(t => t.id === types[0]);
	if (!pileType) {
		return { error: localize('sub.makeCapNoType', "Pile type {0} does not exist.", types[0]) };
	}
	let carried = columns ?? [];
	if (!columns) {
		const outline = foundationOutlines({ id: '', type: 'pileCap', ...capAround(piles.map(p => p.position), pileType.diameter, num(document.pileGrid?.rotation)) }, context)[0] ?? [];
		const taken = new Set(document.foundations.flatMap(f => f.columns ?? []));
		carried = context.columns.filter(c => !taken.has(c.id) && insidePolygon([c.x, c.y], outline));
	}
	return { cap: formCap(document, context, piles, pileType, carried) };
}

/**
 * Deletes the piles `ids` and takes them out of their caps. Returns the caps left with no piles
 * (they are kept: the checks ask for piles).
 */
export function deletePiles(document: ISubstructure, ids: ReadonlySet<string>): string[] {
	document.piles = document.piles.filter(p => !ids.has(p.id));
	const emptied: string[] = [];
	for (const f of document.foundations) {
		if (f.type === 'pileCap' && f.piles?.some(p => ids.has(p))) {
			f.piles = f.piles.filter(p => !ids.has(p));
			if (!f.piles.length) {
				emptied.push(f.id);
			}
		}
	}
	return emptied;
}

/** Moves the piles `ids` by (dx, dy) [mm]. */
export function movePiles(document: ISubstructure, ids: ReadonlySet<string>, dx: number, dy: number): void {
	for (const pile of document.piles) {
		if (ids.has(pile.id)) {
			pile.position = [Math.round(pile.position[0] + dx) + 0, Math.round(pile.position[1] + dy) + 0];
		}
	}
}

/** Fits a pile cap's outline round its piles again (after they moved), keeping its thickness. */
export function refitCap(document: ISubstructure, cap: IFoundation): void {
	const pileType = capPileType(cap, document);
	const points = pilePositions(cap, document);
	if (!pileType || !points.length) {
		return;
	}
	const fitted = capAround(points, pileType.diameter, num(cap.rotation));
	cap.center = fitted.center;
	cap.length = fitted.length;
	cap.width = fitted.width;
}

/** The foundation that carries the column or wall `id`. */
export function foundationOf(document: ISubstructure, id: string): IFoundation | undefined {
	return document.foundations.find(f => f.columns?.includes(id));
}

/** Whether a tie beam joins the foundations `a` and `b` already (either way). */
export function tied(document: ISubstructure, a: string, b: string): boolean {
	return document.tieBeams.some(t => (t.from === a && t.to === b) || (t.from === b && t.to === a));
}

/**
 * Grade (tie) beams along the grid lines: the column bases on one line (the same x, or the same
 * y, within 1 mm), in order along it, each tied to the next one's foundation where the two stand
 * on different foundations not tied yet. Returns the tie beams added to the document.
 */
export function connectGradeBeams(document: ISubstructure, context: ISiteContext): ITieBeam[] {
	const added: ITieBeam[] = [];
	const lines = (key: (c: IColumnBase) => number, along: (c: IColumnBase) => number) => {
		const groups = new Map<number, IColumnBase[]>();
		for (const column of context.columns) {
			const k = Math.round(key(column));
			const line = [...groups.keys()].find(g => Math.abs(g - k) <= 1) ?? k;
			groups.set(line, [...(groups.get(line) ?? []), column]);
		}
		for (const columns of groups.values()) {
			const ids = [...columns].sort((a, b) => along(a) - along(b)).map(c => foundationOf(document, c.id)?.id);
			for (let i = 1; i < ids.length; i++) {
				const [a, b] = [ids[i - 1], ids[i]];
				if (a && b && a !== b && !tied(document, a, b)) {
					const tie = newTieBeam(document, context, a, b);
					document.tieBeams.push(tie);
					added.push(tie);
				}
			}
		}
	};
	lines(c => c.x, c => c.y);
	lines(c => c.y, c => c.x);
	return added;
}

// ───────────────────────────── the pile grid ─────────────────────────────

/** The plan position [mm] of the pile grid's local point (x, y). */
export function gridPoint(grid: IPileGrid, x: number, y: number): Point {
	return toGlobal(grid.origin ?? [0, 0], x, y, num(grid.rotation));
}

/** Every crossing of the pile grid's lines: its x and y line labels and plan position. */
export function gridIntersections(grid: IPileGrid | undefined): { x: string; y: string; point: Point }[] {
	return grid ? grid.x.flatMap(gx => grid.y.map(gy => ({ x: gx.label, y: gy.label, point: gridPoint(grid, gx.position, gy.position) }))) : [];
}

/** The labels a, b, ..., z, aa, ab, ... (the pile grid's x lines). */
function letters(index: number): string {
	let label = '';
	for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
		label = String.fromCharCode(97 + (n - 1) % 26) + label;
	}
	return label;
}

/** The pile grid's line labels: x lines a, b, c, ...; y lines p1, p2, ... (apart from the building's A, B / 1, 2). */
export function gridLabels(axis: 'x' | 'y', count: number): string[] {
	return Array.from({ length: count }, (_, i) => axis === 'x' ? letters(i) : `p${i + 1}`);
}

/**
 * Reads spacings "4@1500, 2000" (n @ spacing, or single spacings, separated by commas or spaces)
 * [mm]: the distances between consecutive lines. Empty: no spacing (one line).
 */
export function parseSpacings(text: string): { value?: number[]; error?: string } {
	const spacings: number[] = [];
	for (const part of text.split(/[\s,;]+/).filter(Boolean)) {
		const match = /^(?:(?<count>\d+)\s*[@x×*])?(?<spacing>\d+(?:\.\d+)?)$/i.exec(part);
		const count = match?.groups?.count ? Number(match.groups.count) : 1;
		const spacing = Number(match?.groups?.spacing);
		if (!match || !(count >= 1 && count <= 200) || !(spacing > 0)) {
			return { error: localize('sub.v.spacings', "Write the spacings in mm as count@spacing or single spacings, e.g. 4@1500, 2000.") };
		}
		spacings.push(...Array.from({ length: count }, () => spacing));
	}
	return { value: spacings };
}

/** The spacings between consecutive lines, as {@link parseSpacings} reads them ("4@1500 2000"). */
export function formatSpacings(lines: readonly IPileGridLine[]): string {
	const positions = [...lines].map(l => l.position).sort((a, b) => a - b);
	const parts: string[] = [];
	for (let i = 1; i < positions.length;) {
		const spacing = positions[i] - positions[i - 1];
		let count = 1;
		while (i + count < positions.length && Math.abs(positions[i + count] - positions[i + count - 1] - spacing) < 0.5) {
			count++;
		}
		parts.push(count > 1 ? `${count}@${formatNumber(spacing, 0)}` : formatNumber(spacing, 0));
		i += count;
	}
	return parts.join(' ');
}

/** The lines at the first line's position (0) and then `spacings` apart, with the labels of `axis`. */
export function gridLines(axis: 'x' | 'y', spacings: readonly number[], start = 0): IPileGridLine[] {
	const labels = gridLabels(axis, spacings.length + 1);
	let at = start;
	return labels.map((label, i) => {
		const line = { label, position: at };
		at += spacings[i] ?? 0;
		return line;
	});
}

/**
 * A pile grid to start with: over the column bases (or the origin) and a pile group's reach
 * beyond them, lines 3 diameters of the first pile type apart (1500 mm without one) both ways,
 * its origin at the lower left, along the global axes.
 */
export function newPileGrid(document: ISubstructure, context: ISiteContext): IPileGrid {
	const diameter = document.pileTypes[0]?.diameter ?? 500;
	const spacing = roundUp(Math.max(DEFAULT_SPACING_FACTOR * diameter, MIN_PILE_SPACING), 50);
	const xs = context.columns.map(c => c.x);
	const ys = context.columns.map(c => c.y);
	const reach = spacing;
	const [x0, x1] = xs.length ? [Math.min(...xs) - reach, Math.max(...xs) + reach] : [0, 4 * spacing];
	const [y0, y1] = ys.length ? [Math.min(...ys) - reach, Math.max(...ys) + reach] : [0, 4 * spacing];
	const count = (span: number) => Math.max(1, Math.ceil(span / spacing - 1e-9));
	return {
		origin: [Math.floor(x0 / 50) * 50, Math.floor(y0 / 50) * 50],
		rotation: 0,
		x: gridLines('x', Array.from({ length: count(x1 - x0) }, () => spacing)),
		y: gridLines('y', Array.from({ length: count(y1 - y0) }, () => spacing)),
	};
}

/** What a point snaps to on the plan: a pile grid crossing, a column's centre, a pile, or the 50 mm raster. */
export interface ISnap {
	readonly point: Point;
	readonly kind: 'grid' | 'column' | 'pile' | 'free';
	readonly label?: string;
}

/**
 * The point `p` [mm] snapped, within `tolerance` [mm], to the nearest pile grid crossing, else a
 * column base's centre, else a pile's centre (`piles`: false leaves them out, for placing a new
 * pile), else rounded to 50 mm.
 */
export function snapPoint(p: Point, document: ISubstructure, context: ISiteContext, tolerance: number, piles = true): ISnap {
	const nearest = <T>(items: readonly T[], at: (item: T) => Point): T | undefined => {
		let best: T | undefined;
		let distance = tolerance;
		for (const item of items) {
			const q = at(item);
			const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
			if (d <= distance) {
				best = item;
				distance = d;
			}
		}
		return best;
	};
	const crossing = nearest(gridIntersections(document.pileGrid), c => c.point);
	if (crossing) {
		return { point: [round1(crossing.point[0]), round1(crossing.point[1])], kind: 'grid', label: `${crossing.x}-${crossing.y}` };
	}
	const column = nearest(context.columns, c => [c.x, c.y]);
	if (column) {
		return { point: [column.x, column.y], kind: 'column', label: column.id };
	}
	const pile = piles ? nearest(document.piles, q => q.position) : undefined;
	if (pile) {
		return { point: pile.position, kind: 'pile', label: pile.id };
	}
	return { point: [Math.round(p[0] / 50) * 50, Math.round(p[1] / 50) * 50], kind: 'free' };
}

/** The pile grid crossings inside the plan box between corners `a` and `b`. */
export function intersectionsInBox(grid: IPileGrid | undefined, a: Point, b: Point): Point[] {
	const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
	const [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
	return gridIntersections(grid).map(c => c.point).filter(([x, y]) => x >= x0 - 0.5 && x <= x1 + 0.5 && y >= y0 - 0.5 && y <= y1 + 0.5);
}

/** The piles whose centres lie inside the plan box between corners `a` and `b`. */
export function pilesInBox(document: ISubstructure, a: Point, b: Point): IPile[] {
	const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
	const [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
	return document.piles.filter(({ position: [x, y] }) => x >= x0 && x <= x1 && y >= y0 && y <= y1);
}

/** Whether a pile stands at `point` already (within 1 mm). */
export function pileAt(document: ISubstructure, point: Point): IPile | undefined {
	return document.piles.find(p => Math.hypot(p.position[0] - point[0], p.position[1] - point[1]) < 1);
}

/**
 * The pile caps of the document as offsets in their axes, for the checks: piles of an earlier
 * version are their own offsets, piles in plan go through the cap's centre and rotation.
 */
function capOffsets(f: IFoundation, document: ISubstructure): Point[] {
	return hasOldPiles(f) ? ((f.piles ?? []) as unknown[]).filter(isPoint) as Point[] : pileOffsets(f, document);
}

/**
 * BNBC 2020 Part 6 Table 6.3.11 (guidance for bored piles, compression only, fy 420): the least
 * bars and hoops by diameter, as [largest diameter, bars, bar Ø, hoop Ø, hoop spacing] in mm (the
 * rows of the backend's `min_reinforcement_note`).
 */
const PILE_BARS: readonly (readonly [number, number, number, number, number])[] = [
	[450, 6, 16, 8, 200], [600, 8, 16, 8, 250], [900, 10, 16, 10, 300], [1200, 12, 16, 10, 300],
	[1800, 12, 20, 10, 400], [2100, 16, 20, 10, 400], [2400, 16, 25, 12, 500],
];

/** The bars a pile of `diameter` starts with: BNBC 2020 Part 6 Table 6.3.11's, 75 mm cover. */
export function defaultPileReinforcement(diameter: number, context: ISiteContext): IPileReinforcement {
	const [, count, dia, hoop, spacing] = PILE_BARS.find(row => diameter <= row[0] + 1e-6) ?? PILE_BARS[PILE_BARS.length - 1];
	const reinforcement: IPileReinforcement = { cover: 75, longitudinal: [{ position: 'perimeter', count, dia }], transverse: { type: 'tie', dia: hoop, spacing } };
	return context.barMaterial ? { material: context.barMaterial, ...reinforcement } : reinforcement;
}

/** "8Ø16" for a pile's longitudinal bars; empty without any. */
export function formatPileBars(reinforcement: IPileReinforcement | undefined): string {
	return (reinforcement?.longitudinal ?? []).map(g => `${g.count}Ø${formatNumber(g.dia, 0)}`).join(' + ');
}

/** Reads "8Ø16" (also "8T16", "8#16", "8-16", "8 x 16"); empty clears it. */
export function parsePileBars(text: string): { value?: { count: number; dia: number }; error?: string } {
	const trimmed = text.trim();
	if (!trimmed) {
		return {};
	}
	const match = /^(?<count>\d+)\s*(?:[ØøT#x×-]|\s)\s*(?<dia>\d+(?:\.\d+)?)\s*(?:mm)?$/i.exec(trimmed);
	const count = Number(match?.groups?.count);
	const dia = Number(match?.groups?.dia);
	if (!match || !(count >= 4) || !(dia > 0)) {
		return { error: localize('sub.v.pileBars', "Write the bars as count Ø diameter, at least 4 bars, e.g. 8Ø16.") };
	}
	return { value: { count, dia } };
}

/** "Ø8@250" for a pile's ties (a spiral: "spiral Ø8@75"); empty without. */
export function formatPileTies(reinforcement: IPileReinforcement | undefined): string {
	const t = reinforcement?.transverse;
	return t ? `${t.type === 'spiral' ? 'spiral ' : ''}Ø${formatNumber(t.dia, 0)}@${formatNumber(t.spacing, 0)}` : '';
}

/** Reads "Ø8@250" or "spiral Ø8@75"; empty clears it. */
export function parsePileTies(text: string): { value?: { type: 'tie' | 'spiral'; dia: number; spacing: number }; error?: string } {
	const trimmed = text.trim();
	if (!trimmed) {
		return {};
	}
	const match = /^(?<spiral>spiral\s*)?[ØøT#]?\s*(?<dia>\d+(?:\.\d+)?)\s*(?:@|\/)\s*(?<spacing>\d+(?:\.\d+)?)\s*(?:mm)?$/i.exec(trimmed);
	const dia = Number(match?.groups?.dia);
	const spacing = Number(match?.groups?.spacing);
	if (!match || !(dia > 0) || !(spacing > 0)) {
		return { error: localize('sub.v.pileTies', "Write the ties as Ø diameter @ spacing in mm, e.g. Ø8@250, or spiral Ø8@75.") };
	}
	return { value: { type: match.groups?.spiral ? 'spiral' : 'tie', dia, spacing } };
}

/** A pile type to start with: bored, 500 mm, 18 m, with the bars of BNBC 2020 Part 6 Table 6.3.11. */
export function newPileType(document: ISubstructure, context: ISiteContext): IPileType {
	const pile: IPileType = { id: nextId('P', document.pileTypes.map(p => p.id)), kind: 'bored', diameter: 500, length: 18000 };
	if (context.defaultMaterial) {
		pile.material = context.defaultMaterial;
	}
	pile.reinforcement = defaultPileReinforcement(pile.diameter, context);
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

/** A 150 mm slab on grade over the extent of the columns (else 10 × 10 m), under 5 kPa. */
export function newGroundSlab(document: ISubstructure, context: ISiteContext): IGroundSlab {
	const xs = context.columns.map(c => c.x);
	const ys = context.columns.map(c => c.y);
	const [x0, x1] = xs.length ? [Math.min(...xs), Math.max(...xs)] : [0, 10000];
	const [y0, y1] = ys.length ? [Math.min(...ys), Math.max(...ys)] : [0, 10000];
	const slab: IGroundSlab = {
		id: nextId('GS', document.groundSlabs.map(s => s.id)),
		outline: [[x0, y0], [Math.max(x1, x0 + 1000), y0], [Math.max(x1, x0 + 1000), Math.max(y1, y0 + 1000)], [x0, Math.max(y1, y0 + 1000)]],
		thickness: 150,
		uniformLoad: 5,
		pointLoad: 0,
		contactSide: 150,
	};
	if (context.defaultMaterial) {
		slab.material = context.defaultMaterial;
	}
	return slab;
}

export function footingSectionLabel(section: FootingSection | string): string {
	switch (section) {
		case 'flat': return localize('sub.section.flat', "Flat");
		case 'sloped': return localize('sub.section.sloped', "Sloped");
		case 'stepped': return localize('sub.section.stepped', "Stepped");
		default: return String(section);
	}
}

/** A tie beam between two foundations, of the first beam type. */
export function newTieBeam(document: ISubstructure, context: ISiteContext, from: string, to: string): ITieBeam {
	const beam: ITieBeam = { id: nextId('TB', document.tieBeams.map(t => t.id)), from, to };
	if (context.beamTypes[0]) {
		beam.type = context.beamTypes[0].id;
	}
	return beam;
}

/**
 * Sets a pile cap's piles to a standard group of `count` piles of `pileType` at `factor`
 * diameters (in place of the ones it had, which are deleted), centred on its columns (else on
 * the cap), and fits the cap round them.
 */
export function applyPileLayout(document: ISubstructure, context: ISiteContext, foundation: IFoundation, pileType: IPileType, count: number, factor = DEFAULT_SPACING_FACTOR): void {
	const at = centroid(carriedColumns(foundation, context).map(c => [c.x, c.y] as const)) ?? foundationCenter(foundation, context);
	deletePiles(document, new Set(foundation.piles ?? []));
	const piles = placePileGroup(document, [], pileType, count, factor, at);
	foundation.piles = piles.map(p => p.id);
	refitCap(document, foundation);
}

/** Sets the pile type of a pile cap's piles. */
export function setCapPileType(document: ISubstructure, foundation: IFoundation, pileType: string): void {
	const ids = new Set(foundation.piles ?? []);
	for (const pile of document.piles) {
		if (ids.has(pile.id)) {
			pile.type = pileType;
		}
	}
}

/** The column bases no foundation carries (a raft carries those inside its outline). */
export function uncoveredColumns(document: ISubstructure, context: ISiteContext): IColumnBase[] {
	return context.columns.filter(c => !document.foundations.some(f => f.columns?.includes(c.id) || f.type === 'raft' && !(f.columns?.length) && f.outline && insidePolygon([c.x, c.y], f.outline)));
}

/**
 * The ids of the columns and walls on the base level that no foundation carries: the columns of
 * {@link uncoveredColumns} and the walls no strip footing lists (nor a raft holds the middle of).
 */
export function uncoveredBases(document: ISubstructure, context: ISiteContext): string[] {
	const walls = context.walls.filter(w => {
		const middle: Point = [(w.start[0] + w.end[0]) / 2, (w.start[1] + w.end[1]) / 2];
		return !document.foundations.some(f => f.columns?.includes(w.id) || f.type === 'raft' && !(f.columns?.length) && f.outline && insidePolygon(middle, f.outline));
	});
	return [...uncoveredColumns(document, context).map(c => c.id), ...walls.map(w => w.id)];
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

export function pileFixityLabel(fixity: PileFixity | string): string {
	switch (fixity) {
		case 'fixed': return localize('sub.pile.fixed', "Fixed in the cap");
		case 'free': return localize('sub.pile.free', "Free (pinned)");
		default: return String(fixity);
	}
}

export function pileKindLabel(kind: PileKind | string): string {
	switch (kind) {
		case 'bored': return localize('sub.pile.bored', "Bored (cast in situ)");
		case 'driven': return localize('sub.pile.driven', "Driven (precast, square)");
		case 'drivenCastInPlace': return localize('sub.pile.drivenCastInPlace', "Driven (cast in place)");
		default: return String(kind);
	}
}

export function pilePlacementLabel(placement: PilePlacement | string): string {
	switch (placement) {
		case 'dry': return localize('sub.placement.dry', "Dry bore");
		case 'submerged': return localize('sub.placement.submerged', "Tremie (water or slurry)");
		default: return String(placement);
	}
}

export function pileTestKindLabel(kind: PileTestKind | string): string {
	switch (kind) {
		case 'compression': return localize('sub.test.compression', "Compression");
		case 'uplift': return localize('sub.test.uplift', "Uplift");
		case 'lateral': return localize('sub.test.lateral', "Lateral");
		default: return String(kind);
	}
}

export function pileTestStageLabel(stage: PileTestStage | string): string {
	switch (stage) {
		case 'initial': return localize('sub.test.initial', "Initial (test pile)");
		case 'routine': return localize('sub.test.routine', "Routine (working pile)");
		default: return String(stage);
	}
}

/** A load test's curve as text: "load movement; ..." (kN, mm). */
export function formatTestCurve(points: readonly (readonly [number, number])[]): string {
	return points.map(([load, movement]) => `${formatNumber(load, 1)} ${formatNumber(movement, 2)}`).join('; ');
}

/** A load test's curve from "load movement; ..." text, or undefined when it does not read. */
export function parseTestCurve(text: string): [number, number][] | undefined {
	const points: [number, number][] = [];
	for (const part of text.split(';').map(s => s.trim()).filter(Boolean)) {
		const values = part.split(/[\s,]+/).filter(Boolean).map(Number);
		if (values.length !== 2 || values.some(v => !Number.isFinite(v) || v < 0)) {
			return undefined;
		}
		points.push([values[0], values[1]]);
	}
	return points;
}

/** A new compression load test of the first pile type, its curve still to enter. */
export function newLoadTest(document: ISubstructure): IPileLoadTest {
	return { id: nextId('TP', (document.loadTests ?? []).map(t => t.id)), pileType: document.pileTypes[0]?.id ?? '', kind: 'compression', test: 'initial', points: [] };
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
	duplicates(document.piles, 'piles');
	duplicates(document.tieBeams, 'tieBeams');
	duplicates(document.groundSlabs, 'groundSlabs');
	document.groundSlabs.forEach((g, i) => {
		const at = (field: string) => `groundSlabs.${i}.${field}`;
		if (!(num(g.thickness) > 0)) {
			error(at('thickness'), localize('sub.g.thickness', "{0}: give the slab's thickness.", g.id));
		}
		if (!Array.isArray(g.outline) || g.outline.length < 3) {
			error(at('outline'), localize('sub.g.outline', "{0}: the outline needs at least 3 points.", g.id));
		}
		if (!g.material) {
			error(at('material'), localize('sub.g.material', "{0}: choose the slab's concrete.", g.id));
		}
		if (g.mesh && !g.meshMaterial) {
			error(at('meshMaterial'), localize('sub.g.meshMaterial', "{0}: the mesh needs a rebar material (03 Materials).", g.id));
		}
	});
	document.foundations.forEach((f, i) => {
		if (!f.section || f.section === 'flat') {
			return;
		}
		const at = (field: string) => `foundations.${i}.${field}`;
		if (f.type !== 'isolated') {
			error(at('section'), localize('sub.f.sectionType', "{0}: only an isolated footing is sloped or stepped.", f.id));
		}
		if (!(num(f.edgeThickness) > 0) || num(f.edgeThickness) >= num(f.thickness)) {
			error(at('edgeThickness'), localize('sub.f.edge', "{0}: the edge thickness must be less than the thickness.", f.id));
		}
		if (!(num(f.topLength) > 0) || num(f.topLength) > num(f.length)) {
			error(at('topLength'), localize('sub.f.topLength', "{0}: the top length must lie within the footing's length.", f.id));
		}
		if (!(num(f.topWidth) > 0) || num(f.topWidth) > num(f.width)) {
			error(at('topWidth'), localize('sub.f.topWidth', "{0}: the top width must lie within the footing's width.", f.id));
		}
	});

	// The rules of the backend's schema (library/substructure.py) are errors: a document that
	// breaks one is refused there as a whole, so no foundation of it would be checked.
	const columnIds = new Set(context.columns.map(c => c.id));
	const wallIds = new Set(context.walls.map(w => w.id));
	const carriedBy = new Map<string, string>();
	const cappedBy = new Map<string, string>();
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
			if (f.type === 'pileCap' && !f.center) {
				error(at('center'), localize('sub.p.capWhere', "{0}: give the pile cap's centre (it is placed over its piles).", f.id));
			} else if (!f.center && !(f.columns?.length)) {
				error(at('center'), localize('sub.p.where', "{0}: give its centre or the columns it carries.", f.id));
			}
		}
		if (f.thickness === undefined) {
			error(at('thickness'), localize('sub.p.thickness', "{0}: give the thickness.", f.id));
		}
		if (f.allowableBearing !== undefined && !(num(f.allowableBearing) > 0)) {
			error(at('allowableBearing'), localize('sub.p.qa', "{0}: the allowable bearing must be more than 0 kPa.", f.id));
		}
		if (f.slopeDistance !== undefined && !(num(f.slopeDistance) > 0)) {
			error(at('slopeDistance'), localize('sub.p.slope', "{0}: the distance to the slope face must be more than 0 mm.", f.id));
		}
		if (f.material && concrete.size && !concrete.has(f.material)) {
			warning(at('material'), localize('sub.p.material', "{0}: concrete {1} is not in 03 Materials.", f.id, f.material));
		}
		reinforcementProblems(f.id, at, f.reinforcement);
		if (f.type === 'pileCap') {
			if (hasOldPiles(f)) {
				error(at('piles'), localize('sub.p.oldPiles', "{0}: its piles are offsets of an earlier version and it has no centre; give its centre, or reopen the project for SAEngine to place them.", f.id));
			} else if (!(f.piles?.length)) {
				error(at('piles'), localize('sub.p.piles', "{0}: lay out the piles.", f.id));
			} else {
				const known = new Set(document.piles.map(p => p.id));
				const unknown = (f.piles ?? []).filter(p => !known.has(p));
				if (unknown.length) {
					error(at('piles'), localize('sub.p.unknownPiles', "{0}: pile {1} does not exist.", f.id, unknown.join(', ')));
				}
				for (const id of f.piles ?? []) {
					const other = cappedBy.get(id);
					if (other && other !== f.id) {
						error(at('piles'), localize('sub.p.pileTwice', "Pile {0} is under {1} and under {2}: a pile stands under one cap only.", id, other, f.id));
					} else {
						cappedBy.set(id, f.id);
					}
				}
				const types = [...new Set(capPiles(f, document).map(p => p.type))];
				if (types.length > 1) {
					error(at('piles'), localize('sub.p.pileTypes', "{0}: its piles are of more than one pile type ({1}).", f.id, types.join(', ')));
				}
			}
			const pile = capPileType(f, document);
			if (pile && pile.diameter > 0) {
				pileProblems(f, pile, capOffsets(f, document), at, error, warning);
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
			error(at('kind'), localize('sub.p.kind', "{0}: the pile is bored, driven precast or driven cast in place.", p.id));
		}
		for (const field of ['tipDiameter', 'reinforcedLength', 'casingDepth', 'unbracedLength', 'lateralDeflection'] as const) {
			if (p[field] !== undefined && !(num(p[field]) > 0)) {
				error(at(field), localize('sub.p.positive', "{0}: {1} is positive, or leave it empty.", p.id, field));
			}
		}
		if (p.headFixity !== undefined && !PILE_FIXITIES.includes(p.headFixity)) {
			error(at('headFixity'), localize('sub.p.fixity', "{0}: the pile head is fixed in the cap or free.", p.id));
		}
		if (p.fixityDepth !== undefined && !(num(p.fixityDepth) > 0)) {
			error(at('fixityDepth'), localize('sub.p.fixityDepth', "{0}: the depth to fixity is positive, or leave it empty.", p.id));
		}
		if (p.reinforcement && !p.reinforcement.material) {
			error(at('reinforcement.material'), localize('sub.p.pileBarMaterial', "{0}: the pile's bars need a rebar material (03 Materials).", p.id));
		} else if (!p.reinforcement?.longitudinal?.length) {
			warning(at('reinforcement'), localize('sub.p.pilePlain', "{0}: no bars: the pile is checked as plain concrete and cannot carry tension; the code pack's least bars of the pile's kind are checked.", p.id));
		}
		if (!p.material) {
			error(at('material'), localize('sub.p.pileMaterial', "{0}: choose the pile's concrete.", p.id));
		} else if (concrete.size && !concrete.has(p.material)) {
			warning(at('material'), localize('sub.p.material', "{0}: concrete {1} is not in 03 Materials.", p.id, p.material));
		}
	});
	pileLayoutProblems(document, pileTypes, error, warning);
	(document.loadTests ?? []).forEach((test, i) => {
		const at = (field: string) => `loadTests.${i}.${field}`;
		if (!document.pileTypes.some(p => p.id === test.pileType)) {
			error(at('pileType'), localize('sub.p.testType', "Load test {0}: pile type {1} does not exist.", test.id, test.pileType || '—'));
		}
		if ((test.points ?? []).length < 2) {
			warning(at('points'), localize('sub.p.testPoints', "Load test {0}: enter its curve, load (kN) and movement (mm) at each stage.", test.id));
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
	if (design.pileCapacity !== undefined && design.pileCapacity !== 'soilReport' && design.pileCapacity !== 'static' && design.pileCapacity !== 'spt') {
		error('design.pileCapacity', localize('sub.p.capacitySource', "The pile capacity comes from the soil report, the code pack's static method or its SPT relations."));
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
 * The piles placed in plan, as the backend's `pile_layout_warnings`: a pile of an unknown pile
 * type (an error: the backend refuses it), a pile under no cap, and two piles overlapping or
 * closer than 2.5 diameters and 750 mm (BNBC 2020 Part 6 Secs 3.10.1.19, 3.10.1.30) whatever cap
 * they are under. The pile grid's labels are distinct.
 */
function pileLayoutProblems(document: ISubstructure, pileTypes: ReadonlyMap<string, IPileType>, error: (path: string, message: string) => void, warning: (path: string, message: string) => void): void {
	const caps = pileCaps(document);
	document.piles.forEach((p, i) => {
		if (!pileTypes.has(p.type)) {
			error(`piles.${i}.type`, p.type
				? localize('sub.p.pileUnknownType', "{0}: pile type {1} does not exist.", p.id, p.type)
				: localize('sub.p.pileNoType', "{0}: choose its pile type.", p.id));
		}
		if (!caps.has(p.id)) {
			warning(`piles.${i}.position`, localize('sub.p.pileFree', "{0}: under no pile cap. Select it with the others of its group and Make Pile Cap, or delete it.", p.id));
		}
	});
	const diameter = (p: IPile) => num(pileTypes.get(p.type)?.diameter);
	for (let i = 0; i < document.piles.length; i++) {
		for (let j = i + 1; j < document.piles.length; j++) {
			const [a, b] = [document.piles[i], document.piles[j]];
			const distance = Math.hypot(a.position[0] - b.position[0], a.position[1] - b.position[1]);
			const d = Math.max(diameter(a), diameter(b));
			const need = Math.max(MIN_SPACING_FACTOR * d, MIN_PILE_SPACING);
			if (distance < d - 1e-6) {
				warning(`piles.${j}.position`, localize('sub.p.pilesOverlap', "{0} and {1} overlap: their centres are {2} mm apart, less than the diameter.", a.id, b.id, formatNumber(distance, 0)));
			} else if (distance < need - 0.5) {
				warning(`piles.${j}.position`, localize('sub.p.pilesClose', "{0} and {1} are {2} mm apart, less than {3} mm (2.5 diameters and 750 mm, BNBC 2020 Part 6 Secs 3.10.1.19 and 3.10.1.30).", a.id, b.id, formatNumber(distance, 0), formatNumber(need, 0)));
			}
		}
	}
	const labels = [...(document.pileGrid?.x ?? []), ...(document.pileGrid?.y ?? [])].map(l => l.label);
	const twice = [...new Set(labels.filter((l, k) => labels.indexOf(l) !== k))];
	if (twice.length) {
		error('pileGrid.x', localize('sub.p.gridTwice', "Pile grid: {0} used twice.", twice.join(', ')));
	}
	if (labels.some(l => !/^[A-Za-z0-9.'-]{1,8}$/.test(l))) {
		error('pileGrid.x', localize('sub.p.gridLabel', "Pile grid: a line label is 1 to 8 letters, digits, dots, dashes or primes."));
	}
}

/**
 * The piles of a cap (`piles`: offsets in its axes) against the cap and each other. Warnings
 * (the design skips a cap with a pile outside it): a pile not wholly within the cap, piles
 * overlapping; BNBC 2020 Part 6 Sec 3.10.1.30 (written for driven precast piles): end-bearing
 * driven piles more than the greater of 750 mm and 2.5 diameters apart; friction piles generally
 * at least 3.0 diameters; a pile's side at least 100 mm from the cap's edge. For bored piles the
 * same spacing is applied as a guide.
 */
function pileProblems(f: IFoundation, pile: IPileType, piles: readonly Point[], at: (field: string) => string, _error: (path: string, message: string) => void, warning: (path: string, message: string) => void): void {
	const d = pile.diameter;
	const length = num(f.length);
	const width = num(f.width);
	if (length > 0 && width > 0) {
		const outside = piles.find(([x, y]) => Math.abs(x) > length / 2 - d / 2 + 1e-6 || Math.abs(y) > width / 2 - d / 2 + 1e-6);
		if (outside) {
			warning(at('piles'), localize('sub.p.pileOutside', "{0}: the pile at {1}, {2} mm does not lie within the cap.", f.id, formatNumber(outside[0], 0), formatNumber(outside[1], 0)));
			return;
		}
	}
	const spacing = minPileSpacing(piles);
	if (spacing !== undefined && spacing < d - 1e-6) {
		warning(at('piles'), localize('sub.p.pileOverlap', "{0}: two piles overlap: their centres are {1} mm apart, less than the diameter.", f.id, formatNumber(spacing, 0)));
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
	/** Its mark (PL1, ...), when the backend gives it. */
	readonly mark?: string;
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
	/** Contact pressure [kPa] and settlement [mm] at each column the raft carries. */
	readonly columns?: readonly { readonly id: string; readonly x: number; readonly y: number; readonly pressure?: number; readonly settlement?: number }[];
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
	/** Checks that could not be made, e.g. `bearing` without qa: the foundation is not checked in full and does not count as passing. */
	readonly notChecked?: readonly string[];
}

export interface ISubstructureReport {
	readonly foundations: readonly IFoundationResult[];
	readonly tieBeams: readonly IFoundationResult[];
	readonly groundSlabs: readonly IFoundationResult[];
	/** Retaining and basement walls (type "retainingWall") and the basement's flotation (type "flotation"). */
	readonly retainingWalls?: readonly IFoundationResult[];
	/** Foundations and tie beams not designed, and why. */
	readonly skipped: readonly { readonly id: string; readonly type: string; readonly reason: string }[];
	readonly pileCapacities: readonly IPileCapacity[];
	readonly summary: {
		readonly checked: number;
		/** Foundations and tie beams in the file the backend checked: the checked ones and the skipped ones. */
		readonly total: number;
		readonly passed: number;
		readonly failed: number;
		readonly maxUtilisation: number | null;
		readonly governing: string | null;
		/** Columns and walls on the base level that no foundation carries. */
		readonly unsupported: readonly string[];
		/** The backend's verdict: pass only when all were checked, all pass and nothing is unsupported. */
		readonly status: SubstructureCheckStatus;
	};
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
		columns: records(raw.columns).filter(c => typeof c.x === 'number' && typeof c.y === 'number').map(c => ({
			id: String(c.id ?? ''), x: num(c.x), y: num(c.y), pressure: optionalNumber(c.pressure), settlement: optionalNumber(c.settlement),
		})),
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
		// The backend's pile has `base` as the tip layer's details (an object): each number is
		// taken from the first of the names that holds one.
		skin: optionalNumber(row.skin) ?? optionalNumber(row.Qs),
		base: optionalNumber(row.base) ?? optionalNumber(row.Qb),
		ultimate: optionalNumber(row.ultimate) ?? optionalNumber(row.Qult),
		compression: optionalNumber(row.compression) ?? optionalNumber(row.allowable) ?? optionalNumber(row.Qa),
		uplift: optionalNumber(row.uplift) ?? optionalNumber(row.Ta),
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
				mark: optionalString(p.mark),
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
		notChecked: Array.isArray(f.notChecked) && f.notChecked.length ? strings(f.notChecked) : undefined,
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
	const groundSlabs = records(raw.groundSlabs).map(readResult);
	const retainingWalls = records(raw.retainingWalls).map(readResult);
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
	const designed = [...foundations, ...tieBeams, ...groundSlabs, ...retainingWalls];
	const failed = designed.filter(f => !f.ok).length;
	const worst = designed.reduce<IFoundationResult | undefined>((w, f) => f.utilisation !== null && (w?.utilisation ?? -1) < f.utilisation ? f : w, undefined);
	return {
		foundations,
		tieBeams,
		groundSlabs,
		retainingWalls,
		skipped,
		pileCapacities,
		summary: readSummary(summary, designed.length, failed, skipped.length, worst),
		notes: strings(raw.notes),
		method: strings(raw.method),
		sources: isRecord(raw.sources) ? Object.fromEntries(Object.entries(raw.sources).filter((e): e is [string, string] => typeof e[1] === 'string')) : undefined,
	};
}

function readSummary(summary: Record<string, unknown>, designed: number, failedCount: number, skippedCount: number, worst: IFoundationResult | undefined): ISubstructureReport['summary'] {
	const checked = optionalNumber(summary.checked) ?? designed;
	const failed = optionalNumber(summary.failed) ?? failedCount;
	const total = optionalNumber(summary.total) ?? checked + (optionalNumber(summary.skipped) ?? skippedCount);
	const unsupported = strings(summary.unsupported);
	const given = summary.status;
	const status: SubstructureCheckStatus = given === 'pass' || given === 'fail' || given === 'incomplete' || given === 'none' ? given
		: failed ? 'fail' : !checked ? 'none' : checked < total || unsupported.length ? 'incomplete' : 'pass';
	return {
		checked,
		total,
		passed: optionalNumber(summary.passed) ?? checked - failed,
		failed,
		maxUtilisation: nullableNumber(summary.maxUtilisation) ?? worst?.utilisation ?? null,
		governing: typeof summary.governing === 'string' ? summary.governing : worst?.id ?? null,
		unsupported,
		status,
	};
}

/** What the sizing assistant proposes: foundations to put in place of those with the same id. */
export interface ISizingProposal {
	readonly foundations: readonly IFoundation[];
	readonly pileTypes: readonly IPileType[];
	/** The piles its pile caps stand on. */
	readonly piles?: readonly IPile[];
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
	return { foundations: parsed.document.foundations, pileTypes: parsed.document.pileTypes, piles: parsed.document.piles, notes: strings(isRecord(raw) ? raw.notes : undefined) };
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

/**
 * Adds a proposed or imported pile cap's piles (of `proposal`) to `document` with free marks and
 * the pile types' ids in the document; returns the foundation listing them by those marks.
 */
function withPiles(document: ISubstructure, foundation: IFoundation, proposal: ISizingProposal, ids: Map<string, string>): IFoundation {
	if (foundation.type !== 'pileCap' || !foundation.piles?.length) {
		return foundation;
	}
	const source = new Map((proposal.piles ?? []).map(p => [p.id, p]));
	const marks: string[] = [];
	for (const id of foundation.piles) {
		const pile = source.get(id);
		if (pile) {
			marks.push(addPiles(document, ids.get(pile.type) ?? pile.type, [pile.position])[0].id);
		}
	}
	return { ...foundation, piles: marks };
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
		const proposed = withPiles(document, raw, proposal, pileIds);
		const columns = new Set(proposed.columns ?? []);
		const replaced = document.foundations.filter(f => !placed.includes(f.id) && (f.columns ?? []).some(c => columns.has(c)));
		if (replaced.length) {
			const [kept, ...others] = replaced;
			// Footings replaced by a raft: the raft is named as one (R1); their tie beams go.
			const id = proposed.type === 'raft' && kept.type !== 'raft' ? foundationId(document, 'raft', []) : kept.id;
			const foundation: IFoundation = { ...proposed, id };
			if (foundation.material === undefined && kept.material !== undefined) {
				foundation.material = kept.material;
			}
			if (foundation.reinforcement === undefined && kept.reinforcement !== undefined) {
				foundation.reinforcement = kept.reinforcement;
			}
			const gone = new Set([...others.map(f => f.id), kept.id]);
			document.foundations[document.foundations.indexOf(kept)] = foundation;
			document.foundations = document.foundations.filter(f => f === foundation || !gone.has(f.id));
			for (const tie of document.tieBeams) {
				tie.from = gone.has(tie.from) ? id : tie.from;
				tie.to = gone.has(tie.to) ? id : tie.to;
			}
			document.tieBeams = document.tieBeams.filter(t => t.from !== t.to);
			placed.push(id);
		} else {
			// The backend's ids were picked against the saved file: named here, in the project's scheme.
			const id = foundationId(document, proposed.type, proposed.columns ?? []);
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
	const types = new Map((imported.piles ?? []).map(p => [p.id, p.type]));
	const usedPiles = new Set(fresh.filter(f => !(f.columns ?? []).some(c => carried.has(c))).flatMap(f => (f.piles ?? []).map(p => types.get(p))).filter(Boolean));
	const pileIds = addPileTypes(document, imported.pileTypes.filter(p => usedPiles.has(p.id)));
	for (const raw of fresh) {
		if ((raw.columns ?? []).some(c => carried.has(c))) {
			skipped.push(raw.id);
			continue;
		}
		const taken = document.foundations.map(f => f.id);
		const id = taken.includes(raw.id) ? nextId('F', taken) : raw.id;
		document.foundations.push({ ...withPiles(document, raw, imported, pileIds), id });
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
export function maxPressure(report: Pick<ISubstructureReport, 'foundations'>): { pressure: number; allowable?: number; id: string } | undefined {
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

/**
 * Pass only when every foundation and tie beam was checked, all pass and every column and wall
 * stands on a foundation; fail when a check fails; incomplete when some were not checked (or
 * changed since), or columns or walls have no foundation; none when nothing was checked.
 */
export type SubstructureCheckStatus = 'pass' | 'fail' | 'incomplete' | 'none';

/**
 * How far the checks cover the document: of the `total` foundations and tie beams, `checked`
 * have a result for exactly what is in the document now (`failed` of them fail), `stale` have a
 * result for what they were before an edit, and `notChecked` have none (skipped by the design,
 * with the reason in the report). `unsupported`: columns and walls without a foundation. The one
 * place that decides "all pass": the status line, the Results view and the part list's summary
 * file all read it.
 */
export interface ISubstructureCheckState {
	readonly total: number;
	readonly checked: number;
	/** Checked in full and passing. */
	readonly passed: number;
	readonly failed: number;
	readonly stale: number;
	readonly notChecked: number;
	/** Foundations checked but for their bearing (no qa): neither checked in full nor passing. */
	readonly bearingUnchecked: readonly string[];
	readonly unsupported: readonly string[];
	readonly status: SubstructureCheckStatus;
}

/** `value` as JSON with every object's keys sorted, so equal values give equal text. */
function canonical(value: unknown): string {
	return JSON.stringify(value, (_key, v) => isRecord(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v);
}

/**
 * What a foundation's checks depend on in the document: the foundation itself (not its note), its
 * pile type and the design options. A result checked for one signature does not describe a
 * foundation with another.
 */
export function foundationSignature(document: ISubstructure, foundation: IFoundation): string {
	const { note: _note, ...rest } = foundation;
	const piles = capPiles(foundation, document);
	const pile = capPileType(foundation, document);
	return canonical({ foundation: rest, piles: piles.length ? piles : undefined, pile, design: document.design });
}

/** What a tie beam's checks depend on: itself and the foundations at its ends. */
export function tieBeamSignature(document: ISubstructure, tie: ITieBeam): string {
	const end = (id: string) => {
		const f = document.foundations.find(x => x.id === id);
		return f ? foundationSignature(document, f) : '';
	};
	return canonical({ tie, from: end(tie.from), to: end(tie.to) });
}

/** The signatures of every foundation and tie beam of `document`, by `f:<id>` and `t:<id>`. */
export function documentSignatures(document: ISubstructure): Map<string, string> {
	const signatures = new Map<string, string>();
	for (const f of document.foundations) {
		signatures.set(`f:${f.id}`, foundationSignature(document, f));
	}
	for (const t of document.tieBeams) {
		signatures.set(`t:${t.id}`, tieBeamSignature(document, t));
	}
	return signatures;
}

/**
 * The coverage of `report` over `document`. `checkedFor` holds the signatures (see
 * {@link documentSignatures}) of the document the report was computed for: a result whose
 * foundation or tie beam has another signature now is stale. Without it every result counts.
 * `unsupported` replaces the report's columns and walls without a foundation (the editor knows
 * them for the document as edited).
 */
export function substructureCheckState(document: ISubstructure, report: ISubstructureReport | undefined, checkedFor?: ReadonlyMap<string, string>, unsupported?: readonly string[]): ISubstructureCheckState {
	const now = documentSignatures(document);
	let checked = 0;
	let failed = 0;
	let stale = 0;
	let passed = 0;
	const bearingUnchecked: string[] = [];
	const count = (key: string, result: IFoundationResult | undefined) => {
		if (!result) {
			return;
		}
		if (checkedFor && checkedFor.get(key) !== now.get(key)) {
			stale++;
			return;
		}
		if (!result.ok) {
			failed++;
		}
		// Without its bearing check a footing is not checked for what sizes it (N-U3).
		if (result.notChecked?.includes('bearing')) {
			bearingUnchecked.push(result.id);
		} else {
			checked++;
			if (result.ok) {
				passed++;
			}
		}
	};
	for (const f of document.foundations) {
		count(`f:${f.id}`, report?.foundations.find(r => r.id === f.id));
	}
	for (const t of document.tieBeams) {
		count(`t:${t.id}`, report?.tieBeams.find(r => r.id === t.id));
	}
	const total = document.foundations.length + document.tieBeams.length;
	const missing = unsupported ?? report?.summary.unsupported ?? [];
	const status: SubstructureCheckStatus = failed ? 'fail' : !checked && !bearingUnchecked.length ? 'none' : checked < total || missing.length ? 'incomplete' : 'pass';
	return { total, checked, passed, failed, stale, notChecked: total - checked - stale - bearingUnchecked.length, bearingUnchecked, unsupported: missing, status };
}

/**
 * A backend error as one line for the engineer and the rest for Details (N-U1): a Python
 * traceback's message without its module path ("CodePackError: code pack ... cannot be used"),
 * the frames in `details`. `restart` when restarting the engine is the likely fix (the code
 * packs or the backend's files changed under it).
 */
export function errorSummary(message: string): { readonly summary: string; readonly details: string | undefined; readonly restart: boolean } {
	const text = message.trim();
	const cut = text.search(/\s*(Traceback \(most recent call last\)|File "|\n)/);
	// A plain Python traceback ends with its message: the last line then.
	const head = cut > 0 ? text.slice(0, cut) : cut === 0 ? text.split('\n').map(l => l.trim()).filter(Boolean).pop() ?? text : text;
	const summary = head.trim().replace(/^(?:[A-Za-z_][\w]*\.)+(?=[A-Za-z_]\w*(?:Error|Exception)\b)/, '');
	const restart = /CodePackError|ModuleNotFoundError|ImportError|BrokenPipe|backend (?:exited|stopped)/i.test(text);
	return { summary: summary || text, details: summary === text ? undefined : text, restart };
}

/** "6 of 7 checked · 1 fail · 1 not checked" for the status line and the Results view. */
export function checkStateText(state: ISubstructureCheckState): string {
	const parts = [localize('sub.checkedOf', "{0} of {1} checked", state.checked, state.total)];
	if (state.failed) {
		parts.push(localize('sub.fail', "{0} fail", state.failed));
	} else if (state.status === 'pass') {
		parts.push(localize('sub.allPass', "all pass"));
	}
	if (state.stale) {
		parts.push(state.stale === 1 ? localize('sub.staleOne', "1 changed since checked") : localize('sub.stale', "{0} changed since checked", state.stale));
	}
	if (state.bearingUnchecked.length) {
		parts.push(localize('sub.bearingUnchecked', "{0} without a bearing check (no qa)", state.bearingUnchecked.length));
	}
	if (state.notChecked) {
		parts.push(localize('sub.notCheckedCount', "{0} not checked", state.notChecked));
	}
	return parts.join(' · ');
}

/** "6 foundations · 7 of 7 checked · 1 fail · max pressure 142 kPa (qa 150)" for the status line. */
export function substructureSummary(document: ISubstructure, report: ISubstructureReport | undefined, state?: ISubstructureCheckState): string {
	const count = document.foundations.length;
	const parts = [count === 1 ? localize('sub.oneFoundation', "1 foundation") : localize('sub.foundations', "{0} foundations", count)];
	if (report) {
		parts.push(checkStateText(state ?? substructureCheckState(document, report)));
		const pressure = maxPressure(report);
		if (pressure) {
			parts.push(typeof pressure.allowable === 'number'
				? localize('sub.maxPressureQa', "max pressure {0} kPa (qa {1})", formatNumber(pressure.pressure, 0), formatNumber(pressure.allowable, 0))
				: localize('sub.maxPressure', "max pressure {0} kPa", formatNumber(pressure.pressure, 0)));
		}
	}
	return parts.join(' · ');
}

/**
 * Content of {@link SUBSTRUCTURE_SUMMARY_FILE}, read by the project's part list. The part's
 * status comes from `status` (with `checked` of `total`): "pass" only when every foundation and
 * tie beam was checked, all pass and every column and wall stands on a foundation.
 */
export interface ISubstructureSummaryFile {
	readonly foundations: number;
	readonly checked: number;
	/** Foundations and tie beams in the file: `checked` of `total` were checked. */
	readonly total: number;
	readonly passed: number;
	readonly failed: number;
	/** Foundations whose bearing was not checked (no qa): not counted in `checked` or `passed`. */
	readonly bearingUnchecked: readonly string[];
	/** Columns and walls without a foundation. */
	readonly unsupported: readonly string[];
	readonly status: SubstructureCheckStatus;
	readonly maxUtilisation: number | null;
	readonly governing: string | null;
	/** ISO time the checks were computed. */
	readonly computed: string;
	/** The stamps of the part files the checks read, by part id (see {@link ISubstructureReport.sources}). */
	readonly source?: { readonly [part: string]: string };
}

/** The summary file of `report`, the checks of the saved `document`. */
export function substructureSummaryFile(document: ISubstructure, report: ISubstructureReport, computed: Date): ISubstructureSummaryFile {
	const { maxUtilisation, governing } = report.summary;
	const state = substructureCheckState(document, report);
	return {
		foundations: document.foundations.length, checked: state.checked, total: state.total, passed: state.passed, failed: state.failed,
		bearingUnchecked: state.bearingUnchecked, unsupported: state.unsupported, status: state.status,
		maxUtilisation, governing, computed: computed.toISOString(), source: report.sources,
	};
}
