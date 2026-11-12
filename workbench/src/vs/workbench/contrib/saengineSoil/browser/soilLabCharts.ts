/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber, IConsolidationPoint, IShearSpecimen, ISieve, ITriaxialSpecimen } from './soilDocument.js';
import { FINES_SIZE, IShearResult } from './soilLabTests.js';
import { niceStep, svg } from './soilLog.js';

/*
 * The charts of the lab tests, as plain SVG like the borehole log (soilLog.ts): the grain size
 * curve, the e–log p curve of the oedometer, and the Mohr-Coulomb line of the shear tests. The
 * colours are CSS classes over the theme's tokens (soilEditor.css).
 */

interface IFrame {
	readonly width: number;
	readonly height: number;
	readonly left: number;
	readonly right: number;
	readonly top: number;
	readonly bottom: number;
}

const FRAME: IFrame = { width: 380, height: 240, left: 46, right: 14, top: 14, bottom: 38 };

function chartRoot(container: HTMLElement, label: string, frame: IFrame = FRAME): SVGSVGElement {
	const root = svg(container, 'svg', { width: frame.width, height: frame.height, viewBox: `0 0 ${frame.width} ${frame.height}`, class: 'soil-lab-chart', role: 'img', 'aria-label': label });
	svg(root, 'rect', { x: frame.left, y: frame.top, width: frame.width - frame.left - frame.right, height: frame.height - frame.top - frame.bottom, class: 'soil-chart-frame' });
	return root;
}

function axisLabels(root: SVGSVGElement, x: string, y: string, frame: IFrame = FRAME): void {
	svg(root, 'text', { x: (frame.left + frame.width - frame.right) / 2, y: frame.height - 6, class: 'soil-heading', 'text-anchor': 'middle' }, x);
	svg(root, 'text', { x: 12, y: (frame.top + frame.height - frame.bottom) / 2, class: 'soil-heading', 'text-anchor': 'middle', transform: `rotate(-90 12 ${(frame.top + frame.height - frame.bottom) / 2})` }, y);
}

/** The grain size curve: percent passing against the size on a log scale, coarse to the left. */
export function renderGrainSizeChart(container: HTMLElement, sieves: readonly ISieve[]): SVGSVGElement {
	const f = FRAME;
	const root = chartRoot(container, localize('soil.chart.grain', "Grain size distribution curve"));
	const valid = sieves.filter(s => Number.isFinite(s.size) && s.size > 0 && Number.isFinite(s.passing)).sort((a, b) => b.size - a.size);
	const maxLog = Math.max(2, Math.ceil(Math.log10(Math.max(...valid.map(s => s.size), 1))));
	const minLog = Math.min(-3, Math.floor(Math.log10(Math.min(...valid.map(s => s.size), 1))));
	const x = (size: number) => f.left + (maxLog - Math.log10(size)) / (maxLog - minLog) * (f.width - f.left - f.right);
	const y = (passing: number) => f.top + (100 - Math.max(0, Math.min(100, passing))) / 100 * (f.height - f.top - f.bottom);
	for (let p = 0; p <= 100; p += 20) {
		svg(root, 'line', { x1: f.left, x2: f.width - f.right, y1: y(p), y2: y(p), class: 'soil-grid' });
		svg(root, 'text', { x: f.left - 4, y: y(p) + 4, class: 'soil-tick', 'text-anchor': 'end' }, String(p));
	}
	for (let e = minLog; e <= maxLog; e++) {
		const size = Math.pow(10, e);
		svg(root, 'line', { x1: x(size), x2: x(size), y1: f.top, y2: f.height - f.bottom, class: 'soil-grid' });
		svg(root, 'text', { x: x(size), y: f.height - f.bottom + 14, class: 'soil-tick', 'text-anchor': 'middle' }, formatNumber(size, 3));
		for (let k = 2; k < 10 && e < maxLog; k++) {
			svg(root, 'line', { x1: x(k * size), x2: x(k * size), y1: f.top, y2: f.height - f.bottom, class: 'soil-grid minor' });
		}
	}
	svg(root, 'line', { x1: x(FINES_SIZE), x2: x(FINES_SIZE), y1: f.top, y2: f.height - f.bottom, class: 'soil-fines-line' });
	svg(root, 'text', { x: x(FINES_SIZE) + 3, y: f.top + 11, class: 'soil-fines-label' }, localize('soil.chart.fines', "75 µm"));
	if (valid.length > 1) {
		svg(root, 'polyline', { points: valid.map(s => `${x(s.size).toFixed(1)},${y(s.passing).toFixed(1)}`).join(' '), class: 'soil-lab-line' });
	}
	for (const s of valid) {
		const mark = svg(root, 'circle', { cx: x(s.size), cy: y(s.passing), r: 3, class: 'soil-lab-point' });
		svg(mark, 'title', {}, localize('soil.chart.sieve', "{0} mm: {1}% passing", formatNumber(s.size, 4), formatNumber(s.passing, 1)));
	}
	if (!valid.length) {
		svg(root, 'text', { x: (f.left + f.width - f.right) / 2, y: (f.top + f.height - f.bottom) / 2, class: 'soil-muted', 'text-anchor': 'middle' }, localize('soil.chart.noSieves', "Enter or paste the sieves"));
	}
	axisLabels(root, localize('soil.chart.size', "Particle size (mm)"), localize('soil.chart.passing', "Passing (%)"));
	return root;
}

