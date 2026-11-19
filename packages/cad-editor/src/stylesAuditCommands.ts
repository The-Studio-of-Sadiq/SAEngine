/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcCmColor, AcDbBlockReference, AcDbBlockTableRecord, AcDbCircle, AcDbDatabase, AcDbEntity,
	AcDbFileType, AcDbLine, AcDbMLeader, AcDbMLeaderContentType, AcDbMLeaderStyle,
	AcDbMLine, AcDbMlineStyle, AcDbMText, AcDbPolyline, AcDbResultBuffer, AcDbTable,
	AcDbText, AcDbXrecord, AcGePoint3d,
} from '@mlightcad/data-model';
import type { CadCommandContext, CadPoint3 } from './commands.js';
import { registerCommand } from './commands.js';
import { tableGrid } from './annotationGeometry.js';
import { polylineVertices } from './entityAccess.js';

// ============================================================================
// 1. TABLESTYLE
// ============================================================================

export interface CadTableStyle {
	name: string;
	textStyle: string;
	textHeight: number;
	alignment: string;
	margins: { top: number; bottom: number; left: number; right: number };
	gridLineweight: number;
	titleTextHeight?: number;
	headerTextHeight?: number;
	dataTextHeight?: number;
}

const DEFAULT_TABLE_STYLE: CadTableStyle = {
	name: 'Standard',
	textStyle: 'Standard',
	textHeight: 2.5,
	alignment: 'MiddleCenter',
	margins: { top: 1.5, bottom: 1.5, left: 1.5, right: 1.5 },
	gridLineweight: 0.25,
	titleTextHeight: 3.5,
	headerTextHeight: 2.5,
	dataTextHeight: 2.5,
};

const TABLE_STYLES_KEY = '_saengineTableStyles';
const TABLE_STYLES_XRECORD = 'SAENGINE_TABLESTYLES';

function getTableStylesMap(db: AcDbDatabase): Map<string, CadTableStyle> {
	let map = (db as any)[TABLE_STYLES_KEY] as Map<string, CadTableStyle> | undefined;
	if (!map) {
		map = new Map<string, CadTableStyle>();
		map.set('Standard', { ...DEFAULT_TABLE_STYLE });
		(db as any)[TABLE_STYLES_KEY] = map;

		// Load from Xrecord if present
		try {
			const xrecDict = db.objects?.xrecord;
			if (xrecDict?.has?.(TABLE_STYLES_XRECORD)) {
				const xrec = xrecDict.getAt(TABLE_STYLES_XRECORD) as AcDbXrecord | undefined;
				const data = (xrec as any)?.data ?? (xrec as any)?._values;
				if (Array.isArray(data) && data.length > 0) {
					const jsonItem = data.find((item: any) => item.code === 1 || item.groupCode === 1);
					if (jsonItem?.value) {
						const parsed = JSON.parse(jsonItem.value) as CadTableStyle[];
						for (const s of parsed) {
							map.set(s.name, s);
						}
					}
				}
			}
		} catch {
			// ignore parse errors
		}
	}
	return map;
}

function syncTableStylesToXrecord(db: AcDbDatabase): void {
	try {
		const map = getTableStylesMap(db);
		const list = Array.from(map.values());
		const xrecDict = db.objects?.xrecord;
		if (xrecDict) {
			const xrec = new AcDbXrecord();
			xrec.data = new AcDbResultBuffer([{ code: 1, value: JSON.stringify(list) }]);
			xrecDict.setAt(TABLE_STYLES_XRECORD, xrec);
		}
	} catch {
		// ignore
	}
}

export function getCurrentTableStyle(db: AcDbDatabase): CadTableStyle {
	const map = getTableStylesMap(db);
	const curName = (db as any).ctablestyle ?? 'Standard';
	return map.get(curName) ?? map.get('Standard') ?? DEFAULT_TABLE_STYLE;
}

export function setCurrentTableStyle(db: AcDbDatabase, name: string): void {
	(db as any).ctablestyle = name;
}

export function setTableStyle(db: AcDbDatabase, style: CadTableStyle): void {
	const map = getTableStylesMap(db);
	map.set(style.name, style);
	syncTableStylesToXrecord(db);
}

