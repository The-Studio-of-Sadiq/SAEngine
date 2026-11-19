/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbArc, AcDbCircle, AcDbEllipse, AcDbEntity, AcDbLine, AcDbPolyline, AcDbSpline } from '@mlightcad/data-model';
import { polylineVertices } from './entityAccess.js';

export type P2 = readonly [number, number];

export interface PathPointAndTangent {
	readonly point: P2;
	readonly tangentAngle: number; // in radians
}

export interface PathCurve {
	readonly length: number;
	pointAndTangentAt(distance: number): PathPointAndTangent;
}

const dist = (a: P2, b: P2): number => Math.hypot(b[0] - a[0], b[1] - a[1]);

export function linePath(p1: P2, p2: P2): PathCurve {
	const dx = p2[0] - p1[0];
	const dy = p2[1] - p1[1];
	const length = Math.hypot(dx, dy);
	const tangentAngle = Math.atan2(dy, dx);
	return {
		length,
		pointAndTangentAt(d: number): PathPointAndTangent {
			const t = length > 0 ? Math.max(0, Math.min(1, d / length)) : 0;
			return {
				point: [p1[0] + dx * t, p1[1] + dy * t],
				tangentAngle,
			};
		},
	};
}

export function arcPath(center: P2, radius: number, startAngleRad: number, endAngleRad: number): PathCurve {
	const sweep = ((endAngleRad - startAngleRad) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || 2 * Math.PI;
	const length = radius * sweep;
	return {
		length,
		pointAndTangentAt(d: number): PathPointAndTangent {
			const t = length > 0 ? Math.max(0, Math.min(1, d / length)) : 0;
			const phi = startAngleRad + t * sweep;
			return {
				point: [center[0] + radius * Math.cos(phi), center[1] + radius * Math.sin(phi)],
				tangentAngle: phi + Math.PI / 2,
			};
		},
	};
}

export function circlePath(center: P2, radius: number): PathCurve {
	return arcPath(center, radius, 0, 2 * Math.PI);
}

function arcFromBulge(a: P2, b: P2, bulge: number) {
	const chord = dist(a, b);
	if (!bulge || chord === 0) return undefined;
	const theta = 4 * Math.atan(bulge);
	const radius = chord * (1 + bulge * bulge) / (4 * Math.abs(bulge));
	const mx = (a[0] + b[0]) / 2;
	const my = (a[1] + b[1]) / 2;
	const h = chord * (1 - bulge * bulge) / (4 * bulge);
	const ux = -(b[1] - a[1]) / chord;
	const uy = (b[0] - a[0]) / chord;
	const cx = mx + ux * h;
	const cy = my + uy * h;
	const start = Math.atan2(a[1] - cy, a[0] - cx);
	return { center: [cx, cy] as P2, radius, start, sweep: theta };
}

export function polylinePath(vertices: readonly P2[], bulges: readonly number[], closed: boolean): PathCurve {
	const n = vertices.length;
	const count = closed ? n : Math.max(0, n - 1);
	const segments: { startDist: number; endDist: number; curve: PathCurve }[] = [];
	let acc = 0;

	for (let i = 0; i < count; i++) {
		const a = vertices[i];
		const b = vertices[(i + 1) % n];
		const bulge = bulges[i] || 0;
		let segCurve: PathCurve;
		const arc = arcFromBulge(a, b, bulge);
		if (arc) {
			const isCCW = arc.sweep > 0;
			const len = arc.radius * Math.abs(arc.sweep);
			segCurve = {
				length: len,
				pointAndTangentAt(d: number): PathPointAndTangent {
					const t = len > 0 ? Math.max(0, Math.min(1, d / len)) : 0;
					const phi = arc.start + t * arc.sweep;
					return {
						point: [arc.center[0] + arc.radius * Math.cos(phi), arc.center[1] + arc.radius * Math.sin(phi)],
						tangentAngle: isCCW ? phi + Math.PI / 2 : phi - Math.PI / 2,
					};
				},
			};
		} else {
			segCurve = linePath(a, b);
		}
		segments.push({ startDist: acc, endDist: acc + segCurve.length, curve: segCurve });
		acc += segCurve.length;
	}

	const totalLength = acc;
	return {
		length: totalLength,
		pointAndTangentAt(d: number): PathPointAndTangent {
			if (segments.length === 0) return { point: [0, 0], tangentAngle: 0 };
			const clamped = Math.max(0, Math.min(totalLength, d));
			for (let i = 0; i < segments.length; i++) {
				const seg = segments[i];
				if (clamped <= seg.endDist || i === segments.length - 1) {
					return seg.curve.pointAndTangentAt(clamped - seg.startDist);
				}
			}
			return segments[0].curve.pointAndTangentAt(0);
		},
	};
}

export function sampledPolylinePath(points: readonly P2[]): PathCurve {
	const bulges = new Array(points.length).fill(0);
	return polylinePath(points, bulges, false);
}

export function ellipsePath(
	center: P2,
	majorRadius: number,
	minorRadius: number,
	majorAxisAngleRad: number,
	startAngleRad = 0,
	endAngleRad = 2 * Math.PI,
): PathCurve {
	const sweep = ((endAngleRad - startAngleRad) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || 2 * Math.PI;
	const sampleCount = 256;
	const pts: P2[] = [];
	const cosA = Math.cos(majorAxisAngleRad);
	const sinA = Math.sin(majorAxisAngleRad);

	for (let i = 0; i <= sampleCount; i++) {
		const t = startAngleRad + (i / sampleCount) * sweep;
		const x0 = majorRadius * Math.cos(t);
		const y0 = minorRadius * Math.sin(t);
		pts.push([
			center[0] + x0 * cosA - y0 * sinA,
			center[1] + x0 * sinA + y0 * cosA,
		]);
	}
	return sampledPolylinePath(pts);
}

export function createPathCurveFromEntity(entity: AcDbEntity): PathCurve | undefined {
	if (entity instanceof AcDbLine) {
		return linePath([entity.startPoint.x, entity.startPoint.y], [entity.endPoint.x, entity.endPoint.y]);
	}
	if (entity instanceof AcDbArc) {
		return arcPath([entity.center.x, entity.center.y], entity.radius, entity.startAngle, entity.endAngle);
	}
	if (entity instanceof AcDbCircle) {
		return circlePath([entity.center.x, entity.center.y], entity.radius);
	}
	if (entity instanceof AcDbPolyline) {
		const { points, bulges, closed } = polylineVertices(entity);
		return polylinePath(points, bulges, closed);
	}
	if (entity instanceof AcDbEllipse) {
		const axisAngle = Math.atan2(entity.majorAxis.y, entity.majorAxis.x);
		return ellipsePath(
			[entity.center.x, entity.center.y],
			entity.majorAxisRadius,
			entity.minorAxisRadius,
			axisAngle,
			entity.startAngle,
			entity.endAngle,
		);
	}
	if (entity instanceof AcDbSpline) {
		const geo = (entity as any)._geo;
		if (geo && typeof geo.getOffsetSamplePath2d === 'function') {
			const sampled = geo.getOffsetSamplePath2d(1);
			if (sampled?.points?.length > 1) {
				const pts: P2[] = sampled.points.map((p: any) => [p.x, p.y] as P2);
				return sampledPolylinePath(pts);
			}
		}
		const anyEnt = entity as any;
		if (Array.isArray(anyEnt.fitPoints) && anyEnt.fitPoints.length > 1) {
			const pts: P2[] = anyEnt.fitPoints.map((p: any) => [p.x, p.y] as P2);
			return sampledPolylinePath(pts);
		}
		if (Array.isArray(anyEnt.controlPoints) && anyEnt.controlPoints.length > 1) {
			const pts: P2[] = anyEnt.controlPoints.map((p: any) => [p.x, p.y] as P2);
			return sampledPolylinePath(pts);
		}
		if (Array.isArray(geo?.controlPoints) && geo.controlPoints.length > 1) {
			const pts: P2[] = geo.controlPoints.map((p: any) => [p.x, p.y] as P2);
			return sampledPolylinePath(pts);
		}
	}
	return undefined;
}

export interface PathArrayOptions {
	readonly method: 'Divide' | 'Measure';
	readonly itemCount?: number;
	readonly itemSpacing?: number;
	readonly rows?: number;
	readonly rowSpacing?: number;
	readonly alignItems?: boolean;
	readonly basePoint: P2;
	readonly tangentAngle0?: number;
}

export interface PathArrayTransform {
	readonly index: number;
	readonly row: number;
	readonly distance: number;
	readonly position: P2;
	readonly rotationAngle: number;
}

export function computePathArrayTransforms(
	path: PathCurve,
	options: PathArrayOptions,
): PathArrayTransform[] {
	if (path.length <= 0) return [];

	const distances: number[] = [];
	if (options.method === 'Divide') {
		const n = Math.max(2, Math.round(options.itemCount ?? 2));
		for (let i = 0; i < n; i++) {
			distances.push((i * path.length) / (n - 1));
		}
	} else {
		// Measure
		const spacing = options.itemSpacing && options.itemSpacing > 0 ? options.itemSpacing : path.length / 5;
		let s = 0;
		while (s <= path.length + 1e-9) {
			distances.push(Math.min(s, path.length));
			s += spacing;
			if (options.itemCount && distances.length >= options.itemCount) break;
		}
		if (distances.length === 0) distances.push(0);
	}

	const tangent0 = options.tangentAngle0 !== undefined
		? options.tangentAngle0
		: path.pointAndTangentAt(0).tangentAngle;

	const rows = Math.max(1, Math.round(options.rows ?? 1));
	const rowSpacing = options.rowSpacing ?? (options.itemSpacing || 10);
	const align = options.alignItems !== false;

	const out: PathArrayTransform[] = [];
	for (let r = 0; r < rows; r++) {
		for (let i = 0; i < distances.length; i++) {
			const s = distances[i];
			const { point, tangentAngle } = path.pointAndTangentAt(s);
			const rotAngle = align ? tangentAngle - tangent0 : 0;

			let posX = point[0];
			let posY = point[1];
			if (r > 0) {
				if (align) {
					// Perpendicular to path tangent (90 degrees CCW)
					const normAngle = tangentAngle + Math.PI / 2;
					posX += r * rowSpacing * Math.cos(normAngle);
					posY += r * rowSpacing * Math.sin(normAngle);
				} else {
					posY += r * rowSpacing;
				}
			}

			out.push({
				index: i,
				row: r,
				distance: s,
				position: [posX, posY],
				rotationAngle: rotAngle,
			});
		}
	}

	return out;
}
