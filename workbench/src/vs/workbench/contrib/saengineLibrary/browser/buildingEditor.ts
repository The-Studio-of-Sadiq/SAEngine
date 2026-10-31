/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modelEditors.css';
import type { BuildingLayer, BuildingViewer, BuildingViewPreset } from '@saengine/fem-viewer';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { Action, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Color } from '../../../../base/common/color.js';
import { DisposableStore, IReference, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { Emitter } from '../../../../base/common/event.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { BIM_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { chartsLines, chartsYellow } from '../../../../platform/theme/common/colors/chartsColors.js';
import { editorBackground } from '../../../../platform/theme/common/colors/editorColors.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService, MemberGroup, ModelSelection } from '../../../services/saengineProject/common/modelSelection.js';
import { recordedStamp, sourceStamp, upstreamPart } from '../../../services/saengineProject/common/partSources.js';
import { IPartSectionPane, sectionOption } from '../../../services/saengineProject/common/partSections.js';
import { ISaengineProjectService, partById, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { loadViewerModule, viewerAssetBaseUrl } from '../../saengineFem/browser/viewerModule.js';
import { propertySheet } from '../../saengineModel/browser/modelData.js';
import { openOwner } from '../../saengineModel/browser/projectDocuments.js';
import { formatPropertyValue, propertyLink, renderPropertySheet, schemaUnit } from '../../saengineModel/browser/propertySheetView.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { humanize, JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

const BIM_SCHEMA_ID = 'saengine.bim/2';

/** A story elevation as the floor plan writes it: "+3200", "-1500" [mm]. */
function formatElevation(mm: number): string {
	return `${mm > 0 ? '+' : ''}${mm}`;
}
const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';
const STRUCTURE_SCHEMA_ID = 'saengine.structure/1';

/** Desktop commands of the Python models (see `saengine.library.bim` and `saengine.library.ifc`). */
const GENERATE_COMMAND = 'saengine.bim.generate';
const GENERATE_FROM_STRUCTURE_COMMAND = 'saengine.bim.generateFromStructure';
const IFC_COMMAND = 'saengine.bim.ifc';

/** The selection service's name for this editor. */
const SELECTION_SOURCE = 'building';

interface IGeneratedBuilding {
	readonly text?: string;
	readonly problems?: readonly string[];
}

interface IBuildingIfc {
	readonly text?: string;
	readonly ids?: { readonly [elementId: string]: string };
	readonly skipped?: readonly string[];
	readonly problems?: readonly string[];
	/** The story each architecture element (`arch:<id>`) stands on. */
	readonly architectureStories?: { readonly [elementId: string]: string };
}

const ELEMENT_KINDS: readonly { readonly kind: string; readonly group?: MemberGroup; readonly label: string }[] = [
	{ kind: 'column', group: 'columns', label: localize('element.columns', "Columns") },
	{ kind: 'beam', group: 'beams', label: localize('element.beams', "Beams") },
	{ kind: 'wall', group: 'walls', label: localize('element.walls', "Walls") },
	{ kind: 'slab', group: 'slabs', label: localize('element.slabs', "Slabs") },
	{ kind: 'footing', group: 'footings', label: localize('element.footings', "Footings") },
	{ kind: 'member', label: localize('element.members', "Members") },
	{ kind: 'area', label: localize('element.areas', "Areas") },
	{ kind: 'block', label: localize('element.blocks', "Blocks") },
];

type View = '3d' | 'additions' | 'summary';

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: '3d', label: localize('building.view3d', "3D View"), icon: Codicon.symbolStructure },
	{ view: 'additions', label: localize('building.viewAdditions', "Additions"), icon: Codicon.add },
	{ view: 'summary', label: localize('building.viewSummary', "Summary"), icon: Codicon.listFlat },
];

/** The camera presets over the 3D view. */
const PRESETS: readonly { readonly preset: BuildingViewPreset; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ preset: 'iso', label: localize('building.viewIso', "Iso"), icon: Codicon.home },
	{ preset: 'top', label: localize('building.viewTop', "Top"), icon: Codicon.arrowDown },
	{ preset: 'front', label: localize('building.viewFront', "Front"), icon: Codicon.arrowUp },
	{ preset: 'side', label: localize('building.viewSide', "Side"), icon: Codicon.arrowLeft },
];

/** Names of the layers of the 3D view, in its legend. */
const LAYER_LABELS: { readonly [layer in BuildingLayer]: string } = {
	column: localize('layer.columns', "Columns"),
	beam: localize('layer.beams', "Beams"),
	wall: localize('layer.walls', "Walls"),
	slab: localize('layer.slabs', "Slabs"),
	footing: localize('layer.foundations', "Foundations"),
	stair: localize('layer.stairs', "Stairs"),
	member: localize('layer.members', "Inclined members"),
	mep: localize('layer.mep', "MEP"),
	architecture: localize('layer.architecture', "Architecture"),
	room: localize('layer.rooms', "Rooms"),
};

/** Ids of the architecture's elements in the IFC's id map (see `saengine.library.architecture_ifc`). */
const ARCHITECTURE_ID = 'arch:';

/**
 * Lists of 7 MEP (`mep.json`) whose items the coordination model draws in 3D (see
 * `saengine.library.ifc`): picking one shows it in Properties with a link to 7 MEP.
 */
const MEP_LISTS: readonly { readonly path: readonly string[]; readonly label: string }[] = [
	{ path: ['equipment'], label: localize('mep.equipment', "Equipment") },
	{ path: ['openings'], label: localize('mep.opening', "MEP opening") },
	{ path: ['shafts'], label: localize('mep.shaft', "Shaft") },
	{ path: ['plumbing', 'tanks'], label: localize('mep.tank', "Water tank") },
	{ path: ['plumbing', 'risers'], label: localize('mep.riser', "Plumbing riser") },
	{ path: ['hvac', 'plant'], label: localize('mep.plant', "HVAC plant") },
	{ path: ['hvac', 'ducts'], label: localize('mep.duct', "Duct") },
	{ path: ['electrical', 'equipment'], label: localize('mep.electrical', "Electrical equipment") },
	{ path: ['electrical', 'risers'], label: localize('mep.electricalRiser', "Electrical riser") },
	{ path: ['electrical', 'trays'], label: localize('mep.tray', "Cable tray") },
];

/** Additions lists, the id prefix of their new entries, and the elements or objects they refer to. */
const ADDITION_LISTS: { readonly [list: string]: string } = {
	slabOpenings: 'O',
	wallOpenings: 'D',
	stairs: 'ST',
	members: 'M',
};

/** The schema definition of an entry of each additions list. */
const ADDITION_DEFINITIONS: { readonly [list: string]: string } = {
	slabOpenings: 'SlabOpening',
	wallOpenings: 'WallOpening',
	stairs: 'Stair',
	members: 'InclinedMember',
};

/** The parts of the building model that are generated, not edited in the Additions form. */
const GENERATED = ['source', 'stories', 'elements'];

/**
 * The building model (`06 BIM/bim.json`), generated from the floor plan. The floor plan owns the
 * layout; this editor shows the building in 3D (the IFC the model exports, loaded with That
 * Open), says when the floor plan has changed since it was built, rebuilds on request and
 * exports IFC. Elements that belong to the building model itself (no floor-plan source) are
 * kept when it is rebuilt.
 */
export class BuildingEditor extends JsonDocumentEditor implements IPartSectionPane {

	static readonly ID = LibraryEditorInput.BUILDING_EDITOR_ID;

	private frame!: EditorFrame;
	private viewport!: HTMLElement;
	private summary!: HTMLElement;
	private additions!: HTMLElement;
	private readonly viewButtons = new Map<View, HTMLButtonElement>();
	private readonly form: SchemaForm;
	private view: View = '3d';
	private readonly _onDidChangePartSection = this._register(new Emitter<void>());
	readonly onDidChangePartSection = this._onDidChangePartSection.event;

	private viewer: BuildingViewer | undefined;
	private viewerLoading: Promise<BuildingViewer | undefined> | undefined;
	private readonly viewerDisposable = this._register(new MutableDisposable());
	private readonly ifcScheduler = this._register(new RunOnceScheduler(() => this.refreshIfc(), 400));
	private ifcVersion = 0;
	private ifcNote: string | undefined;
	/** Elements the IFC (and so the 3D view and the export) leaves out: problems too. */
	private ifcSkipped = 0;
	/** The element picked in 3D, also one the floor plan does not own (an addition). */
	private selectedElement: string | undefined;
	/** The story each architecture element (`arch:<id>`) stands on, from the last IFC. */
	private architectureStories: { readonly [id: string]: string } = {};

	private objectsText: string | undefined;
	private materials: ITextModel | undefined;
	/** `07 MEP/mep.json` (unsaved edits included), for picking its equipment in 3D. */
	private mep: ITextModel | undefined;
	/** The objects file, read here when the tab was restored before the project was open. */
	private readonly objectsReference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());

	/** Over the 3D view: the story filter, the legend, and the loading and empty notes. */
	private storySelect!: HTMLSelectElement;
	private legend!: HTMLElement;
	private loadingNote!: HTMLElement;
	private emptyNote!: HTMLElement;
	private storyFilter: string | undefined;
	private readonly hiddenLayers = new Set<BuildingLayer>();
	private readonly legendDisposables = this._register(new DisposableStore());
	/** The Part 5 model this one is built from, followed to say when it changed. */
	private readonly source = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());

	private readonly rebuildAction = this._register(new Action('saengine.bim.rebuild', '', ThemeIcon.asClassName(Codicon.refresh), true, () => this.build()));
	private readonly fitAction = this._register(new Action('saengine.bim.fit', localize('building.fit', "Zoom to Fit"), ThemeIcon.asClassName(Codicon.screenFull), true, async () => this.viewer?.fit()));
	private readonly openSourceAction = this._register(new Action('saengine.bim.openSource', '', undefined, true, async () => this.openSource()));
	private readonly exportAction = this._register(new Action('saengine.bim.exportIfc', localize('building.exportIfc', "Export IFC"), undefined, false, () => this.exportIfc()));
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private additionsProblems: HTMLElement | undefined;
	/** The Problems heading in Properties, which "Details" scrolls to. */
	private problemsHeading: HTMLElement | undefined;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ICommandService private readonly commands: ICommandService,
		@IEditorService private readonly editors: IEditorService,
		@ITextModelService private readonly textModels: ITextModelService,
		@ISaengineProjectService private readonly project: ISaengineProjectService,
		@INotificationService private readonly notificationService: INotificationService,
		@IFileService private readonly fileService: IFileService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@IInstantiationService private readonly instantiation: IInstantiationService,
		@IConfigurationService configurationService: IConfigurationService,
		@ITextFileService private readonly textFiles: ITextFileService,
	) {
		super(BuildingEditor.ID, group, telemetryService, themeService, storageService, commands, editors, textModels, project);
		this.trackDeveloperMode(configurationService);
		this.form = instantiation.createInstance(SchemaForm, {
			root: BIM_SCHEMA,
			template: defName => clone((TEMPLATES[defName] ?? {}) as JsonObject),
			references: path => this.references(path),
			validate: (path, value) => this.validate(path, value),
			changed: (_path, structural) => this.changed(structural),
			mode: () => undefined,
			newItem: (path, list) => this.newItem(path, list),
		});
		this._register({ dispose: () => this.form.dispose() });
		this._register(selectionService.onDidChangeSelection(({ selection, source }) => {
			if (source !== SELECTION_SOURCE) {
				this.selectedElement = selection?.kind === 'member' ? this.elementOfMember(selection.id) : undefined;
				void this.viewer?.setSelection(this.selectedElement);
			}
			this.renderProperties();
		}));
		this._register(themeService.onDidColorThemeChange(() => void this.viewer?.setTheme(this.viewerTheme())));
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		const frame = this.frame = this._register(this.instantiation.createInstance(EditorFrame, parent, {
			id: BuildingEditor.ID,
			ariaLabel: localize('building.toolbar', "Building Model"),
			properties: { title: localize('building.properties', "Properties") },
		}));
		frame.element.classList.add('saengine-building-editor');
		return frame;
	}

	protected createBody(body: HTMLElement): void {
		const frame = this.frame;

		// The view: a segmented control, the editor's only text in the toolbar.
		const views = append(frame.titleSlot, $('.sa-segmented', { role: 'tablist', 'aria-label': localize('building.viewsAria', "Building model view") }));
		for (const { view, label, icon } of VIEWS) {
			const button = append(views, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }));
			append(button, $(ThemeIcon.asCSSSelector(icon)));
			append(button, $('span', undefined, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => {
				this.showView(view);
				this.render();
			}));
			this.viewButtons.set(view, button);
		}


		const container = append(body, $('.building-editor.building-3d'));
		this.viewport = append(container, $('.building-viewport'));
		this.createViewTools(this.viewport);
		this.summary = append(container, $('.building-summary-view'));
		this.additions = append(container, $('.building-additions-view'));
		this._register(frame.onDidLayoutMain(() => this.viewer?.layout()));
		this.showView(this.view);
	}

	/** The camera presets and story filter (top left), the legend (bottom left) and the notes. */
	private createViewTools(viewport: HTMLElement): void {
		const tools = append(viewport, $('.building-3d-tools'));
		const presets = append(tools, $('.sa-segmented.building-presets', { role: 'group', 'aria-label': localize('building.presetsAria', "View direction") }));
		for (const { preset, label, icon } of PRESETS) {
			const button = append(presets, $<HTMLButtonElement>('button.sa-segment', { type: 'button', title: label }));
			append(button, $(ThemeIcon.asCSSSelector(icon)));
			append(button, $('span', undefined, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => void this.viewer?.setView(preset)));
		}
		this.storySelect = append(tools, $<HTMLSelectElement>('select.building-story-filter', { 'aria-label': localize('building.storyFilterAria', "Stories shown") }));
		this._register(addDisposableListener(this.storySelect, EventType.CHANGE, () => {
			this.storyFilter = this.storySelect.value || undefined;
			void this.applyStoryFilter();
		}));
		this.legend = append(viewport, $('.building-legend', { role: 'group', 'aria-label': localize('building.legendAria', "Layers") }));
		this.loadingNote = append(viewport, $('.building-3d-note.loading.hidden', { role: 'status' }));
		append(this.loadingNote, $(ThemeIcon.asCSSSelector(ThemeIcon.modify(Codicon.loading, 'spin'))));
		append(this.loadingNote, $('span', undefined, localize('building.loading3d', "Loading the 3D view…")));
		this.emptyNote = append(viewport, $('.building-3d-note.empty.hidden'));
	}

	override async setInput(input: LibraryEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		this.materials = undefined;
		this.mep = undefined;
		this.objectsText = undefined;
		this.objectsReference.clear();
		this.storyFilter = undefined;
		this.source.clear();
		this.selectedElement = undefined;
		await super.setInput(input, options, context, token);
		if (this.input !== input) {
			return;
		}
		const root = dirname(dirname(input.resource));
		// Restored at startup before the project was open, the base class found no objects file: read it here.
		if (this.objectsText === undefined) {
			const objects = partById('objects')!;
			try {
				const reference = await this.textModels.createModelReference(joinPath(root, objects.folder, objects.mainFile!));
				if (this.input !== input) {
					reference.dispose();
					return;
				}
				this.objectsReference.value = reference;
				const model = reference.object.textEditorModel;
				this.inputDisposables.add(model.onDidChangeContent(() => this.onCompanionChanged(model.getValue())));
				this.onCompanionChanged(model.getValue());
			} catch {
				// Without object types the 3D view says it cannot be built.
			}
		}
		// The coordination model of 7 MEP is in the 3D view too: picking its equipment shows it here.
		const mepPart = partById('mep');
		if (mepPart?.mainFile) {
			try {
				const reference = await this.textModels.createModelReference(joinPath(root, mepPart.folder, mepPart.mainFile));
				if (this.input !== input) {
					reference.dispose();
					return;
				}
				this.inputDisposables.add(reference);
				this.mep = reference.object.textEditorModel;
				this.inputDisposables.add(this.mep.onDidChangeContent(() => this.ifcScheduler.schedule()));
			} catch {
				// A project without 7 MEP.
			}
		}
		// Material names for the IFC, read from the materials file (unsaved edits included).
		const part = PROJECT_PARTS.find(p => p.id === 'materials')!;
		try {
			const reference = await this.textModels.createModelReference(joinPath(root, part.folder, part.mainFile!));
			if (this.input !== input) {
				reference.dispose();
				return;
			}
			this.inputDisposables.add(reference);
			this.materials = reference.object.textEditorModel;
			this.inputDisposables.add(this.materials.onDidChangeContent(() => this.ifcScheduler.schedule()));
		} catch {
			// Without materials the IFC names materials by id.
		}
		// The floor plan (or structural model): "Out of date" when it changed since the last build.
		const sourcePart = partById(upstreamPart('bim', this.project.parts) ?? (this.special ? 'structure' : 'floorPlan'));
		if (sourcePart?.mainFile) {
			try {
				const reference = await this.textModels.createModelReference(joinPath(root, sourcePart.folder, sourcePart.mainFile));
				if (this.input !== input) {
					reference.dispose();
					return;
				}
				this.source.value = reference;
				this.inputDisposables.add(reference.object.textEditorModel.onDidChangeContent(() => {
					this.updateChrome();
					this.renderProperties();
				}));
			} catch {
				// No source yet: the editor says it has not been built.
			}
		}
		this.ifcScheduler.schedule();
		this.updateChrome();
		this.renderProperties();
	}

	override clearInput(): void {
		this.ifcScheduler.cancel();
		this.source.clear();
		this.objectsReference.clear();
		this.setLoading(false);
		super.clearInput();
	}

	override dispose(): void {
		this.viewer?.dispose();
		this.viewer = undefined;
		super.dispose();
	}

	protected override onCompanionChanged(text: string): void {
		this.objectsText = text;
		this.ifcScheduler.schedule();
		this.renderProperties();
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === BIM_SCHEMA_ID) {
			return undefined;
		}
		const build = { label: localize('building.build', "Build from {0}", this.sourceName), run: () => this.build() };
		if (value.schema === 'saengine.bim/1') {
			return {
				message: localize('building.legacy', "This building model still holds the layout, which the Floor Plan owns now. Open the Floor Plan and create it (it takes the layout over from this file), then build the building model from it."),
				fix: build,
			};
		}
		if (value.part === 'bim') {
			return { message: localize('building.empty', "The building model has not been built from the {0} yet.", this.sourceName), fix: build };
		}
		return { message: localize('building.unexpected', "This file is not a SAEngine building model ({0}).", BIM_SCHEMA_ID) };
	}

	protected override updateFromUpstream(): void {
		void this.build();
	}

	/** A special structure is built from its structural model, a building from its floor plan. */
	private get special(): boolean {
		return this.project.project?.type === 'structure';
	}

	/** The Part 5 model this one is built from, as the engineer knows it. */
	private get sourceName(): string {
		return this.special ? localize('building.structuralModel', "Structural Model") : localize('building.floorPlan', "Floor Plan");
	}

	/** Whether the source changed since the model was built from it (or it never was). */
	private get stale(): boolean {
		const model = this.source.value?.object.textEditorModel;
		const part = upstreamPart('bim', this.project.parts) ?? (this.special ? 'structure' : 'floorPlan');
		return !!this.document && !!model && recordedStamp(this.document, part) !== sourceStamp(model.getValue());
	}

	/** Generates the model from the current Part 5 model, keeping the model's own elements. */
	private async build(): Promise<void> {
		const source = this.upstreamText ?? this.source.value?.object.textEditorModel.getValue();
		let parsed: JsonValue | undefined;
		try {
			parsed = source ? JSON.parse(source) : undefined;
		} catch {
			parsed = undefined;
		}
		if (!source || !isObject(parsed) || parsed.schema !== (this.special ? STRUCTURE_SCHEMA_ID : FLOOR_PLAN_SCHEMA_ID)) {
			this.notificationService.warn(this.special
				? localize('building.noStructure', "The Structural Model is not valid yet. Open it and fix it first.")
				: localize('building.noFloorPlan', "The Floor Plan has no layout yet. Open it and create it first."));
			return;
		}
		let result: IGeneratedBuilding | undefined;
		this.frame.showProgress();
		try {
			result = await this.commands.executeCommand<IGeneratedBuilding>(this.special ? GENERATE_FROM_STRUCTURE_COMMAND : GENERATE_COMMAND, source, this.document ? JSON.stringify(this.document) : undefined);
		} catch (error) {
			this.notificationService.error(localize('building.generateFailed', "The building model could not be built: {0}", String(error)));
			return;
		} finally {
			this.frame.hideProgress();
		}
		if (result?.text) {
			this.replaceDocument(JSON.parse(result.text));
			// The building model is generated: saved at once, so no "save bim.json?" prompt follows.
			const resource = this.resource;
			if (resource) {
				await this.textFiles.save(resource);
			}
		} else {
			this.notificationService.warn(localize('building.problems', "Fix the {0} first: {1}", this.sourceName, (result?.problems ?? []).join('; ')));
		}
	}

	private openSource(): void {
		const resource = this.resource;
		const part = partById(this.special ? 'structure' : 'floorPlan')!;
		if (resource) {
			void this.editors.openEditor({ resource: joinPath(dirname(dirname(resource)), part.folder, part.mainFile!) });
		}
	}

	// ───────────────────────────── IFC: 3D view and export ─────────────────────────────

	private async ifc(): Promise<IBuildingIfc | undefined> {
		if (!this.document || this.objectsText === undefined) {
			return undefined;
		}
		return this.commands.executeCommand<IBuildingIfc>(IFC_COMMAND, {
			bimText: JSON.stringify(this.document),
			objectsText: this.objectsText,
			materialsText: this.materials?.getValue(),
			name: this.project.project?.name ?? 'Project',
		});
	}

	/** Reloads the 3D view from the IFC of the current model (debounced after every change). */
	private async refreshIfc(): Promise<void> {
		if (this.view !== '3d' || !this.document) {
			return;
		}
		this.renderEmptyNote();
		if (this.objectsText === undefined) {
			return; // scheduled again when the object types arrive (onCompanionChanged)
		}
		const version = ++this.ifcVersion;
		this.setLoading(true);
		let result: IBuildingIfc | undefined;
		try {
			result = await this.ifc();
		} catch (error) {
			result = { problems: [String(error)] };
		}
		if (version !== this.ifcVersion) {
			return; // a newer refresh owns the loading note
		}
		if (!result?.text) {
			this.setLoading(false);
			this.setIfcNote(localize('building.ifcProblems', "The 3D view could not be built: {0}", (result?.problems ?? []).join('; ')), 1);
			return;
		}
		this.setIfcNote(result.skipped?.length ? localize('building.ifcSkipped', "{0} not shown: {1}", result.skipped.length, result.skipped.join('; ')) : undefined, result.skipped?.length ?? 0);
		const viewer = await this.ensureViewer();
		if (viewer && version === this.ifcVersion) {
			try {
				this.architectureStories = result.architectureStories ?? {};
				await viewer.load(VSBuffer.fromString(result.text).buffer, result.ids ?? {});
				const selection = this.selectionService.selection;
				this.selectedElement ??= selection?.kind === 'member' ? this.elementOfMember(selection.id) : undefined;
				await viewer.setSelection(this.selectedElement);
				for (const layer of this.hiddenLayers) {
					await viewer.setLayerVisible(layer, false);
				}
				await this.applyStoryFilter();
				await this.renderLegend();
			} catch (error) {
				this.setIfcNote(localize('building.viewerLoadFailed', "The 3D view could not show the building: {0}", String(error)), 1);
			}
			this.renderProperties();
		}
		if (version === this.ifcVersion) {
			this.setLoading(false);
		}
	}

	private setLoading(loading: boolean): void {
		this.loadingNote?.classList.toggle('hidden', !loading);
	}

	/** What to do when the building has no elements yet (the 3D view would only show the ground grid). */
	private renderEmptyNote(): void {
		const elements = Array.isArray(this.document?.elements) ? this.document.elements.length : 0;
		const empty = !!this.document && !elements;
		this.emptyNote.classList.toggle('hidden', !empty);
		this.legend.classList.toggle('hidden', empty);
		this.emptyNote.textContent = empty
			? localize('building.empty3d', "Nothing to show yet: place columns, beams, walls and slabs in the {0}, then build the building model from it.", this.sourceName)
			: '';
	}

	/** The layers of the 3D view with their colours and counts; a click shows or hides one. */
	private async renderLegend(): Promise<void> {
		const viewer = this.viewer;
		if (!viewer) {
			return;
		}
		const layers = await viewer.layers();
		this.legendDisposables.clear();
		clearNode(this.legend);
		for (const { layer, count, color } of layers) {
			const hidden = this.hiddenLayers.has(layer);
			const button = append(this.legend, $<HTMLButtonElement>('button.building-legend-item', {
				type: 'button',
				'aria-pressed': String(!hidden),
				title: hidden ? localize('building.showLayer', "Show {0}", LAYER_LABELS[layer]) : localize('building.hideLayer', "Hide {0}", LAYER_LABELS[layer]),
			}));
			button.classList.toggle('off', hidden);
			const swatch = append(button, $('span.swatch'));
			swatch.style.backgroundColor = color;
			append(button, $('span.label', undefined, LAYER_LABELS[layer]));
			append(button, $('span.count', undefined, String(count)));
			this.legendDisposables.add(addDisposableListener(button, EventType.CLICK, async () => {
				if (this.hiddenLayers.has(layer)) {
					this.hiddenLayers.delete(layer);
				} else {
					this.hiddenLayers.add(layer);
				}
				await viewer.setLayerVisible(layer, !this.hiddenLayers.has(layer));
				await this.renderLegend();
			}));
		}
	}

	/** The story filter's choices: all stories, or one (the base shows the foundations). */
	private renderStoryFilter(): void {
		const select = this.storySelect;
		if (!select) {
			return;
		}
		const stories = this.sortedStories();
		if (this.storyFilter && !stories.some(s => s.id === this.storyFilter)) {
			this.storyFilter = undefined;
		}
		clearNode(select);
		append(select, $<HTMLOptionElement>('option', { value: '' }, localize('building.allStories', "All stories")));
		for (const story of stories) {
			append(select, $<HTMLOptionElement>('option', { value: String(story.id) }, `${story.name ?? story.id} (${formatElevation(Number(story.elevation))})`));
		}
		select.value = this.storyFilter ?? '';
		select.disabled = !stories.length;
	}

	private async applyStoryFilter(): Promise<void> {
		await this.viewer?.setVisibleElements(this.storyFilter ? this.elementsOnStory(this.storyFilter) : undefined);
	}

	private sortedStories(): JsonObject[] {
		const stories = Array.isArray(this.document?.stories) ? this.document.stories.filter(isObject) : [];
		return [...stories].sort((a, b) => Number(a.elevation) - Number(b.elevation));
	}

	/**
	 * The elements, additions and MEP items of story `id`: what stands below its floor up to it
	 * (columns, walls) and what is at its level (beams, slabs). The lowest story has the
	 * foundations.
	 */
	private elementsOnStory(id: string): string[] {
		const stories = this.sortedStories();
		const index = stories.findIndex(s => s.id === id);
		if (index < 0) {
			return [];
		}
		const top = Number(stories[index].elevation) + 1;
		const bottom = index > 0 ? Number(stories[index - 1].elevation) + 1 : -Infinity;
		const on = (z: number) => z > bottom && z <= top;
		const zs = (points: JsonValue | undefined) => (Array.isArray(points) ? points : []).map(p => Array.isArray(p) ? Number(p[2] ?? 0) : 0);
		const ids: string[] = [];
		for (const e of Array.isArray(this.document?.elements) ? this.document.elements.filter(isObject) : []) {
			const level = e.kind === 'column' || e.kind === 'wall' ? Number(e.top)
				: e.kind === 'member' ? Math.max(...zs([e.start, e.end] as JsonValue))
					: e.kind === 'area' || e.kind === 'block' ? Math.max(...zs(e.outline))
						: Number(e.elevation);
			if (on(level)) {
				ids.push(String(e.id));
			}
		}
		const additions = isObject(this.document?.additions) ? this.document.additions : {};
		for (const stair of Array.isArray(additions.stairs) ? additions.stairs.filter(isObject) : []) {
			if (stair.top === id) {
				ids.push(String(stair.id));
			}
		}
		for (const member of Array.isArray(additions.members) ? additions.members.filter(isObject) : []) {
			if (on(Math.max(...zs([member.start, member.end] as JsonValue)))) {
				ids.push(String(member.id));
			}
		}
		for (const { item } of this.mepItems()) {
			if (item.story === id || item.toStory === id) {
				ids.push(String(item.id), `${item.id}/plinth`, `${item.id}-base`);
			}
		}
		// The architecture standing on the story below, as the columns rising to this one.
		const below = index > 0 ? String(stories[index - 1].id) : undefined;
		for (const [element, story] of Object.entries(this.architectureStories)) {
			if (story === below) {
				ids.push(element);
			}
		}
		return ids;
	}

	/** The items of 7 MEP that the 3D view draws, with the list each is in. */
	private mepItems(): { readonly item: JsonObject; readonly label: string }[] {
		const mep = this.parse(this.mep?.getValue());
		if (!isObject(mep)) {
			return [];
		}
		return MEP_LISTS.flatMap(({ path, label }) => {
			let value: JsonValue | undefined = mep;
			for (const key of path) {
				value = isObject(value) ? value[key] : undefined;
			}
			return (Array.isArray(value) ? value.filter(isObject) : []).map(item => ({ item, label }));
		});
	}

	/** The MEP item drawn as `elementId` (its plinth and tank base count as the item). */
	private findMepItem(elementId: string): { readonly item: JsonObject; readonly label: string } | undefined {
		const id = elementId.replace(/(\/plinth|-base|\/\d+)$/, '');
		return this.mepItems().find(({ item }) => item.id === id);
	}

	private ensureViewer(): Promise<BuildingViewer | undefined> {
		if (!this.viewerLoading) {
			this.viewerLoading = (async () => {
				try {
					const { createBuildingViewer } = await loadViewerModule();
					const viewer = this.viewer = createBuildingViewer(this.viewport, {
						assetBaseUrl: viewerAssetBaseUrl(),
						theme: this.viewerTheme(),
						onSelectionChanged: elementId => this.onViewerSelection(elementId),
					});
					this.viewerDisposable.value = toDisposable(() => viewer.dispose());
					return viewer;
				} catch (error) {
					this.viewerLoading = undefined;
					this.setIfcNote(localize('building.viewerFailed', "The 3D view could not start: {0}", String(error)), 1);
					return undefined;
				}
			})();
		}
		return this.viewerLoading;
	}

	/** Canvas, ground grid and selection in the theme's colours, so the 3D view follows light and dark. */
	private viewerTheme(): { background: string; grid?: string; selection?: string } {
		const theme = this.themeService.getColorTheme();
		const color = (id: string) => {
			const value = theme.getColor(id);
			return value ? Color.Format.CSS.formatHex(value) : undefined; // three.js reads #rrggbb only
		};
		return { background: color(editorBackground) ?? '#1e1e1e', grid: color(chartsLines), selection: color(chartsYellow) };
	}

	/** An element picked in 3D selects its floor-plan member (Properties, Model Explorer, plan). */
	private onViewerSelection(elementId: string | undefined): void {
		const elements = Array.isArray(this.document?.elements) ? this.document.elements.filter(isObject) : [];
		const element = elements.find(e => e.id === elementId);
		const group = ELEMENT_KINDS.find(k => k.kind === element?.kind)?.group;
		const member = typeof element?.source === 'string' ? element.source : undefined;
		this.selectedElement = elementId;
		this.selectionService.setSelection(group && member ? { kind: 'member', group, id: member } : undefined, SELECTION_SOURCE);
		this.renderProperties();
	}

	/** Writes the IFC to `11 Exports/IFC/<project>.ifc`. */
	async exportIfc(): Promise<void> {
		const resource = this.resource;
		let result: IBuildingIfc | undefined;
		try {
			result = await this.ifc();
		} catch (error) {
			result = { problems: [String(error)] };
		}
		if (!resource || !result?.text) {
			this.notificationService.error(localize('building.exportFailed', "The IFC could not be written: {0}", (result?.problems ?? []).join('; ')));
			return;
		}
		const exports = PROJECT_PARTS.find(p => p.id === 'exports')!;
		const name = (this.project.project?.name ?? 'Project').replace(/[\\/:*?"<>|]/g, '-');
		const target = joinPath(dirname(dirname(resource)), exports.folder, 'IFC', `${name}.ifc`);
		await this.fileService.writeFile(target, VSBuffer.fromString(result.text));
		this.notificationService.notify({
			severity: result.skipped?.length ? Severity.Warning : Severity.Info,
			message: result.skipped?.length
				? localize('building.exportedSkipped', "Exported {0}/IFC/{1}.ifc without: {2}", exports.folder, name, result.skipped.join('; '))
				: localize('building.exported', "Exported {0}/IFC/{1}.ifc ({2} elements).", exports.folder, name, Object.keys(result.ids ?? {}).length),
		});
	}

	// ───────────────────────────── rendering ─────────────────────────────

	/** The view shown, for the sidebar's entries under BIM. */
	get partSection(): string | undefined {
		return this.view;
	}

	/** `section` (from the sidebar) shows that view. */
	protected override applyOptions(options: IEditorOptions | undefined): void {
		const section = sectionOption(options);
		const view = VIEWS.find(v => v.view === section)?.view;
		if (view) {
			this.showView(view);
			this.render();
		}
	}

	private showView(view: View): void {
		if (this.view !== view) {
			this.view = view;
			this._onDidChangePartSection.fire();
		}
		this.viewport.classList.toggle('hidden', view !== '3d' || !this.document);
		this.summary.classList.toggle('hidden', view !== 'summary');
		this.additions.classList.toggle('hidden', view !== 'additions');
		// What the Additions view is for: the frame's "?" (hover, click or Enter), only in that view.
		this.documentFrame?.setHelp(view === 'additions'
			? localize('building.additionsIntro', "What the building model adds to the Floor Plan: openings cut into slabs and walls, stairs between stories, and braces, sloped beams or raking columns. Rebuilding from the Floor Plan keeps them; openings follow their slab or wall.")
			: undefined);
		for (const [id, button] of this.viewButtons) {
			button.classList.toggle('active', id === view);
			button.setAttribute('aria-selected', String(id === view));
		}
		if (view === '3d') {
			this.ifcScheduler.schedule(0);
			this.viewer?.layout();
		}
		this.updateChrome();
	}

	private setIfcNote(note: string | undefined, skipped = 0): void {
		this.ifcNote = note;
		this.ifcSkipped = skipped;
		this.updateChrome();
	}

	/** The element of the building model built from floor-plan member `member`. */
	private elementOfMember(member: string): string | undefined {
		const elements = Array.isArray(this.document?.elements) ? this.document.elements.filter(isObject) : [];
		return elements.find(e => e.source === member)?.id as string | undefined;
	}

	/** The toolbar (Rebuild stands out only when the source changed), the pill and the status line. */
	private updateChrome(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const stale = this.stale;
		const built = !!this.document;
		this.rebuildAction.label = this.built ? localize('building.rebuild', "Rebuild from {0}", this.sourceName) : localize('building.build', "Build from {0}", this.sourceName);
		this.openSourceAction.label = localize('building.openSource', "Open {0}", this.sourceName);
		this.exportAction.enabled = built;
		this.fitAction.enabled = built && this.view === '3d';
		this.updateDocumentFrameActions();
		for (const [view, button] of this.viewButtons) {
			button.disabled = !built && view !== '3d';
		}
		if (this.document) {
			frame.setStatus(this.status(stale)); // otherwise the frame says why it cannot show the file
		}
	}

	/** Rebuild is an icon button only while the source changed (or it was never built); else in "...". */
	protected override documentFrameActions(): IDocumentFrameActions {
		const frame = this.frame;
		if (!frame) {
			return { primary: [] };
		}
		const prominent = this.stale || !this.document;
		return {
			primary: [...(prominent ? [this.rebuildAction] : []), ...(this.view === '3d' && this.document ? [this.fitAction] : []), frame.togglePropertiesAction],
			secondary: [...(prominent ? [] : [this.rebuildAction]), this.openSourceAction, new Separator(), this.exportAction],
		};
	}

	/** Whether the model was ever built from its source (a new project's file only has the schema). */
	private get built(): boolean {
		const part = upstreamPart('bim', this.project.parts) ?? (this.special ? 'structure' : 'floorPlan');
		return !!this.document && !!recordedStamp(this.document, part);
	}

	/** The checks' problems and the elements the 3D view leaves out, together. */
	private get problemCount(): number {
		return this.problems.length + this.ifcSkipped;
	}

	private status(stale: boolean): IEditorFrameStatus | undefined {
		const document = this.document;
		if (!document) {
			return undefined; // the banner says why and how to build it
		}
		if (!this.built) {
			return {
				text: localize('building.statusNotBuilt', "Not built yet: build the building model from the {0}.", this.sourceName),
				link: { label: localize('building.buildLink', "Build"), run: () => void this.build() },
			};
		}
		const elements = Array.isArray(document.elements) ? document.elements.filter(isObject) : [];
		const stories = this.storiesAboveBase();
		const own = elements.filter(e => typeof e.source !== 'string').length;
		const count = elements.length === 1 ? localize('building.statusOneElement', "1 element") : localize('building.statusElements', "{0} elements", elements.length);
		const where = stories === 1 ? localize('building.statusOneStory', "on 1 story above the base") : localize('building.statusStories', "on {0} stories above the base", stories);
		const parts = [own
			? localize('building.statusOwn', "{0} ({1} of its own) {2}", count, own, where)
			: localize('building.statusCount', "{0} {1}", count, where)];
		if (stale) {
			parts.push(localize('building.statusStale', "the {0} changed since it was built", this.sourceName));
		}
		const problems = this.problemCount;
		if (problems) {
			parts.push(problems === 1 ? localize('building.statusProblem', "1 problem") : localize('building.statusProblems', "{0} problems", problems));
		}
		return {
			text: parts.join('  ·  '),
			severity: problems ? 'warning' : undefined,
			link: stale ? { label: localize('building.rebuildLink', "Rebuild"), run: () => void this.build() }
				: problems ? { label: localize('building.details', "Details"), run: () => this.showProblems() }
					: undefined,
		};
	}

	/** Stories above the lowest one (the base, where the footings are). */
	private storiesAboveBase(): number {
		return Math.max(0, this.sortedStories().length - 1);
	}

	/** "Details": the problems in Properties (the model's summary), scrolled into view. */
	private showProblems(): void {
		if (this.selectedElement) {
			this.selectedElement = undefined;
			void this.viewer?.setSelection(undefined);
			this.selectionService.setSelection(undefined, SELECTION_SOURCE);
		}
		this.frame.setPropertiesVisible(true);
		this.renderProperties();
		this.problemsHeading?.scrollIntoView({ block: 'nearest' });
		this.problemsHeading?.focus({ preventScroll: true });
	}

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.summary);
		clearNode(this.additions);
		this.additionsProblems = undefined;
		this.viewport.classList.toggle('hidden', this.view !== '3d' || !this.document);
		this.renderEmptyNote();
		if (this.document && this.view === '3d') {
			this.ifcScheduler.schedule();
		}
		this.updateChrome();
		this.renderProperties();
		if (!this.document) {
			return; // the frame shows why, and how to build it
		}

		// Models built before additions existed have none yet; the lists are written on the first edit.
		const additions = isObject(this.document.additions) ? this.document.additions : (this.document.additions = {});
		for (const list of Object.keys(ADDITION_LISTS)) {
			if (!Array.isArray(additions[list])) {
				additions[list] = [];
			}
		}
		// The problems of the additions (a host, story or type that does not exist, an opening past
		// its wall), above the form so they are seen where they are fixed.
		this.additionsProblems = append(this.additions, $('.library-problems'));
		this.renderAdditionsProblems();
		this.form.render(append(this.additions, $('.library-form')), BIM_SCHEMA, this.document, GENERATED);
		this.renderStoryFilter();

		const stories = this.sortedStories();
		const elements = Array.isArray(this.document.elements) ? this.document.elements.filter(isObject) : [];

		append(this.summary, $('h3', undefined, stories.length > 1
			? localize('building.storiesAboveBase', "Stories ({0} above the base)", stories.length - 1)
			: localize('building.stories', "Stories")));
		const storyTable = append(this.summary, $('.building-table'));
		// The height of a story is from the story below up to its own level; the base has none.
		for (const header of [localize('building.story', "Story"), localize('building.storyId', "ID"), localize('building.elevation', "Elevation (mm)"), localize('building.heightBelow', "Height from below (mm)")]) {
			append(storyTable, $('span.header', undefined, header));
		}
		stories.forEach((story, i) => {
			const below = stories[i - 1];
			append(storyTable, $('span', undefined, String(story.name ?? story.id) + (i === 0 && stories.length > 1 && !/base/i.test(String(story.name ?? story.id)) ? ` ${localize('building.baseSuffix', "(base)")}` : '')));
			append(storyTable, $('span', undefined, String(story.id)));
			append(storyTable, $('span.number', undefined, String(story.elevation)));
			append(storyTable, $('span.number', undefined, below ? String(Number(story.elevation) - Number(below.elevation)) : '—'));
		});
		if (!stories.length) {
			append(this.summary, $('p.building-note', undefined, localize('building.noStories', "No stories yet.")));
		}

		append(this.summary, $('h3', undefined, localize('building.additionsHeading', "Additions")));
		const additionTable = append(this.summary, $('.building-table.two'));
		for (const [list, label] of [
			['slabOpenings', localize('building.slabOpenings', "Slab openings")],
			['wallOpenings', localize('building.wallOpenings', "Wall openings")],
			['stairs', localize('building.stairs', "Stairs")],
			['members', localize('building.inclinedMembers', "Inclined members")],
		]) {
			append(additionTable, $('span', undefined, label));
			append(additionTable, $('span.number', undefined, String(Array.isArray(additions[list]) ? additions[list].length : 0)));
		}

		append(this.summary, $('h3', undefined, localize('building.elements', "Elements")));
		const elementTable = append(this.summary, $('.building-table'));
		for (const header of [localize('building.kind', "Kind"), localize('building.fromSource', "From {0}", this.sourceName), localize('building.own', "Own"), localize('building.total', "Total")]) {
			append(elementTable, $('span.header', undefined, header));
		}
		for (const { kind, label } of ELEMENT_KINDS) {
			const ofKind = elements.filter(e => e.kind === kind);
			const generated = ofKind.filter(e => typeof e.source === 'string').length;
			append(elementTable, $('span', undefined, label));
			append(elementTable, $('span.number', undefined, String(generated)));
			append(elementTable, $('span.number', undefined, String(ofKind.length - generated)));
			append(elementTable, $('span.number', undefined, String(ofKind.length)));
		}
		if (this.problemCount) {
			const link = append(this.summary, $<HTMLAnchorElement>('a.building-problems-link', { role: 'button', tabIndex: 0 }, this.problemCount === 1
				? localize('building.summaryProblem', "1 problem: see Properties")
				: localize('building.summaryProblems', "{0} problems: see Properties", this.problemCount)));
			this.viewDisposables.add(addDisposableListener(link, EventType.CLICK, () => this.showProblems()));
		}
	}

	/** The checks' problems with the additions, as a list above the Additions form. */
	private renderAdditionsProblems(): void {
		const box = this.additionsProblems;
		if (!box) {
			return;
		}
		clearNode(box);
		const problems = this.problems.filter(p => p.path.startsWith('additions'));
		box.classList.toggle('visible', problems.length > 0);
		for (const problem of problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(row, $('span', undefined, problem.message));
		}
	}

	// ───────────────────────────── properties panel ─────────────────────────────

	/** An element or addition of the building model by id, and the list it is in. */
	private findElement(id: string): { readonly item: JsonObject; readonly list: string } | undefined {
		const document = this.document;
		if (!document) {
			return undefined;
		}
		const element = (Array.isArray(document.elements) ? document.elements.filter(isObject) : []).find(e => e.id === id);
		if (element) {
			return { item: element, list: 'elements' };
		}
		const additions = isObject(document.additions) ? document.additions : {};
		for (const list of Object.keys(ADDITION_LISTS)) {
			const item = (Array.isArray(additions[list]) ? (additions[list] as JsonValue[]).filter(isObject) : []).find(e => e.id === id);
			if (item) {
				return { item, list };
			}
		}
		return undefined;
	}

	/**
	 * The selected element: its own values, then (for one built from the floor plan) the member's
	 * placement and object type; with nothing selected, the model's summary and its problems.
	 */
	private renderProperties(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		this.propertiesDisposables.clear();
		clearNode(panel);
		this.problemsHeading = undefined;
		const document = this.document;
		if (!document) {
			appendPropertyNote(panel, localize('building.propertiesEmpty', "Build the building model to see its elements here."));
			return;
		}
		if (this.selectedElement?.startsWith(ARCHITECTURE_ID)) {
			// An item of the architecture (05 Floor Plan/architecture.json): edited in its own editor.
			appendPropertyHeading(panel, this.selectedElement.slice(ARCHITECTURE_ID.length), localize('building.architectureItem', "Architecture"));
			appendPropertyNote(panel, localize('building.architectureNote', "Architecture is physical only: it adds no stiffness to the analysis. Its loads come in a later round."));
			propertyLink(panel, localize('building.openArchitecture', "Open in Architecture"), () => void this.commands.executeCommand('saengine.architecture.open'), this.propertiesDisposables);
			return;
		}
		const found = this.selectedElement ? this.findElement(this.selectedElement) : undefined;
		if (found) {
			const { item, list } = found;
			const kindLabel = ELEMENT_KINDS.find(k => k.kind === item.kind)?.label;
			appendPropertyHeading(panel, String(item.id), list === 'elements' ? (typeof item.kind === 'string' ? humanize(item.kind) : kindLabel) : humanize(list));
			append(panel, $('.sa-props-section', undefined, localize('building.elementSection', "Building Model")));
			// The schema definition of the item, for the units of its values (mm, °).
			const definition = list === 'elements'
				? typeof item.kind === 'string' && `${item.kind.charAt(0).toUpperCase()}${item.kind.slice(1)}Element`
				: ADDITION_DEFINITIONS[list];
			for (const [key, value] of Object.entries(item)) {
				if (key === 'id' || value === null || typeof value === 'object' && !Array.isArray(value)) {
					continue;
				}
				const text = key === 'kind' && typeof value === 'string' ? humanize(value) : formatPropertyValue(value, definition ? schemaUnit(BIM_SCHEMA, definition, key) : undefined);
				appendPropertyRow(panel, key === 'source' ? localize('building.sourceRow', "From {0}", this.sourceName) : humanize(key), text);
			}
			if (typeof item.source !== 'string' && list === 'elements') {
				appendPropertyNote(panel, localize('building.ownElement', "An element of the building model itself: rebuilding keeps it."));
			}
			const group = ELEMENT_KINDS.find(k => k.kind === item.kind)?.group;
			const sheet = group && typeof item.source === 'string' && !this.special ? propertySheet({ kind: 'member', group, id: item.source }, {
				floorPlan: this.parse(this.source.value?.object.textEditorModel.getValue()),
				floorPlanText: this.source.value?.object.textEditorModel.getValue(),
				objects: this.parse(this.objectsText),
				materials: this.parse(this.materials?.getValue()),
				bim: document,
			}) : undefined;
			if (sheet && group) {
				const member: ModelSelection = { kind: 'member', group, id: String(item.source) };
				const root = this.resource && dirname(dirname(this.resource));
				// The member's placement and object type (its last section, the building model's state, is this editor).
				renderPropertySheet(panel, { ...sheet, title: localize('building.memberHeading', "{0} in the {1}", sheet.title, this.sourceName), subtitle: sheet.subtitle, sections: sheet.sections.slice(0, -1) },
					this.propertiesDisposables,
					action => void openOwner(action === 'editObjectType' && sheet.objectType ? { kind: 'objectType', id: sheet.objectType } : member, action === 'editObjectType' ? 'objects' : 'floorPlan', root, this.editors));
			}
			return;
		}
		const mepItem = this.selectedElement ? this.findMepItem(this.selectedElement) : undefined;
		if (mepItem) {
			this.renderMepProperties(panel, mepItem.item, mepItem.label);
			return;
		}
		const elements = Array.isArray(document.elements) ? document.elements.filter(isObject) : [];
		appendPropertyHeading(panel, localize('building.modelHeading', "Building Model"));
		appendPropertyRow(panel, localize('building.storiesRow', "Stories above the base"), String(this.storiesAboveBase()));
		for (const { kind, label } of ELEMENT_KINDS) {
			const count = elements.filter(e => e.kind === kind).length;
			if (count) {
				appendPropertyRow(panel, label, String(count));
			}
		}
		const additions = isObject(document.additions) ? document.additions : {};
		const added = Object.keys(ADDITION_LISTS).reduce((n, list) => n + (Array.isArray(additions[list]) ? (additions[list] as JsonValue[]).length : 0), 0);
		appendPropertyRow(panel, localize('building.additionsRow', "Additions"), String(added));
		appendPropertyRow(panel, localize('building.builtRow', "Built from the {0}", this.sourceName),
			!this.built ? localize('building.notBuilt', "Not built yet") : this.stale ? localize('building.outOfDate', "Out of date") : localize('building.upToDate', "Up to date"), this.stale);
		if (this.problemCount) {
			const heading = this.problemsHeading = appendPropertyHeading(panel, localize('building.problemsHeading', "Problems"), String(this.problemCount));
			heading.classList.add('building-problems-heading');
			heading.tabIndex = -1;
			for (const problem of this.problems) {
				appendPropertyNote(panel, problem.message).classList.add('building-problem');
			}
			if (this.ifcNote) {
				appendPropertyNote(panel, this.ifcNote).classList.add('building-problem');
			}
		}
		appendPropertyNote(panel, localize('building.selectHint', "Select an element in the 3D view to see its properties."));
	}

	/** An item of 7 MEP picked in 3D: its values, and a link to edit it in 7 MEP (which owns it). */
	private renderMepProperties(panel: HTMLElement, item: JsonObject, label: string): void {
		appendPropertyHeading(panel, String(item.id), label);
		append(panel, $('.sa-props-section', undefined, localize('building.mepSection', "7 MEP")));
		for (const [key, value] of Object.entries(item)) {
			if (key === 'id' || value === null || typeof value === 'object') {
				continue;
			}
			const unit = /^(x|y|length|width|height|elevation|diameter|size)$/.test(key) ? 'mm' : /weight/i.test(key) ? 'kN' : undefined;
			appendPropertyRow(panel, humanize(key), formatPropertyValue(value, unit));
		}
		const open = append(panel, $<HTMLAnchorElement>('a.sa-props-link', { role: 'button', tabIndex: 0 }, localize('building.openMep', "Edit in 7 MEP")));
		this.propertiesDisposables.add(addDisposableListener(open, EventType.CLICK, () => {
			const part = partById('mep');
			const resource = this.resource;
			if (part?.mainFile && resource) {
				void this.editors.openEditor({ resource: joinPath(dirname(dirname(resource)), part.folder, part.mainFile) });
			}
		}));
		appendPropertyNote(panel, localize('building.mepNote', "Drawn from the coordination model of 7 MEP; change it there."));
	}

	private parse(text: string | undefined): JsonValue | undefined {
		try {
			return text ? JSON.parse(text) : undefined;
		} catch {
			return undefined;
		}
	}

	// ───────────────────────────── additions form ─────────────────────────────

	private get stories(): string[] {
		const stories = Array.isArray(this.document?.stories) ? this.document.stories.filter(isObject) : [];
		return stories.sort((a, b) => Number(a.elevation) - Number(b.elevation)).map(s => String(s.id));
	}

	private elementIds(kind: string): string[] {
		const elements = Array.isArray(this.document?.elements) ? this.document.elements.filter(isObject) : [];
		return elements.filter(e => e.kind === kind).map(e => String(e.id));
	}

	private typeIds(kinds: readonly string[]): string[] {
		let objects: JsonValue | undefined;
		try {
			objects = this.objectsText ? JSON.parse(this.objectsText) : undefined;
		} catch {
			objects = undefined;
		}
		const list = isObject(objects) && Array.isArray(objects.objects) ? objects.objects.filter(isObject) : [];
		// In the order of `kinds`: braces before beams before columns for inclined members.
		return kinds.flatMap(kind => list.filter(o => o.kind === kind).map(o => String(o.id)));
	}

	/** Pick lists: the slab or wall an opening cuts, stories, and object types of the right kind. */
	private references(path: string): readonly string[] | undefined {
		// The form asks with the list indexes left out ("additions.wallOpenings.host").
		const match = /^additions\.(?<list>\w+)(?:\.\d+)?\.(?<field>\w+)$/.exec(path);
		switch (match && `${match.groups!.list}.${match.groups!.field}`) {
			case 'slabOpenings.host': return this.elementIds('slab');
			case 'wallOpenings.host': return this.elementIds('wall');
			case 'stairs.type': return this.typeIds(['staircase']);
			case 'stairs.base':
			case 'stairs.top': return this.stories;
			case 'members.type': return this.typeIds(['brace', 'beam', 'column']);
		}
		return undefined;
	}

	/** Ids are unique across the elements and all additions. */
	private validate(path: string, value: string): string | undefined {
		const match = /^additions\.(?<list>\w+)\.(?<index>\d+)\.id$/.exec(path);
		if (!match || !this.document) {
			return undefined;
		}
		const additions = isObject(this.document.additions) ? this.document.additions : {};
		const own = (additions[match.groups!.list] as JsonValue[] | undefined)?.[Number(match.groups!.index)];
		const taken = [
			...(Array.isArray(this.document.elements) ? this.document.elements : []),
			...Object.values(additions).flatMap(list => Array.isArray(list) ? list : []),
		].filter(isObject).filter(item => item !== own).map(item => item.id);
		return taken.includes(value) ? localize('building.idTaken', "Another element already uses the id {0}.", value) : undefined;
	}

	/** A new addition with the next free id and the first host, type or stories that fit. */
	private newItem(path: string, list: readonly JsonValue[]): JsonObject | undefined {
		const name = /^additions\.(?<list>\w+)$/.exec(path)?.groups?.list;
		const prefix = name && ADDITION_LISTS[name];
		if (!name || !prefix || !this.document) {
			return undefined;
		}
		const defName = ADDITION_DEFINITIONS[name];
		const item = clone((TEMPLATES[defName] ?? {}) as JsonObject);
		const additions = isObject(this.document.additions) ? this.document.additions : {};
		const used = new Set([
			...(Array.isArray(this.document.elements) ? this.document.elements : []),
			...Object.values(additions).flatMap(l => Array.isArray(l) ? l : []),
			...list,
		].filter(isObject).map(i => String(i.id)));
		let n = 1;
		while (used.has(`${prefix}${n}`)) {
			n++;
		}
		item.id = `${prefix}${n}`;
		// Optional values the template leaves out get the schema's default (a slab opening's
		// rotation 0), so the new row has no empty field the form calls invalid.
		const properties = BIM_SCHEMA.$defs?.[defName]?.properties ?? {};
		for (const [key, property] of Object.entries(properties)) {
			if (item[key] === undefined && property.default !== undefined && property.default !== null && typeof property.default !== 'object') {
				item[key] = property.default as JsonValue;
			}
		}
		const first = (values: readonly string[]) => values[0];
		if (name === 'slabOpenings') {
			item.host = first(this.elementIds('slab')) ?? item.host;
			// In the middle of its slab, not at the origin (which may be outside it).
			const centre = this.slabCentre(String(item.host));
			if (centre) {
				[item.x, item.y] = centre;
			}
		} else if (name === 'wallOpenings') {
			item.host = first(this.elementIds('wall')) ?? item.host;
		} else if (name === 'stairs') {
			const types = this.typeIds(['staircase']);
			item.type = first(types) ?? item.type;
			[item.base, item.top] = [this.stories[0] ?? item.base, this.stories[1] ?? item.top];
			if (!types.length) {
				// The template's type does not exist in this project: say where to add one.
				this.notificationService.prompt(Severity.Warning,
					localize('building.noStaircaseType', "There is no staircase type in 04 Objects yet. Add one there, then pick it as this stair's object type."),
					[{ label: localize('building.openObjects', "Open 04 Objects"), run: () => this.openObjects() }]);
			}
		} else {
			item.type = first(this.typeIds(['brace', 'beam', 'column'])) ?? item.type;
		}
		return item;
	}

	/** The centre of a slab element's boundary (the mean of its corners), rounded to the mm. */
	private slabCentre(id: string): [number, number] | undefined {
		const slab = (Array.isArray(this.document?.elements) ? this.document.elements.filter(isObject) : []).find(e => e.id === id);
		const corners = slab && Array.isArray(slab.boundary)
			? slab.boundary.filter((p): p is number[] => Array.isArray(p) && p.length >= 2 && p.every(c => typeof c === 'number'))
			: [];
		if (!corners.length) {
			return undefined;
		}
		const mean = (i: number) => Math.round(corners.reduce((sum, p) => sum + p[i], 0) / corners.length);
		return [mean(0), mean(1)];
	}

	/** 04 Objects, where staircase types are added. */
	private openObjects(): void {
		const objects = partById('objects');
		const resource = this.resource;
		if (objects?.mainFile && resource) {
			void this.editors.openEditor({ resource: joinPath(dirname(dirname(resource)), objects.folder, objects.mainFile) });
		}
	}

	protected renderProblems(): void {
		this.updateChrome();
		this.renderProperties();
		this.renderAdditionsProblems();
	}
}
