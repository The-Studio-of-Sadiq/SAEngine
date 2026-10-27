/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatCheckValues, formatUtilisation, IFemDesignCheck, IFemDesignElement, IFemDesignReport } from './femDesign.js';
import { FemDetailingItem, isDetailingCheck } from './femSeismicDetailing.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';

/*
 * Steel members in the design checks (BNBC 2020 Part 6 Chapter 10): the backend adds a `steel`
 * object to a steel beam's, column's or brace's element of `saengine.fem.design`, with how it was
 * checked (the section's class, the unbraced length against Lp and Lr, Cb, the effective lengths,
 * the H1 interaction) and its end connections' checks. Its strength checks are the element's own
 * `checks` as for concrete, each naming its clause. Pure: the properties panel draws these items.
 */

/** A section element's width-thickness class in flexure (Table B4.1b) or compression (Table B4.1a). */
export type SteelElementClass = 'compact' | 'noncompact' | 'slender' | 'nonslender';

/** The section's classes, and the width-thickness ratios against their limits when the backend gives them. */
export interface IFemSteelClass {
	readonly flange?: SteelElementClass | null;
	readonly web?: SteelElementClass | null;
	/** In axial compression: "nonslender" or "slender". */
	readonly compression?: SteelElementClass | null;
	/** λ of the flange (b/t) and of the web (h/tw). */
	readonly flangeRatio?: number | null;
	readonly webRatio?: number | null;
	/** λp, λr of the flange and of the web. */
	readonly flangeLimits?: readonly [number, number] | null;
	readonly webLimits?: readonly [number, number] | null;
}

/** Lengths in mm. */
export interface IFemSteelLengths {
	/** The member's length between its nodes. */
	readonly L?: number | null;
	/** The unbraced length for lateral-torsional buckling. */
	readonly Lb?: number | null;
	readonly Lp?: number | null;
	readonly Lr?: number | null;
	/** The effective length factors about the major (x) and minor (y) axes. */
	readonly Kx?: number | null;
	readonly Ky?: number | null;
	/** The governing slenderness KL/r, and its limit (200 in compression, 300 in tension, as advised). */
	readonly KLr?: number | null;
	readonly KLrLimit?: number | null;
}

/** The H1 interaction of axial force and bending, when it governs or is reported. */
export interface IFemSteelInteraction {
	/** "H1-1a" (Pr/Pc ≥ 0.2) or "H1-1b". */
	readonly equation: string;
	readonly PrPc: number;
	readonly MrxMcx: number;
	readonly MryMcy: number;
	readonly value: number;
	readonly combination?: string | null;
}

/** An end connection of the member: a shear tab, an end plate, a brace's gusset. */
export interface IFemSteelConnection {
	/** "Shear tab", "End plate", "Gusset plate". */
	readonly name: string;
	/** "i", "j", or "both" (the same at both ends). */
	readonly end?: string | null;
	/** "4 M20 8.8 bolts, 10 mm plate, 6 mm fillet welds". */
	readonly description?: string | null;
	/** Bolt shear, bearing, block shear, weld, plate yielding: as the member's checks. */
	readonly checks: readonly IFemDesignCheck[];
	/** What the check assumes (the backend says it: "pinned, eccentricity e = 75 mm"). */
	readonly assumptions?: readonly string[];
}

/** How a steel member was checked. */
export interface IFemSteelDesign {
	/** "W14X90", "SHS 100x100x6", "UB 406x178x60". */
	readonly section: string;
	/** "W", "SHS", "RHS", "CHS", "C", "L", "UB", "UC", "ISMB". */
	readonly family?: string | null;
	/** Material id or name ("A992"), with Fy and Fu [MPa]. */
	readonly material?: string | null;
	readonly Fy?: number | null;
	readonly Fu?: number | null;
	/** Mass per metre [kg/m]. */
	readonly mass?: number | null;
	readonly sectionClass?: IFemSteelClass | null;
	readonly lengths?: IFemSteelLengths | null;
	/** The lateral-torsional buckling modification factor. */
	readonly Cb?: number | null;
	/** The zone of lateral-torsional buckling: Lb ≤ Lp yielding; ≤ Lr inelastic; else elastic. */
	readonly ltb?: 'yielding' | 'inelastic' | 'elastic' | null;
	readonly interaction?: IFemSteelInteraction | null;
	readonly connections?: readonly IFemSteelConnection[];
	readonly notes?: readonly string[];
	/** The section's compression elements as the backend describes them ("flange λ = 8.9 (λr = 13.5, case 3): compact"), when not given as {@link sectionClass} ratios. */
	readonly classElements?: readonly string[];
	/** The unbraced and effective lengths as the backend describes them ("unbraced lengths: about x 6.00 m, ..."). */
	readonly lengthsText?: string | null;
}

