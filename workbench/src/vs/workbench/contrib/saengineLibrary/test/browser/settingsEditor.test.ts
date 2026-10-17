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
				'Site class: Loose-to-medium cohesionless soil or soft-to-firm cohesive soil (Vs < 180 m/s, N < 15, su < 70 kPa)',
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
				'Site class: Dense or medium dense sand, gravel or stiff clay (Vs 180-360 m/s, N 15-50, su 70-250 kPa)',
				'Wind exposure: Urban, suburban, wooded',
			],
		});
	});

	test('the site class comes from the soil report unless it is entered', () => {
		const defaults = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as JsonObject;
		const soil = { class: 'SC', label: 'SC (N̄ = 22 over 30 m, BH-2)' };
		const site = (settings: JsonObject) => codeValues(settings, soil).find(v => v.label === 'Site class');
		assert.deepStrictEqual([
			site(defaults),
			site({ ...defaults, site: { location: 'dhaka', siteClass: 'SD', siteClassSource: 'entered' } }),
		], [
			{ label: 'Site class', value: 'Dense or medium dense sand, gravel or stiff clay (Vs 180-360 m/s, N 15-50, su 70-250 kPa)', source: 'Table 6.2.13, from 1 Soil Report: SC (N̄ = 22 over 30 m, BH-2)', overridden: false },
			{ label: 'Site class', value: 'Loose-to-medium cohesionless soil or soft-to-firm cohesive soil (Vs < 180 m/s, N < 15, su < 70 kPa)', source: 'Table 6.2.13', overridden: false },
		]);
	});
});
