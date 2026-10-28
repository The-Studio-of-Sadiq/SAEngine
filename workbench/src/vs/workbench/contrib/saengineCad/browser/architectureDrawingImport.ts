/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadPoint } from '@saengine/cad-editor';
import { IArchitecture } from './architectureModel.js';

/**
 * The model of the "Import Architect's DWG/DXF..." step of the Architecture editor: what each
 * layer of the drawing holds (guessed from common layer names and what is on the layer, or
 * remembered from an earlier import in this project), the drawing's unit and its placement on
 * the grid. The backend (`architecture/importDrawing`) reads the drawing with this mapping.
 */

export type DrawingRole = 'walls' | 'doors' | 'windows' | 'rooms' | 'ignore';
export const DRAWING_ROLES: readonly DrawingRole[] = ['walls', 'doors', 'windows', 'rooms', 'ignore'];

export type DrawingUnit = 'mm' | 'cm' | 'm' | 'ft' | 'in';
export const DRAWING_UNITS: readonly DrawingUnit[] = ['mm', 'cm', 'm', 'ft', 'in'];
/** Drawing units in mm. */
export const UNIT_MM: { readonly [unit in DrawingUnit]: number } = { mm: 1, cm: 10, m: 1000, ft: 304.8, in: 25.4 };

/** What `architecture/inspectDrawing` says of a drawing (drawing units). */
export interface IDrawingInfo {
	readonly layers: readonly IDrawingLayer[];
	readonly unit: DrawingUnit;
	readonly unitGuessed: boolean;
	readonly extents: readonly [CadPoint, CadPoint] | null;
	/** Shapes per layer, each a flat list x0, y0, x1, y1, ... */
	readonly preview: { readonly [layer: string]: readonly (readonly number[])[] };
	readonly labels: readonly { readonly layer: string; readonly text: string; readonly at: CadPoint }[];
	readonly warnings: readonly string[];
	readonly problems?: readonly string[];
}

export interface IDrawingLayer {
	readonly name: string;
	readonly counts: { readonly lines: number; readonly arcs: number; readonly blocks: number; readonly texts: number; readonly other: number };
	readonly total: number;
	readonly blocks: readonly string[];
	readonly texts: readonly string[];
}

/** An import recorded in architecture.json (`imports`). */
export interface IDrawingImportRecord {
	readonly file: string;
	readonly story: string;
	readonly layers?: { readonly [layer: string]: DrawingRole };
	readonly unit?: DrawingUnit;
	readonly base?: CadPoint;
	readonly at?: CadPoint;
	readonly rotation?: number;
	readonly items?: readonly string[];
}

/** What the backend is asked to do with the drawing. */
export interface IDrawingImportOptions {
	readonly layers: { readonly [layer: string]: DrawingRole };
	readonly unit: DrawingUnit;
	readonly story: string;
	/** The drawing's point (drawing units) placed at `at` (plan mm). */
	readonly base: CadPoint;
	readonly at: CadPoint;
	readonly rotation: number;
	/** A second pair of points: the rotation follows from both pairs instead. */
	readonly align?: { readonly base: CadPoint; readonly at: CadPoint };
	/** The file as recorded (relative to the project folder when it is inside it). */
	readonly source: string;
	/** The wall type of walls drawn as single centre lines. */
	readonly wallType?: string;
}

const tokens = (name: string) => name.toUpperCase().split(/[^A-Z0-9]+/).filter(Boolean);

