/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { timeout } from '../../../../base/common/async.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';

/*
 * Alpha 9 C22: the site's hazard values looked up online by its coordinates. The code pack names
 * the services (its `hazardLookup` table); the Python backend builds the query and sends it
 * (`hazard/offers`, `hazard/lookup`), so this side only asks: the global setting first (off by
 * default), then the engineer's yes to the exact request shown, then the values shown before
 * they are applied. Only the coordinates and the code parameters leave the machine. Used by
 * Project Settings > Site and by the New Project wizard.
 */

/** The global opt-in (application scope: a project's settings cannot turn it on). */
export const ALLOW_HAZARD_LOOKUP_SETTING = 'saengine.hazard.allowOnlineLookups';
/** The pack's services and the exact request each would send (no network). */
export const HAZARD_OFFERS_COMMAND = 'saengine.hazard.offers';
/** Sends the request the engineer confirmed (refused by the backend without `consent`). */
export const HAZARD_LOOKUP_COMMAND = 'saengine.hazard.lookup';

/** The settings fields a lookup fills that are spectra (`(T, Sa)` points). */
const SPECTRUM_TARGETS = new Set(['site.spectral.designSpectrum', 'site.spectral.mcerSpectrum']);

type Bag = { readonly [key: string]: unknown };

function bag(value: unknown): Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Bag : {};
}

function text(value: unknown): string {
	return typeof value === 'string' ? value : '';
}

export interface IHazardOffer {
	readonly id: string;
	readonly service: string;
	readonly publisher: string;
	readonly reference: string;
	readonly host: string;
	readonly documentation: string;
	readonly terms: string;
	readonly timeout: number;
	/** The request that would be sent; undefined with a `problem`. */
	readonly url?: string;
	readonly query?: { readonly [name: string]: string };
	/** Why the service cannot be asked for this site (no coordinates, outside its regions, ...). */
	readonly problem?: string;
}

export interface IHazardOffers {
	readonly codeName: string;
	readonly coordinates?: { readonly latitude: number; readonly longitude: number };
	readonly providers: readonly IHazardOffer[];
	readonly manualNote: string;
	/** Alpha 9 C26: why a user or project pack's services are not offered (not trusted); '' otherwise. */
	readonly untrusted?: string;
}

/** `hazard/offers`'s answer; undefined for a refusal or no answer. */
export function readHazardOffers(raw: unknown): IHazardOffers | undefined {
	const answer = bag(raw);
	if (answer.ok !== true || !Array.isArray(answer.providers)) {
		return undefined;
	}
	const at = bag(answer.coordinates);
	return {
		codeName: text(answer.codeName),
		coordinates: typeof at.latitude === 'number' && typeof at.longitude === 'number' ? { latitude: at.latitude, longitude: at.longitude } : undefined,
		manualNote: text(answer.manualNote),
		untrusted: text(answer.untrusted) || undefined,
		providers: answer.providers.map(bag).filter(p => text(p.id)).map(p => ({
			id: text(p.id),
			service: text(p.service) || text(p.id),
			publisher: text(p.publisher),
			reference: text(p.reference),
			host: text(p.host),
			documentation: text(p.documentation),
			terms: text(p.terms),
			timeout: typeof p.timeout === 'number' && p.timeout > 0 ? p.timeout : 30,
			url: text(p.url) || undefined,
			query: p.query && typeof p.query === 'object' ? p.query as { [name: string]: string } : undefined,
			problem: text(p.problem) || undefined,
		})),
	};
}

export interface IHazardValue {
	/** The settings field (`site.spectral.sds`). */
	readonly target: string;
	readonly label: string;
	/** A number, or a spectrum's `(T, Sa)` points. */
	readonly value: number | readonly (readonly number[])[];
	readonly unit: string;
	readonly current: unknown;
}

/** A lookup the engineer chose to apply: the values and the record kept as `site.hazardSource`. */
export interface IHazardApplied {
	readonly values: readonly IHazardValue[];
	/** The `site.hazardSource` record (service, date, query, values), its `applied` the fields chosen. */
	readonly source: { readonly [key: string]: unknown };
}

function readLookup(raw: unknown): { readonly ok: true; readonly values: IHazardValue[]; readonly source: Bag } | { readonly ok: false; readonly error: string } {
	const answer = bag(raw);
	if (answer.ok !== true) {
		return { ok: false, error: text(answer.message) || localize('hazard.noAnswer', "The lookup gave no answer. Nothing was changed.") };
	}
	const values: IHazardValue[] = (Array.isArray(answer.values) ? answer.values : []).map(bag).filter(v => text(v.target) && (typeof v.value === 'number' || Array.isArray(v.value))).map(v => ({
		target: text(v.target),
		label: text(v.label) || text(v.target),
		value: v.value as IHazardValue['value'],
		unit: text(v.unit),
		current: v.current,
	}));
	return values.length ? { ok: true, values, source: bag(answer.source) } : { ok: false, error: localize('hazard.noValues', "The service gave no values. Nothing was changed.") };
}

