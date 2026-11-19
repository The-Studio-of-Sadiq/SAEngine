/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcCmColor, AcCmColorMethod, AcDbArc, AcDbCircle, AcDbDatabase, AcDbDimension, AcDbEntity, AcDbLine,
	AcDbPolyline, AcDbText, AcDbMText, AcDbEllipse, AcGiLineWeight, AcGePoint2d, AcGePoint3d,
} from '@mlightcad/data-model';
import type { CadCommandContext } from './commands.js';
import { circleMetrics, ellipseMetrics, polylineMetrics } from './inquiryGeometry.js';
import { polylineVertices } from './entityAccess.js';

export type CadColorValue = 'ByLayer' | 'ByBlock' | number | { r: number; g: number; b: number };
export type CadLineweightValue = 'ByLayer' | 'ByBlock' | 'default' | number;

export interface CadEntitySummary {
	readonly type: string;
	readonly count: number;
	readonly ids: readonly string[];
}

export interface CadPropertiesResult {
	readonly layer: string | 'varies';
	readonly color: CadColorValue | 'varies';
	readonly linetype: string | 'varies';
	readonly lineweight: CadLineweightValue | 'varies';
	readonly linetypeScale: number | 'varies';
	readonly length?: number | 'varies';
	readonly area?: number | 'varies';
	readonly radius?: number | 'varies';
	readonly center?: readonly [number, number] | 'varies';
	readonly circumference?: number | 'varies';

	// Summary for type filtering
	readonly totalCount?: number;
	readonly primaryType?: string | 'Mixed';
	readonly types?: readonly CadEntitySummary[];

	// Line geometry
	readonly startX?: number | 'varies';
	readonly startY?: number | 'varies';
	readonly endX?: number | 'varies';
	readonly endY?: number | 'varies';

	// Arc geometry
	readonly startAngle?: number | 'varies';
	readonly endAngle?: number | 'varies';

	// Polyline geometry
	readonly closed?: boolean | 'varies';
	readonly globalWidth?: number | 'varies';
	readonly vertices?: readonly (readonly [number, number])[] | 'varies';

	// Text / MText
	readonly text?: string | 'varies';
	readonly textHeight?: number | 'varies';
	readonly rotation?: number | 'varies';
	readonly textStyle?: string | 'varies';

	// Dimension
	readonly dimensionText?: string | 'varies';
	readonly measurement?: number | 'varies';
}

export interface CadPropertiesPatch {
	readonly layer?: string;
	readonly color?: CadColorValue | string;
	readonly linetype?: string;
	readonly lineweight?: CadLineweightValue | string;
	readonly linetypeScale?: number;

	// Line
	readonly startX?: number;
	readonly startY?: number;
	readonly endX?: number;
	readonly endY?: number;

	// Circle / Arc
	readonly centerX?: number;
	readonly centerY?: number;
	readonly radius?: number;

	// Arc
	readonly startAngle?: number;
	readonly endAngle?: number;

	// Polyline
	readonly closed?: boolean;
	readonly globalWidth?: number;

	// Text / MText
	readonly text?: string;
	readonly textHeight?: number;
	readonly rotation?: number;
	readonly textStyle?: string;

	// Dimension
	readonly dimensionText?: string;
}

export function formatColor(color: AcCmColor | undefined): CadColorValue {
	if (!color || color.isByLayer) return 'ByLayer';
	if (color.isByBlock) return 'ByBlock';
	if (color.isByACI) return color.colorIndex ?? 7;
	if (color.isByColor) return { r: color.red ?? 0, g: color.green ?? 0, b: color.blue ?? 0 };
	return 'ByLayer';
}

