/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbPolyline, AcGeMatrix3d, AcGePoint2d, AcGePoint3d, AcGePoint3dLike } from '@mlightcad/data-model';
import {
	AcApDocManager, AcEdCommand, AcEdOpenMode, AcEdPromptAngleOptions, AcEdPromptDistanceOptions,
	AcEdPromptEntityOptions, AcEdPromptKeywordOptions, AcEdPromptPointOptions, AcEdPromptSelectionOptions,
	AcEdPromptStatus,
} from '@mlightcad/cad-simple-viewer';
import {
	chamferLines, extendArc, extendLine, extendPolyline, filletLines, GeomArc, GeomCircle, GeomLine,
	GeomPoint, GeomPolyline, GeomShape, normalizeAngle, trimArc, trimCircle, trimLine, trimPolyline,
} from './modifyGeometry.js';

export type CadPoint3 = AcGePoint3dLike;
export type CadSelection = readonly AcDbEntity[];

export interface CadPromptEntityOptions {
	readonly keywords?: readonly string[];
	readonly allowNone?: boolean;
}

export interface CadEntityPickResult {
	readonly entity?: AcDbEntity;
	readonly point?: CadPoint3;
	readonly keyword?: string;
	readonly status: 'ok' | 'none' | 'cancel' | 'keyword';
}

/** Reflect a point across an infinite 2D line; Z is preserved. */
export function mirrorPoint(point: CadPoint3, first: CadPoint3, second: CadPoint3): AcGePoint3d {
	const dx = second.x - first.x, dy = second.y - first.y, lenSq = dx * dx + dy * dy;
	if (lenSq < 1e-18) throw new Error('Mirror line points must be distinct');
	const t = ((point.x - first.x) * dx + (point.y - first.y) * dy) / lenSq;
	const x = first.x + t * dx, y = first.y + t * dy;
	return new AcGePoint3d(2 * x - point.x, 2 * y - point.y, point.z);
}

