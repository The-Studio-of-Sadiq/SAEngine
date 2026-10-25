/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { ILatLon, ISoilLocationResult, ISoilReport, newSoilReport } from '../../browser/soilDocument.js';
import { bnbcSuggestion, boreholePoints, boundsOf, spreadLabels, formatBtm, formatDegrees, formatDistance, formatDms, formatLatLon, gridExtent, inBangladesh, mapState, OSM_ATTRIBUTION, OSM_TILE_URL, outlineProject, outlineRings, parseLatLon, sitePosition, tileSource } from '../../browser/soilMap.js';

function report(extra: Partial<ISoilReport> = {}): ISoilReport {
	return {
		...newSoilReport(),
		boreholes: [
			{ id: 'BH-1', x: 0, y: 0, lat: 23.8103, lon: 90.4125, layers: [], spt: [], samples: [] },
			{ id: 'BH-2', x: 20000, y: 0, layers: [], spt: [], samples: [] },
			{ id: 'BH-3', x: 0, y: 15000, layers: [], spt: [], samples: [] },
		],
		...extra,
	};
}

const round = (ll: ILatLon | undefined) => ll && { lat: Number(ll.lat.toFixed(6)), lon: Number(ll.lon.toFixed(6)) };

suite('SAEngine - Soil site map', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('formats coordinates as decimal degrees, DMS, BTM and distances', () => {
		// 23.8103° = 23° 48.618′ = 23° 48′ 37.08″; 90.4125° = 90° 24.75′ = 90° 24′ 45″.
		assert.deepStrictEqual([
			formatDegrees(23.8103, 'lat'),
			formatDegrees(-1.5, 'lon'),
			formatDms(23.8103, 'lat'),
			formatDms(90.4125, 'lon'),
			formatLatLon({ lat: 23.8103, lon: 90.4125 }),
			formatBtm({ easting: 540123.456, northing: 2633456.789 }),
			formatDistance(850),
			formatDistance(3240),
		], [
			'23.810300° N',
			'1.500000° W',
			'23°48′37.08″ N',
			'90°24′45.00″ E',
			'23.810300° N, 90.412500° E',
			'E 540 123.46 m, N 2 633 456.79 m',
			'850 m',
			'3.2 km',
		]);
	});

	test('reads coordinates as Google Maps, QGIS and survey sheets give them', () => {
		assert.deepStrictEqual([
			round(parseLatLon('23.8103, 90.4125')),
			round(parseLatLon('23.8103 90.4125')),
			round(parseLatLon('23.8103 N, 90.4125 E')),
			round(parseLatLon('90.4125 E 23.8103 N')),
			round(parseLatLon('23°48′37.08″N 90°24′45″E')),
			round(parseLatLon('-33.86, 151.21')),
			round(parseLatLon('89.5403,22.8456')),
			round(parseLatLon('90.4125 23.8103')),
			round(parseLatLon('22.8456, 89.5403')),
			round(parseLatLon('151.21, -33.86')),
			parseLatLon('95, 200'),
			parseLatLon('Dhaka'),
			parseLatLon('23° 61′ 0″ N, 90° E'),
		], [
			{ lat: 23.8103, lon: 90.4125 },
			{ lat: 23.8103, lon: 90.4125 },
			{ lat: 23.8103, lon: 90.4125 },
			{ lat: 23.8103, lon: 90.4125 },
			{ lat: 23.8103, lon: 90.4125 },
			{ lat: -33.86, lon: 151.21 },
			{ lat: 22.8456, lon: 89.5403 },
			{ lat: 23.8103, lon: 90.4125 },
			{ lat: 22.8456, lon: 89.5403 },
			{ lat: -33.86, lon: 151.21 },
			undefined,
			undefined,
			undefined,
		]);
		assert.deepStrictEqual([inBangladesh({ lat: 23.8103, lon: 90.4125 }), inBangladesh({ lat: 51.5, lon: 0 })], [true, false]);
	});

	test('uses the configured tiles only when they are a tile URL', () => {
		assert.deepStrictEqual([
			tileSource(undefined),
			tileSource('https://tiles.example.org/{z}/{x}/{y}.png'),
			tileSource('https://a.tile.openstreetmap.org/{z}/{x}/{y}.png').osm,
			tileSource('ftp://tiles.example.org/{z}/{x}/{y}.png').url,
			tileSource('https://tiles.example.org/tile.png').problem !== undefined,
		], [
			{ url: OSM_TILE_URL, osm: true, attribution: OSM_ATTRIBUTION },
			{ url: 'https://tiles.example.org/{z}/{x}/{y}.png', osm: false, attribution: OSM_ATTRIBUTION },
			true,
			OSM_TILE_URL,
			true,
		]);
	});

	test('shows the map only with a site, a connection, MapLibre and tiles', () => {
		const all = { hasSite: true, online: true, mapLibre: true, tilesFailed: false };
		assert.deepStrictEqual([
			mapState(all),
			mapState({ ...all, hasSite: false }),
			mapState({ ...all, online: false }),
			mapState({ ...all, mapLibre: false }),
			mapState({ ...all, tilesFailed: true }),
			mapState({ ...all, hasSite: false, online: false }),
		], ['map', 'noSite', 'offline', 'offline', 'offline', 'noSite']);
	});

	test('places the site and the boreholes: as the backend placed them, else their own lat/lon', () => {
		const location: ISoilLocationResult = {
			site: { lat: 23.8103, lon: 90.4125, georeferenced: false },
			boreholes: [
				{ id: 'BH-1', position: 'wgs84', lat: 23.8103, lon: 90.4125, x: 12, y: -4, btm: null },
				{ id: 'BH-2', position: 'project', lat: 23.8103, lon: 90.4127, x: 20000, y: 0, btm: { easting: 540000, northing: 2633000 } },
				{ id: 'BH-3', position: 'project', lat: null, lon: null, x: null, y: null, btm: null },
			],
			outline: [[90.41, 23.81], [90.4101, 23.81], [90.4101, 23.8101], [90.41, 23.81]],
			outlineProject: [[0, 0], [10000, 0], [10000, 10000]],
		};
		assert.deepStrictEqual({
			points: boreholePoints(report(), location).map(p => [p.id, p.index, p.own, p.x, p.btm?.easting]),
			withoutBackend: boreholePoints(report()).map(p => [p.id, p.own, p.x]),
			site: sitePosition(report({ site: { lat: 23.81, lon: 90.41 } })),
			fromBorehole: sitePosition(report()),
			none: sitePosition({ ...newSoilReport() }),
			fromBackend: sitePosition({ ...newSoilReport() }, { site: { lat: 23.7, lon: 90.4 } }),
			rings: outlineRings(location).length,
			tooShort: outlineRings({ outline: [[90.41, 23.81], [90.42, 23.81]] }),
			project: outlineProject(location),
		}, {
			points: [['BH-1', 0, true, 12, undefined], ['BH-2', 1, false, 20000, 540000]],
			withoutBackend: [['BH-1', true, undefined]],
			site: { lat: 23.81, lon: 90.41 },
			fromBorehole: { lat: 23.8103, lon: 90.4125 },
			none: undefined,
			fromBackend: { lat: 23.7, lon: 90.4 },
			rings: 1,
			tooShort: [],
			project: [{ x: 0, y: 0 }, { x: 10000, y: 0 }, { x: 10000, y: 10000 }],
		});
	});

	test('suggests the nearest BNBC town until the settings use it', () => {
		const dhaka = { town: 'Dhaka', distanceKm: 3.2, zone: 2, Z: 0.2, windSpeed: 65.7, windTown: 'Dhaka', windDistanceKm: 3.2, settingsLocation: 'dhaka' };
		assert.deepStrictEqual([
			bnbcSuggestion({ suggestion: dhaka }),
			bnbcSuggestion({ suggestion: { ...dhaka, current: { location: 'chattogram', Z: 0.28, windSpeed: 80 }, differs: true } }),
			bnbcSuggestion({ suggestion: { ...dhaka, current: { location: 'dhaka', Z: 0.2, windSpeed: 65.7 }, differs: false } }),
			// The zone town is listed but the wind is a nearer other town's: the banner's wind is kept as the override, and the
			// banner stays while the settings' values differ although their location is the zone town.
			bnbcSuggestion({ suggestion: { town: 'Rajshahi', distanceKm: 20.1, zone: 1, Z: 0.12, windSpeed: 69.5, windTown: 'Ishurdi', windDistanceKm: 12.4, settingsLocation: 'rajshahi', current: { location: 'rajshahi', Z: 0.12, windSpeed: 72.1 }, differs: true } }),
			bnbcSuggestion({ suggestion: { town: 'Gazipur', distanceKm: 0.64, zone: 2, Z: 0.2, windSpeed: 66.5, windTown: 'Tangail', windDistanceKm: 41.3, settingsLocation: null } }),
			bnbcSuggestion({ suggestion: null }),
			bnbcSuggestion(undefined),
		], [
			{ location: 'dhaka', Z: 0.2, windSpeed: 65.7, text: 'Nearest town Dhaka, 3.2 km: seismic zone 2, wind 65.7 m/s' },
			{ location: 'dhaka', Z: 0.2, windSpeed: 65.7, text: 'Nearest town Dhaka, 3.2 km: seismic zone 2, wind 65.7 m/s' },
			undefined,
			{ location: 'rajshahi', Z: 0.12, windSpeed: 69.5, windSpeedOverride: 69.5, text: 'Nearest town Rajshahi, 20.1 km: seismic zone 1, wind 69.5 m/s (Ishurdi, 12.4 km)' },
			{ location: undefined, Z: 0.2, windSpeed: 66.5, text: 'Nearest town Gazipur, 640 m: seismic zone 2, wind 66.5 m/s (Tangail, 41.3 km)' },
			undefined,
			undefined,
		]);
	});

	test('the plain grid covers the points with a margin, at least 20 m', () => {
		// 30 m by 10 m of points: a 30 m square about (15, 5) m, 20% wider.
		assert.deepStrictEqual([
			gridExtent([{ x: 0, y: 0 }, { x: 30000, y: 10000 }]),
			gridExtent([{ x: 5000, y: 5000 }]),
			gridExtent([]),
		], [
			{ minX: -3000, minY: -13000, maxX: 33000, maxY: 23000 },
			{ minX: -7000, minY: -7000, maxX: 17000, maxY: 17000 },
			{ minX: -10000, minY: -10000, maxX: 10000, maxY: 10000 },
		]);
	});

	test('frames all boreholes and keeps their labels apart', () => {
		assert.deepStrictEqual({
			bounds: boundsOf([{ lat: 23.81, lon: 90.41 }, { lat: 23.8, lon: 90.42 }, { lat: 23.805, lon: 90.4 }]),
			one: boundsOf([{ lat: 23.81, lon: 90.41 }]),
			// Two labels on top of each other and one well apart.
			offsets: spreadLabels([{ x: 100, y: 100, width: 40 }, { x: 110, y: 104, width: 40 }, { x: 300, y: 100, width: 40 }], 14),
		}, {
			bounds: [[90.4, 23.8], [90.42, 23.81]],
			one: undefined,
			offsets: [0, 14, 0],
		});
	});
});
