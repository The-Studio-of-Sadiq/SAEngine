/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { groundLevelStamp, mepModelStamp, sourceStamp } from '../../common/partSources.js';
import { computePartStatuses, exportKind, IPartStatusInputs, nextStep } from '../../common/partStatus.js';
import { PROJECT_PARTS, projectParts } from '../../common/saengineProject.js';

const placeholder = (part: string) => JSON.stringify({ schema: 1, part });

const SOURCES = {
	settings: '{"schema": "saengine.projectSettings/1"}',
	materials: '{"materials": []}',
	objects: '{"objects": []}',
	floorPlan: '{"schema": "saengine.floorPlan/1"}',
};
const BIM = JSON.stringify({ schema: 'saengine.bim/2', source: { floorPlan: sourceStamp(SOURCES.floorPlan) }, elements: [] });

function femModel(sources: { [part: string]: string }): string {
	const list = Object.entries(sources).map(([key, text]) => `${key}=${key === 'mep' ? mepModelStamp(text) : sourceStamp(text)}`).join('; ');
	return JSON.stringify({ schema_version: 2, meta: { description: `Derived by SAEngine. Sources: ${list}` } });
}

const DERIVED = femModel({ bim: BIM, settings: SOURCES.settings, objects: SOURCES.objects, materials: SOURCES.materials });
const BOQ = JSON.stringify({ schema: 'saengine.boq/1', source: { bim: sourceStamp(BIM), objects: sourceStamp(SOURCES.objects), materials: sourceStamp(SOURCES.materials) }, items: [] });

function project(texts: { [part: string]: string | undefined }, rest: Omit<IPartStatusInputs, 'texts'> = {}): IPartStatusInputs {
	return {
		texts: new Map(Object.entries({
			soil: placeholder('soil'), mep: placeholder('mep'), substructure: placeholder('substructure'),
			...SOURCES, bim: BIM, fem: DERIVED, boq: placeholder('boq'), ...texts,
		})),
		...rest,
	};
}

/** `part: state text` of every part, for one readable snapshot. */
function summary(inputs: IPartStatusInputs, parts = PROJECT_PARTS): string[] {
	return computePartStatuses(parts, inputs, time => `day ${time}`).map(s => `${s.part}: ${s.state}${s.text ? ` ${s.text}` : ''}`);
}

