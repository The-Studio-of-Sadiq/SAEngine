/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { storedFieldProblems } from './modifiersModel.js';

/*
 * The problems of the stiffness modifiers and design overwrites, for the problem lists and the
 * part statuses ("4 Objects" for the object types, "5 Floor Plan" for the members):
 *
 * - values typed into a field that cannot be stored ("abc", "-0.5"): the panel keeps them in
 *   the field, marked, until they are corrected or cleared (`unappliedFields`);
 * - stored values the checks would refuse, from a hand edit or an older file
 *   (`storedFieldProblems` in modifiersModel.ts).
 *
 * `modifierProblems(part, doc)` gives both; `onDidChangeModifierProblems` fires when the typed
 * ones change (the stored ones change with the document).
 */

/** The part whose document holds the fields. */
export type ModifierPart = 'objects' | 'floorPlan';

interface IUnapplied {
	readonly part: ModifierPart;
	readonly message: string;
}

const unapplied = new Map<string, IUnapplied>();
const onDidChange = new Emitter<void>();

/** Fires when a typed value that cannot be stored appears or goes. */
export const onDidChangeModifierProblems: Event<void> = onDidChange.event;

/** Records (`message`) or clears (undefined) the problem of the field `id` (panel scope, group and key). */
export function setUnappliedField(id: string, part: ModifierPart, message: string | undefined): void {
	const current = unapplied.get(id);
	if (message === undefined ? !current : current?.message === message && current.part === part) {
		return;
	}
	if (message === undefined) {
		unapplied.delete(id);
	} else {
		unapplied.set(id, { part, message });
	}
	onDidChange.fire();
}

/** The typed values of `part` that cannot be stored, as messages. */
export function unappliedFields(part: ModifierPart): string[] {
	return [...unapplied.values()].filter(u => u.part === part).map(u => u.message);
}

/**
 * Every problem of the modifiers and overwrites of `part`: the typed values that cannot be
 * stored, then the stored values the checks refuse in `doc` (the part's parsed document).
 * Its length is the count for the part's status.
 */
export function modifierProblems(part: ModifierPart, doc: unknown): string[] {
	return [...unappliedFields(part), ...storedFieldProblems(doc, part).map(p => p.message)];
}
