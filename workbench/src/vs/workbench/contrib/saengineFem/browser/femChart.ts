/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * The FEM results' charts, drawn as SVG: lines, filled diagrams, bars and points on two linear
 * axes with nice ticks, guide lines (a code limit, the 90 % mass line, the modal periods), a
 * legend and a caption. The charts SAEngine draws are small (tens to a few hundred points), so
 * a chart library would add a download and a bundle for nothing this does not: SVG built with
 * the DOM (no markup strings, so Trusted Types are no concern), coloured by the theme's chart
 * colours through CSS variables (light, dark and high contrast follow), with the values in each
 * point's tooltip and the caption saying what matters for screen readers.
 */

import './media/femChart.css';
import { $, append } from '../../../../base/browser/dom.js';
import { FemTableCell } from '../../../../platform/saengine/common/femSolver.js';
import { formatCell, IFemSheet } from './femChartData.js';

const SVG = 'http://www.w3.org/2000/svg';

/** The theme's chart colours (`--vscode-charts-*`), and the editor's text colour. */
export type ChartColor = 'blue' | 'orange' | 'green' | 'red' | 'purple' | 'yellow' | 'foreground';

export interface IChartSeries {
	readonly name: string;
	/** [x, y] in the chart's units. */
	readonly points: readonly (readonly number[])[];
	readonly color: ChartColor;
	/** `area`: filled to y = 0 (a force diagram); `bars`: a bar per point; `points`: markers only. */
	readonly style?: 'line' | 'dashed' | 'area' | 'bars' | 'points';
	/** The tooltip of each point (default: "name: x, y"). */
	readonly tooltips?: readonly string[];
	/** Bars only: the bar's offset from its x and its width, in x units (grouped bars). */
	readonly bar?: { readonly offset: number; readonly width: number };
}

export interface IChartGuide {
	/** `x`: a vertical line at x = value; `y`: a horizontal one. */
	readonly axis: 'x' | 'y';
	readonly value: number;
	readonly label: string;
	readonly color?: ChartColor;
}

export interface IChartSpec {
	readonly title: string;
	readonly xLabel: string;
	readonly yLabel: string;
	readonly xFormat?: (value: number) => string;
	readonly yFormat?: (value: number) => string;
	readonly series: readonly IChartSeries[];
	readonly guides?: readonly IChartGuide[];
	/** Text marks at points (the largest value of a diagram). */
	readonly marks?: readonly { readonly x: number; readonly y: number; readonly text: string; readonly color?: ChartColor }[];
	/** Always show these values on the axes (0 by default for both). */
	readonly include?: { readonly x?: readonly number[]; readonly y?: readonly number[] };
	/** Same scale on both axes (an interaction contour). */
	readonly equalAxes?: boolean;
	/** The x axis spans exactly this range (a member's length), not the round ticks around it. */
	readonly xDomain?: readonly [number, number];
	/** What matters, said under the chart (and to screen readers). */
	readonly caption?: string;
	readonly height?: number;
}

const WIDTH = 480;
const MARGIN = { left: 58, right: 16, top: 12, bottom: 40 };

/** About `count` round tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 5): number[] {
	if (!isFinite(min) || !isFinite(max)) {
		return [0];
	}
	if (max - min < 1e-12) {
		const pad = Math.abs(max) > 1e-12 ? Math.abs(max) * 0.1 : 1;
		min -= pad;
		max += pad;
	}
	const raw = (max - min) / Math.max(1, count);
	const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
	const step = [1, 2, 2.5, 5, 10].map(f => f * magnitude).find(s => s >= raw) ?? 10 * magnitude;
	const first = Math.floor(min / step + 1e-9) * step;
	const ticks: number[] = [];
	// From the tick at or below the least value to the first at or above the largest.
	for (let k = 0; k <= 50; k++) {
		const v = first + k * step;
		ticks.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
		if (ticks.length >= 2 && v >= max - step * 1e-6) {
			break;
		}
	}
	return ticks;
}

/** A number on an axis: few digits, no trailing zeros. */
export function tickText(value: number): string {
	if (value === 0) {
		return '0';
	}
	const abs = Math.abs(value);
	if (abs >= 1e5 || abs < 1e-3) {
		return value.toExponential(1);
	}
	return Number(value.toPrecision(4)).toString();
}

