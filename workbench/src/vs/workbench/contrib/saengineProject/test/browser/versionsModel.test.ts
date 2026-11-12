/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { partOfResource } from '../../browser/projectEdits.js';
import {
	changeGroups, compareRange, compareTitle, diffArgs, hasIssueLabel, issuedBadge, markIssuedArgs, nextSelection, partsSummary, pendingParts, readDiff, readStatus, readVersions,
	relativeTime, restoreArgs, restoreConfirmation, saveArgs, unsavedSummary, versionDetail, versionTitle,
} from '../../browser/versionsModel.js';

const NOW = Date.UTC(2026, 9, 19, 12, 0, 0);
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Three versions as the backend lists them, newest first (the history order): v1 in versions.py's
 * own shape (git's "Name <email>" author beside authorName, an ISO time, part ids with 'project'
 * for the project file), the others with older field names (times in seconds or ms, issued as
 * {label}, folder paths).
 */
const LISTED = {
	versions: [
		{ commit: 'c3d4e5f6a7', number: 3, summary: 'Column sizes after the wind check', author: 'Engineer B <engineer.b@example.com>', date: NOW - 5 * MINUTE, partsChanged: [{ part: '09 Substructure/substructure.json' }] },
		{ sha: 'b2c3d4e5f6', number: 2, message: 'Issued for approval', author: 'Engineer A', timestamp: new Date(NOW - 2 * DAY).toISOString(), issued: { label: 'Rev A' }, changed_parts: ['bim', 'fem', 'substructure', 'boq'] },
		{
			id: 'a1b2c3d', sha: 'a1b2c3d4e5', number: 1, message: 'First layout', author: 'Engineer A <engineer.a@example.com>', authorName: 'Engineer A', authorEmail: 'engineer.a@example.com',
			time: new Date(NOW - 10 * DAY).toISOString(), timestamp: (NOW - 10 * DAY) / 1000, issued: false, label: null, parts: ['floorPlan', 'settings', 'project'],
		},
	],
};

