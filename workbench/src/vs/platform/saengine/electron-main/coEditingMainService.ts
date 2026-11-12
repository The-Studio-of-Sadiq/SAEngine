/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { userInfo } from 'os';
import type { WebsocketProvider } from 'y-websocket';
import type * as Yjs from 'yjs';
import { Emitter } from '../../../base/common/event.js';
import { Disposable } from '../../../base/common/lifecycle.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { ILogService } from '../../log/common/log.js';
import { CoEditingConnection, DEFAULT_RELAY_PORT, ICoEditingConnectionChange, ICoEditingJoined, ICoEditingJoinRequest, ICoEditingPeople, ICoEditingPerson, ICoEditingRelayInfo, ICoEditingRemoteText, ISaengineCoEditingService, personColor, relayUrlProblem } from '../common/coEditing.js';
import { formatJson, IJsonDocs, Json, jsonDocs, parseJson } from '../node/coEditingDoc.js';
import { loadCoEditingLibs } from '../node/coEditingLibs.js';
import { CoEditingRelay } from '../node/coEditingRelay.js';

/** The origin of this window's own edits in the Yjs document. */
const LOCAL = Symbol('local');

interface IUserState {
	readonly name: string;
	readonly color: string;
	readonly selection: readonly string[];
}

interface ISession {
	readonly id: string;
	readonly doc: Yjs.Doc;
	readonly provider: WebsocketProvider;
	readonly name: string;
	/** The window's text as last seen (sent by it or sent to it). */
	text: string;
	/** The room's state has arrived. */
	synced: boolean;
}

/** See {@link ISaengineCoEditingService}. */
export class SaengineCoEditingMainService extends Disposable implements ISaengineCoEditingService {

	declare readonly _serviceBrand: undefined;

	private readonly _onDidChangeRemote = this._register(new Emitter<ICoEditingRemoteText>());
	readonly onDidChangeRemote = this._onDidChangeRemote.event;
	private readonly _onDidChangePeople = this._register(new Emitter<ICoEditingPeople>());
	readonly onDidChangePeople = this._onDidChangePeople.event;
	private readonly _onDidChangeConnection = this._register(new Emitter<ICoEditingConnectionChange>());
	readonly onDidChangeConnection = this._onDidChangeConnection.event;

	private readonly sessions = new Map<string, ISession>();
	private relay: CoEditingRelay | undefined;
	private docs: IJsonDocs | undefined;

	constructor(@ILogService private readonly logService: ILogService) {
		super();
	}

	async join(request: ICoEditingJoinRequest): Promise<ICoEditingJoined> {
		const problem = relayUrlProblem(request.relayUrl);
		if (problem) {
			throw new Error(`The co-editing relay address is not a ws:// or wss:// address: ${request.relayUrl}`);
		}
		const libs = await loadCoEditingLibs();
		const docs = this.docs ??= jsonDocs(libs.Y);
		const id = generateUuid();
		const name = request.name.trim() || defaultName();
		const doc = new libs.Y.Doc();
		const provider = new libs.WebsocketProvider(request.relayUrl.trim().replace(/\/+$/, ''), request.room, doc, {
			// `ws` in place of the browser's WebSocket (the main process has none of its own).
			WebSocketPolyfill: libs.WebSocket as unknown as typeof globalThis.WebSocket,
			disableBc: true,
			maxBackoffTime: 10_000,
		});
		const session: ISession = { id, doc, provider, name, text: request.text, synced: false };
		this.sessions.set(id, session);
		const user: IUserState = { name, color: personColor(doc.clientID), selection: [] };
		provider.awareness.setLocalStateField('user', user);

		provider.on('status', ({ status }: { status: CoEditingConnection }) => {
			this._onDidChangeConnection.fire({ session: id, connection: status });
		});
		provider.on('sync', (synced: boolean) => {
			if (!synced || session.synced) {
				return;
			}
			session.synced = true;
			const local = parseJson(session.text);
			const room = docs.readJson(doc, local);
			if (room === undefined) {
				// The first one in the part: the room starts from this window's part file.
				if (local !== undefined) {
					docs.writeJson(doc, local, LOCAL);
				}
			} else {
				this.sendRemote(session, room);
			}
		});
		doc.on('update', (_update: Uint8Array, origin: unknown) => {
			if (origin === LOCAL || !session.synced) {
				return;
			}
			const merged = docs.readJson(doc, parseJson(session.text));
			if (merged !== undefined) {
				this.sendRemote(session, merged);
			}
		});
		provider.awareness.on('change', () => this.firePeople(session));
		this.logService.info(`[saengine.coEditing] joined ${request.room} at ${request.relayUrl}`);
		return { session: id, name };
	}

