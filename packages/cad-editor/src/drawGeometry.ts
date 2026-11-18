/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

export type Point2D = [number, number];

export interface CircleGeom {
	readonly center: Point2D;
	readonly radius: number;
}

export interface ArcGeom {
	readonly center: Point2D;
	readonly radius: number;
	readonly startAngle: number; // radians in [0, 2π)
	readonly endAngle: number;   // radians in [0, 2π)
	readonly startPoint: Point2D;
	readonly endPoint: Point2D;
}

export interface PolylineGeom {
	readonly points: Point2D[];
	readonly bulges: number[];
	readonly closed: boolean;
	readonly constantWidth?: number;
}

export interface LineSegmentGeom {
	readonly start: Point2D;
	readonly end: Point2D;
}

/** Normalize angle in radians into [0, 2π). */
export function normalizeAngleRad(angle: number): number {
	const twoPi = 2 * Math.PI;
	return ((angle % twoPi) + twoPi) % twoPi;
}

// -----------------------------------------------------------------------------
// 1. CIRCLE VARIANTS
// -----------------------------------------------------------------------------

/** Circle from two diameter endpoints. */
export function circle2P(p1: Point2D, p2: Point2D): CircleGeom {
	const dx = p2[0] - p1[0];
	const dy = p2[1] - p1[1];
	const dist = Math.hypot(dx, dy);
	if (dist < 1e-12) {
		throw new Error('2P diameter endpoints must be distinct');
	}
	return {
		center: [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2],
		radius: dist / 2,
	};
}

/** Circle through three points. */
export function circle3P(p1: Point2D, p2: Point2D, p3: Point2D): CircleGeom {
	const [x1, y1] = p1;
	const [x2, y2] = p2;
	const [x3, y3] = p3;
	const d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2));
	if (Math.abs(d) < 1e-12) {
		throw new Error('Points are collinear');
	}
	const sq1 = x1 * x1 + y1 * y1;
	const sq2 = x2 * x2 + y2 * y2;
	const sq3 = x3 * x3 + y3 * y3;
	const cx = (sq1 * (y2 - y3) + sq2 * (y3 - y1) + sq3 * (y1 - y2)) / d;
	const cy = (sq1 * (x3 - x2) + sq2 * (x1 - x3) + sq3 * (x2 - x1)) / d;
	const radius = Math.hypot(cx - x1, cy - y1);
	return { center: [cx, cy], radius };
}

/**
 * Circle tangent to two entities (lines or circles) with given radius near pick points.
 */
