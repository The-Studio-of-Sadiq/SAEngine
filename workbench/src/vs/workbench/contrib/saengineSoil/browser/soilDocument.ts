/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/*
 * The soil report of a project (`01 Soil Report/soil-report.json`, `saengine.soilReport/1`):
 * boreholes with their strata, SPT records and lab samples, and the design options of the
 * foundation checks. Lengths are in mm in the file (depths below the borehole's ground); the
 * editor shows them in m. What the backend computes from it (site class, allowable bearing,
 * liquefaction, subgrade modulus, pile parameters) is never stored in the file.
 */

export const SOIL_SCHEMA_ID = 'saengine.soilReport/1';

/** Desktop commands of the Python backend (`saengine.library.soil`); absent without one. */
export const SOIL_COMPUTE_COMMAND = 'saengine.soil.compute';
export const SOIL_IMPORT_COMMAND = 'saengine.soil.import';
export const SOIL_TEMPLATE_COMMAND = 'saengine.soil.template';

/**
 * Desktop commands of the backend for the site map (`saengine.gis`); absent without one, and the
 * map then shows the project coordinates only. Requests and results are below.
 */
export const SOIL_LOCATION_COMMAND = 'saengine.soil.location';
export const SOIL_GIS_EXPORT_COMMAND = 'saengine.soil.gisExport';
export const SOIL_GIS_IMPORT_COMMAND = 'saengine.soil.gisImport';
export const SOIL_QGIS_PROGRAM_COMMAND = 'saengine.soil.qgisProgram';
export const SOIL_OPEN_IN_QGIS_COMMAND = 'saengine.soil.openInQgis';
/** The plot and its buildable envelope in project mm, and the floor plan's members outside them. */
export const SOIL_PLOT_CHECK_COMMAND = 'saengine.soil.plotCheck';

/** The tile URL template of the site map (a setting the desktop registers). */
export const MAP_TILE_URL_SETTING = 'saengine.map.tileUrl';

/** The attribution of the tiles of {@link MAP_TILE_URL_SETTING} when they are not OpenStreetMap's. */
export const MAP_TILE_ATTRIBUTION_SETTING = 'saengine.map.tileAttribution';

/** The QGIS that Open in QGIS starts (a machine setting; empty: the QGIS found installed). */
export const QGIS_PROGRAM_SETTING = 'saengine.qgis.program';

/** Commands of the editor: they ask for a file, or take its path (tests, scripts). */
export const SOIL_IMPORT_FILE_COMMAND = 'saengine.soil.importFile';
export const SOIL_SAVE_TEMPLATE_COMMAND = 'saengine.soil.saveTemplate';
export const SOIL_ADD_BOREHOLE_COMMAND = 'saengine.soil.addBorehole';

export type SoilType = 'clay' | 'silt' | 'sand' | 'gravel' | 'organic' | 'fill' | 'rock';

export const SOIL_TYPES: readonly SoilType[] = ['clay', 'silt', 'sand', 'gravel', 'organic', 'fill', 'rock'];

export function soilTypeLabel(type: SoilType | string | undefined): string {
	switch (type) {
		case 'clay': return localize('soil.type.clay', "Clay");
		case 'silt': return localize('soil.type.silt', "Silt");
		case 'sand': return localize('soil.type.sand', "Sand");
		case 'gravel': return localize('soil.type.gravel', "Gravel");
		case 'organic': return localize('soil.type.organic', "Organic");
		case 'fill': return localize('soil.type.fill', "Fill");
		case 'rock': return localize('soil.type.rock', "Rock");
		default: return type ?? '';
	}
}

export interface ISoilLayer {
	top: number;
	bottom: number;
	description: string;
	soilType: SoilType;
	uscs?: string;
	unitWeight?: number;
	saturatedUnitWeight?: number;
	cu?: number;
	c?: number;
	phi?: number;
	E?: number;
	finesContent?: number;
	plasticityIndex?: number;
	liquidLimit?: number;
	Cc?: number;
	Cr?: number;
	e0?: number;
	OCR?: number;
	[key: string]: unknown;
}

/*
 * The fields of the log sheet (the consultant's borehole log) follow `saengine.library.soil`
 * (SptRecord, Sample and its test groups, Site, Borehole.position); written here by hand until
 * the schema that carries them is generated into the workbench. All are optional, so files
 * without them read as before.
 */

/** A refusal recorded as the blows of the test drive and its penetration ("50/100 mm"). */
export interface ISptRefusal {
	blows: number;
	/** Penetration of the test drive after the seating drive [mm], below 300. */
	penetration: number;
	[key: string]: unknown;
}

export interface ISptRecord {
	depth: number;
	/**
	 * Field N (blows for the last 300 mm): N1 + N2 when the increments are given, a refusal's
	 * blows extrapolated to 300 mm; the backend works it out when absent.
	 */
	N?: number;
	/** Blows of the seating drive (first 150 mm), not counted in N. */
	seat?: number;
	/** Blows of the second and third 150 mm increments. */
	N1?: number;
	N2?: number;
	/** The test drive stopped short of 300 mm: its blows and penetration, or true when not recorded. */
	refusal?: boolean | ISptRefusal;
	/** The split spoon sample's number ("D-3") and recovery [%], when no lab sample is listed at the depth. */
	sampleNumber?: string;
	recovery?: number;
	/** Bottom of the drive [mm]; the depth plus 450 mm when not given. */
	depthTo?: number;
	energyRatio?: number;
	[key: string]: unknown;
}

/** One sieve of a grain size analysis. */
export interface ISieve {
	/** Opening [mm]. */
	size: number;
	/** Percent passing [%]. */
	passing: number;
	[key: string]: unknown;
}

/** One load step of an oedometer test. */
export interface IConsolidationPoint {
	/** Effective vertical pressure [kPa]. */
	pressure: number;
	/** Void ratio at the end of the step. */
	e: number;
	[key: string]: unknown;
}

/** One specimen of a triaxial test. */
export interface ITriaxialSpecimen {
	/** Cell pressure σ3 [kPa]. */
	cell: number;
	/** Deviator stress at failure σ1 − σ3 [kPa]. */
	deviator: number;
	/** Pore pressure at failure [kPa] (CU tests). */
	porePressure?: number;
	[key: string]: unknown;
}

/** One specimen of a direct shear test. */
export interface IShearSpecimen {
	/** Normal stress [kPa]. */
	normal: number;
	/** Peak shear stress [kPa]. */
	shear: number;
	[key: string]: unknown;
}

export interface ISoilSample {
	depth: number;
	/** The sample's number on the log ("D-3", "UD-1"). */
	number?: string;
	type?: string;
	/** Bottom of the sample [mm]. */
	depthTo?: number;
	/** Recovered length over the driven length [%]. */
	recovery?: number;
	moisture?: number;
	unitWeight?: number;
	cu?: number;
	c?: number;
	phi?: number;
	finesContent?: number;
	liquidLimit?: number;
	plasticLimit?: number;
	Cc?: number;
	e0?: number;
	grainSize?: { sieves: ISieve[];[key: string]: unknown };
	consolidation?: { points: IConsolidationPoint[]; e0?: number; Cc?: number; Cr?: number; preconsolidation?: number; cv?: number;[key: string]: unknown };
	triaxial?: { type?: 'UU' | 'CU' | 'CD'; specimens: ITriaxialSpecimen[]; cu?: number; c?: number; phi?: number; effective?: boolean;[key: string]: unknown };
	directShear?: { specimens: IShearSpecimen[]; c?: number; phi?: number;[key: string]: unknown };
	/** Unconfined compression: qu [kPa] (cu = qu/2) and the strain at failure [%]. */
	ucs?: { qu: number; strain?: number;[key: string]: unknown };
	[key: string]: unknown;
}

export interface IBorehole {
	id: string;
	x: number;
	y: number;
	/**
	 * Which coordinates place the borehole; when absent: lat/lon if both are given, else the BTM
	 * easting and northing, else x, y. x, y follow from the others through the site point.
	 */
	position?: BoreholePosition;
	/** WGS 84 [°]. */
	lat?: number;
	lon?: number;
	/** Bangladesh Transverse Mercator [m]. */
	easting?: number;
	northing?: number;
	groundLevel?: number;
	waterTable?: number;
	depth?: number;
	/** Left out of the project's bearing table (a borehole far from the building, say). */
	excludeFromSite?: boolean;
	/** Date drilled and the boring method ("wash boring"), as the log sheet's header gives them. */
	date?: string;
	method?: string;
	layers: ISoilLayer[];
	spt: ISptRecord[];
	samples: ISoilSample[];
	[key: string]: unknown;
}

/**
 * Where the site is: the project point (x, y) [mm] at (lat, lon) (WGS 84), and the bearing of
 * the project's +Y axis clockwise from true north [°]. Places the boreholes and the building
 * outline on the map.
 */
export interface ISoilSite {
	lat?: number;
	lon?: number;
	x?: number;
	y?: number;
	rotation?: number;
	address?: string;
	/** The plot boundary as [lon, lat] points (drawn on the map or from QGIS); when given, it is the plot. */
	boundary?: number[][];
	plot?: ISoilPlot;
	[key: string]: unknown;
}

/**
 * The plot (`Site.plot`): its corners in project mm when the boundary is not given in lat/lon,
 * the side facing the road (side i runs from corner i to the next) and the setbacks [mm].
 */
export interface ISoilPlot {
	points?: number[][];
	road?: number;
	front?: number;
	rear?: number;
	side?: number;
	[key: string]: unknown;
}

/** How a borehole is placed: its `position`, else inferred as the backend does. */
export function boreholePosition(borehole: IBorehole): BoreholePosition {
	if (borehole.position === 'project' || borehole.position === 'wgs84' || borehole.position === 'btm') {
		return borehole.position;
	}
	if (typeof borehole.lat === 'number' && typeof borehole.lon === 'number') {
		return 'wgs84';
	}
	return typeof borehole.easting === 'number' && typeof borehole.northing === 'number' ? 'btm' : 'project';
}

/** How the SPT values and the allowable pressure are worked out (`design.practice`). */
export type SoilPractice = 'textbook' | 'bdConsultant';

/** The liquefaction triggering procedure (`design.liquefactionMethod`). */
export type LiquefactionMethod = 'idrissBoulanger2014' | 'bnbc2020';

