/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbEntity, AcDbPolyline, AcDbResultBuffer,
	AcGePoint2d,
} from '@mlightcad/data-model';
import { polylineVertices } from './entityAccess.js';

export interface RegionPoint2D {
	readonly x: number;
	readonly y: number;
}

export interface RegionMassProperties {
	readonly area: number;
	readonly perimeter: number;
	readonly centroid: RegionPoint2D;
	readonly bbox: { readonly min: RegionPoint2D; readonly max: RegionPoint2D };
	/** Moments of inertia about centroid */
	readonly Ixx: number;
	readonly Iyy: number;
	readonly Ixy: number;
	/** Moments of inertia about origin */
	readonly IxOrigin: number;
	readonly IyOrigin: number;
	readonly IxyOrigin: number;
	/** Radii of gyration */
	readonly kx: number;
	readonly ky: number;
	/** Principal moments and directions */
	readonly principalMoments: { readonly I: number; readonly J: number };
	readonly principalAngle: number;
	readonly principalDirectionI: RegionPoint2D;
	readonly principalDirectionJ: RegionPoint2D;
}

export const REGION_APP_ID = 'AUTOCAD_REGION';

/** Tag an entity as a region using AutoCAD-compatible XData. */
export function tagEntityAsRegion(entity: AcDbEntity): void {
	const rb = new AcDbResultBuffer([
		{ code: 1001, value: REGION_APP_ID },
		{ code: 1000, value: 'REGION' },
	]);
	entity.setXData(rb);
}

/** Check if an entity is tagged as a region via XData. */
export function isEntityRegion(entity: AcDbEntity): boolean {
	const xdata = entity.getXData(REGION_APP_ID);
	if (!xdata) return false;
	const first = xdata.at(0);
	return first !== undefined && String(first.value).toUpperCase() === REGION_APP_ID;
}

/** Calculate signed polygon area (positive = CCW, negative = CW). */
export function signedPolygonArea(poly: readonly RegionPoint2D[]): number {
	let area = 0;
	const n = poly.length;
	for (let i = 0; i < n; i++) {
		const j = (i + 1) % n;
		area += poly[i].x * poly[j].y - poly[j].x * poly[i].y;
	}
	return area / 2;
}

/** Calculate perimeter of a closed polygon. */
export function polygonPerimeter(poly: readonly RegionPoint2D[]): number {
	let len = 0;
	const n = poly.length;
	for (let i = 0; i < n; i++) {
		const j = (i + 1) % n;
		len += Math.hypot(poly[j].x - poly[i].x, poly[j].y - poly[i].y);
	}
	return len;
}

/** Standard ray-casting test for point in polygon. */
export function isPointInPolygon(pt: RegionPoint2D, poly: readonly RegionPoint2D[]): boolean {
	let inside = false;
	const n = poly.length;
	for (let i = 0, j = n - 1; i < n; j = i++) {
		const xi = poly[i].x, yi = poly[i].y;
		const xj = poly[j].x, yj = poly[j].y;
		const intersect = ((yi > pt.y) !== (yj > pt.y)) &&
			(pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi);
		if (intersect) inside = !inside;
	}
	return inside;
}

/**
 * Approximates polyline bulges into straight segments using chord tolerance.
 */
