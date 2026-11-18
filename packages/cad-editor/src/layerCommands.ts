/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcCmColor, AcCmColorMethod, AcDbDatabase, AcDbEntity, AcDbLayerTableRecord,
	AcDbLinetypeTableRecord, AcGiLineWeight,
} from '@mlightcad/data-model';
import type { CadCommandContext } from './commands.js';
import { parseColor, parseLineweight } from './properties.js';
import { loadBuiltinLinetype } from './linetypes.js';

export interface CadLayerProps {
	readonly color?: number | { r: number; g: number; b: number } | string;
	readonly linetype?: string;
	readonly lineweight?: number | string;
	readonly on?: boolean;
	readonly frozen?: boolean;
	readonly locked?: boolean;
	readonly plot?: boolean;
	readonly description?: string;
}

export interface CadLayerPatch {
	readonly name?: string;
	readonly color?: number | { r: number; g: number; b: number } | string;
	readonly linetype?: string;
	readonly lineweight?: number | string;
	readonly on?: boolean;
	readonly frozen?: boolean;
	readonly locked?: boolean;
	readonly plot?: boolean;
	readonly description?: string;
}

export interface CadLayerInfo {
	readonly name: string;
	readonly color: number | { r: number; g: number; b: number };
	readonly linetype: string;
	readonly lineweight: number;
	readonly on: boolean;
	readonly frozen: boolean;
	readonly locked: boolean;
	readonly plot: boolean;
	readonly current: boolean;
	readonly inUse: boolean;
	readonly generated: boolean;
}

const LOCKED_FLAG = 0x04;
const FROZEN_FLAG = 0x01;

/**
 * Checks if a layer is referenced by any entity in model space or block definitions.
 */
export function isLayerReferenced(db: AcDbDatabase, name: string): boolean {
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (modelSpace) {
		for (const ent of modelSpace.newIterator()) {
			if (ent.layer === name) return true;
		}
	}
	const blockTable = db.tables?.blockTable;
	if (blockTable) {
		for (const block of blockTable.newIterator()) {
			for (const ent of block.newIterator()) {
				if (ent.layer === name) return true;
			}
		}
	}
	return false;
}

/**
 * Ensures a layer exists in the database, updating it with the given props if provided.
 */
export function ensureLayer(db: AcDbDatabase, name: string, props?: CadLayerProps): AcDbLayerTableRecord {
	const table = db.tables.layerTable;
	let record = table.getAt(name);
	if (!record) {
		const colorVal = props?.color !== undefined ? parseColor(props.color) : new AcCmColor(AcCmColorMethod.ByACI, 7);
		let standardFlags = 0;
		if (props?.frozen) standardFlags |= FROZEN_FLAG;
		if (props?.locked) standardFlags |= LOCKED_FLAG;

		record = new AcDbLayerTableRecord({
			name,
			color: colorVal,
			linetype: props?.linetype || 'Continuous',
			lineWeight: props?.lineweight !== undefined ? parseLineweight(props.lineweight) : AcGiLineWeight.ByLineWeightDefault,
			isOff: props?.on !== undefined ? !props.on : false,
			isPlottable: props?.plot !== undefined ? props.plot : true,
			description: props?.description || '',
			standardFlags,
		});
		if (props?.frozen !== undefined) record.isFrozen = props.frozen;
		if (props?.locked !== undefined) record.isLocked = props.locked;
		table.add(record);
	} else if (props) {
		if (props.color !== undefined) record.color = parseColor(props.color);
		if (props.linetype !== undefined) record.linetype = props.linetype;
		if (props.lineweight !== undefined) record.lineWeight = parseLineweight(props.lineweight);
		if (props.on !== undefined) record.isOff = !props.on;
		if (props.frozen !== undefined) record.isFrozen = props.frozen;
		if (props.locked !== undefined) record.isLocked = props.locked;
		if (props.plot !== undefined) record.isPlottable = props.plot;
		if (props.description !== undefined) record.description = props.description;
	}
	return record;
}

