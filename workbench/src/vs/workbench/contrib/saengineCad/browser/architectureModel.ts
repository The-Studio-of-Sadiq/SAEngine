/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEntitySpec, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { signedArea } from '../../../../platform/saengine/common/geometry.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { DEFAULT_ARCHITECTURE } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { distanceToSegment, insidePolygon } from './floorPlanDrawing.js';
import { ISnapSegment, snapSegments } from './floorPlanSnap.js';
import {
	drawComponents,
	drawInPlaceElements,
	drawMasses,
	IComponentInstance,
	IComponentType,
	IConceptualMass,
	IInPlaceElement,
	parseComponents,
	parseComponentTypes,
	parseInPlaceElements,
	parseMasses,
} from './architectureComponents.js';

export type { IComponentInstance, IComponentType, IConceptualMass, IInPlaceElement } from './architectureComponents.js';

/*
 * The architecture (`05 Floor Plan/architecture.json`, `saengine.library.architecture`): walls of
 * layered wall types, doors and windows hosted in them, rooms found from the walls around a
 * picked point, and room separators; curtain walls, roofs, ramps and railings (T46). Physical
 * only: it never stiffens the analysis. These are the
 * pure parts of its editor: reading the file, the geometry (centre lines, rooms), the drawing of
 * one story and the edits, each returning a new file value.
 */

export const ARCHITECTURE_SCHEMA_ID = 'saengine.architecture/1';
/** The file, beside the floor plan in `05 Floor Plan`. */
export const ARCHITECTURE_FILE = 'architecture.json';

export interface IWallLayer { readonly material: string; readonly thickness: number; readonly unitWeight: number }
export interface IWallType { readonly id: string; readonly name: string; readonly layers: readonly IWallLayer[]; readonly locationLine?: 'center' | 'left' | 'right' }
export type DoorStyle = 'single' | 'double' | 'sliding';
export type WindowStyle = 'fixed' | 'casement' | 'sliding';
export interface IDoorType {
	readonly id: string; readonly name: string; readonly style?: DoorStyle; readonly width: number; readonly height: number; readonly frame?: number;
	readonly leafCount?: number; readonly swing?: 'left' | 'right' | 'both' | 'none'; readonly sill?: number; readonly lintel?: number;
}
export interface IWindowType {
	readonly id: string; readonly name: string; readonly style?: WindowStyle; readonly width: number; readonly height: number; readonly sill?: number; readonly frame?: number;
	readonly leafCount?: number; readonly swing?: 'inward' | 'outward' | 'left' | 'right' | 'none'; readonly lintel?: number;
}
export interface IFinishType {
	readonly id: string; readonly name: string; readonly kind: 'floor' | 'wall' | 'ceiling'; readonly thickness: number; readonly unitWeight: number;
	/** A sunk slab's filling under the finish in wet rooms [mm], and its unit weight [kN/m³] (16 when not given). */
	readonly sunkFilling?: number; readonly sunkUnitWeight?: number;
}

export type GridLayout = 'fixedDistance' | 'fixedNumber' | 'maxSpacing' | 'none';
export interface ICurtainGridRule { readonly layout: GridLayout; readonly spacing?: number; readonly count?: number }
export type PanelKind = 'glazed' | 'solid' | 'door';
export interface ICurtainPanelType {
	readonly id: string; readonly name: string; readonly kind?: PanelKind; readonly material?: string;
	readonly thickness?: number; readonly unitWeight?: number; readonly weight?: number;
}
export interface ICurtainMullionType {
	readonly id: string; readonly name: string; readonly width?: number; readonly depth?: number;
	readonly wallThickness?: number; readonly material?: string; readonly unitWeight?: number; readonly weightPerMetre?: number;
}
export interface ICurtainPanelOverride { readonly segment?: number; readonly column: number; readonly row: number; readonly panelType: string }

/** A curtain wall type: glazing on a mullion grid (defaults as `CurtainWallType`'s). */
export interface ICurtainWallType {
	readonly id: string; readonly name: string;
	readonly glassThickness?: number; readonly glassUnitWeight?: number; readonly frameWeight?: number;
	readonly depth?: number; readonly mullionSpacing?: number; readonly transomSpacing?: number;
	readonly verticalGrid?: ICurtainGridRule; readonly horizontalGrid?: ICurtainGridRule;
	readonly panelType?: string; readonly verticalMullion?: string; readonly horizontalMullion?: string; readonly borderMullion?: string;
}
export type CeilingKind = 'gypsum' | 'grid' | 'plaster' | 'timber' | 'metal' | 'other';
/** A ceiling type (gypsum, acoustic grid tiles, etc.). */
export interface ICeilingType {
	readonly id: string; readonly name: string; readonly kind?: CeilingKind;
	readonly thickness?: number; readonly weight?: number; readonly gridX?: number; readonly gridY?: number;
}
export interface ICeilingOpening { readonly id?: string; readonly outline: readonly CadPoint[] }
/** A ceiling element hosted in a room or by closed plan outline. */
export interface ICeiling {
	readonly id: string; readonly type: string; readonly story: string; readonly height?: number;
	readonly room?: string; readonly outline?: readonly CadPoint[];
	readonly gridRotation?: number; readonly gridOrigin?: CadPoint; readonly openings?: readonly ICeilingOpening[];
}
/** A roof covering: its layers, top down. */
export interface IRoofType { readonly id: string; readonly name: string; readonly layers: readonly IWallLayer[] }
/** A guard or handrail: height [mm], weight [kN/m], drawn width and post spacing [mm]. */
export interface IRailingType { readonly id: string; readonly name: string; readonly height?: number; readonly weight?: number; readonly width?: number; readonly postSpacing?: number }

export interface IArchWall {
	readonly id: string;
	readonly type: string;
	readonly base: string;
	readonly top?: string;
	readonly height?: number;
	readonly baseOffset?: number;
	readonly path: readonly CadPoint[];
	readonly structuralRef?: string;
}
export interface IDoor { readonly id: string; readonly type: string; readonly wall: string; readonly offset: number; readonly flip?: boolean }
export interface IWindow { readonly id: string; readonly type: string; readonly wall: string; readonly offset: number; readonly sill?: number }
export interface IRoom {
	readonly id: string;
	readonly story: string;
	readonly point: CadPoint;
	readonly name: string;
	readonly number?: string;
	readonly occupancy?: string;
	readonly floorFinish?: string;
	readonly wallFinish?: string;
	readonly ceilingFinish?: string;
	readonly wet?: boolean;
}
export interface ISeparator { readonly id: string; readonly story: string; readonly start: CadPoint; readonly end: CadPoint }
/** A curtain wall: placed as a wall, of a curtain wall type, optionally with per-panel overrides. */
export interface ICurtainWall extends IArchWall { readonly panelOverrides?: readonly ICurtainPanelOverride[] }
/** A roof over a plan outline on a story: flat, drainage-sloped, single-pitch, or per-edge footprint / mansard. */
export interface IRoof {
	readonly id: string; readonly type: string; readonly story: string; readonly outline: readonly CadPoint[];
	readonly baseOffset?: number; readonly slope?: number; readonly direction?: number; readonly occupancy?: string;
	readonly edgeSlopes?: readonly (number | null)[];
	readonly overhang?: number; readonly edgeOverhangs?: readonly number[];
	readonly upperSlope?: number; readonly breakHeight?: number;
	readonly drainageSlope?: number; readonly thickness?: number;
}
/** A straight ramp built up on a floor from `start` (low end) to `end` (high end). */
export interface IRamp {
	readonly id: string; readonly story: string; readonly start: CadPoint; readonly end: CadPoint;
	readonly width?: number; readonly rise?: number; readonly finish?: string; readonly fillUnitWeight?: number; readonly occupancy?: string;
	/** What it serves, for the code pack's ramp checks (default walkway). */
	readonly kind?: RampKind;
	/** Traffic lanes of a vehicle ramp (1 or 2). */
	readonly lanes?: number;
	/** A vehicle ramp with transition slopes at both ends. */
	readonly transitions?: boolean;
}
/** What a ramp serves; the code pack keeps its ramp rules by these ids (saengine.library.architecture.RampKind). */
export type RampKind = 'walkway' | 'accessible' | 'exit' | 'vehicle' | 'parking';
export const RAMP_KINDS: readonly RampKind[] = ['walkway', 'accessible', 'exit', 'vehicle', 'parking'];
/** A railing along a path on a story. */
export interface IRailing { readonly id: string; readonly type: string; readonly base: string; readonly baseOffset?: number; readonly path: readonly CadPoint[] }

export interface IArchitecture {
	readonly schema: typeof ARCHITECTURE_SCHEMA_ID;
	readonly wallTypes: readonly IWallType[];
	readonly doorTypes: readonly IDoorType[];
	readonly windowTypes: readonly IWindowType[];
	readonly finishTypes: readonly IFinishType[];
	readonly walls: readonly IArchWall[];
	readonly doors: readonly IDoor[];
	readonly windows: readonly IWindow[];
	readonly rooms: readonly IRoom[];
	readonly separators: readonly ISeparator[];
	readonly curtainWallTypes: readonly ICurtainWallType[];
	readonly curtainPanelTypes: readonly ICurtainPanelType[];
	readonly curtainMullionTypes: readonly ICurtainMullionType[];
	readonly ceilingTypes: readonly ICeilingType[];
	readonly roofTypes: readonly IRoofType[];
	readonly railingTypes: readonly IRailingType[];
	readonly componentTypes?: readonly IComponentType[];
	readonly curtainWalls: readonly ICurtainWall[];
	readonly ceilings: readonly ICeiling[];
	readonly roofs: readonly IRoof[];
	readonly ramps: readonly IRamp[];
	readonly railings: readonly IRailing[];
	readonly components?: readonly IComponentInstance[];
	readonly masses?: readonly IConceptualMass[];
	readonly inPlaceElements?: readonly IInPlaceElement[];
}

/** The kinds of things drawn and picked, by their list in the file. */
export type ArchKind = 'walls' | 'doors' | 'windows' | 'rooms' | 'separators' | 'curtainWalls' | 'ceilings' | 'roofs' | 'ramps' | 'railings' | 'components' | 'masses' | 'inPlaceElements';

/** Every kind, in the order of the file. */
export const ARCH_KINDS: readonly ArchKind[] = ['walls', 'doors', 'windows', 'rooms', 'separators', 'curtainWalls', 'ceilings', 'roofs', 'ramps', 'railings', 'components', 'masses', 'inPlaceElements'];

