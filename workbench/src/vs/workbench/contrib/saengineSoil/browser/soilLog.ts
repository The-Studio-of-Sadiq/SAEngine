/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { boreholeDepth, boreholeGround, formatNumber, IBorehole, IBoreholeResult, ISoilReport, SOIL_TYPES, SoilType, soilTypeLabel, terminationDepth } from './soilDocument.js';
import { sptBlows } from './soilSheet.js';

/*
 * The drawings of the soil report, as plain SVG (no chart library): the borehole log (depth
 * axis, strata column with a hatch per soil type, water table, descriptions, SPT N and N60
 * against depth), the fence of all boreholes side by side on the project datum, and the
 * liquefaction factor of safety against depth. Colours are CSS classes (soilEditor.css) over
 * the theme's tokens, so the drawings follow light and dark themes.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const XHTML_NS = 'http://www.w3.org/1999/xhtml';

/** The height of one line of a layer's description in the log [px] (12 px text, 1.35 line height). */
const DESCRIPTION_LINE = 16;

type Attributes = { readonly [name: string]: string | number | undefined };

/** Creates an SVG element in `parent`'s document and appends it. */
export function svg<K extends keyof SVGElementTagNameMap>(parent: Element, tag: K, attributes: Attributes = {}, text?: string): SVGElementTagNameMap[K] {
	const element = parent.ownerDocument.createElementNS(SVG_NS, tag);
	for (const [name, value] of Object.entries(attributes)) {
		if (value !== undefined) {
			element.setAttribute(name, String(value));
		}
	}
	if (text !== undefined) {
		element.textContent = text;
	}
	parent.appendChild(element);
	return element;
}

/** The ids of the hatch patterns of one editor (see {@link appendSoilPatterns}). */
export function patternId(prefix: string, type: SoilType | string): string {
	return `${prefix}-${SOIL_TYPES.includes(type as SoilType) ? type : 'fill'}`;
}

/**
 * The hatch patterns of the soil types, in a hidden SVG that the logs, the fence and the legend
 * of one editor refer to by id (`url(#<prefix>-clay)`).
 */
export function appendSoilPatterns(container: HTMLElement, prefix: string): SVGSVGElement {
	const root = svg(container, 'svg', { width: 0, height: 0, 'aria-hidden': 'true', class: 'soil-patterns' });
	const defs = svg(root, 'defs');
	for (const type of SOIL_TYPES) {
		const size = type === 'rock' ? 16 : type === 'gravel' ? 12 : 8;
		const pattern = svg(defs, 'pattern', { id: patternId(prefix, type), width: size, height: size, patternUnits: 'userSpaceOnUse' });
		svg(pattern, 'rect', { width: size, height: size, class: `soil-bg soil-bg-${type}` });
		const hatch = (tag: 'path' | 'circle', attributes: Attributes) => svg(pattern, tag, { ...attributes, class: 'soil-hatch' });
		switch (type) {
			case 'clay':
				hatch('path', { d: 'M0 2H8M0 6H8' });
				break;
			case 'silt':
				hatch('path', { d: 'M0 2H3M5 6H8M0 6H1', 'stroke-dasharray': '3 2' });
				break;
			case 'sand':
				hatch('circle', { cx: 2, cy: 2, r: 0.7 });
				hatch('circle', { cx: 6, cy: 6, r: 0.7 });
				break;
			case 'gravel':
				hatch('circle', { cx: 3.5, cy: 3.5, r: 2.2 });
				hatch('circle', { cx: 9.5, cy: 9, r: 1.6 });
				break;
			case 'organic':
				hatch('path', { d: 'M1 6L2.5 3L4 6M5 2.5H8' });
				break;
			case 'fill':
				hatch('path', { d: 'M0 8L8 0M0 0L8 8' });
				break;
			case 'rock':
				hatch('path', { d: 'M0 4H16M0 12H16M4 0V4M12 4V12M4 12V16' });
				break;
		}
	}
	return root;
}

