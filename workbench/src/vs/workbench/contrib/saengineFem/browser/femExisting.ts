/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Alpha 9 P4: what the FEM results show of an existing building's assessment and retrofit
 * (`saengine.fem.existing_building.assessment`): plain data and the sheets built from it, no DOM.
 */

import { localize } from '../../../../nls.js';
import { FemTableCell } from '../../../../platform/saengine/common/femSolver.js';
import { IFemSheet } from './femChartData.js';

/** `(model: URI) => IFemExistingAssessment`: the assessment of the last run (slow once). */
export const FEM_EXISTING_ASSESSMENT_COMMAND = 'saengine.fem.existingAssessment';

export type FemExistingState = 'asBuilt' | 'retrofitted';

export interface IFemExistingCheck {
	readonly ratio: number | null;
	readonly action?: string;
	readonly level?: string | null;
	readonly hinge?: string;
	readonly hazards?: { readonly [id: string]: number | null };
}

export interface IFemExistingRow {
	readonly member: string;
	readonly component: string;
	readonly type?: string;
	readonly measures?: readonly string[];
	readonly covered: boolean;
	readonly asBuilt?: IFemExistingCheck | null;
	readonly retrofitted?: IFemExistingCheck | null;
	/** Where the other state's ratio comes from: its own run, or this run's demands. */
	readonly otherFrom?: 'run' | 'preview';
	readonly notes?: readonly string[];
}

export interface IFemExistingStrength {
	readonly material: string;
	readonly kind: string;
	readonly specified: number;
	readonly tests: number;
	readonly mean: number | null;
	readonly cov: number | null;
	readonly lowerBound: number;
	readonly expected: number;
}

export interface IFemExistingHazard {
	readonly id: string;
	readonly label: string;
	readonly level: string;
	readonly scale: number;
	readonly failed: number;
	readonly worst: number | null;
	readonly ok: boolean;
}

export interface IFemExistingChecklistItem {
	readonly id: string;
	readonly label: string;
	readonly group: string;
	readonly answer: 'C' | 'NC' | 'NA' | 'U';
	readonly note?: string;
}

export interface IFemExistingAssessment {
	readonly available: boolean;
	readonly reason?: string;
	readonly state?: FemExistingState;
	readonly procedure?: 'linear' | 'nonlinear';
	readonly method?: string | null;
	readonly basis?: string;
	readonly clause?: string;
	readonly knowledge?: { readonly id: string; readonly label: string; readonly kappa: number; readonly cf: number; readonly clause?: string };
	readonly strengths?: readonly IFemExistingStrength[];
	readonly levels?: readonly string[];
	readonly hazards?: readonly IFemExistingHazard[];
	readonly rows?: readonly IFemExistingRow[];
	readonly failed?: number;
	readonly checked?: number;
	readonly level?: string | null;
	readonly checklist?: readonly IFemExistingChecklistItem[];
	readonly notes?: readonly string[];
}

/** Whether `found` is an assessment to show (a project that is not an existing building has none). */
export function hasExistingAssessment(found: IFemExistingAssessment | undefined): found is IFemExistingAssessment {
	return !!found && (found.available || (found.reason !== undefined && !found.reason.includes('not an existing building')));
}

function stateLabel(state: FemExistingState): string {
	return state === 'asBuilt' ? localize('femExisting.asBuilt', "As built") : localize('femExisting.retrofitted', "Retrofitted");
}

function ratioCell(check: IFemExistingCheck | null | undefined): FemTableCell {
	if (!check || check.ratio === null || check.ratio === undefined) {
		return check ? '∞' : '';
	}
	return Number(check.ratio.toFixed(3));
}

/** The materials' as-built strengths: specified, tests and the values the checks take [MPa]. */
export function strengthSheet(found: IFemExistingAssessment): IFemSheet {
	const value = (v: number | null | undefined) => v === null || v === undefined ? '' : Number(v.toFixed(1));
	return {
		name: localize('femExisting.strengthTable', "As-built strengths [MPa]"),
		columns: [
			localize('femExisting.materialCol', "Material"), localize('femExisting.kindCol', "Kind"), localize('femExisting.specifiedCol', "Specified"),
			localize('femExisting.testsCol', "Tests"), localize('femExisting.meanCol', "Mean"), localize('femExisting.covCol', "COV"),
			localize('femExisting.lowerCol', "Lower bound"), localize('femExisting.expectedCol', "Expected"),
		],
		rows: (found.strengths ?? []).map(s => [s.material, s.kind, value(s.specified), s.tests, value(s.mean), s.cov === null ? '' : Number(s.cov.toFixed(3)), value(s.lowerBound), value(s.expected)]),
	};
}

