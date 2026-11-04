/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { CommandsRegistry, ICommandService } from '../../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../../platform/configuration/common/configuration.js';
import { IConfirmation, IConfirmationResult, IDialogService } from '../../../../../platform/dialogs/common/dialogs.js';
import { IProgressService } from '../../../../../platform/progress/common/progress.js';
import { ALLOW_HAZARD_LOOKUP_SETTING, applyHazardValues, HAZARD_LOOKUP_COMMAND, HAZARD_OFFERS_COMMAND, hazardSourceSummary, IHazardLookupServices, lookUpHazardValues, readHazardOffers } from '../../browser/hazardLookup.js';

/*
 * Alpha 9 C22: the online hazard lookup's UI side, with the backend and the dialogs stubbed (no
 * network: the backend's `hazard/lookup` is a stub that records what it was asked).
 */

const OFFERS = {
	ok: true,
	codePack: 'aci318-asce7-22',
	codeName: 'ASCE 7-22',
	coordinates: { latitude: 34.0522, longitude: -118.2437 },
	providers: [{
		id: 'usgs-asce7-22',
		service: 'USGS Seismic Design Web Services (ASCE 7-22)',
		publisher: 'U.S. Geological Survey',
		host: 'earthquake.usgs.gov',
		timeout: 30,
		url: 'https://earthquake.usgs.gov/ws/designmaps/asce7-22.json?latitude=34.0522&longitude=-118.2437&riskCategory=II&siteClass=D&title=SAEngine',
		query: { latitude: '34.0522', longitude: '-118.2437', riskCategory: 'II', siteClass: 'D', title: 'SAEngine' },
	}],
	manualNote: '',
};

const SOURCE = {
	provider: 'usgs-asce7-22',
	service: 'USGS Seismic Design Web Services (ASCE 7-22)',
	date: '2026-11-05T08:30:00Z',
	query: OFFERS.providers[0].query,
	values: { 'site.spectral.sds': 1.36, 'site.spectral.sd1': 0.82, 'site.spectral.designSpectrum': [[0, 0.55], [0.2, 1.36]] },
	applied: ['site.spectral.sds', 'site.spectral.sd1', 'site.spectral.designSpectrum'],
};

const LOOKUP = {
	ok: true,
	values: [
		{ target: 'site.spectral.sds', label: 'SDS', value: 1.36, unit: 'g', current: null },
		{ target: 'site.spectral.sd1', label: 'SD1', value: 0.82, unit: 'g', current: null },
		{ target: 'site.spectral.designSpectrum', label: 'Multi-period design spectrum', value: [[0, 0.55], [0.2, 1.36]], unit: 'g', current: null },
	],
	source: SOURCE,
};

interface IStubs {
	readonly services: IHazardLookupServices;
	readonly calls: { id: string; args: unknown }[];
	readonly confirmations: IConfirmation[];
}

function stubs(options: { allowed: boolean; consent: boolean; apply: boolean; spectra?: boolean }): IStubs {
	const calls: { id: string; args: unknown }[] = [];
	const confirmations: IConfirmation[] = [];
	let confirmCount = 0;
	const commands = {
		executeCommand: async (id: string, args: unknown) => {
			calls.push({ id, args });
			return id === HAZARD_OFFERS_COMMAND ? OFFERS : id === HAZARD_LOOKUP_COMMAND ? LOOKUP : undefined;
		},
	} as unknown as ICommandService;
	const dialogs = {
		confirm: async (confirmation: IConfirmation): Promise<IConfirmationResult> => {
			confirmations.push(confirmation);
			const first = confirmCount++ === 0;
			return { confirmed: first ? options.consent : options.apply, checkboxChecked: options.spectra ?? true };
		},
		prompt: async () => ({ result: false }),
		info: async () => undefined,
		error: async () => undefined,
	} as unknown as IDialogService;
	const configuration = { getValue: (key: string) => key === ALLOW_HAZARD_LOOKUP_SETTING ? options.allowed : undefined } as unknown as IConfigurationService;
	const progress = { withProgress: (_options: unknown, task: () => Promise<unknown>) => task() } as unknown as IProgressService;
	return { services: { commands, dialogs, configuration, progress }, calls, confirmations };
}

