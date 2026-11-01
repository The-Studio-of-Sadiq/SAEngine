/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type * as http from 'http';
import { randomBytes } from 'crypto';
import { promises as fs } from 'fs';
import { DeferredPromise } from '../../../base/common/async.js';
import { Emitter, Event } from '../../../base/common/event.js';
import { IJsonRpcSuccessResponse, JsonRpcMessage, JsonRpcProtocol } from '../../../base/common/jsonRpcProtocol.js';
import { Disposable } from '../../../base/common/lifecycle.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { IChannel, IPCServer, IServerChannel } from '../../../base/parts/ipc/common/ipc.js';
import { ILogService } from '../../log/common/log.js';
import { MCP } from '../../mcp/common/modelContextProtocol.js';
import { isInitializeMessage, McpGatewaySession } from '../../mcp/node/mcpGatewaySession.js';
import { checkProviderUrl, checkRequest, ISaengineAiBroker, ISaengineAiClientEvent, ISaengineAiHttpRequest, ISaengineAiHttpResponse, ISaengineAiServerInfo, ISaengineAiStartOptions, MAX_PROVIDER_RESPONSE, MAX_PROVIDER_TIMEOUT, SAENGINE_AI_BROKER_CHANNEL, SAENGINE_AI_PATH } from '../common/saengineAi.js';

/** Largest request body accepted [bytes]. */
const MAX_BODY = 1024 * 1024;
/** Most MCP sessions one window keeps; the oldest goes when another client connects. */
const MAX_SESSIONS = 8;
/** At most one "rejected" notice per this long, so a flood of bad requests is one line [ms]. */
const REJECT_NOTICE_INTERVAL = 5000;

/** A fresh secret for one window's server: 256 random bits, URL-safe. */
export function generateToken(): string {
	return randomBytes(32).toString('base64url');
}

/**
 * The MCP endpoint of one window: Streamable HTTP on 127.0.0.1, each request checked for host,
 * origin and token before it is read. The MCP protocol itself (initialize, tools/list,
 * tools/call, SSE) is the editor's MCP gateway session; the tools are the window's (the broker).
 */
export class SaengineAiServer extends Disposable {

	private server: http.Server | undefined;
	private port = 0;
	private readonly sessions = new Map<string, McpGatewaySession>();
	private lastRejectNotice = 0;

	private readonly _onDidChangeTools = this._register(new Emitter<void>());

	constructor(
		readonly token: string,
		private readonly broker: ISaengineAiBroker,
		private readonly options: ISaengineAiStartOptions,
		private readonly logService: ILogService,
	) {
		super();
	}

	get info(): ISaengineAiServerInfo {
		return { url: `http://127.0.0.1:${this.port}${SAENGINE_AI_PATH}`, port: this.port, token: this.token };
	}

	/** The window's tools changed (e.g. edits were allowed): connected clients list them again. */
	toolsChanged(): void {
		this._onDidChangeTools.fire();
	}

	async start(): Promise<ISaengineAiServerInfo> {
		const { createServer } = await import('http'); // Lazy due to https://github.com/nodejs/node/issues/59686
		const server = this.server = createServer((req, res) => void this.handle(req, res));
		const listen = (port: number) => {
			const listening = new DeferredPromise<void>();
			const onError = (error: Error) => listening.error(error);
			server.once('error', onError);
			// Loopback only: nothing on the network can reach it.
			server.listen(port, '127.0.0.1', () => {
				server.off('error', onError);
				listening.complete();
			});
			return listening.p;
		};
		try {
			await listen(this.options.port ?? 0);
		} catch (error) {
			if (!this.options.port || (error as NodeJS.ErrnoException).code !== 'EADDRINUSE') {
				throw error;
			}
			// The fixed port is taken (another window has it): any free port.
			this.logService.info(`[saengineAi] port ${this.options.port} is in use, using a free one`);
			await listen(0);
		}
		const address = server.address();
		this.port = typeof address === 'object' && address ? address.port : 0;
		this.logService.info(`[saengineAi] listening on 127.0.0.1:${this.port}`);
		if (this.options.connectionFile) {
			await fs.writeFile(this.options.connectionFile, JSON.stringify({ ...this.info, pid: process.pid }, undefined, '\t'), { mode: 0o600 });
		}
		return this.info;
	}

