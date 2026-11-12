/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { decodeHex, encodeBase64 } from '../../../../../base/common/buffer.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { checksumMatches, compareVersions, IGitHubRelease, parseSha256File, parseVersion, pickUpdate } from '../../common/updateCheck.js';

const HASH = '0cd876d0e3fbfcdcdb85e5019080aca243908f4ad5c3b3c93a55ee9ba154f95b';

function release(tag: string, version: string, options: { draft?: boolean; checksum?: boolean } = {}): IGitHubRelease {
	const setup = `SAEngine-x64-user-setup-${version}.exe`;
	const base = `https://github.com/o/r/releases/download/${tag}`;
	const assets = [
		{ name: setup, browser_download_url: `${base}/${setup}`, size: 400 },
		{ name: `SAEngine-${version}-third-party-sources.zip`, browser_download_url: `${base}/sources.zip` },
	];
	if (options.checksum !== false) {
		assets.push({ name: `${setup}.sha256`, browser_download_url: `${base}/${setup}.sha256` });
	}
	return { tag_name: tag, name: `Pre Alpha Version ${tag.slice(11)}`, body: 'notes', html_url: `https://github.com/o/r/releases/tag/${tag}`, draft: options.draft, prerelease: true, assets };
}

suite('SAEngine - update check', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('parses release and development versions', () => {
		assert.deepStrictEqual(parseVersion('0.0.42-alpha.5'), { core: [0, 0, 42], prerelease: ['alpha', 5] });
		assert.deepStrictEqual(parseVersion('v1.2.3'), { core: [1, 2, 3], prerelease: [] });
		assert.deepStrictEqual(parseVersion('0.0.43-dev.3.local'), { core: [0, 0, 43], prerelease: ['dev', 3, 'local'] });
		assert.deepStrictEqual(parseVersion('1.2.3+build.7'), { core: [1, 2, 3], prerelease: [] });
		for (const bad of ['', '1.2', '1.2.x', '1.2.3-', '1.2.3-a..b', 'Pre-Alpha-v5']) {
			assert.strictEqual(parseVersion(bad), undefined, bad);
		}
	});

	test('compares versions as SemVer', () => {
		const ordered = ['0.0.9', '0.0.42-alpha.5', '0.0.42-alpha.10', '0.0.42-dev.1', '0.0.42', '0.0.43-alpha.1', '0.1.0', '1.0.0'];
		for (let i = 0; i < ordered.length; i++) {
			for (let j = 0; j < ordered.length; j++) {
				const result = compareVersions(ordered[i], ordered[j])!;
				assert.strictEqual(Math.sign(result), Math.sign(i - j), `${ordered[i]} vs ${ordered[j]}`);
			}
		}
		assert.ok(compareVersions('1.0.0-alpha', '1.0.0-alpha.1')! < 0);
		assert.ok(compareVersions('1.0.0-1', '1.0.0-alpha')! < 0, 'numeric identifiers sort below alphanumeric ones');
		assert.strictEqual(compareVersions('1.0.0+a', '1.0.0+b'), 0, 'build metadata is ignored');
		assert.strictEqual(compareVersions('1.0.0', 'nonsense'), undefined);
	});

	test('offers the newest published release with a setup and its checksum', () => {
		const releases = [
			release('Pre-Alpha-v7', '0.0.44-alpha.7', { draft: true }),
			release('Pre-Alpha-v6', '0.0.43-alpha.6', { checksum: false }),
			release('Pre-Alpha-v5', '0.0.42-alpha.5'),
			release('Pre-Alpha-v4', '0.0.41-alpha.4'),
		];
		const update = pickUpdate(releases, '0.0.41-alpha.4');
		assert.strictEqual(update?.version, '0.0.42-alpha.5', 'drafts and releases without a .sha256 are skipped');
		assert.strictEqual(update.tag, 'Pre-Alpha-v5');
		assert.strictEqual(update.title, 'Pre Alpha Version 5');
		assert.strictEqual(update.setupName, 'SAEngine-x64-user-setup-0.0.42-alpha.5.exe');
		assert.strictEqual(update.sha256Url, 'https://github.com/o/r/releases/download/Pre-Alpha-v5/SAEngine-x64-user-setup-0.0.42-alpha.5.exe.sha256');
		assert.strictEqual(update.setupSize, 400);

		assert.strictEqual(pickUpdate(releases, '0.0.42-alpha.5'), undefined, 'the same version is not an update');
		assert.strictEqual(pickUpdate(releases, '0.0.43-dev.2'), undefined, 'a newer development build is not offered an older release');
		assert.strictEqual(pickUpdate(releases, 'unknown'), undefined);
		assert.strictEqual(pickUpdate([], '0.0.1')?.version, undefined);
		// Not in API order: the newest version wins, not the first listed.
		assert.strictEqual(pickUpdate([releases[3], releases[2]], '0.0.1')?.version, '0.0.42-alpha.5');
	});

	test('reads the .sha256 file of the setup', () => {
		const name = 'SAEngine-x64-user-setup-0.0.42-alpha.5.exe';
		assert.strictEqual(parseSha256File(`${HASH} *${name}\r\n`, name), HASH);
		assert.strictEqual(parseSha256File(`${HASH.toUpperCase()}  ${name}\n`, name), HASH);
		assert.strictEqual(parseSha256File(`${HASH}\n`, name), HASH);
		assert.strictEqual(parseSha256File(`${HASH} *other.exe`, name), undefined, 'a hash of another file');
		assert.strictEqual(parseSha256File('not a hash', name), undefined);
		assert.strictEqual(parseSha256File(HASH.slice(1), name), undefined);
	});

	test('compares a downloaded file\'s checksum with the expected hash', () => {
		const base64 = encodeBase64(decodeHex(HASH), false);
		assert.ok(checksumMatches(HASH, base64));
		assert.ok(checksumMatches(HASH, encodeBase64(decodeHex(HASH))), 'padding does not matter');
		const other = HASH.replace(/^0/, '1');
		assert.ok(!checksumMatches(other, base64));
		assert.ok(!checksumMatches(HASH.toUpperCase(), base64), 'the expected hash is normalised by parseSha256File');
		assert.ok(!checksumMatches(HASH, ''));
	});
});
