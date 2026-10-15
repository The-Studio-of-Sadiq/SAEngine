/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { DEFAULT_SETTINGS } from '../../../../services/saengineProject/common/projectLibraries.generated.js';
import { codeValues } from '../../browser/settingsEditor.js';
import { JsonObject } from '../../browser/schemaForm.js';

suite('SAEngine - Project settings editor', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const values = (settings: JsonObject) => codeValues(settings).map(v => `${v.label}: ${v.value}${v.overridden ? ' (overridden)' : ''}`);

	test('code values follow the location, occupancy category and structural system, with overrides', () => {
		const defaults = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as JsonObject;
		assert.deepStrictEqual({
			dhaka: values(defaults),
			sylhet: values({ ...defaults, site: { location: 'sylhet', siteClass: 'SC', windSpeed: 70 }, occupancy: { use: 'healthcare', category: 'IV' }, seismic: { system: 'rcSmf' } }),
		}, {
			dhaka: [
				'Seismic zone: 2',
				'Zone coefficient Z: 0.2',
				'Basic wind speed V (m/s): 65.7',
				'Seismic importance factor I: 1',
				'Wind importance factor I: 1',
				'Response reduction factor R: 5',
				'Overstrength factor Ω0: 3',
				'Deflection amplification Cd: 4.5',
				'Site class: Stiff soil (Vs < 180 m/s)',
				'Wind exposure: Urban, suburban, wooded',
			],
			sylhet: [
				'Seismic zone: 4',
				'Zone coefficient Z: 0.36',
				'Basic wind speed V (m/s): 70 (overridden)',
				'Seismic importance factor I: 1.5',
				'Wind importance factor I: 1.15',
				'Response reduction factor R: 8',
				'Overstrength factor Ω0: 3',
				'Deflection amplification Cd: 5.5',
				'Site class: Very dense soil or soft rock (180-360 m/s)',
				'Wind exposure: Urban, suburban, wooded',
			],
		});
	});
});
