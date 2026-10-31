/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/codePacks.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { runningVersion } from '../../saengineUpdate/common/updateCheck.js';
import { COMPONENTS_SHOW_COMMAND } from '../../saengineUpdate/common/components.js';
import {
	CODES_REMOVE_COMMAND, IIndexPackage, IInstalledPackage, IPackageDownload, IPackageIndex, IPackageIndexState, IPackageUpdate, kindLabel, kindPluralLabel, missingRequirements, needsNewerSaengine,
	newestPackages, PACKAGE_KINDS, packageFileName, packageUpdates, PackageKind, PACKAGES_COPY_COMMAND, PACKAGES_DISCARD_COMMAND, PACKAGES_DOWNLOAD_COMMAND, PACKAGES_INDEX_COMMAND, PACKAGES_OPEN_BUNDLE_COMMAND, readPackageIndex, sizeLabel,
} from '../common/packageIndex.js';
import { CodePacksEditorInput } from './codePacksEditorInput.js';
import {
	builtinDefaultPack, CodePackScope, CODES_INSTALL_COMMAND, CODES_LIST_COMMAND, CODES_NEW_COMMAND, CODES_SHOW_COMMAND, CODES_TRUST_COMMAND, CODES_VALIDATE_COMMAND,
	coverageLabel, DEFAULT_CODE_PACK, extendsLabel, groupPacks, ICodePackInfo, packIdProblem, PROJECT_PACKS_FOLDER, readCodePack, readCodePacks, readProblems, scopeLabel, shadowedLabel, trustLabel,
} from './codePacksModel.js';

/** Arguments of "New Code Pack...", for a caller that already knows them (all optional). */
export interface INewCodePackArgs {
	readonly id?: string;
	readonly name?: string;
	readonly extends?: string;
	readonly scope?: 'user' | 'project';
}

/** Arguments of "Install from File...": the folder or .zip, and where it goes. */
export interface IInstallCodePackArgs {
	readonly path?: string;
	readonly scope?: 'user' | 'project';
}

/** The tabs of the Packages page. */
export type PackagesTab = 'installed' | 'browse' | 'updates';

/** Arguments of "Packages...": the tab and the kind shown (both optional). */
export interface IShowPackagesArgs {
	readonly tab?: PackagesTab;
	readonly kind?: PackageKind | 'all';
}

const KIND_ICONS: { readonly [K in PackageKind]: ThemeIcon } = {
	designCode: Codicon.law,
	structureTemplate: Codicon.symbolStructure,
	buildingTemplate: Codicon.home,
};

/**
 * The Packages page (≡ → Packages..., formerly Code Packs; docs/marketplace-plan.md §5):
 *  - Installed: every package on this computer (design codes, structure templates, building
 *    templates), grouped Built-in / Your Packs / This Project, with its details, Validate, Trust
 *    (hooks) and Remove;
 *  - Browse: the packages of the signed index (fetched and verified in the main process), each
 *    with Install: the zip is downloaded pinned by its size and SHA-256, then installed by the
 *    backend like a file (a design code asks where: you or this project; templates go to you);
 *  - Updates: installed packages with a newer version in the index;
 *  - Install from File... (a folder or zip, offline), New Code Pack..., and the installer's
 *    optional components (Help › Installer Components..., the same list).
 * Until the backend answers it shows the built-in BNBC 2020 only, quietly.
 */
export class CodePacksEditor extends EditorPane {

	static readonly ID = CodePacksEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private list!: HTMLElement;
	private tabsElement!: HTMLElement;
	private packs: ICodePackInfo[] = [];
	/** The backend answered the list (else the stand-in built-in pack is shown). */
	private available = false;
	private loaded = false;
	private selectedKey: string | undefined;
	private tab: PackagesTab = 'installed';
	private kindFilter: PackageKind | 'all' = 'all';
	/** Detail answers (`saengine.codes.show`) and validation results, by pack key. */
	private readonly details = new Map<string, ICodePackInfo>();
	private readonly validated = new Map<string, readonly string[]>();
	private loadVersion = 0;

	private indexState: IPackageIndexState | undefined;
	private index: IPackageIndex | undefined;
	private indexLoading = false;
	/** An offline bundle opened with Install from File... (round M8): Browse lists it, installs copy from it. */
	private bundle: { readonly folder: string; readonly source: string } | undefined;
	/** Package keys (`kind/id`) being installed or updated, to disable their buttons. */
	private readonly busy = new Set<string>();

	private readonly tabDisposables = this._register(new DisposableStore());
	private readonly listDisposables = this._register(new DisposableStore());
	private readonly detailDisposables = this._register(new DisposableStore());
	private readonly loadScheduler = this._register(new RunOnceScheduler(() => void this.load(), 0));

