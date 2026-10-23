/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatUtilisation, IFemDesignCheck, IFemDesignElement, IFemDesignReport } from './femDesign.js';

/*
 * Seismic detailing of reinforced-concrete moment frames (BNBC 2020 Part 6 Sec 8.3): what the
 * design checks report of it, as the FEM editor's Properties panel and its joints view show it.
 * Pure view models over the backend's design report (`saengine.design.design_report`); every
 * field is optional, so a report without seismic detailing (an older backend, a building in
 * SDC A) shows nothing of it.
 */

/** The prefix of a member's seismic detailing checks ("Detailing: hoop spacing in lo"). */
export const DETAILING_PREFIX = 'Detailing:';

/**
 * The column-to-beam flexural strength ratio a special moment frame joint needs, ΣMnc ≥ 1.2
 * ΣMnb (BNBC 2020 Part 6 Sec 8.3.5.2(b), Eq 6.8.5): used when the backend gives the ratio only.
 */
export const SCWB_MIN_RATIO = 1.2;

/** A detailing check, as the backend may give it: an ordinary check with the clause it applies. */
export interface IFemDetailingCheck extends IFemDesignCheck {
	/** "Sec 8.3.5.4(b)". */
	readonly clause?: string | null;
}

/** The hoop zones of a beam or column end (lengths and spacings in mm). */
export interface IFemDetailingZones {
	/** The length lo from each joint face over which hoops are required. */
	readonly lo?: number | null;
	/** The largest hoop spacing so within lo. */
	readonly so?: number | null;
	/** The largest spacing elsewhere (beyond lo). */
	readonly outside?: number | null;
}

/** A member's seismic detailing summary (`member.detailing` of the design report). */
export interface IFemMemberDetailing {
	/** "special", "intermediate", "ordinary" (or "SMF", "IMF", "OMF", "SMRF", ...). */
	readonly frameType?: string | null;
	/** The building's Seismic Design Category ("D"). */
	readonly sdc?: string | null;
	readonly zones?: IFemDetailingZones | null;
	/** The capacity-design shear [kN] (probable moments at the ends plus gravity). */
	readonly Ve?: number | null;
	/** The design shear strength [kN]. */
	readonly phiVn?: number | null;
	readonly clause?: string | null;
	readonly notes?: readonly string[];
}

/** A strong-column/weak-beam check in one direction: the ratio ΣMnc / ΣMnb, or its sums. */
export type FemScwb = number | null | {
	readonly ratio?: number | null;
	/** Sum of the columns' nominal flexural strengths at the joint faces [kN·m]. */
	readonly sumMnc?: number | null;
	/** Sum of the beams' nominal flexural strengths at the joint faces [kN·m]. */
	readonly sumMnb?: number | null;
	/** The ratio required (1.2). */
	readonly required?: number | null;
	readonly utilisation?: number | null;
	/** True when the rule does not apply: neither column carries more than 0.1 Ag f'c (Sec 8.3.5.2(a)); the ratio is reported only. */
	readonly notRequired?: boolean | null;
};

/** Whether a strong-column/weak-beam ratio is reported only (Sec 8.3.5.2(a)). */
function scwbNotRequired(scwb: FemScwb | undefined): boolean {
	return !!scwb && typeof scwb === 'object' && scwb.notRequired === true;
}

/** A beam-column joint of a moment frame (`report.joints` of the design report). */
export interface IFemJoint {
	readonly id: string;
	/** The analysis node at the joint (its id, or its name). */
	readonly node?: number | string | null;
	/** The column (building model id) the joint is checked with. */
	readonly column?: string | null;
	readonly beams?: readonly string[];
	readonly type?: 'interior' | 'exterior' | 'corner' | string;
	readonly scwb?: { readonly x?: FemScwb; readonly y?: FemScwb } | null;
	readonly shear?: {
		/** Joint shear demand [kN]. */
		readonly Vj?: number | null;
		/** Design joint shear strength [kN]. */
		readonly phiVn?: number | null;
		readonly utilisation?: number | null;
	} | null;
	/** The governing utilisation, if the backend works it out. */
	readonly utilisation?: number | null;
	readonly ok?: boolean | null;
	readonly notes?: readonly string[] | string | null;
}

