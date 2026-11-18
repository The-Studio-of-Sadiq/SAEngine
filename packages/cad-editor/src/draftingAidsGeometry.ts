/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

export interface DraftingPoint2D {
	readonly x: number;
	readonly y: number;
}

export interface DraftingPoint3D extends DraftingPoint2D {
	readonly z?: number;
}

export type Point2D = DraftingPoint2D;
export type Point3D = DraftingPoint3D;

/**
 * Computes the perpendicular foot from `point` onto the infinite line through `lineStart` and `lineEnd`.
 * Preserves point.z (or 0 if undefined).
 */
export function perpendicularFoot(point: Point3D, lineStart: Point3D, lineEnd: Point3D): Point3D {
	const dx = lineEnd.x - lineStart.x;
	const dy = lineEnd.y - lineStart.y;
	const lenSq = dx * dx + dy * dy;
	if (lenSq < 1e-14) {
		return { x: lineStart.x, y: lineStart.y, z: point.z ?? 0 };
	}
	const t = ((point.x - lineStart.x) * dx + (point.y - lineStart.y) * dy) / lenSq;
	return {
		x: lineStart.x + t * dx,
		y: lineStart.y + t * dy,
		z: point.z ?? 0,
	};
}

/**
 * Computes the tangent points on a circle (center, radius) from an external point.
 * Returns an array of tangent points (0, 1, or 2).
 */
export function tangentPointsToCircle(point: Point3D, center: Point3D, radius: number): Point3D[] {
	if (radius <= 0) return [];
	const dx = point.x - center.x;
	const dy = point.y - center.y;
	const d = Math.hypot(dx, dy);
	if (d < radius - 1e-9) {
		// Inside circle: no real tangents
		return [];
	}
	const z = center.z ?? point.z ?? 0;
	if (Math.abs(d - radius) <= 1e-9) {
		// On circle
		return [{ x: point.x, y: point.y, z }];
	}
	const phi = Math.atan2(dy, dx);
	const alpha = Math.acos(Math.min(1, Math.max(-1, radius / d)));
	const angle1 = phi + alpha;
	const angle2 = phi - alpha;
	return [
		{
			x: center.x + radius * Math.cos(angle1),
			y: center.y + radius * Math.sin(angle1),
			z,
		},
		{
			x: center.x + radius * Math.cos(angle2),
			y: center.y + radius * Math.sin(angle2),
			z,
		},
	];
}

/**
 * Snaps a cursor angle in degrees to the nearest polar tracking increment.
 */
export function polarSnapAngle(cursorAngleDeg: number, incrementDeg: number, baseAngleDeg = 0): number {
	if (incrementDeg <= 0) return cursorAngleDeg;
	const rel = ((cursorAngleDeg - baseAngleDeg) % 360 + 360) % 360;
	const snappedRel = Math.round(rel / incrementDeg) * incrementDeg;
	return ((snappedRel + baseAngleDeg) % 360 + 360) % 360;
}

/**
 * Snaps a cursor point to the nearest polar tracking ray originating at `base`.
 */
export function snapPointToPolarRay(point: Point3D, base: Point3D, incrementDeg: number, baseAngleDeg = 0): Point3D {
	const dx = point.x - base.x;
	const dy = point.y - base.y;
	const dist = Math.hypot(dx, dy);
	if (dist < 1e-12 || incrementDeg <= 0) {
		return { x: point.x, y: point.y, z: point.z ?? base.z ?? 0 };
	}
	const currentDeg = Math.atan2(dy, dx) * 180 / Math.PI;
	const snappedDeg = polarSnapAngle(currentDeg, incrementDeg, baseAngleDeg);
	const snappedRad = snappedDeg * Math.PI / 180;
	return {
		x: base.x + dist * Math.cos(snappedRad),
		y: base.y + dist * Math.sin(snappedRad),
		z: point.z ?? base.z ?? 0,
	};
}

/**
 * Constrains a point to horizontal or vertical alignment relative to `base`.
 * Standard AutoCAD ORTHOMODE behavior:
 * If |dx| >= |dy|, moves horizontally (x from point, y from base).
 * If |dx| < |dy|, moves vertically (x from base, y from point).
 */
export function orthoConstraint(point: Point3D, base: Point3D): Point3D {
	const dx = point.x - base.x;
	const dy = point.y - base.y;
	if (Math.abs(dx) >= Math.abs(dy)) {
		return { x: point.x, y: base.y, z: point.z ?? base.z ?? 0 };
	}
	return { x: base.x, y: point.y, z: point.z ?? base.z ?? 0 };
}

/**
 * Snaps a point to grid spacing (SNAPUNIT).
 */
export function snapToGrid(point: Point3D, unit: number | [number, number]): Point3D {
	const unitX = typeof unit === 'number' ? unit : unit[0];
	const unitY = typeof unit === 'number' ? unit : unit[1];
	if (unitX <= 0 || unitY <= 0) {
		return { x: point.x, y: point.y, z: point.z ?? 0 };
	}
	return {
		x: Math.round(point.x / unitX) * unitX,
		y: Math.round(point.y / unitY) * unitY,
		z: point.z ?? 0,
	};
}

/**
 * Computes the geometric centre (centroid) of a closed polygon formed by vertices.
 * Uses the standard shoelace centroid formula.
 */
export function geometricCenter(vertices: ReadonlyArray<Point2D>): Point2D {
	const n = vertices.length;
	if (n === 0) return { x: 0, y: 0 };
	if (n < 3) {
		let sx = 0, sy = 0;
		for (const v of vertices) {
			sx += v.x;
			sy += v.y;
		}
		return { x: sx / n, y: sy / n };
	}

	let twiceArea = 0;
	let cx = 0;
	let cy = 0;

	for (let i = 0; i < n; i++) {
		const curr = vertices[i];
		const next = vertices[(i + 1) % n];
		const cross = curr.x * next.y - next.x * curr.y;
		twiceArea += cross;
		cx += (curr.x + next.x) * cross;
		cy += (curr.y + next.y) * cross;
	}

	if (Math.abs(twiceArea) < 1e-12) {
		// Degenerate/collinear polygon: fall back to vertex average
		let sx = 0, sy = 0;
		for (const v of vertices) {
			sx += v.x;
			sy += v.y;
		}
		return { x: sx / n, y: sy / n };
	}

	return {
		x: cx / (3 * twiceArea),
		y: cy / (3 * twiceArea),
	};
}