export function parseColor(val: CadColorValue | string): AcCmColor {
	if (typeof val === 'number') {
		const c = new AcCmColor(AcCmColorMethod.ByACI, val);
		c.colorIndex = val;
		return c;
	}
	if (typeof val === 'object' && val !== null) {
		const c = new AcCmColor(AcCmColorMethod.ByColor);
		c.setRGB(val.r, val.g, val.b);
		return c;
	}
	const s = String(val).trim();
	const upper = s.toUpperCase();
	if (upper === 'BYLAYER') return new AcCmColor(AcCmColorMethod.ByLayer, 256);
	if (upper === 'BYBLOCK') return new AcCmColor(AcCmColorMethod.ByBlock, 0);
	const num = Number(s);
	if (!isNaN(num) && num >= 1 && num <= 255) {
		const c = new AcCmColor(AcCmColorMethod.ByACI, num);
		c.colorIndex = num;
		return c;
	}
	const NAMED: Record<string, number> = {
		RED: 1, YELLOW: 2, GREEN: 3, CYAN: 4, BLUE: 5, MAGENTA: 6, WHITE: 7,
	};
	if (NAMED[upper]) {
		const c = new AcCmColor(AcCmColorMethod.ByACI, NAMED[upper]);
		c.colorIndex = NAMED[upper];
		return c;
	}
	const parsed = AcCmColor.fromString(s);
	if (parsed) return parsed;
	throw new Error(`Invalid color "${val}"`);
}

export function formatLineweight(lw: AcGiLineWeight | number | undefined): CadLineweightValue {
	if (lw === undefined || lw === AcGiLineWeight.ByLayer) return 'ByLayer';
	if (lw === AcGiLineWeight.ByBlock) return 'ByBlock';
	if (lw === AcGiLineWeight.ByLineWeightDefault) return 'default';
	if (lw >= 0) return lw / 100;
	return 'ByLayer';
}

export function parseLineweight(val: CadLineweightValue | string): AcGiLineWeight {
	if (typeof val === 'string') {
		const upper = val.trim().toUpperCase();
		if (upper === 'BYLAYER') return AcGiLineWeight.ByLayer;
		if (upper === 'BYBLOCK') return AcGiLineWeight.ByBlock;
		if (upper === 'DEFAULT') return AcGiLineWeight.ByLineWeightDefault;
		const n = Number(upper);
		if (!isNaN(n)) return parseLineweight(n);
		throw new Error(`Invalid lineweight "${val}"`);
	}
	if (val === -1) return AcGiLineWeight.ByLayer;
	if (val === -2) return AcGiLineWeight.ByBlock;
	if (val === -3) return AcGiLineWeight.ByLineWeightDefault;
	if (val >= 0) {
		const scaled = val < 5 ? Math.round(val * 100) : Math.round(val);
		return scaled as AcGiLineWeight;
	}
	return AcGiLineWeight.ByLayer;
}

function areColorsEqual(a: CadColorValue, b: CadColorValue): boolean {
	if (a === b) return true;
	if (typeof a === 'object' && typeof b === 'object' && a !== null && b !== null) {
		return a.r === b.r && a.g === b.g && a.b === b.b;
	}
	return false;
}

function areCentersEqual(a: readonly [number, number], b: readonly [number, number]): boolean {
	return Math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-6;
}

export function friendlyTypeName(e: AcDbEntity): string {
	if (e instanceof AcDbLine || e.dxfTypeName === 'LINE') return 'Line';
	if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') return 'Circle';
	if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') return 'Arc';
	if (e instanceof AcDbPolyline || e.dxfTypeName === 'LWPOLYLINE' || e.dxfTypeName === 'POLYLINE') return 'Polyline';
	if (e instanceof AcDbMText || e.dxfTypeName === 'MTEXT') return 'MText';
	if (e instanceof AcDbText || e.dxfTypeName === 'TEXT') return 'Text';
	if (e instanceof AcDbDimension || e.dxfTypeName?.includes('DIMENSION')) return 'Dimension';
	if (e instanceof AcDbEllipse || e.dxfTypeName === 'ELLIPSE') return 'Ellipse';
	return e.dxfTypeName || 'Entity';
}

