/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbBlockReference, AcDbBlockTableRecord, AcDbBlockTableRecordFlag,
	AcDbDatabase, AcDbDxfCode, AcDbEntity, AcDbLine, AcDbRegAppTableRecord,
	AcDbResultBuffer, AcGeMatrix3d, AcGePoint3d, AcGeVector3d,
} from '@mlightcad/data-model';
import { AcDbRenderingCache } from '@mlightcad/data-model';
import type { CadCommandContext, CadPoint3 } from './commands.js';
import { mirrorPoint } from './commands.js';

export const DYNBLOCK_DEF_APPID = 'SA_DYNBLOCK_DEF';
export const DYNBLOCK_INST_APPID = 'SA_DYNBLOCK_INST';

export interface LinearParam {
	readonly type: 'linear';
	readonly name: string;
	readonly startPoint: CadPoint3;
	readonly endPoint: CadPoint3;
	readonly defaultDistance: number;
	readonly action?: 'stretch';
}

export interface FlipParam {
	readonly type: 'flip';
	readonly name: string;
	readonly lineStart: CadPoint3;
	readonly lineEnd: CadPoint3;
	readonly defaultState: 0 | 1;
	readonly action?: 'flip';
}

export interface VisibilityParam {
	readonly type: 'visibility';
	readonly name: string;
	readonly states: readonly string[];
	readonly defaultState: string;
	readonly stateVisibility?: Record<string, readonly number[]>;
}

export interface RotationParam {
	readonly type: 'rotation';
	readonly name: string;
	readonly center: CadPoint3;
	readonly baseAngle: number;
	readonly defaultAngle: number;
}

export type DynamicParam = LinearParam | FlipParam | VisibilityParam | RotationParam;

export interface DynamicBlockDef {
	readonly params: readonly DynamicParam[];
}

export interface DynamicBlockProps {
	readonly originalBlockName: string;
	readonly values: Record<string, number | string>;
}

function ensureAppId(db: AcDbDatabase, appId: string): void {
	if (db.tables?.appIdTable && !db.tables.appIdTable.has(appId)) {
		try {
			db.tables.appIdTable.add(new AcDbRegAppTableRecord(appId));
		} catch {}
	}
}

function chunkString(str: string, size = 200): string[] {
	const chunks: string[] = [];
	for (let i = 0; i < str.length; i += size) {
		chunks.push(str.slice(i, i + size));
	}
	return chunks.length ? chunks : [''];
}

function writeXData(db: AcDbDatabase, obj: { setXData(rb: AcDbResultBuffer): void }, appId: string, data: unknown): void {
	ensureAppId(db, appId);
	const json = JSON.stringify(data);
	const chunks = chunkString(json);
	const rb = new AcDbResultBuffer([
		{ code: AcDbDxfCode.ExtendedDataRegAppName, value: appId },
		...chunks.map(chunk => ({ code: AcDbDxfCode.ExtendedDataAsciiString, value: chunk })),
	]);
	obj.setXData(rb);
}

function readXData<T>(obj: { getXData(appId: string): AcDbResultBuffer | undefined }, appId: string): T | undefined {
	const rb = obj.getXData(appId);
	if (!rb) return undefined;
	const parts: string[] = [];
	for (const item of rb) {
		if (item.code === AcDbDxfCode.ExtendedDataAsciiString && typeof item.value === 'string') {
			parts.push(item.value);
		}
	}
	if (!parts.length) return undefined;
	try {
		return JSON.parse(parts.join('')) as T;
	} catch {
		return undefined;
	}
}

export function setDynamicBlockDef(db: AcDbDatabase, record: AcDbBlockTableRecord, def: DynamicBlockDef): void {
	writeXData(db, record, DYNBLOCK_DEF_APPID, def);
	// Also attach to first entity in block for backwards/downstream DXF reader compatibility
	const firstEnt = record.newIterator().next().value;
	if (firstEnt) {
		writeXData(db, firstEnt, DYNBLOCK_DEF_APPID, def);
	}
}

export function getDynamicBlockDef(record: AcDbBlockTableRecord): DynamicBlockDef | undefined {
	const fromRecord = readXData<DynamicBlockDef>(record, DYNBLOCK_DEF_APPID);
	if (fromRecord) return fromRecord;
	const firstEnt = record.newIterator().next().value;
	if (firstEnt) {
		return readXData<DynamicBlockDef>(firstEnt, DYNBLOCK_DEF_APPID);
	}
	return undefined;
}

export function setDynamicBlockProps(db: AcDbDatabase, ref: AcDbBlockReference, props: DynamicBlockProps): void {
	writeXData(db, ref, DYNBLOCK_INST_APPID, props);
}