/**
 * Sets current layer for the database, creating it if needed.
 */
export function setCurrentLayer(db: AcDbDatabase, name: string): void {
	ensureLayer(db, name);
	db.clayer = name;
}

/**
 * Lists all layers in the database with their current attributes and state.
 */
export function listLayers(db: AcDbDatabase, generatedLayers: ReadonlySet<string>): CadLayerInfo[] {
	const table = db.tables.layerTable;
	const clayer = (db.clayer || '0').toUpperCase();
	const result: CadLayerInfo[] = [];

	for (const rec of table.newIterator()) {
		const colorVal = rec.color.isByColor
			? { r: rec.color.red ?? 0, g: rec.color.green ?? 0, b: rec.color.blue ?? 0 }
			: (rec.color.colorIndex ?? 7);

		const inUse = !!rec.isInUse || isLayerReferenced(db, rec.name);
		result.push({
			name: rec.name,
			color: colorVal,
			linetype: rec.linetype || 'Continuous',
			lineweight: rec.lineWeight,
			on: !rec.isOff,
			frozen: !!rec.isFrozen,
			locked: !!rec.isLocked,
			plot: rec.isPlottable !== false,
			current: rec.name.toUpperCase() === clayer,
			inUse,
			generated: generatedLayers.has(rec.name),
		});
	}
	return result;
}

/**
 * Modifies layer properties, including renaming (with protections).
 */
export function setLayer(
	db: AcDbDatabase,
	name: string,
	patch: CadLayerPatch,
	generatedLayers: ReadonlySet<string>,
	onModified?: (record: AcDbLayerTableRecord, changes: any) => void,
): void {
	// Rename check
	if (patch.name && patch.name !== name) {
		const upper = name.toUpperCase();
		const curUpper = (db.clayer || '').toUpperCase();
		if (upper === '0' || upper === 'DEFPOINTS' || upper === curUpper || generatedLayers.has(name)) {
			throw new Error(`Cannot rename protected layer "${name}"`);
		}
		if (db.tables.layerTable.has(patch.name)) {
			throw new Error(`Layer "${patch.name}" already exists`);
		}
	}

	const table = db.tables.layerTable;
	const record = table.getAt(name);
	if (!record) {
		throw new Error(`Layer "${name}" does not exist`);
	}

	const changes: any = {};

	if (patch.name && patch.name !== name) {
		// Reassign entities on this layer
		const space = db.tables?.blockTable?.modelSpace;
		if (space) {
			for (const ent of space.newIterator()) {
				if (ent.layer === name) ent.layer = patch.name;
			}
		}
		const blockTable = db.tables?.blockTable;
		if (blockTable) {
			for (const block of blockTable.newIterator()) {
				for (const ent of block.newIterator()) {
					if (ent.layer === name) ent.layer = patch.name;
				}
			}
		}
		record.name = patch.name;
		changes.name = patch.name;
	}

	if (patch.color !== undefined) {
		record.color = parseColor(patch.color);
		changes.color = record.color;
	}
	if (patch.linetype !== undefined) {
		record.linetype = patch.linetype;
		changes.linetype = patch.linetype;
	}
	if (patch.lineweight !== undefined) {
		record.lineWeight = parseLineweight(patch.lineweight);
		changes.lineWeight = record.lineWeight;
	}
	if (patch.on !== undefined) {
		record.isOff = !patch.on;
		changes.isOff = record.isOff;
	}
	if (patch.frozen !== undefined) {
		record.isFrozen = patch.frozen;
		changes.isFrozen = record.isFrozen;
	}
	if (patch.locked !== undefined) {
		record.isLocked = patch.locked;
		changes.isLocked = record.isLocked;
	}
	if (patch.plot !== undefined) {
		record.isPlottable = patch.plot;
		changes.isPlottable = record.isPlottable;
	}
	if (patch.description !== undefined) {
		record.description = patch.description;
		changes.description = record.description;
	}

	onModified?.(record, changes);
}

