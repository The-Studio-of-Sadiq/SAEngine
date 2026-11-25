/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc,
	AcDbCircle,
	AcDbEntity,
	AcDbLine,
	AcDbPolyline,
	AcGeMatrix3d,
	AcGePoint2d,
	AcGePoint3d,
	AcGeVector3d,
} from '@mlightcad/data-model';
import {
	cloneTransform,
	copyProperties,
	mirrorEntity,
	pointTransform,
	registerCommand,
	translation,
	type CadCommandContext,
	type CadPoint3,
} from './commands.js';
import { polylineVertices } from './entityAccess.js';
import {
	addPolylineVertex,
	convertSegmentToArc,
	removePolylineVertex,
} from './gripGeometry.js';

export type GripEditMode = 'STRETCH' | 'MOVE' | 'ROTATE' | 'SCALE' | 'MIRROR';
export const GRIP_EDIT_MODES: readonly GripEditMode[] = ['STRETCH', 'MOVE', 'ROTATE', 'SCALE', 'MIRROR'];

export interface ActiveGripContext {
	entityId: string;
	gripIndex: number;
	basePoint: CadPoint3;
	selectedIds?: string[];
}

let activeGripContext: ActiveGripContext | undefined;

export function setActiveGripContext(ctx: ActiveGripContext | undefined): void {
	activeGripContext = ctx;
}

export function getActiveGripContext(): ActiveGripContext | undefined {
	return activeGripContext;
}

/**
 * AutoCAD-style multifunctional grip editing command.
 * Once a grip is hot:
 * - Space / Enter cycles STRETCH -> MOVE -> ROTATE -> SCALE -> MIRROR
 * - Base point defaults to the hot grip
 * - Keywords: Base point, Copy, Undo, Reference (for rotate/scale), eXit
 * - MOVE/ROTATE/SCALE/MIRROR apply to ALL selected entities
 * - Polyline vertex grips offer Stretch / Add vertex / Remove vertex
 * - Polyline segment-midpoint grips offer Stretch / Add vertex / Convert to arc / Convert to line
 */
