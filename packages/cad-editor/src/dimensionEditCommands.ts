/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDb3PointAngularDimension,
	AcDbAlignedDimension,
	AcDbArc,
	AcDbCircle,
	AcDbDatabase,
	AcDbDimension,
	AcDbDxfCode,
	AcDbEntity,
	AcDbRadialDimension,
	AcDbRegAppTableRecord,
	AcDbResultBuffer,
	AcDbRotatedDimension,
	AcGePoint3d,
} from '@mlightcad/data-model';
import { CadCommandContext, registerCommand } from './commands.js';

export const DIMVAR_DXF_CODES: Record<string, { code: number; type: 'real' | 'int' | 'string' }> = {
	DIMTXT: { code: 140, type: 'real' },
	DIMSCALE: { code: 40, type: 'real' },
	DIMASZ: { code: 41, type: 'real' },
	DIMEXO: { code: 42, type: 'real' },
	DIMDLI: { code: 43, type: 'real' },
	DIMEXE: { code: 44, type: 'real' },
	DIMRND: { code: 45, type: 'real' },
	DIMDLE: { code: 46, type: 'real' },
	DIMTP: { code: 47, type: 'real' },
	DIMTM: { code: 48, type: 'real' },
	DIMTOL: { code: 71, type: 'int' },
	DIMLIM: { code: 72, type: 'int' },
	DIMTIH: { code: 73, type: 'int' },
	DIMTOH: { code: 74, type: 'int' },
	DIMSE1: { code: 75, type: 'int' },
	DIMSE2: { code: 76, type: 'int' },
	DIMTAD: { code: 77, type: 'int' },
	DIMZIN: { code: 78, type: 'int' },
	DIMCLRD: { code: 176, type: 'int' },
	DIMCLRE: { code: 177, type: 'int' },
	DIMCLRT: { code: 178, type: 'int' },
	DIMDEC: { code: 271, type: 'int' },
	DIMTDEC: { code: 272, type: 'int' },
};

function ensureAppId(db: AcDbDatabase, appId: string): void {
	if (db.tables?.appIdTable && !db.tables.appIdTable.has(appId)) {
		try {
			db.tables.appIdTable.add(new AcDbRegAppTableRecord(appId));
		} catch {}
	}
}

/**
 * Applies a dimension variable override to a dimension entity using AutoCAD ACAD DSTYLE XData.
 */
export function applyDimOverride(
	db: AcDbDatabase,
	dim: AcDbDimension,
	varName: string,
	value: number | string,
): void {
	ensureAppId(db, 'ACAD');
	const upper = varName.toUpperCase();
	const meta = DIMVAR_DXF_CODES[upper];
	const varCode = meta ? meta.code : 140;
	const isReal = meta ? meta.type === 'real' : typeof value === 'number';

	// Read existing overrides
	const existing = getDimOverrides(dim);
	existing[upper] = typeof value === 'string' && isReal ? parseFloat(value) : value;

	// Build ResultBuffer following AutoCAD ACAD DSTYLE specification
	const items: { code: number; value: any }[] = [
		{ code: AcDbDxfCode.ExtendedDataRegAppName, value: 'ACAD' },
		{ code: AcDbDxfCode.ExtendedDataAsciiString, value: 'DSTYLE' },
		{ code: AcDbDxfCode.ExtendedDataControlString, value: '{' },
	];

	for (const [k, v] of Object.entries(existing)) {
		const m = DIMVAR_DXF_CODES[k];
		const c = m ? m.code : 140;
		items.push({ code: AcDbDxfCode.ExtendedDataInteger16, value: c });
		if (m && m.type === 'int') {
			items.push({ code: AcDbDxfCode.ExtendedDataInteger16, value: Math.round(Number(v)) });
		} else if (typeof v === 'number' || (m && m.type === 'real')) {
			items.push({ code: AcDbDxfCode.ExtendedDataReal, value: Number(v) });
		} else {
			items.push({ code: AcDbDxfCode.ExtendedDataAsciiString, value: String(v) });
		}
	}

	items.push({ code: AcDbDxfCode.ExtendedDataControlString, value: '}' });
	const rb = new AcDbResultBuffer(items);
	dim.setXData(rb);
}

/**
 * Reads all dimension variable overrides from a dimension's ACAD DSTYLE XData.
 */
