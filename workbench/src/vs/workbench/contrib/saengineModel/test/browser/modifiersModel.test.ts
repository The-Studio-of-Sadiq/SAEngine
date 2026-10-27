/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { DisposableStore } from '../../../../../base/common/lifecycle.js';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IContextViewService } from '../../../../../platform/contextview/browser/contextView.js';
import { modifierProblems, unappliedFields } from '../../browser/modifierProblems.js';
import { checkField, commitField, FieldGroup, Framing, ICodeStiffness, IFieldRow, IModifiersView, memberTargets, modifiersView, objectTypeTarget, pruneForKind, readCodeStiffness, resetMembersGroup, setMembersField, setObjectTypeField, setProjectCode, storedFieldProblems } from '../../browser/modifiersModel.js';
import { flushModifierFields, renderModifiers } from '../../browser/modifiersPanel.js';

/** Synthetic stand-in documents (not a project): two concrete types, one steel, one slab. */
const MATERIALS = { materials: [{ id: 'C25', category: 'concrete' }, { id: 'S275', category: 'steel' }, { id: 'BRICK', category: 'masonry' }] };
const OBJECTS = {
	objects: [
		{ id: 'COL', kind: 'column', material: 'C25' },
		{ id: 'BM', kind: 'beam', material: 'C25', modifiers: { J: 0.1 }, designOverwrites: { k3: 1.2 } },
		{ id: 'SB', kind: 'beam', material: 'S275' },
		{ id: 'SL', kind: 'slab', material: 'C25' },
	],
};
const LAYOUT = {
	columns: [{ id: 'C1', type: 'COL', modifiers: { I33: 0.6 } }, { id: 'C2', type: 'COL' }],
	beams: [{ id: 'B1', type: 'BM' }, { id: 'B2', type: 'SB', modifiers: { mass: 0 } }],
	slabs: [{ id: 'S1', type: 'SL' }],
	footings: [{ id: 'F1', type: 'FT' }],
};
/** The BNBC 2020 pack's `concrete.crackedStiffness` (stand-in for the table the pack answers). */
const PACK = { crackedStiffness: { column: 0.7, beam: 0.35, plate: 0.25, wall: 0.35 } };
const CODE: ICodeStiffness = readCodeStiffness({ analysis: {} }, PACK, 'BNBC 2020');

/** A row as one line: "key value|placeholder|source[|!warning]". */
function line(row: IFieldRow): string {
	return `${row.key} ${row.value}|${row.placeholder}|${row.source}${row.various ? '|various' : ''}${row.warning ? '|!' : ''}`;
}

function lines(view: IModifiersView): { modifiers: string[]; overwrites: string[]; reset: [boolean, boolean] } {
	return { modifiers: view.modifiers.map(line), overwrites: view.overwrites.map(line), reset: [view.hasModifiers, view.hasOverwrites] };
}

