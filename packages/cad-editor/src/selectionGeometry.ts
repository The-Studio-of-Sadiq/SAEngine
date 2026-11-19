/** Pure 2D selection geometry used by AutoCAD-style window/crossing/fence modes. */
import { acdbHostApplicationServices } from '@mlightcad/data-model';
import { polylineVertices } from './entityAccess.js';
export * from './selectionModes.js';

export type SelectionPoint = readonly [number, number];
export type SelectionSegment = readonly [SelectionPoint, SelectionPoint];
export type SelectionModeKind = 'window' | 'crossing' | 'fence';

const EPS = 1e-9;

export function orient(a: SelectionPoint, b: SelectionPoint, c: SelectionPoint): number {
	return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

export function onSegment(p: SelectionPoint, s: SelectionSegment): boolean {
	return Math.abs(orient(s[0], s[1], p)) <= EPS &&
		p[0] >= Math.min(s[0][0], s[1][0]) - EPS &&
		p[0] <= Math.max(s[0][0], s[1][0]) + EPS &&
		p[1] >= Math.min(s[0][1], s[1][1]) - EPS &&
		p[1] <= Math.max(s[0][1], s[1][1]) + EPS;
}

export function segmentsIntersect(a: SelectionSegment, b: SelectionSegment): boolean {
	const o1 = orient(a[0], a[1], b[0]), o2 = orient(a[0], a[1], b[1]);
	const o3 = orient(b[0], b[1], a[0]), o4 = orient(b[0], b[1], a[1]);
	if (((o1 > EPS && o2 < -EPS) || (o1 < -EPS && o2 > EPS)) &&
		((o3 > EPS && o4 < -EPS) || (o3 < -EPS && o4 > EPS))) {
		return true;
	}
	return (Math.abs(o1) <= EPS && onSegment(b[0], a)) ||
		(Math.abs(o2) <= EPS && onSegment(b[1], a)) ||
		(Math.abs(o3) <= EPS && onSegment(a[0], b)) ||
		(Math.abs(o4) <= EPS && onSegment(a[1], b));
}

export function pointInPolygon(point: SelectionPoint, polygon: readonly SelectionPoint[]): boolean {
	let inside = false;
	for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
		const a = polygon[j], b = polygon[i];
		if (onSegment(point, [a, b])) return true;
		if ((a[1] > point[1]) !== (b[1] > point[1]) &&
			point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]) {
			inside = !inside;
		}
	}
	return inside;
}

export function distSqToSegment(p: SelectionPoint, s: SelectionSegment): number {
	const dx = s[1][0] - s[0][0], dy = s[1][1] - s[0][1];
	const lenSq = dx * dx + dy * dy;
	if (lenSq < 1e-12) {
		const px = p[0] - s[0][0], py = p[1] - s[0][1];
		return px * px + py * py;
	}
	const t = Math.max(0, Math.min(1, ((p[0] - s[0][0]) * dx + (p[1] - s[0][1]) * dy) / lenSq));
	const projX = s[0][0] + t * dx, projY = s[0][1] + t * dy;
	const qx = p[0] - projX, qy = p[1] - projY;
	return qx * qx + qy * qy;
}

export function distToSegment(p: SelectionPoint, s: SelectionSegment): number {
	return Math.sqrt(distSqToSegment(p, s));
}

export function fenceCrossesSegment(fence: readonly SelectionPoint[], segment: SelectionSegment): boolean {
	for (let i = 1; i < fence.length; i++) {
		if (segmentsIntersect([fence[i - 1], fence[i]], segment)) return true;
	}
	return false;
}

export function polygonCrossesSegment(polygon: readonly SelectionPoint[], segment: SelectionSegment): boolean {
	if (pointInPolygon(segment[0], polygon) || pointInPolygon(segment[1], polygon)) return true;
	for (let i = 0; i < polygon.length; i++) {
		if (segmentsIntersect([polygon[i], polygon[(i + 1) % polygon.length]], segment)) return true;
	}
	return false;
}

