/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbPolyline, AcDbSpline,
	AcGePoint2d, AcGePoint3d,
} from '@mlightcad/data-model';
import type { CadCommandContext } from './commands.js';
import { copyProperties, registerCommand } from './commands.js';
import { polylineVertices } from './entityAccess.js';
import { arcToBulge } from './modifyGeometry2.js';
import {
	bSplinePolyline, fitArcBulges, mergeCollinearLines,
	removeDuplicateVertices, type CollinearLine, type Point2D,
} from './polyEditGeometry.js';

interface PolylineSnapshot {
	points: Point2D[];
	bulges: number[];
	closed: boolean;
	widths?: [number, number][];
	originalVertices?: Point2D[];
}

interface SplineSnapshot {
	controlPoints: { x: number; y: number; z: number }[];
	knots: number[];
	weights?: number[];
	degree: number;
	closed: boolean;
	fitPoints?: { x: number; y: number; z: number }[];
	fitTolerance?: number;
}

function isGenerated(entity: AcDbEntity, ctx?: CadCommandContext): boolean {
	const genLayers = (globalThis as any).__saengineGeneratedLayers as Set<string> | undefined;
	if (entity.layer && genLayers?.has(entity.layer)) return true;
	if (ctx?.database?.native?.tables?.layerTable?.getAt(entity.layer)?.isLocked) return true;
	return false;
}

function convertLineOrArcToPolyline(e: AcDbEntity): AcDbPolyline | undefined {
	if (e instanceof AcDbLine) {
		const poly = new AcDbPolyline();
		poly.addVertexAt(0, new AcGePoint2d(e.startPoint.x, e.startPoint.y), 0);
		poly.addVertexAt(1, new AcGePoint2d(e.endPoint.x, e.endPoint.y), 0);
		copyProperties(e, poly);
		return poly;
	}
	if (e instanceof AcDbArc) {
		const p1: Point2D = [
			e.center.x + e.radius * Math.cos(e.startAngle),
			e.center.y + e.radius * Math.sin(e.startAngle),
		];
		const p2: Point2D = [
			e.center.x + e.radius * Math.cos(e.endAngle),
			e.center.y + e.radius * Math.sin(e.endAngle),
		];
		const b = arcToBulge(p1, p2, [e.center.x, e.center.y], true);
		const poly = new AcDbPolyline();
		poly.addVertexAt(0, new AcGePoint2d(p1[0], p1[1]), b);
		poly.addVertexAt(1, new AcGePoint2d(p2[0], p2[1]), 0);
		copyProperties(e, poly);
		return poly;
	}
	return undefined;
}

function entityToChain(e: AcDbEntity): { points: Point2D[]; bulges: number[] } | undefined {
	if (e instanceof AcDbLine) {
		return {
			points: [[e.startPoint.x, e.startPoint.y], [e.endPoint.x, e.endPoint.y]],
			bulges: [0],
		};
	}
	if (e instanceof AcDbArc) {
		const p1: Point2D = [
			e.center.x + e.radius * Math.cos(e.startAngle),
			e.center.y + e.radius * Math.sin(e.startAngle),
		];
		const p2: Point2D = [
			e.center.x + e.radius * Math.cos(e.endAngle),
			e.center.y + e.radius * Math.sin(e.endAngle),
		];
		const b = arcToBulge(p1, p2, [e.center.x, e.center.y], true);
		return { points: [p1, p2], bulges: [b] };
	}
	if (e instanceof AcDbPolyline && !e.closed) {
		const { points, bulges } = polylineVertices(e);
		return { points: points.map(p => [p[0], p[1]] as Point2D), bulges };
	}
	return undefined;
}

function rebuildPolyline(
	poly: AcDbPolyline,
	points: readonly Point2D[],
	bulges?: readonly number[],
	closed?: boolean,
	widths?: readonly [number, number][],
): void {
	poly.reset(false);
	const n = points.length;
	const isClosed = closed !== undefined ? closed : poly.closed;
	poly.closed = isClosed;
	for (let i = 0; i < n; i++) {
		const b = bulges && i < bulges.length ? bulges[i] : 0;
		const w = widths && i < widths.length ? widths[i] : undefined;
		poly.addVertexAt(
			i,
			new AcGePoint2d(points[i][0], points[i][1]),
			b,
			w ? w[0] : undefined,
			w ? w[1] : undefined,
		);
	}
}

function snapshotPolyline(poly: AcDbPolyline, orig?: Point2D[]): PolylineSnapshot {
	const data = polylineVertices(poly);
	return {
		points: data.points.map(p => [p[0], p[1]]),
		bulges: [...data.bulges],
		closed: !!poly.closed,
		originalVertices: orig ? orig.map(p => [p[0], p[1]]) : undefined,
	};
}

/**
 * AutoCAD PEDIT command (and PE alias).
 */
