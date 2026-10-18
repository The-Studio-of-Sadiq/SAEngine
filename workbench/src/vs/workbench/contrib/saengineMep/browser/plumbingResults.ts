/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { formatUtilisation } from './mepDocument.js';
import { IFloorHead, IPlumbingCheck, IPlumbingReport, ISizedItem, plumbingFailures, PlumbingStatus, systemLabel, tankKindLabel } from './plumbingDocument.js';

/*
 * The Results view of the plumbing: the backend's report (`saengine.plumbing.report`) as one
 * readable page: tiles, demand and storage, riser and stack sizes, rainwater leaders, the septic
 * tank, the tanks' design checks with their reinforcement, and the hydraulics (residual head per
 * floor against the required head, the pump duty). Plain DOM; the editor wires the rows.
 */

/** What the page needs from the editor. */
export interface IPlumbingResultsHost {
	storyName(id: string): string;
	/** The label of an occupancy key of BNBC Table 8.5.1. */
	occupancyName(key: string): string;
	/** A table row that selects the riser, tank or drain with `id` (else a plain row). */
	row(body: HTMLElement, id: string): HTMLElement;
	tableHead(table: HTMLElement, columns: readonly { label: string; unit?: string; numeric?: boolean; width?: number }[]): void;
}

const MM = localize('plb.unit.mm', "mm");
const M = localize('plb.unit.m', "m");
const M3 = localize('plb.unit.m3', "m³");
const M2 = localize('plb.unit.m2', "m²");

function statusText(status: PlumbingStatus): string {
	switch (status) {
		case 'ok': return localize('plb.status.ok', "ok");
		case 'warn': return localize('plb.status.warn', "check");
		case 'fail': return localize('plb.status.fail', "fails");
		default: return '—';
	}
}

function statusCell(row: HTMLElement, status: PlumbingStatus): void {
	const td = append(row, $('td'));
	append(td, $(`span.plb-pill.band-${status}`, undefined, statusText(status)));
	if (status === 'fail') {
		row.classList.add('failed');
	}
}

function value(n: number | undefined, digits: number): string {
	return n === undefined ? '' : formatNumber(n, digits);
}

function section(view: HTMLElement, title: string, detail?: string): HTMLElement {
	const element = append(view, $('.mep-section.result'));
	const heading = append(element, $('.mep-section-heading'));
	append(heading, $('span.mep-section-title', undefined, title));
	if (detail) {
		append(heading, $('span.mep-section-detail', undefined, detail));
	}
	return element;
}

function utilisation(row: HTMLElement, u: number | undefined, status: PlumbingStatus): void {
	const td = append(row, $('td.number.mep-util-cell'));
	if (u === undefined) {
		td.textContent = statusText(status);
		return;
	}
	const band = status === 'none' ? 'ok' : status;
	const bar = append(td, $('span.mep-util-bar'));
	append(bar, $(`span.mep-util-fill.band-${band}`, { style: `width: ${Math.min(100, u * 100).toFixed(0)}%` }));
	append(td, $(`span.mep-util-value.band-${band}`, undefined, formatUtilisation(u)));
}

/** How many of a long list of checks show before "All N checks". */
const SHOWN_CHECKS = 6;

/** The checks as a table, failing and highest utilisation first; past `shown`, the rest fold into "All N checks". */
function checksTable(parent: HTMLElement, host: IPlumbingResultsHost, checks: readonly IPlumbingCheck[], shown = Infinity): void {
	const ordered = [...checks].sort((a, b) => rank(b.status) - rank(a.status) || (b.utilisation ?? 0) - (a.utilisation ?? 0));
	const table = (rows: readonly IPlumbingCheck[], into: HTMLElement) => {
		const element = append(into, $('table.mep-table.mep-result-table'));
		host.tableHead(element, [
			{ label: localize('plb.f.check', "Check"), width: 260 }, { label: localize('plb.f.demandCapacity', "Demand / capacity"), numeric: true, width: 150 },
			{ label: localize('plb.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('plb.f.note', "Note"), width: 300 },
		]);
		const body = append(element, $('tbody'));
		for (const check of rows) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, check.name));
			append(tr, $('td.number', undefined, check.demand !== undefined && check.capacity !== undefined
				? `${formatNumber(check.demand, 2)} / ${formatNumber(check.capacity, 2)}${check.unit ? ` ${check.unit}` : ''}` : ''));
			utilisation(tr, check.utilisation, check.status);
			append(tr, $('td.mep-wrap', undefined, [check.combination, check.note].filter(Boolean).join(' · ')));
			if (check.status === 'fail') {
				tr.classList.add('failed');
			}
		}
	};
	table(ordered.slice(0, shown), parent);
	if (ordered.length > shown) {
		const more = append(parent, $('details.plb-more'));
		append(more, $('summary', undefined, localize('plb.allChecks', "All {0} checks", ordered.length)));
		table(ordered.slice(shown), more);
	}
}

