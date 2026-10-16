/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { clampPanelWidth, readFrameState } from '../../browser/editorFrame.js';

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
});
