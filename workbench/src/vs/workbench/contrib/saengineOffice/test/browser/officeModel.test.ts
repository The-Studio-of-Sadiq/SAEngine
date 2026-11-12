/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { addDays, bimExtents, daysBetween, elementDates, ganttLayout, ISchedule, ITakeoffItem, ITakeoffSheet, measureItem, nextId, parsePhasing, phaseStates, sheetScale } from '../../browser/officeModel.js';

suite('SAEngine - Office tools (alpha 9 L11)', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const schedule: ISchedule = {
		schema: 'saengine.constructionSchedule/1',
		start: '2026-11-07',
		workDays: ['sat', 'sun', 'mon', 'tue', 'wed', 'thu'],
		holidays: [],
		cycleDays: 7,
		finish: '2026-11-12',
		activities: [
			{ id: 'excavation', name: 'Excavation', category: 'excavation', elements: ['F1'], days: 2, links: [], earlyStart: '2026-11-07', earlyFinish: '2026-11-08', critical: true },
			{ id: 'floor:L1', name: 'Floor', category: 'floor', elements: ['S1', 'F1'], days: 2, links: [{ from: 'excavation', type: 'FS', lag: 0 }], earlyStart: '2026-11-09', earlyFinish: '2026-11-12' },
		],
	};

	test('dates', () => {
		assert.strictEqual(daysBetween('2026-11-07', '2026-11-12'), 5);
		assert.strictEqual(addDays('2026-11-30', 1), '2026-12-01');
	});

	test('the Gantt chart lays the activities out in calendar days', () => {
		const layout = ganttLayout(schedule);
		assert.deepStrictEqual(layout.bars.map(b => [b.row, b.offset, b.length]), [[0, 0, 2], [1, 2, 4]]);
		assert.strictEqual(layout.totalDays, 6);
		assert.deepStrictEqual(layout.links, [{ from: 0, to: 1, type: 'FS' }]);
	});

	test('an element is built by its first activity', () => {
		assert.deepStrictEqual(elementDates(schedule).F1, { start: '2026-11-07', finish: '2026-11-08', activity: 'excavation' });
		assert.strictEqual(elementDates(schedule).S1.activity, 'floor:L1');
	});

	test('a takeoff sheet calibrated from two points measures as the backend does', () => {
		const sheet: ITakeoffSheet = { id: 'A', file: 'a.pdf', page: 1, calibration: { a: [0, 0], b: [100, 0], length: 10000 } };
		assert.strictEqual(sheetScale(sheet), 100);
		const fence: ITakeoffItem = { id: 'T1', sheet: 'A', kind: 'length', points: [[0, 0], [50, 0]], description: 'Fence', group: 'finishes', height: 2000 };
		assert.deepStrictEqual(measureItem(fence, sheet), { quantity: 10, unit: 'm2' });
		const paving: ITakeoffItem = { id: 'T2', sheet: 'A', kind: 'area', points: [[0, 0], [10, 0], [10, 10], [0, 10]], description: 'Paving', group: 'concrete' };
		assert.deepStrictEqual(measureItem(paving, sheet), { quantity: 1, unit: 'm2' });
		assert.strictEqual(measureItem(paving, { id: 'B', file: 'b.pdf', page: 1 }), undefined);
		assert.strictEqual(nextId('T', ['T1', 'T2']), 'T3');
	});

	test('phase states mirror saengine.project.phasing', () => {
		const phasing = parsePhasing(JSON.stringify({ phases: [{ id: 'existing', name: 'Existing' }, { id: 'new', name: 'New' }], defaultPhase: 'new', elements: { C1: { created: 'existing', demolished: 'new' }, C2: { created: 'existing' } } }));
		assert.deepStrictEqual(phaseStates(phasing, ['C1', 'C2', 'C3'], 'new'), { C1: 'demolished', C2: 'existing', C3: 'new' });
		// Built in the phase shown: new in it (as the backend's status_in rules).
		assert.deepStrictEqual(phaseStates(phasing, ['C1', 'C2', 'C3'], 'existing'), { C1: 'new', C2: 'new' });
		assert.strictEqual(parsePhasing('not json').phases.length, 2);
	});

	test('the building extents for the project frame', () => {
		const extents = bimExtents(JSON.stringify({ stories: [{ elevation: 0 }, { elevation: 3000 }], elements: [{ position: [1000, 2000] }, { boundary: [[0, 0], [5000, 0], [5000, 4000]] }] }));
		assert.deepStrictEqual(extents, { min: [0, 0, 0], max: [5000, 4000, 3000] });
	});
});
