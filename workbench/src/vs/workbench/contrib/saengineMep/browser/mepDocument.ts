/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { sourceStamp } from '../../../services/saengineProject/common/partSources.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';

/*
 * The MEP part (`07 MEP/mep.json`): the equipment that loads the structure, the sleeves and
 * openings the services need through beams, slabs and walls, the vertical shafts, and the MEP
 * IFC models coordinated against the structure. Lengths are in mm on the project's axes, weights
 * in kN. This module reads and writes the file, reads the building it is drawn against
 * (`06 BIM/bim.json` with the object types and materials), checks it, and reads the backend's
 * report (`saengine.mep.report`). It holds no UI.
 */

export const MEP_SCHEMA_ID = 'saengine.mep/1';

/** The backend's equipment loads, opening checks and clash list: `{ projectRoot, mepText }`. */
export const MEP_REPORT_COMMAND = 'saengine.mep.report';
/** The sleeves the clashes of the MEP IFC models with the structure need: `{ projectRoot, mepText }`. */
export const MEP_SUGGEST_SLEEVES_COMMAND = 'saengine.mep.suggestSleeves';
/** Reads an MEP IFC model of the project: `{ projectRoot, path }` (project-relative). */
export const MEP_IMPORT_IFC_COMMAND = 'saengine.mep.importIfc';
/** The report's summary the editor writes beside the file, for the project's part list. */
export const MEP_SUMMARY_FILE = 'mep.results/summary.json';
/** Where an MEP IFC model picked outside the project is copied to, inside `07 MEP`. */
export const MEP_IFC_FOLDER = 'IFC';

export type Point = [number, number];

export type EquipmentKind = 'tank' | 'chiller' | 'ahu' | 'pump' | 'generator' | 'transformer' | 'lift' | 'other';
export const EQUIPMENT_KINDS: readonly EquipmentKind[] = ['tank', 'chiller', 'ahu', 'pump', 'generator', 'transformer', 'lift', 'other'];

export type OpeningKind = 'sleeve' | 'opening';
export const OPENING_KINDS: readonly OpeningKind[] = ['sleeve', 'opening'];
export type OpeningShape = 'circle' | 'rectangle';
export const OPENING_SHAPES: readonly OpeningShape[] = ['circle', 'rectangle'];

export type Discipline = 'mechanical' | 'plumbing' | 'fire' | 'electrical';
export const DISCIPLINES: readonly Discipline[] = ['mechanical', 'plumbing', 'fire', 'electrical'];

export type LoadAs = 'area' | 'points';

export interface IPlinth {
	/** Height of the concrete plinth under the equipment [mm]. */
	height?: number;
	/** Concrete material id (03 Materials). */
	material?: string;
	[key: string]: unknown;
}

export interface IEquipment {
	id: string;
	name?: string;
	kind: EquipmentKind | string;
	/** The story (06 BIM) whose floor it stands on. */
	story: string;
	/** Plan position of the centre [mm]. */
	x: number;
	y: number;
	/** Footprint along the local x and y axes [mm]. */
	length: number;
	width: number;
	height?: number;
	/** Weight in operation, with its contents (water, oil, refrigerant) [kN]. */
	operatingWeight: number;
	emptyWeight?: number;
	vibrating?: boolean;
	/** Rotation of the local x axis from the project's x axis [°]. */
	rotation?: number;
	/** Spread over its footprint (default) or on its four feet. */
	loadAs?: LoadAs;
	plinth?: IPlinth;
	[key: string]: unknown;
}

export interface IOpeningPosition {
	/** Beam: from the beam's start end to the centre [mm]. */
	distance?: number;
	/** Beam: from the beam's bottom to the centre [mm]. */
	elevation?: number;
	/** Slab: plan position of the centre; wall: along the wall from its start [mm]. */
	x?: number;
	/** Slab: plan position of the centre; wall: up from the wall's bottom [mm]. */
	y?: number;
	[key: string]: unknown;
}

export interface IOpening {
	id: string;
	/** The beam, slab or wall it goes through (06 BIM element id). */
	host: string;
	kind: OpeningKind | string;
	shape: OpeningShape | string;
	diameter?: number;
	/** Rectangle: across the host's axis (beam, wall: along it; slab: plan x) [mm]. */
	width?: number;
	/** Rectangle: beam, wall: vertical; slab: plan y [mm]. */
	height?: number;
	position: IOpeningPosition;
	/** What passes through ("DN150 drain"). */
	service?: string;
	[key: string]: unknown;
}

export interface IShaft {
	id: string;
	outline: Point[];
	fromStory: string;
	toStory: string;
	service?: string;
	[key: string]: unknown;
}

export interface IIfcModel {
	/** Project-relative path of the model, with forward slashes. */
	path: string;
	discipline: Discipline | string;
	visible: boolean;
	[key: string]: unknown;
}

export interface IMep {
	schema: string;
	equipment: IEquipment[];
	openings: IOpening[];
	shafts: IShaft[];
	ifcModels: IIfcModel[];
	[key: string]: unknown;
}

export function newMep(): IMep {
	return { schema: MEP_SCHEMA_ID, equipment: [], openings: [], shafts: [], ifcModels: [] };
}

// ───────────────────────────── reading and writing ─────────────────────────────

