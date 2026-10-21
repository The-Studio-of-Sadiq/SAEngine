/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';

/**
 * Desktop command running the reinforced-concrete design checks of an analysed model with the
 * Python backend (`saengine.design.design_report`): `(model: URI) => IFemDesignReport`.
 */
export const DESIGN_COMMAND = 'saengine.fem.design';

/**
 * One check of a member or a slab: demand against design capacity (kN, kN·m; slabs per metre
 * width, kN·m/m and kN/m; mm and mm²/m for detailing; none for ratios).
 */
export interface IFemDesignCheck {
	readonly name: string;
	readonly demand: number;
	readonly capacity: number;
	readonly unit: string;
	readonly utilisation: number;
	/** The load combination that governs, if the check depends on one. */
	readonly combination: string | null;
	readonly ok: boolean;
	readonly note: string;
	/** Reported only: does not make the member fail (e.g. slenderness). */
	readonly flag: boolean;
}

/** A checked beam, column or slab of the building model. */
export interface IFemDesignElement {
	/** Building model element id (`B1`, `C3`, `S1`, ...). */
	readonly id: string;
	readonly kind: 'beam' | 'column' | 'slab' | 'footing';
	/** Object type id. */
	readonly type: string;
	/**
	 * The analysis elements it is made of (`B1`, `B1#2`, ...; a slab's shells `S1`, `S1#2`,
	 * ...), by analysis element id.
	 */
	readonly members: readonly number[];
	readonly checks: readonly IFemDesignCheck[];
	/** The largest utilisation of its strength checks. */
	readonly utilisation: number;
	readonly ok: boolean;
	/**
	 * A slab's design strips (flexure and one-way shear are averaged across them), one bay each;
	 * its flexure checks name the governing one in their notes.
	 */
	readonly strips?: readonly IFemDesignStrip[];
}

/** One bay of a slab's design strip (ACI 318-19 8.4.1.5: column and middle strips). */
export interface IFemDesignStrip {
	/** E.g. "X column strip on the line of C4, C5, C6 (y = 5.00 m)". */
	readonly name: string;
	/** The slab layers it designs: bars along the slab's local x or y. */
	readonly direction: 'X' | 'Y';
	/** "strip": a direction without a column grid, cut into strips at most 1 m wide. */
	readonly kind: 'column' | 'middle' | 'strip';
	/** Plan corners of the bay, metres (global X, Y). */
	readonly outline: readonly (readonly [number, number])[];
}

export interface IFemDesignSkipped {
	readonly id: string;
	readonly kind: string;
	readonly type: string;
	readonly reason: string;
}

/** The design checks of an analysed model, enveloped over the project's load combinations. */
export interface IFemDesignReport {
	readonly code: string;
	readonly method: readonly string[];
	readonly combinations: readonly string[];
	readonly elements: readonly IFemDesignElement[];
	readonly skipped: readonly IFemDesignSkipped[];
	readonly summary: {
		readonly checked: number;
		readonly passed: number;
		readonly failed: number;
		readonly skipped: number;
		readonly maxUtilisation: number | null;
		readonly governing: string | null;
	};
	readonly notes: readonly string[];
}

/*
 * Design mode: the steel each member needs, and bars proposed for the object types. Desktop
 * commands of the Python backend (`saengine.design.required`, `.proposal`, `.apply_proposal`),
 * each taking one argument object; until they are registered the views say the backend is not
 * available.
 */

/** `(model?: URI) => void`: opens the Design Reinforcement page (registered by this contribution). */
export const DESIGN_REINFORCEMENT_COMMAND = 'saengine.fem.designReinforcement';

/** `{outDir, projectPath} => IFemDesignRequired`: the steel required by every member of a run. */
export const DESIGN_REQUIRED_COMMAND = 'saengine.design.required';
/** `{outDir, projectPath, mode, diameters?} => IFemDesignProposal`: bars proposed per object type. */
export const DESIGN_PROPOSAL_COMMAND = 'saengine.design.proposal';
/** `{objectsText, bimText, proposal} => IFemDesignApplyResult`: the object types (and building model) with the proposal applied. */
export const DESIGN_APPLY_COMMAND = 'saengine.design.apply';

/**
 * One row of the steel required (`saengine.design.required`): per element and location (a
 * beam's zone, a column, a slab strip and layer, a footing's direction and face), the steel to
 * provide (As,min included) against the steel of the bars entered.
 */
