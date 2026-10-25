/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { DisposableStore } from '../../../../../base/common/lifecycle.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { MIN_SAVING_DISPLAY, SaveStatusKind, SaveStatusModel } from '../../common/saveStatusModel.js';

suite('SAEngine - save status', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	function create(): SaveStatusModel {
		return store.add(new SaveStatusModel());
	}

	test('is saved with nothing open', () => {
		const status = create().status(0);
		assert.deepStrictEqual(status, { kind: SaveStatusKind.Saved, unsaved: [], failed: [], saving: 0, autoSavePending: false, lastSaved: undefined, showSavingUntil: undefined });
	});

	test('clean → unsaved → saving → saved, with counts', () => {
		const model = create();
		model.setDirty('a', '04 Materials/materials.json', true);
		model.setDirty('b', '01 Soil/soil.json', true);
		assert.deepStrictEqual([model.status(0).kind, model.status(0).unsaved], [SaveStatusKind.Unsaved, ['01 Soil/soil.json', '04 Materials/materials.json']]);

		model.saveStarted('a', 1000);
		assert.deepStrictEqual([model.status(1000).kind, model.status(1000).saving], [SaveStatusKind.Saving, 1]);

		model.saved('a', 1010);
		model.setDirty('a', '04 Materials/materials.json', false);
		model.saveEnded('a', 1010);
		// Still one unsaved document: shown as unsaved, not saving.
		assert.deepStrictEqual([model.status(1010).kind, model.status(1010).unsaved, model.status(1010).lastSaved], [SaveStatusKind.Unsaved, ['01 Soil/soil.json'], 1010]);

		model.saveStarted('b', 2000);
		model.saved('b', 2005);
		model.setDirty('b', '01 Soil/soil.json', false);
		model.saveEnded('b', 2005);
		// A quick save stays visible for a moment, then reads saved.
		assert.strictEqual(model.status(2005).kind, SaveStatusKind.Saving);
		assert.strictEqual(model.status(2005).showSavingUntil, 2000 + MIN_SAVING_DISPLAY);
		assert.strictEqual(model.status(2000 + MIN_SAVING_DISPLAY).kind, SaveStatusKind.Saved);
	});

	test('a failed save is shown until the document saves or is reverted', () => {
		const model = create();
		model.setDirty('a', 'materials.json', true);
		model.saveStarted('a', 0);
		model.saveFailed('a', 'materials.json');
		model.saveEnded('a', 5);
		assert.deepStrictEqual([model.status(5).kind, model.status(5).failed], [SaveStatusKind.Failed, ['materials.json']]);

		// Failure wins over a save running elsewhere.
		model.saveStarted('b', 10);
		assert.strictEqual(model.status(10).kind, SaveStatusKind.Failed);
		model.saveEnded('b', 10);

		model.saved('a', 2000);
		assert.strictEqual(model.status(2000).kind, SaveStatusKind.Unsaved);
		model.setDirty('a', 'materials.json', false);
		assert.strictEqual(model.status(2000).kind, SaveStatusKind.Saved);

		model.saveFailed('c', 'objects.json');
		model.setDirty('c', 'objects.json', false); // reverted
		assert.strictEqual(model.status(3000).kind, SaveStatusKind.Saved);

		model.saveFailed('d', 'grids.json');
		model.clearFailures();
		assert.strictEqual(model.status(3000).kind, SaveStatusKind.Saved);
	});

	test('auto save after a delay reads as saving, not unsaved', () => {
		const model = create();
		model.setDirty('a', 'materials.json', true, true);
		assert.deepStrictEqual([model.status(0).kind, model.status(0).autoSavePending], [SaveStatusKind.Saving, true]);
		model.setDirty('b', 'drawing.dxf', true, false);
		assert.deepStrictEqual([model.status(0).kind, model.status(0).unsaved.length], [SaveStatusKind.Unsaved, 2]);
		model.remove('b');
		model.saveStarted('a', 0);
		assert.deepStrictEqual([model.status(0).kind, model.status(0).autoSavePending], [SaveStatusKind.Saving, false]);
	});

	test('overlapping saves of one document count once each', () => {
		const model = create();
		model.saveStarted('a', 0);
		model.saveStarted('a', 1);
		model.saveStarted('b', 2);
		assert.strictEqual(model.status(2).saving, 3);
		model.saveEnded('a', 3);
		model.saveEnded('a', 4);
		model.saveEnded('a', 5); // a stray end is ignored
		assert.strictEqual(model.status(5).saving, 1);
		model.saveEnded('b', 6);
		assert.strictEqual(model.status(10_000).kind, SaveStatusKind.Saved);
	});

	test('writes outside documents show as a short save', () => {
		const model = create();
		model.wrote(100);
		assert.deepStrictEqual([model.status(100).kind, model.status(100).lastSaved], [SaveStatusKind.Saving, 100]);
		assert.strictEqual(model.status(100 + MIN_SAVING_DISPLAY).kind, SaveStatusKind.Saved);
	});

	test('fires a change only when something changed', () => {
		const model = create();
		let changes = 0;
		const listeners = new DisposableStore();
		listeners.add(model.onDidChange(() => changes++));
		model.setDirty('a', 'x', true);
		model.setDirty('a', 'x', true);
		model.setDirty('b', 'y', false);
		model.remove('c');
		model.clearFailures();
		assert.strictEqual(changes, 1);
		listeners.dispose();
	});
});
