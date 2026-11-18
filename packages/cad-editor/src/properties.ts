/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcCmColor, AcCmColorMethod, AcDbArc, AcDbCircle, AcDbDatabase, AcDbEntity, AcDbLine,
	AcDbPolyline, AcDbText, AcDbMText, AcDbEllipse, AcGiLineWeight,
} from '@mlightcad/data-model';
import type { CadCommandContext } from './commands.js';
import { circleMetrics, ellipseMetrics, polylineMetrics, totalLength } from './inquiryGeometry.js';
import { polylineVertices } from './entityAccess.js';

export type CadColorValue = 'ByLayer' | 'ByBlock' | number | { r: number; g: number; b: number };
export type CadLineweightValue = 'ByLayer' | 'ByBlock' | 'default' | number;

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
}

export interface CadPropertiesPatch {
	readonly layer?: string;
	readonly color?: CadColorValue | string;
	readonly linetype?: string;
	readonly lineweight?: CadLineweightValue | string;
	readonly linetypeScale?: number;
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

	// Read-only geometry extraction
	let commonLength: number | 'varies' | undefined;
	let commonArea: number | 'varies' | undefined;
	let commonRadius: number | 'varies' | undefined;
	let commonCenter: readonly [number, number] | 'varies' | undefined;

	const allSameType = entities.every(e => e.dxfTypeName === first.dxfTypeName);
	if (allSameType) {
		if (first instanceof AcDbLine || first.dxfTypeName === 'LINE') {
			const lengths = entities.map(e => {
				const line = e as AcDbLine;
				return Math.hypot(line.endPoint.x - line.startPoint.x, line.endPoint.y - line.startPoint.y);
			});
			commonLength = lengths.every(l => Math.abs(l - lengths[0]) < 1e-6) ? lengths[0] : 'varies';
		} else if (first instanceof AcDbCircle || first.dxfTypeName === 'CIRCLE') {
			const circles = entities.map(e => e as AcDbCircle);
			commonRadius = circles.every(c => Math.abs(c.radius - circles[0].radius) < 1e-6) ? circles[0].radius : 'varies';
			const centers = circles.map(c => [c.center.x, c.center.y] as const);
			commonCenter = centers.every(c => areCentersEqual(c, centers[0])) ? centers[0] : 'varies';
			const areas = circles.map(c => circleMetrics(c.radius).area);
			commonArea = areas.every(a => Math.abs(a - areas[0]) < 1e-6) ? areas[0] : 'varies';
			const lengths = circles.map(c => circleMetrics(c.radius).circumference);
			commonLength = lengths.every(l => Math.abs(l - lengths[0]) < 1e-6) ? lengths[0] : 'varies';
		} else if (first instanceof AcDbArc || first.dxfTypeName === 'ARC') {
			const arcs = entities.map(e => e as AcDbArc);
			commonRadius = arcs.every(a => Math.abs(a.radius - arcs[0].radius) < 1e-6) ? arcs[0].radius : 'varies';
			const centers = arcs.map(a => [a.center.x, a.center.y] as const);
			commonCenter = centers.every(c => areCentersEqual(c, centers[0])) ? centers[0] : 'varies';
			const lengths = arcs.map(a => {
				const sweep = ((a.endAngle - a.startAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) || (2 * Math.PI);
				return a.radius * sweep;
			});
			commonLength = lengths.every(l => Math.abs(l - lengths[0]) < 1e-6) ? lengths[0] : 'varies';
		} else if (first instanceof AcDbPolyline || first.dxfTypeName === 'LWPOLYLINE') {
			const polylines = entities.map(e => e as AcDbPolyline);
			const metrics = polylines.map(p => {
				const data = polylineVertices(p);
				return polylineMetrics(data.points, data.bulges, data.closed);
			});
			commonLength = metrics.every(m => Math.abs(m.length - metrics[0].length) < 1e-6) ? metrics[0].length : 'varies';
			commonArea = metrics.every(m => Math.abs(m.area - metrics[0].area) < 1e-6) ? metrics[0].area : 'varies';
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
		...(commonLength !== undefined ? { length: commonLength } : {}),
		...(commonArea !== undefined ? { area: commonArea } : {}),
		...(commonRadius !== undefined ? { radius: commonRadius } : {}),
		...(commonCenter !== undefined ? { center: commonCenter } : {}),
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
