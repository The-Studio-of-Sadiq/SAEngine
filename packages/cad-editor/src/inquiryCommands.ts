/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc, AcDbCircle, AcDbDimension, AcDbEllipse, AcDbEntity, AcDbLine,
	AcDbMText, AcDbPoint, AcDbPolyline, AcDbText, AcGePoint3d,
} from '@mlightcad/data-model';
import { AcApDocManager } from '@mlightcad/cad-simple-viewer';
import type { CadCommandContext, CadPoint3 } from './commands.js';
import { polylineVertices } from './entityAccess.js';
import {
	angleBetweenLines, arcIncludedAngle, arcSegmentMetrics, circleMetrics,
	curveSegments, divideCurve, ellipseMetrics, measureCurve, polylineMetrics,
	threePointAngle, totalLength, type P2, type Segment,
} from './inquiryGeometry.js';
import { formatAngle, formatLength } from './unitsFormat.js';

const p = (x: number, y: number): P2 => [x, y];

function getUnits(ctx: CadCommandContext) {
	const db = ctx.database?.native ?? AcApDocManager.instance?.curDocument?.database;
	return {
		lunits: db?.lunits ?? 2,
		luprec: db?.luprec ?? 2,
		aunits: db?.aunits ?? 0,
		auprec: db?.auprec ?? 0,
		angbase: db?.angbase ?? 0,
		angdir: db?.angdir ?? 0,
	};
}

const fmtL = (v: number, u: ReturnType<typeof getUnits>) => formatLength(v, u.lunits, u.luprec);
const fmtA = (rad: number, u: ReturnType<typeof getUnits>) => formatAngle(rad, u.aunits, u.auprec, u.angbase, u.angdir);