export interface IArchRef { readonly kind: ArchKind; readonly id: string }

export type ArchitectureParse =
	| { readonly kind: 'ok'; readonly value: IArchitecture }
	| { readonly kind: 'error'; readonly message: string };

type Json = { readonly [key: string]: unknown };

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoint(value: unknown): value is CadPoint {
	return Array.isArray(value) && value.length === 2 && value.every(v => typeof v === 'number' && Number.isFinite(v));
}

/** The default types and no walls: the file of a project that has none yet. */
export function newArchitecture(): IArchitecture {
	const parsed = parseArchitecture(JSON.stringify(DEFAULT_ARCHITECTURE));
	if (parsed.kind !== 'ok') {
		throw new Error(parsed.message); // the generated defaults are always valid
	}
	return parsed.value;
}

/**
 * The architecture in `text`. Missing lists are empty, and items too malformed to draw are left
 * out (the backend's check names them); a file of another kind is an error.
 */
export function parseArchitecture(text: string): ArchitectureParse {
	let value: unknown;
	try {
		value = text.trim() ? JSON.parse(text) : { schema: ARCHITECTURE_SCHEMA_ID };
	} catch (error) {
		return { kind: 'error', message: localize('arch.badJson', "architecture.json is not valid JSON: {0}", String(error)) };
	}
	if (!isObject(value) || value.schema !== ARCHITECTURE_SCHEMA_ID) {
		return { kind: 'error', message: localize('arch.unexpected', "This file is not a SAEngine architecture file ({0}).", ARCHITECTURE_SCHEMA_ID) };
	}
	const list = <T>(key: string, valid: (item: Json) => boolean) => (Array.isArray(value[key]) ? (value[key] as unknown[]).filter(isObject).filter(valid) : []) as unknown as T[];
	const named = (item: Json) => typeof item.id === 'string';
	return {
		kind: 'ok',
		value: {
			...value as object,
			schema: ARCHITECTURE_SCHEMA_ID,
			wallTypes: list<IWallType>('wallTypes', t => named(t) && Array.isArray(t.layers)),
			doorTypes: list<IDoorType>('doorTypes', t => named(t) && typeof t.width === 'number' && typeof t.height === 'number'),
			windowTypes: list<IWindowType>('windowTypes', t => named(t) && typeof t.width === 'number' && typeof t.height === 'number'),
			finishTypes: list<IFinishType>('finishTypes', named),
			walls: list<IArchWall>('walls', w => named(w) && typeof w.type === 'string' && typeof w.base === 'string' && Array.isArray(w.path) && w.path.length >= 2 && w.path.every(isPoint)),
			doors: list<IDoor>('doors', d => named(d) && typeof d.wall === 'string' && typeof d.offset === 'number'),
			windows: list<IWindow>('windows', d => named(d) && typeof d.wall === 'string' && typeof d.offset === 'number'),
			rooms: list<IRoom>('rooms', r => named(r) && typeof r.story === 'string' && isPoint(r.point)),
			separators: list<ISeparator>('separators', s => named(s) && typeof s.story === 'string' && isPoint(s.start) && isPoint(s.end)),
			curtainWallTypes: list<ICurtainWallType>('curtainWallTypes', named),
			curtainPanelTypes: list<ICurtainPanelType>('curtainPanelTypes', named),
			curtainMullionTypes: list<ICurtainMullionType>('curtainMullionTypes', named),
			ceilingTypes: list<ICeilingType>('ceilingTypes', named),
			roofTypes: list<IRoofType>('roofTypes', t => named(t) && Array.isArray(t.layers)),
			railingTypes: list<IRailingType>('railingTypes', named),
			componentTypes: parseComponentTypes(value.componentTypes),
			curtainWalls: list<ICurtainWall>('curtainWalls', w => named(w) && typeof w.type === 'string' && typeof w.base === 'string' && Array.isArray(w.path) && w.path.length >= 2 && w.path.every(isPoint)),
			ceilings: list<ICeiling>('ceilings', c => named(c) && typeof c.type === 'string' && typeof c.story === 'string' && (typeof c.room === 'string' || (Array.isArray(c.outline) && c.outline.length >= 3 && c.outline.every(isPoint)))),
			roofs: list<IRoof>('roofs', r => named(r) && typeof r.type === 'string' && typeof r.story === 'string' && Array.isArray(r.outline) && r.outline.length >= 3 && r.outline.every(isPoint)),
			ramps: list<IRamp>('ramps', r => named(r) && typeof r.story === 'string' && isPoint(r.start) && isPoint(r.end)),
			railings: list<IRailing>('railings', r => named(r) && typeof r.type === 'string' && typeof r.base === 'string' && Array.isArray(r.path) && r.path.length >= 2 && r.path.every(isPoint)),
			components: parseComponents(value.components),
			masses: parseMasses(value.masses),
			inPlaceElements: parseInPlaceElements(value.inPlaceElements),
		},
	};
}

// ───────────────────────────── geometry ─────────────────────────────

const distance = (a: CadPoint, b: CadPoint) => Math.hypot(a[0] - b[0], a[1] - b[1]);

export function wallThickness(type: IWallType | undefined): number {
	return type ? type.layers.reduce((sum, layer) => sum + (Number(layer.thickness) || 0), 0) : 0;
}

/** Weight per wall area [kN/m²]. */
export function wallWeight(type: IWallType): number {
	return type.layers.reduce((sum, layer) => sum + layer.thickness / 1000 * layer.unitWeight, 0);
}

/** Across a curtain wall [mm]: its mullions' depth. */
export function curtainDepth(type: ICurtainWallType | undefined): number {
	return type?.depth ?? 150;
}

/** Grid division offsets [0 .. length] in mm for a curtain grid rule. */
export function gridDivisions(length: number, rule: ICurtainGridRule | undefined, fallbackSpacing = 1500): number[] {
	if (length <= 0) {
		return [0];
	}
	const layout: GridLayout = rule?.layout ?? 'fixedDistance';
	if (layout === 'none') {
		return [0, length];
	}
	if (layout === 'fixedNumber') {
		const n = Math.max(1, (rule?.count ?? 0) + 1);
		return Array.from({ length: n + 1 }, (_, k) => length * k / n);
	}
	if (layout === 'maxSpacing') {
		const step = rule?.spacing || fallbackSpacing;
		const n = Math.max(1, Math.ceil((length - 1e-6) / step));
		return Array.from({ length: n + 1 }, (_, k) => length * k / n);
	}
	const step = rule?.spacing || fallbackSpacing;
	const pts = [0];
	for (let pos = step; pos < length - 1e-6; pos += step) {
		pts.push(pos);
	}
	pts.push(length);
	return pts;
}

function panelAreaWeight(type: ICurtainPanelType): number {
	if (type.weight !== undefined) {
		return type.weight;
	}
	const density = type.unitWeight ?? (type.kind === 'glazed' || type.kind === undefined ? 25 : 20);
	return (type.thickness ?? 12) / 1000 * density;
}

function mullionLinearWeight(type: ICurtainMullionType): number {
	if (type.weightPerMetre !== undefined) {
		return type.weightPerMetre;
	}
	const w = type.width ?? 50;
	const d = type.depth ?? 150;
	const wt = type.wallThickness;
	const areaMm2 = wt !== undefined && 2 * wt < Math.min(w, d)
		? w * d - (w - 2 * wt) * (d - 2 * wt)
		: w * d;
	return areaMm2 / 1e6 * (type.unitWeight ?? 27);
}

/** A curtain wall's weight per m² [kN/m²]: panels + mullions when configured, else glass and frame. */
export function curtainWeight(type: ICurtainWallType, arch?: IArchitecture, wall?: ICurtainWall, height = 3000): number {
	const nominal = (type.glassThickness ?? 12) / 1000 * (type.glassUnitWeight ?? 25) + (type.frameWeight ?? 0.15);
	if (!arch || height <= 0) {
		return nominal;
	}
	const defaultPanel = type.panelType ? arch.curtainPanelTypes.find(p => p.id === type.panelType) : undefined;
	const vMullion = type.verticalMullion ? arch.curtainMullionTypes.find(m => m.id === type.verticalMullion) : undefined;
	const hMullion = type.horizontalMullion ? arch.curtainMullionTypes.find(m => m.id === type.horizontalMullion) : undefined;
	const bMullion = type.borderMullion ? arch.curtainMullionTypes.find(m => m.id === type.borderMullion) : undefined;
	const overrides = wall?.panelOverrides ?? [];
	const hasPanels = !!defaultPanel || overrides.length > 0;
	const hasMullions = !!(vMullion || hMullion || bMullion);
	if (!hasPanels && !hasMullions) {
		return nominal;
	}
	const path = wall?.path ?? [[0, 0], [3000, 0]];
	const zDivs = gridDivisions(height, type.horizontalGrid, type.transomSpacing ?? 1500);
	const rows = zDivs.length - 1;
	const fallbackPanelW = (type.glassThickness ?? 12) / 1000 * (type.glassUnitWeight ?? 25);
	let totalLen = 0;
	let panelsW = 0;
	let mullionsW = 0;
	for (let segIdx = 1; segIdx < path.length; segIdx++) {
		const segLen = distance(path[segIdx - 1], path[segIdx]);
		if (segLen <= 1e-6) {
			continue;
		}
		totalLen += segLen;
		const uDivs = gridDivisions(segLen, type.verticalGrid, type.mullionSpacing ?? 1500);
		for (let r = 0; r < rows; r++) {
			const cellH = zDivs[r + 1] - zDivs[r];
			for (let c = 0; c < uDivs.length - 1; c++) {
				const cellW = uDivs[c + 1] - uDivs[c];
				const ov = overrides.find(o => (o.segment ?? 0) === segIdx - 1 && o.column === c && o.row === r);
				const pType = (ov ? arch.curtainPanelTypes.find(p => p.id === ov.panelType) : undefined) ?? defaultPanel;
				panelsW += (cellW / 1000) * (cellH / 1000) * (pType ? panelAreaWeight(pType) : fallbackPanelW);
			}
		}
		if (hasMullions) {
			const startCol = segIdx === 1 ? 0 : 1;
			for (let k = startCol; k < uDivs.length; k++) {
				const isBorder = (segIdx === 1 && k === 0) || (segIdx === path.length - 1 && k === uDivs.length - 1);
				const mType = (isBorder && bMullion) ? bMullion : vMullion;
				if (mType) {
					mullionsW += (height / 1000) * mullionLinearWeight(mType);
				}
			}
			for (let r = 0; r < zDivs.length; r++) {
				const isBorder = r === 0 || r === zDivs.length - 1;
				const mType = (isBorder && bMullion) ? bMullion : hMullion;
				if (mType) {
					mullionsW += (segLen / 1000) * mullionLinearWeight(mType);
				}
			}
		}
	}
	const areaM2 = (totalLen / 1000) * (height / 1000);
	if (areaM2 <= 0) {
		return nominal;
	}
	if (!hasMullions) {
		mullionsW = (type.frameWeight ?? 0.15) * areaM2;
	}
	return (panelsW + mullionsW) / areaM2;
}

