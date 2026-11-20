/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/** Axis of a single section plane or section box bound. */
export type SectionAxis = 'x' | 'y' | 'z';

/** One of the six draggable faces of a section box. */
export type SectionFace = 'minX' | 'maxX' | 'minY' | 'maxY' | 'minZ' | 'maxZ';

/** Axis-aligned bounds of a section box (either in scene coordinates or project mm). */
export interface SectionBoxBounds {
	readonly minX: number;
	readonly maxX: number;
	readonly minY: number;
	readonly maxY: number;
	readonly minZ: number;
	readonly maxZ: number;
}

/** A user-defined single section plane (stored in project coordinates: mm, Z up). */
export interface SectionPlaneSpec {
	readonly id: string;
	readonly normal: readonly [number, number, number];
	readonly point: readonly [number, number, number];
	readonly axis?: SectionAxis | 'face';
	readonly flipped?: boolean;
}

/** Persistent section state for a 3D view (in project coordinates: mm, Z up). */
export interface SectionState {
	readonly boxEnabled: boolean;
	readonly box?: SectionBoxBounds;
	readonly planes: readonly SectionPlaneSpec[];
}

/** Half-space equation matching Three.js `Plane` (`dot(normal, p) + constant >= 0` is kept). */
export interface ClipPlaneEquation {
	readonly normal: readonly [number, number, number];
	readonly constant: number;
}

export const SECTION_FACES: readonly SectionFace[] = ['minX', 'maxX', 'minY', 'maxY', 'minZ', 'maxZ'];

const MIN_VALUE = 1e-9;

function finite(n: number, fallback: number): number {
	return Number.isFinite(n) ? n : fallback;
}

function normalize3(v: readonly [number, number, number]): [number, number, number] {
	const len = Math.hypot(v[0], v[1], v[2]);
	return len > MIN_VALUE ? [v[0] / len, v[1] / len, v[2] / len] : [0, 1, 0];
}

/** Ensures finite bounds and `max >= min + minSpan` on every axis. */
export function clampBoxBounds(box: SectionBoxBounds, minSpan = 0.01): SectionBoxBounds {
	const span = Math.max(MIN_VALUE, minSpan);
	let minX = finite(box.minX, -1);
	let maxX = finite(box.maxX, 1);
	let minY = finite(box.minY, -1);
	let maxY = finite(box.maxY, 1);
	let minZ = finite(box.minZ, -1);
	let maxZ = finite(box.maxZ, 1);
	if (maxX < minX + span) {
		const mid = (minX + maxX) / 2;
		minX = mid - span / 2;
		maxX = mid + span / 2;
	}
	if (maxY < minY + span) {
		const mid = (minY + maxY) / 2;
		minY = mid - span / 2;
		maxY = mid + span / 2;
	}
	if (maxZ < minZ + span) {
		const mid = (minZ + maxZ) / 2;
		minZ = mid - span / 2;
		maxZ = mid + span / 2;
	}
	return { minX, maxX, minY, maxY, minZ, maxZ };
}

/** Expands all six faces of `box` symmetrically by `padding` (>= 0). */
export function padBox(box: SectionBoxBounds, padding: number): SectionBoxBounds {
	const p = Math.max(0, finite(padding, 0));
	return clampBoxBounds({
		minX: box.minX - p,
		maxX: box.maxX + p,
		minY: box.minY - p,
		maxY: box.maxY + p,
		minZ: box.minZ - p,
		maxZ: box.maxZ + p,
	});
}

/** Moves one face of `box` to `value`, preventing inversion past the opposite face (`minSpan`). */
export function moveFace(box: SectionBoxBounds, face: SectionFace, value: number, minSpan = 0.01): SectionBoxBounds {
	const v = finite(value, box[face]);
	const span = Math.max(MIN_VALUE, minSpan);
	switch (face) {
		case 'minX': return { ...box, minX: Math.min(v, box.maxX - span) };
		case 'maxX': return { ...box, maxX: Math.max(v, box.minX + span) };
		case 'minY': return { ...box, minY: Math.min(v, box.maxY - span) };
		case 'maxY': return { ...box, maxY: Math.max(v, box.minY + span) };
		case 'minZ': return { ...box, minZ: Math.min(v, box.maxZ - span) };
		case 'maxZ': return { ...box, maxZ: Math.max(v, box.minZ + span) };
	}
}

