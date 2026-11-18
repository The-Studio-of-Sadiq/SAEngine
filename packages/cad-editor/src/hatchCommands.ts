/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbHatch, AcDbHatchPatternType, AcDbHatchStyle, AcDbPolyline,
	AcGePoint2d, acdbIsSolidHatchPatternName,
} from '@mlightcad/data-model';
import { AcGePolyline2d } from '@mlightcad/geometry-engine';
import { AcApDocManager } from '@mlightcad/cad-simple-viewer';
import type { CadCommandContext } from './commands.js';
import { registerCommand } from './commands.js';
import {
	detectBoundaryFromPoint, detectLoopsFromObjects, type HatchLoop,
} from './hatchGeometry.js';

let rememberedPattern = 'ANSI31';
let rememberedScale = 1.0;
let rememberedAngle = 0.0; // degrees

/**
 * AutoCAD HATCH / BHATCH command.
 * Creates an AcDbHatch entity on the current layer within one undo transaction.
 */
export async function hatchCommand(ctx: CadCommandContext): Promise<void> {
	while (true) {
		const action = await ctx.getKeyword(
			`Pick internal point or [Select objects/Pattern/Scale/Angle] <Pick>:`,
			['Pick', 'Select', 'Pattern', 'Scale', 'Angle'],
			{ default: 'Pick' },
		);

		if (action === 'Pattern') {
			const pat = await ctx.getKeyword(
				`Enter pattern name [SOLID/ANSI31/AR-CONC/AR-SAND/EARTH/NET/ANSI37/DOTS] <${rememberedPattern}>:`,
				['SOLID', 'ANSI31', 'AR-CONC', 'AR-SAND', 'EARTH', 'NET', 'ANSI37', 'DOTS'],
				{ default: rememberedPattern },
			);
			rememberedPattern = pat.toUpperCase();
			continue;
		}

		if (action === 'Scale') {
			const sc = await ctx.getDistance(`Specify pattern scale <${rememberedScale}>:`);
			if (sc > 0) rememberedScale = sc;
			continue;
		}

		if (action === 'Angle') {
			const ang = await ctx.getAngle(`Specify pattern angle <${rememberedAngle}>:`);
			rememberedAngle = (ang * 180 / Math.PI) % 360;
			continue;
		}

		let loopData: { outer: HatchLoop; islands?: HatchLoop[] } | undefined;

		if (action === 'Select') {
			const sel = await ctx.getSelection('Select objects:');
			const detected = detectLoopsFromObjects(sel);
			if (!detected) {
				ctx.message('No valid closed boundary objects found.');
				return;
			}
			loopData = detected;
		} else {
			// Pick internal point
			const pt = await ctx.getPoint('Pick internal point:');
			const loop = detectBoundaryFromPoint(ctx.database.all(), [pt.x, pt.y]);
			if (!loop) {
				ctx.message('No closed boundary found around point.');
				return;
			}
			loopData = { outer: loop };
		}

		const isSolid = rememberedPattern === 'SOLID' || acdbIsSolidHatchPatternName(rememberedPattern);
		const hatch = new AcDbHatch();
		if (isSolid) {
			hatch.isSolidFill = true;
			hatch.patternName = 'SOLID';
			hatch.patternType = AcDbHatchPatternType.Predefined;
		} else {
			hatch.isSolidFill = false;
			hatch.patternName = rememberedPattern;
			hatch.patternType = AcDbHatchPatternType.Predefined;
			hatch.patternScale = rememberedScale;
			hatch.patternAngle = (rememberedAngle * Math.PI) / 180;
		}
		hatch.hatchStyle = AcDbHatchStyle.Normal;

		// Set current layer
		try {
			const doc = AcApDocManager.instance.curDocument;
			if (doc?.database?.clayer) {
				hatch.layer = doc.database.clayer;
			}
		} catch {
			// ignore
		}

		// Add loops (outer first, then islands)
		const allLoops = [loopData.outer, ...(loopData.islands || [])];
		for (const l of allLoops) {
			const polylineLoop = new AcGePolyline2d();
			polylineLoop.closed = l.closed;
			l.vertices.forEach((v, idx) => {
				polylineLoop.addVertexAt(idx, { x: v.x, y: v.y, bulge: v.bulge || 0 });
			});
			hatch.add(polylineLoop);
		}

		await ctx.transaction(async () => {
			ctx.database.add(hatch);
		});
		return;
	}
}

