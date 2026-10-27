/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IFemDesignReport } from './femDesign.js';
import { jointGoverning, jointOk, jointsOf } from './femSeismicDetailing.js';

/*
 * Design Reinforcement: the bars the backend proposes for the object types (from the steel the
 * members of each type require), the rows the engineer includes, and the edits of the part files
 * that apply them. Pure: the proposal page draws this model. Foundations are designed in
 * 9 Substructure (its Size Footings), never here: one feature lives in one part only.
 */

/**
 * `byType`: one set of bars per object type, from its most demanding member (members sharing
 * a type keep sharing it). `splitTypes`: members needing much less than the governing one move
 * to new types with lighter bars.
 */
export type DesignProposalMode = 'byType' | 'splitTypes';

/** Longitudinal bars of a beam face or a column perimeter (04 Objects `BarGroup`). */
export interface IDesignBarGroup {
	readonly position: 'top' | 'bottom' | 'sides' | 'perimeter';
	readonly count: number;
	readonly dia: number;
}

/** Stirrups, ties or a spiral (04 Objects `Transverse`). */
export interface IDesignTransverse {
	readonly type?: 'stirrup' | 'tie' | 'spiral';
	readonly dia: number;
	/** The spacing elsewhere (beyond the end zones, when they are given). */
	readonly spacing: number;
	readonly legs?: number;
	/** Column ties: the legs running along the profile's x (absent: as many as `legs`). */
	readonly legsX?: number | null;
	/**
	 * Seismic hoop zones (BNBC 2020 Part 6 Sec 8.3.4.3, 8.3.5.4, 8.3.10; 04 Objects
	 * `Transverse.zone`): the spacing so within the length lo from each joint face; absent or
	 * null: one spacing along the member.
	 */
	readonly zone?: IDesignTransverseZone | null;
	/** Hoops over the lap splices (04 Objects `Transverse.splice`). */
	readonly splice?: { readonly spacing: number } | null;
}

/** The end zones of a beam's or column's transverse bars (04 Objects `TransverseZone`). */
export interface IDesignTransverseZone {
	readonly spacing: number;
	/** The zone length lo from each joint face [mm]; absent or null: the length the code requires. */
	readonly length?: number | null;
	/** The first hoop from the joint face [mm]. */
	readonly first?: number | null;
}

/** One layer of bars of a slab or footing (04 Objects `BarMesh`). */
export interface IDesignBarMesh {
	readonly dia: number;
	readonly spacing: number;
}

/**
 * Bars as the backend reports them: an object type's `reinforcement` (linear or planar) with
 * its description under `text`, or a description alone; null for none.
 */
export type DesignBars = string | null | {
	readonly text?: string;
	readonly longitudinal?: readonly IDesignBarGroup[];
	readonly transverse?: IDesignTransverse | null;
	readonly bottomX?: IDesignBarMesh | null;
	readonly bottomY?: IDesignBarMesh | null;
	readonly topX?: IDesignBarMesh | null;
	readonly topY?: IDesignBarMesh | null;
};

/** A warning of the proposal: text (`"B1: section too small — ..."`), or text about one type or member. */
export type DesignProposalWarning = string | { readonly message: string; readonly type?: string; readonly member?: string };

/** `ok`: bars proposed; `unchanged`: the bars entered are those proposed; `tooSmall`: no bars make the section work. */
export type DesignProposalStatus = 'ok' | 'unchanged' | 'tooSmall';

/** Why no bars are proposed, and the next practical section ("try 300 x 550 mm ..."). */
export interface IDesignTooSmall {
	readonly reason: string;
	readonly suggestion?: string;
}

/**
 * A steel member type's section (design mode for steel): the lightest section of its family in
 * the section table that passes every check of the type's members, kg/m and utilisations as
 * the backend gives them.
 */
export interface IDesignSteelProposal {
	/** "W", "SHS", "UB", "ISMB". */
	readonly family: string;
	readonly current: string;
	/** Null when no section of the family passes. */
	readonly proposed: string | null;
	readonly currentMass?: number | null;
	readonly proposedMass?: number | null;
	readonly currentUtilisation?: number | null;
	readonly proposedUtilisation?: number | null;
	/** The check that governs the proposed section ("Compression, flexural buckling"). */
	readonly governingCheck?: string | null;
}