function getPolylineGlobalWidth(poly: AcDbPolyline): number | 'varies' | undefined {
	const geo = (poly as unknown as { _geo?: { vertices?: { startWidth?: number; endWidth?: number }[] } })._geo;
	const verts = geo?.vertices;
	if (!verts || verts.length === 0) return 0;
	const firstSw = verts[0].startWidth ?? 0;
	const firstEw = verts[0].endWidth ?? 0;
	if (Math.abs(firstSw - firstEw) > 1e-6) return 'varies';
	for (let i = 1; i < verts.length; i++) {
		const sw = verts[i].startWidth ?? 0;
		const ew = verts[i].endWidth ?? 0;
		if (Math.abs(sw - firstSw) > 1e-6 || Math.abs(ew - firstSw) > 1e-6) {
			return 'varies';
		}
	}
	return firstSw;
}

/**
 * Returns common properties for the specified entity IDs (or the database's current values when empty).
 */
export function getProperties(
	db: AcDbDatabase,
	ids?: readonly string[],
	generatedIds?: ReadonlySet<string>,
): CadPropertiesResult {
	if (!ids || ids.length === 0) {
		// Nothing selected: return current CECOLOR/CELTYPE/CELWEIGHT/CLAYER
		const curLayer = db.clayer || '0';
		const curColor = formatColor(db.cecolor);
		const curLinetype = db.celtype || 'ByLayer';
		const curLineweight = formatLineweight(db.celweight);
		const curLtscale = db.celtscale ?? 1.0;
		return {
			layer: curLayer,
			color: curColor,
			linetype: curLinetype,
			lineweight: curLineweight,
			linetypeScale: curLtscale,
			totalCount: 0,
			types: [],
		};
	}

	const space = db.tables?.blockTable?.modelSpace;
	const entities: AcDbEntity[] = [];
	for (const id of ids) {
		if (generatedIds?.has(id)) continue;
		const ent = space?.getIdAt(id);
		if (ent) entities.push(ent);
	}

	if (entities.length === 0) {
		return getProperties(db, []);
	}

	const typeMap = new Map<string, { type: string; count: number; ids: string[] }>();
	for (const e of entities) {
		const t = friendlyTypeName(e);
		let entry = typeMap.get(t);
		if (!entry) {
			entry = { type: t, count: 0, ids: [] };
			typeMap.set(t, entry);
		}
		entry.count++;
		entry.ids.push(String(e.objectId));
	}
	const entityTypes: CadEntitySummary[] = Array.from(typeMap.values());
	const primaryType = entityTypes.length === 1 ? entityTypes[0].type : 'Mixed';

	const first = entities[0];
	let commonLayer: string | 'varies' = first.layer || '0';
	let commonColor: CadColorValue | 'varies' = formatColor(first.color);
	let commonLinetype: string | 'varies' = first.lineType || 'ByLayer';
	let commonLineweight: CadLineweightValue | 'varies' = formatLineweight(first.lineWeight);
	let commonLinetypeScale: number | 'varies' = first.linetypeScale ?? 1.0;

	for (let i = 1; i < entities.length; i++) {
		const e = entities[i];
		const layer = e.layer || '0';
		if (commonLayer !== 'varies' && commonLayer !== layer) commonLayer = 'varies';

		const color = formatColor(e.color);
		if (commonColor !== 'varies' && !areColorsEqual(commonColor, color)) commonColor = 'varies';

		const linetype = e.lineType || 'ByLayer';
		if (commonLinetype !== 'varies' && commonLinetype !== linetype) commonLinetype = 'varies';

		const lineweight = formatLineweight(e.lineWeight);
		if (commonLineweight !== 'varies' && commonLineweight !== lineweight) commonLineweight = 'varies';

		const ltscale = e.linetypeScale ?? 1.0;
		if (commonLinetypeScale !== 'varies' && Math.abs(commonLinetypeScale - ltscale) > 1e-6) commonLinetypeScale = 'varies';
	}

	// Read-only and type-specific geometry extraction
	let commonLength: number | 'varies' | undefined;
	let commonArea: number | 'varies' | undefined;
	let commonRadius: number | 'varies' | undefined;
	let commonCenter: readonly [number, number] | 'varies' | undefined;
	let commonCircumference: number | 'varies' | undefined;

	let commonStartX: number | 'varies' | undefined;
	let commonStartY: number | 'varies' | undefined;
	let commonEndX: number | 'varies' | undefined;
	let commonEndY: number | 'varies' | undefined;

	let commonStartAngle: number | 'varies' | undefined;
	let commonEndAngle: number | 'varies' | undefined;

	let commonClosed: boolean | 'varies' | undefined;
	let commonGlobalWidth: number | 'varies' | undefined;
	let commonVertices: readonly (readonly [number, number])[] | 'varies' | undefined;

	let commonText: string | 'varies' | undefined;
	let commonTextHeight: number | 'varies' | undefined;
	let commonRotation: number | 'varies' | undefined;
	let commonTextStyle: string | 'varies' | undefined;

	let commonDimensionText: string | 'varies' | undefined;
	let commonMeasurement: number | 'varies' | undefined;

	const allSameType = entityTypes.length === 1;
	if (allSameType) {
		if (first instanceof AcDbLine || first.dxfTypeName === 'LINE') {
			const lines = entities.map(e => e as AcDbLine);
			const lengths = lines.map(line => Math.hypot(line.endPoint.x - line.startPoint.x, line.endPoint.y - line.startPoint.y));
			commonLength = lengths.every(l => Math.abs(l - lengths[0]) < 1e-6) ? lengths[0] : 'varies';
			const startXs = lines.map(l => l.startPoint.x);
			commonStartX = startXs.every(x => Math.abs(x - startXs[0]) < 1e-6) ? startXs[0] : 'varies';
			const startYs = lines.map(l => l.startPoint.y);
			commonStartY = startYs.every(y => Math.abs(y - startYs[0]) < 1e-6) ? startYs[0] : 'varies';
			const endXs = lines.map(l => l.endPoint.x);
			commonEndX = endXs.every(x => Math.abs(x - endXs[0]) < 1e-6) ? endXs[0] : 'varies';
			const endYs = lines.map(l => l.endPoint.y);
			commonEndY = endYs.every(y => Math.abs(y - endYs[0]) < 1e-6) ? endYs[0] : 'varies';
		} else if (first instanceof AcDbCircle || first.dxfTypeName === 'CIRCLE') {
			const circles = entities.map(e => e as AcDbCircle);
			commonRadius = circles.every(c => Math.abs(c.radius - circles[0].radius) < 1e-6) ? circles[0].radius : 'varies';
			const centers = circles.map(c => [c.center.x, c.center.y] as const);
			commonCenter = centers.every(c => areCentersEqual(c, centers[0])) ? centers[0] : 'varies';
			const areas = circles.map(c => circleMetrics(c.radius).area);
			commonArea = areas.every(a => Math.abs(a - areas[0]) < 1e-6) ? areas[0] : 'varies';
			const lengths = circles.map(c => circleMetrics(c.radius).circumference);
			commonLength = lengths.every(l => Math.abs(l - lengths[0]) < 1e-6) ? lengths[0] : 'varies';
			commonCircumference = commonLength;
		} else if (first instanceof AcDbArc || first.dxfTypeName === 'ARC') {
			const arcs = entities.map(e => e as AcDbArc);
			commonRadius = arcs.every(a => Math.abs(a.radius - arcs[0].radius) < 1e-6) ? arcs[0].radius : 'varies';
			const centers = arcs.map(a => [a.center.x, a.center.y] as const);
			commonCenter = centers.every(c => areCentersEqual(c, centers[0])) ? centers[0] : 'varies';
			const startAngles = arcs.map(a => a.startAngle);
			commonStartAngle = startAngles.every(a => Math.abs(a - startAngles[0]) < 1e-6) ? startAngles[0] : 'varies';
			const endAngles = arcs.map(a => a.endAngle);
			commonEndAngle = endAngles.every(a => Math.abs(a - endAngles[0]) < 1e-6) ? endAngles[0] : 'varies';
			const lengths = arcs.map(a => {
				const sweep = ((a.endAngle - a.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || (2 * Math.PI);
				return a.radius * sweep;
			});
			commonLength = lengths.every(l => Math.abs(l - lengths[0]) < 1e-6) ? lengths[0] : 'varies';
		} else if (first instanceof AcDbPolyline || first.dxfTypeName === 'LWPOLYLINE' || first.dxfTypeName === 'POLYLINE') {
			const polylines = entities.map(e => e as AcDbPolyline);
			const metrics = polylines.map(p => {
				const data = polylineVertices(p);
				return polylineMetrics(data.points, data.bulges, data.closed);
			});
			commonLength = metrics.every(m => Math.abs(m.length - metrics[0].length) < 1e-6) ? metrics[0].length : 'varies';
			commonArea = metrics.every(m => Math.abs(m.area - metrics[0].area) < 1e-6) ? metrics[0].area : 'varies';
			const closedFlags = polylines.map(p => !!p.closed);
			commonClosed = closedFlags.every(c => c === closedFlags[0]) ? closedFlags[0] : 'varies';
			const widths = polylines.map(p => getPolylineGlobalWidth(p));
			commonGlobalWidth = widths.every(w => w !== 'varies' && w !== undefined && Math.abs((w as number) - (widths[0] as number)) < 1e-6) ? widths[0] : 'varies';
			if (polylines.length === 1) {
				commonVertices = polylineVertices(polylines[0]).points;
			}
		} else if (first instanceof AcDbMText || first.dxfTypeName === 'MTEXT') {
			const mtexts = entities.map(e => e as AcDbMText);
			const textVals = mtexts.map(t => t.contents);
			commonText = textVals.every(t => t === textVals[0]) ? textVals[0] : 'varies';
			const heights = mtexts.map(t => t.height);
			commonTextHeight = heights.every(h => Math.abs(h - heights[0]) < 1e-6) ? heights[0] : 'varies';
			const rotations = mtexts.map(t => t.rotation);
			commonRotation = rotations.every(r => Math.abs(r - rotations[0]) < 1e-6) ? rotations[0] : 'varies';
			const styles = mtexts.map(t => t.styleName || 'Standard');
			commonTextStyle = styles.every(s => s === styles[0]) ? styles[0] : 'varies';
		} else if (first instanceof AcDbText || first.dxfTypeName === 'TEXT') {
			const texts = entities.map(e => e as AcDbText);
			const textVals = texts.map(t => t.textString);
			commonText = textVals.every(t => t === textVals[0]) ? textVals[0] : 'varies';
			const heights = texts.map(t => t.height);
			commonTextHeight = heights.every(h => Math.abs(h - heights[0]) < 1e-6) ? heights[0] : 'varies';
			const rotations = texts.map(t => t.rotation);
			commonRotation = rotations.every(r => Math.abs(r - rotations[0]) < 1e-6) ? rotations[0] : 'varies';
			const styles = texts.map(t => t.styleName || 'Standard');
			commonTextStyle = styles.every(s => s === styles[0]) ? styles[0] : 'varies';
		} else if (first instanceof AcDbDimension || first.dxfTypeName?.includes('DIMENSION')) {
			const dims = entities.map(e => e as AcDbDimension);
			const textVals = dims.map(d => d.dimensionText ?? '');
			commonDimensionText = textVals.every(t => t === textVals[0]) ? textVals[0] : 'varies';
			const measurements = dims.map(d => d.measurement ?? 0);
			commonMeasurement = measurements.every(m => Math.abs(m - measurements[0]) < 1e-6) ? measurements[0] : 'varies';
		} else if (first instanceof AcDbEllipse || first.dxfTypeName === 'ELLIPSE') {
			const ellipses = entities.map(e => e as AcDbEllipse);
			const metrics = ellipses.map(el => ellipseMetrics(el.majorAxisRadius, el.minorAxisRadius));
			commonArea = metrics.every(m => Math.abs(m.area - metrics[0].area) < 1e-6) ? metrics[0].area : 'varies';
			commonLength = metrics.every(m => Math.abs(m.perimeter - metrics[0].perimeter) < 1e-6) ? metrics[0].perimeter : 'varies';
		}
	}

	return {
		layer: commonLayer,
		color: commonColor,
		linetype: commonLinetype,
		lineweight: commonLineweight,
		linetypeScale: commonLinetypeScale,
		totalCount: entities.length,
		primaryType,
		types: entityTypes,
		...(commonLength !== undefined ? { length: commonLength } : {}),
		...(commonArea !== undefined ? { area: commonArea } : {}),
		...(commonRadius !== undefined ? { radius: commonRadius } : {}),
		...(commonCenter !== undefined ? { center: commonCenter } : {}),
		...(commonCircumference !== undefined ? { circumference: commonCircumference } : {}),
		...(commonStartX !== undefined ? { startX: commonStartX } : {}),
		...(commonStartY !== undefined ? { startY: commonStartY } : {}),
		...(commonEndX !== undefined ? { endX: commonEndX } : {}),
		...(commonEndY !== undefined ? { endY: commonEndY } : {}),
		...(commonStartAngle !== undefined ? { startAngle: commonStartAngle } : {}),
		...(commonEndAngle !== undefined ? { endAngle: commonEndAngle } : {}),
		...(commonClosed !== undefined ? { closed: commonClosed } : {}),
		...(commonGlobalWidth !== undefined ? { globalWidth: commonGlobalWidth } : {}),
		...(commonVertices !== undefined ? { vertices: commonVertices } : {}),
		...(commonText !== undefined ? { text: commonText } : {}),
		...(commonTextHeight !== undefined ? { textHeight: commonTextHeight } : {}),
		...(commonRotation !== undefined ? { rotation: commonRotation } : {}),
		...(commonTextStyle !== undefined ? { textStyle: commonTextStyle } : {}),
		...(commonDimensionText !== undefined ? { dimensionText: commonDimensionText } : {}),
		...(commonMeasurement !== undefined ? { measurement: commonMeasurement } : {}),
	};
}

/**
 * Modifies properties on the specified entities in an undoable transaction, refusing generated entities.
 */
export function setProperties(
	db: AcDbDatabase,
	ids: readonly string[],
	patch: CadPropertiesPatch,
	generatedIds?: ReadonlySet<string>,
): void {
	for (const id of ids) {
		if (generatedIds?.has(id)) {
			throw new Error(`Cannot modify generated entity ${id}`);
		}
	}

	const space = db.tables?.blockTable?.modelSpace;
	const layerTable = db.tables?.layerTable;

	const entitiesToModify: AcDbEntity[] = [];
	for (const id of ids) {
		const ent = db.openEntityForWrite?.(id) ?? space?.getIdAt(id);
		if (!ent) continue;
		if (ent.layer && layerTable?.getAt(ent.layer)?.isLocked) {
			throw new Error(`Cannot modify entity on locked layer "${ent.layer}"`);
		}
		entitiesToModify.push(ent);
	}

	const apply = () => {
		for (const ent of entitiesToModify) {
			if (patch.layer !== undefined) {
				ent.layer = patch.layer;
			}
			if (patch.color !== undefined) {
				ent.color = parseColor(patch.color);
			}
			if (patch.linetype !== undefined) {
				ent.lineType = patch.linetype;
			}
			if (patch.lineweight !== undefined) {
				ent.lineWeight = parseLineweight(patch.lineweight);
			}
			if (patch.linetypeScale !== undefined) {
				ent.linetypeScale = patch.linetypeScale;
			}

			// Line
			if (ent instanceof AcDbLine || ent.dxfTypeName === 'LINE') {
				const line = ent as AcDbLine;
				const sp = line.startPoint;
				const ep = line.endPoint;
				if (patch.startX !== undefined || patch.startY !== undefined) {
					line.startPoint = new AcGePoint3d(
						patch.startX !== undefined ? patch.startX : sp.x,
						patch.startY !== undefined ? patch.startY : sp.y,
						sp.z,
					);
				}
				if (patch.endX !== undefined || patch.endY !== undefined) {
					line.endPoint = new AcGePoint3d(
						patch.endX !== undefined ? patch.endX : ep.x,
						patch.endY !== undefined ? patch.endY : ep.y,
						ep.z,
					);
				}
			}

			// Circle
			if (ent instanceof AcDbCircle || ent.dxfTypeName === 'CIRCLE') {
				const circle = ent as AcDbCircle;
				const c = circle.center;
				if (patch.centerX !== undefined || patch.centerY !== undefined) {
					circle.center = new AcGePoint3d(
						patch.centerX !== undefined ? patch.centerX : c.x,
						patch.centerY !== undefined ? patch.centerY : c.y,
						c.z,
					);
				}
				if (patch.radius !== undefined && patch.radius > 0) {
					circle.radius = patch.radius;
				}
			}

			// Arc
			if (ent instanceof AcDbArc || ent.dxfTypeName === 'ARC') {
				const arc = ent as AcDbArc;
				const c = arc.center;
				if (patch.centerX !== undefined || patch.centerY !== undefined) {
					arc.center = new AcGePoint3d(
						patch.centerX !== undefined ? patch.centerX : c.x,
						patch.centerY !== undefined ? patch.centerY : c.y,
						c.z,
					);
				}
				if (patch.radius !== undefined && patch.radius > 0) {
					arc.radius = patch.radius;
				}
				if (patch.startAngle !== undefined) {
					arc.startAngle = patch.startAngle;
				}
				if (patch.endAngle !== undefined) {
					arc.endAngle = patch.endAngle;
				}
			}

			// Polyline
			if (ent instanceof AcDbPolyline || ent.dxfTypeName === 'LWPOLYLINE' || ent.dxfTypeName === 'POLYLINE') {
				const poly = ent as AcDbPolyline;
				if (patch.closed !== undefined && patch.globalWidth === undefined) {
					poly.closed = patch.closed;
				}
				if (patch.globalWidth !== undefined && patch.globalWidth >= 0) {
					const data = polylineVertices(poly);
					const w = patch.globalWidth;
					poly.reset(false);
					poly.closed = patch.closed !== undefined ? patch.closed : data.closed;
					for (let i = 0; i < data.points.length; i++) {
						const b = data.bulges && i < data.bulges.length ? data.bulges[i] : 0;
						poly.addVertexAt(i, new AcGePoint2d(data.points[i][0], data.points[i][1]), b, w, w);
					}
				}
			}

			// Text
			if (ent instanceof AcDbText || ent.dxfTypeName === 'TEXT') {
				const text = ent as AcDbText;
				if (patch.text !== undefined) {
					text.textString = patch.text;
				}
				if (patch.textHeight !== undefined && patch.textHeight > 0) {
					text.height = patch.textHeight;
				}
				if (patch.rotation !== undefined) {
					text.rotation = patch.rotation;
				}
				if (patch.textStyle !== undefined) {
					text.styleName = patch.textStyle;
				}
			}

			// MText
			if (ent instanceof AcDbMText || ent.dxfTypeName === 'MTEXT') {
				const mtext = ent as AcDbMText;
				if (patch.text !== undefined) {
					mtext.contents = patch.text;
				}
				if (patch.textHeight !== undefined && patch.textHeight > 0) {
					mtext.height = patch.textHeight;
				}
				if (patch.rotation !== undefined) {
					mtext.rotation = patch.rotation;
				}
				if (patch.textStyle !== undefined) {
					mtext.styleName = patch.textStyle;
				}
			}

			// Dimension
			if (ent instanceof AcDbDimension || (ent as any).dimensionText !== undefined) {
				const dim = ent as AcDbDimension;
				if (patch.dimensionText !== undefined) {
					dim.dimensionText = patch.dimensionText;
				}
			}
		}
	};

	const tx = db.transactionManager?.startTransaction();
	try {
		apply();
		tx?.commit();
	} catch (err) {
		tx?.abort();
		throw err;
	}
}

/**
 * COLOR command: sets current entity color (CECOLOR).
 */
export async function colorCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const cur = formatColor(db.cecolor);
	const curStr = typeof cur === 'object' ? `RGB:${cur.r},${cur.g},${cur.b}` : String(cur);
	const input = await ctx.getString(`Enter new color <${curStr}>:`, { allowEmpty: true, defaultValue: curStr });
	const color = parseColor(input || curStr);
	db.cecolor = color;
	ctx.message(`CECOLOR set to ${input || curStr}.`);
}

/**
 * LWEIGHT command: sets current lineweight (CELWEIGHT).
 */
export async function lweightCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const cur = formatLineweight(db.celweight);
	const curStr = String(cur);
	const input = await ctx.getString(`Enter default lineweight [ByLayer/ByBlock/Default/<mm>] <${curStr}>:`, { allowEmpty: true, defaultValue: curStr });
	const lw = parseLineweight(input || curStr);
	db.celweight = lw;
	ctx.message(`CELWEIGHT set to ${input || curStr}.`);
}