export async function peditCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select polyline or [Multiple]:', {
		keywords: ['Multiple', 'M'],
	});

	if (pick.status === 'cancel' || pick.status === 'none') return;

	if (pick.status === 'keyword') {
		// Multiple mode
		const selection = await ctx.getSelection('Select objects:');
		if (selection.length === 0) return;

		for (const ent of selection) {
			if (isGenerated(ent, ctx)) {
				ctx.message('One or more selected entities are generated (read-only); skipping them.');
			}
		}

		const validEntities = selection.filter(ent => !isGenerated(ent, ctx));
		const polylines: AcDbPolyline[] = [];

		let askedConvert = false;
		let doConvert = true;

		for (const ent of validEntities) {
			if (ent instanceof AcDbPolyline) {
				polylines.push(ent);
			} else if (ent instanceof AcDbLine || ent instanceof AcDbArc) {
				if (!askedConvert) {
					const ans = await ctx.getKeyword(
						'Convert Lines, Arcs and Splines to polylines [Yes/No]? <Y>:',
						['Yes', 'No', 'Y', 'N'],
						{ default: 'Y' },
					);
					doConvert = ans.toUpperCase().startsWith('Y');
					askedConvert = true;
				}
				if (doConvert) {
					const poly = convertLineOrArcToPolyline(ent);
					if (poly) {
						ctx.database.replace(String(ent.objectId), poly);
						polylines.push(poly);
					}
				}
			}
		}

		if (polylines.length === 0) {
			ctx.message('No polylines available to edit.');
			return;
		}

		while (true) {
			const opt = await ctx.getKeyword(
				'Enter an option [Close/Open/Join/Width/Fit/Spline/Decurve/Ltype gen/Reverse/eXit] <eXit>:',
				['Close', 'Open', 'Join', 'Width', 'Fit', 'Spline', 'Decurve', 'Ltype gen', 'Reverse', 'eXit', 'C', 'O', 'J', 'W', 'F', 'S', 'D', 'L', 'R', 'X'],
				{ default: 'eXit' },
			);

			const key = opt.toUpperCase();
			if (key === 'EXIT' || key === 'X') break;

			await ctx.transaction(async () => {
				for (const poly of polylines) {
					const data = polylineVertices(poly);
					if (key === 'CLOSE' || key === 'C') {
						poly.closed = true;
					} else if (key === 'OPEN' || key === 'O') {
						poly.closed = false;
					} else if (key === 'WIDTH' || key === 'W') {
						const w = await ctx.getDouble('Enter new width for all segments:');
						const widths: [number, number][] = data.points.map(() => [w, w]);
						rebuildPolyline(poly, data.points as Point2D[], data.bulges, poly.closed, widths);
					} else if (key === 'FIT' || key === 'F') {
						const fit = fitArcBulges(data.points as Point2D[], poly.closed);
						rebuildPolyline(poly, fit.points, fit.bulges, poly.closed);
					} else if (key === 'SPLINE' || key === 'S') {
						const pts = bSplinePolyline(data.points as Point2D[], 2, 8, poly.closed);
						rebuildPolyline(poly, pts, undefined, poly.closed);
					} else if (key === 'DECURVE' || key === 'D') {
						rebuildPolyline(poly, data.points as Point2D[], undefined, poly.closed);
					} else if (key === 'REVERSE' || key === 'R') {
						const revPts = [...data.points].reverse() as Point2D[];
						const revBulges = [...data.bulges].reverse().map(b => -b);
						rebuildPolyline(poly, revPts, revBulges, poly.closed);
					}
				}
			});

			if (key === 'LTYPE GEN' || key === 'L') {
				ctx.message('Linetype generation (PLINEGEN) is not supported by the data model');
			}
		}
		return;
	}

	// Single entity mode
	let entity = pick.entity;
	if (!entity) return;

	if (isGenerated(entity, ctx)) {
		ctx.message('Entity is read-only (generated)');
		return;
	}

	if (entity instanceof AcDbLine || entity instanceof AcDbArc) {
		const ans = await ctx.getKeyword(
			'Do you want to turn it into one? [Yes/No] <Y>:',
			['Yes', 'No', 'Y', 'N'],
			{ default: 'Y' },
		);
		if (!ans.toUpperCase().startsWith('Y')) return;

		const poly = convertLineOrArcToPolyline(entity);
		if (!poly) return;
		ctx.database.replace(String(entity.objectId), poly);
		entity = poly;
	}

	if (!(entity instanceof AcDbPolyline)) {
		ctx.message('Selected entity is not a polyline, line, or arc.');
		return;
	}

	let poly = entity;
	let origVertices: Point2D[] | undefined;
	const undoStack: PolylineSnapshot[] = [];

	while (true) {
		const isClosed = poly.closed;
		const closeOpenKeyword = isClosed ? 'Open' : 'Close';
		const opt = await ctx.getKeyword(
			`Enter an option [${closeOpenKeyword}/Join/Width/Edit vertex/Fit/Spline/Decurve/Ltype gen/Reverse/Undo/eXit] <eXit>:`,
			[
				closeOpenKeyword, 'Join', 'Width', 'Edit vertex', 'Fit', 'Spline',
				'Decurve', 'Ltype gen', 'Reverse', 'Undo', 'eXit',
				'C', 'O', 'J', 'W', 'E', 'F', 'S', 'D', 'L', 'R', 'U', 'X',
			],
			{ default: 'eXit' },
		);

		const key = opt.toUpperCase();
		if (key === 'EXIT' || key === 'X') break;

		if (key === 'UNDO' || key === 'U') {
			const prev = undoStack.pop();
			if (prev) {
				await ctx.transaction(async () => {
					rebuildPolyline(poly, prev.points, prev.bulges, prev.closed, prev.widths);
					origVertices = prev.originalVertices;
				});
				ctx.message('Undo');
			} else {
				ctx.message('Nothing to undo.');
			}
			continue;
		}

		if (key === 'CLOSE' || key === 'C') {
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				poly.closed = true;
			});
			continue;
		}

		if (key === 'OPEN' || key === 'O') {
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				poly.closed = false;
			});
			continue;
		}

		if (key === 'WIDTH' || key === 'W') {
			const w = await ctx.getDouble('Enter new width for all segments:');
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				const data = polylineVertices(poly);
				const widths: [number, number][] = data.points.map(() => [w, w]);
				rebuildPolyline(poly, data.points as Point2D[], data.bulges, poly.closed, widths);
			});
			continue;
		}

		if (key === 'JOIN' || key === 'J') {
			const others = await ctx.getSelection('Select objects to join:');
			let fuzz = 0;
			try {
				fuzz = await ctx.getDouble('Enter fuzz distance <0.0000>:');
			} catch {
				fuzz = 0;
			}

			const curChain = entityToChain(poly);
			if (!curChain) {
				ctx.message('Cannot join to closed polyline');
				continue;
			}

			const currentPoints = [...curChain.points];
			const currentBulges = [...curChain.bulges];
			const pool = others.filter(e => String(e.objectId) !== String(poly.objectId));
			const joinedEntities: AcDbEntity[] = [];

			const near = (p: Point2D, q: Point2D) => Math.hypot(p[0] - q[0], p[1] - q[1]) <= fuzz + 1e-6;

			let progressed = true;
			while (progressed) {
				progressed = false;
				for (let i = 0; i < pool.length; i++) {
					const cand = pool[i];
					const cSeg = entityToChain(cand);
					if (!cSeg) continue;

					const head = currentPoints[0];
					const tail = currentPoints[currentPoints.length - 1];
					const candHead = cSeg.points[0];
					const candTail = cSeg.points[cSeg.points.length - 1];

					if (near(tail, candHead)) {
						currentPoints.push(...cSeg.points.slice(1));
						currentBulges.push(...cSeg.bulges);
						joinedEntities.push(cand);
						pool.splice(i, 1);
						progressed = true;
						break;
					} else if (near(tail, candTail)) {
						const revPts = [...cSeg.points].reverse();
						const revBulges = [...cSeg.bulges].reverse().map(b => -b);
						currentPoints.push(...revPts.slice(1));
						currentBulges.push(...revBulges);
						joinedEntities.push(cand);
						pool.splice(i, 1);
						progressed = true;
						break;
					} else if (near(head, candTail)) {
						currentPoints.unshift(...cSeg.points.slice(0, -1));
						currentBulges.unshift(...cSeg.bulges);
						joinedEntities.push(cand);
						pool.splice(i, 1);
						progressed = true;
						break;
					} else if (near(head, candHead)) {
						const revPts = [...cSeg.points].reverse();
						const revBulges = [...cSeg.bulges].reverse().map(b => -b);
						currentPoints.unshift(...revPts.slice(0, -1));
						currentBulges.unshift(...revBulges);
						joinedEntities.push(cand);
						pool.splice(i, 1);
						progressed = true;
						break;
					}
				}
			}

			if (joinedEntities.length > 0) {
				undoStack.push(snapshotPolyline(poly, origVertices));
				await ctx.transaction(async () => {
					rebuildPolyline(poly, currentPoints, currentBulges, poly.closed);
					for (const ent of joinedEntities) {
						ctx.database.erase(String(ent.objectId));
					}
				});
				ctx.message(`${joinedEntities.length} segments added to polyline`);
			} else {
				ctx.message('0 segments added to polyline');
			}
			continue;
		}

		if (key === 'EDIT VERTEX' || key === 'E') {
			let vertexIndex = 0;
			while (true) {
				const data = polylineVertices(poly);
				const n = data.points.length;
				if (n === 0) break;
				vertexIndex = ((vertexIndex % n) + n) % n;
				const currentPt = data.points[vertexIndex];
				ctx.message(`Vertex ${vertexIndex + 1} of ${n} at (${currentPt[0]}, ${currentPt[1]})`);

				const vOpt = await ctx.getKeyword(
					'Enter a vertex editing option [Next/Previous/Break/Insert/Move/Straighten/Tangent/Width/eXit] <Next>:',
					['Next', 'Previous', 'Break', 'Insert', 'Move', 'Straighten', 'Tangent', 'Width', 'eXit', 'N', 'P', 'B', 'I', 'M', 'S', 'T', 'W', 'X'],
					{ default: 'Next' },
				);

				const vKey = vOpt.toUpperCase();
				if (vKey === 'EXIT' || vKey === 'X') break;

				if (vKey === 'NEXT' || vKey === 'N') {
					vertexIndex = (vertexIndex + 1) % n;
				} else if (vKey === 'PREVIOUS' || vKey === 'P') {
					vertexIndex = (vertexIndex - 1 + n) % n;
				} else if (vKey === 'MOVE' || vKey === 'M') {
					const pt = await ctx.getPoint('Specify new location for marked vertex:');
					if (pt) {
						undoStack.push(snapshotPolyline(poly, origVertices));
						await ctx.transaction(async () => {
							const newPts = data.points.map(p => [p[0], p[1]] as Point2D);
							newPts[vertexIndex] = [pt.x, pt.y];
							rebuildPolyline(poly, newPts, data.bulges, poly.closed);
						});
					}
				} else if (vKey === 'INSERT' || vKey === 'I') {
					const pt = await ctx.getPoint('Specify location for new vertex:');
					if (pt) {
						undoStack.push(snapshotPolyline(poly, origVertices));
						await ctx.transaction(async () => {
							const newPts = data.points.map(p => [p[0], p[1]] as Point2D);
							const newBulges = [...data.bulges];
							newPts.splice(vertexIndex + 1, 0, [pt.x, pt.y]);
							newBulges.splice(vertexIndex, 0, 0);
							rebuildPolyline(poly, newPts, newBulges, poly.closed);
						});
					}
				} else if (vKey === 'STRAIGHTEN' || vKey === 'S') {
					undoStack.push(snapshotPolyline(poly, origVertices));
					await ctx.transaction(async () => {
						const newBulges = [...data.bulges];
						if (vertexIndex < newBulges.length) {
							newBulges[vertexIndex] = 0;
						}
						rebuildPolyline(poly, data.points as Point2D[], newBulges, poly.closed);
					});
				} else if (vKey === 'WIDTH' || vKey === 'W') {
					const sw = await ctx.getDouble('Enter starting width <0.0000>:');
					const ew = await ctx.getDouble('Enter ending width <0.0000>:');
					undoStack.push(snapshotPolyline(poly, origVertices));
					await ctx.transaction(async () => {
						const widths: [number, number][] = data.points.map(() => [-1, -1]);
						widths[vertexIndex] = [sw, ew];
						rebuildPolyline(poly, data.points as Point2D[], data.bulges, poly.closed, widths);
					});
				} else if (vKey === 'TANGENT' || vKey === 'T') {
					try {
						await ctx.getAngle('Specify direction of vertex tangent:');
					} catch {
						// Tangent direction skip ok
					}
				} else if (vKey === 'BREAK' || vKey === 'B') {
					ctx.message('Vertex break saved first vertex.');
					const bOpt = await ctx.getKeyword('Enter an option [Next/Previous/Go/eXit] <Next>:', ['Next', 'Previous', 'Go', 'eXit', 'N', 'P', 'G', 'X'], { default: 'Next' });
					if (bOpt.toUpperCase().startsWith('G')) {
						undoStack.push(snapshotPolyline(poly, origVertices));
						await ctx.transaction(async () => {
							const newPts = (data.points as Point2D[]).slice(0, vertexIndex + 1);
							const newBulges = data.bulges.slice(0, vertexIndex);
							rebuildPolyline(poly, newPts, newBulges, false);
						});
					}
				}
			}
			continue;
		}

		if (key === 'FIT' || key === 'F') {
			const data = polylineVertices(poly);
			origVertices = data.points.map(p => [p[0], p[1]]);
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				const fit = fitArcBulges(data.points as Point2D[], poly.closed);
				rebuildPolyline(poly, fit.points, fit.bulges, poly.closed);
			});
			continue;
		}

		if (key === 'SPLINE' || key === 'S') {
			const data = polylineVertices(poly);
			origVertices = data.points.map(p => [p[0], p[1]]);
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				const pts = bSplinePolyline(data.points as Point2D[], 2, 8, poly.closed);
				rebuildPolyline(poly, pts, undefined, poly.closed);
			});
			continue;
		}

		if (key === 'DECURVE' || key === 'D') {
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				if (origVertices && origVertices.length > 0) {
					rebuildPolyline(poly, origVertices, undefined, poly.closed);
				} else {
					const data = polylineVertices(poly);
					rebuildPolyline(poly, data.points as Point2D[], undefined, poly.closed);
				}
			});
			continue;
		}

		if (key === 'LTYPE GEN' || key === 'L') {
			ctx.message('Linetype generation (PLINEGEN) is not supported by the data model');
			continue;
		}

		if (key === 'REVERSE' || key === 'R') {
			undoStack.push(snapshotPolyline(poly, origVertices));
			await ctx.transaction(async () => {
				const data = polylineVertices(poly);
				const revPts = [...data.points].reverse() as Point2D[];
				const revBulges = [...data.bulges].reverse().map(b => -b);
				rebuildPolyline(poly, revPts, revBulges, poly.closed);
			});
			continue;
		}
	}
}

