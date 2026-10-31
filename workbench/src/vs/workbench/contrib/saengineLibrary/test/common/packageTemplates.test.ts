/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { groupPresets, readBuildingTemplates, readStructurePresets } from '../../common/packageTemplates.js';

suite('SAEngine - Package templates', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the presets and groups them by package', () => {
		const presets = readStructurePresets({
			presets: [
				{ package: 'saengine-shapes', packageName: 'SAEngine shapes', name: 'Warren truss 30 m', shape: { kind: 'planeTruss' } },
				{ package: 'saengine-shapes', packageName: 'SAEngine shapes', name: 'Dome', shape: { kind: 'dome' } },
				{ package: 'roofs', packageName: 'Roofs', name: 'Howe 12 m', shape: { kind: 'planeTruss' } },
				{ package: 'roofs', name: 'no shape' },
			],
		});
		assert.deepStrictEqual(groupPresets(presets).map(g => `${g.name}: ${g.presets.map(p => p.name).join(', ')}`), ['SAEngine shapes: Warren truss 30 m, Dome', 'Roofs: Howe 12 m']);
		assert.deepStrictEqual(readStructurePresets(undefined), []);
	});

	test('reads specifications and full templates', () => {
		const templates = readBuildingTemplates({
			templates: [
				{ package: 'saengine-default-building', name: 'Dhaka 6-storey', type: 'spec', spec: { storyCount: 6 } },
				{ package: 'clinic', name: 'Clinic', type: 'archive', path: 'C:/t/template.civil', author: 'A' },
				{ package: 'bad', type: 'archive' },
			],
		});
		assert.deepStrictEqual(templates.map(t => `${t.package}:${t.type}`), ['saengine-default-building:spec', 'clinic:archive']);
	});
});
