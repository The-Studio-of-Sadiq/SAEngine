/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { bearerToken, checkRequest, constantTimeEquals, isLocalHost } from '../../common/saengineAi.js';

suite('SAEngine - AI server request checks', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const token = 'k3Y-secret_0123456789abcdefghijklmnopqrstuv';
	const ok = { host: '127.0.0.1:5000', authorization: `Bearer ${token}` };

	test('a local client with the token is let in', () => {
		assert.deepStrictEqual([
			checkRequest(ok, 5000, token),
			checkRequest({ ...ok, host: 'localhost:5000' }, 5000, token),
			checkRequest({ ...ok, host: '[::1]:5000' }, 5000, token),
			checkRequest({ ...ok, authorization: `bearer  ${token} ` }, 5000, token),
		].map(c => c.ok), [true, true, true, true]);
	});

	test('a missing or wrong token is refused with 401', () => {
		const refused = (authorization: string | undefined) => checkRequest({ ...ok, authorization }, 5000, token);
		for (const authorization of [undefined, '', 'Bearer', `Basic ${token}`, `Bearer ${token}x`, `Bearer ${token.slice(0, -1)}`, `Bearer ${token.toUpperCase()}`, token]) {
			assert.deepStrictEqual(refused(authorization), { ok: false, status: 401, reason: 'token' }, String(authorization));
		}
	});

	test('a browser page is refused whatever it sends (Origin, DNS rebinding)', () => {
		// Any Origin: browsers send one with every cross-origin POST; MCP clients do not.
		for (const origin of ['https://evil.example', 'http://127.0.0.1:5000', 'null', '']) {
			assert.deepStrictEqual(checkRequest({ ...ok, origin }, 5000, token), { ok: false, status: 403, reason: 'origin' }, origin);
		}
		// A rebinding page reaches 127.0.0.1 under its own host name.
		for (const host of ['evil.example:5000', 'localhost.evil.example:5000', '127.0.0.1:5001', '127.0.0.1', '0.0.0.0:5000', undefined]) {
			assert.deepStrictEqual(checkRequest({ ...ok, host }, 5000, token), { ok: false, status: 403, reason: 'host' }, String(host));
		}
	});

	test('the host is checked before the token, so a refused page learns nothing about it', () => {
		assert.deepStrictEqual(checkRequest({ host: 'evil.example:5000', origin: 'https://evil.example' }, 5000, token).ok, false);
		assert.strictEqual((checkRequest({ host: 'evil.example:5000' }, 5000, token) as { reason: string }).reason, 'host');
	});

	test('helpers', () => {
		assert.deepStrictEqual({
			bearer: [bearerToken('Bearer abc'), bearerToken('Bearer a b'), bearerToken(undefined), bearerToken('Token abc')],
			equals: [constantTimeEquals('abc', 'abc'), constantTimeEquals('abc', 'abd'), constantTimeEquals('abc', 'ab'), constantTimeEquals('', '')],
			local: [isLocalHost('LOCALHOST:80', 80), isLocalHost('127.0.0.1:80', 8080)],
		}, {
			bearer: ['abc', undefined, undefined, undefined],
			equals: [true, false, false, false],
			local: [true, false],
		});
	});
});