	private readonly newAction = this._register(new Action('saengine.codePacks.newPack', localize('codePacks.new', "New Code Pack..."), ThemeIcon.asClassName(Codicon.add), true, () => this.newPack()));
	private readonly installAction = this._register(new Action('saengine.codePacks.installPack', localize('packages.installFromFile', "Install from File..."), ThemeIcon.asClassName(Codicon.package), true, () => this.install()));
	private readonly validateAction = this._register(new Action('saengine.codePacks.validatePack', localize('codePacks.validate', "Validate"), ThemeIcon.asClassName(Codicon.checklist), true, () => this.validate()));
	private readonly removeAction = this._register(new Action('saengine.packages.removePack', localize('packages.remove', "Remove..."), ThemeIcon.asClassName(Codicon.trash), true, () => this.removeSelected()));
	private readonly refreshAction = this._register(new Action('saengine.codePacks.refresh', localize('codePacks.refresh', "Refresh"), ThemeIcon.asClassName(Codicon.refresh), true, () => this.refresh()));
	private readonly openManifestAction = this._register(new Action('saengine.codePacks.openManifest', localize('codePacks.openManifest', "Open pack.json"), undefined, true, () => this.openManifest()));
	private readonly componentsAction = this._register(new Action('saengine.packages.components', localize('packages.components', "Installer Components..."), undefined, true, () => this.commandService.executeCommand(COMPONENTS_SHOW_COMMAND)));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IEditorService private readonly editorService: IEditorService,
		@IDialogService private readonly dialogService: IDialogService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@INotificationService private readonly notificationService: INotificationService,
		@IHoverService private readonly hoverService: IHoverService,
		@IProductService private readonly productService: IProductService,
	) {
		super(CodePacksEditor.ID, group, telemetryService, themeService, storageService);
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === CODES_LIST_COMMAND) {
				this.loadScheduler.schedule();
			}
		}));
		this._register(this.projectService.onDidChangeProject(() => this.loadScheduler.schedule()));
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: CodePacksEditor.ID,
			ariaLabel: localize('packages.toolbar', "Packages"),
			properties: { title: localize('codePacks.details', "Details"), defaultWidth: 340 },
		}));
		this.frame.element.classList.add('saengine-code-packs-editor');
		this.frame.setTitle(localize('packages.title', "Packages"));
		this.frame.setHelp(localize('packages.help', "Packages add to SAEngine without changing the program: design codes (a code as data: locations and hazard tables, loads, combinations, coefficients, materials, factors, detailing limits and the MEP tables, each with its clauses), structure templates (presets of the special-structure shapes) and building templates (a building specification for the New Building wizard). Browse lists the packages published for SAEngine: the list is signed, and every download is checked against its SHA-256 before it is installed. A package holds data only; Python hooks in a design code run only when you trust them. The project chooses its design code in 02 Project Settings."));
		this.frame.setActions([this.installAction, this.newAction, this.validateAction, this.removeAction, this.refreshAction, this.frame.togglePropertiesAction], [this.openManifestAction, this.componentsAction]);
		this.tabsElement = append(this.frame.controlsSlot, $('.packages-tabs', { role: 'tablist', 'aria-label': localize('packages.tabs', "Packages views") }));
		this.list = $('.code-packs-list', { role: 'listbox', tabIndex: 0, 'aria-label': localize('packages.listLabel', "Packages") });
		this.scrollable = this._register(new DomScrollableElement(this.list, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('code-packs-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this._register(addDisposableListener(this.list, EventType.KEY_DOWN, e => this.onKey(new StandardKeyboardEvent(e))));
	}

	override async setInput(input: CodePacksEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.render();
		await this.load();
		void this.loadIndex(false);
	}

	override clearInput(): void {
		this.listDisposables.clear();
		this.detailDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.list.focus();
	}

	/** Shows a tab and a kind (from "Get More..." links elsewhere). */
	show(args: IShowPackagesArgs = {}): void {
		if (args.tab) {
			this.tab = args.tab;
		}
		if (args.kind) {
			this.kindFilter = args.kind;
		}
		this.selectedKey = undefined;
		this.render();
		if (this.tab !== 'installed' && !this.index && !this.indexLoading) {
			void this.loadIndex(false);
		}
	}

	// ───────────────────────────── data ─────────────────────────────

	private get root(): URI | undefined {
		return this.projectService.project?.root;
	}

	private get saengineVersion(): string {
		return runningVersion(this.productService as unknown as { version: string; saengineVersion?: string });
	}

	private keyOf(pack: ICodePackInfo): string {
		return `${pack.kind}/${pack.scope}/${pack.id}`;
	}

	private indexKey(pkg: { readonly kind: PackageKind; readonly id: string }): string {
		return `index/${pkg.kind}/${pkg.id}`;
	}

	private fits(kind: PackageKind): boolean {
		return this.kindFilter === 'all' || this.kindFilter === kind;
	}

	/** The installed packs in list order (as grouped on the page), of the kind shown. */
	private get ordered(): ICodePackInfo[] {
		return groupPacks(this.packs.filter(p => this.fits(p.kind)), !!this.root).flatMap(g => g.packs);
	}

	private get installed(): IInstalledPackage[] {
		return this.packs.map(p => ({ id: p.id, kind: p.kind, version: p.version, scope: p.scope }));
	}

	private get newest(): IIndexPackage[] {
		return this.index ? newestPackages(this.index, this.saengineVersion) : [];
	}

	private get browseItems(): IIndexPackage[] {
		return this.newest.filter(p => this.fits(p.kind));
	}

	private get updates(): IPackageUpdate[] {
		return packageUpdates(this.installed, this.newest, this.saengineVersion);
	}

	private get updateItems(): IPackageUpdate[] {
		return this.updates.filter(u => this.fits(u.installed.kind));
	}

	/** The keys of the current tab's rows, in order. */
	private get rowKeys(): string[] {
		switch (this.tab) {
			case 'installed': return this.ordered.map(p => this.keyOf(p));
			case 'browse': return this.browseItems.map(p => this.indexKey(p));
			case 'updates': return this.updateItems.map(u => this.keyOf(this.packOf(u.installed) ?? builtinDefaultPack()));
		}
	}

	private packOf(installed: IInstalledPackage): ICodePackInfo | undefined {
		return this.packs.find(p => p.id === installed.id && p.kind === installed.kind && p.scope === installed.scope);
	}

	private get selected(): ICodePackInfo | undefined {
		const pack = this.packs.find(p => this.keyOf(p) === this.selectedKey);
		return pack ? this.details.get(this.keyOf(pack)) ?? pack : undefined;
	}

	private get selectedIndexPackage(): IIndexPackage | undefined {
		return this.newest.find(p => this.indexKey(p) === this.selectedKey);
	}

	private updateFor(pack: ICodePackInfo): IPackageUpdate | undefined {
		return this.updates.find(u => u.installed.id === pack.id && u.installed.kind === pack.kind && u.installed.scope === pack.scope);
	}

	/** Asks the backend for the packages; without it, the built-in BNBC 2020 stands alone. */
	async load(): Promise<void> {
		const version = ++this.loadVersion;
		let packs: ICodePackInfo[] | undefined;
		if (CommandsRegistry.getCommand(CODES_LIST_COMMAND)) {
			try {
				packs = readCodePacks(await this.commandService.executeCommand<unknown>(CODES_LIST_COMMAND, { root: this.root?.fsPath, kind: 'all' }));
			} catch (error) {
				packs = undefined;
				this.notificationService.warn(localize('packages.listFailed', "Could not list the packages: {0}", toErrorMessage(error)));
			}
		}
		if (version !== this.loadVersion) {
			return;
		}
		this.available = packs !== undefined;
		this.packs = packs ?? [builtinDefaultPack()];
		this.loaded = true;
		this.details.clear();
		this.ensureSelection();
		this.render();
		void this.loadDetails();
	}

	private ensureSelection(): void {
		const keys = this.rowKeys;
		if (this.selectedKey && keys.includes(this.selectedKey)) {
			return;
		}
		if (this.tab === 'installed') {
			const first = this.ordered.find(p => p.id === DEFAULT_CODE_PACK) ?? this.ordered[0];
			this.selectedKey = first ? this.keyOf(first) : undefined;
		} else {
			this.selectedKey = keys[0];
		}
	}

	/** The index: the cached one at once, then a fresh one when `refresh` or when it is stale. */
	private async loadIndex(refresh: boolean): Promise<void> {
		if (!CommandsRegistry.getCommand(PACKAGES_INDEX_COMMAND) || this.indexLoading || this.bundle) {
			return;
		}
		this.indexLoading = true;
		this.renderStatus();
		try {
			const state = await this.commandService.executeCommand<IPackageIndexState>(PACKAGES_INDEX_COMMAND, { refresh });
			this.indexState = state;
			this.index = state?.text ? readPackageIndex(state.text) : undefined;
		} catch (error) {
			this.indexState = { error: toErrorMessage(error) };
		} finally {
			this.indexLoading = false;
		}
		this.ensureSelection();
		this.render();
	}

	/** The selected pack in detail (sources, tables, trust), when the backend offers it. */
	private async loadDetails(): Promise<void> {
		const pack = this.tab === 'installed' ? this.packs.find(p => this.keyOf(p) === this.selectedKey) : undefined;
		// A shadowed pack is shown from the list alone: the backend's show describes the pack in force.
		if (!pack || pack.kind !== 'designCode' || !pack.effective || !this.available || this.details.has(this.keyOf(pack)) || !CommandsRegistry.getCommand(CODES_SHOW_COMMAND)) {
			return;
		}
		const key = this.keyOf(pack);
		try {
			const shown = readCodePack(await this.commandService.executeCommand<unknown>(CODES_SHOW_COMMAND, { id: pack.id, root: this.root?.fsPath }));
			if (shown) {
				// The list knows where the pack is installed; the details add the rest.
				this.details.set(key, { ...shown, kind: pack.kind, scope: pack.scope, path: shown.path ?? pack.path, problems: shown.problems.length ? shown.problems : pack.problems, usable: shown.usable && pack.usable, effective: pack.effective, shadowedBy: pack.shadowedBy, trust: shown.trust !== 'none' ? shown.trust : pack.trust, hooksFrom: shown.hooksFrom.length ? shown.hooksFrom : pack.hooksFrom });
			}
		} catch {
			// The list's own fields are shown.
		}
		if (this.selectedKey === key) {
			this.renderDetails();
		}
	}

	private async refresh(): Promise<void> {
		this.bundle = undefined;
		await this.load();
		await this.loadIndex(this.tab !== 'installed');
	}

	// ───────────────────────────── actions ─────────────────────────────

	private ensureBackend(command: string): boolean {
		if (CommandsRegistry.getCommand(command)) {
			return true;
		}
		this.notificationService.info(localize('codePacks.notAvailable', "Code packs are not available yet in this build: only the built-in {0} is used.", builtinDefaultPack().name));
		return false;
	}

	/** Makes a new pack's skeleton (asking what is not given) and opens its pack.json. */
	async newPack(args: INewCodePackArgs = {}): Promise<void> {
		if (!this.ensureBackend(CODES_NEW_COMMAND)) {
			return;
		}
		const codes = this.packs.filter(p => p.kind === 'designCode');
		const taken = this.packs.map(p => p.id);
		const id = args.id ?? await this.quickInputService.input({
			title: localize('codePacks.newTitle', "New Code Pack"),
			prompt: localize('codePacks.newIdPrompt', "The pack's id, such as nbc-nepal-2020 (lowercase, no spaces)."),
			placeHolder: localize('codePacks.newIdPlaceholder', "pack id"),
			validateInput: async value => packIdProblem(value.trim(), taken),
		});
		if (!id || packIdProblem(id.trim(), taken)) {
			return;
		}
		const name = args.name ?? await this.quickInputService.input({
			title: localize('codePacks.newTitle', "New Code Pack"),
			prompt: localize('codePacks.newNamePrompt', "The pack's name, as the project settings show it."),
			placeHolder: localize('codePacks.newNamePlaceholder', "e.g. Nepal NBC 2020"),
			value: id.trim(),
			validateInput: async value => value.trim() ? undefined : localize('codePacks.nameEmpty', "Give the pack a name."),
		});
		if (!name?.trim()) {
			return;
		}
		let base = args.extends;
		if (!base) {
			const items: (IQuickPickItem & { id: string })[] = codes.map(p => ({ id: p.id, label: p.name, description: scopeLabel(p.scope), detail: p.edition || undefined }));
			const picked = await this.quickInputService.pick(items, {
				title: localize('codePacks.newExtendsTitle', "New Code Pack: Extends"),
				placeHolder: localize('codePacks.newExtendsPlaceholder', "The pack it starts from: it inherits every table it does not override"),
			});
			base = picked?.id;
		}
		if (!base) {
			return;
		}
		const scope = args.scope ?? await this.pickScope(localize('codePacks.newWhereTitle', "New Code Pack: Keep It In"));
		if (!scope) {
			return;
		}
		const root = this.root;
		const dest = scope === 'project' && root ? joinPath(root, PROJECT_PACKS_FOLDER).fsPath : undefined;
		try {
			const result = await this.commandService.executeCommand<unknown>(CODES_NEW_COMMAND, { id: id.trim(), name: name.trim(), extends: base, scope, dest, root: root?.fsPath });
			const path = typeof result === 'string' ? result : (result as { path?: unknown } | undefined)?.path;
			this.tab = 'installed';
			await this.load();
			this.selectedKey = `designCode/${scope}/${id.trim()}`;
			this.render();
			const folder = typeof path === 'string' ? path : dest ? joinPath(URI.file(dest), id.trim()).fsPath : undefined;
			if (folder) {
				await this.openFile(folder.endsWith('pack.json') ? URI.file(folder) : joinPath(URI.file(folder), 'pack.json'));
			}
		} catch (error) {
			this.notificationService.error(localize('codePacks.newFailed', "Could not make the code pack: {0}", toErrorMessage(error)));
		}
	}

	/** Installs a package folder or .zip (any kind): a design code into your packs or the project, a template for you. */
	async install(args: IInstallCodePackArgs = {}): Promise<void> {
		if (!this.ensureBackend(CODES_INSTALL_COMMAND)) {
			return;
		}
		let path = args.path;
		if (!path) {
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('packages.installTitle', "Install Package from File"),
				openLabel: localize('codePacks.installOpen', "&&Install"),
				canSelectFiles: true,
				canSelectFolders: true,
				canSelectMany: false,
				filters: [{ name: localize('packages.zipFilter', "Package (.zip)"), extensions: ['zip'] }],
			});
			path = picked?.[0]?.fsPath;
		}
		if (!path) {
			return;
		}
		if (await this.openBundle(path)) {
			return;
		}
		const scope = args.scope ?? await this.pickScope(localize('packages.installWhereTitle', "Install a Design Code In (templates are always installed for you)"));
		if (!scope) {
			return;
		}
		const installed = await this.installPath(path, scope, false);
		if (installed) {
			this.notificationService.info(localize('packages.installed', "Installed {0} ({1}).", installed.name, kindLabel(installed.kind)));
		}
	}

	/**
	 * Hands a folder or zip to the backend's install. A template offered for the project goes to
	 * the user instead (templates are applied, not kept in a project). Undefined on failure (shown).
	 */
	private async installPath(path: string, scope: 'user' | 'project', replace: boolean): Promise<ICodePackInfo | undefined> {
		const run = async (where: 'user' | 'project') => readCodePack(await this.commandService.executeCommand<unknown>(CODES_INSTALL_COMMAND, { path, scope: where, root: this.root?.fsPath, replace }));
		let installed: ICodePackInfo | undefined;
		try {
			try {
				installed = await run(scope);
			} catch (error) {
				if (scope !== 'project' || !/installed for the user/.test(toErrorMessage(error))) {
					throw error;
				}
				installed = await run('user');
			}
		} catch (error) {
			this.notificationService.error(localize('packages.installFailed', "Could not install the package: {0}", toErrorMessage(error)));
			return undefined;
		}
		this.tab = this.tab === 'updates' && this.updates.length > 1 ? 'updates' : 'installed';
		await this.load();
		if (installed) {
			this.selectedKey = this.keyOf(installed);
			this.render();
			void this.loadDetails();
			if (installed.missingRequires.length) {
				this.notificationService.warn(localize('packages.needsMore', "{0} needs packages that are not installed: {1}. Install them from Browse.", installed.name, installed.missingRequires.join(', ')));
			}
		}
		return installed;
	}

	/**
	 * An offline bundle (a folder or zip with index.json, index.json.sig and packages/*.zip):
	 * its signed index is shown in Browse and installs copy the zips from it, checked against the
	 * same SHA-256. False when `path` is not a bundle (then it is one package).
	 */
	private async openBundle(path: string): Promise<boolean> {
		if (!CommandsRegistry.getCommand(PACKAGES_OPEN_BUNDLE_COMMAND)) {
			return false;
		}
		let opened: (IPackageIndexState & { folder?: string }) | undefined;
		try {
			opened = await this.commandService.executeCommand<IPackageIndexState & { folder?: string }>(PACKAGES_OPEN_BUNDLE_COMMAND, { path });
		} catch (error) {
			this.notificationService.error(localize('packages.bundleRefused', "The offline bundle was not used: {0}", toErrorMessage(error)));
			return true;
		}
		if (!opened?.text || !opened.folder) {
			return false;
		}
		this.bundle = { folder: opened.folder, source: path };
		this.indexState = opened;
		this.index = readPackageIndex(opened.text);
		this.tab = 'browse';
		this.selectedKey = undefined;
		this.ensureSelection();
		this.render();
		this.notificationService.info(localize('packages.bundleOpened', "Offline bundle opened: {0} packages. Install them from Browse.", this.newest.length));
		return true;
	}

	private async pickScope(title: string): Promise<'user' | 'project' | undefined> {
		if (!this.root) {
			return 'user';
		}
		const items: (IQuickPickItem & { scope: 'user' | 'project' })[] = [
			{ scope: 'user', label: localize('codePacks.whereUser', "Your Packs"), detail: localize('codePacks.whereUserDetail', "On this computer, for every project") },
			{ scope: 'project', label: localize('codePacks.whereProject', "This Project"), detail: localize('codePacks.whereProjectDetail', "In {0}: travels with the project and its .civil archive", PROJECT_PACKS_FOLDER) },
		];
		return (await this.quickInputService.pick(items, { title }))?.scope;
	}

	/**
	 * Installs (or, with `update`, updates) a package of the index: checks it fits this SAEngine,
	 * offers the packages it requires, downloads the zip pinned by the index's size and SHA-256
	 * (main process), installs it like a file and deletes the download.
	 */
	async installFromIndex(pkg: IIndexPackage, update?: IPackageUpdate): Promise<void> {
		const key = this.indexKey(pkg);
		if (this.busy.has(key) || !this.ensureBackend(CODES_INSTALL_COMMAND) || !CommandsRegistry.getCommand(PACKAGES_DOWNLOAD_COMMAND)) {
			return;
		}
		const newer = needsNewerSaengine(pkg, this.saengineVersion);
		if (newer) {
			this.notificationService.warn(localize('packages.cannotInstall', "{0} cannot be installed: {1}", pkg.name, newer));
			return;
		}
		let scope: 'user' | 'project' = 'user';
		if (update) {
			scope = update.installed.scope === 'project' ? 'project' : 'user';
			if (scope === 'project') {
				const { confirmed } = await this.dialogService.confirm({
					type: 'warning',
					message: localize('packages.updateProjectMessage', "Update {0} in this project to version {1}?", pkg.name, pkg.version),
					detail: localize('packages.updateProjectDetail', "This project's design code changes: loads and design results may change. Run the analysis and design again (Run All) before using any result. The report records the pack version, so results before and after the update stay traceable."),
					primaryButton: localize('packages.updateButton', "&&Update"),
				});
				if (!confirmed) {
					return;
				}
			}
		} else if (pkg.kind === 'designCode') {
			const picked = await this.pickScope(localize('packages.installCodeWhere', "Install {0} In", pkg.name));
			if (!picked) {
				return;
			}
			scope = picked;
		}
		if (pkg.hooks) {
			const { confirmed } = await this.dialogService.confirm({
				type: 'info',
				message: localize('packages.hooksMessage', "{0} contains code (Python hooks).", pkg.name),
				detail: localize('packages.hooksDetail', "Installing it does not trust its code: its data is used, its hooks do not run until you read them and choose Trust on the Installed tab. The index's reviewers saw the code with the hash {0}.", pkg.hooksSha256 ?? localize('packages.hooksNoHash', "(not given)")),
				primaryButton: localize('packages.installAnyway', "&&Install"),
			});
			if (!confirmed) {
				return;
			}
		}
		// Required packages first, from the same index.
		for (const need of missingRequirements(pkg, this.installed, this.newest)) {
			if (!need.available) {
				this.notificationService.warn(localize('packages.requiredMissing', "{0} needs {1} {2}, which neither this computer nor the index has. It is installed anyway and cannot be used until that package is installed.", pkg.name, need.id, need.range));
				continue;
			}
			const { confirmed } = await this.dialogService.confirm({
				message: localize('packages.requiredMessage', "{0} needs {1} {2}. Install it first?", pkg.name, need.available.name, need.range),
				primaryButton: localize('packages.requiredInstall', "&&Install Both"),
			});
			if (!confirmed) {
				return;
			}
			if (!await this.downloadAndInstall(need.available, need.available.kind === 'designCode' ? scope : 'user', false)) {
				return;
			}
		}
		await this.downloadAndInstall(pkg, scope, !!update);
	}

	private async downloadAndInstall(pkg: IIndexPackage, scope: 'user' | 'project', replace: boolean): Promise<boolean> {
		const key = this.indexKey(pkg);
		this.busy.add(key);
		this.frame.setStatus({ text: localize('packages.downloading', "Downloading {0} {1} ({2})...", pkg.name, pkg.version, sizeLabel(pkg.size)), busy: true });
		this.renderDetails();
		let path: string | undefined;
		try {
			const request: IPackageDownload = { url: pkg.url, size: pkg.size, sha256: pkg.sha256, fileName: packageFileName(pkg) };
			path = this.bundle
				? await this.commandService.executeCommand<string>(PACKAGES_COPY_COMMAND, { ...request, path: `${this.bundle.folder}/packages/${pkg.url.split('/').pop() ?? request.fileName}` })
				: await this.commandService.executeCommand<string>(PACKAGES_DOWNLOAD_COMMAND, request);
		} catch (error) {
			this.busy.delete(key);
			this.notificationService.error(localize('packages.downloadFailed', "{0} could not be downloaded: {1}", pkg.name, toErrorMessage(error)));
			this.render();
			return false;
		}
		try {
			const installed = path ? await this.installPath(path, scope, replace) : undefined;
			if (installed) {
				this.notificationService.info(replace
					? localize('packages.updated', "Updated {0} to version {1}.", pkg.name, pkg.version)
					: localize('packages.installedFromIndex', "Installed {0} {1} ({2}).", pkg.name, pkg.version, kindLabel(pkg.kind)));
			}
			return !!installed;
		} finally {
			this.busy.delete(key);
			if (path) {
				void this.commandService.executeCommand(PACKAGES_DISCARD_COMMAND, { path }).catch(() => undefined);
			}
			this.render();
		}
	}

	/** Removes the selected user or project package after asking. */
	async removeSelected(): Promise<void> {
		const pack = this.tab === 'installed' ? this.selected : undefined;
		if (!pack || pack.scope === 'builtin' || !this.ensureBackend(CODES_REMOVE_COMMAND)) {
			return;
		}
		const chosen = pack.kind === 'designCode' && this.projectService.project && pack.effective;
		const { confirmed } = await this.dialogService.confirm({
			type: 'warning',
			message: localize('packages.removeMessage', "Remove {0} ({1}, {2})?", pack.name, kindLabel(pack.kind), scopeLabel(pack.scope)),
			detail: pack.scope === 'project'
				? localize('packages.removeProjectDetail', "Its folder is deleted from {0}. A project whose settings choose it cannot be analysed until another design code is chosen or it is installed again.", PROJECT_PACKS_FOLDER)
				: chosen
					? localize('packages.removeUserCodeDetail', "Its folder is deleted from this computer. Projects that choose it cannot be analysed until another design code is chosen or it is installed again. Projects already made from a template keep what the template gave them.")
					: localize('packages.removeUserDetail', "Its folder is deleted from this computer. Projects already made from a template keep what the template gave them."),
			primaryButton: localize('packages.removeButton', "&&Remove"),
		});
		if (!confirmed) {
			return;
		}
		try {
			const result = await this.commandService.executeCommand<{ ok?: boolean; message?: string }>(CODES_REMOVE_COMMAND, { id: pack.id, scope: pack.scope, kind: pack.kind, root: this.root?.fsPath });
			if (result && result.ok === false) {
				throw new Error(result.message ?? '');
			}
			this.selectedKey = undefined;
			await this.load();
			this.notificationService.info(localize('packages.removed', "Removed {0}.", pack.name));
		} catch (error) {
			this.notificationService.error(localize('packages.removeFailed', "Could not remove {0}: {1}", pack.name, toErrorMessage(error)));
		}
	}

	/** Checks the selected pack's folder against the pack format and shows its problems. */
	async validate(): Promise<void> {
		const pack = this.selected;
		if (!pack || !this.ensureBackend(CODES_VALIDATE_COMMAND)) {
			return;
		}
		if (!pack.path) {
			this.notificationService.info(localize('codePacks.noPath', "The backend did not say where {0} is, so it cannot be validated from here.", pack.name));
			return;
		}
		try {
			const problems = readProblems(await this.commandService.executeCommand<unknown>(CODES_VALIDATE_COMMAND, { path: pack.path }));
			this.validated.set(this.keyOf(pack), problems);
			this.render();
			this.notificationService.info(problems.length === 0
				? localize('codePacks.valid', "{0} is valid.", pack.name)
				: problems.length === 1
					? localize('codePacks.oneProblem', "{0} has 1 problem: {1}", pack.name, problems[0])
					: localize('codePacks.problems', "{0} has {1} problems; they are listed in its details.", pack.name, problems.length));
		} catch (error) {
			this.notificationService.error(localize('codePacks.validateFailed', "Could not validate the code pack: {0}", toErrorMessage(error)));
		}
	}

	/** Asks before a pack's hooks may run (they are code), or stops trusting them. */
	async setTrust(pack: ICodePackInfo, trusted: boolean): Promise<void> {
		// The backend trusts the pack in force with this id; a shadowed one is not it.
		if (!pack.effective || !this.ensureBackend(CODES_TRUST_COMMAND)) {
			return;
		}
		if (trusted) {
			const { confirmed } = await this.dialogService.confirm({
				type: 'warning',
				message: localize('codePacks.trustMessage', "Trust the hooks of {0}?", pack.name),
				detail: localize('codePacks.trustDetail', "Hooks are Python code in the pack that replace SAEngine's design functions. Trusted hooks run with your permissions every time a project using this pack is designed: they can read, change or send any file this computer lets you reach, and they can make the design wrong. Trust them only if you wrote the pack or know who did and have read its hooks. The pack's data tables are used either way."),
				primaryButton: localize('codePacks.trustButton', "&&Trust Hooks"),
			});
			if (!confirmed) {
				return;
			}
		}
		try {
			await this.commandService.executeCommand(CODES_TRUST_COMMAND, { id: pack.id, trusted, root: this.root?.fsPath, kind: pack.kind });
			await this.load();
		} catch (error) {
			this.notificationService.error(localize('codePacks.trustFailed', "Could not change the trust of the code pack: {0}", toErrorMessage(error)));
		}
	}

	private async openManifest(): Promise<void> {
		const pack = this.selected;
		if (pack?.path) {
			await this.openFile(joinPath(URI.file(pack.path), 'pack.json'));
		}
	}

	private async openFile(resource: URI): Promise<void> {
		await this.editorService.openEditor({ resource, options: { pinned: true, override: DEFAULT_EDITOR_ASSOCIATION.id } });
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private selectKey(key: string, focus = true): void {
		this.selectedKey = key;
		this.render();
		if (focus) {
			this.list.focus();
		}
		void this.loadDetails();
	}

	private onKey(e: StandardKeyboardEvent): void {
		const keys = this.rowKeys;
		const index = keys.findIndex(k => k === this.selectedKey);
		const next = e.keyCode === KeyCode.DownArrow ? keys[Math.min(index + 1, keys.length - 1)] : e.keyCode === KeyCode.UpArrow ? keys[Math.max(index - 1, 0)]
			: e.keyCode === KeyCode.Home ? keys[0] : e.keyCode === KeyCode.End ? keys[keys.length - 1] : undefined;
		if (next) {
			e.preventDefault();
			this.selectKey(next);
		} else if (e.keyCode === KeyCode.Enter && this.tab === 'installed' && this.selected?.path) {
			e.preventDefault();
			void this.openManifest();
		}
	}

	private problemsOf(pack: ICodePackInfo): readonly string[] {
		return this.validated.get(this.keyOf(pack)) ?? pack.problems;
	}

	private render(): void {
		if (!this.frame) {
			return;
		}
		this.renderTabs();
		this.renderList();
		this.renderDetails();
		this.renderStatus();
		const selected = this.tab === 'installed' ? this.selected : undefined;
		const backend = this.available;
		this.newAction.enabled = backend;
		this.installAction.enabled = backend;
		this.validateAction.enabled = backend && !!selected?.path;
		this.removeAction.enabled = backend && !!selected && selected.scope !== 'builtin';
		this.openManifestAction.enabled = !!selected?.path;
	}

	private renderTabs(): void {
		this.tabDisposables.clear();
		clearNode(this.tabsElement);
		const updates = this.updates.length;
		const tabs: { readonly id: PackagesTab; readonly label: string }[] = [
			{ id: 'installed', label: localize('packages.tabInstalled', "Installed") },
			{ id: 'browse', label: localize('packages.tabBrowse', "Browse") },
			{ id: 'updates', label: updates ? localize('packages.tabUpdatesCount', "Updates ({0})", updates) : localize('packages.tabUpdates', "Updates") },
		];
		for (const tab of tabs) {
			const button = append(this.tabsElement, $('button.packages-tab', { role: 'tab', 'aria-selected': String(this.tab === tab.id), type: 'button' }, tab.label));
			button.classList.toggle('active', this.tab === tab.id);
			this.tabDisposables.add(addDisposableListener(button, EventType.CLICK, () => this.show({ tab: tab.id })));
		}
	}

	private renderKindFilter(): void {
		const bar = append(this.list, $('.packages-kinds', { role: 'radiogroup', 'aria-label': localize('packages.kindFilter', "Kind") }));
		const kinds: (PackageKind | 'all')[] = ['all', ...PACKAGE_KINDS];
		for (const kind of kinds) {
			const chip = append(bar, $('button.packages-kind', { role: 'radio', 'aria-checked': String(this.kindFilter === kind), type: 'button' }, kind === 'all' ? localize('packages.kindAll', "All") : kindPluralLabel(kind)));
			chip.classList.toggle('active', this.kindFilter === kind);
			this.listDisposables.add(addDisposableListener(chip, EventType.CLICK, () => this.show({ kind })));
		}
	}

	private renderList(): void {
		this.listDisposables.clear();
		clearNode(this.list);
		if (!this.loaded) {
			return;
		}
		this.renderKindFilter();
		switch (this.tab) {
			case 'installed': this.renderInstalled(); break;
			case 'browse': this.renderBrowse(); break;
			case 'updates': this.renderUpdates(); break;
		}
		if (this.selectedKey) {
			this.list.setAttribute('aria-activedescendant', this.rowId(this.selectedKey));
		} else {
			this.list.removeAttribute('aria-activedescendant');
		}
		this.scrollable.scanDomNode();
	}

	private rowId(key: string): string {
		return `package-${key.replace(/[^a-z0-9_-]/gi, '_')}`;
	}

	private renderInstalled(): void {
		const visible = this.packs.filter(p => this.fits(p.kind));
		for (const group of groupPacks(visible, !!this.root)) {
			const section = append(this.list, $('.code-packs-group', { role: 'group', 'aria-label': group.title }));
			append(section, $('.code-packs-group-title', undefined, group.title));
			if (!group.packs.length) {
				append(section, $('.code-packs-empty', undefined, group.empty));
				continue;
			}
			for (const pack of group.packs) {
				this.renderRow(section, pack);
			}
		}
		const components = append(this.list, $('.code-packs-group.packages-components'));
		append(components, $('.code-packs-group-title', undefined, localize('packages.componentsTitle', "Installer Components")));
		append(components, $('.code-packs-empty', undefined, localize('packages.componentsText', "Optional programs of the SAEngine setup (EnergyPlus, LibreCAD, LibreDWG, the AI assistant, Git, collaboration) are added or removed by running the setup again.")));
		const button = this.listDisposables.add(new Button(append(components, $('.code-packs-trust-button')), { ...defaultButtonStyles, secondary: true }));
		button.label = localize('packages.componentsButton', "Show Installer Components...");
		this.listDisposables.add(button.onDidClick(() => this.commandService.executeCommand(COMPONENTS_SHOW_COMMAND)));
	}

	private renderRow(container: HTMLElement, pack: ICodePackInfo): void {
		const key = this.keyOf(pack);
		const selected = key === this.selectedKey;
		const problems = this.problemsOf(pack);
		const row = append(container, $('.code-packs-row', { role: 'option', id: this.rowId(key), 'aria-selected': String(selected) }));
		row.classList.toggle('selected', selected);
		row.classList.toggle('shadowed', !pack.effective);
		append(row, $(`span.code-packs-icon${ThemeIcon.asCSSSelector(KIND_ICONS[pack.kind])}`));
		const body = append(row, $('.code-packs-text'));
		const head = append(body, $('.code-packs-head'));
		append(head, $('span.code-packs-name', undefined, pack.name));
		if (pack.id === DEFAULT_CODE_PACK && pack.scope === 'builtin') {
			append(head, $('span.code-packs-badge', undefined, localize('codePacks.default', "default")));
		}
		if (this.kindFilter === 'all' && pack.kind !== 'designCode') {
			append(head, $('span.code-packs-badge', undefined, kindLabel(pack.kind)));
		}
		const update = this.updateFor(pack);
		if (update) {
			append(head, $('span.code-packs-badge.update', undefined, localize('packages.updateBadge', "update {0}", update.available.version)));
		}
		if (!pack.effective) {
			append(head, $('span.code-packs-badge.shadowed', undefined, pack.shadowedBy ? localize('codePacks.shadowedBadge', "shadowed by {0}", scopeLabel(pack.shadowedBy)) : localize('codePacks.shadowedBadgePlain', "shadowed")));
		}
		const meta = [pack.edition && pack.edition !== pack.name ? pack.edition : '', pack.region, extendsLabel(pack, this.packs) ?? '', pack.version ? localize('codePacks.version', "v{0}", pack.version) : ''].filter(Boolean);
		append(body, $('.code-packs-meta', undefined, meta.length ? meta.join(' · ') : pack.id));
		if (pack.covers.length) {
			const chips = append(body, $('.code-packs-chips', { 'aria-label': localize('codePacks.coversLabel', "Provides") }));
			for (const area of pack.covers) {
				append(chips, $('span.code-packs-chip', undefined, coverageLabel(area)));
			}
		}
		const end = append(row, $('.code-packs-end'));
		if (pack.trust !== 'none') {
			const trust = append(end, $(`span.code-packs-trust.${pack.trust}${ThemeIcon.asCSSSelector(pack.trust === 'trusted' ? Codicon.workspaceTrusted : Codicon.workspaceUntrusted)}`, { 'aria-label': trustLabel(pack.trust) }));
			this.listDisposables.add(this.hoverService.setupDelayedHover(trust, { content: trustLabel(pack.trust) }));
		}
		if (problems.length) {
			const badge = append(end, $('span.code-packs-problems'));
			append(badge, $(ThemeIcon.asCSSSelector(Codicon.warning)));
			append(badge, $('span', undefined, problems.length === 1 ? localize('codePacks.problemCountOne', "1 problem") : localize('codePacks.problemCount', "{0} problems", problems.length)));
			this.listDisposables.add(this.hoverService.setupDelayedHover(badge, { content: problems.join('\n') }));
		}
		this.listDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.selectKey(key)));
		this.listDisposables.add(addDisposableListener(row, EventType.DBLCLICK, () => void this.openManifest()));
	}

	/** Whether `pkg` is installed, and in which version (the newest installed copy). */
	private installedCopy(pkg: { readonly id: string; readonly kind: PackageKind }): ICodePackInfo | undefined {
		return this.packs.filter(p => p.id === pkg.id && p.kind === pkg.kind).sort((a, b) => (b.effective ? 1 : 0) - (a.effective ? 1 : 0))[0];
	}

	private renderIndexMessage(): boolean {
		if (!CommandsRegistry.getCommand(PACKAGES_INDEX_COMMAND)) {
			append(this.list, $('.code-packs-empty', undefined, localize('packages.browseDesktopOnly', "Browsing published packages needs the SAEngine desktop app. Install from File... installs a package you were given.")));
			return true;
		}
		if (!this.index) {
			const text = this.indexLoading
				? localize('packages.indexLoading', "Reading the list of published packages...")
				: this.indexState?.offline
					? localize('packages.indexOffline', "Online checks are off (setting SAEngine › Packages: Check Online). Refresh reads the list once; Install from File... works offline.")
					: this.indexState?.error
						? localize('packages.indexError', "The list of published packages could not be read: {0} Install from File... still works.", this.indexState.error)
						: localize('packages.indexNone', "No list of published packages yet. Refresh reads it.");
			append(this.list, $('.code-packs-empty', undefined, text));
			return true;
		}
		return false;
	}

	private renderBrowse(): void {
		if (this.renderIndexMessage()) {
			return;
		}
		const items = this.browseItems;
		const section = append(this.list, $('.code-packs-group', { role: 'group' }));
		if (!items.length) {
			append(section, $('.code-packs-empty', undefined, this.kindFilter === 'all'
				? localize('packages.browseEmpty', "No packages are published yet.")
				: localize('packages.browseEmptyKind', "No {0} are published yet.", kindPluralLabel(this.kindFilter).toLowerCase())));
			return;
		}
		for (const pkg of items) {
			const key = this.indexKey(pkg);
			const selected = key === this.selectedKey;
			const row = append(section, $('.code-packs-row', { role: 'option', id: this.rowId(key), 'aria-selected': String(selected) }));
			row.classList.toggle('selected', selected);
			append(row, $(`span.code-packs-icon${ThemeIcon.asCSSSelector(KIND_ICONS[pkg.kind])}`));
			const body = append(row, $('.code-packs-text'));
			const head = append(body, $('.code-packs-head'));
			append(head, $('span.code-packs-name', undefined, pkg.name));
			const copy = this.installedCopy(pkg);
			if (copy) {
				append(head, $('span.code-packs-badge', undefined, copy.version ? localize('packages.installedBadgeVersion', "installed v{0}", copy.version) : localize('packages.installedBadge', "installed")));
			}
			if (pkg.source === 'community') {
				append(head, $('span.code-packs-badge', undefined, localize('packages.community', "community")));
			}
			if (pkg.hooks) {
				append(head, $('span.code-packs-badge.shadowed', undefined, localize('packages.containsCode', "contains code")));
			}
			const meta = [kindLabel(pkg.kind), pkg.country || pkg.region, pkg.author, pkg.licence, sizeLabel(pkg.size), localize('codePacks.version', "v{0}", pkg.version)].filter(Boolean);
			append(body, $('.code-packs-meta', undefined, meta.join(' · ')));
			if (pkg.description) {
				append(body, $('.code-packs-meta.packages-description', undefined, pkg.description));
			}
			const newer = needsNewerSaengine(pkg, this.saengineVersion);
			if (newer) {
				const end = append(row, $('.code-packs-end'));
				const badge = append(end, $('span.code-packs-problems'));
				append(badge, $(ThemeIcon.asCSSSelector(Codicon.warning)));
				append(badge, $('span', undefined, localize('packages.newerBadge', "needs SAEngine {0}", pkg.requiresSaengine)));
			}
			this.listDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.selectKey(key)));
			this.listDisposables.add(addDisposableListener(row, EventType.DBLCLICK, () => void this.installFromIndex(pkg)));
		}
	}

	private renderUpdates(): void {
		if (this.renderIndexMessage()) {
			return;
		}
		const items = this.updateItems;
		const section = append(this.list, $('.code-packs-group', { role: 'group' }));
		if (!items.length) {
			append(section, $('.code-packs-empty', undefined, localize('packages.noUpdates', "Every installed package is up to date. Built-in packages are updated with SAEngine itself.")));
			return;
		}
		for (const update of items) {
			const pack = this.packOf(update.installed);
			if (!pack) {
				continue;
			}
			const key = this.keyOf(pack);
			const selected = key === this.selectedKey;
			const row = append(section, $('.code-packs-row', { role: 'option', id: this.rowId(key), 'aria-selected': String(selected) }));
			row.classList.toggle('selected', selected);
			append(row, $(`span.code-packs-icon${ThemeIcon.asCSSSelector(KIND_ICONS[pack.kind])}`));
			const body = append(row, $('.code-packs-text'));
			const head = append(body, $('.code-packs-head'));
			append(head, $('span.code-packs-name', undefined, pack.name));
			append(head, $('span.code-packs-badge', undefined, scopeLabel(pack.scope)));
			append(body, $('.code-packs-meta', undefined, localize('packages.updateMeta', "{0} · v{1} → v{2} · {3}", kindLabel(pack.kind), pack.version || '?', update.available.version, sizeLabel(update.available.size))));
			const end = append(row, $('.code-packs-end'));
			const button = this.listDisposables.add(new Button(end, { ...defaultButtonStyles, secondary: true }));
			button.label = localize('packages.update', "Update");
			button.enabled = !this.busy.has(this.indexKey(update.available));
			this.listDisposables.add(button.onDidClick(() => void this.installFromIndex(update.available, update)));
			this.listDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.selectKey(key)));
		}
	}

	private renderDetails(): void {
		const panel = this.frame.properties;
		if (!panel) {
			return;
		}
		this.detailDisposables.clear();
		clearNode(panel);
		if (this.tab === 'browse') {
			const pkg = this.selectedIndexPackage;
			if (pkg) {
				this.renderIndexDetails(panel, pkg);
			}
			return;
		}
		const pack = this.selected;
		if (!pack) {
			return;
		}
		append(panel, $('.code-packs-detail-title', undefined, pack.name));
		const row = (name: string, value: string | undefined) => {
			if (value) {
				appendPropertyRow(panel, name, value);
			}
		};
		row(localize('codePacks.id', "Id"), pack.id);
		row(localize('packages.kind', "Kind"), kindLabel(pack.kind));
		row(localize('codePacks.edition', "Edition"), pack.edition);
		row(localize('codePacks.region', "Region"), pack.region);
		row(localize('codePacks.versionLabel', "Version"), pack.version);
		row(localize('codePacks.where', "Installed"), scopeLabel(pack.scope));
		const update = this.updateFor(pack);
		if (update) {
			appendPropertyNote(panel, localize('packages.updateNote', "Version {0} is published.", update.available.version));
			this.detailButton(panel, localize('packages.updateTo', "Update to {0}", update.available.version), () => this.installFromIndex(update.available, update), !this.busy.has(this.indexKey(update.available)));
		}
		const shadowed = shadowedLabel(pack);
		if (shadowed) {
			appendPropertyNote(panel, shadowed);
		}
		if (!pack.usable) {
			appendPropertyNote(panel, localize('codePacks.unusableNote', "This pack, or a pack it extends, has errors: it cannot be chosen as a project's design code until they are fixed."));
		}
		if (pack.missingRequires.length) {
			appendPropertyNote(panel, localize('packages.missingRequires', "Needs packages that are not installed: {0}.", pack.missingRequires.join(', ')));
		}
		if (pack.kind === 'designCode') {
			row(localize('codePacks.extendsLabel', "Extends"), pack.extends ? (this.packs.find(p => p.id === pack.extends)?.name ?? pack.extends) : localize('codePacks.extendsNone', "nothing (a complete code)"));
		}
		row(localize('codePacks.author', "Author"), pack.author);
		row(localize('codePacks.licence', "Licence"), pack.licence);
		if (pack.path) {
			const path = appendPropertyRow(panel, localize('codePacks.folder', "Folder"), pack.path);
			path.classList.add('code-packs-path');
			this.detailDisposables.add(this.hoverService.setupDelayedHover(path, { content: pack.path }));
		}
		if (pack.description) {
			appendPropertyNote(panel, pack.description);
		}
		if (pack.scope !== 'builtin' && this.available) {
			this.detailButton(panel, localize('packages.removeDetail', "Remove..."), () => this.removeSelected(), true);
		}
		if (pack.kind !== 'designCode') {
			appendPropertyNote(panel, pack.kind === 'structureTemplate'
				? localize('packages.structureUse', "Its presets are offered in the modeller's Generate panel.")
				: localize('packages.buildingUse', "It is offered in the New Building wizard's Start from list; a full template opens with New Project from Template..."));
			if (pack.trust !== 'none') {
				// Coded templates (round M5): the package's code makes the geometry, only when trusted.
				appendPropertyHeading(panel, localize('codePacks.hooks', "Hooks"));
				appendPropertyNote(panel, pack.trust === 'trusted'
					? localize('packages.codedTrusted', "Its code is trusted: its coded templates make their geometry in the Generate panel.")
					: localize('packages.codedUntrusted', "It contains code (coded templates) that is not trusted: those templates cannot make geometry until you read the hooks and trust them."));
				if (pack.scope !== 'builtin') {
					this.detailButton(panel, pack.trust === 'trusted' ? localize('codePacks.untrust', "Stop Trusting Hooks") : localize('packages.trustCode', "Trust This Package's Code..."), () => this.setTrust(pack, pack.trust !== 'trusted'), true);
				}
			}
			return;
		}

		appendPropertyHeading(panel, localize('codePacks.provides', "Provides"));
		if (pack.covers.length) {
			const chips = append(panel, $('.code-packs-chips.detail'));
			for (const area of pack.covers) {
				append(chips, $('span.code-packs-chip', undefined, coverageLabel(area)));
			}
		} else {
			appendPropertyNote(panel, this.available
				? localize('codePacks.coversNone', "No tables of its own: everything comes from the pack it extends.")
				: localize('codePacks.coversUnknown', "Shown when code packs are available in this build."));
		}

		if (pack.tables.length) {
			appendPropertyHeading(panel, localize('codePacks.tables', "Tables"));
			for (const table of pack.tables) {
				// The backend's PackInfo lists the resolved table names without their origin: a table the pack covers is its own, the rest come from the packs it extends.
				const own = table.from ? table.from === pack.id : pack.covers.includes(table.name);
				const from = table.from || (pack.extends ? this.packs.find(p => p.id === pack.extends)?.name ?? pack.extends : '');
				appendPropertyRow(panel, coverageLabel(table.name), own || !from ? localize('codePacks.tableOwn', "this pack") : localize('codePacks.tableInherited', "from {0}", this.packs.find(p => p.id === from)?.name ?? from));
			}
		}

		appendPropertyHeading(panel, localize('codePacks.sources', "Sources"));
		if (pack.sources.length) {
			const list = append(panel, $('ul.code-packs-sources'));
			for (const source of pack.sources) {
				const item = append(list, $('li'));
				if (source.table !== 'pack') {
					append(item, $('span.code-packs-source-table', undefined, coverageLabel(source.table)));
				}
				append(item, $('span', undefined, source.text));
			}
		} else {
			appendPropertyNote(panel, localize('codePacks.sourcesNone', "No clauses listed yet."));
		}

		const problems = this.problemsOf(pack);
		appendPropertyHeading(panel, localize('codePacks.problemsHeading', "Problems"));
		if (problems.length) {
			const list = append(panel, $('ul.code-packs-problem-list'));
			for (const problem of problems) {
				const item = append(list, $('li'));
				append(item, $(ThemeIcon.asCSSSelector(Codicon.warning)));
				append(item, $('span', undefined, problem));
			}
		} else {
			appendPropertyNote(panel, this.validated.has(this.keyOf(pack)) ? localize('codePacks.validNote', "Valid: no problems.") : localize('codePacks.noProblems', "None found."));
		}

		appendPropertyHeading(panel, localize('codePacks.hooks', "Hooks"));
		const trust = append(panel, $(`.code-packs-trust-state.${pack.trust}`));
		append(trust, $(ThemeIcon.asCSSSelector(pack.trust === 'trusted' ? Codicon.workspaceTrusted : pack.trust === 'untrusted' ? Codicon.workspaceUntrusted : Codicon.shield)));
		append(trust, $('span', undefined, trustLabel(pack.trust)));
		if (pack.hooksFrom.length && (pack.hooksFrom.length > 1 || pack.hooksFrom[0] !== pack.id)) {
			appendPropertyNote(panel, localize('codePacks.hooksFrom', "Hooks of: {0}", pack.hooksFrom.map(id => this.packs.find(p => p.id === id)?.name ?? id).join(', ')));
		}
		if (pack.trust !== 'none' && !pack.effective) {
			appendPropertyNote(panel, localize('codePacks.trustShadowed', "Trust is set on the pack in force; this one is not used while it is shadowed."));
		} else if (pack.trust !== 'none' && pack.scope !== 'builtin') {
			appendPropertyNote(panel, localize('codePacks.hooksNote', "Hooks are Python code that replaces SAEngine's design functions. They run only when trusted, with your permissions."));
			this.detailButton(panel, pack.trust === 'trusted' ? localize('codePacks.untrust', "Stop Trusting Hooks") : localize('codePacks.trust', "Trust This Pack's Hooks..."), () => this.setTrust(pack, pack.trust !== 'trusted'), true);
		}
	}

	private detailButton(panel: HTMLElement, label: string, run: () => unknown, enabled: boolean): void {
		const button = this.detailDisposables.add(new Button(append(panel, $('.code-packs-trust-button')), { ...defaultButtonStyles, secondary: true }));
		button.label = label;
		button.enabled = enabled;
		this.detailDisposables.add(button.onDidClick(() => void run()));
	}

	private renderIndexDetails(panel: HTMLElement, pkg: IIndexPackage): void {
		append(panel, $('.code-packs-detail-title', undefined, pkg.name));
		const row = (name: string, value: string | undefined) => {
			if (value) {
				appendPropertyRow(panel, name, value);
			}
		};
		row(localize('codePacks.id', "Id"), pkg.id);
		row(localize('packages.kind', "Kind"), kindLabel(pkg.kind));
		row(localize('codePacks.versionLabel', "Version"), pkg.version);
		row(localize('codePacks.region', "Region"), [pkg.country, pkg.region].filter(Boolean).join(' · '));
		row(localize('codePacks.author', "Author"), pkg.author);
		row(localize('codePacks.licence', "Licence"), pkg.licence);
		row(localize('packages.size', "Download"), sizeLabel(pkg.size));
		row(localize('packages.source', "Source"), pkg.source === 'official' ? localize('packages.official', "official") : localize('packages.community', "community"));
		row(localize('packages.repository', "Repository"), pkg.repository);
		row(localize('packages.requiresSaengine', "Needs SAEngine"), pkg.requiresSaengine);
		const required = Object.entries(pkg.requiresPackages);
		if (required.length) {
			row(localize('packages.requiresPackages', "Needs packages"), required.map(([id, range]) => `${id} ${range}`.trim()).join(', '));
		}
		if (pkg.description) {
			appendPropertyNote(panel, pkg.description);
		}
		if (pkg.hooks) {
			appendPropertyNote(panel, localize('packages.hooksCard', "Contains code (Python hooks): read it before trusting it. Installing does not trust it; the reviewed code's hash is {0}.", pkg.hooksSha256 ?? localize('packages.hooksNoHash', "(not given)")));
		}
		if (pkg.kind === 'designCode') {
			appendPropertyNote(panel, localize('packages.codeLimits', "A design code package gives the site and hazard values, loads, combinations and coefficients. Resistance factors and detailing limits of member design are still BNBC 2020's in this version (docs/code-packs.md, known limits)."));
		}
		const newer = needsNewerSaengine(pkg, this.saengineVersion);
		if (newer) {
			appendPropertyNote(panel, newer);
			return;
		}
		const copy = this.installedCopy(pkg);
		const update = copy ? this.updateFor(copy) : undefined;
		const busy = this.busy.has(this.indexKey(pkg));
		if (update) {
			this.detailButton(panel, localize('packages.updateTo', "Update to {0}", pkg.version), () => this.installFromIndex(pkg, update), !busy);
		} else if (copy && copy.scope !== 'builtin') {
			appendPropertyNote(panel, localize('packages.alreadyInstalled', "Installed ({0}).", scopeLabel(copy.scope)));
		} else {
			this.detailButton(panel, copy ? localize('packages.installCopy', "Install Your Own Copy") : localize('packages.install', "Install"), () => this.installFromIndex(pkg), !busy);
			if (copy) {
				appendPropertyNote(panel, localize('packages.shadowsBuiltin', "A copy installed for you is used instead of the built-in one."));
			}
		}
	}

	private renderStatus(): void {
		if (!this.loaded) {
			this.frame.setStatus({ text: localize('packages.loading', "Looking for packages..."), busy: true });
			return;
		}
		if (!this.available) {
			this.frame.setStatus({ text: localize('codePacks.standIn', "Code packs are not available yet in this build: the built-in {0} is used for every project.", builtinDefaultPack().name) });
			return;
		}
		if (this.tab !== 'installed') {
			if (this.indexLoading) {
				this.frame.setStatus({ text: localize('packages.indexLoading', "Reading the list of published packages..."), busy: true });
				return;
			}
			const state = this.indexState;
			if (this.bundle && state?.text) {
				this.frame.setStatus({ severity: state.test ? 'warning' : undefined, text: localize('packages.statusBundle', "Offline bundle {0}: its list is signed{1}, every package is checked against its SHA-256.", this.bundle.source, state.test ? localize('packages.testKeySuffix', " with the TEST key") : ''), link: { label: localize('packages.backOnline', "Published List"), run: () => void this.refresh() } });
				return;
			}
			if (state?.text) {
				const when = state.at ? new Date(state.at).toLocaleString() : '';
				const text = state.test
					? localize('packages.statusTest', "Published packages as of {0}, signed with the TEST key (development builds only).", when)
					: localize('packages.statusSigned', "Published packages as of {0}; the list's signature and every download's SHA-256 are checked.", when);
				this.frame.setStatus({ severity: state.error || state.test ? 'warning' : undefined, text: state.error ? localize('packages.statusStale', "{0} The latest check failed: {1}", text, state.error) : text, link: { label: localize('packages.refresh', "Refresh"), run: () => void this.loadIndex(true) } });
				return;
			}
			this.frame.setStatus({ text: localize('packages.statusNoIndex', "No list of published packages."), link: { label: localize('packages.refresh', "Refresh"), run: () => void this.loadIndex(true) } });
			return;
		}
		const count = (scope: CodePackScope) => this.packs.filter(p => p.scope === scope).length;
		const problems = this.packs.reduce((sum, p) => sum + this.problemsOf(p).length, 0);
		const text = localize('packages.status', "{0} built-in, {1} of yours, {2} in this project.", count('builtin'), count('user'), count('project'));
		this.frame.setStatus(problems
			? { severity: 'warning', text: problems === 1 ? localize('codePacks.statusOneProblem', "{0} 1 problem.", text) : localize('codePacks.statusProblems', "{0} {1} problems.", text, problems) }
			: { text });
	}
}