/** A small swatch of a soil type's fill, for the legend. */
export function appendSoilSwatch(container: HTMLElement, prefix: string, type: SoilType): SVGSVGElement {
	const root = svg(container, 'svg', { width: 18, height: 12, class: 'soil-swatch', 'aria-hidden': 'true' });
	svg(root, 'rect', { x: 0.5, y: 0.5, width: 17, height: 11, fill: `url(#${patternId(prefix, type)})`, class: 'soil-stratum' });
	return root;
}

/** A round step for an axis: 1, 2 or 5 times a power of ten, so that `range` has about `count` steps. */
export function niceStep(range: number, count: number): number {
	if (!(range > 0) || !(count > 0)) {
		return 1;
	}
	const raw = range / count;
	const power = Math.pow(10, Math.floor(Math.log10(raw)));
	const fraction = raw / power;
	return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
}

/** Tick labels of the depth axis stay at least this far apart [px]. */
const DEPTH_TICK_SPACING = 40;

/** A log keeps at least this many px per m, so a deep borehole (75 m, 150 m) grows and scrolls. */
const MIN_PX_PER_M = 16;

export interface IDepthScale {
	/** The depth the axis runs to [m]: the borehole's, rounded up to a round step. */
	readonly maxM: number;
	/** px per m. */
	readonly scale: number;
	/** The step of the depth ticks [m]. */
	readonly step: number;
}

/**
 * The depth scale of a log: it fills `height` px, or grows past it at {@link MIN_PX_PER_M} for a
 * deep borehole (no depth limit), with round ticks as close as the space allows.
 */
export function depthScale(depthMm: number, height: number): IDepthScale {
	const depthM = Math.max(1, depthMm / 1000);
	const round = niceStep(depthM, 10);
	const maxM = Math.ceil(depthM / round - 1e-9) * round;
	const scale = Math.max(MIN_PX_PER_M, height / maxM);
	const step = niceStep(maxM, Math.max(2, maxM * scale / DEPTH_TICK_SPACING));
	return { maxM, scale, step };
}

/** A depth in m from mm, for labels. */
function m(value: number): string {
	return formatNumber(value / 1000, 2);
}

export interface ILogOptions {
	readonly width: number;
	/** The height the log should fill; deep boreholes get taller and scroll. */
	readonly height: number;
	readonly patternPrefix: string;
	/** What the backend computed for the borehole (N60 is drawn when given). */
	readonly result?: IBoreholeResult;
	/** The depth the log reaches [mm], so several logs share a scale. */
	readonly maxDepth?: number;
	/** The design hammer energy, to label N60. */
	readonly hammerEnergy?: number;
	/** The narrow log beside the log sheet: the strata and the SPT, the descriptions left to the sheet. */
	readonly compact?: boolean;
}

