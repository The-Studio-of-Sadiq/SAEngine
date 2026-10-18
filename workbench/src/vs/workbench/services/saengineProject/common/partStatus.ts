/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { localize } from '../../../../nls.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { boqSourceStamp, mepModelStamp, recordedStamp, sourceStamp, upstreamPart } from './partSources.js';
import { IProjectPart } from './saengineProject.js';

/*
 * How far each part of a project has got, from its files on disk: not started (a placeholder
 * or missing file), in progress, done, stale (an upstream part changed since this part was
 * produced), failed (the design checks found failing members) or error (an unreadable file).
 */

export type PartState = 'notStarted' | 'inProgress' | 'done' | 'stale' | 'failed' | 'error';

export interface IPartStatus {
	/** Id of the part (see `PROJECT_PARTS`). */
	readonly part: string;
	readonly state: PartState;
	/** A few words for the sidebar ("not derived", "3 fail", "report 16 Oct"); may be empty. */
	readonly text: string;
	/** What to do next in this part, when it is not done ("run the analysis"). */
	readonly hint?: string;
}

/** The design checks' summary, `08 FEM/model.results/design-summary.json`. */
export interface IDesignSummary {
	readonly checked: number;
	readonly passed: number;
	readonly failed: number;
	readonly maxUtilisation: number | null;
	readonly governing: string | null;
	readonly computed: string;
}

/** What the rules read from a project. Times are modification times [ms since the epoch]. */
export interface IPartStatusInputs {
	/** Text of each part's main file by part id; undefined when the file is missing. */
	readonly texts: ReadonlyMap<string, string | undefined>;
	/** Modification time of `08 FEM/model.osmodel`. */
	readonly femModelTime?: number;
	/** Modification time of the analysis results, `08 FEM/model.results/manifest.json`; undefined before a run. */
	readonly femResultsTime?: number;
	/** Text of `08 FEM/model.results/design-summary.json`, if the design checks ran. */
	readonly designSummaryText?: string;
	/** Modification time of `design-summary.json`. */
	readonly designSummaryTime?: number;
	/** Modification time of `11 Exports/report.pdf`, if it exists. */
	readonly reportTime?: number;
	/** How many other exports `11 Exports` holds (IFC, DXF floor plans, CSV); 0 or undefined for none. */
	readonly exportFiles?: number;
	/** Text of `09 Substructure/substructure.results/summary.json`, if the foundations were checked. */
	readonly substructureSummaryText?: string;
	/** Modification time of that summary. */
	readonly substructureSummaryTime?: number;
	/** Modification time of `09 Substructure/substructure.json`. */
	readonly substructureTime?: number;
	/** Text of `07 MEP/mep.results/summary.json`, if the MEP checks ran. */
	readonly mepSummaryText?: string;
	/** Modification time of that summary. */
	readonly mepSummaryTime?: number;
}

/** File names the status reads besides the parts' main files. */
export const FEM_RESULTS_FOLDER = 'model.results';
export const FEM_RESULTS_MANIFEST = 'manifest.json';
export const DESIGN_SUMMARY_FILE = 'design-summary.json';
export const REPORT_FILE = 'report.pdf';
/** The foundation checks' summary the Substructure editor and Run All write beside `substructure.json`. */
export const SUBSTRUCTURE_SUMMARY_FILE = 'substructure.results/summary.json';
/** The MEP coordination summary the MEP editor and Run All write beside `mep.json`. */
export const MEP_SUMMARY_FILE = 'mep.results/summary.json';

/** Where the exports of `11 Exports` go besides the report: IFC models and DXF floor plans in folders, CSV tables at the top. */
export const EXPORT_IFC_FOLDER = 'IFC';
export const EXPORT_DXF_FOLDER = 'Floor Plan';

/** The export kind of a file of `11 Exports` from its path inside that folder, if it is one. */
export function exportKind(relativePath: string): 'report' | 'ifc' | 'dxf' | 'csv' | undefined {
	const path = relativePath.replace(/\\/g, '/');
	const lower = path.toLowerCase();
	if (lower === REPORT_FILE) {
		return 'report';
	}
	if (lower.startsWith(`${EXPORT_IFC_FOLDER.toLowerCase()}/`) && lower.endsWith('.ifc')) {
		return 'ifc';
	}
	if (lower.startsWith(`${EXPORT_DXF_FOLDER.toLowerCase()}/`) && lower.endsWith('.dxf')) {
		return 'dxf';
	}
	if (!path.includes('/') && lower.endsWith('.csv')) {
		return 'csv';
	}
	return undefined;
}