export function getDynamicBlockProps(ref: AcDbBlockReference): DynamicBlockProps | undefined {
	return readXData<DynamicBlockProps>(ref, DYNBLOCK_INST_APPID);
}

/**
 * Regenerates an anonymous block (*U) for a dynamic block reference according
 * to its assigned parameter values, mirroring AutoCAD's dynamic block architecture.
 */
export function regenerateDynamicBlockReference(db: AcDbDatabase, ref: AcDbBlockReference): AcDbBlockTableRecord {
	const existingProps = getDynamicBlockProps(ref);
	const origName = existingProps?.originalBlockName || ref.blockName;
	const masterRecord = db.tables.blockTable.getAt(origName);
	if (!masterRecord) {
		throw new Error(`Master block definition "${origName}" not found`);
	}

	const def = getDynamicBlockDef(masterRecord);
	const values = { ...(existingProps?.values ?? {}) };

	// Create anonymous block table record name (*U1, *U2, ...)
	let anonIdx = 1;
	while (db.tables.blockTable.has(`*U${anonIdx}`)) {
		anonIdx++;
	}
	const anonName = `*U${anonIdx}`;
	const anonRecord = new AcDbBlockTableRecord({
		name: anonName,
		origin: masterRecord.origin.clone(),
		flags: AcDbBlockTableRecordFlag.Anonymous,
	});

	// If no dynamic definition is attached, clone entities as-is
	if (!def || !def.params.length) {
		for (const ent of masterRecord.newIterator()) {
			anonRecord.appendEntity(ent.clone() as AcDbEntity);
		}
		db.tables.blockTable.add(anonRecord);
		ref.blockName = anonName;
		setDynamicBlockProps(db, ref, { originalBlockName: origName, values });
		try { AcDbRenderingCache.instance?.clear(); } catch {}
		return anonRecord;
	}

	// 1. Process Visibility state filtering
	const masterEntities = Array.from(masterRecord.newIterator()) as AcDbEntity[];
	let candidateEntities: Array<{ entity: AcDbEntity; origIndex: number }> = masterEntities.map((e, idx) => ({
		entity: e.clone() as AcDbEntity,
		origIndex: idx,
	}));

	for (const param of def.params) {
		if (param.type === 'visibility') {
			const activeState = String(values[param.name] ?? param.defaultState);
			if (param.stateVisibility && param.stateVisibility[activeState]) {
				const visibleSet = new Set(param.stateVisibility[activeState]);
				candidateEntities = candidateEntities.filter(c => visibleSet.has(c.origIndex));
			}
		}
	}

	// 2. Process Linear Stretch, Flip, and Rotation actions
	for (const param of def.params) {
		if (param.type === 'linear') {
			const curVal = Number(values[param.name] ?? param.defaultDistance);
			const delta = curVal - param.defaultDistance;
			if (Math.abs(delta) > 1e-9) {
				const dx = param.endPoint.x - param.startPoint.x;
				const dy = param.endPoint.y - param.startPoint.y;
				const len = Math.hypot(dx, dy) || 1;
				const ux = dx / len;
				const uy = dy / len;
				const vx = delta * ux;
				const vy = delta * uy;

				for (const item of candidateEntities) {
					const ent = item.entity;
					if (ent instanceof AcDbLine) {
						// Stretch line end point if it's near/at the parameter end
						const projStart = (ent.startPoint.x - param.startPoint.x) * ux + (ent.startPoint.y - param.startPoint.y) * uy;
						const projEnd = (ent.endPoint.x - param.startPoint.x) * ux + (ent.endPoint.y - param.startPoint.y) * uy;
						if (projEnd > 0.5 * len) {
							ent.endPoint = new AcGePoint3d(ent.endPoint.x + vx, ent.endPoint.y + vy, ent.endPoint.z);
						}
						if (projStart > 0.5 * len) {
							ent.startPoint = new AcGePoint3d(ent.startPoint.x + vx, ent.startPoint.y + vy, ent.startPoint.z);
						}
					} else {
						// General stretch translation
						ent.transformBy(new AcGeMatrix3d().makeTranslation(vx, vy, 0));
					}
				}
			}
		} else if (param.type === 'flip') {
			const state = Number(values[param.name] ?? param.defaultState);
			if (state === 1) {
				for (const item of candidateEntities) {
					const ent = item.entity;
					if (ent instanceof AcDbLine) {
						ent.startPoint = mirrorPoint(ent.startPoint, param.lineStart, param.lineEnd);
						ent.endPoint = mirrorPoint(ent.endPoint, param.lineStart, param.lineEnd);
					} else {
						// Reflect about 2D line
						const p1 = param.lineStart;
						const p2 = param.lineEnd;
						const dx = p2.x - p1.x;
						const dy = p2.y - p1.y;
						const angle = Math.atan2(dy, dx);
						const mat = new AcGeMatrix3d()
							.makeTranslation(-p1.x, -p1.y, 0)
							.premultiply(new AcGeMatrix3d().makeRotationZ(-angle))
							.premultiply(new AcGeMatrix3d().makeScale(1, -1, 1))
							.premultiply(new AcGeMatrix3d().makeRotationZ(angle))
							.premultiply(new AcGeMatrix3d().makeTranslation(p1.x, p1.y, 0));
						ent.transformBy(mat);
					}
				}
			}
		} else if (param.type === 'rotation') {
			const curAngle = Number(values[param.name] ?? param.defaultAngle);
			const deltaAngle = curAngle - param.baseAngle;
			if (Math.abs(deltaAngle) > 1e-9) {
				const center = param.center;
				const mat = new AcGeMatrix3d()
					.makeTranslation(-center.x, -center.y, -center.z)
					.premultiply(new AcGeMatrix3d().makeRotationZ(deltaAngle))
					.premultiply(new AcGeMatrix3d().makeTranslation(center.x, center.y, center.z));
				for (const item of candidateEntities) {
					item.entity.transformBy(mat);
				}
			}
		}
	}

	for (const item of candidateEntities) {
		anonRecord.appendEntity(item.entity);
	}
	db.tables.blockTable.add(anonRecord);
	ref.blockName = anonName;
	setDynamicBlockProps(db, ref, { originalBlockName: origName, values });
	try { AcDbRenderingCache.instance?.clear(); } catch {}
	return anonRecord;
}

