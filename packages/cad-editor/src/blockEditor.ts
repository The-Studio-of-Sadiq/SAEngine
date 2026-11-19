/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord,
	AcDbDatabase, AcDbEntity, AcGeMatrix3d, AcGePoint3d, acdbHostApplicationServices,
} from '@mlightcad/data-model';
import { AcDbRenderingCache } from '@mlightcad/data-model';
import type { CadCommandContext } from './commands.js';
import { makeAttribute, transformBlockPoint, blockTransform } from './blockGeometry.js';
import { dxfOut, type DxfOutOptions } from './generated.js';

export interface BlockEditorSession {
	readonly mode: 'bedit' | 'refedit';
	readonly blockName: string;
	readonly database?: AcDbDatabase;
	readonly stashedModelEntities: AcDbEntity[];
	readonly stashedEntityIds?: Set<string>;
	readonly editEntityIds: Set<string>;
	readonly originalVisibility?: Map<string, boolean>;
	readonly nonWorkingSetIds?: Set<string>;
	readonly ref?: AcDbBlockReference;
	readonly transform?: AcGeMatrix3d;
	readonly inverseTransform?: AcGeMatrix3d;
	readonly snapshotDxf: string;
	readonly snapshotDxfExcludeGenerated?: string;
}

export type BlockEditingInfo = { mode: 'bedit' | 'refedit'; blockName: string };
export type BlockEditingListener = (session: BlockEditingInfo | undefined) => void;

let activeSession: BlockEditorSession | undefined;
const blockEditingListeners = new Set<BlockEditingListener>();

export function getActiveBlockEditorSession(): BlockEditorSession | undefined {
	return activeSession;
}

export function getActiveBlockEditingInfo(): BlockEditingInfo | undefined {
	return activeSession ? { mode: activeSession.mode, blockName: activeSession.blockName } : undefined;
}

export function onDidChangeBlockEditorSession(listener: BlockEditingListener): () => void {
	blockEditingListeners.add(listener);
	return () => {
		blockEditingListeners.delete(listener);
	};
}

export function setActiveBlockEditorSession(session: BlockEditorSession | undefined): void {
	activeSession = session;
	if (session) {
		(globalThis as any).__saengineActiveBlockEditorSession = session;
	} else {
		delete (globalThis as any).__saengineActiveBlockEditorSession;
	}
	const info = session ? { mode: session.mode, blockName: session.blockName } : undefined;
	for (const listener of blockEditingListeners) {
		try {
			listener(info);
		} catch (err) {
			console.error('Error in onDidChangeBlockEditing listener:', err);
		}
	}
}

/**
 * Returns DXF text for the active database. If a BEDIT or REFEDIT session is active,
 * returns the exact drawing snapshot captured at session start.
 */
export function toDxf(
	dbOrOptions?: AcDbDatabase | DxfOutOptions,
	maybeOptions?: DxfOutOptions,
): string {
	let db: AcDbDatabase | undefined;
	let options: DxfOutOptions | undefined;

	if (dbOrOptions instanceof AcDbDatabase) {
		db = dbOrOptions;
		options = maybeOptions;
	} else {
		options = dbOrOptions;
		const session = getActiveBlockEditorSession();
		db = session?.database;
		if (!db) {
			try {
				db = acdbHostApplicationServices().workingDatabase;
			} catch {}
		}
	}

	const session = getActiveBlockEditorSession();
	if (session && (!db || session.database === db)) {
		if (options?.excludeGenerated) {
			return session.snapshotDxfExcludeGenerated ?? session.snapshotDxf;
		}
		return session.snapshotDxf;
	}

	if (!db) {
		throw new Error('No database available for toDxf');
	}
	return dxfOut(db, options);
}

function getBlockTable(ctx: CadCommandContext) {
	return ctx.database.native.tables.blockTable;
}

function getDefinitions(record: AcDbBlockTableRecord): AcDbAttributeDefinition[] {
	const found: AcDbAttributeDefinition[] = [];
	for (const entity of record.newIterator()) {
		if (entity instanceof AcDbAttributeDefinition) {
			found.push(entity);
		}
	}
	return found;
}

/**
 * Hides an entity without altering its saved DXF state where possible:
 * 1. Prefers view-level hide (setEntitySceneVisible) so database visibility is unchanged.
 * 2. If no view is available (e.g. headless tests), records original visibility and sets entity.visibility = false.
 */
