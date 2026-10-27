/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/versionsEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { StandardMouseEvent } from '../../../../base/browser/mouseEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore, IDisposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { isMacintosh, language } from '../../../../base/common/platform.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyNote, EditorFrame } from './editorFrame.js';
import { VersionsEditorInput } from './versionsEditorInput.js';
import { VersionsFlows } from './versionsFlows.js';
import {
	changeGroups, compareRange, compareTitle, issuedBadge, IVersionDiff, IVersionEntry, nextSelection, partLabel, partsSummary, pendingParts, unsavedSummary,
	versionDetail, versionName,
} from './versionsModel.js';
import { IProjectVersionsService } from './versionsService.js';

const CHANGE_ICONS = { added: Codicon.diffAdded, removed: Codicon.diffRemoved, changed: Codicon.diffModified } as const;

/**
 * The project's versions on the shared editor frame: the list (newest first, issues marked),
 * with the current files on top; the changes of the selection in the panel on the right (one
 * version against the current files, or two against each other), grouped by part. Save, restore
 * and issue run from the toolbar, the rows and their context menu.
 */
export class VersionsEditor extends EditorPane {

	static readonly ID = VersionsEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private list!: HTMLElement;
	private versions: IVersionEntry[] = [];
	private loaded = false;
	private loadError: string | undefined;
	private selected: string[] = [];
	private focused: string | undefined;
	private diff: IVersionDiff | undefined;
	private diffError: string | undefined;
	private diffLoading = false;
	private loadVersion = 0;
	private diffVersion = 0;
	private actionsKey: string | undefined;
	/** The rendered row of each version. */
	private readonly rows = new Map<string, HTMLElement>();
	private readonly flows: VersionsFlows;

	private readonly renderDisposables = this._register(new DisposableStore());
	private readonly panelDisposables = this._register(new DisposableStore());
	private readonly pill = this._register(new MutableDisposable<IDisposable>());
	private readonly inputDisposables = this._register(new DisposableStore());

