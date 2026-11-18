/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

export type P2 = readonly [number, number];
export interface Segment { start: P2; end: P2; bulge?: number }
const dist = (a: P2, b: P2) => Math.hypot(b[0] - a[0], b[1] - a[1]);

export function arcFromBulge(a: P2, b: P2, bulge = 0) {
	const chord = dist(a, b);
	if (!bulge || chord === 0) return undefined;
	const theta = 4 * Math.atan(bulge), radius = chord * (1 + bulge * bulge) / (4 * Math.abs(bulge));
	const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, h = chord * (1 - bulge * bulge) / (4 * bulge);
	const ux = -(b[1] - a[1]) / chord, uy = (b[0] - a[0]) / chord;
	const cx = mx + ux * h, cy = my + uy * h, start = Math.atan2(a[1] - cy, a[0] - cx);
	return { center: [cx, cy] as P2, radius, start, sweep: theta };
}

export function polylineMetrics(vertices: readonly P2[], bulges: readonly number[], closed: boolean) {
	const n = vertices.length, count = closed ? n : Math.max(0, n - 1);
	let area2 = 0, length = 0;
	for (let i = 0; i < count; i++) {
		const a = vertices[i], b = vertices[(i + 1) % n], bulge = bulges[i] || 0, chord = dist(a, b);
		area2 += a[0] * b[1] - b[0] * a[1];
		const arc = arcFromBulge(a, b, bulge);
		if (arc) {
			length += arc.radius * Math.abs(arc.sweep);
			area2 += arc.radius * arc.radius * (arc.sweep - Math.sin(arc.sweep));
		} else {
			length += chord;
		}
	}
	return { length, area: closed ? Math.abs(area2) / 2 : 0 };
}

export function curveSegments(vertices: readonly P2[], bulges: readonly number[], closed: boolean): Segment[] {
	const n = vertices.length, count = closed ? n : Math.max(0, n - 1);
	return Array.from({ length: count }, (_, i) => ({
		start: vertices[i],
		end: vertices[(i + 1) % n],
		bulge: bulges[i] || 0,
	}));
}

export function totalLength(segments: readonly Segment[]) {
	return segments.reduce((s, g) => {
		const arc = arcFromBulge(g.start, g.end, g.bulge);
		return s + (arc ? arc.radius * Math.abs(arc.sweep) : dist(g.start, g.end));
	}, 0);
}

export function pointAlong(segments: readonly Segment[], distance: number): P2 | undefined {
	let d = distance;
	for (const g of segments) {
		const arc = arcFromBulge(g.start, g.end, g.bulge);
		const len = arc ? arc.radius * Math.abs(arc.sweep) : dist(g.start, g.end);
		if (d <= len + 1e-9) {
			if (!arc) {
				const t = len ? d / len : 0;
				return [g.start[0] + (g.end[0] - g.start[0]) * t, g.start[1] + (g.end[1] - g.start[1]) * t];
			}
			const angle = arc.start + Math.sign(arc.sweep) * d / arc.radius;
			return [arc.center[0] + arc.radius * Math.cos(angle), arc.center[1] + arc.radius * Math.sin(angle)];
		}
		d -= len;
	}
	return undefined;
}

export function divideCurve(segments: readonly Segment[], count: number) {
	const len = totalLength(segments);
	return Array.from({ length: Math.max(0, count - 1) }, (_, i) => pointAlong(segments, len * (i + 1) / count)!).filter(Boolean);
}

export function measureCurve(segments: readonly Segment[], spacing: number, fromEnd = false) {
	const len = totalLength(segments), out: P2[] = [];
	if (spacing <= 0) return out;
	for (let d = spacing; d < len - 1e-9; d += spacing) {
		const p = pointAlong(segments, fromEnd ? len - d : d);
		if (p) out.push(p);
	}
	return out;
}

export function circleMetrics(radius: number) {
	return { area: Math.PI * radius * radius, circumference: 2 * Math.PI * radius };
}

export function ellipseMetrics(majorRadius: number, minorRadius: number) {
	const a = Math.max(majorRadius, minorRadius);
	const b = Math.min(majorRadius, minorRadius);
	const area = Math.PI * a * b;
	const h = (a - b) * (a - b) / ((a + b) * (a + b) || 1);
	const perimeter = a === b ? 2 * Math.PI * a : Math.PI * (a + b) * (1 + (3 * h) / (10 + Math.sqrt(4 - 3 * h)));
	return { area, perimeter };
}

/**
 * AutoCAD treats an arc measured for AREA as closed by its chord.
 * Returns the chord-closed circular segment area and perimeter (arc length + chord length).
 */
export function arcSegmentMetrics(radius: number, sweep: number) {
	const s = Math.abs(sweep);
	const area = 0.5 * radius * radius * (s - Math.sin(s));
	const chord = 2 * radius * Math.sin(s / 2);
	const arcLength = radius * s;
	return { area, perimeter: arcLength + chord, arcLength, chord };
}

export function arcIncludedAngle(startAngleRad: number, endAngleRad: number): number {
	let sweep = ((endAngleRad - startAngleRad) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
	if (sweep === 0 && startAngleRad !== endAngleRad) sweep = 2 * Math.PI;
	return sweep * 180 / Math.PI;
}

export function angleBetweenVectors(v1: P2, v2: P2): number {
	const d1 = Math.hypot(v1[0], v1[1]);
	const d2 = Math.hypot(v2[0], v2[1]);
	if (d1 === 0 || d2 === 0) return 0;
	const dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (d1 * d2);
	const clamped = Math.max(-1, Math.min(1, dot));
	return Math.acos(clamped) * 180 / Math.PI;
}

export function angleBetweenLines(p1: P2, p2: P2, q1: P2, q2: P2): number {
	return angleBetweenVectors([p2[0] - p1[0], p2[1] - p1[1]], [q2[0] - q1[0], q2[1] - q1[1]]);
}

export function threePointAngle(vertex: P2, p1: P2, p2: P2): number {
	return angleBetweenVectors([p1[0] - vertex[0], p1[1] - vertex[1]], [p2[0] - vertex[0], p2[1] - vertex[1]]);
}
