/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { splitProjectPath, stateText } from '../../browser/projectParts.js';

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
			{ head: join('~', ''), tail: join('Documents', 'SAEngine Projects', 'Sample Frame') },
			{ head: '', tail: join('~', 'Sample Frame') },
			{ head: '', tail: '~' },
			{ head: join(URI.file('/home').fsPath, 'eng', ''), tail: join('Documents', 'SAEngine Projects', 'Sample Frame') },
		]);
	});

	test('a part without its own text shows its state in lower case', () => {
		assert.deepStrictEqual([
			stateText({ part: 'bim', state: 'done', text: '' }),
			stateText({ part: 'fem', state: 'failed', text: '3 fail' }),
			stateText(undefined),
		], ['done', '3 fail', 'not started']);
	});
});
