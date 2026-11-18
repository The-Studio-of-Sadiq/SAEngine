/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Pure 2D geometry functions for AutoCAD-style TRIM, EXTEND, FILLET and CHAMFER.
 * No CAD library imports: pure computational geometry for easy unit testing.
 */

export type GeomPoint = readonly [number, number];

export interface GeomLine {
	readonly kind: 'line';
	readonly start: GeomPoint;
	readonly end: GeomPoint;
	readonly [key: string]: unknown;
}

export interface GeomArc {
	readonly kind: 'arc';
	readonly center: GeomPoint;
	readonly radius: number;
	readonly startAngle: number; // degrees, [0, 360)
	readonly endAngle: number;   // degrees, [0, 360)
	readonly [key: string]: unknown;
}

export interface GeomCircle {
	readonly kind: 'circle';
	readonly center: GeomPoint;
	readonly radius: number;
	readonly [key: string]: unknown;
}

export interface GeomPolyline {
	readonly kind: 'polyline';
	readonly points: readonly GeomPoint[];
	readonly closed?: boolean;
	readonly [key: string]: unknown;
}

export type GeomShape = GeomLine | GeomArc | GeomCircle | GeomPolyline;

export function roundCoord(v: number): number {
	const r = Math.round(v * 1000) / 1000;
	return r === 0 ? 0 : r;
}

export function normalizeAngle(degrees: number): number {
	const a = Number((((degrees % 360) + 360) % 360).toFixed(3));
	return a === 360 ? 0 : a;
}

export function normalizedSweep(start: number, end: number): number {
	return ((end - start) % 360 + 360) % 360;
}

const cross = (a: GeomPoint, b: GeomPoint) => a[0] * b[1] - a[1] * b[0];
const sub = (a: GeomPoint, b: GeomPoint): GeomPoint => [a[0] - b[0], a[1] - b[1]];
const add = (a: GeomPoint, b: GeomPoint): GeomPoint => [a[0] + b[0], a[1] + b[1]];
const mul = (a: GeomPoint, n: number): GeomPoint => [a[0] * n, a[1] * n];
const dot = (a: GeomPoint, b: GeomPoint) => a[0] * b[0] + a[1] * b[1];

export function lineIntersection(p: GeomPoint, r: GeomPoint, q: GeomPoint, s: GeomPoint): GeomPoint | undefined {
	const d = cross(r, s);
	if (Math.abs(d) < 1e-9) { return undefined; }
	return add(p, mul(r, cross(sub(q, p), s) / d));
}

export function lineHits(line: GeomLine, shape: GeomShape): { point: GeomPoint; t: number }[] {
	const p = line.start, v = sub(line.end, line.start), vv = v[0] * v[0] + v[1] * v[1];
	if (!vv) { return []; }
	const hits: GeomPoint[] = [];
	const segmentHit = (a: GeomPoint, b: GeomPoint) => {
		const w = sub(b, a), den = cross(v, w);
		if (Math.abs(den) < 1e-9) { return; }
		const t = cross(sub(a, p), w) / den, u = cross(sub(a, p), v) / den;
		if (t >= -1e-9 && t <= 1 + 1e-9 && u >= -1e-9 && u <= 1 + 1e-9) { hits.push(add(p, mul(v, t))); }
	};
	if (shape.kind === 'line') {
		segmentHit(shape.start, shape.end);
	} else if (shape.kind === 'polyline') {
		const pts = shape.points;
		const count = shape.closed ? pts.length : pts.length - 1;
		for (let i = 0; i < count; i++) {
			segmentHit(pts[i], pts[(i + 1) % pts.length]);
		}
	} else {
		const d = sub(p, shape.center), b = 2 * (d[0] * v[0] + d[1] * v[1]), c = d[0] * d[0] + d[1] * d[1] - shape.radius * shape.radius;
		const disc = b * b - 4 * vv * c;
		if (disc >= -1e-8) {
			for (const t of disc <= 1e-8 ? [-b / (2 * vv)] : [(-b - Math.sqrt(disc)) / (2 * vv), (-b + Math.sqrt(disc)) / (2 * vv)]) {
				if (t < -1e-9 || t > 1 + 1e-9) { continue; }
				const hit = add(p, mul(v, t));
				if (shape.kind === 'circle' || normalizedSweep(shape.startAngle, Math.atan2(hit[1] - shape.center[1], hit[0] - shape.center[0]) * 180 / Math.PI) <= normalizedSweep(shape.startAngle, shape.endAngle) + 1e-8) {
					hits.push(hit);
				}
			}
		}
	}
	return hits.map(point => ({ point, t: ((point[0] - p[0]) * v[0] + (point[1] - p[1]) * v[1]) / vv }));
}

