/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatNumber, IConsolidationPoint, IFieldSpec, IShearSpecimen, ISieve, ISoilSample, ITriaxialSpecimen, parseField } from './soilDocument.js';
import { ISheet, ISheetCellError, ISheetColumn, ISheetGroup, ISheetWrite, ISheetWriteResult } from './soilSheet.js';

/*
 * The lab tests of one sample: the grain size analysis (sieves), the oedometer (e–log p), the
 * triaxial and the direct shear specimens. What follows from them by the usual textbook steps is
 * worked out here as a suggestion the engineer can take into the sample's values (the sample's
 * fines content, Cc, c′, φ′, cu); nothing computed is stored without that click.
 */

export type LabTest = 'grainSize' | 'consolidation' | 'triaxial' | 'directShear';

export const LAB_TESTS: readonly { readonly test: LabTest; readonly label: string }[] = [
	{ test: 'grainSize', label: localize('soil.lab.grainSize', "Grain size") },
	{ test: 'consolidation', label: localize('soil.lab.consolidation', "Consolidation") },
	{ test: 'triaxial', label: localize('soil.lab.triaxial', "Triaxial") },
	{ test: 'directShear', label: localize('soil.lab.directShear', "Direct shear") },
];

/** The fines boundary: the 75 µm sieve (No. 200) [mm]. */
export const FINES_SIZE = 0.075;

// ───────────────────────────── grain size ─────────────────────────────

export interface IGrainSizeResult {
	/** Passing the 75 µm sieve [%], interpolated on the log of the size when not sieved exactly. */
	readonly fines?: number;
	readonly D10?: number;
	readonly D30?: number;
	readonly D60?: number;
	/** Coefficient of uniformity D60/D10 and of curvature D30²/(D10·D60). */
	readonly Cu?: number;
	readonly Cc?: number;
}

/** The sieves from the coarsest down, with sizes and passing that are numbers. */
function sortedSieves(sieves: readonly ISieve[]): ISieve[] {
	return sieves.filter(s => Number.isFinite(s.size) && s.size > 0 && Number.isFinite(s.passing)).sort((a, b) => b.size - a.size);
}

/** The size at which `percent` passes, interpolated linearly in log(size) between the sieves around it. */
export function sizeAtPassing(sieves: readonly ISieve[], percent: number): number | undefined {
	const s = sortedSieves(sieves);
	for (let i = 0; i + 1 < s.length; i++) {
		const [a, b] = [s[i], s[i + 1]];
		if (a.passing === percent) {
			return a.size;
		}
		if (b.passing === percent) {
			return b.size;
		}
		if (a.passing > percent && b.passing < percent) {
			const t = (percent - b.passing) / (a.passing - b.passing);
			return Math.pow(10, Math.log10(b.size) + t * (Math.log10(a.size) - Math.log10(b.size)));
		}
	}
	return s.length && s[s.length - 1].passing === percent ? s[s.length - 1].size : undefined;
}

/** The percent passing a size, interpolated in log(size); undefined outside the sieves. */
export function passingAtSize(sieves: readonly ISieve[], size: number): number | undefined {
	const s = sortedSieves(sieves);
	for (let i = 0; i + 1 < s.length; i++) {
		const [a, b] = [s[i], s[i + 1]];
		if (a.size >= size && b.size <= size) {
			if (a.size === b.size) {
				return a.passing;
			}
			const t = (Math.log10(size) - Math.log10(b.size)) / (Math.log10(a.size) - Math.log10(b.size));
			return b.passing + t * (a.passing - b.passing);
		}
	}
	return s.find(x => x.size === size)?.passing;
}

export function grainSizeResult(sieves: readonly ISieve[]): IGrainSizeResult {
	const D10 = sizeAtPassing(sieves, 10);
	const D30 = sizeAtPassing(sieves, 30);
	const D60 = sizeAtPassing(sieves, 60);
	const fines = passingAtSize(sieves, FINES_SIZE);
	return {
		fines, D10, D30, D60,
		Cu: D10 && D60 ? D60 / D10 : undefined,
		Cc: D10 && D30 && D60 ? D30 * D30 / (D10 * D60) : undefined,
	};
}

// ───────────────────────────── consolidation ─────────────────────────────

