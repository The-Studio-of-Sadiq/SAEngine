/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { carriedColumns, foundationCenter, foundationOutlines, formatUtilisation, gridIntersections, gridPoint, IFoundation, IRaftResult, ISiteContext, ISubstructure, pileCaps, Point, toGlobal, toLocal } from './substructureDocument.js';

/*
 * The drawings of the substructure editor, as plain SVG: the plan of the base level (grid,
 * column bases, foundations to scale with their piles, tie beams, boreholes and the sizing
 * assistant's proposals) and the raft's contact pressure or settlement as a heat map. Colours
 * are CSS classes (substructureEditor.css) over the theme's tokens. Interactive parts carry
 * `data-foundation`, `data-column`, `data-pile` or `data-tie` attributes: the editor listens on
 * the container and finds them with `closest`. The pile grid is drawn apart from the building's
 * grid (its own dashed lines, bubbles at the bottom and the right).
 */

/** What the plan highlights and adds. */
export interface IPlanOptions {
	readonly width: number;
	readonly height: number;
	readonly selectedFoundations: ReadonlySet<number>;
	readonly selectedColumns: ReadonlySet<string>;
	readonly selectedTieBeam?: number;
	/** The sizing assistant's foundations, drawn dashed over the current ones. */
	readonly proposals?: readonly IFoundation[];
	/** The colour band of each foundation by id, once the design report is in. */
	readonly bands?: ReadonlyMap<string, 'ok' | 'warn' | 'fail' | 'none'>;
	/** The utilisation of each foundation by id, written under its id. */
	readonly utilisations?: ReadonlyMap<string, number>;
	/** The piles selected, by id. */
	readonly selectedPiles?: ReadonlySet<string>;
	/** The foundation picked as the first end of a grade beam being drawn. */
	readonly beamStart?: string;
}

/** The plan drawn, with its transform: px in the SVG to mm on the project's axes and back. */
export interface IPlanDrawing {
	readonly svg: SVGSVGElement;
	/** Plan mm per px. */
	readonly mmPerPx: number;
	toPlan(x: number, y: number): Point;
	toScreen(p: readonly [number, number]): [number, number];
}

/**
 * Where a tie beam runs: between the closest pair of the columns its two foundations carry (a
 * tie beam joins the column bases, not the foundations' centres), else between the centres.
 */
export function tieBeamEnds(from: IFoundation, to: IFoundation, context: ISiteContext): [Point, Point] | undefined {
	const a = carriedColumns(from, context);
	const b = carriedColumns(to, context);
	let best: [Point, Point] | undefined;
	let distance = Infinity;
	for (const p of a) {
		for (const q of b) {
			const d = Math.hypot(p.x - q.x, p.y - q.y);
			if (d < distance) {
				distance = d;
				best = [[p.x, p.y], [q.x, q.y]];
			}
		}
	}
	if (best) {
		return best;
	}
	const ca = foundationCenter(from, context);
	const cb = foundationCenter(to, context);
	return ca && cb ? [ca, cb] : undefined;
}

/** A plan transform: mm on the project's axes to px with y up. */
interface IView {
	readonly scale: number;
	x(value: number): number;
	y(value: number): number;
	invX(px: number): number;
	invY(px: number): number;
}

function fit(points: readonly (readonly [number, number])[], width: number, height: number, padding: number): IView {
	const xs = points.map(p => p[0]);
	const ys = points.map(p => p[1]);
	const x0 = Math.min(...xs);
	const x1 = Math.max(...xs);
	const y0 = Math.min(...ys);
	const y1 = Math.max(...ys);
	const scale = Math.min((width - 2 * padding) / Math.max(x1 - x0, 1000), (height - 2 * padding) / Math.max(y1 - y0, 1000));
	const offsetX = (width - (x1 - x0) * scale) / 2;
	const offsetY = (height - (y1 - y0) * scale) / 2;
	return {
		scale,
		x: value => offsetX + (value - x0) * scale,
		y: value => height - offsetY - (value - y0) * scale,
		invX: px => x0 + (px - offsetX) / scale,
		invY: px => y0 + (height - offsetY - px) / scale,
	};
}

function polygonPoints(view: IView, points: readonly Point[]): string {
	return points.map(p => `${view.x(p[0]).toFixed(1)},${view.y(p[1]).toFixed(1)}`).join(' ');
}

/**
 * Everything the plan should show, for the fit: the building, the foundations and the grid, and
 * the boreholes near them. Boreholes far from the building would shrink it to a corner of the
 * plan: they are drawn on the plan's edge instead, towards where they are.
 */
