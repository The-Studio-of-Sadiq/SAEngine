/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { MemberGroup } from '../../../services/saengineProject/common/modelSelection.js';

/*
 * Stiffness modifiers and design overwrites of object types (`04 Objects/objects.json`) and of
 * placed members (`05 Floor Plan/floor-plan.json`), as the object type editor and the floor plan's
 * Properties panel show and change them. This module is the view model: which fields a kind of
 * member has, what each field is when left empty (the member's object type, else the code pack's
 * cracked factors or "auto"), how a typed value is checked, and the edits that write a value to
 * one object type or to many members at once (each one undoable edit of the whole document).
 *
 * The stored shapes (proposed for objects.py and floorplan.py, all optional so older files stay
 * valid):
 *
 *   "modifiers":        { "I33": 0.35, "I22": 0.35, "J": 0.1, "mass": 1, ... }
 *   "designOverwrites": { "k3": 1.2, "k2": 1, "Lu3": 2800, "Lu2": 2800,
 *                         "Lb": 3000, "framing": "sway" }
 *
 * A member's own value wins over its object type's, which wins over the code value. A key that is
 * absent means "inherit"; an empty object is removed.
 */

type Json = { [key: string]: unknown };

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// ───────────────────────────── fields ─────────────────────────────

/** Frame (beam, column, brace) modifiers, as a commercial analysis program's frame property modifiers. */
export const FRAME_MODIFIER_KEYS = ['A', 'As2', 'As3', 'J', 'I22', 'I33', 'mass', 'weight'] as const;
/**
 * Shell (slab, wall) modifiers. The analysis model's shells have one membrane and one plate
 * stiffness (OpenSees Studio's ElasticMembranePlateSection: E and Ep_mod), so the modifiers are
 * one factor for the membrane (f11, f22, f12) and one for bending (m11, m22, m12).
 */
export const SHELL_MODIFIER_KEYS = ['membrane', 'bending', 'mass', 'weight'] as const;

export type ModifierKey = typeof FRAME_MODIFIER_KEYS[number] | typeof SHELL_MODIFIER_KEYS[number];

export const DESIGN_OVERWRITE_KEYS = ['k3', 'k2', 'Lu3', 'Lu2', 'Lb', 'framing'] as const;
export type OverwriteKey = typeof DESIGN_OVERWRITE_KEYS[number];

/** How a column's storey is taken for slenderness: from the stability index Q, or as given. */
export type Framing = 'auto' | 'braced' | 'sway';
export const FRAMINGS: readonly Framing[] = ['auto', 'braced', 'sway'];

/** The two groups of fields, also their keys in the stored JSON. */
export type FieldGroup = 'modifiers' | 'designOverwrites';

/** Whether an object kind is a frame (line) or a shell (area) member, or neither. */
export type MemberShape = 'frame' | 'shell' | 'none';

export function shapeOfKind(kind: string | undefined): MemberShape {
	switch (kind) {
		case 'beam': case 'column': case 'brace': return 'frame';
		case 'slab': case 'wall': return 'shell';
		default: return 'none';
	}
}

/** The modifiers an object kind has (none for footings, stairs, piles...). */
export function modifierKeysOf(kind: string | undefined): readonly ModifierKey[] {
	const shape = shapeOfKind(kind);
	return shape === 'frame' ? FRAME_MODIFIER_KEYS : shape === 'shell' ? SHELL_MODIFIER_KEYS : [];
}

/** The design overwrites an object kind has (walls keep their own braced/restrained fields). */
export function overwriteKeysOf(kind: string | undefined): readonly OverwriteKey[] {
	switch (kind) {
		case 'column': return ['k3', 'k2', 'Lu3', 'Lu2', 'framing'];
		case 'beam': return ['k3', 'k2', 'Lu3', 'Lu2', 'Lb'];
		case 'brace': return ['k3', 'k2', 'Lu3', 'Lu2'];
		default: return [];
	}
}

/** The keys of `group` an object kind has. */
export function keysOf(group: FieldGroup, kind: string | undefined): readonly string[] {
	return group === 'modifiers' ? modifierKeysOf(kind) : overwriteKeysOf(kind);
}

/** The floor plan groups whose members carry these fields (footings have none). */
export const GROUPS_WITH_FIELDS: readonly MemberGroup[] = ['columns', 'beams', 'walls', 'slabs'];