export type ParsedMep =
	| { readonly kind: 'document'; readonly document: IMep }
	/** The stub a new project starts with: shown as an empty document, written on the first edit. */
	| { readonly kind: 'placeholder'; readonly document: IMep }
	| { readonly kind: 'error'; readonly message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoint(value: unknown): value is Point {
	return Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number';
}

function num(value: unknown, fallback = 0): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** Reads the file's text; lists it lacks are filled in, unknown fields are kept. */
export function parseMep(text: string): ParsedMep {
	if (!text.trim()) {
		return { kind: 'placeholder', document: newMep() };
	}
	let value: unknown;
	try {
		value = JSON.parse(text);
	} catch (error) {
		return { kind: 'error', message: localize('mep.invalidJson', "This file contains invalid JSON ({0}). Fix it in the text editor; the MEP editor will not change it until then.", String(error)) };
	}
	if (!isRecord(value)) {
		return { kind: 'error', message: localize('mep.notObject', "This file does not contain a JSON object.") };
	}
	if (value.part === 'mep' && Object.keys(value).every(key => key === 'schema' || key === 'part')) {
		return { kind: 'placeholder', document: newMep() };
	}
	if (value.schema !== MEP_SCHEMA_ID) {
		return { kind: 'error', message: localize('mep.unexpected', "This file is not a SAEngine MEP file ({0}).", MEP_SCHEMA_ID) };
	}
	for (const list of ['equipment', 'openings', 'shafts', 'ifcModels']) {
		if (value[list] !== undefined && !Array.isArray(value[list])) {
			return { kind: 'error', message: localize('mep.badList', "The MEP file's {0} are not a list.", list) };
		}
	}
	const document = value as IMep;
	document.equipment = (document.equipment ?? []).filter(isRecord) as IEquipment[];
	document.openings = (document.openings ?? []).filter(isRecord) as IOpening[];
	document.shafts = (document.shafts ?? []).filter(isRecord) as IShaft[];
	document.ifcModels = (document.ifcModels ?? []).filter(isRecord) as IIfcModel[];
	for (const opening of document.openings) {
		if (!isRecord(opening.position)) {
			opening.position = {};
		}
	}
	for (const shaft of document.shafts) {
		shaft.outline = Array.isArray(shaft.outline) ? shaft.outline.filter(isPoint) : [];
	}
	return { kind: 'document', document };
}

export function serializeMep(document: IMep): string {
	return JSON.stringify(document, undefined, '\t') + '\n';
}

// ───────────────────────────── the building it is drawn against ─────────────────────────────

export interface IStory {
	readonly id: string;
	readonly name: string;
	readonly elevation: number;
}

export interface IGridLine {
	readonly label: string;
	readonly position: number;
}

export interface IColumn {
	readonly id: string;
	readonly x: number;
	readonly y: number;
	readonly rotation: number;
	readonly xDim: number;
	readonly yDim: number;
	readonly circle: boolean;
	readonly bottom: number;
	readonly top: number;
}

export interface IBeam {
	readonly id: string;
	readonly start: Point;
	readonly end: Point;
	/** Top of the beam (the story's level) [mm]. */
	readonly elevation: number;
	readonly width: number;
	readonly depth: number;
	readonly type: string;
}

export interface IWall {
	readonly id: string;
	readonly start: Point;
	readonly end: Point;
	readonly bottom: number;
	readonly top: number;
	readonly thickness: number;
	readonly type: string;
}

export interface ISlab {
	readonly id: string;
	readonly boundary: Point[];
	readonly elevation: number;
	readonly thickness: number;
	readonly type: string;
}

/** An opening of the building model itself (06 BIM additions), drawn for reference. */
export interface IBimSlabOpening {
	readonly id: string;
	readonly host: string;
	readonly x: number;
	readonly y: number;
	readonly xDim: number;
	readonly yDim: number;
	readonly rotation: number;
}

/** What the MEP part is drawn and checked against, read from the other parts. */
export interface IMepContext {
	/** By elevation, lowest first. */
	readonly stories: readonly IStory[];
	readonly grids: { readonly x: readonly IGridLine[]; readonly y: readonly IGridLine[] };
	readonly columns: readonly IColumn[];
	readonly beams: readonly IBeam[];
	readonly walls: readonly IWall[];
	readonly slabs: readonly ISlab[];
	readonly slabOpenings: readonly IBimSlabOpening[];
	/** Concrete materials, for the plinths: id and unit weight [kN/m³]. */
	readonly concretes: readonly { readonly id: string; readonly unitWeight: number }[];
}

export const EMPTY_CONTEXT: IMepContext = { stories: [], grids: { x: [], y: [] }, columns: [], beams: [], walls: [], slabs: [], slabOpenings: [], concretes: [] };

/** The texts of the parts the MEP part is drawn against (any may be missing). */
export interface IMepContextTexts {
	readonly bim?: string;
	readonly objects?: string;
	readonly floorPlan?: string;
	readonly materials?: string;
	/** The project settings: not drawn, but the report reads them (stamped in the summary). */
	readonly settings?: string;
}

/**
 * The parts the backend's MEP report reads besides the MEP file itself, by part id (the keys of
 * {@link IMepContextTexts} are the part ids): their stamps go into the part list's summary.
 */
export const MEP_SOURCE_PARTS = ['settings', 'materials', 'objects', 'bim'] as const;

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

/** Standard gravity, for a material's density in kg/m³ to a unit weight in kN/m³. */
const GRAVITY = 9.80665;

export function readMepContext(texts: IMepContextTexts): IMepContext {
	const bim = parseJson(texts.bim);
	const floorPlan = parseJson(texts.floorPlan);
	const objects = records(parseJson(texts.objects)?.objects);
	const byId = new Map(objects.map(o => [String(o.id), o]));
	const profile = (type: unknown) => {
		const value = byId.get(String(type))?.profile;
		return isRecord(value) ? value : {};
	};
	const storySource = records(bim?.stories).length ? records(bim?.stories) : records(floorPlan?.stories);
	const stories = storySource.filter(s => typeof s.id === 'string').map(s => ({ id: String(s.id), name: String(s.name ?? s.id), elevation: num(s.elevation) }))
		.sort((a, b) => a.elevation - b.elevation);
	const elements = records(bim?.elements);
	const columns: IColumn[] = elements.filter(e => e.kind === 'column' && isPoint(e.position)).map(c => {
		const shape = profile(c.type);
		const circle = shape.shape === 'circle';
		const xDim = circle ? 2 * num(shape.radius, 200) : num(shape.xDim, 400);
		const position = c.position as Point;
		return { id: String(c.id), x: position[0], y: position[1], rotation: num(c.rotation), xDim, yDim: circle ? xDim : num(shape.yDim, 400), circle, bottom: num(c.bottom), top: num(c.top) };
	});
	const beams: IBeam[] = elements.filter(e => e.kind === 'beam' && isPoint(e.start) && isPoint(e.end)).map(b => {
		const shape = profile(b.type);
		return { id: String(b.id), start: b.start as Point, end: b.end as Point, elevation: num(b.elevation), width: num(shape.xDim, 300), depth: num(shape.yDim, 500), type: String(b.type ?? '') };
	});
	const walls: IWall[] = elements.filter(e => e.kind === 'wall' && isPoint(e.start) && isPoint(e.end)).map(w => ({
		id: String(w.id), start: w.start as Point, end: w.end as Point, bottom: num(w.bottom), top: num(w.top), thickness: num(byId.get(String(w.type))?.thickness, 200), type: String(w.type ?? ''),
	}));
	const slabs: ISlab[] = elements.filter(e => e.kind === 'slab' && Array.isArray(e.boundary)).map(s => ({
		id: String(s.id), boundary: (s.boundary as unknown[]).filter(isPoint), elevation: num(s.elevation), thickness: num(byId.get(String(s.type))?.thickness, 150), type: String(s.type ?? ''),
	}));
	const additions = isRecord(bim?.additions) ? bim.additions : {};
	const slabOpenings: IBimSlabOpening[] = records(additions.slabOpenings).map(o => ({
		id: String(o.id), host: String(o.host), x: num(o.x), y: num(o.y), xDim: num(o.xDim), yDim: num(o.yDim), rotation: num(o.rotation),
	}));
	const grids = isRecord(floorPlan?.grids) ? floorPlan.grids : {};
	const gridLines = (value: unknown) => records(value).filter(g => typeof g.position === 'number').map(g => ({ label: String(g.label ?? ''), position: num(g.position) }));
	const concretes = records(parseJson(texts.materials)?.materials)
		.filter(m => m.category === 'concrete' || m.kind === 'concrete' || m.type === 'concrete')
		.map(m => {
			const mechanical = isRecord(m.mechanical) ? m.mechanical : {};
			return { id: String(m.id), unitWeight: num(mechanical.density, 2400) * GRAVITY / 1000 };
		});
	return { stories, grids: { x: gridLines(grids.x), y: gridLines(grids.y) }, columns, beams, walls, slabs, slabOpenings, concretes };
}

const TOLERANCE = 1;

/** What stands on, or hangs at, a story's level: its floor (slabs, beams) and the columns and walls through it. */
export interface IStoryElements {
	readonly columns: readonly IColumn[];
	readonly beams: readonly IBeam[];
	readonly walls: readonly IWall[];
	readonly slabs: readonly ISlab[];
	readonly slabOpenings: readonly IBimSlabOpening[];
}

export function storyElements(context: IMepContext, storyId: string): IStoryElements {
	const story = context.stories.find(s => s.id === storyId);
	if (!story) {
		return { columns: [], beams: [], walls: [], slabs: [], slabOpenings: [] };
	}
	const at = (value: number) => Math.abs(value - story.elevation) <= TOLERANCE;
	const through = (bottom: number, top: number) => bottom <= story.elevation + TOLERANCE && top >= story.elevation - TOLERANCE;
	const slabs = context.slabs.filter(s => at(s.elevation));
	const slabIds = new Set(slabs.map(s => s.id));
	return {
		columns: context.columns.filter(c => through(c.bottom, c.top)),
		beams: context.beams.filter(b => at(b.elevation)),
		walls: context.walls.filter(w => through(w.bottom, w.top)),
		slabs,
		slabOpenings: context.slabOpenings.filter(o => slabIds.has(o.host)),
	};
}

export type HostKind = 'beam' | 'slab' | 'wall';

export type Host =
	| { readonly kind: 'beam'; readonly element: IBeam }
	| { readonly kind: 'slab'; readonly element: ISlab }
	| { readonly kind: 'wall'; readonly element: IWall };

/** The beam, slab or wall with id `id`, if the building model has one. */
export function findHost(context: IMepContext, id: string): Host | undefined {
	const beam = context.beams.find(b => b.id === id);
	if (beam) {
		return { kind: 'beam', element: beam };
	}
	const slab = context.slabs.find(s => s.id === id);
	if (slab) {
		return { kind: 'slab', element: slab };
	}
	const wall = context.walls.find(w => w.id === id);
	return wall ? { kind: 'wall', element: wall } : undefined;
}

/** The story at `elevation` (within a millimetre), if any. */
export function storyAt(context: IMepContext, elevation: number): IStory | undefined {
	return context.stories.find(s => Math.abs(s.elevation - elevation) <= TOLERANCE);
}

/** The story an opening's host is on: a beam's or slab's level, the level a wall stands on. */
export function hostStory(context: IMepContext, host: Host | undefined): IStory | undefined {
	if (!host) {
		return undefined;
	}
	return storyAt(context, host.kind === 'wall' ? host.element.bottom : host.element.elevation);
}

function length(a: Point, b: Point): number {
	return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/** A point at `distance` along the line from `a` to `b`. */
function along(a: Point, b: Point, distance: number): Point {
	const span = length(a, b) || 1;
	return [a[0] + (b[0] - a[0]) * distance / span, a[1] + (b[1] - a[1]) * distance / span];
}

/** The plan position of an opening's centre [mm]; undefined when its host is missing. */
export function openingPoint(opening: IOpening, context: IMepContext): Point | undefined {
	const host = findHost(context, opening.host);
	const position = opening.position ?? {};
	switch (host?.kind) {
		case 'beam': return along(host.element.start, host.element.end, num(position.distance));
		case 'wall': return along(host.element.start, host.element.end, num(position.x));
		case 'slab': return [num(position.x), num(position.y)];
		default: return undefined;
	}
}

/** An opening's size in the plan along its host (beam, wall) or along x (slab) [mm]. */
export function openingPlanSize(opening: IOpening): number {
	return opening.shape === 'circle' ? num(opening.diameter) : num(opening.width);
}

/** The unit vector along a beam's or wall's axis. */
export function hostDirection(host: Host): Point {
	if (host.kind === 'slab') {
		return [1, 0];
	}
	const span = length(host.element.start, host.element.end) || 1;
	return [(host.element.end[0] - host.element.start[0]) / span, (host.element.end[1] - host.element.start[1]) / span];
}

/** Rotates the local offset (dx, dy) by `degrees` and moves it to `center`. */
export function toGlobal(center: readonly [number, number], dx: number, dy: number, degrees = 0): Point {
	const a = degrees * Math.PI / 180;
	const c = Math.cos(a);
	const s = Math.sin(a);
	return [center[0] + dx * c - dy * s, center[1] + dx * s + dy * c];
}

/** The four corners of an equipment's footprint, counter-clockwise. */
export function equipmentOutline(equipment: IEquipment): Point[] {
	const center: Point = [num(equipment.x), num(equipment.y)];
	const hx = num(equipment.length) / 2;
	const hy = num(equipment.width) / 2;
	const rotation = num(equipment.rotation);
	return [toGlobal(center, -hx, -hy, rotation), toGlobal(center, hx, -hy, rotation), toGlobal(center, hx, hy, rotation), toGlobal(center, -hx, hy, rotation)];
}

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

function distanceToSegment(p: readonly [number, number], a: readonly [number, number], b: readonly [number, number]): number {
	const dx = b[0] - a[0];
	const dy = b[1] - a[1];
	const span = dx * dx + dy * dy;
	const t = span > 0 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span)) : 0;
	return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

/** Inside `polygon` or within `tolerance` [mm] of its edges (the backend's slab test grows the slab by 1 mm). */
export function insideOrOn(point: readonly [number, number], polygon: readonly (readonly [number, number])[], tolerance = TOLERANCE): boolean {
	if (insidePolygon(point, polygon)) {
		return true;
	}
	for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
		if (distanceToSegment(point, polygon[j], polygon[i]) <= tolerance) {
			return true;
		}
	}
	return false;
}