/** Reflect an arc parameter angle and normalize into [0, 2π). */
export function mirrorArcAngles(start: number, end: number, mirrorAngle: number): readonly [number, number] {
	const normalize = (angle: number) => ((angle % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
	return [normalize(2 * mirrorAngle - end), normalize(2 * mirrorAngle - start)];
}

/** Narrow, typed access to mlightcad's editor input and drawing database for custom commands. */
export interface CadCommandContext {
	getSelection(prompt: string): Promise<CadSelection>;
	getPoint(prompt: string, options?: { readonly base?: CadPoint3 }): Promise<CadPoint3>;
	getDistance(prompt: string, options?: { readonly base?: CadPoint3 }): Promise<number>;
	getAngle(prompt: string, options?: { readonly base?: CadPoint3 }): Promise<number>;
	getKeyword(prompt: string, keywords: readonly string[], options?: { readonly default?: string }): Promise<string>;
	getEntity(prompt: string): Promise<AcDbEntity>;
	getEntityPick(prompt: string, options?: CadPromptEntityOptions): Promise<CadEntityPickResult>;
	transaction<T>(fn: () => T | Promise<T>): Promise<T>;
	message(text: string): void;
	readonly database: {
		add(entity: AcDbEntity | readonly AcDbEntity[]): void;
		replace(id: string, entity: AcDbEntity): void;
		erase(id: string): void;
		get(id: string): AcDbEntity | undefined;
		all(): readonly AcDbEntity[];
	};
}

export interface CadCommandOptions {
	readonly aliases?: string | readonly string[];
	readonly localName?: string;
	readonly group?: string;
	readonly mode?: AcEdOpenMode;
}

function promptValue(result: { status: AcEdPromptStatus; value?: unknown }, label: string): unknown {
	if (result.status !== AcEdPromptStatus.OK || result.value === undefined) {
		throw new Error(`${label} cancelled`);
	}
	return result.value;
}

class CallbackCommand extends AcEdCommand {
	constructor(private readonly run: (ctx: CadCommandContext) => Promise<void>, private readonly name: string) { super(); }
	async execute(context: Parameters<AcEdCommand['execute']>[0]): Promise<void> {
		const db = context.doc.database;
		const editor = context.view.editor;
		const ctx: CadCommandContext = {
			getSelection: async prompt => {
				const result = await editor.getSelection(new AcEdPromptSelectionOptions(prompt));
				if (result.status !== AcEdPromptStatus.OK || !result.value || result.value.count === 0) throw new Error('Selection cancelled');
				return result.value.ids.map(id => db.tables.blockTable.modelSpace.getIdAt(id)).filter((e): e is AcDbEntity => !!e);
			},
			getPoint: async (prompt, options) => {
				const opts = new AcEdPromptPointOptions(prompt);
				if (options?.base) { opts.basePoint = new AcGePoint3d(options.base); opts.useBasePoint = true; opts.useDashedLine = true; }
				return promptValue(await editor.getPoint(opts), 'Point') as CadPoint3;
			},
			getDistance: async (prompt, options) => {
				const opts = new AcEdPromptDistanceOptions(prompt);
				if (options?.base) { opts.basePoint = new AcGePoint3d(options.base); opts.useBasePoint = true; opts.useDashedLine = true; }
				const r = await editor.getDistance(opts); if (r.status !== AcEdPromptStatus.OK || r.value === undefined) throw new Error('Distance cancelled'); return r.value;
			},
			getAngle: async (prompt, options) => {
				const opts = new AcEdPromptAngleOptions(prompt);
				if (options?.base) { opts.basePoint = new AcGePoint3d(options.base); opts.useBasePoint = true; opts.useDashedLine = true; }
				const r = await editor.getAngle(opts); if (r.status !== AcEdPromptStatus.OK || r.value === undefined) throw new Error('Angle cancelled'); return r.value;
			},
			getKeyword: async (prompt, keywords, options) => {
				const opts = new AcEdPromptKeywordOptions(prompt);
				for (const keyword of keywords) opts.keywords.add(keyword, keyword, keyword);
				if (options?.default) opts.keywords.default = opts.keywords.findByGlobalName(options.default);
				const r = await editor.getKeywords(opts);
				if (r.status === AcEdPromptStatus.None && options?.default) return options.default;
				if (r.status !== AcEdPromptStatus.OK || !r.stringResult) throw new Error('Keyword cancelled');
				return r.stringResult;
			},
			getEntity: async prompt => {
				const r = await editor.getEntity(new AcEdPromptEntityOptions(prompt));
				if (r.status !== AcEdPromptStatus.OK || !r.objectId) throw new Error('Entity selection cancelled');
				const entity = db.tables.blockTable.modelSpace.getIdAt(r.objectId);
				if (!entity) throw new Error('Entity no longer exists');
				if (r.pickedPoint) {
					(entity as unknown as { pickedPoint?: CadPoint3 }).pickedPoint = new AcGePoint3d(r.pickedPoint);
				}
				return entity;
			},
			getEntityPick: async (prompt, options) => {
				const opts = new AcEdPromptEntityOptions(prompt);
				if (options?.allowNone) opts.allowNone = true;
				if (options?.keywords) {
					for (const kw of options.keywords) opts.keywords.add(kw, kw, kw);
				}
				const r = await editor.getEntity(opts);
				if (r.status === AcEdPromptStatus.Keyword) {
					return { status: 'keyword', keyword: r.stringResult };
				}
				if (r.status === AcEdPromptStatus.None) {
					return { status: 'none' };
				}
				if (r.status !== AcEdPromptStatus.OK || !r.objectId) {
					return { status: 'cancel' };
				}
				const entity = db.tables.blockTable.modelSpace.getIdAt(r.objectId);
				if (!entity) return { status: 'cancel' };
				const point = r.pickedPoint ? new AcGePoint3d(r.pickedPoint) : undefined;
				return { status: 'ok', entity, point };
			},
			transaction: async fn => fn(), // AcEdCommand.trigger owns the single undo transaction.
			message: text => this.showMessage(text),
			database: {
				add: entity => db.tables.blockTable.modelSpace.appendEntity(entity as AcDbEntity[]),
				replace: (id, entity) => { const old = db.openEntityForWrite(id); if (!old) throw new Error(`Entity ${id} not found`); old.erase(); db.tables.blockTable.modelSpace.appendEntity(entity); },
				erase: id => { const entity = db.openEntityForWrite(id); entity?.erase(); },
				get: id => db.tables.blockTable.modelSpace.getIdAt(id),
				all: () => db.tables.blockTable.modelSpace.newIterator().toArray(),
			},
		};
		try { await this.run(ctx); }
		catch (error) { if (!(error instanceof Error) || !/cancelled/i.test(error.message)) throw error; }
	}
}

/** Register a command in mlightcad's native command stack. Call after opening the editor. */
export function registerCommand(name: string, run: (ctx: CadCommandContext) => Promise<void>, options: CadCommandOptions = {}): void {
	const manager = AcApDocManager.instance;
	const command = new CallbackCommand(run, name.toUpperCase());
	command.globalName = name.toUpperCase();
	command.localName = options.localName ?? name.toUpperCase();
	command.mode = options.mode ?? AcEdOpenMode.Write;
	manager.commandManager.addCommand(options.group ?? 'USER', command.globalName, command.localName, command, options.aliases ? [...options.aliases] : undefined);
}

/** Pure geometry helper used by MIRROR and its node tests. */
function mirrorEntity(source: AcDbEntity, a: CadPoint3, b: CadPoint3): AcDbEntity {
	const clone = source.clone() as AcDbEntity;
	const dx = b.x - a.x, dy = b.y - a.y, angle = Math.atan2(dy, dx);
	const c = Math.cos(2 * angle), s = Math.sin(2 * angle);
	const matrix = new AcGeMatrix3d(
		c, s, 0, 0, s, -c, 0, 0, 0, 0, -1, 0,
		2 * (a.x - (c * a.x + s * a.y)), 2 * (a.y - (s * a.x - c * a.y)), 0, 1,
	);
	clone.transformBy(matrix);
	return clone;
}

/** AutoCAD-style MIRROR. Text is reflected geometrically, matching the library transform behavior. */
export async function mirrorCommand(ctx: CadCommandContext): Promise<void> {
	const selected = await ctx.getSelection('Select objects to mirror:');
	const first = await ctx.getPoint('Specify first point of mirror line:');
	const second = await ctx.getPoint('Specify second point of mirror line:', { base: first });
	const choice = await ctx.getKeyword('Erase source objects? [Yes/No] <No>', ['Yes', 'No'], { default: 'No' });
	const copies = selected.map(entity => mirrorEntity(entity, first, second));
	await ctx.transaction(async () => {
		ctx.database.add(copies);
		if (choice.toLowerCase() === 'yes') for (const entity of selected) ctx.database.erase(String(entity.objectId));
	});
}

function entityToGeom(e: AcDbEntity): GeomShape | undefined {
	if (e instanceof AcDbLine || e.dxfTypeName === 'LINE') {
		const line = e as AcDbLine;
		return {
			kind: 'line',
			start: [line.startPoint.x, line.startPoint.y],
			end: [line.endPoint.x, line.endPoint.y],
		};
	}
	if (e instanceof AcDbArc || e.dxfTypeName === 'ARC') {
		const arc = e as AcDbArc;
		return {
			kind: 'arc',
			center: [arc.center.x, arc.center.y],
			radius: arc.radius,
			startAngle: normalizeAngle(arc.startAngle * 180 / Math.PI),
			endAngle: normalizeAngle(arc.endAngle * 180 / Math.PI),
		};
	}
	if (e instanceof AcDbCircle || e.dxfTypeName === 'CIRCLE') {
		const circle = e as AcDbCircle;
		return {
			kind: 'circle',
			center: [circle.center.x, circle.center.y],
			radius: circle.radius,
		};
	}
	if (e instanceof AcDbPolyline || e.dxfTypeName === 'LWPOLYLINE') {
		const poly = e as AcDbPolyline;
		const points: GeomPoint[] = [];
		for (let i = 0; i < poly.numberOfVertices; i++) {
			const p = poly.getPoint2dAt(i);
			points.push([p.x, p.y]);
		}
		return {
			kind: 'polyline',
			points,
			closed: poly.closed,
		};
	}
	return undefined;
}

function geomToEntity(shape: GeomShape, original?: AcDbEntity): AcDbEntity {
	let ent: AcDbEntity;
	if (shape.kind === 'line') {
		ent = new AcDbLine(
			new AcGePoint3d(shape.start[0], shape.start[1], 0),
			new AcGePoint3d(shape.end[0], shape.end[1], 0),
		);
	} else if (shape.kind === 'arc') {
		ent = new AcDbArc(
			new AcGePoint3d(shape.center[0], shape.center[1], 0),
			shape.radius,
			shape.startAngle * Math.PI / 180,
			shape.endAngle * Math.PI / 180,
		);
	} else if (shape.kind === 'circle') {
		ent = new AcDbCircle(
			new AcGePoint3d(shape.center[0], shape.center[1], 0),
			shape.radius,
		);
	} else if (shape.kind === 'polyline') {
		const poly = new AcDbPolyline();
		poly.closed = !!shape.closed;
		for (let i = 0; i < shape.points.length; i++) {
			poly.addVertexAt(i, new AcGePoint2d(shape.points[i][0], shape.points[i][1]));
		}
		ent = poly;
	} else {
		throw new Error('Unsupported geometry');
	}
	if (original) {
		try {
			if (original.layer) ent.layer = original.layer;
			if (original.color !== undefined) ent.color = original.color;
			if (original.lineType) ent.lineType = original.lineType;
		} catch {
			// ignore property copy errors
		}
	}
	return ent;
}

/** AutoCAD-style TRIM: "all objects are cutting edges" mode; repeatedly pick objects to trim. Enter/Esc ends. */
export async function trimCommand(ctx: CadCommandContext): Promise<void> {
	while (true) {
		const pick = await ctx.getEntityPick('Select object to trim or [Enter to exit]:', { allowNone: true });
		if (pick.status === 'cancel' || pick.status === 'none' || !pick.entity || !pick.point) {
			break;
		}
		const pickedGeom = entityToGeom(pick.entity);
		if (!pickedGeom) {
			ctx.message('Selected object cannot be trimmed');
			continue;
		}
		const pickPt: GeomPoint = [pick.point.x, pick.point.y];
		const allEntities = ctx.database.all();
		const cutters = allEntities
			.filter(e => String(e.objectId) !== String(pick.entity!.objectId))
			.map(entityToGeom)
			.filter((g): g is GeomShape => !!g);

		if (pickedGeom.kind === 'line') {
			const pieces = trimLine(pickedGeom, cutters, pickPt);
			if (pieces.length === 0) {
				ctx.database.erase(String(pick.entity.objectId));
			} else if (pieces.length === 1) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(pieces[0], pick.entity));
			} else {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(pieces[0], pick.entity));
				ctx.database.add(pieces.slice(1).map(p => geomToEntity(p, pick.entity)));
			}
		} else if (pickedGeom.kind === 'circle') {
			const arc = trimCircle(pickedGeom, cutters, pickPt);
			if (arc) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(arc, pick.entity));
			}
		} else if (pickedGeom.kind === 'arc') {
			const pieces = trimArc(pickedGeom, cutters, pickPt);
			if (pieces.length === 0) {
				ctx.database.erase(String(pick.entity.objectId));
			} else if (pieces.length === 1) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(pieces[0], pick.entity));
			} else {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(pieces[0], pick.entity));
				ctx.database.add(pieces.slice(1).map(p => geomToEntity(p, pick.entity)));
			}
		} else if (pickedGeom.kind === 'polyline') {
			const pieces = trimPolyline(pickedGeom, cutters, pickPt);
			if (pieces.length === 0) {
				ctx.database.erase(String(pick.entity.objectId));
			} else if (pieces.length === 1) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(pieces[0], pick.entity));
			} else {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(pieces[0], pick.entity));
				ctx.database.add(pieces.slice(1).map(p => geomToEntity(p, pick.entity)));
			}
		}
	}
}

