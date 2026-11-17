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

