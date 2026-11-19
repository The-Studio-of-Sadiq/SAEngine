/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbDatabase,
	AcDbDxfCode,
	AcDbEntity,
	AcDbMText,
	AcDbRegAppTableRecord,
	AcDbResultBuffer,
	AcDbText,
	AcGePoint3d,
} from '@mlightcad/data-model';
import { CadCommandContext, registerCommand } from './commands.js';
import { evaluateFieldsInText, FieldEvalContext } from './fieldEval.js';

export const FIELD_APPID = 'ACAD_FIELD';

function ensureFieldAppId(db: AcDbDatabase): void {
	if (db.tables?.appIdTable && !db.tables.appIdTable.has(FIELD_APPID)) {
		try {
			db.tables.appIdTable.add(new AcDbRegAppTableRecord(FIELD_APPID));
		} catch {}
	}
}

/**
 * Stores raw field template string in entity XData under ACAD_FIELD.
 */
export function setEntityFieldCode(db: AcDbDatabase, entity: AcDbEntity, fieldCode: string): void {
	ensureFieldAppId(db);
	const rb = new AcDbResultBuffer([
		{ code: AcDbDxfCode.ExtendedDataRegAppName, value: FIELD_APPID },
		{ code: AcDbDxfCode.ExtendedDataAsciiString, value: fieldCode },
	]);
	entity.setXData(rb);
}

/**
 * Retrieves raw field template string from entity XData under ACAD_FIELD, if present.
 */
export function getEntityFieldCode(entity: AcDbEntity): string | undefined {
	const rb = entity.getXData(FIELD_APPID);
	if (!rb) return undefined;
	for (const item of rb) {
		if (item.code === AcDbDxfCode.ExtendedDataAsciiString && typeof item.value === 'string') {
			return item.value;
		}
	}
	return undefined;
}

/**
 * Re-evaluates fields on specified entities (or all entities in drawing) and updates text.
 */
export function updateDrawingFields(db: AcDbDatabase, targetEntityIds?: ReadonlySet<string>): number {
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace) return 0;

	const ctx: FieldEvalContext = {
		database: db,
		date: new Date(),
	};

	let updatedCount = 0;
	for (const ent of modelSpace.newIterator()) {
		if (targetEntityIds && !targetEntityIds.has(String(ent.objectId))) {
			continue;
		}

		const fieldCode = getEntityFieldCode(ent);
		if (fieldCode) {
			const newVal = evaluateFieldsInText(fieldCode, ctx);
			if (ent instanceof AcDbMText && ent.contents !== newVal) {
				ent.contents = newVal;
				updatedCount++;
			} else if (ent instanceof AcDbText && ent.textString !== newVal) {
				ent.textString = newVal;
				updatedCount++;
			}
		} else if (ent instanceof AcDbMText && ent.contents?.includes('%<')) {
			const raw = ent.contents;
			const newVal = evaluateFieldsInText(raw, ctx);
			setEntityFieldCode(db, ent, raw);
			ent.contents = newVal;
			updatedCount++;
		} else if (ent instanceof AcDbText && ent.textString?.includes('%<')) {
			const raw = ent.textString;
			const newVal = evaluateFieldsInText(raw, ctx);
			setEntityFieldCode(db, ent, raw);
			ent.textString = newVal;
			updatedCount++;
		}
	}
	return updatedCount;
}

/**
 * FIELD command: inserts an MTEXT entity containing field expressions and evaluates them.
 */
export async function fieldCommand(ctx: CadCommandContext): Promise<void> {
	const pt = await ctx.getPoint('Specify insertion point:');
	const rawField = await ctx.getString('Enter field expression:');
	if (!rawField) return;

	const evalContext: FieldEvalContext = {
		database: ctx.database.native,
		date: new Date(),
	};

	const evaluated = evaluateFieldsInText(rawField, evalContext);

	const mtext = new AcDbMText();
	mtext.location = new AcGePoint3d(pt.x, pt.y, pt.z ?? 0);
	mtext.contents = evaluated;
	if (ctx.database.native.clayer) {
		mtext.layer = ctx.database.native.clayer;
	}

	setEntityFieldCode(ctx.database.native, mtext, rawField);

	await ctx.transaction(async () => {
		ctx.database.add(mtext);
	});
	ctx.message(`Field inserted with value: "${evaluated}"`);
}

/**
 * UPDATEFIELD command: updates fields in selected objects, or all fields in the drawing.
 */
export async function updatefieldCommand(ctx: CadCommandContext): Promise<void> {
	const selected = await ctx.getSelection('Select objects with fields (or press Enter for all):');
	let count = 0;
	await ctx.transaction(async () => {
		if (selected && selected.length > 0) {
			const ids = new Set(selected.map(e => String(e.objectId)));
			count = updateDrawingFields(ctx.database.native, ids);
		} else {
			count = updateDrawingFields(ctx.database.native);
		}
	});
	ctx.message(`${count} field(s) updated.`);
}

export function registerFieldCommands(): void {
	registerCommand('FIELD', fieldCommand);
	registerCommand('UPDATEFIELD', updatefieldCommand);
}
