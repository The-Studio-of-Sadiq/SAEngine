/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { joinPath } from '../../../../base/common/resources.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, IDataPanelAction, IEngineDataPanelDescriptor, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';

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

function formatScalar(value: unknown): string {
	if (value === null || value === undefined || value === '') {
		return '–';
	}
	if (typeof value === 'boolean') {
		return value ? 'Yes' : 'No';
	}
	if (typeof value === 'number') {
		// Engine floats (17.255999999999997) read as 17.256.
		return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
	}
	if (typeof value === 'string') {
		return value;
	}
	return JSON.stringify(value);
}

function registerBoqPanel(descriptor: IEngineDataPanelDescriptor): void {
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

function openBoqAction(label: string): readonly IDataPanelAction[] {
	return [{
		id: 'openBoqEditor',
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand('saengine.project.showBoq'),
	}];
}

//#region Quantities & Bars

registerBoqPanel({
	id: 'saengine.boq.summary',
	title: localize('u6d.boq.sum.title', "BOQ Quantities Summary"),
	part: 'boq',
	icon: Codicon.table,
	help: localize('u6d.boq.sum.help', "Summarizes all measured Bill of Quantities items from 10 BOQ/boq.json across concrete, formwork, reinforcement, steel and finishes."),
	secondaryActions: openBoqAction(localize('u6d.boq.openBoq', "Open BOQ")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/summary', { projectRoot: ctx.project!.root.fsPath }));
		const items = asArray(raw.items).map(asBag);
		const costing = asBag(raw.costing);
		const rows: DataPanelRow[] = items.map(it => ({
			code: str(it.code),
			group: str(it.group, '–'),
			description: str(it.description),
			quantity: num(it.quantity) ?? 0,
			unit: str(it.unit, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.sum.mItems', "Bill Items"), value: String(rows.length) },
				{ label: localize('u6d.boq.sum.mCost', "Estimated Total"), value: costing.total !== undefined ? `${str(costing.currency)} ${formatScalar(costing.total)}` : '–' },
			],
			tables: [{
				id: 'items',
				title: localize('u6d.boq.sum.tab', "Bill of Quantities Items"),
				columns: [
					{ key: 'code', title: localize('u6d.boq.sum.colCode', "Code") },
					{ key: 'group', title: localize('u6d.boq.sum.colGrp', "Group") },
					{ key: 'description', title: localize('u6d.boq.sum.colDesc', "Description") },
					{ key: 'quantity', title: localize('u6d.boq.sum.colQty', "Quantity"), type: 'number', align: 'right' },
					{ key: 'unit', title: localize('u6d.boq.sum.colUnit', "Unit") },
				],
				rows,
				emptyMessage: localize('u6d.boq.sum.empty', "Run Measure in the BOQ editor to generate 10 BOQ/boq.json."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.rebarSchedule',
	title: localize('u6d.boq.bbs.title', "Reinforcement Bar Bending Schedule"),
	part: 'boq',
	icon: Codicon.listOrdered,
	help: localize('u6d.boq.bbs.help', "Aggregates cut lengths and total steel tonnage by bar diameter and bar mark from drawing-derived and substructure schedules."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/barSchedule', { projectRoot: ctx.project!.root.fsPath }));
		const diaRows: DataPanelRow[] = asArray(raw.byDiameter).map(asBag).map(d => ({
			diaMm: num(d.diaMm) ?? 0,
			totalKg: num(d.totalKg) ?? 0,
			totalTonnes: num(d.totalKg) !== undefined ? Number((num(d.totalKg)! / 1000).toFixed(3)) : 0,
		}));
		const markRows: DataPanelRow[] = asArray(raw.marks).map(asBag).map(m => ({
			mark: str(m.mark),
			member: str(m.member),
			kind: str(m.kind),
			diaMm: num(m.diaMm) ?? 0,
			count: num(m.count) ?? 0,
			cutLengthMm: num(m.cutLengthMm) ?? 0,
			massKg: num(m.massKg) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.bbs.mMarks', "Bar Marks"), value: String(raw.markCount ?? markRows.length) },
				{ label: localize('u6d.boq.bbs.mDias', "Bar Diameters"), value: String(diaRows.length) },
			],
			tables: [
				{
					id: 'byDiameter',
					title: localize('u6d.boq.bbs.diaTab', "Steel Weight by Diameter"),
					columns: [
						{ key: 'diaMm', title: localize('u6d.boq.bbs.colDia', "Bar Ø [mm]"), type: 'number', align: 'right' },
						{ key: 'totalKg', title: localize('u6d.boq.bbs.colKg', "Weight [kg]"), type: 'number', align: 'right' },
						{ key: 'totalTonnes', title: localize('u6d.boq.bbs.colT', "Weight [t]"), type: 'number', align: 'right' },
					],
					rows: diaRows,
					emptyMessage: localize('u6d.boq.bbs.emptyDia', "No designed reinforcement schedule available yet."),
				},
				{
					id: 'marks',
					title: localize('u6d.boq.bbs.markTab', "Bar Marks"),
					columns: [
						{ key: 'mark', title: localize('u6d.boq.bbs.colMark', "Mark") },
						{ key: 'member', title: localize('u6d.boq.bbs.colMem', "Member") },
						{ key: 'kind', title: localize('u6d.boq.bbs.colKind', "Element") },
						{ key: 'diaMm', title: localize('u6d.boq.bbs.colMDia', "Ø [mm]"), type: 'number', align: 'right' },
						{ key: 'count', title: localize('u6d.boq.bbs.colCnt', "Qty"), type: 'number', align: 'right' },
						{ key: 'cutLengthMm', title: localize('u6d.boq.bbs.colLen', "Cut [mm]"), type: 'number', align: 'right' },
						{ key: 'massKg', title: localize('u6d.boq.bbs.colMass', "Mass [kg]"), type: 'number', align: 'right' },
					],
					rows: markRows,
				},
			],
			notes: [...(raw.takenNote ? [str(raw.takenNote)] : []), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.conventions',
	title: localize('u6d.boq.conv.title', "BOQ Estimating & Mix Conventions"),
	part: 'boq',
	icon: Codicon.book,
	help: localize('u6d.boq.conv.help', "Shows code-pack cement bag weights, brick/aggregate conversions and materials estimating conventions used by BOQ takeoff."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/summary', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = asStrings(raw.conventions).map((c, idx) => ({
			index: idx + 1,
			convention: c,
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.conv.mCount', "Conventions"), value: String(rows.length) },
			],
			tables: [{
				id: 'conventions',
				title: localize('u6d.boq.conv.tab', "Estimating & Materials Conventions"),
				columns: [
					{ key: 'index', title: '#', type: 'number', align: 'right' },
					{ key: 'convention', title: localize('u6d.boq.conv.colText', "Rule / Conversion") },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Rates, Costing & Value Engineering

registerBoqPanel({
	id: 'saengine.boq.rateTemplates',
	title: localize('u6d.boq.tpl.title', "Sample Schedule of Rates & Carbon Factors"),
	part: 'boq',
	icon: Codicon.library,
	requiresProject: false,
	help: localize('u6d.boq.tpl.help', "Previews the built-in sample schedule of unit rates and embodied carbon factors [kg CO2e/kg] shipped with SAEngine."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/templates', {}));
		let rateItems: DataPanelRow[] = [];
		let carbonItems: DataPanelRow[] = [];
		try {
			const rParsed = asBag(JSON.parse(str(raw.rates, '{}')));
			rateItems = asArray(rParsed.items ?? rParsed.rates).map(asBag).map(r => ({
				code: str(r.code),
				description: str(r.description),
				unit: str(r.unit),
				rate: num(r.rate) ?? 0,
			}));
		} catch {
			// leave empty if unparseable
		}
		try {
			const cParsed = asBag(JSON.parse(str(raw.carbon, '{}')));
			carbonItems = asArray(cParsed.factors ?? cParsed.materials ?? cParsed.items).map(asBag).map(c => ({
				id: str(c.id || c.material),
				factor: num(c.factor) ?? 0,
				source: str(c.source, '–'),
			}));
		} catch {
			// leave empty if unparseable
		}
		return {
			metrics: [
				{ label: localize('u6d.boq.tpl.mRates', "Sample Rate Items"), value: String(rateItems.length) },
				{ label: localize('u6d.boq.tpl.mCarb', "Carbon Factors"), value: String(carbonItems.length) },
			],
			tables: [
				{
					id: 'rates',
					title: localize('u6d.boq.tpl.rateTab', "Default Schedule of Rates"),
					columns: [
						{ key: 'code', title: localize('u6d.boq.tpl.colCode', "Code") },
						{ key: 'description', title: localize('u6d.boq.tpl.colDesc', "Description") },
						{ key: 'unit', title: localize('u6d.boq.tpl.colUnit', "Unit") },
						{ key: 'rate', title: localize('u6d.boq.tpl.colRate', "Rate"), type: 'number', align: 'right' },
					],
					rows: rateItems,
				},
				{
					id: 'carbon',
					title: localize('u6d.boq.tpl.carbTab', "Default Embodied Carbon Factors"),
					columns: [
						{ key: 'id', title: localize('u6d.boq.tpl.colCId', "Material") },
						{ key: 'factor', title: localize('u6d.boq.tpl.colCFac', "kg CO2e / kg"), type: 'number', align: 'right' },
						{ key: 'source', title: localize('u6d.boq.tpl.colCSrc', "Source") },
					],
					rows: carbonItems,
				},
			],
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.costReport',
	title: localize('u6d.boq.cost.title', "Costing & Embodied Carbon Breakdown"),
	part: 'boq',
	icon: Codicon.pieChart,
	help: localize('u6d.boq.cost.help', "Prices every BOQ line item using 10 BOQ/rates.json and computes embodied carbon [t CO2e] by material and building part."),
	secondaryActions: openBoqAction(localize('u6d.boq.openBoq', "Open BOQ")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/summary', { projectRoot: ctx.project!.root.fsPath }));
		const costing = asBag(raw.costing);
		const lines = asArray(costing.lines).map(asBag).map(l => ({
			code: str(l.code),
			description: str(l.description),
			quantity: num(l.quantity) ?? 0,
			unit: str(l.unit),
			rate: num(l.rate) ?? '–',
			amount: num(l.amount) ?? 0,
			status: str(l.status) === 'priced' ? 'Pass' : 'Warn',
		}));
		const carbon = asArray(costing.carbon).map(asBag).map(c => ({
			material: str(c.material || c.id),
			massKg: num(c.mass) ?? 0,
			factor: num(c.factor) ?? '–',
			carbonKg: num(c.carbon) ?? 0,
			source: str(c.source, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.cost.mTot', "Total Cost"), value: `${str(costing.currency)} ${formatScalar(costing.total)}` },
				{ label: localize('u6d.boq.cost.mCo2', "Embodied Carbon"), value: costing.carbonTotal !== undefined ? `${(Number(costing.carbonTotal) / 1000).toFixed(2)} t CO2e` : '–' },
				{ label: localize('u6d.boq.cost.mSched', "Rate Source"), value: raw.sampleRates ? 'Sample Rates' : str(costing.rateSchedule, 'Project Rates') },
			],
			tables: [
				{
					id: 'lines',
					title: localize('u6d.boq.cost.lineTab', "Priced Bill Lines"),
					columns: [
						{ key: 'code', title: localize('u6d.boq.cost.colCode', "Code") },
						{ key: 'description', title: localize('u6d.boq.cost.colDesc', "Item") },
						{ key: 'quantity', title: localize('u6d.boq.cost.colQty', "Qty"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u6d.boq.cost.colUnit', "Unit") },
						{ key: 'rate', title: localize('u6d.boq.cost.colRate', "Rate"), type: 'number', align: 'right' },
						{ key: 'amount', title: localize('u6d.boq.cost.colAmt', "Amount"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u6d.boq.cost.colStat', "Priced"), type: 'status' },
					],
					rows: lines,
				},
				{
					id: 'carbon',
					title: localize('u6d.boq.cost.carbTab', "Embodied Carbon by Material"),
					columns: [
						{ key: 'material', title: localize('u6d.boq.cost.colMat', "Material") },
						{ key: 'massKg', title: localize('u6d.boq.cost.colMass', "Mass [kg]"), type: 'number', align: 'right' },
						{ key: 'factor', title: localize('u6d.boq.cost.colFac', "Factor"), type: 'number', align: 'right' },
						{ key: 'carbonKg', title: localize('u6d.boq.cost.colCo2', "CO2e [kg]"), type: 'number', align: 'right' },
						{ key: 'source', title: localize('u6d.boq.cost.colSrc', "Source") },
					],
					rows: carbon,
				},
			],
			notes: [...asStrings(costing.notes), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.phaseBill',
	title: localize('u6d.boq.phase.title', "Phased Bill of Quantities"),
	part: 'boq',
	icon: Codicon.splitHorizontal,
	help: localize('u6d.boq.phase.help', "Splits bill of quantities items by construction phase (new vs demolished vs existing) from project phasing definitions."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('office/phaseBill', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = [];
		for (const ph of asArray(raw.phases).map(asBag)) {
			const phaseName = str(ph.name || ph.phase);
			for (const item of asArray(ph.new).map(asBag)) {
				rows.push({
					phase: phaseName,
					work: 'New Work',
					code: str(item.code),
					description: str(item.description),
					quantity: num(item.quantity) ?? 0,
					unit: str(item.unit),
				});
			}
			for (const item of asArray(ph.demolished).map(asBag)) {
				rows.push({
					phase: phaseName,
					work: 'Demolished',
					code: str(item.code),
					description: str(item.description),
					quantity: num(item.quantity) ?? 0,
					unit: str(item.unit),
				});
			}
		}
		for (const item of asArray(raw.existing).map(asBag)) {
			rows.push({
				phase: 'Existing Retained',
				work: 'Retained',
				code: str(item.code),
				description: str(item.description),
				quantity: num(item.quantity) ?? 0,
				unit: str(item.unit),
			});
		}
		return {
			metrics: [
				{ label: localize('u6d.boq.phase.mPhases', "Phases"), value: String(asArray(raw.phases).length) },
				{ label: localize('u6d.boq.phase.mRows', "Phased Lines"), value: String(rows.length) },
			],
			tables: [{
				id: 'phased',
				title: localize('u6d.boq.phase.tab', "Quantities Split by Construction Phase"),
				columns: [
					{ key: 'phase', title: localize('u6d.boq.phase.colPh', "Phase") },
					{ key: 'work', title: localize('u6d.boq.phase.colWk', "Work") },
					{ key: 'code', title: localize('u6d.boq.phase.colCode', "Code") },
					{ key: 'description', title: localize('u6d.boq.phase.colDesc', "Description") },
					{ key: 'quantity', title: localize('u6d.boq.phase.colQty', "Quantity"), type: 'number', align: 'right' },
					{ key: 'unit', title: localize('u6d.boq.phase.colUnit', "Unit") },
				],
				rows,
				emptyMessage: localize('u6d.boq.phase.empty', "Measure the BOQ first to split items across project phases."),
			}],
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.costOptimise',
	title: localize('u6d.boq.opt.title', "Value Engineering Cost Optimisation"),
	part: 'boq',
	icon: Codicon.sparkle,
	autoRun: false,
	runLabel: localize('u6d.boq.opt.run', "Optimise Member Costs"),
	help: localize('u6d.boq.opt.help', "Evaluates candidate sections and grades from 03 Materials to find the lowest-cost code-passing section per member group (requires prior FEM results)."),
	fields: [
		{ key: 'limit', label: localize('u6d.boq.opt.lim', "Max Utilisation Limit"), type: 'number', defaultValue: 1.0, min: 0.5, max: 1.2, step: '0.05' },
	],
	run: async (ctx, values) => {
		const root = ctx.project!.root;
		const outDir = joinPath(root, '08 FEM', 'model.results').fsPath;
		const projectPath = joinPath(root, '08 FEM', 'model.osmodel').fsPath;
		let ratesText: string | undefined;
		try {
			ratesText = (await ctx.fileService.readFile(joinPath(root, '10 BOQ', 'rates.json'))).value.toString();
		} catch {
			ratesText = undefined;
		}
		const raw = asBag(await ctx.engineRequest('office/optimise', {
			outDir,
			projectPath,
			...(ratesText ? { ratesText } : {}),
			options: { limit: Number(values.limit) || 1.0 },
		}));
		const groups = asArray(raw.groups).map(asBag).map(g => ({
			type: str(g.type),
			kind: str(g.kind),
			members: formatScalar(g.members),
			lengthM: num(g.length) ?? 0,
			currentCost: num(asBag(g.current).cost) ?? '–',
			bestCost: num(asBag(g.best).cost) ?? '–',
			delta: num(g.delta) ?? '–',
			status: str(g.status, '–'),
		}));
		const tot = asBag(raw.total);
		return {
			metrics: [
				{ label: localize('u6d.boq.opt.mCur', "Current Cost"), value: formatScalar(tot.current) },
				{ label: localize('u6d.boq.opt.mBest', "Optimised Cost"), value: formatScalar(tot.best) },
				{ label: localize('u6d.boq.opt.mSave', "Savings"), value: formatScalar(tot.delta) },
			],
			tables: [{
				id: 'optimisation',
				title: localize('u6d.boq.opt.tab', "Cost-Optimised Member Groups"),
				columns: [
					{ key: 'type', title: localize('u6d.boq.opt.colType', "Object Type") },
					{ key: 'kind', title: localize('u6d.boq.opt.colKind', "Kind") },
					{ key: 'members', title: localize('u6d.boq.opt.colMem', "Members") },
					{ key: 'lengthM', title: localize('u6d.boq.opt.colLen', "Length [m]"), type: 'number', align: 'right' },
					{ key: 'currentCost', title: localize('u6d.boq.opt.colCur', "Current"), type: 'number', align: 'right' },
					{ key: 'bestCost', title: localize('u6d.boq.opt.colBest', "Best"), type: 'number', align: 'right' },
					{ key: 'delta', title: localize('u6d.boq.opt.colDelta', "Delta"), type: 'number', align: 'right' },
					{ key: 'status', title: localize('u6d.boq.opt.colStat', "Status"), type: 'status' },
				],
				rows: groups,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.compareOptions',
	title: localize('u6d.boq.cmp.title', "Compare Project Versions (Cost & Carbon)"),
	part: 'boq',
	icon: Codicon.diff,
	help: localize('u6d.boq.cmp.help', "Compares quantities, total cost and embodied carbon across saved project versions or working state."),
	fields: [
		{ key: 'versionA', label: localize('u6d.boq.cmp.vA', "Baseline Version"), type: 'text', defaultValue: 'working' },
		{ key: 'versionB', label: localize('u6d.boq.cmp.vB', "Option Version (blank or version tag)"), type: 'text', defaultValue: 'working' },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('office/compareOptions', {
			projectRoot: ctx.project!.root.fsPath,
			options: [
				{ id: 'A', name: str(values.versionA, 'working'), version: String(values.versionA || 'working') },
				{ id: 'B', name: str(values.versionB, 'working'), version: String(values.versionB || 'working') },
			],
		}));
		const opts = asArray(raw.options).map(asBag);
		const deltas = asArray(raw.deltas).map(asBag);
		const rows: DataPanelRow[] = opts.map((o, idx) => ({
			name: str(o.name),
			version: str(o.version),
			cost: formatScalar(o.cost),
			carbon: formatScalar(o.carbon),
			costDelta: formatScalar(deltas[idx]?.cost),
			carbonDelta: formatScalar(deltas[idx]?.carbon),
			problem: asStrings(o.problems).join('; ') || 'Pass',
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.cmp.mOpts', "Options Compared"), value: String(rows.length) },
			],
			tables: [{
				id: 'options',
				title: localize('u6d.boq.cmp.tab', "Design Option Cost & Carbon Comparison"),
				columns: [
					{ key: 'name', title: localize('u6d.boq.cmp.colName', "Option") },
					{ key: 'version', title: localize('u6d.boq.cmp.colVer', "Version") },
					{ key: 'cost', title: localize('u6d.boq.cmp.colCost', "Cost") },
					{ key: 'carbon', title: localize('u6d.boq.cmp.colCarb', "Carbon [kg CO2e]") },
					{ key: 'costDelta', title: localize('u6d.boq.cmp.colDC', "Δ Cost") },
					{ key: 'carbonDelta', title: localize('u6d.boq.cmp.colDCo2', "Δ Carbon") },
					{ key: 'problem', title: localize('u6d.boq.cmp.colStat', "Status"), type: 'status' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
		};
	},
});

//#endregion

//#region Construction Schedule (4D)

registerBoqPanel({
	id: 'saengine.boq.generateSchedule',
	title: localize('u6d.boq.genSched.title', "Generate 4D Construction Programme"),
	part: 'boq',
	icon: Codicon.calendar,
	autoRun: false,
	runLabel: localize('u6d.boq.genSched.run', "Generate 4D Programme"),
	help: localize('u6d.boq.genSched.help', "Generates 10 BOQ/construction-schedule.json from 06 BIM, 09 Substructure, and productivity norms using CPM scheduling."),
	fields: [
		{ key: 'start', label: localize('u6d.boq.genSched.start', "Start Date [YYYY-MM-DD] (blank = today)"), type: 'text', defaultValue: '' },
	],
	run: async (ctx, values) => {
		const start = String(values.start || '').trim();
		const raw = asBag(await ctx.engineRequest('office/schedule', {
			projectRoot: ctx.project!.root.fsPath,
			...(start ? { start } : {}),
		}));
		const sched = asBag(raw.schedule);
		const acts = asArray(sched.activities).map(asBag).map(a => ({
			id: str(a.id),
			name: str(a.name),
			category: str(a.category),
			level: str(a.level, '–'),
			days: num(a.duration ?? a.days) ?? 0,
			earlyStart: str(a.earlyStart, '–'),
			earlyFinish: str(a.earlyFinish, '–'),
			critical: a.critical ? 'Critical' : 'OK',
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.genSched.mStart', "Start"), value: str(sched.start, '–') },
				{ label: localize('u6d.boq.genSched.mFin', "Finish"), value: str(sched.finish, '–') },
				{ label: localize('u6d.boq.genSched.mActs', "Activities"), value: String(acts.length) },
			],
			tables: [{
				id: 'activities',
				title: localize('u6d.boq.genSched.tab', "Generated Construction Activities"),
				columns: [
					{ key: 'id', title: localize('u6d.boq.genSched.colId', "ID") },
					{ key: 'name', title: localize('u6d.boq.genSched.colName', "Activity") },
					{ key: 'category', title: localize('u6d.boq.genSched.colCat', "Category") },
					{ key: 'level', title: localize('u6d.boq.genSched.colLvl', "Level") },
					{ key: 'days', title: localize('u6d.boq.genSched.colDays', "Days"), type: 'number', align: 'right' },
					{ key: 'earlyStart', title: localize('u6d.boq.genSched.colEs', "Early Start") },
					{ key: 'earlyFinish', title: localize('u6d.boq.genSched.colEf', "Early Finish") },
					{ key: 'critical', title: localize('u6d.boq.genSched.colCrit', "Path"), type: 'status' },
				],
				rows: acts,
			}],
			notes: asStrings(sched.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.scheduleSummary',
	title: localize('u6d.boq.schedSum.title', "4D Schedule & Critical Path Audit"),
	part: 'boq',
	icon: Codicon.checklist,
	help: localize('u6d.boq.schedSum.help', "Reads 10 BOQ/construction-schedule.json and evaluates CPM early/late dates, float and critical-path activities."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/scheduleSummary', { projectRoot: ctx.project!.root.fsPath }));
		const sched = asBag(raw.schedule);
		const acts = asArray(sched.activities).map(asBag).map(a => ({
			id: str(a.id),
			name: str(a.name),
			category: str(a.category),
			level: str(a.level, '–'),
			days: num(a.duration ?? a.days) ?? 0,
			totalFloat: num(a.totalFloat) ?? 0,
			critical: a.critical ? 'Critical' : 'OK',
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.schedSum.mFin', "Completion"), value: str(sched.finish, '–') },
				{ label: localize('u6d.boq.schedSum.mActs', "Activities"), value: String(acts.length) },
				{ label: localize('u6d.boq.schedSum.mCrit', "Critical Tasks"), value: String(acts.filter(a => a.critical === 'Critical').length) },
			],
			tables: [{
				id: 'cpm',
				title: localize('u6d.boq.schedSum.tab', "CPM Programme & Total Float"),
				columns: [
					{ key: 'id', title: localize('u6d.boq.schedSum.colId', "ID") },
					{ key: 'name', title: localize('u6d.boq.schedSum.colName', "Activity") },
					{ key: 'category', title: localize('u6d.boq.schedSum.colCat', "Category") },
					{ key: 'level', title: localize('u6d.boq.schedSum.colLvl', "Level") },
					{ key: 'days', title: localize('u6d.boq.schedSum.colDays', "Days"), type: 'number', align: 'right' },
					{ key: 'totalFloat', title: localize('u6d.boq.schedSum.colFlt', "Float [d]"), type: 'number', align: 'right' },
					{ key: 'critical', title: localize('u6d.boq.schedSum.colCrit', "Critical Path"), type: 'status' },
				],
				rows: acts,
				emptyMessage: localize('u6d.boq.schedSum.empty', "No 10 BOQ/construction-schedule.json found. Run Generate 4D Programme first."),
			}],
			notes: [...asStrings(raw.notes), ...asStrings(sched.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.productivityRates',
	title: localize('u6d.boq.prod.title', "Construction Crew Productivity Norms"),
	part: 'boq',
	icon: Codicon.dashboard,
	requiresProject: false,
	help: localize('u6d.boq.prod.help', "Displays standard daily output productivity rates per trade (excavation, piling, concrete, rebar, formwork, steel, finishes) used for 4D scheduling."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('office/productivityTemplate', {}));
		let rows: DataPanelRow[] = [];
		try {
			const parsed = asBag(JSON.parse(str(raw.text, '{}')));
			const rates = asBag(parsed.rates ?? parsed);
			rows = Object.entries(rates).map(([k, v]) => {
				const bag = asBag(v);
				return {
					activity: k,
					outputPerDay: formatScalar(bag.rate ?? bag.output ?? v),
					unit: str(bag.unit, '–'),
					crew: formatScalar(bag.crew),
				};
			});
		} catch {
			// leave empty
		}
		return {
			metrics: [
				{ label: localize('u6d.boq.prod.mCount', "Productivity Norms"), value: String(rows.length) },
			],
			tables: [{
				id: 'productivity',
				title: localize('u6d.boq.prod.tab', "Sample Productivity Rates"),
				columns: [
					{ key: 'activity', title: localize('u6d.boq.prod.colAct', "Trade / Category") },
					{ key: 'outputPerDay', title: localize('u6d.boq.prod.colOut', "Daily Output") },
					{ key: 'unit', title: localize('u6d.boq.prod.colUnit', "Unit") },
					{ key: 'crew', title: localize('u6d.boq.prod.colCrew', "Crew") },
				],
				rows,
			}],
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.exportSchedule',
	title: localize('u6d.boq.expSched.title', "Export 4D Schedule (CSV / MS Project XML)"),
	part: 'boq',
	icon: Codicon.export,
	autoRun: false,
	runLabel: localize('u6d.boq.expSched.run', "Export Schedule"),
	help: localize('u6d.boq.expSched.help', "Exports 10 BOQ/construction-schedule.json to CSV or Microsoft Project MSPDI XML format."),
	fields: [
		{
			key: 'format',
			label: localize('u6d.boq.expSched.fmt', "Export Format"),
			type: 'select',
			defaultValue: 'csv',
			options: [
				{ value: 'csv', label: localize('u6d.boq.expSched.csv', "CSV (.csv)") },
				{ value: 'mspdi', label: localize('u6d.boq.expSched.mspdi', "MS Project XML (.xml)") },
			],
		},
		{ key: 'path', label: localize('u6d.boq.expSched.path', "Output Path (blank = 10 BOQ/schedule.*)"), type: 'text', defaultValue: '' },
	],
	run: async (ctx, values) => {
		const root = ctx.project!.root;
		let schedText: string;
		try {
			schedText = (await ctx.fileService.readFile(joinPath(root, '10 BOQ', 'construction-schedule.json'))).value.toString();
		} catch {
			return { tables: [], problems: [localize('u6d.boq.expSched.missing', "No 10 BOQ/construction-schedule.json found. Run Generate 4D Programme first.")] };
		}
		const fmt = String(values.format || 'csv');
		const customPath = String(values.path || '').trim();
		const outPath = customPath || joinPath(root, '10 BOQ', fmt === 'mspdi' ? 'construction-schedule.xml' : 'construction-schedule.csv').fsPath;
		const raw = asBag(await ctx.engineRequest('office/exportSchedule', {
			text: schedText,
			path: outPath,
			format: fmt,
		}));
		const rows: DataPanelRow[] = Object.entries(raw).filter(([k]) => k !== 'problems').map(([k, v]) => ({
			property: k,
			value: formatScalar(v),
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.expSched.mFmt', "Format"), value: fmt.toUpperCase() },
			],
			tables: [{
				id: 'export',
				title: localize('u6d.boq.expSched.tab', "Schedule Export Output"),
				columns: [
					{ key: 'property', title: localize('u6d.boq.expSched.colProp', "Property") },
					{ key: 'value', title: localize('u6d.boq.expSched.colVal', "Value") },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Architectural, Precast & 2D PDF Takeoff

registerBoqPanel({
	id: 'saengine.boq.archTakeoff',
	title: localize('u6d.boq.arch.title', "Architectural Brickwork, Finishes, Doors & Windows Takeoff"),
	part: 'boq',
	icon: Codicon.home,
	help: localize('u6d.boq.arch.help', "Measures net architectural masonry, plaster, paint, floor finishes, ceilings, doors and windows after deducting structural frames and openings."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/archTakeoff', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = asArray(raw.items).map(asBag).map(it => ({
			code: str(it.code),
			group: str(it.group),
			description: str(it.description),
			quantity: num(it.quantity) ?? 0,
			unit: str(it.unit),
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.arch.mCount', "Architectural Lines"), value: String(rows.length) },
			],
			tables: [{
				id: 'archItems',
				title: localize('u6d.boq.arch.tab', "Architectural Quantity Takeoff"),
				columns: [
					{ key: 'code', title: localize('u6d.boq.arch.colCode', "Code") },
					{ key: 'group', title: localize('u6d.boq.arch.colGrp', "Trade") },
					{ key: 'description', title: localize('u6d.boq.arch.colDesc', "Description") },
					{ key: 'quantity', title: localize('u6d.boq.arch.colQty', "Quantity"), type: 'number', align: 'right' },
					{ key: 'unit', title: localize('u6d.boq.arch.colUnit', "Unit") },
				],
				rows,
				emptyMessage: localize('u6d.boq.arch.empty', "No architectural elements measured yet."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.precastSchedule',
	title: localize('u6d.boq.pre.title', "Precast Concrete Piece Schedule"),
	part: 'boq',
	icon: Codicon.symbolStructure,
	help: localize('u6d.boq.pre.help', "Lists precast piece marks with piece counts, dimensions, concrete volume, self-weight, embedded bars, lifting inserts and mould area."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/precastSchedule', { projectRoot: ctx.project!.root.fsPath }));
		const tot = asBag(raw.totals);
		const rows: DataPanelRow[] = asArray(raw.items).map(asBag).map(it => ({
			mark: str(it.mark || it.id),
			type: str(it.type, '–'),
			count: num(it.count) ?? 0,
			volumeM3: num(it.concrete ?? it.volume) ?? 0,
			weightKg: num(it.weight) ?? 0,
			barsKg: num(it.bars) ?? 0,
			mouldM2: num(it.mould) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.pre.mCnt', "Total Pieces"), value: formatScalar(tot.count ?? rows.length) },
				{ label: localize('u6d.boq.pre.mVol', "Concrete [m³]"), value: formatScalar(tot.concrete) },
				{ label: localize('u6d.boq.pre.mWt', "Weight [kg]"), value: formatScalar(tot.weight) },
			],
			tables: [{
				id: 'precast',
				title: localize('u6d.boq.pre.tab', "Precast Piece Schedule"),
				columns: [
					{ key: 'mark', title: localize('u6d.boq.pre.colMark', "Mark") },
					{ key: 'type', title: localize('u6d.boq.pre.colType', "Type") },
					{ key: 'count', title: localize('u6d.boq.pre.colCnt', "Count"), type: 'number', align: 'right' },
					{ key: 'volumeM3', title: localize('u6d.boq.pre.colVol', "Concrete [m³]"), type: 'number', align: 'right' },
					{ key: 'weightKg', title: localize('u6d.boq.pre.colWt', "Weight [kg]"), type: 'number', align: 'right' },
					{ key: 'barsKg', title: localize('u6d.boq.pre.colBars', "Rebar [kg]"), type: 'number', align: 'right' },
					{ key: 'mouldM2', title: localize('u6d.boq.pre.colMould', "Mould [m²]"), type: 'number', align: 'right' },
				],
				rows,
				emptyMessage: localize('u6d.boq.pre.empty', "No precast concrete elements found in 06 BIM."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.takeoffSummary',
	title: localize('u6d.boq.to.title', "2D PDF Quantity Takeoff Summary"),
	part: 'boq',
	icon: Codicon.filePdf,
	help: localize('u6d.boq.to.help', "Reads 10 BOQ/takeoff.json and measures every traced 2D PDF length, area and count item with mapped bill lines."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('boq/takeoffSummary', { projectRoot: ctx.project!.root.fsPath }));
		const itemRows: DataPanelRow[] = asArray(raw.items).map(asBag).map(it => ({
			id: str(it.id),
			quantity: it.problem ? str(it.problem) : formatScalar(it.quantity),
			unit: str(it.unit, '–'),
			status: it.problem ? 'Fail' : 'Pass',
		}));
		const lineRows: DataPanelRow[] = asArray(raw.lines).map(asBag).map(l => ({
			code: str(l.code),
			description: str(l.description),
			quantity: num(l.quantity) ?? 0,
			unit: str(l.unit),
		}));
		return {
			metrics: [
				{ label: localize('u6d.boq.to.mItems', "Traced Items"), value: String(itemRows.length) },
				{ label: localize('u6d.boq.to.mLines', "Bill Lines"), value: String(lineRows.length) },
			],
			tables: [
				{
					id: 'items',
					title: localize('u6d.boq.to.itemTab', "2D PDF Measured Items"),
					columns: [
						{ key: 'id', title: localize('u6d.boq.to.colId', "Item ID") },
						{ key: 'quantity', title: localize('u6d.boq.to.colQty', "Quantity / Issue") },
						{ key: 'unit', title: localize('u6d.boq.to.colUnit', "Unit") },
						{ key: 'status', title: localize('u6d.boq.to.colStat', "Status"), type: 'status' },
					],
					rows: itemRows,
					emptyMessage: localize('u6d.boq.to.empty', "No 10 BOQ/takeoff.json file found."),
				},
				{
					id: 'lines',
					title: localize('u6d.boq.to.lineTab', "Mapped Bill Lines"),
					columns: [
						{ key: 'code', title: localize('u6d.boq.to.colCode', "Code") },
						{ key: 'description', title: localize('u6d.boq.to.colDesc', "Description") },
						{ key: 'quantity', title: localize('u6d.boq.to.colLQty', "Quantity"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u6d.boq.to.colLUnit', "Unit") },
					],
					rows: lineRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerBoqPanel({
	id: 'saengine.boq.pdfCalibrate',
	title: localize('u6d.boq.cal.title', "2D PDF Sheet Scale Calibration Calculator"),
	part: 'boq',
	icon: Codicon.compass,
	help: localize('u6d.boq.cal.help', "Computes exact true-to-paper scale ratio (1:N) from two picked PDF paper coordinates [mm] and the known true dimension [mm]."),
	fields: [
		{ key: 'ax', label: localize('u6d.boq.cal.ax', "Point A Paper X [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'ay', label: localize('u6d.boq.cal.ay', "Point A Paper Y [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'bx', label: localize('u6d.boq.cal.bx', "Point B Paper X [mm]"), type: 'number', defaultValue: 100 },
		{ key: 'by', label: localize('u6d.boq.cal.by', "Point B Paper Y [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'lengthMm', label: localize('u6d.boq.cal.len', "Known True Length [mm]"), type: 'number', defaultValue: 10000, min: 1 },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('office/calibrate', {
			a: [Number(values.ax) || 0, Number(values.ay) || 0],
			b: [Number(values.bx) ?? 100, Number(values.by) || 0],
			length: Number(values.lengthMm) || 10000,
		}));
		const scale = num(raw.scale);
		const rows: DataPanelRow[] = [
			{ parameter: 'Scale Factor (true mm / paper mm)', value: scale !== undefined ? scale.toFixed(4) : '–' },
			{ parameter: 'Drawing Scale Ratio', value: scale !== undefined ? `1:${Math.round(scale)}` : '–' },
			{ parameter: 'Point A [mm]', value: `[${formatScalar(values.ax)}, ${formatScalar(values.ay)}]` },
			{ parameter: 'Point B [mm]', value: `[${formatScalar(values.bx)}, ${formatScalar(values.by)}]` },
			{ parameter: 'True Length [mm]', value: formatScalar(values.lengthMm) },
		];
		return {
			metrics: [
				{ label: localize('u6d.boq.cal.mScale', "Drawing Scale"), value: scale !== undefined ? `1:${Math.round(scale)}` : '–' },
			],
			tables: [{
				id: 'calibration',
				title: localize('u6d.boq.cal.tab', "Calibration Result"),
				columns: [
					{ key: 'parameter', title: localize('u6d.boq.cal.colParam', "Parameter") },
					{ key: 'value', title: localize('u6d.boq.cal.colVal', "Value") },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion
