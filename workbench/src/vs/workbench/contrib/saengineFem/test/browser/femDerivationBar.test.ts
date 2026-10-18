/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { mepModelStamp, sourceStamp } from '../../../../services/saengineProject/common/partSources.js';
import { derivationState, mepHasContent, recordedSources } from '../../browser/femDerivationBar.js';

suite('SAEngine - FEM derivation', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the source stamps the derivation records in the model description', () => {
		assert.deepStrictEqual({
			derived: [...recordedSources('Derived by SAEngine from the building model and the project settings. Sources: bim=a1; materials=b2; objects=c3; settings=d4')],
			handMade: [...recordedSources('A frame I drew myself')],
			none: [...recordedSources(undefined)],
		}, {
			derived: [['bim', 'a1'], ['materials', 'b2'], ['objects', 'c3'], ['settings', 'd4']],
			handMade: [],
			none: [],
		});
	});

	test('counts the soil report as a source only when the model recorded it', () => {
		const texts = new Map<string, string | undefined>([['bim', 'b'], ['settings', 's'], ['objects', 'o'], ['materials', 'm'], ['soil', 'boreholes']]);
		const sources = `bim=${sourceStamp('b')}; settings=${sourceStamp('s')}; objects=${sourceStamp('o')}; materials=${sourceStamp('m')}`;
		const describe = (soil?: string) => `Derived. Sources: ${sources}${soil === undefined ? '' : `; soil=${sourceStamp(soil)}`}`;
		assert.deepStrictEqual({
			entered: derivationState(describe(), texts).changed,
			current: derivationState(describe('boreholes'), texts).changed,
			placeholderThenBoreholes: derivationState(describe('{"schema": 1, "part": "soil"}'), texts).changed,
			missing: derivationState(describe('boreholes'), new Map([...texts, ['soil', undefined]])).changed,
		}, {
			entered: [],
			current: [],
			placeholderThenBoreholes: ['Soil Report'],
			missing: ['Soil Report'],
		});
	});

	test('counts MEP once recorded, or once it has content for a model derived without it; the substructure once recorded', () => {
		const tank = JSON.stringify({ schema: 'saengine.mep/1', equipment: [{ id: 'EQ1' }], openings: [], shafts: [] });
		const empty = JSON.stringify({ schema: 'saengine.mep/1', equipment: [], openings: [], shafts: [] });
		const texts = new Map<string, string | undefined>([['bim', 'b'], ['settings', 's'], ['objects', 'o'], ['materials', 'm'], ['mep', tank], ['substructure', 'f']]);
		const sources = `bim=${sourceStamp('b')}; settings=${sourceStamp('s')}; objects=${sourceStamp('o')}; materials=${sourceStamp('m')}`;
		assert.deepStrictEqual({
			mepAdded: derivationState(`Sources: ${sources}`, texts).changed,
			mepEmpty: derivationState(`Sources: ${sources}`, new Map([...texts, ['mep', empty]])).changed,
			mepCurrent: derivationState(`Sources: ${sources}; mep=${mepModelStamp(tank)}`, texts).changed,
			mepEdited: derivationState(`Sources: ${sources}; mep=${mepModelStamp(empty)}`, texts).changed,
			springsCurrent: derivationState(`Sources: ${sources}; mep=${mepModelStamp(tank)}; substructure=${sourceStamp('f')}`, texts).changed,
			springsEdited: derivationState(`Sources: ${sources}; mep=${mepModelStamp(tank)}; substructure=${sourceStamp('g')}`, texts).changed,
			mepHasContent: [mepHasContent(tank), mepHasContent(empty), mepHasContent('{"schema": 1, "part": "mep"}'), mepHasContent(undefined)],
		}, {
			mepAdded: ['MEP'],
			mepEmpty: [],
			mepCurrent: [],
			mepEdited: ['MEP'],
			springsCurrent: [],
			springsEdited: ['Substructure'],
			mepHasContent: [true, false, false, false],
		});
	});

	test('stamps only what the analysis model takes from MEP, as the Python side does', () => {
		// The same text and stamp as python/tests/test_integration_e56.py::test_mep_stamp_matches_the_workbench.
		const text = '{"schema": "saengine.mep/1", "contentsAs": "fluid", "equipment": [{"id": "EQ1", "name": "Tank Ø2", "x": 1.0, "y": 2500.5, "operatingWeight": 1e-7, "impact": 0.000001, "rotation": 2.5e22, "big": 1e21, "neg": -0.0}], "openings": [{"id": "OP1", "service": "DN100 drain", "diameter": 100}], "shafts": [], "ifcModels": [{"path": "07 MEP/a.ifc", "visible": true}]}';
		const relabelled = text.replace('Tank Ø2', 'Roof tank').replace('"visible": true', '"visible": false');
		assert.deepStrictEqual({
			stamp: mepModelStamp(text),
			labelsAndIfcIgnored: mepModelStamp(relabelled) === mepModelStamp(text),
			moved: mepModelStamp(text.replace('2500.5', '2600')) === mepModelStamp(text),
			notJson: mepModelStamp('{') === sourceStamp('{'),
		}, {
			stamp: '27130defec6c8086d3157e357806649a4ec265d2',
			labelsAndIfcIgnored: true,
			moved: false,
			notJson: true,
		});
	});

	test('stamps the HVAC plant and the electrical equipment, not the ducts or labels, as the Python side does', () => {
		// The same text and stamp as python/tests/test_services_integration.py::test_mep_stamp_takes_the_plant_and_equipment.
		const text = '{"schema": "saengine.mep/1", "equipment": [], "hvac": {"system": "vrf", "plant": [{"id": "ODU1", "kind": "vrfOutdoor", "story": "L1", "x": 1800, "y": 1500.5, "name": "x"}], "ducts": [{"id": "D1", "story": "BASE", "path": [[0, 0], [1, 1]]}]}, "electrical": {"supply": {"transformerType": "dry"}, "equipment": [{"id": "TX1", "kind": "transformer", "story": "BASE", "x": 3000, "y": -3000}]}}';
		assert.deepStrictEqual({
			stamp: mepModelStamp(text),
			plantMoved: mepModelStamp(text.replace('1500.5', '1600')) === mepModelStamp(text),
			typeChanged: mepModelStamp(text.replace('"dry"', '"oil"')) === mepModelStamp(text),
			ductMoved: mepModelStamp(text.replace('[[0, 0], [1, 1]]', '[[0, 0], [2, 2]]')) === mepModelStamp(text),
			relabelled: mepModelStamp(text.replace('"name": "x"', '"name": "y"')) === mepModelStamp(text),
		}, {
			stamp: '71aa261edebd5ae64a6f6214c92ca19c3a97322c',
			plantMoved: false,
			typeChanged: false,
			ductMoved: true,
			relabelled: true,
		});
	});

	test('stamps the plumbing\'s overhead tanks, not its ground tanks, as the Python side does', () => {
		// The same text and stamps as python/tests/test_plumbing_integration.py::test_mep_stamp_of_the_plumbing_tanks_matches_the_workbench.
		const text = '{"schema": "saengine.mep/1", "equipment": [], "plumbing": {"stories": [{"story": "L1"}], "tanks": [{"id": "T1", "kind": "overhead", "story": "L3", "x": 9500, "y": 2500.5, "length": 2200}, {"id": "SEP1", "kind": "septic", "x": 1, "y": 2}]}}';
		assert.deepStrictEqual({
			stamp: mepModelStamp(text),
			overheadMoved: mepModelStamp(text.replace('2500.5', '2600')) === mepModelStamp(text),
			groundMoved: mepModelStamp(text.replace('"x": 1,', '"x": 5,')) === mepModelStamp(text),
			none: mepModelStamp('{"schema": "saengine.mep/1", "equipment": []}'),
		}, {
			stamp: '9f99e0976f7ef4f8b747aba3e8cb4e054ea1c3ed',
			overheadMoved: false,
			groundMoved: true,
			none: '93870af7da97116c102a976ef591387cb469432b',
		});
	});
});
