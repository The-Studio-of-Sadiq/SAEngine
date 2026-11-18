/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDb3PointAngularDimension,
	AcDbAlignedDimension,
	AcDbArc,
	AcDbArcDimension,
	AcDbCircle,
	AcDbDiametricDimension,
	AcDbDimension,
	AcDbEntity,
	AcDbLine,
	AcDbOrdinateDimension,
	AcDbPolyline,
	AcDbRadialDimension,
	AcDbRotatedDimension,
	AcGePoint3d,
} from '@mlightcad/data-model';
import { AcApDocManager } from '@mlightcad/cad-simple-viewer';
import { polylineVertices } from './entityAccess.js';
import { CadCommandContext, registerCommand } from './commands.js';
import {
	angleBetweenLines,
	calculateArcLength,
	calculateBaselineOffset,
	calculateContinueDimLinePoint,
	calculateDiameter,
	calculateOrdinateMeasurement,
	calculateRadius,
	determineOrdinateDatum,
	extractAndSortCoordinates,
} from './dimensionGeometry.js';
import { bulgeToArc, type P2 } from './modifyGeometry2.js';

interface LinearDimensionState {
	readonly xLine1Point: AcGePoint3d;
	readonly xLine2Point: AcGePoint3d;
	readonly dimLinePoint: AcGePoint3d;
	readonly rotation?: number; // radians, for rotated dimension
	readonly isRotated: boolean;
}

/** Remembers the last linear or aligned dimension created for DIMCONTINUE and DIMBASELINE. */
let lastLinearDimension: LinearDimensionState | undefined;

/** Applies the active drawing layer and dimension style, if available. */
function applyDimensionProperties(dim: AcDbEntity): void {
	try {
		const db = AcApDocManager.instance?.curDocument?.database;
		if (db?.clayer) {
			dim.layer = db.clayer;
		}
		if (dim instanceof AcDbDimension) {
			const styleName = (db as any)?.dimstyle ?? (db as any)?.header?.dimstyle;
			if (styleName) {
				dim.dimensionStyleName = styleName;
			}
		}
	} catch {
		// Ignore if running outside active editor context (e.g. tests)
	}
}

/**
 * Gets baseline dimension spacing.
 * Assumption: For metric (mm) drawings, baseline spacing is 7.5 mm × DIMSCALE (default DIMSCALE = 1).
 */
function getBaselineSpacing(): number {
	try {
		const db = AcApDocManager.instance?.curDocument?.database;
		const scale = Number((db as any)?.dimscale ?? (db as any)?.header?.dimscale) || 1.0;
		const dli = Number((db as any)?.dimdli ?? (db as any)?.header?.dimdli) || 7.5;
		return dli * scale;
	} catch {
		return 7.5;
	}
}

/** DIMALIGNED (DAL): Creates an aligned linear dimension. */
export async function dimalignedCommand(ctx: CadCommandContext): Promise<void> {
	const first = await ctx.getPoint('Specify first extension line origin:');
	const second = await ctx.getPoint('Specify second extension line origin:', { base: first });
	const dimPt = await ctx.getPoint('Specify dimension line location:', { base: second });

	const p1 = new AcGePoint3d(first.x, first.y, first.z ?? 0);
	const p2 = new AcGePoint3d(second.x, second.y, second.z ?? 0);
	const pd = new AcGePoint3d(dimPt.x, dimPt.y, dimPt.z ?? 0);

	const dist = Math.hypot(p2.x - p1.x, p2.y - p1.y);
	const dim = new AcDbAlignedDimension(p1, p2, pd);
	dim.measurement = dist;
	dim.dimensionText = dist.toFixed(3);
	applyDimensionProperties(dim);

	await ctx.transaction(async () => {
		ctx.database.add(dim);
	});

	lastLinearDimension = {
		xLine1Point: p1,
		xLine2Point: p2,
		dimLinePoint: pd,
		isRotated: false,
	};
}

