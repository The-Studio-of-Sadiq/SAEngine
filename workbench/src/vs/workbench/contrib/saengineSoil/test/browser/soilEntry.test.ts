/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { BOREHOLE_FIELDS, IBorehole, ISoilLayer, ISoilReport, newBorehole, newSoilReport, parseField } from '../../browser/soilDocument.js';
import { canCreate, DEFAULT_VIEW, editBoreholeEntry, ENTRY_STEPS, entryProblems, entryStepOf, firstStepWithError, goToStep, newBoreholeEntry, nextStep, shownProblems } from '../../browser/soilEntry.js';
import { appendSoilPatterns, depthScale, renderBoreholeLog } from '../../browser/soilLog.js';
import { StrataSheet } from '../../browser/soilSheet.js';

/** A synthetic deep borehole: layers of 5 m down to `depth` m, an SPT every 1.5 m. */
function deepBorehole(id: string, depth: number): IBorehole {
	const layers: ISoilLayer[] = [];
	for (let top = 0; top < depth; top += 5) {
		layers.push({ top: top * 1000, bottom: Math.min(depth, top + 5) * 1000, description: 'Grey silty fine sand', soilType: top < 10 ? 'clay' : 'sand' });
	}
	const spt = [];
	for (let d = 1.5; d <= depth; d += 1.5) {
		spt.push({ depth: Math.round(d * 1000), N1: 5 + Math.round(d / 3), N2: 6 + Math.round(d / 3) });
	}
	return { id, x: 0, y: 0, waterTable: 1500, depth: depth * 1000, layers, spt, samples: [] };
}

function reportWith(...boreholes: IBorehole[]): ISoilReport {
	return { ...newSoilReport(), boreholes };
}

suite('SAEngine - Soil borehole entry', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('opens on the log; the entry screen follows the log sheet: details, strata, SPT and lab', () => {
		assert.deepStrictEqual({
			view: DEFAULT_VIEW,
			steps: ENTRY_STEPS.map(s => s.step),
			after: [nextStep('details', 1), nextStep('strata', 1), nextStep('tests', 1), nextStep('details', -1)],
			stepOf: ['id', 'depth', 'layers', 'layers.2.bottom', 'spt.0.N1', 'samples.1.depth', undefined].map(entryStepOf),
		}, {
			view: 'log',
			steps: ['details', 'strata', 'tests'],
			after: ['strata', 'tests', undefined, undefined],
			stepOf: ['details', 'details', 'strata', 'strata', 'tests', 'tests', 'details'],
		});
	});

	test('a new borehole starts empty, on its details, and cannot be created until it is filled in', () => {
		const report = reportWith(deepBorehole('BH-1', 30));
		const borehole = newBorehole(report);
		report.boreholes.push(borehole);
		const entry = newBoreholeEntry(1);
		const problems = entryProblems(report, 1);
		const strata = new StrataSheet(borehole, 1);
		const freshDetails = shownProblems(entry, problems).map(p => p.message);
		goToStep(entry, 'strata');
		assert.deepStrictEqual({
			entry: [entry.isNew, entry.snapshot],
			// No invented layer: the strata sheet has no rows, only the row to type a new one into.
			content: [borehole.depth, borehole.waterTable, borehole.layers.length, borehole.spt.length, borehole.samples.length, strata.rowCount()],
			problems: problems.map(p => `${p.step} ${p.path}`),
			// A fresh form is not red all over: what is missing shows once the step is left.
			freshDetails,
			detailsAfterLeaving: shownProblems(entry, problems, 'details').map(p => p.message),
			canCreate: canCreate(problems),
			goTo: firstStepWithError(problems),
		}, {
			entry: [true, undefined],
			content: [undefined, undefined, 0, 0, 0, 0],
			problems: ['details depth', 'strata layers'],
			freshDetails: [],
			detailsAfterLeaving: ['Enter the termination depth: how deep the borehole was drilled.'],
			canCreate: false,
			goTo: 'details',
		});
	});

	test('says what is wrong in plain words, at the step that fixes it', () => {
		const borehole: IBorehole = {
			id: 'BH-7', x: 0, y: 0, depth: 10000,
			layers: [
				{ top: 0, bottom: 4000, description: '', soilType: 'clay' },
				{ top: 4000, bottom: 7000, description: '', soilType: 'silt' },
				{ top: 7000, bottom: 12000, description: '', soilType: 'sand' },
			],
			spt: [{ depth: 1500, N1: 2, N2: 3 }, { depth: 3000, seat: 1 }],
			samples: [],
		};
		const report = reportWith(borehole);
		const problems = entryProblems(report, 0);
		assert.deepStrictEqual({
			messages: problems.map(p => `${p.step} ${p.severity}: ${p.message}`),
			canCreate: canCreate(problems),
			goTo: firstStepWithError(problems),
		}, {
			messages: [
				'strata error: Layer 3 ends at 12 m, below the termination depth 10 m.',
				'tests error: The SPT at 3 m has no blow count: give N1 and N2 (or N, or mark the refusal).',
			],
			canCreate: false,
			goTo: 'strata',
		});
	});

	test('takes boreholes of 75 m and 150 m with no depth limit, and draws them to their depth', () => {
		const depth = BOREHOLE_FIELDS.find(f => f.key === 'depth')!;
		const report = reportWith(deepBorehole('BH-75', 75), deepBorehole('BH-150', 150));
		const container = mainWindow.document.createElement('div');
		appendSoilPatterns(container, 'test');
		const log = renderBoreholeLog(container, report, report.boreholes[0], { width: 700, height: 600, patternPrefix: 'test' });
		const ticks = [...log.querySelectorAll('.soil-tick[text-anchor=end]')].map(t => t.textContent);
		assert.deepStrictEqual({
			typed: [parseField(depth, '75'), parseField(depth, '150'), parseField(depth, '200')],
			problems: [entryProblems(report, 0), entryProblems(report, 1)],
			scales: [depthScale(9000, 400), depthScale(75000, 600), depthScale(150000, 600)],
			// The 75 m log grows past the 600 px it was given (16 px per m) and scrolls, ticked every 5 m.
			logHeight: Number(log.getAttribute('height')) >= 75 * 16,
			depthTicks: ticks.filter(t => ['0', '5', '70', '75', '80'].includes(t ?? '')),
			strata: log.querySelectorAll('.soil-stratum').length,
		}, {
			typed: [{ value: 75000 }, { value: 150000 }, { value: 200000 }],
			problems: [[], []],
			scales: [{ maxM: 9, scale: 400 / 9, step: 1 }, { maxM: 80, scale: 16, step: 5 }, { maxM: 160, scale: 16, step: 5 }],
			logHeight: true,
			depthTicks: ['0', '5', '70', '75', '80'],
			strata: 15,
		});
	});

	test('an edit keeps the borehole as it was, for Cancel', () => {
		const borehole = deepBorehole('BH-1', 12);
		const entry = editBoreholeEntry(0, borehole, 'tests');
		borehole.depth = 15000;
		assert.deepStrictEqual({
			isNew: entry.isNew,
			step: entry.step,
			restored: (JSON.parse(entry.snapshot!) as IBorehole).depth,
		}, { isNew: false, step: 'tests', restored: 12000 });
	});
});
