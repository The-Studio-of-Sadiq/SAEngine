/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	ConstraintDefinition,
	DimensionalConstraint,
	evaluateAllParameters,
	GeomRef,
	GeometricConstraint,
} from './constraintModel.js';

export type SolverPoint2D = [number, number];

export interface SolverLine {
	kind: 'line';
	id: string;
	start: SolverPoint2D;
	end: SolverPoint2D;
	fixed?: boolean;
	fixedStart?: boolean;
	fixedEnd?: boolean;
}

export interface SolverCircle {
	kind: 'circle';
	id: string;
	center: SolverPoint2D;
	radius: number;
	fixed?: boolean;
	fixedCenter?: boolean;
	fixedRadius?: boolean;
}

export interface SolverArc {
	kind: 'arc';
	id: string;
	center: SolverPoint2D;
	radius: number;
	startAngle: number; // in radians
	endAngle: number;   // in radians
	fixed?: boolean;
	fixedCenter?: boolean;
	fixedRadius?: boolean;
}

export interface SolverPolyline {
	kind: 'polyline';
	id: string;
	vertices: SolverPoint2D[];
	bulges?: number[];
	closed?: boolean;
	fixed?: boolean;
	fixedVertices?: boolean[];
}

export interface SolverPoint {
	kind: 'point';
	id: string;
	point: SolverPoint2D;
	fixed?: boolean;
}

export type SolverEntity = SolverLine | SolverCircle | SolverArc | SolverPolyline | SolverPoint;

export interface SolverResult {
	success: boolean;
	entities: SolverEntity[];
	error?: string;
}

// ---------------------------------------------------------------------------
// Linear Algebra Helper for Gaussian Elimination with Partial Pivoting
// Solves M * x = b, where M is m x m
// ---------------------------------------------------------------------------

function solveLinearSystem(A: number[][], b: number[]): number[] | null {
	const n = A.length;
	// Create working copy augmented with b
	const M: number[][] = new Array(n);
	for (let i = 0; i < n; i++) {
		M[i] = new Array(n + 1);
		for (let j = 0; j < n; j++) {
			M[i][j] = A[i][j];
		}
		M[i][n] = b[i];
	}

	// Forward elimination
	for (let i = 0; i < n; i++) {
		// Find pivot
		let maxRow = i;
		let maxVal = Math.abs(M[i][i]);
		for (let k = i + 1; k < n; k++) {
			const val = Math.abs(M[k][i]);
			if (val > maxVal) {
				maxVal = val;
				maxRow = k;
			}
		}

		if (maxRow !== i) {
			const tmp = M[i];
			M[i] = M[maxRow];
			M[maxRow] = tmp;
		}

		const pivot = M[i][i];
		if (Math.abs(pivot) < 1e-12) {
			M[i][i] = pivot >= 0 ? 1e-6 : -1e-6;
		}

		for (let k = i + 1; k < n; k++) {
			const factor = M[k][i] / M[i][i];
			M[k][i] = 0;
			for (let j = i + 1; j <= n; j++) {
				M[k][j] -= factor * M[i][j];
			}
		}
	}

	// Back substitution
	const x = new Array<number>(n).fill(0);
	for (let i = n - 1; i >= 0; i--) {
		let sum = M[i][n];
		for (let j = i + 1; j < n; j++) {
			sum -= M[i][j] * x[j];
		}
		const pivot = M[i][i];
		x[i] = Math.abs(pivot) > 1e-12 ? sum / pivot : 0;
	}

	return x;
}

// ---------------------------------------------------------------------------
// Pure Constraint Solver
// ---------------------------------------------------------------------------