export function getDimOverrides(dim: AcDbDimension): Record<string, number | string> {
	const rb = dim.getXData('ACAD');
	if (!rb) return {};

	const items = Array.from(rb);
	const res: Record<string, number | string> = {};

	// Inverted code lookup
	const codeToName: Record<number, string> = {};
	for (const [name, meta] of Object.entries(DIMVAR_DXF_CODES)) {
		codeToName[meta.code] = name;
	}

	let insideDstyle = false;
	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		if (item.code === AcDbDxfCode.ExtendedDataAsciiString && item.value === 'DSTYLE') {
			insideDstyle = true;
			continue;
		}
		if (insideDstyle && item.code === AcDbDxfCode.ExtendedDataControlString && item.value === '}') {
			insideDstyle = false;
			continue;
		}
		if (insideDstyle && item.code === AcDbDxfCode.ExtendedDataInteger16) {
			const varCode = Number(item.value);
			const varName = codeToName[varCode] ?? `VAR_${varCode}`;
			if (i + 1 < items.length) {
				const valItem = items[++i];
				res[varName] = valItem.value as string | number;
			}
		}
	}
	return res;
}

/**
 * Clears all dimension variable overrides on a dimension.
 */
export function clearDimOverrides(dim: AcDbDimension): void {
	dim.removeXData('ACAD');
}

/**
 * Pure calculation to space parallel linear or angular dimensions equally from a base dimension.
 */
export function spaceDimensions(
	baseDim: AcDbDimension,
	otherDims: readonly AcDbDimension[],
	spacing: number | 'Auto',
): void {
	if (otherDims.length === 0) return;

	let numSpacing = 10;
	if (spacing === 'Auto') {
		const overrides = getDimOverrides(baseDim);
		const txt = Number(overrides.DIMTXT) || 2.5;
		numSpacing = 2 * txt;
	} else {
		numSpacing = spacing;
	}

	// 1. Aligned or Rotated linear dimensions
	if (baseDim instanceof AcDbAlignedDimension) {
		const rot = baseDim.rotation ?? 0;
		// Normal unit vector perpendicular to dimension line
		const nx = -Math.sin(rot);
		const ny = Math.cos(rot);

		const basePt = baseDim.dimLinePoint;
		const s0 = basePt.x * nx + basePt.y * ny;

		// Calculate projection coordinate for each other dimension
		const withDist = otherDims.map(dim => {
			if (dim instanceof AcDbAlignedDimension) {
				const pt = dim.dimLinePoint;
				const s = pt.x * nx + pt.y * ny;
				return { dim, pt, s, delta: s - s0 };
			}
			return { dim, pt: new AcGePoint3d(0, 0, 0), s: s0, delta: 0 };
		});

		// Determine dominant direction (+1 or -1)
		const positiveCount = withDist.filter(d => d.delta >= 0).length;
		const dir = positiveCount >= withDist.length / 2 ? 1 : -1;

		// Sort ascending along chosen direction
		withDist.sort((a, b) => (a.delta * dir) - (b.delta * dir));

		// Position each dimension at base + step * spacing
		for (let k = 0; k < withDist.length; k++) {
			const { dim, pt, s } = withDist[k];
			if (dim instanceof AcDbAlignedDimension) {
				const targetS = s0 + (k + 1) * numSpacing * dir;
				const shift = targetS - s;
				const newDimLinePt = new AcGePoint3d(pt.x + shift * nx, pt.y + shift * ny, pt.z);
				dim.dimLinePoint = newDimLinePt;
				if (dim.textPosition) {
					dim.textPosition = new AcGePoint3d(dim.textPosition.x + shift * nx, dim.textPosition.y + shift * ny, dim.textPosition.z);
				}
			}
		}
	} else if (baseDim instanceof AcDb3PointAngularDimension) {
		// Angular dimensions: space arc points radially
		const center = (baseDim as any).centerPoint ?? new AcGePoint3d(0, 0, 0);
		const baseArcPt = baseDim.arcPoint;
		const r0 = Math.hypot(baseArcPt.x - center.x, baseArcPt.y - center.y);

		const withR = otherDims.map(dim => {
			if (dim instanceof AcDb3PointAngularDimension) {
				const arcPt = dim.arcPoint;
				const r = Math.hypot(arcPt.x - center.x, arcPt.y - center.y);
				return { dim, arcPt, r, delta: r - r0 };
			}
			return { dim, arcPt: baseArcPt, r: r0, delta: 0 };
		});

		withR.sort((a, b) => a.delta - b.delta);
		for (let k = 0; k < withR.length; k++) {
			const { dim, arcPt, r } = withR[k];
			if (dim instanceof AcDb3PointAngularDimension && r > 1e-6) {
				const targetR = r0 + (k + 1) * numSpacing;
				const factor = targetR / r;
				dim.arcPoint = new AcGePoint3d(
					center.x + (arcPt.x - center.x) * factor,
					center.y + (arcPt.y - center.y) * factor,
					arcPt.z,
				);
			}
		}
	}
}

