/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/structureModeler.css';
import '../../saengineLibrary/browser/media/libraryEditor.css';
import '../../saengineLibrary/browser/media/modelEditors.css';
import type { ModelerEntity, ModelerHit, ModelerTheme, ModelerView, ModelPoint, StructureModeler } from '@saengine/fem-viewer';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isKeyboardEvent } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { hasKey } from '../../../../base/common/types.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IQuickInputService, IQuickPickItem, IQuickPickSeparator } from '../../../../platform/quickinput/common/quickInput.js';
import type { IStructureEdit, IStructureGeometry, IStructureScriptResult, StructureGeometryResult } from '../../../../platform/saengine/common/femSolver.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { chartsBlue, chartsGreen, chartsLines, chartsOrange, chartsPurple, chartsYellow } from '../../../../platform/theme/common/colors/chartsColors.js';
import { editorBackground, editorForeground } from '../../../../platform/theme/common/colors/editorColors.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { IOutputService } from '../../../services/output/common/output.js';
import { IMPORT_SCHEMA, SCRIPT_TEMPLATE, SHAPE_SCHEMA, STRUCTURE_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { loadViewerModule } from '../../saengineFem/browser/viewerModule.js';
import { formatPropertyValue, schemaUnit } from '../../saengineModel/browser/propertySheetView.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { humanize, ISchemaFormContext, JsonObject, SchemaForm } from '../../saengineLibrary/browser/schemaForm.js';
import { addArea, addBlock, addMember, addSupport, copyElements, divideMember, EditResult, isStructure, mirrorElements, moveElements, parseOffset, removeElements } from './structureEdits.js';
import { gridGeometry, Json, list, modelerScene, typeKinds } from './structureGeometry.js';
import { CODES_CODED_GEOMETRY_COMMAND, CODES_TEMPLATES_COMMAND, groupPresets, IStructurePreset, readStructurePresets } from '../../saengineLibrary/common/packageTemplates.js';

type Tool = 'select' | 'member' | 'area' | 'block' | 'support' | 'move' | 'copy' | 'mirror' | 'divide' | 'delete';

const TOOLS: readonly { readonly tool: Tool; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ tool: 'select', label: localize('modeler.select', "Select"), icon: Codicon.inspect },
	{ tool: 'member', label: localize('modeler.member', "Member"), icon: Codicon.dash },
	{ tool: 'area', label: localize('modeler.area', "Area"), icon: Codicon.symbolArray },
	{ tool: 'block', label: localize('modeler.block', "Block"), icon: Codicon.package },
	{ tool: 'support', label: localize('modeler.support', "Support"), icon: Codicon.pinned },
	{ tool: 'move', label: localize('modeler.move', "Move"), icon: Codicon.move },
	{ tool: 'copy', label: localize('modeler.copy', "Copy"), icon: Codicon.copy },
	{ tool: 'mirror', label: localize('modeler.mirror', "Mirror"), icon: Codicon.mirror },
	{ tool: 'divide', label: localize('modeler.divide', "Divide"), icon: Codicon.splitHorizontal },
	{ tool: 'delete', label: localize('modeler.delete', "Delete"), icon: Codicon.trash },
];

const VIEWS: readonly { readonly view: ModelerView; readonly label: string }[] = [
	{ view: '3d', label: localize('modeler.view3d', "3D") },
	{ view: 'top', label: localize('modeler.viewTop', "Top") },
	{ view: 'front', label: localize('modeler.viewFront', "Front") },
	{ view: 'side', label: localize('modeler.viewSide', "Side") },
];

/** Object type kinds each drawing tool places. */
const TOOL_KINDS: { readonly [tool in Tool]?: readonly string[] } = {
	member: ['beam', 'column', 'brace'],
	area: ['slab', 'wall'],
	block: ['solid'],
};

const SUPPORT_FIXITIES = ['fixed', 'pinned'] as const;

/** The structure schema's definition of each selectable kind (for the units of its values). */
const ENTITY_DEFINITIONS = { member: 'Member', area: 'Area', block: 'Block', support: 'Support' } as const;

/** What the side panel adds to the model: a parametric shape, or the elements of a file. */
type Source = { readonly kind: 'shape' } | { readonly kind: 'import'; readonly file: URI };

const MEMBER_KINDS = ['beam', 'column', 'brace'];

/** Object type kinds offered by each type field of the Generate and Import forms. */
const FIELD_KINDS: { readonly [path: string]: readonly string[] } = {
	'shape.memberType': MEMBER_KINDS,
	'shape.diagonalType': MEMBER_KINDS,
	'shape.webType': MEMBER_KINDS,
	'shape.edgeType': MEMBER_KINDS,
	'shape.panelType': ['slab', 'wall'],
	'options.memberType': ['beam', 'brace'],
	'options.columnType': ['column'],
	'options.slabType': ['slab'],
	'options.wallType': ['wall'],
};

/** Below this editor width [px] the toolbar keeps the tools and moves the rest to its "..." menu. */
const COMPACT_WIDTH = 950;
/** Below this width [px] the editing tools and the work level picker go to "..." too. */
const NARROW_WIDTH = 700;

/** Scripts live in this folder beside `structure.json`. */
const SCRIPTS_FOLDER = 'scripts';

/** Output channel of model scripts (registered by the contribution). */
export const SCRIPT_OUTPUT_CHANNEL_ID = 'saengine.structureScripts';

function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value));
}

/** The elements of `doc` with these ids, as the modeller selects them. */
function entitiesOf(doc: Json, ids: readonly string[]): ModelerEntity[] {
	const kindOf = (id: string): ModelerEntity['kind'] => list(doc.members).some(m => m.id === id) ? 'member' : list(doc.areas).some(a => a.id === id) ? 'area' : list(doc.blocks).some(b => b.id === id) ? 'block' : 'support';
	return ids.map(id => ({ kind: kindOf(id), id }));
}

function hint(tool: Tool, picked: number, selected: number): string {
	switch (tool) {
		case 'select': return localize('hint.select', "Click an element to select it; Shift+click adds to the selection. Drag to orbit, right-drag to pan, wheel to zoom.");
		case 'member': return picked ? localize('hint.memberEnd', "Click the end of the member (Esc stops the chain).") : localize('hint.memberStart', "Click the start of the member: a grid point, a member end or a free point on the work level.");
		case 'area': return picked < 3 ? localize('hint.areaCorner', "Click the corners of the area in order ({0} so far).", picked) : localize('hint.areaClose', "Click the first corner, press Enter or right-click to finish the area.");
		case 'block': return picked < 3 ? localize('hint.blockCorner', "Click the corners of the block's face in order ({0} so far); it grows by the thickness beside to the side its corners turn counter-clockwise for.", picked) : localize('hint.blockClose', "Click the first corner, press Enter or right-click to finish the block.");
		case 'support': return localize('hint.support', "Click a member end or area corner to support it.");
		case 'move':
		case 'copy':
			return !selected ? localize('hint.selectFirst', "Click what to {0} (or select it first).", tool === 'move' ? localize('hint.moveVerb', "move") : localize('hint.copyVerb', "copy"))
				: picked ? localize('hint.target', "Click the target point.")
					: localize('hint.base', "Click a base point, or type the offset \"dx, dy, dz\"{0} and press Enter.", tool === 'copy' ? localize('hint.count', " (add \", n\" for n copies)") : '');
		case 'mirror': return !selected ? localize('hint.mirrorSelect', "Select what to mirror first.") : picked ? localize('hint.mirrorSecond', "Click the second point of the mirror line (in plan).") : localize('hint.mirrorFirst', "Click the first point of the mirror line (in plan).");
		case 'divide': return localize('hint.divide', "Click a member to divide it into the number of parts typed beside.");
		case 'delete': return localize('hint.delete', "Click an element to delete it, or press Delete to remove the selection.");
	}
}