export function circleHits(center: GeomPoint, radius: number, cutter: GeomShape): GeomPoint[] {
	if (cutter.kind === 'line') {
		const hits = lineHits(cutter, { kind: 'circle', center, radius });
		return hits.map(h => h.point);
	}
	if (cutter.kind === 'polyline') {
		const pts = cutter.points;
		const count = cutter.closed ? pts.length : pts.length - 1;
		const result: GeomPoint[] = [];
		for (let i = 0; i < count; i++) {
			const seg: GeomLine = { kind: 'line', start: pts[i], end: pts[(i + 1) % pts.length] };
			const hits = lineHits(seg, { kind: 'circle', center, radius });
			result.push(...hits.map(h => h.point));
		}
		return result;
	}
	if (cutter.kind === 'circle' || cutter.kind === 'arc') {
		const d = sub(cutter.center, center);
		const dist = Math.hypot(d[0], d[1]);
		if (dist < 1e-9 || dist > radius + cutter.radius || dist < Math.abs(radius - cutter.radius)) {
			return [];
		}
		const a = (radius * radius - cutter.radius * cutter.radius + dist * dist) / (2 * dist);
		const h = Math.sqrt(Math.max(0, radius * radius - a * a));
		const p2 = add(center, mul([d[0] / dist, d[1] / dist], a));
		const normal: GeomPoint = [-d[1] / dist, d[0] / dist];
		const p3a = add(p2, mul(normal, h));
		const p3b = sub(p2, mul(normal, h));
		const candidates = h < 1e-8 ? [p2] : [p3a, p3b];
		if (cutter.kind === 'circle') {
			return candidates;
		}
		return candidates.filter(pt => {
			const ang = normalizeAngle(Math.atan2(pt[1] - cutter.center[1], pt[0] - cutter.center[0]) * 180 / Math.PI);
			return normalizedSweep(cutter.startAngle, ang) <= normalizedSweep(cutter.startAngle, cutter.endAngle) + 1e-6;
		});
	}
	return [];
}

/** Fillet two finite lines, preserving each picked side. */
export function filletLines(
	l1: GeomLine,
	l2: GeomLine,
	radius: number,
	pick1: GeomPoint,
	pick2: GeomPoint
): { readonly lines: readonly [GeomLine, GeomLine]; readonly arc?: GeomArc } | undefined {
	const v1 = sub(l1.end, l1.start), v2 = sub(l2.end, l2.start);
	const corner = lineIntersection(l1.start, v1, l2.start, v2);
	if (!corner || radius < 0) { return undefined; }

	const side = (line: GeomLine, pick: GeomPoint) => {
		const along = sub(line.end, line.start), length = Math.hypot(along[0], along[1]);
		if (!length) { return undefined; }
		const unit: GeomPoint = [along[0] / length, along[1] / length];
		const sign = Math.sign(dot(sub(pick, corner), unit));
		if (!sign) { return undefined; }
		const w: GeomPoint = [unit[0] * sign, unit[1] * sign];
		const keepEnd = dot(sub(line.end, corner), w) >= dot(sub(line.start, corner), w);
		const reach = dot(sub(keepEnd ? line.end : line.start, corner), w);
		return reach > 0 ? { w, keepEnd, reach } : undefined;
	};

	const s1 = side(l1, pick1), s2 = side(l2, pick2);
	if (!s1 || !s2) { return undefined; }
	const theta = Math.acos(Math.max(-1, Math.min(1, dot(s1.w, s2.w))));
	if (theta < 1e-6 || Math.PI - theta < 1e-6) { return undefined; }

	const moved = (line: GeomLine, at: { readonly keepEnd: boolean }, point: GeomPoint): GeomLine =>
		at.keepEnd ? { ...line, start: point } : { ...line, end: point };

	if (!radius) {
		const p: GeomPoint = [roundCoord(corner[0]), roundCoord(corner[1])];
		return { lines: [moved(l1, s1, p), moved(l2, s2, p)] };
	}

	const d = radius / Math.tan(theta / 2);
	if (d > s1.reach + 1e-9 || d > s2.reach + 1e-9) { return undefined; }
	const tangent = (w: GeomPoint): GeomPoint => [roundCoord(corner[0] + w[0] * d), roundCoord(corner[1] + w[1] * d)];
	const t1 = tangent(s1.w), t2 = tangent(s2.w);
	const bis: GeomPoint = [s1.w[0] + s2.w[0], s1.w[1] + s2.w[1]], bl = Math.hypot(bis[0], bis[1]), h = radius / Math.sin(theta / 2);
	const center: GeomPoint = [roundCoord(corner[0] + bis[0] / bl * h), roundCoord(corner[1] + bis[1] / bl * h)];
	const angle = (p: GeomPoint) => normalizeAngle(Math.atan2(p[1] - center[1], p[0] - center[0]) * 180 / Math.PI);
	const a1 = angle(t1), a2 = angle(t2), ccw = normalizedSweep(a1, a2);
	const arc: GeomArc = {
		kind: 'arc',
		center,
		radius: roundCoord(radius),
		startAngle: ccw < 180 ? a1 : a2,
		endAngle: ccw < 180 ? a2 : a1,
	};
	return { lines: [moved(l1, s1, t1), moved(l2, s2, t2)], arc };
}