/**
 * DIMEDIT: Home/New text/Rotate/Oblique.
 */
export async function dimeditCommand(ctx: CadCommandContext): Promise<void> {
	const opt = await ctx.getKeyword(
		'Enter type of dimension editing [Home/New/Rotate/Oblique] <Home>:',
		['Home', 'New', 'Rotate', 'Oblique'],
		{ default: 'Home' },
	);

	if (opt.toLowerCase() === 'home') {
		const selected = await ctx.getSelection('Select dimensions:');
		await ctx.transaction(async () => {
			for (const ent of selected) {
				if (ent instanceof AcDbDimension) {
					ent.dimensionText = '';
					ent.textRotation = 0;
				}
			}
		});
		ctx.message('Dimension text reset to default position and angle.');
	} else if (opt.toLowerCase() === 'new') {
		const newText = await ctx.getString('Enter new dimension text <>:');
		const selected = await ctx.getSelection('Select dimensions:');
		await ctx.transaction(async () => {
			for (const ent of selected) {
				if (ent instanceof AcDbDimension) {
					ent.dimensionText = newText;
				}
			}
		});
		ctx.message(`Updated dimension text on ${selected.length} object(s).`);
	} else if (opt.toLowerCase() === 'rotate') {
		const angleDeg = await ctx.getAngle('Specify angle for dimension text:');
		const angleRad = angleDeg * Math.PI / 180;
		const selected = await ctx.getSelection('Select dimensions:');
		await ctx.transaction(async () => {
			for (const ent of selected) {
				if (ent instanceof AcDbDimension) {
					ent.textRotation = angleRad;
				}
			}
		});
		ctx.message(`Rotated dimension text to ${angleDeg}°.`);
	} else if (opt.toLowerCase() === 'oblique') {
		const angleDeg = await ctx.getAngle('Enter obliquing angle (press ENTER for none):');
		const angleRad = angleDeg * Math.PI / 180;
		const selected = await ctx.getSelection('Select dimensions:');
		await ctx.transaction(async () => {
			for (const ent of selected) {
				if (ent instanceof AcDbAlignedDimension) {
					ent.oblique = angleRad;
				}
			}
		});
		ctx.message(`Set obliquing angle to ${angleDeg}°.`);
	}
}

/**
 * DIMTEDIT: Left/Right/Center/Home/Angle.
 */
export async function dimteditCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select dimension:');
	if (!pick.entity || !(pick.entity instanceof AcDbDimension)) {
		ctx.message('No dimension selected.');
		return;
	}
	const dim = pick.entity;

	const opt = await ctx.getKeyword(
		'Specify new location for dimension text or [Left/Right/Center/Home/Angle]:',
		['Left', 'Right', 'Center', 'Home', 'Angle'],
	);

	if (opt.toLowerCase() === 'angle') {
		const angleDeg = await ctx.getAngle('Specify angle for dimension text:');
		const angleRad = angleDeg * Math.PI / 180;
		await ctx.transaction(async () => {
			dim.textRotation = angleRad;
		});
		ctx.message(`Dimension text rotated to ${angleDeg}°.`);
	} else if (opt.toLowerCase() === 'home') {
		await ctx.transaction(async () => {
			dim.textRotation = 0;
			if (dim instanceof AcDbAlignedDimension) {
				const midX = (dim.xLine1Point.x + dim.xLine2Point.x) / 2;
				const midY = (dim.xLine1Point.y + dim.xLine2Point.y) / 2;
				dim.textPosition = new AcGePoint3d(midX, midY, dim.textPosition?.z ?? 0);
			}
		});
		ctx.message('Dimension text returned to home position.');
	} else if (opt.toLowerCase() === 'left') {
		await ctx.transaction(async () => {
			if (dim instanceof AcDbAlignedDimension) {
				dim.textPosition = new AcGePoint3d(dim.xLine1Point.x, dim.dimLinePoint.y, dim.dimLinePoint.z);
			}
		});
		ctx.message('Dimension text justified left.');
	} else if (opt.toLowerCase() === 'right') {
		await ctx.transaction(async () => {
			if (dim instanceof AcDbAlignedDimension) {
				dim.textPosition = new AcGePoint3d(dim.xLine2Point.x, dim.dimLinePoint.y, dim.dimLinePoint.z);
			}
		});
		ctx.message('Dimension text justified right.');
	} else if (opt.toLowerCase() === 'center') {
		await ctx.transaction(async () => {
			if (dim instanceof AcDbAlignedDimension) {
				const midX = (dim.xLine1Point.x + dim.xLine2Point.x) / 2;
				dim.textPosition = new AcGePoint3d(midX, dim.dimLinePoint.y, dim.dimLinePoint.z);
			}
		});
		ctx.message('Dimension text centered.');
	}
}

