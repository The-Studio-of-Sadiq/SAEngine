/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { gridLabel, IGridLine } from '../../../services/saengineProject/common/gridLabels.js';
import { DEFAULT_CODE_PACK_ID } from '../../../services/saengineProject/common/activeCodePack.js';

/*
 * The New Building wizard's model: the grid spacings and storey heights as engineers type them
 * ("3×6000, 4500"), and the building specification the generator (`saengine.library.generateBuilding`)
 * turns into a project with its floor plan. No UI here, so it is tested on its own.
 */

/** The backend command that writes the new project (wired by the integrator). */
export const GENERATE_BUILDING_COMMAND = 'saengine.library.generateBuilding';

/** The UI command that opens the wizard. */
export const NEW_BUILDING_COMMAND = 'saengine.project.newBuilding';

/** Application storage: the building just generated, so its window opens the floor plan and shows the notes. */
export const PENDING_BUILDING_STORAGE_KEY = 'saengine.newBuilding.pending';

export type StructuralSystemChoice = 'rcFrame' | 'rcFrameCore' | 'flatSlab' | 'masonry' | 'steelMomentFrame' | 'steelBracedFrame';
/** The foundations the generator places (integrator: combined footings and pile caps are added in 09 Substructure). */
export type FootingChoice = 'isolated' | 'mat' | 'none';
export type OccupancyCategory = 'I' | 'II' | 'III' | 'IV';
/** BNBC 2020 site classes (Part 6, Table 6.2.13), as in the project settings (`site.siteClass`). */
/** C7: a pack other than the default has its own site classes (IS soil types I-III). */
export type SiteClass = string;

export const SYSTEM_CHOICES: readonly { readonly value: StructuralSystemChoice; readonly label: string; readonly description: string }[] = [
	{ value: 'rcFrame', label: localize('system.rcFrame', "RC frame"), description: localize('system.rcFrame.description', "Columns at every grid intersection, beams on every grid line, a slab in every bay.") },
	{ value: 'rcFrameCore', label: localize('system.rcFrameCore', "RC frame + core walls"), description: localize('system.rcFrameCore.description', "The frame, with shear walls around the central bay for the lift and stair core.") },
	{ value: 'flatSlab', label: localize('system.flatSlab', "Flat slab"), description: localize('system.flatSlab.description', "Columns and flat plates only, no beams (no drop panels or edge beams); core walls where Seismic Design Category D needs them.") },
	{ value: 'masonry', label: localize('system.masonry', "Load-bearing masonry (low-rise)"), description: localize('system.masonry.description', "Brick walls on every grid line carrying two-way slabs, strip footings, no columns or beams; plain masonry where the design code's seismic category allows it, reinforced above that, not permitted where its structural system table excludes it.") },
	// Alpha 9 C3b: steel systems; the code pack's systems decide the frame's ductility (ordinary, intermediate or special).
	{ value: 'steelMomentFrame', label: localize('system.steelMomentFrame', "Steel moment frame"), description: localize('system.steelMomentFrame.description', "Steel columns and beams with moment connections on every grid line, RC slabs on the beams; the design code's ordinary, intermediate or special moment frame that the Seismic Design Category and height permit.") },
	{ value: 'steelBracedFrame', label: localize('system.steelBracedFrame', "Steel braced frame"), description: localize('system.steelBracedFrame.description', "Steel columns and beams with X braces in one bay of each outer frame line, RC slabs on the beams; the design code's ordinary or special concentrically braced frame that the Seismic Design Category and height permit.") },
];

export const FOOTING_CHOICES: readonly { readonly value: FootingChoice; readonly label: string }[] = [
	{ value: 'isolated', label: localize('footing.isolated', "Isolated") },
	{ value: 'mat', label: localize('footing.mat', "Mat (raft)") },
	{ value: 'none', label: localize('footing.none', "None (add in 09 Substructure)") },
];

/** A story of the floor plan (as in `floor-plan.json`); the first is the base. */
export interface IStorySpec {
	readonly id: string;
	readonly name: string;
	readonly elevation: number;
}

/**
 * What the generator builds: the `spec` of `saengine.library.generateBuilding`. Lengths in mm.
 * Grid lines and stories are written out, so the generator need not parse the shorthand; the
 * spacings and heights are given too, for its notes.
 */