export interface IFemSteelRequirement {
	/** Building model id of the element (`B1`, `C3`, `S1`; a foundation's id). */
	readonly element: string;
	readonly kind: string;
	readonly type: string;
	/** "start", "middle", "end"; "column"; "X column strip on C4, C5 (column), bottomX". */
	readonly location: string;
	/** "bottom bars (sagging)", "stirrups Av/s", "longitudinal bars", "tie spacing (max)", "bottom X bars". */
	readonly quantity: string;
	/** The design force it is required for, in `demandUnit`; null when it needs none. */
	readonly demand: number | null;
	readonly demandUnit: string;
	readonly required: number;
	/** The minimum on its own, when it applies. */
	readonly min: number | null;
	/** The steel of the bars entered; null when there are none (or they were only assumed). */
	readonly provided: number | null;
	/** "mm²", "mm²/m"; "mm" for a largest spacing, which `provided` must not exceed. */
	readonly unit: string;
	/** The load combination that governs it. */
	readonly combination: string | null;
	/** Whether the bars provided are enough; null without bars. */
	readonly ok: boolean | null;
	/** No practical bars make the section work. */
	readonly tooSmall: boolean;
	readonly notes: string;
}

/** Content of {@link DESIGN_REQUIRED_COMMAND}'s result. */
export interface IFemDesignRequired {
	readonly code?: string | null;
	readonly elements: readonly IFemSteelRequirement[];
	readonly summary?: {
		readonly rows?: number;
		readonly elements?: number;
		/** Rows whose bars provide less than required. */
		readonly short?: number;
		/** Elements whose section no bars can make work. */
		readonly tooSmall?: readonly string[];
		/** Object types without bars, checked with assumed ones for the effective depth. */
		readonly assumed?: readonly string[];
	};
	readonly notes?: readonly string[];
}

/** Whether a row is a largest value (a spacing) rather than a least one. */
function isLargest(row: IFemSteelRequirement): boolean {
	return row.unit === 'mm';
}

/**
 * Whether a row is a failing check that bars cannot fix (a footing's bearing or resultant):
 * the backend lists it without a steel quantity (no unit), the failure in its notes.
 */
export function isOtherFailure(row: IFemSteelRequirement): boolean {
	return !row.unit;
}

/** The elements whose section no practical bars make work (not those failing other checks). */
export function tooSmallElements(required: IFemDesignRequired | undefined): string[] {
	return [...new Set((required?.elements ?? []).filter(r => r.tooSmall && !isOtherFailure(r)).map(r => r.element))];
}

/** The elements failing a check that bars cannot fix (a footing's bearing or resultant). */
export function otherFailureElements(required: IFemDesignRequired | undefined): string[] {
	return [...new Set((required?.elements ?? []).filter(isOtherFailure).map(r => r.element))];
}

/**
 * The governing row of each quantity of an element, in the backend's order: a beam's bars
 * and stirrups are the same along the member, so its zone needing the most shows (a short one
 * first); a slab layer's strip needing the most. Failing checks that bars cannot fix
 * ({@link isOtherFailure}) are each kept, after the steel.
 */
export function requiredSteelOf(required: IFemDesignRequired | undefined, elementId: string | undefined): IFemSteelRequirement[] {
	if (!required || elementId === undefined) {
		return [];
	}
	const governing = new Map<string, IFemSteelRequirement>();
	const others: IFemSteelRequirement[] = [];
	for (const row of required.elements) {
		if (row.element !== elementId) {
			continue;
		}
		if (isOtherFailure(row)) {
			others.push(row);
			continue;
		}
		const held = governing.get(row.quantity);
		const worse = !held
			|| (row.tooSmall && !held.tooSmall)
			|| (row.ok === false && held.ok !== false)
			|| (row.tooSmall === held.tooSmall && (row.ok === false) === (held.ok === false) && (isLargest(row) ? row.required < held.required : row.required > held.required));
		if (worse) {
			governing.set(row.quantity, row);
		}
	}
	return [...governing.values(), ...others];
}

/**
 * The members whose bars provide less steel than required, in the backend's order (each once:
 * the backend reports a row per zone, strip and layer).
 */
export function shortElements(required: IFemDesignRequired | undefined): string[] {
	const short = new Set<string>();
	for (const row of required?.elements ?? []) {
		if (row.ok === false) {
			short.add(row.element);
		}
	}
	return [...short];
}

/**
 * A column's steel ratio, required and provided ("ρ required 0.0123, provided 0.0201"): the
 * backend notes ρ required, from which the gross area follows. Undefined for other rows.
 */
export function describeSteelRatio(row: IFemSteelRequirement): string | undefined {
	const rho = Number(/ρ required = (?<rho>[0-9.]+)/.exec(row.notes)?.groups?.rho);
	if (row.kind !== 'column' || !(rho > 0) || !(row.required > 0)) {
		return undefined;
	}
	const gross = row.required / rho;
	const ratio = (value: number) => value.toFixed(4);
	return row.provided === null
		? localize('femDesign.ratioRequired', "ρ required {0}", ratio(rho))
		: localize('femDesign.ratioProvided', "ρ required {0}, provided {1}", ratio(rho), ratio(row.provided / gross));
}

