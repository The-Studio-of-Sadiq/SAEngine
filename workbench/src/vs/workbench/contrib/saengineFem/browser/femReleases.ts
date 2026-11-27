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
import { IActionStep } from '../../../services/saengineProject/common/saengineActions.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, applyPropertyOnCommit } from '../../saengineProject/browser/editorFrame.js';

/*
 * #303: member end releases and point springs, edited in the analysis model's Properties panel
 * for the member or joint picked in 3D. They are stored in the building model
 * (`06 BIM/bim.json`, `additions.endReleases` and `additions.pointSprings`: the BIM window's
 * Additions form edits the same lists) and applied when the analysis model is derived
 * (saengine.fem.derive). The functions here read the building model's text; every change is
 * one shared editing action (`release.set`, `spring.set`, issue #280), the same the terminal
 * (`saengine release set`) and the assistant run, so the edit logic lives in the engine only.
 * The editor runs the action and applies its answer as one undoable edit.
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
	/** Runs a shared editing action on the building model (one undoable edit). */
	readonly run: (step: IActionStep) => void;
}

function stiffnessInput(row: HTMLElement, store: DisposableStore, options: IReleasePanelOptions, label: string, value: number | undefined, placeholder: string, step: (value: number | undefined) => IActionStep): HTMLInputElement {
	const box = store.add(new InputBox(row, options.contextViewService, { inputBoxStyles: defaultInputBoxStyles, placeholder, ariaLabel: label }));
	box.value = value === undefined ? '' : String(value);
	store.add(applyPropertyOnCommit(box.inputElement, typed => {
		const parsed = parseStiffness(typed);
		if (Number.isNaN(parsed)) {
			box.showMessage({ type: MessageType.ERROR, content: localize('femReleases.invalid', "A number, 0 or more (empty: none).") });
			return;
		}
		box.hideMessage();
		options.run(step(parsed));
	}));
	return box.inputElement;
}

/** A release panel: its section, and its first box (focused when the ribbon opens it). */
export interface IReleaseSection {
	readonly section: HTMLElement;
	readonly first?: HTMLInputElement;
}

/**
 * The "End Releases" section for a member: per action its start and end, each empty (fixed),
 * 0 (released) or a spring (partial fixity), and buttons that pin an end (release M2 and M3).
 */
export function renderEndReleases(panel: HTMLElement, member: string, store: DisposableStore, options: IReleasePanelOptions): IReleaseSection {
	const section = append(panel, $('.fem-releases'));
	let first: HTMLInputElement | undefined;
	const releases = memberReleases(options.bimText, member);
	appendPropertyHeading(section, localize('femReleases.heading', "End Releases"), member);
	if (options.bimText === undefined) {
		appendPropertyNote(section, localize('femReleases.noBim', "Build the building model (6 BIM) first: end releases are stored there."));
		return { section };
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
			const input = stiffnessInput(cells, store, options, label, releases[end][action], localize('femReleases.fixed', "fixed"),
				value => ({ action: 'release.set', params: { members: [member], [end]: { [action]: value ?? null } } }));
			first ??= input;
		}
		appendPropertyRow(section, ACTION_LABELS[action], cells);
	}
	const buttons = append(section, $('.fem-releases-buttons'));
	const pin = (end: MemberEnd, label: string) => {
		const button = store.add(new Button(buttons, { ...defaultButtonStyles, secondary: true, title: localize('femReleases.pinTitle', "Release the moments M2 and M3 at this end") }));
		button.label = label;
		store.add(button.onDidClick(() => options.run({ action: 'release.set', params: { members: [member], preset: end === 'start' ? 'pinnedStart' : 'pinnedEnd' } })));
	};
	pin('start', localize('femReleases.pinStart', "Pin Start"));
	pin('end', localize('femReleases.pinEnd', "Pin End"));
	if (releases.id) {
		const clear = store.add(new Button(buttons, { ...defaultButtonStyles, secondary: true }));
		clear.label = localize('femReleases.clear', "Fix Both Ends");
		store.add(clear.onDidClick(() => options.run({ action: 'release.set', params: { members: [member], preset: 'fixed' } })));
	}
	return { section, first };
}

/** The "Point Spring" section for a joint at `at` [mm]: six springs and a support. */
export function renderPointSpring(panel: HTMLElement, at: readonly number[], store: DisposableStore, options: IReleasePanelOptions): IReleaseSection {
	const section = append(panel, $('.fem-releases'));
	let first: HTMLInputElement | undefined;
	const spring = pointSpring(options.bimText, at);
	appendPropertyHeading(section, localize('femReleases.springHeading', "Point Spring"), `(${at.map(v => Math.round(v)).join(', ')}) mm`);
	if (options.bimText === undefined) {
		appendPropertyNote(section, localize('femReleases.springNoBim', "Build the building model (6 BIM) first: point springs are stored there."));
		return { section };
	}
	appendPropertyNote(section, localize('femReleases.springHelp', "Springs to the ground along and about the global axes (empty: none), and a support. Derive the model again to apply."));
	for (const key of SPRING_KEYS) {
		const cell = $('.fem-releases-single');
		const input = stiffnessInput(cell, store, options, SPRING_LABELS[key], spring.springs[key], localize('femReleases.none', "none"),
			value => ({ action: 'spring.set', params: { at: [...at], [key]: value ?? null } }));
		first ??= input;
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
	store.add(select.onDidSelect(({ index }) => options.run({ action: 'spring.set', params: { at: [...at], support: supports[index] } })));
	appendPropertyRow(section, localize('femReleases.support', "Support"), cell);
	return { section, first };
}
