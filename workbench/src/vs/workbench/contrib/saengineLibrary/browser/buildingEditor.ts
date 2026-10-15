/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { BuildingViewer } from '@saengine/fem-viewer';
import { $, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { BIM_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { editorBackground } from '../../../../platform/theme/common/colors/editorColors.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService, MemberGroup } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProjectService, partById, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';
import { loadViewerModule, viewerAssetBaseUrl } from '../../saengineFem/browser/viewerModule.js';
import { clone, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

const BIM_SCHEMA_ID = 'saengine.bim/2';
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
}

const ELEMENT_KINDS: readonly { readonly kind: string; readonly group?: MemberGroup; readonly label: string }[] = [
	{ kind: 'column', group: 'columns', label: localize('element.columns', "Columns") },
	{ kind: 'beam', group: 'beams', label: localize('element.beams', "Beams") },
	{ kind: 'wall', group: 'walls', label: localize('element.walls', "Walls") },
	{ kind: 'slab', group: 'slabs', label: localize('element.slabs', "Slabs") },
	{ kind: 'footing', group: 'footings', label: localize('element.footings', "Footings") },
	{ kind: 'member', label: localize('element.members', "Members") },
	{ kind: 'area', label: localize('element.areas', "Areas") },
];

type View = '3d' | 'additions' | 'summary';

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: '3d', label: localize('building.view3d', "3D View"), icon: Codicon.symbolStructure },
	{ view: 'additions', label: localize('building.viewAdditions', "Additions"), icon: Codicon.add },
	{ view: 'summary', label: localize('building.viewSummary', "Summary"), icon: Codicon.listFlat },
];