/** A roof's outer plan outline including uniform or per-edge overhangs [mm]. */
export function roofEffectiveOutline(roof: IRoof): CadPoint[] {
	const pts: CadPoint[] = roof.outline.length > 3 && distance(roof.outline[0], roof.outline[roof.outline.length - 1]) < 1e-6
		? [...roof.outline.slice(0, -1)]
		: [...roof.outline];
	const n = pts.length;
	if (n < 3) {
		return pts;
	}
	const overhangs = roof.edgeOverhangs && roof.edgeOverhangs.length === n
		? roof.edgeOverhangs
		: Array.from({ length: n }, () => roof.overhang ?? 0);
	if (!overhangs.some(oh => oh > 1e-9)) {
		return pts;
	}
	const ccw = signedArea(pts) >= 0;
	const oriented = ccw ? pts : [...pts].reverse();
	const ohAligned = ccw ? overhangs : [...overhangs].reverse();
	const lines = oriented.map((p, i) => {
		const q = oriented[(i + 1) % n];
		const len = distance(p, q) || 1;
		const [tx, ty] = [(q[0] - p[0]) / len, (q[1] - p[1]) / len];
		const [ox, oy] = [ty, -tx];
		const oh = ohAligned[i] ?? 0;
		return { p: [p[0] + ox * oh, p[1] + oy * oh] as CadPoint, t: [tx, ty] as CadPoint };
	});
	const out: CadPoint[] = [];
	for (let i = 0; i < n; i++) {
		const l1 = lines[(i - 1 + n) % n];
		const l2 = lines[i];
		const det = l1.t[0] * l2.t[1] - l1.t[1] * l2.t[0];
		if (Math.abs(det) <= 1e-9) {
			out.push(l2.p);
		} else {
			const s = ((l2.p[0] - l1.p[0]) * l2.t[1] - (l2.p[1] - l1.p[1]) * l2.t[0]) / det;
			out.push([l1.p[0] + l1.t[0] * s, l1.p[1] + l1.t[1] * s]);
		}
	}
	return out;
}

/** A roof covering's weight per m² of its surface [kN/m²], and its thickness [mm]. */
export function roofWeight(type: IRoofType): number {
	return wallWeight({ id: type.id, name: type.name, layers: type.layers });
}

/** The railing type's values with their defaults (as `RailingType`'s). */
export function railingOf(type: IRailingType | undefined): { readonly height: number; readonly weight: number; readonly width: number; readonly postSpacing: number } {
	return { height: type?.height ?? 1000, weight: type?.weight ?? 0.3, width: type?.width ?? 50, postSpacing: type?.postSpacing ?? 1200 };
}

/** A ramp's rise over its run (0.0833 is 1 in 12), as drawn; the code pack's ramp checks are the backend's (saengine.design.ramps). */
export function rampGradient(ramp: IRamp): number {
	const run = distance(ramp.start, ramp.end);
	return run ? (ramp.rise ?? 0) / run : 0;
}

/** A ramp's plan footprint: its centre line widened to both sides, counter-clockwise from the low end's right. */
export function rampOutline(ramp: IRamp): CadPoint[] {
	return wallOutline([ramp.start, ramp.end], ramp.width ?? 1500);
}

export function pathLength(points: readonly CadPoint[]): number {
	let length = 0;
	for (let i = 1; i < points.length; i++) {
		length += distance(points[i - 1], points[i]);
	}
	return length;
}

/**
 * `points` moved `d` to the left (seen along the path), with mitred corners; a closed path is
 * mitred where it closes too (as `saengine.library.architecture.offset_path`).
 */
export function offsetPath(points: readonly CadPoint[], d: number): CadPoint[] {
	if (!d) {
		return points.map(p => [p[0], p[1]] as CadPoint);
	}
	const normals: CadPoint[] = [];
	for (let i = 1; i < points.length; i++) {
		const [x1, y1] = points[i - 1];
		const [x2, y2] = points[i];
		const length = Math.hypot(x2 - x1, y2 - y1) || 1;
		normals.push([-(y2 - y1) / length, (x2 - x1) / length]);
	}
	const closed = points.length > 3 && distance(points[0], points[points.length - 1]) < 1e-6;
	return points.map(([x, y], i) => {
		const end = i === 0 || i === points.length - 1;
		if (end && !closed) {
			const [nx, ny] = i === 0 ? normals[0] : normals[normals.length - 1];
			return [x + nx * d, y + ny * d] as CadPoint;
		}
		const [ax, ay] = end ? normals[normals.length - 1] : normals[i - 1];
		const [bx, by] = end ? normals[0] : normals[i];
		const [mx, my] = [ax + bx, ay + by];
		const dot = mx * ax + my * ay;
		const scale = Math.abs(dot) > 1e-9 ? d / dot : d;
		return [x + mx * scale, y + my * scale] as CadPoint;
	});
}

/** The wall's centre line from its path (its type's location line). */
export function centreLine(wall: IArchWall, type: IWallType | undefined): CadPoint[] {
	const half = wallThickness(type) / 2;
	const shift = type?.locationLine === 'left' ? -half : type?.locationLine === 'right' ? half : 0;
	return offsetPath(wall.path, shift);
}

/** The wall's outline: its centre line offset to both faces, mitred. */
export function wallOutline(centre: readonly CadPoint[], thickness: number): CadPoint[] {
	return [...offsetPath(centre, thickness / 2), ...offsetPath(centre, -thickness / 2).reverse()];
}

/** The point `offset` along a polyline, and its direction there. */
export function pointAlong(points: readonly CadPoint[], offset: number): { readonly point: CadPoint; readonly direction: CadPoint } {
	let remaining = Math.max(0, offset);
	for (let i = 1; i < points.length; i++) {
		const [x1, y1] = points[i - 1];
		const [x2, y2] = points[i];
		const length = Math.hypot(x2 - x1, y2 - y1);
		if (remaining <= length || i === points.length - 1) {
			const t = length ? Math.min(remaining, length) / length : 0;
			return { point: [x1 + (x2 - x1) * t, y1 + (y2 - y1) * t], direction: length ? [(x2 - x1) / length, (y2 - y1) / length] : [1, 0] };
		}
		remaining -= length;
	}
	return { point: points[0], direction: [1, 0] };
}

/** The point of a polyline nearest `p`: its distance along the line, from `p`, and the direction there. */
export function projectOnto(points: readonly CadPoint[], p: CadPoint): { readonly offset: number; readonly distance: number; readonly direction: CadPoint } {
	let best = { offset: 0, distance: Infinity, direction: [1, 0] as CadPoint };
	let travelled = 0;
	for (let i = 1; i < points.length; i++) {
		const [x1, y1] = points[i - 1];
		const [x2, y2] = points[i];
		const length = Math.hypot(x2 - x1, y2 - y1);
		if (!length) {
			continue;
		}
		const [ux, uy] = [(x2 - x1) / length, (y2 - y1) / length];
		const t = Math.min(Math.max((p[0] - x1) * ux + (p[1] - y1) * uy, 0), length);
		const d = Math.hypot(x1 + ux * t - p[0], y1 + uy * t - p[1]);
		if (d < best.distance) {
			best = { offset: travelled + t, distance: d, direction: [ux, uy] };
		}
		travelled += length;
	}
	return best;
}

/** The wall's bottom and top [mm] on the floor plan's stories, or undefined (as `wall_levels`). */
export function wallLevels(wall: IArchWall, elevations: ReadonlyMap<string, number>): { readonly bottom: number; readonly top: number } | undefined {
	const base = elevations.get(wall.base);
	if (base === undefined) {
		return undefined;
	}
	const bottom = base + (wall.baseOffset ?? 0);
	if (wall.height !== undefined) {
		return { bottom, top: bottom + wall.height };
	}
	if (wall.top !== undefined) {
		const top = elevations.get(wall.top);
		return top === undefined ? undefined : { bottom, top };
	}
	const above = [...elevations.values()].filter(e => e > base).sort((a, b) => a - b);
	return above.length ? { bottom, top: above[0] } : undefined;
}

export function elevationsOf(layout: unknown): Map<string, number> {
	return new Map(storiesOf(layout).map(s => [s.id, s.elevation]));
}

/** The walls standing on `story` or rising through it, with their types and centre lines. */
export function wallsOnStory(arch: IArchitecture, story: string, elevations: ReadonlyMap<string, number>): { readonly wall: IArchWall; readonly type: IWallType | undefined; readonly centre: CadPoint[]; readonly thickness: number }[] {
	const level = elevations.get(story);
	if (level === undefined) {
		return [];
	}
	return arch.walls.flatMap(wall => {
		const levels = wallLevels(wall, elevations);
		const onStory = wall.base === story || (!!levels && levels.bottom - 1e-6 <= level && level < levels.top - 1e-6);
		if (!onStory) {
			return [];
		}
		const type = arch.wallTypes.find(t => t.id === wall.type);
		return [{ wall, type, centre: centreLine(wall, type), thickness: wallThickness(type) }];
	});
}

/** The curtain walls standing on `story` or rising through it, with their types and centre lines. */
export function curtainWallsOnStory(arch: IArchitecture, story: string, elevations: ReadonlyMap<string, number>): { readonly wall: ICurtainWall; readonly type: ICurtainWallType | undefined; readonly centre: CadPoint[]; readonly thickness: number }[] {
	const level = elevations.get(story);
	if (level === undefined) {
		return [];
	}
	return arch.curtainWalls.flatMap(wall => {
		const levels = wallLevels(wall, elevations);
		const onStory = wall.base === story || (!!levels && levels.bottom - 1e-6 <= level && level < levels.top - 1e-6);
		if (!onStory) {
			return [];
		}
		const type = arch.curtainWallTypes.find(t => t.id === wall.type);
		return [{ wall, type, centre: wall.path.map(([x, y]) => [x, y] as CadPoint), thickness: curtainDepth(type) }];
	});
}