/** Whether two convex polygons share an area (separating axes; touching edges do not count). */
export function convexOverlap(a: readonly Point[], b: readonly Point[]): boolean {
	if (a.length < 3 || b.length < 3) {
		return false;
	}
	for (const polygon of [a, b]) {
		for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
			const axis: Point = [polygon[j][1] - polygon[i][1], polygon[i][0] - polygon[j][0]];
			const project = (points: readonly Point[]) => points.map(p => p[0] * axis[0] + p[1] * axis[1]);
			const pa = project(a);
			const pb = project(b);
			const scale = Math.hypot(axis[0], axis[1]) * 0.5;
			if (Math.max(...pa) <= Math.min(...pb) + scale || Math.max(...pb) <= Math.min(...pa) + scale) {
				return false;
			}
		}
	}
	return true;
}

/** The outline of an opening of the building model's own slab (rotated about its centre). */
export function bimOpeningOutline(opening: IBimSlabOpening): Point[] {
	const center: Point = [opening.x, opening.y];
	const hx = opening.xDim / 2;
	const hy = opening.yDim / 2;
	return [toGlobal(center, -hx, -hy, opening.rotation), toGlobal(center, hx, -hy, opening.rotation), toGlobal(center, hx, hy, opening.rotation), toGlobal(center, -hx, hy, opening.rotation)];
}

/** Whether `point` is strictly inside an opening of the building model's slab (as the backend tests it). */
function inBimOpening(point: Point, opening: IBimSlabOpening): boolean {
	const a = -opening.rotation * Math.PI / 180;
	const dx = point[0] - opening.x;
	const dy = point[1] - opening.y;
	const u = dx * Math.cos(a) - dy * Math.sin(a);
	const v = dx * Math.sin(a) + dy * Math.cos(a);
	return Math.abs(u) < opening.xDim / 2 && Math.abs(v) < opening.yDim / 2;
}

/**
 * The points an equipment's load is applied at, as the backend places them: on its four feet
 * (the footprint corners) for `loadAs: 'points'`, else the centres of a grid of cells at most
 * 100 mm apart over the footprint (2 to 40 a side), each with an equal share.
 */
export function equipmentLoadPoints(equipment: IEquipment): Point[] {
	const center: Point = [num(equipment.x), num(equipment.y)];
	const length = Math.max(0, num(equipment.length));
	const width = Math.max(0, num(equipment.width));
	const rotation = num(equipment.rotation);
	if (equipment.loadAs === 'points') {
		return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => toGlobal(center, sx * length / 2, sy * width / 2, rotation));
	}
	const nu = Math.min(40, Math.max(2, Math.ceil(length / 100)));
	const nv = Math.min(40, Math.max(2, Math.ceil(width / 100)));
	const points: Point[] = [];
	for (let i = 0; i < nu; i++) {
		for (let j = 0; j < nv; j++) {
			points.push(toGlobal(center, -length / 2 + (i + 0.5) * length / nu, -width / 2 + (j + 0.5) * width / nv, rotation));
		}
	}
	return points;
}

/** Where an equipment's load points land on the floor of its story. */
export interface IEquipmentSupport {
	readonly points: number;
	/** Load points on a slab of the story (outside its openings): they carry the whole load. */
	readonly onSlab: number;
	/** The slabs that receive the load. */
	readonly slabs: readonly string[];
	/** The building model's slab openings load points fall into, with how many. */
	readonly overOpenings: readonly { readonly opening: string; readonly slab: string; readonly points: number }[];
}

