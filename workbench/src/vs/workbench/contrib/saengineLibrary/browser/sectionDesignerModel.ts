/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * The Section Designer's document and geometry, without the DOM: a designed section
 * (`04 Objects/sections/<id>.json`, `saengine.library.section_designer` in Python), the outline
 * templates, the bar layouts, snapping and the scales of the interaction chart. Units: mm, N.
 */

import { localize } from '../../../../nls.js';
import { signedArea } from '../../../../platform/saengine/common/geometry.js';

export const SECTION_SCHEMA = 'saengine.section/1';
/** Folder of the designed sections, relative to the project root. */
export const SECTIONS_FOLDER = '04 Objects/sections';

export type Point = readonly [number, number];
export type Ring = Point[];

export interface IRegion {
	outline: Ring;
	holes: Ring[];
	material: string;
	label?: string;
}

export interface IBar {
	x: number;
	y: number;
	dia: number;
	material?: string;
}

export interface IDesignedSection {
	schema: typeof SECTION_SCHEMA;
	id: string;
	name: string;
	description?: string;
	regions: IRegion[];
	bars: IBar[];
	rebar?: string;
	confinement: 'tied' | 'spiral';
	cover?: number;
	meshSize?: number;
}

// ───────────────────────────── reading and writing ─────────────────────────────

function isPoint(value: unknown): value is Point {
	return Array.isArray(value) && value.length === 2 && value.every(v => typeof v === 'number' && Number.isFinite(v));
}

function isRing(value: unknown): value is Ring {
	return Array.isArray(value) && value.every(isPoint);
}

/** The section in `text`, or why the visual editor cannot show it. */
export function parseSection(text: string): { readonly ok: true; readonly section: IDesignedSection } | { readonly ok: false; readonly error: string } {
	let value: unknown;
	try {
		value = JSON.parse(text);
	} catch (error) {
		return { ok: false, error: localize('section.invalidJson', "This file contains invalid JSON ({0}).", String(error)) };
	}
	const data = value as Partial<IDesignedSection> | undefined;
	if (!data || typeof data !== 'object' || Array.isArray(data)) {
		return { ok: false, error: localize('section.notObject', "This file does not contain a JSON object.") };
	}
	if (data.schema !== undefined && data.schema !== SECTION_SCHEMA) {
		return { ok: false, error: localize('section.schema', "This is not a designed section ({0}).", String(data.schema)) };
	}
	const regions = Array.isArray(data.regions) ? data.regions : [];
	for (const region of regions) {
		if (!region || !isRing(region.outline) || !(region.holes === undefined || (Array.isArray(region.holes) && region.holes.every(isRing))) || typeof region.material !== 'string') {
			return { ok: false, error: localize('section.badRegion', "A region needs an outline of [x, y] points and a material.") };
		}
	}
	const bars = Array.isArray(data.bars) ? data.bars : [];
	if (!bars.every(b => b && typeof b.x === 'number' && typeof b.y === 'number' && typeof b.dia === 'number')) {
		return { ok: false, error: localize('section.badBar', "A bar needs x, y and dia.") };
	}
	return {
		ok: true,
		section: {
			...data,
			schema: SECTION_SCHEMA,
			id: typeof data.id === 'string' ? data.id : 'SD1',
			name: typeof data.name === 'string' ? data.name : (typeof data.id === 'string' ? data.id : 'SD1'),
			regions: regions.map(r => ({ ...r, outline: r.outline.map(p => [p[0], p[1]] as Point), holes: (r.holes ?? []).map(h => h.map(p => [p[0], p[1]] as Point)) })),
			bars: bars.map(b => ({ ...b })),
			confinement: data.confinement === 'spiral' ? 'spiral' : 'tied',
		},
	};
}