export function polygonContainsSegment(polygon: readonly SelectionPoint[], segment: SelectionSegment): boolean {
	if (!pointInPolygon(segment[0], polygon) || !pointInPolygon(segment[1], polygon)) return false;
	const mid: SelectionPoint = [(segment[0][0] + segment[1][0]) / 2, (segment[0][1] + segment[1][1]) / 2];
	if (!pointInPolygon(mid, polygon)) return false;
	// Reject segments that leave a concave polygon through an edge.
	for (let i = 0; i < polygon.length; i++) {
		const edge: SelectionSegment = [polygon[i], polygon[(i + 1) % polygon.length]];
		if (segmentsIntersect(segment, edge) && !onSegment(segment[0], edge) && !onSegment(segment[1], edge)) return false;
	}
	return true;
}

export function sampleBulge(p1: SelectionPoint, p2: SelectionPoint, bulge: number, count = 8): SelectionSegment[] {
	const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
	const d = Math.hypot(dx, dy);
	if (d < 1e-9) return [];
	const r = (d * (1 + bulge * bulge)) / (4 * Math.abs(bulge));
	const h = (d * (1 - bulge * bulge)) / (4 * bulge);
	const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
	const nx = -dy / d, ny = dx / d;
	const cx = mx + h * nx, cy = my + h * ny;
	const a1 = Math.atan2(p1[1] - cy, p1[0] - cx);
	const sweep = 4 * Math.atan(bulge);
	const pts: SelectionPoint[] = [];
	for (let i = 0; i <= count; i++) {
		const a = a1 + (i / count) * sweep;
		pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
	}
	const segs: SelectionSegment[] = [];
	for (let i = 0; i < pts.length - 1; i++) segs.push([pts[i], pts[i + 1]]);
	return segs;
}

export function sampleArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number, count = 16): SelectionSegment[] {
	let sweep = endAngle - startAngle;
	while (sweep <= 0) sweep += 2 * Math.PI;
	while (sweep > 2 * Math.PI) sweep -= 2 * Math.PI;
	const pts: SelectionPoint[] = [];
	for (let i = 0; i <= count; i++) {
		const a = startAngle + (i / count) * sweep;
		pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
	}
	const segs: SelectionSegment[] = [];
	for (let i = 0; i < pts.length - 1; i++) segs.push([pts[i], pts[i + 1]]);
	return segs;
}

export function sampleCircle(cx: number, cy: number, r: number, count = 32): SelectionSegment[] {
	const pts: SelectionPoint[] = [];
	for (let i = 0; i < count; i++) {
		const a = (i / count) * 2 * Math.PI;
		pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
	}
	const segs: SelectionSegment[] = [];
	for (let i = 0; i < count; i++) segs.push([pts[i], pts[(i + 1) % count]]);
	return segs;
}

export function sampleEllipse(
	cx: number,
	cy: number,
	majorVec: SelectionPoint,
	majorRadius: number,
	minorRadius: number,
	startAngle = 0,
	endAngle = 2 * Math.PI,
	count = 32,
): SelectionSegment[] {
	const len = Math.hypot(majorVec[0], majorVec[1]);
	const rot = len > 1e-9 ? Math.atan2(majorVec[1], majorVec[0]) : 0;
	let sweep = endAngle - startAngle;
	while (sweep <= 0) sweep += 2 * Math.PI;
	while (sweep > 2 * Math.PI) sweep -= 2 * Math.PI;
	const isClosed = Math.abs(sweep - 2 * Math.PI) < 1e-4;
	const steps = isClosed ? count : count + 1;
	const pts: SelectionPoint[] = [];
	for (let i = 0; i < steps; i++) {
		const a = startAngle + (i / count) * sweep;
		const lx = majorRadius * Math.cos(a);
		const ly = minorRadius * Math.sin(a);
		pts.push([
			cx + lx * Math.cos(rot) - ly * Math.sin(rot),
			cy + lx * Math.sin(rot) + ly * Math.cos(rot),
		]);
	}
	const segs: SelectionSegment[] = [];
	const segCount = isClosed ? count : pts.length - 1;
	for (let i = 0; i < segCount; i++) {
		const next = isClosed ? (i + 1) % count : i + 1;
		if (pts[next]) segs.push([pts[i], pts[next]]);
	}
	return segs;
}

