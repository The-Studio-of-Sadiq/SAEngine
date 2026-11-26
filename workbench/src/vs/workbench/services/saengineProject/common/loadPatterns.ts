/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/**
 * Load patterns (issue #301): the built-in D, SD, L and Lr and the project's own
 * (`loadPatterns` of `02 Project Settings/project-settings.json`), as the Python model
 * `saengine.library.load_patterns` has them. Member, point and area loads name a pattern by id;
 * the combinations give the project's own patterns factors (`combinations[].patterns`).
 */

export const PATTERN_TYPES = ['Dead', 'SuperDead', 'Live', 'RoofLive', 'Wind', 'Seismic', 'Other'] as const;
export type LoadPatternType = typeof PATTERN_TYPES[number];

export interface ILoadPattern {
	readonly id: string;
	readonly name: string;
	readonly type: LoadPatternType;
	/** Times the structure's self-weight added to the pattern (the built-in D: 1). */
	readonly selfWeight: number;
	readonly builtIn: boolean;
}

export const BUILT_IN_PATTERNS: readonly ILoadPattern[] = [
	{ id: 'SD', name: localize('loadPatterns.SD', "superimposed dead"), type: 'SuperDead', selfWeight: 0, builtIn: true },
	{ id: 'D', name: localize('loadPatterns.D', "dead"), type: 'Dead', selfWeight: 1, builtIn: true },
	{ id: 'L', name: localize('loadPatterns.L', "live"), type: 'Live', selfWeight: 0, builtIn: true },
	{ id: 'Lr', name: localize('loadPatterns.Lr', "roof live"), type: 'RoofLive', selfWeight: 0, builtIn: true },
];

/** The id rule of the Python model (`LoadPattern.id`). */
export const PATTERN_ID = /^[A-Za-z][A-Za-z0-9_]{0,15}$/;

const RESERVED = new Set([
	'D', 'SD', 'L', 'Lr', 'WX', 'WY', 'EX', 'EY', 'F', 'H', 'T', 'ST', 'CS', 'R', 'FaX', 'FaY', 'S',
	'EXP', 'EXN', 'EYP', 'EYN', 'WTX', 'WTY', 'WI', 'WXN', 'WYN', 'EZ', 'E', 'RX', 'RY', 'AX', 'AY', 'W', 'Fa', 'MODAL', 'PT',
].map(c => c.toLowerCase()));
const RESERVED_FAMILIES = /^(LP\d+|TO\d+|C\d.*|W[XY]N?\d+)$/i;

/** Whether `id` is a case code the program uses itself (`saengine.library.load_patterns.reserved`). */
export function reservedPatternId(id: string): boolean {
	return RESERVED.has(id.toLowerCase()) || RESERVED_FAMILIES.test(id);
}

/** Why `id` cannot be a load pattern's id (`others`: the other patterns' ids), or undefined. */
export function patternIdProblem(id: string, others: readonly string[]): string | undefined {
	if (!PATTERN_ID.test(id)) {
		return localize('loadPatterns.idRule', "A letter, then letters, digits or _ (up to 16 characters).");
	}
	if (reservedPatternId(id)) {
		return localize('loadPatterns.idReserved', "{0} is a load case code the program uses itself; choose another.", id);
	}
	if (others.includes(id)) {
		return localize('loadPatterns.idTaken', "Another load pattern is {0}.", id);
	}
	return undefined;
}

type Json = { readonly [key: string]: unknown };

/** The project's own load patterns of a settings document (none when it has none or is unreadable). */
export function userPatterns(settings: unknown): ILoadPattern[] {
	const list = (settings as Json | undefined)?.loadPatterns;
	if (!Array.isArray(list)) {
		return [];
	}
	return list.filter((p): p is Json => !!p && typeof p === 'object' && typeof (p as Json).id === 'string').map(p => ({
		id: String(p.id),
		name: typeof p.name === 'string' && p.name ? p.name : String(p.id),
		type: PATTERN_TYPES.includes(p.type as LoadPatternType) ? p.type as LoadPatternType : 'Other',
		selfWeight: typeof p.selfWeight === 'number' ? p.selfWeight : 0,
		builtIn: false,
	}));
}

/** Every pattern a load may go to: the built-in ones (SD first, the default), then the project's. */
export function allPatterns(settings: unknown): ILoadPattern[] {
	return [...BUILT_IN_PATTERNS, ...userPatterns(settings)];
}

/** "SD: superimposed dead", "EQP: Equipment on the roof". */
export function patternLabel(pattern: ILoadPattern): string {
	return `${pattern.id}: ${pattern.name}`;
}
