/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { MCP } from '../../mcp/common/modelContextProtocol.js';

/*
 * The built-in SAEngine MCP server: lets an AI assistant (Claude Code, Claude Desktop, any MCP
 * client) drive one SAEngine window. Off by default. When the engineer allows it, the shared
 * process listens on 127.0.0.1 for that window and every request must carry the window's random
 * token. The tools themselves run in the window (see contrib/saengineAi), so they use the same
 * services, commands and undoable edits as the UI.
 */

/** Channel of the server in the shared process (window -> shared process). */
export const SAENGINE_AI_CHANNEL = 'saengineAi';
/** Channel each window registers for the server to call its tools (shared process -> window). */
export const SAENGINE_AI_BROKER_CHANNEL = 'saengineAiBroker';

/** The URL path of the MCP endpoint (Streamable HTTP). */
export const SAENGINE_AI_PATH = '/mcp';

export interface ISaengineAiStartOptions {
	/** Port to listen on; 0 (default) picks a free one. */
	readonly port?: number;
	/** A file to write the connection details to (dev launch with SAENGINE_AI=1); removed on stop. */
	readonly connectionFile?: string;
	/** Shown to the assistant at initialize: what this window is. */
	readonly instructions?: string;
	/** SAEngine's version, for the server info. */
	readonly version?: string;
}

export interface ISaengineAiServerInfo {
	/** The MCP endpoint, e.g. http://127.0.0.1:51234/mcp. */
	readonly url: string;
	readonly port: number;
	/** The secret the client must send as "Authorization: Bearer <token>". */
	readonly token: string;
}

/** What the server tells the window about its clients (shared process -> window, on the broker). */
export interface ISaengineAiClientEvent {
	readonly kind: 'connected' | 'disconnected' | 'rejected';
	/** The client's own name and version from initialize, e.g. "claude-code 2.1.0". */
	readonly client?: string;
	/** Why a request was rejected (no secret in it). */
	readonly reason?: string;
}

/** The calls the server makes on a window's broker channel. */
export interface ISaengineAiBroker {
	listTools(): Promise<readonly MCP.Tool[]>;
	callTool(name: string, args: Record<string, unknown>): Promise<MCP.CallToolResult>;
	clientEvent(event: ISaengineAiClientEvent): Promise<void>;
}

//#region Request checks (pure, unit tested)

export type RequestCheck =
	| { readonly ok: true }
	| { readonly ok: false; readonly status: number; readonly reason: string };

/** Hosts a local client may address the server by. */
const LOCAL_HOSTS = ['127.0.0.1', 'localhost', '[::1]'];

/**
 * Checks a request's headers before anything else is looked at:
 * - the Host is the loopback address and our port (a DNS-rebinding page has its own host name);
 * - there is no Origin: MCP clients are programs, not web pages, so any browser request is refused
 *   (and no CORS headers are ever sent, so a page cannot read a response either);
 * - the Authorization header carries this window's token, compared in constant time.
 */
export function checkRequest(headers: { readonly host?: string; readonly origin?: string; readonly authorization?: string }, port: number, token: string): RequestCheck {
	if (!isLocalHost(headers.host, port)) {
		return { ok: false, status: 403, reason: 'host' };
	}
	if (headers.origin !== undefined) {
		return { ok: false, status: 403, reason: 'origin' };
	}
	const presented = bearerToken(headers.authorization);
	if (presented === undefined || !constantTimeEquals(presented, token)) {
		return { ok: false, status: 401, reason: 'token' };
	}
	return { ok: true };
}

export function isLocalHost(host: string | undefined, port: number): boolean {
	if (!host) {
		return false;
	}
	const lower = host.toLowerCase();
	return LOCAL_HOSTS.some(name => lower === `${name}:${port}`);
}

/** The token of an "Authorization: Bearer <token>" header. */
export function bearerToken(authorization: string | undefined): string | undefined {
	const match = authorization ? /^Bearer\s+(\S+)\s*$/i.exec(authorization) : null;
	return match ? match[1] : undefined;
}

/**
 * Compares two strings in time that does not depend on where they differ (only the length, which
 * is public: every token has the same length).
 */
export function constantTimeEquals(a: string, b: string): boolean {
	if (a.length === 0 || a.length !== b.length) {
		return false;
	}
	let diff = 0;
	for (let i = 0; i < a.length; i++) {
		diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
	}
	return diff === 0;
}

//#endregion

//#region The built-in assistant's provider requests (window -> shared process)

/**
 * One request of the built-in AI assistant to the model provider the engineer configured,
 * sent by the shared process (Node, no browser CORS) on the window's behalf: `httpPost` on
 * {@link SAENGINE_AI_CHANNEL}. The window decides what is sent and only after the engineer
 * agreed; the shared process only checks the address and forwards the request.
 */
export interface ISaengineAiHttpRequest {
	/** Lets the window cancel it with `cancelHttp`. */
	readonly id: string;
	/** https, or http to this computer only (a self-hosted model). */
	readonly url: string;
	readonly headers: { readonly [name: string]: string };
	/** The JSON body as text. */
	readonly body: string;
	/** Default and largest: {@link MAX_PROVIDER_TIMEOUT}. */
	readonly timeoutMs?: number;
}

export interface ISaengineAiHttpResponse {
	/** HTTP status; 0 when the request did not reach the provider. */
	readonly status: number;
	readonly body: string;
	/** Why it failed before an answer (network, timeout, cancelled, refused address). */
	readonly error?: string;
}

/** Longest a provider request may take [ms]: a long answer with thinking. */
export const MAX_PROVIDER_TIMEOUT = 10 * 60 * 1000;
/** Largest answer read [characters]. */
export const MAX_PROVIDER_RESPONSE = 8 * 1024 * 1024;

/**
 * Whether the assistant may send to `url`: https anywhere, or plain http only to this computer
 * (a self-hosted model on localhost); no other scheme, no credentials in the URL.
 */
export function checkProviderUrl(url: string): { readonly ok: true } | { readonly ok: false; readonly reason: string } {
	let parsed: URL;
	try {
		parsed = new URL(url);
	} catch {
		return { ok: false, reason: 'not a URL' };
	}
	if (parsed.username || parsed.password) {
		return { ok: false, reason: 'credentials in the URL' };
	}
	if (parsed.protocol === 'https:') {
		return { ok: true };
	}
	const host = parsed.hostname.toLowerCase();
	if (parsed.protocol === 'http:' && (host === '127.0.0.1' || host === 'localhost' || host === '[::1]' || host === '::1')) {
		return { ok: true };
	}
	return { ok: false, reason: 'only https, or http to this computer' };
}

//#endregion
