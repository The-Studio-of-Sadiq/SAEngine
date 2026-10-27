/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { DEFAULT_SETTINGS } from '../../../../services/saengineProject/common/projectLibraries.generated.js';
import { codeCombinations, codeValues, designCategory, zoneOf } from '../../browser/settingsEditor.js';
import { JsonObject } from '../../browser/schemaForm.js';

suite('SAEngine - Project settings editor', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const values = (settings: JsonObject) => codeValues(settings).map(v => `${v.label}: ${v.value}${v.overridden ? ' (overridden)' : ''}`);

	test('code values follow the location, occupancy category and structural system, with overrides', () => {
		const defaults = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as JsonObject;
		const wind = ['Wind exposure: A', 'Directionality factor Kd: 0.85', 'Topographic factor Kzt: 1', 'Gust effect factor G: 0.85'];
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
				'Site class: SD',
				'Seismic Design Category: D',
				'Response reduction factor R: 8',
				'Overstrength factor Ω0: 3',
				'Deflection amplification Cd: 5.5',
				'Seismic detailing: special',
				...wind,
			],
			sylhet: [
				'Seismic zone: 4',
				'Zone coefficient Z: 0.36',
				'Basic wind speed V (m/s): 70 (overridden)',
				'Seismic importance factor I: 1.5',
				'Wind importance factor I: 1.15',
				'Site class: SC',
				'Seismic Design Category: D',
				'Response reduction factor R: 8',
				'Overstrength factor Ω0: 3',
				'Deflection amplification Cd: 5.5',
				'Seismic detailing: special',
				...wind,
			],
		});
	});

	test('the site class comes from the soil report unless it is entered; its description is on hover', () => {
		const defaults = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as JsonObject;
		const soil = { class: 'SC', label: 'SC (N̄ = 22 over 30 m, BH-2)' };
		const site = (settings: JsonObject) => codeValues(settings, soil).find(v => v.label === 'Site class');
		assert.deepStrictEqual([
			site(defaults),
			site({ ...defaults, site: { location: 'dhaka', siteClass: 'SD', siteClassSource: 'entered' } }),
		], [
			{ label: 'Site class', value: 'SC', source: 'Table 6.2.13, from 1 Soil Report: SC (N̄ = 22 over 30 m, BH-2)', detail: 'Dense or medium dense sand, gravel or stiff clay (Vs 180-360 m/s, N 15-50, su 70-250 kPa)' },
			{ label: 'Site class', value: 'SD', source: 'Table 6.2.13', detail: 'Loose-to-medium cohesionless soil or soft-to-firm cohesive soil (Vs < 180 m/s, N < 15, su < 70 kPa)' },
		]);
	});

	test('a system not permitted in the Seismic Design Category is flagged, with the special moment frame to switch to', () => {
		const defaults = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as JsonObject;
		const omrf = { ...defaults, seismic: { system: 'rcOmf' } };
		const category = designCategory(omrf, 'SD');
		assert.deepStrictEqual(
			{ sdc: category?.sdc, permitted: category?.permitted, required: category?.required, alternative: category?.alternative },
			{ sdc: 'D', permitted: false, required: 'special', alternative: 'rcSmf' });
		assert.ok(codeValues(omrf).find(v => v.label === 'Seismic detailing')?.problem?.includes('not permitted in Seismic Design Category D'));
		// Rajshahi (zone 1) on SC with an IMF: Category B, permitted, nothing to switch.
		assert.deepStrictEqual(designCategory({ ...defaults, site: { location: 'rajshahi' }, seismic: { system: 'rcImf' } }, 'SC')?.alternative, undefined);
	});

	test('a custom Z takes the zone whose coefficient is nearest', () => {
		assert.deepStrictEqual([0.12, 0.17, 0.25, 0.5].map(zoneOf), [1, 2, 3, 4]);
	});

	test('the code combinations add ±T after 1.2D + 1.6L + 0.5Lr when the temperature case is on', () => {
		const defaults = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as JsonObject;
		const names = (settings: JsonObject) => codeCombinations(settings).map(c => (c as JsonObject).name);
		const off = names(defaults);
		const on = names({ ...defaults, analysis: { thermal: { enabled: true } } });
		assert.deepStrictEqual({
			off: off.length,
			on: on.slice(1, 4),
			count: on.length,
		}, {
			off: 23,
			on: ['1.2D + 1.6L + 0.5Lr', '1.2D + 1.2T + 1.6L + 0.5Lr', '1.2D - 1.2T + 1.6L + 0.5Lr'],
			count: 25,
		});
	});
});