/** Additions lists, the id prefix of their new entries, and the elements or objects they refer to. */
const ADDITION_LISTS: { readonly [list: string]: string } = {
	slabOpenings: 'O',
	wallOpenings: 'D',
	stairs: 'ST',
	members: 'M',
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
export class BuildingEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.BUILDING_EDITOR_ID;

	private header!: HTMLElement;
	private status!: HTMLElement;
	private viewport!: HTMLElement;
	private summary!: HTMLElement;
	private additions!: HTMLElement;
	private readonly form: SchemaForm;
	private problemBox: HTMLElement | undefined;
	private view: View = '3d';

	private viewer: BuildingViewer | undefined;
	private viewerLoading: Promise<BuildingViewer | undefined> | undefined;
	private readonly viewerDisposable = this._register(new MutableDisposable());
	private readonly ifcScheduler = this._register(new RunOnceScheduler(() => this.refreshIfc(), 400));
	private ifcVersion = 0;
	private ifcNote: string | undefined;

	private objectsText: string | undefined;
	private materials: ITextModel | undefined;

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
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super(BuildingEditor.ID, group, telemetryService, themeService, storageService, commands, editors, textModels, project);
		this.form = instantiationService.createInstance(SchemaForm, {
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
				void this.viewer?.setSelection(selection?.kind === 'member' ? selection.id : undefined);
			}
		}));
		this._register(themeService.onDidColorThemeChange(() => void this.viewer?.setTheme(this.viewerTheme())));
	}

	protected createBody(body: HTMLElement): void {
		const container = append(body, $('.building-editor.building-3d'));
		this.header = append(container, $('.building-header'));
		this.status = append(container, $('.building-status'));
		this.viewport = append(container, $('.building-viewport'));
		this.summary = append(container, $('.building-summary-view'));
		this.additions = append(container, $('.building-additions-view'));
		this.showView(this.view);
	}

	override async setInput(input: LibraryEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		this.materials = undefined;
		await super.setInput(input, options, context, token);
		// Material names for the IFC, read from the materials file (unsaved edits included).
		const part = PROJECT_PARTS.find(p => p.id === 'materials')!;
		try {
			const reference = await this.textModels.createModelReference(joinPath(dirname(dirname(input.resource)), part.folder, part.mainFile!));
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
		this.ifcScheduler.schedule();
	}

	override clearInput(): void {
		this.ifcScheduler.cancel();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		super.layout(dimension);
		this.viewer?.layout();
	}

	override dispose(): void {
		this.viewer?.dispose();
		this.viewer = undefined;
		super.dispose();
	}

	protected override onCompanionChanged(text: string): void {
		this.objectsText = text;
		this.ifcScheduler.schedule();
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

	/** Generates the model from the current Part 5 model, keeping the model's own elements. */
	private async build(): Promise<void> {
		const source = this.upstreamText;
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
		try {
			result = await this.commands.executeCommand<IGeneratedBuilding>(this.special ? GENERATE_FROM_STRUCTURE_COMMAND : GENERATE_COMMAND, source, this.document ? JSON.stringify(this.document) : undefined);
		} catch (error) {
			this.notificationService.error(localize('building.generateFailed', "The building model could not be built: {0}", String(error)));
			return;
		}
		if (result?.text) {
			this.replaceDocument(JSON.parse(result.text));
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
		const version = ++this.ifcVersion;
		let result: IBuildingIfc | undefined;
		try {
			result = await this.ifc();
		} catch (error) {
			result = { problems: [String(error)] };
		}
		if (version !== this.ifcVersion || !result) {
			return;
		}
		if (!result.text) {
			this.setIfcNote(localize('building.ifcProblems', "The 3D view could not be built: {0}", (result.problems ?? []).join('; ')));
			return;
		}
		this.setIfcNote(result.skipped?.length ? localize('building.ifcSkipped', "Not shown: {0}", result.skipped.join('; ')) : undefined);
		const viewer = await this.ensureViewer();
		if (viewer && version === this.ifcVersion) {
			await viewer.load(VSBuffer.fromString(result.text).buffer, result.ids ?? {});
			const selection = this.selectionService.selection;
			await viewer.setSelection(selection?.kind === 'member' ? selection.id : undefined);
		}
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
					this.setIfcNote(localize('building.viewerFailed', "The 3D view could not start: {0}", String(error)));
					return undefined;
				}
			})();
		}
		return this.viewerLoading;
	}

	private viewerTheme(): { background: string } {
		return { background: this.themeService.getColorTheme().getColor(editorBackground)?.toString() ?? '#1e1e1e' };
	}

	/** An element picked in 3D selects its floor-plan member (Properties, Model Explorer, plan). */
	private onViewerSelection(elementId: string | undefined): void {
		const elements = Array.isArray(this.document?.elements) ? this.document.elements.filter(isObject) : [];
		const element = elements.find(e => e.id === elementId);
		const group = ELEMENT_KINDS.find(k => k.kind === element?.kind)?.group;
		const member = typeof element?.source === 'string' ? element.source : undefined;
		this.selectionService.setSelection(group && member ? { kind: 'member', group, id: member } : undefined, SELECTION_SOURCE);
	}

	/** Writes the IFC to `11 Exports/IFC/<project>.ifc`. */
	private async exportIfc(): Promise<void> {
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

	private showView(view: View): void {
		this.view = view;
		this.viewport.classList.toggle('hidden', view !== '3d');
		this.summary.classList.toggle('hidden', view !== 'summary');
		this.additions.classList.toggle('hidden', view !== 'additions');
		if (view === '3d') {
			this.ifcScheduler.schedule(0);
			this.viewer?.layout();
		}
	}

	private setIfcNote(note: string | undefined): void {
		this.ifcNote = note;
		clearNode(this.status);
		this.status.classList.toggle('visible', !!note);
		if (note) {
			append(this.status, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
			append(this.status, $('span', undefined, note));
		}
	}

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.header);
		clearNode(this.summary);
		clearNode(this.additions);
		this.problemBox = undefined;

		const title = append(this.header, $('.building-title'));
		append(title, $('h2', undefined, localize('building.title', "Building Model")));
		append(title, $('span.building-intro', undefined, localize('building.intro', "Built from the {0}; update it when the {0} changes. Elements added to the building model itself are kept.", this.sourceName)));

		const actions = append(this.header, $('.building-actions'));
		const button = (label: string, icon: ThemeIcon, run: () => void, secondary = true) => {
			const b = this.viewDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary, supportIcons: true }));
			b.label = `$(${icon.id}) ${label}`;
			this.viewDisposables.add(b.onDidClick(run));
			return b;
		};
		button(localize('building.openSource', "Open {0}", this.sourceName), Codicon.symbolArray, () => this.openSource());
		if (this.document) {
			button(localize('building.rebuild', "Rebuild from {0}", this.sourceName), Codicon.refresh, () => this.build());
			button(localize('building.exportIfc', "Export IFC"), Codicon.export, () => this.exportIfc());
			const views = append(actions, $('.building-views', { role: 'tablist' }));
			for (const { view, label, icon } of VIEWS) {
				const b = this.viewDisposables.add(new Button(views, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
				b.label = `$(${icon.id}) ${label}`;
				b.element.classList.toggle('active', view === this.view);
				b.element.setAttribute('role', 'tab');
				b.element.setAttribute('aria-selected', String(view === this.view));
				this.viewDisposables.add(b.onDidClick(() => {
					this.showView(view);
					this.render();
				}));
			}
		}
		this.problemBox = append(this.header, $('.library-problems'));
		this.renderProblems();
		this.setIfcNote(this.ifcNote);
		this.viewport.classList.toggle('hidden', this.view !== '3d' || !this.document);
		if (this.document && this.view === '3d') {
			this.ifcScheduler.schedule();
		}
		if (!this.document) {
			return;
		}

		append(this.additions, $('p.building-intro', undefined, localize('building.additionsIntro', "What the building model adds to the Floor Plan: openings cut into slabs and walls, stairs between stories, and braces, sloped beams or raking columns. Rebuilding from the Floor Plan keeps them; openings follow their slab or wall.")));
		// Models built before additions existed have none yet; the lists are written on the first edit.
		const additions = isObject(this.document.additions) ? this.document.additions : (this.document.additions = {});
		for (const list of Object.keys(ADDITION_LISTS)) {
			if (!Array.isArray(additions[list])) {
				additions[list] = [];
			}
		}
		this.form.render(append(this.additions, $('.library-form')), BIM_SCHEMA, this.document, GENERATED);

		const stories = (Array.isArray(this.document.stories) ? this.document.stories.filter(isObject) : [])
			.sort((a, b) => Number(a.elevation) - Number(b.elevation));
		const elements = Array.isArray(this.document.elements) ? this.document.elements.filter(isObject) : [];

		append(this.summary, $('h3', undefined, localize('building.stories', "Stories")));
		const storyTable = append(this.summary, $('.building-table'));
		for (const header of [localize('building.story', "Story"), localize('building.storyId', "ID"), localize('building.elevation', "Elevation (mm)"), localize('building.height', "Height (mm)")]) {
			append(storyTable, $('span.header', undefined, header));
		}
		stories.forEach((story, i) => {
			const above = stories[i + 1];
			append(storyTable, $('span', undefined, String(story.name ?? story.id)));
			append(storyTable, $('span', undefined, String(story.id)));
			append(storyTable, $('span.number', undefined, String(story.elevation)));
			append(storyTable, $('span.number', undefined, above ? String(Number(above.elevation) - Number(story.elevation)) : '—'));
		});
		if (!stories.length) {
			append(this.summary, $('p.building-intro', undefined, localize('building.noStories', "No stories yet.")));
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
		const match = /^additions\.(?<list>\w+)\.\d+\.(?<field>\w+)$/.exec(path);
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
		const defName = { slabOpenings: 'SlabOpening', wallOpenings: 'WallOpening', stairs: 'Stair', members: 'InclinedMember' }[name]!;
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
		const first = (values: readonly string[]) => values[0];
		if (name === 'slabOpenings') {
			item.host = first(this.elementIds('slab')) ?? item.host;
		} else if (name === 'wallOpenings') {
			item.host = first(this.elementIds('wall')) ?? item.host;
		} else if (name === 'stairs') {
			item.type = first(this.typeIds(['staircase'])) ?? item.type;
			[item.base, item.top] = [this.stories[0] ?? item.base, this.stories[1] ?? item.top];
		} else {
			item.type = first(this.typeIds(['brace', 'beam', 'column'])) ?? item.type;
		}
		return item;
	}

	protected renderProblems(): void {
		const box = this.problemBox;
		if (!box) {
			return;
		}
		clearNode(box);
		box.classList.toggle('visible', this.problems.length > 0);
		for (const problem of this.problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(row, $('span', undefined, problem.message));
		}
	}
}