export interface INewBuildingSpec {
	readonly schema: 'saengine.newBuilding/1';
	readonly name: string;
	readonly grids: { readonly x: readonly IGridLine[]; readonly y: readonly IGridLine[] };
	readonly spacings: { readonly x: readonly number[]; readonly y: readonly number[] };
	/** BASE at 0, then L1, L2, ... */
	readonly stories: readonly IStorySpec[];
	/** Height of each storey above the base, lowest first. */
	readonly storyHeights: readonly number[];
	readonly system: StructuralSystemChoice;
	/** Material ids of `03 Materials` (the default materials). */
	readonly materials: { readonly concrete: string; readonly rebar: string };
	readonly footing: FootingChoice;
	/**
	 * BNBC 2020 location id of the project settings (`site.location`), and the site class: without
	 * a soil report it is an assumption (`siteClassSource: 'assumed'`), which the report says.
	 */
	readonly site: { readonly location: string; readonly siteClass: SiteClass; readonly siteClassSource: 'assumed'; readonly zoneCoefficient?: number; readonly windSpeed?: number; readonly spectral?: ISpectralValues; readonly hazardSource?: { readonly [key: string]: unknown } };
	/** Project settings `occupancy`: building use and BNBC occupancy category. */
	readonly occupancy: { readonly use: string; readonly category: OccupancyCategory };
	/** The code pack id; another than the default takes Z, V and the exposure of its own lists. */
	readonly designCode: string;
	/** The wind exposure (terrain category) of a pack other than the default. */
	readonly wind?: { readonly exposure: string };
	/** Walk 4 (W4A-6): the project's display units (the pack's suggestion unless changed). */
	readonly units?: UnitSystem;
}

/** Walk 4 (W4A-6): the unit systems a new project can show its numbers in. */
export type UnitSystem = 'SI' | 'USCustomary';

/**
 * The site's mapped spectral values (Project Settings `site.spectral`) of a code pack whose
 * seismic hazard comes from the code's hazard tool (ASCE 7-22): SDS, SD1, S1 [g], TL [s].
 */
export interface ISpectralValues {
	readonly sds?: number;
	readonly sd1?: number;
	readonly s1?: number;
	readonly tl?: number;
	/** C22: further values of an online lookup (SMS, SM1, SS and the multi-period spectra). */
	readonly [key: string]: number | readonly (readonly number[])[] | undefined;
}

/**
 * C22: the site's values looked up online in the wizard: every `site.spectral` value the service
 * gave (the typed SDS, SD1, S1 and TL take precedence) and the record kept as `site.hazardSource`.
 */
export interface IWizardHazard {
	readonly spectral: { readonly [key: string]: number | readonly (readonly number[])[] | undefined };
	readonly source: { readonly [key: string]: unknown };
}

/** The wizard's fields as typed. */
export interface INewBuildingForm {
	readonly name: string;
	readonly gridX: string;
	readonly gridY: string;
	readonly storyCount: string;
	readonly groundHeight: string;
	readonly typicalHeight: string;
	/** Every storey height, overriding count, ground and typical when not blank ("4000, 9×3200"). */
	readonly heights: string;
	readonly system: StructuralSystemChoice;
	readonly concrete: string;
	readonly rebar: string;
	readonly footing: FootingChoice;
	readonly location: string;
	readonly siteClass: SiteClass;
	readonly use: string;
	readonly category: OccupancyCategory;
	/** The design code (code pack id). */
	readonly designCode: string;
	/** A pack other than the default: Z (its peak ground acceleration, g), V [m/s], exposure id. */
	readonly zoneCoefficient: string;
	readonly windSpeed: string;
	readonly exposure: string;
	/** C7: the chosen pack lists its own towns: the location is one of them, not Custom. */
	readonly packTowns?: boolean;
	/** C1: a pack whose design spectrum is mapped (ASCE 7-22): SDS, SD1, S1 [g] and TL [s], as typed. */
	readonly sds: string;
	readonly sd1: string;
	readonly s1: string;
	readonly tl: string;
	/** C22: the values of an online lookup by the site's coordinates, where one was applied. */
	readonly hazard?: IWizardHazard;
	/**
	 * Walk 4 (W4A-6): the units the lengths and the wind speed are typed in and the project shows
	 * (lengths in ft and the wind speed in mph in US customary units); SI when not set.
	 */
	readonly units?: UnitSystem;
}

/** The unit lengths are typed in without a unit of their own: ft in US customary units, else mm. */
export function lengthUnit(form: Pick<INewBuildingForm, 'units'>): 'mm' | 'ft' {
	return form.units === 'USCustomary' ? 'ft' : 'mm';
}

/** A mile per hour [m/s] (NIST SP 811), for a wind speed typed in US customary units. */
const MPH = 0.44704;

/**
 * The form's lengths and wind speed written again in the units of `units` (the lengths of the
 * template are in mm; in feet they are rounded to the half foot, a new building's nice numbers).
 */
