/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { mainWindow } from '../../../../../base/browser/window.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { bearingSummary, BOREHOLE_FIELDS, checkSoilReport, distanceFromSite, duplicateIds, hasLabData, mergeBoreholes, splitError, terminationDepth, choiceLabel, choiceTitle, DESIGN_CHOICES, hasLiquefiable, IBorehole, ISoilReport, LAYER_FIELDS, newBorehole, newSoilReport, nextBoreholeId, parseField, parseSoilReport, PRACTICE_CHOICE, readSoilResults, resultsBasis, siltNeedsPlasticity, siteFlagsOf, SPT_FIELDS, soilSummary } from '../../browser/soilDocument.js';
import { SOIL_BACKEND_OUTPUT } from './soilBackendOutput.js';
import { appendSoilPatterns, niceStep, renderBoreholeLog, renderFence, renderLiquefactionChart } from '../../browser/soilLog.js';

function borehole(id: string, extra: Partial<IBorehole> = {}): IBorehole {
	return {
		id, x: 0, y: 0, waterTable: 1500, depth: 9000,
		layers: [
			{ top: 0, bottom: 3000, description: 'Soft grey silty clay', soilType: 'clay', uscs: 'CL' },
			{ top: 3000, bottom: 9000, description: 'Loose silty fine sand', soilType: 'sand' },
		],
		spt: [{ depth: 1500, N: 3 }, { depth: 4500, N: 8 }, { depth: 7500, N: 14 }],
		samples: [],
		...extra,
	};
}