export async function gripEditCommand(ctx: CadCommandContext): Promise<void> {
	const gripContext = activeGripContext;

	// Resolve selected entities
	let selectedEntities: AcDbEntity[] = [];
	if (gripContext?.selectedIds && gripContext.selectedIds.length > 0) {
		selectedEntities = gripContext.selectedIds
			.map(id => ctx.database.get(id))
			.filter((e): e is AcDbEntity => !!e);
	}

	if (selectedEntities.length === 0) {
		try {
			selectedEntities = [...(await ctx.getSelection('Select objects for grip edit:'))];
		} catch {
			return;
		}
	}

	if (selectedEntities.length === 0) return;

	// Resolve the hot entity and grip
	let hotEntity: AcDbEntity | undefined;
	let gripIndex = 0;
	let basePoint: CadPoint3;

	if (gripContext) {
		hotEntity = ctx.database.get(gripContext.entityId) ?? selectedEntities[0];
		gripIndex = gripContext.gripIndex;
		basePoint = { ...gripContext.basePoint };
	} else {
		hotEntity = selectedEntities[0];
		const grips = (hotEntity as unknown as { subGetGripPoints?: () => CadPoint3[] }).subGetGripPoints?.() ?? [];
		if (grips.length > 0) {
			basePoint = { x: grips[0].x, y: grips[0].y, z: grips[0].z ?? 0 };
		} else {
			basePoint = await ctx.getPoint('Specify base point:');
		}
	}

	let modeIdx = 0;
	let copyMode = false;
	const addedCopies: AcDbEntity[] = [];

	while (true) {
		const currentMode = GRIP_EDIT_MODES[modeIdx];

		// Check for polyline-specific grip extras when in STRETCH mode
		let isPolylineVertex = false;
		let isPolylineMidpoint = false;
		let polyVertexIndex = 0;
		let polySegmentIndex = 0;

		if (currentMode === 'STRETCH' && hotEntity instanceof AcDbPolyline) {
			const n = hotEntity.numberOfVertices;
			if (gripIndex < n) {
				isPolylineVertex = true;
				polyVertexIndex = gripIndex;
			} else {
				isPolylineMidpoint = true;
				polySegmentIndex = gripIndex - n;
			}
		}

		// Prepare prompt and keywords
		const keywords: string[] = [];
		if (isPolylineVertex) {
			keywords.push('Stretch', 'Add vertex', 'Remove vertex', 'Base point', 'Copy', 'Undo', 'eXit');
		} else if (isPolylineMidpoint) {
			keywords.push('Stretch', 'Add vertex', 'Convert to arc', 'Convert to line', 'Base point', 'Copy', 'Undo', 'eXit');
		} else if (currentMode === 'ROTATE' || currentMode === 'SCALE') {
			keywords.push('Base point', 'Copy', 'Undo', 'Reference', 'eXit');
		} else {
			keywords.push('Base point', 'Copy', 'Undo', 'eXit');
		}

		let promptMsg = `** ${currentMode} **\n`;
		switch (currentMode) {
			case 'STRETCH':
				promptMsg += `Specify stretch point or [${keywords.join('/')}]:`;
				break;
			case 'MOVE':
				promptMsg += `Specify move point or [${keywords.join('/')}]:`;
				break;
			case 'ROTATE':
				promptMsg += `Specify rotation angle or [${keywords.join('/')}]:`;
				break;
			case 'SCALE':
				promptMsg += `Specify scale factor or [${keywords.join('/')}]:`;
				break;
			case 'MIRROR':
				promptMsg += `Specify second point or [${keywords.join('/')}]:`;
				break;
		}

		const pickResult = await ctx.getPointPick(promptMsg, {
			base: basePoint,
			keywords,
			allowNone: true,
		});

		// Space or Enter: cycle to the next grip mode
		if (pickResult.status === 'none') {
			modeIdx = (modeIdx + 1) % GRIP_EDIT_MODES.length;
			continue;
		}

		if (pickResult.status === 'cancel') {
			break;
		}

		if (pickResult.status === 'keyword') {
			const kw = (pickResult.keyword ?? '').toLowerCase();

			if (kw === 'base point' || kw === 'b') {
				basePoint = await ctx.getPoint('Specify base point:');
				continue;
			}

			if (kw === 'copy' || kw === 'c') {
				copyMode = true;
				ctx.message('Copy mode on. Specify next point or eXit:');
				continue;
			}

			if (kw === 'undo' || kw === 'u') {
				const last = addedCopies.pop();
				if (last) {
					ctx.database.erase(String(last.objectId));
				} else {
					ctx.message('Nothing to undo in this grip edit session.');
				}
				continue;
			}

			if (kw === 'exit' || kw === 'x') {
				break;
			}

			if (kw === 'reference' || kw === 'r') {
				if (currentMode === 'ROTATE') {
					const refAngle = await ctx.getAngle('Specify reference angle <0>:', { base: basePoint });
					const newAngle = await ctx.getAngle('Specify new angle:', { base: basePoint });
					const angleDelta = newAngle - refAngle;
					const mat = pointTransform(basePoint, 1, angleDelta);
					await applyTransformation(ctx, selectedEntities, mat, copyMode, addedCopies);
					if (!copyMode) break;
					continue;
				}
				if (currentMode === 'SCALE') {
					const refLen = await ctx.getDistance('Specify reference length <1>:', { base: basePoint });
					const newLen = await ctx.getDistance('Specify new length:', { base: basePoint });
					const factor = refLen > 0 ? newLen / refLen : 1;
					if (factor > 0) {
						const mat = pointTransform(basePoint, factor, 0);
						await applyTransformation(ctx, selectedEntities, mat, copyMode, addedCopies);
						if (!copyMode) break;
						continue;
					}
				}
			}

			// Polyline extra keywords
			if (isPolylineVertex || isPolylineMidpoint) {
				const poly = hotEntity as AcDbPolyline;

				if (kw === 'add vertex' || kw === 'a') {
					const newPt = await ctx.getPoint('Specify new vertex point:', { base: basePoint });
					const cur = polylineVertices(poly);
					const insertAfter = isPolylineVertex ? polyVertexIndex : polySegmentIndex;
					const updated = addPolylineVertex(cur.points, insertAfter, [newPt.x, newPt.y], cur.bulges);
					const newPoly = new AcDbPolyline();
					newPoly.closed = poly.closed;
					updated.vertices.forEach((p, i) =>
						newPoly.addVertexAt(i, new AcGePoint2d(p[0], p[1]), updated.bulges?.[i] ?? 0),
					);
					ctx.database.replace(String(poly.objectId), copyProperties(poly, newPoly));
					break;
				}

				if (isPolylineVertex && (kw === 'remove vertex' || kw === 'r')) {
					const cur = polylineVertices(poly);
					if (cur.points.length > 2) {
						const updated = removePolylineVertex(cur.points, polyVertexIndex, cur.bulges);
						const newPoly = new AcDbPolyline();
						newPoly.closed = poly.closed;
						updated.vertices.forEach((p, i) =>
							newPoly.addVertexAt(i, new AcGePoint2d(p[0], p[1]), updated.bulges?.[i] ?? 0),
						);
						ctx.database.replace(String(poly.objectId), copyProperties(poly, newPoly));
					} else {
						ctx.message('Cannot remove vertex: polyline requires at least 2 vertices.');
					}
					break;
				}

				if (isPolylineMidpoint && (kw === 'convert to arc' || kw === 'arc')) {
					const arcPt = await ctx.getPoint('Specify point on arc:', { base: basePoint });
					const cur = polylineVertices(poly);
					const p1 = cur.points[polySegmentIndex];
					const p2 = cur.points[(polySegmentIndex + 1) % cur.points.length];
					const bulge = convertSegmentToArc(p1, p2, [arcPt.x, arcPt.y]);
					const newPoly = new AcDbPolyline();
					newPoly.closed = poly.closed;
					const bulges = [...cur.bulges];
					bulges[polySegmentIndex] = bulge;
					cur.points.forEach((p, i) =>
						newPoly.addVertexAt(i, new AcGePoint2d(p[0], p[1]), bulges[i] ?? 0),
					);
					ctx.database.replace(String(poly.objectId), copyProperties(poly, newPoly));
					break;
				}

				if (isPolylineMidpoint && (kw === 'convert to line' || kw === 'line')) {
					const cur = polylineVertices(poly);
					const newPoly = new AcDbPolyline();
					newPoly.closed = poly.closed;
					const bulges = [...cur.bulges];
					bulges[polySegmentIndex] = 0;
					cur.points.forEach((p, i) =>
						newPoly.addVertexAt(i, new AcGePoint2d(p[0], p[1]), bulges[i] ?? 0),
					);
					ctx.database.replace(String(poly.objectId), copyProperties(poly, newPoly));
					break;
				}

				if (kw === 'stretch' || kw === 's') {
					continue;
				}
			}

			continue;
		}

		if (pickResult.status === 'ok' && pickResult.point) {
			const target = pickResult.point;
			const dx = target.x - basePoint.x;
			const dy = target.y - basePoint.y;

			switch (currentMode) {
				case 'STRETCH': {
					const offset = new AcGeVector3d(dx, dy, 0);
					if (copyMode) {
						const clone = hotEntity.clone() as AcDbEntity;
						(clone as unknown as { subMoveGripPointsAt: (idx: number[], off: AcGeVector3d) => void }).subMoveGripPointsAt(
							[gripIndex],
							offset,
						);
						ctx.database.add(clone);
						addedCopies.push(clone);
					} else {
						const c = hotEntity.clone() as AcDbEntity;
						(c as unknown as { subMoveGripPointsAt: (idx: number[], off: AcGeVector3d) => void }).subMoveGripPointsAt(
							[gripIndex],
							offset,
						);
						ctx.database.replace(String(hotEntity.objectId), copyProperties(hotEntity, c));
					}
					break;
				}

				case 'MOVE': {
					const mat = translation(dx, dy);
					await applyTransformation(ctx, selectedEntities, mat, copyMode, addedCopies);
					break;
				}

				case 'ROTATE': {
					const angle = Math.atan2(dy, dx);
					const mat = pointTransform(basePoint, 1, angle);
					await applyTransformation(ctx, selectedEntities, mat, copyMode, addedCopies);
					break;
				}

				case 'SCALE': {
					const dist = Math.hypot(dx, dy);
					const factor = dist > 1e-6 ? dist : 1;
					const mat = pointTransform(basePoint, factor, 0);
					await applyTransformation(ctx, selectedEntities, mat, copyMode, addedCopies);
					break;
				}

				case 'MIRROR': {
					if (Math.hypot(dx, dy) > 1e-9) {
						if (copyMode) {
							const copies = selectedEntities.map(e => mirrorEntity(e, basePoint, target));
							ctx.database.add(copies);
							addedCopies.push(...copies);
						} else {
							for (const e of selectedEntities) {
								const mirrored = mirrorEntity(e, basePoint, target);
								ctx.database.replace(String(e.objectId), copyProperties(e, mirrored));
							}
						}
					}
					break;
				}
			}

			if (!copyMode) {
				break;
			}
		}
	}

	try {
		const { reSolveConstraintsAfterEdit } = await import('./constraintCommands.js');
		await reSolveConstraintsAfterEdit(ctx);
	} catch (err) {
		if (err instanceof Error && err.message.includes('over-constrain')) {
			ctx.message(err.message);
			throw err;
		}
	}

	setActiveGripContext(undefined);
}

async function applyTransformation(
	ctx: CadCommandContext,
	entities: AcDbEntity[],
	matrix: AcGeMatrix3d,
	copyMode: boolean,
	addedCopies: AcDbEntity[],
): Promise<void> {
	if (copyMode) {
		const copies = entities.map(e => cloneTransform(e, matrix));
		ctx.database.add(copies);
		addedCopies.push(...copies);
	} else {
		for (const e of entities) {
			const transformed = cloneTransform(e, matrix);
			ctx.database.replace(String(e.objectId), transformed);
		}
	}
}

/**
 * Registers the GRIPEDIT command with aliases.
 */
export function registerGripCommands(registerFn = registerCommand): void {
	registerFn('GRIPEDIT', gripEditCommand, { aliases: ['GE', 'GRIP'] });
}