const MODIFIER_LABELS: { readonly [key in ModifierKey]: string } = {
	A: localize('modifiers.A', "Axial area (A)"),
	As2: localize('modifiers.As2', "Shear area 2 (As2)"),
	As3: localize('modifiers.As3', "Shear area 3 (As3)"),
	J: localize('modifiers.J', "Torsion (J)"),
	I22: localize('modifiers.I22', "Inertia minor (I22)"),
	I33: localize('modifiers.I33', "Inertia major (I33)"),
	membrane: localize('modifiers.membrane', "Membrane (f11, f22, f12)"),
	bending: localize('modifiers.bending', "Bending (m11, m22, m12)"),
	mass: localize('modifiers.mass', "Mass"),
	weight: localize('modifiers.weight', "Weight"),
};

const MODIFIER_HINTS: { readonly [key in ModifierKey]: string } = {
	A: localize('modifiers.AHint', "Multiplies the cross-section area: axial stiffness."),
	As2: localize('modifiers.As2Hint', "Multiplies the shear area along local axis 2."),
	As3: localize('modifiers.As3Hint', "Multiplies the shear area along local axis 3."),
	J: localize('modifiers.JHint', "Multiplies the torsion constant. Concrete beams are often given a low factor so torsion is carried by compatibility only."),
	I22: localize('modifiers.I22Hint', "Multiplies the moment of inertia about local axis 2 (minor)."),
	I33: localize('modifiers.I33Hint', "Multiplies the moment of inertia about local axis 3 (major)."),
	membrane: localize('modifiers.membraneHint', "Multiplies the in-plane (membrane) stiffness: a wall's in-plane bending, axial and shear stiffness; a slab's diaphragm stiffness."),
	bending: localize('modifiers.bendingHint', "Multiplies the out-of-plane (plate) bending stiffness."),
	mass: localize('modifiers.massHint', "Multiplies the member's own mass in the seismic weight and the modal analysis."),
	weight: localize('modifiers.weightHint', "Multiplies the member's self-weight in the dead load case."),
};

const OVERWRITE_LABELS: { readonly [key in OverwriteKey]: string } = {
	k3: localize('overwrites.k3', "k, major axis"),
	k2: localize('overwrites.k2', "k, minor axis"),
	Lu3: localize('overwrites.Lu3', "Lu, major (mm)"),
	Lu2: localize('overwrites.Lu2', "Lu, minor (mm)"),
	Lb: localize('overwrites.lb', "Lb, lateral-torsional (mm)"),
	framing: localize('overwrites.framing', "Framing"),
};

const OVERWRITE_HINTS: { readonly [key in OverwriteKey]: string } = {
	k3: localize('overwrites.kMajorHint', "Effective length factor for buckling about the major axis (local 3)."),
	k2: localize('overwrites.kMinorHint', "Effective length factor for buckling about the minor axis (local 2)."),
	Lu3: localize('overwrites.luMajorHint', "Unbraced (unsupported) length for buckling about the major axis; empty: the clear length between the members that brace it."),
	Lu2: localize('overwrites.luMinorHint', "Unbraced (unsupported) length for buckling about the minor axis; empty: the clear length between the members that brace it."),
	Lb: localize('overwrites.lbHint', "Steel beams: the length between points braced against lateral-torsional buckling; empty: the member's length."),
	framing: localize('overwrites.framingHint', "Braced (nonsway) or sway storey for the column's slenderness; Auto takes it from the storey's stability index Q."),
};

export function fieldLabel(group: FieldGroup, key: string): string {
	return group === 'modifiers' ? MODIFIER_LABELS[key as ModifierKey] ?? key : OVERWRITE_LABELS[key as OverwriteKey] ?? key;
}

export function fieldHint(group: FieldGroup, key: string): string {
	return group === 'modifiers' ? MODIFIER_HINTS[key as ModifierKey] ?? '' : OVERWRITE_HINTS[key as OverwriteKey] ?? '';
}

export function framingLabel(framing: Framing): string {
	switch (framing) {
		case 'auto': return localize('overwrites.framingAuto', "Auto");
		case 'braced': return localize('overwrites.framingBraced', "Braced (nonsway)");
		case 'sway': return localize('overwrites.framingSway', "Sway");
	}
}

// ───────────────────────────── code values ─────────────────────────────

/** Cracked-section factors of the code pack (`concrete.crackedStiffness`), share of the gross value. */
export interface ICrackedFactors {
	readonly column: number;
	readonly beam: number;
	readonly plate: number;
	readonly wall: number;
	/** Walls when the settings do not take them as cracked; the column factor when the pack has none. */
	readonly wallUncracked?: number;
}

