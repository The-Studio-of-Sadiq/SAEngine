/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { formatNumber } from './formatting.js';

/**
 * Display units (alpha 9, C13): SI or US customary, the same table as the backend's
 * `saengine.units`. SAEngine stores and computes in SI only; a project chooses how its numbers are
 * shown (Project Settings › Units, `units`). The editors convert where a value is shown and where
 * one is typed: {@link toDisplay} / {@link formatQuantity} out, {@link parseQuantity} in. A value
 * not typed again is never rewritten, so switching the system changes no stored value.
 *
 * A quantity is known by the SI unit SAEngine writes it in ("mm", "kN/m²", the "[mm]" of a schema
 * field's description); a field whose unit is not written that way names its kind (`unitKind`).
 * Temperatures (C13b): "°C" is a temperature (°F = 1.8 °C + 32), "Δ°C" a change (a field names it
 * with `unitKind` "temperatureChange"; it shows "°C" in SI). {@link convertText} converts the
 * quantities of a text as the backend does; {@link sizeText} and {@link barName} member and bar sizes.
 */

export type UnitSystem = 'SI' | 'USCustomary';

interface IKind {
	readonly si: string;
	/** US customary units with the factor from the SI base unit (value_us = value_si × factor); the first is the default. */
	readonly us: readonly (readonly [string, number])[];
	/** Added after the factor (value_us = value_si × factor + offset): absolute temperatures (C13b). */
	readonly offsets?: { readonly [unit: string]: number };
	/** The unit text shown in SI when it is not `si` (a temperature change "Δ°C" shows "°C"). */
	readonly siLabel?: string;
}

// exact definitions (NIST SP 811)
const FOOT = 0.3048;
const INCH = 0.0254;
const POUND_FORCE = 4.4482216152605;
const KIP = 1000 * POUND_FORCE;
const POUND = 0.45359237;
const SHORT_TON = 2000 * POUND;
const MILE = 1609.344;

const KN_M2_IN_PSF = 1000 / (POUND_FORCE / FOOT ** 2);
const KN_M_IN_KIP_FT = 1000 / (KIP * FOOT);

/** The quantity kinds, by id (saengine.units.KINDS). */
export const UNIT_KINDS: { readonly [kind: string]: IKind } = {
	length: { si: 'm', us: [['ft', 1 / FOOT], ['in', 1 / INCH]] },
	dimension: { si: 'mm', us: [['in', 1e-3 / INCH], ['ft', 1e-3 / FOOT]] },
	force: { si: 'kN', us: [['kip', 1000 / KIP], ['lbf', 1000 / POUND_FORCE]] },
	stress: { si: 'MPa', us: [['ksi', 1e6 / (KIP / INCH ** 2)], ['psi', 1e6 / (POUND_FORCE / INCH ** 2)]] },
	pressure: { si: 'kN/m²', us: [['psf', KN_M2_IN_PSF], ['ksf', KN_M2_IN_PSF / 1000]] },
	moment: { si: 'kN·m', us: [['kip·ft', KN_M_IN_KIP_FT], ['kip·in', 1000 / (KIP * INCH)]] },
	lineLoad: { si: 'kN/m', us: [['kip/ft', 1000 * FOOT / KIP], ['plf', 1000 * FOOT / POUND_FORCE]] },
	momentPerLength: { si: 'kN·m/m', us: [['kip·ft/ft', KN_M_IN_KIP_FT * FOOT]] },
	unitWeight: { si: 'kN/m³', us: [['pcf', 1000 * FOOT ** 3 / POUND_FORCE], ['kcf', 1000 * FOOT ** 3 / KIP]] },
	density: { si: 'kg/m³', us: [['pcf', FOOT ** 3 / POUND]] },
	area: { si: 'mm²', us: [['in²', 1e-6 / INCH ** 2]] },
	areaPerLength: { si: 'mm²/m', us: [['in²/ft', 1e-6 / INCH ** 2 * FOOT]] },
	areaPerSpacing: { si: 'mm²/mm', us: [['in²/in', 1e-6 / INCH ** 2 * 1e3 * INCH]] },
	areaLarge: { si: 'm²', us: [['ft²', 1 / FOOT ** 2]] },
	volume: { si: 'm³', us: [['ft³', 1 / FOOT ** 3], ['yd³', 1 / (3 * FOOT) ** 3]] },
	mass: { si: 'kg', us: [['lb', 1 / POUND]] },
	massLarge: { si: 't', us: [['ton', 1000 / SHORT_TON]] },
	velocity: { si: 'm/s', us: [['mph', 3600 / MILE], ['ft/s', 1 / FOOT]] },
	stiffness: { si: 'kN/mm', us: [['kip/in', 1000 * INCH * 1000 / KIP]] },
	inertia: { si: 'mm⁴', us: [['in⁴', 1e-12 / INCH ** 4]] },
	sectionModulus: { si: 'mm³', us: [['in³', 1e-9 / INCH ** 3]] },
	// C13b: temperatures (an absolute one with the offset; a change without, named by `unitKind`)
	temperature: { si: '°C', us: [['°F', 1.8]], offsets: { '°F': 32 } },
	temperatureChange: { si: 'Δ°C', us: [['°F', 1.8]], siLabel: '°C' },
	perTemperature: { si: '1/°C', us: [['1/°F', 1 / 1.8]] },
};

