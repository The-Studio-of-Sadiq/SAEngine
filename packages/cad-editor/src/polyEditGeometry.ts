/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

export type PolyPoint2D = [number, number];
export type Point2D = PolyPoint2D;

export interface ArcFitResult {
	points: Point2D[];
	bulges: number[];
}

/**
 * Calculates the circumscribed circle passing through 3 2D points.
 * Returns null if the points are collinear within tolerance.
 * isCW indicates whether the triplet p1 -> p2 -> p3 turns clockwise.
 */
export function circleFrom3Points(
	p1: Point2D,
	p2: Point2D,
	p3: Point2D,
	tolerance = 1e-9,
): { center: Point2D; radius: number; isCW: boolean } | null {
	const x1 = p1[0], y1 = p1[1];
	const x2 = p2[0], y2 = p2[1];
	const x3 = p3[0], y3 = p3[1];

	const D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2));
	if (Math.abs(D) < tolerance) {
		return null;
	}

	const sq1 = x1 * x1 + y1 * y1;
	const sq2 = x2 * x2 + y2 * y2;
	const sq3 = x3 * x3 + y3 * y3;

	const cx = (sq1 * (y2 - y3) + sq2 * (y3 - y1) + sq3 * (y1 - y2)) / D;
	const cy = (sq1 * (x3 - x2) + sq2 * (x1 - x3) + sq3 * (x2 - x1)) / D;

	const radius = Math.hypot(x1 - cx, y1 - cy);
	// Cross product of (p2 - p1) and (p3 - p2): positive is CCW, negative is CW
	const cross = (x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2);
	const isCW = cross < 0;

	return { center: [cx, cy], radius, isCW };
}

/**
 * Calculates the bulge factor for an arc segment from p1 to p2 on a circle with known center.
 * Bulge = tan(sweepAngle / 4), with negative sign for clockwise traversal.
 */
export function arcBulgeForSegment(p1: Point2D, p2: Point2D, center: Point2D, isCW: boolean): number {
	const a1 = Math.atan2(p1[1] - center[1], p1[0] - center[0]);
	const a2 = Math.atan2(p2[1] - center[1], p2[0] - center[0]);

	let sweep = isCW ? (a1 - a2) : (a2 - a1);
	while (sweep < 0) sweep += 2 * Math.PI;
	while (sweep >= 2 * Math.PI) sweep -= 2 * Math.PI;

	const b = Math.tan(sweep / 4);
	return isCW ? -b : b;
}

/**
 * Fits tangent circular arcs through polyline vertices as bulges.
 * For 3 points, both segments lie on the unique circle through the 3 points.
 * For N points, interior segments blend local 3-point circle bulges.
 */
export function fitArcBulges(points: readonly Point2D[], closed = false): ArcFitResult {
	const n = points.length;
	if (n < 3) {
		const bulges = closed ? new Array(n).fill(0) : new Array(Math.max(0, n - 1)).fill(0);
		return { points: points.map(p => [p[0], p[1]]), bulges };
	}

	const segCount = closed ? n : n - 1;
	const bulges: number[] = new Array(segCount).fill(0);

	if (n === 3 && !closed) {
		const circle = circleFrom3Points(points[0], points[1], points[2]);
		if (circle) {
			bulges[0] = arcBulgeForSegment(points[0], points[1], circle.center, circle.isCW);
			bulges[1] = arcBulgeForSegment(points[1], points[2], circle.center, circle.isCW);
		}
		return { points: points.map(p => [p[0], p[1]]), bulges };
	}

	for (let i = 0; i < segCount; i++) {
		const pStart = points[i];
		const pEnd = points[(i + 1) % n];

		if (!closed) {
			if (i === 0) {
				const c = circleFrom3Points(points[0], points[1], points[2]);
				bulges[i] = c ? arcBulgeForSegment(pStart, pEnd, c.center, c.isCW) : 0;
			} else if (i === n - 2) {
				const c = circleFrom3Points(points[n - 3], points[n - 2], points[n - 1]);
				bulges[i] = c ? arcBulgeForSegment(pStart, pEnd, c.center, c.isCW) : 0;
			} else {
				const c1 = circleFrom3Points(points[i - 1], points[i], points[i + 1]);
				const c2 = circleFrom3Points(points[i], points[i + 1], points[i + 2]);
				const b1 = c1 ? arcBulgeForSegment(pStart, pEnd, c1.center, c1.isCW) : 0;
				const b2 = c2 ? arcBulgeForSegment(pStart, pEnd, c2.center, c2.isCW) : 0;
				bulges[i] = (b1 + b2) / 2;
			}
		} else {
			const prev = points[(i - 1 + n) % n];
			const next = points[(i + 1) % n];
			const next2 = points[(i + 2) % n];
			const c1 = circleFrom3Points(prev, pStart, next);
			const c2 = circleFrom3Points(pStart, next, next2);
			const b1 = c1 ? arcBulgeForSegment(pStart, pEnd, c1.center, c1.isCW) : 0;
			const b2 = c2 ? arcBulgeForSegment(pStart, pEnd, c2.center, c2.isCW) : 0;
			bulges[i] = (b1 + b2) / 2;
		}
	}

	return { points: points.map(p => [p[0], p[1]]), bulges };
}

