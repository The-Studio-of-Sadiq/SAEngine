/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc,
	AcDbCircle,
	AcDbDatabase,
	AcDbEllipse,
	AcDbEntity,
	AcDbLine,
	AcDbPolyline,
} from '@mlightcad/data-model';
import { polylineVertices } from './entityAccess.js';
import { circleMetrics, ellipseMetrics, polylineMetrics } from './inquiryGeometry.js';
import { calculateArcLength } from './dimensionGeometry.js';

export interface FieldEvalContext {
	readonly date?: Date;
	readonly fileName?: string;
	readonly lastSavedBy?: string;
	readonly database?: AcDbDatabase;
	readonly getEntityById?: (id: string | number) => AcDbEntity | undefined;
}

const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = [
	'January', 'February', 'March', 'April', 'May', 'June',
	'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Formats a Date according to AutoCAD date format patterns (e.g. "dd-MMM-yyyy").
 */
export function formatDateField(date: Date, formatStr: string = 'dd-MMM-yyyy'): string {
	// If the date's time is UTC midnight and local time is previous day, use UTC components
	const useUtc = date.getUTCHours() === 0 && date.getUTCMinutes() === 0 && date.getUTCDate() !== date.getDate();
	const year = useUtc ? date.getUTCFullYear() : date.getFullYear();
	const month = useUtc ? date.getUTCMonth() : date.getMonth();
	const day = useUtc ? date.getUTCDate() : date.getDate();
	const hours = useUtc ? date.getUTCHours() : date.getHours();
	const minutes = useUtc ? date.getUTCMinutes() : date.getMinutes();
	const seconds = useUtc ? date.getUTCSeconds() : date.getSeconds();

	let res = formatStr;
	res = res.replace(/yyyy/g, String(year));
	res = res.replace(/yy/g, String(year).slice(-2));
	res = res.replace(/MMMM/g, MONTHS_LONG[month]);
	res = res.replace(/MMM/g, MONTHS_SHORT[month]);
	res = res.replace(/MM/g, String(month + 1).padStart(2, '0'));
	res = res.replace(/M/g, String(month + 1));
	res = res.replace(/dd/g, String(day).padStart(2, '0'));
	res = res.replace(/d/g, String(day));
	res = res.replace(/HH/g, String(hours).padStart(2, '0'));
	res = res.replace(/hh/g, String(hours % 12 || 12).padStart(2, '0'));
	res = res.replace(/mm/g, String(minutes).padStart(2, '0'));
	res = res.replace(/ss/g, String(seconds).padStart(2, '0'));
	res = res.replace(/tt/g, hours >= 12 ? 'PM' : 'AM');

	return res;
}

/**
 * Formats a numeric value according to AutoCAD field format options (e.g. "%lu2%pr2").
 */
export function formatNumberField(value: number, formatStr?: string): string {
	let prec = 2;
	if (formatStr) {
		const prMatch = formatStr.match(/%pr(\d)/);
		if (prMatch) {
			prec = parseInt(prMatch[1], 10);
		}
		const ctMatch = formatStr.match(/%ct\d+\[([^\]]+)\]/);
		if (ctMatch) {
			value *= parseFloat(ctMatch[1]);
		}
	}
	let str = value.toFixed(prec);
	if (formatStr) {
		const psMatch = formatStr.match(/%ps\[([^,\s]*),([^,\s]*)\]/);
		if (psMatch) {
			str = (psMatch[1] ?? '') + str + (psMatch[2] ?? '');
		}
	}
	return str;
}

/**
 * Pure calculation of entity area, perimeter, length, and radius for field evaluation.
 */
