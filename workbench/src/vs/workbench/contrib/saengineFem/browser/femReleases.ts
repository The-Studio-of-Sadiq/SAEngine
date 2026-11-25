/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, applyPropertyOnCommit } from '../../saengineProject/browser/editorFrame.js';

/*
 * #303: member end releases and point springs, edited in the analysis model's Properties panel
 * for the member or joint picked in 3D. They are stored in the building model
 * (`06 BIM/bim.json`, `additions.endReleases` and `additions.pointSprings`: the BIM window's
 * Additions form edits the same lists) and applied when the analysis model is derived
 * (saengine.fem.derive). The functions here edit the building model's text; the panel calls
 * them and the editor writes the text back as one undoable edit.
 */

/** The actions at a member end, in its member axes 1-2-3 (saengine.library.bim.END_ACTIONS). */
export const END_ACTIONS = ['P', 'V2', 'V3', 'T', 'M2', 'M3'] as const;
export type EndAction = typeof END_ACTIONS[number];
export type MemberEnd = 'start' | 'end';
/** The springs of a point spring, along and about the global axes. */
export const SPRING_KEYS = ['UX', 'UY', 'UZ', 'RX', 'RY', 'RZ'] as const;
export type SpringKey = typeof SPRING_KEYS[number];
export type SpringSupport = 'none' | 'pinned' | 'fixed';

type Json = { [key: string]: unknown };

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parse(text: string | undefined): Json | undefined {
	try {
		const value = text ? JSON.parse(text) : undefined;
		return isObject(value) ? value : undefined;
	} catch {
		return undefined;
	}
}

function list(bim: Json, key: 'endReleases' | 'pointSprings'): Json[] {
	const additions = isObject(bim.additions) ? bim.additions : (bim.additions = {});
	const items = Array.isArray(additions[key]) ? additions[key] as unknown[] : (additions[key] = []) as unknown[];
	return items.filter(isObject);
}

/** The next free id with `prefix` among the building model's elements and additions. */
function nextId(bim: Json, prefix: string): string {
	const additions = isObject(bim.additions) ? bim.additions : {};
	const used = new Set([
		...(Array.isArray(bim.elements) ? bim.elements : []),
		...Object.values(additions).flatMap(items => Array.isArray(items) ? items : []),
	].filter(isObject).map(item => String(item.id)));
	let n = 1;
	while (used.has(`${prefix}${n}`)) {
		n++;
	}
	return `${prefix}${n}`;
}

function text(bim: Json): string {
	return JSON.stringify(bim, undefined, '\t') + '\n';
}

/** A member's end releases: per end, each released action -> 0 (released) or its spring. */
export interface IMemberReleases {
	readonly id: string | undefined;
	readonly start: { readonly [action in EndAction]?: number };
	readonly end: { readonly [action in EndAction]?: number };
}

function endOf(value: unknown): { [action in EndAction]?: number } {
	const out: { [action in EndAction]?: number } = {};
	if (isObject(value)) {
		for (const action of END_ACTIONS) {
			const v = value[action];
			if (typeof v === 'number' && Number.isFinite(v) && v >= 0) {
				out[action] = v;
			}
		}
	}
	return out;
}

/** The end releases of `member` in the building model's text (none: everything fixed). */
export function memberReleases(bimText: string | undefined, member: string): IMemberReleases {
	const bim = parse(bimText);
	const found = bim ? list(bim, 'endReleases').find(r => r.member === member) : undefined;
	return { id: typeof found?.id === 'string' ? found.id : undefined, start: endOf(found?.start), end: endOf(found?.end) };
}

/**
 * The building model's text with one action of `member`'s `end` set: `undefined` fixed, 0
 * released, a value a spring [kN/m, kN·m/rad]. A member left with nothing released loses its
 * entry. Undefined when the text is not a building model.
 */
export function withMemberRelease(bimText: string | undefined, member: string, end: MemberEnd, action: EndAction, value: number | undefined): string | undefined {
	return withMemberReleases(bimText, member, { [end]: { [action]: value } });
}

/** {@link withMemberRelease} for several actions at once (`undefined` values fix them). */
export function withMemberReleases(bimText: string | undefined, member: string, changes: { readonly [end in MemberEnd]?: { readonly [action in EndAction]?: number | undefined } }): string | undefined {
	const bim = parse(bimText);
	if (!bim) {
		return undefined;
	}
	const items = list(bim, 'endReleases');
	let release = items.find(r => r.member === member);
	if (!release) {
		release = { id: nextId(bim, 'ER'), member, start: {}, end: {} };
		((bim.additions as Json).endReleases as unknown[]).push(release);
	}
	for (const end of ['start', 'end'] as const) {
		const actions = isObject(release[end]) ? release[end] as Json : (release[end] = {}) as Json;
		for (const [action, value] of Object.entries(changes[end] ?? {})) {
			if (value === undefined) {
				delete actions[action];
			} else {
				actions[action] = value;
			}
		}
	}
	if (!Object.keys(endOf(release.start)).length && !Object.keys(endOf(release.end)).length) {
		const all = (bim.additions as Json).endReleases as unknown[];
		all.splice(all.indexOf(release), 1);
	}
	return text(bim);
}