/** Width, height and sill [mm] of a door (sill 0) or window, from its type. */
export function openingSize(arch: IArchitecture, kind: 'doors' | 'windows', opening: IDoor | IWindow): { readonly width: number; readonly height: number; readonly sill: number } | undefined {
	if (kind === 'doors') {
		const type = arch.doorTypes.find(t => t.id === opening.type);
		return type && { width: type.width, height: type.height, sill: 0 };
	}
	const type = arch.windowTypes.find(t => t.id === opening.type);
	const sill = (opening as IWindow).sill ?? type?.sill ?? 900;
	return type && { width: type.width, height: type.height, sill };
}

// ───────────────────────────── rooms ─────────────────────────────

/** How far a wall's centre line runs past its ends to meet the walls it is joined to [mm] (as `JOIN_REACH`). */
const JOIN_REACH = 1;

export interface IRoomOutline {
	/** The face of the wall centre lines and separators holding the point, counter-clockwise. */
	readonly gross: readonly CadPoint[];
	/** The same less half of each bounding wall: the room's floor. */
	readonly net: readonly CadPoint[];
	/** Net floor area [m²]. */
	readonly area: number;
}

interface IEdge { readonly a: number; readonly b: number; readonly half: number }

/**
 * The room around `point` on `story`, found as the backend finds it (`room_boundary`, with
 * shapely's polygonize): the wall centre lines (run a little past their ends, so walls joined at a
 * face still close) and the separators are split where they cross, dangling pieces dropped, and
 * the smallest face holding the point is the room. Undefined when the point is not enclosed.
 */
export function findRoom(arch: IArchitecture, story: string, point: CadPoint, elevations: ReadonlyMap<string, number>): IRoomOutline | undefined {
	// Curtain walls bound rooms as walls do (as `room_boundary`).
	const walls = [...wallsOnStory(arch, story, elevations), ...curtainWallsOnStory(arch, story, elevations)];
	const reach = Math.max(JOIN_REACH, ...walls.map(w => w.thickness / 2 + JOIN_REACH));
	const lines: { readonly start: CadPoint; readonly end: CadPoint; readonly half: number }[] = [];
	for (const { centre, thickness } of walls) {
		const run = extended(centre, reach);
		for (let i = 1; i < run.length; i++) {
			lines.push({ start: run[i - 1], end: run[i], half: thickness / 2 });
		}
	}
	for (const s of arch.separators) {
		if (s.story === story) {
			lines.push({ start: s.start, end: s.end, half: 0 });
		}
	}
	const { vertices, edges } = planarGraph(lines);
	const faces = boundedFaces(vertices, edges);
	let best: { readonly cycle: readonly number[]; readonly halves: readonly number[]; readonly area: number } | undefined;
	for (const face of faces) {
		const polygon = face.cycle.map(i => vertices[i]);
		if (insidePolygon(point, polygon) && (!best || face.area < best.area)) {
			best = face;
		}
	}
	if (!best) {
		return undefined;
	}
	const gross = best.cycle.map(i => vertices[i]);
	const net = insetPolygon(gross, best.halves);
	return { gross, net, area: Math.abs(signedArea(net)) / 1e6 };
}

function extended(points: readonly CadPoint[], reach: number): CadPoint[] {
	const past = (a: CadPoint, b: CadPoint): CadPoint => {
		const length = distance(a, b) || 1;
		return [b[0] + (b[0] - a[0]) / length * reach, b[1] + (b[1] - a[1]) / length * reach];
	};
	return [past(points[1], points[0]), ...points.slice(1, -1), past(points[points.length - 2], points[points.length - 1])];
}

/** The lines split where they cross or touch, as vertices and edges (each with its wall's half thickness). */
function planarGraph(lines: readonly { readonly start: CadPoint; readonly end: CadPoint; readonly half: number }[]): { vertices: CadPoint[]; edges: IEdge[] } {
	const vertices: CadPoint[] = [];
	const index = new Map<string, number>();
	const vertex = (p: CadPoint) => {
		const key = `${Math.round(p[0] * 2)}:${Math.round(p[1] * 2)}`; // 0.5 mm
		let i = index.get(key);
		if (i === undefined) {
			i = vertices.length;
			vertices.push(p);
			index.set(key, i);
		}
		return i;
	};
	const cuts = lines.map(() => [0, 1]);
	for (let i = 0; i < lines.length; i++) {
		for (let j = i + 1; j < lines.length; j++) {
			const hit = crossing(lines[i].start, lines[i].end, lines[j].start, lines[j].end);
			if (hit) {
				cuts[i].push(hit[0]);
				cuts[j].push(hit[1]);
			}
		}
	}
	const edges = new Map<string, IEdge>();
	lines.forEach((line, i) => {
		const ts = [...new Set(cuts[i])].sort((a, b) => a - b);
		const at = (t: number): CadPoint => [line.start[0] + (line.end[0] - line.start[0]) * t, line.start[1] + (line.end[1] - line.start[1]) * t];
		for (let k = 1; k < ts.length; k++) {
			const a = vertex(at(ts[k - 1]));
			const b = vertex(at(ts[k]));
			if (a === b) {
				continue;
			}
			const key = a < b ? `${a}:${b}` : `${b}:${a}`;
			const existing = edges.get(key);
			edges.set(key, { a: Math.min(a, b), b: Math.max(a, b), half: Math.max(existing?.half ?? 0, line.half) });
		}
	});
	return { vertices, edges: [...edges.values()] };
}

/** Where segments ab and cd meet: the parameters along each, or undefined (parallel or apart). */
function crossing(a: CadPoint, b: CadPoint, c: CadPoint, d: CadPoint): [number, number] | undefined {
	const [rx, ry] = [b[0] - a[0], b[1] - a[1]];
	const [sx, sy] = [d[0] - c[0], d[1] - c[1]];
	const denominator = rx * sy - ry * sx;
	if (Math.abs(denominator) < 1e-9) {
		return undefined;
	}
	const [qx, qy] = [c[0] - a[0], c[1] - a[1]];
	const t = (qx * sy - qy * sx) / denominator;
	const u = (qx * ry - qy * rx) / denominator;
	const eps = 1e-9;
	return t >= -eps && t <= 1 + eps && u >= -eps && u <= 1 + eps ? [Math.min(1, Math.max(0, t)), Math.min(1, Math.max(0, u))] : undefined;
}

/** The bounded faces of a planar graph, counter-clockwise, with each edge's half thickness. */
function boundedFaces(vertices: readonly CadPoint[], all: readonly IEdge[]): { cycle: number[]; halves: number[]; area: number }[] {
	// Dangling pieces (wall ends run past a join) bound nothing: drop them.
	let edges = [...all];
	for (; ;) {
		const degree = new Map<number, number>();
		edges.forEach(e => [e.a, e.b].forEach(v => degree.set(v, (degree.get(v) ?? 0) + 1)));
		const kept = edges.filter(e => (degree.get(e.a) ?? 0) > 1 && (degree.get(e.b) ?? 0) > 1);
		if (kept.length === edges.length) {
			break;
		}
		edges = kept;
	}
	const outgoing = new Map<number, { readonly to: number; readonly angle: number; readonly half: number }[]>();
	for (const e of edges) {
		for (const [from, to] of [[e.a, e.b], [e.b, e.a]]) {
			const angle = Math.atan2(vertices[to][1] - vertices[from][1], vertices[to][0] - vertices[from][0]);
			const list = outgoing.get(from) ?? [];
			list.push({ to, angle, half: e.half });
			outgoing.set(from, list);
		}
	}
	outgoing.forEach(list => list.sort((p, q) => p.angle - q.angle));
	const visited = new Set<string>();
	const faces: { cycle: number[]; halves: number[]; area: number }[] = [];
	for (const [start, list] of outgoing) {
		for (const first of list) {
			if (visited.has(`${start}>${first.to}`)) {
				continue;
			}
			const cycle: number[] = [];
			const halves: number[] = [];
			let [from, edge] = [start, first];
			for (let guard = 0; guard <= edges.length * 2; guard++) {
				const key = `${from}>${edge.to}`;
				if (visited.has(key)) {
					break;
				}
				visited.add(key);
				cycle.push(from);
				halves.push(edge.half);
				// Turn: the next edge clockwise from the way back (the face keeps to the left).
				const around = outgoing.get(edge.to)!;
				const back = around.findIndex(o => o.to === from);
				const next = around[(back - 1 + around.length) % around.length];
				[from, edge] = [edge.to, next];
			}
			const area = signedArea(cycle.map(i => vertices[i]));
			if (cycle.length >= 3 && area > 1e-6) {
				faces.push({ cycle, halves, area });
			}
		}
	}
	return faces;
}

/** A counter-clockwise polygon with edge `i` (from vertex i to i+1) moved in by `halves[i]`. */
export function insetPolygon(points: readonly CadPoint[], halves: readonly number[]): CadPoint[] {
	// Straight runs of one thickness are one edge.
	const corners: CadPoint[] = [];
	const insets: number[] = [];
	const n = points.length;
	for (let i = 0; i < n; i++) {
		const prev = points[(i - 1 + n) % n];
		const p = points[i];
		const next = points[(i + 1) % n];
		const cross = (p[0] - prev[0]) * (next[1] - p[1]) - (p[1] - prev[1]) * (next[0] - p[0]);
		if (Math.abs(cross) > 1e-6 * distance(prev, p) * distance(p, next) || halves[(i - 1 + n) % n] !== halves[i]) {
			corners.push(p);
			insets.push(halves[i]);
		}
	}
	const m = corners.length;
	const lines = corners.map((p, i) => {
		const q = corners[(i + 1) % m];
		const length = distance(p, q) || 1;
		const [nx, ny] = [-(q[1] - p[1]) / length, (q[0] - p[0]) / length]; // left: inside
		return { p: [p[0] + nx * insets[i], p[1] + ny * insets[i]] as CadPoint, d: [(q[0] - p[0]) / length, (q[1] - p[1]) / length] as CadPoint, n: [nx, ny] as CadPoint };
	});
	const result: CadPoint[] = [];
	for (let i = 0; i < m; i++) {
		const a = lines[(i - 1 + m) % m];
		const b = lines[i];
		const denominator = a.d[0] * b.d[1] - a.d[1] * b.d[0];
		if (Math.abs(denominator) < 1e-9) {
			// A step where walls of two thicknesses meet in line: both inset points.
			const corner = corners[i];
			const ia = insets[(i - 1 + m) % m];
			result.push([corner[0] + a.n[0] * ia, corner[1] + a.n[1] * ia], [corner[0] + b.n[0] * insets[i], corner[1] + b.n[1] * insets[i]]);
			continue;
		}
		const t = ((b.p[0] - a.p[0]) * b.d[1] - (b.p[1] - a.p[1]) * b.d[0]) / denominator;
		result.push([a.p[0] + a.d[0] * t, a.p[1] + a.d[1] * t]);
	}
	return result;
}

