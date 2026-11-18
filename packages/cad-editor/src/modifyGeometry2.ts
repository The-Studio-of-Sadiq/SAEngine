/** Pure planar helpers for SCALE, arrays, BREAK, JOIN, EXPLODE, STRETCH, LENGTHEN and ALIGN. */
export type P2 = readonly [number, number];
export type Segment =
	| { kind: 'line'; start: P2; end: P2 }
	| { kind: 'arc'; center: P2; radius: number; startAngle: number; endAngle: number };

const add = (a: P2, b: P2): P2 => [a[0] + b[0], a[1] + b[1]];
const sub = (a: P2, b: P2): P2 => [a[0] - b[0], a[1] - b[1]];
const normAngle = (a: number): number => ((a % 360) + 360) % 360;

export function scalePoint(p: P2, base: P2, factor: number): P2 {
	return add(base, [(p[0] - base[0]) * factor, (p[1] - base[1]) * factor]);
}

export function rectangularArray<T>(
	items: readonly T[],
	rows: number,
	columns: number,
	rowSpacing: number,
	columnSpacing: number,
): { item: T; offset: P2 }[] {
	const out: { item: T; offset: P2 }[] = [];
	for (let r = 0; r < rows; r++) {
		for (let c = 0; c < columns; c++) {
			if (r || c) {
				for (const item of items) {
					out.push({ item, offset: [c * columnSpacing, r * rowSpacing] });
				}
			}
		}
	}
	return out;
}

export function polarArray<T>(
	items: readonly T[],
	center: P2,
	count: number,
	fillAngle: number,
	rotate: boolean,
	referencePoint?: P2,
): { item: T; angle: number; point: (p: P2) => P2; offset?: P2 }[] {
	if (items.length === 0 || count <= 1) return [];
	const ref: P2 = referencePoint ?? (Array.isArray(items[0]) && typeof items[0][0] === 'number' ? (items[0] as unknown as P2) : center);
	return Array.from({ length: count - 1 }, (_, i) => {
		const a = fillAngle * (i + 1) / count;
		const rad = a * Math.PI / 180;
		const rot = (p: P2): P2 => {
			const x = p[0] - center[0], y = p[1] - center[1];
			return [
				center[0] + x * Math.cos(rad) - y * Math.sin(rad),
				center[1] + x * Math.sin(rad) + y * Math.cos(rad),
			];
		};
		if (rotate) {
			return { item: items[0], angle: a, point: rot };
		} else {
			const refRot = rot(ref);
			const dx = refRot[0] - ref[0], dy = refRot[1] - ref[1];
			return {
				item: items[0],
				angle: 0,
				offset: [dx, dy],
				point: (p: P2): P2 => [p[0] + dx, p[1] + dy],
			};
		}
	});
}

export function breakLine(start: P2, end: P2, first: P2, second: P2): { start: P2; end: P2 }[] {
	const d = sub(end, start), len2 = d[0] ** 2 + d[1] ** 2;
	const t = (p: P2) => Math.max(0, Math.min(1, ((p[0] - start[0]) * d[0] + (p[1] - start[1]) * d[1]) / len2));
	const a = t(first), b = t(second);
	const minT = Math.min(a, b), maxT = Math.max(a, b);
	const res: { start: P2; end: P2 }[] = [];
	if (minT > 1e-8) {
		res.push({ start, end: add(start, [d[0] * minT, d[1] * minT]) });
	}
	if (1 - maxT > 1e-8) {
		res.push({ start: add(start, [d[0] * maxT, d[1] * maxT]), end });
	}
	return res;
}

/**
 * AutoCAD BREAK on a circle: removes the portion counter-clockwise from first to second pick.
 * The arc that remains goes CCW from second to first.
 */