suite('SAEngine - PartStatus', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('a derived but not analysed project, with placeholder parts and no report', () => {
		assert.deepStrictEqual(summary(project({})), [
			'soil: notStarted not started',
			'settings: done',
			'materials: done',
			'objects: done',
			'floorPlan: done',
			'bim: done',
			'mep: notStarted not started',
			'fem: inProgress not analysed',
			'substructure: notStarted not started',
			'boq: notStarted not measured',
			'exports: notStarted no report',
		]);
	});

	test('analysis model: not derived, stale sources, stale results, design checks', () => {
		const fem = (texts: { [part: string]: string | undefined }, rest: Omit<IPartStatusInputs, 'texts'> = {}) => summary(project(texts, rest))[7];
		const pass = JSON.stringify({ checked: 13, passed: 13, failed: 0, maxUtilisation: 0.8, governing: 'C1', computed: '2026-10-16T00:00:00Z' });
		const fail = JSON.stringify({ checked: 13, passed: 10, failed: 3, maxUtilisation: 1.4, governing: 'B2', computed: '2026-10-16T00:00:00Z' });
		assert.deepStrictEqual([
			fem({ fem: JSON.stringify({ schema_version: 2, meta: { name: 'P' } }) }),
			fem({ fem: undefined }),
			fem({ fem: '{ not json' }),
			fem({ materials: '{"materials": [1]}' }),
			fem({}, { femModelTime: 10, femResultsTime: 20 }),
			fem({}, { femModelTime: 30, femResultsTime: 20 }),
			fem({}, { femModelTime: 10, femResultsTime: 20, designSummaryText: pass, designSummaryTime: 25 }),
			fem({}, { femModelTime: 10, femResultsTime: 20, designSummaryText: fail, designSummaryTime: 25 }),
			fem({}, { femModelTime: 10, femResultsTime: 20, designSummaryText: fail, designSummaryTime: 15 }),
		], [
			'fem: notStarted not derived',
			'fem: notStarted not derived',
			'fem: error invalid file',
			'fem: stale stale',
			'fem: done analysed',
			'fem: stale stale',
			'fem: done 13 pass',
			'fem: failed 3 fail',
			'fem: done analysed',
		]);
	});

	test('bill of quantities, building model, report and other parts', () => {
		const lines = (texts: { [part: string]: string | undefined }, rest: Omit<IPartStatusInputs, 'texts'> = {}) => summary(project(texts, rest));
		assert.deepStrictEqual([
			lines({ boq: BOQ })[9],
			lines({ boq: BOQ, objects: '{"objects": [1]}' })[9],
			lines({ boq: '[' })[9],
			lines({ floorPlan: '{"schema": "saengine.floorPlan/1", "grids": {}}' })[5],
			lines({ bim: JSON.stringify({ schema: 'saengine.bim/2', elements: [] }) })[5],
			lines({}, { reportTime: 42 })[10],
			lines({ materials: '{' })[2],
			lines({ settings: undefined })[1],
		], [
			'boq: done measured',
			'boq: stale stale',
			'boq: error invalid file',
			'bim: stale stale',
			'bim: notStarted not built',
			'exports: done report day 42',
			'materials: error invalid file',
			'settings: notStarted not started',
		]);
	});

	test('soil report: boreholes, and the analysis model that took its site class from it', () => {
		const borehole = (id: string, layers: object[] = [{ top: 0, bottom: 3000 }]) => ({ id, x: 0, y: 0, layers });
		const soil = (boreholes: object[], schema = 'saengine.soilReport/1') => JSON.stringify({ schema, boreholes });
		const three = soil([borehole('BH-1'), borehole('BH-2'), borehole('BH-3')]);
		const line = (texts: { [part: string]: string | undefined }) => summary(project(texts))[0];
		const fem = (texts: { [part: string]: string | undefined }) => summary(project(texts))[7];
		const fromSoil = femModel({ bim: BIM, settings: SOURCES.settings, objects: SOURCES.objects, materials: SOURCES.materials, soil: three });
		assert.deepStrictEqual([
			line({ soil: undefined }),
			line({ soil: soil([]) }),
			line({ soil: three }),
			line({ soil: soil([borehole('BH-1')]) }),
			line({ soil: soil([borehole('BH-1'), borehole('BH-2', [])]) }),
			line({ soil: '{ not json' }),
			line({ soil: soil([borehole('BH-1')], 'saengine.other/1') }),
			fem({ soil: three }),
			fem({ soil: three, fem: fromSoil }),
			fem({ soil: soil([borehole('BH-1')]), fem: fromSoil }),
		], [
			'soil: notStarted not started',
			'soil: notStarted not started',
			'soil: done 3 boreholes',
			'soil: done 1 borehole',
			'soil: inProgress 2 boreholes',
			'soil: error invalid file',
			'soil: error invalid file',
			// A model derived without the soil report (entered site class) does not follow it.
			'fem: inProgress not analysed',
			'fem: inProgress not analysed',
			'fem: stale stale',
		]);
	});

	test('the exports part counts the exports besides the report', () => {
		const exportsLine = (rest: Omit<IPartStatusInputs, 'texts'>) => summary(project({}, rest))[10];
		assert.deepStrictEqual({
			lines: [exportsLine({ exportFiles: 0 }), exportsLine({ exportFiles: 1 }), exportsLine({ exportFiles: 3 }), exportsLine({ exportFiles: 3, reportTime: 7 })],
			kinds: ['report.pdf', 'IFC/Frame.ifc', 'Floor Plan\\L1 Ground.dxf', 'boq.csv', 'IFC/notes.txt', 'Floor Plan/old/L1.csv', 'other.pdf'].map(exportKind),
		}, {
			lines: ['exports: notStarted no report', 'exports: inProgress 1 file, no report', 'exports: inProgress 3 files, no report', 'exports: done report day 7'],
			kinds: ['report', 'ifc', 'dxf', 'csv', undefined, undefined, undefined],
		});
	});

	test('a special structure builds its model from the structural model', () => {
		const structure = '{"schema": "saengine.structure/1"}';
		const bim = JSON.stringify({ schema: 'saengine.bim/2', source: { structure: sourceStamp(structure) }, elements: [] });
		assert.deepStrictEqual(summary(project({ structure, bim }), projectParts('structure')).slice(4, 6), ['structure: done', 'bim: done']);
	});

	test('substructure: placeholder, foundations, checked against the saved file and the results', () => {
		const file = (count: number) => JSON.stringify({ schema: 'saengine.substructure/1', foundations: Array.from({ length: count }, (_, i) => ({ id: `F${i + 1}`, type: 'isolated' })) });
		const pass = JSON.stringify({ foundations: 2, checked: 2, passed: 2, failed: 0, maxUtilisation: 0.7, governing: 'F1', computed: '2026-10-17T00:00:00Z' });
		const fail = JSON.stringify({ foundations: 2, checked: 2, passed: 1, failed: 1, maxUtilisation: 1.2, governing: 'F2', computed: '2026-10-17T00:00:00Z' });
		const part = (texts: { [part: string]: string | undefined }, rest: Omit<IPartStatusInputs, 'texts'> = {}) => computePartStatuses(PROJECT_PARTS, project(texts, rest)).find(s => s.part === 'substructure');
		// A summary with the stamps of the files it was checked from ("" for a missing soil report).
		const recorded = (substructure: string, soil = sourceStamp(placeholder('soil'))) => JSON.stringify({
			...JSON.parse(fail),
			source: { substructure: sourceStamp(substructure), soil, settings: sourceStamp(SOURCES.settings), materials: sourceStamp(SOURCES.materials), objects: sourceStamp(SOURCES.objects), bim: sourceStamp(BIM) },
		});
		const line = (texts: { [part: string]: string | undefined }, rest: Omit<IPartStatusInputs, 'texts'> = {}) => {
			const s = part(texts, rest)!;
			return `${s.state} ${s.text} (${s.hint ?? ''})`;
		};
		assert.deepStrictEqual([
			line({}),
			line({ substructure: file(0) }),
			line({ substructure: '{ not json' }),
			line({ substructure: JSON.stringify({ schema: 'other' }) }),
			line({ substructure: file(1) }),
			line({ substructure: file(2) }, { substructureTime: 10, femResultsTime: 5, substructureSummaryText: pass, substructureSummaryTime: 20 }),
			line({ substructure: file(2) }, { substructureTime: 10, femResultsTime: 5, substructureSummaryText: fail, substructureSummaryTime: 20 }),
			line({ substructure: file(2) }, { substructureTime: 30, femResultsTime: 5, substructureSummaryText: pass, substructureSummaryTime: 20 }),
			line({ substructure: file(2) }, { substructureTime: 10, femResultsTime: 25, substructureSummaryText: pass, substructureSummaryTime: 20 }),
			line({ substructure: file(2) }, { substructureTime: 10, substructureSummaryText: JSON.stringify({ foundations: 2, checked: 0, passed: 0, failed: 0 }), substructureSummaryTime: 20 }),
			// A summary that records its sources is current while they are unchanged, whatever the times.
			line({ substructure: file(2) }, { substructureTime: 30, femResultsTime: 5, substructureSummaryText: recorded(file(2)), substructureSummaryTime: 20 }),
			line({ substructure: file(2), settings: '{"schema": "saengine.projectSettings/1", "foundation": {"allowableBearing": 400}}' }, { femResultsTime: 5, substructureSummaryText: recorded(file(2)), substructureSummaryTime: 20 }),
			line({ substructure: file(2), soil: '{"schema": "saengine.soilReport/1", "boreholes": []}' }, { femResultsTime: 5, substructureSummaryText: recorded(file(2)), substructureSummaryTime: 20 }),
			line({ substructure: file(2), objects: '{"objects": [1]}' }, { femResultsTime: 5, substructureSummaryText: recorded(file(2)), substructureSummaryTime: 20 }),
			line({ substructure: file(2) }, { femResultsTime: 25, substructureSummaryText: recorded(file(2)), substructureSummaryTime: 20 }),
			line({ substructure: file(2) }, { femResultsTime: 5, substructureSummaryText: recorded(file(2), ''), substructureSummaryTime: 20 }),
			line({ substructure: file(2), soil: undefined }, { femResultsTime: 5, substructureSummaryText: recorded(file(2), ''), substructureSummaryTime: 20 }),
		], [
			'notStarted not started (design the foundations)',
			'notStarted not started (design the foundations)',
			'error invalid file (fix the file)',
			'error invalid file (fix the file)',
			'inProgress 1 foundation (check the foundations)',
			'done 2 foundations ()',
			'failed 1 fail (review the failing foundations)',
			'inProgress 2 foundations (check the foundations)',
			'inProgress 2 foundations (check the foundations)',
			'inProgress 2 foundations (run the analysis to design them)',
			'failed 1 fail (review the failing foundations)',
			'inProgress 2 foundations (check the foundations)',
			'inProgress 2 foundations (check the foundations)',
			'inProgress 2 foundations (check the foundations)',
			'inProgress 2 foundations (check the foundations)',
			'inProgress 2 foundations (check the foundations)',
			'failed 1 fail (review the failing foundations)',
		]);
	});

	test('the bill of quantities is stale once the substructure it does not record has foundations', () => {
		const substructure = JSON.stringify({ schema: 'saengine.substructure/1', foundations: [{ id: 'F1', type: 'isolated' }] });
		const withSubstructure = JSON.stringify({ schema: 'saengine.boq/1', source: { bim: sourceStamp(BIM), objects: sourceStamp(SOURCES.objects), materials: sourceStamp(SOURCES.materials), substructure: sourceStamp(substructure), settings: groundLevelStamp(SOURCES.settings) }, items: [] });
		const boq = (texts: { [part: string]: string | undefined }) => computePartStatuses(PROJECT_PARTS, project(texts)).find(s => s.part === 'boq')!.state;
		assert.deepStrictEqual([
			boq({ boq: BOQ }),
			boq({ boq: BOQ, substructure }),
			boq({ boq: withSubstructure, substructure }),
			// Only the ground level of the settings counts.
			boq({ boq: withSubstructure, substructure, settings: '{"schema": "saengine.projectSettings/1", "foundation": {"allowableBearing": 400}}' }),
			boq({ boq: withSubstructure, substructure, settings: '{"schema": "saengine.projectSettings/1", "foundation": {"groundLevel": -300}}' }),
		], ['done', 'stale', 'done', 'done', 'stale']);
	});

	test('MEP: placeholder, content, checked against the saved files and the results', () => {
		const file = (equipment: number, extra: object = {}) => JSON.stringify({ schema: 'saengine.mep/1', equipment: Array.from({ length: equipment }, (_, i) => ({ id: `EQ${i + 1}` })), openings: [], shafts: [], ...extra });
		const summaryOf = (mep: string, counts: { openingsFailed: number; clashesOpen: number; openingsPartial?: number }, bim = BIM) => JSON.stringify({
			equipment: 2, openings: 1, clashes: counts.clashesOpen, computed: '2026-10-17T00:00:00Z', ...counts,
			source: { settings: sourceStamp(SOURCES.settings), materials: sourceStamp(SOURCES.materials), objects: sourceStamp(SOURCES.objects), bim: sourceStamp(bim), mep: sourceStamp(mep) },
		});
		const line = (texts: { [part: string]: string | undefined }, rest: Omit<IPartStatusInputs, 'texts'> = {}) => {
			const s = computePartStatuses(PROJECT_PARTS, project(texts, rest)).find(p => p.part === 'mep')!;
			return `${s.state} ${s.text} (${s.hint ?? ''})`;
		};
		const two = file(2);
		const ok = summaryOf(two, { openingsFailed: 0, clashesOpen: 0 });
		assert.deepStrictEqual([
			line({}),
			line({ mep: file(0) }),
			line({ mep: '{ not json' }),
			line({ mep: JSON.stringify({ schema: 'other' }) }),
			line({ mep: two }),
			line({ mep: two }, { femResultsTime: 5, mepSummaryText: ok, mepSummaryTime: 20 }),
			line({ mep: file(1) }, { femResultsTime: 5, mepSummaryText: summaryOf(file(1), { openingsFailed: 0, clashesOpen: 0 }), mepSummaryTime: 20 }),
			line({ mep: two }, { femResultsTime: 5, mepSummaryText: summaryOf(two, { openingsFailed: 1, clashesOpen: 2 }), mepSummaryTime: 20 }),
			line({ mep: two }, { femResultsTime: 5, mepSummaryText: summaryOf(two, { openingsFailed: 0, clashesOpen: 2 }), mepSummaryTime: 20 }),
			// Openings whose strength was not checked (no analysis results) keep it in progress.
			line({ mep: two }, { femResultsTime: 5, mepSummaryText: summaryOf(two, { openingsFailed: 0, clashesOpen: 0, openingsPartial: 1 }), mepSummaryTime: 20 }),
			line({ mep: two }, { femResultsTime: 5, mepSummaryText: summaryOf(two, { openingsFailed: 0, clashesOpen: 0, openingsPartial: 2 }), mepSummaryTime: 20 }),
			// Edited since, or older than the analysis results: not checked.
			line({ mep: file(2, { contentsAs: 'live' }) }, { femResultsTime: 5, mepSummaryText: ok, mepSummaryTime: 20 }),
			line({ mep: two, objects: '{"objects": [1]}' }, { femResultsTime: 5, mepSummaryText: ok, mepSummaryTime: 20 }),
			line({ mep: two }, { femResultsTime: 25, mepSummaryText: ok, mepSummaryTime: 20 }),
			// IFC models alone are something to coordinate.
			line({ mep: file(0, { ifcModels: [{ path: '07 MEP/HVAC.ifc' }] }) }),
		], [
			'notStarted not started (lay out the services)',
			'notStarted not started (lay out the services)',
			'error invalid file (fix the file)',
			'error invalid file (fix the file)',
			'inProgress not checked (check the openings and clashes)',
			'done 2 equipment ()',
			'done 1 equipment ()',
			'failed 1 opening fails (review the failing openings)',
			'inProgress 2 clashes (coordinate the clashes)',
			'inProgress 1 opening not fully checked (run the analysis to check the openings\' strength)',
			'inProgress 2 openings not fully checked (run the analysis to check the openings\' strength)',
			'inProgress not checked (check the openings and clashes)',
			'inProgress not checked (check the openings and clashes)',
			'inProgress not checked (check the openings and clashes)',
			'inProgress not checked (check the openings and clashes)',
		]);
	});

	test('MEP: the plumbing counts as content and its checks decide the status', () => {
		const tank = { id: 'T1', kind: 'overhead', story: 'L1', x: 0, y: 0 };
		const mep = JSON.stringify({ schema: 'saengine.mep/1', equipment: [], openings: [], shafts: [], plumbing: { stories: [{ story: 'L1' }], risers: [], tanks: [tank] } });
		const summaryOf = (plumbing?: { failed: number; floorsLow: number; source?: { soil: string } }) => JSON.stringify({
			equipment: 0, openings: 0, openingsFailed: 0, clashes: 0, clashesOpen: 0, computed: '2026-10-17T00:00:00Z',
			source: { settings: sourceStamp(SOURCES.settings), materials: sourceStamp(SOURCES.materials), objects: sourceStamp(SOURCES.objects), bim: sourceStamp(BIM), mep: sourceStamp(mep) },
			...(plumbing ? { plumbing: { risers: 0, tanks: 1, ...plumbing } } : {}),
		});
		const line = (summary?: string) => {
			const s = computePartStatuses(PROJECT_PARTS, project({ mep }, summary ? { femResultsTime: 5, mepSummaryText: summary, mepSummaryTime: 20 } : {})).find(p => p.part === 'mep')!;
			return `${s.state} ${s.text} (${s.hint ?? ''})`;
		};
		const fem = computePartStatuses(PROJECT_PARTS, project({ mep, fem: femModel({ bim: BIM, settings: SOURCES.settings, objects: SOURCES.objects, materials: SOURCES.materials }) })).find(p => p.part === 'fem')!;
		assert.deepStrictEqual({
			lines: [line(), line(summaryOf()), line(summaryOf({ failed: 3, floorsLow: 1 })), line(summaryOf({ failed: 0, floorsLow: 2 })), line(summaryOf({ failed: 0, floorsLow: 0 })),
				// Checked against a soil report that has changed since: stale; against the current one: current.
				line(summaryOf({ failed: 3, floorsLow: 0, source: { soil: 'stamp of an older soil report' } })), line(summaryOf({ failed: 3, floorsLow: 0, source: { soil: sourceStamp(placeholder('soil')) } }))],
			// The overhead tank loads the analysis model: a model derived before it is stale.
			femStale: fem.state,
		}, {
			lines: [
				'inProgress not checked (check the openings and clashes)',
				'inProgress plumbing not checked (open the plumbing results or Run All)',
				'failed 3 plumbing checks fail (review the plumbing)',
				'failed 2 floors below the minimum pressure (raise the overhead tank or add a booster pump)',
				'done plumbing checked, 1 tank ()',
				'inProgress plumbing not checked (open the plumbing results or Run All)',
				'failed 3 plumbing checks fail (review the plumbing)',
			],
			femStale: 'stale',
		});
	});

	test('the analysis model and the bill are stale once MEP they do not record has content', () => {
		const mep = JSON.stringify({ schema: 'saengine.mep/1', equipment: [{ id: 'EQ1' }], openings: [], shafts: [] });
		const withMep = femModel({ bim: BIM, settings: SOURCES.settings, objects: SOURCES.objects, materials: SOURCES.materials, mep });
		const boqWithMep = JSON.stringify({ schema: 'saengine.boq/1', source: { bim: sourceStamp(BIM), objects: sourceStamp(SOURCES.objects), materials: sourceStamp(SOURCES.materials), mep: sourceStamp(mep) }, items: [] });
		const state = (part: string, texts: { [part: string]: string | undefined }) => computePartStatuses(PROJECT_PARTS, project(texts, { femModelTime: 10, femResultsTime: 20 })).find(s => s.part === part)!.state;
		assert.deepStrictEqual([
			state('fem', {}),
			state('fem', { mep }),
			state('fem', { mep, fem: withMep }),
			state('fem', { mep: placeholder('mep'), fem: withMep }),
			state('boq', { boq: BOQ, mep }),
			state('boq', { boq: boqWithMep, mep }),
			state('boq', { boq: boqWithMep, mep: placeholder('mep') }),
			// The model takes the equipment, openings and shafts, not the IFC models or the labels.
			state('fem', { mep: JSON.stringify({ ...JSON.parse(mep), ifcModels: [{ path: '07 MEP/HVAC.ifc', discipline: 'mechanical', visible: false }] }), fem: withMep }),
			state('fem', { mep: JSON.stringify({ ...JSON.parse(mep), equipment: [{ id: 'EQ1', name: 'Roof tank' }] }), fem: withMep }),
			state('fem', { mep: JSON.stringify({ ...JSON.parse(mep), equipment: [{ id: 'EQ2' }] }), fem: withMep }),
		], ['done', 'stale', 'done', 'stale', 'stale', 'done', 'stale', 'done', 'done', 'stale']);
	});

	test('the next step skips the parts that are not written yet', () => {
		const statuses = computePartStatuses(PROJECT_PARTS, project({}));
		const next = nextStep(statuses);
		assert.deepStrictEqual({ index: next?.index, part: next?.status.part, hint: next?.status.hint }, { index: 7, part: 'fem', hint: 'run the analysis' });
		assert.strictEqual(nextStep(statuses.map(s => ({ ...s, state: 'done' }))), undefined);
	});
});
