/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { findNodeAtLocation, Node, parseTree } from '../../../../base/common/json.js';
import { applyEdits, removeProperty, setProperty, withFormatting } from '../../../../base/common/jsonEdit.js';
import type { Edit, FormattingOptions } from '../../../../base/common/jsonFormatter.js';
import { distanceToSegment } from './floorPlanDrawing.js';
import type { CadPoint } from '@saengine/cad-editor';

/*
 * 2D drafting geometry (AutoCAD-like lines, polylines, arcs, circles) on the floor plan
 * (`05 Floor Plan/floor-plan.json`). Draft shapes belong to one story and are not structural members.
 */

export type DraftPoint = readonly [number, number];

/** Circle through three points, stored as the CCW arc that passes through the middle point. */
export function arcThroughPoints(a: DraftPoint, b: DraftPoint, c: DraftPoint): { readonly center: DraftPoint; readonly radius: number; readonly startAngle: number; readonly endAngle: number } | undefined {
	const d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]));
	if (Math.abs(d) < 1e-9) { return undefined; }
	const aa = a[0] * a[0] + a[1] * a[1], bb = b[0] * b[0] + b[1] * b[1], cc = c[0] * c[0] + c[1] * c[1];
	const center: DraftPoint = [(aa * (b[1] - c[1]) + bb * (c[1] - a[1]) + cc * (a[1] - b[1])) / d, (aa * (c[0] - b[0]) + bb * (a[0] - c[0]) + cc * (b[0] - a[0])) / d];
	const angle = (p: DraftPoint) => (Math.atan2(p[1] - center[1], p[0] - center[0]) * 180 / Math.PI + 360) % 360;
	const startAngle = angle(a), middleAngle = angle(b), end = angle(c);
	const ccw = (x: number, y: number) => (y - x + 360) % 360;
	const radius = Math.hypot(a[0] - center[0], a[1] - center[1]);
	// Stored arcs run counter-clockwise: when the points were picked clockwise, the same arc runs
	// counter-clockwise from the last point to the first.
	return ccw(startAngle, middleAngle) <= ccw(startAngle, end)
		? { center, radius, startAngle, endAngle: end }
		: { center, radius, startAngle: end, endAngle: startAngle };
}

/** Parses a typed draft point: absolute, relative, polar, or direct-distance along cursor direction. */
export function parseDraftPoint(text: string, last: DraftPoint, cursorDirection: DraftPoint): DraftPoint | undefined {
	const value = text.trim();
	const number = String.raw`[-+]?(?:\d+\.?\d*|\.\d+)`;
	const pair = new RegExp(String.raw`^(@)?\s*(${number})\s*[,;]\s*(${number})$`).exec(value);
	if (pair) { const x = Number(pair[2]), y = Number(pair[3]); return pair[1] ? [last[0] + x, last[1] + y] : [x, y]; }
	const polar = new RegExp(String.raw`^@\s*(${number})\s*<\s*(${number})$`).exec(value);
	if (polar) { const length = Number(polar[1]), angle = Number(polar[2]) * Math.PI / 180; return [last[0] + length * Math.cos(angle), last[1] + length * Math.sin(angle)]; }
	if (new RegExp(`^${number}$`).test(value)) {
		const length = Number(value), magnitude = Math.hypot(cursorDirection[0], cursorDirection[1]);
		if (!magnitude) { return undefined; }
		return [last[0] + length * cursorDirection[0] / magnitude, last[1] + length * cursorDirection[1] / magnitude];
	}
	return undefined;
}

export type DraftShapeKind = 'line' | 'polyline' | 'arc' | 'circle';

export interface IDraftBase {
	readonly id: string;
	readonly story: string;
	readonly layer?: string;
}

export interface IDraftLine extends IDraftBase {
	readonly kind: 'line';
	readonly start: DraftPoint;
	readonly end: DraftPoint;
}

export interface IDraftPolyline extends IDraftBase {
	readonly kind: 'polyline';
	readonly points: readonly DraftPoint[];
	readonly closed?: boolean;
}

export interface IDraftArc extends IDraftBase {
	readonly kind: 'arc';
	readonly center: DraftPoint;
	readonly radius: number;
	readonly startAngle: number;
	readonly endAngle: number;
}

export interface IDraftCircle extends IDraftBase {
	readonly kind: 'circle';
	readonly center: DraftPoint;
	readonly radius: number;
}

export type IDraftShape = IDraftLine | IDraftPolyline | IDraftArc | IDraftCircle;

/** A draft represented as line segments for window selection and crossing tests. */
export function draftSegments(shape: IDraftShape): readonly (readonly [CadPoint, CadPoint])[] {
	if (shape.kind === 'line') {
		return [[shape.start, shape.end]];
	}
	if (shape.kind === 'polyline') {
		const segments: [CadPoint, CadPoint][] = shape.points.slice(1).map((point, i) => [shape.points[i], point]);
		if (shape.closed) {
			segments.push([shape.points[shape.points.length - 1], shape.points[0]]);
		}
		return segments;
	}
	const points: CadPoint[] = [];
	const start = shape.kind === 'arc' ? shape.startAngle : 0;
	const sweep = shape.kind === 'arc' ? normalizedSweep(shape.startAngle, shape.endAngle) : 360;
	const count = Math.max(8, Math.ceil(sweep / 5));
	for (let i = 0; i <= count; i++) {
		const angle = (start + sweep * i / count) * Math.PI / 180;
		points.push([shape.center[0] + Math.cos(angle) * shape.radius, shape.center[1] + Math.sin(angle) * shape.radius]);
	}
	return points.slice(1).map((point, i) => [points[i], point]);
}