export function deleteTableStyle(db: AcDbDatabase, name: string): boolean {
	if (name.toUpperCase() === 'STANDARD') return false;
	const map = getTableStylesMap(db);
	const deleted = map.delete(name);
	if (deleted) syncTableStylesToXrecord(db);
	return deleted;
}

export async function tablestyleCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const cur = (db as any).ctablestyle ?? 'Standard';

	const action = await ctx.getKeyword(
		`Enter table style option [?/New/Set/Delete] <Set>:`,
		['?', 'New', 'Set', 'Delete'],
		{ default: 'Set' },
	);

	const act = action.toLowerCase();
	if (act === '?' || act === 'list') {
		const map = getTableStylesMap(db);
		ctx.message('Defined table styles:');
		for (const [name, s] of map.entries()) {
			const isCur = name.toLowerCase() === cur.toLowerCase();
			ctx.message(`  ${isCur ? '* ' : '  '}${name} (text height: ${s.textHeight}, style: ${s.textStyle})`);
		}
	} else if (act === 'set' || act === 's') {
		const name = await ctx.getString(`Enter table style name to make current <${cur}>:`, {
			allowSpaces: false,
			allowEmpty: true,
			defaultValue: cur,
		});
		const map = getTableStylesMap(db);
		const target = name.trim();
		if (!map.has(target)) {
			ctx.message(`Table style "${target}" not found.`);
			return;
		}
		setCurrentTableStyle(db, target);
		ctx.message(`CTABLESTYLE is now "${target}".`);
	} else if (act === 'new' || act === 'n') {
		const name = (await ctx.getString('Enter new table style name:', { allowSpaces: false })).trim();
		if (!name) {
			ctx.message('Invalid style name.');
			return;
		}
		const textStyle = await ctx.getString('Enter text style name <Standard>:', {
			allowSpaces: false,
			allowEmpty: true,
			defaultValue: 'Standard',
		});
		const height = await ctx.getDouble('Enter cell text height <2.5>:');
		const align = await ctx.getKeyword(
			'Enter cell alignment [TopLeft/TopCenter/TopRight/MiddleLeft/MiddleCenter/MiddleRight/BottomLeft/BottomCenter/BottomRight] <MiddleCenter>:',
			['TopLeft', 'TopCenter', 'TopRight', 'MiddleLeft', 'MiddleCenter', 'MiddleRight', 'BottomLeft', 'BottomCenter', 'BottomRight'],
			{ default: 'MiddleCenter' },
		);
		const marginsVal = await ctx.getDouble('Enter cell margins <1.5>:');
		const lineweightVal = await ctx.getDouble('Enter grid lineweight <0.25>:');

		const style: CadTableStyle = {
			name,
			textStyle: textStyle.trim() || 'Standard',
			textHeight: height > 0 ? height : 2.5,
			alignment: align,
			margins: { top: marginsVal, bottom: marginsVal, left: marginsVal, right: marginsVal },
			gridLineweight: lineweightVal,
			dataTextHeight: height > 0 ? height : 2.5,
			headerTextHeight: height > 0 ? height : 2.5,
			titleTextHeight: (height > 0 ? height : 2.5) * 1.4,
		};
		setTableStyle(db, style);
		setCurrentTableStyle(db, name);
		ctx.message(`Table style "${name}" created and set as current.`);
	} else if (act === 'delete' || act === 'd') {
		const name = (await ctx.getString('Enter table style name to delete:', { allowSpaces: false })).trim();
		if (name.toUpperCase() === 'STANDARD') {
			ctx.message('Cannot delete the STANDARD table style.');
			return;
		}
		if (name.toLowerCase() === cur.toLowerCase()) {
			ctx.message('Cannot delete the current table style.');
			return;
		}
		const success = deleteTableStyle(db, name);
		if (success) {
			ctx.message(`Table style "${name}" deleted.`);
		} else {
			ctx.message(`Table style "${name}" not found.`);
		}
	}
}

// ============================================================================
// 2. MLSTYLE
// ============================================================================