export interface ISoilDesign {
	hammerEnergy?: number;
	factorOfSafety?: number;
	allowableSettlement?: number;
	practice?: SoilPractice;
	liquefactionMethod?: LiquefactionMethod;
	liquefaction?: { magnitude?: number; pga?: number | null;[key: string]: unknown };
	[key: string]: unknown;
}

/** One option of a design choice, with what it does in one line (its hover). */
export interface IChoiceOption {
	readonly value: string;
	readonly label: string;
	readonly title: string;
}

/** A design option picked from a list (a select in the properties panel). */
export interface IChoiceSpec {
	readonly key: 'practice' | 'liquefactionMethod';
	readonly label: string;
	/** What the choice decides, in one line. */
	readonly title: string;
	readonly defaultValue: string;
	readonly options: readonly IChoiceOption[];
}

export const PRACTICE_CHOICE: IChoiceSpec = {
	key: 'practice',
	label: localize('soil.f.practice', "Practice"),
	title: localize('soil.f.practiceTitle', "How the SPT N is corrected and which N the settlement limit on the allowable pressure uses; the shear capacity is the same for both."),
	defaultValue: 'textbook',
	options: [
		{ value: 'textbook', label: localize('soil.practice.textbook', "Textbook"), title: localize('soil.practice.textbookTitle', "Textbook: cumulative σ′v, CN of Liao & Whitman (≤ 1.7), the N60 factors of Youd et al. 2001; the settlement-limited pressure (Meyerhof-Bowles) from N60.") },
		{ value: 'bdConsultant', label: localize('soil.practice.bdConsultant', "Bangladesh consultant practice"), title: localize('soil.practice.bdConsultantTitle', "Bangladesh consultant practice, as in common Dhaka soil reports: σ′v per SPT row, CN of Peck, Hanson & Thornburn, the dilatancy correction N′; the settlement-limited pressure (Meyerhof-Bowles) from N′.") },
	],
};

export const LIQUEFACTION_METHOD_CHOICE: IChoiceSpec = {
	key: 'liquefactionMethod',
	label: localize('soil.f.liquefactionMethod', "Liquefaction method"),
	title: localize('soil.f.liquefactionMethodTitle', "The procedure of the liquefaction screening from the SPT."),
	defaultValue: 'idrissBoulanger2014',
	options: [
		{ value: 'idrissBoulanger2014', label: localize('soil.lqMethod.ib2014', "Idriss & Boulanger 2014"), title: localize('soil.lqMethod.ib2014Title', "Idriss & Boulanger 2014: CSR with their depth factor rd, CRR from (N1)60cs with the magnitude and overburden factors.") },
		{ value: 'bnbc2020', label: localize('soil.lqMethod.bnbc2020', "BNBC 2020 Sec 3.9.5"), title: localize('soil.lqMethod.bnbc2020Title', "BNBC 2020 Part 6 Sec 3.9.5: FL = CRR/CSR (Eq 6.3.6), the code's CSR (Eq 6.3.8) with rd = 1 − 0.015z (Eq 6.3.7b), CRR of Youd et al. 2001 from the SPT.") },
	],
};

/** The design options picked from a list, in the order of the properties panel. */
export const DESIGN_CHOICES: readonly IChoiceSpec[] = [PRACTICE_CHOICE, LIQUEFACTION_METHOD_CHOICE];

/** The label of a choice's value; an unknown value as it is. */
export function choiceLabel(spec: IChoiceSpec, value: unknown): string | undefined {
	if (typeof value !== 'string' || !value) {
		return undefined;
	}
	return spec.options.find(o => o.value === value)?.label ?? value;
}

/** The hover of a choice's row: what it decides, then one line per option. */
export function choiceTitle(spec: IChoiceSpec): string {
	return [spec.title, ...spec.options.map(o => o.title)].join('\n');
}

export interface ISoilReport {
	schema: string;
	report: { title?: string; consultant?: string; reportNumber?: string; date?: string;[key: string]: unknown };
	groundLevel: number;
	site?: ISoilSite;
	boreholes: IBorehole[];
	design: ISoilDesign;
	[key: string]: unknown;
}

export const DESIGN_DEFAULTS = { hammerEnergy: 60, factorOfSafety: 3, allowableSettlement: 25, magnitude: 7.5 } as const;

// ───────────────────────────── backend requests and results ─────────────────────────────

export interface ISoilComputeRequest {
	readonly soilText: string;
	/** `02 Project Settings/settings.json` (seismic zone and site class for the PGA). */
	readonly settingsText?: string;
}

export interface ISoilImportRequest {
	/** File system path of the CSV or Excel file. */
	readonly path: string;
	readonly soilText: string;
}

/** The report with the file's boreholes merged in, or why it could not be read. */
export interface ISoilImportResult {
	readonly text?: string;
	readonly problems?: readonly string[];
}

export interface ISoilTemplateRequest {
	/** File system path to write the CSV or Excel template to. */
	readonly path: string;
}

export interface ISoilTemplateResult {
	readonly path?: string;
	readonly problems?: readonly string[];
}
/*
 * The site map's backend (`saengine.gis.site`): `soil_location()`, `gis_export()`, `gis_import()`
 * and `qgis_program()` answer in these shapes (null where a value is unknown).
 */

/** `saengine.soil.location`: where the site, the boreholes and the building are on the earth. */
export interface ISoilLocationRequest {
	readonly soilText: string;
	/** `06 BIM/bim.json`, for the building's outline. */
	readonly bimText?: string;
	/** `02 Project Settings/project-settings.json`, for the BNBC location in use. */
	readonly settingsText?: string;
}

export interface ILatLon {
	readonly lat: number;
	readonly lon: number;
}

/** Bangladesh Transverse Mercator (EPSG:9678) [m]. */
export interface IBtm {
	readonly easting: number;
	readonly northing: number;
}

/** How a borehole's position is given (`Borehole.position`); inferred from its fields when absent. */
export type BoreholePosition = 'project' | 'wgs84' | 'btm';

/** The BNBC values of the nearest listed towns (BNBC 2020 Table 6.2.15 Z, Table 6.2.8 V). */
export interface ISoilLocationSuggestion {
	readonly town: string;
	readonly distanceKm: number;
	readonly zone?: number | null;
	readonly Z?: number | null;
	readonly windSpeed?: number | null;
	/** The town the wind speed is from, when another town lists it nearer. */
	readonly windTown?: string | null;
	readonly windDistanceKm?: number | null;
	/** The town's id in the project settings' locations, when it is one of them. */
	readonly settingsLocation?: string | null;
	readonly source?: string;
	readonly note?: string;
	/** What the project settings use now. */
	readonly current?: { readonly location?: string; readonly zone?: number | null; readonly Z?: number | null; readonly windSpeed?: number | null } | null;
	/** Whether the settings' values differ from the suggestion. */
	readonly differs?: boolean;
}

export interface ISoilLocationResult {
	readonly site?: (ILatLon & {
		readonly x?: number;
		readonly y?: number;
		readonly rotation?: number;
		readonly address?: string | null;
		/** Whether the project grid is placed (the site has its own lat/lon). */
		readonly georeferenced?: boolean;
		readonly btm?: IBtm | null;
	}) | null;
	/** Every borehole with both positions where known. */
	readonly boreholes?: readonly {
		readonly id: string;
		readonly position?: BoreholePosition;
		readonly x?: number | null;
		readonly y?: number | null;
		readonly lat?: number | null;
		readonly lon?: number | null;
		readonly btm?: IBtm | null;
	}[];
	/** The building's outline as a closed ring of [lon, lat]. */
	readonly outline?: readonly (readonly number[])[] | null;
	/** The same in project coordinates [mm], an open ring of [x, y]. */
	readonly outlineProject?: readonly (readonly number[])[] | null;
	readonly outlineSource?: string;
	/** The plot as `saengine.gis.plot.describe` measures it; null without one. */
	readonly plot?: ISitePlot | null;
	readonly suggestion?: ISoilLocationSuggestion | null;
	readonly problems?: readonly string[];
}

/** One side of the plot: corner `index` to the next. */
export interface IPlotSide {
	readonly index: number;
	/** [mm] */
	readonly length: number;
	/** Of the side, from its corner to the next, clockwise from true north [°]. */
	readonly bearing: number;
	/** The direction the side faces (outwards) [°], and as a compass point ("SW"). */
	readonly faces: number;
	readonly facing: string;
	readonly kind: 'front' | 'rear' | 'side' | null;
	/** [mm] */
	readonly setback: number;
}

/** The grid frame of the plot: turned along the road side, its origin at the envelope's lower-left corner. */
export interface IPlotFit {
	/** How far the grid turns clockwise [°], and the grid bearing it then has. */
	readonly turn: number;
	readonly rotation: number;
	/** The largest rectangle in the envelope, in that frame [mm]. */
	readonly width: number;
	readonly depth: number;
	/** The plot and the envelope in that frame [mm]. */
	readonly plot: readonly (readonly number[])[];
	readonly envelope: readonly (readonly number[])[];
}

export interface ISitePlot {
	/** `wgs84`: the site boundary is the plot; `project`: its corners in the project grid. */
	readonly given?: 'wgs84' | 'project';
	/** Corners in project mm (open ring); null when the site has no position for a lat/lon boundary. */
	readonly ring?: readonly (readonly number[])[] | null;
	/** Closed [lon, lat] ring; null without a site point. */
	readonly lonlat?: readonly (readonly number[])[] | null;
	/** [m²], and in katha (720 sq ft) and decimal (435.6 sq ft). */
	readonly area?: number;
	readonly katha?: number;
	readonly decimal?: number;
	/** [mm] */
	readonly perimeter?: number;
	readonly sides?: readonly IPlotSide[];
	readonly road?: number | null;
	/** The buildable envelope in project mm (open ring), and as a closed [lon, lat] ring. */
	readonly envelope?: readonly (readonly number[])[] | null;
	readonly envelopeLonlat?: readonly (readonly number[])[] | null;
	/** [m²] */
	readonly envelopeArea?: number | null;
	readonly fit?: IPlotFit | null;
	readonly problems?: readonly string[];
}

/** `saengine.soil.plotCheck`: the floor plan against the soil report's plot. */
export interface IPlotCheckRequest {
	readonly soilText: string;
	readonly floorPlanText: string;
	readonly objectsText?: string;
}

