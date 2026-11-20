/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/** A 3D point or vector (project space mm with Z up, unless noted otherwise). */
export type Vec3 = readonly [number, number, number];

/** Geometry snap target kinds, in priority order. */
export type SnapKind = 'vertex' | 'midpoint' | 'edge' | 'face';

/** All measurement modes supported across the 3D viewers. */
export type ViewerMeasureMode = 'off' | 'distance' | 'chain' | 'pointToFace' | 'edgeAngle' | 'angle' | 'area';

/** A candidate snap point evaluated in screen space. */
export interface SnapCandidate {
	readonly point: Vec3;
	readonly kind: SnapKind;
	readonly screenDistancePx: number;
	readonly depth: number;
	readonly normal?: Vec3;
	readonly edge?: readonly [Vec3, Vec3];
}

/** The winning snap result under the cursor. */
export interface SnapResult {
	readonly point: Vec3;
	readonly kind: SnapKind;
	readonly normal?: Vec3;
	readonly edge?: readonly [Vec3, Vec3];
}

/** A recorded measurement shown in the 3D overlay and copyable panel. */
export interface MeasureEntry {
	readonly id: string;
	readonly mode: Exclude<ViewerMeasureMode, 'off'>;
	readonly points: readonly Vec3[];
	readonly complete: boolean;
	readonly label: string;
	readonly summary: string;
	readonly distanceMm?: number;
	readonly dxMm?: number;
	readonly dyMm?: number;
	readonly dzMm?: number;
	readonly segmentsMm?: readonly number[];
	readonly totalMm?: number;
	readonly footPoint?: Vec3;
	readonly faceNormal?: Vec3;
	readonly angleDeg?: number;
	readonly edgeA?: readonly [Vec3, Vec3];
	readonly edgeB?: readonly [Vec3, Vec3];
	readonly area?: number;
	readonly perimeter?: number;
}

export const SNAP_PRIORITY: Readonly<Record<SnapKind, number>> = {
	vertex: 0,
	midpoint: 1,
	edge: 2,
	face: 3,
};

const DEFAULT_THRESHOLDS = {
	vertexPx: 14,
	midpointPx: 14,
	edgePx: 10,
};

export function midpoint(a: Vec3, b: Vec3): Vec3 {
	return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}

export function distance3(a: Vec3, b: Vec3): number {
	return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}

export function normalize3(v: Vec3): Vec3 {
	const len = Math.hypot(v[0], v[1], v[2]);
	return len > 1e-12 ? [v[0] / len, v[1] / len, v[2] / len] : [0, 0, 1];
}

export function closestPointOnSegment(p: Vec3, a: Vec3, b: Vec3): Vec3 {
	const dx = b[0] - a[0];
	const dy = b[1] - a[1];
	const dz = b[2] - a[2];
	const lenSq = dx * dx + dy * dy + dz * dz;
	if (lenSq <= 1e-12) {
		return a;
	}
	const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy + (p[2] - a[2]) * dz) / lenSq));
	return [a[0] + t * dx, a[1] + t * dy, a[2] + t * dz];
}

/**
 * Selects the best snap candidate under the cursor: vertices win over edge midpoints,
 * midpoints over edges, and edges over arbitrary face points within their screen radii.
 */
export function chooseSnap(
	candidates: readonly SnapCandidate[],
	thresholds: { readonly vertexPx?: number; readonly midpointPx?: number; readonly edgePx?: number } = {},
): SnapResult | undefined {
	const vertexPx = thresholds.vertexPx ?? DEFAULT_THRESHOLDS.vertexPx;
	const midpointPx = thresholds.midpointPx ?? DEFAULT_THRESHOLDS.midpointPx;
	const edgePx = thresholds.edgePx ?? DEFAULT_THRESHOLDS.edgePx;

	const withinThreshold = (c: SnapCandidate): boolean => {
		switch (c.kind) {
			case 'vertex': return c.screenDistancePx <= vertexPx;
			case 'midpoint': return c.screenDistancePx <= midpointPx;
			case 'edge': return c.screenDistancePx <= edgePx;
			case 'face': return true;
		}
	};

	let best: SnapCandidate | undefined;
	for (const candidate of candidates) {
		if (!withinThreshold(candidate)) {
			continue;
		}
		if (!best) {
			best = candidate;
			continue;
		}
		const pBest = SNAP_PRIORITY[best.kind];
		const pCand = SNAP_PRIORITY[candidate.kind];
		if (pCand < pBest) {
			best = candidate;
		} else if (pCand === pBest) {
			if (candidate.screenDistancePx < best.screenDistancePx - 0.5) {
				best = candidate;
			} else if (Math.abs(candidate.screenDistancePx - best.screenDistancePx) <= 0.5 && candidate.depth < best.depth) {
				best = candidate;
			}
		}
	}
	return best ? { point: best.point, kind: best.kind, normal: best.normal, edge: best.edge } : undefined;
}

