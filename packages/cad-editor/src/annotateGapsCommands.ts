/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbDatabase, AcDbEntity, AcDbFcf, AcDbHatch, AcDbHatchObjectType,
	AcDbGradientPatternType, AcDbLeader, AcDbLeaderAnnotationType,
	AcDbLine, AcDbMLeader, AcDbMText, AcDbPolyline, AcDbRasterImageClipBoundaryType,
	AcDbSortentsTable, AcDbSpline, AcDbText, AcDbWipeout,
	AcGePoint2d, AcGePoint3d, AcGePolyline2d, AcGeVector2d, AcGeVector3d,
} from '@mlightcad/data-model';
import { AcApDocManager, AcEdOpenMode } from '@mlightcad/cad-simple-viewer';
import type { CadCommandContext, CadPoint3 } from './commands.js';
import { copyProperties, registerCommand } from './commands.js';
import { detectBoundaryFromPoint, detectLoopsFromObjects, type HatchLoop } from './hatchGeometry.js';
import {
	calculateRegionMassProperties, createRegionPolyline, entityToPolygon2D,
	isEntityRegion, polygonBoolean, type RegionPoint2D,
} from './regionGeometry.js';
import { polylineVertices } from './entityAccess.js';

let rememberedWipeoutFrame: 0 | 1 | 2 = 1;
let rememberedCenterexe = 3.75;
let rememberedQleaderAnnoType: 'MText' | 'None' | 'Copy' | 'Tolerance' | 'Block' = 'MText';
let rememberedQleaderMaxPoints = 3;
let rememberedQleaderArrow = 'Closed filled';
let rememberedGradientPattern = 'LINEAR';
let rememberedGradientColor1 = 0x0000ff; // blue
let rememberedGradientColor2 = 0xffff00; // yellow
let rememberedGradientOneColor = false;
let rememberedGradientAngle = 0; // degrees
let rememberedGradientShift = 0; // 0..1

function getDatabaseCenterexe(db: any): number {
	const raw = db?.centerexe ??
		db?.header?.centerexe ??
		db?.header?.CENTEREXE ??
		(typeof db?.getVariable === 'function' ? db.getVariable('CENTEREXE') : undefined) ??
		(typeof db?.getSysVar === 'function' ? db.getSysVar('CENTEREXE') : undefined);
	if (typeof raw === 'number' && !isNaN(raw)) {
		rememberedCenterexe = Math.abs(raw);
	}
	return rememberedCenterexe;
}

// ---------------------------------------------------------------------------
// 1. WIPEOUT
// ---------------------------------------------------------------------------