/**
 * Evaluates a single point on a B-spline curve with clamped uniform knot vector at parameter t in [0, 1].
 */
export function bSplinePoint(controlPoints: readonly Point2D[], degree: number, t: number): Point2D {
	const n = controlPoints.length;
	if (n === 0) return [0, 0];
	if (n === 1) return [controlPoints[0][0], controlPoints[0][1]];

	const p = Math.min(degree, n - 1);
	if (t <= 0) return [controlPoints[0][0], controlPoints[0][1]];
	if (t >= 1) return [controlPoints[n - 1][0], controlPoints[n - 1][1]];

	// Build clamped uniform knot vector: m = n + p + 1
	const m = n + p + 1;
	const knots: number[] = new Array(m);
	for (let i = 0; i <= p; i++) knots[i] = 0;
	for (let i = m - 1 - p; i < m; i++) knots[i] = 1;
	for (let i = p + 1; i < m - 1 - p; i++) {
		knots[i] = (i - p) / (n - p);
	}

	// Find knot span k such that knots[k] <= t < knots[k + 1]
	let k = p;
	while (k < n && knots[k + 1] <= t) {
		k++;
	}

	// De Boor's algorithm
	const d: Point2D[] = [];
	for (let j = 0; j <= p; j++) {
		const cpIndex = j + k - p;
		d[j] = [controlPoints[cpIndex][0], controlPoints[cpIndex][1]];
	}

	for (let r = 1; r <= p; r++) {
		for (let j = p; j >= r; j--) {
			const denom = knots[j + k - r + 1] - knots[j + k - p];
			const alpha = denom === 0 ? 0 : (t - knots[j + k - p]) / denom;
			d[j] = [
				(1 - alpha) * d[j - 1][0] + alpha * d[j][0],
				(1 - alpha) * d[j - 1][1] + alpha * d[j][1],
			];
		}
	}

	return d[p];
}

/**
 * Computes a B-spline approximation of polyline vertices using SPLINESEGS segments per span.
 */
export function bSplinePolyline(
	controlPoints: readonly Point2D[],
	degree = 2,
	segmentsPerSpan = 8,
	closed = false,
): Point2D[] {
	const n = controlPoints.length;
	if (n <= 1) return controlPoints.map(p => [p[0], p[1]]);

	let pts = [...controlPoints];
	if (closed) {
		// Wrap control points for closed curve
		for (let i = 0; i < degree; i++) {
			pts.push(controlPoints[i]);
		}
	}

	const spans = pts.length - 1;
	const totalSegments = Math.max(1, spans * Math.max(1, segmentsPerSpan));
	const result: Point2D[] = [];

	for (let i = 0; i <= totalSegments; i++) {
		const t = i / totalSegments;
		result.push(bSplinePoint(pts, degree, t));
	}

	return result;
}

/**
 * Removes duplicate consecutive vertices within tolerance from polyline vertex list.
 */
