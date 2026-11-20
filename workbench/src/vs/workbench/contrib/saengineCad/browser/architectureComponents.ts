/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEntitySpec, CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { signedArea } from '../../../../platform/saengine/common/geometry.js';
import { insidePolygon } from './floorPlanDrawing.js';
import type { IArchShape, IArchitecture, ICeilingType, IRoomOutline } from './architectureModel.js';

export type ComponentCategory = 'furniture' | 'casework' | 'plumbingFixture' | 'equipment' | 'generic';
export type ComponentIfcClass = 'IfcFurniture' | 'IfcSanitaryTerminal' | 'IfcFlowTerminal' | 'IfcBuildingElementProxy';
export type ParameterValue = number | string | boolean;

export type ISymbolPrimitive =
	| { readonly kind: 'line'; readonly start: CadPoint; readonly end: CadPoint }
	| { readonly kind: 'rect'; readonly x?: number; readonly y?: number; readonly width: number; readonly depth: number }
	| { readonly kind: 'circle'; readonly center?: CadPoint; readonly radius: number }
	| { readonly kind: 'polyline'; readonly points: readonly CadPoint[]; readonly closed?: boolean };

export interface IComponentType {
	readonly id: string;
	readonly name: string;
	readonly category?: ComponentCategory;
	readonly width: number;
	readonly depth: number;
	readonly height: number;
	readonly weight?: number;
	readonly material?: string;
	readonly symbol2d?: readonly ISymbolPrimitive[];
	readonly representation3d?: 'box' | 'cylinder' | 'extrusion';
	readonly extrusionOutline?: readonly CadPoint[];
	readonly parameters?: { readonly [key: string]: ParameterValue };
	readonly ifcClass?: ComponentIfcClass;
	readonly ifcPredefinedType?: string;
}

export interface IComponentInstance {
	readonly id: string;
	readonly type: string;
	readonly story: string;
	readonly point: CadPoint;
	readonly rotation?: number;
	readonly mirrored?: boolean;
	readonly elevation?: number;
	readonly hostRoom?: string;
	readonly parameters?: { readonly [key: string]: ParameterValue };
}

export type MassKind = 'extrusion' | 'box' | 'cylinder' | 'loft';

export interface IConceptualMass {
	readonly id: string;
	readonly name?: string;
	readonly kind: MassKind;
	readonly baseElevation?: number;
	readonly height: number;
	readonly outline?: readonly CadPoint[];
	readonly origin?: CadPoint;
	readonly width?: number;
	readonly depth?: number;
	readonly rotation?: number;
	readonly center?: CadPoint;
	readonly radius?: number;
	readonly baseOutline?: readonly CadPoint[];
	readonly topOutline?: readonly CadPoint[];
	readonly floorHeight?: number;
	readonly use?: string;
}

export interface IInPlaceElement {
	readonly id: string;
	readonly name: string;
	readonly category?: ComponentCategory;
	readonly story: string;
	readonly geometry?: MassKind;
	readonly baseOffset?: number;
	readonly height: number;
	readonly outline?: readonly CadPoint[];
	readonly origin?: CadPoint;
	readonly width?: number;
	readonly depth?: number;
	readonly rotation?: number;
	readonly center?: CadPoint;
	readonly radius?: number;
	readonly baseOutline?: readonly CadPoint[];
	readonly topOutline?: readonly CadPoint[];
	readonly weight?: number;
	readonly material?: string;
	readonly hostRoom?: string;
	readonly parameters?: { readonly [key: string]: ParameterValue };
}

export const TYPES_LIBRARY_SCHEMA_ID = 'saengine.typesLibrary/1';

export type ArchTypeCategory = 'wall' | 'door' | 'window' | 'finish' | 'roof' | 'railing' | 'ceiling' | 'curtainWall' | 'component';

export const ARCH_TYPE_CATEGORIES: readonly ArchTypeCategory[] = [
	'wall', 'door', 'window', 'finish', 'roof', 'railing', 'ceiling', 'curtainWall', 'component',
];