/** DIMRADIUS (DRA): Creates a radial dimension for an arc or circle. */
export async function dimradiusCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select arc or circle:');
	if (pick.status !== 'ok' || !pick.entity) return;

	let center: AcGePoint3d;
	let radius: number;
	const e = pick.entity;

	if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') {
		const c = e as AcDbCircle;
		center = new AcGePoint3d(c.center.x, c.center.y, c.center.z);
		radius = c.radius;
	} else if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') {
		const a = e as AcDbArc;
		center = new AcGePoint3d(a.center.x, a.center.y, a.center.z);
		radius = a.radius;
	} else {
		ctx.message('Selected object must be an arc or circle');
		return;
	}

	const loc = await ctx.getPoint('Specify dimension line location:');
	const ang = Math.atan2(loc.y - center.y, loc.x - center.x);
	const chordPoint = new AcGePoint3d(center.x + radius * Math.cos(ang), center.y + radius * Math.sin(ang), center.z);
	const distToLoc = Math.hypot(loc.x - center.x, loc.y - center.y);
	const leaderLength = Math.max(0, distToLoc - radius);

	const dim = new AcDbRadialDimension(center, chordPoint, leaderLength);
	dim.measurement = radius;
	dim.dimensionText = `R${radius.toFixed(3)}`;
	applyDimensionProperties(dim);

	await ctx.transaction(async () => {
		ctx.database.add(dim);
	});
}

/** DIMDIAMETER (DDI): Creates a diametric dimension for an arc or circle. */
export async function dimdiameterCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select arc or circle:');
	if (pick.status !== 'ok' || !pick.entity) return;

	let center: AcGePoint3d;
	let radius: number;
	const e = pick.entity;

	if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') {
		const c = e as AcDbCircle;
		center = new AcGePoint3d(c.center.x, c.center.y, c.center.z);
		radius = c.radius;
	} else if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') {
		const a = e as AcDbArc;
		center = new AcGePoint3d(a.center.x, a.center.y, a.center.z);
		radius = a.radius;
	} else {
		ctx.message('Selected object must be an arc or circle');
		return;
	}

	const loc = await ctx.getPoint('Specify dimension line location:');
	const ang = Math.atan2(loc.y - center.y, loc.x - center.x);
	const chordPoint = new AcGePoint3d(center.x + radius * Math.cos(ang), center.y + radius * Math.sin(ang), center.z);
	const farChordPoint = new AcGePoint3d(center.x - radius * Math.cos(ang), center.y - radius * Math.sin(ang), center.z);
	const distToLoc = Math.hypot(loc.x - center.x, loc.y - center.y);
	const leaderLength = Math.max(0, distToLoc - radius);

	const dim = new AcDbDiametricDimension(chordPoint, farChordPoint, leaderLength);
	dim.measurement = radius * 2;
	dim.dimensionText = `%%c${(radius * 2).toFixed(3)}`;
	applyDimensionProperties(dim);

	await ctx.transaction(async () => {
		ctx.database.add(dim);
	});
}

