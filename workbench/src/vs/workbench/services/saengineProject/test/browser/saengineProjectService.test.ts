/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { timeout } from '../../../../../base/common/async.js';
import { VSBuffer } from '../../../../../base/common/buffer.js';
import { Event } from '../../../../../base/common/event.js';
import { Schemas } from '../../../../../base/common/network.js';
import { joinPath } from '../../../../../base/common/resources.js';
import { URI } from '../../../../../base/common/uri.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { runWithFakedTimers } from '../../../../../base/test/common/virtualScheduling/index.js';
import { FileService } from '../../../../../platform/files/common/fileService.js';
import { InMemoryFileSystemProvider } from '../../../../../platform/files/common/inMemoryFilesystemProvider.js';
import { NullLogService } from '../../../../../platform/log/common/log.js';
import { INotificationHandle, NoOpNotification } from '../../../../../platform/notification/common/notification.js';
import { TestNotificationService } from '../../../../../platform/notification/test/common/testNotificationService.js';
import { UriIdentityService } from '../../../../../platform/uriIdentity/common/uriIdentityService.js';
import { testWorkspace } from '../../../../../platform/workspace/test/common/testWorkspace.js';
import { TestDecorationsService } from '../../../../test/browser/workbenchTestServices.js';
import { TestContextService } from '../../../../test/common/workbenchTestServices.js';
import { SaengineProjectService } from '../../browser/saengineProjectService.js';
import { ISaengineProject, PROJECT_PARTS } from '../../common/saengineProject.js';

class RecordingNotificationService extends TestNotificationService {
	readonly messages: string[] = [];
	override info(message: string): INotificationHandle {
		this.messages.push(message);
		return new NoOpNotification();
	}
}