export interface IConsolidationResult {
	/** The steepest slope −Δe/Δlog p of the loading points (the virgin compression line). */
	readonly Cc?: number;
	/** The slope of the unloading points, when the test unloads. */
	readonly Cr?: number;
	/** The void ratio of the first point. */
	readonly e0?: number;
}

/**
 * Cc and Cr from the points of an oedometer test in the order they were applied: the loading
 * branch (pressure going up) gives Cc as its steepest segment, the unloading branch Cr as the
 * slope from its start to its end. σ′p (Casagrande's construction) is left to the engineer.
 */
export function consolidationResult(points: readonly IConsolidationPoint[]): IConsolidationResult {
	const valid = points.filter(p => Number.isFinite(p.pressure) && p.pressure > 0 && Number.isFinite(p.e));
	let Cc: number | undefined;
	let peak = 0;
	for (let i = 0; i + 1 < valid.length; i++) {
		const [a, b] = [valid[i], valid[i + 1]];
		if (b.pressure > a.pressure) {
			const slope = -(b.e - a.e) / (Math.log10(b.pressure) - Math.log10(a.pressure));
			Cc = Cc === undefined ? slope : Math.max(Cc, slope);
			peak = i + 1;
		} else {
			break;
		}
	}
	const unloading = valid.slice(peak);
	let Cr: number | undefined;
	if (unloading.length > 1) {
		const [a, b] = [unloading[0], unloading[unloading.length - 1]];
		if (b.pressure < a.pressure) {
			Cr = -(b.e - a.e) / (Math.log10(b.pressure) - Math.log10(a.pressure));
		}
	}
	return { Cc, Cr, e0: valid[0]?.e };
}

// ───────────────────────────── shear strength ─────────────────────────────

/** The least squares line y = a + b·x through the points; undefined below two distinct x. */
export function fitLine(points: readonly { readonly x: number; readonly y: number }[]): { readonly a: number; readonly b: number } | undefined {
	const n = points.length;
	if (n < 2) {
		return undefined;
	}
	const mx = points.reduce((s, p) => s + p.x, 0) / n;
	const my = points.reduce((s, p) => s + p.y, 0) / n;
	const sxx = points.reduce((s, p) => s + (p.x - mx) ** 2, 0);
	if (sxx <= 0) {
		return undefined;
	}
	const b = points.reduce((s, p) => s + (p.x - mx) * (p.y - my), 0) / sxx;
	return { a: my - b * mx, b };
}

export interface IShearResult {
	/** Cohesion [kPa] and friction angle [°] of the Mohr-Coulomb line. */
	readonly c?: number;
	readonly phi?: number;
	/** Undrained strength (UU): half the mean deviator stress [kPa]. */
	readonly cu?: number;
}

/** The Mohr-Coulomb line τ = c + σ tan φ through the direct shear specimens. */
export function directShearResult(specimens: readonly IShearSpecimen[]): IShearResult {
	const line = fitLine(specimens.filter(s => Number.isFinite(s.normal) && Number.isFinite(s.shear)).map(s => ({ x: s.normal, y: s.shear })));
	if (!line) {
		return {};
	}
	return { c: Math.max(0, line.a), phi: Math.atan(line.b) * 180 / Math.PI };
}

/**
 * The strength of the triaxial specimens. UU: cu is half the mean deviator stress. CU and CD:
 * the effective stresses at failure (σ′ = σ − u) on the p′–q diagram, q = a + p′ tan α, give
 * sin φ′ = tan α and c′ = a / cos φ′.
 */
export function triaxialResult(type: 'UU' | 'CU' | 'CD' | undefined, specimens: readonly ITriaxialSpecimen[]): IShearResult {
	const valid = specimens.filter(s => Number.isFinite(s.cell) && Number.isFinite(s.deviator) && s.deviator > 0);
	if (!valid.length) {
		return {};
	}
	if (type === 'UU') {
		return { cu: valid.reduce((sum, s) => sum + s.deviator, 0) / valid.length / 2 };
	}
	const line = fitLine(valid.map(s => {
		const u = type === 'CU' && typeof s.porePressure === 'number' ? s.porePressure : 0;
		const s3 = s.cell - u;
		const s1 = s3 + s.deviator;
		return { x: (s1 + s3) / 2, y: (s1 - s3) / 2 };
	}));
	if (!line || line.b <= 0 || line.b >= 1) {
		return {};
	}
	const phi = Math.asin(line.b);
	return { c: Math.max(0, line.a / Math.cos(phi)), phi: phi * 180 / Math.PI };
}