export interface ITypesLibrary {
	readonly schema: typeof TYPES_LIBRARY_SCHEMA_ID;
	readonly name: string;
	readonly wallTypes?: readonly unknown[];
	readonly doorTypes?: readonly unknown[];
	readonly windowTypes?: readonly unknown[];
	readonly finishTypes?: readonly unknown[];
	readonly roofTypes?: readonly unknown[];
	readonly railingTypes?: readonly unknown[];
	readonly ceilingTypes?: readonly ICeilingType[];
	readonly curtainWallTypes?: readonly unknown[];
	readonly curtainPanelTypes?: readonly unknown[];
	readonly curtainMullionTypes?: readonly unknown[];
	readonly componentTypes?: readonly IComponentType[];
}

export interface IArchTypeEntry {
	readonly category: ArchTypeCategory;
	readonly id: string;
	readonly name: string;
	readonly usedBy: readonly string[];
	readonly data: Json;
}

type Json = { readonly [key: string]: unknown };

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoint(value: unknown): value is CadPoint {
	return Array.isArray(value) && value.length === 2 && value.every(v => typeof v === 'number' && Number.isFinite(v));
}

export function parseComponentTypes(raw: unknown): IComponentType[] {
	if (!Array.isArray(raw)) {
		return [];
	}
	return raw.filter((item): item is IComponentType =>
		isObject(item) && typeof item.id === 'string' && typeof item.name === 'string'
		&& typeof item.width === 'number' && typeof item.depth === 'number' && typeof item.height === 'number',
	);
}

export function parseComponents(raw: unknown): IComponentInstance[] {
	if (!Array.isArray(raw)) {
		return [];
	}
	return raw.filter((item): item is IComponentInstance =>
		isObject(item) && typeof item.id === 'string' && typeof item.type === 'string'
		&& typeof item.story === 'string' && isPoint(item.point),
	);
}

export function parseMasses(raw: unknown): IConceptualMass[] {
	if (!Array.isArray(raw)) {
		return [];
	}
	return raw.filter((item): item is IConceptualMass =>
		isObject(item) && typeof item.id === 'string' && typeof item.kind === 'string' && typeof item.height === 'number',
	);
}

export function parseInPlaceElements(raw: unknown): IInPlaceElement[] {
	if (!Array.isArray(raw)) {
		return [];
	}
	return raw.filter((item): item is IInPlaceElement =>
		isObject(item) && typeof item.id === 'string' && typeof item.name === 'string'
		&& typeof item.story === 'string' && typeof item.height === 'number',
	);
}

// ───────────────────────────── geometry & drawing ─────────────────────────────

export function transformPoint(local: CadPoint, origin: CadPoint, rotation = 0, mirrored = false): CadPoint {
	const lx = mirrored ? -local[0] : local[0];
	const ly = local[1];
	const rad = rotation * Math.PI / 180;
	const c = Math.cos(rad);
	const s = Math.sin(rad);
	return [origin[0] + lx * c - ly * s, origin[1] + lx * s + ly * c];
}

export function componentOutline(comp: Pick<IComponentInstance, 'point' | 'rotation' | 'mirrored'>, type: Pick<IComponentType, 'width' | 'depth'>): CadPoint[] {
	const hw = type.width / 2;
	const hd = type.depth / 2;
	const rot = comp.rotation ?? 0;
	const mir = !!comp.mirrored;
	const corners: readonly CadPoint[] = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]];
	return corners.map(p => transformPoint(p, comp.point, rot, mir));
}

export function drawComponentSymbol(
	comp: Pick<IComponentInstance, 'point' | 'rotation' | 'mirrored'>,
	type: IComponentType,
	layer: string,
	entities: CadEntitySpec[],
): void {
	const rot = comp.rotation ?? 0;
	const mir = !!comp.mirrored;
	const toWorld = (p: CadPoint) => transformPoint(p, comp.point, rot, mir);
	const symbol = type.symbol2d;
	if (!symbol || !symbol.length) {
		const box = componentOutline(comp, type);
		entities.push({ kind: 'polyline', layer, points: box, closed: true });
		entities.push({ kind: 'line', layer, start: box[0], end: box[2] });
		return;
	}
	for (const prim of symbol) {
		switch (prim.kind) {
			case 'line':
				entities.push({ kind: 'line', layer, start: toWorld(prim.start), end: toWorld(prim.end) });
				break;
			case 'rect': {
				const cx = prim.x ?? 0;
				const cy = prim.y ?? 0;
				const hw = prim.width / 2;
				const hd = prim.depth / 2;
				const pts = [
					toWorld([cx - hw, cy - hd]),
					toWorld([cx + hw, cy - hd]),
					toWorld([cx + hw, cy + hd]),
					toWorld([cx - hw, cy + hd]),
				];
				entities.push({ kind: 'polyline', layer, points: pts, closed: true });
				break;
			}
			case 'circle': {
				const [cx, cy] = prim.center ?? [0, 0];
				const steps = 20;
				const pts: CadPoint[] = [];
				for (let k = 0; k < steps; k++) {
					const a = 2 * Math.PI * k / steps;
					pts.push(toWorld([cx + prim.radius * Math.cos(a), cy + prim.radius * Math.sin(a)]));
				}
				entities.push({ kind: 'polyline', layer, points: pts, closed: true });
				break;
			}
			case 'polyline':
				entities.push({ kind: 'polyline', layer, points: prim.points.map(toWorld), closed: !!prim.closed });
				break;
		}
	}
}