export function removeDuplicateVertices(
	points: readonly Point2D[],
	bulges?: readonly number[],
	closed = false,
	tolerance = 1e-6,
): { points: Point2D[]; bulges: number[]; removedCount: number } {
	if (points.length <= 1) {
		return {
			points: points.map(p => [p[0], p[1]]),
			bulges: bulges ? [...bulges] : [],
			removedCount: 0,
		};
	}

	const newPoints: Point2D[] = [points[0]];
	const newBulges: number[] = [];
	let removedCount = 0;

	for (let i = 1; i < points.length; i++) {
		const prev = newPoints[newPoints.length - 1];
		const curr = points[i];
		const dist = Math.hypot(curr[0] - prev[0], curr[1] - prev[1]);
		if (dist <= tolerance) {
			removedCount++;
		} else {
			if (bulges && bulges.length >= i) {
				newBulges.push(bulges[i - 1]);
			}
			newPoints.push(curr);
		}
	}

	// For closed polyline, check if last vertex equals first vertex
	if (closed && newPoints.length > 2) {
		const first = newPoints[0];
		const last = newPoints[newPoints.length - 1];
		if (Math.hypot(first[0] - last[0], first[1] - last[1]) <= tolerance) {
			newPoints.pop();
			removedCount++;
		}
	}

	return { points: newPoints, bulges: newBulges, removedCount };
}

export interface CollinearLine<T = unknown> {
	start: Point2D;
	end: Point2D;
	data?: T;
}

/**
 * Merges overlapping and/or end-to-end collinear line segments within tolerance.
 */
export function mergeCollinearLines<T extends CollinearLine>(
	lines: readonly T[],
	options: {
		tolerance?: number;
		combinePartialOverlap?: boolean;
		combineEndToEnd?: boolean;
	} = {},
): { merged: T[]; deletedCount: number; mergedCount: number } {
	const tol = options.tolerance ?? 1e-6;
	const combinePartial = options.combinePartialOverlap ?? true;
	const combineEnd = options.combineEndToEnd ?? false;

	const pool: T[] = lines
		.filter(l => Math.hypot(l.end[0] - l.start[0], l.end[1] - l.start[1]) > tol)
		.map(l => ({ ...l }));

	let deletedCount = lines.length - pool.length; // zero-length lines removed
	let mergedCount = 0;
	let changed = true;

	while (changed) {
		changed = false;
		for (let i = 0; i < pool.length; i++) {
			for (let j = i + 1; j < pool.length; j++) {
				const lineA = pool[i];
				const lineB = pool[j];

				const vAx = lineA.end[0] - lineA.start[0];
				const vAy = lineA.end[1] - lineA.start[1];
				const lenA = Math.hypot(vAx, vAy);

				const vBx = lineB.end[0] - lineB.start[0];
				const vBy = lineB.end[1] - lineB.start[1];
				const lenB = Math.hypot(vBx, vBy);

				if (lenA <= tol || lenB <= tol) continue;

				const uAx = vAx / lenA;
				const uAy = vAy / lenA;
				const uBx = vBx / lenB;
				const uBy = vBy / lenB;

				// Check if parallel: cross product approx 0
				const cross = uAx * uBy - uAy * uBx;
				if (Math.abs(cross) > tol) continue;

				// Check if lineB points lie on infinite lineA
				const distStart = Math.abs((lineB.start[0] - lineA.start[0]) * uAy - (lineB.start[1] - lineA.start[1]) * uAx);
				const distEnd = Math.abs((lineB.end[0] - lineA.start[0]) * uAy - (lineB.end[1] - lineA.start[1]) * uAx);
				if (distStart > tol || distEnd > tol) continue;

				// Project endpoints onto lineA direction
				const tA1 = 0;
				const tA2 = lenA;
				const tB1 = (lineB.start[0] - lineA.start[0]) * uAx + (lineB.start[1] - lineA.start[1]) * uAy;
				const tB2 = (lineB.end[0] - lineA.start[0]) * uAx + (lineB.end[1] - lineA.start[1]) * uAy;

				const minA = Math.min(tA1, tA2);
				const maxA = Math.max(tA1, tA2);
				const minB = Math.min(tB1, tB2);
				const maxB = Math.max(tB1, tB2);

				const overlap = Math.min(maxA, maxB) - Math.max(minA, minB);

				let shouldMerge = false;
				if (combinePartial && overlap > tol) {
					shouldMerge = true;
				} else if (combineEnd && Math.abs(overlap) <= tol && Math.max(minA, minB) <= Math.min(maxA, maxB) + tol) {
					shouldMerge = true;
				}

				if (shouldMerge) {
					const newMin = Math.min(minA, minB);
					const newMax = Math.max(maxA, maxB);

					lineA.start = [lineA.start[0] + newMin * uAx, lineA.start[1] + newMin * uAy];
					lineA.end = [lineA.start[0] + (newMax - newMin) * uAx, lineA.start[1] + (newMax - newMin) * uAy];

					pool.splice(j, 1);
					mergedCount++;
					deletedCount++;
					changed = true;
					break;
				}
			}
			if (changed) break;
		}
	}

	return { merged: pool, deletedCount, mergedCount };
}