/**
 * Parts that never block the next step: the soil report is optional (without boreholes the
 * settings' site class and qa apply), MEP and the substructure are not written yet.
 */
const OPTIONAL_PARTS = new Set(['soil', 'mep', 'substructure']);

/** The parts the analysis model is derived from, by the keys its description records them under. */
const FEM_SOURCES = ['bim', 'settings', 'objects', 'materials'];

/** The parts the bill of quantities is measured from (the substructure and MEP: once the bill records them). */
const BOQ_SOURCES = ['bim', 'objects', 'materials'];
const BOQ_RECORDED_SOURCES = ['substructure', 'settings', 'mep'];

const MEP_SCHEMA_ID = 'saengine.mep/1';

const SUBSTRUCTURE_SCHEMA_ID = 'saengine.substructure/1';

const BOQ_SCHEMA_ID = 'saengine.boq/1';

const SOIL_SCHEMA_ID = 'saengine.soilReport/1';

/** The key a derived analysis model records the soil report's stamp under, when its settings take the site class from it. */
const FEM_SOIL_SOURCE = 'soil';
/** Sources an analysis model records only when they give it something: soil springs' foundations, MEP's loads and holes. */
const FEM_RECORDED_SOURCES = ['substructure', 'mep'];

/** The stamp an analysis model records for source part `part`: of what it takes for MEP, the whole file's otherwise. */
function femSourceStamp(part: string, text: string): string {
	return part === 'mep' ? mepModelStamp(text) : sourceStamp(text);
}

type JsonObject = { readonly [key: string]: unknown };

function parse(text: string): JsonObject | undefined {
	try {
		const value = JSON.parse(text);
		return typeof value === 'object' && value !== null && !Array.isArray(value) ? value : undefined;
	} catch {
		return undefined;
	}
}

/** True for the stub a new project starts with in parts that are not implemented yet. */
export function isPlaceholder(document: JsonObject, part: string): boolean {
	const keys = Object.keys(document);
	return document.part === part && keys.every(key => key === 'schema' || key === 'part');
}

/** The source stamps a derived analysis model records in `meta.description` ("Sources: bim=…; settings=…"). */
export function femRecordedSources(model: JsonObject): Map<string, string> {
	const sources = new Map<string, string>();
	const meta = model.meta as JsonObject | undefined;
	const description = typeof meta === 'object' && meta !== null ? meta.description : undefined;
	const match = typeof description === 'string' ? /Sources: (?<list>.*)$/.exec(description) : null;
	for (const entry of match?.groups?.list.split(';') ?? []) {
		const [key, value] = entry.trim().split('=');
		if (key && value) {
			sources.set(key, value);
		}
	}
	return sources;
}

function changed(texts: ReadonlyMap<string, string | undefined>, part: string, recorded: string | undefined, stamp: (part: string, text: string) => string = (_part, text) => sourceStamp(text)): boolean {
	const text = texts.get(part);
	return text === undefined || recorded !== stamp(part, text);
}

function status(part: string, state: PartState, text = '', hint?: string): IPartStatus {
	return { part, state, text, hint };
}

const NOT_STARTED = () => localize('partStatus.notStarted', "not started");
const STALE = () => localize('partStatus.stale', "stale");

function parseDesignSummary(text: string | undefined): IDesignSummary | undefined {
	const value = text !== undefined ? parse(text) : undefined;
	return value && typeof value.checked === 'number' && typeof value.passed === 'number' && typeof value.failed === 'number' ? value as unknown as IDesignSummary : undefined;
}

