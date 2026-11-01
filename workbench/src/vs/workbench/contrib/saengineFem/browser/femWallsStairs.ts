/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { formatUtilisation, IFemDesignCheck, IFemDesignElement, IFemDesignReport } from './femDesign.js';
import { FemDetailingItem } from './femSeismicDetailing.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';

/*
 * Structural walls and stairs in the design checks (`saengine.design.design_report`): a wall is
 * an element of kind "wall" whose piers (one per storey, or more where openings cut it) are each
 * designed for P, V2 and M3; a staircase one of kind "staircase" whose flights are designed as
 * one-way slabs, with its geometry checked. Pure view models for the FEM editor's Properties
 * panel. Every field is optional: a report without them (an older backend) shows nothing of it,
 * and a wall without piers is shown as an ordinary element.
 */

/** A check as the backend may give it for walls and stairs: an ordinary check with its clause. */
export interface IFemClauseCheck extends IFemDesignCheck {
	/** "Sec 8.3.6.4". */
	readonly clause?: string | null;
}

/** A pier's design forces under its governing combination: P [kN], V2 [kN], M3 [kN·m]. */
export interface IFemPierForces {
	readonly combination?: string | null;
	readonly P?: number | null;
	readonly V2?: number | null;
	readonly M3?: number | null;
}

/** Whether a wall needs special boundary elements (BNBC 2020 Part 6 Sec 8.3.6.6), and how long. */
export interface IFemWallBoundary {
	readonly required?: boolean | null;
	/** Horizontal length of each boundary element from the wall's end [mm]. */
	readonly length?: number | null;
	/** Why: "c = 820 mm ≥ lw / (600 δu/hw) = 610 mm" or "σ = 6.1 MPa > 0.2 f'c = 5.6 MPa". */
	readonly reason?: string | null;
	/** "displacement" (Sec 8.3.6.6(b)) or "stress" (Sec 8.3.6.6(c)). */
	readonly method?: string | null;
	readonly clause?: string | null;
}

/** One pier of a wall: its part within a storey, between openings or the wall's ends. */
export interface IFemWallPier {
	readonly id: string;
	readonly storey?: string | null;
	/** Length lw and thickness tw [mm]. */
	readonly lw?: number | null;
	readonly tw?: number | null;
	/** The analysis shells it is made of (to find the pier of a selected shell). */
	readonly members?: readonly number[] | null;
	readonly forces?: IFemPierForces | null;
	readonly checks?: readonly IFemClauseCheck[] | null;
	readonly utilisation?: number | null;
	readonly ok?: boolean | null;
	/** The pier's own boundary elements, when the backend works them out per pier. */
	readonly boundary?: IFemWallBoundary | null;
}

/** A coupling beam between two wall piers (Sec 8.3.6.7). */
export interface IFemCouplingBeam {
	readonly id: string;
	readonly storey?: string | null;
	/** Clear span ln and depth h [mm]. */
	readonly ln?: number | null;
	readonly h?: number | null;
	/** Diagonal bars are required (ln/h < 2 and a large shear) or chosen. */
	readonly diagonal?: boolean | null;
	readonly checks?: readonly IFemClauseCheck[] | null;
	readonly utilisation?: number | null;
	readonly ok?: boolean | null;
	readonly notes?: readonly string[] | null;
}

/** A designed wall: an ordinary element with its piers, boundary elements and coupling beams. */
export type FemWallElement = IFemDesignElement & {
	readonly piers?: readonly IFemWallPier[] | null;
	readonly boundary?: IFemWallBoundary | null;
	readonly couplingBeams?: readonly IFemCouplingBeam[] | null;
	/** Curtains (layers) of reinforcement provided and required (two when Vu is large, Sec 8.3.6.2). */
	readonly curtains?: number | null;
	readonly curtainsRequired?: number | null;
	/** "special" (Sec 8.3.6), "ordinary", "masonryPlain" or "masonryReinforced" (Part 6 Chapter 7). */
	readonly wallType?: string | null;
	/** A masonry wall's masonry: "Plain clay masonry, f'm 9.9 MPa, Em 6941 MPa, type S mortar". */
	readonly masonry?: string | null;
	readonly notes?: readonly string[] | null;
};

