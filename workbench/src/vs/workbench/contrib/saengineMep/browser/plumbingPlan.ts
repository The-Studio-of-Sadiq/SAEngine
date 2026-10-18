/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { IMep, IMepContext, Point } from './mepDocument.js';
import type { IPlanView, MepSelection } from './mepPlan.js';
import { IPlumbingReport, isGroundTank, plumbingOf, riserOnStory, systemLabel, systemLetters, tankCapacity, tankKindLabel, tankOutline, tankStory } from './plumbingDocument.js';

/*
 * The plumbing drawn over the plan of one story (mepPlan.ts draws the building first): the
 * risers and stacks as lettered symbols in their system's colour, the tanks as footprints (an
 * overhead tank on its story, the tanks in the ground on the lowest story's plan), the roof
 * drains with their catchments (from the report). Interactive parts carry `data-riser`,
 * `data-tank` or `data-drain` (indexes into the plumbing's lists).
 */

export interface IPlumbingPlanOptions {
	readonly story: string;
	readonly selection?: MepSelection;
	readonly report?: IPlumbingReport;
}

function selected(selection: MepSelection | undefined, kind: 'riser' | 'tank' | 'drain', index: number): boolean {
	return selection?.kind === kind && selection.index === index;
}

function polygonPoints(view: IPlanView, points: readonly Point[]): string {
	return points.map(p => `${view.x(p[0]).toFixed(1)},${view.y(p[1]).toFixed(1)}`).join(' ');
}

/** The plan points the plumbing of `story` needs in view (tanks beside the building, risers, drains). */
export function plumbingExtent(document: IMep, context: IMepContext, story: string): Point[] {
	const plumbing = plumbingOf(document);
	if (!plumbing) {
		return [];
	}
	return [
		...plumbing.tanks.filter(t => tankStory(t, context) === story).flatMap(tankOutline),
		...plumbing.risers.filter(r => riserOnStory(r, context, story)).map(r => [r.x, r.y] as Point),
		...plumbing.roof.drains.filter(d => d.story === story).map(d => [d.x, d.y] as Point),
	];
}

/** Draws the plumbing of `options.story` into the plan's svg. */
export function renderPlumbing(root: SVGElement, view: IPlanView, document: IMep, context: IMepContext, options: IPlumbingPlanOptions): void {
	const plumbing = plumbingOf(document);
	if (!plumbing) {
		return;
	}
	const { story, selection, report } = options;
	const layer = svg(root, 'g', { class: 'plb-layer' });

	// Catchments of the roof drains (the report's split of the roof), under everything.
	const drainsHere = new Set(plumbing.roof.drains.filter(d => d.story === story).map(d => d.id));
	for (const catchment of report?.catchments ?? []) {
		if (drainsHere.has(catchment.drain) && catchment.outline.length >= 3) {
			const group = svg(layer, 'g', { class: 'plb-catchment' });
			svg(group, 'title', {}, localize('plb.catchmentTitle', "Catchment of {0}: {1} m²", catchment.drain, catchment.area === undefined ? '?' : formatNumber(catchment.area, 1)));
			svg(group, 'polygon', { points: polygonPoints(view, catchment.outline), class: 'plb-catchment-shape' });
		}
	}

	// Tanks: footprints with the inside outlined, id and capacity.
	plumbing.tanks.forEach((tank, index) => {
		if (tankStory(tank, context) !== story) {
			return;
		}
		const outline = tankOutline(tank);
		const group = svg(layer, 'g', { class: `plb-tank kind-${tank.kind}${isGroundTank(tank) ? ' ground' : ''}${tank.sized ? ' sized' : ''}${selected(selection, 'tank', index) ? ' selected' : ''}`, 'data-tank': index });
		const capacity = tankCapacity(tank);
		svg(group, 'title', {}, `${tank.id} · ${tankKindLabel(tank.kind)}${capacity === undefined ? '' : ` · ${formatNumber(capacity, 1)} m³`}`);
		svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'plb-tank-shape' });
		if (tank.kind !== 'soakWell') {
			const inside = tankOutline({ ...tank, walls: 0 });
			svg(group, 'polygon', { points: polygonPoints(view, inside), class: 'plb-tank-inside' });
			// Compartments: the inside divided along its length.
			const parts = Math.max(1, Math.min(6, Math.round(tank.compartments ?? 1)));
			for (let i = 1; i < parts; i++) {
				const x = inside[0][0] + (inside[1][0] - inside[0][0]) * i / parts;
				svg(group, 'line', { x1: view.x(x), y1: view.y(inside[0][1]), x2: view.x(x), y2: view.y(inside[2][1]), class: 'plb-tank-baffle' });
			}
		}
		const cx = view.x(tank.x);
		const cy = view.y(tank.y);
		svg(group, 'text', { x: cx, y: cy - 1, class: 'plb-tank-label', 'text-anchor': 'middle' }, tank.id);
		if (capacity !== undefined) {
			svg(group, 'text', { x: cx, y: cy + 11, class: 'plb-tank-capacity', 'text-anchor': 'middle' }, localize('plb.m3Value', "{0} m³", formatNumber(capacity, 1)));
		}
		const top = Math.min(...outline.map(p => view.y(p[1])));
		const left = Math.min(...outline.map(p => view.x(p[0])));
		svg(group, 'text', { x: left, y: top - 4, class: 'plb-tank-name' }, tankKindLabel(tank.kind));
	});

	// Roof drains: a small square with a cross.
	plumbing.roof.drains.forEach((drain, index) => {
		if (drain.story !== story) {
			return;
		}
		const x = view.x(drain.x);
		const y = view.y(drain.y);
		const group = svg(layer, 'g', { class: `plb-drain${selected(selection, 'drain', index) ? ' selected' : ''}`, 'data-drain': index });
		svg(group, 'title', {}, localize('plb.drainTitle', "Roof drain {0}", drain.id));
		svg(group, 'rect', { x: x - 7, y: y - 7, width: 14, height: 14, class: 'plb-drain-shape' });
		svg(group, 'path', { d: `M${x - 4} ${y - 4}L${x + 4} ${y + 4}M${x + 4} ${y - 4}L${x - 4} ${y + 4}`, class: 'plb-drain-cross' });
		svg(group, 'text', { x: x + 10, y: y - 9, class: 'plb-label' }, drain.id);
	});

	// Risers and stacks: a circle in the system's colour with its letters.
	plumbing.risers.forEach((riser, index) => {
		if (!riserOnStory(riser, context, story)) {
			return;
		}
		const x = view.x(riser.x);
		const y = view.y(riser.y);
		const status = report?.risers.find(r => r.id === riser.id)?.status;
		const group = svg(layer, 'g', { class: `plb-riser sys-${riser.system}${status === 'fail' ? ' failed' : ''}${selected(selection, 'riser', index) ? ' selected' : ''}`, 'data-riser': index });
		const size = riser.diameter ?? report?.risers.find(r => r.id === riser.id)?.diameter;
		svg(group, 'title', {}, `${riser.id} · ${systemLabel(riser.system)}${size ? ` · Ø${formatNumber(size, 0)} mm` : ''}`);
		svg(group, 'circle', { cx: x, cy: y, r: 11, class: 'plb-riser-shape' });
		svg(group, 'text', { x, y: y + 3.5, class: 'plb-riser-letters', 'text-anchor': 'middle' }, systemLetters(riser.system));
		svg(group, 'text', { x: x + 14, y: y - 10, class: 'plb-label' }, riser.id);
	});
}