export function breakCircle(
	center: P2,
	radius: number,
	first: P2,
	second: P2,
): { center: P2; radius: number; startAngle: number; endAngle: number } {
	const a1 = normAngle(Math.atan2(first[1] - center[1], first[0] - center[0]) * 180 / Math.PI);
	const a2 = normAngle(Math.atan2(second[1] - center[1], second[0] - center[0]) * 180 / Math.PI);
	return { center, radius, startAngle: a2, endAngle: a1 };
}

/**
 * AutoCAD BREAK on an arc: removes the interval between first and second picks.
 */
export function breakArc(
	center: P2,
	radius: number,
	startAngle: number,
	endAngle: number,
	first: P2,
	second: P2,
): { center: P2; radius: number; startAngle: number; endAngle: number }[] {
	const s = normAngle(startAngle), e = normAngle(endAngle);
	const totalSweep = ((e - s) % 360 + 360) % 360 || 360;
	const a1 = normAngle(Math.atan2(first[1] - center[1], first[0] - center[0]) * 180 / Math.PI);
	const a2 = normAngle(Math.atan2(second[1] - center[1], second[0] - center[0]) * 180 / Math.PI);
	const t1 = ((a1 - s) % 360 + 360) % 360;
	const t2 = ((a2 - s) % 360 + 360) % 360;
	const minT = Math.max(0, Math.min(totalSweep, Math.min(t1, t2)));
	const maxT = Math.max(0, Math.min(totalSweep, Math.max(t1, t2)));
	const res: { center: P2; radius: number; startAngle: number; endAngle: number }[] = [];
	if (minT > 1e-4) {
		res.push({ center, radius, startAngle: s, endAngle: normAngle(s + minT) });
	}
	if (totalSweep - maxT > 1e-4) {
		res.push({ center, radius, startAngle: normAngle(s + maxT), endAngle: e });
	}
	return res;
}

export function breakPolyline(points: readonly P2[], first: P2, second: P2): P2[][] {
	if (points.length < 2) return [];
	const getParam = (pt: P2): number => {
		let bestDist = Infinity, bestU = 0;
		for (let i = 0; i < points.length - 1; i++) {
			const p1 = points[i], p2 = points[i + 1];
			const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
			const lenSq = dx * dx + dy * dy;
			if (lenSq < 1e-12) continue;
			const t = Math.max(0, Math.min(1, ((pt[0] - p1[0]) * dx + (pt[1] - p1[1]) * dy) / lenSq));
			const projX = p1[0] + t * dx, projY = p1[1] + t * dy;
			const dist = Math.hypot(pt[0] - projX, pt[1] - projY);
			if (dist < bestDist) {
				bestDist = dist;
				bestU = i + t;
			}
		}
		return bestU;
	};

	const u1 = getParam(first), u2 = getParam(second);
	const uA = Math.min(u1, u2), uB = Math.max(u1, u2);

	const getPt = (u: number): P2 => {
		const idx = Math.min(points.length - 2, Math.max(0, Math.floor(u)));
		const t = u - idx;
		return [
			points[idx][0] + t * (points[idx + 1][0] - points[idx][0]),
			points[idx][1] + t * (points[idx + 1][1] - points[idx][1]),
		];
	};

	const poly1: P2[] = [];
	const poly2: P2[] = [];

	if (uA > 1e-5) {
		const endIdx = Math.floor(uA);
		for (let i = 0; i <= endIdx; i++) poly1.push(points[i]);
		const ptA = getPt(uA);
		if (Math.hypot(ptA[0] - poly1[poly1.length - 1][0], ptA[1] - poly1[poly1.length - 1][1]) > 1e-5) {
			poly1.push(ptA);
		}
	}

	if (uB < points.length - 1 - 1e-5) {
		const ptB = getPt(uB);
		poly2.push(ptB);
		const startIdx = Math.ceil(uB);
		for (let i = startIdx; i < points.length; i++) {
			if (i === startIdx && Math.hypot(ptB[0] - points[i][0], ptB[1] - points[i][1]) < 1e-5) continue;
			poly2.push(points[i]);
		}
	}

	const res: P2[][] = [];
	if (poly1.length >= 2) res.push(poly1);
	if (poly2.length >= 2) res.push(poly2);
	return res;
}