/** What the analysis does with the sections when a modifier is left empty. */
export interface ICodeStiffness {
	/** Project Settings → Analysis → Section stiffness. */
	readonly stiffness: 'gross' | 'aci';
	/** Project Settings → Analysis → Cracked stiffness for. */
	readonly crackedFor: 'all' | 'lateral';
	/** Project Settings → Analysis → Walls cracked. */
	readonly wallsCracked: boolean;
	/** The active code pack's factors; undefined while they are not known (shown as "code pack"). */
	readonly factors: ICrackedFactors | undefined;
	/** The pack's name for the source column ("BNBC 2020"). */
	readonly packName: string | undefined;
}

function positive(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
}

/** The cracked factors of a code pack table (`concrete` or its `crackedStiffness`), read tolerantly. */
export function readCrackedFactors(table: unknown): ICrackedFactors | undefined {
	const group = isObject(table) && isObject(table.crackedStiffness) ? table.crackedStiffness : table;
	if (!isObject(group)) {
		return undefined;
	}
	const column = positive(group.column);
	const beam = positive(group.beam);
	const plate = positive(group.plate);
	const wall = positive(group.wall);
	if (column === undefined || beam === undefined || plate === undefined || wall === undefined) {
		return undefined;
	}
	const wallUncracked = positive(group.wallUncracked);
	return { column, beam, plate, wall, ...(wallUncracked !== undefined ? { wallUncracked } : {}) };
}

/** The open project's settings and code pack table, as projectCodeStiffness.ts last read them. */
export interface IProjectCode {
	readonly settings?: unknown;
	readonly crackedTable?: unknown;
	readonly packName?: string;
}

let projectCode: IProjectCode = {};

/**
 * Remembers the open project's settings and its code pack's cracked table (set by
 * projectCodeStiffness.ts as the project opens and its settings are saved), for the editors that
 * do not read them themselves; `{}` forgets them (no project).
 */
export function setProjectCode(code: IProjectCode): void {
	projectCode = code;
}

/**
 * The code stiffness from the project settings (`analysis.stiffness`, `crackedFor`,
 * `wallsCracked`, with the defaults of saengine.library.settings) and the pack's cracked table.
 * What is not given is taken from the open project (see {@link setProjectCode}).
 */
export function readCodeStiffness(settings: unknown, crackedTable: unknown, packName?: string): ICodeStiffness {
	settings ??= projectCode.settings;
	const analysis = isObject(settings) && isObject(settings.analysis) ? settings.analysis : {};
	return {
		stiffness: analysis.stiffness === 'gross' ? 'gross' : 'aci',
		crackedFor: analysis.crackedFor === 'all' ? 'all' : 'lateral',
		wallsCracked: analysis.wallsCracked === true,
		factors: readCrackedFactors(crackedTable ?? projectCode.crackedTable),
		packName: packName ?? projectCode.packName,
	};
}

/** The code's value of a modifier: a number, or 'pack' when it is the pack's factor and the pack is not read yet. */
export function codeModifier(kind: string | undefined, key: ModifierKey, concrete: boolean, code: ICodeStiffness): number | 'pack' {
	if (code.stiffness === 'gross' || !concrete) {
		return 1;
	}
	const f = code.factors;
	switch (kind) {
		case 'column':
		case 'brace':
			// A brace takes the factor of its direction in the analysis (steep ones as columns);
			// shown as a column's, the usual case for concrete braces (struts).
			return key === 'I22' || key === 'I33' ? f?.column ?? 'pack' : 1;
		case 'beam':
			return key === 'I22' || key === 'I33' ? f?.beam ?? 'pack' : 1;
		case 'slab':
			return key === 'bending' ? f?.plate ?? 'pack' : 1;
		case 'wall':
			if (key === 'membrane' || key === 'bending') {
				return f ? (code.wallsCracked ? f.wall : f.wallUncracked ?? f.column) : 'pack';
			}
			return 1;
		default:
			return 1;
	}
}

/** Where the code value comes from, for the muted column beside an empty field. */
function codeSource(key: ModifierKey, concrete: boolean, code: ICodeStiffness, value: number | 'pack'): string {
	if (key === 'mass') {
		return localize('modifiers.sourceOwn', "own mass");
	}
	if (key === 'weight') {
		return localize('modifiers.sourceOwnWeight', "own weight");
	}
	if (code.stiffness === 'gross') {
		return localize('modifiers.sourceGross', "gross (settings)");
	}
	if (!concrete) {
		return localize('modifiers.sourceNotConcrete', "gross (not concrete)");
	}
	if (value === 1) {
		return localize('modifiers.sourceGrossKey', "gross");
	}
	const pack = code.packName ?? localize('modifiers.codePack', "code pack");
	return code.crackedFor === 'lateral'
		? localize('modifiers.sourceCrackedLateral', "{0} cracked (lateral)", pack)
		: localize('modifiers.sourceCracked', "{0} cracked", pack);
}