function rank(status: PlumbingStatus): number {
	return status === 'fail' ? 3 : status === 'warn' ? 2 : status === 'ok' ? 1 : 0;
}

/** Renders the report into `view`. */
export function renderPlumbingReport(view: HTMLElement, report: IPlumbingReport, host: IPlumbingResultsHost): void {
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('plb.resultsTitle', "Plumbing coordination")));
	append(header, $('span.mep-view-subtitle', undefined, localize('plb.resultsSubtitle', "Computed by the backend to BNBC 2020 Part 8 from the plumbing set-up; not stored in the file.")));

	// Tiles.
	const tiles = append(view, $('.mep-tiles'));
	const tile = (text: string, label: string, band?: PlumbingStatus) => {
		const element = append(tiles, $('.mep-tile'));
		append(element, $(`span.mep-tile-value${band ? `.band-${band}` : ''}`, undefined, text));
		append(element, $('span.mep-tile-label', undefined, label));
	};
	if (report.dailyDemand !== undefined) {
		tile(localize('plb.m3dValue', "{0} m³/d", formatNumber(report.dailyDemand / 1000, 2)), localize('plb.tileDemand', "daily water demand"));
	}
	if (report.overheadRequired !== undefined) {
		tile(localize('plb.m3Value', "{0} m³", formatNumber(report.overheadRequired, 2)), localize('plb.tileOverhead', "overhead storage needed"));
	}
	const { items, floorsLow } = plumbingFailures(report);
	tile(String(items), localize('plb.tileFails', "checks fail"), items ? 'fail' : 'ok');
	if (report.floors.length) {
		tile(String(floorsLow), localize('plb.tileFloors', "floors below the minimum pressure"), floorsLow ? 'fail' : 'ok');
	}
	if (report.summary.length) {
		const summary = append(view, $('ul.plb-summary'));
		for (const line of report.summary) {
			append(summary, $('li', undefined, line));
		}
	}
	if (report.problems.length) {
		const problems = section(view, localize('plb.problems', "Problems"), localize('plb.problemsDetail', "what the backend could not read or check"));
		for (const line of report.problems) {
			append(problems, $('p.mep-note.plb-problem', undefined, line));
		}
	}

	// Demand and storage.
	if (report.demand.length || report.storage.length) {
		const demand = section(view, localize('plb.demand', "Demand and storage"), report.references.storage
			? localize('plb.demandDetailRef', "BNBC Table 8.5.1 consumption; storage {0}", report.references.storage)
			: localize('plb.demandDetail', "BNBC Table 8.5.1 consumption; storage BNBC Sec 5.9.1.2(c)"));
		if (report.demand.length) {
			const table = append(demand, $('table.mep-table.mep-result-table'));
			host.tableHead(table, [
				{ label: localize('plb.f.story', "Storey"), width: 130 }, { label: localize('plb.f.occupancy', "Occupancy"), width: 150 },
				{ label: localize('plb.f.population', "Population"), numeric: true, width: 90 }, { label: localize('plb.f.lpcd', "Consumption"), unit: localize('plb.unit.lpcd', "lpcd"), numeric: true, width: 100 },
				{ label: localize('plb.f.daily', "Daily"), unit: localize('plb.unit.ld', "L/d"), numeric: true, width: 90 },
				{ label: localize('plb.f.supplyUnits', "Supply units"), numeric: true, width: 90 }, { label: localize('plb.f.drainageUnits', "Drainage units"), numeric: true, width: 100 },
			]);
			const body = append(table, $('tbody'));
			for (const row of report.demand) {
				const tr = append(body, $('tr'));
				append(tr, $('td', undefined, host.storyName(row.story)));
				append(tr, $('td', undefined, row.occupancy ? host.occupancyName(row.occupancy) : ''));
				append(tr, $('td.number', undefined, value(row.population, 0)));
				append(tr, $('td.number', undefined, value(row.lpcd, 0)));
				append(tr, $('td.number', undefined, value(row.daily, 0)));
				append(tr, $('td.number', undefined, value(row.supplyUnits, 1)));
				append(tr, $('td.number', undefined, value(row.drainageUnits, 1)));
			}
			if (report.dailyDemand !== undefined) {
				const tr = append(body, $('tr.plb-total'));
				append(tr, $('td', { colspan: '2' }, localize('plb.total', "Total")));
				append(tr, $('td.number', undefined, value(report.population, 0)));
				append(tr, $('td'));
				append(tr, $('td.number', undefined, formatNumber(report.dailyDemand, 0)));
				append(tr, $('td', { colspan: '2' }));
			}
		}
		if (report.storage.length) {
			const table = append(demand, $('table.mep-table.mep-result-table'));
			host.tableHead(table, [
				{ label: localize('plb.f.storage', "Storage"), width: 160 }, { label: localize('plb.f.tank', "Tank"), width: 80 },
				{ label: localize('plb.f.required', "Required"), unit: M3, numeric: true, width: 90 }, { label: localize('plb.f.provided', "Provided"), unit: M3, numeric: true, width: 90 },
				{ label: localize('plb.f.status', "Status"), width: 80 }, { label: localize('plb.f.note', "Note"), width: 300 },
			]);
			const body = append(table, $('tbody'));
			for (const row of report.storage) {
				const tr = row.tank ? host.row(body, row.tank) : append(body, $('tr'));
				append(tr, $('td', undefined, row.kind ? tankKindLabel(row.kind) : ''));
				append(tr, $('td', undefined, row.tank ?? ''));
				append(tr, $('td.number', undefined, value(row.required, 2)));
				append(tr, $('td.number', undefined, value(row.provided, 2)));
				statusCell(tr, row.status);
				append(tr, $('td.mep-wrap', undefined, row.note ?? ''));
			}
		}
		if (report.fireReserve) {
			append(demand, $('p.mep-note', undefined, localize('plb.fireReserve', "Each tank includes a fire reserve of {0} m³.", formatNumber(report.fireReserve, 1))));
		}
	}

	sizedTable(view, host, localize('plb.risers', "Risers and stacks"), localize('plb.risersDetail', "fixture units: BNBC Appendix O Table 8.O.1, Tables 8.5.4 to 8.5.6; stacks Tables 8.6.12 to 8.6.16"), report.risers, false);
	sizedTable(view, host, localize('plb.leaders', "Rainwater leaders"), report.references.rainwater ?? localize('plb.leadersDetail', "BNBC Table 8.7.2"), report.leaders, true);

	// Septic tank and soak well.
	if (report.septic.length) {
		const detail = [report.references.septic, report.references.soakWell].filter(Boolean).join('; ') || localize('plb.septicDetail', "BNBC Sec 6.9.12, Appendix S; soak well Table 8.6.10");
		const septic = section(view, localize('plb.septic', "Septic tank and soak well"), detail);
		const table = append(septic, $('table.mep-table.mep-result-table'));
		host.tableHead(table, [
			{ label: localize('plb.f.item', "Item"), width: 150 }, { label: localize('plb.f.users', "Users"), numeric: true, width: 70 },
			{ label: localize('plb.f.liquid', "Liquid needed"), unit: M3, numeric: true, width: 100 }, { label: localize('plb.f.provided', "Provided"), unit: M3, numeric: true, width: 90 },
			{ label: localize('plb.f.sizes', "Inside sizes"), unit: MM, width: 170 }, { label: localize('plb.f.status', "Status"), width: 80 }, { label: localize('plb.f.note', "Note"), width: 300 },
		]);
		const body = append(table, $('tbody'));
		for (const s of report.septic) {
			const tr = s.id ? host.row(body, s.id) : append(body, $('tr'));
			const label = s.kind === 'septic' ? tankKindLabel('septic') : tankKindLabel('soakWell');
			append(tr, $('td', undefined, s.id ? `${label} ${s.id}` : label));
			append(tr, $('td.number', undefined, value(s.population, 0)));
			append(tr, $('td.number', undefined, value(s.required, 2)));
			append(tr, $('td.number', undefined, value(s.provided, 2)));
			const sizes = s.diameter !== undefined
				? s.depth === undefined ? `Ø${formatNumber(s.diameter, 0)}` : localize('plb.wellSizes', "Ø{0} × {1} deep", formatNumber(s.diameter, 0), formatNumber(s.depth, 0))
				: s.length && s.width && s.depth ? `${formatNumber(s.length, 0)} × ${formatNumber(s.width, 0)} × ${formatNumber(s.depth, 0)}` : '';
			append(tr, $('td', undefined, sizes));
			statusCell(tr, s.status);
			append(tr, $('td.mep-wrap', undefined, s.note ?? ''));
		}
	}

	// The checks of the sizing (P1).
	if (report.checks.length) {
		const checks = section(view, localize('plb.checks', "Checks"), localize('plb.checksDetail', "storage, risers, stacks, drains, rainwater, septic tank, soak well and separations"));
		checksTable(checks, host, report.checks);
	}

	// Tank design (P2).
	if (report.tanks.length) {
		const tanks = section(view, localize('plb.tankDesign', "Tank design"), localize('plb.tankDesignDetail', "walls, base and roof as RC plates; the governing checks first"));
		for (const tank of report.tanks) {
			const card = append(tanks, $(`.plb-tank-card${tank.status === 'fail' ? '.failed' : ''}`));
			const title = append(card, $('.plb-tank-card-title'));
			append(title, $('span.plb-tank-card-id', undefined, tank.id));
			append(title, $('span.mep-muted-inline', undefined, [tank.kind ? tankKindLabel(tank.kind) : '', tank.capacity !== undefined ? localize('plb.m3Value', "{0} m³", formatNumber(tank.capacity, 1)) : ''].filter(Boolean).join(' · ')));
			append(title, $(`span.plb-pill.band-${tank.status}`, undefined, statusText(tank.status)));
			if (tank.checks.length) {
				checksTable(card, host, tank.checks, SHOWN_CHECKS);
			}
			if (tank.reinforcement.length) {
				append(card, $('.mep-subheading', undefined, localize('plb.reinforcement', "Reinforcement")));
				const list = append(card, $('dl.plb-bars'));
				for (const bar of tank.reinforcement) {
					append(list, $('dt', undefined, bar.location));
					append(list, $('dd', undefined, bar.bars));
				}
			}
			for (const line of [tank.loads, tank.quantities, ...tank.notes]) {
				if (line) {
					append(card, $('p.mep-note', undefined, line));
				}
			}
		}
	}

	// Hydraulics (P3; the pump also from P1).
	if (report.floors.length || report.pump || report.hydraulicChecks.length) {
		const hydraulics = section(view, localize('plb.hydraulics', "Hydraulics"), report.requiredHead !== undefined
			? localize('plb.hydraulicsDetail', "residual head at each floor against the required {0} m", formatNumber(report.requiredHead, 1))
			: localize('plb.hydraulicsDetailNone', "residual head at each floor"));
		if (report.floors.length) {
			headChart(append(hydraulics, $('.plb-head-chart')), report.floors, host);
		}
		if (report.pump) {
			const pump = report.pump;
			const parts = [
				pump.flow !== undefined ? localize('plb.pumpFlow', "{0} L/s", formatNumber(pump.flow, 2)) : '',
				pump.head !== undefined ? localize('plb.pumpHead', "{0} m head", formatNumber(pump.head, 1)) : '',
				pump.power !== undefined ? localize('plb.pumpPower', "{0} kW", formatNumber(pump.power, 2)) : '',
			].filter(Boolean);
			const line = append(hydraulics, $('p.plb-pump'));
			append(line, $('span.plb-pump-label', undefined, localize('plb.pump', "Pump duty")));
			append(line, $('span', undefined, parts.join(' · ')));
			if (pump.note) {
				append(hydraulics, $('p.mep-note', undefined, pump.note));
			}
		}
		if (report.hydraulicChecks.length) {
			checksTable(hydraulics, host, report.hydraulicChecks, SHOWN_CHECKS);
		}
	}

	for (const [title, lines] of [[localize('plb.notes', "Notes"), report.notes], [localize('plb.method', "Method"), report.method]] as const) {
		if (lines.length) {
			const element = section(view, title);
			for (const line of lines) {
				append(element, $('p.mep-note', undefined, line));
			}
		}
	}
}