/** AutoCAD-style EXTEND: pick near the end of an object to extend it to the nearest boundary. Enter/Esc ends. */
export async function extendCommand(ctx: CadCommandContext): Promise<void> {
	while (true) {
		const pick = await ctx.getEntityPick('Select object to extend or [Enter to exit]:', { allowNone: true });
		if (pick.status === 'cancel' || pick.status === 'none' || !pick.entity || !pick.point) {
			break;
		}
		const pickedGeom = entityToGeom(pick.entity);
		if (!pickedGeom) {
			ctx.message('Selected object cannot be extended');
			continue;
		}
		const pickPt: GeomPoint = [pick.point.x, pick.point.y];
		const allEntities = ctx.database.all();
		const boundaries = allEntities
			.filter(e => String(e.objectId) !== String(pick.entity!.objectId))
			.map(entityToGeom)
			.filter((g): g is GeomShape => !!g);

		if (pickedGeom.kind === 'line') {
			const ext = extendLine(pickedGeom, boundaries, pickPt);
			if (ext) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(ext, pick.entity));
			}
		} else if (pickedGeom.kind === 'arc') {
			const ext = extendArc(pickedGeom, boundaries, pickPt);
			if (ext) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(ext, pick.entity));
			}
		} else if (pickedGeom.kind === 'polyline') {
			const ext = extendPolyline(pickedGeom, boundaries, pickPt);
			if (ext) {
				ctx.database.replace(String(pick.entity.objectId), geomToEntity(ext, pick.entity));
			}
		}
	}
}

