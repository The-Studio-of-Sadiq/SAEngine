import {
	AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord, AcDbEntity,
	AcDbGroup, AcDbText, AcGeMatrix3d, AcGePoint3d, acdbHostApplicationServices,
} from '@mlightcad/data-model';
import { AcDbDatabase } from '@mlightcad/data-model';
import { dxfOut } from './generated.js';
import type { CadCommandContext, CadPoint3 } from './commands.js';
import { makeAttribute, transformBlockPoint } from './blockGeometry.js';
import { registerCommand } from './commands.js';

function blockTable(ctx: CadCommandContext) { return ctx.database.native.tables.blockTable; }
function definitions(record: AcDbBlockTableRecord): AcDbAttributeDefinition[] {
	const found: AcDbAttributeDefinition[] = [];
	for (const entity of record.newIterator()) if (entity instanceof AcDbAttributeDefinition) found.push(entity);
	return found;
}
function attributes(reference: AcDbBlockReference) { return Array.from(reference.attributeIterator()); }
function point(p: CadPoint3) { return new AcGePoint3d(p); }

export async function blockCommand(ctx: CadCommandContext): Promise<void> {
	const name = (await ctx.getString('Enter block name:', { allowSpaces: false })).trim();
	if (!name || blockTable(ctx).has(name)) throw new Error('Block name is empty or already exists');
	const base = await ctx.getPoint('Specify insertion base point:');
	const selected = await ctx.getSelection('Select objects:');
	if (selected.length === 0) throw new Error('No objects selected for block');
	const disposition = await ctx.getKeyword('Retain, convert to block, or delete source objects? [Retain/Convert/Delete] <Convert>:', ['Retain', 'Convert', 'Delete'], { default: 'Convert' });
	const record = new AcDbBlockTableRecord({ name, origin: new AcGePoint3d(0, 0, 0) });
	await ctx.transaction(async () => {
		blockTable(ctx).add(record);
		for (const entity of selected) {
			const clone = entity.clone() as AcDbEntity;
			clone.transformBy(new AcGeMatrix3d().makeTranslation(-base.x, -base.y, -base.z));
			record.appendEntity(clone);
		}
		const disp = disposition.toLowerCase();
		if (disp === 'delete') {
			for (const entity of selected) ctx.database.erase(String(entity.objectId));
		} else if (disp === 'convert') {
			for (const entity of selected) ctx.database.erase(String(entity.objectId));
			const ref = new AcDbBlockReference(name);
			ref.position = point(base);
			for (const def of definitions(record)) {
				const attr = makeAttribute(def, def.textString);
				const pos = transformBlockPoint(def.position, record.origin, base, 1, 1, 0);
				attr.position = point(pos);
				ref.appendAttributes(attr);
			}
			ctx.database.add(ref);
		}
	});
}

export async function insertCommand(ctx: CadCommandContext): Promise<void> {
	const name = (await ctx.getString('Enter block name:', { allowSpaces: false })).trim();
	const record = blockTable(ctx).getAt(name);
	if (!record) throw new Error(`Block "${name}" does not exist`);
	const insertion = await ctx.getPoint('Specify insertion point:');
	const sxRaw = await ctx.getString('Specify X scale factor <1>:', { allowSpaces: false, allowEmpty: true, defaultValue: '1' });
	const sx = sxRaw.trim() ? Number(sxRaw) : 1;
	const syRaw = await ctx.getString(`Specify Y scale factor <${sx}>:`, { allowSpaces: false, allowEmpty: true, defaultValue: String(sx) });
	const sy = syRaw.trim() ? Number(syRaw) : sx;
	if (!Number.isFinite(sx) || !Number.isFinite(sy) || sx === 0 || sy === 0) throw new Error('Scale factors must be finite and nonzero');
	const angle = await ctx.getAngle('Specify rotation angle <0>:');
	const ref = new AcDbBlockReference(name);
	ref.position = point(insertion); ref.scaleFactors = new AcGePoint3d(sx, sy, 1); ref.rotation = angle;
	for (const def of definitions(record)) {
		if (def.isConst) continue;
		const promptLabel = def.prompt || def.tag;
		const promptText = def.textString ? `${promptLabel} <${def.textString}>:` : `${promptLabel}:`;
		const value = def.isPreset
			? def.textString
			: await ctx.getString(promptText, { allowSpaces: true, allowEmpty: true, defaultValue: def.textString });
		const attr = makeAttribute(def, value);
		const pos = transformBlockPoint(def.position, record.origin, insertion, sx, sy, angle);
		attr.position = point(pos);
		attr.height *= Math.abs(sy);
		attr.rotation += angle;
		ref.appendAttributes(attr);
	}
	await ctx.transaction(async () => ctx.database.add(ref));
}