/**
 * Extracts vertex, edge-midpoint, edge, and face snap candidates around a face intersection.
 */
export function extractFaceSnapCandidates(
	hitPoint: Vec3,
	vertices: readonly Vec3[],
	edges: readonly (readonly [Vec3, Vec3])[],
	project: (p: Vec3) => { readonly x: number; readonly y: number; readonly depth: number; readonly visible: boolean },
	cursorX: number,
	cursorY: number,
	normal?: Vec3,
): SnapCandidate[] {
	const candidates: SnapCandidate[] = [];
	const pushPoint = (point: Vec3, kind: SnapKind, edge?: readonly [Vec3, Vec3]) => {
		const projected = project(point);
		if (!projected.visible) {
			return;
		}
		candidates.push({
			point,
			kind,
			screenDistancePx: Math.hypot(projected.x - cursorX, projected.y - cursorY),
			depth: projected.depth,
			normal,
			edge,
		});
	};
	for (const vertex of vertices) {
		pushPoint(vertex, 'vertex');
	}
	for (const edge of edges) {
		pushPoint(midpoint(edge[0], edge[1]), 'midpoint', edge);
		pushPoint(closestPointOnSegment(hitPoint, edge[0], edge[1]), 'edge', edge);
	}
	pushPoint(hitPoint, 'face');
	return candidates;
}

/** Perpendicular distance from `point` to the plane `(planePoint, planeNormal)` and the foot point on the plane. */
export function distancePointToPlane(
	point: Vec3,
	planePoint: Vec3,
	planeNormal: Vec3,
): { readonly distance: number; readonly signedDistance: number; readonly foot: Vec3 } {
	const n = normalize3(planeNormal);
	const dx = point[0] - planePoint[0];
	const dy = point[1] - planePoint[1];
	const dz = point[2] - planePoint[2];
	const signedDistance = dx * n[0] + dy * n[1] + dz * n[2];
	const foot: Vec3 = [
		point[0] - signedDistance * n[0],
		point[1] - signedDistance * n[1],
		point[2] - signedDistance * n[2],
	];
	return { distance: Math.abs(signedDistance), signedDistance, foot };
}

/**
 * Angle (in degrees) between two edges.
 * If the two edges share an endpoint within `vertexTol`, returns the interior angle [0°, 180°]
 * between the rays radiating from that shared vertex. Otherwise returns the acute angle [0°, 90°]
 * between the two line directions.
 */
export function angleBetweenEdges(
	edgeA: readonly [Vec3, Vec3],
	edgeB: readonly [Vec3, Vec3],
	vertexTol = 1,
): { readonly angleDeg: number; readonly vertex: Vec3; readonly sharedVertex: boolean; readonly dirA: Vec3; readonly dirB: Vec3 } {
	const pairs: readonly [Vec3, Vec3, Vec3, Vec3][] = [
		[edgeA[0], edgeA[1], edgeB[0], edgeB[1]],
		[edgeA[0], edgeA[1], edgeB[1], edgeB[0]],
		[edgeA[1], edgeA[0], edgeB[0], edgeB[1]],
		[edgeA[1], edgeA[0], edgeB[1], edgeB[0]],
	];
	for (const [aCommon, aOther, bCommon, bOther] of pairs) {
		if (distance3(aCommon, bCommon) <= vertexTol) {
			const dirA = normalize3([aOther[0] - aCommon[0], aOther[1] - aCommon[1], aOther[2] - aCommon[2]]);
			const dirB = normalize3([bOther[0] - bCommon[0], bOther[1] - bCommon[1], bOther[2] - bCommon[2]]);
			const dot = Math.max(-1, Math.min(1, dirA[0] * dirB[0] + dirA[1] * dirB[1] + dirA[2] * dirB[2]));
			return {
				angleDeg: Math.acos(dot) * 180 / Math.PI,
				vertex: midpoint(aCommon, bCommon),
				sharedVertex: true,
				dirA,
				dirB,
			};
		}
	}
	const dirA = normalize3([edgeA[1][0] - edgeA[0][0], edgeA[1][1] - edgeA[0][1], edgeA[1][2] - edgeA[0][2]]);
	let dirB = normalize3([edgeB[1][0] - edgeB[0][0], edgeB[1][1] - edgeB[0][1], edgeB[1][2] - edgeB[0][2]]);
	let dot = dirA[0] * dirB[0] + dirA[1] * dirB[1] + dirA[2] * dirB[2];
	if (dot < 0) {
		dot = -dot;
		dirB = [-dirB[0], -dirB[1], -dirB[2]];
	}
	const clamped = Math.max(0, Math.min(1, dot));
	return {
		angleDeg: Math.acos(clamped) * 180 / Math.PI,
		vertex: midpoint(midpoint(edgeA[0], edgeA[1]), midpoint(edgeB[0], edgeB[1])),
		sharedVertex: false,
		dirA,
		dirB,
	};
}

