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

/** Arguments of "Install Code Pack...": the folder or .zip, and where it goes. */
export interface IInstallCodePackArgs {
	readonly path?: string;
	readonly scope?: 'user' | 'project';
}

/**
 * The Code Packs page (≡ → Code Packs...): the design codes found on this computer, grouped
 * Built-in / Your Packs / This Project, each with its edition, what it extends, what it
 * provides and its problems; the selected pack's details (sources, tables, trust of its hooks)
 * in the properties panel. Makes a new pack's skeleton, installs a pack folder or zip, validates
 * a pack and asks before trusting a pack's hooks. Until the backend answers it shows the
 * built-in BNBC 2020 only, quietly.
 */
export class CodePacksEditor extends EditorPane {

	static readonly ID = CodePacksEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private list!: HTMLElement;
	private packs: ICodePackInfo[] = [];
	/** The backend answered the list (else the stand-in built-in pack is shown). */
	private available = false;
	private loaded = false;
	private selectedKey: string | undefined;
	/** Detail answers (`saengine.codes.show`) and validation results, by pack key. */
	private readonly details = new Map<string, ICodePackInfo>();
	private readonly validated = new Map<string, readonly string[]>();
	private loadVersion = 0;

	private readonly listDisposables = this._register(new DisposableStore());
	private readonly detailDisposables = this._register(new DisposableStore());
	private readonly loadScheduler = this._register(new RunOnceScheduler(() => void this.load(), 0));