/**
 * DIMOVERRIDE: sets or clears dimension variable overrides.
 */
export async function dimoverrideCommand(ctx: CadCommandContext): Promise<void> {
	const opt = await ctx.getString('Enter dimension variable name to override or [Clear overrides]:');
	if (!opt) return;

	if (opt.toLowerCase() === 'clear') {
		const selected = await ctx.getSelection('Select dimensions:');
		await ctx.transaction(async () => {
			for (const ent of selected) {
				if (ent instanceof AcDbDimension) {
					clearDimOverrides(ent);
				}
			}
		});
		ctx.message('Cleared dimension overrides.');
		return;
	}

	const val = await ctx.getString(`Enter new value for dimension variable <${opt}>:`);
	const numVal = isNaN(Number(val)) ? val : Number(val);

	const selected = await ctx.getSelection('Select dimensions:');
	await ctx.transaction(async () => {
		for (const ent of selected) {
			if (ent instanceof AcDbDimension) {
				applyDimOverride(ctx.database.native, ent, opt, numVal);
			}
		}
	});
	ctx.message(`Applied override ${opt}=${val} to ${selected.length} dimension(s).`);
}

/**
 * DIMSPACE: equal spacing of parallel linear or angular dimensions from a base dimension.
 */
export async function dimspaceCommand(ctx: CadCommandContext): Promise<void> {
	const basePick = await ctx.getEntityPick('Select base dimension:');
	if (!basePick.entity || !(basePick.entity instanceof AcDbDimension)) {
		ctx.message('No base dimension selected.');
		return;
	}
	const baseDim = basePick.entity;

	const selected = await ctx.getSelection('Select dimensions to space:');
	const otherDims = selected.filter((e): e is AcDbDimension => e instanceof AcDbDimension && e !== baseDim);
	if (otherDims.length === 0) {
		ctx.message('No additional dimensions selected to space.');
		return;
	}

	const val = await ctx.getString('Enter value or [Auto] <Auto>:');
	const spacing = (val && val.toLowerCase() !== 'auto' && !isNaN(Number(val))) ? Number(val) : 'Auto';

	await ctx.transaction(async () => {
		spaceDimensions(baseDim, otherDims, spacing);
	});
	ctx.message(`Spaced ${otherDims.length} dimension(s) from base.`);
}

/**
 * DIMBREAK: store break flag / metadata on dimension entity.
 */
export async function dimbreakCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select dimension to add/remove break or [Multiple]:');
	if (!pick.entity || !(pick.entity instanceof AcDbDimension)) {
		ctx.message('No dimension selected.');
		return;
	}
	const dim = pick.entity;
	const opt = await ctx.getKeyword('Enter option [Auto/Manual/Remove] <Auto>:', ['Auto', 'Manual', 'Remove'], { default: 'Auto' });

	await ctx.transaction(async () => {
		if (opt.toLowerCase() === 'remove') {
			dim.removeXData('SAENGINE_DIMBREAK');
			ctx.message('Dimension break removed.');
		} else {
			ensureAppId(ctx.database.native, 'SAENGINE_DIMBREAK');
			const rb = new AcDbResultBuffer([
				{ code: AcDbDxfCode.ExtendedDataRegAppName, value: 'SAENGINE_DIMBREAK' },
				{ code: AcDbDxfCode.ExtendedDataInteger16, value: 1 },
			]);
			dim.setXData(rb);
			ctx.message('Dimension break stored in dimension metadata (renderer does not draw breaks).');
		}
	});
}

