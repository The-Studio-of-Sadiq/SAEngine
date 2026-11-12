/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { formatJson, Json, jsonDocs } from '../../node/coEditingDoc.js';
import { loadCoEditingLibs } from '../../node/coEditingLibs.js';
import { CoEditingRelay, validRoom } from '../../node/coEditingRelay.js';

const plan = {
	name: 'Ground floor',
	columns: [
		{ id: 'C1', x: 0, y: 0, b: 300, h: 300 },
		{ id: 'C2', x: 6000, y: 0, b: 300, h: 300 },
	],
	grid: [0, 6000],
};

function waitFor(condition: () => boolean, timeout = 5000): Promise<void> {
	return new Promise((resolve, reject) => {
		const started = Date.now();
		const check = () => {
			if (condition()) {
				resolve();
			} else if (Date.now() - started > timeout) {
				reject(new Error('timed out'));
			} else {
				setTimeout(check, 20);
			}
		};
		check();
	});
}

suite('SAEngine live co-editing', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	// Yjs and its protocols load only under Node (the main process, and the node test run in CI);
	// the Electron renderer test run cannot resolve npm packages, so the suite is skipped there.
	suiteSetup(async function () {
		try {
			await loadCoEditingLibs();
		} catch {
			this.skip();
		}
	});

	test('two engineers editing different members and fields both keep their edits', async () => {
		const { Y } = await loadCoEditingLibs();
		const docs = jsonDocs(Y);
		const a = new Y.Doc();
		const b = new Y.Doc();
		docs.writeJson(a, plan);
		Y.applyUpdate(b, Y.encodeStateAsUpdate(a));

		// A widens C1; B adds C3 and renames the storey, at the same time.
		docs.writeJson(a, { ...plan, columns: [{ ...plan.columns[0], b: 400 }, plan.columns[1]] });
		docs.writeJson(b, { ...plan, name: 'GF', columns: [...plan.columns, { id: 'C3', x: 12000, y: 0, b: 300, h: 300 }] });
		Y.applyUpdate(a, Y.encodeStateAsUpdate(b));
		Y.applyUpdate(b, Y.encodeStateAsUpdate(a));

		const merged: Json = {
			name: 'GF',
			columns: [
				{ id: 'C1', x: 0, y: 0, b: 400, h: 300 },
				{ id: 'C2', x: 6000, y: 0, b: 300, h: 300 },
				{ id: 'C3', x: 12000, y: 0, b: 300, h: 300 },
			],
			grid: [0, 6000],
		};
		assert.deepStrictEqual({ a: docs.readJson(a, plan), b: docs.readJson(b, plan) }, { a: merged, b: merged });
		a.destroy();
		b.destroy();
	});

	test('a member deleted by one engineer stays deleted when the other edits it', async () => {
		const { Y } = await loadCoEditingLibs();
		const docs = jsonDocs(Y);
		const a = new Y.Doc();
		const b = new Y.Doc();
		docs.writeJson(a, plan);
		Y.applyUpdate(b, Y.encodeStateAsUpdate(a));
		docs.writeJson(a, { ...plan, columns: [plan.columns[0]] });
		docs.writeJson(b, { ...plan, columns: [plan.columns[0], { ...plan.columns[1], h: 450 }] });
		Y.applyUpdate(a, Y.encodeStateAsUpdate(b));
		Y.applyUpdate(b, Y.encodeStateAsUpdate(a));
		assert.deepStrictEqual(docs.readJson(b, plan), { ...plan, columns: [plan.columns[0]] });
		a.destroy();
		b.destroy();
	});

	test('the relay takes part paths with spaces, and refuses ..', () => {
		assert.deepStrictEqual(
			['saengine/k/05 Floor Plan/floor-plan.json', 'saengine/k/../x', '', 'a\u0000b'].map(validRoom),
			[true, false, false, false]);
	});

	test('the text keeps the file\'s indentation and final new line', () => {
		assert.strictEqual(formatJson({ a: [1] }, '{\n  "a": []\n}\n'), '{\n  "a": [\n    1\n  ]\n}\n');
		assert.strictEqual(formatJson({ a: 1 }, '{\r\n\t"a": 0\r\n}'), '{\r\n\t"a": 1\r\n}');
	});

	test('through the relay, two engineers see each other\'s edits', async function () {
		this.timeout(20000);
		const libs = await loadCoEditingLibs();
		const docs = jsonDocs(libs.Y);
		const relay = new CoEditingRelay(libs);
		const port = await relay.start(0, '127.0.0.1');
		const url = `ws://127.0.0.1:${port}`;
		// Part folders have spaces in their names.
		const room = 'saengine/test/05 Floor Plan/floor-plan.json';
		const connect = () => {
			const doc = new libs.Y.Doc();
			const provider = new libs.WebsocketProvider(url, room, doc, { WebSocketPolyfill: libs.WebSocket as unknown as typeof globalThis.WebSocket, disableBc: true });
			return { doc, provider };
		};
		const a = connect();
		const b = connect();
		try {
			await waitFor(() => a.provider.synced && b.provider.synced);
			docs.writeJson(a.doc, plan);
			await waitFor(() => docs.readJson(b.doc) !== undefined);
			docs.writeJson(b.doc, { ...plan, columns: [...plan.columns, { id: 'C3', x: 12000, y: 0, b: 300, h: 300 }] });
			docs.writeJson(a.doc, { ...plan, name: 'GF' });
			const expected = { ...plan, name: 'GF', columns: [...plan.columns, { id: 'C3', x: 12000, y: 0, b: 300, h: 300 }] };
			await waitFor(() => JSON.stringify(docs.readJson(a.doc, plan)) === JSON.stringify(expected) && JSON.stringify(docs.readJson(b.doc, plan)) === JSON.stringify(expected));

			// Presence: each sees the other in the room.
			a.provider.awareness.setLocalStateField('user', { name: 'Rahim', color: '#1f77b4', selection: ['C3'] });
			await waitFor(() => [...b.provider.awareness.getStates().values()].some(s => (s as { user?: { name?: string } }).user?.name === 'Rahim'));
			assert.strictEqual(relay.roomCount, 1);
		} finally {
			a.provider.destroy();
			b.provider.destroy();
			a.doc.destroy();
			b.doc.destroy();
			await relay.stop();
		}
	});
});