/**
 * BPARAMETER command: Define or add a dynamic block parameter/action to a block definition.
 */
export async function bparameterCommand(ctx: CadCommandContext): Promise<void> {
	let blockName = '';
	if (typeof ctx.getString === 'function') {
		blockName = (await ctx.getString('Enter block name to configure dynamic parameters:', { allowSpaces: false, allowEmpty: true })).trim();
	}
	if (!blockName && typeof ctx.getEntity === 'function') {
		const ent = await ctx.getEntity('Select block reference:');
		if (ent instanceof AcDbBlockReference) {
			const props = getDynamicBlockProps(ent);
			blockName = props?.originalBlockName || ent.blockName;
		}
	}
	if (!blockName) {
		throw new Error('No block specified for BPARAMETER');
	}

	const record = ctx.database.native.tables.blockTable.getAt(blockName);
	if (!record) {
		throw new Error(`Block "${blockName}" not found`);
	}

	const existingDef = getDynamicBlockDef(record) ?? { params: [] };
	const params: DynamicParam[] = [...existingDef.params];

	const paramType = (await ctx.getKeyword(
		'Enter parameter type [Linear/Flip/Visibility/Rotation] <Linear>:',
		['Linear', 'Flip', 'Visibility', 'Rotation'],
		{ default: 'Linear' },
	)).toLowerCase();

	if (paramType === 'linear') {
		const name = (await ctx.getString('Enter parameter name <Distance>:', { allowSpaces: false, allowEmpty: true, defaultValue: 'Distance' })).trim() || 'Distance';
		const start = await ctx.getPoint('Specify parameter start point:');
		const end = await ctx.getPoint('Specify parameter endpoint:', { base: start });
		const dx = end.x - start.x;
		const dy = end.y - start.y;
		const dist = Math.hypot(dx, dy);
		params.push({
			type: 'linear',
			name,
			startPoint: { x: start.x, y: start.y, z: start.z ?? 0 },
			endPoint: { x: end.x, y: end.y, z: end.z ?? 0 },
			defaultDistance: dist,
			action: 'stretch',
		});
		ctx.message(`Linear parameter "${name}" (length ${dist.toFixed(4)}) with Stretch action added.`);
	} else if (paramType === 'flip') {
		const name = (await ctx.getString('Enter parameter name <Flip>:', { allowSpaces: false, allowEmpty: true, defaultValue: 'Flip' })).trim() || 'Flip';
		const p1 = await ctx.getPoint('Specify base point of reflection line:');
		const p2 = await ctx.getPoint('Specify endpoint of reflection line:', { base: p1 });
		params.push({
			type: 'flip',
			name,
			lineStart: { x: p1.x, y: p1.y, z: p1.z ?? 0 },
			lineEnd: { x: p2.x, y: p2.y, z: p2.z ?? 0 },
			defaultState: 0,
			action: 'flip',
		});
		ctx.message(`Flip parameter "${name}" with Flip action added.`);
	} else if (paramType === 'visibility') {
		const name = (await ctx.getString('Enter parameter name <Visibility>:', { allowSpaces: false, allowEmpty: true, defaultValue: 'Visibility' })).trim() || 'Visibility';
		const statesInput = await ctx.getString('Enter comma-separated visibility states <State1,State2>:', { allowSpaces: true, allowEmpty: true, defaultValue: 'State1,State2' });
		const states = statesInput.split(',').map(s => s.trim()).filter(Boolean);
		params.push({
			type: 'visibility',
			name,
			states: states.length ? states : ['State1', 'State2'],
			defaultState: states[0] || 'State1',
		});
		ctx.message(`Visibility parameter "${name}" with states [${states.join(', ')}] added.`);
	} else if (paramType === 'rotation') {
		const name = (await ctx.getString('Enter parameter name <Angle>:', { allowSpaces: false, allowEmpty: true, defaultValue: 'Angle' })).trim() || 'Angle';
		const center = await ctx.getPoint('Specify parameter base/center point:');
		params.push({
			type: 'rotation',
			name,
			center: { x: center.x, y: center.y, z: center.z ?? 0 },
			baseAngle: 0,
			defaultAngle: 0,
		});
		ctx.message(`Rotation parameter "${name}" added.`);
	}

	await ctx.transaction(async () => {
		setDynamicBlockDef(ctx.database.native, record, { params });
	});
}

