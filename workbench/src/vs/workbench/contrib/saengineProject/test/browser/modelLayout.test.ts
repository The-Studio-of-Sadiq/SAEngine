/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { activeTableId, frameOfContainer, ISaengineTableDescriptor, MODEL_LAYOUT_VERSION, modelViewPart, needsModelLayout, SaengineTableRegistry } from '../../browser/modelLayoutModel.js';
import type { ISaengineProject } from '../../../../services/saengineProject/common/saengineProject.js';

/** A stand-in for an element: contains itself and the elements under it. */
class Node {
	constructor(readonly name: string, readonly parent?: Node) { }
	contains(other: Node): boolean {
		for (let node: Node | undefined = other; node; node = node.parent) {
			if (node === this) {
				return true;
			}
		}
		return false;
	}
}

function frame(element: Node): { readonly element: HTMLElement; readonly name: string } {
	return { element: element as unknown as HTMLElement, name: element.name };
}

suite('SAEngine - model layout', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('the model view parts: a special structure plans in its structural model', () => {
		assert.strictEqual(modelViewPart('plan', { type: 'building' }), 'floorPlan');
		assert.strictEqual(modelViewPart('plan', { type: 'structure' }), 'structure');
		assert.strictEqual(modelViewPart('3d', { type: 'building' }), 'bim');
		assert.strictEqual(modelViewPart('analysis', { type: 'structure' }), 'fem');
	});

	test('the layout is set up once per version', () => {
		assert.strictEqual(needsModelLayout(0), true);
		assert.strictEqual(needsModelLayout(MODEL_LAYOUT_VERSION), false);
		assert.strictEqual(needsModelLayout(MODEL_LAYOUT_VERSION + 1), false);
	});

	test('the Properties panel shows the outermost frame of the active editor', () => {
		const pane = new Node('pane');
		const outer = new Node('outer', pane);
		const inner = new Node('inner', new Node('body', outer)); // a compact floor plan inside
		const elsewhere = new Node('elsewhere', new Node('other pane'));
		const frames = [frame(inner), frame(elsewhere), frame(outer)];
		assert.strictEqual(frameOfContainer(frames, pane as unknown as HTMLElement)?.name, 'outer');
		assert.strictEqual(frameOfContainer([frame(elsewhere)], pane as unknown as HTMLElement), undefined);
		assert.strictEqual(frameOfContainer(frames, undefined), undefined);
	});

	test('tables: ordered, per project type, the remembered tab while it is there', () => {
		const registry = new SaengineTableRegistry();
		const table = (id: string, order: number, when?: ISaengineTableDescriptor['when']): ISaengineTableDescriptor => ({ id, order, when, label: () => id, create: () => { throw new Error('not created'); } });
		const results = registry.register(table('results', 30));
		const members = registry.register(table('members', 10, p => p.type !== 'structure'));
		const building = { type: 'building' } as ISaengineProject;
		const structure = { type: 'structure' } as ISaengineProject;
		assert.deepStrictEqual(registry.tablesOf(building).map(d => d.id), ['members', 'results']);
		assert.deepStrictEqual(registry.tablesOf(structure).map(d => d.id), ['results']);
		assert.deepStrictEqual(registry.tablesOf(undefined), []);
		members.dispose();
		results.dispose();
		assert.deepStrictEqual(registry.tablesOf(building), []);
		registry.dispose();

		assert.strictEqual(activeTableId(['members', 'storeys'], 'storeys'), 'storeys');
		assert.strictEqual(activeTableId(['members', 'storeys'], 'results'), 'members');
		assert.strictEqual(activeTableId([], 'members'), undefined);
	});
});
