/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { formatNumber, ISoilSample, parseField } from './soilDocument.js';
import { renderConsolidationChart, renderGrainSizeChart, renderShearChart } from './soilLabCharts.js';
import { consolidationResult, directShearResult, grainSizeResult, hasLabTest, LAB_TESTS, LabTest, labSheet, pruneLabTests, triaxialResult } from './soilLabTests.js';
import { IGridState, newGridState, SoilGrid } from './soilGrid.js';

/*
 * The lab tests of the sample selected in the log sheet: a tab per test, the test's specimens in
 * a grid (keyboard and Excel paste as in the sheet), its chart, and what follows from it with a
 * button that takes the value into the sample.
 */

export interface ILabPanelOptions {
	readonly sample: ISoilSample;
	/** "D-3, 4.5–4.95 m" */
	readonly title: string;
	readonly test: LabTest;
	/** The grids' states by test, kept by the owner across renders. */
	readonly gridStates: Map<string, IGridState>;
	readonly onDidChangeTest: (test: LabTest) => void;
	/** After the sample changed: store the report and render again. */
	readonly onDidWrite: () => void;
}

export class SoilLabPanel extends Disposable {

	readonly element: HTMLElement;
	readonly grid: SoilGrid;

	constructor(container: HTMLElement, private readonly options: ILabPanelOptions) {
		super();
		const { sample, test } = options;
		this.element = append(container, $('.soil-lab'));
		const header = append(this.element, $('.soil-lab-header'));
		append(header, $('span.soil-section-title', undefined, localize('soil.lab.title', "Lab tests")));
		append(header, $('span.soil-section-detail', undefined, options.title));
		const tabs = append(header, $('.sa-segmented.soil-lab-tabs', { role: 'tablist', 'aria-label': localize('soil.lab.tabs', "Lab test") }));
		for (const { test: id, label } of LAB_TESTS) {
			const button = append(tabs, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab', 'aria-selected': String(id === test) }));
			button.classList.toggle('active', id === test);
			append(button, $('span', undefined, label));
			if (hasLabTest(sample, id)) {
				append(button, $('span.soil-lab-dot', { 'aria-label': localize('soil.lab.hasData', "has entries") }));
			}
			this._register(addDisposableListener(button, EventType.CLICK, () => options.onDidChangeTest(id)));
		}

		const body = append(this.element, $('.soil-lab-body'));
		const left = append(body, $('.soil-lab-entries'));
		if (test === 'triaxial') {
			this.renderTriaxialType(left, sample);
		}
		const sheet = labSheet(sample, test);
		let state = options.gridStates.get(test);
		if (!state) {
			state = newGridState();
			options.gridStates.set(test, state);
		}
		this.grid = this._register(new SoilGrid(left, {
			sheet,
			state,
			ariaLabel: localize('soil.lab.gridAria', "{0} of {1}", sheet.label, options.title),
			onDidWrite: () => options.onDidWrite(),
			maxHeight: 260,
		}));
		const right = append(body, $('.soil-lab-result'));
		this.renderResult(right, sample, test);
	}

	private renderTriaxialType(container: HTMLElement, sample: ISoilSample): void {
		const row = append(container, $('.soil-lab-type'));
		append(row, $('span', undefined, localize('soil.lab.testType', "Test")));
		const select = append(row, $<HTMLSelectElement>('select.soil-select.soil-lab-select', { 'aria-label': localize('soil.lab.testType', "Test") }));
		const current = sample.triaxial?.type ?? 'CU';
		for (const [value, label] of [
			['UU', localize('soil.lab.uu', "UU (unconsolidated undrained)")],
			['CU', localize('soil.lab.cu', "CU (consolidated undrained)")],
			['CD', localize('soil.lab.cd', "CD (consolidated drained)")],
		] as const) {
			const option = append(select, $<HTMLOptionElement>('option', { value }, label));
			option.selected = value === current;
		}
		this._register(addDisposableListener(select, EventType.CHANGE, () => {
			(sample.triaxial ??= { specimens: [] }).type = select.value as 'UU' | 'CU' | 'CD';
			this.options.onDidWrite();
		}));
	}

	/** A computed value with a button that takes it into the sample. */
	private suggestion(container: HTMLElement, label: string, value: number | undefined, decimals: number, unit: string, take?: () => void): void {
		const row = append(container, $('.soil-lab-value'));
		append(row, $('span.soil-lab-value-label', undefined, label));
		append(row, $('span.soil-lab-value-number', undefined, typeof value === 'number' && Number.isFinite(value) ? `${formatNumber(value, decimals)}${unit ? ` ${unit}` : ''}` : '—'));
		if (take && typeof value === 'number' && Number.isFinite(value)) {
			const button = append(row, $<HTMLButtonElement>('button.soil-add.soil-lab-use', { type: 'button', title: localize('soil.lab.useTitle', "Take this value into the sample's {0}", label) }, localize('soil.lab.use', "Use")));
			this._register(addDisposableListener(button, EventType.CLICK, () => {
				take();
				this.options.onDidWrite();
			}));
		}
	}

	private renderResult(container: HTMLElement, sample: ISoilSample, test: LabTest): void {
		const chart = append(container, $('.soil-chart'));
		const values = append(container, $('.soil-lab-values'));
		const round = (value: number, decimals: number) => Number(value.toFixed(decimals));
		switch (test) {
			case 'grainSize': {
				const sieves = sample.grainSize?.sieves ?? [];
				renderGrainSizeChart(chart, sieves);
				const r = grainSizeResult(sieves);
				this.suggestion(values, localize('soil.lab.fines', "Fines (passing 75 µm)"), r.fines, 1, '%', () => sample.finesContent = round(r.fines!, 1));
				this.suggestion(values, 'D10', r.D10, 4, localize('soil.unit.mm', "mm"));
				this.suggestion(values, 'D30', r.D30, 4, localize('soil.unit.mm', "mm"));
				this.suggestion(values, 'D60', r.D60, 4, localize('soil.unit.mm', "mm"));
				this.suggestion(values, localize('soil.lab.cuUniformity', "Cu = D60/D10"), r.Cu, 2, '');
				this.suggestion(values, localize('soil.lab.ccCurvature', "Cc = D30²/(D10·D60)"), r.Cc, 2, '');
				break;
			}
			case 'consolidation': {
				const points = sample.consolidation?.points ?? [];
				renderConsolidationChart(chart, points);
				const r = consolidationResult(points);
				this.suggestion(values, localize('soil.lab.ccIndex', "Cc (steepest loading step)"), r.Cc, 3, '', () => {
					sample.Cc = round(r.Cc!, 3);
					(sample.consolidation ??= { points: [] }).Cc = sample.Cc;
				});
				this.suggestion(values, localize('soil.lab.crIndex', "Cr (unloading)"), r.Cr, 3, '', () => (sample.consolidation ??= { points: [] }).Cr = round(r.Cr!, 3));
				this.suggestion(values, localize('soil.lab.e0', "e0 (first step)"), r.e0, 3, '', () => sample.e0 = round(r.e0!, 3));
				this.preconsolidationInput(values, sample);
				break;
			}
			case 'triaxial': {
				const specimens = sample.triaxial?.specimens ?? [];
				const type = sample.triaxial?.type ?? 'CU';
				const r = triaxialResult(type, specimens);
				renderShearChart(chart, { triaxial: specimens, type }, r);
				if (type === 'UU') {
					this.suggestion(values, localize('soil.lab.cuUU', "cu = (σ1 − σ3)/2, mean"), r.cu, 1, localize('soil.unit.kpa', "kPa"), () => sample.cu = round(r.cu!, 1));
				} else {
					this.suggestion(values, 'c′', r.c, 1, localize('soil.unit.kpa', "kPa"), () => sample.c = round(r.c!, 1));
					this.suggestion(values, 'φ′', r.phi, 1, '°', () => sample.phi = round(r.phi!, 1));
				}
				append(values, $('p.soil-note', undefined, type === 'UU'
					? localize('soil.lab.uuNote', "Total stress circles; cu is half the mean deviator stress.")
					: localize('soil.lab.pqNote', "Effective stresses at failure on the p′–q diagram: q = a + p′ tan α, sin φ′ = tan α, c′ = a / cos φ′.")));
				break;
			}
			case 'directShear': {
				const specimens = sample.directShear?.specimens ?? [];
				const r = directShearResult(specimens);
				renderShearChart(chart, { direct: specimens }, r);
				this.suggestion(values, 'c′', r.c, 1, localize('soil.unit.kpa', "kPa"), () => sample.c = round(r.c!, 1));
				this.suggestion(values, 'φ′', r.phi, 1, '°', () => sample.phi = round(r.phi!, 1));
				append(values, $('p.soil-note', undefined, localize('soil.lab.dsNote', "Least squares line τ = c′ + σn tan φ′ through the peak stresses.")));
				break;
			}
		}
	}

	/** σ′p, entered: the Casagrande construction is the engineer's. */
	private preconsolidationInput(container: HTMLElement, sample: ISoilSample): void {
		const row = append(container, $('.soil-lab-value'));
		const label = localize('soil.lab.preconsolidation', "σ′p (Casagrande)");
		append(row, $('span.soil-lab-value-label', undefined, label));
		const input = append(row, $<HTMLInputElement>('input.soil-input.number.soil-lab-input', { type: 'text', spellcheck: 'false', 'aria-label': label }));
		const value = sample.consolidation?.preconsolidation;
		input.value = typeof value === 'number' ? formatNumber(value, 1) : '';
		append(row, $('span.soil-prop-unit', undefined, localize('soil.unit.kpa', "kPa")));
		const spec = { key: 'preconsolidation', label, kind: 'number' as const, min: 0, max: 100000 };
		this._register(addDisposableListener(input, EventType.CHANGE, () => {
			const parsed = parseField(spec, input.value);
			input.classList.toggle('invalid', !!parsed.error);
			input.title = parsed.error ?? '';
			if (parsed.error) {
				return;
			}
			const consolidation = sample.consolidation ??= { points: [] };
			if (typeof parsed.value === 'number') {
				consolidation.preconsolidation = parsed.value;
			} else {
				delete consolidation.preconsolidation;
				pruneLabTests(sample);
			}
			this.options.onDidWrite();
		}));
	}
}
