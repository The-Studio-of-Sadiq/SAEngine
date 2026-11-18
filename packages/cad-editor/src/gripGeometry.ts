/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Pure 2D geometry functions for AutoCAD grip editing:
 * - ROTATE, SCALE, MIRROR about grip base point
 * - LWPOLYLINE vertex addition, vertex removal, and segment arc conversion
 */

export type GripPoint2D = readonly [number, number];
export type Point2D = GripPoint2D;

/**
 * Rotates a 2D point about base point by angle in degrees.
 * Positive angle is counter-clockwise.
 */
export function rotateGripPoint(
	point: GripPoint2D,
	base: GripPoint2D,
	angleDeg: number
): [number, number] {
	const rad = (angleDeg * Math.PI) / 180;
	const cos = Math.cos(rad);
	const sin = Math.sin(rad);
	const dx = point[0] - base[0];
	const dy = point[1] - base[1];
	const rx = base[0] + dx * cos - dy * sin;
	const ry = base[1] + dx * sin + dy * cos;
	const rrx = Math.abs(rx) < 1e-10 ? 0 : Number(rx.toFixed(6));
	const rry = Math.abs(ry) < 1e-10 ? 0 : Number(ry.toFixed(6));
	return [rrx, rry];
}

/**
 * Scales a 2D point about base point by a scale factor.
 */
export function scaleGripPoint(
	point: GripPoint2D,
	base: GripPoint2D,
	factor: number
): [number, number] {
	const rx = base[0] + (point[0] - base[0]) * factor;
	const ry = base[1] + (point[1] - base[1]) * factor;
	const rrx = Math.abs(rx) < 1e-10 ? 0 : Number(rx.toFixed(6));
	const rry = Math.abs(ry) < 1e-10 ? 0 : Number(ry.toFixed(6));
	return [rrx, rry];
}

/**
 * Mirrors a 2D point across a mirror line defined by two points.
 */
export function mirrorGripPoint(
	point: GripPoint2D,
	lineP1: GripPoint2D,
	lineP2: GripPoint2D
): [number, number] {
	const dx = lineP2[0] - lineP1[0];
	const dy = lineP2[1] - lineP1[1];
	const lenSq = dx * dx + dy * dy;
	if (lenSq < 1e-18) throw new Error('Mirror line points must be distinct');
	const t = ((point[0] - lineP1[0]) * dx + (point[1] - lineP1[1]) * dy) / lenSq;
	const projX = lineP1[0] + t * dx;
	const projY = lineP1[1] + t * dy;
	const rx = 2 * projX - point[0];
	const ry = 2 * projY - point[1];
	const rrx = Math.abs(rx) < 1e-10 ? 0 : Number(rx.toFixed(6));
	const rry = Math.abs(ry) < 1e-10 ? 0 : Number(ry.toFixed(6));
	return [rrx, rry];
}
export const mirrorPoint2D = mirrorGripPoint;

/**
 * Adds a vertex to a polyline after the specified vertex index.
 * If newPoint is not provided, defaults to the midpoint of that segment.
 */
export function addPolylineVertex(
	vertices: readonly GripPoint2D[],
	afterIndex: number,
	newPoint?: GripPoint2D,
	bulges?: readonly number[]
): { vertices: [number, number][]; bulges?: number[] } {
	const pts: [number, number][] = vertices.map(p => [p[0], p[1]]);
	const p1 = vertices[afterIndex];
	const nextIdx = (afterIndex + 1) % vertices.length;
	const p2 = vertices[nextIdx];
	const pt: [number, number] = newPoint ? [newPoint[0], newPoint[1]] : [
		(p1[0] + p2[0]) / 2,
		(p1[1] + p2[1]) / 2,
	];
	pts.splice(afterIndex + 1, 0, pt);

	let newBulges: number[] | undefined;
	if (bulges) {
		newBulges = [...bulges];
		const b = bulges[afterIndex] ?? 0;
		if (Math.abs(b) < 1e-9) {
			newBulges.splice(afterIndex + 1, 0, 0);
		} else {
			const halfB = Math.tan(Math.atan(b) / 2);
			newBulges[afterIndex] = halfB;
			newBulges.splice(afterIndex + 1, 0, halfB);
		}
	}
	return { vertices: pts, bulges: newBulges };
}

/**
 * Removes a vertex from a polyline at the specified index.
 * Does not remove if polyline has 2 or fewer vertices.
 */
export function removePolylineVertex(
	vertices: readonly GripPoint2D[],
	indexToRemove: number,
	bulges?: readonly number[]
): { vertices: [number, number][]; bulges?: number[] } {
	if (vertices.length <= 2) {
		return {
			vertices: vertices.map(p => [p[0], p[1]]),
			bulges: bulges ? [...bulges] : undefined,
		};
	}
	const pts = vertices.filter((_, i) => i !== indexToRemove).map(p => [p[0], p[1]] as [number, number]);
	let newBulges: number[] | undefined;
	if (bulges) {
		newBulges = [...bulges];
		newBulges.splice(indexToRemove, 1);
	}
	return { vertices: pts, bulges: newBulges };
}

/**
 * Calculates the AutoCAD bulge factor for an arc segment from p1 to p2 passing through throughPoint.
 * Bulge = tan(theta / 4).
 * Positive sign indicates a counter-clockwise arc (curving to the left of p1 -> p2).
 */
export function convertSegmentToArc(
	p1: GripPoint2D,
	p2: GripPoint2D,
	throughPoint: GripPoint2D
): number {
	const dx = p2[0] - p1[0];
	const dy = p2[1] - p1[1];
	const d = Math.hypot(dx, dy);
	if (d < 1e-9) return 0;

	// Cross product of (p2 - p1) with (throughPoint - p1)
	const cdx = throughPoint[0] - p1[0];
	const cdy = throughPoint[1] - p1[1];
	const cross = dx * cdy - dy * cdx;
	if (Math.abs(cross) < 1e-9) return 0; // Collinear

	// Circumcenter of triangle (p1, p2, throughPoint)
	const ax = p1[0], ay = p1[1];
	const bx = p2[0], by = p2[1];
	const cx = throughPoint[0], cy = throughPoint[1];
	const D = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
	if (Math.abs(D) < 1e-9) return 0;

	const a2 = ax * ax + ay * ay;
	const b2 = bx * bx + by * by;
	const c2 = cx * cx + cy * cy;
	const ox = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / D;
	const oy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / D;

	const radius = Math.hypot(ax - ox, ay - oy);

	// Midpoint of chord
	const mx = (ax + bx) / 2;
	const my = (ay + by) / 2;
	const centerToChord = Math.hypot(ox - mx, oy - my);

	// Check if center and throughPoint are on the same side of chord
	const crossCenter = dx * (oy - ay) - dy * (ox - ax);
	const sameSide = (cross * crossCenter) > 0;

	let h: number;
	if (centerToChord < 1e-9) {
		h = radius; // Semicircle
	} else if (sameSide) {
		h = radius - centerToChord;
	} else {
		h = radius + centerToChord;
	}

	const bulgeMag = (2 * h) / d;
	const sign = cross > 0 ? 1 : -1;
	return Number((sign * bulgeMag).toFixed(6));
}
export const segmentToArcBulge = convertSegmentToArc;