/** The bars proposed for one existing object type. */
export interface IDesignProposalType {
	readonly type: string;
	readonly name?: string;
	readonly kind?: string;
	readonly current: DesignBars;
	readonly proposed: DesignBars;
	readonly status?: DesignProposalStatus;
	/** The member whose demand sets the bars. */
	readonly governingMember?: string | null;
	/** Every member of this type, those the split moves to new types included. */
	readonly members?: readonly string[];
	/** Members whose own bars would be much lighter than the type's single-type bars (`byType`). */
	readonly overDesigned?: readonly string[];
	/**
	 * `splitTypes` only: the bars for all its members, as in `byType` mode; the type takes them
	 * when a member the split moves stays in it (its new type left out).
	 */
	readonly byType?: DesignBars;
	readonly tooSmall?: IDesignTooSmall | null;
	readonly notes?: readonly string[];
	readonly warnings?: readonly DesignProposalWarning[];
	/** A steel type: its section is proposed instead of bars (`current`, `proposed` then unused). */
	readonly steel?: IDesignSteelProposal | null;
	/**
	 * A steel type as design/steel_proposal.py propose_type gives it (the RC proposal's shape):
	 * its section family, with `current`/`proposed` `{section, family, text, profile, mass}` and
	 * the proposed section's utilisation by check. Read with {@link steelProposalOf}.
	 */
	readonly family?: string | null;
	readonly utilisation?: { readonly [check: string]: number } | null;
	/** False: left out of the apply (set by this page). */
	readonly apply?: boolean;
}

/** A type the `splitTypes` mode adds, copied from `from` with lighter bars. */
export interface IDesignProposalNewType {
	readonly type: string;
	readonly from: string;
	readonly kind?: string;
	readonly name?: string;
	readonly proposed: DesignBars;
	readonly governingMember?: string | null;
	readonly members: readonly string[];
	readonly warnings?: readonly DesignProposalWarning[];
	readonly apply?: boolean;
}

/** A building model member moved to another type (`splitTypes`); `source`: its floor plan item. */
export interface IDesignProposalReassign {
	readonly member: string;
	readonly from: string;
	readonly to: string;
	readonly source?: string | null;
	readonly apply?: boolean;
}

/** Content of the `saengine.design.proposal` result (and the `proposal` argument of apply). */
export interface IFemDesignProposal {
	readonly mode?: DesignProposalMode;
	readonly types: readonly IDesignProposalType[];
	readonly newTypes?: readonly IDesignProposalNewType[];
	readonly reassign?: readonly IDesignProposalReassign[];
	readonly warnings?: readonly DesignProposalWarning[];
	/** Information about the proposal as a whole (where the foundations are designed). */
	readonly notes?: readonly string[];
}

/** A change the apply made, as the backend says it. */
export type DesignApplyChange = string | { readonly message?: string; readonly text?: string };

/** Content of the `saengine.design.apply` result: the new text of each part file it was given. */
export interface IFemDesignApplyResult {
	readonly objectsText: string;
	readonly bimText?: string | null;
	readonly floorPlanText?: string | null;
	readonly changes?: readonly DesignApplyChange[];
}

/** One row of the proposal page: an object type, existing or new. */
export interface IDesignProposalRow {
	/** `type:<id>` for an existing type, `new:<id>` for one the split adds. */
	readonly key: string;
	readonly type: string;
	readonly name: string | undefined;
	readonly kind: string | undefined;
	/** The existing type a new one is copied from. */
	readonly from: string | undefined;
	readonly current: string;
	readonly proposed: string;
	/** The proposed bars differ from the current ones (always, for a new type). */
	readonly changed: boolean;
	/** No bars make the section work: nothing is proposed. */
	readonly tooSmall: boolean;
	readonly governingMember: string | undefined;
	readonly members: readonly string[];
	readonly overDesigned: readonly string[];
	readonly warnings: readonly string[];
	readonly notes: readonly string[];
	readonly included: boolean;
	/** It cannot be applied as the rows stand (it is left out, its toggle locked). */
	readonly blocked: boolean;
	/** A steel type's section proposal: its rows show sections, not bars. */
	readonly steel?: IDesignSteelProposal;
}