	private sendRemote(session: ISession, merged: Json): void {
		const text = formatJson(merged, session.text);
		if (text === session.text || sameAsJson(text, session.text)) {
			return;
		}
		session.text = text;
		this._onDidChangeRemote.fire({ session: session.id, text });
	}

	private firePeople(session: ISession): void {
		const people: ICoEditingPerson[] = [];
		for (const [clientId, state] of session.provider.awareness.getStates()) {
			const user = (state as { user?: Partial<IUserState> }).user;
			if (clientId === session.doc.clientID || !user) {
				continue;
			}
			people.push({
				id: clientId,
				name: typeof user.name === 'string' ? user.name : String(clientId),
				color: typeof user.color === 'string' ? user.color : personColor(clientId),
				selection: Array.isArray(user.selection) ? user.selection.filter((s): s is string => typeof s === 'string') : [],
			});
		}
		this._onDidChangePeople.fire({ session: session.id, people });
	}

	async update(sessionId: string, text: string): Promise<void> {
		const session = this.sessions.get(sessionId);
		if (!session || text === session.text) {
			return;
		}
		session.text = text;
		if (!session.synced) {
			return; // sent when the room's state has arrived (an empty room takes it)
		}
		const json = parseJson(text);
		if (json !== undefined && this.docs) {
			this.docs.writeJson(session.doc, json, LOCAL);
		}
	}

	async setSelection(sessionId: string, ids: readonly string[]): Promise<void> {
		const session = this.sessions.get(sessionId);
		if (!session) {
			return;
		}
		const user = session.provider.awareness.getLocalState()?.user as IUserState | undefined;
		session.provider.awareness.setLocalStateField('user', { ...user, name: session.name, selection: ids.slice(0, 500) });
	}

	async leave(sessionId: string): Promise<void> {
		const session = this.sessions.get(sessionId);
		if (!session) {
			return;
		}
		this.sessions.delete(sessionId);
		session.provider.awareness.setLocalState(null);
		session.provider.destroy();
		session.doc.destroy();
	}

	async hostRelay(port: number = DEFAULT_RELAY_PORT): Promise<ICoEditingRelayInfo> {
		if (!this.relay) {
			const relay = new CoEditingRelay(await loadCoEditingLibs());
			await relay.start(port);
			this.relay = relay;
			this.logService.info(`[saengine.coEditing] relay hosted on port ${relay.port}`);
		}
		return this.info(this.relay);
	}

	async stopRelay(): Promise<void> {
		const relay = this.relay;
		this.relay = undefined;
		await relay?.stop();
	}

	async relayInfo(): Promise<ICoEditingRelayInfo | undefined> {
		return this.relay ? this.info(this.relay) : undefined;
	}

	private info(relay: CoEditingRelay): ICoEditingRelayInfo {
		const port = relay.port ?? DEFAULT_RELAY_PORT;
		return { port, urls: CoEditingRelay.addresses(port), localUrl: `ws://127.0.0.1:${port}`, rooms: relay.roomCount, connections: relay.connectionCount };
	}

	override dispose(): void {
		for (const id of [...this.sessions.keys()]) {
			void this.leave(id);
		}
		void this.stopRelay();
		super.dispose();
	}
}

function defaultName(): string {
	try {
		return userInfo().username;
	} catch {
		return 'Engineer';
	}
}

function sameAsJson(a: string, b: string): boolean {
	const x = parseJson(a);
	const y = parseJson(b);
	return x !== undefined && y !== undefined && JSON.stringify(x) === JSON.stringify(y);
}