/** How an equipment's load reaches the slabs of its story, as the backend applies it. */
export function equipmentSupport(equipment: IEquipment, context: IMepContext): IEquipmentSupport {
	const elements = storyElements(context, equipment.story);
	const points = equipmentLoadPoints(equipment);
	const slabs = new Set<string>();
	const over = new Map<string, { opening: string; slab: string; points: number }>();
	let onSlab = 0;
	for (const point of points) {
		let placed = false;
		let hit: { opening: IBimSlabOpening; slab: string } | undefined;
		for (const slab of elements.slabs) {
			if (!insideOrOn(point, slab.boundary)) {
				continue;
			}
			const hole = elements.slabOpenings.find(o => o.host === slab.id && inBimOpening(point, o));
			if (hole) {
				hit ??= { opening: hole, slab: slab.id };
				continue;
			}
			placed = true;
			slabs.add(slab.id);
			break;
		}
		if (placed) {
			onSlab++;
		} else if (hit) {
			const entry = over.get(hit.opening.id) ?? { opening: hit.opening.id, slab: hit.slab, points: 0 };
			entry.points++;
			over.set(hit.opening.id, entry);
		}
	}
	return { points: points.length, onSlab, slabs: [...slabs].sort(), overOpenings: [...over.values()] };
}

export function polygonArea(points: readonly (readonly [number, number])[]): number {
	let area = 0;
	for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
		area += (points[j][0] + points[i][0]) * (points[j][1] - points[i][1]);
	}
	return Math.abs(area) / 2;
}

export function centroid(points: readonly (readonly [number, number])[]): Point | undefined {
	if (!points.length) {
		return undefined;
	}
	return [points.reduce((s, p) => s + p[0], 0) / points.length, points.reduce((s, p) => s + p[1], 0) / points.length];
}

/**
 * Whether a shaft cuts the floor of a story: the stories above the one it starts at
 * (`fromStory`, not cut) up to its top story (`toStory`, cut), as the backend's clash check takes it.
 */
export function shaftOnStory(shaft: IShaft, context: IMepContext, storyId: string): boolean {
	const elevation = (id: string) => context.stories.find(s => s.id === id)?.elevation;
	const at = elevation(storyId);
	const from = elevation(shaft.fromStory);
	const to = elevation(shaft.toStory);
	if (at === undefined) {
		return false;
	}
	if (from === undefined || to === undefined) {
		return shaft.fromStory !== storyId && shaft.toStory === storyId;
	}
	return at > from + TOLERANCE && at <= to + TOLERANCE;
}

// ───────────────────────────── loads ─────────────────────────────

/** Footprint area of an equipment [m²]. */
export function equipmentArea(equipment: IEquipment): number {
	return Math.max(0, num(equipment.length)) * Math.max(0, num(equipment.width)) / 1e6;
}

/** The operating weight spread over the footprint [kPa]; undefined without a footprint. */
export function equipmentPressure(equipment: IEquipment): number | undefined {
	const area = equipmentArea(equipment);
	return area > 0 ? num(equipment.operatingWeight) / area : undefined;
}

/** The weight of an equipment's concrete plinth [kN]; 0 without one. */
export function plinthWeight(equipment: IEquipment, context: IMepContext): number {
	const height = num(equipment.plinth?.height);
	if (height <= 0) {
		return 0;
	}
	const material = context.concretes.find(c => c.id === equipment.plinth?.material) ?? context.concretes[0];
	const unitWeight = material?.unitWeight ?? 2400 * GRAVITY / 1000;
	return unitWeight * equipmentArea(equipment) * height / 1000;
}

/** The equipment of each story with its operating weight and plinths [kN], in story order. */
export function storyLoads(document: IMep, context: IMepContext): { story: string; count: number; operating: number; plinths: number }[] {
	const order = new Map(context.stories.map((s, i) => [s.id, i]));
	const loads = new Map<string, { story: string; count: number; operating: number; plinths: number }>();
	for (const e of document.equipment) {
		const entry = loads.get(e.story) ?? { story: e.story, count: 0, operating: 0, plinths: 0 };
		entry.count++;
		entry.operating += num(e.operatingWeight);
		entry.plinths += plinthWeight(e, context);
		loads.set(e.story, entry);
	}
	return [...loads.values()].sort((a, b) => (order.get(a.story) ?? 1e9) - (order.get(b.story) ?? 1e9));
}

// ───────────────────────────── new items ─────────────────────────────

/** A starting point for a new equipment: typical size and weight, for the engineer to edit. */
export interface IEquipmentPreset {
	readonly kind: EquipmentKind;
	readonly name: string;
	readonly length: number;
	readonly width: number;
	readonly height: number;
	readonly operatingWeight: number;
	readonly emptyWeight: number;
	readonly vibrating?: boolean;
	/** Height of a concrete plinth [mm]. */
	readonly plinth?: number;
}

/**
 * Typical sizes and weights of common building equipment, to start from: the engineer replaces
 * them with the supplier's data. A 4 × 3 × 2 m water tank holds 24 m³ (about 235 kN of water).
 */
export const EQUIPMENT_PRESETS: readonly IEquipmentPreset[] = [
	{ kind: 'tank', name: localize('mep.preset.tank', "Overhead water tank"), length: 4000, width: 3000, height: 2000, operatingWeight: 265, emptyWeight: 30 },
	{ kind: 'chiller', name: localize('mep.preset.chiller', "Chiller"), length: 6000, width: 2300, height: 2400, operatingWeight: 85, emptyWeight: 75, vibrating: true, plinth: 150 },
	{ kind: 'ahu', name: localize('mep.preset.ahu', "Air handling unit"), length: 3000, width: 1500, height: 1800, operatingWeight: 18, emptyWeight: 16, vibrating: true, plinth: 100 },
	{ kind: 'generator', name: localize('mep.preset.generator', "Generator"), length: 4500, width: 1600, height: 2200, operatingWeight: 65, emptyWeight: 58, vibrating: true, plinth: 150 },
	{ kind: 'transformer', name: localize('mep.preset.transformer', "Transformer"), length: 2200, width: 1500, height: 2000, operatingWeight: 40, emptyWeight: 30, plinth: 150 },
	{ kind: 'lift', name: localize('mep.preset.lift', "Lift machine room"), length: 2500, width: 2500, height: 2500, operatingWeight: 60, emptyWeight: 60, vibrating: true },
	{ kind: 'pump', name: localize('mep.preset.pump', "Pump"), length: 1200, width: 600, height: 800, operatingWeight: 6, emptyWeight: 5, vibrating: true, plinth: 150 },
];

export function equipmentKindLabel(kind: string): string {
	switch (kind) {
		case 'tank': return localize('mep.kind.tank', "Water tank");
		case 'chiller': return localize('mep.kind.chiller', "Chiller");
		case 'ahu': return localize('mep.kind.ahu', "Air handling unit");
		case 'pump': return localize('mep.kind.pump', "Pump");
		case 'generator': return localize('mep.kind.generator', "Generator");
		case 'transformer': return localize('mep.kind.transformer', "Transformer");
		case 'lift': return localize('mep.kind.lift', "Lift machine");
		case 'other': return localize('mep.kind.other', "Other");
		default: return kind;
	}
}

export function openingKindLabel(kind: string): string {
	return kind === 'sleeve' ? localize('mep.opening.sleeve', "Sleeve") : kind === 'opening' ? localize('mep.opening.opening', "Opening") : kind;
}

export function openingShapeLabel(shape: string): string {
	return shape === 'circle' ? localize('mep.shape.circle', "Circle") : shape === 'rectangle' ? localize('mep.shape.rectangle', "Rectangle") : shape;
}

export function disciplineLabel(discipline: string): string {
	switch (discipline) {
		case 'mechanical': return localize('mep.discipline.mechanical', "Mechanical");
		case 'plumbing': return localize('mep.discipline.plumbing', "Plumbing");
		case 'fire': return localize('mep.discipline.fire', "Fire protection");
		case 'electrical': return localize('mep.discipline.electrical', "Electrical");
		default: return discipline;
	}
}

export function hostKindLabel(kind: HostKind | string): string {
	return kind === 'beam' ? localize('mep.host.beam', "Beam") : kind === 'slab' ? localize('mep.host.slab', "Slab") : kind === 'wall' ? localize('mep.host.wall', "Wall") : kind;
}

/** The IDs of the file's equipment, openings and shafts: one ID space, as the backend requires. */
export function usedIds(document: IMep): string[] {
	return [...document.equipment, ...document.openings, ...document.shafts].map(item => item.id);
}