function formatMass(value: number): string {
	return localize('femProposal.mass', "{0} kg/m", value.toFixed(1));
}

/** A section of design/steel_proposal.py's `_label`: `{section, family, text, profile, mass}`. */
interface ISteelSectionLabel {
	readonly section?: string | null;
	readonly family?: string | null;
	readonly text?: string;
	readonly mass?: number | null;
}

function steelLabelOf(value: DesignBars | undefined): ISteelSectionLabel | undefined {
	if (!value || typeof value !== 'object') {
		return undefined;
	}
	const label = value as ISteelSectionLabel;
	return typeof label.section === 'string' || typeof label.mass === 'number' || typeof label.family === 'string' ? label : undefined;
}

/**
 * A type's steel section proposal: its `steel`, or read from the RC-shaped entry that
 * design/steel_proposal.py propose_type gives (`family`, `current`/`proposed` section labels,
 * `utilisation` by check); undefined for a concrete type.
 */
export function steelProposalOf(t: IDesignProposalType): IDesignSteelProposal | undefined {
	if (t.steel) {
		return t.steel;
	}
	const current = steelLabelOf(t.current);
	const proposed = steelLabelOf(t.proposed);
	if (!current && !proposed && typeof t.family !== 'string') {
		return undefined;
	}
	const byCheck = Object.entries(t.utilisation && typeof t.utilisation === 'object' ? t.utilisation : {})
		.filter(([, u]) => typeof u === 'number' && Number.isFinite(u))
		.sort((a, b) => b[1] - a[1]);
	return {
		family: t.family ?? current?.family ?? proposed?.family ?? '',
		current: current?.section ?? current?.text ?? describeBars(t.current),
		proposed: proposed ? proposed.section ?? proposed.text ?? null : null,
		currentMass: current?.mass,
		proposedMass: proposed?.mass,
		currentUtilisation: undefined,
		proposedUtilisation: proposed && byCheck.length ? byCheck[0][1] : undefined,
		governingCheck: proposed && byCheck.length ? byCheck[0][0] : undefined,
	};
}

/**
 * A steel row's facts: "41.7 → 32.9 kg/m (21% lighter), utilisation 0.62 → 0.91, governed by
 * Compression, flexural buckling".
 */
export function describeSteelProposal(steel: IDesignSteelProposal): string {
	const parts: string[] = [];
	const { currentMass, proposedMass, currentUtilisation, proposedUtilisation } = steel;
	if (typeof currentMass === 'number' && typeof proposedMass === 'number' && steel.proposed) {
		const change = currentMass > 0 ? Math.round((1 - proposedMass / currentMass) * 100) : 0;
		parts.push(change > 0
			? localize('femProposal.massLighter', "{0} → {1} ({2}% lighter)", formatMass(currentMass), formatMass(proposedMass), change)
			: change < 0
				? localize('femProposal.massHeavier', "{0} → {1} ({2}% heavier)", formatMass(currentMass), formatMass(proposedMass), -change)
				: localize('femProposal.massSame', "{0} → {1}", formatMass(currentMass), formatMass(proposedMass)));
	} else if (typeof currentMass === 'number') {
		parts.push(formatMass(currentMass));
	}
	if (typeof proposedUtilisation === 'number' && steel.proposed) {
		parts.push(typeof currentUtilisation === 'number'
			? localize('femProposal.steelUtilisation', "utilisation {0} → {1}", currentUtilisation.toFixed(2), proposedUtilisation.toFixed(2))
			: localize('femProposal.steelUtilisationOnly', "utilisation {0}", proposedUtilisation.toFixed(2)));
	} else if (typeof currentUtilisation === 'number') {
		parts.push(localize('femProposal.steelUtilisationOnly', "utilisation {0}", currentUtilisation.toFixed(2)));
	}
	if (steel.governingCheck) {
		parts.push(localize('femProposal.steelGoverning', "governed by {0}", steel.governingCheck));
	}
	return parts.join(', ');
}