/** One flight of a staircase as `saengine.design.stairs.design_stair` gives it. */
export interface IFemStairFlight {
	/** "F1". */
	readonly name: string;
	/** Its risers, as built (rise / risers) [mm], and its going [mm]. */
	readonly risers?: number | null;
	readonly riser?: number | null;
	readonly going?: number | null;
	/** Effective span [mm] and how it was taken ("Sec 6.7.1.1(a): centre to centre of beams"). */
	readonly span?: number | null;
	readonly rule?: string | null;
	/** Concrete per plan area of waist and steps [mm]. */
	readonly meanThickness?: number | null;
}

/** A designed part of a staircase (a flight or a landing spanning across), per metre width. */
export interface IFemStairPart {
	/** "F1", "L1": the prefix of its checks' names ("F1: flexure (bottom)"). */
	readonly name: string;
	/** "flight" | "landing". */
	readonly kind?: string | null;
	/** Span and thickness [mm]. */
	readonly span?: number | null;
	readonly h?: number | null;
	/** Factored load [kN/m²], moments [kN·m/m] (sagging, hogging at supports), shear [kN/m]. */
	readonly wu?: number | null;
	readonly mu?: number | null;
	readonly muTop?: number | null;
	readonly vu?: number | null;
	readonly combination?: string | null;
}

/** The loads a staircase was designed for. */
export interface IFemStairLoads {
	/** Finish and live loads [kN/m²], concrete unit weight [kN/m³], where they came from. */
	readonly finish?: number | null;
	readonly live?: number | null;
	readonly unitWeight?: number | null;
	readonly source?: string | null;
}

/**
 * A designed staircase (`design_stair`'s entry): its checks are the geometry checks (the clause
 * in the name, the working in the note) and each part's checks, named "F1: flexure (bottom)".
 */
export type FemStaircaseElement = IFemDesignElement & {
	readonly flights?: readonly IFemStairFlight[] | null;
	readonly parts?: readonly IFemStairPart[] | null;
	readonly loads?: IFemStairLoads | null;
	readonly notes?: readonly string[] | null;
};

function isNumber(value: unknown): value is number {
	return typeof value === 'number' && Number.isFinite(value);
}

function arrayOf<T>(value: readonly T[] | null | undefined): readonly T[] {
	return Array.isArray(value) ? value : [];
}

function formatMillimetres(value: number): string {
	return localize('femWalls.mm', "{0} mm", formatNumber(value));
}

function formatTenths(value: number): string {
	return formatNumber(value, { decimals: 1 });
}

/** Whether a design element is a structural wall. */
export function isWall(element: IFemDesignElement): element is FemWallElement {
	return (element.kind as string) === 'wall';
}

/** Whether a design element is a staircase. */
export function isStaircase(element: IFemDesignElement): element is FemStaircaseElement {
	return (element.kind as string) === 'staircase';
}

/** The staircases of a design report, in its order (they are not in the analysis model, so cannot be picked in 3D). */
export function staircasesOf(report: IFemDesignReport | undefined): FemStaircaseElement[] {
	return (report?.elements ?? []).filter(isStaircase);
}

/** A list of checks' utilisation: the largest of its strength checks (reported-only ones left out). */
function checksUtilisation(checks: readonly IFemDesignCheck[]): number | undefined {
	const strength = checks.filter(c => !c.flag);
	return strength.length ? Math.max(...strength.map(c => c.utilisation)) : undefined;
}

/** A part's utilisation: the backend's, else the largest of its checks. */
function partUtilisation(part: { readonly utilisation?: number | null; readonly checks?: readonly IFemDesignCheck[] | null }): number | undefined {
	return isNumber(part.utilisation) ? part.utilisation : checksUtilisation(arrayOf(part.checks));
}

/** A part's verdict: the backend's, else every strength check passing. */
function partOk(part: { readonly ok?: boolean | null; readonly checks?: readonly IFemDesignCheck[] | null }): boolean {
	return typeof part.ok === 'boolean' ? part.ok : arrayOf(part.checks).every(c => c.ok || c.flag);
}

/** The pier a selected analysis shell belongs to, if the backend names the piers' shells. */
export function pierOfShell(element: FemWallElement, shellId: number | undefined): IFemWallPier | undefined {
	return shellId === undefined ? undefined : arrayOf(element.piers).find(p => arrayOf(p.members).includes(shellId));
}