/**
 * -DYNPROP command: Edit dynamic properties on a selected block reference.
 * AutoCAD regenerates the reference as an anonymous block (*U) with modified geometry.
 */
export async function dynpropCommand(ctx: CadCommandContext): Promise<void> {
	const ent = await ctx.getEntity('Select dynamic block reference:');
	if (!(ent instanceof AcDbBlockReference)) {
		throw new Error('Selected entity is not a block reference');
	}

	const db = ctx.database.native;
	const existingProps = getDynamicBlockProps(ent);
	const origName = existingProps?.originalBlockName || ent.blockName;
	const masterRecord = db.tables.blockTable.getAt(origName);
	if (!masterRecord) {
		throw new Error(`Master block definition "${origName}" not found`);
	}

	const def = getDynamicBlockDef(masterRecord);
	if (!def || !def.params.length) {
		ctx.message(`Block "${origName}" has no dynamic parameters defined.`);
		return;
	}

	const currentValues = { ...(existingProps?.values ?? {}) };
	const paramNames = def.params.map(p => p.name);
	const summary = def.params.map(p => {
		const val = currentValues[p.name] ?? (
			p.type === 'linear' ? p.defaultDistance :
			p.type === 'flip' ? p.defaultState :
			p.type === 'visibility' ? p.defaultState :
			p.defaultAngle
		);
		return `${p.name}=${val}`;
	}).join(', ');

	ctx.message(`Dynamic parameters: [${summary}]`);
	const chosenName = await ctx.getKeyword(
		`Select parameter to change [${paramNames.join('/')}]:`,
		paramNames,
		{ default: paramNames[0] },
	);

	const param = def.params.find(p => p.name.toUpperCase() === chosenName.toUpperCase());
	if (!param) {
		throw new Error(`Parameter "${chosenName}" not found`);
	}

	let newVal: number | string;
	if (param.type === 'linear') {
		const curVal = Number(currentValues[param.name] ?? param.defaultDistance);
		newVal = await ctx.getDouble(`Enter new distance for ${param.name} <${curVal}>:`);
	} else if (param.type === 'flip') {
		const curState = Number(currentValues[param.name] ?? param.defaultState);
		const kw = await ctx.getKeyword(`Flip state [0/1] <${curState}>:`, ['0', '1'], { default: String(curState) });
		newVal = Number(kw) as 0 | 1;
	} else if (param.type === 'visibility') {
		const curState = String(currentValues[param.name] ?? param.defaultState);
		newVal = await ctx.getKeyword(
			`Select visibility state [${param.states.join('/')}] <${curState}>:`,
			param.states,
			{ default: curState },
		);
	} else {
		// rotation
		const curAngle = Number(currentValues[param.name] ?? param.defaultAngle);
		newVal = await ctx.getAngle(`Enter new angle for ${param.name} <${curAngle}>:`);
	}

	currentValues[param.name] = newVal;
	await ctx.transaction(async () => {
		setDynamicBlockProps(db, ent, { originalBlockName: origName, values: currentValues });
		regenerateDynamicBlockReference(db, ent);
	});
	ctx.message(`Parameter "${param.name}" updated to ${newVal}. Reference regenerated.`);
}
