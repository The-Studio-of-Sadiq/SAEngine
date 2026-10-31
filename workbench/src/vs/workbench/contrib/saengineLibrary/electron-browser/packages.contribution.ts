/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { disposableTimeout } from '../../../../base/common/async.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IEnvironmentService } from '../../../../platform/environment/common/environment.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ISaenginePackagesService } from '../../../../platform/saengine/common/packages.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { runningVersion } from '../../saengineUpdate/common/updateCheck.js';
import { readCodePacks } from '../browser/codePacksModel.js';
import {
	acceptedIndexKeys, CHECK_ONLINE_SETTING, DEFAULT_INDEX_URL, INDEX_URL_SETTING, IPackageDownload, IPackageIndexState, newestPackages, packageUpdates, PACKAGES_DISCARD_COMMAND,
	PACKAGES_DOWNLOAD_COMMAND, PACKAGES_INDEX_COMMAND, PACKAGES_SHOW_COMMAND, readPackageIndex,
} from '../common/packageIndex.js';

/*
 * The desktop side of the Packages page (docs/marketplace-plan.md §5, round M3): the commands
 * that read the signed package index and download a package through the main process
 * (platform/saengine/common/packages.ts), the last verified index kept for offline use, and a
 * check at most once a day, after start-up, that says when installed packages have updates.
 */

/** The last verified index (text, key, time, source), kept between sessions for offline use. */
const INDEX_CACHE_KEY = 'saengine.packages.index';
/** When the background check last ran (ms since the epoch). */
const LAST_CHECK_KEY = 'saengine.packages.lastCheck';
const DAY_MS = 24 * 60 * 60 * 1000;
/** After start-up has settled and after the update check (30 s). */
const BACKGROUND_DELAY_MS = 90_000;

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saenginePackages',
	order: 101,
	title: localize('saenginePackagesConfigurationTitle', "SAEngine Packages"),
	type: 'object',
	properties: {
		[CHECK_ONLINE_SETTING]: {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('saengine.packages.checkOnline', "Read the list of published packages (design codes, structure and building templates) when the Packages page opens and at most once a day in the background. Only the signed list is read; nothing is downloaded until you choose Install or Update. When off, the page shows the installed packages and the last list it saw, and **Install from File...** works offline."),
		},
		[INDEX_URL_SETTING]: {
			type: 'string',
			default: DEFAULT_INDEX_URL,
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('saengine.packages.indexUrl', "Where the package index (`index.json`, with `index.json.sig` beside it) is read. It must be on GitHub and signed with a key this SAEngine accepts; another index is refused."),
		},
	},
});

function cached(storage: IStorageService): IPackageIndexState | undefined {
	try {
		const value = JSON.parse(storage.get(INDEX_CACHE_KEY, StorageScope.APPLICATION) ?? 'null');
		return value && typeof value.text === 'string' ? value as IPackageIndexState : undefined;
	} catch {
		return undefined;
	}
}

/** Fetches and verifies the index; on failure the cached one with the error. */
async function fetchIndex(accessor: ServicesAccessor): Promise<IPackageIndexState> {
	const packages = accessor.get(ISaenginePackagesService);
	const storage = accessor.get(IStorageService);
	const configuration = accessor.get(IConfigurationService);
	const environment = accessor.get(IEnvironmentService);
	const log = accessor.get(ILogService);
	const keys = acceptedIndexKeys(environment.isBuilt);
	const last = cached(storage);
	if (!keys.length) {
		return { ...last, error: localize('packages.noKeys', "this SAEngine has no key to check the package list with yet (it comes with a later release).") };
	}
	const url = configuration.getValue<string>(INDEX_URL_SETTING) || DEFAULT_INDEX_URL;
	try {
		const index = await packages.fetchIndex({ indexUrl: url, keys });
		const state: IPackageIndexState = { text: index.text, keyId: index.keyId, test: index.test, at: index.at, source: index.source };
		storage.store(INDEX_CACHE_KEY, JSON.stringify(state), StorageScope.APPLICATION, StorageTarget.MACHINE);
		storage.store(LAST_CHECK_KEY, String(Date.now()), StorageScope.APPLICATION, StorageTarget.MACHINE);
		return state;
	} catch (error) {
		log.warn(`[saengine packages] the index at ${url} was not used: ${toErrorMessage(error)}`);
		return { ...last, error: toErrorMessage(error) };
	}
}