/** The design report with the seismic detailing fields this view reads. */
export type FemDetailingReport = IFemDesignReport & { readonly joints?: readonly IFemJoint[] | null };

/** A designed member with its detailing summary. */
export type FemDetailingElement = IFemDesignElement & { readonly detailing?: IFemMemberDetailing | null };

/** One line of the Properties panel's seismic detailing section. */
export type FemDetailingItem =
	| { readonly kind: 'heading' | 'subheading' | 'note'; readonly text: string }
	| { readonly kind: 'row'; readonly name: string; readonly value: string; readonly ok?: boolean }
	| { readonly kind: 'check'; readonly name: string; readonly value: string; readonly detail: string; readonly ok: boolean; readonly note?: string };

/** The groups a member's detailing checks are shown in, in this order. */
export type FemDetailingGroup = 'dimensions' | 'longitudinal' | 'transverse' | 'splices' | 'shear' | 'joints' | 'other';

const GROUP_ORDER: readonly FemDetailingGroup[] = ['dimensions', 'longitudinal', 'transverse', 'splices', 'shear', 'joints', 'other'];

/** Whether a check is one of the seismic detailing checks. */
export function isDetailingCheck(check: IFemDesignCheck): boolean {
	return check.name.startsWith(DETAILING_PREFIX);
}

/** A detailing check's name without the prefix ("hoop spacing in lo"), capitalised. */
export function detailingName(check: IFemDesignCheck): string {
	const name = check.name.startsWith(DETAILING_PREFIX) ? check.name.slice(DETAILING_PREFIX.length).trim() : check.name;
	return name ? name[0].toUpperCase() + name.slice(1) : check.name;
}

/** Which group a detailing check belongs to, from its name. */
export function detailingGroup(check: IFemDesignCheck): FemDetailingGroup {
	const name = detailingName(check);
	if (/splice|\blap/i.test(name)) {
		return 'splices';
	}
	if (/hoop|\bties?\b|stirrup|confine|\bAsh\b|\blo\b|\bso\b|cross[- ]?tie|transverse|spiral|lateral support/i.test(name)) {
		return 'transverse';
	}
	if (/joint|strong[- ]column|scwb|ΣMn/i.test(name)) {
		return 'joints';
	}
	if (/shear|\bVe\b/i.test(name)) {
		return 'shear';
	}
	if (/longitudinal|\bbars?\b|ρ|reinforcement ratio|steel ratio|moment strength|M\+|M-|top|bottom/i.test(name)) {
		return 'longitudinal';
	}
	if (/width|depth|dimension|span|aspect|size|shortest|axial|eccentric|\bb\s*\/|\bln\b/i.test(name)) {
		return 'dimensions';
	}
	return 'other';
}

function groupLabel(group: FemDetailingGroup): string {
	switch (group) {
		case 'dimensions': return localize('femDetailing.dimensions', "Dimensions");
		case 'longitudinal': return localize('femDetailing.longitudinal', "Longitudinal Bars");
		case 'transverse': return localize('femDetailing.transverse', "Transverse Zones");
		case 'splices': return localize('femDetailing.splices', "Splices");
		case 'shear': return localize('femDetailing.shear', "Shear");
		case 'joints': return localize('femDetailing.joints', "Joints");
		case 'other': return localize('femDetailing.other', "Other");
	}
}

/** A value in a detailing unit: whole mm, mm², legs and bars, one decimal in other units, three digits for ratios (ρ 0.0105). */
function formatValue(value: number, unit: string): string {
	const text = /^(mm|mm²|legs|bars)$/.test(unit) ? value.toLocaleString('en-US', { maximumFractionDigits: 0 }) : unit ? value.toFixed(1) : String(Number(value.toPrecision(3)));
	return unit ? localize('femDetailing.valueUnit', "{0} {1}", text, unit) : text;
}

