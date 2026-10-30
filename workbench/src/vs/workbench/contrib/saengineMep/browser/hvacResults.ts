/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { ductSystemLabel, hvacFailures, IHvacItemResult, IHvacReport, IOpeningResult, IShaftResult, plantKindLabel } from './hvacDocument.js';
import { barChart, checksTable, IResultsHost, noteSection, resultSection, statusCell, tiles, utilisationCell, value } from './mepResults.js';

/*
 * The Results view of the HVAC: the backend's report (`saengine.hvac.report`) as one page: the
 * engine line (EnergyPlus or an estimate), tiles, the cooling load per story (sensible, latent,
 * total and W/m², with a bar chart), the airflow and the ducts, the plant, the openings the
 * ducts need with their checks, and the shafts. Plain DOM; the editor wires the rows.
 */

const KW = localize('hvacResults.unit.kw', "kW");
const M2 = localize('hvacResults.unit.m2', "m²");
const M3S = localize('hvacResults.unit.m3s', "m³/s");
const WM2 = localize('hvacResults.unit.wm2', "W/m²");
const KN = localize('hvacResults.unit.kn', "kN");

/** One ton of refrigeration [kW] (12 000 BTU/h, the backend's KW_PER_TON), when the report gives no tons. */
const TR = 3.51685;

/** The rooms of each story grouped by their Table 8.2.3 use, as they feed the story's zone. */
function roomZones(view: HTMLElement, report: IHvacReport, host: IResultsHost): void {
	const rows = report.stories.filter(s => s.gainsFrom === 'rooms' && s.rooms?.length);
	if (!rows.length) {
		return;
	}
	const section = resultSection(view, localize('hvacResults.roomZones', "Zones from the rooms"), localize('hvacResults.roomZonesDetail', "the rooms of 6 BIM › Architecture by use (Table 8.2.3); EnergyPlus models one thermal zone per story with their gains added up"));
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('hvacResults.f.story', "Story"), width: 130 }, { label: localize('hvacResults.f.use', "Use"), width: 240 },
		{ label: localize('hvacResults.f.rooms', "Rooms"), numeric: true, width: 64 }, { label: localize('hvacResults.f.area', "Area"), unit: M2, numeric: true, width: 80 },
		{ label: localize('hvacResults.f.persons', "Persons"), numeric: true, width: 80 }, { label: localize('hvacResults.f.freshAir', "Outdoor air"), unit: M3S, numeric: true, width: 84 },
	]);
	const body = append(table, $('tbody'));
	for (const row of rows) {
		for (const group of row.rooms ?? []) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, host.storyName(row.story)));
			append(tr, $('td', undefined, group.label));
			append(tr, $('td.number', undefined, String(group.rooms.length)));
			append(tr, $('td.number', undefined, formatNumber(group.area, 1)));
			append(tr, $('td.number', undefined, formatNumber(group.occupants, 1)));
			append(tr, $('td.number', undefined, formatNumber(group.outdoorAir, 3)));
		}
	}
}

/**
 * Renders the report into `view`. `addEnergyPlus`: *Add Component...* of the setup's Energy
 * simulation component, offered while EnergyPlus is not installed (desktop only).
 */