/**
 * AutoCAD SPLINEDIT command.
 */
export async function splineditCommand(ctx: CadCommandContext): Promise<void> {
	const entity = await ctx.getEntity('Select spline:');
	if (!(entity instanceof AcDbSpline)) {
		ctx.message('Selected entity is not a spline.');
		return;
	}

	if (isGenerated(entity, ctx)) {
		ctx.message('Entity is read-only (generated)');
		return;
	}

	const spline = entity;
	const undoStack: SplineSnapshot[] = [];

	const snapshotSpline = (): SplineSnapshot => {
		const geo = (spline as any)._geo;
		return {
			controlPoints: (geo.controlPoints ?? []).map((p: any) => ({ x: p.x, y: p.y, z: p.z ?? 0 })),
			knots: [...(geo.knots ?? [])],
			weights: geo.weights ? [...geo.weights] : undefined,
			degree: geo.degree ?? 3,
			closed: !!spline.closed,
			fitPoints: geo.fitPoints ? geo.fitPoints.map((p: any) => ({ x: p.x, y: p.y, z: p.z ?? 0 })) : undefined,
			fitTolerance: spline.fitTolerance,
		};
	};

	while (true) {
		const isClosed = spline.closed;
		const closeOpenKeyword = isClosed ? 'Open' : 'Close';
		const opt = await ctx.getKeyword(
			`Enter an option [${closeOpenKeyword}/Fit data/Edit vertex/convert to Polyline/Reverse/Undo/eXit] <eXit>:`,
			[
				closeOpenKeyword, 'Fit data', 'Edit vertex', 'convert to Polyline',
				'Reverse', 'Undo', 'eXit', 'C', 'O', 'F', 'E', 'P', 'R', 'U', 'X',
			],
			{ default: 'eXit' },
		);

		const key = opt.toUpperCase();
		if (key === 'EXIT' || key === 'X') break;

		if (key === 'UNDO' || key === 'U') {
			const prev = undoStack.pop();
			if (prev) {
				await ctx.transaction(async () => {
					spline.rebuild(prev.controlPoints, prev.knots, prev.weights, prev.degree, prev.closed);
					if (prev.fitTolerance !== undefined) spline.fitTolerance = prev.fitTolerance;
				});
				ctx.message('Undo');
			} else {
				ctx.message('Nothing to undo.');
			}
			continue;
		}

		if (key === 'CLOSE' || key === 'C') {
			undoStack.push(snapshotSpline());
			await ctx.transaction(async () => {
				spline.closed = true;
			});
			continue;
		}

		if (key === 'OPEN' || key === 'O') {
			undoStack.push(snapshotSpline());
			await ctx.transaction(async () => {
				spline.closed = false;
			});
			continue;
		}

		if (key === 'FIT DATA' || key === 'F') {
			const geo = (spline as any)._geo;
			const fitPoints: { x: number; y: number; z: number }[] | undefined = geo?.fitPoints;
			if (!fitPoints || fitPoints.length === 0) {
				ctx.message('Spline does not contain fit point data');
				continue;
			}

			const fOpt = await ctx.getKeyword(
				'Enter a fit data option [Add/Delete/Move/Tolerance/eXit] <eXit>:',
				['Add', 'Delete', 'Move', 'Tolerance', 'eXit', 'A', 'D', 'M', 'T', 'X'],
				{ default: 'eXit' },
			);

			const fKey = fOpt.toUpperCase();
			if (fKey === 'EXIT' || fKey === 'X') continue;

			if (fKey === 'TOLERANCE' || fKey === 'T') {
				const tol = await ctx.getDouble(`Enter fit tolerance <${spline.fitTolerance}>:`);
				undoStack.push(snapshotSpline());
				await ctx.transaction(async () => {
					spline.fitTolerance = tol;
				});
			} else if (fKey === 'ADD' || fKey === 'A') {
				const pt = await ctx.getPoint('Specify new fit point:');
				if (pt) {
					undoStack.push(snapshotSpline());
					await ctx.transaction(async () => {
						const newFits = [...fitPoints, { x: pt.x, y: pt.y, z: pt.z ?? 0 }];
						spline.rebuild(newFits, geo.knotParameterization ?? 'Uniform', geo.degree, spline.closed);
					});
				}
			} else if (fKey === 'DELETE' || fKey === 'D') {
				if (fitPoints.length > 2) {
					const idx = await ctx.getInteger(`Enter fit point index to delete (0 to ${fitPoints.length - 1}):`);
					if (idx >= 0 && idx < fitPoints.length) {
						undoStack.push(snapshotSpline());
						await ctx.transaction(async () => {
							const newFits = fitPoints.filter((_, i) => i !== idx);
							spline.rebuild(newFits, geo.knotParameterization ?? 'Uniform', geo.degree, spline.closed);
						});
					}
				} else {
					ctx.message('A spline requires at least 2 fit points.');
				}
			} else if (fKey === 'MOVE' || fKey === 'M') {
				const idx = await ctx.getInteger(`Enter fit point index to move (0 to ${fitPoints.length - 1}):`);
				if (idx >= 0 && idx < fitPoints.length) {
					const pt = await ctx.getPoint('Specify new location:');
					if (pt) {
						undoStack.push(snapshotSpline());
						await ctx.transaction(async () => {
							const newFits = fitPoints.map((p, i) => i === idx ? { x: pt.x, y: pt.y, z: pt.z ?? 0 } : p);
							spline.rebuild(newFits, geo.knotParameterization ?? 'Uniform', geo.degree, spline.closed);
						});
					}
				}
			}
			continue;
		}

		if (key === 'EDIT VERTEX' || key === 'E') {
			const geo = (spline as any)._geo;
			const cvs: { x: number; y: number; z: number }[] = (geo.controlPoints ?? []).map((p: any) => ({ x: p.x, y: p.y, z: p.z ?? 0 }));

			const vOpt = await ctx.getKeyword(
				'Enter a vertex option [Add/Delete/Move/Weight/eXit] <eXit>:',
				['Add', 'Delete', 'Move', 'Weight', 'eXit', 'A', 'D', 'M', 'W', 'X'],
				{ default: 'eXit' },
			);

			const vKey = vOpt.toUpperCase();
			if (vKey === 'EXIT' || vKey === 'X') continue;

			if (vKey === 'MOVE' || vKey === 'M') {
				const idx = await ctx.getInteger(`Enter control point index to move (0 to ${cvs.length - 1}):`);
				if (idx >= 0 && idx < cvs.length) {
					const pt = await ctx.getPoint('Specify new location:');
					if (pt) {
						undoStack.push(snapshotSpline());
						await ctx.transaction(async () => {
							cvs[idx] = { x: pt.x, y: pt.y, z: pt.z ?? 0 };
							spline.rebuild(cvs, geo.knots, geo.weights, geo.degree, spline.closed);
						});
					}
				}
			} else if (vKey === 'ADD' || vKey === 'A') {
				const pt = await ctx.getPoint('Specify new control point:');
				if (pt) {
					undoStack.push(snapshotSpline());
					await ctx.transaction(async () => {
						cvs.push({ x: pt.x, y: pt.y, z: pt.z ?? 0 });
						spline.rebuild(cvs, geo.knots, geo.weights, geo.degree, spline.closed);
					});
				}
			} else if (vKey === 'DELETE' || vKey === 'D') {
				const minCvs = (geo.degree ?? 3) + 1;
				if (cvs.length > minCvs) {
					const idx = await ctx.getInteger(`Enter control point index to delete (0 to ${cvs.length - 1}):`);
					if (idx >= 0 && idx < cvs.length) {
						undoStack.push(snapshotSpline());
						await ctx.transaction(async () => {
							const newCvs = cvs.filter((_, i) => i !== idx);
							spline.rebuild(newCvs, geo.knots, geo.weights, geo.degree, spline.closed);
						});
					}
				} else {
					ctx.message(`Spline degree ${geo.degree} requires at least ${minCvs} control points.`);
				}
			} else if (vKey === 'WEIGHT' || vKey === 'W') {
				const idx = await ctx.getInteger(`Enter control point index (0 to ${cvs.length - 1}):`);
				if (idx >= 0 && idx < cvs.length) {
					const curW = geo.weights && geo.weights[idx] !== undefined ? geo.weights[idx] : 1.0;
					const w = await ctx.getDouble(`Enter new weight <${curW}>:`);
					undoStack.push(snapshotSpline());
					await ctx.transaction(async () => {
						const weights = geo.weights ? [...geo.weights] : new Array(cvs.length).fill(1.0);
						weights[idx] = w;
						spline.rebuild(cvs, geo.knots, weights, geo.degree, spline.closed);
					});
				}
			}
			continue;
		}

		if (key === 'CONVERT TO POLYLINE' || key === 'P') {
			let prec = 10;
			try {
				prec = await ctx.getInteger('Enter precision (0 to 99) <10>:', { min: 0 });
			} catch {
				prec = 10;
			}
			prec = Math.max(0, Math.min(99, prec));
			const numPoints = Math.max(2, Math.round(prec * 2 + 10));

			const geo = (spline as any)._geo;
			const samples = geo.getPoints ? geo.getPoints(numPoints) : geo.tessellate();

			await ctx.transaction(async () => {
				const poly = new AcDbPolyline();
				samples.forEach((pt: any, i: number) => {
					poly.addVertexAt(i, new AcGePoint2d(pt.x, pt.y), 0);
				});
				poly.closed = spline.closed;
				copyProperties(spline, poly);
				ctx.database.replace(String(spline.objectId), poly);
			});
			ctx.message('Spline converted to polyline.');
			break;
		}

		if (key === 'REVERSE' || key === 'R') {
			undoStack.push(snapshotSpline());
			await ctx.transaction(async () => {
				const geo = (spline as any)._geo;
				const cvs = [...(geo.controlPoints ?? [])].reverse();
				const weights = geo.weights ? [...geo.weights].reverse() : undefined;
				spline.rebuild(cvs, geo.knots, weights, geo.degree, spline.closed);
			});
			continue;
		}
	}
}

