/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { wantsAcrylic } from '../../common/startBackdrop.js';

suite('SAEngine - Start page backdrop', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('acrylic only while no project is open, solid for high contrast and reduced transparency', () => {
		assert.strictEqual(wantsAcrylic(false, false, false), true);
		assert.strictEqual(wantsAcrylic(true, false, false), false, 'a project is open');
		assert.strictEqual(wantsAcrylic(false, true, false), false, 'high-contrast theme');
		assert.strictEqual(wantsAcrylic(false, false, true), false, 'Windows transparency effects off');
	});
});