export async function wipeoutCommand(ctx: CadCommandContext): Promise<void> {
	const choice = await ctx.getKeyword(
		`Specify first point or [Frames/Polyline] <Polyline>:`,
		['Frames', 'Polyline', 'Point'],
		{ default: 'Polyline' },
	);

	if (choice === 'Frames') {
		const mode = await ctx.getKeyword(
			`Enter mode [ON/OFF/Display but not plot] <${rememberedWipeoutFrame === 0 ? 'OFF' : rememberedWipeoutFrame === 2 ? 'Display' : 'ON'}>:`,
			['ON', 'OFF', 'Display'],
			{ default: rememberedWipeoutFrame === 0 ? 'OFF' : rememberedWipeoutFrame === 2 ? 'Display' : 'ON' },
		);
		if (mode === 'OFF') rememberedWipeoutFrame = 0;
		else if (mode === 'Display') rememberedWipeoutFrame = 2;
		else rememberedWipeoutFrame = 1;
		ctx.message(`WIPEOUTFRAME set to ${rememberedWipeoutFrame}.`);
		return;
	}

	let pts: RegionPoint2D[] = [];
	let sourcePolylineId: string | undefined;

	if (choice === 'Polyline') {
		const ent = await ctx.getEntity('Select a closed polyline:');
		if (!(ent instanceof AcDbPolyline) || !ent.closed) {
			ctx.message('Selected object is not a closed polyline.');
			return;
		}
		const data = polylineVertices(ent);
		pts = data.points.map(([x, y]) => ({ x, y }));
		const eraseChoice = await ctx.getKeyword('Erase polyline? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
		if (eraseChoice === 'Yes') {
			sourcePolylineId = String(ent.objectId);
		}
	} else {
		// Point sequence
		const p1 = await ctx.getPoint('Specify first point:');
		pts.push({ x: p1.x, y: p1.y });
		while (true) {
			const res = await ctx.getPointPick('Specify next point:', { base: p1, keywords: ['Close', 'Undo'] });
			if (res.status === 'cancel' || res.status === 'none') break;
			if (res.keyword === 'Close' || (res.point && pts.length >= 3 && Math.hypot(res.point.x - pts[0].x, res.point.y - pts[0].y) < 1e-4)) {
				break;
			}
			if (res.point) {
				pts.push({ x: res.point.x, y: res.point.y });
			}
		}
	}

	if (pts.length < 3) {
		ctx.message('At least 3 points required for WIPEOUT.');
		return;
	}

	let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
	for (const p of pts) {
		minX = Math.min(minX, p.x);
		minY = Math.min(minY, p.y);
		maxX = Math.max(maxX, p.x);
		maxY = Math.max(maxY, p.y);
	}
	const width = Math.max(1e-6, maxX - minX);
	const height = Math.max(1e-6, maxY - minY);

	const wipeout = new AcDbWipeout();
	wipeout.position = new AcGePoint3d(minX, minY, 0);
	wipeout.width = width;
	wipeout.height = height;
	wipeout.scale = new AcGeVector2d(1, 1);
	wipeout.clipBoundaryType = AcDbRasterImageClipBoundaryType.Poly;
	wipeout.isClipped = true;
	wipeout.isShownClipped = true;
	wipeout.isImageShown = true;

	const normalizedPts = pts.map(p => new AcGePoint2d((p.x - minX) / width, (p.y - minY) / height));
	if (Math.hypot(pts[0].x - pts[pts.length - 1].x, pts[0].y - pts[pts.length - 1].y) > 1e-6) {
		normalizedPts.push(normalizedPts[0]);
	}
	wipeout.clipBoundary = normalizedPts;

	await ctx.transaction(async () => {
		if (sourcePolylineId) {
			ctx.database.erase(sourcePolylineId);
		}
		ctx.database.add(wipeout);
	});
	ctx.message('WIPEOUT created.');
}

// ---------------------------------------------------------------------------
// 2. REGION, UNION, SUBTRACT, INTERSECT, MASSPROP
// ---------------------------------------------------------------------------

export async function regionCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects:');
	const detected = detectLoopsFromObjects(sel);
	if (!detected) {
		ctx.message('0 loop(s) extracted. 0 Region(s) created.');
		return;
	}

	const allLoops: HatchLoop[] = [detected.outer, ...(detected.islands || [])];
	const createdEntities: AcDbPolyline[] = [];

	await ctx.transaction(async () => {
		for (const loop of allLoops) {
			const ring: RegionPoint2D[] = loop.vertices.map(v => ({ x: v.x, y: v.y }));
			if (ring.length >= 3) {
				const poly = createRegionPolyline(ring);
				ctx.database.add(poly);
				createdEntities.push(poly);
			}
		}
	});

	ctx.message(`${createdEntities.length} loop(s) extracted. ${createdEntities.length} Region(s) created.`);
}

export async function unionCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select regions or closed polylines:');
	const polys: RegionPoint2D[][] = [];
	const idsToErase: string[] = [];

	for (const e of sel) {
		const poly = entityToPolygon2D(e);
		if (poly && poly.length >= 3) {
			polys.push(poly);
			idsToErase.push(String(e.objectId));
		}
	}

	if (polys.length < 2) {
		ctx.message('At least 2 regions or closed polylines required for UNION.');
		return;
	}

	let currentRings = [polys[0]];
	for (let i = 1; i < polys.length; i++) {
		const next = polys[i];
		const newRings: RegionPoint2D[][] = [];
		for (const r of currentRings) {
			const res = polygonBoolean(r, next, 'union');
			newRings.push(...res);
		}
		currentRings = newRings;
	}

	await ctx.transaction(async () => {
		for (const id of idsToErase) ctx.database.erase(id);
		for (const ring of currentRings) {
			ctx.database.add(createRegionPolyline(ring));
		}
	});
	ctx.message(`UNION completed: ${currentRings.length} region(s) created.`);
}

export async function subtractCommand(ctx: CadCommandContext): Promise<void> {
	const selFrom = await ctx.getSelection('Select regions to subtract from:');
	const sourcePolys: { id: string; poly: RegionPoint2D[] }[] = [];
	for (const e of selFrom) {
		const poly = entityToPolygon2D(e);
		if (poly && poly.length >= 3) {
			sourcePolys.push({ id: String(e.objectId), poly });
		}
	}

	if (sourcePolys.length === 0) {
		ctx.message('No valid source regions selected.');
		return;
	}

	const selMinus = await ctx.getSelection('Select regions to subtract:');
	const cutPolys: { id: string; poly: RegionPoint2D[] }[] = [];
	for (const e of selMinus) {
		const poly = entityToPolygon2D(e);
		if (poly && poly.length >= 3) {
			cutPolys.push({ id: String(e.objectId), poly });
		}
	}

	if (cutPolys.length === 0) {
		ctx.message('No cutting regions selected.');
		return;
	}

	let currentRings = sourcePolys.map(s => s.poly);
	for (const cut of cutPolys) {
		const nextRings: RegionPoint2D[][] = [];
		for (const ring of currentRings) {
			const res = polygonBoolean(ring, cut.poly, 'difference');
			nextRings.push(...res);
		}
		currentRings = nextRings;
	}

	await ctx.transaction(async () => {
		for (const s of sourcePolys) ctx.database.erase(s.id);
		for (const c of cutPolys) ctx.database.erase(c.id);
		for (const ring of currentRings) {
			ctx.database.add(createRegionPolyline(ring));
		}
	});
	ctx.message(`SUBTRACT completed: ${currentRings.length} region(s) created.`);
}