/** The IDs the backend accepts (as for every SAEngine part): letters, digits, '.', '_' and '-', at most 64. */
const ID_PATTERN = /^[A-Za-z0-9._-]+$/;

/** Why `id` is not an ID the backend accepts; undefined when it is one (an empty one is "missing", checked apart). */
export function idError(id: string): string | undefined {
	if (!id) {
		return undefined;
	}
	if (!ID_PATTERN.test(id)) {
		return localize('mep.v.idChars', "use only letters, digits, '.', '_' and '-' (no spaces).");
	}
	return id.length > 64 ? localize('mep.v.idLength', "use at most 64 characters.") : undefined;
}

/** The first `prefix` + number not in `used`. */
export function nextId(prefix: string, used: Iterable<string>): string {
	const taken = new Set(used);
	for (let i = 1; ; i++) {
		if (!taken.has(`${prefix}${i}`)) {
			return `${prefix}${i}`;
		}
	}
}

function bounds(points: readonly Point[]): [number, number, number, number] | undefined {
	if (!points.length) {
		return undefined;
	}
	return [Math.min(...points.map(p => p[0])), Math.max(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[1]))];
}

/** The plan points of what a story shows (its floor, columns, walls), else of the whole building. */
export function storyExtent(context: IMepContext, storyId: string): Point[] {
	const elements = storyElements(context, storyId);
	const points: Point[] = [
		...elements.slabs.flatMap(s => s.boundary),
		...elements.beams.flatMap(b => [b.start, b.end]),
		...elements.walls.flatMap(w => [w.start, w.end]),
		...elements.columns.map(c => [c.x, c.y] as Point),
	];
	if (points.length) {
		return points;
	}
	return [...context.columns.map(c => [c.x, c.y] as Point), ...context.slabs.flatMap(s => s.boundary), ...context.beams.flatMap(b => [b.start, b.end])];
}

function round(value: number, step = 50): number {
	return Math.round(value / step) * step;
}

/**
 * A new equipment from a preset on `story`: at the free place nearest the middle of the story's
 * floor (on a grid of at least 250 mm) where its footprint lies wholly on the story's slabs and
 * overlaps no other equipment, no opening of the building model's slabs and no shaft; turned by
 * 90° when it fits nowhere as it is. Without such a place, the clear place with most of it on a slab.
 */
export function newEquipment(document: IMep, context: IMepContext, preset: IEquipmentPreset, story: string): IEquipment {
	const extent = bounds(storyExtent(context, story)) ?? [0, 10000, 0, 10000];
	const center: Point = [round((extent[0] + extent[1]) / 2), round((extent[2] + extent[3]) / 2)];
	const equipment: IEquipment = {
		id: nextId('EQ', usedIds(document)),
		name: preset.name,
		kind: preset.kind,
		story,
		x: center[0], y: center[1],
		length: preset.length, width: preset.width, height: preset.height,
		operatingWeight: preset.operatingWeight, emptyWeight: preset.emptyWeight,
		...(preset.vibrating ? { vibrating: true } : {}),
		...(preset.plinth ? { plinth: { height: preset.plinth, ...(context.concretes[0] ? { material: context.concretes[0].id } : {}) } } : {}),
	};
	const elements = storyElements(context, story);
	// Kept clear of: the equipment already on the story, the building model's slab openings, the shafts through the floor.
	const obstacles = [
		...document.equipment.filter(e => e.story === story).map(equipmentOutline),
		...elements.slabOpenings.map(bimOpeningOutline),
		...document.shafts.filter(s => shaftOnStory(s, context, story) && s.outline.length >= 3).map(s => s.outline),
	];
	const slabs = elements.slabs;
	// Candidate centres on a grid over the floor, nearest the middle first.
	const step = Math.max(250, round(Math.max(extent[1] - extent[0], extent[3] - extent[2]) / 60, 250));
	const candidates: Point[] = [];
	for (let x = round(extent[0], step); x <= extent[1] + step / 2; x += step) {
		for (let y = round(extent[2], step); y <= extent[3] + step / 2; y += step) {
			candidates.push([x, y]);
		}
	}
	candidates.sort((a, b) => Math.hypot(a[0] - center[0], a[1] - center[1]) - Math.hypot(b[0] - center[0], b[1] - center[1]));
	const orientations = preset.length === preset.width ? [0] : [0, 90];
	const at = (point: Point, rotation: number): IEquipment => rotation ? { ...equipment, x: point[0], y: point[1], rotation } : { ...equipment, x: point[0], y: point[1] };
	const clear = (candidate: IEquipment) => {
		const outline = equipmentOutline(candidate);
		return !obstacles.some(o => convexOverlap(o, outline));
	};
	// The share of the footprint on a slab: checked at a node grid (corners and edges included) at most 500 mm apart.
	const supported = (candidate: IEquipment) => {
		const nodes = footprintNodes(candidate, 500);
		return nodes.filter(p => slabs.some(s => insideOrOn(p, s.boundary))).length / nodes.length;
	};
	if (slabs.length) {
		// First wholly on the slabs, clear of everything (its load then reaches the members as placed).
		for (const rotation of orientations) {
			for (const point of candidates) {
				const candidate = at(point, rotation);
				if (supported(candidate) === 1 && clear(candidate)) {
					return candidate;
				}
			}
		}
	}
	// Else clear, with as much of it on a slab as there is room for.
	let best: { candidate: IEquipment; share: number } | undefined;
	for (const point of candidates) {
		const candidate = at(point, 0);
		if (!clear(candidate)) {
			continue;
		}
		const share = slabs.length ? supported(candidate) : 1;
		if (!best || share > best.share + 1e-9) {
			best = { candidate, share };
		}
		if (share === 1) {
			break;
		}
	}
	return best?.candidate ?? equipment;
}

/** The nodes of a grid over an equipment's footprint, corners and edges included, at most `spacing` apart. */
function footprintNodes(equipment: IEquipment, spacing: number): Point[] {
	const center: Point = [num(equipment.x), num(equipment.y)];
	const length = num(equipment.length);
	const width = num(equipment.width);
	const nu = Math.max(1, Math.ceil(length / spacing));
	const nv = Math.max(1, Math.ceil(width / spacing));
	const nodes: Point[] = [];
	for (let i = 0; i <= nu; i++) {
		for (let j = 0; j <= nv; j++) {
			nodes.push(toGlobal(center, -length / 2 + i * length / nu, -width / 2 + j * width / nv, num(equipment.rotation)));
		}
	}
	return nodes;
}

/**
 * A new sleeve through `host`: a 150 mm round sleeve at mid-span and mid-depth of a beam, at the
 * middle of a wall, or at the centre of a slab.
 */
export function newSleeve(document: IMep, context: IMepContext, hostId: string): IOpening | undefined {
	const host = findHost(context, hostId);
	if (!host) {
		return undefined;
	}
	const id = nextId('OP', usedIds(document));
	const base = { id, host: hostId, kind: 'sleeve', shape: 'circle', diameter: 150, service: '' };
	switch (host.kind) {
		case 'beam': return { ...base, position: { distance: round(length(host.element.start, host.element.end) / 2), elevation: round(host.element.depth / 2, 10) } };
		case 'wall': return { ...base, position: { x: round(length(host.element.start, host.element.end) / 2), y: round((host.element.top - host.element.bottom) / 2) } };
		case 'slab': {
			const center = centroid(host.element.boundary) ?? [0, 0];
			return { ...base, position: { x: round(center[0]), y: round(center[1]) } };
		}
	}
}

/**
 * A new 1.5 m square shaft in the middle of `story`'s floor that cuts that floor and every one
 * above it: it starts at the story below `story` (not cut) and goes up to the top story. On the
 * lowest story it starts there and cuts the floors above.
 */
export function newShaft(document: IMep, context: IMepContext, story: string): IShaft {
	const extent = bounds(storyExtent(context, story)) ?? [0, 10000, 0, 10000];
	const cx = round((extent[0] + extent[1]) / 2);
	const cy = round((extent[2] + extent[3]) / 2);
	const half = 750;
	const index = context.stories.findIndex(s => s.id === story);
	const fromStory = index > 0 ? context.stories[index - 1].id : story;
	return {
		id: nextId('SH', usedIds(document)),
		outline: [[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]],
		fromStory,
		toStory: context.stories[context.stories.length - 1]?.id ?? story,
		service: '',
	};
}

