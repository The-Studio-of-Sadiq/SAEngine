/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbDatabase, AcDbLinetypeTableRecord, AcDbSystemVariables } from '@mlightcad/data-model';
import type { CadCommandContext } from './commands.js';

export interface BuiltinLinetypeDefinition {
	readonly name: string;
	readonly description: string;
	readonly totalPatternLength: number;
	readonly pattern: readonly number[];
}

/**
 * Standard metric (acadiso.lin) linetype definitions in drawing units (mm).
 * DASHED: dash 12.7, gap -6.35, total pattern length = 19.05 mm.
 */
export const ACADISO_LINETYPES: Record<string, BuiltinLinetypeDefinition> = {
	CONTINUOUS: {
		name: 'Continuous',
		description: 'Solid line',
		totalPatternLength: 0.0,
		pattern: [],
	},
	DASHED: {
		name: 'DASHED',
		description: 'Dashed __ __ __ __ __ __ __ __ __ __ __ __ __ _',
		totalPatternLength: 19.05,
		pattern: [12.7, -6.35],
	},
	DASHED2: {
		name: 'DASHED2',
		description: 'Dashed (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _',
		totalPatternLength: 9.525,
		pattern: [6.35, -3.175],
	},
	HIDDEN: {
		name: 'HIDDEN',
		description: 'Hidden __ __ __ __ __ __ __ __ __ __ __ __ __ __',
		totalPatternLength: 9.525,
		pattern: [6.35, -3.175],
	},
	HIDDEN2: {
		name: 'HIDDEN2',
		description: 'Hidden (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _',
		totalPatternLength: 4.7625,
		pattern: [3.175, -1.5875],
	},
	CENTER: {
		name: 'CENTER',
		description: 'Center ____ _ ____ _ ____ _ ____ _ ____ _ ____',
		totalPatternLength: 50.8,
		pattern: [31.75, -6.35, 6.35, -6.35],
	},
	CENTER2: {
		name: 'CENTER2',
		description: 'Center (.5x) ____ _ ____ _ ____ _ ____ _ ____',
		totalPatternLength: 25.4,
		pattern: [15.875, -3.175, 3.175, -3.175],
	},
	PHANTOM: {
		name: 'PHANTOM',
		description: 'Phantom ______  __  __  ______  __  __  ______',
		totalPatternLength: 63.5,
		pattern: [31.75, -6.35, 6.35, -6.35, 6.35, -6.35],
	},
	DOT: {
		name: 'DOT',
		description: 'Dot . . . . . . . . . . . . . . . . . . . . . . . .',
		totalPatternLength: 6.35,
		pattern: [0.0, -6.35],
	},
	DASHDOT: {
		name: 'DASHDOT',
		description: 'Dash dot __ . __ . __ . __ . __ . __ . __ . __',
		totalPatternLength: 25.4,
		pattern: [12.7, -6.35, 0.0, -6.35],
	},
	BORDER: {
		name: 'BORDER',
		description: 'Border __ __ . __ __ . __ __ . __ __ . __ __ .',
		totalPatternLength: 44.45,
		pattern: [12.7, -6.35, 12.7, -6.35, 0.0, -6.35],
	},
	DIVIDE: {
		name: 'DIVIDE',
		description: 'Divide __ . . __ . . __ . . __ . . __ . . __',
		totalPatternLength: 31.75,
		pattern: [12.7, -6.35, 0.0, -6.35, 0.0, -6.35],
	},
};

/**
 * Creates an AcDbLinetypeTableRecord from built-in acadiso.lin definitions.
 */
export function createLinetypeRecord(name: string): AcDbLinetypeTableRecord | undefined {
	const upper = name.toUpperCase();
	const def = ACADISO_LINETYPES[upper];
	if (!def) return undefined;
	return new AcDbLinetypeTableRecord({
		name: def.name,
		description: def.description,
		totalPatternLength: def.totalPatternLength,
		pattern: def.pattern.map(elementLength => ({ elementLength, elementTypeFlag: 0 })),
	});
}

/**
 * Loads a linetype from built-in acadiso definitions into the database's linetype table if not present.
 */
export function loadBuiltinLinetype(db: AcDbDatabase, name: string): AcDbLinetypeTableRecord | undefined {
	const table = db.tables?.linetypeTable;
	if (!table) return undefined;
	const existing = table.getAt(name);
	if (existing) return existing;
	const record = createLinetypeRecord(name);
	if (record) {
		table.add(record);
		return record;
	}
	return undefined;
}

/**
 * LINETYPE command (-LINETYPE): ?, Load from acadiso.lin, Set current.
 */
export async function linetypeCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const opt = await ctx.getKeyword('Enter an option [?/Load/Set] <Set>:', ['?', 'Load', 'Set'], { default: 'Set' });
	const upper = opt.toUpperCase();

	if (upper === '?') {
		const table = db.tables.linetypeTable;
		ctx.message('Loaded linetypes:');
		for (const rec of table.newIterator()) {
			const desc = (rec as any).comments || (rec as any).description || '(no description)';
			ctx.message(`  ${rec.name}: ${desc}`);
		}
		return;
	}

	if (upper === 'LOAD' || upper === 'L') {
		const name = await ctx.getString('Enter linetype name(s) to load:');
		const names = name.split(',').map(s => s.trim()).filter(Boolean);
		let loaded = 0;
		for (const n of names) {
			const rec = loadBuiltinLinetype(db, n);
			if (rec) {
				loaded++;
				ctx.message(`Linetype "${rec.name}" loaded.`);
			} else {
				ctx.message(`Linetype "${n}" not found in built-in definitions.`);
			}
		}
		if (loaded === 0 && names.length > 0) {
			throw new Error(`Failed to load requested linetype(s)`);
		}
		return;
	}

	if (upper === 'SET' || upper === 'S') {
		const current = db.celtype || 'ByLayer';
		const name = await ctx.getString(`Enter linetype name to set current <${current}>:`, { allowEmpty: true, defaultValue: current });
		const chosen = (name || current).trim();
		if (!chosen) return;
		const chosenUpper = chosen.toUpperCase();
		if (chosenUpper !== 'BYLAYER' && chosenUpper !== 'BYBLOCK') {
			if (!db.tables.linetypeTable.has(chosen)) {
				const loaded = loadBuiltinLinetype(db, chosen);
				if (!loaded) {
					throw new Error(`Linetype "${chosen}" is not loaded and not in built-in definitions`);
				}
			}
		}
		db.celtype = chosen;
		ctx.message(`Current linetype set to "${chosen}".`);
	}
}

/**
 * LTSCALE command: sets global drawing linetype scale.
 */
export async function ltscaleCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const current = db.ltscale ?? 1.0;
	const val = await ctx.getDouble(`Enter new linetype scale factor <${current}>:`);
	if (val <= 0) {
		throw new Error('Linetype scale factor must be positive');
	}
	db.ltscale = val;
	ctx.message(`LTSCALE set to ${val}.`);
}

/**
 * CELTSCALE command: sets current entity linetype scale.
 */
export async function celtscaleCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const current = db.celtscale ?? 1.0;
	const val = await ctx.getDouble(`Enter new entity linetype scale <${current}>:`);
	if (val <= 0) {
		throw new Error('Entity linetype scale must be positive');
	}
	db.celtscale = val;
	ctx.message(`CELTSCALE set to ${val}.`);
}