export function approximatePolylineArcs(
	vertices: readonly RegionPoint2D[],
	bulges?: readonly number[],
	chordTolerance = 0.05,
): RegionPoint2D[] {
	if (!bulges || bulges.every(b => !b)) {
		return vertices.map(v => ({ x: v.x, y: v.y }));
	}

	const result: RegionPoint2D[] = [];
	const n = vertices.length;

	for (let i = 0; i < n; i++) {
		const p1 = vertices[i];
		const p2 = vertices[(i + 1) % n];
		const bulge = bulges[i] || 0;
		result.push({ x: p1.x, y: p1.y });

		if (Math.abs(bulge) > 1e-6) {
			const chord = Math.hypot(p2.x - p1.x, p2.y - p1.y);
			if (chord > 1e-6) {
				const theta = 4 * Math.atan(bulge);
				const radius = chord * (1 + bulge * bulge) / (4 * Math.abs(bulge));
				const numSteps = Math.max(4, Math.ceil(Math.abs(theta) / (2 * Math.acos(Math.max(-1, Math.min(1, 1 - chordTolerance / radius))))));

				const mx = (p1.x + p2.x) / 2;
				const my = (p1.y + p2.y) / 2;
				const h = chord * (1 - bulge * bulge) / (4 * bulge);
				const dx = (p2.x - p1.x) / chord;
				const dy = (p2.y - p1.y) / chord;
				const cx = mx - h * dy;
				const cy = my + h * dx;

				const startAngle = Math.atan2(p1.y - cy, p1.x - cx);
				const dAngle = theta / numSteps;

				for (let step = 1; step < numSteps; step++) {
					const ang = startAngle + step * dAngle;
					result.push({
						x: cx + radius * Math.cos(ang),
						y: cy + radius * Math.sin(ang),
					});
				}
			}
		}
	}

	return result;
}

/**
 * Calculates mass properties of a region (or collection of loops) using Green's Theorem.
 * Handles outer loops (CCW, positive area) and inner holes (CW, negative area).
 */
export function calculateRegionMassProperties(loops: readonly (readonly RegionPoint2D[])[]): RegionMassProperties {
	let totalArea = 0;
	let totalPerimeter = 0;
	let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
	let sumCxA = 0;
	let sumCyA = 0;
	let sumIxOrigin = 0;
	let sumIyOrigin = 0;
	let sumIxyOrigin = 0;

	for (const poly of loops) {
		const n = poly.length;
		if (n < 3) continue;

		totalPerimeter += polygonPerimeter(poly);

		for (let i = 0; i < n; i++) {
			const p1 = poly[i];
			const p2 = poly[(i + 1) % n];

			minX = Math.min(minX, p1.x);
			minY = Math.min(minY, p1.y);
			maxX = Math.max(maxX, p1.x);
			maxY = Math.max(maxY, p1.y);

			const a = p1.x * p2.y - p2.x * p1.y;
			totalArea += a / 2;

			sumCxA += (p1.x + p2.x) * a;
			sumCyA += (p1.y + p2.y) * a;

			sumIxOrigin += (p1.y * p1.y + p1.y * p2.y + p2.y * p2.y) * a;
			sumIyOrigin += (p1.x * p1.x + p1.x * p2.x + p2.x * p2.x) * a;
			sumIxyOrigin += (p1.x * p2.y + 2 * p1.x * p1.y + 2 * p2.x * p2.y + p2.x * p1.y) * a;
		}
	}

	const area = Math.abs(totalArea);
	if (area < 1e-12) {
		return {
			area: 0,
			perimeter: totalPerimeter,
			centroid: { x: 0, y: 0 },
			bbox: { min: { x: minX, y: minY }, max: { x: maxX, y: maxY } },
			Ixx: 0, Iyy: 0, Ixy: 0,
			IxOrigin: 0, IyOrigin: 0, IxyOrigin: 0,
			kx: 0, ky: 0,
			principalMoments: { I: 0, J: 0 },
			principalAngle: 0,
			principalDirectionI: { x: 1, y: 0 },
			principalDirectionJ: { x: 0, y: 1 },
		};
	}

	// Sign adjustment if clockwise
	const sign = totalArea < 0 ? -1 : 1;
	const cx = (sign * sumCxA) / (6 * area);
	const cy = (sign * sumCyA) / (6 * area);

	const IxOrigin = (sign * sumIxOrigin) / 12;
	const IyOrigin = (sign * sumIyOrigin) / 12;
	const IxyOrigin = (sign * sumIxyOrigin) / 24;

	// Parallel axis theorem: moments about centroid
	const Ixx = IxOrigin - area * cy * cy;
	const Iyy = IyOrigin - area * cx * cx;
	const Ixy = IxyOrigin - area * cx * cy;

	const kx = Math.sqrt(Math.max(0, Ixx / area));
	const ky = Math.sqrt(Math.max(0, Iyy / area));

	// Principal moments and angle
	const diff = (Ixx - Iyy) / 2;
	const R = Math.hypot(diff, Ixy);
	const avg = (Ixx + Iyy) / 2;
	const I = avg + R;
	const J = avg - R;
	const principalAngle = 0.5 * Math.atan2(-2 * Ixy, Ixx - Iyy);

	return {
		area,
		perimeter: totalPerimeter,
		centroid: { x: cx, y: cy },
		bbox: { min: { x: minX, y: minY }, max: { x: maxX, y: maxY } },
		Ixx, Iyy, Ixy,
		IxOrigin, IyOrigin, IxyOrigin,
		kx, ky,
		principalMoments: { I, J },
		principalAngle,
		principalDirectionI: { x: Math.cos(principalAngle), y: Math.sin(principalAngle) },
		principalDirectionJ: { x: -Math.sin(principalAngle), y: Math.cos(principalAngle) },
	};
}

