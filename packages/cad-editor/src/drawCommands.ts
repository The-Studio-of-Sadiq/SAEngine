/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbPolyline,
	AcGePoint2d, AcGePoint3d,
} from '@mlightcad/data-model';
import {
	CadCommandContext, CadPoint3, registerCommand,
} from './commands.js';
import { polylineVertices } from './entityAccess.js';
import {
	arcCenterStartEnd, arcContinue, arcStartCenterAngle, arcStartCenterEnd,
	arcStartCenterLength, arcStartEndAngle, arcStartEndDirection, arcStartEndRadius,
	CircleGeom, circle2P, circle3P, circleTTR, circleTTT,
	donut, LineSegmentGeom, normalizeAngleRad, Point2D,
	polygonCircumscribed, polygonEdge, polygonInscribed, PolylineGeom,
	rectangleArea, rectangleChamfer, rectangleDimensions, rectangleFillet,
} from './drawGeometry.js';

function extractLineOrCircle(entity: AcDbEntity, pickPt?: CadPoint3): LineSegmentGeom | CircleGeom {
	if (entity instanceof AcDbLine) {
		return { start: [entity.startPoint.x, entity.startPoint.y], end: [entity.endPoint.x, entity.endPoint.y] };
	}
	if (entity instanceof AcDbCircle) {
		return { center: [entity.center.x, entity.center.y], radius: entity.radius };
	}
	if (entity instanceof AcDbArc) {
		return { center: [entity.center.x, entity.center.y], radius: entity.radius };
	}
	if (entity instanceof AcDbPolyline) {
		const { points, closed } = polylineVertices(entity);
		const n = points.length;
		const segCount = closed ? n : n - 1;
		if (segCount <= 0) throw new Error('Polyline has no segments');
		let bestIdx = 0;
		if (pickPt) {
			let bestDist = Infinity;
			for (let i = 0; i < segCount; i++) {
				const pA = points[i];
				const pB = points[(i + 1) % n];
				const midX = (pA[0] + pB[0]) / 2, midY = (pA[1] + pB[1]) / 2;
				const dist = Math.hypot(midX - pickPt.x, midY - pickPt.y);
				if (dist < bestDist) {
					bestDist = dist;
					bestIdx = i;
				}
			}
		}
		return { start: points[bestIdx], end: points[(bestIdx + 1) % n] };
	}
	throw new Error('Selected entity must be a Line, Circle, Arc, or Polyline');
}

function createPolyline(geom: PolylineGeom): AcDbPolyline {
	const poly = new AcDbPolyline();
	const width = geom.constantWidth ?? -1;
	for (let i = 0; i < geom.points.length; i++) {
		const pt = geom.points[i];
		const bulge = geom.bulges[i] ?? 0;
		poly.addVertexAt(i, new AcGePoint2d(pt[0], pt[1]), bulge, width, width);
	}
	poly.closed = geom.closed;
	return poly;
}

// -----------------------------------------------------------------------------
// CIRCLE COMMAND & VARIANTS
// -----------------------------------------------------------------------------

async function runTtrFlow(ctx: CadCommandContext): Promise<void> {
	const r1 = await ctx.getEntityPick('Specify point on object for first tangent of circle:');
	if (r1.status !== 'ok' || !r1.entity) return;
	const r2 = await ctx.getEntityPick('Specify point on object for second tangent of circle:');
	if (r2.status !== 'ok' || !r2.entity) return;
	const radius = await ctx.getDouble('Specify radius of circle:');

	const e1 = extractLineOrCircle(r1.entity, r1.point);
	const e2 = extractLineOrCircle(r2.entity, r2.point);
	const pick1: Point2D = r1.point ? [r1.point.x, r1.point.y] : ('start' in e1 ? e1.start : e1.center);
	const pick2: Point2D = r2.point ? [r2.point.x, r2.point.y] : ('start' in e2 ? e2.start : e2.center);

	const geom = circleTTR(e1, e2, radius, pick1, pick2);
	const circle = new AcDbCircle();
	circle.center = new AcGePoint3d(geom.center[0], geom.center[1], 0);
	circle.radius = geom.radius;
	ctx.database.add(circle);
}

