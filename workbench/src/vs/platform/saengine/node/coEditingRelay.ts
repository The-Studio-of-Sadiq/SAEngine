/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { IncomingMessage } from 'http';
import { networkInterfaces } from 'os';
import type { WebSocket, WebSocketServer } from 'ws';
import type { Awareness } from 'y-protocols/awareness';
import type * as Yjs from 'yjs';
import { ICoEditingLibs } from './coEditingLibs.js';

/*
 * The co-editing relay: the y-websocket protocol (sync and awareness messages) over WebSocket, so
 * SAEngine's own sessions and any y-websocket client can use it. Each room (the URL's path) keeps
 * one Yjs document while anyone is in it, so a late joiner gets the current state; an empty room
 * is dropped, and the next engineer starts it from their part file again. Nothing is stored.
 */

const MESSAGE_SYNC = 0;
const MESSAGE_AWARENESS = 1;
const PING_INTERVAL = 30_000;
/** The longest room name: `saengine/<project key>/<part path>` (part folders have spaces). */
const MAX_ROOM_LENGTH = 300;

/** A room name the relay accepts: printable, not too long, no `..` segment. */
export function validRoom(name: string): boolean {
	return name.length > 0 && name.length <= MAX_ROOM_LENGTH && !/[\u0000-\u001f\u007f]/.test(name) && !name.split('/').includes('..');
}

interface IRoom {
	readonly doc: Yjs.Doc;
	readonly awareness: Awareness;
	/** Each connection and the awareness client ids it controls. */
	readonly connections: Map<WebSocket, Set<number>>;
}

function send(connection: WebSocket, message: Uint8Array): void {
	if (connection.readyState !== connection.OPEN) {
		return;
	}
	connection.send(message, error => {
		if (error) {
			connection.close();
		}
	});
}

export class CoEditingRelay {

	private server: WebSocketServer | undefined;
	private readonly rooms = new Map<string, IRoom>();
	private pingTimer: ReturnType<typeof setInterval> | undefined;
	private readonly alive = new WeakSet<WebSocket>();

	constructor(private readonly libs: ICoEditingLibs) { }

	get port(): number | undefined {
		const address = this.server?.address();
		return typeof address === 'object' && address ? address.port : undefined;
	}

	get roomCount(): number {
		return this.rooms.size;
	}

	get connectionCount(): number {
		let count = 0;
		for (const room of this.rooms.values()) {
			count += room.connections.size;
		}
		return count;
	}

	/** Listens on every network interface of this computer (the office network). */
	start(port: number, host = '0.0.0.0'): Promise<number> {
		if (this.server) {
			return Promise.resolve(this.port!);
		}
		return new Promise<number>((resolve, reject) => {
			const server = new this.libs.WebSocketServer({ port, host, maxPayload: 64 * 1024 * 1024 });
			server.once('error', reject);
			server.once('listening', () => {
				server.off('error', reject);
				server.on('error', () => { /* a failed connection; the server stays up */ });
				this.server = server;
				this.pingTimer = setInterval(() => this.ping(), PING_INTERVAL);
				resolve(this.port!);
			});
			server.on('connection', (connection, request) => this.connect(connection, request));
		});
	}

	async stop(): Promise<void> {
		if (this.pingTimer) {
			clearInterval(this.pingTimer);
			this.pingTimer = undefined;
		}
		const server = this.server;
		this.server = undefined;
		for (const room of this.rooms.values()) {
			for (const connection of room.connections.keys()) {
				connection.terminate();
			}
			room.awareness.destroy();
			room.doc.destroy();
		}
		this.rooms.clear();
		if (server) {
			await new Promise<void>(resolve => server.close(() => resolve()));
		}
	}

	/** The `ws://` addresses of this computer on its networks (IPv4, not the loopback). */
	static addresses(port: number): string[] {
		const urls: string[] = [];
		for (const entries of Object.values(networkInterfaces())) {
			for (const entry of entries ?? []) {
				if (entry.family === 'IPv4' && !entry.internal) {
					urls.push(`ws://${entry.address}:${port}`);
				}
			}
		}
		return urls;
	}

	private ping(): void {
		for (const room of this.rooms.values()) {
			for (const connection of room.connections.keys()) {
				if (!this.alive.has(connection)) {
					connection.terminate();
					continue;
				}
				this.alive.delete(connection);
				connection.ping();
			}
		}
	}