// ───────────────────────────── values ─────────────────────────────

/** A number as a modifier or length is shown: up to three decimals, lengths in whole mm. */
export function formatFieldValue(key: string, value: number): string {
	return isLength(key) ? String(Math.round(value)) : String(Math.round(value * 1000) / 1000);
}

function isLength(key: string): boolean {
	return key === 'Lu3' || key === 'Lu2' || key === 'Lb';
}

function isStiffness(key: string): boolean {
	return (FRAME_MODIFIER_KEYS as readonly string[]).includes(key) && key !== 'mass' && key !== 'weight' || key === 'membrane' || key === 'bending';
}

/** The result of checking what was typed into a field. */
export interface IFieldCheck {
	/** The value to store; undefined clears the field (back to the inherited value). */
	readonly value?: number | Framing;
	/** Why it cannot be stored. */
	readonly error?: string;
	/** Stored, but unusual. */
	readonly warning?: string;
}

/** Parses "0.35" or "0,35" (a decimal comma, as typed on some keyboards); NaN when it is no number. */
function parseNumber(text: string): number {
	const trimmed = text.trim().replace(/^(-?\d*),(\d+)$/, '$1.$2');
	return trimmed === '' ? NaN : Number(trimmed);
}

/** Largest modifier taken: ten times the gross section is surely a typing slip. */
const MODIFIER_MAX = 10;
/** Stiffness modifiers below this leave the member almost without stiffness. */
const MODIFIER_LOW = 0.1;
/** Mass or weight modifiers above this are more often loads that belong in the load cases. */
const MASS_HIGH = 2;
/** The largest effective length factor taken. */
const K_MAX = 10;
/** Effective length factors below this (a member fixed at both ends is 0.5 in theory) are unusual. */
const K_LOW = 0.5;
/** Unbraced lengths shorter than this [mm] are unusual. */
const LENGTH_LOW = 300;
/** Unbraced lengths longer than this [mm] are unusual for a building. */
const LENGTH_HIGH = 30000;

/** A warning for a stored value, also shown while it is typed. `framing` is the member's framing for k. */
export function fieldWarning(group: FieldGroup, key: string, value: number, framing?: Framing): string | undefined {
	if (group === 'modifiers') {
		if (key === 'mass' || key === 'weight') {
			if (value === 0) {
				return key === 'mass'
					? localize('modifiers.noMass', "No mass: the member is left out of the seismic weight and the modes.")
					: localize('modifiers.noWeight', "No weight: the member's self-weight is left out of the dead load.");
			}
			return value > MASS_HIGH ? localize('modifiers.highMass', "More than twice the member's own: added mass is usually entered as a load instead.") : undefined;
		}
		if (value > 1) {
			return localize('modifiers.stiffer', "Stiffer than the gross section: unusual.");
		}
		return value < MODIFIER_LOW ? localize('modifiers.low', "Below {0}: the member hardly takes any force this way. Check that this is intended.", MODIFIER_LOW) : undefined;
	}
	if (key === 'k3' || key === 'k2') {
		if (framing === 'braced' && value > 1) {
			return localize('overwrites.bracedK', "A braced (nonsway) member normally has k of 1.0 or less.");
		}
		if (framing === 'sway' && value < 1) {
			return localize('overwrites.swayK', "A sway member normally has k of 1.0 or more.");
		}
		return value < K_LOW ? localize('overwrites.lowK', "Below {0}: less than a member fixed at both ends.", K_LOW) : undefined;
	}
	if (isLength(key)) {
		if (value < LENGTH_LOW) {
			return localize('overwrites.shortLength', "Shorter than {0} mm: check the unit (mm).", LENGTH_LOW);
		}
		return value > LENGTH_HIGH ? localize('overwrites.longLength', "Longer than {0} m: check the unit (mm).", LENGTH_HIGH / 1000) : undefined;
	}
	return undefined;
}