// ───────────────────────────── drawing ─────────────────────────────

/** Layer names follow the US National CAD Standard's architectural discipline. */
export const ARCH_LAYERS = {
	walls: 'A-WALL',
	doors: 'A-DOOR',
	windows: 'A-GLAZ',
	rooms: 'A-AREA',
	roomLabels: 'A-AREA-IDEN',
	separators: 'A-AREA-SEPR',
	curtainWalls: 'A-GLAZ-CWMG',
	ceilings: 'A-CLNG',
	roofs: 'A-ROOF',
	ramps: 'A-FLOR-LEVL',
	railings: 'A-FLOR-HRAL',
	components: 'A-FURN',
	masses: 'A-MASS',
	labels: 'A-ANNO-NOTE',
} as const;

export const ARCH_LAYER_SPECS: readonly CadLayerSpec[] = [
	{ name: ARCH_LAYERS.walls, color: 7, description: 'Walls' },
	{ name: ARCH_LAYERS.doors, color: 30, description: 'Doors' },
	{ name: ARCH_LAYERS.windows, color: 4, description: 'Windows' },
	{ name: ARCH_LAYERS.rooms, color: 8, linetype: 'DASHED', description: 'Room floors' },
	{ name: ARCH_LAYERS.roomLabels, color: 7, description: 'Room names, numbers and areas' },
	{ name: ARCH_LAYERS.separators, color: 6, linetype: 'DASHED', description: 'Room separators' },
	{ name: ARCH_LAYERS.curtainWalls, color: 4, description: 'Curtain walls and mullions' },
	{ name: ARCH_LAYERS.ceilings, color: 9, linetype: 'DASHED', description: 'Ceilings and tile grids' },
	{ name: ARCH_LAYERS.roofs, color: 3, linetype: 'DASHED', description: 'Roofs' },
	{ name: ARCH_LAYERS.ramps, color: 5, description: 'Ramps' },
	{ name: ARCH_LAYERS.railings, color: 1, description: 'Railings' },
	{ name: ARCH_LAYERS.components, color: 2, description: 'Furniture, casework and equipment' },
	{ name: ARCH_LAYERS.masses, color: 6, linetype: 'DASHED', description: 'Conceptual masses' },
	{ name: ARCH_LAYERS.labels, color: 7, description: 'Notes: roof slopes, ramp gradients' },
];

/** A drawn item's outline, for picking and highlighting. */
export interface IArchShape {
	readonly kind: ArchKind;
	readonly id: string;
	/** A closed outline (walls, openings, rooms) or a line (separators). */
	readonly points: readonly CadPoint[];
	readonly closed: boolean;
}

export interface IArchDrawing {
	readonly entities: CadEntitySpec[];
	readonly shapes: IArchShape[];
	/** Rooms on the story by id, with their outlines and net areas. */
	readonly rooms: ReadonlyMap<string, IRoomOutline>;
	/** Items that could not be drawn, and why. */
	readonly problems: string[];
}

const ROOM_TEXT = 250;
const SWING_STEPS = 12;
const DASH_SCALE = 60;

/** The architecture of `story` drawn for the plan: walls cut at their openings, doors with their swings, windows, rooms with their names and areas. */
export function architectureDrawing(arch: IArchitecture, story: string, elevations: ReadonlyMap<string, number>): IArchDrawing {
	const entities: CadEntitySpec[] = [];
	const shapes: IArchShape[] = [];
	const problems: string[] = [];
	const line = (layer: string, start: CadPoint, end: CadPoint) => entities.push({ kind: 'line', layer, start, end });
	const walls = wallsOnStory(arch, story, elevations);

	for (const { wall, type, centre, thickness } of walls) {
		if (!type || thickness <= 0) {
			problems.push(localize('arch.noWallType', "{0}: no wall type '{1}'", wall.id, wall.type));
			continue;
		}
		const gaps: [number, number][] = [];
		for (const kind of ['doors', 'windows'] as const) {
			for (const opening of arch[kind] as readonly (IDoor | IWindow)[]) {
				if (opening.wall !== wall.id) {
					continue;
				}
				const size = openingSize(arch, kind, opening);
				if (!size) {
					problems.push(localize('arch.noOpeningType', "{0}: no type '{1}'", opening.id, opening.type));
					continue;
				}
				gaps.push([opening.offset - size.width / 2, opening.offset + size.width / 2]);
				const drawn = openingDrawing(kind, opening, size.width, centre, thickness, arch);
				entities.push(...drawn.entities);
				shapes.push({ kind, id: opening.id, points: drawn.outline, closed: true });
			}
		}
		// The faces, broken at the openings, and the end caps.
		const left = offsetPath(centre, thickness / 2);
		const right = offsetPath(centre, -thickness / 2);
		let travelled = 0;
		for (let i = 1; i < centre.length; i++) {
			const length = distance(centre[i - 1], centre[i]);
			const pieces = solidPieces(travelled, travelled + length, gaps);
			for (const [s0, s1] of pieces) {
				const [t0, t1] = [(s0 - travelled) / length, (s1 - travelled) / length];
				for (const face of [left, right]) {
					const a = face[i - 1], b = face[i];
					line(ARCH_LAYERS.walls, [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0], [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1]);
				}
			}
			travelled += length;
		}
		const closedLoop = distance(wall.path[0], wall.path[wall.path.length - 1]) < 1;
		if (!closedLoop) {
			line(ARCH_LAYERS.walls, left[0], right[0]);
			line(ARCH_LAYERS.walls, left[left.length - 1], right[right.length - 1]);
		}
		shapes.push({ kind: 'walls', id: wall.id, points: wallOutline(centre, thickness), closed: true });
	}

	for (const s of arch.separators) {
		if (s.story === story) {
			entities.push({ kind: 'line', layer: ARCH_LAYERS.separators, start: s.start, end: s.end, linetypeScale: DASH_SCALE });
			shapes.push({ kind: 'separators', id: s.id, points: [s.start, s.end], closed: false });
		}
	}

	const rooms = new Map<string, IRoomOutline>();
	for (const room of arch.rooms) {
		if (room.story !== story) {
			continue;
		}
		const outline = findRoom(arch, story, room.point, elevations);
		const [x, y] = room.point;
		const title = room.number ? `${room.number} ${room.name}` : room.name;
		entities.push({ kind: 'text', layer: ARCH_LAYERS.roomLabels, position: [x, y + ROOM_TEXT * 0.8], height: ROOM_TEXT, text: title });
		if (!outline) {
			problems.push(localize('arch.roomOpen', "{0}: its point is not enclosed by walls or separators", room.id));
			entities.push({ kind: 'text', layer: ARCH_LAYERS.roomLabels, position: [x, y - ROOM_TEXT * 0.8], height: ROOM_TEXT * 0.8, text: localize('arch.roomOpenLabel', "(not enclosed)") });
			shapes.push({ kind: 'rooms', id: room.id, points: square(room.point, ROOM_TEXT * 2), closed: true });
			continue;
		}
		rooms.set(room.id, outline);
		entities.push({ kind: 'polyline', layer: ARCH_LAYERS.rooms, points: outline.net, closed: true, linetypeScale: DASH_SCALE });
		entities.push({ kind: 'text', layer: ARCH_LAYERS.roomLabels, position: [x, y - ROOM_TEXT * 0.8], height: ROOM_TEXT * 0.8, text: localize('arch.roomArea', "{0} m²", outline.area.toFixed(2)) });
		shapes.push({ kind: 'rooms', id: room.id, points: outline.net, closed: true });
	}

	extrasDrawing(arch, story, elevations, rooms, entities, shapes, problems);
	return { entities, shapes, rooms, problems };
}