export function circleTTR(
	e1: LineSegmentGeom | CircleGeom,
	e2: LineSegmentGeom | CircleGeom,
	radius: number,
	pick1: Point2D,
	pick2: Point2D,
): CircleGeom {
	if (radius <= 0) {
		throw new Error('Radius must be positive');
	}

	const isLine = (e: LineSegmentGeom | CircleGeom): e is LineSegmentGeom => 'start' in e && 'end' in e;

	// Line-Line case
	if (isLine(e1) && isLine(e2)) {
		const dx1 = e1.end[0] - e1.start[0], dy1 = e1.end[1] - e1.start[1];
		const len1 = Math.hypot(dx1, dy1);
		if (len1 < 1e-12) throw new Error('First line length is zero');
		const u1 = [dx1 / len1, dy1 / len1];
		const n1 = [-u1[1], u1[0]]; // normal

		const dx2 = e2.end[0] - e2.start[0], dy2 = e2.end[1] - e2.start[1];
		const len2 = Math.hypot(dx2, dy2);
		if (len2 < 1e-12) throw new Error('Second line length is zero');
		const u2 = [dx2 / len2, dy2 / len2];
		const n2 = [-u2[1], u2[0]]; // normal

		// Determine sign of offset based on pick point
		const sign1 = ((pick1[0] - e1.start[0]) * n1[0] + (pick1[1] - e1.start[1]) * n1[1]) >= 0 ? 1 : -1;
		const sign2 = ((pick2[0] - e2.start[0]) * n2[0] + (pick2[1] - e2.start[1]) * n2[1]) >= 0 ? 1 : -1;

		const pOffset1: Point2D = [e1.start[0] + sign1 * radius * n1[0], e1.start[1] + sign1 * radius * n1[1]];
		const pOffset2: Point2D = [e2.start[0] + sign2 * radius * n2[0], e2.start[1] + sign2 * radius * n2[1]];

		// Intersect offset lines: pOffset1 + s * u1 = pOffset2 + t * u2
		const denom = u1[0] * u2[1] - u1[1] * u2[0];
		if (Math.abs(denom) < 1e-12) {
			throw new Error('Lines are parallel; cannot construct tangent circle');
		}
		const s = ((pOffset2[0] - pOffset1[0]) * u2[1] - (pOffset2[1] - pOffset1[1]) * u2[0]) / denom;
		const cx = pOffset1[0] + s * u1[0];
		const cy = pOffset1[1] + s * u1[1];
		return { center: [cx, cy], radius };
	}

	// Line-Circle / Circle-Line case
	const line = isLine(e1) ? e1 : (isLine(e2) ? e2 : null);
	const circle = !isLine(e1) ? e1 : (!isLine(e2) ? e2 : null);
	const linePick = isLine(e1) ? pick1 : pick2;
	const circlePick = isLine(e1) ? pick2 : pick1;

	if (line && circle) {
		const dx = line.end[0] - line.start[0], dy = line.end[1] - line.start[1];
		const len = Math.hypot(dx, dy);
		if (len < 1e-12) throw new Error('Line length is zero');
		const u = [dx / len, dy / len];
		const n = [-u[1], u[0]];
		const sign = ((linePick[0] - line.start[0]) * n[0] + (linePick[1] - line.start[1]) * n[1]) >= 0 ? 1 : -1;
		const linePt: Point2D = [line.start[0] + sign * radius * n[0], line.start[1] + sign * radius * n[1]];

		const dPick = Math.hypot(circlePick[0] - circle.center[0], circlePick[1] - circle.center[1]);
		const rOffset = dPick > circle.radius ? circle.radius + radius : Math.abs(circle.radius - radius);

		// Intersect line (linePt + t * u) and circle (circle.center, rOffset)
		// (linePt.x + t*u.x - cx)^2 + (linePt.y + t*u.y - cy)^2 = rOffset^2
		const fX = linePt[0] - circle.center[0];
		const fY = linePt[1] - circle.center[1];
		const a = u[0] * u[0] + u[1] * u[1]; // 1
		const b = 2 * (fX * u[0] + fY * u[1]);
		const c = fX * fX + fY * fY - rOffset * rOffset;
		const discr = b * b - 4 * a * c;
		if (discr < 0) {
			throw new Error('No tangent circle exists for given radius and objects');
		}
		const t1 = (-b + Math.sqrt(discr)) / (2 * a);
		const t2 = (-b - Math.sqrt(discr)) / (2 * a);
		const cand1: Point2D = [linePt[0] + t1 * u[0], linePt[1] + t1 * u[1]];
		const cand2: Point2D = [linePt[0] + t2 * u[0], linePt[1] + t2 * u[1]];

		const d1 = Math.hypot(cand1[0] - linePick[0], cand1[1] - linePick[1]) + Math.hypot(cand1[0] - circlePick[0], cand1[1] - circlePick[1]);
		const d2 = Math.hypot(cand2[0] - linePick[0], cand2[1] - linePick[1]) + Math.hypot(cand2[0] - circlePick[0], cand2[1] - circlePick[1]);
		return { center: d1 <= d2 ? cand1 : cand2, radius };
	}

	// Circle-Circle case
	const c1 = e1 as CircleGeom;
	const c2 = e2 as CircleGeom;
	const dPick1 = Math.hypot(pick1[0] - c1.center[0], pick1[1] - c1.center[1]);
	const rOffset1 = dPick1 > c1.radius ? c1.radius + radius : Math.abs(c1.radius - radius);
	const dPick2 = Math.hypot(pick2[0] - c2.center[0], pick2[1] - c2.center[1]);
	const rOffset2 = dPick2 > c2.radius ? c2.radius + radius : Math.abs(c2.radius - radius);

	// Intersect two offset circles (c1.center, rOffset1) and (c2.center, rOffset2)
	const dC = Math.hypot(c2.center[0] - c1.center[0], c2.center[1] - c1.center[1]);
	if (dC > rOffset1 + rOffset2 || dC < Math.abs(rOffset1 - rOffset2) || dC < 1e-12) {
		throw new Error('No tangent circle exists for given radius and circles');
	}
	const aVal = (rOffset1 * rOffset1 - rOffset2 * rOffset2 + dC * dC) / (2 * dC);
	const h = Math.sqrt(Math.max(0, rOffset1 * rOffset1 - aVal * aVal));
	const pMidX = c1.center[0] + (aVal * (c2.center[0] - c1.center[0])) / dC;
	const pMidY = c1.center[1] + (aVal * (c2.center[1] - c1.center[1])) / dC;
	const cand1: Point2D = [
		pMidX + (h * (c2.center[1] - c1.center[1])) / dC,
		pMidY - (h * (c2.center[0] - c1.center[0])) / dC,
	];
	const cand2: Point2D = [
		pMidX - (h * (c2.center[1] - c1.center[1])) / dC,
		pMidY + (h * (c2.center[0] - c1.center[0])) / dC,
	];
	const d1 = Math.hypot(cand1[0] - pick1[0], cand1[1] - pick1[1]) + Math.hypot(cand1[0] - pick2[0], cand1[1] - pick2[1]);
	const d2 = Math.hypot(cand2[0] - pick1[0], cand2[1] - pick1[1]) + Math.hypot(cand2[0] - pick2[0], cand2[1] - pick2[1]);
	return { center: d1 <= d2 ? cand1 : cand2, radius };
}