/** Chamfer two finite lines, preserving each picked side. */
export function chamferLines(
	l1: GeomLine,
	l2: GeomLine,
	d1: number,
	d2: number,
	pick1: GeomPoint,
	pick2: GeomPoint
): { readonly lines: readonly [GeomLine, GeomLine]; readonly chamferLine?: GeomLine } | undefined {
	const v1 = sub(l1.end, l1.start), v2 = sub(l2.end, l2.start);
	const corner = lineIntersection(l1.start, v1, l2.start, v2);
	if (!corner || d1 < 0 || d2 < 0) { return undefined; }

	const side = (line: GeomLine, pick: GeomPoint) => {
		const along = sub(line.end, line.start), length = Math.hypot(along[0], along[1]);
		if (!length) { return undefined; }
		const unit: GeomPoint = [along[0] / length, along[1] / length];
		const sign = Math.sign(dot(sub(pick, corner), unit));
		if (!sign) { return undefined; }
		const w: GeomPoint = [unit[0] * sign, unit[1] * sign];
		const keepEnd = dot(sub(line.end, corner), w) >= dot(sub(line.start, corner), w);
		const reach = dot(sub(keepEnd ? line.end : line.start, corner), w);
		return reach > 0 ? { w, keepEnd, reach } : undefined;
	};

	const s1 = side(l1, pick1), s2 = side(l2, pick2);
	if (!s1 || !s2) { return undefined; }
	const theta = Math.acos(Math.max(-1, Math.min(1, dot(s1.w, s2.w))));
	if (theta < 1e-6 || Math.PI - theta < 1e-6) { return undefined; }

	const moved = (line: GeomLine, at: { readonly keepEnd: boolean }, point: GeomPoint): GeomLine =>
		at.keepEnd ? { ...line, start: point } : { ...line, end: point };

	if (d1 === 0 && d2 === 0) {
		const p: GeomPoint = [roundCoord(corner[0]), roundCoord(corner[1])];
		return { lines: [moved(l1, s1, p), moved(l2, s2, p)] };
	}

	if (d1 > s1.reach + 1e-9 || d2 > s2.reach + 1e-9) { return undefined; }
	const t1: GeomPoint = [roundCoord(corner[0] + s1.w[0] * d1), roundCoord(corner[1] + s1.w[1] * d1)];
	const t2: GeomPoint = [roundCoord(corner[0] + s2.w[0] * d2), roundCoord(corner[1] + s2.w[1] * d2)];
	const chamferLine: GeomLine = { kind: 'line', start: t1, end: t2 };
	return { lines: [moved(l1, s1, t1), moved(l2, s2, t2)], chamferLine };
}

