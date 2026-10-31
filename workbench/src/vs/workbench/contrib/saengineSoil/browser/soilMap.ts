/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { boreholePosition, formatNumber, IBorehole, IBtm, ILatLon, IPlotSide, ISoilLocationResult, ISoilPlot, ISoilReport, ISoilSite } from './soilDocument.js';

/*
 * The model of the site map (soilMapView.ts), free of the DOM and of MapLibre: the tile source and
 * its attribution, coordinates as the engineer reads and types them, what the map can show
 * (tiles, or the plain grid when there are none) and the BNBC suggestion for the site.
 */

/** OpenStreetMap's standard tiles (https://operations.osmfoundation.org/policies/tiles/). */
export const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

/** The attribution OpenStreetMap asks for, always on the map (https://www.openstreetmap.org/copyright). */
export const OSM_ATTRIBUTION = '© OpenStreetMap contributors';
export const OSM_COPYRIGHT_URL = 'https://www.openstreetmap.org/copyright';

/** The zoom the standard tiles go to. */
export const OSM_MAX_ZOOM = 19;

export interface ITileSource {
	/** The URL template, with {z}, {x} and {y}. */
	readonly url: string;
	/** Whether it is OpenStreetMap's own server (its usage policy applies). */
	readonly osm: boolean;
	readonly attribution: string;
	/** Why the configured template is not used (the standard tiles are then). */
	readonly problem?: string;
}

/**
 * The tiles of the map: the configured template when it is a web address with {z}, {x} and {y},
 * else OpenStreetMap's. Another server's tiles keep the OpenStreetMap attribution unless the
 * engineer gives one (most tile servers draw OpenStreetMap data).
 */
export function tileSource(setting: unknown, attribution?: unknown): ITileSource {
	const text = typeof setting === 'string' ? setting.trim() : '';
	const own = typeof attribution === 'string' && attribution.trim() ? attribution.trim() : OSM_ATTRIBUTION;
	if (!text || text === OSM_TILE_URL) {
		return { url: OSM_TILE_URL, osm: true, attribution: OSM_ATTRIBUTION };
	}
	if (!/^https?:\/\//i.test(text) || !['{z}', '{x}', '{y}'].every(part => text.includes(part))) {
		return {
			url: OSM_TILE_URL, osm: true, attribution: OSM_ATTRIBUTION,
			problem: localize('soil.map.badTileUrl', "The tile URL {0} is not a web address with {z}, {x} and {y}; the OpenStreetMap tiles are shown.", text),
		};
	}
	const osm = /^https?:\/\/([a-c]\.)?tile\.openstreetmap\.org\//i.test(text);
	return { url: text, osm, attribution: osm ? OSM_ATTRIBUTION : own };
}

// ───────────────────────────── coordinates ─────────────────────────────

export function isLatLon(value: unknown): value is ILatLon {
	const ll = value as ILatLon | undefined;
	return !!ll && typeof ll.lat === 'number' && typeof ll.lon === 'number' && Number.isFinite(ll.lat) && Number.isFinite(ll.lon)
		&& Math.abs(ll.lat) <= 90 && Math.abs(ll.lon) <= 180;
}

/** Roughly Bangladesh's extent: the BNBC location towns only apply inside it. */
const BANGLADESH = { south: 20.3, north: 26.8, west: 87.9, east: 92.8 };

export function inBangladesh(ll: ILatLon): boolean {
	return ll.lat >= BANGLADESH.south && ll.lat <= BANGLADESH.north && ll.lon >= BANGLADESH.west && ll.lon <= BANGLADESH.east;
}

/** "23.810300° N" (6 decimals: about 0.1 m). */
export function formatDegrees(value: number, axis: 'lat' | 'lon', decimals = 6): string {
	const hemisphere = axis === 'lat' ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
	return `${Math.abs(value).toFixed(decimals)}° ${hemisphere}`;
}

/** "23°48′37.08″ N" */
export function formatDms(value: number, axis: 'lat' | 'lon'): string {
	const hemisphere = axis === 'lat' ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
	let total = Math.round(Math.abs(value) * 360000); // hundredths of a second
	const degrees = Math.floor(total / 360000);
	total -= degrees * 360000;
	const minutes = Math.floor(total / 6000);
	const seconds = (total - minutes * 6000) / 100;
	return `${degrees}°${String(minutes).padStart(2, '0')}′${seconds.toFixed(2).padStart(5, '0')}″ ${hemisphere}`;
}

