/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, Separator, SubmenuAction } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
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
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { BNBC, MATERIALS_SCHEMA, OBJECTS_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { keepMaterialDefaults, projectMaterial } from '../../../services/saengineProject/common/materialDefaults.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IDocumentProblem, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput, LibraryKind } from './libraryEditorInput.js';
import { humanize, JsonObject, JsonValue, SchemaForm } from './schemaForm.js';
import { parseSection, SECTIONS_FOLDER } from './sectionDesignerModel.js';
import { modifiersView, objectTypeTarget, pruneForKind, readCodeStiffness, resetObjectTypeGroup, setObjectTypeField } from '../../saengineModel/browser/modifiersModel.js';
import { renderModifiers } from '../../saengineModel/browser/modifiersPanel.js';

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

/** The material categories each kind of object type can be made of (members never of rebar or mortar alone). */
const KIND_MATERIALS: { readonly [kind: string]: readonly string[] } = {
	beam: ['concrete', 'steel', 'timber', 'other'],
	column: ['concrete', 'steel', 'masonry', 'timber', 'other'],
	brace: ['steel', 'timber', 'other'],
	slab: ['concrete', 'other'],
	wall: ['concrete', 'masonry', 'other'],
	staircase: ['concrete', 'other'],
	footing: ['concrete', 'other'],
	pileCap: ['concrete', 'other'],
	pile: ['concrete', 'steel', 'other'],
};

/** What each kind of object type is for, under the Kind field. */
const KIND_HELP: { readonly [kind: string]: string } = {
	beam: localize('library.kindBeam', "A beam: a line member between supports, with its section, material and bars. The floor plan places it between grid points."),
	column: localize('library.kindColumn', "A column: a vertical member rising between storeys. Its bars go round the perimeter; ρ is shown below them."),
	brace: localize('library.kindBrace', "A brace: a steel diagonal between storeys, with its gusset connection."),
	slab: localize('library.kindSlab', "A slab: a floor or roof plate of a thickness, spanning one or two ways between beams (or flat on columns). The floor plan fills panels with it; Project Settings › Area Loads give its loads."),
	wall: localize('library.kindWall', "A wall: a structural (shear) wall of a thickness, rising between storeys. Partition walls are loads, not object types."),
	staircase: localize('library.kindStaircase', "A staircase: its waist, risers and treads, and the landings."),
	footing: localize('library.kindFooting', "A footing: designed in 9 Substructure; this type gives its material and bars."),
	pileCap: localize('library.kindPileCap', "A pile cap on bored piles of a pile type; designed in 9 Substructure."),
	pile: localize('library.kindPile', "A bored pile: its diameter, length and bars; pile caps refer to it."),
};

/** Ec = 4700 √f'c (BNBC 2020 Part 6 Sec 6.1.7.1) and fr = 0.62 √f'c (Eq. 6.6.3), rounded as the defaults are. */
export function concreteFromFc(fc: number): { readonly E: number; readonly fr: number } {
	const root = Math.sqrt(fc);
	return { E: Math.round(BNBC.concrete.ec * root / 10) * 10, fr: Math.round(BNBC.concrete.fr * root * 100) / 100 };
}

/** Whether `value` is the code relation of `fc` (within rounding): it then follows f'c. */
function follows(value: JsonValue | undefined, derived: number): boolean {
	return typeof value !== 'number' || Math.abs(value - derived) <= Math.max(0.005 * derived, 0.01);
}

/**
 * Column steel ratio limits: at least 1 % (ACI 318 10.6.1.1, as BNBC 2020 Part 6 Chapter 6;
 * the design reads the code pack's `columnRho`), and above 4 % the lapped bars crowd the
 * section (ACI 318 R10.6.1.1), so a warning, not an error.
 */
const COLUMN_RHO_MIN = 0.01;
const COLUMN_RHO_PRACTICAL = 0.04;

/** Gross area of a solid rectangle or circle profile [mm²]; undefined for other shapes. */
export function grossArea(profile: JsonValue | undefined): number | undefined {
	if (!isObject(profile)) {
		return undefined;
	}
	if (profile.shape === 'rectangle' && typeof profile.xDim === 'number' && typeof profile.yDim === 'number') {
		return profile.xDim * profile.yDim;
	}
	if (profile.shape === 'circle' && typeof profile.radius === 'number') {
		return Math.PI * profile.radius ** 2;
	}
	return undefined;
}

/** Area of the longitudinal bars of a linear reinforcement [mm²]. */
export function longitudinalArea(reinforcement: JsonValue | undefined): number {
	const groups = isObject(reinforcement) && Array.isArray(reinforcement.longitudinal) ? reinforcement.longitudinal.filter(isObject) : [];
	return groups.reduce((sum, g) => sum + (typeof g.count === 'number' && typeof g.dia === 'number' ? g.count * Math.PI * g.dia ** 2 / 4 : 0), 0);
}

/**
 * The fewest perimeter bars of the usual sizes that give a column of gross area `area` at least
 * 1 % steel: at least 4 bars (6 round a circle), in even counts.
 */
export function columnBars(area: number, circular: boolean): { readonly count: number; readonly dia: number } {
	const options: { count: number; dia: number; steel: number }[] = [];
	for (const dia of [16, 20, 25, 28, 32]) {
		for (let count = circular ? 6 : 4; count <= 24; count += 2) {
			options.push({ count, dia, steel: count * Math.PI * dia ** 2 / 4 });
		}
	}
	options.sort((a, b) => a.steel - b.steel || a.count - b.count);
	const best = options.find(o => o.steel >= COLUMN_RHO_MIN * area) ?? options[options.length - 1];
	return { count: best.count, dia: best.dia };
}

/** The id prefix of a new material of each category. */
const NEW_MATERIAL_ID: { readonly [category: string]: string } = { concrete: 'C', rebar: 'R', steel: 'S', masonry: 'MAS', mortar: 'M', other: 'MAT' };

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
	private materialIds: { members: { id: string; category: string }[]; rebar: string[] } = { members: [], rebar: [] };
	/** The designed sections of the project (`04 Objects/sections`), for designed profiles. */
	private sections: string[] = [];
	/** The selected entry of each file shown, kept while the editor shows another. */
	private readonly selections = new Map<string, string>();
	/** f'c of the concrete whose form is shown, before the edit being typed (E and fr follow it). */
	private formFc: number | undefined;
	/** The column's steel ratio row (see renderSteelRatio), and the form it is in. */
	private steelRatioRow: HTMLElement | undefined;
	private steelRatioForm: HTMLElement | undefined;
	/** The materials document, for which object types take the code's cracked factors (stiffness modifiers). */
	private materialsDoc: JsonObject | undefined;

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
		@ICommandService private readonly commands: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IHoverService private readonly hoverService: IHoverService,
		@IConfigurationService configurationService: IConfigurationService,
		@IFileService private readonly fileService: IFileService,
	) {
		super(LibraryEditor.ID, group, telemetryService, themeService, storageService, commands, editorService, textModelService, projectService);
		this.trackDeveloperMode(configurationService);
		const editor = this;
		this.form = instantiationService.createInstance(SchemaForm, {
			get root() { return editor.config?.schema ?? MATERIALS_SCHEMA; },
			template: defName => this.template(defName),
			references: path => this.references(path),
			validate: (path, value) => this.validate(path, value),
			changed: (path, structural) => this.onFormChanged(path, structural),
			mode: path => this.fieldMode(path),
			placeholder: path => this.placeholder(path),
			note: path => this.note(path),
			label: path => path === 'reinforcement.material' ? localize('library.barMaterial', "Bar material") : undefined,
			referenceLabel: (path, id) => path === 'profile.section' && id === '' ? localize('library.chooseSection', "Choose a section...") : undefined,
			editing: active => this.fieldEditing(active),
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
		// A field's help does not linger over other fields while the form scrolls.
		this._register(addDisposableListener(this.detail, EventType.SCROLL, () => this.hoverService.hideHover(true)));
	}

	protected override onWillLoadInput(): void {
		void this.refreshSections();
		const kind = this.kind;
		this.config = kind === 'materials' || kind === 'objects' ? libraryConfig(kind) : undefined;
		// A file shown again (back from the Section Designer) keeps its selected entry.
		this.selectedId = this.selections.get(this.resource?.toString() ?? '');
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
			const document = JSON.parse(text) as JsonObject;
			const materials = document.materials;
			const list = Array.isArray(materials) ? materials.filter(isObject) : [];
			this.materialsDoc = document;
			this.materialIds = {
				// Members are made of concrete, steel, masonry, ...; never of rebar or mortar alone.
				members: list.filter(m => m.category !== 'rebar' && m.category !== 'mortar').map(m => ({ id: String(m.id), category: String(m.category) })),
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
			// The project's concrete or rebar (`defaults`) follows its material's new ID.
			if (this.config?.listKey === 'materials' && this.document && this.selectedId !== undefined) {
				keepMaterialDefaults(this.document, this.selectedId, String(item.id));
			}
			this.selectedId = item.id as string;
		}
		if (item && path === 'concrete.fc') {
			this.followFc(item);
		}
		const renamed = !!item && this.config?.listKey === 'objects' && path !== 'name' && this.followName(item);
		this.changed(structural);
		if (!structural && (path === 'id' || path === 'name' || renamed)) {
			this.renderList();
			this.renderDetailTitle();
		}
		if (!structural && item && this.steelRatioForm && (path.startsWith('reinforcement.') || path.startsWith('profile.'))) {
			this.renderSteelRatio(this.steelRatioForm, item);
		}
	}

	/**
	 * A new object type's name ("New beam") follows its section while nobody has typed one:
	 * "Beam 250 × 450", "Column Ø500". Returns whether the name changed.
	 */
	private followName(item: JsonObject): boolean {
		const kind = humanize(String(item.kind ?? ''));
		const name = String(item.name ?? '');
		const generated = name === localize('library.newObjectName', "New {0}", kind.toLowerCase()) || name === this.generatedName;
		const next = this.describedName(item);
		if (!generated || !next || next === name) {
			return false;
		}
		item.name = this.generatedName = next;
		this.form.showValue('name', next);
		return true;
	}

	/** The name last made from the section (see followName); a typed name differs from it. */
	private generatedName: string | undefined;

	private describedName(item: JsonObject): string | undefined {
		const kind = humanize(String(item.kind ?? ''));
		const profile = item.profile;
		if (isObject(profile) && profile.shape === 'rectangle' && typeof profile.xDim === 'number' && typeof profile.yDim === 'number') {
			return `${kind} ${profile.xDim} × ${profile.yDim}`;
		}
		if (isObject(profile) && profile.shape === 'circle' && typeof profile.radius === 'number') {
			return `${kind} Ø${2 * profile.radius}`;
		}
		if (typeof item.thickness === 'number') {
			return `${kind} ${item.thickness} mm`;
		}
		return undefined;
	}

	/**
	 * A concrete's E and fr follow its f'c (BNBC 2020 Part 6 Sec 6.1.7.1, Eq. 6.6.3) while they
	 * are empty or still the code values of the previous f'c; values entered by the engineer
	 * (test results) stay, and the check flags them when they are far from the code's.
	 */
	private followFc(item: JsonObject): void {
		const concrete = isObject(item.concrete) ? item.concrete : undefined;
		const fc = typeof concrete?.fc === 'number' ? concrete.fc : undefined;
		const before = this.formFc;
		this.formFc = fc;
		if (!concrete || fc === undefined || fc <= 0) {
			return;
		}
		const mechanical = isObject(item.mechanical) ? item.mechanical : (item.mechanical = {});
		const old = before !== undefined && before > 0 ? concreteFromFc(before) : undefined;
		const next = concreteFromFc(fc);
		if (!old || follows(mechanical.E, old.E)) {
			mechanical.E = next.E;
			this.form.showValue('mechanical.E', next.E);
		}
		if (concrete.ft === undefined || (old && follows(concrete.ft, old.fr))) {
			concrete.ft = next.fr;
			this.form.showValue('concrete.ft', next.fr);
		}
		this.form.refreshPlaceholders();
	}

	/** Empty fields that follow another: E and fr of a concrete show the code value of its f'c. */
	private placeholder(path: string): string | undefined {
		const item = this.formItem ?? this.selected;
		const concrete = item && isObject(item.concrete) ? item.concrete : undefined;
		const fc = typeof concrete?.fc === 'number' && concrete.fc > 0 ? concrete.fc : undefined;
		if (this.config?.listKey !== 'materials' || fc === undefined) {
			return undefined;
		}
		const derived = concreteFromFc(fc);
		if (path === 'mechanical.E') {
			return localize('library.ePlaceholder', "{0} (4700 √f'c, BNBC Sec 6.1.7.1)", derived.E);
		}
		if (path === 'concrete.ft') {
			return localize('library.frPlaceholder', "{0} (0.62 √f'c, BNBC Eq. 6.6.3)", derived.fr);
		}
		return undefined;
	}

	/** A concrete's E and fr that still follow f'c say so, so they do not read as typed overrides. */
	private note(path: string): string | undefined {
		const item = this.formItem ?? this.selected;
		const concrete = item && isObject(item.concrete) ? item.concrete : undefined;
		const fc = typeof concrete?.fc === 'number' && concrete.fc > 0 ? concrete.fc : undefined;
		if (this.config?.listKey !== 'materials' || fc === undefined || !item) {
			return undefined;
		}
		const derived = concreteFromFc(fc);
		const mechanical = isObject(item.mechanical) ? item.mechanical : {};
		if (path === 'mechanical.E' && typeof mechanical.E === 'number' && follows(mechanical.E, derived.E)) {
			return localize('library.eFollows', "Code value 4700 √f'c (BNBC 2020 Part 6 Sec 6.1.7.1): follows f'c until you type another, e.g. from tests.");
		}
		if (path === 'concrete.ft' && typeof concrete!.ft === 'number' && follows(concrete!.ft, derived.fr)) {
			return localize('library.frFollows', "Code value 0.62 √f'c (BNBC 2020 Part 6 Eq. 6.6.3): follows f'c until you type another.");
		}
		return undefined;
	}

	/** Lists the designed sections (`04 Objects/sections/<id>.json`) for designed profiles. */
	private async refreshSections(): Promise<void> {
		const root = this.projectService.project?.root;
		let sections: string[] = [];
		if (root) {
			try {
				const folder = await this.fileService.resolve(joinPath(root, SECTIONS_FOLDER));
				sections = (folder.children ?? []).filter(c => !c.isDirectory && c.name.endsWith('.json')).map(c => c.name.slice(0, -'.json'.length)).sort();
			} catch {
				// No sections folder yet.
			}
		}
		const changed = sections.join('|') !== this.sections.join('|');
		this.sections = sections;
		if (changed && this.document && this.config?.listKey === 'objects') {
			this.renderDetail();
		}
	}

	// ───────────────────────────── items ─────────────────────────────

	/**
	 * A template with its references pointed at entries that exist in this project: an object
	 * kind's own template of a definition when it has one (a column's bars go round it), and a
	 * reinforcement's material a rebar.
	 */
	private template(key: string): JsonObject {
		const item = this.config?.listKey === 'objects' ? this.formItem ?? this.selected : undefined;
		const kind = item?.kind;
		const value = clone((TEMPLATES[`${key}:${String(kind)}`] ?? TEMPLATES[key] ?? {}) as JsonObject);
		this.fixReferences(value, /Reinforcement$/.test(key) ? 'reinforcement' : '');
		if (key === 'DesignedProfile') {
			// No made-up section id (it would be a problem at once): the first designed section, or
			// none yet, chosen or made with the buttons beside the field.
			value.section = this.sections[0] ?? '';
		}
		const area = grossArea(item?.profile);
		if (key === 'LinearReinforcement' && kind === 'column' && area !== undefined && Array.isArray(value.longitudinal)) {
			// The column's bars give it at least 1 % steel (the template's 8 Ø16 is 0.8 % of 450 × 450).
			const bars = columnBars(area, isObject(item?.profile) && item.profile.shape === 'circle');
			value.longitudinal = [{ position: 'perimeter', count: bars.count, dia: bars.dia }];
		}
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
			// A new type's bars and concrete are the project's (`defaults` of 03 Materials, as the
			// New Building wizard chose them), else the template's when the project has it.
			const preferred = this.projectChoice(entryPath, entry);
			if (allowed && preferred !== undefined && allowed.includes(preferred)) {
				value[key] = preferred;
			} else if (allowed && typeof entry === 'string' && !allowed.includes(entry) && allowed.length) {
				value[key] = allowed[0];
			}
		}
	}

	/** The project's material for a template's reference: its rebar for bars, its concrete for a concrete type's material. */
	private projectChoice(path: string, entry: JsonValue): string | undefined {
		if (this.config?.listKey !== 'objects' || !this.materialsDoc?.defaults) {
			return undefined;
		}
		if (path === 'reinforcement.material') {
			return projectMaterial(this.materialsDoc, 'rebar');
		}
		const concrete = path === 'material' && this.materialIds.members.some(m => m.id === entry && m.category === 'concrete');
		return concrete ? projectMaterial(this.materialsDoc, 'concrete') : undefined;
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

	/**
	 * Adds a new entry of the category or kind: its template (not a copy of the selected entry),
	 * a fresh id and name, and the cursor in its ID field.
	 */
	private addItem(variant: IVariant): void {
		if (!this.document || !this.config) {
			return;
		}
		this.flush();
		const materials = this.config.listKey === 'materials';
		this.formItem = { [this.config.discriminator]: variant.value };
		const item = this.template(variant.template);
		const base = materials ? NEW_MATERIAL_ID[variant.value] ?? 'MAT' : String(item.id ?? variant.value.toUpperCase());
		let n = 1;
		while (this.items.some(i => i.id === `${base}${n}`)) {
			n++;
		}
		item.id = `${base}${n}`;
		item.name = materials
			? localize('library.newMaterialName', "New {0}", humanize(variant.value).toLowerCase())
			: localize('library.newObjectName', "New {0}", humanize(variant.value).toLowerCase());
		delete item.source; // the template's source notes describe the default it was made from
		if (!materials) {
			// "Beam 250 × 450", following the section until a name is typed (see followName).
			item.name = this.generatedName = this.describedName(item) ?? String(item.name);
		}
		(this.document[this.config.listKey] as JsonValue[]).push(item);
		this.selectedId = item.id as string;
		this.changed(true);
		this.form.focus('id');
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

	/** The object types that use material `id` (as their material or their bars), from the saved or open objects file. */
	private async materialUsers(id: string): Promise<string[]> {
		const root = this.projectService.project?.root;
		const part = partById('objects');
		if (!root || !part?.mainFile) {
			return [];
		}
		try {
			const reference = await this.textModelService.createModelReference(joinPath(root, part.folder, part.mainFile));
			try {
				const objects = JSON.parse(reference.object.textEditorModel.getValue()).objects;
				return (Array.isArray(objects) ? objects : []).filter(isObject)
					.filter(o => o.material === id || (isObject(o.reinforcement) && o.reinforcement.material === id))
					.map(o => String(o.id));
			} finally {
				reference.dispose();
			}
		} catch {
			return [];
		}
	}

	/** The floor plan's members of object type `id`, counted by group ("12 columns"), from the saved or open floor plan. */
	private async typeUsers(id: string): Promise<string[]> {
		const root = this.projectService.project?.root;
		const part = partById('floorPlan');
		if (!root || !part?.mainFile) {
			return [];
		}
		try {
			const reference = await this.textModelService.createModelReference(joinPath(root, part.folder, part.mainFile));
			try {
				const plan = JSON.parse(reference.object.textEditorModel.getValue());
				if (!isObject(plan)) {
					return [];
				}
				return Object.entries(plan).flatMap(([group, list]) => {
					const count = Array.isArray(list) ? list.filter(m => isObject(m) && m.type === id).length : 0;
					return count ? [`${count} ${humanize(group).toLowerCase()}`] : [];
				});
			} finally {
				reference.dispose();
			}
		} catch {
			return [];
		}
	}

	private async deleteItem(): Promise<void> {
		const item = this.selected;
		if (!item || !this.document || !this.config) {
			return;
		}
		const materials = this.config.listKey === 'materials';
		const users = materials ? await this.materialUsers(String(item.id)) : await this.typeUsers(String(item.id));
		const name = String(item.name ?? item.id);
		const message = !users.length
			? localize('library.deleteConfirm', "Delete '{0}'?", name)
			: materials
				? localize('library.deleteUsedConfirm', "'{0}' is used by {1} object type(s). Delete it anyway?", name, users.length)
				: localize('library.deleteTypeUsedConfirm', "'{0}' is placed in the floor plan. Delete it anyway?", name);
		const detail = !users.length
			? localize('library.deleteDetail', "Anything that refers to {0} will show it as not defined. You can undo this with Ctrl+Z.", String(item.id))
			: materials
				? localize('library.deleteUsedDetail', "Used by: {0}. They will show {1} as not defined, and the analysis and design cannot run until each gets another material in 04 Objects. You can undo this with Ctrl+Z.", users.join(', '), String(item.id))
				: localize('library.deleteTypeUsedDetail', "Placed as {0} in 05 Floor Plan. They will show {1} as not defined, and the building model cannot be built until each gets another type. You can undo this with Ctrl+Z.", users.join(', '), String(item.id));
		// Something in use is kept unless Delete is chosen: Keep is the default (Enter) button.
		const { result: confirmed } = users.length
			? await this.dialogService.prompt<boolean>({
				type: 'warning',
				message,
				detail,
				buttons: [
					{ label: localize('library.keep', "&&Keep"), run: () => false },
					{ label: localize('library.deleteAnyway', "&&Delete Anyway"), run: () => true },
				],
				cancelButton: { label: localize('library.cancel', "Cancel"), run: () => false },
			})
			: { result: (await this.dialogService.confirm({ message, detail, primaryButton: localize('library.delete', "&&Delete") })).confirmed };
		if (!confirmed || this.selected !== item || !this.document) {
			return;
		}
		const list = this.document[this.config.listKey] as JsonValue[];
		const index = list.indexOf(item);
		list.splice(index, 1);
		if (this.config.listKey === 'materials') {
			keepMaterialDefaults(this.document); // a deleted default is no longer the project's
		}
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
		if (this.config.listKey === 'objects') {
			// The stiffness modifiers and design overwrites the new kind still has.
			for (const key of ['modifiers', 'designOverwrites']) {
				if (item[key] !== undefined) {
					replacement[key] = item[key];
				}
			}
			pruneForKind(replacement);
		}
		const list = this.document[this.config.listKey] as JsonValue[];
		list[list.indexOf(item)] = replacement;
		if (this.config.listKey === 'materials') {
			keepMaterialDefaults(this.document); // a default that changed category is no longer the project's
		}
		this.changed(true);
	}

	// ───────────────────────────── references and rules ─────────────────────────────

	private references(path: string): readonly string[] | undefined {
		if (this.config?.listKey === 'materials') {
			return path === 'masonry.mortar' ? this.items.filter(i => i.category === 'mortar').map(i => String(i.id)) : undefined;
		}
		switch (path) {
			case 'material': {
				// Only materials the kind can be made of (no brick slab, no steel wall).
				const kind = String((this.formItem ?? this.selected)?.kind ?? '');
				const allowed = KIND_MATERIALS[kind];
				return this.materialIds.members.filter(m => !allowed || allowed.includes(m.category)).map(m => m.id);
			}
			case 'reinforcement.material': return this.materialIds.rebar;
			case 'profile.section': return ['', ...this.sections];
			case 'pile': return this.items.filter(i => i.kind === 'pile').map(i => String(i.id));
		}
		return undefined;
	}

	/** Material property groups follow the category, mirroring the Python model's rules. */
	private fieldMode(path: string): 'hidden' | 'required' | undefined {
		const item = this.selected;
		if (this.config?.listKey === 'objects' && item && path === 'connection' && item.connection === undefined) {
			// The simple shear and gusset connections are steel members' (BNBC 2020 Part 6 Sec 10.10).
			const material = this.materialIds.members.find(m => m.id === item.material);
			return material?.category === 'steel' ? undefined : 'hidden';
		}
		if (this.config?.listKey !== 'materials' || !item) {
			return undefined;
		}
		const category = item.category;
		const group = { concrete: 'concrete', rebar: 'steel', steel: 'steel', masonry: 'masonry', timber: 'timber' }[String(category)];
		if (path === 'concrete' || path === 'steel' || path === 'masonry' || path === 'timber') {
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
		if (this.resource && this.selectedId) {
			this.selections.set(this.resource.toString(), this.selectedId);
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
		this.formFc = isObject(item.concrete) && typeof item.concrete.fc === 'number' ? item.concrete.fc : undefined;
		if (config.listKey === 'objects' && this.generatedName !== item.name) {
			this.generatedName = undefined; // another entry, or a name typed meanwhile
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
			this.form.render(form, schema, item, [config.discriminator, 'modifiers', 'designOverwrites']);
		}
		if (config.listKey === 'objects' && isObject(item.profile) && item.profile.shape === 'designed') {
			void this.renderDesignedSection(form, item);
		}
		if (config.listKey === 'objects') {
			const help = KIND_HELP[String(item.kind)];
			if (help) {
				append(typeRow, $('.form-note', undefined, help));
			}
			this.steelRatioForm = form;
			this.renderSteelRatio(form, item);
		}
		if (config.listKey === 'objects') {
			// Stiffness modifiers and design overwrites of the type (the members inherit them).
			renderModifiers(form, modifiersView('type', [objectTypeTarget(item, this.materialsDoc)], readCodeStiffness(undefined, undefined)), this.detailDisposables, {
				contextViewService: this.contextViewService,
				apply: (group, key, value) => {
					setObjectTypeField(item, group, key, value);
					this.changed(true);
				},
				reset: group => {
					resetObjectTypeGroup(item, group);
					this.changed(true);
				},
			});
		}
	}

	/**
	 * A column's longitudinal steel ratio ρ = As / Ag, read-only after its bars, with a warning
	 * below 1 % (the code's minimum) or above 4 % (crowded laps).
	 */
	private renderSteelRatio(form: HTMLElement, item: JsonObject): void {
		this.steelRatioRow?.remove();
		this.steelRatioRow = undefined;
		const area = grossArea(item.profile);
		if (item.kind !== 'column' || area === undefined || !isObject(item.reinforcement)) {
			return;
		}
		const rho = longitudinalArea(item.reinforcement) / area;
		const row = this.steelRatioRow = $('.form-field.library-steel-ratio');
		// After the bars it is worked out from (before the stiffness modifiers).
		const bars = this.form.row('reinforcement.cover')?.closest('.form-group');
		if (bars) {
			bars.after(row);
		} else {
			form.appendChild(row);
		}
		append(append(row, $('.form-label-cell')), $('span.form-label', undefined, localize('library.steelRatio', "Steel ratio ρ")));
		const control = append(row, $('.form-control', { 'aria-live': 'polite' }));
		append(control, $('span', undefined, `${(rho * 100).toFixed(2)} %`));
		const warning = rho < COLUMN_RHO_MIN
			? localize('library.rhoLow', "Below the 1 % minimum of a column (ACI 318 10.6.1.1, as BNBC 2020 Part 6 Chapter 6): add bars or use larger ones.")
			: rho > COLUMN_RHO_PRACTICAL
				? localize('library.rhoHigh', "Above 4 %: the lapped bars crowd the section (ACI 318 R10.6.1.1); a larger column is usually better.")
				: undefined;
		if (warning) {
			const warn = append(row, $('.library-problem.library-designed-warning'));
			append(warn, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(warn, $('span', undefined, warning));
		}
	}

	/**
	 * A designed profile: New/Edit buttons for its section (Section Designer), and the section's
	 * own material and bars, read-only, with a warning where the object type says otherwise.
	 */
	private async renderDesignedSection(form: HTMLElement, item: JsonObject): Promise<void> {
		const profile = item.profile as JsonObject;
		const sectionId = typeof profile.section === 'string' ? profile.section : undefined;
		const root = this.projectService.project?.root;
		const store = this.detailDisposables;
		const row = $('.form-field.library-designed-section');
		// Right below the section it edits, not at the end of the form.
		const field = this.form.row('profile.section');
		if (field) {
			field.after(row);
		} else {
			form.appendChild(row);
		}
		append(row, $('.form-label-cell'));
		const control = append(row, $('.form-control.library-designed-actions'));
		const exists = !!sectionId && this.sections.includes(sectionId);
		if (exists && root) {
			const edit = store.add(new Button(control, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			edit.label = `$(${Codicon.edit.id}) ${localize('library.editSection', "Edit {0}", sectionId)}`;
			store.add(edit.onDidClick(() => void this.editorService.openEditor({ resource: joinPath(root, SECTIONS_FOLDER, `${sectionId}.json`), options: { pinned: true } })));
		}
		const create = store.add(new Button(control, { ...defaultButtonStyles, secondary: exists, supportIcons: true }));
		create.label = `$(${Codicon.add.id}) ${localize('library.newSection', "New Section...")}`;
		store.add(create.onDidClick(async () => {
			let n = 1;
			while (this.sections.includes(`${item.id}-SD${n}`)) {
				n++;
			}
			const id = `${item.id}-SD${n}`;
			// The type names its section first (opening the Section Designer hides this editor), on
			// the entry as the document holds it now: the form may have been rebuilt since.
			const target = this.items.find(i => i.id === item.id);
			if (!target || !isObject(target.profile)) {
				return;
			}
			target.profile.section = id;
			this.flush();
			this.changed(true);
			await this.commands.executeCommand('saengine.section.new', id);
			await this.refreshSections();
		}));
		if (!exists || !root) {
			return;
		}
		let text: string;
		try {
			text = (await this.fileService.readFile(joinPath(root, SECTIONS_FOLDER, `${sectionId}.json`))).value.toString();
		} catch {
			return;
		}
		const parsed = parseSection(text);
		if (!parsed.ok || !row.isConnected) {
			return;
		}
		const section = parsed.section;
		const materials = [...new Set(section.regions.map(r => r.material))];
		const bars = new Map<number, number>();
		for (const bar of section.bars) {
			bars.set(bar.dia, (bars.get(bar.dia) ?? 0) + 1);
		}
		const barText = section.bars.length ? [...bars].map(([dia, count]) => `${count} Ø${dia}`).join(' + ') : localize('library.noBars', "none");
		const info = $('.form-field.library-designed-info');
		row.after(info);
		append(append(info, $('.form-label-cell')), $('span.form-label', undefined, localize('library.sectionHas', "From the section")));
		append(info, $('.form-control', undefined, localize('library.sectionValues', "{0}; bars {1}{2}", materials.join(', '), barText, section.rebar ? ` (${section.rebar})` : '')));
		// The section is what is analysed and designed: a type saying otherwise is fixed in one click.
		const fixes: { readonly text: string; readonly label: string; readonly run: (target: JsonObject) => void }[] = [];
		const sectionMaterial = materials.length === 1 ? materials[0] : undefined;
		if (typeof item.material === 'string' && !materials.includes(item.material)) {
			fixes.push({
				text: localize('library.sectionMaterial', "The type's material {0} is not the section's {1}: make them the same.", item.material, materials.join(', ')),
				label: sectionMaterial ? localize('library.useSectionMaterial', "Use {0}", sectionMaterial) : '',
				run: target => target.material = sectionMaterial!,
			});
		}
		if (isObject(item.reinforcement) && section.bars.length) {
			fixes.push({
				text: localize('library.sectionBars', "The section has its own bars ({0}); the type's Reinforcement describes others: turn it off or match it.", barText),
				label: localize('library.useSectionBars', "Use the Section's Bars"),
				run: target => delete target.reinforcement,
			});
		}
		let after: HTMLElement = info;
		for (const fix of fixes) {
			const warn = $('.library-problem.library-designed-warning');
			after.after(warn);
			after = warn;
			append(warn, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(warn, $('span', undefined, fix.text));
			if (fix.label) {
				const button = store.add(new Button(append(warn, $('span.library-designed-fix')), { ...defaultButtonStyles, secondary: true }));
				button.label = fix.label;
				store.add(button.onDidClick(() => {
					const target = this.items.find(i => i.id === item.id);
					if (target) {
						fix.run(target);
						this.changed(true);
					}
				}));
			}
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
