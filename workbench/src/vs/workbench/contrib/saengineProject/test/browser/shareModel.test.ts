/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { coEditingBlocker } from '../../browser/liveCoEditing.js';
import { isServerLocation, lockedByOther, readShareStatus, readSyncResult } from '../../browser/shareModel.js';

suite('SAEngine - shared projects', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the shared state', () => {
		const status = readShareStatus({
			shared: true, location: '\\\\office\\projects\\Tower', kind: 'folder', ahead: 2, behind: -1,
			locks: [{ part: 'floorPlan', title: '05 Floor Plan', user: 'bob', host: 'PC2', since: 1, mine: false }, { title: 'no part' }],
			people: [{ user: 'bob', host: 'PC2', part: 'fem', me: false }, { host: 'x' }],
			problems: ['slow', 3],
		});
		assert.strictEqual(status.ahead, 2);
		assert.strictEqual(status.behind, 0);
		assert.deepStrictEqual(status.locks.map(l => l.part), ['floorPlan']);
		assert.deepStrictEqual(status.people.map(p => p.user), ['bob']);
		assert.deepStrictEqual(status.problems, ['slow']);
		assert.strictEqual(lockedByOther(status, 'floorPlan')?.user, 'bob');
		assert.strictEqual(lockedByOther(status, 'fem'), undefined);
		assert.strictEqual(readShareStatus({ shared: false }).shared, false);
	});

	test('reads a sync result', () => {
		const result = readSyncResult({ state: 'conflicts', conflicts: [{ part: 'settings', title: '02 Project Settings', paths: ['02 Project Settings/project-settings.json'] }] });
		assert.strictEqual(result.state, 'conflicts');
		assert.deepStrictEqual(result.conflicts.map(c => c.part), ['settings']);
		assert.strictEqual(readSyncResult({ state: 'bogus' }).state, 'upToDate');
	});

	test('folder or git server', () => {
		assert.ok(isServerLocation('https://git.office.local/tower.git'));
		assert.ok(isServerLocation('git@git.office.local:tower.git'));
		assert.ok(!isServerLocation('\\\\office\\projects\\Tower'));
		assert.ok(!isServerLocation('S:\\Projects\\Tower'));
	});

	test('live co-editing says what it still needs', () => {
		const ready = { componentUsable: true, provider: true, relayUrl: 'wss://relay.office.local:1234', shared: true };
		assert.strictEqual(coEditingBlocker(ready), undefined);
		assert.strictEqual(coEditingBlocker({ ...ready, componentUsable: false }), 'component');
		assert.strictEqual(coEditingBlocker({ ...ready, provider: false }), 'engine');
		assert.strictEqual(coEditingBlocker({ ...ready, shared: false }), 'notShared');
		assert.strictEqual(coEditingBlocker({ ...ready, relayUrl: '' }), 'relay');
		assert.strictEqual(coEditingBlocker({ ...ready, relayUrl: 'https://cloud.example' }), 'relay');
	});
});