function formatValue(value: unknown, unit: string): string {
	if (typeof value === 'number') {
		return `${Number(value.toPrecision(4))}${unit ? ' ' + unit : ''}`;
	}
	if (Array.isArray(value)) {
		return localize('hazard.spectrumPoints', "{0} points", value.length);
	}
	return localize('hazard.empty', "empty");
}

export interface IHazardLookupServices {
	readonly commands: ICommandService;
	readonly dialogs: IDialogService;
	readonly configuration: IConfigurationService;
	readonly progress: IProgressService;
}

export interface IHazardLookupRequest {
	/** The project settings as they are (unsaved edits included). */
	readonly settingsText: string;
	/** 1 Soil Report as it is: its site point gives the coordinates (and the site class). */
	readonly soilText?: string;
	readonly root?: string;
	/** Coordinates typed in the wizard (else the soil report's site point). */
	readonly latitude?: number;
	readonly longitude?: number;
}

/** Asks the backend for the pack's services (no network); undefined without the backend. */
export async function hazardOffers(commands: ICommandService, request: IHazardLookupRequest): Promise<IHazardOffers | undefined> {
	if (!CommandsRegistry.getCommand(HAZARD_OFFERS_COMMAND)) {
		return undefined;
	}
	try {
		return readHazardOffers(await commands.executeCommand<unknown>(HAZARD_OFFERS_COMMAND, request));
	} catch {
		return undefined;
	}
}

/**
 * The whole lookup: the setting, the choice of service, the consent to the exact request, the
 * call with its progress and timeout, then the values shown with Apply. Undefined: nothing to
 * apply (turned off, declined, offline, failed: the reason was shown; nothing changes).
 */
export async function lookUpHazardValues(services: IHazardLookupServices, request: IHazardLookupRequest): Promise<IHazardApplied | undefined> {
	const { commands, dialogs, configuration, progress } = services;
	const offers = await hazardOffers(commands, request);
	if (!offers) {
		await dialogs.error(localize('hazard.noBackend', "The hazard lookup needs SAEngine's Python backend, which did not answer."));
		return undefined;
	}
	if (!offers.providers.length) {
		await dialogs.info(
			localize('hazard.none', "Enter values by hand"),
			offers.untrusted || offers.manualNote || localize('hazard.noneDetail', "{0} names no online hazard service. Take the site's values from the code's maps or hazard tool and type them in Project Settings > Site.", offers.codeName),
		);
		return undefined;
	}
	if (configuration.getValue<boolean>(ALLOW_HAZARD_LOOKUP_SETTING) !== true) {
		const open = await dialogs.prompt<boolean>({
			type: 'info',
			message: localize('hazard.off', "Online hazard lookups are turned off"),
			detail: localize('hazard.offDetail', "Turn on the setting \"Allow online hazard lookups\" to look the site's values up by its coordinates. SAEngine then asks before every lookup; only the coordinates and the code parameters are sent. Or enter the values by hand."),
			buttons: [{ label: localize('hazard.openSettings', "&&Open Settings"), run: () => true }],
			cancelButton: { label: localize('hazard.offCancel', "Enter by Hand"), run: () => false },
		});
		if (open.result) {
			await commands.executeCommand('workbench.action.openSettings', ALLOW_HAZARD_LOOKUP_SETTING);
		}
		return undefined;
	}
	let offer = offers.providers[0];
	if (offers.providers.length > 1) {
		const chosen = await dialogs.prompt<IHazardOffer | undefined>({
			type: 'question',
			message: localize('hazard.choose', "Which service should give the site's values?"),
			buttons: offers.providers.map(p => ({ label: p.service.replace(/&/g, '&&'), run: () => p })),
			cancelButton: { label: localize('hazard.cancel', "Cancel"), run: () => undefined },
		});
		if (!chosen.result) {
			return undefined;
		}
		offer = chosen.result;
	}
	if (offer.problem || !offer.url) {
		await dialogs.info(localize('hazard.cannot', "{0} cannot be asked for this site", offer.service), offer.problem ?? '');
		return undefined;
	}
	const sent = Object.entries(offer.query ?? {}).map(([name, value]) => `${name} = ${value}`).join('\n');
	const { confirmed } = await dialogs.confirm({
		type: 'question',
		message: localize('hazard.consent', "Send the site's coordinates to {0}?", offer.service),
		detail: [
			localize('hazard.consentWho', "SAEngine will ask {0}{1} at {2} for the site's hazard values. Only these values are sent; no other project data:", offer.service, offer.publisher ? ` (${offer.publisher})` : '', offer.host),
			sent,
			offer.terms ? localize('hazard.consentTerms', "Terms of use: {0}", offer.terms) : '',
			localize('hazard.consentAfter', "The values are shown before anything is changed."),
		].filter(Boolean).join('\n\n'),
		primaryButton: localize('hazard.send', "&&Send Request"),
	});
	if (!confirmed) {
		return undefined;
	}
	let cancel: () => void = () => { };
	const cancelled = new Promise<undefined>(resolve => cancel = () => resolve(undefined));
	// The backend gives up after the provider's timeout; this only guards a silent backend.
	const limit = offer.timeout + 15;
	const timer = timeout(limit * 1000);
	let raw: unknown;
	try {
		raw = await progress.withProgress({
			location: ProgressLocation.Notification,
			title: localize('hazard.asking', "Asking {0} for the site's hazard values...", offer.service),
			cancellable: true,
		}, () => Promise.race([
			commands.executeCommand<unknown>(HAZARD_LOOKUP_COMMAND, { ...request, provider: offer.id, consent: true }),
			cancelled,
			timer.then(() => ({ ok: false, message: localize('hazard.timeout', "No answer within {0} s. Nothing was changed.", limit) }), () => undefined),
		]), () => cancel());
	} catch (error) {
		raw = { ok: false, message: toErrorMessage(error) };
	} finally {
		timer.cancel();
	}
	if (raw === undefined) {
		return undefined; // cancelled: whatever comes later is not applied
	}
	const answer = readLookup(raw);
	if (!answer.ok) {
		await dialogs.error(localize('hazard.failed', "The hazard values could not be looked up"), answer.error);
		return undefined;
	}
	const spectra = answer.values.some(v => SPECTRUM_TARGETS.has(v.target));
	const lines = answer.values.map(v => localize('hazard.valueLine', "{0}: {1} (now {2})", v.label, formatValue(v.value, v.unit), formatValue(v.current, v.unit)));
	const source = answer.source;
	const result = await dialogs.confirm({
		type: 'info',
		message: localize('hazard.apply', "Apply the values of {0}?", offer.service),
		detail: [
			lines.join('\n'),
			localize('hazard.applyNote', "Looked up {0} for {1}. The values go into Project Settings > Site and stay editable; the project keeps the service, date and query, and the report names them.", text(source.date), sent.replace(/\n/g, ', ')),
		].join('\n\n'),
		checkbox: spectra ? { label: localize('hazard.useSpectra', "Also use the multi-period spectra (response spectrum analysis)"), checked: true } : undefined,
		primaryButton: localize('hazard.applyButton', "&&Apply Values"),
	});
	if (!result.confirmed) {
		return undefined;
	}
	const chosen = answer.values.filter(v => !SPECTRUM_TARGETS.has(v.target) || result.checkboxChecked !== false);
	return { values: chosen, source: { ...source, applied: chosen.map(v => v.target) } };
}

