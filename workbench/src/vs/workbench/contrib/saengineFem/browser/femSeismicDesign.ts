/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { URI } from '../../../../base/common/uri.js';
import { designArguments } from './femDesign.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';

/*
 * The seismic design from the response spectrum and the second-order analysis of a run: desktop
 * commands of the Python backend (`saengine.fem.seismic_design.seismic_design`,
 * `saengine.fem.second_order.drift_amplification`), each taking `{outDir, projectPath}`. Until
 * they are registered, or when they return null (the project does not use them), the results
 * view says nothing of them.
 */

/** `{outDir, projectPath} => IFemSeismicDesign | null`: the response spectrum scaled for design. */
export const SEISMIC_DESIGN_COMMAND = 'saengine.fem.seismicDesign';
/** `{outDir, projectPath} => IFemSecondOrder | null`: what the second-order (P-Delta) analysis changed. */
export const SECOND_ORDER_COMMAND = 'saengine.fem.secondOrder';

/** A value per direction, or one for both. */
export type FemPerDirection = number | { readonly x?: number | null; readonly y?: number | null };

/** How the response spectrum base shear is scaled up to the share of the static one the code asks. */
export interface IFemSeismicScale {
	/** Factor applied to the RS results along X and Y (1 when they already reach the share). */
	readonly x: number | null;
	readonly y: number | null;
	/** Equivalent static base shear [kN]. */
	readonly vStatic: FemPerDirection | null;
	/** Response spectrum base shear before scaling [kN]. */
	readonly vDynamic: FemPerDirection | null;
	/** The share of the static base shear it is scaled to (0.85). */
	readonly fraction: number;
	/** The clause asking it ("BNBC 2020 Part 6 Sec 2.5.9.4 (p. 635)"). */
	readonly clause: string;
}

/** A design load combination with the scaled spectrum as E. */
export type FemSeismicCombination = string | {
	readonly name: string;
	readonly clause?: string | null;
	readonly description?: string | null;
};

/** A storey's design drift from the response spectrum, Cd / I × (Δ RS + Δ torsion), in m. */
export interface IFemSeismicDrift {
	/** "X" or "Y". */
	readonly direction: string;
	/** Elevations of the storey's floor and ceiling [m]. */
	readonly bottom: number;
	readonly top: number;
	/** Drift ratio Δ / h and the allowed one. */
	readonly ratio: number;
	readonly allowableRatio?: number | null;
	readonly ok?: boolean | null;
}

/** A floor's accidental torsion: its static force [kN], extent [m] and torsional moment [kN·m]. */
export interface IFemTorsionLevel {
	readonly z?: number | null;
	readonly force?: number | null;
	readonly L?: number | null;
	readonly moment?: number | null;
}

function hasTorsionMoment(level: IFemTorsionLevel): boolean {
	return typeof level.moment === 'number' && Math.abs(level.moment) > 0;
}

/** Content of {@link SEISMIC_DESIGN_COMMAND}'s result (`saengine.seismicDesign/1`). */
export interface IFemSeismicDesign {
	/** False when the run has no response spectrum results: then only `notes` say why. */
	readonly available?: boolean;
	readonly scale?: IFemSeismicScale;
	readonly combinations?: readonly FemSeismicCombination[];
	readonly drift?: readonly IFemSeismicDrift[] | null;
	/** Whether the 100 % + 30 % rule is applied (or a text saying how). */
	readonly orthogonal?: boolean | string | null;
	/** The floors' accidental torsion per direction (`{X: [...], Y: [...]}`), or a text. */
	readonly torsion?: string | { readonly [axis: string]: readonly IFemTorsionLevel[] } | null;
	/** Seismic Design Category ("D"). */
	readonly category?: string | null;
	/** Cd / I applied to the drift. */
	readonly amplification?: number | null;
	readonly clauses?: { readonly [name: string]: string } | null;
	readonly notes?: readonly string[] | null;
}

