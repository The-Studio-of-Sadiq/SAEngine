/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { MATERIALS_SCHEMA, OBJECTS_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { clone, IDocumentProblem, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
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
 * Visual editor for the project's material and object-type libraries. The left side lists the
 * entries grouped by category/kind; the right side is a form generated from the library's
 * JSON Schema.
 */
export class LibraryEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.EDITOR_ID;

	private listContainer!: HTMLElement;
	private detail!: HTMLElement;
	private toolbar!: HTMLElement;
	private problemBox: HTMLElement | undefined;

	private config: ILibraryConfig | undefined;
	private selectedId: string | undefined;

	/** Ids from the project's materials file, for the material fields of object types. */
	private materialIds: { members: string[]; rebar: string[] } = { members: [], rebar: [] };

	private readonly form: SchemaForm;
	private readonly detailDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IDialogService private readonly dialogService: IDialogService,
		@ICommandService commandService: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IHoverService private readonly hoverService: IHoverService,
	) {
		super(LibraryEditor.ID, group, telemetryService, themeService, storageService, commandService, editorService, textModelService, projectService);
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

	protected createBody(body: HTMLElement): void {
		const master = append(body, $('.library-master'));
		this.toolbar = append(master, $('.library-toolbar'));
		this.listContainer = append(master, $('.library-list', { role: 'listbox', tabIndex: 0 }));
		this.detail = append(body, $('.library-detail'));
		this._register(addDisposableListener(this.listContainer, EventType.KEY_DOWN, e => this.onListKey(new StandardKeyboardEvent(e))));
	}

	protected override onWillLoadInput(): void {
		const kind = this.kind;
		this.config = kind === 'materials' || kind === 'objects' ? libraryConfig(kind) : undefined;
		this.selectedId = undefined;
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

	// ───────────────────────────── document ─────────────────────────────

	private get items(): JsonObject[] {
		const list = this.config && this.document?.[this.config.listKey];
		return Array.isArray(list) ? list.filter(isObject) : [];
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
		const item = this.selected;
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
		this.changed(true);
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
		this.viewDisposables.clear();
		this.renderToolbar();
		this.renderList();
		this.renderDetail();
	}

	protected renderProblems(): void {
		this.renderList();
		this.renderDetailProblems();
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
		const fileProblems = this.problems.filter(p => p.index === null);
		if (fileProblems.length) {
			const box = append(this.listContainer, $('.library-list-problems'));
			for (const problem of fileProblems) {
				append(box, $('div', undefined, problem.message));
			}
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
				const problems = this.problemsOf(item);
				if (problems.length) {
					row.classList.add('has-problems');
					const icon = append(row, $(`span.item-warning${ThemeIcon.asCSSSelector(Codicon.warning)}`));
					this.viewDisposables.add(this.hoverService.setupDelayedHover(icon, { content: problems.map(p => p.message).join('\n') }));
				}
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
		this.problemBox = append(header, $('.library-problems'));
		this.renderDetailProblems();
		const typeRow = append(header, $('.library-detail-type'));
		append(typeRow, $('span', undefined, config.listKey === 'materials' ? localize('library.categoryLabel', "Category") : localize('library.kindLabel', "Kind")));
		const variants = config.variants;
		const current = Math.max(0, variants.findIndex(v => v.value === item[config.discriminator]));
		const select = this.detailDisposables.add(new SelectBox(variants.map(v => ({ text: humanize(v.value) })), current, this.contextViewService, defaultSelectBoxStyles, {
			ariaLabel: config.listKey === 'materials' ? localize('library.category', "Category") : localize('library.kind', "Kind"),
		}));
		select.render(append(typeRow, $('.library-variant')));
		this.detailDisposables.add(select.onDidSelect(e => this.replaceVariant(item, variants[e.index].value)));

		const schema = config.schema.$defs?.[variants[current].defName];
		if (schema) {
			this.form.render(append(this.detail, $('.library-form')), schema, item, [config.discriminator]);
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

	private select(id: string): void {
		if (id === this.selectedId) {
			return;
		}
		this.flush();
		this.selectedId = id;
		this.render();
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