type Json = { [key: string]: unknown };

/**
 * Puts the chosen values into their settings fields (creating `site.spectral` where needed) and
 * the record into `site.hazardSource`; the document is changed in place. A spectrum not chosen
 * that an earlier lookup applied is left as it is.
 */
export function applyHazardValues(document: Json, applied: IHazardApplied): void {
	for (const value of applied.values) {
		const path = value.target.split('.');
		const last = path.pop()!;
		let node: Json = document;
		for (const key of path) {
			const child = node[key];
			if (typeof child !== 'object' || child === null || Array.isArray(child)) {
				node[key] = {};
			}
			node = node[key] as Json;
		}
		node[last] = Array.isArray(value.value) ? value.value.map(point => [...point]) : value.value;
	}
	if (typeof document.site !== 'object' || document.site === null || Array.isArray(document.site)) {
		document.site = {};
	}
	(document.site as Json).hazardSource = applied.source;
}

/** The value of a settings field (`site.spectral.sds`) of a document. */
export function settingsValue(document: Json, target: string): unknown {
	let node: unknown = document;
	for (const key of target.split('.')) {
		node = typeof node === 'object' && node !== null && !Array.isArray(node) ? (node as Json)[key] : undefined;
	}
	return node;
}

function same(a: unknown, b: unknown): boolean {
	if (typeof a === 'number' && typeof b === 'number') {
		return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b));
	}
	if (Array.isArray(a) && Array.isArray(b)) {
		return a.length === b.length && a.every((x, i) => same(x, b[i]));
	}
	return a === b;
}

/**
 * The record of an earlier lookup (`site.hazardSource`), as Project Settings > Site shows it:
 * its line, and the fields whose values differ from the service's now (edited since).
 */
export function hazardSourceSummary(document: Json): { readonly line: string; readonly edited: readonly string[]; readonly restore?: IHazardApplied } | undefined {
	const site = bag(document.site);
	const record = bag(site.hazardSource);
	if (!text(record.service)) {
		return undefined;
	}
	const values = bag(record.values);
	const applied = Array.isArray(record.applied) ? record.applied.filter((t): t is string => typeof t === 'string' && values[t] !== undefined) : [];
	const edited = applied.filter(t => !same(settingsValue(document, t), values[t]));
	const query = Object.entries(bag(record.query)).map(([k, v]) => `${k}=${String(v)}`).join(', ');
	const line = localize('hazard.sourceLine', "from {0}, looked up {1} ({2})", text(record.service), text(record.date), query || text(record.url));
	const restore: IHazardApplied | undefined = edited.length ? {
		values: applied.map(t => ({ target: t, label: t, value: values[t] as IHazardValue['value'], unit: '', current: settingsValue(document, t) })),
		source: record,
	} : undefined;
	return { line, edited: edited.map(t => t.split('.').pop() ?? t), restore };
}