function svg<K extends keyof SVGElementTagNameMap>(parent: Element, tag: K, attributes: { [name: string]: string | number }): SVGElementTagNameMap[K] {
	const element = parent.ownerDocument.createElementNS(SVG, tag) as SVGElementTagNameMap[K];
	for (const [name, value] of Object.entries(attributes)) {
		element.setAttribute(name, String(value));
	}
	parent.appendChild(element);
	return element;
}

/** Appends the rows of a result table to its `tbody`, numbers right-aligned ({@link formatCell}). */
export function renderSheetRows(body: HTMLElement, rows: readonly (readonly FemTableCell[])[]): void {
	for (const row of rows) {
		const tr = append(body, $('tr'));
		for (const cell of row) {
			append(tr, $(typeof cell === 'number' ? 'td.number' : 'td', undefined, formatCell(cell)));
		}
	}
}

/** Draws a result table (a sheet) into `container`: its columns, rows and notes. */
export function renderSheet(container: HTMLElement, sheet: IFemSheet): void {
	const table = append(append(container, $('.fem-results-table-wrap')), $('table.fem-table'));
	const head = append(append(table, $('thead')), $('tr'));
	for (const column of sheet.columns) {
		append(head, $('th', undefined, column));
	}
	renderSheetRows(append(table, $('tbody')), sheet.rows);
	for (const note of sheet.notes ?? []) {
		append(container, $('.fem-results-note', undefined, note));
	}
}

function title(parent: Element, text: string): void {
	svg(parent, 'title', {}).textContent = text;
}

function colorClass(color: ChartColor | undefined): string {
	return `fem-chart-${color ?? 'foreground'}`;
}

/**
 * Draws a chart into `parent` as a figure (the SVG, its legend and caption) and returns it. The
 * SVG keeps its proportions and fills the figure's width.
 */