/** SAEngine's SI unit texts → [kind, factor to the kind's base unit] (saengine.units.SI_UNITS). */
const SI_UNITS: { readonly [unit: string]: readonly [string, number] } = {
	'm': ['length', 1], 'mm': ['dimension', 1], 'kN': ['force', 1], 'MPa': ['stress', 1], 'N/mm²': ['stress', 1],
	'GPa': ['stress', 1000], 'kN/m²': ['pressure', 1], 'kPa': ['pressure', 1], 'kN·m': ['moment', 1], 'kNm': ['moment', 1],
	'kN/m': ['lineLoad', 1], 'kN·m/m': ['momentPerLength', 1], 'kN/m³': ['unitWeight', 1], 'kg/m³': ['density', 1],
	'mm²': ['area', 1], 'mm²/m': ['areaPerLength', 1], 'mm²/mm': ['areaPerSpacing', 1], 'm²': ['areaLarge', 1],
	'm³': ['volume', 1], 'kg': ['mass', 1], 't': ['massLarge', 1], 'm/s': ['velocity', 1], 'kN/mm': ['stiffness', 1],
	'mm⁴': ['inertia', 1], 'mm³': ['sectionModulus', 1],
	'°C': ['temperature', 1], 'Δ°C': ['temperatureChange', 1], '1/°C': ['perTemperature', 1],
};

/** The per-quantity choices of Project Settings › Units (saengine.units.OVERRIDABLE). */
export const OVERRIDABLE_KINDS = ['length', 'dimension', 'force', 'stress', 'pressure', 'moment', 'lineLoad', 'unitWeight', 'volume', 'velocity'] as const;

/** The project's display units: the `units` of its settings. */
export interface IDisplayUnits {
	readonly system: UnitSystem;
	/** Per-quantity choices, kind → unit (US customary only). */
	readonly choices: { readonly [kind: string]: string };
}

export const SI_UNITS_SETTING: IDisplayUnits = { system: 'SI', choices: {} };

/** The display units of project settings' `units` value (any JSON); SI when it says none. */
export function readDisplayUnits(value: unknown): IDisplayUnits {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		return SI_UNITS_SETTING;
	}
	const data = value as { [key: string]: unknown };
	const choices: { [kind: string]: string } = {};
	for (const kind of OVERRIDABLE_KINDS) {
		if (typeof data[kind] === 'string' && data[kind]) {
			choices[kind] = data[kind] as string;
		}
	}
	return { system: data.system === 'USCustomary' ? 'USCustomary' : 'SI', choices };
}

/** [kind, factor to its base] of an SI unit text, or undefined (a unit SAEngine does not convert). */
export function kindOfUnit(siUnit: string | undefined): readonly [string, number] | undefined {
	return siUnit ? SI_UNITS[siUnit.trim()] : undefined;
}

/** The unit `kind` is shown in. */
export function unitOf(kind: string, units: IDisplayUnits = activeDisplayUnits()): string {
	const k = UNIT_KINDS[kind];
	if (!k) {
		return '';
	}
	if (units.system !== 'USCustomary') {
		return k.si;
	}
	const chosen = units.choices[kind];
	return k.us.find(([label]) => label === chosen)?.[0] ?? k.us[0][0];
}

function factorTo(kind: string, unit: string): number {
	const k = UNIT_KINDS[kind];
	if (!k || unit === k.si) {
		return 1;
	}
	return k.us.find(([label]) => label === unit)?.[1] ?? 1;
}