let currentFilletRadius = 0;

/** AutoCAD-style FILLET: remember radius (default 0), pick two lines to fillet. */
export async function filletCommand(ctx: CadCommandContext): Promise<void> {
	let pick1: { entity: AcDbEntity; point: CadPoint3 } | undefined;
	while (!pick1) {
		const res = await ctx.getEntityPick(`Select first line or [Radius] <${currentFilletRadius}>:`, {
			keywords: ['Radius'],
		});
		if (res.status === 'cancel' || res.status === 'none') return;
		if (res.status === 'keyword') {
			const r = await ctx.getDistance(`Specify fillet radius <${currentFilletRadius}>:`);
			currentFilletRadius = Math.max(0, r);
			continue;
		}
		if (res.status === 'ok' && res.entity && res.point) {
			pick1 = { entity: res.entity, point: res.point };
		}
	}

	const res2 = await ctx.getEntityPick('Select second line:');
	if (res2.status !== 'ok' || !res2.entity || !res2.point) return;

	const geom1 = entityToGeom(pick1.entity);
	const geom2 = entityToGeom(res2.entity);
	if (geom1?.kind !== 'line' || geom2?.kind !== 'line') {
		ctx.message('FILLET requires two lines');
		return;
	}

	const p1: GeomPoint = [pick1.point.x, pick1.point.y];
	const p2: GeomPoint = [res2.point.x, res2.point.y];
	const filleted = filletLines(geom1, geom2, currentFilletRadius, p1, p2);
	if (!filleted) {
		ctx.message('Lines cannot be filleted');
		return;
	}

	ctx.database.replace(String(pick1.entity.objectId), geomToEntity(filleted.lines[0], pick1.entity));
	ctx.database.replace(String(res2.entity.objectId), geomToEntity(filleted.lines[1], res2.entity));
	if (filleted.arc) {
		ctx.database.add(geomToEntity(filleted.arc, pick1.entity));
	}
}

