/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc, AcDbCircle, AcDbEllipse, AcDbEntity, AcDbLine, AcDbPolyline,
} from '@mlightcad/data-model';
import { polylineVertices } from './entityAccess.js';
import { arcFromBulge, polylineMetrics, type P2, type Segment } from './inquiryGeometry.js';

export interface HatchSegment {
	start: P2;
	end: P2;
	bulge?: number;
}

export interface HatchVertex {
	x: number;
	y: number;
	bulge?: number;
}

export interface HatchLoop {
	vertices: HatchVertex[];
	closed: boolean;
	area: number;
}

const EPS = 1e-5;
const dist = (a: P2, b: P2) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const normalizeAngle = (a: number) => {
	let res = a % (2 * Math.PI);
	if (res <= -Math.PI) res += 2 * Math.PI;
	if (res > Math.PI) res -= 2 * Math.PI;
	return res;
};

/**
 * Extract 2D boundary segments from CAD entities.
 */
export function extractSegmentsFromEntity(e: AcDbEntity): HatchSegment[] {
	if (e instanceof AcDbLine || e.dxfTypeName === 'LINE') {
		const line = e as AcDbLine;
		return [{
			start: [line.startPoint.x, line.startPoint.y],
			end: [line.endPoint.x, line.endPoint.y],
			bulge: 0,
		}];
	}
	if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') {
		const circle = e as AcDbCircle;
		const c = circle.center, r = circle.radius;
		return [
			{ start: [c.x - r, c.y], end: [c.x + r, c.y], bulge: 1 },
			{ start: [c.x + r, c.y], end: [c.x - r, c.y], bulge: 1 },
		];
	}
	if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') {
		const arc = e as AcDbArc;
		const c = arc.center, r = arc.radius;
		const sweep = ((arc.endAngle - arc.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || 2 * Math.PI;
		if (sweep > Math.PI) {
			const mid = arc.startAngle + sweep / 2;
			const b = Math.tan(sweep / 8);
			return [
				{
					start: [c.x + r * Math.cos(arc.startAngle), c.y + r * Math.sin(arc.startAngle)],
					end: [c.x + r * Math.cos(mid), c.y + r * Math.sin(mid)],
					bulge: b,
				},
				{
					start: [c.x + r * Math.cos(mid), c.y + r * Math.sin(mid)],
					end: [c.x + r * Math.cos(arc.endAngle), c.y + r * Math.sin(arc.endAngle)],
					bulge: b,
				},
			];
		}
		return [{
			start: [c.x + r * Math.cos(arc.startAngle), c.y + r * Math.sin(arc.startAngle)],
			end: [c.x + r * Math.cos(arc.endAngle), c.y + r * Math.sin(arc.endAngle)],
			bulge: Math.tan(sweep / 4),
		}];
	}
	if (e instanceof AcDbPolyline || e.dxfTypeName === 'LWPOLYLINE') {
		const { points, bulges, closed } = polylineVertices(e as AcDbPolyline);
		const n = points.length;
		const count = closed ? n : Math.max(0, n - 1);
		const segs: HatchSegment[] = [];
		for (let i = 0; i < count; i++) {
			segs.push({
				start: points[i],
				end: points[(i + 1) % n],
				bulge: bulges[i] || 0,
			});
		}
		return segs;
	}
	return [];
}

/**
 * Find intersection points between two segments.
 */
function getIntersections(s1: HatchSegment, s2: HatchSegment): P2[] {
	const b1 = s1.bulge || 0;
	const b2 = s2.bulge || 0;

	if (Math.abs(b1) < 1e-6 && Math.abs(b2) < 1e-6) {
		// Line - Line
		const p = s1.start, r: P2 = [s1.end[0] - p[0], s1.end[1] - p[1]];
		const q = s2.start, s: P2 = [s2.end[0] - q[0], s2.end[1] - q[1]];
		const denom = r[0] * s[1] - r[1] * s[0];
		if (Math.abs(denom) < 1e-9) return [];
		const qp: P2 = [q[0] - p[0], q[1] - p[1]];
		const t = (qp[0] * s[1] - qp[1] * s[0]) / denom;
		const u = (qp[0] * r[1] - qp[1] * r[0]) / denom;
		if (t >= -EPS && t <= 1 + EPS && u >= -EPS && u <= 1 + EPS) {
			return [[p[0] + t * r[0], p[1] + t * r[1]]];
		}
		return [];
	}

	// Line - Arc or Arc - Arc
	const arc1 = b1 !== 0 ? arcFromBulge(s1.start, s1.end, b1) : undefined;
	const arc2 = b2 !== 0 ? arcFromBulge(s2.start, s2.end, b2) : undefined;

	if (arc1 && !arc2) {
		return lineArcIntersections(s2, arc1);
	}
	if (!arc1 && arc2) {
		return lineArcIntersections(s1, arc2);
	}
	if (arc1 && arc2) {
		return arcArcIntersections(arc1, arc2);
	}
	return [];
}