export function hideEntityInViewOrModel(
	ctx: CadCommandContext,
	entity: AcDbEntity,
	origVisibilityMap: Map<string, boolean>,
): void {
	const id = String(entity.objectId);
	origVisibilityMap.set(id, entity.visibility);

	const view = (ctx as any).view;
	let hiddenByView = false;
	if (view && typeof view.setEntitySceneVisible === 'function') {
		hiddenByView = Boolean(view.setEntitySceneVisible(entity.objectId, false));
		if ((ctx as any).doc && typeof (ctx as any).doc.addHiddenObject === 'function') {
			(ctx as any).doc.addHiddenObject(entity.objectId);
		}
	}

	if (!hiddenByView) {
		entity.visibility = false;
	}
	(entity as any).__blockEditorHidden = true;
}

/**
 * Restores an entity hidden by hideEntityInViewOrModel to its exact pre-session visibility.
 */
export function restoreEntityInViewOrModel(
	ctx: CadCommandContext,
	entity: AcDbEntity,
	origVisibilityMap: Map<string, boolean>,
): void {
	const id = String(entity.objectId);
	const orig = origVisibilityMap.get(id) ?? true;
	delete (entity as any).__blockEditorHidden;

	const view = (ctx as any).view;
	let restoredByView = false;
	if (view && typeof view.setEntitySceneVisible === 'function') {
		restoredByView = Boolean(view.setEntitySceneVisible(entity.objectId, orig));
	}

	if (!restoredByView || entity.visibility !== orig) {
		entity.visibility = orig;
	}
}

/**
 * BEDIT command: Enter a block editing session.
 *
 * Model space entities are hidden (not erased) in the view/model. Clones of the
 * block definition's entities are added at the origin with __blockEditor = true.
 */
export async function beditCommand(ctx: CadCommandContext): Promise<void> {
	if (activeSession) {
		throw new Error(`A ${activeSession.mode.toUpperCase()} session is already active for "${activeSession.blockName}". Use ${activeSession.mode === 'bedit' ? 'BCLOSE' : 'REFCLOSE'} first.`);
	}

	const table = getBlockTable(ctx);
	let targetName = '';

	if (typeof ctx.getString === 'function') {
		try {
			const input = (await ctx.getString('Enter block name or press Enter to select reference [?]:', { allowSpaces: false, allowEmpty: true })).trim();
			if (input === '?') {
				const names = Array.from(table.newIterator())
					.filter(r => !r.isModelSapce && !r.isPaperSapce && !r.isXref)
					.map(r => r.name);
				ctx.message(`Defined blocks: ${names.join(', ') || '(none)'}`);
				targetName = (await ctx.getString('Enter block name:', { allowSpaces: false, allowEmpty: false })).trim();
			} else if (input) {
				targetName = input;
			}
		} catch {
			// If cancelled or empty, try getEntity
		}
	}

	if (!targetName && typeof ctx.getEntity === 'function') {
		const ent = await ctx.getEntity('Select block reference:');
		if (ent instanceof AcDbBlockReference) {
			targetName = ent.blockName;
		} else {
			throw new Error('Selected entity is not a block reference');
		}
	}

	if (!targetName) {
		throw new Error('No block specified for BEDIT');
	}

	const record = table.getAt(targetName);
	if (!record) {
		throw new Error(`Block "${targetName}" does not exist`);
	}
	if (record.isModelSapce || record.isPaperSapce) {
		throw new Error('Cannot edit layout space as a block');
	}

	// Capture DXF snapshot before modifying model space
	const nativeDb = ctx.database.native;
	const snapshotDxf = dxfOut(nativeDb);
	const snapshotDxfExcludeGenerated = dxfOut(nativeDb, {
		excludeGenerated: true,
		generatedLayers: (globalThis as any).__saengineGeneratedLayers,
	});

	// Stash existing model space entities by hiding them WITHOUT erasing
	const stashedEntities = ctx.database.all().map(e => e);
	const stashedEntityIds = new Set(stashedEntities.map(e => String(e.objectId)));
	const originalVisibility = new Map<string, boolean>();

	for (const ent of stashedEntities) {
		hideEntityInViewOrModel(ctx, ent, originalVisibility);
	}

	// Populate model space with cloned definition entities at origin
	const editIds = new Set<string>();
	const clones: AcDbEntity[] = [];
	for (const ent of record.newIterator()) {
		const clone = ent.clone() as AcDbEntity;
		(clone as any).__blockEditor = true;
		clones.push(clone);
	}

	await ctx.transaction(async () => {
		if (clones.length > 0) {
			ctx.database.add(clones);
			for (const c of clones) {
				editIds.add(String(c.objectId));
			}
		}
	});

	const session: BlockEditorSession = {
		mode: 'bedit',
		blockName: targetName,
		database: nativeDb,
		stashedModelEntities: stashedEntities,
		stashedEntityIds,
		editEntityIds: editIds,
		originalVisibility,
		snapshotDxf,
		snapshotDxfExcludeGenerated,
	};
	setActiveBlockEditorSession(session);

	ctx.message(`Block Editor: ${targetName} — BCLOSE to save or discard`);
}

