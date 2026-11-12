/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { decodeBase64, encodeHex } from '../../../../base/common/buffer.js';

/**
 * The pure part of SAEngine's update check: which GitHub release is newer than the running
 * build, and whether a downloaded setup matches the release's .sha256 file. The workbench side
 * (saengineUpdate.contribution.ts) does the requests, the dialogs and the download.
 *
 * Release versions are `<x.y.z>-alpha.<N>` (scripts/ci/release.py); development builds are
 * `<x.y.z>-dev.<commits>[.local]` (scripts/build-installer.ps1). They compare as SemVer 2.0
 * versions: the core numerically, then the pre-release identifiers (a version without one is
 * newer than any with one), numeric identifiers numerically and below alphanumeric ones.
 */

/** A setup asset of a release: `SAEngine-x64-user-setup-<version>.exe`. */
export const SETUP_ASSET = /^SAEngine-x64-user-setup-([0-9A-Za-z.\-]+)\.exe$/;

/**
 * The running SAEngine version: product.json's `saengineVersion`, which build-installer.ps1 stamps
 * into the packaged app, else (a build from sources) Code - OSS's `version` from package.json.
 */
export function runningVersion(product: { readonly version: string; readonly saengineVersion?: string }): string {
	return product.saengineVersion || product.version;
}

export interface IParsedVersion {
	readonly core: readonly [number, number, number];
	readonly prerelease: readonly (number | string)[];
}

export function parseVersion(version: string): IParsedVersion | undefined {
	const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?(?:\+[0-9A-Za-z.\-]+)?$/.exec(version.trim());
	if (!match) {
		return undefined;
	}
	const prerelease = match[4] ? match[4].split('.') : [];
	if (prerelease.some(identifier => identifier === '')) {
		return undefined;
	}
	return {
		core: [Number(match[1]), Number(match[2]), Number(match[3])],
		prerelease: prerelease.map(identifier => /^\d+$/.test(identifier) ? Number(identifier) : identifier),
	};
}

/** Negative when `a` is older than `b`, 0 when equal, positive when newer; undefined when either does not parse. */
export function compareVersions(a: string, b: string): number | undefined {
	const left = parseVersion(a);
	const right = parseVersion(b);
	if (!left || !right) {
		return undefined;
	}
	for (let i = 0; i < 3; i++) {
		if (left.core[i] !== right.core[i]) {
			return left.core[i] - right.core[i];
		}
	}
	if (left.prerelease.length === 0 || right.prerelease.length === 0) {
		return right.prerelease.length - left.prerelease.length;
	}
	const length = Math.min(left.prerelease.length, right.prerelease.length);
	for (let i = 0; i < length; i++) {
		const x = left.prerelease[i];
		const y = right.prerelease[i];
		if (x === y) {
			continue;
		}
		if (typeof x === 'number' && typeof y === 'number') {
			return x - y;
		}
		if (typeof x === 'number') {
			return -1;
		}
		if (typeof y === 'number') {
			return 1;
		}
		return x < y ? -1 : 1;
	}
	return left.prerelease.length - right.prerelease.length;
}

/** The fields of a GitHub release (GET /repos/<owner>/<repo>/releases) the check reads. */
export interface IGitHubRelease {
	readonly tag_name: string;
	readonly name?: string | null;
	readonly body?: string | null;
	readonly html_url: string;
	readonly draft?: boolean;
	readonly prerelease?: boolean;
	readonly published_at?: string | null;
	readonly assets?: readonly { readonly name: string; readonly browser_download_url: string; readonly size?: number }[];
}

export interface IAvailableUpdate {
	readonly version: string;
	readonly tag: string;
	readonly title: string;
	readonly notes: string;
	readonly releaseUrl: string;
	readonly setupName: string;
	readonly setupUrl: string;
	readonly setupSize: number | undefined;
	/** The release's `<setup>.sha256` file; a release without one is never offered. */
	readonly sha256Url: string;
}

/**
 * The newest published release (pre-releases included, drafts never) with a setup and its
 * .sha256 file whose version is newer than `current`; undefined when there is none or when
 * `current` does not parse.
 */
export function pickUpdate(releases: readonly IGitHubRelease[], current: string): IAvailableUpdate | undefined {
	if (!parseVersion(current)) {
		return undefined;
	}
	let best: IAvailableUpdate | undefined;
	for (const release of releases) {
		if (release.draft) {
			continue;
		}
		for (const asset of release.assets ?? []) {
			const match = SETUP_ASSET.exec(asset.name);
			if (!match) {
				continue;
			}
			const version = match[1];
			const checksum = release.assets?.find(other => other.name === `${asset.name}.sha256`);
			// A version that does not parse compares as 0: never offered.
			if (!checksum || (compareVersions(version, current) ?? 0) <= 0) {
				continue;
			}
			if (best && (compareVersions(version, best.version) ?? 0) <= 0) {
				continue;
			}
			best = {
				version,
				tag: release.tag_name,
				title: release.name || release.tag_name,
				notes: release.body ?? '',
				releaseUrl: release.html_url,
				setupName: asset.name,
				setupUrl: asset.browser_download_url,
				setupSize: asset.size,
				sha256Url: checksum.browser_download_url,
			};
		}
	}
	return best;
}

/**
 * The lower-case hex SHA-256 from a `.sha256` file as build-installer.ps1 writes it
 * (`<hash> *<file name>`; sha256sum's text mode `<hash>  <file name>` and a bare hash are
 * accepted too). Undefined when the file holds no hash or names another file.
 */
export function parseSha256File(text: string, fileName: string): string | undefined {
	for (const line of text.split(/\r?\n/)) {
		const match = /^\s*([0-9A-Fa-f]{64})(?:\s+\*?(.+?))?\s*$/.exec(line);
		if (!match) {
			continue;
		}
		if (match[2] !== undefined && match[2] !== fileName) {
			return undefined;
		}
		return match[1].toLowerCase();
	}
	return undefined;
}

/**
 * Whether a checksum from Code - OSS's IChecksumService (SHA-256, base64 without padding)
 * equals the expected lower-case hex hash.
 */
export function checksumMatches(expectedHex: string, actualBase64: string): boolean {
	if (!/^[0-9a-f]{64}$/.test(expectedHex)) {
		return false;
	}
	try {
		return encodeHex(decodeBase64(actualBase64)) === expectedHex;
	} catch {
		return false;
	}
}
