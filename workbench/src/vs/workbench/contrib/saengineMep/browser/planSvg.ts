/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { svg } from '../../saengineSoil/browser/soilLog.js';

/*
 * The scaffolding the plan views draw with (the MEP plans; the Substructure plan can use it
 * too): fitting the points into the view, SVG point lists, a round scale-bar length and the
 * grid lines with their bubbles. Plain SVG through the shared `svg()` helper.
 */

type PlanPoint = readonly [number, number];

/** A plan transform: mm on the project's axes to px with y up. */
export interface IPlanView {
	readonly scale: number;
	x(value: number): number;
	y(value: number): number;
}

/** The transform that fits `points` (mm) into `width` × `height` px, `padding` px clear, at least 1 m each way. */
export function fitPlan(points: readonly PlanPoint[], width: number, height: number, padding: number): IPlanView {
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

/** An SVG `points` list of plan points. */
export function polygonPoints(view: IPlanView, points: readonly PlanPoint[]): string {
	return points.map(p => `${view.x(p[0]).toFixed(1)},${view.y(p[1]).toFixed(1)}`).join(' ');
}

/** A step of 1, 2 or 5 × 10^n that is about `target` long. */
export function niceLength(target: number): number {
	const power = Math.pow(10, Math.floor(Math.log10(Math.max(target, 1))));
	const unit = target / power;
	return (unit >= 5 ? 5 : unit >= 2 ? 2 : 1) * power;
}

export interface IPlanGrids {
	readonly x: readonly { readonly label: string; readonly position: number }[];
	readonly y: readonly { readonly label: string; readonly position: number }[];
}

/**
 * The grid: lines `reach` px past the extent [minX, maxX, minY, maxY] (mm), bubbles at the top
 * and the left. `prefix` names the classes (`<prefix>-grid`, `-grid-line`, `-grid-bubble`, `-grid-label`).
 */
export function drawPlanGrid(root: SVGElement, view: IPlanView, grids: IPlanGrids, extent: readonly [number, number, number, number], prefix: string, reach = 24): SVGGElement {
	const [minX, maxX, minY, maxY] = extent;
	const grid = svg(root, 'g', { class: `${prefix}-grid` });
	for (const line of grids.x) {
		const x = view.x(line.position);
		svg(grid, 'line', { x1: x, y1: view.y(maxY) - reach, x2: x, y2: view.y(minY) + reach, class: `${prefix}-grid-line` });
		svg(grid, 'circle', { cx: x, cy: view.y(maxY) - reach - 10, r: 10, class: `${prefix}-grid-bubble` });
		svg(grid, 'text', { x, y: view.y(maxY) - reach - 6, class: `${prefix}-grid-label`, 'text-anchor': 'middle' }, line.label);
	}
	for (const line of grids.y) {
		const y = view.y(line.position);
		svg(grid, 'line', { x1: view.x(minX) - reach, y1: y, x2: view.x(maxX) + reach, y2: y, class: `${prefix}-grid-line` });
		svg(grid, 'circle', { cx: view.x(minX) - reach - 10, cy: y, r: 10, class: `${prefix}-grid-bubble` });
		svg(grid, 'text', { x: view.x(minX) - reach - 10, y: y + 4, class: `${prefix}-grid-label`, 'text-anchor': 'middle' }, line.label);
	}
	return grid;
}