export function drawComponents(
	arch: IArchitecture,
	story: string,
	layer: string,
	labelLayer: string,
	entities: CadEntitySpec[],
	shapes: IArchShape[],
	problems: string[],
): void {
	for (const comp of arch.components ?? []) {
		if (comp.story !== story) {
			continue;
		}
		const type = (arch.componentTypes ?? []).find(t => t.id === comp.type);
		if (!type) {
			problems.push(localize('arch.noComponentType', "{0}: no component type '{1}'", comp.id, comp.type));
			continue;
		}
		drawComponentSymbol(comp, type, layer, entities);
		entities.push({ kind: 'text', layer: labelLayer, position: [comp.point[0], comp.point[1]], height: 140, text: comp.id });
		shapes.push({ kind: 'components', id: comp.id, points: componentOutline(comp, type), closed: true });
	}
}

export function massOutline(mass: Pick<IConceptualMass, 'kind' | 'outline' | 'origin' | 'width' | 'depth' | 'rotation' | 'center' | 'radius' | 'baseOutline'>): CadPoint[] {
	if (mass.kind === 'extrusion') {
		return [...(mass.outline ?? [])];
	}
	if (mass.kind === 'box') {
		const ox = mass.origin?.[0] ?? 0;
		const oy = mass.origin?.[1] ?? 0;
		const hw = (mass.width ?? 1000) / 2;
		const hd = (mass.depth ?? 1000) / 2;
		const rot = mass.rotation ?? 0;
		const corners: readonly CadPoint[] = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]];
		return corners.map(p => transformPoint(p, [ox, oy], rot, false));
	}
	if (mass.kind === 'cylinder') {
		const [cx, cy] = mass.center ?? [0, 0];
		const r = mass.radius ?? 500;
		const pts: CadPoint[] = [];
		for (let k = 0; k < 32; k++) {
			const a = 2 * Math.PI * k / 32;
			pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
		}
		return pts;
	}
	return [...(mass.baseOutline ?? [])];
}

function cleanRing(points: readonly CadPoint[]): CadPoint[] {
	if (points.length > 1 && Math.hypot(points[0][0] - points[points.length - 1][0], points[0][1] - points[points.length - 1][1]) < 1e-6) {
		return points.slice(0, -1);
	}
	return [...points];
}

function ensureCcw(points: readonly CadPoint[]): CadPoint[] {
	const ring = cleanRing(points);
	return signedArea(ring) < 0 ? [...ring].reverse() : ring;
}

function resampleRing(ring: readonly CadPoint[], n: number): CadPoint[] {
	if (ring.length === n || ring.length < 3) {
		return [...ring];
	}
	const dists = [0];
	for (let i = 0; i < ring.length; i++) {
		const a = ring[i];
		const b = ring[(i + 1) % ring.length];
		dists.push(dists[dists.length - 1] + Math.hypot(b[0] - a[0], b[1] - a[1]));
	}
	const total = dists[dists.length - 1] || 1;
	const out: CadPoint[] = [];
	for (let k = 0; k < n; k++) {
		const s = (k / n) * total;
		let idx = 0;
		while (idx < ring.length - 1 && dists[idx + 1] < s) {
			idx++;
		}
		const a = ring[idx];
		const b = ring[(idx + 1) % ring.length];
		const seg = dists[idx + 1] - dists[idx];
		const t = seg > 1e-9 ? (s - dists[idx]) / seg : 0;
		out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
	}
	return out;
}