suite('SAEngine - Soil report', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('reads the placeholder, a report and broken files', () => {
		const report = parseSoilReport(JSON.stringify({ schema: 'saengine.soilReport/1', boreholes: [{ id: 'BH-1', x: 0, y: 0 }], extra: 1 }));
		assert.deepStrictEqual({
			placeholder: parseSoilReport('{"schema": 1, "part": "soil"}').kind,
			empty: parseSoilReport('').kind,
			report: report.kind === 'report' ? { lists: [report.report.boreholes[0].layers, report.report.boreholes[0].spt], kept: report.report.extra, ground: report.report.groundLevel } : undefined,
			invalid: parseSoilReport('{').kind,
			other: parseSoilReport('{"schema": "saengine.bim/2"}').kind,
		}, {
			placeholder: 'placeholder',
			empty: 'placeholder',
			report: { lists: [[], []], kept: 1, ground: 0 },
			invalid: 'error',
			other: 'error',
		});
	});

	test('parses field input in the engineer\'s units', () => {
		const [top] = LAYER_FIELDS;
		const [, n] = SPT_FIELDS;
		const gamma = LAYER_FIELDS.find(f => f.key === 'unitWeight')!;
		const soilType = LAYER_FIELDS.find(f => f.key === 'soilType')!;
		const cu = LAYER_FIELDS.find(f => f.key === 'cu')!;
		const x = BOREHOLE_FIELDS.find(f => f.key === 'x')!;
		assert.deepStrictEqual([
			parseField(top, '1.5'),
			parseField(top, '2,25').error !== undefined,
			parseField(cu, '1,200'),
			parseField(x, '12,000.5'),
			parseField(x, '1,20,000'),
			parseField(cu, '1,2,00').error !== undefined,
			parseField(top, '').error !== undefined,
			parseField(top, '-1').error !== undefined,
			parseField(n, '12'),
			parseField(n, '12.5').error !== undefined,
			parseField(gamma, ''),
			parseField(gamma, '40').error !== undefined,
			parseField(soilType, 'sand'),
			parseField(soilType, 'loam').error !== undefined,
		], [
			{ value: 1500 }, true, { value: 1200 }, { value: 12000500 }, { value: 120000000 }, true, true, true, { value: 12 }, true, {}, true, { value: 'sand' }, true,
		]);
	});

	test('checks the strata, the records and the ids', () => {
		const report: ISoilReport = { ...newSoilReport(), boreholes: [
			borehole('BH-1'),
			borehole('BH-2', { layers: [{ top: 0, bottom: 2000, description: '', soilType: 'clay' }, { top: 2500, bottom: 2400, description: '', soilType: 'sand' }], spt: [{ depth: 12000, N: 30 }, { depth: 12000, N: 31 }] }),
			borehole('BH-2', { layers: [] }),
		] };
		assert.deepStrictEqual(checkSoilReport(report).map(p => `${p.severity} ${p.index} ${p.borehole ?? ''} ${p.path ?? ''}`), [
			'error 1 BH-2 id',
			'error 1 BH-2 layers.1.bottom',
			'error 1 BH-2 layers.1.top',
			'error 1 BH-2 spt.0.depth',
			'error 1 BH-2 spt.1.depth',
			'error 1 BH-2 spt.1.depth',
			'error 2 BH-2 id',
			'warning 2 BH-2 layers',
			// One note for the report: no borehole reaches the 30 m of Table 6.2.13.
			'warning undefined  ',
		]);
	});

	test('checks the layers and the water table against the termination depth, in plain words', () => {
		const report: ISoilReport = { ...newSoilReport(), boreholes: [
			borehole('BH-1', { depth: 8000, waterTable: 8500, spt: [{ depth: 1500, N: 3 }] }),
			borehole('BH-2', { depth: undefined, spt: [{ depth: 9500, N: 20 }] }),
		] };
		assert.deepStrictEqual(checkSoilReport(report).map(p => `${p.severity} ${p.index} ${p.path}: ${p.message}`), [
			'error 0 layers.1.bottom: BH-1: layer 2 ends at 9 m, below the termination depth 8 m.',
			'warning 0 waterTable: BH-1: the water table (8.5 m) is below the termination depth 8 m.',
			'error 1 spt.0.depth: BH-2: the SPT at 9.5 m is below the bottom of the borehole (9 m).',
			'warning undefined undefined: No borehole reaches 30 m (the deepest ends at 9.5 m): BNBC 2020 Table 6.2.13 classifies the site by the top 30 m, so the site class is provisional (the last N is carried down to 30 m). Drill one borehole to 30 m to confirm it.',
		]);
	});

	test('reads the results of the backend (real soil_report() output)', () => {
		const results = readSoilResults(SOIL_BACKEND_OUTPUT)!;
		const [bh1, bh2] = results.boreholes!;
		assert.deepStrictEqual({
			siteClass: results.siteClass,
			perBorehole: results.boreholes!.map(b => [b.id, b.siteClass?.class, b.siteClass?.nBar, b.siteClass?.suBar]),
			pga: results.pga,
			pgaSource: results.pgaSource?.startsWith('amax = Z'),
			spt: bh1.spt!.slice(3, 5),
			points: bh1.liquefaction!.points.slice(2, 4).map(p => [p.depth, p.FS, p.liquefiable, p.note]),
			lpi: results.boreholes!.map(b => [b.liquefaction?.LPI, b.liquefaction?.category, hasLiquefiable(b)]),
			layers: bh1.liquefaction!.liquefiableLayers,
			bearing: bh1.bearing!.cells.map(c => [c.B, c.Df, c.qa, c.qBearing, c.qSettlement, c.governs]),
			envelope: results.bearing!.cells.map(c => [c.B, c.Df, c.qa, c.borehole]),
			governing: results.bearing!.governing && bearingSummary(results.bearing!.governing),
			ks: [bh1.ks, bh2.ks, !!bh1.ksMethod],
			piles: bh1.piles!.map(p => [p.top, p.bottom, p.soilType, p.fs, p.qb]),
			notes: results.notes!.length,
		}, {
			siteClass: { class: 'SD', borehole: 'BH-1', nBar: 6.5, suBar: 22, depth: 30000, note: 'SD, the softest of the boreholes (BH-1 SD, BH-2 SD), in the order SA to SE of Table 6.2.13.', provisional: false },
			perBorehole: [['BH-1', 'SD', 6.5, 22], ['BH-2', 'SD', 6.7, 22]],
			pga: 0.37800000000000006,
			pgaSource: true,
			spt: [{ depth: 6000, N: 2, N60: 1.7, N160: 2.2, N160cs: 7.9 }, { depth: 7500, N: 6, N60: 5.2, N160: 6.1, N160cs: 11.7 }],
			points: [[4500, null, false, 'clay: not susceptible (clay-like)'], [6000, 0.27, true, undefined]],
			lpi: [[31.59, 'very high', true], [26.2, 'very high', true]],
			layers: [{ top: 6000, bottom: 11500, soilType: 'silt' }, { top: 11500, bottom: 21000, soilType: 'sand' }],
			bearing: [[1000, 1000, null, null, 35, null], [2000, 1000, null, null, 25.5, null], [1000, 1500, 39.8, 62.7, 39.8, 'settlement'], [2000, 1500, 26.2, 58.5, 26.2, 'settlement']],
			envelope: [[1000, 1000, null, 'BH-1'], [2000, 1000, null, 'BH-1'], [1000, 1500, 39.8, 'BH-1'], [2000, 1500, 26.2, 'BH-1']],
			governing: 'qa 26 kPa at B 2 m, Df 1.5 m',
			ks: [1049, 1129, true],
			piles: [[0, 1500, 'fill', null, null], [1500, 6000, 'clay', 12.1, 143], [6000, 11500, 'silt', 21.5, 280], [11500, 21000, 'sand', 72.6, 799.4], [21000, 30000, 'sand', 63.1, 1807.1]],
			notes: 1,
		});
		assert.deepStrictEqual([readSoilResults(undefined), readSoilResults('x'), readSoilResults({ problems: ['Soil report: not valid JSON'] })?.problems], [undefined, undefined, ['Soil report: not valid JSON']]);
	});

	test('reads the basis, the site class flags and the permissible settlement', () => {
		const backend = SOIL_BACKEND_OUTPUT as { boreholes: Record<string, unknown>[]; siteClass: Record<string, unknown>; methods: Record<string, unknown> };
		const raw = {
			...backend,
			practice: 'bdConsultant',
			design: { liquefactionMethod: 'bnbc2020' },
			methods: { ...backend.methods as object, spt: 'SPT (consultant)' },
			amaxNote: 'amax = 0.378 g (soil report)',
			siteClass: { ...backend.siteClass, flags: [{ class: 'S1', note: '12 m of soft clay with PI 45.', boreholes: ['BH-2'] }, 'S2: liquefiable sand'] },
			boreholes: backend.boreholes.map((b, i) => ({
				...b,
				siteClass: { ...b.siteClass as object, flags: i === 0 ? ['S2: liquefiable sand'] : [] },
				settlement: { B: 2000, L: 2000, Df: 1500, q: 26.2, immediate: 4.04, consolidation: 20.9, total: 24.9, permissible: i === 0 ? { value: 50, framedBuilding: 60, foundation: 'isolated', soil: 'sand', source: 'Table 6.3.8: isolated, RCC, sand' } : undefined },
			})),
			permissibleSettlement: 75,
		};
		const results = readSoilResults(raw)!;
		const plain = readSoilResults(SOIL_BACKEND_OUTPUT)!;
		const design = { ...newSoilReport().design, practice: 'textbook' as const };
		assert.deepStrictEqual({
			flags: results.siteClassFlags,
			settlement: results.boreholes!.map(b => b.settlement),
			project: [results.permissibleSettlement, results.permissibleSettlementSource],
			basis: resultsBasis(design, results),
			plainBasis: resultsBasis(design, plain).map(r => [r.value, r.detail?.startsWith('amax = Z') ? 'Z·S' : r.detail]),
			derived: siteFlagsOf(plain),
			choices: DESIGN_CHOICES.map(c => [c.key, c.defaultValue, c.options.map(o => o.value), choiceTitle(c).split('\n').length]),
			unknown: choiceLabel(PRACTICE_CHOICE, 'other'),
		}, {
			flags: [{ class: 'S1', note: '12 m of soft clay with PI 45.', boreholes: ['BH-2'] }, { class: 'S2', note: 'liquefiable sand', boreholes: ['BH-1'] }],
			settlement: [
				{ B: 2000, Df: 1500, q: 26.2, immediate: 4.04, consolidation: 20.9, total: 24.9, permissible: 50, permissibleSource: 'Table 6.3.8: isolated, RCC, sand' },
				{ B: 2000, Df: 1500, q: 26.2, immediate: 4.04, consolidation: 20.9, total: 24.9, permissible: undefined, permissibleSource: undefined },
			],
			project: [75, undefined],
			basis: [
				{ label: 'Practice', value: 'Bangladesh consultant practice', detail: 'SPT (consultant)' },
				{ label: 'Liquefaction method', value: 'BNBC 2020 Sec 3.9.5', detail: undefined },
				{ label: 'amax', value: '0.378 g', detail: 'amax = 0.378 g (soil report)' },
			],
			plainBasis: [['Textbook', 'as set in the design options'], ['Idriss & Boulanger 2014', 'as set in the design options'], ['0.378 g', 'Z·S']],
			derived: [{ class: 'S2', note: '', boreholes: ['BH-1', 'BH-2'] }],
			choices: [['practice', 'textbook', ['textbook', 'bdConsultant'], 3], ['liquefactionMethod', 'idrissBoulanger2014', ['idrissBoulanger2014', 'bnbc2020'], 3]],
			unknown: 'other',
		});
	});

	test('keeps each borehole\'s own site class flag note', () => {
		const backend = SOIL_BACKEND_OUTPUT as { boreholes: Record<string, unknown>[]; siteClass: Record<string, unknown> };
		const s1 = (from: number, to: number) => ({ class: 'S1', note: `S1 possible: ${to - from} m of soft clay from ${from} to ${to} m.` });
		const raw = {
			...backend,
			// The project's merged flag carries the first borehole's note for both boreholes.
			siteClass: { ...backend.siteClass, flags: [{ ...s1(1, 13), boreholes: ['BH-1', 'BH-2'] }, { class: 'SE', note: 'SE possible: rock at 12 m.', boreholes: ['BH-2'] }] },
			boreholes: backend.boreholes.map((b, i) => ({ ...b, siteClass: { ...b.siteClass as object, flags: [i === 0 ? s1(1, 13) : s1(4, 18)] } })),
		};
		const same = { ...raw, boreholes: backend.boreholes.map(b => ({ ...b, siteClass: { ...b.siteClass as object, flags: [s1(1, 13)] } })) };
		assert.deepStrictEqual([readSoilResults(raw)!.siteClassFlags, readSoilResults(same)!.siteClassFlags], [[
			{ ...s1(1, 13), boreholes: ['BH-1'] },
			{ ...s1(4, 18), boreholes: ['BH-2'] },
			{ class: 'SE', note: 'SE possible: rock at 12 m.', boreholes: ['BH-2'] },
		], [
			{ ...s1(1, 13), boreholes: ['BH-1', 'BH-2'] },
			{ class: 'SE', note: 'SE possible: rock at 12 m.', boreholes: ['BH-2'] },
		]]);
	});

	test('names new boreholes and summarises the report', () => {
		const report: ISoilReport = { ...newSoilReport(), boreholes: [borehole('BH-1'), borehole('BH-3')] };
		const added = newBorehole(report);
		assert.deepStrictEqual({
			next: nextBoreholeId(report),
			added,
			summaries: [soilSummary(newSoilReport()), soilSummary({ ...report, boreholes: [borehole('BH-1')] }), soilSummary(report)],
		}, {
			next: 'BH-2',
			// Nothing made up: no termination depth, no layer, no water table copied from a neighbour.
			added: { id: 'BH-2', x: 10000, y: 0, layers: [], spt: [], samples: [] },
			summaries: ['no boreholes', '1 borehole', '2 boreholes'],
		});
	});

	test('asks whether a silt with no PI or cu is plastic, as the backend treats it', () => {
		const hole = borehole('BH-1', {
			layers: [
				{ top: 0, bottom: 3000, description: '', soilType: 'silt' },
				{ top: 3000, bottom: 6000, description: '', soilType: 'silt', plasticityIndex: 12 },
				{ top: 6000, bottom: 9000, description: '', soilType: 'silt', cu: 0 },
				{ top: 9000, bottom: 12000, description: '', soilType: 'silt' },
				{ top: 12000, bottom: 15000, description: '', soilType: 'silt' },
				{ top: 15000, bottom: 18000, description: '', soilType: 'sand' },
				{ top: 18000, bottom: 21000, description: '', soilType: 'silt' },
			],
			// cu in the fourth layer; only LL in the fifth (no PI without PL); LL and PL below the
			// last layer's top count for it.
			samples: [{ depth: 10000, cu: 30 }, { depth: 12000, liquidLimit: 30 }, { depth: 22000, liquidLimit: 30, plasticLimit: 24 }],
		});
		assert.deepStrictEqual(hole.layers.map(layer => siltNeedsPlasticity(hole, layer)), [true, false, false, false, true, false, false]);
	});

	test('draws the log, the fence and the liquefaction chart', () => {
		const container = mainWindow.document.createElement('div');
		const report: ISoilReport = { ...newSoilReport(), boreholes: [borehole('BH-1'), borehole('BH-2', { groundLevel: -500 })] };
		appendSoilPatterns(container, 'test');
		const log = renderBoreholeLog(container, report, report.boreholes[0], {
			width: 700, height: 400, patternPrefix: 'test',
			result: { id: 'BH-1', spt: [{ depth: 1500, N: 3, N60: 2.8 }, { depth: 4500, N: 8, N60: 7.3 }] },
		});
		const fence = renderFence(container, report, { width: 600, height: 400, patternPrefix: 'test' });
		const chart = renderLiquefactionChart(container, [{ id: 'BH-1', liquefaction: { points: [{ depth: 4500, FS: 0.8 }, { depth: 7500, FS: 1.4 }], liquefiableLayers: [{ top: 3000, bottom: 6000 }] } }], { width: 400, height: 300, maxDepth: 9000 });
		assert.deepStrictEqual({
			patterns: container.querySelectorAll('pattern').length,
			strata: log.querySelectorAll('.soil-stratum').length,
			n: log.querySelectorAll('.soil-n').length,
			n60: log.querySelectorAll('.soil-n60').length,
			water: log.querySelectorAll('.soil-water').length,
			fenceColumns: fence.querySelectorAll('.soil-fence-borehole').length,
			joins: fence.querySelectorAll('.soil-join').length,
			liquefiable: chart.querySelectorAll('.liquefiable').length,
			steps: [niceStep(30, 10), niceStep(7, 10), niceStep(120, 5)],
		}, {
			patterns: 7, strata: 2, n: 3, n60: 2, water: 1, fenceColumns: 2, joins: 2, liquefiable: 1, steps: [5, 1, 50],
		});
	});

	test('imports: duplicate ids replaced, kept both or skipped, never silently', () => {
		const make = () => ({ ...newSoilReport(), boreholes: [borehole('BH-1'), borehole('BH-2')] });
		const incoming = () => [borehole('BH-2', { depth: 12000 }), borehole('BH-3')];
		const replace = make();
		const keep = make();
		const skip = make();
		assert.deepStrictEqual({
			duplicates: duplicateIds(make(), incoming()),
			replace: [mergeBoreholes(replace, incoming(), 'replace'), replace.boreholes.map(b => `${b.id} ${b.depth}`)],
			keep: [mergeBoreholes(keep, incoming(), 'keepBoth'), keep.boreholes.map(b => b.id)],
			skip: [mergeBoreholes(skip, incoming(), 'skip'), skip.boreholes.map(b => `${b.id} ${b.depth}`)],
		}, {
			duplicates: ['BH-2'],
			replace: [{ added: ['BH-3'], replaced: ['BH-2'], renamed: [], skipped: [] }, ['BH-1 9000', 'BH-2 12000', 'BH-3 9000']],
			keep: [{ added: ['BH-3'], replaced: [], renamed: [{ from: 'BH-2', to: 'BH-2-2' }], skipped: [] }, ['BH-1', 'BH-2', 'BH-2-2', 'BH-3']],
			skip: [{ added: ['BH-3'], replaced: [], renamed: [], skipped: ['BH-2'] }, ['BH-1 9000', 'BH-2 9000', 'BH-3 9000']],
		});
	});

	test('a borehole far from the site, the termination depth and lab samples', () => {
		const site = { lat: 23.8103, lon: 90.4125, x: 0, y: 0 };
		const near = borehole('BH-1', { x: 30000, y: 40000 });
		const far = borehole('BH-2', { lat: 23.8203, lon: 90.4125 });
		const report: ISoilReport = { ...newSoilReport(), site, boreholes: [near, far] };
		const problems = checkSoilReport(report).filter(p => p.message.includes('from the site'));
		assert.deepStrictEqual({
			near: Math.round(distanceFromSite(report, near)!),
			far: Math.round(distanceFromSite(report, far)!),
			problems: problems.map(p => `${p.index} ${p.path} ${p.severity}`),
			noSite: distanceFromSite({ ...report, site: undefined }, far),
			termination: [terminationDepth(borehole('A', { depth: 6000 })), terminationDepth(borehole('B', { depth: undefined }))],
			lab: [hasLabData({ depth: 1500, type: 'SPT', number: 'S-1' }), hasLabData({ depth: 3000, type: 'UD', moisture: 32 })],
		}, {
			near: 50, far: 1112, problems: ['1 lat warning'], noSite: undefined, termination: [6000, 9000], lab: [false, true],
		});
	});

	test('backend errors: one line, the traceback as details', () => {
		const traceback = 'Traceback (most recent call last):\n  File "report.py", line 9, in soil_report\n    x = 1 / 0\nZeroDivisionError: division by zero\n';
		assert.deepStrictEqual([splitError('Backend not reachable'), splitError(traceback)], [
			{ summary: 'Backend not reachable' },
			{ summary: 'ZeroDivisionError: division by zero', details: traceback.trim() },
		]);
	});

	test('results: per-borehole warnings, skipped boreholes and the site class criteria', () => {
		const results = readSoilResults({
			boreholes: [{ id: 'BH-1', siteClass: { class: 'SD', N: 12, su: 30, byN: 'SD', bySu: 'SD' } }],
			warnings: ['Soil report: BH-2: layers 1 and 2 overlap'], skipped: ['BH-2'], details: [],
		});
		assert.deepStrictEqual({
			problems: results?.problems, skipped: results?.skipped,
			byN: results?.boreholes?.[0].siteClass?.byN, bySu: results?.boreholes?.[0].siteClass?.bySu,
		}, {
			problems: ['Soil report: BH-2: layers 1 and 2 overlap'], skipped: ['BH-2'], byN: 'SD', bySu: 'SD',
		});
	});
	test('the site bearing table: the lowest of the boreholes with a value, the others named or left out (N-S4, N-S3, N-S5, N-S6)', () => {
		const table = (qa: (number | null)[]) => [1000, 2000].map((Df, i) => ({ B: 2000, Df, qa: qa[i], qa_shear: qa[i], qa_settlement: null, governs: qa[i] === null ? null : 'shear' }));
		const raw = {
			siteClass: { class: 'SD', governing: 'BH-1', provisional: true, note: 'SD' },
			boreholes: [
				{ id: 'BH-1', siteClass: { class: 'SD', N: 8, depth: 15000, provisional: true }, bearing: { table: table([80, 95]) }, ks: 615, ksDetail: { bowles: 9600 },
					pile: [{ top: 0, bottom: 6000, soilType: 'sand', fs: 20, qb: 300, liquefiable: 0.5, fsSeismic: 10 }] },
				{ id: 'BH-2', siteClass: { class: 'SD', N: 9, depth: 30000 }, bearing: { table: table([100, 110]) } },
				// Far away, with fill at its base: no value at Df 1 m.
				{ id: 'BH-3', siteClass: { class: 'SD', N: 5, depth: 20000 }, bearing: { table: table([null, 60]) } },
			],
		};
		const all = readSoilResults(raw)!;
		const without = readSoilResults(raw, new Set(['BH-3']))!;
		const cells = (r: typeof all) => r.bearing!.cells.map(c => [c.Df, c.qa, c.borehole, c.missing]);
		assert.deepStrictEqual({
			all: cells(all), without: cells(without), excluded: [all.bearing!.excluded, without.bearing!.excluded],
			site: [all.siteClass!.provisional, all.boreholes!.map(b => b.siteClass!.provisional)],
			ks: [all.boreholes![0].ks, all.boreholes![0].ksBowles],
			piles: all.boreholes![0].piles!.map(p => [p.fs, p.liquefiable, p.fsSeismic]),
		}, {
			// Before, BH-3's empty cell blanked Df 1 m for the whole site.
			all: [[1000, 80, 'BH-1', ['BH-3']], [2000, 60, 'BH-3', undefined]],
			without: [[1000, 80, 'BH-1', undefined], [2000, 95, 'BH-1', undefined]],
			excluded: [undefined, ['BH-3']],
			site: [true, [true, false, false]],
			ks: [615, 9600],
			piles: [[20, 0.5, 10]],
		});
	});

	test('flags every borehole that shares an id, and a site class when no log reaches 30 m (N-S7, N-S3)', () => {
		const report: ISoilReport = { ...newSoilReport(), boreholes: [
			borehole('BH-1', { depth: 30000, layers: [{ top: 0, bottom: 30000, description: '', soilType: 'clay' }] }),
			borehole('BH-1', { depth: 30000, layers: [{ top: 0, bottom: 30000, description: '', soilType: 'clay' }] }),
			borehole('BH-3', { depth: 15000, layers: [{ top: 0, bottom: 15000, description: '', soilType: 'clay' }] }),
			borehole('BH-4', { depth: 12000, layers: [{ top: 0, bottom: 10000, description: '', soilType: 'clay' }, { top: 10000, bottom: 12000, description: '', soilType: 'rock' }] }),
		] };
		assert.deepStrictEqual(checkSoilReport(report).map(p => `${p.severity} ${p.index} ${p.path}: ${p.message}`), [
			'error 0 id: 2 boreholes are called BH-1: give each its own id.',
			'error 1 id: 2 boreholes are called BH-1: give each its own id.',
		]);
		// Without the two 30 m boreholes: one report note, the deepest log named (rock ends BH-4's log).
		report.boreholes.splice(0, 2);
		report.boreholes[1].layers = [{ top: 0, bottom: 12000, description: '', soilType: 'clay' }];
		assert.deepStrictEqual(checkSoilReport(report).map(p => `${p.severity} ${p.index} ${p.message.slice(0, 50)}`), [
			'warning undefined No borehole reaches 30 m (the deepest ends at 15 m',
		]);
	});
});
