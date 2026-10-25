/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Plan geometry shared by the SAEngine editors: polygons as rings of [x, y] points, the last
 * point not repeating the first.
 */

/** The signed area of a polygon (shoelace), anticlockwise positive, in the points' units squared. */
export function signedArea(points: readonly (readonly [number, number])[]): number {
	let sum = 0;
	for (let i = 0; i < points.length; i++) {
		const [x0, y0] = points[i];
		const [x1, y1] = points[(i + 1) % points.length];
		sum += x0 * y1 - x1 * y0;
	}
	return sum / 2;
}

/** The area of a polygon, whichever way round it runs. */
export function polygonArea(points: readonly (readonly [number, number])[]): number {
	return Math.abs(signedArea(points));
}

/** The mean of the points (where a label goes, a foundation's centre); undefined for none. */
export function centroid(points: readonly (readonly [number, number])[]): [number, number] | undefined {
	if (!points.length) {
		return undefined;
	}
	return [points.reduce((s, p) => s + p[0], 0) / points.length, points.reduce((s, p) => s + p[1], 0) / points.length];
}
