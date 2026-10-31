/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { DisposableStore } from '../../../../../base/common/lifecycle.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IBorehole, ISoilSample } from '../../browser/soilDocument.js';
import { IGridState, newGridState, SoilGrid } from '../../browser/soilGrid.js';
import { SampleSheet } from '../../browser/soilSheet.js';

/** A synthetic borehole with one stratum and no tests yet. */
function borehole(): IBorehole {
	return {
		id: 'BH-1', x: 0, y: 0, waterTable: 1500, depth: 30000,
		layers: [{ top: 0, bottom: 30000, description: 'Grey silty clay', soilType: 'clay', uscs: 'CL' }],
		spt: [],
		samples: [],
	};
}

function key(target: Element, k: string, shiftKey = false): void {
	target.dispatchEvent(new KeyboardEvent('keydown', { key: k, shiftKey, bubbles: true, cancelable: true }));
}

/**
 * The soil editor's samples sheet as it hosts the grid: every write renders the grid again, and
 * the active row is put on the row of the sample the lab panel shows (which follows the active row).
 */
class SamplesHost {
	readonly container = mainWindow.document.body.appendChild(mainWindow.document.createElement('div'));
	readonly state: IGridState = newGridState(['stratum', 'index', 'strength', 'consolidation']);
	readonly store = new DisposableStore();
	grid!: SoilGrid;
	private labSample: ISoilSample | undefined;

	constructor(readonly borehole: IBorehole) {
		this.render();
	}

	render(): void {
		this.store.clear();
		this.container.textContent = '';
		const sheet = new SampleSheet(this.borehole);
		const labRow = sheet.rowOf(this.labSample);
		if (labRow >= 0) {
			this.state.active = { row: labRow, column: this.state.active.column };
		}
		this.grid = this.store.add(new SoilGrid(this.container, {
			sheet, state: this.state, ariaLabel: 'Samples',
			onDidWrite: () => this.render(),
			onDidChangeActiveRow: row => this.labSample = sheet.rowAt(row)?.sample,
		}));
		this.labSample = sheet.rowAt(this.state.active.row)?.sample;
	}

	/** Types a row as an engineer does: each cell, Tab between them, Enter at the end. */
	typeRow(cells: readonly string[]): void {
		cells.forEach((text, i) => {
			const scroller = this.container.querySelector('.soil-grid-scroll')!;
			key(scroller, text[0]);
			const input = this.container.querySelector<HTMLInputElement>('input.soil-grid-editor')!;
			input.value = text;
			key(input, i === cells.length - 1 ? 'Enter' : 'Tab');
		});
	}

	dispose(): void {
		this.store.dispose();
		this.container.remove();
	}
}

suite('SAEngine - Soil grid', () => {

	const disposables = ensureNoDisposablesAreLeakedInTestSuite();

	test('Enter at the end of a row starts the next row, also when the row has a sample (N-S1)', () => {
		const host = new SamplesHost(borehole());
		disposables.add({ dispose: () => host.dispose() });
		// Depth, To, No., Type, Seat, N1, N2: eight rows, 1.5 m apart, as a log sheet gives them.
		for (let i = 1; i <= 8; i++) {
			host.typeRow([(1.5 * i).toFixed(1), (1.5 * i + 0.45).toFixed(2), `D-${i}`, 'SPT', '2', String(i), String(i + 1)]);
		}
		const b = host.borehole;
		assert.strictEqual(b.spt.length, 8);
		assert.deepStrictEqual(b.spt.map(s => s.depth), Array.from({ length: 8 }, (_, i) => 1500 * (i + 1)));
		assert.deepStrictEqual(b.spt.map(s => [s.N1, s.N2]), Array.from({ length: 8 }, (_, i) => [i + 1, i + 2]));
		assert.deepStrictEqual(b.samples.map(s => s.number), Array.from({ length: 8 }, (_, i) => `D-${i + 1}`));
		// The active cell waits in the first column of the new row.
		assert.deepStrictEqual(host.state.active, { row: 8, column: 0 });
	});
});