export async function mlstyleCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const cur = db.cmlstyle || 'Standard';

	const action = await ctx.getKeyword(
		`Enter multiline style option [?/New/Set/Rename/Delete] <Set>:`,
		['?', 'New', 'Set', 'Rename', 'Delete'],
		{ default: 'Set' },
	);

	const act = action.toLowerCase();
	const mlineDict = db.objects.mlineStyle;

	if (act === '?' || act === 'list') {
		ctx.message('Defined multiline styles:');
		for (const [name, s] of mlineDict.entries()) {
			const isCur = name.toLowerCase() === cur.toLowerCase();
			const elCount = s?.elements?.length ?? 0;
			ctx.message(`  ${isCur ? '* ' : '  '}${name} (${elCount} elements)`);
		}
	} else if (act === 'set' || act === 's') {
		const name = (await ctx.getString(`Enter multiline style name <${cur}>:`, {
			allowSpaces: false,
			allowEmpty: true,
			defaultValue: cur,
		})).trim();
		if (!mlineDict.has(name)) {
			ctx.message(`Multiline style "${name}" not found.`);
			return;
		}
		db.cmlstyle = name;
		ctx.message(`CMLSTYLE is now "${name}".`);
	} else if (act === 'new' || act === 'n') {
		const name = (await ctx.getString('Enter new multiline style name:', { allowSpaces: false })).trim();
		if (!name) return;
		if (mlineDict.has(name)) {
			ctx.message(`Style "${name}" already exists.`);
			return;
		}

		const numElements = await ctx.getInteger('Enter number of line elements <2>:', { min: 1 });
		const elements: Array<{ offset: number; color: AcCmColor; lineType: string }> = [];

		for (let i = 0; i < numElements; i++) {
			const defaultOffset = numElements === 2 ? (i === 0 ? 0.5 : -0.5) : i * 0.5;
			const offset = await ctx.getDouble(`Enter offset for element ${i + 1} <${defaultOffset}>:`);
			elements.push({
				offset: Number.isFinite(offset) ? offset : defaultOffset,
				color: new AcCmColor().setByLayer(),
				lineType: 'ByLayer',
			});
		}

		let flags = 0;
		const capsChoice = await ctx.getKeyword(
			'Add end caps? [None/Square/Round/Inner] <None>:',
			['None', 'Square', 'Round', 'Inner'],
			{ default: 'None' },
		);
		if (capsChoice === 'Square') flags |= (16 | 256); // StartSquareCap | EndSquareCap
		else if (capsChoice === 'Round') flags |= (64 | 1024); // StartRoundCap | EndRoundCap
		else if (capsChoice === 'Inner') flags |= (32 | 512); // StartInnerArcs | EndInnerArcs

		const fillChoice = await ctx.getKeyword('Fill multiline? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
		const style = new AcDbMlineStyle();
		style.styleName = name;
		style.elements = elements;
		style.flags = flags;
		if (fillChoice === 'Yes') {
			style.flags |= 1; // FillOn
			style.fillColor = new AcCmColor().setByLayer();
		}

		mlineDict.setAt(name, style);
		db.cmlstyle = name;
		ctx.message(`Multiline style "${name}" created.`);
	} else if (act === 'rename' || act === 'r') {
		const oldName = (await ctx.getString('Enter multiline style to rename:', { allowSpaces: false })).trim();
		if (oldName.toUpperCase() === 'STANDARD') {
			ctx.message('Cannot rename the STANDARD style.');
			return;
		}
		if (!mlineDict.has(oldName)) {
			ctx.message(`Style "${oldName}" not found.`);
			return;
		}
		const newName = (await ctx.getString('Enter new style name:', { allowSpaces: false })).trim();
		if (!newName || mlineDict.has(newName)) {
			ctx.message(`Invalid or existing style name "${newName}".`);
			return;
		}
		const style = mlineDict.getAt(oldName);
		if (style) {
			style.styleName = newName;
			mlineDict.remove(oldName);
			mlineDict.setAt(newName, style);
			if (db.cmlstyle?.toLowerCase() === oldName.toLowerCase()) {
				db.cmlstyle = newName;
			}
			ctx.message(`Style "${oldName}" renamed to "${newName}".`);
		}
	} else if (act === 'delete' || act === 'd') {
		const name = (await ctx.getString('Enter multiline style to delete:', { allowSpaces: false })).trim();
		if (name.toUpperCase() === 'STANDARD') {
			ctx.message('Cannot delete the STANDARD style.');
			return;
		}
		if (db.cmlstyle?.toLowerCase() === name.toLowerCase()) {
			ctx.message('Cannot delete the current style.');
			return;
		}
		// Check in use
		const modelSpace = db.tables?.blockTable?.modelSpace;
		let inUse = false;
		if (modelSpace) {
			for (const ent of modelSpace.newIterator()) {
				if (ent instanceof AcDbMLine && ent.styleName?.toLowerCase() === name.toLowerCase()) {
					inUse = true;
					break;
				}
			}
		}
		if (inUse) {
			ctx.message(`Cannot delete style "${name}": style is in use.`);
			return;
		}
		mlineDict.remove(name);
		ctx.message(`Style "${name}" deleted.`);
	}
}

