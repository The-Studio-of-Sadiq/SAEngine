/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IPartStatus, PartAction, PartState } from './partStatus.js';

/*
 * The stages of a project in the order an engineer works through them (the project stage bar):
 * Site & Soil, Model, Loads, Analysis, Design, then Drawings, BOQ and Report. A stage's state is
 * read from the part statuses (partStatus.ts), never worked out again: a stage is the worst of
 * its parts, and Analysis and Design are the two phases of the analysis part.
 */

export type StageState = 'notStarted' | 'inProgress' | 'done' | 'stale' | 'failed';

/** What a stage offers as its next step besides opening its part. */
export type StageAction = 'runAll' | PartAction;

export interface IProjectStage {
	readonly id: string;
	readonly label: string;
	readonly state: StageState;
	/** The part that needs the engineer first (its hint is the next step), else the stage's main part. */
	readonly focus: IPartStatus | undefined;
	/** The section of the focus part's editor to open (the settings' loads), if any. */
	readonly section?: string;
	/** The command kind that does the next step, when the stage is not done. */
	readonly action?: StageAction;
	/** The stage waits for an earlier one (Design before the analysis has run). */
	readonly waitsFor?: string;
}

interface IStageDefinition {
	readonly id: string;
	readonly label: () => string;
	/** The parts of the stage, the main part first. */
	readonly parts: readonly string[];
	/** The section of the main part the stage opens. */
	readonly section?: string;
	/** Steps that Run All does (derive, analyse, check, measure, report, draw). */
	readonly runAll?: boolean;
}

const STAGES: readonly IStageDefinition[] = [
	{ id: 'site', label: () => localize('stage.site', "Site & Soil"), parts: ['soil'] },
	{ id: 'model', label: () => localize('stage.model', "Model"), parts: ['floorPlan', 'structure', 'materials', 'objects', 'bim', 'mep'] },
	// The settings hold the loads, seismic and wind, and the combinations.
	{ id: 'loads', label: () => localize('stage.loads', "Loads"), parts: ['settings'], section: 'areaLoads' },
	{ id: 'analysis', label: () => localize('stage.analysis', "Analysis"), parts: ['fem'], runAll: true },
	{ id: 'design', label: () => localize('stage.design', "Design"), parts: ['fem', 'substructure'], runAll: true },
	{ id: 'outputs', label: () => localize('stage.outputs', "Drawings · BOQ · Report"), parts: ['exports', 'boq'], runAll: true },
];

/** Parts a project may do without: not started, they leave their stage as it is. */
const OPTIONAL_PARTS: ReadonlySet<string> = new Set(['soil', 'mep', 'substructure']);

/** How bad a part state is for its stage (higher first). */
function severity(state: PartState): number {
	switch (state) {
		case 'failed':
		case 'error': return 4;
		case 'stale': return 3;
		case 'inProgress':
		case 'defaults': return 2;
		case 'notStarted': return 1;
		default: return 0;
	}
}

function stageState(state: PartState): StageState {
	switch (state) {
		case 'failed':
		case 'error': return 'failed';
		case 'stale': return 'stale';
		case 'inProgress':
		case 'defaults': return 'inProgress';
		case 'notStarted': return 'notStarted';
		default: return 'done';
	}
}

/**
 * The analysis part as each of its two stages sees it: Analysis is done once the design checks
 * can run; Design waits until then (out of date while the analysis is).
 */
function femFor(stage: string, fem: IPartStatus): { readonly status: IPartStatus; readonly waits: boolean } {
	const designing = fem.phase === 'design' || (fem.phase === undefined && fem.state === 'done');
	if (stage === 'analysis') {
		return { status: designing ? { ...fem, state: 'done', hint: undefined } : fem, waits: false };
	}
	if (designing) {
		return { status: fem, waits: false };
	}
	return { status: { ...fem, state: fem.state === 'stale' ? 'stale' : 'notStarted' }, waits: true };
}

/** The stages of a project whose parts have `statuses` (in workflow order); empty without parts. */
export function projectStages(statuses: readonly IPartStatus[]): IProjectStage[] {
	if (!statuses.length) {
		return [];
	}
	const byId = new Map(statuses.map(s => [s.part, s]));
	const stages: IProjectStage[] = [];
	for (const definition of STAGES) {
		let waitsFor: string | undefined;
		const members: IPartStatus[] = [];
		for (const id of definition.parts) {
			const own = byId.get(id);
			if (!own) {
				continue;
			}
			if (id === 'fem') {
				const fem = femFor(definition.id, own);
				if (fem.waits) {
					waitsFor = 'analysis';
				}
				members.push(fem.status);
			} else {
				members.push(own);
			}
		}
		if (!members.length) {
			continue;
		}
		// Optional parts not started leave the stage as the others make it.
		const counted = members.filter(m => !(OPTIONAL_PARTS.has(m.part) && m.state === 'notStarted'));
		let worst: IPartStatus | undefined;
		for (const member of counted) {
			if (!worst || severity(member.state) > severity(worst.state)) {
				worst = member;
			}
		}
		let state: StageState;
		if (!counted.length) {
			state = 'notStarted';
		} else if (counted.every(m => m.state === 'notStarted')) {
			state = 'notStarted';
		} else if (worst!.state === 'notStarted') {
			// Some parts are done, others not started: under way.
			state = 'inProgress';
		} else {
			state = stageState(worst!.state);
		}
		const focus = state === 'done' || !worst ? members[0] : worst;
		const action: StageAction | undefined = state === 'done'
			? undefined
			: focus.action ?? (definition.runAll && state !== 'failed' ? 'runAll' : undefined);
		stages.push({
			id: definition.id,
			label: definition.label(),
			state,
			focus,
			section: focus.part === definition.parts[0] ? definition.section : undefined,
			action,
			waitsFor: state === 'done' ? undefined : waitsFor,
		});
	}
	return stages;
}

/** Words for a stage's state, for its tooltip and screen readers. */
export function stageStateLabel(state: StageState): string {
	switch (state) {
		case 'done': return localize('stageState.done', "Done");
		case 'inProgress': return localize('stageState.inProgress', "In progress");
		case 'stale': return localize('stageState.stale', "Out of date");
		case 'failed': return localize('stageState.failed', "Failing");
		default: return localize('stageState.notStarted', "Not started");
	}
}