function alignLoftRings(baseIn: readonly CadPoint[], topIn: readonly CadPoint[]): { base: CadPoint[]; top: CadPoint[] } {
	let base = ensureCcw(baseIn);
	let top = ensureCcw(topIn);
	if (base.length !== top.length) {
		const n = Math.max(base.length, top.length);
		base = resampleRing(base, n);
		top = resampleRing(top, n);
	}
	const n = base.length;
	let bestShift = 0;
	let bestCost = Infinity;
	for (let shift = 0; shift < n; shift++) {
		let cost = 0;
		for (let i = 0; i < n; i++) {
			const b = base[i];
			const t = top[(i + shift) % n];
			cost += (b[0] - t[0]) ** 2 + (b[1] - t[1]) ** 2;
		}
		if (cost < bestCost) {
			bestCost = cost;
			bestShift = shift;
		}
	}
	return { base, top: base.map((_, i) => top[(i + bestShift) % n]) };
}

export function massSectionAreaM2(mass: IConceptualMass, elevation: number): number {
	const base = mass.baseElevation ?? 0;
	if (elevation < base - 1e-6 || elevation > base + mass.height + 1e-6) {
		return 0;
	}
	if (mass.kind === 'box') {
		return (mass.width ?? 0) * (mass.depth ?? 0) / 1e6;
	}
	if (mass.kind === 'cylinder') {
		return Math.PI * (mass.radius ?? 0) ** 2 / 1e6;
	}
	if (mass.kind === 'extrusion') {
		return Math.abs(signedArea(mass.outline ?? [])) / 1e6;
	}
	if (!mass.baseOutline || !mass.topOutline || mass.baseOutline.length < 3 || mass.topOutline.length < 3) {
		return 0;
	}
	const { base: b, top } = alignLoftRings(mass.baseOutline, mass.topOutline);
	const t = Math.min(Math.max((elevation - base) / mass.height, 0), 1);
	const mid = b.map((p, i): CadPoint => [p[0] * (1 - t) + top[i][0] * t, p[1] * (1 - t) + top[i][1] * t]);
	return Math.abs(signedArea(mid)) / 1e6;
}

/** Volume [m³] of `mass` (exact prismoid formula h/6·(A1 + 4·Am + A2) for lofts). */
export function massVolumeM3(mass: IConceptualMass): number {
	const base = mass.baseElevation ?? 0;
	const hM = mass.height / 1000;
	if (mass.kind === 'loft') {
		const a1 = massSectionAreaM2(mass, base);
		const am = massSectionAreaM2(mass, base + mass.height / 2);
		const a2 = massSectionAreaM2(mass, base + mass.height);
		return (hM / 6) * (a1 + 4 * am + a2);
	}
	return massSectionAreaM2(mass, base) * hM;
}

export function massFloorAreaSummary(mass: IConceptualMass): { readonly floorCount: number; readonly grossFloorArea: number; readonly volume: number } {
	const base = mass.baseElevation ?? 0;
	const step = mass.floorHeight;
	let floorCount = 1;
	let grossFloorArea = massSectionAreaM2(mass, base);
	if (step && step > 0) {
		floorCount = 0;
		grossFloorArea = 0;
		for (let k = 0; ; k++) {
			const z = base + k * step;
			if (z >= base + mass.height - 1e-6) {
				break;
			}
			floorCount++;
			grossFloorArea += massSectionAreaM2(mass, z);
		}
	}
	return { floorCount, grossFloorArea, volume: massVolumeM3(mass) };
}

export function drawMasses(
	arch: IArchitecture,
	layer: string,
	labelLayer: string,
	entities: CadEntitySpec[],
	shapes: IArchShape[],
): void {
	for (const mass of arch.masses ?? []) {
		const outline = massOutline(mass);
		if (outline.length < 3) {
			continue;
		}
		entities.push({ kind: 'polyline', layer, points: outline, closed: true, linetypeScale: 60 });
		const [cx, cy] = outline.reduce<CadPoint>((s, p) => [s[0] + p[0] / outline.length, s[1] + p[1] / outline.length], [0, 0]);
		const info = massFloorAreaSummary(mass);
		entities.push({
			kind: 'text',
			layer: labelLayer,
			position: [cx, cy],
			height: 220,
			text: localize('arch.massLabel', "{0} ({1} m², {2} fl)", mass.name || mass.id, info.grossFloorArea.toFixed(1), info.floorCount),
		});
		shapes.push({ kind: 'masses', id: mass.id, points: outline, closed: true });
	}
}

