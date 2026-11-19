/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbArc,
	AcDbCircle,
	AcDbDatabase,
	AcDbEntity,
	AcDbGroup,
	AcDbLine,
	AcDbPolyline,
	AcDbResultBuffer,
	AcDbXrecord,
	AcGeMatrix3d,
	AcGePoint3d,
} from '@mlightcad/data-model';
import { CadCommandContext, registerCommand } from './commands.js';
import { rectangularArray } from './modifyGeometry2.js';
import { cloneTransform, pointTransform, translation } from './commands.js';

export interface RectangularArrayParams {
	readonly rows: number;
	readonly columns: number;
	readonly rowSpacing: number;
	readonly columnSpacing: number;
}

export interface PolarArrayParams {
	readonly center: [number, number];
	readonly count: number;
	readonly fillAngle: number;
	readonly rotateItems: boolean;
}

export interface ArrayDefinition {
	readonly groupName: string;
	readonly type: 'rectangular' | 'polar' | 'path';
	readonly sourceIds: readonly string[];
	readonly itemIds: readonly string[];
	readonly rectangular?: RectangularArrayParams;
	readonly polar?: PolarArrayParams;
}

let arrayCounter = 1;

export function getNextArrayGroupName(db: AcDbDatabase): string {
	while (db.objects?.group?.has(`*A${arrayCounter}`)) {
		arrayCounter++;
	}
	return `*A${arrayCounter++}`;
}

/**
 * Saves array definition into AcDbXrecord in db.objects.xrecord.
 */
export function saveArrayDefinition(db: AcDbDatabase, def: ArrayDefinition): void {
	if (!db.objects?.xrecord) return;
	const key = `SA_ARRAY_${def.groupName}`;
	const json = JSON.stringify(def);
	const xrec = new AcDbXrecord();
	const buf = new AcDbResultBuffer();
	const CHUNK_SIZE = 250;
	for (let i = 0; i < json.length; i += CHUNK_SIZE) {
		buf.add({ code: 1, value: json.slice(i, i + CHUNK_SIZE) });
	}
	xrec.data = buf;
	db.objects.xrecord.setAt(key, xrec);
}

/**
 * Loads array definition from AcDbXrecord in db.objects.xrecord.
 */
export function loadArrayDefinition(db: AcDbDatabase, groupName: string): ArrayDefinition | undefined {
	if (!db.objects?.xrecord) return undefined;
	const key = `SA_ARRAY_${groupName}`;
	const xrec = db.objects.xrecord.getAt(key);
	if (!xrec?.data) return undefined;
	const chunks: string[] = [];
	for (const item of xrec.data) {
		if (typeof item.value === 'string') {
			chunks.push(item.value);
		}
	}
	try {
		return JSON.parse(chunks.join('')) as ArrayDefinition;
	} catch {
		return undefined;
	}
}

/**
 * Finds the array definition and group that contains a given entity ID.
 */
export function findArrayByEntityId(
	db: AcDbDatabase,
	entityId: string,
): { group: AcDbGroup; def: ArrayDefinition } | undefined {
	if (!db.objects?.group) return undefined;
	for (const [name, grp] of db.objects.group.entries()) {
		if (grp.entityIds?.includes(entityId as any)) {
			const def = loadArrayDefinition(db, name);
			if (def) {
				return { group: grp, def };
			}
		}
	}
	return undefined;
}

/**
 * Removes an array group and its xrecord, leaving plain entities (EXPLODE support).
 */
export function explodeArrayGroup(db: AcDbDatabase, groupName: string): boolean {
	let removed = false;
	if (db.objects?.group?.has(groupName)) {
		db.objects.group.remove(groupName);
		removed = true;
	}
	const key = `SA_ARRAY_${groupName}`;
	if (db.objects?.xrecord?.has(key)) {
		db.objects.xrecord.remove(key);
	}
	return removed;
}

/**
 * Generates copies for a rectangular array and registers group and Xrecord.
 */
export function createRectangularArray(
	db: AcDbDatabase,
	sourceEntities: readonly AcDbEntity[],
	rows: number,
	columns: number,
	rowSpacing: number,
	columnSpacing: number,
): { group: AcDbGroup; def: ArrayDefinition; copies: readonly AcDbEntity[] } {
	const copies: AcDbEntity[] = [];
	const offsets = rectangularArray(sourceEntities, rows, columns, rowSpacing, columnSpacing);
	for (const { item, offset } of offsets) {
		copies.push(cloneTransform(item, translation(...offset)));
	}

	for (const c of copies) {
		db.tables.blockTable.modelSpace.appendEntity(c);
	}

	const sourceIds = sourceEntities.map(e => String(e.objectId));
	const copyIds = copies.map(e => String(e.objectId));
	const allIds = [...sourceIds, ...copyIds];

	const groupName = getNextArrayGroupName(db);
	const group = new AcDbGroup();
	group.name = groupName;
	group.selectable = true;
	for (const id of allIds) {
		group.addEntityId(id as any);
	}
	db.objects.group.setAt(groupName, group);

	const def: ArrayDefinition = {
		groupName,
		type: 'rectangular',
		sourceIds,
		itemIds: allIds,
		rectangular: { rows, columns, rowSpacing, columnSpacing },
	};
	saveArrayDefinition(db, def);

	return { group, def, copies };
}

