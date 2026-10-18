/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { findHost, hostDirection, IMep, IMepContext, Point } from './mepDocument.js';
import type { IPlanView, MepSelection } from './mepPlan.js';
import {
	capacityUnit, ductCrossings, ductDepth, ductLetters, ductOnStory, ductPlanWidth, ductSystemLabel, hvacOf, IDuct, IHvacReport, IPlant, plantKindLabel, plantLetters, plantOutline, riserInShaft,
} from './hvacDocument.js';

/*
 * The HVAC drawn over the plan of one story (mepPlan.ts draws the building first, with the beams
 * of the ceiling dashed): the plant as footprints with their letters, capacity and weight, the
 * ducts as bands as wide as they are along their runs, the riser ducts as their sections in the
 * shafts, and where a run crosses a beam of the ceiling: a ring where an opening is, a dashed
 * outline where one is still needed. Interactive parts carry `data-plant` or `data-duct`.
 */

export interface IHvacPlanOptions {
	readonly story: string;
	readonly selection?: MepSelection;
	readonly report?: IHvacReport;
}

function selected(selection: MepSelection | undefined, kind: 'plant' | 'duct', index: number): boolean {
	return selection?.kind === kind && selection.index === index;
}

function polygonPoints(view: IPlanView, points: readonly Point[]): string {
	return points.map(p => `${view.x(p[0]).toFixed(1)},${view.y(p[1]).toFixed(1)}`).join(' ');
}

function polylinePoints(view: IPlanView, points: readonly Point[]): string {
	return polygonPoints(view, points);
}

/** A duct's size in words: "600 × 300" or "Ø400". */
export function ductSizeText(duct: IDuct): string {
	return duct.shape === 'round' ? `Ø${formatNumber(ductPlanWidth(duct), 0)}` : `${formatNumber(ductPlanWidth(duct), 0)} × ${formatNumber(ductDepth(duct), 0)}`;
}

