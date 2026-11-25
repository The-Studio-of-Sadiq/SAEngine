/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcApDocManager } from '@mlightcad/cad-simple-viewer';
import type { CadCommandContext } from './commands.js';

export async function unitsCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database?.native ?? AcApDocManager.instance?.curDocument?.database;
	if (!db) return;

	const curLunits = db.lunits ?? 2;
	const curLuprec = db.luprec ?? 2;
	const curAunits = db.aunits ?? 0;
	const curAuprec = db.auprec ?? 0;
	const curAngbaseDeg = ((db.angbase ?? 0) * 180 / Math.PI) % 360;
	const curAngdir = db.angdir ?? 0;
	const curInsunits = db.insunits ?? 4; // 4 = Millimeters (SAEngine default)

	// 1. Linear units
	const lunitsStr = await ctx.getString(
		`Enter linear units (1 = Scientific, 2 = Decimal, 3 = Engineering, 4 = Architectural, 5 = Fractional) <${curLunits}>:`,
		{ allowEmpty: true, defaultValue: String(curLunits) },
	);
	const lunits = Math.max(1, Math.min(5, parseInt(lunitsStr.trim() || String(curLunits), 10)));
	db.lunits = lunits;

	// 2. Linear precision
	const luprecStr = await ctx.getString(
		`Enter linear unit precision (0 to 8) <${curLuprec}>:`,
		{ allowEmpty: true, defaultValue: String(curLuprec) },
	);
	const luprec = Math.max(0, Math.min(8, parseInt(luprecStr.trim() || String(curLuprec), 10)));
	db.luprec = luprec;

	// 3. Angular units
	const aunitsStr = await ctx.getString(
		`Enter angular units (0 = Decimal degrees, 1 = Deg/Min/Sec, 2 = Grads, 3 = Radians, 4 = Surveyor's) <${curAunits}>:`,
		{ allowEmpty: true, defaultValue: String(curAunits) },
	);
	const aunits = Math.max(0, Math.min(4, parseInt(aunitsStr.trim() || String(curAunits), 10)));
	db.aunits = aunits;

	// 4. Angular precision
	const auprecStr = await ctx.getString(
		`Enter angular unit precision (0 to 8) <${curAuprec}>:`,
		{ allowEmpty: true, defaultValue: String(curAuprec) },
	);
	const auprec = Math.max(0, Math.min(8, parseInt(auprecStr.trim() || String(curAuprec), 10)));
	db.auprec = auprec;

	// 5. Base angle
	const angbaseStr = await ctx.getString(
		`Enter base angle in degrees (0 = East, 90 = North, 180 = West, 270 = South) <${curAngbaseDeg.toFixed(0)}>:`,
		{ allowEmpty: true, defaultValue: String(curAngbaseDeg) },
	);
	const angbaseDeg = parseFloat(angbaseStr.trim() || String(curAngbaseDeg));
	db.angbase = (angbaseDeg * Math.PI) / 180;

	// 6. Direction
	const curClockwise = curAngdir === 1 ? 'Yes' : 'No';
	const angdirKeyword = await ctx.getKeyword(
		`Measure angles clockwise? [Yes/No] <${curClockwise}>:`,
		['Yes', 'No'],
		{ default: curClockwise },
	);
	db.angdir = angdirKeyword.toLowerCase() === 'yes' ? 1 : 0;

	// 7. Insertion units (INSUNITS: mm = 4 default for SAEngine)
	const insunitsStr = await ctx.getString(
		`Enter insertion units (0 = Unitless, 1 = Inches, 2 = Feet, 4 = Millimeters, 6 = Meters) <${curInsunits}>:`,
		{ allowEmpty: true, defaultValue: String(curInsunits) },
	);
	const insunits = parseInt(insunitsStr.trim() || String(curInsunits), 10);
	db.insunits = Number.isFinite(insunits) ? insunits : 4;

	ctx.message(
		`Drawing units updated: LUNITS=${db.lunits}, LUPREC=${db.luprec}, AUNITS=${db.aunits}, AUPREC=${db.auprec}, ANGBASE=${((db.angbase * 180 / Math.PI) % 360).toFixed(0)}, ANGDIR=${db.angdir}, INSUNITS=${db.insunits}.`,
	);
}
