/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcCmColor, AcCmColorMethod,
	AcDbBlockReference, AcDbBlockTableRecord, AcDbBlockTableRecordFlag,
	AcDbDatabase, AcDbEntity, AcDbFileType, AcGePoint3d,
} from '@mlightcad/data-model';
import { AcDbRenderingCache } from '@mlightcad/data-model';
import type { CadCommandContext, CadPoint3 } from './commands.js';
import { UNDERLAY_ACI } from './underlay.js';

export interface XrefInfo {
	readonly name: string;
	readonly pathName: string;
	readonly isOverlay: boolean;
	readonly isResolved: boolean;
	readonly flags: number;
}

export function listXrefs(db: AcDbDatabase): XrefInfo[] {
	const results: XrefInfo[] = [];
	for (const record of db.tables.blockTable.newIterator()) {
		const isXref = record.isXref || ((record.flags & AcDbBlockTableRecordFlag.Xref) !== 0);
		if (isXref) {
			results.push({
				name: record.name,
				pathName: record.pathName || '',
				isOverlay: record.isOverlayReference || ((record.flags & AcDbBlockTableRecordFlag.XrefOverlay) !== 0),
				isResolved: !record.isUnresolvedXref,
				flags: record.flags,
			});
		}
	}
	return results;
}

export async function attachXref(
	db: AcDbDatabase,
	options: {
		readonly name: string;
		readonly path: string;
		readonly dxfText: string;
		readonly isOverlay?: boolean;
		readonly insertion?: CadPoint3;
		readonly scale?: number;
		readonly rotation?: number;
	},
): Promise<{ record: AcDbBlockTableRecord; reference: AcDbBlockReference }> {
	const table = db.tables.blockTable;
	if (table.has(options.name)) {
		throw new Error(`Block or xref "${options.name}" already exists`);
	}

	const tempDb = new AcDbDatabase();
	await tempDb.read(options.dxfText, { readOnly: true }, AcDbFileType.DXF);

	const baseFlags = options.isOverlay
		? (AcDbBlockTableRecordFlag.Xref | AcDbBlockTableRecordFlag.XrefOverlay | AcDbBlockTableRecordFlag.Resolved)
		: (AcDbBlockTableRecordFlag.Xref | AcDbBlockTableRecordFlag.Resolved);

	const record = new AcDbBlockTableRecord({
		name: options.name,
		pathName: options.path,
		flags: baseFlags,
		origin: new AcGePoint3d(0, 0, 0),
	});

	// Populate record with greyed entities from parsed DXF
	for (const ent of tempDb.tables.blockTable.modelSpace.newIterator()) {
		const clone = ent.clone() as AcDbEntity;
		try {
			clone.color = new AcCmColor(AcCmColorMethod.ByACI, UNDERLAY_ACI);
		} catch {}
		record.appendEntity(clone);
	}

	table.add(record);

	const ins = options.insertion ?? { x: 0, y: 0, z: 0 };
	const sc = options.scale ?? 1;
	const rot = options.rotation ?? 0;

	const ref = new AcDbBlockReference(options.name);
	ref.position = new AcGePoint3d(ins.x, ins.y, ins.z ?? 0);
	ref.scaleFactors = new AcGePoint3d(sc, sc, 1);
	ref.rotation = rot;
	table.modelSpace.appendEntity(ref);

	try { AcDbRenderingCache.instance?.clear(); } catch {}
	return { record, reference: ref };
}

export function bindXref(db: AcDbDatabase, name: string): AcDbBlockTableRecord {
	const record = db.tables.blockTable.getAt(name);
	if (!record) {
		throw new Error(`Xref "${name}" does not exist`);
	}
	const isXref = record.isXref || ((record.flags & AcDbBlockTableRecordFlag.Xref) !== 0);
	if (!isXref) {
		throw new Error(`Block "${name}" is not an external reference`);
	}

	// Turn xref into a normal block: clear xref flags and empty pathName
	record.flags = record.flags & ~(
		AcDbBlockTableRecordFlag.Xref |
		AcDbBlockTableRecordFlag.XrefOverlay |
		AcDbBlockTableRecordFlag.Resolved |
		AcDbBlockTableRecordFlag.Referenced |
		AcDbBlockTableRecordFlag.ExternallyDependent
	);
	record.pathName = '';
	try { AcDbRenderingCache.instance?.clear(); } catch {}
	return record;
}

export function detachXref(db: AcDbDatabase, name: string): void {
	const record = db.tables.blockTable.getAt(name);
	if (!record) {
		throw new Error(`Xref "${name}" does not exist`);
	}
	const isXref = record.isXref || ((record.flags & AcDbBlockTableRecordFlag.Xref) !== 0);
	if (!isXref) {
		throw new Error(`Block "${name}" is not an external reference`);
	}

	// Remove all references from model space
	for (const ent of db.tables.blockTable.modelSpace.newIterator()) {
		if (ent instanceof AcDbBlockReference && ent.blockName.toUpperCase() === name.toUpperCase()) {
			ent.erase();
		}
	}

	db.tables.blockTable.remove(name);
	try { AcDbRenderingCache.instance?.clear(); } catch {}
}