let currentChamferDist1 = 0;
let currentChamferDist2 = 0;

/** AutoCAD-style CHAMFER: remember distances (default 0), pick two lines to chamfer. */
export async function chamferCommand(ctx: CadCommandContext): Promise<void> {
	let pick1: { entity: AcDbEntity; point: CadPoint3 } | undefined;
	while (!pick1) {
		const res = await ctx.getEntityPick(`Select first line or [Distance] <${currentChamferDist1}, ${currentChamferDist2}>:`, {
			keywords: ['Distance'],
		});
		if (res.status === 'cancel' || res.status === 'none') return;
		if (res.status === 'keyword') {
			const d1 = await ctx.getDistance(`Specify first chamfer distance <${currentChamferDist1}>:`);
			currentChamferDist1 = Math.max(0, d1);
			const d2 = await ctx.getDistance(`Specify second chamfer distance <${currentChamferDist2}>:`);
			currentChamferDist2 = Math.max(0, d2);
			continue;
		}
		if (res.status === 'ok' && res.entity && res.point) {
			pick1 = { entity: res.entity, point: res.point };
		}
	}

	const res2 = await ctx.getEntityPick('Select second line:');
	if (res2.status !== 'ok' || !res2.entity || !res2.point) return;

	const geom1 = entityToGeom(pick1.entity);
	const geom2 = entityToGeom(res2.entity);
	if (geom1?.kind !== 'line' || geom2?.kind !== 'line') {
		ctx.message('CHAMFER requires two lines');
		return;
	}

	const p1: GeomPoint = [pick1.point.x, pick1.point.y];
	const p2: GeomPoint = [res2.point.x, res2.point.y];
	const chamfered = chamferLines(geom1, geom2, currentChamferDist1, currentChamferDist2, p1, p2);
	if (!chamfered) {
		ctx.message('Lines cannot be chamfered');
		return;
	}

	ctx.database.replace(String(pick1.entity.objectId), geomToEntity(chamfered.lines[0], pick1.entity));
	ctx.database.replace(String(res2.entity.objectId), geomToEntity(chamfered.lines[1], res2.entity));
	if (chamfered.chamferLine) {
		ctx.database.add(geomToEntity(chamfered.chamferLine, pick1.entity));
	}
}
