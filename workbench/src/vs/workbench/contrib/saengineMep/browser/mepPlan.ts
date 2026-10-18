/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import {
	equipmentOutline, findHost, hostDirection, IMep, IMepContext, openingPlanSize, openingPoint, Point, shaftOnStory, storyElements, storyExtent, toGlobal,
} from './mepDocument.js';

/*
 * The plan of one story of the MEP editor, as plain SVG: grid, the floor (slabs with the
 * building model's openings, beams), the columns and walls through it, the shafts hatched, the
 * sleeves and openings on their hosts, the equipment as footprints with their weights, and the
 * report's clashes. Colours are CSS classes (mepEditor.css) over the theme's tokens.
 * Interactive parts carry `data-equipment`, `data-opening`, `data-shaft` (indexes), `data-element`
 * (a building model id) or `data-clash` attributes: the editor listens on the container and
 * finds them with `closest`.
 */

export type MepSelection =
	| { readonly kind: 'equipment'; readonly index: number }
	| { readonly kind: 'opening'; readonly index: number }
	| { readonly kind: 'shaft'; readonly index: number }
	/** The plumbing's risers and stacks, tanks and roof drains (plumbingDocument.ts). */
	| { readonly kind: 'riser'; readonly index: number }
	| { readonly kind: 'tank'; readonly index: number }
	| { readonly kind: 'drain'; readonly index: number }
	| { readonly kind: 'element'; readonly id: string };

/** A clash of the report drawn on the plan. */
export interface IPlanClash {
	readonly id: string;
	readonly point: Point;
	readonly open: boolean;
}

export interface IPlanOptions {
	readonly width: number;
	readonly height: number;
	readonly story: string;
	readonly selection?: MepSelection;
	/** The colour band of each opening by id, once the report is in. */
	readonly openingBands?: ReadonlyMap<string, 'ok' | 'warn' | 'fail' | 'none'>;
	readonly clashes?: readonly IPlanClash[];
	readonly selectedClash?: string;
	/** More plan points to keep in view (the plumbing's tanks beside the building). */
	readonly extraExtent?: readonly Point[];
	/** The plumbing view: the coordination items are drawn quietly, under the plumbing. */
	readonly plumbing?: boolean;
	/** Draws more over the plan (the plumbing), before the scale bar. */
	readonly overlay?: (root: SVGElement, view: IPlanView) => void;
}

/** A plan transform: mm on the project's axes to px with y up. */
export interface IPlanView {
	readonly scale: number;
	x(value: number): number;
	y(value: number): number;
}

function fit(points: readonly Point[], width: number, height: number, padding: number): IPlanView {
	const xs = points.map(p => p[0]);
	const ys = points.map(p => p[1]);
	const x0 = Math.min(...xs);
	const x1 = Math.max(...xs);
	const y0 = Math.min(...ys);
	const y1 = Math.max(...ys);
	const scale = Math.min((width - 2 * padding) / Math.max(x1 - x0, 1000), (height - 2 * padding) / Math.max(y1 - y0, 1000));
	const offsetX = (width - (x1 - x0) * scale) / 2;
	const offsetY = (height - (y1 - y0) * scale) / 2;
	return { scale, x: value => offsetX + (value - x0) * scale, y: value => height - offsetY - (value - y0) * scale };
}

function polygonPoints(view: IPlanView, points: readonly Point[]): string {
	return points.map(p => `${view.x(p[0]).toFixed(1)},${view.y(p[1]).toFixed(1)}`).join(' ');
}

/** A step of 1, 2 or 5 × 10^n that is about `target` long. */
function niceLength(target: number): number {
	const power = Math.pow(10, Math.floor(Math.log10(Math.max(target, 1))));
	const unit = target / power;
	return (unit >= 5 ? 5 : unit >= 2 ? 2 : 1) * power;
}

function isSelected(selection: MepSelection | undefined, kind: MepSelection['kind'], key: number | string): boolean {
	if (!selection || selection.kind !== kind) {
		return false;
	}
	return selection.kind === 'element' ? selection.id === key : selection.index === key;
}

/** Everything the story's plan should fit: its floor, columns and walls, its equipment and shafts, the grid. */
function extent(document: IMep, context: IMepContext, story: string, extra: readonly Point[] = []): Point[] {
	const points: Point[] = [...storyExtent(context, story), ...extra];
	for (const e of document.equipment) {
		if (e.story === story) {
			points.push(...equipmentOutline(e));
		}
	}
	for (const s of document.shafts) {
		if (shaftOnStory(s, context, story)) {
			points.push(...s.outline);
		}
	}
	const anchor = points[0] ?? [0, 0];
	for (const g of context.grids.x) {
		points.push([g.position, anchor[1]]);
	}
	for (const g of context.grids.y) {
		points.push([anchor[0], g.position]);
	}
	return points.length ? points : [[0, 0], [10000, 10000]];
}