export function drawInPlaceElements(
	arch: IArchitecture,
	story: string,
	layer: string,
	labelLayer: string,
	entities: CadEntitySpec[],
	shapes: IArchShape[],
): void {
	for (const elem of arch.inPlaceElements ?? []) {
		if (elem.story !== story) {
			continue;
		}
		const outline = massOutline({
			kind: elem.geometry ?? 'extrusion',
			outline: elem.outline,
			origin: elem.origin,
			width: elem.width,
			depth: elem.depth,
			rotation: elem.rotation,
			center: elem.center,
			radius: elem.radius,
			baseOutline: elem.baseOutline,
		});
		if (outline.length < 3) {
			continue;
		}
		entities.push({ kind: 'polyline', layer, points: outline, closed: true });
		const [cx, cy] = outline.reduce<CadPoint>((s, p) => [s[0] + p[0] / outline.length, s[1] + p[1] / outline.length], [0, 0]);
		entities.push({ kind: 'text', layer: labelLayer, position: [cx, cy], height: 150, text: elem.id });
		shapes.push({ kind: 'inPlaceElements', id: elem.id, points: outline, closed: true });
	}
}

// ───────────────────────────── component & mass edits ─────────────────────────────

export type CompEdit = { readonly ok: true; readonly value: IArchitecture; readonly id: string } | { readonly ok: false; readonly error: string };

export function detectHostRoomId(point: CadPoint, rooms: ReadonlyMap<string, IRoomOutline>): string | undefined {
	for (const [id, outline] of rooms) {
		if (insidePolygon(point, outline.net) || insidePolygon(point, outline.gross)) {
			return id;
		}
	}
	return undefined;
}

export function addComponent(
	arch: IArchitecture,
	typeId: string,
	story: string,
	point: CadPoint,
	id: string,
	rooms?: ReadonlyMap<string, IRoomOutline>,
	rotation = 0,
	mirrored = false,
): CompEdit {
	if (!(arch.componentTypes ?? []).some(t => t.id === typeId)) {
		return { ok: false, error: localize('arch.noComponentTypeToPlace', "There is no component type '{0}'.", typeId) };
	}
	const pt: CadPoint = [Math.round(point[0]), Math.round(point[1])];
	const hostRoom = rooms ? detectHostRoomId(pt, rooms) : undefined;
	const comp: IComponentInstance = {
		id,
		type: typeId,
		story,
		point: pt,
		...(rotation ? { rotation } : {}),
		...(mirrored ? { mirrored: true } : {}),
		...(hostRoom ? { hostRoom } : {}),
	};
	return { ok: true, value: { ...arch, components: [...(arch.components ?? []), comp] }, id };
}

export function mirrorComponent(
	arch: IArchitecture,
	componentId: string,
	axisStart: CadPoint,
	axisEnd: CadPoint,
	nextId?: string,
	rooms?: ReadonlyMap<string, IRoomOutline>,
): CompEdit {
	const dx = axisEnd[0] - axisStart[0];
	const dy = axisEnd[1] - axisStart[1];
	const lenSq = dx * dx + dy * dy;
	if (lenSq <= 1e-9) {
		return { ok: false, error: localize('arch.mirrorAxisInvalid', "Mirror axis needs two different points.") };
	}
	const source = (arch.components ?? []).find(c => c.id === componentId);
	if (!source) {
		return { ok: false, error: localize('arch.noComponentFound', "Component '{0}' not found.", componentId) };
	}
	const px = source.point[0] - axisStart[0];
	const py = source.point[1] - axisStart[1];
	const dot = (px * dx + py * dy) / lenSq;
	const projX = axisStart[0] + dot * dx;
	const projY = axisStart[1] + dot * dy;
	const pt: CadPoint = [Math.round(2 * projX - source.point[0]), Math.round(2 * projY - source.point[1])];
	const axisDeg = Math.atan2(dy, dx) * 180 / Math.PI;
	const rot = ((2 * axisDeg - (source.rotation ?? 0)) % 360 + 360) % 360;
	const hostRoom = rooms ? detectHostRoomId(pt, rooms) : source.hostRoom;
	const updated: IComponentInstance = {
		...source,
		id: nextId ?? source.id,
		point: pt,
		rotation: rot || undefined,
		mirrored: !source.mirrored || undefined,
		...(hostRoom ? { hostRoom } : {}),
	};
	const components = nextId
		? [...(arch.components ?? []), updated]
		: (arch.components ?? []).map(c => c.id === componentId ? updated : c);
	return { ok: true, value: { ...arch, components }, id: updated.id };
}