/**
 * Regenerates copies for an existing rectangular array definition in one undoable step.
 */
export function updateRectangularArray(
	db: AcDbDatabase,
	def: ArrayDefinition,
	params: Partial<RectangularArrayParams>,
): { group: AcDbGroup; def: ArrayDefinition; totalCount: number } {
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace) throw new Error('Model space not available');

	const rows = params.rows ?? def.rectangular?.rows ?? 1;
	const columns = params.columns ?? def.rectangular?.columns ?? 1;
	const rowSpacing = params.rowSpacing ?? def.rectangular?.rowSpacing ?? 0;
	const columnSpacing = params.columnSpacing ?? def.rectangular?.columnSpacing ?? 0;

	// Locate source entities
	const sourceEntities: AcDbEntity[] = [];
	for (const sId of def.sourceIds) {
		for (const ent of modelSpace.newIterator()) {
			if (String(ent.objectId) === sId) {
				sourceEntities.push(ent);
				break;
			}
		}
	}
	if (sourceEntities.length === 0) {
		throw new Error('Source entities for array could not be found');
	}

	// Erase previous copy entities
	const sourceSet = new Set(def.sourceIds);
	for (const ent of Array.from(modelSpace.newIterator())) {
		const id = String(ent.objectId);
		if (def.itemIds.includes(id) && !sourceSet.has(id)) {
			ent.erase();
		}
	}

	// Generate new copies
	const newCopies: AcDbEntity[] = [];
	const offsets = rectangularArray(sourceEntities, rows, columns, rowSpacing, columnSpacing);
	for (const { item, offset } of offsets) {
		const clone = cloneTransform(item, translation(...offset));
		modelSpace.appendEntity(clone);
		newCopies.push(clone);
	}

	const newCopyIds = newCopies.map(e => String(e.objectId));
	const allIds = [...def.sourceIds, ...newCopyIds];

	// Update AcDbGroup
	const group = db.objects.group.getAt(def.groupName) ?? new AcDbGroup();
	group.name = def.groupName;
	group.selectable = true;
	group.entityIds = allIds as any;
	db.objects.group.setAt(def.groupName, group);

	// Update Xrecord
	const updatedDef: ArrayDefinition = {
		...def,
		itemIds: allIds,
		rectangular: { rows, columns, rowSpacing, columnSpacing },
	};
	saveArrayDefinition(db, updatedDef);

	return { group, def: updatedDef, totalCount: allIds.length };
}

/**
 * ARRAY command: prompts for type [Rectangular/PAth/POlar] and sets up grouped array.
 */
export async function arrayCommand(ctx: CadCommandContext): Promise<void> {
	const type = await ctx.getKeyword('Enter array type [Rectangular/PAth/POlar] <Rectangular>:', ['Rectangular', 'PAth', 'POlar'], { default: 'Rectangular' });
	if (type.toLowerCase() === 'rectangular') {
		const src = await ctx.getSelection('Select objects to array:');
		if (src.length === 0) return;
		const rows = Math.max(1, Math.round(await ctx.getDistance('Rows <1>:')));
		const columns = Math.max(1, Math.round(await ctx.getDistance('Columns <1>:')));
		const rowSpacing = await ctx.getDistance('Row spacing:');
		const columnSpacing = await ctx.getDistance('Column spacing:');

		await ctx.transaction(async () => {
			createRectangularArray(ctx.database.native, src, rows, columns, rowSpacing, columnSpacing);
		});
		ctx.message(`Created rectangular array (${rows} rows × ${columns} cols). Note: True associative arrays (AcDbAssocArray) are not supported by the data model; maintained via AcDbGroup and Xrecord.`);
	} else if (type.toLowerCase() === 'polar') {
		const src = await ctx.getSelection('Select objects to array:');
		if (src.length === 0) return;
		const center = await ctx.getPoint('Specify center point:');
		const count = Math.max(1, Math.round(await ctx.getDistance('Number of items:')));
		const fill = await ctx.getAngle('Angle to fill <360>:');
		const rotate = (await ctx.getKeyword('Rotate items? [Yes/No] <Yes>', ['Yes', 'No'], { default: 'Yes' })).toLowerCase() === 'yes';

		let sumX = 0, sumY = 0, ptCount = 0;
		for (const e of src) {
			if (e instanceof AcDbCircle || e instanceof AcDbArc) { sumX += e.center.x; sumY += e.center.y; ptCount++; }
			else if (e instanceof AcDbLine) { sumX += e.startPoint.x + e.endPoint.x; sumY += e.startPoint.y + e.endPoint.y; ptCount += 2; }
			else if (e instanceof AcDbPolyline) { for (let i = 0; i < e.numberOfVertices; i++) { const p = e.getPoint2dAt(i); sumX += p.x; sumY += p.y; ptCount++; } }
		}
		const refX = ptCount > 0 ? sumX / ptCount : center.x;
		const refY = ptCount > 0 ? sumY / ptCount : center.y;

		const copies: AcDbEntity[] = [];
		for (let i = 1; i < count; i++) {
			const a = fill * i / count;
			if (rotate) {
				const radial = pointTransform(center, 1, a, center);
				for (const e of src) copies.push(cloneTransform(e, radial));
			} else {
				const rad = a * Math.PI / 180;
				const rx = refX - center.x, ry = refY - center.y;
				const rotX = center.x + rx * Math.cos(rad) - ry * Math.sin(rad);
				const rotY = center.y + rx * Math.sin(rad) + ry * Math.cos(rad);
				const matrix = translation(rotX - refX, rotY - refY);
				for (const e of src) copies.push(cloneTransform(e, matrix));
			}
		}

		await ctx.transaction(async () => {
			for (const c of copies) ctx.database.native.tables.blockTable.modelSpace.appendEntity(c);
			const sourceIds = src.map(e => String(e.objectId));
			const allIds = [...sourceIds, ...copies.map(e => String(e.objectId))];
			const groupName = getNextArrayGroupName(ctx.database.native);
			const group = new AcDbGroup();
			group.name = groupName;
			group.selectable = true;
			for (const id of allIds) group.addEntityId(id as any);
			ctx.database.native.objects.group.setAt(groupName, group);
			saveArrayDefinition(ctx.database.native, {
				groupName,
				type: 'polar',
				sourceIds,
				itemIds: allIds,
				polar: { center: [center.x, center.y], count, fillAngle: fill, rotateItems: rotate },
			});
		});
		ctx.message(`Created polar array with ${count} items. Note: AcDbAssocArray is not supported by the data model.`);
	} else {
		ctx.message('Run ARRAYPATH directly for path array creation.');
	}
}

