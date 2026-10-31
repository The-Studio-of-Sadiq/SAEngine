/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { appendPlannedFeatureChip } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { formatNumber, ISoilReport, IStrataFence, IStratigraphy, soilTypeLabel } from './soilDocument.js';
import { appendSoilSwatch, niceStep, patternId, svg } from './soilLog.js';

/*
 * The Strata view of the soil report: the 3D stratigraphy of the site as a block diagram (the
 * correlated units between the interpolated surfaces, turned by azimuth and tilt) and the fence
 * diagrams through the boreholes, drawn from `saengine.soil.stratigraphy` (the backend's soil
 * results). The fences and the correlation are stored in the report's `stratigraphy`. The 1D
 * site response is planned (not in this MVP) and shown as a chip.
 */

export const SITE_RESPONSE_FEATURE = 'soil.siteResponse';

/** What the view keeps between renders. */
export interface IStrataViewState {
	/** The fence shown (index). */
	fence: number;
	/** Plan rotation of the block diagram [°]. */
	azimuth: number;
	/** Tilt of the view above the horizon [°]. */
	elevation: number;
	/** Vertical exaggeration of the block diagram. */
	exaggeration: number;
}

export interface IStrataViewOptions {
	readonly report: ISoilReport;
	readonly model: IStratigraphy | undefined;
	readonly computing: boolean;
	readonly patternPrefix: string;
	readonly width: number;
	readonly state: IStrataViewState;
	readonly disposables: DisposableStore;
	readonly commandService: ICommandService;
	/** The report changed (fences, correlation): saves and recomputes. */
	changed(): void;
	rerender(): void;
}

interface IStoredFence {
	id: string;
	boreholes: string[];
}

interface IStoredStratigraphy {
	correlateBy?: 'soilType' | 'uscs';
	fences?: IStoredFence[];
}

function stored(report: ISoilReport): IStoredStratigraphy | undefined {
	const value = report.stratigraphy;
	return typeof value === 'object' && value !== null ? value as IStoredStratigraphy : undefined;
}

function ensureStored(report: ISoilReport): IStoredStratigraphy {
	const existing = stored(report);
	if (existing) {
		existing.fences ??= [];
		return existing;
	}
	const created: IStoredStratigraphy = { fences: [] };
	report.stratigraphy = created;
	return created;
}

function unitLabel(model: IStratigraphy, index: number): string {
	const unit = model.units[index];
	return model.correlateBy === 'uscs' && unit.key !== unit.soilType ? `${unit.id} ${unit.key} (${soilTypeLabel(unit.soilType)})` : `${unit.id} ${soilTypeLabel(unit.soilType)}`;
}