/** The file's text: tab-indented JSON with each point on one line, as the other project files. */
export function serializeSection(section: IDesignedSection): string {
	const text = JSON.stringify(section, (_key, value) => {
		if (isPoint(value)) {
			return `${POINT_MARK}${round(value[0])}, ${round(value[1])}${POINT_MARK}`;
		}
		return typeof value === 'number' ? round(value) : value;
	}, '\t');
	return text.replace(new RegExp(`"${POINT_MARK}([^"]*)${POINT_MARK}"`, 'g'), '[$1]') + '\n';
}

const POINT_MARK = '@@point@@';

function round(value: number): number {
	return Math.round(value * 1000) / 1000;
}

/** A new section: a 500 x 500 rectangle with 8 bars at 40 mm cover. */
export function newSection(id: string, concrete: string, rebar: string): IDesignedSection {
	const section: IDesignedSection = {
		schema: SECTION_SCHEMA,
		id,
		name: id,
		regions: [{ outline: rectangle(500, 500), holes: [], material: concrete }],
		bars: [],
		rebar,
		confinement: 'tied',
		cover: 40,
	};
	section.bars = barsAlongEdges(section.regions[0], 40 + 10, 20, 200);
	return section;
}

// ───────────────────────────── geometry ─────────────────────────────

/** Net area of a region (outline less holes) [mm²]. */
export function regionArea(region: IRegion): number {
	return Math.abs(signedArea(region.outline)) - region.holes.reduce((sum, h) => sum + Math.abs(signedArea(h)), 0);
}

export function pointInRing(point: Point, ring: readonly Point[]): boolean {
	const [x, y] = point;
	let inside = false;
	for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
		const [xi, yi] = ring[i];
		const [xj, yj] = ring[j];
		if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) {
			inside = !inside;
		}
	}
	return inside;
}

export function pointInRegion(point: Point, region: IRegion): boolean {
	return pointInRing(point, region.outline) && !region.holes.some(h => pointInRing(point, h));
}

export function bounds(section: IDesignedSection): { minX: number; minY: number; maxX: number; maxY: number } | undefined {
	const points = section.regions.flatMap(r => r.outline);
	if (!points.length) {
		return undefined;
	}
	return {
		minX: Math.min(...points.map(p => p[0])),
		minY: Math.min(...points.map(p => p[1])),
		maxX: Math.max(...points.map(p => p[0])),
		maxY: Math.max(...points.map(p => p[1])),
	};
}

export function snap(value: number, step: number): number {
	return step > 0 ? Math.round(value / step) * step : value;
}

export function snapPoint(point: Point, step: number): Point {
	return [snap(point[0], step), snap(point[1], step)];
}

/**
 * The ring offset by `distance` into the material: inwards for an outline, outwards (into the
 * concrete around it) for a hole. Each edge moves along its normal and neighbouring edges are
 * intersected (mitred corners), which is exact for the straight-edged outlines drawn here.
 */
export function offsetRing(ring: readonly Point[], distance: number, hole = false): Ring {
	const n = ring.length;
	const ccw = signedArea(ring) > 0;
	// Inward normal of an anticlockwise ring is the left normal; a hole's material is outside it.
	const sign = (ccw ? 1 : -1) * (hole ? -1 : 1);
	const lines = ring.map((p, i) => {
		const q = ring[(i + 1) % n];
		const dx = q[0] - p[0], dy = q[1] - p[1];
		const length = Math.hypot(dx, dy) || 1;
		const nx = -dy / length * sign * distance, ny = dx / length * sign * distance;
		return { p: [p[0] + nx, p[1] + ny] as Point, d: [dx, dy] as Point };
	});
	return lines.map((line, i) => {
		const prev = lines[(i - 1 + n) % n];
		const cross = prev.d[0] * line.d[1] - prev.d[1] * line.d[0];
		if (Math.abs(cross) < 1e-9) {
			return line.p; // collinear edges: the moved point itself
		}
		const t = ((line.p[0] - prev.p[0]) * line.d[1] - (line.p[1] - prev.p[1]) * line.d[0]) / cross;
		return [prev.p[0] + t * prev.d[0], prev.p[1] + t * prev.d[1]] as Point;
	});
}

