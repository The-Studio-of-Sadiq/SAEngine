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

/** The dimensions each template is drawn from, with their names, for its parameter form. */
export function templateFields(kind: TemplateKind): readonly { readonly key: keyof ITemplateParams; readonly label: string }[] {
	const b = { key: 'b' as const, label: localize('section.param.b', "Width b [mm]") };
	const h = { key: 'h' as const, label: localize('section.param.h', "Depth h [mm]") };
	const t = { key: 't' as const, label: kind === 'I' ? localize('section.param.tw', "Web thickness tw [mm]") : localize('section.param.t', "Thickness t [mm]") };
	const tf = { key: 'tf' as const, label: localize('section.param.tf', "Flange thickness tf [mm]") };
	switch (kind) {
		case 'rectangle': return [b, h];
		case 'circle': return [{ key: 'b', label: localize('section.param.d', "Diameter D [mm]") }];
		case 'L': case 'box': return [b, h, t];
		case 'T': case 'C': case 'I': return [b, h, t, tf];
		case 'core': return [b, h, t, { key: 'opening', label: localize('section.param.opening', "Door opening [mm]") }];
	}
}

/** Whether a template's dimensions draw a valid shape (thicknesses inside the outline). */
export function templateProblem(kind: TemplateKind, p: ITemplateParams): string | undefined {
	const { b, h, t } = p;
	const tf = p.tf ?? t;
	if (!(b > 0) || (kind !== 'circle' && !(h > 0))) {
		return localize('section.param.positive', "The width and depth must be more than 0.");
	}
	if (kind === 'rectangle' || kind === 'circle') {
		return undefined;
	}
	if (!(t > 0) || !(tf > 0)) {
		return localize('section.param.thickness', "The thicknesses must be more than 0.");
	}
	if (t >= b || tf >= h / (kind === 'L' || kind === 'T' ? 1 : 2) || (kind === 'box' || kind === 'core') && (2 * t >= b || 2 * t >= h)) {
		return localize('section.param.tooThick', "The thicknesses must leave room inside the outline.");
	}
	if (kind === 'core' && !((p.opening ?? 0) > 0 && (p.opening ?? 0) < b - 4 * t)) {
		return localize('section.param.openingProblem', "The door opening must be more than 0 and leave a jamb of 2t on each side.");
	}
	return undefined;
}

/** Whether two sets of regions are the same shapes (to the 0.01 mm the file keeps). */
export function sameRegions(a: readonly IRegion[], b: readonly IRegion[]): boolean {
	const same = (p: readonly Point[], q: readonly Point[]) => p.length === q.length && p.every((v, i) => Math.abs(v[0] - q[i][0]) < 0.01 && Math.abs(v[1] - q[i][1]) < 0.01);
	return a.length === b.length && a.every((r, i) => r.material === b[i].material && same(r.outline, b[i].outline) && r.holes.length === b[i].holes.length && r.holes.every((hole, k) => same(hole, b[i].holes[k])));
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
	// The corner bars' coordinates: a bar between corners close to one moves onto its line, so the
	// bars of parallel faces line up (an L's leg with its inner corner) instead of nearly lining up.
	const corners = rings.flat();
	const align = (value: number, axis: 0 | 1, from: number, to: number) => {
		const [lo, hi] = from < to ? [from, to] : [to, from];
		const near = corners.map(c => c[axis]).filter(c => c > lo + dia && c < hi - dia && Math.abs(c - value) < spacing / 4);
		return near.length ? near.reduce((a, c) => Math.abs(c - value) < Math.abs(a - value) ? c : a) : value;
	};
	for (const ring of rings) {
		for (let i = 0; i < ring.length; i++) {
			const p = ring[i];
			const q = ring[(i + 1) % ring.length];
			const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
			const count = Math.max(1, Math.ceil(length / spacing));
			for (let k = 0; k < count; k++) {
				const s = k / count;
				let x = p[0] + s * (q[0] - p[0]), y = p[1] + s * (q[1] - p[1]);
				if (k > 0 && Math.abs(p[1] - q[1]) < 1e-6) {
					x = align(x, 0, p[0], q[0]); // a horizontal face
				} else if (k > 0 && Math.abs(p[0] - q[0]) < 1e-6) {
					y = align(y, 1, p[1], q[1]); // a vertical face
				}
				addBar(bars, { x: round(x), y: round(y), dia });
			}
		}
	}
	return bars.filter(bar => pointInRegion([bar.x, bar.y], region));
}

/** An axis-aligned rectangle: one leg (or flange, or web) of a template. */
interface ILeg {
	readonly x0: number;
	readonly y0: number;
	readonly x1: number;
	readonly y1: number;
}

