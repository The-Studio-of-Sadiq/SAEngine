/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ISaengineProject, ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import {
	diffArgs, IVersionDiff, IVersionEntry, IVersionsStatus, markIssuedArgs, readDiff, readStatus, readVersion, readVersions, restoreArgs, saveArgs,
	VERSIONS_DIFF_COMMAND, VERSIONS_LIMIT, VERSIONS_LIST_COMMAND, VERSIONS_MARK_ISSUED_COMMAND, VERSIONS_RESTORE_COMMAND, VERSIONS_SAVE_COMMAND, VERSIONS_STATUS_COMMAND,
} from './versionsModel.js';
import { readProblems } from './projectArchiveModel.js';
import { editedParts, saveProjectEdits, unsavedEdits } from './projectEdits.js';
import { IWorkingCopyService } from '../../../services/workingCopy/common/workingCopyService.js';
import { URI } from '../../../../base/common/uri.js';

export const IProjectVersionsService = createDecorator<IProjectVersionsService>('saengineProjectVersionsService');

/** The open project's versions, as the sidebar and the Versions editor show them. */
export interface IProjectVersionsService {
	readonly _serviceBrand: undefined;

	/** Whether the backend keeps versions (its commands are registered). */
	readonly available: boolean;
	/** The open project's files against its latest version; undefined until known. */
	readonly status: IVersionsStatus | undefined;
	/**
	 * The parts of the open project with edits in an editor not saved to disk yet (the backend does
	 * not see them; Save Version and Restore save them first).
	 */
	readonly editedParts: readonly string[];
	/** The status, or the availability, or the unsaved edits changed; or a version was saved, restored or issued. */
	readonly onDidChange: Event<void>;

	refresh(): Promise<void>;
	/** Saves the open project's unsaved edits to disk; returns the files that could not be saved. */
	saveEdits(): Promise<URI[]>;
	list(limit?: number): Promise<IVersionEntry[]>;
	diff(from: string, to?: string): Promise<IVersionDiff>;
	save(message: string, options: { readonly author?: string; readonly issued?: boolean; readonly label?: string }): Promise<IVersionEntry | undefined>;
	restore(version: string, parts?: readonly string[], allParts?: readonly string[]): Promise<void>;
	markIssued(version: string, label: string): Promise<void>;
}

/** The commands whose registration makes the versions available. */
const COMMANDS = [VERSIONS_STATUS_COMMAND, VERSIONS_LIST_COMMAND, VERSIONS_SAVE_COMMAND, VERSIONS_DIFF_COMMAND, VERSIONS_RESTORE_COMMAND, VERSIONS_MARK_ISSUED_COMMAND];

/** A backend answer that carries only problems becomes an error the caller shows. */
function orThrow<T>(result: T, keys: readonly string[]): T {
	const problems = readProblems(result);
	const bag = typeof result === 'object' && result !== null ? result as { readonly [key: string]: unknown } : {};
	if (problems.length && !keys.some(key => bag[key] !== undefined)) {
		throw new Error(problems.join(' '));
	}
	return result;
}

export class ProjectVersionsService extends Disposable implements IProjectVersionsService {

	declare readonly _serviceBrand: undefined;

