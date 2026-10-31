/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IPackageIndexKey } from '../../../../platform/saengine/common/packages.js';
import { compareVersions } from '../../saengineUpdate/common/updateCheck.js';

/*
 * The package index as the Packages page reads it (docs/marketplace-plan.md §3, round M3):
 * `index.json` (`saengine.packageIndex/1`) of the saengine-index repository's latest release, one
 * entry per package version the app may install, each pinned by the size and SHA-256 of its zip.
 * The main process fetches it and checks its Ed25519 signature (platform/saengine/common/packages.ts);
 * this module only reads the verified text, picks what Browse and Updates show, and holds the
 * keys the app accepts.
 */

/** `{ refresh?: boolean }` -> `IPackageIndexState`: the last verified index (fetched when asked or stale). Desktop only. */
export const PACKAGES_INDEX_COMMAND = 'saengine.packages.index';
/** `IPackageDownload` -> the path of the verified zip in a temporary folder. Desktop only. */
export const PACKAGES_DOWNLOAD_COMMAND = 'saengine.packages.download';
/** `{ path }`: deletes a zip the download command returned, after the install. Desktop only. */
export const PACKAGES_DISCARD_COMMAND = 'saengine.packages.discard';
/** `{ tab?, kind? }`: opens the Packages page. */
export const PACKAGES_SHOW_COMMAND = 'saengine.packages.show';
/** `{ id, scope, kind, root? }` -> `{ ok, path }`: removes a user or project package (backend). */
export const CODES_REMOVE_COMMAND = 'saengine.codes.remove';

/** Setting: fetch the index when the Packages page opens and once a day in the background. */
export const CHECK_ONLINE_SETTING = 'saengine.packages.checkOnline';
/** Setting: where the index is read (the index repository's latest release). */
export const INDEX_URL_SETTING = 'saengine.packages.indexUrl';

/** The index of the official packages: the newest release of the index repository. */
export const DEFAULT_INDEX_URL = 'https://github.com/The-Studio-of-Sadiq/saengine-index/releases/latest/download/index.json';

export type PackageKind = 'designCode' | 'structureTemplate' | 'buildingTemplate';
export const PACKAGE_KINDS: readonly PackageKind[] = ['designCode', 'structureTemplate', 'buildingTemplate'];

/**
 * The TEST key of the index repository (keys/TEST-KEY-not-trusted-by-release-builds.pub.pem): its
 * private half is derived from a published seed, so it proves nothing about who signed. Only
 * development builds accept it.
 */
export const TEST_INDEX_KEY: IPackageIndexKey = {
	keyId: '82af6b8cd5077d21',
	publicKey: '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAnh862XvPC3UeuOZnxRhTtcj+lm1lq0DnPriljmpYVa8=\n-----END PUBLIC KEY-----\n',
	test: true,
};

/**
 * The owner's index keys (decision D3): release builds accept only these. Empty until the owner
 * creates the key pair offline and commits its public half here and in the index repository
 * (keys/index-public.pem); until then a release build shows Browse as "not signed yet".
 */
export const OWNER_INDEX_KEYS: readonly IPackageIndexKey[] = [];

/** The keys this build accepts: the owner's, plus the TEST key in a development build. */
export function acceptedIndexKeys(isBuilt: boolean): IPackageIndexKey[] {
	return isBuilt ? [...OWNER_INDEX_KEYS] : [...OWNER_INDEX_KEYS, TEST_INDEX_KEY];
}

/** One package version the index offers. */
export interface IIndexPackage {
	readonly id: string;
	readonly kind: PackageKind;
	readonly name: string;
	readonly version: string;
	readonly country: string;
	readonly region: string;
	readonly author: string;
	readonly licence: string;
	readonly description: string;
	/** `requires.saengine`, e.g. `>=0.0.50`; empty when any version will do. */
	readonly requiresSaengine: string;
	/** `requires.packages`: other packages it needs, by id, with their version ranges. */
	readonly requiresPackages: { readonly [id: string]: string };
	readonly url: string;
	readonly size: number;
	readonly sha256: string;
	readonly hooks: boolean;
	readonly hooksSha256: string | undefined;
	readonly preview: string | undefined;
	readonly previewSha256: string | undefined;
	readonly source: 'official' | 'community';
	readonly repository: string;
}

export interface IPackageIndex {
	readonly generated: string;
	readonly packages: readonly IIndexPackage[];
	/** Entries left out, and why (a missing hash, a URL that is not HTTPS...). */
	readonly problems: readonly string[];
}

/** What the index command answers: the last verified index, or why there is none. */
export interface IPackageIndexState {
	/** The verified index text (parse it with {@link readPackageIndex}). */
	readonly text?: string;
	readonly keyId?: string;
	readonly test?: boolean;
	readonly at?: string;
	readonly source?: string;
	/** Why the last fetch failed (the cached index, if any, is still given). */
	readonly error?: string;
	/** Online checks are off (`saengine.packages.checkOnline`). */
	readonly offline?: boolean;
}