/**
 * 2D Polygon Boolean Clipping (Greiner–Hormann / Martinez segment subdivision).
 * Splits edges at intersection points, classifies segments as inside/outside,
 * and chains resulting cycles into closed rings.
 */
function lineLineIntersection(
	p1: RegionPoint2D, p2: RegionPoint2D,
	p3: RegionPoint2D, p4: RegionPoint2D,
): { readonly x: number; readonly y: number; readonly t: number; readonly u: number } | null {
	const d1x = p2.x - p1.x;
	const d1y = p2.y - p1.y;
	const d2x = p4.x - p3.x;
	const d2y = p4.y - p3.y;

	const denom = d1x * d2y - d1y * d2x;
	if (Math.abs(denom) < 1e-12) return null;

	const numT = (p3.x - p1.x) * d2y - (p3.y - p1.y) * d2x;
	const numU = (p3.x - p1.x) * d1y - (p3.y - p1.y) * d1x;

	const t = numT / denom;
	const u = numU / denom;

	const eps = 1e-8;
	if (t > eps && t < 1 - eps && u > eps && u < 1 - eps) {
		return {
			x: p1.x + t * d1x,
			y: p1.y + t * d1y,
			t,
			u,
		};
	}
	return null;
}

interface DirectedSegment {
	readonly start: RegionPoint2D;
	readonly end: RegionPoint2D;
}

function splitEdgesAtIntersections(poly: readonly RegionPoint2D[], otherPoly: readonly RegionPoint2D[]): DirectedSegment[] {
	const segments: DirectedSegment[] = [];
	const n = poly.length;
	const m = otherPoly.length;

	for (let i = 0; i < n; i++) {
		const p1 = poly[i];
		const p2 = poly[(i + 1) % n];

		const hits: { x: number; y: number; t: number }[] = [];
		for (let j = 0; j < m; j++) {
			const q1 = otherPoly[j];
			const q2 = otherPoly[(j + 1) % m];
			const hit = lineLineIntersection(p1, p2, q1, q2);
			if (hit) hits.push(hit);
		}
		hits.sort((a, b) => a.t - b.t);

		let lastPt = p1;
		for (const h of hits) {
			const pt = { x: h.x, y: h.y };
			segments.push({ start: lastPt, end: pt });
			lastPt = pt;
		}
		segments.push({ start: lastPt, end: p2 });
	}

	return segments;
}

function chainSegmentsToRings(segments: readonly DirectedSegment[]): RegionPoint2D[][] {
	const eps = 1e-4;
	const dist = (a: RegionPoint2D, b: RegionPoint2D) => Math.hypot(a.x - b.x, a.y - b.y);
	const unused = [...segments];
	const rings: RegionPoint2D[][] = [];

	while (unused.length > 0) {
		const ring: RegionPoint2D[] = [];
		let current = unused.shift()!;
		ring.push(current.start);

		while (current) {
			const target = current.end;
			const nextIdx = unused.findIndex(s => dist(s.start, target) < eps);
			if (nextIdx === -1) {
				break;
			}
			ring.push(target);
			current = unused.splice(nextIdx, 1)[0];
			if (dist(current.end, ring[0]) < eps) {
				break;
			}
		}
		if (ring.length >= 3) {
			rings.push(ring);
		}
	}
	return rings;
}

