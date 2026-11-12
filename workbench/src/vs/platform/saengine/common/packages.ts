/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createDecorator } from '../../instantiation/common/instantiation.js';

/*
 * The network side of the Packages page (docs/marketplace-plan.md §4, round M3), in the main
 * process: it fetches the package index and its Ed25519 signature, verifies the signature with
 * Node's crypto (no new dependency), and downloads a package zip pinned by the size and SHA-256
 * of the verified index. Nothing it fetches is run: the workbench hands a verified zip to the
 * backend's `codes/install`, which validates it like any other package (no programs, no links,
 * no paths outside the folder) and never trusts its hooks.
 */

export const PACKAGES_CHANNEL = 'saenginePackages';

export const ISaenginePackagesService = createDecorator<ISaenginePackagesService>('saenginePackagesService');

/** A public key the app accepts for the index (`keys/*.pem` of the index repository). */
export interface IPackageIndexKey {
	/** The first 16 hex digits of the SHA-256 of the raw 32-byte Ed25519 public key. */
	readonly keyId: string;
	/** The public key as PEM (SubjectPublicKeyInfo) or as the raw 32 bytes in base64. */
	readonly publicKey: string;
	/** The TEST key (a published seed): accepted by development builds only. */
	readonly test?: boolean;
}

export interface IFetchIndexRequest {
	readonly indexUrl: string;
	/** Default: `<indexUrl>.sig`. */
	readonly signatureUrl?: string;
	readonly keys: readonly IPackageIndexKey[];
}

export interface IReadIndexFileRequest {
	/** `index.json` on disk (an offline bundle); its signature is `<indexPath>.sig`. */
	readonly indexPath: string;
	readonly keys: readonly IPackageIndexKey[];
}

/** An index whose signature checked out: its exact text, and who signed it. */
export interface IVerifiedIndex {
	readonly text: string;
	readonly keyId: string;
	/** Signed by the TEST key. */
	readonly test: boolean;
	/** When it was fetched or read (ISO 8601). */
	readonly at: string;
	/** Where it came from (the URL, or the file of an offline bundle). */
	readonly source: string;
}

export interface IOpenBundleRequest {
	/** An offline bundle: a folder, or a zip, with `index.json`, `index.json.sig` and `packages/*.zip`. */
	readonly path: string;
	readonly keys: readonly IPackageIndexKey[];
}

/** An offline bundle whose index checked out: the folder its package zips are read from. */
export interface IOpenedBundle extends IVerifiedIndex {
	readonly folder: string;
}

export interface IDownloadPackageRequest {
	readonly url: string;
	readonly size: number;
	readonly sha256: string;
	/** The file name to save as (`<id>-<version>.zip`); only its base name is used. */
	readonly fileName: string;
}

export interface ICopyPackageRequest {
	/** A package zip of an offline bundle, checked against the same size and SHA-256. */
	readonly path: string;
	readonly size: number;
	readonly sha256: string;
	readonly fileName: string;
}

export interface ISaenginePackagesService {
	readonly _serviceBrand: undefined;
	/** Fetches `index.json` and its `.sig`; rejects unless a key in `keys` signed exactly these bytes. */
	fetchIndex(request: IFetchIndexRequest): Promise<IVerifiedIndex>;
	/** The same for an offline bundle's `index.json` beside its `index.json.sig`. */
	readIndexFile(request: IReadIndexFileRequest): Promise<IVerifiedIndex>;
	/**
	 * Downloads a package zip to a private temporary folder as `<file>.partial`, checks its size
	 * and SHA-256, then renames it: the path of the verified zip. A mismatch deletes the file.
	 * Only HTTPS URLs on the allowed hosts are fetched.
	 */
	downloadPackage(request: IDownloadPackageRequest): Promise<string>;
	/**
	 * Opens an offline bundle (round M8): a zip is unpacked to the private temporary folder
	 * first; its index is verified like a downloaded one. Undefined when `path` is not a bundle
	 * (no `index.json` in it): then it is a single package to install as a file.
	 */
	openBundle(request: IOpenBundleRequest): Promise<IOpenedBundle | undefined>;
	/** Copies an offline bundle's zip to the temporary folder after the same checks. */
	copyPackage(request: ICopyPackageRequest): Promise<string>;
	/** Deletes a zip `downloadPackage` or `copyPackage` returned (after the install). */
	discard(path: string): Promise<void>;
}

/** The hosts a package or index may be fetched from: GitHub releases and their download host. */
export const PACKAGE_HOSTS: readonly string[] = ['github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'];

/** Why `url` may not be fetched (not HTTPS, another host), or undefined when it may. */
export function packageUrlProblem(url: string): string | undefined {
	let parsed: URL;
	try {
		parsed = new URL(url);
	} catch {
		return `not a URL: ${url}`;
	}
	if (parsed.protocol !== 'https:') {
		return `only HTTPS is used, not ${parsed.protocol.replace(':', '')}`;
	}
	if (!PACKAGE_HOSTS.includes(parsed.hostname.toLowerCase())) {
		return `the host ${parsed.hostname} is not one packages come from (${PACKAGE_HOSTS.join(', ')})`;
	}
	return undefined;
}

/** A safe local file name for a download: the base name, letters, digits, `.`, `-` and `_` only. */
export function safeFileName(name: string): string {
	const base = name.split(/[\\/]/).pop() ?? '';
	const cleaned = base.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '');
	return cleaned.toLowerCase().endsWith('.zip') && cleaned.length > 4 ? cleaned : `${cleaned || 'package'}.zip`;
}