// ───────────────────────────── templates ─────────────────────────────

export type TemplateKind = 'rectangle' | 'circle' | 'L' | 'T' | 'C' | 'box' | 'core' | 'I';

export interface ITemplateParams {
	/** Overall width (x) [mm]. */
	readonly b: number;
	/** Overall depth (y) [mm]. */
	readonly h: number;
	/** Wall, leg or web thickness [mm]. */
	readonly t: number;
	/** Flange thickness [mm] (T, C, I); the wall thickness when omitted. */
	readonly tf?: number;
	/** Door opening width in the core's front wall [mm] (core). */
	readonly opening?: number;
}

export const TEMPLATE_DEFAULTS: { readonly [kind in TemplateKind]: ITemplateParams } = {
	rectangle: { b: 400, h: 600, t: 0 },
	circle: { b: 600, h: 600, t: 0 },
	L: { b: 600, h: 600, t: 250 },
	T: { b: 900, h: 600, t: 250 },
	C: { b: 600, h: 900, t: 250 },
	box: { b: 2000, h: 2000, t: 250 },
	core: { b: 3000, h: 2500, t: 250, opening: 1000 },
	I: { b: 300, h: 500, t: 10, tf: 16 },
};

export function templateLabel(kind: TemplateKind): string {
	switch (kind) {
		case 'rectangle': return localize('section.template.rectangle', "Rectangle");
		case 'circle': return localize('section.template.circle', "Circle");
		case 'L': return localize('section.template.L', "L column");
		case 'T': return localize('section.template.T', "T column");
		case 'C': return localize('section.template.C', "C (channel) column");
		case 'box': return localize('section.template.box', "Box");
		case 'core': return localize('section.template.core', "Core wall with opening");
		case 'I': return localize('section.template.I', "Built-up I (plates)");
	}
}

/** An anticlockwise rectangle centred on the origin. */
export function rectangle(b: number, h: number, cx = 0, cy = 0): Ring {
	return [[cx - b / 2, cy - h / 2], [cx + b / 2, cy - h / 2], [cx + b / 2, cy + h / 2], [cx - b / 2, cy + h / 2]];
}

/**
 * The regions of a template, centred on its bounding box. All are one region of `material`
 * except the built-up I, three plates (flanges and web) of it.
 */
export function templateRegions(kind: TemplateKind, p: ITemplateParams, material: string): IRegion[] {
	const { b, h, t } = p;
	const tf = p.tf ?? t;
	const x0 = -b / 2, y0 = -h / 2, x1 = b / 2, y1 = h / 2;
	const region = (outline: Ring, holes: Ring[] = []): IRegion => ({ outline, holes, material });
	switch (kind) {
		case 'rectangle':
			return [region(rectangle(b, h))];
		case 'circle': {
			const n = 48;
			return [region(Array.from({ length: n }, (_, k) => [b / 2 * Math.cos(2 * Math.PI * k / n), b / 2 * Math.sin(2 * Math.PI * k / n)] as Point))];
		}
		case 'L':
			return [region([[x0, y0], [x1, y0], [x1, y0 + t], [x0 + t, y0 + t], [x0 + t, y1], [x0, y1]])];
		case 'T':
			return [region([[x0, y1 - tf], [-t / 2, y1 - tf], [-t / 2, y0], [t / 2, y0], [t / 2, y1 - tf], [x1, y1 - tf], [x1, y1], [x0, y1]])];
		case 'C':
			return [region([[x0, y0], [x1, y0], [x1, y0 + tf], [x0 + t, y0 + tf], [x0 + t, y1 - tf], [x1, y1 - tf], [x1, y1], [x0, y1]])];
		case 'box':
			return [region(rectangle(b, h), [rectangle(b - 2 * t, h - 2 * t)])];
		case 'core': {
			// A box core whose bottom (front) wall has a door opening in the middle: a C-shaped
			// outline closed to the opening's jambs.
			const o = Math.min(p.opening ?? b / 3, b - 2 * t - 2 * t);
			return [region([
				[x0, y0], [-o / 2, y0], [-o / 2, y0 + t], [x0 + t, y0 + t], [x0 + t, y1 - t], [x1 - t, y1 - t], [x1 - t, y0 + t], [o / 2, y0 + t], [o / 2, y0], [x1, y0], [x1, y1], [x0, y1],
			])];
		}
		case 'I':
			return [
				region(rectangle(b, tf, 0, y1 - tf / 2)),
				region(rectangle(t, h - 2 * tf)),
				region(rectangle(b, tf, 0, y0 + tf / 2)),
			];
	}
}