// ============================================================================
// 3. MLEADERSTYLE
// ============================================================================

export async function mleaderstyleCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const cur = db.cmleaderstyle || 'Standard';
	const mldDict = db.objects.mleaderStyle;

	const action = await ctx.getKeyword(
		`Enter multileader style option [?/New/Set/Delete] <Set>:`,
		['?', 'New', 'Set', 'Delete'],
		{ default: 'Set' },
	);

	const act = action.toLowerCase();
	if (act === '?' || act === 'list') {
		ctx.message('Defined multileader styles:');
		for (const [name, s] of mldDict.entries()) {
			const isCur = name.toLowerCase() === cur.toLowerCase();
			ctx.message(`  ${isCur ? '* ' : '  '}${name} (arrow size: ${s?.arrowSize}, text height: ${s?.textHeight})`);
		}
	} else if (act === 'set' || act === 's') {
		const name = (await ctx.getString(`Enter multileader style name <${cur}>:`, {
			allowSpaces: false,
			allowEmpty: true,
			defaultValue: cur,
		})).trim();
		if (!mldDict.has(name)) {
			ctx.message(`Multileader style "${name}" not found.`);
			return;
		}
		db.cmleaderstyle = name;
		ctx.message(`CMLEADERSTYLE is now "${name}".`);
	} else if (act === 'new' || act === 'n') {
		const name = (await ctx.getString('Enter new multileader style name:', { allowSpaces: false })).trim();
		if (!name) return;
		if (mldDict.has(name)) {
			ctx.message(`Style "${name}" already exists.`);
			return;
		}

		const arrowSize = await ctx.getDouble('Enter arrowhead size <2.5>:');
		const landingGap = await ctx.getDouble('Enter landing gap <1.5>:');
		const textHeight = await ctx.getDouble('Enter text height <2.5>:');
		const contentChoice = await ctx.getKeyword(
			'Enter content type [MText/Block/None] <MText>:',
			['MText', 'Block', 'None'],
			{ default: 'MText' },
		);

		const style = new AcDbMLeaderStyle();
		style.arrowSize = arrowSize > 0 ? arrowSize : 2.5;
		style.landingGap = landingGap > 0 ? landingGap : 1.5;
		style.enableLanding = true;
		style.enableDogleg = true;
		style.doglegLength = landingGap > 0 ? landingGap * 2 : 3.0;
		style.textHeight = textHeight > 0 ? textHeight : 2.5;
		style.contentType = contentChoice === 'Block' ? 2 : contentChoice === 'None' ? 0 : 1;

		mldDict.setAt(name, style);
		db.cmleaderstyle = name;
		ctx.message(`Multileader style "${name}" created and set as current.`);
	} else if (act === 'delete' || act === 'd') {
		const name = (await ctx.getString('Enter multileader style to delete:', { allowSpaces: false })).trim();
		if (name.toUpperCase() === 'STANDARD') {
			ctx.message('Cannot delete the STANDARD multileader style.');
			return;
		}
		if (db.cmleaderstyle?.toLowerCase() === name.toLowerCase()) {
			ctx.message('Cannot delete the current multileader style.');
			return;
		}
		// Check in use
		const modelSpace = db.tables?.blockTable?.modelSpace;
		let inUse = false;
		if (modelSpace) {
			const targetId = mldDict.getAt(name)?.objectId;
			for (const ent of modelSpace.newIterator()) {
				if (ent instanceof AcDbMLeader && (ent.mleaderStyleId === targetId || (ent as any).leaderStyleId === targetId)) {
					inUse = true;
					break;
				}
			}
		}
		if (inUse) {
			ctx.message(`Cannot delete style "${name}": style is in use.`);
			return;
		}
		mldDict.remove(name);
		ctx.message(`Style "${name}" deleted.`);
	}
}