/** The pier with the largest utilisation (the first such). */
export function governingPier(element: FemWallElement): IFemWallPier | undefined {
	let best: { pier: IFemWallPier; utilisation: number } | undefined;
	for (const pier of arrayOf(element.piers)) {
		const utilisation = partUtilisation(pier);
		if (utilisation !== undefined && (!best || utilisation > best.utilisation)) {
			best = { pier, utilisation };
		}
	}
	return best?.pier;
}

/** One pier force in its unit, as the design report gives it: "1,250.0 kN", "2,400.0 kN·m". */
export function formatPierForce(key: 'P' | 'V2' | 'M3', value: number): string {
	return key === 'M3' ? localize('femWalls.kNm', "{0} kN·m", formatTenths(value)) : localize('femWalls.kN', "{0} kN", formatTenths(value));
}

/** "P 1,250.0 kN · V2 310.0 kN · M3 2,400.0 kN·m" (the forces the backend gives). */
export function describePierForces(forces: IFemPierForces | null | undefined): string | undefined {
	if (!forces) {
		return undefined;
	}
	const parts = [
		...(isNumber(forces.P) ? [localize('femWalls.P', "P {0} kN", formatTenths(forces.P))] : []),
		...(isNumber(forces.V2) ? [localize('femWalls.V2', "V2 {0} kN", formatTenths(forces.V2))] : []),
		...(isNumber(forces.M3) ? [localize('femWalls.M3', "M3 {0} kN·m", formatTenths(forces.M3))] : []),
	];
	return parts.length ? parts.join(' · ') : undefined;
}

/** "Storey 2 · P1 (lw 3,000 mm, tw 200 mm)". */
export function pierHeading(pier: IFemWallPier, showId: boolean): string {
	const name = pier.storey
		? (showId ? localize('femWalls.pierStoreyId', "{0} · {1}", pier.storey, pier.id) : pier.storey)
		: localize('femWalls.pierId', "Pier {0}", pier.id);
	if (isNumber(pier.lw) && isNumber(pier.tw)) {
		return localize('femWalls.pierSize', "{0} (lw {1}, tw {2})", name, formatMillimetres(pier.lw), formatMillimetres(pier.tw));
	}
	return name;
}

function checkValues(check: IFemDesignCheck): string {
	// Lengths and areas to the millimetre; forces to one decimal; ratios below 1 (c/d 0.08) to two.
	const value = (v: number) => check.unit
		? localize('femWalls.valueUnit', "{0} {1}", /^(mm|mm²|mm²\/m)$/.test(check.unit) ? formatNumber(v) : v.toFixed(Math.abs(v) < 1 ? 2 : 1), check.unit)
		: String(Number(v.toPrecision(3)));
	return localize('femWalls.against', "{0} against {1}", value(check.demand), value(check.capacity));
}

/** A check as a line of the panel: utilisation, demand against capacity, the clause and combination. */
function checkItem(check: IFemClauseCheck, name = check.name): FemDetailingItem {
	const extras = [
		...(typeof check.clause === 'string' && check.clause ? [check.clause] : []),
		...(check.combination ? [check.combination] : []),
	];
	return {
		kind: 'check',
		name,
		value: check.flag ? localize('femWalls.reported', "reported") : formatUtilisation(check.utilisation),
		detail: [checkValues(check), ...extras].join(' · '),
		ok: check.ok || check.flag,
		...(check.note ? { note: check.note } : {}),
	};
}

function sortChecks<T extends IFemDesignCheck>(checks: readonly T[] | null | undefined): T[] {
	return [...arrayOf(checks)].sort((a, b) => Number(a.flag) - Number(b.flag) || Number(a.ok) - Number(b.ok) || b.utilisation - a.utilisation);
}

/** Checks as lines of the panel, failing and governing first, reported-only ones ("reported") last. */
export function checkItems(checks: readonly IFemClauseCheck[] | null | undefined): FemDetailingItem[] {
	return sortChecks(checks).map(c => checkItem(c));
}

/** "Required: 450 mm from each end" / "Not required", with why. */
export function boundaryItems(boundary: IFemWallBoundary | null | undefined): FemDetailingItem[] {
	if (!boundary || typeof boundary.required !== 'boolean') {
		return [];
	}
	const value = boundary.required
		? (isNumber(boundary.length)
			? localize('femWalls.boundaryLength', "required, {0} from each end", formatMillimetres(boundary.length))
			: localize('femWalls.boundaryRequired', "required"))
		: localize('femWalls.boundaryNot', "not required");
	const items: FemDetailingItem[] = [{ kind: 'row', name: localize('femWalls.boundary', "Boundary elements"), value }];
	const method = boundary.method === 'displacement'
		? localize('femWalls.displacement', "displacement-based")
		: boundary.method === 'stress' ? localize('femWalls.stress', "stress-based") : undefined;
	const why = [...(method ? [method] : []), ...(boundary.reason ? [boundary.reason] : []), ...(boundary.clause ? [boundary.clause] : [])];
	if (why.length) {
		items.push({ kind: 'note', text: why.join(' · ') });
	}
	return items;
}

