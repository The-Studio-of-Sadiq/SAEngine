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
				precondition: descriptor.requiresProject === false ? undefined : projectOpen,
			});
		}

		override run(accessor: ServicesAccessor): Promise<unknown> {
			return openEngineDataPanel(accessor.get(IEditorService), descriptor.id);
		}
	});
}

function openMepSectionAction(section: 'coordination' | 'electrical' | 'hvac' | 'fire' | 'plumbing' | 'systems', label: string): readonly IDataPanelAction[] {
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

//#region Coordination Panels (2)

function formatOpeningSize(o: IJsonBag): string {
	const diameter = num(o.diameter);
	if (diameter !== undefined) {
		return `Ø${diameter} mm`;
	}
	const width = num(o.width);
	const height = num(o.height);
	return width !== undefined && height !== undefined ? `${width}×${height} mm` : '–';
}

registerMepPanel({
	id: 'saengine.mep.coordination.openings',
	title: localize('u3.mep.openings.title', "MEP Opening Checks & Equipment Loads"),
	part: 'mep',
	icon: Codicon.circleLargeOutline,
	help: localize('u3.mep.openings.help', "Evaluates structural beam, slab and wall openings/sleeves, equipment floor loads by story, and MEP IFC clash checks."),
	secondaryActions: openMepSectionAction('coordination', localize('u3.mep.openings.openSec', "Open MEP Coordination")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/report', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const openings = asArray(raw.openings).map(asBag);
		const equipment = asArray(raw.equipment).map(asBag);
		const stories = asArray(raw.stories).map(asBag);
		const clashes = asArray(raw.clashes).map(asBag);

		const openingRows: DataPanelRow[] = openings.map(o => {
			const checked = o.checked !== false;
			const strengthChecked = checked && (typeof o.strengthChecked === 'boolean' ? o.strengthChecked : true);
			const ok = !checked || o.ok !== false;
			const status = !checked ? 'OK' : !ok ? 'Fail' : !strengthChecked ? 'Warn' : 'Pass';
			return {
				id: str(o.id),
				host: str(o.host, '–'),
				check: str(o.check, '–'),
				utilisation: num(o.utilisation) ?? '–',
				strengthChecked: strengthChecked ? 'Yes' : 'No',
				status,
				note: str(o.note, '–'),
			};
		});

		const equipmentRows: DataPanelRow[] = equipment.map(e => {
			const onGrade = e.onGrade === true;
			const applied = typeof e.applied === 'boolean' ? e.applied : !onGrade;
			return {
				id: str(e.id),
				discipline: str(e.discipline, 'coordination'),
				kind: str(e.kind, '–'),
				story: str(e.story, '–'),
				operatingWeight: num(e.operatingWeight) ?? 0,
				load: num(e.load ?? e.operatingWeight) ?? 0,
				pressure: num(e.pressure) ?? '–',
				host: str(e.host, '–'),
				status: onGrade ? 'OK' : applied ? 'Pass' : 'Warn',
				note: str(e.note, '–'),
			};
		});

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			count: num(s.count) ?? 0,
			load: num(s.load) ?? 0,
			onGrade: num(s.onGrade) ?? 0,
			notApplied: num(s.notApplied) ?? 0,
			note: str(s.note, '–'),
		}));

		const clashRows: DataPanelRow[] = clashes.map(c => ({
			id: str(c.id, '–'),
			discipline: str(c.discipline, '–'),
			element: str(c.mepName || c.mep || c.mepElement, '–'),
			structural: str(c.structural || c.structuralElement, '–'),
			kind: str(c.kind, 'hard'),
			story: str(c.story, '–'),
			size: num(c.size) ?? '–',
			opening: str(c.opening, '–'),
			status: c.status === 'coordinated' ? 'Pass' : 'Warn',
			note: str(c.note, '–'),
		}));

		const failingOpenings = openingRows.filter(r => r.status === 'Fail').length;
		const openClashes = clashes.filter(c => c.status !== 'coordinated' && c.kind !== 'clearance').length;
		return {
			metrics: [
				{ label: localize('u3.mep.openings.mOpenings', "Openings"), value: String(openingRows.length) },
				{ label: localize('u3.mep.openings.mFailing', "Failing Openings"), value: String(failingOpenings), tone: failingOpenings ? 'fail' : 'ok' },
				{ label: localize('u3.mep.openings.mEquip', "Equipment"), value: String(equipmentRows.length) },
				{ label: localize('u3.mep.openings.mClashes', "Open Clashes"), value: String(openClashes), tone: openClashes ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'openings',
					title: localize('u3.mep.openings.openingsTab', "Opening Checks"),
					columns: [
						{ key: 'id', title: localize('u3.mep.openings.colOId', "Opening") },
						{ key: 'host', title: localize('u3.mep.openings.colHost', "Host") },
						{ key: 'check', title: localize('u3.mep.openings.colCheck', "Check") },
						{ key: 'utilisation', title: localize('u3.mep.openings.colUtil', "Utilisation"), type: 'number', align: 'right' },
						{ key: 'strengthChecked', title: localize('u3.mep.openings.colStrength', "Strength Checked") },
						{ key: 'status', title: localize('u3.mep.openings.colStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.openings.colNote', "Note") },
					],
					rows: openingRows,
					emptyMessage: localize('u3.mep.openings.noOpenings', "No sleeves or openings defined in 07 MEP yet."),
				},
				{
					id: 'equipment',
					title: localize('u3.mep.openings.equipTab', "Equipment Loads"),
					columns: [
						{ key: 'id', title: localize('u3.mep.openings.colEId', "Equipment") },
						{ key: 'discipline', title: localize('u3.mep.openings.colEDisc', "Discipline") },
						{ key: 'kind', title: localize('u3.mep.openings.colEKind', "Kind") },
						{ key: 'story', title: localize('u3.mep.openings.colEStory', "Story") },
						{ key: 'operatingWeight', title: localize('u3.mep.openings.colEOp', "Weight [kN]"), type: 'number', align: 'right' },
						{ key: 'load', title: localize('u3.mep.openings.colELoad', "Applied [kN]"), type: 'number', align: 'right' },
						{ key: 'pressure', title: localize('u3.mep.openings.colEPress', "Pressure [kPa]"), type: 'number', align: 'right' },
						{ key: 'host', title: localize('u3.mep.openings.colEHost', "Host") },
						{ key: 'status', title: localize('u3.mep.openings.colEStatus', "Placement"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.openings.colENote', "Note") },
					],
					rows: equipmentRows,
				},
				{
					id: 'stories',
					title: localize('u3.mep.openings.storiesTab', "Story Load Summary"),
					columns: [
						{ key: 'story', title: localize('u3.mep.openings.colSStory', "Story") },
						{ key: 'count', title: localize('u3.mep.openings.colSCount', "Items"), type: 'number', align: 'right' },
						{ key: 'load', title: localize('u3.mep.openings.colSLoad', "On Frame [kN]"), type: 'number', align: 'right' },
						{ key: 'onGrade', title: localize('u3.mep.openings.colSGrade', "On Grade [kN]"), type: 'number', align: 'right' },
						{ key: 'notApplied', title: localize('u3.mep.openings.colSOff', "Off Slab [kN]"), type: 'number', align: 'right' },
						{ key: 'note', title: localize('u3.mep.openings.colSNote', "Note") },
					],
					rows: storyRows,
				},
				{
					id: 'clashes',
					title: localize('u3.mep.openings.clashesTab', "MEP Clashes"),
					columns: [
						{ key: 'id', title: localize('u3.mep.openings.colCId', "Clash") },
						{ key: 'discipline', title: localize('u3.mep.openings.colCDisc', "Discipline") },
						{ key: 'element', title: localize('u3.mep.openings.colCMep', "MEP Element") },
						{ key: 'structural', title: localize('u3.mep.openings.colCStruct', "Structural") },
						{ key: 'kind', title: localize('u3.mep.openings.colCKind', "Kind") },
						{ key: 'story', title: localize('u3.mep.openings.colCStory', "Story") },
						{ key: 'size', title: localize('u3.mep.openings.colCSize', "Size [mm]"), type: 'number', align: 'right' },
						{ key: 'opening', title: localize('u3.mep.openings.colCOpen', "Opening") },
						{ key: 'status', title: localize('u3.mep.openings.colCStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.openings.colCNote', "Note") },
					],
					rows: clashRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.coordination.checkIds',
	title: localize('u3.mep.ids.title', "IDS Specification Checks"),
	part: 'mep',
	icon: Codicon.checklist,
	help: localize('u3.mep.ids.help', "Validates SAEngine and external IFC models against buildingSMART IDS files via IfcTester and reports failing specifications and elements."),
	secondaryActions: openMepSectionAction('coordination', localize('u3.mep.ids.openSec', "Open MEP Coordination")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/checkIds', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const results = asArray(raw.results).map(asBag);
		const counts = asBag(raw.counts);
		const specRows: DataPanelRow[] = [];
		const failureRows: DataPanelRow[] = [];

		for (const entry of results) {
			const ids = str(entry.ids);
			const model = str(entry.model);
			for (const spec of asArray(entry.specifications).map(asBag)) {
				const specName = str(spec.name);
				const failed = num(spec.failed) ?? 0;
				const passed = spec.status === true && failed === 0;
				specRows.push({
					ids,
					model,
					name: specName,
					applicable: num(spec.applicable) ?? 0,
					failed,
					status: passed ? 'Pass' : 'Fail',
					description: str(spec.description, '–'),
				});
				for (const f of asArray(spec.failures).map(asBag)) {
					failureRows.push({
						ids,
						model,
						specification: specName,
						globalId: str(f.globalId),
						elementName: str(f.name, '–'),
						ifcClass: str(f.class, '–'),
						reason: str(f.reason, '–'),
					});
				}
			}
		}

		const passedSpecs = specRows.filter(r => r.status === 'Pass').length;
		const failedSpecs = specRows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u3.mep.ids.mSpecs', "Specifications"), value: String(specRows.length) },
				{ label: localize('u3.mep.ids.mPassed', "Passed"), value: String(passedSpecs), tone: passedSpecs ? 'ok' : 'neutral' },
				{ label: localize('u3.mep.ids.mFailed', "Failed"), value: String(failedSpecs), tone: failedSpecs ? 'fail' : 'ok' },
				{ label: localize('u3.mep.ids.mOpen', "Open Issues"), value: String(num(counts.open) ?? 0) },
			],
			tables: [
				{
					id: 'specifications',
					title: localize('u3.mep.ids.specsTab', "Specifications"),
					columns: [
						{ key: 'ids', title: localize('u3.mep.ids.colIds', "IDS File") },
						{ key: 'model', title: localize('u3.mep.ids.colModel', "IFC Model") },
						{ key: 'name', title: localize('u3.mep.ids.colSpec', "Specification") },
						{ key: 'applicable', title: localize('u3.mep.ids.colApp', "Applicable"), type: 'number', align: 'right' },
						{ key: 'failed', title: localize('u3.mep.ids.colFail', "Failed"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.ids.colStatus', "Status"), type: 'status' },
						{ key: 'description', title: localize('u3.mep.ids.colDesc', "Description") },
					],
					rows: specRows,
					emptyMessage: localize('u3.mep.ids.noSpecs', "No IDS files configured in coordination yet (add an .ids file in 07 MEP Data)."),
				},
				{
					id: 'failures',
					title: localize('u3.mep.ids.failTab', "Failing Elements"),
					columns: [
						{ key: 'ids', title: localize('u3.mep.ids.colFIds', "IDS File") },
						{ key: 'model', title: localize('u3.mep.ids.colFModel', "IFC Model") },
						{ key: 'specification', title: localize('u3.mep.ids.colFSpec', "Specification") },
						{ key: 'globalId', title: localize('u3.mep.ids.colFGuid', "GlobalId") },
						{ key: 'elementName', title: localize('u3.mep.ids.colFName', "Element") },
						{ key: 'ifcClass', title: localize('u3.mep.ids.colFClass', "IFC Class") },
						{ key: 'reason', title: localize('u3.mep.ids.colFReason', "Reason") },
					],
					rows: failureRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Additional Plumbing Panels (6)

registerMepPanel({
	id: 'saengine.mep.plumbing.occupancies',
	title: localize('u3.mep.plbOcc.title', "Water Consumption Occupancies"),
	part: 'mep',
	requiresProject: false,
	icon: Codicon.book,
	help: localize('u3.mep.plbOcc.help', "Displays code-pack domestic water consumption rates (full facility and restricted lpcd) by building occupancy category."),
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.plbOcc.openSec', "Open MEP Plumbing")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/plumbingOccupancies', {}));
		const rows: DataPanelRow[] = asArray(raw.occupancies).map(asBag).map(o => ({
			label: str(o.label),
			group: str(o.group, '–'),
			lpcd: num(o.lpcd) ?? '–',
			restricted: num(o.restricted) ?? '–',
			unit: str(o.unit, 'lpcd'),
			table: str(o.table, '–'),
			source: str(o.source, '–'),
		}));
		const tablesCount = new Set(rows.map(r => str(r.table)).filter(v => v && v !== '–')).size;
		return {
			metrics: [
				{ label: localize('u3.mep.plbOcc.mCount', "Occupancies"), value: String(rows.length) },
				{ label: localize('u3.mep.plbOcc.mTables', "Code Tables"), value: String(tablesCount) },
			],
			tables: [{
				id: 'occupancies',
				title: localize('u3.mep.plbOcc.tab', "Water Consumption Rates"),
				columns: [
					{ key: 'label', title: localize('u3.mep.plbOcc.colLabel', "Occupancy") },
					{ key: 'group', title: localize('u3.mep.plbOcc.colGroup', "Group") },
					{ key: 'lpcd', title: localize('u3.mep.plbOcc.colFull', "Full [L/day]"), type: 'number', align: 'right' },
					{ key: 'restricted', title: localize('u3.mep.plbOcc.colRest', "Restricted [L/day]"), type: 'number', align: 'right' },
					{ key: 'unit', title: localize('u3.mep.plbOcc.colUnit', "Basis") },
					{ key: 'table', title: localize('u3.mep.plbOcc.colTable', "Table") },
					{ key: 'source', title: localize('u3.mep.plbOcc.colSource', "Reference") },
				],
				rows,
			}],
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.plumbing.branches',
	title: localize('u3.mep.plbBr.title', "Wet-Room Supply & Drainage Branches"),
	part: 'mep',
	icon: Codicon.gitBranch,
	help: localize('u3.mep.plbBr.help', "Traces horizontal supply and drainage branch runs from risers/stacks to architectural wet rooms and flags structural beam crossings."),
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.plbBr.openSec', "Open MEP Plumbing")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/plumbingReport', {
			projectRoot: ctx.project!.root.fsPath,
			designs: false,
		}));
		const rooms = asBag(raw.rooms);
		const branches = asArray(rooms.branches).map(asBag);
		const wetRooms = asArray(rooms.wetRooms).map(asBag);

		const branchRows: DataPanelRow[] = branches.map(b => {
			const beams = asStrings(b.beams);
			return {
				story: str(b.story),
				room: str(b.label || b.room),
				system: str(b.system),
				riser: str(b.riser, '–'),
				length: num(b.length) ?? 0,
				beamCount: beams.length,
				beams: beams.join(', ') || '–',
			};
		});

		const wetRoomRows: DataPanelRow[] = wetRooms.map(w => ({
			id: str(w.id),
			story: str(w.story),
			name: str(w.name),
			kind: str(w.kind, '–'),
			area: num(w.area) ?? 0,
		}));

		const totalCrossings = branchRows.reduce((acc, r) => acc + (num(r.beamCount) ?? 0), 0);
		return {
			metrics: [
				{ label: localize('u3.mep.plbBr.mBranches', "Branch Runs"), value: String(branchRows.length) },
				{ label: localize('u3.mep.plbBr.mRooms', "Wet Rooms"), value: String(wetRoomRows.length) },
				{ label: localize('u3.mep.plbBr.mBeams', "Beam Crossings"), value: String(totalCrossings), tone: totalCrossings ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'branches',
					title: localize('u3.mep.plbBr.branchesTab', "Riser-to-Room Branches"),
					columns: [
						{ key: 'story', title: localize('u3.mep.plbBr.colStory', "Story") },
						{ key: 'room', title: localize('u3.mep.plbBr.colRoom', "Wet Room") },
						{ key: 'system', title: localize('u3.mep.plbBr.colSys', "System") },
						{ key: 'riser', title: localize('u3.mep.plbBr.colRiser', "Riser / Stack") },
						{ key: 'length', title: localize('u3.mep.plbBr.colLen', "Length [m]"), type: 'number', align: 'right' },
						{ key: 'beamCount', title: localize('u3.mep.plbBr.colCross', "Crossings"), type: 'number', align: 'right' },
						{ key: 'beams', title: localize('u3.mep.plbBr.colBeams', "Beams Crossed") },
					],
					rows: branchRows,
					emptyMessage: localize('u3.mep.plbBr.empty', "No wet-room branches computed yet (add architectural wet rooms and plumbing risers)."),
				},
				{
					id: 'wetRooms',
					title: localize('u3.mep.plbBr.roomsTab', "Wet Rooms"),
					columns: [
						{ key: 'id', title: localize('u3.mep.plbBr.colWId', "Room") },
						{ key: 'story', title: localize('u3.mep.plbBr.colWStory', "Story") },
						{ key: 'name', title: localize('u3.mep.plbBr.colWName', "Name") },
						{ key: 'kind', title: localize('u3.mep.plbBr.colWKind', "Kind") },
						{ key: 'area', title: localize('u3.mep.plbBr.colWArea', "Area [m²]"), type: 'number', align: 'right' },
					],
					rows: wetRoomRows,
				},
			],
			notes: [...asStrings(rooms.notes), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.plumbing.drainage',
	title: localize('u3.mep.plbDrn.title', "Sanitary Drainage Stacks & Building Drains"),
	part: 'mep',
	icon: Codicon.arrowDown,
	help: localize('u3.mep.plbDrn.help', "Sizes soil, waste, combined and vent stacks plus horizontal building drains by drainage fixture units (DFU) and slope."),
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.plbDrn.openSec', "Open MEP Plumbing")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/plumbingReport', {
			projectRoot: ctx.project!.root.fsPath,
			designs: false,
		}));
		const rawStacks = asArray(raw.stacks).map(asBag);
		const fallbackStacks = asArray(raw.risers).map(asBag).filter(r => ['soil', 'waste', 'soilWaste', 'vent'].includes(str(r.system)));
		const stacks = rawStacks.length ? rawStacks : fallbackStacks;
		const drains = asArray(raw.drains).map(asBag);

		const stackRows: DataPanelRow[] = stacks.map(s => ({
			id: str(s.id),
			system: str(s.system),
			units: num(s.units) ?? 0,
			required: num(s.required) ?? '–',
			diameter: num(s.diameter) ?? '–',
			status: s.ok === false ? 'Fail' : 'Pass',
			note: asStrings(s.notes).join('; ') || str(s.note, '–'),
		}));

		const drainRows: DataPanelRow[] = drains.map(d => {
			const slope = num(d.slope);
			const slopeLabel = slope && slope > 0 ? `1/${Math.round(1 / slope)}` : '–';
			return {
				name: str(d.name),
				units: num(d.units) ?? 0,
				slope: slopeLabel,
				diameter: num(d.diameter) ?? '–',
				status: d.ok === false ? 'Fail' : 'Pass',
				note: str(d.note, '–'),
			};
		});

		const totalDfu = drainRows.reduce((sum, r) => sum + (num(r.units) ?? 0), 0);
		const failing = [...stackRows, ...drainRows].filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u3.mep.plbDrn.mStacks', "Stacks & Vents"), value: String(stackRows.length) },
				{ label: localize('u3.mep.plbDrn.mDrains', "Building Drains"), value: String(drainRows.length) },
				{ label: localize('u3.mep.plbDrn.mDfu', "Total DFU"), value: String(totalDfu) },
				{ label: localize('u3.mep.plbDrn.mFail', "Failing Checks"), value: String(failing), tone: failing ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'stacks',
					title: localize('u3.mep.plbDrn.stacksTab', "Soil, Waste & Vent Stacks"),
					columns: [
						{ key: 'id', title: localize('u3.mep.plbDrn.colSId', "Stack") },
						{ key: 'system', title: localize('u3.mep.plbDrn.colSSys', "System") },
						{ key: 'units', title: localize('u3.mep.plbDrn.colSDfu', "Load [DFU]"), type: 'number', align: 'right' },
						{ key: 'required', title: localize('u3.mep.plbDrn.colSReq', "Required [mm]"), type: 'number', align: 'right' },
						{ key: 'diameter', title: localize('u3.mep.plbDrn.colSDia', "Provided [mm]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.plbDrn.colSStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.plbDrn.colSNote', "Note") },
					],
					rows: stackRows,
					emptyMessage: localize('u3.mep.plbDrn.noStacks', "No soil, waste or vent stacks configured in 07 MEP yet."),
				},
				{
					id: 'drains',
					title: localize('u3.mep.plbDrn.drainsTab', "Building Drains"),
					columns: [
						{ key: 'name', title: localize('u3.mep.plbDrn.colDName', "Drain") },
						{ key: 'units', title: localize('u3.mep.plbDrn.colDDfu', "Load [DFU]"), type: 'number', align: 'right' },
						{ key: 'slope', title: localize('u3.mep.plbDrn.colDSlope', "Slope") },
						{ key: 'diameter', title: localize('u3.mep.plbDrn.colDDia', "Diameter [mm]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.plbDrn.colDStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.plbDrn.colDNote', "Note") },
					],
					rows: drainRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.plumbing.rainwater',
	title: localize('u3.mep.plbRain.title', "Rainwater Leaders, Storm Drain & Harvesting"),
	part: 'mep',
	icon: Codicon.cloudDownload,
	help: localize('u3.mep.plbRain.help', "Computes roof drain catchments, leader & gutter sizes, horizontal storm drain diameter, and rainwater harvesting storage."),
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.plbRain.openSec', "Open MEP Plumbing")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/plumbingReport', {
			projectRoot: ctx.project!.root.fsPath,
			designs: false,
		}));
		const rw = asBag(raw.rainwater);
		const drains = asArray(rw.drains).map(asBag);
		const leaders = asArray(rw.leaders).map(asBag);
		const storm = asBag(rw.stormDrain);
		const harvest = asBag(rw.harvesting);

		const drainRows: DataPanelRow[] = drains.map(d => ({
			id: str(d.id || d.drain),
			story: str(d.story, '–'),
			area: num(d.area) ?? 0,
			flow: num(d.flow) ?? 0,
			leader: num(d.leader) ?? '–',
			gutter: num(d.gutter) ?? '–',
			status: d.ok === false ? 'Fail' : 'Pass',
			note: str(d.source || d.note, '–'),
		}));

		const leaderRows: DataPanelRow[] = leaders.map(l => ({
			id: str(l.id),
			area: num(l.area) ?? 0,
			required: num(l.required) ?? '–',
			diameter: num(l.diameter) ?? '–',
			status: l.ok === false ? 'Fail' : 'Pass',
			note: asStrings(l.notes).join('; ') || str(l.note, '–'),
		}));

		const stormRows: DataPanelRow[] = [
			...(Object.keys(storm).length ? [
				{ parameter: localize('u3.mep.plbRain.sArea', "Total Roof Catchment"), value: `${num(storm.area) ?? 0} m²` },
				{ parameter: localize('u3.mep.plbRain.sFlow', "Storm Flow"), value: `${num(storm.flow) ?? 0} L/s` },
				{ parameter: localize('u3.mep.plbRain.sDia', "Storm Drain Diameter"), value: storm.diameter ? `Ø${str(storm.diameter)} mm` : '–' },
				{ parameter: localize('u3.mep.plbRain.sNote', "Storm Drain Basis"), value: str(storm.note, '–') },
			] : []),
			...(Object.keys(harvest).length ? [
				{ parameter: localize('u3.mep.plbRain.hReq', "Harvesting Required"), value: formatScalar(harvest.required) },
				{ parameter: localize('u3.mep.plbRain.hVol', "Harvest Storage Volume"), value: num(harvest.volume) !== undefined ? `${num(harvest.volume)!.toFixed(2)} m³` : '–' },
				{ parameter: localize('u3.mep.plbRain.hDays', "Storage Days"), value: formatScalar(harvest.days) },
			] : []),
		];

		const intensity = num(rw.intensity) ?? 0;
		const harvestVol = num(harvest.volume);
		return {
			metrics: [
				{ label: localize('u3.mep.plbRain.mInt', "Rainfall Intensity"), value: `${intensity.toFixed(1)} mm/h` },
				{ label: localize('u3.mep.plbRain.mDrains', "Roof Drains"), value: String(drainRows.length) },
				{ label: localize('u3.mep.plbRain.mLeaders', "Leaders"), value: String(leaderRows.length) },
				{ label: localize('u3.mep.plbRain.mHarvest', "Harvest Storage"), value: harvestVol !== undefined ? `${harvestVol.toFixed(1)} m³` : '–' },
			],
			tables: [
				{
					id: 'drains',
					title: localize('u3.mep.plbRain.drainsTab', "Roof Drains & Catchments"),
					columns: [
						{ key: 'id', title: localize('u3.mep.plbRain.colDId', "Drain") },
						{ key: 'story', title: localize('u3.mep.plbRain.colDStory', "Story") },
						{ key: 'area', title: localize('u3.mep.plbRain.colDArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'flow', title: localize('u3.mep.plbRain.colDFlow', "Flow [L/s]"), type: 'number', align: 'right' },
						{ key: 'leader', title: localize('u3.mep.plbRain.colDLeader', "Leader [mm]"), type: 'number', align: 'right' },
						{ key: 'gutter', title: localize('u3.mep.plbRain.colDGutter', "Gutter [mm]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.plbRain.colDStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.plbRain.colDNote', "Source") },
					],
					rows: drainRows,
					emptyMessage: localize('u3.mep.plbRain.noDrains', "No roof drains defined in 07 MEP yet."),
				},
				{
					id: 'leaders',
					title: localize('u3.mep.plbRain.leadersTab', "Rainwater Leaders"),
					columns: [
						{ key: 'id', title: localize('u3.mep.plbRain.colLId', "Leader") },
						{ key: 'area', title: localize('u3.mep.plbRain.colLArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'required', title: localize('u3.mep.plbRain.colLReq', "Required [mm]"), type: 'number', align: 'right' },
						{ key: 'diameter', title: localize('u3.mep.plbRain.colLDia', "Provided [mm]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.plbRain.colLStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.plbRain.colLNote', "Note") },
					],
					rows: leaderRows,
				},
				{
					id: 'storm',
					title: localize('u3.mep.plbRain.stormTab', "Storm Drain & Harvesting"),
					columns: [
						{ key: 'parameter', title: localize('u3.mep.plbRain.colSParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.plbRain.colSVal', "Value") },
					],
					rows: stormRows,
				},
			],
			notes: [...asStrings(rw.notes), ...asStrings(harvest.notes), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.plumbing.septic',
	title: localize('u3.mep.plbSep.title', "Septic Tank, Soak Well & Separations"),
	part: 'mep',
	icon: Codicon.database,
	help: localize('u3.mep.plbSep.help', "Sizes septic tanks, soak wells (seepage pits) using soil percolation estimates, and checks code separation clearances."),
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.plbSep.openSec', "Open MEP Plumbing")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/plumbingReport', {
			projectRoot: ctx.project!.root.fsPath,
			designs: false,
		}));
		const septic = asBag(raw.septic);
		const well = asBag(septic.soakWell);
		const seps = asArray(septic.separations).map(asBag);

		const sizingRows: DataPanelRow[] = [
			...(Object.keys(septic).length ? [
				{ item: localize('u3.mep.plbSep.tank', "Septic Tank"), parameter: localize('u3.mep.plbSep.users', "Equivalent Users"), value: formatScalar(septic.persons ?? septic.population), unit: 'persons' },
				{ item: localize('u3.mep.plbSep.tank', "Septic Tank"), parameter: localize('u3.mep.plbSep.reqVol', "Required Liquid Volume"), value: num(septic.volume) !== undefined ? (num(septic.volume)! / 1000).toFixed(2) : '–', unit: 'm³' },
				{ item: localize('u3.mep.plbSep.tank', "Septic Tank"), parameter: localize('u3.mep.plbSep.provVol', "Provided Liquid Volume"), value: num(septic.provided) !== undefined ? (num(septic.provided)! / 1000).toFixed(2) : '–', unit: 'm³' },
				{ item: localize('u3.mep.plbSep.tank', "Septic Tank"), parameter: localize('u3.mep.plbSep.dims', "Inside Length × Width × Depth"), value: `${str(septic.length, '–')} × ${str(septic.width, '–')} × ${str(septic.waterDepth, '–')}`, unit: 'mm' },
				{ item: localize('u3.mep.plbSep.tank', "Septic Tank"), parameter: localize('u3.mep.plbSep.count', "Tank Count"), value: formatScalar(septic.count), unit: 'nos' },
			] : []),
			...(Object.keys(well).length ? [
				{ item: localize('u3.mep.plbSep.well', "Soak Well"), parameter: localize('u3.mep.plbSep.wCount', "Well Count"), value: formatScalar(well.count), unit: 'nos' },
				{ item: localize('u3.mep.plbSep.well', "Soak Well"), parameter: localize('u3.mep.plbSep.wDia', "Diameter × Effective Depth"), value: `Ø${str(well.diameter, '–')} × ${str(well.waterDepth, '–')}`, unit: 'mm' },
				{ item: localize('u3.mep.plbSep.well', "Soak Well"), parameter: localize('u3.mep.plbSep.wPerc', "Soil Percolation Rate"), value: formatScalar(well.percolation), unit: 'min/25mm' },
				{ item: localize('u3.mep.plbSep.well', "Soak Well"), parameter: localize('u3.mep.plbSep.wAllow', "Effluent Allowance"), value: formatScalar(well.allowance), unit: 'L/m²/day' },
			] : []),
		];

		const sepRows: DataPanelRow[] = seps.map(c => ({
			name: str(c.name),
			demand: num(c.demand) ?? '–',
			capacity: num(c.capacity) ?? '–',
			unit: str(c.unit, 'm'),
			status: c.ok === false ? 'Fail' : 'Pass',
			note: str(c.note, '–'),
		}));

		const failing = sepRows.filter(r => r.status === 'Fail').length;
		const reqVolM3 = num(septic.volume) !== undefined ? (num(septic.volume)! / 1000).toFixed(2) : '–';
		return {
			metrics: [
				{ label: localize('u3.mep.plbSep.mUsers', "Users"), value: str(septic.persons ?? septic.population, '–') },
				{ label: localize('u3.mep.plbSep.mVol', "Required Volume"), value: reqVolM3 === '–' ? '–' : `${reqVolM3} m³` },
				{ label: localize('u3.mep.plbSep.mWells', "Soak Wells"), value: str(well.count, '0') },
				{ label: localize('u3.mep.plbSep.mFail', "Separation Fails"), value: String(failing), tone: failing ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'sizing',
					title: localize('u3.mep.plbSep.sizingTab', "Septic Tank & Soak Well Sizing"),
					columns: [
						{ key: 'item', title: localize('u3.mep.plbSep.colItem', "Component") },
						{ key: 'parameter', title: localize('u3.mep.plbSep.colParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.plbSep.colVal', "Value") },
						{ key: 'unit', title: localize('u3.mep.plbSep.colUnit', "Unit") },
					],
					rows: sizingRows,
					emptyMessage: localize('u3.mep.plbSep.noSeptic', "Disposal is not set to septic or building population is 0."),
				},
				{
					id: 'separations',
					title: localize('u3.mep.plbSep.sepTab', "Separation Checks"),
					columns: [
						{ key: 'name', title: localize('u3.mep.plbSep.colSName', "Check") },
						{ key: 'demand', title: localize('u3.mep.plbSep.colSDem', "Required"), type: 'number', align: 'right' },
						{ key: 'capacity', title: localize('u3.mep.plbSep.colSCap', "Provided"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.plbSep.colSUnit', "Unit") },
						{ key: 'status', title: localize('u3.mep.plbSep.colSStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.plbSep.colSNote', "Note") },
					],
					rows: sepRows,
				},
			],
			notes: [...asStrings(septic.notes), ...asStrings(well.notes), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.plumbing.hydraulics',
	title: localize('u3.mep.plbHyd.title', "Water Supply Hydraulics & Transfer Pump"),
	part: 'mep',
	icon: Codicon.pulse,
	help: localize('u3.mep.plbHyd.help', "Evaluates WNTR/EPANET floor residual pressures, static head limits, pipe velocities, and transfer pump flow/head/motor sizing."),
	secondaryActions: openMepSectionAction('plumbing', localize('u3.mep.plbHyd.openSec', "Open MEP Plumbing")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/plumbingReport', {
			projectRoot: ctx.project!.root.fsPath,
			designs: false,
		}));
		const hyd = asBag(raw.hydraulics);
		const storage = asBag(raw.storage);
		const p3Pump = asBag(hyd.pump);
		const p1Pump = asBag(storage.pump);
		const floors = asArray(hyd.floors).map(asBag);
		const checks = asArray(hyd.checks).map(asBag);

		const reqHead = num(hyd.requiredHead) ?? num(asBag(storage.heads).minResidualHead);
		const floorRows: DataPanelRow[] = floors.map(f => {
			const head = num(f.head) ?? 0;
			const req = num(f.required) ?? reqHead ?? 0;
			const ok = typeof f.pressureOk === 'boolean' ? f.pressureOk : head >= req;
			return {
				story: str(f.story),
				riser: str(f.riser, '–'),
				elevation: num(f.elevation) ?? 0,
				head,
				required: req,
				status: ok ? 'Pass' : 'Fail',
			};
		});

		const flowLpm = num(p3Pump.flow) !== undefined ? Number((num(p3Pump.flow)! * 60).toFixed(1)) : num(p1Pump.flow);
		const pumpRows: DataPanelRow[] = [
			...(flowLpm !== undefined ? [{ parameter: localize('u3.mep.plbHyd.pFlow', "Transfer Pump Flow"), value: String(flowLpm), unit: 'L/min' }] : []),
			...(num(p3Pump.tdh ?? p3Pump.head) !== undefined ? [{ parameter: localize('u3.mep.plbHyd.pHead', "Total Dynamic Head"), value: String(num(p3Pump.tdh ?? p3Pump.head)), unit: 'm' }] : []),
			...(num(p3Pump.shaftPower ?? p3Pump.power) !== undefined ? [{ parameter: localize('u3.mep.plbHyd.pShaft', "Shaft Power"), value: String(num(p3Pump.shaftPower ?? p3Pump.power)), unit: 'kW' }] : []),
			...(num(p3Pump.motor) !== undefined ? [{ parameter: localize('u3.mep.plbHyd.pMotor', "Standard Motor Rating"), value: String(num(p3Pump.motor)), unit: 'kW' }] : []),
			...(str(p3Pump.note || p1Pump.note) ? [{ parameter: localize('u3.mep.plbHyd.pNote', "Note"), value: str(p3Pump.note || p1Pump.note), unit: '' }] : []),
		];

		const checkRows: DataPanelRow[] = checks.map(c => ({
			name: str(c.name),
			demand: num(c.demand) ?? '–',
			capacity: num(c.capacity) ?? '–',
			unit: str(c.unit, '-'),
			status: c.ok === false ? 'Fail' : 'Pass',
			note: str(c.note, '–'),
		}));

		const lowFloors = floorRows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u3.mep.plbHyd.mFloors', "Floors Checked"), value: String(floorRows.length) },
				{ label: localize('u3.mep.plbHyd.mLow', "Low-Pressure Floors"), value: String(lowFloors), tone: lowFloors ? 'fail' : 'ok' },
				{ label: localize('u3.mep.plbHyd.mReqHead', "Min Residual Head"), value: reqHead !== undefined ? `${reqHead.toFixed(1)} m` : '–' },
				{ label: localize('u3.mep.plbHyd.mPump', "Pump Flow"), value: flowLpm !== undefined ? `${flowLpm} L/min` : '–' },
			],
			tables: [
				{
					id: 'floors',
					title: localize('u3.mep.plbHyd.floorsTab', "Residual Head by Floor"),
					columns: [
						{ key: 'story', title: localize('u3.mep.plbHyd.colStory', "Story") },
						{ key: 'riser', title: localize('u3.mep.plbHyd.colRiser', "Riser") },
						{ key: 'elevation', title: localize('u3.mep.plbHyd.colElev', "Elevation [m]"), type: 'number', align: 'right' },
						{ key: 'head', title: localize('u3.mep.plbHyd.colHead', "Residual [m]"), type: 'number', align: 'right' },
						{ key: 'required', title: localize('u3.mep.plbHyd.colReq', "Required [m]"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.mep.plbHyd.colStatus', "Status"), type: 'status' },
					],
					rows: floorRows,
					emptyMessage: localize('u3.mep.plbHyd.noFloors', "No supply risers or overhead tank hydraulic network solved yet."),
				},
				{
					id: 'pump',
					title: localize('u3.mep.plbHyd.pumpTab', "Transfer Pump Sizing"),
					columns: [
						{ key: 'parameter', title: localize('u3.mep.plbHyd.colPParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.plbHyd.colPVal', "Value") },
						{ key: 'unit', title: localize('u3.mep.plbHyd.colPUnit', "Unit") },
					],
					rows: pumpRows,
				},
				{
					id: 'checks',
					title: localize('u3.mep.plbHyd.checksTab', "Hydraulic Checks"),
					columns: [
						{ key: 'name', title: localize('u3.mep.plbHyd.colCName', "Check") },
						{ key: 'demand', title: localize('u3.mep.plbHyd.colCDem', "Demand"), type: 'number', align: 'right' },
						{ key: 'capacity', title: localize('u3.mep.plbHyd.colCCap', "Limit"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.plbHyd.colCUnit', "Unit") },
						{ key: 'status', title: localize('u3.mep.plbHyd.colCStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.plbHyd.colCNote', "Note") },
					],
					rows: checkRows,
				},
			],
			notes: [...asStrings(hyd.notes), ...asStrings(raw.notes)],
			problems: [...asStrings(hyd.problems), ...asStrings(raw.problems)],
		};
	},
});

//#endregion

//#region Additional HVAC Panels (4)

registerMepPanel({
	id: 'saengine.mep.hvac.summary',
	title: localize('u3.mep.hvacSum.title', "HVAC Cooling Loads & Air Summary"),
	part: 'mep',
	icon: Codicon.output,
	help: localize('u3.mep.hvacSum.help', "Summarizes cached EnergyPlus or block cooling loads by story along with duct air-side checks and shafts."),
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.hvacSum.openSec', "Open MEP HVAC")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/hvacReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const air = asBag(raw.air);
		const stories = asArray(raw.stories).map(asBag);
		const ducts = asArray(air.ducts);
		const checks = asArray(air.checks).map(asBag);

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			area: num(s.area) ?? 0,
			sensible: num(s.sensible) ?? 0,
			latent: num(s.latent) ?? 0,
			total: num(s.total) ?? 0,
			airflow: num(s.airflow) ?? 0,
			outdoorAir: num(s.outdoorAir) ?? 0,
		}));

		const checkRows: DataPanelRow[] = checks.map(c => ({
			name: str(c.name),
			demand: num(c.demand) ?? '–',
			capacity: num(c.capacity) ?? '–',
			unit: str(c.unit, '-'),
			status: c.ok === false ? 'Fail' : 'Pass',
			note: str(c.note, '–'),
		}));

		const totalKw = num(raw.total) ?? 0;
		const tons = num(raw.tons) ?? 0;
		const failing = checkRows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u3.mep.hvacSum.mEngine', "Engine"), value: str(raw.engineLabel || raw.engine, '–') },
				{ label: localize('u3.mep.hvacSum.mTotal', "Total Cooling"), value: `${totalKw.toFixed(1)} kW (${tons.toFixed(1)} TR)`, tone: totalKw > 0 ? 'ok' : 'neutral' },
				{ label: localize('u3.mep.hvacSum.mDucts', "Duct Segments"), value: String(ducts.length) },
				{ label: localize('u3.mep.hvacSum.mFail', "Air-Side Fails"), value: String(failing), tone: failing ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'stories',
					title: localize('u3.mep.hvacSum.storiesTab', "Story Cooling Loads & Airflows"),
					columns: [
						{ key: 'story', title: localize('u3.mep.hvacSum.colStory', "Story") },
						{ key: 'area', title: localize('u3.mep.hvacSum.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'sensible', title: localize('u3.mep.hvacSum.colSens', "Sensible [kW]"), type: 'number', align: 'right' },
						{ key: 'latent', title: localize('u3.mep.hvacSum.colLat', "Latent [kW]"), type: 'number', align: 'right' },
						{ key: 'total', title: localize('u3.mep.hvacSum.colTot', "Total [kW]"), type: 'number', align: 'right' },
						{ key: 'airflow', title: localize('u3.mep.hvacSum.colAir', "Supply [m³/s]"), type: 'number', align: 'right' },
						{ key: 'outdoorAir', title: localize('u3.mep.hvacSum.colOa', "OA [m³/s]"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
				{
					id: 'checks',
					title: localize('u3.mep.hvacSum.checksTab', "Air-Side Checks"),
					columns: [
						{ key: 'name', title: localize('u3.mep.hvacSum.colCName', "Check") },
						{ key: 'demand', title: localize('u3.mep.hvacSum.colCDem', "Demand"), type: 'number', align: 'right' },
						{ key: 'capacity', title: localize('u3.mep.hvacSum.colCCap', "Capacity"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.hvacSum.colCUnit', "Unit") },
						{ key: 'status', title: localize('u3.mep.hvacSum.colCStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.hvacSum.colCNote', "Note") },
					],
					rows: checkRows,
				},
			],
			notes: [...asStrings(raw.notes), ...asStrings(air.notes)],
			problems: [...asStrings(raw.problems), ...asStrings(air.problems)],
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.hvac.openingsCheck',
	title: localize('u3.mep.hvacOpen.title', "HVAC Duct Openings & Beam Conflicts"),
	part: 'mep',
	icon: Codicon.circleLargeOutline,
	help: localize('u3.mep.hvacOpen.help', "Reports proposed slab/beam openings for HVAC ducts, beam crossings with no passing web opening, and stale duct openings."),
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.hvacOpen.openSec', "Open MEP HVAC")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/hvacDuctOpenings', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const openings = asArray(raw.openings).map(asBag);
		const conflicts = asArray(raw.conflicts).map(asBag);
		const stale = asArray(raw.stale);

		const openingRows: DataPanelRow[] = openings.map(o => ({
			id: str(o.id),
			host: str(o.host),
			kind: str(o.kind, 'opening'),
			shape: str(o.shape),
			size: formatOpeningSize(o),
			service: str(o.service, '–'),
		}));

		const conflictRows: DataPanelRow[] = conflicts.map(c => ({
			duct: str(c.duct || c.id, '–'),
			beam: str(c.beam || c.host, '–'),
			note: str(c.note, asStrings(c.options).join('; ') || 'No checked beam web opening fits'),
		}));

		const staleRows: DataPanelRow[] = stale.map(entry => {
			if (typeof entry === 'string') {
				return { id: entry, note: localize('u3.mep.hvacOpen.staleDefault', "Duct moved or removed; opening no longer needed") };
			}
			const b = asBag(entry);
			return { id: str(b.id), note: str(b.note, localize('u3.mep.hvacOpen.staleDefault', "Duct moved or removed; opening no longer needed")) };
		});

		return {
			metrics: [
				{ label: localize('u3.mep.hvacOpen.mOpenings', "Proposed Openings"), value: String(openingRows.length) },
				{ label: localize('u3.mep.hvacOpen.mConflicts', "Beam Conflicts"), value: String(conflictRows.length), tone: conflictRows.length ? 'warn' : 'ok' },
				{ label: localize('u3.mep.hvacOpen.mStale', "Stale Openings"), value: String(staleRows.length), tone: staleRows.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'openings',
					title: localize('u3.mep.hvacOpen.openingsTab', "Proposed Duct Openings"),
					columns: [
						{ key: 'id', title: localize('u3.mep.hvacOpen.colId', "Opening") },
						{ key: 'host', title: localize('u3.mep.hvacOpen.colHost', "Host") },
						{ key: 'kind', title: localize('u3.mep.hvacOpen.colKind', "Kind") },
						{ key: 'shape', title: localize('u3.mep.hvacOpen.colShape', "Shape") },
						{ key: 'size', title: localize('u3.mep.hvacOpen.colSize', "Size") },
						{ key: 'service', title: localize('u3.mep.hvacOpen.colService', "Service") },
					],
					rows: openingRows,
					emptyMessage: localize('u3.mep.hvacOpen.noOpenings', "No additional duct openings needed or no ducts defined yet."),
				},
				{
					id: 'conflicts',
					title: localize('u3.mep.hvacOpen.conflictsTab', "Beam Crossing Conflicts"),
					columns: [
						{ key: 'duct', title: localize('u3.mep.hvacOpen.colCDuct', "Duct") },
						{ key: 'beam', title: localize('u3.mep.hvacOpen.colCBeam', "Beam / Host") },
						{ key: 'note', title: localize('u3.mep.hvacOpen.colCNote', "Resolution Note") },
					],
					rows: conflictRows,
				},
				{
					id: 'stale',
					title: localize('u3.mep.hvacOpen.staleTab', "Stale Openings"),
					columns: [
						{ key: 'id', title: localize('u3.mep.hvacOpen.colSId', "Opening") },
						{ key: 'note', title: localize('u3.mep.hvacOpen.colSNote', "Status") },
					],
					rows: staleRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.hvac.constructions',
	title: localize('u3.mep.hvacConst.title', "Envelope Constructions & U-Values"),
	part: 'mep',
	requiresProject: false,
	icon: Codicon.layers,
	help: localize('u3.mep.hvacConst.help', "Lists built-in wall, roof and glazing thermal assemblies with U-values and solar heat gain coefficients (SHGC)."),
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.hvacConst.openSec', "Open MEP HVAC")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/hvacConstructions', {}));
		const walls: DataPanelRow[] = asArray(raw.wall).map(asBag).map(w => ({
			key: str(w.key),
			label: str(w.label),
			u: num(w.u) ?? 0,
		}));
		const roofs: DataPanelRow[] = asArray(raw.roof).map(asBag).map(r => ({
			key: str(r.key),
			label: str(r.label),
			u: num(r.u) ?? 0,
		}));
		const glazings: DataPanelRow[] = asArray(raw.glazing).map(asBag).map(g => ({
			key: str(g.key),
			label: str(g.label),
			u: num(g.u) ?? 0,
			shgc: num(g.shgc) ?? '–',
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.hvacConst.mWalls', "Walls"), value: String(walls.length) },
				{ label: localize('u3.mep.hvacConst.mRoofs', "Roofs"), value: String(roofs.length) },
				{ label: localize('u3.mep.hvacConst.mGlazing', "Glazing"), value: String(glazings.length) },
			],
			tables: [
				{
					id: 'walls',
					title: localize('u3.mep.hvacConst.wallsTab', "Wall Assemblies"),
					columns: [
						{ key: 'key', title: localize('u3.mep.hvacConst.colWKey', "Key") },
						{ key: 'label', title: localize('u3.mep.hvacConst.colWLabel', "Description") },
						{ key: 'u', title: localize('u3.mep.hvacConst.colWU', "U-Value [W/m²K]"), type: 'number', align: 'right' },
					],
					rows: walls,
				},
				{
					id: 'roofs',
					title: localize('u3.mep.hvacConst.roofsTab', "Roof Assemblies"),
					columns: [
						{ key: 'key', title: localize('u3.mep.hvacConst.colRKey', "Key") },
						{ key: 'label', title: localize('u3.mep.hvacConst.colRLabel', "Description") },
						{ key: 'u', title: localize('u3.mep.hvacConst.colRU', "U-Value [W/m²K]"), type: 'number', align: 'right' },
					],
					rows: roofs,
				},
				{
					id: 'glazing',
					title: localize('u3.mep.hvacConst.glazingTab', "Glazing Assemblies"),
					columns: [
						{ key: 'key', title: localize('u3.mep.hvacConst.colGKey', "Key") },
						{ key: 'label', title: localize('u3.mep.hvacConst.colGLabel', "Description") },
						{ key: 'u', title: localize('u3.mep.hvacConst.colGU', "U-Value [W/m²K]"), type: 'number', align: 'right' },
						{ key: 'shgc', title: localize('u3.mep.hvacConst.colGShgc', "SHGC"), type: 'number', align: 'right' },
					],
					rows: glazings,
				},
			],
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.hvac.tables',
	title: localize('u3.mep.hvacTbl.title', "HVAC Weather & Ventilation Design Tables"),
	part: 'mep',
	requiresProject: false,
	icon: Codicon.table,
	help: localize('u3.mep.hvacTbl.help', "Shows code-pack outdoor cooling design conditions (2% DB/MCWB/range) and ASHRAE 62.1 / BNBC ventilation rates."),
	secondaryActions: openMepSectionAction('hvac', localize('u3.mep.hvacTbl.openSec', "Open MEP HVAC")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/hvacTables', {}));
		const cities: DataPanelRow[] = asArray(raw.cities).map(asBag).map(c => ({
			label: str(c.label),
			db: num(c.db) ?? 0,
			wb: num(c.wb) ?? 0,
			range: num(c.range) ?? 0,
		}));
		const uses: DataPanelRow[] = asArray(raw.uses).map(asBag).map(u => ({
			label: str(u.label),
			perPerson: num(u.perPerson) ?? '–',
			perArea: num(u.perArea) ?? '–',
			density: num(u.density) ?? '–',
			source: str(u.source, '–'),
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.hvacTbl.mCities', "Weather Stations"), value: String(cities.length) },
				{ label: localize('u3.mep.hvacTbl.mUses', "Ventilation Uses"), value: String(uses.length) },
			],
			tables: [
				{
					id: 'cities',
					title: localize('u3.mep.hvacTbl.citiesTab', "Cooling Design Conditions (2%)"),
					columns: [
						{ key: 'label', title: localize('u3.mep.hvacTbl.colCity', "Station") },
						{ key: 'db', title: localize('u3.mep.hvacTbl.colDb', "Dry Bulb [°C]"), type: 'number', align: 'right' },
						{ key: 'wb', title: localize('u3.mep.hvacTbl.colWb', "MCWB [°C]"), type: 'number', align: 'right' },
						{ key: 'range', title: localize('u3.mep.hvacTbl.colRange', "Daily Range [°C]"), type: 'number', align: 'right' },
					],
					rows: cities,
				},
				{
					id: 'uses',
					title: localize('u3.mep.hvacTbl.usesTab', "Outdoor Air Ventilation Rates"),
					columns: [
						{ key: 'label', title: localize('u3.mep.hvacTbl.colUse', "Occupancy Use") },
						{ key: 'perPerson', title: localize('u3.mep.hvacTbl.colRp', "Per Person [L/s]"), type: 'number', align: 'right' },
						{ key: 'perArea', title: localize('u3.mep.hvacTbl.colRa', "Per Area [L/s·m²]"), type: 'number', align: 'right' },
						{ key: 'density', title: localize('u3.mep.hvacTbl.colDens', "Occupants / 100 m²"), type: 'number', align: 'right' },
						{ key: 'source', title: localize('u3.mep.hvacTbl.colSrc', "Source") },
					],
					rows: uses,
				},
			],
		};
	},
});

//#endregion

//#region Additional Electrical Panels (5)

registerMepPanel({
	id: 'saengine.mep.electrical.uses',
	title: localize('u3.mep.elecUses.title', "Electrical Load Density Table"),
	part: 'mep',
	requiresProject: false,
	icon: Codicon.book,
	help: localize('u3.mep.elecUses.help', "Lists code-pack minimum electrical load densities [W/m²] for non-air-conditioned and air-conditioned occupancies."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.elecUses.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalUses', {}));
		const rows: DataPanelRow[] = asArray(raw.uses).map(asBag).map(u => ({
			label: str(u.label),
			nonAc: num(u.nonAc) ?? '–',
			ac: num(u.ac) ?? '–',
			source: str(u.source, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u3.mep.elecUses.mCount', "Occupancy Categories"), value: String(rows.length) },
			],
			tables: [{
				id: 'uses',
				title: localize('u3.mep.elecUses.tab', "Minimum Electrical Load Densities"),
				columns: [
					{ key: 'label', title: localize('u3.mep.elecUses.colLabel', "Occupancy") },
					{ key: 'nonAc', title: localize('u3.mep.elecUses.colNonAc', "Non-A/C [W/m²]"), type: 'number', align: 'right' },
					{ key: 'ac', title: localize('u3.mep.elecUses.colAc', "A/C [W/m²]"), type: 'number', align: 'right' },
					{ key: 'source', title: localize('u3.mep.elecUses.colSource', "Reference") },
				],
				rows,
			}],
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.demand',
	title: localize('u3.mep.elecDem.title', "Electrical Demand Schedule & Plant Rooms"),
	part: 'mep',
	icon: Codicon.graph,
	help: localize('u3.mep.elecDem.help', "Summarizes connected load, diversified maximum demand (kW / kVA), story demand breakdown, and substation/generator room checks."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.elecDem.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const demand = asBag(raw.demand);
		const stories = asArray(demand.stories).map(asBag);
		const rooms = asArray(raw.rooms).map(asBag);

		const storyRows: DataPanelRow[] = stories.map(s => ({
			story: str(s.story),
			use: str(s.useLabel || s.use, '–'),
			area: num(s.area) ?? 0,
			density: num(s.density) ?? 0,
			connected: num(s.connected) ?? 0,
			demand: num(s.demand) ?? 0,
			kva: num(s.kva) ?? 0,
		}));

		const roomRows: DataPanelRow[] = rooms.map(r => ({
			name: str(r.name),
			demand: num(r.demand) ?? '–',
			capacity: num(r.capacity) ?? '–',
			unit: str(r.unit, 'm²'),
			status: r.ok === false ? 'Fail' : 'Pass',
			note: str(r.note, '–'),
		}));

		const roomFails = roomRows.filter(r => r.status === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u3.mep.elecDem.mConn', "Connected Load"), value: `${(num(demand.connected) ?? 0).toFixed(1)} kW` },
				{ label: localize('u3.mep.elecDem.mMax', "Maximum Demand"), value: `${(num(demand.maximumDemand) ?? 0).toFixed(1)} kW (${(num(demand.kva) ?? 0).toFixed(1)} kVA)` },
				{ label: localize('u3.mep.elecDem.mCurrent', "Line Current (400 V)"), value: `${(num(demand.current) ?? 0).toFixed(0)} A` },
				{ label: localize('u3.mep.elecDem.mRooms', "Room Check Fails"), value: String(roomFails), tone: roomFails ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'stories',
					title: localize('u3.mep.elecDem.storiesTab', "Demand by Story"),
					columns: [
						{ key: 'story', title: localize('u3.mep.elecDem.colStory', "Story") },
						{ key: 'use', title: localize('u3.mep.elecDem.colUse', "Occupancy") },
						{ key: 'area', title: localize('u3.mep.elecDem.colArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'density', title: localize('u3.mep.elecDem.colDens', "Unit Load [W/m²]"), type: 'number', align: 'right' },
						{ key: 'connected', title: localize('u3.mep.elecDem.colConn', "Connected [kW]"), type: 'number', align: 'right' },
						{ key: 'demand', title: localize('u3.mep.elecDem.colDem', "Demand [kW]"), type: 'number', align: 'right' },
						{ key: 'kva', title: localize('u3.mep.elecDem.colKva', "Demand [kVA]"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
				{
					id: 'rooms',
					title: localize('u3.mep.elecDem.roomsTab', "Electrical Room Checks"),
					columns: [
						{ key: 'name', title: localize('u3.mep.elecDem.colRName', "Room Check") },
						{ key: 'demand', title: localize('u3.mep.elecDem.colRDem', "Required"), type: 'number', align: 'right' },
						{ key: 'capacity', title: localize('u3.mep.elecDem.colRCap', "Provided"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.elecDem.colRUnit', "Unit") },
						{ key: 'status', title: localize('u3.mep.elecDem.colRStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.elecDem.colRNote', "Note") },
					],
					rows: roomRows,
				},
			],
			notes: [...asStrings(raw.notes), ...asStrings(demand.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.supply',
	title: localize('u3.mep.elecSup.title', "Substation, Transformers, Generator & UPS"),
	part: 'mep',
	icon: Codicon.zap,
	help: localize('u3.mep.elecSup.help', "Evaluates substation transformer rating, standby diesel generator and fuel tank sizing, UPS capacity, and proposed heavy equipment."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.elecSup.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const supply = asBag(raw.supply);
		const tx = asBag(supply.transformers);
		const gen = asBag(supply.generator);
		const ups = asBag(supply.ups);
		const proposed = asArray(raw.equipment).map(asBag);

		const sourceRows: DataPanelRow[] = [
			...(Object.keys(tx).length ? [{
				source: localize('u3.mep.elecSup.tx', "Transformers"),
				required: num(tx.required) ?? '–',
				provided: num(tx.total) ?? '–',
				unit: 'kVA',
				note: `${str(tx.count, '0')} × ${str(tx.rating, '–')} kVA${tx.substationArea ? `; substation ${str(tx.substationArea)} m²` : ''}`,
			}] : []),
			...(Object.keys(gen).length && num(gen.kva) ? [{
				source: localize('u3.mep.elecSup.gen', "Standby Generator"),
				required: num(gen.required) ?? '–',
				provided: num(gen.kva) ?? '–',
				unit: 'kVA',
				note: `Fuel ${str(gen.fuel, '–')} L (${str(gen.fuelHours, '–')} h)${gen.roomArea ? `; room ${str(gen.roomArea)} m²` : ''}`,
			}] : []),
			...(Object.keys(ups).length && num(ups.kva) ? [{
				source: localize('u3.mep.elecSup.ups', "UPS & Battery"),
				required: num(ups.load) !== undefined ? Number((num(ups.load)! / 0.9).toFixed(1)) : '–',
				provided: num(ups.kva) ?? '–',
				unit: 'kVA',
				note: `${str(ups.autonomy, '15')} min autonomy; UPS ${str(ups.upsWeight, '–')} kN, battery ${str(ups.batteryWeight, '–')} kN`,
			}] : []),
		];

		const proposedRows: DataPanelRow[] = proposed.map(e => ({
			id: str(e.id),
			kind: str(e.kind),
			name: str(e.name, '–'),
			story: str(e.story, '–'),
			rating: num(e.rating) ?? '–',
			operatingWeight: num(e.operatingWeight) ?? 0,
			size: `${str(e.length, '–')}×${str(e.width, '–')} mm`,
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.elecSup.mVolt', "Supply Voltage"), value: str(supply.voltage, '0.4kV') },
				{ label: localize('u3.mep.elecSup.mTx', "Transformers"), value: num(tx.count) ? `${str(tx.count)} × ${str(tx.rating)} kVA` : 'None' },
				{ label: localize('u3.mep.elecSup.mGen', "Generator"), value: num(gen.kva) ? `${str(gen.kva)} kVA` : 'None' },
				{ label: localize('u3.mep.elecSup.mUps', "UPS"), value: num(ups.kva) ? `${str(ups.kva)} kVA` : 'None' },
			],
			tables: [
				{
					id: 'sources',
					title: localize('u3.mep.elecSup.sourcesTab', "Power Supply Equipment Sizing"),
					columns: [
						{ key: 'source', title: localize('u3.mep.elecSup.colSource', "Source") },
						{ key: 'required', title: localize('u3.mep.elecSup.colReq', "Required"), type: 'number', align: 'right' },
						{ key: 'provided', title: localize('u3.mep.elecSup.colProv', "Provided"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.elecSup.colUnit', "Unit") },
						{ key: 'note', title: localize('u3.mep.elecSup.colNote', "Details") },
					],
					rows: sourceRows,
				},
				{
					id: 'proposed',
					title: localize('u3.mep.elecSup.propTab', "Proposed Equipment Loads"),
					columns: [
						{ key: 'id', title: localize('u3.mep.elecSup.colPId', "ID") },
						{ key: 'kind', title: localize('u3.mep.elecSup.colPKind', "Kind") },
						{ key: 'name', title: localize('u3.mep.elecSup.colPName', "Name") },
						{ key: 'story', title: localize('u3.mep.elecSup.colPStory', "Story") },
						{ key: 'rating', title: localize('u3.mep.elecSup.colPRating', "Rating"), type: 'number', align: 'right' },
						{ key: 'operatingWeight', title: localize('u3.mep.elecSup.colPWeight', "Weight [kN]"), type: 'number', align: 'right' },
						{ key: 'size', title: localize('u3.mep.elecSup.colPSize', "Footprint") },
					],
					rows: proposedRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.lightning',
	title: localize('u3.mep.elecLightn.title', "Lightning Protection & Earthing"),
	part: 'mep',
	icon: Codicon.shield,
	help: localize('u3.mep.elecLightn.help', "Evaluates lightning risk index, IEC/BNBC protection level, roof air terminals, structural down-conductor columns, and earthing resistance limits."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.elecLightn.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const ltg = asBag(raw.lightning);
		const risk = asBag(ltg.risk);
		const earth = asBag(ltg.earth);
		const downConductors = asArray(ltg.downConductors).map(asBag);
		const airTerminals = asArray(ltg.airTerminals);

		const dcRows: DataPanelRow[] = downConductors.map((dc, i) => {
			const cols = asStrings(dc.columns);
			return {
				id: str(dc.id || `DC${i + 1}`),
				column: cols[0] ?? str(dc.column, '–'),
				columns: cols.join(' -> ') || '–',
				foundation: str(dc.foundation, '–'),
				testBox: num(dc.testBox) ?? '–',
				conductor: str(dc.conductor, '–'),
			};
		});

		const summaryRows: DataPanelRow[] = Object.keys(ltg).length ? [
			{ parameter: localize('u3.mep.elecLightn.pLevel', "Protection Level"), value: str(ltg.level, '–') },
			{ parameter: localize('u3.mep.elecLightn.pDecision', "Risk Decision"), value: str(risk.decision, '–') },
			{ parameter: localize('u3.mep.elecLightn.pRisk', "Total Risk Index"), value: formatScalar(risk.total) },
			{ parameter: localize('u3.mep.elecLightn.pEarth', "Earthing Arrangement"), value: str(earth.arrangement || ltg.earthing, '–') },
			{ parameter: localize('u3.mep.elecLightn.pRes', "Max Earth Resistance"), value: num(earth.limit) !== undefined ? `${num(earth.limit)} Ω` : '–' },
			{ parameter: localize('u3.mep.elecLightn.pClear', "Separation Clearance"), value: num(earth.clearance) !== undefined ? `${num(earth.clearance)!.toFixed(2)} m` : '–' },
		] : [];

		return {
			metrics: [
				{ label: localize('u3.mep.elecLightn.mRisk', "Risk Index"), value: formatScalar(risk.total) },
				{ label: localize('u3.mep.elecLightn.mDecision', "Decision"), value: str(risk.decision, '–'), tone: risk.decision === 'required' ? 'warn' : 'ok' },
				{ label: localize('u3.mep.elecLightn.mDown', "Down Conductors"), value: String(dcRows.length) },
				{ label: localize('u3.mep.elecLightn.mAir', "Air Terminals"), value: String(airTerminals.length) },
			],
			tables: [
				{
					id: 'downConductors',
					title: localize('u3.mep.elecLightn.dcTab', "Down-Conductor Columns"),
					columns: [
						{ key: 'id', title: localize('u3.mep.elecLightn.colId', "ID") },
						{ key: 'column', title: localize('u3.mep.elecLightn.colBase', "Base Column") },
						{ key: 'columns', title: localize('u3.mep.elecLightn.colChain', "Continuous Stack") },
						{ key: 'foundation', title: localize('u3.mep.elecLightn.colFound', "Foundation Electrode") },
						{ key: 'testBox', title: localize('u3.mep.elecLightn.colTest', "Test Box [mm]"), type: 'number', align: 'right' },
						{ key: 'conductor', title: localize('u3.mep.elecLightn.colCond', "Conductor") },
					],
					rows: dcRows,
				},
				{
					id: 'summary',
					title: localize('u3.mep.elecLightn.sumTab', "Lightning & Earthing Parameters"),
					columns: [
						{ key: 'parameter', title: localize('u3.mep.elecLightn.colParam', "Parameter") },
						{ key: 'value', title: localize('u3.mep.elecLightn.colVal', "Value") },
					],
					rows: summaryRows,
				},
			],
			notes: [...asStrings(ltg.structuralNotes), ...asStrings(ltg.notes), ...asStrings(raw.notes)],
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.electrical.risers',
	title: localize('u3.mep.elecRisers.title', "Electrical Risers & Cable Tray Crossings"),
	part: 'mep',
	icon: Codicon.arrowUp,
	help: localize('u3.mep.elecRisers.help', "Sizes rising mains and busbars, evaluates cable tray beam crossings and headroom, and lists required structural openings."),
	secondaryActions: openMepSectionAction('electrical', localize('u3.mep.elecRisers.openSec', "Open MEP Electrical")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/electricalReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const risers = asArray(raw.risers).map(asBag);
		const trays = asArray(raw.trays).map(asBag);
		const openings = asArray(raw.openings);

		const riserRows: DataPanelRow[] = risers.map(r => {
			const w = num(r.width);
			const d = num(r.depth);
			const size = w !== undefined && d !== undefined ? `${Math.round(w)}×${Math.round(d)} mm` : '–';
			return {
				id: str(r.id),
				kind: str(r.kind, '–'),
				current: num(r.current) ?? 0,
				rating: num(r.rating) ?? '–',
				size,
				status: r.ok === false ? 'Fail' : 'Pass',
				note: asStrings(r.notes).join('; ') || '–',
			};
		});

		const trayRows: DataPanelRow[] = trays.map(t => {
			const below = t.passesBelow === true;
			const fits = t.fits !== false;
			return {
				tray: str(t.tray || t.id),
				beam: str(t.beam, '–'),
				passesBelow: below ? 'Yes' : 'No',
				fits: fits ? 'Yes' : 'No',
				status: below || fits ? 'Pass' : 'Fail',
			};
		});

		return {
			metrics: [
				{ label: localize('u3.mep.elecRisers.mRisers', "Risers"), value: String(riserRows.length) },
				{ label: localize('u3.mep.elecRisers.mTrays', "Tray Crossings"), value: String(trayRows.length) },
				{ label: localize('u3.mep.elecRisers.mOpen', "Missing Openings"), value: String(openings.length), tone: openings.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'risers',
					title: localize('u3.mep.elecRisers.risersTab', "Electrical Risers"),
					columns: [
						{ key: 'id', title: localize('u3.mep.elecRisers.colId', "Riser") },
						{ key: 'kind', title: localize('u3.mep.elecRisers.colKind', "Kind") },
						{ key: 'current', title: localize('u3.mep.elecRisers.colCurr', "Current [A]"), type: 'number', align: 'right' },
						{ key: 'rating', title: localize('u3.mep.elecRisers.colRat', "Rating [A]"), type: 'number', align: 'right' },
						{ key: 'size', title: localize('u3.mep.elecRisers.colSize', "Dimensions") },
						{ key: 'status', title: localize('u3.mep.elecRisers.colStatus', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.mep.elecRisers.colNote', "Note") },
					],
					rows: riserRows,
				},
				{
					id: 'trays',
					title: localize('u3.mep.elecRisers.traysTab', "Cable Tray Beam Crossings"),
					columns: [
						{ key: 'tray', title: localize('u3.mep.elecRisers.colTTray', "Tray") },
						{ key: 'beam', title: localize('u3.mep.elecRisers.colTBeam', "Beam") },
						{ key: 'passesBelow', title: localize('u3.mep.elecRisers.colTBelow', "Passes Below") },
						{ key: 'fits', title: localize('u3.mep.elecRisers.colTFits', "Web Opening Fits") },
						{ key: 'status', title: localize('u3.mep.elecRisers.colTStatus', "Status"), type: 'status' },
					],
					rows: trayRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Additional Fire Protection Panels (4)

registerMepPanel({
	id: 'saengine.mep.fire.proposals',
	title: localize('u3.mep.fireProp.title', "Fire Water Supply Proposals"),
	part: 'mep',
	icon: Codicon.database,
	help: localize('u3.mep.fireProp.help', "Computes proposed fire water storage tanks and main/standby/jockey fire pump sets for the project."),
	secondaryActions: openMepSectionAction('fire', localize('u3.mep.fireProp.openSec', "Open MEP Fire")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/fireProposals', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const tanks = asArray(raw.tanks).map(asBag);
		const pumps = asArray(raw.pumps).map(asBag);

		const tankRows: DataPanelRow[] = tanks.map(t => ({
			id: str(t.id),
			kind: str(t.kind),
			length: num(t.length) ?? 0,
			width: num(t.width) ?? 0,
			waterDepth: num(t.waterDepth) ?? 0,
			freeboard: num(t.freeboard) ?? 0,
			compartments: num(t.compartments) ?? 1,
			construction: str(t.construction, 'rc'),
		}));

		const pumpRows: DataPanelRow[] = pumps.map(p => ({
			id: str(p.id),
			duty: str(p.duty),
			story: str(p.story, '–'),
			flow: num(p.flow) ?? 0,
			head: num(p.head) ?? 0,
			power: num(p.power) ?? 0,
			operatingWeight: num(p.operatingWeight) ?? 0,
			size: `${str(p.length, '–')}×${str(p.width, '–')}×${str(p.height, '–')} mm`,
		}));

		const mainPump = pumps.find(p => p.duty === 'main');
		return {
			metrics: [
				{ label: localize('u3.mep.fireProp.mTanks', "Proposed Tanks"), value: String(tankRows.length) },
				{ label: localize('u3.mep.fireProp.mPumps', "Proposed Pumps"), value: String(pumpRows.length) },
				{ label: localize('u3.mep.fireProp.mMain', "Main Pump Duty"), value: mainPump ? `${num(mainPump.flow) ?? 0} L/min @ ${num(mainPump.head) ?? 0} m` : '–' },
			],
			tables: [
				{
					id: 'tanks',
					title: localize('u3.mep.fireProp.tanksTab', "Proposed Fire Tanks"),
					columns: [
						{ key: 'id', title: localize('u3.mep.fireProp.colTId', "Tank") },
						{ key: 'kind', title: localize('u3.mep.fireProp.colTKind', "Kind") },
						{ key: 'length', title: localize('u3.mep.fireProp.colTLen', "Length [mm]"), type: 'number', align: 'right' },
						{ key: 'width', title: localize('u3.mep.fireProp.colTWid', "Width [mm]"), type: 'number', align: 'right' },
						{ key: 'waterDepth', title: localize('u3.mep.fireProp.colTDepth', "Depth [mm]"), type: 'number', align: 'right' },
						{ key: 'freeboard', title: localize('u3.mep.fireProp.colTFree', "Freeboard [mm]"), type: 'number', align: 'right' },
						{ key: 'compartments', title: localize('u3.mep.fireProp.colTComp', "Compartments"), type: 'number', align: 'right' },
						{ key: 'construction', title: localize('u3.mep.fireProp.colTConst', "Construction") },
					],
					rows: tankRows,
					emptyMessage: localize('u3.mep.fireProp.noTanks', "Existing tanks satisfy fire demand or no fire stories configured yet."),
				},
				{
					id: 'pumps',
					title: localize('u3.mep.fireProp.pumpsTab', "Proposed Fire Pumps"),
					columns: [
						{ key: 'id', title: localize('u3.mep.fireProp.colPId', "Pump") },
						{ key: 'duty', title: localize('u3.mep.fireProp.colPDuty', "Duty") },
						{ key: 'story', title: localize('u3.mep.fireProp.colPStory', "Story") },
						{ key: 'flow', title: localize('u3.mep.fireProp.colPFlow', "Flow [L/min]"), type: 'number', align: 'right' },
						{ key: 'head', title: localize('u3.mep.fireProp.colPHead', "Head [m]"), type: 'number', align: 'right' },
						{ key: 'power', title: localize('u3.mep.fireProp.colPPower', "Power [kW]"), type: 'number', align: 'right' },
						{ key: 'operatingWeight', title: localize('u3.mep.fireProp.colPWeight', "Weight [kN]"), type: 'number', align: 'right' },
						{ key: 'size', title: localize('u3.mep.fireProp.colPSize', "Dimensions") },
					],
					rows: pumpRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.fire.requirements',
	title: localize('u3.mep.fireReq.title', "Fire Protection Code Requirements"),
	part: 'mep',
	icon: Codicon.checklist,
	help: localize('u3.mep.fireReq.help', "Evaluates required active fire systems (hydrants, sprinklers, alarm, extinguishers), occupancy hazard classification, and clauses."),
	secondaryActions: openMepSectionAction('fire', localize('u3.mep.fireReq.openSec', "Open MEP Fire")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/fireReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const req = asBag(raw.requirements);
		const systems = asArray(req.systems).map(asBag);
		const rules = asArray(req.rules).map(asBag);
		const stories = asArray(raw.stories).map(asBag);
		const checks = asArray(raw.checks).map(asBag);

		const systemRows: DataPanelRow[] = systems.map(s => ({
			label: str(s.label || s.system),
			status: str(s.status),
			provided: s.provided ? 'Yes' : 'No',
			reasons: asStrings(s.reasons).join(' · ') || '–',
		}));

		const storyRows: DataPanelRow[] = stories.map(s => {
			const spr = asBag(s.sprinklers);
			return {
				story: str(s.story),
				occupancy: str(s.occupancy, '–'),
				group: str(s.group, '–'),
				hazard: str(s.hazard, '–'),
				area: num(s.area) ?? 0,
				sprinklered: s.sprinklered ? 'Yes' : 'No',
				heads: num(spr.heads) ?? '–',
				extinguishers: num(s.extinguishers) ?? '–',
				callPoints: num(s.callPoints) ?? '–',
				detectors: num(s.detectors) ?? '–',
			};
		});

		const ruleRows: DataPanelRow[] = rules.map(r => ({
			group: str(r.group),
			clause: str(r.clause),
			text: str(r.text),
		}));

		const requiredCount = systems.filter(s => s.status === 'required').length;
		const failing = checks.filter(c => c.ok === false).length;
		return {
			metrics: [
				{ label: localize('u3.mep.fireReq.mReq', "Required Systems"), value: String(requiredCount) },
				{ label: localize('u3.mep.fireReq.mHigh', "Building Class"), value: req.highRise ? localize('u3.mep.fireReq.highRise', "High-Rise") : localize('u3.mep.fireReq.standard', "Standard") },
				{ label: localize('u3.mep.fireReq.mStories', "Stories"), value: String(storyRows.length) },
				{ label: localize('u3.mep.fireReq.mFail', "Failing Checks"), value: String(failing), tone: failing ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'systems',
					title: localize('u3.mep.fireReq.systemsTab', "Required Fire Protection Systems"),
					columns: [
						{ key: 'label', title: localize('u3.mep.fireReq.colSystem', "System") },
						{ key: 'status', title: localize('u3.mep.fireReq.colStatus', "Requirement") },
						{ key: 'provided', title: localize('u3.mep.fireReq.colProvided', "Designed") },
						{ key: 'reasons', title: localize('u3.mep.fireReq.colReason', "Clauses & Basis") },
					],
					rows: systemRows,
				},
				{
					id: 'stories',
					title: localize('u3.mep.fireReq.storiesTab', "Floor Classifications & Devices"),
					columns: [
						{ key: 'story', title: localize('u3.mep.fireReq.colFStory', "Story") },
						{ key: 'occupancy', title: localize('u3.mep.fireReq.colFOcc', "Occupancy") },
						{ key: 'group', title: localize('u3.mep.fireReq.colFGroup', "Group") },
						{ key: 'hazard', title: localize('u3.mep.fireReq.colFHaz', "Hazard") },
						{ key: 'area', title: localize('u3.mep.fireReq.colFArea', "Area [m²]"), type: 'number', align: 'right' },
						{ key: 'sprinklered', title: localize('u3.mep.fireReq.colFSpr', "Sprinklered") },
						{ key: 'heads', title: localize('u3.mep.fireReq.colFHeads', "Heads"), type: 'number', align: 'right' },
						{ key: 'extinguishers', title: localize('u3.mep.fireReq.colFExt', "Extinguishers"), type: 'number', align: 'right' },
						{ key: 'callPoints', title: localize('u3.mep.fireReq.colFMcp', "Call Points"), type: 'number', align: 'right' },
						{ key: 'detectors', title: localize('u3.mep.fireReq.colFDet', "Detectors"), type: 'number', align: 'right' },
					],
					rows: storyRows,
				},
				{
					id: 'rules',
					title: localize('u3.mep.fireReq.rulesTab', "Applicable Code Clauses"),
					columns: [
						{ key: 'group', title: localize('u3.mep.fireReq.colRGrp', "Group") },
						{ key: 'clause', title: localize('u3.mep.fireReq.colRClause', "Clause") },
						{ key: 'text', title: localize('u3.mep.fireReq.colRText', "Requirement") },
					],
					rows: ruleRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.fire.hydraulics',
	title: localize('u3.mep.fireHyd.title', "Fire Water Demand, Hydraulics & Supports"),
	part: 'mep',
	icon: Codicon.pulse,
	help: localize('u3.mep.fireHyd.help', "Reports fire water demand, reservoir volume, standpipe/sprinkler hydraulic pump duty, hanger support loads, and test pressures."),
	secondaryActions: openMepSectionAction('fire', localize('u3.mep.fireHyd.openSec', "Open MEP Fire")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/fireReport', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const demand = asBag(raw.demand);
		const hyd = asBag(raw.hydraulics);
		const pumps = asArray(raw.pumps).map(asBag);
		const supports = asArray(raw.supports).map(asBag);
		const tests = asArray(raw.testPressures).map(asBag);
		const checks = asArray(raw.checks).map(asBag);

		const pumpRows: DataPanelRow[] = pumps.map(p => ({
			duty: str(p.duty),
			label: str(p.label || p.duty),
			flow: num(p.flow) ?? 0,
			head: num(p.head) ?? 0,
			power: num(p.power) ?? 0,
			count: num(p.count) ?? 1,
			operatingWeight: num(p.operatingWeight) ?? 0,
		}));

		const supportRows: DataPanelRow[] = supports.map(s => ({
			size: num(s.size) ?? '–',
			kind: str(s.kind),
			spacing: num(s.spacing) ?? '–',
			load: num(s.load) ?? 0,
			basis: str(s.basis, '–'),
		}));

		const testRows: DataPanelRow[] = tests.map(t => ({
			system: str(t.system),
			pressure: num(t.pressure) ?? 0,
			note: str(t.note, '–'),
		}));

		const checkRows: DataPanelRow[] = checks.map(c => ({
			name: str(c.name),
			demand: num(c.demand) ?? '–',
			capacity: num(c.capacity) ?? '–',
			unit: str(c.unit, '-'),
			status: c.ok === false ? 'Fail' : 'Pass',
			clause: str(c.clause, '–'),
			note: str(c.note, '–'),
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.fireHyd.mFlow', "Fire Water Flow"), value: `${num(demand.flow) ?? 0} L/min` },
				{ label: localize('u3.mep.fireHyd.mVol', "Reservoir"), value: `${num(demand.volume) ?? 0} m³` },
				{ label: localize('u3.mep.fireHyd.mHead', "Pump Head"), value: num(hyd.pumpHead) !== undefined ? `${num(hyd.pumpHead)!.toFixed(1)} m` : '–' },
				{ label: localize('u3.mep.fireHyd.mVel', "Max Velocity"), value: num(hyd.maxVelocity) !== undefined ? `${num(hyd.maxVelocity)!.toFixed(2)} m/s` : '–' },
			],
			tables: [
				{
					id: 'pumps',
					title: localize('u3.mep.fireHyd.pumpsTab', "Fire Pump Sets"),
					columns: [
						{ key: 'duty', title: localize('u3.mep.fireHyd.colPDuty', "Duty") },
						{ key: 'label', title: localize('u3.mep.fireHyd.colPLabel', "Description") },
						{ key: 'flow', title: localize('u3.mep.fireHyd.colPFlow', "Flow [L/min]"), type: 'number', align: 'right' },
						{ key: 'head', title: localize('u3.mep.fireHyd.colPHead', "Head [m]"), type: 'number', align: 'right' },
						{ key: 'power', title: localize('u3.mep.fireHyd.colPPow', "Power [kW]"), type: 'number', align: 'right' },
						{ key: 'count', title: localize('u3.mep.fireHyd.colPCount', "Sets"), type: 'number', align: 'right' },
						{ key: 'operatingWeight', title: localize('u3.mep.fireHyd.colPWeight', "Weight [kN]"), type: 'number', align: 'right' },
					],
					rows: pumpRows,
				},
				{
					id: 'supports',
					title: localize('u3.mep.fireHyd.suppTab', "Pipe Hanger & Support Loads"),
					columns: [
						{ key: 'size', title: localize('u3.mep.fireHyd.colSSize', "Pipe [mm]"), type: 'number', align: 'right' },
						{ key: 'kind', title: localize('u3.mep.fireHyd.colSKind', "Kind") },
						{ key: 'spacing', title: localize('u3.mep.fireHyd.colSSpace', "Spacing [m]"), type: 'number', align: 'right' },
						{ key: 'load', title: localize('u3.mep.fireHyd.colSLoad', "Load [kN]"), type: 'number', align: 'right' },
						{ key: 'basis', title: localize('u3.mep.fireHyd.colSBasis', "Basis") },
					],
					rows: supportRows,
				},
				{
					id: 'tests',
					title: localize('u3.mep.fireHyd.testsTab', "Hydrostatic Test Pressures"),
					columns: [
						{ key: 'system', title: localize('u3.mep.fireHyd.colTSys', "System") },
						{ key: 'pressure', title: localize('u3.mep.fireHyd.colTPress', "Pressure [kPa]"), type: 'number', align: 'right' },
						{ key: 'note', title: localize('u3.mep.fireHyd.colTNote', "Note") },
					],
					rows: testRows,
				},
				{
					id: 'checks',
					title: localize('u3.mep.fireHyd.checksTab', "Fire Code Checks"),
					columns: [
						{ key: 'name', title: localize('u3.mep.fireHyd.colCName', "Check") },
						{ key: 'demand', title: localize('u3.mep.fireHyd.colCDem', "Demand"), type: 'number', align: 'right' },
						{ key: 'capacity', title: localize('u3.mep.fireHyd.colCCap', "Capacity"), type: 'number', align: 'right' },
						{ key: 'unit', title: localize('u3.mep.fireHyd.colCUnit', "Unit") },
						{ key: 'status', title: localize('u3.mep.fireHyd.colCStatus', "Status"), type: 'status' },
						{ key: 'clause', title: localize('u3.mep.fireHyd.colCClause', "Clause") },
						{ key: 'note', title: localize('u3.mep.fireHyd.colCNote', "Note") },
					],
					rows: checkRows,
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerMepPanel({
	id: 'saengine.mep.fire.openingsCheck',
	title: localize('u3.mep.fireOpen.title', "Fire Sleeves & Penetrations Audit"),
	part: 'mep',
	icon: Codicon.circleLargeOutline,
	help: localize('u3.mep.fireOpen.help', "Lists slab and beam sleeves still missing for fire risers and main runs."),
	secondaryActions: openMepSectionAction('fire', localize('u3.mep.fireOpen.openSec', "Open MEP Fire")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/fireOpenings', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const openings = asArray(raw.openings).map(asBag);
		const rows: DataPanelRow[] = openings.map(o => ({
			id: str(o.id),
			host: str(o.host),
			kind: str(o.kind, 'sleeve'),
			shape: str(o.shape),
			size: formatOpeningSize(o),
			service: str(o.service, '–'),
		}));

		return {
			metrics: [
				{ label: localize('u3.mep.fireOpen.mMissing', "Missing Sleeves"), value: String(rows.length), tone: rows.length ? 'warn' : 'ok' },
			],
			tables: [{
				id: 'openings',
				title: localize('u3.mep.fireOpen.tab', "Missing Fire Sleeves"),
				columns: [
					{ key: 'id', title: localize('u3.mep.fireOpen.colId', "Sleeve") },
					{ key: 'host', title: localize('u3.mep.fireOpen.colHost', "Host") },
					{ key: 'kind', title: localize('u3.mep.fireOpen.colKind', "Kind") },
					{ key: 'shape', title: localize('u3.mep.fireOpen.colShape', "Shape") },
					{ key: 'size', title: localize('u3.mep.fireOpen.colSize', "Size") },
					{ key: 'service', title: localize('u3.mep.fireOpen.colService', "Service") },
				],
				rows,
				emptyMessage: localize('u3.mep.fireOpen.none', "All fire risers and mains already have sleeves or shafts."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Systems Panel (1)

registerMepPanel({
	id: 'saengine.mep.systems.summary',
	title: localize('u3.mep.sys.title', "MEP Systems & Connectivity Summary"),
	part: 'mep',
	icon: Codicon.typeHierarchy,
	help: localize('u3.mep.sys.help', "Summarizes logical MEP systems derived from connectors, critical path lengths, flow/load totals, and connectivity warnings."),
	secondaryActions: openMepSectionAction('systems', localize('u3.mep.sys.openSec', "Open System Browser")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('mep/systems', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const summary = asBag(raw.summary);
		const systems = asArray(raw.systems).map(asBag);
		const issues = asArray(raw.issues).map(asBag);

		const systemRows: DataPanelRow[] = systems.map(s => ({
			id: str(s.id),
			name: str(s.name),
			classification: str(s.classificationLabel || s.classification),
			domain: str(s.domain),
			elementCount: num(s.elementCount) ?? 0,
			airFlowLps: num(s.airFlowLps) ?? '–',
			waterFlowLps: num(s.waterFlowLps) ?? '–',
			fixtureUnits: num(s.fixtureUnits) ?? '–',
			electricalLoadKw: num(s.electricalLoadKw) ?? '–',
			criticalPathLength: num(s.criticalPathLength) ?? 0,
			warnings: num(s.warnings) ?? 0,
		}));

		const issueRows: DataPanelRow[] = issues.map(i => ({
			id: str(i.id),
			severity: i.severity === 'error' ? 'Fail' : 'Warn',
			kind: str(i.kind),
			story: str(i.story, '–'),
			elements: asStrings(i.elements).join(', ') || '–',
			message: str(i.message),
		}));

		const warnCount = num(summary.issues) ?? issueRows.length;
		return {
			metrics: [
				{ label: localize('u3.mep.sys.mSystems', "Systems"), value: String(num(summary.systems) ?? systemRows.length) },
				{ label: localize('u3.mep.sys.mElements', "Elements"), value: String(num(summary.elements) ?? 0) },
				{ label: localize('u3.mep.sys.mConns', "Connections"), value: String(num(summary.connections) ?? 0) },
				{ label: localize('u3.mep.sys.mWarnings', "Warnings"), value: String(warnCount), tone: warnCount ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'systems',
					title: localize('u3.mep.sys.systemsTab', "Derived MEP Systems"),
					columns: [
						{ key: 'id', title: localize('u3.mep.sys.colId', "System") },
						{ key: 'name', title: localize('u3.mep.sys.colName', "Name") },
						{ key: 'classification', title: localize('u3.mep.sys.colClass', "Classification") },
						{ key: 'domain', title: localize('u3.mep.sys.colDomain', "Domain") },
						{ key: 'elementCount', title: localize('u3.mep.sys.colElems', "Elements"), type: 'number', align: 'right' },
						{ key: 'airFlowLps', title: localize('u3.mep.sys.colAir', "Air [L/s]"), type: 'number', align: 'right' },
						{ key: 'waterFlowLps', title: localize('u3.mep.sys.colWater', "Water [L/s]"), type: 'number', align: 'right' },
						{ key: 'fixtureUnits', title: localize('u3.mep.sys.colFu', "FU"), type: 'number', align: 'right' },
						{ key: 'electricalLoadKw', title: localize('u3.mep.sys.colKw', "Power [kW]"), type: 'number', align: 'right' },
						{ key: 'criticalPathLength', title: localize('u3.mep.sys.colCrit', "Critical Path [m]"), type: 'number', align: 'right' },
						{ key: 'warnings', title: localize('u3.mep.sys.colWarn', "Warnings"), type: 'number', align: 'right' },
					],
					rows: systemRows,
				},
				{
					id: 'issues',
					title: localize('u3.mep.sys.issuesTab', "Connectivity Warnings"),
					columns: [
						{ key: 'id', title: localize('u3.mep.sys.colIId', "Issue") },
						{ key: 'severity', title: localize('u3.mep.sys.colISev', "Severity"), type: 'status' },
						{ key: 'kind', title: localize('u3.mep.sys.colIKind', "Kind") },
						{ key: 'story', title: localize('u3.mep.sys.colIStory', "Story") },
						{ key: 'elements', title: localize('u3.mep.sys.colIElems', "Elements") },
						{ key: 'message', title: localize('u3.mep.sys.colIMsg', "Message") },
					],
					rows: issueRows,
					emptyMessage: localize('u3.mep.sys.noIssues', "No connector or system warnings found."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion
