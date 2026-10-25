/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { IMep, IMepContext, Point } from './mepDocument.js';
import type { IPlanView, MepSelection } from './mepPlan.js';
import { num } from './mepRead.js';
import { tankOutline } from './plumbingDocument.js';
import { fireOf, fireRiserLabel, fireRiserLetters, fireRiserOnStory, firePumpLabel, firePumpLetters, fireTankStory, IFireReport, pumpOutline } from './fireDocument.js';

/*
 * The fire protection drawn over the plan of one story: the pump room's outline, the fire tanks
 * (an overhead one on its story, a ground one on the lowest), the pump sets as footprints with
 * their letters, duty and weight, the fire mains along their runs and the risers as rings with
 * their letters (SP standpipe, SR sprinkler, CR combined). Interactive parts carry
 * `data-fire-riser`, `data-fire-pump` or `data-fire-tank`.
 */

export interface IFirePlanOptions {
	readonly story: string;
	readonly selection?: MepSelection;
	readonly report?: IFireReport;
}

function selected(selection: MepSelection | undefined, kind: 'fireRiser' | 'firePump' | 'fireTank', index: number): boolean {
	return selection?.kind === kind && selection.index === index;
}

function polygonPoints(view: IPlanView, points: readonly Point[]): string {
	return points.map(p => `${view.x(p[0]).toFixed(1)},${view.y(p[1]).toFixed(1)}`).join(' ');
}

/** Draws the fire protection of `options.story` into the plan's svg. */
export function renderFire(root: SVGElement, view: IPlanView, document: IMep, context: IMepContext, options: IFirePlanOptions): void {
	const fire = fireOf(document);
	if (!fire) {
		return;
	}
	const { story, selection, report } = options;
	const layer = svg(root, 'g', { class: 'fire-layer' });

	// The pump room.
	if (fire.pumpRoom?.story === story && fire.pumpRoom.outline.length >= 3) {
		const group = svg(layer, 'g', { class: 'fire-pump-room' });
		const needed = report?.pumpRoom?.area;
		svg(group, 'title', {}, needed !== undefined ? localize('fire.roomTitleNeeded', "Fire pump room ({0} m² needed)", formatNumber(needed, 1)) : localize('fire.roomTitle', "Fire pump room"));
		svg(group, 'polygon', { points: polygonPoints(view, fire.pumpRoom.outline), class: 'fire-pump-room-shape' });
		const xs = fire.pumpRoom.outline.map(p => view.x(p[0]));
		const ys = fire.pumpRoom.outline.map(p => view.y(p[1]));
		svg(group, 'text', { x: Math.min(...xs) + 4, y: Math.min(...ys) + 12, class: 'fire-label' }, localize('fire.roomLabel', "Fire pump room"));
	}

	// Fire tanks.
	fire.tanks.forEach((tank, index) => {
		if (fireTankStory(tank, context) !== story) {
			return;
		}
		const outline = tankOutline(tank);
		const design = report?.tankDesigns.find(d => d.id === tank.id);
		const failed = !!design && (design.failed > 0 || !!design.error);
		const group = svg(layer, 'g', { class: `fire-tank${tank.kind === 'overhead' ? '' : ' ground'}${tank.sized ? ' sized' : ''}${failed ? ' failed' : ''}${selected(selection, 'fireTank', index) ? ' selected' : ''}`, 'data-fire-tank': index });
		const volume = num(tank.length) * num(tank.width) * num(tank.waterDepth) / 1e9;
		svg(group, 'title', {}, `${tank.id} · ${tank.kind === 'overhead' ? localize('fire.tankOverhead', "overhead fire tank") : localize('fire.tankGround', "underground fire reservoir")} · ${formatNumber(volume, 1)} m³`);
		svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'fire-tank-shape' });
		svg(group, 'text', { x: view.x(num(tank.x)), y: view.y(num(tank.y)) + 4, class: 'fire-tank-label', 'text-anchor': 'middle' }, tank.id);
	});

	// Fire mains: a line as thick as the pipe, at least 3 px.
	fire.mains.forEach(main => {
		if (main.story !== story || main.path.length < 2) {
			return;
		}
		const group = svg(layer, 'g', { class: 'fire-main' });
		svg(group, 'title', {}, localize('fire.mainTitle', "{0} · fire main DN{1}", main.id, formatNumber(main.diameter ?? 100, 0)));
		svg(group, 'polyline', { points: polygonPoints(view, main.path), class: 'fire-main-line', 'stroke-width': Math.max(3, num(main.diameter, 100) * view.scale) });
		const [a, b] = main.path;
		svg(group, 'text', { x: view.x((a[0] + b[0]) / 2) + 6, y: view.y((a[1] + b[1]) / 2) - 6, class: 'fire-label' }, `${main.id} DN${formatNumber(main.diameter ?? 100, 0)}`);
	});

	// Pump sets.
	fire.pumps.forEach((pump, index) => {
		if (pump.story !== story) {
			return;
		}
		const outline = pumpOutline(pump);
		const group = svg(layer, 'g', { class: `fire-pump duty-${pump.duty}${pump.sized ? ' sized' : ''}${selected(selection, 'firePump', index) ? ' selected' : ''}`, 'data-fire-pump': index });
		const duty = pump.flow !== undefined && pump.head !== undefined ? localize('fire.pumpDuty', "{0} l/min × {1} m", formatNumber(pump.flow, 0), formatNumber(pump.head, 1)) : undefined;
		const weight = pump.operatingWeight !== undefined ? localize('fire.knValue', "{0} kN", formatNumber(pump.operatingWeight, 1)) : localize('fire.typicalWeight', "typical weight");
		svg(group, 'title', {}, [`${pump.id} · ${firePumpLabel(pump.duty)}`, duty, weight].filter(Boolean).join(' · '));
		svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'fire-pump-shape' });
		const cx = view.x(num(pump.x));
		const cy = view.y(num(pump.y));
		svg(group, 'text', { x: cx, y: cy + 4, class: 'fire-pump-letters', 'text-anchor': 'middle' }, firePumpLetters(pump.duty));
		const top = Math.min(...outline.map(p => view.y(p[1])));
		const left = Math.min(...outline.map(p => view.x(p[0])));
		svg(group, 'text', { x: left, y: top - 4, class: 'fire-label' }, [pump.id, duty].filter(Boolean).join(' · '));
	});

	// Risers: a ring with the letters of the system.
	fire.risers.forEach((riser, index) => {
		if (!fireRiserOnStory(riser, context, story)) {
			return;
		}
		const x = view.x(num(riser.x));
		const y = view.y(num(riser.y));
		const group = svg(layer, 'g', { class: `fire-riser sys-${riser.system}${selected(selection, 'fireRiser', index) ? ' selected' : ''}`, 'data-fire-riser': index });
		svg(group, 'title', {}, `${riser.id} · ${fireRiserLabel(riser.system)}${riser.diameter ? ` · DN${formatNumber(riser.diameter, 0)}` : ''}${riser.shaft ? ` · ${riser.shaft}` : ''}`);
		svg(group, 'circle', { cx: x, cy: y, r: 11, class: 'fire-riser-ring' });
		svg(group, 'text', { x, y: y + 3.5, class: 'fire-riser-letters', 'text-anchor': 'middle' }, fireRiserLetters(riser.system));
		svg(group, 'text', { x: x + 14, y: y + 4, class: 'fire-label' }, riser.id);
	});
}