export interface IPlotWarning {
	/** The story whose plan shows the member. */
	readonly story: string;
	readonly group: 'column' | 'wall' | 'beam' | 'slab';
	readonly id: string;
	/** `outside`: outside the plot; `setback`: inside the setback of `side`. */
	readonly kind: 'outside' | 'setback';
	/** How far [mm]. */
	readonly amount: number;
	readonly side: 'front' | 'rear' | 'side' | null;
	readonly message: string;
}

export interface IPlotCheckResult {
	/** The plot and the envelope in project mm (open rings), null without them. */
	readonly plot?: readonly (readonly number[])[] | null;
	readonly envelope?: readonly (readonly number[])[] | null;
	readonly warnings?: readonly IPlotWarning[];
	readonly problems?: readonly string[];
}

export type GisFormat = 'geojson' | 'gpkg';

/** `saengine.soil.gisExport`: the site, the boreholes and the outline for QGIS. */
export interface ISoilGisExportRequest {
	/** File system path of the project folder. */
	readonly projectRoot: string;
	readonly format: GisFormat;
	readonly outPath: string;
}

export interface ISoilGisExportResult {
	readonly path?: string;
	readonly counts?: { readonly [layer: string]: number };
	readonly problems?: readonly string[];
}

/** `saengine.soil.gisImport`: boreholes (points) and the site boundary from a GeoJSON or GeoPackage file. */
export interface ISoilGisImportRequest {
	readonly path: string;
	readonly soilText: string;
}

export interface ISoilGisImportResult {
	/** The report with the file's points merged in. */
	readonly soilText?: string;
	readonly added?: number | readonly string[];
	readonly updated?: number | readonly string[];
	readonly boundary?: boolean | number;
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
}

/** `saengine.soil.qgisProgram`: the QGIS launcher found on this computer (a path), if any. */
export type QgisProgramResult = string | { readonly path?: string | null; readonly version?: string | null } | null | undefined;

export interface IOpenInQgisRequest {
	readonly path: string;
}

export interface IOpenInQgisResult {
	readonly ok?: boolean;
	readonly problems?: readonly string[];
}

/*
 * The results as the editor shows them. The backend's own shape (what `soil_report()` in
 * `python/src/saengine/soil/report.py` returns, `IBackendSoilReport` below) is read into these by
 * `readSoilResults`, the one place that knows the backend's field names.
 */

/** A site class with the average it was found from (BNBC 2020 Table 6.2.13, top 30 m). */
export interface ISiteClassResult {
	readonly class: string;
	/** The borehole that governs the project's class. */
	readonly borehole?: string;
	/** Harmonic mean SPT N over the depth considered (N̄). */
	readonly nBar?: number | null;
	/** Harmonic mean undrained shear strength of the cohesive layers (s̄u) [kPa]. */
	readonly suBar?: number | null;
	/** Depth the average is taken over [mm]. */
	readonly depth?: number;
	readonly note?: string;
	/** The class by N̄ and by s̄u of Table 6.2.13 (the softer governs). */
	readonly byN?: string;
	readonly bySu?: string;
	/** The borehole (or, for the project, every borehole of its class) ends above 30 m: the class rests on its last N carried down. */
	readonly provisional?: boolean;
}

/** The site class as the results show it: "SD", or "SD (provisional)" when no borehole of it reaches 30 m. */
export function siteClassLabel(site: Pick<ISiteClassResult, 'class' | 'provisional'>): string {
	return site.provisional ? localize('soil.classProvisional', "{0} (provisional)", site.class) : site.class;
}

/**
 * A secant ks below this is very soft ground [kN/m³] (Bowles, Foundation Analysis and Design,
 * 5th ed., Table 9-1: about 4800-16000 for loose sand, 12000-24000 for clay with qa up to 200 kPa;
 * a value this low is a raft on very soft clay or fill): the subgrade springs of the analysis
 * then carry the footings on settlements of tens of mm, so it is flagged before it reaches FEM.
 */
export const KS_LOW = 2000;

/** The depth BNBC 2020 Table 6.2.13 classifies the site by [mm]. */
export const SITE_CLASS_DEPTH = 30000;

/** One footing size of the allowable bearing table. */
export interface IBearingCell {
	/** Footing width [mm]. */
	readonly B: number;
	/** Founding depth [mm]. */
	readonly Df: number;
	/** Allowable net bearing pressure [kPa]: the lower of the two below; null when it cannot be found. */
	readonly qa: number | null;
	/** From the bearing capacity (shear) / factor of safety [kPa]. */
	readonly qBearing?: number | null;
	/** That keeps the settlement within the allowable [kPa]. */
	readonly qSettlement?: number | null;
	readonly governs?: 'shear' | 'settlement' | null;
	/** The borehole the value is from (the lowest of all, in the project table). */
	readonly borehole?: string;
	/** In the project table: the boreholes that give no value for this footing (left out of the lowest). */
	readonly missing?: readonly string[];
}

export interface IBearingResult {
	readonly method?: string;
	readonly cells: readonly IBearingCell[];
	/** In the project table: the boreholes left out of it (`excludeFromSite`). */
	readonly excluded?: readonly string[];
	/** The reference footing (the subgrade footing of the design options) and its value. */
	readonly governing?: IBearingCell;
	readonly notes?: readonly string[];
}

export interface ISptResult {
	readonly depth: number;
	readonly N: number;
	readonly N60?: number;
	readonly N160?: number;
	readonly N160cs?: number;
}

export interface ILiquefactionPoint {
	readonly depth: number;
	readonly CSR?: number;
	readonly CRR?: number;
	readonly FS?: number | null;
	readonly liquefiable?: boolean;
	/** Why the point is not checked (above the water table, clay-like, deeper than 20 m). */
	readonly note?: string;
}

export interface ILiquefactionResult {
	readonly method?: string;
	readonly points: readonly ILiquefactionPoint[];
	/** Liquefaction potential index (Iwasaki et al. 1978). */
	readonly LPI?: number | null;
	/** The backend's risk class of the LPI ("very low" ... "very high"). */
	readonly category?: string | null;
	readonly liquefiableLayers?: readonly { readonly top: number; readonly bottom: number; readonly soilType?: string }[];
	readonly note?: string;
	readonly notes?: readonly string[];
}

export interface IPileLayerResult {
	readonly top: number;
	readonly bottom: number;
	readonly soilType?: string;
	/** Unit skin friction [kPa]. */
	readonly fs?: number | null;
	/** Unit end bearing [kPa]. */
	readonly qb?: number | null;
	readonly method?: string | null;
	readonly note?: string | null;
	/** The share of the layer the liquefaction screening finds liquefiable (0 to 1). */
	readonly liquefiable?: number;
	/** Skin friction under the earthquake: none over the liquefiable share [kPa]. */
	readonly fsSeismic?: number | null;
}

export interface IBoreholeResult {
	readonly id: string;
	readonly siteClass?: ISiteClassResult;
	readonly spt?: readonly ISptResult[];
	readonly liquefaction?: ILiquefactionResult;
	/** Modulus of subgrade reaction [kN/m³]. */
	readonly ks?: number | null;
	readonly ksMethod?: string;
	readonly ksNote?: string;
	/** Bowles' 40·FS·qa for comparison [kN/m³]. */
	readonly ksBowles?: number;
	readonly piles?: readonly IPileLayerResult[];
	readonly bearing?: IBearingResult;
	/** Settlement of the reference footing under its allowable pressure. */
	readonly settlement?: ISettlementResult;
	readonly notes?: readonly string[];
}

/** A footing's settlement [mm] and, when the backend gives it, the limit it is held to. */
export interface ISettlementResult {
	/** Footing width and founding depth [mm], net pressure [kPa]. */
	readonly B?: number;
	readonly Df?: number;
	readonly q?: number;
	readonly immediate?: number;
	readonly consolidation?: number;
	readonly total: number;
	/** BNBC 2020 Table 6.3.8's permissible total settlement [mm], and which row of it. */
	readonly permissible?: number;
	readonly permissibleSource?: string;
}

/** A site class the boreholes may fall in beyond SA to SE (BNBC 2020 Table 6.2.13): a warning, not an error. */
export interface ISiteClassFlag {
	readonly class: string;
	readonly note: string;
	readonly boreholes?: readonly string[];
}

/** What the editor shows of `saengine.soil.compute`'s answer. */
export interface ISoilResults {
	readonly siteClass?: ISiteClassResult;
	readonly boreholes?: readonly IBoreholeResult[];
	/** The lowest qa of all boreholes for each footing size. */
	readonly bearing?: IBearingResult;
	/** Peak ground acceleration used for liquefaction [g], and where it came from. */
	readonly pga?: number;
	readonly pgaSource?: string;
	/** The practice and the liquefaction method the backend used (its ids), when it says. */
	readonly practice?: string;
	readonly liquefactionMethod?: string;
	/** How the SPT values were corrected (the practice's method). */
	readonly sptMethod?: string;
	/** S1 / S2 / SE warnings of the site class, from the backend. */
	readonly siteClassFlags?: readonly ISiteClassFlag[];
	/** BNBC 2020 Table 6.3.8's permissible settlement for the project [mm], when the backend gives one. */
	readonly permissibleSettlement?: number;
	readonly permissibleSettlementSource?: string;
	readonly problems?: readonly string[];
	readonly notes?: readonly string[];
	/** The boreholes left out of the results (a mistake in them, or the computation failed). */
	readonly skipped?: readonly string[];
	/** What a failed computation printed (tracebacks), behind "Show details". */
	readonly details?: readonly string[];
}

// ───────────────────────────── the backend's results ─────────────────────────────

type Maybe<T> = T | null | undefined;

/** A site class as `site_class.site_class()` returns it. */
export interface IBackendSiteClass {
	readonly class?: Maybe<string>;
	/** Harmonic mean field N over the top 30 m. */
	readonly N?: Maybe<number>;
	/** Harmonic mean su of the cohesive layers [kPa]. */
	readonly su?: Maybe<number>;
	readonly depth?: Maybe<number>;
	readonly note?: Maybe<string>;
	/** The class by N̄ and by s̄u alone. */
	readonly byN?: Maybe<string>;
	readonly bySu?: Maybe<string>;
	/** The project's: the governing borehole's id. */
	readonly governing?: Maybe<string>;
	/** Shallower than 30 m: the class rests on the last N carried down. */
	readonly provisional?: Maybe<boolean>;
	/** Special classes the profile may be (S1, S2): objects or "S2: why" strings. */
	readonly flags?: readonly (IBackendSiteClassFlag | string)[];
}