export function circleMatchesSelection(
	center: SelectionPoint,
	r: number,
	mode: SelectionModeKind,
	boundary: readonly SelectionPoint[],
): boolean {
	const [cx, cy] = center;
	if (r <= 1e-9) {
		if (mode === 'fence') {
			for (let i = 1; i < boundary.length; i++) {
				if (onSegment(center, [boundary[i - 1], boundary[i]])) return true;
			}
			return false;
		}
		return pointInPolygon(center, boundary);
	}

	const segs = sampleCircle(cx, cy, r, 32);

	if (mode === 'fence') {
		for (let i = 1; i < boundary.length; i++) {
			const fs: SelectionSegment = [boundary[i - 1], boundary[i]];
			if (distSqToSegment(center, fs) <= (r + 1e-9) * (r + 1e-9)) return true;
		}
		return false;
	}

	if (mode === 'window') {
		if (!pointInPolygon(center, boundary)) return false;
		for (let i = 0; i < boundary.length; i++) {
			const edge: SelectionSegment = [boundary[i], boundary[(i + 1) % boundary.length]];
			if (distSqToSegment(center, edge) < (r - 1e-6) * (r - 1e-6)) return false;
		}
		for (const s of segs) {
			if (!pointInPolygon(s[0], boundary)) return false;
		}
		return true;
	}

	if (mode === 'crossing') {
		if (pointInPolygon(center, boundary)) return true;
		for (const p of boundary) {
			if (Math.hypot(p[0] - cx, p[1] - cy) <= r + 1e-9) return true;
		}
		for (let i = 0; i < boundary.length; i++) {
			const edge: SelectionSegment = [boundary[i], boundary[(i + 1) % boundary.length]];
			if (distSqToSegment(center, edge) <= (r + 1e-9) * (r + 1e-9)) return true;
		}
		for (const s of segs) {
			if (pointInPolygon(s[0], boundary)) return true;
		}
		return false;
	}

	return false;
}

