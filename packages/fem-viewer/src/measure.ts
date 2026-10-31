/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { disposeObject } from './geometry.js';
import { LabelLayer } from './labels.js';
import { roundPointMaterial } from './theme.js';

/** What a click measures: a distance (two points), an angle (three, the vertex second) or an area (a polygon). */
export type FemMeasureMode = 'off' | 'distance' | 'angle' | 'area';

/** A point in model space (x, y, z; Z up), snapped to a node or lying on a member or face. */
export type FemMeasurePoint = readonly [number, number, number];

/**
 * A measurement taken in the view. Lengths in model units (metres for SAEngine models); in a
 * developed elevation, x is the distance along the path.
 */
export interface FemMeasurement {
	readonly mode: Exclude<FemMeasureMode, 'off'>;
	readonly points: readonly FemMeasurePoint[];
	/** All the points it needs have been picked (an area: closed on its first point). */
	readonly complete: boolean;
	/** Distance: the straight length and its components along x, y and z. */
	readonly length?: number;
	readonly dx?: number;
	readonly dy?: number;
	readonly dz?: number;
	/** Angle at the second point, in degrees (0 to 180). */
	readonly angle?: number;
	/** Area: of the polygon (its plane's), and its perimeter (closed). */
	readonly area?: number;
	readonly perimeter?: number;
}

/** Model space to world space (Z up to Y up), and back. */
const toWorld = (p: FemMeasurePoint) => new THREE.Vector3(p[0], p[2], -p[1]);
export const fromWorld = (v: THREE.Vector3): FemMeasurePoint => [v.x, -v.z, v.y];

const sub = (a: FemMeasurePoint, b: FemMeasurePoint): [number, number, number] => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const norm = (v: readonly number[]) => Math.hypot(v[0], v[1], v[2]);

/** The measurement of `points` in `mode` (`complete`: the area is closed). */
export function measure(mode: Exclude<FemMeasureMode, 'off'>, points: readonly FemMeasurePoint[], complete: boolean): FemMeasurement {
	if (mode === 'distance') {
		if (points.length < 2) {
			return { mode, points, complete: false };
		}
		const [dx, dy, dz] = sub(points[1], points[0]);
		return { mode, points, complete: true, length: Math.hypot(dx, dy, dz), dx, dy, dz };
	}
	if (mode === 'angle') {
		if (points.length < 3) {
			return { mode, points, complete: false };
		}
		const u = sub(points[0], points[1]);
		const v = sub(points[2], points[1]);
		const lu = norm(u);
		const lv = norm(v);
		const cos = lu > 0 && lv > 0 ? (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (lu * lv) : 1;
		return { mode, points, complete: true, angle: Math.acos(Math.min(1, Math.max(-1, cos))) * 180 / Math.PI };
	}
	// Area: half the length of the sum of the edges' cross products (Newell), the polygon's own
	// plane whatever its orientation; the perimeter is closed back to the first point.
	let ax = 0;
	let ay = 0;
	let az = 0;
	let perimeter = 0;
	for (let k = 0; k < points.length; k++) {
		const a = points[k];
		const b = points[(k + 1) % points.length];
		ax += (a[1] - b[1]) * (a[2] + b[2]);
		ay += (a[2] - b[2]) * (a[0] + b[0]);
		az += (a[0] - b[0]) * (a[1] + b[1]);
		if (points.length > 1 && (k + 1 < points.length || points.length > 2)) {
			perimeter += norm(sub(b, a));
		}
	}
	return { mode, points, complete, area: points.length >= 3 ? Math.hypot(ax, ay, az) / 2 : 0, perimeter };
}

/** The drawing of a measurement: its points, its lines and its value, on top of the model. */
export class MeasureOverlay {

	readonly group = new THREE.Group();
	private readonly labels: LabelLayer;
	private readonly shapes = new THREE.Group();

	constructor(private readonly color: string, background: string) {
		this.labels = new LabelLayer(background);
		this.group.add(this.shapes);
		this.group.add(this.labels.group);
		this.group.renderOrder = 20;
	}

	draw(measurement: FemMeasurement | undefined, text: string | undefined): void {
		this.clear();
		if (!measurement || !measurement.points.length) {
			return;
		}
		const points = measurement.points.map(toWorld);
		const dots = new THREE.Points(new THREE.BufferGeometry().setFromPoints(points), roundPointMaterial(this.color, 9, { depthTest: false }));
		dots.renderOrder = 21;
		this.shapes.add(dots);
		if (points.length >= 2) {
			const closed = measurement.mode === 'area' && points.length >= 3;
			const line = closed ? new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points)) : new THREE.Line(new THREE.BufferGeometry().setFromPoints(points));
			line.material = new THREE.LineBasicMaterial({ color: this.color, depthTest: false, transparent: true });
			line.renderOrder = 21;
			this.shapes.add(line);
		}
		if (text) {
			const at = measurement.mode === 'angle' && points.length >= 2 ? points[1].clone()
				: points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).multiplyScalar(1 / points.length);
			this.labels.add(text, at, this.color, 0.05);
			this.labels.build();
		}
	}

	setLabelScale(factor: number): void {
		this.labels.setScale(factor);
	}

	dispose(): void {
		this.clear();
	}

	private clear(): void {
		this.labels.reset();
		for (const child of [...this.shapes.children]) {
			this.shapes.remove(child);
			disposeObject(child);
		}
	}
}