function offsetTo(kind: string, unit: string): number {
	return UNIT_KINDS[kind]?.offsets?.[unit] ?? 0;
}

/** Whether values in `siUnit` are shown in another unit than their own. */
export function isConverted(siUnit: string | undefined, units: IDisplayUnits = activeDisplayUnits()): boolean {
	return units.system === 'USCustomary' && !!kindOfUnit(siUnit);
}

/** The unit text shown for values stored in `siUnit` (the SI text itself in SI, or for a unit SAEngine does not convert). */
export function displayUnit(siUnit: string, units: IDisplayUnits = activeDisplayUnits()): string {
	const known = kindOfUnit(siUnit);
	if (known && units.system !== 'USCustomary') {
		return UNIT_KINDS[known[0]].siLabel ?? siUnit;
	}
	return known ? unitOf(known[0], units) : siUnit;
}

/** A value stored in `siUnit` as shown (unchanged in SI). */
export function toDisplay(value: number, siUnit: string, units: IDisplayUnits = activeDisplayUnits()): number {
	const known = kindOfUnit(siUnit);
	if (!known || units.system !== 'USCustomary') {
		return value;
	}
	const unit = unitOf(known[0], units);
	return value * known[1] * factorTo(known[0], unit) + offsetTo(known[0], unit);
}

/** A value as shown → the value stored in `siUnit` (unchanged in SI). */
export function fromDisplay(value: number, siUnit: string, units: IDisplayUnits = activeDisplayUnits()): number {
	const known = kindOfUnit(siUnit);
	if (!known || units.system !== 'USCustomary') {
		return value;
	}
	const unit = unitOf(known[0], units);
	return (value - offsetTo(known[0], unit)) / (known[1] * factorTo(known[0], unit));
}

/** A scale of values stored in `siUnit` (a length on a chart axis) as shown: the factor without an offset. */
export function displayFactor(siUnit: string, units: IDisplayUnits = activeDisplayUnits()): number {
	const known = kindOfUnit(siUnit);
	return known && units.system === 'USCustomary' ? known[1] * factorTo(known[0], unitOf(known[0], units)) : 1;
}

/** `significant` significant figures, whole units from 10^(significant-1), as the backend's `fmt`. */
export function significantText(value: number, significant = 3): string {
	if (!isFinite(value)) {
		return isNaN(value) ? '-' : value > 0 ? '∞' : '-∞';
	}
	const size = Math.abs(value);
	if (size === 0) {
		return '0';
	}
	if (size >= 10 ** (significant - 1)) {
		return formatNumber(value);
	}
	const decimals = Math.min(10, significant - 1 - Math.floor(Math.log10(size)));
	return formatNumber(value, { maxDecimals: decimals });
}

/**
 * A value stored in `siUnit` as text with its unit: "9.84 in" in US units; in SI the value with
 * `siDecimals` decimals (default as {@link significantText}) and its SI unit, "250 mm".
 */
export function formatQuantity(value: number, siUnit: string, options: { readonly siDecimals?: number; readonly significant?: number; readonly units?: IDisplayUnits } = {}): string {
	const units = options.units ?? activeDisplayUnits();
	if (!isConverted(siUnit, units)) {
		const text = options.siDecimals !== undefined ? formatNumber(value, { decimals: options.siDecimals }) : significantText(value, options.significant);
		return siUnit ? `${text} ${displayUnit(siUnit, units)}` : text;
	}
	return `${significantText(toDisplay(value, siUnit, units), options.significant)} ${displayUnit(siUnit, units)}`;
}

/**
 * The number of a value stored in `siUnit` for an input field: the stored text as it is in SI;
 * converted to 5 significant figures (no thousands separators) in US units.
 */
export function inputText(value: number, siUnit: string, units: IDisplayUnits = activeDisplayUnits()): string {
	if (!isConverted(siUnit, units)) {
		return String(value);
	}
	const shown = toDisplay(value, siUnit, units);
	const whole = Math.floor(Math.log10(Math.abs(shown) || 1)) + 1;
	return String(Number(shown.toPrecision(Math.min(21, Math.max(5, whole)))));
}