/** The void ratio against the effective pressure on a log scale, in the order of the load steps. */
export function renderConsolidationChart(container: HTMLElement, points: readonly IConsolidationPoint[]): SVGSVGElement {
	const f = FRAME;
	const root = chartRoot(container, localize('soil.chart.elogp', "Void ratio against log pressure"));
	const valid = points.filter(p => Number.isFinite(p.pressure) && p.pressure > 0 && Number.isFinite(p.e));
	const minLog = Math.floor(Math.log10(Math.min(...valid.map(p => p.pressure), 10)));
	const maxLog = Math.max(minLog + 1, Math.ceil(Math.log10(Math.max(...valid.map(p => p.pressure), 1000))));
	const es = valid.map(p => p.e);
	const step = niceStep(Math.max(0.1, (Math.max(...es, 1) - Math.min(...es, 0.5))), 5);
	const eMin = Math.floor(Math.min(...es, 0.5) / step) * step;
	const eMax = Math.ceil(Math.max(...es, 1) / step) * step;
	const x = (p: number) => f.left + (Math.log10(p) - minLog) / (maxLog - minLog) * (f.width - f.left - f.right);
	const y = (e: number) => f.top + (eMax - e) / (eMax - eMin) * (f.height - f.top - f.bottom);
	for (let e = eMin; e <= eMax + 1e-9; e += step) {
		svg(root, 'line', { x1: f.left, x2: f.width - f.right, y1: y(e), y2: y(e), class: 'soil-grid' });
		svg(root, 'text', { x: f.left - 4, y: y(e) + 4, class: 'soil-tick', 'text-anchor': 'end' }, formatNumber(e, 2));
	}
	for (let k = minLog; k <= maxLog; k++) {
		const p = Math.pow(10, k);
		svg(root, 'line', { x1: x(p), x2: x(p), y1: f.top, y2: f.height - f.bottom, class: 'soil-grid' });
		svg(root, 'text', { x: x(p), y: f.height - f.bottom + 14, class: 'soil-tick', 'text-anchor': 'middle' }, formatNumber(p, 0));
	}
	if (valid.length > 1) {
		svg(root, 'polyline', { points: valid.map(p => `${x(p.pressure).toFixed(1)},${y(p.e).toFixed(1)}`).join(' '), class: 'soil-lab-line' });
	}
	for (const p of valid) {
		const mark = svg(root, 'circle', { cx: x(p.pressure), cy: y(p.e), r: 3, class: 'soil-lab-point' });
		svg(mark, 'title', {}, localize('soil.chart.step', "{0} kPa: e {1}", formatNumber(p.pressure, 1), formatNumber(p.e, 3)));
	}
	if (!valid.length) {
		svg(root, 'text', { x: (f.left + f.width - f.right) / 2, y: (f.top + f.height - f.bottom) / 2, class: 'soil-muted', 'text-anchor': 'middle' }, localize('soil.chart.noSteps', "Enter or paste the load steps"));
	}
	axisLabels(root, localize('soil.chart.pressure', "Effective pressure σ′v (kPa)"), localize('soil.chart.voidRatio', "Void ratio e"));
	return root;
}

/**
 * The shear tests on the τ–σ plane: the direct shear specimens as points, the triaxial ones as
 * Mohr circles (effective for CU and CD), and the Mohr-Coulomb line of the result.
 */