/** Curtain walls (faces, glass line, mullions), ceilings (outline, grid), roofs (outline, overhang, slope labels), ramps and railings of `story`. */
function extrasDrawing(arch: IArchitecture, story: string, elevations: ReadonlyMap<string, number>, rooms: ReadonlyMap<string, IRoomOutline>, entities: CadEntitySpec[], shapes: IArchShape[], problems: string[]): void {
	const line = (layer: string, start: CadPoint, end: CadPoint) => entities.push({ kind: 'line', layer, start, end });
	const arrow = (layer: string, from: CadPoint, to: CadPoint) => {
		line(layer, from, to);
		const length = distance(from, to);
		if (length <= 0) {
			return;
		}
		const [dx, dy] = [(to[0] - from[0]) / length, (to[1] - from[1]) / length];
		const head = Math.min(300, length / 3);
		line(layer, to, [to[0] - head * (dx - dy * 0.5), to[1] - head * (dy + dx * 0.5)]);
		line(layer, to, [to[0] - head * (dx + dy * 0.5), to[1] - head * (dy - dx * 0.5)]);
	};
	// Marks every `spacing` along `points` (not at the ends): `mark(point, direction)`.
	const along = (points: readonly CadPoint[], spacing: number, mark: (p: CadPoint, d: CadPoint) => void) => {
		const total = pathLength(points);
		if (spacing <= 0 || total <= 0) {
			return;
		}
		for (let s = spacing; s < total - 1; s += spacing) {
			const { point, direction } = pointAlong(points, s);
			mark(point, direction);
		}
	};

	for (const { wall, type, centre, thickness } of curtainWallsOnStory(arch, story, elevations)) {
		if (!type) {
			problems.push(localize('arch.noCurtainType', "{0}: no curtain wall type '{1}'", wall.id, wall.type));
			continue;
		}
		const layer = ARCH_LAYERS.curtainWalls;
		const left = offsetPath(centre, thickness / 2);
		const right = offsetPath(centre, -thickness / 2);
		for (let i = 1; i < centre.length; i++) {
			line(layer, left[i - 1], left[i]);
			line(layer, right[i - 1], right[i]);
			line(layer, centre[i - 1], centre[i]);
		}
		line(layer, left[0], right[0]);
		line(layer, left[left.length - 1], right[right.length - 1]);
		const t = thickness / 2;
		for (let i = 1; i < centre.length; i++) {
			const [a, b] = [centre[i - 1], centre[i]];
			const segLen = distance(a, b);
			if (segLen <= 1e-6) {
				continue;
			}
			const [dx, dy] = [(b[0] - a[0]) / segLen, (b[1] - a[1]) / segLen];
			const divs = gridDivisions(segLen, type.verticalGrid, type.mullionSpacing ?? 1500);
			for (let k = 1; k < divs.length - 1; k++) {
				const u = divs[k];
				const [x, y] = [a[0] + dx * u, a[1] + dy * u];
				line(layer, [x - dy * t, y + dx * t], [x + dy * t, y - dx * t]);
			}
		}
		shapes.push({ kind: 'curtainWalls', id: wall.id, points: wallOutline(centre, thickness), closed: true });
	}

	for (const ceiling of arch.ceilings) {
		if (ceiling.story !== story) {
			continue;
		}
		const type = arch.ceilingTypes.find(t => t.id === ceiling.type);
		if (!type) {
			problems.push(localize('arch.noCeilingType', "{0}: no ceiling type '{1}'", ceiling.id, ceiling.type));
		}
		const poly = ceiling.room ? rooms.get(ceiling.room)?.net : ceiling.outline;
		if (!poly || poly.length < 3) {
			problems.push(localize('arch.noCeilingOutline', "{0}: host room is not enclosed or outline missing", ceiling.id));
			continue;
		}
		entities.push({ kind: 'polyline', layer: ARCH_LAYERS.ceilings, points: poly, closed: true, linetypeScale: DASH_SCALE });
		if (type?.gridX && type?.gridY) {
			drawCeilingGrid(entities, poly, type.gridX, type.gridY, ceiling.gridRotation ?? 0, ceiling.gridOrigin);
		}
		for (const op of ceiling.openings ?? []) {
			if (op.outline.length >= 3) {
				entities.push({ kind: 'polyline', layer: ARCH_LAYERS.ceilings, points: op.outline, closed: true });
				line(ARCH_LAYERS.ceilings, op.outline[0], op.outline[2]);
			}
		}
		const [cx, cy] = poly.reduce<CadPoint>((sum, p) => [sum[0] + p[0] / poly.length, sum[1] + p[1] / poly.length], [0, 0]);
		entities.push({ kind: 'text', layer: ARCH_LAYERS.labels, position: [cx, cy - ROOM_TEXT * 2.2], height: ROOM_TEXT * 0.7, text: localize('arch.ceilingLabel', "{0} {1} +{2}", ceiling.id, ceiling.type, Math.round(ceiling.height ?? 2700)) });
		shapes.push({ kind: 'ceilings', id: ceiling.id, points: poly, closed: true });
	}

	for (const roof of arch.roofs) {
		if (roof.story !== story) {
			continue;
		}
		const type = arch.roofTypes.find(t => t.id === roof.type);
		if (!type) {
			problems.push(localize('arch.noRoofType', "{0}: no roof type '{1}'", roof.id, roof.type));
		}
		const outer = roofEffectiveOutline(roof);
		entities.push({ kind: 'polyline', layer: ARCH_LAYERS.roofs, points: outer, closed: true, linetypeScale: DASH_SCALE });
		if ((roof.overhang ?? 0) > 0 || roof.edgeOverhangs?.some(oh => oh > 0)) {
			entities.push({ kind: 'polyline', layer: ARCH_LAYERS.roofs, points: roof.outline, closed: true, linetypeScale: DASH_SCALE * 0.5 });
		}
		const [cx, cy] = outer.reduce<CadPoint>((sum, p) => [sum[0] + p[0] / outer.length, sum[1] + p[1] / outer.length], [0, 0]);
		const edgeSlopes = roof.edgeSlopes;
		if (edgeSlopes && edgeSlopes.some(s => (s ?? 0) > 0)) {
			const ccw = signedArea(roof.outline) >= 0;
			const n = outer.length;
			for (let i = 0; i < n; i++) {
				const s = edgeSlopes[ccw ? i : n - 1 - i] ?? 0;
				const a = outer[i];
				const b = outer[(i + 1) % n];
				const mx = (a[0] + b[0]) / 2;
				const my = (a[1] + b[1]) / 2;
				if (s > 0) {
					const len = distance(a, b) || 1;
					const [nx, ny] = [-(b[1] - a[1]) / len, (b[0] - a[0]) / len];
					const tick = Math.min(400, len / 4);
					line(ARCH_LAYERS.labels, [mx, my], [mx + nx * tick, my + ny * tick]);
					entities.push({ kind: 'text', layer: ARCH_LAYERS.labels, position: [mx + nx * (tick + 120), my + ny * (tick + 120)], height: ROOM_TEXT * 0.65, text: `${s}°` });
				}
			}
			const maxS = Math.max(...edgeSlopes.map(s => s ?? 0));
			const label = roof.breakHeight
				? localize('arch.roofMansard', "{0} {1}, mansard", roof.id, roof.type)
				: localize('arch.roofFootprint', "{0} {1}, {2}° footprint", roof.id, roof.type, maxS);
			entities.push({ kind: 'text', layer: ARCH_LAYERS.labels, position: [cx, cy - ROOM_TEXT * 1.6], height: ROOM_TEXT * 0.8, text: label });
		} else {
			const slope = roof.slope ?? 0;
			const drainage = roof.drainageSlope ?? 0;
			const label = slope
				? localize('arch.roofPitched', "{0} {1}, {2}°", roof.id, roof.type, slope)
				: drainage > 0
					? localize('arch.roofDrainage', "{0} {1}, flat ({2}° fall)", roof.id, roof.type, drainage)
					: localize('arch.roofFlat', "{0} {1}, flat", roof.id, roof.type);
			entities.push({ kind: 'text', layer: ARCH_LAYERS.labels, position: [cx, cy - ROOM_TEXT * 1.6], height: ROOM_TEXT * 0.8, text: label });
			if (slope > 0 || drainage > 0) {
				// Rising towards `direction`: the arrow points uphill.
				const angle = (roof.direction ?? 90) * Math.PI / 180;
				const reach = 1000;
				arrow(ARCH_LAYERS.labels, [cx - Math.cos(angle) * reach, cy - Math.sin(angle) * reach], [cx + Math.cos(angle) * reach, cy + Math.sin(angle) * reach]);
			}
		}
		shapes.push({ kind: 'roofs', id: roof.id, points: outer, closed: true });
	}

	for (const ramp of arch.ramps) {
		if (ramp.story !== story) {
			continue;
		}
		const outline = rampOutline(ramp);
		entities.push({ kind: 'polyline', layer: ARCH_LAYERS.ramps, points: outline, closed: true });
		arrow(ARCH_LAYERS.ramps, ramp.start, ramp.end);
		const gradient = rampGradient(ramp);
		const [mx, my] = [(ramp.start[0] + ramp.end[0]) / 2, (ramp.start[1] + ramp.end[1]) / 2];
		entities.push({ kind: 'text', layer: ARCH_LAYERS.labels, position: [mx, my + ROOM_TEXT], height: ROOM_TEXT * 0.8, text: gradient > 0 ? localize('arch.rampUp', "UP 1 in {0}", (1 / gradient).toFixed(1)) : localize('arch.rampLevel', "Level ramp") });
		shapes.push({ kind: 'ramps', id: ramp.id, points: outline, closed: true });
	}

	for (const railing of arch.railings) {
		if (railing.base !== story) {
			continue;
		}
		const type = arch.railingTypes.find(t => t.id === railing.type);
		if (!type) {
			problems.push(localize('arch.noRailingType', "{0}: no railing type '{1}'", railing.id, railing.type));
		}
		const { width, postSpacing } = railingOf(type);
		entities.push({ kind: 'polyline', layer: ARCH_LAYERS.railings, points: railing.path, closed: false });
		const posts: CadPoint[] = [railing.path[0], railing.path[railing.path.length - 1]];
		along(railing.path, postSpacing, p => posts.push(p));
		for (const post of posts) {
			entities.push({ kind: 'polyline', layer: ARCH_LAYERS.railings, points: square(post, Math.max(width, 40) / 2), closed: true });
		}
		shapes.push({ kind: 'railings', id: railing.id, points: wallOutline(railing.path.map(([x, y]) => [x, y] as CadPoint), Math.max(width, 100)), closed: true });
	}

	drawComponents(arch, story, ARCH_LAYERS.components, ARCH_LAYERS.labels, entities, shapes, problems);
	drawInPlaceElements(arch, story, ARCH_LAYERS.components, ARCH_LAYERS.labels, entities, shapes);
	drawMasses(arch, ARCH_LAYERS.masses, ARCH_LAYERS.labels, entities, shapes);
}

function square([x, y]: CadPoint, r: number): CadPoint[] {
	return [[x - r, y - r], [x + r, y - r], [x + r, y + r], [x - r, y + r]];
}

/** The parts of [from, to] outside the gaps. */
function solidPieces(from: number, to: number, gaps: readonly (readonly [number, number])[]): [number, number][] {
	let pieces: [number, number][] = [[from, to]];
	for (const [g0, g1] of gaps) {
		pieces = pieces.flatMap(([a, b]): [number, number][] => {
			if (g1 <= a || g0 >= b) {
				return [[a, b]];
			}
			return ([[a, Math.max(a, g0)], [Math.min(b, g1), b]] as [number, number][]).filter(([p, q]) => q - p > 1e-6);
		});
	}
	return pieces;
}