/**
 * CHPROP and CHANGE commands: changes properties of selected objects.
 */
export async function chpropCommand(ctx: CadCommandContext): Promise<void> {
	const selected = await ctx.getSelection('Select objects:');
	const ids = selected.map(e => String(e.objectId));

	while (true) {
		const prop = await ctx.getKeyword(
			'Enter property to change [Color/LAyer/LType/ltScale/LWeight]:',
			['Color', 'LAyer', 'LType', 'ltScale', 'LWeight'],
			{ default: 'Color' },
		);
		const upper = prop.toUpperCase();

		if (upper === 'COLOR' || upper === 'C') {
			const c = await ctx.getString('Enter new color <ByLayer>:');
			setProperties(ctx.database.native, ids, { color: c });
			ctx.message(`Color updated.`);
			break;
		} else if (upper === 'LAYER' || upper === 'LA') {
			const layer = await ctx.getString('Enter new layer name <0>:');
			setProperties(ctx.database.native, ids, { layer });
			ctx.message(`Layer updated.`);
			break;
		} else if (upper === 'LTYPE' || upper === 'LT') {
			const lt = await ctx.getString('Enter new linetype <ByLayer>:');
			setProperties(ctx.database.native, ids, { linetype: lt });
			ctx.message(`Linetype updated.`);
			break;
		} else if (upper === 'LTSCALE' || upper === 'S') {
			const scale = await ctx.getDouble('Enter new linetype scale <1.0>:');
			setProperties(ctx.database.native, ids, { linetypeScale: scale });
			ctx.message(`Linetype scale updated.`);
			break;
		} else if (upper === 'LWEIGHT' || upper === 'LW') {
			const lw = await ctx.getString('Enter new lineweight <ByLayer>:');
			setProperties(ctx.database.native, ids, { lineweight: lw });
			ctx.message(`Lineweight updated.`);
			break;
		}
	}
}
