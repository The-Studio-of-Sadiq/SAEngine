/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import {
	archiveSummaryLines, defaultArchiveName, dxfCommandTarget, exportArgs, formatSize, importArgs, lastArchiveDescription, projectNameForArchive, readArchiveManifest, safeFolderName, uniqueFolderName,
} from '../../browser/projectArchiveModel.js';
import { readLastArchive } from '../../browser/projectArchiveFlows.js';

suite('SAEngine - project archive', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	test('the command arguments', () => {
		assert.deepStrictEqual([
			exportArgs('C:\\Projects\\Frame', 'C:\\Projects\\Frame 2026-10-19'),
			exportArgs('C:\\Projects\\Frame', 'C:\\out\\frame.CIVIL', { includeResults: true, includeVersions: false, includeExports: false }),
			importArgs('C:\\in\\frame.civil', 'C:\\Projects', ' Frame (2) '),
		], [
			{ projectRoot: 'C:\\Projects\\Frame', outPath: 'C:\\Projects\\Frame 2026-10-19.civil', includeResults: false, includeVersions: true, includeExports: true },
			{ projectRoot: 'C:\\Projects\\Frame', outPath: 'C:\\out\\frame.CIVIL', includeResults: true, includeVersions: false, includeExports: false },
			{ path: 'C:\\in\\frame.civil', destParent: 'C:\\Projects', name: 'Frame (2)' },
		]);
	});

	test('names and sizes', () => {
		const taken = new Set(['sample frame', 'sample frame (2)']);
		assert.deepStrictEqual([
			defaultArchiveName('Sample Frame', new Date(2026, 9, 9)),
			defaultArchiveName('  ', new Date(2026, 0, 1)),
			projectNameForArchive('Sample Frame 2026-10-09.civil'),
			projectNameForArchive('frame.civil', ' Six Storey Frame '),
			uniqueFolderName('Sample Frame', name => taken.has(name.toLowerCase())),
			uniqueFolderName('Other', name => taken.has(name.toLowerCase())),
			// As archive.safe_name() cleans it, so the second import of 'Road 5: Block A' gets "(2)".
			uniqueFolderName('Road 5: Block A', name => name.toLowerCase() === 'road 5- block a'),
			safeFolderName(' Block A/B? ... '),
			safeFolderName('con'),
			safeFolderName('Nul.txt'),
			safeFolderName('...'),
			formatSize(undefined),
			formatSize(512),
			formatSize(740 * 1024),
			formatSize(12.44 * 1024 * 1024),
			formatSize(240 * 1024 * 1024),
		], [
			'Sample Frame 2026-10-09.civil',
			'Project 2026-01-01.civil',
			'Sample Frame',
			'Six Storey Frame',
			'Sample Frame (3)',
			'Other',
			'Road 5- Block A (2)',
			'Block A-B-',
			'con_',
			'Nul.txt_',
			'Project',
			'',
			'512 B',
			'740 KB',
			'12.4 MB',
			'240 MB',
		]);
	});

	test('the manifest of saengine.project.inspectArchive is summarised for the open dialog', () => {
		// The shape of python/src/saengine/project/archive.py inspect_archive().
		const manifest = readArchiveManifest({
			manifest: {
				format: 'saengine-project',
				saengineVersion: '0.0.34',
				created: '2026-10-19T06:30:00Z',
				project: { name: 'Sample Frame', file: 'Sample Frame.saengine', type: 'building' },
				parts: [
					{ id: 'soil', folder: '01 Soil Report', files: [] },
					{ id: 'settings', folder: '02 Project Settings', files: [] },
					{ id: 'floorPlan', folder: '05 Floor Plan', files: [] },
					{ id: 'mep', folder: '07 MEP', missing: true, files: [] },
					{ id: 'fem', folder: '08 FEM', files: [] },
				],
				files: [{ path: 'Sample Frame.saengine' }],
				includes: { results: false, versions: true, exports: true },
			},
			problems: [
				{ code: 'versions', severity: 'warning', message: 'includes a version history: its git settings are reset and its hooks are not extracted' },
				{ code: 'part', severity: 'error', message: 'MEP is missing.' },
			],
			ok: true,
			files: 14,
			size: 740 * 1024,
		});
		assert.deepStrictEqual({ manifest: { ...manifest, created: undefined }, created: manifest.created, lines: archiveSummaryLines({ ...manifest, created: undefined }, 'frame.civil') }, {
			manifest: {
				name: 'Sample Frame',
				type: 'building',
				appVersion: '0.0.34',
				created: undefined,
				parts: ['soil', 'settings', 'floorPlan', 'fem'],
				size: 740 * 1024,
				files: 14,
				includesResults: false,
				includesVersions: true,
				versions: undefined,
				ok: true,
				problems: ['MEP is missing.'],
				notes: ['includes a version history: its git settings are reset and its hooks are not extracted'],
			},
			created: Date.UTC(2026, 9, 19, 6, 30),
			lines: [
				'Project: Sample Frame',
				'Written by SAEngine 0.0.34',
				'Parts (4): Soil Report, Project Settings, Floor Plan, FEM',
				'740 KB · without results · with versions',
				'Problems: MEP is missing.',
				'Note: Includes a version history: its git settings are reset and its hooks are not extracted.',
			],
		});
	});

	test('a file that is not an archive reads as no parts and its problems', () => {
		assert.deepStrictEqual(readArchiveManifest({ problems: [{ message: 'Not a zip file.' }] }).parts, []);
		assert.deepStrictEqual(readArchiveManifest(undefined).problems, []);
	});

	test('the last archive is described where it is', () => {
		const root = URI.file('/work/Frame');
		assert.deepStrictEqual([
			lastArchiveDescription(URI.file('/work/Frame 2026-10-19.civil'), 2048, root),
			lastArchiveDescription(URI.file('/outbox/Frame.civil'), 2048, root),
		], [
			`Frame 2026-10-19.civil (${formatSize(2048)}), next to the project folder`,
			`Frame.civil (${formatSize(2048)}) in ${URI.file('/outbox').fsPath}`,
		]);
	});

	test('the DXF and the last archive given to the commands', () => {
		const file = URI.file('/p/11 Exports/Floor Plan/Ground.dxf');
		assert.deepStrictEqual([
			dxfCommandTarget(file)?.toString(),
			dxfCommandTarget(file.fsPath)?.toString(),
			dxfCommandTarget({ path: file.fsPath })?.toString(),
			dxfCommandTarget({ resource: file })?.toString(),
			dxfCommandTarget(file.toString())?.toString(),
			dxfCommandTarget(undefined),
			dxfCommandTarget(' '),
			readLastArchive('{"path":"C:\\\\a.civil","time":5,"size":10}'),
			readLastArchive('{"path":3}'),
			readLastArchive('not json'),
		], [
			file.toString(), file.toString(), file.toString(), file.toString(), file.toString(), undefined, undefined,
			{ path: 'C:\\a.civil', time: 5, size: 10 },
			undefined,
			undefined,
		]);
	});
});