/** A storey's drift with the second-order analysis and without it. */
export interface IFemSecondOrderStorey {
	/** Elevations of the storey [m]. */
	readonly from: number;
	readonly to: number;
	/** Second-order drift / first-order drift; null when the first-order drift is zero. */
	readonly ratio: number | null;
	/** The stability coefficient it implies, θ = 1 - 1 / ratio. */
	readonly theta?: number | null;
}

/** A lateral case's drift amplification. */
export interface IFemSecondOrderCase {
	/** "EX", "WY". */
	readonly case: string;
	readonly storeys: readonly IFemSecondOrderStorey[];
	readonly maxRatio?: number | null;
}

/** Content of {@link SECOND_ORDER_COMMAND}'s result (`drift_amplification` with the options). */
export interface IFemSecondOrder {
	/** "none" for a first-order run (then nothing is shown); "pDelta" when omitted. */
	readonly method?: 'none' | 'pDelta';
	/** Section stiffness: gross, or ACI 318-19 6.6.3.1.1 cracked modifiers. */
	readonly stiffness?: 'gross' | 'aci' | null;
	readonly cases: readonly IFemSecondOrderCase[];
	readonly notes?: readonly string[] | null;
}

export type FemAxis = 'x' | 'y';

async function optionalCommand<T>(commandService: ICommandService, id: string, model: URI): Promise<T | undefined> {
	if (!CommandsRegistry.getCommand(id)) {
		return undefined;
	}
	return await commandService.executeCommand<T>(id, designArguments(model)) ?? undefined;
}

/** The response spectrum design of `model`'s run; undefined when the backend or the project has none. */
export function runSeismicDesign(commandService: ICommandService, model: URI): Promise<IFemSeismicDesign | undefined> {
	return optionalCommand<IFemSeismicDesign>(commandService, SEISMIC_DESIGN_COMMAND, model);
}

/** The second-order analysis of `model`'s run; undefined when the backend or the project has none. */
export function runSecondOrder(commandService: ICommandService, model: URI): Promise<IFemSecondOrder | undefined> {
	return optionalCommand<IFemSecondOrder>(commandService, SECOND_ORDER_COMMAND, model);
}

/** The direction of a response spectrum result ("RX: Response spectrum X", "EY"); undefined if none. */
export function spectrumAxis(label: string): FemAxis | undefined {
	const axis = /^(?:R|E)(?<axis>[XY])\b/i.exec(label)?.groups?.axis ?? /spectrum\s+(?<axis>[XY])\b/i.exec(label)?.groups?.axis;
	return axis ? axis.toLowerCase() as FemAxis : undefined;
}

function perDirection(value: FemPerDirection | null, axis: FemAxis): number | undefined {
	if (typeof value === 'number') {
		return value;
	}
	const v = value?.[axis];
	return typeof v === 'number' ? v : undefined;
}

function formatShear(value: number): string {
	return localize('femSeismic.kN', "{0} kN", formatNumber(value));
}

/** A share as a percentage, trimmed ("85 %"): for a code's fraction, not a measured value. */
function percent(fraction: number, digits = 1): string {
	return localize('femSeismic.percent', "{0} %", Number((fraction * 100).toFixed(digits)));
}

/** A measured ratio as a percentage with fixed decimals ("0.10 %"), so a list lines up. */
function fixedPercent(fraction: number): string {
	return localize('femSeismic.percentFixed', "{0} %", (fraction * 100).toFixed(2));
}

function elevations(bottom: number, top: number): string {
	return localize('femSeismic.elevations', "{0} to {1} m", Number(bottom.toFixed(2)), Number(top.toFixed(2)));
}

/**
 * "EX scaled × 1.18 to 85 % of the static base shear (dynamic …, static …), BNBC …", or that it
 * needs no scaling. Undefined without a factor for the direction.
 */
