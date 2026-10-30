/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { WebContents } from 'electron';
import { validatedIpcMain } from './ipcMain.js';
import { VSBuffer } from '../../../common/buffer.js';
import { Emitter, Event } from '../../../common/event.js';
import { IDisposable, toDisposable } from '../../../common/lifecycle.js';
import { ClientConnectionEvent, IPCServer } from '../common/ipc.js';
import { Protocol as ElectronProtocol, Sender } from '../common/ipc.electron.js';

interface IIPCEvent {
	event: { sender: WebContents };
	message: Buffer | null;
}

function createScopedOnMessageEvent(senderId: number, eventName: string): Event<VSBuffer | null> {
	const onMessage = Event.fromNodeEventEmitter<IIPCEvent>(validatedIpcMain, eventName, (event, message) => ({ event, message }));
	const onMessageFromSender = Event.filter(onMessage, ({ event }) => event.sender.id === senderId);

	return Event.map(onMessageFromSender, ({ message }) => message ? VSBuffer.wrap(message) : message);
}

/** The web contents a client says hello from: its id, and how to send to it. */
export interface IClientWebContents extends Sender {
	readonly id: number;
}

/**
 * The connections of the clients saying hello on `onHello`, whose messages come from
 * `onSenderMessage`. A hello from web contents that already has a connection (a reloaded window)
 * disconnects the old connection.
 */
export function createOnDidClientConnect(clients: Map<number, IDisposable>, onHello: Event<IClientWebContents>, onSenderMessage: (senderId: number, eventName: string) => Event<VSBuffer | null>): Event<ClientConnectionEvent> {
	return Event.map(onHello, webContents => {
		const id = webContents.id;
		const client = clients.get(id);

		client?.dispose();

		const onDidClientReconnect = new Emitter<void>();
		const reconnectDisposable = toDisposable(() => {
			// Dispose only once every listener has the event: an emitter disposed while it delivers
			// stops delivering, and the IPC server would keep the old connection, which then also
			// answers the reloaded window (its streamed replies arriving once more per reload).
			onDidClientReconnect.fire();
			onDidClientReconnect.dispose();
		});
		clients.set(id, reconnectDisposable);

		const onMessage = onSenderMessage(id, 'vscode:message') as Event<VSBuffer>;
		const onDidClientDisconnect = Event.any(Event.signal(onSenderMessage(id, 'vscode:disconnect')), onDidClientReconnect.event);
		Event.once(onDidClientDisconnect)(() => {
			if (clients.get(id) === reconnectDisposable) {
				clients.delete(id);
			}
		});
		const protocol = new ElectronProtocol(webContents, onMessage);

		return { protocol, onDidClientDisconnect };
	});
}

/**
 * An implementation of `IPCServer` on top of Electron `ipcMain` API.
 */
export class Server extends IPCServer {

	private static readonly Clients = new Map<number, IDisposable>();

	private static getOnDidClientConnect(): Event<ClientConnectionEvent> {
		const onHello = Event.fromNodeEventEmitter<WebContents>(validatedIpcMain, 'vscode:hello', ({ sender }) => sender);

		return createOnDidClientConnect(Server.Clients, onHello, createScopedOnMessageEvent);
	}

	constructor() {
		super(Server.getOnDidClientConnect());
	}
}