export function solveGeometricConstraints(
	entities: readonly SolverEntity[],
	constraints: readonly ConstraintDefinition[],
	parameters: Record<string, number> = {},
): SolverResult {
	if (constraints.length === 0) {
		return { success: true, entities: entities.map(cloneEntity) };
	}

	// Deep clone entities
	const cloned: SolverEntity[] = entities.map(cloneEntity);
	const entityMap = new Map<string, SolverEntity>();
	for (const e of cloned) {
		entityMap.set(e.id, e);
	}

	// Setup variable mapping
	// Variables can be point coordinates (x, y) or radii (r)
	interface VarBinding {
		type: 'point_x' | 'point_y' | 'radius';
		entityId: string;
		feature: string;
		index?: number;
		get: () => number;
		set: (val: number) => void;
	}

	const vars: VarBinding[] = [];
	const varIndexMap = new Map<string, number>();

	function addPointVar(entityId: string, feature: string, index: number | undefined, isFixed: boolean, getX: () => number, setX: (v: number) => void, getY: () => number, setY: (v: number) => void) {
		if (isFixed) return;
		const keyX = `${entityId}:${feature}:${index ?? 0}:x`;
		const keyY = `${entityId}:${feature}:${index ?? 0}:y`;
		if (!varIndexMap.has(keyX)) {
			varIndexMap.set(keyX, vars.length);
			vars.push({ type: 'point_x', entityId, feature, index, get: getX, set: setX });
		}
		if (!varIndexMap.has(keyY)) {
			varIndexMap.set(keyY, vars.length);
			vars.push({ type: 'point_y', entityId, feature, index, get: getY, set: setY });
		}
	}

	function addRadiusVar(entityId: string, isFixed: boolean, getR: () => number, setR: (v: number) => void) {
		if (isFixed) return;
		const keyR = `${entityId}:radius:0`;
		if (!varIndexMap.has(keyR)) {
			varIndexMap.set(keyR, vars.length);
			vars.push({ type: 'radius', entityId, feature: 'radius', get: getR, set: setR });
		}
	}

	// Collect variable bindings for all entities
	for (const ent of cloned) {
		const isFixed = !!ent.fixed;
		if (ent.kind === 'line') {
			const sFixed = isFixed || !!ent.fixedStart;
			const eFixed = isFixed || !!ent.fixedEnd;
			addPointVar(ent.id, 'start', undefined, sFixed, () => ent.start[0], v => { ent.start[0] = v; }, () => ent.start[1], v => { ent.start[1] = v; });
			addPointVar(ent.id, 'end', undefined, eFixed, () => ent.end[0], v => { ent.end[0] = v; }, () => ent.end[1], v => { ent.end[1] = v; });
		} else if (ent.kind === 'circle') {
			const cFixed = isFixed || !!ent.fixedCenter;
			const rFixed = isFixed || !!ent.fixedRadius;
			addPointVar(ent.id, 'center', undefined, cFixed, () => ent.center[0], v => { ent.center[0] = v; }, () => ent.center[1], v => { ent.center[1] = v; });
			addRadiusVar(ent.id, rFixed, () => ent.radius, v => { ent.radius = Math.max(1e-6, v); });
		} else if (ent.kind === 'arc') {
			const cFixed = isFixed || !!ent.fixedCenter;
			const rFixed = isFixed || !!ent.fixedRadius;
			addPointVar(ent.id, 'center', undefined, cFixed, () => ent.center[0], v => { ent.center[0] = v; }, () => ent.center[1], v => { ent.center[1] = v; });
			addRadiusVar(ent.id, rFixed, () => ent.radius, v => { ent.radius = Math.max(1e-6, v); });
		} else if (ent.kind === 'polyline') {
			for (let i = 0; i < ent.vertices.length; i++) {
				const vFixed = isFixed || !!ent.fixedVertices?.[i];
				addPointVar(ent.id, 'vertex', i, vFixed, () => ent.vertices[i][0], v => { ent.vertices[i][0] = v; }, () => ent.vertices[i][1], v => { ent.vertices[i][1] = v; });
			}
		} else if (ent.kind === 'point') {
			addPointVar(ent.id, 'point', undefined, isFixed, () => ent.point[0], v => { ent.point[0] = v; }, () => ent.point[1], v => { ent.point[1] = v; });
		}
	}

	const nVars = vars.length;

	// Resolve feature to point coordinate and variable indices
	interface ResolvedPoint {
		point: SolverPoint2D;
		varX: number; // -1 if fixed
		varY: number; // -1 if fixed
	}

	function resolvePointRef(ref: GeomRef): ResolvedPoint | undefined {
		const ent = entityMap.get(ref.entityId);
		if (!ent) return undefined;
		if (ent.kind === 'line') {
			if (ref.feature === 'start') {
				const vx = varIndexMap.get(`${ent.id}:start:0:x`) ?? -1;
				const vy = varIndexMap.get(`${ent.id}:start:0:y`) ?? -1;
				return { point: ent.start, varX: vx, varY: vy };
			}
			if (ref.feature === 'end') {
				const vx = varIndexMap.get(`${ent.id}:end:0:x`) ?? -1;
				const vy = varIndexMap.get(`${ent.id}:end:0:y`) ?? -1;
				return { point: ent.end, varX: vx, varY: vy };
			}
			if (ref.feature === 'mid') {
				const mid: SolverPoint2D = [(ent.start[0] + ent.end[0]) / 2, (ent.start[1] + ent.end[1]) / 2];
				return { point: mid, varX: -1, varY: -1 };
			}
		}
		if (ent.kind === 'circle' || ent.kind === 'arc') {
			if (ref.feature === 'center') {
				const vx = varIndexMap.get(`${ent.id}:center:0:x`) ?? -1;
				const vy = varIndexMap.get(`${ent.id}:center:0:y`) ?? -1;
				return { point: ent.center, varX: vx, varY: vy };
			}
		}
		if (ent.kind === 'polyline') {
			const idx = ref.index ?? 0;
			if (idx >= 0 && idx < ent.vertices.length) {
				const vx = varIndexMap.get(`${ent.id}:vertex:${idx}:x`) ?? -1;
				const vy = varIndexMap.get(`${ent.id}:vertex:${idx}:y`) ?? -1;
				return { point: ent.vertices[idx], varX: vx, varY: vy };
			}
		}
		if (ent.kind === 'point') {
			const vx = varIndexMap.get(`${ent.id}:point:0:x`) ?? -1;
			const vy = varIndexMap.get(`${ent.id}:point:0:y`) ?? -1;
			return { point: ent.point, varX: vx, varY: vy };
		}
		return undefined;
	}

	interface ResolvedLine {
		p1: ResolvedPoint;
		p2: ResolvedPoint;
	}

	function resolveLineRef(ref: GeomRef): ResolvedLine | undefined {
		const ent = entityMap.get(ref.entityId);
		if (!ent) return undefined;
		if (ent.kind === 'line') {
			const p1 = resolvePointRef({ entityId: ent.id, feature: 'start' });
			const p2 = resolvePointRef({ entityId: ent.id, feature: 'end' });
			if (p1 && p2) return { p1, p2 };
		}
		if (ent.kind === 'polyline') {
			const idx = ref.index ?? 0;
			const p1 = resolvePointRef({ entityId: ent.id, feature: 'vertex', index: idx });
			const nextIdx = (idx + 1) % ent.vertices.length;
			const p2 = resolvePointRef({ entityId: ent.id, feature: 'vertex', index: nextIdx });
			if (p1 && p2) return { p1, p2 };
		}
		return undefined;
	}

	interface ResolvedCircle {
		center: ResolvedPoint;
		radius: number;
		radiusVar: number;
	}

	function resolveCircleRef(ref: GeomRef): ResolvedCircle | undefined {
		const ent = entityMap.get(ref.entityId);
		if (!ent || (ent.kind !== 'circle' && ent.kind !== 'arc')) return undefined;
		const center = resolvePointRef({ entityId: ent.id, feature: 'center' });
		if (!center) return undefined;
		const rVar = varIndexMap.get(`${ent.id}:radius:0`) ?? -1;
		return { center, radius: ent.radius, radiusVar: rVar };
	}

	// -----------------------------------------------------------------------
	// Iterative Solver Loop (Newton-Raphson with Levenberg-Marquardt damping)
	// -----------------------------------------------------------------------

	const MAX_ITERS = 40;
	const TOLERANCE = 1e-6;
	const DAMPING = 1e-6;

	let lastMaxResidual = 0;

	for (let iter = 0; iter < MAX_ITERS; iter++) {
		const residuals: number[] = [];
		const jacobian: number[][] = [];

		function addEq(r: number, grad: Array<{ idx: number; val: number }>) {
			residuals.push(r);
			const row = new Array<number>(nVars).fill(0);
			for (const g of grad) {
				if (g.idx >= 0 && g.idx < nVars) {
					row[g.idx] += g.val;
				}
			}
			jacobian.push(row);
		}

		// Build equations from constraints
		for (const c of constraints) {
			if (c.type === 'geometric') {
				const geom = c as GeometricConstraint;
				switch (geom.kind) {
					case 'horizontal': {
						const line = resolveLineRef(geom.refs[0]);
						if (line) {
							// y2 - y1 = 0
							const r = line.p2.point[1] - line.p1.point[1];
							addEq(r, [
								{ idx: line.p1.varY, val: -1 },
								{ idx: line.p2.varY, val: 1 },
							]);
						} else if (geom.refs.length >= 2) {
							const pt1 = resolvePointRef(geom.refs[0]);
							const pt2 = resolvePointRef(geom.refs[1]);
							if (pt1 && pt2) {
								const r = pt2.point[1] - pt1.point[1];
								addEq(r, [
									{ idx: pt1.varY, val: -1 },
									{ idx: pt2.varY, val: 1 },
								]);
							}
						}
						break;
					}

					case 'vertical': {
						const line = resolveLineRef(geom.refs[0]);
						if (line) {
							// x2 - x1 = 0
							const r = line.p2.point[0] - line.p1.point[0];
							addEq(r, [
								{ idx: line.p1.varX, val: -1 },
								{ idx: line.p2.varX, val: 1 },
							]);
						} else if (geom.refs.length >= 2) {
							const pt1 = resolvePointRef(geom.refs[0]);
							const pt2 = resolvePointRef(geom.refs[1]);
							if (pt1 && pt2) {
								const r = pt2.point[0] - pt1.point[0];
								addEq(r, [
									{ idx: pt1.varX, val: -1 },
									{ idx: pt2.varX, val: 1 },
								]);
							}
						}
						break;
					}

					case 'coincident': {
						const pt1 = resolvePointRef(geom.refs[0]);
						const pt2 = resolvePointRef(geom.refs[1]);
						if (pt1 && pt2) {
							addEq(pt1.point[0] - pt2.point[0], [
								{ idx: pt1.varX, val: 1 },
								{ idx: pt2.varX, val: -1 },
							]);
							addEq(pt1.point[1] - pt2.point[1], [
								{ idx: pt1.varY, val: 1 },
								{ idx: pt2.varY, val: -1 },
							]);
						}
						break;
					}

					case 'parallel': {
						const l1 = resolveLineRef(geom.refs[0]);
						const l2 = resolveLineRef(geom.refs[1]);
						if (l1 && l2) {
							const dx1 = l1.p2.point[0] - l1.p1.point[0];
							const dy1 = l1.p2.point[1] - l1.p1.point[1];
							const dx2 = l2.p2.point[0] - l2.p1.point[0];
							const dy2 = l2.p2.point[1] - l2.p1.point[1];
							const r = dx1 * dy2 - dy1 * dx2;
							addEq(r, [
								{ idx: l1.p1.varX, val: -dy2 },
								{ idx: l1.p2.varX, val: dy2 },
								{ idx: l1.p1.varY, val: dx2 },
								{ idx: l1.p2.varY, val: -dx2 },
								{ idx: l2.p1.varX, val: dy1 },
								{ idx: l2.p2.varX, val: -dy1 },
								{ idx: l2.p1.varY, val: -dx1 },
								{ idx: l2.p2.varY, val: dx1 },
							]);
						}
						break;
					}

					case 'perpendicular': {
						const l1 = resolveLineRef(geom.refs[0]);
						const l2 = resolveLineRef(geom.refs[1]);
						if (l1 && l2) {
							const dx1 = l1.p2.point[0] - l1.p1.point[0];
							const dy1 = l1.p2.point[1] - l1.p1.point[1];
							const dx2 = l2.p2.point[0] - l2.p1.point[0];
							const dy2 = l2.p2.point[1] - l2.p1.point[1];
							const r = dx1 * dx2 + dy1 * dy2;
							addEq(r, [
								{ idx: l1.p1.varX, val: -dx2 },
								{ idx: l1.p2.varX, val: dx2 },
								{ idx: l1.p1.varY, val: -dy2 },
								{ idx: l1.p2.varY, val: dy2 },
								{ idx: l2.p1.varX, val: -dx1 },
								{ idx: l2.p2.varX, val: dx1 },
								{ idx: l2.p1.varY, val: -dy1 },
								{ idx: l2.p2.varY, val: dy1 },
							]);
						}
						break;
					}

					case 'collinear': {
						const l1 = resolveLineRef(geom.refs[0]);
						const l2 = resolveLineRef(geom.refs[1]);
						if (l1 && l2) {
							const dx1 = l1.p2.point[0] - l1.p1.point[0];
							const dy1 = l1.p2.point[1] - l1.p1.point[1];
							const dx2 = l2.p2.point[0] - l2.p1.point[0];
							const dy2 = l2.p2.point[1] - l2.p1.point[1];
							// Parallel
							addEq(dx1 * dy2 - dy1 * dx2, [
								{ idx: l1.p1.varX, val: -dy2 },
								{ idx: l1.p2.varX, val: dy2 },
								{ idx: l1.p1.varY, val: dx2 },
								{ idx: l1.p2.varY, val: -dx2 },
								{ idx: l2.p1.varX, val: dy1 },
								{ idx: l2.p2.varX, val: -dy1 },
								{ idx: l2.p1.varY, val: -dx1 },
								{ idx: l2.p2.varY, val: dx1 },
							]);
							// l2.p1 on line 1
							const dx3 = l2.p1.point[0] - l1.p1.point[0];
							const dy3 = l2.p1.point[1] - l1.p1.point[1];
							addEq(dx1 * dy3 - dy1 * dx3, [
								{ idx: l1.p1.varX, val: -dy3 + dy1 },
								{ idx: l1.p2.varX, val: dy3 },
								{ idx: l1.p1.varY, val: dx3 - dx1 },
								{ idx: l1.p2.varY, val: -dx3 },
								{ idx: l2.p1.varX, val: -dy1 },
								{ idx: l2.p1.varY, val: dx1 },
							]);
						}
						break;
					}

					case 'concentric': {
						const c1 = resolveCircleRef(geom.refs[0]);
						const c2 = resolveCircleRef(geom.refs[1]);
						if (c1 && c2) {
							addEq(c1.center.point[0] - c2.center.point[0], [
								{ idx: c1.center.varX, val: 1 },
								{ idx: c2.center.varX, val: -1 },
							]);
							addEq(c1.center.point[1] - c2.center.point[1], [
								{ idx: c1.center.varY, val: 1 },
								{ idx: c2.center.varY, val: -1 },
							]);
						}
						break;
					}

					case 'tangent': {
						// Line and circle
						let line = resolveLineRef(geom.refs[0]);
						let circle = resolveCircleRef(geom.refs[1]);
						if (!line || !circle) {
							line = resolveLineRef(geom.refs[1]);
							circle = resolveCircleRef(geom.refs[0]);
						}
						if (line && circle) {
							const dx = line.p2.point[0] - line.p1.point[0];
							const dy = line.p2.point[1] - line.p1.point[1];
							const L = Math.hypot(dx, dy);
							if (L > 1e-9) {
								const num = dx * (circle.center.point[1] - line.p1.point[1]) - dy * (circle.center.point[0] - line.p1.point[0]);
								const sign = num >= 0 ? 1 : -1;
								const dist = Math.abs(num) / L;
								const r = dist - circle.radius;
								// Normalized distance derivative
								const dnum_dx1 = line.p2.point[1] - circle.center.point[1];
								const dnum_dy1 = circle.center.point[0] - line.p2.point[0];
								const dnum_dx2 = circle.center.point[1] - line.p1.point[1];
								const dnum_dy2 = line.p1.point[0] - circle.center.point[0];
								const dnum_dxc = -dy;
								const dnum_dyc = dx;

								addEq(r, [
									{ idx: line.p1.varX, val: sign * dnum_dx1 / L },
									{ idx: line.p1.varY, val: sign * dnum_dy1 / L },
									{ idx: line.p2.varX, val: sign * dnum_dx2 / L },
									{ idx: line.p2.varY, val: sign * dnum_dy2 / L },
									{ idx: circle.center.varX, val: sign * dnum_dxc / L },
									{ idx: circle.center.varY, val: sign * dnum_dyc / L },
									{ idx: circle.radiusVar, val: -1 },
								]);
							}
						}
						break;
					}

					case 'equal': {
						const l1 = resolveLineRef(geom.refs[0]);
						const l2 = resolveLineRef(geom.refs[1]);
						if (l1 && l2) {
							const dx1 = l1.p2.point[0] - l1.p1.point[0];
							const dy1 = l1.p2.point[1] - l1.p1.point[1];
							const len1 = Math.hypot(dx1, dy1);
							const dx2 = l2.p2.point[0] - l2.p1.point[0];
							const dy2 = l2.p2.point[1] - l2.p1.point[1];
							const len2 = Math.hypot(dx2, dy2);
							const r = len1 - len2;
							const u1x = len1 > 1e-9 ? dx1 / len1 : 0;
							const u1y = len1 > 1e-9 ? dy1 / len1 : 0;
							const u2x = len2 > 1e-9 ? dx2 / len2 : 0;
							const u2y = len2 > 1e-9 ? dy2 / len2 : 0;
							addEq(r, [
								{ idx: l1.p1.varX, val: -u1x },
								{ idx: l1.p1.varY, val: -u1y },
								{ idx: l1.p2.varX, val: u1x },
								{ idx: l1.p2.varY, val: u1y },
								{ idx: l2.p1.varX, val: u2x },
								{ idx: l2.p1.varY, val: u2y },
								{ idx: l2.p2.varX, val: -u2x },
								{ idx: l2.p2.varY, val: -u2y },
							]);
						} else {
							const c1 = resolveCircleRef(geom.refs[0]);
							const c2 = resolveCircleRef(geom.refs[1]);
							if (c1 && c2) {
								addEq(c1.radius - c2.radius, [
									{ idx: c1.radiusVar, val: 1 },
									{ idx: c2.radiusVar, val: -1 },
								]);
							}
						}
						break;
					}

					case 'fix': {
						const pt = resolvePointRef(geom.refs[0]);
						if (pt) {
							// If point is already fixed in variable selection, nothing needed.
							// If it has variables, pin to current initial value:
							// (Handled by solver entity flags)
						}
						break;
					}
				}
			} else if (c.type === 'dimensional') {
				const dim = c as DimensionalConstraint;
				const targetVal = dim.name in parameters ? parameters[dim.name] : dim.value;
				switch (dim.kind) {
					case 'aligned':
					case 'linear': {
						let pt1 = resolvePointRef(dim.refs[0]);
						let pt2 = dim.refs.length >= 2 ? resolvePointRef(dim.refs[1]) : undefined;
						if (!pt2) {
							const line = resolveLineRef(dim.refs[0]);
							if (line) {
								pt1 = line.p1;
								pt2 = line.p2;
							}
						}
						if (pt1 && pt2) {
							const dx = pt2.point[0] - pt1.point[0];
							const dy = pt2.point[1] - pt1.point[1];
							const dist = Math.hypot(dx, dy);
							const r = dist - targetVal;
							const ux = dist > 1e-9 ? dx / dist : 1;
							const uy = dist > 1e-9 ? dy / dist : 0;
							addEq(r, [
								{ idx: pt1.varX, val: -ux },
								{ idx: pt1.varY, val: -uy },
								{ idx: pt2.varX, val: ux },
								{ idx: pt2.varY, val: uy },
							]);
						}
						break;
					}

					case 'horizontal': {
						let pt1 = resolvePointRef(dim.refs[0]);
						let pt2 = dim.refs.length >= 2 ? resolvePointRef(dim.refs[1]) : undefined;
						if (!pt2) {
							const line = resolveLineRef(dim.refs[0]);
							if (line) { pt1 = line.p1; pt2 = line.p2; }
						}
						if (pt1 && pt2) {
							const dx = pt2.point[0] - pt1.point[0];
							const sign = dx >= 0 ? 1 : -1;
							const r = Math.abs(dx) - targetVal;
							addEq(r, [
								{ idx: pt1.varX, val: -sign },
								{ idx: pt2.varX, val: sign },
							]);
						}
						break;
					}

					case 'vertical': {
						let pt1 = resolvePointRef(dim.refs[0]);
						let pt2 = dim.refs.length >= 2 ? resolvePointRef(dim.refs[1]) : undefined;
						if (!pt2) {
							const line = resolveLineRef(dim.refs[0]);
							if (line) { pt1 = line.p1; pt2 = line.p2; }
						}
						if (pt1 && pt2) {
							const dy = pt2.point[1] - pt1.point[1];
							const sign = dy >= 0 ? 1 : -1;
							const r = Math.abs(dy) - targetVal;
							addEq(r, [
								{ idx: pt1.varY, val: -sign },
								{ idx: pt2.varY, val: sign },
							]);
						}
						break;
					}

					case 'radial': {
						const circle = resolveCircleRef(dim.refs[0]);
						if (circle) {
							addEq(circle.radius - targetVal, [
								{ idx: circle.radiusVar, val: 1 },
							]);
						}
						break;
					}

					case 'diameter': {
						const circle = resolveCircleRef(dim.refs[0]);
						if (circle) {
							addEq(2 * circle.radius - targetVal, [
								{ idx: circle.radiusVar, val: 2 },
							]);
						}
						break;
					}

					case 'angular': {
						const l1 = resolveLineRef(dim.refs[0]);
						const l2 = resolveLineRef(dim.refs[1]);
						if (l1 && l2) {
							const dx1 = l1.p2.point[0] - l1.p1.point[0];
							const dy1 = l1.p2.point[1] - l1.p1.point[1];
							const len1 = Math.hypot(dx1, dy1);
							const dx2 = l2.p2.point[0] - l2.p1.point[0];
							const dy2 = l2.p2.point[1] - l2.p1.point[1];
							const len2 = Math.hypot(dx2, dy2);
							if (len1 > 1e-9 && len2 > 1e-9) {
								const dot = dx1 * dx2 + dy1 * dy2;
								const cosTarget = Math.cos(targetVal * Math.PI / 180);
								const r = (dot / (len1 * len2)) - cosTarget;
								const invLen12 = 1 / (len1 * len2);
								addEq(r, [
									{ idx: l1.p1.varX, val: -dx2 * invLen12 },
									{ idx: l1.p1.varY, val: -dy2 * invLen12 },
									{ idx: l1.p2.varX, val: dx2 * invLen12 },
									{ idx: l1.p2.varY, val: dy2 * invLen12 },
									{ idx: l2.p1.varX, val: -dx1 * invLen12 },
									{ idx: l2.p1.varY, val: -dy1 * invLen12 },
									{ idx: l2.p2.varX, val: dx1 * invLen12 },
									{ idx: l2.p2.varY, val: dy1 * invLen12 },
								]);
							}
						}
						break;
					}
				}
			}
		}

		const mEqs = residuals.length;
		if (mEqs === 0 || nVars === 0) {
			break;
		}

		// Calculate max residual norm
		let maxR = 0;
		for (const r of residuals) {
			const absR = Math.abs(r);
			if (absR > maxR) maxR = absR;
		}
		lastMaxResidual = maxR;
		if (maxR < TOLERANCE) {
			// Converged!
			break;
		}

		// Compute M = J * J^T + lambda * I (mEqs x mEqs)
		const M: number[][] = new Array(mEqs);
		for (let i = 0; i < mEqs; i++) {
			M[i] = new Array(mEqs).fill(0);
			const rowI = jacobian[i];
			for (let j = 0; j <= i; j++) {
				const rowJ = jacobian[j];
				let sum = 0;
				for (let k = 0; k < nVars; k++) {
					sum += rowI[k] * rowJ[k];
				}
				M[i][j] = sum;
				M[j][i] = sum;
			}
			M[i][i] += DAMPING;
		}

		// Target vector: -residuals
		const b = residuals.map(r => -r);

		// Solve M * y = b
		const y = solveLinearSystem(M, b);
		if (!y) {
			return { success: false, entities: cloned, error: 'would over-constrain the geometry' };
		}

		// deltaX = J^T * y
		const deltaX = new Array<number>(nVars).fill(0);
		for (let k = 0; k < nVars; k++) {
			let sum = 0;
			for (let i = 0; i < mEqs; i++) {
				sum += jacobian[i][k] * y[i];
			}
			deltaX[k] = sum;
		}

		// Update variable bindings
		for (let k = 0; k < nVars; k++) {
			vars[k].set(vars[k].get() + deltaX[k]);
		}
	}

	if (lastMaxResidual > 1e-3) {
		return {
			success: false,
			entities: cloned,
			error: 'would over-constrain the geometry',
		};
	}

	return {
		success: true,
		entities: cloned,
	};
}

