/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { addComponentLink, componentContextKey, IComponentStates, isUsable, readComponentStatus, releasesPage, setupComponents } from '../../common/components.js';
import { runningVersion } from '../../common/updateCheck.js';

suite('SAEngine - installer components', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('re-running the setup keeps the installed components and adds the new one', () => {
		const states: IComponentStates = {
			energyplus: { state: 'missing' },
			librecad: { state: 'installed', path: 'C:\\SAEngine\\resources\\librecad\\LibreCAD.exe' },
			libredwg: { state: 'elsewhere', path: 'C:\\tools\\dwg2dxf.exe' },
			ai: { state: 'installed', path: 'C:\\SAEngine\\resources\\app\\extensions\\copilot' },
			git: { state: 'missing' },
			collaboration: { state: 'elsewhere', path: 'C:\\Users\\a\\.saengine\\extensions\\tunnel-forwarding' },
		};
		// Inno Setup's /COMPONENTS= is the whole selection: LibreCAD must stay in it; LibreDWG found
		// elsewhere was never installed by the setup and stays out.
		assert.deepStrictEqual(setupComponents(states, 'energyplus'), ['energyplus', 'librecad', 'ai']);
		assert.deepStrictEqual(setupComponents(states, 'libredwg'), ['librecad', 'libredwg', 'ai']);
		assert.deepStrictEqual(setupComponents({ ...states, librecad: { state: 'unknown' }, ai: { state: 'missing' } }, 'energyplus'), ['energyplus']);
	});

	test('reads the backend answer', () => {
		assert.deepStrictEqual(readComponentStatus({ state: 'installed', path: 'C:\\a\\energyplus.exe' }), { state: 'installed', path: 'C:\\a\\energyplus.exe' });
		assert.deepStrictEqual(readComponentStatus({ state: 'missing', path: 'x' }), { state: 'missing' });
		assert.deepStrictEqual(readComponentStatus({ state: 'bogus' }), { state: 'unknown' });
		assert.deepStrictEqual(readComponentStatus(undefined), { state: 'unknown' });
	});

	test('the releases page of the releases API URL', () => {
		assert.strictEqual(releasesPage('https://api.github.com/repos/The-Studio-of-Sadiq/SAEngine/releases?per_page=20'), 'https://github.com/The-Studio-of-Sadiq/SAEngine/releases');
		assert.strictEqual(releasesPage('https://example.com/releases'), undefined);
		assert.strictEqual(releasesPage(undefined), undefined);
	});

	test('the running version', () => {
		assert.strictEqual(runningVersion({ version: '1.108.0', saengineVersion: '0.0.47-alpha.8' }), '0.0.47-alpha.8');
		assert.strictEqual(runningVersion({ version: '1.108.0' }), '1.108.0');
	});

	test('extension components: context keys, usable states and the Add Component link', () => {
		assert.strictEqual(componentContextKey('git'), 'saengine.component.git');
		assert.strictEqual(addComponentLink('git'), 'command:saengine.components.add?%5B%22git%22%5D');
		assert.strictEqual(isUsable({ state: 'installed' }), true);
		assert.strictEqual(isUsable({ state: 'elsewhere', path: 'x' }), true);
		assert.strictEqual(isUsable({ state: 'missing' }), false);
		assert.strictEqual(isUsable({ state: 'unknown' }), false);
	});
});
