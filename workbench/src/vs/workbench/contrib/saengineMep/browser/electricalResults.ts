/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { elecKindLabel, electricalFailures, IElectricalReport, IRunResult, loadBreakdownText, riserKindLabel } from './electricalDocument.js';
import { openingsTable, shaftsTable } from './hvacResults.js';
import { barChart, checksTable, IResultsHost, noteSection, resultSection, statusCell, tiles, utilisationCell, value } from './mepResults.js';

/*
 * The Results view of the electrical services: the backend's report
 * (`saengine.electrical.report`) as one page: tiles, the demand per story and in all, the
 * transformer, generator and UPS against it, the rooms they need, the risers and trays, the
 * lightning protection (with the down-conductor columns for the structural drawings) and the
 * openings with their checks. Plain DOM; the editor wires the rows.
 */

const KW = localize('elecResults.unit.kw', "kW");
const KVA = localize('elecResults.unit.kva', "kVA");
const M2 = localize('elecResults.unit.m2', "m²");
const WM2 = localize('elecResults.unit.wm2', "W/m²");

export interface IElectricalResultsHost extends IResultsHost {
	/** Shows the column in the plan of the lowest story. */
	showColumn?(id: string): void;
}

export function renderElectricalReport(view: HTMLElement, report: IElectricalReport, host: IElectricalResultsHost): void {
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('elecResults.title', "Electrical coordination")));
	append(header, $('span.mep-view-subtitle', undefined, localize('elecResults.subtitle', "Computed by the backend to BNBC 2020 Part 8 Chapter 1 from the electrical set-up; not stored in the file.")));

	const tile = tiles(view);
	if (report.total?.kva !== undefined) {
		tile(localize('elecResults.kvaValue', "{0} kVA", formatNumber(report.total.kva, 0)), localize('elecResults.tileDemand', "maximum demand"));
	}
	if (report.total?.connected !== undefined) {
		tile(localize('elecResults.kwValue', "{0} kW", formatNumber(report.total.connected, 0)), localize('elecResults.tileConnected', "connected load"));
	}
	if (report.lightning) {
		tile(String(report.lightning.downConductors.length), localize('elecResults.tileDown', "down-conductor columns"));
	}
	const failed = electricalFailures(report);
	tile(String(failed), localize('elecResults.tileFails', "checks fail"), failed ? 'fail' : 'ok');
	if (report.summary.length) {
		const summary = append(view, $('ul.plb-summary'));
		for (const line of report.summary) {
			append(summary, $('li', undefined, line));
		}
	}
	if (report.problems.length) {
		noteSection(view, localize('elecResults.problems', "Problems"), report.problems, 'p.mep-note.plb-problem');
	}

	// Demand.
	if (report.stories.length) {
		const section = resultSection(view, localize('elecResults.demand', "Demand by story"), report.demandMethod ?? localize('elecResults.demandDetail', "unit loads BNBC Table 8.1.17 over the floor area"));
		barChart(append(section, $('.elec-demand-chart')), report.stories.map(row => ({
			label: host.storyName(row.story),
			parts: [{ value: row.kva ?? row.demand ?? row.connected ?? 0, className: 'elec-bar-demand', label: localize('elecResults.demandPart', "Demand") }],
			text: row.kva !== undefined ? `${formatNumber(row.kva, 0)} kVA` : row.demand !== undefined ? `${formatNumber(row.demand, 0)} kW` : '',
		})), localize('elecResults.chartAria', "Demand per story"));
		// Each story's unit load, part by part (lighting, power and socket outlets, the A/C share), with where each comes from.
		const table = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(table, [
			{ label: localize('elecResults.f.story', "Story"), width: 110 }, { label: localize('elecResults.f.use', "Occupancy"), width: 170 },
			{ label: localize('elecResults.f.area', "Area"), unit: M2, numeric: true, width: 70 },
			{ label: localize('elecResults.f.lighting', "Lighting"), unit: WM2, numeric: true, width: 72 }, { label: localize('elecResults.f.power', "Power"), unit: WM2, numeric: true, width: 72, title: localize('elecResults.f.powerTitle', "Power and socket outlets") },
			{ label: localize('elecResults.f.ac', "A/C"), unit: WM2, numeric: true, width: 60, title: localize('elecResults.f.acTitle', "The air-conditioning share of Table 8.1.17 (A/C less non-A/C density); 0 where the hvac plant's own load is counted") },
			{ label: localize('elecResults.f.unit', "Unit load"), unit: WM2, numeric: true, width: 76 },
			{ label: localize('elecResults.f.connected', "Connected"), unit: KW, numeric: true, width: 84 }, { label: localize('elecResults.f.demand', "Demand"), unit: KW, numeric: true, width: 76 },
			{ label: localize('elecResults.f.kva', "Demand"), unit: KVA, numeric: true, width: 76 },
		]);
		const body = append(table, $('tbody'));
		for (const row of report.stories) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, host.storyName(row.story)));
			const use = append(tr, $('td.mep-wrap', undefined, row.useLabel ?? row.use ?? ''));
			if (row.useSource && row.useSource !== 'entered') {
				append(use, $('span.mep-muted', undefined, ` (${localize('elecResults.useDefault', "building use")})`));
				use.title = row.useSource;
			}
			// Lighting and power blank together: Table 8.1.17 gives them as one figure, shown across both columns.
			const together = row.lighting === undefined && row.power === undefined ? row.breakdown.find(p => p.part === 'lightingAndPower')?.density : undefined;
			append(tr, $('td.number', undefined, value(row.area, 0)));
			if (together !== undefined) {
				append(tr, $('td.number', { colspan: '2' }, localize('elecResults.together', "{0} together", formatNumber(together, 1))));
			} else {
				append(tr, $('td.number', undefined, value(row.lighting, 1)), $('td.number', undefined, value(row.power, 1)));
			}
			for (const [n, digits] of [[row.acShare, 1], [row.density, 1], [row.connected, 1], [row.demand, 1], [row.kva, 1]] as const) {
				append(tr, $('td.number', undefined, value(n, digits)));
			}
			tr.title = loadBreakdownText(row);
		}
		// The loads the stories' unit loads leave out: the air-conditioning plant, the motors, the extra loads.
		const others: [number | undefined, string][] = [
			[report.total?.hvac, localize('elecResults.hvacLoad', "Air-conditioning plant")],
			[report.total?.motors, localize('elecResults.motorLoad', "Motors (lifts, pumps)")],
			[report.total?.extra, localize('elecResults.extraLoad', "Other loads")],
		];
		for (const [kw, label] of others) {
			if (kw) {
				const tr = append(body, $('tr'));
				append(tr, $('td', { colspan: '7' }, label));
				append(tr, $('td.number', undefined, value(kw, 1)));
				append(tr, $('td'), $('td'));
			}
		}
		if (report.total) {
			const tr = append(body, $('tr.plb-total'));
			append(tr, $('td', { colspan: '7' }, localize('elecResults.total', "Total")));
			for (const [n, digits] of [[report.total.connected, 1], [report.total.demand, 1], [report.total.kva, 1]] as const) {
				append(tr, $('td.number', undefined, value(n, digits)));
			}
		}
		// Where each storey's unit load comes from, part by part.
		const sources = append(section, $('ul.plb-summary.elec-load-sources'));
		for (const row of report.stories) {
			if (row.breakdown.length || row.note) {
				const li = append(sources, $('li'));
				append(li, $('strong', undefined, `${host.storyName(row.story)}: `));
				append(li, $('span', undefined, [loadBreakdownText(row).split('\n').join('; '), row.note ?? ''].filter(Boolean).join('; ')));
			}
		}
	}

	// Sources: transformer, generator, UPS.
	if (report.sources.length) {
		const section = resultSection(view, localize('elecResults.sources', "Transformer, generator and UPS"), localize('elecResults.sourcesDetail', "the rating each needs against the one given"));
		const table = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(table, [
			{ label: localize('elecResults.f.source', "Source"), width: 150 }, { label: localize('elecResults.f.id', "ID"), width: 64 },
			{ label: localize('elecResults.f.required', "Required"), numeric: true, width: 90 }, { label: localize('elecResults.f.provided', "Provided"), numeric: true, width: 90 },
			{ label: localize('elecResults.f.status', "Status"), width: 80 }, { label: localize('elecResults.f.note', "Note"), width: 300 },
		]);
		const body = append(table, $('tbody'));
		for (const s of report.sources) {
			const tr = s.id ? host.row(body, s.id) : append(body, $('tr'));
			append(tr, $('td', undefined, elecKindLabel(s.kind)));
			append(tr, $('td', undefined, s.id ?? ''));
			const unit = s.unit ?? KVA;
			append(tr, $('td.number', undefined, s.required === undefined ? '' : `${formatNumber(s.required, 0)} ${unit}`));
			append(tr, $('td.number', undefined, s.provided === undefined ? '' : `${formatNumber(s.provided, 0)} ${unit}`));
			statusCell(tr, s.status);
			append(tr, $('td.mep-wrap', undefined, s.note ?? ''));
		}
	}

	// Rooms.
	if (report.rooms.length) {
		checksTable(resultSection(view, localize('elecResults.rooms', "Rooms"), localize('elecResults.roomsDetail', "substation and generator rooms: area, clear height and placement, BNBC Part 8 Chapter 1")), host, report.rooms, 8);
	}

	runTable(view, host, localize('elecResults.risers', "Risers"), report.risers, true);
	runTable(view, host, localize('elecResults.trays', "Cable trays"), report.trays, false);

	// Lightning protection.
	const lightning = report.lightning;
	if (lightning) {
		const detail = [lightning.reference, lightning.level ? localize('elecResults.level', "level {0}", lightning.level) : undefined, lightning.risk !== undefined ? localize('elecResults.risk', "risk index {0}", lightning.risk) : undefined]
			.filter(Boolean).join(' · ') || localize('elecResults.lightningDetail', "BNBC Part 8 Chapter 1, lightning protection");
		const section = resultSection(view, localize('elecResults.lightning', "Lightning protection"), detail);
		const decision = lightning.decision === 'required' ? localize('elecResults.decisionRequired', "Protection is required for this building.")
			: lightning.decision === 'recommended' ? localize('elecResults.decisionRecommended', "The risk index is at or above the marginal value: protection is needed.")
				: lightning.decision === 'notRequired' ? localize('elecResults.decisionNotRequired', "The risk index does not require protection; it is designed as set up.")
					: lightning.required === undefined ? undefined
						: lightning.required ? localize('elecResults.required', "Protection is required for this building.")
							: localize('elecResults.notRequired', "The risk index does not require protection; it is designed as set up.");
		if (decision) {
			append(section, $('p.mep-note', undefined, decision));
		}
		if (lightning.riskNote) {
			append(section, $('p.mep-note', undefined, lightning.riskNote));
		}
		if (lightning.downConductors.length) {
			append(section, $('.mep-subheading', undefined, lightning.downConductorsNeeded !== undefined
				? localize('elecResults.downConductorsOf', "Down-conductor columns (for the structural drawings): {0} placed, {1} needed", lightning.downConductors.length, lightning.downConductorsNeeded)
				: localize('elecResults.downConductors', "Down-conductor columns (for the structural drawings)")));
			append(section, $('p.elec-dc-list', undefined, lightning.downConductors.map(d => d.column).join(', ')));
			const table = append(section, $('table.mep-table.mep-result-table'));
			host.tableHead(table, [
				{ label: localize('elecResults.f.dc', "Down conductor"), width: 90 }, { label: localize('elecResults.f.column', "Column"), width: 110 },
				{ label: 'X', unit: localize('elecResults.unit.m', "m"), numeric: true, width: 72 }, { label: 'Y', unit: localize('elecResults.unit.m', "m"), numeric: true, width: 72 },
				{ label: localize('elecResults.f.columns', "Column line"), width: 220 }, { label: localize('elecResults.f.note', "Note"), width: 300 },
			]);
			const body = append(table, $('tbody'));
			for (const d of lightning.downConductors) {
				const tr = host.row(body, d.column);
				append(tr, $('td', undefined, d.id ?? ''));
				append(tr, $('td', undefined, d.column));
				append(tr, $('td.number', undefined, d.x === undefined ? '' : formatNumber(d.x / 1000, 3)));
				append(tr, $('td.number', undefined, d.y === undefined ? '' : formatNumber(d.y / 1000, 3)));
				append(tr, $('td.mep-wrap', undefined, d.columns.join(', ')));
				append(tr, $('td.mep-wrap', undefined, d.note ?? localize('elecResults.dcNote', "its reinforcement serves as the down conductor; see the notes for the bonding and the test joint")));
			}
		}
		for (const line of lightning.structuralNotes) {
			append(section, $('p.mep-note.elec-structural-note', undefined, line));
		}
		if (lightning.airTerminals.length) {
			append(section, $('p.mep-note', undefined, lightning.airTerminalsProposed
				? localize('elecResults.terminalsProposed', "{0} air terminals proposed on the roof (shown in the roof's plan).", lightning.airTerminals.length)
				: localize('elecResults.terminals', "{0} air terminals on the roof (shown in the roof's plan).", lightning.airTerminals.length)));
		}
		if (lightning.mesh.length) {
			append(section, $('p.mep-note', undefined, localize('elecResults.mesh', "{0} roof conductor runs (shown in the roof's plan).", lightning.mesh.length)));
		}
		if (lightning.earthing) {
			append(section, $('p.mep-note', undefined, localize('elecResults.earthing', "Earthing: {0}", lightning.earthing)));
		}
		for (const line of lightning.notes) {
			append(section, $('p.mep-note', undefined, line));
		}
	}

	openingsTable(view, host, localize('elecResults.openings', "Openings for risers and trays"), localize('elecResults.openingsDetail', "through slabs, beams and walls: the governing check of each"), report.openings);
	shaftsTable(view, host, report.shafts);
	// The room checks are in the report's checks too: shown once, under Rooms.
	const roomChecks = new Set(report.rooms.map(r => r.name));
	const checks = report.checks.filter(c => !roomChecks.has(c.name));
	if (checks.length) {
		checksTable(resultSection(view, localize('elecResults.checks', "Checks")), host, checks, 8);
	}
	noteSection(view, localize('elecResults.notes', "Notes"), report.notes);
	noteSection(view, localize('elecResults.method', "Method"), report.method);
}

