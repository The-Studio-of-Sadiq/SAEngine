/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { sourceStamp } from '../../../../services/saengineProject/common/partSources.js';
import { IModelNode, IPropertySheet, modelTree, propertySheet } from '../../browser/modelData.js';

suite('SAEngine - Model explorer and properties', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const floorPlan = {
		schema: 'saengine.floorPlan/1',
		grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
		stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3200 }],
		columns: [{ id: 'C1', type: 'C400', at: { x: 'A', y: '1', dx: 100 }, base: 'BASE', top: 'L1', rotation: 90 }],
		beams: [{ id: 'B1', type: 'NOPE', story: 'L1', start: { x: 'A', y: '1' }, end: { x: 'B', y: '1' } }],
		walls: [],
		slabs: [{ id: 'S1', type: 'S150', story: 'L1', boundary: [{ x: 'A', y: '1' }, { x: 'B', y: '1' }, { x: 'B', y: '2' }, { x: 'A', y: '2' }] }],
		footings: [],
	};
	const floorPlanText = JSON.stringify(floorPlan, undefined, '\t');
	const docs = {
		floorPlan,
		floorPlanText,
		objects: {
			objects: [
				{ id: 'C400', name: 'Column 400', kind: 'column', material: 'C24', profile: { shape: 'rectangle', xDim: 400, yDim: 600 } },
				{ id: 'S150', name: 'Slab 150', kind: 'slab', material: 'C24', thickness: 150 },
			],
		},
		materials: { materials: [{ id: 'C24', name: 'Concrete 24 MPa' }] },
		bim: { schema: 'saengine.bim/2', source: { floorPlan: sourceStamp(floorPlanText) }, elements: [{ id: 'C1', source: 'C1', kind: 'column' }] },
	};

	/** The tree as indented lines: label, description and problem marker. */
	function outline(nodes: readonly IModelNode[], depth = 0): string[] {
		return nodes.flatMap(n => [`${'  '.repeat(depth)}${n.label}${n.description ? ` — ${n.description}` : ''}${n.problem ? ' ⚠' : ''}`, ...outline(n.children ?? [], depth + 1)]);
	}

	/** A property sheet as lines. */
	function sheet(value: IPropertySheet | undefined): string[] {
		return value ? [`${value.title} (${value.subtitle})`, ...value.sections.flatMap(s => [`[${s.title}]`, ...s.rows.map(r => `${r.label}: ${r.value}${r.problem ? ' ⚠' : ''}`)]), `actions: ${value.actions.join(', ')}`] : ['none'];
	}

	test('the tree lists grids, stories top-down with their members, types and the building model', () => {
		assert.deepStrictEqual(outline(modelTree(docs)), [
			'Floor Plan',
			'  Grid Lines — 2 × 2',
			'    X (lettered)',
			'      A — 0 mm',
			'      B — 6000 mm',
			'    Y (numbered)',
			'      1 — 0 mm',
			'      2 — 5000 mm',
			'  Stories — 2',
			'    Level 1 — +3200 · 3 members',
			'      Columns — 1',
			'        C1 — C400 · A-1 (+100, +0)',
			'      Beams — 1',
			'        B1 — NOPE · A-1 → B-1 ⚠',
			'      Slabs — 1',
			'        S1 — S150 · A-1, B-1, B-2, A-2',
			'    Base — +0 · 0 members',
			'Object Types — 2',
			'  Column Types — 1',
			'    C400 — Column 400',
			'  Slab Types — 1',
			'    S150 — Slab 150',
			'Building Model — up to date',
			'  Columns — 1',
		]);
	});

	test('property sheets describe members, stories, grid lines and types without editing them', () => {
		assert.deepStrictEqual({
			column: sheet(propertySheet({ kind: 'member', group: 'columns', id: 'C1' }, docs)),
			beam: sheet(propertySheet({ kind: 'member', group: 'beams', id: 'B1' }, docs)),
			slab: sheet(propertySheet({ kind: 'member', group: 'slabs', id: 'S1' }, { ...docs, floorPlanText: '{}' })),
			story: sheet(propertySheet({ kind: 'story', id: 'L1' }, docs)),
			grid: sheet(propertySheet({ kind: 'gridLine', axis: 'x', label: 'B' }, docs)),
			type: sheet(propertySheet({ kind: 'objectType', id: 'C400' }, docs)),
			gone: sheet(propertySheet({ kind: 'member', group: 'columns', id: 'C9' }, docs)),
		}, {
			column: [
				'C1 (Column)',
				'[Placement]',
				'Location: A-1 (+100, +0)  (x 100, y 0)',
				'From: Base (+0)',
				'To: Level 1 (+3200)',
				'Height: 3200 mm',
				'Rotation: 90°',
				'[Object Type]',
				'Type: C400',
				'Name: Column 400',
				'Material: Concrete 24 MPa (C24)',
				'Section: Rectangle 400 × 600 mm',
				'[Building Model]',
				'Element: Built and up to date',
				'actions: showInFloorPlan, editObjectType',
			],
			beam: [
				'B1 (Beam)',
				'[Placement]',
				'Start: A-1  (x 0, y 0)',
				'End: B-1  (x 6000, y 0)',
				'Length: 6000 mm',
				'Story: Level 1 (+3200)',
				'[Object Type]',
				'Type: Unknown object type \'NOPE\' ⚠',
				'[Building Model]',
				'Element: Not in the building model yet (update it) ⚠',
				'actions: showInFloorPlan',
			],
			slab: [
				'S1 (Slab)',
				'[Placement]',
				'Story: Level 1 (+3200)',
				'Corners: A-1, B-1, B-2, A-2',
				'Area: 30 m²',
				'[Object Type]',
				'Type: S150',
				'Name: Slab 150',
				'Material: Concrete 24 MPa (C24)',
				'Thickness: 150 mm',
				'[Building Model]',
				'Element: Not in the building model yet (update it) ⚠',
				'actions: showInFloorPlan, editObjectType',
			],
			story: [
				'Level 1 (Story)',
				'[Level]',
				'ID: L1',
				'Elevation: 3200 mm',
				'Height below: 3200 mm',
				'Story above: —',
				'[Members on the Plan]',
				'Columns: 1',
				'Beams: 1',
				'Walls: 0',
				'Slabs: 1',
				'Footings: 0',
				'actions: showInFloorPlan, editGrids',
			],
			grid: [
				'B (X grid line)',
				'[Grid Line]',
				'Position: 6000 mm',
				'From previous: A: 6000 mm',
				'To next: —',
				'actions: editGrids',
			],
			type: [
				'C400 (Object type (column))',
				'[Object Type]',
				'Name: Column 400',
				'Material: Concrete 24 MPa (C24)',
				'Section: Rectangle 400 × 600 mm',
				'Placed members: 1',
				'actions: editObjectType',
			],
			gone: ['none'],
		});
	});
});