function normalizedSweep(start: number, end: number): number {
	return ((end - start) % 360 + 360) % 360;
}

/** Distance from a point to a draft curve. */
export function distanceToDraft(shape: IDraftShape, point: CadPoint): number {
	if (shape.kind === 'circle') {
		return Math.abs(Math.hypot(point[0] - shape.center[0], point[1] - shape.center[1]) - shape.radius);
	}
	if (shape.kind === 'arc') {
		const angle = Math.atan2(point[1] - shape.center[1], point[0] - shape.center[0]) * 180 / Math.PI;
		const sweep = normalizedSweep(shape.startAngle, shape.endAngle);
		const offset = normalizedSweep(shape.startAngle, angle);
		if (offset <= sweep) {
			return Math.abs(Math.hypot(point[0] - shape.center[0], point[1] - shape.center[1]) - shape.radius);
		}
		const start = shape.startAngle * Math.PI / 180;
		const end = shape.endAngle * Math.PI / 180;
		const endpoints = [[shape.center[0] + Math.cos(start) * shape.radius, shape.center[1] + Math.sin(start) * shape.radius] as CadPoint, [shape.center[0] + Math.cos(end) * shape.radius, shape.center[1] + Math.sin(end) * shape.radius] as CadPoint];
		return Math.min(...endpoints.map(p => Math.hypot(point[0] - p[0], point[1] - p[1])));
	}
	return Math.min(...draftSegments(shape).map(([a, b]) => distanceToSegment(point, a, b)));
}

/** Drafts within the given pick tolerance, nearest first (ties retain input order). */
export function pickDraft(shapes: readonly IDraftShape[], point: CadPoint, tolerance: number): IDraftShape | undefined {
	return shapes.map(shape => ({ shape, distance: distanceToDraft(shape, point) }))
		.filter(hit => hit.distance <= tolerance)
		.sort((a, b) => a.distance - b.distance)[0]?.shape;
}

/** Whether a draft is fully within a window or touches a crossing window. */
export function draftInWindow(shape: IDraftShape, min: CadPoint, max: CadPoint, crossing: boolean): boolean {
	const inside = ([x, y]: CadPoint) => min[0] <= x && x <= max[0] && min[1] <= y && y <= max[1];
	const segments = draftSegments(shape);
	if (!crossing) {
		if (shape.kind === 'circle') {
			return inside([shape.center[0] - shape.radius, shape.center[1] - shape.radius]) && inside([shape.center[0] + shape.radius, shape.center[1] + shape.radius]);
		}
		if (shape.kind === 'arc') {
			return inside([shape.center[0] - shape.radius, shape.center[1] - shape.radius]) && inside([shape.center[0] + shape.radius, shape.center[1] + shape.radius]);
		}
		return segments.every(([a, b]) => inside(a) && inside(b));
	}
	const intersects = (a: CadPoint, b: CadPoint, c: CadPoint, d: CadPoint) => {
		const cross = (p: CadPoint, q: CadPoint, r: CadPoint) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
		const abC = cross(a, b, c), abD = cross(a, b, d), cdA = cross(c, d, a), cdB = cross(c, d, b);
		return Math.min(a[0], b[0]) <= Math.max(c[0], d[0]) && Math.min(c[0], d[0]) <= Math.max(a[0], b[0])
			&& Math.min(a[1], b[1]) <= Math.max(c[1], d[1]) && Math.min(c[1], d[1]) <= Math.max(a[1], b[1])
			&& abC * abD <= 0 && cdA * cdB <= 0;
	};
	const corners: CadPoint[] = [min, [max[0], min[1]], max, [min[0], max[1]]];
	return segments.some(([a, b]) => inside(a) || inside(b) || corners.some((c, i) => intersects(a, b, c, corners[(i + 1) % 4])));
}

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoint(value: unknown): value is DraftPoint {
	return Array.isArray(value)
		&& value.length === 2
		&& typeof value[0] === 'number' && Number.isFinite(value[0])
		&& typeof value[1] === 'number' && Number.isFinite(value[1]);
}

/**
 * Reads 2D drafting geometry loosely from `layout`, optionally filtered to `storyId`.
 * Malformed entries (non-finite coordinates, invalid shape parameters, missing required fields) are skipped.
 */
export function draftsOf(layout: unknown, storyId?: string): IDraftShape[] {
	if (!isObject(layout) || !Array.isArray(layout.drafting)) {
		return [];
	}
	const result: IDraftShape[] = [];
	for (const item of layout.drafting) {
		if (!isObject(item)) {
			continue;
		}
		if (typeof item.id !== 'string' || !item.id) {
			continue;
		}
		if (typeof item.story !== 'string' || !item.story) {
			continue;
		}
		if (storyId !== undefined && item.story !== storyId) {
			continue;
		}
		const layer = typeof item.layer === 'string' && item.layer ? item.layer : 'DRAFT';
		switch (item.kind) {
			case 'line': {
				if (isPoint(item.start) && isPoint(item.end)) {
					result.push({
						kind: 'line',
						id: item.id,
						story: item.story,
						layer,
						start: [item.start[0], item.start[1]],
						end: [item.end[0], item.end[1]],
					});
				}
				break;
			}
			case 'polyline': {
				if (Array.isArray(item.points)) {
					const pts: DraftPoint[] = [];
					let allValid = true;
					for (const p of item.points) {
						if (isPoint(p)) {
							pts.push([p[0], p[1]]);
						} else {
							allValid = false;
							break;
						}
					}
					if (!allValid || pts.length < 2) {
						break;
					}
					const closed = Boolean(item.closed);
					if (closed && pts.length < 3) {
						break;
					}
					result.push({
						kind: 'polyline',
						id: item.id,
						story: item.story,
						layer,
						points: pts,
						closed,
					});
				}
				break;
			}
			case 'arc': {
				if (
					isPoint(item.center)
					&& typeof item.radius === 'number' && Number.isFinite(item.radius) && item.radius > 0
					&& typeof item.startAngle === 'number' && Number.isFinite(item.startAngle)
					&& typeof item.endAngle === 'number' && Number.isFinite(item.endAngle)
				) {
					result.push({
						kind: 'arc',
						id: item.id,
						story: item.story,
						layer,
						center: [item.center[0], item.center[1]],
						radius: item.radius,
						startAngle: item.startAngle,
						endAngle: item.endAngle,
					});
				}
				break;
			}
			case 'circle': {
				if (
					isPoint(item.center)
					&& typeof item.radius === 'number' && Number.isFinite(item.radius) && item.radius > 0
				) {
					result.push({
						kind: 'circle',
						id: item.id,
						story: item.story,
						layer,
						center: [item.center[0], item.center[1]],
						radius: item.radius,
					});
				}
				break;
			}
		}
	}
	return result;
}

