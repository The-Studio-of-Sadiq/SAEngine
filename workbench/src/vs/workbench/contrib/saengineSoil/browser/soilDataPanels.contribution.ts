/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
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

function registerSoilPanel(descriptor: IEngineDataPanelDescriptor): void {
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

function openSoilEditorAction(label: string): readonly IDataPanelAction[] {
	return [{
		id: 'openSoilEditor',
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand('saengine.project.showSoil'),
	}];
}

//#region Investigation & Stratigraphy

registerSoilPanel({
	id: 'saengine.soil.investigationCheck',
	title: localize('u6d.soil.inv.title', "Investigation Adequacy"),
	part: 'soil',
	icon: Codicon.checklist,
	help: localize('u6d.soil.inv.help', "Checks borehole count, spatial pattern, spacing, exploration depth, deep borings, rock cores and geo-hazards against the active code pack."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const inv = asBag(raw.investigation);
		const checks = asArray(inv.checks).map(asBag);
		const rows: DataPanelRow[] = checks.map(c => ({
			item: str(c.item || c.id),
			required: str(c.required, '–'),
			provided: str(c.provided, '–'),
			status: str(c.status, 'ok') === 'ok' ? 'Pass' : str(c.status) === 'fail' ? 'Fail' : 'Warn',
			clause: str(c.clause, '–'),
			note: str(c.note, '–'),
		}));
		const failCount = rows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u6d.soil.inv.mCount', "Checks"), value: String(rows.length) },
				{ label: localize('u6d.soil.inv.mFail', "Failing"), value: String(failCount), tone: failCount ? 'fail' : 'ok' },
				{ label: localize('u6d.soil.inv.mCode', "Code"), value: str(inv.code, '–') },
			],
			tables: [{
				id: 'checks',
				title: localize('u6d.soil.inv.tab', "Site Investigation Checks"),
				columns: [
					{ key: 'item', title: localize('u6d.soil.inv.colItem', "Criterion") },
					{ key: 'required', title: localize('u6d.soil.inv.colReq', "Required") },
					{ key: 'provided', title: localize('u6d.soil.inv.colProv', "Provided") },
					{ key: 'status', title: localize('u6d.soil.inv.colStatus', "Status"), type: 'status' },
					{ key: 'clause', title: localize('u6d.soil.inv.colClause', "Clause") },
					{ key: 'note', title: localize('u6d.soil.inv.colNote', "Note") },
				],
				rows,
			}],
			notes: [...asStrings(inv.notes), ...asStrings(raw.notes)],
			problems: [...asStrings(raw.problems), ...asStrings(raw.warnings)],
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.stratigraphySummary',
	title: localize('u6d.soil.strata.title', "3D Stratigraphy Units"),
	part: 'soil',
	icon: Codicon.layers,
	help: localize('u6d.soil.strata.help', "Correlated subsurface strata units across boreholes, unit elevations, water table surfaces and fence sections."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const strat = asBag(raw.stratigraphy);
		const units = asArray(strat.units).map(asBag);
		const bhs = asArray(strat.boreholes).map(asBag);
		const fences = asArray(strat.fences).map(asBag);

		const unitRows: DataPanelRow[] = units.map(u => ({
			id: str(u.id),
			key: str(u.key),
			soilType: str(u.soilType),
		}));
		const bhStrataRows: DataPanelRow[] = bhs.flatMap(bh =>
			asArray(bh.strata).map(asBag).map(s => ({
				borehole: str(bh.id),
				unit: str(s.unit),
				topM: num(s.top) ?? 0,
				bottomM: num(s.bottom) ?? 0,
				groundM: num(bh.ground) ?? 0,
				waterM: num(bh.water) ?? '–',
			}))
		);

		return {
			metrics: [
				{ label: localize('u6d.soil.strata.mUnits', "Correlated Units"), value: String(unitRows.length) },
				{ label: localize('u6d.soil.strata.mBh', "Logged Boreholes"), value: String(bhs.length) },
				{ label: localize('u6d.soil.strata.mFences', "Fence Sections"), value: String(fences.length) },
			],
			tables: [
				{
					id: 'units',
					title: localize('u6d.soil.strata.unitsTab', "Stratigraphic Units"),
					columns: [
						{ key: 'id', title: localize('u6d.soil.strata.colId', "Unit") },
						{ key: 'key', title: localize('u6d.soil.strata.colKey', "Correlation Key") },
						{ key: 'soilType', title: localize('u6d.soil.strata.colType', "Soil Type") },
					],
					rows: unitRows,
				},
				{
					id: 'boreholes',
					title: localize('u6d.soil.strata.bhTab', "Borehole Elevations & Strata"),
					columns: [
						{ key: 'borehole', title: localize('u6d.soil.strata.colBh', "Borehole") },
						{ key: 'unit', title: localize('u6d.soil.strata.colUnit', "Unit") },
						{ key: 'topM', title: localize('u6d.soil.strata.colTop', "Top Elev. [m]"), type: 'number', align: 'right' },
						{ key: 'bottomM', title: localize('u6d.soil.strata.colBot', "Bottom Elev. [m]"), type: 'number', align: 'right' },
						{ key: 'groundM', title: localize('u6d.soil.strata.colGnd', "Ground [m]"), type: 'number', align: 'right' },
						{ key: 'waterM', title: localize('u6d.soil.strata.colWat', "Water [m]"), type: 'number', align: 'right' },
					],
					rows: bhStrataRows,
				},
			],
			notes: [...asStrings(strat.notes), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Lab Tests & Profiles

registerSoilPanel({
	id: 'saengine.soil.sptProfile',
	title: localize('u6d.soil.spt.title', "SPT Profile & Layer Parameters"),
	part: 'soil',
	icon: Codicon.listFlat,
	help: localize('u6d.soil.spt.help', "Reports corrected SPT N60, (N1)60, unit weight, friction angle, undrained shear strength cu, and layer behaviour per borehole."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const boreholes = asArray(raw.boreholes).map(asBag);
		const rows: DataPanelRow[] = boreholes.flatMap(bh =>
			asArray(bh.layers).map(asBag).map(l => ({
				borehole: str(bh.id),
				topM: num(l.top) ?? 0,
				bottomM: num(l.bottom) ?? 0,
				soilType: str(l.soilType),
				behaviour: str(l.behaviour),
				gamma: num(l.gamma) ?? '–',
				nField: num(l.nField) ?? '–',
				n60: num(l.n60) ?? '–',
				n160: num(l.n160) ?? '–',
				phi: num(l.phi) ?? '–',
				cu: num(l.cu) ?? '–',
			}))
		);
		return {
			metrics: [
				{ label: localize('u6d.soil.spt.mBh', "Boreholes"), value: String(boreholes.length) },
				{ label: localize('u6d.soil.spt.mLayers', "Soil Layers"), value: String(rows.length) },
			],
			tables: [{
				id: 'layers',
				title: localize('u6d.soil.spt.tab', "Borehole Layer Parameters"),
				columns: [
					{ key: 'borehole', title: localize('u6d.soil.spt.colBh', "Borehole") },
					{ key: 'topM', title: localize('u6d.soil.spt.colTop', "Top [m]"), type: 'number', align: 'right' },
					{ key: 'bottomM', title: localize('u6d.soil.spt.colBot', "Bottom [m]"), type: 'number', align: 'right' },
					{ key: 'soilType', title: localize('u6d.soil.spt.colType', "Soil") },
					{ key: 'behaviour', title: localize('u6d.soil.spt.colBeh', "Behaviour") },
					{ key: 'gamma', title: localize('u6d.soil.spt.colGam', "γ [kN/m³]"), type: 'number', align: 'right' },
					{ key: 'nField', title: localize('u6d.soil.spt.colNf', "N"), type: 'number', align: 'right' },
					{ key: 'n60', title: localize('u6d.soil.spt.colN60', "N60"), type: 'number', align: 'right' },
					{ key: 'n160', title: localize('u6d.soil.spt.colN160', "(N1)60"), type: 'number', align: 'right' },
					{ key: 'phi', title: localize('u6d.soil.spt.colPhi', "φ' [°]"), type: 'number', align: 'right' },
					{ key: 'cu', title: localize('u6d.soil.spt.colCu', "cu [kPa]"), type: 'number', align: 'right' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.labSummary',
	title: localize('u6d.soil.lab.title', "Laboratory Tests & USCS Classification"),
	part: 'soil',
	icon: Codicon.beaker,
	help: localize('u6d.soil.lab.help', "Summarizes grading, Atterberg limits, USCS classification, direct shear, triaxial and consolidation lab results from borehole samples."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const boreholes = asArray(raw.boreholes).map(asBag);
		const rows: DataPanelRow[] = boreholes.flatMap(bh =>
			asArray(bh.lab).map(asBag).map(s => {
				const uscs = asBag(s.uscs);
				return {
					borehole: str(bh.id),
					sample: str(s.sample, '–'),
					depthMm: num(s.depth) ?? 0,
					uscs: str(uscs.symbol, '–'),
					ll: num(s.ll) ?? '–',
					pi: num(s.pi) ?? '–',
					finesPct: num(s.fines) ?? '–',
					cc: num(s.cc) ?? '–',
					e0: num(s.e0) ?? '–',
					summary: str(s.summary, '–'),
				};
			})
		);
		return {
			metrics: [
				{ label: localize('u6d.soil.lab.mSamples', "Lab Samples"), value: String(rows.length) },
				{ label: localize('u6d.soil.lab.mBh', "Boreholes"), value: String(boreholes.length) },
			],
			tables: [{
				id: 'lab',
				title: localize('u6d.soil.lab.tab', "Sample Lab Summary"),
				columns: [
					{ key: 'borehole', title: localize('u6d.soil.lab.colBh', "Borehole") },
					{ key: 'sample', title: localize('u6d.soil.lab.colSample', "Sample") },
					{ key: 'depthMm', title: localize('u6d.soil.lab.colDepth', "Depth [mm]"), type: 'number', align: 'right' },
					{ key: 'uscs', title: localize('u6d.soil.lab.colUscs', "USCS") },
					{ key: 'll', title: localize('u6d.soil.lab.colLl', "LL [%]"), type: 'number', align: 'right' },
					{ key: 'pi', title: localize('u6d.soil.lab.colPi', "PI [%]"), type: 'number', align: 'right' },
					{ key: 'finesPct', title: localize('u6d.soil.lab.colFines', "Fines [%]"), type: 'number', align: 'right' },
					{ key: 'cc', title: localize('u6d.soil.lab.colCc', "Cc"), type: 'number', align: 'right' },
					{ key: 'e0', title: localize('u6d.soil.lab.colE0', "e0"), type: 'number', align: 'right' },
					{ key: 'summary', title: localize('u6d.soil.lab.colSum', "Summary") },
				],
				rows,
				emptyMessage: localize('u6d.soil.lab.empty', "No borehole lab samples entered yet."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.pileParams',
	title: localize('u6d.soil.pileParams.title', "Pile Layer Parameters & Subgrade Modulus"),
	part: 'soil',
	icon: Codicon.arrowDown,
	help: localize('u6d.soil.pileParams.help', "Reports shaft adhesion alpha, beta factor, unit skin friction, end bearing and Winkler subgrade modulus ks per soil layer."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const boreholes = asArray(raw.boreholes).map(asBag);
		const rows: DataPanelRow[] = boreholes.flatMap(bh =>
			asArray(bh.pile).map(asBag).map(p => ({
				borehole: str(bh.id),
				topM: num(p.top) ?? 0,
				bottomM: num(p.bottom) ?? 0,
				soilType: str(p.soilType),
				ksBorehole: num(bh.ks) ?? '–',
				fsKpa: num(p.fs) ?? num(p.skin) ?? '–',
				qbKpa: num(p.qb) ?? num(p.base) ?? '–',
				alpha: num(p.alpha) ?? '–',
				beta: num(p.beta) ?? '–',
				note: str(p.note, '–'),
			}))
		);
		return {
			metrics: [
				{ label: localize('u6d.soil.pileParams.mRows', "Layer Entries"), value: String(rows.length) },
				{ label: localize('u6d.soil.pileParams.mBh', "Boreholes"), value: String(boreholes.length) },
			],
			tables: [{
				id: 'pileParams',
				title: localize('u6d.soil.pileParams.tab', "Pile Shaft & Base Parameters"),
				columns: [
					{ key: 'borehole', title: localize('u6d.soil.pileParams.colBh', "Borehole") },
					{ key: 'topM', title: localize('u6d.soil.pileParams.colTop', "Top [m]"), type: 'number', align: 'right' },
					{ key: 'bottomM', title: localize('u6d.soil.pileParams.colBot', "Bottom [m]"), type: 'number', align: 'right' },
					{ key: 'soilType', title: localize('u6d.soil.pileParams.colSoil', "Soil") },
					{ key: 'fsKpa', title: localize('u6d.soil.pileParams.colFs', "Skin fs [kPa]"), type: 'number', align: 'right' },
					{ key: 'qbKpa', title: localize('u6d.soil.pileParams.colQb', "Base qb [kPa]"), type: 'number', align: 'right' },
					{ key: 'ksBorehole', title: localize('u6d.soil.pileParams.colKs', "ks [kN/m³]"), type: 'number', align: 'right' },
					{ key: 'note', title: localize('u6d.soil.pileParams.colNote', "Note") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Bearing & Settlement

registerSoilPanel({
	id: 'saengine.soil.bearingCalc',
	title: localize('u6d.soil.bearingCalc.title', "Allowable Bearing Pressure Calculator"),
	part: 'soil',
	icon: Codicon.dashboard,
	help: localize('u6d.soil.bearingCalc.help', "Computes net allowable bearing pressure qa (shear failure vs settlement limit) for a footing at plan coordinates (x, y) and founding level."),
	fields: [
		{ key: 'x', label: localize('u6d.soil.bc.x', "Plan X [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'y', label: localize('u6d.soil.bc.y', "Plan Y [mm]"), type: 'number', defaultValue: 0 },
		{ key: 'foundingLevel', label: localize('u6d.soil.bc.fl', "Founding Level [mm]"), type: 'number', defaultValue: -1500 },
		{ key: 'b', label: localize('u6d.soil.bc.b', "Width B [mm]"), type: 'number', defaultValue: 2000, min: 300 },
		{ key: 'l', label: localize('u6d.soil.bc.l', "Length L [mm]"), type: 'number', defaultValue: 2000, min: 300 },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('soil/bearingCheck', {
			projectRoot: ctx.project!.root.fsPath,
			x: Number(values.x) || 0,
			y: Number(values.y) || 0,
			foundingLevel: Number(values.foundingLevel ?? -1500),
			b: Number(values.b) || 2000,
			l: Number(values.l) || 2000,
		}));
		const qa = num(raw.qa_kpa);
		const rows: DataPanelRow[] = [
			{ parameter: localize('u6d.soil.bc.rBh', "Governing Borehole"), value: str(raw.borehole, '–') },
			{ parameter: localize('u6d.soil.bc.rQa', "Allowable Bearing qa [kPa]"), value: qa !== undefined ? qa.toFixed(1) : '–' },
			{ parameter: localize('u6d.soil.bc.rShear', "Shear Bearing qa,shear [kPa]"), value: formatScalar(raw.qa_shear) },
			{ parameter: localize('u6d.soil.bc.rSett', "Settlement Bearing qa,sett [kPa]"), value: formatScalar(raw.qa_settlement) },
			{ parameter: localize('u6d.soil.bc.rDf', "Embedment Df [mm]"), value: formatScalar(raw.Df) },
			{ parameter: localize('u6d.soil.bc.rMethod', "Method"), value: str(raw.method, '–') },
			{ parameter: localize('u6d.soil.bc.rNote', "Basis"), value: str(raw.note, '–') },
		];
		return {
			metrics: [
				{ label: localize('u6d.soil.bc.mQa', "Allowable qa"), value: qa !== undefined ? `${qa.toFixed(1)} kPa` : '–', tone: qa !== undefined ? 'ok' : 'warn' },
				{ label: localize('u6d.soil.bc.mBh', "Borehole"), value: str(raw.borehole, '–') },
			],
			tables: [{
				id: 'bearing',
				title: localize('u6d.soil.bc.tab', "Bearing Pressure Result"),
				columns: [
					{ key: 'parameter', title: localize('u6d.soil.bc.colParam', "Parameter") },
					{ key: 'value', title: localize('u6d.soil.bc.colVal', "Value") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.bearingTable',
	title: localize('u6d.soil.bearingTbl.title', "Site Allowable Bearing Table"),
	part: 'soil',
	icon: Codicon.table,
	help: localize('u6d.soil.bearingTbl.help', "Tabulates net allowable bearing pressure qa across standard footing widths B and embedment depths Df for every borehole."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const boreholes = asArray(raw.boreholes).map(asBag);
		const rows: DataPanelRow[] = boreholes.flatMap(bh =>
			asArray(asBag(bh.bearing).table).map(asBag).map(r => ({
				borehole: str(bh.id),
				bMm: num(r.B) ?? 0,
				dfMm: num(r.Df) ?? 0,
				qaShear: num(r.qa_shear) ?? '–',
				qaSettlement: num(r.qa_settlement) ?? '–',
				qa: num(r.qa) ?? '–',
				governs: str(r.governs, '–'),
			}))
		);
		return {
			metrics: [
				{ label: localize('u6d.soil.bearingTbl.mRows', "Table Entries"), value: String(rows.length) },
				{ label: localize('u6d.soil.bearingTbl.mBh', "Boreholes"), value: String(boreholes.length) },
			],
			tables: [{
				id: 'bearingTable',
				title: localize('u6d.soil.bearingTbl.tab', "Allowable Bearing Pressure Matrix [kPa]"),
				columns: [
					{ key: 'borehole', title: localize('u6d.soil.bearingTbl.colBh', "Borehole") },
					{ key: 'bMm', title: localize('u6d.soil.bearingTbl.colB', "Width B [mm]"), type: 'number', align: 'right' },
					{ key: 'dfMm', title: localize('u6d.soil.bearingTbl.colDf', "Depth Df [mm]"), type: 'number', align: 'right' },
					{ key: 'qaShear', title: localize('u6d.soil.bearingTbl.colShear', "qa,shear [kPa]"), type: 'number', align: 'right' },
					{ key: 'qaSettlement', title: localize('u6d.soil.bearingTbl.colSett', "qa,sett [kPa]"), type: 'number', align: 'right' },
					{ key: 'qa', title: localize('u6d.soil.bearingTbl.colQa', "Allowable qa [kPa]"), type: 'number', align: 'right' },
					{ key: 'governs', title: localize('u6d.soil.bearingTbl.colGov', "Governs") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.settlementCalc',
	title: localize('u6d.soil.sett.title', "Footing Settlement Calculator"),
	part: 'soil',
	icon: Codicon.graphLine,
	help: localize('u6d.soil.sett.help', "Computes immediate elastic (Schmertmann / Steinbrenner) and 1D primary consolidation settlement against code permissible limits."),
	fields: [
		{ key: 'borehole', label: localize('u6d.soil.sett.bh', "Borehole"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.soil.firstBh', "First Borehole") }] },
		{ key: 'foundation', label: localize('u6d.soil.sett.type', "Foundation Type"), type: 'select', defaultValue: 'isolated', options: [{ value: 'isolated', label: localize('u6d.soil.sett.isolated', "Isolated Footing") }, { value: 'raft', label: localize('u6d.soil.sett.raft', "Raft Foundation") }] },
		{ key: 'b', label: localize('u6d.soil.sett.b', "Width B [mm]"), type: 'number', defaultValue: 2000, min: 300 },
		{ key: 'l', label: localize('u6d.soil.sett.l', "Length L [mm]"), type: 'number', defaultValue: 2000, min: 300 },
		{ key: 'df', label: localize('u6d.soil.sett.df', "Embedment Df [mm]"), type: 'number', defaultValue: 1500, min: 0 },
		{ key: 'q', label: localize('u6d.soil.sett.q', "Net Pressure q [kPa]"), type: 'number', defaultValue: 150, min: 1 },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const res = asBag(await ctx.engineRequest('soil/settlementCheck', { projectRoot: ctx.project.root.fsPath }));
		const bhs = asStrings(res.availableBoreholes);
		if (!bhs.length) {
			return undefined;
		}
		return {
			options: { borehole: bhs.map(b => ({ value: b, label: b })) },
			values: { borehole: bhs[0] },
		};
	},
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('soil/settlementCheck', {
			projectRoot: ctx.project!.root.fsPath,
			borehole: String(values.borehole || '') || undefined,
			b: Number(values.b) || 2000,
			l: Number(values.l) || 2000,
			df: Number(values.df ?? 1500),
			q: Number(values.q) || 150,
			foundation: String(values.foundation || 'isolated'),
		}));
		const total = num(raw.total);
		const perm = asBag(raw.permissible);
		const permVal = num(perm.total) ?? num(perm.limit);
		const rows: DataPanelRow[] = [
			{ component: localize('u6d.soil.sett.imm', "Immediate Settlement"), valueMm: num(raw.immediate) ?? '–' },
			{ component: localize('u6d.soil.sett.cons', "Consolidation Settlement"), valueMm: num(raw.consolidation) ?? '–' },
			{ component: localize('u6d.soil.sett.tot', "Total Settlement"), valueMm: total ?? '–' },
			{ component: localize('u6d.soil.sett.perm', "Code Permissible Limit"), valueMm: permVal ?? formatScalar(perm.text) },
		];
		return {
			metrics: [
				{ label: localize('u6d.soil.sett.mTot', "Total Settlement"), value: total !== undefined ? `${total.toFixed(1)} mm` : '–', tone: total !== undefined && permVal !== undefined && total > permVal ? 'fail' : 'ok' },
				{ label: localize('u6d.soil.sett.mBh', "Borehole"), value: str(raw.borehole, '–') },
			],
			tables: [{
				id: 'settlement',
				title: localize('u6d.soil.sett.tab', "Settlement Breakdown"),
				columns: [
					{ key: 'component', title: localize('u6d.soil.sett.colComp', "Component") },
					{ key: 'valueMm', title: localize('u6d.soil.sett.colVal', "Value [mm]"), type: 'number', align: 'right' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.characteristicBearing',
	title: localize('u6d.soil.cb.title', "Characteristic Bearing & Layerwise Settlement"),
	part: 'soil',
	icon: Codicon.symbolRuler,
	help: localize('u6d.soil.cb.help', "Applies width/depth characteristic bearing corrections (fa from fak) and layerwise settlement summation when provided by the active code pack."),
	fields: [
		{ key: 'borehole', label: localize('u6d.soil.cb.bh', "Borehole"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.soil.firstBh', "First Borehole") }] },
		{ key: 'fak', label: localize('u6d.soil.cb.fak', "Characteristic Bearing fak [kPa]"), type: 'number', defaultValue: 150, min: 1 },
		{ key: 'b', label: localize('u6d.soil.cb.b', "Width b [m]"), type: 'number', defaultValue: 2.0, min: 0.3, step: '0.1' },
		{ key: 'l', label: localize('u6d.soil.cb.l', "Length l [m]"), type: 'number', defaultValue: 2.0, min: 0.3, step: '0.1' },
		{ key: 'df', label: localize('u6d.soil.cb.df', "Depth d [m]"), type: 'number', defaultValue: 1.5, min: 0, step: '0.1' },
		{ key: 'q', label: localize('u6d.soil.cb.q', "Net Pressure q [kPa]"), type: 'number', defaultValue: 150, min: 1 },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const res = asBag(await ctx.engineRequest('soil/characteristicBearing', { projectRoot: ctx.project.root.fsPath }));
		const bhs = asStrings(res.availableBoreholes);
		if (!bhs.length) {
			return undefined;
		}
		return {
			options: { borehole: bhs.map(b => ({ value: b, label: b })) },
			values: { borehole: bhs[0] },
		};
	},
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('soil/characteristicBearing', {
			projectRoot: ctx.project!.root.fsPath,
			borehole: String(values.borehole || '') || undefined,
			fak: Number(values.fak) || 150,
			b: Number(values.b) || 2.0,
			l: Number(values.l) || 2.0,
			df: Number(values.df ?? 1.5),
			q: Number(values.q) || 150,
		}));
		const fa = num(raw.faKpa);
		const lw = asBag(raw.layerwise);
		const rows: DataPanelRow[] = [
			{ item: localize('u6d.soil.cb.rFak', "Input fak"), value: `${formatScalar(raw.fakKpa)} kPa` },
			{ item: localize('u6d.soil.cb.rFa', "Corrected fa"), value: fa !== undefined ? `${fa.toFixed(1)} kPa` : 'Not covered by pack' },
			{ item: localize('u6d.soil.cb.rLw', "Layerwise Settlement"), value: num(lw.total) !== undefined ? `${num(lw.total)!.toFixed(1)} mm` : 'Not covered by pack' },
			{ item: localize('u6d.soil.cb.rNote', "Basis"), value: str(raw.correctionNote, '–') },
		];
		return {
			metrics: [
				{ label: localize('u6d.soil.cb.mFa', "Corrected fa"), value: fa !== undefined ? `${fa.toFixed(1)} kPa` : 'N/A', tone: fa !== undefined ? 'ok' : 'neutral' },
				{ label: localize('u6d.soil.cb.mBh', "Borehole"), value: str(raw.borehole, '–') },
			],
			tables: [{
				id: 'charBearing',
				title: localize('u6d.soil.cb.tab', "Characteristic Bearing Summary"),
				columns: [
					{ key: 'item', title: localize('u6d.soil.cb.colItem', "Parameter") },
					{ key: 'value', title: localize('u6d.soil.cb.colVal', "Result") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.sources',
	title: localize('u6d.soil.sources.title', "Active Site Class & Bearing Sources"),
	part: 'soil',
	icon: Codicon.info,
	help: localize('u6d.soil.sources.help', "Shows whether seismic site class and footing bearing capacity come from borehole logs in 01 Soil Report or manual overrides in 02 Project Settings."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/sourcesCheck', { projectRoot: ctx.project!.root.fsPath }));
		const site = asBag(raw.site);
		const soil = asBag(raw.soil);
		const bearing = asBag(raw.bearing);
		const rows: DataPanelRow[] = [
			{ setting: localize('u6d.soil.src.siteCls', "Active Site Class"), value: str(site.class, '–'), source: str(site.source, '–'), detail: str(site.label || site.note) },
			{ setting: localize('u6d.soil.src.soilCls', "Soil Report Site Class"), value: str(soil.class, '–'), source: `${str(soil.boreholes, '0')} boreholes`, detail: str(soil.label || soil.note) },
			{ setting: localize('u6d.soil.src.bearing', "Allowable Bearing Source"), value: bearing.override ? `${str(bearing.override)} kPa` : str(bearing.source, '–'), source: str(bearing.source, '–'), detail: str(bearing.note) },
		];
		return {
			metrics: [
				{ label: localize('u6d.soil.src.mCls', "Site Class"), value: str(site.class, '–') },
				{ label: localize('u6d.soil.src.mSrc', "Bearing Source"), value: str(bearing.source, '–') },
			],
			tables: [{
				id: 'sources',
				title: localize('u6d.soil.src.tab', "Geotechnical Parameter Sources"),
				columns: [
					{ key: 'setting', title: localize('u6d.soil.src.colSet', "Parameter") },
					{ key: 'value', title: localize('u6d.soil.src.colVal', "Value") },
					{ key: 'source', title: localize('u6d.soil.src.colSrc', "Source") },
					{ key: 'detail', title: localize('u6d.soil.src.colDet', "Detail") },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Seismic & Liquefaction

registerSoilPanel({
	id: 'saengine.soil.siteClass',
	title: localize('u6d.soil.siteClass.title', "Site Class Report"),
	part: 'soil',
	icon: Codicon.pulse,
	help: localize('u6d.soil.siteClass.help', "Reports seismic site classification per borehole (harmonic mean N̄ and su over top 30 m, soft clay and liquefaction flags) and governing project class."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const projectSite = asBag(raw.siteClass);
		const boreholes = asArray(raw.boreholes).map(asBag);
		const rows: DataPanelRow[] = boreholes.map(bh => {
			const sc = asBag(bh.siteClass);
			return {
				borehole: str(bh.id),
				siteClass: str(sc.class, '–'),
				nBar: num(sc.nBar) ?? num(sc.n) ?? '–',
				suBar: num(sc.suBar) ?? num(sc.su) ?? '–',
				softClay: sc.softClay ? 'Yes' : 'No',
				liquefiable: sc.liquefiable ? 'Yes' : 'No',
				note: str(sc.label || sc.note, '–'),
			};
		});
		return {
			metrics: [
				{ label: localize('u6d.soil.sc.mGov', "Governing Site Class"), value: str(projectSite.class, '–'), tone: projectSite.class ? 'ok' : 'warn' },
				{ label: localize('u6d.soil.sc.mGovBh', "Governing Borehole"), value: str(projectSite.governing, '–') },
			],
			tables: [{
				id: 'siteClass',
				title: localize('u6d.soil.sc.tab', "Per-Borehole Site Classification"),
				columns: [
					{ key: 'borehole', title: localize('u6d.soil.sc.colBh', "Borehole") },
					{ key: 'siteClass', title: localize('u6d.soil.sc.colCls', "Site Class") },
					{ key: 'nBar', title: localize('u6d.soil.sc.colN', "N̄"), type: 'number', align: 'right' },
					{ key: 'suBar', title: localize('u6d.soil.sc.colSu', "s̄u [kPa]"), type: 'number', align: 'right' },
					{ key: 'softClay', title: localize('u6d.soil.sc.colSoft', "Soft Clay") },
					{ key: 'liquefiable', title: localize('u6d.soil.sc.colLiq', "Liquefiable") },
					{ key: 'note', title: localize('u6d.soil.sc.colNote', "Summary") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.liquefaction',
	title: localize('u6d.soil.liq.title', "Liquefaction Screening (SPT)"),
	part: 'soil',
	icon: Codicon.warning,
	help: localize('u6d.soil.liq.help', "Evaluates cyclic stress ratio (CSR), cyclic resistance ratio (CRR), factor of safety (FS) against liquefaction, and LPI per SPT depth."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const boreholes = asArray(raw.boreholes).map(asBag);
		const rows: DataPanelRow[] = boreholes.flatMap(bh => {
			const liq = asBag(bh.liquefaction);
			const pts = asArray(liq.points).map(asBag);
			return pts.map(pt => {
				const fs = num(pt.fs);
				return {
					borehole: str(bh.id),
					depthM: num(pt.depth) ?? num(pt.z) ?? 0,
					n160cs: num(pt.n160cs) ?? '–',
					csr: num(pt.csr) ?? '–',
					crr: num(pt.crr) ?? '–',
					fs: fs ?? '–',
					status: pt.liquefiable || (fs !== undefined && fs < 1.0) ? 'Fail' : 'Pass',
				};
			});
		});
		const failing = rows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u6d.soil.liq.mAmax', "Peak Ground Accel. amax"), value: num(raw.amax) !== undefined ? `${num(raw.amax)!.toFixed(3)} g` : '–' },
				{ label: localize('u6d.soil.liq.mPts', "Checked Depths"), value: String(rows.length) },
				{ label: localize('u6d.soil.liq.mLiq', "Liquefiable Points"), value: String(failing), tone: failing ? 'fail' : 'ok' },
			],
			tables: [{
				id: 'liquefaction',
				title: localize('u6d.soil.liq.tab', "SPT Liquefaction Screening"),
				columns: [
					{ key: 'borehole', title: localize('u6d.soil.liq.colBh', "Borehole") },
					{ key: 'depthM', title: localize('u6d.soil.liq.colDepth', "Depth [m]"), type: 'number', align: 'right' },
					{ key: 'n160cs', title: localize('u6d.soil.liq.colN', "(N1)60cs"), type: 'number', align: 'right' },
					{ key: 'csr', title: localize('u6d.soil.liq.colCsr', "CSR"), type: 'number', align: 'right' },
					{ key: 'crr', title: localize('u6d.soil.liq.colCrr', "CRR"), type: 'number', align: 'right' },
					{ key: 'fs', title: localize('u6d.soil.liq.colFs', "FS"), type: 'number', align: 'right' },
					{ key: 'status', title: localize('u6d.soil.liq.colStatus', "Status"), type: 'status' },
				],
				rows,
				emptyMessage: localize('u6d.soil.liq.empty', "No saturated granular SPT intervals requiring liquefaction screening."),
			}],
			notes: [str(raw.amaxNote), ...asStrings(raw.notes)].filter(Boolean),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.specialSoils',
	title: localize('u6d.soil.spec.title', "Problem & Special Soils Audit"),
	part: 'soil',
	icon: Codicon.shield,
	help: localize('u6d.soil.spec.help', "Screens borehole samples and layers for organic, expansive, collapsible, dispersive, and very soft clay soils."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const boreholes = asArray(raw.boreholes).map(asBag);
		const sampleRows: DataPanelRow[] = boreholes.flatMap(bh => {
			const ps = asBag(bh.problemSoils);
			return asArray(ps.samples).map(asBag).map(s => ({
				borehole: str(bh.id),
				sample: str(s.sample, '–'),
				depthMm: num(s.depth) ?? 0,
				organic: s.organic ? formatScalar(asBag(s.organic).kind || asBag(s.organic).note || 'Flagged') : 'No',
				expansive: s.expansive ? formatScalar(asBag(s.expansive).potential || asBag(s.expansive).note || 'Flagged') : 'No',
				collapsible: s.collapsible ? formatScalar(asBag(s.collapsible).note || 'Flagged') : 'No',
				dispersive: s.dispersive ? formatScalar(asBag(s.dispersive).note || 'Flagged') : 'No',
			}));
		});
		const softRows: DataPanelRow[] = boreholes.flatMap(bh => {
			const ps = asBag(bh.problemSoils);
			return asArray(ps.softClay).map(asBag).map(c => ({
				borehole: str(bh.id),
				layer: (num(c.layer) ?? 0) + 1,
				topMm: num(c.top) ?? 0,
				bottomMm: num(c.bottom) ?? 0,
				consistency: str(c.consistency, '–'),
				nField: num(c.N) ?? '–',
				cu: num(c.cu) ?? '–',
				clause: str(c.clause, '–'),
			}));
		});
		return {
			metrics: [
				{ label: localize('u6d.soil.spec.mSamp', "Problem Samples"), value: String(sampleRows.length), tone: sampleRows.length ? 'warn' : 'ok' },
				{ label: localize('u6d.soil.spec.mSoft', "Soft Clay Layers"), value: String(softRows.length), tone: softRows.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'softClay',
					title: localize('u6d.soil.spec.softTab', "Soft Clay Layers"),
					columns: [
						{ key: 'borehole', title: localize('u6d.soil.spec.colBh', "Borehole") },
						{ key: 'layer', title: localize('u6d.soil.spec.colLay', "Layer"), type: 'number', align: 'right' },
						{ key: 'topMm', title: localize('u6d.soil.spec.colTop', "Top [mm]"), type: 'number', align: 'right' },
						{ key: 'bottomMm', title: localize('u6d.soil.spec.colBot', "Bottom [mm]"), type: 'number', align: 'right' },
						{ key: 'consistency', title: localize('u6d.soil.spec.colCons', "Consistency") },
						{ key: 'nField', title: localize('u6d.soil.spec.colN', "N"), type: 'number', align: 'right' },
						{ key: 'cu', title: localize('u6d.soil.spec.colCu', "cu [kPa]"), type: 'number', align: 'right' },
						{ key: 'clause', title: localize('u6d.soil.spec.colClause', "Clause") },
					],
					rows: softRows,
					emptyMessage: localize('u6d.soil.spec.noSoft', "No soft clay layers detected."),
				},
				{
					id: 'samples',
					title: localize('u6d.soil.spec.sampTab', "Problem Soil Samples"),
					columns: [
						{ key: 'borehole', title: localize('u6d.soil.spec.colSBh', "Borehole") },
						{ key: 'sample', title: localize('u6d.soil.spec.colSamp', "Sample") },
						{ key: 'depthMm', title: localize('u6d.soil.spec.colSDep', "Depth [mm]"), type: 'number', align: 'right' },
						{ key: 'organic', title: localize('u6d.soil.spec.colOrg', "Organic") },
						{ key: 'expansive', title: localize('u6d.soil.spec.colExp', "Expansive") },
						{ key: 'collapsible', title: localize('u6d.soil.spec.colCol', "Collapsible") },
						{ key: 'dispersive', title: localize('u6d.soil.spec.colDisp', "Dispersive") },
					],
					rows: sampleRows,
					emptyMessage: localize('u6d.soil.spec.noSamp', "No organic, expansive, collapsible or dispersive samples flagged."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Earth Pressure & Chemistry

registerSoilPanel({
	id: 'saengine.soil.earthPressure',
	title: localize('u6d.soil.ep.title', "Lateral Earth Pressure Profile"),
	part: 'soil',
	icon: Codicon.arrowBoth,
	help: localize('u6d.soil.ep.help', "Computes Rankine, Jaky K0, Coulomb, and Mononobe-Okabe earth pressure coefficients plus total lateral soil and hydrostatic pressure profiles with depth."),
	fields: [
		{ key: 'borehole', label: localize('u6d.soil.ep.bh', "Borehole"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.soil.firstBh', "First Borehole") }] },
		{ key: 'depthM', label: localize('u6d.soil.ep.depth', "Retained Depth [m]"), type: 'number', defaultValue: 6.0, min: 0.5, step: '0.5' },
		{ key: 'surchargeKpa', label: localize('u6d.soil.ep.q', "Surface Surcharge q [kPa]"), type: 'number', defaultValue: 10, min: 0 },
		{ key: 'phiDeg', label: localize('u6d.soil.ep.phi', "Fallback φ' [°]"), type: 'number', defaultValue: 30, min: 5, max: 50 },
		{ key: 'betaDeg', label: localize('u6d.soil.ep.beta', "Backfill Slope β [°]"), type: 'number', defaultValue: 0, min: 0, max: 35 },
		{ key: 'deltaDeg', label: localize('u6d.soil.ep.delta', "Wall Friction δ [°]"), type: 'number', defaultValue: 0, min: 0, max: 35 },
		{ key: 'kh', label: localize('u6d.soil.ep.kh', "Seismic kh"), type: 'number', defaultValue: 0, min: 0, max: 0.5, step: '0.02' },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const res = asBag(await ctx.engineRequest('soil/earthPressure', { projectRoot: ctx.project.root.fsPath }));
		const bhs = asStrings(res.availableBoreholes);
		if (!bhs.length) {
			return undefined;
		}
		return {
			options: { borehole: bhs.map(b => ({ value: b, label: b })) },
			values: { borehole: bhs[0] },
		};
	},
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('soil/earthPressure', {
			projectRoot: ctx.project!.root.fsPath,
			borehole: String(values.borehole || '') || undefined,
			depthM: Number(values.depthM) || 6.0,
			surchargeKpa: Number(values.surchargeKpa ?? 10),
			phiDeg: Number(values.phiDeg) || 30,
			betaDeg: Number(values.betaDeg) || 0,
			deltaDeg: Number(values.deltaDeg) || 0,
			kh: Number(values.kh) || 0,
		}));
		const coef = asBag(raw.coefficients);
		const profRows: DataPanelRow[] = asArray(raw.profile).map(asBag).map(r => ({
			z: num(r.z) ?? 0,
			sigmaV: num(r.sigmaV) ?? 0,
			u: num(r.u) ?? 0,
			active: num(r.active) ?? 0,
			atRest: num(r.atRest) ?? 0,
			passive: num(r.passive) ?? 0,
		}));
		const coefRows: DataPanelRow[] = [
			{ theory: 'Rankine Active (level) Ka', value: num(coef.kaRankine) ?? '–' },
			{ theory: 'Rankine Passive (level) Kp', value: num(coef.kpRankine) ?? '–' },
			{ theory: 'Jaky At-Rest K0', value: num(coef.k0Jaky) ?? '–' },
			{ theory: 'Rankine Active (sloped) Ka', value: num(coef.kaRankineSloped) ?? '–' },
			{ theory: 'Coulomb Active Ka', value: num(coef.kaCoulomb) ?? '–' },
			{ theory: 'Coulomb Passive Kp', value: num(coef.kpCoulomb) ?? '–' },
			{ theory: 'Mononobe-Okabe Seismic Kae', value: num(coef.kaeMononobeOkabe) ?? '–' },
		];
		return {
			metrics: [
				{ label: localize('u6d.soil.ep.mK0', "K0 (Jaky)"), value: formatScalar(coef.k0Jaky) },
				{ label: localize('u6d.soil.ep.mKa', "Ka (Rankine)"), value: formatScalar(coef.kaRankine) },
				{ label: localize('u6d.soil.ep.mKp', "Kp (Rankine)"), value: formatScalar(coef.kpRankine) },
			],
			tables: [
				{
					id: 'profile',
					title: localize('u6d.soil.ep.profTab', "Pressure Profile with Depth"),
					columns: [
						{ key: 'z', title: localize('u6d.soil.ep.colZ', "Depth [m]"), type: 'number', align: 'right' },
						{ key: 'sigmaV', title: localize('u6d.soil.ep.colSv', "σv [kPa]"), type: 'number', align: 'right' },
						{ key: 'u', title: localize('u6d.soil.ep.colU', "u [kPa]"), type: 'number', align: 'right' },
						{ key: 'active', title: localize('u6d.soil.ep.colPa', "Active [kPa]"), type: 'number', align: 'right' },
						{ key: 'atRest', title: localize('u6d.soil.ep.colP0', "At-Rest [kPa]"), type: 'number', align: 'right' },
						{ key: 'passive', title: localize('u6d.soil.ep.colPp', "Passive [kPa]"), type: 'number', align: 'right' },
					],
					rows: profRows,
				},
				{
					id: 'coefficients',
					title: localize('u6d.soil.ep.coefTab', "Earth Pressure Coefficients"),
					columns: [
						{ key: 'theory', title: localize('u6d.soil.ep.colTheory', "Coefficient") },
						{ key: 'value', title: localize('u6d.soil.ep.colCoefVal', "Value"), type: 'number', align: 'right' },
					],
					rows: coefRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.chemistry',
	title: localize('u6d.soil.chem.title', "Soil Chemistry & Concrete Durability"),
	part: 'soil',
	icon: Codicon.beaker,
	help: localize('u6d.soil.chem.help', "Evaluates groundwater and soil sulphate/chloride/pH tests, steel pile corrosivity, and minimum foundation concrete strength, cement type and w/c ratio."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/analysis', { projectRoot: ctx.project!.root.fsPath }));
		const chem = asBag(raw.chemistry);
		const samples = asArray(chem.samples).map(asBag);
		const conc = asBag(chem.concrete);
		const rows: DataPanelRow[] = samples.map(s => ({
			borehole: str(s.borehole),
			sample: str(s.sample, '–'),
			depthMm: num(s.depth) ?? 0,
			sulphateClass: str(asBag(s.sulphate).class, '–'),
			ph: num(s.ph) ?? '–',
			chloride: num(s.chloride) ?? '–',
			corrosivity: str(asBag(s.corrosivity).rating || asBag(s.corrosivity).class, '–'),
			flags: asStrings(s.flags).join(', ') || 'None',
		}));
		const concRows: DataPanelRow[] = Object.entries(conc).map(([k, v]) => ({
			requirement: k,
			value: formatScalar(v),
		}));
		return {
			metrics: [
				{ label: localize('u6d.soil.chem.mSamples', "Tested Samples"), value: String(rows.length) },
				{ label: localize('u6d.soil.chem.mClass', "Exposure Class"), value: str(conc.class || conc.sulphateClass, '–') },
			],
			tables: [
				{
					id: 'samples',
					title: localize('u6d.soil.chem.sampTab', "Chemical Test Results"),
					columns: [
						{ key: 'borehole', title: localize('u6d.soil.chem.colBh', "Borehole") },
						{ key: 'sample', title: localize('u6d.soil.chem.colSamp', "Sample") },
						{ key: 'depthMm', title: localize('u6d.soil.chem.colDep', "Depth [mm]"), type: 'number', align: 'right' },
						{ key: 'sulphateClass', title: localize('u6d.soil.chem.colSul', "Sulphate Class") },
						{ key: 'ph', title: localize('u6d.soil.chem.colPh', "pH"), type: 'number', align: 'right' },
						{ key: 'chloride', title: localize('u6d.soil.chem.colCl', "Chloride"), type: 'number', align: 'right' },
						{ key: 'corrosivity', title: localize('u6d.soil.chem.colCorr', "Corrosivity") },
						{ key: 'flags', title: localize('u6d.soil.chem.colFlags', "Flags") },
					],
					rows,
					emptyMessage: localize('u6d.soil.chem.empty', "No soil chemistry test values entered on borehole samples."),
				},
				{
					id: 'concrete',
					title: localize('u6d.soil.chem.concTab', "Foundation Concrete Requirement"),
					columns: [
						{ key: 'requirement', title: localize('u6d.soil.chem.colReq', "Requirement") },
						{ key: 'value', title: localize('u6d.soil.chem.colVal', "Value") },
					],
					rows: concRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Site & GIS

registerSoilPanel({
	id: 'saengine.soil.locationSummary',
	title: localize('u6d.soil.loc.title', "Site Coordinates & Nearest Town"),
	part: 'soil',
	icon: Codicon.location,
	help: localize('u6d.soil.loc.help', "Reports project origin WGS 84 latitude/longitude, BTM coordinates, borehole GIS positions, and nearest hazard-table town."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/plotPlanning', { projectRoot: ctx.project!.root.fsPath }));
		const loc = asBag(raw.location);
		const site = asBag(loc.site);
		const sug = asBag(loc.suggestion);
		const bhs = asArray(loc.boreholes).map(asBag);
		const rows: DataPanelRow[] = [
			{ property: localize('u6d.soil.loc.lat', "Latitude [°]"), value: formatScalar(site.latitude) },
			{ property: localize('u6d.soil.loc.lon', "Longitude [°]"), value: formatScalar(site.longitude) },
			{ property: localize('u6d.soil.loc.town', "Nearest Town"), value: str(sug.town || sug.label, '–') },
			{ property: localize('u6d.soil.loc.dist', "Distance [km]"), value: formatScalar(sug.distanceKm) },
			{ property: localize('u6d.soil.loc.z', "Suggested Seismic Z"), value: formatScalar(sug.Z) },
			{ property: localize('u6d.soil.loc.v', "Suggested Wind V [m/s]"), value: formatScalar(sug.V) },
		];
		const bhRows: DataPanelRow[] = bhs.map(b => ({
			id: str(b.id),
			xMm: num(b.x) ?? 0,
			yMm: num(b.y) ?? 0,
			lat: num(b.latitude) ?? '–',
			lon: num(b.longitude) ?? '–',
		}));
		return {
			metrics: [
				{ label: localize('u6d.soil.loc.mTown', "Nearest Town"), value: str(sug.town || sug.label, '–') },
				{ label: localize('u6d.soil.loc.mBh', "Mapped Boreholes"), value: String(bhRows.length) },
			],
			tables: [
				{
					id: 'site',
					title: localize('u6d.soil.loc.siteTab', "Site Location & Hazard Suggestion"),
					columns: [
						{ key: 'property', title: localize('u6d.soil.loc.colProp', "Property") },
						{ key: 'value', title: localize('u6d.soil.loc.colVal', "Value") },
					],
					rows,
				},
				{
					id: 'boreholes',
					title: localize('u6d.soil.loc.bhTab', "Borehole GIS Coordinates"),
					columns: [
						{ key: 'id', title: localize('u6d.soil.loc.colId', "Borehole") },
						{ key: 'xMm', title: localize('u6d.soil.loc.colX', "Grid X [mm]"), type: 'number', align: 'right' },
						{ key: 'yMm', title: localize('u6d.soil.loc.colY', "Grid Y [mm]"), type: 'number', align: 'right' },
						{ key: 'lat', title: localize('u6d.soil.loc.colLat', "Latitude [°]"), type: 'number', align: 'right' },
						{ key: 'lon', title: localize('u6d.soil.loc.colLon', "Longitude [°]"), type: 'number', align: 'right' },
					],
					rows: bhRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.plotCompliance',
	title: localize('u6d.soil.plot.title', "Plot Setbacks, FAR & Ground Coverage"),
	part: 'soil',
	icon: Codicon.layout,
	help: localize('u6d.soil.plot.help', "Checks floor plan members against the plot's buildable setback envelope and verifies FAR, MGC and building height against planning rules."),
	secondaryActions: openSoilEditorAction(localize('u6d.soil.openSoil', "Open Soil Report")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('soil/plotPlanning', { projectRoot: ctx.project!.root.fsPath }));
		const plot = asBag(raw.plot);
		const plan = asBag(raw.planning);
		const planChecks = asArray(plan.checks).map(asBag);
		const warnings = asStrings(plot.warnings);
		const checkRows: DataPanelRow[] = planChecks.map(c => ({
			item: str(c.item || c.name),
			permitted: formatScalar(c.permitted ?? c.limit),
			actual: formatScalar(c.actual),
			status: c.ok === false ? 'Fail' : 'Pass',
			rule: str(c.rule, '–'),
		}));
		const warnRows: DataPanelRow[] = warnings.map(w => ({
			warning: w,
			status: 'Warn',
		}));
		return {
			metrics: [
				{ label: localize('u6d.soil.plot.mChecks', "Planning Checks"), value: String(checkRows.length) },
				{ label: localize('u6d.soil.plot.mEnc', "Encroachments"), value: String(warnRows.length), tone: warnRows.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'planning',
					title: localize('u6d.soil.plot.planTab', "Planning Compliance (FAR / MGC / Setbacks)"),
					columns: [
						{ key: 'item', title: localize('u6d.soil.plot.colItem', "Requirement") },
						{ key: 'permitted', title: localize('u6d.soil.plot.colPerm', "Permitted") },
						{ key: 'actual', title: localize('u6d.soil.plot.colAct', "Actual") },
						{ key: 'status', title: localize('u6d.soil.plot.colStatus', "Status"), type: 'status' },
						{ key: 'rule', title: localize('u6d.soil.plot.colRule', "Rule") },
					],
					rows: checkRows,
					emptyMessage: localize('u6d.soil.plot.emptyPlan', "Enter plot boundary and planning parameters in 01 Soil Report to run FAR/MGC checks."),
				},
				{
					id: 'encroachments',
					title: localize('u6d.soil.plot.encTab', "Plot Boundary & Setback Warnings"),
					columns: [
						{ key: 'warning', title: localize('u6d.soil.plot.colWarn', "Finding") },
						{ key: 'status', title: localize('u6d.soil.plot.colWStatus', "Status"), type: 'status' },
					],
					rows: warnRows,
					emptyMessage: localize('u6d.soil.plot.noEnc', "No plot or setback encroachments detected."),
				},
			],
			notes: asStrings(raw.notes),
			problems: [...asStrings(plot.problems), ...asStrings(raw.problems)],
		};
	},
});

registerSoilPanel({
	id: 'saengine.soil.terrainProfile',
	title: localize('u6d.soil.terrain.title', "Site Terrain Cut & Fill Volumes"),
	part: 'soil',
	icon: Codicon.compass,
	help: localize('u6d.soil.terrain.help', "Recomputes TIN topography cut and fill earthwork volumes from imported site survey points at the target formation platform level."),
	fields: [
		{ key: 'platform', label: localize('u6d.soil.terrain.platform', "Formation Platform Level [m] (blank = default)"), type: 'text', defaultValue: '' },
	],
	run: async (ctx, values) => {
		const platText = String(values.platform || '').trim();
		const platNum = platText ? Number(platText) : undefined;
		const raw = asBag(await ctx.engineRequest('office/terrainRecompute', {
			projectRoot: ctx.project!.root.fsPath,
			...(platNum !== undefined && Number.isFinite(platNum) ? { platform: { level: platNum * 1000 } } : {}),
		}));
		const terrain = asBag(raw.terrain);
		const cut = terrain.cutVolume ?? terrain.cut;
		const fill = terrain.fillVolume ?? terrain.fill;
		const rows: DataPanelRow[] = [
			...(raw.pointCount !== undefined ? [{ metric: localize('u6d.soil.terrain.pts', "Survey Points"), value: formatScalar(raw.pointCount) }] : []),
			...(raw.triangleCount !== undefined ? [{ metric: localize('u6d.soil.terrain.tris', "TIN Triangles"), value: formatScalar(raw.triangleCount) }] : []),
			...Object.entries(terrain).map(([k, v]) => ({ metric: k, value: formatScalar(v) })),
		];
		return {
			metrics: [
				{ label: localize('u6d.soil.terrain.mCut', "Cut [m³]"), value: formatScalar(cut) },
				{ label: localize('u6d.soil.terrain.mFill', "Fill [m³]"), value: formatScalar(fill) },
				...(raw.pointCount !== undefined ? [{ label: localize('u6d.soil.terrain.mPts', "Survey Points"), value: formatScalar(raw.pointCount) }] : []),
			],
			tables: [{
				id: 'terrain',
				title: localize('u6d.soil.terrain.tab', "Topography & Cut/Fill Summary"),
				columns: [
					{ key: 'metric', title: localize('u6d.soil.terrain.colMet', "Parameter") },
					{ key: 'value', title: localize('u6d.soil.terrain.colVal', "Value") },
				],
				rows,
				emptyMessage: localize('u6d.soil.terrain.empty', "No terrain survey points imported yet (import survey in Office Tools > Site)."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion
