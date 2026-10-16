/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { errorSummary, FemRunTracker } from '../../browser/femResultsBar.js';

suite('SAEngine - FEM run tracker', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	test('allows one run per model at a time and reports its progress', () => {
		const tracker = store.add(new FemRunTracker());
		const model = URI.file('/project/08 FEM/model.osmodel');
		const other = URI.file('/other/08 FEM/model.osmodel');
		const events: string[] = [];
		store.add(tracker.onDidChange(uri => events.push(uri.path)));
		let cancelled = 0;

		const first = tracker.begin(model, () => cancelled++);
		const second = tracker.begin(model, () => { });
		const elsewhere = tracker.begin(other, () => { });
		first?.report({ fraction: 0.5, message: 'Dead: step 1 of 2' });
		const during = tracker.get(model)?.progress;
		tracker.get(model)?.cancel();
		first?.dispose();
		first?.dispose();
		elsewhere?.dispose();
		const again = tracker.begin(model, () => { });
		again?.dispose();

		assert.deepStrictEqual({
			first: !!first,
			second: second === undefined,
			elsewhere: !!elsewhere,
			during,
			cancelled,
			afterEnd: tracker.get(model),
			again: !!again,
			events,
		}, {
			first: true,
			second: true,
			elsewhere: true,
			during: { fraction: 0.5, message: 'Dead: step 1 of 2' },
			cancelled: 1,
			afterEnd: undefined,
			again: true,
			events: [model.path, other.path, model.path, model.path, other.path, model.path, model.path],
		});
	});

	test('keeps only the line of a backend error that says what went wrong', () => {
		const traceback = 'Traceback (most recent call last):\n  File "x.py", line 3, in <module>\n    view(case)\nValueError: unknown result case:10\n';
		const withStderr = 'ValueError: unknown result case:10\nTraceback (most recent call last):\n  File "server.py", line 9\nINFO:pygls:shutting down';
		assert.deepStrictEqual(
			[errorSummary(new Error(traceback)), errorSummary(new Error(withStderr)), errorSummary('plain'), errorSummary(new Error(''))],
			['ValueError: unknown result case:10', 'ValueError: unknown result case:10', 'plain', ''],
		);
	});
});
