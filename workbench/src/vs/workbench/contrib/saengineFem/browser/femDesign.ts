/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
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

export function runDesign(commandService: ICommandService, model: URI): Promise<IFemDesignReport | undefined> {
	return commandService.executeCommand<IFemDesignReport>(DESIGN_COMMAND, model);
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

function formatCheck(check: IFemDesignCheck): string {
	// Ratios (c/d, slenderness) keep two decimals: one would round a slab's c/d of 0.11 to 0.1.
	const values = check.unit
		? localize('femDesign.checkValues', "{0} of {1} {2}", check.demand.toFixed(1), check.capacity.toFixed(1), check.unit)
		: localize('femDesign.checkRatio', "{0} against {1}", check.demand.toFixed(2), check.capacity.toFixed(2));
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
	const checks = [...element.checks].sort((a, b) => Number(a.flag) - Number(b.flag) || b.utilisation - a.utilisation);
	const kind = element.kind === 'beam' ? localize('femDesign.beam', "beam")
		: element.kind === 'slab' ? localize('femDesign.slab', "slab")
			: element.kind === 'footing' ? localize('femDesign.footing', "footing")
				: localize('femDesign.column', "column");
	const verdict = element.ok ? localize('femDesign.passes', "passes") : localize('femDesign.fails', "fails");
	const text = localize('femDesign.element', "{0} ({1} {2}) {3}, utilisation {4}: {5}.", element.id, kind, element.type, verdict,
		formatUtilisation(element.utilisation), checks.map(formatCheck).join('; '));
	const governing = checks.find(c => !c.flag);
	return governing?.note ? localize('femDesign.governing', "{0} Governing: {1}.", text, governing.note) : text;
}