/** Intersect two infinite lines defined by segments. */
function lineLineIntersection(l1: LineSegmentGeom, l2: LineSegmentGeom): Point2D {
	const dx1 = l1.end[0] - l1.start[0], dy1 = l1.end[1] - l1.start[1];
	const dx2 = l2.end[0] - l2.start[0], dy2 = l2.end[1] - l2.start[1];
	const denom = dx1 * dy2 - dy1 * dx2;
	if (Math.abs(denom) < 1e-12) throw new Error('Lines are parallel');
	const s = ((l2.start[0] - l1.start[0]) * dy2 - (l2.start[1] - l1.start[1]) * dx2) / denom;
	return [l1.start[0] + s * dx1, l1.start[1] + s * dy1];
}

/** Circle tangent to three lines (incircle of triangle). */
export function circleTTT(line1: LineSegmentGeom, line2: LineSegmentGeom, line3: LineSegmentGeom): CircleGeom {
	const A = lineLineIntersection(line1, line2);
	const B = lineLineIntersection(line2, line3);
	const C = lineLineIntersection(line3, line1);

	const a = Math.hypot(B[0] - C[0], B[1] - C[1]);
	const b = Math.hypot(C[0] - A[0], C[1] - A[1]);
	const c = Math.hypot(A[0] - B[0], A[1] - B[1]);
	const perimeter = a + b + c;
	if (perimeter < 1e-12) throw new Error('Triangle vertices are degenerate');

	const incenterX = (a * A[0] + b * B[0] + c * C[0]) / perimeter;
	const incenterY = (a * A[1] + b * B[1] + c * C[1]) / perimeter;
	const s = perimeter / 2;
	const area = 0.5 * Math.abs((B[0] - A[0]) * (C[1] - A[1]) - (B[1] - A[1]) * (C[0] - A[0]));
	const inradius = area / s;

	return { center: [incenterX, incenterY], radius: inradius };
}