export async function intersectCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select regions to intersect:');
	const polys: { id: string; poly: RegionPoint2D[] }[] = [];
	for (const e of sel) {
		const poly = entityToPolygon2D(e);
		if (poly && poly.length >= 3) {
			polys.push({ id: String(e.objectId), poly });
		}
	}

	if (polys.length < 2) {
		ctx.message('At least 2 regions required for INTERSECT.');
		return;
	}

	let currentRings = [polys[0].poly];
	for (let i = 1; i < polys.length; i++) {
		const nextRings: RegionPoint2D[][] = [];
		for (const r of currentRings) {
			const res = polygonBoolean(r, polys[i].poly, 'intersect');
			nextRings.push(...res);
		}
		currentRings = nextRings;
	}

	await ctx.transaction(async () => {
		for (const p of polys) ctx.database.erase(p.id);
		for (const ring of currentRings) {
			ctx.database.add(createRegionPolyline(ring));
		}
	});
	ctx.message(`INTERSECT completed: ${currentRings.length} region(s) created.`);
}

export async function masspropCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select regions for mass properties:');
	const loops: RegionPoint2D[][] = [];

	for (const e of sel) {
		const poly = entityToPolygon2D(e);
		if (poly && poly.length >= 3) {
			loops.push(poly);
		}
	}

	if (loops.length === 0) {
		ctx.message('No valid regions or closed curves selected.');
		return;
	}

	const props = calculateRegionMassProperties(loops);
	const fmt = (n: number) => n.toFixed(4);

	const report = [
		'---------------- REGIONS MASS PROPERTIES ----------------',
		`Area:                   ${fmt(props.area)}`,
		`Perimeter:              ${fmt(props.perimeter)}`,
		`Bounding box:           X: ${fmt(props.bbox.min.x)}  --  ${fmt(props.bbox.max.x)}`,
		`                        Y: ${fmt(props.bbox.min.y)}  --  ${fmt(props.bbox.max.y)}`,
		`Centroid:               X: ${fmt(props.centroid.x)}`,
		`                        Y: ${fmt(props.centroid.y)}`,
		`Moments of inertia:     X: ${fmt(props.Ixx)}`,
		`                        Y: ${fmt(props.Iyy)}`,
		`Product of inertia:     XY: ${fmt(props.Ixy)}`,
		`Radii of gyration:      X: ${fmt(props.kx)}`,
		`                        Y: ${fmt(props.ky)}`,
		`Principal moments and X-Y directions about centroid:`,
		`                        I: ${fmt(props.principalMoments.I)} along [${fmt(props.principalDirectionI.x)} ${fmt(props.principalDirectionI.y)}]`,
		`                        J: ${fmt(props.principalMoments.J)} along [${fmt(props.principalDirectionJ.x)} ${fmt(props.principalDirectionJ.y)}]`,
	].join('\n');

	ctx.message(report);
}

// ---------------------------------------------------------------------------
// 3. GRADIENT
// ---------------------------------------------------------------------------

export const GRADIENT_PATTERNS = [
	'LINEAR', 'CYLINDER', 'INVCYLINDER',
	'SPHERICAL', 'INVSPHERICAL',
	'HEMISPHERICAL', 'INVHEMISPHERICAL',
	'CURVED', 'INVCURVED',
] as const;

