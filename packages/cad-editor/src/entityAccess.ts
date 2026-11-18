/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbPolyline } from '@mlightcad/data-model';

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
