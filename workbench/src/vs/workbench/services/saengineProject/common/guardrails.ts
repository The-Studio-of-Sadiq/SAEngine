/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { GUARDRAIL_RULES, IGuardrailLimit, IGuardrailRule } from './projectLibraries.generated.js';

/**
 * The input guardrails of the workbench (U2): the rules of `saengine.library.guardrails`
 * (`python/src/saengine/library/data/guardrails.json`), checked on each field as it is typed so
 * an impossible value is refused where it is entered, with the reason. The rules are the
 * Python ones, not a second set: the practice limits come with the generated library module,
 * the code pack's limits (least f'c, most fy, bar sizes) from the backend (`library/limits`,
 * {@link LIBRARY_LIMITS_COMMAND}) once a project is open. Unusual values (`warn`) are not refused
 * here: the full check (`saengine.library.check`) lists them as warnings.
 */

/** Internal command: the rules with the open project's code pack limits filled in (`{rules}`). */
export const LIBRARY_LIMITS_COMMAND = 'saengine.library.limits';

export interface IGuardrailVerdict {
	readonly severity: 'error' | 'warning';
	readonly message: string;
}

const PRACTICE = GUARDRAIL_RULES.source;

let resolved: readonly IGuardrailRule[] | undefined;
const onDidChange = new Emitter<void>();
/** The rules changed (the project's code pack limits arrived or changed). */
export const onDidChangeGuardrails: Event<void> = onDidChange.event;

/** Takes the rules the backend resolved for the open project's code pack (undefined: the practice rules only). */
export function setResolvedGuardrails(rules: readonly IGuardrailRule[] | undefined): void {
	resolved = rules;
	onDidChange.fire();
}

/** The rules of a file kind: the backend's resolved ones, else the practice ones (pack limits left out). */
export function guardrailRules(kind: string): readonly IGuardrailRule[] {
	const rules = resolved ?? GUARDRAIL_RULES.rules.map(rule => ({
		...rule,
		block: rule.block?.filter(l => !l.fromPack).map(l => ({ ...l, source: l.source ?? PRACTICE })),
		warn: rule.warn?.filter(l => !l.fromPack).map(l => ({ ...l, source: l.source ?? PRACTICE })),
	}));
	return rules.filter(r => r.kind === kind);
}

/** One rule by id (practice limits until the backend answered). */
export function guardrailRule(id: string): IGuardrailRule | undefined {
	for (const kind of ['materials', 'objects', 'floorPlan', 'memberLoads']) {
		const rule = guardrailRules(kind).find(r => r.id === id);
		if (rule) {
			return rule;
		}
	}
	return undefined;
}

/** The first block limit of a rule with a `min`/`max`: the range a value must keep. */
export function blockRange(id: string): { readonly min?: number; readonly max?: number; readonly reason?: string } {
	const limit = guardrailRule(id)?.block?.find(l => l.min !== undefined || l.max !== undefined);
	return { min: limit?.min, max: limit?.max, reason: limit?.reason };
}

// ───────────────────────────── evaluation (as saengine.library.guardrails) ─────────────────────────────

function num(value: number): string {
	return String(Number(value.toPrecision(6)));
}

function withUnit(value: number, unit: string | undefined): string {
	return unit ? `${num(value)} ${unit}` : num(value);
}