function femStatus(inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get('fem');
	const model = text !== undefined ? parse(text) : undefined;
	if (text === undefined) {
		return status('fem', 'notStarted', localize('partStatus.fem.notDerived', "not derived"), localize('partStatus.fem.derive', "derive the analysis model"));
	}
	if (!model) {
		return status('fem', 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.fem.deriveInvalid', "derive the analysis model again"));
	}
	const recorded = femRecordedSources(model);
	if (!recorded.size) {
		return status('fem', 'notStarted', localize('partStatus.fem.notDerived', "not derived"), localize('partStatus.fem.derive', "derive the analysis model"));
	}
	// The soil report counts as a source only when the model recorded it: the settings take the
	// site class from it (also while it gives none yet, so boreholes added later count).
	const soilChanged = recorded.has(FEM_SOIL_SOURCE) && changed(inputs.texts, 'soil', recorded.get(FEM_SOIL_SOURCE));
	// The substructure and MEP likewise; MEP also when it has content a model without it lacks.
	const recordedChanged = FEM_RECORDED_SOURCES.some(part => recorded.has(part) && changed(inputs.texts, part, recorded.get(part), femSourceStamp));
	const mepAdded = !recorded.has('mep') && mepHasContent(inputs);
	if (soilChanged || recordedChanged || mepAdded || FEM_SOURCES.some(part => changed(inputs.texts, part, recorded.get(part)))) {
		return status('fem', 'stale', STALE(), localize('partStatus.fem.deriveAgain', "derive the analysis model again"));
	}
	if (inputs.femResultsTime === undefined) {
		return status('fem', 'inProgress', localize('partStatus.fem.notAnalysed', "not analysed"), localize('partStatus.fem.run', "run the analysis"));
	}
	if (inputs.femModelTime !== undefined && inputs.femModelTime > inputs.femResultsTime) {
		return status('fem', 'stale', STALE(), localize('partStatus.fem.runAgain', "run the analysis again"));
	}
	const summary = parseDesignSummary(inputs.designSummaryText);
	if (!summary || (inputs.designSummaryTime !== undefined && inputs.designSummaryTime < inputs.femResultsTime)) {
		return status('fem', 'done', localize('partStatus.fem.analysed', "analysed"));
	}
	if (summary.failed > 0) {
		return status('fem', 'failed', localize('partStatus.fem.fail', "{0} fail", summary.failed), localize('partStatus.fem.review', "review the failing members"));
	}
	return status('fem', 'done', localize('partStatus.fem.pass', "{0} pass", summary.passed));
}

function boqStatus(inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get('boq');
	const document = text !== undefined ? parse(text) : undefined;
	if (text !== undefined && !document) {
		return status('boq', 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.boq.measureInvalid', "measure the quantities again"));
	}
	if (!document || document.schema !== BOQ_SCHEMA_ID) {
		return status('boq', 'notStarted', localize('partStatus.boq.notMeasured', "not measured"), localize('partStatus.boq.measure', "measure the quantities"));
	}
	// The substructure and the settings count once the bill was measured with them (bills from
	// before Part 9 do not record them; Run All measures them again). Of the settings only the
	// ground level counts: the earthwork is dug from it, and nothing else in the bill reads them.
	const recorded = (part: string) => recordedStamp(document, part) !== undefined;
	if (BOQ_SOURCES.some(part => changed(inputs.texts, part, recordedStamp(document, part)))
		|| BOQ_RECORDED_SOURCES.some(part => recorded(part) && changed(inputs.texts, part, recordedStamp(document, part), boqSourceStamp))
		|| (!recorded('substructure') && substructureHasFoundations(inputs))
		|| (!recorded('mep') && mepHasContent(inputs))) {
		return status('boq', 'stale', STALE(), localize('partStatus.boq.measureAgain', "measure the quantities again"));
	}
	return status('boq', 'done', localize('partStatus.boq.measured', "measured"));
}

function bimStatus(parts: readonly IProjectPart[], inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get('bim');
	const document = text !== undefined ? parse(text) : undefined;
	if (text !== undefined && !document) {
		return status('bim', 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.bim.buildInvalid', "build the building model again"));
	}
	const upstream = upstreamPart('bim', parts);
	const recorded = document && upstream ? recordedStamp(document, upstream) : undefined;
	if (!document || !recorded) {
		return status('bim', 'notStarted', localize('partStatus.bim.notBuilt', "not built"), localize('partStatus.bim.build', "build the building model"));
	}
	if (upstream && changed(inputs.texts, upstream, recorded)) {
		return status('bim', 'stale', STALE(), localize('partStatus.bim.buildAgain', "build the building model again"));
	}
	return status('bim', 'done');
}

/**
 * Part 1: not started while the soil report is the placeholder of a new project or has no
 * boreholes; in progress while a borehole has no layers; done with the number of boreholes.
 */
function soilStatus(inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get('soil');
	const document = text !== undefined ? parse(text) : undefined;
	if (text === undefined || (document && isPlaceholder(document, 'soil'))) {
		return status('soil', 'notStarted', NOT_STARTED(), startHint('soil'));
	}
	if (!document || document.schema !== SOIL_SCHEMA_ID) {
		return status('soil', 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.fix', "fix the file"));
	}
	const boreholes = Array.isArray(document.boreholes) ? document.boreholes : [];
	if (!boreholes.length) {
		return status('soil', 'notStarted', NOT_STARTED(), localize('partStatus.soil.addBorehole', "add the boreholes"));
	}
	const count = boreholes.length === 1 ? localize('partStatus.soil.oneBorehole', "1 borehole") : localize('partStatus.soil.boreholes', "{0} boreholes", boreholes.length);
	const logged = (b: unknown) => typeof b === 'object' && b !== null && Array.isArray((b as JsonObject).layers) && ((b as JsonObject).layers as unknown[]).length > 0;
	if (!boreholes.every(logged)) {
		return status('soil', 'inProgress', count, localize('partStatus.soil.layers', "enter the layers of every borehole"));
	}
	return status('soil', 'done', count);
}

/** The MEP file of 7 MEP, parsed, when it is one (not the placeholder). */
function mepDocument(inputs: IPartStatusInputs): JsonObject | undefined {
	const text = inputs.texts.get('mep');
	const document = text !== undefined ? parse(text) : undefined;
	return document && document.schema === MEP_SCHEMA_ID ? document : undefined;
}

/** The plumbing section of an MEP file, when it has one. */
function plumbingSection(document: JsonObject): JsonObject | undefined {
	const plumbing = document.plumbing;
	return typeof plumbing === 'object' && plumbing !== null && !Array.isArray(plumbing) ? plumbing as JsonObject : undefined;
}

/** Whether the plumbing of an MEP file has an overhead tank (its weight loads the analysis model). */
function hasOverheadTank(document: JsonObject): boolean {
	const tanks = plumbingSection(document)?.tanks;
	return Array.isArray(tanks) && tanks.some(t => typeof t === 'object' && t !== null && (t as JsonObject).kind === 'overhead');
}

/** A section of an MEP file (`hvac`, `electrical`), when it has one. */
function mepSection(document: JsonObject, key: string): JsonObject | undefined {
	const section = document[key];
	return typeof section === 'object' && section !== null && !Array.isArray(section) ? section as JsonObject : undefined;
}

/** How many entries the lists `keys` of an MEP file's section `key` have together. */
function sectionCount(document: JsonObject, key: string, keys: readonly string[]): number {
	const section = mepSection(document, key);
	return section ? keys.reduce((sum, k) => sum + (Array.isArray(section[k]) ? (section[k] as unknown[]).length : 0), 0) : 0;
}

/** How many storeys, plant items and ducts the HVAC of an MEP file has. */
function hvacCount(document: JsonObject): number {
	return sectionCount(document, 'hvac', ['stories', 'plant', 'ducts']);
}

/** How many storeys, equipment, risers and trays the electrical services of an MEP file have. */
function electricalCount(document: JsonObject): number {
	return sectionCount(document, 'electrical', ['stories', 'equipment', 'risers', 'trays']);
}

/** Whether 7 MEP has anything for the analysis model or the bill: equipment, openings, shafts, an overhead plumbing tank, HVAC plant or electrical equipment. */
function mepHasContent(inputs: IPartStatusInputs): boolean {
	const document = mepDocument(inputs);
	return !!document && (['equipment', 'openings', 'shafts'].some(key => Array.isArray(document[key]) && (document[key] as unknown[]).length > 0) || hasOverheadTank(document)
		|| sectionCount(document, 'hvac', ['plant']) > 0 || sectionCount(document, 'electrical', ['equipment']) > 0);
}

/** How many storeys, risers, tanks and roof drains the plumbing of an MEP file has. */
function plumbingCount(document: JsonObject): number {
	const plumbing = plumbingSection(document);
	if (!plumbing) {
		return 0;
	}
	const length = (value: unknown) => Array.isArray(value) ? value.length : 0;
	const roof = plumbing.roof;
	const drains = typeof roof === 'object' && roof !== null && !Array.isArray(roof) ? (roof as JsonObject).drains : undefined;
	return length(plumbing.stories) + length(plumbing.risers) + length(plumbing.tanks) + length(drains);
}

/** The plumbing checks' part of the MEP summary (the MEP editor and Run All write it). */
interface IPlumbingSummary {
	readonly risers: number;
	readonly tanks: number;
	readonly failed: number;
	readonly floorsLow: number;
	/** The stamps of the files the plumbing results read beyond the MEP summary's own: the soil report ("" for a missing file). */
	readonly source?: { readonly [part: string]: unknown };
}

/** The MEP checks' summary (see {@link MEP_SUMMARY_FILE}). */
interface IMepSummary {
	readonly equipment: number;
	readonly openings: number;
	readonly openingsFailed: number;
	readonly clashes: number;
	readonly clashesOpen: number;
	/** Openings whose strength checks did not run (only their size and spacing were checked). */
	readonly openingsPartial?: number;
	/** The stamp of each part file the checks read, by part id ("" for a missing file). */
	readonly source?: { readonly [part: string]: unknown };
	/** The plumbing checks, when the file has plumbing and they ran. */
	readonly plumbing?: IPlumbingSummary;
	/** The HVAC checks (ducts, shafts, openings, plant), when the file has HVAC and they ran. */
	readonly hvac?: IServiceSummary;
	/** The electrical checks (supply, rooms, risers, trays, lightning), when the file has them and they ran. */
	readonly electrical?: IServiceSummary;
}

/** The HVAC or electrical checks' part of the MEP summary (the MEP editor and Run All write it). */
interface IServiceSummary {
	readonly failed: number;
}

/**
 * Part 7: not started while the file is missing, the placeholder, or has no equipment, openings,
 * shafts, IFC models, plumbing (storeys, risers, tanks, roof drains), HVAC (storeys, plant,
 * ducts) or electrical services (storeys, equipment, risers, trays); in progress until the
 * checks' summary is newer than the analysis results with every part file it read unchanged;
 * then failed when an opening, a plumbing, HVAC or electrical check fails or a floor is below
 * the minimum pressure, in progress while the plumbing, HVAC or electrical services are not
 * checked, clashes are open or openings are only partly checked, done otherwise.
 */
function mepStatus(inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get('mep');
	const value = text !== undefined ? parse(text) : undefined;
	if (text === undefined || (value && isPlaceholder(value, 'mep'))) {
		return status('mep', 'notStarted', NOT_STARTED(), startHint('mep'));
	}
	if (!value || value.schema !== MEP_SCHEMA_ID) {
		return status('mep', 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.fix', "fix the file"));
	}
	const count = (key: string) => Array.isArray(value[key]) ? (value[key] as unknown[]).length : 0;
	const plumbingItems = plumbingCount(value);
	const hvacItems = hvacCount(value);
	const electricalItems = electricalCount(value);
	if (!count('equipment') && !count('openings') && !count('shafts') && !count('ifcModels') && !plumbingItems && !hvacItems && !electricalItems) {
		return status('mep', 'notStarted', NOT_STARTED(), startHint('mep'));
	}
	const parsed = inputs.mepSummaryText !== undefined ? parse(inputs.mepSummaryText) : undefined;
	const summary = parsed && typeof parsed.openingsFailed === 'number' && typeof parsed.clashesOpen === 'number' ? parsed as unknown as IMepSummary : undefined;
	const source = summary && typeof summary.source === 'object' && summary.source !== null ? summary.source : undefined;
	const time = inputs.mepSummaryTime;
	const current = !!summary && !!source && time !== undefined && sourcesUnchanged(inputs.texts, source)
		&& (inputs.femResultsTime === undefined || time >= inputs.femResultsTime);
	if (!current || !summary) {
		return status('mep', 'inProgress', localize('partStatus.mep.notChecked', "not checked"), localize('partStatus.mep.check', "check the openings and clashes"));
	}
	const recorded = typeof summary.plumbing === 'object' && summary.plumbing !== null && typeof summary.plumbing.failed === 'number' ? summary.plumbing : undefined;
	// The plumbing results also read the soil report (soak well, flotation, bearing, ground tanks):
	// once it has changed they are stale.
	const plumbing = recorded && (typeof recorded.source !== 'object' || recorded.source === null || sourcesUnchanged(inputs.texts, recorded.source)) ? recorded : undefined;
	const service = (key: 'hvac' | 'electrical') => {
		const recorded = summary[key];
		return typeof recorded === 'object' && recorded !== null && typeof recorded.failed === 'number' ? recorded : undefined;
	};
	const hvac = service('hvac');
	const electrical = service('electrical');
	// Every discipline with failing checks, so one does not hide another.
	const failing = [
		{ failed: summary.openingsFailed, label: () => summary.openingsFailed === 1 ? localize('partStatus.mep.oneFail', "1 opening fails") : localize('partStatus.mep.fail', "{0} openings fail", summary.openingsFailed), hint: () => localize('partStatus.mep.review', "review the failing openings"), name: () => localize('partStatus.mep.openingsName', "openings {0}", summary.openingsFailed) },
		{ failed: plumbing?.failed ?? 0, label: () => plumbing?.failed === 1 ? localize('partStatus.mep.plumbingOneFail', "1 plumbing check fails") : localize('partStatus.mep.plumbingFail', "{0} plumbing checks fail", plumbing?.failed), hint: () => localize('partStatus.mep.plumbingReview', "review the plumbing"), name: () => localize('partStatus.mep.plumbingName', "plumbing {0}", plumbing?.failed) },
		{ failed: hvac?.failed ?? 0, label: () => hvac?.failed === 1 ? localize('partStatus.mep.hvacOneFail', "1 HVAC check fails") : localize('partStatus.mep.hvacFail', "{0} HVAC checks fail", hvac?.failed), hint: () => localize('partStatus.mep.hvacReview', "review the ducts' openings and the plant"), name: () => localize('partStatus.mep.hvacName', "HVAC {0}", hvac?.failed) },
		{ failed: electrical?.failed ?? 0, label: () => electrical?.failed === 1 ? localize('partStatus.mep.electricalOneFail', "1 electrical check fails") : localize('partStatus.mep.electricalFail', "{0} electrical checks fail", electrical?.failed), hint: () => localize('partStatus.mep.electricalReview', "review the electrical services"), name: () => localize('partStatus.mep.electricalName', "electrical {0}", electrical?.failed) },
	].filter(item => item.failed > 0);
	if (failing.length === 1) {
		return status('mep', 'failed', failing[0].label(), failing[0].hint());
	}
	if (failing.length > 1) {
		const total = failing.reduce((sum, item) => sum + item.failed, 0);
		return status('mep', 'failed', localize('partStatus.mep.manyFail', "{0} checks fail", total), localize('partStatus.mep.manyReview', "{0}: review them in the MEP results", failing.map(item => item.name()).join(', ')));
	}
	if (plumbing && typeof plumbing.floorsLow === 'number' && plumbing.floorsLow > 0) {
		return status('mep', 'failed', plumbing.floorsLow === 1 ? localize('partStatus.mep.oneFloorLow', "1 floor below the minimum pressure") : localize('partStatus.mep.floorsLow', "{0} floors below the minimum pressure", plumbing.floorsLow), localize('partStatus.mep.raiseTank', "raise the overhead tank or add a booster pump"));
	}
	if (plumbingItems && !plumbing) {
		return status('mep', 'inProgress', localize('partStatus.mep.plumbingNotChecked', "plumbing not checked"), localize('partStatus.mep.checkPlumbing', "open the plumbing results or Run All"));
	}
	if (hvacItems && !hvac) {
		return status('mep', 'inProgress', localize('partStatus.mep.hvacNotChecked', "HVAC not checked"), localize('partStatus.mep.checkHvac', "open the HVAC results or Run All"));
	}
	if (electricalItems && !electrical) {
		return status('mep', 'inProgress', localize('partStatus.mep.electricalNotChecked', "electrical not checked"), localize('partStatus.mep.checkElectrical', "open the electrical results or Run All"));
	}
	if (summary.clashesOpen > 0) {
		return status('mep', 'inProgress', summary.clashesOpen === 1 ? localize('partStatus.mep.oneClash', "1 clash") : localize('partStatus.mep.clashes', "{0} clashes", summary.clashesOpen), localize('partStatus.mep.coordinate', "coordinate the clashes"));
	}
	// Openings that passed only their size and spacing checks: their strength checks need results.
	const partial = typeof summary.openingsPartial === 'number' ? summary.openingsPartial : 0;
	if (partial > 0) {
		return status('mep', 'inProgress', partial === 1 ? localize('partStatus.mep.onePartial', "1 opening not fully checked") : localize('partStatus.mep.partial', "{0} openings not fully checked", partial), localize('partStatus.mep.analyse', "run the analysis to check the openings' strength"));
	}
	const equipment = count('equipment');
	if (!equipment && (hvac || electrical)) {
		return status('mep', 'done', localize('partStatus.mep.servicesChecked', "services checked"));
	}
	if (!equipment && plumbing) {
		return status('mep', 'done', plumbing.tanks === 1 ? localize('partStatus.mep.oneTank', "plumbing checked, 1 tank") : localize('partStatus.mep.tanks', "plumbing checked, {0} tanks", plumbing.tanks));
	}
	return status('mep', 'done', equipment === 1 ? localize('partStatus.mep.oneEquipment', "1 equipment") : localize('partStatus.mep.equipment', "{0} equipment", equipment));
}

function substructureHasFoundations(inputs: IPartStatusInputs): boolean {
	const text = inputs.texts.get('substructure');
	const document = text !== undefined ? parse(text) : undefined;
	return !!document && document.schema === SUBSTRUCTURE_SCHEMA_ID && Array.isArray(document.foundations) && document.foundations.length > 0;
}

/** The foundation checks' summary (see {@link SUBSTRUCTURE_SUMMARY_FILE}). */
interface ISubstructureSummary {
	readonly foundations: number;
	readonly checked: number;
	readonly passed: number;
	readonly failed: number;
	/**
	 * The stamp of each part file the checks read, by part id ("" for a file that was missing):
	 * the substructure, soil report, settings, materials, object types and building model.
	 * Summaries written before it was recorded are compared by time with the substructure only.
	 */
	readonly source?: { readonly [part: string]: unknown };
}

/** True when every part file a summary recorded still has the text it was checked with. */
function sourcesUnchanged(texts: ReadonlyMap<string, string | undefined>, source: { readonly [part: string]: unknown }): boolean {
	return Object.entries(source).every(([part, recorded]) => {
		const text = texts.get(part);
		return recorded === '' ? text === undefined : text !== undefined && recorded === sourceStamp(text);
	});
}

/**
 * Part 9: not started while the file is the placeholder or has no foundations; done (or failed)
 * when the foundation checks' summary is newer than the analysis results and every part file
 * it was checked from (the substructure, soil report, settings, materials, object types and
 * building model) is unchanged; in progress otherwise.
 */
function substructureStatus(inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get('substructure');
	const document = text !== undefined ? parse(text) : undefined;
	if (text === undefined || (document && isPlaceholder(document, 'substructure'))) {
		return status('substructure', 'notStarted', NOT_STARTED(), startHint('substructure'));
	}
	if (!document || document.schema !== SUBSTRUCTURE_SCHEMA_ID) {
		return status('substructure', 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.fix', "fix the file"));
	}
	const count = Array.isArray(document.foundations) ? document.foundations.length : 0;
	if (!count) {
		return status('substructure', 'notStarted', NOT_STARTED(), startHint('substructure'));
	}
	const foundations = count === 1 ? localize('partStatus.substructure.one', "1 foundation") : localize('partStatus.substructure.count', "{0} foundations", count);
	const value = inputs.substructureSummaryText !== undefined ? parse(inputs.substructureSummaryText) : undefined;
	const summary = value && typeof value.failed === 'number' && typeof value.passed === 'number' ? value as unknown as ISubstructureSummary : undefined;
	const time = inputs.substructureSummaryTime;
	const source = summary && typeof summary.source === 'object' && summary.source !== null ? summary.source : undefined;
	const current = summary && time !== undefined
		&& (source ? sourcesUnchanged(inputs.texts, source) : inputs.substructureTime === undefined || time >= inputs.substructureTime)
		&& (inputs.femResultsTime === undefined || time >= inputs.femResultsTime);
	if (!current) {
		return status('substructure', 'inProgress', foundations, localize('partStatus.substructure.check', "check the foundations"));
	}
	if (summary.checked === 0) {
		return status('substructure', 'inProgress', foundations, localize('partStatus.substructure.analyse', "run the analysis to design them"));
	}
	if (summary.failed > 0) {
		return status('substructure', 'failed', localize('partStatus.substructure.fail', "{0} fail", summary.failed), localize('partStatus.substructure.review', "review the failing foundations"));
	}
	return status('substructure', 'done', foundations);
}

function exportsStatus(inputs: IPartStatusInputs, formatDate: (time: number) => string): IPartStatus {
	if (inputs.reportTime === undefined) {
		const files = inputs.exportFiles ?? 0;
		return files > 0
			? status('exports', 'inProgress', files === 1 ? localize('partStatus.exports.oneFile', "1 file, no report") : localize('partStatus.exports.files', "{0} files, no report", files), localize('partStatus.exports.build', "build the design report"))
			: status('exports', 'notStarted', localize('partStatus.exports.noReport', "no report"), localize('partStatus.exports.build', "build the design report"));
	}
	return status('exports', 'done', localize('partStatus.exports.report', "report {0}", formatDate(inputs.reportTime)));
}

/** The hint of a part that is not started, by part id. */
function startHint(part: string): string {
	switch (part) {
		case 'soil': return localize('partStatus.soil.start', "enter the soil report");
		case 'settings': return localize('partStatus.settings.start', "set up the project");
		case 'materials': return localize('partStatus.materials.start', "choose the materials");
		case 'objects': return localize('partStatus.objects.start', "define the object types");
		case 'floorPlan': return localize('partStatus.floorPlan.start', "draw the floor plan");
		case 'structure': return localize('partStatus.structure.start', "draw the structural model");
		case 'mep': return localize('partStatus.mep.start', "lay out the services");
		case 'substructure': return localize('partStatus.substructure.start', "design the foundations");
		default: return localize('partStatus.open', "open the part");
	}
}

function documentStatus(part: string, inputs: IPartStatusInputs): IPartStatus {
	const text = inputs.texts.get(part);
	if (text === undefined) {
		return status(part, 'notStarted', NOT_STARTED(), startHint(part));
	}
	const document = parse(text);
	if (!document) {
		return status(part, 'error', localize('partStatus.invalid', "invalid file"), localize('partStatus.fix', "fix the file"));
	}
	if (isPlaceholder(document, part)) {
		return status(part, 'notStarted', NOT_STARTED(), startHint(part));
	}
	return status(part, 'done');
}

function defaultFormatDate(time: number): string {
	return new Date(time).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

/** The status of each of `parts` (a project's parts, in workflow order). */
export function computePartStatuses(parts: readonly IProjectPart[], inputs: IPartStatusInputs, formatDate: (time: number) => string = defaultFormatDate): IPartStatus[] {
	return parts.map(part => {
		switch (part.id) {
			case 'soil': return soilStatus(inputs);
			case 'fem': return femStatus(inputs);
			case 'boq': return boqStatus(inputs);
			case 'bim': return bimStatus(parts, inputs);
			case 'exports': return exportsStatus(inputs, formatDate);
			case 'substructure': return substructureStatus(inputs);
			case 'mep': return mepStatus(inputs);
			default: return documentStatus(part.id, inputs);
		}
	});
}

/**
 * The first part, in workflow order, that needs doing, with its index; the parts whose modules
 * are not written yet (soil report, MEP, substructure) are skipped.
 */
export function nextStep(statuses: readonly IPartStatus[]): { readonly index: number; readonly status: IPartStatus } | undefined {
	const index = statuses.findIndex(s => s.state !== 'done' && !OPTIONAL_PARTS.has(s.part));
	return index < 0 ? undefined : { index, status: statuses[index] };
}

export const ISaenginePartStatusService = createDecorator<ISaenginePartStatusService>('saenginePartStatusService');

/** The status of the open project's parts, kept up to date as their files change. */
export interface ISaenginePartStatusService {
	readonly _serviceBrand: undefined;

	/** One entry per part of the open project, in workflow order; empty without a project. */
	readonly statuses: readonly IPartStatus[];
	readonly onDidChange: Event<void>;

	statusOf(part: string): IPartStatus | undefined;
}