export function entityMatchesSelection(
	entity: any,
	mode: SelectionModeKind,
	boundary: readonly SelectionPoint[],
): boolean {
	if (!entity || boundary.length < 2) return false;
	const type = String(entity.dxfTypeName ?? '').toUpperCase();

	// 1. LINE
	if (type === 'LINE' || (entity.startPoint && entity.endPoint && !entity.numberOfVertices)) {
		const p1: SelectionPoint = [Number(entity.startPoint.x), Number(entity.startPoint.y)];
		const p2: SelectionPoint = [Number(entity.endPoint.x), Number(entity.endPoint.y)];
		const seg: SelectionSegment = [p1, p2];
		if (mode === 'fence') return fenceCrossesSegment(boundary, seg);
		if (mode === 'window') return polygonContainsSegment(boundary, seg);
		if (mode === 'crossing') return polygonCrossesSegment(boundary, seg);
		return false;
	}

	// 2. CIRCLE
	if (type === 'CIRCLE') {
		const cx = Number(entity.center?.x ?? 0), cy = Number(entity.center?.y ?? 0);
		const r = Number(entity.radius ?? 0);
		return circleMatchesSelection([cx, cy], r, mode, boundary);
	}

	// 3. ARC
	if (type === 'ARC') {
		const cx = Number(entity.center?.x ?? 0), cy = Number(entity.center?.y ?? 0);
		const r = Number(entity.radius ?? 0);
		const startAngle = Number(entity.startAngle ?? 0);
		const endAngle = Number(entity.endAngle ?? 0);
		const segs = sampleArc(cx, cy, r, startAngle, endAngle, 16);
		if (mode === 'fence') return segs.some(s => fenceCrossesSegment(boundary, s));
		if (mode === 'window') return segs.every(s => polygonContainsSegment(boundary, s));
		if (mode === 'crossing') return segs.some(s => polygonCrossesSegment(boundary, s));
		return false;
	}

	// 4. LWPOLYLINE
	if (type === 'LWPOLYLINE' || entity.numberOfVertices !== undefined) {
		const poly = polylineVertices(entity);
		const count = poly.closed ? poly.points.length : poly.points.length - 1;
		const segs: SelectionSegment[] = [];
		for (let i = 0; i < count; i++) {
			const p1: SelectionPoint = poly.points[i];
			const p2: SelectionPoint = poly.points[(i + 1) % poly.points.length];
			const b = poly.bulges[i] ?? 0;
			if (Math.abs(b) >= 1e-6) {
				segs.push(...sampleBulge(p1, p2, b, 8));
			} else {
				segs.push([p1, p2]);
			}
		}
		if (mode === 'fence') {
			if (segs.some(s => fenceCrossesSegment(boundary, s))) return true;
			if (poly.closed && boundary.some(p => pointInPolygon(p, poly.points))) return true;
			return false;
		}
		if (mode === 'window') {
			return segs.length > 0 && segs.every(s => polygonContainsSegment(boundary, s));
		}
		if (mode === 'crossing') {
			if (segs.some(s => polygonCrossesSegment(boundary, s))) return true;
			if (poly.points.some(p => pointInPolygon(p, boundary))) return true;
			if (poly.closed && boundary.some(p => pointInPolygon(p, poly.points))) return true;
			return false;
		}
		return false;
	}

	// 5. ELLIPSE
	if (type === 'ELLIPSE') {
		const cx = Number(entity.center?.x ?? 0), cy = Number(entity.center?.y ?? 0);
		const majorVec: SelectionPoint = [Number(entity.majorAxis?.x ?? 1), Number(entity.majorAxis?.y ?? 0)];
		const majorR = Number(entity.majorAxisRadius ?? Math.hypot(majorVec[0], majorVec[1]));
		const minorR = Number(entity.minorAxisRadius ?? (majorR * (entity.radiusRatio ?? 1)));
		const startAngle = Number(entity.startAngle ?? 0);
		const endAngle = Number(entity.endAngle ?? 2 * Math.PI);
		const segs = sampleEllipse(cx, cy, majorVec, majorR, minorR, startAngle, endAngle, 32);
		if (mode === 'fence') return segs.some(s => fenceCrossesSegment(boundary, s));
		if (mode === 'window') return segs.length > 0 && segs.every(s => polygonContainsSegment(boundary, s));
		if (mode === 'crossing') {
			if (segs.some(s => polygonCrossesSegment(boundary, s))) return true;
			if (pointInPolygon([cx, cy], boundary)) return true;
			return false;
		}
		return false;
	}

	// 6. Bounding box via geometricExtents for HATCH, DIMENSION, TEXT, MTEXT, INSERT, etc.
	let extents = entity.geometricExtents;
	if (!extents && typeof entity.getGeometricExtentsFromDimBlockOrPoints === 'function') {
		try { extents = entity.getGeometricExtentsFromDimBlockOrPoints(); } catch { /* ignore */ }
	}
	if (!extents && entity.boundingBox) extents = entity.boundingBox;

	if (extents?.min && extents?.max) {
		const minX = Number(extents.min.x), minY = Number(extents.min.y);
		const maxX = Number(extents.max.x), maxY = Number(extents.max.y);
		if (Math.abs(maxX - minX) > 1e-9 || Math.abs(maxY - minY) > 1e-9) {
			const c0: SelectionPoint = [minX, minY], c1: SelectionPoint = [maxX, minY];
			const c2: SelectionPoint = [maxX, maxY], c3: SelectionPoint = [minX, maxY];
			const boxCorners: readonly SelectionPoint[] = [c0, c1, c2, c3];
			const boxSegs: readonly SelectionSegment[] = [[c0, c1], [c1, c2], [c2, c3], [c3, c0]];
			const inBox = (p: SelectionPoint) => p[0] >= minX - EPS && p[0] <= maxX + EPS && p[1] >= minY - EPS && p[1] <= maxY + EPS;

			if (mode === 'fence') {
				return boxSegs.some(s => fenceCrossesSegment(boundary, s)) || boundary.some(inBox);
			}
			if (mode === 'window') {
				return boxCorners.every(p => pointInPolygon(p, boundary)) && boxSegs.every(s => polygonContainsSegment(boundary, s));
			}
			if (mode === 'crossing') {
				return boxCorners.some(p => pointInPolygon(p, boundary)) ||
					boxSegs.some(s => polygonCrossesSegment(boundary, s)) ||
					boundary.some(inBox);
			}
			return false;
		}
	}

	// 7. Single position / insertion point fallback (POINT, TEXT without extents, etc.)
	const pos = entity.position ?? entity.alignmentPoint ?? entity.insertionPoint;
	if (pos) {
		const p: SelectionPoint = [Number(pos.x ?? 0), Number(pos.y ?? 0)];
		if (mode === 'fence') {
			for (let i = 1; i < boundary.length; i++) {
				if (onSegment(p, [boundary[i - 1], boundary[i]])) return true;
			}
			return false;
		}
		return pointInPolygon(p, boundary);
	}

	return false;
}

