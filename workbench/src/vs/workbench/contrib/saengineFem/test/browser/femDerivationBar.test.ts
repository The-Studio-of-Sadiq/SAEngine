/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { sourceStamp } from '../../../../services/saengineProject/common/partSources.js';
import { derivationState, recordedSources } from '../../browser/femDerivationBar.js';

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

	test('counts the soil report as a source only when the model recorded it', () => {
		const texts = new Map<string, string | undefined>([['bim', 'b'], ['settings', 's'], ['objects', 'o'], ['materials', 'm'], ['soil', 'boreholes']]);
		const sources = `bim=${sourceStamp('b')}; settings=${sourceStamp('s')}; objects=${sourceStamp('o')}; materials=${sourceStamp('m')}`;
		const describe = (soil?: string) => `Derived. Sources: ${sources}${soil === undefined ? '' : `; soil=${sourceStamp(soil)}`}`;
		assert.deepStrictEqual({
			entered: derivationState(describe(), texts).changed,
			current: derivationState(describe('boreholes'), texts).changed,
			placeholderThenBoreholes: derivationState(describe('{"schema": 1, "part": "soil"}'), texts).changed,
			missing: derivationState(describe('boreholes'), new Map([...texts, ['soil', undefined]])).changed,
		}, {
			entered: [],
			current: [],
			placeholderThenBoreholes: ['Soil Report'],
			missing: ['Soil Report'],
		});
	});
});