// ───────────────────────────── bars ─────────────────────────────

export function barArea(dia: number): number {
	return Math.PI * dia * dia / 4;
}

/** `count` bars evenly from `from` to `to`, both ends included. */
export function barsLine(from: Point, to: Point, count: number, dia: number): IBar[] {
	if (count <= 1) {
		return [{ x: round(from[0]), y: round(from[1]), dia }];
	}
	return Array.from({ length: count }, (_, k) => {
		const s = k / (count - 1);
		return { x: round(from[0] + s * (to[0] - from[0])), y: round(from[1] + s * (to[1] - from[1])), dia };
	});
}

/** `count` bars on a circle (the first at angle 0). */
export function barsRing(center: Point, radius: number, count: number, dia: number): IBar[] {
	return Array.from({ length: count }, (_, k) => {
		const a = 2 * Math.PI * k / count;
		return { x: round(center[0] + radius * Math.cos(a)), y: round(center[1] + radius * Math.sin(a)), dia };
	});
}

/**
 * Bars along every edge of a region, their centres `inset` from the faces (clear cover, ties and
 * half the bar), one at each corner and as many between as keep the spacing at most `spacing`; the faces of holes (core walls) get bars too. Corners closer than
 * the bar to each other are merged.
 */
export function barsAlongEdges(region: IRegion, inset: number, dia: number, spacing: number): IBar[] {
	const bars: IBar[] = [];
	const rings = [offsetRing(region.outline, inset), ...region.holes.map(h => offsetRing(h, inset, true))];
	for (const ring of rings) {
		for (let i = 0; i < ring.length; i++) {
			const p = ring[i];
			const q = ring[(i + 1) % ring.length];
			const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
			const count = Math.max(1, Math.ceil(length / spacing));
			for (let k = 0; k < count; k++) {
				const s = k / count;
				addBar(bars, { x: round(p[0] + s * (q[0] - p[0])), y: round(p[1] + s * (q[1] - p[1])), dia });
			}
		}
	}
	return bars.filter(bar => pointInRegion([bar.x, bar.y], region));
}

function addBar(bars: IBar[], bar: IBar): void {
	if (!bars.some(b => Math.hypot(b.x - bar.x, b.y - bar.y) < (b.dia + bar.dia) / 2)) {
		bars.push(bar);
	}
}

// ───────────────────────────── hit testing ─────────────────────────────

export type Selection = { readonly kind: 'region'; readonly index: number } | { readonly kind: 'bar'; readonly index: number } | undefined;

/** What is under `point` (bars first, within `tolerance` of their edge), else undefined. */
export function hitTest(section: IDesignedSection, point: Point, tolerance: number): Selection {
	for (let i = section.bars.length - 1; i >= 0; i--) {
		const bar = section.bars[i];
		if (Math.hypot(bar.x - point[0], bar.y - point[1]) <= bar.dia / 2 + tolerance) {
			return { kind: 'bar', index: i };
		}
	}
	for (let i = section.regions.length - 1; i >= 0; i--) {
		if (pointInRegion(point, section.regions[i])) {
			return { kind: 'region', index: i };
		}
	}
	return undefined;
}