export function renderHvacReport(view: HTMLElement, report: IHvacReport, host: IResultsHost & { readonly addEnergyPlus?: () => void }): void {
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('hvacResults.title', "HVAC coordination")));
	append(header, $('span.mep-view-subtitle', undefined, localize('hvacResults.subtitle', "Computed by the backend to BNBC 2020 Part 8 Chapter 2 from the HVAC set-up; not stored in the file.")));
	const engine = append(view, $(`.hvac-engine${report.estimate ? '.estimate' : ''}`));
	append(engine, $('span.hvac-engine-label', undefined, localize('hvacResults.engine', "Cooling loads")));
	append(engine, $('span.hvac-engine-value', undefined, report.estimate
		? report.energyPlusFound === false
			? localize('hvacResults.estimateNoEnergyPlus', "SAEngine's estimate: EnergyPlus is not installed (the setup's Energy simulation component gives the design-day loads)")
			: localize('hvacResults.estimate', "estimate (Calculate Loads runs EnergyPlus for the design day)")
		: report.computed ? localize('hvacResults.engineAt', "{0}, {1}", report.engine, report.computed) : report.engine));
	const addEnergyPlus = host.addEnergyPlus;
	if (report.estimate && report.energyPlusFound === false && addEnergyPlus) {
		const add = append(engine, $<HTMLButtonElement>('button.mep-link', { type: 'button', title: localize('hvacResults.addEnergyPlusTitle', "Add EnergyPlus by running the SAEngine setup again with Energy simulation ticked") }, localize('hvacResults.addEnergyPlus', "Add Component...")));
		add.addEventListener('click', () => addEnergyPlus());
	}

	const tile = tiles(view);
	if (report.total?.total !== undefined) {
		tile(localize('hvacResults.kwValue', "{0} kW", formatNumber(report.total.total, 0)), localize('hvacResults.tileLoad', "cooling load ({0} TR)", formatNumber(report.tons ?? report.total.total / TR, 1)));
	}
	if (report.coincident !== undefined) {
		tile(localize('hvacResults.kwValue', "{0} kW", formatNumber(report.coincident, 0)), report.peak
			? localize('hvacResults.tileCoincidentAt', "all stories together, {0} (central plant)", report.peak)
			: localize('hvacResults.tileCoincident', "all stories together (central plant)"));
	}
	if (report.total?.total !== undefined && report.total.area) {
		tile(localize('hvacResults.wm2Value', "{0} W/m²", formatNumber(report.total.total * 1000 / report.total.area, 0)), localize('hvacResults.tileDensity', "over {0} m² conditioned", formatNumber(report.total.area, 0)));
	}
	if (report.total?.supply !== undefined) {
		tile(localize('hvacResults.m3sValue', "{0} m³/s", formatNumber(report.total.supply, 2)), localize('hvacResults.tileSupply', "supply air"));
	}
	const failed = hvacFailures(report);
	tile(String(failed), localize('hvacResults.tileFails', "checks fail"), failed ? 'fail' : 'ok');
	if (report.summary.length) {
		const summary = append(view, $('ul.plb-summary'));
		for (const line of report.summary) {
			append(summary, $('li', undefined, line));
		}
	}
	if (report.problems.length) {
		noteSection(view, localize('hvacResults.problems', "Problems"), report.problems, 'p.mep-note.plb-problem');
	}

	// Loads per story.
	if (report.stories.length) {
		const section = resultSection(view, localize('hvacResults.loads', "Cooling load by story"), report.coincident !== undefined
			? localize('hvacResults.loadsDetailPeak', "each story at its own peak, the total their sum; outdoor design conditions BNBC Table 8.2.2 (2 %), ventilation Table 8.2.3")
			: localize('hvacResults.loadsDetail', "outdoor design conditions BNBC Table 8.2.2 (2 %), ventilation Table 8.2.3"));
		barChart(append(section, $('.hvac-load-chart')), report.stories.map(row => ({
			label: host.storyName(row.story),
			parts: [
				{ value: row.sensible ?? (row.latent === undefined ? row.total ?? 0 : 0), className: 'hvac-bar-sensible', label: localize('hvacResults.sensible', "Sensible") },
				{ value: row.latent ?? 0, className: 'hvac-bar-latent', label: localize('hvacResults.latent', "Latent") },
			],
			text: row.total !== undefined ? `${formatNumber(row.total, 1)} kW${row.density !== undefined ? ` · ${formatNumber(row.density, 0)} W/m²` : ''}` : '',
		})), localize('hvacResults.chartAria', "Cooling load per story"));
		const table = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(table, [
			{ label: localize('hvacResults.f.story', "Story"), width: 130 }, { label: localize('hvacResults.f.area', "Area"), unit: M2, numeric: true, width: 80 },
			{ label: localize('hvacResults.sensible', "Sensible"), unit: KW, numeric: true, width: 84 }, { label: localize('hvacResults.latent', "Latent"), unit: KW, numeric: true, width: 84 },
			{ label: localize('hvacResults.f.total', "Total"), unit: KW, numeric: true, width: 84 }, { label: localize('hvacResults.f.density', "Load"), unit: WM2, numeric: true, width: 72 },
			{ label: localize('hvacResults.f.supply', "Supply air"), unit: M3S, numeric: true, width: 84 }, { label: localize('hvacResults.f.freshAir', "Outdoor air"), unit: M3S, numeric: true, width: 84 },
			{ label: localize('hvacResults.f.note', "Note"), width: 240 },
		]);
		const body = append(table, $('tbody'));
		for (const row of report.stories) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, host.storyName(row.story)));
			for (const [n, digits] of [[row.area, 0], [row.sensible, 1], [row.latent, 1], [row.total, 1], [row.density, 0], [row.supply, 2], [row.freshAir, 3]] as const) {
				append(tr, $('td.number', undefined, value(n, digits)));
			}
			const from = row.gainsFrom === 'rooms'
				? localize('hvacResults.fromRooms', "gains from {0} room group(s) of the architecture", row.rooms?.length ?? 0)
				: row.gainsFrom === 'typed' ? localize('hvacResults.fromTyped', "gains from the use typed in the set-up") : '';
			append(tr, $('td.mep-wrap', undefined, [from, row.note ?? ''].filter(Boolean).join(' · ')));
		}
		const total = report.total;
		if (total) {
			const tr = append(body, $('tr.plb-total'));
			append(tr, $('td', undefined, localize('hvacResults.total', "Total")));
			for (const [n, digits] of [[total.area, 0], [total.sensible, 1], [total.latent, 1], [total.total, 1]] as const) {
				append(tr, $('td.number', undefined, value(n, digits)));
			}
			append(tr, $('td.number', undefined, total.total !== undefined && total.area ? formatNumber(total.total * 1000 / total.area, 0) : ''));
			append(tr, $('td.number', undefined, value(total.supply, 2)));
			append(tr, $('td.number', undefined, value(total.freshAir, 3)));
			append(tr, $('td'));
		}
	}

	roomZones(view, report, host);
	itemTable(view, host, localize('hvacResults.ducts', "Airflow and ducts"), localize('hvacResults.ductsDetail', "the flow each duct carries, its size and velocity"), report.ducts, 'duct');
	itemTable(view, host, localize('hvacResults.plant', "Plant"), localize('hvacResults.plantDetail', "capacity against the load it serves; the operating weight is a load on the structure"), report.plant, 'plant');
	openingsTable(view, host, localize('hvacResults.openings', "Duct openings"), localize('hvacResults.openingsDetail', "through beams (web openings), slabs and walls: the governing check of each"), report.openings);
	shaftsTable(view, host, report.shafts);
	if (report.checks.length) {
		checksTable(resultSection(view, localize('hvacResults.checks', "Checks")), host, report.checks, 8);
	}
	noteSection(view, localize('hvacResults.notes', "Notes"), report.notes);
	noteSection(view, localize('hvacResults.method', "Method"), report.method);
}