/**
 * Executes a 2D boolean operation (Union, Intersection, or Difference) between two polygons.
 * Greiner–Hormann edge subdivision algorithm with boundary perturbation to resolve collinearities.
 */
export function polygonBoolean(
	polyA: readonly RegionPoint2D[],
	polyB: readonly RegionPoint2D[],
	op: 'union' | 'intersect' | 'difference',
): RegionPoint2D[][] {
	if (polyA.length < 3) return op === 'union' ? [polyB.map(p => ({ ...p }))] : [];
	if (polyB.length < 3) return op === 'union' || op === 'difference' ? [polyA.map(p => ({ ...p }))] : [];

	// Perturb polyB slightly to break collinear overlapping edges
	const perturb = (p: RegionPoint2D, i: number) => ({
		x: p.x + 1e-6 * Math.cos(i * 1.7),
		y: p.y + 1e-6 * Math.sin(i * 1.7),
	});
	const cleanB = polyB.map(perturb);

	const segsA = splitEdgesAtIntersections(polyA, cleanB);
	const segsB = splitEdgesAtIntersections(cleanB, polyA);

	const kept: DirectedSegment[] = [];
	for (const s of segsA) {
		const mid = { x: (s.start.x + s.end.x) / 2, y: (s.start.y + s.end.y) / 2 };
		const inB = isPointInPolygon(mid, cleanB);
		if (op === 'union' && !inB) kept.push(s);
		else if (op === 'intersect' && inB) kept.push(s);
		else if (op === 'difference' && !inB) kept.push(s);
	}

	for (const s of segsB) {
		const mid = { x: (s.start.x + s.end.x) / 2, y: (s.start.y + s.end.y) / 2 };
		const inA = isPointInPolygon(mid, polyA);
		if (op === 'union' && !inA) kept.push(s);
		else if (op === 'intersect' && inA) kept.push(s);
		else if (op === 'difference' && inA) {
			kept.push({ start: s.end, end: s.start });
		}
	}

	const rings = chainSegmentsToRings(kept);
	// Snap vertices to clean coordinates
	return rings.map(ring => ring.map(pt => ({
		x: Math.round(pt.x * 1000) / 1000,
		y: Math.round(pt.y * 1000) / 1000,
	})));
}

/** Extracts RegionPoint2D vertices from an entity (polyline, circle, line). */
export function entityToPolygon2D(entity: AcDbEntity): RegionPoint2D[] | null {
	if (entity instanceof AcDbPolyline) {
		const data = polylineVertices(entity);
		const pts = data.points.map(([x, y]) => ({ x, y }));
		return approximatePolylineArcs(pts, data.bulges);
	}
	const e = entity as any;
	if (e.center && e.radius) {
		// Circle/arc
		const numSteps = 64;
		const r = e.radius;
		const cx = e.center.x, cy = e.center.y;
		const pts: RegionPoint2D[] = [];
		for (let i = 0; i < numSteps; i++) {
			const ang = (i * 2 * Math.PI) / numSteps;
			pts.push({ x: cx + r * Math.cos(ang), y: cy + r * Math.sin(ang) });
		}
		return pts;
	}
	return null;
}

/** Creates an AcDbPolyline from a 2D ring of vertices. */
export function createRegionPolyline(ring: readonly RegionPoint2D[]): AcDbPolyline {
	const poly = new AcDbPolyline();
	ring.forEach((pt, i) => {
		poly.addVertexAt(i, new AcGePoint2d(pt.x, pt.y));
	});
	poly.closed = true;
	tagEntityAsRegion(poly);
	return poly;
}
