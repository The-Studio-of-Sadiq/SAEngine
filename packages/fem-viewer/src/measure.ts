/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { disposeObject } from './geometry.js';
import { LabelLayer } from './labels.js';
import {
	angleBetweenEdges,
	chainMetrics,
	formatMm,
	type MeasureEntry,
	type SnapKind,
	type SnapResult,
	type Vec3,
	type ViewerMeasureMode,
} from './measureMath.js';
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

const NO_CLIP: THREE.Plane[] = [];

const SNAP_COLORS: Readonly<Record<SnapKind, string>> = {
	vertex: '#ffcc00',
	midpoint: '#4fc1ff',
	edge: '#89d185',
	face: '#d4d4d4',
};

/**
 * Multi-entry 3D measurement overlay supporting distance, chain, perpendicular point-to-face,
 * edge-to-edge angle, and live snap preview without being clipped by active section planes.
 */
export class RichMeasureOverlay {

	readonly group = new THREE.Group();
	private readonly labels: LabelLayer;
	private readonly shapes = new THREE.Group();
	private color: string;

	constructor(color: string, background: string) {
		this.color = color;
		this.labels = new LabelLayer(background);
		this.group.add(this.shapes);
		this.group.add(this.labels.group);
		this.group.renderOrder = 20;
	}

	setColor(color: string): void {
		this.color = color;
	}

	drawEntries(
		entries: readonly MeasureEntry[],
		toScene: (p: Vec3) => THREE.Vector3,
		activePoints: readonly Vec3[] = [],
		activeMode: ViewerMeasureMode = 'off',
		previewSnap?: SnapResult,
		activeEdge?: readonly [Vec3, Vec3],
		scaleToMm = 1,
	): void {
		this.clear();

		for (const entry of entries) {
			this.drawEntry(entry, toScene);
		}

		// Active in-progress points & edge
		if (activePoints.length) {
			const scenePts = activePoints.map(toScene);
			this.addDots(scenePts, this.color, 9);
			if (scenePts.length >= 2) {
				this.addLine(scenePts, this.color);
				if (activeMode === 'chain') {
					const { segments, total } = chainMetrics(activePoints);
					segments.forEach((seg, idx) => {
						const mid = scenePts[idx].clone().add(scenePts[idx + 1]).multiplyScalar(0.5);
						this.labels.add(formatMm(seg * scaleToMm), mid, this.color, 0.042);
					});
					this.labels.add(`Σ ${formatMm(total * scaleToMm)}`, scenePts[scenePts.length - 1], this.color, 0.048);
				}
			}
			if (previewSnap && (activeMode === 'distance' || activeMode === 'chain' || activeMode === 'pointToFace')) {
				const last = scenePts[scenePts.length - 1];
				const target = toScene(previewSnap.point);
				this.addDashedLine([last, target], this.color);
				const distMm = Math.hypot(
					previewSnap.point[0] - activePoints[activePoints.length - 1][0],
					previewSnap.point[1] - activePoints[activePoints.length - 1][1],
					previewSnap.point[2] - activePoints[activePoints.length - 1][2],
				) * scaleToMm;
				if (distMm > 0.5) {
					const mid = last.clone().add(target).multiplyScalar(0.5);
					this.labels.add(formatMm(distMm), mid, SNAP_COLORS[previewSnap.kind], 0.042);
				}
			}
		}

		if (activeEdge) {
			this.addLine([toScene(activeEdge[0]), toScene(activeEdge[1])], this.color);
		}

		if (previewSnap) {
			const snapColor = SNAP_COLORS[previewSnap.kind];
			this.addDots([toScene(previewSnap.point)], snapColor, previewSnap.kind === 'face' ? 7 : 11);
			if (previewSnap.edge) {
				this.addLine([toScene(previewSnap.edge[0]), toScene(previewSnap.edge[1])], snapColor, 0.65);
			}
		}

		this.labels.build();
	}

	setLabelScale(factor: number): void {
		this.labels.setScale(factor);
	}

	dispose(): void {
		this.clear();
	}