/**
 * The 3D modeller of a special structure's structural model (`05 Structural Model/structure.json`):
 * draw members, areas and supports on the grid systems, and move, copy, mirror, divide or delete
 * them. Every change is one undoable edit of the file; the form stays available beside.
 */
export class StructureModelerEditor extends EditorPane {

	static readonly ID = LibraryEditorInput.STRUCTURE_MODELER_ID;

	private frame!: EditorFrame;
	private root!: HTMLElement;
	private viewport!: HTMLElement;
	private message!: HTMLElement;
	private typePicker!: SelectBox;
	private levelPicker!: SelectBox;
	private valueBox!: InputBox;
	private typeGroup!: HTMLElement;
	private valueGroup!: HTMLElement;
	private readonly toolActions = new Map<Tool, Action>();
	private readonly viewButtons = new Map<ModelerView, HTMLButtonElement>();
	private view: ModelerView = '3d';
	/** A narrow editor keeps the drawing tools as buttons and moves the rest to "...". */
	private compact: boolean | undefined;
	/** A very narrow editor also moves the editing tools and the work level picker to "...". */
	private narrow = false;
	private readonly levelAction = this._register(new Action('saengine.structure.level', localize('modeler.levelMenu', "Work Level..."), undefined, true, () => this.pickLevel()));
	private readonly undoAction = this._register(new Action('saengine.structure.undo', localize('modeler.undo', "Undo"), ThemeIcon.asClassName(Codicon.discard), false, () => this.undoRedo(false)));
	private readonly redoAction = this._register(new Action('saengine.structure.redo', localize('modeler.redo', "Redo"), ThemeIcon.asClassName(Codicon.redo), false, () => this.undoRedo(true)));
	private readonly fitAction = this._register(new Action('saengine.structure.fit', localize('modeler.fit', "Zoom to Fit"), ThemeIcon.asClassName(Codicon.screenFull), true, async () => this.modeler?.fit()));
	private readonly generateAction = this._register(new Action('saengine.structure.generate', localize('modeler.generateTitle', "Add a parametric shape: space truss, plane truss, arch, dome, barrel vault or cable net"), ThemeIcon.asClassName(Codicon.symbolStructure), true, async () => this.openShape()));
	private readonly importAction = this._register(new Action('saengine.structure.import', localize('modeler.importTitle', "Add the members and surfaces of a DXF, DWG, IFC or Rhino (.3dm) file"), ThemeIcon.asClassName(Codicon.cloudDownload), true, () => this.openImport()));
	private readonly scriptAction = this._register(new Action('saengine.structure.script', localize('modeler.scriptTitle', "Run a Python script that builds the model, or start a new one"), ThemeIcon.asClassName(Codicon.symbolMethod), true, () => this.pickScript()));
	private readonly formAction = this._register(new Action('saengine.structure.form', localize('modeler.form', "Edit Grids and Values"), undefined, true, async () => this.openForm()));
	private readonly generateMenuAction = this._register(new Action('saengine.structure.generateMenu', localize('modeler.generateMenu', "Generate Shape..."), undefined, true, async () => this.openShape()));
	private readonly importMenuAction = this._register(new Action('saengine.structure.importMenu', localize('modeler.importMenu', "Import Geometry..."), undefined, true, () => this.openImport()));
	private readonly scriptMenuAction = this._register(new Action('saengine.structure.scriptMenu', localize('modeler.scriptMenu', "Run Script..."), undefined, true, () => this.pickScript()));

