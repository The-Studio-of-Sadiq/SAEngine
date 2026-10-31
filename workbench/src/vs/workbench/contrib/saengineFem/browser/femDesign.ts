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
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';

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
	/** Reported only: does not make the member fail. */
	readonly flag: boolean;
	/**
	 * A column's slenderness check ("Slenderness (nonsway, δns = 1.12)"): how it was designed
	 * for. The backend may give the fields here or directly on the check (see {@link slendernessOf}).
	 */
	readonly slenderness?: IFemSlenderness;
	/** The column is too slender for moment magnification: a second-order analysis is required. */
	readonly secondOrderRequired?: boolean;
}

/**
 * How a column's slenderness is designed for (ACI 318-19 6.2.5, 6.6.4 as BNBC 2020 Part 6
 * Ch 6 adopts): lengths in mm, moments in kN·m.
 */
export interface IFemSlenderness {
	/** Unbraced length [mm]. */
	readonly lu: number;
	/** Effective length factor. */
	readonly k: number;
	/** Radius of gyration [mm]. */
	readonly r: number;
	readonly klu_r: number;
	/** The storey is a sway storey; null when not known (one storey, no lateral case). */
	readonly sway: boolean | null;
	/** The storey's stability index; null when not worked out. */
	readonly Q?: number | null;
	readonly deltaNs?: number | null;
	readonly deltaS?: number | null;
	/** The larger end moment, first order [kN·m]. */
	readonly M2?: number | null;
	/** M2 magnified (minimum moment included) [kN·m]. */
	readonly M2magnified?: number | null;
	/** The k lu / r below which slenderness may be neglected, if the backend reports it. */
	readonly limit?: number | null;
	/** The storey ("Storey 2"), if the backend names it. */
	readonly storey?: string | null;
	/** The bending axis of the check ("y", "z"). */
	readonly axis?: string | null;
	/** k lu / r is at most the limit: slenderness neglected (the check is then a flag). */
	readonly neglected?: boolean | null;
	/** Cm of the nonsway magnifier, and the critical load Pc [kN]. */
	readonly Cm?: number | null;
	readonly Pc?: number | null;
	/** "none" or "pDelta": the sway moments come from a P-Delta analysis. */
	readonly secondOrder?: string | null;
}

