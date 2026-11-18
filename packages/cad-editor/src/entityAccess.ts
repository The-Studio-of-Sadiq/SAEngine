/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbPolyline } from '@mlightcad/data-model';
import type { CadPoint } from './generated.js';

export interface CadSelectedEntity {
	readonly handle: string;
	readonly kind: 'line' | 'polyline' | 'arc' | 'circle' | string;
	readonly points: readonly CadPoint[];
	readonly closed?: boolean;
}

/** Extracts 2D polyline vertices in order. */
export function polylineVertices(poly: AcDbPolyline): CadPoint[] {
	const pts: CadPoint[] = [];
	for (let i = 0; i < poly.numberOfVertices; i++) {
		const pt = poly.getPoint2dAt(i);
		pts.push([pt.x, pt.y]);
	}
	return pts;
}

/** Reads selected geometry from an entity in the CAD database. */
export function entityToSelectedGeometry(entity: AcDbEntity): CadSelectedEntity | undefined {
	const handle = String((entity as any).handle || entity.objectId);
	if (entity instanceof AcDbLine || entity.dxfTypeName === 'LINE') {
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
	if (entity instanceof AcDbPolyline || entity.dxfTypeName === 'LWPOLYLINE') {
		const poly = entity as AcDbPolyline;
		return {
			handle,
			kind: 'polyline',
			points: polylineVertices(poly),
			closed: !!poly.closed,
		};
	}
	if (entity instanceof AcDbArc || entity.dxfTypeName === 'ARC') {
		const arc = entity as AcDbArc;
		return {
			handle,
			kind: 'arc',
			points: [[arc.center.x, arc.center.y]],
		};
	}
	if (entity instanceof AcDbCircle || entity.dxfTypeName === 'CIRCLE') {
		const circle = entity as AcDbCircle;
		return {
			handle,
			kind: 'circle',
			points: [[circle.center.x, circle.center.y]],
		};
	}
	return undefined;
}
