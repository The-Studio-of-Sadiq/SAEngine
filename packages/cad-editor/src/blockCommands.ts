import {
	AcDbAttribute, AcDbAttributeDefinition, AcDbBlockReference, AcDbBlockTableRecord, AcDbEntity,
	AcDbGroup, AcDbText, AcGeMatrix3d, AcGePoint3d,
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
	const disposition = await ctx.getKeyword('Retain, convert to block, or delete source objects? [Retain/Convert/Delete] <Convert>:', ['Retain', 'Convert', 'Delete'], { default: 'Convert' });
	const record = new AcDbBlockTableRecord({ name, origin: point(base) });
	await ctx.transaction(async () => {
		for (const entity of selected) {
			const clone = entity.clone() as AcDbEntity;
			clone.transformBy(new AcGeMatrix3d().makeTranslation(-base.x, -base.y, -base.z));
			record.appendEntity(clone);
		}
		blockTable(ctx).add(record);
		if (disposition.toLowerCase() !== 'retain') {
			if (disposition.toLowerCase() === 'delete') for (const entity of selected) ctx.database.erase(String(entity.objectId));
			else {
				const ref = new AcDbBlockReference(name);
				ref.position = point(base);
				ctx.database.add(ref);
			}
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
		const value = def.isPreset
			? def.textString
			: await ctx.getString(`${def.prompt || def.tag} <${def.textString}>:`, { allowSpaces: true, allowEmpty: true, defaultValue: def.textString });
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
	const prompt = await ctx.getString('Enter attribute prompt:', { allowSpaces: true });
	const value = await ctx.getString('Enter default value:', { allowSpaces: true, allowEmpty: true });
	const position = await ctx.getPoint('Specify attribute insertion point:');
	const height = await ctx.getDistance('Specify text height:');
	const def = new AcDbAttributeDefinition();
	def.tag = tag.toUpperCase(); def.prompt = prompt; def.textString = value; def.position = point(position); def.height = height;
	await ctx.transaction(async () => ctx.database.add(def));
}

async function editAttributes(ctx: CadCommandContext): Promise<void> {
	const entity = await ctx.getEntity('Select block reference:');
	if (!(entity instanceof AcDbBlockReference)) throw new Error('Selected entity is not a block reference');
	const edits: Array<readonly [AcDbAttribute, string]> = [];
	for (const attr of attributes(entity)) edits.push([attr, await ctx.getString(`Enter value for ${attr.tag}:`, { allowSpaces: true, defaultValue: attr.textString })] as const);
	await ctx.transaction(async () => { for (const [attr, value] of edits) attr.textString = value; });
}
export const atteditCommand = editAttributes;

export async function wblockCommand(ctx: CadCommandContext): Promise<void> {
	const name = (await ctx.getString('Enter output block name:', { allowSpaces: false })).trim();
	const sourceName = await ctx.getString('Enter existing block name or leave blank to select objects:', { allowSpaces: false, allowEmpty: true });
	const temp = new AcDbDatabase();
	const record = new AcDbBlockTableRecord({ name, origin: new AcGePoint3d() });
	if (sourceName.trim()) {
		const source = blockTable(ctx).getAt(sourceName.trim());
		if (!source) throw new Error(`Block "${sourceName}" does not exist`);
		for (const entity of source.newIterator()) {
			const clone = entity.clone() as AcDbEntity;
			clone.transformBy(new AcGeMatrix3d().makeTranslation(-source.origin.x, -source.origin.y, -source.origin.z));
			record.appendEntity(clone);
		}
	} else {
		const base = await ctx.getPoint('Specify base point:');
		record.origin = point(base);
		for (const entity of await ctx.getSelection('Select objects:')) {
			const clone = entity.clone() as AcDbEntity;
			clone.transformBy(new AcGeMatrix3d().makeTranslation(-base.x, -base.y, -base.z));
			record.appendEntity(clone);
		}
	}
	const tempTransaction = temp.transactionManager.startTransaction();
	try { temp.tables.blockTable.add(record); tempTransaction.commit(); }
	catch (error) { tempTransaction.abort(); throw error; }
	ctx.onWblock?.(name, dxfOut(temp));
	if (!ctx.onWblock) ctx.message('WBLOCK output callback is not connected.');
}

export async function groupCommand(ctx: CadCommandContext): Promise<void> {
	const name = (await ctx.getString('Enter group name:', { allowSpaces: false })).trim();
	const selected = await ctx.getSelection('Select objects:');
	if (ctx.database.native.objects.group.has(name)) throw new Error(`Group "${name}" already exists`);
	const group = new AcDbGroup(); group.name = name; group.selectable = true;
	for (const entity of selected) group.addEntityId(entity.objectId);
	await ctx.transaction(async () => { ctx.database.native.objects.group.setAt(name, group); });
}
export async function ungroupCommand(ctx: CadCommandContext): Promise<void> {
	const name = (await ctx.getString('Enter group name:', { allowSpaces: false })).trim();
	await ctx.transaction(async () => {
		if (!ctx.database.native.objects.group.remove(name)) ctx.message(`Group "${name}" not found.`);
	});
}
export async function purgeCommand(ctx: CadCommandContext): Promise<void> {
	const table = blockTable(ctx);
	const used = new Set(ctx.database.all().filter((e): e is AcDbBlockReference => e instanceof AcDbBlockReference).map(e => e.blockName.toLowerCase()));
	let count = 0;
	await ctx.transaction(async () => { for (const record of Array.from(table.newIterator())) {
		if (record.isModelSapce || record.isPaperSapce || record.isXref || used.has(record.name.toLowerCase())) continue;
		if (table.remove(record.name)) count++;
	} });
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