/** Arguments of the download command. */
export interface IPackageDownload {
	readonly url: string;
	readonly size: number;
	readonly sha256: string;
	readonly fileName: string;
}

type Raw = { readonly [key: string]: unknown };

function isRaw(value: unknown): value is Raw {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string {
	return typeof value === 'string' ? value : '';
}

function kindOf(value: unknown): PackageKind | undefined {
	return PACKAGE_KINDS.find(k => k === value);
}

/** The index from its verified text; entries that cannot be installed safely are left out. */
export function readPackageIndex(text: string): IPackageIndex {
	let doc: unknown;
	try {
		doc = JSON.parse(text);
	} catch {
		return { generated: '', packages: [], problems: [localize('packages.indexNotJson', "The package index cannot be read.")] };
	}
	if (!isRaw(doc) || doc.schema !== 'saengine.packageIndex/1' || !Array.isArray(doc.packages)) {
		return { generated: '', packages: [], problems: [localize('packages.indexSchema', "The package index is not a saengine.packageIndex/1 document (a newer SAEngine may be needed).")] };
	}
	const packages: IIndexPackage[] = [];
	const problems: string[] = [];
	for (const entry of doc.packages) {
		if (!isRaw(entry)) {
			continue;
		}
		const id = str(entry.id);
		const kind = kindOf(entry.kind ?? 'designCode');
		const sha256 = str(entry.sha256).toLowerCase();
		const size = typeof entry.size === 'number' ? entry.size : NaN;
		const url = str(entry.url);
		if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(id) || !kind || !str(entry.version)) {
			problems.push(localize('packages.entryInvalid', "An entry without a valid id, kind or version was left out ({0}).", id || '?'));
			continue;
		}
		if (!/^[0-9a-f]{64}$/.test(sha256) || !(size > 0) || !url.startsWith('https://')) {
			problems.push(localize('packages.entryUnpinned', "{0} {1} was left out: it has no HTTPS URL, size and SHA-256.", id, str(entry.version)));
			continue;
		}
		const requires = isRaw(entry.requires) ? entry.requires : {};
		const required: { [id: string]: string } = {};
		if (isRaw(requires.packages)) {
			for (const [other, range] of Object.entries(requires.packages)) {
				required[other] = str(range);
			}
		}
		const hooksSha256 = str(entry.hooksSha256).toLowerCase();
		const previewSha256 = str(entry.previewSha256).toLowerCase();
		packages.push({
			id, kind, sha256, size, url,
			name: str(entry.name) || id,
			version: str(entry.version),
			country: str(entry.country),
			region: str(entry.region),
			author: str(entry.author),
			licence: str(entry.licence ?? entry.license),
			description: str(entry.description),
			requiresSaengine: str(requires.saengine),
			requiresPackages: required,
			hooks: entry.hooks === true,
			hooksSha256: /^[0-9a-f]{64}$/.test(hooksSha256) ? hooksSha256 : undefined,
			preview: str(entry.preview) || undefined,
			previewSha256: /^[0-9a-f]{64}$/.test(previewSha256) ? previewSha256 : undefined,
			source: entry.source === 'community' ? 'community' : 'official',
			repository: str(entry.repository),
		});
	}
	return { generated: str(doc.generated), packages, problems };
}

/** Negative, 0 or positive like {@link compareVersions}; a version that does not parse sorts as text. */
export function compareLoose(a: string, b: string): number {
	const full = (v: string) => /^\d+\.\d+$/.test(v) ? `${v}.0` : /^\d+$/.test(v) ? `${v}.0.0` : v;
	return compareVersions(full(a), full(b)) ?? a.localeCompare(b, undefined, { numeric: true });
}

/**
 * Whether `version` satisfies `spec`: comparators (`>=`, `>`, `<=`, `<`, `==`, `=`, `!=`; a bare
 * version means `==`) joined by commas, as pack.json's `requires` (PEP 440 style) writes them.
 * An empty spec is satisfied by anything; a spec that cannot be read is not satisfied.
 */
export function versionSatisfies(version: string, spec: string): boolean {
	const parts = spec.split(',').map(p => p.trim()).filter(Boolean);
	for (const part of parts) {
		const match = /^(>=|<=|==|!=|>|<|=|~=)?\s*v?([0-9][0-9A-Za-z.+\-]*)$/.exec(part);
		if (!match) {
			return false;
		}
		const c = compareLoose(version, match[2]);
		const ok = match[1] === '>=' || match[1] === '~=' ? c >= 0 : match[1] === '>' ? c > 0 : match[1] === '<=' ? c <= 0 : match[1] === '<' ? c < 0 : match[1] === '!=' ? c !== 0 : c === 0;
		if (!ok) {
			return false;
		}
	}
	return true;
}

