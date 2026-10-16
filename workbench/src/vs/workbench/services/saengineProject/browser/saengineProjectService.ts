/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { ResourceSet } from '../../../../base/common/map.js';
import { basename, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { FileChangeType, IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IUriIdentityService } from '../../../../platform/uriIdentity/common/uriIdentity.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IDecorationData, IDecorationsService } from '../../decorations/common/decorations.js';
import { Extensions as JSONExtensions, IJSONContributionRegistry } from '../../../../platform/jsonschemas/common/jsonContributionRegistry.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ALL_PARTS, createManifest, IProjectManifest, IProjectPart, ISaengineProject, ISaengineProjectService, PROJECT_MANIFEST_EXTENSION, PROJECT_PARTS, projectParts, ProjectType } from '../common/saengineProject.js';

const schemaRegistry = Registry.as<IJSONContributionRegistry>(JSONExtensions.JSONContribution);

export class SaengineProjectService extends Disposable implements ISaengineProjectService {

	declare readonly _serviceBrand: undefined;

	private _project: ISaengineProject | undefined;
	get project(): ISaengineProject | undefined { return this._project; }

	private readonly _onDidChangeProject = this._register(new Emitter<ISaengineProject | undefined>());
	readonly onDidChangeProject = this._onDidChangeProject.event;

	private readonly _onDidChangeDecorations = this._register(new Emitter<URI[]>());

	private protectedResources: ResourceSet;
	private readonly projectDisposables = this._register(new DisposableStore());
	private readonly restoreScheduler = this._register(new RunOnceScheduler(() => this.restoreStructure(true), 500));

	constructor(
		@IFileService private readonly fileService: IFileService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IUriIdentityService private readonly uriIdentityService: IUriIdentityService,
		@INotificationService private readonly notificationService: INotificationService,
		@IDecorationsService decorationsService: IDecorationsService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		this.protectedResources = this.newResourceSet();

		this._register(decorationsService.registerDecorationsProvider({
			label: localize('saengineProject.decorations', "SAEngine Project"),
			onDidChange: this._onDidChangeDecorations.event,
			provideDecorations: uri => this.provideDecoration(uri),
		}));

		for (const part of ALL_PARTS) {
			if (part.schema) {
				schemaRegistry.registerSchema(part.schema.id, part.schema.schema, this._store);
			}
		}

		this._register(this.contextService.onDidChangeWorkspaceFolders(() => this.detect()));
		void this.detect();
	}

	get parts(): readonly IProjectPart[] {
		return this._project ? projectParts(this._project.type) : PROJECT_PARTS;
	}

	isProtected(resource: URI): boolean {
		return this.protectedResources.has(resource);
	}

	async findProject(folder: URI): Promise<ISaengineProject | undefined> {
		let children;
		try {
			children = (await this.fileService.resolve(folder)).children ?? [];
		} catch {
			return undefined;
		}
		const manifest = children.find(c => c.isFile && c.name.toLowerCase().endsWith(PROJECT_MANIFEST_EXTENSION));
		if (!manifest) {
			return undefined;
		}
		let name = manifest.name.slice(0, -PROJECT_MANIFEST_EXTENSION.length);
		let type: ProjectType = 'building';
		try {
			const parsed: Partial<IProjectManifest> = JSON.parse((await this.fileService.readFile(manifest.resource)).value.toString());
			if (typeof parsed.name === 'string' && parsed.name) {
				name = parsed.name;
			}
			if (parsed.type === 'structure') {
				type = 'structure';
			}
		} catch (error) {
			this.logService.warn(`[saengine] unreadable project manifest ${manifest.resource.toString()}: ${error}`);
		}
		return { root: folder, manifest: manifest.resource, name, type };
	}

	async createProject(folder: URI, name: string, type: ProjectType = 'building'): Promise<ISaengineProject> {
		const existing = await this.findProject(folder);
		const project = existing ?? { root: folder, manifest: joinPath(folder, `${name}${PROJECT_MANIFEST_EXTENSION}`), name, type };
		if (!existing) {
			await this.fileService.createFolder(folder);
			await this.fileService.writeFile(project.manifest, VSBuffer.fromString(JSON.stringify(createManifest(name, type), undefined, '\t') + '\n'));
		}
		await this.createMissing(project);
		return project;
	}

	async setProjectType(type: ProjectType): Promise<void> {
		const project = this._project;
		if (!project || project.type === type) {
			return;
		}
		let manifest: { [key: string]: unknown };
		try {
			manifest = JSON.parse((await this.fileService.readFile(project.manifest)).value.toString());
		} catch {
			manifest = { ...createManifest(project.name, type) };
		}
		manifest.type = type;
		manifest.parts = projectParts(type).map(p => p.id);
		await this.fileService.writeFile(project.manifest, VSBuffer.fromString(JSON.stringify(manifest, undefined, '\t') + '\n'));
		const changed = { ...project, type };
		this.setProject(changed);
		await this.createMissing(changed);
	}

	private async detect(): Promise<void> {
		const folder = this.contextService.getWorkspace().folders[0]?.uri;
		const project = folder ? await this.findProject(folder) : undefined;
		if (project?.root.toString() === this._project?.root.toString() && project?.manifest.toString() === this._project?.manifest.toString() && project?.type === this._project?.type) {
			return;
		}
		// Opening a project fills in missing core items quietly; the open project losing one is said.
		const sameRoot = !!project && project.root.toString() === this._project?.root.toString();
		this.setProject(project);
		if (project) {
			await this.restoreStructure(sameRoot);
		}
	}

	private setProject(project: ISaengineProject | undefined): void {
		const previous = [...this.protectedResources];
		this.projectDisposables.clear();
		this._project = project;
		this.protectedResources = this.newResourceSet();

		if (project) {
			this.protectedResources.add(project.manifest);
			for (const part of projectParts(project.type)) {
				const folder = joinPath(project.root, part.folder);
				this.protectedResources.add(folder);
				if (part.mainFile) {
					const mainFile = joinPath(folder, part.mainFile);
					this.protectedResources.add(mainFile);
					if (part.schema) {
						// The JSON language service matches associations against the decoded URI.
						this.projectDisposables.add(schemaRegistry.registerSchemaAssociation(part.schema.id, mainFile.toString(true)));
					}
				}
			}

			// Core items removed outside the workbench (file manager, terminal, git) come back. The
			// project is the workspace folder, which the workbench already watches recursively.
			this.projectDisposables.add(this.fileService.onDidFilesChange(e => {
				if (e.gotDeleted() && [...this.protectedResources].some(r => e.contains(r, FileChangeType.DELETED))) {
					this.restoreScheduler.schedule();
				}
				// The project type may be changed in another window.
				if (e.contains(project.manifest, FileChangeType.UPDATED)) {
					void this.detect();
				}
			}));
		}

		this._onDidChangeDecorations.fire([...previous, ...this.protectedResources]);
		this._onDidChangeProject.fire(project);
	}

	private async restoreStructure(notify: boolean): Promise<void> {
		const project = this._project;
		if (!project) {
			return;
		}
		const restored = await this.createMissing(project);
		if (!restored.length) {
			return;
		}
		this.logService.info(`[saengine] restored core project items: ${restored.join(', ')}`);
		if (notify) {
			this.notificationService.info(localize('saengineProject.restored', "{0} was missing and has been recreated.", restored.join(', ')));
		}
	}

	/** Creates every missing core item and returns their project-relative names. */
	private async createMissing(project: ISaengineProject): Promise<string[]> {
		const created: string[] = [];
		try {
			if (!await this.fileService.exists(project.manifest)) {
				await this.fileService.writeFile(project.manifest, VSBuffer.fromString(JSON.stringify(createManifest(project.name, project.type), undefined, '\t') + '\n'));
				created.push(basename(project.manifest));
			}
			for (const part of projectParts(project.type)) {
				const folder = joinPath(project.root, part.folder);
				if (!await this.fileService.exists(folder)) {
					await this.fileService.createFolder(folder);
					created.push(part.folder);
				}
				if (part.mainFile) {
					const file = joinPath(folder, part.mainFile);
					if (!await this.fileService.exists(file)) {
						await this.fileService.writeFile(file, VSBuffer.fromString(part.initialContent?.(project.name) ?? ''));
						created.push(`${part.folder}/${part.mainFile}`);
					}
				}
			}
		} catch (error) {
			this.logService.error(`[saengine] could not create the project structure in ${project.root.toString()}: ${error}`);
			throw error;
		}
		return created;
	}

	private provideDecoration(uri: URI): IDecorationData | undefined {
		if (!this.isProtected(uri)) {
			return undefined;
		}
		return {
			letter: Codicon.lock,
			tooltip: localize('saengineProject.protected', "Core project item: it cannot be deleted, renamed or moved"),
		};
	}

	private newResourceSet(): ResourceSet {
		return new ResourceSet(uri => this.uriIdentityService.extUri.getComparisonKey(uri));
	}
}

registerSingleton(ISaengineProjectService, SaengineProjectService, InstantiationType.Delayed);