/** Remove the picked interval of a line. */
export function trimLine(line: GeomLine, cutters: readonly GeomShape[], pickPoint: GeomPoint): GeomLine[] {
	const hits = cutters.flatMap(c => lineHits(line, c))
		.map(h => h.t)
		.filter(t => t > 1e-8 && t < 1 - 1e-8)
		.sort((a, b) => a - b)
		.filter((t, i, a) => !i || Math.abs(t - a[i - 1]) > 1e-7);
	if (!hits.length) { return []; }
	const v = sub(line.end, line.start), vv = v[0] * v[0] + v[1] * v[1];
	const t = Math.max(0, Math.min(1, ((pickPoint[0] - line.start[0]) * v[0] + (pickPoint[1] - line.start[1]) * v[1]) / vv));
	const left = [...hits].reverse().find(h => h < t), right = hits.find(h => h > t);
	const lo = left ?? 0, hi = right ?? 1;
	const point = (n: number): GeomPoint => [roundCoord(line.start[0] + n * v[0]), roundCoord(line.start[1] + n * v[1])];
	const out: GeomLine[] = [];
	if (lo > 1e-8) { out.push({ ...line, end: point(lo) }); }
	if (hi < 1 - 1e-8) { out.push({ ...line, start: point(hi) }); }
	return out;
}

/** Extend the end nearest the pick point to the nearest boundary intersection. */
export function extendLine(line: GeomLine, boundaries: readonly GeomShape[], pickPoint: GeomPoint): GeomLine | undefined {
	const fromStart = Math.hypot(pickPoint[0] - line.start[0], pickPoint[1] - line.start[1]) < Math.hypot(pickPoint[0] - line.end[0], pickPoint[1] - line.end[1]);
	const origin = fromStart ? line.start : line.end, other = fromStart ? line.end : line.start;
	const v = sub(origin, other), len2 = v[0] * v[0] + v[1] * v[1];
	if (!len2) { return undefined; }
	const ray: GeomLine = { ...line, start: origin, end: add(origin, mul(v, 1e6)) };
	const hit = boundaries.flatMap(b => lineHits(ray, b)).filter(h => h.t > 1e-8).sort((a, b) => a.t - b.t)[0];
	if (!hit) { return undefined; }
	const end: GeomPoint = [roundCoord(hit.point[0]), roundCoord(hit.point[1])];
	return fromStart ? { ...line, start: end } : { ...line, end: end };
}

/** Trim a circle: pick point interval between cutters is removed; the remaining circle becomes an arc. */
export function trimCircle(circle: GeomCircle, cutters: readonly GeomShape[], pickPoint: GeomPoint): GeomArc | undefined {
	const allHits: GeomPoint[] = cutters.flatMap(c => circleHits(circle.center, circle.radius, c));
	if (!allHits.length) { return undefined; }
	const center = circle.center;
	const angles = allHits.map(pt => normalizeAngle(Math.atan2(pt[1] - center[1], pt[0] - center[0]) * 180 / Math.PI))
		.sort((a, b) => a - b)
		.filter((ang, idx, arr) => !idx || Math.abs(ang - arr[idx - 1]) > 1e-4);
	if (angles.length < 2) { return undefined; }
	const pickAngle = normalizeAngle(Math.atan2(pickPoint[1] - center[1], pickPoint[0] - center[0]) * 180 / Math.PI);
	const n = angles.length;
	for (let i = 0; i < n; i++) {
		const aStart = angles[i];
		const aEnd = angles[(i + 1) % n];
		const sweep = normalizedSweep(aStart, aEnd);
		const offset = normalizedSweep(aStart, pickAngle);
		if (offset > 1e-6 && offset < sweep - 1e-6) {
			return {
				kind: 'arc',
				center: [roundCoord(center[0]), roundCoord(center[1])],
				radius: roundCoord(circle.radius),
				startAngle: aEnd,
				endAngle: aStart,
			};
		}
	}
	return undefined;
}

