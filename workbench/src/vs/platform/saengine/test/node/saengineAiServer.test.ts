/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import type * as http from 'http';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { NullLogService } from '../../../log/common/log.js';
import { MCP } from '../../../mcp/common/modelContextProtocol.js';
import { ISaengineAiBroker, ISaengineAiClientEvent } from '../../common/saengineAi.js';
import { generateToken, SaengineAiServer } from '../../node/saengineAiServer.js';

interface IResponse {
	readonly status: number;
	readonly headers: http.IncomingHttpHeaders;
	readonly body: string;
}

/** A raw request, so the test sets Host and Origin as a browser or another program would. */
async function request(port: number, options: { method?: string; path?: string; headers?: Record<string, string>; body?: unknown }): Promise<IResponse> {
	const { request: httpRequest } = await import('http');
	return new Promise((resolve, reject) => {
		const req = httpRequest({
			host: '127.0.0.1', port, method: options.method ?? 'POST', path: options.path ?? '/mcp',
			headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', ...options.headers },
		}, res => {
			let body = '';
			res.setEncoding('utf8');
			res.on('data', chunk => body += chunk);
			res.on('end', () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body }));
		});
		req.on('error', reject);
		if (options.body !== undefined) {
			req.write(JSON.stringify(options.body));
		}
		req.end();
	});
}

const INITIALIZE = { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test-client', version: '1.0' } } };

suite('SAEngine - AI server (HTTP)', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	let events: ISaengineAiClientEvent[];
	let calls: { name: string; args: Record<string, unknown> }[];
	const broker: ISaengineAiBroker = {
		listTools: async () => [{ name: 'get_project', inputSchema: { type: 'object' } } as MCP.Tool],
		callTool: async (name, args) => {
			calls.push({ name, args });
			return { content: [{ type: 'text', text: `ran ${name}` }] };
		},
		clientEvent: async event => { events.push(event); },
	};

	async function withServer(run: (server: SaengineAiServer, auth: Record<string, string>) => Promise<void>): Promise<void> {
		events = [];
		calls = [];
		const server = new SaengineAiServer(generateToken(), broker, { version: '9.9.9', instructions: 'hello' }, new NullLogService());
		try {
			const info = await server.start();
			assert.strictEqual(info.url, `http://127.0.0.1:${info.port}/mcp`);
			await run(server, { Authorization: `Bearer ${info.token}`, Host: `127.0.0.1:${info.port}` });
		} finally {
			server.dispose();
		}
	}

	test('tokens are long, random and URL-safe', () => {
		const tokens = new Set(Array.from({ length: 20 }, generateToken));
		assert.strictEqual(tokens.size, 20);
		for (const token of tokens) {
			assert.match(token, /^[A-Za-z0-9_-]{43}$/);
		}
	});

	test('requests without the token, from a browser or under another host are refused', () => withServer(async (server, auth) => {
		const port = server.info.port;
		const refused: IResponse[] = [];
		for (const options of [
			{ body: INITIALIZE },
			{ headers: { Authorization: 'Bearer wrong' }, body: INITIALIZE },
			{ headers: { ...auth, Origin: 'https://evil.example' }, body: INITIALIZE },
			{ headers: { ...auth, Host: `evil.example:${port}` }, body: INITIALIZE },
			{ method: 'OPTIONS', headers: { Origin: 'https://evil.example', 'Access-Control-Request-Method': 'POST' } },
		]) {
			refused.push(await request(port, options));
		}
		assert.deepStrictEqual(refused.map(r => r.status), [401, 401, 403, 403, 403]);
		// No CORS header ever: a page could not read a response even if it got one.
		assert.ok(refused.every(r => r.headers['access-control-allow-origin'] === undefined));
		assert.deepStrictEqual(calls, []);
		// One notice for the burst, without the token.
		assert.deepStrictEqual(events, [{ kind: 'rejected', reason: 'token' }]);
	}));

	test('an MCP client initializes, lists and calls tools', () => withServer(async (server, auth) => {
		const port = server.info.port;
		const init = await request(port, { headers: auth, body: INITIALIZE });
		assert.strictEqual(init.status, 200);
		const session = init.headers['mcp-session-id'] as string;
		assert.ok(session);
		const result = JSON.parse(init.body).result;
		assert.deepStrictEqual({ server: result.serverInfo, instructions: result.instructions, version: result.protocolVersion, tools: result.capabilities.tools }, {
			server: { name: 'saengine', title: 'SAEngine', version: '9.9.9' }, instructions: 'hello', version: '2025-06-18', tools: { listChanged: true },
		});
		assert.deepStrictEqual(events, [{ kind: 'connected', client: 'test-client 1.0' }]);

		const headers = { ...auth, 'Mcp-Session-Id': session };
		assert.strictEqual((await request(port, { headers, body: { jsonrpc: '2.0', method: 'notifications/initialized' } })).status, 202);
		const list = JSON.parse((await request(port, { headers, body: { jsonrpc: '2.0', id: 2, method: 'tools/list' } })).body);
		assert.deepStrictEqual(list.result.tools.map((t: MCP.Tool) => t.name), ['get_project']);
		const call = JSON.parse((await request(port, { headers, body: { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'get_project', arguments: { a: 1 } } } })).body);
		assert.deepStrictEqual(call.result.content, [{ type: 'text', text: 'ran get_project' }]);
		assert.deepStrictEqual(calls, [{ name: 'get_project', args: { a: 1 } }]);

		// A session id alone is not enough: the token is checked on every request.
		assert.strictEqual((await request(port, { headers: { 'Mcp-Session-Id': session, Host: auth.Host }, body: { jsonrpc: '2.0', id: 4, method: 'tools/list' } })).status, 401);
		assert.strictEqual((await request(port, { method: 'DELETE', headers })).status, 204);
		assert.strictEqual((await request(port, { headers, body: { jsonrpc: '2.0', id: 5, method: 'tools/list' } })).status, 404);
	}));

	test('only the MCP path answers, and a request must start a session', () => withServer(async (server, auth) => {
		const port = server.info.port;
		assert.strictEqual((await request(port, { path: '/', headers: auth, body: INITIALIZE })).status, 404);
		assert.strictEqual((await request(port, { headers: auth, body: { jsonrpc: '2.0', id: 1, method: 'tools/list' } })).status, 400);
		assert.strictEqual((await request(port, { method: 'PUT', headers: auth, body: INITIALIZE })).status, 405);
	}));

	test('a fixed port another window has falls back to a free one', async () => {
		const first = new SaengineAiServer(generateToken(), broker, {}, new NullLogService());
		let second: SaengineAiServer | undefined;
		try {
			const { port } = await first.start();
			second = new SaengineAiServer(generateToken(), broker, { port }, new NullLogService());
			const info = await second.start();
			assert.notStrictEqual(info.port, port);
			assert.ok(info.port > 0);
		} finally {
			first.dispose();
			second?.dispose();
		}
	});

	test('a stopped server no longer answers', async () => {
		const server = new SaengineAiServer(generateToken(), broker, {}, new NullLogService());
		const { port } = await server.start();
		server.dispose();
		await assert.rejects(request(port, { body: INITIALIZE }));
	});
});