	private readonly saveAction = this._register(new Action('saengine.versions.saveAction', localize('versions.saveAction', "Save Version..."), ThemeIcon.asClassName(Codicon.save), true, () => this.save()));
	private readonly compareCurrentAction = this._register(new Action('saengine.versions.compareCurrent', localize('versions.compareWithCurrent', "Compare with Current"), undefined, false, () => this.compareWithCurrent()));
	private readonly restoreAction = this._register(new Action('saengine.versions.restoreAction', localize('versions.restoreAction', "Restore..."), undefined, false, () => this.restoreSelected()));
	private readonly markAction = this._register(new Action('saengine.versions.markAction', localize('versions.markAction', "Mark as Issued..."), undefined, false, () => this.markSelected()));
	private readonly refreshAction = this._register(new Action('saengine.versions.refresh', localize('versions.refresh', "Refresh"), undefined, true, () => this.load()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IProjectVersionsService private readonly versionsService: IProjectVersionsService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
	) {
		super(VersionsEditor.ID, group, telemetryService, themeService, storageService);
		this.flows = instantiationService.createInstance(VersionsFlows);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: VersionsEditor.ID,
			ariaLabel: localize('versions.toolbar', "Versions"),
			properties: { title: localize('versions.changes', "Changes"), defaultWidth: 380, maxWidth: 720 },
		}));
		this.frame.element.classList.add('saengine-versions-editor');
		this.frame.setTitle(localize('versions.editorTitle', "Versions"));
		this.frame.setHelp(localize('versions.help', "The project's history. Save a version at each milestone (a design stage, a submission); mark the ones you hand over as issued. Select a version to see what changed since; Ctrl+click a second one to compare the two. Restore brings parts back as they were."));
		this.list = $('.versions-list', { role: 'listbox', 'aria-label': localize('versions.listAria', "Versions"), tabIndex: 0 });
		this.scrollable = this._register(new DomScrollableElement(this.list, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('versions-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this._register(addDisposableListener(this.list, EventType.KEY_DOWN, e => this.onKeyDown(new StandardKeyboardEvent(e))));
	}

	override async setInput(input: VersionsEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.inputDisposables.add(this.projectService.onDidChangeProject(() => {
			this.selected = [];
			void this.load();
		}));
		let lastHead = this.versionsService.status?.head?.id;
		let lastAvailable = this.versionsService.available;
		this.inputDisposables.add(this.versionsService.onDidChange(() => {
			const head = this.versionsService.status?.head?.id;
			const available = this.versionsService.available;
			if (head !== lastHead || available !== lastAvailable) {
				// A version was saved or restored elsewhere (or the backend came): the list changed.
				lastHead = head;
				lastAvailable = available;
				void this.load();
			} else {
				this.render();
				// The current files changed: their comparison too.
				if (this.selected.length === 1) {
					void this.loadDiff();
				}
			}
		}));
		await this.load();
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.renderDisposables.clear();
		this.panelDisposables.clear();
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

	private async load(): Promise<void> {
		const version = ++this.loadVersion;
		this.loadError = undefined;
		if (!this.projectService.project || !this.versionsService.available) {
			this.versions = [];
			this.loaded = true;
			this.render();
			return;
		}
		this.frame?.showProgress();
		try {
			const versions = await this.versionsService.list();
			if (version !== this.loadVersion) {
				return;
			}
			this.versions = versions;
		} catch (error) {
			if (version !== this.loadVersion) {
				return;
			}
			this.versions = [];
			this.loadError = toErrorMessage(error);
		} finally {
			if (version === this.loadVersion) {
				this.frame?.hideProgress();
			}
		}
		this.loaded = true;
		this.selected = this.selected.filter(id => this.versions.some(v => v.id === id));
		if (!this.selected.length && this.versions.length) {
			this.selected = [this.versions[0].id];
		}
		this.focused ??= this.selected[0];
		this.render();
		void this.loadDiff();
	}

	private async loadDiff(): Promise<void> {
		const version = ++this.diffVersion;
		const range = compareRange(this.versions, this.selected);
		this.diffError = undefined;
		if (!range) {
			this.diff = undefined;
			this.diffLoading = false;
			this.renderPanel();
			return;
		}
		this.diffLoading = true;
		this.renderPanel();
		let diff: IVersionDiff | undefined;
		try {
			diff = await this.versionsService.diff(range.from.id, range.to?.id);
		} catch (error) {
			this.diffError = toErrorMessage(error);
		}
		if (version !== this.diffVersion) {
			return;
		}
		this.diff = diff;
		this.diffLoading = false;
		this.renderPanel();
	}

	private select(id: string, additive: boolean): void {
		this.selected = nextSelection(this.selected, id, additive);
		this.focused = id;
		this.render();
		void this.loadDiff();
	}

	private versionById(id: string | undefined): IVersionEntry | undefined {
		return id ? this.versions.find(v => v.id === id) : undefined;
	}

	/** The version the single-version actions (restore, issue) act on: the focused selected one. */
	private get target(): IVersionEntry | undefined {
		return this.versionById(this.selected.includes(this.focused ?? '') ? this.focused : this.selected[0]);
	}

	// ───────────────────────────── actions ─────────────────────────────

	private async save(): Promise<void> {
		const version = await this.flows.save();
		if (version) {
			this.selected = [version.id];
			this.focused = version.id;
		}
		await this.load();
	}

	private compareWithCurrent(version = this.target): void {
		if (version) {
			this.selected = [version.id];
			this.focused = version.id;
			this.frame.setPropertiesVisible(true);
			this.render();
			void this.loadDiff();
		}
	}

	private async restoreSelected(version = this.target): Promise<void> {
		if (version && await this.flows.restore(version)) {
			await this.load();
		}
	}

	private async markSelected(version = this.target): Promise<void> {
		if (version && await this.flows.markIssued(version)) {
			await this.load();
		}
	}

	private onKeyDown(e: StandardKeyboardEvent): void {
		if (!this.versions.length) {
			return;
		}
		const index = Math.max(0, this.versions.findIndex(v => v.id === this.focused));
		let next: number | undefined;
		if (e.keyCode === KeyCode.DownArrow) {
			next = Math.min(this.versions.length - 1, index + 1);
		} else if (e.keyCode === KeyCode.UpArrow) {
			next = Math.max(0, index - 1);
		} else if (e.keyCode === KeyCode.Home) {
			next = 0;
		} else if (e.keyCode === KeyCode.End) {
			next = this.versions.length - 1;
		} else if (e.keyCode === KeyCode.Space && this.focused) {
			e.preventDefault();
			this.select(this.focused, true);
			return;
		}
		if (next !== undefined) {
			e.preventDefault();
			this.select(this.versions[next].id, e.shiftKey);
			this.rows.get(this.versions[next].id)?.scrollIntoView({ block: 'nearest' });
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		if (!this.input || !this.frame) {
			return;
		}
		this.renderDisposables.clear();
		clearNode(this.list);
		this.rows.clear();
		const project = this.projectService.project;
		const available = this.versionsService.available;
		this.updateActions(!!project && available);
		this.updatePill(!!project && available);
		if (!project) {
			this.frame.setEmpty({ icon: Codicon.history, title: localize('versions.noProject', "No project is open") });
			this.frame.setStatus(undefined);
			this.renderPanel();
			return;
		}
		if (!available) {
			this.frame.setEmpty({
				icon: Codicon.history,
				title: localize('versions.notAvailableTitle', "Versions are not available yet"),
				text: localize('versions.notAvailableText', "This build of SAEngine has no versions backend. When it has, save a version at each milestone, compare versions part by part and restore earlier ones here."),
			});
			this.frame.setStatus(undefined);
			this.renderPanel();
			return;
		}
		if (!this.loaded) {
			this.frame.setEmpty(undefined);
			this.frame.setStatus({ busy: true, text: localize('versions.loading', "Reading the versions...") });
			return;
		}
		if (this.loadError) {
			this.frame.setEmpty({
				icon: Codicon.warning,
				title: localize('versions.loadFailed', "The versions could not be read"),
				text: this.loadError,
				actions: [{ label: localize('versions.tryAgain', "Try Again"), run: () => void this.load() }],
			});
			this.frame.setStatus(undefined);
			this.renderPanel();
			return;
		}
		const summary = unsavedSummary(this.versionsService.status, this.versionsService.editedParts);
		if (!this.versions.length && summary?.problem) {
			// Not kept here (a project inside another git repository), or the status failed: say why.
			this.frame.setEmpty({
				icon: Codicon.warning,
				title: summary.text,
				text: summary.problem,
				actions: [{ label: localize('versions.tryAgain', "Try Again"), run: () => { void this.versionsService.refresh(); void this.load(); } }],
			});
			this.frame.setStatus(undefined);
			this.renderPanel();
			return;
		}
		if (!this.versions.length) {
			this.frame.setEmpty({
				icon: Codicon.history,
				title: localize('versions.emptyTitle', "No versions yet"),
				text: localize('versions.emptyText', "Save a version to start the project's history. Each version keeps every part as it is now, so you can compare and come back to it."),
				actions: [{ label: localize('versions.saveFirst', "Save Version..."), icon: Codicon.save, primary: true, run: () => void this.save() }],
			});
			this.frame.setStatus(undefined);
			this.renderPanel();
			return;
		}
		this.frame.setEmpty(undefined);
		this.renderCurrent();
		const now = Date.now();
		const head = this.versionsService.status?.head?.id ?? this.versions[0]?.id;
		for (const version of this.versions) {
			this.renderVersion(version, version.id === head, now);
		}
		const issued = this.versions.filter(v => v.issued).length;
		this.frame.setStatus({
			text: issued
				? localize('versions.countIssued', "{0} versions, {1} issued.", this.versions.length, issued)
				: this.versions.length === 1 ? localize('versions.countOne', "1 version.") : localize('versions.count', "{0} versions.", this.versions.length),
		});
		this.scrollable.scanDomNode();
		this.renderPanel();
	}

	private updateActions(enabled: boolean): void {
		const target = enabled ? this.target : undefined;
		this.saveAction.enabled = enabled;
		this.compareCurrentAction.enabled = !!target;
		this.restoreAction.enabled = !!target;
		this.markAction.enabled = !!target;
		this.markAction.label = target?.issued ? localize('versions.addLabel', "Add Issue Label...") : localize('versions.markAction', "Mark as Issued...");
		const key = String(enabled);
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			this.frame.setActions([this.saveAction, this.frame.togglePropertiesAction], [this.compareCurrentAction, this.restoreAction, this.markAction, new Separator(), this.refreshAction]);
		}
	}

	private updatePill(enabled: boolean): void {
		const summary = enabled ? unsavedSummary(this.versionsService.status, this.versionsService.editedParts) : undefined;
		this.pill.value = summary ? this.frame.createPill(summary.text, {
			severity: summary.dirty || summary.problem ? 'warn' : undefined,
			icon: summary.problem ? Codicon.warning : summary.dirty ? Codicon.circleFilled : Codicon.check,
			title: summary.problem ?? (summary.dirty ? localize('versions.pillSave', "Save the current files as a version") : undefined),
			run: summary.dirty ? () => void this.save() : undefined,
		}) : undefined;
	}

	/** The row of the current files: what changed since the latest version, and Save. */
	private renderCurrent(): void {
		const status = this.versionsService.status;
		const edited = this.versionsService.editedParts;
		const pending = pendingParts(status, edited);
		const summary = unsavedSummary(status, edited);
		const row = append(this.list, $('.versions-current'));
		row.classList.toggle('dirty', !!summary?.dirty);
		row.classList.toggle('problem', !!summary?.problem);
		append(row, $(`span.versions-current-icon${ThemeIcon.asCSSSelector(summary?.problem ? Codicon.warning : summary?.dirty ? Codicon.circleFilled : Codicon.check)}`));
		const text = append(row, $('.versions-text'));
		append(text, $('.versions-message', undefined, localize('versions.currentFiles', "Current files")));
		append(text, $('.versions-detail', undefined, summary?.dirty && pending.length
			? localize('versions.currentDetail', "{0}: {1}", summary.text, partsSummary(pending, 5))
			: summary?.text ?? ''));
		if (edited.length && status?.initialized) {
			// Edits still open in an editor: the backend sees the files on disk, so say they are saved first.
			append(text, $('.versions-detail', undefined, localize('versions.editedDetail', "Edits not saved yet in {0}: Save Version saves them first.", partsSummary(edited, 5))));
		}
		if (summary?.problem) {
			// The backend's own words: a project inside another git repository, a failed status.
			append(text, $('.versions-detail.versions-problem', { role: 'alert' }, summary.problem));
		}
		if (summary?.dirty) {
			const button = this.renderDisposables.add(new Button(append(row, $('.versions-actions')), { ...defaultButtonStyles, supportIcons: true }));
			button.label = localize('versions.saveButton', "Save Version...");
			this.renderDisposables.add(button.onDidClick(() => void this.save()));
		}
	}

	private renderVersion(version: IVersionEntry, latest: boolean, now: number): void {
		const selected = this.selected.includes(version.id);
		const row = append(this.list, $('.versions-row', { role: 'option', 'aria-selected': String(selected), 'data-version': version.id }));
		this.rows.set(version.id, row);
		row.classList.toggle('selected', selected);
		row.classList.toggle('focused', this.focused === version.id);
		row.classList.toggle('issued', version.issued);
		append(row, $('span.versions-name', undefined, versionName(version)));
		const text = append(row, $('.versions-text'));
		const title = append(text, $('.versions-title'));
		append(title, $('span.versions-message', undefined, version.message || localize('versions.noMessage', "(no message)")));
		const badge = issuedBadge(version);
		if (badge) {
			const pill = append(title, $('span.versions-badge.issued'));
			append(pill, $(ThemeIcon.asCSSSelector(Codicon.verified)));
			append(pill, $('span', undefined, badge));
		}
		if (latest) {
			append(title, $('span.versions-badge', undefined, localize('versions.latest', "Latest")));
		}
		append(text, $('.versions-detail', undefined, versionDetail(version, now)));
		if (version.time !== undefined) {
			row.title = new Date(version.time).toLocaleString(language);
		}
		const actions = append(row, $('.versions-actions'));
		this.renderDisposables.add(this.frame.createIconButton(actions, Codicon.diff, localize('versions.compareWithCurrent', "Compare with Current"), () => this.compareWithCurrent(version)));
		this.renderDisposables.add(this.frame.createIconButton(actions, Codicon.discard, localize('versions.restoreAction', "Restore..."), () => void this.restoreSelected(version)));
		this.renderDisposables.add(addDisposableListener(row, EventType.CLICK, (e: MouseEvent) => {
			if ((e.target as HTMLElement).closest('.versions-actions')) {
				return;
			}
			this.select(version.id, isMacintosh ? e.metaKey : e.ctrlKey || e.shiftKey);
			this.list.focus();
		}));
		this.renderDisposables.add(addDisposableListener(row, EventType.CONTEXT_MENU, (e: MouseEvent) => {
			e.preventDefault();
			if (!this.selected.includes(version.id)) {
				this.select(version.id, false);
			}
			this.showContextMenu(version, e);
		}));
	}

	private showContextMenu(version: IVersionEntry, e: MouseEvent): void {
		const range = compareRange(this.versions, this.selected);
		const actions: IAction[] = [
			new Action('saengine.versions.ctx.compare', localize('versions.compareWithCurrent', "Compare with Current"), undefined, true, () => this.compareWithCurrent(version)),
		];
		if (range?.to) {
			actions.push(new Action('saengine.versions.ctx.compareSelected', localize('versions.compareSelected', "Compare {0}", compareTitle(range.from, range.to)), undefined, true, () => {
				this.frame.setPropertiesVisible(true);
				void this.loadDiff();
			}));
		}
		actions.push(
			new Separator(),
			new Action('saengine.versions.ctx.restore', localize('versions.restoreAction', "Restore..."), undefined, true, () => this.restoreSelected(version)),
			new Action('saengine.versions.ctx.mark', version.issued ? localize('versions.addLabel', "Add Issue Label...") : localize('versions.markAction', "Mark as Issued..."), undefined, true, () => this.markSelected(version)),
		);
		const event = new StandardMouseEvent(getWindow(this.list), e);
		this.contextMenuService.showContextMenu({ getAnchor: () => event, getActions: () => actions });
	}

	/** The changes of the selection, grouped by part. */
	private renderPanel(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		this.panelDisposables.clear();
		clearNode(panel);
		const range = this.versionsService.available ? compareRange(this.versions, this.selected) : undefined;
		if (!range) {
			appendPropertyNote(panel, this.versions.length
				? localize('versions.selectHint', "Select a version to see what changed since. Ctrl+click a second version to compare the two.")
				: localize('versions.noneHint', "The changes between versions show here."));
			return;
		}
		const header = append(panel, $('.versions-compare-header'));
		append(header, $('.versions-compare-title', undefined, compareTitle(range.from, range.to)));
		append(header, $('.versions-compare-detail', undefined, range.to
			? localize('versions.compareTwoDetail', "What changed from {0} to {1}.", versionName(range.from), versionName(range.to))
			: localize('versions.compareCurrentDetail', "What changed in the current files since {0}.", versionName(range.from))));
		if (this.diffLoading) {
			append(panel, $(`.versions-compare-loading`, undefined, localize('versions.comparing', "Comparing...")));
			return;
		}
		if (this.diffError) {
			append(panel, $('.versions-compare-error', undefined, localize('versions.compareFailed', "The versions could not be compared: {0}", this.diffError)));
			return;
		}
		const groups = this.diff ? changeGroups(this.diff) : [];
		// Edits still in an editor: the backend compares the files on disk, so they are listed here.
		const unsaved = range.to ? [] : this.versionsService.editedParts;
		if (unsaved.length) {
			const section = append(panel, $('section.versions-group'));
			const heading = append(section, $('.versions-group-heading'));
			append(heading, $('span.versions-group-title', undefined, localize('versions.unsavedEdits', "Unsaved edits")));
			append(heading, $('span.versions-group-count', undefined, String(unsaved.length)));
			const list = append(section, $('ul.versions-changes'));
			for (const part of unsaved) {
				const item = append(list, $('li.versions-change.changed'));
				append(item, $(`span.versions-change-icon${ThemeIcon.asCSSSelector(Codicon.circleFilled)}`, { 'aria-label': 'unsaved' }));
				const body = append(item, $('.versions-change-body'));
				append(body, $('span.versions-change-text', undefined, partLabel(part)));
				append(body, $('span.versions-change-values', undefined, localize('versions.unsavedDetail', "edited, not saved to disk yet: save (Ctrl+S) to see what changed")));
			}
		}
		if (!groups.length && !unsaved.length) {
			appendPropertyNote(panel, range.to
				? localize('versions.noDifferenceTwo', "No differences between {0} and {1}.", versionName(range.from), versionName(range.to))
				: localize('versions.noDifference', "The current files are the same as {0}.", versionName(range.from)));
		}
		for (const group of groups) {
			const section = append(panel, $('section.versions-group'));
			const heading = append(section, $('.versions-group-heading'));
			append(heading, $('span.versions-group-title', undefined, group.title));
			append(heading, $('span.versions-group-count', undefined, group.count));
			const list = append(section, $('ul.versions-changes'));
			for (const line of group.lines) {
				const item = append(list, $(`li.versions-change.${line.kind}`));
				append(item, $(`span.versions-change-icon${ThemeIcon.asCSSSelector(CHANGE_ICONS[line.kind])}`, { 'aria-label': line.kind }));
				const body = append(item, $('.versions-change-body'));
				append(body, $('span.versions-change-text', undefined, line.text));
				if (line.values) {
					append(body, $('span.versions-change-values', undefined, line.values));
				}
			}
			if (group.more) {
				appendPropertyNote(section, localize('versions.moreChanges', "and {0} more", group.more));
			}
		}
		for (const problem of this.diff?.problems ?? []) {
			appendPropertyNote(panel, problem);
		}
		if (!range.to && groups.length) {
			const actions = append(panel, $('.versions-compare-actions'));
			const restore = this.panelDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true }));
			restore.label = localize('versions.restoreVersion', "Restore {0}...", versionName(range.from));
			this.panelDisposables.add(restore.onDidClick(() => void this.restoreSelected(range.from)));
		}
	}
}