export function getEntityProperty(
	entity: AcDbEntity,
	prop: 'Area' | 'Length' | 'Radius' | 'Perimeter',
): number | undefined {
	const norm = prop.toLowerCase();
	if (norm === 'area') {
		if (entity instanceof AcDbCircle) {
			return circleMetrics(entity.radius).area;
		}
		if (entity instanceof AcDbEllipse) {
			return ellipseMetrics(entity.majorAxisRadius, entity.minorAxisRadius).area;
		}
		if (entity instanceof AcDbPolyline) {
			const { points, bulges, closed } = polylineVertices(entity);
			return polylineMetrics(points, bulges, closed).area;
		}
		return undefined;
	}

	if (norm === 'length') {
		if (entity instanceof AcDbLine) {
			return Math.hypot(entity.endPoint.x - entity.startPoint.x, entity.endPoint.y - entity.startPoint.y);
		}
		if (entity instanceof AcDbCircle) {
			return 2 * Math.PI * entity.radius;
		}
		if (entity instanceof AcDbArc) {
			return calculateArcLength(entity.radius, entity.startAngle, entity.endAngle);
		}
		if (entity instanceof AcDbPolyline) {
			const { points, bulges, closed } = polylineVertices(entity);
			return polylineMetrics(points, bulges, closed).length;
		}
		return undefined;
	}

	if (norm === 'radius') {
		if (entity instanceof AcDbCircle || entity instanceof AcDbArc) {
			return entity.radius;
		}
		return undefined;
	}

	if (norm === 'perimeter') {
		if (entity instanceof AcDbCircle) {
			return 2 * Math.PI * entity.radius;
		}
		if (entity instanceof AcDbEllipse) {
			return ellipseMetrics(entity.majorAxisRadius, entity.minorAxisRadius).perimeter;
		}
		if (entity instanceof AcDbPolyline) {
			const { points, bulges, closed } = polylineVertices(entity);
			return polylineMetrics(points, bulges, closed).length;
		}
		return undefined;
	}

	return undefined;
}

/**
 * Finds an entity by handle/objectId in the context's database or lookup function.
 */
export function resolveEntity(id: string | number, ctx: FieldEvalContext): AcDbEntity | undefined {
	if (ctx.getEntityById) {
		const ent = ctx.getEntityById(id);
		if (ent) return ent;
	}
	if (ctx.database) {
		const strId = String(id);
		const modelSpace = ctx.database.tables?.blockTable?.modelSpace;
		if (modelSpace) {
			for (const ent of modelSpace.newIterator()) {
				if (String(ent.objectId) === strId || (ent as any).handle === strId) {
					return ent;
				}
			}
		}
	}
	return undefined;
}

/**
 * Evaluates a single field code expression (with or without enclosing %< ... >%).
 */
export function evaluateField(fieldCode: string, ctx: FieldEvalContext): string {
	// Strip outer %< ... >% if present
	let raw = fieldCode.trim();
	if (raw.startsWith('%<') && raw.endsWith('>%')) {
		raw = raw.slice(2, -2).trim();
	}

	// 1. AcVar Date
	const dateMatch = raw.match(/^\\?AcVar\s+Date(?:\s+\\f\s+"([^"]+)")?/i);
	if (dateMatch) {
		const fmt = dateMatch[1] ?? 'dd-MMM-yyyy';
		const date = ctx.date ?? new Date();
		return formatDateField(date, fmt);
	}

	// 2. AcVar Filename
	const fileMatch = raw.match(/^\\?AcVar\s+Filename/i);
	if (fileMatch) {
		return ctx.fileName ?? 'Drawing1.dwg';
	}

	// 3. AcVar LastSavedBy
	const userMatch = raw.match(/^\\?AcVar\s+LastSavedBy/i);
	if (userMatch) {
		return ctx.lastSavedBy ?? 'User';
	}

	// 4. AcObjProp Object(%<\_ObjId n>%).Property \f "format"
	// Also supports Object(n).Property
	const objPropMatch = raw.match(/^\\?AcObjProp\s+Object\((?:%<\\_ObjId\s+([^>]+)>%|([^)]+))\)\.(\w+)(?:\s+\\f\s+"([^"]+)")?/i);
	if (objPropMatch) {
		const targetId = (objPropMatch[1] ?? objPropMatch[2])?.trim();
		const propName = objPropMatch[3] as 'Area' | 'Length' | 'Radius' | 'Perimeter';
		const formatStr = objPropMatch[4];

		if (targetId) {
			const entity = resolveEntity(targetId, ctx);
			if (entity) {
				const val = getEntityProperty(entity, propName);
				if (val !== undefined) {
					return formatNumberField(val, formatStr);
				}
			}
		}
		return '####';
	}

	return raw;
}

/**
 * Evaluates all field codes within a string, replacing each %<...>% with its evaluated result.
 */
export function evaluateFieldsInText(text: string, ctx: FieldEvalContext): string {
	return text.replace(/%<([\s\S]*?)>%/g, (match) => {
		return evaluateField(match, ctx);
	});
}