/** DIMANGULAR (DAN): Creates an angular dimension between lines, on an arc/circle, or 3 points. */
export async function dimangularCommand(ctx: CadCommandContext): Promise<void> {
	const pick1 = await ctx.getEntityPick('Select arc, circle, line, or [Enter for 3-point vertex]:', {
		allowNone: true,
		keywords: ['Vertex'],
	});

	let centerPoint: AcGePoint3d;
	let xLine1Point: AcGePoint3d;
	let xLine2Point: AcGePoint3d;
	let angleRad: number;

	if (pick1.status === 'none' || pick1.keyword === 'Vertex' || !pick1.entity) {
		const vertex = await ctx.getPoint('Specify angle vertex:');
		const pt1 = await ctx.getPoint('Specify first angle endpoint:', { base: vertex });
		const pt2 = await ctx.getPoint('Specify second angle endpoint:', { base: vertex });

		centerPoint = new AcGePoint3d(vertex.x, vertex.y, vertex.z ?? 0);
		xLine1Point = new AcGePoint3d(pt1.x, pt1.y, pt1.z ?? 0);
		xLine2Point = new AcGePoint3d(pt2.x, pt2.y, pt2.z ?? 0);

		const v1: P2 = [pt1.x - vertex.x, pt1.y - vertex.y];
		const v2: P2 = [pt2.x - vertex.x, pt2.y - vertex.y];
		const len1 = Math.hypot(v1[0], v1[1]), len2 = Math.hypot(v2[0], v2[1]);
		if (len1 < 1e-12 || len2 < 1e-12) {
			ctx.message('Endpoints must be distinct from vertex');
			return;
		}
		const cosA = Math.max(-1, Math.min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)));
		angleRad = Math.acos(cosA);
	} else if (pick1.entity instanceof AcDbLine || pick1.entity.dxfTypeName === 'LINE') {
		const line1 = pick1.entity as AcDbLine;
		const pick2 = await ctx.getEntityPick('Select second line:');
		if (pick2.status !== 'ok' || !pick2.entity) return;
		if (!(pick2.entity instanceof AcDbLine || pick2.entity.dxfTypeName === 'LINE')) {
			ctx.message('Second object must be a line');
			return;
		}
		const line2 = pick2.entity as AcDbLine;

		const a1: P2 = [line1.startPoint.x, line1.startPoint.y];
		const a2: P2 = [line1.endPoint.x, line1.endPoint.y];
		const b1: P2 = [line2.startPoint.x, line2.startPoint.y];
		const b2: P2 = [line2.endPoint.x, line2.endPoint.y];
		const pPick1: P2 | undefined = pick1.point ? [pick1.point.x, pick1.point.y] : undefined;
		const pPick2: P2 | undefined = pick2.point ? [pick2.point.x, pick2.point.y] : undefined;

		const res = angleBetweenLines(a1, a2, b1, b2, pPick1, pPick2);
		if (!res) {
			ctx.message('Lines are parallel');
			return;
		}

		centerPoint = new AcGePoint3d(res.vertex[0], res.vertex[1], line1.startPoint.z ?? 0);
		xLine1Point = new AcGePoint3d(res.p1[0], res.p1[1], line1.startPoint.z ?? 0);
		xLine2Point = new AcGePoint3d(res.p2[0], res.p2[1], line2.startPoint.z ?? 0);
		angleRad = res.angleRad;
	} else if (pick1.entity instanceof AcDbArc || pick1.entity.dxfTypeName === 'ARC') {
		const arc = pick1.entity as AcDbArc;
		centerPoint = new AcGePoint3d(arc.center.x, arc.center.y, arc.center.z);
		xLine1Point = new AcGePoint3d(
			arc.center.x + arc.radius * Math.cos(arc.startAngle),
			arc.center.y + arc.radius * Math.sin(arc.startAngle),
			arc.center.z,
		);
		xLine2Point = new AcGePoint3d(
			arc.center.x + arc.radius * Math.cos(arc.endAngle),
			arc.center.y + arc.radius * Math.sin(arc.endAngle),
			arc.center.z,
		);
		const sweep = ((arc.endAngle - arc.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
		angleRad = sweep === 0 ? 2 * Math.PI : sweep;
	} else if (pick1.entity instanceof AcDbCircle || pick1.entity.dxfTypeName === 'CIRCLE') {
		const circle = pick1.entity as AcDbCircle;
		centerPoint = new AcGePoint3d(circle.center.x, circle.center.y, circle.center.z);
		const pt1 = await ctx.getPoint('Specify first angle endpoint:', { base: centerPoint });
		const pt2 = await ctx.getPoint('Specify second angle endpoint:', { base: centerPoint });
		xLine1Point = new AcGePoint3d(pt1.x, pt1.y, pt1.z ?? 0);
		xLine2Point = new AcGePoint3d(pt2.x, pt2.y, pt2.z ?? 0);
		const v1: P2 = [pt1.x - centerPoint.x, pt1.y - centerPoint.y];
		const v2: P2 = [pt2.x - centerPoint.x, pt2.y - centerPoint.y];
		const len1 = Math.hypot(v1[0], v1[1]), len2 = Math.hypot(v2[0], v2[1]);
		const cosA = Math.max(-1, Math.min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)));
		angleRad = Math.acos(cosA);
	} else {
		ctx.message('Unsupported object for DIMANGULAR');
		return;
	}

	const arcLoc = await ctx.getPoint('Specify dimension arc line location:', { base: centerPoint });
	const arcPoint = new AcGePoint3d(arcLoc.x, arcLoc.y, arcLoc.z ?? 0);

	const dim = new AcDb3PointAngularDimension(centerPoint, xLine1Point, xLine2Point, arcPoint);
	dim.measurement = angleRad;
	dim.dimensionText = `${(angleRad * 180 / Math.PI).toFixed(1)}°`;
	applyDimensionProperties(dim);

	await ctx.transaction(async () => {
		ctx.database.add(dim);
	});
}