function capital(text: string): string {
	const first = text.split(' ', 1)[0];
	return /^[a-z]+$/i.test(first) && (first.length > 2 || first === 'a' || first === 'an') ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

function violation(limit: IGuardrailLimit, value: number, unit: string | undefined): string | undefined {
	if (!isFinite(value)) {
		return undefined;
	}
	if (limit.oneOf) {
		return limit.oneOf.some(a => Math.abs(value - a) < 1e-6) ? undefined : `${withUnit(value, unit)} is ${limit.reason} (${limit.oneOf.map(num).join(', ')})`;
	}
	if (limit.min !== undefined && value < limit.min) {
		return `${withUnit(value, unit)} is below ${withUnit(limit.min, unit)}: ${limit.reason}`;
	}
	if (limit.max !== undefined && value > limit.max) {
		return `${withUnit(value, unit)} is above ${withUnit(limit.max, unit)}: ${limit.reason}`;
	}
	return undefined;
}

/** `value` against `rule`: the first block it breaks (error), else the first warn (warning). */
export function judge(rule: IGuardrailRule, value: number, what = rule.what): IGuardrailVerdict | undefined {
	for (const [limits, severity] of [[rule.block, 'error'], [rule.warn, 'warning']] as const) {
		for (const limit of limits ?? []) {
			const detail = violation(limit, value, rule.unit);
			if (detail) {
				return { severity, message: `${capital(`${what} ${detail}`)} (${limit.source ?? PRACTICE}).` };
			}
		}
	}
	return undefined;
}

/** A count against a rule's `max` limits (storeys, spans). */
export function judgeCount(rule: IGuardrailRule, count: number, where = ''): IGuardrailVerdict | undefined {
	for (const [limits, severity] of [[rule.block, 'error'], [rule.warn, 'warning']] as const) {
		for (const limit of limits ?? []) {
			if (limit.max !== undefined && count > limit.max) {
				return { severity, message: `${capital(`${count} ${rule.what}${where} is more than ${num(limit.max)}: ${limit.reason}`)} (${limit.source ?? PRACTICE}).` };
			}
		}
	}
	return undefined;
}

type Json = unknown;

function isRecord(value: Json): value is Record<string, Json> {
	return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** Whether the dotted `path` is one `pattern` names (`*`: any key or index). */
function matches(pattern: string, path: string): boolean {
	const p = pattern.split('.');
	const q = path.split('.');
	return p.length === q.length && p.every((part, i) => part === '*' || part === q[i]);
}

function at(node: Json, path: string): Json {
	let current = node;
	for (const key of path.split('.')) {
		if (Array.isArray(current)) {
			current = current[Number(key)];
		} else if (isRecord(current)) {
			current = current[key];
		} else {
			return undefined;
		}
	}
	return current;
}

function applies(rule: IGuardrailRule, item: Json): boolean {
	return Object.entries(rule.when ?? {}).every(([field, allowed]) => isRecord(item) && allowed.includes(String(item[field])));
}

/** A member's least overall dimension [mm] the cover sits in (as `guardrails.least_dimension`). */
function leastDimension(item: Json): number | undefined {
	if (!isRecord(item)) {
		return undefined;
	}
	const profile = item.profile;
	if (isRecord(profile)) {
		if (profile.shape === 'rectangle' && typeof profile.xDim === 'number' && typeof profile.yDim === 'number') {
			return Math.min(profile.xDim, profile.yDim);
		}
		return profile.shape === 'circle' && typeof profile.radius === 'number' ? 2 * profile.radius : undefined;
	}
	return typeof item.thickness === 'number' && item.thickness > 0 ? item.thickness : undefined;
}

/** The levels next to entry `index` of a sorted list: the gaps that change when it moves. */
function neighbourGaps(entries: readonly Json[], index: number, key: string, label: (e: Json) => string): { gap: number; between: string }[] {
	const values = entries.map((e, i) => ({ i, v: isRecord(e) ? e[key] : undefined, e })).filter((x): x is { i: number; v: number; e: Json } => typeof x.v === 'number');
	values.sort((a, b) => a.v - b.v);
	const k = values.findIndex(x => x.i === index);
	if (k < 0) {
		return [];
	}
	const gaps: { gap: number; between: string }[] = [];
	if (k > 0) {
		gaps.push({ gap: values[k].v - values[k - 1].v, between: `${label(values[k - 1].e)} to ${label(values[k].e)}` });
	}
	if (k + 1 < values.length) {
		gaps.push({ gap: values[k + 1].v - values[k].v, between: `${label(values[k].e)} to ${label(values[k + 1].e)}` });
	}
	return gaps;
}

function worst(a: IGuardrailVerdict | undefined, b: IGuardrailVerdict | undefined): IGuardrailVerdict | undefined {
	return !a || (a.severity === 'warning' && b?.severity === 'error') ? b ?? a : a;
}

/**
 * The verdict on the field at `path` of `document` (an entry of a list file: one material or
 * object type; else the whole file) of file `kind`, with the value being typed already in it.
 */
export function checkField(kind: string, document: Json, path: string): IGuardrailVerdict | undefined {
	let verdict: IGuardrailVerdict | undefined;
	for (const rule of guardrailRules(kind)) {
		if (!rule.paths.some(p => matches(p, path)) || !applies(rule, document)) {
			continue;
		}
		const value = at(document, path);
		switch (rule.derived) {
			case undefined:
				if (typeof value === 'number') {
					verdict = worst(verdict, judge(rule, value));
				}
				break;
			case 'coverInMember': {
				const least = leastDimension(document);
				const limit = rule.block?.[0];
				if (least !== undefined && typeof value === 'number' && 2 * value >= least && limit) {
					verdict = worst(verdict, { severity: 'error', message: `${capital(`${rule.what} ${num(value)} mm in a ${num(least)} mm section: ${limit.reason}`)} (${limit.source ?? PRACTICE}).` });
				}
				break;
			}
			case 'storeyHeight':
			case 'gridSpacing': {
				const [list, index] = rule.derived === 'storeyHeight'
					? [at(document, 'stories'), Number(path.split('.')[1])]
					: [at(document, path.split('.').slice(0, 2).join('.')), Number(path.split('.')[2])];
				if (Array.isArray(list)) {
					const key = rule.derived === 'storeyHeight' ? 'elevation' : 'position';
					const label = (e: Json) => isRecord(e) ? String(e.name ?? e.label ?? e.id ?? '') : '';
					for (const { gap, between } of neighbourGaps(list, index, key, label)) {
						verdict = worst(verdict, judge(rule, gap, `${rule.what} (${between})`));
					}
				}
				break;
			}
		}
	}
	return verdict;
}

/**
 * The verdict on `text` typed into the field at `path` of `owner` (the entry or file the form
 * edits): the value is put into a copy, then {@link checkField}. Text that is not a number is
 * left to the form's own checks.
 */
export function checkTypedField(kind: string, owner: Json, path: string, text: string): IGuardrailVerdict | undefined {
	const value = Number(text.trim());
	if (!text.trim() || !isFinite(value) || !guardrailRules(kind).some(r => r.paths.some(p => matches(p, path)))) {
		return undefined;
	}
	const copy = JSON.parse(JSON.stringify(owner ?? {})) as Json;
	const keys = path.split('.');
	let node: Json = copy;
	for (const key of keys.slice(0, -1)) {
		node = Array.isArray(node) ? node[Number(key)] : isRecord(node) ? node[key] : undefined;
	}
	const last = keys[keys.length - 1];
	if (Array.isArray(node)) {
		node[Number(last)] = value;
	} else if (isRecord(node)) {
		node[last] = value;
	} else {
		return undefined;
	}
	return checkField(kind, copy, path);
}

/** The blocked reason of a typed field, for a form's `validate` (warnings are not refused). */
export function guardrailError(kind: string, owner: Json, path: string, text: string): string | undefined {
	const verdict = checkTypedField(kind, owner, path, text);
	return verdict?.severity === 'error' ? verdict.message : undefined;
}