export function renderStrataView(container: HTMLElement, options: IStrataViewOptions): void {
	const { model, state, disposables } = options;
	const header = append(container, $('.soil-view-header'));
	append(header, $('span.soil-view-title', undefined, localize('soil.strata.title', "Stratigraphy")));
	append(header, $('span.soil-view-subtitle', undefined, localize('soil.strata.subtitle', "The boreholes' strata correlated into units and interpolated between them (inverse distance); a model of the logs to judge, not measured ground.")));

	renderSettings(container, options);

	if (!model) {
		append(container, $('p.soil-note', undefined, options.computing
			? localize('soil.strata.computing', "Building the stratigraphy...")
			: localize('soil.strata.noModel', "The stratigraphy is built by the SAEngine backend with the other results; it appears here once the results are in.")));
		renderPlanned(container, options);
		return;
	}
	for (const note of model.notes) {
		append(container, $('p.soil-note', undefined, note));
	}
	if (!model.units.length) {
		renderPlanned(container, options);
		return;
	}

	// Legend of the units.
	const legend = append(container, $('.soil-legend'));
	model.units.forEach((unit, index) => {
		const item = append(legend, $('span.soil-legend-item'));
		appendSoilSwatch(item, options.patternPrefix, unit.soilType as never);
		append(item, $('span', undefined, unitLabel(model, index)));
	});

	// Fence diagrams.
	if (model.fences.length) {
		const section = append(container, $('.soil-section'));
		const heading = append(section, $('.soil-section-heading'));
		append(heading, $('span.soil-section-title', undefined, localize('soil.strata.fence', "Fence diagram")));
		if (model.fences.length > 1) {
			const select = append(heading, $<HTMLSelectElement>('select.soil-select', { 'aria-label': localize('soil.strata.fencePick', "Fence shown") }));
			model.fences.forEach((fence, index) => {
				const option = append(select, $<HTMLOptionElement>('option', { value: String(index) }, localize('soil.strata.fenceOption', "Fence {0}: {1}", fence.id, fence.boreholes.map(b => b.id).join(' – '))));
				option.selected = index === state.fence;
			});
			disposables.add(addDisposableListener(select, EventType.CHANGE, () => {
				state.fence = Number(select.value) || 0;
				options.rerender();
			}));
		}
		const fence = model.fences[Math.min(state.fence, model.fences.length - 1)];
		if (fence.schematic) {
			append(section, $('p.soil-note', undefined, localize('soil.strata.schematic', "The boreholes share one plan position: they are spaced 10 m apart, joined straight between their logs.")));
		}
		renderFenceDiagram(append(section, $('.soil-strata-canvas')), model, fence, options);
	}

	// 3D block diagram.
	if (model.grid) {
		const section = append(container, $('.soil-section'));
		const heading = append(section, $('.soil-section-heading'));
		append(heading, $('span.soil-section-title', undefined, localize('soil.strata.block', "3D stratigraphy")));
		const controls = append(section, $('.soil-strata-controls'));
		const slider = (label: string, value: number, min: number, max: number, store: (v: number) => void) => {
			const element = append(controls, $('label.soil-strata-control'));
			append(element, $('span', undefined, label));
			const input = append(element, $<HTMLInputElement>('input', { type: 'range', min: String(min), max: String(max), step: '5', 'aria-label': label }));
			input.value = String(value);
			disposables.add(addDisposableListener(input, EventType.INPUT, () => {
				store(Number(input.value));
				options.rerender();
			}));
		};
		slider(localize('soil.strata.azimuth', "Turn"), state.azimuth, 0, 355, v => state.azimuth = v);
		slider(localize('soil.strata.tilt', "Tilt"), state.elevation, 5, 85, v => state.elevation = v);
		const exaggeration = append(append(controls, $('label.soil-strata-control')), $<HTMLSelectElement>('select.soil-select', { 'aria-label': localize('soil.strata.exaggeration', "Vertical exaggeration") }));
		for (const factor of [1, 2, 5, 10]) {
			const option = append(exaggeration, $<HTMLOptionElement>('option', { value: String(factor) }, localize('soil.strata.exaggerationOption', "Vertical × {0}", factor)));
			option.selected = factor === state.exaggeration;
		}
		disposables.add(addDisposableListener(exaggeration, EventType.CHANGE, () => {
			state.exaggeration = Number(exaggeration.value) || 1;
			options.rerender();
		}));
		renderBlockDiagram(append(section, $('.soil-strata-canvas')), model, options);
	}
	renderPlanned(container, options);
}