suite('SAEngine - ProjectService', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();
	const root = URI.from({ scheme: Schemas.inMemory, path: '/projects/Office' });

	let fileService: FileService;
	let notifications: RecordingNotificationService;

	setup(() => {
		fileService = store.add(new FileService(new NullLogService()));
		store.add(fileService.registerProvider(Schemas.inMemory, store.add(new InMemoryFileSystemProvider())));
		notifications = new RecordingNotificationService();
	});

	function createService(folder = root): SaengineProjectService {
		return store.add(new SaengineProjectService(
			fileService,
			new TestContextService(testWorkspace(folder)),
			store.add(new UriIdentityService(fileService)),
			notifications,
			new TestDecorationsService(),
			new NullLogService(),
		));
	}

	async function listing(folder: URI): Promise<string[]> {
		const result: string[] = [];
		for (const child of (await fileService.resolve(folder)).children ?? []) {
			result.push(child.isDirectory ? `${child.name}/` : child.name);
			if (child.isDirectory) {
				result.push(...(await listing(child.resource)).map(n => `${child.name}/${n}`));
			}
		}
		return result.sort();
	}

	async function detected(service: SaengineProjectService): Promise<ISaengineProject | undefined> {
		return service.project ?? Event.toPromise(service.onDidChangeProject);
	}

	test('creates the fixed structure and keeps existing files', async () => {
		await fileService.writeFile(joinPath(root, '03 Materials', 'concrete.json'), VSBuffer.fromString('{}'));
		const service = createService(URI.from({ scheme: Schemas.inMemory, path: '/elsewhere' }));

		const project = await service.createProject(root, 'Office');
		const fem = (await fileService.readFile(joinPath(root, '08 FEM', 'model.osmodel'))).value.toString();
		const materials = JSON.parse((await fileService.readFile(joinPath(root, '03 Materials', 'materials.json'))).value.toString());

		assert.deepStrictEqual({
			name: project.name,
			files: await listing(root),
			fem: JSON.parse(fem),
			materials: { schema: materials.schema, first: materials.materials[0].id, count: materials.materials.length },
		}, {
			name: 'Office',
			files: [
				'01 Soil Report/', '01 Soil Report/soil-report.json',
				'02 Project Settings/', '02 Project Settings/project-settings.json',
				'03 Materials/', '03 Materials/concrete.json', '03 Materials/materials.json',
				'04 Objects/', '04 Objects/objects.json',
				'05 Floor Plan/', '05 Floor Plan/floor-plan.json',
				'06 BIM/', '06 BIM/bim.json',
				'07 MEP/', '07 MEP/mep.json',
				'08 FEM/', '08 FEM/model.osmodel',
				'09 Substructure/', '09 Substructure/substructure.json',
				'10 BOQ/', '10 BOQ/boq.json',
				'11 Exports/',
				'Office.saengine',
			],
			fem: { schema_version: 2, meta: { name: 'Office' } },
			materials: { schema: 'saengine.materials/1', first: 'C20.7', count: 12 },
		});
	});

	test('protects only the core items of the open project', async () => {
		await createService(URI.from({ scheme: Schemas.inMemory, path: '/elsewhere' })).createProject(root, 'Office');
		const service = createService();
		await detected(service);

		const check = (path: string) => service.isProtected(joinPath(root, path));
		assert.deepStrictEqual({
			manifest: check('Office.saengine'),
			partFolders: PROJECT_PARTS.every(p => check(p.folder)),
			mainFile: check('08 FEM/model.osmodel'),
			userFile: check('03 Materials/concrete.json'),
			userFolder: check('drawings'),
			root: service.isProtected(root),
		}, { manifest: true, partFolders: true, mainFile: true, userFile: false, userFolder: false, root: false });
	});

	test('restores core items deleted outside the workbench', () => runWithFakedTimers({ useFakeTimers: true }, async () => {
		await createService(URI.from({ scheme: Schemas.inMemory, path: '/elsewhere' })).createProject(root, 'Office');
		const service = createService();
		await detected(service);
		await timeout(1000); // opened: the quiet check for missing items is done

		await fileService.del(joinPath(root, '04 Objects'), { recursive: true });
		await fileService.del(joinPath(root, '08 FEM', 'model.osmodel'));
		await timeout(1000);

		assert.deepStrictEqual({
			objects: await fileService.exists(joinPath(root, '04 Objects', 'objects.json')),
			model: await fileService.exists(joinPath(root, '08 FEM', 'model.osmodel')),
			notified: notifications.messages.length > 0,
		}, { objects: true, model: true, notified: true });
	}));

	test('a special structure has a structural model as Part 5, and the type can change', async () => {
		await createService(URI.from({ scheme: Schemas.inMemory, path: '/elsewhere' })).createProject(root, 'Terminal', 'structure');
		const service = createService();
		const project = await detected(service);
		const manifest = () => fileService.readFile(joinPath(root, 'Terminal.saengine')).then(f => JSON.parse(f.value.toString()));
		const before = {
			type: project?.type,
			manifest: (await manifest()).type,
			structure: service.isProtected(joinPath(root, '05 Structural Model', 'structure.json')),
			floorPlan: await fileService.exists(joinPath(root, '05 Floor Plan')),
			parts: service.parts.map(p => p.id).slice(3, 6),
		};

		await service.setProjectType('building');
		assert.deepStrictEqual({
			before,
			after: {
				type: service.project?.type,
				manifest: (await manifest()).type,
				floorPlan: service.isProtected(joinPath(root, '05 Floor Plan', 'floor-plan.json')) && await fileService.exists(joinPath(root, '05 Floor Plan', 'floor-plan.json')),
				// The structural model stays with its files, as a plain folder.
				structure: [service.isProtected(joinPath(root, '05 Structural Model')), await fileService.exists(joinPath(root, '05 Structural Model', 'structure.json'))],
			},
		}, {
			before: { type: 'structure', manifest: 'structure', structure: true, floorPlan: false, parts: ['objects', 'structure', 'bim'] },
			after: { type: 'building', manifest: 'building', floorPlan: true, structure: [false, true] },
		});
	});

	test('is not a project without a manifest', async () => {
		await fileService.createFolder(root);
		const service = createService();
		assert.strictEqual(await service.findProject(root), undefined);
		assert.strictEqual(service.isProtected(joinPath(root, '08 FEM')), false);
	});
});