/** A flag of the site class as the backend gives it. */
export interface IBackendSiteClassFlag {
	readonly class?: Maybe<string>;
	readonly code?: Maybe<string>;
	readonly note?: Maybe<string>;
	readonly message?: Maybe<string>;
	readonly reason?: Maybe<string>;
	readonly boreholes?: readonly string[];
}

/** A permissible settlement: the value [mm], or the value with the row of Table 6.3.8 it is from. */
type BackendPermissible = Maybe<number | { readonly value?: Maybe<number>; readonly mm?: Maybe<number>; readonly source?: Maybe<string>; readonly note?: Maybe<string> }>;

/** The settlement of the reference footing as `settlement.rounded()` gives it. */
export interface IBackendSettlement {
	readonly B?: Maybe<number>;
	readonly Df?: Maybe<number>;
	readonly q?: Maybe<number>;
	readonly immediate?: Maybe<number>;
	readonly consolidation?: Maybe<number>;
	readonly total?: Maybe<number>;
	readonly permissible?: BackendPermissible;
	readonly permissibleSource?: Maybe<string>;
}

/** What `soil_report()` (python/src/saengine/soil/report.py) returns. */
export interface IBackendSoilReport {
	readonly boreholes?: readonly {
		readonly id: string;
		readonly siteClass?: IBackendSiteClass;
		readonly profile?: readonly { readonly depth: number; readonly N: number; readonly N60?: Maybe<number>; readonly N160?: Maybe<number> }[];
		readonly liquefaction?: {
			readonly points?: readonly { readonly depth: number; readonly N60?: Maybe<number>; readonly screened?: boolean; readonly reason?: Maybe<string>; readonly csr?: Maybe<number>; readonly crr?: Maybe<number>; readonly N160cs?: Maybe<number>; readonly fs?: Maybe<number>; readonly liquefiable?: boolean }[];
			readonly layers?: readonly { readonly top: number; readonly bottom: number; readonly soilType?: string }[];
			readonly lpi?: Maybe<number>;
			readonly category?: Maybe<string>;
			readonly note?: Maybe<string>;
			readonly notes?: readonly string[];
		};
		readonly bearing?: {
			readonly table?: readonly { readonly B: number; readonly Df: number; readonly qa_shear?: Maybe<number>; readonly qa_settlement?: Maybe<number>; readonly qa?: Maybe<number>; readonly governs?: Maybe<string> }[];
			readonly method?: Maybe<string>;
			readonly notes?: readonly string[];
		};
		readonly ks?: Maybe<number>;
		readonly ksDetail?: { readonly B?: Maybe<number>; readonly Df?: Maybe<number>; readonly method?: Maybe<string>; readonly note?: Maybe<string>; readonly bowles?: Maybe<number> };
		readonly pile?: readonly { readonly top: number; readonly bottom: number; readonly soilType?: Maybe<string>; readonly fs?: Maybe<number>; readonly qb?: Maybe<number>; readonly method?: Maybe<string>; readonly note?: Maybe<string>; readonly liquefiable?: Maybe<number>; readonly fsSeismic?: Maybe<number> }[];
		readonly settlement?: Maybe<IBackendSettlement>;
		readonly permissibleSettlement?: BackendPermissible;
		readonly notes?: readonly string[];
	}[];
	readonly siteClass?: IBackendSiteClass;
	/** Peak ground acceleration for the liquefaction screening [g], and how it was found. */
	readonly amax?: Maybe<number>;
	readonly amaxSource?: Maybe<string>;
	readonly amaxNote?: Maybe<string>;
	/** The options the results were computed with (`practice`, `liquefactionMethod`), at the top or under `design`. */
	readonly practice?: Maybe<string>;
	readonly liquefactionMethod?: Maybe<string>;
	readonly design?: { readonly practice?: Maybe<string>; readonly liquefactionMethod?: Maybe<string> };
	readonly permissibleSettlement?: BackendPermissible;
	readonly methods?: { readonly spt?: Maybe<string>; readonly bearing?: Maybe<string>; readonly liquefaction?: Maybe<string>; readonly siteClass?: Maybe<string>; readonly settlement?: Maybe<string> };
	readonly problems?: readonly string[];
	readonly notes?: readonly string[];
	/** Per borehole: why one was left out (the report itself was read). */
	readonly warnings?: readonly string[];
	readonly skipped?: readonly string[];
	readonly details?: readonly string[];
}

/**
 * A backend error for the engineer: one line (a Python traceback's last line, the exception),
 * and the whole text as the details for a bug report.
 */
export function splitError(message: string): { readonly summary: string; readonly details?: string } {
	const lines = message.split(/\r?\n/).map(l => l.trimEnd()).filter(Boolean);
	if (lines.length <= 1) {
		return { summary: message.trim() };
	}
	const traceback = lines.findIndex(l => l.includes('Traceback (most recent call last)'));
	const summary = traceback >= 0 ? lines[lines.length - 1].trim() : lines[0].trim();
	return { summary, details: message.trim() };
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function str(value: unknown): string | undefined {
	return typeof value === 'string' && value ? value : undefined;
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((s): s is string => typeof s === 'string' && !!s) : [];
}

function list<T>(value: readonly T[] | undefined): readonly T[] {
	return Array.isArray(value) ? value : [];
}

/** The reference footing of the bearing summary when the backend does not give one [mm]. */
const REFERENCE_FOOTING = { B: 2000, Df: 1500 };

/**
 * Reads what `saengine.soil.compute` returned (the backend's `soil_report()`) into what the
 * editor shows. Missing or malformed parts are left out, never guessed; undefined when the
 * answer is not an object.
 */
/**
 * The backend's results as the editor shows them. `excluded`: the boreholes the engineer left out
 * of the project's tables (`excludeFromSite`), e.g. one far from the building.
 */
export function readSoilResults(raw: unknown, excluded: ReadonlySet<string> = new Set()): ISoilResults | undefined {
	if (!isRecord(raw)) {
		return undefined;
	}
	const backend = raw as IBackendSoilReport;
	const liquefactionMethod = str(backend.methods?.liquefaction);
	const bearingMethod = str(backend.methods?.bearing);
	let reference: { B: number; Df: number } | undefined;
	const boreholes: IBoreholeResult[] = list(backend.boreholes).filter(isRecord).map(b => {
		const site = isRecord(b.siteClass) ? b.siteClass : undefined;
		const liquefaction = isRecord(b.liquefaction) ? b.liquefaction : undefined;
		const points = list(liquefaction?.points).filter(isRecord);
		const cs = new Map(points.map(p => [p.depth, num(p.N160cs)]));
		const bearing = isRecord(b.bearing) ? b.bearing : undefined;
		const id = String(b.id ?? '');
		const ksB = num(b.ksDetail?.B);
		const ksDf = num(b.ksDetail?.Df);
		if (!reference && ksB !== undefined && ksDf !== undefined) {
			reference = { B: ksB, Df: ksDf };
		}
		return {
			id,
			siteClass: site && str(site.class) ? { class: str(site.class)!, nBar: num(site.N) ?? null, suBar: num(site.su) ?? null, depth: num(site.depth), note: str(site.note), byN: str(site.byN), bySu: str(site.bySu), provisional: site.provisional === true } : undefined,
			spt: list(b.profile).filter(isRecord).map(s => ({ depth: s.depth, N: s.N, N60: num(s.N60), N160: num(s.N160), N160cs: cs.get(s.depth) })),
			liquefaction: liquefaction ? {
				method: liquefactionMethod,
				points: points.map(p => ({ depth: p.depth, CSR: num(p.csr), CRR: num(p.crr), FS: num(p.fs) ?? null, liquefiable: p.liquefiable === true, note: str(p.reason) })),
				LPI: num(liquefaction.lpi) ?? null,
				category: str(liquefaction.category) ?? null,
				liquefiableLayers: list(liquefaction.layers).filter(isRecord).map(l => ({ top: l.top, bottom: l.bottom, soilType: str(l.soilType) })),
				note: str(liquefaction.note),
				notes: strings(liquefaction.notes),
			} : undefined,
			ks: num(b.ks) ?? null,
			ksMethod: str(b.ksDetail?.method),
			ksNote: str(b.ksDetail?.note),
			ksBowles: num(b.ksDetail?.bowles),
			piles: list(b.pile).filter(isRecord).map(p => ({ top: p.top, bottom: p.bottom, soilType: str(p.soilType), fs: num(p.fs) ?? null, qb: num(p.qb) ?? null, method: str(p.method) ?? null, note: str(p.note) ?? null, liquefiable: num(p.liquefiable), fsSeismic: num(p.fsSeismic) ?? null })),
			bearing: bearing ? {
				method: str(bearing.method) ?? bearingMethod,
				cells: list(bearing.table).filter(isRecord).map(c => ({
					B: c.B, Df: c.Df, qa: num(c.qa) ?? null, qBearing: num(c.qa_shear) ?? null, qSettlement: num(c.qa_settlement) ?? null,
					governs: c.governs === 'shear' || c.governs === 'settlement' ? c.governs : null, borehole: id,
				})),
				notes: strings(bearing.notes),
			} : undefined,
			settlement: readSettlement(b.settlement, b.permissibleSettlement),
			notes: strings(b.notes),
		};
	});
	for (const borehole of boreholes) {
		if (borehole.bearing) {
			(borehole as { bearing: IBearingResult }).bearing = { ...borehole.bearing, governing: referenceCell(borehole.bearing.cells, reference) };
		}
	}

	// The project's table: for each footing size the lowest qa of the boreholes that give one. A
	// borehole without a value there (no strength under that base) is named under the table, not
	// allowed to blank the size for the whole site.
	const envelope = new Map<string, IBearingCell>();
	const missing = new Map<string, string[]>();
	for (const borehole of boreholes) {
		if (excluded.has(borehole.id)) {
			continue;
		}
		for (const cell of borehole.bearing?.cells ?? []) {
			const key = `${cell.B}|${cell.Df}`;
			if (cell.qa === null) {
				missing.set(key, [...missing.get(key) ?? [], borehole.id]);
			}
			const current = envelope.get(key);
			if (!current || cell.qa !== null && (current.qa === null || cell.qa < current.qa)) {
				envelope.set(key, cell);
			}
		}
	}
	const cells = [...envelope.entries()].map(([key, cell]) => missing.has(key) ? { ...cell, missing: missing.get(key) } : cell);
	const left = boreholes.filter(b => excluded.has(b.id) && b.bearing?.cells.length).map(b => b.id);
	const project = isRecord(backend.siteClass) ? backend.siteClass : undefined;
	const governingId = str(project?.governing);
	const governingSite = boreholes.find(b => b.id === governingId)?.siteClass;
	const amaxNote = str(backend.amaxSource) ?? str(backend.amaxNote) ?? boreholes.map(b => b.liquefaction?.notes?.find(n => n.startsWith('amax'))).find(Boolean);
	const permissible = readPermissible(backend.permissibleSettlement);
	return {
		siteClass: project && str(project.class) ? {
			class: str(project.class)!,
			borehole: governingId,
			nBar: governingSite?.nBar ?? null,
			suBar: governingSite?.suBar ?? null,
			depth: governingSite?.depth,
			note: str(project.note),
			provisional: project.provisional === true,
		} : undefined,
		boreholes,
		bearing: cells.length ? { method: bearingMethod, cells, governing: referenceCell(cells, reference), excluded: left.length ? left : undefined } : undefined,
		pga: num(backend.amax),
		pgaSource: amaxNote,
		practice: str(backend.practice) ?? str(isRecord(backend.design) ? backend.design.practice : undefined),
		liquefactionMethod: str(backend.liquefactionMethod) ?? str(isRecord(backend.design) ? backend.design.liquefactionMethod : undefined),
		sptMethod: str(backend.methods?.spt),
		siteClassFlags: readFlags(backend),
		permissibleSettlement: permissible?.value,
		permissibleSettlementSource: permissible?.source,
		problems: [...strings(backend.problems), ...strings(backend.warnings)],
		notes: strings(backend.notes),
		skipped: strings(backend.skipped),
		details: strings(backend.details),
	};
}

function readPermissible(raw: BackendPermissible): { value: number; source?: string } | undefined {
	if (typeof raw === 'number') {
		return Number.isFinite(raw) ? { value: raw } : undefined;
	}
	if (!isRecord(raw)) {
		return undefined;
	}
	const value = num(raw.value) ?? num(raw.mm);
	return value === undefined ? undefined : { value, source: str(raw.source) ?? str(raw.note) };
}

function readSettlement(value: Maybe<IBackendSettlement>, permissibleRaw: BackendPermissible): ISettlementResult | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const raw: IBackendSettlement = value;
	const total = num(raw.total);
	if (total === undefined) {
		return undefined;
	}
	const permissible = readPermissible(raw.permissible) ?? readPermissible(permissibleRaw);
	return {
		B: num(raw.B), Df: num(raw.Df), q: num(raw.q), immediate: num(raw.immediate), consolidation: num(raw.consolidation), total,
		permissible: permissible?.value,
		permissibleSource: str(raw.permissibleSource) ?? permissible?.source,
	};
}