/** The correlation and the fences, edited in place. */
function renderSettings(container: HTMLElement, options: IStrataViewOptions): void {
	const { report, disposables } = options;
	const settings = stored(report);
	const section = append(container, $('.soil-section.soil-strata-settings'));
	const row = append(section, $('.soil-strata-controls'));
	const correlate = append(row, $('label.soil-strata-control'));
	append(correlate, $('span', undefined, localize('soil.strata.correlateBy', "Correlate by")));
	const select = append(correlate, $<HTMLSelectElement>('select.soil-select'));
	for (const [value, label] of [['soilType', localize('soil.strata.bySoilType', "Soil type")], ['uscs', localize('soil.strata.byUscs', "USCS group")]] as const) {
		const option = append(select, $<HTMLOptionElement>('option', { value }, label));
		option.selected = (settings?.correlateBy ?? 'soilType') === value;
	}
	disposables.add(addDisposableListener(select, EventType.CHANGE, () => {
		const target = ensureStored(report);
		if (select.value === 'uscs') {
			target.correlateBy = 'uscs';
		} else {
			delete target.correlateBy;
		}
		options.changed();
	}));
	const add = append(row, $<HTMLButtonElement>('button.soil-link', { type: 'button' }, localize('soil.strata.addFence', "Add Fence")));
	disposables.add(addDisposableListener(add, EventType.CLICK, () => {
		const target = ensureStored(report);
		const fences = target.fences!;
		let n = fences.length;
		let id = String.fromCharCode(65 + (n % 26));
		while (fences.some(f => f.id === id)) {
			n++;
			id = `F${n}`;
		}
		fences.push({ id, boreholes: report.boreholes.slice(0, 2).map(b => b.id) });
		options.changed();
	}));
	const fences = settings?.fences ?? [];
	if (!fences.length) {
		append(section, $('p.soil-note', undefined, localize('soil.strata.defaultFence', "No fence given: one runs through all boreholes along the site. Add a fence to choose the boreholes and their order.")));
	}
	const known = new Set(report.boreholes.map(b => b.id));
	fences.forEach((fence, index) => {
		const line = append(section, $('.soil-strata-controls'));
		const idLabel = append(line, $('label.soil-strata-control'));
		append(idLabel, $('span', undefined, localize('soil.strata.fenceId', "Fence")));
		const idInput = append(idLabel, $<HTMLInputElement>('input.soil-input', { type: 'text', size: '4', 'aria-label': localize('soil.strata.fenceIdAria', "Fence ID") }));
		idInput.value = fence.id;
		const boreholes = append(line, $<HTMLInputElement>('input.soil-input.soil-strata-boreholes', { type: 'text', 'aria-label': localize('soil.strata.fenceBoreholes', "Boreholes of fence {0}, in order", fence.id), placeholder: localize('soil.strata.fencePlaceholder', "BH-1, BH-2, BH-3") }));
		boreholes.value = fence.boreholes.join(', ');
		const commit = () => {
			const ids = boreholes.value.split(/[,;\s]+/).map(s => s.trim()).filter(Boolean);
			const bad = ids.filter(i => !known.has(i));
			boreholes.classList.toggle('invalid', bad.length > 0 || ids.length < 2);
			boreholes.title = bad.length ? localize('soil.strata.unknownBorehole', "No borehole {0}", bad.join(', ')) : ids.length < 2 ? localize('soil.strata.twoBoreholes', "A fence needs two boreholes or more") : '';
			const id = idInput.value.trim();
			if (bad.length || ids.length < 2 || !id) {
				return;
			}
			const target = ensureStored(report).fences![index];
			target.id = id;
			target.boreholes = ids;
			options.changed();
		};
		disposables.add(addDisposableListener(boreholes, EventType.CHANGE, commit));
		disposables.add(addDisposableListener(idInput, EventType.CHANGE, commit));
		const remove = append(line, $<HTMLButtonElement>('button.soil-link', { type: 'button' }, localize('soil.strata.removeFence', "Remove")));
		disposables.add(addDisposableListener(remove, EventType.CLICK, () => {
			const target = ensureStored(report);
			target.fences!.splice(index, 1);
			if (!target.fences!.length && !target.correlateBy) {
				delete report.stratigraphy;
			}
			options.changed();
		}));
	});
}

function renderPlanned(container: HTMLElement, options: IStrataViewOptions): void {
	const section = append(container, $('.soil-section'));
	const heading = append(section, $('.soil-section-heading'));
	append(heading, $('span.soil-section-title', undefined, localize('soil.strata.siteResponse', "Site response")));
	options.disposables.add(appendPlannedFeatureChip(section, SITE_RESPONSE_FEATURE, options.commandService));
}