function warningText(warning: DesignProposalWarning): string {
	return typeof warning === 'string' ? warning : warning.message;
}

/** The type or member a warning is about: its own field, or the `"B1: "` its text starts with. */
function warningSubject(warning: DesignProposalWarning): string | undefined {
	if (typeof warning !== 'string') {
		return warning.type ?? warning.member;
	}
	return /^(?<subject>[^\s:]+): /.exec(warning)?.groups?.subject;
}

/** A warning shown in its row: without the `"B1: "` the row already says. */
function rowWarningText(warning: DesignProposalWarning, subject: string): string {
	const text = warningText(warning);
	return typeof warning === 'string' && text.startsWith(`${subject}: `) ? text.slice(subject.length + 2) : text;
}

/** "Section too small: <reason>; try 300 x 550 mm ...". */
function tooSmallText(tooSmall: IDesignTooSmall): string {
	return tooSmall.suggestion
		? localize('femProposal.tooSmallTry', "Section too small: {0}; {1}", tooSmall.reason, tooSmall.suggestion)
		: localize('femProposal.tooSmall', "Section too small: {0}", tooSmall.reason);
}

function positionLabel(position: IDesignBarGroup['position']): string {
	switch (position) {
		case 'top': return localize('femProposal.top', "top");
		case 'bottom': return localize('femProposal.bottom', "bottom");
		case 'sides': return localize('femProposal.sides', "sides");
		case 'perimeter': return localize('femProposal.perimeter', "around");
	}
}

function meshText(mesh: IDesignBarMesh): string {
	return localize('femProposal.mesh', "Ø{0} @ {1}", mesh.dia, mesh.spacing);
}

/**
 * The spacing of stirrups or ties: "150", or with seismic hoop zones "100 over 600 at each end,
 * 150 elsewhere" ("100 within lo at each end, ..." when lo is the code's).
 */
export function describeTransverseSpacing(transverse: IDesignTransverse): string {
	const zone = transverse.zone?.spacing;
	const length = transverse.zone?.length;
	if (typeof zone !== 'number' || !(zone > 0) || zone === transverse.spacing) {
		return String(transverse.spacing);
	}
	return typeof length === 'number' && length > 0
		? localize('femProposal.zones', "{0} over {1} at each end, {2} elsewhere", zone, length, transverse.spacing)
		: localize('femProposal.zonesLo', "{0} within lo at each end, {1} elsewhere", zone, transverse.spacing);
}

/**
 * Bars as the drawings write them: the backend's description when it gives one, else "4 Ø20
 * top, 3 Ø16 bottom, Ø10 @ 150 (4 legs)"; a slab's layers "bottom Ø10 @ 150 X, Ø10 @ 200 Y; top
 * Ø10 @ 150 X".
 */
export function describeBars(bars: DesignBars | undefined): string {
	if (bars === null || bars === undefined) {
		return localize('femProposal.noBars', "no bars");
	}
	if (typeof bars === 'string') {
		return bars;
	}
	if (bars.text) {
		return bars.text;
	}
	const parts: string[] = [];
	for (const group of bars.longitudinal ?? []) {
		parts.push(localize('femProposal.group', "{0} Ø{1} {2}", group.count, group.dia, positionLabel(group.position)));
	}
	if (bars.transverse) {
		const t = bars.transverse;
		const spacing = describeTransverseSpacing(t);
		parts.push(t.legs && t.legs !== 2
			? localize('femProposal.transverseLegs', "Ø{0} @ {1} ({2} legs)", t.dia, spacing, t.legs)
			: localize('femProposal.transverse', "Ø{0} @ {1}", t.dia, spacing));
	}
	const layer = (label: string, x: IDesignBarMesh | null | undefined, y: IDesignBarMesh | null | undefined) => {
		const meshes = [
			...(x ? [localize('femProposal.meshX', "{0} X", meshText(x))] : []),
			...(y ? [localize('femProposal.meshY', "{0} Y", meshText(y))] : []),
		];
		if (meshes.length) {
			parts.push(localize('femProposal.layer', "{0} {1}", label, meshes.join(', ')));
		}
	};
	layer(localize('femProposal.bottomLayer', "bottom"), bars.bottomX, bars.bottomY);
	layer(localize('femProposal.topLayer', "top"), bars.topX, bars.topY);
	return parts.length ? parts.join(bars.bottomX || bars.bottomY || bars.topX || bars.topY ? '; ' : ', ') : localize('femProposal.noBars', "no bars");
}