/** Checks what was typed into a field: empty clears it; a number in range is stored, perhaps with a warning. */
export function checkField(group: FieldGroup, key: string, text: string, framing?: Framing): IFieldCheck {
	if (key === 'framing') {
		const value = FRAMINGS.find(f => f === text.trim());
		return value === undefined || value === 'auto' ? {} : { value };
	}
	if (text.trim() === '') {
		return {};
	}
	const value = parseNumber(text);
	if (!Number.isFinite(value)) {
		return { error: localize('field.notNumber', "Type a number, or leave the field empty for the inherited value.") };
	}
	if (group === 'modifiers') {
		if (isStiffness(key) ? value <= 0 : value < 0) {
			return { error: isStiffness(key) ? localize('modifiers.notPositive', "A stiffness modifier must be more than 0.") : localize('modifiers.negative', "A mass or weight modifier cannot be negative.") };
		}
		if (value > MODIFIER_MAX) {
			return { error: localize('modifiers.tooHigh', "A modifier can be at most {0}.", MODIFIER_MAX) };
		}
	} else if (value <= 0) {
		return { error: localize('overwrites.notPositive', "Must be more than 0.") };
	} else if ((key === 'k3' || key === 'k2') && value > K_MAX) {
		return { error: localize('overwrites.kTooHigh', "An effective length factor can be at most {0}.", K_MAX) };
	}
	return { value, warning: fieldWarning(group, key, value, framing) };
}

// ───────────────────────────── view model ─────────────────────────────

/** One object type or member whose fields are shown. */
export interface IModifierTarget {
	/** Its object kind (`column`, `beam`, `slab`...): for a member, its object type's. */
	readonly kind: string | undefined;
	/** Whether its material is concrete or masonry (only those take the code's cracked factors, as in derive). */
	readonly concrete: boolean;
	/** Its own record: the object type, or the placed member. */
	readonly own: Json;
	/** For a member, its object type's record (its values are inherited); undefined for an object type. */
	readonly type?: Json;
	/** For a member, its object type's id, for the source column. */
	readonly typeId?: string;
}

/** The inherited value of a field: what applies when the field is left empty. */
interface IInherited {
	readonly text: string;
	readonly source: string;
}

/** A row of the panel. */
export interface IFieldRow {
	readonly group: FieldGroup;
	readonly key: string;
	readonly label: string;
	readonly hint: string;
	/** The own value common to all targets, as text ('' when empty or various). */
	readonly value: string;
	/** The targets have different own values. */
	readonly various: boolean;
	/** The inherited value, shown greyed in the empty field ("0.35", "auto"). */
	readonly placeholder: string;
	/** Where the shown value comes from: "BNBC 2020 cracked", "type B300x500", "member", "various". */
	readonly source: string;
	/** Whether the shown value is the target's own (not inherited). */
	readonly own: boolean;
	/** A warning for the common own value, if unusual. */
	readonly warning: string | undefined;
}

/** What Enter in a field's box does: show an error, nothing (unchanged), or store `value` (undefined clears). */
export interface IFieldCommit extends IFieldCheck {
	readonly unchanged?: boolean;
}

/**
 * Enter in the box of `row` with `text` typed. Text equal to the shown value changes nothing; in
 * particular an untouched empty "(various)" box keeps every member's own value instead of clearing it.
 */
export function commitField(row: IFieldRow, text: string): IFieldCommit {
	const check = checkField(row.group, row.key, text);
	if (check.error) {
		return check;
	}
	return text.trim() === row.value.trim() ? { unchanged: true } : check;
}

export interface IModifiersView {
	/** An object type, or placed members. */
	readonly level: 'type' | 'member';
	/** Which targets these are (their ids), so a field typed but not stored is kept only for them. */
	readonly scope: string;
	readonly modifiers: readonly IFieldRow[];
	readonly overwrites: readonly IFieldRow[];
	/** Whether any target has an own value in the group (for the "Reset" links). */
	readonly hasModifiers: boolean;
	readonly hasOverwrites: boolean;
	/** The muted note under the modifiers. */
	readonly note: string;
	readonly count: number;
}

function groupOf(record: Json | undefined, group: FieldGroup): Json | undefined {
	const value = record?.[group];
	return isObject(value) ? value : undefined;
}