/** DIMARC (DAR): Creates an arc length dimension for an arc or polyline arc segment. */
export async function dimarcCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select arc or polyline arc segment:');
	if (pick.status !== 'ok' || !pick.entity) return;

	let center: P2;
	let radius: number;
	let startAngle: number; // radians
	let endAngle: number; // radians
	let z = 0;

	const e = pick.entity;
	if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') {
		const a = e as AcDbArc;
		center = [a.center.x, a.center.y];
		radius = a.radius;
		startAngle = a.startAngle;
		endAngle = a.endAngle;
		z = a.center.z;
	} else if (e instanceof AcDbPolyline || e.dxfTypeName === 'LWPOLYLINE') {
		const poly = e as AcDbPolyline;
		z = poly.elevation ?? 0;
		const pickPt: P2 = pick.point ? [pick.point.x, pick.point.y] : [0, 0];
		let foundArc: { center: P2; radius: number; startAngle: number; endAngle: number } | undefined;
		let bestDist = Infinity;

		const numVerts = poly.numberOfVertices;
		for (let i = 0; i < (poly.closed ? numVerts : numVerts - 1); i++) {
			const nextIdx = (i + 1) % numVerts;
			const v1 = poly.getPoint2dAt(i);
			const v2 = poly.getPoint2dAt(nextIdx);
			const bulge = (poly as any)._geo?.vertices?.[i]?.bulge ?? 0;
			if (Math.abs(bulge) > 1e-6) {
				const arcGeom = bulgeToArc([v1.x, v1.y], [v2.x, v2.y], bulge);
				const midDist = Math.hypot(pickPt[0] - arcGeom.center[0], pickPt[1] - arcGeom.center[1]);
				if (midDist < bestDist) {
					bestDist = midDist;
					foundArc = {
						center: arcGeom.center,
						radius: arcGeom.radius,
						startAngle: arcGeom.startAngle * Math.PI / 180,
						endAngle: arcGeom.endAngle * Math.PI / 180,
					};
				}
			}
		}
		if (!foundArc) {
			ctx.message('Selected polyline segment is not an arc');
			return;
		}
		center = foundArc.center;
		radius = foundArc.radius;
		startAngle = foundArc.startAngle;
		endAngle = foundArc.endAngle;
	} else {
		ctx.message('Selected object must be an arc or polyline arc segment');
		return;
	}

	const len = calculateArcLength(radius, startAngle, endAngle);
	const p1 = new AcGePoint3d(center[0] + radius * Math.cos(startAngle), center[1] + radius * Math.sin(startAngle), z);
	const p2 = new AcGePoint3d(center[0] + radius * Math.cos(endAngle), center[1] + radius * Math.sin(endAngle), z);
	const centerPt = new AcGePoint3d(center[0], center[1], z);

	const arcLoc = await ctx.getPoint('Specify arc length dimension location:', { base: centerPt });
	const arcPoint = new AcGePoint3d(arcLoc.x, arcLoc.y, arcLoc.z ?? z);

	const dim = new AcDbArcDimension(centerPt, p1, p2, arcPoint);
	dim.measurement = len;
	dim.dimensionText = len.toFixed(3);
	applyDimensionProperties(dim);

	await ctx.transaction(async () => {
		ctx.database.add(dim);
	});
}