const MEMBER_GROUPS = ['columns', 'beams', 'walls', 'slabs', 'footings', 'towers'] as const;

/**
 * Returns the next free draft id ("D1", "D2", ...) not clashing with existing drafts or member ids.
 */
export function nextDraftId(layout: unknown): string {
	const used = new Set<string>();
	if (isObject(layout)) {
		for (const group of MEMBER_GROUPS) {
			const list = layout[group];
			if (Array.isArray(list)) {
				for (const item of list) {
					if (isObject(item) && typeof item.id === 'string') {
						used.add(item.id);
					}
				}
			}
		}
		if (Array.isArray(layout.drafting)) {
			for (const item of layout.drafting) {
				if (isObject(item) && typeof item.id === 'string') {
					used.add(item.id);
				}
			}
		}
	}
	let n = 1;
	while (used.has(`D${n}`)) {
		n++;
	}
	return `D${n}`;
}

function guessFormattingOptions(text: string, override?: FormattingOptions): FormattingOptions {
	const eol = override?.eol ?? (text.includes('\r\n') ? '\r\n' : '\n');
	const insertSpaces = override?.insertSpaces ?? (!text.includes('\t'));
	const tabSize = override?.tabSize ?? (insertSpaces ? 2 : 4);
	return { tabSize, insertSpaces, eol };
}

function findDraftIndex(draftingNode: Node, id: string): number {
	if (!Array.isArray(draftingNode.children)) {
		return -1;
	}
	for (let i = 0; i < draftingNode.children.length; i++) {
		const child = draftingNode.children[i];
		const idNode = findNodeAtLocation(child, ['id']);
		if (idNode && idNode.value === id) {
			return i;
		}
	}
	return -1;
}

/**
 * Produces minimal JSON text edits for adding a draft shape to `floor-plan.json`.
 */
export function addDraftEdit(jsonText: string, draft: IDraftShape, options?: FormattingOptions): Edit[] {
	const formattingOptions = guessFormattingOptions(jsonText, options);
	const root = parseTree(jsonText);
	if (!root) {
		return [];
	}
	const draftingNode = findNodeAtLocation(root, ['drafting']);
	if (!draftingNode || draftingNode.type !== 'array') {
		return setProperty(jsonText, ['drafting'], [draft], formattingOptions);
	}
	return setProperty(jsonText, ['drafting', -1], draft, formattingOptions);
}

/**
 * Returns the new JSON text with `draft` appended to the floor plan's drafting array.
 */
export function addDraft(jsonText: string, draft: IDraftShape, options?: FormattingOptions): string {
	const edits = addDraftEdit(jsonText, draft, options);
	return edits.length > 0 ? applyEdits(jsonText, edits) : jsonText;
}

/**
 * Produces minimal JSON text edits for removing draft `id` from `floor-plan.json`.
 */
export function removeDraftEdit(jsonText: string, id: string, options?: FormattingOptions): Edit[] {
	const formattingOptions = guessFormattingOptions(jsonText, options);
	const root = parseTree(jsonText);
	if (!root) {
		return [];
	}
	const draftingNode = findNodeAtLocation(root, ['drafting']);
	if (!draftingNode || draftingNode.type !== 'array') {
		return [];
	}
	const index = findDraftIndex(draftingNode, id);
	if (index < 0) {
		return [];
	}
	return removeProperty(jsonText, ['drafting', index], formattingOptions);
}

/**
 * Returns the new JSON text without draft `id`.
 */
export function removeDraft(jsonText: string, id: string, options?: FormattingOptions): string {
	const edits = removeDraftEdit(jsonText, id, options);
	return edits.length > 0 ? applyEdits(jsonText, edits) : jsonText;
}

/**
 * Produces minimal JSON text edits for replacing an existing draft shape in `floor-plan.json`.
 */
export function replaceDraftEdit(jsonText: string, draft: IDraftShape, options?: FormattingOptions): Edit[] {
	const formattingOptions = guessFormattingOptions(jsonText, options);
	const root = parseTree(jsonText);
	if (!root) {
		return [];
	}
	const draftingNode = findNodeAtLocation(root, ['drafting']);
	if (!draftingNode || draftingNode.type !== 'array' || !Array.isArray(draftingNode.children)) {
		return [];
	}
	const index = findDraftIndex(draftingNode, draft.id);
	if (index < 0) {
		return [];
	}
	const targetNode = draftingNode.children[index];
	const content = JSON.stringify(draft);
	return withFormatting(jsonText, { offset: targetNode.offset, length: targetNode.length, content }, formattingOptions);
}

/**
 * Returns the new JSON text with the existing draft matching `draft.id` replaced.
 */