/**
 * The entry stream T's design_steel_member gives (python/src/saengine/design/steel/members.py):
 * `section` is an object, `lengths` a sentence; Lb, Lp, Lr, Cb, the flexure classes, KL/r and
 * the H1 ratios are in its checks' notes. Connections (design/steel_connections.py
 * check_connection) are `{connection: 'finPlate'|'endPlate'|'gusset', checks, ok, assumptions}`.
 */
interface IFemSteelMemberEntry {
	readonly section?: {
		readonly family?: string;
		readonly label?: string;
		readonly class?: string;
		readonly elements?: readonly string[];
		readonly massPerMetre?: number;
		readonly notes?: readonly string[];
	} | string | null;
	readonly lengths?: string | IFemSteelLengths | null;
	readonly material?: string | null;
	readonly connections?: readonly IFemSteelConnectionEntry[];
}

/** A connection as design/steel_connections.py check_connection gives it, or as {@link IFemSteelConnection}. */
interface IFemSteelConnectionEntry {
	readonly name?: string;
	readonly connection?: string;
	readonly end?: string | null;
	readonly description?: string | null;
	readonly checks?: readonly IFemDesignCheck[];
	readonly assumptions?: readonly string[];
}

/** A design element that may carry a steel member's design. */
export type FemSteelElement = IFemDesignElement & { readonly steel?: IFemSteelDesign | null };

/** A check of the design report, with the clause it was worked to (the backend's text: "BNBC 2020 Part 6 Sec 10.5.3"). */
export type FemClauseCheck = IFemDesignCheck & { readonly clause?: string | null };

/** The checks of a member's connections are named so in its own checks, if the backend repeats them there. */
const CONNECTION_PREFIX = 'Connection';

const steelCache = new WeakMap<IFemDesignElement, IFemSteelDesign | null>();

/**
 * The steel design of an element, if it is a steel member: its `steel` object, or read from the
 * member entry design_steel_member gives (`section: {label, ...}` with the details in the checks).
 */
export function steelOf(element: IFemDesignElement): IFemSteelDesign | undefined {
	let steel = steelCache.get(element);
	if (steel === undefined) {
		const given = (element as FemSteelElement).steel;
		steel = given && typeof given.section === 'string' ? given : fromMemberEntry(element) ?? null;
		steelCache.set(element, steel);
	}
	return steel ?? undefined;
}

export function isSteelElement(element: IFemDesignElement): boolean {
	return steelOf(element) !== undefined;
}

/** "Fin plate", "End plate", "Gusset plate": the label of design/steel_connections.py's connection kinds. */
function connectionKindLabel(kind: string | undefined): string {
	switch (kind) {
		case 'finPlate': return localize('femSteel.finPlate', "Fin plate (shear tab)");
		case 'endPlate': return localize('femSteel.endPlate', "End plate");
		case 'gusset': return localize('femSteel.gusset', "Brace gusset");
		default: return kind ?? localize('femSteel.connection', "Connection");
	}
}

function readConnection(entry: IFemSteelConnectionEntry): IFemSteelConnection {
	return {
		name: entry.name ?? connectionKindLabel(entry.connection),
		end: entry.end,
		description: entry.description,
		checks: entry.checks ?? [],
		assumptions: entry.assumptions,
	};
}

/** The first number a pattern captures in a text, or undefined. */
function numberIn(text: string | undefined, pattern: RegExp): number | undefined {
	const match = text?.match(pattern);
	const value = match?.groups?.value !== undefined ? Number(match.groups.value) : NaN;
	return Number.isFinite(value) ? value : undefined;
}

const FLEXURE_ELEMENT = /(?<part>flange|web) λ = (?<ratio>[\d.]+) \(λp = (?<lp>[\d.]+), λr = (?<lr>[\d.]+), case \d+\): (?<cls>compact|noncompact|slender)/g;

function readClass(value: string | undefined): SteelElementClass | undefined {
	return value === 'compact' || value === 'noncompact' || value === 'slender' || value === 'nonslender' ? value : undefined;
}