export async function attdefCommand(ctx: CadCommandContext): Promise<void> {
	const tag = (await ctx.getString('Enter attribute tag:', { allowSpaces: false })).trim();
	if (!tag) throw new Error('Attribute tag cannot be empty');
	const prompt = await ctx.getString('Enter attribute prompt:', { allowSpaces: true, allowEmpty: true });
	const value = await ctx.getString('Enter default value:', { allowSpaces: true, allowEmpty: true });
	const position = await ctx.getPoint('Specify attribute insertion point:');
	const height = await ctx.getDistance('Specify text height:');
	if (height <= 0) throw new Error('Text height must be positive');
	const def = new AcDbAttributeDefinition();
	def.tag = tag.toUpperCase(); def.prompt = prompt; def.textString = value; def.position = point(position); def.height = height;
	await ctx.transaction(async () => ctx.database.add(def));
}

async function editAttributes(ctx: CadCommandContext): Promise<void> {
	const entity = await ctx.getEntity('Select block reference:');
	if (!(entity instanceof AcDbBlockReference)) throw new Error('Selected entity is not a block reference');
	const attrs = attributes(entity);
	if (attrs.length === 0) {
		ctx.message('Block reference has no editable attributes.');
		return;
	}
	const edits: Array<readonly [AcDbAttribute, string]> = [];
	for (const attr of attrs) {
		const val = await ctx.getString(`Enter value for ${attr.tag} <${attr.textString}>:`, { allowSpaces: true, allowEmpty: true, defaultValue: attr.textString });
		edits.push([attr, val] as const);
	}
	await ctx.transaction(async () => { for (const [attr, value] of edits) attr.textString = value; });
}
export const atteditCommand = editAttributes;

export async function wblockCommand(ctx: CadCommandContext): Promise<void> {
	const name = (await ctx.getString('Enter output block name:', { allowSpaces: false })).trim();
	if (!name) throw new Error('Output block name cannot be empty');
	const sourceName = (await ctx.getString('Enter existing block name or leave blank to select objects:', { allowSpaces: false, allowEmpty: true })).trim();
	const temp = new AcDbDatabase();
	const prevDb = acdbHostApplicationServices().workingDatabase;
	try {
		acdbHostApplicationServices().workingDatabase = temp;
		const record = new AcDbBlockTableRecord({ name, origin: new AcGePoint3d(0, 0, 0) });
		temp.tables.blockTable.add(record);
		const modelEntities: AcDbEntity[] = [];
		if (sourceName) {
			const source = blockTable(ctx).getAt(sourceName);
			if (!source) throw new Error(`Block "${sourceName}" does not exist`);
			for (const entity of source.newIterator()) {
				const clone = entity.clone() as AcDbEntity;
				if (source.origin.x !== 0 || source.origin.y !== 0 || source.origin.z !== 0) {
					clone.transformBy(new AcGeMatrix3d().makeTranslation(-source.origin.x, -source.origin.y, -source.origin.z));
				}
				record.appendEntity(clone);
				modelEntities.push(clone.clone() as AcDbEntity);
			}
		} else {
			const base = await ctx.getPoint('Specify base point:');
			const selected = await ctx.getSelection('Select objects:');
			if (selected.length === 0) throw new Error('No objects selected for WBLOCK');
			for (const entity of selected) {
				const clone = entity.clone() as AcDbEntity;
				clone.transformBy(new AcGeMatrix3d().makeTranslation(-base.x, -base.y, -base.z));
				record.appendEntity(clone);
				modelEntities.push(clone.clone() as AcDbEntity);
			}
		}
		if (modelEntities.length > 0) {
			temp.tables.blockTable.modelSpace.appendEntity(modelEntities);
		}
		const outputDxf = dxfOut(temp);
		ctx.onWblock?.(name, outputDxf);
		if (!ctx.onWblock) ctx.message('WBLOCK output callback is not connected.');
	} finally {
		acdbHostApplicationServices().workingDatabase = prevDb;
	}
}