/** A steel quantity in its unit: "1,257 mm²", "524 mm²/m", "150 mm". */
export function formatSteel(value: number, unit: string): string {
	const text = value.toLocaleString('en-US', { maximumFractionDigits: 0 });
	return unit ? localize('femDesign.steelValue', "{0} {1}", text, unit) : text;
}

/** "required 1,257 mm², provided 1,473 mm²", "required 1,257 mm², none provided", "at most 150 mm, provided 200 mm". */
export function describeSteel(row: IFemSteelRequirement): string {
	if (isOtherFailure(row)) {
		return row.notes || localize('femDesign.otherFails', "fails; bars do not fix it");
	}
	const required = formatSteel(row.required, row.unit);
	if (isLargest(row)) {
		return row.provided === null
			? localize('femDesign.atMostOnly', "at most {0}", required)
			: localize('femDesign.atMostProvided', "at most {0}, provided {1}", required, formatSteel(row.provided, row.unit));
	}
	return row.provided === null
		? localize('femDesign.requiredOnly', "required {0}, none provided", required)
		: localize('femDesign.requiredProvided', "required {0}, provided {1}", required, formatSteel(row.provided, row.unit));
}

/** The folder a model's analysis results are written to (`model.osmodel` -> `model.results`). */
export function resultsFolder(model: URI): URI {
	return joinPath(dirname(model), `${basename(model).replace(/\.osmodel$/i, '')}.results`);
}

/** The design checks' summary beside the results, read by the project's part list ("3 fail"). */
export const DESIGN_SUMMARY_FILE = 'design-summary.json';

/** Content of {@link DESIGN_SUMMARY_FILE}. */
export interface IFemDesignSummaryFile {
	readonly checked: number;
	readonly passed: number;
	readonly failed: number;
	readonly maxUtilisation: number | null;
	readonly governing: string | null;
	/** ISO time the checks were computed. */
	readonly computed: string;
}

export function designSummaryFile(report: IFemDesignReport, computed: Date): IFemDesignSummaryFile {
	const { checked, passed, failed, maxUtilisation, governing } = report.summary;
	return { checked, passed, failed, maxUtilisation, governing, computed: computed.toISOString() };
}

/** Writes the design checks' summary of `model`'s run to `<model>.results/design-summary.json`. */
export async function writeDesignSummary(fileService: IFileService, model: URI, report: IFemDesignReport): Promise<void> {
	const content = JSON.stringify(designSummaryFile(report, new Date()), undefined, '\t') + '\n';
	await fileService.writeFile(joinPath(resultsFolder(model), DESIGN_SUMMARY_FILE), VSBuffer.fromString(content));
}

export function runDesign(commandService: ICommandService, model: URI): Promise<IFemDesignReport | undefined> {
	return commandService.executeCommand<IFemDesignReport>(DESIGN_COMMAND, model);
}

/** The arguments of the design-mode commands for `model`'s last run. */
export function designArguments(model: URI): { readonly outDir: string; readonly projectPath: string } {
	return { outDir: resultsFolder(model).fsPath, projectPath: model.fsPath };
}

/** The steel every member of `model`'s run requires; undefined when the backend does not offer it. */
export async function runDesignRequired(commandService: ICommandService, model: URI): Promise<IFemDesignRequired | undefined> {
	if (!CommandsRegistry.getCommand(DESIGN_REQUIRED_COMMAND)) {
		return undefined;
	}
	return commandService.executeCommand<IFemDesignRequired>(DESIGN_REQUIRED_COMMAND, designArguments(model));
}

/**
 * The project files the design checks read besides the results (`08 FEM/model.osmodel` -> the
 * project two folders up): reinforcement, materials and combinations change the checks without
 * a new analysis run.
 */
export function designInputs(model: URI): URI[] {
	const root = dirname(dirname(model));
	return [
		['02 Project Settings', 'project-settings.json'],
		['03 Materials', 'materials.json'],
		['04 Objects', 'objects.json'],
		['06 BIM', 'bim.json'],
	].map(([folder, file]) => joinPath(root, folder, file));
}

/** A utilisation to two decimals, or three where two would hide which colour band it is in. */
export function formatUtilisation(value: number): string {
	const short = value.toFixed(2);
	return Number(short) !== value && (short === '1.00' || short === '0.90') ? value.toFixed(3) : short;
}