/** DIMORDINATE (DOR): Creates an ordinate dimension (X or Y datum determined by leader direction). */
export async function dimordinateCommand(ctx: CadCommandContext): Promise<void> {
	const feat = await ctx.getPoint('Specify feature location:');
	const leader = await ctx.getPoint('Specify leader endpoint:', { base: feat });

	const pFeat: P2 = [feat.x, feat.y];
	const pLeader: P2 = [leader.x, leader.y];
	const datum = determineOrdinateDatum(pFeat, pLeader);
	const measurement = calculateOrdinateMeasurement(pFeat, datum);

	const definingPoint = new AcGePoint3d(feat.x, feat.y, feat.z ?? 0);
	const leaderEndPoint = new AcGePoint3d(leader.x, leader.y, leader.z ?? 0);

	const dim = new AcDbOrdinateDimension(definingPoint, leaderEndPoint);
	dim.dimensionType = datum === 'X' ? 70 : 6;
	dim.measurement = measurement;
	dim.dimensionText = measurement.toFixed(3);
	applyDimensionProperties(dim);

	await ctx.transaction(async () => {
		ctx.database.add(dim);
	});
}

/** Resolves the base linear dimension for DIMCONTINUE or DIMBASELINE. */
async function resolveBaseDimension(ctx: CadCommandContext, prompt: string): Promise<LinearDimensionState | undefined> {
	if (lastLinearDimension) return lastLinearDimension;

	const pick = await ctx.getEntityPick(prompt);
	if (pick.status !== 'ok' || !pick.entity) return undefined;

	const ent = pick.entity;
	if (ent instanceof AcDbRotatedDimension) {
		return {
			xLine1Point: ent.xLine1Point,
			xLine2Point: ent.xLine2Point,
			dimLinePoint: ent.dimLinePoint,
			rotation: ent.rotation,
			isRotated: true,
		};
	}
	if (ent instanceof AcDbAlignedDimension) {
		return {
			xLine1Point: ent.xLine1Point,
			xLine2Point: ent.xLine2Point,
			dimLinePoint: ent.dimLinePoint,
			rotation: Math.atan2(ent.xLine2Point.y - ent.xLine1Point.y, ent.xLine2Point.x - ent.xLine1Point.x),
			isRotated: false,
		};
	}
	ctx.message('Selected entity is not a linear or aligned dimension');
	return undefined;
}

/** DIMCONTINUE (DCO): Continues a chain of linear/aligned dimensions. */
export async function dimcontinueCommand(ctx: CadCommandContext): Promise<void> {
	let curBase = await resolveBaseDimension(ctx, 'Select continued dimension:');
	if (!curBase) return;

	while (true) {
		let nextPt: { x: number; y: number; z?: number };
		try {
			nextPt = await ctx.getPoint('Specify a second extension line origin or [Enter to exit]:', {
				base: curBase.xLine2Point,
			});
		} catch {
			break;
		}

		const p1: P2 = [curBase.xLine2Point.x, curBase.xLine2Point.y];
		const pBaseDim: P2 = [curBase.dimLinePoint.x, curBase.dimLinePoint.y];
		const pNext: P2 = [nextPt.x, nextPt.y];
		const pPrev1: P2 = [curBase.xLine1Point.x, curBase.xLine1Point.y];

		const newDimLinePt = calculateContinueDimLinePoint(pPrev1, p1, pBaseDim, pNext);

		const xLine1: AcGePoint3d = new AcGePoint3d(p1[0], p1[1], curBase.xLine2Point.z);
		const xLine2: AcGePoint3d = new AcGePoint3d(pNext[0], pNext[1], nextPt.z ?? curBase.xLine2Point.z);
		const dimPt: AcGePoint3d = new AcGePoint3d(newDimLinePt[0], newDimLinePt[1], curBase.dimLinePoint.z);

		let dim: AcDbAlignedDimension | AcDbRotatedDimension;
		let dist: number;

		if (curBase.isRotated) {
			const rotDim = new AcDbRotatedDimension(xLine1, xLine2, dimPt);
			rotDim.rotation = curBase.rotation ?? 0;
			const cosR = Math.cos(rotDim.rotation), sinR = Math.sin(rotDim.rotation);
			dist = Math.abs((xLine2.x - xLine1.x) * cosR + (xLine2.y - xLine1.y) * sinR);
			rotDim.measurement = dist;
			rotDim.dimensionText = dist.toFixed(3);
			dim = rotDim;
		} else {
			dist = Math.hypot(xLine2.x - xLine1.x, xLine2.y - xLine1.y);
			const alDim = new AcDbAlignedDimension(xLine1, xLine2, dimPt);
			alDim.measurement = dist;
			alDim.dimensionText = dist.toFixed(3);
			dim = alDim;
		}

		applyDimensionProperties(dim);
		await ctx.transaction(async () => {
			ctx.database.add(dim);
		});

		curBase = {
			xLine1Point: xLine1,
			xLine2Point: xLine2,
			dimLinePoint: dimPt,
			rotation: curBase.rotation,
			isRotated: curBase.isRotated,
		};
		lastLinearDimension = curBase;
	}
}

