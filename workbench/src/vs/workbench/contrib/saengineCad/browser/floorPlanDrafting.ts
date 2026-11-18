/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { gridsOf } from './floorPlanDrawing.js';
import type { IActionStep } from '../../../services/saengineProject/common/saengineActions.js';
import type { CadPoint } from '@saengine/cad-editor';

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
	readonly id?: string;
	readonly handle?: string;
	readonly story?: string;
	readonly layer?: string;
}

export interface IDraftLine extends IDraftBase {
	readonly kind: 'line';
	readonly start?: DraftPoint | CadPoint;
	readonly end?: DraftPoint | CadPoint;
	readonly points?: readonly (DraftPoint | CadPoint)[];
}

export interface IDraftPolyline extends IDraftBase {
	readonly kind: 'polyline';
	readonly points: readonly (DraftPoint | CadPoint)[];
	readonly closed?: boolean;
}

export interface IDraftArc extends IDraftBase {
	readonly kind: 'arc';
	readonly center?: DraftPoint | CadPoint;
	readonly radius?: number;
	readonly startAngle?: number;
	readonly endAngle?: number;
	readonly points?: readonly (DraftPoint | CadPoint)[];
}

export interface IDraftCircle extends IDraftBase {
	readonly kind: 'circle';
	readonly center?: DraftPoint | CadPoint;
	readonly radius?: number;
	readonly points?: readonly (DraftPoint | CadPoint)[];
}

export type IDraftShape = IDraftLine | IDraftPolyline | IDraftArc | IDraftCircle;

export interface IConvertibleDraft {
	readonly id?: string;
	readonly handle?: string;
	readonly kind: string;
	readonly points?: readonly (DraftPoint | CadPoint)[];
	readonly start?: DraftPoint | CadPoint;
	readonly end?: DraftPoint | CadPoint;
	readonly closed?: boolean;
}

/** A grid intersection and its offsets, in the actions catalogue's point format. */
export interface IDraftPointRef {
	readonly x: string;
	readonly y: string;
	readonly dx: number;
	readonly dy: number;
}

/** Names a draft point by its nearest grid lines, keeping its distance from each in mm. */
export function toPointRef(point: DraftPoint | CadPoint, grids: ReturnType<typeof gridsOf>): IDraftPointRef | undefined {
	const nearest = (lines: ReadonlyMap<string, number>, value: number): [string, number] | undefined => {
		let result: [string, number] | undefined;
		for (const [label, position] of lines) {
			if (!result || Math.abs(value - position) < Math.abs(value - result[1])) {
				result = [label, position];
			}
		}
		return result;
	};
	const x = nearest(grids.x, point[0]);
	const y = nearest(grids.y, point[1]);
	return x && y ? { x: x[0], y: y[0], dx: Math.round(point[0] - x[1]), dy: Math.round(point[1] - y[1]) } : undefined;
}

/** Builds shared actions for converting selected drafts on one story. */
export function conversionSteps(
	drafts: readonly (IDraftShape | IConvertibleDraft)[],
	kind: 'beam' | 'wall' | 'slab',
	type: string,
	story: string,
	grids: ReturnType<typeof gridsOf>
): { readonly steps: IActionStep[]; readonly skipped: string[] } {
	const steps: IActionStep[] = [];
	const skipped: string[] = [];
	const converted: string[] = [];
	const ref = (point: DraftPoint | CadPoint) => toPointRef(point, grids);

	for (const draft of drafts) {
		const id = draft.id ?? draft.handle ?? '';
		const entityKind = draft.kind;
		const closed = draft.closed ?? false;

		if (entityKind === 'circle' || entityKind === 'arc' || (kind === 'slab' && (entityKind !== 'polyline' || !closed))) {
			skipped.push(id);
			continue;
		}

		if (kind === 'slab') {
			const pts = (draft as IDraftPolyline).points;
			if (!pts) {
				skipped.push(id);
				continue;
			}
			const points = pts.map(ref);
			if (points.length < 3 || points.some(point => !point)) {
				skipped.push(id);
				continue;
			}
			steps.push({ action: 'slabs.place', params: { type, panels: [points], storeys: [story] } });
			converted.push(id);
			continue;
		}

		let segments: (readonly [DraftPoint | CadPoint, DraftPoint | CadPoint])[] = [];
		if (entityKind === 'line') {
			const start = (draft as IDraftLine).start ?? draft.points?.[0];
			const end = (draft as IDraftLine).end ?? draft.points?.[1];
			if (start && end) {
				segments = [[start, end]];
			}
		} else if (entityKind === 'polyline' && draft.points) {
			const pts = draft.points;
			segments = pts.slice(1).map((point, index) => [pts[index], point] as const);
			if (closed && pts.length > 1) {
				segments.push([pts[pts.length - 1], pts[0]]);
			}
		}

		const between = segments.map(([start, end]) => [ref(start), ref(end)]);
		if (!between.length || between.some(pair => pair.some(point => !point))) {
			skipped.push(id);
			continue;
		}

		steps.push({ action: kind === 'beam' ? 'beams.place' : 'walls.place', params: { type, between, storeys: [story] } });
		converted.push(id);
	}

	if (converted.length) {
		steps.push({ action: 'drafting.delete', params: { ids: converted } });
	}

	return { steps, skipped };
}