// ============================================================================
// 4. AUDIT & RECOVER
// ============================================================================

export interface AuditResult {
	errorCount: number;
	fixedCount: number;
	messages: string[];
}

export function auditDrawing(db: AcDbDatabase, fix: boolean): AuditResult {
	let errorCount = 0;
	let fixedCount = 0;
	const messages: string[] = [];

	const report = (msg: string, fixed: boolean) => {
		errorCount++;
		if (fixed) fixedCount++;
		messages.push(msg + (fixed ? ' [Fixed]' : ''));
	};

	// 1. Check duplicate handles
	const handleRegistry = (db as any)._handleRegistry as Map<string, any> | undefined;
	const handlesSeen = new Set<string>();

	// 2. Collect all entities from modelSpace and blocks
	const allEntities: AcDbEntity[] = [];
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (modelSpace) {
		for (const ent of modelSpace.newIterator()) allEntities.push(ent);
	}
	const blockTable = db.tables?.blockTable;
	if (blockTable) {
		for (const blk of blockTable.newIterator()) {
			if (blk !== modelSpace) {
				for (const ent of blk.newIterator()) allEntities.push(ent);
			}
		}
	}

	for (const ent of allEntities) {
		const handle = ent.objectId;
		if (handle) {
			if (handlesSeen.has(handle)) {
				let didFix = false;
				if (fix) {
					ent.objectId = db.generateHandle();
					didFix = true;
				}
				report(`Duplicate handle "${handle}" on entity`, didFix);
			} else {
				handlesSeen.add(handle);
			}
		}

		// a) Missing layer check
		if (ent.layer && !db.tables.layerTable.has(ent.layer)) {
			let didFix = false;
			if (fix) {
				ent.layer = '0';
				didFix = true;
			}
			report(`Entity ${ent.objectId || 'unknown'}: layer "${ent.layer}" missing (moved to layer 0)`, didFix);
		}

		// b) Invalid linetype reference check
		const lt = ent.lineType;
		if (lt && lt !== 'ByLayer' && lt !== 'ByBlock' && lt !== 'Continuous' && lt.toUpperCase() !== 'BYLAYER' && lt.toUpperCase() !== 'BYBLOCK' && lt.toUpperCase() !== 'CONTINUOUS') {
			if (!db.tables.linetypeTable.has(lt)) {
				let didFix = false;
				if (fix) {
					ent.lineType = 'ByLayer';
					didFix = true;
				}
				report(`Entity ${ent.objectId || 'unknown'}: invalid linetype "${lt}" (reset to ByLayer)`, didFix);
			}
		}

		// c) Zero-length line and degenerate polyline (report only)
		if (ent instanceof AcDbLine) {
			const dx = ent.endPoint.x - ent.startPoint.x;
			const dy = ent.endPoint.y - ent.startPoint.y;
			const dz = ent.endPoint.z - ent.startPoint.z;
			if (Math.hypot(dx, dy, dz) < 1e-8) {
				report(`Entity ${ent.objectId}: zero-length line detected`, false);
			}
		} else if (ent instanceof AcDbPolyline) {
			const pts = polylineVertices(ent).points;
			if (pts.length < 2) {
				report(`Entity ${ent.objectId}: degenerate polyline (< 2 vertices)`, false);
			}
		}

		// d) Block reference to missing block
		if (ent instanceof AcDbBlockReference) {
			const bName = ent.blockName;
			if (bName && !db.tables.blockTable.has(bName)) {
				let didFix = false;
				if (fix) {
					db.tables.blockTable.add(new AcDbBlockTableRecord({ name: bName }));
					didFix = true;
				}
				report(`Block reference ${ent.objectId} refers to missing block "${bName}"`, didFix);
			}
		}
	}

	// e) Orphaned dictionary entries
	const dicts = [
		db.objects?.layout,
		db.objects?.group,
		db.objects?.sortentsTable,
		db.objects?.mleaderStyle,
		db.objects?.mlineStyle,
		db.objects?.imageDefinition,
		db.objects?.xrecord,
	];
	for (const dict of dicts) {
		if (!dict) continue;
		const toRemove: string[] = [];
		for (const [key, val] of dict.entries()) {
			if (val === null || val === undefined) {
				toRemove.push(key);
			}
		}
		for (const k of toRemove) {
			let didFix = false;
			if (fix) {
				dict.remove(k);
				didFix = true;
			}
			report(`Orphaned dictionary entry "${k}"`, didFix);
		}
	}

	return { errorCount, fixedCount, messages };
}