	private async handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
		const check = checkRequest({ host: req.headers.host, origin: req.headers.origin, authorization: req.headers.authorization }, this.port, this.token);
		if (!check.ok) {
			this.reject(req, res, check.status, check.reason);
			return;
		}
		const path = (req.url ?? '').split('?')[0];
		if (path !== SAENGINE_AI_PATH) {
			this.respondError(res, 404, 'Not found');
			return;
		}
		try {
			switch (req.method) {
				case 'POST': await this.handlePost(req, res); return;
				case 'GET': this.handleGet(req, res); return;
				case 'DELETE': this.handleDelete(req, res); return;
				default: this.respondError(res, 405, 'Method not allowed');
			}
		} catch (error) {
			this.logService.error('[saengineAi] request failed', error);
			if (!res.headersSent) {
				this.respondError(res, 500, 'Internal server error');
			}
		}
	}

	private reject(req: http.IncomingMessage, res: http.ServerResponse, status: number, reason: string): void {
		this.logService.warn(`[saengineAi] rejected ${req.method} ${req.url}: ${reason}`);
		// Drain and close: nothing of the request is processed.
		req.resume();
		res.writeHead(status, { 'Content-Type': 'application/json', 'Connection': 'close' });
		res.end(JSON.stringify({ error: status === 401 ? 'Unauthorized' : 'Forbidden' }));
		const now = Date.now();
		if (now - this.lastRejectNotice > REJECT_NOTICE_INTERVAL) {
			this.lastRejectNotice = now;
			this.notify({ kind: 'rejected', reason });
		}
	}

	private async handlePost(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
		const body = await readBody(req);
		if (body === undefined) {
			this.respondError(res, 413, 'Payload too large');
			return;
		}
		let message: JsonRpcMessage | JsonRpcMessage[];
		try {
			message = JSON.parse(body);
		} catch (error) {
			res.writeHead(400, { 'Content-Type': 'application/json' });
			res.end(JSON.stringify(JsonRpcProtocol.createParseError('Parse error', String(error))));
			return;
		}

		const sessionId = header(req, 'mcp-session-id');
		let session = sessionId ? this.sessions.get(sessionId) : undefined;
		if (sessionId && !session) {
			this.respondError(res, 404, 'Session not found');
			return;
		}
		const initialize = isInitializeMessage(message);
		if (!session) {
			if (!initialize) {
				this.respondError(res, 400, 'Missing Mcp-Session-Id header');
				return;
			}
			session = this.createSession();
		}

		const responses = await session.handleIncoming(message);
		if (initialize) {
			this.decorateInitialize(responses, message);
		}
		const headers = { 'Content-Type': 'application/json', 'Mcp-Session-Id': session.id };
		if (responses.length === 0) {
			res.writeHead(202, headers);
			res.end();
			return;
		}
		res.writeHead(200, headers);
		res.end(JSON.stringify(Array.isArray(message) ? responses : responses[0]));
	}

	private handleGet(req: http.IncomingMessage, res: http.ServerResponse): void {
		const session = this.sessions.get(header(req, 'mcp-session-id') ?? '');
		if (!session) {
			this.respondError(res, 404, 'Session not found');
			return;
		}
		session.attachSseClient(req, res);
	}

	private handleDelete(req: http.IncomingMessage, res: http.ServerResponse): void {
		const session = this.sessions.get(header(req, 'mcp-session-id') ?? '');
		if (!session) {
			this.respondError(res, 404, 'Session not found');
			return;
		}
		session.dispose();
		res.writeHead(204);
		res.end();
	}

	private createSession(): McpGatewaySession {
		if (this.sessions.size >= MAX_SESSIONS) {
			this.sessions.values().next().value?.dispose();
		}
		const id = generateUuid();
		const session = new McpGatewaySession(id, this.logService, () => {
			if (this.sessions.delete(id)) {
				this.notify({ kind: 'disconnected' });
			}
		}, {
			onDidChangeTools: this._onDidChangeTools.event,
			onDidChangeResources: Event.None,
			listTools: () => this.broker.listTools(),
			callTool: (name, args) => this.broker.callTool(name, args),
			listResources: async () => [],
			readResource: async uri => { throw new Error(`No resource ${uri}`); },
			listResourceTemplates: async () => [],
		});
		this.sessions.set(id, session);
		return session;
	}

	/** Names the server SAEngine (the gateway session calls itself the editor's gateway) and tells the client about the window. */
	private decorateInitialize(responses: readonly unknown[], message: JsonRpcMessage | JsonRpcMessage[]): void {
		const request = (Array.isArray(message) ? message[0] : message) as { params?: { clientInfo?: { name?: string; version?: string } } };
		const response = responses[0] as IJsonRpcSuccessResponse | undefined;
		const result = response?.result as MCP.InitializeResult | undefined;
		if (!result) {
			return;
		}
		(response as { result: MCP.InitializeResult }).result = {
			...result,
			capabilities: { tools: { listChanged: true } },
			serverInfo: { name: 'saengine', title: 'SAEngine', version: this.options.version ?? '0.0.0' },
			instructions: this.options.instructions,
		};
		const client = request.params?.clientInfo;
		this.notify({ kind: 'connected', client: client?.name ? `${client.name}${client.version ? ` ${client.version}` : ''}` : undefined });
	}

	private notify(event: ISaengineAiClientEvent): void {
		this.broker.clientEvent(event).catch(error => this.logService.warn(`[saengineAi] could not tell the window: ${error}`));
	}

	private respondError(res: http.ServerResponse, status: number, message: string): void {
		res.writeHead(status, { 'Content-Type': 'application/json' });
		res.end(JSON.stringify({ jsonrpc: '2.0', error: { code: status, message } }));
	}

	override dispose(): void {
		for (const session of [...this.sessions.values()]) {
			session.dispose();
		}
		this.sessions.clear();
		this.server?.close();
		this.server?.closeAllConnections();
		this.server = undefined;
		if (this.options.connectionFile) {
			fs.unlink(this.options.connectionFile).catch(() => { /* already gone */ });
		}
		super.dispose();
	}
}