/** Layer-name words, in the order they are tried (the first that a token starts with wins). */
const NAME_RULES: readonly { readonly role: DrawingRole; readonly words: readonly string[] }[] = [
	// What is drawn on, around or across walls but is not one: hatches, dimensions, furniture,
	// the structure (the floor plan has it), services, annotation frames.
	{ role: 'ignore', words: ['HATCH', 'PATT', 'POCHE', 'DIM', 'FURN', 'FURNITURE', 'GRID', 'AXIS', 'COL', 'COLUMN', 'STRUC', 'STR', 'BEAM', 'SLAB', 'FOOT', 'ELEC', 'LIGHT', 'PLUMB', 'SANI', 'SAN', 'HVAC', 'MECH', 'TITLE', 'BORDER', 'FRAME', 'VPORT', 'VIEWPORT', 'DEFPOINTS', 'TREE', 'LAND', 'PLANT', 'CAR', 'PARK', 'FIXT', 'STAIR', 'LIFT', 'ELEV', 'LEVEL', 'SECT', 'SYMB', 'NORTH', 'CENTER', 'CENTRE', 'HIDDEN', 'OVERHEAD', 'OVHD'] },
	{ role: 'doors', words: ['DOOR', 'DOORS', 'DR', 'GATE', 'SHUTTER'] },
	{ role: 'windows', words: ['WINDOW', 'WINDOWS', 'WIN', 'WIND', 'WNDW', 'GLAZ', 'GLAZING', 'GLASS', 'VENT', 'VENTILATOR'] },
	{ role: 'walls', words: ['WALL', 'WALLS', 'WL', 'BRICK', 'BRK', 'MASONRY', 'PARTITION', 'PART', 'MAS'] },
	{ role: 'rooms', words: ['ROOM', 'ROOMS', 'RM', 'SPACE', 'IDEN', 'NAME', 'NAMES', 'TEXT', 'TXT', 'LABEL', 'TAG'] },
];

/** What a layer most likely holds, from its name (A-WALL, WALL, DOOR, A-GLAZ, TEXT, ROOM, ...) and what is on it. */
export function guessRole(layer: IDrawingLayer): DrawingRole {
	const words = tokens(layer.name);
	const counts = layer.counts;
	if (!layer.total || layer.name === '0' && !counts.lines && !counts.blocks) {
		return 'ignore';
	}
	for (const rule of NAME_RULES) {
		// The token itself (A-WALL, WALL-INT) or its start (WALLS, DOORS, GLAZING).
		if (words.some(word => rule.words.some(w => word === w || w.length >= 4 && word.startsWith(w)))) {
			return fits(rule.role, layer) ? rule.role : 'ignore';
		}
	}
	return 'ignore';
}

/** Whether the layer has what the role reads: lines for walls, blocks or arcs and lines for doors and windows, texts for rooms. */
function fits(role: DrawingRole, layer: IDrawingLayer): boolean {
	const c = layer.counts;
	switch (role) {
		case 'walls': return c.lines > 0;
		case 'doors': return c.blocks > 0 || c.arcs > 0;
		case 'windows': return c.blocks > 0 || c.lines > 0;
		case 'rooms': return c.texts > 0;
		default: return true;
	}
}

/** The imports of `arch` (those of `file` first, the latest first). */
export function importsOf(arch: IArchitecture | undefined, file?: string): IDrawingImportRecord[] {
	const list = (arch as { readonly imports?: unknown } | undefined)?.imports;
	const records = Array.isArray(list) ? (list as unknown[]).filter((r): r is IDrawingImportRecord => typeof r === 'object' && r !== null && typeof (r as IDrawingImportRecord).file === 'string' && typeof (r as IDrawingImportRecord).story === 'string') : [];
	const same = (r: IDrawingImportRecord) => file !== undefined && sameFile(r.file, file);
	return [...records.filter(same).reverse(), ...records.filter(r => !same(r)).reverse()];
}

export function sameFile(a: string, b: string): boolean {
	const norm = (x: string) => x.replace(/\\/g, '/').trim().toLowerCase();
	return norm(a) === norm(b);
}

/**
 * The role of each layer: as mapped when this file was imported before, else as another import of
 * this project mapped a layer of that name, else guessed. Also whether any came from memory.
 */
export function initialRoles(info: IDrawingInfo, arch: IArchitecture | undefined, file: string): { readonly roles: Map<string, DrawingRole>; readonly remembered: boolean } {
	const remembered = new Map<string, DrawingRole>();
	// Older imports first, so later ones (and this file's) win.
	for (const record of importsOf(arch, file).reverse()) {
		for (const [layer, role] of Object.entries(record.layers ?? {})) {
			if (DRAWING_ROLES.includes(role)) {
				remembered.set(layer, role);
			}
		}
	}
	const roles = new Map<string, DrawingRole>();
	let fromMemory = false;
	for (const layer of info.layers) {
		const known = remembered.get(layer.name);
		if (known) {
			fromMemory = true;
		}
		roles.set(layer.name, known ?? guessRole(layer));
	}
	return { roles, remembered: fromMemory };
}

