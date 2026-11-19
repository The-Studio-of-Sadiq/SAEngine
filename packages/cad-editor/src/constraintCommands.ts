/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbAlignedDimension,
	AcDbArc,
	AcDbCircle,
	AcDbDatabase,
	AcDbEntity,
	AcDbLine,
	AcDbPoint,
	AcDbPolyline,
	AcDbRotatedDimension,
	AcGePoint2d,
	AcGePoint3d,
} from '@mlightcad/data-model';
import {
	CadCommandContext,
	CadPoint3,
	copyProperties,
	registerCommand,
} from './commands.js';
import { polylineVertices } from './entityAccess.js';
import { ensureLayer } from './layerCommands.js';
import {
	ConstraintDefinition,
	ConstraintStore,
	createEmptyConstraintStore,
	DimensionalConstraint,
	DimensionalConstraintType,
	evaluateAllParameters,
	GeometricConstraint,
	GeometricConstraintType,
	GeomRef,
	loadConstraintsFromDatabase,
	ParameterDefinition,
	saveConstraintsToDatabase,
} from './constraintModel.js';
import {
	SolverPoint2D,
	solveGeometricConstraints,
	SolverEntity,
} from './constraintSolver.js';

export const DIMCONSTRAINT_LAYER = 'DIMCONSTRAINT';

/**
 * Ensures the DIMCONSTRAINT layer exists with no-plot setting.
 */
export function ensureDimConstraintLayer(db: AcDbDatabase): void {
	ensureLayer(db, DIMCONSTRAINT_LAYER, {
		color: 4, // cyan
		plot: false, // excluded from plotting
		description: 'Parametric Dimensional Constraints',
	});
}

/**
 * Converts an AcDbEntity from the drawing into a SolverEntity.
 */
export function entityToSolverEntity(entity: AcDbEntity, isFixed = false): SolverEntity | undefined {
	const id = String(entity.objectId);
	if (entity instanceof AcDbLine || entity.dxfTypeName === 'LINE') {
		const line = entity as AcDbLine;
		return {
			kind: 'line',
			id,
			start: [line.startPoint.x, line.startPoint.y],
			end: [line.endPoint.x, line.endPoint.y],
			fixed: isFixed,
		};
	}
	if (entity instanceof AcDbCircle || entity.dxfTypeName === 'CIRCLE') {
		const circle = entity as AcDbCircle;
		return {
			kind: 'circle',
			id,
			center: [circle.center.x, circle.center.y],
			radius: circle.radius,
			fixed: isFixed,
		};
	}
	if (entity instanceof AcDbArc || entity.dxfTypeName === 'ARC') {
		const arc = entity as AcDbArc;
		return {
			kind: 'arc',
			id,
			center: [arc.center.x, arc.center.y],
			radius: arc.radius,
			startAngle: arc.startAngle,
			endAngle: arc.endAngle,
			fixed: isFixed,
		};
	}
	if (entity instanceof AcDbPolyline || entity.dxfTypeName === 'LWPOLYLINE') {
		const poly = entity as AcDbPolyline;
		const data = polylineVertices(poly);
		return {
			kind: 'polyline',
			id,
			vertices: data.points,
			bulges: data.bulges,
			closed: data.closed,
			fixed: isFixed,
		};
	}
	if (entity instanceof AcDbPoint || entity.dxfTypeName === 'POINT') {
		const pt = entity as unknown as { position: AcGePoint3d };
		return {
			kind: 'point',
			id,
			point: [pt.position.x, pt.position.y],
			fixed: isFixed,
		};
	}
	return undefined;
}

/**
 * Re-solve constraints stored in the database and update modified entities.
 */
/** Pins what the drawing's Fix constraints name, so a re-solve keeps fixed geometry where it is. */
function applyStoredFixes(se: SolverEntity, id: string, store: ConstraintStore): void {
	for (const c of store.constraints) {
		if (c.type !== 'geometric' || c.kind !== 'fix') {
			continue;
		}
		for (const ref of c.refs) {
			if (ref.entityId !== id) {
				continue;
			}
			const e = se as SolverEntity & { fixed?: boolean; fixedStart?: boolean; fixedEnd?: boolean; fixedCenter?: boolean; fixedVertices?: boolean[] };
			switch (ref.feature) {
				case 'start': e.fixedStart = true; break;
				case 'end': e.fixedEnd = true; break;
				case 'center': e.fixedCenter = true; break;
				case 'vertex': {
					if (ref.index !== undefined) {
						e.fixedVertices = e.fixedVertices ?? [];
						e.fixedVertices[ref.index] = true;
					}
					break;
				}
				default: e.fixed = true;
			}
		}
	}
}