/** The discipline an IFC file's name suggests ("Plumbing.ifc"), else mechanical. */
export function guessDiscipline(path: string): Discipline {
	const name = path.toLowerCase().replace(/^.*[\\/]/, '');
	if (/plumb|sanit|drain|water|sewer|storm/.test(name)) {
		return 'plumbing';
	}
	if (/fire|sprink|hydrant/.test(name)) {
		return 'fire';
	}
	if (/elec|power|light|cable|tray/.test(name)) {
		return 'electrical';
	}
	return 'mechanical';
}

// ───────────────────────────── checks ─────────────────────────────

export interface IMepProblem {
	/** Dotted path of the field ("equipment.0.story"), for marking its input. */
	readonly path: string;
	readonly severity: 'error' | 'warning';
	readonly message: string;
}

function duplicates(ids: readonly string[]): Set<string> {
	const seen = new Set<string>();
	const repeated = new Set<string>();
	for (const id of ids) {
		if (seen.has(id)) {
			repeated.add(id);
		}
		seen.add(id);
	}
	return repeated;
}

/** What is missing or inconsistent in the file against the building model (not the design checks). */
export function checkMep(document: IMep, context: IMepContext): IMepProblem[] {
	const problems: IMepProblem[] = [];
	const add = (path: string, severity: 'error' | 'warning', message: string) => problems.push({ path, severity, message });
	const storyIds = new Set(context.stories.map(s => s.id));
	const lowest = context.stories[0]?.id;

	// One ID space for the equipment, openings and shafts (the backend refuses a file that repeats one).
	const repeated = duplicates(usedIds(document));
	const checkId = (path: string, id: unknown) => {
		if (typeof id !== 'string' || !id) {
			add(path, 'error', localize('mep.p.noId', "An item has no ID."));
		} else if (idError(id)) {
			add(path, 'error', localize('mep.p.badId', "The ID '{0}' is not valid: {1}", id, idError(id)));
		} else if (repeated.has(id)) {
			add(path, 'error', localize('mep.p.duplicate', "The ID {0} is used twice.", id));
		}
	};
	document.equipment.forEach((e, i) => {
		const path = (field: string) => `equipment.${i}.${field}`;
		checkId(path('id'), e.id);
		if (context.stories.length && !storyIds.has(e.story)) {
			add(path('story'), 'error', localize('mep.p.equipmentStory', "{0}: the building model has no story '{1}'.", e.id, String(e.story ?? '')));
		}
		if (!(EQUIPMENT_KINDS as readonly unknown[]).includes(e.kind ?? 'other')) {
			add(path('kind'), 'error', localize('mep.p.kind', "{0}: '{1}' is not a kind of equipment ({2}).", e.id, String(e.kind), EQUIPMENT_KINDS.join(', ')));
		}
		if (!(num(e.length) > 0) || !(num(e.width) > 0)) {
			add(path(num(e.length) > 0 ? 'width' : 'length'), 'error', localize('mep.p.footprint', "{0}: give the footprint's length and width.", e.id));
		}
		if (e.height !== undefined && e.height !== null && !(num(e.height) > 0)) {
			add(path('height'), 'error', localize('mep.p.height', "{0}: give a height above 0, or leave it empty.", e.id));
		}
		if (e.emptyWeight !== undefined && e.emptyWeight !== null && !(num(e.emptyWeight) > 0)) {
			add(path('emptyWeight'), 'error', localize('mep.p.emptyZero', "{0}: give an empty weight above 0 kN, or leave it empty (then the operating weight).", e.id));
		}
		if (!(num(e.operatingWeight) > 0)) {
			add(path('operatingWeight'), 'error', localize('mep.p.weight', "{0}: give the operating weight.", e.id));
		} else if (typeof e.emptyWeight === 'number' && e.emptyWeight > e.operatingWeight) {
			add(path('emptyWeight'), 'error', localize('mep.p.empty', "{0}: the empty weight is more than the operating weight.", e.id));
		}
		if (e.plinth !== undefined && e.plinth !== null) {
			if (!(num(e.plinth.height) > 0)) {
				add(path('plinth.height'), 'error', localize('mep.p.plinthHeight', "{0}: give the plinth's height, or remove the plinth.", e.id));
			}
			if (!e.plinth.material) {
				add(path('plinth.material'), 'error', localize('mep.p.plinthMaterial', "{0}: choose the plinth's concrete.", e.id));
			} else if (context.concretes.length && !context.concretes.some(c => c.id === e.plinth?.material)) {
				add(path('plinth.material'), 'warning', localize('mep.p.plinthConcrete', "{0}: 03 Materials has no concrete '{1}'.", e.id, String(e.plinth.material)));
			}
		}
		// Where the backend applies its load: at its load points on the slabs of the story, outside the slabs' openings.
		if (storyIds.has(e.story) && e.story !== lowest && num(e.length) > 0 && num(e.width) > 0) {
			const support = equipmentSupport(e, context);
			if (!support.onSlab) {
				add(path('x'), 'warning', localize('mep.p.noSlab', "{0} stands on no slab of {1}: its load is not applied to the structure.", e.id, e.story));
			} else if (support.onSlab < support.points) {
				const hole = support.overOpenings[0];
				add(path('x'), 'warning', hole
					? localize('mep.p.overOpening', "{0} stands partly over opening {1} of slab {2}: {3} of its {4} load points are on no slab, and the rest carry its whole load.", e.id, hole.opening, hole.slab, support.points - support.onSlab, support.points)
					: localize('mep.p.offSlab', "{0} stands partly off the slabs of {1}: {2} of its {3} load points are on no slab, and the rest carry its whole load.", e.id, e.story, support.points - support.onSlab, support.points));
			}
		}
	});

	document.openings.forEach((o, i) => {
		const path = (field: string) => `openings.${i}.${field}`;
		checkId(path('id'), o.id);
		if (!(OPENING_KINDS as readonly unknown[]).includes(o.kind ?? 'sleeve')) {
			add(path('kind'), 'error', localize('mep.p.openingKind', "{0}: the kind must be sleeve or opening.", o.id));
		}
		if (!(OPENING_SHAPES as readonly unknown[]).includes(o.shape ?? 'circle')) {
			add(path('shape'), 'error', localize('mep.p.openingShape', "{0}: the shape must be circle or rectangle.", o.id));
		}
		const host = findHost(context, o.host);
		if (!host) {
			add(path('host'), 'error', localize('mep.p.host', "{0}: the building model has no beam, slab or wall '{1}'.", o.id, String(o.host ?? '')));
			return;
		}
		// The backend needs both coordinates of the position: distance and elevation in a beam, x and y in a slab or wall.
		const given = (value: unknown) => typeof value === 'number' && Number.isFinite(value);
		const pair = host.kind === 'beam' ? ['distance', 'elevation'] as const : ['x', 'y'] as const;
		const missing = pair.find(key => !given(o.position?.[key]));
		if (missing) {
			add(path(`position.${missing}`), 'error', host.kind === 'beam'
				? localize('mep.p.positionBeam', "{0}: give its distance from the start and its height above the bottom of beam {1}.", o.id, host.element.id)
				: host.kind === 'wall'
					? localize('mep.p.positionWall', "{0}: give its position along and up wall {1}.", o.id, host.element.id)
					: localize('mep.p.positionSlab', "{0}: give its X and Y in slab {1}.", o.id, host.element.id));
			return;
		}
		const circle = o.shape === 'circle';
		const across = circle ? num(o.diameter) : num(o.width);
		const up = circle ? num(o.diameter) : num(o.height);
		if (!(across > 0) || !(up > 0)) {
			add(path(circle ? 'diameter' : across > 0 ? 'height' : 'width'), 'error', localize('mep.p.size', "{0}: give its size.", o.id));
			return;
		}
		const position = o.position ?? {};
		if (host.kind === 'beam') {
			const span = length(host.element.start, host.element.end);
			const distance = num(position.distance);
			if (distance - across / 2 < 0 || distance + across / 2 > span) {
				add(path('position.distance'), 'error', localize('mep.p.beamSpan', "{0} lies beyond the ends of beam {1} ({2} m long).", o.id, host.element.id, formatNumber(span / 1000, 2)));
			}
			const elevation = num(position.elevation, host.element.depth / 2);
			if (elevation - up / 2 < 0 || elevation + up / 2 > host.element.depth) {
				add(path('position.elevation'), 'error', localize('mep.p.beamDepth', "{0} does not fit in the {1} mm depth of beam {2}.", o.id, formatNumber(host.element.depth, 0), host.element.id));
			}
		} else if (host.kind === 'wall') {
			const span = length(host.element.start, host.element.end);
			const x = num(position.x);
			const y = num(position.y);
			if (x - across / 2 < 0 || x + across / 2 > span) {
				add(path('position.x'), 'error', localize('mep.p.wallLength', "{0} lies beyond the ends of wall {1}.", o.id, host.element.id));
			}
			if (y - up / 2 < 0 || y + up / 2 > host.element.top - host.element.bottom) {
				add(path('position.y'), 'error', localize('mep.p.wallHeight', "{0} lies above or below wall {1}.", o.id, host.element.id));
			}
		} else if (!insidePolygon([num(position.x), num(position.y)], host.element.boundary)) {
			add(path('position.x'), 'error', localize('mep.p.slab', "{0} lies outside slab {1}.", o.id, host.element.id));
		}
	});

	document.shafts.forEach((s, i) => {
		const path = (field: string) => `shafts.${i}.${field}`;
		checkId(path('id'), s.id);
		if (s.outline.length < 3 || polygonArea(s.outline) <= 0) {
			add(path('outline'), 'error', localize('mep.p.outline', "{0}: the outline needs at least three points around an area.", s.id));
		}
		let storiesKnown = true;
		for (const end of ['fromStory', 'toStory'] as const) {
			if (context.stories.length && !storyIds.has(s[end])) {
				storiesKnown = false;
				add(path(end), 'error', localize('mep.p.shaftStory', "{0}: the building model has no story '{1}'.", s.id, String(s[end] ?? '')));
			}
		}
		const from = context.stories.find(story => story.id === s.fromStory);
		const to = context.stories.find(story => story.id === s.toStory);
		if (storiesKnown && from && to && to.elevation <= from.elevation + TOLERANCE) {
			add(path('toStory'), 'error', localize('mep.p.shaftOrder', "{0}: its top story must be above the story it starts at.", s.id));
		}
	});

	document.ifcModels.forEach((m, i) => {
		if (!m.path) {
			add(`ifcModels.${i}.path`, 'error', localize('mep.p.ifcPath', "An IFC model has no path."));
		} else if (!/\.ifc$/i.test(m.path)) {
			add(`ifcModels.${i}.path`, 'warning', localize('mep.p.ifcExt', "{0} is not an .ifc file.", m.path));
		}
		if (!(DISCIPLINES as readonly unknown[]).includes(m.discipline ?? 'mechanical')) {
			add(`ifcModels.${i}.discipline`, 'error', localize('mep.p.discipline', "{0}: the discipline must be one of {1}.", m.path, DISCIPLINES.join(', ')));
		}
	});
	return problems;
}

