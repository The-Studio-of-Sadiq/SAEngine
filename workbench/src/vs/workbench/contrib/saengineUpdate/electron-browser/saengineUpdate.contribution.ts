/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isWindows } from '../../../../base/common/platform.js';
import { joinPath } from '../../../../base/common/resources.js';
import { disposableTimeout } from '../../../../base/common/async.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IChecksumService } from '../../../../platform/checksum/common/checksumService.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IDownloadService } from '../../../../platform/download/common/download.js';
import { IEnvironmentService } from '../../../../platform/environment/common/environment.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { createDecorator, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { asJson, asText, IRequestService } from '../../../../platform/request/common/request.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { checksumMatches, IAvailableUpdate, IGitHubRelease, parseSha256File, pickUpdate, runningVersion } from '../common/updateCheck.js';
import './saengineComponents.js';

/*
 * SAEngine's update check. Code - OSS's own update service needs an update server answering
 * per commit (product.json updateUrl) and installs in the background; SAEngine's releases are
 * GitHub pre-releases instead, so product.json has no updateUrl (that service stays disabled
 * and its "Check for Updates..." entries hidden) and this contribution:
 *   - reads the releases from product.json's saengineUpdate.releasesUrl (GitHub's releases API),
 *   - offers the newest release with a setup newer than the running build (updateCheck.ts),
 *   - shows its release notes, and only on the user's click downloads the setup to a place the
 *     user picks and checks it against the release's .sha256 file. Nothing installs by itself:
 *     the user runs the setup (the same setup as a manual download).
 * The running version is product.json's saengineVersion, which build-installer.ps1 stamps into
 * the packaged app (x.y.z-alpha.N for a release); a build from sources reports package.json's.
 * Not code-signed yet: SmartScreen warns when the setup is run (docs/release.md).
 */

const CHECK_ON_STARTUP = 'saengine.update.checkOnStartup';
const SKIPPED_VERSION_KEY = 'saengine.update.skippedVersion';
const CALL_SITE = 'saengine.update';
/** Long enough for start-up work to settle; the check is one small request. */
const STARTUP_DELAY_MS = 30_000;
const NOTES_LIMIT = 6000;

interface ISAEngineProduct {
	readonly saengineVersion?: string;
	readonly saengineUpdate?: { readonly releasesUrl?: string };
}

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineUpdate',
	order: 100,
	title: localize('saengineUpdateConfigurationTitle', "SAEngine Updates"),
	type: 'object',
	properties: {
		[CHECK_ON_STARTUP]: {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('saengine.update.checkOnStartup', "Look for a newer SAEngine release on GitHub when SAEngine starts. Only the list of releases is read; a new version is shown with its release notes and is downloaded only when you choose to. **Help: Check for SAEngine Updates...** checks at any time."),
		},
	},
});

/**
 * Why a check failed: `message` for the engineer (plain words, no HTTP codes), `detail` for the
 * log (G18).
 */
class UpdateCheckError extends Error {
	constructor(message: string, readonly detail: string) {
		super(message);
	}
}

export const ISAEngineUpdateService = createDecorator<ISAEngineUpdateService>('saengineUpdateService');

export interface ISAEngineUpdateService {
	readonly _serviceBrand: undefined;
	/** `manual`: report every outcome (also "up to date" and errors) and ignore a skipped version. */
	check(manual: boolean): Promise<void>;
}

class SAEngineUpdateService implements ISAEngineUpdateService {

	declare readonly _serviceBrand: undefined;

	private checking = false;
	private downloading = false;

	constructor(
		@IProductService private readonly productService: IProductService,
		@IRequestService private readonly requestService: IRequestService,
		@IDownloadService private readonly downloadService: IDownloadService,
		@IChecksumService private readonly checksumService: IChecksumService,
		@IFileService private readonly fileService: IFileService,
		@IDialogService private readonly dialogService: IDialogService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProgressService private readonly progressService: IProgressService,
		@IStorageService private readonly storageService: IStorageService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IOpenerService private readonly openerService: IOpenerService,
		@INativeHostService private readonly nativeHostService: INativeHostService,
		@IPathService private readonly pathService: IPathService,
		@ILogService private readonly logService: ILogService,
	) { }

	private get product(): ISAEngineProduct {
		return this.productService as unknown as ISAEngineProduct;
	}

	private currentVersion(): string {
		return runningVersion({ version: this.productService.version, saengineVersion: this.product.saengineVersion });
	}