/**
 * Converts a polyline segment with bulge into an arc.
 * bulge b = tan(included_angle / 4), sign indicates CCW (>0) or CW (<0).
 */
export function bulgeToArc(
	p1: P2,
	p2: P2,
	bulge: number,
): { center: P2; radius: number; startAngle: number; endAngle: number } {
	const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
	const d = Math.hypot(dx, dy);
	const r = (d * (1 + bulge * bulge)) / (4 * Math.abs(bulge));
	const h = (d * (1 - bulge * bulge)) / (4 * bulge);
	const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
	const nx = -dy / d, ny = dx / d;
	const cx = mx + h * nx, cy = my + h * ny;
	const a1 = normAngle(Math.atan2(p1[1] - cy, p1[0] - cx) * 180 / Math.PI);
	const a2 = normAngle(Math.atan2(p2[1] - cy, p2[0] - cx) * 180 / Math.PI);
	return {
		center: [cx, cy],
		radius: r,
		startAngle: bulge > 0 ? a1 : a2,
		endAngle: bulge > 0 ? a2 : a1,
	};
}

/**
 * Converts an arc segment from p1 to p2 into a polyline bulge.
 */
export function arcToBulge(p1: P2, p2: P2, center: P2, isCCW = true): number {
	const a1 = normAngle(Math.atan2(p1[1] - center[1], p1[0] - center[0]) * 180 / Math.PI);
	const a2 = normAngle(Math.atan2(p2[1] - center[1], p2[0] - center[0]) * 180 / Math.PI);
	const sweep = isCCW ? ((a2 - a1) % 360 + 360) % 360 : ((a1 - a2) % 360 + 360) % 360;
	const b = Math.tan((sweep * Math.PI / 180) / 4);
	return isCCW ? b : -b;
}

export function explodePolyline(
	points: readonly P2[],
	closed = false,
	bulges?: readonly number[],
): ({ kind: 'line'; start: P2; end: P2 } | { kind: 'arc'; center: P2; radius: number; startAngle: number; endAngle: number })[] {
	const count = closed ? points.length : points.length - 1;
	const out: ({ kind: 'line'; start: P2; end: P2 } | { kind: 'arc'; center: P2; radius: number; startAngle: number; endAngle: number })[] = [];
	for (let i = 0; i < count; i++) {
		const p1 = points[i];
		const p2 = points[(i + 1) % points.length];
		const b = bulges?.[i] ?? 0;
		if (Math.abs(b) > 1e-6) {
			const arc = bulgeToArc(p1, p2, b);
			out.push({ kind: 'arc', ...arc });
		} else {
			out.push({ kind: 'line', start: p1, end: p2 });
		}
	}
	return out;
}

export function joinLines(a: { start: P2; end: P2 }, b: { start: P2; end: P2 }): { start: P2; end: P2 } | undefined {
	const near = (p: P2, q: P2) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 1e-5;
	const v = sub(a.end, a.start), w = sub(b.end, b.start);
	if (Math.abs(v[0] * w[1] - v[1] * w[0]) > 1e-6 || Math.abs(v[0] * (b.start[1] - a.start[1]) - v[1] * (b.start[0] - a.start[0])) > 1e-6) return undefined;
	const pts = [a.start, a.end, b.start, b.end].sort((p, q) => p[0] * v[0] + p[1] * v[1] - q[0] * v[0] - q[1] * v[1]);
	if (!(near(a.start, b.start) || near(a.start, b.end) || near(a.end, b.start) || near(a.end, b.end))) return undefined;
	return { start: pts[0], end: pts[3] };
}