export async function auditCommand(ctx: CadCommandContext): Promise<void> {
	const choice = await ctx.getKeyword('Fix any errors detected? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
	const fix = choice.toLowerCase() === 'yes' || choice.toLowerCase() === 'y';
	const result = auditDrawing(ctx.database.native, fix);
	for (const msg of result.messages) {
		ctx.message(msg);
	}
	ctx.message(`${result.errorCount} errors found, ${result.fixedCount} fixed`);
}

export async function recoverCommand(ctx: CadCommandContext): Promise<void> {
	const filePath = await ctx.getString('Enter name of drawing file to recover <current drawing>:', {
		allowSpaces: true,
		allowEmpty: true,
	});

	let dxfText = '';
	if (filePath.trim() && ctx.readFile) {
		try {
			dxfText = await ctx.readFile(filePath.trim());
		} catch (err: any) {
			ctx.message(`Error reading file: ${err.message}`);
			return;
		}
	} else {
		// Recover current drawing DXF
		const out = ctx.database.native.dxfOut(undefined, 6);
		dxfText = typeof out === 'string' ? out : new TextDecoder().decode(out);
	}

	// Defensively parse
	let droppedCount = 0;
	const db = new AcDbDatabase();
	try {
		await db.read(dxfText, { readOnly: false }, AcDbFileType.DXF);
	} catch {
		// Attempt simple sanitization
		droppedCount++;
		try {
			const sanitized = dxfText.replace(/\r\n/g, '\n');
			await db.read(sanitized, { readOnly: false }, AcDbFileType.DXF);
		} catch (err: any) {
			ctx.message(`Recovery failed: ${err.message}`);
			return;
		}
	}

	// Run audit with fix
	const audit = auditDrawing(db, true);
	ctx.message(`Recovery complete: ${droppedCount} dropped element(s), ${audit.errorCount} errors found, ${audit.fixedCount} fixed`);
}

// ============================================================================
// 5. DATAEXTRACTION
// ============================================================================

export interface CadDataExtractionOptions {
	readonly entities?: readonly AcDbEntity[];
	readonly properties?: readonly string[];
	readonly combineIdentical?: boolean;
	readonly outputTable?: boolean;
	readonly tableInsertionPoint?: CadPoint3;
	readonly showTotals?: boolean;
}

export function dataExtraction(db: AcDbDatabase, options?: CadDataExtractionOptions): string {
	const requestedProps = options?.properties ? options.properties.map(p => p.trim()) : undefined;
	const rawEntities = options?.entities ?? (db.tables?.blockTable?.modelSpace ? Array.from(db.tables.blockTable.modelSpace.newIterator()) : []);

	// Filter out preview/generated entities
	const genSet = (globalThis as any).__saengineGenerated as Set<string> | undefined;
	const entities = rawEntities.filter(e => {
		if (genSet?.has(e.objectId)) return false;
		if ((e as any)._isGenerated) return false;
		return true;
	});

	// If no entities, return header
	const defaultProps = ['Type', 'Layer', 'Length'];
	const props = requestedProps && requestedProps.length > 0 ? requestedProps : defaultProps;

	// Helper to extract properties for an entity
	const getPropValue = (e: AcDbEntity, prop: string): string => {
		const p = prop.toLowerCase();
		if (p === 'type') {
			if (e instanceof AcDbLine) return 'Line';
			if (e instanceof AcDbCircle) return 'Circle';
			if (e instanceof AcDbPolyline) return 'Polyline';
			if (e instanceof AcDbBlockReference) return 'Block';
			if (e instanceof AcDbText || e instanceof AcDbMText) return 'Text';
			return e.dxfTypeName || e.constructor.name;
		}
		if (p === 'layer') return e.layer || '0';
		if (p === 'colour' || p === 'color') {
			return e.color?.colorMethod === 0 ? 'ByBlock' : e.color?.colorMethod === 3 ? 'ByLayer' : String(e.color?.colorIndex ?? 'ByLayer');
		}
		if (p === 'linetype') return e.lineType || 'ByLayer';
		if (p === 'length') {
			if (e instanceof AcDbLine) {
				const dx = e.endPoint.x - e.startPoint.x;
				const dy = e.endPoint.y - e.startPoint.y;
				const dz = e.endPoint.z - e.startPoint.z;
				return String(Math.round(Math.hypot(dx, dy, dz) * 10000) / 10000);
			}
			if (e instanceof AcDbPolyline) {
				const pts = polylineVertices(e).points;
				let len = 0;
				for (let i = 0; i < pts.length - 1; i++) {
					len += Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
				}
				return String(Math.round(len * 10000) / 10000);
			}
			return '0';
		}
		if (p === 'area') {
			if (e instanceof AcDbCircle) return String(Math.round(Math.PI * e.radius * e.radius * 10000) / 10000);
			return '0';
		}
		if (p === 'name' || p === 'block name') {
			if (e instanceof AcDbBlockReference) return e.blockName;
			return '';
		}
		// Block attributes
		if (e instanceof AcDbBlockReference && typeof (e as any).attributeIterator === 'function') {
			for (const attr of (e as any).attributeIterator()) {
				if (attr.tag?.toLowerCase() === p) return attr.textString || '';
			}
		}
		return '';
	};

	// Check if Count column is present
	const hasCount = props.some(p => p.toLowerCase() === 'count');

	// Grouping / collapsing rows
	if (hasCount) {
		// Group by all non-Count properties
		const otherProps = props.filter(p => p.toLowerCase() !== 'count');
		const groups = new Map<string, { count: number; row: Record<string, string> }>();

		for (const ent of entities) {
			const rowData: Record<string, string> = {};
			for (const prop of otherProps) {
				rowData[prop] = getPropValue(ent, prop);
			}
			const groupKey = otherProps.map(pr => rowData[pr]).join('|||');
			const existing = groups.get(groupKey);
			if (existing) {
				existing.count++;
			} else {
				groups.set(groupKey, { count: 1, row: rowData });
			}
		}

		const rows: string[] = [props.join(',')];
		for (const g of groups.values()) {
			const rowVals = props.map(pr => (pr.toLowerCase() === 'count' ? String(g.count) : g.row[pr] ?? ''));
			rows.push(rowVals.join(','));
		}
		return rows.join('\n');
	}

	// Normal extraction: one row per entity
	const rows: string[] = [props.join(',')];
	for (const ent of entities) {
		const rowVals = props.map(pr => getPropValue(ent, pr));
		rows.push(rowVals.join(','));
	}

	return rows.join('\n');
}

export async function dataextractionCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects for data extraction or press Enter for all:');
	const entities = sel.length > 0 ? sel : ctx.database.native.tables?.blockTable?.modelSpace ? Array.from(ctx.database.native.tables.blockTable.modelSpace.newIterator()) : [];

	const propString = await ctx.getString('Enter properties to extract comma-separated [Type,Layer,Length] <Type,Layer,Length>:', {
		allowSpaces: true,
		allowEmpty: true,
		defaultValue: 'Type,Layer,Length',
	});
	const properties = propString.split(',').map(s => s.trim()).filter(Boolean);

	const outputDest = await ctx.getKeyword('Output destination [Table/CSV/Both] <Both>:', ['Table', 'CSV', 'Both'], { default: 'Both' });

	const csv = dataExtraction(ctx.database.native, { entities, properties });

	if (outputDest === 'Table' || outputDest === 'Both') {
		const origin = await ctx.getPoint('Specify table insertion point:');
		const lines = csv.split('\n').map(l => l.split(','));
		const numRows = lines.length;
		const numCols = properties.length;
		const rowHeight = 8;
		const colWidth = 40;

		const tableEntities: AcDbEntity[] = tableGrid(numRows, numCols, rowHeight, colWidth, origin).map(s => new AcDbLine(new AcGePoint3d(s.start), new AcGePoint3d(s.end)));
		for (let r = 0; r < numRows; r++) {
			for (let c = 0; c < numCols; c++) {
				const val = lines[r][c] || '';
				const t = new AcDbMText();
				t.contents = val;
				t.location = new AcGePoint3d(origin.x + c * colWidth + colWidth * 0.1, origin.y - r * rowHeight - rowHeight * 0.75, origin.z);
				t.height = 2.5;
				tableEntities.push(t);
			}
		}
		ctx.database.add(tableEntities);
	}

	if (outputDest === 'CSV' || outputDest === 'Both') {
		ctx.message('Data extraction CSV output:');
		ctx.message(csv);
	}
}