/**
 * Finds and removes exact duplicate items within tolerance.
 */
export function findDuplicateEntities<T>(
	entities: readonly T[],
	areEqual: (a: T, b: T, tol: number) => boolean,
	tolerance = 1e-6,
): { unique: T[]; duplicates: T[] } {
	const unique: T[] = [];
	const duplicates: T[] = [];

	for (const e of entities) {
		const isDup = unique.some(u => areEqual(u, e, tolerance));
		if (isDup) {
			duplicates.push(e);
		} else {
			unique.push(e);
		}
	}

	return { unique, duplicates };
}

export interface ChainSegment2D {
	points: Point2D[];
	bulges: number[];
}

/**
 * Joins chain segments within a fuzz distance.
 */
export function joinPolylineChains(
	chains: readonly ChainSegment2D[],
	fuzz = 0,
): { points: Point2D[]; bulges: number[]; joinedCount: number } | null {
	if (chains.length === 0) return null;

	const near = (p: Point2D, q: Point2D) => Math.hypot(p[0] - q[0], p[1] - q[1]) <= fuzz + 1e-6;

	const currentPoints = [...chains[0].points.map(p => [p[0], p[1]] as Point2D)];
	const currentBulges = [...chains[0].bulges];
	const pool = chains.slice(1).map(c => ({
		points: c.points.map(p => [p[0], p[1]] as Point2D),
		bulges: [...c.bulges],
	}));

	let joinedCount = 0;
	let progressed = true;

	while (progressed) {
		progressed = false;
		for (let i = 0; i < pool.length; i++) {
			const cand = pool[i];
			const head = currentPoints[0];
			const tail = currentPoints[currentPoints.length - 1];
			const candHead = cand.points[0];
			const candTail = cand.points[cand.points.length - 1];

			if (near(tail, candHead)) {
				currentPoints.push(...cand.points.slice(1));
				currentBulges.push(...cand.bulges);
				pool.splice(i, 1);
				joinedCount++;
				progressed = true;
				break;
			} else if (near(tail, candTail)) {
				const revPts = [...cand.points].reverse();
				const revBulges = [...cand.bulges].reverse().map(b => -b);
				currentPoints.push(...revPts.slice(1));
				currentBulges.push(...revBulges);
				pool.splice(i, 1);
				joinedCount++;
				progressed = true;
				break;
			} else if (near(head, candTail)) {
				currentPoints.unshift(...cand.points.slice(0, -1));
				currentBulges.unshift(...cand.bulges);
				pool.splice(i, 1);
				joinedCount++;
				progressed = true;
				break;
			} else if (near(head, candHead)) {
				const revPts = [...cand.points].reverse();
				const revBulges = [...cand.bulges].reverse().map(b => -b);
				currentPoints.unshift(...revPts.slice(0, -1));
				currentBulges.unshift(...revBulges);
				pool.splice(i, 1);
				joinedCount++;
				progressed = true;
				break;
			}
		}
	}

	return { points: currentPoints, bulges: currentBulges, joinedCount };
}
