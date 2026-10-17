/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { localize } from '../../../../nls.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { boqSourceStamp, recordedStamp, sourceStamp, upstreamPart } from './partSources.js';
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
}

/** File names the status reads besides the parts' main files. */
export const FEM_RESULTS_FOLDER = 'model.results';
export const FEM_RESULTS_MANIFEST = 'manifest.json';
export const DESIGN_SUMMARY_FILE = 'design-summary.json';
export const REPORT_FILE = 'report.pdf';
/** The foundation checks' summary the Substructure editor and Run All write beside `substructure.json`. */
export const SUBSTRUCTURE_SUMMARY_FILE = 'substructure.results/summary.json';

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

/** The parts the bill of quantities is measured from (the substructure: once the bill records it). */
const BOQ_SOURCES = ['bim', 'objects', 'materials'];
const BOQ_RECORDED_SOURCES = ['substructure', 'settings'];

const SUBSTRUCTURE_SCHEMA_ID = 'saengine.substructure/1';

const BOQ_SCHEMA_ID = 'saengine.boq/1';

const SOIL_SCHEMA_ID = 'saengine.soilReport/1';

/** The key a derived analysis model records the soil report's stamp under, when its settings take the site class from it. */
const FEM_SOIL_SOURCE = 'soil';

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
	if (soilChanged || FEM_SOURCES.some(part => changed(inputs.texts, part, recorded.get(part)))) {
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
		|| (!recorded('substructure') && substructureHasFoundations(inputs))) {
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