/**
 * Six inward-pointing clipping planes enclosing `box`: points inside satisfy
 * `dot(normal, p) + constant >= 0` for all six planes.
 */
export function boxToClipPlanes(box: SectionBoxBounds): ClipPlaneEquation[] {
	return [
		{ normal: [1, 0, 0], constant: -box.minX },
		{ normal: [-1, 0, 0], constant: box.maxX },
		{ normal: [0, 1, 0], constant: -box.minY },
		{ normal: [0, -1, 0], constant: box.maxY },
		{ normal: [0, 0, 1], constant: -box.minZ },
		{ normal: [0, 0, -1], constant: box.maxZ },
	];
}

/** Converts a single section plane spec into a clipping equation. */
export function planeSpecToEquation(spec: SectionPlaneSpec): ClipPlaneEquation {
	const normal = normalize3(spec.normal);
	const constant = -(normal[0] * spec.point[0] + normal[1] * spec.point[1] + normal[2] * spec.point[2]);
	return { normal, constant };
}

/** Reverses the kept half-space of `spec`. */
export function flipPlaneSpec(spec: SectionPlaneSpec): SectionPlaneSpec {
	return {
		...spec,
		normal: [-spec.normal[0], -spec.normal[1], -spec.normal[2]],
		flipped: !spec.flipped,
	};
}

/** Whether `point` is not clipped by any plane in `planes` (within `eps`). */
export function isPointInClipPlanes(point: readonly [number, number, number], planes: readonly ClipPlaneEquation[], eps = 1e-6): boolean {
	for (const plane of planes) {
		const d = plane.normal[0] * point[0] + plane.normal[1] * point[1] + plane.normal[2] * point[2] + plane.constant;
		if (d < -eps) {
			return false;
		}
	}
	return true;
}

/** Center of a face on `box`. */
export function faceCenter(box: SectionBoxBounds, face: SectionFace): [number, number, number] {
	const cx = (box.minX + box.maxX) / 2;
	const cy = (box.minY + box.maxY) / 2;
	const cz = (box.minZ + box.maxZ) / 2;
	switch (face) {
		case 'minX': return [box.minX, cy, cz];
		case 'maxX': return [box.maxX, cy, cz];
		case 'minY': return [cx, box.minY, cz];
		case 'maxY': return [cx, box.maxY, cz];
		case 'minZ': return [cx, cy, box.minZ];
		case 'maxZ': return [cx, cy, box.maxZ];
	}
}

/** Outward unit normal of `face`. */
export function faceNormal(face: SectionFace): [number, number, number] {
	switch (face) {
		case 'minX': return [-1, 0, 0];
		case 'maxX': return [1, 0, 0];
		case 'minY': return [0, -1, 0];
		case 'maxY': return [0, 1, 0];
		case 'minZ': return [0, 0, -1];
		case 'maxZ': return [0, 0, 1];
	}
}

/**
 * Closest parameter `t` along line `axisOrigin + t * axisDir` to pointer ray
 * `rayOrigin + s * rayDir`. Returns `undefined` when the ray and axis are nearly parallel.
 */
export function dragAxisParameter(
	rayOrigin: readonly [number, number, number],
	rayDir: readonly [number, number, number],
	axisOrigin: readonly [number, number, number],
	axisDir: readonly [number, number, number],
): number | undefined {
	const uLen = Math.hypot(axisDir[0], axisDir[1], axisDir[2]);
	const vLen = Math.hypot(rayDir[0], rayDir[1], rayDir[2]);
	if (uLen < MIN_VALUE || vLen < MIN_VALUE) {
		return undefined;
	}
	const u: [number, number, number] = [axisDir[0] / uLen, axisDir[1] / uLen, axisDir[2] / uLen];
	const v: [number, number, number] = [rayDir[0] / vLen, rayDir[1] / vLen, rayDir[2] / vLen];
	const w0: [number, number, number] = [
		axisOrigin[0] - rayOrigin[0],
		axisOrigin[1] - rayOrigin[1],
		axisOrigin[2] - rayOrigin[2],
	];
	const b = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
	const denom = 1 - b * b;
	if (denom < 1e-6) {
		return undefined;
	}
	const c = w0[0] * u[0] + w0[1] * u[1] + w0[2] * u[2];
	const d = w0[0] * v[0] + w0[1] * v[1] + w0[2] * v[2];
	return (b * d - c) / denom;
}