export function replaceDraft(jsonText: string, draft: IDraftShape, options?: FormattingOptions): string {
	const edits = replaceDraftEdit(jsonText, draft, options);
	return edits.length > 0 ? applyEdits(jsonText, edits) : jsonText;
}

/**
 * Closed sequence of four corners for an axis-aligned rectangle from two opposite corners `a` and `b`.
 */
export function rectangleFromCorners(a: DraftPoint, b: DraftPoint): DraftPoint[] {
	return [
		[a[0], a[1]],
		[b[0], a[1]],
		[b[0], b[1]],
		[a[0], b[1]],
	];
}

/**
 * Vertices of a regular polygon with `sides` equal edges centered at `center`,
 * starting at and passing through `vertex`.
 */
export function regularPolygon(center: DraftPoint, vertex: DraftPoint, sides: number): DraftPoint[] {
	if (sides < 3) {
		return [];
	}
	const [cx, cy] = center;
	const [vx, vy] = vertex;
	const radius = Math.hypot(vx - cx, vy - cy);
	if (radius === 0) {
		return [];
	}
	const startAngle = Math.atan2(vy - cy, vx - cx);
	const step = (2 * Math.PI) / sides;
	const points: DraftPoint[] = [];
	const round = (v: number) => Math.round(v * 1000) / 1000 || 0;
	for (let i = 0; i < sides; i++) {
		if (i === 0) {
			points.push([round(vx), round(vy)]);
		} else {
			const angle = startAngle + i * step;
			points.push([
				round(cx + radius * Math.cos(angle)),
				round(cy + radius * Math.sin(angle)),
			]);
		}
	}
	return points;
}

// ───────────────────────────── modify operations ─────────────────────────────

export interface IDraftBulkResult {
	readonly layout: Record<string, unknown>;
	readonly ids: readonly string[];
	readonly placed: number;
	readonly skipped: number;
	readonly count: number;
}

function cloneLayout(layout: unknown): Record<string, unknown> {
	return JSON.parse(JSON.stringify(isObject(layout) ? layout : {})) as Record<string, unknown>;
}

function roundCoord(v: number): number {
	const r = Math.round(v * 1000) / 1000;
	return r === 0 ? 0 : r;
}

const cross = (a: DraftPoint, b: DraftPoint) => a[0] * b[1] - a[1] * b[0];
const sub = (a: DraftPoint, b: DraftPoint): DraftPoint => [a[0] - b[0], a[1] - b[1]];
const add = (a: DraftPoint, b: DraftPoint): DraftPoint => [a[0] + b[0], a[1] + b[1]];
const mul = (a: DraftPoint, n: number): DraftPoint => [a[0] * n, a[1] * n];
function lineIntersection(p: DraftPoint, r: DraftPoint, q: DraftPoint, s: DraftPoint): DraftPoint | undefined {
	const d = cross(r, s);
	if (Math.abs(d) < 1e-9) { return undefined; }
	return add(p, mul(r, cross(sub(q, p), s) / d));
}
function lineHits(line: IDraftLine, shape: IDraftShape): { point: DraftPoint; t: number }[] {
	const p = line.start, v = sub(line.end, line.start), vv = v[0] * v[0] + v[1] * v[1];
	if (!vv) { return []; }
	const hits: DraftPoint[] = [];
	const segmentHit = (a: DraftPoint, b: DraftPoint) => {
		const w = sub(b, a), den = cross(v, w);
		if (Math.abs(den) < 1e-9) { return; }
		const t = cross(sub(a, p), w) / den, u = cross(sub(a, p), v) / den;
		if (t >= -1e-9 && t <= 1 + 1e-9 && u >= -1e-9 && u <= 1 + 1e-9) { hits.push(add(p, mul(v, t))); }
	};
	if (shape.kind === 'line') { segmentHit(shape.start, shape.end); }
	else if (shape.kind === 'polyline') { draftSegments(shape).forEach(([a, b]) => segmentHit(a, b)); }
	else {
		const d = sub(p, shape.center), b = 2 * (d[0] * v[0] + d[1] * v[1]), c = d[0] * d[0] + d[1] * d[1] - shape.radius * shape.radius;
		const disc = b * b - 4 * vv * c;
		if (disc >= -1e-8) {
			for (const t of disc <= 1e-8 ? [-b / (2 * vv)] : [(-b - Math.sqrt(disc)) / (2 * vv), (-b + Math.sqrt(disc)) / (2 * vv)]) {
				if (t < -1e-9 || t > 1 + 1e-9) { continue; }
				const hit = add(p, mul(v, t));
				if (shape.kind === 'circle' || normalizedSweep(shape.startAngle, Math.atan2(hit[1] - shape.center[1], hit[0] - shape.center[0]) * 180 / Math.PI) <= normalizedSweep(shape.startAngle, shape.endAngle) + 1e-8) { hits.push(hit); }
			}
		}
	}
	return hits.map(point => ({ point, t: ((point[0] - p[0]) * v[0] + (point[1] - p[1]) * v[1]) / vv }));
}