/** A joint's point spring: its springs [kN/m, kN·m/rad] and its support. */
export interface IPointSpring {
	readonly id: string | undefined;
	readonly springs: { readonly [key in SpringKey]?: number };
	readonly support: SpringSupport;
}

function sameMm(a: unknown, b: readonly number[]): boolean {
	return Array.isArray(a) && a.length === 3 && a.every((v, i) => typeof v === 'number' && Math.abs(v - b[i]) < 1);
}

/** The point spring at `at` [mm] (none: no springs, no support). */
export function pointSpring(bimText: string | undefined, at: readonly number[]): IPointSpring {
	const bim = parse(bimText);
	const found = bim ? list(bim, 'pointSprings').find(s => sameMm(s.at, at)) : undefined;
	const springs: { [key in SpringKey]?: number } = {};
	for (const key of SPRING_KEYS) {
		const v = found?.[key];
		if (typeof v === 'number' && v > 0) {
			springs[key] = v;
		}
	}
	const support = found?.support === 'pinned' || found?.support === 'fixed' ? found.support : 'none';
	return { id: typeof found?.id === 'string' ? found.id : undefined, springs, support };
}

/**
 * The building model's text with the point spring at `at` [mm] changed: a spring (`undefined`
 * or 0: none) or the support. A joint left with no spring and no support loses its entry.
 */
export function withPointSpring(bimText: string | undefined, at: readonly number[], key: SpringKey | 'support', value: number | SpringSupport | undefined): string | undefined {
	const bim = parse(bimText);
	if (!bim) {
		return undefined;
	}
	const items = list(bim, 'pointSprings');
	let spring = items.find(s => sameMm(s.at, at));
	if (!spring) {
		spring = { id: nextId(bim, 'PS'), at: at.map(v => Math.round(v)) };
		((bim.additions as Json).pointSprings as unknown[]).push(spring);
	}
	if (value === undefined || value === 0 || value === 'none') {
		delete spring[key];
	} else {
		spring[key] = value;
	}
	if (!SPRING_KEYS.some(k => typeof spring[k] === 'number' && spring[k] as number > 0) && (spring.support ?? 'none') === 'none') {
		const all = (bim.additions as Json).pointSprings as unknown[];
		all.splice(all.indexOf(spring), 1);
	}
	return text(bim);
}

/** A typed stiffness: '' -> undefined, else a number ≥ 0; NaN when it is not one. */
export function parseStiffness(value: string): number | undefined {
	const trimmed = value.trim();
	if (!trimmed) {
		return undefined;
	}
	const n = Number(trimmed);
	return Number.isFinite(n) && n >= 0 ? n : NaN;
}

const ACTION_LABELS: { readonly [action in EndAction]: string } = {
	P: localize('femReleases.P', "Axial P"),
	V2: localize('femReleases.V2', "Shear V2"),
	V3: localize('femReleases.V3', "Shear V3"),
	T: localize('femReleases.T', "Torsion T"),
	M2: localize('femReleases.M2', "Moment M2"),
	M3: localize('femReleases.M3', "Moment M3"),
};

const SPRING_LABELS: { readonly [key in SpringKey]: string } = {
	UX: localize('femReleases.UX', "Spring X [kN/m]"),
	UY: localize('femReleases.UY', "Spring Y [kN/m]"),
	UZ: localize('femReleases.UZ', "Spring Z [kN/m]"),
	RX: localize('femReleases.RX', "About X [kN·m/rad]"),
	RY: localize('femReleases.RY', "About Y [kN·m/rad]"),
	RZ: localize('femReleases.RZ', "About Z [kN·m/rad]"),
};

export interface IReleasePanelOptions {
	readonly contextViewService: IContextViewService;
	/** The building model's text (unsaved edits included), undefined when it is not open. */
	readonly bimText: string | undefined;
	/** Writes the building model's new text as one undoable edit. */
	readonly write: (text: string) => void;
}

function stiffnessInput(row: HTMLElement, store: DisposableStore, options: IReleasePanelOptions, label: string, value: number | undefined, placeholder: string, apply: (value: number | undefined) => string | undefined): void {
	const box = store.add(new InputBox(row, options.contextViewService, { inputBoxStyles: defaultInputBoxStyles, placeholder, ariaLabel: label }));
	box.value = value === undefined ? '' : String(value);
	store.add(applyPropertyOnCommit(box.inputElement, typed => {
		const parsed = parseStiffness(typed);
		if (Number.isNaN(parsed)) {
			box.showMessage({ type: MessageType.ERROR, content: localize('femReleases.invalid', "A number, 0 or more (empty: none).") });
			return;
		}
		box.hideMessage();
		const next = apply(parsed);
		if (next !== undefined) {
			options.write(next);
		}
	}));
}