/** Segment lengths and cumulative total of a chain of points. */
export function chainMetrics(points: readonly Vec3[]): { readonly segments: number[]; readonly total: number } {
	const segments: number[] = [];
	let total = 0;
	for (let i = 1; i < points.length; i++) {
		const len = distance3(points[i - 1], points[i]);
		segments.push(len);
		total += len;
	}
	return { segments, total };
}

/** Formats a millimetre length concisely (whole mm when near integer, else 1 decimal). */
export function formatMm(mm: number): string {
	const abs = Math.abs(mm);
	const rounded = Math.round(mm);
	if (Math.abs(mm - rounded) < 0.05 || abs >= 100) {
		return `${rounded} mm`;
	}
	return `${mm.toFixed(1)} mm`;
}

export function buildDistanceEntry(id: string, a: Vec3, b: Vec3, scaleToMm = 1): MeasureEntry {
	const dxMm = (b[0] - a[0]) * scaleToMm;
	const dyMm = (b[1] - a[1]) * scaleToMm;
	const dzMm = (b[2] - a[2]) * scaleToMm;
	const distanceMm = Math.hypot(dxMm, dyMm, dzMm);
	const label = formatMm(distanceMm);
	const summary = `${label} (dX ${formatMm(dxMm)}, dY ${formatMm(dyMm)}, dZ ${formatMm(dzMm)})`;
	return { id, mode: 'distance', points: [a, b], complete: true, label, summary, distanceMm, dxMm, dyMm, dzMm };
}

export function buildChainEntry(id: string, points: readonly Vec3[], complete: boolean, scaleToMm = 1): MeasureEntry {
	const { segments, total } = chainMetrics(points);
	const segmentsMm = segments.map(s => s * scaleToMm);
	const totalMm = total * scaleToMm;
	const label = `Σ ${formatMm(totalMm)}`;
	const parts = segmentsMm.map(formatMm).join(' + ');
	const summary = segmentsMm.length > 1 ? `${formatMm(totalMm)} (${parts})` : formatMm(totalMm);
	return { id, mode: 'chain', points, complete, label, summary, segmentsMm, totalMm };
}

export function buildPointToFaceEntry(id: string, point: Vec3, facePoint: Vec3, faceNormal: Vec3, scaleToMm = 1): MeasureEntry {
	const perp = distancePointToPlane(point, facePoint, faceNormal);
	const distanceMm = perp.distance * scaleToMm;
	const label = `⊥ ${formatMm(distanceMm)}`;
	const dxMm = (perp.foot[0] - point[0]) * scaleToMm;
	const dyMm = (perp.foot[1] - point[1]) * scaleToMm;
	const dzMm = (perp.foot[2] - point[2]) * scaleToMm;
	const summary = `⊥ ${formatMm(distanceMm)} (dX ${formatMm(dxMm)}, dY ${formatMm(dyMm)}, dZ ${formatMm(dzMm)})`;
	return {
		id,
		mode: 'pointToFace',
		points: [point, facePoint],
		complete: true,
		label,
		summary,
		distanceMm,
		dxMm,
		dyMm,
		dzMm,
		footPoint: perp.foot,
		faceNormal: normalize3(faceNormal),
	};
}

export function buildEdgeAngleEntry(id: string, edgeA: readonly [Vec3, Vec3], edgeB: readonly [Vec3, Vec3]): MeasureEntry {
	const res = angleBetweenEdges(edgeA, edgeB);
	const label = `${res.angleDeg.toFixed(1)}°`;
	const summary = `${res.angleDeg.toFixed(2)}°`;
	return {
		id,
		mode: 'edgeAngle',
		points: [res.vertex],
		complete: true,
		label,
		summary,
		angleDeg: res.angleDeg,
		edgeA,
		edgeB,
	};
}