suite('SAEngine - Stiffness modifiers and design overwrites', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	test('an object type shows its own values and the code pack values greyed', () => {
		const beam = objectTypeTarget(OBJECTS.objects[1], MATERIALS);
		assert.deepStrictEqual(lines(modifiersView('type', [beam], CODE)), {
			modifiers: [
				'A |1|gross', 'As2 |1|gross', 'As3 |1|gross', 'J 0.1|1|this type', 'I22 |0.35|BNBC 2020 cracked (lateral)',
				'I33 |0.35|BNBC 2020 cracked (lateral)', 'mass |1|own mass', 'weight |1|own weight',
			],
			overwrites: ['k3 1.2|auto|this type', 'k2 |auto|1.0 braced, chart if sway', 'Lu3 |auto|clear length', 'Lu2 |auto|clear length', 'Lb |auto|member length'],
			reset: [true, true],
		});
	});

	test('the code values follow the settings, the material and the pack', () => {
		const column = (settings: object, table: object | undefined, material = 'C25') =>
			modifiersView('type', [objectTypeTarget({ id: 'X', kind: 'column', material }, MATERIALS)], readCodeStiffness(settings, table)).modifiers.find(r => r.key === 'I33')!;
		const wall = (wallsCracked: boolean, material = 'C25') =>
			modifiersView('type', [objectTypeTarget({ id: 'W', kind: 'wall', material }, MATERIALS)], readCodeStiffness({ analysis: { wallsCracked, crackedFor: 'all' } }, PACK)).modifiers.map(line);
		assert.deepStrictEqual({
			gross: line(column({ analysis: { stiffness: 'gross' } }, PACK)),
			steel: line(column({}, PACK, 'S275')),
			// As fem/derive.py: masonry takes the cracked factors; a material not found stays gross.
			masonryWall: wall(true, 'BRICK').slice(0, 2),
			missingMaterial: line(column({}, PACK, 'NONE')),
			packNotRead: line(column({}, undefined)),
			wallUncracked: wall(false),
			wallCracked: wall(true),
		}, {
			gross: 'I33 |1|gross (settings)',
			steel: 'I33 |1|gross (not concrete)',
			masonryWall: ['membrane |0.35|code pack cracked', 'bending |0.35|code pack cracked'],
			missingMaterial: 'I33 |1|gross (not concrete)',
			packNotRead: 'I33 |code|code pack cracked (lateral)',
			wallUncracked: ['membrane |0.7|code pack cracked', 'bending |0.7|code pack cracked', 'mass |1|own mass', 'weight |1|own weight'],
			wallCracked: ['membrane |0.35|code pack cracked', 'bending |0.35|code pack cracked', 'mass |1|own mass', 'weight |1|own weight'],
		});
	});

	test('members inherit from their type; a multi-selection shows what they share', () => {
		const one = memberTargets(LAYOUT, OBJECTS, MATERIALS, [{ group: 'beams', id: 'B1' }]);
		const columns = memberTargets(LAYOUT, OBJECTS, MATERIALS, [{ group: 'columns', id: 'C1' }, { group: 'columns', id: 'C2' }]);
		const mixed = memberTargets(LAYOUT, OBJECTS, MATERIALS, [{ group: 'beams', id: 'B2' }, { group: 'slabs', id: 'S1' }, { group: 'footings', id: 'F1' }]);
		const view = (targets: typeof one) => modifiersView('member', targets, CODE);
		assert.deepStrictEqual({
			beam: [view(one).modifiers.find(r => r.key === 'J')!, view(one).overwrites[0]].map(line),
			columns: view(columns).modifiers.filter(r => r.key === 'I33' || r.key === 'I22').map(line),
			columnFraming: line(view(columns).overwrites.find(r => r.key === 'framing')!),
			mixed: lines(view(mixed)),
			count: view(mixed).count,
		}, {
			beam: ['J |0.1|type BM', 'k3 |1.2|type BM'],
			columns: ['I22 |0.7|BNBC 2020 cracked (lateral)', 'I33 |(various)|various|various'],
			columnFraming: 'framing |Auto|from the stability index Q',
			// A beam and a slab share only mass and weight; the footing has none and is left out.
			mixed: { modifiers: ['mass |(various)|various|various', 'weight |1|own weight'], overwrites: [], reset: [true, false] },
			count: 2,
		});
	});

	test('typed values are checked: errors keep the value out, warnings let it in', () => {
		const check = (group: 'modifiers' | 'designOverwrites', key: string, text: string, framing?: 'braced' | 'sway') => {
			const result = checkField(group, key, text, framing);
			return result.error ? 'error' : result.warning ? `${result.value} warning` : String(result.value);
		};
		assert.deepStrictEqual([
			check('modifiers', 'I33', '0.35'),
			check('modifiers', 'I33', '0,35'),
			check('modifiers', 'I33', ''),
			check('modifiers', 'I33', 'abc'),
			check('modifiers', 'I33', '0'),
			check('modifiers', 'I33', '1.5'),
			check('modifiers', 'I33', '12'),
			check('modifiers', 'J', '0.05'),
			check('modifiers', 'mass', '0'),
			check('modifiers', 'mass', '-1'),
			check('designOverwrites', 'k3', '1.2', 'braced'),
			check('designOverwrites', 'k3', '0.8', 'sway'),
			check('designOverwrites', 'k3', '0'),
			check('designOverwrites', 'Lu3', '3.2'),
			check('designOverwrites', 'Lu3', '3200'),
			check('designOverwrites', 'framing', 'sway'),
			check('designOverwrites', 'framing', 'auto'),
		], [
			'0.35', '0.35', 'undefined', 'error', 'error', '1.5 warning', 'error', '0.05 warning', '0 warning', 'error',
			'1.2 warning', '0.8 warning', 'error', '3.2 warning', '3200', 'sway', 'undefined',
		]);
	});

	test('Enter in a box: an untouched "(various)" box keeps every member\'s own value', () => {
		const columns = modifiersView('member', memberTargets(LAYOUT, OBJECTS, MATERIALS, [{ group: 'columns', id: 'C1' }, { group: 'columns', id: 'C2' }]), CODE);
		const various = columns.modifiers.find(r => r.key === 'I33')!;
		const single = modifiersView('member', memberTargets(LAYOUT, OBJECTS, MATERIALS, [{ group: 'columns', id: 'C1' }]), CODE).modifiers.find(r => r.key === 'I33')!;
		assert.deepStrictEqual({
			variousUntouched: commitField(various, ''),
			variousTyped: commitField(various, '0.5'),
			singleUnchanged: commitField(single, '0.6'),
			singleCleared: commitField(single, ''),
			error: !!commitField(various, 'abc').error,
		}, {
			variousUntouched: { unchanged: true },
			variousTyped: { value: 0.5, warning: undefined },
			singleUnchanged: { unchanged: true },
			singleCleared: {},
			error: true,
		});
	});

	test('an edit of many members is one edit of the floor plan; members without the field are skipped', () => {
		const refs = [{ group: 'columns' as const, id: 'C1' }, { group: 'columns' as const, id: 'C2' }, { group: 'slabs' as const, id: 'S1' }];
		const set = setMembersField(LAYOUT, refs, OBJECTS, 'modifiers', 'I33', 0.5);
		const cleared = setMembersField(LAYOUT, refs.slice(0, 1), OBJECTS, 'modifiers', 'I33', undefined);
		const reset = resetMembersGroup(LAYOUT, [{ group: 'beams', id: 'B2' }], OBJECTS, 'modifiers');
		const unchanged = setMembersField(LAYOUT, refs.slice(0, 1), OBJECTS, 'modifiers', 'I33', 0.6);
		const pick = (result: typeof set, group: 'columns' | 'beams' | 'slabs') => result.ok ? (result.layout[group] as object[]) : result.error;
		assert.deepStrictEqual({
			set: [pick(set, 'columns'), pick(set, 'slabs'), set.ok && set.ids.length],
			cleared: pick(cleared, 'columns'),
			reset: pick(reset, 'beams'),
			unchanged: unchanged.ok,
			original: LAYOUT.columns,
		}, {
			set: [[{ id: 'C1', type: 'COL', modifiers: { I33: 0.5 } }, { id: 'C2', type: 'COL', modifiers: { I33: 0.5 } }], [{ id: 'S1', type: 'SL' }], 2],
			cleared: [{ id: 'C1', type: 'COL' }, { id: 'C2', type: 'COL' }],
			reset: [{ id: 'B1', type: 'BM' }, { id: 'B2', type: 'SB' }],
			unchanged: false,
			original: [{ id: 'C1', type: 'COL', modifiers: { I33: 0.6 } }, { id: 'C2', type: 'COL' }],
		});
	});

	test('an object type is changed in place; a new kind keeps only its own fields', () => {
		const item: { [key: string]: unknown } = { id: 'T', kind: 'beam', material: 'C25' };
		setObjectTypeField(item, 'modifiers', 'I33', 0.5);
		setObjectTypeField(item, 'modifiers', 'mass', 0.9);
		setObjectTypeField(item, 'designOverwrites', 'Lb', 3000);
		const asBeam = JSON.parse(JSON.stringify(item));
		item.kind = 'slab';
		pruneForKind(item);
		setObjectTypeField(item, 'modifiers', 'mass', undefined);
		assert.deepStrictEqual({ asBeam, asSlab: item }, {
			asBeam: { id: 'T', kind: 'beam', material: 'C25', modifiers: { I33: 0.5, mass: 0.9 }, designOverwrites: { Lb: 3000 } },
			asSlab: { id: 'T', kind: 'slab', material: 'C25' },
		});
	});

	test('read-only rendering shows own values and the inherited ones greyed', () => {
		const disposables = store.add(new DisposableStore());
		const container = mainWindow.document.createElement('div');
		const view = modifiersView('member', memberTargets(LAYOUT, OBJECTS, MATERIALS, [{ group: 'columns', id: 'C1' }]), CODE);
		renderModifiers(container, view, disposables, { contextViewService: undefined!, apply: () => { }, reset: () => { }, editable: false });
		const rows = [...container.querySelectorAll('.sa-modifiers-row')].map(row => {
			const value = row.querySelector('.sa-modifiers-readonly')!;
			return `${row.querySelector('.sa-modifiers-name')!.textContent}=${value.textContent}${value.classList.contains('inherited') ? ' (inherited)' : ''}`;
		});
		assert.deepStrictEqual({ headings: [...container.querySelectorAll('.sa-modifiers-heading')].map(h => h.textContent), rows: rows.slice(4, 6), framing: rows.at(-1) }, {
			headings: ['Stiffness Modifiers', 'Design Overwrites'],
			rows: ['Inertia minor (I22)=0.7 (inherited)', 'Inertia major (I33)=0.6'],
			framing: 'Framing=Auto (inherited)',
		});
	});
	test('the open project\'s settings and pack fill in what an editor does not pass', () => {
		setProjectCode({ settings: { analysis: { crackedFor: 'all' } }, crackedTable: PACK.crackedStiffness, packName: 'BNBC 2020' });
		try {
			const column = modifiersView('type', [objectTypeTarget({ id: 'X', kind: 'column', material: 'C25' }, MATERIALS)], readCodeStiffness(undefined, undefined));
			const given = modifiersView('type', [objectTypeTarget({ id: 'X', kind: 'column', material: 'C25' }, MATERIALS)], readCodeStiffness({ analysis: { stiffness: 'gross' } }, undefined));
			assert.deepStrictEqual({
				project: line(column.modifiers.find(r => r.key === 'I33')!),
				given: line(given.modifiers.find(r => r.key === 'I33')!),
				note: column.note,
			}, {
				project: 'I33 |0.7|BNBC 2020 cracked',
				given: 'I33 |1|gross (settings)',
				note: 'Empty: the BNBC 2020 cracked factors in every case. A value replaces the factor in every case, gravity and lateral.',
			});
		} finally {
			setProjectCode({});
		}
	});

	test('stored values the checks refuse are problems of the part', () => {
		const objects = { objects: [{ id: 'T1', kind: 'column', modifiers: { I33: -0.5, J: 0.1 }, designOverwrites: { k3: 0, framing: 'wobbly' } }, { id: 'T2', kind: 'beam', modifiers: { A: 'x' } }] };
		const plan = { columns: [{ id: 'C1', modifiers: { I22: 12 } }], beams: [{ id: 'B1', designOverwrites: { Lu3: 3000 } }] };
		assert.deepStrictEqual({
			objects: storedFieldProblems(objects, 'objects').map(p => p.message),
			plan: modifierProblems('floorPlan', plan),
		}, {
			objects: [
				'T1: Inertia major (I33): A stiffness modifier must be more than 0.',
				'T1: k, major axis: Must be more than 0.',
				'T1: Framing: Framing must be Auto, Braced or Sway.',
				'T2: Axial area (A): Not a number.',
			],
			plan: ['C1: Inertia minor (I22): A modifier can be at most 10.'],
		});
	});

	suite('typing in a field', () => {

		const contextViewService = { showContextView: () => ({ close: () => { } }), hideContextView: () => { }, layout: () => { } } as unknown as IContextViewService;
		let container: HTMLElement;
		let applied: string[];
		let panel: DisposableStore | undefined;
		let closed: boolean;

		/** Renders one column's panel as the floor plan does: each store is an edit and a new panel. */
		function render(own: { [key: string]: unknown } = {}): void {
			const layout = { columns: [{ id: 'C2', type: 'COL', ...own }] };
			panel?.dispose();
			panel = new DisposableStore();
			container.textContent = '';
			renderModifiers(container, modifiersView('member', memberTargets(layout, OBJECTS, MATERIALS, [{ group: 'columns', id: 'C2' }]), CODE), panel, {
				contextViewService,
				apply: (group: FieldGroup, key: string, value: number | Framing | undefined) => {
					applied.push(`${key}=${value}`);
					if (!closed) {
						render({ [group]: { [key]: value } });
					}
				},
				reset: () => { },
			});
		}

		function field(key: string): HTMLInputElement {
			return container.querySelector<HTMLInputElement>(`.sa-modifiers-row[data-key="${key}"] input`)!;
		}

		function type(key: string, text: string): void {
			field(key).focus();
			field(key).value = text;
			field(key).dispatchEvent(new Event('input'));
		}

		/** Leaves field `from` for `to` (Tab or a click); the hidden test window fires no focus events itself. */
		function leave(from: string, to: string): void {
			field(from).dispatchEvent(new FocusEvent('blur', { relatedTarget: field(to) }));
			field(to).focus();
		}

		function rowState(key: string): string {
			const row = container.querySelector(`.sa-modifiers-row[data-key="${key}"]`)!;
			return ['dirty', 'invalid', 'applied'].filter(c => row.classList.contains(c)).join(' ') || 'clean';
		}

		function status(): string {
			return container.querySelector('.sa-modifiers-status')!.textContent ?? '';
		}

		setup(() => {
			container = mainWindow.document.createElement('div');
			mainWindow.document.body.appendChild(container);
			applied = [];
			closed = false;
		});

		teardown(() => {
			closed = true;
			panel?.dispose();
			panel = undefined;
			container.remove();
		});

		test('leaving the field stores the value and marks it applied; Tab lands on the next field', () => {
			render();
			type('I33', '0.7');
			const typed = [rowState('I33'), status()];
			leave('I33', 'mass'); // Tab
			assert.deepStrictEqual({ typed, applied, after: [rowState('I33'), status(), field('I33').value], focused: mainWindow.document.activeElement === field('mass') }, {
				typed: ['dirty', 'Not applied yet: Enter or leave the field'],
				applied: ['I33=0.7'],
				after: ['applied', 'Applied', '0.7'],
				focused: true,
			});
		});

		test('Enter stores and keeps the focus; Escape goes back to the stored value', () => {
			render();
			type('I22', '0,5');
			field('I22').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
			const enter = mainWindow.document.activeElement === field('I22');
			type('I22', '0.4');
			field('I22').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
			assert.deepStrictEqual({ applied, enter, value: field('I22').value, state: rowState('I22') }, { applied: ['I22=0.5'], enter: true, value: '0.5', state: 'clean' });
		});

		test('a value that cannot be stored stays, marked, and counts as a problem until corrected', () => {
			render();
			type('I33', '-0.5');
			leave('I33', 'mass');
			const wrong = { applied: [...applied], state: rowState('I33'), status: status(), problems: unappliedFields('floorPlan') };
			type('I33', '0.6');
			leave('I33', 'mass');
			assert.deepStrictEqual({ wrong, applied, problems: unappliedFields('floorPlan') }, {
				wrong: { applied: [], state: 'invalid', status: '1 value cannot be used', problems: ['Inertia major (I33): -0.5: A stiffness modifier must be more than 0.'] },
				applied: ['I33=0.6'],
				problems: [],
			});
		});

		test('a save stores what is typed; closing the panel stores it too', async () => {
			render();
			type('J', '0.2');
			flushModifierFields();
			type('I33', '0.7');
			closed = true;
			panel!.dispose(); // the panel closes (another selection, the editor closed) with the value typed
			container.textContent = '';
			await Promise.resolve();
			assert.deepStrictEqual(applied, ['J=0.2', 'I33=0.7']);
		});

		test('a panel rendered again while typing keeps the text and the caret', () => {
			render();
			type('I33', '0.6');
			render(); // the owner redraws (an edit elsewhere)
			assert.deepStrictEqual({ value: field('I33').value, state: rowState('I33'), focused: mainWindow.document.activeElement === field('I33'), applied }, { value: '0.6', state: 'dirty', focused: true, applied: [] });
		});
	});
});
