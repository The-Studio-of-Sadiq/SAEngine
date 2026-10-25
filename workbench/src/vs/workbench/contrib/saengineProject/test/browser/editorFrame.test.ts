/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, clampPanelWidth, readFrameState } from '../../browser/editorFrame.js';

suite('SAEngine - editor frame', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('keeps the properties panel within its limits and leaves room for the main area', () => {
		assert.deepStrictEqual({
			within: clampPanelWidth(300, 1200),
			tooNarrow: clampPanelWidth(50, 1200),
			tooWide: clampPanelWidth(2000, 1200),
			smallEditor: clampPanelWidth(400, 600),
			tinyEditor: clampPanelWidth(400, 300),
			ownLimits: clampPanelWidth(500, 1200, 150, 420),
			notANumber: clampPanelWidth(NaN, 1200),
		}, {
			within: 300,
			tooNarrow: 200,
			tooWide: 640,
			smallEditor: 360,
			tinyEditor: 200,
			ownLimits: 420,
			notANumber: 200,
		});
	});

	test('reads the remembered panel state, field by field', () => {
		const defaults = { visible: true, width: 280 };
		assert.deepStrictEqual([
			readFrameState(undefined, defaults),
			readFrameState('{"visible":false,"width":350}', defaults),
			readFrameState('{"visible":"no","width":320}', defaults),
			readFrameState('not json', defaults),
		], [
			{ visible: true, width: 280 },
			{ visible: false, width: 350 },
			{ visible: true, width: 320 },
			{ visible: true, width: 280 },
		]);
	});

	test('property sheet rows: a heading with a detail, values as text or elements, problems marked', () => {
		const panel = mainWindow.document.createElement('div');
		appendPropertyHeading(panel, 'C1', 'C400');
		appendPropertyHeading(panel, 'Placement');
		appendPropertyRow(panel, 'Story', 'Level 1');
		appendPropertyRow(panel, 'Type', 'NOPE', true);
		const link = mainWindow.document.createElement('a');
		link.textContent = 'Edit';
		appendPropertyRow(panel, 'Object', link);
		appendPropertyNote(panel, 'Read-only.');
		assert.deepStrictEqual({
			headings: [...panel.querySelectorAll('.sa-props-heading')].map(h => [h.textContent, h.querySelector('.sa-props-detail')?.textContent]),
			values: [...panel.querySelectorAll('.sa-props-row')].map(r => [r.querySelector('.name')?.textContent, r.querySelector('.value')?.textContent, r.querySelector('.value')!.classList.contains('problem')]),
			icon: !!panel.querySelector('.value.problem > .codicon-warning'),
			element: panel.querySelectorAll('.sa-props-row')[2].querySelector('.value > a') === link,
			note: panel.querySelector('.sa-props-note')?.textContent,
		}, {
			headings: [['C1C400', 'C400'], ['Placement', undefined]],
			values: [['Story', 'Level 1', false], ['Type', 'NOPE', true], ['Object', 'Edit', false]],
			icon: true,
			element: true,
			note: 'Read-only.',
		});
	});
});