/**
 * Deletes a layer, refusing layer 0, DEFPOINTS, current layer, in-use layers, and generated layers.
 */
export function deleteLayer(db: AcDbDatabase, name: string, generatedLayers: ReadonlySet<string>): void {
	const upper = name.toUpperCase();
	const curUpper = (db.clayer || '').toUpperCase();
	if (upper === '0' || upper === 'DEFPOINTS' || upper === curUpper || generatedLayers.has(name)) {
		throw new Error(`Cannot delete protected layer "${name}"`);
	}
	if (isLayerReferenced(db, name)) {
		throw new Error(`Cannot delete layer "${name}" because it is currently in use`);
	}
	const table = db.tables.layerTable;
	const record = table.getAt(name);
	if (!record) {
		throw new Error(`Layer "${name}" does not exist`);
	}
	table.remove(name);
}

/**
 * Merges source layer into target layer, moving all entities and deleting the source layer.
 */
export function mergeLayers(db: AcDbDatabase, sourceName: string, targetName: string, generatedLayers: ReadonlySet<string>): void {
	if (sourceName === targetName) return;
	const sUpper = sourceName.toUpperCase();
	if (sUpper === '0' || sUpper === 'DEFPOINTS' || generatedLayers.has(sourceName)) {
		throw new Error(`Cannot merge protected layer "${sourceName}"`);
	}
	ensureLayer(db, targetName);

	const space = db.tables?.blockTable?.modelSpace;
	if (space) {
		for (const ent of space.newIterator()) {
			if (ent.layer === sourceName) ent.layer = targetName;
		}
	}
	const blockTable = db.tables?.blockTable;
	if (blockTable) {
		for (const block of blockTable.newIterator()) {
			for (const ent of block.newIterator()) {
				if (ent.layer === sourceName) ent.layer = targetName;
			}
		}
	}

	if ((db.clayer || '').toUpperCase() === sUpper) {
		db.clayer = targetName;
	}

	db.tables.layerTable.remove(sourceName);
}

// Session snapshot for LAYISO / LAYUNISO
interface LayerStateSnapshot {
	readonly on: boolean;
	readonly frozen: boolean;
	readonly locked: boolean;
}
let activeLayisoSnapshot: Map<string, LayerStateSnapshot> | undefined;

/**
 * -LAYER / LAYER command: comprehensive command-line layer manager.
 */