/** "2 provided, 2 required" for the wall's curtains of reinforcement. */
function curtainItems(element: FemWallElement): FemDetailingItem[] {
	const provided = element.curtains;
	const required = element.curtainsRequired;
	if (!isNumber(provided) && !isNumber(required)) {
		return [];
	}
	const value = isNumber(provided) && isNumber(required)
		? localize('femWalls.curtainsBoth', "{0} provided, {1} required", provided, required)
		: isNumber(provided) ? localize('femWalls.curtainsProvided', "{0} provided", provided) : localize('femWalls.curtainsRequired', "{0} required", required);
	return [{ kind: 'row', name: localize('femWalls.curtains', "Curtains"), value, ok: !(isNumber(provided) && isNumber(required)) || provided >= required }];
}

function pierItems(pier: IFemWallPier, showId: boolean): FemDetailingItem[] {
	const items: FemDetailingItem[] = [{ kind: 'subheading', text: pierHeading(pier, showId) }];
	const forces = describePierForces(pier.forces);
	if (forces) {
		items.push({ kind: 'row', name: localize('femWalls.forces', "Forces"), value: forces });
	}
	if (pier.forces?.combination) {
		items.push({ kind: 'row', name: localize('femWalls.combination', "Governing combination"), value: pier.forces.combination });
	}
	items.push(...checkItems(pier.checks), ...boundaryItems(pier.boundary));
	return items;
}

/** Whether more than one pier shares a storey (their ids then tell them apart). */
function piersShareStoreys(piers: readonly IFemWallPier[]): boolean {
	const storeys = piers.map(p => p.storey ?? '');
	return new Set(storeys).size < storeys.length;
}

/** The piers' and coupling beams' checks, by name, demand and capacity: to leave them out of the wall's own list. */
function partCheckKeys(element: FemWallElement): Set<string> {
	const parts = [...arrayOf(element.piers).map(p => arrayOf(p.checks)), ...arrayOf(element.couplingBeams).map(b => arrayOf(b.checks))];
	return new Set(parts.flat().map(checkKey));
}

function checkKey(check: IFemDesignCheck): string {
	return `${check.name}\u0000${check.demand}\u0000${check.capacity}\u0000${check.combination ?? ''}`;
}

/** Whether a wall or staircase is shown by its parts (piers, flights) rather than as a flat list of checks. */
export function hasParts(element: IFemDesignElement): boolean {
	return isWall(element) ? arrayOf(element.piers).length > 0
		: isStaircase(element) ? stairParts(element).length > 0
			: false;
}

/**
 * The element's own checks, shown in the general list above its parts: a wall's checks not
 * repeated in its piers or coupling beams (the backend lists every check on the element too, for
 * its utilisation); none of a staircase shown by its parts ({@link staircaseSection} shows them all).
 */
export function ownChecks(element: IFemDesignElement): IFemDesignCheck[] {
	if (!hasParts(element)) {
		return [...element.checks];
	}
	if (isStaircase(element)) {
		return [];
	}
	const keys = partCheckKeys(element as FemWallElement);
	return element.checks.filter(c => !keys.has(checkKey(c)));
}

/**
 * The Properties panel's sections of a wall: its curtains and boundary elements, the pier at the
 * selected shell (if the backend names the piers' shells) and the governing pier, each with its
 * forces, governing combination and checks, then its coupling beams. Every pier is in the pier
 * diagram ({@link pierDiagram}). Empty for a wall without piers.
 */
