/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { FileAccess } from '../../../../base/common/network.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { isRecentFolder, IWorkspacesService } from '../../../../platform/workspaces/common/workspaces.js';
import { IHostService } from '../../../services/host/browser/host.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { ISaengineProject, ISaengineProjectService, partById, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';

/** Characters Windows does not allow in a folder name (the strictest platform). */
const INVALID_NAME = /[\\/:*?"<>|]/;

/** When each project was last opened, by the URI of its folder (application storage). */
const OPENED_STORAGE_KEY = 'saengine.project.lastOpened';

/** The sample project shipped with the app: `<app root>/resources/saengine/samples/<name>`. */
const SAMPLE_NAME = 'Sample Frame';

/** The design code a new project follows (Project Settings > codes). */
export type DesignCode = 'bnbc' | 'aci';

export const DESIGN_CODES: readonly { readonly code: DesignCode; readonly label: string; readonly codes: { readonly concrete: string; readonly steel: string } }[] = [
	{ code: 'bnbc', label: localize('designCode.bnbc', "BNBC 2020"), codes: { concrete: 'BNBC 2020 Part 6 Chapter 6', steel: 'BNBC 2020 Part 6 Chapter 10' } },
	{ code: 'aci', label: localize('designCode.aci', "ACI 318-19"), codes: { concrete: 'ACI 318-19', steel: 'AISC 360-22' } },
];

export interface IRecentProject {
	readonly project: ISaengineProject;
	readonly label: string;
	/** When the project was last opened in SAEngine [ms since the epoch], if known. */
	readonly opened?: number;
	/** When a part's main file last changed, for projects last opened before SAEngine recorded it. */
	readonly changed?: number;
}

/**
 * Creating, picking and opening SAEngine projects, shared by the start window and the commands.
 */
export class ProjectOpener {

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IDialogService private readonly dialogService: IDialogService,
		@IHostService private readonly hostService: IHostService,
		@IWorkspacesService private readonly workspacesService: IWorkspacesService,
		@IPathService private readonly pathService: IPathService,
		@IStorageService private readonly storageService: IStorageService,
	) { }

	async defaultLocation(): Promise<URI> {
		return joinPath(await this.pathService.userHome(), 'Documents', 'SAEngine Projects');
	}

	/** Error message for an invalid project name, or undefined when it can be used. */
	validateName(name: string): string | undefined {
		const trimmed = name.trim();
		if (!trimmed) {
			return localize('projectName.empty', "Enter a project name.");
		}
		if (INVALID_NAME.test(trimmed) || trimmed.endsWith('.') || trimmed.endsWith(' ')) {
			return localize('projectName.invalid', "A project name cannot contain \\ / : * ? \" < > | or end with a dot or space.");
		}
		return undefined;
	}

	async browseForLocation(current: URI | undefined, title = localize('projectLocation.title', "Choose Where to Create the Project")): Promise<URI | undefined> {
		const picked = await this.fileDialogService.showOpenDialog({
			title,
			canSelectFolders: true,
			canSelectFiles: false,
			canSelectMany: false,
			defaultUri: await this.existingFolder(current),
		});
		return picked?.[0];
	}

	/** `folder` if it exists, else its parent if that exists, else the home folder. */
	private async existingFolder(folder: URI | undefined): Promise<URI> {
		for (const candidate of folder ? [folder, dirname(folder)] : []) {
			if (await this.fileService.exists(candidate)) {
				return candidate;
			}
		}
		return this.pathService.userHome();
	}

	/** Creates `<location>/<name>` as a new project following `code` and opens it in this window. */
	async createAndOpen(location: URI, name: string, type: ProjectType = 'building', code?: DesignCode): Promise<void> {
		const folder = joinPath(location, name.trim());
		let existing: ISaengineProject | undefined;
		if (await this.fileService.exists(folder)) {
			existing = await this.projectService.findProject(folder);
			const { confirmed } = await this.dialogService.confirm({
				message: existing
					? localize('projectExists.project', "A SAEngine project already exists at {0}.", folder.fsPath)
					: localize('projectExists.folder', "The folder {0} already exists.", folder.fsPath),
				detail: existing ? undefined : localize('projectExists.detail', "The project structure will be added to it. Existing files are kept."),
				primaryButton: existing ? localize('projectExists.open', "&&Open Project") : localize('projectExists.create', "&&Create Project Here"),
			});
			if (!confirmed) {
				return;
			}
		}
		const project = await this.projectService.createProject(folder, name.trim(), type);
		if (!existing && code) {
			await this.setDesignCode(project, code);
		}
		await this.open(folder);
	}

	/** Writes the codes of `code` into the project settings of a new project. */
	private async setDesignCode(project: ISaengineProject, code: DesignCode): Promise<void> {
		const codes = DESIGN_CODES.find(c => c.code === code)?.codes;
		const part = partById('settings');
		if (!codes || !part?.mainFile) {
			return;
		}
		const file = joinPath(project.root, part.folder, part.mainFile);
		const settings = JSON.parse((await this.fileService.readFile(file)).value.toString());
		settings.codes = { ...settings.codes, ...codes };
		await this.fileService.writeFile(file, VSBuffer.fromString(JSON.stringify(settings, undefined, '\t') + '\n'));
	}

	/** Asks for a folder and opens it, offering to add the project structure if it has none. */
	async pickAndOpen(): Promise<void> {
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('openProject.title', "Open SAEngine Project"),
			canSelectFolders: true,
			canSelectFiles: false,
			canSelectMany: false,
			defaultUri: await this.existingFolder(await this.defaultLocation()),
		});
		const folder = picked?.[0];
		if (!folder) {
			return;
		}
		if (!await this.projectService.findProject(folder)) {
			const { confirmed } = await this.dialogService.confirm({
				message: localize('openProject.notProject', "{0} is not a SAEngine project.", basename(folder)),
				detail: localize('openProject.notProjectDetail', "Create the SAEngine project structure in this folder? Existing files are kept."),
				primaryButton: localize('openProject.create', "&&Create Project Structure"),
			});
			if (!confirmed) {
				return;
			}
			await this.projectService.createProject(folder, basename(folder));
		}
		await this.open(folder);
	}

	/** The sample project shipped with the app; the same layout in a build and from sources. */
	sampleFolder(): URI {
		// The app root holds `out/` (FileAccess's root) and `resources/`.
		return joinPath(dirname(FileAccess.asFileUri('')), 'resources', 'saengine', 'samples', SAMPLE_NAME);
	}

	/**
	 * Copies the sample project into a folder the user picks (by default
	 * `Documents/SAEngine Projects`) and opens the copy. An existing copy is opened as it is.
	 */
	async openSample(): Promise<void> {
		// Nothing is created before the user picks a folder (the dialog falls back to the home folder).
		const parent = await this.browseForLocation(await this.defaultLocation(),localize('sample.location', "Choose Where to Put the Sample Project"));
		if (!parent) {
			return;
		}
		const target = joinPath(parent, SAMPLE_NAME);
		if (await this.fileService.exists(target)) {
			const existing = await this.projectService.findProject(target);
			const { confirmed } = await this.dialogService.confirm({
				message: existing
					? localize('sample.exists', "The sample project is already in {0}.", parent.fsPath)
					: localize('sample.folderExists', "The folder {0} already exists.", target.fsPath),
				detail: existing ? localize('sample.existsDetail', "Open that copy? Your changes to it are kept.") : localize('sample.folderExistsDetail', "Choose another location for the sample project."),
				primaryButton: existing ? localize('sample.openExisting', "&&Open Sample Project") : localize('sample.ok', "&&OK"),
			});
			if (confirmed && existing) {
				await this.open(target);
			}
			return;
		}
		await this.fileService.copy(this.sampleFolder(), target, false);
		// The parts the sample leaves empty (analysis model, exports) are created quietly.
		const project = await this.projectService.findProject(target);
		await this.projectService.createProject(target, project?.name ?? SAMPLE_NAME, project?.type);
		await this.open(target);
	}

	async open(folder: URI): Promise<void> {
		await this.hostService.openWindow([{ folderUri: folder }], { forceReuseWindow: true });
	}

	/** Remembers that the project at `folder` was opened now, for the recent projects list. */
	recordOpened(folder: URI): void {
		const opened = this.openedTimes();
		opened[folder.toString()] = Date.now();
		// Only the most recent entries are kept.
		const entries = Object.entries(opened).sort((a, b) => b[1] - a[1]).slice(0, 50);
		this.storageService.store(OPENED_STORAGE_KEY, JSON.stringify(Object.fromEntries(entries)), StorageScope.APPLICATION, StorageTarget.MACHINE);
	}

	private openedTimes(): { [folder: string]: number } {
		try {
			const value = JSON.parse(this.storageService.get(OPENED_STORAGE_KEY, StorageScope.APPLICATION, '{}'));
			return typeof value === 'object' && value !== null ? value : {};
		} catch {
			return {};
		}
	}

	/** The latest modification of the project's manifest and part main files. */
	private async lastChanged(project: ISaengineProject): Promise<number | undefined> {
		const files = [project.manifest, ...this.projectService.parts.filter(p => p.mainFile).map(p => joinPath(project.root, p.folder, p.mainFile!))];
		const times = await Promise.all(files.map(async file => {
			try {
				return (await this.fileService.stat(file)).mtime;
			} catch {
				return undefined;
			}
		}));
		const known = times.filter((time): time is number => typeof time === 'number');
		return known.length ? Math.max(...known) : undefined;
	}

	/** Recently opened folders that are still SAEngine projects, most recent first. */
	async recentProjects(limit = 8): Promise<IRecentProject[]> {
		const recent = (await this.workspacesService.getRecentlyOpened()).workspaces.filter(isRecentFolder);
		const opened = this.openedTimes();
		const projects: IRecentProject[] = [];
		for (const entry of recent) {
			if (projects.length >= limit) {
				break;
			}
			const project = await this.projectService.findProject(entry.folderUri);
			if (project) {
				const time = opened[entry.folderUri.toString()];
				projects.push({ project, label: project.name, opened: time, changed: time === undefined ? await this.lastChanged(project) : undefined });
			}
		}
		return projects;
	}
}
