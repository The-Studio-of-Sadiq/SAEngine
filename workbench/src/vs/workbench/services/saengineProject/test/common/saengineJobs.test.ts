/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { FINISHED_JOBS_KEPT, formatDuration, runningStep, SaengineJobs } from '../../common/saengineJobs.js';

suite('SAEngine jobs', () => {
	const store = ensureNoDisposablesAreLeakedInTestSuite();

	function jobs(): { model: SaengineJobs; tick: (ms: number) => void } {
		let now = 1_000;
		const model = store.add(new SaengineJobs(() => now));
		return { model, tick: ms => now += ms };
	}

	test('planned steps: started, reported, ended one by one', () => {
		const { model, tick } = jobs();
		let stopped = 0;
		const job = model.start({ title: 'Run All', steps: ['derive', 'analysis', 'design'], cancel: () => stopped++ });
		assert.deepStrictEqual(model.jobs[0].steps.map(s => s.state), ['pending', 'pending', 'pending']);
		job.startStep(0);
		job.report('12 members');
		assert.deepStrictEqual(runningStep(model.jobs[0]), { index: 0, step: { label: 'derive', state: 'running', detail: '12 members' } });
		job.endStep(0, 'done', 'up to date', 1);
		job.startStep(1);
		model.cancel(job.id);
		assert.strictEqual(stopped, 1);
		job.endStep(1, 'cancelled', 'stopped');
		job.endStep(2, 'skipped', 'not run');
		tick(5_000);
		job.end('cancelled', 'Run All stopped', [{ label: 'Show Results', run: () => undefined }]);
		const ended = model.jobs[0];
		assert.deepStrictEqual([ended.state, ended.ended! - ended.started, ended.message, ended.actions.length, ended.planned], ['cancelled', 5_000, 'Run All stopped', 1, true]);
		assert.deepStrictEqual(ended.steps.map(s => s.state), ['done', 'cancelled', 'skipped']);
		// A finished job cannot be stopped or changed again.
		model.cancel(job.id);
		job.end('done');
		assert.deepStrictEqual([stopped, model.jobs[0].state], [1, 'cancelled']);
	});

	test('progress messages become steps; run ends done, or failed and throws', async () => {
		const { model } = jobs();
		const value = await model.run({ title: 'Importing' }, async progress => {
			progress.report({ message: 'reading' });
			progress.report({ message: 'reading' });
			progress.report({ message: 'writing' });
			return 7;
		});
		assert.strictEqual(value, 7);
		assert.deepStrictEqual(model.jobs[0].steps.map(s => [s.label, s.state]), [['reading', 'done'], ['writing', 'done']]);
		assert.strictEqual(model.jobs[0].state, 'done');
		await assert.rejects(model.run({ title: 'Report' }, async () => { throw new Error('no LaTeX'); }));
		assert.deepStrictEqual([model.jobs[0].title, model.jobs[0].state, model.jobs[0].message], ['Report', 'failed', 'no LaTeX']);
	});

	test('a job without steps reports its detail; the list keeps the last finished jobs', () => {
		const { model } = jobs();
		const drawings = model.start({ title: 'Drawings' });
		drawings.report('S-03 (3 of 12)');
		assert.strictEqual(model.jobs[0].detail, 'S-03 (3 of 12)');
		for (let i = 0; i < FINISHED_JOBS_KEPT + 3; i++) {
			model.start({ title: `job ${i}` }).end('done');
		}
		// The running job stays, whatever its age.
		assert.strictEqual(model.jobs.length, FINISHED_JOBS_KEPT + 1);
		assert.ok(model.jobs.some(j => j.id === drawings.id && j.state === 'running'));
		drawings.end('done');
		assert.strictEqual(model.jobs.length, FINISHED_JOBS_KEPT);
	});

	test('durations', () => {
		assert.deepStrictEqual([formatDuration(5), formatDuration(125), formatDuration(3730)], ['0:05', '2:05', '1:02:10']);
	});
});