export function formInUnits(form: INewBuildingForm, units: UnitSystem): INewBuildingForm {
	if ((form.units ?? 'SI') === units) {
		return form;
	}
	const from = lengthUnit(form);
	const to = units === 'USCustomary' ? 'ft' : 'mm';
	const again = (text: string, limits: { readonly min: number; readonly max: number; readonly maxCount: number }) => {
		if (!text.trim()) {
			return text;
		}
		const parsed = parseLengths(text, limits, from);
		return parsed.ok ? formatLengths(parsed.values, to) : text;
	};
	const spacing = { min: MIN_SPACING, max: MAX_SPACING, maxCount: MAX_BAYS };
	const height = { min: MIN_HEIGHT, max: MAX_HEIGHT, maxCount: MAX_STORIES };
	const wind = positive(form.windSpeed);
	return {
		...form,
		units,
		gridX: again(form.gridX, spacing),
		gridY: again(form.gridY, spacing),
		groundHeight: again(form.groundHeight, { ...height, maxCount: 1 }),
		typicalHeight: again(form.typicalHeight, { ...height, maxCount: 1 }),
		heights: again(form.heights, height),
		windSpeed: wind === undefined ? form.windSpeed : String(Math.round(units === 'USCustomary' ? wind / MPH : wind * MPH)),
	};
}

/**
 * The form before a building template fills it: blank lengths, and choices that fall back to
 * the first option of each list. The wizard's starting values are the built-in building
 * template `saengine-default-building` (docs/marketplace-plan.md, round M4), applied by
 * {@link formFromSpec}; the wizard keeps no copy of its own.
 */
export const BLANK_FORM: INewBuildingForm = {
	name: '',
	gridX: '',
	gridY: '',
	storyCount: '',
	groundHeight: '',
	typicalHeight: '',
	heights: '',
	system: 'rcFrame',
	concrete: '',
	rebar: '',
	footing: 'isolated',
	location: '',
	siteClass: 'SD',
	use: '',
	category: 'II',
	designCode: DEFAULT_CODE_PACK_ID,
	zoneCoefficient: '',
	windSpeed: '',
	exposure: '',
	sds: '',
	sd1: '',
	s1: '',
	tl: '',
};

/** A positive number typed in the form, else undefined. */
function positive(text: string): number | undefined {
	const value = Number(text.trim().replace(',', '.'));
	return text.trim() && Number.isFinite(value) && value > 0 ? value : undefined;
}

/** C1: the mapped spectral values typed in the form (a pack whose design spectrum is mappedSpectral), else undefined. */
function spectralValues(form: INewBuildingForm): ISpectralValues | undefined {
	// C22: a lookup's values first; the four typed in the form take precedence (or clear them).
	const spectral: { [key: string]: number | readonly (readonly number[])[] } = {};
	for (const [key, value] of Object.entries(form.hazard?.spectral ?? {})) {
		if (value !== undefined && !['sds', 'sd1', 's1', 'tl'].includes(key)) {
			spectral[key] = value;
		}
	}
	for (const key of ['sds', 'sd1', 's1', 'tl'] as const) {
		const value = positive(form[key] ?? '');
		if (value !== undefined) {
			spectral[key] = value;
		}
	}
	return Object.keys(spectral).length ? spectral as ISpectralValues : undefined;
}

type SpecRaw = { readonly [key: string]: unknown };

function specLengths(value: unknown): number[] | undefined {
	return Array.isArray(value) && value.length && value.every(v => typeof v === 'number' && v > 0) ? value as number[] : undefined;
}

function specText(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() ? value.trim() : typeof value === 'number' && value > 0 ? String(value) : undefined;
}

/**
 * The form filled from a building template's specification (`spec.json`, SAEngine's
 * `BuildingSpec`: `gridsX`, `gridsY`, `storyCount`, `groundHeight`, `typicalHeight` or
 * `stories`, `system`, `concrete`, `rebar`, `footing`, `occupancy`, `occupancyCategory`,
 * `location`, `siteClass`). The name typed in the form is kept; a field the specification does
 * not give, or gives a value the wizard does not offer, keeps the form's value.
 */