export async function solveAndUpdateDatabase(
	ctx: CadCommandContext,
	store: ConstraintStore,
	options?: { fixedIds?: ReadonlySet<string> },
): Promise<boolean> {
	if (store.constraints.length === 0) {
		saveConstraintsToDatabase(ctx.database.native, store);
		return true;
	}

	// 1. Evaluate all parameters
	const evaluatedParams = evaluateAllParameters(store.parameters);

	// 2. Identify all entities involved in constraints
	const referencedIds = new Set<string>();
	for (const c of store.constraints) {
		for (const ref of c.refs) {
			referencedIds.add(ref.entityId);
		}
	}

	// 3. Collect solver entities
	const solverEntities: SolverEntity[] = [];
	const originalEntities = new Map<string, AcDbEntity>();

	for (const id of referencedIds) {
		const ent = ctx.database.get(id);
		if (!ent) continue;
		originalEntities.set(id, ent);

		// Check if entity should be fixed:
		// - user explicitly fixed it
		// - it belongs to generated layers
		// - it is locked
		const isLocked = !!(ent.layer && ctx.database.native.tables?.layerTable?.getAt(ent.layer)?.isLocked);
		const genLayers = (globalThis as any).__saengineGeneratedLayers as Set<string> | undefined;
		const isGenerated = !!(ent.layer && genLayers?.has(ent.layer));
		const isFixed = isLocked || isGenerated || !!options?.fixedIds?.has(id);

		const se = entityToSolverEntity(ent, isFixed);
		if (se) {
			applyStoredFixes(se, id, store);
			solverEntities.push(se);
		}
	}

	// 4. Solve system
	const res = solveGeometricConstraints(solverEntities, store.constraints, evaluatedParams);
	if (!res.success) {
		ctx.message(res.error || 'would over-constrain the geometry');
		throw new Error(res.error || 'would over-constrain the geometry');
	}

	// 5. Update modified entities in the database inside transaction
	await ctx.transaction(async () => {
		// Edit in place: the constraints refer to the entities by id, which a replace would change.
		const db = ctx.database.native as AcDbDatabase & { openEntityForWrite?(id: string): AcDbEntity | undefined };
		for (const solved of res.entities) {
			const original = originalEntities.get(solved.id);
			if (!original) continue;
			const target = (db.openEntityForWrite?.(solved.id) ?? original) as AcDbEntity;

			if (solved.kind === 'line') {
				const line = target as AcDbLine;
				const z = line.startPoint.z;
				line.startPoint = new AcGePoint3d(solved.start[0], solved.start[1], z);
				line.endPoint = new AcGePoint3d(solved.end[0], solved.end[1], z);
			} else if (solved.kind === 'circle') {
				const circle = target as AcDbCircle;
				circle.center = new AcGePoint3d(solved.center[0], solved.center[1], circle.center.z);
				circle.radius = solved.radius;
			} else if (solved.kind === 'arc') {
				const arc = target as AcDbArc;
				arc.center = new AcGePoint3d(solved.center[0], solved.center[1], arc.center.z);
				arc.radius = solved.radius;
				arc.startAngle = solved.startAngle;
				arc.endAngle = solved.endAngle;
			} else if (solved.kind === 'polyline') {
				const poly = target as AcDbPolyline;
				while (poly.numberOfVertices > 0) {
					poly.removeVertexAt(poly.numberOfVertices - 1);
				}
				solved.vertices.forEach((v, i) => {
					poly.addVertexAt(i, new AcGePoint2d(v[0], v[1]), solved.bulges?.[i] ?? 0);
				});
				poly.closed = !!solved.closed;
			}
		}

		saveConstraintsToDatabase(ctx.database.native, store);
	});

	return true;
}

/**
 * Re-solve constraints after any editing command (MOVE, STRETCH, grip edit, etc.)
 */
export async function reSolveConstraintsAfterEdit(ctx: CadCommandContext): Promise<void> {
	const store = loadConstraintsFromDatabase(ctx.database.native);
	if (store.constraints.length === 0) return;
	await solveAndUpdateDatabase(ctx, store);
}

// ---------------------------------------------------------------------------
// Geometry Pick Helpers
// ---------------------------------------------------------------------------