/**
 * ARRAYEDIT command: picks any item in an array, allows changing parameters, and regenerates copies.
 */
export async function arrayEditCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select array:');
	if (!pick.entity) return;

	const arrayInfo = findArrayByEntityId(ctx.database.native, String(pick.entity.objectId));
	if (!arrayInfo) {
		ctx.message('Selected entity is not part of an editable array.');
		return;
	}

	const { def } = arrayInfo;
	if (def.type === 'rectangular' && def.rectangular) {
		const opt = await ctx.getKeyword(
			'Enter an option [Columns/Rows/Spacing/Reset/eXit] <Columns>:',
			['Columns', 'Rows', 'Spacing', 'Reset', 'eXit'],
			{ default: 'Columns' },
		);

		if (opt.toLowerCase() === 'columns') {
			const cols = Math.max(1, Math.round(await ctx.getDistance(`Enter number of columns <${def.rectangular.columns}>:`)));
			const colSpacing = await ctx.getDistance(`Specify column spacing <${def.rectangular.columnSpacing}>:`);
			await ctx.transaction(async () => {
				const res = updateRectangularArray(ctx.database.native, def, {
					columns: cols,
					columnSpacing: colSpacing || def.rectangular?.columnSpacing,
				});
				ctx.message(`Array updated to ${res.totalCount} items.`);
			});
		} else if (opt.toLowerCase() === 'rows') {
			const rows = Math.max(1, Math.round(await ctx.getDistance(`Enter number of rows <${def.rectangular.rows}>:`)));
			const rowSpacing = await ctx.getDistance(`Specify row spacing <${def.rectangular.rowSpacing}>:`);
			await ctx.transaction(async () => {
				const res = updateRectangularArray(ctx.database.native, def, {
					rows,
					rowSpacing: rowSpacing || def.rectangular?.rowSpacing,
				});
				ctx.message(`Array updated to ${res.totalCount} items.`);
			});
		} else if (opt.toLowerCase() === 'spacing') {
			const colSpacing = await ctx.getDistance(`Specify column spacing <${def.rectangular.columnSpacing}>:`);
			const rowSpacing = await ctx.getDistance(`Specify row spacing <${def.rectangular.rowSpacing}>:`);
			await ctx.transaction(async () => {
				updateRectangularArray(ctx.database.native, def, { rowSpacing, columnSpacing: colSpacing });
			});
		} else if (opt.toLowerCase() === 'reset') {
			await ctx.transaction(async () => {
				updateRectangularArray(ctx.database.native, def, { rows: 1, columns: 1 });
			});
			ctx.message('Array reset to source item.');
		}
	} else {
		ctx.message(`ARRAYEDIT for ${def.type} arrays: parameter modification not supported.`);
	}
}

/**
 * ARRAYCLOSE command: closes array editing.
 */
export async function arrayCloseCommand(ctx: CadCommandContext): Promise<void> {
	ctx.message('Array editing closed.');
}

export function registerArrayCommands(): void {
	registerCommand('ARRAY', arrayCommand, { aliases: ['AR'] });
	registerCommand('ARRAYEDIT', arrayEditCommand);
	registerCommand('ARRAYCLOSE', arrayCloseCommand);
}