// ───────────────────────────── the backend's report ─────────────────────────────

export interface IMepRequest {
	/** The project folder (fsPath). */
	readonly projectRoot: string;
	/** The editor's text of `mep.json`, which may hold unsaved edits. */
	readonly mepText?: string;
}

export interface IImportIfcRequest {
	readonly projectRoot: string;
	/** Project-relative path of the model, with forward slashes. */
	readonly path: string;
}

export interface IEquipmentLoad {
	readonly id: string;
	readonly story?: string;
	/** The load carried to the structure [kN]. */
	readonly load?: number;
	/** Over the footprint [kPa]. */
	readonly pressure?: number;
	/** The slab or beam it loads. */
	readonly host?: string;
	readonly loadCase?: string;
	readonly note?: string;
}

export interface IStoryLoad {
	readonly story: string;
	readonly count?: number;
	readonly load: number;
	readonly note?: string;
}

export interface IOpeningCheck {
	readonly id: string;
	readonly host?: string;
	readonly check?: string;
	readonly utilisation?: number | null;
	readonly ok: boolean;
	/** False when no check applied to it (the backend found nothing to check it against). */
	readonly checked: boolean;
	/**
	 * False when its strength checks (shear and flexure of a beam, punching of a slab) did not
	 * run, e.g. without analysis results: then only its size and spacing are checked, and its
	 * `ok` says nothing of its strength.
	 */
	readonly strengthChecked: boolean;
	readonly note?: string;
}

export type ClashStatus = 'coordinated' | 'clash';

export interface IClash {
	readonly id: string;
	/** The MEP element (IFC GlobalId or name). */
	readonly mep: string;
	readonly mepName?: string;
	readonly discipline?: string;
	/** The structural element it meets (06 BIM id). */
	readonly structural: string;
	readonly structuralKind?: string;
	/** "hard" (passes through), "clearance"... */
	readonly kind: string;
	/** Coordinated when an opening of the MEP file already takes it through. */
	readonly status: ClashStatus;
	/** Where they meet [mm]; z is the elevation. */
	readonly point?: readonly [number, number, number?];
	readonly story?: string;
	/** Size of the MEP element where it passes (a pipe's outer diameter) [mm]. */
	readonly size?: number;
	/** The opening that coordinates it. */
	readonly opening?: string;
	/** The sleeve the backend proposes for it. */
	readonly sleeve?: IOpening;
	/** The backend's note ("runs along beam B1: reroute"). */
	readonly note?: string;
}

export interface IMepReport {
	readonly equipment: readonly IEquipmentLoad[];
	readonly stories: readonly IStoryLoad[];
	readonly openings: readonly IOpeningCheck[];
	readonly clashes: readonly IClash[];
	readonly notes: readonly string[];
	readonly method: readonly string[];
	/** The stamps of the part files the report read, by part id. */
	readonly sources?: { readonly [part: string]: string };
}