/** Trim an arc: remove the picked interval between cutter intersections. */
export function trimArc(arc: GeomArc, cutters: readonly GeomShape[], pickPoint: GeomPoint): GeomArc[] {
	const allHits: GeomPoint[] = cutters.flatMap(c => circleHits(arc.center, arc.radius, c));
	const sweep = normalizedSweep(arc.startAngle, arc.endAngle);
	if (sweep < 1e-6) { return []; }
	const hitsOnArc = allHits.map(pt => {
		const ang = normalizeAngle(Math.atan2(pt[1] - arc.center[1], pt[0] - arc.center[0]) * 180 / Math.PI);
		const off = normalizedSweep(arc.startAngle, ang);
		return off / sweep;
	}).filter(t => t > 1e-6 && t < 1 - 1e-6)
		.sort((a, b) => a - b)
		.filter((t, i, arr) => !i || Math.abs(t - arr[i - 1]) > 1e-5);

	if (!hitsOnArc.length) { return []; }
	const pickAngle = normalizeAngle(Math.atan2(pickPoint[1] - arc.center[1], pickPoint[0] - arc.center[0]) * 180 / Math.PI);
	const pickT = Math.max(0, Math.min(1, normalizedSweep(arc.startAngle, pickAngle) / sweep));
	const left = [...hitsOnArc].reverse().find(h => h < pickT);
	const right = hitsOnArc.find(h => h > pickT);
	const lo = left ?? 0;
	const hi = right ?? 1;
	const out: GeomArc[] = [];
	if (lo > 1e-6) {
		out.push({
			...arc,
			center: [roundCoord(arc.center[0]), roundCoord(arc.center[1])],
			radius: roundCoord(arc.radius),
			startAngle: arc.startAngle,
			endAngle: normalizeAngle(arc.startAngle + lo * sweep),
		});
	}
	if (hi < 1 - 1e-6) {
		out.push({
			...arc,
			center: [roundCoord(arc.center[0]), roundCoord(arc.center[1])],
			radius: roundCoord(arc.radius),
			startAngle: normalizeAngle(arc.startAngle + hi * sweep),
			endAngle: arc.endAngle,
		});
	}
	return out;
}

/** Extend the end of an arc nearest the pick point to the nearest boundary. */
export function extendArc(arc: GeomArc, boundaries: readonly GeomShape[], pickPoint: GeomPoint): GeomArc | undefined {
	const allHits: GeomPoint[] = boundaries.flatMap(b => circleHits(arc.center, arc.radius, b));
	if (!allHits.length) { return undefined; }
	const sweep = normalizedSweep(arc.startAngle, arc.endAngle);
	const startPt: GeomPoint = [
		arc.center[0] + arc.radius * Math.cos(arc.startAngle * Math.PI / 180),
		arc.center[1] + arc.radius * Math.sin(arc.startAngle * Math.PI / 180),
	];
	const endPt: GeomPoint = [
		arc.center[0] + arc.radius * Math.cos(arc.endAngle * Math.PI / 180),
		arc.center[1] + arc.radius * Math.sin(arc.endAngle * Math.PI / 180),
	];
	const distToStart = Math.hypot(pickPoint[0] - startPt[0], pickPoint[1] - startPt[1]);
	const distToEnd = Math.hypot(pickPoint[0] - endPt[0], pickPoint[1] - endPt[1]);
	const fromStart = distToStart < distToEnd;

	if (fromStart) {
		let bestAngle: number | undefined;
		let minDelta = Infinity;
		for (const pt of allHits) {
			const ang = normalizeAngle(Math.atan2(pt[1] - arc.center[1], pt[0] - arc.center[0]) * 180 / Math.PI);
			const deltaCw = normalizedSweep(ang, arc.startAngle);
			if (deltaCw > 1e-4 && deltaCw < 360 - sweep - 1e-4) {
				if (deltaCw < minDelta) {
					minDelta = deltaCw;
					bestAngle = ang;
				}
			}
		}
		if (bestAngle !== undefined) {
			return { ...arc, startAngle: bestAngle };
		}
	} else {
		let bestAngle: number | undefined;
		let minDelta = Infinity;
		for (const pt of allHits) {
			const ang = normalizeAngle(Math.atan2(pt[1] - arc.center[1], pt[0] - arc.center[0]) * 180 / Math.PI);
			const deltaCcw = normalizedSweep(arc.endAngle, ang);
			if (deltaCcw > 1e-4 && deltaCcw < 360 - sweep - 1e-4) {
				if (deltaCcw < minDelta) {
					minDelta = deltaCcw;
					bestAngle = ang;
				}
			}
		}
		if (bestAngle !== undefined) {
			return { ...arc, endAngle: bestAngle };
		}
	}
	return undefined;
}

