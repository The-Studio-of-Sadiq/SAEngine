/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import type { CadPoint } from '@saengine/cad-editor';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { alignAngle, calibrated, cloudSlice, DEFAULT_PDF_SCALE, diffLines, firstPdfPlacement, gridCentre, diffSummary, isPointCloud, IUnderlayPlacement, moved, placementFields, placementOf, planSegments, readWorkbookImport, rotated, segmentsNear, storyFloor, toPlan } from '../../browser/floorPlanUnderlay.js';

suite('SAEngine - Floor plan underlay', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const round = ([x, y]: CadPoint) => [Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000];
	const placement: IUnderlayPlacement = { offset: [1000, 500], scale: 2, rotation: 90 };

	test('a new PDF page starts at its stated scale, centred on the grid', () => {
		// An A3 page (420 x 297 mm) stating 1:100, on a plan whose grid spans 0-13000 x 0-5000.
		const centre = gridCentre({ grids: { x: [{ position: 0 }, { position: 13000 }], y: [{ position: 0 }, { position: 5000 }] } });
		assert.deepStrictEqual(centre, [6500, 2500]);
		const first = firstPdfPlacement([420, 297], 100, centre);
		assert.deepStrictEqual(first, { offset: [6500 - 21000, 2500 - 14850], scale: 100, rotation: 0 });
		assert.deepStrictEqual(toPlan(first, [210, 148.5]), [6500, 2500]);
		// No stated scale: 1:100; no grid: the origin.
		assert.strictEqual(firstPdfPlacement([420, 297], null, [0, 0]).scale, DEFAULT_PDF_SCALE);
		assert.deepStrictEqual(gridCentre({}), [0, 0]);
	});

	test('alpha 9 L2: a point cloud is sliced at the story cut in the scan units', () => {
		assert.ok(isPointCloud('Underlays/scan.LAS') && isPointCloud('a.e57') && !isPointCloud('a.dxf'));
		// A scan in metres (scale 1000), the story at +3000 mm, the scan's ±0 at 12.5 m.
		assert.deepStrictEqual(cloudSlice({ scale: 1000, elevationOffset: 12.5 }, 3000), { cut: 4.2 + 12.5, thickness: 0.1, voxel: 0.02 });
		assert.deepStrictEqual(cloudSlice({ scale: 1, cutHeight: 900, sliceThickness: 50, pointSpacing: 0 }, 0), { cut: 900, thickness: 50, voxel: 0 });
	});

	test('W4C-12: a story is cut above its floor, the level of the story below', () => {
		const stories = [{ id: 'BASE', elevation: 0 }, { id: 'L1', elevation: 3600 }, { id: 'L2', elevation: 6800 }];
		assert.strictEqual(storyFloor(stories, 'L1'), 0);
		assert.strictEqual(storyFloor(stories, 'L2'), 3600);
		assert.strictEqual(storyFloor(stories, 'BASE'), 0);
		// Level 1 of a 0-3.6 m scan in metres is cut at 1.2 m, not 4.8 m.
		assert.strictEqual(cloudSlice({ scale: 1000 }, storyFloor(stories, 'L1')).cut, 1.2);
	});

	test('a drawing point is scaled, turned and moved onto the plan', () => {
		assert.deepStrictEqual(round(toPlan(placement, [10, 0])), [1000, 520]);
		assert.deepStrictEqual(placementOf({ dx: 5, scale: -1 }), { offset: [5, 0], scale: 1, rotation: 0 });
	});

	test('calibrating keeps the first point and makes the second the known length away', () => {
		// A 1:100 plan shown at 1: 60 mm on paper is 6000 mm.
		const paper: IUnderlayPlacement = { offset: [0, 0], scale: 1, rotation: 0 };
		const a = toPlan(paper, [10, 10]);
		const b = toPlan(paper, [70, 10]);
		const next = calibrated(paper, a, b, 6000)!;
		assert.strictEqual(next.scale, 100);
		assert.deepStrictEqual(round(toPlan(next, [10, 10])), round(a));
		const [x1, y1] = toPlan(next, [10, 10]);
		const [x2, y2] = toPlan(next, [70, 10]);
		assert.strictEqual(Math.round(Math.hypot(x2 - x1, y2 - y1)), 6000);
		assert.strictEqual(calibrated(paper, a, a, 6000), undefined);
	});

	test('moving, rotating about a point and aligning to the grid', () => {
		const p: CadPoint = [3, 4];
		const before = toPlan(placement, p);
		const after = toPlan(moved(placement, [0, 0], [100, -50]), p);
		assert.deepStrictEqual(round(after), round([before[0] + 100, before[1] - 50]));
		const base: CadPoint = toPlan(placement, [0, 0]);
		const turned = rotated(placement, base, 90);
		assert.deepStrictEqual(round(toPlan(turned, [0, 0])), round(base));
		assert.strictEqual(turned.rotation, 180);
		assert.strictEqual(Math.round(alignAngle([0, 0], [100, 3]) * 1000) / 1000, Math.round(-Math.atan2(3, 100) * 180 / Math.PI * 1000) / 1000);
		assert.deepStrictEqual(placementFields({ offset: [1.04, 2], scale: 100.0000001, rotation: 370 }), { dx: 1, dy: 2, scale: 100, rotation: 10 });
	});

	test('the underlay lines near a point are offered for snaps', () => {
		const segments = planSegments({ offset: [0, 0], scale: 100, rotation: 0 }, [[0, 0, 60, 0], [0, 50, 60, 50], 'bad']);
		assert.strictEqual(segments.length, 2);
		assert.deepStrictEqual(segments[0].end, [6000, 0]);
		assert.strictEqual(segmentsNear(segments, [3000, 40], 100).length, 1);
		assert.strictEqual(segmentsNear(segments, [3000, 2500], 100).length, 0);
	});

	test('the workbook diff reads into preview lines', () => {
		const result = readWorkbookImport({
			ok: true, problems: [], changed: ['floorPlan'], texts: { floorPlan: '{}' },
			diff: { Grids: { added: ['C'], removed: [], changed: [{ id: 'A', fields: [{ field: 'position', old: 0, new: 150 }] }] }, Beams: { added: [], removed: ['B1'], changed: [] } },
		});
		assert.deepStrictEqual(diffLines(result.diff).map(l => [l.sheet, l.kind, l.text]), [
			['Grids', 'added', 'Added C'],
			['Grids', 'changed', 'A: position 0 → 150'],
			['Beams', 'removed', 'Deleted B1'],
		]);
		assert.strictEqual(diffSummary(result.diff), '1 added, 1 deleted, 1 changed');
	});
});