/** "23.810300° N, 90.412500° E" */
export function formatLatLon(ll: ILatLon, style: 'decimal' | 'dms' = 'decimal'): string {
	return style === 'dms'
		? `${formatDms(ll.lat, 'lat')}, ${formatDms(ll.lon, 'lon')}`
		: `${formatDegrees(ll.lat, 'lat')}, ${formatDegrees(ll.lon, 'lon')}`;
}

/** BTM as the survey drawings give it: "E 540 123.45 m, N 2 633 456.78 m". */
export function formatBtm(btm: IBtm): string {
	const group = (value: number) => {
		const [whole, fraction] = value.toFixed(2).split('.');
		return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')}.${fraction}`;
	};
	return localize('soil.map.btm', "E {0} m, N {1} m", group(btm.easting), group(btm.northing));
}

/** Project coordinates [mm] in m: "X 12.5 m, Y −3 m". */
export function formatProjectPoint(x: number, y: number): string {
	return localize('soil.map.project', "X {0} m, Y {1} m", formatNumber(x / 1000, 3), formatNumber(y / 1000, 3));
}

/** "850 m", "3.2 km" */
export function formatDistance(metres: number): string {
	return metres < 1000 ? localize('soil.map.metres', "{0} m", formatNumber(metres, 0)) : localize('soil.map.km', "{0} km", formatNumber(metres / 1000, 1));
}

/** One coordinate typed: decimal degrees or degrees, minutes and seconds, with N/S/E/W or a sign. */
function parseOne(text: string): { value: number; hemisphere?: string } | undefined {
	const t = text.trim().toUpperCase();
	const hemisphere = /[NSEW]/.exec(t)?.[0];
	const numbers = t.replace(/[NSEW]/g, ' ').match(/-?\d+(?:\.\d+)?/g);
	if (!numbers?.length || numbers.length > 3) {
		return undefined;
	}
	const [d, m = '0', s = '0'] = numbers;
	const degrees = Number(d);
	const minutes = Number(m);
	const seconds = Number(s);
	if (numbers.length > 1 && (minutes >= 60 || seconds >= 60 || minutes < 0 || seconds < 0)) {
		return undefined;
	}
	const sign = degrees < 0 || hemisphere === 'S' || hemisphere === 'W' ? -1 : 1;
	return { value: sign * (Math.abs(degrees) + minutes / 60 + seconds / 3600), hemisphere };
}

/**
 * A position typed or pasted: "23.8103, 90.4125", "23.8103 N 90.4125 E", "23°48′37″N 90°24′45″E"
 * (as Google Maps and QGIS copy them). Latitude first unless the letters say otherwise; two bare
 * numbers that only read as a place in Bangladesh as x, y ("90.4125, 23.8103", the GeoJSON order),
 * or whose first is beyond ±90°, are taken as longitude, latitude.
 */