function extent(document: ISubstructure, context: ISiteContext, proposals: readonly IFoundation[]): Point[] {
	const points: Point[] = [];
	for (const c of context.columns) {
		points.push([c.x - c.xDim / 2, c.y - c.yDim / 2], [c.x + c.xDim / 2, c.y + c.yDim / 2]);
	}
	for (const w of context.walls) {
		points.push(w.start, w.end);
	}
	for (const f of [...document.foundations, ...proposals]) {
		points.push(...foundationOutlines(f, context).flat());
	}
	for (const g of context.grids.x) {
		points.push([g.position, points[0]?.[1] ?? 0]);
	}
	for (const g of context.grids.y) {
		points.push([points[0]?.[0] ?? 0, g.position]);
	}
	for (const pile of document.piles) {
		points.push(pile.position);
	}
	points.push(...gridIntersections(document.pileGrid).map(c => c.point));
	if (!points.length) {
		return context.boreholes.length ? context.boreholes.map(b => [b.x, b.y] as Point) : [[0, 0], [10000, 10000]];
	}
	const [x0, x1, y0, y1] = bounds(points);
	const margin = Math.max(x1 - x0, y1 - y0) * 0.25 + 3000;
	for (const b of context.boreholes) {
		if (b.x >= x0 - margin && b.x <= x1 + margin && b.y >= y0 - margin && b.y <= y1 + margin) {
			points.push([b.x, b.y]);
		}
	}
	return points;
}

function bounds(points: readonly Point[]): [number, number, number, number] {
	return [Math.min(...points.map(p => p[0])), Math.max(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[1]))];
}

/** A step of 1, 2 or 5 × 10^n that is about `target` long. */
function niceLength(target: number): number {
	const power = Math.pow(10, Math.floor(Math.log10(Math.max(target, 1))));
	const unit = target / power;
	return (unit >= 5 ? 5 : unit >= 2 ? 2 : 1) * power;
}

