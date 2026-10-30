/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { boqMaterialsStamp, groundLevelStamp, sourceStamp } from '../../../../services/saengineProject/common/partSources.js';
import { boqComputeArgs, boqProblems, changedSources, displayQuantity, formatQuantity, IBoqDocument, IBoqItem, parseBoq, quantityText, toCsv, totalledItems, totalRows, totals, unitLabel } from '../../browser/boqDocument.js';

suite('SAEngine - Bill of quantities', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const document: IBoqDocument = {
		schema: 'saengine.boq/1',
		source: { bim: sourceStamp('{"a": 1}\n'), objects: sourceStamp('o'), materials: sourceStamp('m') },
		items: [
			{
				code: 'C.01', group: 'concrete', description: 'Concrete C24.1 in columns', quantity: 2.048, unit: 'm3',
				byStory: { L1: 2.048 },
				breakdown: [{ element: 'C1', story: 'L1', quantity: 1.024 }, { element: 'C2', story: 'L1', quantity: 1.024 }],
			},
			{ code: 'C.02', group: 'concrete', description: 'Concrete C24.1 in "beams", ground', quantity: 3, unit: 'm3', breakdown: [] },
		],
		notes: [],
	};

	test('the substructure and the settings count as sources once the bill records them', () => {
		const texts = (extra: [string, string][]) => new Map([['bim', '{"a": 1}\n'], ['objects', 'o'], ['materials', 'm'], ...extra]);
		const settings = '{"foundation": {"groundLevel": -150, "allowableBearing": 150}}';
		const measured: IBoqDocument = { ...document, source: { ...document.source, substructure: sourceStamp('s'), settings: groundLevelStamp(settings) } };
		assert.deepStrictEqual({
			before: changedSources(document, texts([['substructure', 's'], ['settings', settings]])),
			current: changedSources(measured, texts([['substructure', 's'], ['settings', settings]])),
			// Only the ground level of the settings counts: a new qa leaves the bill current.
			otherSetting: changedSources(measured, texts([['substructure', 's'], ['settings', '{"foundation": {"groundLevel": -150.0, "allowableBearing": 400}, "x": 1}']])),
			changed: changedSources(measured, texts([['substructure', 's2'], ['settings', '{"foundation": {"groundLevel": -300}}']])),
			invalid: changedSources(measured, texts([['substructure', 's'], ['settings', '{']])),
			missing: changedSources(measured, texts([])),
			// The same stamps as saengine.library.bim.ground_level_stamp(-150.0) and (0.0).
			python: [groundLevelStamp(settings), groundLevelStamp('{}')],
			args: boqComputeArgs(texts([['substructure', 's']])),
			noBim: boqComputeArgs(new Map([['objects', 'o']])),
		}, {
			before: ['substructure'],
			current: [],
			otherSetting: [],
			changed: ['substructure', 'settings'],
			invalid: ['settings'],
			missing: ['substructure', 'settings'],
			python: ['eb7f0d0d5faa4ccf9f9d13fbdda0529448065fda', 'fe329f8351df78af4c4980a95d5ca6d0310b7ccd'],
			args: { args: { bimText: '{"a": 1}\n', objectsText: 'o', materialsText: 'm', substructureText: 's', settingsText: undefined, mepText: undefined, architectureText: undefined }, missing: [] },
			noBim: { missing: ['Building Model', 'Materials'] },
		});
	});

	test('MEP counts as a source once the bill records it; sleeves are counted whole', () => {
		const mep = '{"schema": "saengine.mep/1", "openings": [{"id": "OP1"}]}';
		const texts = new Map([['bim', '{"a": 1}\n'], ['objects', 'o'], ['materials', 'm'], ['mep', mep]]);
		const measured: IBoqDocument = { ...document, source: { ...document.source, mep: sourceStamp(mep) } };
		assert.deepStrictEqual({
			before: changedSources(document, texts),
			current: changedSources(measured, texts),
			edited: changedSources(measured, new Map([...texts, ['mep', '{}']])),
			args: boqComputeArgs(texts).args?.mepText,
			count: formatQuantity(3, 'nr'),
		}, {
			before: ['mep'],
			current: [],
			edited: ['mep'],
			args: mep,
			count: '3',
		});
	});

	test('reads a measured bill, tells which sources changed, totals and exports it', () => {
		assert.deepStrictEqual({
			parsed: parseBoq(JSON.stringify(document))?.items.length,
			placeholder: parseBoq('{"schema": 1, "part": "boq"}'),
			invalid: parseBoq('{'),
			current: changedSources(document, new Map([['bim', '{"a": 1}\r\n'], ['objects', 'o'], ['materials', 'm']])),
			changed: changedSources(document, new Map([['bim', '{"a": 2}'], ['objects', 'o']])),
			never: changedSources(undefined, new Map([['bim', ''], ['objects', 'o'], ['materials', 'm']])),
			totals: totals(document.items),
			csv: toCsv(document).split('\r\n'),
		}, {
			parsed: 2,
			placeholder: undefined,
			invalid: undefined,
			current: [],
			changed: ['bim', 'materials'],
			never: ['bim', 'objects', 'materials'],
			totals: [{ unit: 'm3', total: 5.048 }],
			csv: [
				'Row,Code,Group,Description,Element,Story,Detail,Item Quantity,Element Quantity,Unit,Rate,Amount',
				'item,C.01,concrete,Concrete C24.1 in columns,,,,2.048,,m3,,',
				'element,C.01,concrete,Concrete C24.1 in columns,C1,L1,,,1.024,m3',
				'element,C.01,concrete,Concrete C24.1 in columns,C2,L1,,,1.024,m3',
				'item,C.02,concrete,"Concrete C24.1 in ""beams"", ground",,,,3,,m3,,',
				'',
			],
		});
	});

	test('the materials total their cement in kg only; bags are shown as bags', () => {
		const item = (kind: string, quantity: number, unit: IBoqItem['unit']): IBoqItem => ({ code: 'MT.01', group: 'materials', description: kind, quantity, unit, kind, byStory: {}, breakdown: [] });
		const items = [item('cement', 9724.062, 'kg'), item('bags', 194.481, 'bag'), item('sand', 476.948, 'cft'), item('stone', 953.895, 'cft'), item('water', 4862.031, 'l')];
		assert.deepStrictEqual({
			totals: totals(totalledItems('materials', items)),
			units: ['kg', 'bag', 'cft', 'l'].map(unitLabel),
		}, {
			totals: [{ unit: 'kg', total: 9724.062 }],
			units: ['kg', 'bags', 'cft', 'l'],
		});
	});

	test('groups total only like with like', () => {
		const item = (group: IBoqItem['group'], kind: string, description: string, quantity: number, unit: IBoqItem['unit']): IBoqItem => ({ code: 'X.01', group, description, quantity, unit, kind, byStory: {}, breakdown: [] });
		const materials = [
			item('materials', 'cement', 'Cement (OPC)', 100, 'kg'), item('materials', 'cement', 'Cement (PCC)', 50, 'kg'),
			item('materials', 'bags', 'Cement (OPC) in 50 kg bags', 2, 'bag'), item('materials', 'sand', 'Sand (fine aggregate)', 10, 'cft'),
			item('materials', 'stone', 'Stone chips (coarse aggregate)', 20, 'cft'),
		];
		const mep = [item('mep', 'sleeve', 'Sleeves through beams', 4, 'nr'), item('mep', 'riser', 'Risers', 12, 'm')];
		const concrete = [item('concrete', 'column', 'Concrete in columns', 1.5, 'm3'), item('concrete', 'beam', 'Concrete in beams', 2.5, 'm3')];
		assert.deepStrictEqual({
			materials: totalRows('materials', materials),
			mep: totalRows('mep', mep),
			concrete: totalRows('concrete', concrete),
			earthwork: totalRows('earthwork', concrete),
		}, {
			materials: [{ label: 'Cement', unit: 'kg', total: 150 }],
			mep: [],
			concrete: [{ unit: 'm3', total: 4 }],
			earthwork: [],
		});
	});

	test('quantities in feet on request; an incomplete bill has problems', () => {
		assert.deepStrictEqual({
			metric: displayQuantity(1, 'm3', false),
			cft: quantityText(1, 'm3', true),
			sft: quantityText(1, 'm2', true),
			rft: quantityText(1, 'm', true),
			kg: quantityText(1, 'kg', true),
			problems: boqProblems({ ...document, problems: ['No reinforcement measured'] }),
			none: boqProblems(document),
		}, {
			metric: { quantity: 1, unit: 'm3' },
			cft: '35.31 cft',
			sft: '10.76 sft',
			rft: '3.28 rft',
			kg: '1 kg',
			problems: ['No reinforcement measured'],
			none: [],
		});
	});
	test('quantities are grouped in thousands, masses whole, bags rounded up (N-Q5)', () => {
		assert.deepStrictEqual({
			kg: formatQuantity(623434.39, 'kg'),
			bags: formatQuantity(12468.69, 'bag'),
			wholeBags: formatQuantity(12.0000000001, 'bag'),
			volume: formatQuantity(1234.5678, 'm3'),
			cft: formatQuantity(-1234567.891, 'cft'),
			plain: formatQuantity(623434.39, 'kg', false),
		}, {
			kg: '623,434',
			bags: '12,469',
			wholeBags: '12',
			volume: '1,234.568',
			cft: '-1,234,567.89',
			plain: '623434',
		});
	});

	test('a material nothing uses leaves the bill current (N-Q3)', () => {
		const materials = (extra: object[]) => JSON.stringify({ schema: 'saengine.materials/1', materials: [{ id: 'C25', name: 'Concrete', density: 2400.0, alpha: 0.00001 }, ...extra] }, undefined, '	');
		const text = materials([]);
		const measured: IBoqDocument = { ...document, source: { ...document.source, materials: boqMaterialsStamp(text, ['C25']), materialIds: ['C25'] as unknown as string } };
		const texts = (m: string) => new Map([['bim', '{"a": 1}
'], ['objects', 'o'], ['materials', m]]);
		assert.deepStrictEqual({
			current: changedSources(measured, texts(text)),
			unusedAdded: changedSources(measured, texts(materials([{ id: 'FE500', name: 'Steel' }]))),
			usedEdited: changedSources(measured, texts(text.replace('Concrete', 'Concrete 25'))),
			// the Python side (saengine.boq.quantities.materials_stamp) stamps the same text
			stamped: JSON.stringify({ ids: ['C25'], materials: [{ id: 'C25', density: 2400.0, alpha: 0.00001 }] }),
		}, {
			current: [],
			unusedAdded: [],
			usedEdited: ['materials'],
			stamped: '{"ids":["C25"],"materials":[{"id":"C25","density":2400,"alpha":0.00001}]}',
		});
	});

	test('the architecture is a source of the bill once it has a wall or a room', () => {
		const walls = JSON.stringify({ schema: 'saengine.architecture/1', walls: [{ id: 'W1' }] });
		const base = { bim: sourceStamp('b'), objects: sourceStamp('o'), materials: sourceStamp('m') };
		const texts = new Map<string, string | undefined>([['bim', 'b'], ['objects', 'o'], ['materials', 'm'], ['architecture', walls]]);
		const bill = (source: { readonly [part: string]: string }): IBoqDocument => ({ schema: 'saengine.boq/1', source, items: [] } as unknown as IBoqDocument);
		assert.deepStrictEqual({
			added: changedSources(bill(base), texts),
			none: changedSources(bill(base), new Map([...texts, ['architecture', undefined]])),
			current: changedSources(bill({ ...base, architecture: sourceStamp(walls) }), texts),
			edited: changedSources(bill({ ...base, architecture: sourceStamp('{}') }), texts),
			args: boqComputeArgs(texts).args?.architectureText === walls,
		}, { added: ['architecture'], none: [], current: [], edited: ['architecture'], args: true });
	});
});