// -----------------------------------------------------------------------------
// 2. ARC VARIANTS
// -----------------------------------------------------------------------------

/** Arc from Start, Center, and End points. */
export function arcStartCenterEnd(start: Point2D, center: Point2D, end: Point2D): ArcGeom {
	const radius = Math.hypot(start[0] - center[0], start[1] - center[1]);
	if (radius < 1e-12) throw new Error('Start point and center point must be distinct');
	const startAngle = normalizeAngleRad(Math.atan2(start[1] - center[1], start[0] - center[0]));
	const endAngle = normalizeAngleRad(Math.atan2(end[1] - center[1], end[0] - center[0]));
	const endPoint: Point2D = [center[0] + radius * Math.cos(endAngle), center[1] + radius * Math.sin(endAngle)];
	return { center, radius, startAngle, endAngle, startPoint: start, endPoint };
}

/** Arc from Start, Center, and Included Angle in radians. */
export function arcStartCenterAngle(start: Point2D, center: Point2D, angleRad: number): ArcGeom {
	const radius = Math.hypot(start[0] - center[0], start[1] - center[1]);
	if (radius < 1e-12) throw new Error('Start point and center point must be distinct');
	const startAngle = normalizeAngleRad(Math.atan2(start[1] - center[1], start[0] - center[0]));
	const rawEndAngle = startAngle + angleRad;
	const endAngle = normalizeAngleRad(rawEndAngle);
	const endPoint: Point2D = [center[0] + radius * Math.cos(rawEndAngle), center[1] + radius * Math.sin(rawEndAngle)];
	return { center, radius, startAngle, endAngle, startPoint: start, endPoint };
}

/** Arc from Start, Center, and Chord Length. */
export function arcStartCenterLength(start: Point2D, center: Point2D, chordLength: number): ArcGeom {
	const radius = Math.hypot(start[0] - center[0], start[1] - center[1]);
	if (radius < 1e-12) throw new Error('Start point and center point must be distinct');
	if (Math.abs(chordLength) > 2 * radius) throw new Error('Chord length exceeds circle diameter');
	const includedAngle = 2 * Math.asin(chordLength / (2 * radius));
	return arcStartCenterAngle(start, center, includedAngle);
}

/** Arc from Start, End, and Included Angle in radians. */
export function arcStartEndAngle(start: Point2D, end: Point2D, angleRad: number): ArcGeom {
	const d = Math.hypot(end[0] - start[0], end[1] - start[1]);
	if (d < 1e-12) throw new Error('Start and end points must be distinct');
	if (Math.abs(angleRad) < 1e-12) throw new Error('Angle cannot be zero');
	const radius = (d / 2) / Math.sin(Math.abs(angleRad) / 2);
	const mid: Point2D = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
	const u = [(end[0] - start[0]) / d, (end[1] - start[1]) / d];
	const n = [-u[1], u[0]];
	const h = (d / 2) / Math.tan(angleRad / 2);
	const center: Point2D = [mid[0] + h * n[0], mid[1] + h * n[1]];
	const startAngle = normalizeAngleRad(Math.atan2(start[1] - center[1], start[0] - center[0]));
	const endAngle = normalizeAngleRad(Math.atan2(end[1] - center[1], end[0] - center[0]));
	return { center, radius, startAngle, endAngle, startPoint: start, endPoint: end };
}

