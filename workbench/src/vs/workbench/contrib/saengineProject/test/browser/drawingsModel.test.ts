/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { joinPath } from '../../../../../base/common/resources.js';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { DrawingPreviewInput, DrawingPreviewInputSerializer, sameSheet } from '../../browser/drawingPreviewInput.js';
import {
	drawingSetKey, drawingSettingsRows, drawingsDescription, findPreviewSheet, fitView, generateArgs, generateLabel, IDrawingSet, keepSelection, readDrawingSet, readDrawingSettings, readScale, readTime,
	resolveProjectPath, selectedSheets, zoomAt, zoomLabel,
} from '../../browser/drawingsModel.js';

const root = URI.file('C:\\Projects\\Frame');
/** A file of the drawings folder, joined as the model joins it (off Windows the root keeps its backslashes). */
const inDrawings = (name: string) => joinPath(root, '11 Exports', 'Drawings', name);

/** A set as the backend answers it, with paths relative to the project and an absolute one. */
const answer = {
	sheets: [
		{ number: 'S-101', title: 'Ground floor framing plan', dxf: '11 Exports/Drawings/S-101.dxf', pdfPage: 1, png: '11 Exports/Drawings/S-101.png', size: 'A1', scale: '1:100' },
		{ number: 'S-201', title: 'Column schedule', dxf: 'C:\\Projects\\Frame\\11 Exports\\Drawings\\S-201.dxf', pdfPage: 2, png: '11 Exports\\Drawings\\S-201.png', stale: true },
		{ title: 'no number: left out' },
		'junk',
	],
	pdf: '11 Exports/Drawings/Frame drawings.pdf',
	bbsCsv: '11 Exports/Drawings/bbs.csv',
	generatedAt: '2026-10-23T09:30:00Z',
	notes: ['Bar marks are per storey.'],
	problems: ['B12: no design yet, drawn without bars', { message: 'Stair S1 drawn schematic', severity: 'warning' }],
};

function paths(set: IDrawingSet | undefined) {
	return set && {
		...set,
		pdf: set.pdf?.fsPath, bbsCsv: set.bbsCsv?.fsPath,
		sheets: set.sheets.map(s => ({ ...s, dxf: s.dxf?.fsPath, png: s.png?.fsPath })),
	};
}