/** Offset a draft to the side indicated by `sidePoint`; polyline corners use mitres. */
export function offsetDraft(shape: IDraftShape, distance: number, sidePoint: DraftPoint): IDraftShape | undefined {
	if (!Number.isFinite(distance) || distance < 0) { return undefined; }
	if (shape.kind === 'line') {
		const v = sub(shape.end, shape.start), len = Math.hypot(v[0], v[1]); if (!len) { return undefined; }
		const n: DraftPoint = [-v[1] / len, v[0] / len], sign = (sidePoint[0] - shape.start[0]) * n[0] + (sidePoint[1] - shape.start[1]) * n[1] < 0 ? -1 : 1;
		return { ...shape, start: [roundCoord(shape.start[0] + sign * distance * n[0]), roundCoord(shape.start[1] + sign * distance * n[1])], end: [roundCoord(shape.end[0] + sign * distance * n[0]), roundCoord(shape.end[1] + sign * distance * n[1])] };
	}
	if (shape.kind === 'circle' || shape.kind === 'arc') {
		const radial = Math.hypot(sidePoint[0] - shape.center[0], sidePoint[1] - shape.center[1]);
		const radius = shape.radius + (radial >= shape.radius ? distance : -distance);
		return radius > 0 ? { ...shape, radius: roundCoord(radius) } : undefined;
	}
	const pts = shape.points, closed = !!shape.closed, area = pts.reduce((sum, p, i) => { const q = pts[(i + 1) % pts.length]; return sum + p[0] * q[1] - q[0] * p[1]; }, 0);
	let inward = false;
	if (closed) {
		let inside = false;
		for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
			const a = pts[i], b = pts[j];
			if ((a[1] > sidePoint[1]) !== (b[1] > sidePoint[1]) && sidePoint[0] < (b[0] - a[0]) * (sidePoint[1] - a[1]) / (b[1] - a[1]) + a[0]) { inside = !inside; }
		}
		inward = inside;
		if (inward && pts.length === 4 && Math.abs(distance) * 2 >= Math.min(Math.max(...pts.map(p => p[0])) - Math.min(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1])) - Math.min(...pts.map(p => p[1])))) { return undefined; }
	}
	const segCount = closed ? pts.length : pts.length - 1;
	const offsets: { p: DraftPoint; v: DraftPoint }[] = [];
	for (let i = 0; i < segCount; i++) {
		const a = pts[i], b = pts[(i + 1) % pts.length], d = sub(b, a), len = Math.hypot(d[0], d[1]); if (!len) { return undefined; }
		let n: DraftPoint = [-d[1] / len, d[0] / len];
		if (closed && ((area > 0) !== inward)) { n = mul(n, -1); }
		else { const mid: DraftPoint = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; if ((sidePoint[0] - mid[0]) * n[0] + (sidePoint[1] - mid[1]) * n[1] < 0) { n = mul(n, -1); } }
		offsets.push({ p: add(a, mul(n, distance)), v: d });
	}
	const result: DraftPoint[] = [];
	for (let i = 0; i < pts.length; i++) {
		if (!closed && i === 0) { result.push(offsets[0].p); continue; }
		if (!closed && i === pts.length - 1) { result.push(add(offsets[offsets.length - 1].p, offsets[offsets.length - 1].v)); continue; }
		const before = offsets[(i - 1 + segCount) % segCount], after = offsets[i % segCount];
		result.push(lineIntersection(before.p, before.v, after.p, after.v) ?? after.p);
	}
	return { ...shape, points: result.map(p => [roundCoord(p[0]), roundCoord(p[1])]) };
}

/** Remove the picked interval of a line; no hits removes the whole line. */
export function trimLine(line: IDraftLine, cutters: readonly IDraftShape[], pickPoint: DraftPoint): IDraftLine[] {
	const hits = cutters.flatMap(c => lineHits(line, c)).map(h => h.t).filter(t => t > 1e-8 && t < 1 - 1e-8).sort((a, b) => a - b).filter((t, i, a) => !i || Math.abs(t - a[i - 1]) > 1e-7);
	if (!hits.length) { return []; }
	const v = sub(line.end, line.start), vv = v[0] * v[0] + v[1] * v[1], t = Math.max(0, Math.min(1, ((pickPoint[0] - line.start[0]) * v[0] + (pickPoint[1] - line.start[1]) * v[1]) / vv));
	const left = [...hits].reverse().find(h => h < t), right = hits.find(h => h > t);
	const lo = left ?? 0, hi = right ?? 1;
	const point = (n: number): DraftPoint => [roundCoord(line.start[0] + n * v[0]), roundCoord(line.start[1] + n * v[1])];
	const out: IDraftLine[] = [];
	if (lo > 1e-8) { out.push({ ...line, end: point(lo) }); }
	if (hi < 1 - 1e-8) { out.push({ ...line, id: out.length ? `${line.id}_trim` : line.id, start: point(hi) }); }
	return out;
}

/** Extend the end nearest the pick point to the nearest boundary intersection. */
export function extendLine(line: IDraftLine, boundaries: readonly IDraftShape[], pickPoint: DraftPoint): IDraftLine | undefined {
	const fromStart = Math.hypot(pickPoint[0] - line.start[0], pickPoint[1] - line.start[1]) < Math.hypot(pickPoint[0] - line.end[0], pickPoint[1] - line.end[1]);
	const origin = fromStart ? line.start : line.end, other = fromStart ? line.end : line.start, v = sub(origin, other), len2 = v[0] * v[0] + v[1] * v[1];
	if (!len2) { return undefined; }
	const ray: IDraftLine = { ...line, start: origin, end: add(origin, mul(v, 1e6)) };
	const hit = boundaries.flatMap(b => lineHits(ray, b)).filter(h => h.t > 1e-8).sort((a, b) => a.t - b.t)[0];
	if (!hit) { return undefined; }
	const end: DraftPoint = [roundCoord(hit.point[0]), roundCoord(hit.point[1])];
	return fromStart ? { ...line, start: end } : { ...line, end: end };
}