/** Utilisation of each analysis element: that of the member it belongs to. */
export function designUtilisation(report: IFemDesignReport): { [elementId: number]: number } {
	const result: { [elementId: number]: number } = {};
	for (const element of report.elements) {
		for (const id of element.members) {
			result[id] = element.utilisation;
		}
	}
	return result;
}

/** The checked member an analysis element belongs to. */
export function designElementOf(report: IFemDesignReport, elementId: number): IFemDesignElement | undefined {
	return report.elements.find(e => e.members.includes(elementId));
}

/** "12 members pass, 2 fail, 3 not checked." */
export function describeDesignSummary(report: IFemDesignReport): string {
	const { passed, failed, skipped } = report.summary;
	if (!report.elements.length) {
		return skipped
			? localize('femDesign.noneChecked', "No member could be checked ({0} not checked: select one for the reason, or see the notes).", skipped)
			: localize('femDesign.noMembersOrSlabs', "There are no reinforced-concrete beams, columns or slabs to check.");
	}
	const counts = localize('femDesign.counts', "{0} members pass, {1} fail", passed, failed);
	const largest = report.summary.maxUtilisation !== null && report.summary.governing
		? localize('femDesign.largest', "largest utilisation {0} in {1}", formatUtilisation(report.summary.maxUtilisation), report.summary.governing)
		: undefined;
	const parts = [counts, ...(largest ? [largest] : []), ...(skipped ? [localize('femDesign.skipped', "{0} not checked", skipped)] : [])];
	return report.elements.some(e => e.kind === 'slab')
		? localize('femDesign.summarySlabs', "{0} ({1}). Select a member, or a slab's shell, for its checks.", parts.join(', '), report.code)
		: localize('femDesign.summary', "{0} ({1}). Select a member for its checks.", parts.join(', '), report.code);
}

/** A check's demand against capacity: "120.5 of 300.0 kN", or a ratio "0.11 against 0.38". */
export function formatCheckValues(check: IFemDesignCheck): string {
	// Ratios (c/d, slenderness) keep two decimals: one would round a slab's c/d of 0.11 to 0.1.
	return check.unit
		? localize('femDesign.checkValues', "{0} of {1} {2}", check.demand.toFixed(1), check.capacity.toFixed(1), check.unit)
		: localize('femDesign.checkRatio', "{0} against {1}", check.demand.toFixed(2), check.capacity.toFixed(2));
}

/** A member's checks, the governing (strength) checks first, then the reported-only ones. */
export function sortedChecks(element: IFemDesignElement): IFemDesignCheck[] {
	return [...element.checks].sort((a, b) => Number(a.flag) - Number(b.flag) || b.utilisation - a.utilisation);
}

/** "beam", "column", "slab", "footing". */
export function designKindLabel(kind: IFemDesignElement['kind'] | string): string {
	return kind === 'beam' ? localize('femDesign.beam', "beam")
		: kind === 'slab' ? localize('femDesign.slab', "slab")
			: kind === 'footing' ? localize('femDesign.footing', "footing")
				: localize('femDesign.column', "column");
}

function formatCheck(check: IFemDesignCheck): string {
	const values = formatCheckValues(check);
	return check.combination
		? localize('femDesign.checkUnder', "{0} {1} ({2}, {3})", check.name, formatUtilisation(check.utilisation), values, check.combination)
		: localize('femDesign.check', "{0} {1} ({2})", check.name, formatUtilisation(check.utilisation), values);
}

/**
 * The selected analysis element's member: its utilisation and its checks, the governing first,
 * with where and how the governing one is found; or why the member was not checked.
 */
export function describeDesignElement(report: IFemDesignReport, elementId: number, elementName: string | undefined): string | undefined {
	const element = designElementOf(report, elementId);
	if (!element) {
		const id = elementName?.split('#')[0];
		const skipped = id !== undefined ? report.skipped.find(s => s.id === id) : undefined;
		return skipped ? localize('femDesign.notChecked', "{0} ({1}) is not checked: {2}.", skipped.id, skipped.type, skipped.reason) : undefined;
	}
	const checks = sortedChecks(element);
	const kind = designKindLabel(element.kind);
	const verdict = element.ok ? localize('femDesign.passes', "passes") : localize('femDesign.fails', "fails");
	const text = localize('femDesign.element', "{0} ({1} {2}) {3}, utilisation {4}: {5}.", element.id, kind, element.type, verdict,
		formatUtilisation(element.utilisation), checks.map(formatCheck).join('; '));
	const governing = checks.find(c => !c.flag);
	return governing?.note ? localize('femDesign.governing', "{0} Governing: {1}.", text, governing.note) : text;
}