suite('SAEngine - versions', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('the list reads leniently, newest first, and formats each row', () => {
		const versions = readVersions(LISTED);
		assert.deepStrictEqual(versions.map(v => ({
			id: v.id,
			title: versionTitle(v),
			badge: issuedBadge(v),
			detail: versionDetail(v, NOW),
		})), [
			{ id: 'c3d4e5f6a7', title: 'v3 · Column sizes after the wind check', badge: undefined, detail: 'Engineer B · 5 min ago · Substructure' },
			{ id: 'b2c3d4e5f6', title: 'v2 · Issued for approval', badge: 'Issued · Rev A', detail: 'Engineer A · 2 days ago · BIM, FEM, Substructure +1' },
			{ id: 'a1b2c3d', title: 'v1 · First layout', badge: undefined, detail: `Engineer A · ${relativeTime(NOW - 10 * DAY, NOW)} · Floor Plan, Project Settings, Project file` },
		]);
	});

	test('relative times and part summaries', () => {
		assert.deepStrictEqual([
			relativeTime(undefined, NOW),
			relativeTime(NOW - 20_000, NOW),
			relativeTime(NOW - 12 * MINUTE, NOW),
			relativeTime(NOW - 3 * HOUR, NOW),
			relativeTime(NOW - DAY, NOW),
			relativeTime(NOW - 4 * DAY, NOW),
			partsSummary([]),
			partsSummary(['soil', 'floorPlan']),
		], ['', 'just now', '12 min ago', '3 h ago', 'yesterday', '4 days ago', 'No part changed', 'Soil Report, Floor Plan']);
	});

	test('the history order is kept even when the clocks of the saving machines disagree; every issue label shows', () => {
		const versions = readVersions({
			versions: [
				// v3 was saved on a machine whose clock is behind: still the latest.
				{ id: 'c3', number: 3, message: 'Third', time: (NOW - 3 * DAY) / 1000, issued: false, label: null, labels: [], parts: [] },
				{ id: 'b2', number: 2, message: 'Second', time: (NOW - HOUR) / 1000, issued: true, label: 'Rev B', labels: ['Rev A', 'Rev B'], parts: [] },
				{ id: 'a1', number: 1, message: 'First', time: (NOW - 2 * DAY) / 1000, issued: false, label: null, labels: [], parts: [] },
			],
		});
		const [, v2] = versions;
		assert.deepStrictEqual({
			order: versions.map(v => v.id),
			pair: compareTitle(compareRange(versions, ['c3', 'a1'])!.from, compareRange(versions, ['c3', 'a1'])!.to),
			badge: issuedBadge(v2),
			labels: [hasIssueLabel(v2, ' Rev A '), hasIssueLabel(v2, 'Rev B'), hasIssueLabel(v2, 'Rev C'), hasIssueLabel(versions[0], 'Rev A')],
		}, {
			order: ['c3', 'b2', 'a1'],
			pair: 'v1 → v3',
			badge: 'Issued · Rev A, Rev B',
			labels: [true, true, false, false],
		});
	});

	test('edits not saved yet count as changes, under their part', () => {
		const root = URI.file('/Projects/Frame');
		const head = { id: 'c3d4e5f6a7', number: 12, message: 'x' };
		assert.deepStrictEqual({
			parts: [
				partOfResource(root, URI.file('/Projects/Frame/05 Floor Plan/floor-plan.json')),
				partOfResource(root, URI.file('/Projects/Frame/Frame.saengine')),
				partOfResource(root, URI.file('/Projects/Frame/Notes/site visit.md')),
				partOfResource(root, URI.file('/Projects/Other/05 Floor Plan/floor-plan.json')),
				partOfResource(root, URI.from({ scheme: 'untitled', path: 'Untitled-1' })),
			],
			pending: pendingParts(readStatus({ head, changedParts: ['fem'] }), ['floorPlan', 'fem']),
			clean: unsavedSummary(readStatus({ head, changedParts: [] }), ['floorPlan']),
		}, {
			parts: ['floorPlan', 'project', 'Notes', undefined, undefined],
			pending: ['fem', 'floorPlan'],
			clean: { text: '1 part changed since v12', dirty: true },
		});
	});

	test('the unsaved-changes line of the sidebar', () => {
		const INSIDE_REPO = 'The project is inside the git repository C:\\work; Versions are not kept for a project inside another repository.';
		const head = { id: 'c3d4e5f6a7', number: 12, message: 'x' };
		assert.deepStrictEqual([
			unsavedSummary(undefined),
			unsavedSummary(readStatus({ initialized: false })),
			unsavedSummary(readStatus({ head, changedParts: [] })),
			unsavedSummary(readStatus({ head, changed_parts: ['05 Floor Plan', 'fem'] })),
			unsavedSummary(readStatus({ head, changedParts: ['fem', 'substructure', 'bim'] })),
			// versions.status() for a project inside another git repository.
			unsavedSummary(readStatus({ initialized: false, head: null, changedParts: ['fem'], problems: [INSIDE_REPO] })),
			// The status command failed (the service's stand-in status).
			unsavedSummary({ initialized: false, changedParts: [], problems: ['RPC timed out'], failed: true }),
		], [
			undefined,
			{ text: 'No version saved yet', dirty: true },
			{ text: 'No changes since v12', dirty: false },
			{ text: '2 parts changed since v12', dirty: true },
			{ text: '3 parts changed since v12', dirty: true },
			{ text: 'Versions are not kept for this project', dirty: false, problem: INSIDE_REPO },
			{ text: 'Versions could not be read', dirty: false, problem: 'RPC timed out' },
		]);
	});

	test('the diff is grouped by part in workflow order, with the backend words and plain values only', () => {
		const diff = readDiff({
			from: 'b2c3d4e5f6',
			// diff.py's shape: `what` already says the values; an added or removed item carries the whole item.
			parts: [
				{
					part: 'floorPlan', title: 'Floor Plan', summary: '3 changes', changes: [
						{ kind: 'removed', id: 'A', what: 'Grid line A removed', before: { label: 'A', position: 0 }, after: null, path: 'grid.x[0]' },
						{ kind: 'changed', id: 'B', what: 'Grid line B: position 6000 → 6600 mm', before: 6000, after: 6600.000000100001, path: 'grid.x[1].position' },
						{ kind: 'added', id: 'C9', what: 'Column C9 added', before: null, after: { x: 3, y: 4 }, path: 'columns[8]' },
					],
				},
				{ part: 'project', title: 'Project', changes: [{ kind: 'changed', what: 'Project file Frame.saengine modified', before: null, after: null, path: '' }] },
				{ part: 'fem', summary: 'Model regenerated' },
			],
			// The flat, older shape: a bare path gets its plain values under it.
			changes: [
				{ part: 'substructure', op: 'replace', path: ['members', 'C3', 'section'], before: '300×300', after: '350×350' },
				{ part: 'substructure', kind: 'removed', label: 'Beam B12' },
				{ file: 'notes.txt', label: 'notes.txt' },
				{ part: 'bim', kind: 'changed', path: 'grid.x[1].position', before: 6000, after: 6600.000000100001 },
				{ part: 'bim', kind: 'added', path: 'walls[3]', after: { id: 'W3' } },
			],
			problems: [{ message: 'The FEM results are not compared.' }],
		});
		assert.deepStrictEqual({ groups: changeGroups(diff, 2), problems: diff.problems }, {
			groups: [
				{
					part: 'floorPlan', title: 'Floor Plan', count: '3 changes', lines: [
						{ kind: 'removed', text: 'Grid line A removed', values: undefined },
						{ kind: 'changed', text: 'Grid line B: position 6000 → 6600 mm', values: undefined },
					], more: 1,
				},
				{
					part: 'bim', title: 'BIM', count: '2 changes', lines: [
						{ kind: 'changed', text: 'grid.x[1].position', values: '6000 → 6600' },
						{ kind: 'added', text: 'walls[3]', values: undefined },
					], more: 0,
				},
				{ part: 'fem', title: 'FEM', count: '1 change', lines: [{ kind: 'changed', text: 'Model regenerated', values: undefined }], more: 0 },
				{
					part: 'substructure', title: 'Substructure', count: '2 changes', lines: [
						{ kind: 'changed', text: 'members.C3.section', values: '300×300 → 350×350' },
						{ kind: 'removed', text: 'Beam B12', values: undefined },
					], more: 0,
				},
				{ part: 'project', title: 'Project file', count: '1 change', lines: [{ kind: 'changed', text: 'Project file Frame.saengine modified', values: undefined }], more: 0 },
				{ part: '', title: 'Other files', count: '1 change', lines: [{ kind: 'changed', text: 'notes.txt', values: undefined }], more: 0 },
			],
			problems: ['The FEM results are not compared.'],
		});
	});

	test('the command arguments', () => {
		assert.deepStrictEqual([
			saveArgs('C:\\p', '  Rev B issue  ', { issued: true, label: ' Rev B ', author: ' ' }),
			saveArgs('C:\\p', 'Work in progress', { issued: false, label: 'ignored' }),
			diffArgs('C:\\p', 'v1'),
			diffArgs('C:\\p', 'v1', 'v2'),
			restoreArgs('C:\\p', 'v1'),
			restoreArgs('C:\\p', 'v1', ['fem', 'substructure'], ['substructure', 'fem']),
			restoreArgs('C:\\p', 'v1', ['fem'], ['substructure', 'fem']),
			markIssuedArgs('C:\\p', 'v2', ' Rev A '),
		], [
			{ projectRoot: 'C:\\p', message: 'Rev B issue', issued: true, label: 'Rev B' },
			{ projectRoot: 'C:\\p', message: 'Work in progress', issued: false },
			{ projectRoot: 'C:\\p', from: 'v1' },
			{ projectRoot: 'C:\\p', from: 'v1', to: 'v2' },
			{ projectRoot: 'C:\\p', version: 'v1' },
			{ projectRoot: 'C:\\p', version: 'v1' },
			{ projectRoot: 'C:\\p', version: 'v1', parts: ['fem'] },
			{ projectRoot: 'C:\\p', version: 'v2', label: 'Rev A' },
		]);
	});

	test('selection, comparison and the restore confirmation', () => {
		const versions = readVersions(LISTED);
		const [v3, v2, v1] = versions;
		const one = nextSelection([], v3.id, false);
		const two = nextSelection(one, v1.id, true);
		const three = nextSelection(two, v2.id, true);
		const range = compareRange(versions, two)!;
		assert.deepStrictEqual({
			one, two, three,
			untoggled: nextSelection(two, v3.id, true),
			current: compareTitle(compareRange(versions, one)!.from, undefined),
			pair: compareTitle(range.from, range.to),
			restore: restoreConfirmation(v2, ['fem', 'substructure'], ['substructure', 'project']),
			clean: restoreConfirmation(v2, ['fem'], []).detail,
		}, {
			one: [v3.id],
			two: [v3.id, v1.id],
			three: [v1.id, v2.id],
			untoggled: [v1.id],
			current: 'v3 → current files',
			pair: 'v1 → v3',
			restore: {
				message: 'Restore v2 · Issued for approval?',
				// versions.restore() first saves the unsaved work as "Before restoring version 2 (...)".
				detail: 'These parts will be replaced by their state in v2: FEM, Substructure.\n\nYour unsaved changes (in Substructure, Project file) are first saved as a version of their own, so nothing is lost.\n\nThe restore is then saved as a new version; the earlier versions stay as they are.',
			},
			clean: 'These parts will be replaced by their state in v2: FEM.\n\nThe restore is then saved as a new version; the earlier versions stay as they are.',
		});
	});
});