/** The graphical log of one borehole. */
export function renderBoreholeLog(container: HTMLElement, report: ISoilReport, borehole: IBorehole, options: ILogOptions): SVGSVGElement {
	const top = 34;
	const bottom = 20;
	const axisWidth = 46;
	const columnX = axisWidth + 20;
	const columnWidth = options.compact ? 44 : 58;
	const width = Math.max(options.compact ? 240 : 480, options.width);
	const chartWidth = options.compact ? width - columnX - columnWidth - 40 : Math.round(Math.max(170, Math.min(300, options.width * 0.32)));
	const chartX = width - chartWidth - 16;
	const descriptionX = columnX + columnWidth + 14;
	const descriptionWidth = options.compact ? 0 : Math.max(80, chartX - descriptionX - 24);

	const { maxM, scale, step: depthStep } = depthScale(options.maxDepth ?? boreholeDepth(borehole), options.height - top - bottom);
	const height = Math.round(top + maxM * scale + bottom);
	const y = (depth: number) => top + depth / 1000 * scale;

	const root = svg(container, 'svg', {
		width, height, viewBox: `0 0 ${width} ${height}`, class: 'soil-log', role: 'img',
		'aria-label': localize('soil.log.aria', "Borehole log of {0}, {1} m deep", borehole.id, m(boreholeDepth(borehole))),
	});

	// Headers.
	svg(root, 'text', { x: axisWidth, y: 14, class: 'soil-heading', 'text-anchor': 'end' }, localize('soil.log.depth', "Depth (m)"));
	svg(root, 'text', { x: columnX + columnWidth / 2, y: 14, class: 'soil-heading', 'text-anchor': 'middle' }, localize('soil.log.strata', "Strata"));
	if (!options.compact) {
		svg(root, 'text', { x: descriptionX, y: 14, class: 'soil-heading' }, localize('soil.log.description', "Description"));
	}

	// Depth axis and the grid across the log.
	for (let d = 0; d <= maxM + 1e-9; d += depthStep) {
		const yy = y(d * 1000);
		svg(root, 'line', { x1: axisWidth + 2, x2: width - 16, y1: yy, y2: yy, class: 'soil-grid' });
		svg(root, 'text', { x: axisWidth - 2, y: yy + 4, class: 'soil-tick', 'text-anchor': 'end' }, formatNumber(d, 1));
	}
	svg(root, 'line', { x1: axisWidth + 2, x2: axisWidth + 2, y1: top, y2: y(maxM * 1000), class: 'soil-axis' });

	// Strata with their descriptions. A layer too thin for its text gets one line, pushed down
	// below the label above it with a leader line to its layer; hovering shows the full text.
	const layers = [...borehole.layers].sort((a, b) => a.top - b.top);
	let free = top;
	for (const layer of layers) {
		const y1 = y(Math.max(0, layer.top));
		const y2 = y(Math.max(layer.top, layer.bottom));
		const label = layer.uscs ? `${soilTypeLabel(layer.soilType)} (${layer.uscs})` : soilTypeLabel(layer.soilType);
		const full = `${m(layer.top)}–${m(layer.bottom)} m  ${label}${layer.description ? `: ${layer.description}` : ''}`;
		const stratum = svg(root, 'rect', { x: columnX, y: y1, width: columnWidth, height: Math.max(0, y2 - y1), fill: `url(#${patternId(options.patternPrefix, layer.soilType)})`, class: 'soil-stratum' });
		svg(stratum, 'title', {}, full);
		if (options.compact) {
			if (layer.uscs) {
				svg(root, 'text', { x: columnX + columnWidth + 4, y: Math.min(y2 - 3, y1 + 12), class: 'soil-n-label' }, layer.uscs);
			}
			continue;
		}
		svg(root, 'line', { x1: columnX + columnWidth, x2: descriptionX - 4, y1: y2, y2, class: 'soil-boundary' });
		const thin = y2 - y1 < DESCRIPTION_LINE * (layer.description ? 2 : 1) + 4;
		const labelTop = Math.max(y1, free);
		const labelHeight = thin ? DESCRIPTION_LINE + 3 : Math.max(0, y2 - labelTop);
		if (labelTop > y1 + 1) {
			// Pushed down by the label above: a leader from the middle of its layer.
			const mid = (y1 + y2) / 2;
			svg(root, 'polyline', { points: `${columnX + columnWidth + 2},${mid} ${descriptionX - 10},${mid} ${descriptionX - 3},${labelTop + DESCRIPTION_LINE / 2 + 2}`, class: 'soil-leader' });
		}
		free = labelTop + labelHeight;
		const box = svg(root, 'foreignObject', { x: descriptionX, y: labelTop, width: descriptionWidth, height: labelHeight });
		const text = root.ownerDocument.createElementNS(XHTML_NS, 'div') as HTMLDivElement;
		text.className = thin ? 'soil-description thin' : 'soil-description';
		text.title = full;
		const strong = root.ownerDocument.createElementNS(XHTML_NS, 'span') as HTMLSpanElement;
		strong.className = 'soil-description-type';
		strong.textContent = thin && layer.description ? `${m(layer.top)}–${m(layer.bottom)} m  ${label}: ${layer.description}` : `${m(layer.top)}–${m(layer.bottom)} m  ${label}`;
		text.appendChild(strong);
		if (layer.description && !thin) {
			const description = root.ownerDocument.createElementNS(XHTML_NS, 'span') as HTMLSpanElement;
			description.className = 'soil-description-text';
			description.textContent = layer.description;
			text.appendChild(description);
		}
		box.appendChild(text);
	}
	if (!layers.length) {
		svg(root, 'text', { x: options.compact ? axisWidth + 8 : descriptionX, y: top + 18, class: 'soil-muted' }, localize('soil.log.noLayers', "No layers yet: add them with Edit Borehole."));
	}
	// The termination depth as logged; layers drawn below it are marked as a problem.
	const termination = terminationDepth(borehole);
	if (termination > 0) {
		const deeper = layers.some(l => l.bottom > termination + 1);
		const mark = svg(root, 'line', { x1: columnX - 6, x2: columnX + columnWidth + 6, y1: y(termination), y2: y(termination), class: deeper ? 'soil-termination problem' : 'soil-termination' });
		svg(mark, 'title', {}, deeper
			? localize('soil.log.terminationProblem', "Termination depth {0} m: the layers go below it. Correct the termination depth or the layers.", m(termination))
			: localize('soil.log.termination', "Termination depth {0} m", m(termination)));
		if (deeper && !options.compact) {
			// Right of the strata column: the depth axis has its own ticks on the left.
			svg(root, 'text', { x: columnX + columnWidth + 8, y: y(termination) - 4, class: 'soil-termination-label' }, localize('soil.log.terminationShort', "end {0} m", m(termination)));
		}
	}

	// Water table: a line across the strata column with the ▽ mark.
	if (typeof borehole.waterTable === 'number') {
		const yy = y(borehole.waterTable);
		const group = svg(root, 'g', { class: 'soil-water' });
		svg(group, 'line', { x1: columnX - 4, x2: columnX + columnWidth + 4, y1: yy, y2: yy });
		svg(group, 'path', { d: `M${columnX - 16} ${yy - 8}h10l-5 7z` });
		svg(group, 'title', {}, localize('soil.log.waterTitle', "Water table {0} m below ground", m(borehole.waterTable)));
	}

	// SPT N (and N60 from the results) against depth.
	const spt = borehole.spt.map(s => ({ depth: s.depth, N: sptBlows(s), refusal: !!s.refusal }))
		.filter((s): s is { depth: number; N: number; refusal: boolean } => Number.isFinite(s.depth) && typeof s.N === 'number')
		.sort((a, b) => a.depth - b.depth);
	const results = (options.result?.spt ?? []).filter(s => typeof s.N60 === 'number').sort((a, b) => a.depth - b.depth);
	const maxN = Math.max(50, ...spt.map(s => s.N), ...results.map(s => s.N60!));
	const nMax = Math.ceil(maxN / 10) * 10;
	const x = (n: number) => chartX + Math.min(n, nMax) / nMax * chartWidth;
	svg(root, 'text', { x: chartX + chartWidth / 2, y: 14, class: 'soil-heading', 'text-anchor': 'middle' }, localize('soil.log.spt', "SPT N (blows/300 mm)"));
	svg(root, 'rect', { x: chartX, y: top, width: chartWidth, height: y(maxM * 1000) - top, class: 'soil-chart-frame' });
	const nStep = nMax <= 50 ? 10 : niceStep(nMax, 5);
	for (let n = 0; n <= nMax; n += nStep) {
		svg(root, 'line', { x1: x(n), x2: x(n), y1: top, y2: y(maxM * 1000), class: 'soil-grid' });
		svg(root, 'text', { x: x(n), y: top - 6, class: 'soil-tick', 'text-anchor': 'middle' }, String(n));
	}
	const polyline = (points: readonly { readonly depth: number; readonly value: number }[], klass: string) => {
		if (points.length > 1) {
			svg(root, 'polyline', { points: points.map(p => `${x(p.value).toFixed(1)},${y(p.depth).toFixed(1)}`).join(' '), class: klass });
		}
	};
	polyline(results.map(s => ({ depth: s.depth, value: s.N60! })), 'soil-n60-line');
	polyline(spt.map(s => ({ depth: s.depth, value: s.N })), 'soil-n-line');
	for (const s of results) {
		const mark = svg(root, 'rect', { x: x(s.N60!) - 3, y: y(s.depth) - 3, width: 6, height: 6, class: 'soil-n60' });
		svg(mark, 'title', {}, localize('soil.log.n60Title', "N60 {0} at {1} m", formatNumber(s.N60!, 1), m(s.depth)));
	}
	for (const s of spt) {
		const mark = svg(root, 'circle', { cx: x(s.N), cy: y(s.depth), r: 3.5, class: s.N > nMax || s.refusal ? 'soil-n refusal' : 'soil-n' });
		svg(mark, 'title', {}, s.refusal ? localize('soil.log.nRefusalTitle', "N {0} at {1} m (refusal)", s.N, m(s.depth)) : localize('soil.log.nTitle', "N {0} at {1} m", s.N, m(s.depth)));
		svg(root, 'text', { x: x(s.N) + 7, y: y(s.depth) + 4, class: 'soil-n-label' }, s.refusal ? localize('soil.log.nRefusal', "{0} R", s.N) : String(s.N));
	}
	if (!spt.length) {
		svg(root, 'text', { x: chartX + 8, y: top + 18, class: 'soil-muted' }, localize('soil.log.noSpt', "No SPT records"));
	}
	return root;
}