export function addMass(
	arch: IArchitecture,
	outline: readonly CadPoint[],
	height: number,
	id: string,
	baseElevation = 0,
	floorHeight = 3000,
	name?: string,
): CompEdit {
	const pts = outline.length > 3 && Math.hypot(outline[0][0] - outline[outline.length - 1][0], outline[0][1] - outline[outline.length - 1][1]) < 1 ? outline.slice(0, -1) : outline;
	if (pts.length < 3 || Math.abs(signedArea(pts)) <= 0) {
		return { ok: false, error: localize('arch.massTooSmall', "A conceptual mass needs three or more corners enclosing an area.") };
	}
	if (!(height > 0)) {
		return { ok: false, error: localize('arch.massHeightInvalid', "A conceptual mass needs a positive height.") };
	}
	const mass: IConceptualMass = {
		id,
		name: name ?? id,
		kind: 'extrusion',
		baseElevation,
		height,
		outline: pts.map(([x, y]) => [Math.round(x), Math.round(y)] as CadPoint),
		floorHeight,
	};
	return { ok: true, value: { ...arch, masses: [...(arch.masses ?? []), mass] }, id };
}

// ───────────────────────────── unified types library ─────────────────────────────

const ARCH_TYPE_FIELD: { readonly [cat in ArchTypeCategory]: string } = {
	wall: 'wallTypes',
	door: 'doorTypes',
	window: 'windowTypes',
	finish: 'finishTypes',
	roof: 'roofTypes',
	railing: 'railingTypes',
	ceiling: 'ceilingTypes',
	curtainWall: 'curtainWallTypes',
	component: 'componentTypes',
};

function typeList(arch: IArchitecture, category: ArchTypeCategory): readonly Json[] {
	const raw = (arch as unknown as Json)[ARCH_TYPE_FIELD[category]];
	return Array.isArray(raw) ? raw.filter(isObject) : [];
}

function setTypeList(arch: IArchitecture, category: ArchTypeCategory, items: readonly Json[]): IArchitecture {
	switch (category) {
		case 'wall': return { ...arch, wallTypes: items as unknown as IArchitecture['wallTypes'] };
		case 'door': return { ...arch, doorTypes: items as unknown as IArchitecture['doorTypes'] };
		case 'window': return { ...arch, windowTypes: items as unknown as IArchitecture['windowTypes'] };
		case 'finish': return { ...arch, finishTypes: items as unknown as IArchitecture['finishTypes'] };
		case 'roof': return { ...arch, roofTypes: items as unknown as IArchitecture['roofTypes'] };
		case 'railing': return { ...arch, railingTypes: items as unknown as IArchitecture['railingTypes'] };
		case 'curtainWall': return { ...arch, curtainWallTypes: items as unknown as IArchitecture['curtainWallTypes'] };
		case 'component': return { ...arch, componentTypes: items as unknown as IComponentType[] };
		case 'ceiling': return { ...arch, ceilingTypes: items as unknown as IArchitecture['ceilingTypes'] };
	}
}

export function typeUsages(arch: IArchitecture, category: ArchTypeCategory, typeId: string): string[] {
	switch (category) {
		case 'wall': return arch.walls.filter(w => w.type === typeId).map(w => w.id);
		case 'door': return arch.doors.filter(d => d.type === typeId).map(d => d.id);
		case 'window': return arch.windows.filter(w => w.type === typeId).map(w => w.id);
		case 'finish': return [
			...arch.rooms.filter(r => r.floorFinish === typeId || r.wallFinish === typeId || r.ceilingFinish === typeId).map(r => r.id),
			...arch.ramps.filter(r => r.finish === typeId).map(r => r.id),
		];
		case 'roof': return arch.roofs.filter(r => r.type === typeId).map(r => r.id);
		case 'railing': return arch.railings.filter(r => r.type === typeId).map(r => r.id);
		case 'curtainWall': return arch.curtainWalls.filter(c => c.type === typeId).map(c => c.id);
		case 'component': return (arch.components ?? []).filter(c => c.type === typeId).map(c => c.id);
		case 'ceiling': return arch.ceilings.filter(c => c.type === typeId).map(c => c.id);
	}
}