function geom(e: AcDbEntity): { segments: Segment[]; length: number } | undefined {
	if (e instanceof AcDbLine) {
		const a = e.startPoint, b = e.endPoint;
		const s: Segment[] = [{ start: p(a.x, a.y), end: p(b.x, b.y) }];
		return { segments: s, length: totalLength(s) };
	}
	if (e instanceof AcDbCircle) {
		const c = e.center, r = e.radius;
		const s1: Segment = { start: p(c.x + r, c.y), end: p(c.x - r, c.y), bulge: 1 };
		const s2: Segment = { start: p(c.x - r, c.y), end: p(c.x + r, c.y), bulge: 1 };
		return { segments: [s1, s2], length: 2 * Math.PI * r };
	}
	if (e instanceof AcDbArc) {
		const c = e.center, r = e.radius;
		const sweep = ((e.endAngle - e.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || 2 * Math.PI;
		if (sweep > Math.PI) {
			const mid = e.startAngle + sweep / 2;
			const end = e.startAngle + sweep;
			const b = Math.tan(sweep / 8);
			const s1: Segment = { start: p(c.x + r * Math.cos(e.startAngle), c.y + r * Math.sin(e.startAngle)), end: p(c.x + r * Math.cos(mid), c.y + r * Math.sin(mid)), bulge: b };
			const s2: Segment = { start: p(c.x + r * Math.cos(mid), c.y + r * Math.sin(mid)), end: p(c.x + r * Math.cos(end), c.y + r * Math.sin(end)), bulge: b };
			return { segments: [s1, s2], length: r * sweep };
		}
		const segs: Segment[] = [{
			start: p(c.x + r * Math.cos(e.startAngle), c.y + r * Math.sin(e.startAngle)),
			end: p(c.x + r * Math.cos(e.startAngle + sweep), c.y + r * Math.sin(e.startAngle + sweep)),
			bulge: Math.tan(sweep / 4),
		}];
		return { segments: segs, length: r * sweep };
	}
	if (e instanceof AcDbPolyline) {
		const { points, bulges, closed } = polylineVertices(e);
		const segments = curveSegments(points, bulges, closed);
		return { segments, length: polylineMetrics(points, bulges, closed).length };
	}
	return undefined;
}

export async function distCommand(ctx: CadCommandContext): Promise<void> {
	const u = getUnits(ctx);
	const a = await ctx.getPoint('Specify first point:');
	const b = await ctx.getPoint('Specify second point:', { base: a });
	const dx = b.x - a.x, dy = b.y - a.y;
	const d = Math.hypot(dx, dy);
	const angRad = (Math.atan2(dy, dx) + 2 * Math.PI) % (2 * Math.PI);
	ctx.message(`Distance = ${fmtL(d, u)}\nAngle in XY Plane = ${fmtA(angRad, u)}\nDelta X = ${fmtL(dx, u)}, Delta Y = ${fmtL(dy, u)}, Delta Z = ${fmtL(b.z - a.z, u)}`);
}

export async function idCommand(ctx: CadCommandContext): Promise<void> {
	const u = getUnits(ctx);
	const a = await ctx.getPoint('Specify point:');
	ctx.message(`X = ${fmtL(a.x, u)}, Y = ${fmtL(a.y, u)}, Z = ${fmtL(a.z, u)}`);
}

const pointEntity = (q: P2): AcDbPoint => {
	const e = new AcDbPoint();
	e.position = new AcGePoint3d(q[0], q[1], 0);
	return e;
};

export async function divideCommand(ctx: CadCommandContext): Promise<void> {
	const e = await ctx.getEntity('Select object to divide:');
	const n = Math.floor(await ctx.getDistance('Enter number of segments:'));
	const g = geom(e);
	if (!g || n < 2) {
		ctx.message('Invalid object or segment count');
		return;
	}
	ctx.database.add(divideCurve(g.segments, n).map(pointEntity));
}

export async function measureCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select object to measure:');
	if (!pick.entity) return;
	const step = await ctx.getDistance('Specify length of segment:');
	const g = geom(pick.entity);
	if (!g || step <= 0) return;
	const nearStart = pick.point ? Math.hypot(pick.point.x - g.segments[0].start[0], pick.point.y - g.segments[0].start[1]) < Math.hypot(pick.point.x - g.segments[g.segments.length - 1].end[0], pick.point.y - g.segments[g.segments.length - 1].end[1]) : true;
	ctx.database.add(measureCurve(g.segments, step, !nearStart).map(pointEntity));
}

export function entityArea(e: AcDbEntity): { area: number; perimeter: number; isChordClosedArc?: boolean } | undefined {
	if (e instanceof AcDbCircle) {
		const m = circleMetrics(e.radius);
		return { area: m.area, perimeter: m.circumference };
	}
	if (e instanceof AcDbEllipse) {
		const m = ellipseMetrics(e.majorAxisRadius, e.minorAxisRadius);
		return { area: m.area, perimeter: m.perimeter };
	}
	if (e instanceof AcDbArc) {
		const sweep = ((e.endAngle - e.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || 2 * Math.PI;
		const m = arcSegmentMetrics(e.radius, sweep);
		return { area: m.area, perimeter: m.perimeter, isChordClosedArc: true };
	}
	if (e instanceof AcDbPolyline && e.closed) {
		const { points, bulges } = polylineVertices(e);
		const m = polylineMetrics(points, bulges, true);
		return { area: m.area, perimeter: m.length };
	}
	return undefined;
}

async function pickPointsArea(ctx: CadCommandContext): Promise<{ area: number; perimeter: number } | undefined> {
	const first = await ctx.getPoint('Specify first corner or press Enter to finish:', { allowNone: true });
	if (!first) return undefined;
	const pts: CadPoint3[] = [first];
	while (true) {
		const next = await ctx.getPoint('Specify next point or press Enter to finish:', { base: pts[pts.length - 1], allowNone: true });
		if (!next) break;
		pts.push(next);
	}
	if (pts.length < 3) return undefined;
	let a = 0, per = 0;
	for (let i = 0; i < pts.length; i++) {
		const q = pts[i], r = pts[(i + 1) % pts.length];
		a += q.x * r.y - r.x * q.y;
		per += Math.hypot(r.x - q.x, r.y - q.y);
	}
	return { area: Math.abs(a) / 2, perimeter: per };
}

export async function areaCommand(ctx: CadCommandContext): Promise<void> {
	const u = getUnits(ctx);
	const mode = await ctx.getKeyword('Specify first point or [Object/Add/Subtract]:', ['Object', 'Add', 'Subtract', 'Points'], { default: 'Object' });
	if (mode === 'Object') {
		const e = await ctx.getEntity('Select object:');
		const m = entityArea(e);
		if (m) {
			ctx.message(`Area = ${fmtL(m.area, u)}${m.isChordClosedArc ? ' (chord-closed segment)' : ''}, Perimeter = ${fmtL(m.perimeter, u)}`);
		}
		return;
	}
	if (mode === 'Add' || mode === 'Subtract') {
		let total = 0;
		let sign = mode === 'Subtract' ? -1 : 1;
		while (true) {
			const sub = await ctx.getKeyword(
				`Specify [${sign > 0 ? 'Object/Subtract/Points/Exit' : 'Object/Add/Points/Exit'}]:`,
				['Object', 'Add', 'Subtract', 'Points', 'Exit'],
				{ default: 'Object' },
			);
			if (sub === 'Exit') break;
			if (sub === 'Add') { sign = 1; continue; }
			if (sub === 'Subtract') { sign = -1; continue; }
			if (sub === 'Object') {
				const e = await ctx.getEntity('Select object:');
				const m = entityArea(e);
				if (m) {
					total += sign * m.area;
					ctx.message(`Area = ${fmtL(m.area, u)}${m.isChordClosedArc ? ' (chord-closed segment)' : ''}, Perimeter = ${fmtL(m.perimeter, u)}\nTotal area = ${fmtL(total, u)}`);
				}
			} else if (sub === 'Points') {
				const m = await pickPointsArea(ctx);
				if (m) {
					total += sign * m.area;
					ctx.message(`Area = ${fmtL(m.area, u)}, Perimeter = ${fmtL(m.perimeter, u)}\nTotal area = ${fmtL(total, u)}`);
				}
			}
		}
		ctx.message(`Total area = ${fmtL(total, u)}`);
		return;
	}
	const m = await pickPointsArea(ctx);
	if (m) {
		ctx.message(`Area = ${fmtL(m.area, u)}, Perimeter = ${fmtL(m.perimeter, u)}`);
	}
}

export async function measureGeomCommand(ctx: CadCommandContext): Promise<void> {
	const u = getUnits(ctx);
	const option = await ctx.getKeyword('Specify [Distance/Radius/Angle/Area]:', ['Distance', 'Radius', 'Angle', 'Area'], { default: 'Distance' });
	if (option === 'Distance') return distCommand(ctx);
	if (option === 'Area') return areaCommand(ctx);
	if (option === 'Radius') {
		const e = await ctx.getEntity('Select arc or circle:');
		if (e instanceof AcDbArc || e instanceof AcDbCircle) {
			ctx.message(`Radius = ${fmtL(e.radius, u)}, Diameter = ${fmtL(2 * e.radius, u)}`);
		}
		return;
	}
	// Angle
	const pick = await ctx.getEntityPick('Select arc, line, or [3Point]:', { keywords: ['3Point'], allowNone: true });
	if (pick.status === 'ok' && pick.entity instanceof AcDbArc) {
		const ang = arcIncludedAngle(pick.entity.startAngle, pick.entity.endAngle);
		ctx.message(`Angle = ${fmtA(ang * Math.PI / 180, u)}`);
		return;
	}
	if (pick.status === 'ok' && pick.entity instanceof AcDbLine) {
		const e1 = pick.entity;
		const pick2 = await ctx.getEntity('Select second line:');
		if (pick2 instanceof AcDbLine) {
			const e2 = pick2;
			const ang = angleBetweenLines(
				[e1.startPoint.x, e1.startPoint.y],
				[e1.endPoint.x, e1.endPoint.y],
				[e2.startPoint.x, e2.startPoint.y],
				[e2.endPoint.x, e2.endPoint.y],
			);
			ctx.message(`Angle = ${fmtA(ang * Math.PI / 180, u)}`);
			return;
		}
		ctx.message('Second object must be a line');
		return;
	}
	const v = await ctx.getPoint('Specify angle vertex:');
	const p1 = await ctx.getPoint('Specify first angle endpoint:', { base: v });
	const p2 = await ctx.getPoint('Specify second angle endpoint:', { base: v });
	const ang = threePointAngle([v.x, v.y], [p1.x, p1.y], [p2.x, p2.y]);
	ctx.message(`Angle = ${fmtA(ang * Math.PI / 180, u)}`);
}

export async function listCommand(ctx: CadCommandContext): Promise<void> {
	const u = getUnits(ctx);
	const es = await ctx.getSelection('Select objects:');
	for (const e of es) {
		let s = `${e.dxfTypeName} Layer=${e.layer ?? ''} Handle=${e.objectId}`;
		if (e instanceof AcDbLine) {
			const g = geom(e)!;
			const a = e.startPoint, b = e.endPoint;
			s += ` Length=${fmtL(g.length, u)} Angle=${fmtA(Math.atan2(b.y - a.y, b.x - a.x), u)}`;
		} else if (e instanceof AcDbCircle) {
			const m = circleMetrics(e.radius);
			s += ` Center=(${fmtL(e.center.x, u)},${fmtL(e.center.y, u)}) Radius=${fmtL(e.radius, u)} Circumference=${fmtL(m.circumference, u)} Area=${fmtL(m.area, u)}`;
		} else if (e instanceof AcDbArc) {
			const sweep = ((e.endAngle - e.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || 2 * Math.PI;
			const length = e.radius * sweep;
			s += ` Center=(${fmtL(e.center.x, u)},${fmtL(e.center.y, u)}) Radius=${fmtL(e.radius, u)} StartAngle=${fmtA(e.startAngle, u)} EndAngle=${fmtA(e.endAngle, u)} TotalAngle=${fmtA(sweep, u)} Length=${fmtL(length, u)}`;
		} else if (e instanceof AcDbEllipse) {
			const a = e.majorAxisRadius, b = e.minorAxisRadius;
			const m = ellipseMetrics(a, b);
			s += ` Center=(${fmtL(e.center.x, u)},${fmtL(e.center.y, u)}) MajorRadius=${fmtL(a, u)} MinorRadius=${fmtL(b, u)} Area=${fmtL(m.area, u)} Circumference=${fmtL(m.perimeter, u)}`;
		} else if (e instanceof AcDbPolyline) {
			const { points, bulges, closed } = polylineVertices(e);
			const m = polylineMetrics(points, bulges, closed);
			s += ` Vertices=${e.numberOfVertices} Length=${fmtL(m.length, u)} ${closed ? 'Closed' : 'Open'}${closed ? ` Area=${fmtL(m.area, u)}` : ''}`;
		} else if (e instanceof AcDbText) {
			const rot = e.rotation ?? 0;
			const style = e.styleName ? ` Style=${e.styleName}` : '';
			s += ` Text="${e.textString}" Height=${fmtL(e.height, u)} Rotation=${fmtA(rot, u)}${style}`;
		} else if (e instanceof AcDbMText) {
			const rot = e.rotation ?? 0;
			const style = e.styleName ? ` Style=${e.styleName}` : '';
			s += ` Text="${e.contents}" Height=${fmtL(e.height, u)} Rotation=${fmtA(rot, u)}${style}`;
		} else if (e instanceof AcDbDimension) {
			const dimTypeNames: Record<number, string> = {
				0: 'Rotated',
				1: 'Aligned',
				2: 'Angular',
				3: 'Diameter',
				4: 'Radius',
				5: 'Angular 3-Point',
				6: 'Ordinate',
			};
			const rawType = (e.dimensionType ?? 0) & 7;
			const typeName = (dimTypeNames[rawType] ?? e.constructor.name.replace(/^AcDb/, '').replace(/Dimension$/, '')) || 'Dimension';
			let meas = e.measurement;
			if (meas === undefined && typeof (e as any).getMeasurementPropertyValue === 'function') {
				const v = (e as any).getMeasurementPropertyValue();
				if (typeof v === 'number' && Number.isFinite(v) && v > 0) meas = v;
			}
			if (meas === undefined && (e as any).xLine1Point && (e as any).xLine2Point) {
				const p1 = (e as any).xLine1Point, p2 = (e as any).xLine2Point;
				const d = Math.hypot(p2.x - p1.x, p2.y - p1.y);
				if (d > 0) meas = d;
			}
			const measStr = meas !== undefined ? ` Measurement=${fmtL(meas, u)}` : '';
			const style = e.dimensionStyleName ? ` Style=${e.dimensionStyleName}` : '';
			s += ` Type=${typeName}${measStr}${style}`;
		}
		ctx.message(s);
	}
}