CommandsRegistry.registerCommand(PACKAGES_INDEX_COMMAND, async (accessor, raw?: { refresh?: boolean }): Promise<IPackageIndexState> => {
	const storage = accessor.get(IStorageService);
	const online = accessor.get(IConfigurationService).getValue<boolean>(CHECK_ONLINE_SETTING) !== false;
	const last = cached(storage);
	const lastCheck = Number(storage.get(LAST_CHECK_KEY, StorageScope.APPLICATION) ?? 0);
	// Opening the page reads the list when online checks are on; Refresh always does.
	if (raw?.refresh || (online && (!last || Date.now() - lastCheck > 60_000))) {
		return fetchIndex(accessor);
	}
	return last ? { ...last, offline: !online } : { offline: !online };
});

CommandsRegistry.registerCommand(PACKAGES_DOWNLOAD_COMMAND, (accessor, request: IPackageDownload) => {
	return accessor.get(ISaenginePackagesService).downloadPackage(request);
});

CommandsRegistry.registerCommand(PACKAGES_DISCARD_COMMAND, (accessor, raw: { path?: unknown }) => {
	return typeof raw?.path === 'string' ? accessor.get(ISaenginePackagesService).discard(raw.path) : undefined;
});

/**
 * Once a day at most, a while after start-up, in a packaged build with online checks on: reads
 * the index and, when installed packages have updates, says so once with a link to Updates.
 */
class PackagesBackgroundCheck extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saenginePackagesCheck';

	constructor(
		@IConfigurationService configurationService: IConfigurationService,
		@IEnvironmentService environmentService: IEnvironmentService,
		@IStorageService private readonly storageService: IStorageService,
		@ICommandService private readonly commandService: ICommandService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProductService private readonly productService: IProductService,
	) {
		super();
		if (!environmentService.isBuilt || configurationService.getValue<boolean>(CHECK_ONLINE_SETTING) === false) {
			return;
		}
		const last = Number(this.storageService.get(LAST_CHECK_KEY, StorageScope.APPLICATION) ?? 0);
		if (Date.now() - last < DAY_MS) {
			return;
		}
		disposableTimeout(() => void this.check(), BACKGROUND_DELAY_MS, this._store);
	}

	private async check(): Promise<void> {
		try {
			const state = await this.commandService.executeCommand<IPackageIndexState>(PACKAGES_INDEX_COMMAND, { refresh: true });
			if (!state?.text || state.error || !CommandsRegistry.getCommand('saengine.codes.list')) {
				return;
			}
			const version = runningVersion(this.productService as unknown as { version: string; saengineVersion?: string });
			const installed = readCodePacks(await this.commandService.executeCommand<unknown>('saengine.codes.list', { kind: 'all' }))
				.map(p => ({ id: p.id, kind: p.kind, version: p.version, scope: p.scope }));
			const updates = packageUpdates(installed, newestPackages(readPackageIndex(state.text), version), version);
			if (!updates.length) {
				return;
			}
			this.notificationService.prompt(Severity.Info,
				updates.length === 1
					? localize('packages.oneUpdate', "{0} {1} is published (you have {2}).", updates[0].available.name, updates[0].available.version, updates[0].installed.version || '?')
					: localize('packages.updates', "{0} installed packages have newer versions.", updates.length),
				[{ label: localize('packages.showUpdates', "Show Updates"), run: () => this.commandService.executeCommand(PACKAGES_SHOW_COMMAND, { tab: 'updates' }) }]);
		} catch {
			// Quiet: the Packages page shows what failed when it is opened.
		}
	}
}

registerWorkbenchContribution2(PackagesBackgroundCheck.ID, PackagesBackgroundCheck, WorkbenchPhase.Eventually);
