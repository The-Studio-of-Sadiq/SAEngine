/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type * as Yjs from 'yjs';
import type * as Decoding from 'lib0/decoding';
import type * as Encoding from 'lib0/encoding';
import type * as Awareness from 'y-protocols/awareness';
import type * as Sync from 'y-protocols/sync';
import type * as YWebsocket from 'y-websocket';
import type * as Ws from 'ws';

/**
 * The co-editing packages (Yjs, its protocols and WebSocket provider, all MIT, and `ws`), loaded
 * the first time co-editing is used, so they cost nothing at startup. One instance of each: Yjs
 * types must come from the same module to merge.
 */
export interface ICoEditingLibs {
	readonly Y: typeof Yjs;
	readonly decoding: typeof Decoding;
	readonly encoding: typeof Encoding;
	readonly awareness: typeof Awareness;
	readonly sync: typeof Sync;
	readonly WebsocketProvider: typeof YWebsocket.WebsocketProvider;
	readonly WebSocket: typeof Ws.WebSocket;
	readonly WebSocketServer: typeof Ws.WebSocketServer;
}

let loading: Promise<ICoEditingLibs> | undefined;

export function loadCoEditingLibs(): Promise<ICoEditingLibs> {
	loading ??= (async () => {
		const [Y, decoding, encoding, awareness, sync, yWebsocket, ws] = await Promise.all([
			import('yjs'),
			import('lib0/decoding'),
			import('lib0/encoding'),
			import('y-protocols/awareness'),
			import('y-protocols/sync'),
			import('y-websocket'),
			import('ws'),
		]);
		return {
			Y, decoding, encoding, awareness, sync,
			WebsocketProvider: yWebsocket.WebsocketProvider,
			WebSocket: ws.WebSocket ?? ws.default,
			WebSocketServer: ws.WebSocketServer ?? (ws.default as unknown as { Server: typeof Ws.WebSocketServer }).Server,
		};
	})();
	return loading;
}