export function formFromSpec(spec: SpecRaw, form: INewBuildingForm): INewBuildingForm {
	const x = specLengths(spec.gridsX);
	const y = specLengths(spec.gridsY);
	const stories = Array.isArray(spec.stories) ? specLengths(spec.stories.map(s => typeof s === 'object' && s !== null ? (s as SpecRaw).height : undefined)) : undefined;
	const pick = <T extends string>(value: unknown, allowed: readonly T[] | undefined, fallback: T): T =>
		typeof value === 'string' && (!allowed || allowed.includes(value as T)) ? value as T : fallback;
	// W4A-6: the specification's lengths [mm] in the form's unit (ft in US customary units).
	const unit = lengthUnit(form);
	const height = (value: unknown) => {
		const text = specText(value);
		return text !== undefined && unit === 'ft' && Number(text) > 0 ? formatLengths([Number(text)], unit) : text;
	};
	const typical = height(spec.typicalHeight);
	return {
		...form,
		gridX: x ? formatLengths(x, unit) : form.gridX,
		gridY: y ? formatLengths(y, unit) : form.gridY,
		storyCount: stories ? String(stories.length) : specText(spec.storyCount) ?? form.storyCount,
		groundHeight: stories ? '' : height(spec.groundHeight) ?? typical ?? form.groundHeight,
		typicalHeight: stories ? '' : typical ?? form.typicalHeight,
		heights: stories ? formatLengths(stories, unit) : '',
		system: pick(spec.system, SYSTEM_CHOICES.map(c => c.value), form.system),
		concrete: pick(spec.concrete, undefined, form.concrete),
		rebar: pick(spec.rebar, undefined, form.rebar),
		footing: pick(spec.footing, FOOTING_CHOICES.map(c => c.value), form.footing),
		location: pick(spec.location, undefined, form.location),
		siteClass: pick(spec.siteClass, ['SA', 'SB', 'SC', 'SD', 'SE'] as const, form.siteClass),
		use: pick(spec.occupancy, undefined, form.use),
		category: pick(spec.occupancyCategory, ['I', 'II', 'III', 'IV'] as const, form.category),
	};
}

/** Limits the wizard checks, so a typo does not create a 600 m bay [mm]. */
const MIN_SPACING = 1000;
const MAX_SPACING = 30000;
const MIN_HEIGHT = 2000;
const MAX_HEIGHT = 12000;
const MAX_BAYS = 60;
const MAX_STORIES = 80;

export type ParseResult = { readonly ok: true; readonly values: readonly number[] } | { readonly ok: false; readonly error: string };

const UNIT_FACTORS: { readonly [unit: string]: number } = { '': 1, mm: 1, cm: 10, m: 1000, ft: 304.8, '\'': 304.8 };

/**
 * Lengths as engineers type them: comma, semicolon or space separated, each optionally repeated
 * ("3×6000", "3x6000", "3*6000") and optionally with a unit (mm by default; cm, m, ft or ').
 * "3×6000, 4500" is 6000, 6000, 6000, 4500 [mm].
 */