/** Converts project point `(x, y, z)` [mm, Z up] to Three.js scene coordinates [m, Y up]. */
export function projectPointToScene(
	point: readonly [number, number, number],
	scale = 0.001,
	offset: readonly [number, number, number] = [0, 0, 0],
): [number, number, number] {
	return [
		point[0] * scale + offset[0],
		point[2] * scale + offset[1],
		-point[1] * scale + offset[2],
	];
}

/** Converts Three.js scene coordinates [m, Y up] back to project coordinates `(x, y, z)` [mm, Z up]. */
export function scenePointToProject(
	point: readonly [number, number, number],
	scale = 0.001,
	offset: readonly [number, number, number] = [0, 0, 0],
): [number, number, number] {
	const s = Math.abs(scale) > MIN_VALUE ? scale : 0.001;
	return [
		(point[0] - offset[0]) / s,
		(offset[2] - point[2]) / s,
		(point[1] - offset[1]) / s,
	];
}

/** Converts a project-space unit normal (Z up) into scene space (Y up). */
export function projectNormalToScene(normal: readonly [number, number, number]): [number, number, number] {
	return normalize3([normal[0], normal[2], -normal[1]]);
}

/** Converts a scene-space unit normal (Y up) into project space (Z up). */
export function sceneNormalToProject(normal: readonly [number, number, number]): [number, number, number] {
	return normalize3([normal[0], -normal[2], normal[1]]);
}

/** Converts project-mm bounds (Z up) to scene bounds (Y up). */
export function projectBoxToScene(
	boxMm: SectionBoxBounds,
	scale = 0.001,
	offset: readonly [number, number, number] = [0, 0, 0],
): SectionBoxBounds {
	return clampBoxBounds({
		minX: boxMm.minX * scale + offset[0],
		maxX: boxMm.maxX * scale + offset[0],
		minY: boxMm.minZ * scale + offset[1],
		maxY: boxMm.maxZ * scale + offset[1],
		minZ: -boxMm.maxY * scale + offset[2],
		maxZ: -boxMm.minY * scale + offset[2],
	});
}

/** Converts scene bounds (Y up) back to project-mm bounds (Z up). */
export function sceneBoxToProject(
	boxScene: SectionBoxBounds,
	scale = 0.001,
	offset: readonly [number, number, number] = [0, 0, 0],
): SectionBoxBounds {
	const s = Math.abs(scale) > MIN_VALUE ? scale : 0.001;
	return clampBoxBounds({
		minX: (boxScene.minX - offset[0]) / s,
		maxX: (boxScene.maxX - offset[0]) / s,
		minY: (offset[2] - boxScene.maxZ) / s,
		maxY: (offset[2] - boxScene.minZ) / s,
		minZ: (boxScene.minY - offset[1]) / s,
		maxZ: (boxScene.maxY - offset[1]) / s,
	}, 1);
}

/** Converts a project-mm section plane spec into scene space. */
export function projectPlaneToScene(
	spec: SectionPlaneSpec,
	scale = 0.001,
	offset: readonly [number, number, number] = [0, 0, 0],
): SectionPlaneSpec {
	return {
		...spec,
		normal: projectNormalToScene(spec.normal),
		point: projectPointToScene(spec.point, scale, offset),
	};
}

/** Converts a scene-space section plane spec into project mm. */
export function scenePlaneToProject(
	spec: SectionPlaneSpec,
	scale = 0.001,
	offset: readonly [number, number, number] = [0, 0, 0],
): SectionPlaneSpec {
	return {
		...spec,
		normal: sceneNormalToProject(spec.normal),
		point: scenePointToProject(spec.point, scale, offset),
	};
}
