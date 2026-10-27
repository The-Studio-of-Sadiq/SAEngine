/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { Severity } from '../../../../../platform/notification/common/notification.js';
import { femSettingsStamp, femSourceCurrent, sourceStamp } from '../../../../services/saengineProject/common/partSources.js';
import { analysisInputsStamp, bimMembers, femModelStamp, formatDuration, IStepOutcome, outcomeLine, RUN_ALL_STEPS, runSeverity } from '../../electron-browser/runAll.js';

function outcome(id: IStepOutcome['id'], status: IStepOutcome['status'], failing?: number): IStepOutcome {
	return { id, label: id, status, message: status, seconds: 1, failing };
}

suite('SAEngine - Run All', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('every step comes after the steps it needs; the foundations before the design checks', () => {
		const order = RUN_ALL_STEPS.map(s => s.id);
		for (const [index, step] of RUN_ALL_STEPS.entries()) {
			for (const need of step.needs) {
				assert.ok(order.indexOf(need) < index, `${step.id} needs ${need}`);
			}
		}
		assert.deepStrictEqual(order, ['bim', 'derive', 'analysis', 'ssi', 'substructure', 'design', 'mep', 'boq', 'report', 'drawings']);
		assert.ok(order.indexOf('substructure') < order.indexOf('design'));
	});

	test('G1: a failed step is an error, failing checks or notes a warning, all done information', () => {
		assert.strictEqual(runSeverity([outcome('bim', 'ok'), outcome('design', 'failed'), outcome('report', 'notRun')]), Severity.Error);
		assert.strictEqual(runSeverity([outcome('design', 'ok', 3)]), Severity.Warning);
		assert.strictEqual(runSeverity([outcome('design', 'ok', 0), outcome('substructure', 'warning')]), Severity.Warning);
		assert.strictEqual(runSeverity([outcome('design', 'ok', 0), outcome('boq', 'skipped')]), Severity.Info);
		assert.strictEqual(runSeverity([outcome('analysis', 'cancelled'), outcome('design', 'cancelled')]), Severity.Info);
	});

	test('the step summary says how each step ended and how long it took', () => {
		assert.strictEqual(outcomeLine({ id: 'analysis', label: 'analysis', status: 'skipped', message: 'results current', seconds: 0.4 }, 2), '– 3. analysis: results current (0:00)');
		assert.strictEqual(outcomeLine({ id: 'design', label: 'design checks', status: 'failed', message: 'checked nothing', seconds: 125 }, 5), '✗ 6. design checks: checked nothing (2:05)');
		assert.strictEqual(outcomeLine({ id: 'report', label: 'report', status: 'notRun', message: 'not run', seconds: 0 }, 8), '· 9. report: not run');
		assert.strictEqual(formatDuration(3725), '1:02:05');
	});

	test('G3: a building model without members has nothing to analyse', () => {
		assert.strictEqual(bimMembers(undefined), 0);
		assert.strictEqual(bimMembers('{"schema": "saengine.bim/2", "elements": []}'), 0);
		assert.strictEqual(bimMembers('{"part": "bim"}'), 0);
		assert.strictEqual(bimMembers('not json'), 0);
		assert.strictEqual(bimMembers('{"elements": [{"id": "C1"}, {"id": "B1"}]}'), 2);
	});

	test('X28/X19: the analysis stamp leaves out the model meta, and matches the Python side', () => {
		const model = '{"meta": {"name": "A"}, "nodes": [[1, 0.5, 1e-7, 3000.0]], "ndm": 3}';
		// saengine.pipeline.design_mode.model_stamp of the same text
		assert.strictEqual(femModelStamp(model), '9f58f9607989ba9364cea330c4072d72edcf7b1c');
		const renamed = '{"meta": {"name": "B", "description": "Sources: settings=1"}, "nodes": [[1, 0.5, 1e-7, 3000.0]], "ndm": 3}';
		assert.strictEqual(femModelStamp(renamed), femModelStamp(model));
		assert.notStrictEqual(femModelStamp('{"meta": {}, "nodes": [[1, 0.5, 1e-7, 3001]], "ndm": 3}'), femModelStamp(model));
		const sides = [['thermal.json', undefined], ['ssi.json', '{}'], ['faces.json', undefined]] as const;
		assert.strictEqual(analysisInputsStamp(model, sides), analysisInputsStamp(renamed, sides));
		assert.notStrictEqual(analysisInputsStamp(model, sides), analysisInputsStamp(model, [['thermal.json', undefined], ['ssi.json', '{"k": 1}'], ['faces.json', undefined]]));
	});

	test('X28: the settings stamp leaves out the project details and the title block', () => {
		const text = '{"schema": "s", "project": {"name": "A", "engineer": "E"}, "seismic": {"system": "SMF", "R": 8.0, "x": 0.1}, "drawings": {"drawnBy": "X"}}';
		// saengine.fem.derive.settings_stamp of the same text
		assert.strictEqual(femSettingsStamp(text), 'bd723026eecf9a062ec799860853b19f5e01f916');
		const named = text.replace('"engineer": "E"', '"engineer": "Eng. R. Khan"').replace('"drawnBy": "X"', '"drawnBy": "Y"');
		assert.strictEqual(femSettingsStamp(named), femSettingsStamp(text));
		assert.notStrictEqual(femSettingsStamp(text.replace('SMF', 'IMF')), femSettingsStamp(text));
		assert.ok(femSourceCurrent('settings', named, femSettingsStamp(text)));
		// A model derived before records the whole file's stamp: current while the file is unchanged.
		assert.ok(femSourceCurrent('settings', text, sourceStamp(text)));
		assert.ok(!femSourceCurrent('settings', named, sourceStamp(text)));
		// Other sources are stamped whole.
		assert.ok(!femSourceCurrent('objects', named, femSettingsStamp(text)));
	});
});
