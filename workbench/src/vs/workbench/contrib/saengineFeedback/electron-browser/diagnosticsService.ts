/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { errorHandler } from '../../../../base/common/errors.js';
import { Disposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { basename } from '../../../../base/common/path.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { generateUuid } from '../../../../base/common/uuid.js';
import { process } from '../../../../base/parts/sandbox/electron-browser/globals.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { INativeWorkbenchEnvironmentService } from '../../../services/environment/electron-browser/environmentService.js';
import { ILifecycleService } from '../../../services/lifecycle/common/lifecycle.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { activeCodeName } from '../../../services/saengineProject/common/activeCodePack.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { ISaenginePartStatusService } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IAnonymiseContext, diagnosticsBundle, IRecordedError, projectStatusSummary } from '../common/feedback.js';

export const ISaengineDiagnosticsService = createDecorator<ISaengineDiagnosticsService>('saengineDiagnosticsService');

/**
 * The anonymised diagnostics bundle (U2): what SAEngine knows about a problem, with nothing of
 * the project's content, for the engineer to review and send with a bug report. There is no
 * developers' endpoint: nothing leaves the computer except through the feedback form.
 */
export interface ISaengineDiagnosticsService {
	readonly _serviceBrand: undefined;
	/** The previous SAEngine session ended without closing (a crash or a forced stop). */
	readonly lastSessionEndedUnexpectedly: boolean;
	/** The bundle's text (JSON), anonymised. */
	bundle(): Promise<string>;
	/** Writes the bundle to the diagnostics folder (user data) and returns the file. */
	writeBundle(): Promise<URI>;
	/** The open project's status summary (each part's state; no names or values), or undefined. */
	projectStatus(): string | undefined;
	/** Takes a screenshot of the window into the diagnostics folder (undefined when it fails). */
	screenshot(): Promise<URI | undefined>;
	/** The folder bundles and screenshots are written to. */
	readonly folder: URI;
}

/** Window sessions not yet closed, for {@link ISaengineDiagnosticsService.lastSessionEndedUnexpectedly}. */
const OPEN_SESSIONS_KEY = 'saengine.diagnostics.openSessions';
/** Most unexpected errors kept. */
const MAX_ERRORS = 50;

export class SaengineDiagnosticsService extends Disposable implements ISaengineDiagnosticsService {

	declare readonly _serviceBrand: undefined;

	private readonly errors: IRecordedError[] = [];
	private readonly session = generateUuid();
	private _crashed = false;
	get lastSessionEndedUnexpectedly(): boolean { return this._crashed; }

	readonly folder: URI;

	constructor(
		@IStorageService private readonly storageService: IStorageService,
		@INativeHostService private readonly nativeHostService: INativeHostService,
		@IProductService private readonly productService: IProductService,
		@IFileService private readonly fileService: IFileService,
		@IPathService private readonly pathService: IPathService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly partStatusService: ISaenginePartStatusService,
		@ILifecycleService lifecycleService: ILifecycleService,
		@INativeWorkbenchEnvironmentService environmentService: INativeWorkbenchEnvironmentService,
	) {
		super();
		this.folder = joinPath(URI.file(environmentService.userDataPath), 'diagnostics');
		const unbind = errorHandler.addListener(error => this.record(error));
		this._register(toDisposable(unbind));
		void this.markOpen();
		this._register(lifecycleService.onWillShutdown(() => this.markClosed()));
	}

	private record(error: unknown): void {
		const err = error instanceof Error ? error : new Error(String(error));
		this.errors.push({ time: new Date().toISOString(), message: err.message.slice(0, 500), stack: err.stack?.split('\n').slice(0, 8).join('\n') });
		if (this.errors.length > MAX_ERRORS) {
			this.errors.shift();
		}
	}

	private sessions(): string[] {
		try {
			const value = JSON.parse(this.storageService.get(OPEN_SESSIONS_KEY, StorageScope.APPLICATION) ?? '[]');
			return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
		} catch {
			return [];
		}
	}

	/**
	 * Each window records its session until it closes; at start, more open sessions than the
	 * other windows now open mean one ended without closing.
	 */
	private async markOpen(): Promise<void> {
		const stored = this.sessions();
		const others = Math.max(0, (await this.nativeHostService.getWindowCount().catch(() => 1)) - 1);
		this._crashed = stored.length > others;
		const kept = others ? stored.slice(-others) : [];
		this.storageService.store(OPEN_SESSIONS_KEY, JSON.stringify([...kept, this.session]), StorageScope.APPLICATION, StorageTarget.MACHINE);
	}

	private markClosed(): void {
		const left = this.sessions().filter(s => s !== this.session);
		this.storageService.store(OPEN_SESSIONS_KEY, JSON.stringify(left), StorageScope.APPLICATION, StorageTarget.MACHINE);
	}

	private async context(): Promise<IAnonymiseContext> {
		const home = (await this.pathService.userHome()).fsPath;
		const project = this.projectService.project;
		return { home, userName: basename(home), projectRoot: project?.root.fsPath, projectName: project?.name };
	}

	async bundle(): Promise<string> {
		const os = await this.nativeHostService.getOSProperties();
		return diagnosticsBundle({
			created: new Date().toISOString(),
			app: { version: this.productService.version, commit: this.productService.commit?.slice(0, 10), date: this.productService.date },
			os: { platform: os.platform, release: os.release, arch: os.arch },
			runtime: { electron: process.versions.electron, chrome: process.versions.chrome, node: process.versions.node },
			codePack: this.projectService.project ? activeCodeName() : undefined,
			displayLanguage: this.configurationService.getValue<string>('locale'),
			developerMode: this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true,
			lastSessionEndedUnexpectedly: this._crashed,
			projectOpen: !!this.projectService.project,
			errors: this.errors,
		}, await this.context());
	}

	private stamp(): string {
		return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
	}

	async writeBundle(): Promise<URI> {
		const file = joinPath(this.folder, `saengine-diagnostics-${this.stamp()}.json`);
		await this.fileService.writeFile(file, VSBuffer.fromString(await this.bundle()));
		return file;
	}

	projectStatus(): string | undefined {
		return this.projectService.project ? projectStatusSummary(this.partStatusService.statuses) : undefined;
	}

	async screenshot(): Promise<URI | undefined> {
		const image = await this.nativeHostService.getScreenshot().catch(() => undefined);
		if (!image) {
			return undefined;
		}
		const file = joinPath(this.folder, `saengine-screenshot-${this.stamp()}.jpg`);
		await this.fileService.writeFile(file, image);
		return file;
	}
}