/** A member entry of design_steel_member as {@link IFemSteelDesign}; undefined when it is not one. */
function fromMemberEntry(element: IFemDesignElement): IFemSteelDesign | undefined {
	const entry = element as IFemDesignElement & IFemSteelMemberEntry;
	const section = entry.section;
	if (!section || typeof section !== 'object' || typeof section.label !== 'string') {
		return undefined;
	}
	const named = (start: string) => element.checks.find(c => c.name.startsWith(start));
	// Flexure about the major axis: the classes of its flange and web, and the LTB lengths and Cb.
	const flexure = named('Flexure about x');
	const sectionClass: { flange?: SteelElementClass; web?: SteelElementClass; flangeRatio?: number; webRatio?: number; flangeLimits?: [number, number]; webLimits?: [number, number]; compression?: SteelElementClass } = {};
	for (const match of flexure?.note.matchAll(FLEXURE_ELEMENT) ?? []) {
		const groups = match.groups!;
		const cls = readClass(groups.cls);
		const limits: [number, number] = [Number(groups.lp), Number(groups.lr)];
		if (groups.part === 'flange' && !sectionClass.flange) {
			Object.assign(sectionClass, { flange: cls, flangeRatio: Number(groups.ratio), flangeLimits: limits });
		} else if (groups.part === 'web' && !sectionClass.web) {
			Object.assign(sectionClass, { web: cls, webRatio: Number(groups.ratio), webLimits: limits });
		}
	}
	const overall = readClass(section.class);
	if (overall) {
		// Under uniform compression an element is only slender or not (λr alone).
		sectionClass.compression = overall === 'slender' ? 'slender' : 'nonslender';
	}
	const note = flexure?.note;
	const slenderness = named('Slenderness KL/r');
	const kText = slenderness?.note;
	const lengths: IFemSteelLengths = {
		Lb: numberIn(note, /Lb = (?<value>[\d.]+) mm/),
		Lp: numberIn(note, /Lp = (?<value>[\d.]+)/),
		Lr: numberIn(note, /Lr = (?<value>[\d.]+)/),
		Kx: numberIn(kText, /K = (?<value>[\d.]+) \//),
		Ky: numberIn(kText, /K = [\d.]+ \/ (?<value>[\d.]+)/),
		KLr: slenderness?.demand,
		KLrLimit: slenderness?.capacity,
	};
	const h1 = named('Axial force and flexure');
	const h1Note = h1?.note;
	const pr = numberIn(h1Note, /Pr = (?<value>[\d.]+)/);
	const pc = numberIn(h1Note, /Pc = (?<value>[\d.]+)/);
	const mrx = numberIn(h1Note, /Mrx = (?<value>[\d.]+)/);
	const mcx = numberIn(h1Note, /Mcx = (?<value>[\d.]+)/);
	const mry = numberIn(h1Note, /Mry = (?<value>[\d.]+)/);
	const mcy = numberIn(h1Note, /Mcy = (?<value>[\d.]+)/);
	const equation = h1Note?.match(/Eq (?<eq>[\d.]+[ab]?)/)?.groups?.eq;
	const ratio = (a: number | undefined, b: number | undefined) => isNumber(a) && isNumber(b) && b > 0 ? a / b : 0;
	const interaction: IFemSteelInteraction | undefined = h1 && isNumber(pc) ? {
		equation: equation ? localize('femSteel.eq', "Eq {0}", equation) : '',
		PrPc: ratio(pr, pc), MrxMcx: ratio(mrx, mcx), MryMcy: ratio(mry, mcy),
		value: h1.utilisation, combination: h1.combination,
	} : undefined;
	const fy = numberIn(named('Tension: yielding')?.note, /Fy = (?<value>[\d.]+) MPa/);
	const fu = numberIn(named('Tension: rupture')?.note, /Fu = (?<value>[\d.]+) MPa/);
	const hasClass = !!(sectionClass.flange || sectionClass.web);
	return {
		section: section.label,
		family: section.family,
		material: entry.material ?? undefined,
		Fy: fy, Fu: fu,
		mass: section.massPerMetre,
		sectionClass,
		lengths,
		Cb: numberIn(note, /Cb = (?<value>[\d.]+)/),
		interaction,
		connections: (entry.connections ?? []).map(readConnection),
		notes: section.notes,
		classElements: hasClass ? undefined : section.elements,
		lengthsText: typeof entry.lengths === 'string' ? entry.lengths : undefined,
	};
}

/** The names of the checks of a member's connections (if the backend repeats them among the member's own checks). */
function connectionCheckNames(element: IFemDesignElement): ReadonlySet<string> {
	return new Set((steelOf(element)?.connections ?? []).flatMap(c => c.checks.map(check => check.name)));
}

/**
 * Whether a member's check is a connection's (shown under Connections, not with the member's, and
 * not counted for its governing check): named "Connection…", or one of its connections' checks.
 */
export function isConnectionCheck(check: IFemDesignCheck, connectionChecks?: ReadonlySet<string>): boolean {
	return check.name.startsWith(CONNECTION_PREFIX) || !!connectionChecks?.has(check.name);
}

/** The member's own checks that are its connections'. */
export function memberConnectionChecks(element: IFemDesignElement): (check: IFemDesignCheck) => boolean {
	const names = connectionCheckNames(element);
	return check => isConnectionCheck(check, names);
}

function isNumber(value: unknown): value is number {
	return typeof value === 'number' && Number.isFinite(value);
}

function mm(value: number): string {
	return localize('femSteel.mm', "{0} mm", formatNumber(value));
}

function classLabel(value: SteelElementClass): string {
	switch (value) {
		case 'compact': return localize('femSteel.compact', "compact");
		case 'noncompact': return localize('femSteel.noncompact', "noncompact");
		case 'slender': return localize('femSteel.slender', "slender");
		case 'nonslender': return localize('femSteel.nonslender', "nonslender");
	}
}

/** "compact (b/t 7.2, λp 9.2, λr 24.1)". */
function elementClass(value: SteelElementClass, ratio: number | null | undefined, limits: readonly [number, number] | null | undefined): string {
	const label = classLabel(value);
	if (!isNumber(ratio)) {
		return label;
	}
	return limits
		? localize('femSteel.classRatioLimits', "{0} (λ {1}, λp {2}, λr {3})", label, ratio.toFixed(1), limits[0].toFixed(1), limits[1].toFixed(1))
		: localize('femSteel.classRatio', "{0} (λ {1})", label, ratio.toFixed(1));
}

function ltbLabel(zone: NonNullable<IFemSteelDesign['ltb']>): string {
	switch (zone) {
		case 'yielding': return localize('femSteel.ltbYielding', "Lb ≤ Lp: yielding, no lateral-torsional buckling");
		case 'inelastic': return localize('femSteel.ltbInelastic', "Lp < Lb ≤ Lr: inelastic lateral-torsional buckling");
		case 'elastic': return localize('femSteel.ltbElastic', "Lb > Lr: elastic lateral-torsional buckling");
	}
}

/** The zone of lateral-torsional buckling: the backend's, else from Lb, Lp and Lr. */
export function ltbZone(steel: IFemSteelDesign): IFemSteelDesign['ltb'] {
	if (steel.ltb) {
		return steel.ltb;
	}
	const { Lb, Lp, Lr } = steel.lengths ?? {};
	if (!isNumber(Lb) || !isNumber(Lp) || !isNumber(Lr)) {
		return undefined;
	}
	return Lb <= Lp ? 'yielding' : Lb <= Lr ? 'inelastic' : 'elastic';
}

/** The governing strength check of a member (not a flag, a connection's or a seismic detailing one). */
export function governingSteelCheck(element: IFemDesignElement): FemClauseCheck | undefined {
	const isConnection = memberConnectionChecks(element);
	return [...element.checks].filter(c => !c.flag && !isConnection(c) && !isDetailingCheck(c)).sort((a, b) => b.utilisation - a.utilisation)[0];
}

/** "Flexure, lateral-torsional buckling 0.86 (BNBC 2020 Part 6 Sec 10.6.2)". */
function describeGoverning(check: FemClauseCheck): string {
	return check.clause
		? localize('femSteel.governingClause', "{0} {1} ({2})", check.name, formatUtilisation(check.utilisation), check.clause)
		: localize('femSteel.governingNoClause', "{0} {1}", check.name, formatUtilisation(check.utilisation));
}

/** "end i", "end j", "both ends". */
function endLabel(end: string | null | undefined): string | undefined {
	switch (end) {
		case 'i': return localize('femSteel.endI', "end i");
		case 'j': return localize('femSteel.endJ', "end j");
		case 'both': return localize('femSteel.endBoth', "both ends");
		default: return end ?? undefined;
	}
}

function checkItem(check: FemClauseCheck): FemDetailingItem {
	const values = formatCheckValues(check);
	const detail = [values, ...(check.combination ? [check.combination] : []), ...(check.clause ? [check.clause] : [])].join(', ');
	return { kind: 'check', name: check.name.startsWith(CONNECTION_PREFIX) ? check.name.slice(CONNECTION_PREFIX.length).replace(/^[\s:,-]+/, '') || check.name : check.name, value: formatUtilisation(check.utilisation), detail, ok: check.ok, note: check.note || undefined };
}

/** Whether every check of a connection passes. */
export function connectionOk(connection: IFemSteelConnection): boolean {
	return connection.checks.every(c => c.ok || c.flag);
}

/**
 * A steel member's part of the properties panel: its section and material, the section's
 * class, the lengths and Cb of lateral-torsional buckling, KL/r, the H1 interaction and the
 * governing check with its clause; then its connections' checks with their assumptions. Empty
 * for a member that is not steel.
 */
export function steelSection(element: IFemDesignElement): FemDetailingItem[] {
	const steel = steelOf(element);
	if (!steel) {
		return [];
	}
	const items: FemDetailingItem[] = [{ kind: 'heading', text: localize('femSteel.heading', "Steel Member") }];
	items.push({
		kind: 'row', name: localize('femSteel.section', "Section"),
		value: isNumber(steel.mass) ? localize('femSteel.sectionMass', "{0} ({1} kg/m)", steel.section, steel.mass.toFixed(1)) : steel.section,
	});
	if (steel.material || isNumber(steel.Fy)) {
		const strength = isNumber(steel.Fy)
			? isNumber(steel.Fu) ? localize('femSteel.fyFu', "Fy {0} MPa, Fu {1} MPa", steel.Fy.toFixed(0), steel.Fu.toFixed(0)) : localize('femSteel.fy', "Fy {0} MPa", steel.Fy.toFixed(0))
			: undefined;
		items.push({
			kind: 'row', name: localize('femSteel.material', "Material"),
			value: steel.material && strength ? localize('femSteel.materialStrength', "{0}, {1}", steel.material, strength) : steel.material ?? strength ?? '',
		});
	}
	const cls = steel.sectionClass;
	if (cls?.flange) {
		items.push({ kind: 'row', name: localize('femSteel.flange', "Flange"), value: elementClass(cls.flange, cls.flangeRatio, cls.flangeLimits), ok: cls.flange !== 'slender' });
	}
	if (cls?.web) {
		items.push({ kind: 'row', name: localize('femSteel.web', "Web"), value: elementClass(cls.web, cls.webRatio, cls.webLimits), ok: cls.web !== 'slender' });
	}
	if (cls?.compression) {
		items.push({ kind: 'row', name: localize('femSteel.inCompression', "In compression"), value: classLabel(cls.compression), ok: cls.compression !== 'slender' });
	}
	for (const line of steel.classElements ?? []) {
		items.push({ kind: 'note', text: line });
	}
	if (steel.lengthsText) {
		items.push({ kind: 'note', text: steel.lengthsText });
	}
	const lengths = steel.lengths ?? {};
	if (isNumber(lengths.Lb)) {
		const limits = isNumber(lengths.Lp) && isNumber(lengths.Lr) ? localize('femSteel.lpLr', "Lp {0}, Lr {1}", mm(lengths.Lp), mm(lengths.Lr)) : undefined;
		items.push({ kind: 'row', name: localize('femSteel.lb', "Unbraced length Lb"), value: limits ? localize('femSteel.lbLimits', "{0} ({1})", mm(lengths.Lb), limits) : mm(lengths.Lb) });
	}
	const zone = ltbZone(steel);
	if (zone) {
		items.push({ kind: 'row', name: localize('femSteel.ltb', "Lateral-torsional buckling"), value: ltbLabel(zone) });
	}
	if (isNumber(steel.Cb)) {
		items.push({ kind: 'row', name: localize('femSteel.cb', "Cb"), value: steel.Cb.toFixed(2) });
	}
	if (isNumber(lengths.Kx) || isNumber(lengths.Ky)) {
		const k = [
			...(isNumber(lengths.Kx) ? [localize('femSteel.kx', "Kx {0}", lengths.Kx.toFixed(2))] : []),
			...(isNumber(lengths.Ky) ? [localize('femSteel.ky', "Ky {0}", lengths.Ky.toFixed(2))] : []),
		];
		items.push({ kind: 'row', name: localize('femSteel.k', "Effective length factor"), value: k.join(', ') });
	}
	if (isNumber(lengths.KLr)) {
		const over = isNumber(lengths.KLrLimit) && lengths.KLr > lengths.KLrLimit;
		items.push({
			kind: 'row', name: localize('femSteel.klr', "KL / r"),
			value: isNumber(lengths.KLrLimit)
				? over
					? localize('femSteel.klrOver', "{0} > {1}", lengths.KLr.toFixed(1), lengths.KLrLimit.toFixed(0))
					: localize('femSteel.klrWithin', "{0} ≤ {1}", lengths.KLr.toFixed(1), lengths.KLrLimit.toFixed(0))
				: lengths.KLr.toFixed(1),
			ok: !over,
		});
	}
	const h1 = steel.interaction;
	if (h1) {
		items.push({
			kind: 'row', name: localize('femSteel.interaction', "Interaction {0}", h1.equation),
			value: localize('femSteel.interactionValue', "{0} (Pr/Pc {1}, Mrx/Mcx {2}, Mry/Mcy {3})", formatUtilisation(h1.value), h1.PrPc.toFixed(2), h1.MrxMcx.toFixed(2), h1.MryMcy.toFixed(2)),
			ok: h1.value <= 1,
		});
	}
	const governing = governingSteelCheck(element);
	if (governing) {
		items.push({ kind: 'row', name: localize('femSteel.governing', "Governing"), value: describeGoverning(governing), ok: governing.ok });
	}
	for (const note of steel.notes ?? []) {
		items.push({ kind: 'note', text: note });
	}

	// The connections: those the backend gives, and any connection checks among the member's own.
	const connections = [...(steel.connections ?? [])];
	const loose = element.checks.filter(c => isConnectionCheck(c));
	if (loose.length && !connections.length) {
		connections.push({ name: localize('femSteel.connection', "Connection"), checks: loose });
	}
	if (connections.length) {
		items.push({ kind: 'heading', text: localize('femSteel.connections', "Connections") });
		for (const connection of connections) {
			const end = endLabel(connection.end);
			const verdict = connectionOk(connection) ? localize('femSteel.connPasses', "passes") : localize('femSteel.connFails', "fails");
			items.push({ kind: 'subheading', text: end ? localize('femSteel.connAtEnd', "{0}, {1}: {2}", connection.name, end, verdict) : localize('femSteel.connNoEnd', "{0}: {1}", connection.name, verdict) });
			if (connection.description) {
				items.push({ kind: 'note', text: connection.description });
			}
			for (const check of [...connection.checks].sort((a, b) => b.utilisation - a.utilisation)) {
				items.push(checkItem(check));
			}
			if (connection.assumptions?.length) {
				items.push({ kind: 'note', text: localize('femSteel.assumes', "Assumes: {0}.", connection.assumptions.join('; ')) });
			}
		}
	}
	return items;
}

/** The steel members of a report, and how many fail: undefined when there are none. */
export function steelSummary(report: IFemDesignReport): { readonly checked: number; readonly failed: number; readonly connectionsFailing: readonly string[] } | undefined {
	const steel = report.elements.filter(isSteelElement);
	if (!steel.length) {
		return undefined;
	}
	const connectionsFailing = steel.filter(e => {
		const isConnection = memberConnectionChecks(e);
		return (steelOf(e)?.connections ?? []).some(c => !connectionOk(c)) || e.checks.some(c => isConnection(c) && !c.ok && !c.flag);
	}).map(e => e.id);
	return { checked: steel.length, failed: steel.filter(e => !e.ok).length, connectionsFailing };
}

/** "12 checked, 1 fails" (with the members whose connections fail). */
export function describeSteelSummary(report: IFemDesignReport): string | undefined {
	const summary = steelSummary(report);
	if (!summary) {
		return undefined;
	}
	const counts = localize('femSteel.summary', "{0} checked, {1} fail", summary.checked, summary.failed);
	return summary.connectionsFailing.length
		? localize('femSteel.summaryConnections', "{0}; connections fail at {1}", counts, summary.connectionsFailing.join(', '))
		: counts;
}

