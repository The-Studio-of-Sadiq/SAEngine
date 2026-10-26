/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { gridLabel } from '../../../../services/saengineProject/common/gridLabels.js';
import { buildSpec, centralBay, DEFAULT_FORM, folderError, formatLengths, gridLines, parseSpacings, readGenerateResult, readGenerateSummary, readPendingBuilding, storyHeights, summarize } from '../../browser/newBuildingModel.js';

suite('SAEngine - New Building wizard model', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	const values = (text: string) => {
		const result = parseSpacings(text);
		return result.ok ? result.values : result.error;
	};

	test('spacing shorthand: repeats, units, separators and errors', () => {
		assert.deepStrictEqual({
			repeat: values('3×6000, 4500'),
			ascii: values('2x5000;2 * 4000'),
			spaces: values('6000 6000'),
			metres: values('2×6m, 4.5m'),
			feet: values('20ft'),
			spacedUnits: values('6 m, 2×5000, 20 ft, 450 cm'),
			bad: typeof values('6000, abc'),
			small: typeof values('600'),
			empty: typeof values('  '),
			format: formatLengths([6000, 6000, 6000, 4500, 6000]),
		}, {
			repeat: [6000, 6000, 6000, 4500],
			ascii: [5000, 5000, 4000, 4000],
			spaces: [6000, 6000],
			metres: [6000, 6000, 4500],
			feet: [6096],
			spacedUnits: [6000, 5000, 5000, 6096, 4500],
			bad: 'string',
			small: 'string',
			empty: 'string',
			format: '3×6000, 4500, 6000',
		});
	});

	test('grid labels and lines: letters across X (past Z), numbers along Y', () => {
		assert.deepStrictEqual({
			labels: [0, 1, 25, 26, 27].map(i => gridLabel('x', i)),
			y: gridLabel('y', 2),
			lines: gridLines('x', [6000, 4500]),
		}, {
			labels: ['A', 'B', 'Z', 'AA', 'AB'],
			y: '3',
			lines: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }, { label: 'C', position: 10500 }],
		});
	});

	test('storey heights from count, ground and typical, or listed', () => {
		const heights = (change: Partial<typeof DEFAULT_FORM>) => {
			const result = storyHeights({ ...DEFAULT_FORM, ...change });
			return result.ok ? result.values : 'error';
		};
		assert.deepStrictEqual({
			counted: heights({ storyCount: '4', groundHeight: '3600', typicalHeight: '3000' }),
			one: heights({ storyCount: '1' }),
			listed: heights({ heights: '4000, 2×3200' }),
			badCount: heights({ storyCount: '0' }),
			tooLow: heights({ typicalHeight: '1500' }),
		}, {
			counted: [3600, 3000, 3000, 3000],
			one: [3600],
			listed: [4000, 3200, 3200],
			badCount: 'error',
			tooLow: 'error',
		});
	});

	test('the spec writes out grids and stories; errors are reported by field', () => {
		const ok = buildSpec({ ...DEFAULT_FORM, name: ' Tower ', gridX: '2×6000', gridY: '5000', storyCount: '2', system: 'rcFrameCore', location: 'sylhet', use: 'office', category: 'III' }, () => undefined);
		assert.deepStrictEqual(ok, {
			ok: true,
			spec: {
				schema: 'saengine.newBuilding/1',
				name: 'Tower',
				grids: { x: [{ label: 'A', position: 0 }, { label: 'B', position: 6000 }, { label: 'C', position: 12000 }], y: [{ label: '1', position: 0 }, { label: '2', position: 5000 }] },
				spacings: { x: [6000, 6000], y: [5000] },
				stories: [{ id: 'BASE', name: 'Base', elevation: 0 }, { id: 'L1', name: 'Level 1', elevation: 3600 }, { id: 'L2', name: 'Level 2', elevation: 6800 }],
				storyHeights: [3600, 3200],
				system: 'rcFrameCore',
				materials: { concrete: 'C27.6', rebar: 'B500DWR' },
				footing: 'isolated',
				site: { location: 'sylhet', siteClass: 'SD', siteClassSource: 'assumed' },
				occupancy: { use: 'office', category: 'III' },
				designCode: 'bnbc',
			},
		});
		const bad = buildSpec({ ...DEFAULT_FORM, name: 'a/b', gridX: 'x', storyCount: 'many' }, name => name.includes('/') ? 'bad name' : undefined);
		assert.deepStrictEqual(bad.ok ? [] : Object.keys(bad.errors).sort(), ['gridX', 'name', 'stories']);
	});

	test('summary, central bay, and the generator answer read defensively', () => {
		assert.deepStrictEqual({
			summary: summarize([6000, 6000, 6000], [5000, 5000], [3600, 3200]),
			central: [centralBay([6000, 6000, 6000]), centralBay([4000, 4000]), centralBay([5000])],
			answer: readGenerateResult({ root: 'C:\\P\\Tower', notes: ['Columns 400×400', { text: 'Beams span/12', rule: 'ACI 318 Table 9.3.1.1' }, 3] }),
			uri: readGenerateResult({ root: { fsPath: 'C:\\P\\T' }, notes: [] }),
			error: readGenerateResult({ error: 'no python' }),
			nothing: readGenerateResult(undefined).error !== undefined,
			pending: readPendingBuilding('{"root":"C:\\\\P","notes":["a",1],"time":5}'),
			pendingBad: readPendingBuilding('nope'),
		}, {
			summary: { baysX: 3, baysY: 2, lengthX: 18000, lengthY: 10000, storeys: 2, height: 6800, columnsPerFloor: 12 },
			central: [1, 0, 0],
			answer: { root: 'C:\\P\\Tower', notes: ['Columns 400×400', 'Beams span/12 (ACI 318 Table 9.3.1.1)'] },
			uri: { root: 'C:\\P\\T', notes: [] },
			error: { notes: [], error: 'no python' },
			nothing: true,
			pending: { root: 'C:\\P', notes: ['a'], time: 5 },
			pendingBad: undefined,
		});
	});

	test('project folder: full paths only, never one the app folder would resolve', () => {
		const ok = (path: string, windows: boolean) => folderError(path, windows) === undefined;
		assert.deepStrictEqual({
			drive: ok('C:\\Users\\me\\Documents', true),
			forward: ok('D:/Projects', true),
			unc: ok('\\\\server\\share\\jobs', true),
			driveRelative: ok('C:Users', true),
			rooted: ok('\\Users\\me', true),
			relative: ok('Projects', true),
			empty: ok('  ', true),
			wild: ok('C:\\a*b', true),
			posix: ok('/home/me', false),
			posixRelative: ok('home/me', false),
		}, {
			drive: true, forward: true, unc: true,
			driveRelative: false, rooted: false, relative: false, empty: false, wild: false,
			posix: true, posixRelative: false,
		});
	});

	test('generator summary: counts and sizes for the result page', () => {
		assert.deepStrictEqual(readGenerateSummary({
			sdc: 'D',
			counts: { columns: 72, beams: 102, walls: 0, slabs: 36, foundations: 12 },
			columnTypes: { 'L1-L3 interior': 'C500x500' },
			beamTypes: ['B300x500'],
			slabTypes: ['S150', 7],
		}), {
			sdc: 'D',
			counts: [['Columns', 72], ['Beams', 102], ['Slabs', 36], ['Footings', 12]],
			sizes: [{ what: 'Columns L1-L3 interior', size: 'C500x500' }, { what: 'Beams', size: 'B300x500' }, { what: 'Slabs', size: 'S150' }],
		});
		assert.strictEqual(readGenerateSummary('nope'), undefined);
	});
});