/** "13 pass, 2 fail" (and the members not checked). */
export function describeCheckCounts(report: Pick<IFemDesignReport, 'summary'>): string {
	const { passed, failed, skipped } = report.summary;
	return skipped
		? localize('femProposal.countsSkipped', "{0} pass, {1} fail, {2} not checked", passed, failed, skipped)
		: localize('femProposal.counts', "{0} pass, {1} fail", passed, failed);
}

/** "13 pass, 2 fail → 15 pass, 0 fail". */
export function describeBeforeAfter(before: Pick<IFemDesignReport, 'summary'> | undefined, after: Pick<IFemDesignReport, 'summary'>): string {
	return before
		? localize('femProposal.beforeAfter', "{0} → {1}", describeCheckCounts(before), describeCheckCounts(after))
		: describeCheckCounts(after);
}

/** A change the apply reports, as text. */
export function describeChange(change: DesignApplyChange): string {
	return typeof change === 'string' ? change : change.message ?? change.text ?? '';
}

/**
 * A member, beam-column joint or check of the building as a whole (the seismic system permitted
 * in the category, the bar grades) that fails, and what fails.
 */
export interface IFailingItem {
	/** The member's or joint's id; the check's name for the building. */
	readonly id: string;
	/** The member's object type; undefined otherwise. */
	readonly type: string | undefined;
	readonly kind: 'member' | 'joint' | 'building';
	/** The governing failing check ("Deflection", "joint shear"); empty for the building. */
	readonly what: string;
}

/** The checks of the building as a whole in a design report (`seismic.checks`). */
function buildingChecks(report: IFemDesignReport): readonly { readonly name: string; readonly ok: boolean; readonly flag?: boolean }[] {
	const checks = (report as { readonly seismic?: { readonly checks?: unknown } | null }).seismic?.checks;
	return Array.isArray(checks) ? checks : [];
}

/** The building's checks, members and joints of `report` that fail, in that order. */
export function failingItems(report: IFemDesignReport | undefined): IFailingItem[] {
	if (!report) {
		return [];
	}
	const items: IFailingItem[] = [];
	for (const check of buildingChecks(report)) {
		if (!check.ok && !check.flag) {
			items.push({ id: check.name, type: undefined, kind: 'building', what: '' });
		}
	}
	for (const element of report.elements) {
		if (element.ok) {
			continue;
		}
		let worst: { readonly name: string; readonly utilisation: number } | undefined;
		for (const check of element.checks) {
			if (!check.ok && !check.flag && (!worst || check.utilisation > worst.utilisation)) {
				worst = check;
			}
		}
		items.push({ id: element.id, type: element.type, kind: 'member', what: worst?.name ?? localize('femProposal.failChecks', "checks") });
	}
	for (const joint of jointsOf(report)) {
		if (jointOk(joint)) {
			continue;
		}
		const check = jointGoverning(joint)?.check;
		items.push({
			id: joint.id, type: undefined, kind: 'joint',
			what: check === 'shear'
				? localize('femProposal.failJointShear', "joint shear")
				: check
					? localize('femProposal.failScwb', "strong column / weak beam")
					: localize('femProposal.failJoint', "joint checks"),
		});
	}
	return items;
}