	async check(manual: boolean): Promise<void> {
		if (this.checking || this.downloading) {
			if (manual) {
				this.notificationService.info(localize('update.busy', "SAEngine is already checking for or downloading an update."));
			}
			return;
		}
		const releasesUrl = this.product.saengineUpdate?.releasesUrl;
		if (!releasesUrl) {
			if (manual) {
				this.notificationService.info(localize('update.notConfigured', "This build of SAEngine has no release feed (saengineUpdate.releasesUrl in product.json)."));
			}
			return;
		}
		this.checking = true;
		let update: IAvailableUpdate | undefined;
		const current = this.currentVersion();
		try {
			const releases = await this.fetchReleases(releasesUrl);
			update = pickUpdate(releases, current);
			this.logService.info(`[saengine update] running ${current}; newest offered: ${update?.version ?? 'none'}`);
		} catch (error) {
			this.logService.warn(`[saengine update] ${error instanceof UpdateCheckError ? error.detail : toErrorMessage(error)}`);
			if (manual) {
				// Not the engineer's fault and nothing to fix in the app: information, not an error.
				this.notificationService.info(error instanceof UpdateCheckError
					? error.message
					: localize('update.offline', "SAEngine could not reach its release list just now (no internet connection?). Try again later."));
			}
			return;
		} finally {
			this.checking = false;
		}

		if (!update) {
			if (manual) {
				this.notificationService.info(localize('update.upToDate', "SAEngine {0} is the newest release.", current));
			}
			return;
		}
		if (manual) {
			return this.showUpdate(update, current);
		}
		if (this.storageService.get(SKIPPED_VERSION_KEY, StorageScope.APPLICATION) === update.version) {
			return;
		}
		const found = update;
		this.notificationService.prompt(Severity.Info,
			localize('update.available', "SAEngine {0} is available (you have {1}).", found.version, current),
			[{
				label: localize('update.showNotes', "Release Notes and Download..."),
				run: () => this.showUpdate(found, current),
			}, {
				label: localize('update.skip', "Skip This Version"),
				run: () => this.storageService.store(SKIPPED_VERSION_KEY, found.version, StorageScope.APPLICATION, StorageTarget.MACHINE),
			}, {
				label: localize('update.noStartupCheck', "Don't Check on Start-up"),
				isSecondary: true,
				run: () => this.configurationService.updateValue(CHECK_ON_STARTUP, false),
			}],
			{ sticky: true });
	}

	private async fetchReleases(url: string): Promise<IGitHubRelease[]> {
		const cts = new CancellationTokenSource();
		try {
			const context = await this.requestService.request({
				type: 'GET',
				url,
				headers: { 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
				timeout: 20_000,
				callSite: CALL_SITE,
			}, cts.token);
			const status = context.res.statusCode ?? 0;
			if (status === 404) {
				throw new UpdateCheckError(localize('update.notFound', "SAEngine's releases are not published online yet. You get new versions from whoever gave you SAEngine."), `release list not found at ${url} (HTTP 404); the repository may not be public yet`);
			}
			if (status === 403 || status === 429) {
				throw new UpdateCheckError(localize('update.rateLimited', "Too many update checks from this network just now. Try again in an hour."), `GitHub refused the request (HTTP ${status}), probably its rate limit`);
			}
			if (status !== 200) {
				throw new UpdateCheckError(localize('update.unavailable', "The release list is not available just now. Try again later."), `GitHub answered HTTP ${status} for ${url}`);
			}
			const releases = await asJson<IGitHubRelease[]>(context);
			if (!Array.isArray(releases)) {
				throw new UpdateCheckError(localize('update.unavailable', "The release list is not available just now. Try again later."), `the answer from ${url} is not a list of releases`);
			}
			return releases;
		} finally {
			cts.dispose();
		}
	}

	private async showUpdate(update: IAvailableUpdate, current: string): Promise<void> {
		let notes = update.notes.trim() || localize('update.noNotes', "No release notes.");
		if (notes.length > NOTES_LIMIT) {
			notes = notes.slice(0, NOTES_LIMIT) + '\n\n' + localize('update.notesCut', "(Shortened: the full notes are on GitHub.)");
		}
		const sizeText = update.setupSize ? localize('update.size', " ({0} MB)", Math.round(update.setupSize / (1024 * 1024))) : '';
		const { result } = await this.dialogService.prompt<'download' | 'open' | undefined>({
			type: Severity.Info,
			message: localize('update.dialogTitle', "SAEngine {0} is available", update.version),
			detail: localize('update.dialogDetail', "{0}. You have {1}. The setup{2} is downloaded only when you choose Download, and checked against the release's SHA-256 before you run it.", update.title, current, sizeText),
			buttons: [
				...(isWindows ? [{ label: localize({ key: 'update.download', comment: ['&& denotes a mnemonic'] }, "&&Download..."), run: () => 'download' as const }] : []),
				{ label: localize({ key: 'update.openRelease', comment: ['&& denotes a mnemonic'] }, "&&Open on GitHub"), run: () => 'open' as const },
			],
			cancelButton: { label: localize('update.later', "Later"), run: () => undefined },
			custom: {
				markdownDetails: [{ markdown: new MarkdownString(notes, { isTrusted: false }) }],
			},
		});
		if (result === 'open') {
			await this.openerService.open(URI.parse(update.releaseUrl), { openExternal: true });
		} else if (result === 'download') {
			await this.download(update);
		}
	}

	private async download(update: IAvailableUpdate): Promise<void> {
		const downloads = joinPath(await this.pathService.userHome(), 'Downloads');
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('update.saveTitle', "Save the SAEngine {0} Setup", update.version),
			defaultUri: joinPath(downloads, update.setupName),
			filters: [{ name: localize('update.setupFilter', "Setup"), extensions: ['exe'] }],
			availableFileSystems: ['file'],
		});
		if (!target || this.downloading) {
			return;
		}
		this.downloading = true;
		const cts = new CancellationTokenSource();
		let verified: string | undefined;
		try {
			verified = await this.progressService.withProgress({
				location: ProgressLocation.Notification,
				title: localize('update.downloading', "Downloading SAEngine {0}", update.version),
				cancellable: true,
			}, async progress => {
				progress.report({ message: localize('update.readingChecksum', "reading the SHA-256...") });
				const expected = await this.fetchChecksum(update, cts);
				progress.report({ message: update.setupName });
				await this.downloadService.download(URI.parse(update.setupUrl), target, CALL_SITE, cts.token);
				if (cts.token.isCancellationRequested) {
					throw new Error(localize('update.cancelled', "cancelled"));
				}
				progress.report({ message: localize('update.verifying', "checking the SHA-256...") });
				const actual = await this.checksumService.checksum(target);
				if (!checksumMatches(expected, actual)) {
					throw new Error(localize('update.mismatch', "the downloaded setup does not match the release's SHA-256 (expected {0}); it was deleted", expected));
				}
				return expected;
			}, () => cts.cancel());
		} catch (error) {
			await this.fileService.del(target).catch(() => undefined);
			if (!cts.token.isCancellationRequested) {
				this.logService.error(`[saengine update] download of ${update.setupUrl} failed: ${toErrorMessage(error)}`);
				this.notificationService.error(localize('update.downloadFailed', "The SAEngine {0} setup could not be downloaded: {1}", update.version, toErrorMessage(error)));
			}
			return;
		} finally {
			this.downloading = false;
			cts.dispose();
		}