export function describeScale(design: IFemSeismicDesign | undefined, axis: FemAxis): string | undefined {
	const scale = design?.available === false ? undefined : design?.scale;
	const factor = scale?.[axis];
	if (!scale || typeof factor !== 'number') {
		return undefined;
	}
	const name = axis === 'x' ? 'EX' : 'EY';
	const share = percent(scale.fraction);
	const vStatic = perDirection(scale.vStatic, axis);
	const vDynamic = perDirection(scale.vDynamic, axis);
	if (vDynamic !== undefined && vDynamic <= 0) {
		return undefined; // no response spectrum case along this direction: nothing was scaled
	}
	if (vStatic !== undefined && vStatic <= 0) {
		return localize('femSeismic.noStatic', "{0} not scaled: there is no equivalent static base shear to compare it with.", name);
	}
	const shears = vStatic !== undefined && vDynamic !== undefined
		? localize('femSeismic.shears', " (dynamic {0}, static {1})", formatShear(vDynamic), formatShear(vStatic))
		: '';
	return factor > 1 + 1e-6
		? localize('femSeismic.scaled', "{0} scaled × {1} to {2} of the static base shear{3}, {4}.", name, factor.toFixed(2), share, shears, scale.clause)
		: localize('femSeismic.notScaled', "{0} not scaled: its base shear is at least {1} of the static one{2}, {3}.", name, share, shears, scale.clause);
}

/**
 * {@link describeScale} on a response spectrum result itself: the values shown there are the
 * spectrum's own, so a factor above 1 says it applies to the design forces only (Sec 2.5.9.4
 * leaves the drifts unscaled).
 */
export function describeScaleOnResult(design: IFemSeismicDesign | undefined, axis: FemAxis): string | undefined {
	const text = describeScale(design, axis);
	const factor = design?.scale?.[axis];
	return text && typeof factor === 'number' && factor > 1 + 1e-6
		? localize('femSeismic.scaledOnResult', "{0} Shown unscaled: the factor applies to the design forces, not to these results or the drifts.", text)
		: text;
}

/**
 * The largest design drift with how it is found: "… Design drift = spectrum drift × Cd / I
 * (Cd / I = 4.50)." Undefined without drifts.
 */
export function describeDesignDrift(design: IFemSeismicDesign | undefined): string | undefined {
	const drift = describeDrift(design);
	return drift && typeof design?.amplification === 'number'
		? localize('femSeismic.driftCd', "{0} Design drift = spectrum drift × Cd / I (Cd / I = {1}).", drift, design.amplification.toFixed(2))
		: drift;
}

/** One line of the Properties panel's seismic design section. */
export type FemSeismicItem =
	| { readonly kind: 'heading' | 'note'; readonly text: string }
	| { readonly kind: 'row'; readonly name: string; readonly value: string }
	| { readonly kind: 'combination'; readonly name: string; readonly detail?: string };

/**
 * The Properties panel's section on the response spectrum scaled for design: the factor of each
 * direction (or of `axis` only), the category, the orthogonal rule, accidental torsion and the
 * design drift (per storey without `combinations`); with `combinations`, the design combinations
 * with the scaled spectrum as E. Empty when the project does not design from it (no result). When
 * it does but the run has no spectrum (`available: false`), the heading and the backend's notes
 * only, so the engineer sees why (e.g. "enable Response spectrum").
 */