/** Computes the shortest 2D distance from a point to an entity's linework/boundary. */
export function entityDistanceToPoint(entity: any, point: SelectionPoint): number {
	if (!entity) return Infinity;
	const type = String(entity.dxfTypeName ?? '').toUpperCase();

	// 1. LINE
	if (type === 'LINE' || (entity.startPoint && entity.endPoint && !entity.numberOfVertices)) {
		const p1: SelectionPoint = [Number(entity.startPoint.x), Number(entity.startPoint.y)];
		const p2: SelectionPoint = [Number(entity.endPoint.x), Number(entity.endPoint.y)];
		return distToSegment(point, [p1, p2]);
	}

	// 2. CIRCLE
	if (type === 'CIRCLE') {
		const cx = Number(entity.center?.x ?? 0), cy = Number(entity.center?.y ?? 0);
		const r = Number(entity.radius ?? 0);
		return Math.abs(Math.hypot(point[0] - cx, point[1] - cy) - r);
	}

	// 3. ARC
	if (type === 'ARC') {
		const cx = Number(entity.center?.x ?? 0), cy = Number(entity.center?.y ?? 0);
		const r = Number(entity.radius ?? 0);
		const startAngle = Number(entity.startAngle ?? 0);
		const endAngle = Number(entity.endAngle ?? 0);
		const segs = sampleArc(cx, cy, r, startAngle, endAngle, 32);
		let min = Infinity;
		for (const s of segs) {
			const d = distToSegment(point, s);
			if (d < min) min = d;
		}
		return min;
	}

	// 4. LWPOLYLINE
	if (type === 'LWPOLYLINE' || entity.numberOfVertices !== undefined) {
		const poly = polylineVertices(entity);
		const count = poly.closed ? poly.points.length : poly.points.length - 1;
		let min = Infinity;
		for (let i = 0; i < count; i++) {
			const p1: SelectionPoint = poly.points[i];
			const p2: SelectionPoint = poly.points[(i + 1) % poly.points.length];
			const b = poly.bulges[i] ?? 0;
			if (Math.abs(b) >= 1e-6) {
				for (const s of sampleBulge(p1, p2, b, 8)) {
					const d = distToSegment(point, s);
					if (d < min) min = d;
				}
			} else {
				const d = distToSegment(point, [p1, p2]);
				if (d < min) min = d;
			}
		}
		return min;
	}

	// 5. ELLIPSE
	if (type === 'ELLIPSE') {
		const cx = Number(entity.center?.x ?? 0), cy = Number(entity.center?.y ?? 0);
		const majorVec: SelectionPoint = [Number(entity.majorAxis?.x ?? 1), Number(entity.majorAxis?.y ?? 0)];
		const majorR = Number(entity.majorAxisRadius ?? Math.hypot(majorVec[0], majorVec[1]));
		const minorR = Number(entity.minorAxisRadius ?? (majorR * (entity.radiusRatio ?? 1)));
		const startAngle = Number(entity.startAngle ?? 0);
		const endAngle = Number(entity.endAngle ?? 2 * Math.PI);
		const segs = sampleEllipse(cx, cy, majorVec, majorR, minorR, startAngle, endAngle, 32);
		let min = Infinity;
		for (const s of segs) {
			const d = distToSegment(point, s);
			if (d < min) min = d;
		}
		return min;
	}

	// 6. Bounding box / extents (HATCH, DIMENSION, TEXT, MTEXT, INSERT, etc.)
	let extents = entity.geometricExtents;
	if (!extents && typeof entity.getGeometricExtentsFromDimBlockOrPoints === 'function') {
		try { extents = entity.getGeometricExtentsFromDimBlockOrPoints(); } catch { /* ignore */ }
	}
	if (!extents && entity.boundingBox) extents = entity.boundingBox;

	if (extents?.min && extents?.max) {
		const minX = Number(extents.min.x), minY = Number(extents.min.y);
		const maxX = Number(extents.max.x), maxY = Number(extents.max.y);
		if (point[0] >= minX && point[0] <= maxX && point[1] >= minY && point[1] <= maxY) {
			return 0;
		}
		const c0: SelectionPoint = [minX, minY], c1: SelectionPoint = [maxX, minY];
		const c2: SelectionPoint = [maxX, maxY], c3: SelectionPoint = [minX, maxY];
		return Math.min(
			distToSegment(point, [c0, c1]),
			distToSegment(point, [c1, c2]),
			distToSegment(point, [c2, c3]),
			distToSegment(point, [c3, c0]),
		);
	}

	// 7. Single position / insertion point fallback
	const pos = entity.position ?? entity.alignmentPoint ?? entity.insertionPoint;
	if (pos) {
		return Math.hypot(point[0] - Number(pos.x ?? 0), point[1] - Number(pos.y ?? 0));
	}

	return Infinity;
}