function sizedTable(view: HTMLElement, host: IPlumbingResultsHost, title: string, detail: string, items: readonly ISizedItem[], leaders: boolean): void {
	if (!items.length) {
		return;
	}
	const element = section(view, title, detail);
	const table = append(element, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('plb.f.id', "ID"), width: 70 }, leaders ? { label: localize('plb.f.catchment', "Catchment"), unit: M2, numeric: true, width: 90 } : { label: localize('plb.f.system', "System"), width: 150 },
		{ label: localize('plb.f.load', "Load"), numeric: true, width: 110 }, { label: localize('plb.f.requiredSize', "Required"), unit: MM, numeric: true, width: 90 },
		{ label: localize('plb.f.diameter', "Diameter"), unit: MM, numeric: true, width: 90 }, { label: localize('plb.f.status', "Status"), width: 80 }, { label: localize('plb.f.note', "Note"), width: 300 },
	]);
	const body = append(table, $('tbody'));
	for (const item of items) {
		const tr = host.row(body, item.id);
		append(tr, $('td', undefined, item.id));
		append(tr, leaders ? $('td.number', undefined, value(item.area, 1)) : $('td', undefined, item.system ? systemLabel(item.system) : ''));
		append(tr, $('td.number', undefined, item.load === undefined ? '' : `${formatNumber(item.load, 1)}${item.loadUnit ? ` ${item.loadUnit}` : ''}`));
		append(tr, $('td.number', undefined, value(item.required, 0)));
		append(tr, $('td.number', undefined, value(item.diameter, 0)));
		statusCell(tr, item.status);
		append(tr, $('td.mep-wrap', undefined, item.note ?? ''));
	}
}

