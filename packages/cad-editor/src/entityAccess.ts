/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbPolyline } from '@mlightcad/data-model';
import type { CadPoint } from './generated.js';

export interface PolylineData {
	points: [number, number][];
	bulges: number[];
	closed: boolean;
}

/**
 * Extract 2D vertices, bulge factors, and closed flag from an AcDbPolyline.
 * Uses `(e as any)._geo?.vertices?.[i]?.bulge ?? 0` since the library
 * exposes no public bulge accessor on AcDbPolyline.
 */
export function polylineVertices(e: AcDbPolyline): PolylineData {
	const points: [number, number][] = [];
	const bulges: number[] = [];
	const n = e.numberOfVertices;
	const closed = !!e.closed;
	const count = closed ? n : Math.max(0, n - 1);
	for (let i = 0; i < n; i++) {
		const pt = e.getPoint2dAt(i);
		points.push([pt.x, pt.y]);
	}
	for (let i = 0; i < count; i++) {
		bulges.push((e as unknown as { _geo?: { vertices?: { bulge?: number }[] } })._geo?.vertices?.[i]?.bulge ?? 0);
	}
	return { points, bulges, closed };
}

export interface CadSelectedEntity {
	readonly handle: string;
	readonly kind: 'line' | 'polyline' | 'arc' | 'circle' | string;
	readonly points: readonly CadPoint[];
	readonly closed?: boolean;
}

/** Reads selected geometry from an entity in the CAD database. */
export function entityToSelectedGeometry(entity: AcDbEntity): CadSelectedEntity | undefined {
	const handle = String((entity as any).handle || entity.objectId);
	if (entity.dxfTypeName === 'LINE') {
		const line = entity as AcDbLine;
		return {
			handle,
			kind: 'line',
			points: [
				[line.startPoint.x, line.startPoint.y],
				[line.endPoint.x, line.endPoint.y],
			],
		};
	}
	if (entity.dxfTypeName === 'LWPOLYLINE') {
		const poly = entity as AcDbPolyline;
		return {
			handle,
			kind: 'polyline',
			points: polylineVertices(poly).points,
			closed: !!poly.closed,
		};
	}
	if (entity.dxfTypeName === 'ARC') {
		const arc = entity as AcDbArc;
		return {
			handle,
			kind: 'arc',
			points: [[arc.center.x, arc.center.y]],
		};
	}
	if (entity.dxfTypeName === 'CIRCLE') {
		const circle = entity as AcDbCircle;
		return {
			handle,
			kind: 'circle',
			points: [[circle.center.x, circle.center.y]],
		};
	}
	return undefined;
}
