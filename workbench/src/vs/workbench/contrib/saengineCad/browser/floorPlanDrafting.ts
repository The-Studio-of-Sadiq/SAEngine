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
	const endAngle = ccw(startAngle, middleAngle) <= ccw(startAngle, end) ? end : startAngle + (ccw(startAngle, end) - 360);
	return { center, radius: Math.hypot(a[0] - center[0], a[1] - center[1]), startAngle, endAngle };
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