export async function gradientCommand(ctx: CadCommandContext): Promise<void> {
	while (true) {
		const action = await ctx.getKeyword(
			`Pick internal point or [Select objects/Pattern/Color1/Color2/Angle/Centred] <Pick>:`,
			['Pick', 'Select', 'Pattern', 'Color1', 'Color2', 'Angle', 'Centred'],
			{ default: 'Pick' },
		);

		if (action === 'Pattern') {
			const pat = await ctx.getKeyword(
				`Enter gradient pattern [LINEAR/CYLINDER/INVCYLINDER/SPHERICAL/INVSPHERICAL/HEMISPHERICAL/INVHEMISPHERICAL/CURVED/INVCURVED] <${rememberedGradientPattern}>:`,
				GRADIENT_PATTERNS,
				{ default: rememberedGradientPattern },
			);
			rememberedGradientPattern = pat.toUpperCase();
			continue;
		}

		if (action === 'Angle') {
			const ang = await ctx.getAngle(`Specify gradient angle <${rememberedGradientAngle}>:`);
			rememberedGradientAngle = (ang * 180 / Math.PI) % 360;
			continue;
		}

		if (action === 'Centred') {
			const shift = await ctx.getDouble(`Specify gradient shift (0.0 to 1.0) <${rememberedGradientShift}>:`);
			rememberedGradientShift = Math.max(0, Math.min(1, shift));
			continue;
		}

		if (action === 'Color1') {
			const hexStr = await ctx.getString('Specify Color 1 (RGB hex e.g. ff0000) <blue>:');
			const hex = parseInt(hexStr.replace(/^#/, ''), 16);
			if (!isNaN(hex)) rememberedGradientColor1 = hex;
			continue;
		}

		if (action === 'Color2') {
			const hexStr = await ctx.getString('Specify Color 2 (RGB hex e.g. ffff00) <yellow>:');
			const hex = parseInt(hexStr.replace(/^#/, ''), 16);
			if (!isNaN(hex)) rememberedGradientColor2 = hex;
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
			const pt = await ctx.getPoint('Pick internal point:');
			const loop = detectBoundaryFromPoint(ctx.database.all(), [pt.x, pt.y]);
			if (!loop) {
				ctx.message('No closed boundary found around point.');
				return;
			}
			loopData = { outer: loop };
		}

		const hatch = new AcDbHatch();
		hatch.hatchObjectType = AcDbHatchObjectType.GradientObject;
		hatch.gradientType = AcDbGradientPatternType.PreDefinedGradient;
		hatch.gradientName = rememberedGradientPattern;
		hatch.gradientAngle = (rememberedGradientAngle * Math.PI) / 180;
		hatch.gradientShift = rememberedGradientShift;
		hatch.gradientStartColor = rememberedGradientColor1;
		hatch.gradientEndColor = rememberedGradientColor2;
		hatch.gradientOneColorMode = rememberedGradientOneColor;

		try {
			const doc = AcApDocManager.instance.curDocument;
			if (doc?.database?.clayer) hatch.layer = doc.database.clayer;
		} catch {
			// ignore
		}

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
		ctx.message(`GRADIENT created (${rememberedGradientPattern}).`);
		return;
	}
}

// ---------------------------------------------------------------------------
// 4. TOLERANCE
// ---------------------------------------------------------------------------

export const GD_SYMBOLS: Record<string, string> = {
	POS: '{\\Fgdt;j}', // Position
	FLAT: '{\\Fgdt;c}', // Flatness
	CIRC: '{\\Fgdt;e}', // Circularity
	STR: '{\\Fgdt;b}', // Straightness
	CYL: '{\\Fgdt;g}', // Cylindricity
	PERP: '{\\Fgdt;b}', // Perpendicularity
	PARA: '{\\Fgdt;f}', // Parallelism
	ANG: '{\\Fgdt;a}', // Angularity
	RUN: '{\\Fgdt;k}', // Circular runout
	TRUN: '{\\Fgdt;t}', // Total runout
	PROF_L: '{\\Fgdt;k}', // Profile of line
	PROF_S: '{\\Fgdt;d}', // Profile of surface
	CONC: '{\\Fgdt;r}', // Concentricity
	SYM: '{\\Fgdt;i}', // Symmetry
};

export async function toleranceCommand(ctx: CadCommandContext): Promise<void> {
	const symChoice = await ctx.getKeyword(
		'Enter GD&T symbol [POS/FLAT/CIRC/STR/CYL/PERP/PARA/ANG/RUN/TRUN/PROF_L/PROF_S/CONC/SYM] <POS>:',
		['POS', 'FLAT', 'CIRC', 'STR', 'CYL', 'PERP', 'PARA', 'ANG', 'RUN', 'TRUN', 'PROF_L', 'PROF_S', 'CONC', 'SYM'],
		{ default: 'POS' },
	);
	const symStr = GD_SYMBOLS[symChoice] || symChoice;

	const tol1Val = await ctx.getString('Enter tolerance 1 value <0.05>:', { defaultValue: '0.05' });
	const dia1 = await ctx.getKeyword('Include diameter symbol (Ø)? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
	const mc1 = await ctx.getKeyword('Material condition [None/MMC/LMC/RFS] <None>:', ['None', 'MMC', 'LMC', 'RFS'], { default: 'None' });
	const mcCode1 = mc1 === 'MMC' ? '%%m' : mc1 === 'LMC' ? '%%l' : mc1 === 'RFS' ? '%%s' : '';
	const tol1 = (dia1 === 'Yes' ? '%%c' : '') + tol1Val + mcCode1;

	const tol2Val = await ctx.getString('Enter tolerance 2 value (or Enter for none):', { allowEmpty: true });

	const datum1 = await ctx.getString('Enter primary datum A (or Enter for none):', { allowEmpty: true });
	const datum2 = await ctx.getString('Enter secondary datum B (or Enter for none):', { allowEmpty: true });
	const datum3 = await ctx.getString('Enter tertiary datum C (or Enter for none):', { allowEmpty: true });

	const pt = await ctx.getPoint('Specify insertion point:');

	const textTokens = [symStr, tol1, tol2Val || '', datum1 || '', datum2 || '', datum3 || ''];
	while (textTokens.length > 2 && !textTokens[textTokens.length - 1]) {
		textTokens.pop();
	}
	const fcfText = textTokens.join('%%v');

	const fcf = new AcDbFcf();
	fcf.location = new AcGePoint3d(pt.x, pt.y, pt.z ?? 0);
	fcf.text = fcfText;

	await ctx.transaction(async () => {
		ctx.database.add(fcf);
	});
	ctx.message('TOLERANCE entity created.');
}

// ---------------------------------------------------------------------------
// 5. CENTERLINE
// ---------------------------------------------------------------------------

export async function centerlineCommand(ctx: CadCommandContext): Promise<void> {
	const ent1 = await ctx.getEntity('Select first line:');
	if (!(ent1 instanceof AcDbLine)) {
		ctx.message('First object is not a line.');
		return;
	}
	const ent2 = await ctx.getEntity('Select second line:');
	if (!(ent2 instanceof AcDbLine)) {
		ctx.message('Second object is not a line.');
		return;
	}

	const exe = getDatabaseCenterexe(ctx.database.native);

	const A1 = ent1.startPoint, B1 = ent1.endPoint;
	let A2 = ent2.startPoint, B2 = ent2.endPoint;

	const v1 = { x: B1.x - A1.x, y: B1.y - A1.y };
	const len1 = Math.hypot(v1.x, v1.y);
	const u1 = { x: v1.x / len1, y: v1.y / len1 };

	let v2 = { x: B2.x - A2.x, y: B2.y - A2.y };
	const len2 = Math.hypot(v2.x, v2.y);
	let u2 = { x: v2.x / len2, y: v2.y / len2 };

	if (u1.x * u2.x + u1.y * u2.y < 0) {
		const tmp = A2; A2 = B2; B2 = tmp;
		v2 = { x: B2.x - A2.x, y: B2.y - A2.y };
		u2 = { x: v2.x / len2, y: v2.y / len2 };
	}

	const cross = u1.x * u2.y - u1.y * u2.x;
	let startPt: RegionPoint2D;
	let endPt: RegionPoint2D;

	if (Math.abs(cross) < 1e-4) {
		// Parallel lines
		const u = u1;
		const n = { x: -u.y, y: u.x };
		const d1 = A1.x * n.x + A1.y * n.y;
		const d2 = A2.x * n.x + A2.y * n.y;
		const dMid = (d1 + d2) / 2;
		const P0 = { x: dMid * n.x, y: dMid * n.y };

		const tA1 = (A1.x - P0.x) * u.x + (A1.y - P0.y) * u.y;
		const tB1 = (B1.x - P0.x) * u.x + (B1.y - P0.y) * u.y;
		const tA2 = (A2.x - P0.x) * u.x + (A2.y - P0.y) * u.y;
		const tB2 = (B2.x - P0.x) * u.x + (B2.y - P0.y) * u.y;

		const min1 = Math.min(tA1, tB1), max1 = Math.max(tA1, tB1);
		const min2 = Math.min(tA2, tB2), max2 = Math.max(tA2, tB2);

		const tMin = Math.min(min1, min2);
		const tMax = Math.max(max1, max2);

		startPt = { x: P0.x + (tMin - exe) * u.x, y: P0.y + (tMin - exe) * u.y };
		endPt = { x: P0.x + (tMax + exe) * u.x, y: P0.y + (tMax + exe) * u.y };
	} else {
		// Converging lines: angle bisector
		const denom = cross;
		const t = ((A2.x - A1.x) * u2.y - (A2.y - A1.y) * u2.x) / denom;
		const V = { x: A1.x + t * u1.x, y: A1.y + t * u1.y };

		const bisectX = u1.x + u2.x;
		const bisectY = u1.y + u2.y;
		const bLen = Math.hypot(bisectX, bisectY);
		const uBisect = { x: bisectX / bLen, y: bisectY / bLen };

		const tA1 = (A1.x - V.x) * uBisect.x + (A1.y - V.y) * uBisect.y;
		const tB1 = (B1.x - V.x) * uBisect.x + (B1.y - V.y) * uBisect.y;
		const tA2 = (A2.x - V.x) * uBisect.x + (A2.y - V.y) * uBisect.y;
		const tB2 = (B2.x - V.x) * uBisect.x + (B2.y - V.y) * uBisect.y;

		const tMin = Math.min(tA1, tB1, tA2, tB2);
		const tMax = Math.max(tA1, tB1, tA2, tB2);

		startPt = { x: V.x + (tMin - exe) * uBisect.x, y: V.y + (tMin - exe) * uBisect.y };
		endPt = { x: V.x + (tMax + exe) * uBisect.x, y: V.y + (tMax + exe) * uBisect.y };
	}

	const cl = new AcDbLine(
		new AcGePoint3d(startPt.x, startPt.y, 0),
		new AcGePoint3d(endPt.x, endPt.y, 0),
	);
	cl.lineType = 'CENTER';

	await ctx.transaction(async () => {
		ctx.database.add(cl);
	});
	ctx.message('CENTERLINE created.');
}

// ---------------------------------------------------------------------------
// 6. BLEND
// ---------------------------------------------------------------------------

function extractCurveEndpointAndTangent(entity: AcDbEntity, pickPt: CadPoint3): { pt: RegionPoint2D; tangent: RegionPoint2D } | null {
	if (entity instanceof AcDbLine) {
		const A = entity.startPoint;
		const B = entity.endPoint;
		const distA = Math.hypot(pickPt.x - A.x, pickPt.y - A.y);
		const distB = Math.hypot(pickPt.x - B.x, pickPt.y - B.y);
		const len = Math.hypot(B.x - A.x, B.y - A.y);
		if (len < 1e-9) return null;

		if (distA < distB) {
			// Picked near start: outward continuation tangent is away from line: A - B or into curve
			// Following AutoCAD BLEND: tangent smoothly continues the curve's parameterization direction
			const ux = (B.x - A.x) / len;
			const uy = (B.y - A.y) / len;
			return { pt: { x: A.x, y: A.y }, tangent: { x: -ux, y: -uy } };
		} else {
			// Picked near end: continuation tangent is from A toward B
			const ux = (B.x - A.x) / len;
			const uy = (B.y - A.y) / len;
			return { pt: { x: B.x, y: B.y }, tangent: { x: ux, y: uy } };
		}
	} else if (entity instanceof AcDbPolyline) {
		const data = polylineVertices(entity);
		if (data.points.length < 2 || data.closed) return null;
		const A = data.points[0];
		const B = data.points[data.points.length - 1];
		const distA = Math.hypot(pickPt.x - A[0], pickPt.y - A[1]);
		const distB = Math.hypot(pickPt.x - B[0], pickPt.y - B[1]);
		if (distA < distB) {
			const pNext = data.points[1];
			const len = Math.hypot(pNext[0] - A[0], pNext[1] - A[1]);
			return { pt: { x: A[0], y: A[1] }, tangent: { x: (A[0] - pNext[0]) / len, y: (A[1] - pNext[1]) / len } };
		} else {
			const pPrev = data.points[data.points.length - 2];
			const len = Math.hypot(B[0] - pPrev[0], B[1] - pPrev[1]);
			return { pt: { x: B[0], y: B[1] }, tangent: { x: (B[0] - pPrev[0]) / len, y: (B[1] - pPrev[1]) / len } };
		}
	}
	return null;
}

export async function blendCommand(ctx: CadCommandContext): Promise<void> {
	let continuity: 'Tangent' | 'Smooth' = 'Tangent';
	const pick1 = await ctx.getEntityPick('Select first curve or [Continuity] <Continuity>:', { keywords: ['Continuity'] });
	if (pick1.keyword === 'Continuity') {
		const cChoice = await ctx.getKeyword('Enter continuity [Tangent/Smooth] <Tangent>:', ['Tangent', 'Smooth'], { default: 'Tangent' });
		continuity = cChoice as any;
	}

	const e1 = pick1.entity ?? (await ctx.getEntity('Select first curve near endpoint:'));
	const pt1 = pick1.point ?? (await ctx.getPoint('Pick endpoint on first curve:'));
	const e2 = await ctx.getEntity('Select second curve near endpoint:');
	const pt2 = await ctx.getPoint('Pick endpoint on second curve:');

	const end1 = extractCurveEndpointAndTangent(e1, pt1);
	const end2 = extractCurveEndpointAndTangent(e2, pt2);

	if (!end1 || !end2) {
		ctx.message('Could not extract endpoints or tangents from selected curves.');
		return;
	}

	const P0 = new AcGePoint3d(end1.pt.x, end1.pt.y, 0);
	const P3 = new AcGePoint3d(end2.pt.x, end2.pt.y, 0);
	const dist = Math.hypot(P3.x - P0.x, P3.y - P0.y);
	const scale = dist / 3;

	const P1 = new AcGePoint3d(P0.x + scale * end1.tangent.x, P0.y + scale * end1.tangent.y, 0);
	const P2 = new AcGePoint3d(P3.x + scale * end2.tangent.x, P3.y + scale * end2.tangent.y, 0);

	const controlPoints = [P0, P1, P2, P3];
	const knots = [0, 0, 0, 0, 1, 1, 1, 1];
	const spline = AcDbSpline.fromControlPoints(controlPoints, knots, undefined, 3, false);

	if (!spline) {
		ctx.message('Failed to create BLEND spline.');
		return;
	}

	await ctx.transaction(async () => {
		ctx.database.add(spline);
	});
	ctx.message(`BLEND curve created (${continuity} G1/G2).`);
}

// ---------------------------------------------------------------------------
// 7. QLEADER
// ---------------------------------------------------------------------------

export async function qleaderCommand(ctx: CadCommandContext): Promise<void> {
	const firstPick = await ctx.getPointPick('Specify first leader point or [Settings] <Settings>:', { keywords: ['Settings'] });
	if (firstPick.keyword === 'Settings') {
		const annoType = await ctx.getKeyword(
			`Annotation type [MText/None/Copy/Tolerance/Block] <${rememberedQleaderAnnoType}>:`,
			['MText', 'None', 'Copy', 'Tolerance', 'Block'],
			{ default: rememberedQleaderAnnoType },
		);
		rememberedQleaderAnnoType = annoType as any;

		const maxPts = await ctx.getInteger(`Number of points <${rememberedQleaderMaxPoints}>:`, { min: 2 });
		if (maxPts >= 2) rememberedQleaderMaxPoints = maxPts;
	}

	const p1 = firstPick.point ?? (await ctx.getPoint('Specify first leader point:'));
	const points: CadPoint3[] = [p1];

	while (points.length < rememberedQleaderMaxPoints) {
		const nextPt = await ctx.getPoint('Specify next point:', { base: points[points.length - 1], allowNone: points.length >= 2 });
		if (!nextPt) break;
		points.push(nextPt);
	}

	const leader = new AcDbLeader();
	for (const pt of points) {
		leader.appendVertex(new AcGePoint3d(pt.x, pt.y, pt.z ?? 0));
	}
	leader.hasArrowHead = true;
	leader.hasHookLine = true;

	const lastPt = points[points.length - 1];

	await ctx.transaction(async () => {
		if (rememberedQleaderAnnoType === 'MText') {
			const textStr = await ctx.getString('Specify text:');
			const mtext = new AcDbMText();
			mtext.contents = textStr;
			mtext.location = new AcGePoint3d(lastPt.x, lastPt.y, lastPt.z ?? 0);
			mtext.height = 2.5;
			ctx.database.add(mtext);

			leader.associatedAnnotation = String(mtext.objectId);
			leader.annoType = AcDbLeaderAnnotationType.MText;
			ctx.database.add(leader);
		} else if (rememberedQleaderAnnoType === 'Tolerance') {
			const tolStr = await ctx.getString('Enter tolerance text:');
			const fcf = new AcDbFcf();
			fcf.location = new AcGePoint3d(lastPt.x, lastPt.y, lastPt.z ?? 0);
			fcf.text = tolStr;
			ctx.database.add(fcf);

			leader.associatedAnnotation = String(fcf.objectId);
			leader.annoType = AcDbLeaderAnnotationType.Fcf;
			ctx.database.add(leader);
		} else {
			leader.annoType = AcDbLeaderAnnotationType.NoAnnotation;
			ctx.database.add(leader);
		}
	});
	ctx.message('QLEADER created.');
}

// ---------------------------------------------------------------------------
// 8. DRAWORDER, TEXTTOFRONT, HATCHTOBACK
// ---------------------------------------------------------------------------

function getOrCreateSortentsTable(db: AcDbDatabase): AcDbSortentsTable {
	const sortentsDict = db.objects.sortentsTable;
	for (const [, tbl] of sortentsDict.entries()) {
		if (tbl instanceof AcDbSortentsTable) return tbl;
	}
	const sortents = new AcDbSortentsTable();
	sortentsDict.setAt('MODEL_SPACE_SORTENTS', sortents);
	return sortents;
}

function syncDrawOrder(
	db: AcDbDatabase,
	targetIds: readonly string[],
	position: 'front' | 'back' | 'above' | 'under',
	refId?: string,
): void {
	const modelSpace = db.tables.blockTable.modelSpace as any;
	const currentList: any[] = modelSpace._entities ? [...modelSpace._entities] : [];
	const idSet = new Set(targetIds);
	const getId = (item: any): string => typeof item === 'string' ? item : String(item.objectId);

	const targetItems = currentList.filter(item => idSet.has(getId(item)));
	const remaining = currentList.filter(item => !idSet.has(getId(item)));

	let newOrder: any[];
	if (position === 'front') {
		newOrder = [...remaining, ...targetItems];
	} else if (position === 'back') {
		newOrder = [...targetItems, ...remaining];
	} else if (position === 'above' && refId) {
		const refIdx = remaining.findIndex(item => getId(item) === refId);
		if (refIdx !== -1) {
			newOrder = [...remaining.slice(0, refIdx + 1), ...targetItems, ...remaining.slice(refIdx + 1)];
		} else {
			newOrder = [...remaining, ...targetItems];
		}
	} else if (position === 'under' && refId) {
		const refIdx = remaining.findIndex(item => getId(item) === refId);
		if (refIdx !== -1) {
			newOrder = [...remaining.slice(0, refIdx), ...targetItems, ...remaining.slice(refIdx)];
		} else {
			newOrder = [...targetItems, ...remaining];
		}
	} else {
		newOrder = currentList;
	}

	if (modelSpace._entities) {
		modelSpace._entities.length = 0;
		modelSpace._entities.push(...newOrder);
	}

	const sortents = getOrCreateSortentsTable(db);
	sortents.entityIds = newOrder.map(getId);
}

export async function draworderCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects:');
	if (sel.length === 0) return;
	const targetIds = sel.map(e => String(e.objectId));

	const opt = await ctx.getKeyword(
		'Enter object ordering option [Above object/Under object/Front/Back] <Back>:',
		['Above', 'Under', 'Front', 'Back'],
		{ default: 'Back' },
	);

	let refId: string | undefined;
	if (opt === 'Above' || opt === 'Under') {
		const ref = await ctx.getEntity('Select reference object:');
		refId = String(ref.objectId);
	}

	const pos = opt.toLowerCase() as 'front' | 'back' | 'above' | 'under';
	await ctx.transaction(async () => {
		syncDrawOrder(ctx.database.native, targetIds, pos, refId);
	});
	ctx.message(`DRAWORDER ${opt} applied.`);
}

export async function texttofrontCommand(ctx: CadCommandContext): Promise<void> {
	const opt = await ctx.getKeyword(
		'Enter option [Text/Dimensions/Leaders/All] <All>:',
		['Text', 'Dimensions', 'Leaders', 'All'],
		{ default: 'All' },
	);

	const all = ctx.database.all();
	const matches: string[] = [];

	for (const e of all) {
		const isText = e instanceof AcDbText || e instanceof AcDbMText || e.dxfTypeName === 'TEXT' || e.dxfTypeName === 'MTEXT';
		const isDim = e.dxfTypeName.includes('DIMENSION');
		const isLeader = e instanceof AcDbLeader || e instanceof AcDbMLeader || e.dxfTypeName === 'LEADER' || e.dxfTypeName === 'MULTILEADER';

		if (opt === 'Text' && isText) matches.push(String(e.objectId));
		else if (opt === 'Dimensions' && isDim) matches.push(String(e.objectId));
		else if (opt === 'Leaders' && isLeader) matches.push(String(e.objectId));
		else if (opt === 'All' && (isText || isDim || isLeader)) matches.push(String(e.objectId));
	}

	if (matches.length > 0) {
		await ctx.transaction(async () => {
			syncDrawOrder(ctx.database.native, matches, 'front');
		});
	}
	ctx.message(`${matches.length} annotation object(s) brought to front.`);
}

export async function hatchtobackCommand(ctx: CadCommandContext): Promise<void> {
	const all = ctx.database.all();
	const hatchIds: string[] = [];

	for (const e of all) {
		if (e instanceof AcDbHatch || e.dxfTypeName === 'HATCH') {
			hatchIds.push(String(e.objectId));
		}
	}

	if (hatchIds.length > 0) {
		await ctx.transaction(async () => {
			syncDrawOrder(ctx.database.native, hatchIds, 'back');
		});
	}
	ctx.message(`${hatchIds.length} hatch(es) sent to back.`);
}

// ---------------------------------------------------------------------------
// REGISTRATION
// ---------------------------------------------------------------------------

export function registerAnnotateGapsCommands(): void {
	registerCommand('WIPEOUT', wipeoutCommand);
	registerCommand('REGION', regionCommand, { aliases: ['REG'] });
	registerCommand('UNION', unionCommand, { aliases: ['UNI'] });
	registerCommand('SUBTRACT', subtractCommand, { aliases: ['SU'] });
	registerCommand('INTERSECT', intersectCommand, { aliases: ['IN'] });
	registerCommand('MASSPROP', masspropCommand, { aliases: ['MP'], mode: AcEdOpenMode.Read });
	registerCommand('GRADIENT', gradientCommand, { aliases: ['GD'] });
	registerCommand('TOLERANCE', toleranceCommand, { aliases: ['TOL'] });
	registerCommand('CENTERLINE', centerlineCommand, { aliases: ['CL'] });
	registerCommand('BLEND', blendCommand, { aliases: ['BLE'] });
	registerCommand('QLEADER', qleaderCommand, { aliases: ['LE', 'LEADER'] });
	registerCommand('DRAWORDER', draworderCommand, { aliases: ['DR'] });
	registerCommand('TEXTTOFRONT', texttofrontCommand);
	registerCommand('HATCHTOBACK', hatchtobackCommand);
}