/** "B5 (Deflection); joints J1, J2, J3 (joint shear)": the items grouped by what fails. */
export function describeFailing(items: readonly IFailingItem[]): string {
	const groups = new Map<string, { kind: IFailingItem['kind']; what: string; ids: string[] }>();
	for (const item of items) {
		const key = `${item.kind}|${item.what}`;
		const group = groups.get(key) ?? { kind: item.kind, what: item.what, ids: [] };
		group.ids.push(item.id);
		groups.set(key, group);
	}
	return [...groups.values()].map(g => {
		switch (g.kind) {
			case 'building': return g.ids.join('; ');
			case 'joint': return g.ids.length === 1
				? localize('femProposal.failingJoint', "joint {0} ({1})", g.ids[0], g.what)
				: localize('femProposal.failingJoints', "joints {0} ({1})", g.ids.join(', '), g.what);
			default: return localize('femProposal.failingMembers', "{0} ({1})", g.ids.join(', '), g.what);
		}
	}).join('; ');
}

/**
 * What the included rows leave failing: the building's checks and the joints (bars proposed per
 * type design neither) and the members whose type no included row changes.
 */
export function notFixedBy(rows: readonly IDesignProposalRow[], report: IFemDesignReport | undefined): IFailingItem[] {
	const changing = new Set(rows.filter(r => r.included).map(r => r.from ?? r.type));
	return failingItems(report).filter(item => item.kind !== 'member' || !item.type || !changing.has(item.type));
}

/** What a row of the proposal shows of its bars, and whether it can be applied. */
interface IRowEntry {
	readonly key: string;
	readonly tooSmall: boolean;
	readonly current: string;
	readonly proposed: string;
	readonly changed: boolean;
	readonly included: boolean;
}

/**
 * The proposal page's state: the proposal of each mode (fetched once each), the rows of the
 * mode shown, and the rows included in the apply (by default those whose bars change).
 */
export class DesignProposalModel {

	private readonly proposals = new Map<DesignProposalMode, IFemDesignProposal>();
	/** Rows the engineer toggled, per mode: key -> included. */
	private readonly toggled = new Map<DesignProposalMode, Map<string, boolean>>();
	/** The object types the design checks checked (undefined: not known yet). */
	private checkedTypes: ReadonlySet<string> | undefined;

	constructor(private _mode: DesignProposalMode = 'byType') { }

	get mode(): DesignProposalMode {
		return this._mode;
	}

	set mode(mode: DesignProposalMode) {
		this._mode = mode;
	}

	/** The proposal of the mode shown, once fetched. */
	get proposal(): IFemDesignProposal | undefined {
		return this.proposals.get(this._mode);
	}

	has(mode: DesignProposalMode): boolean {
		return this.proposals.has(mode);
	}

	/** Takes the proposal of `mode`; the rows' toggles start again from their defaults. */
	setProposal(mode: DesignProposalMode, proposal: IFemDesignProposal): void {
		this.proposals.set(mode, proposal);
		this.toggled.delete(mode);
	}

	/**
	 * The design checks the rows are proposed against: a type none of whose members they checked
	 * starts left out (X12 of the usability walk: unchecked members were applied by default).
	 */
	setChecks(report: IFemDesignReport | undefined): void {
		// Types without bars are not checked, but proposing their first bars is the point (X29).
		this.checkedTypes = report ? new Set([...report.elements.map(e => e.type), ...(report.summary.noBars ?? [])]) : undefined;
	}

	/** Whether the design checks checked no member of type `type` (false while not known). */
	private unchecked(type: string): boolean {
		return !!this.checkedTypes && !this.checkedTypes.has(type);
	}

	/** Forgets every proposal (the inputs changed). */
	clear(): void {
		this.proposals.clear();
		this.toggled.clear();
	}

	private entry(key: string, status: DesignProposalStatus | undefined, current: DesignBars, proposed: DesignBars, byDefault = true): IRowEntry {
		const tooSmall = status === 'tooSmall' || (status === undefined && (proposed === null || proposed === undefined));
		const currentText = describeBars(current);
		const proposedText = tooSmall ? localize('femProposal.noProposal', "no bars proposed") : describeBars(proposed);
		const changed = !tooSmall && (status ? status === 'ok' : currentText !== proposedText);
		return { key, tooSmall, current: currentText, proposed: proposedText, changed, included: changed && (this.toggled.get(this._mode)?.get(key) ?? byDefault) };
	}