export interface PickDraftingOptions {
	readonly generated?: ReadonlySet<string>;
	readonly preview?: ReadonlySet<string>;
	readonly generatedLayers?: ReadonlySet<string>;
}

/** Determines if an entity is a non-generated, non-locked, visible drafting entity. */
export function isEntitySelectable(
	entity: any,
	db: any,
	options?: PickDraftingOptions,
): boolean {
	if (!entity) return false;
	const id = String(entity.objectId ?? '');
	if (!id) return false;
	if (entity.isErased) return false;
	const session = (globalThis as any).__saengineActiveBlockEditorSession;
	if (session && !session.editEntityIds?.has(id)) return false;
	if (options?.generated?.has(id) || options?.preview?.has(id)) return false;
	if (entity.visibility === false) return false;

	const layer = entity.layer;
	if (layer && options?.generatedLayers?.has(layer)) return false;
	if (layer && db?.tables?.layerTable) {
		const rec = db.tables.layerTable.getAt(layer);
		if (rec) {
			if (rec.isLocked) return false;
			if (rec.isOff || rec.isFrozen) return false;
		}
	}
	return true;
}

/**
 * Returns IDs of non-generated, non-locked, visible entities whose geometry is within
 * tolerance of the point, nearest first.
 */
export function pickDrafting(
	dbOrPoint: any,
	pointOrTol?: any,
	toleranceOrOptions?: any,
	maybeOptions?: PickDraftingOptions,
): string[] {
	let db: any = dbOrPoint;
	let point: SelectionPoint;
	let tolerance = 0;
	let options: PickDraftingOptions | undefined;

	if (Array.isArray(dbOrPoint) || typeof (dbOrPoint as any)?.[0] === 'number') {
		try { db = acdbHostApplicationServices().workingDatabase; } catch { db = undefined; }
		point = dbOrPoint as SelectionPoint;
		tolerance = typeof pointOrTol === 'number' ? pointOrTol : 0;
		options = toleranceOrOptions as PickDraftingOptions;
	} else {
		point = pointOrTol as SelectionPoint;
		tolerance = typeof toleranceOrOptions === 'number' ? toleranceOrOptions : 0;
		options = maybeOptions;
	}

	if (!db) return [];
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace) return [];

	const hits: { id: string; dist: number }[] = [];
	const iterator = typeof modelSpace.newIterator === 'function' ? modelSpace.newIterator() : [];
	for (const ent of iterator) {
		if (!isEntitySelectable(ent, db, options)) continue;
		const dist = entityDistanceToPoint(ent, point);
		if (dist <= tolerance) {
			hits.push({ id: String(ent.objectId), dist });
		}
	}

	hits.sort((a, b) => a.dist - b.dist);
	return hits.map(h => h.id);
}

export interface CadDraftingHit {
	readonly id: string;
	readonly type: string;
	readonly layer: string;
	readonly distance: number;
}

/**
 * Returns detailed hit information for non-generated, non-locked, visible entities whose
 * geometry is within tolerance of the point, nearest first.
 */
export function pickDraftingAll(
	dbOrPoint: any,
	pointOrTol?: any,
	toleranceOrOptions?: any,
	maybeOptions?: PickDraftingOptions,
): CadDraftingHit[] {
	let db: any = dbOrPoint;
	let point: SelectionPoint;
	let tolerance = 0;
	let options: PickDraftingOptions | undefined;

	if (Array.isArray(dbOrPoint) || typeof (dbOrPoint as any)?.[0] === 'number') {
		try { db = acdbHostApplicationServices().workingDatabase; } catch { db = undefined; }
		point = dbOrPoint as SelectionPoint;
		tolerance = typeof pointOrTol === 'number' ? pointOrTol : 0;
		options = toleranceOrOptions as PickDraftingOptions;
	} else {
		point = pointOrTol as SelectionPoint;
		tolerance = typeof toleranceOrOptions === 'number' ? toleranceOrOptions : 0;
		options = maybeOptions;
	}

	if (!db) return [];
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace) return [];

	const hits: CadDraftingHit[] = [];
	const iterator = typeof modelSpace.newIterator === 'function' ? modelSpace.newIterator() : [];
	for (const ent of iterator) {
		if (!isEntitySelectable(ent, db, options)) continue;
		const dist = entityDistanceToPoint(ent, point);
		if (dist <= tolerance) {
			hits.push({
				id: String(ent.objectId),
				type: String(ent.dxfTypeName ?? ent.type ?? 'Entity'),
				layer: String(ent.layer ?? '0'),
				distance: dist,
			});
		}
	}

	hits.sort((a, b) => a.distance - b.distance);
	return hits;
}