function itemTable(view: HTMLElement, host: IResultsHost, title: string, detail: string, items: readonly IHvacItemResult[], kind: 'duct' | 'plant'): void {
	if (!items.length) {
		return;
	}
	const section = resultSection(view, title, detail);
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, kind === 'duct' ? [
		{ label: localize('hvacResults.f.id', "ID"), width: 64 }, { label: localize('hvacResults.f.system', "System"), width: 130 }, { label: localize('hvacResults.f.flow', "Flow"), unit: M3S, numeric: true, width: 72 },
		{ label: localize('hvacResults.f.size', "Size"), unit: localize('hvacResults.unit.mm', "mm"), numeric: true, width: 96 }, { label: localize('hvacResults.f.velocity', "Velocity"), unit: localize('hvacResults.unit.ms', "m/s"), numeric: true, width: 72 },
		{ label: localize('hvacResults.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('hvacResults.f.note', "Note"), width: 260 },
	] : [
		{ label: localize('hvacResults.f.id', "ID"), width: 64 }, { label: localize('hvacResults.f.kind', "Kind"), width: 140 }, { label: localize('hvacResults.f.required', "Required"), numeric: true, width: 84 },
		{ label: localize('hvacResults.f.provided', "Provided"), numeric: true, width: 84 }, { label: localize('hvacResults.f.weight', "Weight"), unit: KN, numeric: true, width: 72 },
		{ label: localize('hvacResults.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('hvacResults.f.note', "Note"), width: 260 },
	]);
	const body = append(table, $('tbody'));
	for (const item of items) {
		const tr = host.row(body, item.id);
		append(tr, $('td', undefined, item.id));
		if (kind === 'duct') {
			append(tr, $('td', undefined, item.system ? ductSystemLabel(item.system) : ''));
			append(tr, $('td.number', undefined, value(item.load, 2)));
			append(tr, $('td.number', undefined, item.size ?? ''));
			append(tr, $('td.number', undefined, value(item.velocity, 1)));
		} else {
			append(tr, $('td', undefined, item.kind ? plantKindLabel(item.kind) : ''));
			append(tr, $('td.number', undefined, item.required === undefined ? '' : `${formatNumber(item.required, 1)}${item.unit ? ` ${item.unit}` : ''}`));
			append(tr, $('td.number', undefined, item.provided === undefined ? '' : `${formatNumber(item.provided, 1)}${item.unit ? ` ${item.unit}` : ''}`));
			append(tr, $('td.number', undefined, value(item.weight, 1)));
		}
		utilisationCell(tr, item.utilisation, item.status);
		append(tr, $('td.mep-wrap', undefined, item.note ?? ''));
		if (item.status === 'fail') {
			tr.classList.add('failed');
		}
	}
}

/** The openings the services need with their checks (shared with the electrical Results). */
export function openingsTable(view: HTMLElement, host: IResultsHost, title: string, detail: string, openings: readonly IOpeningResult[]): void {
	if (!openings.length) {
		return;
	}
	const section = resultSection(view, title, detail);
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('hvacResults.f.id', "ID"), width: 64 }, { label: localize('hvacResults.f.host', "Host"), width: 80 }, { label: localize('hvacResults.f.service', "Service"), width: 90 },
		{ label: localize('hvacResults.f.size', "Size"), unit: localize('hvacResults.unit.mm', "mm"), numeric: true, width: 96 }, { label: localize('hvacResults.f.check', "Check"), width: 200 },
		{ label: localize('hvacResults.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('hvacResults.f.note', "Note"), width: 260 },
	]);
	const body = append(table, $('tbody'));
	for (const o of openings) {
		const tr = host.row(body, o.id);
		append(tr, $('td', undefined, o.id));
		append(tr, $('td', undefined, o.host ?? ''));
		append(tr, $('td', undefined, o.duct ?? ''));
		append(tr, $('td.number', undefined, o.size ?? ''));
		append(tr, $('td', undefined, o.check ?? ''));
		utilisationCell(tr, o.utilisation, o.status);
		append(tr, $('td.mep-wrap', undefined, [o.proposed ? localize('hvacResults.proposed', "proposed; not in the file yet") : '', o.note ?? ''].filter(Boolean).join(' · ')));
		if (o.status === 'fail') {
			tr.classList.add('failed');
		}
	}
}

/** The shafts' areas against what the services in them need (shared with the electrical Results). */
export function shaftsTable(view: HTMLElement, host: IResultsHost, shafts: readonly IShaftResult[]): void {
	if (!shafts.length) {
		return;
	}
	const section = resultSection(view, localize('hvacResults.shafts', "Shafts"), localize('hvacResults.shaftsDetail', "the area the services in each need, with the clearances"));
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('hvacResults.f.shaft', "Shaft"), width: 80 }, { label: localize('hvacResults.f.required', "Required"), unit: M2, numeric: true, width: 84 },
		{ label: localize('hvacResults.f.provided', "Provided"), unit: M2, numeric: true, width: 84 }, { label: localize('hvacResults.f.status', "Status"), width: 80 }, { label: localize('hvacResults.f.note', "Note"), width: 300 },
	]);
	const body = append(table, $('tbody'));
	for (const s of shafts) {
		const tr = host.row(body, s.id);
		append(tr, $('td', undefined, s.id));
		append(tr, $('td.number', undefined, value(s.required, 2)));
		append(tr, $('td.number', undefined, value(s.provided, 2)));
		statusCell(tr, s.status);
		append(tr, $('td.mep-wrap', undefined, s.note ?? ''));
	}
}