export function renderChart(parent: HTMLElement, spec: IChartSpec): HTMLElement {
	const figure = append(parent, $('figure.fem-chart'));
	append(figure, $('.fem-chart-title', undefined, spec.title));
	const height = spec.height ?? 300;
	const plotW = WIDTH - MARGIN.left - MARGIN.right;
	const plotH = height - MARGIN.top - MARGIN.bottom;

	// The ranges: every point, the guides, the marks and the values to include.
	const xs: number[] = [...(spec.include?.x ?? [0])];
	const ys: number[] = [...(spec.include?.y ?? [0])];
	for (const series of spec.series) {
		for (const p of series.points) {
			const bar = series.bar;
			xs.push(p[0] + (bar ? bar.offset - bar.width / 2 : 0), p[0] + (bar ? bar.offset + bar.width / 2 : 0));
			ys.push(p[1]);
		}
	}
	for (const guide of spec.guides ?? []) {
		(guide.axis === 'x' ? xs : ys).push(guide.value);
	}
	let xTicks = niceTicks(Math.min(...xs), Math.max(...xs));
	let yTicks = niceTicks(Math.min(...ys), Math.max(...ys));
	let x0 = xTicks[0], x1 = xTicks[xTicks.length - 1];
	let y0 = yTicks[0], y1 = yTicks[yTicks.length - 1];
	if (spec.equalAxes) {
		// One unit is as long on both axes: widen the shorter range about its centre.
		const unitX = (x1 - x0) / plotW;
		const unitY = (y1 - y0) / plotH;
		if (unitX > unitY) {
			const mid = (y0 + y1) / 2;
			yTicks = niceTicks(mid - unitX * plotH / 2, mid + unitX * plotH / 2);
		} else {
			const mid = (x0 + x1) / 2;
			xTicks = niceTicks(mid - unitY * plotW / 2, mid + unitY * plotW / 2);
		}
		x0 = xTicks[0]; x1 = xTicks[xTicks.length - 1];
		y0 = yTicks[0]; y1 = yTicks[yTicks.length - 1];
	} else if (spec.xDomain && spec.xDomain[1] > spec.xDomain[0]) {
		[x0, x1] = spec.xDomain;
		// The round ticks inside, and the end itself (replacing a round tick too close to it).
		const inside = niceTicks(x0, x1).filter(t => t >= x0 - 1e-9 && t <= x1 + 1e-9);
		const step = inside.length > 1 ? inside[1] - inside[0] : x1 - x0;
		xTicks = [...inside.filter(t => t < x1 - 0.4 * step), Number(x1.toPrecision(4))];
	}
	const sx = (v: number) => MARGIN.left + (x1 > x0 ? (v - x0) / (x1 - x0) : 0.5) * plotW;
	const sy = (v: number) => MARGIN.top + plotH - (y1 > y0 ? (v - y0) / (y1 - y0) : 0.5) * plotH;
	const xFormat = spec.xFormat ?? tickText;
	const yFormat = spec.yFormat ?? tickText;

	const root = svg(figure, 'svg', { viewBox: `0 0 ${WIDTH} ${height}`, role: 'img', class: 'fem-chart-svg' });
	root.setAttribute('aria-label', [spec.title, spec.caption].filter(Boolean).join('. '));

	// Grid and axes.
	const grid = svg(root, 'g', { class: 'fem-chart-grid' });
	for (const t of xTicks) {
		svg(grid, 'line', { x1: sx(t), x2: sx(t), y1: MARGIN.top, y2: MARGIN.top + plotH });
		const text = svg(root, 'text', { x: sx(t), y: MARGIN.top + plotH + 14, 'text-anchor': 'middle', class: 'fem-chart-tick' });
		text.textContent = tickText(t);
	}
	for (const t of yTicks) {
		svg(grid, 'line', { x1: MARGIN.left, x2: MARGIN.left + plotW, y1: sy(t), y2: sy(t) });
		const text = svg(root, 'text', { x: MARGIN.left - 6, y: sy(t) + 4, 'text-anchor': 'end', class: 'fem-chart-tick' });
		text.textContent = tickText(t);
	}
	const axes = svg(root, 'g', { class: 'fem-chart-axis' });
	if (x0 <= 0 && x1 >= 0) {
		svg(axes, 'line', { x1: sx(0), x2: sx(0), y1: MARGIN.top, y2: MARGIN.top + plotH });
	}
	if (y0 <= 0 && y1 >= 0) {
		svg(axes, 'line', { x1: MARGIN.left, x2: MARGIN.left + plotW, y1: sy(0), y2: sy(0) });
	}
	svg(axes, 'rect', { x: MARGIN.left, y: MARGIN.top, width: plotW, height: plotH, class: 'fem-chart-frame' });
	const xLabel = svg(root, 'text', { x: MARGIN.left + plotW / 2, y: height - 6, 'text-anchor': 'middle', class: 'fem-chart-label' });
	xLabel.textContent = spec.xLabel;
	const yLabel = svg(root, 'text', { x: 12, y: MARGIN.top + plotH / 2, 'text-anchor': 'middle', class: 'fem-chart-label', transform: `rotate(-90 12 ${MARGIN.top + plotH / 2})` });
	yLabel.textContent = spec.yLabel;

	// Guides under the data.
	for (const guide of spec.guides ?? []) {
		const g = svg(root, 'g', { class: `fem-chart-guide ${colorClass(guide.color ?? 'red')}` });
		if (guide.axis === 'x') {
			svg(g, 'line', { x1: sx(guide.value), x2: sx(guide.value), y1: MARGIN.top, y2: MARGIN.top + plotH });
			const text = svg(g, 'text', { x: sx(guide.value) + 3, y: MARGIN.top + 10, class: 'fem-chart-guide-text' });
			text.textContent = guide.label;
		} else {
			svg(g, 'line', { x1: MARGIN.left, x2: MARGIN.left + plotW, y1: sy(guide.value), y2: sy(guide.value) });
			const text = svg(g, 'text', { x: MARGIN.left + plotW - 3, y: sy(guide.value) - 3, 'text-anchor': 'end', class: 'fem-chart-guide-text' });
			text.textContent = guide.label;
		}
		title(g, guide.label);
	}

	// The data.
	const clip = `fem-chart-clip-${Math.random().toString(36).slice(2)}`;
	const defs = svg(root, 'defs', {});
	svg(svg(defs, 'clipPath', { id: clip }), 'rect', { x: MARGIN.left, y: MARGIN.top, width: plotW, height: plotH });
	const data = svg(root, 'g', { 'clip-path': `url(#${clip})` });
	for (const series of spec.series) {
		const g = svg(data, 'g', { class: `fem-chart-series ${colorClass(series.color)} ${series.style ?? 'line'}` });
		const tip = (k: number) => series.tooltips?.[k] ?? `${series.name}: ${xFormat(series.points[k][0])}, ${yFormat(series.points[k][1])}`;
		const style = series.style ?? 'line';
		if (style === 'bars') {
			const bar = series.bar ?? { offset: 0, width: 0.6 };
			series.points.forEach((p, k) => {
				const left = sx(p[0] + bar.offset - bar.width / 2);
				const right = sx(p[0] + bar.offset + bar.width / 2);
				const top = sy(Math.max(0, p[1]));
				const bottom = sy(Math.min(0, p[1]));
				title(svg(g, 'rect', { x: left, y: top, width: Math.max(1, right - left), height: Math.max(0.5, bottom - top) }), tip(k));
			});
			continue;
		}
		if (style !== 'points' && series.points.length > 1) {
			const path = series.points.map((p, k) => `${k ? 'L' : 'M'}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join('');
			if (style === 'area') {
				const first = series.points[0];
				const last = series.points[series.points.length - 1];
				svg(g, 'path', { d: `M${sx(first[0]).toFixed(2)},${sy(0).toFixed(2)}${path.replace(/^M/, 'L')}L${sx(last[0]).toFixed(2)},${sy(0).toFixed(2)}Z`, class: 'fem-chart-fill' });
			}
			svg(g, 'path', { d: path, class: 'fem-chart-line' });
		}
		// Markers: every point of a sparse series (and of `points`), for the tooltips.
		if (style === 'points' || series.points.length <= 40) {
			series.points.forEach((p, k) => {
				title(svg(g, 'circle', { cx: sx(p[0]), cy: sy(p[1]), r: style === 'points' ? 3.5 : 2.5, class: 'fem-chart-marker' }), tip(k));
			});
		}
	}
	for (const mark of spec.marks ?? []) {
		const g = svg(root, 'g', { class: `fem-chart-mark ${colorClass(mark.color)}` });
		svg(g, 'circle', { cx: sx(mark.x), cy: sy(mark.y), r: 3 });
		const right = sx(mark.x) > MARGIN.left + plotW * 0.7;
		const text = svg(g, 'text', { x: sx(mark.x) + (right ? -6 : 6), y: sy(mark.y) - 6, 'text-anchor': right ? 'end' : 'start' });
		text.textContent = mark.text;
	}

	// Legend and caption, as text.
	if (spec.series.length > 1 || (spec.guides?.length ?? 0) > 0) {
		const legend = append(figure, $('.fem-chart-legend'));
		for (const series of spec.series) {
			const item = append(legend, $('span.fem-chart-legend-item'));
			append(item, $(`span.fem-chart-swatch.${colorClass(series.color)}.${series.style ?? 'line'}`));
			append(item, $('span', undefined, series.name));
		}
		for (const guide of spec.guides ?? []) {
			if (guide.axis === 'y' || spec.guides!.length <= 3) {
				const item = append(legend, $('span.fem-chart-legend-item'));
				append(item, $(`span.fem-chart-swatch.guide.${colorClass(guide.color ?? 'red')}`));
				append(item, $('span', undefined, guide.label));
			}
		}
	}
	if (spec.caption) {
		append(figure, $('figcaption.fem-chart-caption', undefined, spec.caption));
	}
	return figure;
}