/** Fillet two finite lines, preserving each picked side. */
export function filletLines(l1: IDraftLine, l2: IDraftLine, radius: number, pick1: DraftPoint, pick2: DraftPoint): { readonly lines: readonly [IDraftLine, IDraftLine]; readonly arc?: IDraftArc } | undefined {
	const v1 = sub(l1.end, l1.start), v2 = sub(l2.end, l2.start), corner = lineIntersection(l1.start, v1, l2.start, v2);
	if (!corner || radius < 0) { return undefined; }
	const dot = (a: DraftPoint, b: DraftPoint) => a[0] * b[0] + a[1] * b[1];
	// AutoCAD: each line keeps its end on the picked side of the corner; the other end moves to
	// the corner (radius 0) or to the arc's tangent point.
	const side = (line: IDraftLine, pick: DraftPoint) => {
		const along = sub(line.end, line.start), length = Math.hypot(along[0], along[1]);
		if (!length) { return undefined; }
		const unit: DraftPoint = [along[0] / length, along[1] / length];
		const sign = Math.sign(dot(sub(pick, corner), unit));
		if (!sign) { return undefined; }
		const w: DraftPoint = [unit[0] * sign, unit[1] * sign];
		const keepEnd = dot(sub(line.end, corner), w) >= dot(sub(line.start, corner), w);
		const reach = dot(sub(keepEnd ? line.end : line.start, corner), w);
		return reach > 0 ? { w, keepEnd, reach } : undefined;
	};
	const s1 = side(l1, pick1), s2 = side(l2, pick2);
	if (!s1 || !s2) { return undefined; }
	const theta = Math.acos(Math.max(-1, Math.min(1, dot(s1.w, s2.w))));
	if (theta < 1e-6 || Math.PI - theta < 1e-6) { return undefined; }
	const moved = (line: IDraftLine, at: { readonly keepEnd: boolean }, point: DraftPoint): IDraftLine => at.keepEnd ? { ...line, start: point } : { ...line, end: point };
	if (!radius) {
		const p: DraftPoint = [roundCoord(corner[0]), roundCoord(corner[1])];
		return { lines: [moved(l1, s1, p), moved(l2, s2, p)] };
	}
	const d = radius / Math.tan(theta / 2);
	if (d > s1.reach + 1e-9 || d > s2.reach + 1e-9) { return undefined; }
	const tangent = (w: DraftPoint): DraftPoint => [roundCoord(corner[0] + w[0] * d), roundCoord(corner[1] + w[1] * d)];
	const t1 = tangent(s1.w), t2 = tangent(s2.w);
	const bis: DraftPoint = [s1.w[0] + s2.w[0], s1.w[1] + s2.w[1]], bl = Math.hypot(bis[0], bis[1]), h = radius / Math.sin(theta / 2);
	const center: DraftPoint = [roundCoord(corner[0] + bis[0] / bl * h), roundCoord(corner[1] + bis[1] / bl * h)];
	const angle = (p: DraftPoint) => normalizeAngle(Math.atan2(p[1] - center[1], p[0] - center[0]) * 180 / Math.PI);
	const a1 = angle(t1), a2 = angle(t2), ccw = normalizedSweep(a1, a2);
	// The fillet arc spans less than 180°: stored counter-clockwise from whichever end that makes it.
	const arc: IDraftArc = { kind: 'arc', id: `${l1.id}_fillet`, story: l1.story, layer: l1.layer, center, radius: roundCoord(radius), startAngle: ccw < 180 ? a1 : a2, endAngle: ccw < 180 ? a2 : a1 };
	return { lines: [moved(l1, s1, t1), moved(l2, s2, t2)], arc };
}

function normalizeAngle(degrees: number): number {
	const a = Number((((degrees % 360) + 360) % 360).toFixed(3));
	return a === 360 ? 0 : a;
}

/**
 * Axis-aligned bounding box of draft shapes.
 */
export function draftBounds(shapes: readonly IDraftShape[]): { readonly min: DraftPoint; readonly max: DraftPoint } | undefined {
	if (!shapes.length) {
		return undefined;
	}
	let minX = Infinity;
	let minY = Infinity;
	let maxX = -Infinity;
	let maxY = -Infinity;
	const include = ([x, y]: DraftPoint | CadPoint) => {
		if (x < minX) { minX = x; }
		if (x > maxX) { maxX = x; }
		if (y < minY) { minY = y; }
		if (y > maxY) { maxY = y; }
	};
	for (const shape of shapes) {
		switch (shape.kind) {
			case 'line':
				include(shape.start);
				include(shape.end);
				break;
			case 'polyline':
				for (const pt of shape.points) {
					include(pt);
				}
				break;
			case 'circle':
				include([shape.center[0] - shape.radius, shape.center[1] - shape.radius]);
				include([shape.center[0] + shape.radius, shape.center[1] + shape.radius]);
				break;
			case 'arc':
				for (const [a, b] of draftSegments(shape)) {
					include(a);
					include(b);
				}
				break;
		}
	}
	if (!Number.isFinite(minX)) {
		return undefined;
	}
	return { min: [minX, minY], max: [maxX, maxY] };
}

/**
 * Geometric center of draft shapes' bounding box.
 */
export function draftBoundsCenter(shapes: readonly IDraftShape[]): DraftPoint {
	const b = draftBounds(shapes);
	if (!b) {
		return [0, 0];
	}
	return [roundCoord((b.min[0] + b.max[0]) / 2), roundCoord((b.min[1] + b.max[1]) / 2)];
}

/**
 * Moves the selected drafts by `delta`. Does not mutate input `layout`.
 */