export async function groupCommand(ctx: CadCommandContext): Promise<void> {
	if (typeof AcDbGroup === 'undefined' || !ctx.database.native.objects?.group) {
		ctx.message('Groups are not supported in this environment.');
		return;
	}
	const name = (await ctx.getString('Enter group name:', { allowSpaces: false })).trim();
	if (!name) throw new Error('Group name cannot be empty');
	if (ctx.database.native.objects.group.has(name)) throw new Error(`Group "${name}" already exists`);
	const selected = await ctx.getSelection('Select objects:');
	if (selected.length === 0) throw new Error('No objects selected for group');
	const group = new AcDbGroup(); group.name = name; group.selectable = true;
	for (const entity of selected) group.addEntityId(entity.objectId);
	await ctx.transaction(async () => { ctx.database.native.objects.group.setAt(name, group); });
}

export async function ungroupCommand(ctx: CadCommandContext): Promise<void> {
	if (typeof AcDbGroup === 'undefined' || !ctx.database.native.objects?.group) {
		ctx.message('Groups are not supported in this environment.');
		return;
	}
	const name = (await ctx.getString('Enter group name:', { allowSpaces: false })).trim();
	if (!name) throw new Error('Group name cannot be empty');
	await ctx.transaction(async () => {
		if (ctx.database.native.objects.group.remove(name)) {
			ctx.message(`Group "${name}" removed.`);
		} else {
			ctx.message(`Group "${name}" not found.`);
		}
	});
}

export async function purgeCommand(ctx: CadCommandContext): Promise<void> {
	const table = blockTable(ctx);
	const used = new Set<string>();
	function collectUsed(entities: Iterable<AcDbEntity>): void {
		for (const entity of entities) {
			if (entity instanceof AcDbBlockReference) {
				const bName = entity.blockName.toLowerCase();
				if (!used.has(bName)) {
					used.add(bName);
					const rec = table.getAt(entity.blockName);
					if (rec) collectUsed(rec.newIterator());
				}
			}
		}
	}
	collectUsed(ctx.database.all());
	let count = 0;
	await ctx.transaction(async () => {
		for (const record of Array.from(table.newIterator())) {
			if (record.isModelSapce || record.isPaperSapce || record.isXref || record.name.startsWith('*') || used.has(record.name.toLowerCase())) {
				continue;
			}
			if (table.remove(record.name)) count++;
		}
	});
	ctx.message(`Purged ${count} unused block definition(s).`);
}

export function registerBlockCommands(): void {
	registerCommand('BLOCK', blockCommand, { aliases: ['B'] });
	registerCommand('INSERT', insertCommand, { aliases: ['I'] });
	registerCommand('ATTDEF', attdefCommand, { aliases: ['ATT'] });
	registerCommand('ATTEDIT', atteditCommand, { aliases: ['ATE', 'EATTEDIT'] });
	registerCommand('WBLOCK', wblockCommand, { aliases: ['W'] });
	registerCommand('GROUP', groupCommand, { aliases: ['G'] });
	registerCommand('UNGROUP', ungroupCommand);
	registerCommand('PURGE', purgeCommand, { aliases: ['PU'] });
}
