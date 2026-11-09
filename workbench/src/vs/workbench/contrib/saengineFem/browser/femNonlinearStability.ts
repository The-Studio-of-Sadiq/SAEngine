/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Alpha 9 L4: what the FEM results show of the nonlinear stability analysis (GMNIA) and the
 * cables (`saengine.fem.nonlinear_stability.run_project`): plain data and the sheets and chart
 * series built from it, no DOM.
 */

import { localize } from '../../../../nls.js';
import { IChartSeries } from './femChart.js';
import { IFemSheet } from './femChartData.js';

/** `(model: URI, run: boolean) => IFemNonlinearStability`: the last analysis kept beside the results, or (run) a new one (minutes). */
export const FEM_NONLINEAR_STABILITY_COMMAND = 'saengine.fem.nonlinearStability';

export interface IFemStabilityCable {
	readonly cable: string;
	readonly pretension: number;
	readonly maxTension: number;
	readonly minTension: number;
	readonly sag: number;
	readonly slack: number;
	readonly segments: number;
	readonly resistance?: number | null;
	readonly utilisation?: number | null;
}

export interface IFemNonlinearStability {
	readonly available: boolean;
	readonly reason?: string;
	/** Whether the project sets the analysis (Project Settings, Analysis, Nonlinear stability). */
	readonly configured?: boolean;
	/** GMNIA, GMNA, GNIA or GNA. */
	readonly analysis?: string;
	readonly combination?: string;
	/** [λ, control displacement [m]] along the path. */
	readonly path?: readonly (readonly number[])[];
	readonly limitFactor?: number;
	readonly limitReached?: boolean;
	readonly alphaCr?: number | null;
	readonly ratio?: number | null;
	readonly required?: number;
	readonly ok?: boolean;
	readonly control?: { readonly node: number; readonly dof: number };
	readonly imperfection?: { readonly kind: 'eigenmode' | 'equivalent' | 'none'; readonly amplitude?: number; readonly governs?: string; readonly sway?: number; readonly bows?: number; readonly largestBow?: number; readonly direction?: string };
	readonly cables?: readonly IFemStabilityCable[];
	readonly stopped?: string;
	readonly code?: string;
	readonly source?: string;
	readonly notes?: readonly string[];
}

/** Whether there is an analysis to show (a project without the setting answers "not run yet"). */
export function hasStability(found: IFemNonlinearStability | undefined): found is IFemNonlinearStability {
	return !!found && found.available;
}

const DOF = ['X', 'Y', 'Z'];

/** The load-displacement path: λ against the control displacement [mm]. */
export function pathSeries(found: IFemNonlinearStability): IChartSeries[] {
	const points = (found.path ?? []).map(([lam, u]) => [1000 * u, lam]);
	return [{ name: localize('femStability.path', "Load factor λ"), points, color: 'blue' }];
}

export function pathXLabel(found: IFemNonlinearStability): string {
	const control = found.control;
	return control
		? localize('femStability.controlAxis', "Displacement of node {0} along {1} [mm]", control.node, DOF[control.dof - 1] ?? '')
		: localize('femStability.controlAxisPlain', "Control displacement [mm]");
}

/** The heading's help: the analysis, the combination, the imperfection, λu against αcr and the check. */
export function stabilityHelp(found: IFemNonlinearStability): string {
	const imp = found.imperfection;
	const imperfection = !imp || imp.kind === 'none'
		? localize('femStability.perfect', "the perfect frame")
		: imp.kind === 'eigenmode'
			? localize('femStability.eigenmode', "the first buckling mode scaled to {0} mm ({1})", (1000 * (imp.amplitude ?? 0)).toFixed(1), imp.governs ?? '')
			: localize('femStability.equivalent', "sway 1/{0} in {1} and bows of {2} members (largest {3} mm)", imp.sway ? (1 / imp.sway).toFixed(0) : '-', imp.direction ?? 'X', imp.bows ?? 0, (1000 * (imp.largestBow ?? 0)).toFixed(1));
	const limit = (found.limitFactor ?? 0).toFixed(3);
	const versus = found.alphaCr ? localize('femStability.versus', "αcr = {0}, λu / αcr = {1}", found.alphaCr.toFixed(3), (found.ratio ?? 0).toFixed(3)) : '';
	return [
		localize('femStability.basis', "{0} under {1} ({2})", found.analysis ?? '', found.combination ?? '', found.code ?? ''),
		localize('femStability.imperfection', "imperfection: {0}", imperfection),
		found.limitReached
			? localize('femStability.limit', "limit load factor λu = {0}", limit)
			: localize('femStability.rising', "λ = {0} when the path stopped, still rising (a lower bound)", limit),
		versus,
		localize('femStability.required', "required at least {0}: {1}", (found.required ?? 1).toFixed(2), found.ok ? localize('femStability.ok', "OK") : localize('femStability.fails', "fails")),
		found.stopped ? localize('femStability.stopped', "stopped: {0}", found.stopped) : '',
	].filter(s => !!s).join('; ');
}

/** The cables at λ = 1: tensions, sag, slack pieces and the check against the resistance. */
export function cableSheet(found: IFemNonlinearStability): IFemSheet {
	const kn = (v: number | null | undefined) => v === null || v === undefined ? '' : Number((v / 1000).toFixed(1));
	return {
		name: localize('femStability.cables', "Cables at the combination's loads (λ = 1)"),
		columns: [
			localize('femStability.cableCol', "Cable"), localize('femStability.pretensionCol', "Pretension [kN]"), localize('femStability.maxCol', "Largest T [kN]"),
			localize('femStability.minCol', "Least T [kN]"), localize('femStability.sagCol', "Sag [mm]"), localize('femStability.slackCol', "Slack pieces"),
			localize('femStability.resistanceCol', "Resistance [kN]"), localize('femStability.utilCol', "Utilisation"),
		],
		rows: (found.cables ?? []).map(c => [
			c.cable, kn(c.pretension), kn(c.maxTension), kn(c.minTension), Number((1000 * c.sag).toFixed(1)),
			`${c.slack} / ${c.segments}`, kn(c.resistance), c.utilisation === null || c.utilisation === undefined ? '' : Number(c.utilisation.toFixed(3)),
		]),
		notes: [localize('femStability.cableNote', "Tension-only co-rotational truss chains with their pretension; sag is the largest vertical distance below the chord between the cable's ends.")],
	};
}