export function seismicSection(design: IFemSeismicDesign | undefined, axis: FemAxis | undefined, combinations: boolean): FemSeismicItem[] {
	if (!design) {
		return [];
	}
	const items: FemSeismicItem[] = [{ kind: 'heading', text: localize('femSeismic.heading', "Seismic Design (Response Spectrum)") }];
	const note = (text: string | undefined) => {
		if (text) {
			items.push({ kind: 'note', text });
		}
	};
	if (design.available !== false) {
		for (const direction of axis ? [axis] : ['x', 'y'] as const) {
			note(describeScale(design, direction));
		}
		if (design.category) {
			items.push({ kind: 'row', name: localize('femSeismic.category', "Seismic Design Category"), value: design.category });
		}
		const orthogonal = describeOrthogonal(design);
		note(orthogonal && localize('femSeismic.orthogonalNote', "Orthogonal effects: {0}.", orthogonal));
		const torsion = describeTorsion(design);
		note(torsion && localize('femSeismic.torsionNote', "Accidental torsion: {0}.", torsion));
		const drift = describeDesignDrift(design);
		note(drift);
		if (drift && !combinations) {
			items.push(...storeyDriftRows(design).map(row => ({ kind: 'row' as const, ...row })));
		}
		if (combinations && design.combinations?.length) {
			items.push({ kind: 'heading', text: localize('femSeismic.combinations', "Seismic Combinations") });
			for (const combination of design.combinations) {
				const detail = combinationDetail(combination);
				items.push({ kind: 'combination', name: combinationName(combination), ...(detail ? { detail } : {}) });
			}
		}
	}
	for (const text of design.notes ?? []) {
		note(text);
	}
	return items;
}

/** The name of a seismic design combination. */
export function combinationName(combination: FemSeismicCombination): string {
	return typeof combination === 'string' ? combination : combination.name;
}

/** The clause or description of a seismic design combination, if it has one. */
export function combinationDetail(combination: FemSeismicCombination): string | undefined {
	return typeof combination === 'string' ? undefined : combination.description ?? combination.clause ?? undefined;
}

/** How the orthogonal effects are combined: "100 % + 30 %" or "one direction at a time". */
export function describeOrthogonal(design: IFemSeismicDesign | undefined): string | undefined {
	const orthogonal = design?.orthogonal;
	if (typeof orthogonal === 'string') {
		return orthogonal || undefined;
	}
	if (typeof orthogonal !== 'boolean') {
		return undefined;
	}
	const clause = design?.clauses?.orthogonal;
	const rule = orthogonal ? localize('femSeismic.orthogonal', "100 % + 30 %") : localize('femSeismic.oneDirection', "one direction at a time");
	return clause ? localize('femSeismic.withClause', "{0} ({1})", rule, clause) : rule;
}

/** The accidental torsion: "5 % eccentricity, static torsion cases AX, AY", or undefined when none. */
export function describeTorsion(design: IFemSeismicDesign | undefined): string | undefined {
	const torsion = design?.torsion;
	if (typeof torsion === 'string') {
		return torsion || undefined;
	}
	// The backend lists every floor, also those without a torsional moment (no static force or no
	// extent): only a direction with a moment has a torsion case.
	const axes = Object.entries(torsion ?? {}).filter(([, levels]) => levels.some(hasTorsionMoment)).map(([axis]) => `A${axis.toUpperCase()}`);
	if (!axes.length) {
		return undefined;
	}
	const text = localize('femSeismic.torsion', "5 % eccentricity, static torsion cases {0}", axes.join(', '));
	const clause = design?.clauses?.torsion;
	return clause ? localize('femSeismic.withClause', "{0} ({1})", text, clause) : text;
}

/** "Largest drift 0.62 % (allowed 2.00 %) at 3.2 to 6.4 m, Y": the design drift from the spectrum. */
export function describeDrift(design: IFemSeismicDesign | undefined): string | undefined {
	let largest: IFemSeismicDrift | undefined;
	for (const storey of design?.drift ?? []) {
		if (!largest || storey.ratio > largest.ratio) {
			largest = storey;
		}
	}
	if (!largest) {
		return undefined;
	}
	const at = elevations(largest.bottom, largest.top);
	const text = typeof largest.allowableRatio === 'number'
		? localize('femSeismic.driftLimit', "Largest drift {0} (allowed {1}) at {2}, {3}", fixedPercent(largest.ratio), fixedPercent(largest.allowableRatio), at, largest.direction)
		: localize('femSeismic.drift', "Largest drift {0} at {1}, {2}", fixedPercent(largest.ratio), at, largest.direction);
	return largest.ok === false ? localize('femSeismic.driftExceeds', "{0}: exceeds the allowed drift.", text) : localize('femSeismic.driftEnd', "{0}.", text);
}