/**
 * DIMJOGGED: jogged radius dimension.
 */
export async function dimjoggedCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select arc or circle:');
	if (!pick.entity || (!(pick.entity instanceof AcDbCircle) && !(pick.entity instanceof AcDbArc))) {
		ctx.message('Selected entity is not a circle or arc.');
		return;
	}
	const target = pick.entity;
	const centerOverride = await ctx.getPoint('Specify center location override:');
	const dimPt = await ctx.getPoint('Specify dimension line location:');
	const jogPt = await ctx.getPoint('Specify jog location:');

	const r = target.radius;
	const radDim = new AcDbRadialDimension(
		new AcGePoint3d(centerOverride.x, centerOverride.y, 0),
		new AcGePoint3d(dimPt.x, dimPt.y, 0),
		Math.hypot(dimPt.x - jogPt.x, dimPt.y - jogPt.y),
		`R ${r.toFixed(2)}`,
	);

	ensureAppId(ctx.database.native, 'SAENGINE_DIMJOGGED');
	const rb = new AcDbResultBuffer([
		{ code: AcDbDxfCode.ExtendedDataRegAppName, value: 'SAENGINE_DIMJOGGED' },
		{ code: AcDbDxfCode.ExtendedDataReal, value: jogPt.x },
		{ code: AcDbDxfCode.ExtendedDataReal, value: jogPt.y },
	]);
	radDim.setXData(rb);

	await ctx.transaction(async () => {
		ctx.database.add(radDim);
	});
	ctx.message('Jogged dimension created (stored as AcDbRadialDimension with jog parameters in XData).');
}

/**
 * DIMJOGLINE: add or remove jog line on linear dimension.
 */
export async function dimjoglineCommand(ctx: CadCommandContext): Promise<void> {
	const pick = await ctx.getEntityPick('Select dimension to add jog or [Remove]:');
	if (!pick.entity || !(pick.entity instanceof AcDbDimension)) {
		ctx.message('No dimension selected.');
		return;
	}
	const dim = pick.entity;
	const jogPt = await ctx.getPoint('Specify jog location (or press ENTER for default):');

	await ctx.transaction(async () => {
		ensureAppId(ctx.database.native, 'SAENGINE_DIMJOGLINE');
		const rb = new AcDbResultBuffer([
			{ code: AcDbDxfCode.ExtendedDataRegAppName, value: 'SAENGINE_DIMJOGLINE' },
			{ code: AcDbDxfCode.ExtendedDataReal, value: jogPt.x },
			{ code: AcDbDxfCode.ExtendedDataReal, value: jogPt.y },
		]);
		dim.setXData(rb);
	});
	ctx.message('Dimension jog line added (stored in XData metadata).');
}

/**
 * DIMREASSOCIATE / DIMDISASSOCIATE: report that AcDbDimAssoc is not in data model.
 */
export async function dimreassociateCommand(ctx: CadCommandContext): Promise<void> {
	ctx.message('Dimension associativity (AcDbDimAssoc) is not supported by the underlying data model.');
}

export async function dimdisassociateCommand(ctx: CadCommandContext): Promise<void> {
	ctx.message('Dimension associativity (AcDbDimAssoc) is not supported by the underlying data model.');
}

export function registerDimensionEditCommands(): void {
	registerCommand('DIMEDIT', dimeditCommand);
	registerCommand('DIMTEDIT', dimteditCommand);
	registerCommand('DIMOVERRIDE', dimoverrideCommand);
	registerCommand('DIMSPACE', dimspaceCommand);
	registerCommand('DIMBREAK', dimbreakCommand);
	registerCommand('DIMJOGGED', dimjoggedCommand);
	registerCommand('DIMJOGLINE', dimjoglineCommand);
	registerCommand('DIMREASSOCIATE', dimreassociateCommand);
	registerCommand('DIMDISASSOCIATE', dimdisassociateCommand);
}