	private modeler: StructureModeler | undefined;
	private readonly modelerDisposable = this._register(new MutableDisposable());
	private readonly inputDisposables = this._register(new DisposableStore());
	/** "Get more structure templates...": the Generate panel's link to the Packages page. */
	private panelMore!: HTMLElement;
	/** The Generate panel's template picker (the presets of the structure templates installed). */
	private panelPresets!: HTMLElement;
	private presetSelect!: HTMLSelectElement;
	private presets: IStructurePreset[] = [];
	/** The coded template being generated (round M5), with its form; undefined for a built-in shape. */
	private coded: { readonly preset: IStructurePreset; readonly schema: IJSONSchema; readonly value: JsonObject; readonly form: SchemaForm } | undefined;
	private readonly codedForm = this._register(new DisposableStore());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.render(), 50));

	private model: ITextModel | undefined;
	private objects: ITextModel | undefined;
	private doc: Json | undefined;
	private kinds = new Map<string, string>();
	private levels: { label: string; z: number }[] = [];
	private level: number | undefined;
	private tool: Tool = 'select';
	private readonly types = new Map<Tool, string>();
	private typeOptions: string[] = [];
	private points: ModelPoint[] = [];
	private selection: ModelerEntity[] = [];
	private hover: ModelerHit = {};
	private notice: string | undefined;
	private writing = false;

	// The properties panel shows the selection, or a shape or a file to add, its form and its
	// preview ("ghost").
	private details!: HTMLElement;
	private panel!: HTMLElement;
	private panelTitle!: HTMLElement;
	private panelForm!: HTMLElement;
	private panelStatus!: HTMLElement;
	private insertButton!: Button;
	private shapeForm!: SchemaForm;
	private importForm!: SchemaForm;
	private source: Source | undefined;
	private shapeValue: JsonObject | undefined;
	private importValue: JsonObject | undefined;
	private ghost: IStructureGeometry | undefined;
	private ghostProblems: readonly string[] = [];
	private ghostRequest = 0;
	private fitGhost = false;
	private readonly ghostScheduler = this._register(new RunOnceScheduler(() => void this.refreshGhost(), 250));
	private lastScript: URI | undefined;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IEditorService private readonly editorService: IEditorService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IFileService private readonly fileService: IFileService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IOutputService private readonly outputService: IOutputService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
	) {
		super(StructureModelerEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: StructureModelerEditor.ID,
			ariaLabel: localize('modeler.toolbar', "Structural Model"),
			properties: { title: localize('modeler.properties', "Properties") },
		}));
		this.root = frame.element;
		this.root.classList.add('saengine-structure-modeler');
		this.root.tabIndex = -1;

		// The view direction: a segmented control, the only text in the toolbar.
		const views = append(frame.titleSlot, $('.sa-segmented', { role: 'tablist', 'aria-label': localize('modeler.viewsAria', "View direction") }));
		for (const { view, label } of VIEWS) {
			const button = append(views, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.setView(view)));
			this.viewButtons.set(view, button);
		}
		this.setView(this.view);

		for (const { tool, label, icon } of TOOLS) {
			this.toolActions.set(tool, this._register(new Action(`saengine.structure.tool.${tool}`, label, ThemeIcon.asClassName(icon), true, async () => this.setTool(tool))));
		}

		// Inline controls: the work level always, the type and the typed value of the active tool.
		const levels = append(frame.controlsSlot, $('.modeler-inline.modeler-level'));
		append(levels, $('span.sa-frame-label.modeler-level-label', undefined, localize('modeler.level', "Work level")));
		this.levelPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('modeler.levelAria', "Level free points are drawn on") }));
		this.levelPicker.render(append(levels, $('.modeler-select.level')));
		this._register(this.levelPicker.onDidSelect(({ index }) => {
			this.level = this.levels[index - 1]?.z;
			this.modeler?.setWorkPlane(this.level);
		}));

		this.typeGroup = append(frame.controlsSlot, $('.modeler-inline'));
		append(this.typeGroup, $('span.sa-frame-label', undefined, localize('modeler.type', "Type")));
		this.typePicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('modeler.typeAria', "Object type to draw") }));
		this.typePicker.render(append(this.typeGroup, $('.modeler-select.type')));
		this._register(this.typePicker.onDidSelect(({ index }) => this.types.set(this.tool, this.typeOptions[index])));

		this.valueGroup = append(frame.controlsSlot, $('.modeler-inline.value'));
		this.valueBox = this._register(new InputBox(this.valueGroup, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles }));
		this._register(addDisposableListener(this.valueBox.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				e.stopPropagation();
				this.applyTyped();
			}
		}));

		this.viewport = append(frame.main, $('.modeler-viewport'));
		this.message = append(this.viewport, $('.modeler-message'));
		this._register(frame.onDidLayoutMain(() => this.modeler?.layout()));

		// The properties panel: the selection, or the shape or file being added.
		const properties = frame.properties!;
		this.details = append(properties, $('.modeler-details'));
		this.panel = append(properties, $('.modeler-panel.saengine-library-editor'));
		this.panelTitle = append(this.panel, $('h3.modeler-panel-title'));
		// The structure templates installed (Packages page), grouped by package: one fills the form.
		this.panelPresets = append(this.panel, $('.modeler-panel-presets.hidden'));
		this.presetSelect = append(this.panelPresets, $('select.modeler-panel-preset', { 'aria-label': localize('modeler.presetLabel', "Start from a structure template") })) as HTMLSelectElement;
		this._register(addDisposableListener(this.presetSelect, EventType.CHANGE, () => this.applyPreset(this.presetSelect.value)));
		this.panelForm = append(this.panel, $('.modeler-panel-form.library-form'));
		this.panelStatus = append(this.panel, $('.modeler-panel-status'));
		const buttons = append(this.panel, $('.modeler-panel-buttons'));
		this.insertButton = this._register(new Button(buttons, { ...defaultButtonStyles }));
		this.insertButton.label = localize('modeler.insert', "Insert");
		this._register(this.insertButton.onDidClick(() => void this.insertGhost()));
		// Structure templates are installed on the Packages page; the panel only links to it.
		this.panelMore = append(this.panel, $('a.modeler-panel-more.hidden', { href: '#', role: 'button' }, localize('modeler.morePresets', "Get more structure templates...")));
		this._register(addDisposableListener(this.panelMore, EventType.CLICK, e => {
			e.preventDefault();
			void this.commandService.executeCommand('saengine.packages.show', { tab: 'browse', kind: 'structureTemplate' });
		}));
		const cancel = this._register(new Button(buttons, { ...defaultButtonStyles, secondary: true }));
		cancel.label = localize('modeler.cancel', "Cancel");
		this._register(cancel.onDidClick(() => this.closePanel()));
		this.shapeForm = this._register(this.instantiationService.createInstance(SchemaForm, this.formContext(SHAPE_SCHEMA)));
		this.importForm = this._register(this.instantiationService.createInstance(SchemaForm, this.formContext(IMPORT_SCHEMA)));

		this._register(addDisposableListener(this.root, EventType.KEY_DOWN, e => this.onKey(e)));
		this.setActions();
		this.updateToolbar();
	}

	/**
	 * Tools, then adding geometry, undo and redo, and the view; the form and the rest in "...".
	 * A narrow editor keeps the tools, Fit and the panel toggle; the rest goes to "...".
	 */
	private setActions(): void {
		const tools = (names: readonly Tool[]) => names.map(name => this.toolActions.get(name)!);
		const compact = !!this.compact;
		const narrow = this.narrow;
		const primary: IAction[] = [
			...tools(['select']),
			new Separator(),
			...tools(['member', 'area', 'block', 'support']),
			new Separator(),
			...(narrow ? [] : [...tools(['move', 'copy', 'mirror', 'divide', 'delete']), new Separator()]),
			...(compact ? [] : [this.generateAction, this.importAction, this.scriptAction, new Separator(), this.undoAction, this.redoAction, new Separator()]),
			this.fitAction, this.frame.togglePropertiesAction,
		];
		const secondary: IAction[] = [
			this.formAction,
			new Separator(),
			this.generateMenuAction, this.importMenuAction, this.scriptMenuAction,
			...(compact ? [new Separator(), this.undoAction, this.redoAction] : []),
			...(narrow ? [new Separator(), ...tools(['move', 'copy', 'mirror', 'divide', 'delete'])] : []),
			new Separator(),
			this.levelAction,
		];
		this.frame.setActions(primary, secondary);
	}

	private setView(view: ModelerView): void {
		this.view = view;
		for (const [id, button] of this.viewButtons) {
			button.classList.toggle('active', id === view);
			button.setAttribute('aria-selected', String(id === view));
		}
		void this.modeler?.setView(view);
	}

	/** The level free points are drawn on, from a quick pick (the toolbar's picker in a narrow editor). */
	private async pickLevel(): Promise<void> {
		const items: (IQuickPickItem & { readonly z: number | undefined })[] = [
			{ label: localize('modeler.snapOnly', "None (snap points only)"), z: undefined },
			...this.levels.map(l => ({ label: `${l.label} (${l.z} mm)`, z: l.z })),
		];
		const pick = await this.quickInputService.pick(items, { placeHolder: localize('modeler.levelPick', "Level free points are drawn on"), activeItem: items.find(i => i.z === this.level) });
		if (pick) {
			this.level = pick.z;
			this.levelPicker.select(Math.max(0, this.levels.findIndex(l => l.z === pick.z) + 1));
			this.modeler?.setWorkPlane(this.level);
		}
	}

	private async undoRedo(redo: boolean): Promise<void> {
		const resource = (this.input as LibraryEditorInput | undefined)?.resource;
		if (resource) {
			await (redo ? this.undoRedoService.redo(resource) : this.undoRedoService.undo(resource));
		}
		this.updateToolbar();
	}

	override async setInput(input: LibraryEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.points = [];
		this.selection = [];
		this.closePanel();
		// The project root is two levels up (05 Structural Model/structure.json); the project itself
		// may not be detected yet when the editor is restored at startup.
		const objectsPart = partById('objects')!;
		try {
			const references = await Promise.all([
				this.textModelService.createModelReference(input.resource),
				this.textModelService.createModelReference(joinPath(dirname(dirname(input.resource)), objectsPart.folder, objectsPart.mainFile!)),
			]);
			if (token.isCancellationRequested || this.input !== input) {
				references.forEach(r => r.dispose());
				return;
			}
			references.forEach(r => this.inputDisposables.add(r));
			[this.model, this.objects] = references.map(r => r.object.textEditorModel);
		} catch (error) {
			this.showMessage(localize('modeler.readFailed', "The structural model could not be read: {0}", String(error)));
			return;
		}
		for (const model of [this.model, this.objects]) {
			if (model) {
				this.inputDisposables.add(model.onDidChangeContent(() => {
					if (!this.writing) {
						this.notice = undefined; // undo, redo or another editor changed it
					}
					this.renderScheduler.schedule();
				}));
			}
		}
		await this.ensureModeler();
		this.render();
	}

	override clearInput(): void {
		this.inputDisposables.clear();
		this.model = undefined;
		this.objects = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		const compact = dimension.width < COMPACT_WIDTH;
		const narrow = dimension.width < NARROW_WIDTH;
		if (compact !== this.compact || narrow !== this.narrow) {
			this.compact = compact;
			this.narrow = narrow;
			this.root.classList.toggle('compact', compact);
			this.root.classList.toggle('narrow', narrow);
			this.setActions();
		}
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.root.focus();
	}

	override updateStyles(): void {
		super.updateStyles();
		this.modeler?.setTheme(this.computeTheme());
	}

	private async ensureModeler(): Promise<void> {
		if (this.modeler) {
			return;
		}
		try {
			const { createStructureModeler } = await loadViewerModule();
			if (this.modeler) {
				return;
			}
			const modeler = createStructureModeler(this.viewport, {
				theme: this.computeTheme(),
				onPointerMove: hit => this.onHover(hit),
				onClick: (hit, modifiers) => this.onClick(hit, modifiers.shift, modifiers.secondary),
			});
			this.modeler = modeler;
			this.modelerDisposable.value = toDisposable(() => {
				modeler.dispose();
				this.modeler = undefined;
			});
			modeler.layout();
		} catch (error) {
			this.showMessage(localize('modeler.loadFailed', "The 3D view could not be loaded: {0}", String(error)));
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		let parsed: unknown;
		try {
			parsed = this.model ? JSON.parse(this.model.getValue()) : undefined;
		} catch {
			parsed = undefined;
		}
		if (!isStructure(parsed)) {
			this.doc = undefined;
			this.showMessage(localize('modeler.invalid', "The structural model has errors the 3D view cannot show. Fix them in Grids & Values (the form) or the JSON."));
			return;
		}
		this.showMessage(undefined);
		this.doc = parsed;
		let objects: unknown;
		try {
			objects = this.objects ? JSON.parse(this.objects.getValue()) : undefined;
		} catch {
			objects = undefined;
		}
		this.kinds = typeKinds(objects);
		// Drop selected elements that no longer exist (deleted, or undone).
		const exists = (e: ModelerEntity) => list(parsed[e.kind === 'member' ? 'members' : e.kind === 'area' ? 'areas' : e.kind === 'block' ? 'blocks' : 'supports']).some(x => x.id === e.id);
		this.selection = this.selection.filter(exists);

		const levels = gridGeometry(parsed.grids).levels;
		if (JSON.stringify(levels) !== JSON.stringify(this.levels)) {
			this.levels = levels;
			if (this.level === undefined || !levels.some(l => l.z === this.level)) {
				this.level = levels[0]?.z;
			}
			this.levelPicker.setOptions([
				{ text: localize('modeler.snapOnly', "None (snap points only)") },
				...levels.map(l => ({ text: `${l.label} (${l.z} mm)` })),
			], Math.max(0, levels.findIndex(l => l.z === this.level) + 1));
		}
		this.modeler?.setWorkPlane(this.level);
		this.modeler?.setScene(modelerScene(parsed, this.kinds));
		this.modeler?.setSelection(this.selection);
		this.updateToolbar();
		this.updatePreview();
		this.renderDetails();
	}

	private updateToolbar(): void {
		for (const [tool, action] of this.toolActions) {
			action.checked = tool === this.tool;
		}
		const resource = (this.input as LibraryEditorInput | undefined)?.resource;
		this.undoAction.enabled = !!resource && this.undoRedoService.canUndo(resource);
		this.redoAction.enabled = !!resource && this.undoRedoService.canRedo(resource);
		const kinds = TOOL_KINDS[this.tool];
		this.typeGroup.classList.toggle('hidden', !kinds && this.tool !== 'support');
		if (kinds) {
			this.typeOptions = [...this.kinds].filter(([, kind]) => kinds.includes(kind)).map(([id]) => id);
			const chosen = this.types.get(this.tool);
			const index = chosen ? this.typeOptions.indexOf(chosen) : -1;
			this.typePicker.setOptions(this.typeOptions.length ? this.typeOptions.map(id => ({ text: `${id} (${this.kinds.get(id)})` })) : [{ text: localize('modeler.noTypes', "No types: add them in Object Types") }], Math.max(0, index));
			if (index < 0 && this.typeOptions.length) {
				this.types.set(this.tool, this.typeOptions[0]);
			}
		} else if (this.tool === 'support') {
			this.typeOptions = [...SUPPORT_FIXITIES];
			this.typePicker.setOptions([{ text: localize('modeler.fixed', "Fixed") }, { text: localize('modeler.pinned', "Pinned") }], Math.max(0, this.typeOptions.indexOf(this.types.get('support') ?? 'fixed')));
		}
		const typed = this.tool === 'move' || this.tool === 'copy' || this.tool === 'divide' || this.tool === 'block';
		this.valueGroup.classList.toggle('hidden', !typed);
		if (typed) {
			this.valueBox.setPlaceHolder(this.tool === 'divide' ? localize('modeler.partsPlaceholder', "Parts (e.g. 4)") : this.tool === 'block' ? localize('modeler.thicknessPlaceholder', "Thickness (mm), e.g. 1000") : this.tool === 'copy' ? localize('modeler.copyPlaceholder', "dx, dy, dz[, copies] (mm)") : localize('modeler.movePlaceholder', "dx, dy, dz (mm)"));
		}
		this.renderStatus();
	}

	/** One line: what to do now (or what just happened), the selection and the cursor position. */
	private renderStatus(): void {
		const help = this.source?.kind === 'shape' ? localize('hint.shape', "Set the shape's dimensions and click a point to place its origin; Insert adds it to the model.")
			: this.source ? localize('hint.import', "Choose the object types and units; Insert adds the file's elements to the model.")
				: hint(this.tool, this.points.length, this.selection.length);
		const parts = [this.notice ?? help];
		if (this.selection.length) {
			parts.push(this.selection.length > 8 ? localize('modeler.selectedCount', "Selected: {0} elements", this.selection.length) : localize('modeler.selected', "Selected: {0}", this.selection.map(s => s.id).join(', ')));
		}
		const at = this.hover.point;
		if (at) {
			parts.push(`${at.map(v => Math.round(v)).join(', ')} mm${this.hover.snap && this.hover.snap !== 'plane' ? ` (${this.hover.snap})` : ''}`);
		}
		this.frame.setStatus({ text: parts.join('  ·  ') });
	}

	/** The selected elements' values; with nothing selected, the model's counts and levels. */
	private renderDetails(): void {
		const details = this.details;
		if (!details) {
			return;
		}
		clearNode(details);
		details.classList.toggle('hidden', !!this.source);
		const doc = this.doc;
		if (!doc || this.source) {
			return;
		}
		const lists = { member: doc.members, area: doc.areas, block: doc.blocks, support: doc.supports } as const;
		const shown = this.selection.slice(0, 4);
		for (const entity of shown) {
			const item = list(lists[entity.kind]).find(x => x.id === entity.id);
			if (!item) {
				continue;
			}
			appendPropertyHeading(details, entity.id, humanize(entity.kind));
			for (const [key, value] of Object.entries(item)) {
				if (key === 'id' || value === null || value === undefined) {
					continue;
				}
				// With the unit the schema gives (mm, °), as the floor plan's member sheet shows them.
				appendPropertyRow(details, humanize(key), formatPropertyValue(value, schemaUnit(STRUCTURE_SCHEMA, ENTITY_DEFINITIONS[entity.kind], key)));
			}
			const kind = typeof item.type === 'string' ? this.kinds.get(item.type) : undefined;
			if (kind) {
				appendPropertyRow(details, localize('modeler.typeKind', "Type kind"), humanize(kind));
			}
		}
		if (this.selection.length > shown.length) {
			appendPropertyNote(details, localize('modeler.moreSelected', "And {0} more.", this.selection.length - shown.length));
		}
		if (shown.length) {
			appendPropertyNote(details, localize('modeler.editInForm', "Change the values in Grids and Values (More Actions)."));
			return;
		}
		appendPropertyHeading(details, localize('modeler.modelHeading', "Structural Model"));
		appendPropertyRow(details, localize('modeler.members', "Members"), String(list(doc.members).length));
		appendPropertyRow(details, localize('modeler.areas', "Areas"), String(list(doc.areas).length));
		appendPropertyRow(details, localize('modeler.blocks', "Blocks"), String(list(doc.blocks).length));
		appendPropertyRow(details, localize('modeler.supports', "Supports"), String(list(doc.supports).length));
		appendPropertyRow(details, localize('modeler.gridSystems', "Grid systems"), String(list(doc.grids).length));
		if (this.levels.length) {
			appendPropertyRow(details, localize('modeler.levels', "Levels"), this.levels.map(l => `${l.label} (${l.z})`).join(', '));
		}
		appendPropertyNote(details, localize('modeler.selectHint', "Click an element to see its values; Shift+click adds to the selection."));
	}

	private updatePreview(): void {
		const modeler = this.modeler;
		if (!modeler) {
			return;
		}
		const at = this.hover.point;
		modeler.setCursor(at);
		const points = at ? [...this.points, at] : this.points;
		switch (this.tool) {
			case 'area':
			case 'block':
				modeler.setPreview(points, points.length > 2);
				break;
			case 'member':
			case 'move':
			case 'copy':
			case 'mirror':
				modeler.setPreview(this.points.length ? points : undefined);
				break;
			default: modeler.setPreview(undefined);
		}
	}

	private showMessage(text: string | undefined): void {
		this.message.classList.toggle('visible', !!text);
		this.message.textContent = text ?? '';
	}

	// ───────────────────────────── tools ─────────────────────────────

	private setTool(tool: Tool): void {
		this.closePanel();
		this.tool = tool;
		this.points = [];
		this.notice = undefined;
		this.valueBox.value = '';
		this.updateToolbar();
		this.updatePreview();
		this.root.focus();
	}

	private onHover(hit: ModelerHit): void {
		this.hover = hit;
		this.renderStatus();
		this.updatePreview();
	}

	private onClick(hit: ModelerHit, shift: boolean, secondary: boolean): void {
		const doc = this.doc;
		if (!doc) {
			return;
		}
		this.notice = undefined;
		if (this.source) {
			// A point places the shape being generated.
			if (this.source.kind === 'shape' && hit.point && !secondary && this.shapeValue) {
				const [x, y, z] = hit.point;
				(this.shapeValue.shape as JsonObject).origin = { x, y, z };
				this.renderPanel();
				this.ghostScheduler.schedule(0);
			}
			return;
		}
		if (secondary) {
			if ((this.tool === 'area' || this.tool === 'block') && this.points.length >= 3) {
				this.finishArea();
			} else {
				this.points = [];
			}
			this.renderStatus();
			this.updatePreview();
			return;
		}
		const p = hit.point;
		switch (this.tool) {
			case 'select':
				this.select(hit.entity, shift);
				break;
			case 'member':
				if (p && this.points.length) {
					// Chains: the end is the start of the next member.
					if (this.apply(addMember(doc, this.types.get('member') ?? '', this.points[0], p))) {
						this.points = [p];
					}
				} else if (p) {
					this.points = [p];
				}
				break;
			case 'area':
			case 'block':
				if (p && this.points.length >= 3 && p.every((v, i) => Math.abs(v - this.points[0][i]) < 1)) {
					this.finishArea();
				} else if (p) {
					this.points.push(p);
				}
				break;
			case 'support':
				if (p) {
					this.apply(addSupport(doc, p, (this.types.get('support') ?? 'fixed') as 'fixed' | 'pinned'));
				}
				break;
			case 'move':
			case 'copy':
				if (!this.selection.length) {
					this.select(hit.entity, false);
				} else if (p && this.points.length) {
					const base = this.points[0];
					const delta: ModelPoint = [p[0] - base[0], p[1] - base[1], p[2] - base[2]];
					this.points = [];
					this.apply(this.tool === 'move' ? moveElements(doc, this.selection, delta) : copyElements(doc, this.selection, delta), this.tool === 'copy');
				} else if (p) {
					this.points = [p];
				}
				break;
			case 'mirror':
				if (!this.selection.length) {
					this.select(hit.entity, false);
				} else if (p && this.points.length) {
					const first = this.points[0];
					this.points = [];
					this.apply(mirrorElements(doc, this.selection, first, p), true);
				} else if (p) {
					this.points = [p];
				}
				break;
			case 'divide':
				if (hit.entity?.kind === 'member') {
					this.apply(divideMember(doc, hit.entity.id, Number(this.valueBox.value || 2)));
				}
				break;
			case 'delete':
				if (hit.entity) {
					this.apply(removeElements(doc, [hit.entity]));
				}
				break;
		}
		this.renderStatus();
		this.updatePreview();
	}

	private select(entity: ModelerEntity | undefined, add: boolean): void {
		if (!entity) {
			if (!add) {
				this.selection = [];
			}
		} else if (add) {
			const has = this.selection.some(s => s.kind === entity.kind && s.id === entity.id);
			this.selection = has ? this.selection.filter(s => !(s.kind === entity.kind && s.id === entity.id)) : [...this.selection, entity];
		} else {
			this.selection = [entity];
		}
		this.modeler?.setSelection(this.selection);
		this.renderDetails();
	}

	private finishArea(): void {
		const doc = this.doc;
		const result = !doc ? undefined : this.tool === 'block'
			? addBlock(doc, this.types.get('block') ?? '', this.points, Number(this.valueBox.value || 1000))
			: addArea(doc, this.types.get('area') ?? '', this.points);
		if (result && this.apply(result)) {
			this.points = [];
		}
	}

	/** Move or copy by the typed offset, or the count of parts for Divide. */
	private applyTyped(): void {
		const doc = this.doc;
		if (!doc || (this.tool !== 'move' && this.tool !== 'copy')) {
			return;
		}
		const offset = parseOffset(this.valueBox.value);
		if (!offset) {
			this.notice = localize('modeler.badOffset', "Type the offset as \"dx, dy, dz\" in mm{0}.", this.tool === 'copy' ? localize('modeler.badOffsetCount', ", with \", n\" for n copies") : '');
		} else {
			this.points = [];
			this.apply(this.tool === 'move' ? moveElements(doc, this.selection, offset.delta) : copyElements(doc, this.selection, offset.delta, offset.count ?? 1), this.tool === 'copy');
		}
		this.renderStatus();
		this.updatePreview();
	}

	private onKey(e: KeyboardEvent): void {
		if (!isKeyboardEvent(e) || e.target === this.valueBox.inputElement) {
			return;
		}
		if (this.source) {
			if (e.key === 'Escape') {
				e.preventDefault();
				this.closePanel();
			}
			return; // typing in the panel's form
		}
		if (e.key === 'Escape') {
			if (this.points.length) {
				this.points = [];
			} else if (this.tool !== 'select') {
				this.setTool('select');
			} else {
				this.select(undefined, false);
			}
		} else if (e.key === 'Enter' && (this.tool === 'area' || this.tool === 'block') && this.points.length >= 3) {
			this.finishArea();
		} else if ((e.key === 'Delete' || e.key === 'Backspace') && this.selection.length && this.doc) {
			this.apply(removeElements(this.doc, this.selection));
			this.selection = [];
		} else {
			return;
		}
		e.preventDefault();
		this.renderStatus();
		this.updatePreview();
	}

	/** Writes a successful edit (selecting what it made when `selectResult`); shows why not otherwise. */
	private apply(result: EditResult, selectResult = false): boolean {
		if (!result.ok) {
			this.notice = result.error;
			return false;
		}
		if (selectResult) {
			this.selection = entitiesOf(result.doc, result.ids);
		}
		this.write(JSON.stringify(result.doc, undefined, '\t') + '\n');
		this.notice = localize('modeler.done', "{0}: {1}.", TOOLS.find(t => t.tool === this.tool)?.label ?? '', result.ids.join(', '));
		return true;
	}

	/** Replaces the structural model with `text` as one undoable edit. */
	private write(text: string): void {
		const model = this.model;
		if (!model || model.isDisposed()) {
			return;
		}
		this.writing = true;
		try {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null);
			model.pushStackElement();
		} finally {
			this.writing = false;
		}
		this.renderScheduler.cancel();
		this.render();
	}

	/** Writes a model built by Python (a shape, an import or a script) and selects what it added. */
	private writeAdded(text: string, ids: readonly string[]): void {
		let doc: unknown;
		try {
			doc = JSON.parse(text);
		} catch {
			return;
		}
		if (isStructure(doc)) {
			this.selection = entitiesOf(doc, ids);
		}
		this.write(text);
	}

	// ───────────────────────────── shapes and import (side panel) ─────────────────────────────

	private formContext(root: IJSONSchema): ISchemaFormContext {
		return {
			root,
			template: defName => this.template(defName),
			references: path => FIELD_KINDS[path] && this.typesOf(FIELD_KINDS[path]),
			validate: () => undefined,
			changed: (_path, structural) => {
				if (structural) {
					this.renderPanel();
				}
				this.ghostScheduler.schedule();
			},
			mode: () => undefined,
		};
	}

	/** Object type ids of these kinds. */
	private typesOf(kinds: readonly string[]): string[] {
		return [...this.kinds].filter(([, kind]) => kinds.includes(kind)).map(([id]) => id);
	}

	/** The type a new shape or import starts with: the one drawn last, else the first of its kinds. */
	private defaultType(kinds: readonly string[]): string | undefined {
		const drawn = this.types.get(kinds.includes('slab') || kinds.includes('wall') ? 'area' : 'member');
		const types = this.typesOf(kinds);
		return drawn && types.includes(drawn) ? drawn : types[0];
	}

	/** A shape's starting values, with the member type placeholder replaced. */
	private template(defName: string): JsonObject {
		const value = clone((TEMPLATES[defName] ?? {}) as JsonObject);
		if (value.memberType === 'MEMBER') {
			value.memberType = this.defaultType(['brace', 'beam']) ?? this.defaultType(MEMBER_KINDS) ?? '';
		}
		return value;
	}

	private openShape(): void {
		this.closePanel();
		this.coded = undefined;
		this.codedForm.clear();
		this.shapeValue ??= { shape: this.template('SpaceTruss') };
		this.openPanel({ kind: 'shape' });
		void this.loadPresets();
	}

	/** The presets of the structure templates installed, for the Generate panel's picker. */
	private async loadPresets(): Promise<void> {
		if (!CommandsRegistry.getCommand(CODES_TEMPLATES_COMMAND)) {
			return;
		}
		try {
			this.presets = readStructurePresets(await this.commandService.executeCommand<unknown>(CODES_TEMPLATES_COMMAND, { kind: 'structureTemplate' }));
		} catch {
			this.presets = [];
		}
		this.renderPresets();
	}

	private renderPresets(): void {
		const select = this.presetSelect;
		clearNode(select);
		this.panelPresets.classList.toggle('hidden', this.source?.kind !== 'shape' || !this.presets.length);
		const placeholder = append(select, $('option', { value: '' }, localize('modeler.presetPlaceholder', "Start from a structure template...")));
		placeholder.selected = true;
		groupPresets(this.presets).forEach((group, g) => {
			const optgroup = append(select, $('optgroup', { label: group.name }));
			group.presets.forEach((preset, i) => {
				append(optgroup, $('option', { value: `${g}/${i}`, title: preset.description }, preset.name));
			});
		});
	}

	/** Fills the Generate form with a preset (keeping where the shape is placed). */
	private applyPreset(value: string): void {
		const [g, i] = value.split('/').map(Number);
		const preset = groupPresets(this.presets)[g]?.presets[i];
		if (!preset || this.source?.kind !== 'shape') {
			return;
		}
		this.codedForm.clear();
		if (preset.coded) {
			// A new shape kind made by the package's code: its form is made from its parameter schema.
			const schema: IJSONSchema = { type: 'object', properties: { values: preset.coded.parameters as IJSONSchema } };
			this.coded = { preset, schema, value: { values: clone(preset.coded.values as JsonObject) }, form: this.codedForm.add(this.instantiationService.createInstance(SchemaForm, this.formContext(schema))) };
			this.fitGhost = true;
			this.renderPanel();
			this.renderPresets();
			this.presetSelect.value = value;
			this.ghostScheduler.schedule(0);
			return;
		}
		this.coded = undefined;
		if (!preset.shape) {
			return;
		}
		const shape = clone(preset.shape as JsonObject);
		if (shape.memberType === 'MEMBER' || typeof shape.memberType !== 'string' || !shape.memberType) {
			shape.memberType = this.defaultType(['brace', 'beam']) ?? this.defaultType(MEMBER_KINDS) ?? '';
		}
		const origin = (this.shapeValue?.shape as JsonObject | undefined)?.origin;
		if (origin !== undefined && shape.origin === undefined) {
			shape.origin = origin;
		}
		this.shapeValue = { shape };
		this.fitGhost = true;
		this.renderPanel();
		this.renderPresets();
		this.presetSelect.value = value;
		this.ghostScheduler.schedule(0);
	}

	private async openImport(): Promise<void> {
		const input = this.input as LibraryEditorInput | undefined;
		const files = await this.fileDialogService.showOpenDialog({
			title: localize('modeler.importDialog', "Import 3D Geometry"),
			filters: [{ name: localize('modeler.importFilter', "3D models (DXF, DWG, IFC, Rhino)"), extensions: ['dxf', 'dwg', 'ifc', '3dm'] }],
			canSelectFiles: true,
			canSelectMany: false,
			defaultUri: input && dirname(dirname(input.resource)),
		});
		if (!files?.length) {
			return;
		}
		this.closePanel();
		if (!this.importValue) {
			const options: JsonObject = { units: 'auto', supports: 'none' };
			for (const [key, kinds] of Object.entries(FIELD_KINDS)) {
				const type = key.startsWith('options.') ? this.defaultType(kinds) : undefined;
				if (type) {
					options[key.slice('options.'.length)] = type;
				}
			}
			this.importValue = { options };
		}
		this.fitGhost = true;
		this.openPanel({ kind: 'import', file: files[0] });
	}

	private openPanel(source: Source): void {
		this.tool = 'select';
		this.points = [];
		this.source = source;
		this.ghost = undefined;
		this.ghostProblems = [];
		this.updateToolbar();
		this.updatePreview();
		this.renderPanel();
		this.ghostScheduler.schedule(0);
	}

	private closePanel(): void {
		if (!this.source) {
			return;
		}
		this.source = undefined;
		this.ghost = undefined;
		this.ghostRequest++;
		this.ghostScheduler.cancel();
		this.modeler?.setGhost(undefined);
		this.renderPanel();
		this.renderStatus();
	}

	private renderPanel(): void {
		const source = this.source;
		if (this.panel.classList.contains('visible') !== !!source) {
			this.panel.classList.toggle('visible', !!source);
			if (source) {
				this.frame.setPropertiesVisible(true); // the form of what is being added
			}
		}
		this.renderDetails();
		this.panelMore.classList.toggle('hidden', source?.kind !== 'shape');
		this.panelPresets.classList.toggle('hidden', source?.kind !== 'shape' || !this.presets.length);
		clearNode(this.panelForm);
		if (!source) {
			return;
		}
		if (source.kind === 'shape' && this.coded) {
			this.panelTitle.textContent = this.coded.preset.name;
			this.coded.form.render(this.panelForm, this.coded.schema, this.coded.value);
		} else if (source.kind === 'shape' && this.shapeValue) {
			this.panelTitle.textContent = localize('modeler.generateTitleShort', "Generate Shape");
			this.shapeForm.render(this.panelForm, SHAPE_SCHEMA, this.shapeValue);
		} else if (source.kind === 'import' && this.importValue) {
			this.panelTitle.textContent = localize('modeler.importFile', "Import {0}", basename(source.file));
			this.importForm.render(this.panelForm, IMPORT_SCHEMA, this.importValue);
		}
		this.renderPanelStatus();
	}

	private renderPanelStatus(): void {
		clearNode(this.panelStatus);
		const ghost = this.ghost;
		const count = ghost ? ghost.members.length + ghost.areas.length + ghost.supports.length : 0;
		this.insertButton.enabled = count > 0;
		if (this.ghostProblems.length) {
			for (const problem of this.ghostProblems) {
				append(this.panelStatus, $('.modeler-panel-problem', undefined, problem));
			}
			return;
		}
		if (!ghost) {
			append(this.panelStatus, $('div', undefined, localize('modeler.previewing', "Building the preview…")));
			return;
		}
		append(this.panelStatus, $('div', undefined, localize('modeler.ghostCount', "{0} members, {1} areas, {2} supports.", ghost.members.length, ghost.areas.length, ghost.supports.length)));
		for (const note of ghost.notes) {
			append(this.panelStatus, $('.modeler-panel-note', undefined, note));
		}
	}

	/** Asks Python for the geometry of the panel's shape or file and shows it as a preview. */
	private async refreshGhost(): Promise<void> {
		const source = this.source;
		if (!source) {
			return;
		}
		const request = ++this.ghostRequest;
		let result: StructureGeometryResult | undefined;
		try {
			const coded = source.kind === 'shape' ? this.coded : undefined;
			result = coded
				? await this.commandService.executeCommand<StructureGeometryResult>(CODES_CODED_GEOMETRY_COMMAND, { package: coded.preset.package, file: coded.preset.file, values: coded.value.values, memberType: this.defaultType(['brace', 'beam']) ?? this.defaultType(MEMBER_KINDS) })
				: source.kind === 'shape'
				? await this.commandService.executeCommand<StructureGeometryResult>('saengine.structure.shapeGeometry', this.shapeValue?.shape)
				: await this.commandService.executeCommand<StructureGeometryResult>('saengine.structure.importGeometry', source.file, this.importValue?.options, this.objects?.getValue());
		} catch (error) {
			result = { problems: [String(error)] };
		}
		if (request !== this.ghostRequest || this.source !== source) {
			return; // a newer request, or the panel was closed
		}
		if (!result || hasKey(result, { problems: true })) {
			this.ghost = undefined;
			this.ghostProblems = result?.problems ?? [localize('modeler.noBackend', "The SAEngine Python backend did not answer.")];
		} else {
			this.ghost = result;
			this.ghostProblems = [];
		}
		this.modeler?.setGhost(this.ghost);
		if (this.ghost && this.fitGhost) {
			this.fitGhost = false;
			void this.modeler?.fit();
		}
		this.renderPanelStatus();
	}

	private async insertGhost(): Promise<void> {
		const ghost = this.ghost;
		const model = this.model;
		if (!ghost || !model) {
			return;
		}
		let result: IStructureEdit | undefined;
		try {
			result = await this.commandService.executeCommand<IStructureEdit>('saengine.structure.insertGeometry', model.getValue(), ghost);
		} catch (error) {
			result = { problems: [String(error)] };
		}
		if (!result?.text) {
			this.ghostProblems = result?.problems ?? [localize('modeler.noBackend', "The SAEngine Python backend did not answer.")];
			this.renderPanelStatus();
			return;
		}
		const ids = result.ids ?? [];
		this.closePanel();
		this.writeAdded(result.text, ids);
		this.notice = result.skipped
			? localize('modeler.insertedSkipped', "Added {0} elements; {1} already in the model were left out.", ids.length, result.skipped)
			: localize('modeler.inserted', "Added {0} elements.", ids.length);
		this.renderStatus();
	}

	// ───────────────────────────── scripts ─────────────────────────────

	private scriptsFolder(): URI | undefined {
		const input = this.input as LibraryEditorInput | undefined;
		return input && joinPath(dirname(input.resource), SCRIPTS_FOLDER);
	}

	/** Lists the model's scripts (the last one run first) to run one, or starts a new one. */
	private async pickScript(): Promise<void> {
		const folder = this.scriptsFolder();
		if (!folder) {
			return;
		}
		let scripts: URI[] = [];
		try {
			const stat = await this.fileService.resolve(folder);
			scripts = (stat.children ?? []).filter(c => !c.isDirectory && c.name.endsWith('.py')).map(c => c.resource);
		} catch {
			// no scripts folder yet
		}
		const last = this.lastScript?.toString();
		scripts.sort((a, b) => Number(b.toString() === last) - Number(a.toString() === last) || basename(a).localeCompare(basename(b)));
		const edit = { iconClass: ThemeIcon.asClassName(Codicon.edit), tooltip: localize('modeler.editScript', "Edit Script") };
		type ScriptItem = IQuickPickItem & { readonly script?: URI };
		const items: (ScriptItem | IQuickPickSeparator)[] = scripts.map(script => ({ label: basename(script), description: localize('modeler.scriptsFolder', "05 Structural Model/scripts"), script, buttons: [edit] }));
		if (items.length) {
			items.push({ type: 'separator' });
		}
		items.push({ label: `$(${Codicon.add.id}) ${localize('modeler.newScript', "New Script...")}` });
		const pick = await this.quickInputService.pick<ScriptItem>(items, {
			placeHolder: localize('modeler.scriptPick', "Run a script on the structural model, or start a new one"),
			onDidTriggerItemButton: context => {
				context.removeItem();
				if (context.item.script) {
					void this.editorService.openEditor({ resource: context.item.script, options: { pinned: true } }, SIDE_GROUP);
				}
			},
		});
		if (pick?.script) {
			await this.runScript(pick.script);
		} else if (pick) {
			await this.newScript(folder);
		}
	}

	private async newScript(folder: URI): Promise<void> {
		const name = await this.quickInputService.input({
			prompt: localize('modeler.scriptName', "Name of the new script (without .py)"),
			value: 'model',
			validateInput: async value => /^[A-Za-z_][A-Za-z0-9_-]*$/.test(value) ? undefined : localize('modeler.scriptNameInvalid', "Use letters, digits, - and _, starting with a letter."),
		});
		if (!name) {
			return;
		}
		const script = joinPath(folder, `${name}.py`);
		if (await this.fileService.exists(script)) {
			this.notice = localize('modeler.scriptExists', "{0} already exists.", basename(script));
		} else {
			const text = SCRIPT_TEMPLATE
				.replaceAll('{column}', this.defaultType(['column']) ?? 'COL')
				.replaceAll('{member}', this.defaultType(['brace', 'beam']) ?? 'BM');
			await this.fileService.createFile(script, VSBuffer.fromString(text));
			this.lastScript = script;
			this.notice = localize('modeler.scriptCreated', "{0} created: edit it, save it, then run it with Script.", basename(script));
			await this.editorService.openEditor({ resource: script, options: { pinned: true } }, SIDE_GROUP);
		}
		this.renderStatus();
	}

	private async runScript(script: URI): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		this.lastScript = script;
		if (this.textFileService.isDirty(script)) {
			await this.textFileService.save(script); // run what is on screen
		}
		this.notice = localize('modeler.scriptRunning', "Running {0}...", basename(script));
		this.renderStatus();
		let result: IStructureScriptResult | undefined;
		try {
			result = await this.commandService.executeCommand<IStructureScriptResult>('saengine.structure.runScript', model.getValue(), script);
		} catch (error) {
			result = { error: String(error), output: '' };
		}
		const output = this.outputService.getChannel(SCRIPT_OUTPUT_CHANNEL_ID);
		if (result?.output) {
			output?.append(`${basename(script)}:\n${result.output}\n`);
		}
		if (result?.text) {
			const ids = result.ids ?? [];
			this.writeAdded(result.text, ids);
			this.notice = result.cleared
				? localize('modeler.scriptRebuilt', "{0} rebuilt the model: {1} elements.", basename(script), ids.length)
				: localize('modeler.scriptAdded', "{0} added {1} elements.", basename(script), ids.length);
		} else {
			const why = result?.error ?? result?.problems?.join('; ') ?? localize('modeler.noBackend', "The SAEngine Python backend did not answer.");
			this.notice = localize('modeler.scriptFailed', "{0} failed: {1}", basename(script), why);
			if (result?.output) {
				void this.outputService.showChannel(SCRIPT_OUTPUT_CHANNEL_ID, true);
			}
		}
		this.renderStatus();
	}

	private openForm(): void {
		const input = this.input as LibraryEditorInput | undefined;
		if (input) {
			void this.editorService.openEditor({ resource: input.resource, options: { override: LibraryEditorInput.STRUCTURE_EDITOR_ID, pinned: true } }, SIDE_GROUP);
		}
	}

	private computeTheme(): Partial<ModelerTheme> {
		const theme = this.themeService.getColorTheme();
		const color = (id: string) => theme.getColor(id)?.toString();
		return {
			background: color(editorBackground),
			grid: color(chartsLines),
			gridPoint: color(chartsLines),
			member: color(chartsBlue),
			column: color(chartsPurple),
			brace: color(chartsOrange),
			slab: color(chartsGreen),
			solid: color(chartsPurple),
			wall: color(chartsOrange),
			support: color(chartsGreen),
			selection: color(chartsYellow),
			preview: color(editorForeground),
			cursor: color(chartsYellow),
		};
	}
}