/** Arc from Start, End, and Tangent Direction at Start in radians. */
export function arcStartEndDirection(start: Point2D, end: Point2D, tangentAngleRad: number): ArcGeom {
	const d = Math.hypot(end[0] - start[0], end[1] - start[1]);
	if (d < 1e-12) throw new Error('Start and end points must be distinct');

	// Tangent unit vector T, Normal to tangent pointing to center N
	const tX = Math.cos(tangentAngleRad), tY = Math.sin(tangentAngleRad);
	const nX = -tY, nY = tX; // 90° CCW

	// Center is on line start + r * N, and on perpendicular bisector of chord SE
	// mid + s * (-uY, uX)
	const midX = (start[0] + end[0]) / 2, midY = (start[1] + end[1]) / 2;
	const chordX = end[0] - start[0], chordY = end[1] - start[1];

	// Dot product: (C - mid) · chord = 0  =>  (start + r*N - mid) · chord = 0
	// (start - mid) · chord + r * (N · chord) = 0
	const smX = start[0] - midX, smY = start[1] - midY;
	const nDotChord = nX * chordX + nY * chordY;
	if (Math.abs(nDotChord) < 1e-12) throw new Error('Direction cannot be collinear with chord');
	const r = -(smX * chordX + smY * chordY) / nDotChord;

	const center: Point2D = [start[0] + r * nX, start[1] + r * nY];
	const radius = Math.abs(r);
	const startAngle = normalizeAngleRad(Math.atan2(start[1] - center[1], start[0] - center[0]));
	const endAngle = normalizeAngleRad(Math.atan2(end[1] - center[1], end[0] - center[0]));
	return { center, radius, startAngle, endAngle, startPoint: start, endPoint: end };
}

/** Arc from Start, End, and Radius. */
export function arcStartEndRadius(start: Point2D, end: Point2D, radius: number, majorArc: boolean = false): ArcGeom {
	const d = Math.hypot(end[0] - start[0], end[1] - start[1]);
	if (d < 1e-12) throw new Error('Start and end points must be distinct');
	if (d > 2 * radius) throw new Error('Radius is too small for chord');

	const h = Math.sqrt(Math.max(0, radius * radius - (d / 2) * (d / 2)));
	const mid: Point2D = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
	const u = [(end[0] - start[0]) / d, (end[1] - start[1]) / d];
	const n = [-u[1], u[0]];
	const sign = majorArc ? -1 : 1;
	const center: Point2D = [mid[0] + sign * h * n[0], mid[1] + sign * h * n[1]];
	const startAngle = normalizeAngleRad(Math.atan2(start[1] - center[1], start[0] - center[0]));
	const endAngle = normalizeAngleRad(Math.atan2(end[1] - center[1], end[0] - center[0]));
	return { center, radius, startAngle, endAngle, startPoint: start, endPoint: end };
}

/** Arc from Center, Start, and End points. */
export function arcCenterStartEnd(center: Point2D, start: Point2D, end: Point2D): ArcGeom {
	return arcStartCenterEnd(start, center, end);
}

/** Continue arc tangent from last line or arc endpoint. */
export function arcContinue(lastEndpoint: Point2D, lastTangentAngleRad: number, end: Point2D): ArcGeom {
	return arcStartEndDirection(lastEndpoint, end, lastTangentAngleRad);
}

// -----------------------------------------------------------------------------
// 3. RECTANG VARIANTS
// -----------------------------------------------------------------------------

function rotatePoint(pt: Point2D, origin: Point2D, angleRad: number): Point2D {
	if (Math.abs(angleRad) < 1e-12) return pt;
	const cos = Math.cos(angleRad), sin = Math.sin(angleRad);
	const dx = pt[0] - origin[0], dy = pt[1] - origin[1];
	return [origin[0] + dx * cos - dy * sin, origin[1] + dx * sin + dy * cos];
}