function header(req: http.IncomingMessage, name: string): string | undefined {
	const value = req.headers[name];
	return Array.isArray(value) ? value[0] : value;
}

async function readBody(req: http.IncomingMessage): Promise<string | undefined> {
	const chunks: Buffer[] = [];
	let size = 0;
	for await (const chunk of req) {
		const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
		size += buffer.byteLength;
		if (size > MAX_BODY) {
			return undefined;
		}
		chunks.push(buffer);
	}
	return Buffer.concat(chunks).toString('utf8');
}

/**
 * The shared process's side: one server per window that asks for it, stopped when the window asks
 * or goes away. Tool calls go back to the window that owns the server.
 */
export class SaengineAiChannel extends Disposable implements IServerChannel<string> {

	private readonly servers = new Map<string, SaengineAiServer>();

	constructor(
		private readonly ipcServer: IPCServer<string>,
		private readonly logService: ILogService,
	) {
		super();
		this._register(ipcServer.onDidRemoveConnection(connection => this.stop(connection.ctx)));
	}

	listen<T>(_ctx: string, event: string): Event<T> {
		throw new Error(`Invalid listen: ${event}`);
	}

	async call<T>(ctx: string, command: string, arg?: unknown): Promise<T> {
		switch (command) {
			case 'start': return await this.start(ctx, (arg ?? {}) as ISaengineAiStartOptions) as T;
			case 'stop': this.stop(ctx); return undefined as T;
			case 'info': return this.servers.get(ctx)?.info as T;
			case 'toolsChanged': this.servers.get(ctx)?.toolsChanged(); return undefined as T;
			case 'httpPost': return await this.httpPost(ctx, arg as ISaengineAiHttpRequest) as T;
			case 'cancelHttp': this.requests.get(`${ctx}/${String(arg)}`)?.abort(); return undefined as T;
		}
		throw new Error(`Invalid call: ${command}`);
	}

	/** The built-in assistant's requests in flight, by window and id. */
	private readonly requests = new Map<string, AbortController>();

	/**
	 * Sends one request of the built-in assistant to its provider (see ISaengineAiHttpRequest).
	 * The key is in the headers and never logged; only the host and the status are.
	 */
	private async httpPost(ctx: string, request: ISaengineAiHttpRequest): Promise<ISaengineAiHttpResponse> {
		const check = checkProviderUrl(request?.url ?? '');
		if (!check.ok) {
			return { status: 0, body: '', error: check.reason };
		}
		const key = `${ctx}/${request.id}`;
		const controller = new AbortController();
		this.requests.set(key, controller);
		const timeout = Math.min(Math.max(request.timeoutMs ?? MAX_PROVIDER_TIMEOUT, 1000), MAX_PROVIDER_TIMEOUT);
		const timer = setTimeout(() => controller.abort(), timeout);
		const host = new URL(request.url).host;
		try {
			const response = await fetch(request.url, {
				method: 'POST',
				headers: { ...request.headers, 'content-type': 'application/json' },
				body: request.body,
				signal: controller.signal,
				redirect: 'error',
			});
			const text = await response.text();
			this.logService.info(`[saengineAi] assistant request to ${host}: ${response.status}`);
			return { status: response.status, body: text.length > MAX_PROVIDER_RESPONSE ? text.slice(0, MAX_PROVIDER_RESPONSE) : text };
		} catch (error) {
			const aborted = controller.signal.aborted;
			this.logService.warn(`[saengineAi] assistant request to ${host} failed: ${aborted ? 'cancelled or timed out' : String(error)}`);
			return { status: 0, body: '', error: aborted ? 'cancelled or timed out' : (error instanceof Error ? error.message : String(error)) };
		} finally {
			clearTimeout(timer);
			this.requests.delete(key);
		}
	}

	private async start(ctx: string, options: ISaengineAiStartOptions): Promise<ISaengineAiServerInfo> {
		const existing = this.servers.get(ctx);
		if (existing) {
			return existing.info;
		}
		const channel: IChannel = this.ipcServer.getChannel(SAENGINE_AI_BROKER_CHANNEL, client => client.ctx === ctx);
		const broker: ISaengineAiBroker = {
			listTools: () => channel.call('listTools'),
			callTool: (name, args) => channel.call('callTool', { name, args }),
			clientEvent: event => channel.call('clientEvent', event),
		};
		const server = new SaengineAiServer(generateToken(), broker, options, this.logService);
		this.servers.set(ctx, server);
		try {
			return await server.start();
		} catch (error) {
			this.stop(ctx);
			throw error;
		}
	}

	private stop(ctx: string): void {
		const server = this.servers.get(ctx);
		if (server) {
			this.servers.delete(ctx);
			server.dispose();
			this.logService.info(`[saengineAi] stopped the server of ${ctx}`);
		}
	}

	override dispose(): void {
		for (const ctx of [...this.servers.keys()]) {
			this.stop(ctx);
		}
		super.dispose();
	}
}
