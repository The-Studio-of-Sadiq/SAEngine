/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/floorPlanTable.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { Disposable, DisposableStore, IReference } from '../../../../base/common/lifecycle.js';
import { basename, dirname, isEqual, joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, EditorInputCapabilities, GroupIdentifier, IEditorFactoryRegistry, IEditorOpenContext, IEditorSerializer, IRevertOptions, ISaveOptions, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { IWorkingCopyEditorService } from '../../../services/workingCopy/common/workingCopyEditorService.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { PROJECT_MENU, ProjectOpenContext } from '../../saengineProject/browser/projectMenu.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { footingsOwnedMessage } from './floorPlanEdits.js';
import { siblingPartFile } from './floorPlanEditorInput.js';
import {
	filterRows, GROUP_LABELS, IMemberRow, IRowFilter, ISort, MEMBER_GROUPS, memberRows, membersCsv, rowKey, rowRange, setRowsStory, setRowsType, SortKey, sortRows,
	storyOptions, TableEdit, typeOptions,
} from './floorPlanTableModel.js';

const tableIcon = registerIcon('saengine-members-table-icon', Codicon.table, localize('membersTableIcon', "Icon of the Members Table."));

/** The selection service's name for this editor. */
const SELECTION_SOURCE = 'membersTable';

/** The open command (command palette, the sidebar's ≡ menu; the floor plan's toolbar can call it). */
export const OPEN_MEMBERS_TABLE_COMMAND = 'saengine.floorPlan.openMembersTable';

/**
 * The floor plan (`floor-plan.json`) as a table of its members. Its edits are edits of the floor
 * plan's text file, so unsaved changes, Save and Revert are those of that file (as for the Floor
 * Plan editor, FloorPlanEditorInput).
 */
export class MembersTableInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.membersTable';
	static readonly EDITOR_ID = 'workbench.editor.saengine.membersTable';

	constructor(
		readonly floorPlan: URI,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super();
		this._register(this.textFileService.files.onDidChangeDirty(model => {
			if (isEqual(model.resource, this.floorPlan)) {
				this._onDidChangeDirty.fire();
			}
		}));
	}

	override isDirty(): boolean {
		return this.textFileService.isDirty(this.floorPlan);
	}

	override async save(_group: GroupIdentifier, options?: ISaveOptions): Promise<EditorInput | IUntypedEditorInput | undefined> {
		const saved = await this.textFileService.save(this.floorPlan, options);
		return saved ? this : undefined;
	}

	override async revert(_group: GroupIdentifier, options?: IRevertOptions): Promise<void> {
		await this.textFileService.revert(this.floorPlan, options);
	}

	/** A resource of its own, so the table opens beside the floor plan of the same file. */
	get resource(): URI {
		return this.floorPlan.with({ scheme: 'saengine-members-table' });
	}

	override get typeId(): string {
		return MembersTableInput.ID;
	}

	override get editorId(): string {
		return MembersTableInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('membersTable', "Members Table");
	}

	override getIcon(): ThemeIcon {
		return tableIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof MembersTableInput && isEqual(other.floorPlan, this.floorPlan));
	}
}

class MembersTableInputSerializer implements IEditorSerializer {
	canSerialize(): boolean {
		return true;
	}
	serialize(input: MembersTableInput): string {
		return JSON.stringify({ floorPlan: input.floorPlan.toJSON() });
	}
	deserialize(instantiationService: IInstantiationService, serialized: string): MembersTableInput {
		return instantiationService.createInstance(MembersTableInput, URI.revive(JSON.parse(serialized).floorPlan));
	}
}

/**
 * Tells the workbench that a floor plan edited in the Members Table is open in an editor, so a
 * floor plan made dirty by the table does not open a second, text tab of floor-plan.json
 * (TextFileEditorTracker opens dirty files that no editor shows). It restores no backups.
 */
class MembersTableWorkingCopyHandler extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.membersTableWorkingCopyHandler';

	constructor(@IWorkingCopyEditorService workingCopyEditorService: IWorkingCopyEditorService) {
		super();
		this._register(workingCopyEditorService.registerHandler({
			handles: () => false,
			isOpen: (workingCopy, editor) => editor instanceof MembersTableInput && isEqual(workingCopy.resource, editor.floorPlan),
			createEditor: () => { throw new Error('The Members Table restores no backups.'); },
		}));
	}
}

interface IColumn {
	readonly key: SortKey;
	readonly label: string;
	readonly className: string;
}

const COLUMNS: readonly IColumn[] = [
	{ key: 'id', label: localize('column.id', "ID"), className: 'id' },
	{ key: 'group', label: localize('column.kind', "Kind"), className: 'kind' },
	{ key: 'type', label: localize('column.type', "Object Type"), className: 'type' },
	{ key: 'section', label: localize('column.section', "Section (mm)"), className: 'section' },
	{ key: 'length', label: localize('column.length', "Length (mm)"), className: 'length' },
	{ key: 'story', label: localize('column.story', "Story"), className: 'story' },
	{ key: 'location', label: localize('column.location', "Location"), className: 'location' },
];

/**
 * The Members Table: every member placed on the floor plan, a row each, to filter by story,
 * kind and type, sort, select (click, Ctrl+click, Shift+click, Ctrl+A) and edit in place. Changing
 * a row's object type or story changes every selected row with it, as one undoable edit of the
 * floor plan's text model (the same model, and undo stack, as the Floor Plan editor's). The
 * selected member is shared with the Floor Plan and the Properties view.
 */
export class MembersTableEditor extends EditorPane {

	static readonly ID = MembersTableInput.EDITOR_ID;

	private frame!: EditorFrame;
	private body!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private storyFilter!: SelectBox;
	private kindFilter!: SelectBox;
	private typeFilter!: SelectBox;
	private search!: InputBox;
	private planModel: ITextModel | undefined;
	private objectsModel: ITextModel | undefined;
	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly cellEditor = this._register(new DisposableStore());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.render(), 100));

	private filter: IRowFilter = {};
	private sort: ISort = { key: 'group', descending: false };
	private readonly selected = new Set<string>();
	private anchor: string | undefined;
	private focused: string | undefined;
	private shown: IMemberRow[] = [];
	private storyIds: (string | undefined)[] = [];
	private typeIds: (string | undefined)[] = [];
	/** The object type cell of each row shown, by row key (for F2). */
	private readonly typeCells = new Map<string, HTMLElement>();

	private readonly undoAction = this._register(new Action('saengine.membersTable.undo', localize('membersTable.undo', "Undo"), ThemeIcon.asClassName(Codicon.discard), false, () => this.undoRedo(false)));
	private readonly redoAction = this._register(new Action('saengine.membersTable.redo', localize('membersTable.redo', "Redo"), ThemeIcon.asClassName(Codicon.redo), false, () => this.undoRedo(true)));
	private readonly exportAction = this._register(new Action('saengine.membersTable.export', localize('membersTable.exportCsv', "Export CSV..."), ThemeIcon.asClassName(Codicon.export), true, () => this.exportCsv()));
	private readonly floorPlanAction = this._register(new Action('saengine.membersTable.floorPlan', localize('membersTable.openFloorPlan', "Open Floor Plan"), ThemeIcon.asClassName(Codicon.symbolArray), true, () => this.openFloorPlan()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@INotificationService private readonly notificationService: INotificationService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(MembersTableEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.selectionService.onDidChangeSelection(({ selection, source }) => {
			if (source !== SELECTION_SOURCE && selection?.kind === 'member') {
				const key = rowKey(selection);
				this.selected.clear();
				this.selected.add(key);
				this.anchor = this.focused = key;
				this.renderRows(true);
			}
		}));
	}

	/** The floor plan this table shows (for undo and redo). */
	get resource(): URI | undefined {
		return (this.input as MembersTableInput | undefined)?.floorPlan;
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, { id: MembersTableEditor.ID, ariaLabel: localize('membersTable.toolbar', "Members Table") }));
		this.frame.element.classList.add('saengine-members-table');
		this.frame.setTitle(localize('membersTable.title', "Members"));
		this.frame.setHelp(localize('membersTable.help', "Every member placed on the floor plan. Filter, sort by a column heading, select rows (Ctrl+click, Shift+click, Ctrl+A) and click a row's object type or story to change it for all selected rows. Edits go to the floor plan and undo there too; typical floors follow their master."));

		const filter = (aria: string, className: string, onSelect: (index: number) => void) => {
			const box = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: aria }));
			box.render(append(this.frame.controlsSlot, $(`.members-filter.${className}`)));
			this._register(box.onDidSelect(({ index }) => onSelect(index)));
			return box;
		};
		this.storyFilter = filter(localize('membersTable.storyFilter', "Story"), 'story', index => this.setFilter({ story: this.storyIds[index] }));
		this.kindFilter = filter(localize('membersTable.kindFilter', "Kind"), 'kind', index => this.setFilter({ group: index ? MEMBER_GROUPS[index - 1] : undefined }));
		this.typeFilter = filter(localize('membersTable.typeFilter', "Object type"), 'type', index => this.setFilter({ type: this.typeIds[index] }));
		this.kindFilter.setOptions([{ text: localize('membersTable.allKinds', "All kinds") }, ...MEMBER_GROUPS.map(g => ({ text: GROUP_LABELS[g] }))], 0);
		this.search = this._register(new InputBox(append(this.frame.controlsSlot, $('.members-search')), this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			placeholder: localize('membersTable.search', "Find ID, type, grid"),
			ariaLabel: localize('membersTable.searchAria', "Find members by ID, object type or grid"),
		}));
		this._register(this.search.onDidChange(text => this.setFilter({ text })));

		this.frame.setActions([this.undoAction, this.redoAction, this.exportAction], [this.floorPlanAction]);
		this.body = $('.members-body', { tabIndex: 0, role: 'grid', 'aria-multiselectable': 'true', 'aria-label': localize('membersTable.aria', "Members") });
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Auto, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('members-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this._register(addDisposableListener(this.body, EventType.KEY_DOWN, e => this.onKey(new StandardKeyboardEvent(e))));
	}

	override async setInput(input: MembersTableInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.planModel = this.objectsModel = undefined;
		let references: IReference<IResolvedTextEditorModel>[];
		try {
			references = await Promise.all([input.floorPlan, siblingPartFile(input.floorPlan, 'objects')].map(r => this.textModelService.createModelReference(r)));
		} catch (error) {
			this.frame.setEmpty({ icon: Codicon.warning, title: localize('membersTable.noModel', "The floor plan could not be read"), text: String(error) });
			return;
		}
		if (token.isCancellationRequested || this.input !== input) {
			references.forEach(r => r.dispose());
			return;
		}
		references.forEach(r => this.inputDisposables.add(r));
		[this.planModel, this.objectsModel] = references.map(r => r.object.textEditorModel);
		for (const model of [this.planModel, this.objectsModel]) {
			this.inputDisposables.add(model.onDidChangeContent(() => this.renderScheduler.schedule()));
		}
		const current = this.selectionService.selection;
		if (current?.kind === 'member' && !this.selected.size) {
			this.selected.add(rowKey(current));
			this.anchor = this.focused = rowKey(current);
		}
		this.render();
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.cellEditor.clear();
		this.planModel = this.objectsModel = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.body.focus();
	}

	private get layoutJson(): unknown {
		return parse(this.planModel);
	}

	private setFilter(change: Partial<IRowFilter>): void {
		this.filter = { ...this.filter, ...change };
		this.renderRows();
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		this.cellEditor.clear();
		const layout = this.layoutJson;
		if (this.planModel && layout === undefined) {
			this.frame.setEmpty({ icon: Codicon.warning, title: localize('membersTable.invalid', "The floor plan is not valid JSON"), text: localize('membersTable.invalidText', "Fix floor-plan.json, then the table shows its members again.") });
			return;
		}
		this.frame.setEmpty(undefined);
		const stories = storiesOf(layout);
		this.storyIds = [undefined, ...stories.map(s => s.id)];
		if (this.filter.story && !stories.some(s => s.id === this.filter.story)) {
			this.filter = { ...this.filter, story: undefined };
		}
		this.storyFilter.setOptions([{ text: localize('membersTable.allStories', "All stories") }, ...stories.map(s => ({ text: s.name }))], Math.max(0, this.storyIds.indexOf(this.filter.story)));
		const types = [...new Set(memberRows(layout).map(r => r.type).filter(Boolean))].sort();
		this.typeIds = [undefined, ...types];
		if (this.filter.type && !types.includes(this.filter.type)) {
			this.filter = { ...this.filter, type: undefined };
		}
		this.typeFilter.setOptions([{ text: localize('membersTable.allTypes', "All types") }, ...types.map(t => ({ text: t }))], Math.max(0, this.typeIds.indexOf(this.filter.type)));
		this.renderRows();
		const resource = this.resource;
		this.undoAction.enabled = !!resource && this.undoRedoService.canUndo(resource);
		this.redoAction.enabled = !!resource && this.undoRedoService.canRedo(resource);
	}

	private renderRows(reveal = false): void {
		this.cellEditor.clear();
		const layout = this.layoutJson;
		const all = memberRows(layout, parse(this.objectsModel));
		const keys = new Set(all.map(rowKey));
		for (const key of [...this.selected]) {
			if (!keys.has(key)) {
				this.selected.delete(key);
			}
		}
		this.shown = sortRows(filterRows(layout, all, this.filter), this.sort);
		const names = new Map(storiesOf(layout).map(s => [s.id, s.name]));
		const typeNames = new Map(MEMBER_GROUPS.flatMap(g => typeOptions(parse(this.objectsModel), g)));

		clearNode(this.body);
		const table = append(this.body, $('table.members-table'));
		const columns = append(table, $('colgroup'));
		for (const column of COLUMNS) {
			append(columns, $(`col.${column.className}`));
		}
		const headRow = append(append(table, $('thead')), $('tr'));
		for (const column of COLUMNS) {
			const sorted = this.sort.key === column.key;
			const th = append(headRow, $(`th.${column.className}`, { 'aria-sort': sorted ? (this.sort.descending ? 'descending' : 'ascending') : 'none' }));
			const button = append(th, $('button.sort', { type: 'button' }));
			append(button, $('span', undefined, column.label));
			if (sorted) {
				append(button, $(`span${ThemeIcon.asCSSSelector(this.sort.descending ? Codicon.arrowDown : Codicon.arrowUp)}`));
			}
			this.cellEditor.add(addDisposableListener(button, EventType.CLICK, () => {
				this.sort = { key: column.key, descending: sorted ? !this.sort.descending : false };
				this.renderRows();
			}));
		}
		const tbody = append(table, $('tbody'));
		this.typeCells.clear();
		let focusedRow: HTMLElement | undefined;
		for (const row of this.shown) {
			const key = rowKey(row);
			const tr = append(tbody, $('tr.member', { 'data-key': key, 'aria-selected': String(this.selected.has(key)) }));
			tr.classList.toggle('selected', this.selected.has(key));
			tr.classList.toggle('focused', this.focused === key);
			append(tr, $('td.id', undefined, row.id));
			append(tr, $('td.kind', undefined, GROUP_LABELS[row.group]));
			// Footings are listed for reference; 9 Substructure places and edits them.
			const editable = row.group === 'footings' ? '' : '.editable';
			const type = append(tr, $(`td.type${editable}`, { title: typeNames.get(row.type) ?? row.type }, row.type || '—'));
			this.typeCells.set(key, type);
			append(tr, $('td.section', undefined, row.section || '—'));
			append(tr, $('td.length', { title: row.group === 'columns' ? localize('membersTable.height', "Height of the column") : '' }, row.length === undefined ? '' : String(row.length)));
			const story = append(tr, $(`td.story${editable}`, undefined, row.base !== undefined ? `${names.get(row.base) ?? row.base} – ${names.get(row.story) ?? row.story}` : names.get(row.story) ?? row.story));
			append(tr, $('td.location', { title: row.location }, row.location));
			if (this.focused === key) {
				focusedRow = tr;
			}
			this.cellEditor.add(addDisposableListener(tr, EventType.MOUSE_DOWN, e => {
				if (e.button !== 0) {
					return;
				}
				const editing = (e.target === type || e.target === story) && this.selected.has(key) && !e.ctrlKey && !e.metaKey && !e.shiftKey;
				if (editing) {
					e.preventDefault();
					this.editCell(row, e.target === type ? 'type' : 'story', e.target as HTMLElement);
					return;
				}
				this.select(key, e.ctrlKey || e.metaKey, e.shiftKey);
			}));
		}
		if (!this.shown.length) {
			append(this.body, $('p.members-empty', undefined, all.length ? localize('membersTable.noneShown', "No members match the filters.") : localize('membersTable.none', "No members are placed yet. Place them in the floor plan, or create a building from its grids (File > New Building from Grid).")));
		}
		this.frame.setStatus({
			text: this.selected.size
				? localize('membersTable.statusSelected', "{0} of {1} members shown · {2} selected", this.shown.length, all.length, this.selected.size)
				: localize('membersTable.status', "{0} of {1} members shown", this.shown.length, all.length),
		});
		this.scrollable.scanDomNode();
		if (reveal && focusedRow) {
			focusedRow.scrollIntoView({ block: 'nearest' });
			this.scrollable.scanDomNode();
		}
	}

	// ───────────────────────────── selection ─────────────────────────────

	private select(key: string, toggle: boolean, range: boolean): void {
		if (range) {
			const keys = rowRange(this.shown, this.anchor, key);
			if (!toggle) {
				this.selected.clear();
			}
			keys.forEach(k => this.selected.add(k));
		} else if (toggle) {
			if (!this.selected.delete(key)) {
				this.selected.add(key);
			}
			this.anchor = key;
		} else {
			this.selected.clear();
			this.selected.add(key);
			this.anchor = key;
		}
		this.focused = key;
		this.renderRows(true);
		this.body.focus();
		this.publishSelection();
	}

	/** The focused row, when selected, is the member the Floor Plan and Properties show. */
	private publishSelection(): void {
		const row = this.shown.find(r => rowKey(r) === this.focused);
		if (row && this.selected.has(rowKey(row))) {
			this.selectionService.setSelection({ kind: 'member', group: row.group, id: row.id }, SELECTION_SOURCE);
		}
	}

	private onKey(e: StandardKeyboardEvent): void {
		if (isEditableElement(getActiveElement() as HTMLElement) && getActiveElement() !== this.body) {
			return;
		}
		const index = this.shown.findIndex(r => rowKey(r) === this.focused);
		const move = (to: number) => {
			const row = this.shown[Math.max(0, Math.min(this.shown.length - 1, to))];
			if (row) {
				this.select(rowKey(row), false, e.shiftKey);
			}
		};
		if (e.keyCode === KeyCode.DownArrow) {
			move(index + 1);
		} else if (e.keyCode === KeyCode.UpArrow) {
			move(index - 1);
		} else if (e.keyCode === KeyCode.Home) {
			move(0);
		} else if (e.keyCode === KeyCode.End) {
			move(this.shown.length - 1);
		} else if (e.keyCode === KeyCode.KeyA && (e.ctrlKey || e.metaKey)) {
			this.shown.forEach(r => this.selected.add(rowKey(r)));
			this.renderRows();
		} else if (e.keyCode === KeyCode.Escape) {
			this.selected.clear();
			this.renderRows();
		} else if ((e.keyCode === KeyCode.F2 || e.keyCode === KeyCode.Enter) && index >= 0) {
			const row = this.shown[index];
			const cell = this.typeCells.get(rowKey(row));
			if (cell) {
				this.selected.add(rowKey(row));
				this.editCell(row, 'type', cell);
			}
		} else {
			return;
		}
		e.preventDefault();
		e.stopPropagation();
	}

	// ───────────────────────────── editing ─────────────────────────────

	/** The rows an edit of `row` changes: the selection when the row is in it, else the row. */
	private targets(row: IMemberRow): IMemberRow[] {
		const key = rowKey(row);
		return this.selected.has(key) ? this.shown.filter(r => this.selected.has(rowKey(r))) : [row];
	}

	private editCell(row: IMemberRow, field: 'type' | 'story', cell: HTMLElement): void {
		this.cellEditor.clear();
		if (row.group === 'footings') {
			this.notificationService.info(footingsOwnedMessage());
			return;
		}
		const layout = this.layoutJson;
		const options = field === 'type'
			? typeOptions(parse(this.objectsModel), row.group).map(([id, name]) => ({ id, text: id === name ? id : `${id} — ${name}` }))
			: storyOptions(layout, row.group).map(s => ({ id: s.id, text: s.name }));
		if (!options.length) {
			this.notificationService.info(field === 'type'
				? localize('membersTable.noTypes', "There are no object types for {0}s; add one in 4 Objects.", GROUP_LABELS[row.group].toLowerCase())
				: localize('membersTable.noStories', "The floor plan has no stories to choose from."));
			return;
		}
		const current = field === 'type' ? row.type : row.story;
		const targets = this.targets(row);
		clearNode(cell);
		cell.classList.add('editing');
		const box = this.cellEditor.add(new SelectBox(options.map(o => ({ text: o.text })), Math.max(0, options.findIndex(o => o.id === current)), this.contextViewService, defaultSelectBoxStyles, {
			ariaLabel: targets.length > 1
				? localize('membersTable.editMany', "{0} of {1} selected members", field === 'type' ? localize('column.type', "Object Type") : localize('column.story', "Story"), targets.length)
				: localize('membersTable.editOne', "{0} of {1}", field === 'type' ? localize('column.type', "Object Type") : localize('column.story', "Story"), row.id),
		}));
		box.render(cell);
		this.cellEditor.add(box.onDidSelect(({ index }) => {
			const value = options[index]?.id;
			if (value && value !== current) {
				this.apply(field === 'type'
					? setRowsType(this.layoutJson, parse(this.objectsModel), targets, value)
					: setRowsStory(this.layoutJson, targets, value));
			} else {
				this.renderRows();
			}
		}));
		box.focus();
	}

	private apply(edit: TableEdit): void {
		if (!edit.ok) {
			this.notificationService.info(edit.error);
			this.renderRows();
			return;
		}
		this.write(edit.layout);
		if (edit.skipped.length) {
			this.notificationService.info(localize('membersTable.skipped', "Changed {0} members; left {1} as they were (they cannot take it): {2}.", edit.changed, edit.skipped.length, edit.skipped.slice(0, 12).join(', ')));
		}
		this.body.focus();
	}

	/**
	 * Replaces the floor plan with `value` as one undoable edit of its text model, exactly as the
	 * Floor Plan editor writes (FloorPlanEditor.write), so both share one undo stack.
	 */
	private write(value: object): void {
		const model = this.planModel;
		if (!model || model.isDisposed()) {
			return;
		}
		model.pushStackElement();
		model.pushEditOperations([], [{ range: model.getFullModelRange(), text: JSON.stringify(value, undefined, '\t') + '\n' }], () => null);
		model.pushStackElement();
		this.renderScheduler.cancel();
		this.render();
	}

	async undoRedo(redo: boolean): Promise<void> {
		const resource = this.resource;
		if (resource) {
			await (redo ? this.undoRedoService.redo(resource) : this.undoRedoService.undo(resource));
		}
	}

	private async exportCsv(): Promise<void> {
		const input = this.input as MembersTableInput | undefined;
		const exportsPart = partById('exports');
		if (!input) {
			return;
		}
		const root = dirname(dirname(input.floorPlan));
		const target = await this.fileDialogService.showSaveDialog({
			title: localize('membersTable.exportTitle', "Export Members Table"),
			defaultUri: exportsPart ? joinPath(root, exportsPart.folder, 'members.csv') : undefined,
			filters: [{ name: localize('membersTable.csvFiles', "CSV Files"), extensions: ['csv'] }],
		});
		if (!target) {
			return;
		}
		const names = new Map(storiesOf(this.layoutJson).map(s => [s.id, s.name]));
		try {
			await this.fileService.writeFile(target, VSBuffer.fromString(membersCsv(this.shown, id => names.get(id) ?? id)));
			this.notificationService.info(localize('membersTable.exported', "Exported {0} members to {1}.", this.shown.length, basename(target)));
		} catch (error) {
			this.notificationService.error(localize('membersTable.exportFailed', "The members table could not be exported: {0}", String(error)));
		}
	}

	private async openFloorPlan(): Promise<void> {
		const resource = this.resource;
		if (resource) {
			await this.editorService.openEditor({ resource, options: { pinned: true } });
		}
	}
}

function parse(model: ITextModel | undefined): unknown {
	try {
		return model && !model.isDisposed() ? JSON.parse(model.getValue()) : undefined;
	} catch {
		return undefined;
	}
}

// ───────────────────────────── registration ─────────────────────────────

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(MembersTableEditor, MembersTableInput.EDITOR_ID, localize('membersTableEditor', "Members Table")),
	[new SyncDescriptor(MembersTableInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(MembersTableInput.ID, MembersTableInputSerializer);

registerWorkbenchContribution2(MembersTableWorkingCopyHandler.ID, MembersTableWorkingCopyHandler, WorkbenchPhase.BlockRestore);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: OPEN_MEMBERS_TABLE_COMMAND,
			title: localize2('saengine.openMembersTable', "Members Table"),
			metadata: { description: localize2('saengine.openMembersTable.description', "Opens every member of the floor plan as a table to filter, sort and edit.") },
			category: localize2('floorPlan.category', "Floor Plan"),
			f1: true,
			precondition: ProjectOpenContext,
			menu: { id: PROJECT_MENU, group: '1_project', order: 6, when: ProjectOpenContext },
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const part = partById('floorPlan');
		const editorService = accessor.get(IEditorService);
		if (!project || !part?.mainFile || project.type === 'structure') {
			accessor.get(INotificationService).info(localize('membersTable.noFloorPlan', "Open a building project to see its members."));
			return;
		}
		await editorService.openEditor(accessor.get(IInstantiationService).createInstance(MembersTableInput, joinPath(project.root, part.folder, part.mainFile)), { pinned: true });
	}
});

/** Ctrl+Z / Ctrl+Y in the Members Table undo and redo its edits to the floor plan. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	if (!(pane instanceof MembersTableEditor) || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	return pane.undoRedo(redo);
}

UndoCommand.addImplementation(110, 'saengine-members-table', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-members-table', accessor => undoRedo(accessor, true));