/** The drift per storey as rows: "3.2 to 6.4 m" → "0.41 % X, 0.62 % Y" (with "exceeds"). */
export function storeyDriftRows(design: IFemSeismicDesign | undefined): { readonly name: string; readonly value: string }[] {
	const storeys = new Map<string, IFemSeismicDrift[]>();
	for (const row of design?.drift ?? []) {
		const key = elevations(row.bottom, row.top);
		storeys.set(key, [...storeys.get(key) ?? [], row]);
	}
	return [...storeys].map(([name, rows]) => {
		const value = rows.map(r => localize('femSeismic.driftAxis', "{0} {1}", fixedPercent(r.ratio), r.direction)).join(', ');
		return { name, value: rows.some(r => r.ok === false) ? localize('femSeismic.storeyExceeds', "{0} (exceeds)", value) : value };
	});
}

function isSecondOrderRun(secondOrder: IFemSecondOrder | undefined): secondOrder is IFemSecondOrder {
	return !!secondOrder && secondOrder.method !== 'none';
}

/** The largest drift amplification of the second-order analysis, with its case and storey. */
export function largestAmplification(secondOrder: IFemSecondOrder | undefined): { readonly factor: number; readonly case: string; readonly storey: string } | undefined {
	let largest: { factor: number; case: string; storey: string } | undefined;
	for (const lateral of isSecondOrderRun(secondOrder) ? secondOrder.cases : []) {
		for (const storey of lateral.storeys) {
			if (typeof storey.ratio === 'number' && (!largest || storey.ratio > largest.factor)) {
				largest = { factor: storey.ratio, case: lateral.case, storey: elevations(storey.from, storey.to) };
			}
		}
	}
	return largest;
}

/**
 * The results bar's "Second order" note: "Second order (P-Delta): storey drifts amplified up to
 * × 1.08 (EX, 3.2 to 6.4 m)." Undefined when the run is first order.
 */
export function describeSecondOrder(secondOrder: IFemSecondOrder | undefined): string | undefined {
	if (!isSecondOrderRun(secondOrder)) {
		return undefined;
	}
	const largest = largestAmplification(secondOrder);
	const stiffness = secondOrder.stiffness === 'aci' ? localize('femSeismic.cracked', ", cracked section stiffness") : '';
	return largest
		? localize('femSeismic.secondOrder', "Second order (P-Delta{0}): storey drifts amplified up to × {1} ({2}, {3}).", stiffness, largest.factor.toFixed(2), largest.case, largest.storey)
		: localize('femSeismic.secondOrderOnly', "Second order (P-Delta{0}).", stiffness);
}

/**
 * Whether a result is a first-order reference analysis that the second-order run adds beside a
 * lateral case ("EX-1: …, first order (P-Delta reference)"): no second-order note belongs on it.
 */
export function isFirstOrderReference(label: string): boolean {
	return /first order \(P-Delta reference\)\s*$/i.test(label);
}

/** The drift amplification per storey as rows: "0 to 3.2 m" → "× 1.05 EX, × 1.08 EY". */
export function storeyAmplificationRows(secondOrder: IFemSecondOrder | undefined): { readonly name: string; readonly value: string }[] {
	const storeys = new Map<string, string[]>();
	for (const lateral of isSecondOrderRun(secondOrder) ? secondOrder.cases : []) {
		for (const storey of lateral.storeys) {
			if (typeof storey.ratio === 'number') {
				const key = elevations(storey.from, storey.to);
				storeys.set(key, [...storeys.get(key) ?? [], localize('femSeismic.amplificationCase', "× {0} {1}", storey.ratio.toFixed(2), lateral.case)]);
			}
		}
	}
	return [...storeys].map(([name, values]) => ({ name, value: values.join(', ') }));
}