/**
 * The "End Releases" section for a member: per action its start and end, each empty (fixed),
 * 0 (released) or a spring (partial fixity), and buttons that pin an end (release M2 and M3).
 */
export function renderEndReleases(panel: HTMLElement, member: string, store: DisposableStore, options: IReleasePanelOptions): HTMLElement {
	const section = append(panel, $('.fem-releases'));
	const releases = memberReleases(options.bimText, member);
	appendPropertyHeading(section, localize('femReleases.heading', "End Releases"), member);
	if (options.bimText === undefined) {
		appendPropertyNote(section, localize('femReleases.noBim', "Build the building model (6 BIM) first: end releases are stored there."));
		return section;
	}
	appendPropertyNote(section, localize('femReleases.help', "In the member axes. Empty: fixed; 0: released; a value: a spring (kN/m, kN·m/rad). Derive the model again to apply."));
	const ends = $('.fem-releases-pair.fem-releases-ends');
	append(ends, $('span', undefined, localize('femReleases.startHead', "Start (i)")));
	append(ends, $('span', undefined, localize('femReleases.endHead', "End (j)")));
	appendPropertyRow(section, '', ends);
	for (const action of END_ACTIONS) {
		const cells = $('.fem-releases-pair');
		for (const end of ['start', 'end'] as const) {
			const label = localize('femReleases.cellAria', "{0} at the {1} of {2}", ACTION_LABELS[action], end === 'start' ? localize('femReleases.start', "start") : localize('femReleases.end', "end"), member);
			stiffnessInput(cells, store, options, label, releases[end][action], localize('femReleases.fixed', "fixed"),
				value => withMemberRelease(options.bimText, member, end, action, value));
		}
		appendPropertyRow(section, ACTION_LABELS[action], cells);
	}
	const buttons = append(section, $('.fem-releases-buttons'));
	const pin = (end: MemberEnd, label: string) => {
		const button = store.add(new Button(buttons, { ...defaultButtonStyles, secondary: true, title: localize('femReleases.pinTitle', "Release the moments M2 and M3 at this end") }));
		button.label = label;
		store.add(button.onDidClick(() => {
			const next = withMemberReleases(options.bimText, member, { [end]: { M2: 0, M3: 0 } });
			if (next !== undefined) {
				options.write(next);
			}
		}));
	};
	pin('start', localize('femReleases.pinStart', "Pin Start"));
	pin('end', localize('femReleases.pinEnd', "Pin End"));
	if (releases.id) {
		const clear = store.add(new Button(buttons, { ...defaultButtonStyles, secondary: true }));
		clear.label = localize('femReleases.clear', "Fix Both Ends");
		store.add(clear.onDidClick(() => {
			const fixed = Object.fromEntries(END_ACTIONS.map(a => [a, undefined]));
			const next = withMemberReleases(options.bimText, member, { start: fixed, end: fixed });
			if (next !== undefined) {
				options.write(next);
			}
		}));
	}
	return section;
}

/** The "Point Spring" section for a joint at `at` [mm]: six springs and a support. */
export function renderPointSpring(panel: HTMLElement, at: readonly number[], store: DisposableStore, options: IReleasePanelOptions): HTMLElement {
	const section = append(panel, $('.fem-releases'));
	const spring = pointSpring(options.bimText, at);
	appendPropertyHeading(section, localize('femReleases.springHeading', "Point Spring"), `(${at.map(v => Math.round(v)).join(', ')}) mm`);
	if (options.bimText === undefined) {
		appendPropertyNote(section, localize('femReleases.springNoBim', "Build the building model (6 BIM) first: point springs are stored there."));
		return section;
	}
	appendPropertyNote(section, localize('femReleases.springHelp', "Springs to the ground along and about the global axes (empty: none), and a support. Derive the model again to apply."));
	for (const key of SPRING_KEYS) {
		const cell = $('.fem-releases-single');
		stiffnessInput(cell, store, options, SPRING_LABELS[key], spring.springs[key], localize('femReleases.none', "none"),
			value => withPointSpring(options.bimText, at, key, value));
		appendPropertyRow(section, SPRING_LABELS[key], cell);
	}
	const supports: readonly SpringSupport[] = ['none', 'pinned', 'fixed'];
	const select = store.add(new SelectBox([
		{ text: localize('femReleases.supportNone', "No support") },
		{ text: localize('femReleases.supportPinned', "Pinned (translations held)") },
		{ text: localize('femReleases.supportFixed', "Fixed (all six held)") },
	], supports.indexOf(spring.support), options.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femReleases.supportAria', "Support at the joint") }));
	const cell = $('.fem-releases-single');
	select.render(cell);
	store.add(select.onDidSelect(({ index }) => {
		const next = withPointSpring(options.bimText, at, 'support', supports[index]);
		if (next !== undefined) {
			options.write(next);
		}
	}));
	appendPropertyRow(section, localize('femReleases.support', "Support"), cell);
	return section;
}