export function wallSection(element: FemWallElement, selectedShell: number | undefined): FemDetailingItem[] {
	const piers = arrayOf(element.piers);
	const beams = arrayOf(element.couplingBeams);
	const items: FemDetailingItem[] = [];
	const wallItems = [...curtainItems(element), ...boundaryItems(element.boundary)];
	if (wallItems.length || element.wallType || element.masonry) {
		items.push({ kind: 'heading', text: localize('femWalls.wallHeading', "Wall") });
		if (element.wallType) {
			items.push({ kind: 'row', name: localize('femWalls.wallType', "Type"), value: wallTypeLabel(element.wallType) });
		}
		if (element.masonry) {
			items.push({ kind: 'row', name: localize('femWalls.masonry', "Masonry"), value: element.masonry });
		}
		items.push(...wallItems);
	}
	if (piers.length) {
		const showId = piersShareStoreys(piers);
		const selected = pierOfShell(element, selectedShell);
		const governing = governingPier(element);
		if (selected) {
			items.push({ kind: 'heading', text: localize('femWalls.selectedPier', "Pier at Selection") }, ...pierItems(selected, showId));
		}
		if (governing && governing !== selected) {
			items.push({ kind: 'heading', text: localize('femWalls.governingPier', "Governing Pier") }, ...pierItems(governing, showId));
		}
	}
	if (beams.length) {
		items.push({ kind: 'heading', text: localize('femWalls.couplingHeading', "Coupling Beams") });
		for (const beam of beams) {
			items.push(...couplingBeamItems(beam));
		}
	}
	for (const note of arrayOf(element.notes)) {
		items.push({ kind: 'note', text: note });
	}
	return items;
}

function wallTypeLabel(type: string): string {
	const key = type.toLowerCase();
	return key.startsWith('special') ? localize('femWalls.special', "Special structural wall")
		: key.startsWith('ordinary') ? localize('femWalls.ordinary', "Ordinary structural wall")
			: key === 'masonryplain' ? localize('femWalls.masonryPlain', "Plain masonry wall")
				: key === 'masonryreinforced' ? localize('femWalls.masonryReinforced', "Reinforced masonry wall")
					: type;
}

function couplingBeamItems(beam: IFemCouplingBeam): FemDetailingItem[] {
	const utilisation = partUtilisation(beam);
	const name = beam.storey ? localize('femWalls.beamStorey', "{0} · {1}", beam.id, beam.storey) : beam.id;
	const items: FemDetailingItem[] = [{ kind: 'subheading', text: utilisation === undefined ? name : localize('femWalls.beamUtilisation', "{0} — {1}", name, formatUtilisation(utilisation)) }];
	if (isNumber(beam.ln) && isNumber(beam.h)) {
		items.push({
			kind: 'row', name: localize('femWalls.aspect', "ln / h"),
			value: localize('femWalls.aspectValue', "{0} ({1} / {2})", (beam.h > 0 ? beam.ln / beam.h : Infinity).toFixed(2), formatMillimetres(beam.ln), formatMillimetres(beam.h)),
		});
	}
	if (typeof beam.diagonal === 'boolean') {
		items.push({
			kind: 'row', name: localize('femWalls.reinforcement', "Reinforcement"),
			value: beam.diagonal ? localize('femWalls.diagonal', "diagonal bars") : localize('femWalls.conventional', "longitudinal bars and stirrups"),
		});
	}
	items.push(...checkItems(beam.checks));
	if (!partOk(beam) && !arrayOf(beam.checks).length) {
		items.push({ kind: 'note', text: localize('femWalls.beamFails', "Fails.") });
	}
	for (const note of arrayOf(beam.notes)) {
		items.push({ kind: 'note', text: note });
	}
	return items;
}

/** One bar row of the pier diagram. */
export interface IFemPierBar {
	readonly label: string;
	readonly P: number;
	readonly V2: number;
	readonly M3: number;
	readonly utilisation: number | undefined;
	readonly ok: boolean;
	/** The pier at the selected shell. */
	readonly selected: boolean;
	readonly governing: boolean;
}

/** The wall's piers as bars per storey, top storey first, with the largest magnitude of each force. */
export interface IFemPierDiagram {
	readonly bars: readonly IFemPierBar[];
	readonly max: { readonly P: number; readonly V2: number; readonly M3: number };
}

/**
 * The pier-force diagram of a wall: P, V2 and M3 of each pier under its governing combination, as
 * bars per storey along the height. The backend lists the piers from the bottom up; the diagram
 * reads top down like the building. Undefined without piers with forces.
 */