export async function reloadXref(
	db: AcDbDatabase,
	name: string,
	readFile: (path: string) => Promise<string>,
): Promise<AcDbBlockTableRecord> {
	const record = db.tables.blockTable.getAt(name);
	if (!record) {
		throw new Error(`Xref "${name}" does not exist`);
	}
	const isXref = record.isXref || ((record.flags & AcDbBlockTableRecordFlag.Xref) !== 0);
	if (!isXref) {
		throw new Error(`Block "${name}" is not an external reference`);
	}
	if (!record.pathName) {
		throw new Error(`Xref "${name}" has no path configured`);
	}

	const dxfText = await readFile(record.pathName);
	const tempDb = new AcDbDatabase();
	await tempDb.read(dxfText, { readOnly: true }, AcDbFileType.DXF);

	// Remove old entities from record
	const oldEntities = Array.from(record.newIterator()) as AcDbEntity[];
	for (const ent of oldEntities) {
		record.removeEntity(ent.objectId);
	}

	// Add updated greyed entities
	for (const ent of tempDb.tables.blockTable.modelSpace.newIterator()) {
		const clone = ent.clone() as AcDbEntity;
		try {
			clone.color = new AcCmColor(AcCmColorMethod.ByACI, UNDERLAY_ACI);
		} catch {}
		record.appendEntity(clone);
	}

	try { AcDbRenderingCache.instance?.clear(); } catch {}
	return record;
}

/**
 * XREF / -XREF command: Attach, List (?), Detach, Reload, Bind, and Overlay.
 */
export async function xrefCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const option = (await ctx.getKeyword(
		'Enter an option [Attach/Overlay/Bind/Detach/Reload/?] <Attach>:',
		['Attach', 'Overlay', 'Bind', 'Detach', 'Reload', '?'],
		{ default: 'Attach' },
	)).toLowerCase();

	if (option === '?' || option === 'list') {
		const xrefs = listXrefs(db);
		if (xrefs.length === 0) {
			ctx.message('No external references found in drawing.');
			return;
		}
		const lines = xrefs.map(x =>
			`  ${x.name} [${x.isOverlay ? 'Overlay' : 'Attach'}]: "${x.pathName}" (flags: ${x.flags})`,
		);
		ctx.message(`External references (${xrefs.length}):\n${lines.join('\n')}`);
		return;
	}

	if (option === 'attach' || option === 'overlay') {
		if (!ctx.readFile) {
			ctx.message('File reading callback is not configured.');
			return;
		}
		const filePath = (await ctx.getString('Enter file path to attach:', { allowSpaces: true })).trim();
		if (!filePath) throw new Error('File path cannot be empty');

		const baseName = filePath.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^/.]+$/, '') || 'XREF1';
		const namePrompt = `Enter xref block name <${baseName}>:`;
		const customName = (await ctx.getString(namePrompt, { allowSpaces: false, allowEmpty: true, defaultValue: baseName })).trim() || baseName;

		const ins = await ctx.getPoint('Specify insertion point <0,0,0>:', { allowNone: true }) ?? { x: 0, y: 0, z: 0 };
		const scaleRaw = await ctx.getString('Specify scale factor <1>:', { allowSpaces: false, allowEmpty: true, defaultValue: '1' });
		const scale = scaleRaw.trim() ? Number(scaleRaw) : 1;
		const rot = await ctx.getAngle('Specify rotation angle <0>:');

		let dxfText: string;
		try {
			dxfText = await ctx.readFile(filePath);
		} catch (err) {
			throw new Error(`Failed to read file "${filePath}": ${(err as Error).message}`);
		}

		await ctx.transaction(async () => {
			await attachXref(db, {
				name: customName,
				path: filePath,
				dxfText,
				isOverlay: option === 'overlay',
				insertion: ins,
				scale,
				rotation: rot,
			});
		});
		ctx.message(`Xref "${customName}" attached from "${filePath}".`);
		return;
	}

	if (option === 'bind') {
		const name = (await ctx.getString('Enter block name of xref to bind:', { allowSpaces: false })).trim();
		await ctx.transaction(async () => {
			bindXref(db, name);
		});
		ctx.message(`Xref "${name}" bound into normal block.`);
		return;
	}

	if (option === 'detach') {
		const name = (await ctx.getString('Enter block name of xref to detach:', { allowSpaces: false })).trim();
		await ctx.transaction(async () => {
			detachXref(db, name);
		});
		ctx.message(`Xref "${name}" detached.`);
		return;
	}

	if (option === 'reload') {
		if (!ctx.readFile) {
			ctx.message('File reading callback is not configured.');
			return;
		}
		const name = (await ctx.getString('Enter block name of xref to reload:', { allowSpaces: false })).trim();
		await ctx.transaction(async () => {
			await reloadXref(db, name, ctx.readFile!);
		});
		ctx.message(`Xref "${name}" reloaded.`);
		return;
	}
}