/** DIMBASELINE (DBA): Creates a series of baseline linear/aligned dimensions with constant offset. */
export async function dimbaselineCommand(ctx: CadCommandContext): Promise<void> {
	const base = await resolveBaseDimension(ctx, 'Select base dimension:');
	if (!base) return;

	const spacing = getBaselineSpacing();
	let step = 1;

	while (true) {
		let nextPt: { x: number; y: number; z?: number };
		try {
			nextPt = await ctx.getPoint('Specify a second extension line origin or [Enter to exit]:', {
				base: base.xLine1Point,
			});
		} catch {
			break;
		}

		const p1: P2 = [base.xLine1Point.x, base.xLine1Point.y];
		const p2: P2 = [base.xLine2Point.x, base.xLine2Point.y];
		const pBaseDim: P2 = [base.dimLinePoint.x, base.dimLinePoint.y];
		const pNext: P2 = [nextPt.x, nextPt.y];

		const offsetPt = calculateBaselineOffset(pBaseDim, p1, p2, spacing, step);

		const xLine1: AcGePoint3d = new AcGePoint3d(base.xLine1Point.x, base.xLine1Point.y, base.xLine1Point.z);
		const xLine2: AcGePoint3d = new AcGePoint3d(pNext[0], pNext[1], nextPt.z ?? base.xLine1Point.z);
		const dimPt: AcGePoint3d = new AcGePoint3d(offsetPt[0], offsetPt[1], base.dimLinePoint.z);

		let dim: AcDbAlignedDimension | AcDbRotatedDimension;
		let dist: number;

		if (base.isRotated) {
			const rotDim = new AcDbRotatedDimension(xLine1, xLine2, dimPt);
			rotDim.rotation = base.rotation ?? 0;
			const cosR = Math.cos(rotDim.rotation), sinR = Math.sin(rotDim.rotation);
			dist = Math.abs((xLine2.x - xLine1.x) * cosR + (xLine2.y - xLine1.y) * sinR);
			rotDim.measurement = dist;
			rotDim.dimensionText = dist.toFixed(3);
			dim = rotDim;
		} else {
			dist = Math.hypot(xLine2.x - xLine1.x, xLine2.y - xLine1.y);
			const alDim = new AcDbAlignedDimension(xLine1, xLine2, dimPt);
			alDim.measurement = dist;
			alDim.dimensionText = dist.toFixed(3);
			dim = alDim;
		}

		applyDimensionProperties(dim);
		await ctx.transaction(async () => {
			ctx.database.add(dim);
		});

		lastLinearDimension = {
			xLine1Point: xLine1,
			xLine2Point: xLine2,
			dimLinePoint: dimPt,
			rotation: base.rotation,
			isRotated: base.isRotated,
		};
		step++;
	}
}