/** The grid intersections of the floor plan (`A-1` at x of A, y of 1), the first the origin's. */
export function gridPoints(layout: unknown): { readonly label: string; readonly point: CadPoint }[] {
	const grids = (layout as { readonly grids?: { readonly x?: unknown; readonly y?: unknown } } | undefined)?.grids;
	const lines = (value: unknown) => (Array.isArray(value) ? value : []).filter((g): g is { label: string; position: number } => typeof g?.label === 'string' && typeof g?.position === 'number')
		.sort((a, b) => a.position - b.position);
	const xs = lines(grids?.x);
	const ys = lines(grids?.y);
	const points = xs.flatMap(x => ys.map(y => ({ label: `${x.label}-${y.label}`, point: [x.position, y.position] as CadPoint })));
	return points.length ? points : [{ label: '0, 0', point: [0, 0] }];
}

/** At most this many segments near a pick are intersected with each other. */
const MAX_NEAR_SEGMENTS = 300;

/**
 * Where a pick at `point` snaps on the preview: the nearest end or corner of the drawing's lines,
 * or crossing of two of them (grid lines crossing at a grid point), within `reach` (drawing units).
 */
export function snapPoint(info: IDrawingInfo, point: CadPoint, reach: number): CadPoint | undefined {
	let best: CadPoint | undefined;
	let distance = reach;
	const consider = (x: number, y: number) => {
		const d = Math.hypot(x - point[0], y - point[1]);
		if (d <= distance) {
			distance = d;
			best = [x, y];
		}
	};
	const near: [number, number, number, number][] = [];
	for (const shapes of Object.values(info.preview)) {
		for (const shape of shapes) {
			for (let i = 0; i + 1 < shape.length; i += 2) {
				consider(shape[i], shape[i + 1]);
				if (i + 3 < shape.length && near.length < MAX_NEAR_SEGMENTS) {
					const [ax, ay, bx, by] = [shape[i], shape[i + 1], shape[i + 2], shape[i + 3]];
					if (Math.min(ax, bx) - reach <= point[0] && point[0] <= Math.max(ax, bx) + reach && Math.min(ay, by) - reach <= point[1] && point[1] <= Math.max(ay, by) + reach) {
						near.push([ax, ay, bx, by]);
					}
				}
			}
		}
	}
	for (let i = 0; i < near.length; i++) {
		for (let j = i + 1; j < near.length; j++) {
			const [ax, ay, bx, by] = near[i];
			const [cx, cy, dx, dy] = near[j];
			const ux = bx - ax, uy = by - ay, vx = dx - cx, vy = dy - cy;
			const denom = ux * vy - uy * vx;
			if (Math.abs(denom) < 1e-12 * Math.hypot(ux, uy) * Math.hypot(vx, vy)) {
				continue;
			}
			const t = ((cx - ax) * vy - (cy - ay) * vx) / denom;
			const s = ((cx - ax) * uy - (cy - ay) * ux) / denom;
			if (t >= 0 && t <= 1 && s >= 0 && s <= 1) {
				consider(ax + ux * t, ay + uy * t);
			}
		}
	}
	return best;
}

/** The rotation [°] that turns the drawing's direction from `base` to `base2` onto the plan's from `at` to `at2`. */
export function alignedRotation(base: CadPoint, at: CadPoint, base2: CadPoint, at2: CadPoint): number {
	const drawn = Math.atan2(base2[1] - base[1], base2[0] - base[0]);
	const target = Math.atan2(at2[1] - at[1], at2[0] - at[0]);
	const degrees = (target - drawn) * 180 / Math.PI;
	return ((degrees + 180) % 360 + 360) % 360 - 180;
}

/** How many layers have each role. */
export function roleCounts(roles: ReadonlyMap<string, DrawingRole>, info: IDrawingInfo): { readonly [role in DrawingRole]: number } {
	const counts = { walls: 0, doors: 0, windows: 0, rooms: 0, ignore: 0 };
	for (const layer of info.layers) {
		if (layer.total) {
			counts[roles.get(layer.name) ?? 'ignore']++;
		}
	}
	return counts;
}