/** Closed rectangle polyline with fillets (bulges tan(22.5°) = sqrt(2)-1). */
export function rectangleFillet(p1: Point2D, p2: Point2D, filletRadius: number, rotationRad: number = 0): PolylineGeom {
	const xmin = Math.min(p1[0], p2[0]), xmax = Math.max(p1[0], p2[0]);
	const ymin = Math.min(p1[1], p2[1]), ymax = Math.max(p1[1], p2[1]);
	const w = xmax - xmin, h = ymax - ymin;
	const r = Math.max(0, Math.min(filletRadius, w / 2, h / 2));

	if (r < 1e-12) {
		const rawPts: Point2D[] = [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]];
		return {
			points: rawPts.map(pt => rotatePoint(pt, p1, rotationRad)),
			bulges: [0, 0, 0, 0],
			closed: true,
		};
	}

	const cornerBulge = Math.tan(Math.PI / 8); // tan(22.5°) = 0.41421356...
	const rawPts: Point2D[] = [
		[xmin + r, ymin],     // V0
		[xmax - r, ymin],     // V1 -> fillet arc to V2
		[xmax, ymin + r],     // V2
		[xmax, ymax - r],     // V3 -> fillet arc to V4
		[xmax - r, ymax],     // V4
		[xmin + r, ymax],     // V5 -> fillet arc to V6
		[xmin, ymax - r],     // V6
		[xmin, ymin + r],     // V7 -> fillet arc to V0
	];

	return {
		points: rawPts.map(pt => rotatePoint(pt, p1, rotationRad)),
		bulges: [0, cornerBulge, 0, cornerBulge, 0, cornerBulge, 0, cornerBulge],
		closed: true,
	};
}

/** Closed rectangle polyline with chamfers. */
export function rectangleChamfer(p1: Point2D, p2: Point2D, d1: number, d2: number, rotationRad: number = 0): PolylineGeom {
	const xmin = Math.min(p1[0], p2[0]), xmax = Math.max(p1[0], p2[0]);
	const ymin = Math.min(p1[1], p2[1]), ymax = Math.max(p1[1], p2[1]);
	const w = xmax - xmin, h = ymax - ymin;
	const cd1 = Math.max(0, Math.min(d1, w / 2));
	const cd2 = Math.max(0, Math.min(d2, h / 2));

	if (cd1 < 1e-12 && cd2 < 1e-12) {
		const rawPts: Point2D[] = [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]];
		return {
			points: rawPts.map(pt => rotatePoint(pt, p1, rotationRad)),
			bulges: [0, 0, 0, 0],
			closed: true,
		};
	}

	const rawPts: Point2D[] = [
		[xmin + cd1, ymin],
		[xmax - cd1, ymin],
		[xmax, ymin + cd2],
		[xmax, ymax - cd2],
		[xmax - cd1, ymax],
		[xmin + cd1, ymax],
		[xmin, ymax - cd2],
		[xmin, ymin + cd2],
	];

	return {
		points: rawPts.map(pt => rotatePoint(pt, p1, rotationRad)),
		bulges: [0, 0, 0, 0, 0, 0, 0, 0],
		closed: true,
	};
}

/** Closed rectangle polyline by Length, Width, and Rotation. */
export function rectangleDimensions(p1: Point2D, length: number, width: number, rotationRad: number = 0): PolylineGeom {
	const cos = Math.cos(rotationRad), sin = Math.sin(rotationRad);
	const v0 = p1;
	const v1: Point2D = [p1[0] + length * cos, p1[1] + length * sin];
	const v2: Point2D = [v1[0] - width * sin, v1[1] + width * cos];
	const v3: Point2D = [p1[0] - width * sin, p1[1] + width * cos];
	return {
		points: [v0, v1, v2, v3],
		bulges: [0, 0, 0, 0],
		closed: true,
	};
}

/** Closed rectangle polyline by Area and one known dimension. */
export function rectangleArea(
	p1: Point2D,
	area: number,
	known: { length?: number; width?: number },
	rotationRad: number = 0,
): PolylineGeom {
	if (area <= 0) throw new Error('Area must be positive');
	let length: number;
	let width: number;
	if (known.length !== undefined && known.length > 0) {
		length = known.length;
		width = area / length;
	} else if (known.width !== undefined && known.width > 0) {
		width = known.width;
		length = area / width;
	} else {
		throw new Error('Either length or width must be provided');
	}
	return rectangleDimensions(p1, length, width, rotationRad);
}