export async function layerCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	const generatedLayers = (globalThis as any).__saengineGeneratedLayers ?? new Set<string>();

	while (true) {
		const opt = await ctx.getKeyword(
			'Enter an option [?/Make/Set/New/ON/OFF/Color/Ltype/LWeight/Freeze/Thaw/LOck/Unlock/Plot/Rename/Delete]:',
			['?', 'Make', 'Set', 'New', 'ON', 'OFF', 'Color', 'Ltype', 'LWeight', 'Freeze', 'Thaw', 'LOck', 'Unlock', 'Plot', 'Rename', 'Delete'],
			{ default: '?' },
		);
		const upper = opt.toUpperCase();

		if (upper === '?') {
			const list = listLayers(db, generatedLayers);
			ctx.message('Layer table:');
			for (const l of list) {
				const col = typeof l.color === 'object' ? `RGB(${l.color.r},${l.color.g},${l.color.b})` : l.color;
				const flags = `${l.current ? '*' : ' '} ${l.on ? 'ON' : 'OFF'} ${l.frozen ? 'FRZ' : '   '} ${l.locked ? 'LCK' : '   '} ${l.plot ? 'PLT' : '   '}`;
				ctx.message(`  ${flags} ${l.name.padEnd(20)} color: ${col} ltype: ${l.linetype} lweight: ${l.lineweight}`);
			}
			break;
		} else if (upper === 'MAKE' || upper === 'M') {
			const name = await ctx.getString('Enter name for new layer <0>:');
			if (name) {
				ensureLayer(db, name);
				setCurrentLayer(db, name);
				ctx.message(`Layer "${name}" is now current.`);
			}
			break;
		} else if (upper === 'SET' || upper === 'S') {
			const name = await ctx.getString(`Enter layer name to set current <${db.clayer}>:`);
			if (name) {
				if (!db.tables.layerTable.has(name)) {
					throw new Error(`Layer "${name}" does not exist`);
				}
				setCurrentLayer(db, name);
				ctx.message(`Current layer is now "${name}".`);
			}
			break;
		} else if (upper === 'NEW' || upper === 'N') {
			const input = await ctx.getString('Enter name list for new layer(s):');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				ensureLayer(db, name);
				ctx.message(`Layer "${name}" created.`);
			}
			break;
		} else if (upper === 'ON') {
			const input = await ctx.getString('Enter layer name(s) to turn ON:');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.isOff = false;
			}
			ctx.message('Layers turned on.');
			break;
		} else if (upper === 'OFF') {
			const input = await ctx.getString('Enter layer name(s) to turn OFF:');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) {
					if (rec.name.toUpperCase() === (db.clayer || '').toUpperCase()) {
						const ans = await ctx.getKeyword('Really want to turn the current layer off? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
						if (ans.toLowerCase() !== 'yes') continue;
					}
					rec.isOff = true;
				}
			}
			ctx.message('Layers turned off.');
			break;
		} else if (upper === 'COLOR' || upper === 'C') {
			const colorStr = await ctx.getString('Enter color:');
			const layerNames = (await ctx.getString(`Enter layer name(s) for color ${colorStr} <${db.clayer}>:`)) || db.clayer;
			const names = layerNames.split(',').map(s => s.trim()).filter(Boolean);
			const c = parseColor(colorStr);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.color = c;
			}
			break;
		} else if (upper === 'LTYPE' || upper === 'L') {
			const lt = await ctx.getString('Enter linetype name:');
			const layerNames = (await ctx.getString(`Enter layer name(s) for linetype ${lt} <${db.clayer}>:`)) || db.clayer;
			const names = layerNames.split(',').map(s => s.trim()).filter(Boolean);
			loadBuiltinLinetype(db, lt);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.linetype = lt;
			}
			break;
		} else if (upper === 'LWEIGHT' || upper === 'LW') {
			const lwStr = await ctx.getString('Enter lineweight:');
			const layerNames = (await ctx.getString(`Enter layer name(s) for lineweight ${lwStr} <${db.clayer}>:`)) || db.clayer;
			const names = layerNames.split(',').map(s => s.trim()).filter(Boolean);
			const lw = parseLineweight(lwStr);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.lineWeight = lw;
			}
			break;
		} else if (upper === 'FREEZE' || upper === 'F') {
			const input = await ctx.getString('Enter layer name(s) to freeze:');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				if (name.toUpperCase() === (db.clayer || '').toUpperCase()) {
					ctx.message(`Cannot freeze current layer "${name}".`);
					continue;
				}
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.isFrozen = true;
			}
			break;
		} else if (upper === 'THAW' || upper === 'T') {
			const input = await ctx.getString('Enter layer name(s) to thaw:');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.isFrozen = false;
			}
			break;
		} else if (upper === 'LOCK' || upper === 'LO') {
			const input = await ctx.getString('Enter layer name(s) to lock:');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.isLocked = true;
			}
			break;
		} else if (upper === 'UNLOCK' || upper === 'U') {
			const input = await ctx.getString('Enter layer name(s) to unlock:');
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.isLocked = false;
			}
			break;
		} else if (upper === 'PLOT' || upper === 'P') {
			const plotOpt = await ctx.getKeyword('Enter a plot option [Plot/No plot]:', ['Plot', 'No plot'], { default: 'Plot' });
			const isPlot = plotOpt.toLowerCase().startsWith('p');
			const input = await ctx.getString(`Enter layer name(s) to ${isPlot ? 'plot' : 'not plot'}:`);
			const names = input.split(',').map(s => s.trim()).filter(Boolean);
			for (const name of names) {
				const rec = db.tables.layerTable.getAt(name);
				if (rec) rec.isPlottable = isPlot;
			}
			break;
		} else if (upper === 'RENAME' || upper === 'R') {
			const oldName = await ctx.getString('Enter old layer name:');
			const newName = await ctx.getString('Enter new layer name:');
			setLayer(db, oldName, { name: newName }, generatedLayers);
			ctx.message(`Layer "${oldName}" renamed to "${newName}".`);
			break;
		} else if (upper === 'DELETE' || upper === 'D') {
			const name = await ctx.getString('Enter layer name to delete:');
			deleteLayer(db, name, generatedLayers);
			ctx.message(`Layer "${name}" deleted.`);
			break;
		}
	}
}