export function listArchTypes(arch: IArchitecture, category?: ArchTypeCategory): IArchTypeEntry[] {
	const cats = category ? [category] : ARCH_TYPE_CATEGORIES;
	const entries: IArchTypeEntry[] = [];
	for (const cat of cats) {
		for (const item of typeList(arch, cat)) {
			if (typeof item.id !== 'string') {
				continue;
			}
			entries.push({
				category: cat,
				id: item.id,
				name: typeof item.name === 'string' ? item.name : item.id,
				usedBy: typeUsages(arch, cat, item.id),
				data: item,
			});
		}
	}
	return entries;
}

export function duplicateArchType(arch: IArchitecture, category: ArchTypeCategory, typeId: string, newId?: string, newName?: string): { readonly ok: true; readonly value: IArchitecture; readonly id: string } | { readonly ok: false; readonly error: string } {
	const list = typeList(arch, category);
	const source = list.find(t => t.id === typeId);
	if (!source) {
		return { ok: false, error: localize('arch.typeMissing', "Type '{0}' was not found.", typeId) };
	}
	const ids = new Set(list.map(t => String(t.id)));
	let candidate = newId?.trim();
	if (!candidate) {
		let n = 2;
		while (ids.has(`${typeId}-${n}`)) {
			n++;
		}
		candidate = `${typeId}-${n}`;
	}
	if (ids.has(candidate)) {
		return { ok: false, error: localize('arch.typeExists', "A type with ID '{0}' already exists.", candidate) };
	}
	const copy: Json = {
		...source,
		id: candidate,
		name: newName?.trim() || `${String(source.name ?? typeId)} (copy)`,
	};
	return { ok: true, value: setTypeList(arch, category, [...list, copy]), id: candidate };
}

export function renameArchType(arch: IArchitecture, category: ArchTypeCategory, oldId: string, newId: string, newName?: string): { readonly ok: true; readonly value: IArchitecture } | { readonly ok: false; readonly error: string } {
	const targetId = newId.trim();
	if (!targetId) {
		return { ok: false, error: localize('arch.typeIdEmpty', "Type ID cannot be empty.") };
	}
	const list = typeList(arch, category);
	if (!list.some(t => t.id === oldId)) {
		return { ok: false, error: localize('arch.typeMissing', "Type '{0}' was not found.", oldId) };
	}
	if (targetId !== oldId && list.some(t => t.id === targetId)) {
		return { ok: false, error: localize('arch.typeExists', "A type with ID '{0}' already exists.", targetId) };
	}
	const nextList = list.map(t => t.id === oldId ? { ...t, id: targetId, ...(newName ? { name: newName } : {}) } : t);
	let next = setTypeList(arch, category, nextList);
	if (targetId !== oldId) {
		switch (category) {
			case 'wall': next = { ...next, walls: next.walls.map(w => w.type === oldId ? { ...w, type: targetId } : w) }; break;
			case 'door': next = { ...next, doors: next.doors.map(d => d.type === oldId ? { ...d, type: targetId } : d) }; break;
			case 'window': next = { ...next, windows: next.windows.map(w => w.type === oldId ? { ...w, type: targetId } : w) }; break;
			case 'finish':
				next = {
					...next,
					rooms: next.rooms.map(r => ({
						...r,
						...(r.floorFinish === oldId ? { floorFinish: targetId } : {}),
						...(r.wallFinish === oldId ? { wallFinish: targetId } : {}),
						...(r.ceilingFinish === oldId ? { ceilingFinish: targetId } : {}),
					})),
					ramps: next.ramps.map(rp => rp.finish === oldId ? { ...rp, finish: targetId } : rp),
				};
				break;
			case 'roof': next = { ...next, roofs: next.roofs.map(r => r.type === oldId ? { ...r, type: targetId } : r) }; break;
			case 'railing': next = { ...next, railings: next.railings.map(r => r.type === oldId ? { ...r, type: targetId } : r) }; break;
			case 'curtainWall': next = { ...next, curtainWalls: next.curtainWalls.map(c => c.type === oldId ? { ...c, type: targetId } : c) }; break;
			case 'component': next = { ...next, components: (next.components ?? []).map(c => c.type === oldId ? { ...c, type: targetId } : c) }; break;
			case 'ceiling': next = { ...next, ceilings: next.ceilings.map(c => c.type === oldId ? { ...c, type: targetId } : c) }; break;
		}
	}
	return { ok: true, value: next };
}