/** Draws the plan of the base level into `container` (replacing nothing: the caller clears it). */
export function renderPlan(container: HTMLElement, document: ISubstructure, context: ISiteContext, options: IPlanOptions): IPlanDrawing {
	const { width, height } = options;
	const root = svg(container, 'svg', { width, height, class: 'sub-plan', role: 'img', 'aria-label': localize('sub.planAria', "Plan of the foundations") });
	const proposals = options.proposals ?? [];
	const points = extent(document, context, proposals);
	const view = fit(points, width, height, 56);
	const [minX, maxX, minY, maxY] = bounds(points);

	// Grid: lines past the extent, bubbles at the top and the left.
	const grid = svg(root, 'g', { class: 'sub-grid' });
	const reach = 24;
	for (const line of context.grids.x) {
		const x = view.x(line.position);
		svg(grid, 'line', { x1: x, y1: view.y(maxY) - reach, x2: x, y2: view.y(minY) + reach, class: 'sub-grid-line' });
		svg(grid, 'circle', { cx: x, cy: view.y(maxY) - reach - 10, r: 10, class: 'sub-grid-bubble' });
		svg(grid, 'text', { x, y: view.y(maxY) - reach - 6, class: 'sub-grid-label', 'text-anchor': 'middle' }, line.label);
	}
	for (const line of context.grids.y) {
		const y = view.y(line.position);
		svg(grid, 'line', { x1: view.x(minX) - reach, y1: y, x2: view.x(maxX) + reach, y2: y, class: 'sub-grid-line' });
		svg(grid, 'circle', { cx: view.x(minX) - reach - 10, cy: y, r: 10, class: 'sub-grid-bubble' });
		svg(grid, 'text', { x: view.x(minX) - reach - 10, y: y + 4, class: 'sub-grid-label', 'text-anchor': 'middle' }, line.label);
	}

	// The pile grid: its own setting-out, dashed, bubbles at the bottom and the right.
	const pileGrid = document.pileGrid;
	if (pileGrid && (pileGrid.x.length || pileGrid.y.length)) {
		const group = svg(root, 'g', { class: 'sub-pile-grid' });
		const origin = pileGrid.origin ?? [0, 0];
		const rotation = pileGrid.rotation ?? 0;
		const corners: Point[] = [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY]];
		const local = corners.map(c => toLocal(origin, c, rotation));
		const margin = 12 / view.scale;
		const [u0, u1] = [Math.min(...local.map(p => p[0])) - margin, Math.max(...local.map(p => p[0])) + margin];
		const [v0, v1] = [Math.min(...local.map(p => p[1])) - margin, Math.max(...local.map(p => p[1])) + margin];
		const bubble = (p: Point, label: string) => {
			svg(group, 'circle', { cx: view.x(p[0]), cy: view.y(p[1]), r: 8, class: 'sub-pile-grid-bubble' });
			svg(group, 'text', { x: view.x(p[0]), y: view.y(p[1]) + 3.5, class: 'sub-pile-grid-label', 'text-anchor': 'middle' }, label);
		};
		const reach = 8 / view.scale;
		for (const line of pileGrid.x) {
			const [a, b] = [gridPoint(pileGrid, line.position, v0), gridPoint(pileGrid, line.position, v1)];
			svg(group, 'line', { x1: view.x(a[0]), y1: view.y(a[1]), x2: view.x(b[0]), y2: view.y(b[1]), class: 'sub-pile-grid-line' });
			bubble(gridPoint(pileGrid, line.position, v0 - reach), line.label);
		}
		for (const line of pileGrid.y) {
			const [a, b] = [gridPoint(pileGrid, u0, line.position), gridPoint(pileGrid, u1, line.position)];
			svg(group, 'line', { x1: view.x(a[0]), y1: view.y(a[1]), x2: view.x(b[0]), y2: view.y(b[1]), class: 'sub-pile-grid-line' });
			bubble(gridPoint(pileGrid, u1 + reach, line.position), line.label);
		}
	}

	// Walls on the base level, faint.
	for (const wall of context.walls) {
		svg(root, 'line', { x1: view.x(wall.start[0]), y1: view.y(wall.start[1]), x2: view.x(wall.end[0]), y2: view.y(wall.end[1]), class: 'sub-wall', 'stroke-width': Math.max(2, wall.thickness * view.scale) });
	}

	// Foundations: rafts first so that footings and caps stay on top.
	const order = document.foundations.map((f, i) => ({ f, i })).sort((a, b) => Number(b.f.type === 'raft') - Number(a.f.type === 'raft'));
	const pileTypes = new Map(document.pileTypes.map(p => [p.id, p]));
	for (const { f, i } of order) {
		const selected = options.selectedFoundations.has(i) || options.beamStart === f.id;
		const band = options.bands?.get(f.id) ?? 'none';
		const group = svg(root, 'g', { class: `sub-foundation type-${f.type} band-${band}${selected ? ' selected' : ''}`, 'data-foundation': i, tabindex: -1 });
		svg(group, 'title', {}, f.id);
		for (const outline of foundationOutlines(f, context)) {
			svg(group, 'polygon', { points: polygonPoints(view, outline), class: 'sub-foundation-shape' });
		}
		if (f.type === 'strip' && f.path && f.path.length >= 2) {
			svg(group, 'polyline', { points: polygonPoints(view, f.path), class: 'sub-strip-axis' });
		}
		const center = foundationCenter(f, context);
		if (center) {
			const outlines = foundationOutlines(f, context).flat();
			const top = outlines.length ? Math.min(...outlines.map(p => view.y(p[1]))) : view.y(center[1]);
			const left = outlines.length ? Math.min(...outlines.map(p => view.x(p[0]))) : view.x(center[0]);
			// The id just above the outline's top-left corner, clear of the column and the piles;
			// its utilisation beside it once checked.
			const label = svg(group, 'text', { x: left, y: top - 4, class: 'sub-foundation-label' }, f.id);
			const utilisation = options.utilisations?.get(f.id);
			if (typeof utilisation === 'number') {
				svg(label, 'tspan', { class: `sub-foundation-util band-${band}`, dx: 6 }, formatUtilisation(utilisation));
			}
		}
	}

	// Proposals of the sizing assistant: dashed, over the current foundations.
	for (const f of proposals) {
		for (const outline of foundationOutlines(f, context)) {
			svg(root, 'polygon', { points: polygonPoints(view, outline), class: 'sub-proposal' });
		}
	}

	// Tie beams between the column bases of the two foundations.
	const byId = new Map(document.foundations.map(f => [f.id, f]));
	document.tieBeams.forEach((tie, i) => {
		const from = byId.get(tie.from);
		const to = byId.get(tie.to);
		const ends = from && to && tieBeamEnds(from, to, context);
		if (!ends) {
			return;
		}
		const [a, b] = ends;
		const group = svg(root, 'g', { class: `sub-tie${options.selectedTieBeam === i ? ' selected' : ''}`, 'data-tie': i });
		svg(group, 'title', {}, tie.id);
		const coordinates = { x1: view.x(a[0]), y1: view.y(a[1]), x2: view.x(b[0]), y2: view.y(b[1]) };
		const thickness = Math.max(3, 300 * view.scale);
		svg(group, 'line', { ...coordinates, class: 'sub-tie-hit' });
		svg(group, 'line', { ...coordinates, class: 'sub-tie-line', 'stroke-width': thickness });
		// The label beside the beam (off its line, on the side away from the plan's top-left), halfway along.
		const dx = coordinates.x2 - coordinates.x1;
		const dy = coordinates.y2 - coordinates.y1;
		const length = Math.hypot(dx, dy) || 1;
		const offset = thickness / 2 + 10;
		const nx = dy / length * offset;
		const ny = -dx / length * offset;
		const flip = nx + ny < 0 ? -1 : 1;
		svg(group, 'text', { x: (coordinates.x1 + coordinates.x2) / 2 + flip * nx, y: (coordinates.y1 + coordinates.y2) / 2 + flip * ny + 4, class: 'sub-tie-label', 'text-anchor': 'middle' }, tie.id);
	});

	// Piles, placed in plan: under a cap or not yet (dashed), with their marks when there is room.
	const caps = pileCaps(document);
	const piles = svg(root, 'g', { class: 'sub-piles' });
	for (const pile of document.piles) {
		const radius = Math.max(3, (pileTypes.get(pile.type)?.diameter ?? 500) / 2 * view.scale);
		const selected = options.selectedPiles?.has(pile.id) ?? false;
		const group = svg(piles, 'g', { class: `sub-pile-item${caps.has(pile.id) ? '' : ' free'}${selected ? ' selected' : ''}`, 'data-pile': pile.id });
		svg(group, 'title', {}, caps.has(pile.id) ? localize('sub.pileTitle', "Pile {0} ({1}) under {2}", pile.id, pile.type, caps.get(pile.id)!) : localize('sub.pileFreeTitle', "Pile {0} ({1}), under no cap", pile.id, pile.type));
		const [cx, cy] = [view.x(pile.position[0]), view.y(pile.position[1])];
		svg(group, 'circle', { cx, cy, r: radius + 4, class: 'sub-pile-hit' });
		svg(group, 'circle', { cx, cy, r: radius, class: 'sub-pile' });
		svg(group, 'path', { d: `M${cx - radius} ${cy}H${cx + radius}M${cx} ${cy - radius}V${cy + radius}`, class: 'sub-pile-cross' });
		if (radius >= 6 || selected) {
			svg(group, 'text', { x: cx + radius * 0.75 + 2, y: cy + radius * 0.75 + 10, class: 'sub-pile-label' }, pile.id);
		}
	}

	// Column bases.
	for (const column of context.columns) {
		const selected = options.selectedColumns.has(column.id);
		const group = svg(root, 'g', { class: `sub-column${selected ? ' selected' : ''}`, 'data-column': column.id });
		svg(group, 'title', {}, column.id);
		if (column.circle) {
			svg(group, 'circle', { cx: view.x(column.x), cy: view.y(column.y), r: Math.max(3, column.xDim / 2 * view.scale), class: 'sub-column-shape' });
		} else {
			const corners: Point[] = [
				toGlobal([column.x, column.y], -column.xDim / 2, -column.yDim / 2, column.rotation), toGlobal([column.x, column.y], column.xDim / 2, -column.yDim / 2, column.rotation),
				toGlobal([column.x, column.y], column.xDim / 2, column.yDim / 2, column.rotation), toGlobal([column.x, column.y], -column.xDim / 2, column.yDim / 2, column.rotation),
			];
			svg(group, 'polygon', { points: polygonPoints(view, corners), class: 'sub-column-shape' });
		}
		svg(group, 'text', { x: view.x(column.x) + Math.max(6, column.xDim / 2 * view.scale + 4), y: view.y(column.y) - Math.max(6, column.yDim / 2 * view.scale + 3), class: 'sub-column-label' }, column.id);
	}

	// Boreholes.
	for (const borehole of context.boreholes) {
		const group = svg(root, 'g', { class: 'sub-borehole' });
		svg(group, 'title', {}, localize('sub.boreholeTitle', "Borehole {0}", borehole.id));
		// A borehole off the plan sits on its edge, towards where it is.
		const x = Math.max(12, Math.min(width - 110, view.x(borehole.x)));
		const y = Math.max(12, Math.min(height - 24, view.y(borehole.y)));
		if (x !== view.x(borehole.x) || y !== view.y(borehole.y)) {
			group.classList.add('off-plan');
		}
		svg(group, 'circle', { cx: x, cy: y, r: 6, class: 'sub-borehole-mark' });
		svg(group, 'path', { d: `M${x - 6} ${y}H${x + 6}M${x} ${y - 6}V${y + 6}`, class: 'sub-borehole-cross' });
		svg(group, 'text', { x: x + 9, y: y + 14, class: 'sub-borehole-label' }, group.classList.contains('off-plan') ? localize('sub.boreholeOff', "{0} (off plan)", borehole.id) : borehole.id);
	}

	// Scale bar.
	const length = niceLength(120 / view.scale);
	const barX = 16;
	const barY = height - 16;
	svg(root, 'path', { d: `M${barX} ${barY - 4}V${barY}H${barX + length * view.scale}V${barY - 4}`, class: 'sub-scale' });
	svg(root, 'text', { x: barX + length * view.scale + 6, y: barY, class: 'sub-scale-label' }, localize('sub.scaleBar', "{0} m", formatNumber(length / 1000, 2)));
	return {
		svg: root,
		mmPerPx: 1 / view.scale,
		toPlan: (x, y) => [view.invX(x), view.invY(y)],
		toScreen: p => [view.x(p[0]), view.y(p[1])],
	};
}

