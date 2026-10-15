/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/boqEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { basename, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { BOQ_COMPUTE_COMMAND, BOQ_GROUPS, BOQ_SOURCES, changedSources, formatQuantity, IBoqComputeArgs, IBoqComputeResult, IBoqDocument, IBoqItem, parseBoq, toCsv, totals, unitLabel } from './boqDocument.js';
import { BoqEditorInput } from './boqEditorInput.js';

/**
 * The bill of quantities (`10 BOQ/boq.json`): concrete, reinforcement by bar diameter, formwork
 * and structural steel measured from the building model, in tables with their totals; a row
 * expands to its breakdown by element. The bar above says whether the building model, object
 * types or materials changed since the bill was measured, and measures it again on request.
 */
export class BoqEditor extends EditorPane {

	static readonly ID = BoqEditorInput.EDITOR_ID;

	private root!: HTMLElement;
	private bar!: HTMLElement;
	private body!: HTMLElement;
	private model: ITextModel | undefined;
	private readonly sources = new Map<string, ITextModel>();
	/** Codes of the items whose breakdown is shown. */
	private readonly expanded = new Set<string>();
	private computing = false;
	private sourcesVersion = 0;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly sourceDisposables = this._register(new DisposableStore());
	private readonly barDisposables = this._register(new DisposableStore());
	private readonly bodyDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super(BoqEditor.ID, group, telemetryService, themeService, storageService);
		// Editors restore before the project is detected: find the source files once it is.
		this._register(this.projectService.onDidChangeProject(async () => {
			if (this.input) {
				await this.trackSources();
				this.renderBar();
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		this.root = append(parent, $('.saengine-boq-editor'));
		this.bar = append(this.root, $('.boq-source'));
		this.body = append(this.root, $('.boq-body'));
		this.body.tabIndex = -1;
	}

	override async setInput(input: BoqEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.expanded.clear();
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
		this.root.style.width = `${dimension.width}px`;
		this.root.style.height = `${dimension.height}px`;
	}

	override focus(): void {
		super.focus();
		this.body.focus();
	}

	private get document(): IBoqDocument | undefined {
		return this.model && !this.model.isDisposed() ? parseBoq(this.model.getValue()) : undefined;
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
				this.sourceDisposables.add(model.onDidChangeContent(() => this.renderBar()));
			} catch {
				// A missing source file shows as changed until it is restored.
			}
		}
	}

	private render(): void {
		this.renderBar();
		this.renderBody();
	}

	// ───────────────────────────── source bar ─────────────────────────────

	private renderBar(): void {
		this.barDisposables.clear();
		clearNode(this.bar);
		if (!this.model) {
			return;
		}
		const document = this.document;
		const texts = new Map(BOQ_SOURCES.map(({ part }) => [part, this.sources.get(part)?.getValue()]));
		const changed = changedSources(document, texts);
		const status = append(this.bar, $('span.boq-source-status'));
		if (!document) {
			append(status, $(`span${ThemeIcon.asCSSSelector(Codicon.info)}`));
			append(status, $('span', undefined, localize('boq.notMeasured', "The bill of quantities has not been measured from the building model yet.")));
		} else if (changed.length) {
			const labels = BOQ_SOURCES.filter(s => changed.includes(s.part)).map(s => s.label);
			append(status, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(status, $('span', undefined, localize('boq.changed', "Changed since the bill was measured: {0}.", labels.join(', '))));
		} else {
			append(status, $(`span${ThemeIcon.asCSSSelector(Codicon.check)}`));
			append(status, $('span', undefined, localize('boq.current', "Measured from the current building model, object types and materials.")));
		}
		const actions = append(this.bar, $('.boq-source-actions'));
		const update = this.barDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: !!document && !changed.length, supportIcons: true }));
		update.label = `$(${Codicon.refresh.id}) ${document ? localize('boq.update', "Update from Building Model") : localize('boq.measure', "Measure from Building Model")}`;
		update.enabled = !this.computing;
		this.barDisposables.add(update.onDidClick(() => this.compute()));
		const exportCsv = this.barDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		exportCsv.label = `$(${Codicon.export.id}) ${localize('boq.exportCsv', "Export CSV")}`;
		exportCsv.enabled = !!document;
		this.barDisposables.add(exportCsv.onDidClick(() => this.exportCsv()));
	}

	private async compute(): Promise<void> {
		const model = this.model;
		const resource = (this.input as BoqEditorInput | undefined)?.resource;
		const text = (part: string) => this.sources.get(part)?.getValue();
		const [bimText, objectsText, materialsText] = BOQ_SOURCES.map(s => text(s.part));
		if (!model || !resource) {
			return;
		}
		if (bimText === undefined || objectsText === undefined || materialsText === undefined) {
			const missing = BOQ_SOURCES.filter(s => text(s.part) === undefined).map(s => s.label);
			this.notificationService.warn(localize('boq.missingSources', "The bill cannot be measured: {0} could not be read.", missing.join(', ')));
			return;
		}
		this.computing = true;
		this.renderBar();
		try {
			const args: IBoqComputeArgs = { bimText, objectsText, materialsText };
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
			this.renderBar();
		}
	}

	private async exportCsv(): Promise<void> {
		const document = this.document;
		if (!document) {
			return;
		}
		const root = this.projectService.project?.root;
		const exports = partById('exports');
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('boq.exportTitle', "Export Bill of Quantities"),
			defaultUri: root && exports ? joinPath(root, exports.folder, 'boq.csv') : undefined,
			filters: [{ name: localize('boq.csvFiles', "CSV Files"), extensions: ['csv'] }],
		});
		if (!target) {
			return;
		}
		try {
			await this.fileService.writeFile(target, VSBuffer.fromString(toCsv(document)));
			this.notificationService.info(localize('boq.exported', "Exported the bill of quantities to {0}.", basename(target)));
		} catch (error) {
			this.notificationService.error(localize('boq.exportFailed', "The bill of quantities could not be exported: {0}", String(error)));
		}
	}

	// ───────────────────────────── tables ─────────────────────────────

	private renderBody(focusCode?: string): void {
		const scrollTop = this.body.scrollTop;
		this.bodyDisposables.clear();
		clearNode(this.body);
		const document = this.document;
		if (!this.model) {
			return;
		}
		if (!document) {
			append(this.body, $('p.boq-message', undefined, localize('boq.empty', "Measure the bill from the building model to list its concrete, reinforcement, formwork and structural steel.")));
			return;
		}
		if (!document.items.length) {
			append(this.body, $('p.boq-message', undefined, localize('boq.nothing', "Nothing was measured: the building model has no elements of known object types.")));
		}
		for (const { group, title } of BOQ_GROUPS) {
			const items = document.items.filter(i => i.group === group);
			if (items.length) {
				this.renderGroup(title, items, focusCode);
			}
		}
		if (document.notes?.length) {
			const notes = append(this.body, $('details.boq-notes'));
			append(notes, $('summary', undefined, localize('boq.notes', "Notes ({0})", document.notes.length)));
			const list = append(notes, $('ul'));
			for (const note of document.notes) {
				append(list, $('li', undefined, note));
			}
		}
		this.body.scrollTop = scrollTop;
	}

	private renderGroup(title: string, items: readonly IBoqItem[], focusCode: string | undefined): void {
		const section = append(this.body, $('section.boq-group'));
		append(section, $('h2', undefined, title));
		const table = append(section, $('table.boq-table'));
		const head = append(append(table, $('thead')), $('tr'));
		append(head, $('th.code', undefined, localize('boq.code', "Code")));
		append(head, $('th', undefined, localize('boq.description', "Description")));
		append(head, $('th.number', undefined, localize('boq.quantity', "Quantity")));
		append(head, $('th.unit', undefined, localize('boq.unit', "Unit")));
		const body = append(table, $('tbody'));
		for (const item of items) {
			const open = this.expanded.has(item.code);
			const row = append(body, $('tr.boq-item'));
			row.tabIndex = 0;
			row.setAttribute('aria-expanded', String(open));
			const code = append(row, $('td.code'));
			append(code, $(`span${ThemeIcon.asCSSSelector(open ? Codicon.chevronDown : Codicon.chevronRight)}`));
			append(code, $('span', undefined, item.code));
			append(row, $('td', undefined, item.description));
			append(row, $('td.number', undefined, formatQuantity(item.quantity, item.unit)));
			append(row, $('td.unit', undefined, unitLabel(item.unit)));
			const toggle = () => {
				if (!this.expanded.delete(item.code)) {
					this.expanded.add(item.code);
				}
				this.renderBody(item.code);
			};
			this.bodyDisposables.add(addDisposableListener(row, EventType.CLICK, toggle));
			this.bodyDisposables.add(addDisposableListener(row, EventType.KEY_DOWN, (e: KeyboardEvent) => {
				const event = new StandardKeyboardEvent(e);
				if (event.equals(KeyCode.Enter) || event.equals(KeyCode.Space)) {
					event.preventDefault();
					toggle();
				}
			}));
			if (open) {
				this.renderBreakdown(append(append(body, $('tr.boq-breakdown')), $('td', { colspan: '4' })), item);
			}
			if (item.code === focusCode) {
				row.focus();
			}
		}
		const foot = append(table, $('tfoot'));
		for (const { unit, total } of totals(items)) {
			const row = append(foot, $('tr.boq-total'));
			append(row, $('td', { colspan: '2' }, localize('boq.total', "Total")));
			append(row, $('td.number', undefined, formatQuantity(total, unit)));
			append(row, $('td.unit', undefined, unitLabel(unit)));
		}
	}

	private renderBreakdown(cell: HTMLElement, item: IBoqItem): void {
		const stories = Object.entries(item.byStory ?? {});
		if (stories.length) {
			const list = stories.map(([story, quantity]) => localize('boq.storyShare', "{0}: {1} {2}", story, formatQuantity(quantity, item.unit), unitLabel(item.unit)));
			append(cell, $('.boq-stories', undefined, localize('boq.byStory', "By story: {0}", list.join(', '))));
		}
		const table = append(cell, $('table.boq-breakdown-table'));
		const head = append(append(table, $('thead')), $('tr'));
		append(head, $('th', undefined, localize('boq.element', "Element")));
		append(head, $('th', undefined, localize('boq.story', "Story")));
		append(head, $('th', undefined, localize('boq.detail', "Detail")));
		append(head, $('th.number', undefined, localize('boq.quantity', "Quantity")));
		const body = append(table, $('tbody'));
		for (const entry of item.breakdown ?? []) {
			const row = append(body, $('tr'));
			append(row, $('td', undefined, entry.element));
			append(row, $('td', undefined, entry.story ?? ''));
			append(row, $('td', undefined, entry.detail ?? ''));
			append(row, $('td.number', undefined, `${formatQuantity(entry.quantity, item.unit)} ${unitLabel(item.unit)}`));
		}
	}
}
