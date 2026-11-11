/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { anonymise, buildReport, FEEDBACK_DESTINATION, formProblem, issueRequest, MAX_URL_LENGTH } from '../../common/feedback.js';

suite('SAEngine feedback and diagnostics', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	const form = { kind: 'bug' as const, title: 'Design stops', description: 'It stops at storey 7.', steps: '1. Run All', email: '' };

	test('the report holds only what was ticked, and says where it goes', () => {
		const report = buildReport(form, {}, { version: '0.0.49', os: 'win32 10 x64' });
		assert.strictEqual(report.title, '[Bug] Design stops');
		assert.ok(report.body.includes('Steps to reproduce'));
		assert.ok(!report.body.includes('Diagnostics'));
		const request = issueRequest(report);
		assert.ok(request.url.startsWith(`${FEEDBACK_DESTINATION.url}?title=`));
		assert.strictEqual(request.clipboard, undefined);
	});

	test('a long report goes by the clipboard', () => {
		const report = buildReport({ ...form, description: 'x'.repeat(MAX_URL_LENGTH) }, {}, { version: '1', os: 'os' });
		const request = issueRequest(report);
		assert.ok(request.url.length <= MAX_URL_LENGTH);
		assert.strictEqual(request.clipboard, report.body);
	});

	test('the form needs a title and a description', () => {
		assert.ok(formProblem({ ...form, title: ' ' }));
		assert.ok(formProblem({ ...form, description: '' }));
		assert.ok(formProblem({ ...form, email: 'not-an-email' }));
		assert.strictEqual(formProblem(form), undefined);
	});

	test('anonymising removes folders, names and e-mail addresses', () => {
		const text = anonymise('C:\\Users\\rahim\\Projects\\Tower A\\08 FEM failed; /home/rahim/x; mail rahim@example.com; Tower A opened', {
			home: 'C:\\Users\\rahim', userName: 'rahim', projectRoot: 'C:\\Users\\rahim\\Projects\\Tower A', projectName: 'Tower A',
		});
		assert.ok(!/rahim|Tower A/i.test(text), text);
		assert.ok(text.includes('<project>') && text.includes('<email>') && text.includes('<home>'), text);
	});
});