export function pierDiagram(element: FemWallElement, selectedShell: number | undefined): IFemPierDiagram | undefined {
	const piers = arrayOf(element.piers).filter(p => p.forces && (isNumber(p.forces.P) || isNumber(p.forces.V2) || isNumber(p.forces.M3)));
	if (!piers.length) {
		return undefined;
	}
	const showId = piersShareStoreys(piers);
	const selected = pierOfShell(element, selectedShell);
	const governing = governingPier(element);
	const value = (v: number | null | undefined) => isNumber(v) ? v : 0;
	const bars = [...piers].reverse().map(pier => ({
		label: pier.storey ? (showId ? localize('femWalls.barStoreyId', "{0} {1}", pier.storey, pier.id) : pier.storey) : pier.id,
		P: value(pier.forces?.P),
		V2: value(pier.forces?.V2),
		M3: value(pier.forces?.M3),
		utilisation: partUtilisation(pier),
		ok: partOk(pier),
		selected: pier === selected,
		governing: pier === governing,
	}));
	const largest = (key: 'P' | 'V2' | 'M3') => Math.max(...bars.map(b => Math.abs(b[key])));
	return { bars, max: { P: largest('P'), V2: largest('V2'), M3: largest('M3') } };
}

/** "Walls: 3 checked, 1 fails"; undefined when the report has none. */
export function describeWallsSummary(report: IFemDesignReport | undefined): string | undefined {
	const walls = (report?.elements ?? []).filter(isWall);
	if (!walls.length) {
		return undefined;
	}
	return localize('femWalls.summary', "{0} checked, {1} fail", walls.length, walls.filter(w => !w.ok).length);
}

// ───────────────────────────── stairs ─────────────────────────────

/**
 * The designed parts of a staircase: its `parts` (flights and landings), else its `flights`
 * (a backend giving only those). Only those with a name: their checks are found by it.
 */
function stairParts(element: FemStaircaseElement): IFemStairPart[] {
	const parts = arrayOf(element.parts).filter(p => typeof p?.name === 'string' && p.name.length > 0);
	if (parts.length) {
		return parts;
	}
	return arrayOf(element.flights)
		.filter(f => typeof f?.name === 'string' && f.name.length > 0)
		.map(f => ({ name: f.name, kind: 'flight', span: f.span }));
}

/** The prefix of a part's checks: "F1: ". */
function partPrefix(part: IFemStairPart): string {
	return `${part.name}: `;
}

function formatDecimal(value: number, digits: number): string {
	return formatNumber(value, { decimals: digits });
}

/** "Flight F1 (span 3,000 mm, h 150 mm)", "Landing L1 (...)". */
export function stairPartHeading(part: IFemStairPart): string {
	const name = part.kind === 'landing'
		? localize('femStairs.landing', "Landing {0}", part.name)
		: localize('femStairs.flight', "Flight {0}", part.name);
	const sizes = [
		...(isNumber(part.span) ? [localize('femStairs.span', "span {0}", formatMillimetres(part.span))] : []),
		...(isNumber(part.h) ? [localize('femStairs.thickness', "h {0}", formatMillimetres(part.h))] : []),
	];
	return sizes.length ? localize('femStairs.partSizes', "{0} ({1})", name, sizes.join(', ')) : name;
}

/** A flight's steps, span rule and mean thickness; a part's demands per metre width. */
function stairPartRows(part: IFemStairPart, flight: IFemStairFlight | undefined): FemDetailingItem[] {
	const items: FemDetailingItem[] = [];
	if (flight && isNumber(flight.risers) && isNumber(flight.riser)) {
		items.push({
			kind: 'row', name: localize('femStairs.steps', "Steps"),
			value: isNumber(flight.going)
				? localize('femStairs.stepsGoing', "{0} risers of {1} mm, going {2}", flight.risers, formatDecimal(flight.riser, 1), formatMillimetres(flight.going))
				: localize('femStairs.stepsOnly', "{0} risers of {1} mm", flight.risers, formatDecimal(flight.riser, 1)),
		});
	}
	if (flight && isNumber(flight.meanThickness)) {
		items.push({ kind: 'row', name: localize('femStairs.meanThickness', "Mean thickness"), value: formatMillimetres(flight.meanThickness) });
	}
	const demands = [
		...(isNumber(part.wu) ? [localize('femStairs.wu', "wu {0} kN/m²", formatDecimal(part.wu, 2))] : []),
		...(isNumber(part.mu) ? [localize('femStairs.mu', "Mu {0} kN·m/m", formatDecimal(part.mu, 2))] : []),
		...(isNumber(part.muTop) && part.muTop > 0 ? [localize('femStairs.muTop', "Mu,top {0} kN·m/m", formatDecimal(part.muTop, 2))] : []),
		...(isNumber(part.vu) ? [localize('femStairs.vu', "Vu {0} kN/m", formatDecimal(part.vu, 2))] : []),
	];
	if (demands.length) {
		items.push({ kind: 'row', name: localize('femStairs.demands', "Demands"), value: demands.join(' · ') });
	}
	if (part.combination) {
		items.push({ kind: 'row', name: localize('femStairs.combination', "Governing combination"), value: part.combination });
	}
	if (flight?.rule) {
		items.push({ kind: 'note', text: localize('femStairs.spanRule', "Span: {0}", flight.rule) });
	}
	return items;
}

