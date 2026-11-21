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
	if (typeof value === 'number' || typeof value === 'string') {
		return String(value);
	}
	return JSON.stringify(value);
}

function registerMepPanel(descriptor: IEngineDataPanelDescriptor): void {
	registerEngineDataPanel(descriptor);
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: descriptor.id,
				title: { value: descriptor.title, original: descriptor.title },
				category,
				icon: descriptor.icon,
				f1: true,
				precondition: projectOpen,
			});
		}

		override run(accessor: ServicesAccessor): Promise<unknown> {
			return openEngineDataPanel(accessor.get(IEditorService), descriptor.id);
		}
	});
}

function openMepSectionAction(section: 'electrical' | 'hvac' | 'fire' | 'plumbing', label: string): readonly IDataPanelAction[] {
	return [{
		id: `openMep.${section}`,
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand(`saengine.ribbon.openSection.mep.${section}`),
	}];
}

//#region Electrical Panels (5)

registerMepPanel({
	id: 'saengine.mep.electrical.boards',
	title: localize('u3.mep.boards.title', "Distribution Boards & Circuits"),
	part: 'mep',
	icon: Codicon.circuitBoard,
	help: localize('u3.mep.boards.help', "Evaluates distribution boards, phase balancing across L1/L2/L3, feeder cables, incomer ratings, and final circuit schedules."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.boards.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalCableSize', {
			projectRoot: ctx.project!.root.fsPath,
			mode: 'project',
		}));
		const boards = asArray(raw.boards).map(asBag);
		const circuits = asArray(raw.circuits).map(asBag);
		const maxImbalance = boards.reduce((mx, b) => Math.max(mx, num(b.imbalancePct) ?? 0), 0);
		const failingCircuits = circuits.filter(c => c.ok === false).length;

		const boardRows: DataPanelRow[] = boards.map(b => ({
			id: str(b.id),
			story: str(b.story),
			incomer: `${str(b.incomerType, 'MCCB')} ${str(b.incomerRating)} A`,
			busbarRating: num(b.busbarRating) ?? '–',
			ways: `${str(b.usedWays, '0')}/${str(b.ways, '0')}`,
			feeder: `${str(b.feederCableSize)} mm² ${str(b.feederConductor)} ${str(b.feederInsulation)}`,
			loadKw: num(b.totalLoadW) !== undefined ? Number(((num(b.totalLoadW) ?? 0) / 1000).toFixed(2)) : '–',
			imbalancePct: num(b.imbalancePct) ?? 0,
			ik3MaxKa: num(b.ik3MaxKa) ?? '–',
			status: b.ok === false ? 'Fail' : 'Pass',
		}));

		const circuitRows: DataPanelRow[] = circuits.map(c => ({
			board: str(c.board),
			way: num(c.way) ?? '–',
			id: str(c.id),
			description: str(c.description),
			phase: str(c.phase),
			loadW: num(c.loadW) ?? 0,
			ib: num(c.ib) ?? 0,
			device: `${str(c.deviceType, 'MCB')} ${str(c.curve)}${str(c.rating)}A`,
			cable: `${str(c.cableSize)} mm² ${str(c.conductor)} ${str(c.insulation)}`,
			cumVdPct: num(c.cumVdPct) ?? 0,
			status: c.ok === false ? 'Fail' : 'Pass',
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.boards.mBoards', "Boards"), value: String(boardRows.length), tone: boardRows.length ? 'ok' : 'warn' },
				{ label: localize('u3.mep.boards.mCircuits', "Circuits"), value: String(circuitRows.length) },
				{ label: localize('u3.mep.boards.mImbal', "Max Imbalance"), value: `${maxImbalance.toFixed(1)}%`, tone: maxImbalance > 15 ? 'warn' : 'ok' },
				{ label: localize('u3.mep.boards.mFailing', "Failing Circuits"), value: String(failingCircuits), tone: failingCircuits ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'boards',
					title: localize('u3.mep.boards.boardsTab', "Distribution Boards"),
					columns: [
						{ key: 'id', title: localize('u3.mep.boards.colBoardId', "Board") },
						{ key: 'story', title: localize('u3.mep.boards.colStory', "Story") },
						{ key: 'incomer', title: localize('u3.mep.boards.colIncomer', "Incomer") },
						{ key: 'busbarRating', title: localize('u3.mep.boards.colBusbar', "Busbar [A]"), type: 'number', align: 'right' },
						{ key: 'ways', title: localize('u3.mep.boards.colWays', "Ways") },
						{ key: 'feeder', title: localize('u3.mep.boards.colFeeder', "Feeder Cable") },
						{ key: 'loadKw', title: localize('u3.mep.boards.colLoadKw', "Load [kW]"), type: 'number', align: 'right' },
						{ key: 'imbalancePct', title: localize('u3.mep.boards.colImbal', "Imbalance [%]"), type: 'number', align: 'right' },
						{ key: 'ik3MaxKa', title: localize('u3.mep.boards.colIk3', "Ik3 [kA]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.boards.colBoardStatus', "Status"), type: 'status' },
					],
					rows: boardRows,
				},
				{
					id: 'circuits',
					title: localize('u3.mep.boards.circuitsTab', "Final Circuits"),
					columns: [
						{ key: 'board', title: localize('u3.mep.boards.colCBoard', "Board") },
						{ key: 'way', title: localize('u3.mep.boards.colWay', "Way"), type: 'number', align: 'right' },
						{ key: 'id', title: localize('u3.mep.boards.colCId', "Circuit") },
						{ key: 'description', title: localize('u3.mep.boards.colDesc', "Description") },
						{ key: 'phase', title: localize('u3.mep.boards.colPhase', "Phase") },
						{ key: 'loadW', title: localize('u3.mep.boards.colLoadW', "Load [W]"), type: 'number', align: 'right' },
						{ key: 'ib', title: localize('u3.mep.boards.colIb', "Ib [A]"), type: 'number', align: 'right' },
						{ key: 'device', title: localize('u3.mep.boards.colDevice', "Breaker") },
						{ key: 'cable', title: localize('u3.mep.boards.colCable', "Cable") },
						{ key: 'cumVdPct', title: localize('u3.mep.boards.colCumVd', "Cum. Vd [%]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.boards.colCStatus', "Status"), type: 'status' },
					],
					rows: circuitRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.cables',
	title: localize('u3.mep.cables.title', "Cable Sizing Calculator & Schedule"),
	part: 'mep',
	icon: Codicon.plug,
	help: localize('u3.mep.cables.help', "Size project circuit cables or run a standalone IEC 60364-5-52 cable sizing check with ambient/grouping derating and voltage drop."),
	fields: [
		{
			key: 'mode',
			label: localize('u3.mep.cables.mode', "Mode"),
			type: 'select',
			defaultValue: 'project',
			options: [
				{ value: 'project', label: localize('u3.mep.cables.modeProject', "Project Cable Schedule") },
				{ value: 'calculator', label: localize('u3.mep.cables.modeCalc', "Single Cable Calculator") },
			],
		},
		{ key: 'designCurrentA', label: localize('u3.mep.cables.ib', "Design Current Ib [A]"), type: 'number', defaultValue: 32, min: 0.1, visibleWhen: v => v.mode === 'calculator' },
		{ key: 'lengthM', label: localize('u3.mep.cables.len', "Length [m]"), type: 'number', defaultValue: 30, min: 0.5, visibleWhen: v => v.mode === 'calculator' },
		{
			key: 'phases',
			label: localize('u3.mep.cables.phases', "Phases"),
			type: 'select',
			defaultValue: '1',
			options: [
				{ value: '1', label: localize('u3.mep.cables.ph1', "1-Phase (230 V)") },
				{ value: '3', label: localize('u3.mep.cables.ph3', "3-Phase (400 V)") },
			],
			visibleWhen: v => v.mode === 'calculator',
		},
		{
			key: 'conductor',
			label: localize('u3.mep.cables.cond', "Conductor"),
			type: 'select',
			defaultValue: 'Cu',
			options: [{ value: 'Cu', label: 'Cu' }, { value: 'Al', label: 'Al' }],
			visibleWhen: v => v.mode === 'calculator',
		},
		{
			key: 'insulation',
			label: localize('u3.mep.cables.ins', "Insulation"),
			type: 'select',
			defaultValue: 'PVC',
			options: [{ value: 'PVC', label: 'PVC (70°C)' }, { value: 'XLPE', label: 'XLPE (90°C)' }],
			visibleWhen: v => v.mode === 'calculator',
		},
		{
			key: 'installationMethod',
			label: localize('u3.mep.cables.instMethod', "Method"),
			type: 'select',
			defaultValue: 'C',
			options: [
				{ value: 'C', label: localize('u3.mep.cables.methC', "C (Clipped direct)") },
				{ value: 'B', label: localize('u3.mep.cables.methB', "B (Conduit / trunking)") },
				{ value: 'E', label: localize('u3.mep.cables.methE', "E (Free air / tray)") },
				{ value: 'D', label: localize('u3.mep.cables.methD', "D (Buried in ground)") },
			],
			visibleWhen: v => v.mode === 'calculator',
		},
		{ key: 'ambientC', label: localize('u3.mep.cables.amb', "Ambient [°C]"), type: 'number', defaultValue: 35, visibleWhen: v => v.mode === 'calculator' },
		{ key: 'groupedCircuits', label: localize('u3.mep.cables.grp', "Grouped Circuits"), type: 'number', defaultValue: 1, min: 1, visibleWhen: v => v.mode === 'calculator' },
		{ key: 'vdLimitPct', label: localize('u3.mep.cables.vdLim', "Vd Limit [%]"), type: 'number', defaultValue: 4, min: 0.5, visibleWhen: v => v.mode === 'calculator' },
	],
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.cables.openSec', "Open MEP Electrical")),
	run: async (ctx, values) => {
		const mode = String(values.mode || 'project');
		const raw = asBag(await ctx.engineRequest('mep/electricalCableSize', {
			projectRoot: ctx.project!.root.fsPath,
			mode,
			designCurrentA: Number(values.designCurrentA) || 32,
			lengthM: Number(values.lengthM) || 30,
			phases: Number(values.phases) || 1,
			conductor: String(values.conductor || 'Cu'),
			insulation: String(values.insulation || 'PVC'),
			installationMethod: String(values.installationMethod || 'C'),
			ambientC: Number(values.ambientC) || 35,
			groupedCircuits: Number(values.groupedCircuits) || 1,
			vdLimitPct: Number(values.vdLimitPct) || 4,
		}));

		if (mode === 'calculator') {
			const r = asBag(raw.result);
			const ok = Boolean(r.ok);
			const rows: DataPanelRow[] = Object.keys(r).length ? [
				{ parameter: localize('u3.mep.cables.rSize', "Selected Cable Size"), value: `${str(r.size)} mm² (${str(r.conductor)} ${str(r.insulation)})`, status: ok ? 'Pass' : 'Fail' },
				{ parameter: localize('u3.mep.cables.rRec', "Recommended Size"), value: r.recommendedSize ? `${str(r.recommendedSize)} mm²` : 'None', status: r.recommendedSize ? 'OK' : 'Fail' },
				{ parameter: localize('u3.mep.cables.rIbIn', "Design Ib / Breaker In"), value: `${str(r.Ib)} A / ${str(r.In)} A`, status: r.ampacityOk ? 'Pass' : 'Fail' },
				{ parameter: localize('u3.mep.cables.rAmp', "Base It / Derated Iz"), value: `${str(r.It)} A / ${num(r.Iz)?.toFixed(1) ?? '–'} A`, status: r.ampacityOk ? 'Pass' : 'Fail' },
				{ parameter: localize('u3.mep.cables.rFactors', "Correction Factors (Ca / Cg / Ci)"), value: `${str(r.Ca)} / ${str(r.Cg)} / ${str(r.Ci)} (total ${num(r.factor)?.toFixed(3) ?? '–'})`, status: 'OK' },
				{ parameter: localize('u3.mep.cables.rVd', "Voltage Drop"), value: `${num(r.vdV)?.toFixed(2) ?? '–'} V (${num(r.vdPct)?.toFixed(2) ?? '–'}%)`, status: r.vdOk ? 'Pass' : 'Fail' },
				{ parameter: localize('u3.mep.cables.rLim', "Allowable Vd Limit"), value: `${str(r.vdLimitPct)}%`, status: r.vdOk ? 'Pass' : 'Fail' },
			] : [];
			return {
				metrics: [
					{ label: localize('u3.mep.cables.mSize', "Cable Size"), value: r.size ? `${str(r.size)} mm²` : '–', tone: ok ? 'ok' : 'fail' },
					{ label: localize('u3.mep.cables.mIz', "Derated Iz"), value: num(r.Iz) !== undefined ? `${num(r.Iz)!.toFixed(1)} A` : '–' },
					{ label: localize('u3.mep.cables.mVd', "Voltage Drop"), value: num(r.vdPct) !== undefined ? `${num(r.vdPct)!.toFixed(2)}%` : '–', tone: r.vdOk ? 'ok' : 'fail' },
				],
				tables: [{
					id: 'calc',
					title: localize('u3.mep.cables.calcTab', "Cable Sizing Calculation"),
					columns: [
						{ key: 'parameter', title: localize('u3.mep.cables.colParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.cables.colVal', "Result") },
						{ key: 'status', title: localize('u3.mep.cables.colCalcStatus', "Check"), type: 'status' },
					],
					rows,
				}],
				notes: asStrings(raw.notes),
				problems: asStrings(raw.problems),
			};
		}

		const circuits = asArray(raw.circuits).map(asBag);
		const rows: DataPanelRow[] = circuits.map(c => ({
			board: str(c.board),
			id: str(c.id),
			description: str(c.description),
			ib: num(c.ib) ?? 0,
			rating: num(c.rating) ?? 0,
			cableSize: num(c.cableSize) ?? 0,
			cpcSize: num(c.cpcSize) ?? 0,
			Iz: num(c.Iz) ?? 0,
			cumVdPct: num(c.cumVdPct) ?? 0,
			recommendedSize: num(c.recommendedSize) ?? '–',
			status: c.ampacityOk && c.vdOk ? 'Pass' : 'Fail',
		}));
		const failing = rows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u3.mep.cables.mSchedCount', "Circuits Sized"), value: String(rows.length) },
				{ label: localize('u3.mep.cables.mSchedFail', "Failing Cables"), value: String(failing), tone: failing ? 'fail' : 'ok' },
			],
			tables: [{
				id: 'cables',
				title: localize('u3.mep.cables.schedTab', "Project Cable Schedule"),
				columns: [
					{ key: 'board', title: localize('u3.mep.cables.colBoard', "Board") },
					{ key: 'id', title: localize('u3.mep.cables.colId', "Circuit") },
					{ key: 'description', title: localize('u3.mep.cables.colDesc', "Description") },
					{ key: 'ib', title: localize('u3.mep.cables.colIb', "Ib [A]"), type: 'number', align: 'right' },
					{ key: 'rating', title: localize('u3.mep.cables.colIn', "In [A]"), type: 'number', align: 'right' },
					{ key: 'cableSize', title: localize('u3.mep.cables.colSize', "Cable [mm²]"), type: 'number', align: 'right' },
					{ key: 'cpcSize', title: localize('u3.mep.cables.colCpc', "CPC [mm²]"), type: 'number', align: 'right' },
					{ key: 'Iz', title: localize('u3.mep.cables.colIz', "Iz [A]"), type: 'number', align: 'right' },
					{ key: 'cumVdPct', title: localize('u3.mep.cables.colCumVd', "Cum. Vd [%]"), type: 'number', align: 'right' },
					{ key: 'recommendedSize', title: localize('u3.mep.cables.colRec', "Rec. [mm²]"), type: 'number', align: 'right' },
					{ key: 'status', title: localize('u3.mep.cables.colStatus', "Status"), type: 'status' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.voltageDrop',
	title: localize('u3.mep.vd.title', "Voltage Drop Audit"),
	part: 'mep',
	icon: Codicon.pulse,
	help: localize('u3.mep.vd.help', "Checks cumulative voltage drop (sub-main feeder + final circuit) across all boards and circuits against code pack voltage drop limits."),
	fields: [
		{ key: 'onlyFailing', label: localize('u3.mep.vd.onlyFailing', "Show failing circuits only"), type: 'checkbox', defaultValue: false },
	],
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.vd.openSec', "Open MEP Electrical")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/electricalCableSize', {
			projectRoot: ctx.project!.root.fsPath,
			mode: 'project',
		}));
		const boards = asArray(raw.boards).map(asBag);
		const allCircuits = asArray(raw.circuits).map(asBag);
		const failingVd = asArray(raw.failingVd).map(asBag);
		const onlyFailing = Boolean(values.onlyFailing);
		const filtered = onlyFailing ? allCircuits.filter(c => c.vdOk === false) : allCircuits;
		const maxCumVd = allCircuits.reduce((mx, c) => Math.max(mx, num(c.cumVdPct) ?? 0), 0);

		const cktRows: DataPanelRow[] = filtered.map(c => ({
			board: str(c.board),
			id: str(c.id),
			description: str(c.description),
			kind: str(c.kind),
			length: num(c.length) ?? 0,
			cableSize: num(c.cableSize) ?? 0,
			vdV: num(c.vdV) ?? 0,
			vdPct: num(c.vdPct) ?? 0,
			cumVdPct: num(c.cumVdPct) ?? 0,
			vdLimitPct: num(c.vdLimitPct) ?? 0,
			recommendedSize: num(c.recommendedSize) ?? '–',
			status: c.vdOk ? 'Pass' : 'Fail',
		}));

		const feederRows: DataPanelRow[] = boards.map(b => ({
			id: str(b.id),
			story: str(b.story),
			feederLength: num(b.feederLength) ?? 0,
			feederCableSize: num(b.feederCableSize) ?? 0,
			feederVdPct: num(b.feederVdPct) ?? 0,
			upstreamVdPct: num(b.upstreamVdPct) ?? 0,
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.vd.mChecked', "Checked Circuits"), value: String(allCircuits.length) },
				{ label: localize('u3.mep.vd.mFailing', "Failing Vd"), value: String(failingVd.length), tone: failingVd.length ? 'fail' : 'ok' },
				{ label: localize('u3.mep.vd.mMax', "Max Cum. Vd"), value: `${maxCumVd.toFixed(2)}%`, tone: failingVd.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'circuits',
					title: localize('u3.mep.vd.circuitsTab', "Circuit Voltage Drop"),
					columns: [
						{ key: 'board', title: localize('u3.mep.vd.colBoard', "Board") },
						{ key: 'id', title: localize('u3.mep.vd.colId', "Circuit") },
						{ key: 'description', title: localize('u3.mep.vd.colDesc', "Description") },
						{ key: 'kind', title: localize('u3.mep.vd.colKind', "Kind") },
						{ key: 'length', title: localize('u3.mep.vd.colLen', "Length [m]"), type: 'number', align: 'right' },
						{ key: 'cableSize', title: localize('u3.mep.vd.colSize', "Cable [mm²]"), type: 'number', align: 'right' },
						{ key: 'vdV', title: localize('u3.mep.vd.colVdV', "Vd [V]"), type: 'number', align: 'right' },
						{ key: 'vdPct', title: localize('u3.mep.vd.colVdPct', "Run Vd [%]"), type: 'number', align: 'right' },
						{ key: 'cumVdPct', title: localize('u3.mep.vd.colCumVd', "Cum. Vd [%]"), type: 'number', align: 'right' },
						{ key: 'vdLimitPct', title: localize('u3.mep.vd.colLimit', "Limit [%]"), type: 'number', align: 'right' },
						{ key: 'recommendedSize', title: localize('u3.mep.vd.colRec', "Rec. [mm²]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.vd.colStatus', "Status"), type: 'status' },
					],
					rows: cktRows,
					emptyMessage: localize('u3.mep.vd.empty', "No circuits match the current voltage drop filter."),
				},
				{
					id: 'feeders',
					title: localize('u3.mep.vd.feedersTab', "Sub-Main Feeders"),
					columns: [
						{ key: 'id', title: localize('u3.mep.vd.colFBoard', "Board") },
						{ key: 'story', title: localize('u3.mep.vd.colFStory', "Story") },
						{ key: 'feederLength', title: localize('u3.mep.vd.colFLen', "Feeder [m]"), type: 'number', align: 'right' },
						{ key: 'feederCableSize', title: localize('u3.mep.vd.colFSize', "Cable [mm²]"), type: 'number', align: 'right' },
						{ key: 'feederVdPct', title: localize('u3.mep.vd.colFVd', "Feeder Vd [%]"), type: 'number', align: 'right' },
						{ key: 'upstreamVdPct', title: localize('u3.mep.vd.colUpVd', "Upstream Cum. Vd [%]"), type: 'number', align: 'right' },
					],
					rows: feederRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.shortCircuit',
	title: localize('u3.mep.sc.title', "Short-Circuit & Fault Protection"),
	part: 'mep',
	icon: Codicon.symbolEvent,
	help: localize('u3.mep.sc.help', "Reports IEC 60909 prospective fault currents (Ik3 / Ik1), breaker breaking capacity (Icu), and earth-fault loop impedance (Zs) disconnection checks."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.sc.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalCableSize', {
			projectRoot: ctx.project!.root.fsPath,
			mode: 'project',
		}));
		const boards = asArray(raw.boards).map(asBag);
		const circuits = asArray(raw.circuits).map(asBag);
		const source = asBag(raw.shortCircuit);

		const maxIk3 = boards.reduce((mx, b) => Math.max(mx, num(b.ik3MaxKa) ?? 0), 0);
		const faultFailures = boards.filter(b => b.incomerBreakingOk === false).length
			+ circuits.filter(c => c.breakingOk === false || c.disconnectionOk === false || c.faultOk === false).length;

		const boardRows: DataPanelRow[] = boards.map(b => ({
			id: str(b.id),
			story: str(b.story),
			incomer: `${str(b.incomerType, 'MCCB')} ${str(b.incomerRating)} A`,
			ik3MaxKa: num(b.ik3MaxKa) ?? 0,
			ik1MinKa: num(b.ik1MinKa) ?? 0,
			zsOhm: num(b.zsOhm) ?? 0,
			status: b.incomerBreakingOk === false ? 'Fail' : 'Pass',
		}));

		const cktRows: DataPanelRow[] = circuits.map(c => ({
			board: str(c.board),
			id: str(c.id),
			device: `${str(c.deviceType, 'MCB')} ${str(c.curve)}${str(c.rating)}A`,
			breakingCapacityKa: num(c.breakingCapacityKa) ?? 0,
			endZsOhm: num(c.endZsOhm) ?? 0,
			zsMaxOhm: num(c.zsMaxOhm) ?? 0,
			breakingOk: c.breakingOk ? 'Pass' : 'Fail',
			disconnectionOk: c.disconnectionOk ? 'Pass' : 'Fail',
			note: str(c.note, '–'),
		}));

		const sourceRows: DataPanelRow[] = Object.entries(source).map(([k, v]) => ({
			property: k,
			value: formatScalar(v),
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.sc.mMaxIk3', "Max Board Ik3"), value: `${maxIk3.toFixed(2)} kA` },
				{ label: localize('u3.mep.sc.mBoards', "Boards Checked"), value: String(boardRows.length) },
				{ label: localize('u3.mep.sc.mFails', "Fault Failures"), value: String(faultFailures), tone: faultFailures ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'boards',
					title: localize('u3.mep.sc.boardsTab', "Board Fault Levels"),
					columns: [
						{ key: 'id', title: localize('u3.mep.sc.colBoard', "Board") },
						{ key: 'story', title: localize('u3.mep.sc.colStory', "Story") },
						{ key: 'incomer', title: localize('u3.mep.sc.colIncomer', "Incomer") },
						{ key: 'ik3MaxKa', title: localize('u3.mep.sc.colIk3', "Ik3 Max [kA]"), type: 'number', align: 'right' },
						{ key: 'ik1MinKa', title: localize('u3.mep.sc.colIk1', "Ik1 Min [kA]"), type: 'number', align: 'right' },
						{ key: 'zsOhm', title: localize('u3.mep.sc.colZs', "Zs [Ω]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.sc.colBStatus', "Breaking"), type: 'status' },
					],
					rows: boardRows,
				},
				{
					id: 'circuits',
					title: localize('u3.mep.sc.circuitsTab', "Circuit Protection & Zs"),
					columns: [
						{ key: 'board', title: localize('u3.mep.sc.colCBoard', "Board") },
						{ key: 'id', title: localize('u3.mep.sc.colCId', "Circuit") },
						{ key: 'device', title: localize('u3.mep.sc.colDevice', "Device") },
						{ key: 'breakingCapacityKa', title: localize('u3.mep.sc.colIcu', "Icu [kA]"), type: 'number', align: 'right' },
						{ key: 'endZsOhm', title: localize('u3.mep.sc.colEndZs', "End Zs [Ω]"), type: 'number', align: 'right' },
						{ key: 'zsMaxOhm', title: localize('u3.mep.sc.colMaxZs', "Max Zs [Ω]"), type: 'number', align: 'right' },
						{ key: 'breakingOk', title: localize('u3.mep.sc.colBrkOk', "Breaking"), type: 'status' },
						{ key: 'disconnectionOk', title: localize('u3.mep.sc.colDiscOk', "Disconnection"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.sc.colNote', "Note") },
					],
					rows: cktRows,
				},
				{
					id: 'source',
					title: localize('u3.mep.sc.sourceTab', "Transformer Source"),
					columns: [
						{ key: 'property', title: localize('u3.mep.sc.colSrcProp', "Property") },
						{ key: 'value', title: localize('u3.mep.sc.colSrcVal', "Value") },
					],
					rows: sourceRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.lighting',
	title: localize('u3.mep.light.title', "Interior Lighting Design"),
	part: 'mep',
	icon: Codicon.lightbulb,
	help: localize('u3.mep.light.help', "Computes lumen-method luminaire counts, even grid spacing, achieved illuminance [lx], lighting power density [W/m²] and lighting circuits."),
	fields: [
		{
			key: 'luminaireType',
			label: localize('u3.mep.light.lumType', "Luminaire"),
			type: 'select',
			defaultValue: 'ledPanel600',
			options: [
				{ value: 'ledPanel600', label: localize('u3.mep.light.panel600', "LED Panel 600×600") },
				{ value: 'ledDownlight', label: localize('u3.mep.light.downlight', "LED Downlight") },
				{ value: 'ledBatten', label: localize('u3.mep.light.batten', "LED Batten") },
				{ value: 'highBay', label: localize('u3.mep.light.highBay', "LED High Bay") },
			],
		},
		{ key: 'maintenanceFactor', label: localize('u3.mep.light.mf', "Maintenance Factor"), type: 'number', defaultValue: 0.8, min: 0.4, max: 1, step: '0.05' },
		{ key: 'workPlaneM', label: localize('u3.mep.light.wp', "Work Plane [m]"), type: 'number', defaultValue: 0.8, min: 0, max: 2, step: '0.05' },
		{
			key: 'reflectance',
			label: localize('u3.mep.light.ref', "Reflectances (C/W/F)"),
			type: 'select',
			defaultValue: '70/50/20',
			options: [
				{ value: '70/50/20', label: '70 / 50 / 20' },
				{ value: '50/30/10', label: '50 / 30 / 10' },
				{ value: '70/30/10', label: '70 / 30 / 10' },
				{ value: '30/30/10', label: '30 / 30 / 10' },
			],
		},
	],
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.light.openSec', "Open MEP Electrical")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/electricalLighting', {
			projectRoot: ctx.project!.root.fsPath,
			luminaireType: String(values.luminaireType || 'ledPanel600'),
			maintenanceFactor: Number(values.maintenanceFactor) || 0.8,
			workPlaneM: Number(values.workPlaneM) || 0.8,
			reflectance: String(values.reflectance || '70/50/20'),
		}));
		const rooms = asArray(raw.rooms).map(asBag);
		const stories = asArray(raw.stories).map(asBag);
		const circuits = asArray(raw.circuits).map(asBag);

		const roomRows: DataPanelRow[] = rooms.map(r => {
			const target = num(r.targetLux) ?? 0;
			const achieved = num(r.achievedLux) ?? 0;
			return {
				story: str(r.story),
				label: str(r.label || r.room),
				use: str(r.use),
				area: num(r.area) ?? 0,
				targetLux: target,
				achievedLux: achieved,
				count: num(r.count) ?? 0,
				grid: `${str(r.nx, '1')}×${str(r.ny, '1')}`,
				lpd: num(r.lpd) ?? 0,
				status: achieved >= target - 1 ? 'Pass' : 'Warn',
			};
		});

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			area: num(s.area) ?? 0,
			count: num(s.count) ?? 0,
			kw: num(s.kw) ?? 0,
			lpd: num(s.lpd) ?? 0,
			circuits: num(s.circuits) ?? 0,
		}));

		const cktRows: DataPanelRow[] = circuits.map(c => ({
			id: str(c.id),
			story: str(c.story),
			luminaireCount: asArray(c.luminaires).length,
			watts: num(c.watts) ?? 0,
			amps: num(c.amps) ?? 0,
			mcbAmps: num(c.mcbAmps) ?? 0,
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.light.mLum', "Luminaires"), value: String(raw.luminaireCount ?? 0), tone: (num(raw.luminaireCount) ?? 0) > 0 ? 'ok' : 'warn' },
				{ label: localize('u3.mep.light.mKw', "Total Power"), value: `${str(raw.totalKw, '0')} kW` },
				{ label: localize('u3.mep.light.mRooms', "Rooms"), value: String(roomRows.length) },
				{ label: localize('u3.mep.light.mCircuits', "Circuits"), value: String(cktRows.length) },
			],
			tables: [
				{
					id: 'rooms',
					title: localize('u3.mep.light.roomsTab', "Room Lighting Design"),
					columns: [
						{ key: 'story', title: localize('u3.mep.light.colStory', "Story") },
						{ key: 'label', title: localize('u3.mep.light.colRoom', "Room") },
						{ key: 'use', title: localize('u3.mep.light.colUse', "Use") },
						{ key: 'area', title: localize('u3.mep.light.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'targetLux', title: localize('u3.mep.light.colTarget', "Target [lx]"), type: 'number', align: 'right' },
						{ key: 'achievedLux', title: localize('u3.mep.light.colAchieved', "Achieved [lx]"), type: 'number', align: 'right' },
						{ key: 'count', title: localize('u3.mep.light.colCount', "Qty"), type: 'number', align: 'right' },
						{ key: 'grid', title: localize('u3.mep.light.colGrid', "Grid") },
						{ key: 'lpd', title: localize('u3.mep.light.colLpd', "LPD [W/m²]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.light.colStatus', "Check"), type: 'status' },
					],
					rows: roomRows,
				},
				{
					id: 'stories',
					title: localize('u3.mep.light.storiesTab', "Story Summary"),
					columns: [
						{ key: 'story', title: localize('u3.mep.light.colSStory', "Story") },
						{ key: 'area', title: localize('u3.mep.light.colSArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'count', title: localize('u3.mep.light.colSQty', "Luminaires"), type: 'number', align: 'right' },
						{ key: 'kw', title: localize('u3.mep.light.colSKw', "Power [kW]"), type: 'number', align: 'right' },
						{ key: 'lpd', title: localize('u3.mep.light.colSLpd', "LPD [W/m²]"), type: 'number', align: 'right' },
						{ key: 'circuits', title: localize('u3.mep.light.colSCkt', "Circuits"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
				{
					id: 'circuits',
					title: localize('u3.mep.light.circuitsTab', "Lighting Circuits"),
					columns: [
						{ key: 'id', title: localize('u3.mep.light.colCId', "Circuit") },
						{ key: 'story', title: localize('u3.mep.light.colCStory', "Story") },
						{ key: 'luminaireCount', title: localize('u3.mep.light.colCLum', "Luminaires"), type: 'number', align: 'right' },
						{ key: 'watts', title: localize('u3.mep.light.colCWatts', "Load [W]"), type: 'number', align: 'right' },
						{ key: 'amps', title: localize('u3.mep.light.colCAmps', "Current [A]"), type: 'number', align: 'right' },
						{ key: 'mcbAmps', title: localize('u3.mep.light.colCMcb', "MCB [A]"), type: 'number', align: 'right' },
					],
					rows: cktRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region HVAC Panels (4)

registerMepPanel({
	id: 'saengine.mep.hvac.roomLoads',
	title: localize('u3.mep.roomLoads.title', "HVAC Room Cooling Loads"),
	part: 'mep',
	icon: Codicon.dashboard,
	help: localize('u3.mep.roomLoads.help', "Computes room-by-room or story-by-story sensible/latent cooling loads, ventilation airflow, and peak timing using EnergyPlus or SAEngine block estimates."),
	fields: [
		{
			key: 'zoning',
			label: localize('u3.mep.roomLoads.zoning', "Zoning"),
			type: 'select',
			defaultValue: 'room',
			options: [
				{ value: 'room', label: localize('u3.mep.roomLoads.zRoom', "Per Room") },
				{ value: 'story', label: localize('u3.mep.roomLoads.zStory', "Per Story") },
			],
		},
		{ key: 'useEnergyPlus', label: localize('u3.mep.roomLoads.useEp', "Run EnergyPlus (if installed)"), type: 'checkbox', defaultValue: false },
	],
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.roomLoads.openSec', "Open MEP HVAC")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/hvacLoadsDetailed', {
			projectRoot: ctx.project!.root.fsPath,
			zoning: String(values.zoning || 'room'),
			useEnergyPlus: Boolean(values.useEnergyPlus),
			annual: false,
		}));
		const zones = asArray(raw.zones).map(asBag);
		const stories = asArray(raw.stories).map(asBag);

		const zoneRows: DataPanelRow[] = zones.map(z => ({
			story: str(z.story),
			zone: str(z.roomLabel || z.room || z.zone),
			use: str(z.use),
			area: num(z.area) ?? 0,
			sensible: num(z.sensible) ?? 0,
			latent: num(z.latent) ?? 0,
			total: num(z.total) ?? 0,
			density: num(z.density) ?? 0,
			airflow: num(z.airflow) ?? 0,
			outdoorAir: num(z.outdoorAir) ?? 0,
			peak: [str(z.peakMonth), str(z.peakHour)].filter(Boolean).join(' ') || '–',
		}));

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			area: num(s.area) ?? 0,
			sensible: num(s.sensible) ?? 0,
			latent: num(s.latent) ?? 0,
			total: num(s.total) ?? 0,
			heating: num(s.heating) ?? 0,
			airflow: num(s.airflow) ?? 0,
			outdoorAir: num(s.outdoorAir) ?? 0,
		}));

		const totalKw = num(raw.total) ?? 0;
		const tons = num(raw.tons) ?? 0;
		const airflow = num(raw.airflow) ?? 0;
		return {
			metrics: [
				{ label: localize('u3.mep.roomLoads.mEngine', "Engine"), value: str(raw.engineLabel || raw.engine, '–') },
				{ label: localize('u3.mep.roomLoads.mTotal', "Total Cooling"), value: `${totalKw.toFixed(1)} kW (${tons.toFixed(1)} TR)`, tone: totalKw > 0 ? 'ok' : 'warn' },
				{ label: localize('u3.mep.roomLoads.mZones', "Zones"), value: String(zoneRows.length) },
				{ label: localize('u3.mep.roomLoads.mSupply', "Supply Air"), value: `${airflow.toFixed(2)} m³/s` },
			],
			tables: [
				{
					id: 'zones',
					title: localize('u3.mep.roomLoads.zonesTab', "Zone / Room Cooling Loads"),
					columns: [
						{ key: 'story', title: localize('u3.mep.roomLoads.colStory', "Story") },
						{ key: 'zone', title: localize('u3.mep.roomLoads.colZone', "Room / Zone") },
						{ key: 'use', title: localize('u3.mep.roomLoads.colUse', "Use") },
						{ key: 'area', title: localize('u3.mep.roomLoads.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'sensible', title: localize('u3.mep.roomLoads.colSens', "Sensible [kW]"), type: 'number', align: 'right' },
						{ key: 'latent', title: localize('u3.mep.roomLoads.colLat', "Latent [kW]"), type: 'number', align: 'right' },
						{ key: 'total', title: localize('u3.mep.roomLoads.colTot', "Total [kW]"), type: 'number', align: 'right' },
						{ key: 'density', title: localize('u3.mep.roomLoads.colDens', "W/m²"), type: 'number', align: 'right' },
						{ key: 'airflow', title: localize('u3.mep.roomLoads.colAir', "Supply [m³/s]"), type: 'number', align: 'right' },
						{ key: 'outdoorAir', title: localize('u3.mep.roomLoads.colOa', "OA [m³/s]"), type: 'number', align: 'right' },
						{ key: 'peak', title: localize('u3.mep.roomLoads.colPeak', "Peak") },
					],
					rows: zoneRows,
				},
				{
					id: 'stories',
					title: localize('u3.mep.roomLoads.storiesTab', "Story Totals"),
					columns: [
						{ key: 'story', title: localize('u3.mep.roomLoads.colSStory', "Story") },
						{ key: 'area', title: localize('u3.mep.roomLoads.colSArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'sensible', title: localize('u3.mep.roomLoads.colSSens', "Sensible [kW]"), type: 'number', align: 'right' },
						{ key: 'latent', title: localize('u3.mep.roomLoads.colSLat', "Latent [kW]"), type: 'number', align: 'right' },
						{ key: 'total', title: localize('u3.mep.roomLoads.colSTot', "Cooling [kW]"), type: 'number', align: 'right' },
						{ key: 'heating', title: localize('u3.mep.roomLoads.colSHeat', "Heating [kW]"), type: 'number', align: 'right' },
						{ key: 'airflow', title: localize('u3.mep.roomLoads.colSAir', "Supply [m³/s]"), type: 'number', align: 'right' },
						{ key: 'outdoorAir', title: localize('u3.mep.roomLoads.colSOa', "OA [m³/s]"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.hvac.heatingLoads',
	title: localize('u3.mep.heatLoads.title', "HVAC Heating Loads"),
	part: 'mep',
	icon: Codicon.flame,
	help: localize('u3.mep.heatLoads.help', "Computes steady-state design heating loads (fabric, glazing, infiltration/ventilation) and heating supply airflows per room or story."),
	fields: [
		{
			key: 'zoning',
			label: localize('u3.mep.heatLoads.zoning', "Zoning"),
			type: 'select',
			defaultValue: 'room',
			options: [
				{ value: 'room', label: localize('u3.mep.heatLoads.zRoom', "Per Room") },
				{ value: 'story', label: localize('u3.mep.heatLoads.zStory', "Per Story") },
			],
		},
	],
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.heatLoads.openSec', "Open MEP HVAC")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/hvacLoadsDetailed', {
			projectRoot: ctx.project!.root.fsPath,
			zoning: String(values.zoning || 'room'),
			useEnergyPlus: false,
			annual: false,
		}));
		const design = asBag(raw.design);
		const zones = asArray(raw.zones).map(asBag);
		const stories = asArray(raw.stories).map(asBag);

		const zoneRows: DataPanelRow[] = zones.map(z => {
			const hb = asBag(z.heatingBreakdown);
			const summary = Object.entries(hb).map(([k, v]) => `${k}: ${formatScalar(v)} kW`).join(', ');
			return {
				story: str(z.story),
				zone: str(z.roomLabel || z.room || z.zone),
				area: num(z.area) ?? 0,
				heatingIndoorDB: num(z.heatingIndoorDB) ?? '–',
				heating: num(z.heating) ?? 0,
				heatingAirflow: num(z.heatingAirflow) ?? 0,
				breakdown: summary || '–',
			};
		});

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			area: num(s.area) ?? 0,
			heating: num(s.heating) ?? 0,
			cooling: num(s.total) ?? 0,
		}));

		const heatingTotal = num(raw.heatingTotal) ?? 0;
		const outdoorHeatDb = num(design.heatingOutdoorDB);
		return {
			metrics: [
				{ label: localize('u3.mep.heatLoads.mTotal', "Total Heating"), value: `${heatingTotal.toFixed(1)} kW`, tone: heatingTotal > 0 ? 'ok' : 'neutral' },
				{ label: localize('u3.mep.heatLoads.mOutdoor', "Outdoor Heating DB"), value: outdoorHeatDb !== undefined ? `${outdoorHeatDb} °C` : '–' },
				{ label: localize('u3.mep.heatLoads.mZones', "Zones"), value: String(zoneRows.length) },
			],
			tables: [
				{
					id: 'zones',
					title: localize('u3.mep.heatLoads.zonesTab', "Zone Heating Loads"),
					columns: [
						{ key: 'story', title: localize('u3.mep.heatLoads.colStory', "Story") },
						{ key: 'zone', title: localize('u3.mep.heatLoads.colZone', "Room / Zone") },
						{ key: 'area', title: localize('u3.mep.heatLoads.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'heatingIndoorDB', title: localize('u3.mep.heatLoads.colIndoor', "Indoor [°C]"), type: 'number', align: 'right' },
						{ key: 'heating', title: localize('u3.mep.heatLoads.colHeat', "Heating [kW]"), type: 'number', align: 'right' },
						{ key: 'heatingAirflow', title: localize('u3.mep.heatLoads.colAir', "Airflow [m³/s]"), type: 'number', align: 'right' },
						{ key: 'breakdown', title: localize('u3.mep.heatLoads.colBreakdown', "Loss Breakdown") },
					],
					rows: zoneRows,
				},
				{
					id: 'stories',
					title: localize('u3.mep.heatLoads.storiesTab', "Story Summary"),
					columns: [
						{ key: 'story', title: localize('u3.mep.heatLoads.colSStory', "Story") },
						{ key: 'area', title: localize('u3.mep.heatLoads.colSArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'heating', title: localize('u3.mep.heatLoads.colSHeat', "Heating [kW]"), type: 'number', align: 'right' },
						{ key: 'cooling', title: localize('u3.mep.heatLoads.colSCool', "Cooling [kW]"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.hvac.ductPressure',
	title: localize('u3.mep.ductP.title', "Duct Pressure Loss & Critical Path"),
	part: 'mep',
	icon: Codicon.compass,
	help: localize('u3.mep.ductP.help', "Computes Darcy-Weisbach friction loss, fitting dynamic losses, critical path total pressure and fan static pressure across the duct network."),
	fields: [
		{
			key: 'method',
			label: localize('u3.mep.ductP.method', "Sizing Method"),
			type: 'select',
			defaultValue: 'equalFriction',
			options: [
				{ value: 'equalFriction', label: localize('u3.mep.ductP.mEq', "Equal Friction") },
				{ value: 'staticRegain', label: localize('u3.mep.ductP.mSr', "Static Regain") },
				{ value: 'velocityReduction', label: localize('u3.mep.ductP.mVr', "Velocity Reduction") },
			],
		},
		{ key: 'frictionRate', label: localize('u3.mep.ductP.rate', "Friction Rate [Pa/m]"), type: 'number', defaultValue: 1.0, min: 0.2, step: '0.1' },
		{
			key: 'material',
			label: localize('u3.mep.ductP.mat', "Material"),
			type: 'select',
			defaultValue: '',
			options: [
				{ value: '', label: localize('u3.mep.ductP.matDefault', "Default (from duct / pack)") },
				{ value: 'galvanizedSteel', label: localize('u3.mep.ductP.matSteel', "Galvanized Steel") },
				{ value: 'aluminum', label: localize('u3.mep.ductP.matAl', "Aluminum") },
				{ value: 'flexible', label: localize('u3.mep.ductP.matFlex', "Flexible Duct") },
			],
		},
	],
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.ductP.openSec', "Open MEP HVAC")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/hvacDuctPressure', {
			projectRoot: ctx.project!.root.fsPath,
			method: String(values.method || 'equalFriction'),
			frictionRate: Number(values.frictionRate) || 1.0,
			material: String(values.material || '') || undefined,
		}));
		const ducts = asArray(raw.ducts);
		const pressure = asBag(raw.pressure);
		const segments = asArray(pressure.segments).map(asBag);
		const paths = asArray(pressure.paths).map(asBag);
		const critPath = asStrings(pressure.criticalPath);

		const segRows: DataPanelRow[] = segments.map(s => ({
			id: str(s.id),
			flow: num(s.flow) ?? 0,
			length: num(s.length) ?? 0,
			velocity: num(s.velocity) ?? 0,
			frictionGradient: num(s.frictionGradient) ?? 0,
			frictionLoss: num(s.frictionLoss) ?? 0,
			fittingLoss: num(s.fittingLoss) ?? 0,
			totalLoss: num(s.totalLoss) ?? 0,
		}));

		const pathRows: DataPanelRow[] = paths.map(p => ({
			leaf: str(p.leaf),
			path: asStrings(p.path).join(' -> '),
			frictionLoss: num(p.frictionLoss) ?? 0,
			fittingLoss: num(p.fittingLoss) ?? 0,
			totalPressure: num(p.totalPressure) ?? 0,
			balancingExcess: num(p.balancingExcess) ?? 0,
		}));

		const emptyState = !ducts.length ? {
			title: localize('u3.mep.ductP.emptyTitle', "No ducts in 07 MEP yet"),
			text: localize('u3.mep.ductP.emptyText', "Auto-route ducts or add duct segments in 07 MEP to evaluate friction, fitting losses and fan static pressure."),
			action: {
				id: 'routeDucts',
				label: localize('u3.mep.ductP.goRoute', "Open Auto-Route Ducts"),
				icon: Codicon.wand,
				run: () => void openEngineDataPanel(ctx.editorService, 'saengine.mep.hvac.routeDucts'),
			},
		} : undefined;

		return {
			metrics: [
				{ label: localize('u3.mep.ductP.mFan', "Fan Static Pressure"), value: `${(num(pressure.fanStaticPressure) ?? 0).toFixed(1)} Pa`, tone: segments.length ? 'ok' : 'neutral' },
				{ label: localize('u3.mep.ductP.mCrit', "Critical Total"), value: `${(num(pressure.criticalTotalPressure) ?? 0).toFixed(1)} Pa` },
				{ label: localize('u3.mep.ductP.mSegs', "Segments"), value: String(segRows.length) },
				{ label: localize('u3.mep.ductP.mPath', "Critical Path"), value: critPath.join(' -> ') || '–' },
			],
			tables: [
				{
					id: 'segments',
					title: localize('u3.mep.ductP.segsTab', "Duct Segments"),
					columns: [
						{ key: 'id', title: localize('u3.mep.ductP.colId', "Segment") },
						{ key: 'flow', title: localize('u3.mep.ductP.colFlow', "Flow [m³/s]"), type: 'number', align: 'right' },
						{ key: 'length', title: localize('u3.mep.ductP.colLen', "Length [m]"), type: 'number', align: 'right' },
						{ key: 'velocity', title: localize('u3.mep.ductP.colVel', "Velocity [m/s]"), type: 'number', align: 'right' },
						{ key: 'frictionGradient', title: localize('u3.mep.ductP.colGrad', "dP/L [Pa/m]"), type: 'number', align: 'right' },
						{ key: 'frictionLoss', title: localize('u3.mep.ductP.colFric', "Friction [Pa]"), type: 'number', align: 'right' },
						{ key: 'fittingLoss', title: localize('u3.mep.ductP.colFit', "Fittings [Pa]"), type: 'number', align: 'right' },
						{ key: 'totalLoss', title: localize('u3.mep.ductP.colTot', "Total [Pa]"), type: 'number', align: 'right' },
					],
					rows: segRows,
				},
				{
					id: 'paths',
					title: localize('u3.mep.ductP.pathsTab', "Index & Branch Paths"),
					columns: [
						{ key: 'leaf', title: localize('u3.mep.ductP.colLeaf', "Terminal") },
						{ key: 'path', title: localize('u3.mep.ductP.colChain', "Duct Path") },
						{ key: 'frictionLoss', title: localize('u3.mep.ductP.colPFric', "Friction [Pa]"), type: 'number', align: 'right' },
						{ key: 'fittingLoss', title: localize('u3.mep.ductP.colPFit', "Fittings [Pa]"), type: 'number', align: 'right' },
						{ key: 'totalPressure', title: localize('u3.mep.ductP.colPTot', "Total [Pa]"), type: 'number', align: 'right' },
						{ key: 'balancingExcess', title: localize('u3.mep.ductP.colBal', "Damper Drop [Pa]"), type: 'number', align: 'right' },
					],
					rows: pathRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
			emptyState,
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.hvac.routeDucts',
	title: localize('u3.mep.route.title', "Auto-Route HVAC Ducts"),
	part: 'mep',
	icon: Codicon.wand,
	autoRun: false,
	runLabel: localize('u3.mep.route.run', "Route Ducts"),
	help: localize('u3.mep.route.help', "Routes supply/return/exhaust duct trees from AHU/shaft to room diffusers through corridors while penalising structural beam crossings and checking ceiling void depth."),
	fields: [
		{ key: 'story', label: localize('u3.mep.route.story', "Story (blank = first)"), type: 'text', defaultValue: '', placeholder: localize('u3.mep.route.storyPh', "Optional story id") },
		{
			key: 'system',
			label: localize('u3.mep.route.system', "System"),
			type: 'select',
			defaultValue: 'supply',
			options: [
				{ value: 'supply', label: localize('u3.mep.route.sysSupply', "Supply") },
				{ value: 'return', label: localize('u3.mep.route.sysReturn', "Return") },
				{ value: 'exhaust', label: localize('u3.mep.route.sysExhaust', "Exhaust") },
			],
		},
		{
			key: 'shape',
			label: localize('u3.mep.route.shape', "Duct Shape"),
			type: 'select',
			defaultValue: 'rect',
			options: [
				{ value: 'rect', label: localize('u3.mep.route.shapeRect', "Rectangular") },
				{ value: 'round', label: localize('u3.mep.route.shapeRound', "Round") },
			],
		},
		{
			key: 'method',
			label: localize('u3.mep.route.method', "Sizing Method"),
			type: 'select',
			defaultValue: 'equalFriction',
			options: [
				{ value: 'equalFriction', label: localize('u3.mep.route.mEq', "Equal Friction") },
				{ value: 'staticRegain', label: localize('u3.mep.route.mSr', "Static Regain") },
				{ value: 'velocityReduction', label: localize('u3.mep.route.mVr', "Velocity Reduction") },
			],
		},
		{ key: 'frictionRate', label: localize('u3.mep.route.rate', "Friction Rate [Pa/m]"), type: 'number', defaultValue: 1.0, min: 0.2, step: '0.1' },
		{ key: 'beamPenalty', label: localize('u3.mep.route.penalty', "Beam Crossing Penalty [mm]"), type: 'number', defaultValue: 5000, min: 0, step: '500' },
		{ key: 'applyToMep', label: localize('u3.mep.route.apply', "Write routed ducts into 07 MEP/mep.json"), type: 'checkbox', defaultValue: false },
	],
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.route.openSec', "Open MEP HVAC")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/hvacRouteDucts', {
			projectRoot: ctx.project!.root.fsPath,
			story: String(values.story || '').trim() || undefined,
			system: String(values.system || 'supply'),
			shape: String(values.shape || 'rect'),
			method: String(values.method || 'equalFriction'),
			frictionRate: Number(values.frictionRate) || 1.0,
			beamPenalty: Number(values.beamPenalty) ?? 5000,
			applyToMep: Boolean(values.applyToMep),
		}));
		const ducts = asArray(raw.ducts).map(asBag);
		const pressure = asBag(raw.pressure);
		const beamsCrossed = asStrings(raw.beamsCrossed);
		const rows: DataPanelRow[] = ducts.map(d => {
			const sizeStr = d.diameter ? `Ø${str(d.diameter)} mm` : `${str(d.width)}×${str(d.height)} mm`;
			return {
				id: str(d.id),
				parent: str(d.parent, '–'),
				role: str(d.role),
				room: str(d.room, '–'),
				size: sizeStr,
				flow: num(d.flow) ?? 0,
				fittings: asStrings(d.fittings).join(', ') || '–',
			};
		});
		const applied = Boolean(raw.applied);
		return {
			metrics: [
				{ label: localize('u3.mep.route.mStory', "Story"), value: str(raw.story, '–') },
				{ label: localize('u3.mep.route.mSegs', "Segments"), value: String(rows.length), tone: rows.length ? 'ok' : 'warn' },
				{ label: localize('u3.mep.route.mLen', "Total Length"), value: `${num(raw.totalLength) ?? 0} m` },
				{ label: localize('u3.mep.route.mFan', "Fan Static"), value: `${(num(pressure.fanStaticPressure) ?? 0).toFixed(1)} Pa` },
				{ label: localize('u3.mep.route.mBeams', "Beams Crossed"), value: String(beamsCrossed.length), tone: beamsCrossed.length ? 'warn' : 'ok' },
				{ label: localize('u3.mep.route.mMode', "Mode"), value: applied ? localize('u3.mep.route.saved', "Saved to 07 MEP") : localize('u3.mep.route.preview', "Preview"), tone: applied ? 'ok' : 'neutral' },
			],
			tables: [{
				id: 'ducts',
				title: localize('u3.mep.route.ductsTab', "Routed Duct Segments"),
				columns: [
					{ key: 'id', title: localize('u3.mep.route.colId', "Duct") },
					{ key: 'parent', title: localize('u3.mep.route.colParent', "Parent") },
					{ key: 'role', title: localize('u3.mep.route.colRole', "Role") },
					{ key: 'room', title: localize('u3.mep.route.colRoom', "Room") },
					{ key: 'size', title: localize('u3.mep.route.colSize', "Size") },
					{ key: 'flow', title: localize('u3.mep.route.colFlow', "Flow [m³/s]"), type: 'number', align: 'right' },
					{ key: 'fittings', title: localize('u3.mep.route.colFittings', "Fittings") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Fire Protection Panels (2)

registerMepPanel({
	id: 'saengine.mep.fire.sprinklers',
	title: localize('u3.mep.spr.title', "Sprinkler Layout & Pipe Schedule"),
	part: 'mep',
	icon: Codicon.flame,
	help: localize('u3.mep.spr.help', "Places sprinkler heads per room and sizes branch and cross-main piping per NFPA 13 / BNBC 2020 Part 4."),
	fields: [
		{
			key: 'hazard',
			label: localize('u3.mep.spr.hazard', "Occupancy Hazard"),
			type: 'select',
			defaultValue: 'lightI',
			options: [
				{ value: 'lightI', label: localize('u3.mep.spr.lightI', "Light Hazard") },
				{ value: 'ordinaryI', label: localize('u3.mep.spr.ordI', "Ordinary Hazard Group 1") },
				{ value: 'ordinaryII', label: localize('u3.mep.spr.ordII', "Ordinary Hazard Group 2") },
				{ value: 'extraI', label: localize('u3.mep.spr.extraI', "Extra Hazard Group 1") },
			],
		},
		{
			key: 'material',
			label: localize('u3.mep.spr.material', "Pipe Material"),
			type: 'select',
			defaultValue: 'steel',
			options: [
				{ value: 'steel', label: localize('u3.mep.spr.matSteel', "Black Steel") },
				{ value: 'cpvc', label: localize('u3.mep.spr.matCpvc', "CPVC") },
				{ value: 'copper', label: localize('u3.mep.spr.matCopper', "Copper") },
			],
		},
		{
			key: 'ceiling',
			label: localize('u3.mep.spr.ceiling', "Ceiling Type"),
			type: 'select',
			defaultValue: 'beams',
			options: [
				{ value: 'beams', label: localize('u3.mep.spr.ceilBeams', "Exposed Beams / Combustible") },
				{ value: 'smooth', label: localize('u3.mep.spr.ceilSmooth', "Smooth / Suspended") },
			],
		},
	],
	secondaryActions: openMepSectionAction('fire', localize('u3.mep.spr.openSec', "Open MEP Fire")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/fireSprinklers', {
			projectRoot: ctx.project!.root.fsPath,
			hazard: String(values.hazard || 'lightI'),
			material: String(values.material || 'steel'),
			ceiling: String(values.ceiling || 'beams'),
		}));
		const stories = asArray(raw.stories).map(asBag);
		const pipes = asArray(raw.pipes).map(asBag);
		const heads = asArray(raw.heads).map(asBag);

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			area: num(s.area) ?? 0,
			coverage: num(s.coverage) ?? 0,
			maxSpacing: num(s.maxSpacing) ?? 0,
			placedHeads: num(s.placedHeads) ?? 0,
			designArea: num(s.designArea) ?? 0,
			demand: num(s.demand) ?? 0,
			mainSize: num(s.mainSize) ?? '–',
			risersNeeded: num(s.risersNeeded) ?? 1,
		}));

		const pipeRows: DataPanelRow[] = pipes.map(p => ({
			id: str(p.id),
			story: str(p.story),
			kind: str(p.kind),
			diameter: num(p.diameter) ?? 0,
			heads: num(p.heads) ?? 0,
		}));

		const headRows: DataPanelRow[] = heads.map(h => ({
			id: str(h.id),
			story: str(h.story),
			room: str(h.room, '–'),
			x: num(h.x) ?? 0,
			y: num(h.y) ?? 0,
			kFactor: num(h.kFactor) ?? 0,
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.spr.mHeads', "Placed Heads"), value: String(raw.headCount ?? headRows.length), tone: headRows.length ? 'ok' : 'warn' },
				{ label: localize('u3.mep.spr.mDemand', "Governing Demand"), value: `${num(raw.totalDemand) ?? 0} L/min` },
				{ label: localize('u3.mep.spr.mPipes', "Pipe Segments"), value: String(pipeRows.length) },
				{ label: localize('u3.mep.spr.mHazard', "Hazard"), value: str(raw.hazard, String(values.hazard)) },
			],
			tables: [
				{
					id: 'stories',
					title: localize('u3.mep.spr.storiesTab', "Story Sprinkler Summary"),
					columns: [
						{ key: 'story', title: localize('u3.mep.spr.colStory', "Story") },
						{ key: 'area', title: localize('u3.mep.spr.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'coverage', title: localize('u3.mep.spr.colCov', "Max Cover [m²]"), type: 'number', align: 'right' },
						{ key: 'maxSpacing', title: localize('u3.mep.spr.colSpace', "Max Space [m]"), type: 'number', align: 'right' },
						{ key: 'placedHeads', title: localize('u3.mep.spr.colHeads', "Heads"), type: 'number', align: 'right' },
						{ key: 'designArea', title: localize('u3.mep.spr.colDesArea', "Design Area [m²]"), type: 'number', align: 'right' },
						{ key: 'demand', title: localize('u3.mep.spr.colDemand', "Demand [L/min]"), type: 'number', align: 'right' },
						{ key: 'mainSize', title: localize('u3.mep.spr.colMain', "Main [mm]"), type: 'number', align: 'right' },
						{ key: 'risersNeeded', title: localize('u3.mep.spr.colRisers', "Risers"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
				{
					id: 'pipes',
					title: localize('u3.mep.spr.pipesTab', "Pipe Schedule"),
					columns: [
						{ key: 'id', title: localize('u3.mep.spr.colPId', "Pipe") },
						{ key: 'story', title: localize('u3.mep.spr.colPStory', "Story") },
						{ key: 'kind', title: localize('u3.mep.spr.colPKind', "Kind") },
						{ key: 'diameter', title: localize('u3.mep.spr.colPDia', "DN [mm]"), type: 'number', align: 'right' },
						{ key: 'heads', title: localize('u3.mep.spr.colPHeads', "Downstream Heads"), type: 'number', align: 'right' },
					],
					rows: pipeRows,
				},
				{
					id: 'heads',
					title: localize('u3.mep.spr.headsTab', "Sprinkler Heads"),
					columns: [
						{ key: 'id', title: localize('u3.mep.spr.colHId', "Head") },
						{ key: 'story', title: localize('u3.mep.spr.colHStory', "Story") },
						{ key: 'room', title: localize('u3.mep.spr.colHRoom', "Room") },
						{ key: 'x', title: localize('u3.mep.spr.colHX', "X [mm]"), type: 'number', align: 'right' },
						{ key: 'y', title: localize('u3.mep.spr.colHY', "Y [mm]"), type: 'number', align: 'right' },
						{ key: 'kFactor', title: localize('u3.mep.spr.colHK', "K-Factor"), type: 'number', align: 'right' },
					],
					rows: headRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.fire.alarm',
	title: localize('u3.mep.alarm.title', "Fire Alarm Layout & Battery Sizing"),
	part: 'mep',
	icon: Codicon.warning,
	help: localize('u3.mep.alarm.help', "Places smoke/heat detectors, manual call points, sounders and FACP per NFPA 72 / BS 5839-1 and calculates standby battery Ah capacity."),
	fields: [
		{ key: 'standbyHours', label: localize('u3.mep.alarm.standby', "Standby [h]"), type: 'number', defaultValue: 24, min: 1, step: '1' },
		{ key: 'alarmMinutes', label: localize('u3.mep.alarm.alarmMin', "Alarm Duration [min]"), type: 'number', defaultValue: 30, min: 5, step: '5' },
		{ key: 'ageingFactor', label: localize('u3.mep.alarm.ageing', "Ageing Factor"), type: 'number', defaultValue: 1.25, min: 1, step: '0.05' },
	],
	secondaryActions: openMepSectionAction('fire', localize('u3.mep.alarm.openSec', "Open MEP Fire")),
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('mep/fireAlarm', {
			projectRoot: ctx.project!.root.fsPath,
			standbyHours: Number(values.standbyHours) || 24,
			alarmMinutes: Number(values.alarmMinutes) || 30,
			ageingFactor: Number(values.ageingFactor) || 1.25,
		}));
		const devices = asArray(raw.devices).map(asBag);
		const counts = asBag(raw.counts);
		const bat = asBag(raw.battery);

		const summaryRows: DataPanelRow[] = [
			...Object.entries(counts).map(([k, v]) => ({ item: `Device count: ${k}`, value: num(v) ?? 0, unit: 'nos' })),
			...(Object.keys(bat).length ? [
				{ item: localize('u3.mep.alarm.sStandbyA', "Standby Current"), value: num(bat.standbyAmps) ?? 0, unit: 'A' },
				{ item: localize('u3.mep.alarm.sAlarmA', "Alarm Current"), value: num(bat.alarmAmps) ?? 0, unit: 'A' },
				{ item: localize('u3.mep.alarm.sStandbyAh', "Standby Charge"), value: num(bat.standbyAh) ?? 0, unit: 'Ah' },
				{ item: localize('u3.mep.alarm.sAlarmAh', "Alarm Charge"), value: num(bat.alarmAh) ?? 0, unit: 'Ah' },
				{ item: localize('u3.mep.alarm.sAgeing', "Ageing Factor"), value: num(bat.ageingFactor) ?? 1.25, unit: '-' },
				{ item: localize('u3.mep.alarm.sReqAh', "Required Battery Capacity"), value: num(bat.requiredAh) ?? 0, unit: 'Ah' },
				{ item: localize('u3.mep.alarm.sRecAh', "Recommended Standard Battery"), value: num(bat.recommendedAh) ?? 0, unit: 'Ah' },
			] : []),
		];

		const deviceRows: DataPanelRow[] = devices.map(d => ({
			id: str(d.id),
			kind: str(d.kind),
			story: str(d.story),
			room: str(d.room, '–'),
			zone: str(d.zone),
			x: num(d.x) ?? 0,
			y: num(d.y) ?? 0,
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.alarm.mDevices', "Devices"), value: String(deviceRows.length), tone: deviceRows.length ? 'ok' : 'warn' },
				{ label: localize('u3.mep.alarm.mStandbyA', "Standby Current"), value: `${num(bat.standbyAmps) ?? 0} A` },
				{ label: localize('u3.mep.alarm.mReqAh', "Required Battery"), value: `${num(bat.requiredAh) ?? 0} Ah` },
				{ label: localize('u3.mep.alarm.mRecAh', "Recommended Battery"), value: `${num(bat.recommendedAh) ?? 0} Ah`, tone: num(bat.recommendedAh) ? 'ok' : 'neutral' },
			],
			tables: [
				{
					id: 'summary',
					title: localize('u3.mep.alarm.sumTab', "Device Counts & Battery Sizing"),
					columns: [
						{ key: 'item', title: localize('u3.mep.alarm.colItem', "Parameter") },
						{ key: 'value', title: localize('u3.mep.alarm.colVal', "Value"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.alarm.colUnit', "Unit") },
					],
					rows: summaryRows,
				},
				{
					id: 'devices',
					title: localize('u3.mep.alarm.devTab', "Alarm Devices"),
					columns: [
						{ key: 'id', title: localize('u3.mep.alarm.colDId', "Device") },
						{ key: 'kind', title: localize('u3.mep.alarm.colDKind', "Type") },
						{ key: 'story', title: localize('u3.mep.alarm.colDStory', "Story") },
						{ key: 'room', title: localize('u3.mep.alarm.colDRoom', "Room") },
						{ key: 'zone', title: localize('u3.mep.alarm.colDZone', "Zone") },
						{ key: 'x', title: localize('u3.mep.alarm.colDX', "X [mm]"), type: 'number', align: 'right' },
						{ key: 'y', title: localize('u3.mep.alarm.colDY', "Y [mm]"), type: 'number', align: 'right' },
					],
					rows: deviceRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Plumbing Panels (2)

registerMepPanel({
	id: 'saengine.mep.plumbing.hotWater',
	title: localize('u3.mep.hw.title', "Domestic Hot Water & Recirculation"),
	part: 'mep',
	icon: Codicon.beaker,
	help: localize('u3.mep.hw.help', "Sizes domestic hot water storage volume, recovery heater power [kW], supply header and recirculation loop piping."),
	fields: [
		{ key: 'supplyTempC', label: localize('u3.mep.hw.supTemp', "Storage Temp [°C]"), type: 'number', defaultValue: 60, min: 45, max: 80 },
		{ key: 'coldTempC', label: localize('u3.mep.hw.coldTemp', "Cold Water Temp [°C]"), type: 'number', defaultValue: 15, min: 5, max: 35 },
		{ key: 'loopLengthM', label: localize('u3.mep.hw.loopLen', "Loop Length [m] (0 = auto)"), type: 'number', defaultValue: 0, min: 0 },
		{
			key: 'material',
			label: localize('u3.mep.hw.mat', "Pipe Material"),
			type: 'select',
			defaultValue: 'PPR',
			options: [
				{ value: 'PPR', label: 'PPR' },
				{ value: 'CPVC', label: 'CPVC' },
				{ value: 'copper', label: localize('u3.mep.hw.matCopper', "Copper") },
				{ value: 'GI', label: 'GI' },
			],
		},
	],
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.hw.openSec', "Open MEP Plumbing")),
	run: async (ctx, values) => {
		const loopVal = Number(values.loopLengthM);
		const raw = asBag(await ctx.engineRequest('mep/plumbingHotWater', {
			projectRoot: ctx.project!.root.fsPath,
			supplyTempC: Number(values.supplyTempC) || 60,
			coldTempC: Number(values.coldTempC) || 15,
			loopLengthM: Number.isFinite(loopVal) && loopVal > 0 ? loopVal : undefined,
			material: String(values.material || 'PPR'),
		}));
		const hw = asBag(raw.hotWater);
		const heater = asBag(hw.heater);
		const recirc = asBag(hw.recirculation);

		const heaterRows: DataPanelRow[] = [
			...(Object.keys(hw).length ? [
				{ parameter: localize('u3.mep.hw.hotUnits', "Hot Water Fixture Units"), value: num(hw.hotUnits) ?? 0, unit: 'FU' },
				{ parameter: localize('u3.mep.hw.supFlow', "Supply Header Flow"), value: num(hw.supplyFlowLpm) ?? 0, unit: 'L/min' },
				{ parameter: localize('u3.mep.hw.supPipe', "Supply Header Pipe"), value: num(hw.supplyPipeMm) ?? 0, unit: 'mm' },
			] : []),
			...Object.entries(heater).map(([k, v]) => ({ parameter: k, value: formatScalar(v), unit: '' })),
		];

		const recircRows: DataPanelRow[] = Object.entries(recirc).map(([k, v]) => ({
			parameter: k,
			value: formatScalar(v),
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.hw.mPeak', "Peak Demand"), value: `${num(heater.peakDemandLph) ?? 0} L/h` },
				{ label: localize('u3.mep.hw.mStorage', "Storage Volume"), value: `${num(heater.storageVolumeL) ?? 0} L` },
				{ label: localize('u3.mep.hw.mPower', "Heater Power"), value: `${num(heater.powerKw) ?? 0} kW`, tone: num(heater.powerKw) ? 'ok' : 'neutral' },
				{ label: localize('u3.mep.hw.mHeader', "Supply Header"), value: hw.supplyPipeMm ? `DN${str(hw.supplyPipeMm)}` : '–' },
			],
			tables: [
				{
					id: 'heater',
					title: localize('u3.mep.hw.heaterTab', "Hot Water Heater & Supply"),
					columns: [
						{ key: 'parameter', title: localize('u3.mep.hw.colHParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.hw.colHVal', "Value") },
						{ key: 'unit', title: localize('u3.mep.hw.colHUnit', "Unit") },
					],
					rows: heaterRows,
				},
				{
					id: 'recirc',
					title: localize('u3.mep.hw.recircTab', "Recirculation Loop"),
					columns: [
						{ key: 'parameter', title: localize('u3.mep.hw.colRParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.hw.colRVal', "Value") },
					],
					rows: recircRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.plumbing.gas',
	title: localize('u3.mep.gas.title', "Fuel Gas & Medical Gas Piping"),
	part: 'mep',
	icon: Codicon.flame,
	help: localize('u3.mep.gas.help', "Sizes fuel gas (natural gas / LPG via Pole's formula) and medical gas (O2, N2O, vacuum, medical air, AGSS) piping systems."),
	fields: [
		{
			key: 'fuel',
			label: localize('u3.mep.gas.fuel', "Fuel Gas Type"),
			type: 'select',
			defaultValue: 'naturalGas',
			options: [
				{ value: 'naturalGas', label: localize('u3.mep.gas.natGas', "Natural Gas") },
				{ value: 'lpg', label: 'LPG' },
			],
		},
		{ key: 'supplyPressureKpa', label: localize('u3.mep.gas.supPress', "Supply Pressure [kPa] (0 = default)"), type: 'number', defaultValue: 0, min: 0, step: '0.5' },
		{ key: 'maxDropKpa', label: localize('u3.mep.gas.maxDrop', "Max Drop [kPa] (0 = default)"), type: 'number', defaultValue: 0, min: 0, step: '0.1' },
	],
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.gas.openSec', "Open MEP Plumbing")),
	run: async (ctx, values) => {
		const supP = Number(values.supplyPressureKpa);
		const dropP = Number(values.maxDropKpa);
		const raw = asBag(await ctx.engineRequest('mep/plumbingGas', {
			projectRoot: ctx.project!.root.fsPath,
			fuel: String(values.fuel || 'naturalGas'),
			supplyPressureKpa: Number.isFinite(supP) && supP > 0 ? supP : undefined,
			maxDropKpa: Number.isFinite(dropP) && dropP > 0 ? dropP : undefined,
		}));
		const gas = asBag(raw.gas);
		const med = asBag(raw.medicalGas);
		const gasPipes = asArray(gas.pipes).map(asBag);
		const gasChecks = asArray(gas.checks).map(asBag);
		const medSystems = Object.values(asBag(med.systems)).map(asBag);

		const gasSummaryRows: DataPanelRow[] = [
			...(Object.keys(gas).length ? [
				{ item: localize('u3.mep.gas.sFuel', "Fuel"), value: str(gas.fuelLabel || gas.fuel), status: 'OK' },
				{ item: localize('u3.mep.gas.sApps', "Appliance Count"), value: str(gas.applianceCount, '0'), status: 'OK' },
				{ item: localize('u3.mep.gas.sConn', "Connected Load [kW]"), value: str(gas.connectedKw, '0'), status: 'OK' },
				{ item: localize('u3.mep.gas.sDiv', "Diversified Load [kW]"), value: `${str(gas.diversifiedKw, '0')} (DF ${str(gas.diversityFactor, '1')})`, status: 'OK' },
				{ item: localize('u3.mep.gas.sFlow', "Diversified Flow [m³/h]"), value: str(gas.flowM3h, '0'), status: 'OK' },
				{ item: localize('u3.mep.gas.sPress', "Supply / Max Drop [kPa]"), value: `${str(gas.supplyPressureKpa, '–')} / ${str(gas.maxDropKpa, '–')}`, status: 'OK' },
			] : []),
			...gasChecks.map(c => ({
				item: str(c.name),
				value: str(c.note, formatScalar(c.demand)),
				status: c.ok ? 'Pass' : 'Fail',
			})),
		];

		const gasPipeRows: DataPanelRow[] = gasPipes.map(p => ({
			id: str(p.id),
			story: str(p.story),
			lengthM: num(p.lengthM) ?? 0,
			flowM3h: num(p.flowM3h) ?? 0,
			diameter: num(p.diameter) ?? '–',
			required: num(p.required) ?? '–',
			dropKpa: num(p.dropKpa) ?? 0,
			velocityMs: num(p.velocityMs) ?? 0,
			status: p.ok ? 'Pass' : 'Fail',
		}));

		const medRows: DataPanelRow[] = medSystems.map(s => ({
			gas: str(s.gas),
			label: str(s.label),
			outlets: num(s.outlets) ?? 0,
			diversity: num(s.diversity) ?? 0,
			flowLpm: num(s.flowLpm) ?? 0,
			mainPipeMm: num(s.mainPipeMm) ?? '–',
			velocityMs: num(s.velocityMs) ?? 0,
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.gas.mFuel', "Fuel"), value: str(gas.fuelLabel || gas.fuel, String(values.fuel)) },
				{ label: localize('u3.mep.gas.mFlow', "Gas Flow"), value: `${num(gas.flowM3h) ?? 0} m³/h` },
				{ label: localize('u3.mep.gas.mPipes', "Gas Pipes"), value: String(gasPipeRows.length) },
				{ label: localize('u3.mep.gas.mMed', "Medical Gas Systems"), value: String(medRows.length) },
			],
			tables: [
				{
					id: 'gasSummary',
					title: localize('u3.mep.gas.sumTab', "Fuel Gas Demand & Checks"),
					columns: [
						{ key: 'item', title: localize('u3.mep.gas.colItem', "Item / Check") },
						{ key: 'value', title: localize('u3.mep.gas.colVal', "Value / Note") },
						{ key: 'status', title: localize('u3.mep.gas.colStatus', "Status"), type: 'status' },
					],
					rows: gasSummaryRows,
					emptyMessage: localize('u3.mep.gas.noGas', "No fuel gas system configured in 07 MEP/mep.json yet."),
				},
				{
					id: 'gasPipes',
					title: localize('u3.mep.gas.pipesTab', "Fuel Gas Pipe Sizing"),
					columns: [
						{ key: 'id', title: localize('u3.mep.gas.colPId', "Pipe") },
						{ key: 'story', title: localize('u3.mep.gas.colPStory', "Story") },
						{ key: 'lengthM', title: localize('u3.mep.gas.colPLen', "Length [m]"), type: 'number', align: 'right' },
						{ key: 'flowM3h', title: localize('u3.mep.gas.colPFlow', "Flow [m³/h]"), type: 'number', align: 'right' },
						{ key: 'diameter', title: localize('u3.mep.gas.colPDia', "Provided [mm]"), type: 'number', align: 'right' },
						{ key: 'required', title: localize('u3.mep.gas.colPReq', "Required [mm]"), type: 'number', align: 'right' },
						{ key: 'dropKpa', title: localize('u3.mep.gas.colPDrop', "Drop [kPa]"), type: 'number', align: 'right' },
						{ key: 'velocityMs', title: localize('u3.mep.gas.colPVel', "Vel [m/s]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.gas.colPStatus', "Status"), type: 'status' },
					],
					rows: gasPipeRows,
					emptyMessage: localize('u3.mep.gas.noGasPipes', "No explicit fuel gas pipe runs defined in 07 MEP (see Notes for estimated header size)."),
				},
				{
					id: 'medGas',
					title: localize('u3.mep.gas.medTab', "Medical Gas Systems"),
					columns: [
						{ key: 'gas', title: localize('u3.mep.gas.colMGas', "Gas") },
						{ key: 'label', title: localize('u3.mep.gas.colMLabel', "Description") },
						{ key: 'outlets', title: localize('u3.mep.gas.colMOut', "Outlets"), type: 'number', align: 'right' },
						{ key: 'diversity', title: localize('u3.mep.gas.colMDiv', "Diversity"), type: 'number', align: 'right' },
						{ key: 'flowLpm', title: localize('u3.mep.gas.colMFlow', "Flow [L/min]"), type: 'number', align: 'right' },
						{ key: 'mainPipeMm', title: localize('u3.mep.gas.colMPipe', "Main [mm]"), type: 'number', align: 'right' },
						{ key: 'velocityMs', title: localize('u3.mep.gas.colMVel', "Vel [m/s]"), type: 'number', align: 'right' },
					],
					rows: medRows,
					emptyMessage: localize('u3.mep.gas.noMedGas', "No medical gas outlets or clinical rooms configured in 07 MEP."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion
