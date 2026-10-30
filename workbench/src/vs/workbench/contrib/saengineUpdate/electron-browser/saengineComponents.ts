/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEnvironmentService } from '../../../../platform/environment/common/environment.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IFemSolverService, SETUP_COMPONENTS, SetupComponent } from '../../../../platform/saengine/common/femSolver.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { FemAnalysisRunner } from '../../saengineFem/electron-browser/femAnalysisRunner.js';
import { CAD_PROGRAM_SETTING } from '../../saengineProject/electron-browser/projectBackend.contribution.js';
import { COMPONENTS_ADD_COMMAND, COMPONENTS_SHOW_COMMAND, COMPONENTS_STATES_COMMAND, componentLabel, componentPurpose, componentStateText, IComponentStates, readComponentStatus, releasesPage, setupComponents } from '../common/components.js';
import { compareVersions, parseSha256File, runningVersion, SETUP_ASSET } from '../common/updateCheck.js';

/*
 * The setup's optional components in the app (../common/components.ts): their states, found
 * where each program is found for use (no second search), and *Add Component...*: the user
 * chooses the SAEngine setup (SAEngine downloads no program by itself, D7), its SHA-256 is checked
 * against the release's `.sha256` beside it, and the shared process runs it with `/COMPONENTS=`.
 */

interface ISAEngineProduct {
	readonly saengineVersion?: string;
	readonly saengineUpdate?: { readonly releasesUrl?: string };
}

function isComponent(value: unknown): value is SetupComponent {
	return typeof value === 'string' && (SETUP_COMPONENTS as readonly string[]).includes(value);
}

async function componentStates(accessor: ServicesAccessor): Promise<IComponentStates> {
	const solver = accessor.get(IFemSolverService);
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	const configured = accessor.get(IConfigurationService).getValue<string>(CAD_PROGRAM_SETTING) || undefined;
	const logService = accessor.get(ILogService);
	const [backend, cad] = await Promise.all([
		solver.projectPlatform(python, 'components/list', {}).catch(error => {
			logService.warn(`[saengine components] the backend could not be asked: ${toErrorMessage(error)}`);
			return undefined;
		}),
		solver.cadProgram(configured).catch(() => undefined),
	]);
	const answer = (backend ?? {}) as { readonly energyplus?: unknown; readonly libredwg?: unknown };
	return {
		energyplus: readComponentStatus(answer.energyplus),
		librecad: cad ? { state: cad.source === 'bundled' ? 'installed' : 'elsewhere', path: cad.program } : { state: 'missing' },
		libredwg: readComponentStatus(answer.libredwg),
	};
}

