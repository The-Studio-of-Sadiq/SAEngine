/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { checkSoilReport, formatNumber, IBorehole, ISoilProblem, ISoilReport } from './soilDocument.js';
import { sptBlows } from './soilSheet.js';

/*
 * The borehole entry screen's model, free of the DOM so it can be tested. A borehole is entered
 * (or edited) on one screen in the order of the consultant's log sheet: its details, its strata,
 * then its SPT records and lab results. The drawn log, the SPT graph and the results come after
 * "Create" (or "Save"); the views of the soil report show them.
 */

/** The views of the soil report: the drawn log, the results and the site map. */
export type SoilView = 'log' | 'results' | 'map';

/** The view a soil report opens on, and the one an entry returns to. */
export const DEFAULT_VIEW: SoilView = 'log';

export type EntryStep = 'details' | 'strata' | 'tests';

export interface IEntryStepInfo {
	readonly step: EntryStep;
	readonly label: string;
	readonly detail: string;
}

/** The steps of the entry screen, in the order of the log sheet. */
export const ENTRY_STEPS: readonly IEntryStepInfo[] = [
	{ step: 'details', label: localize('soil.entry.details', "Details"), detail: localize('soil.entry.detailsDetail', "ID, location, levels, termination depth, date and method") },
	{ step: 'strata', label: localize('soil.entry.strata', "Strata"), detail: localize('soil.entry.strataDetail', "the layers from the ground down: depths, soil type, description") },
	{ step: 'tests', label: localize('soil.entry.tests', "SPT and lab"), detail: localize('soil.entry.testsDetail', "the SPT blows (seat, N1, N2: N is worked out) and the lab results") },
];

/** The step a problem's path ("layers.2.bottom", "spt.0.depth", "depth") belongs to. */
export function entryStepOf(path: string | undefined): EntryStep {
	const head = path?.split('.')[0];
	return head === 'layers' ? 'strata' : head === 'spt' || head === 'samples' ? 'tests' : 'details';
}

/** A problem of the borehole being entered, with the step that fixes it. */
export interface IEntryProblem extends ISoilProblem {
	readonly step: EntryStep;
	/** Something not entered yet (not something entered wrongly): shown once the step was left or Create tried. */
	readonly missing?: boolean;
}

/**
 * The problems of one borehole in plain words: the report's checks (what the backend refuses is
 * an error) and what the log sheet needs before the borehole can be created: a termination
 * depth, at least one layer and a blow count for every SPT record.
 */
export function entryProblems(report: ISoilReport, index: number): IEntryProblem[] {
	const borehole = report.boreholes[index];
	if (!borehole) {
		return [];
	}
	const problems: IEntryProblem[] = checkSoilReport(report)
		.filter(p => p.index === index && p.path !== 'layers')
		.map(p => ({ ...p, message: withoutId(p.message, borehole), step: entryStepOf(p.path) }));
	const missing = (step: EntryStep, path: string, message: string) => problems.push({ index, borehole: borehole.id, path, message, severity: 'error', step, missing: true });
	if (typeof borehole.depth !== 'number') {
		missing('details', 'depth', localize('soil.entry.noDepth', "Enter the termination depth: how deep the borehole was drilled."));
	}
	if (!borehole.layers.length) {
		missing('strata', 'layers', localize('soil.entry.noLayers', "Add at least one layer: its top and bottom depth and soil type."));
	}
	borehole.spt.forEach((record, i) => {
		if (sptBlows(record) === undefined) {
			missing('tests', `spt.${i}.N1`, localize('soil.entry.noBlows', "The SPT at {0} m has no blow count: give N1 and N2 (or N, or mark the refusal).", formatNumber(record.depth / 1000, 2)));
		}
	});
	const order = ENTRY_STEPS.map(s => s.step);
	return problems.sort((a, b) => order.indexOf(a.step) - order.indexOf(b.step));
}

/** The report's messages start with the borehole's id; on its own entry screen that is said already. */
function withoutId(message: string, borehole: IBorehole): string {
	const prefix = `${borehole.id}: `;
	return borehole.id && message.startsWith(prefix) ? message.charAt(prefix.length).toUpperCase() + message.slice(prefix.length + 1) : message;
}

/** Whether the borehole can be created (or saved): no errors left; warnings may stay. */
export function canCreate(problems: readonly IEntryProblem[]): boolean {
	return !problems.some(p => p.severity === 'error');
}

/** The first step with an error, where "Create" takes the engineer when it cannot create yet. */
export function firstStepWithError(problems: readonly IEntryProblem[]): EntryStep | undefined {
	return ENTRY_STEPS.find(s => problems.some(p => p.step === s.step && p.severity === 'error'))?.step;
}

/** The state of the entry screen while it is open. */
export interface IEntryState {
	/** The borehole's place in the report. */
	index: number;
	step: EntryStep;
	/** A borehole added by this entry: Cancel removes it. */
	readonly isNew: boolean;
	/** The borehole as it was when an edit started: Cancel puts it back. */
	readonly snapshot?: string;
	/** The steps the engineer moved on from: their missing values are shown. */
	readonly left: Set<EntryStep>;
	/** "Create" (or "Save") was tried: every step's problems are shown. */
	tried: boolean;
}

/** The entry of a borehole just added: it starts at its details. */
export function newBoreholeEntry(index: number): IEntryState {
	return { index, step: 'details', isNew: true, left: new Set(), tried: false };
}

/** The entry of an existing borehole, at a step (its details unless a problem points elsewhere). */
export function editBoreholeEntry(index: number, borehole: IBorehole, step: EntryStep = 'details'): IEntryState {
	return { index, step, isNew: false, snapshot: JSON.stringify(borehole), left: new Set(), tried: false };
}

/** Moves to another step; the step left counts as seen. */
export function goToStep(state: IEntryState, step: EntryStep): void {
	if (step !== state.step) {
		state.left.add(state.step);
		state.step = step;
	}
}

/** The step after (1) or before (-1) the current one, if any. */
export function nextStep(step: EntryStep, direction: 1 | -1): EntryStep | undefined {
	const at = ENTRY_STEPS.findIndex(s => s.step === step);
	return ENTRY_STEPS[at + direction]?.step;
}

/**
 * The problems shown on a step: what was entered wrongly at once, what is still missing only
 * after the step was left or Create was tried, so a fresh form is not red all over.
 */
export function shownProblems(state: IEntryState, problems: readonly IEntryProblem[], step: EntryStep = state.step): IEntryProblem[] {
	const seen = state.tried || state.left.has(step);
	return problems.filter(p => p.step === step && (!p.missing || seen));
}