/**
 * LAYCUR: changes layer of selected objects to the current layer.
 */
export async function laycurCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects to be changed to current layer:');
	const cur = ctx.database.native.clayer || '0';
	for (const e of sel) {
		e.layer = cur;
	}
	ctx.message(`${sel.length} object(s) changed to layer ${cur}.`);
}

/**
 * LAYISO: isolates the layers of selected objects (turning off other layers).
 */
export async function layisoCommand(ctx: CadCommandContext): Promise<void> {
	const sel = await ctx.getSelection('Select objects on the layer(s) to be isolated:');
	const keep = new Set<string>();
	for (const e of sel) {
		if (e.layer) keep.add(e.layer);
	}

	const db = ctx.database.native;
	const snapshot = new Map<string, LayerStateSnapshot>();
	for (const rec of db.tables.layerTable.newIterator()) {
		snapshot.set(rec.name, { on: !rec.isOff, frozen: !!rec.isFrozen, locked: !!rec.isLocked });
		if (!keep.has(rec.name)) {
			rec.isOff = true;
		}
	}
	activeLayisoSnapshot = snapshot;
	ctx.message(`${keep.size} layer(s) isolated.`);
}

/**
 * LAYUNISO: restores layer visibility and states isolated by LAYISO.
 */
export async function layunisoCommand(ctx: CadCommandContext): Promise<void> {
	if (!activeLayisoSnapshot) {
		ctx.message('No layer isolation state to restore.');
		return;
	}
	const db = ctx.database.native;
	for (const [name, state] of activeLayisoSnapshot.entries()) {
		const rec = db.tables.layerTable.getAt(name);
		if (rec) {
			rec.isOff = !state.on;
			rec.isFrozen = state.frozen;
			rec.isLocked = state.locked;
		}
	}
	activeLayisoSnapshot = undefined;
	ctx.message('Layer isolation restored.');
}

/**
 * LAYOFF: turns off the layer of the picked object.
 */
export async function layoffCommand(ctx: CadCommandContext): Promise<void> {
	const ent = await ctx.getEntity('Select an object on the layer to be turned off:');
	const db = ctx.database.native;
	const layerName = ent.layer || '0';
	const rec = db.tables.layerTable.getAt(layerName);
	if (rec) {
		if (layerName.toUpperCase() === (db.clayer || '').toUpperCase()) {
			const ans = await ctx.getKeyword('Really want to turn the current layer off? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
			if (ans.toLowerCase() !== 'yes') return;
		}
		rec.isOff = true;
		ctx.message(`Layer "${layerName}" has been turned off.`);
	}
}

/**
 * LAYFRZ: freezes the layer of the picked object.
 */
export async function layfrzCommand(ctx: CadCommandContext): Promise<void> {
	const ent = await ctx.getEntity('Select an object on the layer to be frozen:');
	const db = ctx.database.native;
	const layerName = ent.layer || '0';
	if (layerName.toUpperCase() === (db.clayer || '').toUpperCase()) {
		ctx.message('Cannot freeze the current layer.');
		return;
	}
	const rec = db.tables.layerTable.getAt(layerName);
	if (rec) {
		rec.isFrozen = true;
		ctx.message(`Layer "${layerName}" has been frozen.`);
	}
}

/**
 * LAYON: turns on all layers.
 */
export async function layonCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	let count = 0;
	for (const rec of db.tables.layerTable.newIterator()) {
		if (rec.isOff) {
			rec.isOff = false;
			count++;
		}
	}
	ctx.message(`All layers have been turned on (${count} modified).`);
}