// -----------------------------------------------------------------------------
// 4. POLYGON VARIANTS
// -----------------------------------------------------------------------------

/** Polygon inscribed in a circle of given radius. */
export function polygonInscribed(center: Point2D, radius: number, sides: number, startAngleRad: number = 0): PolylineGeom {
	if (sides < 3) throw new Error('Polygon must have at least 3 sides');
	if (radius <= 0) throw new Error('Radius must be positive');
	const step = (2 * Math.PI) / sides;
	const points: Point2D[] = [];
	for (let i = 0; i < sides; i++) {
		const angle = startAngleRad + i * step;
		points.push([center[0] + radius * Math.cos(angle), center[1] + radius * Math.sin(angle)]);
	}
	return { points, bulges: new Array(sides).fill(0), closed: true };
}

/** Polygon circumscribed about a circle of given radius. */
export function polygonCircumscribed(center: Point2D, radius: number, sides: number, startAngleRad: number = 0): PolylineGeom {
	if (sides < 3) throw new Error('Polygon must have at least 3 sides');
	if (radius <= 0) throw new Error('Radius must be positive');
	// Distance from center to vertex = radius / cos(π / sides)
	const vertexRadius = radius / Math.cos(Math.PI / sides);
	const step = (2 * Math.PI) / sides;
	const points: Point2D[] = [];
	for (let i = 0; i < sides; i++) {
		const angle = startAngleRad + i * step;
		points.push([center[0] + vertexRadius * Math.cos(angle), center[1] + vertexRadius * Math.sin(angle)]);
	}
	return { points, bulges: new Array(sides).fill(0), closed: true };
}

/** Polygon defined by first edge endpoints. */
export function polygonEdge(p1: Point2D, p2: Point2D, sides: number): PolylineGeom {
	if (sides < 3) throw new Error('Polygon must have at least 3 sides');
	const edgeLen = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
	if (edgeLen < 1e-12) throw new Error('Edge endpoints must be distinct');

	const extAngle = (2 * Math.PI) / sides;
	let currentAngle = Math.atan2(p2[1] - p1[1], p2[0] - p1[0]);
	const points: Point2D[] = [p1, p2];
	let current = p2;

	for (let i = 2; i < sides; i++) {
		currentAngle += extAngle;
		const next: Point2D = [current[0] + edgeLen * Math.cos(currentAngle), current[1] + edgeLen * Math.sin(currentAngle)];
		points.push(next);
		current = next;
	}

	return { points, bulges: new Array(sides).fill(0), closed: true };
}

// -----------------------------------------------------------------------------
// 5. DONUT
// -----------------------------------------------------------------------------

export interface DonutGeom extends PolylineGeom {
	readonly meanRadius: number;
	readonly width: number;
}

/** Donut as a closed LWPOLYLINE of two bulge-1 segments with constant width. */
export function donut(center: Point2D, insideDiameter: number, outsideDiameter: number): DonutGeom {
	let rIn = Math.max(0, insideDiameter) / 2;
	let rOut = Math.max(0, outsideDiameter) / 2;
	if (rOut < rIn) {
		const temp = rOut;
		rOut = rIn;
		rIn = temp;
	}
	const width = rOut - rIn;
	const meanRadius = (rIn + rOut) / 2;
	if (meanRadius < 1e-12) {
		throw new Error('Donut outside diameter must be greater than zero');
	}

	// Two semicircles: from (-R, 0) to (+R, 0) bulge 1, then back to (-R, 0) bulge 1
	const v0: Point2D = [center[0] - meanRadius, center[1]];
	const v1: Point2D = [center[0] + meanRadius, center[1]];

	return {
		points: [v0, v1],
		bulges: [1, 1],
		closed: true,
		constantWidth: width,
		meanRadius,
		width,
	};
}