/** A door (leaf and swing, or sliding panels) or window (frame and glass) in its wall, and its outline. */
function openingDrawing(kind: 'doors' | 'windows', opening: IDoor | IWindow, width: number, centre: readonly CadPoint[], thickness: number, arch: IArchitecture): { entities: CadEntitySpec[]; outline: CadPoint[] } {
	const { point: [cx, cy], direction: [dx, dy] } = pointAlong(centre, opening.offset);
	const [nx, ny] = [-dy, dx];
	const at = (u: number, v: number): CadPoint => [cx + dx * u + nx * v, cy + dy * u + ny * v];
	const half = width / 2;
	const t = thickness / 2;
	const layer = kind === 'doors' ? ARCH_LAYERS.doors : ARCH_LAYERS.windows;
	const entities: CadEntitySpec[] = [];
	const line = (a: CadPoint, b: CadPoint) => entities.push({ kind: 'line', layer, start: a, end: b });
	// Jambs across the wall.
	line(at(-half, -t), at(-half, t));
	line(at(half, -t), at(half, t));
	if (kind === 'windows') {
		const winType = arch.windowTypes.find(w => w.id === opening.type);
		const frame = Math.min(winType?.frame ?? 50, width / 4);
		const leaves = Math.max(1, winType?.leafCount ?? (winType?.style === 'sliding' ? 2 : 1));
		line(at(-half, -t), at(half, -t));
		line(at(-half, t), at(half, t));
		line(at(-half, 0), at(half, 0));
		if (frame > 0) {
			line(at(-half + frame, -t), at(-half + frame, t));
			line(at(half - frame, -t), at(half - frame, t));
		}
		for (let k = 1; k < leaves; k++) {
			const u = -half + width * k / leaves;
			line(at(u, -t * 0.6), at(u, t * 0.6));
		}
	} else {
		const doorType = arch.doorTypes.find(d => d.id === opening.type);
		const style = doorType?.style ?? 'single';
		const frame = Math.min(doorType?.frame ?? 50, width / 4);
		const leaves = Math.max(1, doorType?.leafCount ?? (style === 'double' || style === 'sliding' ? 2 : 1));
		const swing = doorType?.swing;
		if (frame > 0) {
			line(at(-half + frame, -t), at(-half + frame, t));
			line(at(half - frame, -t), at(half - frame, t));
		}
		const side = (opening as IDoor).flip ? -1 : 1;
		const leaf = (hinge: number, length: number, sense: number) => {
			// The open leaf at right angles to the wall, and its swing back to the jamb.
			const base = side * t;
			line(at(hinge, base), at(hinge, base + side * length));
			const points: CadPoint[] = [];
			for (let k = 0; k <= SWING_STEPS; k++) {
				const angle = k / SWING_STEPS * Math.PI / 2;
				points.push(at(hinge + sense * length * Math.sin(angle), base + side * length * Math.cos(angle)));
			}
			entities.push({ kind: 'polyline', layer, points, closed: false });
		};
		if (style === 'double' || (leaves >= 2 && style !== 'sliding')) {
			leaf(-half, half, 1);
			leaf(half, half, -1);
		} else if (style === 'sliding') {
			const step = width / Math.max(2, leaves);
			for (let k = 0; k < Math.max(2, leaves); k++) {
				const u0 = -half + k * step * 0.9;
				const u1 = Math.min(half, u0 + step * 1.1);
				const v = k % 2 === 0 ? t / 3 : -t / 3;
				line(at(u0, v), at(u1, v));
			}
		} else if (swing === 'right') {
			leaf(half, width, -1);
		} else {
			leaf(-half, width, 1);
		}
	}
	return { entities, outline: [at(-half, -t), at(half, -t), at(half, t), at(-half, t)] };
}

function drawCeilingGrid(entities: CadEntitySpec[], poly: readonly CadPoint[], gridX: number, gridY: number, rotation: number, origin?: CadPoint): void {
	if (gridX <= 0 || gridY <= 0 || poly.length < 3) {
		return;
	}
	const ox = origin ? origin[0] : Math.min(...poly.map(p => p[0]));
	const oy = origin ? origin[1] : Math.min(...poly.map(p => p[1]));
	const rad = rotation * Math.PI / 180;
	const [ux, uy] = [Math.cos(rad), Math.sin(rad)];
	const [vx, vy] = [-uy, ux];
	const us = poly.map(p => (p[0] - ox) * ux + (p[1] - oy) * uy);
	const vs = poly.map(p => (p[0] - ox) * vx + (p[1] - oy) * vy);
	const [uMin, uMax] = [Math.min(...us), Math.max(...us)];
	const [vMin, vMax] = [Math.min(...vs), Math.max(...vs)];
	const clip = (a: CadPoint, b: CadPoint) => {
		const ts: number[] = [];
		for (let i = 0; i < poly.length; i++) {
			const hit = crossing(a, b, poly[i], poly[(i + 1) % poly.length]);
			if (hit) {
				ts.push(hit[0]);
			}
		}
		ts.sort((x, y) => x - y);
		for (let k = 0; k + 1 < ts.length; k += 2) {
			if (ts[k + 1] - ts[k] > 1e-6) {
				entities.push({
					kind: 'line',
					layer: ARCH_LAYERS.ceilings,
					start: [a[0] + (b[0] - a[0]) * ts[k], a[1] + (b[1] - a[1]) * ts[k]],
					end: [a[0] + (b[0] - a[0]) * ts[k + 1], a[1] + (b[1] - a[1]) * ts[k + 1]],
				});
			}
		}
	};
	const k0 = Math.ceil(uMin / gridX);
	const k1 = Math.min(Math.floor(uMax / gridX), k0 + 80);
	for (let k = k0; k <= k1; k++) {
		const u = k * gridX;
		clip([ox + u * ux + (vMin - 10) * vx, oy + u * uy + (vMin - 10) * vy], [ox + u * ux + (vMax + 10) * vx, oy + u * uy + (vMax + 10) * vy]);
	}
	const j0 = Math.ceil(vMin / gridY);
	const j1 = Math.min(Math.floor(vMax / gridY), j0 + 80);
	for (let j = j0; j <= j1; j++) {
		const v = j * gridY;
		clip([ox + (uMin - 10) * ux + v * vx, oy + (uMin - 10) * uy + v * vy], [ox + (uMax + 10) * ux + v * vx, oy + (uMax + 10) * uy + v * vy]);
	}
}

/** The item of `shapes` at `point`: openings and components first, then walls, separators, rooms, ceilings, roofs, masses. */
export function pickItem(shapes: readonly IArchShape[], point: CadPoint, tolerance: number): IArchShape | undefined {
	for (const kind of ['doors', 'windows', 'components', 'inPlaceElements', 'railings', 'walls', 'curtainWalls', 'separators', 'ramps', 'rooms', 'ceilings', 'roofs', 'masses'] as const) {
		const hit = shapes.find(s => s.kind === kind && (s.closed ? insidePolygon(point, s.points) || nearOutline(s.points, point, tolerance) : distanceToSegment(point, s.points[0], s.points[1]) <= tolerance));
		if (hit) {
			return hit;
		}
	}
	return undefined;
}

function nearOutline(points: readonly CadPoint[], p: CadPoint, tolerance: number): boolean {
	return points.some((a, i) => distanceToSegment(p, a, points[(i + 1) % points.length]) <= tolerance);
}

/** The architecture's wall centre lines on `story` as snap segments (they snap as members do). */
export function wallSnapSegments(arch: IArchitecture, story: string, elevations: ReadonlyMap<string, number>): ISnapSegment[] {
	return wallsOnStory(arch, story, elevations).flatMap(({ wall, centre }) => centre.slice(1).map((end, i) => ({ id: wall.id, start: centre[i], end })));
}

/** The floor-plan beam or wall a straight wall from `start` to `end` stands on: one lying under all of it. */
export function structureUnder(layout: unknown, story: string, start: CadPoint, end: CadPoint): string | undefined {
	return snapSegments(layout, story).find(s => distanceToSegment(start, s.start, s.end) < 1 && distanceToSegment(end, s.start, s.end) < 1)?.id;
}

// ───────────────────────────── edits ─────────────────────────────

export type ArchEdit = { readonly ok: true; readonly value: IArchitecture; readonly id: string } | { readonly ok: false; readonly error: string };

const PREFIX: { readonly [kind in ArchKind]: string } = { walls: 'AW', doors: 'D', windows: 'W', rooms: 'R', separators: 'RS', curtainWalls: 'CW', ceilings: 'CL', roofs: 'RF', ramps: 'RP', railings: 'RL', components: 'C', masses: 'M', inPlaceElements: 'IP' };

/** The next free id of `kind`: AW1, AW2, ... (unique across all the items). */
export function nextId(arch: IArchitecture, kind: ArchKind): string {
	const used = new Set(ARCH_KINDS.flatMap(k => ((arch[k] ?? []) as readonly { readonly id: string }[]).map(i => i.id)));
	let n = 1;
	while (used.has(`${PREFIX[kind]}${n}`)) {
		n++;
	}
	return `${PREFIX[kind]}${n}`;
}

/**
 * A wall of `type` along `path` (its location line) standing on `story`. It rises to the next
 * story up; on the top story it is 3 m high (a parapet or roof structure: change its height).
 */
export function addWall(arch: IArchitecture, type: string, story: string, path: readonly CadPoint[], elevations: ReadonlyMap<string, number>, structuralRef?: string): ArchEdit {
	if (path.length < 2 || pathLength(path) <= 0) {
		return { ok: false, error: localize('arch.wallTooShort', "A wall needs two different points.") };
	}
	if (!arch.wallTypes.some(t => t.id === type)) {
		return { ok: false, error: localize('arch.noWallTypes', "There is no wall type '{0}'.", type) };
	}
	const level = elevations.get(story);
	const above = [...elevations.values()].some(e => level !== undefined && e > level);
	const id = nextId(arch, 'walls');
	const wall: IArchWall = {
		id, type, base: story,
		...(above ? {} : { height: 3000 }),
		path: path.map(([x, y]) => [Math.round(x), Math.round(y)] as CadPoint),
		...(structuralRef ? { structuralRef } : {}),
	};
	return { ok: true, value: { ...arch, walls: [...arch.walls, wall] }, id };
}

/**
 * A door or window of `type` in `wall` centred `offset` along it (rounded to 10 mm, kept inside
 * the wall). An error when it is wider than the wall or overlaps another opening.
 */
