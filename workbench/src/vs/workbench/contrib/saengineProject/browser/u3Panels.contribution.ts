/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DataPanelRow, DataPanelScalar, DataPanelValues, IDataPanelFieldOption, IEngineDataPanelDescriptor, registerEngineDataPanel } from './engineDataPanelRegistry.js';
import { openEngineDataPanel } from './engineDataPanelInput.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { openPart } from './projectParts.js';

const category = localize2('saengine.category', "SAEngine");
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

interface IJsonBag {
	readonly [key: string]: unknown;
}

function asBag(value: unknown): IJsonBag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as IJsonBag : {};
}

function asArray(value: unknown): readonly unknown[] {
	return Array.isArray(value) ? value : [];
}

function asStrings(value: unknown): string[] {
	return asArray(value).filter((v): v is string => typeof v === 'string' && !!v);
}

function str(value: unknown, fallback = ''): string {
	return typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : fallback;
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function registerPanelCommand(descriptor: IEngineDataPanelDescriptor): void {
	registerEngineDataPanel(descriptor);
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: descriptor.id,
				title: { value: descriptor.title, original: descriptor.title },
				category,
				icon: descriptor.icon,
				f1: true,
				precondition: descriptor.requiresProject === false ? undefined : projectOpen,
			});
		}

		override run(accessor: ServicesAccessor): Promise<unknown> {
			return openEngineDataPanel(accessor.get(IEditorService), descriptor.id);
		}
	});
}

function openExportsAction(id: string, label: string): IEngineDataPanelDescriptor['secondaryActions'] {
	return [{
		id,
		label,
		icon: Codicon.files,
		run: async ctx => {
			if (!ctx.project) {
				return;
			}
			const part = partById('exports');
			if (part) {
				await openPart(ctx.project, part, {
					editorService: ctx.editorService,
					fileService: ctx.fileService,
					openerService: ctx.openerService,
					commandService: ctx.commandService,
				});
			}
		},
	}];
}

function parseList(raw: string): string[] {
	return raw.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
}

//#region Documents: Scope Boxes, Callouts, Keynotes, Legend, Schedule Builder

registerPanelCommand({
	id: 'saengine.drawings.scopeBoxes',
	title: localize('u3.scopeBoxes.title', "Scope Boxes & Dependent Views"),
	part: 'exports',
	icon: Codicon.layout,
	help: localize('u3.scopeBoxes.help', "Crop floor framing plans by named scope boxes with automatic key plans and matchlines between shared edges."),
	fields: [
		{
			key: 'scopeBoxes',
			label: localize('u3.scopeBoxes.spec', "Scope boxes (Name: x0,y0,x1,y1 [; ...])"),
			type: 'text',
			defaultValue: '',
			placeholder: localize('u3.scopeBoxes.placeholder', "Leave blank to use Project Settings or auto-split West/East zones"),
		},
		{
			key: 'size',
			label: localize('u3.scopeBoxes.size', "Sheet size"),
			type: 'select',
			defaultValue: 'A1',
			options: [
				{ value: 'A1', label: 'A1' },
				{ value: 'A2', label: 'A2' },
				{ value: 'A3', label: 'A3' },
			],
		},
		{ key: 'scale', label: localize('u3.scopeBoxes.scale', "Scale (1:N)"), type: 'number', defaultValue: 100, min: 10, step: '10' },
		{ key: 'prefix', label: localize('u3.scopeBoxes.prefix', "Prefix"), type: 'text', defaultValue: 'S-' },
		{ key: 'writeFiles', label: localize('u3.scopeBoxes.write', "Write DXF sheets"), type: 'checkbox', defaultValue: true },
		{ key: 'saveToSettings', label: localize('u3.scopeBoxes.save', "Save boxes to Settings"), type: 'checkbox', defaultValue: false },
	],
	secondaryActions: openExportsAction('openExports', localize('u3.openExports', "Open Drawing Set")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('drawings/scopeBoxes', {
			projectRoot: ctx.project!.root.fsPath,
			scopeBoxes: String(values.scopeBoxes || ''),
			size: String(values.size || 'A1'),
			scale: Number(values.scale) || 100,
			prefix: String(values.prefix || 'S-'),
			writeFiles: Boolean(values.writeFiles),
			saveToSettings: Boolean(values.saveToSettings),
		}));
		const plans = asArray(raw.plans).map(asBag);
		const boxes = asArray(raw.scopeBoxes).map(asBag);
		const rows: DataPanelRow[] = plans.map(p => ({
			sheet: str(p.sheetNumber),
			title: str(p.title),
			scopeBox: str(p.scopeBox),
			level: str(p.level),
			scale: str(p.scale),
			bounds: asArray(p.bounds).map(v => typeof v === 'number' ? Math.round(v) : v).join(', '),
			matchlines: str(p.matchlines, 'None'),
			dxf: str(p.dxf, '–'),
		}));
		const outputFiles = plans
			.filter(p => typeof p.dxf === 'string' && p.dxf)
			.map(p => ({ label: localize('u3.scopeBoxes.openDxf', "Open {0}.dxf", str(p.sheetNumber)), path: str(p.dxf) }));
		const problems = asStrings(raw.problems);
		const emptyState = !rows.length && problems.length ? {
			title: localize('u3.scopeBoxes.emptyTitle', "Build the Building Model first"),
			text: localize('u3.scopeBoxes.emptyText', "Generate or save 06 BIM and 04 Objects before cropping dependent sheet views."),
			action: {
				id: 'openBim',
				label: localize('u3.openBim', "Open BIM Model"),
				icon: Codicon.symbolStructure,
				run: () => void ctx.commandService.executeCommand('saengine.ribbon.openSection.bim.summary'),
			},
		} : undefined;
		return {
			metrics: [
				{ label: localize('u3.scopeBoxes.count', "Scope Boxes"), value: String(boxes.length), tone: boxes.length ? 'ok' : 'neutral' },
				{ label: localize('u3.scopeBoxes.sheets', "Dependent Sheets"), value: String(rows.length), tone: rows.length ? 'ok' : 'warn' },
				{ label: localize('u3.scopeBoxes.mode', "Source"), value: raw.autoProposed ? localize('u3.scopeBoxes.auto', "Auto Split") : localize('u3.scopeBoxes.custom', "Defined") },
			],
			tables: [{
				id: 'plans',
				title: localize('u3.scopeBoxes.tableTitle', "Dependent Plans & Matchlines"),
				columns: [
					{ key: 'sheet', title: localize('u3.col.sheet', "Sheet") },
					{ key: 'title', title: localize('u3.col.title', "Title") },
					{ key: 'scopeBox', title: localize('u3.col.scopeBox', "Scope Box") },
					{ key: 'level', title: localize('u3.col.level', "Level") },
					{ key: 'scale', title: localize('u3.col.scale', "Scale") },
					{ key: 'matchlines', title: localize('u3.col.matchlines', "Matchlines") },
					{ key: 'bounds', title: localize('u3.col.bounds', "Bounds [mm]") },
					{ key: 'dxf', title: localize('u3.col.dxf', "DXF File") },
				],
				rows,
			}],
			outputFiles,
			notes: asStrings(raw.notes),
			problems,
			emptyState,
		};
	},
});