export interface IFenceOptions {
	readonly width: number;
	readonly height: number;
	readonly patternPrefix: string;
	/** The selected borehole's index in the report. */
	readonly selected?: number;
	readonly onSelect?: (index: number) => void;
}

/** All boreholes side by side on the project datum, with matching strata and the water table joined. */
export function renderFence(container: HTMLElement, report: ISoilReport, options: IFenceOptions): SVGSVGElement {
	const boreholes = report.boreholes;
	const top = 40;
	const bottom = 20;
	const axisWidth = 56;
	const columnWidth = 34;
	const width = Math.max(320, options.width);
	const grounds = boreholes.map(b => boreholeGround(report, b));
	const highest = Math.max(...grounds, report.groundLevel);
	const lowest = Math.min(...boreholes.map((b, i) => grounds[i] - Math.max(1000, boreholeDepth(b))), highest - 1000);
	const step = niceStep((highest - lowest) / 1000, 10);
	const topM = Math.ceil(highest / 1000 + 0.5);
	const bottomM = Math.floor(lowest / 1000 - 0.5);
	const scale = Math.max(14, (options.height - top - bottom) / Math.max(step, topM - bottomM));
	const height = Math.round(top + (topM - bottomM) * scale + bottom);
	const y = (elevation: number) => top + (topM - elevation / 1000) * scale;
	const gap = boreholes.length > 1 ? Math.max(columnWidth + 50, (width - axisWidth - 64 - columnWidth - 24) / (boreholes.length - 1)) : 0;
	const x = (i: number) => axisWidth + 24 + i * gap;

	const root = svg(container, 'svg', {
		width: Math.max(width, x(Math.max(0, boreholes.length - 1)) + columnWidth + 24), height, class: 'soil-fence', role: 'img',
		'aria-label': localize('soil.fence.aria', "Fence diagram of {0} boreholes", boreholes.length),
	});
	svg(root, 'text', { x: axisWidth, y: 14, class: 'soil-heading', 'text-anchor': 'end' }, localize('soil.fence.elevation', "Elevation (m)"));
	for (let e = Math.ceil(bottomM / step) * step; e <= topM + 1e-9; e += step) {
		const yy = y(e * 1000);
		svg(root, 'line', { x1: axisWidth + 2, x2: root.width.baseVal.value - 16, y1: yy, y2: yy, class: 'soil-grid' });
		svg(root, 'text', { x: axisWidth - 4, y: yy + 4, class: 'soil-tick', 'text-anchor': 'end' }, formatNumber(e, 1));
	}

	// Joins between neighbours: strata boundaries of the same sequence, and the water table.
	for (let i = 0; i + 1 < boreholes.length; i++) {
		const [a, b] = [boreholes[i], boreholes[i + 1]];
		const [la, lb] = [[...a.layers].sort((p, q) => p.top - q.top), [...b.layers].sort((p, q) => p.top - q.top)];
		for (let k = 0; k < Math.min(la.length, lb.length) && la[k].soilType === lb[k].soilType; k++) {
			svg(root, 'line', { x1: x(i) + columnWidth, x2: x(i + 1), y1: y(grounds[i] - la[k].bottom), y2: y(grounds[i + 1] - lb[k].bottom), class: 'soil-join' });
		}
		if (typeof a.waterTable === 'number' && typeof b.waterTable === 'number') {
			svg(root, 'line', { x1: x(i) + columnWidth, x2: x(i + 1), y1: y(grounds[i] - a.waterTable), y2: y(grounds[i + 1] - b.waterTable), class: 'soil-water-join' });
		}
	}

	boreholes.forEach((borehole, i) => {
		const group = svg(root, 'g', { class: i === options.selected ? 'soil-fence-borehole selected' : 'soil-fence-borehole', tabindex: 0, role: 'button', 'aria-label': borehole.id });
		const ground = grounds[i];
		svg(group, 'text', { x: x(i) + columnWidth / 2, y: 16, class: 'soil-fence-id', 'text-anchor': 'middle' }, borehole.id);
		svg(group, 'text', { x: x(i) + columnWidth / 2, y: 30, class: 'soil-tick', 'text-anchor': 'middle' }, localize('soil.fence.ground', "GL {0}", formatNumber(ground / 1000, 2)));
		for (const layer of borehole.layers) {
			const y1 = y(ground - layer.top);
			const y2 = y(ground - Math.max(layer.top, layer.bottom));
			const stratum = svg(group, 'rect', { x: x(i), y: y1, width: columnWidth, height: Math.max(0, y2 - y1), fill: `url(#${patternId(options.patternPrefix, layer.soilType)})`, class: 'soil-stratum' });
			svg(stratum, 'title', {}, `${borehole.id}: ${soilTypeLabel(layer.soilType)} ${m(layer.top)}–${m(layer.bottom)} m${layer.description ? ` ${layer.description}` : ''}`);
		}
		svg(group, 'rect', { x: x(i), y: y(ground), width: columnWidth, height: Math.max(0, y(ground - boreholeDepth(borehole)) - y(ground)), class: 'soil-fence-outline' });
		if (typeof borehole.waterTable === 'number') {
			const yy = y(ground - borehole.waterTable);
			const water = svg(group, 'g', { class: 'soil-water' });
			svg(water, 'line', { x1: x(i) - 3, x2: x(i) + columnWidth + 3, y1: yy, y2: yy });
			svg(water, 'path', { d: `M${x(i) - 12} ${yy - 8}h10l-5 7z` });
		}
		for (const record of borehole.spt) {
			const n = sptBlows(record);
			if (n !== undefined) {
				svg(group, 'text', { x: x(i) + columnWidth + 4, y: y(ground - record.depth) + 4, class: 'soil-n-label' }, String(n));
			}
		}
		const onSelect = options.onSelect;
		if (onSelect) {
			group.addEventListener('click', () => onSelect(i));
			group.addEventListener('keydown', e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					onSelect(i);
				}
			});
		}
	});
	return root;
}