/**
 * BSAVE command: Save current Block Editor changes into the block definition without exiting.
 */
export async function bsaveCommand(ctx: CadCommandContext): Promise<void> {
	if (!activeSession || activeSession.mode !== 'bedit') {
		throw new Error('No active BEDIT session to save');
	}

	const table = getBlockTable(ctx);
	const record = table.getAt(activeSession.blockName);
	if (!record) {
		throw new Error(`Block "${activeSession.blockName}" does not exist`);
	}

	const session = activeSession;
	const workingEntities = ctx.database.all().filter(e => !session.stashedEntityIds?.has(String(e.objectId)));

	await ctx.transaction(async () => {
		// Clear existing entities from block definition
		const oldEntities = Array.from(record.newIterator()) as AcDbEntity[];
		for (const ent of oldEntities) {
			record.removeEntity(ent.objectId);
		}

		// Write working entities back into block table record
		for (const ent of workingEntities) {
			const clone = ent.clone() as AcDbEntity;
			delete (clone as any).__blockEditor;
			record.appendEntity(clone);
		}

		record.origin = new AcGePoint3d(0, 0, 0);
	});

	try { AcDbRenderingCache.instance?.clear(); } catch {}
	ctx.message(`Block "${activeSession.blockName}" saved.`);
}

/**
 * BSAVEAS command: Save current Block Editor content under a new block name.
 */
export async function bsaveasCommand(ctx: CadCommandContext): Promise<void> {
	if (!activeSession || activeSession.mode !== 'bedit') {
		throw new Error('No active BEDIT session to save');
	}

	const newName = (await ctx.getString('Enter new block name:', { allowSpaces: false })).trim();
	if (!newName) {
		throw new Error('Block name cannot be empty');
	}
	const table = getBlockTable(ctx);
	if (table.has(newName)) {
		throw new Error(`Block "${newName}" already exists`);
	}

	const session = activeSession;
	const workingEntities = ctx.database.all().filter(e => !session.stashedEntityIds?.has(String(e.objectId)));

	const newRecord = new AcDbBlockTableRecord({ name: newName, origin: new AcGePoint3d(0, 0, 0) });
	await ctx.transaction(async () => {
		table.add(newRecord);
		for (const ent of workingEntities) {
			const clone = ent.clone() as AcDbEntity;
			delete (clone as any).__blockEditor;
			newRecord.appendEntity(clone);
		}
	});

	ctx.message(`Block saved as "${newName}".`);
}

/**
 * BCLOSE command: Close Block Editor session, saving or discarding changes.
 */