	private drawEntry(entry: MeasureEntry, toScene: (p: Vec3) => THREE.Vector3): void {
		if (entry.mode === 'pointToFace' && entry.points.length >= 2 && entry.footPoint) {
			const p = toScene(entry.points[0]);
			const foot = toScene(entry.footPoint);
			const facePt = toScene(entry.points[1]);
			this.addDots([p, foot], this.color, 9);
			this.addLine([p, foot], this.color);
			this.addDashedLine([foot, facePt], this.color, 0.5);
			// Right-angle bracket at foot
			const seg = p.clone().sub(foot);
			const len = seg.length();
			const ref = facePt.clone().sub(foot);
			if (len > 1e-4 && ref.length() > 1e-4) {
				const arm = Math.min(0.22, len * 0.25, ref.length() * 0.45);
				const u = seg.normalize().multiplyScalar(arm);
				const v = ref.normalize().multiplyScalar(arm);
				this.addLine([
					foot.clone().add(u),
					foot.clone().add(u).add(v),
					foot.clone().add(v),
				], this.color, 0.85);
			}
			const mid = p.clone().add(foot).multiplyScalar(0.5);
			this.labels.add(entry.label, mid, this.color, 0.048);
			return;
		}

		if (entry.mode === 'edgeAngle' && entry.edgeA && entry.edgeB) {
			const a0 = toScene(entry.edgeA[0]);
			const a1 = toScene(entry.edgeA[1]);
			const b0 = toScene(entry.edgeB[0]);
			const b1 = toScene(entry.edgeB[1]);
			this.addLine([a0, a1], this.color);
			this.addLine([b0, b1], this.color);
			const res = angleBetweenEdges(entry.edgeA, entry.edgeB);
			const vertex = toScene(res.vertex);
			this.addDots([vertex], this.color, 9);
			const arcRadius = Math.max(0.15, Math.min(0.45, a0.distanceTo(a1) * 0.25, b0.distanceTo(b1) * 0.25));
			const da = new THREE.Vector3(res.dirA[0], res.dirA[2], -res.dirA[1]).normalize();
			const db = new THREE.Vector3(res.dirB[0], res.dirB[2], -res.dirB[1]).normalize();
			if (da.lengthSq() > 0 && db.lengthSq() > 0) {
				const pts: THREE.Vector3[] = [];
				const steps = 12;
				for (let i = 0; i <= steps; i++) {
					const t = i / steps;
					const dir = da.clone().lerp(db, t).normalize();
					pts.push(vertex.clone().addScaledVector(dir, arcRadius));
				}
				this.addLine(pts, this.color, 0.85);
			}
			this.labels.add(entry.label, vertex, this.color, 0.048);
			return;
		}

		const scenePts = entry.points.map(toScene);
		if (!scenePts.length) {
			return;
		}
		this.addDots(scenePts, this.color, 9);
		if (scenePts.length >= 2) {
			const closed = entry.mode === 'area' && scenePts.length >= 3;
			this.addLine(scenePts, this.color, 1, closed);
		}
		if (entry.mode === 'chain' && entry.segmentsMm && entry.segmentsMm.length > 1) {
			for (let i = 0; i < entry.segmentsMm.length; i++) {
				const mid = scenePts[i].clone().add(scenePts[i + 1]).multiplyScalar(0.5);
				this.labels.add(formatMm(entry.segmentsMm[i]), mid, this.color, 0.042);
			}
			this.labels.add(entry.label, scenePts[scenePts.length - 1], this.color, 0.048);
		} else if (entry.label) {
			const at = entry.mode === 'angle' && scenePts.length >= 2
				? scenePts[1]
				: scenePts.reduce((sum, p) => sum.add(p), new THREE.Vector3()).multiplyScalar(1 / scenePts.length);
			this.labels.add(entry.label, at, this.color, 0.048);
		}
	}

	private addDots(points: readonly THREE.Vector3[], color: string, size: number): void {
		const mat = roundPointMaterial(color, size, { depthTest: false });
		mat.clippingPlanes = NO_CLIP;
		const dots = new THREE.Points(new THREE.BufferGeometry().setFromPoints([...points]), mat);
		dots.renderOrder = 22;
		this.shapes.add(dots);
	}

	private addLine(points: readonly THREE.Vector3[], color: string, opacity = 1, closed = false): void {
		const geo = new THREE.BufferGeometry().setFromPoints([...points]);
		const mat = new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity, clippingPlanes: NO_CLIP });
		const line = closed ? new THREE.LineLoop(geo, mat) : new THREE.Line(geo, mat);
		line.renderOrder = 21;
		this.shapes.add(line);
	}

	private addDashedLine(points: readonly THREE.Vector3[], color: string, opacity = 0.85): void {
		const geo = new THREE.BufferGeometry().setFromPoints([...points]);
		const mat = new THREE.LineDashedMaterial({
			color,
			dashSize: 0.12,
			gapSize: 0.08,
			depthTest: false,
			transparent: true,
			opacity,
			clippingPlanes: NO_CLIP,
		});
		const line = new THREE.Line(geo, mat);
		line.computeLineDistances();
		line.renderOrder = 21;
		this.shapes.add(line);
	}

	private clear(): void {
		this.labels.reset();
		for (const child of [...this.shapes.children]) {
			this.shapes.remove(child);
			disposeObject(child);
		}
	}
}