export interface ILiquefactionChartOptions {
	readonly width: number;
	readonly height: number;
	readonly maxDepth: number;
}

/** The liquefaction factor of safety against depth for each borehole, with the FS = 1 line. */
export function renderLiquefactionChart(container: HTMLElement, results: readonly IBoreholeResult[], options: ILiquefactionChartOptions): SVGSVGElement {
	const top = 44;
	const bottom = 34;
	const left = 46;
	const right = 16;
	const width = Math.max(260, options.width);
	const height = Math.max(200, options.height);
	const fsMax = 2;
	const step = niceStep(options.maxDepth / 1000, 8);
	const maxM = Math.max(step, Math.ceil(options.maxDepth / 1000 / step) * step);
	const x = (fs: number) => left + Math.min(fs, fsMax) / fsMax * (width - left - right);
	const y = (depth: number) => top + depth / 1000 / maxM * (height - top - bottom);
	const root = svg(container, 'svg', { width, height, class: 'soil-liquefaction', role: 'img', 'aria-label': localize('soil.liq.aria', "Factor of safety against liquefaction against depth") });

	for (let d = 0; d <= maxM + 1e-9; d += step) {
		svg(root, 'line', { x1: left, x2: width - right, y1: y(d * 1000), y2: y(d * 1000), class: 'soil-grid' });
		svg(root, 'text', { x: left - 4, y: y(d * 1000) + 4, class: 'soil-tick', 'text-anchor': 'end' }, formatNumber(d, 1));
	}
	for (let fs = 0; fs <= fsMax + 1e-9; fs += 0.5) {
		svg(root, 'line', { x1: x(fs), x2: x(fs), y1: top, y2: y(maxM * 1000), class: 'soil-grid' });
		svg(root, 'text', { x: x(fs), y: top - 8, class: 'soil-tick', 'text-anchor': 'middle' }, fs === fsMax ? `≥${formatNumber(fs, 1)}` : formatNumber(fs, 1));
	}
	svg(root, 'text', { x: (left + width - right) / 2, y: height - 8, class: 'soil-heading', 'text-anchor': 'middle' }, localize('soil.liq.fs', "Factor of safety FS = CRR / CSR"));
	svg(root, 'text', { x: 4, y: 12, class: 'soil-heading' }, localize('soil.liq.depth', "Depth (m)"));

	// Liquefiable layers behind the points.
	for (const result of results) {
		for (const band of result.liquefaction?.liquefiableLayers ?? []) {
			svg(root, 'rect', { x: left, y: y(band.top), width: width - left - right, height: Math.max(1, y(band.bottom) - y(band.top)), class: 'soil-liquefiable-band' });
		}
	}
	svg(root, 'line', { x1: x(1), x2: x(1), y1: top, y2: y(maxM * 1000), class: 'soil-fs-one' });
	svg(root, 'text', { x: x(1) + 4, y: y(maxM * 1000) - 4, class: 'soil-fs-one-label' }, 'FS = 1');

	results.forEach((result, series) => {
		const points = (result.liquefaction?.points ?? []).filter(p => typeof p.FS === 'number').sort((a, b) => a.depth - b.depth);
		const klass = `soil-series soil-series-${series % 6}`;
		if (points.length > 1) {
			svg(root, 'polyline', { points: points.map(p => `${x(p.FS!).toFixed(1)},${y(p.depth).toFixed(1)}`).join(' '), class: `${klass} line` });
		}
		for (const point of points) {
			const liquefiable = point.liquefiable ?? point.FS! < 1;
			const mark = svg(root, 'circle', { cx: x(point.FS!), cy: y(point.depth), r: 3.5, class: `${klass} point${liquefiable ? ' liquefiable' : ''}` });
			svg(mark, 'title', {}, localize('soil.liq.pointTitle', "{0} at {1} m: FS {2}", result.id, m(point.depth), formatNumber(point.FS!, 2)));
		}
	});
	return root;
}