/** The legs of the L, T and C templates, overlapping where they meet; undefined for the others. */
function templateLegs(kind: TemplateKind, p: ITemplateParams): ILeg[] | undefined {
	const { b, h, t } = p;
	const tf = p.tf ?? t;
	const x0 = -b / 2, y0 = -h / 2, x1 = b / 2, y1 = h / 2;
	switch (kind) {
		case 'L': return [{ x0, y0, x1, y1: y0 + t }, { x0, y0, x1: x0 + t, y1 }];
		case 'T': return [{ x0, y0: y1 - tf, x1, y1 }, { x0: -t / 2, y0, x1: t / 2, y1 }];
		case 'C': return [{ x0, y0, x1: x0 + t, y1 }, { x0, y0, x1, y1: y0 + tf }, { x0, y0: y1 - tf, x1, y1 }];
		default: return undefined;
	}
}

/**
 * The bars of the L, T and C templates: each leg has a row on each of its two long faces,
 * `inset` from them, with the bars of the two rows in opposite pairs (so ties can cross the leg)
 * at no more than `spacing`. The rows of the other legs are stations of every leg, so the bars
 * at the corners and re-entrant corners are shared, and the spacing is even between them.
 * Undefined for the other templates (their bars go along the edges, see `barsAlongEdges`).
 */
export function templateBars(kind: TemplateKind, p: ITemplateParams, inset: number, dia: number, spacing: number): IBar[] | undefined {
	const legs = templateLegs(kind, p);
	if (!legs) {
		return undefined;
	}
	// The bar lines across each leg's thickness: one on each face, or one in the middle of a leg
	// too thin for two.
	const lines = (lo: number, hi: number) => hi - lo - 2 * inset >= dia ? [lo + inset, hi - inset] : [(lo + hi) / 2];
	const along = legs.map(leg => leg.x1 - leg.x0 >= leg.y1 - leg.y0);
	const bars: IBar[] = [];
	legs.forEach((leg, i) => {
		const [lo, hi, a0, a1] = along[i] ? [leg.y0, leg.y1, leg.x0, leg.x1] : [leg.x0, leg.x1, leg.y0, leg.y1];
		const [from, to] = [a0 + inset, a1 - inset];
		// Stations: the leg's ends and the bar lines of the legs across it, then evenly between.
		const fixed = [from, to, ...legs.flatMap((other, j) => j === i || along[j] === along[i] ? [] : along[j] ? lines(other.y0, other.y1) : lines(other.x0, other.x1))]
			.filter(s => s >= from - 1e-6 && s <= to + 1e-6)
			.sort((m, n) => m - n);
		const stations: number[] = [];
		fixed.forEach((s, k) => {
			const next = fixed[k + 1];
			stations.push(s);
			if (next !== undefined && next - s > 1e-6) {
				const n = Math.ceil((next - s) / spacing - 1e-9);
				for (let m = 1; m < n; m++) {
					stations.push(s + m * (next - s) / n);
				}
			}
		});
		for (const line of lines(lo, hi)) {
			for (const s of stations) {
				addBar(bars, along[i] ? { x: Math.round(s), y: Math.round(line), dia } : { x: Math.round(line), y: Math.round(s), dia });
			}
		}
	});
	return bars;
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

/**
 * The properties without the round-off of the analysis: a centroid or shear centre of a
 * symmetric section comes out as 1e-14 mm (a shear centre as 1e-5 mm, against a section hundreds
 * of mm across) and Ixy as 1e-4 mm⁴ (against 1e12); those are 0, and so is the principal angle then.
 */
export function cleanProperties(p: ISectionProperties): ISectionProperties {
	const size = Math.sqrt(Math.abs(p.area)) || 1;
	// The shear centre is solved numerically: its noise is far larger than the centroid's
	// (-15e-6 mm on a 600 mm L), yet still under a micrometre per metre of section.
	const coordinate = (v: number) => Math.abs(v) < 1e-6 * size ? 0 : v;
	const ixy = Math.abs(p.ixy) < 1e-6 * Math.sqrt(Math.abs(p.ixx * p.iyy)) ? 0 : p.ixy;
	return {
		...p,
		cx: coordinate(p.cx),
		cy: coordinate(p.cy),
		scx: coordinate(p.scx),
		scy: coordinate(p.scy),
		ixy,
		principalAngle: ixy === 0 && Math.abs(p.principalAngle) < 1e-6 ? 0 : p.principalAngle,
	};
}

/** The properties table: name, value and unit per row. */
export function propertyRows(properties: ISectionProperties): IPropertyRow[] {
	const p = cleanProperties(properties);
	const ixy = p.ixy;
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