/**
 * AutoCAD HATCHEDIT command.
 * Allows editing pattern name, scale, and angle of an existing hatch entity.
 */
export async function hatchEditCommand(ctx: CadCommandContext): Promise<void> {
	const e = await ctx.getEntity('Select hatch object:');
	if (!(e instanceof AcDbHatch) && e.dxfTypeName !== 'HATCH') {
		ctx.message('Selected object is not a hatch.');
		return;
	}
	const hatch = e as AcDbHatch;
	const option = await ctx.getKeyword(
		`Specify option to edit [Pattern/Scale/Angle] <Pattern>:`,
		['Pattern', 'Scale', 'Angle'],
		{ default: 'Pattern' },
	);

	if (option === 'Pattern') {
		const curPat = hatch.patternName || (hatch.isSolidFill ? 'SOLID' : 'ANSI31');
		const pat = await ctx.getKeyword(
			`Enter pattern name [SOLID/ANSI31/AR-CONC/AR-SAND/EARTH/NET/ANSI37/DOTS] <${curPat}>:`,
			['SOLID', 'ANSI31', 'AR-CONC', 'AR-SAND', 'EARTH', 'NET', 'ANSI37', 'DOTS'],
			{ default: curPat },
		);
		const isSolid = pat.toUpperCase() === 'SOLID';
		if (isSolid) {
			hatch.isSolidFill = true;
			hatch.patternName = 'SOLID';
			hatch.patternType = AcDbHatchPatternType.Predefined;
		} else {
			hatch.isSolidFill = false;
			hatch.patternName = pat.toUpperCase();
			hatch.patternType = AcDbHatchPatternType.Predefined;
		}
	} else if (option === 'Scale') {
		const sc = await ctx.getDistance(`Specify pattern scale <${hatch.patternScale}>:`);
		if (sc > 0) hatch.patternScale = sc;
	} else if (option === 'Angle') {
		const curDeg = (hatch.patternAngle * 180 / Math.PI) % 360;
		const ang = await ctx.getAngle(`Specify pattern angle <${curDeg}>:`);
		hatch.patternAngle = ang;
	}

	await ctx.transaction(async () => {
		ctx.database.replace(String(hatch.objectId), hatch);
	});
}

/**
 * AutoCAD BOUNDARY command.
 * Picks an internal point and creates a closed LWPOLYLINE of the detected boundary.
 */
export async function boundaryCommand(ctx: CadCommandContext): Promise<void> {
	const pt = await ctx.getPoint('Pick internal point:');
	const loop = detectBoundaryFromPoint(ctx.database.all(), [pt.x, pt.y]);
	if (!loop) {
		ctx.message('No closed boundary found around point.');
		return;
	}

	const poly = new AcDbPolyline();
	poly.closed = true;
	loop.vertices.forEach((v, idx) => {
		poly.addVertexAt(idx, new AcGePoint2d(v.x, v.y), v.bulge || 0);
	});

	try {
		const doc = AcApDocManager.instance.curDocument;
		if (doc?.database?.clayer) {
			poly.layer = doc.database.clayer;
		}
	} catch {
		// ignore
	}

	await ctx.transaction(async () => {
		ctx.database.add(poly);
	});
	ctx.message('1 boundary polyline created.');
}

/**
 * Register HATCH, HATCHEDIT, and BOUNDARY commands.
 */
export function registerHatchCommands(): void {
	registerCommand('HATCH', hatchCommand, { aliases: ['H', 'BH'] });
	registerCommand('HATCHEDIT', hatchEditCommand, { aliases: ['HE'] });
	registerCommand('BOUNDARY', boundaryCommand, { aliases: ['BO'] });
}
