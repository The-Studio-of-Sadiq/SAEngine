/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { promises as fs } from 'fs';
import { tmpdir } from 'os';
import { streamToBuffer } from '../../../base/common/buffer.js';
import { CancellationToken, CancellationTokenSource } from '../../../base/common/cancellation.js';
import { buffer as zipBuffer, extract } from '../../../base/node/zip.js';
import { basename, dirname, join, resolve } from '../../../base/common/path.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { ILogService } from '../../log/common/log.js';
import { IRequestService } from '../../request/common/request.js';
import { ICopyPackageRequest, IDownloadPackageRequest, IFetchIndexRequest, IOpenBundleRequest, IOpenedBundle, IReadIndexFileRequest, ISaenginePackagesService, IVerifiedIndex, packageUrlProblem, safeFileName } from '../common/packages.js';
import { sha256Hex, verifyIndexSignature } from '../node/packageSignature.js';

const CALL_SITE = 'saengine.packages';
/** The index is a few hundred kB at most. */
const MAX_INDEX_BYTES = 8 * 1024 * 1024;
/** The registry's own limit for a package (a .civil template) is 50 MB unpacked. */
const MAX_PACKAGE_BYTES = 64 * 1024 * 1024;

/** See {@link ISaenginePackagesService}. */
export class SaenginePackagesMainService implements ISaenginePackagesService {

	declare readonly _serviceBrand: undefined;

	private readonly folder = join(tmpdir(), 'saengine-packages', generateUuid());

	constructor(
		@IRequestService private readonly requestService: IRequestService,
		@ILogService private readonly logService: ILogService,
	) { }

	private async get(url: string, limit: number, timeout: number): Promise<Uint8Array> {
		const problem = packageUrlProblem(url);
		if (problem) {
			throw new Error(problem);
		}
		const cts = new CancellationTokenSource();
		try {
			const context = await this.requestService.request({ type: 'GET', url, timeout, callSite: CALL_SITE, followRedirects: 5 }, cts.token);
			const status = context.res.statusCode ?? 0;
			if (status === 404) {
				throw new Error(`not published (yet) at ${url}`);
			}
			if (status !== 200) {
				throw new Error(`the server answered HTTP ${status} for ${url}`);
			}
			const length = Number(context.res.headers['content-length'] ?? 0);
			if (length > limit) {
				throw new Error(`${url} is ${length} bytes, more than the ${limit} allowed`);
			}
			const buffer = (await streamToBuffer(context.stream)).buffer;
			if (buffer.byteLength > limit) {
				throw new Error(`${url} is larger than the ${limit} bytes allowed`);
			}
			return buffer;
		} finally {
			cts.dispose();
		}
	}

	async fetchIndex(request: IFetchIndexRequest): Promise<IVerifiedIndex> {
		const signatureUrl = request.signatureUrl ?? `${request.indexUrl}.sig`;
		const [index, signature] = await Promise.all([
			this.get(request.indexUrl, MAX_INDEX_BYTES, 30_000),
			this.get(signatureUrl, 64 * 1024, 30_000),
		]);
		const key = verifyIndexSignature(index, new TextDecoder().decode(signature), request.keys);
		this.logService.info(`[saengine packages] index from ${request.indexUrl} verified with key ${key.keyId}${key.test ? ' (TEST key)' : ''}`);
		return { text: new TextDecoder().decode(index), keyId: key.keyId, test: key.test === true, at: new Date().toISOString(), source: request.indexUrl };
	}

	async readIndexFile(request: IReadIndexFileRequest): Promise<IVerifiedIndex> {
		const index = await fs.readFile(request.indexPath);
		if (index.byteLength > MAX_INDEX_BYTES) {
			throw new Error(`${request.indexPath} is too large for a package index`);
		}
		let signature: string;
		try {
			signature = await fs.readFile(`${request.indexPath}.sig`, 'utf8');
		} catch {
			throw new Error(`there is no index.json.sig beside ${request.indexPath}: an unsigned index is not used`);
		}
		const key = verifyIndexSignature(index, signature, request.keys);
		return { text: new TextDecoder().decode(index), keyId: key.keyId, test: key.test === true, at: new Date().toISOString(), source: request.indexPath };
	}

	async openBundle(request: IOpenBundleRequest): Promise<IOpenedBundle | undefined> {
		const stat = await fs.stat(request.path);
		let folder = request.path;
		if (stat.isFile()) {
			if (!request.path.toLowerCase().endsWith('.zip')) {
				return undefined;
			}
			// A package zip has pack.json, a bundle index.json: look before unpacking.
			try {
				await zipBuffer(request.path, 'index.json');
			} catch {
				return undefined;
			}
			folder = join(this.folder, `bundle-${generateUuid()}`);
			await fs.mkdir(folder, { recursive: true });
			await extract(request.path, folder, { overwrite: true }, CancellationToken.None);
		} else if (!stat.isDirectory()) {
			return undefined;
		}
		const indexPath = join(folder, 'index.json');
		try {
			await fs.access(indexPath);
		} catch {
			return undefined;
		}
		const index = await this.readIndexFile({ indexPath, keys: request.keys });
		this.logService.info(`[saengine packages] offline bundle ${request.path} verified with key ${index.keyId}`);
		return { ...index, source: request.path, folder };
	}

	private async save(data: Uint8Array, expected: { readonly size: number; readonly sha256: string; readonly fileName: string }, from: string): Promise<string> {
		if (!/^[0-9a-f]{64}$/.test(expected.sha256)) {
			throw new Error('the index gives no valid SHA-256 for this package');
		}
		await fs.mkdir(this.folder, { recursive: true });
		const target = join(this.folder, safeFileName(expected.fileName));
		const partial = `${target}.partial`;
		await fs.writeFile(partial, data);
		try {
			if (data.byteLength !== expected.size) {
				throw new Error(`${from} has ${data.byteLength} bytes, the index says ${expected.size}: it was not installed`);
			}
			const actual = sha256Hex(data);
			if (actual !== expected.sha256) {
				throw new Error(`${from} does not match the SHA-256 in the index (expected ${expected.sha256}, got ${actual}): it was not installed`);
			}
			await fs.rename(partial, target);
		} catch (error) {
			await fs.rm(partial, { force: true });
			throw error;
		}
		return target;
	}

	async downloadPackage(request: IDownloadPackageRequest): Promise<string> {
		if (!Number.isFinite(request.size) || request.size <= 0 || request.size > MAX_PACKAGE_BYTES) {
			throw new Error(`the index gives an impossible size for ${request.fileName}`);
		}
		const data = await this.get(request.url, request.size, 120_000);
		const path = await this.save(data, request, request.url);
		this.logService.info(`[saengine packages] ${request.url} downloaded and verified (sha256 ${request.sha256})`);
		return path;
	}

	async copyPackage(request: ICopyPackageRequest): Promise<string> {
		const stat = await fs.stat(request.path);
		if (!stat.isFile() || stat.size > MAX_PACKAGE_BYTES) {
			throw new Error(`${request.path} is not a package zip`);
		}
		return this.save(await fs.readFile(request.path), request, basename(request.path));
	}

	async discard(path: string): Promise<void> {
		// Only files this service wrote, in its own folder.
		if (dirname(resolve(path)) === resolve(this.folder)) {
			await fs.rm(path, { force: true });
		}
	}
}