function cloneEntity(e: SolverEntity): SolverEntity {
	if (e.kind === 'line') {
		return {
			kind: 'line',
			id: e.id,
			start: [e.start[0], e.start[1]],
			end: [e.end[0], e.end[1]],
			fixed: e.fixed,
			fixedStart: e.fixedStart,
			fixedEnd: e.fixedEnd,
		};
	}
	if (e.kind === 'circle') {
		return {
			kind: 'circle',
			id: e.id,
			center: [e.center[0], e.center[1]],
			radius: e.radius,
			fixed: e.fixed,
			fixedCenter: e.fixedCenter,
			fixedRadius: e.fixedRadius,
		};
	}
	if (e.kind === 'arc') {
		return {
			kind: 'arc',
			id: e.id,
			center: [e.center[0], e.center[1]],
			radius: e.radius,
			startAngle: e.startAngle,
			endAngle: e.endAngle,
			fixed: e.fixed,
			fixedCenter: e.fixedCenter,
			fixedRadius: e.fixedRadius,
		};
	}
	if (e.kind === 'polyline') {
		return {
			kind: 'polyline',
			id: e.id,
			vertices: e.vertices.map(v => [v[0], v[1]]),
			bulges: e.bulges ? [...e.bulges] : undefined,
			closed: e.closed,
			fixed: e.fixed,
			fixedVertices: e.fixedVertices ? [...e.fixedVertices] : undefined,
		};
	}
	if (e.kind === 'point') {
		return {
			kind: 'point',
			id: e.id,
			point: [e.point[0], e.point[1]],
			fixed: e.fixed,
		};
	}
	return e;
}