/** Trim an open polyline: trims the picked segment (end segments or splits polyline). */
export function trimPolyline(poly: GeomPolyline, cutters: readonly GeomShape[], pickPoint: GeomPoint): GeomPolyline[] {
	if (poly.closed || poly.points.length < 2) { return []; }
	const pts = poly.points;
	let bestSeg = -1;
	let minDist = Infinity;
	for (let i = 0; i < pts.length - 1; i++) {
		const a = pts[i], b = pts[i + 1];
		const v = sub(b, a), vv = v[0] * v[0] + v[1] * v[1];
		const t = vv ? Math.max(0, Math.min(1, ((pickPoint[0] - a[0]) * v[0] + (pickPoint[1] - a[1]) * v[1]) / vv)) : 0;
		const proj = add(a, mul(v, t));
		const dist = Math.hypot(pickPoint[0] - proj[0], pickPoint[1] - proj[1]);
		if (dist < minDist) {
			minDist = dist;
			bestSeg = i;
		}
	}
	if (bestSeg < 0) { return []; }

	if (bestSeg === 0) {
		const lineSeg: GeomLine = { kind: 'line', start: pts[0], end: pts[1] };
		const pieces = trimLine(lineSeg, cutters, pickPoint);
		if (!pieces.length) { return []; }
		const surviving = pieces.find(p => Math.hypot(p.end[0] - pts[1][0], p.end[1] - pts[1][1]) < 1e-6);
		if (surviving) {
			return [{ ...poly, points: [surviving.start, ...pts.slice(1)] }];
		}
		return [];
	} else if (bestSeg === pts.length - 2) {
		const lineSeg: GeomLine = { kind: 'line', start: pts[pts.length - 2], end: pts[pts.length - 1] };
		const pieces = trimLine(lineSeg, cutters, pickPoint);
		if (!pieces.length) { return []; }
		const surviving = pieces.find(p => Math.hypot(p.start[0] - pts[pts.length - 2][0], p.start[1] - pts[pts.length - 2][1]) < 1e-6);
		if (surviving) {
			return [{ ...poly, points: [...pts.slice(0, -1), surviving.end] }];
		}
		return [];
	}

	// Interior segment: split into two open polylines
	const lineSeg: GeomLine = { kind: 'line', start: pts[bestSeg], end: pts[bestSeg + 1] };
	const pieces = trimLine(lineSeg, cutters, pickPoint);
	const result: GeomPolyline[] = [];
	const leftPiece = pieces.find(p => Math.hypot(p.start[0] - pts[bestSeg][0], p.start[1] - pts[bestSeg][1]) < 1e-6);
	const rightPiece = pieces.find(p => Math.hypot(p.end[0] - pts[bestSeg + 1][0], p.end[1] - pts[bestSeg + 1][1]) < 1e-6);
	if (leftPiece) {
		result.push({ ...poly, points: [...pts.slice(0, bestSeg), leftPiece.start, leftPiece.end] });
	} else {
		result.push({ ...poly, points: pts.slice(0, bestSeg + 1) });
	}
	if (rightPiece) {
		result.push({ ...poly, points: [rightPiece.start, rightPiece.end, ...pts.slice(bestSeg + 2)] });
	} else {
		result.push({ ...poly, points: pts.slice(bestSeg + 1) });
	}
	return result;
}

/** Extend an open polyline's end segment towards the nearest boundary. */
export function extendPolyline(poly: GeomPolyline, boundaries: readonly GeomShape[], pickPoint: GeomPoint): GeomPolyline | undefined {
	if (poly.closed || poly.points.length < 2) { return undefined; }
	const pts = poly.points;
	const dStart = Math.hypot(pickPoint[0] - pts[0][0], pickPoint[1] - pts[0][1]);
	const dEnd = Math.hypot(pickPoint[0] - pts[pts.length - 1][0], pickPoint[1] - pts[pts.length - 1][1]);
	const fromStart = dStart < dEnd;
	if (fromStart) {
		const seg: GeomLine = { kind: 'line', start: pts[1], end: pts[0] };
		const ext = extendLine(seg, boundaries, pts[0]);
		if (!ext) { return undefined; }
		return { ...poly, points: [ext.end, ...pts.slice(1)] };
	} else {
		const seg: GeomLine = { kind: 'line', start: pts[pts.length - 2], end: pts[pts.length - 1] };
		const ext = extendLine(seg, boundaries, pts[pts.length - 1]);
		if (!ext) { return undefined; }
		return { ...poly, points: [...pts.slice(0, -1), ext.end] };
	}
}