/** The section with the selected region or bar moved by (dx, dy). */
export function moveSelection(section: IDesignedSection, selection: Selection, dx: number, dy: number): void {
	if (selection?.kind === 'bar') {
		const bar = section.bars[selection.index];
		bar.x = round(bar.x + dx);
		bar.y = round(bar.y + dy);
	} else if (selection?.kind === 'region') {
		const region = section.regions[selection.index];
		const move = (ring: Ring) => ring.map(([x, y]) => [round(x + dx), round(y + dy)] as Point);
		region.outline = move(region.outline);
		region.holes = region.holes.map(move);
	}
}

// ───────────────────────────── results ─────────────────────────────

/** The backend's answer (`section/analyse`). */
export interface ISectionAnalysis {
	readonly problems: readonly { readonly path: string; readonly message: string }[];
	readonly properties?: ISectionProperties;
	readonly uniaxial?: { readonly x: IUniaxial; readonly y: IUniaxial };
	readonly capacityNote?: string;
	readonly phi?: { readonly tension: number; readonly compression: number };
}

export interface ISectionProperties {
	readonly referenceMaterial: string;
	readonly E: number;
	readonly area: number;
	readonly cx: number;
	readonly cy: number;
	readonly ixx: number;
	readonly iyy: number;
	readonly ixy: number;
	readonly i11: number;
	readonly i22: number;
	readonly principalAngle: number;
	readonly rx: number;
	readonly ry: number;
	readonly sxTop: number;
	readonly sxBottom: number;
	readonly syRight: number;
	readonly syLeft: number;
	readonly zx: number | null;
	readonly zy: number | null;
	readonly j: number;
	readonly cw: number;
	readonly asx: number;
	readonly asy: number;
	readonly scx: number;
	readonly scy: number;
	readonly massPerLength: number;
	readonly barArea: number;
	readonly barRatio: number;
}

export interface IUniaxialPoint {
	readonly P: number;
	readonly M: number;
	readonly phiP: number;
	readonly phiM: number;
	readonly phi: number;
	readonly epsT: number | null;
}

export interface IUniaxial {
	readonly axis: 'x' | 'y';
	readonly points: readonly IUniaxialPoint[];
	readonly phiPnMax: number;
	readonly phiTension: number;
	readonly p0: number;
}

/** A value as engineers read it: 3 significant digits, × 10ⁿ for large or small numbers. */
export function formatNumber(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) {
		return '—';
	}
	if (value === 0) {
		return '0';
	}
	const exponent = Math.floor(Math.log10(Math.abs(value)));
	if (exponent >= -2 && exponent < 5) {
		return String(Number(value.toPrecision(4)));
	}
	const engineering = Math.floor(exponent / 3) * 3;
	const mantissa = value / Math.pow(10, engineering);
	return `${Number(mantissa.toPrecision(4))} × 10${superscript(engineering)}`;
}

function superscript(n: number): string {
	const digits = '⁰¹²³⁴⁵⁶⁷⁸⁹';
	return (n < 0 ? '⁻' : '') + String(Math.abs(n)).split('').map(d => digits[Number(d)]).join('');
}

export interface IPropertyRow {
	readonly label: string;
	readonly value: string;
	readonly unit: string;
	/** Longer explanation, for the hover. */
	readonly title?: string;
}