export function updateArchType(arch: IArchitecture, category: ArchTypeCategory, typeId: string, changes: { readonly [key: string]: unknown }): IArchitecture {
	const nextList = typeList(arch, category).map(t => {
		if (t.id !== typeId) {
			return t;
		}
		const copy: { [key: string]: unknown } = { ...t };
		for (const [k, v] of Object.entries(changes)) {
			if (v === undefined || v === '') {
				delete copy[k];
			} else {
				copy[k] = v;
			}
		}
		return copy;
	});
	return setTypeList(arch, category, nextList);
}

export function deleteArchType(arch: IArchitecture, category: ArchTypeCategory, typeId: string): { readonly ok: true; readonly value: IArchitecture } | { readonly ok: false; readonly error: string } {
	const list = typeList(arch, category);
	if (!list.some(t => t.id === typeId)) {
		return { ok: false, error: localize('arch.typeMissing', "Type '{0}' was not found.", typeId) };
	}
	const used = typeUsages(arch, category, typeId);
	if (used.length) {
		return { ok: false, error: localize('arch.typeInUse', "Cannot delete type '{0}': it is used by {1}.", typeId, used.join(', ')) };
	}
	return { ok: true, value: setTypeList(arch, category, list.filter(t => t.id !== typeId)) };
}

export function exportTypesLibrary(arch: IArchitecture, name = 'Office Standards'): ITypesLibrary {
	const out: { [key: string]: unknown } = { schema: TYPES_LIBRARY_SCHEMA_ID, name };
	for (const cat of ARCH_TYPE_CATEGORIES) {
		const field = ARCH_TYPE_FIELD[cat];
		out[field] = typeList(arch, cat);
	}
	if (arch.curtainPanelTypes.length) {
		out.curtainPanelTypes = arch.curtainPanelTypes;
	}
	if (arch.curtainMullionTypes.length) {
		out.curtainMullionTypes = arch.curtainMullionTypes;
	}
	return out as unknown as ITypesLibrary;
}

export function importTypesLibrary(arch: IArchitecture, raw: unknown, overwrite = false): { readonly ok: true; readonly value: IArchitecture; readonly added: number; readonly updated: number } | { readonly ok: false; readonly error: string } {
	if (!isObject(raw) || raw.schema !== TYPES_LIBRARY_SCHEMA_ID) {
		return { ok: false, error: localize('arch.badTypesLib', "This file is not a SAEngine types library ({0}).", TYPES_LIBRARY_SCHEMA_ID) };
	}
	let next = arch;
	let added = 0;
	let updated = 0;
	for (const subField of ['curtainPanelTypes', 'curtainMullionTypes'] as const) {
		const incoming = Array.isArray(raw[subField]) ? (raw[subField] as unknown[]).filter(isObject).filter(t => typeof t.id === 'string') : [];
		if (!incoming.length) {
			continue;
		}
		const current = [...(next[subField] as unknown as readonly Json[])];
		const indexById = new Map(current.map((t, i) => [String(t.id), i]));
		for (const item of incoming) {
			const idx = indexById.get(String(item.id));
			if (idx !== undefined) {
				if (overwrite) {
					current[idx] = item;
				}
			} else {
				indexById.set(String(item.id), current.length);
				current.push(item);
			}
		}
		next = { ...next, [subField]: current };
	}
	for (const cat of ARCH_TYPE_CATEGORIES) {
		const field = ARCH_TYPE_FIELD[cat];
		const incoming = Array.isArray(raw[field]) ? (raw[field] as unknown[]).filter(isObject).filter(t => typeof t.id === 'string') : [];
		if (!incoming.length) {
			continue;
		}
		const current = [...typeList(next, cat)];
		const indexById = new Map(current.map((t, i) => [String(t.id), i]));
		for (const item of incoming) {
			const idx = indexById.get(String(item.id));
			if (idx !== undefined) {
				if (overwrite) {
					current[idx] = item;
					updated++;
				}
			} else {
				indexById.set(String(item.id), current.length);
				current.push(item);
				added++;
			}
		}
		next = setTypeList(next, cat, current);
	}
	return { ok: true, value: next, added, updated };
}
