/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbEntity, AcGeMatrix3d, AcGePoint3d, AcGePoint3dLike } from '@mlightcad/data-model';
import {
	AcApDocManager, AcEdCommand, AcEdOpenMode, AcEdPromptAngleOptions, AcEdPromptDistanceOptions,
	AcEdPromptEntityOptions, AcEdPromptKeywordOptions, AcEdPromptPointOptions, AcEdPromptSelectionOptions,
	AcEdPromptStatus,
} from '@mlightcad/cad-simple-viewer';

export type CadPoint3 = AcGePoint3dLike;
export type CadSelection = readonly AcDbEntity[];

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
	transaction<T>(fn: () => T | Promise<T>): Promise<T>;
	message(text: string): void;
	readonly database: {
		add(entity: AcDbEntity | readonly AcDbEntity[]): void;
		replace(id: string, entity: AcDbEntity): void;
		erase(id: string): void;
		get(id: string): AcDbEntity | undefined;
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
				if (!entity) throw new Error('Entity no longer exists'); return entity;
			},
			transaction: async fn => fn(), // AcEdCommand.trigger owns the single undo transaction.
			message: text => this.showMessage(text),
			database: {
				add: entity => db.tables.blockTable.modelSpace.appendEntity(entity as AcDbEntity[]),
				replace: (id, entity) => { const old = db.openEntityForWrite(id); if (!old) throw new Error(`Entity ${id} not found`); old.erase(); db.tables.blockTable.modelSpace.appendEntity(entity); },
				erase: id => { const entity = db.openEntityForWrite(id); entity?.erase(); },
				get: id => db.tables.blockTable.modelSpace.getIdAt(id),
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

const reflectPoint = (p: CadPoint3, a: CadPoint3, b: CadPoint3): AcGePoint3d => {
	const dx = b.x - a.x, dy = b.y - a.y, lenSq = dx * dx + dy * dy;
	if (lenSq < 1e-18) throw new Error('Mirror line points must be distinct');
	const t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
	const x = a.x + t * dx, y = a.y + t * dy;
	return new AcGePoint3d(2 * x - p.x, 2 * y - p.y, p.z);
};

/** Pure geometry helper used by MIRROR and its node tests. */
function mirrorEntity(source: AcDbEntity, a: CadPoint3, b: CadPoint3): AcDbEntity {
	const clone = source.clone() as AcDbEntity;
	const dx = b.x - a.x, dy = b.y - a.y, angle = Math.atan2(dy, dx);
	const c = Math.cos(2 * angle), s = Math.sin(2 * angle);
	const matrix = new AcGeMatrix3d(
		c, s, 0, 0, s, -c, 0, 0, 0, 0, -1, 0,
		2 * (a.x - (c * a.x + s * a.y)), 2 * (a.y - (s * a.x - c * a.y)), 0, 1,
	);
	// Reflection transforms are supported by the library entities; this correctly reverses arc sweep and polyline bulges.
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