/** The colour of a value from 0 (low) to 1 (high) on a sequential blue → red ramp, as a CSS class step. */
function step(t: number, steps: number): number {
	return Math.max(0, Math.min(steps - 1, Math.floor(t * steps)));
}

export const HEAT_STEPS = 8;

/**
 * The raft's contact pressure or settlement as a heat map of its result points (one square of
 * the mesh size each) over its outline, with the columns; returns the range shown.
 */
export function renderRaftHeatMap(container: HTMLElement, raft: IFoundation, result: IRaftResult, context: ISiteContext, quantity: 'pressure' | 'settlement', size: { width: number; height: number }): { min: number; max: number } | undefined {
	const values = result.points.map(p => p[quantity]).filter((v): v is number => typeof v === 'number');
	if (!values.length) {
		return undefined;
	}
	const min = Math.min(...values);
	const max = Math.max(...values);
	const outline = foundationOutlines(raft, context).flat();
	const points: Point[] = [...outline, ...result.points.map(p => [p.x, p.y] as Point)];
	const view = fit(points, size.width, size.height, 24);
	const root = svg(container, 'svg', { width: size.width, height: size.height, class: 'sub-heat', role: 'img', 'aria-label': quantity === 'pressure' ? localize('sub.heatPressure', "Contact pressure under the raft") : localize('sub.heatSettlement', "Settlement of the raft") });
	const mesh = result.meshSize ?? estimateSpacing(result.points);
	const cell = mesh * view.scale;
	const clip = `sub-heat-clip-${Math.random().toString(36).slice(2)}`;
	if (outline.length >= 3) {
		const clipPath = svg(svg(root, 'defs'), 'clipPath', { id: clip });
		svg(clipPath, 'polygon', { points: polygonPoints(view, outline) });
	}
	const cells = svg(root, 'g', outline.length >= 3 ? { 'clip-path': `url(#${clip})` } : {});
	for (const point of result.points) {
		const value = point[quantity];
		if (typeof value !== 'number') {
			continue;
		}
		const t = max > min ? (value - min) / (max - min) : 0.5;
		svg(cells, 'rect', { x: view.x(point.x) - cell / 2, y: view.y(point.y) - cell / 2, width: cell + 0.5, height: cell + 0.5, class: `sub-heat-cell sub-heat-${step(t, HEAT_STEPS)}` });
	}
	if (outline.length >= 3) {
		svg(root, 'polygon', { points: polygonPoints(view, outline), class: 'sub-heat-outline' });
	}
	for (const column of context.columns) {
		svg(root, 'rect', { x: view.x(column.x) - column.xDim / 2 * view.scale, y: view.y(column.y) - column.yDim / 2 * view.scale, width: column.xDim * view.scale, height: column.yDim * view.scale, class: 'sub-heat-column' });
	}
	// The value at each column the raft carries, beside it.
	for (const column of result.columns ?? []) {
		const value = column[quantity];
		if (typeof value === 'number') {
			svg(root, 'text', { x: view.x(column.x) + 6, y: view.y(column.y) - 6, class: 'sub-heat-value' }, `${column.id} ${formatNumber(value, quantity === 'pressure' ? 0 : 1)}`);
		}
	}
	return { min, max };
}

/** The spacing of a regular grid of points: the smallest distance between two of them. */
function estimateSpacing(points: readonly { x: number; y: number }[]): number {
	let best = Infinity;
	for (let i = 0; i < Math.min(points.length, 200); i++) {
		for (let j = i + 1; j < Math.min(points.length, 200); j++) {
			const d = Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y);
			if (d > 0) {
				best = Math.min(best, d);
			}
		}
	}
	return Number.isFinite(best) ? best : 500;
}