	private _status: IVersionsStatus | undefined;
	private statusVersion = 0;
	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	/** Files change in bursts (a save, Run All): the status is asked once they settle. */
	private readonly refreshScheduler = this._register(new RunOnceScheduler(() => void this.refresh(), 1500));

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService fileService: IFileService,
		@IWorkingCopyService private readonly workingCopyService: IWorkingCopyService,
	) {
		super();
		this._register(this.workingCopyService.onDidChangeDirty(copy => {
			const project = this.projectService.project;
			if (project && this.available && editedParts([copy], project.root).length) {
				this._onDidChange.fire();
			}
		}));
		this._register(this.projectService.onDidChangeProject(() => {
			this._status = undefined;
			this._onDidChange.fire();
			void this.refresh();
		}));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			if (COMMANDS.includes(id)) {
				this.refreshScheduler.schedule(50);
			}
		}));
		this._register(fileService.onDidFilesChange(e => {
			const project = this.projectService.project;
			if (project && this.available && (e.affects(project.manifest) || this.projectService.parts.some(part => e.affects(joinPath(project.root, part.folder))))) {
				this.refreshScheduler.schedule();
			}
		}));
		void this.refresh();
	}

	get available(): boolean {
		return !!CommandsRegistry.getCommand(VERSIONS_STATUS_COMMAND);
	}

	get status(): IVersionsStatus | undefined {
		return this._status;
	}

	get editedParts(): readonly string[] {
		const project = this.projectService.project;
		return project ? editedParts(unsavedEdits(this.workingCopyService, project.root), project.root, this.projectService.parts) : [];
	}

	async saveEdits(): Promise<URI[]> {
		const project = this.projectService.project;
		return project ? saveProjectEdits(this.workingCopyService, project.root) : [];
	}

	private root(): { project: ISaengineProject; projectRoot: string } {
		const project = this.projectService.project;
		if (!project) {
			throw new Error('No SAEngine project is open.');
		}
		return { project, projectRoot: project.root.fsPath };
	}

	async refresh(): Promise<void> {
		const project = this.projectService.project;
		const version = ++this.statusVersion;
		if (!project || !this.available) {
			if (this._status) {
				this._status = undefined;
			}
			this._onDidChange.fire();
			return;
		}
		let status: IVersionsStatus;
		try {
			status = readStatus(await this.commandService.executeCommand(VERSIONS_STATUS_COMMAND, { projectRoot: project.root.fsPath }));
		} catch (error) {
			status = { initialized: false, changedParts: [], problems: [toErrorMessage(error)], failed: true };
		}
		if (version !== this.statusVersion || project !== this.projectService.project) {
			return; // asked again meanwhile
		}
		this._status = status;
		this._onDidChange.fire();
	}

	async list(limit = VERSIONS_LIMIT): Promise<IVersionEntry[]> {
		const { projectRoot } = this.root();
		return readVersions(orThrow(await this.commandService.executeCommand(VERSIONS_LIST_COMMAND, { projectRoot, limit }), ['versions']));
	}

	async diff(from: string, to?: string): Promise<IVersionDiff> {
		const { projectRoot } = this.root();
		return readDiff(await this.commandService.executeCommand(VERSIONS_DIFF_COMMAND, diffArgs(projectRoot, from, to)));
	}

	async save(message: string, options: { readonly author?: string; readonly issued?: boolean; readonly label?: string }): Promise<IVersionEntry | undefined> {
		const { projectRoot } = this.root();
		try {
			const result = orThrow(await this.commandService.executeCommand(VERSIONS_SAVE_COMMAND, saveArgs(projectRoot, message, options)), ['id', 'version', 'sha', 'commit']);
			const bag = typeof result === 'object' && result !== null ? result as { readonly version?: unknown } : {};
			return readVersion(typeof bag.version === 'object' ? bag.version : result);
		} finally {
			this.refreshNow();
		}
	}

	async restore(version: string, parts?: readonly string[], allParts?: readonly string[]): Promise<void> {
		const { projectRoot } = this.root();
		try {
			orThrow(await this.commandService.executeCommand(VERSIONS_RESTORE_COMMAND, restoreArgs(projectRoot, version, parts, allParts)), ['restored', 'parts', 'files']);
		} finally {
			this.refreshNow();
		}
	}

	async markIssued(version: string, label: string): Promise<void> {
		const { projectRoot } = this.root();
		try {
			orThrow(await this.commandService.executeCommand(VERSIONS_MARK_ISSUED_COMMAND, markIssuedArgs(projectRoot, version, label)), ['id', 'version', 'issued', 'label']);
		} finally {
			this.refreshNow();
		}
	}

	private refreshNow(): void {
		this.refreshScheduler.cancel();
		void this.refresh();
	}
}

registerSingleton(IProjectVersionsService, ProjectVersionsService, InstantiationType.Delayed);
