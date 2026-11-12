/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { ModelerScene, ModelPoint } from '@saengine/fem-viewer';

/*
 * The structural model of a special structure (`structure.json`, see python
 * `saengine.library.structure`) as the 3D modeller draws it: its grid systems turned into lines
 * and intersection points, and its members, areas and supports with the kinds of their types.
 */

export type Json = { [key: string]: unknown };

export function isJson(value: unknown): value is Json {
	return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isJson) : [];
}

function num(value: unknown, fallback = 0): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** A point of the file ({x, y, z} in mm) as a tuple. */
export function point(value: unknown): ModelPoint {
	return isJson(value) ? [num(value.x), num(value.y), num(value.z)] : [0, 0, 0];
}

/** A tuple as a point of the file, rounded to 0.1 mm. */
export function json(p: ModelPoint): Json {
	const round = (v: number) => Math.round(v * 10) / 10;
	return { x: round(p[0]), y: round(p[1]), z: round(p[2]) };
}

export interface ILevel {
	readonly label: string;
	readonly z: number;
}

/** Ring segments drawn per full circle of a cylindrical grid. */
const RING_SEGMENTS = 72;

/** The lines and intersection points of every grid system, and the levels they define. */
export function gridGeometry(grids: unknown): { lines: [ModelPoint, ModelPoint][]; points: ModelPoint[]; levels: ILevel[] } {
	const lines: [ModelPoint, ModelPoint][] = [];
	const points: ModelPoint[] = [];
	const levels = new Map<number, string>();
	for (const grid of list(grids)) {
		const origin = point(grid.origin);
		const zs = list(grid.z).map(l => ({ label: String(l.label ?? ''), z: origin[2] + num(l.position) }));
		for (const level of zs) {
			if (!levels.has(level.z)) {
				levels.set(level.z, level.label);
			}
		}
		if (grid.kind === 'cylindrical') {
			const radii = list(grid.radii).map(l => num(l.position));
			const angles = list(grid.angles).map(l => num(l.angle) * Math.PI / 180);
			const outer = Math.max(0, ...radii);
			const at = (r: number, a: number, z: number): ModelPoint => [origin[0] + r * Math.cos(a), origin[1] + r * Math.sin(a), z];
			for (const { z } of zs) {
				points.push([origin[0], origin[1], z]);
				for (const r of radii) {
					for (let k = 0; k < RING_SEGMENTS; k++) {
						lines.push([at(r, 2 * Math.PI * k / RING_SEGMENTS, z), at(r, 2 * Math.PI * (k + 1) / RING_SEGMENTS, z)]);
					}
					points.push(...angles.map(a => at(r, a, z)));
				}
				lines.push(...angles.map(a => [at(0, a, z), at(outer, a, z)] as [ModelPoint, ModelPoint]));
			}
			continue;
		}
		const rotation = num(grid.rotation) * Math.PI / 180;
		const ux = [Math.cos(rotation), Math.sin(rotation)];
		const uy = [-Math.sin(rotation), Math.cos(rotation)];
		const xs = list(grid.x).map(l => num(l.position));
		const ys = list(grid.y).map(l => num(l.position));
		const at = (x: number, y: number, z: number): ModelPoint => [origin[0] + x * ux[0] + y * uy[0], origin[1] + x * ux[1] + y * uy[1], z];
		const [x0, x1] = [Math.min(0, ...xs), Math.max(0, ...xs)];
		const [y0, y1] = [Math.min(0, ...ys), Math.max(0, ...ys)];
		for (const { z } of zs) {
			lines.push(...xs.map(x => [at(x, y0, z), at(x, y1, z)] as [ModelPoint, ModelPoint]));
			lines.push(...ys.map(y => [at(x0, y, z), at(x1, y, z)] as [ModelPoint, ModelPoint]));
			for (const x of xs) {
				points.push(...ys.map(y => at(x, y, z)));
			}
		}
	}
	return { lines, points, levels: [...levels].map(([z, label]) => ({ label, z })).sort((a, b) => a.z - b.z) };
}

/** The unit normal of a polygon (Newell's method), or undefined when it has no area. */
export function polygonNormal(points: readonly ModelPoint[]): ModelPoint | undefined {
	let nx = 0, ny = 0, nz = 0;
	for (let i = 0; i < points.length; i++) {
		const a = points[i];
		const b = points[(i + 1) % points.length];
		nx += (a[1] - b[1]) * (a[2] + b[2]);
		ny += (a[2] - b[2]) * (a[0] + b[0]);
		nz += (a[0] - b[0]) * (a[1] + b[1]);
	}
	const size = Math.hypot(nx, ny, nz);
	return size < 1 ? undefined : [nx / size, ny / size, nz / size];
}

/** Object type id -> kind (beam, column, brace, slab, wall...), from `objects.json`. */
export function typeKinds(objects: unknown): Map<string, string> {
	return new Map(list(isJson(objects) ? objects.objects : undefined).map(o => [String(o.id), String(o.kind)]));
}

/** What the modeller draws of the structural model `doc`. */
export function modelerScene(doc: unknown, kinds: ReadonlyMap<string, string>): ModelerScene {
	const model = isJson(doc) ? doc : {};
	const grid = gridGeometry(model.grids);
	return {
		gridLines: grid.lines,
		gridPoints: grid.points,
		members: list(model.members).map(m => ({ id: String(m.id), start: point(m.start), end: point(m.end), kind: kinds.get(String(m.type)) ?? 'unknown' })),
		areas: list(model.areas).map(a => ({
			id: String(a.id), outline: list(a.outline).map(point), openings: list(a.openings).map(o => list(o.outline).map(point)),
			kind: kinds.get(String(a.type)) ?? 'unknown',
		})),
		supports: list(model.supports).map(s => ({ id: String(s.id), at: point(s.at), fixity: String(s.fixity ?? 'fixed') })),
		blocks: list(model.blocks).flatMap(b => {
			const outline = list(b.outline).map(point);
			const normal = polygonNormal(outline);
			const thickness = Number(b.thickness) || 0;
			return normal ? [{ id: String(b.id), outline, extrusion: [normal[0] * thickness, normal[1] * thickness, normal[2] * thickness] as ModelPoint, supported: b.supported === true }] : [];
		}),
	};
}