/** Draws the plan of `options.story` into `container` (the caller clears it); returns the transform. */
export function renderPlan(container: HTMLElement, document: IMep, context: IMepContext, options: IPlanOptions): IPlanView {
	const { width, height, story, selection } = options;
	const root = svg(container, 'svg', { width, height, class: `mep-plan${options.plumbing ? ' plumbing' : ''}`, role: 'img', 'aria-label': localize('mep.planAria', "Plan of the services on {0}", story) });
	const points = extent(document, context, story, options.extraExtent);
	const view = fit(points, width, height, 56);
	const minX = Math.min(...points.map(p => p[0]));
	const maxX = Math.max(...points.map(p => p[0]));
	const minY = Math.min(...points.map(p => p[1]));
	const maxY = Math.max(...points.map(p => p[1]));

	const hatch = `mep-hatch-${Math.random().toString(36).slice(2)}`;
	const pattern = svg(svg(root, 'defs'), 'pattern', { id: hatch, width: 8, height: 8, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' });
	svg(pattern, 'line', { x1: 0, y1: 0, x2: 0, y2: 8, class: 'mep-hatch-line' });

	// Grid: lines past the extent, bubbles at the top and the left.
	const grid = svg(root, 'g', { class: 'mep-grid' });
	const reach = 24;
	for (const line of context.grids.x) {
		const x = view.x(line.position);
		svg(grid, 'line', { x1: x, y1: view.y(maxY) - reach, x2: x, y2: view.y(minY) + reach, class: 'mep-grid-line' });
		svg(grid, 'circle', { cx: x, cy: view.y(maxY) - reach - 10, r: 10, class: 'mep-grid-bubble' });
		svg(grid, 'text', { x, y: view.y(maxY) - reach - 6, class: 'mep-grid-label', 'text-anchor': 'middle' }, line.label);
	}
	for (const line of context.grids.y) {
		const y = view.y(line.position);
		svg(grid, 'line', { x1: view.x(minX) - reach, y1: y, x2: view.x(maxX) + reach, y2: y, class: 'mep-grid-line' });
		svg(grid, 'circle', { cx: view.x(minX) - reach - 10, cy: y, r: 10, class: 'mep-grid-bubble' });
		svg(grid, 'text', { x: view.x(minX) - reach - 10, y: y + 4, class: 'mep-grid-label', 'text-anchor': 'middle' }, line.label);
	}

	const elements = storyElements(context, story);

	// The floor: slabs, then the building model's own openings in them.
	for (const slab of elements.slabs) {
		const group = svg(root, 'g', { class: `mep-slab${isSelected(selection, 'element', slab.id) ? ' selected' : ''}`, 'data-element': slab.id });
		svg(group, 'title', {}, localize('mep.slabTitle', "Slab {0}", slab.id));
		svg(group, 'polygon', { points: polygonPoints(view, slab.boundary), class: 'mep-slab-shape' });
		const center = slab.boundary.length ? slab.boundary.reduce((s, p) => [s[0] + p[0] / slab.boundary.length, s[1] + p[1] / slab.boundary.length], [0, 0]) : undefined;
		if (center) {
			svg(group, 'text', { x: view.x(center[0]), y: view.y(center[1]), class: 'mep-element-label slab', 'text-anchor': 'middle' }, slab.id);
		}
	}
	for (const opening of elements.slabOpenings) {
		const corners: Point[] = [
			toGlobal([opening.x, opening.y], -opening.xDim / 2, -opening.yDim / 2, opening.rotation), toGlobal([opening.x, opening.y], opening.xDim / 2, -opening.yDim / 2, opening.rotation),
			toGlobal([opening.x, opening.y], opening.xDim / 2, opening.yDim / 2, opening.rotation), toGlobal([opening.x, opening.y], -opening.xDim / 2, opening.yDim / 2, opening.rotation),
		];
		const group = svg(root, 'g', { class: 'mep-bim-opening' });
		svg(group, 'title', {}, localize('mep.bimOpeningTitle', "Opening {0} of the building model", opening.id));
		svg(group, 'polygon', { points: polygonPoints(view, corners), class: 'mep-bim-opening-shape' });
		svg(group, 'path', { d: `M${view.x(corners[0][0])} ${view.y(corners[0][1])}L${view.x(corners[2][0])} ${view.y(corners[2][1])}M${view.x(corners[1][0])} ${view.y(corners[1][1])}L${view.x(corners[3][0])} ${view.y(corners[3][1])}`, class: 'mep-bim-opening-cross' });
	}

	// Shafts through this story, hatched.
	document.shafts.forEach((shaft, index) => {
		if (!shaftOnStory(shaft, context, story) || shaft.outline.length < 3) {
			return;
		}
		const group = svg(root, 'g', { class: `mep-shaft${isSelected(selection, 'shaft', index) ? ' selected' : ''}`, 'data-shaft': index });
		svg(group, 'title', {}, shaft.service ? `${shaft.id} · ${shaft.service}` : shaft.id);
		svg(group, 'polygon', { points: polygonPoints(view, shaft.outline), class: 'mep-shaft-fill', fill: `url(#${hatch})` });
		svg(group, 'polygon', { points: polygonPoints(view, shaft.outline), class: 'mep-shaft-shape' });
		const top = Math.min(...shaft.outline.map(p => view.y(p[1])));
		const left = Math.min(...shaft.outline.map(p => view.x(p[0])));
		svg(group, 'text', { x: left, y: top - 4, class: 'mep-shaft-label' }, shaft.service ? `${shaft.id} · ${shaft.service}` : shaft.id);
	});

	// Walls and beams.
	for (const wall of elements.walls) {
		const group = svg(root, 'g', { class: `mep-wall${isSelected(selection, 'element', wall.id) ? ' selected' : ''}`, 'data-element': wall.id });
		svg(group, 'title', {}, localize('mep.wallTitle', "Wall {0}", wall.id));
		const coordinates = { x1: view.x(wall.start[0]), y1: view.y(wall.start[1]), x2: view.x(wall.end[0]), y2: view.y(wall.end[1]) };
		svg(group, 'line', { ...coordinates, class: 'mep-hit' });
		svg(group, 'line', { ...coordinates, class: 'mep-wall-line', 'stroke-width': Math.max(3, wall.thickness * view.scale) });
	}
	for (const beam of elements.beams) {
		const group = svg(root, 'g', { class: `mep-beam${isSelected(selection, 'element', beam.id) ? ' selected' : ''}`, 'data-element': beam.id });
		svg(group, 'title', {}, localize('mep.beamTitle', "Beam {0}", beam.id));
		const coordinates = { x1: view.x(beam.start[0]), y1: view.y(beam.start[1]), x2: view.x(beam.end[0]), y2: view.y(beam.end[1]) };
		svg(group, 'line', { ...coordinates, class: 'mep-hit' });
		svg(group, 'line', { ...coordinates, class: 'mep-beam-line', 'stroke-width': Math.max(3, beam.width * view.scale) });
		const direction = hostDirection({ kind: 'beam', element: beam });
		const offset = Math.max(8, beam.width / 2 * view.scale + 6);
		svg(group, 'text', { x: (coordinates.x1 + coordinates.x2) / 2 - direction[1] * offset, y: (coordinates.y1 + coordinates.y2) / 2 + direction[0] * offset + 4, class: 'mep-element-label', 'text-anchor': 'middle' }, beam.id);
	}

	// Columns through the story.
	for (const column of elements.columns) {
		const group = svg(root, 'g', { class: `mep-column${isSelected(selection, 'element', column.id) ? ' selected' : ''}`, 'data-element': column.id });
		svg(group, 'title', {}, localize('mep.columnTitle', "Column {0}", column.id));
		if (column.circle) {
			svg(group, 'circle', { cx: view.x(column.x), cy: view.y(column.y), r: Math.max(3, column.xDim / 2 * view.scale), class: 'mep-column-shape' });
		} else {
			const corners: Point[] = [
				toGlobal([column.x, column.y], -column.xDim / 2, -column.yDim / 2, column.rotation), toGlobal([column.x, column.y], column.xDim / 2, -column.yDim / 2, column.rotation),
				toGlobal([column.x, column.y], column.xDim / 2, column.yDim / 2, column.rotation), toGlobal([column.x, column.y], -column.xDim / 2, column.yDim / 2, column.rotation),
			];
			svg(group, 'polygon', { points: polygonPoints(view, corners), class: 'mep-column-shape' });
		}
	}

	// Equipment: footprints with the id, name and weight.
	document.equipment.forEach((equipment, index) => {
		if (equipment.story !== story) {
			return;
		}
		const outline = equipmentOutline(equipment);
		const group = svg(root, 'g', { class: `mep-equipment kind-${equipment.kind}${equipment.vibrating ? ' vibrating' : ''}${isSelected(selection, 'equipment', index) ? ' selected' : ''}`, 'data-equipment': index });
		svg(group, 'title', {}, `${equipment.id} · ${equipment.name ?? ''}`);
		svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'mep-equipment-shape' });
		if (equipment.loadAs === 'points') {
			for (const corner of equipmentOutline({ ...equipment, length: equipment.length * 0.8, width: equipment.width * 0.8 })) {
				svg(group, 'circle', { cx: view.x(corner[0]), cy: view.y(corner[1]), r: 3, class: 'mep-equipment-foot' });
			}
		}
		const cx = view.x(equipment.x);
		const cy = view.y(equipment.y);
		const roomy = Math.min(equipment.length, equipment.width) * view.scale >= 34;
		svg(group, 'text', { x: cx, y: roomy ? cy - 2 : cy + 4, class: 'mep-equipment-label', 'text-anchor': 'middle' }, equipment.id);
		if (roomy) {
			svg(group, 'text', { x: cx, y: cy + 11, class: 'mep-equipment-weight', 'text-anchor': 'middle' }, localize('mep.knValue', "{0} kN", formatNumber(equipment.operatingWeight, 1)));
		}
		if (equipment.name && equipment.length * view.scale >= 70) {
			const top = Math.min(...outline.map(p => view.y(p[1])));
			const left = Math.min(...outline.map(p => view.x(p[0])));
			svg(group, 'text', { x: left, y: top - 4, class: 'mep-equipment-name' }, equipment.name);
		}
	});

	// Sleeves and openings on their hosts.
	document.openings.forEach((opening, index) => {
		const host = findHost(context, opening.host);
		const point = openingPoint(opening, context);
		if (!host || !point || !(host.kind === 'wall' ? elements.walls.includes(host.element) : host.kind === 'beam' ? elements.beams.includes(host.element) : elements.slabs.includes(host.element))) {
			return;
		}
		const band = options.openingBands?.get(opening.id) ?? 'none';
		const group = svg(root, 'g', { class: `mep-opening kind-${opening.kind} band-${band}${isSelected(selection, 'opening', index) ? ' selected' : ''}`, 'data-opening': index });
		svg(group, 'title', {}, opening.service ? `${opening.id} · ${opening.service}` : opening.id);
		const across = openingPlanSize(opening);
		const x = view.x(point[0]);
		const y = view.y(point[1]);
		if (opening.shape === 'rectangle' && host.kind === 'slab') {
			const w = Math.max(6, across * view.scale);
			const h = Math.max(6, (opening.height ?? across) * view.scale);
			svg(group, 'rect', { x: x - w / 2, y: y - h / 2, width: w, height: h, class: 'mep-opening-shape' });
		} else if (opening.shape === 'rectangle') {
			// Along the beam or wall: a short bar across the host.
			const direction = hostDirection(host);
			const half = Math.max(4, across / 2 * view.scale);
			const thickness = Math.max(8, (host.kind === 'beam' ? host.element.width : host.element.thickness) * view.scale + 6);
			const corners: [number, number][] = [[-half, -thickness / 2], [half, -thickness / 2], [half, thickness / 2], [-half, thickness / 2]]
				.map(([u, v]) => [x + u * direction[0] + v * direction[1], y - u * direction[1] + v * direction[0]]);
			svg(group, 'polygon', { points: corners.map(c => `${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(' '), class: 'mep-opening-shape' });
		} else {
			svg(group, 'circle', { cx: x, cy: y, r: Math.max(5, across / 2 * view.scale), class: 'mep-opening-shape' });
		}
		svg(group, 'text', { x: x + 8, y: y - 8, class: 'mep-opening-label' }, opening.id);
	});

	// The report's clashes on this story.
	for (const clash of options.clashes ?? []) {
		const x = view.x(clash.point[0]);
		const y = view.y(clash.point[1]);
		const group = svg(root, 'g', { class: `mep-clash${clash.open ? ' open' : ' coordinated'}${options.selectedClash === clash.id ? ' selected' : ''}`, 'data-clash': clash.id });
		svg(group, 'title', {}, clash.id);
		svg(group, 'path', { d: `M${x - 6} ${y - 6}L${x + 6} ${y + 6}M${x + 6} ${y - 6}L${x - 6} ${y + 6}`, class: 'mep-clash-mark' });
		svg(group, 'circle', { cx: x, cy: y, r: 10, class: 'mep-clash-ring' });
	}

	options.overlay?.(root, view);

	// Scale bar.
	const scaleLength = niceLength(120 / view.scale);
	const barX = 16;
	const barY = height - 16;
	svg(root, 'path', { d: `M${barX} ${barY - 4}V${barY}H${barX + scaleLength * view.scale}V${barY - 4}`, class: 'mep-scale' });
	svg(root, 'text', { x: barX + scaleLength * view.scale + 6, y: barY, class: 'mep-scale-label' }, localize('mep.scaleBar', "{0} m", formatNumber(scaleLength / 1000, 2)));
	return view;
}