async function addComponent(accessor: ServicesAccessor, component: SetupComponent): Promise<boolean> {
	const dialogService = accessor.get(IDialogService);
	const fileDialogService = accessor.get(IFileDialogService);
	const fileService = accessor.get(IFileService);
	const notificationService = accessor.get(INotificationService);
	const openerService = accessor.get(IOpenerService);
	const productService = accessor.get(IProductService);
	const solver = accessor.get(IFemSolverService);
	const pathService = accessor.get(IPathService);
	const logService = accessor.get(ILogService);
	const label = componentLabel(component);
	const product = productService as unknown as ISAEngineProduct;
	const current = runningVersion({ version: productService.version, saengineVersion: product.saengineVersion });

	if (!accessor.get(IEnvironmentService).isBuilt) {
		notificationService.info(localize('components.fromSources', "This SAEngine runs from its sources, not from the setup, so {0} cannot be added here. Install the program and point SAEngine to it (see docs/install).", label));
		return false;
	}
	const states = await componentStates(accessor);
	if (states[component].state === 'installed') {
		notificationService.info(localize('components.already', "{0} is already installed.", label));
		return false;
	}
	const page = releasesPage(product.saengineUpdate?.releasesUrl);
	const setupName = `SAEngine-x64-user-setup-${current}.exe`;
	const { result } = await dialogService.prompt<'choose' | 'page' | undefined>({
		type: Severity.Info,
		message: localize('components.addTitle', "Add {0}", label),
		detail: localize('components.addDetail', "{0}\n\nSAEngine adds a component by running its setup again with that component ticked; it does not download programs by itself. Choose the setup of SAEngine {1} ({2}, from the release page) with its .sha256 file beside it. The setup closes SAEngine, adds the component and keeps your projects and settings.", componentPurpose(component), current, setupName),
		buttons: [
			{ label: localize({ key: 'components.choose', comment: ['&& denotes a mnemonic'] }, "&&Choose Setup File..."), run: () => 'choose' as const },
			...(page ? [{ label: localize({ key: 'components.openReleases', comment: ['&& denotes a mnemonic'] }, "&&Open Release Page"), run: () => 'page' as const }] : []),
		],
		cancelButton: { label: localize('components.cancel', "Cancel"), run: () => undefined },
	});
	if (result === 'page' && page) {
		await openerService.open(URI.parse(page), { openExternal: true });
		return false;
	}
	if (result !== 'choose') {
		return false;
	}
	const picked = await fileDialogService.showOpenDialog({
		title: localize('components.chooseTitle', "Choose the SAEngine {0} Setup", current),
		defaultUri: joinPath(await pathService.userHome(), 'Downloads'),
		canSelectFiles: true,
		canSelectFolders: false,
		canSelectMany: false,
		filters: [{ name: localize('components.setupFilter', "Setup"), extensions: ['exe'] }],
		availableFileSystems: ['file'],
	});
	const setup = picked?.[0];
	if (!setup) {
		return false;
	}
	const name = basename(setup);
	const checksumFile = joinPath(dirname(setup), `${name}.sha256`);
	let expected: string | undefined;
	try {
		expected = parseSha256File((await fileService.readFile(checksumFile)).value.toString(), name);
	} catch {
		notificationService.error(localize('components.noChecksum', "{0} has no {1} beside it. Download that file from the same release and put it next to the setup: SAEngine runs a setup only after checking its SHA-256.", name, `${name}.sha256`));
		return false;
	}
	if (!expected) {
		notificationService.error(localize('components.badChecksum', "{0} holds no SHA-256 for {1}.", `${name}.sha256`, name));
		return false;
	}
	const version = SETUP_ASSET.exec(name)?.[1];
	if (!version) {
		notificationService.error(localize('components.notSetup', "{0} is not a SAEngine setup (SAEngine-x64-user-setup-<version>.exe).", name));
		return false;
	}
	if (version !== current) {
		const newer = (compareVersions(version, current) ?? 0) > 0;
		const { confirmed } = await dialogService.confirm({
			type: Severity.Warning,
			message: newer
				? localize('components.newerSetup', "This setup is SAEngine {0}; you have {1}. It also updates SAEngine to {0}.", version, current)
				: localize('components.olderSetup', "This setup is SAEngine {0}; you have {1}. It replaces SAEngine by the older {0}.", version, current),
			primaryButton: localize({ key: 'components.runAnyway', comment: ['&& denotes a mnemonic'] }, "&&Run It Anyway"),
		});
		if (!confirmed) {
			return false;
		}
	}
	const components = setupComponents(states, component);
	const answer = await solver.runSetup({ setup: setup.fsPath, sha256: expected, components });
	if (!answer.ok) {
		logService.warn(`[saengine components] ${setup.fsPath}: ${(answer.problems ?? []).join(' ')}`);
		notificationService.error(localize('components.runFailed', "{0} could not be added: {1}", label, (answer.problems ?? []).join(' ')));
		return false;
	}
	notificationService.info(localize('components.running', "The SAEngine setup is running with {0} ticked. It asks to close SAEngine; start SAEngine again when it has finished.", label));
	return true;
}

CommandsRegistry.registerCommand(COMPONENTS_STATES_COMMAND, accessor => componentStates(accessor));

CommandsRegistry.registerCommand(COMPONENTS_ADD_COMMAND, async (accessor, component: unknown) => {
	if (isComponent(component)) {
		return addComponent(accessor, component);
	}
	return accessor.get(IInstantiationService).invokeFunction(showComponents);
});

interface IComponentPick extends IQuickPickItem {
	readonly component: SetupComponent;
}

async function showComponents(accessor: ServicesAccessor): Promise<boolean> {
	const quickInputService = accessor.get(IQuickInputService);
	const instantiationService = accessor.get(IInstantiationService);
	const states = await componentStates(accessor);
	const items: IComponentPick[] = SETUP_COMPONENTS.map(component => ({
		component,
		label: componentLabel(component),
		description: componentStateText(states[component]),
		detail: componentPurpose(component),
	}));
	const picked = await quickInputService.pick(items, {
		title: localize('components.title', "Installer Components"),
		placeHolder: localize('components.placeholder', "Choose a component to add it; the core is always installed"),
		matchOnDescription: true,
	});
	if (!picked) {
		return false;
	}
	return instantiationService.invokeFunction(addComponent, picked.component);
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: COMPONENTS_SHOW_COMMAND,
			title: localize2('saengineInstallerComponents', "Installer Components..."),
			category: localize2('help', "Help"),
			f1: true,
			menu: [{ id: MenuId.MenubarHelpMenu, group: '1_welcome', order: 7 }],
		});
	}

	override run(accessor: ServicesAccessor): Promise<boolean> {
		return accessor.get(IInstantiationService).invokeFunction(showComponents);
	}
});
