/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { recordedSources } from '../../browser/femDerivationBar.js';

suite('SAEngine - FEM derivation', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the source stamps the derivation records in the model description', () => {
		assert.deepStrictEqual({
			derived: [...recordedSources('Derived by SAEngine from the building model and the project settings. Sources: bim=a1; materials=b2; objects=c3; settings=d4')],
			handMade: [...recordedSources('A frame I drew myself')],
			none: [...recordedSources(undefined)],
		}, {
			derived: [['bim', 'a1'], ['materials', 'b2'], ['objects', 'c3'], ['settings', 'd4']],
			handMade: [],
			none: [],
		});
	});
});
