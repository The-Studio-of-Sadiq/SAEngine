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

function parseNumberList(raw: unknown): number[] {
	return String(raw ?? '')
		.split(/[\s,;]+/)
		.map(t => Number(t.trim()))
		.filter(n => Number.isFinite(n) && n > 0);
}

function registerSubstructurePanel(descriptor: IEngineDataPanelDescriptor): void {
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

function openSubstructureAction(label: string): readonly IDataPanelAction[] {
	return [{
		id: 'openSubstructureEditor',
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand('saengine.project.showSubstructure'),
	}];
}

//#region Shallow & Sizing

registerSubstructurePanel({
	id: 'saengine.substructure.sizeSummary',
	title: localize('u6d.sub.size.title', "Footing Sizing & Geotechnical Check"),
	part: 'substructure',
	icon: Codicon.symbolRuler,
	help: localize('u6d.sub.size.help', "Computes preliminary foundation sizes and checks shallow foundations against active bearing pressures and structural analysis reactions."),
	secondaryActions: openSubstructureAction(localize('u6d.sub.openSub', "Open Substructure")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('substructure/size', { projectRoot: ctx.project!.root.fsPath }));
		const designs = asArray(raw.designs).map(asBag);
		const designById = new Map(designs.map(d => [str(d.id), d]));
		const foundations = asArray(raw.foundations).map(asBag);
		const rows: DataPanelRow[] = foundations.map(f => {
			const id = str(f.id);
			const d = designById.get(id) ?? {};
			const cols = asStrings(d.columns ?? f.columns).join(', ') || '–';
			const dim = f.width !== undefined && f.length !== undefined
				? `${formatScalar(f.width)} × ${formatScalar(f.length)} × ${formatScalar(f.thickness)}`
				: formatScalar(f.thickness ?? '–');
			const util = num(d.utilisation);
			return {
				id,
				kind: str(f.type, 'footing'),
				columns: cols,
				dimensions: dim,
				governing: str(d.governing, '–'),
				utilisation: util !== undefined ? Number((util * 100).toFixed(1)) : '–',
				status: d.ok === false ? 'Fail' : 'Pass',
			};
		});
		const raft = asBag(raw.raft);
		const metrics = [
			{ label: localize('u6d.sub.size.mCount', "Proposed Footings"), value: String(rows.length) },
			{ label: localize('u6d.sub.size.mProbs', "Issues"), value: String(asArray(raw.problems).length), tone: asArray(raw.problems).length ? 'warn' as const : 'ok' as const },
			...(raft.areaRatio !== undefined ? [{ label: localize('u6d.sub.size.mRaft', "Coverage Ratio"), value: formatScalar(raft.areaRatio) }] : []),
		];
		return {
			metrics,
			tables: [{
				id: 'proposals',
				title: localize('u6d.sub.size.tab', "Substructure Sizing Output"),
				columns: [
					{ key: 'id', title: localize('u6d.sub.size.colId', "Element") },
					{ key: 'kind', title: localize('u6d.sub.size.colKind', "Type") },
					{ key: 'columns', title: localize('u6d.sub.size.colCols', "Columns") },
					{ key: 'dimensions', title: localize('u6d.sub.size.colDim', "Proposed Size [mm]") },
					{ key: 'governing', title: localize('u6d.sub.size.colGov', "Governing Check") },
					{ key: 'utilisation', title: localize('u6d.sub.size.colUtil', "Util. [%]"), type: 'number', align: 'right' },
					{ key: 'status', title: localize('u6d.sub.size.colStat', "Status"), type: 'status' },
				],
				rows,
				emptyMessage: localize('u6d.sub.size.empty', "All columns already have foundations, or run FEM analysis first to size footings."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Piles & Pile Analysis

registerSubstructurePanel({
	id: 'saengine.substructure.pileCapacity',
	title: localize('u6d.sub.pcap.title', "Single-Pile Axial Capacity Matrix"),
	part: 'substructure',
	icon: Codicon.arrowDown,
	help: localize('u6d.sub.pcap.help', "Computes skin friction Qs, end bearing Qb, ultimate capacity Qult, safe compression Qa and tension Ta across pile diameters and lengths per borehole."),
	fields: [
		{
			key: 'kind',
			label: localize('u6d.sub.pcap.kind', "Pile Kind"),
			type: 'select',
			defaultValue: 'bored',
			options: [
				{ value: 'bored', label: localize('u6d.sub.pcap.bored', "Bored Cast-in-Situ") },
				{ value: 'driven', label: localize('u6d.sub.pcap.driven', "Driven Precast / Steel") },
				{ value: 'cfa', label: localize('u6d.sub.pcap.cfa', "CFA Pile") },
			],
		},
		{ key: 'headLevelMm', label: localize('u6d.sub.pcap.head', "Cut-Off Level [mm, project z]"), type: 'number', defaultValue: -1500 },
		{ key: 'diameters', label: localize('u6d.sub.pcap.diams', "Diameters [mm]"), type: 'text', defaultValue: '450, 500, 600, 750' },
		{ key: 'lengths', label: localize('u6d.sub.pcap.lens', "Lengths [m]"), type: 'text', defaultValue: '10, 15, 20, 25' },
	],
	run: async (ctx, values) => {
		const diams = parseNumberList(values.diameters);
		const lens = parseNumberList(values.lengths);
		const raw = asBag(await ctx.engineRequest('substructure/pileCapacity', {
			projectRoot: ctx.project!.root.fsPath,
			kind: String(values.kind || 'bored'),
			headLevelMm: Number(values.headLevelMm ?? -1500),
			diametersMm: diams.length ? diams : [450, 500, 600, 750],
			lengthsM: lens.length ? lens : [10, 15, 20, 25],
		}));
		const rows: DataPanelRow[] = asArray(raw.rows).map(asBag).map(r => ({
			borehole: str(r.borehole),
			diameterMm: num(r.diameterMm) ?? 0,
			lengthM: num(r.lengthM) ?? 0,
			qsKn: num(r.qsKn) ?? 0,
			qbKn: num(r.qbKn) ?? 0,
			qultKn: num(r.qultKn) ?? 0,
			qaKn: num(r.qaKn) ?? 0,
			taKn: num(r.taKn) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.pcap.mKind', "Pile Type"), value: str(raw.kind, 'bored') },
				{ label: localize('u6d.sub.pcap.mRows', "Capacity Cases"), value: String(rows.length) },
			],
			tables: [{
				id: 'pileCapacity',
				title: localize('u6d.sub.pcap.tab', "Single-Pile Capacity Matrix [kN]"),
				columns: [
					{ key: 'borehole', title: localize('u6d.sub.pcap.colBh', "Borehole") },
					{ key: 'diameterMm', title: localize('u6d.sub.pcap.colD', "Dia [mm]"), type: 'number', align: 'right' },
					{ key: 'lengthM', title: localize('u6d.sub.pcap.colL', "Length [m]"), type: 'number', align: 'right' },
					{ key: 'qsKn', title: localize('u6d.sub.pcap.colQs', "Skin Qs [kN]"), type: 'number', align: 'right' },
					{ key: 'qbKn', title: localize('u6d.sub.pcap.colQb', "Base Qb [kN]"), type: 'number', align: 'right' },
					{ key: 'qultKn', title: localize('u6d.sub.pcap.colQult', "Qult [kN]"), type: 'number', align: 'right' },
					{ key: 'qaKn', title: localize('u6d.sub.pcap.colQa', "Allowable Qa [kN]"), type: 'number', align: 'right' },
					{ key: 'taKn', title: localize('u6d.sub.pcap.colTa', "Uplift Ta [kN]"), type: 'number', align: 'right' },
				],
				rows,
				emptyMessage: localize('u6d.sub.pcap.empty', "Add boreholes to 01 Soil Report to compute pile capacities."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.pileLateral',
	title: localize('u6d.sub.plat.title', "Lateral Pile Response, Broms Hu & p-y Curves"),
	part: 'substructure',
	icon: Codicon.arrowRight,
	help: localize('u6d.sub.plat.help', "Computes coupled lateral/rotational pile-head stiffness, Broms soil failure lateral capacity Hu, and depth-sampled p-y springs."),
	fields: [
		{ key: 'borehole', label: localize('u6d.sub.plat.bh', "Borehole"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.sub.firstBh', "First Borehole") }] },
		{
			key: 'kind',
			label: localize('u6d.sub.plat.kind', "Pile Kind"),
			type: 'select',
			defaultValue: 'bored',
			options: [
				{ value: 'bored', label: localize('u6d.sub.pcap.bored', "Bored Cast-in-Situ") },
				{ value: 'driven', label: localize('u6d.sub.pcap.driven', "Driven Precast / Steel") },
			],
		},
		{ key: 'diameterMm', label: localize('u6d.sub.plat.d', "Diameter [mm]"), type: 'number', defaultValue: 600, min: 200 },
		{ key: 'lengthM', label: localize('u6d.sub.plat.l', "Length [m]"), type: 'number', defaultValue: 18, min: 2 },
		{ key: 'headDepthM', label: localize('u6d.sub.plat.hd', "Head Depth Below Ground [m]"), type: 'number', defaultValue: 1.5, min: 0, step: '0.1' },
		{
			key: 'fixity',
			label: localize('u6d.sub.plat.fix', "Head Fixity"),
			type: 'select',
			defaultValue: 'fixed',
			options: [
				{ value: 'fixed', label: localize('u6d.sub.plat.fixed', "Fixed Head") },
				{ value: 'free', label: localize('u6d.sub.plat.free', "Free Head") },
			],
		},
		{ key: 'myKnm', label: localize('u6d.sub.plat.my', "Plastic Moment My [kN·m]"), type: 'number', defaultValue: 250, min: 1 },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const res = asBag(await ctx.engineRequest('substructure/pileLateral', { projectRoot: ctx.project.root.fsPath }));
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
		const raw = asBag(await ctx.engineRequest('substructure/pileLateral', {
			projectRoot: ctx.project!.root.fsPath,
			borehole: String(values.borehole || '') || undefined,
			kind: String(values.kind || 'bored'),
			diameterMm: Number(values.diameterMm) || 600,
			lengthM: Number(values.lengthM) || 18,
			headDepthM: Number(values.headDepthM ?? 1.5),
			fixity: String(values.fixity || 'fixed'),
			myKnm: Number(values.myKnm) || 250,
		}));
		const stiff = asBag(raw.stiffness);
		const broms = asBag(raw.broms);
		const summaryRows: DataPanelRow[] = [
			...Object.entries(stiff).map(([k, v]) => ({ item: `Stiffness: ${k}`, value: formatScalar(v) })),
			...Object.entries(broms).map(([k, v]) => ({ item: `Broms: ${k}`, value: formatScalar(v) })),
		];
		const pyRows: DataPanelRow[] = asArray(raw.py).map(asBag).map(r => ({
			zM: num(r.zM) ?? 0,
			layer: str(r.layer, '–'),
			sigmaEffKpa: num(r.sigmaEffKpa) ?? 0,
			yMaxMm: num(r.yMaxMm) ?? 0,
			pUltKnPerM: num(r.pUltKnPerM) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.plat.mBh', "Borehole"), value: str(raw.borehole, '–') },
				{ label: localize('u6d.sub.plat.mHu', "Broms Hu [kN]"), value: formatScalar(broms.hu ?? broms.Hu ?? broms.capacity) },
				{ label: localize('u6d.sub.plat.mPy', "p-y Sample Depths"), value: String(pyRows.length) },
			],
			tables: [
				{
					id: 'summary',
					title: localize('u6d.sub.plat.sumTab', "Pile-Head Stiffness & Broms Lateral Capacity"),
					columns: [
						{ key: 'item', title: localize('u6d.sub.plat.colItem', "Parameter") },
						{ key: 'value', title: localize('u6d.sub.plat.colVal', "Value") },
					],
					rows: summaryRows,
				},
				{
					id: 'py',
					title: localize('u6d.sub.plat.pyTab', "p-y Lateral Spring Summary"),
					columns: [
						{ key: 'zM', title: localize('u6d.sub.plat.colZ', "Depth [m]"), type: 'number', align: 'right' },
						{ key: 'layer', title: localize('u6d.sub.plat.colLay', "Soil Layer") },
						{ key: 'sigmaEffKpa', title: localize('u6d.sub.plat.colSig', "σ'v0 [kPa]"), type: 'number', align: 'right' },
						{ key: 'yMaxMm', title: localize('u6d.sub.plat.colY', "y_max [mm]"), type: 'number', align: 'right' },
						{ key: 'pUltKnPerM', title: localize('u6d.sub.plat.colP', "p_ult [kN/m]"), type: 'number', align: 'right' },
					],
					rows: pyRows,
					emptyMessage: localize('u6d.sub.plat.noPy', "Active code pack does not define p-y curve rules for these soil layers."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.pileSettlement',
	title: localize('u6d.sub.psett.title', "Single-Pile & Group Equivalent Raft Settlement"),
	part: 'substructure',
	icon: Codicon.graphLine,
	help: localize('u6d.sub.psett.help', "Computes single-pile elastic shortening + shaft/tip settlement and pile-group equivalent raft immediate + consolidation settlement."),
	fields: [
		{ key: 'borehole', label: localize('u6d.sub.psett.bh', "Borehole"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.sub.firstBh', "First Borehole") }] },
		{ key: 'diameterMm', label: localize('u6d.sub.psett.d', "Diameter [mm]"), type: 'number', defaultValue: 600, min: 200 },
		{ key: 'lengthM', label: localize('u6d.sub.psett.l', "Length [m]"), type: 'number', defaultValue: 18, min: 2 },
		{ key: 'loadKn', label: localize('u6d.sub.psett.p', "Load per Pile [kN]"), type: 'number', defaultValue: 800, min: 1 },
		{ key: 'count', label: localize('u6d.sub.psett.n', "Piles in Group"), type: 'number', defaultValue: 4, min: 1 },
		{ key: 'bgM', label: localize('u6d.sub.psett.bg', "Group Width Bg [m]"), type: 'number', defaultValue: 2.4, min: 0.5, step: '0.1' },
		{ key: 'lgM', label: localize('u6d.sub.psett.lg', "Group Length Lg [m]"), type: 'number', defaultValue: 2.4, min: 0.5, step: '0.1' },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const res = asBag(await ctx.engineRequest('substructure/pileSettlement', { projectRoot: ctx.project.root.fsPath }));
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
		const raw = asBag(await ctx.engineRequest('substructure/pileSettlement', {
			projectRoot: ctx.project!.root.fsPath,
			borehole: String(values.borehole || '') || undefined,
			diameterMm: Number(values.diameterMm) || 600,
			lengthM: Number(values.lengthM) || 18,
			loadKn: Number(values.loadKn) || 800,
			count: Number(values.count) || 4,
			bgM: Number(values.bgM) || 2.4,
			lgM: Number(values.lgM) || 2.4,
		}));
		const single = asBag(raw.single);
		const group = asBag(raw.group);
		const rows: DataPanelRow[] = [
			...Object.entries(single).map(([k, v]) => ({ scope: 'Single Pile', parameter: k, value: formatScalar(v) })),
			...Object.entries(group).map(([k, v]) => ({ scope: 'Pile Group', parameter: k, value: formatScalar(v) })),
		];
		return {
			metrics: [
				{ label: localize('u6d.sub.psett.mSing', "Single Total [mm]"), value: formatScalar(single.total ?? single.settlement) },
				{ label: localize('u6d.sub.psett.mGrp', "Group Total [mm]"), value: formatScalar(group.total ?? group.settlement) },
			],
			tables: [{
				id: 'settlement',
				title: localize('u6d.sub.psett.tab', "Single & Group Settlement Components"),
				columns: [
					{ key: 'scope', title: localize('u6d.sub.psett.colScope', "Scope") },
					{ key: 'parameter', title: localize('u6d.sub.psett.colParam', "Parameter") },
					{ key: 'value', title: localize('u6d.sub.psett.colVal', "Value") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.downdrag',
	title: localize('u6d.sub.down.title', "Negative Skin Friction (Downdrag) & Uplift"),
	part: 'substructure',
	icon: Codicon.triangleDown,
	help: localize('u6d.sub.down.help', "Locates the pile neutral point, computes negative skin friction dragload in settling strata, and checks swelling clay uplift."),
	fields: [
		{ key: 'borehole', label: localize('u6d.sub.down.bh', "Borehole"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.sub.firstBh', "First Borehole") }] },
		{ key: 'diameterMm', label: localize('u6d.sub.down.d', "Diameter [mm]"), type: 'number', defaultValue: 600, min: 200 },
		{ key: 'lengthM', label: localize('u6d.sub.down.l', "Length [m]"), type: 'number', defaultValue: 18, min: 2 },
		{ key: 'sustainedKn', label: localize('u6d.sub.down.p', "Sustained Dead Load [kN]"), type: 'number', defaultValue: 600, min: 0 },
		{ key: 'settlingDepthM', label: localize('u6d.sub.down.sd', "Settling Depth [m] (blank = auto)"), type: 'text', defaultValue: '' },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const res = asBag(await ctx.engineRequest('substructure/downdrag', { projectRoot: ctx.project.root.fsPath }));
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
		const sdText = String(values.settlingDepthM || '').trim();
		const sdNum = sdText ? Number(sdText) : undefined;
		const raw = asBag(await ctx.engineRequest('substructure/downdrag', {
			projectRoot: ctx.project!.root.fsPath,
			borehole: String(values.borehole || '') || undefined,
			diameterMm: Number(values.diameterMm) || 600,
			lengthM: Number(values.lengthM) || 18,
			sustainedKn: Number(values.sustainedKn) || 600,
			...(sdNum !== undefined && Number.isFinite(sdNum) ? { settlingDepthM: sdNum } : {}),
		}));
		const np = asBag(raw.neutralPoint);
		const sw = asBag(raw.swelling);
		const rows: DataPanelRow[] = [
			{ scope: 'Profile', item: 'Settling Zone Depth [m]', value: formatScalar(raw.settlingDepthM) },
			{ scope: 'Profile', item: 'Expansive Clay Depth [m]', value: formatScalar(raw.expansiveDepthM) },
			...Object.entries(np).map(([k, v]) => ({ scope: 'Downdrag', item: k, value: formatScalar(v) })),
			...Object.entries(sw).map(([k, v]) => ({ scope: 'Swelling Uplift', item: k, value: formatScalar(v) })),
		];
		return {
			metrics: [
				{ label: localize('u6d.sub.down.mBh', "Borehole"), value: str(raw.borehole, '–') },
				{ label: localize('u6d.sub.down.mDrag', "Dragload [kN]"), value: formatScalar(np.dragload ?? np.drag) },
				{ label: localize('u6d.sub.down.mNp', "Neutral Depth [m]"), value: formatScalar(np.depth ?? np.neutralPoint) },
			],
			tables: [{
				id: 'downdrag',
				title: localize('u6d.sub.down.tab', "Downdrag & Swelling Uplift Results"),
				columns: [
					{ key: 'scope', title: localize('u6d.sub.down.colScope', "Analysis") },
					{ key: 'item', title: localize('u6d.sub.down.colItem', "Parameter") },
					{ key: 'value', title: localize('u6d.sub.down.colVal', "Value") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.pileLoadTests',
	title: localize('u6d.sub.lt.title', "Static Pile Load Tests (Davisson / Butler-Hoy / Brinch Hansen)"),
	part: 'substructure',
	icon: Codicon.beaker,
	help: localize('u6d.sub.lt.help', "Evaluates saved pile load tests and interprets custom load:settlement curves [kN:mm] by Davisson offset, Butler-Hoy, and Brinch Hansen criteria."),
	fields: [
		{ key: 'diameterMm', label: localize('u6d.sub.lt.d', "Diameter [mm]"), type: 'number', defaultValue: 600, min: 200 },
		{ key: 'lengthM', label: localize('u6d.sub.lt.l', "Length [m]"), type: 'number', defaultValue: 18, min: 2 },
		{ key: 'curveText', label: localize('u6d.sub.lt.curve', "Optional Load:Settlement Pairs [kN:mm]"), type: 'text', defaultValue: '0:0, 400:1.2, 800:3.0, 1200:6.8, 1600:14.5, 2000:28.0' },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('substructure/loadTests', {
			projectRoot: ctx.project!.root.fsPath,
			diameterMm: Number(values.diameterMm) || 600,
			lengthM: Number(values.lengthM) || 18,
			curveText: String(values.curveText || ''),
		}));
		const calc = asBag(raw.calculator);
		const proj = asArray(raw.projectTests).map(asBag);
		const calcRows: DataPanelRow[] = Object.entries(calc).map(([k, v]) => ({ parameter: k, value: formatScalar(v) }));
		const projRows: DataPanelRow[] = proj.map(t => ({
			pileType: str(t.pileType),
			id: str(t.id, '–'),
			kind: str(t.kind, '–'),
			safeKn: formatScalar(t.safe),
			note: str(t.note, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.lt.mProj', "Project Tests"), value: String(projRows.length) },
				{ label: localize('u6d.sub.lt.mDav', "Davisson [kN]"), value: formatScalar(calc.davissonKn) },
				{ label: localize('u6d.sub.lt.mSafe', "Safe Load [kN]"), value: formatScalar(calc.safeKn) },
			],
			tables: [
				{
					id: 'calculator',
					title: localize('u6d.sub.lt.calcTab', "Load-Settlement Curve Interpretation"),
					columns: [
						{ key: 'parameter', title: localize('u6d.sub.lt.colParam', "Criterion") },
						{ key: 'value', title: localize('u6d.sub.lt.colVal', "Value") },
					],
					rows: calcRows,
				},
				{
					id: 'projectTests',
					title: localize('u6d.sub.lt.projTab', "Project Saved Pile Load Tests"),
					columns: [
						{ key: 'pileType', title: localize('u6d.sub.lt.colPt', "Pile Type") },
						{ key: 'id', title: localize('u6d.sub.lt.colId', "Test ID") },
						{ key: 'kind', title: localize('u6d.sub.lt.colKind', "Kind") },
						{ key: 'safeKn', title: localize('u6d.sub.lt.colSafe', "Safe [kN]") },
						{ key: 'note', title: localize('u6d.sub.lt.colNote', "Note") },
					],
					rows: projRows,
					emptyMessage: localize('u6d.sub.lt.noProj', "No pile load tests saved in 09 Substructure."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.pileDetailing',
	title: localize('u6d.sub.pdet.title', "Pile Detailing & Concrete Mix Requirements"),
	part: 'substructure',
	icon: Codicon.checklist,
	help: localize('u6d.sub.pdet.help', "Checks saved pile type reinforcement detailing rules (minimum bars, spiral/link spacing, clear cover) and recommends concrete f'c and tremie/dry mix."),
	fields: [
		{
			key: 'kind',
			label: localize('u6d.sub.pdet.kind', "Pile Kind"),
			type: 'select',
			defaultValue: 'bored',
			options: [
				{ value: 'bored', label: localize('u6d.sub.pcap.bored', "Bored Cast-in-Situ") },
				{ value: 'driven', label: localize('u6d.sub.pcap.drivenPrecast', "Driven Precast") },
			],
		},
		{ key: 'diameterMm', label: localize('u6d.sub.pdet.d', "Diameter [mm]"), type: 'number', defaultValue: 600, min: 200 },
		{ key: 'fcMpa', label: localize('u6d.sub.pdet.fc', "Concrete f'c [MPa]"), type: 'number', defaultValue: 28, min: 15 },
		{
			key: 'placement',
			label: localize('u6d.sub.pdet.pl', "Concrete Placement"),
			type: 'select',
			defaultValue: 'tremie',
			options: [
				{ value: 'tremie', label: localize('u6d.sub.pdet.tremie', "Tremie / Under Slurry") },
				{ value: 'dry', label: localize('u6d.sub.pdet.dry', "Dry Borehole") },
			],
		},
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('substructure/pileDetailing', {
			projectRoot: ctx.project!.root.fsPath,
			kind: String(values.kind || 'bored'),
			diameterMm: Number(values.diameterMm) || 600,
			fcMpa: Number(values.fcMpa) || 28,
			placement: String(values.placement || 'tremie'),
		}));
		const chks = asArray(raw.checks).map(asBag).map(c => ({
			pileType: str(c.pileType),
			name: str(c.name || c.item),
			required: formatScalar(c.required ?? c.limit),
			provided: formatScalar(c.provided ?? c.actual),
			status: c.ok === false ? 'Fail' : 'Pass',
		}));
		const guidRows: DataPanelRow[] = [
			{ requirement: 'Minimum Concrete f\'c [MPa]', value: formatScalar(raw.minFcMpa) },
			{ requirement: 'Recommended Mix', value: str(raw.recommendedMix, '–') },
			{ requirement: 'Placement Guidance', value: str(raw.guidance, '–') },
		];
		return {
			metrics: [
				{ label: localize('u6d.sub.pdet.mFc', "Min f'c [MPa]"), value: formatScalar(raw.minFcMpa) },
				{ label: localize('u6d.sub.pdet.mChks', "Pile Type Checks"), value: String(chks.length) },
			],
			tables: [
				{
					id: 'guidance',
					title: localize('u6d.sub.pdet.gTab', "Concrete & Placement Requirements"),
					columns: [
						{ key: 'requirement', title: localize('u6d.sub.pdet.colReq', "Requirement") },
						{ key: 'value', title: localize('u6d.sub.pdet.colVal', "Value") },
					],
					rows: guidRows,
				},
				{
					id: 'checks',
					title: localize('u6d.sub.pdet.cTab', "Saved Pile Type Detailing Checks"),
					columns: [
						{ key: 'pileType', title: localize('u6d.sub.pdet.colPt', "Pile Type") },
						{ key: 'name', title: localize('u6d.sub.pdet.colName', "Check") },
						{ key: 'required', title: localize('u6d.sub.pdet.colReqr', "Required") },
						{ key: 'provided', title: localize('u6d.sub.pdet.colProv', "Provided") },
						{ key: 'status', title: localize('u6d.sub.pdet.colStat', "Status"), type: 'status' },
					],
					rows: chks,
					emptyMessage: localize('u6d.sub.pdet.noTypes', "Define pile types in 09 Substructure to run per-type bar detailing checks."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Retaining, Basement & Excavation

registerSubstructurePanel({
	id: 'saengine.substructure.embeddedWall',
	title: localize('u6d.sub.ew.title', "Embedded Wall, Uplift & Seepage Calculator"),
	part: 'substructure',
	icon: Codicon.shield,
	help: localize('u6d.sub.ew.help', "Designs cantilever or single-propped embedded sheet pile / diaphragm walls and checks base hydraulic uplift and seepage piping gradient."),
	fields: [
		{ key: 'heightM', label: localize('u6d.sub.ew.h', "Retained Height [m]"), type: 'number', defaultValue: 5.0, min: 1.0, step: '0.5' },
		{
			key: 'kind',
			label: localize('u6d.sub.ew.kind', "Wall Support"),
			type: 'select',
			defaultValue: 'cantilever',
			options: [
				{ value: 'cantilever', label: localize('u6d.sub.ew.cant', "Cantilever") },
				{ value: 'propped', label: localize('u6d.sub.ew.prop', "Single Propped / Anchored") },
			],
		},
		{
			key: 'support',
			label: localize('u6d.sub.ew.sup', "Toe Fixity (if Propped)"),
			type: 'select',
			defaultValue: 'free',
			options: [
				{ value: 'free', label: localize('u6d.sub.ew.free', "Free Earth Support") },
				{ value: 'fixed', label: localize('u6d.sub.ew.fixed', "Fixed Earth Support") },
			],
		},
		{ key: 'propDepthM', label: localize('u6d.sub.ew.pd', "Prop Depth [m]"), type: 'number', defaultValue: 1.5, min: 0.3, step: '0.2' },
		{ key: 'surchargeKpa', label: localize('u6d.sub.ew.q', "Surface Surcharge [kPa]"), type: 'number', defaultValue: 10, min: 0 },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('substructure/embeddedWall', {
			projectRoot: ctx.project!.root.fsPath,
			heightM: Number(values.heightM) || 5.0,
			kind: String(values.kind || 'cantilever'),
			support: String(values.support || 'free'),
			propDepthM: Number(values.propDepthM) || 1.5,
			surchargeKpa: Number(values.surchargeKpa ?? 10),
		}));
		const wall = asBag(raw.wall);
		const uplift = asBag(raw.uplift);
		const seepage = asBag(raw.seepage);
		const rows: DataPanelRow[] = [
			...Object.entries(wall).map(([k, v]) => ({ group: 'Embedded Wall', parameter: k, value: formatScalar(v) })),
			...Object.entries(uplift).map(([k, v]) => ({ group: 'Base Uplift', parameter: k, value: formatScalar(v) })),
			...Object.entries(seepage).map(([k, v]) => ({ group: 'Seepage Piping', parameter: k, value: formatScalar(v) })),
		];
		return {
			metrics: [
				{ label: localize('u6d.sub.ew.mD', "Embedment d [m]"), value: typeof wall.d === 'number' ? wall.d.toFixed(2) : formatScalar(wall.d) },
				{ label: localize('u6d.sub.ew.mM', "Max Moment [kN·m/m]"), value: formatScalar(wall.moment ?? wall.mMax) },
				{ label: localize('u6d.sub.ew.mOk', "Equilibrium"), value: wall.ok === false ? 'Fail' : 'Pass', tone: wall.ok === false ? 'fail' : 'ok' },
			],
			tables: [{
				id: 'wall',
				title: localize('u6d.sub.ew.tab', "Embedded Wall & Hydraulic Checks"),
				columns: [
					{ key: 'group', title: localize('u6d.sub.ew.colGrp', "Check") },
					{ key: 'parameter', title: localize('u6d.sub.ew.colParam', "Parameter") },
					{ key: 'value', title: localize('u6d.sub.ew.colVal', "Value") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.basementLoads',
	title: localize('u6d.sub.base.title', "Basement Wall Lateral Earth & Water Loads (H)"),
	part: 'substructure',
	icon: Codicon.layers,
	help: localize('u6d.sub.base.help', "Computes at-rest soil + hydrostatic lateral pressures (Load Case H) exerted on BIM perimeter walls below finished ground level."),
	secondaryActions: openSubstructureAction(localize('u6d.sub.openSub', "Open Substructure")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('substructure/basementLoads', { projectRoot: ctx.project!.root.fsPath }));
		const walls = asArray(raw.walls).map(asBag);
		const rows: DataPanelRow[] = walls.map(w => ({
			wall: str(w.wall),
			source: str(w.source, '–'),
			direction: asArray(w.direction).join(', '),
			pTopKpa: num(w.pTopKpa) ?? 0,
			pMidKpa: num(w.pMidKpa) ?? 0,
			pBotKpa: num(w.pBotKpa) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.base.mCount', "Basement Walls"), value: String(rows.length) },
			],
			tables: [{
				id: 'basementWalls',
				title: localize('u6d.sub.base.tab', "Lateral Earth Pressure Load Case H [kPa]"),
				columns: [
					{ key: 'wall', title: localize('u6d.sub.base.colWall', "Wall Element") },
					{ key: 'source', title: localize('u6d.sub.base.colSrc', "Soil Source") },
					{ key: 'direction', title: localize('u6d.sub.base.colDir', "Normal Vector") },
					{ key: 'pTopKpa', title: localize('u6d.sub.base.colTop', "Top [kPa]"), type: 'number', align: 'right' },
					{ key: 'pMidKpa', title: localize('u6d.sub.base.colMid', "Mid [kPa]"), type: 'number', align: 'right' },
					{ key: 'pBotKpa', title: localize('u6d.sub.base.colBot', "Base [kPa]"), type: 'number', align: 'right' },
				],
				rows,
				emptyMessage: localize('u6d.sub.base.empty', "No BIM walls extend below the ground datum."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.excavationReport',
	title: localize('u6d.sub.exc.title', "Retaining, Excavation & Temporary Works Audit"),
	part: 'substructure',
	icon: Codicon.checklist,
	help: localize('u6d.sub.exc.help', "Reports all code design checks for retaining walls, excavations and slab formwork / shoring temporary works saved in 09 Substructure."),
	secondaryActions: openSubstructureAction(localize('u6d.sub.openSub', "Open Substructure")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('substructure/report', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = [];
		const pushGroup = (label: string, items: readonly unknown[]) => {
			for (const entry of items.map(asBag)) {
				const chks = asArray(entry.checks).map(asBag);
				if (!chks.length) {
					rows.push({
						category: label,
						id: str(entry.id),
						check: str(entry.kind || label),
						demand: '–',
						capacity: '–',
						utilisation: formatScalar(entry.utilisation),
						status: entry.ok === false ? 'Fail' : 'Pass',
					});
				} else {
					for (const c of chks) {
						rows.push({
							category: label,
							id: str(entry.id),
							check: str(c.name),
							demand: formatScalar(c.demand),
							capacity: formatScalar(c.capacity),
							utilisation: num(c.utilisation) ?? formatScalar(c.utilisation),
							status: c.ok === false ? 'Fail' : 'Pass',
						});
					}
				}
			}
		};
		pushGroup('Retaining Wall', asArray(raw.retainingWalls));
		pushGroup('Excavation', asArray(raw.excavations));
		pushGroup('Temporary Works', asArray(raw.temporaryWorks));
		return {
			metrics: [
				{ label: localize('u6d.sub.exc.mChecks', "Checks"), value: String(rows.length) },
				{ label: localize('u6d.sub.exc.mFail', "Failing"), value: String(rows.filter(r => r.status === 'Fail').length), tone: rows.some(r => r.status === 'Fail') ? 'fail' : 'ok' },
			],
			tables: [{
				id: 'retainingExcavation',
				title: localize('u6d.sub.exc.tab', "Retaining Walls, Excavations & Shoring Checks"),
				columns: [
					{ key: 'category', title: localize('u6d.sub.exc.colCat', "Category") },
					{ key: 'id', title: localize('u6d.sub.exc.colId', "ID") },
					{ key: 'check', title: localize('u6d.sub.exc.colChk', "Check") },
					{ key: 'demand', title: localize('u6d.sub.exc.colDem', "Demand") },
					{ key: 'capacity', title: localize('u6d.sub.exc.colCap', "Capacity") },
					{ key: 'utilisation', title: localize('u6d.sub.exc.colUtil', "Util.") },
					{ key: 'status', title: localize('u6d.sub.exc.colStat', "Status"), type: 'status' },
				],
				rows,
				emptyMessage: localize('u6d.sub.exc.empty', "No retaining walls, excavations or temporary works checks in 09 Substructure."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Ground Slabs, Machine Foundations & Report

registerSubstructurePanel({
	id: 'saengine.substructure.groundSlabCalc',
	title: localize('u6d.sub.gslab.title', "Slab on Grade Westergaard & Punching Calculator"),
	part: 'substructure',
	icon: Codicon.symbolNumeric,
	help: localize('u6d.sub.gslab.help', "Evaluates Westergaard interior/edge/corner wheel or racking post bending stresses, punching shear, and shrinkage reinforcement for ground-bearing slabs."),
	fields: [
		{ key: 'thicknessMm', label: localize('u6d.sub.gslab.t', "Slab Thickness [mm]"), type: 'number', defaultValue: 150, min: 75 },
		{ key: 'fcMpa', label: localize('u6d.sub.gslab.fc', "Concrete f'c [MPa]"), type: 'number', defaultValue: 25, min: 15 },
		{ key: 'subgradeKnM3', label: localize('u6d.sub.gslab.k', "Subgrade Modulus k [kN/m³]"), type: 'number', defaultValue: 30000, min: 5000 },
		{ key: 'pointLoadKn', label: localize('u6d.sub.gslab.p', "Point / Wheel Load [kN]"), type: 'number', defaultValue: 50, min: 0 },
		{ key: 'contactSideMm', label: localize('u6d.sub.gslab.c', "Contact Plate Side [mm]"), type: 'number', defaultValue: 150, min: 50 },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('substructure/groundSlab', {
			projectRoot: ctx.project!.root.fsPath,
			thicknessMm: Number(values.thicknessMm) || 150,
			fcMpa: Number(values.fcMpa) || 25,
			subgradeKnM3: Number(values.subgradeKnM3) || 30000,
			pointLoadKn: Number(values.pointLoadKn ?? 50),
			contactSideMm: Number(values.contactSideMm) || 150,
		}));
		const chks = asArray(raw.checks).map(asBag).map(c => ({
			name: str(c.name),
			demand: formatScalar(c.demand),
			capacity: formatScalar(c.capacity),
			unit: str(c.unit, '–'),
			utilisation: num(c.utilisation) ?? formatScalar(c.utilisation),
			status: c.ok === false ? 'Fail' : 'Pass',
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.gslab.mL', "Radius of Stiffness l [mm]"), value: formatScalar(raw.relativeStiffnessMm) },
				{ label: localize('u6d.sub.gslab.mFr', "Flexural fr [MPa]"), value: formatScalar(raw.frMpa) },
			],
			tables: [{
				id: 'checks',
				title: localize('u6d.sub.gslab.tab', "Ground Slab Structural Checks"),
				columns: [
					{ key: 'name', title: localize('u6d.sub.gslab.colName', "Check") },
					{ key: 'demand', title: localize('u6d.sub.gslab.colDem', "Demand") },
					{ key: 'capacity', title: localize('u6d.sub.gslab.colCap', "Capacity") },
					{ key: 'unit', title: localize('u6d.sub.gslab.colUnit', "Unit") },
					{ key: 'utilisation', title: localize('u6d.sub.gslab.colUtil', "Util."), type: 'number', align: 'right' },
					{ key: 'status', title: localize('u6d.sub.gslab.colStat', "Status"), type: 'status' },
				],
				rows: chks,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.machineReport',
	title: localize('u6d.sub.mach.title', "Machine Foundations Dynamic & Ground Slab Checks"),
	part: 'substructure',
	icon: Codicon.pulse,
	help: localize('u6d.sub.mach.help', "Inspects natural frequencies, resonance speed ratios, vibration amplitudes and checks for saved machine block foundations and ground slabs."),
	secondaryActions: openSubstructureAction(localize('u6d.sub.openSub', "Open Substructure")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('substructure/report', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = [];
		for (const item of [...asArray(raw.machineFoundations), ...asArray(raw.groundSlabs)].map(asBag)) {
			const chks = asArray(item.checks).map(asBag);
			if (!chks.length) {
				rows.push({ id: str(item.id), check: str(item.type || 'Item'), demand: '–', capacity: '–', utilisation: formatScalar(item.utilisation), status: item.ok === false ? 'Fail' : 'Pass' });
			} else {
				for (const c of chks) {
					rows.push({
						id: str(item.id),
						check: str(c.name),
						demand: formatScalar(c.demand),
						capacity: formatScalar(c.capacity),
						utilisation: formatScalar(c.utilisation),
						status: c.ok === false ? 'Fail' : 'Pass',
					});
				}
			}
		}
		return {
			metrics: [
				{ label: localize('u6d.sub.mach.mItems', "Special Checks"), value: String(rows.length) },
			],
			tables: [{
				id: 'special',
				title: localize('u6d.sub.mach.tab', "Machine Foundation & Ground Slab Checks"),
				columns: [
					{ key: 'id', title: localize('u6d.sub.mach.colId', "ID") },
					{ key: 'check', title: localize('u6d.sub.mach.colChk', "Check") },
					{ key: 'demand', title: localize('u6d.sub.mach.colDem', "Demand") },
					{ key: 'capacity', title: localize('u6d.sub.mach.colCap', "Capacity") },
					{ key: 'utilisation', title: localize('u6d.sub.mach.colUtil', "Util.") },
					{ key: 'status', title: localize('u6d.sub.mach.colStat', "Status"), type: 'status' },
				],
				rows,
				emptyMessage: localize('u6d.sub.mach.empty', "No machine foundations or ground slabs entered in 09 Substructure."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.designSummary',
	title: localize('u6d.sub.rep.title', "Substructure Design Report Summary"),
	part: 'substructure',
	icon: Codicon.report,
	help: localize('u6d.sub.rep.help', "Summarizes governing checks across every footing, raft, pile cap, tie beam and skipped item in 09 Substructure."),
	secondaryActions: openSubstructureAction(localize('u6d.sub.openSub', "Open Substructure")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('substructure/report', { projectRoot: ctx.project!.root.fsPath }));
		const fnds = [...asArray(raw.foundations), ...asArray(raw.tieBeams)].map(asBag);
		const skipped = asArray(raw.skipped).map(asBag);
		const summary = asBag(raw.summary);
		const rows: DataPanelRow[] = fnds.map(f => ({
			id: str(f.id),
			type: str(f.type, 'footing'),
			columns: asStrings(f.columns).join(', ') || '–',
			utilisation: num(f.utilisation) !== undefined ? Number((num(f.utilisation)! * 100).toFixed(1)) : '–',
			checksCount: asArray(f.checks).length,
			status: f.ok === false ? 'Fail' : 'Pass',
		}));
		const skipRows: DataPanelRow[] = skipped.map(s => ({
			id: str(s.id),
			type: str(s.type, '–'),
			reason: str(s.reason, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.rep.mPass', "Passing"), value: String(summary.passing ?? rows.filter(r => r.status === 'Pass').length), tone: 'ok' },
				{ label: localize('u6d.sub.rep.mFail', "Failing"), value: String(summary.failing ?? rows.filter(r => r.status === 'Fail').length), tone: rows.some(r => r.status === 'Fail') ? 'fail' : 'ok' },
				{ label: localize('u6d.sub.rep.mSkip', "Skipped"), value: String(skipRows.length), tone: skipRows.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'foundations',
					title: localize('u6d.sub.rep.tab', "Designed Foundations & Tie Beams"),
					columns: [
						{ key: 'id', title: localize('u6d.sub.rep.colId', "ID") },
						{ key: 'type', title: localize('u6d.sub.rep.colType', "Type") },
						{ key: 'columns', title: localize('u6d.sub.rep.colCols', "Supports") },
						{ key: 'utilisation', title: localize('u6d.sub.rep.colUtil', "Max Util. [%]"), type: 'number', align: 'right' },
						{ key: 'checksCount', title: localize('u6d.sub.rep.colChks', "Checks"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u6d.sub.rep.colStat', "Status"), type: 'status' },
					],
					rows,
				},
				{
					id: 'skipped',
					title: localize('u6d.sub.rep.skipTab', "Skipped Items"),
					columns: [
						{ key: 'id', title: localize('u6d.sub.rep.colSId', "ID") },
						{ key: 'type', title: localize('u6d.sub.rep.colSType', "Type") },
						{ key: 'reason', title: localize('u6d.sub.rep.colSReas', "Reason") },
					],
					rows: skipRows,
					emptyMessage: localize('u6d.sub.rep.noSkip', "No skipped substructure items."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSubstructurePanel({
	id: 'saengine.substructure.limitState',
	title: localize('u6d.sub.ls.title', "Geotechnical Limit State & Correlation Factors"),
	part: 'substructure',
	icon: Codicon.law,
	help: localize('u6d.sub.ls.help', "Reports active code pack limit-state partial factors (Design Approach combinations) and pile correlation factors ξ vs borehole count."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('substructure/limitState', { projectRoot: ctx.project!.root.fsPath }));
		const combos = asArray(raw.combinations).map(asBag).map(c => ({
			name: str(c.name || c.id || c.label),
			approach: str(c.approach || raw.designApproach, '–'),
			factors: Object.entries(c).filter(([k]) => !['name', 'id', 'label', 'approach'].includes(k)).map(([k, v]) => `${k}=${formatScalar(v)}`).join(', '),
		}));
		const corrs = asArray(raw.correlations).map(asBag).map(c => ({
			n: num(c.n) ?? 0,
			xiBase: num(c.xiBase) ?? 0,
			xiLoadTest: num(c.xiLoadTest) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.sub.ls.mCov', "Limit-State Mode"), value: raw.covered ? str(raw.designApproach, 'Enabled') : 'Allowable Stress' },
				{ label: localize('u6d.sub.ls.mCombos', "Combinations"), value: String(combos.length) },
			],
			tables: [
				{
					id: 'combinations',
					title: localize('u6d.sub.ls.tab', "Geotechnical ULS Partial Factor Sets"),
					columns: [
						{ key: 'name', title: localize('u6d.sub.ls.colName', "Combination") },
						{ key: 'approach', title: localize('u6d.sub.ls.colApp', "Approach") },
						{ key: 'factors', title: localize('u6d.sub.ls.colFac', "Partial Factors") },
					],
					rows: combos,
					emptyMessage: localize('u6d.sub.ls.working', "Working / allowable stress method active (no partial-factor sets)."),
				},
				{
					id: 'correlations',
					title: localize('u6d.sub.ls.corrTab', "Pile Correlation Factors ξ"),
					columns: [
						{ key: 'n', title: localize('u6d.sub.ls.colN', "Profiles / Tests (n)"), type: 'number', align: 'right' },
						{ key: 'xiBase', title: localize('u6d.sub.ls.colXib', "ξ (Boreholes)"), type: 'number', align: 'right' },
						{ key: 'xiLoadTest', title: localize('u6d.sub.ls.colXit', "ξ (Load Tests)"), type: 'number', align: 'right' },
					],
					rows: corrs,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion
