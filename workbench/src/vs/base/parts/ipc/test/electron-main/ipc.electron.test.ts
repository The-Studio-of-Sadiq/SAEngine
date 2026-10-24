/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { timeout } from '../../../../common/async.js';
import { VSBuffer } from '../../../../common/buffer.js';
import { Emitter, Event } from '../../../../common/event.js';
import { DisposableStore, IDisposable } from '../../../../common/lifecycle.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../test/common/utils.js';
import { IMessagePassingProtocol, IPCClient, IPCServer, IServerChannel } from '../../common/ipc.js';
import { createOnDidClientConnect, IClientWebContents } from '../../electron-main/ipc.electron.js';

/**
 * One window's web contents and the main process, as Electron's IPC connects them: messages are
 * delivered asynchronously, and a reload keeps the web contents (and its id) for a new page.
 */
class TestWindow implements IDisposable {

	private readonly disposables = new DisposableStore();
	private readonly onHelloEmitter = this.disposables.add(new Emitter<IClientWebContents>());
	readonly onHello = this.onHelloEmitter.event;
	private readonly mainEvents = new Map<string, Emitter<VSBuffer | null>>();
	private page: Emitter<VSBuffer> | undefined;
	private readonly clients: IPCClient[] = [];

	private readonly webContents: IClientWebContents = {
		id: 1,
		send: (_channel, message) => {
			const page = this.page;
			queueMicrotask(() => page?.fire(VSBuffer.wrap(message as Uint8Array)));
		}
	};

	/** The scoped `ipcMain` events of the web contents (`vscode:message`, `vscode:disconnect`). */
	onSenderMessage = (senderId: number, eventName: string): Event<VSBuffer | null> => {
		assert.strictEqual(senderId, this.webContents.id);
		let emitter = this.mainEvents.get(eventName);
		if (!emitter) {
			emitter = this.disposables.add(new Emitter<VSBuffer | null>());
			this.mainEvents.set(eventName, emitter);
		}
		return emitter.event;
	};

	/** Loads a new page in the window (the first load or a reload) and connects it. */
	load(): IPCClient {
		const page = this.page = this.disposables.add(new Emitter<VSBuffer>());
		const protocol: IMessagePassingProtocol = {
			send: message => queueMicrotask(() => this.mainEvents.get('vscode:message')?.fire(message)),
			onMessage: page.event,
		};
		this.onHelloEmitter.fire(this.webContents);
		const client = new IPCClient(protocol, 'window:1');
		this.clients.push(client);
		return client;
	}

	dispose(): void {
		this.clients.forEach(client => client.dispose());
		this.disposables.dispose();
	}
}

suite('IPC, Electron main', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	test('a reloaded window has one connection, which answers once', async () => {
		const window = store.add(new TestWindow());
		const clients = new Map<number, IDisposable>();
		const server = store.add(new IPCServer(createOnDidClientConnect(clients, window.onHello, window.onSenderMessage)));
		const chunks = store.add(new Emitter<string>());
		const channel: IServerChannel<string> = {
			call: () => Promise.reject(new Error('not supported')),
			listen: <T>() => chunks.event as Event<T>,
		};
		server.registerChannel('files', channel);

		window.load();
		await timeout(0);
		window.load(); // reload
		await timeout(0);
		const client = window.load(); // reload again
		await timeout(0);
		assert.strictEqual(server.connections.length, 1);

		const received: string[] = [];
		const listener = client.getChannel('files').listen<string>('readFileStream')(chunk => received.push(chunk));
		await timeout(0);
		chunks.fire('chunk');
		await timeout(0);
		listener.dispose();
		assert.deepStrictEqual(received, ['chunk']);

		clients.forEach(reconnect => reconnect.dispose());
		await timeout(0);
		assert.strictEqual(server.connections.length, 0);
	});
});