export function moveDrafts(layout: unknown, ids: Iterable<string>, delta: DraftPoint): IDraftBulkResult {
	const next = cloneLayout(layout);
	const targetIds = new Set(ids);
	if (!targetIds.size || !Array.isArray(next.drafting)) {
		return { layout: next, ids: [], placed: 0, skipped: targetIds.size, count: 0 };
	}
	const movedIds: string[] = [];
	next.drafting = next.drafting.map(item => {
		if (!isObject(item) || typeof item.id !== 'string' || !targetIds.has(item.id)) {
			return item;
		}
		movedIds.push(item.id);
		const moved = { ...item };
		switch (item.kind) {
			case 'line':
				if (isPoint(item.start) && isPoint(item.end)) {
					moved.start = [roundCoord(item.start[0] + delta[0]), roundCoord(item.start[1] + delta[1])];
					moved.end = [roundCoord(item.end[0] + delta[0]), roundCoord(item.end[1] + delta[1])];
				}
				break;
			case 'polyline':
				if (Array.isArray(item.points)) {
					moved.points = item.points.map(p => isPoint(p) ? [roundCoord(p[0] + delta[0]), roundCoord(p[1] + delta[1])] : p);
				}
				break;
			case 'arc':
				if (isPoint(item.center)) {
					moved.center = [roundCoord(item.center[0] + delta[0]), roundCoord(item.center[1] + delta[1])];
				}
				break;
			case 'circle':
				if (isPoint(item.center)) {
					moved.center = [roundCoord(item.center[0] + delta[0]), roundCoord(item.center[1] + delta[1])];
				}
				break;
		}
		return moved;
	});
	return {
		layout: next,
		ids: movedIds,
		placed: movedIds.length,
		skipped: targetIds.size - movedIds.length,
		count: movedIds.length,
	};
}

/**
 * Copies the selected drafts `times` times, each copy shifted by `k * delta`.
 * New ids are allocated avoiding clashes with existing drafts and members. Does not mutate input `layout`.
 */
export function copyDrafts(layout: unknown, ids: Iterable<string>, delta: DraftPoint, times = 1, nextId?: (layout: unknown) => string): IDraftBulkResult {
	const next = cloneLayout(layout);
	const targetIds = new Set(ids);
	if (!targetIds.size || times < 1) {
		return { layout: next, ids: [], placed: 0, skipped: targetIds.size, count: 0 };
	}
	if (!Array.isArray(next.drafting)) {
		next.drafting = [];
	}
	const getNextId = nextId ?? nextDraftId;
	const originalItems = (next.drafting as unknown[])
		.filter((item): item is Record<string, unknown> => isObject(item) && typeof item.id === 'string' && targetIds.has(item.id));

	const createdIds: string[] = [];
	for (let k = 1; k <= times; k++) {
		const stepDelta: DraftPoint = [k * delta[0], k * delta[1]];
		for (const item of originalItems) {
			const newId = getNextId(next);
			createdIds.push(newId);
			const copy: Record<string, unknown> = { ...JSON.parse(JSON.stringify(item)), id: newId };
			switch (copy.kind) {
				case 'line':
					if (isPoint(copy.start) && isPoint(copy.end)) {
						copy.start = [roundCoord(copy.start[0] + stepDelta[0]), roundCoord(copy.start[1] + stepDelta[1])];
						copy.end = [roundCoord(copy.end[0] + stepDelta[0]), roundCoord(copy.end[1] + stepDelta[1])];
					}
					break;
				case 'polyline':
					if (Array.isArray(copy.points)) {
						copy.points = copy.points.map(p => isPoint(p) ? [roundCoord(p[0] + stepDelta[0]), roundCoord(p[1] + stepDelta[1])] : p);
					}
					break;
				case 'arc':
					if (isPoint(copy.center)) {
						copy.center = [roundCoord(copy.center[0] + stepDelta[0]), roundCoord(copy.center[1] + stepDelta[1])];
					}
					break;
				case 'circle':
					if (isPoint(copy.center)) {
						copy.center = [roundCoord(copy.center[0] + stepDelta[0]), roundCoord(copy.center[1] + stepDelta[1])];
					}
					break;
			}
			(next.drafting as unknown[]).push(copy);
		}
	}
	return {
		layout: next,
		ids: createdIds,
		placed: createdIds.length,
		skipped: targetIds.size - originalItems.length,
		count: createdIds.length,
	};
}

/**
 * Rotates the selected drafts by `degrees` about `centre` (or the bounding box center of the selected drafts if omitted).
 * Does not mutate input `layout`.
 */
export function rotateDrafts(layout: unknown, ids: Iterable<string>, degrees: number, centre?: DraftPoint): IDraftBulkResult {
	const next = cloneLayout(layout);
	const targetIds = new Set(ids);
	if (!targetIds.size || !Array.isArray(next.drafting)) {
		return { layout: next, ids: [], placed: 0, skipped: targetIds.size, count: 0 };
	}
	const shapes = draftsOf(next).filter(s => targetIds.has(s.id));
	const center = centre ?? draftBoundsCenter(shapes);
	const rad = degrees * Math.PI / 180;
	const cos = Math.cos(rad);
	const sin = Math.sin(rad);

	const rotatePt = ([x, y]: DraftPoint): DraftPoint => {
		const dx = x - center[0];
		const dy = y - center[1];
		return [
			roundCoord(center[0] + dx * cos - dy * sin),
			roundCoord(center[1] + dx * sin + dy * cos),
		];
	};

	const rotatedIds: string[] = [];
	next.drafting = next.drafting.map(item => {
		if (!isObject(item) || typeof item.id !== 'string' || !targetIds.has(item.id)) {
			return item;
		}
		rotatedIds.push(item.id);
		const rotated = { ...item };
		switch (item.kind) {
			case 'line':
				if (isPoint(item.start) && isPoint(item.end)) {
					rotated.start = rotatePt(item.start);
					rotated.end = rotatePt(item.end);
				}
				break;
			case 'polyline':
				if (Array.isArray(item.points)) {
					rotated.points = item.points.map(p => isPoint(p) ? rotatePt(p) : p);
				}
				break;
			case 'arc':
				if (isPoint(item.center) && typeof item.startAngle === 'number' && typeof item.endAngle === 'number') {
					rotated.center = rotatePt(item.center);
					rotated.startAngle = normalizeAngle(item.startAngle + degrees);
					rotated.endAngle = normalizeAngle(item.endAngle + degrees);
				}
				break;
			case 'circle':
				if (isPoint(item.center)) {
					rotated.center = rotatePt(item.center);
				}
				break;
		}
		return rotated;
	});
	return {
		layout: next,
		ids: rotatedIds,
		placed: rotatedIds.length,
		skipped: targetIds.size - rotatedIds.length,
		count: rotatedIds.length,
	};
}

