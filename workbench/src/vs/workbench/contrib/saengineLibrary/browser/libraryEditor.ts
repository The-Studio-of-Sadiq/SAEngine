/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, Separator, SubmenuAction } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextMenuService, IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { MATERIALS_SCHEMA, OBJECTS_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IDocumentProblem, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput, LibraryKind } from './libraryEditorInput.js';
import { humanize, JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

interface IVariant {
	/** Value of the item's discriminator field (material category, object kind). */
	readonly value: string;
	/** Template key for a new item of this variant. */
	readonly template: string;
	/** Schema definition of an item of this variant. */
	readonly defName: string;
}

interface ILibraryConfig {
	readonly schema: IJSONSchema;
	readonly listKey: 'materials' | 'objects';
	readonly discriminator: 'category' | 'kind';
	readonly variants: readonly IVariant[];
}

function libraryConfig(kind: LibraryKind): ILibraryConfig {
	if (kind === 'materials') {
		const categories = (MATERIALS_SCHEMA.$defs?.Category?.enum ?? []) as string[];
		return {
			schema: MATERIALS_SCHEMA,
			listKey: 'materials',
			discriminator: 'category',
			variants: categories.map(c => ({ value: c, template: `Material:${c}`, defName: 'Material' })),
		};
	}
	const items = OBJECTS_SCHEMA.properties?.objects?.items as IJSONSchema;
	return {
		schema: OBJECTS_SCHEMA,
		listKey: 'objects',
		discriminator: 'kind',
		variants: (items.oneOf ?? []).map(branch => {
			const defName = branch.$ref!.slice('#/$defs/'.length);
			const value = String(OBJECTS_SCHEMA.$defs![defName].properties!.kind.const);
			return { value, template: defName, defName };
		}),
	};
}

/**
 * Visual editor for the project's material and object-type libraries, in the shared editor
 * frame. The toolbar adds (by category/kind), duplicates and deletes entries; the list on the
 * left groups the entries by category/kind; the selected entry's form, generated from the
 * library's JSON Schema, fills the rest. Rule warnings show on the entries and in the status line.
 */
export class LibraryEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.EDITOR_ID;

	private listContainer!: HTMLElement;
	private detail!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	private detailTitle: HTMLElement | undefined;
	private selectedRow: HTMLElement | undefined;

	private config: ILibraryConfig | undefined;
	private selectedId: string | undefined;
	/** The entry the form edits (the selected one when the form was rendered). */
	private formItem: JsonObject | undefined;

	/** Ids from the project's materials file, for the material fields of object types. */
	private materialIds: { members: string[]; rebar: string[] } = { members: [], rebar: [] };

	private readonly form: SchemaForm;
	private readonly listDisposables = this._register(new DisposableStore());
	private readonly detailDisposables = this._register(new DisposableStore());

	private addAction: SubmenuAction | undefined;
	private readonly addActionStore = this._register(new DisposableStore());
	private addActionKind: LibraryKind | undefined;
	private readonly duplicateAction = this._register(new Action('saengine.library.duplicate', localize('library.duplicate', "Duplicate"), ThemeIcon.asClassName(Codicon.copy), false, async () => this.duplicateItem()));
	private readonly deleteAction = this._register(new Action('saengine.library.delete', localize('library.deleteTitle', "Delete"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteItem()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IDialogService private readonly dialogService: IDialogService,
		@ICommandService commandService: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IHoverService private readonly hoverService: IHoverService,
		@IConfigurationService configurationService: IConfigurationService,
	) {
		super(LibraryEditor.ID, group, telemetryService, themeService, storageService, commandService, editorService, textModelService, projectService);
		this.trackDeveloperMode(configurationService);
		const editor = this;
		this.form = instantiationService.createInstance(SchemaForm, {
			get root() { return editor.config?.schema ?? MATERIALS_SCHEMA; },
			template: defName => this.template(defName),
			references: path => this.references(path),
			validate: (path, value) => this.validate(path, value),
			changed: (path, structural) => this.onFormChanged(path, structural),
			mode: path => this.fieldMode(path),
		});
		this._register({ dispose: () => this.form.dispose() });
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		return this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: LibraryEditor.ID,
			ariaLabel: localize('library.toolbar', "Library"),
		}));
	}

	protected createBody(body: HTMLElement): void {
		body.classList.add('library-split');
		const master = append(body, $('.library-master'));
		this.listContainer = append(master, $('.library-list', { role: 'listbox', tabIndex: 0 }));
		this.detail = append(body, $('.library-detail'));
		this._register(addDisposableListener(this.listContainer, EventType.KEY_DOWN, e => this.onListKey(new StandardKeyboardEvent(e))));
	}

	protected override onWillLoadInput(): void {
		const kind = this.kind;
		this.config = kind === 'materials' || kind === 'objects' ? libraryConfig(kind) : undefined;
		this.selectedId = undefined;
		this.documentFrame?.setTitle(kind === 'materials' ? localize('library.materialsTitle', "Materials") : localize('library.objectsTitle', "Object Types"));
		this.documentFrame?.setHelp(kind === 'materials'
			? localize('library.materialsHelp', "The materials of the project: concrete, rebar, steel, masonry and mortar, with their mechanical properties. Object types refer to them by ID. Add with + (by category), duplicate or delete the selected material in the toolbar or by right-clicking it.")
			: localize('library.objectsHelp', "The object types of the project: beams, columns, slabs, walls, footings and the other member types, with their sections, materials and reinforcement. The floor plan places them by ID. Add with + (by kind), duplicate or delete the selected type in the toolbar or by right-clicking it."));
		this.listContainer.setAttribute('aria-label', kind === 'materials' ? localize('library.materialsList', "Materials") : localize('library.objectsList', "Object types"));
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		const add = this.createAddAction();
		if (!add || !this.document) {
			return { primary: [] };
		}
		this.duplicateAction.enabled = this.deleteAction.enabled = !!this.selected;
		return { primary: [add, this.duplicateAction, this.deleteAction] };
	}

	/** "+" with a menu of the categories/kinds to add (built again when the library changes). */
	private createAddAction(): SubmenuAction | undefined {
		const config = this.config;
		if (!config) {
			return undefined;
		}
		if (this.addAction && this.addActionKind === this.kind) {
			return this.addAction;
		}
		this.addActionStore.clear();
		this.addActionKind = this.kind;
		const materials = config.listKey === 'materials';
		const actions = config.variants.map(variant => this.addActionStore.add(new Action(`saengine.library.add.${variant.value}`, humanize(variant.value), undefined, true, async () => this.addItem(variant))));
		this.addAction = new SubmenuAction(`saengine.library.add.${config.listKey}`,
			materials ? localize('library.addMaterial', "Add Material") : localize('library.addObject', "Add Object Type"),
			actions, ThemeIcon.asClassName(Codicon.add));
		return this.addAction;
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (this.config && !Array.isArray(value[this.config.listKey])) {
			return { message: localize('library.unexpected', "This file does not have the expected \"{0}\" list. Fix it in the text editor.", this.config.listKey) };
		}
		return undefined;
	}

	protected override onCompanionChanged(text: string): void {
		try {
			const materials = (JSON.parse(text) as JsonObject).materials;
			const list = Array.isArray(materials) ? materials.filter(isObject) : [];
			this.materialIds = {
				// Members are made of concrete, steel, masonry, ...; never of rebar or mortar alone.
				members: list.filter(m => m.category !== 'rebar' && m.category !== 'mortar').map(m => String(m.id)),
				rebar: list.filter(m => m.category === 'rebar').map(m => String(m.id)),
			};
		} catch {
			return; // keep the last good list while the materials file is being fixed
		}
		if (this.document) {
			this.renderDetail();
		}
	}

	override focus(): void {
		super.focus();
		this.listContainer.focus();
	}

	/** `revealId` (e.g. from the Properties view) selects that entry. */
	protected override applyOptions(options: (IEditorOptions & { readonly revealId?: unknown }) | undefined): void {
		const id = options?.revealId;
		if (typeof id === 'string' && this.items.some(i => i.id === id)) {
			this.selectedId = id;
			this.render();
		}
	}

	// ───────────────────────────── document ─────────────────────────────

	private get items(): JsonObject[] {
		const list = this.config && this.document?.[this.config.listKey];
		return Array.isArray(list) ? list.filter(isObject) : [];
	}

	/** The entries in the order the list shows them (grouped by category or kind). */
	private get displayOrder(): JsonObject[] {
		const config = this.config;
		return config ? config.variants.flatMap(v => this.items.filter(i => i[config.discriminator] === v.value)) : [];
	}

	private get selected(): JsonObject | undefined {
		return this.items.find(i => i.id === this.selectedId);
	}

	private problemsOf(item: JsonObject): readonly IDocumentProblem[] {
		const list = this.config && this.document?.[this.config.listKey];
		const index = Array.isArray(list) ? list.indexOf(item) : -1;
		return this.problems.filter(p => p.index === index);
	}

	private onFormChanged(path: string, structural: boolean): void {
		// The entry whose form is shown: after its ID was typed, `selected` no longer finds it.
		const item = this.formItem ?? this.selected;
		if (item && this.config?.listKey === 'materials' && path === 'category') {
			this.replaceVariant(item, String(item.category));
			return;
		}
		if (path === 'id' && item) {
			this.selectedId = item.id as string;
		}
		this.changed(structural);
		if (!structural && (path === 'id' || path === 'name')) {
			this.renderList();
			this.renderDetailTitle();
		}
	}

	// ───────────────────────────── items ─────────────────────────────

	/** A template with its references pointed at entries that exist in this project. */
	private template(key: string): JsonObject {
		const value = clone((TEMPLATES[key] ?? {}) as JsonObject);
		this.fixReferences(value, '');
		return value;
	}

	private fixReferences(value: JsonObject, path: string): void {
		for (const [key, entry] of Object.entries(value)) {
			const entryPath = path ? `${path}.${key}` : key;
			if (isObject(entry)) {
				this.fixReferences(entry, entryPath);
				continue;
			}
			const allowed = this.references(entryPath);
			if (allowed && typeof entry === 'string' && !allowed.includes(entry) && allowed.length) {
				value[key] = allowed[0];
			}
		}
	}

	private uniqueId(base: string): string {
		const ids = new Set(this.items.map(i => i.id));
		if (!ids.has(base)) {
			return base;
		}
		for (let n = 2; ; n++) {
			if (!ids.has(`${base}-${n}`)) {
				return `${base}-${n}`;
			}
		}
	}

	private addItem(variant: IVariant): void {
		if (!this.document || !this.config) {
			return;
		}
		this.flush();
		const item = this.template(variant.template);
		item.id = this.uniqueId(String(item.id ?? variant.value.toUpperCase()));
		(this.document[this.config.listKey] as JsonValue[]).push(item);
		this.selectedId = item.id as string;
		this.changed(true);
	}

	private duplicateItem(): void {
		const item = this.selected;
		if (!item || !this.document || !this.config) {
			return;
		}
		this.flush();
		const copy = clone(item);
		copy.id = this.uniqueId(String(item.id));
		copy.name = localize('library.copyName', "{0} (copy)", String(item.name));
		const list = this.document[this.config.listKey] as JsonValue[];
		list.splice(list.indexOf(item) + 1, 0, copy);
		this.selectedId = copy.id as string;
		this.changed(true);
	}

	private async deleteItem(): Promise<void> {
		const item = this.selected;
		if (!item || !this.document || !this.config) {
			return;
		}
		const { confirmed } = await this.dialogService.confirm({
			message: localize('library.deleteConfirm', "Delete '{0}'?", String(item.name ?? item.id)),
			detail: localize('library.deleteDetail', "Anything that refers to {0} will show it as not defined. You can undo this with Ctrl+Z.", String(item.id)),
			primaryButton: localize('library.delete', "&&Delete"),
		});
		if (!confirmed || this.selected !== item || !this.document) {
			return;
		}
		const list = this.document[this.config.listKey] as JsonValue[];
		const index = list.indexOf(item);
		list.splice(index, 1);
		const remaining = this.items;
		this.selectedId = remaining[Math.min(index, remaining.length - 1)]?.id as string | undefined;
		this.changed(true);
	}

	/** Changes a material's category or an object's kind, keeping what both have in common. */
	private replaceVariant(item: JsonObject, value: string): void {
		const variant = this.config?.variants.find(v => v.value === value);
		if (!variant || !this.document || !this.config) {
			return;
		}
		const replacement = this.template(variant.template);
		for (const key of ['id', 'name', 'description', 'material']) {
			if (item[key] !== undefined) {
				replacement[key] = item[key];
			}
		}
		if (this.config.listKey === 'objects' && isObject(item.profile) && replacement.profile !== undefined) {
			replacement.profile = item.profile;
		}
		const list = this.document[this.config.listKey] as JsonValue[];
		list[list.indexOf(item)] = replacement;
		this.changed(true);
	}

	// ───────────────────────────── references and rules ─────────────────────────────

	private references(path: string): readonly string[] | undefined {
		if (this.config?.listKey === 'materials') {
			return path === 'masonry.mortar' ? this.items.filter(i => i.category === 'mortar').map(i => String(i.id)) : undefined;
		}
		switch (path) {
			case 'material': return this.materialIds.members;
			case 'reinforcement.material': return this.materialIds.rebar;
			case 'pile': return this.items.filter(i => i.kind === 'pile').map(i => String(i.id));
		}
		return undefined;
	}

	/** Material property groups follow the category, mirroring the Python model's rules. */
	private fieldMode(path: string): 'hidden' | 'required' | undefined {
		const item = this.selected;
		if (this.config?.listKey !== 'materials' || !item) {
			return undefined;
		}
		const category = item.category;
		const group = { concrete: 'concrete', rebar: 'steel', steel: 'steel', masonry: 'masonry' }[String(category)];
		if (path === 'concrete' || path === 'steel' || path === 'masonry') {
			return path === group ? 'required' : 'hidden';
		}
		if (path === 'composition' && category !== 'concrete' && category !== 'mortar') {
			return 'hidden';
		}
		return undefined;
	}

	private validate(path: string, value: string): string | undefined {
		if (path === 'id' && this.items.some(i => i !== this.selected && i.id === value)) {
			return localize('library.duplicateId', "Another entry already uses the ID {0}.", value);
		}
		return undefined;
	}

	// ───────────────────────────── rendering ─────────────────────────────

	protected render(): void {
		if (!this.selected) {
			this.selectedId = this.items[0]?.id as string | undefined;
		}
		this.renderList();
		this.renderDetail();
		this.renderStatus();
	}

	protected renderProblems(): void {
		this.renderList();
		this.renderDetailProblems();
		this.renderStatus();
	}

	private renderList(): void {
		this.listDisposables.clear();
		clearNode(this.listContainer);
		this.selectedRow = undefined;
		const config = this.config;
		if (!config || !this.document) {
			return;
		}
		const fileProblems = this.problems.filter(p => p.index === null);
		if (fileProblems.length) {
			const box = append(this.listContainer, $('.library-list-problems'));
			for (const problem of fileProblems) {
				const row = append(box, $('.library-problem'));
				append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
				append(row, $('span', undefined, problem.message));
			}
		}
		for (const variant of config.variants) {
			const members = this.items.filter(i => i[config.discriminator] === variant.value);
			if (!members.length) {
				continue;
			}
			append(this.listContainer, $('.library-list-group', { role: 'presentation' }, humanize(variant.value)));
			for (const item of members) {
				const id = String(item.id);
				const selected = item.id === this.selectedId;
				const row = append(this.listContainer, $('.library-list-item', { role: 'option', 'aria-selected': String(selected), id: `library-item-${id}` }));
				row.classList.toggle('selected', selected);
				if (selected) {
					this.selectedRow = row;
				}
				append(row, $('span.item-id', undefined, id));
				append(row, $('span.item-name', undefined, String(item.name ?? '')));
				const problems = this.problemsOf(item);
				if (problems.length) {
					row.classList.add('has-problems');
					const icon = append(row, $(`span.item-warning${ThemeIcon.asCSSSelector(Codicon.warning)}`));
					this.listDisposables.add(this.hoverService.setupDelayedHover(icon, { content: problems.map(p => p.message).join('\n') }));
				}
				this.listDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.select(id)));
				this.listDisposables.add(addDisposableListener(row, EventType.CONTEXT_MENU, e => {
					e.preventDefault();
					this.showItemMenu({ x: e.clientX, y: e.clientY }, id);
				}));
				if (selected) {
					this.listContainer.setAttribute('aria-activedescendant', row.id);
				}
			}
		}
		if (!this.items.length) {
			append(this.listContainer, $('.library-list-empty', undefined, localize('library.empty', "Nothing here yet. Add an entry with + in the toolbar.")));
		}
	}

	/** Right-click on an entry: duplicate or delete it. */
	private showItemMenu(anchor: { readonly x: number; readonly y: number }, id: string): void {
		this.select(id);
		this.contextMenuService.showContextMenu({
			getAnchor: () => anchor,
			getActions: () => [this.duplicateAction, new Separator(), this.deleteAction],
		});
	}

	private renderDetail(): void {
		this.detailDisposables.clear();
		clearNode(this.detail);
		this.problemBox = undefined;
		this.detailTitle = undefined;
		const config = this.config;
		const item = this.formItem = this.selected;
		if (!config || !item) {
			return;
		}
		const header = append(this.detail, $('.library-detail-header'));
		this.detailTitle = append(header, $('.library-detail-title'));
		this.renderDetailTitle();
		this.problemBox = append(this.detail, $('.library-problems'));
		this.renderDetailProblems();

		const form = append(this.detail, $('.library-form'));
		// The category/kind first, as a field like the others; changing it keeps the shared fields.
		const typeRow = append(form, $('.form-field'));
		const typeLabel = config.listKey === 'materials' ? localize('library.categoryLabel', "Category") : localize('library.kindLabel', "Kind");
		append(append(typeRow, $('.form-label-cell')), $('label.form-label', undefined, typeLabel));
		const variants = config.variants;
		const current = Math.max(0, variants.findIndex(v => v.value === item[config.discriminator]));
		const select = this.detailDisposables.add(new SelectBox(variants.map(v => ({ text: humanize(v.value) })), current, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: typeLabel }));
		select.render(append(typeRow, $('.form-control')));
		this.detailDisposables.add(select.onDidSelect(e => this.replaceVariant(item, variants[e.index].value)));

		const schema = config.schema.$defs?.[variants[current].defName];
		if (schema) {
			this.form.render(form, schema, item, [config.discriminator]);
		}
	}

	/** The selected entry's name and id above its form, kept up to date while they are typed. */
	private renderDetailTitle(): void {
		const title = this.detailTitle;
		const item = this.selected;
		if (!title || !item) {
			return;
		}
		clearNode(title);
		append(title, $('span.library-detail-name', undefined, String(item.name || item.id)));
		if (item.name) {
			append(title, $('span.library-detail-id', undefined, String(item.id)));
		}
	}

	/** Fills the selected entry's warning box without rebuilding the form (keeps focus while typing). */
	private renderDetailProblems(): void {
		const box = this.problemBox;
		const item = this.selected;
		if (!box) {
			return;
		}
		clearNode(box);
		const problems = item ? this.problemsOf(item) : [];
		box.classList.toggle('visible', problems.length > 0);
		for (const problem of problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			const field = problem.path ? `${problem.path.split('.').map(humanize).join(' › ')}: ` : '';
			append(row, $('span', undefined, `${field}${problem.message}`));
		}
	}

	/** Counts in the status line; with rule warnings, how many and where. */
	private renderStatus(): void {
		const frame = this.documentFrame;
		const config = this.config;
		if (!frame || !config || !this.document) {
			return;
		}
		const count = this.items.length;
		const materials = config.listKey === 'materials';
		const text = materials
			? count === 1 ? localize('library.oneMaterial', "1 material") : localize('library.materials', "{0} materials", count)
			: count === 1 ? localize('library.oneObject', "1 object type") : localize('library.objects', "{0} object types", count);
		const problems = this.problems.length;
		if (!problems) {
			frame.setStatus({ text });
			return;
		}
		// The next other entry with a problem below the selected one in the list (wrapping round), so
		// repeated clicks walk through every entry that needs fixing.
		const items = this.items;
		const flaggedItems = new Set(this.problems.map(p => p.index === null ? undefined : items[p.index]));
		const ordered = this.displayOrder;
		const current = ordered.findIndex(i => i.id === this.selectedId);
		const flagged = ordered.map((item, i) => ({ item, i })).filter(({ item, i }) => i !== current && flaggedItems.has(item));
		const target = (flagged.find(({ i }) => i > current) ?? flagged[0])?.item;
		frame.setStatus({
			severity: 'warning',
			text: problems === 1 ? localize('library.statusOneProblem', "{0}. 1 problem to fix.", text) : localize('library.statusProblems', "{0}. {1} problems to fix.", text, problems),
			link: target ? { label: localize('library.showProblem', "Show {0}", String(target.id)), run: () => this.select(String(target.id)) } : undefined,
		});
	}

	private select(id: string): void {
		if (id === this.selectedId) {
			return;
		}
		this.flush();
		this.selectedId = id;
		this.render();
		this.updateDocumentFrameActions();
		this.duplicateAction.enabled = this.deleteAction.enabled = !!this.selected;
		this.listContainer.focus();
		this.selectedRow?.scrollIntoView({ block: 'nearest' });
	}

	private onListKey(e: StandardKeyboardEvent): void {
		const config = this.config;
		if (!config) {
			return;
		}
		if (e.keyCode === KeyCode.Delete && this.selected) {
			e.preventDefault();
			void this.deleteItem();
			return;
		}
		if ((e.keyCode === KeyCode.F10 && e.shiftKey) || e.keyCode === KeyCode.ContextMenu) {
			const row = this.selectedRow;
			if (row && this.selectedId) {
				e.preventDefault();
				const rect = row.getBoundingClientRect();
				this.showItemMenu({ x: rect.left + 24, y: rect.bottom }, this.selectedId);
			}
			return;
		}
		if (!(e.keyCode === KeyCode.UpArrow || e.keyCode === KeyCode.DownArrow)) {
			return;
		}
		const ordered = this.displayOrder;
		const index = ordered.findIndex(i => i.id === this.selectedId);
		const next = ordered[Math.min(ordered.length - 1, Math.max(0, index + (e.keyCode === KeyCode.DownArrow ? 1 : -1)))];
		if (next) {
			e.preventDefault();
			this.select(String(next.id));
		}
	}
}