		this.logService.info(`[saengine update] ${target.fsPath} verified, sha256 ${verified}`);
		this.notificationService.prompt(Severity.Info,
			localize('update.ready', "The SAEngine {0} setup is downloaded and its SHA-256 checked. Run it to update: it asks to close SAEngine, and your projects are not touched.", update.version),
			[{
				label: localize('update.runSetup', "Run Setup"),
				run: () => this.nativeHostService.openExternal(target.toString(true)),
			}, {
				label: localize('update.showInFolder', "Show in Folder"),
				run: () => this.nativeHostService.showItemInFolder(target.fsPath),
			}],
			{ sticky: true });
	}

	private async fetchChecksum(update: IAvailableUpdate, cts: CancellationTokenSource): Promise<string> {
		const context = await this.requestService.request({ type: 'GET', url: update.sha256Url, timeout: 20_000, callSite: CALL_SITE }, cts.token);
		if (context.res.statusCode !== 200) {
			throw new Error(localize('update.checksumStatus', "the release's .sha256 file could not be read (HTTP {0})", context.res.statusCode ?? 0));
		}
		const expected = parseSha256File(await asText(context) ?? '', update.setupName);
		if (!expected) {
			throw new Error(localize('update.checksumInvalid', "the release's .sha256 file holds no SHA-256 for {0}", update.setupName));
		}
		return expected;
	}
}

registerSingleton(ISAEngineUpdateService, SAEngineUpdateService, InstantiationType.Delayed);

/** The start-up check: only in a packaged build, after start-up, when the setting allows it. */
class SAEngineUpdateStartupCheck extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengineUpdateStartupCheck';

	constructor(
		@ISAEngineUpdateService updateService: ISAEngineUpdateService,
		@IConfigurationService configurationService: IConfigurationService,
		@IEnvironmentService environmentService: IEnvironmentService,
	) {
		super();
		if (!environmentService.isBuilt || !configurationService.getValue<boolean>(CHECK_ON_STARTUP)) {
			return;
		}
		disposableTimeout(() => updateService.check(false), STARTUP_DELAY_MS, this._store);
	}
}

registerWorkbenchContribution2(SAEngineUpdateStartupCheck.ID, SAEngineUpdateStartupCheck, WorkbenchPhase.Eventually);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.update.check',
			title: localize2('saengineCheckForUpdates', "Check for SAEngine Updates..."),
			category: localize2('help', "Help"),
			f1: true,
			menu: [{ id: MenuId.MenubarHelpMenu, group: '1_welcome', order: 6 }],
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(ISAEngineUpdateService).check(true);
	}
});