suite('SAEngine - drawings', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('the command arguments', () => {
		assert.deepStrictEqual([
			generateArgs('C:\\Projects\\Frame'),
			generateArgs('C:\\Projects\\Frame', { sheets: [], size: 'A2' }),
			generateArgs('C:\\Projects\\Frame', { sheets: ['S-101', ' ', 'S-201'], size: 'A1' }),
		], [
			{ projectRoot: 'C:\\Projects\\Frame' },
			{ projectRoot: 'C:\\Projects\\Frame', size: 'A2' },
			{ projectRoot: 'C:\\Projects\\Frame', sheets: ['S-101', 'S-201'], size: 'A1' },
		]);
	});

	test('paths and times of an answer', () => {
		assert.deepStrictEqual([
			resolveProjectPath(root, '11 Exports/Drawings/S-101.dxf')?.fsPath,
			resolveProjectPath(root, 'D:\\elsewhere\\x.pdf')?.fsPath,
			resolveProjectPath(root, ''),
			readTime(1792747800),
			readTime(1792747800000),
			readTime('2026-10-23T09:30:00Z'),
			readTime('yesterday'),
		], [
			inDrawings('S-101.dxf').fsPath,
			URI.file('D:\\elsewhere\\x.pdf').fsPath,
			undefined,
			1792747800000,
			1792747800000,
			Date.parse('2026-10-23T09:30:00Z'),
			undefined,
		]);
	});

	test('the answer of generate and list', () => {
		const file = (name: string) => inDrawings(name).fsPath;
		assert.deepStrictEqual(paths(readDrawingSet(answer, root)), {
			sheets: [
				{ number: 'S-101', title: 'Ground floor framing plan', dxf: file('S-101.dxf'), pdfPage: 1, png: file('S-101.png'), size: 'A1', scale: '1:100', stale: false },
				{ number: 'S-201', title: 'Column schedule', dxf: URI.file('C:\\Projects\\Frame\\11 Exports\\Drawings\\S-201.dxf').fsPath, pdfPage: 2, png: file('S-201.png'), size: undefined, scale: undefined, stale: true },
			],
			pdf: file('Frame drawings.pdf'),
			bbsCsv: file('bbs.csv'),
			generatedAt: Date.parse('2026-10-23T09:30:00Z'),
			size: 'A1',
			stale: true,
			staleReason: undefined,
			notes: ['Bar marks are per storey.', 'Stair S1 drawn schematic'],
			problems: ['B12: no design yet, drawn without bars'],
		});
		// Nothing generated yet; then a whole set made stale by its stamps, under `drawings`.
		const stamped = readDrawingSet({ drawings: { ...answer, stamps: { stale: true, changed: ['06 BIM', 'design'] } } }, root);
		assert.deepStrictEqual([
			readDrawingSet({}, root),
			readDrawingSet(undefined, root),
			readDrawingSet({ sheets: [], problems: ['No building model.'] }, root),
			stamped?.sheets.map(s => s.stale),
			stamped?.staleReason,
		], [
			undefined,
			undefined,
			{ sheets: [], stale: false, notes: [], problems: ['No building model.'] },
			[true, true],
			'changed since: 06 BIM, design',
		]);
	});

	test('what the section says and the Generate button', () => {
		const set = readDrawingSet(answer, root)!;
		const current = readDrawingSet({ ...answer, sheets: answer.sheets.slice(0, 1) }, root)!;
		const stale = readDrawingSet({ ...answer, stale: true, staleReason: 'the design changed' }, root)!;
		const clean = readDrawingSet({ ...answer, sheets: answer.sheets.slice(0, 1), problems: [] }, root)!;
		assert.deepStrictEqual([
			drawingsDescription(undefined, false),
			drawingsDescription(clean, true),
			drawingsDescription(current, true),
			drawingsDescription(set, true),
			drawingsDescription(stale, true),
			generateLabel(undefined, 0),
			generateLabel(set, 0),
			generateLabel(set, 1),
			generateLabel(set, 2),
		], [
			'Drawing generation is not available in this build of SAEngine yet.',
			'1 sheet, A1, current',
			'1 sheet, A1, current; 1 problem to resolve before issue (listed below)',
			'2 sheets, 1 out of date — regenerate',
			'2 sheets, out of date — regenerate (the design changed)',
			'Generate Drawings',
			'Regenerate Drawings',
			'Generate 1 Sheet',
			'Generate 2 Sheets',
		]);
	});

	test('the selection follows the set', () => {
		const set = readDrawingSet(answer, root);
		const selection = new Set(['S-201', 'S-999', 'S-101']);
		assert.deepStrictEqual([selectedSheets(set, selection), [...keepSelection(set, selection)], selectedSheets(undefined, selection)], [['S-101', 'S-201'], ['S-101', 'S-201'], []]);
	});

	test('the drawing settings', () => {
		const CONFLICTS = ['The drawings name the engineer B. Designer, Project names A. Engineer.', `The drawings' project number is EC-7, Project's is P-0042.`];
		const empty = readDrawingSettings({ project: { name: 'Frame', number: 'P-0042', engineer: 'A. Engineer' } });
		const full = readDrawingSettings({
			project: { name: 'Frame', number: 'P-0042', engineer: 'A. Engineer', client: 'Example Developers' },
			drawings: {
				firm: 'Example Consultants', engineer: 'B. Designer', checkedBy: 'C. Checker', approvedBy: 'D. Approver', projectNumber: 'EC-7',
				revisions: [{ code: 'P1', date: '2026-10-01', description: 'For comment' }, { code: 'A', date: '2026-10-23', description: 'For construction' }],
				sheetSize: 'a2', planScale: 100, detailScale: '1/50',
			},
		});
		assert.deepStrictEqual([
			empty,
			full,
			readDrawingSettings({ drawings: { revision: 'B', sheetSize: 'A0', scales: { plan: '1:200', detail: 'large' } } }),
			[readScale(50), readScale('1:25'), readScale('1 / 100'), readScale('x'), readScale(0)],
			drawingSettingsRows(full).map(r => `${r.name}: ${r.value ?? '-'}`),
		], [
			{
				client: undefined, firm: undefined, engineer: 'A. Engineer', checkedBy: undefined, approvedBy: undefined, projectNumber: 'P-0042', revision: undefined,
				sheetSize: 'A1', planScale: '1:100', detailScale: '1:25', standard: undefined, present: false, conflicts: [],
			},
			{
				client: 'Example Developers', firm: 'Example Consultants', engineer: 'B. Designer', checkedBy: 'C. Checker', approvedBy: 'D. Approver', projectNumber: 'EC-7',
				revision: { code: 'A', date: '2026-10-23', description: 'For construction' },
				sheetSize: 'A2', planScale: '1:100', detailScale: '1:50', standard: undefined, present: true, conflicts: CONFLICTS,
			},
			{
				client: undefined, firm: undefined, engineer: undefined, checkedBy: undefined, approvedBy: undefined, projectNumber: undefined,
				revision: { code: 'B', date: undefined, description: undefined },
				sheetSize: 'A1', planScale: '1:200', detailScale: '1:25', standard: undefined, present: true, conflicts: [],
			},
			['1:50', '1:25', '1:100', undefined, undefined],
			[
				'Client: Example Developers', 'Firm: Example Consultants', 'Engineer: B. Designer', 'Checked by: C. Checker', 'Approved by: D. Approver', 'Project number: EC-7',
				'Revision: A · 2026-10-23 · For construction', 'Sheet size: A2', 'Scales: plans 1:100, details 1:50', 'Office standard: -',
			],
		]);
	});

	test('the preview fits, zooms about the pointer and keeps its limits', () => {
		const fit = fitView(8400, 5940, 1000, 732);
		const zoomed = zoomAt({ zoom: 0.5, x: 10, y: 20 }, 2, 110, 220);
		const round = (v: { zoom: number; x: number; y: number }) => ({ zoom: Math.round(v.zoom * 1e4) / 1e4, x: Math.round(v.x), y: Math.round(v.y) });
		assert.deepStrictEqual([
			round(fit),
			zoomed,
			zoomAt({ zoom: 8, x: 0, y: 0 }, 2, 0, 0).zoom,
			fitView(0, 0, 100, 100),
			zoomLabel({ zoom: 0.1143, x: 0, y: 0 }),
		], [
			{ zoom: 0.1152, x: 16, y: 24 },
			// The point under the pointer (110, 220) stays where it is.
			{ zoom: 1, x: -90, y: -180 },
			8,
			{ zoom: 1, x: 0, y: 0 },
			'11%',
		]);
	});

	test('a preview is restored with the window', () => {
		const serializer = new DrawingPreviewInputSerializer();
		const input = new DrawingPreviewInput({ number: 'S-101', title: 'Ground floor framing plan', png: URI.file('C:\\p\\S-101.png'), dxf: URI.file('C:\\p\\S-101.dxf'), pdfPage: 1, size: 'A1', stale: true, root });
		const restored = serializer.deserialize(undefined!, serializer.serialize(input));
		assert.deepStrictEqual([restored?.getName(), restored?.getDescription(), restored?.sheet.png.fsPath, restored?.sheet.dxf?.fsPath, restored?.sheet.stale, restored?.sheet.root?.fsPath, restored?.matches(input), serializer.deserialize(undefined!, '{')], [
			'S-101', 'Ground floor framing plan', URI.file('C:\\p\\S-101.png').fsPath, URI.file('C:\\p\\S-101.dxf').fsPath, true, root.fsPath, true, undefined,
		]);
		input.dispose();
		restored?.dispose();
	});

	test('an unchanged answer is the same set, a changed one is not', () => {
		const set = readDrawingSet(answer, root);
		const again = readDrawingSet(JSON.parse(JSON.stringify(answer)), root);
		// A URI that has worked out its fsPath (cached state) is still the same file.
		assert.ok(again?.sheets[0].png?.fsPath);
		const stale = readDrawingSet({ ...answer, stamps: { stale: true } }, root);
		assert.deepStrictEqual([drawingSetKey(set) === drawingSetKey(again), drawingSetKey(set) === drawingSetKey(stale), drawingSetKey(undefined)], [true, false, '']);
	});

	test('a preview changes only when its sheet does', () => {
		const sheet = { number: 'S-101', title: 'Ground floor framing plan', png: URI.file('C:\\p\\S-101.png'), dxf: URI.file('C:\\p\\S-101.dxf'), size: 'A1' };
		const input = new DrawingPreviewInput(sheet);
		const changes: string[] = [];
		const listener = input.onDidChangeSheet(s => changes.push(`${s.number} ${s.stale ? 'stale' : 'current'}`));
		const results = [
			input.update({ ...sheet, png: URI.file('C:\\p\\S-101.png'), stale: false }),
			input.update({ ...sheet, stale: true }),
			input.update({ ...sheet, stale: true }),
		];
		// The sheet of a (re-)listed set, found by its picture, as the preview shows it.
		const set = readDrawingSet(answer, root);
		const found = findPreviewSheet(set, inDrawings('S-201.png'), root);
		assert.deepStrictEqual([results, changes, sameSheet(sheet, { ...sheet, title: 'other' }), found?.number, found?.stale, found?.pdf?.fsPath, found?.root?.fsPath, findPreviewSheet(set, URI.file('C:\\x.png'), root)], [
			[false, true, false], ['S-101 stale'], false, 'S-201', true, set?.pdf?.fsPath, root.fsPath, undefined,
		]);
		listener.dispose();
		input.dispose();
	});
});