/**
 * The site class flags (S1, S2, SE) with the boreholes of each. A borehole's own flags win: their
 * notes give that borehole's depths and layers, so boreholes share a row only when their notes are
 * the same. The project's merged flags (one note for all boreholes) are used only for a class that
 * no borehole reports.
 */
function readFlags(backend: IBackendSoilReport): ISiteClassFlag[] {
	const flags = new Map<string, { class: string; note: string; boreholes: Set<string> }>();
	const add = (raw: IBackendSiteClassFlag | string, borehole: string | undefined, skip?: ReadonlySet<string>) => {
		let cls: string | undefined;
		let note: string | undefined;
		let boreholes: readonly string[] = [];
		if (typeof raw === 'string') {
			const match = /^(?<cls>S[12])\b[:\s-]*(?<note>.*)$/s.exec(raw.trim());
			cls = match?.groups?.cls;
			note = match?.groups?.note || raw;
		} else if (isRecord(raw)) {
			cls = str(raw.class) ?? str(raw.code);
			note = str(raw.note) ?? str(raw.message) ?? str(raw.reason);
			boreholes = strings(raw.boreholes);
		}
		if (!cls || skip?.has(cls)) {
			return;
		}
		const key = `${cls}\u0000${note ?? ''}`;
		const flag = flags.get(key) ?? { class: cls, note: note ?? '', boreholes: new Set<string>() };
		for (const id of borehole ? [borehole, ...boreholes] : boreholes) {
			flag.boreholes.add(id);
		}
		flags.set(key, flag);
	};
	const flagsOf = (site: IBackendSiteClass | undefined) => list(isRecord(site) ? site.flags as IBackendSiteClass['flags'] : undefined);
	for (const b of list(backend.boreholes).filter(isRecord)) {
		for (const raw of flagsOf(b.siteClass)) {
			add(raw, String(b.id ?? ''));
		}
	}
	const fromBoreholes = new Set([...flags.values()].map(f => f.class));
	for (const raw of flagsOf(backend.siteClass)) {
		add(raw, undefined, fromBoreholes);
	}
	return [...flags.values()].sort((a, b) => a.class.localeCompare(b.class)).map(f => ({ class: f.class, note: f.note, boreholes: f.boreholes.size ? [...f.boreholes] : undefined }));
}

/** The reference footing's cell (the subgrade footing, else B 2 m Df 1.5 m), if it has a value. */
function referenceCell(cells: readonly IBearingCell[], reference: { B: number; Df: number } | undefined): IBearingCell | undefined {
	const at = (r: { B: number; Df: number }) => cells.find(c => c.B === r.B && c.Df === r.Df && c.qa !== null);
	return (reference && at(reference)) ?? at(REFERENCE_FOOTING);
}

/** Whether a borehole's liquefaction screening found liquefiable layers or points. */
export function hasLiquefiable(result: IBoreholeResult | undefined): boolean {
	const liquefaction = result?.liquefaction;
	return !!liquefaction && ((liquefaction.liquefiableLayers?.length ?? 0) > 0 || liquefaction.points.some(p => p.liquefiable));
}

/** What a special site class means (BNBC 2020 Table 6.2.13 and Sec 2.5.3.1). */
export function siteFlagMeaning(cls: string): string | undefined {
	switch (cls) {
		case 'S1': return localize('soil.flag.s1', "S1 possible: a layer at least 10 m thick of soft clays or silts with PI > 40 and a high water content (BNBC 2020 Table 6.2.13). Sec 2.5.3.1 asks for a site-specific study of the ground motion.");
		case 'S2': return localize('soil.flag.s2', "S2 possible: liquefiable soils (BNBC 2020 Table 6.2.13). Sec 2.5.3.1 asks for a site-specific study of the ground motion and of the possibility of soil failure.");
		default: return undefined;
	}
}

/**
 * The site class warnings to show: the backend's flags and, when it gives no S2 flag, S2 from
 * the liquefaction screening's liquefiable layers (Table 6.2.13: "deposits of liquefiable soils").
 */
export function siteFlagsOf(results: ISoilResults): ISiteClassFlag[] {
	const flags = [...results.siteClassFlags ?? []];
	if (!flags.some(f => f.class === 'S2')) {
		const liquefiable = (results.boreholes ?? []).filter(hasLiquefiable).map(b => b.id);
		if (liquefiable.length) {
			flags.push({ class: 'S2', note: '', boreholes: liquefiable });
		}
	}
	return flags.sort((a, b) => a.class.localeCompare(b.class));
}

/** A line of the basis of the results: what was used, and where it came from. */
export interface IResultsBasisRow {
	readonly label: string;
	readonly value: string;
	readonly detail?: string;
}

/**
 * The practice, the liquefaction method and the amax the results were computed with. The
 * backend's answer when it states them, else the report's design option (marked as such).
 */
export function resultsBasis(design: ISoilDesign, results: ISoilResults): IResultsBasisRow[] {
	const asSet = localize('soil.basis.asSet', "as set in the design options");
	const choice = (spec: IChoiceSpec, used: string | undefined, detail?: string): IResultsBasisRow => ({
		label: spec.label,
		value: choiceLabel(spec, used ?? design[spec.key] ?? spec.defaultValue) ?? '',
		detail: used ? detail : asSet,
	});
	return [
		choice(PRACTICE_CHOICE, results.practice, results.sptMethod),
		choice(LIQUEFACTION_METHOD_CHOICE, results.liquefactionMethod),
		{
			label: 'amax',
			value: typeof results.pga === 'number' ? localize('soil.basis.amax', "{0} g", formatNumber(results.pga, 3)) : localize('soil.basis.noAmax', "none"),
			detail: results.pgaSource,
		},
	];
}

// ───────────────────────────── reading ─────────────────────────────

export function newSoilReport(): ISoilReport {
	return {
		schema: SOIL_SCHEMA_ID,
		report: {},
		groundLevel: 0,
		boreholes: [],
		design: { hammerEnergy: DESIGN_DEFAULTS.hammerEnergy, factorOfSafety: DESIGN_DEFAULTS.factorOfSafety, allowableSettlement: DESIGN_DEFAULTS.allowableSettlement, liquefaction: { magnitude: DESIGN_DEFAULTS.magnitude, pga: null } },
	};
}