// ───────────────────────────── the specimen tables as sheets ─────────────────────────────

const KPA = localize('soil.unit.kpa', "kPa");

interface ILabColumn {
	readonly spec: IFieldSpec;
	readonly width?: number;
}

/**
 * A list of a lab test (the sieves, the load steps, the specimens) as a sheet: each item a row,
 * each field a column; rows written past the end are added, and the list is kept in its order.
 */
type LabItem = { [key: string]: unknown };

/** Orders the items by a field: the largest first when `descending`; items without it last. */
function byField(key: string, descending = false): (a: LabItem, b: LabItem) => number {
	const value = (item: LabItem) => typeof item[key] === 'number' ? item[key] as number : (descending ? -Infinity : Infinity);
	return (a, b) => descending ? value(b) - value(a) : value(a) - value(b);
}

class LabListSheet implements ISheet {

	readonly groups: readonly ISheetGroup[];
	readonly columns: readonly ISheetColumn[];

	constructor(
		readonly id: string,
		readonly label: string,
		private readonly fields: readonly ILabColumn[],
		/** The test's list, if the sample has the test. */
		private readonly read: () => LabItem[] | undefined,
		/** The test's list, made when missing. */
		private readonly ensure: () => LabItem[],
		/** Drops the test's object again when it is left empty. */
		private readonly prune: () => void,
		private readonly order?: (a: LabItem, b: LabItem) => number,
	) {
		this.groups = [{ id: id, label }];
		this.columns = fields.map(({ spec, width }) => ({ id: spec.key, group: id, label: spec.label, unit: spec.unit, title: spec.title, width: width ?? 76, numeric: true }));
	}

	rowCount(): number {
		return this.read()?.length ?? 0;
	}

	text(row: number, column: ISheetColumn): string {
		const value = this.read()?.[row]?.[column.id];
		return typeof value === 'number' ? formatNumber(value, value !== 0 && Math.abs(value) < 0.01 ? 6 : 4) : '';
	}

	editText(row: number, column: ISheetColumn): string {
		return this.text(row, column);
	}

	isReadOnly(): boolean {
		return false;
	}

	isDerived(): boolean {
		return false;
	}

	problem(): undefined {
		return undefined;
	}

	hint(): undefined {
		return undefined;
	}

	write(writes: readonly ISheetWrite[]): ISheetWriteResult {
		const list = this.ensure();
		const targets = new Map<number, LabItem>();
		const errors: ISheetCellError[] = [];
		let added = 0;
		let written = 0;
		for (const w of [...writes].sort((a, b) => a.row - b.row)) {
			const field = this.fields.find(f => f.spec.key === w.column);
			if (!field || w.row >= list.length && !targets.has(w.row) && !w.text.trim()) {
				continue;
			}
			const parsed = parseField(field.spec, w.text);
			if (parsed.error) {
				errors.push({ row: w.row, column: w.column, message: parsed.error });
				continue;
			}
			let item = targets.get(w.row) ?? list[w.row];
			if (!item) {
				item = {};
				list.push(item);
				added++;
			}
			targets.set(w.row, item);
			if (parsed.value === undefined) {
				delete item[w.column];
			} else {
				item[w.column] = parsed.value;
			}
			written++;
		}
		// An item missing a required value is not an item.
		const required = this.fields.filter(f => f.spec.required).map(f => f.spec.key);
		for (let i = list.length - 1; i >= 0; i--) {
			if (required.some(key => typeof list[i][key] !== 'number')) {
				const emptied = this.fields.every(f => typeof list[i][f.spec.key] !== 'number');
				if (emptied) {
					list.splice(i, 1);
				}
			}
		}
		if (this.order) {
			list.sort(this.order);
		}
		this.prune();
		return { written, added, errors };
	}

	removeRows(rows: readonly number[]): void {
		const list = this.read();
		if (!list) {
			return;
		}
		const remove = new Set(rows.map(r => list[r]).filter(Boolean));
		const kept = list.filter(item => !remove.has(item));
		list.splice(0, list.length, ...kept);
		this.prune();
	}
}