/**
 * Mirrors the selected drafts about axis `axis` ('x' for vertical grid line at x=coordinate, 'y' for horizontal at y=coordinate).
 * If `keep` is false, originals are replaced in place; if true (default), original drafts stay and new mirrored copies are created.
 * Arcs have their angles reflected and start/end angles swapped to maintain CCW orientation.
 * Does not mutate input `layout`.
 */
export function mirrorDrafts(layout: unknown, ids: Iterable<string>, axis: 'x' | 'y', coordinate: number, keep = true): IDraftBulkResult {
	const next = cloneLayout(layout);
	const targetIds = new Set(ids);
	if (!targetIds.size) {
		return { layout: next, ids: [], placed: 0, skipped: 0, count: 0 };
	}
	if (!Array.isArray(next.drafting)) {
		next.drafting = [];
	}

	const mapPt = ([x, y]: DraftPoint): DraftPoint => {
		return axis === 'x'
			? [roundCoord(2 * coordinate - x), roundCoord(y)]
			: [roundCoord(x), roundCoord(2 * coordinate - y)];
	};

	const mirrorArcAngles = (startAngle: number, endAngle: number): { readonly startAngle: number; readonly endAngle: number } => {
		if (axis === 'x') {
			return {
				startAngle: normalizeAngle(180 - endAngle),
				endAngle: normalizeAngle(180 - startAngle),
			};
		} else {
			return {
				startAngle: normalizeAngle(-endAngle),
				endAngle: normalizeAngle(-startAngle),
			};
		}
	};

	const transformShape = (item: Record<string, unknown>, newId?: string): Record<string, unknown> => {
		const result: Record<string, unknown> = { ...JSON.parse(JSON.stringify(item)) };
		if (newId) {
			result.id = newId;
		}
		switch (result.kind) {
			case 'line':
				if (isPoint(result.start) && isPoint(result.end)) {
					result.start = mapPt(result.start);
					result.end = mapPt(result.end);
				}
				break;
			case 'polyline':
				if (Array.isArray(result.points)) {
					result.points = result.points.map(p => isPoint(p) ? mapPt(p) : p);
				}
				break;
			case 'arc':
				if (isPoint(result.center) && typeof result.startAngle === 'number' && typeof result.endAngle === 'number') {
					result.center = mapPt(result.center);
					const angles = mirrorArcAngles(result.startAngle, result.endAngle);
					result.startAngle = angles.startAngle;
					result.endAngle = angles.endAngle;
				}
				break;
			case 'circle':
				if (isPoint(result.center)) {
					result.center = mapPt(result.center);
				}
				break;
		}
		return result;
	};

	if (!keep) {
		const replacedIds: string[] = [];
		next.drafting = (next.drafting as unknown[]).map(item => {
			if (!isObject(item) || typeof item.id !== 'string' || !targetIds.has(item.id)) {
				return item;
			}
			replacedIds.push(item.id);
			return transformShape(item);
		});
		return {
			layout: next,
			ids: replacedIds,
			placed: replacedIds.length,
			skipped: targetIds.size - replacedIds.length,
			count: replacedIds.length,
		};
	}

	const originalItems = (next.drafting as unknown[])
		.filter((item): item is Record<string, unknown> => isObject(item) && typeof item.id === 'string' && targetIds.has(item.id));

	const createdIds: string[] = [];
	for (const item of originalItems) {
		const newId = nextDraftId(next);
		createdIds.push(newId);
		const mirrored = transformShape(item, newId);
		(next.drafting as unknown[]).push(mirrored);
	}

	return {
		layout: next,
		ids: createdIds,
		placed: createdIds.length,
		skipped: targetIds.size - originalItems.length,
		count: createdIds.length,
	};
}

/**
 * Copies selected drafts to each target story with fresh ids. Does not mutate input `layout`.
 */
export function copyDraftsToStories(layout: unknown, ids: Iterable<string>, targets: readonly string[]): IDraftBulkResult {
	const next = cloneLayout(layout);
	const targetIds = new Set(ids);
	if (!targetIds.size || !targets.length) {
		return { layout: next, ids: [], placed: 0, skipped: targetIds.size, count: 0 };
	}
	if (!Array.isArray(next.drafting)) {
		next.drafting = [];
	}
	const originalItems = (next.drafting as unknown[])
		.filter((item): item is Record<string, unknown> => isObject(item) && typeof item.id === 'string' && targetIds.has(item.id));

	const createdIds: string[] = [];
	for (const storyId of targets) {
		for (const item of originalItems) {
			const newId = nextDraftId(next);
			createdIds.push(newId);
			const copy: Record<string, unknown> = {
				...JSON.parse(JSON.stringify(item)),
				id: newId,
				story: storyId,
			};
			(next.drafting as unknown[]).push(copy);
		}
	}
	return {
		layout: next,
		ids: createdIds,
		placed: createdIds.length,
		skipped: targetIds.size - originalItems.length,
		count: createdIds.length,
	};
}