function pickGeometryFeature(entity: AcDbEntity, pickPt: CadPoint3 | undefined, defaultFeature: GeomRef['feature']): GeomRef {
	const entityId = String(entity.objectId);
	if (!pickPt) {
		return { entityId, feature: defaultFeature };
	}

	if (entity instanceof AcDbLine || entity.dxfTypeName === 'LINE') {
		const line = entity as AcDbLine;
		const dStart = Math.hypot(pickPt.x - line.startPoint.x, pickPt.y - line.startPoint.y);
		const dEnd = Math.hypot(pickPt.x - line.endPoint.x, pickPt.y - line.endPoint.y);
		const midX = (line.startPoint.x + line.endPoint.x) / 2;
		const midY = (line.startPoint.y + line.endPoint.y) / 2;
		const dMid = Math.hypot(pickPt.x - midX, pickPt.y - midY);

		if (defaultFeature === 'whole') {
			return { entityId, feature: 'whole' };
		}
		if (dMid < dStart && dMid < dEnd) {
			return { entityId, feature: 'mid' };
		}
		return { entityId, feature: dStart <= dEnd ? 'start' : 'end' };
	}

	if (entity instanceof AcDbCircle || entity instanceof AcDbArc || entity.dxfTypeName === 'CIRCLE' || entity.dxfTypeName === 'ARC') {
		return { entityId, feature: defaultFeature === 'center' ? 'center' : 'whole' };
	}

	if (entity instanceof AcDbPolyline || entity.dxfTypeName === 'LWPOLYLINE') {
		const poly = entity as AcDbPolyline;
		const { points } = polylineVertices(poly);
		let bestIdx = 0;
		let bestDist = Infinity;
		for (let i = 0; i < points.length; i++) {
			const d = Math.hypot(pickPt.x - points[i][0], pickPt.y - points[i][1]);
			if (d < bestDist) {
				bestDist = d;
				bestIdx = i;
			}
		}
		return { entityId, feature: 'vertex', index: bestIdx };
	}

	return { entityId, feature: defaultFeature };
}

// ---------------------------------------------------------------------------
// Geometric Constraint Command Handlers
// ---------------------------------------------------------------------------