/** The sheet of a lab test of a sample; the test's object is made on the first write. */
export function labSheet(sample: ISoilSample, test: LabTest): ISheet {
	const prune = () => pruneLabTests(sample);
	switch (test) {
		case 'grainSize':
			return new LabListSheet('grainSize', localize('soil.lab.sieves', "Sieves"), [
				{ spec: { key: 'size', label: localize('soil.lab.size', "Size"), unit: localize('soil.unit.mm', "mm"), kind: 'number', min: 0.0001, max: 300, required: true, title: localize('soil.lab.sizeTitle', "Sieve opening (or particle size of the hydrometer)") } },
				{ spec: { key: 'passing', label: localize('soil.lab.passing', "Passing"), unit: '%', kind: 'number', min: 0, max: 100, required: true } },
			], () => sample.grainSize?.sieves, () => (sample.grainSize ??= { sieves: [] }).sieves, prune, byField('size', true));
		case 'consolidation':
			return new LabListSheet('consolidation', localize('soil.lab.loadSteps', "Load steps"), [
				{ spec: { key: 'pressure', label: localize('soil.lab.pressure', "σ′v"), unit: KPA, kind: 'number', min: 0, max: 100000, required: true, title: localize('soil.lab.pressureTitle', "Effective vertical pressure of the load step") } },
				{ spec: { key: 'e', label: 'e', kind: 'number', min: 0, max: 20, required: true, title: localize('soil.lab.eTitle', "Void ratio at the end of the step") } },
			], () => sample.consolidation?.points, () => (sample.consolidation ??= { points: [] }).points, prune);
		case 'triaxial':
			return new LabListSheet('triaxial', localize('soil.lab.specimens', "Specimens"), [
				{ spec: { key: 'cell', label: 'σ3', unit: KPA, kind: 'number', min: 0, max: 10000, required: true, title: localize('soil.lab.cellTitle', "Cell pressure") } },
				{ spec: { key: 'deviator', label: 'σ1 − σ3', unit: KPA, kind: 'number', min: 0, max: 20000, required: true, title: localize('soil.lab.deviatorTitle', "Deviator stress at failure") }, width: 84 },
				{ spec: { key: 'porePressure', label: 'u', unit: KPA, kind: 'number', min: -1000, max: 10000, title: localize('soil.lab.uTitle', "Pore pressure at failure (CU)") } },
			], () => sample.triaxial?.specimens, () => (sample.triaxial ??= { specimens: [] }).specimens, prune, byField('cell'));
		case 'directShear':
			return new LabListSheet('directShear', localize('soil.lab.specimens', "Specimens"), [
				{ spec: { key: 'normal', label: 'σn', unit: KPA, kind: 'number', min: 0, max: 10000, required: true, title: localize('soil.lab.normalTitle', "Normal stress") } },
				{ spec: { key: 'shear', label: 'τ', unit: KPA, kind: 'number', min: 0, max: 10000, required: true, title: localize('soil.lab.shearTitle', "Peak shear stress") } },
			], () => sample.directShear?.specimens, () => (sample.directShear ??= { specimens: [] }).specimens, prune, byField('normal'));
	}
}

/** Whether the sample has entries of a test. */
export function hasLabTest(sample: ISoilSample, test: LabTest): boolean {
	switch (test) {
		case 'grainSize': return !!sample.grainSize?.sieves?.length;
		case 'consolidation': return !!sample.consolidation?.points?.length;
		case 'triaxial': return !!sample.triaxial?.specimens?.length;
		case 'directShear': return !!sample.directShear?.specimens?.length;
	}
}

/**
 * Drops the test objects a sheet made but left empty (an empty `grainSize: { sieves: [] }` is
 * not written to the file).
 */
export function pruneLabTests(sample: ISoilSample): void {
	if (sample.grainSize && !sample.grainSize.sieves?.length && Object.keys(sample.grainSize).length <= 1) {
		delete sample.grainSize;
	}
	if (sample.consolidation && !sample.consolidation.points?.length && Object.keys(sample.consolidation).length <= 1) {
		delete sample.consolidation;
	}
	if (sample.triaxial && !sample.triaxial.specimens?.length && Object.keys(sample.triaxial).length <= 1) {
		delete sample.triaxial;
	}
	if (sample.directShear && !sample.directShear.specimens?.length && Object.keys(sample.directShear).length <= 1) {
		delete sample.directShear;
	}
}
