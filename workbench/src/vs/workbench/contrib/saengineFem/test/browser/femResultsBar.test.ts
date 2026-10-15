/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { resultFormatter, resultsFolder } from '../../browser/femResultsBar.js';

suite('SAEngine - FEM results', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('shows SI results in mm, kN and kN·m, other units as they are', () => {
		const si = resultFormatter('SI (m, N, kg, s, Pa)');
		const other = resultFormatter('kip-in');
		assert.deepStrictEqual(
			[si('length', 0.0032104), si('force', -77215.4), si('moment', 4463.9), other('force', 12.34567)],
			['3.21 mm', '-77.2 kN', '4.5 kN·m', '12.35'],
		);
	});

	test('results are written beside the model', () => {
		assert.strictEqual(resultsFolder(URI.file('/p/08 FEM/model.osmodel')).path, '/p/08 FEM/model.results');
	});
});