export function addOpening(arch: IArchitecture, kind: 'doors' | 'windows', type: string, wallId: string, offset: number): ArchEdit {
	const wall = arch.walls.find(w => w.id === wallId);
	const size = openingSize(arch, kind, { id: '', type, wall: wallId, offset: 0 });
	if (!wall || !size) {
		return { ok: false, error: localize('arch.noOpeningTypeFor', "There is no type '{0}' to place.", type) };
	}
	const length = pathLength(centreLine(wall, arch.wallTypes.find(t => t.id === wall.type)));
	if (size.width > length) {
		return { ok: false, error: localize('arch.openingTooWide', "{0} is {1} mm wide; wall {2} is {3} mm long.", type, size.width, wall.id, Math.round(length)) };
	}
	const at = Math.min(Math.max(Math.round(offset / 10) * 10, size.width / 2), length - size.width / 2);
	const overlap = (['doors', 'windows'] as const).flatMap(k => (arch[k] as readonly (IDoor | IWindow)[]).map(o => ({ o, k }))).find(({ o, k }) => {
		const other = o.wall === wallId && openingSize(arch, k, o);
		return other && Math.abs(o.offset - at) < (other.width + size.width) / 2 - 1e-6;
	});
	if (overlap) {
		return { ok: false, error: localize('arch.openingOverlaps', "It would overlap {0}.", overlap.o.id) };
	}
	const id = nextId(arch, kind);
	const opening = { id, type, wall: wallId, offset: at };
	return { ok: true, value: { ...arch, [kind]: [...arch[kind], opening] }, id };
}

/** A room around `point` on `story`; an error when the point is not enclosed or already in a room. */
export function addRoom(arch: IArchitecture, story: string, point: CadPoint, elevations: ReadonlyMap<string, number>, name?: string): ArchEdit {
	const outline = findRoom(arch, story, point, elevations);
	if (!outline) {
		return { ok: false, error: localize('arch.notEnclosed', "That point is not enclosed by walls or room separators: close the walls, or draw a room separator.") };
	}
	const taken = arch.rooms.find(r => r.story === story && insidePolygon(r.point, outline.gross));
	if (taken) {
		return { ok: false, error: localize('arch.roomTaken', "Room {0} is already there.", taken.number ? `${taken.number} ${taken.name}` : taken.name) };
	}
	const id = nextId(arch, 'rooms');
	const number = String(100 * (1 + Math.max(0, storyIndex(elevations, story))) + 1 + arch.rooms.filter(r => r.story === story).length);
	const room: IRoom = { id, story, point: [Math.round(point[0]), Math.round(point[1])], name: name ?? localize('arch.roomDefault', "Room"), number };
	return { ok: true, value: { ...arch, rooms: [...arch.rooms, room] }, id };
}

function storyIndex(elevations: ReadonlyMap<string, number>, story: string): number {
	return [...elevations.entries()].sort((a, b) => a[1] - b[1]).findIndex(([id]) => id === story) - 1;
}

export function addSeparator(arch: IArchitecture, story: string, start: CadPoint, end: CadPoint): ArchEdit {
	if (distance(start, end) <= 0) {
		return { ok: false, error: localize('arch.separatorTooShort', "A room separator needs two different points.") };
	}
	const id = nextId(arch, 'separators');
	const round = (p: CadPoint): CadPoint => [Math.round(p[0]), Math.round(p[1])];
	return { ok: true, value: { ...arch, separators: [...arch.separators, { id, story, start: round(start), end: round(end) }] }, id };
}

/** A curtain wall of `type` along `path` (its centre line) standing on `story`, rising as a wall does (`addWall`). */
export function addCurtainWall(arch: IArchitecture, type: string, story: string, path: readonly CadPoint[], elevations: ReadonlyMap<string, number>): ArchEdit {
	if (path.length < 2 || pathLength(path) <= 0) {
		return { ok: false, error: localize('arch.curtainTooShort', "A curtain wall needs two different points.") };
	}
	if (!arch.curtainWallTypes.some(t => t.id === type)) {
		return { ok: false, error: localize('arch.noCurtainTypes', "There is no curtain wall type '{0}'.", type) };
	}
	const level = elevations.get(story);
	const above = [...elevations.values()].some(e => level !== undefined && e > level);
	const id = nextId(arch, 'curtainWalls');
	const wall: ICurtainWall = { id, type, base: story, ...(above ? {} : { height: 3000 }), path: path.map(roundPoint) };
	return { ok: true, value: { ...arch, curtainWalls: [...arch.curtainWalls, wall] }, id };
}

/** A railing of `type` along `path` on `story`. */
export function addRailing(arch: IArchitecture, type: string, story: string, path: readonly CadPoint[]): ArchEdit {
	if (path.length < 2 || pathLength(path) <= 0) {
		return { ok: false, error: localize('arch.railingTooShort', "A railing needs two different points.") };
	}
	if (!arch.railingTypes.some(t => t.id === type)) {
		return { ok: false, error: localize('arch.noRailingTypes', "There is no railing type '{0}'.", type) };
	}
	const id = nextId(arch, 'railings');
	return { ok: true, value: { ...arch, railings: [...arch.railings, { id, type, base: story, path: path.map(roundPoint) }] }, id };
}

/** A flat roof of `type` over the plan `outline` (three or more points) on `story`. */
export function addRoof(arch: IArchitecture, type: string, story: string, outline: readonly CadPoint[]): ArchEdit {
	const points = outline.length > 3 && distance(outline[0], outline[outline.length - 1]) < 1 ? outline.slice(0, -1) : outline;
	if (points.length < 3 || Math.abs(signedArea(points)) <= 0) {
		return { ok: false, error: localize('arch.roofTooSmall', "A roof needs three or more corners around an area.") };
	}
	if (!arch.roofTypes.some(t => t.id === type)) {
		return { ok: false, error: localize('arch.noRoofTypes', "There is no roof type '{0}'.", type) };
	}
	const id = nextId(arch, 'roofs');
	return { ok: true, value: { ...arch, roofs: [...arch.roofs, { id, type, story, outline: points.map(roundPoint) }] }, id };
}

/** A ceiling of `type` hosted in `room` or over `outline` on `story` at `height` mm above level. */
export function addCeiling(arch: IArchitecture, type: string, story: string, target: string | readonly CadPoint[], height = 2700): ArchEdit {
	if (!arch.ceilingTypes.some(t => t.id === type)) {
		return { ok: false, error: localize('arch.noCeilingTypes', "There is no ceiling type '{0}'.", type) };
	}
	const id = nextId(arch, 'ceilings');
	if (typeof target === 'string') {
		const room = arch.rooms.find(r => r.id === target);
		if (!room) {
			return { ok: false, error: localize('arch.noRoomForCeiling', "Room '{0}' does not exist.", target) };
		}
		if (arch.ceilings.some(c => c.room === target)) {
			return { ok: false, error: localize('arch.roomHasCeiling', "Room {0} already has a ceiling.", target) };
		}
		return { ok: true, value: { ...arch, ceilings: [...arch.ceilings, { id, type, story: room.story, height: Math.round(height), room: target }] }, id };
	}
	const points = target.length > 3 && distance(target[0], target[target.length - 1]) < 1 ? target.slice(0, -1) : target;
	if (points.length < 3 || Math.abs(signedArea(points)) <= 0) {
		return { ok: false, error: localize('arch.ceilingTooSmall', "A ceiling needs a room or three or more corners around an area.") };
	}
	return { ok: true, value: { ...arch, ceilings: [...arch.ceilings, { id, type, story, height: Math.round(height), outline: points.map(roundPoint) }] }, id };
}

/** `arch` with fields of a type changed; `undefined` removes a field. */
export function updateType(
	arch: IArchitecture,
	key: 'wallTypes' | 'curtainWallTypes' | 'ceilingTypes' | 'roofTypes' | 'curtainPanelTypes' | 'curtainMullionTypes',
	id: string,
	change: { readonly [field: string]: unknown },
): IArchitecture {
	const items = (arch[key] as unknown as readonly Json[]).map(item => {
		if (item.id !== id) {
			return item;
		}
		const copy: { [field: string]: unknown } = { ...item };
		for (const [field, value] of Object.entries(change)) {
			if (value === undefined || value === '') {
				delete copy[field];
			} else {
				copy[field] = value;
			}
		}
		return copy;
	});
	return { ...arch, [key]: items };
}

/** A ramp 1500 mm wide on `story` from `start` (low end) to `end`, level until its rise is given. */
export function addRamp(arch: IArchitecture, story: string, start: CadPoint, end: CadPoint): ArchEdit {
	if (distance(start, end) <= 0) {
		return { ok: false, error: localize('arch.rampTooShort', "A ramp needs two different points: its low end and its high end.") };
	}
	const id = nextId(arch, 'ramps');
	return { ok: true, value: { ...arch, ramps: [...arch.ramps, { id, story, start: roundPoint(start), end: roundPoint(end), width: 1500, rise: 0 }] }, id };
}

const roundPoint = (p: CadPoint): CadPoint => [Math.round(p[0]), Math.round(p[1])];

/** `arch` without the item; a wall goes with its doors and windows. */
export function removeItem(arch: IArchitecture, ref: IArchRef): IArchitecture {
	const without = <T extends { readonly id: string }>(items: readonly T[] | undefined) => (items ?? []).filter(i => i.id !== ref.id);
	const next = { ...arch, [ref.kind]: without(arch[ref.kind] as readonly { readonly id: string }[] | undefined) };
	if (ref.kind === 'walls') {
		return { ...next, doors: arch.doors.filter(d => d.wall !== ref.id), windows: arch.windows.filter(w => w.wall !== ref.id) };
	}
	return next;
}

/** `arch` with fields of an item changed; `undefined` removes a field. */
export function updateItem(arch: IArchitecture, ref: IArchRef, change: { readonly [field: string]: unknown }): IArchitecture {
	const items = ((arch[ref.kind] ?? []) as unknown as readonly Json[]).map(item => {
		if (item.id !== ref.id) {
			return item;
		}
		const copy: { [field: string]: unknown } = { ...item };
		for (const [field, value] of Object.entries(change)) {
			if (value === undefined || value === '') {
				delete copy[field];
			} else {
				copy[field] = value;
			}
		}
		return copy;
	});
	return { ...arch, [ref.kind]: items };
}

export function itemOf(arch: IArchitecture, ref: IArchRef): Json | undefined {
	return ((arch[ref.kind] ?? []) as unknown as readonly Json[]).find(i => i.id === ref.id);
}

/** Counts of the story's items, for the status line. */
export function storyCounts(arch: IArchitecture, story: string, elevations: ReadonlyMap<string, number>): { readonly walls: number; readonly doors: number; readonly windows: number; readonly rooms: number } {
	const walls = new Set(wallsOnStory(arch, story, elevations).filter(w => w.wall.base === story).map(w => w.wall.id));
	return {
		walls: walls.size,
		doors: arch.doors.filter(d => walls.has(d.wall)).length,
		windows: arch.windows.filter(w => walls.has(w.wall)).length,
		rooms: arch.rooms.filter(r => r.story === story).length,
	};
}
