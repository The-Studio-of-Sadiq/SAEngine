/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { IMep, IMepContext, Point, storyElements } from './mepDocument.js';
import type { MepSelection } from './mepPlan.js';
import { IPlanView, polygonPoints } from './planSvg.js';
import { roofStory } from './mepRead.js';
import {
	earthingLabel, elecKindLabel, RING_OFFSET, elecLetters, elecOutline, elecRiserOnStory, electricalOf, IElectricalReport, ratingUnit, riserKindLabel, riserLetters, riserOutline, sourceOf,
} from './electricalDocument.js';

/*
 * The electrical services drawn over the plan of one story: the equipment as footprints with
 * their letters, rating and weight, the risers (busbar trunking, trays) as their sections, the
 * cable trays as bands along their runs; on the roof the lightning protection (the roof's edge
 * conductor, the mesh and the air terminals), and on the roof and the lowest story the columns
 * whose bars are the down conductors, with the earthing. Interactive parts carry
 * `data-elec-equipment`, `data-elec-riser` or `data-tray`.
 */

export interface IElectricalPlanOptions {
	readonly story: string;
	readonly selection?: MepSelection;
	readonly report?: IElectricalReport;
}

function selected(selection: MepSelection | undefined, kind: 'elecEquipment' | 'elecRiser' | 'tray', index: number): boolean {
	return selection?.kind === kind && selection.index === index;
}

/** The air terminals drawn: the file's, else the ones the backend proposes. */
export function airTerminals(document: IMep, report: IElectricalReport | undefined): { points: readonly [number, number, number][]; proposed: boolean } {
	const given = electricalOf(document)?.lightning.airTerminals;
	if (given?.length) {
		return { points: given, proposed: false };
	}
	return { points: report?.lightning?.airTerminals ?? [], proposed: true };
}

