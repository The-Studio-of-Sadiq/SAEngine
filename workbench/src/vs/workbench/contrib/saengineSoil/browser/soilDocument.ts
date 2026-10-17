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

export interface ISptRecord {
	depth: number;
	N: number;
	energyRatio?: number;
	[key: string]: unknown;
}

export interface ISoilSample {
	depth: number;
	type?: string;
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
	[key: string]: unknown;
}

export interface IBorehole {
	id: string;
	x: number;
	y: number;
	groundLevel?: number;
	waterTable?: number;
	depth?: number;
	layers: ISoilLayer[];
	spt: ISptRecord[];
	samples: ISoilSample[];
	[key: string]: unknown;
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
}

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
}

export interface IBearingResult {
	readonly method?: string;
	readonly cells: readonly IBearingCell[];
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
	/** The project's: the governing borehole's id. */
	readonly governing?: Maybe<string>;
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
		readonly ksDetail?: { readonly B?: Maybe<number>; readonly Df?: Maybe<number>; readonly method?: Maybe<string>; readonly note?: Maybe<string> };
		readonly pile?: readonly { readonly top: number; readonly bottom: number; readonly soilType?: Maybe<string>; readonly fs?: Maybe<number>; readonly qb?: Maybe<number>; readonly method?: Maybe<string>; readonly note?: Maybe<string> }[];
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
export function readSoilResults(raw: unknown): ISoilResults | undefined {
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
			siteClass: site && str(site.class) ? { class: str(site.class)!, nBar: num(site.N) ?? null, suBar: num(site.su) ?? null, depth: num(site.depth), note: str(site.note) } : undefined,
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
			piles: list(b.pile).filter(isRecord).map(p => ({ top: p.top, bottom: p.bottom, soilType: str(p.soilType), fs: num(p.fs) ?? null, qb: num(p.qb) ?? null, method: str(p.method) ?? null, note: str(p.note) ?? null })),
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

	// The project's table: for each footing size the lowest qa of the boreholes.
	const envelope = new Map<string, IBearingCell>();
	for (const borehole of boreholes) {
		for (const cell of borehole.bearing?.cells ?? []) {
			const key = `${cell.B}|${cell.Df}`;
			const current = envelope.get(key);
			if (!current || current.qa !== null && (cell.qa === null || cell.qa < current.qa)) {
				envelope.set(key, cell);
			}
		}
	}
	const cells = [...envelope.values()];
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
		} : undefined,
		boreholes,
		bearing: cells.length ? { method: bearingMethod, cells, governing: referenceCell(cells, reference) } : undefined,
		pga: num(backend.amax),
		pgaSource: amaxNote,
		practice: str(backend.practice) ?? str(isRecord(backend.design) ? backend.design.practice : undefined),
		liquefactionMethod: str(backend.liquefactionMethod) ?? str(isRecord(backend.design) ? backend.design.liquefactionMethod : undefined),
		sptMethod: str(backend.methods?.spt),
		siteClassFlags: readFlags(backend),
		permissibleSettlement: permissible?.value,
		permissibleSettlementSource: permissible?.source,
		problems: strings(backend.problems),
		notes: strings(backend.notes),
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

/** A new borehole beside the last one, 10 m deep, one layer, no records. */
export function newBorehole(report: ISoilReport): IBorehole {
	const last = report.boreholes[report.boreholes.length - 1];
	return {
		id: nextBoreholeId(report),
		x: last ? last.x + 10000 : 0,
		y: last ? last.y : 0,
		waterTable: last?.waterTable,
		depth: 10000,
		layers: [{ top: 0, bottom: 10000, description: '', soilType: 'clay' }],
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
	return typeof value === 'number' ? formatNumber(value, 4) : String(value);
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

/** The checks the editor makes while typing (the backend checks the rest). */
export function checkSoilReport(report: ISoilReport): ISoilProblem[] {
	const problems: ISoilProblem[] = [];
	const seen = new Set<string>();
	report.boreholes.forEach((borehole, boreholeIndex) => {
		const problem = (p: Omit<ISoilProblem, 'index'>) => problems.push({ ...p, index: boreholeIndex });
		const id = String(borehole.id ?? '');
		if (!id) {
			problem({ message: localize('soil.p.noId', "A borehole has no id."), severity: 'error' });
		} else if (seen.has(id)) {
			problem({ borehole: id, path: 'id', message: localize('soil.p.duplicateId', "Two boreholes are called {0}.", id), severity: 'error' });
		}
		seen.add(id);
		const layers = [...borehole.layers].map((layer, index) => ({ layer, index })).sort((a, b) => a.layer.top - b.layer.top);
		let previousBottom = 0;
		layers.forEach(({ layer, index }, order) => {
			if (!(layer.bottom > layer.top)) {
				problem({ borehole: id, path: `layers.${index}.bottom`, message: localize('soil.p.layerThickness', "{0}: layer {1} ends at or above its top.", id, index + 1), severity: 'error' });
			}
			if (order === 0 && layer.top > 0) {
				problem({ borehole: id, path: `layers.${index}.top`, message: localize('soil.p.firstLayer', "{0}: the first layer starts below the ground ({1} m).", id, formatNumber(layer.top / 1000)), severity: 'warning' });
			} else if (order > 0 && Math.abs(layer.top - previousBottom) > 1) {
				problem({
					borehole: id, path: `layers.${index}.top`, severity: 'warning', message: layer.top > previousBottom
						? localize('soil.p.gap', "{0}: a gap between {1} m and {2} m.", id, formatNumber(previousBottom / 1000), formatNumber(layer.top / 1000))
						: localize('soil.p.overlap', "{0}: layers overlap between {1} m and {2} m.", id, formatNumber(layer.top / 1000), formatNumber(previousBottom / 1000)),
				});
			}
			previousBottom = Math.max(previousBottom, layer.bottom);
		});
		if (typeof borehole.depth === 'number') {
			borehole.spt.forEach((record, index) => {
				if (record.depth > borehole.depth! + 1) {
					problem({ borehole: id, path: `spt.${index}.depth`, message: localize('soil.p.sptBelow', "{0}: an SPT at {1} m is below the termination depth.", id, formatNumber(record.depth / 1000)), severity: 'warning' });
				}
			});
		}
		const sptDepths = new Set<number>();
		borehole.spt.forEach((record, index) => {
			if (sptDepths.has(record.depth)) {
				problem({ borehole: id, path: `spt.${index}.depth`, message: localize('soil.p.sptTwice', "{0}: two SPT records at {1} m.", id, formatNumber(record.depth / 1000)), severity: 'warning' });
			}
			sptDepths.add(record.depth);
		});
		if (!borehole.layers.length) {
			problem({ borehole: id, message: localize('soil.p.noLayers', "{0} has no layers yet.", id), severity: 'warning' });
		}
	});
	return problems;
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
