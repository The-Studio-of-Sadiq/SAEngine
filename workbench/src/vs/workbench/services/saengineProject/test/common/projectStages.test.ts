/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { FemPhase, IPartStatus, PartAction, PartState } from '../../common/partStatus.js';
import { projectStages } from '../../common/projectStages.js';

function part(id: string, state: PartState, extra: { phase?: FemPhase; action?: PartAction; hint?: string } = {}): IPartStatus {
	return { part: id, state, text: '', ...extra };
}

/** A building whose inputs are done, with the analysis part as given. */
function building(fem: IPartStatus, overrides: Record<string, PartState> = {}): IPartStatus[] {
	const ids = ['soil', 'settings', 'materials', 'objects', 'floorPlan', 'bim', 'mep', 'substructure', 'boq', 'exports'];
	const states: Record<string, PartState> = { soil: 'notStarted', mep: 'notStarted', substructure: 'notStarted', boq: 'notStarted', exports: 'notStarted', ...overrides };
	return [...ids.slice(0, 7).map(id => part(id, states[id] ?? 'done')), fem, ...ids.slice(7).map(id => part(id, states[id] ?? 'done'))];
}

function states(statuses: IPartStatus[]): Record<string, string> {
	return Object.fromEntries(projectStages(statuses).map(stage => [stage.id, stage.state]));
}

suite('SAEngine project stages', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('no parts, no stages', () => {
		assert.deepStrictEqual(projectStages([]), []);
	});

	test('the stages in order, optional parts not started leave their stage alone', () => {
		const stages = projectStages(building(part('fem', 'notStarted', { phase: 'model', hint: 'derive the analysis model' })));
		assert.deepStrictEqual(stages.map(s => s.id), ['site', 'model', 'loads', 'analysis', 'design', 'outputs']);
		assert.deepStrictEqual(states(building(part('fem', 'notStarted', { phase: 'model' }))), {
			site: 'notStarted', model: 'done', loads: 'done', analysis: 'notStarted', design: 'notStarted', outputs: 'notStarted',
		});
		assert.strictEqual(stages[3].action, 'runAll');
		assert.strictEqual(stages[4].waitsFor, 'analysis');
	});

	test('analysis and design are the two phases of the analysis part', () => {
		assert.deepStrictEqual(states(building(part('fem', 'stale', { phase: 'analysis' }))).analysis, 'stale');
		// A stale model leaves the design out of date too.
		assert.deepStrictEqual(states(building(part('fem', 'stale', { phase: 'model' }))).design, 'stale');
		const designing = states(building(part('fem', 'failed', { phase: 'design' })));
		assert.deepStrictEqual([designing.analysis, designing.design], ['done', 'failed']);
		const done = states(building(part('fem', 'done', { phase: 'design' })));
		assert.deepStrictEqual([done.analysis, done.design], ['done', 'done']);
	});

	test('a failing design offers no Run All; members without bars offer Design Reinforcement', () => {
		const failing = projectStages(building(part('fem', 'failed', { phase: 'design', hint: 'review the failing members' })));
		assert.strictEqual(failing[4].action, undefined);
		assert.strictEqual(failing[4].focus?.part, 'fem');
		const noBars = projectStages(building(part('fem', 'inProgress', { phase: 'design', action: 'designReinforcement' })));
		assert.strictEqual(noBars[4].action, 'designReinforcement');
	});

	test('the worst part of a stage is its state and its focus; settings at their defaults are in progress', () => {
		const stages = projectStages(building(part('fem', 'done', { phase: 'design' }), { objects: 'stale', settings: 'defaults', substructure: 'failed' }));
		assert.deepStrictEqual([stages[1].state, stages[1].focus?.part], ['stale', 'objects']);
		assert.deepStrictEqual([stages[2].state, stages[2].focus?.part, stages[2].section], ['inProgress', 'settings', 'areaLoads']);
		assert.deepStrictEqual([stages[4].state, stages[4].focus?.part], ['failed', 'substructure']);
	});

	test('outputs partly made are under way; a done stage opens its main part', () => {
		const stages = projectStages(building(part('fem', 'done', { phase: 'design' }), { boq: 'done' }));
		assert.deepStrictEqual([stages[5].state, stages[5].focus?.part], ['inProgress', 'exports']);
		const model = stages[1];
		assert.deepStrictEqual([model.state, model.focus?.part, model.action], ['done', 'floorPlan', undefined]);
	});
});