export function parseLatLon(text: string): ILatLon | undefined {
	const t = text.trim().replace(/[°′″'"]/g, ' ');
	let parts = t.split(/[,;]/).map(p => p.trim()).filter(Boolean);
	if (parts.length !== 2) {
		// "23.8103 N 90.4125 E": split after the first hemisphere letter, or two bare numbers.
		const byLetter = /^(?<first>.*?[NS])\s+(?<second>.*[EW])$/i.exec(t) ?? /^(?<first>.*?[EW])\s+(?<second>.*[NS])$/i.exec(t);
		if (byLetter?.groups) {
			parts = [byLetter.groups.first, byLetter.groups.second];
		} else {
			const numbers = t.split(/\s+/).filter(Boolean);
			parts = numbers.length === 2 ? numbers : [];
		}
	}
	if (parts.length !== 2) {
		return undefined;
	}
	const a = parseOne(parts[0]);
	const b = parseOne(parts[1]);
	if (!a || !b) {
		return undefined;
	}
	let swapped = a.hemisphere === 'E' || a.hemisphere === 'W' || b.hemisphere === 'N' || b.hemisphere === 'S';
	if (!a.hemisphere && !b.hemisphere) {
		// Two bare numbers: latitude first (Google Maps), unless they read as x, y (GeoJSON, a QGIS
		// copy): the first is beyond ±90°, or only the swapped pair lies in Bangladesh.
		const asGiven = { lat: a.value, lon: b.value };
		const asXy = { lat: b.value, lon: a.value };
		swapped = Math.abs(a.value) > 90 && Math.abs(b.value) <= 90
			|| isLatLon(asXy) && inBangladesh(asXy) && !(isLatLon(asGiven) && inBangladesh(asGiven));
	}
	const ll = swapped ? { lat: b.value, lon: a.value } : { lat: a.value, lon: b.value };
	return isLatLon(ll) ? ll : undefined;
}

// ───────────────────────────── what the map shows ─────────────────────────────

/**
 * `map`: the tiles with the points; `offline`: no tiles (no connection, MapLibre or WebGL
 * unavailable): the plain grid of the project coordinates with the outline and the points;
 * `noSite`: the site has no position yet: the grid, and a box to give it.
 */
export type MapState = 'map' | 'offline' | 'noSite';

export function mapState(options: { readonly hasSite: boolean; readonly online: boolean; readonly mapLibre: boolean; readonly tilesFailed: boolean }): MapState {
	if (!options.hasSite) {
		return 'noSite';
	}
	return options.online && options.mapLibre && !options.tilesFailed ? 'map' : 'offline';
}

/** The quiet note of the offline state: why there are no tiles. */
export function offlineNote(options: { readonly online: boolean; readonly mapLibre: boolean; readonly tilesFailed: boolean }): string {
	if (!options.online) {
		return localize('soil.map.offline', "Offline: no map tiles. The grid shows the project coordinates, the building outline and the boreholes.");
	}
	if (!options.mapLibre) {
		return localize('soil.map.noMapLibre', "The map could not be started here. The grid shows the project coordinates, the building outline and the boreholes.");
	}
	return localize('soil.map.tilesFailed', "The map tiles could not be loaded. The grid shows the project coordinates, the building outline and the boreholes.");
}

/**
 * The site's position: the report's own site point, else what the backend places it at (the
 * mean of the boreholes given on the map), else the first borehole with its own lat/lon.
 */
export function sitePosition(report: ISoilReport, location?: ISoilLocationResult): ILatLon | undefined {
	const site = report.site;
	if (isLatLon(site)) {
		return { lat: site.lat, lon: site.lon };
	}
	const placed = location?.site;
	if (isLatLon(placed)) {
		return { lat: placed.lat, lon: placed.lon };
	}
	const own = report.boreholes.find(isLatLon);
	return own && isLatLon(own) ? { lat: own.lat, lon: own.lon } : undefined;
}

/** Whether the project grid is on the map: the site has its own lat/lon. */
export function isGeoreferenced(report: ISoilReport): boolean {
	return isLatLon(report.site);
}

export interface IMapPoint extends ILatLon {
	readonly id: string;
	/** The borehole's place in the report. */
	readonly index: number;
	/** Project coordinates [mm], when known. */
	readonly x?: number;
	readonly y?: number;
	readonly btm?: IBtm;
	/** Whether the borehole is placed by its own lat/lon or BTM (else from x, y through the site). */
	readonly own: boolean;
}

/**
 * The boreholes with a geographic position: as the backend placed them, else their own lat/lon
 * (without a backend). Boreholes in project x, y need the backend and a site point.
 */
export function boreholePoints(report: ISoilReport, location?: ISoilLocationResult): IMapPoint[] {
	const points: IMapPoint[] = [];
	report.boreholes.forEach((borehole, index) => {
		const placed = location?.boreholes?.find(b => b.id === borehole.id);
		const own = boreholePosition(borehole) !== 'project';
		const number = (value: number | null | undefined) => typeof value === 'number' ? value : undefined;
		if (placed && typeof placed.lat === 'number' && typeof placed.lon === 'number') {
			points.push({ id: borehole.id, index, lat: placed.lat, lon: placed.lon, x: number(placed.x), y: number(placed.y), btm: placed.btm ?? undefined, own });
		} else if (isLatLon(borehole)) {
			points.push({ id: borehole.id, index, lat: borehole.lat, lon: borehole.lon, x: own ? undefined : borehole.x, y: own ? undefined : borehole.y, own });
		}
	});
	return points;
}

/** Two positions further apart than this disagree [m]. */
export const POSITION_TOLERANCE = 2;

/** The great-circle distance between two points [m]. */
export function distanceBetween(a: ILatLon, b: ILatLon): number {
	const radians = Math.PI / 180;
	const dLat = (b.lat - a.lat) * radians;
	const dLon = (b.lon - a.lon) * radians;
	const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * radians) * Math.cos(b.lat * radians) * Math.sin(dLon / 2) ** 2;
	return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * The project X and Y [mm] of a borehole as the backend places it: worked out from its latitude
 * and longitude (or BTM) when they place it, else its own. The stored X and Y of a borehole
 * placed by lat/lon only follow when the site or a borehole is moved, so they may be old.
 */
export function boreholeXY(borehole: IBorehole, location: ISoilLocationResult | undefined): { x: number; y: number } {
	if (boreholePosition(borehole) !== 'project') {
		const placed = location?.boreholes?.find(b => b.id === borehole.id);
		if (typeof placed?.x === 'number' && typeof placed.y === 'number') {
			return { x: placed.x, y: placed.y };
		}
	}
	return { x: borehole.x, y: borehole.y };
}

/**
 * How far apart a borehole's two positions are [m], when they disagree by more than
 * POSITION_TOLERANCE: for one placed by lat/lon (or BTM), its stored X and Y and those worked out;
 * for one placed by X and Y that also has a latitude and longitude, those and the point its X
 * and Y give on a georeferenced site.
 */
export function positionMismatch(borehole: IBorehole, location: ISoilLocationResult | undefined): number | undefined {
	const placed = location?.boreholes?.find(b => b.id === borehole.id);
	if (!placed) {
		return undefined;
	}
	let metres: number | undefined;
	if (boreholePosition(borehole) !== 'project') {
		if (typeof placed.x === 'number' && typeof placed.y === 'number') {
			metres = Math.hypot(placed.x - borehole.x, placed.y - borehole.y) / 1000;
		}
	} else if (isLatLon(borehole) && location?.site?.georeferenced && typeof placed.lat === 'number' && typeof placed.lon === 'number') {
		metres = distanceBetween(borehole, { lat: placed.lat, lon: placed.lon });
	}
	return metres !== undefined && metres > POSITION_TOLERANCE ? metres : undefined;
}

/**
 * Stores the X and Y the backend worked out for the boreholes placed by lat/lon (or BTM), so
 * that what is shown and stored agrees with the map after the site moved. Whether any changed.
 */
export function syncPlacedXY(report: ISoilReport, location: ISoilLocationResult | undefined): boolean {
	let changed = false;
	for (const borehole of report.boreholes) {
		if (boreholePosition(borehole) === 'project') {
			continue;
		}
		const placed = location?.boreholes?.find(b => b.id === borehole.id);
		if (typeof placed?.x !== 'number' || typeof placed.y !== 'number') {
			continue;
		}
		const x = Math.round(placed.x);
		const y = Math.round(placed.y);
		if (x !== borehole.x || y !== borehole.y) {
			borehole.x = x;
			borehole.y = y;
			changed = true;
		}
	}
	return changed;
}

/** The building's outline as the map draws it: [lon, lat] rings, closed. */
export function outlineRings(location: ISoilLocationResult | undefined): number[][][] {
	const ring = (location?.outline ?? []).filter(p => p.length >= 2 && p.every(Number.isFinite)).map(p => [p[0], p[1]]);
	return ring.length > 3 ? [ring] : [];
}

/** The building's outline in project coordinates [mm] for the plain grid. */
export function outlineProject(location: ISoilLocationResult | undefined): { x: number; y: number }[] {
	return (location?.outlineProject ?? []).filter(p => p.length >= 2 && p.every(Number.isFinite)).map(p => ({ x: p[0], y: p[1] }));
}

export interface IBnbcSuggestion {
	readonly text: string;
	/** The settings' location id to apply; undefined when the town is not one of the settings' list (applied as Custom, Z and V). */
	readonly location?: string;
	readonly Z?: number;
	readonly windSpeed?: number;
	/**
	 * With a listed location: the wind speed to set as its override, when the nearest town that
	 * lists a wind speed is another town than the zone's (so the banner's wind is what is used).
	 */
	readonly windSpeedOverride?: number;
}

/**
 * The banner's suggestion: the nearest BNBC towns' zone and wind speed, unless the project
 * settings already use those values.
 */
export function bnbcSuggestion(location: ISoilLocationResult | undefined): IBnbcSuggestion | undefined {
	const s = location?.suggestion;
	if (!s?.town) {
		return undefined;
	}
	const current = s.current;
	// The backend compares the values (Z and V) the settings use; the location id alone is not
	// enough, as the wind may come from another town than the zone.
	const same = current && (typeof s.differs === 'boolean' ? !s.differs : !!s.settingsLocation && current.location === s.settingsLocation);
	if (same) {
		return undefined;
	}
	const values: string[] = [];
	if (typeof s.zone === 'number') {
		values.push(localize('soil.map.zone', "seismic zone {0}", s.zone));
	}
	if (typeof s.windSpeed === 'number') {
		values.push(s.windTown && s.windTown !== s.town && typeof s.windDistanceKm === 'number'
			? localize('soil.map.windOf', "wind {0} m/s ({1}, {2})", formatNumber(s.windSpeed, 1), s.windTown, formatDistance(s.windDistanceKm * 1000))
			: localize('soil.map.wind', "wind {0} m/s", formatNumber(s.windSpeed, 1)));
	}
	const distance = formatDistance(s.distanceKm * 1000);
	const windSpeed = typeof s.windSpeed === 'number' ? s.windSpeed : undefined;
	const windElsewhere = !!s.windTown && s.windTown !== s.town;
	return {
		location: s.settingsLocation ?? undefined,
		Z: typeof s.Z === 'number' ? s.Z : undefined,
		windSpeed,
		...(s.settingsLocation && windElsewhere && windSpeed !== undefined ? { windSpeedOverride: windSpeed } : {}),
		text: values.length
			? localize('soil.map.nearest', "Nearest town {0}, {1}: {2}", s.town, distance, values.join(', '))
			: localize('soil.map.nearestOnly', "Nearest town {0}, {1}", s.town, distance),
	};
}


// ───────────────────────────── the plain grid ─────────────────────────────

export interface IGridExtent {
	readonly minX: number;
	readonly minY: number;
	readonly maxX: number;
	readonly maxY: number;
}

/** The extent of points in project coordinates [mm], at least 20 m across, with a margin. */
export function gridExtent(points: readonly { readonly x: number; readonly y: number }[]): IGridExtent {
	if (!points.length) {
		return { minX: -10000, minY: -10000, maxX: 10000, maxY: 10000 };
	}
	let minX = Math.min(...points.map(p => p.x));
	let maxX = Math.max(...points.map(p => p.x));
	let minY = Math.min(...points.map(p => p.y));
	let maxY = Math.max(...points.map(p => p.y));
	const size = Math.max(20000, maxX - minX, maxY - minY);
	const cx = (minX + maxX) / 2;
	const cy = (minY + maxY) / 2;
	const half = size * 0.6;
	minX = cx - half;
	maxX = cx + half;
	minY = cy - half;
	maxY = cy + half;
	return { minX, minY, maxX, maxY };
}

/** A label at a point on screen: its anchor (left, middle) and width [px]. */
export interface ILabelBox {
	readonly x: number;
	readonly y: number;
	readonly width: number;
}

/**
 * How far down to move each label [px] so none overlaps another: labels are placed top to
 * bottom (then left to right), each one stepping down a line while it overlaps one placed.
 */
export function spreadLabels(labels: readonly ILabelBox[], lineHeight = 14): number[] {
	const order = labels.map((_, i) => i).sort((a, b) => labels[a].y - labels[b].y || labels[a].x - labels[b].x);
	const placed: { x1: number; x2: number; y1: number; y2: number }[] = [];
	const offsets = labels.map(() => 0);
	for (const i of order) {
		const { x, y, width } = labels[i];
		let dy = 0;
		const overlaps = () => placed.some(p => x < p.x2 && x + width > p.x1 && y + dy - lineHeight / 2 < p.y2 && y + dy + lineHeight / 2 > p.y1);
		for (let step = 0; step < 8 && overlaps(); step++) {
			dy += lineHeight;
		}
		offsets[i] = dy;
		placed.push({ x1: x, x2: x + width, y1: y + dy - lineHeight / 2, y2: y + dy + lineHeight / 2 });
	}
	return offsets;
}

/** The south-west and north-east corners around the points, or undefined for fewer than two. */
export function boundsOf(points: readonly ILatLon[]): [[number, number], [number, number]] | undefined {
	if (points.length < 2) {
		return undefined;
	}
	const lons = points.map(p => p.lon);
	const lats = points.map(p => p.lat);
	return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

// ───────────────────────────── the plot ─────────────────────────────

/** One foot [mm]; the plot can be typed in m or ft. */
export const FOOT = 304.8;

export type LengthUnit = 'm' | 'ft';

/** "240 m² (3.59 katha, 5.93 decimal)": the area as Bangladeshi deeds give it too. */
export function formatPlotArea(area: number, katha: number, decimal: number): string {
	return localize('soil.plot.area', "{0} m² ({1} katha, {2} decimal)", formatNumber(area, 1), formatNumber(katha, 2), formatNumber(decimal, 2));
}

/** A length typed in `unit` ("12", "12.5", "40 ft") as mm, or undefined when it is not a positive number. */
export function parsePlotLength(text: string, unit: LengthUnit): number | undefined {
	const trimmed = text.trim().replace(/\s*(m|ft|′)$/i, '');
	const value = trimmed ? Number(trimmed) : NaN;
	return Number.isFinite(value) && value > 0 ? value * (unit === 'ft' ? FOOT : 1000) : undefined;
}

/** A side of the project grid: the bottom (−Y), right (+X), top (+Y) or left (−X). */
export type GridSide = '-y' | '+x' | '+y' | '-x';

export const GRID_SIDES: readonly GridSide[] = ['-y', '+x', '+y', '-x'];

/** The bearing a grid side faces (outwards) for the grid bearing `rotation` [°]. */
export function gridSideFacing(side: GridSide, rotation: number): number {
	const offset = { '-y': 180, '+x': 90, '+y': 0, '-x': 270 }[side];
	return ((rotation + offset) % 360 + 360) % 360;
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

/** The compass point of a bearing: "SW". */
export function compassPoint(degrees: number): string {
	return COMPASS[((Math.round(degrees / 45) % 8) + 8) % 8];
}

/** "Bottom (−Y), faces S": a grid side as the road side list shows it. */
export function gridSideLabel(side: GridSide, rotation: number): string {
	const facing = compassPoint(gridSideFacing(side, rotation));
	switch (side) {
		case '-y': return localize('soil.plot.sideBottom', "Bottom (−Y), faces {0}", facing);
		case '+x': return localize('soil.plot.sideRight', "Right (+X), faces {0}", facing);
		case '+y': return localize('soil.plot.sideTop', "Top (+Y), faces {0}", facing);
		case '-x': return localize('soil.plot.sideLeft', "Left (−X), faces {0}", facing);
	}
}

/**
 * A rectangular plot `frontage` × `depth` [mm], the frontage along the road side, aligned with the
 * project grid with its lower-left corner at `origin` (the project point): its corners
 * counter-clockwise from there, and the index of the road side (side i runs from corner i).
 */
export function rectanglePlot(frontage: number, depth: number, road: GridSide, origin: { readonly x: number; readonly y: number }): { readonly points: number[][]; readonly road: number } {
	const alongX = road === '-y' || road === '+y';
	const [w, h] = alongX ? [frontage, depth] : [depth, frontage];
	const points = [[0, 0], [w, 0], [w, h], [0, h]].map(([x, y]) => [Math.round(origin.x + x), Math.round(origin.y + y)]);
	return { points, road: GRID_SIDES.indexOf(road) };
}

/** The road side after corner `index` is deleted: the two sides at it become one (the earlier). */
export function roadAfterDelete(road: number | undefined, index: number, corners: number): number | undefined {
	if (road === undefined || corners - 1 < 3) {
		return undefined;
	}
	if (road === index) {
		// The side from the deleted corner merges into the one before it.
		return (index - 1 + corners - 1) % (corners - 1);
	}
	return road > index ? road - 1 : road;
}

/** A change to the plot (`ISoilSite.boundary` and `plot`) from the map or the panel. */
export interface IPlotEdit {
	/** New corners as [lon, lat] (drawn on the map): the boundary; the project corners go. */
	readonly lonlat?: readonly (readonly number[])[];
	/** New corners in project mm (on the project grid, or a rectangle): the boundary goes. */
	readonly points?: readonly (readonly number[])[];
	/** The road side; null clears it. */
	readonly road?: number | null;
	/** Setbacks [mm]; null clears one. */
	readonly front?: number | null;
	readonly rear?: number | null;
	readonly side?: number | null;
	/** Removes the plot (boundary, corners, road side; the setbacks stay). */
	readonly clear?: boolean;
}

/** Applies `edit` to `site` in place, the way the soil report stores the plot. */
export function applyPlotEdit(site: ISoilSite, edit: IPlotEdit): void {
	const plot: ISoilPlot = site.plot ?? {};
	if (edit.clear) {
		delete site.boundary;
		delete plot.points;
		delete plot.road;
	}
	if (edit.lonlat) {
		site.boundary = edit.lonlat.map(([lon, lat]) => [Number(lon.toFixed(8)), Number(lat.toFixed(8))]);
		delete plot.points;
	} else if (edit.points) {
		plot.points = edit.points.map(([x, y]) => [Math.round(x), Math.round(y)]);
		delete site.boundary;
	}
	for (const key of ['road', 'front', 'rear', 'side'] as const) {
		const value = edit[key];
		if (value === null) {
			delete plot[key];
		} else if (typeof value === 'number' && Number.isFinite(value)) {
			plot[key] = key === 'road' ? value : Math.round(value);
		}
	}
	const corners = site.boundary?.length || plot.points?.length || 0;
	if (typeof plot.road === 'number' && plot.road >= corners) {
		delete plot.road;
	}
	if (!site.boundary?.length) {
		delete site.boundary;
	}
	if (Object.keys(plot).length) {
		site.plot = plot;
	} else {
		delete site.plot;
	}
}

/**
 * The plot's corners as the map draws them ([lon, lat], open ring): the backend's, else the
 * site's own boundary (without a backend).
 */
export function plotLonLat(report: ISoilReport, location: ISoilLocationResult | undefined): number[][] {
	const ring = location?.plot?.lonlat;
	if (ring && ring.length > 3) {
		return ring.slice(0, -1).map(p => [p[0], p[1]]);
	}
	return (report.site?.boundary ?? []).filter(p => p.length >= 2 && p.every(Number.isFinite)).map(p => [p[0], p[1]]);
}

/** The plot's corners in project mm for the plain grid: the backend's, else the plot's own corners. */
export function plotProject(report: ISoilReport, location: ISoilLocationResult | undefined): { x: number; y: number }[] {
	const own = report.site?.boundary?.length ? [] : report.site?.plot?.points ?? [];
	const ring = location?.plot?.ring ?? own;
	return ring.filter(p => p.length >= 2 && p.every(Number.isFinite)).map(p => ({ x: p[0], y: p[1] }));
}

/** The buildable envelope in project mm for the plain grid. */
export function envelopeProject(location: ISoilLocationResult | undefined): { x: number; y: number }[] {
	return (location?.plot?.envelope ?? []).filter(p => p.length >= 2 && p.every(Number.isFinite)).map(p => ({ x: p[0], y: p[1] }));
}

/** "Side 2: 20 m, faces SE (front)": a side of the plot in the road side list. */
export function plotSideLabel(side: IPlotSide): string {
	const length = formatNumber(side.length / 1000, 2);
	const kind = side.kind === 'front' ? localize('soil.plot.front', "front")
		: side.kind === 'rear' ? localize('soil.plot.rear', "rear")
			: side.kind === 'side' ? localize('soil.plot.side', "side") : undefined;
	return kind
		? localize('soil.plot.sideKind', "Side {0}: {1} m, faces {2} ({3})", side.index + 1, length, side.facing, kind)
		: localize('soil.plot.sideLabel', "Side {0}: {1} m, faces {2}", side.index + 1, length, side.facing);
}
