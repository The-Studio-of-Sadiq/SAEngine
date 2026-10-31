/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { isPartEditor, isSectionActive, partSections, splitProjectPath, stateText } from '../../browser/projectParts.js';

suite('SAEngine - project parts', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('project paths keep their last folders and are home-relative', () => {
		const home = URI.file('/home/eng');
		const sep = URI.file('/a/b').fsPath.includes('\\') ? '\\' : '/';
		const join = (...segments: string[]) => segments.join(sep);
		assert.deepStrictEqual([
			splitProjectPath(URI.file('/home/eng/Documents/SAEngine Projects/Sample Frame'), home),
			splitProjectPath(URI.file('/home/eng/Sample Frame'), home),
			splitProjectPath(URI.file('/home/eng'), home),
			splitProjectPath(URI.file('/home/eng/Documents/SAEngine Projects/Sample Frame'), undefined),
		], [
			{ head: join('~', 'Documents', ''), tail: join('SAEngine Projects', 'Sample Frame') },
			{ head: '', tail: join('~', 'Sample Frame') },
			{ head: '', tail: '~' },
			{ head: join(URI.file('/home').fsPath, 'eng', 'Documents', ''), tail: join('SAEngine Projects', 'Sample Frame') },
		]);
	});

	test('a part without its own text shows its state in lower case', () => {
		assert.deepStrictEqual([
			stateText({ part: 'bim', state: 'done', text: '' }),
			stateText({ part: 'fem', state: 'failed', text: '3 fail' }),
			stateText(undefined),
		], ['done', '3 fail', 'not started']);
	});

	test('the entries under a part: which one the active editor shows', () => {
		const entry = (part: string, id: string) => partSections(part).find(e => e.id === id)!;
		const editor = (typeId: string, editorId?: string) => ({ typeId, editorId });
		const floorPlan = editor('workbench.input.saengine.floorPlan', 'workbench.editor.saengine.floorPlan');
		const grids = editor('workbench.input.saengine.library', 'workbench.editor.saengine.grids');
		const charts = editor('workbench.input.saengine.femResults', 'workbench.editor.saengine.femResults');
		const member = editor('workbench.input.saengine.femMember', 'workbench.editor.saengine.femResults');
		const architecture = editor('workbench.input.saengine.architecture', 'workbench.editor.saengine.architecture');
		assert.deepStrictEqual({
			parts: ['settings', 'floorPlan', 'bim', 'mep', 'fem', 'soil'].map(part => partSections(part).map(e => e.id).join(' ')),
			// A section of the part's editor: Combinations and Analysis also stands for the analysis settings.
			seismic: isSectionActive(entry('settings', 'seismic'), editor('workbench.input.saengine.library'), 'seismic'),
			analysis: isSectionActive(entry('settings', 'combinations'), editor('workbench.input.saengine.library'), 'analysis'),
			wind: isSectionActive(entry('settings', 'wind'), editor('workbench.input.saengine.library'), 'seismic'),
			// The plan and the grids show the same file in different editors.
			plan: [isSectionActive(entry('floorPlan', 'plan'), floorPlan, undefined), isSectionActive(entry('floorPlan', 'plan'), grids, undefined)],
			grids: [isSectionActive(entry('floorPlan', 'grids'), grids, undefined), isSectionActive(entry('floorPlan', 'grids'), floorPlan, undefined)],
			// The charts have no file: they still belong to 8 FEM.
			charts: [isSectionActive(entry('fem', 'results'), charts, undefined), isPartEditor('fem', charts), isPartEditor('floorPlan', charts)],
			// A member's page belongs to Model and Analysis, where the member was picked.
			member: [isSectionActive(entry('fem', 'model'), member, undefined), isSectionActive(entry('fem', 'results'), member, undefined), isPartEditor('fem', member)],
			// The architecture is 05 Floor Plan's file in its own editor, listed under 6 BIM.
			architecture: [entry('bim', 'architecture').command, isSectionActive(entry('bim', 'architecture'), architecture, undefined), isPartEditor('bim', architecture), isPartEditor('floorPlan', architecture)],
		}, {
			parts: ['code loads seismic wind combinations foundation drawings', 'plan grids members', '3d additions summary architecture', 'coordination plumbing hvac electrical fire', 'model results proposal', ''],
			seismic: true,
			analysis: true,
			wind: false,
			plan: [true, false],
			grids: [true, false],
			charts: [true, true, false],
			member: [true, false, true],
			architecture: ['saengine.architecture.open', true, true, false],
		});
	});
});