/** Draws the electrical services of `options.story` into the plan's svg. */
export function renderElectrical(root: SVGElement, view: IPlanView, document: IMep, context: IMepContext, options: IElectricalPlanOptions): void {
	const electrical = electricalOf(document);
	if (!electrical) {
		return;
	}
	const { story, selection, report } = options;
	const layer = svg(root, 'g', { class: 'elec-layer' });
	const roof = roofStory(context)?.id;
	const ground = context.stories[0]?.id;
	const lightning = electrical.lightning;

	// Lightning protection on the roof: the edge conductor along the roof's slabs, the mesh, the air terminals.
	if (lightning.enabled && story === roof) {
		const group = svg(layer, 'g', { class: 'elec-lightning' });
		svg(group, 'title', {}, lightning.level ? localize('elec.lpsTitleLevel', "Lightning protection, level {0}", String(lightning.level)) : localize('elec.lpsTitle', "Lightning protection"));
		for (const slab of storyElements(context, story).slabs) {
			svg(group, 'polygon', { points: polygonPoints(view, slab.boundary), class: 'elec-lps-edge' });
		}
		for (const [a, b] of report?.lightning?.mesh ?? []) {
			svg(group, 'line', { x1: view.x(a[0]), y1: view.y(a[1]), x2: view.x(b[0]), y2: view.y(b[1]), class: 'elec-lps-mesh' });
		}
		const terminals = airTerminals(document, report);
		for (const [x, y, z] of terminals.points) {
			const px = view.x(x);
			const py = view.y(y);
			const terminal = svg(group, 'g', { class: `elec-air-terminal${terminals.proposed ? ' proposed' : ''}` });
			svg(terminal, 'title', {}, terminals.proposed
				? localize('elec.terminalProposed', "Air terminal proposed by SAEngine, {0} m high", formatNumber(z / 1000, 2))
				: localize('elec.terminal', "Air terminal, {0} m high", formatNumber(z / 1000, 2)));
			svg(terminal, 'path', { d: `M${px} ${py - 7}L${px + 6} ${py + 4}H${px - 6}Z`, class: 'elec-air-terminal-shape' });
		}
	}

	// Down conductors: the columns the backend lists (on the roof and the lowest story), and the earthing at the lowest.
	if (lightning.enabled && (story === roof || story === ground)) {
		// A down conductor is a column line (`columns`: its column at each story): label it with this story's column.
		const here = storyElements(context, story).columns;
		const columns = (report?.lightning?.downConductors ?? []).map(d => {
			const column = here.find(c => d.columns.includes(c.id)) ?? context.columns.find(c => d.columns.includes(c.id));
			const point: Point | undefined = d.x !== undefined && d.y !== undefined ? [d.x, d.y] : column ? [column.x, column.y] : undefined;
			return point ? { id: column?.id ?? d.column, point } : undefined;
		}).filter((c): c is { id: string; point: Point } => !!c);
		const group = svg(layer, 'g', { class: 'elec-down-conductors' });
		for (const column of columns) {
			const x = view.x(column.point[0]);
			const y = view.y(column.point[1]);
			const mark = svg(group, 'g', { class: 'elec-down-conductor' });
			svg(mark, 'title', {}, localize('elec.downConductorTitle', "Column {0}: down conductor (its bars bonded and continuous to the earthing)", column.id));
			svg(mark, 'circle', { cx: x, cy: y, r: 11, class: 'elec-down-conductor-ring' });
			svg(mark, 'text', { x: x + 13, y: y + 15, class: 'elec-down-conductor-label' }, localize('elec.dcLabel', "DC {0}", column.id));
			if (story === ground && lightning.earthing === 'rods') {
				svg(mark, 'path', { d: `M${x - 7} ${y + 18}H${x + 7}M${x - 4.5} ${y + 21}H${x + 4.5}M${x - 2} ${y + 24}H${x + 2}`, class: 'elec-earth-symbol' });
			}
		}
		if (story === ground && lightning.earthing === 'ring') {
			const points = context.columns.map(c => [c.x, c.y] as Point);
			if (points.length >= 2) {
				const pad = RING_OFFSET;
				const x0 = Math.min(...points.map(p => p[0])) - pad;
				const x1 = Math.max(...points.map(p => p[0])) + pad;
				const y0 = Math.min(...points.map(p => p[1])) - pad;
				const y1 = Math.max(...points.map(p => p[1])) + pad;
				const ring = svg(group, 'g', { class: 'elec-earth-ring' });
				svg(ring, 'title', {}, earthingLabel('ring'));
				svg(ring, 'rect', { x: view.x(x0), y: view.y(y1), width: (x1 - x0) * view.scale, height: (y1 - y0) * view.scale, class: 'elec-earth-ring-shape' });
			}
		}
	}

	// Cable trays: a band as wide as the tray.
	electrical.trays.forEach((tray, index) => {
		if (tray.story !== story || tray.path.length < 2) {
			return;
		}
		const group = svg(layer, 'g', { class: `elec-tray${selected(selection, 'tray', index) ? ' selected' : ''}`, 'data-tray': index });
		svg(group, 'title', {}, localize('elec.trayTitle', "{0} · cable tray {1} × {2} mm", tray.id, formatNumber(tray.width, 0), formatNumber(tray.height, 0)));
		const points = polygonPoints(view, tray.path);
		svg(group, 'polyline', { points, class: 'mep-hit' });
		svg(group, 'polyline', { points, class: 'elec-tray-body', 'stroke-width': Math.max(4, tray.width * view.scale) });
		svg(group, 'polyline', { points, class: 'elec-tray-rungs', 'stroke-width': Math.max(4, tray.width * view.scale) });
		const [a, b] = tray.path;
		const offset = Math.max(10, tray.width * view.scale / 2 + 8);
		const horizontal = Math.abs(b[0] - a[0]) >= Math.abs(b[1] - a[1]);
		const mx = view.x((a[0] + b[0]) / 2);
		const my = view.y((a[1] + b[1]) / 2);
		svg(group, 'text', { x: horizontal ? mx : mx + offset, y: horizontal ? my + offset + 4 : my, class: 'elec-label', 'text-anchor': horizontal ? 'middle' : 'start' }, `${tray.id} ${formatNumber(tray.width, 0)}`);
	});

	// Equipment footprints.
	electrical.equipment.forEach((equipment, index) => {
		if (equipment.story !== story) {
			return;
		}
		const outline = elecOutline(equipment);
		const failed = sourceOf(report, equipment)?.status === 'fail';
		const group = svg(layer, 'g', { class: `elec-equipment kind-${equipment.kind}${equipment.vibrating ? ' vibrating' : ''}${failed ? ' failed' : ''}${selected(selection, 'elecEquipment', index) ? ' selected' : ''}`, 'data-elec-equipment': index });
		const rating = equipment.rating !== undefined ? `${formatNumber(equipment.rating, 0)} ${ratingUnit(equipment.kind)}` : undefined;
		const weight = equipment.operatingWeight !== undefined ? localize('elec.knValue', "{0} kN", formatNumber(equipment.operatingWeight, 1)) : localize('elec.noWeight', "? kN");
		svg(group, 'title', {}, [`${equipment.id} · ${elecKindLabel(equipment.kind)}`, rating, weight].filter(Boolean).join(' · '));
		svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'elec-equipment-shape' });
		const cx = view.x(equipment.x);
		const cy = view.y(equipment.y);
		const w = Math.abs(view.x(outline[1][0]) - view.x(outline[0][0]));
		const h = Math.abs(view.y(outline[2][1]) - view.y(outline[0][1]));
		const roomy = Math.min(w, h) >= 30;
		svg(group, 'text', { x: cx, y: roomy ? cy - 2 : cy + 4, class: 'elec-equipment-letters', 'text-anchor': 'middle' }, roomy ? equipment.id : elecLetters(equipment.kind));
		if (roomy) {
			svg(group, 'text', { x: cx, y: cy + 10, class: 'elec-equipment-weight', 'text-anchor': 'middle' }, weight);
		}
		const top = Math.min(...outline.map(p => view.y(p[1])));
		const left = Math.min(...outline.map(p => view.x(p[0])));
		svg(group, 'text', { x: left, y: top - 4, class: 'elec-equipment-name' }, [roomy ? elecLetters(equipment.kind) : equipment.id, rating].filter(Boolean).join(' · '));
	});

	// Risers: their section, with its letters.
	electrical.risers.forEach((riser, index) => {
		if (!elecRiserOnStory(riser, context, story)) {
			return;
		}
		const outline = riserOutline(riser);
		const group = svg(layer, 'g', { class: `elec-riser kind-${riser.kind}${selected(selection, 'elecRiser', index) ? ' selected' : ''}`, 'data-elec-riser': index });
		svg(group, 'title', {}, `${riser.id} · ${riserKindLabel(riser.kind)} · ${formatNumber(riser.width ?? 300, 0)} × ${formatNumber(riser.depth ?? 200, 0)} mm${riser.shaft ? ` · ${riser.shaft}` : ''}`);
		svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'elec-riser-shape' });
		const right = Math.max(...outline.map(p => view.x(p[0])));
		svg(group, 'text', { x: right + 4, y: view.y(riser.y) + 4, class: 'elec-label' }, `${riser.id} ${riserLetters(riser.kind)}`);
	});
}
