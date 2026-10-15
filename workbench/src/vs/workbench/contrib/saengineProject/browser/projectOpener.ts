/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { basename, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { isRecentFolder, IWorkspacesService } from '../../../../platform/workspaces/common/workspaces.js';
import { IHostService } from '../../../services/host/browser/host.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { ISaengineProject, ISaengineProjectService, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';

/** Characters Windows does not allow in a folder name (the strictest platform). */
const INVALID_NAME = /[\\/:*?"<>|]/;

export interface IRecentProject {
	readonly project: ISaengineProject;
	readonly label: string;
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

	async browseForLocation(current: URI | undefined): Promise<URI | undefined> {
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('projectLocation.title', "Choose Where to Create the Project"),
			canSelectFolders: true,
			canSelectFiles: false,
			canSelectMany: false,
			defaultUri: current,
		});
		return picked?.[0];
	}

	/** Creates `<location>/<name>` as a new project and opens it in this window. */
	async createAndOpen(location: URI, name: string, type: ProjectType = 'building'): Promise<void> {
		const folder = joinPath(location, name.trim());
		if (await this.fileService.exists(folder)) {
			const existing = await this.projectService.findProject(folder);
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
		await this.projectService.createProject(folder, name.trim(), type);
		await this.open(folder);
	}

	/** Asks for a folder and opens it, offering to add the project structure if it has none. */
	async pickAndOpen(): Promise<void> {
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('openProject.title', "Open SAEngine Project"),
			canSelectFolders: true,
			canSelectFiles: false,
			canSelectMany: false,
			defaultUri: await this.defaultLocation(),
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

	async open(folder: URI): Promise<void> {
		await this.hostService.openWindow([{ folderUri: folder }], { forceReuseWindow: true });
	}

	/** Recently opened folders that are still SAEngine projects, most recent first. */
	async recentProjects(limit = 8): Promise<IRecentProject[]> {
		const recent = (await this.workspacesService.getRecentlyOpened()).workspaces.filter(isRecentFolder);
		const projects: IRecentProject[] = [];
		for (const entry of recent) {
			if (projects.length >= limit) {
				break;
			}
			const project = await this.projectService.findProject(entry.folderUri);
			if (project) {
				projects.push({ project, label: entry.label ?? project.name });
			}
		}
		return projects;
	}
}