export type ParsedSoilReport =
	| { readonly kind: 'report'; readonly report: ISoilReport }
	/** The stub a new project starts with: shown as an empty report, written on the first edit. */
	| { readonly kind: 'placeholder'; readonly report: ISoilReport }
	| { readonly kind: 'error'; readonly message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Reads the file's text; lists and objects the file lacks are filled in (missing lists are empty). */
export function parseSoilReport(text: string): ParsedSoilReport {
	if (!text.trim()) {
		return { kind: 'placeholder', report: newSoilReport() };
	}
	let value: unknown;
	try {
		value = JSON.parse(text);
	} catch (error) {
		return { kind: 'error', message: localize('soil.invalidJson', "This file contains invalid JSON ({0}). Fix it in the text editor; the soil report editor will not change it until then.", String(error)) };
	}
	if (!isRecord(value)) {
		return { kind: 'error', message: localize('soil.notObject', "This file does not contain a JSON object.") };
	}
	if (value.part === 'soil' && Object.keys(value).every(key => key === 'schema' || key === 'part')) {
		return { kind: 'placeholder', report: newSoilReport() };
	}
	if (value.schema !== SOIL_SCHEMA_ID) {
		return { kind: 'error', message: localize('soil.unexpected', "This file is not a SAEngine soil report ({0}).", SOIL_SCHEMA_ID) };
	}
	if (value.boreholes !== undefined && !Array.isArray(value.boreholes)) {
		return { kind: 'error', message: localize('soil.badBoreholes', "The soil report's boreholes are not a list.") };
	}
	const report = value as ISoilReport;
	report.report = isRecord(report.report) ? report.report : {};
	report.design = isRecord(report.design) ? report.design : {};
	report.boreholes = (report.boreholes ?? []).filter(isRecord) as IBorehole[];
	if (typeof report.groundLevel !== 'number') {
		report.groundLevel = 0;
	}
	for (const borehole of report.boreholes) {
		borehole.layers = Array.isArray(borehole.layers) ? borehole.layers.filter(isRecord) as ISoilLayer[] : [];
		borehole.spt = Array.isArray(borehole.spt) ? borehole.spt.filter(isRecord) as ISptRecord[] : [];
		borehole.samples = Array.isArray(borehole.samples) ? borehole.samples.filter(isRecord) as ISoilSample[] : [];
	}
	return { kind: 'report', report };
}

export function serializeSoilReport(report: ISoilReport): string {
	return JSON.stringify(report, undefined, '\t') + '\n';
}

/** The next free borehole id: BH-1, BH-2, ... */
export function nextBoreholeId(report: ISoilReport): string {
	const used = new Set(report.boreholes.map(b => b.id));
	let n = report.boreholes.length + 1;
	for (let i = 1; i <= n; i++) {
		if (!used.has(`BH-${i}`)) {
			n = i;
			break;
		}
	}
	return `BH-${n}`;
}

/** What to do with an imported borehole whose id the report already has. */
export type DuplicateChoice = 'replace' | 'keepBoth' | 'skip';

export interface IMergeResult {
	readonly added: readonly string[];
	readonly replaced: readonly string[];
	/** Kept both: the imported borehole under a new id. */
	readonly renamed: readonly { readonly from: string; readonly to: string }[];
	readonly skipped: readonly string[];
}

/** The ids of `incoming` boreholes the report already has, in the file's order. */
export function duplicateIds(report: ISoilReport, incoming: readonly IBorehole[]): string[] {
	const ids = new Set(report.boreholes.map(b => b.id));
	return incoming.filter(b => ids.has(b.id)).map(b => b.id);
}

/**
 * Merges imported boreholes into the report: a new id is added at the end; an id the report
 * has is replaced in place, kept beside it under the next free "-2", "-3" suffix, or skipped.
 */
export function mergeBoreholes(report: ISoilReport, incoming: readonly IBorehole[], choice: DuplicateChoice): IMergeResult {
	const added: string[] = [];
	const replaced: string[] = [];
	const renamed: { from: string; to: string }[] = [];
	const skipped: string[] = [];
	const used = new Set([...report.boreholes.map(b => b.id), ...incoming.map(b => b.id)]);
	for (const borehole of incoming) {
		const index = report.boreholes.findIndex(b => b.id === borehole.id);
		if (index < 0) {
			report.boreholes.push(borehole);
			added.push(borehole.id);
		} else if (choice === 'replace') {
			report.boreholes[index] = borehole;
			replaced.push(borehole.id);
		} else if (choice === 'skip') {
			skipped.push(borehole.id);
		} else {
			let n = 2;
			while (used.has(`${borehole.id}-${n}`)) {
				n++;
			}
			const to = `${borehole.id}-${n}`;
			used.add(to);
			renamed.push({ from: borehole.id, to });
			report.boreholes.push({ ...borehole, id: to });
		}
	}
	return { added, replaced, renamed, skipped };
}

/**
 * A new borehole beside the last one with nothing logged yet: no termination depth, no layers,
 * no records. The engineer enters them from the log sheet; nothing is made up.
 */
export function newBorehole(report: ISoilReport): IBorehole {
	const last = report.boreholes[report.boreholes.length - 1];
	return {
		id: nextBoreholeId(report),
		x: last ? last.x + 10000 : 0,
		y: last ? last.y : 0,
		layers: [],
		spt: [],
		samples: [],
	};
}

/** The deepest depth a borehole reaches: its termination, or its last layer or record [mm]. */
export function boreholeDepth(borehole: IBorehole): number {
	const depths = [
		borehole.depth ?? 0,
		...borehole.layers.map(l => Number(l.bottom) || 0),
		...borehole.spt.map(s => Number(s.depth) || 0),
		...borehole.samples.map(s => Number(s.depth) || 0),
	];
	return Math.max(0, ...depths);
}

/** The depth the borehole was drilled to as logged: its termination depth, else the deepest record [mm]. */
export function terminationDepth(borehole: IBorehole): number {
	return typeof borehole.depth === 'number' ? borehole.depth : boreholeDepth(borehole);
}

/** Whether a sample has lab results (an SPT row without them is not a lab sample). */
export function hasLabData(sample: ISoilSample): boolean {
	return Object.entries(sample).some(([key, value]) => !SAMPLE_RECORD_KEYS.has(key) && value !== undefined && value !== null && value !== '');
}

/** What a sample row records besides lab results: where it was taken and how. */
const SAMPLE_RECORD_KEYS = new Set(['depth', 'depthTo', 'type', 'number', 'description', 'uscs', 'recovery']);

/** The ground elevation of a borehole [mm]: its own, or the report's. */
export function boreholeGround(report: ISoilReport, borehole: IBorehole): number {
	return typeof borehole.groundLevel === 'number' ? borehole.groundLevel : report.groundLevel;
}

// ───────────────────────────── fields: units and validation ─────────────────────────────

export type FieldKind = 'depth' | 'length' | 'number' | 'integer' | 'text' | 'soilType';

/** A column of a data table or a row of the properties panel. */
export interface IFieldSpec {
	readonly key: string;
	readonly label: string;
	/** Unit shown to the engineer (depths in m though the file holds mm). */
	readonly unit?: string;
	readonly kind: FieldKind;
	readonly min?: number;
	readonly max?: number;
	/** Whether the value must be given. */
	readonly required?: boolean;
	readonly title?: string;
	/** Column width in the table [px]. */
	readonly width?: number;
	/** Decimals shown (4 when not given; depths and lengths in m: 3). */
	readonly decimals?: number;
}

const M = localize('soil.unit.m', "m");
const KPA = localize('soil.unit.kpa', "kPa");
const KNM3 = localize('soil.unit.knm3', "kN/m³");
const PERCENT = '%';
const DEG = '°';

export const LAYER_FIELDS: readonly IFieldSpec[] = [
	{ key: 'top', label: localize('soil.f.top', "Top"), unit: M, kind: 'depth', min: 0, required: true, width: 64 },
	{ key: 'bottom', label: localize('soil.f.bottom', "Bottom"), unit: M, kind: 'depth', min: 0, required: true, width: 64 },
	{ key: 'description', label: localize('soil.f.description', "Description"), kind: 'text', width: 220 },
	{ key: 'soilType', label: localize('soil.f.soilType', "Soil type"), kind: 'soilType', required: true, width: 92 },
	{ key: 'uscs', label: localize('soil.f.uscs', "USCS"), kind: 'text', width: 58, title: localize('soil.f.uscsTitle', "Unified Soil Classification System group symbol (ASTM D2487), e.g. CL, ML, SM") },
	{ key: 'unitWeight', label: 'γ', unit: KNM3, kind: 'number', min: 5, max: 30, width: 58, title: localize('soil.f.gammaTitle', "Bulk unit weight") },
	{ key: 'saturatedUnitWeight', label: 'γsat', unit: KNM3, kind: 'number', min: 5, max: 30, width: 58, title: localize('soil.f.gammaSatTitle', "Saturated unit weight") },
	{ key: 'cu', label: 'cu', unit: KPA, kind: 'number', min: 0, max: 2000, width: 58, title: localize('soil.f.cuTitle', "Undrained shear strength") },
	{ key: 'c', label: 'c′', unit: KPA, kind: 'number', min: 0, max: 500, width: 58, title: localize('soil.f.cTitle', "Effective cohesion") },
	{ key: 'phi', label: 'φ′', unit: DEG, kind: 'number', min: 0, max: 50, width: 58, title: localize('soil.f.phiTitle', "Effective friction angle") },
	{ key: 'E', label: 'E', unit: localize('soil.unit.mpa', "MPa"), kind: 'number', min: 0, max: 10000, width: 58, title: localize('soil.f.eTitle', "Young's modulus of the soil") },
	{ key: 'finesContent', label: 'FC', unit: PERCENT, kind: 'number', min: 0, max: 100, width: 58, title: localize('soil.f.fcTitle', "Fines content (passing 75 µm)") },
	{ key: 'plasticityIndex', label: 'PI', unit: PERCENT, kind: 'number', min: 0, max: 200, width: 58, title: localize('soil.f.piTitle', "Plasticity index") },
	{ key: 'liquidLimit', label: 'LL', unit: PERCENT, kind: 'number', min: 0, max: 300, width: 58, title: localize('soil.f.llTitle', "Liquid limit") },
	{ key: 'Cc', label: 'Cc', kind: 'number', min: 0, max: 5, width: 58, title: localize('soil.f.ccTitle', "Compression index") },
	{ key: 'Cr', label: 'Cr', kind: 'number', min: 0, max: 2, width: 58, title: localize('soil.f.crTitle', "Recompression index") },
	{ key: 'e0', label: 'e0', kind: 'number', min: 0, max: 10, width: 58, title: localize('soil.f.e0Title', "Initial void ratio") },
	{ key: 'OCR', label: 'OCR', kind: 'number', min: 1, max: 50, width: 58, title: localize('soil.f.ocrTitle', "Overconsolidation ratio") },
];

/**
 * Whether a layer is a silt with neither a PI nor a cu, from its own row or its lab samples
 * (a PI needs both LL and PL): the backend then treats it as non-plastic (granular), so the
 * Data view asks whether it is plastic. The samples are the backend's (`saengine.soil.profile`):
 * those from the layer's top (inclusive) to its bottom; for the last layer with none of its
 * own, every sample from its top down.
 */
export function siltNeedsPlasticity(borehole: IBorehole, layer: ISoilLayer): boolean {
	if (layer.soilType !== 'silt' || typeof layer.plasticityIndex === 'number' || typeof layer.cu === 'number') {
		return false;
	}
	let samples = borehole.samples.filter(s => layer.top <= s.depth && s.depth < layer.bottom);
	if (!samples.length && borehole.layers.indexOf(layer) === borehole.layers.length - 1) {
		samples = borehole.samples.filter(s => s.depth >= layer.top);
	}
	return !samples.some(s => typeof s.cu === 'number' || (typeof s.liquidLimit === 'number' && typeof s.plasticLimit === 'number'));
}

export const SPT_FIELDS: readonly IFieldSpec[] = [
	{ key: 'depth', label: localize('soil.f.depth', "Depth"), unit: M, kind: 'depth', min: 0, required: true, width: 70 },
	{ key: 'N', label: 'N', kind: 'integer', min: 0, max: 100, required: true, width: 60, title: localize('soil.f.nTitle', "Field SPT blow count for 300 mm (ASTM D1586); 100 for refusal") },
	{ key: 'energyRatio', label: localize('soil.f.energyRatio', "Energy ratio"), unit: PERCENT, kind: 'number', min: 30, max: 100, width: 84, title: localize('soil.f.erTitle', "Hammer energy ratio of this test; empty uses the report's") },
];

export const SAMPLE_FIELDS: readonly IFieldSpec[] = [
	{ key: 'depth', label: localize('soil.f.depth', "Depth"), unit: M, kind: 'depth', min: 0, required: true, width: 64 },
	{ key: 'type', label: localize('soil.f.sampleType', "Type"), kind: 'text', width: 64, title: localize('soil.f.sampleTypeTitle', "UD (undisturbed), SPT (split spoon), D (disturbed)...") },
	{ key: 'moisture', label: 'w', unit: PERCENT, kind: 'number', min: 0, max: 500, width: 58, title: localize('soil.f.wTitle', "Natural moisture content") },
	{ key: 'unitWeight', label: 'γ', unit: KNM3, kind: 'number', min: 5, max: 30, width: 58 },
	{ key: 'cu', label: 'cu', unit: KPA, kind: 'number', min: 0, max: 2000, width: 58, title: localize('soil.f.cuSampleTitle', "Undrained shear strength (unconfined compression or UU triaxial)") },
	{ key: 'c', label: 'c′', unit: KPA, kind: 'number', min: 0, max: 500, width: 58 },
	{ key: 'phi', label: 'φ′', unit: DEG, kind: 'number', min: 0, max: 50, width: 58 },
	{ key: 'finesContent', label: 'FC', unit: PERCENT, kind: 'number', min: 0, max: 100, width: 58 },
	{ key: 'liquidLimit', label: 'LL', unit: PERCENT, kind: 'number', min: 0, max: 300, width: 58 },
	{ key: 'plasticLimit', label: 'PL', unit: PERCENT, kind: 'number', min: 0, max: 200, width: 58 },
	{ key: 'Cc', label: 'Cc', kind: 'number', min: 0, max: 5, width: 58 },
	{ key: 'e0', label: 'e0', kind: 'number', min: 0, max: 10, width: 58 },
];

export const BOREHOLE_FIELDS: readonly IFieldSpec[] = [
	{ key: 'id', label: localize('soil.f.id', "ID"), kind: 'text', required: true },
	{ key: 'x', label: 'X', unit: M, kind: 'length', required: true, title: localize('soil.f.xTitle', "Plan position in project coordinates") },
	{ key: 'y', label: 'Y', unit: M, kind: 'length', required: true },
	{ key: 'groundLevel', label: localize('soil.f.groundLevel', "Ground level"), unit: M, kind: 'length', title: localize('soil.f.groundLevelTitle', "Elevation of the existing ground at the borehole on the project datum; empty uses the report's") },
	{ key: 'waterTable', label: localize('soil.f.waterTable', "Water table"), unit: M, kind: 'depth', min: 0, title: localize('soil.f.waterTableTitle', "Depth of the ground water table below the borehole's ground") },
	{ key: 'depth', label: localize('soil.f.termination', "Termination depth"), unit: M, kind: 'depth', min: 0 },
	{ key: 'lat', label: localize('soil.f.lat', "Latitude"), unit: DEG, kind: 'number', min: -90, max: 90, decimals: 7, title: localize('soil.f.latTitle', "WGS 84; when given with the longitude it places the borehole, and X and Y follow from it") },
	{ key: 'lon', label: localize('soil.f.lon', "Longitude"), unit: DEG, kind: 'number', min: -180, max: 180, decimals: 7 },
	{ key: 'easting', label: localize('soil.f.easting', "BTM easting"), unit: M, kind: 'number', decimals: 3, title: localize('soil.f.btmTitle', "Bangladesh Transverse Mercator (EPSG:9678), as survey drawings give it; places the borehole when there is no latitude and longitude") },
	{ key: 'northing', label: localize('soil.f.northing', "BTM northing"), unit: M, kind: 'number', decimals: 3 },
	{ key: 'date', label: localize('soil.f.dateDrilled', "Date drilled"), kind: 'text' },
	{ key: 'method', label: localize('soil.f.method', "Method"), kind: 'text', title: localize('soil.f.methodTitle', "How the borehole was drilled, e.g. wash boring, auger, rotary") },
];

export const REPORT_FIELDS: readonly IFieldSpec[] = [
	{ key: 'title', label: localize('soil.f.title', "Title"), kind: 'text' },
	{ key: 'consultant', label: localize('soil.f.consultant', "Consultant"), kind: 'text' },
	{ key: 'reportNumber', label: localize('soil.f.reportNumber', "Report number"), kind: 'text' },
	{ key: 'date', label: localize('soil.f.date', "Date"), kind: 'text' },
];

export const DESIGN_FIELDS: readonly IFieldSpec[] = [
	{ key: 'hammerEnergy', label: localize('soil.f.hammerEnergy', "Hammer energy"), unit: PERCENT, kind: 'number', min: 30, max: 100, title: localize('soil.f.hammerEnergyTitle', "Energy ratio of the SPT hammer; N60 = N × ER / 60. Typical donut hammers in Bangladesh deliver about 45 to 60%.") },
	{ key: 'factorOfSafety', label: localize('soil.f.fs', "Factor of safety"), kind: 'number', min: 1, max: 10, title: localize('soil.f.fsTitle', "On the ultimate bearing capacity") },
	{ key: 'allowableSettlement', label: localize('soil.f.settlement', "Allowable settlement"), unit: localize('soil.unit.mm', "mm"), kind: 'number', min: 1, max: 500 },
	{ key: 'magnitude', label: localize('soil.f.magnitude', "Earthquake magnitude"), unit: 'Mw', kind: 'number', min: 5, max: 9.5, title: localize('soil.f.magnitudeTitle', "Moment magnitude of the design earthquake for the liquefaction screening") },
	{ key: 'pga', label: localize('soil.f.pga', "PGA"), unit: 'g', kind: 'number', min: 0, max: 2, title: localize('soil.f.pgaTitle', "Peak ground acceleration; empty takes it from the project settings' seismic zone and site class") },
];

/** The value an input shows for a stored value (depths and lengths in m). */
export function formatField(spec: IFieldSpec, value: unknown): string {
	if (value === undefined || value === null || value === '') {
		return '';
	}
	if (spec.kind === 'depth' || spec.kind === 'length') {
		return typeof value === 'number' ? formatNumber(value / 1000, 3) : String(value);
	}
	return typeof value === 'number' ? formatNumber(value, spec.decimals ?? 4) : String(value);
}

/** A number without trailing zeros, at most `decimals` places. */
export function formatNumber(value: number, decimals = 2): string {
	if (!Number.isFinite(value)) {
		return '';
	}
	const fixed = value.toFixed(decimals);
	return fixed.includes('.') ? fixed.replace(/\.?0+$/, '') : fixed;
}

export interface IFieldValue {
	/** The value to store; undefined clears the field. */
	readonly value?: number | string;
	readonly error?: string;
}

/** Thousands grouped by commas: 1,200 and 12,000 (Western) or 1,20,000 (South Asian). */
const GROUPED = /^[+-]?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3})(?:\.\d*)?$/;

