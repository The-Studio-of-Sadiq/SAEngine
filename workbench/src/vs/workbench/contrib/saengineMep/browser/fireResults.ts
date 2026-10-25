/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { fireFailures, fireStatusLabel, hazardLabel, IFireReport } from './fireDocument.js';
import { openingsTable } from './hvacResults.js';
import { IResultsHost, noteSection, resultSection, tiles, utilisationCell, value } from './mepResults.js';

/*
 * The Results view of the fire protection: the backend's report (`saengine.fire.report`) as one
 * page: tiles, what BNBC 2020 Part 4 requires and why (each system with the clauses that ask
 * for it), the floors, the fire water and the hydraulic calculation, the pump sets and their
 * room, the fire tanks, the hanger and support loads for the structure, the sleeves still
 * missing and the checks with their clauses. Plain DOM; the editor wires the rows.
 */

const LPM = localize('fireResults.unit.lpm', "l/min");
const M = localize('fireResults.unit.m', "m");
const M2 = localize('fireResults.unit.m2', "m²");
const M3 = localize('fireResults.unit.m3', "m³");
const KN = localize('fireResults.unit.kn', "kN");
const KW = localize('fireResults.unit.kw', "kW");

export function renderFireReport(view: HTMLElement, report: IFireReport, host: IResultsHost): void {
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('fireResults.title', "Fire protection")));
	append(header, $('span.mep-view-subtitle', undefined, localize('fireResults.subtitle', "Computed by the backend to BNBC 2020 Part 4 from the fire set-up; not stored in the file. NFPA values are from memory, to be checked.")));

	const tile = tiles(view);
	const required = report.systems.filter(s => s.status === 'required').length;
	tile(String(required), localize('fireResults.tileRequired', "systems required"));
	if (report.demand?.flow) {
		tile(localize('fireResults.lpmValue', "{0} l/min", formatNumber(report.demand.flow, 0)), localize('fireResults.tileFlow', "fire water"));
	}
	if (report.demand?.volume) {
		tile(localize('fireResults.m3Value', "{0} m³", formatNumber(report.demand.volume, 0)), localize('fireResults.tileReservoir', "reservoir"));
	}
	if (report.hydraulics?.pumpHead !== undefined) {
		tile(localize('fireResults.mValue', "{0} m", formatNumber(report.hydraulics.pumpHead, 1)), localize('fireResults.tileHead', "pump head"));
	}
	const failed = fireFailures(report);
	tile(String(failed), localize('fireResults.tileFails', "checks fail"), failed ? 'fail' : 'ok');
	if (report.summary.length) {
		const summary = append(view, $('ul.plb-summary'));
		for (const line of report.summary) {
			append(summary, $('li', undefined, line));
		}
	}
	if (report.problems.length) {
		noteSection(view, localize('fireResults.problems', "Problems"), report.problems, 'p.mep-note.plb-problem');
	}

	// What Part 4 requires, and why.
	const systems = resultSection(view, localize('fireResults.systems', "Systems required"), report.highRiseNote);
	if (report.firePlan.length) {
		append(systems, $('p.mep-note', undefined, localize('fireResults.firePlan', "A fire protection plan is required (Part 4 Sec 5.1.6): {0}.", report.firePlan.join('; '))));
	}
	const table = append(systems, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('fireResults.f.system', "System"), width: 220 }, { label: localize('fireResults.f.part4', "Part 4"), width: 130 },
		{ label: localize('fireResults.f.designed', "Designed"), width: 80 }, { label: localize('fireResults.f.why', "Why (clause)"), width: 460 },
	]);
	const body = append(table, $('tbody'));
	for (const s of report.systems) {
		const tr = append(body, $('tr'));
		append(tr, $('td', undefined, s.label));
		append(append(tr, $('td')), $(`span.fire-status.${s.status}`, undefined, fireStatusLabel(s.status)));
		append(tr, $('td', undefined, s.provided ? localize('fireResults.yes', "yes") : localize('fireResults.no', "no")));
		append(tr, $('td.mep-wrap', undefined, s.reasons.join(' · ')));
	}

	// Floors.
	if (report.stories.length) {
		const section = resultSection(view, localize('fireResults.floors', "Floors"), localize('fireResults.floorsDetail', "hazard of Table 4.4.1; heads a layout estimate (Table 4.4.7); devices per floor"));
		const t = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(t, [
			{ label: localize('fireResults.f.story', "Story"), width: 110 }, { label: localize('fireResults.f.group', "Group"), width: 60 }, { label: localize('fireResults.f.hazard', "Hazard"), width: 150 },
			{ label: localize('fireResults.f.area', "Area"), unit: M2, numeric: true, width: 72 }, { label: localize('fireResults.f.heads', "Heads"), numeric: true, width: 64 },
			{ label: localize('fireResults.f.extinguishers', "Extinguishers"), numeric: true, width: 96 }, { label: localize('fireResults.f.callPoints', "Call points"), numeric: true, width: 84 },
			{ label: localize('fireResults.f.detectors', "Detectors"), numeric: true, width: 80 },
		]);
		const b = append(t, $('tbody'));
		for (const r of report.stories) {
			const tr = append(b, $('tr'));
			append(tr, $('td', undefined, host.storyName(r.story)));
			append(tr, $('td', undefined, r.group ?? ''));
			append(tr, $('td', undefined, r.hazard ? hazardLabel(r.hazard) : ''));
			append(tr, $('td.number', undefined, value(r.area, 0)));
			append(tr, $('td.number', undefined, r.sprinklered ? value(r.heads, 0) : '–'));
			for (const n of [r.extinguishers, r.callPoints, r.detectors]) {
				append(tr, $('td.number', undefined, n ? String(n) : '–'));
			}
		}
	}

	// Water and the hydraulic calculation.
	const demand = report.demand;
	const hyd = report.hydraulics;
	if (demand || hyd) {
		const section = resultSection(view, localize('fireResults.water', "Fire water and hydraulics"), localize('fireResults.waterDetail', "Table 4.4.1, Sec 4.2.3.2 and 4.2.3.5; EPANET through WNTR"));
		const rows: [string, string][] = [];
		if (demand) {
			rows.push([localize('fireResults.standpipes', "Standpipes"), `${value(demand.standpipe, 0)} ${LPM}`]);
			rows.push([localize('fireResults.sprinklers', "Sprinklers"), `${value(demand.sprinkler, 0)} ${LPM}`]);
			rows.push([localize('fireResults.total', "Total for the duration"), localize('fireResults.totalValue', "{0} l/min for {1} min = {2} m³", value(demand.flow, 0), value(demand.duration, 0), value(demand.volume, 1))]);
		}
		if (report.storage) {
			rows.push([localize('fireResults.stored', "Stored"), `${value(report.storage.provided, 1)} ${M3}`]);
		}
		if (hyd) {
			rows.push([localize('fireResults.duty', "Pump duty"), localize('fireResults.dutyValue', "{0} l/min at {1} m ({2})", value(hyd.flow, 0), value(hyd.pumpHead, 1), hyd.governing ?? '')]);
			if (hyd.suction) {
				rows.push([localize('fireResults.suction', "Suction"), localize('fireResults.suctionValue', "water at {0} m, pump at {1} m", value(hyd.suction.waterLevel, 2), value(hyd.suction.pumpLevel, 2))]);
			}
			if (hyd.standpipe) {
				const least = Math.min(...hyd.standpipe.outlets.map(o => o.pressure ?? Infinity));
				rows.push([localize('fireResults.remote', "Most remote standpipe"), localize('fireResults.remoteValue', "{0}: {1} l/min, {2} kPa at the top outlet", hyd.standpipe.first ?? '', value(hyd.standpipe.flow, 0), Number.isFinite(least) ? formatNumber(least, 0) : '')]);
			}
			if (hyd.sprinkler) {
				const s = hyd.sprinkler;
				rows.push([localize('fireResults.designArea', "Sprinkler design area"), localize('fireResults.designAreaValue', "{0} heads on {1} over {2} m² at {3} mm/min: {4} l/min, least head {5} l/min at {6} kPa",
					value(s.heads, 0), s.story ? host.storyName(s.story) : '', value(s.designArea, 0), value(s.density, 1), value(s.sprinklerFlow, 0), value(s.least, 1), value(s.leastPressure, 0))]);
			}
			if (hyd.maxVelocity !== undefined) {
				rows.push([localize('fireResults.velocity', "Largest velocity"), `${value(hyd.maxVelocity, 2)} m/s`]);
			}
			if (hyd.prvStories.length) {
				rows.push([localize('fireResults.prv', "Pressure reducing valves"), hyd.prvStories.map(s => host.storyName(s)).join(', ')]);
			}
		}
		const t = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(t, [{ label: localize('fireResults.f.item', "Item"), width: 220 }, { label: localize('fireResults.f.value', "Value"), width: 520 }]);
		const b = append(t, $('tbody'));
		for (const [label, text] of rows) {
			const tr = append(b, $('tr'));
			append(tr, $('td', undefined, label));
			append(tr, $('td.mep-wrap', undefined, text));
		}
		if (demand?.hand) {
			append(section, $('p.mep-note', undefined, localize('fireResults.hand', "By hand: {0}", demand.hand)));
		}
	}

	// Pump sets and room.
	if (report.pumps.length) {
		const section = resultSection(view, localize('fireResults.pumps', "Pump sets"), localize('fireResults.pumpsDetail', "Table 4.4.2 rating, at least 272 kPa net (Sec 4.2.2.5); sizes and weights typical"));
		const t = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(t, [
			{ label: localize('fireResults.f.pump', "Pump"), width: 190 }, { label: localize('fireResults.f.flow', "Flow"), unit: LPM, numeric: true, width: 72 },
			{ label: localize('fireResults.f.head', "Head"), unit: M, numeric: true, width: 64 }, { label: localize('fireResults.f.power', "Motor"), unit: KW, numeric: true, width: 64 },
			{ label: localize('fireResults.f.size', "Size"), unit: localize('fireResults.unit.mm', "mm"), numeric: true, width: 110 }, { label: localize('fireResults.f.weight', "Weight"), unit: KN, numeric: true, width: 72 },
			{ label: localize('fireResults.f.entered', "In 7 MEP"), width: 110 },
		]);
		const b = append(t, $('tbody'));
		for (const p of report.pumps) {
			const tr = p.ids[0] ? host.row(b, p.ids[0]) : append(b, $('tr'));
			append(tr, $('td', undefined, p.count && p.count > 1 ? `${p.count} × ${p.label}` : p.label));
			append(tr, $('td.number', undefined, value(p.flow, 0)));
			append(tr, $('td.number', undefined, value(p.head, 1)));
			append(tr, $('td.number', undefined, value(p.power, 1)));
			append(tr, $('td.number', undefined, p.length && p.width ? `${formatNumber(p.length, 0)} × ${formatNumber(p.width, 0)}` : ''));
			append(tr, $('td.number', undefined, value(p.operatingWeight, 1)));
			append(tr, $('td', undefined, p.ids.join(', ') || localize('fireResults.notEntered', "propose")));
		}
		const room = report.pumpRoom;
		if (room?.area) {
			append(section, $('p.mep-note', undefined, room.provided !== undefined
				? localize('fireResults.roomProvided', "Pump room: {0} m² needed ({1} × {2} m), {3} m² drawn. {4}", formatNumber(room.area, 1), formatNumber((room.length ?? 0) / 1000, 1), formatNumber((room.width ?? 0) / 1000, 1), formatNumber(room.provided, 1), room.note ?? '')
				: localize('fireResults.room', "Pump room: {0} m² needed ({1} × {2} m). {3}", formatNumber(room.area, 1), formatNumber((room.length ?? 0) / 1000, 1), formatNumber((room.width ?? 0) / 1000, 1), room.note ?? '')));
		}
	}

	// Tanks.
	if (report.storage && (report.storage.tanks.length || report.tankDesigns.length)) {
		const section = resultSection(view, localize('fireResults.tanks', "Fire tanks"), localize('fireResults.tanksDetail', "designed as the plumbing tanks (OpenSees shells); an overhead tank loads its floor"));
		const t = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(t, [
			{ label: localize('fireResults.f.id', "ID"), width: 64 }, { label: localize('fireResults.f.kind', "Kind"), width: 110 },
			{ label: localize('fireResults.f.volume', "Water"), unit: M3, numeric: true, width: 72 }, { label: localize('fireResults.f.design', "Design"), width: 360 },
		]);
		const b = append(t, $('tbody'));
		for (const tank of report.storage.tanks) {
			const design = report.tankDesigns.find(d => d.id === tank.id);
			const tr = host.row(b, tank.id);
			append(tr, $('td', undefined, tank.id));
			append(tr, $('td', undefined, tank.kind ?? ''));
			append(tr, $('td.number', undefined, value(tank.volume, 1)));
			append(tr, $('td.mep-wrap', undefined, !design ? localize('fireResults.notDesigned', "not designed yet") : design.error ? design.error
				: design.failed ? localize('fireResults.designFails', "{0} check(s) of the tank design fail", design.failed) : localize('fireResults.designOk', "designed: all checks pass")));
			if (design && (design.error || design.failed)) {
				tr.classList.add('failed');
			}
		}
	}
	for (const line of report.storage?.notes ?? []) {
		append(view, $('p.mep-note', undefined, line));
	}

	// Hangers and riser supports.
	if (report.supports.length) {
		const section = resultSection(view, localize('fireResults.supports', "Hangers and riser supports"), localize('fireResults.supportsDetail', "design loads for the inserts and anchors in the structure (Sec 4.2.3.13, 4.2.3.14, 4.2.10.6)"));
		const t = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(t, [
			{ label: localize('fireResults.f.pipe', "Pipe"), width: 72 }, { label: localize('fireResults.f.kind', "Kind"), width: 80 },
			{ label: localize('fireResults.f.spacing', "Spacing"), unit: M, numeric: true, width: 72 }, { label: localize('fireResults.f.load', "Load"), unit: KN, numeric: true, width: 64 },
			{ label: localize('fireResults.f.basis', "Basis"), width: 460 },
		]);
		const b = append(t, $('tbody'));
		for (const s of report.supports) {
			const tr = append(b, $('tr'));
			append(tr, $('td', undefined, `DN${value(s.size, 0)}`));
			append(tr, $('td', undefined, s.kind));
			append(tr, $('td.number', undefined, value(s.spacing, 1)));
			append(tr, $('td.number', undefined, value(s.load, 2)));
			append(tr, $('td.mep-wrap', undefined, s.basis ?? ''));
		}
	}

	openingsTable(view, host, localize('fireResults.openings', "Sleeves still missing"), localize('fireResults.openingsDetail', "for the fire risers through the slabs and the mains through the beams: Add Sleeves adds them"), report.openings);

	// Checks with their clauses.
	if (report.checks.length) {
		const section = resultSection(view, localize('fireResults.checks', "Checks"));
		const t = append(section, $('table.mep-table.mep-result-table'));
		host.tableHead(t, [
			{ label: localize('fireResults.f.check', "Check"), width: 220 }, { label: localize('fireResults.f.demandCapacity', "Demand / capacity"), numeric: true, width: 140 },
			{ label: localize('fireResults.f.utilisation', "Utilisation"), numeric: true, width: 110 }, { label: localize('fireResults.f.clause', "Clause"), width: 200 },
			{ label: localize('fireResults.f.note', "Note"), width: 320 },
		]);
		const b = append(t, $('tbody'));
		for (const c of [...report.checks].sort((x, y) => (x.status === 'fail' ? 0 : 1) - (y.status === 'fail' ? 0 : 1))) {
			const tr = append(b, $('tr'));
			append(tr, $('td', undefined, c.name));
			append(tr, $('td.number', undefined, c.demand !== undefined && c.capacity !== undefined ? `${formatNumber(c.demand, 2)} / ${formatNumber(c.capacity, 2)}${c.unit ? ` ${c.unit}` : ''}` : ''));
			utilisationCell(tr, c.utilisation, c.status);
			append(tr, $('td.mep-wrap', undefined, c.clause ?? ''));
			append(tr, $('td.mep-wrap', undefined, c.note ?? ''));
			if (c.status === 'fail') {
				tr.classList.add('failed');
			}
		}
	}
	if (report.tests.length) {
		noteSection(view, localize('fireResults.tests', "Test pressures"), report.tests.map(t => localize('fireResults.testLine', "{0}: {1} kPa ({2})", t.system, value(t.pressure, 0), t.note ?? '')));
	}
	noteSection(view, localize('fireResults.notes', "Notes"), report.notes);
	noteSection(view, localize('fireResults.method', "Method"), report.method);
}