function value(v: number | null | undefined, fallback: number): number {
	return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

/** The fence: each unit between its top and bottom along the stations, the boreholes and the water table. */
function renderFenceDiagram(container: HTMLElement, model: IStratigraphy, fence: IStrataFence, options: IStrataViewOptions): void {
	const left = 56, right = 24, top = 36, bottom = 34;
	const width = Math.max(420, options.width - 32);
	const all = fence.surfaces.flat().filter((v): v is number => typeof v === 'number');
	if (!all.length || !fence.stations.length) {
		return;
	}
	const high = Math.max(...all);
	const low = Math.min(...all);
	const span = Math.max(1, high - low);
	const height = Math.max(240, Math.min(560, top + bottom + span * 18));
	const x = (d: number) => left + d / Math.max(fence.length, 1e-6) * (width - left - right);
	const y = (z: number) => top + (high - z) / span * (height - top - bottom);
	const root = svg(container, 'svg', { width, height, class: 'soil-fence soil-strata-fence', role: 'img', 'aria-label': localize('soil.strata.fenceAria', "Fence diagram {0}", fence.id) });
	const step = niceStep(span, 8);
	for (let e = Math.ceil(low / step) * step; e <= high + 1e-9; e += step) {
		svg(root, 'line', { x1: left, x2: width - right, y1: y(e), y2: y(e), class: 'soil-grid' });
		svg(root, 'text', { x: left - 4, y: y(e) + 4, class: 'soil-tick', 'text-anchor': 'end' }, formatNumber(e, 1));
	}
	svg(root, 'text', { x: 4, y: 14, class: 'soil-heading' }, localize('soil.strata.elevation', "Elevation (m)"));
	const dStep = niceStep(fence.length, 8);
	for (let d = 0; d <= fence.length + 1e-9; d += dStep) {
		svg(root, 'text', { x: x(d), y: height - 18, class: 'soil-tick', 'text-anchor': 'middle' }, formatNumber(d, 0));
	}
	svg(root, 'text', { x: (left + width - right) / 2, y: height - 4, class: 'soil-heading', 'text-anchor': 'middle' }, localize('soil.strata.distance', "Distance along fence {0} (m)", fence.id));
	const stations = fence.stations.map(s => s.distance);
	model.units.forEach((unit, k) => {
		const upper = fence.surfaces[k];
		const lower = fence.surfaces[k + 1];
		if (!upper || !lower) {
			return;
		}
		let thick = false;
		const tops: string[] = [];
		const bottoms: string[] = [];
		stations.forEach((d, i) => {
			const zt = value(upper[i], 0);
			const zb = value(lower[i], zt);
			thick ||= zt - zb > 1e-3;
			tops.push(`${x(d).toFixed(1)},${y(zt).toFixed(1)}`);
			bottoms.push(`${x(d).toFixed(1)},${y(zb).toFixed(1)}`);
		});
		if (!thick) {
			return;
		}
		const polygon = svg(root, 'polygon', { points: [...tops, ...bottoms.reverse()].join(' '), fill: `url(#${patternId(options.patternPrefix, unit.soilType)})`, class: 'soil-stratum' });
		svg(polygon, 'title', {}, unitLabel(model, k));
	});
	if (fence.water) {
		const points = stations.map((d, i) => fence.water![i] === null ? undefined : `${x(d).toFixed(1)},${y(fence.water![i]!).toFixed(1)}`).filter(Boolean);
		if (points.length > 1) {
			svg(root, 'polyline', { points: points.join(' '), class: 'soil-water-join' });
		}
	}
	for (const b of fence.boreholes) {
		const hole = model.boreholes.find(h => h.id === b.id);
		if (!hole) {
			continue;
		}
		svg(root, 'line', { x1: x(b.distance), x2: x(b.distance), y1: y(hole.ground), y2: y(hole.bottom), class: 'soil-strata-hole' });
		svg(root, 'text', { x: x(b.distance), y: top - 8, class: 'soil-fence-id', 'text-anchor': 'middle' }, b.id);
	}
}

/** The 3D block diagram: every unit's walls around the grid and the ground on top, drawn far to near. */
function renderBlockDiagram(container: HTMLElement, model: IStratigraphy, options: IStrataViewOptions): void {
	const grid = model.grid;
	if (!grid) {
		return;
	}
	const { azimuth, elevation, exaggeration } = options.state;
	const a = azimuth * Math.PI / 180;
	const e = elevation * Math.PI / 180;
	const cx = (grid.x[0] + grid.x[grid.x.length - 1]) / 2;
	const cy = (grid.y[0] + grid.y[grid.y.length - 1]) / 2;
	const all = grid.surfaces.flat(2).filter((v): v is number => typeof v === 'number');
	const zMid = all.length ? (Math.max(...all) + Math.min(...all)) / 2 : 0;
	const nx = grid.x.length, ny = grid.y.length;
	// Every surface at every node, missing values from the surface above.
	const z = (k: number, j: number, i: number): number => {
		for (let s = k; s >= 0; s--) {
			const v = grid.surfaces[s]?.[j]?.[i];
			if (typeof v === 'number') {
				return v;
			}
		}
		return zMid;
	};
	const project = (px: number, py: number, pz: number) => {
		const u = (px - cx) * Math.cos(a) - (py - cy) * Math.sin(a);
		const v = (px - cx) * Math.sin(a) + (py - cy) * Math.cos(a);
		const h = (pz - zMid) * exaggeration;
		return { sx: u, sy: -(h * Math.cos(e) + v * Math.sin(e)), depth: v * Math.cos(e) - h * Math.sin(e) };
	};
	interface IFace { points: { sx: number; sy: number }[]; depth: number; unit: number; ground: boolean }
	const faces: IFace[] = [];
	const quad = (corners: [number, number, number][], unit: number, ground: boolean) => {
		const projected = corners.map(c => project(...c));
		faces.push({ points: projected, depth: projected.reduce((s, p) => s + p.depth, 0) / projected.length, unit, ground });
	};
	const units = model.units.length;
	// The walls on the four sides of the grid.
	const edges: [number, number, number, number][] = [];
	for (let i = 0; i + 1 < nx; i++) {
		edges.push([0, i, 0, i + 1], [ny - 1, i, ny - 1, i + 1]);
	}
	for (let j = 0; j + 1 < ny; j++) {
		edges.push([j, 0, j + 1, 0], [j, nx - 1, j + 1, nx - 1]);
	}
	for (const [j1, i1, j2, i2] of edges) {
		for (let k = 0; k < units; k++) {
			const t1 = z(k, j1, i1), t2 = z(k, j2, i2), b1 = z(k + 1, j1, i1), b2 = z(k + 1, j2, i2);
			if (t1 - b1 < 1e-3 && t2 - b2 < 1e-3) {
				continue;
			}
			quad([[grid.x[i1], grid.y[j1], t1], [grid.x[i2], grid.y[j2], t2], [grid.x[i2], grid.y[j2], b2], [grid.x[i1], grid.y[j1], b1]], k, false);
		}
	}
	// The ground, coloured by the unit at the top of each cell.
	for (let j = 0; j + 1 < ny; j++) {
		for (let i = 0; i + 1 < nx; i++) {
			let unit = 0;
			while (unit + 1 < units && z(unit, j, i) - z(unit + 1, j, i) < 1e-3) {
				unit++;
			}
			quad([[grid.x[i], grid.y[j], z(0, j, i)], [grid.x[i + 1], grid.y[j], z(0, j, i + 1)], [grid.x[i + 1], grid.y[j + 1], z(0, j + 1, i + 1)], [grid.x[i], grid.y[j + 1], z(0, j + 1, i)]], unit, true);
		}
	}
	faces.sort((p, q) => q.depth - p.depth);
	const xs = faces.flatMap(f => f.points.map(p => p.sx));
	const ys = faces.flatMap(f => f.points.map(p => p.sy));
	const width = Math.max(420, options.width - 32);
	const height = Math.round(Math.min(620, width * 0.7));
	const pad = 28;
	const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
	const scale = Math.min((width - 2 * pad) / Math.max(maxX - minX, 1e-6), (height - 2 * pad) / Math.max(maxY - minY, 1e-6));
	const px = (sx: number) => pad + (sx - minX) * scale + ((width - 2 * pad) - (maxX - minX) * scale) / 2;
	const py = (sy: number) => pad + (sy - minY) * scale;
	const root = svg(container, 'svg', { width, height, class: 'soil-strata-block', role: 'img', 'aria-label': localize('soil.strata.blockAria', "3D stratigraphy of {0} units from {1} boreholes", units, model.boreholes.length) });
	for (const face of faces) {
		const unit = model.units[face.unit];
		svg(root, 'polygon', {
			points: face.points.map(p => `${px(p.sx).toFixed(1)},${py(p.sy).toFixed(1)}`).join(' '),
			fill: `url(#${patternId(options.patternPrefix, unit.soilType)})`,
			class: face.ground ? 'soil-stratum soil-strata-ground' : 'soil-stratum',
		});
	}
	for (const hole of model.boreholes) {
		const p1 = project(hole.x, hole.y, hole.ground);
		const p2 = project(hole.x, hole.y, hole.bottom);
		svg(root, 'line', { x1: px(p1.sx), y1: py(p1.sy), x2: px(p2.sx), y2: py(p2.sy), class: 'soil-strata-hole' });
		svg(root, 'text', { x: px(p1.sx), y: py(p1.sy) - 6, class: 'soil-fence-id', 'text-anchor': 'middle' }, hole.id);
	}
}