	/** A row's warnings: why nothing is proposed, its own, and the general ones about it. */
	private warningsOf(proposal: IFemDesignProposal, subject: string, own: readonly DesignProposalWarning[] | undefined, tooSmall: IDesignTooSmall | null | undefined): string[] {
		const general = (proposal.warnings ?? []).filter(w => warningSubject(w) === subject);
		return [
			...(tooSmall ? [tooSmallText(tooSmall)] : []),
			...(own ?? []).map(warningText),
			// The backend repeats a type's "section too small" among the general warnings.
			...(tooSmall ? general.filter(w => !warningText(w).includes(tooSmall.reason)) : general).map(w => rowWarningText(w, subject)),
		];
	}

	/** The rows of the mode shown: the existing types, then the new ones. */
	rows(): IDesignProposalRow[] {
		const proposal = this.proposal;
		if (!proposal) {
			return [];
		}
		const newRows: IDesignProposalRow[] = [];
		for (const t of proposal.newTypes ?? []) {
			const source = proposal.types.find(s => s.type === t.from);
			newRows.push({
				...this.entry(`new:${t.type}`, 'ok', source?.current ?? null, t.proposed, !this.unchecked(t.from)),
				type: t.type, name: t.name, kind: t.kind ?? source?.kind, from: t.from,
				governingMember: t.governingMember ?? undefined,
				members: t.members,
				overDesigned: [],
				warnings: this.warningsOf(proposal, t.type, t.warnings, undefined),
				notes: [],
				blocked: false,
			});
		}
		const split = this.splitOf(proposal, newRows);
		const rows: IDesignProposalRow[] = [];
		for (const t of proposal.types) {
			const { moved, keptBack } = split.get(t.type) ?? { moved: new Set<string>(), keptBack: [] };
			// Members the split would move whose new type is left out stay: the type needs bars for
			// all its members again (the backend applies `byType` then), else it cannot be applied.
			const whole = keptBack.length > 0 && !!t.byType;
			const blocked = keptBack.length > 0 && !t.byType;
			const steel = steelProposalOf(t);
			const unchecked = this.unchecked(t.type);
			const steelEntry = steel && this.entry(`type:${t.type}`, steel.proposed ? t.status : 'tooSmall', steel.current, steel.proposed, !unchecked);
			const entry = steelEntry
				? { ...steelEntry, proposed: steelEntry.tooSmall ? localize('femProposal.noSteelSection', "no {0} section passes", steel.family) : steelEntry.proposed }
				: this.entry(`type:${t.type}`, whole ? undefined : t.status, t.current, whole && t.byType ? t.byType : t.proposed, !unchecked);
			const keptNote = whole
				? [localize('femProposal.keptBack', "Bars for all its members (the new type for {0} is left out).", keptBack.join(', '))]
				: [];
			rows.push({
				...entry,
				included: entry.included && !blocked,
				type: t.type, name: t.name, kind: t.kind, from: undefined,
				governingMember: t.governingMember ?? undefined,
				members: (t.members ?? []).filter(m => !moved.has(m)),
				overDesigned: (t.overDesigned ?? []).filter(m => !moved.has(m)),
				warnings: [
					...this.warningsOf(proposal, t.type, t.warnings, t.tooSmall),
					...(blocked ? [localize('femProposal.keptBackBlocked', "Its bars were designed without {0}: include their new type too, or propose with Keep Shared Types.", keptBack.join(', '))] : []),
					...(unchecked && entry.changed ? [localize('femProposal.unchecked', "The design checks checked none of its members: left out unless you include it.")] : []),
				],
				// The backend's notes are about the split's bars.
				notes: whole ? keptNote : t.notes ?? [],
				blocked,
				...(steel ? { steel } : {}),
			});
		}
		rows.push(...newRows);
		return rows;
	}