function optionalNumber(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function optionalString(value: unknown): string | undefined {
	return typeof value === 'string' && value ? value : undefined;
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

function readOpening(value: unknown): IOpening | undefined {
	if (!isRecord(value) || typeof value.host !== 'string') {
		return undefined;
	}
	const opening: IOpening = {
		...value,
		id: String(value.id ?? ''),
		host: value.host,
		kind: String(value.kind ?? 'sleeve'),
		shape: String(value.shape ?? 'circle'),
		position: isRecord(value.position) ? value.position : {},
	};
	return opening;
}

/**
 * What the backend writes of an opening whose strength checks did not run (until it sends
 * `strengthChecked`): "no analysis results; shear and flexure at it are not checked", "not found
 * in the analysis results of B1", "B1 is not checked: ...", and a punching check flagged "(no results)".
 */
const STRENGTH_SKIPPED = /no analysis results|not found in the analysis results|\bis not checked\b|are not checked|\(no results\)/i;

function strengthSkipped(opening: Record<string, unknown>, note: string | undefined): boolean {
	const texts = [note ?? '', ...strings(opening.notes), ...records(opening.checks).map(c => typeof c.note === 'string' ? c.note : '')];
	return texts.some(text => STRENGTH_SKIPPED.test(text));
}

/** The backend's report, read defensively; undefined when it is not one. */
export function readMepReport(raw: unknown): IMepReport | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const equipment = records(raw.equipment).filter(e => typeof e.id === 'string').map(e => ({
		id: String(e.id), story: optionalString(e.story), load: optionalNumber(e.load ?? e.operatingWeight), pressure: optionalNumber(e.pressure),
		host: optionalString(e.host), loadCase: optionalString(e.loadCase), note: optionalString(e.note),
	}));
	const stories = records(raw.stories).filter(s => typeof s.story === 'string').map(s => ({
		story: String(s.story), count: optionalNumber(s.count), load: num(s.load), note: optionalString(s.note),
	}));
	const openings = records(raw.openings).filter(o => typeof o.id === 'string').map(o => {
		const checked = o.checked !== false;
		const utilisation = checked ? optionalNumber(o.utilisation) ?? null : null;
		const note = optionalString(o.note);
		return {
			id: String(o.id), host: optionalString(o.host), check: optionalString(o.check), utilisation, checked,
			strengthChecked: checked && (typeof o.strengthChecked === 'boolean' ? o.strengthChecked : !strengthSkipped(o, note)),
			ok: !checked || (typeof o.ok === 'boolean' ? o.ok : utilisation === null || utilisation <= 1), note,
		};
	});
	const clashes = records(raw.clashes).map((c, i) => {
		const point = Array.isArray(c.point) && c.point.length >= 2 && c.point.slice(0, 3).every(v => typeof v === 'number') ? c.point.slice(0, 3) as unknown as [number, number, number?] : undefined;
		return {
			id: String(c.id ?? `CL${i + 1}`), mep: String(c.mep ?? c.mepElement ?? ''), mepName: optionalString(c.mepName), discipline: optionalString(c.discipline),
			structural: String(c.structural ?? c.structuralElement ?? ''), structuralKind: optionalString(c.structuralKind), kind: String(c.kind ?? 'hard'),
			status: (c.status === 'coordinated' ? 'coordinated' : 'clash') as ClashStatus, point, story: optionalString(c.story), size: optionalNumber(c.size),
			opening: optionalString(c.opening), sleeve: readOpening(c.sleeve), note: optionalString(c.note),
		};
	});
	const sources = isRecord(raw.sources) ? Object.fromEntries(Object.entries(raw.sources).filter((e): e is [string, string] => typeof e[1] === 'string')) : undefined;
	return { equipment, stories, openings, clashes, notes: strings(raw.notes), method: strings(raw.method), sources };
}

/** The openings the backend proposes (`saengine.mep.suggestSleeves`) and its notes. */
export function readSleeveSuggestions(raw: unknown): { openings: IOpening[]; notes: string[] } | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	return { openings: (Array.isArray(raw.openings) ? raw.openings : []).map(readOpening).filter((o): o is IOpening => !!o), notes: strings(raw.notes) };
}

/** What `saengine.mep.importIfc` says of a model it read. */
export function readIfcImport(raw: unknown): { discipline?: Discipline; elements?: number; notes: string[] } | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const discipline = isRecord(raw.model) ? raw.model.discipline : raw.discipline;
	return {
		discipline: (DISCIPLINES as readonly unknown[]).includes(discipline) ? discipline as Discipline : undefined,
		elements: optionalNumber(raw.elements),
		notes: strings(raw.notes),
	};
}

/**
 * The sleeve for a clash: the backend's proposal (sized from the service's cross-section where
 * it crosses, with the allowance each side, rounded up), with an ID not yet used in the file.
 * Undefined when the backend proposed none: the service runs along the beam or wall, or cuts a
 * column or foundation, and is to be rerouted.
 */
export function sleeveForClash(document: IMep, clash: IClash): IOpening | undefined {
	if (!clash.sleeve) {
		return undefined;
	}
	const used = usedIds(document);
	const id = clash.sleeve.id && !used.includes(clash.sleeve.id) ? clash.sleeve.id : nextId('OP', used);
	return { ...clash.sleeve, id };
}

/** An opening that passes only because its strength checks did not run (or nothing was checked). */
export function isPartlyChecked(check: IOpeningCheck): boolean {
	return check.ok && !check.strengthChecked;
}

/** A clash still to coordinate: the MEP element passes through without an opening (clearance ones are listed, not counted). */
export function isOpenClash(clash: IClash): boolean {
	return clash.status === 'clash' && clash.kind !== 'clearance';
}

/** The utilisation band of the shared ok / warn / fail tiers. */
export function utilisationBand(utilisation: number | null | undefined): 'ok' | 'warn' | 'fail' | 'none' {
	if (typeof utilisation !== 'number' || !Number.isFinite(utilisation)) {
		return 'none';
	}
	return utilisation > 1 ? 'fail' : utilisation >= 0.9 ? 'warn' : 'ok';
}

export function formatUtilisation(value: number): string {
	return value.toFixed(2);
}

/** The status line: "12 equipment · 2 openings fail · 3 clashes". */
export function mepSummary(document: IMep, report: IMepReport | undefined): string {
	const parts: string[] = [];
	const count = document.equipment.length;
	parts.push(localize('mep.sum.equipment', "{0} equipment", count));
	if (report) {
		const failed = report.openings.filter(o => !o.ok).length;
		const partial = report.openings.filter(isPartlyChecked).length;
		if (failed) {
			parts.push(failed === 1 ? localize('mep.sum.openingFails', "1 opening fails") : localize('mep.sum.openingsFail', "{0} openings fail", failed));
		}
		if (partial) {
			parts.push(partial === 1 ? localize('mep.sum.openingPartial', "1 opening not fully checked") : localize('mep.sum.openingsPartial', "{0} openings not fully checked", partial));
		}
		if (!failed && !partial && document.openings.length) {
			parts.push(document.openings.length === 1 ? localize('mep.sum.openingOk', "1 opening") : localize('mep.sum.openingsOk', "{0} openings", document.openings.length));
		}
		const clashes = report.clashes.filter(isOpenClash).length;
		if (clashes) {
			parts.push(clashes === 1 ? localize('mep.sum.clash', "1 clash") : localize('mep.sum.clashes', "{0} clashes", clashes));
		} else if (report.clashes.length) {
			parts.push(localize('mep.sum.coordinated', "{0} crossings coordinated", report.clashes.length));
		}
	} else {
		if (document.openings.length) {
			parts.push(document.openings.length === 1 ? localize('mep.sum.openingOk', "1 opening") : localize('mep.sum.openingsOk', "{0} openings", document.openings.length));
		}
		if (document.shafts.length) {
			parts.push(document.shafts.length === 1 ? localize('mep.sum.shaft', "1 shaft") : localize('mep.sum.shafts', "{0} shafts", document.shafts.length));
		}
	}
	return parts.join(' · ');
}

/** Content of {@link MEP_SUMMARY_FILE}, read by the project's part list. */
export interface IMepSummaryFile {
	readonly equipment: number;
	readonly openings: number;
	readonly openingsFailed: number;
	/** Openings that pass their size and spacing checks, but whose strength checks did not run. */
	readonly openingsPartial: number;
	readonly clashes: number;
	readonly clashesOpen: number;
	/** ISO time the report was computed. */
	readonly computed: string;
	/** The stamps of the part files the report read, by part id; the MEP file's own at least. */
	readonly source: { readonly [part: string]: string };
}

/**
 * The summary for the part list. `sourceTexts` are the texts of {@link MEP_SOURCE_PARTS} the
 * report was asked with: each is stamped (a missing one as ''), so the part list can tell when the
 * building has changed since.
 */
export function mepSummaryFile(document: IMep, report: IMepReport, mepText: string, computed: Date, sourceTexts: IMepContextTexts): IMepSummaryFile {
	const stamps = Object.fromEntries(MEP_SOURCE_PARTS.map(part => {
		const text = sourceTexts[part];
		return [part, text === undefined ? '' : sourceStamp(text)];
	}));
	return {
		equipment: document.equipment.length,
		openings: document.openings.length,
		openingsFailed: report.openings.filter(o => !o.ok).length,
		openingsPartial: report.openings.filter(isPartlyChecked).length,
		clashes: report.clashes.length,
		clashesOpen: report.clashes.filter(isOpenClash).length,
		computed: computed.toISOString(),
		source: { ...report.sources, ...stamps, mep: sourceStamp(mepText) },
	};
}