suite('SAEngine - Hazard lookup by site coordinates (C22)', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	setup(() => {
		// The backend's command exists (the desktop contribution registers it).
		store.add(CommandsRegistry.registerCommand(HAZARD_OFFERS_COMMAND, () => OFFERS));
	});

	test('reads the offers: the service, its host and the exact query', () => {
		const offers = readHazardOffers(OFFERS);
		assert.strictEqual(offers?.providers[0].host, 'earthquake.usgs.gov');
		assert.strictEqual(offers?.providers[0].query?.siteClass, 'D');
		assert.strictEqual(readHazardOffers({ ok: false, message: 'no' }), undefined);
	});

	test('with the setting off nothing is sent', async () => {
		const { services, calls } = stubs({ allowed: false, consent: true, apply: true });
		assert.strictEqual(await lookUpHazardValues(services, { settingsText: '{}' }), undefined);
		assert.ok(!calls.some(c => c.id === HAZARD_LOOKUP_COMMAND));
	});

	test('declining the consent sends nothing', async () => {
		const { services, calls, confirmations } = stubs({ allowed: true, consent: false, apply: true });
		assert.strictEqual(await lookUpHazardValues(services, { settingsText: '{}' }), undefined);
		assert.ok(!calls.some(c => c.id === HAZARD_LOOKUP_COMMAND));
		// The consent names the service, the host and every value that would be sent.
		const detail = String(confirmations[0].detail);
		assert.ok(confirmations[0].message.includes('USGS'));
		assert.ok(detail.includes('earthquake.usgs.gov') && detail.includes('latitude = 34.0522') && detail.includes('siteClass = D'));
	});

	test('a confirmed lookup shows the values and applies the chosen ones with the record', async () => {
		const { services, calls } = stubs({ allowed: true, consent: true, apply: true, spectra: false });
		const applied = await lookUpHazardValues(services, { settingsText: '{}', latitude: 34.0522, longitude: -118.2437 });
		const lookup = calls.find(c => c.id === HAZARD_LOOKUP_COMMAND)?.args as { consent?: boolean; provider?: string };
		assert.deepStrictEqual([lookup.consent, lookup.provider], [true, 'usgs-asce7-22']);
		// The spectra were not chosen (the checkbox off): only SDS and SD1 apply.
		assert.deepStrictEqual(applied?.values.map(v => v.target), ['site.spectral.sds', 'site.spectral.sd1']);
		const document: { [key: string]: unknown } = { site: { location: 'custom' } };
		applyHazardValues(document, applied!);
		const site = document.site as { spectral: { sds: number; designSpectrum?: unknown }; hazardSource: { applied: string[] } };
		assert.strictEqual(site.spectral.sds, 1.36);
		assert.strictEqual(site.spectral.designSpectrum, undefined);
		assert.deepStrictEqual(site.hazardSource.applied, ['site.spectral.sds', 'site.spectral.sd1']);
	});

	test('not applied when the engineer cancels the values', async () => {
		const { services } = stubs({ allowed: true, consent: true, apply: false });
		assert.strictEqual(await lookUpHazardValues(services, { settingsText: '{}' }), undefined);
	});

	test('the record names the source and the values edited since, and restores them', () => {
		const document: { [key: string]: unknown } = { site: { spectral: { sds: 1.36, sd1: 0.9, designSpectrum: [[0, 0.55], [0.2, 1.36]] }, hazardSource: SOURCE } };
		const summary = hazardSourceSummary(document);
		assert.ok(summary?.line.includes('USGS') && summary.line.includes('2026-11-05T08:30:00Z'));
		assert.deepStrictEqual(summary?.edited, ['sd1']);
		applyHazardValues(document, summary!.restore!);
		assert.strictEqual((document.site as { spectral: { sd1: number } }).spectral.sd1, 0.82);
		assert.strictEqual(hazardSourceSummary({ site: {} }), undefined);
	});
});