/** "finish 1.2 kN/m², live 4.8 kN/m², concrete 23.5 kN/m³". */
function stairLoadItems(loads: IFemStairLoads | null | undefined): FemDetailingItem[] {
	if (!loads) {
		return [];
	}
	const items: FemDetailingItem[] = [
		...(isNumber(loads.finish) ? [{ kind: 'row' as const, name: localize('femStairs.finish', "Finish"), value: localize('femStairs.area', "{0} kN/m²", formatTenths(loads.finish)) }] : []),
		...(isNumber(loads.live) ? [{ kind: 'row' as const, name: localize('femStairs.live', "Live"), value: localize('femStairs.area', "{0} kN/m²", formatTenths(loads.live)) }] : []),
		...(isNumber(loads.unitWeight) ? [{ kind: 'row' as const, name: localize('femStairs.unitWeight', "Concrete"), value: localize('femStairs.unitWeightValue', "{0} kN/m³", formatTenths(loads.unitWeight)) }] : []),
	];
	if (items.length && loads.source) {
		items.push({ kind: 'note', text: loads.source });
	}
	return items;
}

/**
 * The Properties panel's sections of a staircase (`design_stair`'s entry): the geometry checks
 * (every check not named after a part; the clause is in the name, the working in the note), the
 * loads, then each flight and landing with its steps, demands and checks (named without the part's
 * prefix: "flexure (bottom)"). The bars entered show in the checks' notes; those proposed in the
 * Required Steel rows. Empty for a staircase without named parts (shown as a flat list instead).
 */
export function staircaseSection(element: FemStaircaseElement): FemDetailingItem[] {
	const parts = stairParts(element);
	if (!parts.length) {
		return [];
	}
	const partOf = (check: IFemDesignCheck) => parts.find(p => check.name.startsWith(partPrefix(p)));
	const items: FemDetailingItem[] = [];
	const geometry = element.checks.filter(c => !partOf(c));
	if (geometry.length) {
		items.push({ kind: 'heading', text: localize('femStairs.geometry', "Geometry") }, ...checkItems(geometry));
	}
	const loads = stairLoadItems(element.loads);
	if (loads.length) {
		items.push({ kind: 'heading', text: localize('femStairs.loadsHeading', "Loads") }, ...loads);
	}
	items.push({ kind: 'heading', text: localize('femStairs.parts', "Flights and Landings") });
	const flights = arrayOf(element.flights);
	for (const part of parts) {
		const prefix = partPrefix(part);
		const checks = sortChecks(element.checks.filter(c => partOf(c) === part));
		items.push(
			{ kind: 'subheading', text: stairPartHeading(part) },
			...stairPartRows(part, part.kind === 'landing' ? undefined : flights.find(f => f?.name === part.name)),
			...checks.map(c => checkItem(c, c.name.slice(prefix.length))),
		);
		if (!checks.length) {
			items.push({ kind: 'note', text: localize('femStairs.noChecks', "No checks reported for this part.") });
		}
	}
	for (const note of arrayOf(element.notes)) {
		items.push({ kind: 'note', text: note });
	}
	return items;
}

/** A staircase's one-line verdict for the summary list: "ST1 passes 0.72" / "ST1 fails 1.12". */
export function describeStaircaseVerdict(element: IFemDesignElement): string {
	return element.ok
		? localize('femStairs.passes', "{0} ({1}) passes, {2}", element.id, element.type, formatUtilisation(element.utilisation))
		: localize('femStairs.fails', "{0} ({1}) fails, {2}", element.id, element.type, formatUtilisation(element.utilisation));
}