/** Merges two co-circular arcs if they touch or overlap. */
export function joinArcs(
	a: { center: P2; radius: number; startAngle: number; endAngle: number },
	b: { center: P2; radius: number; startAngle: number; endAngle: number },
): { center: P2; radius: number; startAngle: number; endAngle: number } | undefined {
	if (Math.hypot(a.center[0] - b.center[0], a.center[1] - b.center[1]) > 1e-5) return undefined;
	if (Math.abs(a.radius - b.radius) > 1e-5) return undefined;

	const sa = normAngle(a.startAngle), ea = normAngle(a.endAngle);
	const sb = normAngle(b.startAngle), eb = normAngle(b.endAngle);
	const sweepA = ((ea - sa) % 360 + 360) % 360 || 360;
	const sweepB = ((eb - sb) % 360 + 360) % 360 || 360;

	const t = (ang: number) => ((ang - sa) % 360 + 360) % 360;
	const tSb = t(sb), tEb = t(eb);

	// Case 1: b starts at or inside a
	if (tSb <= sweepA + 1e-4) {
		const newSweep = Math.max(sweepA, tEb);
		if (newSweep >= 360 - 1e-4) return undefined; // would close into circle, not arc
		return { center: a.center, radius: a.radius, startAngle: sa, endAngle: normAngle(sa + newSweep) };
	}
	// Case 2: b ends at or inside a
	if (tEb <= sweepA + 1e-4) {
		const startRel = tSb - 360;
		const newSweep = sweepA - startRel;
		if (newSweep >= 360 - 1e-4) return undefined;
		return { center: a.center, radius: a.radius, startAngle: normAngle(sa + startRel), endAngle: ea };
	}
	return undefined;
}

export function stretchPolyline(points: readonly P2[], inside: (p: P2) => boolean, delta: P2): P2[] {
	return points.map(p => inside(p) ? add(p, delta) : p);
}

export function lengthenLine(start: P2, end: P2, delta: number, pick: P2): { start: P2; end: P2 } {
	const d = sub(end, start), n = Math.hypot(...d);
	const atEnd = Math.hypot(pick[0] - end[0], pick[1] - end[1]) < Math.hypot(pick[0] - start[0], pick[1] - start[1]);
	const k = delta / n;
	return atEnd ? { start, end: add(end, [d[0] * k, d[1] * k]) } : { start: add(start, [-d[0] * k, -d[1] * k]), end };
}

export function lengthenArc(
	center: P2,
	radius: number,
	startAngle: number,
	endAngle: number,
	delta: number,
	pick: P2,
): { center: P2; radius: number; startAngle: number; endAngle: number } {
	const s = normAngle(startAngle), e = normAngle(endAngle);
	const dTheta = (delta / radius) * (180 / Math.PI);
	const pStart: P2 = [
		center[0] + radius * Math.cos(s * Math.PI / 180),
		center[1] + radius * Math.sin(s * Math.PI / 180),
	];
	const pEnd: P2 = [
		center[0] + radius * Math.cos(e * Math.PI / 180),
		center[1] + radius * Math.sin(e * Math.PI / 180),
	];
	const dStart = Math.hypot(pick[0] - pStart[0], pick[1] - pStart[1]);
	const dEnd = Math.hypot(pick[0] - pEnd[0], pick[1] - pEnd[1]);
	if (dEnd < dStart) {
		return { center, radius, startAngle: s, endAngle: normAngle(e + dTheta) };
	} else {
		return { center, radius, startAngle: normAngle(s - dTheta), endAngle: e };
	}
}

export function alignPoint(p: P2, source: P2, angle: number, destination: P2, scale = 1): P2 {
	const r = angle * Math.PI / 180, x = (p[0] - source[0]) * scale, y = (p[1] - source[1]) * scale;
	return [destination[0] + x * Math.cos(r) - y * Math.sin(r), destination[1] + x * Math.sin(r) + y * Math.cos(r)];
}
