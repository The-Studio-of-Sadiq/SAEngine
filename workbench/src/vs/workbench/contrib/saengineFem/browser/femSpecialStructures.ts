/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Alpha 9 L9: what the FEM results show of the bridges and special structures of Project
 * Settings (`saengine.special.project.run_project`): plain data, and the sheets and chart series
 * built from it, no DOM. The backend gives each structure its sheets and charts already; this
 * module only types them and turns them into the views' sheets and series.
 */

import { localize } from '../../../../nls.js';
import { FemTableCell } from '../../../../platform/saengine/common/femSolver.js';
import { ChartColor, IChartSeries } from './femChart.js';
import { IFemSheet } from './femChartData.js';

/** `(model: URI, run: boolean) => IFemSpecialStructures`: the last run kept beside the analysis model, or (run) a new one. */
export const FEM_SPECIAL_STRUCTURES_COMMAND = 'saengine.fem.specialStructures';

export interface IFemSpecialSheet {
	readonly name: string;
	readonly columns: readonly string[];
	readonly rows: readonly (readonly FemTableCell[])[];
	readonly fails?: readonly boolean[];
}

export interface IFemSpecialChart {
	readonly title: string;
	readonly xLabel: string;
	readonly yLabel: string;
	readonly series: readonly { readonly name: string; readonly points: readonly (readonly number[])[] }[];
}

export interface IFemSpecialSection {
	readonly title: string;
	readonly error?: string;
	readonly sheets: readonly IFemSpecialSheet[];
	readonly charts: readonly IFemSpecialChart[];
	readonly notes: readonly string[];
}

export interface IFemSpecialStructures {
	readonly available: boolean;
	/** Whether Project Settings has any bridge or special structure. */
	readonly configured?: boolean;
	readonly reason?: string;
	/** The code pack's name. */
	readonly code?: string;
	readonly sections?: readonly IFemSpecialSection[];
}

/** Whether there is a run to show. */
export function hasSpecialStructures(found: IFemSpecialStructures | undefined): found is IFemSpecialStructures & { readonly sections: readonly IFemSpecialSection[] } {
	return !!found && found.available && Array.isArray(found.sections);
}

const COLORS: readonly ChartColor[] = ['blue', 'orange', 'green', 'purple', 'red', 'yellow'];

/** A chart's series, coloured in turn. */
export function specialSeries(chart: IFemSpecialChart): IChartSeries[] {
	return chart.series.map((s, k) => ({ name: s.name, points: s.points, color: COLORS[k % COLORS.length] }));
}

/** A sheet with the failing rows marked in an extra column. */
export function specialSheet(sheet: IFemSpecialSheet): IFemSheet {
	const fails = sheet.fails ?? [];
	if (!fails.some(f => f)) {
		return { name: sheet.name, columns: sheet.columns, rows: sheet.rows };
	}
	const fail = localize('femSpecial.fails', "fails");
	const ok = '';
	return {
		name: sheet.name,
		columns: [...sheet.columns, localize('femSpecial.result', "Result")],
		rows: sheet.rows.map((row, k) => [...row, fails[k] ? fail : ok]),
	};
}

/** The heading's help: what the section holds and the pack it follows. */
export function specialHelp(found: IFemSpecialStructures): string {
	return found.code
		? localize('femSpecial.help', "Bridges, lattice towers, silos, chimneys, cooling towers, offshore structures and piping of Project Settings, by the code pack {0}: their loads, checks and what the checks leave out.", found.code)
		: localize('femSpecial.helpPlain', "Bridges, lattice towers, silos, chimneys, cooling towers, offshore structures and piping of Project Settings, by the project's code pack.");
}