export async function bcloseCommand(ctx: CadCommandContext): Promise<void> {
	if (!activeSession || activeSession.mode !== 'bedit') {
		throw new Error('No active BEDIT session to close');
	}

	const choice = (await ctx.getKeyword(
		`Save changes to ${activeSession.blockName}? [Save/Discard] <Save>:`,
		['Save', 'Discard'],
		{ default: 'Save' },
	)).toLowerCase();

	const session = activeSession;
	const table = getBlockTable(ctx);
	const record = table.getAt(session.blockName);

	// Working entities are those in editEntityIds and NOT in stashedEntityIds
	const allCurrent = ctx.database.all();
	const workingEntities = allCurrent.filter(e => !session.stashedEntityIds?.has(String(e.objectId)));

	await ctx.transaction(async () => {
		if (choice === 'save' && record) {
			// Clear definition
			const oldEntities = Array.from(record.newIterator()) as AcDbEntity[];
			for (const ent of oldEntities) {
				record.removeEntity(ent.objectId);
			}
			// Write working entities to definition
			for (const ent of workingEntities) {
				const clone = ent.clone() as AcDbEntity;
				delete (clone as any).__blockEditor;
				record.appendEntity(clone);
			}
			record.origin = new AcGePoint3d(0, 0, 0);
		}

		// Erase temporary working entities from model space
		for (const ent of workingEntities) {
			try {
				ctx.database.erase(String(ent.objectId));
			} catch {}
		}

		// Restore visibility of stashed model space entities
		for (const ent of session.stashedModelEntities) {
			restoreEntityInViewOrModel(ctx, ent, session.originalVisibility ?? new Map());
		}
	});

	try { AcDbRenderingCache.instance?.clear(); } catch {}
	setActiveBlockEditorSession(undefined);
	ctx.message(choice === 'save' ? `Block "${session.blockName}" saved and closed.` : `Block Editor closed (changes discarded).`);
}

/**
 * REFEDIT command: Edit a block reference's content in place in model space.
 */
export async function refeditCommand(ctx: CadCommandContext): Promise<void> {
	if (activeSession) {
		throw new Error(`A ${activeSession.mode.toUpperCase()} session is already active. Use ${activeSession.mode === 'bedit' ? 'BCLOSE' : 'REFCLOSE'} first.`);
	}

	const ent = await ctx.getEntity('Select block reference:');
	if (!(ent instanceof AcDbBlockReference)) {
		throw new Error('Selected entity is not a block reference');
	}

	const table = getBlockTable(ctx);
	const blockName = ent.blockName;
	const record = table.getAt(blockName);
	if (!record) {
		throw new Error(`Block "${blockName}" does not exist`);
	}

	const xform = blockTransform(ent);
	const invXform = xform.clone().invert();

	// Capture DXF snapshot before modifying model space
	const nativeDb = ctx.database.native;
	const snapshotDxf = dxfOut(nativeDb);
	const snapshotDxfExcludeGenerated = dxfOut(nativeDb, {
		excludeGenerated: true,
		generatedLayers: (globalThis as any).__saengineGeneratedLayers,
	});

	// Hide reference in the view/model instead of erasing it
	const originalVisibility = new Map<string, boolean>();
	hideEntityInViewOrModel(ctx, ent, originalVisibility);

	// Record non-working-set entity IDs (entities that were already in model space)
	const nonWorkingSetIds = new Set(ctx.database.all().map(e => String(e.objectId)));

	// Clone definition entities, transform into place, and add to model space
	const editIds = new Set<string>();
	const workingClones: AcDbEntity[] = [];
	for (const defEnt of record.newIterator()) {
		const clone = defEnt.clone() as AcDbEntity;
		clone.transformBy(xform);
		(clone as any).__refEdit = true;
		workingClones.push(clone);
	}

	await ctx.transaction(async () => {
		if (workingClones.length > 0) {
			ctx.database.add(workingClones);
			for (const c of workingClones) {
				editIds.add(String(c.objectId));
			}
		}
	});

	const session: BlockEditorSession = {
		mode: 'refedit',
		blockName,
		database: nativeDb,
		stashedModelEntities: [ent],
		stashedEntityIds: nonWorkingSetIds,
		editEntityIds: editIds,
		originalVisibility,
		nonWorkingSetIds,
		ref: ent,
		transform: xform,
		inverseTransform: invXform,
		snapshotDxf,
		snapshotDxfExcludeGenerated,
	};
	setActiveBlockEditorSession(session);

	ctx.message(`REFEDIT: ${blockName} — REFCLOSE to save or discard`);
}

/**
 * REFCLOSE command: Close REFEDIT session, mapping edits back through the inverse transform.
 */