/**
 * LAYTHW: thaws all layers.
 */
export async function laythwCommand(ctx: CadCommandContext): Promise<void> {
	const db = ctx.database.native;
	let count = 0;
	for (const rec of db.tables.layerTable.newIterator()) {
		if (rec.isFrozen) {
			rec.isFrozen = false;
			count++;
		}
	}
	ctx.message(`All layers have been thawed (${count} modified).`);
}

/**
 * LAYMCUR: makes the picked object's layer current.
 */
export async function laymcurCommand(ctx: CadCommandContext): Promise<void> {
	const ent = await ctx.getEntity('Select object whose layer will become current:');
	const layerName = ent.layer || '0';
	setCurrentLayer(ctx.database.native, layerName);
	ctx.message(`"${layerName}" is now the current layer.`);
}

/**
 * LAYMRG: merges source layer into target layer.
 */
export async function laymrgCommand(ctx: CadCommandContext): Promise<void> {
	const srcEnt = await ctx.getEntity('Select object on layer to merge:');
	const srcLayer = srcEnt.layer || '0';

	const dstEnt = await ctx.getEntity('Select object on target layer:');
	const dstLayer = dstEnt.layer || '0';

	if (srcLayer === dstLayer) {
		ctx.message('Source and target layers are identical.');
		return;
	}

	const ans = await ctx.getKeyword(`Merge layer "${srcLayer}" into "${dstLayer}"? [Yes/No] <Yes>:`, ['Yes', 'No'], { default: 'Yes' });
	if (ans.toLowerCase() !== 'yes') return;

	const generatedLayers = (globalThis as any).__saengineGeneratedLayers ?? new Set<string>();
	mergeLayers(ctx.database.native, srcLayer, dstLayer, generatedLayers);
	ctx.message(`Layer "${srcLayer}" has been merged into "${dstLayer}".`);
}

export interface MatchpropSettings {
	color: boolean;
	layer: boolean;
	linetype: boolean;
	lineweight: boolean;
	ltscale: boolean;
	textStyle: boolean;
	dimStyle: boolean;
	hatch: boolean;
}

const defaultMatchpropSettings: MatchpropSettings = {
	color: true,
	layer: true,
	linetype: true,
	lineweight: true,
	ltscale: true,
	textStyle: true,
	dimStyle: true,
	hatch: true,
};

/**
 * MATCHPROP / MA: copies properties from a source object to destination objects.
 */
export async function matchpropCommand(ctx: CadCommandContext): Promise<void> {
	const src = await ctx.getEntity('Select source object:');
	const settings = { ...defaultMatchpropSettings };

	const dests = await ctx.getSelection('Select destination object(s) or [Settings]:');
	for (const dst of dests) {
		if (settings.color && src.color) {
			dst.color = src.color.clone();
		}
		if (settings.layer && src.layer) {
			dst.layer = src.layer;
		}
		if (settings.linetype && src.lineType) {
			dst.lineType = src.lineType;
		}
		if (settings.lineweight && src.lineWeight !== undefined) {
			dst.lineWeight = src.lineWeight;
		}
		if (settings.ltscale && src.linetypeScale !== undefined) {
			dst.linetypeScale = src.linetypeScale;
		}
		if (settings.textStyle && (src as any).styleName && (dst as any).styleName !== undefined) {
			(dst as any).styleName = (src as any).styleName;
		}
		if (settings.dimStyle && (src as any).dimensionStyle && (dst as any).dimensionStyle !== undefined) {
			(dst as any).dimensionStyle = (src as any).dimensionStyle;
		}
	}
	ctx.message(`Properties matched to ${dests.length} object(s).`);
}