/**
 * Returns IDs of non-generated, non-locked, visible entities matching a window or crossing
 * box selection.
 */
export function pickDraftingWindow(
	dbOrStart: any,
	startOrEnd: any,
	endOrMode: any,
	modeOrOptions?: any,
	maybeOptions?: PickDraftingOptions,
): string[] {
	let db: any = dbOrStart;
	let start: SelectionPoint;
	let end: SelectionPoint;
	let mode: SelectionModeKind;
	let options: PickDraftingOptions | undefined;

	if (Array.isArray(dbOrStart) || typeof (dbOrStart as any)?.[0] === 'number') {
		try { db = acdbHostApplicationServices().workingDatabase; } catch { db = undefined; }
		start = dbOrStart as SelectionPoint;
		end = startOrEnd as SelectionPoint;
		mode = (endOrMode ?? 'window') as SelectionModeKind;
		options = modeOrOptions as PickDraftingOptions;
	} else {
		start = startOrEnd as SelectionPoint;
		end = endOrMode as SelectionPoint;
		mode = (modeOrOptions ?? 'window') as SelectionModeKind;
		options = maybeOptions;
	}

	if (!db) return [];
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace) return [];

	const minX = Math.min(start[0], end[0]), maxX = Math.max(start[0], end[0]);
	const minY = Math.min(start[1], end[1]), maxY = Math.max(start[1], end[1]);
	const boundary: readonly SelectionPoint[] = [
		[minX, minY],
		[maxX, minY],
		[maxX, maxY],
		[minX, maxY],
	];

	const result: string[] = [];
	const iterator = typeof modelSpace.newIterator === 'function' ? modelSpace.newIterator() : [];
	for (const ent of iterator) {
		if (!isEntitySelectable(ent, db, options)) continue;
		if (entityMatchesSelection(ent, mode, boundary)) {
			result.push(String(ent.objectId));
		}
	}
	return result;
}

/**
 * Returns IDs of non-generated, non-locked, visible entities matching a polygon boundary
 * (window, crossing, or fence).
 */
export function pickDraftingPolygon(
	dbOrPoints: any,
	pointsOrMode?: any,
	modeOrOptions?: any,
	maybeOptions?: PickDraftingOptions,
): string[] {
	let db: any = dbOrPoints;
	let points: readonly SelectionPoint[];
	let mode: SelectionModeKind;
	let options: PickDraftingOptions | undefined;

	if (Array.isArray(dbOrPoints) && (dbOrPoints.length === 0 || Array.isArray(dbOrPoints[0]) || typeof dbOrPoints[0]?.[0] === 'number')) {
		try { db = acdbHostApplicationServices().workingDatabase; } catch { db = undefined; }
		points = dbOrPoints as readonly SelectionPoint[];
		mode = (typeof pointsOrMode === 'string' ? pointsOrMode : 'window') as SelectionModeKind;
		options = modeOrOptions as PickDraftingOptions;
	} else {
		points = pointsOrMode as readonly SelectionPoint[];
		mode = (typeof modeOrOptions === 'string' ? modeOrOptions : 'window') as SelectionModeKind;
		options = maybeOptions;
	}

	if (!db || !points || points.length < 2) return [];
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace) return [];

	const result: string[] = [];
	const iterator = typeof modelSpace.newIterator === 'function' ? modelSpace.newIterator() : [];
	for (const ent of iterator) {
		if (!isEntitySelectable(ent, db, options)) continue;
		if (entityMatchesSelection(ent, mode, points)) {
			result.push(String(ent.objectId));
		}
	}
	return result;
}