export function renderShearChart(container: HTMLElement, data: { readonly direct?: readonly IShearSpecimen[]; readonly triaxial?: readonly ITriaxialSpecimen[]; readonly type?: 'UU' | 'CU' | 'CD' }, result: IShearResult): SVGSVGElement {
	const f = FRAME;
	const root = chartRoot(container, localize('soil.chart.shear', "Shear strength: Mohr-Coulomb line"));
	const circles = (data.triaxial ?? []).filter(s => Number.isFinite(s.cell) && Number.isFinite(s.deviator) && s.deviator > 0).map(s => {
		const u = data.type === 'CU' && typeof s.porePressure === 'number' ? s.porePressure : 0;
		const s3 = data.type === 'UU' ? s.cell : s.cell - u;
		return { s3, s1: s3 + s.deviator };
	});
	const points = (data.direct ?? []).filter(s => Number.isFinite(s.normal) && Number.isFinite(s.shear));
	const maxSigma = Math.max(100, ...points.map(p => p.normal), ...circles.map(c => c.s1)) * 1.1;
	const maxTau = Math.max(50, ...points.map(p => p.shear), ...circles.map(c => (c.s1 - c.s3) / 2)) * 1.2;
	// One scale for both axes, so the circles are round.
	const scale = Math.min((f.width - f.left - f.right) / maxSigma, (f.height - f.top - f.bottom) / maxTau);
	const x = (sigma: number) => f.left + sigma * scale;
	const y = (tau: number) => f.height - f.bottom - tau * scale;
	const sigmaStep = niceStep(maxSigma, 6);
	for (let s = 0; x(s) <= f.width - f.right + 1e-6; s += sigmaStep) {
		svg(root, 'line', { x1: x(s), x2: x(s), y1: f.top, y2: f.height - f.bottom, class: 'soil-grid' });
		svg(root, 'text', { x: x(s), y: f.height - f.bottom + 14, class: 'soil-tick', 'text-anchor': 'middle' }, formatNumber(s, 0));
	}
	for (let t = 0; y(t) >= f.top - 1e-6; t += sigmaStep) {
		svg(root, 'line', { x1: f.left, x2: f.width - f.right, y1: y(t), y2: y(t), class: 'soil-grid' });
		svg(root, 'text', { x: f.left - 4, y: y(t) + 4, class: 'soil-tick', 'text-anchor': 'end' }, formatNumber(t, 0));
	}
	for (const c of circles) {
		const r = (c.s1 - c.s3) / 2 * scale;
		svg(root, 'path', { d: `M${x(c.s3).toFixed(1)} ${y(0).toFixed(1)} A${r.toFixed(1)} ${r.toFixed(1)} 0 0 1 ${x(c.s1).toFixed(1)} ${y(0).toFixed(1)}`, class: 'soil-mohr' });
	}
	for (const p of points) {
		const mark = svg(root, 'circle', { cx: x(p.normal), cy: y(p.shear), r: 3, class: 'soil-lab-point' });
		svg(mark, 'title', {}, localize('soil.chart.shearPoint', "σn {0} kPa: τ {1} kPa", formatNumber(p.normal, 1), formatNumber(p.shear, 1)));
	}
	if (typeof result.c === 'number' && typeof result.phi === 'number') {
		const tan = Math.tan(result.phi * Math.PI / 180);
		const end = (f.width - f.right - f.left) / scale;
		svg(root, 'line', { x1: x(0), y1: y(result.c), x2: x(end), y2: y(result.c + end * tan), class: 'soil-envelope' });
	} else if (typeof result.cu === 'number') {
		svg(root, 'line', { x1: x(0), y1: y(result.cu), x2: f.width - f.right, y2: y(result.cu), class: 'soil-envelope' });
	}
	if (!circles.length && !points.length) {
		svg(root, 'text', { x: (f.left + f.width - f.right) / 2, y: (f.top + f.height - f.bottom) / 2, class: 'soil-muted', 'text-anchor': 'middle' }, localize('soil.chart.noSpecimens', "Enter or paste the specimens"));
	}
	axisLabels(root, localize('soil.chart.sigma', "Normal stress σ (kPa)"), localize('soil.chart.tau', "Shear stress τ (kPa)"));
	return root;
}
