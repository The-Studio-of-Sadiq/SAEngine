/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../base/common/event.js';
import { createDecorator } from '../../instantiation/common/instantiation.js';

/*
 * Live co-editing (several engineers in one part at the same moment). The Yjs engine (MIT) runs
 * in the main process, where its packages load: one service for every window, reached over IPC.
 * A window binds a part file's text model to a session; the service turns the part's JSON into a
 * shared Yjs document (objects keyed by their ids, so edits of different members merge and the
 * same field edited twice keeps the later edit) and hands the merged JSON back.
 *
 * The relay is the office's own: any SAEngine can host it on the office network (`hostRelay`),
 * or the office runs it on a server. SAEngine ships no relay address and uses no outside cloud.
 */

export const CO_EDITING_CHANNEL = 'saengineCoEditing';

export const ISaengineCoEditingService = createDecorator<ISaengineCoEditingService>('saengineCoEditingService');

/** The relay port SAEngine hosts on unless told otherwise (y-websocket's usual port). */
export const DEFAULT_RELAY_PORT = 1234;

export interface ICoEditingJoinRequest {
	/** The relay (`ws://host:port` or `wss://...`). */
	readonly relayUrl: string;
	/** The room: the shared project's id and the part file's path in the project. */
	readonly room: string;
	/** The engineer's name as the others see it; empty: this computer's user name. */
	readonly name: string;
	/** The part file's text in this window now (its unsaved model). */
	readonly text: string;
}

export interface ICoEditingJoined {
	readonly session: string;
	/** The engineer's name as the others see it. */
	readonly name: string;
}

/** Someone in the same part. */
export interface ICoEditingPerson {
	/** Yjs client id, unique in the room. */
	readonly id: number;
	readonly name: string;
	/** `#rrggbb`, for their highlight. */
	readonly color: string;
	/** The object ids they have selected. */
	readonly selection: readonly string[];
}

export type CoEditingConnection = 'connecting' | 'connected' | 'disconnected';

export interface ICoEditingRemoteText {
	readonly session: string;
	/** The part's merged text: the window applies it to its model as an edit. */
	readonly text: string;
}

export interface ICoEditingPeople {
	readonly session: string;
	/** The others in the part (not this window). */
	readonly people: readonly ICoEditingPerson[];
}

export interface ICoEditingConnectionChange {
	readonly session: string;
	readonly connection: CoEditingConnection;
}

export interface ICoEditingRelayInfo {
	readonly port: number;
	/** Addresses colleagues on the office network connect to (`ws://192.168.1.20:1234`). */
	readonly urls: readonly string[];
	/** The address this computer itself uses. */
	readonly localUrl: string;
	/** Rooms open on the relay and how many are in each. */
	readonly rooms: number;
	readonly connections: number;
}

export interface ISaengineCoEditingService {
	readonly _serviceBrand: undefined;

	/** The merged text of a session changed through someone else's edit. */
	readonly onDidChangeRemote: Event<ICoEditingRemoteText>;
	readonly onDidChangePeople: Event<ICoEditingPeople>;
	readonly onDidChangeConnection: Event<ICoEditingConnectionChange>;

	/**
	 * Joins the part's room. Once the room's state has arrived, a room that already has the part
	 * sends its text (`onDidChangeRemote`); an empty room takes this window's text.
	 */
	join(request: ICoEditingJoinRequest): Promise<ICoEditingJoined>;
	/** This window's text changed (an edit by this engineer). */
	update(session: string, text: string): Promise<void>;
	/** Tells the others what this engineer has selected. */
	setSelection(session: string, ids: readonly string[]): Promise<void>;
	leave(session: string): Promise<void>;

	/** Hosts the relay on this computer for the office network; the running relay if there is one. */
	hostRelay(port?: number): Promise<ICoEditingRelayInfo>;
	stopRelay(): Promise<void>;
	/** The relay this computer hosts, or undefined. */
	relayInfo(): Promise<ICoEditingRelayInfo | undefined>;
}

/** A relay address as the setting takes it, or why it is not one. */
export function relayUrlProblem(url: string): string | undefined {
	const value = url.trim();
	if (!value) {
		return 'empty';
	}
	let parsed: URL;
	try {
		parsed = new URL(value);
	} catch {
		return 'invalid';
	}
	if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') {
		return 'protocol';
	}
	return undefined;
}

/** The room of a part: the shared project's key and the part file's path, with forward slashes. */
export function coEditingRoom(projectKey: string, relativePath: string): string {
	const path = relativePath.replace(/\\/g, '/').replace(/^\/+/, '');
	return `saengine/${projectKey}/${path}`;
}

/** A person's colour from their client id: one of a set readable on light and dark themes. */
export function personColor(id: number): string {
	const colors = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf', '#e377c2', '#8c564b'];
	return colors[Math.abs(id) % colors.length];
}