export async function addGeometricConstraint(
	ctx: CadCommandContext,
	kind: GeometricConstraintType,
): Promise<void> {
	const store = loadConstraintsFromDatabase(ctx.database.native);

	if (kind === 'horizontal' || kind === 'vertical') {
		const pick = await ctx.getEntityPick(`Select line for ${kind.toUpperCase()} constraint:`);
		if (pick.status !== 'ok' || !pick.entity) return;
		const ref = pickGeometryFeature(pick.entity, pick.point, 'whole');
		const constraint: GeometricConstraint = {
			id: `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
			type: 'geometric',
			kind,
			refs: [ref],
		};
		store.constraints.push(constraint);
		await solveAndUpdateDatabase(ctx, store);
		ctx.message(`${kind.toUpperCase()} constraint added.`);
		return;
	}

	if (kind === 'fix') {
		const pick = await ctx.getEntityPick('Select point or entity to FIX:');
		if (pick.status !== 'ok' || !pick.entity) return;
		const ref = pickGeometryFeature(pick.entity, pick.point, 'start');
		const constraint: GeometricConstraint = {
			id: `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
			type: 'geometric',
			kind: 'fix',
			refs: [ref],
		};
		store.constraints.push(constraint);
		await solveAndUpdateDatabase(ctx, store, { fixedIds: new Set([ref.entityId]) });
		ctx.message('FIX constraint added.');
		return;
	}

	// Two-entity constraints: coincident, parallel, perpendicular, collinear, concentric, tangent, equal
	const pick1 = await ctx.getEntityPick(`Select first object for ${kind.toUpperCase()} constraint:`);
	if (pick1.status !== 'ok' || !pick1.entity) return;
	const ref1 = pickGeometryFeature(pick1.entity, pick1.point, kind === 'coincident' ? 'start' : (kind === 'concentric' ? 'center' : 'whole'));

	const pick2 = await ctx.getEntityPick(`Select second object for ${kind.toUpperCase()} constraint:`);
	if (pick2.status !== 'ok' || !pick2.entity) return;
	const ref2 = pickGeometryFeature(pick2.entity, pick2.point, kind === 'coincident' ? 'start' : (kind === 'concentric' ? 'center' : 'whole'));

	const constraint: GeometricConstraint = {
		id: `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
		type: 'geometric',
		kind,
		refs: [ref1, ref2],
	};

	store.constraints.push(constraint);
	await solveAndUpdateDatabase(ctx, store);
	ctx.message(`${kind.toUpperCase()} constraint added.`);
}

export async function geomConstraintCommand(ctx: CadCommandContext): Promise<void> {
	const choice = await ctx.getKeyword(
		'Enter constraint type [Coincident/Collinear/Concentric/Equal/Fix/Horizontal/Parallel/Perpendicular/Tangent/Vertical] <Horizontal>:',
		['Coincident', 'Collinear', 'Concentric', 'Equal', 'Fix', 'Horizontal', 'Parallel', 'Perpendicular', 'Tangent', 'Vertical'],
		{ default: 'Horizontal' },
	);
	const kind = choice.toLowerCase() as GeometricConstraintType;
	await addGeometricConstraint(ctx, kind);
}

// ---------------------------------------------------------------------------
// AUTOCONSTRAIN Command
// ---------------------------------------------------------------------------

export async function autoConstrainCommand(ctx: CadCommandContext): Promise<void> {
	let selection: readonly AcDbEntity[] = [];
	try {
		selection = await ctx.getSelection('Select objects for AUTOCONSTRAIN:');
	} catch {
		selection = ctx.database.all();
	}
	if (selection.length === 0) selection = ctx.database.all();

	const store = loadConstraintsFromDatabase(ctx.database.native);
	let appliedCount = 0;

	const lines = selection.filter((e): e is AcDbLine => e instanceof AcDbLine || e.dxfTypeName === 'LINE');
	const circles = selection.filter((e): e is AcDbCircle => e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE');

	const TOL_ANGLE = 0.015; // ~0.85 degrees
	const TOL_DIST = 0.1;

	// 1. Horizontal / Vertical for lines
	for (const l of lines) {
		const dx = l.endPoint.x - l.startPoint.x;
		const dy = l.endPoint.y - l.startPoint.y;
		const len = Math.hypot(dx, dy);
		if (len < 1e-6) continue;

		if (Math.abs(dy) / len < TOL_ANGLE) {
			store.constraints.push({
				id: `ac_${Date.now()}_${appliedCount++}`,
				type: 'geometric',
				kind: 'horizontal',
				refs: [{ entityId: String(l.objectId), feature: 'whole' }],
			});
		} else if (Math.abs(dx) / len < TOL_ANGLE) {
			store.constraints.push({
				id: `ac_${Date.now()}_${appliedCount++}`,
				type: 'geometric',
				kind: 'vertical',
				refs: [{ entityId: String(l.objectId), feature: 'whole' }],
			});
		}
	}

	// 2. Coincident / Parallel / Perpendicular between pairs of lines
	for (let i = 0; i < lines.length; i++) {
		const l1 = lines[i];
		const id1 = String(l1.objectId);
		const dx1 = l1.endPoint.x - l1.startPoint.x;
		const dy1 = l1.endPoint.y - l1.startPoint.y;
		const len1 = Math.hypot(dx1, dy1);

		for (let j = i + 1; j < lines.length; j++) {
			const l2 = lines[j];
			const id2 = String(l2.objectId);
			const dx2 = l2.endPoint.x - l2.startPoint.x;
			const dy2 = l2.endPoint.y - l2.startPoint.y;
			const len2 = Math.hypot(dx2, dy2);

			// Coincident endpoints
			const pts1: [string, AcGePoint3d][] = [['start', l1.startPoint], ['end', l1.endPoint]];
			const pts2: [string, AcGePoint3d][] = [['start', l2.startPoint], ['end', l2.endPoint]];
			for (const [f1, p1] of pts1) {
				for (const [f2, p2] of pts2) {
					if (Math.hypot(p1.x - p2.x, p1.y - p2.y) < TOL_DIST) {
						store.constraints.push({
							id: `ac_${Date.now()}_${appliedCount++}`,
							type: 'geometric',
							kind: 'coincident',
							refs: [
								{ entityId: id1, feature: f1 as 'start' | 'end' },
								{ entityId: id2, feature: f2 as 'start' | 'end' },
							],
						});
					}
				}
			}

			// Parallel or Perpendicular
			if (len1 > 1e-6 && len2 > 1e-6) {
				const cross = Math.abs(dx1 * dy2 - dy1 * dx2) / (len1 * len2);
				const dot = Math.abs(dx1 * dx2 + dy1 * dy2) / (len1 * len2);
				if (cross < TOL_ANGLE) {
					store.constraints.push({
						id: `ac_${Date.now()}_${appliedCount++}`,
						type: 'geometric',
						kind: 'parallel',
						refs: [{ entityId: id1, feature: 'whole' }, { entityId: id2, feature: 'whole' }],
					});
				} else if (dot < TOL_ANGLE) {
					store.constraints.push({
						id: `ac_${Date.now()}_${appliedCount++}`,
						type: 'geometric',
						kind: 'perpendicular',
						refs: [{ entityId: id1, feature: 'whole' }, { entityId: id2, feature: 'whole' }],
					});
				}
			}
		}
	}

	// 3. Tangent between lines and circles
	for (const l of lines) {
		const idL = String(l.objectId);
		const dx = l.endPoint.x - l.startPoint.x;
		const dy = l.endPoint.y - l.startPoint.y;
		const len = Math.hypot(dx, dy);
		if (len < 1e-6) continue;

		for (const c of circles) {
			const idC = String(c.objectId);
			const num = Math.abs(dx * (c.center.y - l.startPoint.y) - dy * (c.center.x - l.startPoint.x));
			const dist = num / len;
			if (Math.abs(dist - c.radius) < TOL_DIST) {
				store.constraints.push({
					id: `ac_${Date.now()}_${appliedCount++}`,
					type: 'geometric',
					kind: 'tangent',
					refs: [{ entityId: idL, feature: 'whole' }, { entityId: idC, feature: 'whole' }],
				});
			}
		}
	}

	if (appliedCount > 0) {
		try {
			await solveAndUpdateDatabase(ctx, store);
			ctx.message(`${appliedCount} constraint(s) inferred and applied.`);
		} catch {
			ctx.message('AUTOCONSTRAIN produced conflicting constraints; partial set saved.');
		}
	} else {
		ctx.message('No geometric constraints inferred within tolerance.');
	}
}

// ---------------------------------------------------------------------------
// DIMCONSTRAINT Command Handlers
// ---------------------------------------------------------------------------

function nextParameterName(params: Record<string, ParameterDefinition>, prefix = 'd'): string {
	let idx = 1;
	while (`${prefix}${idx}` in params) {
		idx++;
	}
	return `${prefix}${idx}`;
}

export async function addDimensionalConstraint(
	ctx: CadCommandContext,
	kind: DimensionalConstraintType,
): Promise<void> {
	ensureDimConstraintLayer(ctx.database.native);
	const store = loadConstraintsFromDatabase(ctx.database.native);

	if (kind === 'radial' || kind === 'diameter') {
		const pick = await ctx.getEntityPick(`Select arc or circle for ${kind.toUpperCase()} constraint:`);
		if (pick.status !== 'ok' || !pick.entity) return;
		const circle = pick.entity as AcDbCircle;
		const measured = kind === 'diameter' ? 2 * circle.radius : circle.radius;
		const paramName = nextParameterName(store.parameters, kind === 'radial' ? 'rad' : 'dia');
		const expr = (await ctx.getString(`Enter expression for parameter ${paramName} <${measured.toFixed(2)}>:`, { allowEmpty: true })).trim() || `${measured}`;
		const val = Number(expr) || measured;

		store.parameters[paramName] = { name: paramName, expression: expr, value: val };
		const constraint: DimensionalConstraint = {
			id: `dim_${Date.now()}`,
			type: 'dimensional',
			kind,
			refs: [{ entityId: String(circle.objectId), feature: 'whole' }],
			name: paramName,
			expression: expr,
			value: val,
		};
		store.constraints.push(constraint);
		await solveAndUpdateDatabase(ctx, store);
		ctx.message(`Dimensional constraint ${paramName} = ${expr} added.`);
		return;
	}

	// Aligned / Linear / Horizontal / Vertical
	const pick1 = await ctx.getEntityPick('Select first object or specify first point:');
	if (pick1.status !== 'ok' || !pick1.entity) return;

	let ref1: GeomRef;
	let ref2: GeomRef;
	let measured = 100;

	if (pick1.entity instanceof AcDbLine || pick1.entity.dxfTypeName === 'LINE') {
		const line = pick1.entity as AcDbLine;
		ref1 = { entityId: String(line.objectId), feature: 'start' };
		ref2 = { entityId: String(line.objectId), feature: 'end' };
		if (kind === 'horizontal') {
			measured = Math.abs(line.endPoint.x - line.startPoint.x);
		} else if (kind === 'vertical') {
			measured = Math.abs(line.endPoint.y - line.startPoint.y);
		} else {
			measured = Math.hypot(line.endPoint.x - line.startPoint.x, line.endPoint.y - line.startPoint.y);
		}
	} else {
		ref1 = pickGeometryFeature(pick1.entity, pick1.point, 'start');
		const pick2 = await ctx.getEntityPick('Select second object or point:');
		if (pick2.status !== 'ok' || !pick2.entity) return;
		ref2 = pickGeometryFeature(pick2.entity, pick2.point, 'end');
	}

	const paramName = nextParameterName(store.parameters, 'd');
	const expr = (await ctx.getString(`Enter expression for parameter ${paramName} <${measured.toFixed(2)}>:`, { allowEmpty: true })).trim() || `${measured}`;
	const val = Number(expr) || measured;

	// Create plain dimension entity on DIMCONSTRAINT layer
	let dimEntId: string | undefined;
	try {
		const ent1 = ctx.database.get(ref1.entityId);
		if (ent1 instanceof AcDbLine) {
			const p1 = ent1.startPoint;
			const p2 = ent1.endPoint;
			const dimPt = new AcGePoint3d((p1.x + p2.x) / 2, (p1.y + p2.y) / 2 + 10, 0);
			const dim = kind === 'horizontal' || kind === 'vertical'
				? new AcDbRotatedDimension(p1, p2, dimPt)
				: new AcDbAlignedDimension(p1, p2, dimPt);
			dim.layer = DIMCONSTRAINT_LAYER;
			dim.dimensionText = `${paramName}=${expr}`;
			ctx.database.add(dim);
			dimEntId = String(dim.objectId);
		}
	} catch {
		// Ignore dimension entity render fallback
	}

	store.parameters[paramName] = { name: paramName, expression: expr, value: val };
	const constraint: DimensionalConstraint = {
		id: `dim_${Date.now()}`,
		type: 'dimensional',
		kind,
		refs: [ref1, ref2],
		name: paramName,
		expression: expr,
		value: val,
		dimensionEntityId: dimEntId,
	};
	store.constraints.push(constraint);
	await solveAndUpdateDatabase(ctx, store);
	ctx.message(`Dimensional constraint ${paramName} = ${expr} added.`);
}

export async function dimConstraintCommand(ctx: CadCommandContext): Promise<void> {
	const choice = await ctx.getKeyword(
		'Enter dimensional constraint type [Aligned/Linear/Horizontal/Vertical/Radial/Diameter] <Aligned>:',
		['Aligned', 'Linear', 'Horizontal', 'Vertical', 'Radial', 'Diameter'],
		{ default: 'Aligned' },
	);
	const kind = choice.toLowerCase() as DimensionalConstraintType;
	await addDimensionalConstraint(ctx, kind);
}

// ---------------------------------------------------------------------------
// PARAMETERS / -PARAMETERS Command
// ---------------------------------------------------------------------------

export async function parametersCommand(ctx: CadCommandContext): Promise<void> {
	const store = loadConstraintsFromDatabase(ctx.database.native);
	evaluateAllParameters(store.parameters);

	const action = await ctx.getKeyword(
		'Parameter option [List/Edit/Rename/Delete/New] <List>:',
		['List', 'Edit', 'Rename', 'Delete', 'New'],
		{ default: 'List' },
	);

	const opt = action.toUpperCase();

	if (opt === 'LIST') {
		const keys = Object.keys(store.parameters);
		if (keys.length === 0) {
			ctx.message('No parameters in drawing.');
			return;
		}
		ctx.message('Drawing Parameters:');
		for (const key of keys) {
			const p = store.parameters[key];
			ctx.message(`  ${p.name} = ${p.expression}  (Value: ${p.value.toFixed(4)})${p.isUser ? ' [User]' : ''}`);
		}
		return;
	}

	if (opt === 'NEW') {
		const name = (await ctx.getString('Enter parameter name:', { allowSpaces: false })).trim();
		if (!name) return;
		if (name in store.parameters) {
			ctx.message(`Parameter "${name}" already exists.`);
			return;
		}
		const expr = (await ctx.getString('Enter expression:')).trim();
		if (!expr) return;
		store.parameters[name] = { name, expression: expr, value: 0, isUser: true };
		try {
			await solveAndUpdateDatabase(ctx, store);
			ctx.message(`User parameter "${name}" = ${expr} created.`);
		} catch (err) {
			delete store.parameters[name];
			ctx.message(`Failed to create parameter: ${err instanceof Error ? err.message : String(err)}`);
		}
		return;
	}

	if (opt === 'EDIT') {
		const name = (await ctx.getString('Enter parameter name to edit:', { allowSpaces: false })).trim();
		if (!(name in store.parameters)) {
			ctx.message(`Parameter "${name}" not found.`);
			return;
		}
		const oldExpr = store.parameters[name].expression;
		const newExpr = (await ctx.getString(`Enter new expression <${oldExpr}>:`)).trim() || oldExpr;
		store.parameters[name] = { ...store.parameters[name], expression: newExpr };

		try {
			await solveAndUpdateDatabase(ctx, store);
			ctx.message(`Parameter "${name}" updated to ${newExpr}. Drawing re-solved.`);
		} catch (err) {
			store.parameters[name] = { ...store.parameters[name], expression: oldExpr };
			ctx.message(`Parameter update rejected: ${err instanceof Error ? err.message : String(err)}`);
		}
		return;
	}

	if (opt === 'RENAME') {
		const oldName = (await ctx.getString('Enter current parameter name:', { allowSpaces: false })).trim();
		if (!(oldName in store.parameters)) {
			ctx.message(`Parameter "${oldName}" not found.`);
			return;
		}
		const newName = (await ctx.getString('Enter new parameter name:', { allowSpaces: false })).trim();
		if (!newName || newName === oldName) return;
		if (newName in store.parameters) {
			ctx.message(`Parameter "${newName}" already exists.`);
			return;
		}
		const p = store.parameters[oldName];
		delete store.parameters[oldName];
		store.parameters[newName] = { ...p, name: newName };

		// Update constraint references
		for (let i = 0; i < store.constraints.length; i++) {
			const c = store.constraints[i];
			if (c.type === 'dimensional' && c.name === oldName) {
				store.constraints[i] = { ...c, name: newName };
			}
		}

		await solveAndUpdateDatabase(ctx, store);
		ctx.message(`Parameter renamed to "${newName}".`);
		return;
	}

	if (opt === 'DELETE') {
		const name = (await ctx.getString('Enter parameter name to delete:', { allowSpaces: false })).trim();
		if (!(name in store.parameters)) {
			ctx.message(`Parameter "${name}" not found.`);
			return;
		}
		// Check if referenced by a dimensional constraint
		const isConstrained = store.constraints.some(c => c.type === 'dimensional' && c.name === name);
		if (isConstrained) {
			ctx.message(`Cannot delete parameter "${name}": referenced by active constraint. Use DELCONSTRAINT first.`);
			return;
		}
		delete store.parameters[name];
		saveConstraintsToDatabase(ctx.database.native, store);
		ctx.message(`Parameter "${name}" deleted.`);
		return;
	}
}

// ---------------------------------------------------------------------------
// DELCONSTRAINT & CONSTRAINTBAR Commands
// ---------------------------------------------------------------------------

export async function delConstraintCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects to delete constraints:');
	if (sel.length === 0) return;
	const selectedIds = new Set(sel.map(e => String(e.objectId)));

	const store = loadConstraintsFromDatabase(ctx.database.native);
	const initialCount = store.constraints.length;

	const remaining: ConstraintDefinition[] = [];
	const removedDimEntityIds: string[] = [];

	for (const c of store.constraints) {
		const hits = c.refs.some(r => selectedIds.has(r.entityId));
		if (hits) {
			if (c.type === 'dimensional' && c.dimensionEntityId) {
				removedDimEntityIds.push(c.dimensionEntityId);
			}
		} else {
			remaining.push(c);
		}
	}

	store.constraints = remaining;

	await ctx.transaction(async () => {
		for (const dimId of removedDimEntityIds) {
			try {
				ctx.database.erase(dimId);
			} catch {}
		}
		saveConstraintsToDatabase(ctx.database.native, store);
	});

	const removedCount = initialCount - remaining.length;
	ctx.message(`${removedCount} constraint(s) removed.`);
}

export async function constraintBarCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects to list constraints:');
	if (sel.length === 0) return;
	const selectedIds = new Set(sel.map(e => String(e.objectId)));

	const store = loadConstraintsFromDatabase(ctx.database.native);
	const matching = store.constraints.filter(c => c.refs.some(r => selectedIds.has(r.entityId)));

	if (matching.length === 0) {
		ctx.message('No constraints on selected objects.');
		return;
	}

	ctx.message(`Constraints on selected objects (${matching.length}):`);
	for (const c of matching) {
		const ents = c.refs.map(r => `#${r.entityId}.${r.feature}`).join(', ');
		if (c.type === 'geometric') {
			ctx.message(`  [Geometric] ${c.kind.toUpperCase()} (${ents})`);
		} else {
			ctx.message(`  [Dimensional] ${c.kind.toUpperCase()} ${c.name}=${c.expression} (${ents})`);
		}
	}
}