/**
 * A typed number. Commas that group thousands (as Bangladeshi reports write "1,200 kPa") are
 * dropped; any other comma is refused rather than guessed as a decimal comma, so "1,200" can
 * never become 1.2.
 */
function parseNumber(text: string): number | 'comma' {
	if (!text.includes(',')) {
		return Number(text);
	}
	return GROUPED.test(text) ? Number(text.replace(/,/g, '')) : 'comma';
}

/** Reads what the engineer typed into a field: the value to store, or why it is not valid. */
export function parseField(spec: IFieldSpec, raw: string): IFieldValue {
	const text = raw.trim();
	if (!text) {
		return spec.required ? { error: localize('soil.v.required', "{0} is required.", spec.label) } : {};
	}
	if (spec.kind === 'text') {
		return { value: text };
	}
	if (spec.kind === 'soilType') {
		return SOIL_TYPES.includes(text as SoilType) ? { value: text } : { error: localize('soil.v.soilType', "Pick one of: {0}.", SOIL_TYPES.join(', ')) };
	}
	const number = parseNumber(text);
	if (number === 'comma') {
		return { error: localize('soil.v.comma', "{0}: use a point for decimals (1.5); commas only group thousands (1,200).", spec.label) };
	}
	if (!Number.isFinite(number)) {
		return { error: localize('soil.v.number', "{0} must be a number.", spec.label) };
	}
	if (spec.kind === 'integer' && !Number.isInteger(number)) {
		return { error: localize('soil.v.integer', "{0} must be a whole number.", spec.label) };
	}
	if (spec.min !== undefined && number < spec.min) {
		return { error: localize('soil.v.min', "{0} must be at least {1}{2}.", spec.label, spec.min, spec.unit ? ` ${spec.unit}` : '') };
	}
	if (spec.max !== undefined && number > spec.max) {
		return { error: localize('soil.v.max', "{0} must be at most {1}{2}.", spec.label, spec.max, spec.unit ? ` ${spec.unit}` : '') };
	}
	return { value: spec.kind === 'depth' || spec.kind === 'length' ? Math.round(number * 1000) : number };
}

// ───────────────────────────── whole-report checks ─────────────────────────────

/** A problem of the report, by borehole and the path inside it ("layers.2.bottom"). */
export interface ISoilProblem {
	readonly borehole?: string;
	/** The borehole's place in the report (ids may repeat). */
	readonly index?: number;
	readonly path?: string;
	readonly message: string;
	readonly severity: 'error' | 'warning';
}