async function runTttFlow(ctx: CadCommandContext): Promise<void> {
	const r1 = await ctx.getEntityPick('Select first line:');
	if (r1.status !== 'ok' || !r1.entity) return;
	const r2 = await ctx.getEntityPick('Select second line:');
	if (r2.status !== 'ok' || !r2.entity) return;
	const r3 = await ctx.getEntityPick('Select third line:');
	if (r3.status !== 'ok' || !r3.entity) return;

	const l1 = extractLineOrCircle(r1.entity, r1.point);
	const l2 = extractLineOrCircle(r2.entity, r2.point);
	const l3 = extractLineOrCircle(r3.entity, r3.point);
	if (!('start' in l1) || !('start' in l2) || !('start' in l3)) {
		throw new Error('All three objects for TTT must be lines');
	}

	const geom = circleTTT(l1, l2, l3);
	const circle = new AcDbCircle();
	circle.center = new AcGePoint3d(geom.center[0], geom.center[1], 0);
	circle.radius = geom.radius;
	ctx.database.add(circle);
}

/** Fuller CIRCLE command offering Center, Diameter, 2P, 3P, TTR, and TTT options. */
export async function circleVarCommand(ctx: CadCommandContext): Promise<void> {
	const pickRes = await ctx.getPointPick('Specify center point for circle or [3P/2P/Ttr (tan tan radius)/TTT (tan tan tan)]:', {
		keywords: ['3P', '2P', 'TTR', 'TTT'],
	});

	if (pickRes.status === 'keyword') {
		const kw = pickRes.keyword?.toUpperCase();
		if (kw === '3P') {
			const p1 = await ctx.getPoint('Specify first point on circle:');
			const p2 = await ctx.getPoint('Specify second point on circle:', { base: p1 });
			const p3 = await ctx.getPoint('Specify third point on circle:', { base: p2 });
			const geom = circle3P([p1.x, p1.y], [p2.x, p2.y], [p3.x, p3.y]);
			const c = new AcDbCircle();
			c.center = new AcGePoint3d(geom.center[0], geom.center[1], p1.z ?? 0);
			c.radius = geom.radius;
			ctx.database.add(c);
			return;
		}
		if (kw === '2P') {
			const p1 = await ctx.getPoint("Specify first end point of circle's diameter:");
			const p2 = await ctx.getPoint("Specify second end point of circle's diameter:", { base: p1 });
			const geom = circle2P([p1.x, p1.y], [p2.x, p2.y]);
			const c = new AcDbCircle();
			c.center = new AcGePoint3d(geom.center[0], geom.center[1], p1.z ?? 0);
			c.radius = geom.radius;
			ctx.database.add(c);
			return;
		}
		if (kw === 'TTR') {
			await runTtrFlow(ctx);
			return;
		}
		if (kw === 'TTT') {
			await runTttFlow(ctx);
			return;
		}
	}

	if (pickRes.status === 'ok' && pickRes.point) {
		const centerPt = pickRes.point;
		const radRes = await ctx.getPointPick('Specify radius of circle or [Diameter]:', {
			base: centerPt,
			keywords: ['Diameter'],
		});

		let radius: number;
		if (radRes.status === 'keyword' && radRes.keyword?.toUpperCase() === 'DIAMETER') {
			const dia = await ctx.getDouble('Specify diameter of circle:');
			radius = dia / 2;
		} else if (radRes.point) {
			radius = Math.hypot(radRes.point.x - centerPt.x, radRes.point.y - centerPt.y);
		} else {
			radius = await ctx.getDistance('Specify radius of circle:', { base: centerPt });
		}

		const c = new AcDbCircle();
		c.center = new AcGePoint3d(centerPt.x, centerPt.y, centerPt.z ?? 0);
		c.radius = radius;
		ctx.database.add(c);
	}
}

// -----------------------------------------------------------------------------
// ARC COMMAND & VARIANTS
// -----------------------------------------------------------------------------

