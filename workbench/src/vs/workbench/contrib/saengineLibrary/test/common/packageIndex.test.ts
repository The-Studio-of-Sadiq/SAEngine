/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { packageUrlProblem, safeFileName } from '../../../../../platform/saengine/common/packages.js';
import { acceptedIndexKeys, missingRequirements, needsNewerSaengine, newestPackages, packageUpdates, readPackageIndex, TEST_INDEX_KEY, versionSatisfies } from '../../common/packageIndex.js';

const SHA = 'a'.repeat(64);

function entry(id: string, version: string, extra: object = {}): object {
	return { id, kind: 'designCode', name: id.toUpperCase(), version, licence: 'CC-BY-4.0', url: `https://github.com/o/r/releases/download/t/${id}-${version}.zip`, size: 1000, sha256: SHA, hooks: false, ...extra };
}

const INDEX = JSON.stringify({
	schema: 'saengine.packageIndex/1',
	generated: '2026-11-01T00:00:00Z',
	packages: [
		entry('bd-coastal-wind', '1.0.0', { requires: { saengine: '>=0.0.40', packages: { bnbc2020: '>=1.0.0' } } }),
		entry('bd-coastal-wind', '1.1.0', { requires: { saengine: '>=0.0.40' } }),
		entry('bd-coastal-wind', '2.0.0', { requires: { saengine: '>=9.0.0' } }),
		entry('warren', '1.0.0', { kind: 'structureTemplate' }),
		entry('no-hash', '1.0.0', { sha256: 'nope' }),
		entry('http', '1.0.0', { url: 'http://example.com/x.zip' }),
		{ id: 'Bad Id', version: '1' },
	],
});

suite('SAEngine - Package index', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the index and leaves out entries that are not pinned', () => {
		const index = readPackageIndex(INDEX);
		assert.deepStrictEqual(index.packages.map(p => `${p.id}@${p.version}`), ['bd-coastal-wind@1.0.0', 'bd-coastal-wind@1.1.0', 'bd-coastal-wind@2.0.0', 'warren@1.0.0']);
		assert.strictEqual(index.problems.length, 3);
		assert.strictEqual(readPackageIndex('{').packages.length, 0);
		assert.strictEqual(readPackageIndex('{"schema":"other"}').problems.length, 1);
	});

	test('picks the newest version this SAEngine understands', () => {
		const newest = newestPackages(readPackageIndex(INDEX), '0.0.50-alpha.7');
		assert.deepStrictEqual(newest.map(p => `${p.id}@${p.version}`), ['bd-coastal-wind@1.1.0', 'warren@1.0.0']);
		const only = newestPackages(readPackageIndex(INDEX), '0.0.30');
		assert.strictEqual(only.find(p => p.id === 'bd-coastal-wind')?.version, '2.0.0');
		assert.ok(needsNewerSaengine(only[0], '0.0.30'));
	});

	test('version ranges', () => {
		assert.ok(versionSatisfies('0.0.50', '>=0.0.50'));
		assert.ok(!versionSatisfies('0.0.49', '>=0.0.50'));
		assert.ok(versionSatisfies('1.2', '>=1.0,<2'));
		assert.ok(!versionSatisfies('2.0.0', '>=1.0,<2'));
		assert.ok(versionSatisfies('1.0.0', ''));
		assert.ok(versionSatisfies('1.0.0', '==1.0.0'));
		assert.ok(!versionSatisfies('1.0.0', 'garbage'));
	});

	test('updates: user and project packages only, newer versions only', () => {
		const newest = newestPackages(readPackageIndex(INDEX), '0.0.50');
		const updates = packageUpdates([
			{ id: 'bd-coastal-wind', kind: 'designCode', version: '1.0.0', scope: 'project' },
			{ id: 'warren', kind: 'structureTemplate', version: '1.0.0', scope: 'user' },
			{ id: 'bd-coastal-wind', kind: 'designCode', version: '0.1.0', scope: 'builtin' },
		], newest, '0.0.50');
		assert.deepStrictEqual(updates.map(u => `${u.installed.scope}:${u.installed.id} ${u.installed.version}->${u.available.version}`), ['project:bd-coastal-wind 1.0.0->1.1.0']);
	});

	test('required packages', () => {
		const index = readPackageIndex(INDEX);
		const pkg = index.packages[0];
		assert.deepStrictEqual(missingRequirements(pkg, [], newestPackages(index, '0.0.50')).map(m => m.id), ['bnbc2020']);
		assert.deepStrictEqual(missingRequirements(pkg, [{ id: 'bnbc2020', kind: 'designCode', version: '1.0.0', scope: 'builtin' }], []), []);
	});

	test('keys: release builds never accept the TEST key', () => {
		assert.ok(!acceptedIndexKeys(true).some(k => k.test));
		assert.ok(acceptedIndexKeys(false).includes(TEST_INDEX_KEY));
	});

	test('downloads: HTTPS on GitHub only, safe file names', () => {
		assert.strictEqual(packageUrlProblem('https://github.com/o/r/releases/download/t/a.zip'), undefined);
		assert.ok(packageUrlProblem('http://github.com/a.zip'));
		assert.ok(packageUrlProblem('https://example.com/a.zip'));
		assert.strictEqual(safeFileName('..\\..\\evil.zip'), 'evil.zip');
		assert.strictEqual(safeFileName('a b.exe'), 'a_b.exe.zip');
	});
});
