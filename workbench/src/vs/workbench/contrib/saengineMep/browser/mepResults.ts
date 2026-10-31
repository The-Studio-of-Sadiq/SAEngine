/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { formatUtilisation } from './mepDocument.js';
import { CheckStatus, IMepCheck, statusRank } from './mepRead.js';

/*
 * The parts of the services' Results views that every discipline shares (plumbing, HVAC,
 * electrical): sections, tiles, status pills, utilisation bars, the checks table and a small
 * horizontal bar chart. Plain DOM; the editor wires the rows.
 */

export interface ITableColumn {
	readonly label: string;
	readonly unit?: string;
	readonly numeric?: boolean;
	readonly width?: number;
	/** The header's tooltip; else its label and unit (a narrow column's label can be cut). */
	readonly title?: string;
}

/** What the result pages need from the editor. */
export interface IResultsHost {
	storyName(id: string): string;
	/** A table row that selects the item with `id` (else a plain row). */
	row(body: HTMLElement, id: string): HTMLElement;
	tableHead(table: HTMLElement, columns: readonly ITableColumn[]): void;
}

export function statusText(status: CheckStatus): string {
	switch (status) {
		case 'ok': return localize('mepResults.status.ok', "ok");
		case 'warn': return localize('mepResults.status.warn', "check");
		case 'fail': return localize('mepResults.status.fail', "fails");
		default: return '—';
	}
}

export function statusPill(status: CheckStatus): HTMLElement {
	return $(`span.plb-pill.band-${status}`, undefined, statusText(status));
}

export function statusCell(row: HTMLElement, status: CheckStatus): void {
	const td = append(row, $('td'));
	append(td, statusPill(status));
	if (status === 'fail') {
		row.classList.add('failed');
	}
}

/** A number for a table cell; '' when there is none. */
export function value(n: number | undefined, digits: number): string {
	return n === undefined ? '' : formatNumber(n, digits);
}

export function resultSection(view: HTMLElement, title: string, detail?: string): HTMLElement {
	const element = append(view, $('.mep-section.result'));
	const heading = append(element, $('.mep-section-heading'));
	append(heading, $('span.mep-section-title', undefined, title));
	if (detail) {
		append(heading, $('span.mep-section-detail', undefined, detail));
	}
	return element;
}

/** A row of tiles: `tile(value, label, band?)` adds one. */
export function tiles(view: HTMLElement): (text: string, label: string, band?: CheckStatus) => void {
	const element = append(view, $('.mep-tiles'));
	return (text, label, band) => {
		const tile = append(element, $('.mep-tile'));
		append(tile, $(`span.mep-tile-value${band ? `.band-${band}` : ''}`, undefined, text));
		append(tile, $('span.mep-tile-label', undefined, label));
	};
}

/** A utilisation cell: a short bar in the status's band and the value; the status in words without one. */
export function utilisationCell(row: HTMLElement, u: number | undefined, status: CheckStatus): void {
	const td = append(row, $('td.number.mep-util-cell'));
	if (u === undefined) {
		td.textContent = statusText(status);
		if (status === 'fail') {
			td.classList.add('band-fail');
		}
		return;
	}
	const band = status === 'none' ? 'ok' : status;
	const bar = append(td, $('span.mep-util-bar'));
	append(bar, $(`span.mep-util-fill.band-${band}`, { style: `width: ${Math.min(100, u * 100).toFixed(0)}%` }));
	append(td, $(`span.mep-util-value.band-${band}`, undefined, formatUtilisation(u)));
}