/** QDIM: Quickly dimensions selected geometry into a continuous chain along X or Y. */
export async function qdimCommand(ctx: CadCommandContext): Promise<void> {
	const selection = await ctx.getSelection('Select geometry to dimension:');
	if (selection.length === 0) return;

	const orientation = await ctx.getKeyword(
		'Specify dimension orientation [Horizontal/Vertical] <Horizontal>:',
		['Horizontal', 'Vertical'],
		{ default: 'Horizontal' },
	);
	const isHorizontal = orientation.toLowerCase() !== 'vertical';

	const dimLoc = await ctx.getPoint('Specify dimension line location:');

	// Collect points from selected geometry
	const pts: P2[] = [];
	for (const e of selection) {
		if (e instanceof AcDbLine || e.dxfTypeName === 'LINE') {
			const line = e as AcDbLine;
			pts.push([line.startPoint.x, line.startPoint.y]);
			pts.push([line.endPoint.x, line.endPoint.y]);
		} else if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') {
			const arc = e as AcDbArc;
			pts.push([arc.center.x, arc.center.y]);
			pts.push([arc.center.x + arc.radius * Math.cos(arc.startAngle), arc.center.y + arc.radius * Math.sin(arc.startAngle)]);
			pts.push([arc.center.x + arc.radius * Math.cos(arc.endAngle), arc.center.y + arc.radius * Math.sin(arc.endAngle)]);
		} else if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') {
			const circle = e as AcDbCircle;
			pts.push([circle.center.x, circle.center.y]);
			if (isHorizontal) {
				pts.push([circle.center.x - circle.radius, circle.center.y]);
				pts.push([circle.center.x + circle.radius, circle.center.y]);
			} else {
				pts.push([circle.center.x, circle.center.y - circle.radius]);
				pts.push([circle.center.x, circle.center.y + circle.radius]);
			}
		} else if (e instanceof AcDbPolyline || e.dxfTypeName === 'LWPOLYLINE') {
			const poly = e as AcDbPolyline;
			pts.push(...polylineVertices(poly).points);
		}
	}

	const coords = extractAndSortCoordinates(pts, isHorizontal ? 'X' : 'Y');
	if (coords.length < 2) {
		ctx.message('Not enough distinct points to dimension');
		return;
	}

	const created: AcDbRotatedDimension[] = [];
	for (let i = 0; i < coords.length - 1; i++) {
		const c1 = coords[i];
		const c2 = coords[i + 1];
		const span = c2 - c1;

		let p1: AcGePoint3d;
		let p2: AcGePoint3d;
		let pd: AcGePoint3d;

		if (isHorizontal) {
			p1 = new AcGePoint3d(c1, dimLoc.y, dimLoc.z ?? 0);
			p2 = new AcGePoint3d(c2, dimLoc.y, dimLoc.z ?? 0);
			pd = new AcGePoint3d((c1 + c2) / 2, dimLoc.y, dimLoc.z ?? 0);
		} else {
			p1 = new AcGePoint3d(dimLoc.x, c1, dimLoc.z ?? 0);
			p2 = new AcGePoint3d(dimLoc.x, c2, dimLoc.z ?? 0);
			pd = new AcGePoint3d(dimLoc.x, (c1 + c2) / 2, dimLoc.z ?? 0);
		}

		const dim = new AcDbRotatedDimension(p1, p2, pd);
		dim.rotation = isHorizontal ? 0 : Math.PI / 2;
		dim.measurement = span;
		dim.dimensionText = span.toFixed(3);
		applyDimensionProperties(dim);
		created.push(dim);
	}

	await ctx.transaction(async () => {
		ctx.database.add(created);
	});

	if (created.length > 0) {
		const last = created[created.length - 1];
		lastLinearDimension = {
			xLine1Point: last.xLine1Point,
			xLine2Point: last.xLine2Point,
			dimLinePoint: last.dimLinePoint,
			rotation: last.rotation,
			isRotated: true,
		};
	}
}

/** Registers all AutoCAD dimension commands. */
export function registerDimensionCommands(): void {
	registerCommand('DIMALIGNED', dimalignedCommand, { aliases: ['DAL'] });
	registerCommand('DIMRADIUS', dimradiusCommand, { aliases: ['DRA'] });
	registerCommand('DIMDIAMETER', dimdiameterCommand, { aliases: ['DDI'] });
	registerCommand('DIMANGULAR', dimangularCommand, { aliases: ['DAN'] });
	registerCommand('DIMARC', dimarcCommand, { aliases: ['DAR'] });
	registerCommand('DIMORDINATE', dimordinateCommand, { aliases: ['DOR'] });
	registerCommand('DIMCONTINUE', dimcontinueCommand, { aliases: ['DCO'] });
	registerCommand('DIMBASELINE', dimbaselineCommand, { aliases: ['DBA'] });
	registerCommand('QDIM', qdimCommand);
}
