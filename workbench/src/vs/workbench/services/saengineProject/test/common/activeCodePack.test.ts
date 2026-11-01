/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { activeCodeName, DEFAULT_CODE_PACK_ID, defaultCodeName, setActiveCodePack } from '../../common/activeCodePack.js';
import { DEFAULT_CODE_TABLES } from '../../common/projectLibraries.generated.js';

suite('SAEngine active code pack', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	teardown(() => setActiveCodePack(undefined, undefined));

	test('the editors name the project\'s pack, the default pack\'s edition without one', () => {
		assert.strictEqual(defaultCodeName(), DEFAULT_CODE_TABLES.edition);
		assert.strictEqual(activeCodeName(), DEFAULT_CODE_TABLES.edition);
		setActiveCodePack(DEFAULT_CODE_PACK_ID, undefined);
		assert.strictEqual(activeCodeName(), DEFAULT_CODE_TABLES.edition);
		setActiveCodePack('stub-2030', 'Stub Code 2030');
		assert.deepStrictEqual([activeCodeName(), defaultCodeName()], ['Stub Code 2030', DEFAULT_CODE_TABLES.edition]);
		// A pack the backend could not describe is named by its id.
		setActiveCodePack('office-pack', undefined);
		assert.strictEqual(activeCodeName(), 'office-pack');
	});
});
