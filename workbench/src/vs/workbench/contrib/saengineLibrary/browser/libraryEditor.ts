/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/libraryEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { MATERIALS_SCHEMA, OBJECTS_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
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

function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value));
}

function isObject(value: JsonValue | undefined): value is JsonObject {
	return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Visual editor for the project's material and object-type libraries. The left side lists the
 * entries grouped by category/kind; the right side is a form generated from the library's
 * JSON Schema. Edits are written to the file's text model only when they are valid.
 */
export class LibraryEditor extends EditorPane {

	private root!: HTMLElement;
	private banner!: HTMLElement;
	private listContainer!: HTMLElement;
	private detail!: HTMLElement;
	private toolbar!: HTMLElement;

	private config: ILibraryConfig | undefined;
	private document: JsonObject | undefined;
	private selectedId: string | undefined;
	private model: ITextModel | undefined;
	private applying = false;

	/** Ids from the project's materials file, for the material fields of object types. */
	private materialIds: { members: string[]; rebar: string[] } = { members: [], rebar: [] };

	private readonly form: SchemaForm;
	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly materialsReference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly viewDisposables = this._register(new DisposableStore());
	private readonly detailDisposables = this._register(new DisposableStore());
	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 300));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IDialogService private readonly dialogService: IDialogService,
		@IEditorService private readonly editorService: IEditorService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super(LibraryEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
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

	protected createEditor(parent: HTMLElement): void {
		this.root = append(parent, $('.saengine-library-editor'));
		this.banner = append(this.root, $('.library-banner'));
		const body = append(this.root, $('.library-body'));
		const master = append(body, $('.library-master'));
		this.toolbar = append(master, $('.library-toolbar'));
		this.listContainer = append(master, $('.library-list', { role: 'listbox', tabIndex: 0 }));
		this.detail = append(body, $('.library-detail'));
		this._register(addDisposableListener(this.listContainer, EventType.KEY_DOWN, e => this.onListKey(new StandardKeyboardEvent(e))));
	}

	override async setInput(input: LibraryEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.materialsReference.clear();
		this.config = libraryConfig(input.kind);

		const reference = await input.resolve();
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
		this.model = reference.object.textEditorModel;
		this.inputDisposables.add(this.model.onDidChangeContent(() => {
			if (!this.applying) {
				this.load(); // undo/redo, revert, external edits
			}
		}));

		if (input.kind === 'objects') {
			await this.trackMaterials();
		}
		this.selectedId = undefined;
		this.load();
	}

	override clearInput(): void {
		this.flush();
		this.inputDisposables.clear();
		this.materialsReference.clear();
		this.model = undefined;
		this.document = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.root.style.width = `${dimension.width}px`;
		this.root.style.height = `${dimension.height}px`;
	}

	override focus(): void {
		super.focus();
		this.listContainer.focus();
	}

	override dispose(): void {
		this.flush();
		super.dispose();
	}

	/** The library file's text model, for undo/redo. */
	get resource() {
		return (this.input as LibraryEditorInput | undefined)?.resource;
	}

	// ───────────────────────────── document ─────────────────────────────

	private get items(): JsonObject[] {
		const list = this.config && this.document?.[this.config.listKey];
		return Array.isArray(list) ? list.filter(isObject) : [];
	}

	private get selected(): JsonObject | undefined {
		return this.items.find(i => i.id === this.selectedId);
	}

	private load(): void {
		if (!this.model || !this.config) {
			return;
		}
		let parsed: unknown;
		try {
			parsed = JSON.parse(this.model.getValue());
		} catch (error) {
			this.showBanner(localize('library.invalidJson', "This file contains invalid JSON ({0}). Fix it in the text editor; the visual editor will not change it until then.", String(error)));
			this.document = undefined;
			this.renderAll();
			return;
		}
		if (!isObject(parsed as JsonValue) || !Array.isArray((parsed as JsonObject)[this.config.listKey])) {
			this.showBanner(localize('library.unexpected', "This file does not have the expected \"{0}\" list. Fix it in the text editor.", this.config.listKey));
			this.document = undefined;
			this.renderAll();
			return;
		}
		this.showBanner(undefined);
		this.document = parsed as JsonObject;
		if (!this.selected) {
			this.selectedId = this.items[0]?.id as string | undefined;
		}
		this.renderAll();
	}

	/** Writes the document to the text model as one undoable edit. */
	private commit(): void {
		this.commitScheduler.cancel();
		if (!this.model || !this.document || this.model.isDisposed()) {
			return;
		}
		const text = JSON.stringify(this.document, undefined, '\t') + '\n';
		if (text === this.model.getValue()) {
			return;
		}
		this.applying = true;
		try {
			this.model.pushStackElement();
			this.model.pushEditOperations([], [{ range: this.model.getFullModelRange(), text }], () => null);
			this.model.pushStackElement();
		} finally {
			this.applying = false;
		}
	}

	private flush(): void {
		if (this.commitScheduler.isScheduled()) {
			this.commit();
		}
	}

	private onFormChanged(path: string, structural: boolean): void {
		const item = this.selected;
		if (item && this.config?.listKey === 'materials' && path === 'category') {
			this.replaceVariant(item, String(item.category));
			return;
		}
		if (path === 'id' && item) {
			this.selectedId = item.id as string;
		}
		if (structural) {
			this.commit();
			this.renderAll();
		} else {
			this.commitScheduler.schedule();
			if (path === 'id' || path === 'name') {
				this.renderList();
			}
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
		const item = this.template(variant.template);
		item.id = this.uniqueId(String(item.id ?? variant.value.toUpperCase()));
		(this.document[this.config.listKey] as JsonValue[]).push(item);
		this.selectedId = item.id as string;
		this.commit();
		this.renderAll();
	}

	private duplicateItem(): void {
		const item = this.selected;
		if (!item || !this.document || !this.config) {
			return;
		}
		const copy = clone(item);
		copy.id = this.uniqueId(String(item.id));
		copy.name = localize('library.copyName', "{0} (copy)", String(item.name));
		const list = this.document[this.config.listKey] as JsonValue[];
		list.splice(list.indexOf(item) + 1, 0, copy);
		this.selectedId = copy.id as string;
		this.commit();
		this.renderAll();
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
		if (!confirmed || this.selected !== item) {
			return;
		}
		const list = this.document[this.config.listKey] as JsonValue[];
		const index = list.indexOf(item);
		list.splice(index, 1);
		const remaining = this.items;
		this.selectedId = remaining[Math.min(index, remaining.length - 1)]?.id as string | undefined;
		this.commit();
		this.renderAll();
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
		this.commit();
		this.renderAll();
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

	/** Follows the project's materials file (unsaved edits included) for the material pickers. */
	private async trackMaterials(): Promise<void> {
		const project = this.projectService.project;
		const part = PROJECT_PARTS.find(p => p.id === 'materials');
		if (!project || !part?.mainFile) {
			return;
		}
		try {
			this.materialsReference.value = await this.textModelService.createModelReference(joinPath(project.root, part.folder, part.mainFile));
		} catch {
			return;
		}
		const model = this.materialsReference.value.object.textEditorModel;
		const update = () => {
			try {
				const materials = (JSON.parse(model.getValue()) as JsonObject).materials;
				const list = Array.isArray(materials) ? materials.filter(isObject) : [];
				this.materialIds = {
					// Members are made of concrete, steel, masonry, ...; never of rebar or mortar alone.
					members: list.filter(m => m.category !== 'rebar' && m.category !== 'mortar').map(m => String(m.id)),
					rebar: list.filter(m => m.category === 'rebar').map(m => String(m.id)),
				};
			} catch {
				// keep the last good list while the materials file is being fixed
			}
		};
		update();
		this.inputDisposables.add(model.onDidChangeContent(() => {
			update();
			this.renderDetail();
		}));
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private showBanner(message: string | undefined): void {
		clearNode(this.banner);
		this.banner.classList.toggle('visible', !!message);
		if (message) {
			append(this.banner, $('span', undefined, message));
			const button = this.viewDisposables.add(new Button(this.banner, { ...defaultButtonStyles, secondary: true }));
			button.label = localize('library.openText', "Open in Text Editor");
			this.viewDisposables.add(button.onDidClick(() => this.openAsText()));
		}
	}

	private openAsText(): void {
		const resource = this.resource;
		if (resource) {
			void this.editorService.openEditor({ resource, options: { override: DEFAULT_EDITOR_ASSOCIATION.id } }, this.group);
		}
	}

	private renderAll(): void {
		this.viewDisposables.clear();
		this.renderToolbar();
		this.renderList();
		this.renderDetail();
	}

	private renderToolbar(): void {
		clearNode(this.toolbar);
		const config = this.config;
		if (!config || !this.document) {
			return;
		}
		const variants = config.variants;
		const select = this.viewDisposables.add(new SelectBox(variants.map(v => ({ text: humanize(v.value) })), 0, this.contextViewService, defaultSelectBoxStyles, {
			ariaLabel: config.listKey === 'materials' ? localize('library.category', "Category") : localize('library.kind', "Kind"),
		}));
		select.render(append(this.toolbar, $('.library-variant')));
		let variantIndex = 0;
		this.viewDisposables.add(select.onDidSelect(e => variantIndex = e.index));

		const buttons = append(this.toolbar, $('.library-buttons'));
		const add = this.viewDisposables.add(new Button(buttons, { ...defaultButtonStyles, supportIcons: true, title: localize('library.addTitle', "Add a new entry of the selected type") }));
		add.label = `$(${Codicon.add.id}) ${localize('library.add', "Add")}`;
		this.viewDisposables.add(add.onDidClick(() => this.addItem(variants[variantIndex])));

		const duplicate = this.viewDisposables.add(new Button(buttons, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('library.duplicate', "Duplicate") }));
		duplicate.label = `$(${Codicon.copy.id})`;
		duplicate.enabled = !!this.selected;
		this.viewDisposables.add(duplicate.onDidClick(() => this.duplicateItem()));

		const remove = this.viewDisposables.add(new Button(buttons, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('library.deleteTitle', "Delete") }));
		remove.label = `$(${Codicon.trash.id})`;
		remove.enabled = !!this.selected;
		this.viewDisposables.add(remove.onDidClick(() => this.deleteItem()));
	}

	private renderList(): void {
		clearNode(this.listContainer);
		const config = this.config;
		if (!config) {
			return;
		}
		for (const variant of config.variants) {
			const members = this.items.filter(i => i[config.discriminator] === variant.value);
			if (!members.length) {
				continue;
			}
			append(this.listContainer, $('.library-list-group', undefined, humanize(variant.value)));
			for (const item of members) {
				const selected = item.id === this.selectedId;
				const row = append(this.listContainer, $('.library-list-item', { role: 'option', 'aria-selected': String(selected) }));
				row.classList.toggle('selected', selected);
				append(row, $('span.item-id', undefined, String(item.id)));
				append(row, $('span.item-name', undefined, String(item.name ?? '')));
				this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.select(String(item.id))));
			}
		}
		if (!this.items.length && this.document) {
			append(this.listContainer, $('.library-list-empty', undefined, localize('library.empty', "Nothing here yet. Choose a type above and click Add.")));
		}
	}

	private renderDetail(): void {
		this.detailDisposables.clear();
		clearNode(this.detail);
		const config = this.config;
		const item = this.selected;
		if (!config || !item) {
			return;
		}
		const header = append(this.detail, $('.library-detail-header'));
		append(header, $('h2', undefined, String(item.name ?? item.id)));
		const typeRow = append(header, $('.library-detail-type'));
		append(typeRow, $('span', undefined, config.listKey === 'materials' ? localize('library.categoryLabel', "Category") : localize('library.kindLabel', "Kind")));
		const variants = config.variants;
		const current = Math.max(0, variants.findIndex(v => v.value === item[config.discriminator]));
		const select = this.detailDisposables.add(new SelectBox(variants.map(v => ({ text: humanize(v.value) })), current, this.contextViewService, defaultSelectBoxStyles, {
			ariaLabel: config.listKey === 'materials' ? localize('library.category', "Category") : localize('library.kind', "Kind"),
		}));
		select.render(append(typeRow, $('.library-variant')));
		this.detailDisposables.add(select.onDidSelect(e => this.replaceVariant(item, variants[e.index].value)));

		const variant = variants[current];
		const schema = config.schema.$defs?.[variant.defName];
		if (schema) {
			this.form.render(append(this.detail, $('.library-form')), schema, item, [config.discriminator]);
		}
	}

	private select(id: string): void {
		if (id === this.selectedId) {
			return;
		}
		this.flush();
		this.selectedId = id;
		this.renderAll();
		this.listContainer.focus();
	}

	private onListKey(e: StandardKeyboardEvent): void {
		const config = this.config;
		if (!config || !(e.keyCode === KeyCode.UpArrow || e.keyCode === KeyCode.DownArrow)) {
			return;
		}
		// Navigate in display order (grouped by type).
		const ordered = config.variants.flatMap(v => this.items.filter(i => i[config.discriminator] === v.value));
		const index = ordered.findIndex(i => i.id === this.selectedId);
		const next = ordered[Math.min(ordered.length - 1, Math.max(0, index + (e.keyCode === KeyCode.DownArrow ? 1 : -1)))];
		if (next) {
			e.preventDefault();
			this.select(String(next.id));
		}
	}
}
