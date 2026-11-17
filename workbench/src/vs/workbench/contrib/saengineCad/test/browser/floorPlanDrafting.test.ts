/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	addDraft,
	arcThroughPoints,
	extendLine,
	filletLines,
	copyDrafts,
	copyDraftsToStories,
	conversionSteps,
	distanceToDraft,
	draftInWindow,
	draftsOf,
	IDraftArc,
	IDraftCircle,
	IDraftLine,
	IDraftPolyline,
	IDraftShape,
	mirrorDrafts,
	moveDrafts,
	nextDraftId,
	offsetDraft,
	parseDraftPoint,
	pickDraft,
	rectangleFromCorners,
	regularPolygon,
	removeDraft,
	replaceDraft,
	rotateDrafts,
	trimLine,
	toPointRef,
} from '../../browser/floorPlanDrafting.js';
import { gridsOf } from '../../browser/floorPlanDrawing.js';

suite('SAEngine - Floor plan drafting', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('draft conversion names the nearest grid lines and preserves offsets to 1 mm', () => {
		const grids = gridsOf({ grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] } });
		assert.deepStrictEqual(toPointRef([6100, 4900], grids), { x: 'B', y: '2', dx: 100, dy: -100 });
		assert.strictEqual(toPointRef([1, 2], { x: new Map(), y: new Map() }), undefined);
		assert.deepStrictEqual(conversionSteps([line1], 'beam', 'B250', 'L1', grids).steps, [
			{ action: 'beams.place', params: { type: 'B250', between: [[{ x: 'A', y: '1', dx: 0, dy: 0 }, { x: 'B', y: '2', dx: 0, dy: 0 }]], storeys: ['L1'] } },
			{ action: 'drafting.delete', params: { ids: ['D1'] } },
		]);
		assert.deepStrictEqual(conversionSteps([polylineClosed], 'slab', 'S125', 'L1', grids).steps, [
			{ action: 'slabs.place', params: { type: 'S125', panels: [[{ x: 'A', y: '1', dx: 0, dy: 0 }, { x: 'A', y: '1', dx: 1000, dy: 0 }, { x: 'A', y: '1', dx: 1000, dy: 500 }, { x: 'A', y: '1', dx: 0, dy: 500 }]], storeys: ['L1'] } },
			{ action: 'drafting.delete', params: { ids: ['D3'] } },
		]);
		assert.deepStrictEqual(conversionSteps([circle1], 'beam', 'B250', 'L1', grids).skipped, ['D5']);
	});

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

	test('OFFSET, TRIM, EXTEND and FILLET use verified coordinates', () => {
		const horizontal: IDraftLine = { kind: 'line', id: 'H', story: 'L1', start: [0, 0], end: [100, 0] };
		assert.deepStrictEqual(offsetDraft(horizontal, 100, [50, 200])?.kind === 'line' ? (offsetDraft(horizontal, 100, [50, 200]) as IDraftLine).start : undefined, [0, 100]);
		const rectangleOutside = offsetDraft(polylineClosed, 100, [-50, 250]) as IDraftPolyline;
		assert.deepStrictEqual(rectangleOutside.points, [[-100, -100], [1100, -100], [1100, 600], [-100, 600]]);
		const rectangleInside = offsetDraft(polylineClosed, 100, [500, 250]) as IDraftPolyline;
		assert.deepStrictEqual(rectangleInside.points, [[100, 100], [900, 100], [900, 400], [100, 400]]);
		const rectangleClockwise: IDraftPolyline = { ...polylineClosed, points: [...polylineClosed.points].reverse() };
		assert.deepStrictEqual((offsetDraft(rectangleClockwise, 100, [500, 250]) as IDraftPolyline).points, [[100, 400], [900, 400], [900, 100], [100, 100]]);
		const crossing: IDraftLine = { kind: 'line', id: 'T', story: 'L1', start: [0, 0], end: [100, 0] };
		const cuts: IDraftShape[] = [25, 75].map((x, i) => ({ kind: 'line', id: `C${i}`, story: 'L1', start: [x, -10], end: [x, 10] }));
		assert.deepStrictEqual(trimLine(crossing, cuts, [50, 0]).map(l => [l.start, l.end]), [[[0, 0], [25, 0]], [[75, 0], [100, 0]]]);
		const ext: IDraftLine = { kind: 'line', id: 'E', story: 'L1', start: [0, 0], end: [10, 0] };
		const boundary: IDraftLine = { kind: 'line', id: 'B', story: 'L1', start: [20, -10], end: [20, 10] };
		assert.deepStrictEqual(extendLine(ext, [boundary], [9, 0])?.end, [20, 0]);
		const vertical: IDraftLine = { kind: 'line', id: 'V', story: 'L1', start: [0, 0], end: [0, 100] };
		const horizontal2: IDraftLine = { kind: 'line', id: 'H2', story: 'L1', start: [0, 0], end: [100, 0] };
		const sharp = filletLines({ ...horizontal2, end: [500, 0] }, { ...vertical, end: [0, 500] }, 0, [300, 0], [0, 300])!;
		assert.deepStrictEqual(sharp.lines.map(l => [l.start, l.end]), [[[0, 0], [500, 0]], [[0, 0], [0, 500]]]);
		const rounded = filletLines({ ...horizontal2, start: [-50, 0], end: [500, 0] }, { ...vertical, start: [0, -50], end: [0, 500] }, 100, [300, 0], [0, 300])!;
		assert.deepStrictEqual(rounded.lines.map(l => [l.start, l.end]), [[[100, 0], [500, 0]], [[0, 100], [0, 500]]]);
		assert.strictEqual(rounded.arc?.radius, 100);
		assert.deepStrictEqual(rounded.arc?.center, [100, 100]);
		assert.deepStrictEqual([rounded.arc?.startAngle, rounded.arc?.endAngle], [180, 270]);
		const negative = filletLines({ ...horizontal2, start: [-500, 0], end: [50, 0] }, { ...vertical, start: [0, -500], end: [0, 50] }, 100, [-300, 0], [0, -300])!;
		assert.deepStrictEqual(negative.lines.map(l => [l.start, l.end]), [[[-500, 0], [-100, 0]], [[0, -500], [0, -100]]]);
		assert.deepStrictEqual(negative.arc?.center, [-100, -100]);
		assert.deepStrictEqual([negative.arc?.startAngle, negative.arc?.endAngle], [0, 90]);
	});

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

	test('arcThroughPoints stores the CCW arc containing the middle point', () => {
		// 359.9999° is 0°: compare angles around the circle.
		const angleOff = (angle: number, expected: number) => { const d = ((angle - expected) % 360 + 360) % 360; return Math.min(d, 360 - d); };
		const first = arcThroughPoints([1000, 0], [707.107, 707.107], [0, 1000]);
		assert.ok(first);
		assert.ok(Math.abs(first.center[0]) < 0.001 && Math.abs(first.center[1]) < 0.001);
		assert.ok(Math.abs(first.radius - 1000) < 0.001);
		assert.ok(angleOff(first.startAngle, 0) < 0.001 && angleOff(first.endAngle, 90) < 0.001);
		const reversed = arcThroughPoints([0, 1000], [707.107, 707.107], [1000, 0]);
		assert.ok(reversed);
		assert.ok(Math.abs(reversed.center[0]) < 0.001 && Math.abs(reversed.center[1]) < 0.001);
		assert.ok(Math.abs(reversed.radius - 1000) < 0.001);
		assert.ok(angleOff(reversed.startAngle, 0) < 0.001 && angleOff(reversed.endAngle, 90) < 0.001);
		assert.strictEqual(arcThroughPoints([0, 0], [1, 1], [2, 2]), undefined);
	});

	test('parseDraftPoint reads absolute, relative, polar, and direct distance points', () => {
		assert.deepStrictEqual(parseDraftPoint('120, 240', [10, 20], [1, 0]), [120, 240]);
		assert.deepStrictEqual(parseDraftPoint('@120,-40', [10, 20], [1, 0]), [130, -20]);
		const polar = parseDraftPoint('@100<30', [10, 20], [1, 0]);
		assert.ok(polar);
		assert.ok(Math.abs(polar[0] - 96.6025403784) < 1e-8 && Math.abs(polar[1] - 70) < 1e-8);
		assert.deepStrictEqual(parseDraftPoint('50', [10, 20], [3, 4]), [40, 60]);
		assert.strictEqual(parseDraftPoint('50', [10, 20], [0, 0]), undefined);
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

	test('rectangleFromCorners returns four corners in cyclical order', () => {
		const corners1 = rectangleFromCorners([0, 0], [1000, 500]);
		assert.deepStrictEqual(corners1, [
			[0, 0],
			[1000, 0],
			[1000, 500],
			[0, 500],
		]);

		const corners2 = rectangleFromCorners([1000, 500], [0, 0]);
		assert.deepStrictEqual(corners2, [
			[1000, 500],
			[0, 500],
			[0, 0],
			[1000, 0],
		]);

		const cornersNegative = rectangleFromCorners([-200, -100], [300, 400]);
		assert.deepStrictEqual(cornersNegative, [
			[-200, -100],
			[300, -100],
			[300, 400],
			[-200, 400],
		]);
	});

	test('regularPolygon computes vertices of regular polygons', () => {
		// Edge cases: sides < 3 or zero radius returns empty
		assert.deepStrictEqual(regularPolygon([0, 0], [100, 0], 2), []);
		assert.deepStrictEqual(regularPolygon([100, 100], [100, 100], 6), []);

		// 4-sided square
		const square = regularPolygon([0, 0], [10, 0], 4);
		assert.strictEqual(square.length, 4);
		assert.deepStrictEqual(square, [
			[10, 0],
			[0, 10],
			[-10, 0],
			[0, -10],
		]);

		// 6-sided hexagon
		const hexagon = regularPolygon([0, 0], [1000, 0], 6);
		assert.strictEqual(hexagon.length, 6);
		assert.deepStrictEqual(hexagon[0], [1000, 0]);
		assert.deepStrictEqual(hexagon[1], [500, 866.025]);
		assert.deepStrictEqual(hexagon[2], [-500, 866.025]);
		assert.deepStrictEqual(hexagon[3], [-1000, 0]);
		assert.deepStrictEqual(hexagon[4], [-500, -866.025]);
		assert.deepStrictEqual(hexagon[5], [500, -866.025]);

		// Distance from center to all vertices should equal radius (1000)
		for (const pt of hexagon) {
			const dist = Math.hypot(pt[0], pt[1]);
			assert.ok(Math.abs(dist - 1000) < 0.01, `Vertex distance ${dist} close to 1000`);
		}

		// Edge lengths should all equal radius (1000) for a regular hexagon
		for (let i = 0; i < 6; i++) {
			const next = hexagon[(i + 1) % 6];
			const edge = Math.hypot(next[0] - hexagon[i][0], next[1] - hexagon[i][1]);
			assert.ok(Math.abs(edge - 1000) < 0.01, `Edge length ${edge} close to 1000`);
		}
	});

	test('moveDrafts moves a line by delta without mutating input', () => {
		const line: IDraftLine = {
			kind: 'line',
			id: 'D1',
			story: 'L1',
			start: [1000, 2000],
			end: [4000, 6000],
		};
		const layout = { drafting: [line] };
		const result = moveDrafts(layout, ['D1'], [500, -1000]);

		assert.strictEqual(result.placed, 1);
		assert.strictEqual(result.skipped, 0);
		assert.strictEqual(result.count, 1);
		assert.deepStrictEqual(result.ids, ['D1']);

		// Original layout drafting should not be mutated
		assert.deepStrictEqual((layout.drafting[0] as IDraftLine).start, [1000, 2000]);
		assert.deepStrictEqual((layout.drafting[0] as IDraftLine).end, [4000, 6000]);

		// Result layout should have line moved by [500, -1000]
		// start: [1000 + 500, 2000 + (-1000)] = [1500, 1000]
		// end: [4000 + 500, 6000 + (-1000)] = [4500, 5000]
		const moved = (result.layout.drafting as IDraftShape[])[0] as IDraftLine;
		assert.strictEqual(moved.id, 'D1');
		assert.deepStrictEqual(moved.start, [1500, 1000]);
		assert.deepStrictEqual(moved.end, [4500, 5000]);
	});

	test('copyDrafts twice gives two new ids without clashing', () => {
		const line: IDraftLine = {
			kind: 'line',
			id: 'D1',
			story: 'L1',
			start: [1000, 2000],
			end: [4000, 6000],
		};
		const layout = { drafting: [line] };
		const result = copyDrafts(layout, ['D1'], [100, 200], 2);

		assert.strictEqual(result.placed, 2);
		assert.strictEqual(result.skipped, 0);
		assert.strictEqual(result.count, 2);
		assert.deepStrictEqual(result.ids, ['D2', 'D3']);

		// Original layout drafting should not be mutated
		assert.strictEqual(layout.drafting.length, 1);

		// Result layout should have 3 shapes: original D1 and copies D2, D3
		const shapes = result.layout.drafting as IDraftLine[];
		assert.strictEqual(shapes.length, 3);
		assert.strictEqual(shapes[0].id, 'D1');
		assert.deepStrictEqual(shapes[0].start, [1000, 2000]);
		assert.deepStrictEqual(shapes[0].end, [4000, 6000]);

		// Copy 1 (k=1): [1000 + 100, 2000 + 200] = [1100, 2200], [4000 + 100, 6000 + 200] = [4100, 6200]
		assert.strictEqual(shapes[1].id, 'D2');
		assert.deepStrictEqual(shapes[1].start, [1100, 2200]);
		assert.deepStrictEqual(shapes[1].end, [4100, 6200]);

		// Copy 2 (k=2): [1000 + 200, 2000 + 400] = [1200, 2400], [4000 + 200, 6000 + 400] = [4200, 6400]
		assert.strictEqual(shapes[2].id, 'D3');
		assert.deepStrictEqual(shapes[2].start, [1200, 2400]);
		assert.deepStrictEqual(shapes[2].end, [4200, 6400]);
	});

	test('rotateDrafts rotates a line 90 degrees about the origin', () => {
		const line: IDraftLine = {
			kind: 'line',
			id: 'D1',
			story: 'L1',
			start: [1000, 0],
			end: [2000, 0],
		};
		const layout = { drafting: [line] };
		const result = rotateDrafts(layout, ['D1'], 90, [0, 0]);

		assert.strictEqual(result.placed, 1);
		assert.strictEqual(result.skipped, 0);
		assert.strictEqual(result.count, 1);
		assert.deepStrictEqual(result.ids, ['D1']);

		// Original layout not mutated
		assert.deepStrictEqual((layout.drafting[0] as IDraftLine).start, [1000, 0]);

		// [1000, 0] rotated 90° CCW about [0, 0] gives [0, 1000]
		// [2000, 0] rotated 90° CCW about [0, 0] gives [0, 2000]
		const rotated = (result.layout.drafting as IDraftLine[])[0];
		assert.deepStrictEqual(rotated.start, [0, 1000]);
		assert.deepStrictEqual(rotated.end, [0, 2000]);
	});

	test('mirrorDrafts mirrors an arc about x=0 keeping it CCW with right angles', () => {
		const arc: IDraftArc = {
			kind: 'arc',
			id: 'D1',
			story: 'L1',
			center: [1000, 0],
			radius: 500,
			startAngle: 0,
			endAngle: 90,
		};
		const layout = { drafting: [arc] };

		// axis 'x' is a vertical line at x = coordinate (x = 0)
		// With keep = true (default): original stays, new copy created with new id
		const resultKeep = mirrorDrafts(layout, ['D1'], 'x', 0, true);
		assert.strictEqual(resultKeep.placed, 1);
		assert.strictEqual(resultKeep.count, 1);
		assert.deepStrictEqual(resultKeep.ids, ['D2']);

		const shapes = resultKeep.layout.drafting as IDraftArc[];
		assert.strictEqual(shapes.length, 2);
		assert.strictEqual(shapes[0].id, 'D1');
		assert.deepStrictEqual(shapes[0].center, [1000, 0]);

		// Expected mirrored arc:
		// center x' = 2 * 0 - 1000 = -1000, y' = 0 -> [-1000, 0]
		// radius: 500
		// startAngle: 180 - oldEndAngle(90) = 90
		// endAngle: 180 - oldStartAngle(0) = 180
		assert.strictEqual(shapes[1].id, 'D2');
		assert.deepStrictEqual(shapes[1].center, [-1000, 0]);
		assert.strictEqual(shapes[1].radius, 500);
		assert.strictEqual(shapes[1].startAngle, 90);
		assert.strictEqual(shapes[1].endAngle, 180);

		// With keep = false: original replaced in place keeping id 'D1'
		const resultReplace = mirrorDrafts(layout, ['D1'], 'x', 0, false);
		assert.strictEqual(resultReplace.placed, 1);
		assert.deepStrictEqual(resultReplace.ids, ['D1']);
		const replacedShapes = resultReplace.layout.drafting as IDraftArc[];
		assert.strictEqual(replacedShapes.length, 1);
		assert.strictEqual(replacedShapes[0].id, 'D1');
		assert.deepStrictEqual(replacedShapes[0].center, [-1000, 0]);
		assert.strictEqual(replacedShapes[0].startAngle, 90);
		assert.strictEqual(replacedShapes[0].endAngle, 180);
	});

	test('mirrorDrafts mirrors an arc about y=0 keeping it CCW with right angles', () => {
		const arc: IDraftArc = {
			kind: 'arc',
			id: 'D1',
			story: 'L1',
			center: [0, 1000],
			radius: 500,
			startAngle: 0,
			endAngle: 90,
		};
		const layout = { drafting: [arc] };
		const result = mirrorDrafts(layout, ['D1'], 'y', 0, false);

		// center y' = 2 * 0 - 1000 = -1000 -> [0, -1000]
		// startAngle = normalizeAngle(-oldEndAngle) = normalizeAngle(-90) = 270
		// endAngle = normalizeAngle(-oldStartAngle) = normalizeAngle(-0) = 0
		const mirrored = (result.layout.drafting as IDraftArc[])[0];
		assert.deepStrictEqual(mirrored.center, [0, -1000]);
		assert.strictEqual(mirrored.startAngle, 270);
		assert.strictEqual(mirrored.endAngle, 0);
	});

	test('copyDraftsToStories copies drafts to target stories with new ids', () => {
		const line: IDraftLine = {
			kind: 'line',
			id: 'D1',
			story: 'L1',
			start: [0, 0],
			end: [1000, 1000],
		};
		const layout = { drafting: [line] };
		const result = copyDraftsToStories(layout, ['D1'], ['L2', 'L3']);

		assert.strictEqual(result.placed, 2);
		assert.deepStrictEqual(result.ids, ['D2', 'D3']);
		const shapes = result.layout.drafting as IDraftLine[];
		assert.strictEqual(shapes.length, 3);
		assert.strictEqual(shapes[1].story, 'L2');
		assert.strictEqual(shapes[2].story, 'L3');
	});

});