export async function refcloseCommand(ctx: CadCommandContext): Promise<void> {
	if (!activeSession || activeSession.mode !== 'refedit') {
		throw new Error('No active REFEDIT session to close');
	}

	const choice = (await ctx.getKeyword(
		'Save or discard changes to block reference? [Save/Discard] <Save>:',
		['Save', 'Discard'],
		{ default: 'Save' },
	)).toLowerCase();

	const session = activeSession;
	const table = getBlockTable(ctx);
	const record = table.getAt(session.blockName);

	// Working set entities include cloned definition entities and any new entities added during the session
	const allCurrent = ctx.database.all();
	const workingEntities = allCurrent.filter(e => !session.nonWorkingSetIds?.has(String(e.objectId)));

	await ctx.transaction(async () => {
		if (choice === 'save' && record && session.inverseTransform) {
			// Clear definition
			const oldEntities = Array.from(record.newIterator()) as AcDbEntity[];
			for (const ent of oldEntities) {
				record.removeEntity(ent.objectId);
			}

			// Map working set entities back through inverse transform into definition
			for (const e of workingEntities) {
				const clone = e.clone() as AcDbEntity;
				clone.transformBy(session.inverseTransform);
				delete (clone as any).__refEdit;
				record.appendEntity(clone);
			}
		}

		// Erase working set entities from model space
		for (const e of workingEntities) {
			try {
				ctx.database.erase(String(e.objectId));
			} catch {}
		}

		// Restore original reference visibility (do NOT re-add)
		if (session.ref) {
			restoreEntityInViewOrModel(ctx, session.ref, session.originalVisibility ?? new Map());
		}
	});

	try { AcDbRenderingCache.instance?.clear(); } catch {}
	setActiveBlockEditorSession(undefined);
	ctx.message(choice === 'save' ? 'Block reference edits saved to definition.' : 'Block reference edits discarded.');
}

/**
 * ATTSYNC command: Update attributes of all references of a chosen block
 * to match its current attribute definitions.
 */
export async function attsyncCommand(ctx: CadCommandContext): Promise<void> {
	const table = getBlockTable(ctx);
	let targetName = '';

	if (typeof ctx.getString === 'function') {
		try {
			const input = (await ctx.getString('Enter block name for ATTSYNC or press Enter to select [?]:', { allowSpaces: false, allowEmpty: true })).trim();
			if (input === '?') {
				const names = Array.from(table.newIterator())
					.filter(r => !r.isModelSapce && !r.isPaperSapce && getDefinitions(r).length > 0)
					.map(r => r.name);
				ctx.message(`Blocks with attributes: ${names.join(', ') || '(none)'}`);
				targetName = (await ctx.getString('Enter block name:', { allowSpaces: false, allowEmpty: false })).trim();
			} else if (input) {
				targetName = input;
			}
		} catch {}
	}

	if (!targetName && typeof ctx.getEntity === 'function') {
		const ent = await ctx.getEntity('Select block reference:');
		if (ent instanceof AcDbBlockReference) {
			targetName = ent.blockName;
		}
	}

	if (!targetName) {
		throw new Error('No block specified for ATTSYNC');
	}

	const record = table.getAt(targetName);
	if (!record) {
		throw new Error(`Block "${targetName}" does not exist`);
	}

	const defs = getDefinitions(record);
	let syncedCount = 0;

	await ctx.transaction(async () => {
		for (const ent of ctx.database.all()) {
			if (ent instanceof AcDbBlockReference && ent.blockName.toUpperCase() === targetName.toUpperCase()) {
				// 1. Collect current attribute values
				const valueMap = new Map<string, string>();
				for (const attr of ent.attributeIterator()) {
					valueMap.set(attr.tag.toUpperCase(), attr.textString);
				}

				// 2. Clear orphaned and existing attributes
				try {
					(ent as any)._attribs?.clear?.();
				} catch {}

				// 3. Rebuild attributes from current definitions
				for (const def of defs) {
					const tagUpper = def.tag.toUpperCase();
					const val = valueMap.has(tagUpper) ? valueMap.get(tagUpper)! : def.textString;
					const attr = makeAttribute(def, val);
					const pos = transformBlockPoint(def.position, record.origin, ent.position, ent.scaleFactors.x, ent.scaleFactors.y, ent.rotation);
					attr.position = new AcGePoint3d(pos);
					attr.height *= Math.abs(ent.scaleFactors.y);
					attr.rotation += ent.rotation;
					ent.appendAttributes(attr);
				}
				syncedCount++;
			}
		}
	});

	try { AcDbRenderingCache.instance?.clear(); } catch {}
	ctx.message(`ATTSYNC complete. Synchronized ${syncedCount} reference(s) of block "${targetName}".`);
}