	private room(name: string): IRoom {
		const { Y, encoding, sync: syncProtocol, awareness: awarenessProtocol, WebSocket: WebSocketClass } = this.libs;
		let room = this.rooms.get(name);
		if (!room) {
			const doc = new Y.Doc({ gc: true });
			const awareness = new awarenessProtocol.Awareness(doc);
			awareness.setLocalState(null);
			const created: IRoom = { doc, awareness, connections: new Map() };
			doc.on('update', (update: Uint8Array) => {
				const encoder = encoding.createEncoder();
				encoding.writeVarUint(encoder, MESSAGE_SYNC);
				syncProtocol.writeUpdate(encoder, update);
				const message = encoding.toUint8Array(encoder);
				for (const connection of created.connections.keys()) {
					send(connection, message);
				}
			});
			awareness.on('update', ({ added, updated, removed }: { added: number[]; updated: number[]; removed: number[] }, origin: unknown) => {
				const changed = [...added, ...updated, ...removed];
				const controlled = origin instanceof WebSocketClass ? created.connections.get(origin) : undefined;
				if (controlled) {
					added.forEach(id => controlled.add(id));
					removed.forEach(id => controlled.delete(id));
				}
				const encoder = encoding.createEncoder();
				encoding.writeVarUint(encoder, MESSAGE_AWARENESS);
				encoding.writeVarUint8Array(encoder, awarenessProtocol.encodeAwarenessUpdate(awareness, changed));
				const message = encoding.toUint8Array(encoder);
				for (const connection of created.connections.keys()) {
					send(connection, message);
				}
			});
			this.rooms.set(name, created);
			room = created;
		}
		return room;
	}

	private connect(connection: WebSocket, request: IncomingMessage): void {
		let name: string;
		try {
			name = decodeURIComponent((request.url ?? '/').split('?')[0].replace(/^\/+/, ''));
		} catch {
			name = '';
		}
		if (!validRoom(name)) {
			connection.close(1008, 'invalid room');
			return;
		}
		connection.binaryType = 'arraybuffer';
		const room = this.room(name);
		room.connections.set(connection, new Set());
		this.alive.add(connection);
		connection.on('pong', () => this.alive.add(connection));
		connection.on('message', (data: ArrayBuffer | Buffer) => {
			try {
				this.receive(room, connection, new Uint8Array(data instanceof ArrayBuffer ? data : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)));
			} catch {
				connection.close(1007, 'invalid message');
			}
		});
		connection.on('close', () => this.disconnect(name, room, connection));

		// Start the exchange: what this room has (step 1), and who is in it.
		const { encoding, sync: syncProtocol, awareness: awarenessProtocol } = this.libs;
		const encoder = encoding.createEncoder();
		encoding.writeVarUint(encoder, MESSAGE_SYNC);
		syncProtocol.writeSyncStep1(encoder, room.doc);
		send(connection, encoding.toUint8Array(encoder));
		const states = room.awareness.getStates();
		if (states.size > 0) {
			const awarenessEncoder = encoding.createEncoder();
			encoding.writeVarUint(awarenessEncoder, MESSAGE_AWARENESS);
			encoding.writeVarUint8Array(awarenessEncoder, awarenessProtocol.encodeAwarenessUpdate(room.awareness, [...states.keys()]));
			send(connection, encoding.toUint8Array(awarenessEncoder));
		}
	}

	private receive(room: IRoom, connection: WebSocket, message: Uint8Array): void {
		const { encoding, decoding, sync: syncProtocol, awareness: awarenessProtocol } = this.libs;
		const decoder = decoding.createDecoder(message);
		const type = decoding.readVarUint(decoder);
		if (type === MESSAGE_SYNC) {
			const encoder = encoding.createEncoder();
			encoding.writeVarUint(encoder, MESSAGE_SYNC);
			syncProtocol.readSyncMessage(decoder, encoder, room.doc, connection);
			if (encoding.length(encoder) > 1) {
				send(connection, encoding.toUint8Array(encoder));
			}
		} else if (type === MESSAGE_AWARENESS) {
			awarenessProtocol.applyAwarenessUpdate(room.awareness, decoding.readVarUint8Array(decoder), connection);
		}
	}

	private disconnect(name: string, room: IRoom, connection: WebSocket): void {
		const controlled = room.connections.get(connection);
		room.connections.delete(connection);
		if (controlled?.size) {
			this.libs.awareness.removeAwarenessStates(room.awareness, [...controlled], null);
		}
		if (room.connections.size === 0) {
			room.awareness.destroy();
			room.doc.destroy();
			this.rooms.delete(name);
		}
	}
}