registerPanelCommand({
	id: 'saengine.drawings.callouts',
	title: localize('u3.callouts.title', "Sheet Callouts"),
	part: 'exports',
	icon: Codicon.search,
	help: localize('u3.callouts.help', "Create a plan callout bubble on a parent framing plan linked to a zoomed detail sheet."),
	autoRun: false,
	runLabel: localize('u3.callouts.run', "Create Callout Sheet"),
	fields: [
		{ key: 'level', label: localize('u3.callouts.level', "Level"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u3.defaultFirst', "First Level") }] },
		{ key: 'calloutNumber', label: localize('u3.callouts.num', "Callout #"), type: 'text', defaultValue: '1' },
		{ key: 'detailSheetNumber', label: localize('u3.callouts.target', "Detail Sheet #"), type: 'text', defaultValue: 'S-501' },
		{ key: 'planScale', label: localize('u3.callouts.planScale', "Plan Scale (1:N)"), type: 'number', defaultValue: 100, min: 10, step: '10' },
		{ key: 'detailScale', label: localize('u3.callouts.detailScale', "Detail Scale (1:N)"), type: 'number', defaultValue: 25, min: 5, step: '5' },
		{ key: 'x0', label: localize('u3.callouts.x0', "Crop Min X [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'y0', label: localize('u3.callouts.y0', "Crop Min Y [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'x1', label: localize('u3.callouts.x1', "Crop Max X [mm]"), type: 'number', defaultValue: 6000 },
		{ key: 'y1', label: localize('u3.callouts.y1', "Crop Max Y [mm]"), type: 'number', defaultValue: 6000 },
		{ key: 'writeFiles', label: localize('u3.callouts.write', "Write DXF sheets"), type: 'checkbox', defaultValue: true },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const preview = asBag(await ctx.engineRequest('drawings/callout', { projectRoot: ctx.project.root.fsPath, writeFiles: false }));
		const levels = asArray(preview.levels).map(asBag);
		const bounds = asArray(preview.buildingBounds).map(v => typeof v === 'number' ? Math.round(v) : 0);
		if (!levels.length) {
			return undefined;
		}
		const x0 = bounds.length >= 4 ? Math.round(bounds[0] + (bounds[2] - bounds[0]) * 0.25) : 0;
		const y0 = bounds.length >= 4 ? Math.round(bounds[1] + (bounds[3] - bounds[1]) * 0.25) : 0;
		const x1 = bounds.length >= 4 ? Math.round(bounds[0] + (bounds[2] - bounds[0]) * 0.75) : 6000;
		const y1 = bounds.length >= 4 ? Math.round(bounds[1] + (bounds[3] - bounds[1]) * 0.75) : 6000;
		return {
			options: { level: levels.map(l => ({ value: str(l.id), label: `${str(l.name)} (${str(l.id)})` })) },
			values: { level: str(levels[0].id), x0, y0, x1, y1 },
		};
	},
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('drawings/callout', {
			projectRoot: ctx.project!.root.fsPath,
			level: String(values.level || '') || undefined,
			calloutNumber: String(values.calloutNumber || '1'),
			detailSheetNumber: String(values.detailSheetNumber || 'S-501'),
			planScale: Number(values.planScale) || 100,
			detailScale: Number(values.detailScale) || 25,
			x0: Number(values.x0),
			y0: Number(values.y0),
			x1: Number(values.x1),
			y1: Number(values.y1),
			writeFiles: Boolean(values.writeFiles),
		}));
		const co = asBag(raw.callout);
		const rows: DataPanelRow[] = co.reference ? [{
			reference: str(co.reference),
			level: str(co.level),
			detailSheet: str(co.detailSheet),
			planScale: `1:${str(co.planScale)}`,
			detailScale: `1:${str(co.detailScale)}`,
			bounds: asArray(co.bounds).join(', '),
			detailDxf: str(co.detailDxf, '–'),
		}] : [];
		const outputFiles = [];
		if (typeof co.parentDxf === 'string' && co.parentDxf) {
			outputFiles.push({ label: localize('u3.callouts.openParent', "Open Parent Plan DXF"), path: co.parentDxf });
		}
		if (typeof co.detailDxf === 'string' && co.detailDxf) {
			outputFiles.push({ label: localize('u3.callouts.openDetail', "Open Callout Detail DXF"), path: co.detailDxf });
		}
		return {
			metrics: [
				{ label: localize('u3.callouts.ref', "Callout Reference"), value: str(co.reference, '–'), tone: co.reference ? 'ok' : 'warn' },
				{ label: localize('u3.callouts.detailScaleMetric', "Detail Scale"), value: co.detailScale ? `1:${str(co.detailScale)}` : '–' },
			],
			tables: [{
				id: 'callouts',
				title: localize('u3.callouts.table', "Callout Reference"),
				columns: [
					{ key: 'reference', title: localize('u3.col.reference', "Reference") },
					{ key: 'level', title: localize('u3.col.level', "Level") },
					{ key: 'detailSheet', title: localize('u3.col.detailSheet', "Target Sheet") },
					{ key: 'planScale', title: localize('u3.col.planScale', "Plan Scale") },
					{ key: 'detailScale', title: localize('u3.col.detailScale', "Detail Scale") },
					{ key: 'bounds', title: localize('u3.col.bounds', "Bounds [mm]") },
					{ key: 'detailDxf', title: localize('u3.col.detailDxf', "Detail DXF") },
				],
				rows,
			}],
			outputFiles,
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerPanelCommand({
	id: 'saengine.drawings.keynotes',
	title: localize('u3.keynotes.title', "Keynotes & Used-Key Legend"),
	part: 'exports',
	icon: Codicon.tag,
	help: localize('u3.keynotes.help', "Lists keynotes from the active catalogue and shows every keynote key actually tagged on generated DXF sheets."),
	fields: [
		{ key: 'sheet', label: localize('u3.keynotes.sheetFilter', "Filter sheet name"), type: 'text', defaultValue: '', placeholder: localize('u3.optionalAllSheets', "All sheets in 11 Exports/Drawings") },
	],
	secondaryActions: openExportsAction('openExports', localize('u3.openExports', "Open Drawing Set")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('drawings/keynotes', {
			projectRoot: ctx.project!.root.fsPath,
			sheet: String(values.sheet || '') || undefined,
		}));
		const usedRows: DataPanelRow[] = asArray(raw.used).map(asBag).map(r => ({
			key: str(r.key),
			description: str(r.description),
			sheet: str(r.sheet),
			status: r.known ? 'Pass' : 'Missing',
		}));
		const catRows: DataPanelRow[] = asArray(raw.catalogue).map(asBag).map(r => ({
			key: str(r.key),
			description: str(r.description),
			usedOnSheets: r.used ? 'Yes' : 'No',
		}));
		return {
			metrics: [
				{ label: localize('u3.keynotes.catalogueCount', "Catalogue Keys"), value: String(raw.totalCatalogue ?? catRows.length) },
				{ label: localize('u3.keynotes.usedCount', "Used on Sheets"), value: String(raw.totalUsed ?? usedRows.length), tone: usedRows.length ? 'ok' : 'neutral' },
				{ label: localize('u3.keynotes.sheetsScanned', "DXFs Scanned"), value: String(raw.sheetsScanned ?? 0) },
			],
			tables: [
				{
					id: 'catalogue',
					title: localize('u3.keynotes.catTab', "Keynote Catalogue"),
					columns: [
						{ key: 'key', title: localize('u3.col.key', "Key") },
						{ key: 'description', title: localize('u3.col.description', "Description") },
						{ key: 'usedOnSheets', title: localize('u3.col.used', "Used on Sheets") },
					],
					rows: catRows,
				},
				{
					id: 'used',
					title: localize('u3.keynotes.usedTab', "Used on Sheets"),
					columns: [
						{ key: 'key', title: localize('u3.col.key', "Key") },
						{ key: 'description', title: localize('u3.col.description', "Description") },
						{ key: 'sheet', title: localize('u3.col.sheet', "Sheet") },
						{ key: 'status', title: localize('u3.col.status', "Status"), type: 'status' },
					],
					rows: usedRows,
					emptyMessage: localize('u3.keynotes.noneUsed', "No keynote tags found across scanned DXF sheets (see Catalogue tab for available keys)."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerPanelCommand({
	id: 'saengine.drawings.legend',
	title: localize('u3.legend.title', "Drawing Legend"),
	part: 'exports',
	icon: Codicon.listFlat,
	help: localize('u3.legend.help', "Inspects generated DXF sheets and builds a per-set legend of linetypes, hatch patterns, symbols and annotation tags."),
	fields: [
		{ key: 'sheet', label: localize('u3.legend.sheetFilter', "Filter sheet name"), type: 'text', defaultValue: '', placeholder: localize('u3.optionalAllSheets', "All sheets in 11 Exports/Drawings") },
	],
	secondaryActions: openExportsAction('openExports', localize('u3.legend.generateDrawings', "Generate Drawings")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('drawings/legend', {
			projectRoot: ctx.project!.root.fsPath,
			sheet: String(values.sheet || '') || undefined,
		}));
		const items: DataPanelRow[] = asArray(raw.items).map(asBag).map(r => ({
			kind: str(r.kind),
			name: str(r.name),
			sheetCount: num(r.sheetCount) ?? 0,
			sheets: str(r.sheets),
		}));
		const scanned = num(raw.sheetsScanned) ?? 0;
		const emptyState = !items.length && !scanned ? {
			title: localize('u3.legend.emptyTitle', "Generate the Drawing Set first"),
			text: localize('u3.legend.emptyText', "No DXF sheets exist in 11 Exports/Drawings yet; generate drawings to populate the sheet legend."),
			action: {
				id: 'openExports',
				label: localize('u3.openExports', "Open Drawing Set"),
				icon: Codicon.files,
				run: () => void ctx.commandService.executeCommand('saengine.project.showExports'),
			},
		} : undefined;
		return {
			metrics: [
				{ label: localize('u3.legend.scanned', "Sheets Scanned"), value: String(scanned), tone: scanned ? 'ok' : 'warn' },
				{ label: localize('u3.legend.entries', "Legend Symbols"), value: String(items.length) },
			],
			tables: [{
				id: 'legend',
				title: localize('u3.legend.table', "Legend Items"),
				columns: [
					{ key: 'kind', title: localize('u3.col.type', "Type") },
					{ key: 'name', title: localize('u3.col.name', "Name") },
					{ key: 'sheetCount', title: localize('u3.col.sheetCount', "Sheets"), type: 'number', align: 'right' },
					{ key: 'sheets', title: localize('u3.col.usedOn', "Used On") },
				],
				rows: items,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
			emptyState,
		};
	},
});

function buildScheduleDefinition(values: DataPanelValues): { [key: string]: unknown } {
	const category = String(values.category || 'beams');
	const fieldKeys = parseList(String(values.fields || 'id, story, type, widthMm, depthMm, lengthMm'));
	const fields: { key: string; title: string; expression?: string }[] = fieldKeys.map(k => ({ key: k, title: k }));
	const calcRaw = String(values.calculated || '').trim();
	if (calcRaw) {
		for (const exprPart of parseList(calcRaw)) {
			const eqIdx = exprPart.indexOf('=');
			if (eqIdx > 0) {
				const k = exprPart.slice(0, eqIdx).trim();
				const expr = exprPart.slice(eqIdx + 1).trim();
				if (k && expr) {
					fields.push({ key: k, title: k, expression: expr });
				}
			}
		}
	}
	const filters: { field: string; operator: string; value: string | number }[] = [];
	const filterField = String(values.filterField || '').trim();
	const filterValue = String(values.filterValue || '').trim();
	if (filterField && filterValue) {
		const n = Number(filterValue);
		filters.push({
			field: filterField,
			operator: String(values.filterOp || 'contains'),
			value: Number.isFinite(n) && filterValue !== '' ? n : filterValue,
		});
	}
	const sortField = String(values.sortField || '').trim();
	const groupBy = parseList(String(values.groupBy || ''));
	const totals = parseList(String(values.totals || ''));
	return {
		name: String(values.name || `${category} Schedule`),
		category,
		fields,
		filters,
		sort: sortField ? [{ field: sortField, order: String(values.sortOrder || 'asc') }] : [],
		groupBy,
		totals,
		itemize: values.itemize !== false,
	};
}

registerPanelCommand({
	id: 'saengine.drawings.scheduleBuilder',
	title: localize('u3.sched.title', "Schedule Builder"),
	part: 'exports',
	icon: Codicon.table,
	help: localize('u3.sched.help', "Query model elements by category with custom fields, arithmetic expressions (key=expr), filters, grouping, sorting and totals."),
	fields: [
		{ key: 'name', label: localize('u3.sched.name', "Title"), type: 'text', defaultValue: localize('u3.sched.defaultName', "Element Schedule") },
		{
			key: 'category',
			label: localize('u3.sched.category', "Category"),
			type: 'select',
			defaultValue: 'beams',
			options: [
				{ value: 'beams', label: localize('u3.sched.beams', "Structural Beams") },
				{ value: 'columns', label: localize('u3.sched.columns', "Structural Columns") },
				{ value: 'slabs', label: localize('u3.sched.slabs', "Floor & Roof Slabs") },
				{ value: 'walls', label: localize('u3.sched.walls', "Structural Walls") },
				{ value: 'footings', label: localize('u3.sched.footings', "Foundations / Footings") },
				{ value: 'rooms', label: localize('u3.sched.rooms', "Architectural Rooms") },
				{ value: 'doors', label: localize('u3.sched.doors', "Doors") },
				{ value: 'windows', label: localize('u3.sched.windows', "Windows") },
				{ value: 'mepEquipment', label: localize('u3.sched.mepEq', "MEP Equipment") },
			],
		},
		{ key: 'fields', label: localize('u3.sched.fields', "Fields (comma-separated)"), type: 'text', defaultValue: 'id, story, type, widthMm, depthMm, lengthMm' },
		{ key: 'calculated', label: localize('u3.sched.calc', "Calculated (key=expr)"), type: 'text', defaultValue: '', placeholder: 'e.g. areaM2=widthMm*lengthMm/1000000' },
		{ key: 'filterField', label: localize('u3.sched.filterField', "Filter field"), type: 'text', defaultValue: '', placeholder: localize('u3.optional', "Optional") },
		{
			key: 'filterOp',
			label: localize('u3.sched.filterOp', "Filter op"),
			type: 'select',
			defaultValue: 'contains',
			options: [
				{ value: 'contains', label: 'contains' },
				{ value: '==', label: '==' },
				{ value: '!=', label: '!=' },
				{ value: '>', label: '>' },
				{ value: '>=', label: '>=' },
				{ value: '<', label: '<' },
				{ value: '<=', label: '<=' },
			],
		},
		{ key: 'filterValue', label: localize('u3.sched.filterVal', "Filter value"), type: 'text', defaultValue: '' },
		{ key: 'groupBy', label: localize('u3.sched.group', "Group by"), type: 'text', defaultValue: '', placeholder: 'e.g. story' },
		{ key: 'sortField', label: localize('u3.sched.sort', "Sort by"), type: 'text', defaultValue: 'id' },
		{ key: 'sortOrder', label: localize('u3.sched.order', "Order"), type: 'select', defaultValue: 'asc', options: [{ value: 'asc', label: 'Ascending' }, { value: 'desc', label: 'Descending' }] },
		{ key: 'totals', label: localize('u3.sched.totals', "Totals fields"), type: 'text', defaultValue: 'count', placeholder: 'e.g. count, lengthMm' },
		{ key: 'itemize', label: localize('u3.sched.itemize', "Itemize every instance"), type: 'checkbox', defaultValue: true },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const cats = asBag(await ctx.engineRequest('drawings/scheduleCategories', { projectRoot: ctx.project.root.fsPath }));
		const list = asArray(cats.categories).map(asBag);
		if (!list.length) {
			return undefined;
		}
		const options: IDataPanelFieldOption[] = list.map(c => ({
			value: str(c.id),
			label: `${str(c.label)} (${str(c.count)})`,
		}));
		const firstNonEmpty = list.find(c => (num(c.count) ?? 0) > 0) ?? list[0];
		const fields = asArray(firstNonEmpty.fields).map(f => str(asBag(f).key)).filter(Boolean);
		return {
			options: { category: options },
			values: {
				category: str(firstNonEmpty.id, 'beams'),
				...(fields.length ? { fields: fields.join(', '), sortField: fields[0] } : {}),
			},
		};
	},
	run: async (ctx, values) => {
		const definition = buildScheduleDefinition(values);
		const raw = asBag(await ctx.engineRequest('drawings/schedule', {
			projectRoot: ctx.project!.root.fsPath,
			definition,
		}));
		const cols = asStrings(raw.columns);
		const rawRows = asArray(raw.rows).map(asArray);
		const tableRows: DataPanelRow[] = rawRows.map(cells => {
			const record: { [key: string]: DataPanelScalar } = {};
			cols.forEach((col, i) => {
				const cell = cells[i];
				record[`c${i}`] = typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean' ? cell : '';
			});
			return record;
		});
		const problems = asStrings(raw.problems);
		const emptyState = !tableRows.length && !problems.length ? {
			title: localize('u3.sched.emptyTitle', "No matching elements in {0}", String(values.category)),
			text: localize('u3.sched.emptyText', "Choose another category with elements or model elements in the Floor Plan / Architecture first."),
		} : undefined;
		return {
			metrics: [
				{ label: localize('u3.sched.categoryMetric', "Category"), value: String(values.category) },
				{ label: localize('u3.sched.rowsMetric', "Rows"), value: String(raw.rowCount ?? tableRows.length), tone: tableRows.length ? 'ok' : 'warn' },
				{ label: localize('u3.sched.colsMetric', "Columns"), value: String(cols.length) },
			],
			tables: [{
				id: 'schedule',
				title: str(raw.title, localize('u3.sched.fallbackTitle', "Schedule")),
				columns: cols.map((c, i) => ({ key: `c${i}`, title: c })),
				rows: tableRows,
			}],
			notes: asStrings(raw.notes),
			problems,
			emptyState,
		};
	},
	secondaryActions: [{
		id: 'exportXlsx',
		label: localize('u3.sched.exportXlsx', "Export Excel (.xlsx)..."),
		icon: Codicon.table,
		run: async (ctx, values) => {
			if (!ctx.project) {
				return;
			}
			const safe = String(values.category || 'schedule').replace(/[^a-zA-Z0-9_-]/g, '-');
			const target = await ctx.fileDialogService.showSaveDialog({
				title: localize('u3.sched.saveXlsx', "Save Schedule as Excel"),
				defaultUri: URI.joinPath(ctx.project.root, '11 Exports', `${safe}-schedule.xlsx`),
				filters: [{ name: localize('u3.sched.xlsxFilter', "Excel Workbook"), extensions: ['xlsx'] }],
			});
			if (!target) {
				return;
			}
			const res = asBag(await ctx.engineRequest('drawings/schedule', {
				projectRoot: ctx.project.root.fsPath,
				definition: buildScheduleDefinition(values),
				exportXlsxPath: target.fsPath,
			}));
			if (res.xlsxPath) {
				ctx.notificationService.info(localize('u3.sched.xlsxSaved', "Exported schedule workbook to {0}.", str(res.xlsxPath)));
			} else if (asStrings(res.problems).length) {
				ctx.notificationService.error(asStrings(res.problems).join('; '));
			}
		},
	}],
});

//#endregion

//#region Output: Export IFC options, Compare IFC Revisions, ETABS Options

registerPanelCommand({
	id: 'saengine.bim.exportIfcOptions',
	title: localize('u3.ifcOpt.title', "Export IFC Options"),
	part: 'exports',
	icon: Codicon.layers,
	help: localize('u3.ifcOpt.help', "Configure IFC schema (IFC4 / IFC2X3), structural analysis view (IfcStructuralAnalysisModel), georeferencing and CRS before writing the IFC file."),
	autoRun: false,
	runLabel: localize('u3.ifcOpt.run', "Export IFC"),
	fields: [
		{
			key: 'schema',
			label: localize('u3.ifcOpt.schema', "IFC Schema"),
			type: 'select',
			defaultValue: 'IFC4',
			options: [
				{ value: 'IFC4', label: 'IFC4 Reference / Design Transfer' },
				{ value: 'IFC2X3', label: 'IFC2X3 Coordination View 2.0' },
			],
		},
		{ key: 'includeStructuralAnalysis', label: localize('u3.ifcOpt.analysis', "Include IfcStructuralAnalysisModel"), type: 'checkbox', defaultValue: false },
		{ key: 'includeGeoreferencing', label: localize('u3.ifcOpt.geo', "Include georeferencing (IfcMapConversion)"), type: 'checkbox', defaultValue: true },
		{ key: 'crs', label: localize('u3.ifcOpt.crs', "Coordinate Reference System (CRS)"), type: 'text', defaultValue: 'BTM', placeholder: 'BTM, UTM, or EPSG:<code>' },
		{ key: 'includeConnections', label: localize('u3.ifcOpt.conn', "Include steel connection plates & bolts"), type: 'checkbox', defaultValue: true },
		{ key: 'outPath', label: localize('u3.ifcOpt.outPath', "Output .ifc file (blank = 11 Exports/IFC)"), type: 'file', defaultValue: '', saveMode: true, filters: [{ name: 'IFC', extensions: ['ifc'] }] },
	],
	secondaryActions: [{
		id: 'openBim',
		label: localize('u3.ifcOpt.openBim', "Open 3D BIM"),
		icon: Codicon.symbolNamespace,
		run: async ctx => {
			if (!ctx.project) {
				return;
			}
			const bimPart = partById('bim');
			if (bimPart) {
				await openPart(ctx.project, bimPart, {
					editorService: ctx.editorService,
					fileService: ctx.fileService,
					openerService: ctx.openerService,
					commandService: ctx.commandService,
				});
			}
		},
	}],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('bim/exportIfcFile', {
			projectRoot: ctx.project!.root.fsPath,
			schema: String(values.schema || 'IFC4'),
			includeStructuralAnalysis: Boolean(values.includeStructuralAnalysis),
			includeGeoreferencing: Boolean(values.includeGeoreferencing),
			crs: String(values.crs || '') || undefined,
			includeConnections: Boolean(values.includeConnections),
			outPath: String(values.outPath || '') || undefined,
		}));
		const skipped = asStrings(raw.skipped);
		const problems = asStrings(raw.problems);
		const rows: DataPanelRow[] = raw.path ? [
			{ property: localize('u3.ifcOpt.file', "Written File"), value: str(raw.path), status: 'Pass' },
			{ property: localize('u3.ifcOpt.schema', "IFC Schema"), value: str(raw.schema), status: 'OK' },
			{ property: localize('u3.ifcOpt.elements', "IFC Entities"), value: num(raw.elementCount) ?? 0, status: 'OK' },
			{ property: localize('u3.ifcOpt.analysisRow', "Structural Analysis View"), value: raw.structuralAnalysis ? 'Yes' : 'No' },
			{ property: localize('u3.ifcOpt.geoRow', "Georeferencing / CRS"), value: raw.includeGeoreferencing ? str(raw.crs, 'BTM') : 'Disabled' },
			...skipped.map(s => ({ property: localize('u3.ifcOpt.skipped', "Skipped"), value: s, status: 'Warning' })),
		] : [];
		return {
			metrics: [
				{ label: localize('u3.ifcOpt.schemaMetric', "Schema"), value: str(raw.schema, String(values.schema)) },
				{ label: localize('u3.ifcOpt.entitiesMetric', "Entities"), value: String(raw.elementCount ?? 0), tone: raw.path ? 'ok' : 'fail' },
				{ label: localize('u3.ifcOpt.skippedMetric', "Skipped"), value: String(skipped.length), tone: skipped.length ? 'warn' : 'ok' },
			],
			tables: [{
				id: 'ifc',
				title: localize('u3.ifcOpt.summary', "IFC Export Summary"),
				columns: [
					{ key: 'property', title: localize('u3.col.setting', "Setting") },
					{ key: 'value', title: localize('u3.col.value', "Result") },
					{ key: 'status', title: localize('u3.col.status', "Status"), type: 'status' },
				],
				rows,
			}],
			outputFiles: typeof raw.path === 'string' && raw.path ? [{ label: localize('u3.ifcOpt.openFile', "Open IFC File"), path: raw.path }] : [],
			notes: asStrings(raw.notes),
			problems,
		};
	},
});

registerPanelCommand({
	id: 'saengine.bim.compareIfc',
	title: localize('u3.ifcDiff.title', "Compare IFC Revisions"),
	part: 'exports',
	icon: Codicon.diff,
	help: localize('u3.ifcDiff.help', "Semantic and geometric comparison of two IFC files by GlobalId (added, removed and modified type, placement, geometry, material or property sets)."),
	autoRun: false,
	runLabel: localize('u3.ifcDiff.run', "Compare Revisions"),
	fields: [
		{ key: 'beforePath', label: localize('u3.ifcDiff.before', "Before (.ifc)"), type: 'file', defaultValue: '', filters: [{ name: 'IFC', extensions: ['ifc'] }] },
		{ key: 'afterPath', label: localize('u3.ifcDiff.after', "After (.ifc)"), type: 'file', defaultValue: '', filters: [{ name: 'IFC', extensions: ['ifc'] }] },
	],
	run: async (ctx, values) => {
		const beforePath = String(values.beforePath || '').trim();
		const afterPath = String(values.afterPath || '').trim();
		if (!beforePath || !afterPath) {
			return {
				tables: [],
				problems: [localize('u3.ifcDiff.pickBoth', "Select both a Before .ifc revision and an After .ifc revision to compare.")],
			};
		}
		const raw = asBag(await ctx.engineRequest('bim/diffIfc', { beforePath, afterPath }));
		const counts = asBag(raw.counts);
		const changes = asArray(raw.changes).map(asBag);
		const rows: DataPanelRow[] = changes.map(c => ({
			change: str(c.kind),
			id: str(c.id),
			what: str(c.what),
			before: formatUnknown(c.before),
			after: formatUnknown(c.after),
			detail: str(c.path),
		}));
		return {
			metrics: [
				{ label: localize('u3.ifcDiff.added', "Added"), value: String(counts.added ?? asArray(raw.added).length), tone: 'ok' },
				{ label: localize('u3.ifcDiff.removed', "Removed"), value: String(counts.removed ?? counts.deleted ?? asArray(raw.removed).length), tone: 'fail' },
				{ label: localize('u3.ifcDiff.changed', "Changed"), value: String(counts.changed ?? asArray(raw.changed).length), tone: 'warn' },
				{ label: localize('u3.ifcDiff.unchanged', "Unchanged"), value: String(counts.unchanged ?? 0) },
			],
			tables: [{
				id: 'changes',
				title: localize('u3.ifcDiff.changesTab', "Element Differences"),
				columns: [
					{ key: 'change', title: localize('u3.col.change', "Change"), type: 'status' },
					{ key: 'id', title: localize('u3.col.globalId', "GlobalId / Element") },
					{ key: 'what', title: localize('u3.col.what', "Summary") },
					{ key: 'before', title: localize('u3.col.before', "Before") },
					{ key: 'after', title: localize('u3.col.after', "After") },
				],
				rows,
				emptyMessage: localize('u3.ifcDiff.identical', "No semantic or geometric differences found between these two IFC files."),
			}],
			problems: asStrings(raw.problems),
		};
	},
});

function formatUnknown(val: unknown): string {
	if (val === null || val === undefined) {
		return '–';
	}
	if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
		return String(val);
	}
	return JSON.stringify(val);
}

registerPanelCommand({
	id: 'saengine.export.e2kOptions',
	title: localize('u3.e2k.title', "ETABS Export Options (.e2k)"),
	part: 'exports',
	icon: Codicon.export,
	help: localize('u3.e2k.help', "Export the structural BIM model as an ETABS text model (.e2k) with unit system (kN-m or N-mm) and lateral load representation options."),
	autoRun: false,
	runLabel: localize('u3.e2k.run', "Export ETABS .e2k"),
	fields: [
		{
			key: 'units',
			label: localize('u3.e2k.units', "Units"),
			type: 'select',
			defaultValue: 'kN-m',
			options: [
				{ value: 'kN-m', label: 'kN, m, °C' },
				{ value: 'N-mm', label: 'N, mm, °C' },
			],
		},
		{
			key: 'lateral',
			label: localize('u3.e2k.lateral', "Lateral Loads"),
			type: 'select',
			defaultValue: 'loads',
			options: [
				{ value: 'loads', label: localize('u3.e2k.latLoads', "Derived story forces (WX, WY, EX, EY)") },
				{ value: 'coefficient', label: localize('u3.e2k.latCoeff', "ETABS BNBC seismic user coefficient") },
			],
		},
		{ key: 'outPath', label: localize('u3.e2k.outPath', "Output .e2k file (blank = 11 Exports/ETABS)"), type: 'file', defaultValue: '', saveMode: true, filters: [{ name: 'ETABS', extensions: ['e2k'] }] },
	],
	secondaryActions: openExportsAction('openExports', localize('u3.e2k.openAllExports', "Open All Exports")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.commandService.executeCommand('saengine.export.e2k', {
			projectRoot: ctx.project!.root.fsPath,
			units: String(values.units || 'kN-m') as 'kN-m' | 'N-mm',
			lateral: String(values.lateral || 'loads') as 'loads' | 'coefficient',
			outPath: String(values.outPath || '') || undefined,
		}));
		if (typeof raw.error === 'string' && raw.error) {
			return { tables: [], problems: [raw.error] };
		}
		const report = asBag(raw.report);
		const exported = asBag(report.exported);
		const warnings = asStrings(report.warnings);
		const skipped = asArray(report.skipped).map(s => formatUnknown(s));
		const rows: DataPanelRow[] = [
			...Object.entries(exported).map(([k, v]) => ({ item: k, countOrNote: str(v), kind: 'Exported' })),
			...warnings.map(w => ({ item: localize('u3.e2k.warn', "Warning"), countOrNote: w, kind: 'Warning' })),
			...skipped.map(s => ({ item: localize('u3.e2k.skipped', "Skipped"), countOrNote: s, kind: 'Warn' })),
		];
		const outputFiles = [];
		if (typeof raw.path === 'string' && raw.path) {
			outputFiles.push({ label: localize('u3.e2k.openE2k', "Open .e2k File"), path: raw.path });
		}
		if (typeof raw.readablePath === 'string' && raw.readablePath) {
			outputFiles.push({ label: localize('u3.e2k.openReport', "Open Export Report (.md)"), path: raw.readablePath });
		}
		return {
			metrics: [
				{ label: localize('u3.e2k.unitsMetric', "Units"), value: String(values.units) },
				{ label: localize('u3.e2k.warningsMetric', "Warnings"), value: String(warnings.length), tone: warnings.length ? 'warn' : 'ok' },
				{ label: localize('u3.e2k.skippedMetric', "Skipped"), value: String(skipped.length), tone: skipped.length ? 'warn' : 'ok' },
			],
			tables: [{
				id: 'e2k',
				title: localize('u3.e2k.reportTab', "ETABS Export Summary"),
				columns: [
					{ key: 'item', title: localize('u3.col.item', "Category / Item") },
					{ key: 'countOrNote', title: localize('u3.col.details', "Count / Note") },
					{ key: 'kind', title: localize('u3.col.status', "Status"), type: 'status' },
				],
				rows,
			}],
			outputFiles,
			problems: [],
		};
	},
});

//#endregion

//#region Manage: Verification Manual (PDF)

registerPanelCommand({
	id: 'saengine.manage.verificationManual',
	title: localize('u3.verify.title', "Verification Manual (PDF)"),
	part: 'fem',
	icon: Codicon.filePdf,
	requiresProject: false,
	autoRun: false,
	runLabel: localize('u3.verify.run', "Run Verification Pack"),
	help: localize('u3.verify.help', "Runs SAEngine closed-form and reference benchmarks, compares computed quantities against reference tolerances, and renders the Typst Verification Manual PDF."),
	fields: [
		{
			key: 'scope',
			label: localize('u3.verify.scope', "Benchmark Scope"),
			type: 'select',
			defaultValue: 'fast',
			options: [
				{ value: 'fast', label: localize('u3.verify.fast', "Fast cases only") },
				{ value: 'all', label: localize('u3.verify.all', "All cases (includes full FE models)") },
				{ value: 'selected', label: localize('u3.verify.selected', "Selected case IDs") },
			],
		},
		{
			key: 'caseIds',
			label: localize('u3.verify.caseIds', "Case IDs (comma-separated)"),
			type: 'text',
			defaultValue: '',
			placeholder: 'e.g. A1, D1',
			visibleWhen: values => values.scope === 'selected',
		},
		{ key: 'pdf', label: localize('u3.verify.pdf', "Generate Verification Manual PDF"), type: 'checkbox', defaultValue: true },
		{ key: 'outDir', label: localize('u3.verify.outDir', "Output Folder (blank = temp folder)"), type: 'folder', defaultValue: '' },
	],
	loadInitial: async () => {
		return undefined;
	},
	run: async (ctx, values) => {
		const scope = String(values.scope || 'fast');
		const ids = scope === 'selected' ? parseList(String(values.caseIds || '')) : undefined;
		const defaultOut = !String(values.outDir || '').trim() && ctx.project
			? `${ctx.project.root.fsPath}/11 Exports/Verification`
			: (String(values.outDir || '').trim() || undefined);
		const raw = asBag(await ctx.engineRequest('verification/run', {
			outDir: defaultOut,
			ids: ids?.length ? ids : undefined,
			fastOnly: scope === 'fast',
			pdf: Boolean(values.pdf),
		}));
		const summary = asBag(raw.summary);
		const cases = asArray(raw.cases).map(asBag);
		const caseRows: DataPanelRow[] = cases.map(c => ({
			id: str(c.id),
			title: str(c.title),
			category: str(c.category),
			quantities: asArray(c.quantities).length,
			seconds: num(c.seconds) ?? 0,
			status: c.error ? 'Error' : (c.pass ? 'Pass' : 'Fail'),
			error: str(c.error),
		}));
		const qtyRows: DataPanelRow[] = cases.flatMap(c =>
			asArray(c.quantities).map(asBag).map(q => ({
				caseId: str(c.id),
				name: str(q.name),
				unit: str(q.unit),
				reference: num(q.reference) ?? str(q.reference),
				saengine: num(q.saengine) ?? str(q.saengine),
				ratio: num(q.ratio) ?? '–',
				tolerance: num(q.tolerance) ?? '–',
				status: q.pass ? 'Pass' : 'Fail',
			}))
		);
		const outputFiles = [];
		if (typeof raw.pdfPath === 'string' && raw.pdfPath) {
			outputFiles.push({ label: localize('u3.verify.openPdf', "Open Verification Manual PDF"), path: raw.pdfPath });
		}
		if (typeof raw.jsonPath === 'string' && raw.jsonPath) {
			outputFiles.push({ label: localize('u3.verify.openJson', "Open verification.json"), path: raw.jsonPath });
		}
		const failed = num(summary.failed) ?? 0;
		const total = num(summary.cases) ?? cases.length;
		const passed = num(summary.passed) ?? 0;
		return {
			metrics: [
				{ label: localize('u3.verify.totalCases', "Cases"), value: String(total) },
				{ label: localize('u3.verify.passedCases', "Passed"), value: String(passed), tone: passed > 0 ? 'ok' : 'neutral' },
				{ label: localize('u3.verify.failedCases', "Failed"), value: String(failed), tone: failed ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'cases',
					title: localize('u3.verify.casesTab', "Benchmark Cases"),
					columns: [
						{ key: 'id', title: localize('u3.col.id', "ID") },
						{ key: 'title', title: localize('u3.col.title', "Title") },
						{ key: 'category', title: localize('u3.col.category', "Category") },
						{ key: 'quantities', title: localize('u3.col.checks', "Checks"), type: 'number', align: 'right' },
						{ key: 'seconds', title: localize('u3.col.seconds', "Time [s]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.col.result', "Result"), type: 'status' },
					],
					rows: caseRows,
				},
				{
					id: 'quantities',
					title: localize('u3.verify.qtyTab', "Compared Quantities"),
					columns: [
						{ key: 'caseId', title: localize('u3.col.case', "Case") },
						{ key: 'name', title: localize('u3.col.quantity', "Quantity") },
						{ key: 'unit', title: localize('u3.col.unit', "Unit") },
						{ key: 'reference', title: localize('u3.col.referenceVal', "Reference"), type: 'number', align: 'right' },
						{ key: 'saengine', title: localize('u3.col.saengineVal', "SAEngine"), type: 'number', align: 'right' },
						{ key: 'ratio', title: localize('u3.col.ratio', "Ratio"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.col.status', "Status"), type: 'status' },
					],
					rows: qtyRows,
				},
			],
			outputFiles,
			notes: asStrings(raw.warnings),
			problems: asStrings(raw.problems),
		};
	},
	secondaryActions: [{
		id: 'listCases',
		label: localize('u3.verify.listCases', "List Available Cases"),
		icon: Codicon.checklist,
		run: async ctx => {
			const res = asBag(await ctx.engineRequest('verification/cases', {}));
			const list = asArray(res.cases).map(c => `${str(asBag(c).id)}: ${str(asBag(c).title)}`);
			ctx.notificationService.info(localize('u3.verify.availableCases', "Verification cases ({0}): {1}", list.length, list.join(', ')));
		},
	}],
});

//#endregion

//#region Studies: Annual Energy & Envelope Compliance

registerPanelCommand({
	id: 'saengine.studies.annualEnergy',
	title: localize('u3.studies.energy.title', "Annual Energy Simulation (EUI)"),
	part: 'mep',
	icon: Codicon.pulse,
	autoRun: false,
	runLabel: localize('u3.studies.energy.run', "Run Annual Simulation"),
	help: localize('u3.studies.energy.help', "Runs an 8760-hour EnergyPlus annual energy simulation with a user-supplied EPW weather file and reports annual end uses, EUI [kWh/m²·yr] and unmet hours."),
	fields: [
		{
			key: 'epw',
			label: localize('u3.studies.energy.epw', "EPW Weather File"),
			type: 'file',
			defaultValue: '',
			placeholder: localize('u3.studies.energy.epwPlaceholder', "Select an .epw weather file"),
			filters: [{ name: 'EnergyPlus Weather', extensions: ['epw'] }],
		},
		{
			key: 'zoning',
			label: localize('u3.studies.energy.zoning', "Thermal Zoning"),
			type: 'select',
			defaultValue: 'story',
			options: [
				{ value: 'story', label: localize('u3.studies.energy.zoningStory', "Per Story (faster annual run)") },
				{ value: 'room', label: localize('u3.studies.energy.zoningRoom', "Per Room (detailed)") },
			],
		},
	],
	secondaryActions: [{
		id: 'openHvac',
		label: localize('u3.studies.openHvac', "Open MEP HVAC"),
		icon: Codicon.dashboard,
		run: ctx => void ctx.commandService.executeCommand('saengine.ribbon.openSection.mep.hvac'),
	}],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/hvacLoadsDetailed', {
			projectRoot: ctx.project!.root.fsPath,
			zoning: String(values.zoning || 'story'),
			useEnergyPlus: true,
			annual: true,
			epw: String(values.epw || '').trim() || undefined,
		}));
		const annual = asBag(raw.annual);
		const unmet = asBag(annual.unmetHours);
		const hasAnnual = Object.keys(annual).length > 0;
		const endUseRows: DataPanelRow[] = hasAnnual ? [
			{ metric: localize('u3.studies.energy.cooling', "Cooling Energy"), value: num(annual.coolingKwh) ?? 0, unit: 'kWh', note: `COP ${str(annual.coolingCop, '–')}` },
			{ metric: localize('u3.studies.energy.heating', "Heating Energy"), value: num(annual.heatingKwh) ?? 0, unit: 'kWh', note: `COP ${str(annual.heatingCop, '–')}` },
			{ metric: localize('u3.studies.energy.lighting', "Interior Lighting"), value: num(annual.lightingKwh) ?? 0, unit: 'kWh', note: str(annual.copNote) },
			{ metric: localize('u3.studies.energy.equipment', "Equipment"), value: num(annual.equipmentKwh) ?? 0, unit: 'kWh', note: '' },
			{ metric: localize('u3.studies.energy.fansPumps', "Fans & Pumps"), value: num(annual.fansPumpsKwh) ?? 0, unit: 'kWh', note: '' },
			{ metric: localize('u3.studies.energy.totalKwh', "Total Annual Energy"), value: num(annual.totalKwh) ?? 0, unit: 'kWh', note: `System: ${str(annual.system)}` },
			{ metric: localize('u3.studies.energy.floorArea', "Conditioned Floor Area"), value: num(annual.floorAreaM2) ?? 0, unit: 'm²', note: '' },
			{ metric: localize('u3.studies.energy.eui', "Energy Use Intensity (EUI)"), value: num(annual.euiKwhM2Yr) ?? '–', unit: 'kWh/m²·yr', note: '' },
			{ metric: localize('u3.studies.energy.unmetHeat', "Unmet Heating Hours"), value: num(unmet.heating) ?? 0, unit: 'h', note: '' },
			{ metric: localize('u3.studies.energy.unmetCool', "Unmet Cooling Hours"), value: num(unmet.cooling) ?? 0, unit: 'h', note: '' },
		] : [];
		const storyRows: DataPanelRow[] = asArray(raw.stories).map(asBag).map(s => ({
			story: str(s.story),
			area: num(s.area) ?? 0,
			total: num(s.total) ?? 0,
			heating: num(s.heating) ?? 0,
		}));
		const euiVal = num(annual.euiKwhM2Yr);
		const totalKwhVal = num(annual.totalKwh);
		const unmetTotalVal = num(unmet.total);
		return {
			metrics: [
				{ label: localize('u3.studies.energy.mEui', "EUI"), value: euiVal !== undefined ? `${euiVal} kWh/m²·yr` : '–', tone: hasAnnual ? 'ok' : 'warn' },
				{ label: localize('u3.studies.energy.mTotal', "Annual Total"), value: totalKwhVal !== undefined ? `${totalKwhVal} kWh` : '–' },
				{ label: localize('u3.studies.energy.mUnmet', "Unmet Hours"), value: unmetTotalVal !== undefined ? `${unmetTotalVal} h` : '–', tone: (unmetTotalVal ?? 0) > 300 ? 'warn' : 'ok' },
				{ label: localize('u3.studies.energy.mEngine', "Engine"), value: str(raw.engineLabel || raw.engine, '–') },
			],
			tables: [
				{
					id: 'endUses',
					title: localize('u3.studies.energy.endUsesTab', "Annual End Uses & EUI"),
					columns: [
						{ key: 'metric', title: localize('u3.studies.energy.colMetric', "End Use / Metric") },
						{ key: 'value', title: localize('u3.studies.energy.colValue', "Value"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.studies.energy.colUnit', "Unit") },
						{ key: 'note', title: localize('u3.studies.energy.colNote', "Note") },
					],
					rows: endUseRows,
					emptyMessage: localize('u3.studies.energy.noAnnual', "No annual results returned. Select a valid .epw weather file and ensure EnergyPlus is installed."),
				},
				{
					id: 'stories',
					title: localize('u3.studies.energy.storiesTab', "Design-Day Story Loads"),
					columns: [
						{ key: 'story', title: localize('u3.studies.energy.colStory', "Story") },
						{ key: 'area', title: localize('u3.studies.energy.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'total', title: localize('u3.studies.energy.colCooling', "Cooling [kW]"), type: 'number', align: 'right' },
						{ key: 'heating', title: localize('u3.studies.energy.colHeating', "Heating [kW]"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerPanelCommand({
	id: 'saengine.studies.envelopeCompliance',
	title: localize('u3.studies.env.title', "Building Envelope Compliance"),
	part: 'mep',
	icon: Codicon.pass,
	autoRun: true,
	help: localize('u3.studies.env.help', "Checks exterior wall, roof and glazing U-values, window-to-wall ratio (WWR) and glazing SHGC against active code pack and ASHRAE 90.1 / ECBC limits."),
	secondaryActions: [{
		id: 'openHvac',
		label: localize('u3.studies.env.openHvac', "Open MEP HVAC"),
		icon: Codicon.dashboard,
		run: ctx => void ctx.commandService.executeCommand('saengine.ribbon.openSection.mep.hvac'),
	}],
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/hvacLoadsDetailed', {
			projectRoot: ctx.project!.root.fsPath,
			zoning: 'room',
			useEnergyPlus: false,
			annual: false,
		}));
		const ec = asBag(raw.envelopeCompliance);
		const env = asBag(raw.envelope);
		const checks = asArray(ec.checks).map(asBag);
		const checkRows: DataPanelRow[] = checks.map(c => ({
			label: str(c.label),
			actual: num(c.actual) ?? '–',
			limit: num(c.limit) ?? '–',
			unit: str(c.unit, '-'),
			status: c.passed ? 'Pass' : 'Fail',
			reference: str(c.reference),
		}));
		const facadeRows: DataPanelRow[] = Object.entries(asBag(ec.byFacade)).map(([facade, entry]) => {
			const f = asBag(entry);
			const wwr = num(f.wwr) ?? 0;
			return {
				facade,
				wallArea: num(f.wallArea) ?? 0,
				windowArea: num(f.windowArea) ?? 0,
				wwrPct: Number((wwr * 100).toFixed(1)),
			};
		});
		const constructionRows: DataPanelRow[] = Object.keys(env).length ? [
			{ item: localize('u3.studies.env.wall', "Wall Construction"), description: str(env.wall), value: num(env.uWall) ?? '–', unit: 'W/m²K' },
			{ item: localize('u3.studies.env.roof', "Roof Construction"), description: str(env.roof), value: num(env.uRoof) ?? '–', unit: 'W/m²K' },
			{ item: localize('u3.studies.env.glazing', "Glazing Construction"), description: str(env.glazing), value: num(env.uGlazing) ?? '–', unit: 'W/m²K' },
			{ item: localize('u3.studies.env.shgc', "Glazing SHGC"), description: str(env.glazing), value: num(env.shgc) ?? '–', unit: '-' },
			{ item: localize('u3.studies.env.shading', "Shading"), description: str(env.shading, '–'), value: str(env.shading, '–'), unit: '' },
		] : [];
		const wwrPct = `${((num(ec.wwr) ?? 0) * 100).toFixed(1)}%`;
		const passed = Boolean(ec.passed);
		return {
			metrics: [
				{
					label: localize('u3.studies.env.mStatus', "Compliance"),
					value: checks.length ? (passed ? localize('u3.studies.env.pass', "Pass") : localize('u3.studies.env.fail', "Fail")) : '–',
					tone: checks.length ? (passed ? 'ok' : 'fail') : 'neutral',
				},
				{ label: localize('u3.studies.env.mWwr', "Overall WWR"), value: wwrPct },
				{ label: localize('u3.studies.env.mWallArea', "Wall Area"), value: `${num(ec.wallArea) ?? 0} m²` },
				{ label: localize('u3.studies.env.mWinArea', "Window Area"), value: `${num(ec.windowArea) ?? 0} m²` },
			],
			tables: [
				{
					id: 'checks',
					title: localize('u3.studies.env.checksTab', "Envelope Code Checks"),
					columns: [
						{ key: 'label', title: localize('u3.studies.env.colCheck', "Parameter") },
						{ key: 'actual', title: localize('u3.studies.env.colActual', "Actual"), type: 'number', align: 'right' },
						{ key: 'limit', title: localize('u3.studies.env.colLimit', "Limit"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.studies.env.colUnit', "Unit") },
						{ key: 'status', title: localize('u3.studies.env.colStatus', "Status"), type: 'status' },
						{ key: 'reference', title: localize('u3.studies.env.colRef', "Reference") },
					],
					rows: checkRows,
				},
				{
					id: 'facades',
					title: localize('u3.studies.env.facadesTab', "Facade Breakdown"),
					columns: [
						{ key: 'facade', title: localize('u3.studies.env.colFacade', "Facade") },
						{ key: 'wallArea', title: localize('u3.studies.env.colWallArea', "Wall Area [m²]"), type: 'number', align: 'right' },
						{ key: 'windowArea', title: localize('u3.studies.env.colWinArea', "Window Area [m²]"), type: 'number', align: 'right' },
						{ key: 'wwrPct', title: localize('u3.studies.env.colWwr', "WWR [%]"), type: 'number', align: 'right' },
					],
					rows: facadeRows,
				},
				{
					id: 'constructions',
					title: localize('u3.studies.env.constructionsTab', "Constructions"),
					columns: [
						{ key: 'item', title: localize('u3.studies.env.colItem', "Element") },
						{ key: 'description', title: localize('u3.studies.env.colDesc', "Assembly") },
						{ key: 'value', title: localize('u3.studies.env.colUVal', "Value"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.studies.env.colCUnit', "Unit") },
					],
					rows: constructionRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion
