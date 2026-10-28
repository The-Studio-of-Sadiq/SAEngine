/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/boqEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { StandardMouseEvent } from '../../../../base/browser/mouseEvent.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { BOQ_COMPUTE_COMMAND, BOQ_GROUPS, BOQ_SOURCES, BoqGroup, boqComputeArgs, boqProblems, changedSources, displayQuantity, formatQuantity, totalledItems, IBoqComputeResult, IBoqDocument, IBoqItem, parseBoq, quantityText, totalRows, totals, unitLabel } from './boqDocument.js';
import { BoqEditorInput } from './boqEditorInput.js';
import { exportBoqCsv } from './boqExport.js';

/** Short group names for the status line's totals. */
function shortGroupName(group: BoqGroup): string {
	switch (group) {
		case 'earthwork': return localize('boq.short.earthwork', "Earthwork");
		case 'concrete': return localize('boq.short.concrete', "Concrete");
		case 'masonry': return localize('boq.short.masonry', "Masonry");
		case 'reinforcement': return localize('boq.short.reinforcement', "Reinforcement");
		case 'formwork': return localize('boq.short.formwork', "Formwork");
		case 'steel': return localize('boq.short.steel', "Steel");
		case 'mep': return localize('boq.short.mep', "MEP");
		case 'materials': return localize('boq.short.materials', "Cement");
	}
}

/** Where the viewer's choice of units (metric or feet) is kept. */
const IMPERIAL_STORAGE_KEY = 'saengine.boq.imperial';

function groupTitle(group: BoqGroup): string {
	return BOQ_GROUPS.find(g => g.group === group)?.title ?? group;
}

/**
 * The bill of quantities (`10 BOQ/boq.json`) on the shared editor frame: concrete, reinforcement
 * by bar diameter, formwork and structural steel measured from the building model, in compact
 * tables with their totals. A row expands to its breakdown by element, and its details show in
 * the properties panel. The toolbar offers "Update from Building Model" when the building model,
 * the object types or the materials changed since the bill was measured ("Out of date"); the
 * status line has the totals.
 */
export class BoqEditor extends EditorPane {

	static readonly ID = BoqEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private body!: HTMLElement;
	private model: ITextModel | undefined;
	private readonly sources = new Map<string, ITextModel>();
	/** Codes of the items whose breakdown is shown. */
	private readonly expanded = new Set<string>();
	/** The item rows of the bill as rendered, in order, by code. */
	private readonly rows = new Map<string, HTMLElement>();
	/** Code of the item whose details the properties panel shows. */
	private selected: string | undefined;
	private computing = false;
	private sourcesVersion = 0;
	private actionsKey: string | undefined;
	private pillKey: string | undefined;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly sourceDisposables = this._register(new DisposableStore());
	private readonly bodyDisposables = this._register(new DisposableStore());
	private readonly pill = this._register(new MutableDisposable());