/** The hazard levels of the linear procedure and the members exceeding each one's level. */
export function hazardSheet(found: IFemExistingAssessment): IFemSheet {
	const yes = localize('femExisting.yes', "yes"), no = localize('femExisting.no', "no");
	return {
		name: localize('femExisting.hazardTable', "Performance by hazard level"),
		columns: [
			localize('femExisting.hazardCol', "Hazard level"), localize('femExisting.levelCol', "Performance level"), localize('femExisting.scaleCol', "Spectrum scale"),
			localize('femExisting.failedCol', "Members exceeding"), localize('femExisting.worstCol', "Largest ratio"), localize('femExisting.okCol', "OK"),
		],
		rows: (found.hazards ?? []).map(h => [h.label, h.level, Number(h.scale.toFixed(2)), h.failed, h.worst === null ? '' : Number(h.worst.toFixed(3)), h.ok ? yes : no]),
	};
}

/**
 * The members as built and retrofitted: their largest demand over capacity ratio at the main
 * hazard's level, the level each reaches and the action that governs.
 */
export function memberSheet(found: IFemExistingAssessment): IFemSheet {
	const state = found.state ?? 'asBuilt';
	const other: FemExistingState = state === 'asBuilt' ? 'retrofitted' : 'asBuilt';
	const preview = localize('femExisting.preview', "this run's demands");
	const run = localize('femExisting.ownRun', "its own run");
	const rows = (found.rows ?? []).map(r => {
		if (!r.covered) {
			return [r.member, r.component, (r.measures ?? []).join(', '), localize('femExisting.notCovered', "not covered"), '', '', '', (r.notes ?? []).join('; '), ''];
		}
		const before = r.asBuilt, after = r.retrofitted;
		const governing = (state === 'asBuilt' ? before : after)?.action ?? '';
		return [
			r.member, r.component, (r.measures ?? []).join(', '),
			ratioCell(before), before?.level ?? '', ratioCell(after), after?.level ?? '', governing,
			r.otherFrom === 'run' ? run : preview,
		];
	});
	return {
		name: localize('femExisting.memberTable', "Members: demand over capacity, as built and retrofitted ({0} of {1} exceed 1 in this run)", found.failed ?? 0, found.checked ?? 0),
		columns: [
			localize('femExisting.memberCol', "Member"), localize('femExisting.componentCol', "Component"), localize('femExisting.measuresCol', "Retrofit"),
			localize('femExisting.beforeCol', "Ratio as built"), localize('femExisting.beforeLevelCol', "Level as built"),
			localize('femExisting.afterCol', "Ratio retrofitted"), localize('femExisting.afterLevelCol', "Level retrofitted"),
			localize('femExisting.governsCol', "Governs"), localize('femExisting.otherCol', "{0} from", stateLabel(other)),
		],
		rows,
		notes: [
			localize('femExisting.memberNote', "This run analysed the model {0}. The other state's ratio comes from its own run when it has been run (switch Project Settings, Analysis model, Existing building, Model, and run again), else from this run's demands with the other state's capacities.", stateLabel(state).toLowerCase()),
		],
	};
}

/** The screening checklist with the engineer's answers. */
export function checklistSheet(found: IFemExistingAssessment): IFemSheet {
	const answers: { [answer: string]: string } = {
		C: localize('femExisting.compliant', "compliant"),
		NC: localize('femExisting.nonCompliant', "non-compliant"),
		NA: localize('femExisting.notApplicable', "not applicable"),
		U: localize('femExisting.unknown', "unknown"),
	};
	return {
		name: localize('femExisting.checklistTable', "Screening checklist"),
		columns: [localize('femExisting.groupCol', "Group"), localize('femExisting.idCol', "Id"), localize('femExisting.statementCol', "Statement"), localize('femExisting.answerCol', "Answer"), localize('femExisting.noteCol', "Note")],
		rows: (found.checklist ?? []).map(c => [c.group, c.id, c.label, answers[c.answer] ?? c.answer, c.note ?? '']),
	};
}

/** The heading's help: the basis, the procedure, the knowledge level and the building's level. */
export function assessmentHelp(found: IFemExistingAssessment): string {
	const k = found.knowledge;
	const procedure = found.procedure === 'nonlinear'
		? localize('femExisting.nonlinear', "nonlinear (the pushover's hinges)")
		: localize('femExisting.linear', "linear ({0})", found.method ?? '');
	const knowledge = k ? localize('femExisting.knowledge', "knowledge level {0}: κ = {1}, CF = {2}", k.label, k.kappa, k.cf) : '';
	const level = found.level ? localize('femExisting.buildingLevel', "the building reaches {0}", found.level) : '';
	return [found.basis ?? '', procedure, knowledge, level, found.clause ?? ''].filter(s => !!s).join('; ');
}

export function assessmentTitle(found: IFemExistingAssessment): string {
	return localize('femExisting.heading', "Existing Building: Assessment ({0})", stateLabel(found.state ?? 'asBuilt'));
}