export function parseLengths(text: string, limits: { readonly min: number; readonly max: number; readonly maxCount: number }, unit: 'mm' | 'ft' = 'mm'): ParseResult {
	// "6 m" is one length: join a number and the unit after it before splitting on spaces.
	const normalized = text.trim().replace(/\s*[×xX*]\s*/g, '×').replace(/(?<digit>[\d.])\s+(?<unit>mm|cm|m|ft|')(?![a-z])/gi, '$<digit>$<unit>');
	if (!normalized) {
		return { ok: false, error: localize('lengths.empty', "Enter at least one length, e.g. 3×6000, 4500.") };
	}
	const values: number[] = [];
	for (const item of normalized.split(/[,;\s]+/).filter(Boolean)) {
		const groups = /^(?:(?<count>\d+)×)?(?<value>\d+(?:\.\d+)?|\.\d+)\s*(?<unit>mm|cm|m|ft|')?$/i.exec(item)?.groups;
		if (!groups) {
			return { ok: false, error: localize('lengths.bad', "\"{0}\" is not a length; write e.g. 6000, 3×6000 or 6m.", item) };
		}
		const count = groups.count === undefined ? 1 : Number(groups.count);
		// W4A-6: a length without a unit is in the form's unit (ft in US customary units).
		const factor = groups.unit ? UNIT_FACTORS[groups.unit.toLowerCase()] : UNIT_FACTORS[unit];
		const value = Math.round(Number(groups.value) * factor);
		if (count < 1) {
			return { ok: false, error: localize('lengths.count', "\"{0}\" repeats a length zero times.", item) };
		}
		if (value < limits.min || value > limits.max) {
			return {
				ok: false, error: unit === 'ft'
					? localize('lengths.rangeFt', "{0} ft is outside {1}–{2} ft (lengths are in ft unless they end in mm or m).", (value / 304.8).toFixed(1), (limits.min / 304.8).toFixed(1), (limits.max / 304.8).toFixed(1))
					: localize('lengths.range', "{0} mm is outside {1}–{2} mm (lengths are in mm unless they end in m or ft).", value, limits.min, limits.max)
			};
		}
		if (values.length + count > limits.maxCount) {
			return { ok: false, error: localize('lengths.tooMany', "At most {0} lengths.", limits.maxCount) };
		}
		for (let i = 0; i < count; i++) {
			values.push(value);
		}
	}
	return { ok: true, values };
}

/** Grid spacings (bays) along one axis [mm]. */
export function parseSpacings(text: string, unit: 'mm' | 'ft' = 'mm'): ParseResult {
	return parseLengths(text, { min: MIN_SPACING, max: MAX_SPACING, maxCount: MAX_BAYS }, unit);
}

/**
 * Lengths [mm] back in the shorthand: repeated neighbours as "3×6000"; in `unit` ft rounded to
 * the half foot ("3×20, 14.5").
 */
export function formatLengths(values: readonly number[], unit: 'mm' | 'ft' = 'mm'): string {
	const shown = unit === 'ft' ? values.map(v => String(Math.round(v / 304.8 * 2) / 2)) : values.map(v => String(v));
	const parts: string[] = [];
	for (let i = 0; i < shown.length;) {
		let j = i;
		while (j < shown.length && shown[j] === shown[i]) {
			j++;
		}
		parts.push(j - i > 1 ? `${j - i}×${shown[i]}` : shown[i]);
		i = j;
	}
	return parts.join(', ');
}

/** Bay spacings fitted to a plot are rounded to this [mm]. */
export const FIT_STEP = 50;

/**
 * `spacings` scaled to fill `room` [mm] with the same number of bays in the same proportions,
 * each a multiple of {@link FIT_STEP} and their sum the most that fits (the largest bays take
 * the rounding); undefined when the room is too small for that many bays.
 */
export function fitSpacings(spacings: readonly number[], room: number): number[] | undefined {
	const total = Math.floor(room / FIT_STEP) * FIT_STEP;
	const sum = spacings.reduce((a, b) => a + b, 0);
	if (!spacings.length || sum <= 0 || total < spacings.length * MIN_SPACING) {
		return undefined;
	}
	const fitted = spacings.map(s => Math.max(MIN_SPACING, Math.round(s * total / sum / FIT_STEP) * FIT_STEP));
	let rest = total - fitted.reduce((a, b) => a + b, 0);
	// The rounding goes to (or comes from) the largest bays first, a step at a time.
	const order = fitted.map((_, i) => i).sort((a, b) => spacings[b] - spacings[a] || a - b);
	for (let k = 0; rest !== 0 && k < 10 * fitted.length; k++) {
		const i = order[k % order.length];
		const step = rest > 0 ? FIT_STEP : -FIT_STEP;
		if (fitted[i] + step >= MIN_SPACING && fitted[i] + step <= MAX_SPACING) {
			fitted[i] += step;
			rest -= step;
		}
	}
	return rest === 0 && fitted.every(s => s <= MAX_SPACING) ? fitted : undefined;
}

/** The plot of the open project's soil report as the wizard draws it, in the grid's frame [mm]. */
export interface IWizardPlot {
	/** The project it is from. */
	readonly project: string;
	/** The room for the grid lines (inside the envelope, less the column allowance) [mm]. */
	readonly width: number;
	readonly depth: number;
	readonly plot: readonly (readonly number[])[];
	readonly envelope: readonly (readonly number[])[];
	/** The soil report's site, passed to the generator (which turns the grid along the plot). */
	readonly site: object;
}

/** Why the grid does not fit the plot's envelope (`x`, `y` total lengths [mm]), or undefined. */
export function plotFitWarning(x: readonly number[], y: readonly number[], plot: IWizardPlot): string | undefined {
	const lx = x.reduce((a, b) => a + b, 0);
	const ly = y.reduce((a, b) => a + b, 0);
	const over: string[] = [];
	if (lx > plot.width + 0.5) {
		over.push(localize('newBuilding.overX', "X by {0} m", ((lx - plot.width) / 1000).toFixed(2)));
	}
	if (ly > plot.depth + 0.5) {
		over.push(localize('newBuilding.overY', "Y by {0} m", ((ly - plot.depth) / 1000).toFixed(2)));
	}
	return over.length
		? localize('newBuilding.overPlot', "The grid is larger than the buildable area of the plot ({0} × {1} m): {2}. Use Fit to the Buildable Area or shorten the bays.", (plot.width / 1000).toFixed(2), (plot.depth / 1000).toFixed(2), over.join(', '))
		: undefined;
}

/** The grid lines of an axis from its spacings, the first at 0. */
export function gridLines(axis: 'x' | 'y', spacings: readonly number[]): IGridLine[] {
	const lines: IGridLine[] = [{ label: gridLabel(axis, 0), position: 0 }];
	let position = 0;
	spacings.forEach((spacing, i) => {
		position += spacing;
		lines.push({ label: gridLabel(axis, i + 1), position });
	});
	return lines;
}

function positiveInteger(text: string): number | undefined {
	const value = Number(text.trim());
	return Number.isInteger(value) && value > 0 ? value : undefined;
}

/** Storey heights from the list, or from the count, the ground storey's and the typical storey's height. */
export function storyHeights(form: Pick<INewBuildingForm, 'storyCount' | 'groundHeight' | 'typicalHeight' | 'heights' | 'units'>): ParseResult {
	const limits = { min: MIN_HEIGHT, max: MAX_HEIGHT, maxCount: MAX_STORIES };
	const unit = lengthUnit(form);
	if (form.heights.trim()) {
		return parseLengths(form.heights, limits, unit);
	}
	const count = positiveInteger(form.storyCount);
	if (count === undefined || count > MAX_STORIES) {
		return { ok: false, error: localize('stories.count', "Enter the number of storeys (1–{0}).", MAX_STORIES) };
	}
	const ground = parseLengths(form.groundHeight, { ...limits, maxCount: 1 }, unit);
	if (!ground.ok) {
		return ground;
	}
	if (count === 1) {
		return ground;
	}
	const typical = parseLengths(form.typicalHeight, { ...limits, maxCount: 1 }, unit);
	return typical.ok ? { ok: true, values: [ground.values[0], ...Array(count - 1).fill(typical.values[0])] } : typical;
}

/** The stories of the floor plan: the base at 0 and a level at the top of each storey. */
export function storiesFromHeights(heights: readonly number[]): IStorySpec[] {
	const stories: IStorySpec[] = [{ id: 'BASE', name: localize('story.base', "Base"), elevation: 0 }];
	let elevation = 0;
	heights.forEach((height, i) => {
		elevation += height;
		stories.push({ id: `L${i + 1}`, name: localize('story.level', "Level {0}", i + 1), elevation });
	});
	return stories;
}

/** Which field an error belongs to, so the wizard shows it there. */
export type FormField = 'name' | 'gridX' | 'gridY' | 'stories';

export type SpecResult =
	| { readonly ok: true; readonly spec: INewBuildingSpec }
	| { readonly ok: false; readonly errors: { readonly [field in FormField]?: string } };

/**
 * The specification of the form, or the errors by field. `validateName` is the project name
 * check of the New Project form (the folder name must be valid on Windows).
 */
export function buildSpec(form: INewBuildingForm, validateName: (name: string) => string | undefined): SpecResult {
	const errors: { [field in FormField]?: string } = {};
	const nameError = validateName(form.name);
	if (nameError) {
		errors.name = nameError;
	}
	const x = parseSpacings(form.gridX, lengthUnit(form));
	const y = parseSpacings(form.gridY, lengthUnit(form));
	const heights = storyHeights(form);
	if (!x.ok) {
		errors.gridX = x.error;
	}
	if (!y.ok) {
		errors.gridY = y.error;
	}
	if (!heights.ok) {
		errors.stories = heights.error;
	}
	if (!x.ok || !y.ok || !heights.ok || nameError) {
		return { ok: false, errors };
	}
	return {
		ok: true,
		spec: {
			schema: 'saengine.newBuilding/1',
			name: form.name.trim(),
			grids: { x: gridLines('x', x.values), y: gridLines('y', y.values) },
			spacings: { x: x.values, y: y.values },
			stories: storiesFromHeights(heights.values),
			storyHeights: heights.values,
			system: form.system,
			materials: { concrete: form.concrete, rebar: form.rebar },
			footing: form.footing,
			site: { location: form.location, siteClass: form.siteClass, siteClassSource: 'assumed' },
			occupancy: { use: form.use, category: form.category },
			...otherPackSite(form),
			...(form.units ? { units: form.units } : {}),
		},
	};
}

/**
 * The design code of the spec and, for a pack other than the default, its site values: Z and V
 * (Location: Custom in the project) and the exposure, where typed.
 */
function otherPackSite(form: INewBuildingForm): { designCode: string; site?: INewBuildingSpec['site']; wind?: { exposure: string } } {
	const code = form.designCode || DEFAULT_CODE_PACK_ID;
	if (code === DEFAULT_CODE_PACK_ID) {
		return { designCode: code };
	}
	const z = Number(form.zoneCoefficient);
	// W4A-6: a wind speed typed in mph (US customary units) goes to the project in m/s.
	const v = Number(form.windSpeed) * (form.units === 'USCustomary' ? MPH : 1);
	if (form.packTowns) {
		// C7: a pack with towns (IS): the town sets Z and V, the site class is one of the pack's.
		return {
			designCode: code,
			site: { location: form.location, siteClass: form.siteClass, siteClassSource: 'assumed' },
			...(form.exposure ? { wind: { exposure: form.exposure } } : {}),
		};
	}
	return {
		designCode: code,
		site: {
			location: 'custom', siteClass: form.siteClass, siteClassSource: 'assumed',
			...(form.zoneCoefficient.trim() && z > 0 && z < 1 ? { zoneCoefficient: z } : {}),
			...(form.windSpeed.trim() && v > 0 ? { windSpeed: v } : {}),
			...(spectralValues(form) ? { spectral: spectralValues(form) } : {}),
			...(form.hazard ? { hazardSource: form.hazard.source } : {}),
		},
		...(form.exposure ? { wind: { exposure: form.exposure } } : {}),
	};
}

/** One line about the building, under the preview. */
export interface IBuildingSummary {
	readonly baysX: number;
	readonly baysY: number;
	/** Plan size [mm]. */
	readonly lengthX: number;
	readonly lengthY: number;
	readonly storeys: number;
	/** Height of the roof above the base [mm]. */
	readonly height: number;
	readonly columnsPerFloor: number;
}

export function summarize(x: readonly number[], y: readonly number[], heights: readonly number[]): IBuildingSummary {
	const sum = (values: readonly number[]) => values.reduce((a, b) => a + b, 0);
	return {
		baysX: x.length,
		baysY: y.length,
		lengthX: sum(x),
		lengthY: sum(y),
		storeys: heights.length,
		height: sum(heights),
		columnsPerFloor: (x.length + 1) * (y.length + 1),
	};
}

export function formatSummary(summary: IBuildingSummary, units: UnitSystem = 'SI'): string {
	if (units === 'USCustomary') {
		const ft = (mm: number) => (mm / 304.8).toFixed(1);
		return localize('summaryFt', "{0} × {1} bays · {2} ft × {3} ft · {4} storeys, {5} ft · {6} columns a floor",
			summary.baysX, summary.baysY, ft(summary.lengthX), ft(summary.lengthY), summary.storeys, ft(summary.height), summary.columnsPerFloor);
	}
	const m = (mm: number) => (mm / 1000).toFixed(1);
	return localize('summary', "{0} × {1} bays · {2} m × {3} m · {4} storeys, {5} m · {6} columns a floor",
		summary.baysX, summary.baysY, m(summary.lengthX), m(summary.lengthY), summary.storeys, m(summary.height), summary.columnsPerFloor);
}

/** The bay of each axis nearest the middle, where the core walls of 'rcFrameCore' go in the preview. */
export function centralBay(spacings: readonly number[]): number {
	const total = spacings.reduce((a, b) => a + b, 0);
	let start = 0;
	for (let i = 0; i < spacings.length; i++) {
		if (start + spacings[i] >= total / 2) {
			return i;
		}
		start += spacings[i];
	}
	return Math.max(0, spacings.length - 1);
}

/**
 * Why `folder` cannot hold a new project, or undefined. It must be a full path: a relative one,
 * or a Windows drive-relative one ("C:Users") or rooted one without a drive ("\Users"), would
 * resolve against the folder the app runs in. Whether it exists is checked separately.
 */
export function folderError(folder: string, windows: boolean): string | undefined {
	const path = folder.trim();
	if (!path) {
		return localize('folder.empty', "Choose the folder the project goes in.");
	}
	const absolute = windows
		? /^[a-zA-Z]:[\\/]/.test(path) || /^[\\/]{2}[^\\/]+[\\/][^\\/]+/.test(path)
		: path.startsWith('/');
	if (!absolute) {
		return windows
			? localize('folder.relativeWindows', "Enter the full path of a folder, starting with the drive, e.g. C:\\Users\\you\\Documents.")
			: localize('folder.relative', "Enter the full path of a folder, starting with /.");
	}
	if (windows && /[<>"|?*]/.test(path.slice(2))) {
		return localize('folder.invalid', "A folder path cannot contain < > \" | ? or *.");
	}
	return undefined;
}

/** One row of the sizes table of the result page. */
export interface IGeneratedSize {
	readonly what: string;
	readonly size: string;
	/** What governed the size (columns only): gravity, drift, wind and earthquake, transition. */
	readonly why?: string;
}

/** What the generator built, as the result page shows it (from its `summary`). */
export interface IGenerateSummary {
	/** Seismic design category, when the generator gave it. */
	readonly sdc?: string;
	/** Member counts: [label, count]. */
	readonly counts: readonly (readonly [string, number])[];
	readonly sizes: readonly IGeneratedSize[];
	/** What the engineer should see first: drift not met, overlapping footings. */
	readonly warnings: readonly string[];
	/** The frame failed the drift without walls: core walls would help. */
	readonly suggestCoreWalls: boolean;
}

/** What the generator answered: the new project's folder and its notes, or why it failed. */
export interface IGenerateOutcome {
	readonly root?: string;
	readonly notes: readonly string[];
	readonly summary?: IGenerateSummary;
	readonly error?: string;
}

const COUNT_LABELS: readonly (readonly [string, string])[] = [
	['columns', localize('count.columns', "Columns")],
	['beams', localize('count.beams', "Beams")],
	['walls', localize('count.walls', "Walls")],
	['slabs', localize('count.slabs', "Slabs")],
	['foundations', localize('count.foundations', "Footings")],
];

/** The generator's `summary` (counts and the types it chose), read defensively. */
export function readGenerateSummary(value: unknown): IGenerateSummary | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const record = value as { readonly [key: string]: unknown };
	const counts = (typeof record.counts === 'object' && record.counts !== null ? record.counts : {}) as { readonly [key: string]: unknown };
	const sizes: IGeneratedSize[] = [];
	const columnTypes = typeof record.columnTypes === 'object' && record.columnTypes !== null ? record.columnTypes as { readonly [key: string]: unknown } : {};
	const reasons = typeof record.columnReasons === 'object' && record.columnReasons !== null ? record.columnReasons as { readonly [key: string]: unknown } : {};
	for (const [what, size] of Object.entries(columnTypes)) {
		if (typeof size === 'string') {
			const why = reasons[what];
			sizes.push({ what: localize('size.columns', "Columns {0}", what), size, why: typeof why === 'string' ? why : localize('size.gravity', "gravity: axial load") });
		}
	}
	for (const [key, label] of [['beamTypes', localize('size.beams', "Beams")], ['wallTypes', localize('size.walls', "Walls")], ['slabTypes', localize('size.slabs', "Slabs")], ['footingTypes', localize('size.footings', "Footings")]] as const) {
		const types = Array.isArray(record[key]) ? (record[key] as unknown[]).filter((t): t is string => typeof t === 'string') : [];
		if (types.length) {
			sizes.push({ what: label, size: types.join(', ') });
		}
	}
	return {
		sdc: typeof record.sdc === 'string' ? record.sdc : undefined,
		counts: COUNT_LABELS.map(([key, label]) => [label, Number(counts[key]) || 0] as const).filter(([, n]) => n > 0),
		sizes,
		warnings: Array.isArray(record.warnings) ? record.warnings.filter((w): w is string => typeof w === 'string') : [],
		suggestCoreWalls: record.suggestCoreWalls === true,
	};
}

function noteText(note: unknown): string | undefined {
	if (typeof note === 'string') {
		return note;
	}
	if (typeof note === 'object' && note !== null) {
		const record = note as { readonly [key: string]: unknown };
		const text = record.text ?? record.message ?? record.note;
		if (typeof text === 'string') {
			return typeof record.rule === 'string' ? `${text} (${record.rule})` : text;
		}
	}
	return undefined;
}

/** The generator's answer `{root, notes}` (root a path or a URI's JSON; notes strings or `{text, rule}`), read defensively. */
export function readGenerateResult(value: unknown): IGenerateOutcome {
	if (typeof value !== 'object' || value === null) {
		return { notes: [], error: localize('generate.noAnswer', "The generator gave no answer.") };
	}
	const record = value as { readonly [key: string]: unknown };
	const notes = (Array.isArray(record.notes) ? record.notes : []).map(noteText).filter((n): n is string => !!n);
	const rawRoot = record.root;
	const root = typeof rawRoot === 'string' ? rawRoot
		: typeof rawRoot === 'object' && rawRoot !== null && typeof (rawRoot as { fsPath?: unknown }).fsPath === 'string' ? (rawRoot as { fsPath: string }).fsPath
			: typeof rawRoot === 'object' && rawRoot !== null && typeof (rawRoot as { path?: unknown }).path === 'string' ? (rawRoot as { path: string }).path
				: undefined;
	if (typeof record.error === 'string' && record.error) {
		return { notes, error: record.error };
	}
	const summary = readGenerateSummary(record.summary);
	return root ? { root, notes, ...(summary ? { summary } : {}) } : { notes, error: localize('generate.noRoot', "The generator did not say where it wrote the project.") };
}

/** The building just generated, stored until its window opens. */
export interface IPendingBuilding {
	readonly root: string;
	readonly notes: readonly string[];
	readonly time: number;
}

export function readPendingBuilding(raw: string | undefined): IPendingBuilding | undefined {
	try {
		const value = raw ? JSON.parse(raw) : undefined;
		return value && typeof value.root === 'string' && Array.isArray(value.notes)
			? { root: value.root, notes: value.notes.filter((n: unknown) => typeof n === 'string'), time: Number(value.time) || 0 }
			: undefined;
	} catch {
		return undefined;
	}
}
