/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { changePackWarning, chosenPackId, groupPacks, packIdProblem, packLabel, packOptionBlock, packOptions, readCodePack, readCodePacks, readProblems, shadowedLabel } from '../../browser/codePacksModel.js';
import { settingsSections } from '../../browser/settingsEditor.js';

/** Stand-in answers of `saengine.codes.list` (the backend's PackInfo), in the shapes it may take. */
const LIST = [
	{ id: 'bnbc2020', name: 'BNBC 2020', edition: 'BNBC 2020', country: 'Bangladesh', scope: 'builtin', covers: ['locations', 'loads', 'combinations'], problems: [], path: 'C:/app/packs/bnbc2020' },
	{ info: { id: 'example-region', name: 'Example Region', edition: '2024', extends: 'bnbc2020', covers: { locations: true, windSeismic: true }, hooks: 'hooks.py' }, scope: 'user', problems: [{ severity: 'warning', message: 'windSpeeds: town "Eastport" has no zone' }], trusted: false },
	{ id: 'site-x', name: 'Site X', extends: 'example-region', origin: 'project', covers: ['combinations'], trusted: true, hooks: { design: 'x.py' } },
	{ name: 'no id' },
	{ id: 'bnbc2020', name: 'BNBC 2020', scope: 'builtin' },
];