// ============================================================================
// 6. LAYWALK
// ============================================================================

export async function laywalkCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const layerTable = db.tables?.layerTable;
	if (!layerTable) return;

	const layers = Array.from(layerTable.newIterator());
	if (layers.length === 0) {
		ctx.message('No layers found.');
		return;
	}

	// Save original layer states
	const originalStates = layers.map(l => ({
		record: l,
		isOff: l.isOff,
		isFrozen: l.isFrozen,
	}));

	let currentIndex = 0;

	const isolateLayer = (idx: number) => {
		for (let i = 0; i < layers.length; i++) {
			const rec = layers[i];
			if (i === idx) {
				rec.isOff = false;
				rec.isFrozen = false;
			} else {
				rec.isOff = true;
			}
		}
		ctx.message(`Layer ${idx + 1}/${layers.length}: "${layers[idx].name}"`);
	};

	try {
		isolateLayer(currentIndex);

		while (true) {
			const choice = await ctx.getKeyword(
				'Enter an option [Next/Previous/Select/Exit] <Next>:',
				['Next', 'Previous', 'Select', 'Exit'],
				{ default: 'Next' },
			);

			const kw = choice.toLowerCase();
			if (kw === 'next' || kw === 'n') {
				currentIndex = (currentIndex + 1) % layers.length;
				isolateLayer(currentIndex);
			} else if (kw === 'previous' || kw === 'p') {
				currentIndex = (currentIndex - 1 + layers.length) % layers.length;
				isolateLayer(currentIndex);
			} else if (kw === 'select' || kw === 's') {
				const name = (await ctx.getString('Enter layer name to display:', { allowSpaces: true })).trim();
				const found = layers.findIndex(l => l.name.toLowerCase() === name.toLowerCase());
				if (found >= 0) {
					currentIndex = found;
					isolateLayer(currentIndex);
				} else {
					ctx.message(`Layer "${name}" not found.`);
				}
			} else if (kw === 'exit' || kw === 'e') {
				break;
			}
		}
	} finally {
		// Restore layer states exactly
		for (const s of originalStates) {
			s.record.isOff = s.isOff;
			s.record.isFrozen = s.isFrozen;
		}
		ctx.message('Layer states restored.');
	}
}

// ============================================================================
// Registration helper
// ============================================================================

export function registerStylesAuditCommands(): void {
	registerCommand('MLSTYLE', mlstyleCommand, { aliases: ['-MLSTYLE'] });
	registerCommand('-MLSTYLE', mlstyleCommand);
	registerCommand('TABLESTYLE', tablestyleCommand, { aliases: ['-TABLESTYLE'] });
	registerCommand('-TABLESTYLE', tablestyleCommand);
	registerCommand('MLEADERSTYLE', mleaderstyleCommand, { aliases: ['-MLEADERSTYLE'] });
	registerCommand('-MLEADERSTYLE', mleaderstyleCommand);
	registerCommand('AUDIT', auditCommand);
	registerCommand('RECOVER', recoverCommand);
	registerCommand('DATAEXTRACTION', dataextractionCommand, { aliases: ['-DATAEXTRACTION'] });
	registerCommand('-DATAEXTRACTION', dataextractionCommand);
	registerCommand('LAYWALK', laywalkCommand);
}