	private readonly updateAction = this._register(new Action('saengine.boq.editor.update', localize('boq.update', "Update from Building Model"), ThemeIcon.asClassName(Codicon.refresh), true, () => this.compute()));
	private readonly updateAgainAction = this._register(new Action('saengine.boq.editor.updateAgain', localize('boq.update', "Update from Building Model"), undefined, true, () => this.compute()));
	private readonly exportAction = this._register(new Action('saengine.boq.editor.export', localize('boq.exportCsv', "Export CSV..."), ThemeIcon.asClassName(Codicon.export), true, () => this.exportCsv()));
	private readonly expandAllAction = this._register(new Action('saengine.boq.editor.expandAll', localize('boq.expandAll', "Expand All"), undefined, true, async () => this.setAllExpanded(true)));
	private readonly collapseAllAction = this._register(new Action('saengine.boq.editor.collapseAll', localize('boq.collapseAll', "Collapse All"), undefined, true, async () => this.setAllExpanded(false)));
	private readonly openJsonAction = this._register(new Action('saengine.boq.editor.openJson', localize('boq.openJson', "Open as JSON"), undefined, true, () => this.openAsJson()));
	private readonly imperialAction = this._register(new Action('saengine.boq.editor.imperial', localize('boq.imperial', "Show in Feet (cft, sft, rft)"), undefined, true, async () => this.setImperial(!this.imperial)));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService private readonly storage: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@INotificationService private readonly notificationService: INotificationService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(BoqEditor.ID, group, telemetryService, themeService, storage);
		// Editors restore before the project is detected: find the source files once it is.
		this._register(this.projectService.onDidChangeProject(async () => {
			if (this.input) {
				await this.trackSources();
				this.renderChrome();
			}
		}));
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.renderChrome();
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: BoqEditor.ID,
			ariaLabel: localize('boq.toolbar', "Bill of Quantities"),
			properties: { title: localize('boq.properties', "Properties"), defaultWidth: 260 },
		}));
		this.frame.element.classList.add('saengine-boq-editor');
		this.frame.setTitle(localize('boq.title', "Bill of Quantities"));
		this.frame.setHelp(localize('boq.help', "Concrete, reinforcement by bar diameter, formwork and structural steel, measured from the building model, the object types and the materials. Click a row for its breakdown by element; its details show in the properties panel."));
		this.body = $('.boq-body', { tabIndex: -1 });
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('boq-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
	}

	override async setInput(input: BoqEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.expanded.clear();
		this.selected = undefined;
		this.model = undefined;
		const reference = await input.resolve();
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
		this.model = reference.object.textEditorModel;
		this.inputDisposables.add(this.model.onDidChangeContent(() => this.render()));
		await this.trackSources();
		if (this.input === input) {
			this.render();
		}
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.sourceDisposables.clear();
		this.sources.clear();
		this.model = undefined;
		this.sourcesVersion++;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		const row = this.selected ? this.rowOf(this.selected) : undefined;
		(row ?? this.body).focus();
	}

	private get document(): IBoqDocument | undefined {
		return this.model && !this.model.isDisposed() ? parseBoq(this.model.getValue()) : undefined;
	}

	/** Whether volumes, areas and lengths show in feet (cft, sft, rft): the viewer's choice, kept. */
	private get imperial(): boolean {
		return this.storage.getBoolean(IMPERIAL_STORAGE_KEY, StorageScope.PROFILE, false);
	}

	private setImperial(imperial: boolean): void {
		this.storage.store(IMPERIAL_STORAGE_KEY, imperial, StorageScope.PROFILE, StorageTarget.USER);
		this.render();
	}

	private get developerMode(): boolean {
		return this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
	}

	/** Follows the files the bill is measured from (unsaved edits included). */
	private async trackSources(): Promise<void> {
		const version = ++this.sourcesVersion;
		this.sourceDisposables.clear();
		this.sources.clear();
		const root = this.projectService.project?.root;
		if (!root) {
			return;
		}
		for (const { part } of BOQ_SOURCES) {
			const file = partById(part);
			if (!file?.mainFile) {
				continue;
			}
			try {
				const reference = await this.textModelService.createModelReference(joinPath(root, file.folder, file.mainFile));
				if (version !== this.sourcesVersion) {
					reference.dispose();
					return;
				}
				this.sourceDisposables.add(reference);
				const model = reference.object.textEditorModel;
				this.sources.set(part, model);
				this.sourceDisposables.add(model.onDidChangeContent(() => this.renderChrome()));
			} catch {
				// A missing source file shows as changed until it is restored.
			}
		}
	}

	/** Labels of the sources changed since the bill was measured. */
	private changedLabels(document: IBoqDocument | undefined): string[] {
		const texts = new Map(BOQ_SOURCES.map(({ part }) => [part, this.sources.get(part)?.getValue()]));
		const changed = changedSources(document, texts);
		return BOQ_SOURCES.filter(s => changed.includes(s.part)).map(s => s.label);
	}

	private render(): void {
		this.renderBody();
		this.renderChrome();
	}

	// ───────────────────────────── chrome ─────────────────────────────

	/** The toolbar, the pill, the status line, the empty state and the properties panel. */
	private renderChrome(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const document = this.model ? this.document : undefined;
		const changed = document ? this.changedLabels(document) : [];
		const stale = !!this.model && (!document || changed.length > 0);

		this.updateAction.label = document ? localize('boq.update', "Update from Building Model") : localize('boq.measure', "Measure from Building Model");
		this.updateAction.enabled = this.updateAgainAction.enabled = !this.computing && !!this.model;
		this.exportAction.enabled = !!document;
		const hasItems = !!document?.items.length;
		this.expandAllAction.enabled = this.collapseAllAction.enabled = hasItems;

		this.imperialAction.checked = this.imperial;
		const primary: IAction[] = [...(stale ? [this.updateAction] : []), this.exportAction, frame.togglePropertiesAction];
		const secondary: IAction[] = [
			...(stale ? [] : [this.updateAgainAction]),
			new Separator(),
			this.imperialAction,
			new Separator(),
			this.expandAllAction,
			this.collapseAllAction,
			...(this.developerMode ? [new Separator(), this.openJsonAction] : []),
		];
		const key = `${primary.map(a => a.id).join()}|${secondary.map(a => a.id).join()}`;
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			frame.setActions(primary, secondary);
		}

		// "Out of date": what changed since the bill was measured; built again only when that changes.
		const pillKey = document && changed.length ? changed.join(', ') : undefined;
		if (pillKey !== this.pillKey) {
			this.pillKey = pillKey;
			this.pill.value = pillKey === undefined ? undefined : frame.createPill(localize('boq.outOfDate', "Out of date"), {
				severity: 'warn',
				icon: Codicon.warning,
				title: localize('boq.outOfDateTitle', "Changed since the bill was measured: {0}. Click to measure it again.", pillKey),
				run: () => void this.compute(),
			});
		}

		if (this.computing) {
			frame.showProgress();
		} else {
			frame.hideProgress();
		}
		frame.setStatus(this.status(document, changed));
		this.renderEmpty(document);
		this.renderProperties(document, changed);
	}

	private status(document: IBoqDocument | undefined, changed: readonly string[]): IEditorFrameStatus | undefined {
		if (!this.model) {
			return undefined;
		}
		if (this.computing) {
			return { busy: true, text: localize('boq.measuring', "Measuring the bill from the building model...") };
		}
		if (!document) {
			return {
				text: localize('boq.notMeasured', "Not measured from the building model yet."),
				link: { label: localize('boq.measure', "Measure from Building Model"), run: () => void this.compute() },
			};
		}
		if (changed.length) {
			return {
				severity: 'warning',
				text: localize('boq.changed', "Changed since the bill was measured: {0}.", changed.join(', ')),
				link: { label: localize('boq.updateLink', "Update"), run: () => void this.compute() },
			};
		}
		const problems = boqProblems(document);
		if (problems.length) {
			return {
				severity: 'warning',
				text: problems.length === 1
					? localize('boq.incompleteOne', "Incomplete: 1 problem. {0}", problems[0])
					: localize('boq.incomplete', "Incomplete: {0} problems, listed above the bill.", problems.length),
				link: { label: localize('boq.updateLink', "Update"), run: () => void this.compute() },
			};
		}
		const sums: string[] = [];
		for (const { group } of BOQ_GROUPS) {
			const items = document.items.filter(i => i.group === group);
			if (items.length) {
				const values = totals(totalledItems(group, items)).map(({ unit, total }) => quantityText(total, unit, this.imperial)).join(', ');
				sums.push(localize('boq.groupTotal', "{0} {1}", shortGroupName(group), values));
			}
		}
		return {
			icon: Codicon.check,
			text: sums.length
				? localize('boq.currentTotals', "Measured from the current building model. {0}", sums.join('  ·  '))
				: localize('boq.current', "Measured from the current building model."),
		};
	}

	private renderEmpty(document: IBoqDocument | undefined): void {
		if (!this.model) {
			this.frame.setEmpty(undefined);
			return;
		}
		if (!document) {
			this.frame.setEmpty({
				icon: Codicon.listOrdered,
				title: localize('boq.emptyTitle', "No bill of quantities yet"),
				text: localize('boq.emptyText', "The bill is measured from the building model, the object types and the materials."),
				actions: [{ label: localize('boq.measure', "Measure from Building Model"), icon: Codicon.refresh, primary: true, enabled: !this.computing, run: () => void this.compute() }],
			});
		} else if (!document.items.length) {
			this.frame.setEmpty({
				icon: Codicon.listOrdered,
				title: localize('boq.nothingTitle', "Nothing was measured"),
				text: localize('boq.nothing', "The building model has no elements of known object types."),
				actions: [{ label: localize('boq.update', "Update from Building Model"), icon: Codicon.refresh, enabled: !this.computing, run: () => void this.compute() }],
			});
		} else {
			this.frame.setEmpty(undefined);
		}
	}

	/** The selected item's details, what the bill was measured from, and the bill's notes. */
	private renderProperties(document: IBoqDocument | undefined, changed: readonly string[]): void {
		const panel = this.frame.properties;
		if (!panel) {
			return;
		}
		clearNode(panel);
		if (!document) {
			appendPropertyNote(panel, localize('boq.propsNotMeasured', "The bill has not been measured yet."));
			return;
		}
		const item = document.items.find(i => i.code === this.selected);
		if (item) {
			appendPropertyHeading(panel, `${item.code}  ${item.description}`);
			appendPropertyRow(panel, localize('boq.propGroup', "Group"), groupTitle(item.group));
			appendPropertyRow(panel, localize('boq.quantity', "Quantity"), quantityText(item.quantity, item.unit, this.imperial));
			if (item.material) {
				appendPropertyRow(panel, localize('boq.propMaterial', "Material"), item.material);
			}
			if (item.kind) {
				appendPropertyRow(panel, localize('boq.propKind', "Element"), item.kind);
			}
			if (typeof item.diameter === 'number') {
				appendPropertyRow(panel, localize('boq.propDiameter', "Bar diameter"), localize('boq.mm', "{0} mm", item.diameter));
			}
			appendPropertyRow(panel, localize('boq.propElements', "Elements"), String(item.breakdown?.length ?? 0));
			const stories = Object.entries(item.byStory ?? {});
			if (stories.length) {
				appendPropertyHeading(panel, localize('boq.byStoryHeading', "By story"));
				for (const [story, quantity] of stories) {
					appendPropertyRow(panel, story, quantityText(quantity, item.unit, this.imperial));
				}
				// What is on no story (foundations, special-structure members): the rows add up to the item.
				const other = item.quantity - stories.reduce((sum, [, quantity]) => sum + quantity, 0);
				if (other > 0.0005 * Math.max(1, item.quantity)) {
					appendPropertyRow(panel, localize('boq.noStory', "Other (no story)"), quantityText(other, item.unit, this.imperial));
				}
			}
		} else {
			appendPropertyNote(panel, localize('boq.selectRow', "Select a row for its details."));
		}

		const problems = boqProblems(document);
		if (problems.length) {
			appendPropertyHeading(panel, localize('boq.problemsHeading', "Not measured ({0})", problems.length));
			for (const problem of problems) {
				appendPropertyNote(panel, problem);
			}
		}

		appendPropertyHeading(panel, localize('boq.sourcesHeading', "Measured from"));
		for (const source of BOQ_SOURCES) {
			appendPropertyRow(panel, source.label, changed.includes(source.label) ? localize('boq.sourceChanged', "Changed") : localize('boq.sourceCurrent', "Up to date"));
		}

		if (document.notes?.length) {
			appendPropertyHeading(panel, localize('boq.notes', "Notes ({0})", document.notes.length));
			for (const note of document.notes) {
				appendPropertyNote(panel, note);
			}
		}
	}

	// ───────────────────────────── actions ─────────────────────────────

	private async compute(): Promise<void> {
		const model = this.model;
		const resource = (this.input as BoqEditorInput | undefined)?.resource;
		const { args, missing } = boqComputeArgs(new Map(BOQ_SOURCES.map(({ part }) => [part, this.sources.get(part)?.getValue()])), this.projectService.project?.root.fsPath);
		if (!model || !resource || this.computing) {
			return;
		}
		if (!args) {
			this.notificationService.warn(localize('boq.missingSources', "The bill cannot be measured: {0} could not be read.", missing.join(', ')));
			return;
		}
		this.computing = true;
		this.renderChrome();
		try {
			const result = await this.commandService.executeCommand<IBoqComputeResult>(BOQ_COMPUTE_COMMAND, args);
			if (!result?.text) {
				this.notificationService.warn(localize('boq.problems', "The bill could not be measured: {0}", (result?.problems ?? []).join('; ')));
				return;
			}
			if (model.isDisposed()) {
				return;
			}
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: result.text }], () => null);
			model.pushStackElement();
			await this.textFileService.save(resource);
		} catch (error) {
			this.notificationService.error(localize('boq.failed', "The bill could not be measured: {0}", String(error)));
		} finally {
			this.computing = false;
			this.renderChrome();
		}
	}

	private async exportCsv(): Promise<void> {
		const document = this.document;
		if (document) {
			await exportBoqCsv(document, this.projectService.project, {
				textModelService: this.textModelService,
				fileService: this.fileService,
				fileDialogService: this.fileDialogService,
				notificationService: this.notificationService,
			});
		}
	}

	private async openAsJson(): Promise<void> {
		const resource = (this.input as BoqEditorInput | undefined)?.resource;
		if (resource) {
			await this.editorService.openEditor({ resource, options: { override: DEFAULT_EDITOR_ASSOCIATION.id, pinned: true } }, this.group);
		}
	}

	private setAllExpanded(expanded: boolean): void {
		this.expanded.clear();
		if (expanded) {
			for (const item of this.document?.items ?? []) {
				this.expanded.add(item.code);
			}
		}
		this.renderBody(this.selected);
	}

	private toggle(code: string, expanded = !this.expanded.has(code)): void {
		if (expanded) {
			this.expanded.add(code);
		} else {
			this.expanded.delete(code);
		}
		this.select(code);
		this.renderBody(code);
	}

	private select(code: string | undefined): void {
		if (code === this.selected) {
			return;
		}
		this.selected = code;
		for (const [rowCode, row] of this.rows) {
			const isSelected = rowCode === code;
			row.classList.toggle('selected', isSelected);
			row.setAttribute('aria-selected', String(isSelected));
		}
		const document = this.document;
		this.renderProperties(document, document ? this.changedLabels(document) : []);
	}

	private rowOf(code: string): HTMLElement | undefined {
		return this.rows.get(code);
	}

	private showContextMenu(item: IBoqItem, e: MouseEvent): void {
		const open = this.expanded.has(item.code);
		const quantity = quantityText(item.quantity, item.unit, this.imperial);
		const actions: IAction[] = [
			new Action('saengine.boq.row.toggle', open ? localize('boq.hideBreakdown', "Hide Breakdown") : localize('boq.showBreakdown', "Show Breakdown"), undefined, true, async () => this.toggle(item.code)),
			new Separator(),
			new Action('saengine.boq.row.copyQuantity', localize('boq.copyQuantity', "Copy Quantity"), undefined, true, () => this.clipboardService.writeText(formatQuantity(item.quantity, item.unit))),
			new Action('saengine.boq.row.copyRow', localize('boq.copyRow', "Copy Row"), undefined, true, () => this.clipboardService.writeText([item.code, item.description, quantity].join('\t'))),
			new Separator(),
			this.exportAction,
		];
		const event = new StandardMouseEvent(getWindow(this.body), e);
		this.contextMenuService.showContextMenu({ getAnchor: () => event, getActions: () => actions });
	}

	// ───────────────────────────── tables ─────────────────────────────

	private renderBody(focusCode?: string): void {
		const { scrollTop } = this.scrollable.getScrollPosition();
		this.bodyDisposables.clear();
		this.rows.clear();
		clearNode(this.body);
		const document = this.model ? this.document : undefined;
		const problems = boqProblems(document);
		if (problems.length) {
			const box = append(this.body, $('.boq-problems', { role: 'status' }));
			append(box, $('.boq-problems-title', undefined, localize('boq.problemsTitle', "This bill is incomplete: {0} thing(s) could not be measured", problems.length)));
			const list = append(box, $('ul'));
			for (const problem of problems) {
				const entry = append(list, $('li'));
				append(entry, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
				append(entry, $('span', undefined, problem));
			}
		}
		if (document?.items.length) {
			const table = append(this.body, $('table.boq-table', { role: 'treegrid', 'aria-label': localize('boq.toolbar', "Bill of Quantities") }));
			const columns = append(table, $('colgroup'));
			append(columns, $('col.code'));
			append(columns, $('col.description'));
			append(columns, $('col.number'));
			append(columns, $('col.unit'));
			const head = append(append(table, $('thead')), $('tr'));
			append(head, $('th.code', undefined, localize('boq.code', "Code")));
			append(head, $('th', undefined, localize('boq.description', "Description")));
			append(head, $('th.number', undefined, localize('boq.quantity', "Quantity")));
			append(head, $('th.unit', undefined, localize('boq.unit', "Unit")));
			for (const { group, title } of BOQ_GROUPS) {
				const items = document.items.filter(i => i.group === group);
				if (items.length) {
					this.renderGroup(table, title, items, focusCode);
				}
			}
		}
		this.scrollable.scanDomNode();
		this.scrollable.setScrollPosition({ scrollTop });
	}

	/** One group: a heading row, the items (and the breakdowns shown) and the totals. */
	private renderGroup(table: HTMLElement, title: string, items: readonly IBoqItem[], focusCode: string | undefined): void {
		const body = append(table, $('tbody.boq-group'));
		append(append(body, $('tr.boq-group-row')), $('th', { colspan: '4', scope: 'rowgroup' }, title));
		for (const item of items) {
			const open = this.expanded.has(item.code);
			const row = append(body, $('tr.boq-item', { tabIndex: 0, 'aria-expanded': String(open), 'aria-selected': String(item.code === this.selected) }));
			this.rows.set(item.code, row);
			row.classList.toggle('selected', item.code === this.selected);
			const code = append(row, $('td.code'));
			append(code, $(`span.boq-twistie${ThemeIcon.asCSSSelector(open ? Codicon.chevronDown : Codicon.chevronRight)}`));
			append(code, $('span', undefined, item.code));
			append(row, $('td.description', undefined, item.description));
			const shown = displayQuantity(item.quantity, item.unit, this.imperial);
			append(row, $('td.number', undefined, formatQuantity(shown.quantity, shown.unit)));
			append(row, $('td.unit', undefined, unitLabel(shown.unit)));
			this.bodyDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.toggle(item.code)));
			this.bodyDisposables.add(addDisposableListener(row, EventType.FOCUS, () => this.select(item.code)));
			this.bodyDisposables.add(addDisposableListener(row, EventType.CONTEXT_MENU, (e: MouseEvent) => {
				e.preventDefault();
				this.select(item.code);
				this.showContextMenu(item, e);
			}));
			this.bodyDisposables.add(addDisposableListener(row, EventType.KEY_DOWN, (e: KeyboardEvent) => this.onRowKey(new StandardKeyboardEvent(e), row, item)));
			if (open) {
				this.renderBreakdown(append(append(body, $('tr.boq-breakdown')), $('td', { colspan: '4' })), item);
			}
			if (item.code === focusCode) {
				row.focus();
			}
		}
		// Only like with like (totalRows): no total of excavation with backfill, sand with stone, or counts.
		for (const { label, unit, total } of items[0] ? totalRows(items[0].group, items) : []) {
			const shown = displayQuantity(total, unit, this.imperial);
			const row = append(body, $('tr.boq-total'));
			append(row, $('td.code'));
			append(row, $('td', undefined, label ? localize('boq.totalOf', "Total {0}", label) : localize('boq.total', "Total")));
			append(row, $('td.number', undefined, formatQuantity(shown.quantity, shown.unit)));
			append(row, $('td.unit', undefined, unitLabel(shown.unit)));
		}
	}

	private onRowKey(event: StandardKeyboardEvent, row: HTMLElement, item: IBoqItem): void {
		const rows = [...this.rows.values()];
		const index = rows.indexOf(row);
		if (event.equals(KeyCode.Enter) || event.equals(KeyCode.Space)) {
			this.toggle(item.code);
		} else if (event.equals(KeyCode.RightArrow)) {
			this.toggle(item.code, true);
		} else if (event.equals(KeyCode.LeftArrow)) {
			this.toggle(item.code, false);
		} else if (event.equals(KeyCode.DownArrow)) {
			rows[Math.min(rows.length - 1, index + 1)]?.focus();
		} else if (event.equals(KeyCode.UpArrow)) {
			rows[Math.max(0, index - 1)]?.focus();
		} else {
			return;
		}
		event.preventDefault();
		event.stopPropagation();
	}

	/** The item's elements, aligned with the bill's own columns. */
	private renderBreakdown(cell: HTMLElement, item: IBoqItem): void {
		const table = append(cell, $('table.boq-breakdown-table'));
		const head = append(append(table, $('thead')), $('tr'));
		append(head, $('th', undefined, localize('boq.element', "Element")));
		append(head, $('th', undefined, localize('boq.story', "Story")));
		append(head, $('th', undefined, localize('boq.detail', "Detail")));
		append(head, $('th.number', undefined, localize('boq.quantity', "Quantity")));
		append(head, $('th.unit'));
		const body = append(table, $('tbody'));
		for (const entry of item.breakdown ?? []) {
			const row = append(body, $('tr'));
			append(row, $('td', undefined, entry.element));
			append(row, $('td', undefined, entry.story ?? ''));
			append(row, $('td.detail', undefined, entry.detail ?? ''));
			const shown = displayQuantity(entry.quantity, item.unit, this.imperial);
			append(row, $('td.number', undefined, formatQuantity(shown.quantity, shown.unit)));
			append(row, $('td.unit', undefined, unitLabel(shown.unit)));
		}
		if (!item.breakdown?.length) {
			append(append(body, $('tr')), $('td.muted', { colspan: '5' }, localize('boq.noBreakdown', "No breakdown by element was recorded.")));
		}
	}
}