/**
 * The newest version of each package that this SAEngine understands (`requires.saengine`),
 * sorted by kind then name; a package whose every version needs a newer SAEngine is kept (its
 * newest version) and marked by {@link needsNewerSaengine}.
 */
export function newestPackages(index: IPackageIndex, saengineVersion: string): IIndexPackage[] {
	const byId = new Map<string, IIndexPackage>();
	const newer = (a: IIndexPackage, b: IIndexPackage | undefined) => !b || compareLoose(a.version, b.version) > 0;
	for (const pkg of index.packages) {
		const current = byId.get(pkg.id);
		const fits = versionSatisfies(saengineVersion, pkg.requiresSaengine);
		const currentFits = current ? versionSatisfies(saengineVersion, current.requiresSaengine) : false;
		if (!current || (fits && !currentFits) || (fits === currentFits && newer(pkg, current))) {
			byId.set(pkg.id, pkg);
		}
	}
	return [...byId.values()].sort((a, b) => PACKAGE_KINDS.indexOf(a.kind) - PACKAGE_KINDS.indexOf(b.kind) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

/** Why this SAEngine cannot install `pkg`, or undefined. */
export function needsNewerSaengine(pkg: IIndexPackage, saengineVersion: string): string | undefined {
	return versionSatisfies(saengineVersion, pkg.requiresSaengine)
		? undefined
		: localize('packages.needsNewer', "Needs SAEngine {0}; this is SAEngine {1}. Update SAEngine first (Help > Check for SAEngine Updates...).", pkg.requiresSaengine, saengineVersion);
}

/** An installed package as the update check needs it. */
export interface IInstalledPackage {
	readonly id: string;
	readonly kind: PackageKind;
	readonly version: string;
	readonly scope: 'builtin' | 'user' | 'project';
}

/** An installed (user or project) package with a newer version in the index. */
export interface IPackageUpdate {
	readonly installed: IInstalledPackage;
	readonly available: IIndexPackage;
}

/**
 * The updates: every user or project package whose id and kind the index offers in a newer
 * version this SAEngine understands. Built-in packages update with SAEngine itself; a newer
 * index version of one is installed as the user's copy from Browse, which shadows it.
 */
export function packageUpdates(installed: readonly IInstalledPackage[], newest: readonly IIndexPackage[], saengineVersion: string): IPackageUpdate[] {
	const updates: IPackageUpdate[] = [];
	for (const pkg of installed) {
		if (pkg.scope === 'builtin') {
			continue;
		}
		const available = newest.find(n => n.id === pkg.id && n.kind === pkg.kind);
		if (available && !needsNewerSaengine(available, saengineVersion) && (!pkg.version || compareLoose(available.version, pkg.version) > 0)) {
			updates.push({ installed: pkg, available });
		}
	}
	return updates;
}

/** The required packages of `pkg` that are not installed in a fitting version, with the index entry to install. */
export function missingRequirements(pkg: IIndexPackage, installed: readonly IInstalledPackage[], newest: readonly IIndexPackage[]): { readonly id: string; readonly range: string; readonly available: IIndexPackage | undefined }[] {
	const missing = [];
	for (const [id, range] of Object.entries(pkg.requiresPackages)) {
		if (installed.some(i => i.id === id && (!i.version || versionSatisfies(i.version, range)))) {
			continue;
		}
		missing.push({ id, range, available: newest.find(n => n.id === id && versionSatisfies(n.version, range)) });
	}
	return missing;
}

export function kindLabel(kind: PackageKind): string {
	switch (kind) {
		case 'designCode': return localize('packages.kindDesignCode', "Design code");
		case 'structureTemplate': return localize('packages.kindStructure', "Structure template");
		case 'buildingTemplate': return localize('packages.kindBuilding', "Building template");
	}
}

export function kindPluralLabel(kind: PackageKind): string {
	switch (kind) {
		case 'designCode': return localize('packages.kindsDesignCode', "Design codes");
		case 'structureTemplate': return localize('packages.kindsStructure', "Structure templates");
		case 'buildingTemplate': return localize('packages.kindsBuilding', "Building templates");
	}
}

/** "1.2 MB", "48 kB". */
export function sizeLabel(bytes: number): string {
	return bytes >= 1024 * 1024
		? localize('packages.sizeMb', "{0} MB", (bytes / (1024 * 1024)).toFixed(1))
		: localize('packages.sizeKb', "{0} kB", Math.max(1, Math.round(bytes / 1024)));
}

/** The zip's file name: `<id>-<version>.zip`. */
export function packageFileName(pkg: IIndexPackage): string {
	return `${pkg.id}-${pkg.version}.zip`;
}