/** Residual head per floor as vertical bars, lowest floor on the left, with the required head as a dashed line. */
function headChart(container: HTMLElement, floors: readonly IFloorHead[], host: IPlumbingResultsHost): void {
	const barWidth = 30;
	const gap = 30;
	const left = 40;
	const top = 14;
	const plot = 150;
	const width = left + floors.length * (barWidth + gap) + gap;
	const height = top + plot + 36;
	const required = floors.map(f => f.required).filter((r): r is number => r !== undefined);
	const manyRisers = new Set(floors.map(f => f.riser)).size > 1;
	const max = Math.max(1, ...floors.map(f => f.head), ...required) * 1.15;
	const y = (head: number) => top + plot - Math.max(0, head) / max * plot;
	const root = svg(container, 'svg', { width, height, class: 'plb-chart', role: 'img', 'aria-label': localize('plb.chartAria', "Residual head per floor") });
	// Axis: a few recessive gridlines in m.
	const step = max > 40 ? 10 : max > 16 ? 5 : 2;
	for (let v = 0; v <= max; v += step) {
		svg(root, 'line', { x1: left - 4, y1: y(v), x2: width, y2: y(v), class: v === 0 ? 'plb-chart-base' : 'plb-chart-grid' });
		svg(root, 'text', { x: left - 8, y: y(v) + 4, class: 'plb-chart-tick', 'text-anchor': 'end' }, formatNumber(v, 0));
	}
	svg(root, 'text', { x: 4, y: top - 4, class: 'plb-chart-tick' }, M);
	floors.forEach((floor, i) => {
		const x = left + gap + i * (barWidth + gap);
		const group = svg(root, 'g', { class: `plb-chart-bar band-${floor.status}` });
		svg(group, 'title', {}, localize('plb.chartTip', "{0}: {1} m residual head{2}", host.storyName(floor.story), formatNumber(floor.head, 1),
			floor.required !== undefined ? localize('plb.chartTipRequired', " (required {0} m)", formatNumber(floor.required, 1)) : ''));
		// A hit area the full height of the plot, for the tooltip.
		svg(group, 'rect', { x: x - gap / 2, y: top, width: barWidth + gap, height: plot, class: 'plb-chart-hit' });
		const h = Math.max(1, top + plot - y(floor.head));
		svg(group, 'path', { d: `M${x} ${top + plot}V${top + plot - h + 4}Q${x} ${top + plot - h} ${x + 4} ${top + plot - h}H${x + barWidth - 4}Q${x + barWidth} ${top + plot - h} ${x + barWidth} ${top + plot - h + 4}V${top + plot}Z`, class: 'plb-chart-fill' });
		svg(group, 'text', { x: x + barWidth / 2, y: top + plot - h - 4, class: 'plb-chart-value', 'text-anchor': 'middle' }, formatNumber(floor.head, 1));
		svg(root, 'text', { x: x + barWidth / 2, y: top + plot + 16, class: 'plb-chart-tick', 'text-anchor': 'middle' }, host.storyName(floor.story));
		if (manyRisers && floor.riser) {
			svg(root, 'text', { x: x + barWidth / 2, y: top + plot + 30, class: 'plb-chart-tick', 'text-anchor': 'middle' }, floor.riser);
		}
		if (floor.required !== undefined) {
			svg(root, 'line', { x1: x - 6, y1: y(floor.required), x2: x + barWidth + 6, y2: y(floor.required), class: 'plb-chart-required' });
		}
	});
	if (required.length) {
		const legend = append(container, $('.mep-legend.plb-chart-legend'));
		const item = append(legend, $('span.mep-legend-item'));
		append(item, $('span.plb-swatch-required'));
		append(item, $('span', undefined, localize('plb.chartRequired', "required residual head")));
		const below = append(legend, $('span.mep-legend-item'));
		append(below, $('span.mep-swatch.plb-swatch-fail'));
		append(below, $('span', undefined, localize('plb.chartBelow', "below the required head")));
	}
}