// ---------------------------------------------------------------------------
// Register all constraint commands
// ---------------------------------------------------------------------------

export function registerConstraintCommands(registerFn = registerCommand): void {
	registerFn('GEOMCONSTRAINT', geomConstraintCommand, { aliases: ['GC'] });
	registerFn('GCHORIZONTAL', ctx => addGeometricConstraint(ctx, 'horizontal'), { aliases: ['GCH'] });
	registerFn('GCVERTICAL', ctx => addGeometricConstraint(ctx, 'vertical'), { aliases: ['GCV'] });
	registerFn('GCPARALLEL', ctx => addGeometricConstraint(ctx, 'parallel'), { aliases: ['GCP'] });
	registerFn('GCPERPENDICULAR', ctx => addGeometricConstraint(ctx, 'perpendicular'), { aliases: ['GCPERP'] });
	registerFn('GCCOINCIDENT', ctx => addGeometricConstraint(ctx, 'coincident'), { aliases: ['GCCO'] });
	registerFn('GCCOLLINEAR', ctx => addGeometricConstraint(ctx, 'collinear'), { aliases: ['GCCOL'] });
	registerFn('GCCONCENTRIC', ctx => addGeometricConstraint(ctx, 'concentric'), { aliases: ['GCCON'] });
	registerFn('GCTANGENT', ctx => addGeometricConstraint(ctx, 'tangent'), { aliases: ['GCT'] });
	registerFn('GCEQUAL', ctx => addGeometricConstraint(ctx, 'equal'), { aliases: ['GCE'] });
	registerFn('GCFIX', ctx => addGeometricConstraint(ctx, 'fix'), { aliases: ['GCF'] });
	registerFn('GCSYMMETRIC', ctx => addGeometricConstraint(ctx, 'symmetric'), { aliases: ['GCSYM'] });

	registerFn('AUTOCONSTRAIN', autoConstrainCommand, { aliases: ['AUTOCON'] });

	registerFn('DIMCONSTRAINT', dimConstraintCommand, { aliases: ['DC'] });
	registerFn('DCALIGNED', ctx => addDimensionalConstraint(ctx, 'aligned'), { aliases: ['DALIGNED'] });
	registerFn('DCLINEAR', ctx => addDimensionalConstraint(ctx, 'linear'), { aliases: ['DLINEAR'] });
	registerFn('DCHORIZONTAL', ctx => addDimensionalConstraint(ctx, 'horizontal'), { aliases: ['DCH'] });
	registerFn('DCVERTICAL', ctx => addDimensionalConstraint(ctx, 'vertical'), { aliases: ['DCV'] });
	registerFn('DCRADIAL', ctx => addDimensionalConstraint(ctx, 'radial'), { aliases: ['DCR'] });
	registerFn('DCDIAMETER', ctx => addDimensionalConstraint(ctx, 'diameter'), { aliases: ['DCD'] });
	registerFn('DCANGULAR', ctx => addDimensionalConstraint(ctx, 'angular'), { aliases: ['DCANG'] });

	registerFn('PARAMETERS', parametersCommand, { aliases: ['PARAM', '-PARAMETERS'] });
	registerFn('-PARAMETERS', parametersCommand);

	registerFn('DELCONSTRAINT', delConstraintCommand, { aliases: ['DELCON'] });
	registerFn('CONSTRAINTBAR', constraintBarCommand, { aliases: ['CBAR'] });

	// The library's own edits (MOVE, ROTATE, SCALE, MIRROR, …) are re-solved after they end (index.ts).
	registerFn('CONSTRAINTSOLVE', reSolveConstraintsAfterEdit);
}