	/**
	 * Per existing type, the members the split moves out of it (their new type included) and
	 * those it would move but that stay (their new type left out), as the backend applies them.
	 */
	private splitOf(proposal: IFemDesignProposal, newRows: readonly IDesignProposalRow[]): Map<string, { moved: Set<string>; keptBack: string[] }> {
		const includedNew = new Set(newRows.filter(r => r.included).map(r => r.type));
		const split = new Map<string, { moved: Set<string>; keptBack: string[] }>();
		const add = (from: string, member: string, moves: boolean) => {
			let entry = split.get(from);
			if (!entry) {
				entry = { moved: new Set(), keptBack: [] };
				split.set(from, entry);
			}
			if (moves) {
				entry.moved.add(member);
			} else if (!entry.keptBack.includes(member)) {
				entry.keptBack.push(member);
			}
		};
		if (proposal.reassign) {
			for (const r of proposal.reassign) {
				add(r.from, r.member, includedNew.has(r.to));
			}
		} else {
			for (const t of proposal.newTypes ?? []) {
				for (const member of t.members) {
					add(t.from, member, includedNew.has(t.type));
				}
			}
		}
		return split;
	}

	/** The proposal's warnings about no row in particular. */
	generalWarnings(): string[] {
		const proposal = this.proposal;
		if (!proposal) {
			return [];
		}
		const subjects = new Set([...proposal.types.map(t => t.type), ...(proposal.newTypes ?? []).map(t => t.type)]);
		return (proposal.warnings ?? []).filter(w => {
			const subject = warningSubject(w);
			return subject === undefined || !subjects.has(subject);
		}).map(warningText);
	}

	/** The proposal's notes about it as a whole (where the foundations are designed). */
	generalNotes(): readonly string[] {
		return this.proposal?.notes ?? [];
	}

	/** Includes or leaves out a row of the mode shown (a row whose bars do not change stays out). */
	setIncluded(key: string, included: boolean): void {
		let toggled = this.toggled.get(this._mode);
		if (!toggled) {
			toggled = new Map();
			this.toggled.set(this._mode, toggled);
		}
		toggled.set(key, included);
	}

	/** Includes or leaves out every row of the mode shown. */
	setAllIncluded(included: boolean): void {
		for (const row of this.rows()) {
			this.setIncluded(row.key, included);
		}
	}

	/** The rows that would be applied. */
	includedRows(): IDesignProposalRow[] {
		return this.rows().filter(r => r.included);
	}

	/**
	 * The proposal to apply: every entry, those left out marked `apply: false` (the backend skips
	 * them), and the members moved to a new type left out marked so too (they keep their type,
	 * which the backend then gives its `byType` bars, as its row shows). Undefined when nothing
	 * is included.
	 */
	applyRequest(): IFemDesignProposal | undefined {
		const proposal = this.proposal;
		if (!proposal) {
			return undefined;
		}
		const included = new Set(this.includedRows().map(r => r.key));
		if (!included.size) {
			return undefined;
		}
		return {
			...proposal,
			mode: this._mode,
			types: proposal.types.map(t => ({ ...t, apply: included.has(`type:${t.type}`) })),
			...(proposal.newTypes ? { newTypes: proposal.newTypes.map(t => ({ ...t, apply: included.has(`new:${t.type}`) })) } : {}),
			...(proposal.reassign ? { reassign: proposal.reassign.map(r => ({ ...r, apply: included.has(`new:${r.to}`) })) } : {}),
		};
	}
}

/** The part files an apply edits, as they are now (undefined: not there, or not sent). */
export interface IDesignProposalTexts {
	readonly objectsText: string;
	readonly bimText: string | undefined;
	readonly floorPlanText?: string;
}

/** The part files an apply changes, by part id, with their new text. */
export type DesignProposalEdits = Partial<Record<'objects' | 'bim' | 'floorPlan', string>>;

/** The text edits an apply result makes: only of files it was given and whose text differs. */
export function proposalEdits(current: IDesignProposalTexts, result: IFemDesignApplyResult): DesignProposalEdits {
	const edits: DesignProposalEdits = {};
	const pairs = [
		['objects', current.objectsText, result.objectsText],
		['bim', current.bimText, result.bimText],
		['floorPlan', current.floorPlanText, result.floorPlanText],
	] as const;
	for (const [part, now, next] of pairs) {
		if (now !== undefined && typeof next === 'string' && next !== now) {
			edits[part] = next;
		}
	}
	return edits;
}