/** The properties table: name, value and unit per row. */
export function propertyRows(p: ISectionProperties): IPropertyRow[] {
	// Ixy of a symmetric section comes out as round-off (1e-4 mm⁴ against 1e12): shown as 0.
	const ixy = Math.abs(p.ixy) < 1e-9 * Math.sqrt(Math.abs(p.ixx * p.iyy)) ? 0 : p.ixy;
	const row = (label: string, value: number | null, unit: string, title?: string): IPropertyRow => ({ label, value: formatNumber(value), unit, title });
	return [
		row(localize('section.prop.area', "A"), p.area, 'mm²', localize('section.prop.areaTitle', "Area (transformed to the reference material)")),
		row(localize('section.prop.cx', "x̄"), p.cx, 'mm', localize('section.prop.cxTitle', "Centroid x")),
		row(localize('section.prop.cy', "ȳ"), p.cy, 'mm', localize('section.prop.cyTitle', "Centroid y")),
		row(localize('section.prop.ixx', "Ixx"), p.ixx, 'mm⁴', localize('section.prop.ixxTitle', "Second moment of area about the horizontal centroidal axis")),
		row(localize('section.prop.iyy', "Iyy"), p.iyy, 'mm⁴', localize('section.prop.iyyTitle', "Second moment of area about the vertical centroidal axis")),
		row(localize('section.prop.ixy', "Ixy"), ixy, 'mm⁴', localize('section.prop.ixyTitle', "Product of inertia")),
		row(localize('section.prop.i11', "I11"), p.i11, 'mm⁴', localize('section.prop.i11Title', "Major principal moment of inertia")),
		row(localize('section.prop.i22', "I22"), p.i22, 'mm⁴', localize('section.prop.i22Title', "Minor principal moment of inertia")),
		row(localize('section.prop.angle', "θ"), p.principalAngle, '°', localize('section.prop.angleTitle', "Angle from x to the major principal axis")),
		row(localize('section.prop.rx', "rx"), p.rx, 'mm'),
		row(localize('section.prop.ry', "ry"), p.ry, 'mm'),
		row(localize('section.prop.sxTop', "Sx,top"), p.sxTop, 'mm³', localize('section.prop.sxTitle', "Elastic section modulus to the top fibre")),
		row(localize('section.prop.sxBottom', "Sx,bottom"), p.sxBottom, 'mm³'),
		row(localize('section.prop.syRight', "Sy,right"), p.syRight, 'mm³'),
		row(localize('section.prop.syLeft', "Sy,left"), p.syLeft, 'mm³'),
		row(localize('section.prop.zx', "Zx"), p.zx, 'mm³', localize('section.prop.zxTitle', "Plastic section modulus (one material only)")),
		row(localize('section.prop.zy', "Zy"), p.zy, 'mm³'),
		row(localize('section.prop.j', "J"), p.j, 'mm⁴', localize('section.prop.jTitle', "St. Venant torsion constant")),
		row(localize('section.prop.cw', "Cw"), p.cw, 'mm⁶', localize('section.prop.cwTitle', "Warping constant")),
		row(localize('section.prop.asx', "Asx"), p.asx, 'mm²', localize('section.prop.asxTitle', "Shear area for shear along x")),
		row(localize('section.prop.asy', "Asy"), p.asy, 'mm²', localize('section.prop.asyTitle', "Shear area for shear along y")),
		row(localize('section.prop.scx', "xs"), p.scx, 'mm', localize('section.prop.scTitle', "Shear centre")),
		row(localize('section.prop.scy', "ys"), p.scy, 'mm', localize('section.prop.scTitle', "Shear centre")),
		row(localize('section.prop.mass', "Mass"), p.massPerLength, 'kg/m'),
		row(localize('section.prop.bars', "Bars As"), p.barArea, 'mm²'),
		row(localize('section.prop.rho', "ρ"), p.barRatio * 100, '%', localize('section.prop.rhoTitle', "Bar area over concrete area")),
	].filter(r => r.value !== '—');
}

// ───────────────────────────── chart ─────────────────────────────

/**
 * The interaction diagram as closed curves in display units, [M kN·m, P kN] with compression
 * up: the nominal (`factored` false) or the design points.
 */
export function interactionCurve(diagram: IUniaxial, factored: boolean): number[][] {
	const points = diagram.points.map(q => [(factored ? q.phiM : q.M) / 1e6, (factored ? q.phiP : q.P) / 1e3]);
	return points.length ? [...points, points[0]] : [];
}
