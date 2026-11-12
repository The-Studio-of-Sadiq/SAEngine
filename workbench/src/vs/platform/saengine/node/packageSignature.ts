/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createHash, createPublicKey, KeyObject, verify } from 'crypto';
import { IPackageIndexKey } from '../common/packages.js';

/*
 * The package index signature (`saengine.packageIndexSignature/1`, written by the index
 * repository's scripts/sign_index.py): a small JSON document with the key id (the first 16 hex
 * digits of the SHA-256 of the raw 32-byte Ed25519 public key) and the 64-byte signature of the
 * exact bytes of index.json, in base64.
 */

export const SIGNATURE_SCHEMA = 'saengine.packageIndexSignature/1';

/** DER prefix of an Ed25519 SubjectPublicKeyInfo; the raw 32-byte key follows it. */
const ED25519_SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex');

/** The key as a Node KeyObject and its raw 32 bytes, from PEM or base64 of the raw bytes. */
export function readPublicKey(publicKey: string): { readonly key: KeyObject; readonly raw: Buffer } {
	const text = publicKey.trim();
	if (text.startsWith('-----BEGIN')) {
		const key = createPublicKey(text);
		if (key.asymmetricKeyType !== 'ed25519') {
			throw new Error('not an Ed25519 public key');
		}
		const der = key.export({ format: 'der', type: 'spki' });
		return { key, raw: der.subarray(der.length - 32) };
	}
	const raw = Buffer.from(text, 'base64');
	if (raw.length !== 32) {
		throw new Error('an Ed25519 public key has 32 bytes');
	}
	return { key: createPublicKey({ key: Buffer.concat([ED25519_SPKI_PREFIX, raw]), format: 'der', type: 'spki' }), raw };
}

/** The key id sign_index.py writes: the first 16 hex digits of SHA-256 of the raw key. */
export function keyIdOf(raw: Buffer): string {
	return createHash('sha256').update(raw).digest('hex').slice(0, 16);
}

/**
 * Checks `signature` (the text of index.json.sig) over `index` (the exact bytes of index.json)
 * against the accepted keys: the key that signed it, or an Error saying why not (written for
 * the engineer).
 */
export function verifyIndexSignature(index: Uint8Array, signature: string, keys: readonly IPackageIndexKey[]): IPackageIndexKey {
	let doc: { schema?: unknown; algorithm?: unknown; keyId?: unknown; signature?: unknown };
	try {
		doc = JSON.parse(signature);
	} catch {
		throw new Error('the index signature file cannot be read');
	}
	if (doc.schema !== SIGNATURE_SCHEMA || doc.algorithm !== 'Ed25519' || typeof doc.signature !== 'string' || typeof doc.keyId !== 'string') {
		throw new Error(`the index signature is not a ${SIGNATURE_SCHEMA} Ed25519 signature`);
	}
	const accepted = keys.find(k => k.keyId === doc.keyId);
	if (!accepted) {
		throw new Error(`the index is signed with the key ${doc.keyId}, which this SAEngine does not accept`);
	}
	const { key, raw } = readPublicKey(accepted.publicKey);
	if (keyIdOf(raw) !== accepted.keyId) {
		throw new Error(`the key ${accepted.keyId} built into SAEngine does not match its id`);
	}
	const bytes = Buffer.from(doc.signature, 'base64');
	if (bytes.length !== 64 || !verify(null, Buffer.from(index), key, bytes)) {
		throw new Error('the index signature does not match index.json: it was changed after signing');
	}
	return accepted;
}

/** Lower-case hex SHA-256 of `data`. */
export function sha256Hex(data: Uint8Array): string {
	return createHash('sha256').update(data).digest('hex');
}