function ownValue(record: Json | undefined, group: FieldGroup, key: string): number | Framing | undefined {
	const value = groupOf(record, group)?.[key];
	if (key === 'framing') {
		return value === 'braced' || value === 'sway' ? value : undefined;
	}
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** The keys every target has (a mixed selection of frames and shells keeps mass and weight). */
function commonKeys(group: FieldGroup, targets: readonly IModifierTarget[]): string[] {
	if (!targets.length) {
		return [];
	}
	const [first, ...rest] = targets.map(t => keysOf(group, t.kind));
	return first.filter(key => rest.every(keys => keys.includes(key)));
}

function valueText(key: string, value: number | Framing): string {
	return typeof value === 'number' ? formatFieldValue(key, value) : framingLabel(value);
}

function inheritedOf(group: FieldGroup, key: string, target: IModifierTarget, code: ICodeStiffness): IInherited {
	const fromType = target.type ? ownValue(target.type, group, key) : undefined;
	if (fromType !== undefined) {
		return {
			text: key === 'framing' ? framingLabel(fromType as Framing) : valueText(key, fromType),
			source: localize('field.sourceType', "type {0}", target.typeId ?? ''),
		};
	}
	if (group === 'modifiers') {
		const value = codeModifier(target.kind, key as ModifierKey, target.concrete, code);
		return {
			text: value === 'pack' ? localize('modifiers.packValue', "code") : formatFieldValue(key, value),
			source: codeSource(key as ModifierKey, target.concrete, code, value),
		};
	}
	switch (key) {
		case 'framing': return { text: framingLabel('auto'), source: localize('overwrites.sourceAuto', "from the stability index Q") };
		case 'k3': case 'k2': return { text: localize('overwrites.autoK', "auto"), source: localize('overwrites.sourceK', "1.0 braced, chart if sway") };
		case 'Lb': return { text: localize('overwrites.autoLength', "auto"), source: localize('overwrites.sourceLb', "member length") };
		default: return { text: localize('overwrites.autoLength', "auto"), source: localize('overwrites.sourceLu', "clear length") };
	}
}

function rowsOf(group: FieldGroup, targets: readonly IModifierTarget[], code: ICodeStiffness, member: boolean): IFieldRow[] {
	return commonKeys(group, targets).map(key => {
		const owns = targets.map(t => ownValue(t.own, group, key));
		const firstOwn = owns[0];
		const sameOwn = owns.every(v => v === firstOwn);
		const inherited = targets.map(t => inheritedOf(group, key, t, code));
		const sameInherited = inherited.every(i => i.text === inherited[0].text && i.source === inherited[0].source);
		const own = sameOwn && firstOwn !== undefined;
		const framings = targets.map(t => (ownValue(t.own, 'designOverwrites', 'framing') ?? ownValue(t.type, 'designOverwrites', 'framing')) as Framing | undefined);
		const framing = framings.every(f => f === framings[0]) ? framings[0] : undefined;
		return {
			group,
			key,
			label: fieldLabel(group, key),
			hint: fieldHint(group, key),
			value: own ? (key === 'framing' ? firstOwn as string : formatFieldValue(key, firstOwn as number)) : '',
			various: !sameOwn,
			placeholder: !sameOwn || !sameInherited ? localize('field.various', "(various)") : inherited[0].text,
			source: !sameOwn ? localize('field.sourceVarious', "various")
				: own ? (member ? localize('field.sourceMember', "member") : localize('field.sourceThisType', "this type"))
					: sameInherited ? inherited[0].source : localize('field.sourceVarious', "various"),
			own,
			warning: own && typeof firstOwn === 'number' ? fieldWarning(group, key, firstOwn, framing) : undefined,
		};
	});
}

/**
 * The rows for one object type (`level: 'type'`) or for the selected members (`'member'`): the
 * fields all of them have, each with the common own value (or various) and the inherited one.
 */
export function modifiersView(level: 'type' | 'member', targets: readonly IModifierTarget[], code: ICodeStiffness): IModifiersView {
	const member = level === 'member';
	const modifiers = rowsOf('modifiers', targets, code, member);
	const overwrites = rowsOf('designOverwrites', targets, code, member);
	const has = (group: FieldGroup) => targets.some(t => Object.keys(groupOf(t.own, group) ?? {}).length > 0);
	const pack = code.packName ?? localize('modifiers.codePack', "code pack");
	const note = code.stiffness === 'gross'
		? localize('modifiers.noteGross', "Empty: the gross section (Project Settings → Analysis → Section stiffness is Gross). A value applies in every case, gravity and lateral.")
		: code.crackedFor === 'lateral'
			? localize('modifiers.noteLateral2', "Empty: the {0} cracked factors for the lateral cases, the gross section for gravity. A value replaces both: it applies in every case, gravity and lateral.", pack)
			: localize('modifiers.noteAll2', "Empty: the {0} cracked factors in every case. A value replaces the factor in every case, gravity and lateral.", pack);
	return {
		level,
		scope: `${level}:${targets.map(t => String(t.own.id ?? '')).join(',')}`,
		modifiers,
		overwrites,
		hasModifiers: has('modifiers'),
		hasOverwrites: has('designOverwrites'),
		note: member ? `${note} ${localize('modifiers.noteMember', "A member's value wins over its object type's.")}` : note,
		count: targets.length,
	};
}

// ───────────────────────────── stored values ─────────────────────────────

/** A stored value that cannot be used (typed into the JSON, or from an older file). */
export interface IStoredFieldProblem {
	/** The object type's or member's id. */
	readonly id: string;
	readonly group: FieldGroup;
	readonly key: string;
	readonly message: string;
}

/** The lists of a part's document that carry fields: the object types, or the floor plan's member groups. */
export function fieldListsOf(part: 'objects' | 'floorPlan'): readonly string[] {
	return part === 'objects' ? ['objects'] : GROUPS_WITH_FIELDS;
}

/**
 * The stored modifiers and overwrites of `04 Objects/objects.json` (part 'objects') or
 * `05 Floor Plan/floor-plan.json` ('floorPlan') that the panel's checks would refuse. The panel
 * never stores such a value, so they come from a hand edit or an older file.
 */
export function storedFieldProblems(doc: unknown, part: 'objects' | 'floorPlan'): IStoredFieldProblem[] {
	const problems: IStoredFieldProblem[] = [];
	for (const record of fieldListsOf(part).flatMap(key => listOf(doc, key))) {
		for (const group of ['modifiers', 'designOverwrites'] as const) {
			for (const [key, value] of Object.entries(groupOf(record, group) ?? {})) {
				const error = key === 'framing'
					? (value === 'braced' || value === 'sway' || value === 'auto' ? undefined : localize('field.badFraming', "Framing must be Auto, Braced or Sway."))
					: typeof value === 'number' ? checkField(group, key, String(value)).error
						: localize('field.storedNotNumber', "Not a number.");
				if (error) {
					const id = String(record.id ?? '?');
					problems.push({ id, group, key, message: localize('field.storedProblem', "{0}: {1}: {2}", id, fieldLabel(group, key), error) });
				}
			}
		}
	}
	return problems;
}

// ───────────────────────────── targets from the documents ─────────────────────────────

/** The member reference of the floor plan (as floorPlanSelection's IMemberRef). */
export interface IMemberRef {
	readonly group: MemberGroup;
	readonly id: string;
}

function listOf(doc: unknown, key: string): Json[] {
	const list = isObject(doc) ? doc[key] : undefined;
	return Array.isArray(list) ? list.filter(isObject) : [];
}

/**
 * Whether material `id` of `03 Materials/materials.json` takes the code's cracked factors:
 * concrete or masonry, as fem/derive.py's concrete_sections. A material not found stays gross there.
 */
export function isConcreteMaterial(materials: unknown, id: unknown): boolean {
	const material = listOf(materials, 'materials').find(m => m.id === id);
	return material ? material.category === 'concrete' || material.category === 'masonry' : false;
}

/** The target of an object type record (`04 Objects`). */
export function objectTypeTarget(item: Json, materials: unknown): IModifierTarget {
	return { kind: typeof item.kind === 'string' ? item.kind : undefined, concrete: isConcreteMaterial(materials, item.material), own: item };
}

/** The targets of the selected members (those of groups without fields, or not found, left out). */
export function memberTargets(layout: unknown, objects: unknown, materials: unknown, refs: readonly IMemberRef[]): IModifierTarget[] {
	const types = listOf(objects, 'objects');
	const targets: IModifierTarget[] = [];
	for (const ref of refs) {
		if (!GROUPS_WITH_FIELDS.includes(ref.group)) {
			continue;
		}
		const own = listOf(layout, ref.group).find(m => m.id === ref.id);
		if (!own) {
			continue;
		}
		const type = types.find(t => t.id === own.type);
		targets.push({
			kind: typeof type?.kind === 'string' ? type.kind : GROUP_KIND[ref.group],
			concrete: isConcreteMaterial(materials, type?.material),
			own,
			type,
			typeId: typeof own.type === 'string' ? own.type : undefined,
		});
	}
	return targets;
}

/** The kind of a group's members when their object type is missing. */
const GROUP_KIND: { readonly [group in MemberGroup]: string } = {
	columns: 'column',
	beams: 'beam',
	walls: 'wall',
	slabs: 'slab',
	footings: 'footing',
};

// ───────────────────────────── edits ─────────────────────────────

/** `record` with `group.key` set to `value`, or removed when undefined; an empty group is removed. Not in place. */
export function withField(record: Json, group: FieldGroup, key: string, value: number | Framing | undefined): Json {
	const fields: Json = { ...(groupOf(record, group) ?? {}) };
	if (value === undefined || value === 'auto') {
		delete fields[key];
	} else {
		fields[key] = value;
	}
	const next: Json = { ...record };
	if (Object.keys(fields).length) {
		next[group] = fields;
	} else {
		delete next[group];
	}
	return next;
}

/**
 * Sets a field of an object type in place (the object type editor's form changes its item in
 * place and then commits the document as one undoable edit).
 */
export function setObjectTypeField(item: Json, group: FieldGroup, key: string, value: number | Framing | undefined): void {
	const next = withField(item, group, key, value);
	if (next[group] === undefined) {
		delete item[group];
	} else {
		item[group] = next[group];
	}
}

/** Clears a group of an object type in place. */
export function resetObjectTypeGroup(item: Json, group: FieldGroup): void {
	delete item[group];
}

/**
 * Keeps only the fields the object's (new) kind has, in place: after the kind of an object type
 * changes (a beam made a slab loses its I33).
 */
export function pruneForKind(item: Json): void {
	const kind = typeof item.kind === 'string' ? item.kind : undefined;
	for (const group of ['modifiers', 'designOverwrites'] as const) {
		const fields = groupOf(item, group);
		if (!fields) {
			continue;
		}
		const keys = keysOf(group, kind);
		const kept = Object.fromEntries(Object.entries(fields).filter(([key]) => keys.includes(key)));
		if (Object.keys(kept).length) {
			item[group] = kept;
		} else {
			delete item[group];
		}
	}
}

/** The result of an edit of the floor plan (shaped as floorPlanBulk's BulkResult, so the editor applies it as one edit). */
export type MemberEditResult =
	| { readonly ok: true; readonly layout: Json; readonly ids: readonly IMemberRef[]; readonly placed: number; readonly skipped: number }
	| { readonly ok: false; readonly error: string };

function editMembers(layout: unknown, refs: readonly IMemberRef[], objects: unknown, change: (member: Json, kind: string | undefined) => Json | undefined): MemberEditResult {
	if (!isObject(layout)) {
		return { ok: false, error: localize('field.noPlan', "The floor plan cannot be read.") };
	}
	const next: Json = JSON.parse(JSON.stringify(layout));
	const types = listOf(objects, 'objects');
	const changed: IMemberRef[] = [];
	for (const ref of refs) {
		if (!GROUPS_WITH_FIELDS.includes(ref.group)) {
			continue;
		}
		const list = Array.isArray(next[ref.group]) ? next[ref.group] as unknown[] : [];
		const index = list.findIndex(m => isObject(m) && m.id === ref.id);
		if (index < 0) {
			continue;
		}
		const member = list[index] as Json;
		const type = types.find(t => t.id === member.type);
		const kind = typeof type?.kind === 'string' ? type.kind : GROUP_KIND[ref.group];
		const updated = change(member, kind);
		if (updated && JSON.stringify(updated) !== JSON.stringify(member)) {
			list[index] = updated;
			changed.push(ref);
		}
	}
	if (!changed.length) {
		return { ok: false, error: localize('field.nothingChanged', "Nothing to change: the selected members already have this value.") };
	}
	return { ok: true, layout: next, ids: changed, placed: 0, skipped: 0 };
}

/**
 * Sets (or clears, `value` undefined) one field of every selected member that has it, as one edit
 * of the floor plan. `objects` gives the members' kinds (a slab has no I33).
 */
export function setMembersField(layout: unknown, refs: readonly IMemberRef[], objects: unknown, group: FieldGroup, key: string, value: number | Framing | undefined): MemberEditResult {
	return editMembers(layout, refs, objects, (member, kind) => keysOf(group, kind).includes(key) ? withField(member, group, key, value) : undefined);
}

/** Clears a group (all modifiers, or all overwrites) of every selected member, as one edit. */
export function resetMembersGroup(layout: unknown, refs: readonly IMemberRef[], objects: unknown, group: FieldGroup): MemberEditResult {
	return editMembers(layout, refs, objects, member => {
		if (member[group] === undefined) {
			return undefined;
		}
		const next = { ...member };
		delete next[group];
		return next;
	});
}

/** The notice after an edit of `count` members. */
export function editNotice(group: FieldGroup, key: string | undefined, count: number): string {
	if (key === undefined) {
		return group === 'modifiers'
			? localize('field.resetModifiers', "Stiffness modifiers of {0} member(s) back to the inherited values.", count)
			: localize('field.resetOverwrites', "Design overwrites of {0} member(s) back to the inherited values.", count);
	}
	return localize('field.changed', "{0} of {1} member(s) changed.", fieldLabel(group, key), count);
}