/** The group symbols of the Unified Soil Classification System (ASTM D2487), with Pt for peat. */
const USCS_SYMBOLS = new Set(['GW', 'GP', 'GM', 'GC', 'SW', 'SP', 'SM', 'SC', 'ML', 'CL', 'OL', 'MH', 'CH', 'OH', 'PT']);

/**
 * The British (BS 5930) plasticity symbols logs in Bangladesh often use, and the USCS group they
 * fall in on the plasticity chart: I (intermediate, LL 35-50) is USCS's low (LL < 50); H, V and
 * E (LL above 50) are its high.
 */
const BS_TO_USCS: { readonly [symbol: string]: string } = {
	CI: 'CL', MI: 'ML', CV: 'CH', CE: 'CH', MV: 'MH', ME: 'MH',
};

/** What is wrong with a USCS symbol: unknown, or a BS 5930 one (with its USCS group); undefined when fine or empty. */
export function uscsProblem(symbol: string | undefined): string | undefined {
	const text = (symbol ?? '').trim().toUpperCase();
	if (!text) {
		return undefined;
	}
	// Dual symbols (SP-SM, CL-ML) and borderline ones (CL/ML): each part a group symbol.
	const parts = text.split(/[-/]/).map(p => p.trim());
	if (parts.every(p => USCS_SYMBOLS.has(p))) {
		return undefined;
	}
	const bs = parts.find(p => BS_TO_USCS[p]);
	if (bs) {
		return localize('soil.p.uscsBs', "{0} is a BS 5930 symbol, not USCS: on the plasticity chart it is {1} (ASTM D2487). Give {1}, or LL and PL to classify it.", bs, BS_TO_USCS[bs]);
	}
	return localize('soil.p.uscsUnknown', "{0} is not a USCS group symbol (ASTM D2487: GW, GP, GM, GC, SW, SP, SM, SC, ML, CL, OL, MH, CH, OH, Pt; dual as SP-SM).", symbol!.trim());
}

/** The checks the editor makes while typing (the backend checks the rest). */
export function checkSoilReport(report: ISoilReport): ISoilProblem[] {
	const problems: ISoilProblem[] = [];
	const counts = new Map<string, number>();
	for (const borehole of report.boreholes) {
		const id = String(borehole.id ?? '');
		counts.set(id, (counts.get(id) ?? 0) + 1);
	}
	report.boreholes.forEach((borehole, boreholeIndex) => {
		const problem = (p: Omit<ISoilProblem, 'index'>) => problems.push({ ...p, index: boreholeIndex });
		const id = String(borehole.id ?? '');
		if (!id) {
			problem({ path: 'id', message: localize('soil.p.noId', "A borehole has no id."), severity: 'error' });
		} else if ((counts.get(id) ?? 0) > 1) {
			// Every borehole with the id, so that each problem opens its own borehole.
			problem({ borehole: id, path: 'id', message: localize('soil.p.duplicateIdOf', "{0} boreholes are called {1}: give each its own id.", counts.get(id), id), severity: 'error' });
		}
		// What the backend refuses (library/soil.py Borehole) is an error: the report cannot be read until it is fixed.
		const layers = [...borehole.layers].map((layer, index) => ({ layer, index })).sort((a, b) => a.layer.top - b.layer.top);
		const termination = typeof borehole.depth === 'number' ? borehole.depth : undefined;
		let previousBottom = 0;
		layers.forEach(({ layer, index }, order) => {
			const n = order + 1;
			const uscs = uscsProblem(layer.uscs);
			if (uscs) {
				problem({ borehole: id, path: `layers.${index}.uscs`, message: localize('soil.p.uscs', "{0}: layer {1}: {2}", id, n, uscs), severity: 'warning' });
			}
			if (!(layer.bottom > layer.top)) {
				problem({ borehole: id, path: `layers.${index}.bottom`, message: localize('soil.p.layerThickness', "{0}: layer {1} ends at or above its top.", id, n), severity: 'error' });
			}
			if (order === 0 && layer.top > 1) {
				problem({ borehole: id, path: `layers.${index}.top`, message: localize('soil.p.firstLayer', "{0}: layer 1 starts at {1} m; the first layer starts at the ground (0 m).", id, formatNumber(layer.top / 1000)), severity: 'error' });
			} else if (order > 0 && Math.abs(layer.top - previousBottom) > 1) {
				problem({
					borehole: id, path: `layers.${index}.top`, severity: 'error', message: layer.top > previousBottom
						? localize('soil.p.gap', "{0}: a gap between layer {1} and layer {2} ({3} m to {4} m).", id, n - 1, n, formatNumber(previousBottom / 1000), formatNumber(layer.top / 1000))
						: localize('soil.p.overlap', "{0}: layer {1} overlaps layer {2} ({3} m to {4} m).", id, n, n - 1, formatNumber(layer.top / 1000), formatNumber(previousBottom / 1000)),
				});
			}
			if (termination !== undefined && layer.bottom > termination + 1) {
				problem({ borehole: id, path: `layers.${index}.bottom`, message: localize('soil.p.layerBelow', "{0}: layer {1} ends at {2} m, below the termination depth {3} m.", id, n, formatNumber(layer.bottom / 1000), formatNumber(termination / 1000)), severity: 'error' });
			}
			previousBottom = Math.max(previousBottom, layer.bottom);
		});
		// The bottom of the borehole as the backend takes it: the termination depth, else the deepest layer.
		const bottom = Math.max(termination ?? 0, ...borehole.layers.map(l => Number(l.bottom) || 0));
		if (termination !== undefined || borehole.layers.length) {
			borehole.spt.forEach((record, index) => {
				if (record.depth > bottom + 1) {
					problem({ borehole: id, path: `spt.${index}.depth`, message: localize('soil.p.sptBelow', "{0}: the SPT at {1} m is below the bottom of the borehole ({2} m).", id, formatNumber(record.depth / 1000), formatNumber(bottom / 1000)), severity: 'error' });
				}
			});
		}
		if (termination !== undefined && typeof borehole.waterTable === 'number' && borehole.waterTable > termination + 1) {
			problem({ borehole: id, path: 'waterTable', message: localize('soil.p.waterBelow', "{0}: the water table ({1} m) is below the termination depth {2} m.", id, formatNumber(borehole.waterTable / 1000), formatNumber(termination / 1000)), severity: 'warning' });
		}
		const sptDepths = new Set<number>();
		borehole.spt.forEach((record, index) => {
			if (sptDepths.has(record.depth)) {
				problem({ borehole: id, path: `spt.${index}.depth`, message: localize('soil.p.sptTwice', "{0}: two SPT records at {1} m.", id, formatNumber(record.depth / 1000)), severity: 'error' });
			}
			sptDepths.add(record.depth);
		});
		if (!borehole.layers.length) {
			problem({ borehole: id, path: 'layers', message: localize('soil.p.noLayers', "{0} has no layers yet.", id), severity: 'warning' });
		}
		const away = distanceFromSite(report, borehole);
		if (away !== undefined && away > FAR_FROM_SITE) {
			const path = boreholePosition(borehole) === 'wgs84' ? 'lat' : 'x';
			problem({ borehole: id, path, message: localize('soil.p.farFromSite', "{0} is {1} m from the site: check its position.", id, formatNumber(away, 0)), severity: 'warning' });
		}
	});
	// BNBC 2020 Table 6.2.13 classifies the site by the top 30 m: when no borehole with SPT reaches
	// it (or rock), the site class is provisional. One note for the report, not one per borehole.
	const tested = report.boreholes.filter(b => b.spt.length);
	const reaches = (b: IBorehole) => terminationDepth(b) >= SITE_CLASS_DEPTH - 1 || b.layers.some(l => l.soilType === 'rock' && l.bottom >= terminationDepth(b) - 1);
	if (tested.length && !tested.some(reaches)) {
		const deepest = Math.max(...tested.map(terminationDepth));
		problems.push({ message: localize('soil.p.shallowForSiteClass', "No borehole reaches 30 m (the deepest ends at {0} m): BNBC 2020 Table 6.2.13 classifies the site by the top 30 m, so the site class is provisional (the last N is carried down to 30 m). Drill one borehole to 30 m to confirm it.", formatNumber(deepest / 1000, 1)), severity: 'warning' });
	}
	return problems;
}

/** A borehole further than this from the site point is probably misplaced [m]. */
export const FAR_FROM_SITE = 200;

/**
 * How far a borehole is from the site point on the map [m]: by latitude and longitude when it
 * is placed by them, else by its project X and Y from the site's project point. Undefined when
 * the site has no position, or the borehole is placed by BTM (that needs the backend).
 */
export function distanceFromSite(report: ISoilReport, borehole: IBorehole): number | undefined {
	const site = report.site;
	if (typeof site?.lat !== 'number' || typeof site.lon !== 'number') {
		return undefined;
	}
	const position = boreholePosition(borehole);
	if (position === 'wgs84' && typeof borehole.lat === 'number' && typeof borehole.lon === 'number') {
		const radians = Math.PI / 180;
		const dLat = (borehole.lat - site.lat) * radians;
		const dLon = (borehole.lon - site.lon) * radians;
		const a = Math.sin(dLat / 2) ** 2 + Math.cos(site.lat * radians) * Math.cos(borehole.lat * radians) * Math.sin(dLon / 2) ** 2;
		return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(a)));
	}
	if (position === 'project') {
		return Math.hypot(borehole.x - (site.x ?? 0), borehole.y - (site.y ?? 0)) / 1000;
	}
	return undefined;
}

/** What the sidebar says about the part (see `partStatus`): "3 boreholes", "no boreholes". */
export function soilSummary(report: ISoilReport): string {
	const n = report.boreholes.length;
	return n === 0 ? localize('soil.summary.none', "no boreholes")
		: n === 1 ? localize('soil.summary.one', "1 borehole")
			: localize('soil.summary.many', "{0} boreholes", n);
}

/** "qa 150 kPa at B 2 m, Df 1.5 m" */
export function bearingSummary(cell: IBearingCell): string {
	return localize('soil.qaAt', "qa {0} kPa at B {1} m, Df {2} m", typeof cell.qa === 'number' ? formatNumber(cell.qa, 0) : '—', formatNumber(cell.B / 1000), formatNumber(cell.Df / 1000));
}