/** A checked beam, column, slab, footing, wall or staircase of the building model. */
export interface IFemDesignElement {
	/** Building model element id (`B1`, `C3`, `S1`, ...). */
	readonly id: string;
	/** A wall's members are its shells; a staircase has none (it is not in the analysis model). */
	readonly kind: 'beam' | 'column' | 'brace' | 'slab' | 'footing' | 'wall' | 'staircase' | 'diaphragm';
	/** Object type id. */
	readonly type: string;
	/**
	 * The analysis elements it is made of (`B1`, `B1#2`, ...; a slab's shells `S1`, `S1#2`,
	 * ...), by analysis element id.
	 */
	readonly members: readonly number[];
	readonly checks: readonly IFemDesignCheck[];
	/**
	 * What ranks and colours the member: its strength utilisation, or its detailing one when a
	 * detailing check fails (a passing detailing equality, lo 550 against 550 mm, never governs).
	 */
	readonly utilisation: number;
	/** The largest utilisation of its strength checks (not `Detailing: ...`). */
	readonly strengthUtilisation?: number;
	/** The largest utilisation of its detailing checks. */
	readonly detailingUtilisation?: number;
	/** The check that sets `utilisation`, and its combination. */
	readonly governingCheck?: { readonly name: string; readonly combination?: string | null } | null;
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

/** Checked, passed and failed of a group of checks. */
export interface IFemDesignTally {
	readonly checked: number;
	readonly passed: number;
	readonly failed: number;
}

/** A member kind's counts: `total` = `checked` + `notChecked`. */
export interface IFemDesignKindCounts extends IFemDesignTally {
	readonly total: number;
	readonly notChecked: number;
}

/**
 * The counts of a design run (`summary.counts`, python `saengine.design.check.design_counts`):
 * the ONE count every surface shows (the proposal, the FEM view, Run All, the report, the
 * navigator). Members, joints and the building's own seismic checks are counted apart and never
 * added together. A member is one designed element (a beam or column member, a slab panel, a
 * wall, a staircase), whatever its analysis elements.
 */
export interface IFemDesignCounts {
	readonly members: IFemDesignKindCounts & {
		/** By kind: "beam", "column", "slab", "wall", "staircase", the steel kinds. */
		readonly byKind: { readonly [kind: string]: IFemDesignKindCounts };
	};
	readonly joints: IFemDesignTally;
	/** The building's own checks (system permitted in the category, bar grades). */
	readonly building: IFemDesignTally;
	/** Members not checked: for want of bars (proposed by Design Reinforcement), or another reason. */
	readonly notChecked: { readonly noBars: number; readonly other: number };
}

/** The design checks of an analysed model, enveloped over the project's load combinations. */
export interface IFemDesignReport {
	readonly code: string;
	readonly method: readonly string[];
	readonly combinations: readonly string[];
	readonly elements: readonly IFemDesignElement[];
	readonly skipped: readonly IFemDesignSkipped[];
	/**
	 * The totals count the members, the beam-column joints and the building's seismic checks
	 * (system permitted in the category, bar grades); `elements` the members alone.
	 */
	readonly summary: {
		readonly checked: number;
		readonly passed: number;
		readonly failed: number;
		readonly skipped: number;
		readonly maxUtilisation: number | null;
		readonly governing: string | null;
		readonly elements?: { readonly checked: number; readonly passed: number; readonly failed: number };
		readonly joints?: { readonly checked: number; readonly failed: number };
		readonly seismicChecks?: number;
		readonly seismicChecksFailed?: number;
		/** Object types not checked for want of bars (Design Reinforcement proposes them). */
		readonly noBars?: readonly string[];
		/** The check that sets `maxUtilisation`. */
		readonly governingCheck?: { readonly name: string; readonly combination?: string | null } | null;
		/** The one count every surface shows (see {@link IFemDesignCounts}). */
		readonly counts?: IFemDesignCounts;
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

/** Planned: strut-and-tie models of any D-region (registered in saengineFem.contribution.ts). */
export const PLANNED_STM_GENERAL = 'fem.stm-general';

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
	const text = formatNumber(value);
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

/**
 * "16 members pass, 2 fail; 6 joints, 1 fails; 1 building check fails": the members' counts,
 * then the joints and the building's seismic checks when there are any (the totals hold all
 * three; an older backend's totals are the members').
 */
export function describeDesignCounts(summary: IFemDesignReport['summary']): string {
	const counts = summary.counts;
	if (counts) {
		const parts = [localize('femDesign.counts', "{0} members pass, {1} fail", counts.members.passed, counts.members.failed)];
		if (counts.joints.checked) {
			parts.push(localize('femDesign.jointCounts', "{0} joints, {1} fail", counts.joints.checked, counts.joints.failed));
		}
		if (counts.building.failed) {
			parts.push(counts.building.failed === 1
				? localize('femDesign.buildingCheckFails', "1 building check fails")
				: localize('femDesign.buildingChecksFail', "{0} building checks fail", counts.building.failed));
		}
		return parts.join('; ');
	}
	const members = summary.elements ?? summary;
	const parts = [localize('femDesign.counts', "{0} members pass, {1} fail", members.passed, members.failed)];
	if (summary.elements && summary.joints?.checked) {
		parts.push(localize('femDesign.jointCounts', "{0} joints, {1} fail", summary.joints.checked, summary.joints.failed));
	}
	if (summary.elements && summary.seismicChecksFailed) {
		parts.push(summary.seismicChecksFailed === 1
			? localize('femDesign.buildingCheckFails', "1 building check fails")
			: localize('femDesign.buildingChecksFail', "{0} building checks fail", summary.seismicChecksFailed));
	}
	return parts.join('; ');
}

/**
 * "1 member not checked" / "28 members not checked (12 for want of bars)": the members the
 * checks left out, from the counts (the report's `skipped` from an older backend).
 */
export function describeNotChecked(summary: IFemDesignReport['summary']): string | undefined {
	const counts = summary.counts;
	const total = counts ? counts.members.notChecked : summary.skipped;
	if (!total) {
		return undefined;
	}
	const noBars = counts?.notChecked.noBars ?? 0;
	if (noBars && noBars < total) {
		return localize('femDesign.notCheckedSome', "{0} members not checked ({1} for want of bars)", total, noBars);
	}
	if (noBars) {
		return total === 1
			? localize('femDesign.notCheckedOneNoBars', "1 member not checked for want of bars")
			: localize('femDesign.notCheckedNoBars', "{0} members not checked for want of bars", total);
	}
	return total === 1
		? localize('femDesign.notCheckedOne', "1 member not checked")
		: localize('femDesign.notCheckedMany', "{0} members not checked", total);
}

/**
 * The text of a backend error line to show for a design run: a code pack the engine cannot use
 * (N-X17 of usability walk 2: a raw `saengine.codes.registry.CodePackError` when the pack's
 * files changed while the engine ran) says what to do; anything else is returned as it is.
 */
export function describeEngineError(line: string): string {
	const pack = /(?:^|\.)CodePack(?:Hook)?Error:\s*(?<message>.*)$/.exec(line);
	if (pack?.groups) {
		return localize('femDesign.codePackError', "The code pack cannot be used ({0}). If its files changed while the engine ran, restart the engine (Run All menu: Restart Engine) to read them again.", pack.groups.message);
	}
	return line;
}

/** "12 members pass, 2 fail, 3 not checked." */
export function describeDesignSummary(report: IFemDesignReport): string {
	const { skipped } = report.summary;
	if (!report.elements.length) {
		return skipped
			? localize('femDesign.noneChecked', "No member could be checked ({0} not checked: select one for the reason, or see the notes).", skipped)
			: localize('femDesign.noMembersOrSlabs', "There are no reinforced-concrete beams, columns or slabs to check.");
	}
	const counts = describeDesignCounts(report.summary);
	const largest = describeLargest(report.summary);
	const notChecked = describeNotChecked(report.summary);
	const parts = [counts, ...(largest ? [largest] : []), ...(notChecked ? [notChecked] : [])];
	return report.elements.some(e => e.kind === 'slab')
		? localize('femDesign.summarySlabs', "{0} ({1}). Select a member, or a slab's shell, for its checks.", parts.join(', '), report.code)
		: localize('femDesign.summary', "{0} ({1}). Select a member for its checks.", parts.join(', '), report.code);
}

/** "largest utilisation 0.93 in C-A1-L1 (Axial and bending, 1.2D + 1.0L + 1.0EX)". */
export function describeLargest(summary: IFemDesignReport['summary']): string | undefined {
	if (summary.maxUtilisation === null || !summary.governing) {
		return undefined;
	}
	const check = summary.governingCheck;
	const what = check ? (check.combination ? `${check.name}, ${check.combination}` : check.name) : undefined;
	return what
		? localize('femDesign.largestCheck', "largest utilisation {0} in {1} ({2})", formatUtilisation(summary.maxUtilisation), summary.governing, what)
		: localize('femDesign.largest', "largest utilisation {0} in {1}", formatUtilisation(summary.maxUtilisation), summary.governing);
}

/** A check's demand against capacity: "120.5 of 300.0 kN", or a ratio "0.11 against 0.38". */
export function formatCheckValues(check: IFemDesignCheck): string {
	// A column whose slenderness may be neglected is rated against that limit (22, or
	// 34 - 12 M1/M2), not against the 100 of the second-order analysis: show the limit it uses.
	const slenderness = check.name.startsWith('Slenderness') ? slendernessOf(check) : undefined;
	if (slenderness?.neglected && typeof slenderness.limit === 'number') {
		return localize('femDesign.checkSlenderLimit', "k lu / r {0} against {1} (slenderness may be neglected)", check.demand.toFixed(2), slenderness.limit.toFixed(2));
	}
	// Ratios (c/d, slenderness) keep two decimals: one would round a slab's c/d of 0.11 to 0.1.
	return check.unit
		? localize('femDesign.checkValues', "{0} of {1} {2}", check.demand.toFixed(1), check.capacity.toFixed(1), check.unit)
		: localize('femDesign.checkRatio', "{0} against {1}", ...formatRatios(check.demand, check.capacity));
}

/**
 * Two ratios to the same number of decimals: two, or enough for two significant digits of the
 * smaller (a wall's ρ 0.0124 against 0.0025 as "0.0124 against 0.0025", not "0.01 against 0.0025").
 */
function formatRatios(demand: number, capacity: number): [string, string] {
	const decimals = (v: number) => v !== 0 && Number.isFinite(v) && Math.abs(v) < 0.1 ? Math.min(6, 1 - Math.floor(Math.log10(Math.abs(v)))) : 2;
	const digits = Math.max(decimals(demand), decimals(capacity));
	return [demand.toFixed(digits), capacity.toFixed(digits)];
}

/** A member's checks, the governing (strength) checks first, then the reported-only ones. */
export function sortedChecks(element: IFemDesignElement): IFemDesignCheck[] {
	return [...element.checks].sort((a, b) => Number(a.flag) - Number(b.flag) || b.utilisation - a.utilisation);
}

/** "beam", "column", "brace", "slab", "footing", "wall", "staircase", "diaphragm". */
export function designKindLabel(kind: IFemDesignElement['kind'] | string): string {
	return kind === 'beam' ? localize('femDesign.beam', "beam")
		: kind === 'brace' ? localize('femDesign.brace', "brace")
		: kind === 'slab' ? localize('femDesign.slab', "slab")
			: kind === 'footing' ? localize('femDesign.footing', "footing")
				: kind === 'wall' ? localize('femDesign.wall', "wall")
					: kind === 'staircase' ? localize('femDesign.staircase', "staircase")
						: kind === 'diaphragm' ? localize('femDesign.diaphragm', "diaphragm")
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

// ───────────────────────────── column slenderness ─────────────────────────────

/** Whether a check is a column's slenderness check (designed for, or flagged by an older backend). */
export function isSlendernessCheck(check: IFemDesignCheck): boolean {
	return check.name.startsWith('Slenderness') || slendernessOf(check) !== undefined;
}

/**
 * How a slenderness check was designed for: the backend's `slenderness` object, or its fields on
 * the check itself; undefined when it reports none (a flag of an older backend).
 */
export function slendernessOf(check: IFemDesignCheck): IFemSlenderness | undefined {
	if (check.slenderness) {
		return check.slenderness;
	}
	const fields = check as IFemDesignCheck & Partial<IFemSlenderness>;
	return typeof fields.klu_r === 'number' && typeof fields.lu === 'number' && typeof fields.k === 'number' && typeof fields.r === 'number'
		? {
			lu: fields.lu, k: fields.k, r: fields.r, klu_r: fields.klu_r, sway: fields.sway ?? null, Q: fields.Q, deltaNs: fields.deltaNs, deltaS: fields.deltaS,
			M2: fields.M2, M2magnified: fields.M2magnified, limit: fields.limit, storey: fields.storey, axis: fields.axis, neglected: fields.neglected,
			Cm: fields.Cm, Pc: fields.Pc, secondOrder: fields.secondOrder,
		}
		: undefined;
}

/** Whether a check says the column needs a second-order analysis (too slender to magnify its moments). */
export function isSecondOrderRequired(check: IFemDesignCheck): boolean {
	return check.secondOrderRequired === true || (!check.ok && /second-order analysis (is )?required/i.test(`${check.name} ${check.note}`));
}

/** The members that need a second-order analysis, in the report's order. */
export function secondOrderRequiredMembers(report: IFemDesignReport | undefined): string[] {
	return (report?.elements ?? []).filter(e => e.checks.some(isSecondOrderRequired)).map(e => e.id);
}

/** One name/value row of a column's slenderness in the properties panel. */
export interface IFemSlendernessRow {
	readonly name: string;
	readonly value: string;
}

/**
 * The k lu / r above which moment magnification is not permitted and a second-order analysis is
 * required (ACI 318-19 6.2.6, as `saengine.design.slender.KLU_R_MAX`).
 */
const KLU_R_MAX = 100;

/** The δs above which a second-order analysis is required (as `saengine.design.slender.DELTA_S_MAX`). */
const DELTA_S_MAX = 1.5;

function formatMillimetres(value: number): string {
	return localize('femDesign.mm', "{0} mm", formatNumber(value));
}

function formatKilonewtonMetres(value: number): string {
	return localize('femDesign.kNm', "{0} kN·m", value.toFixed(1));
}

/**
 * A column's slenderness as rows: lu, k, r, k lu / r (against its limit), the storey (sway or
 * nonsway, with Q), the magnifiers and M2 magnified, and the combination that governs.
 */
export function describeSlenderness(check: IFemDesignCheck): IFemSlendernessRow[] {
	const s = slendernessOf(check);
	if (!s) {
		return [];
	}
	const rows: IFemSlendernessRow[] = [
		{ name: localize('femDesign.lu', "Unbraced length lu"), value: formatMillimetres(s.lu) },
		{ name: localize('femDesign.k', "Effective length factor k"), value: s.k.toFixed(2) },
		{ name: localize('femDesign.r', "Radius of gyration r"), value: formatMillimetres(s.r) },
		{
			name: localize('femDesign.kluR', "k lu / r"),
			value: s.klu_r > KLU_R_MAX
				? localize('femDesign.kluRMax', "{0} > {1}: second-order analysis required", s.klu_r.toFixed(1), KLU_R_MAX.toFixed(1))
				: typeof s.limit !== 'number'
					? s.klu_r.toFixed(1)
					: s.neglected
						? localize('femDesign.kluRNeglected', "{0} ≤ {1}: slenderness neglected", s.klu_r.toFixed(1), s.limit.toFixed(1))
						// Past the "may be neglected" limit the moments are magnified: that limit never
						// asks for a second-order analysis (δs > 1.5 or an unstable storey does, below).
						: localize('femDesign.kluRLimit', "{0} > {1}: moments magnified", s.klu_r.toFixed(1), s.limit.toFixed(1)),
		},
	];
	if (s.klu_r <= KLU_R_MAX && isSecondOrderRequired(check)) {
		// Required for another reason than k lu / r: the backend's note says which (δs, stability).
		rows.push({ name: localize('femDesign.secondOrderRow', "Second-order analysis"), value: secondOrderReason(s) });
	}
	if (s.sway !== null) {
		const kind = s.sway ? localize('femDesign.sway', "sway") : localize('femDesign.nonsway', "nonsway");
		const value = typeof s.Q === 'number' ? localize('femDesign.storeyQ', "{0}, Q = {1}", kind, s.Q.toFixed(3)) : kind;
		// The storey's name in a row of its own: with the name or the value it squeezes the row.
		if (s.storey) {
			rows.push({ name: localize('femDesign.storey', "Storey"), value: s.storey });
		}
		rows.push({ name: localize('femDesign.frame', "Frame"), value });
	}
	const magnifiers = [
		...(typeof s.deltaNs === 'number' ? [localize('femDesign.deltaNs', "δns = {0}", s.deltaNs.toFixed(2))] : []),
		...(typeof s.deltaS === 'number' ? [localize('femDesign.deltaS', "δs = {0}", s.deltaS.toFixed(2))] : []),
	];
	if (s.sway && s.secondOrder === 'pDelta') {
		magnifiers.unshift(localize('femDesign.swayPDelta', "sway moments from the P-Delta analysis"));
	}
	if (magnifiers.length) {
		rows.push({ name: localize('femDesign.magnifier', "Moment magnifier"), value: magnifiers.join(', ') });
	}
	if (typeof s.Cm === 'number') {
		rows.push({
			name: localize('femDesign.cm', "Cm, Pc"),
			value: typeof s.Pc === 'number' ? localize('femDesign.cmPc', "{0}, {1} kN", s.Cm.toFixed(2), formatNumber(s.Pc)) : s.Cm.toFixed(2),
		});
	}
	if (typeof s.M2 === 'number') {
		rows.push({
			name: localize('femDesign.m2', "Moment M2"),
			value: typeof s.M2magnified === 'number'
				? localize('femDesign.m2Magnified', "{0} → {1}", formatKilonewtonMetres(s.M2), formatKilonewtonMetres(s.M2magnified))
				: formatKilonewtonMetres(s.M2),
		});
	}
	if (check.combination) {
		rows.push({ name: localize('femDesign.slenderCombination', "Governing combination"), value: check.combination });
	}
	return rows;
}

/**
 * Why a second-order analysis is required when k lu / r is within 100: δs over its 1.5 limit, or
 * else whatever the check's note says (an unstable storey, a column that buckles).
 */
function secondOrderReason(s: IFemSlenderness): string {
	return typeof s.deltaS === 'number' && s.deltaS > DELTA_S_MAX
		? localize('femDesign.secondOrderDeltaS', "required: δs = {0} > {1}", s.deltaS.toFixed(2), DELTA_S_MAX.toFixed(1))
		: localize('femDesign.secondOrderNote', "required (see the check)");
}

/** A slenderness check's heading: "Slenderness about y", or "Slenderness" without an axis. */
export function slendernessHeading(check: IFemDesignCheck): string {
	const axis = slendernessOf(check)?.axis ?? /^Slenderness about (?<axis>\w+)/.exec(check.name)?.groups?.axis;
	return axis ? localize('femDesign.slendernessAbout', "Slenderness about {0}", axis) : localize('femDesign.slendernessHeading', "Slenderness");
}