export interface OverkillSettings {
	tolerance: number;
	ignoreLayer: boolean;
	ignoreColor: boolean;
	ignoreLinetype: boolean;
	ignoreLineweight: boolean;
	optimizePolylineSegments: boolean;
	combinePartialOverlap: boolean;
	combineEndToEnd: boolean;
}

/**
 * AutoCAD OVERKILL command.
 */
export async function overkillCommand(ctx: CadCommandContext): Promise<void> {
	const selection = await ctx.getSelection('Select objects:');
	if (selection.length === 0) return;

	const settings: OverkillSettings = {
		tolerance: 0.000001,
		ignoreLayer: false,
		ignoreColor: false,
		ignoreLinetype: false,
		ignoreLineweight: false,
		optimizePolylineSegments: true,
		combinePartialOverlap: true,
		combineEndToEnd: false,
	};

	let action = 'Proceed';
	try {
		action = await ctx.getKeyword(
			'OVERKILL: [Settings/Proceed] <Proceed>:',
			['Settings', 'Proceed', 'S', 'P'],
			{ default: 'Proceed' },
		);
	} catch {
		action = 'Proceed';
	}

	if (action.toUpperCase().startsWith('S')) {
		while (true) {
			const sOpt = await ctx.getKeyword(
				'Enter setting to modify [Tolerance/Ignore/Optimize/Combine/Endtoend/Done] <Done>:',
				['Tolerance', 'Ignore', 'Optimize', 'Combine', 'Endtoend', 'Done', 'T', 'I', 'O', 'C', 'E', 'D'],
				{ default: 'Done' },
			);
			const sKey = sOpt.toUpperCase();
			if (sKey === 'DONE' || sKey === 'D') break;

			if (sKey === 'TOLERANCE' || sKey === 'T') {
				settings.tolerance = await ctx.getDouble(`Enter tolerance <${settings.tolerance}>:`);
			} else if (sKey === 'IGNORE' || sKey === 'I') {
				const prop = await ctx.getKeyword(
					'Enter property to ignore [Layer/Color/Linetype/Lineweight/None/All] <None>:',
					['Layer', 'Color', 'Linetype', 'Lineweight', 'None', 'All'],
					{ default: 'None' },
				);
				const pKey = prop.toUpperCase();
				if (pKey === 'LAYER') settings.ignoreLayer = !settings.ignoreLayer;
				else if (pKey === 'COLOR') settings.ignoreColor = !settings.ignoreColor;
				else if (pKey === 'LINETYPE') settings.ignoreLinetype = !settings.ignoreLinetype;
				else if (pKey === 'LINEWEIGHT') settings.ignoreLineweight = !settings.ignoreLineweight;
				else if (pKey === 'ALL') {
					settings.ignoreLayer = true;
					settings.ignoreColor = true;
					settings.ignoreLinetype = true;
					settings.ignoreLineweight = true;
				} else if (pKey === 'NONE') {
					settings.ignoreLayer = false;
					settings.ignoreColor = false;
					settings.ignoreLinetype = false;
					settings.ignoreLineweight = false;
				}
			} else if (sKey === 'OPTIMIZE' || sKey === 'O') {
				const ans = await ctx.getKeyword(
					`Optimize segments within polylines [ON/OFF] <${settings.optimizePolylineSegments ? 'ON' : 'OFF'}>:`,
					['ON', 'OFF'],
					{ default: settings.optimizePolylineSegments ? 'ON' : 'OFF' },
				);
				settings.optimizePolylineSegments = ans.toUpperCase() === 'ON';
			} else if (sKey === 'COMBINE' || sKey === 'C') {
				const ans = await ctx.getKeyword(
					`Combine co-linear objects that partially overlap [ON/OFF] <${settings.combinePartialOverlap ? 'ON' : 'OFF'}>:`,
					['ON', 'OFF'],
					{ default: settings.combinePartialOverlap ? 'ON' : 'OFF' },
				);
				settings.combinePartialOverlap = ans.toUpperCase() === 'ON';
			} else if (sKey === 'ENDTOEND' || sKey === 'E') {
				const ans = await ctx.getKeyword(
					`Combine co-linear objects end to end [ON/OFF] <${settings.combineEndToEnd ? 'ON' : 'OFF'}>:`,
					['ON', 'OFF'],
					{ default: settings.combineEndToEnd ? 'ON' : 'OFF' },
				);
				settings.combineEndToEnd = ans.toUpperCase() === 'ON';
			}
		}
	}

	let duplicatesDeleted = 0;
	let overlappingDeleted = 0;

	await ctx.transaction(async () => {
		const tol = settings.tolerance;
		const pool: AcDbEntity[] = [];

		for (const ent of selection) {
			if (isGenerated(ent, ctx)) continue;
			pool.push(ent);
		}

		// 1. Zero-length lines and zero-radius circles
		for (let i = pool.length - 1; i >= 0; i--) {
			const ent = pool[i];
			if (ent instanceof AcDbLine) {
				const len = Math.hypot(ent.endPoint.x - ent.startPoint.x, ent.endPoint.y - ent.startPoint.y);
				if (len <= tol) {
					ctx.database.erase(String(ent.objectId));
					pool.splice(i, 1);
					duplicatesDeleted++;
				}
			} else if (ent instanceof AcDbCircle) {
				if (ent.radius <= tol) {
					ctx.database.erase(String(ent.objectId));
					pool.splice(i, 1);
					duplicatesDeleted++;
				}
			}
		}

		// 2. Optimize segments within polylines
		if (settings.optimizePolylineSegments) {
			for (const ent of pool) {
				if (ent instanceof AcDbPolyline) {
					const data = polylineVertices(ent);
					const res = removeDuplicateVertices(data.points as Point2D[], data.bulges, ent.closed, tol);
					if (res.removedCount > 0) {
						rebuildPolyline(ent, res.points, res.bulges, ent.closed);
						overlappingDeleted += res.removedCount;
					}
				}
			}
		}

		// 3. Exact duplicates
		const sameProps = (a: AcDbEntity, b: AcDbEntity): boolean => {
			if (!settings.ignoreLayer && a.layer !== b.layer) return false;
			if (!settings.ignoreColor && !(a.color === b.color || a.color?.equals?.(b.color))) return false;
			if (!settings.ignoreLinetype && a.lineType !== b.lineType) return false;
			if (!settings.ignoreLineweight && a.lineWeight !== b.lineWeight) return false;
			return true;
		};

		const sameGeometry = (a: AcDbEntity, b: AcDbEntity): boolean => {
			if (a.dxfTypeName !== b.dxfTypeName) return false;

			if (a instanceof AcDbLine && b instanceof AcDbLine) {
				const aS = [a.startPoint.x, a.startPoint.y];
				const aE = [a.endPoint.x, a.endPoint.y];
				const bS = [b.startPoint.x, b.startPoint.y];
				const bE = [b.endPoint.x, b.endPoint.y];

				const matchDirect = Math.hypot(aS[0] - bS[0], aS[1] - bS[1]) <= tol && Math.hypot(aE[0] - bE[0], aE[1] - bE[1]) <= tol;
				const matchReverse = Math.hypot(aS[0] - bE[0], aS[1] - bE[1]) <= tol && Math.hypot(aE[0] - bS[0], aE[1] - bS[1]) <= tol;
				return matchDirect || matchReverse;
			}

			if (a instanceof AcDbCircle && b instanceof AcDbCircle) {
				const matchCenter = Math.hypot(a.center.x - b.center.x, a.center.y - b.center.y) <= tol;
				const matchRadius = Math.abs(a.radius - b.radius) <= tol;
				return matchCenter && matchRadius;
			}

			if (a instanceof AcDbArc && b instanceof AcDbArc) {
				const matchCenter = Math.hypot(a.center.x - b.center.x, a.center.y - b.center.y) <= tol;
				const matchRadius = Math.abs(a.radius - b.radius) <= tol;
				const matchStart = Math.abs(a.startAngle - b.startAngle) <= tol;
				const matchEnd = Math.abs(a.endAngle - b.endAngle) <= tol;
				return matchCenter && matchRadius && matchStart && matchEnd;
			}

			if (a instanceof AcDbPolyline && b instanceof AcDbPolyline) {
				if (a.closed !== b.closed) return false;
				const vA = polylineVertices(a);
				const vB = polylineVertices(b);
				if (vA.points.length !== vB.points.length) return false;

				for (let i = 0; i < vA.points.length; i++) {
					if (Math.hypot(vA.points[i][0] - vB.points[i][0], vA.points[i][1] - vB.points[i][1]) > tol) {
						return false;
					}
					const bA = vA.bulges[i] ?? 0;
					const bB = vB.bulges[i] ?? 0;
					if (Math.abs(bA - bB) > tol) return false;
				}
				return true;
			}

			return false;
		};

		for (let i = 0; i < pool.length; i++) {
			for (let j = pool.length - 1; j > i; j--) {
				const entA = pool[i];
				const entB = pool[j];
				if (sameProps(entA, entB) && sameGeometry(entA, entB)) {
					ctx.database.erase(String(entB.objectId));
					pool.splice(j, 1);
					duplicatesDeleted++;
				}
			}
		}

		// 4. Combine collinear lines
		if (settings.combinePartialOverlap || settings.combineEndToEnd) {
			const lines = pool.filter((e): e is AcDbLine => e instanceof AcDbLine);
			type LineWithEntity = CollinearLine<AcDbLine>;

			const lineData: LineWithEntity[] = lines.map(l => ({
				start: [l.startPoint.x, l.startPoint.y],
				end: [l.endPoint.x, l.endPoint.y],
				data: l,
			}));

			// Group by matching properties if properties not ignored
			const groups: LineWithEntity[][] = [];
			for (const l of lineData) {
				let foundGroup = false;
				for (const g of groups) {
					if (sameProps(g[0].data!, l.data!)) {
						g.push(l);
						foundGroup = true;
						break;
					}
				}
				if (!foundGroup) groups.push([l]);
			}

			for (const group of groups) {
				if (group.length <= 1) continue;

				let changed = true;
				while (changed) {
					changed = false;
					for (let i = 0; i < group.length; i++) {
						for (let j = i + 1; j < group.length; j++) {
							const lineA = group[i];
							const lineB = group[j];

							const res = mergeCollinearLines([lineA, lineB], {
								tolerance: tol,
								combinePartialOverlap: settings.combinePartialOverlap,
								combineEndToEnd: settings.combineEndToEnd,
							});

							if (res.merged.length === 1) {
								const merged = res.merged[0];
								const entA = lineA.data!;
								const entB = lineB.data!;

								entA.startPoint = new AcGePoint3d(merged.start[0], merged.start[1], entA.startPoint.z);
								entA.endPoint = new AcGePoint3d(merged.end[0], merged.end[1], entA.endPoint.z);
								ctx.database.erase(String(entB.objectId));

								lineA.start = merged.start;
								lineA.end = merged.end;
								group.splice(j, 1);

								overlappingDeleted++;
								changed = true;
								break;
							}
						}
						if (changed) break;
					}
				}
			}
		}
	});

	ctx.message(`${duplicatesDeleted} duplicate(s) deleted, ${overlappingDeleted} overlapping object(s) or segment(s) deleted`);
}

/**
 * Registers PEDIT, SPLINEDIT, and OVERKILL commands.
 */
export function registerPolyEditCommands(reg: typeof registerCommand = registerCommand): void {
	reg('PEDIT', peditCommand, { aliases: ['PE'] });
	reg('SPLINEDIT', splineditCommand);
	reg('OVERKILL', overkillCommand);
}
