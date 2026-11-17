/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	addDraft,
	distanceToDraft,
	draftInWindow,
	draftsOf,
	IDraftArc,
	IDraftCircle,
	IDraftLine,
	IDraftPolyline,
	nextDraftId,
	pickDraft,
	removeDraft,
	replaceDraft,
} from '../../browser/floorPlanDrafting.js';

suite('SAEngine - Floor plan drafting', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const line1: IDraftLine = {
		kind: 'line',
		id: 'D1',
		story: 'L1',
		start: [0, 0],
		end: [6000, 5000],
	};

	const polylineOpen: IDraftPolyline = {
		kind: 'polyline',
		id: 'D2',
		story: 'L1',
		points: [[0, 0], [1000, 2000]],
		closed: false,
		layer: 'SITE',
	};

	const polylineClosed: IDraftPolyline = {
		kind: 'polyline',
		id: 'D3',
		story: 'L1',
		points: [[0, 0], [1000, 0], [1000, 500], [0, 500]],
		closed: true,
	};

	const arc1: IDraftArc = {
		kind: 'arc',
		id: 'D4',
		story: 'BASE',
		center: [3000, 2500],
		radius: 500,
		startAngle: 0,
		endAngle: 90,
	};

	const circle1: IDraftCircle = {
		kind: 'circle',
		id: 'D5',
		story: 'L1',
		center: [1000, 1000],
		radius: 250,
	};

	test('draftsOf reads valid shapes of all kinds and defaults layer to DRAFT', () => {
		const layout = {
			schema: 'saengine.floorPlan/1',
			drafting: [line1, polylineOpen, polylineClosed, arc1, circle1],
		};

		const all = draftsOf(layout);
		assert.strictEqual(all.length, 5);

		assert.deepStrictEqual(all[0], {
			kind: 'line',
			id: 'D1',
			story: 'L1',
			layer: 'DRAFT',
			start: [0, 0],
			end: [6000, 5000],
		});

		assert.deepStrictEqual(all[1], {
			kind: 'polyline',
			id: 'D2',
			story: 'L1',
			layer: 'SITE',
			points: [[0, 0], [1000, 2000]],
			closed: false,
		});

		assert.deepStrictEqual(all[2], {
			kind: 'polyline',
			id: 'D3',
			story: 'L1',
			layer: 'DRAFT',
			points: [[0, 0], [1000, 0], [1000, 500], [0, 500]],
			closed: true,
		});

		assert.deepStrictEqual(all[3], {
			kind: 'arc',
			id: 'D4',
			story: 'BASE',
			layer: 'DRAFT',
			center: [3000, 2500],
			radius: 500,
			startAngle: 0,
			endAngle: 90,
		});

		assert.deepStrictEqual(all[4], {
			kind: 'circle',
			id: 'D5',
			story: 'L1',
			layer: 'DRAFT',
			center: [1000, 1000],
			radius: 250,
		});
	});

	test('draft picking measures segments, circle edges and arc sweeps', () => {
		assert.strictEqual(distanceToDraft(line1, [3000, 2500]), 0);
		assert.strictEqual(distanceToDraft(circle1, [1250, 1000]), 0);
		assert.strictEqual(distanceToDraft(arc1, [3000, 3000]), 0);
		assert.strictEqual(distanceToDraft(arc1, [2500, 2500]), Math.sqrt(500 * 500 + 500 * 500));
		assert.strictEqual(pickDraft([line1, circle1], [3000, 2500], 10)?.id, 'D1');
		assert.strictEqual(pickDraft([line1], [3000, 2510], 4), undefined); // 7.7 mm off the line
	});

	test('draft window selection includes full shapes and crossing segments', () => {
		assert.strictEqual(draftInWindow(line1, [0, 0], [6000, 5000], false), true);
		assert.strictEqual(draftInWindow(line1, [100, 100], [200, 200], false), false);
		assert.strictEqual(draftInWindow(line1, [100, 100], [200, 200], true), true); // the line runs through it
		assert.strictEqual(draftInWindow(line1, [3000, 100], [3100, 200], true), false);
		assert.strictEqual(draftInWindow(polylineClosed, [900, 100], [1100, 300], true), true); // across its right edge
		assert.strictEqual(draftInWindow(polylineClosed, [400, 100], [600, 300], true), false); // inside it, touching no edge (as AutoCAD)
		assert.strictEqual(draftInWindow(circle1, [700, 700], [1300, 1300], false), true);
		assert.strictEqual(draftInWindow(arc1, [3300, 2800], [3400, 2900], true), true); // the arc's 45° point (3354, 2854)
		assert.strictEqual(draftInWindow(arc1, [3400, 2900], [3600, 3100], true), false);
	});

	test('draftsOf filters by storyId', () => {
		const layout = {
			drafting: [line1, arc1, circle1],
		};

		assert.strictEqual(draftsOf(layout, 'BASE').length, 1);
		assert.strictEqual(draftsOf(layout, 'BASE')[0].id, 'D4');
		assert.strictEqual(draftsOf(layout, 'L1').length, 2);
		assert.strictEqual(draftsOf(layout, 'L9').length, 0);
	});

	test('draftsOf skips malformed entries', () => {
		const malformed = {
			drafting: [
				null,
				123,
				'string',
				{},
				{ kind: 'line', id: 'M1' }, // missing story, start, end
				{ kind: 'line', id: 'M2', story: 'L1', start: [0, 0] }, // missing end
				{ kind: 'line', id: 'M3', story: 'L1', start: [0, 'bad'], end: [1, 1] }, // non-numeric
				{ kind: 'line', id: 'M4', story: 'L1', start: [NaN, 0], end: [1, 1] }, // non-finite
				{ kind: 'line', id: 'M5', story: 'L1', start: [0, 0], end: [Infinity, 1] }, // non-finite
				{ kind: 'polyline', id: 'M6', story: 'L1', points: [[0, 0]] }, // < 2 points
				{ kind: 'polyline', id: 'M7', story: 'L1', points: [[0, 0], [10, 10]], closed: true }, // closed < 3 points
				{ kind: 'arc', id: 'M8', story: 'L1', center: [0, 0], radius: 0, startAngle: 0, endAngle: 90 }, // radius <= 0
				{ kind: 'arc', id: 'M9', story: 'L1', center: [0, 0], radius: 50, startAngle: NaN, endAngle: 90 }, // non-finite angle
				{ kind: 'circle', id: 'M10', story: 'L1', center: [0, 0], radius: -5 }, // radius < 0
				{ kind: 'unknown', id: 'M11', story: 'L1' },
			],
		};

		assert.deepStrictEqual(draftsOf(malformed), []);
		assert.deepStrictEqual(draftsOf(null), []);
		assert.deepStrictEqual(draftsOf({}), []);
		assert.deepStrictEqual(draftsOf({ drafting: 'not an array' }), []);
	});

	test('nextDraftId returns D1 for empty layout and avoids clashing with existing drafts and members', () => {
		assert.strictEqual(nextDraftId({}), 'D1');
		assert.strictEqual(nextDraftId({ drafting: [] }), 'D1');

		// Existing draft D1 -> next is D2
		assert.strictEqual(nextDraftId({ drafting: [{ id: 'D1' }] }), 'D2');

		// Existing member D1 -> next is D2
		assert.strictEqual(nextDraftId({ columns: [{ id: 'D1' }] }), 'D2');
		assert.strictEqual(nextDraftId({ beams: [{ id: 'D1' }] }), 'D2');

		// Existing member D1 and draft D2 -> next is D3
		assert.strictEqual(nextDraftId({
			columns: [{ id: 'D1' }],
			drafting: [{ id: 'D2' }],
		}), 'D3');

		// Gap filling: D1 deleted, D2 exists -> next is D1
		assert.strictEqual(nextDraftId({ drafting: [{ id: 'D2' }] }), 'D1');
	});

	test('addDraft appends to empty or missing drafting array in JSON text', () => {
		const initialWithoutDrafting = '{\n\t"schema": "saengine.floorPlan/1"\n}\n';
		const added1 = addDraft(initialWithoutDrafting, line1);
		const parsed1 = JSON.parse(added1);
		assert.strictEqual(parsed1.drafting.length, 1);
		assert.strictEqual(parsed1.drafting[0].id, 'D1');

		const added2 = addDraft(added1, circle1);
		const parsed2 = JSON.parse(added2);
		assert.strictEqual(parsed2.drafting.length, 2);
		assert.strictEqual(parsed2.drafting[0].id, 'D1');
		assert.strictEqual(parsed2.drafting[1].id, 'D5');
	});

	test('replaceDraft updates an existing draft by id', () => {
		const initial = JSON.stringify({
			schema: 'saengine.floorPlan/1',
			drafting: [line1, circle1],
		}, null, '\t');

		const updatedLine: IDraftLine = {
			kind: 'line',
			id: 'D1',
			story: 'L2',
			start: [100, 100],
			end: [200, 200],
			layer: 'NEW_LAYER',
		};

		const replaced = replaceDraft(initial, updatedLine);
		const parsed = JSON.parse(replaced);
		assert.strictEqual(parsed.drafting.length, 2);
		assert.strictEqual(parsed.drafting[0].story, 'L2');
		assert.strictEqual(parsed.drafting[0].layer, 'NEW_LAYER');
		assert.strictEqual(parsed.drafting[1].id, 'D5');

		// Non-existent id leaves text unchanged
		const nonExistent: IDraftLine = { ...line1, id: 'D999' };
		assert.strictEqual(replaceDraft(initial, nonExistent), initial);
	});

	test('removeDraft removes draft by id and leaves others intact', () => {
		const initial = JSON.stringify({
			schema: 'saengine.floorPlan/1',
			drafting: [line1, circle1],
		}, null, '\t');

		const removed1 = removeDraft(initial, 'D1');
		const parsed1 = JSON.parse(removed1);
		assert.strictEqual(parsed1.drafting.length, 1);
		assert.strictEqual(parsed1.drafting[0].id, 'D5');

		const removed2 = removeDraft(removed1, 'D5');
		const parsed2 = JSON.parse(removed2);
		assert.deepStrictEqual(parsed2.drafting, []);

		// Non-existent id leaves text unchanged
		assert.strictEqual(removeDraft(initial, 'D999'), initial);
	});

	test('full lifecycle: add, replace, remove, draftsOf round-trip', () => {
		let text = '{\n\t"schema": "saengine.floorPlan/1",\n\t"stories": [{"id": "L1", "elevation": 0}]\n}\n';

		text = addDraft(text, line1);
		text = addDraft(text, polylineClosed);
		text = addDraft(text, arc1);

		let drafts = draftsOf(JSON.parse(text));
		assert.strictEqual(drafts.length, 3);
		assert.deepStrictEqual(drafts.map(d => d.id), ['D1', 'D3', 'D4']);

		// Replace D3
		const modifiedPolyline: IDraftPolyline = {
			kind: 'polyline',
			id: 'D3',
			story: 'L1',
			points: [[0, 0], [2000, 0], [2000, 1000], [0, 1000]],
			closed: true,
			layer: 'ROOM',
		};
		text = replaceDraft(text, modifiedPolyline);

		drafts = draftsOf(JSON.parse(text));
		assert.strictEqual(drafts.length, 3);
		assert.strictEqual((drafts[1] as IDraftPolyline).layer, 'ROOM');
		assert.strictEqual((drafts[1] as IDraftPolyline).points[1][0], 2000);

		// Remove D1
		text = removeDraft(text, 'D1');
		drafts = draftsOf(JSON.parse(text));
		assert.strictEqual(drafts.length, 2);
		assert.deepStrictEqual(drafts.map(d => d.id), ['D3', 'D4']);
	});
});