function runTable(view: HTMLElement, host: IResultsHost, title: string, runs: readonly IRunResult[], risers: boolean): void {
	if (!runs.length) {
		return;
	}
	const section = resultSection(view, title);
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('elecResults.f.id', "ID"), width: 64 }, { label: localize('elecResults.f.kind', "Kind"), width: 170 },
		{ label: localize('elecResults.f.current', "Current"), unit: localize('elecResults.unit.a', "A"), numeric: true, width: 72 }, { label: localize('elecResults.f.size', "Size"), numeric: true, width: 110 },
		{ label: localize('elecResults.f.fill', "Fill"), numeric: true, width: 120 }, { label: localize('elecResults.f.note', "Note"), width: 260 },
	]);
	const body = append(table, $('tbody'));
	for (const run of runs) {
		const tr = host.row(body, run.id);
		append(tr, $('td', undefined, run.id));
		append(tr, $('td', undefined, run.kind ? riserKindLabel(run.kind) : risers ? '' : localize('elecResults.tray', "Cable tray")));
		append(tr, $('td.number', undefined, value(run.current, 0)));
		append(tr, $('td.number', undefined, run.size ?? ''));
		utilisationCell(tr, run.fill, run.status);
		append(tr, $('td.mep-wrap', undefined, run.note ?? ''));
		if (run.status === 'fail') {
			tr.classList.add('failed');
		}
	}
}