function lineArcIntersections(line: HatchSegment, arc: { center: P2; radius: number; start: number; sweep: number }): P2[] {
	const dx = line.end[0] - line.start[0], dy = line.end[1] - line.start[1];
	const fx = line.start[0] - arc.center[0], fy = line.start[1] - arc.center[1];
	const a = dx * dx + dy * dy;
	const b = 2 * (fx * dx + fy * dy);
	const c = fx * fx + fy * fy - arc.radius * arc.radius;
	if (a < 1e-12) return [];
	const disc = b * b - 4 * a * c;
	if (disc < 0) return [];
	const sqrtD = Math.sqrt(Math.max(0, disc));
	const ts = [(-b - sqrtD) / (2 * a), (-b + sqrtD) / (2 * a)];
	const hits: P2[] = [];
	for (const t of ts) {
		if (t >= -EPS && t <= 1 + EPS) {
			const pt: P2 = [line.start[0] + t * dx, line.start[1] + t * dy];
			const ang = Math.atan2(pt[1] - arc.center[1], pt[0] - arc.center[0]);
			const diff = arc.sweep >= 0
				? ((ang - arc.start) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI)
				: ((arc.start - ang) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
			if (diff <= Math.abs(arc.sweep) + EPS) {
				hits.push(pt);
			}
		}
	}
	return hits;
}

function arcArcIntersections(
	a1: { center: P2; radius: number; start: number; sweep: number },
	a2: { center: P2; radius: number; start: number; sweep: number },
): P2[] {
	const d = dist(a1.center, a2.center);
	if (d > a1.radius + a2.radius + EPS || d < Math.abs(a1.radius - a2.radius) - EPS || d < 1e-9) return [];
	const a = (a1.radius * a1.radius - a2.radius * a2.radius + d * d) / (2 * d);
	const h = Math.sqrt(Math.max(0, a1.radius * a1.radius - a * a));
	const p2x = a1.center[0] + (a * (a2.center[0] - a1.center[0])) / d;
	const p2y = a1.center[1] + (a * (a2.center[1] - a1.center[1])) / d;
	const rx = -(a2.center[1] - a1.center[1]) * (h / d);
	const ry = (a2.center[0] - a1.center[0]) * (h / d);
	const candidates: P2[] = [[p2x + rx, p2y + ry], [p2x - rx, p2y - ry]];
	const hits: P2[] = [];
	for (const pt of candidates) {
		const ang1 = Math.atan2(pt[1] - a1.center[1], pt[0] - a1.center[0]);
		const ang2 = Math.atan2(pt[1] - a2.center[1], pt[0] - a2.center[0]);
		const diff1 = a1.sweep >= 0
			? ((ang1 - a1.start) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI)
			: ((a1.start - ang1) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
		const diff2 = a2.sweep >= 0
			? ((ang2 - a2.start) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI)
			: ((a2.start - ang2) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
		if (diff1 <= Math.abs(a1.sweep) + EPS && diff2 <= Math.abs(a2.sweep) + EPS) {
			hits.push(pt);
		}
	}
	return hits;
}

/**
 * Split segments at all intersection points to form planar graph edges.
 */
function splitSegments(segments: readonly HatchSegment[]): HatchSegment[] {
	const n = segments.length;
	const splitPoints: P2[][] = Array.from({ length: n }, () => []);

	for (let i = 0; i < n; i++) {
		for (let j = i + 1; j < n; j++) {
			const hits = getIntersections(segments[i], segments[j]);
			for (const h of hits) {
				splitPoints[i].push(h);
				splitPoints[j].push(h);
			}
		}
	}

	const result: HatchSegment[] = [];
	for (let i = 0; i < n; i++) {
		const s = segments[i];
		const pts = splitPoints[i];
		const bulge = s.bulge || 0;

		if (Math.abs(bulge) < 1e-6) {
			// Line segment: parameter t in [0, 1]
			const dx = s.end[0] - s.start[0], dy = s.end[1] - s.start[1];
			const lenSq = dx * dx + dy * dy;
			if (lenSq < 1e-12) continue;
			const validTs: number[] = [];
			for (const pt of pts) {
				const t = ((pt[0] - s.start[0]) * dx + (pt[1] - s.start[1]) * dy) / lenSq;
				if (t > 1e-4 && t < 1 - 1e-4) validTs.push(t);
			}
			validTs.sort((a, b) => a - b);
			const uniqueTs: number[] = [];
			for (const t of validTs) {
				if (!uniqueTs.length || t - uniqueTs[uniqueTs.length - 1] > 1e-4) {
					uniqueTs.push(t);
				}
			}
			let cur = s.start;
			for (const t of uniqueTs) {
				const next: P2 = [s.start[0] + t * dx, s.start[1] + t * dy];
				if (dist(cur, next) > 1e-4) {
					result.push({ start: cur, end: next, bulge: 0 });
					cur = next;
				}
			}
			if (dist(cur, s.end) > 1e-4) {
				result.push({ start: cur, end: s.end, bulge: 0 });
			}
		} else {
			// Arc segment
			const arc = arcFromBulge(s.start, s.end, bulge);
			if (!arc) {
				result.push(s);
				continue;
			}
			const validTs: number[] = [];
			for (const pt of pts) {
				const ang = Math.atan2(pt[1] - arc.center[1], pt[0] - arc.center[0]);
				const diff = arc.sweep >= 0
					? ((ang - arc.start) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI)
					: ((arc.start - ang) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
				const t = diff / Math.abs(arc.sweep);
				if (t > 1e-4 && t < 1 - 1e-4) validTs.push(t);
			}
			validTs.sort((a, b) => a - b);
			const uniqueTs: number[] = [];
			for (const t of validTs) {
				if (!uniqueTs.length || t - uniqueTs[uniqueTs.length - 1] > 1e-4) {
					uniqueTs.push(t);
				}
			}
			const allTs = [0, ...uniqueTs, 1];
			for (let k = 0; k < allTs.length - 1; k++) {
				const t0 = allTs[k], t1 = allTs[k + 1];
				const dt = t1 - t0;
				if (dt < 1e-4) continue;
				const a0 = arc.start + (arc.sweep >= 0 ? t0 * arc.sweep : -t0 * Math.abs(arc.sweep));
				const a1 = arc.start + (arc.sweep >= 0 ? t1 * arc.sweep : -t1 * Math.abs(arc.sweep));
				const p0: P2 = [arc.center[0] + arc.radius * Math.cos(a0), arc.center[1] + arc.radius * Math.sin(a0)];
				const p1: P2 = [arc.center[0] + arc.radius * Math.cos(a1), arc.center[1] + arc.radius * Math.sin(a1)];
				const subSweep = dt * arc.sweep;
				const subBulge = Math.sign(arc.sweep) * Math.tan(Math.abs(subSweep) / 4);
				if (dist(p0, p1) > 1e-4) {
					result.push({ start: p0, end: p1, bulge: subBulge });
				}
			}
		}
	}
	return result;
}

interface DirectedEdge {
	id: number;
	from: number;
	to: number;
	bulge: number;
	angle: number; // departure angle at 'from' vertex
	revId: number;
}

/**
 * Build planar graph and find the minimal enclosing cycle enclosing pickPoint.
 */
export function findMinimalEnclosingLoop(
	segments: readonly HatchSegment[],
	pickPoint: P2,
	tolerance = 1e-4,
): HatchLoop | undefined {
	const split = splitSegments(segments);
	if (!split.length) return undefined;

	// Cluster vertices
	const vertices: P2[] = [];
	function getVertexIndex(pt: P2): number {
		for (let i = 0; i < vertices.length; i++) {
			if (dist(vertices[i], pt) <= tolerance) return i;
		}
		vertices.push(pt);
		return vertices.length - 1;
	}

	const halfEdges: DirectedEdge[] = [];
	const outgoing: DirectedEdge[][] = [];

	function addHalfEdge(from: number, to: number, bulge: number, angle: number): number {
		const id = halfEdges.length;
		const edge: DirectedEdge = { id, from, to, bulge, angle, revId: -1 };
		halfEdges.push(edge);
		if (!outgoing[from]) outgoing[from] = [];
		outgoing[from].push(edge);
		return id;
	}

	for (const seg of split) {
		const u = getVertexIndex(seg.start);
		const v = getVertexIndex(seg.end);
		if (u === v && Math.abs(seg.bulge || 0) < 1e-6) continue;

		const b = seg.bulge || 0;
		const chord1 = Math.atan2(vertices[v][1] - vertices[u][1], vertices[v][0] - vertices[u][0]);
		const angle1 = normalizeAngle(chord1 + 2 * Math.atan(b));

		const chord2 = Math.atan2(vertices[u][1] - vertices[v][1], vertices[u][0] - vertices[v][0]);
		const angle2 = normalizeAngle(chord2 - 2 * Math.atan(b));

		const e1 = addHalfEdge(u, v, b, angle1);
		const e2 = addHalfEdge(v, u, -b, angle2);
		halfEdges[e1].revId = e2;
		halfEdges[e2].revId = e1;
	}

	// Sort outgoing half-edges counter-clockwise by departure angle
	for (let i = 0; i < vertices.length; i++) {
		if (outgoing[i]) {
			outgoing[i].sort((a, b) => a.angle - b.angle);
		}
	}

	// Helper to find the next edge around the face to the left of edge `e`
	function getNextEdge(e: DirectedEdge): DirectedEdge {
		const v = e.to;
		const rev = halfEdges[e.revId];
		const edges = outgoing[v];
		if (!edges || !edges.length) return rev;
		if (edges.length === 1) return edges[0];

		// We want the edge immediately CLOCKWISE from rev.angle
		let best: DirectedEdge | undefined;
		let minCwDist = Infinity;
		for (const cand of edges) {
			let cwDist = (rev.angle - cand.angle) % (2 * Math.PI);
			if (cwDist < 0) cwDist += 2 * Math.PI;
			if (cwDist > 1e-7 && cwDist < minCwDist) {
				minCwDist = cwDist;
				best = cand;
			}
		}
		return best ?? rev;
	}

	// Walk faces
	const visited = new Set<number>();
	const candidateLoops: HatchLoop[] = [];

	for (const startEdge of halfEdges) {
		if (visited.has(startEdge.id)) continue;

		const path: DirectedEdge[] = [];
		let cur: DirectedEdge | undefined = startEdge;
		const edgeIndexInPath = new Map<number, number>();

		while (cur && !visited.has(cur.id)) {
			if (edgeIndexInPath.has(cur.id)) {
				// Loop closed!
				const loopStartIdx = edgeIndexInPath.get(cur.id)!;
				const cycleEdges = path.slice(loopStartIdx);

				// Mark all cycle edges as visited
				for (const edge of cycleEdges) visited.add(edge.id);

				// Construct vertices of the cycle
				const loopVerts: HatchVertex[] = cycleEdges.map(edge => ({
					x: vertices[edge.from][0],
					y: vertices[edge.from][1],
					bulge: edge.bulge,
				}));

				// Calculate signed area
				const pts: P2[] = loopVerts.map(v => [v.x, v.y]);
				const bulges: number[] = loopVerts.map(v => v.bulge || 0);
				const metrics = polylineMetrics(pts, bulges, true);

				// Compute polygon orientation / signed area to check if CCW bounded
				let signedArea2 = 0;
				const numV = pts.length;
				for (let i = 0; i < numV; i++) {
					const a = pts[i], b = pts[(i + 1) % numV];
					signedArea2 += a[0] * b[1] - b[0] * a[1];
					const arc = arcFromBulge(a, b, bulges[i] || 0);
					if (arc) {
						signedArea2 += arc.radius * arc.radius * (arc.sweep - Math.sin(arc.sweep));
					}
				}

				if (signedArea2 > 1e-4) {
					// Bounded interior face: check if pickPoint is inside
					if (isPointInside(pickPoint, loopVerts)) {
						candidateLoops.push({
							vertices: loopVerts,
							closed: true,
							area: metrics.area,
						});
					}
				}
				break;
			}

			edgeIndexInPath.set(cur.id, path.length);
			path.push(cur);
			cur = getNextEdge(cur);
			if (path.length > halfEdges.length) break; // guard against cycle walk runaway
		}
		for (const edge of path) visited.add(edge.id);
	}

	if (!candidateLoops.length) return undefined;

	// Pick minimal area enclosing loop
	candidateLoops.sort((a, b) => a.area - b.area);
	return candidateLoops[0];
}

/**
 * Point-in-polygon test with bulge arc tessellation.
 */
export function isPointInside(pt: P2, vertices: readonly HatchVertex[]): boolean {
	const poly: P2[] = [];
	const n = vertices.length;
	for (let i = 0; i < n; i++) {
		const v = vertices[i];
		const next = vertices[(i + 1) % n];
		poly.push([v.x, v.y]);
		if (v.bulge && Math.abs(v.bulge) > 1e-5) {
			const arc = arcFromBulge([v.x, v.y], [next.x, next.y], v.bulge);
			if (arc) {
				const steps = Math.max(4, Math.ceil(Math.abs(arc.sweep) / (Math.PI / 8)));
				for (let s = 1; s < steps; s++) {
					const ang = arc.start + (arc.sweep >= 0 ? (s / steps) * arc.sweep : -(s / steps) * Math.abs(arc.sweep));
					poly.push([arc.center[0] + arc.radius * Math.cos(ang), arc.center[1] + arc.radius * Math.sin(ang)]);
				}
			}
		}
	}

	let inside = false;
	for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
		const xi = poly[i][0], yi = poly[i][1];
		const xj = poly[j][0], yj = poly[j][1];
		const intersect = ((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi);
		if (intersect) inside = !inside;
	}
	return inside;
}

/**
 * Detect boundary from pick internal point across database entities.
 */
export function detectBoundaryFromPoint(entities: readonly AcDbEntity[], pickPoint: P2): HatchLoop | undefined {
	const allSegments: HatchSegment[] = [];
	for (const e of entities) {
		allSegments.push(...extractSegmentsFromEntity(e));
	}
	return findMinimalEnclosingLoop(allSegments, pickPoint);
}

/**
 * Detect loops from selected objects (closed polylines, circles, ellipses).
 * Island detection "Normal": outer loop largest, inner loops nested.
 */
export function detectLoopsFromObjects(entities: readonly AcDbEntity[]): { outer: HatchLoop; islands: HatchLoop[] } | undefined {
	const loops: HatchLoop[] = [];

	for (const e of entities) {
		if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') {
			const circle = e as AcDbCircle;
			const c = circle.center, r = circle.radius;
			const verts: HatchVertex[] = [
				{ x: c.x - r, y: c.y, bulge: 1 },
				{ x: c.x + r, y: c.y, bulge: 1 },
			];
			const area = Math.PI * r * r;
			loops.push({ vertices: verts, closed: true, area });
		} else if (e instanceof AcDbPolyline || e.dxfTypeName === 'LWPOLYLINE') {
			const { points, bulges, closed } = polylineVertices(e as AcDbPolyline);
			if (closed && points.length >= 3) {
				const metrics = polylineMetrics(points, bulges, true);
				const verts: HatchVertex[] = points.map((p, i) => ({
					x: p[0],
					y: p[1],
					bulge: bulges[i] || 0,
				}));
				loops.push({ vertices: verts, closed: true, area: metrics.area });
			}
		} else if (e instanceof AcDbEllipse || e.dxfTypeName === 'ELLIPSE') {
			const el = e as AcDbEllipse;
			const c = el.center;
			const a = el.majorAxisRadius;
			const b = el.minorAxisRadius;
			const area = Math.PI * a * b;
			// Sample ellipse into a 16-point closed loop
			const n = 16;
			const rot = Math.atan2(el.majorAxis.y, el.majorAxis.x);
			const verts: HatchVertex[] = [];
			for (let i = 0; i < n; i++) {
				const theta = (i * 2 * Math.PI) / n;
				const px = a * Math.cos(theta);
				const py = b * Math.sin(theta);
				const rx = c.x + px * Math.cos(rot) - py * Math.sin(rot);
				const ry = c.y + px * Math.sin(rot) + py * Math.cos(rot);
				verts.push({ x: rx, y: ry, bulge: 0 });
			}
			loops.push({ vertices: verts, closed: true, area });
		}
	}

	if (!loops.length) return undefined;

	// Sort by area descending: largest is outer loop
	loops.sort((a, b) => b.area - a.area);
	const outer = loops[0];
	const islands = loops.slice(1);

	return { outer, islands };
}
