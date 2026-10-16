/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { localize } from '../../../../nls.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { recordedStamp, sourceStamp, upstreamPart } from './partSources.js';
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
}

/** File names the status reads besides the parts' main files. */
export const FEM_RESULTS_FOLDER = 'model.results';
export const FEM_RESULTS_MANIFEST = 'manifest.json';
export const DESIGN_SUMMARY_FILE = 'design-summary.json';
export const REPORT_FILE = 'report.pdf';

/** Parts whose modules are not written yet: they never block the next step. */
const OPTIONAL_PARTS = new Set(['soil', 'mep', 'substructure']);

/** The parts the analysis model is derived from, by the keys its description records them under. */
const FEM_SOURCES = ['bim', 'settings', 'objects', 'materials'];

/** The parts the bill of quantities is measured from. */
const BOQ_SOURCES = ['bim', 'objects', 'materials'];

const BOQ_SCHEMA_ID = 'saengine.boq/1';

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

function changed(texts: ReadonlyMap<string, string | undefined>, part: string, recorded: string | undefined): boolean {
	const text = texts.get(part);
	return text === undefined || recorded !== sourceStamp(text);
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
	if (FEM_SOURCES.some(part => changed(inputs.texts, part, recorded.get(part)))) {
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
	if (BOQ_SOURCES.some(part => changed(inputs.texts, part, recordedStamp(document, part)))) {
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

function exportsStatus(inputs: IPartStatusInputs, formatDate: (time: number) => string): IPartStatus {
	if (inputs.reportTime === undefined) {
		return status('exports', 'notStarted', localize('partStatus.exports.noReport', "no report"), localize('partStatus.exports.build', "build the design report"));
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
			case 'fem': return femStatus(inputs);
			case 'boq': return boqStatus(inputs);
			case 'bim': return bimStatus(parts, inputs);
			case 'exports': return exportsStatus(inputs, formatDate);
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
