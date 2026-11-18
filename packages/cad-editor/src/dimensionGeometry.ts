/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { P2 } from './modifyGeometry2.js';

export interface LineAngleResult {
	readonly vertex: P2;
	readonly p1: P2;
	readonly p2: P2;
	readonly angleRad: number;
	readonly angleDeg: number;
}

/**
 * Calculates the vertex, leg points, and angle between two infinite 2D lines.
 * Returns undefined if the lines are parallel.
 */
export function angleBetweenLines(
	a1: P2,
	a2: P2,
	b1: P2,
	b2: P2,
	pick1?: P2,
	pick2?: P2,
): LineAngleResult | undefined {
	const dx1 = a2[0] - a1[0], dy1 = a2[1] - a1[1];
	const dx2 = b2[0] - b1[0], dy2 = b2[1] - b1[1];
	const denom = dx1 * dy2 - dy1 * dx2;
	if (Math.abs(denom) < 1e-12) return undefined;

	const t = ((b1[0] - a1[0]) * dy2 - (b1[1] - a1[1]) * dx2) / denom;
	const vertex: P2 = [a1[0] + t * dx1, a1[1] + t * dy1];

	// Determine direction along line 1
	let v1: P2;
	if (pick1) {
		const d = [pick1[0] - vertex[0], pick1[1] - vertex[1]];
		if (Math.hypot(d[0], d[1]) > 1e-6) {
			v1 = [d[0], d[1]];
		} else {
			v1 = Math.hypot(a2[0] - vertex[0], a2[1] - vertex[1]) >= Math.hypot(a1[0] - vertex[0], a1[1] - vertex[1])
				? [a2[0] - vertex[0], a2[1] - vertex[1]]
				: [a1[0] - vertex[0], a1[1] - vertex[1]];
		}
	} else {
		v1 = Math.hypot(a2[0] - vertex[0], a2[1] - vertex[1]) >= Math.hypot(a1[0] - vertex[0], a1[1] - vertex[1])
			? [a2[0] - vertex[0], a2[1] - vertex[1]]
			: [a1[0] - vertex[0], a1[1] - vertex[1]];
	}

	// Determine direction along line 2
	let v2: P2;
	if (pick2) {
		const d = [pick2[0] - vertex[0], pick2[1] - vertex[1]];
		if (Math.hypot(d[0], d[1]) > 1e-6) {
			v2 = [d[0], d[1]];
		} else {
			v2 = Math.hypot(b2[0] - vertex[0], b2[1] - vertex[1]) >= Math.hypot(b1[0] - vertex[0], b1[1] - vertex[1])
				? [b2[0] - vertex[0], b2[1] - vertex[1]]
				: [b1[0] - vertex[0], b1[1] - vertex[1]];
		}
	} else {
		v2 = Math.hypot(b2[0] - vertex[0], b2[1] - vertex[1]) >= Math.hypot(b1[0] - vertex[0], b1[1] - vertex[1])
			? [b2[0] - vertex[0], b2[1] - vertex[1]]
			: [b1[0] - vertex[0], b1[1] - vertex[1]];
	}

	const len1 = Math.hypot(v1[0], v1[1]);
	const len2 = Math.hypot(v2[0], v2[1]);
	if (len1 < 1e-12 || len2 < 1e-12) return undefined;

	const cosAngle = Math.max(-1, Math.min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)));
	const angleRad = Math.acos(cosAngle);
	const angleDeg = angleRad * 180 / Math.PI;

	const p1: P2 = [vertex[0] + v1[0], vertex[1] + v1[1]];
	const p2: P2 = [vertex[0] + v2[0], vertex[1] + v2[1]];

	return { vertex, p1, p2, angleRad, angleDeg };
}

/** Normalized sweep angle of an arc in radians in range (0, 2π]. */
export function arcSweepAngle(startAngleRad: number, endAngleRad: number): number {
	const tau = 2 * Math.PI;
	const diff = ((endAngleRad - startAngleRad) % tau + tau) % tau;
	return diff === 0 ? tau : diff;
}