/** Fuller ARC command supporting SCE, SCA, SCL, SEA, SED, SER, CSE, and Continue. */
export async function arcVarCommand(ctx: CadCommandContext): Promise<void> {
	const startRes = await ctx.getPointPick('Specify start point of arc or [Center/Continue]:', {
		keywords: ['Center', 'Continue'],
		allowNone: true,
	});

	if (startRes.status === 'none' || (startRes.status === 'keyword' && startRes.keyword?.toUpperCase() === 'CONTINUE')) {
		// Continue tangent to the last line or arc
		const allEntities = ctx.database.all();
		let lastEntity: AcDbEntity | undefined;
		for (let i = allEntities.length - 1; i >= 0; i--) {
			if (allEntities[i] instanceof AcDbLine || allEntities[i] instanceof AcDbArc) {
				lastEntity = allEntities[i];
				break;
			}
		}

		if (!lastEntity) {
			ctx.message('No previous line or arc to continue from');
			return;
		}

		let startPt: Point2D;
		let tangentAngle: number;
		if (lastEntity instanceof AcDbLine) {
			startPt = [lastEntity.endPoint.x, lastEntity.endPoint.y];
			tangentAngle = Math.atan2(lastEntity.endPoint.y - lastEntity.startPoint.y, lastEntity.endPoint.x - lastEntity.startPoint.x);
		} else {
			const arc = lastEntity as AcDbArc;
			startPt = [arc.center.x + arc.radius * Math.cos(arc.endAngle), arc.center.y + arc.radius * Math.sin(arc.endAngle)];
			tangentAngle = arc.endAngle + Math.PI / 2;
		}

		const endPt = await ctx.getPoint('Specify end point of arc:', { base: new AcGePoint3d(startPt[0], startPt[1], 0) });
		const geom = arcContinue(startPt, tangentAngle, [endPt.x, endPt.y]);
		const arc = new AcDbArc();
		arc.center = new AcGePoint3d(geom.center[0], geom.center[1], 0);
		arc.radius = geom.radius;
		arc.startAngle = geom.startAngle;
		arc.endAngle = geom.endAngle;
		ctx.database.add(arc);
		return;
	}

	if (startRes.status === 'keyword' && startRes.keyword?.toUpperCase() === 'CENTER') {
		// Center-first branch (Center-Start-End / Angle / Length)
		const centerPt = await ctx.getPoint('Specify center point of arc:');
		const startPt = await ctx.getPoint('Specify start point of arc:', { base: centerPt });
		const opt = await ctx.getPointPick('Specify end point of arc or [Angle/chord Length]:', {
			base: centerPt,
			keywords: ['Angle', 'Length'],
		});

		let geom: ReturnType<typeof arcStartCenterEnd>;
		if (opt.status === 'keyword' && opt.keyword?.toUpperCase() === 'ANGLE') {
			const angle = await ctx.getAngle('Specify included angle:', { base: centerPt });
			geom = arcStartCenterAngle([startPt.x, startPt.y], [centerPt.x, centerPt.y], angle);
		} else if (opt.status === 'keyword' && opt.keyword?.toUpperCase() === 'LENGTH') {
			const chord = await ctx.getDistance('Specify chord length:', { base: startPt });
			geom = arcStartCenterLength([startPt.x, startPt.y], [centerPt.x, centerPt.y], chord);
		} else if (opt.point) {
			geom = arcCenterStartEnd([centerPt.x, centerPt.y], [startPt.x, startPt.y], [opt.point.x, opt.point.y]);
		} else {
			return;
		}

		const arc = new AcDbArc();
		arc.center = new AcGePoint3d(geom.center[0], geom.center[1], centerPt.z ?? 0);
		arc.radius = geom.radius;
		arc.startAngle = geom.startAngle;
		arc.endAngle = geom.endAngle;
		ctx.database.add(arc);
		return;
	}

	if (startRes.status === 'ok' && startRes.point) {
		const startPt = startRes.point;
		const opt2 = await ctx.getPointPick('Specify second point of arc or [Center/End]:', {
			base: startPt,
			keywords: ['Center', 'End'],
		});

		if (opt2.status === 'keyword' && opt2.keyword?.toUpperCase() === 'CENTER') {
			const centerPt = await ctx.getPoint('Specify center point of arc:', { base: startPt });
			const opt = await ctx.getPointPick('Specify end point of arc or [Angle/chord Length]:', {
				base: centerPt,
				keywords: ['Angle', 'Length'],
			});

			let geom: ReturnType<typeof arcStartCenterEnd>;
			if (opt.status === 'keyword' && opt.keyword?.toUpperCase() === 'ANGLE') {
				const angle = await ctx.getAngle('Specify included angle:', { base: centerPt });
				geom = arcStartCenterAngle([startPt.x, startPt.y], [centerPt.x, centerPt.y], angle);
			} else if (opt.status === 'keyword' && opt.keyword?.toUpperCase() === 'LENGTH') {
				const chord = await ctx.getDistance('Specify chord length:', { base: startPt });
				geom = arcStartCenterLength([startPt.x, startPt.y], [centerPt.x, centerPt.y], chord);
			} else if (opt.point) {
				geom = arcStartCenterEnd([startPt.x, startPt.y], [centerPt.x, centerPt.y], [opt.point.x, opt.point.y]);
			} else {
				return;
			}

			const arc = new AcDbArc();
			arc.center = new AcGePoint3d(geom.center[0], geom.center[1], startPt.z ?? 0);
			arc.radius = geom.radius;
			arc.startAngle = geom.startAngle;
			arc.endAngle = geom.endAngle;
			ctx.database.add(arc);
			return;
		}

		if (opt2.status === 'keyword' && opt2.keyword?.toUpperCase() === 'END') {
			const endPt = await ctx.getPoint('Specify end point of arc:', { base: startPt });
			const opt = await ctx.getKeyword('Specify parameter [Angle/Direction/Radius]:', ['Angle', 'Direction', 'Radius'], {
				default: 'Angle',
			});

			let geom: ReturnType<typeof arcStartEndAngle>;
			if (opt.toUpperCase() === 'ANGLE') {
				const angle = await ctx.getAngle('Specify included angle:');
				geom = arcStartEndAngle([startPt.x, startPt.y], [endPt.x, endPt.y], angle);
			} else if (opt.toUpperCase() === 'DIRECTION') {
				const dir = await ctx.getAngle('Specify tangent direction for the start point of arc:', { base: startPt });
				geom = arcStartEndDirection([startPt.x, startPt.y], [endPt.x, endPt.y], dir);
			} else {
				const rad = await ctx.getDistance('Specify radius of arc:');
				geom = arcStartEndRadius([startPt.x, startPt.y], [endPt.x, endPt.y], rad);
			}

			const arc = new AcDbArc();
			arc.center = new AcGePoint3d(geom.center[0], geom.center[1], startPt.z ?? 0);
			arc.radius = geom.radius;
			arc.startAngle = geom.startAngle;
			arc.endAngle = geom.endAngle;
			ctx.database.add(arc);
			return;
		}

		if (opt2.status === 'ok' && opt2.point) {
			// 3-point arc: start, second, third
			const secondPt = opt2.point;
			const endPt = await ctx.getPoint('Specify end point of arc:', { base: secondPt });
			const cg = circle3P([startPt.x, startPt.y], [secondPt.x, secondPt.y], [endPt.x, endPt.y]);
			const a1 = normalizeAngleRad(Math.atan2(startPt.y - cg.center[1], startPt.x - cg.center[0]));
			const a2 = normalizeAngleRad(Math.atan2(secondPt.y - cg.center[1], secondPt.x - cg.center[0]));
			const a3 = normalizeAngleRad(Math.atan2(endPt.y - cg.center[1], endPt.x - cg.center[0]));

			const sweep13 = ((a3 - a1) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
			const sweep12 = ((a2 - a1) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);

			let startAngle = a1;
			let endAngle = a3;
			if (sweep12 > sweep13) {
				startAngle = a3;
				endAngle = a1;
			}

			const arc = new AcDbArc();
			arc.center = new AcGePoint3d(cg.center[0], cg.center[1], startPt.z ?? 0);
			arc.radius = cg.radius;
			arc.startAngle = startAngle;
			arc.endAngle = endAngle;
			ctx.database.add(arc);
		}
	}
}

// -----------------------------------------------------------------------------
// RECTANG COMMAND & VARIANTS
// -----------------------------------------------------------------------------

/** Fuller RECTANG command supporting Chamfer, Fillet, Dimensions, Area, and Rotation. */
export async function rectangVarCommand(ctx: CadCommandContext): Promise<void> {
	let filletRadius = 0;
	let chamferD1 = 0;
	let chamferD2 = 0;
	let rotation = 0;
	let firstCorner: CadPoint3 | undefined;

	for (;;) {
		const promptStr = 'Specify first corner point or [Chamfer/Fillet]:';
		const pick = await ctx.getPointPick(promptStr, { keywords: ['Chamfer', 'Fillet'] });
		if (pick.status === 'cancel' || pick.status === 'none') return;
		if (pick.status === 'keyword') {
			const kw = pick.keyword?.toUpperCase();
			if (kw === 'CHAMFER') {
				chamferD1 = await ctx.getDistance('Specify first chamfer distance for rectangles:');
				chamferD2 = await ctx.getDistance('Specify second chamfer distance for rectangles:');
				filletRadius = 0;
				continue;
			}
			if (kw === 'FILLET') {
				filletRadius = await ctx.getDistance('Specify fillet radius for rectangles:');
				chamferD1 = 0;
				chamferD2 = 0;
				continue;
			}
		}
		if (pick.status === 'ok' && pick.point) {
			firstCorner = pick.point;
			break;
		}
	}

	const secondPick = await ctx.getPointPick('Specify other corner point or [Area/Dimensions/Rotation]:', {
		base: firstCorner,
		keywords: ['Area', 'Dimensions', 'Rotation'],
	});

	if (secondPick.status === 'keyword' && secondPick.keyword?.toUpperCase() === 'ROTATION') {
		rotation = await ctx.getAngle('Specify rotation angle or [Pick points] <0>:', { base: firstCorner });
		const nextPick = await ctx.getPointPick('Specify other corner point or [Area/Dimensions]:', {
			base: firstCorner,
			keywords: ['Area', 'Dimensions'],
		});
		if (nextPick.status === 'keyword' && nextPick.keyword?.toUpperCase() === 'DIMENSIONS') {
			const len = await ctx.getDistance('Specify length for rectangles:', { base: firstCorner });
			const w = await ctx.getDistance('Specify width for rectangles:', { base: firstCorner });
			const geom = filletRadius > 0
				? rectangleFillet([firstCorner.x, firstCorner.y], [firstCorner.x + len, firstCorner.y + w], filletRadius, rotation)
				: (chamferD1 > 0 || chamferD2 > 0)
					? rectangleChamfer([firstCorner.x, firstCorner.y], [firstCorner.x + len, firstCorner.y + w], chamferD1, chamferD2, rotation)
					: rectangleDimensions([firstCorner.x, firstCorner.y], len, w, rotation);
			ctx.database.add(createPolyline(geom));
			return;
		}
		if (nextPick.status === 'keyword' && nextPick.keyword?.toUpperCase() === 'AREA') {
			const area = await ctx.getDouble('Enter area of rectangle in current units:');
			const opt = await ctx.getKeyword('Calculate rectangle dimensions based on [Length/Width] <Length>:', ['Length', 'Width'], { default: 'Length' });
			const known = opt.toUpperCase() === 'WIDTH'
				? { width: await ctx.getDistance('Enter rectangle width:', { base: firstCorner }) }
				: { length: await ctx.getDistance('Enter rectangle length:', { base: firstCorner }) };
			const geom = rectangleArea([firstCorner.x, firstCorner.y], area, known, rotation);
			ctx.database.add(createPolyline(geom));
			return;
		}
		if (nextPick.point) {
			const geom = filletRadius > 0
				? rectangleFillet([firstCorner.x, firstCorner.y], [nextPick.point.x, nextPick.point.y], filletRadius, rotation)
				: (chamferD1 > 0 || chamferD2 > 0)
					? rectangleChamfer([firstCorner.x, firstCorner.y], [nextPick.point.x, nextPick.point.y], chamferD1, chamferD2, rotation)
					: rectangleFillet([firstCorner.x, firstCorner.y], [nextPick.point.x, nextPick.point.y], 0, rotation);
			ctx.database.add(createPolyline(geom));
			return;
		}
	}

	if (secondPick.status === 'keyword' && secondPick.keyword?.toUpperCase() === 'DIMENSIONS') {
		const len = await ctx.getDistance('Specify length for rectangles:', { base: firstCorner });
		const w = await ctx.getDistance('Specify width for rectangles:', { base: firstCorner });
		const geom = filletRadius > 0
			? rectangleFillet([firstCorner.x, firstCorner.y], [firstCorner.x + len, firstCorner.y + w], filletRadius, rotation)
			: (chamferD1 > 0 || chamferD2 > 0)
				? rectangleChamfer([firstCorner.x, firstCorner.y], [firstCorner.x + len, firstCorner.y + w], chamferD1, chamferD2, rotation)
				: rectangleDimensions([firstCorner.x, firstCorner.y], len, w, rotation);
		ctx.database.add(createPolyline(geom));
		return;
	}

	if (secondPick.status === 'keyword' && secondPick.keyword?.toUpperCase() === 'AREA') {
		const area = await ctx.getDouble('Enter area of rectangle in current units:');
		const opt = await ctx.getKeyword('Calculate rectangle dimensions based on [Length/Width] <Length>:', ['Length', 'Width'], { default: 'Length' });
		const known = opt.toUpperCase() === 'WIDTH'
			? { width: await ctx.getDistance('Enter rectangle width:', { base: firstCorner }) }
			: { length: await ctx.getDistance('Enter rectangle length:', { base: firstCorner }) };
		const geom = rectangleArea([firstCorner.x, firstCorner.y], area, known, rotation);
		ctx.database.add(createPolyline(geom));
		return;
	}

	if (secondPick.point) {
		const geom = filletRadius > 0
			? rectangleFillet([firstCorner.x, firstCorner.y], [secondPick.point.x, secondPick.point.y], filletRadius, rotation)
			: (chamferD1 > 0 || chamferD2 > 0)
				? rectangleChamfer([firstCorner.x, firstCorner.y], [secondPick.point.x, secondPick.point.y], chamferD1, chamferD2, rotation)
				: rectangleFillet([firstCorner.x, firstCorner.y], [secondPick.point.x, secondPick.point.y], 0, rotation);
		ctx.database.add(createPolyline(geom));
	}
}

// -----------------------------------------------------------------------------
// POLYGON COMMAND & VARIANTS
// -----------------------------------------------------------------------------

/** Fuller POLYGON command supporting sides, Inscribed, Circumscribed, and Edge. */
export async function polygonVarCommand(ctx: CadCommandContext): Promise<void> {
	const sides = await ctx.getInteger('Enter number of sides <4>:', { min: 3 });
	const pick = await ctx.getPointPick('Specify center of polygon or [Edge]:', { keywords: ['Edge'] });

	if (pick.status === 'keyword' && pick.keyword?.toUpperCase() === 'EDGE') {
		const p1 = await ctx.getPoint('Specify first endpoint of edge:');
		const p2 = await ctx.getPoint('Specify second endpoint of edge:', { base: p1 });
		const geom = polygonEdge([p1.x, p1.y], [p2.x, p2.y], sides);
		ctx.database.add(createPolyline(geom));
		return;
	}

	if (pick.status === 'ok' && pick.point) {
		const centerPt = pick.point;
		const mode = await ctx.getKeyword(
			'Enter an option [Inscribed in circle/Circumscribed about circle] <I>:',
			['Inscribed', 'Circumscribed'],
			{ default: 'Inscribed' },
		);
		const radPt = await ctx.getPoint('Specify radius of circle:', { base: centerPt });
		const radius = Math.hypot(radPt.x - centerPt.x, radPt.y - centerPt.y);
		const startAngle = Math.atan2(radPt.y - centerPt.y, radPt.x - centerPt.x);

		const geom = mode.toUpperCase().startsWith('C')
			? polygonCircumscribed([centerPt.x, centerPt.y], radius, sides, startAngle)
			: polygonInscribed([centerPt.x, centerPt.y], radius, sides, startAngle);

		ctx.database.add(createPolyline(geom));
	}
}

// -----------------------------------------------------------------------------
// DONUT COMMAND (DO)
// -----------------------------------------------------------------------------

/** DONUT / DO command creating closed LWPOLYLINEs of two bulge-1 segments with constant width. */
export async function donutCommand(ctx: CadCommandContext): Promise<void> {
	const inDia = await ctx.getDouble('Specify inside diameter of donut <0.0>:');
	const outDia = await ctx.getDouble('Specify outside diameter of donut <10.0>:');

	for (;;) {
		const centerPt = await ctx.getPoint('Specify center of donut or <exit>:', { allowNone: true });
		if (!centerPt) break;
		const geom = donut([centerPt.x, centerPt.y], inDia, outDia);
		ctx.database.add(createPolyline(geom));
	}
}

// -----------------------------------------------------------------------------
// REGISTRATION
// -----------------------------------------------------------------------------

/** Register SAEngine's draw command variants into the CAD editor command stack. */
export function registerDrawCommands(): void {
	// DONUT is not built into the viewer library, so register directly under DONUT/DO
	registerCommand('DONUT', donutCommand, { aliases: ['DO'] });

	// Circle variants
	registerCommand('CIRCLEX', circleVarCommand, { aliases: ['CIRCLE2'] });
	registerCommand('TTR', runTtrFlow);
	registerCommand('TTT', runTttFlow);

	// Arc variants
	registerCommand('ARCX', arcVarCommand, { aliases: ['ARC2'] });

	// Rectangle variants
	registerCommand('RECTANGX', rectangVarCommand, { aliases: ['RECT2', 'RECTANGLE2'] });

	// Polygon variants
	registerCommand('POLYGONX', polygonVarCommand, { aliases: ['POLYGON2', 'POL2'] });
}