/** A length [mm] in feet and inches to the nearest 1/`denominator` inch: 3810 → `12'-6"`. */
export function feetInches(mm: number, denominator = 8): string {
	const sign = mm < 0 ? '-' : '';
	const steps = Math.round(Math.abs(mm) / 25.4 * denominator);
	const whole = Math.floor(steps / denominator);
	const part = steps % denominator;
	const feet = Math.floor(whole / 12);
	const inches = whole % 12;
	let fraction = '';
	if (part) {
		const g = gcd(part, denominator);
		fraction = `${part / g}/${denominator / g}`;
	}
	const inchText = [inches ? String(inches) : '', fraction].filter(t => t).join(' ');
	return feet ? `${sign}${feet}'-${inchText || '0'}"` : `${sign}${inchText || '0'}"`;
}

function gcd(a: number, b: number): number {
	return b ? gcd(b, a % b) : a;
}

/** Every unit text a value of `kind` may be typed in, → factor to the SI base. */
function typedUnits(kind: string): Map<string, number> {
	const k = UNIT_KINDS[kind];
	const out = new Map<string, number>();
	if (!k) {
		return out;
	}
	out.set(k.si, 1);
	for (const [label, factor] of k.us) {
		out.set(label, factor);
	}
	for (const [unit, [own, scale]] of Object.entries(SI_UNITS)) {
		if (own === kind) {
			out.set(unit, 1 / scale);
		}
	}
	if (kind === 'temperatureChange') {
		out.set('°C', 1);
	}
	if (kind === 'length' || kind === 'dimension') {
		const metre = kind === 'length' ? 1 : 1000;
		out.set('ft', 1 / FOOT / metre).set('\'', 1 / FOOT / metre).set('in', 1 / INCH / metre).set('"', 1 / INCH / metre);
		out.set(kind === 'length' ? 'mm' : 'm', kind === 'length' ? 1000 : 1e-3);
	}
	return out;
}