/** Radius measured between center and chord point. */
export function calculateRadius(center: P2, chordPoint: P2): number {
	return Math.hypot(chordPoint[0] - center[0], chordPoint[1] - center[1]);
}

/** Diameter measured between chord point and diametrically opposite point. */
export function calculateDiameter(chordPoint: P2, farChordPoint: P2): number {
	return Math.hypot(chordPoint[0] - farChordPoint[0], chordPoint[1] - farChordPoint[1]);
}

/** Arc length from radius and start/end angles in radians. */
export function calculateArcLength(radius: number, startAngleRad: number, endAngleRad: number): number {
	return radius * arcSweepAngle(startAngleRad, endAngleRad);
}

/**
 * Determines ordinate datum (X or Y) from leader direction.
 * If leader displacement in Y is greater than or equal to displacement in X,
 * the leader runs predominantly vertically, which measures the X coordinate (X datum).
 * Otherwise it runs horizontally, measuring the Y coordinate (Y datum).
 */
export function determineOrdinateDatum(featurePoint: P2, leaderEndPoint: P2): 'X' | 'Y' {
	const dx = Math.abs(leaderEndPoint[0] - featurePoint[0]);
	const dy = Math.abs(leaderEndPoint[1] - featurePoint[1]);
	return dy >= dx ? 'X' : 'Y';
}

/** Coordinate value according to ordinate datum. */
export function calculateOrdinateMeasurement(featurePoint: P2, datum: 'X' | 'Y'): number {
	return datum === 'X' ? featurePoint[0] : featurePoint[1];
}

/** Perpendicular unit normal pointing from segment (p1 -> p2) towards reference point ref. */
export function outwardNormal(p1: P2, p2: P2, ref: P2): P2 {
	const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
	const len = Math.hypot(dx, dy);
	if (len < 1e-12) return [0, 1];
	let nx = -dy / len, ny = dx / len;
	const dot = (ref[0] - p1[0]) * nx + (ref[1] - p1[1]) * ny;
	if (dot < 0) {
		nx = -nx;
		ny = -ny;
	}
	return [nx, ny];
}

/**
 * Computes dimension line location for DIMBASELINE offset by spacing * step
 * along the outward normal from the base dimension segment towards baseDimPt.
 */
export function calculateBaselineOffset(
	baseDimPt: P2,
	p1: P2,
	p2: P2,
	spacing: number,
	step = 1,
): P2 {
	const n = outwardNormal(p1, p2, baseDimPt);
	return [
		baseDimPt[0] + spacing * step * n[0],
		baseDimPt[1] + spacing * step * n[1],
	];
}

/**
 * Computes dimension line location for DIMCONTINUE so that the dimension line
 * lies on the exact same line as the base dimension line.
 */
export function calculateContinueDimLinePoint(
	p1: P2,
	p2: P2,
	baseDimPt: P2,
	nextPt: P2,
): P2 {
	const n = outwardNormal(p1, p2, baseDimPt);
	const normalDist = (baseDimPt[0] - p1[0]) * n[0] + (baseDimPt[1] - p1[1]) * n[1];
	const midX = (p2[0] + nextPt[0]) / 2;
	const midY = (p2[1] + nextPt[1]) / 2;
	return [
		midX + normalDist * n[0],
		midY + normalDist * n[1],
	];
}

/**
 * Extracts coordinates along specified axis from points, sorts them,
 * and deduplicates within tolerance.
 */
export function extractAndSortCoordinates(
	points: readonly P2[],
	axis: 'X' | 'Y',
	tolerance = 1e-4,
): number[] {
	const idx = axis === 'X' ? 0 : 1;
	const sorted = points.map(p => p[idx]).sort((a, b) => a - b);
	const unique: number[] = [];
	for (const val of sorted) {
		if (unique.length === 0 || Math.abs(val - unique[unique.length - 1]) > tolerance) {
			unique.push(val);
		}
	}
	return unique;
}