/** The checks as a table, failing and highest utilisation first; past `shown`, the rest fold into "All N checks". Returns the first failing row. */
export function checksTable(parent: HTMLElement, host: Pick<IResultsHost, 'tableHead'>, checks: readonly IMepCheck[], shown = Infinity): HTMLElement | undefined {
	let firstFailure: HTMLElement | undefined;
	const ordered = [...checks].sort((a, b) => statusRank(b.status) - statusRank(a.status) || (b.utilisation ?? 0) - (a.utilisation ?? 0));
	const table = (rows: readonly IMepCheck[], into: HTMLElement) => {
		const element = append(into, $('table.mep-table.mep-result-table'));
		host.tableHead(element, [
			{ label: localize('mepResults.f.check', "Check"), width: 260 }, { label: localize('mepResults.f.demandCapacity', "Demand / capacity"), numeric: true, width: 150 },
			{ label: localize('mepResults.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('mepResults.f.note', "Note"), width: 300 },
		]);
		const body = append(element, $('tbody'));
		for (const check of rows) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, check.name));
			append(tr, $('td.number', undefined, check.demand !== undefined && check.capacity !== undefined
				? `${formatNumber(check.demand, 2)} / ${formatNumber(check.capacity, 2)}${check.unit ? ` ${check.unit}` : ''}` : ''));
			utilisationCell(tr, check.utilisation, check.status);
			append(tr, $('td.mep-wrap', undefined, [check.combination, check.note].filter(Boolean).join(' · ')));
			if (check.status === 'fail') {
				tr.classList.add('failed');
				firstFailure ??= tr;
			}
		}
	};
	// The checks that need attention in full; the passing ones grouped under one line (N-E6).
	const attention = ordered.filter(c => c.status === 'fail' || c.status === 'warn');
	const head = attention.length ? attention : ordered.slice(0, Math.min(shown, ordered.length));
	const rest = ordered.slice(head.length);
	if (head.length) {
		table(head, parent);
	}
	if (rest.length) {
		const more = append(parent, $('details.plb-more'));
		append(more, $('summary', undefined, attention.length
			? localize('mepResults.passingChecks', "{0} more checks pass or are not applicable", rest.length)
			: localize('mepResults.allChecks', "All {0} checks", ordered.length)));
		table(rest, more);
	}
	return firstFailure;
}

/** Paragraphs of notes under a heading (nothing when there are none). */
export function noteSection(view: HTMLElement, title: string, lines: readonly string[], className = 'p.mep-note'): void {
	if (!lines.length) {
		return;
	}
	const element = resultSection(view, title);
	for (const line of lines) {
		append(element, $(className, undefined, line));
	}
}

export interface IBarRow {
	readonly label: string;
	/** The parts of the bar, stacked left to right; each with its CSS class (its colour). */
	readonly parts: readonly { readonly value: number; readonly className: string; readonly label: string }[];
	/** The text at the end of the bar. */
	readonly text: string;
	readonly status?: CheckStatus;
}

/**
 * A small horizontal bar chart: one bar per row (stacked parts), the label on the left and the
 * value at the end of the bar; a legend of the parts under it. Rows keep their order.
 */
export function barChart(container: HTMLElement, rows: readonly IBarRow[], aria: string): void {
	if (!rows.length) {
		return;
	}
	const labelWidth = 120;
	const plot = 320;
	const rowHeight = 22;
	const barHeight = 12;
	const width = labelWidth + plot + 90;
	const height = rows.length * rowHeight + 6;
	const max = Math.max(1e-9, ...rows.map(r => r.parts.reduce((s, p) => s + Math.max(0, p.value), 0)));
	const root = svg(container, 'svg', { width, height, class: 'mep-bar-chart', role: 'img', 'aria-label': aria });
	rows.forEach((row, i) => {
		const y = 3 + i * rowHeight;
		const group = svg(root, 'g', { class: `mep-bar-row${row.status ? ` band-${row.status}` : ''}` });
		svg(group, 'title', {}, `${row.label}: ${row.parts.map(p => `${p.label} ${formatNumber(p.value, 1)}`).join(', ')}`);
		svg(group, 'text', { x: labelWidth - 8, y: y + barHeight - 1, class: 'mep-bar-label', 'text-anchor': 'end' }, row.label);
		let x = labelWidth;
		for (const part of row.parts) {
			const w = Math.max(0, part.value) / max * plot;
			if (w > 0) {
				svg(group, 'rect', { x, y, width: Math.max(1, w), height: barHeight, rx: 2, class: `mep-bar ${part.className}` });
			}
			x += w;
		}
		svg(group, 'text', { x: x + 6, y: y + barHeight - 1, class: 'mep-bar-value' }, row.text);
	});
	const parts = new Map<string, string>();
	for (const row of rows) {
		for (const part of row.parts) {
			parts.set(part.className, part.label);
		}
	}
	if (parts.size > 1) {
		const legend = append(container, $('.mep-legend.mep-bar-legend'));
		for (const [className, label] of parts) {
			const item = append(legend, $('span.mep-legend-item'));
			append(item, $(`span.mep-swatch.mep-bar-swatch.${className.split(' ').join('.')}`));
			append(item, $('span', undefined, label));
		}
	}
}