suite('SAEngine - Code packs', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the backend list tolerantly and groups it Built-in / Your Packs / This Project', () => {
		const packs = readCodePacks({ packs: LIST });
		assert.deepStrictEqual(groupPacks(packs, true).map(g => ({
			title: g.title,
			packs: g.packs.map(p => `${packLabel(p)} | extends ${p.extends ?? '-'} | ${p.covers.join(',')} | ${p.problems.length} problems | hooks ${p.trust}`),
			empty: g.packs.length ? undefined : g.empty,
		})), [
			{ title: 'Built-in', packs: ['BNBC 2020 (built-in) | extends - | locations,loads,combinations | 0 problems | hooks none'], empty: undefined },
			{ title: 'Your Packs', packs: ['Example Region (your pack) | extends bnbc2020 | locations,windSeismic | 1 problems | hooks untrusted'], empty: undefined },
			{ title: 'This Project', packs: ['Site X (this project) | extends example-region | combinations | 0 problems | hooks trusted'], empty: undefined },
		]);
		assert.deepStrictEqual(groupPacks([], false).map(g => g.title), ['Built-in', 'Your Packs']);
	});

	test('the design code selector: the default, every pack once, and a pack that is not installed', () => {
		const packs = readCodePacks(LIST);
		assert.deepStrictEqual({
			standIn: packOptions([], chosenPackId(undefined)).map(o => o.label),
			oldFile: chosenPackId({ schema: 'saengine.projectSettings/1' }),
			installed: packOptions(packs, 'example-region').map(o => `${o.label}: ${o.description}`),
			missing: packOptions(packs, 'nbc-nepal').filter(o => o.missing).map(o => o.label),
		}, {
			standIn: ['BNBC 2020 (built-in)'],
			oldFile: 'bnbc2020',
			installed: [
				'BNBC 2020 (built-in): Bangladesh · provides Locations, Area loads, Combinations',
				'Example Region (your pack): 2024 · Extends BNBC 2020 · provides Locations, Wind and seismic',
				'Site X (this project): Extends Example Region · provides Combinations',
			],
			missing: ['nbc-nepal (not installed)'],
		});
	});

	test('the real PackInfo of the backend: hooks, unusable packs and shadowed packs', () => {
		// The shape of python/src/saengine/codes/manifest.py PackInfo (model_dump), invented packs.
		const base = { country: null, region: null, version: '1.0.0', tables: ['locations'], shadows: [], hooksFrom: [], untrustedHooks: [], usable: true, problems: [], effective: true, shadowedBy: null, hooks: false, trusted: null };
		const real = readCodePacks([
			{ ...base, id: 'bnbc2020', name: 'BNBC 2020', edition: 'BNBC 2020', extends: null, covers: ['locations'], chain: ['bnbc2020'], scope: 'builtin', path: 'C:/app/bnbc2020' },
			{ ...base, id: 'hooked', name: 'Hooked', edition: '2024', extends: 'bnbc2020', covers: [], chain: ['hooked', 'bnbc2020'], scope: 'user', path: 'C:/u/hooked', hooks: true, trusted: false, hooksFrom: ['hooked'], untrustedHooks: ['hooked'] },
			{ ...base, id: 'child', name: 'Child', edition: '2024', extends: 'hooked', covers: [], chain: ['child', 'hooked', 'bnbc2020'], scope: 'user', path: 'C:/u/child', hooks: true, trusted: true, hooksFrom: ['hooked'] },
			{ ...base, id: 'broken', name: 'Broken', edition: '1', extends: 'bnbc2020', covers: [], chain: ['broken'], scope: 'user', path: 'C:/u/broken', usable: false, problems: [{ severity: 'error', message: 'combinations: field required', file: 'data/combinations.json', table: 'combinations' }] },
			{ ...base, id: 'site', name: 'Site (yours)', edition: '1', extends: 'bnbc2020', covers: [], chain: ['site', 'bnbc2020'], scope: 'user', path: 'C:/u/site', effective: false, shadowedBy: 'project' },
			{ ...base, id: 'site', name: 'Site (project)', edition: '1', extends: 'bnbc2020', covers: [], chain: ['site', 'bnbc2020'], scope: 'project', path: 'P:/site', shadows: ['user'] },
		]);
		const options = packOptions(real, 'bnbc2020');
		assert.deepStrictEqual({
			packs: real.map(p => `${p.id}/${p.scope}: hooks ${p.trust}, usable ${p.usable}, ${shadowedLabel(p) ?? 'in force'}`),
			options: options.map(o => `${o.label}${o.unusable ? ' [disabled]' : ''}`),
			blocked: options.map(o => packOptionBlock(o)?.message ?? 'ok'),
		}, {
			packs: [
				'bnbc2020/builtin: hooks none, usable true, in force',
				'hooked/user: hooks untrusted, usable true, in force',
				'child/user: hooks trusted, usable true, in force',
				'broken/user: hooks none, usable false, in force',
				'site/user: hooks none, usable true, Not in force: the pack with the same id in this project is used instead',
				'site/project: hooks none, usable true, in force',
			],
			options: ['BNBC 2020 (built-in)', 'Broken (your pack) (has errors) [disabled]', 'Child (your pack)', 'Hooked (your pack)', 'Site (project) (this project)'],
			blocked: ['ok', 'Broken (your pack) (has errors) cannot be used as the design code yet.', 'ok', 'ok', 'ok'],
		});
	});

	test('switching packs warns that the design results change', () => {
		const warning = changePackWarning('BNBC 2020 (built-in)', packOptions(readCodePacks(LIST), 'bnbc2020')[1]);
		assert.deepStrictEqual([warning.message, /design results will change/.test(warning.detail), /Run All/.test(warning.detail)], ['Use Example Region (your pack) as the design code of this project?', true, true]);
	});

	test('details, validation answers and new pack ids', () => {
		const shown = readCodePack({
			id: 'example-region', name: 'Example Region', author: 'SAEngine contributors', license: 'AGPL-3.0-only',
			sources: { locations: [{ clause: 'Invented towns for the example', page: 1 }], combinations: ['Example code 2.7'] },
			tables: { locations: 'example-region', combinations: 'bnbc2020' },
		});
		assert.deepStrictEqual({
			sources: shown?.sources,
			tables: shown?.tables,
			licence: shown?.licence,
			problems: [readProblems(['a', { message: 'b' }]), readProblems({ problems: [{ message: 'c' }] }), readProblems(undefined)],
			ids: ['', 'Nepal 2020', 'nbc-nepal-2020', 'bnbc2020'].map(id => packIdProblem(id, ['bnbc2020']) ?? 'ok'),
		}, {
			sources: [
				{ table: 'locations', text: 'Invented towns for the example, p. 1' },
				{ table: 'combinations', text: 'Example code 2.7' },
			],
			tables: [{ name: 'locations', from: 'example-region' }, { name: 'combinations', from: 'bnbc2020' }],
			licence: 'AGPL-3.0-only',
			problems: [['a', 'b'], ['c'], []],
			ids: [
				'Give the pack an id, such as nbc-nepal-2020.',
				'Use 2 to 64 lowercase letters, digits, dots, hyphens or underscores, starting with a letter or digit.',
				'ok',
				'A pack with the id bnbc2020 is already installed.',
			],
		});
	});

	test('the settings form leaves the design code to the toolbar selector', () => {
		const sections = settingsSections({ type: 'object', properties: { codePack: { type: 'string', title: 'Code pack' }, site: { type: 'object', title: 'Site' } } });
		assert.deepStrictEqual(sections.map(s => s.id), ['site']);
	});
});