function formatKilonewtons(value: number): string {
	return localize('femDetailing.kN', "{0} kN", value.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
}

function formatMillimetres(value: number): string {
	return localize('femDetailing.mm', "{0} mm", value.toLocaleString('en-US', { maximumFractionDigits: 0 }));
}

function isNumber(value: unknown): value is number {
	return typeof value === 'number' && Number.isFinite(value);
}

/**
 * A detailing check's values, its demand against its limit: "150 mm against 100 mm" (the
 * spacing provided against the largest allowed), "520 mm² against 452 mm²" (Ash required against
 * provided), as the backend sets them.
 */
export function describeDetailingValues(check: IFemDesignCheck): string {
	return localize('femDetailing.against', "{0} against {1}", formatValue(check.demand, check.unit), formatValue(check.capacity, check.unit));
}

/** The clause a check applies ("BNBC 2020 Sec 8.3.5.4(b)"), when the backend names it. */
function clauseOf(check: IFemDesignCheck): string | undefined {
	const clause = (check as IFemDetailingCheck).clause;
	return typeof clause === 'string' && clause ? clause : undefined;
}

/** "Special moment frame", "Intermediate moment frame", "Ordinary moment frame", or the backend's word. */
export function frameTypeLabel(frameType: string): string {
	const key = frameType.toLowerCase();
	if (key.startsWith('special') || key.startsWith('smf') || key.startsWith('smrf')) {
		return localize('femDetailing.special', "Special moment frame");
	}
	if (key.startsWith('intermediate') || key.startsWith('imf') || key.startsWith('imrf')) {
		return localize('femDetailing.intermediate', "Intermediate moment frame");
	}
	if (key.startsWith('ordinary') || key.startsWith('omf') || key.startsWith('omrf')) {
		return localize('femDetailing.ordinary', "Ordinary moment frame");
	}
	return frameType;
}

/** "Special moment frame (SDC D)". */
export function describeFrameType(detailing: IFemMemberDetailing | null | undefined): string | undefined {
	const frame = detailing?.frameType ? frameTypeLabel(detailing.frameType) : undefined;
	const sdc = detailing?.sdc || undefined;
	if (frame && sdc) {
		return localize('femDetailing.frameSdc', "{0} (SDC {1})", frame, sdc);
	}
	return frame ?? (sdc ? localize('femDetailing.sdcOnly', "SDC {0}", sdc) : undefined);
}

/** The hoop zones as rows: "lo" 600 mm at each end, hoops at 100 mm; elsewhere at 150 mm. */
export function zoneRows(zones: IFemDetailingZones | null | undefined): { readonly name: string; readonly value: string }[] {
	if (!zones) {
		return [];
	}
	const rows: { name: string; value: string }[] = [];
	if (isNumber(zones.lo)) {
		rows.push({
			name: localize('femDetailing.lo', "Hoop zone lo"),
			value: isNumber(zones.so)
				? localize('femDetailing.loSo', "{0} from each joint face, hoops at {1} (so)", formatMillimetres(zones.lo), formatMillimetres(zones.so))
				: localize('femDetailing.loOnly', "{0} from each joint face", formatMillimetres(zones.lo)),
		});
	} else if (isNumber(zones.so)) {
		rows.push({ name: localize('femDetailing.so', "Hoop spacing so"), value: formatMillimetres(zones.so) });
	}
	if (isNumber(zones.outside)) {
		rows.push({ name: localize('femDetailing.outside', "Elsewhere"), value: localize('femDetailing.outsideValue', "hoops at {0}", formatMillimetres(zones.outside)) });
	}
	return rows;
}

/** "Ve 185.0 kN against φVn 240.0 kN": a member's capacity-design shear. */
export function describeCapacityShear(detailing: IFemMemberDetailing | null | undefined): { readonly value: string; readonly ok: boolean } | undefined {
	if (!isNumber(detailing?.Ve)) {
		return undefined;
	}
	if (!isNumber(detailing.phiVn)) {
		return { value: formatKilonewtons(detailing.Ve), ok: true };
	}
	const utilisation = detailing.phiVn > 0 ? detailing.Ve / detailing.phiVn : Infinity;
	return {
		value: localize('femDetailing.veValue', "{0} against φVn {1} ({2})", formatKilonewtons(detailing.Ve), formatKilonewtons(detailing.phiVn), Number.isFinite(utilisation) ? formatUtilisation(utilisation) : '∞'),
		ok: utilisation <= 1,
	};
}

// ───────────────────────────── joints ─────────────────────────────

/** The joints of a design report (none for an older backend, or no special moment frame). */
export function jointsOf(report: IFemDesignReport | undefined): readonly IFemJoint[] {
	const joints = (report as FemDetailingReport | undefined)?.joints;
	return Array.isArray(joints) ? joints : [];
}

/** A strong-column/weak-beam check's ratio ΣMnc / ΣMnb; undefined when there is none. */
export function scwbRatio(scwb: FemScwb | undefined): number | undefined {
	if (isNumber(scwb)) {
		return scwb;
	}
	if (!scwb || typeof scwb !== 'object') {
		return undefined;
	}
	if (isNumber(scwb.ratio)) {
		return scwb.ratio;
	}
	return isNumber(scwb.sumMnc) && isNumber(scwb.sumMnb) && scwb.sumMnb > 0 ? scwb.sumMnc / scwb.sumMnb : undefined;
}

/** The ratio a strong-column/weak-beam check needs: the backend's, or 1.2. */
function scwbRequired(scwb: FemScwb | undefined): number {
	return scwb && typeof scwb === 'object' && isNumber(scwb.required) ? scwb.required : SCWB_MIN_RATIO;
}

/** A strong-column/weak-beam check's utilisation: required / provided ratio (1.2 / 1.5 = 0.80). */
export function scwbUtilisation(scwb: FemScwb | undefined): number | undefined {
	if (scwbNotRequired(scwb)) {
		return 0;
	}
	if (scwb && typeof scwb === 'object' && isNumber(scwb.utilisation)) {
		return scwb.utilisation;
	}
	const ratio = scwbRatio(scwb);
	return ratio === undefined ? undefined : ratio > 0 ? scwbRequired(scwb) / ratio : Infinity;
}

/** The joint shear's utilisation Vj / φVn. */
export function jointShearUtilisation(joint: IFemJoint): number | undefined {
	const shear = joint.shear;
	if (isNumber(shear?.utilisation)) {
		return shear.utilisation;
	}
	return isNumber(shear?.Vj) && isNumber(shear.phiVn) ? (shear.phiVn > 0 ? shear.Vj / shear.phiVn : Infinity) : undefined;
}

/** Which of a joint's checks governs. */
export type FemJointGoverning = 'shear' | 'scwbX' | 'scwbY';

/** A joint's governing utilisation and the check giving it; undefined when it has no checks. */
export function jointGoverning(joint: IFemJoint): { readonly utilisation: number; readonly check: FemJointGoverning | undefined } | undefined {
	const candidates: [FemJointGoverning, number | undefined][] = [
		['shear', jointShearUtilisation(joint)],
		['scwbX', scwbUtilisation(joint.scwb?.x)],
		['scwbY', scwbUtilisation(joint.scwb?.y)],
	];
	let best: { utilisation: number; check: FemJointGoverning | undefined } | undefined;
	for (const [check, utilisation] of candidates) {
		if (utilisation !== undefined && (!best || utilisation > best.utilisation)) {
			best = { utilisation, check };
		}
	}
	if (isNumber(joint.utilisation) && (!best || joint.utilisation > best.utilisation)) {
		best = { utilisation: joint.utilisation, check: undefined };
	}
	return best;
}

/** Whether a joint passes: the backend's verdict, else its governing utilisation within 1. */
export function jointOk(joint: IFemJoint): boolean {
	if (typeof joint.ok === 'boolean') {
		return joint.ok;
	}
	const governing = jointGoverning(joint);
	return !governing || governing.utilisation <= 1;
}

function governingLabel(check: FemJointGoverning | undefined): string {
	switch (check) {
		case 'shear': return localize('femDetailing.governShear', "joint shear");
		case 'scwbX': return localize('femDetailing.governScwbX', "strong column / weak beam along X");
		case 'scwbY': return localize('femDetailing.governScwbY', "strong column / weak beam along Y");
		default: return localize('femDetailing.governOther', "joint checks");
	}
}

function jointTypeLabel(type: string | undefined): string | undefined {
	switch (type) {
		case 'interior': return localize('femDetailing.interior', "interior");
		case 'exterior': return localize('femDetailing.exterior', "exterior");
		case 'corner': return localize('femDetailing.corner', "corner");
		default: return type || undefined;
	}
}

/** "12 joints: 10 pass, 2 fail; largest utilisation 1.18 at J4 (joint shear)". */
export function describeJointsSummary(report: IFemDesignReport | undefined): string {
	const joints = jointsOf(report);
	if (!joints.length) {
		return localize('femDetailing.noJoints', "No beam-column joints are checked: the joint shear and strong-column/weak-beam checks apply to special moment frames (BNBC 2020 Part 6 Sec 8.3.5.2, 8.3.7).");
	}
	const failed = joints.filter(j => !jointOk(j)).length;
	let largest: { joint: IFemJoint; utilisation: number; check: FemJointGoverning | undefined } | undefined;
	for (const joint of joints) {
		const governing = jointGoverning(joint);
		if (governing && (!largest || governing.utilisation > largest.utilisation)) {
			largest = { joint, ...governing };
		}
	}
	const counts = localize('femDetailing.jointCounts', "{0} joints: {1} pass, {2} fail", joints.length, joints.length - failed, failed);
	return largest
		? localize('femDetailing.jointLargest', "{0} · largest utilisation {1} at {2} ({3})", counts, formatUtilisation(largest.utilisation), largest.joint.id, governingLabel(largest.check))
		: counts;
}

/** The analysis model the joints view needs: node coordinates and the elements' end nodes. */
export interface IFemDetailingModel {
	readonly nodes: readonly { readonly id: number; readonly name?: string; readonly coords: readonly number[] }[];
	readonly elements: readonly { readonly id: number; readonly nodes: readonly number[] }[];
}

/** The analysis node id of a joint, matched against the model's nodes by id or name. */
export function jointNodeId(joint: IFemJoint, model: IFemDetailingModel | undefined): number | undefined {
	const node = joint.node;
	if (isNumber(node)) {
		return node;
	}
	if (typeof node !== 'string' || !node) {
		return undefined;
	}
	const named = model?.nodes.find(n => n.name === node || String(n.id) === node);
	return named?.id ?? (Number.isFinite(Number(node)) ? Number(node) : undefined);
}

/** The building model members of a joint: its column, then its beams. */
function jointMembers(joint: IFemJoint): string[] {
	return [...(joint.column ? [joint.column] : []), ...(joint.beams ?? [])];
}

/**
 * The colours of the joints view, as utilisation by analysis element: the segments of each
 * joint's column and beams that frame into its node take the joint's governing utilisation (the
 * largest of the joints at their ends). Without the model (or the joint's node), the whole
 * members are coloured.
 */
export function jointColouring(report: IFemDesignReport | undefined, model: IFemDetailingModel | undefined): { [elementId: number]: number } {
	const result: { [elementId: number]: number } = {};
	const analysisIds = new Map<string, readonly number[]>((report?.elements ?? []).map(e => [e.id, e.members]));
	const nodesOf = new Map<number, readonly number[]>((model?.elements ?? []).map(e => [e.id, e.nodes]));
	for (const joint of jointsOf(report)) {
		const governing = jointGoverning(joint);
		if (!governing) {
			continue;
		}
		const node = jointNodeId(joint, model);
		for (const member of jointMembers(joint)) {
			for (const id of analysisIds.get(member) ?? []) {
				const ends = nodesOf.get(id);
				const framesIn = node === undefined || !ends || ends.includes(node);
				if (framesIn) {
					result[id] = Math.max(result[id] ?? 0, governing.utilisation);
				}
			}
		}
	}
	return result;
}

/** The joint at an analysis node, if one is checked there. */
export function jointAtNode(report: IFemDesignReport | undefined, nodeId: number, model: IFemDetailingModel | undefined): IFemJoint | undefined {
	return jointsOf(report).find(j => jointNodeId(j, model) === nodeId);
}

/** The joints a member frames into (as their column or one of their beams), in the report's order. */
export function jointsOfMember(report: IFemDesignReport | undefined, memberId: string): IFemJoint[] {
	return jointsOf(report).filter(j => jointMembers(j).includes(memberId));
}

/**
 * A column's joints at its top and bottom: the joints at the end nodes of its analysis elements,
 * the highest the top (z up in 3D). Without the model, the joints naming it as their column, in
 * the report's order (the first taken as the bottom).
 */
export function columnEndJoints(report: IFemDesignReport | undefined, element: IFemDesignElement, model: IFemDetailingModel | undefined): { readonly top?: IFemJoint; readonly bottom?: IFemJoint } {
	const joints = jointsOf(report);
	if (model) {
		const members = new Set(element.members);
		const nodes = new Set(model.elements.filter(e => members.has(e.id)).flatMap(e => e.nodes));
		const height = (id: number | undefined) => {
			const coords = model.nodes.find(n => n.id === id)?.coords ?? [];
			return coords[coords.length >= 3 ? 2 : 1] ?? 0;
		};
		const at = joints.filter(j => {
			const node = jointNodeId(j, model);
			return node !== undefined && nodes.has(node);
		}).sort((a, b) => height(jointNodeId(a, model)) - height(jointNodeId(b, model)));
		if (at.length) {
			return at.length === 1
				? (height(jointNodeId(at[0], model)) >= Math.max(...[...nodes].map(height)) ? { top: at[0] } : { bottom: at[0] })
				: { bottom: at[0], top: at[at.length - 1] };
		}
	}
	const own = joints.filter(j => j.column === element.id);
	return own.length > 1 ? { bottom: own[0], top: own[own.length - 1] } : own.length ? { top: own[0] } : {};
}

/** The required ratio as written in the code: "1.2" (up to two decimals, no trailing zeros). */
function formatRequired(required: number): string {
	return String(Number(required.toFixed(2)));
}

/** "ΣMnc / ΣMnb = 1.45 ≥ 1.2" (or "< 1.2"), with the sums when the backend gives them. */
export function describeScwb(scwb: FemScwb | undefined): { readonly value: string; readonly ok: boolean } | undefined {
	const ratio = scwbRatio(scwb);
	if (ratio === undefined) {
		return undefined;
	}
	const required = scwbRequired(scwb);
	if (scwbNotRequired(scwb)) {
		return { value: localize('femDetailing.scwbNotRequired', "ΣMnc / ΣMnb = {0}, not required (Pu ≤ 0.1 Ag f'c, Sec 8.3.5.2(a))", ratio.toFixed(2)), ok: true };
	}
	const ok = ratio >= required;
	// A failing ratio is shown rounded down (1.196 reads 1.19 < 1.2, not 1.20 < 1.2), and a passing
	// one rounded down to no less than the limit, so the text never contradicts the verdict.
	const shown = ok ? Math.max(Math.floor(ratio * 100 + 1e-9) / 100, required) : Math.floor(ratio * 100 + 1e-9) / 100;
	const text = ok
		? localize('femDetailing.scwbOk', "ΣMnc / ΣMnb = {0} ≥ {1}", shown.toFixed(2), formatRequired(required))
		: localize('femDetailing.scwbFail', "ΣMnc / ΣMnb = {0} < {1}", Math.min(shown, required - 0.01).toFixed(2), formatRequired(required));
	const sums = scwb && typeof scwb === 'object' && isNumber(scwb.sumMnc) && isNumber(scwb.sumMnb)
		? localize('femDetailing.scwbSums', "{0} (ΣMnc {1}, ΣMnb {2} kN·m)", text, scwb.sumMnc.toFixed(0), scwb.sumMnb.toFixed(0))
		: text;
	return { value: sums, ok };
}

function notesOf(joint: IFemJoint): string[] {
	const notes = joint.notes;
	return typeof notes === 'string' ? (notes ? [notes] : []) : Array.isArray(notes) ? [...notes] : [];
}

/** The rows of one joint: its members, joint shear and strong-column/weak-beam ratios, notes. */
export function jointItems(joint: IFemJoint): FemDetailingItem[] {
	const items: FemDetailingItem[] = [];
	if (joint.column) {
		items.push({ kind: 'row', name: localize('femDetailing.column', "Column"), value: joint.column });
	}
	if (joint.beams?.length) {
		items.push({ kind: 'row', name: localize('femDetailing.beams', "Beams"), value: joint.beams.join(', ') });
	}
	const shear = joint.shear;
	const shearUtilisation = jointShearUtilisation(joint);
	if (isNumber(shear?.Vj)) {
		items.push({
			kind: 'row', name: localize('femDetailing.jointShear', "Joint shear"),
			value: isNumber(shear.phiVn)
				? localize('femDetailing.jointShearValue', "{0} against φVn {1} ({2})", formatKilonewtons(shear.Vj), formatKilonewtons(shear.phiVn), shearUtilisation !== undefined && Number.isFinite(shearUtilisation) ? formatUtilisation(shearUtilisation) : '∞')
				: formatKilonewtons(shear.Vj),
			ok: shearUtilisation === undefined || shearUtilisation <= 1,
		});
	}
	for (const [axis, scwb] of [['X', joint.scwb?.x], ['Y', joint.scwb?.y]] as const) {
		const described = describeScwb(scwb);
		if (described) {
			items.push({ kind: 'row', name: localize('femDetailing.scwbAxis', "SCWB along {0}", axis), value: described.value, ok: described.ok });
		}
	}
	for (const note of notesOf(joint)) {
		items.push({ kind: 'note', text: note });
	}
	return items;
}

/** "Joint J3 (interior)". */
export function jointHeading(joint: IFemJoint): string {
	const type = jointTypeLabel(joint.type);
	return type ? localize('femDetailing.jointHeadingType', "Joint {0} ({1})", joint.id, type) : localize('femDetailing.jointHeading', "Joint {0}", joint.id);
}

/** A joint's verdict line: "Passes 0.80 (strong column / weak beam along X)". */
export function describeJointVerdict(joint: IFemJoint): { readonly ok: boolean; readonly utilisation: string | undefined; readonly governing: string | undefined } {
	const governing = jointGoverning(joint);
	return {
		ok: jointOk(joint),
		utilisation: governing ? (Number.isFinite(governing.utilisation) ? formatUtilisation(governing.utilisation) : '∞') : undefined,
		governing: governing?.check ? governingLabel(governing.check) : undefined,
	};
}

// ───────────────────────────── a member's section ─────────────────────────────

/**
 * The Properties panel's "Seismic Detailing" section of a beam or column: its frame type (with
 * the SDC), its detailing checks grouped (dimensions, longitudinal bars, transverse zones with lo,
 * so and Ash, splices), its capacity shear Ve against φVn and, for a column, the strong-column /
 * weak-beam ratio at its top and bottom joints. Empty when the report has nothing of it.
 */
export function detailingSection(report: IFemDesignReport | undefined, element: IFemDesignElement, model: IFemDetailingModel | undefined): FemDetailingItem[] {
	const detailing = (element as FemDetailingElement).detailing ?? undefined;
	const checks = element.checks.filter(isDetailingCheck);
	const ends = element.kind === 'column' ? columnEndJoints(report, element, model) : {};
	if (!detailing && !checks.length && !ends.top && !ends.bottom) {
		return [];
	}
	const items: FemDetailingItem[] = [{ kind: 'heading', text: localize('femDetailing.heading', "Seismic Detailing") }];
	const frame = describeFrameType(detailing);
	if (frame) {
		items.push({ kind: 'row', name: localize('femDetailing.frame', "Frame"), value: frame });
	}
	const groups = new Map<FemDetailingGroup, IFemDesignCheck[]>();
	for (const check of checks) {
		const group = detailingGroup(check);
		groups.set(group, [...(groups.get(group) ?? []), check]);
	}
	const zones = zoneRows(detailing?.zones);
	for (const group of GROUP_ORDER) {
		const inGroup = groups.get(group) ?? [];
		const zonesHere = group === 'transverse' ? zones : [];
		if (!inGroup.length && !zonesHere.length) {
			continue;
		}
		items.push({ kind: 'subheading', text: groupLabel(group) });
		items.push(...zonesHere.map(row => ({ kind: 'row' as const, ...row })));
		for (const check of [...inGroup].sort((a, b) => Number(a.ok) - Number(b.ok) || b.utilisation - a.utilisation)) {
			const clause = clauseOf(check);
			const values = describeDetailingValues(check);
			items.push({
				kind: 'check',
				name: detailingName(check),
				value: check.flag ? localize('femDetailing.reported', "reported") : formatUtilisation(check.utilisation),
				detail: clause ? localize('femDetailing.detailClause', "{0} · {1}", values, clause) : values,
				ok: check.ok,
				...(check.note ? { note: check.note } : {}),
			});
		}
	}
	const shear = describeCapacityShear(detailing);
	if (shear) {
		if (!groups.has('shear')) {
			items.push({ kind: 'subheading', text: groupLabel('shear') });
		}
		items.push({ kind: 'row', name: localize('femDetailing.ve', "Capacity shear Ve"), value: shear.value, ok: shear.ok });
	}
	if (element.kind === 'column' && (ends.top || ends.bottom)) {
		items.push({ kind: 'subheading', text: localize('femDetailing.scwbHeading', "Strong Column / Weak Beam") });
		for (const [label, joint] of [[localize('femDetailing.top', "Top"), ends.top], [localize('femDetailing.bottom', "Bottom"), ends.bottom]] as const) {
			if (!joint) {
				continue;
			}
			const ratios = (['x', 'y'] as const).flatMap(axis => {
				const described = describeScwb(joint.scwb?.[axis]);
				return described ? [{ axis: axis.toUpperCase(), ...described }] : [];
			});
			items.push({
				kind: 'row',
				name: localize('femDetailing.endJoint', "{0} ({1})", label, joint.id),
				value: ratios.length
					? ratios.map(r => localize('femDetailing.scwbAlong', "{0}: {1}", r.axis, r.value)).join('; ')
					: localize('femDetailing.noScwb', "no beams framing in to check"),
				ok: ratios.every(r => r.ok),
			});
		}
	}
	for (const note of detailing?.notes ?? []) {
		items.push({ kind: 'note', text: note });
	}
	if (detailing?.clause) {
		items.push({ kind: 'note', text: localize('femDetailing.clause', "Per {0}.", detailing.clause) });
	}
	return items;
}

/** The checks shown in a member's general list: all but the detailing checks, shown in their own section. */
export function generalChecks(checks: readonly IFemDesignCheck[]): IFemDesignCheck[] {
	return checks.filter(c => !isDetailingCheck(c));
}