/** Draws the HVAC of `options.story` into the plan's svg. */
export function renderHvac(root: SVGElement, view: IPlanView, document: IMep, context: IMepContext, options: IHvacPlanOptions): void {
	const hvac = hvacOf(document);
	if (!hvac) {
		return;
	}
	const { story, selection, report } = options;
	const layer = svg(root, 'g', { class: 'hvac-layer' });

	// Plant footprints.
	hvac.plant.forEach((plant, index) => {
		if (plant.story !== story) {
			return;
		}
		drawPlant(layer, view, plant, index, selected(selection, 'plant', index), report?.plant.find(p => p.id === plant.id)?.status === 'fail');
	});

	// Horizontal runs: a band as wide as the duct, its axis, its label; then the crossings with the ceiling's beams.
	hvac.ducts.forEach((duct, index) => {
		if (duct.riser || duct.story !== story || duct.path.length < 2) {
			return;
		}
		const group = svg(layer, 'g', { class: `hvac-duct sys-${duct.system}${selected(selection, 'duct', index) ? ' selected' : ''}`, 'data-duct': index });
		svg(group, 'title', {}, `${duct.id} · ${ductSystemLabel(duct.system)} · ${ductSizeText(duct)} mm`);
		const points = polylinePoints(view, duct.path);
		svg(group, 'polyline', { points, class: 'mep-hit' });
		svg(group, 'polyline', { points, class: 'hvac-duct-body', 'stroke-width': Math.max(4, ductPlanWidth(duct) * view.scale) });
		svg(group, 'polyline', { points, class: 'hvac-duct-axis' });
		const [a, b] = duct.path;
		const mx = view.x((a[0] + b[0]) / 2);
		const my = view.y((a[1] + b[1]) / 2);
		const offset = Math.max(10, ductPlanWidth(duct) * view.scale / 2 + 8);
		const horizontal = Math.abs(b[0] - a[0]) >= Math.abs(b[1] - a[1]);
		svg(group, 'text', { x: horizontal ? mx : mx + offset, y: horizontal ? my - offset + 4 : my, class: 'hvac-duct-label', 'text-anchor': horizontal ? 'middle' : 'start' },
			`${duct.id} ${ductLetters(duct.system)} ${ductSizeText(duct)}`);
	});
	for (const duct of hvac.ducts) {
		if (duct.riser || duct.story !== story) {
			continue;
		}
		for (const crossing of ductCrossings(duct, document, context)) {
			const host = findHost(context, crossing.beam);
			if (host?.kind !== 'beam') {
				continue;
			}
			const x = view.x(crossing.point[0]);
			const y = view.y(crossing.point[1]);
			const group = svg(layer, 'g', { class: `hvac-crossing${crossing.opening ? ' coordinated' : ' open'}` });
			svg(group, 'title', {}, crossing.opening
				? localize('hvac.crossingOk', "{0} passes beam {1} through opening {2}", duct.id, crossing.beam, crossing.opening)
				: localize('hvac.crossingOpen', "{0} crosses beam {1} at {2} m from its start: it needs an opening (Add Duct Openings) or to run below the beam", duct.id, crossing.beam, formatNumber(crossing.distance / 1000, 2)));
			if (crossing.opening) {
				svg(group, 'circle', { cx: x, cy: y, r: 5, class: 'hvac-crossing-mark' });
				continue;
			}
			// The opening it needs: the duct's width along the beam, across the beam's width.
			const direction = hostDirection(host);
			const sin = Math.max(0.2, Math.sin(crossing.angle * Math.PI / 180));
			const half = Math.max(4, ductPlanWidth(duct) / sin / 2 * view.scale);
			const thickness = Math.max(8, host.element.width * view.scale + 6);
			const corners: [number, number][] = [[-half, -thickness / 2], [half, -thickness / 2], [half, thickness / 2], [-half, thickness / 2]]
				.map(([u, v]) => [x + u * direction[0] + v * direction[1], y - u * direction[1] + v * direction[0]]);
			svg(group, 'polygon', { points: corners.map(c => `${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(' '), class: 'hvac-crossing-shape' });
		}
	}

	// Riser ducts: their section where they pass this story.
	hvac.ducts.forEach((duct, index) => {
		if (!duct.riser || !duct.path.length || !ductOnStory(duct, context, story)) {
			return;
		}
		const [px, py] = duct.path[0];
		const shaft = riserInShaft(duct, document);
		const group = svg(layer, 'g', { class: `hvac-riser-duct sys-${duct.system}${shaft ? '' : ' unshafted'}${selected(selection, 'duct', index) ? ' selected' : ''}`, 'data-duct': index });
		svg(group, 'title', {}, `${duct.id} · ${ductSystemLabel(duct.system)} · ${ductSizeText(duct)} mm${shaft ? ` · ${shaft}` : ` · ${localize('hvac.noShaft', "not in a shaft: it needs openings through the floors")}`}`);
		const w = Math.max(8, ductPlanWidth(duct) * view.scale);
		const h = Math.max(8, ductDepth(duct) * view.scale);
		const x = view.x(px);
		const y = view.y(py);
		if (duct.shape === 'round') {
			svg(group, 'circle', { cx: x, cy: y, r: w / 2, class: 'hvac-riser-shape' });
		} else {
			svg(group, 'rect', { x: x - w / 2, y: y - h / 2, width: w, height: h, class: 'hvac-riser-shape' });
			svg(group, 'path', { d: `M${x - w / 2} ${y - h / 2}L${x + w / 2} ${y + h / 2}`, class: 'hvac-riser-diagonal' });
		}
		svg(group, 'text', { x: x + w / 2 + 4, y: y + 4, class: 'hvac-label' }, `${duct.id} ${ductLetters(duct.system)}`);
	});
}

function drawPlant(layer: SVGElement, view: IPlanView, plant: IPlant, index: number, isSelected: boolean, failed: boolean): void {
	const outline = plantOutline(plant);
	const group = svg(layer, 'g', { class: `hvac-plant kind-${plant.kind}${plant.sized ? ' sized' : ''}${failed ? ' failed' : ''}${isSelected ? ' selected' : ''}`, 'data-plant': index });
	const capacity = plant.capacity !== undefined ? `${formatNumber(plant.capacity, plant.capacity < 10 ? 2 : 0)} ${capacityUnit(plant.kind)}` : undefined;
	const weight = plant.operatingWeight !== undefined ? localize('hvac.knValue', "{0} kN", formatNumber(plant.operatingWeight, 1)) : localize('hvac.noWeight', "? kN");
	svg(group, 'title', {}, [`${plant.id} · ${plantKindLabel(plant.kind)}`, capacity, weight].filter(Boolean).join(' · '));
	svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'hvac-plant-shape' });
	const cx = view.x(plant.x);
	const cy = view.y(plant.y);
	const w = Math.abs(view.x(outline[1][0]) - view.x(outline[0][0]));
	const h = Math.abs(view.y(outline[2][1]) - view.y(outline[0][1]));
	const roomy = Math.min(w, h) >= 30;
	svg(group, 'text', { x: cx, y: roomy ? cy - 2 : cy + 4, class: 'hvac-plant-letters', 'text-anchor': 'middle' }, roomy ? plant.id : plantLetters(plant.kind));
	if (roomy) {
		svg(group, 'text', { x: cx, y: cy + 10, class: 'hvac-plant-weight', 'text-anchor': 'middle' }, weight);
	}
	const top = Math.min(...outline.map(p => view.y(p[1])));
	const left = Math.min(...outline.map(p => view.x(p[0])));
	svg(group, 'text', { x: left, y: top - 4, class: 'hvac-plant-name' }, [roomy ? plantLetters(plant.kind) : plant.id, capacity].filter(Boolean).join(' · '));
}

/**
 * The path being drawn (a duct or a tray): its points so far as a dashed band of its width; the
 * returned line follows the pointer from the last point (the editor moves it).
 */
export function renderDraft(root: SVGElement, view: IPlanView, points: readonly Point[], width: number, className: string): SVGLineElement | undefined {
	const group = svg(root, 'g', { class: `mep-draft ${className}` });
	if (points.length >= 2) {
		svg(group, 'polyline', { points: polylinePoints(view, points), class: 'mep-draft-body', 'stroke-width': Math.max(4, width * view.scale) });
	}
	for (const p of points) {
		svg(group, 'circle', { cx: view.x(p[0]), cy: view.y(p[1]), r: 3.5, class: 'mep-draft-point' });
	}
	const last = points[points.length - 1];
	if (!last) {
		return undefined;
	}
	return svg(group, 'line', { x1: view.x(last[0]), y1: view.y(last[1]), x2: view.x(last[0]), y2: view.y(last[1]), class: 'mep-draft-rubber' }) as SVGLineElement;
}
