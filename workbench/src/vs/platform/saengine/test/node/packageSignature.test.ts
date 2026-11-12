/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { createHash, createPrivateKey, generateKeyPairSync, sign } from 'crypto';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { keyIdOf, readPublicKey, SIGNATURE_SCHEMA, verifyIndexSignature } from '../../node/packageSignature.js';

/** The index repository's TEST key: its private key is SHA-256 of this published seed (scripts/sign_index.py). */
const TEST_SEED = 'saengine-index TEST KEY - not trusted by release builds';
const TEST_PUBLIC_PEM = '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAnh862XvPC3UeuOZnxRhTtcj+lm1lq0DnPriljmpYVa8=\n-----END PUBLIC KEY-----\n';

function testPrivateKey() {
	// PKCS#8 DER of an Ed25519 private key: a fixed prefix and the 32-byte seed.
	const seed = createHash('sha256').update(TEST_SEED).digest();
	return createPrivateKey({ key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]), format: 'der', type: 'pkcs8' });
}

function signature(data: Buffer, keyId: string, key = testPrivateKey()): string {
	return JSON.stringify({ schema: SIGNATURE_SCHEMA, algorithm: 'Ed25519', keyId, signature: sign(null, data, key).toString('base64') });
}

suite('SAEngine - Package index signature', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const index = Buffer.from('{"schema":"saengine.packageIndex/1","packages":[]}\n');
	const testKey = { keyId: '82af6b8cd5077d21', publicKey: TEST_PUBLIC_PEM, test: true };

	test('the TEST key id matches the index repository', () => {
		assert.strictEqual(keyIdOf(readPublicKey(TEST_PUBLIC_PEM).raw), '82af6b8cd5077d21');
	});

	test('accepts the exact bytes signed by an accepted key', () => {
		assert.strictEqual(verifyIndexSignature(index, signature(index, testKey.keyId), [testKey]), testKey);
	});

	test('refuses a changed index, another key, or a key it does not accept', () => {
		const changed = Buffer.from(index.toString().replace('[]', '[{}]'));
		assert.throws(() => verifyIndexSignature(changed, signature(index, testKey.keyId), [testKey]), /does not match/);
		assert.throws(() => verifyIndexSignature(index, signature(index, testKey.keyId), []), /does not accept/);
		const other = generateKeyPairSync('ed25519');
		const otherRaw = readPublicKey(other.publicKey.export({ format: 'pem', type: 'spki' }).toString()).raw;
		const otherKey = { keyId: keyIdOf(otherRaw), publicKey: otherRaw.toString('base64') };
		assert.throws(() => verifyIndexSignature(index, signature(index, otherKey.keyId), [otherKey]), /does not match/);
		assert.ok(verifyIndexSignature(index, signature(index, otherKey.keyId, other.privateKey), [otherKey]));
		assert.throws(() => verifyIndexSignature(index, '{"schema":"x"}', [testKey]), /not a/);
	});
});