	private readonly newAction = this._register(new Action('saengine.codePacks.newPack', localize('codePacks.new', "New Code Pack..."), ThemeIcon.asClassName(Codicon.add), true, () => this.newPack()));
	private readonly installAction = this._register(new Action('saengine.codePacks.installPack', localize('codePacks.install', "Install Code Pack..."), ThemeIcon.asClassName(Codicon.package), true, () => this.install()));
	private readonly validateAction = this._register(new Action('saengine.codePacks.validatePack', localize('codePacks.validate', "Validate"), ThemeIcon.asClassName(Codicon.checklist), true, () => this.validate()));
	private readonly refreshAction = this._register(new Action('saengine.codePacks.refresh', localize('codePacks.refresh', "Refresh"), ThemeIcon.asClassName(Codicon.refresh), true, () => this.load()));
	private readonly openManifestAction = this._register(new Action('saengine.codePacks.openManifest', localize('codePacks.openManifest', "Open pack.json"), undefined, true, () => this.openManifest()));

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
			ariaLabel: localize('codePacks.toolbar', "Code Packs"),
			properties: { title: localize('codePacks.details', "Details"), defaultWidth: 340 },
		}));
		this.frame.element.classList.add('saengine-code-packs-editor');
		this.frame.setTitle(localize('codePacks.title', "Code Packs"));
		this.frame.setHelp(localize('codePacks.help', "A code pack is a design code as data: locations and hazard tables, area loads, load combinations, seismic and wind coefficients, materials, resistance factors and detailing limits, each table with its clauses. A pack can extend another and override only the tables it provides. The design formulas stay in SAEngine; a pack replaces them only through hooks, which run only when you trust them. The project chooses its pack in 02 Project Settings."));
		this.frame.setActions([this.newAction, this.installAction, this.validateAction, this.refreshAction, this.frame.togglePropertiesAction], [this.openManifestAction]);
		this.list = $('.code-packs-list', { role: 'listbox', tabIndex: 0, 'aria-label': localize('codePacks.listLabel', "Installed code packs") });
		this.scrollable = this._register(new DomScrollableElement(this.list, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('code-packs-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this._register(addDisposableListener(this.list, EventType.KEY_DOWN, e => this.onKey(new StandardKeyboardEvent(e))));
	}

	override async setInput(input: CodePacksEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.render();
		await this.load();
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

	// ───────────────────────────── data ─────────────────────────────

	private get root(): URI | undefined {
		return this.projectService.project?.root;
	}

	private keyOf(pack: ICodePackInfo): string {
		return `${pack.scope}/${pack.id}`;
	}

	/** The packs in list order (as grouped on the page). */
	private get ordered(): ICodePackInfo[] {
		return groupPacks(this.packs, !!this.root).flatMap(g => g.packs);
	}

	private get selected(): ICodePackInfo | undefined {
		const pack = this.ordered.find(p => this.keyOf(p) === this.selectedKey);
		return pack ? this.details.get(this.keyOf(pack)) ?? pack : undefined;
	}

	/** Asks the backend for the packs; without it, the built-in BNBC 2020 stands alone. */
	async load(): Promise<void> {
		const version = ++this.loadVersion;
		let packs: ICodePackInfo[] | undefined;
		if (CommandsRegistry.getCommand(CODES_LIST_COMMAND)) {
			try {
				packs = readCodePacks(await this.commandService.executeCommand<unknown>(CODES_LIST_COMMAND, { root: this.root?.fsPath }));
			} catch (error) {
				packs = undefined;
				this.notificationService.warn(localize('codePacks.listFailed', "Could not list the code packs: {0}", toErrorMessage(error)));
			}
		}
		if (version !== this.loadVersion) {
			return;
		}
		this.available = packs !== undefined;
		this.packs = packs ?? [builtinDefaultPack()];
		this.loaded = true;
		this.details.clear();
		if (!this.ordered.some(p => this.keyOf(p) === this.selectedKey)) {
			const first = this.ordered.find(p => p.id === DEFAULT_CODE_PACK) ?? this.ordered[0];
			this.selectedKey = first ? this.keyOf(first) : undefined;
		}
		this.render();
		void this.loadDetails();
	}

	/** The selected pack in detail (sources, tables, trust), when the backend offers it. */
	private async loadDetails(): Promise<void> {
		const pack = this.ordered.find(p => this.keyOf(p) === this.selectedKey);
		// A shadowed pack is shown from the list alone: the backend's show describes the pack in force.
		if (!pack || !pack.effective || !this.available || this.details.has(this.keyOf(pack)) || !CommandsRegistry.getCommand(CODES_SHOW_COMMAND)) {
			return;
		}
		const key = this.keyOf(pack);
		try {
			const shown = readCodePack(await this.commandService.executeCommand<unknown>(CODES_SHOW_COMMAND, { id: pack.id, root: this.root?.fsPath }));
			if (shown) {
				// The list knows where the pack is installed; the details add the rest.
				this.details.set(key, { ...shown, scope: pack.scope, path: shown.path ?? pack.path, problems: shown.problems.length ? shown.problems : pack.problems, usable: shown.usable && pack.usable, effective: pack.effective, shadowedBy: pack.shadowedBy, trust: shown.trust !== 'none' ? shown.trust : pack.trust, hooksFrom: shown.hooksFrom.length ? shown.hooksFrom : pack.hooksFrom });
			}
		} catch {
			// The list's own fields are shown.
		}
		if (this.selectedKey === key) {
			this.renderDetails();
		}
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
			const items: (IQuickPickItem & { id: string })[] = this.packs.map(p => ({ id: p.id, label: p.name, description: scopeLabel(p.scope), detail: p.edition || undefined }));
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
			await this.load();
			this.selectedKey = `${scope}/${id.trim()}`;
			this.render();
			const folder = typeof path === 'string' ? path : dest ? joinPath(URI.file(dest), id.trim()).fsPath : undefined;
			if (folder) {
				await this.openFile(folder.endsWith('pack.json') ? URI.file(folder) : joinPath(URI.file(folder), 'pack.json'));
			}
		} catch (error) {
			this.notificationService.error(localize('codePacks.newFailed', "Could not make the code pack: {0}", toErrorMessage(error)));
		}
	}

	/** Installs a pack folder or .zip into the user's packs or the project. */
	async install(args: IInstallCodePackArgs = {}): Promise<void> {
		if (!this.ensureBackend(CODES_INSTALL_COMMAND)) {
			return;
		}
		let path = args.path;
		if (!path) {
			const picked = await this.fileDialogService.showOpenDialog({
				title: localize('codePacks.installTitle', "Install Code Pack"),
				openLabel: localize('codePacks.installOpen', "&&Install"),
				canSelectFiles: true,
				canSelectFolders: true,
				canSelectMany: false,
				filters: [{ name: localize('codePacks.zipFilter', "Code pack (.zip)"), extensions: ['zip'] }],
			});
			path = picked?.[0]?.fsPath;
		}
		if (!path) {
			return;
		}
		const scope = args.scope ?? await this.pickScope(localize('codePacks.installWhereTitle', "Install Code Pack In"));
		if (!scope) {
			return;
		}
		try {
			const result = await this.commandService.executeCommand<unknown>(CODES_INSTALL_COMMAND, { path, scope, root: this.root?.fsPath });
			const installed = readCodePack(result);
			await this.load();
			if (installed) {
				this.selectedKey = `${scope}/${installed.id}`;
				this.render();
				void this.loadDetails();
			}
			this.notificationService.info(installed
				? localize('codePacks.installed', "Installed the code pack {0}.", installed.name)
				: localize('codePacks.installedUnnamed', "Installed the code pack."));
		} catch (error) {
			this.notificationService.error(localize('codePacks.installFailed', "Could not install the code pack: {0}", toErrorMessage(error)));
		}
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
			await this.commandService.executeCommand(CODES_TRUST_COMMAND, { id: pack.id, trusted, root: this.root?.fsPath });
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

	private select(pack: ICodePackInfo, focus = true): void {
		this.selectedKey = this.keyOf(pack);
		this.render();
		if (focus) {
			this.list.focus();
		}
		void this.loadDetails();
	}

	private onKey(e: StandardKeyboardEvent): void {
		const packs = this.ordered;
		const index = packs.findIndex(p => this.keyOf(p) === this.selectedKey);
		const next = e.keyCode === KeyCode.DownArrow ? packs[Math.min(index + 1, packs.length - 1)] : e.keyCode === KeyCode.UpArrow ? packs[Math.max(index - 1, 0)]
			: e.keyCode === KeyCode.Home ? packs[0] : e.keyCode === KeyCode.End ? packs[packs.length - 1] : undefined;
		if (next) {
			e.preventDefault();
			this.select(next);
		} else if (e.keyCode === KeyCode.Enter && this.selected?.path) {
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
		this.renderList();
		this.renderDetails();
		this.renderStatus();
		const selected = this.selected;
		const backend = this.available;
		this.newAction.enabled = backend;
		this.installAction.enabled = backend;
		this.validateAction.enabled = backend && !!selected?.path;
		this.openManifestAction.enabled = !!selected?.path;
	}

	private renderList(): void {
		this.listDisposables.clear();
		clearNode(this.list);
		if (!this.loaded) {
			return;
		}
		for (const group of groupPacks(this.packs, !!this.root)) {
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
		const selected = this.selected;
		if (selected) {
			this.list.setAttribute('aria-activedescendant', this.rowId(selected));
		} else {
			this.list.removeAttribute('aria-activedescendant');
		}
		this.scrollable.scanDomNode();
	}

	private rowId(pack: ICodePackInfo): string {
		return `code-pack-${pack.scope}-${pack.id.replace(/[^a-z0-9_-]/gi, '_')}`;
	}

	private renderRow(container: HTMLElement, pack: ICodePackInfo): void {
		const selected = this.keyOf(pack) === this.selectedKey;
		const problems = this.problemsOf(pack);
		const row = append(container, $('.code-packs-row', { role: 'option', id: this.rowId(pack), 'aria-selected': String(selected) }));
		row.classList.toggle('selected', selected);
		row.classList.toggle('shadowed', !pack.effective);
		append(row, $(`span.code-packs-icon${ThemeIcon.asCSSSelector(Codicon.law)}`));
		const body = append(row, $('.code-packs-text'));
		const head = append(body, $('.code-packs-head'));
		append(head, $('span.code-packs-name', undefined, pack.name));
		if (pack.id === DEFAULT_CODE_PACK && pack.scope === 'builtin') {
			append(head, $('span.code-packs-badge', undefined, localize('codePacks.default', "default")));
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
		this.listDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.select(pack)));
		this.listDisposables.add(addDisposableListener(row, EventType.DBLCLICK, () => void this.openManifest()));
	}

	private renderDetails(): void {
		const panel = this.frame.properties;
		if (!panel) {
			return;
		}
		this.detailDisposables.clear();
		clearNode(panel);
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
		row(localize('codePacks.edition', "Edition"), pack.edition);
		row(localize('codePacks.region', "Region"), pack.region);
		row(localize('codePacks.versionLabel', "Version"), pack.version);
		row(localize('codePacks.where', "Installed"), scopeLabel(pack.scope));
		const shadowed = shadowedLabel(pack);
		if (shadowed) {
			appendPropertyNote(panel, shadowed);
		}
		if (!pack.usable) {
			appendPropertyNote(panel, localize('codePacks.unusableNote', "This pack, or a pack it extends, has errors: it cannot be chosen as a project's design code until they are fixed."));
		}
		row(localize('codePacks.extendsLabel', "Extends"), pack.extends ? (this.packs.find(p => p.id === pack.extends)?.name ?? pack.extends) : localize('codePacks.extendsNone', "nothing (a complete code)"));
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
			const button = this.detailDisposables.add(new Button(append(panel, $('.code-packs-trust-button')), { ...defaultButtonStyles, secondary: true }));
			button.label = pack.trust === 'trusted' ? localize('codePacks.untrust', "Stop Trusting Hooks") : localize('codePacks.trust', "Trust This Pack's Hooks...");
			this.detailDisposables.add(button.onDidClick(() => void this.setTrust(pack, pack.trust !== 'trusted')));
		}
	}

	private renderStatus(): void {
		if (!this.loaded) {
			this.frame.setStatus({ text: localize('codePacks.loading', "Looking for code packs..."), busy: true });
			return;
		}
		if (!this.available) {
			this.frame.setStatus({ text: localize('codePacks.standIn', "Code packs are not available yet in this build: the built-in {0} is used for every project.", builtinDefaultPack().name) });
			return;
		}
		const count = (scope: CodePackScope) => this.packs.filter(p => p.scope === scope).length;
		const problems = this.packs.reduce((sum, p) => sum + this.problemsOf(p).length, 0);
		const text = localize('codePacks.status', "{0} built-in, {1} of yours, {2} in this project.", count('builtin'), count('user'), count('project'));
		this.frame.setStatus(problems
			? { severity: 'warning', text: problems === 1 ? localize('codePacks.statusOneProblem', "{0} 1 problem.", text) : localize('codePacks.statusProblems', "{0} {1} problems.", text, problems) }
			: { text });
	}
}