const NUMBER = /^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?$/i;
const FEET_INCHES = /^([-+]?)\s*(\d+(?:\.\d+)?)\s*(?:'|ft)\s*-?\s*(?:(\d+(?:\.\d+)?)?\s*(?:(\d+)\s*\/\s*(\d+))?\s*(?:"|in)?)?$/i;
const INCHES_FRACTION = /^([-+]?)\s*(?:(\d+(?:\.\d+)?)\s+)?(\d+)\s*\/\s*(\d+)\s*(?:"|in)?$/i;

/**
 * A value typed in a field whose stored unit is `siUnit` → the value in `siUnit`, or undefined
 * when it is not a number. A plain number is in the display unit; a number with a unit is in
 * that unit (any unit of the quantity: "300 mm" in US units, "10 ft" in SI). Lengths also
 * take feet and inches: `12'-6"`, `12' 6 1/2"`, `6 1/2"`.
 */
export function parseQuantity(text: string, siUnit: string | undefined, units: IDisplayUnits = activeDisplayUnits()): number | undefined {
	const trimmed = text.trim().replace(/,/g, '');
	if (NUMBER.test(trimmed)) {
		const value = Number(trimmed);
		return siUnit ? fromDisplay(value, siUnit, units) : value;
	}
	const known = kindOfUnit(siUnit);
	if (!known || !siUnit) {
		return undefined;
	}
	const [kind, scale] = known;
	if (kind === 'temperature') {
		// an absolute temperature typed with its unit: "68 °F", "20 °C"
		const typed = /^([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*°?\s*([CF])$/i.exec(trimmed);
		return typed ? (typed[2].toUpperCase() === 'F' ? (Number(typed[1]) - 32) / 1.8 : Number(typed[1])) : undefined;
	}
	// typed unit → the kind's base unit → the field's own SI unit
	const toSi = (value: number, factor: number) => value / factor / scale;
	if (kind === 'length' || kind === 'dimension') {
		const inchFactor = typedUnits(kind).get('in')!;
		const ft = FEET_INCHES.exec(trimmed);
		if (ft) {
			const inches = Number(ft[2]) * 12 + Number(ft[3] ?? 0) + (ft[4] ? Number(ft[4]) / Number(ft[5]) : 0);
			return toSi((ft[1] === '-' ? -1 : 1) * inches, inchFactor);
		}
		const fraction = INCHES_FRACTION.exec(trimmed);
		if (fraction && Number(fraction[4]) !== 0) {
			const inches = Number(fraction[2] ?? 0) + Number(fraction[3]) / Number(fraction[4]);
			return toSi((fraction[1] === '-' ? -1 : 1) * inches, inchFactor);
		}
	}
	const match = /^([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?)\s*(.+)$/i.exec(trimmed);
	if (!match) {
		return undefined;
	}
	const factor = typedUnits(kind).get(match[2].trim());
	return factor === undefined ? undefined : toSi(Number(match[1]), factor);
}

/**
 * Numbers typed as a list ("150, -200", "150 -200", "@150,-200": AutoCAD's relative form) in a
 * unit stored as `siUnit` (default mm) → the values in `siUnit`; undefined when a part is not a
 * number. In SI exactly as `Number` reads each part; in US units each part may be feet and
 * inches (`12'-6", 3'`), so the parts are split at commas (or at spaces between plain numbers).
 */
export function parseList(text: string, siUnit = 'mm', units: IDisplayUnits = activeDisplayUnits()): number[] | undefined {
	const body = text.trim().replace(/^@/, '');
	if (!isConverted(siUnit, units)) {
		const parts = body.split(/[\s,;]+/).filter(Boolean).map(Number);
		return parts.every(Number.isFinite) ? parts : undefined;
	}
	let parts = body.split(/[,;]+/).map(p => p.trim()).filter(Boolean);
	if (parts.length === 1 && /^[-+.\d\s]+$/.test(parts[0])) {
		parts = parts[0].split(/\s+/).filter(Boolean);
	}
	const values = parts.map(p => parseQuantity(p, siUnit, units));
	return values.every((v): v is number => v !== undefined && isFinite(v)) ? values : undefined;
}

/** A length [mm] as the editors show one: "250 mm" in SI, `9'-10 1/8"` in US units. */
export function formatLength(mm: number, units: IDisplayUnits = activeDisplayUnits()): string {
	return isConverted('mm', units) ? feetInches(mm) : `${formatNumber(Math.round(mm))} mm`;
}

// ─────────────────────────────── the open project's units ───────────────────────────────

let active: IDisplayUnits = SI_UNITS_SETTING;
const onDidChange = new Emitter<IDisplayUnits>();

/** Fires when the open project's display units change (its settings were read or edited). */
export const onDidChangeDisplayUnits: Event<IDisplayUnits> = onDidChange.event;

/** The open project's display units (SI without a project). */
export function activeDisplayUnits(): IDisplayUnits {
	return active;
}

/** Records the open project's display units: its settings' `units` (any JSON). */
export function setActiveDisplayUnits(value: unknown): void {
	const next = readDisplayUnits(value);
	if (next.system === active.system && JSON.stringify(next.choices) === JSON.stringify(active.choices)) {
		return;
	}
	active = next;
	onDidChange.fire(next);
}

/** A table or CSV heading with its unit in the display units: "Mass (kg)" → "Mass (lb)". */
export function headingWithUnit(heading: string, units: IDisplayUnits = activeDisplayUnits()): string {
	return heading.replace(/([(\[])([^()\[\]]+)([)\]])\s*$/, (whole, open: string, unit: string, close: string) => kindOfUnit(unit) ? `${open}${displayUnit(unit.trim(), units)}${close}` : whole);
}

// ─────────────────────────────── sizes and printed text (C13b) ───────────────────────────────

/** A size [mm] in inches to the nearest 1/`denominator` inch, without feet: 300 → `11 3/4"` (saengine.units.inches_text). */
export function inchesText(mm: number, denominator = 8): string {
	const sign = mm < 0 ? '-' : '';
	const steps = Math.round(Math.abs(mm) / 25.4 * denominator);
	const whole = Math.floor(steps / denominator);
	const part = steps % denominator;
	let fraction = '';
	if (part) {
		const g = gcd(part, denominator);
		fraction = `${part / g}/${denominator / g}`;
	}
	const text = [whole ? String(whole) : '', fraction].filter(t => t).join(' ');
	return `${sign}${text || '0'}"`;
}

/**
 * A member size [mm] as a label or a table writes it: the number as it is in SI ("300"); in US
 * units in inches (`11 3/4"`), or feet and inches when sizes are shown in feet (saengine.units.Units.size_text).
 */
export function sizeText(mm: number, units: IDisplayUnits = activeDisplayUnits()): string {
	if (!isConverted('mm', units)) {
		return String(mm);
	}
	return unitOf('dimension', units) === 'ft' ? feetInches(mm) : inchesText(mm);
}

let barNames: { readonly [dia: string]: string } = {};

/** Records the code pack's bar names by diameter (`concrete.barNames`: "16" → "#5"), shown in every unit system (alpha 9 C26). */
export function setActiveBarNames(names: unknown): void {
	const out: { [dia: string]: string } = {};
	if (typeof names === 'object' && names !== null && !Array.isArray(names)) {
		for (const [dia, name] of Object.entries(names)) {
			if (typeof name === 'string' && name) {
				out[dia] = name;
			}
		}
	}
	barNames = out;
}

/**
 * A bar size: the pack's name ("#5", "N16", "HD16", "16M") when it has one, in every unit system
 * (alpha 9 C26), else "Ø16" (saengine.units.Units.bar).
 */
export function barName(dia: number, _units: IDisplayUnits = activeDisplayUnits()): string {
	return barNames[String(dia)] || `Ø${dia}`;
}

/** Alpha 9 C26: `text` with its bar sizes by the pack's names in SI ("4Ø16 @ 150" → "4-N16 @ 150"); the numbers as they are (saengine.units.si_bar_names). */
function siBarNames(text: string): string {
	return text.replace(BAR, (whole: string, count: string | undefined, gap: string | undefined, dia: string, spacing: string | undefined) => {
		const own = barNames[String(Number(dia))];
		if (!own) {
			return whole;
		}
		const name = count !== undefined ? `${count}${own.startsWith('Ø') ? gap ?? '' : '-'}${own}` : own;
		return spacing === undefined ? name : `${name} @ ${spacing}`;
	});
}

const NUM = String.raw`(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?`;
const UNIT_TEXTS = Object.keys(SI_UNITS).filter(u => !['t', 'kNm', 'Δ°C', '1/°C'].includes(u)).sort((a, b) => b.length - a.length);
const UNIT_PATTERN = UNIT_TEXTS.map(u => u.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')).join('|');
const QUANTITY = new RegExp(String.raw`(?<![\w.,#Ø/·])(-?${NUM})((?:\s*(?:×|x|–|to)\s*-?${NUM})*)\s?(${UNIT_PATTERN})(?![\w²³⁴/·])`, 'g');
const SEPARATOR = new RegExp(String.raw`(\s*(?:×|x|–|to)\s*)(-?${NUM})`, 'g');
const BAR = /(?:(?<![\w.,])(\d+)(\s?))?Ø(\d+(?:\.\d+)?)(?:\s*@\s*(\d+(?:\.\d+)?)(?!\s*(?:mm|m)\b))?/g;
/** Words before a temperature that make it a change ("ΔT = 20 °C", "±20 °C", "differ by 11 °C"). */
const CHANGE = /Δ|±|\b(?:by|range|rise|drop|change|gradient)\b/i;

function numberOf(text: string): number {
	return Number(text.replace(/,/g, ''));
}

/**
 * `text` with every SI quantity it writes ("250 mm", "300 × 500 mm", "4.5 kN/m²", "20 °C") in the
 * display units, and bar sizes ("Ø16 @ 150") by the pack's names; as it is in SI. The rules of the
 * backend's `saengine.units.convert_text` (a temperature after "Δ", "±", "by" ... is a change).
 */
export function convertText(text: string, units: IDisplayUnits = activeDisplayUnits()): string {
	if (!text) {
		return text;
	}
	if (units.system !== 'USCustomary') {
		// Alpha 9 C26: SI as it is, but for the bar sizes of a pack that names them.
		return Object.keys(barNames).length ? siBarNames(text) : text;
	}
	const quantities = text.replace(QUANTITY, (_whole: string, first: string, rest: string, unit: string, at: number) => {
		// the words before it in its own clause (up to a ; , : ( ) or the temperature before it)
		const before = text.slice(Math.max(0, at - 20), at).split(/[;,:()\n°]/).pop() ?? '';
		const own = unit === '°C' && CHANGE.test(before) ? 'Δ°C' : unit;
		const shown = rest.replace(SEPARATOR, (_part: string, gap: string, value: string) => gap + significantText(toDisplay(numberOf(value), own, units)));
		return `${significantText(toDisplay(numberOf(first), own, units))}${shown} ${displayUnit(own, units)}`;
	});
	return quantities.replace(BAR, (_whole: string, count: string | undefined, gap: string | undefined, dia: string, spacing: string | undefined) => {
		let name = barName(Number(dia), units);
		if (count !== undefined) {
			name = `${count}${name.startsWith('Ø') ? gap ?? '' : '-'}${name}`;
		}
		return spacing === undefined ? name : `${name} @ ${significantText(toDisplay(Number(spacing), 'mm', units))} ${displayUnit('mm', units)}`;
	});
}
