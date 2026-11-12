/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IntervalTimer } from '../../../../base/common/async.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { ILifecycleService } from '../../../services/lifecycle/common/lifecycle.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IProjectVersionsService } from './versionsService.js';
import {
	IShareStatus, ISyncResult, PRESENCE_INTERVAL_MS, readPresence, readShareStatus, readSyncResult, Resolution,
	SHARE_CONNECT_COMMAND, SHARE_DISCONNECT_COMMAND, SHARE_HEARTBEAT_COMMAND, SHARE_LOCK_COMMAND, SHARE_STATUS_COMMAND, SHARE_SYNC_COMMAND, SHARE_UNLOCK_COMMAND,
} from './shareModel.js';

export const IProjectShareService = createDecorator<IProjectShareService>('saengineProjectShareService');

/**
 * The open project's office copy: where it is shared, what waits each way, the part locks and
 * who else has the project open (refreshed with each presence heartbeat).
 */
export interface IProjectShareService {
	readonly _serviceBrand: undefined;

	/** Whether the backend can share projects (its commands are registered). */
	readonly available: boolean;
	/** The open project's shared state; undefined until known or without a project. */
	readonly status: IShareStatus | undefined;
	readonly onDidChange: Event<void>;

	/** Reads the state again; with `fetch`, asks the office copy too (slower on a network). */
	refresh(fetch?: boolean): Promise<void>;
	connect(location: string): Promise<ISyncResult>;
	disconnect(): Promise<void>;
	sync(resolutions?: { readonly [part: string]: Resolution }): Promise<ISyncResult>;
	lock(part: string, note?: string): Promise<void>;
	unlock(part: string, force?: boolean): Promise<void>;
}

export class ProjectShareService extends Disposable implements IProjectShareService {

	declare readonly _serviceBrand: undefined;

	private _status: IShareStatus | undefined;
	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;
	private readonly heartbeat = this._register(new IntervalTimer());
	private generation = 0;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@IProjectVersionsService private readonly versionsService: IProjectVersionsService,
		@ILifecycleService lifecycleService: ILifecycleService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		this._register(this.projectService.onDidChangeProject(() => {
			this.leave();
			this._status = undefined;
			this._onDidChange.fire();
			void this.refresh(false);
		}));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === SHARE_STATUS_COMMAND) {
				void this.refresh(false);
			}
		}));
		this._register(lifecycleService.onWillShutdown(() => this.leave()));
		void this.refresh(false);
	}

	get available(): boolean {
		return !!CommandsRegistry.getCommand(SHARE_STATUS_COMMAND);
	}

	get status(): IShareStatus | undefined {
		return this._status;
	}

	private projectRoot(): string {
		const project = this.projectService.project;
		if (!project) {
			throw new Error('No SAEngine project is open.');
		}
		return project.root.fsPath;
	}

	async refresh(fetch = false): Promise<void> {
		const project = this.projectService.project;
		if (!project || !this.available) {
			return;
		}
		const generation = ++this.generation;
		try {
			const status = readShareStatus(await this.commandService.executeCommand(SHARE_STATUS_COMMAND, { projectRoot: project.root.fsPath, fetch }));
			if (generation !== this.generation || this.projectService.project !== project) {
				return;
			}
			this._status = status;
			this.updateHeartbeat();
			this._onDidChange.fire();
		} catch (error) {
			this.logService.warn(`[saengine share] status: ${error}`);
		}
	}

	/** Presence is kept while a project shared through a folder is open. */
	private updateHeartbeat(): void {
		if (this._status?.shared && this._status.kind === 'folder') {
			this.heartbeat.cancelAndSet(() => void this.beat(), PRESENCE_INTERVAL_MS);
			void this.beat();
		} else {
			this.heartbeat.cancel();
		}
	}

	private async beat(): Promise<void> {
		const project = this.projectService.project;
		if (!project || !this._status?.shared) {
			return;
		}
		try {
			const answer = await this.commandService.executeCommand(SHARE_HEARTBEAT_COMMAND, { projectRoot: project.root.fsPath });
			const people = Array.isArray((answer as { people?: unknown })?.people) ? (answer as { people: unknown[] }).people : [];
			if (this._status && this.projectService.project === project) {
				this._status = { ...this._status, people: people.map(readPresence).filter(p => !!p) };
				this._onDidChange.fire();
			}
		} catch {
			// Presence is a courtesy; a share that cannot be written must not interrupt work.
		}
	}

	private leave(): void {
		this.heartbeat.cancel();
		const project = this.projectService.project;
		if (project && this._status?.shared && this._status.kind === 'folder') {
			void this.commandService.executeCommand(SHARE_HEARTBEAT_COMMAND, { projectRoot: project.root.fsPath, leaving: true }).catch(() => undefined);
		}
	}

	private async saveEditsFirst(): Promise<void> {
		const failed = await this.versionsService.saveEdits();
		if (failed.length) {
			throw new Error(failed.map(f => f.fsPath).join(', '));
		}
	}

	async connect(location: string): Promise<ISyncResult> {
		await this.saveEditsFirst();
		const result = readSyncResult(await this.commandService.executeCommand(SHARE_CONNECT_COMMAND, { projectRoot: this.projectRoot(), location }));
		await this.afterChange();
		return result;
	}

	async disconnect(): Promise<void> {
		this.leave();
		await this.commandService.executeCommand(SHARE_DISCONNECT_COMMAND, { projectRoot: this.projectRoot() });
		await this.afterChange();
	}

	async sync(resolutions?: { readonly [part: string]: Resolution }): Promise<ISyncResult> {
		await this.saveEditsFirst();
		const result = readSyncResult(await this.commandService.executeCommand(SHARE_SYNC_COMMAND, { projectRoot: this.projectRoot(), resolutions }));
		await this.afterChange();
		return result;
	}

	async lock(part: string, note?: string): Promise<void> {
		await this.commandService.executeCommand(SHARE_LOCK_COMMAND, { projectRoot: this.projectRoot(), part, note });
		await this.refresh(false);
	}

	async unlock(part: string, force?: boolean): Promise<void> {
		await this.commandService.executeCommand(SHARE_UNLOCK_COMMAND, { projectRoot: this.projectRoot(), part, force });
		await this.refresh(false);
	}

	private async afterChange(): Promise<void> {
		await Promise.all([this.refresh(false), this.versionsService.refresh()]);
	}
}

registerSingleton(IProjectShareService, ProjectShareService, InstantiationType.Delayed);
