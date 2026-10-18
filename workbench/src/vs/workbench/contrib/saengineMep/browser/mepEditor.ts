/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import './media/mepEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isHTMLInputElement } from '../../../../base/browser/dom.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action, IAction, Separator, SubmenuAction } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { basename, dirname, isEqualOrParent, joinPath, relativePath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { formatField, formatNumber, IFieldSpec, parseField } from '../../saengineSoil/browser/soilDocument.js';
import {
	checkMep, DISCIPLINES, disciplineLabel, EMPTY_CONTEXT, EQUIPMENT_KINDS, EQUIPMENT_PRESETS, equipmentArea, equipmentKindLabel, equipmentPressure, findHost, formatUtilisation, guessDiscipline, hostKindLabel, hostStory, IClash, IEquipment, IEquipmentPreset,
	IIfcModel, IImportIfcRequest, IMep, IMepContext, IMepContextTexts, IMepProblem, IMepReport, IMepRequest, IOpening, IShaft, MEP_IFC_FOLDER, MEP_IMPORT_IFC_COMMAND, MEP_REPORT_COMMAND, MEP_SUGGEST_SLEEVES_COMMAND, MEP_SUMMARY_FILE, mepSummary, mepSummaryFile,
	newEquipment, newShaft, newSleeve, OPENING_KINDS, OPENING_SHAPES, openingKindLabel, openingPoint, openingShapeLabel, parseMep, plinthWeight, Point, polygonArea, readIfcImport, readMepContext, readMepReport, readSleeveSuggestions, serializeMep, shaftOnStory, sleeveForClash,
	idError, isOpenClash, isPartlyChecked, nextId, storyAt, storyElements, storyLoads, usedIds, utilisationBand,
} from './mepDocument.js';
import { MepEditorInput } from './mepEditorInput.js';
import { IPlanClash, IPlanView, MepSelection, renderPlan } from './mepPlan.js';

type View = 'plan' | 'data' | 'results';

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: 'plan', label: localize('mep.viewPlan', "Plan"), icon: Codicon.symbolStructure },
	{ view: 'data', label: localize('mep.viewData', "Data"), icon: Codicon.table },
	{ view: 'results', label: localize('mep.viewResults', "Results"), icon: Codicon.graphLine },
];

/** The state of the report: not asked yet, being computed, computed, or no backend / failed. */
type ReportState = 'idle' | 'computing' | 'ok' | 'missing' | 'error';

/** The parts the plan is drawn against, by the key of {@link IMepContextTexts}. */
const SITE_PARTS: readonly (readonly [keyof IMepContextTexts, string])[] = [
	['bim', 'bim'], ['objects', 'objects'], ['floorPlan', 'floorPlan'], ['materials', 'materials'], ['settings', 'settings'],
];

const MM = localize('mep.unit.mm', "mm");
const M = localize('mep.unit.m', "m");
const KN = localize('mep.unit.kn', "kN");
const KPA = localize('mep.unit.kpa', "kPa");

const F = {
	id: { key: 'id', label: localize('mep.f.id', "ID"), kind: 'text', required: true, width: 64 },
	name: { key: 'name', label: localize('mep.f.name', "Name"), kind: 'text', width: 170 },
	x: { key: 'x', label: 'X', unit: M, kind: 'length', required: true, title: localize('mep.f.xTitle', "Plan position of the centre"), width: 72 },
	y: { key: 'y', label: 'Y', unit: M, kind: 'length', required: true, title: localize('mep.f.yTitle', "Plan position of the centre"), width: 72 },
	rotation: { key: 'rotation', label: localize('mep.f.rotation', "Rotation"), unit: '°', kind: 'number' },
	length: { key: 'length', label: localize('mep.f.length', "Length"), unit: MM, kind: 'number', min: 1, required: true, title: localize('mep.f.lengthTitle', "Footprint along the local x axis"), width: 72 },
	width: { key: 'width', label: localize('mep.f.width', "Width"), unit: MM, kind: 'number', min: 1, required: true, title: localize('mep.f.widthTitle', "Footprint along the local y axis"), width: 72 },
	height: { key: 'height', label: localize('mep.f.height', "Height"), unit: MM, kind: 'number', min: 1, width: 72 },
	operatingWeight: { key: 'operatingWeight', label: localize('mep.f.operating', "Operating weight"), unit: KN, kind: 'number', min: 0.001, required: true, title: localize('mep.f.operatingTitle', "Weight in operation with its contents (water, oil, refrigerant), from the supplier"), width: 84 },
	emptyWeight: { key: 'emptyWeight', label: localize('mep.f.empty', "Empty weight"), unit: KN, kind: 'number', min: 0.001, title: localize('mep.f.emptyTitle', "Weight without its contents; empty for the operating weight"), width: 76 },
	plinth: { key: 'height', label: localize('mep.f.plinth', "Plinth height"), unit: MM, kind: 'number', min: 1, title: localize('mep.f.plinthTitle', "A concrete plinth under the equipment; empty for none") },
	diameter: { key: 'diameter', label: localize('mep.f.diameter', "Diameter"), unit: MM, kind: 'number', min: 1, required: true, width: 72 },
	openingWidth: { key: 'width', label: localize('mep.f.openingWidth', "Width"), unit: MM, kind: 'number', min: 1, required: true, title: localize('mep.f.openingWidthTitle', "Along a beam or wall; along x in a slab"), width: 72 },
	openingHeight: { key: 'height', label: localize('mep.f.openingHeight', "Height"), unit: MM, kind: 'number', min: 1, required: true, title: localize('mep.f.openingHeightTitle', "Vertical in a beam or wall; along y in a slab"), width: 72 },
	distance: { key: 'distance', label: localize('mep.f.distance', "From start"), unit: MM, kind: 'number', min: 0, required: true, title: localize('mep.f.distanceTitle', "From the beam's start end to the centre of the opening") },
	elevation: { key: 'elevation', label: localize('mep.f.elevation', "Above bottom"), unit: MM, kind: 'number', min: 0, required: true, title: localize('mep.f.elevationTitle', "From the beam's bottom to the centre of the opening") },
	slabX: { key: 'x', label: 'X', unit: M, kind: 'length', required: true, title: localize('mep.f.slabXTitle', "Plan position of the centre") },
	slabY: { key: 'y', label: 'Y', unit: M, kind: 'length', required: true, title: localize('mep.f.slabYTitle', "Plan position of the centre") },
	along: { key: 'x', label: localize('mep.f.along', "Along"), unit: MM, kind: 'number', min: 0, required: true, title: localize('mep.f.alongTitle', "From the wall's start to the centre of the opening") },
	up: { key: 'y', label: localize('mep.f.up', "Up"), unit: MM, kind: 'number', min: 0, required: true, title: localize('mep.f.upTitle', "From the wall's bottom to the centre of the opening") },
	service: { key: 'service', label: localize('mep.f.service', "Service"), kind: 'text', title: localize('mep.f.serviceTitle', "What passes through, e.g. DN150 drain"), width: 150 },
	path: { key: 'path', label: localize('mep.f.path', "Path"), kind: 'text', required: true, width: 300 },
} satisfies { [key: string]: IFieldSpec };

/**
 * The MEP part (`07 MEP/mep.json`) on the shared editor frame. The Plan view draws one story of
 * the building (grid, slabs with their openings, beams, columns, walls) with the equipment that
 * loads it, the shafts through it and the sleeves through its beams, slabs and walls; items are
 * picked there (and dragged) and edited in the properties panel. The Data view lists everything
 * as tables, and the Results view shows the backend's report: the equipment loads per story,
 * the checks of the openings and the clashes of the MEP IFC models with the structure. The JSON
 * text model stays the document: every edit is one undoable text edit, so save, dirty state
 * and undo come from the text file.
 */
export class MepEditor extends EditorPane {

	static readonly ID = MepEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private viewElement!: HTMLElement;
	private storyPicker!: SelectBox;
	private storyIds: string[] = [];
	private readonly viewButtons = new Map<View, HTMLButtonElement>();

	private model: ITextModel | undefined;
	private document: IMep | undefined;
	private parseError: string | undefined;
	private problems: IMepProblem[] = [];
	private context: IMepContext = EMPTY_CONTEXT;
	private applying = false;
	private view: View = 'plan';
	private story: string | undefined;
	private selection: MepSelection | undefined;
	private selectedClash: string | undefined;

	private report: IMepReport | undefined;
	private reportState: ReportState = 'idle';
	private reportError: string | undefined;
	private reportVersion = 0;
	private readonly busy = new Set<string>();
	private actionsKey: string | undefined;
	private lastSize = '';
	private planView: IPlanView | undefined;
	private drag: { kind: 'equipment' | 'shaft'; index: number; x: number; y: number; group: Element; moved: boolean } | undefined;
	private suppressClick = false;

	private readonly inputs = new Map<string, HTMLElement>();
	/** The rows of the view's tables that select an item, with the item's selection key. */
	private readonly selectableRows = new Map<HTMLElement, string>();
	private readonly propertyInputs = new Map<string, HTMLElement>();
	private propertiesFor: { document: IMep | undefined; selection: string } | undefined;
	private renderingProperties = false;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly siteDisposables = this._register(new DisposableStore());
	private readonly viewDisposables = this._register(new DisposableStore());
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private readonly siteModels = new Map<keyof IMepContextTexts, ITextModel>();
	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 300));
	private readonly reportScheduler = this._register(new RunOnceScheduler(() => void this.computeReport(), 1200));
	private readonly siteScheduler = this._register(new RunOnceScheduler(() => this.readSite(), 300));
	private readonly layoutScheduler = this._register(new RunOnceScheduler(() => this.onMainResized(), 50));

	private readonly presetActions = EQUIPMENT_PRESETS.map(preset => this._register(new Action(`saengine.mep.editor.addEquipment.${preset.kind}`, preset.name, undefined, true, async () => this.addEquipment(preset))));
	private readonly addEquipmentAction = new SubmenuAction('saengine.mep.editor.addEquipment', localize('mep.addEquipment', "Add Equipment"), this.presetActions, ThemeIcon.asClassName(Codicon.package));
	private readonly addSleeveAction = this._register(new Action('saengine.mep.editor.addSleeve', localize('mep.addSleeve', "Add Sleeve through the Selected Beam, Slab or Wall"), ThemeIcon.asClassName(Codicon.circleLargeOutline), true, async () => this.addSleeve()));
	private readonly addShaftAction = this._register(new Action('saengine.mep.editor.addShaft', localize('mep.addShaft', "Add Shaft"), ThemeIcon.asClassName(Codicon.layers), true, async () => this.addShaft()));
	private readonly importIfcAction = this._register(new Action('saengine.mep.editor.importIfc', localize('mep.importIfc', "Import MEP IFC Model"), ThemeIcon.asClassName(Codicon.cloudDownload), true, () => this.importIfc()));
	private readonly suggestAction = this._register(new Action('saengine.mep.editor.suggestSleeves', localize('mep.suggest', "Suggest Sleeves from Clashes"), ThemeIcon.asClassName(Codicon.wand), true, () => this.suggestSleeves()));
	private readonly deleteAction = this._register(new Action('saengine.mep.editor.delete', localize('mep.delete', "Delete"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteSelection()));
	private readonly recomputeAction = this._register(new Action('saengine.mep.editor.recompute', localize('mep.recompute', "Check the Openings and Clashes Again"), undefined, true, () => this.computeReport()));
	private readonly openTextAction = this._register(new Action('saengine.mep.editor.openText', localize('mep.openText', "Open as Text"), undefined, true, () => this.openAsText()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ICommandService private readonly commandService: ICommandService,
		@INotificationService private readonly notificationService: INotificationService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IContextViewService private readonly contextViewService: IContextViewService,
	) {
		super(MepEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.renderActions();
			}
		}));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			// The backend registers its commands when it starts: check as soon as it can.
			if (id === MEP_REPORT_COMMAND && this.reportState === 'missing') {
				this.reportScheduler.schedule(0);
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: MepEditor.ID,
			ariaLabel: localize('mep.toolbar', "MEP"),
			properties: { title: localize('mep.properties', "Properties"), defaultWidth: 300 },
		}));
		frame.element.classList.add('saengine-mep-editor');
		frame.setTitle(localize('mep.title', "MEP"));
		frame.setHelp(localize('mep.help', "The building services as they affect the structure: equipment that loads the floors (water tanks, chillers, generators...), sleeves and openings through beams, slabs and walls, and the vertical shafts. Pick a story, add equipment from typical presets and edit it to the supplier's data, select a beam, slab or wall to add a sleeve through it. Import the MEP IFC models to find where pipes and ducts cross the structure; the Results view lists those clashes and checks the openings."));

		const storyGroup = append(frame.titleSlot, $('.mep-story'));
		this.storyPicker = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('mep.storyAria', "Story shown") }));
		this.storyPicker.render(append(storyGroup, $('.mep-story-select')));
		this._register(this.storyPicker.onDidSelect(({ index }) => this.showStory(this.storyIds[index])));

		const views = append(frame.controlsSlot, $('.sa-segmented', { role: 'tablist', 'aria-label': localize('mep.viewsAria', "MEP view") }));
		for (const { view, label, icon } of VIEWS) {
			const button = append(views, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }));
			append(button, $(ThemeIcon.asCSSSelector(icon)));
			append(button, $('span', undefined, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.showView(view)));
			this.viewButtons.set(view, button);
		}
		this.viewElement = append(frame.main, $('.mep-view', { tabIndex: 0 }));
		this._register(addDisposableListener(this.viewElement, EventType.KEY_DOWN, e => this.onKey(e)));
		this._register(frame.onDidLayoutMain(() => this.layoutScheduler.schedule()));
		this.updateViewButtons();
	}

	override async setInput(input: MepEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.siteDisposables.clear();
		this.siteModels.clear();
		this.model = undefined;
		this.report = undefined;
		this.reportState = 'idle';
		this.selection = undefined;
		this.selectedClash = undefined;
		this.story = undefined;
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
		this.inputDisposables.add(input.onDidChangeDirty(() => {
			// The part list's summary describes the saved file: write it once the edits are saved.
			if (!input.isDirty()) {
				this.reportScheduler.schedule(0);
			}
			this.renderStatus();
		}));
		await this.openSite(input);
		if (this.input !== input) {
			return;
		}
		this.load();
	}

	override clearInput(): void {
		this.flush();
		this.inputDisposables.clear();
		this.siteDisposables.clear();
		this.siteModels.clear();
		this.reportScheduler.cancel();
		this.model = undefined;
		this.document = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.viewElement?.focus();
	}

	override dispose(): void {
		this.flush();
		super.dispose();
	}

	/** The MEP file. */
	get resource(): URI | undefined {
		return (this.input as MepEditorInput | undefined)?.resource;
	}

	private get projectRoot(): URI | undefined {
		const resource = this.resource;
		return resource ? dirname(dirname(resource)) : undefined;
	}

	private get developerMode(): boolean {
		return this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
	}

	private setBusy(holder: string, busy: boolean): void {
		const was = this.busy.size > 0;
		if (busy) {
			this.busy.add(holder);
		} else {
			this.busy.delete(holder);
		}
		if (this.busy.size > 0 && !was) {
			this.frame.showProgress();
		} else if (!this.busy.size && was) {
			this.frame.hideProgress();
		}
	}

	// ───────────────────────────── the building around it ─────────────────────────────

	/** Opens the parts the plan is drawn against and follows their edits. */
	private async openSite(input: MepEditorInput): Promise<void> {
		const root = dirname(dirname(input.resource));
		await Promise.all(SITE_PARTS.map(async ([key, partId]) => {
			const part = partById(partId);
			if (!part?.mainFile) {
				return;
			}
			try {
				const reference = await this.textModelService.createModelReference(joinPath(root, part.folder, part.mainFile));
				if (this.input !== input) {
					reference.dispose();
					return;
				}
				this.siteDisposables.add(reference);
				const model = reference.object.textEditorModel;
				this.siteModels.set(key, model);
				this.siteDisposables.add(model.onDidChangeContent(() => this.siteScheduler.schedule()));
			} catch {
				// A missing part: the plan goes without it.
			}
		}));
		this.readSite(false);
	}

	/** The texts of the parts around the MEP file, as the editor holds them. */
	private siteTexts(): IMepContextTexts {
		const texts: { -readonly [K in keyof IMepContextTexts]?: string } = {};
		for (const [key, model] of this.siteModels) {
			if (!model.isDisposed()) {
				texts[key] = model.getValue();
			}
		}
		return texts;
	}

	private readSite(render = true): void {
		this.context = readMepContext(this.siteTexts());
		if (render && this.document) {
			this.ensureStory();
			this.problems = checkMep(this.document, this.context);
			this.render();
			this.reportScheduler.schedule();
		}
	}

	// ───────────────────────────── document ─────────────────────────────

	private load(): void {
		if (!this.model) {
			return;
		}
		const parsed = parseMep(this.model.getValue());
		if (parsed.kind === 'error') {
			this.document = undefined;
			this.parseError = parsed.message;
		} else {
			this.document = parsed.document;
			this.parseError = undefined;
			if (!this.selectionExists(this.document)) {
				this.selection = undefined;
			}
		}
		this.ensureStory();
		this.problems = this.document ? checkMep(this.document, this.context) : [];
		this.render();
		this.reportScheduler.schedule(this.reportState === 'idle' ? 0 : undefined);
	}

	private selectionExists(document: IMep): boolean {
		const selection = this.selection;
		switch (selection?.kind) {
			case 'equipment': return selection.index < document.equipment.length;
			case 'opening': return selection.index < document.openings.length;
			case 'shaft': return selection.index < document.shafts.length;
			default: return true;
		}
	}

	/** Keeps the story shown one of the building's: the first with equipment, else the first floor above the base. */
	private ensureStory(): void {
		const stories = this.context.stories;
		if (this.story && stories.some(s => s.id === this.story)) {
			this.updateStoryPicker();
			return;
		}
		const withEquipment = stories.find(s => this.document?.equipment.some(e => e.story === s.id));
		const withFloor = stories.find(s => storyElements(this.context, s.id).slabs.length);
		this.story = (withEquipment ?? withFloor ?? stories[0])?.id;
		this.updateStoryPicker();
	}

	private updateStoryPicker(): void {
		if (!this.storyPicker) {
			return;
		}
		this.storyIds = this.context.stories.map(s => s.id);
		const options: ISelectOptionItem[] = this.context.stories.map(s => ({
			text: localize('mep.storyOption', "{0} ({1} m)", s.name, `${s.elevation >= 0 ? '+' : ''}${formatNumber(s.elevation / 1000, 2)}`),
		}));
		this.storyPicker.setOptions(options.length ? options : [{ text: localize('mep.noStories', "No stories") }], Math.max(0, this.storyIds.indexOf(this.story ?? '')));
		this.storyPicker.setEnabled(options.length > 0);
	}

	private showStory(story: string | undefined): void {
		if (!story || story === this.story) {
			return;
		}
		this.flush();
		this.story = story;
		if (this.selection?.kind !== 'opening') {
			this.selection = undefined;
		}
		this.render();
	}

	/** Writes the document to the text model as one undoable edit. */
	private commit(): void {
		this.commitScheduler.cancel();
		const model = this.model;
		if (!model || !this.document || model.isDisposed()) {
			return;
		}
		const text = serializeMep(this.document);
		if (text === model.getValue()) {
			return;
		}
		this.applying = true;
		try {
			model.pushStackElement();
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null);
			model.pushStackElement();
		} finally {
			this.applying = false;
		}
		this.reportScheduler.schedule();
	}

	private flush(): void {
		if (this.commitScheduler.isScheduled()) {
			this.commit();
		}
	}

	/** After an edit in place: structural edits save and re-render at once, typing is batched. */
	private changed(structural: boolean): void {
		if (!this.document) {
			return;
		}
		this.problems = checkMep(this.document, this.context);
		if (structural) {
			this.commit();
			this.render();
		} else {
			this.commitScheduler.schedule();
			if (this.view === 'plan') {
				this.renderView();
			} else {
				this.renderProblems();
			}
			this.renderStatus();
		}
	}

	// ───────────────────────────── selection ─────────────────────────────

	private get selectionKey(): string {
		const selection = this.selection;
		return !selection ? '' : selection.kind === 'element' ? `element:${selection.id}` : `${selection.kind}:${selection.index}`;
	}

	private select(selection: MepSelection | undefined): void {
		this.flush();
		this.selection = selection;
		this.selectedClash = undefined;
		this.renderSelection();
	}

	private renderSelection(): void {
		this.renderActions();
		if (this.view !== 'data') {
			this.renderView();
		} else {
			this.markSelectedRows();
		}
		this.renderProperties();
	}

	private onPlanClick(e: MouseEvent): void {
		if (this.suppressClick) {
			this.suppressClick = false;
			return;
		}
		const target = e.target as Element | null;
		const pick = (attribute: string) => target?.closest(`[${attribute}]`)?.getAttribute(attribute);
		const equipment = pick('data-equipment');
		const opening = pick('data-opening');
		const shaft = pick('data-shaft');
		const element = pick('data-element');
		const clash = pick('data-clash');
		if (clash) {
			this.flush();
			this.selectedClash = clash;
			this.renderView();
		} else if (opening) {
			this.select({ kind: 'opening', index: Number(opening) });
		} else if (equipment) {
			this.select({ kind: 'equipment', index: Number(equipment) });
		} else if (element) {
			this.select({ kind: 'element', id: element });
		} else if (shaft) {
			this.select({ kind: 'shaft', index: Number(shaft) });
		} else {
			this.select(undefined);
		}
	}

	/** Equipment and shafts are moved by dragging them in the plan; the move is one edit, in 50 mm steps. */
	private onPlanPointerDown(canvas: HTMLElement, e: PointerEvent): void {
		// A click follows only the gesture that ends a drag (and not always): a new press clears it.
		this.suppressClick = false;
		const target = e.target as Element | null;
		const equipment = target?.closest('[data-equipment]');
		const shaft = equipment ? undefined : target?.closest('[data-shaft]');
		const group = equipment ?? shaft;
		if (!group || e.button !== 0) {
			return;
		}
		this.drag = {
			kind: equipment ? 'equipment' : 'shaft',
			index: Number(group.getAttribute(equipment ? 'data-equipment' : 'data-shaft')),
			x: e.clientX, y: e.clientY, group, moved: false,
		};
		canvas.setPointerCapture(e.pointerId);
	}

	private onPlanPointerMove(e: PointerEvent): void {
		const drag = this.drag;
		if (!drag) {
			return;
		}
		const dx = e.clientX - drag.x;
		const dy = e.clientY - drag.y;
		if (!drag.moved && Math.hypot(dx, dy) < 4) {
			return;
		}
		drag.moved = true;
		drag.group.setAttribute('transform', `translate(${dx.toFixed(1)} ${dy.toFixed(1)})`);
	}

	private onPlanPointerUp(canvas: HTMLElement, e: PointerEvent): void {
		const drag = this.drag;
		this.drag = undefined;
		if (canvas.hasPointerCapture(e.pointerId)) {
			canvas.releasePointerCapture(e.pointerId);
		}
		if (drag && !drag.moved) {
			// A press without a move selects: the pointer capture retargets the click to the canvas.
			this.suppressClick = true;
			this.select({ kind: drag.kind, index: drag.index });
			return;
		}
		const document = this.document;
		const scale = this.planView?.scale;
		if (!drag?.moved || !document || !scale) {
			return;
		}
		this.suppressClick = true;
		const dx = Math.round((e.clientX - drag.x) / scale / 50) * 50;
		const dy = -Math.round((e.clientY - drag.y) / scale / 50) * 50;
		if (drag.kind === 'equipment') {
			const equipment = document.equipment[drag.index];
			if (equipment) {
				equipment.x = equipment.x + dx;
				equipment.y = equipment.y + dy;
			}
		} else {
			const shaft = document.shafts[drag.index];
			if (shaft) {
				shaft.outline = shaft.outline.map(p => [p[0] + dx, p[1] + dy] as Point);
			}
		}
		this.selection = { kind: drag.kind, index: drag.index };
		this.changed(true);
	}

	private onKey(e: KeyboardEvent): void {
		const target = e.target as HTMLElement;
		if (isHTMLInputElement(target) || target.tagName === 'SELECT') {
			return;
		}
		if (e.key === 'Delete' && this.deleteAction.enabled) {
			e.preventDefault();
			this.deleteSelection();
		} else if (e.key === 'Escape') {
			this.select(undefined);
		}
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Shows `selection` after a structural edit: in the plan of its story. */
	private added(selection: MepSelection, story?: string): void {
		this.selection = selection;
		this.selectedClash = undefined;
		if (story) {
			this.story = story;
			this.updateStoryPicker();
		}
		this.view = this.view === 'results' ? 'plan' : this.view;
		this.frame.setPropertiesVisible(true);
		this.changed(true);
	}

	addEquipment(preset: IEquipmentPreset): void {
		const document = this.document;
		const story = this.story;
		if (!document) {
			return;
		}
		if (!story) {
			this.notificationService.info(localize('mep.noStory', "The building model has no stories yet. Build it (6 BIM) first: equipment stands on a story's floor."));
			return;
		}
		document.equipment.push(newEquipment(document, this.context, preset, story));
		this.added({ kind: 'equipment', index: document.equipment.length - 1 });
	}

	/** A sleeve through the beam, slab or wall selected in the plan. */
	addSleeve(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const hostId = this.selection?.kind === 'element' ? this.selection.id
			: this.selection?.kind === 'opening' ? document.openings[this.selection.index]?.host : undefined;
		const host = hostId ? findHost(this.context, hostId) : undefined;
		if (!host) {
			this.notificationService.info(localize('mep.sleeveNeeds', "Select a beam, slab or wall in the plan first: the sleeve goes through it."));
			return;
		}
		const sleeve = newSleeve(document, this.context, host.element.id);
		if (!sleeve) {
			return;
		}
		document.openings.push(sleeve);
		this.added({ kind: 'opening', index: document.openings.length - 1 }, hostStory(this.context, host)?.id);
	}

	private addShaft(): void {
		const document = this.document;
		if (!document || !this.story) {
			return;
		}
		document.shafts.push(newShaft(document, this.context, this.story));
		this.added({ kind: 'shaft', index: document.shafts.length - 1 });
	}

	private deleteSelection(): void {
		const document = this.document;
		const selection = this.selection;
		if (!document || !selection) {
			return;
		}
		switch (selection.kind) {
			case 'equipment': document.equipment.splice(selection.index, 1); break;
			case 'opening': document.openings.splice(selection.index, 1); break;
			case 'shaft': document.shafts.splice(selection.index, 1); break;
			default: return;
		}
		this.selection = undefined;
		this.changed(true);
	}

	private request(): IMepRequest | undefined {
		const root = this.projectRoot;
		const model = this.model;
		if (!root || !model) {
			return undefined;
		}
		return { projectRoot: root.fsPath, mepText: model.getValue() };
	}

	/**
	 * Adds an MEP IFC model: a file picked outside the project is copied into `07 MEP/IFC` first,
	 * so the project stays self-contained; the backend reads it when it is available.
	 */
	async importIfc(): Promise<void> {
		this.flush();
		const resource = this.resource;
		const root = this.projectRoot;
		const document = this.document;
		if (!resource || !root || !document) {
			return;
		}
		const picked = await this.fileDialogService.showOpenDialog({
			title: localize('mep.importTitle', "Import MEP IFC Model"),
			canSelectFiles: true, canSelectFolders: false, canSelectMany: false,
			defaultUri: dirname(resource),
			filters: [{ name: localize('mep.ifcFilter', "IFC models"), extensions: ['ifc'] }],
		});
		const source = picked?.[0];
		if (!source) {
			return;
		}
		let target = source;
		try {
			if (!isEqualOrParent(source, root)) {
				target = joinPath(dirname(resource), MEP_IFC_FOLDER, basename(source));
				if (!(await this.fileService.exists(target))) {
					await this.fileService.copy(source, target);
				}
			}
		} catch (error) {
			this.notificationService.error(localize('mep.copyFailed', "The model could not be copied into the project: {0}", error instanceof Error ? error.message : String(error)));
			return;
		}
		const path = relativePath(root, target) ?? basename(target);
		if (document.ifcModels.some(m => m.path === path)) {
			this.notificationService.info(localize('mep.importedAlready', "{0} is already among the MEP models.", path));
			return;
		}
		const model: IIfcModel = { path, discipline: guessDiscipline(path), visible: true };
		if (CommandsRegistry.getCommand(MEP_IMPORT_IFC_COMMAND)) {
			this.setBusy('import', true);
			try {
				const request: IImportIfcRequest = { projectRoot: root.fsPath, path };
				const answer = readIfcImport(await this.commandService.executeCommand<unknown>(MEP_IMPORT_IFC_COMMAND, request));
				if (answer?.discipline) {
					model.discipline = answer.discipline;
				}
				if (answer?.notes.length) {
					this.notificationService.info(answer.notes.join(' '));
				}
			} catch (error) {
				this.notificationService.error(localize('mep.importFailed', "The model could not be read: {0}", error instanceof Error ? error.message : String(error)));
				return;
			} finally {
				this.setBusy('import', false);
			}
		} else {
			this.notificationService.info(localize('mep.importNoBackend', "{0} is listed among the MEP models. Its clashes with the structure are found once the SAEngine backend is available.", path));
		}
		if (this.document !== document) {
			return;
		}
		document.ifcModels.push(model);
		this.view = 'data';
		this.changed(true);
	}

	/** Adds the sleeves the backend proposes where the MEP models cross the structure. */
	async suggestSleeves(): Promise<void> {
		this.flush();
		const request = this.request();
		const document = this.document;
		if (!request || !document) {
			return;
		}
		if (!document.ifcModels.length) {
			this.notificationService.info(localize('mep.suggestNoModels', "Import an MEP IFC model first: the sleeves come from where its pipes and ducts cross the beams, slabs and walls."));
			return;
		}
		if (!CommandsRegistry.getCommand(MEP_SUGGEST_SLEEVES_COMMAND)) {
			this.notificationService.info(localize('mep.suggestNoBackend', "Suggesting sleeves needs the SAEngine backend, which is not available in this window."));
			return;
		}
		this.setBusy('suggest', true);
		let answer: { openings: IOpening[]; notes: string[] } | undefined;
		try {
			answer = readSleeveSuggestions(await this.commandService.executeCommand<unknown>(MEP_SUGGEST_SLEEVES_COMMAND, request));
		} catch (error) {
			this.notificationService.error(localize('mep.suggestFailed', "The sleeves could not be suggested: {0}", error instanceof Error ? error.message : String(error)));
			return;
		} finally {
			this.setBusy('suggest', false);
		}
		if (this.document !== document) {
			return;
		}
		const added: IOpening[] = [];
		for (const proposal of answer?.openings ?? []) {
			const point = openingPoint(proposal, this.context);
			const same = document.openings.some(o => {
				const other = openingPoint(o, this.context);
				return o.host === proposal.host && !!point && !!other && Math.hypot(point[0] - other[0], point[1] - other[1]) < 50;
			});
			if (same) {
				continue;
			}
			const used = usedIds(document);
			if (!proposal.id || used.includes(proposal.id)) {
				proposal.id = nextId('OP', used);
			}
			document.openings.push(proposal);
			added.push(proposal);
		}
		if (!added.length) {
			this.notificationService.info(answer?.notes.length ? answer.notes.join(' ') : localize('mep.suggestNone', "No crossing of the MEP models with the structure needs a new sleeve."));
			return;
		}
		const first = added[0];
		this.added({ kind: 'opening', index: document.openings.indexOf(first) }, hostStory(this.context, findHost(this.context, first.host))?.id);
		this.notificationService.info(added.length === 1 ? localize('mep.suggestedOne', "Added 1 sleeve where an MEP model crosses the structure.") : localize('mep.suggested', "Added {0} sleeves where the MEP models cross the structure.", added.length));
	}

	/** A sleeve for one clash of the report. */
	private addSleeveForClash(clash: IClash): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const sleeve = sleeveForClash(document, clash);
		if (!sleeve) {
			this.notificationService.info(localize('mep.clashNoSleeve', "No sleeve is proposed where {0} meets {1}: reroute the service.", clash.mepName ?? clash.mep, clash.structural));
			return;
		}
		document.openings.push(sleeve);
		this.view = 'plan';
		this.added({ kind: 'opening', index: document.openings.length - 1 }, hostStory(this.context, findHost(this.context, sleeve.host))?.id);
	}

	/** The story a clash is on: the report's, else its structural element's. */
	private clashStory(clash: IClash): string | undefined {
		if (clash.story) {
			return clash.story;
		}
		const host = findHost(this.context, clash.structural);
		if (host) {
			return hostStory(this.context, host)?.id;
		}
		const z = clash.point?.[2];
		return typeof z === 'number' ? storyAt(this.context, z)?.id : undefined;
	}

	private showClash(clash: IClash): void {
		this.flush();
		const story = this.clashStory(clash);
		if (story) {
			this.story = story;
			this.updateStoryPicker();
		}
		this.selection = undefined;
		this.selectedClash = clash.id;
		this.view = 'plan';
		this.render();
	}

	private async openAsText(): Promise<void> {
		const resource = this.resource;
		if (resource) {
			this.flush();
			await this.editorService.openEditor({ resource, options: { override: DEFAULT_EDITOR_ASSOCIATION.id, pinned: true } }, this.group);
		}
	}

	private showView(view: View): void {
		this.flush();
		this.view = view;
		this.render();
	}

	private hasContent(document: IMep): boolean {
		return document.equipment.length + document.openings.length + document.shafts.length + document.ifcModels.length > 0;
	}

	/** Asks the backend for the report (debounced after every edit). */
	async computeReport(): Promise<void> {
		const document = this.document;
		const version = ++this.reportVersion;
		const request = this.request();
		if (!document || !request || !this.hasContent(document)) {
			this.setBusy('report', false);
			this.report = undefined;
			this.reportState = 'idle';
			this.renderReportDependent();
			return;
		}
		if (!CommandsRegistry.getCommand(MEP_REPORT_COMMAND)) {
			this.setBusy('report', false);
			this.report = undefined;
			this.reportState = 'missing';
			this.renderReportDependent();
			return;
		}
		this.flush();
		// The building as the report is asked for, stamped in the part list's summary.
		const sourceTexts = this.siteTexts();
		this.reportState = this.report ? 'ok' : 'computing';
		this.setBusy('report', true);
		let report: IMepReport | undefined;
		let error: string | undefined;
		try {
			report = readMepReport(await this.commandService.executeCommand<unknown>(MEP_REPORT_COMMAND, request));
			if (!report) {
				error = localize('mep.reportEmpty', "The backend gave no report.");
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		if (version !== this.reportVersion) {
			return;
		}
		this.setBusy('report', false);
		this.report = report;
		this.reportState = report ? 'ok' : 'error';
		this.reportError = error;
		this.renderReportDependent();
		// The summary describes the saved file: written only when the editor holds no unsaved edits.
		const model = this.model;
		if (report && model && this.resource && !this.input?.isDirty()) {
			const content = JSON.stringify(mepSummaryFile(document, report, model.getValue(), new Date(), sourceTexts), undefined, '\t') + '\n';
			this.fileService.writeFile(joinPath(dirname(this.resource), MEP_SUMMARY_FILE), VSBuffer.fromString(content)).catch(() => { /* the part list then shows the count only */ });
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		if (!this.frame) {
			return;
		}
		this.updateViewButtons();
		this.renderActions();
		this.renderEmpty();
		this.renderView();
		this.renderProperties();
		this.renderStatus();
	}

	private renderReportDependent(): void {
		if (this.view !== 'data') {
			this.renderView();
		}
		this.renderProperties();
		this.renderStatus();
	}

	private onMainResized(): void {
		const size = `${this.viewElement.clientWidth}x${this.viewElement.clientHeight}`;
		if (size !== this.lastSize && this.view === 'plan') {
			this.renderView();
		}
	}

	private updateViewButtons(): void {
		const usable = !!this.document;
		for (const [view, button] of this.viewButtons) {
			const active = view === this.view;
			button.classList.toggle('active', active);
			button.setAttribute('aria-selected', String(active));
			button.disabled = !usable;
		}
	}

	private renderActions(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const document = this.document;
		const usable = !!document;
		const selection = this.selection;
		const host = selection?.kind === 'element' ? findHost(this.context, selection.id) : undefined;
		this.addSleeveAction.label = host ? localize('mep.addSleeveThrough', "Add Sleeve through {0} {1}", hostKindLabel(host.kind), host.element.id) : localize('mep.addSleeve', "Add Sleeve through the Selected Beam, Slab or Wall");
		this.addSleeveAction.enabled = !!host || selection?.kind === 'opening';
		const named = selection?.kind === 'equipment' ? document?.equipment[selection.index]?.id
			: selection?.kind === 'opening' ? document?.openings[selection.index]?.id
				: selection?.kind === 'shaft' ? document?.shafts[selection.index]?.id : undefined;
		this.deleteAction.enabled = !!named;
		this.deleteAction.label = named ? localize('mep.deleteNamed', "Delete {0}", named) : localize('mep.delete', "Delete");
		this.recomputeAction.enabled = !!document && this.hasContent(document);
		const primary: IAction[] = usable ? [
			this.addEquipmentAction, this.addSleeveAction, this.addShaftAction, this.importIfcAction, this.suggestAction, this.deleteAction, frame.togglePropertiesAction,
		] : [frame.togglePropertiesAction];
		const secondary: IAction[] = usable ? [this.recomputeAction] : [];
		if (this.developerMode || this.parseError) {
			if (secondary.length) {
				secondary.push(new Separator());
			}
			secondary.push(this.openTextAction);
		}
		const key = `${primary.map(a => a.id).join()}|${secondary.map(a => a.id).join()}`;
		if (key !== this.actionsKey) {
			this.actionsKey = key;
			frame.setActions(primary, secondary);
		}
	}

	private renderEmpty(): void {
		if (this.parseError) {
			this.frame.setEmpty({
				icon: Codicon.warning,
				title: localize('mep.cannotShow', "The MEP file cannot be shown"),
				text: this.parseError,
				actions: [{ label: localize('mep.openText', "Open as Text"), primary: true, run: () => void this.openAsText() }],
			});
		} else if (this.document && !this.context.stories.length && !this.hasContent(this.document)) {
			this.frame.setEmpty({
				icon: Codicon.tools,
				title: localize('mep.emptyNoBuilding', "No building to serve yet"),
				text: localize('mep.emptyNoBuildingText', "Equipment stands on the floors of the building model and sleeves go through its beams, slabs and walls. Build the building model (6 BIM) first; its stories then appear here."),
			});
		} else {
			this.frame.setEmpty(undefined);
		}
	}

	private renderView(): void {
		this.viewDisposables.clear();
		this.inputs.clear();
		this.selectableRows.clear();
		const scroll = this.viewElement.scrollTop;
		clearNode(this.viewElement);
		this.viewElement.className = `mep-view ${this.view}`;
		this.lastSize = `${this.viewElement.clientWidth}x${this.viewElement.clientHeight}`;
		const document = this.document;
		if (!document) {
			return;
		}
		switch (this.view) {
			case 'plan': this.renderPlanView(document); break;
			case 'data': this.renderDataView(document); break;
			case 'results': this.renderResultsView(document); break;
		}
		this.viewElement.scrollTop = scroll;
		this.renderProblems();
	}

	// ───────────────────────────── plan view ─────────────────────────────

	private planClashes(): IPlanClash[] {
		if (this.reportState !== 'ok' || !this.report || !this.story) {
			return [];
		}
		const clashes: IPlanClash[] = [];
		for (const clash of this.report.clashes) {
			if (clash.point && this.clashStory(clash) === this.story) {
				clashes.push({ id: clash.id, point: [clash.point[0], clash.point[1]], open: clash.status === 'clash' });
			}
		}
		return clashes;
	}

	private renderPlanView(document: IMep): void {
		const view = this.viewElement;
		const story = this.context.stories.find(s => s.id === this.story);
		const header = append(view, $('.mep-view-header'));
		append(header, $('span.mep-view-title', undefined, story ? story.name : localize('mep.planNoStory', "No story")));
		const onStory = document.equipment.filter(e => e.story === this.story);
		const load = onStory.reduce((sum, e) => sum + (e.operatingWeight || 0), 0);
		append(header, $('span.mep-view-subtitle', undefined, story
			? localize('mep.planSubtitle', "level {0} m · {1} equipment, {2} kN · click to select, drag equipment and shafts to move them",
				formatNumber(story.elevation / 1000, 2), onStory.length, formatNumber(load, 1))
			: localize('mep.planSubtitleNone', "Build the building model to lay out the services on its stories.")));

		const legend = append(view, $('.mep-legend'));
		const item = (cls: string, label: string) => {
			const element = append(legend, $('span.mep-legend-item'));
			append(element, $(`span.mep-swatch.${cls}`));
			append(element, $('span', undefined, label));
		};
		item('equipment', localize('mep.legendEquipment', "Equipment"));
		item('shaft', localize('mep.legendShaft', "Shaft"));
		item('sleeve', localize('mep.legendSleeve', "Sleeve or opening"));
		item('beam', localize('mep.legendBeam', "Beam"));
		item('slab', localize('mep.legendSlab', "Slab"));
		const clashes = this.planClashes();
		if (clashes.length) {
			item('clash', localize('mep.legendClash', "Clash"));
		}

		const canvas = append(view, $('.mep-canvas'));
		if (!story) {
			return;
		}
		const width = Math.max(240, view.clientWidth - 32);
		const height = Math.max(240, view.clientHeight - 96);
		const bands = this.reportState === 'ok' && this.report ? new Map(this.report.openings.map(o => [o.id, o.ok ? utilisationBand(o.utilisation) : 'fail' as const])) : undefined;
		this.planView = renderPlan(canvas, document, this.context, {
			width, height, story: story.id, selection: this.selection, openingBands: bands, clashes, selectedClash: this.selectedClash,
		});
		this.viewDisposables.add(addDisposableListener(canvas, EventType.CLICK, e => this.onPlanClick(e)));
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_DOWN, e => this.onPlanPointerDown(canvas, e)));
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_MOVE, e => this.onPlanPointerMove(e)));
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_UP, e => this.onPlanPointerUp(canvas, e)));
	}

	// ───────────────────────────── data view ─────────────────────────────

	private renderDataView(document: IMep): void {
		const header = append(this.viewElement, $('.mep-view-header'));
		append(header, $('span.mep-view-title', undefined, localize('mep.dataTitle', "Equipment, openings, shafts and models")));
		append(header, $('span.mep-view-subtitle', undefined, localize('mep.dataSubtitle', "Sizes in mm, positions in m, weights in kN; click a row to edit the rest in Properties.")));
		this.renderEquipmentTable(document);
		this.renderOpeningTable(document);
		this.renderShaftTable(document);
		this.renderModelTable(document);
		this.markSelectedRows();
	}

	private section(title: string, count: number, add?: { label: string; run: () => void }): HTMLElement {
		const section = append(this.viewElement, $('.mep-section'));
		const heading = append(section, $('.mep-section-heading'));
		append(heading, $('span.mep-section-title', undefined, title));
		append(heading, $('span.mep-section-count', undefined, String(count)));
		if (add) {
			const button = append(heading, $<HTMLButtonElement>('button.mep-add', { type: 'button' }));
			append(button, $(ThemeIcon.asCSSSelector(Codicon.add)));
			append(button, $('span', undefined, add.label));
			this.viewDisposables.add(addDisposableListener(button, EventType.CLICK, () => add.run()));
		}
		return section;
	}

	private tableHead(table: HTMLElement, columns: readonly { label: string; unit?: string; numeric?: boolean; width?: number }[]): void {
		const colgroup = append(table, $('colgroup'));
		const head = append(append(table, $('thead')), $('tr'));
		for (const column of columns) {
			append(colgroup, $('col', { style: `width: ${column.width ?? 72}px` }));
			const th = append(head, $(column.numeric ? 'th.number' : 'th'));
			append(th, $('span', undefined, column.label));
			if (column.unit) {
				append(th, $('span.mep-unit', undefined, column.unit));
			}
		}
	}

	private removeButton(row: HTMLElement, run: () => void): void {
		const label = localize('mep.removeRow', "Remove");
		const button = append(append(row, $('td.mep-row-actions')), $<HTMLButtonElement>('button.mep-remove', { type: 'button', title: label, 'aria-label': label }));
		append(button, $(ThemeIcon.asCSSSelector(Codicon.trash)));
		this.viewDisposables.add(addDisposableListener(button, EventType.CLICK, e => {
			e.stopPropagation();
			run();
		}));
	}

	private selectableRow(body: HTMLElement, selection: MepSelection): HTMLElement {
		const row = append(body, $('tr.mep-row'));
		this.selectableRows.set(row, selection.kind === 'element' ? `element:${selection.id}` : `${selection.kind}:${selection.index}`);
		this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, e => {
			if (!(e.target as HTMLElement).closest('input, select, button')) {
				this.select(selection);
			}
		}));
		return row;
	}

	private markSelectedRows(): void {
		const key = this.selectionKey;
		for (const [row, rowKey] of this.selectableRows) {
			row.classList.toggle('selected', !!key && rowKey === key);
		}
	}

	private storyOptions(): { value: string; label: string }[] {
		return this.context.stories.map(s => ({ value: s.id, label: s.name }));
	}

	private renderEquipmentTable(document: IMep): void {
		const section = this.section(localize('mep.equipmentHeading', "Equipment"), document.equipment.length, { label: localize('mep.addTank', "Add Water Tank"), run: () => this.addEquipment(EQUIPMENT_PRESETS[0]) });
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: F.name.label, width: 170 }, { label: localize('mep.f.kind', "Kind"), width: 130 }, { label: localize('mep.f.story', "Story"), width: 100 },
			{ label: F.x.label, unit: M, numeric: true }, { label: F.y.label, unit: M, numeric: true }, { label: F.length.label, unit: MM, numeric: true }, { label: F.width.label, unit: MM, numeric: true },
			{ label: F.operatingWeight.label, unit: KN, numeric: true, width: 84 }, { label: F.emptyWeight.label, unit: KN, numeric: true, width: 76 },
			{ label: localize('mep.f.pressure', "Load"), unit: KPA, numeric: true, width: 64 }, { label: localize('mep.f.vibrating', "Vibrating"), width: 64 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		document.equipment.forEach((e, index) => {
			const row = this.selectableRow(body, { kind: 'equipment', index });
			const path = (field: string) => `equipment.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, e.id, value => this.setField(e, 'id', value), path('id')));
			append(append(row, $('td')), this.textInput(F.name, e.name, value => this.setField(e, 'name', value), path('name')));
			append(append(row, $('td')), this.selectInput(EQUIPMENT_KINDS.map(k => ({ value: k, label: equipmentKindLabel(k) })), e.kind, value => {
				e.kind = value;
				this.changed(true);
			}, path('kind'), localize('mep.f.kind', "Kind")));
			append(append(row, $('td')), this.selectInput(this.storyOptions(), e.story, value => this.setStory(e, value), path('story'), localize('mep.f.story', "Story")));
			for (const field of [F.x, F.y, F.length, F.width, F.operatingWeight, F.emptyWeight]) {
				append(append(row, $('td')), this.textInput(field, e[field.key], value => this.setField(e, field.key, value), path(field.key)));
			}
			const pressure = equipmentPressure(e);
			append(row, $('td.number', undefined, pressure === undefined ? '' : formatNumber(pressure, 1)));
			append(append(row, $('td.mep-check-cell')), this.checkbox(!!e.vibrating, value => {
				if (value) {
					e.vibrating = true;
				} else {
					delete e.vibrating;
				}
				this.changed(true);
			}, localize('mep.f.vibrating', "Vibrating")));
			this.removeButton(row, () => {
				document.equipment.splice(index, 1);
				this.selection = undefined;
				this.changed(true);
			});
		});
		if (!document.equipment.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('mep.noEquipment', "None yet. Add equipment from the toolbar: start from a preset and edit it to the supplier's data.")));
		}
	}

	private renderOpeningTable(document: IMep): void {
		const section = this.section(localize('mep.openingsHeading', "Sleeves and openings"), document.openings.length);
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('mep.f.host', "Host"), width: 120 }, { label: localize('mep.f.openingKind', "Kind"), width: 96 }, { label: localize('mep.f.shape', "Shape"), width: 100 },
			{ label: F.diameter.label, unit: MM, numeric: true }, { label: F.openingWidth.label, unit: MM, numeric: true }, { label: F.openingHeight.label, unit: MM, numeric: true },
			{ label: localize('mep.f.position', "Position"), width: 170 }, { label: F.service.label, width: 150 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		const hosts = this.hostOptions();
		document.openings.forEach((o, index) => {
			const row = this.selectableRow(body, { kind: 'opening', index });
			const path = (field: string) => `openings.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, o.id, value => this.setField(o, 'id', value), path('id')));
			append(append(row, $('td')), this.selectInput(hosts, o.host, value => this.setHost(o, value), path('host'), localize('mep.f.host', "Host")));
			append(append(row, $('td')), this.selectInput(OPENING_KINDS.map(k => ({ value: k, label: openingKindLabel(k) })), o.kind, value => {
				o.kind = value;
				this.changed(true);
			}, path('kind'), localize('mep.f.openingKind', "Kind")));
			append(append(row, $('td')), this.selectInput(OPENING_SHAPES.map(s => ({ value: s, label: openingShapeLabel(s) })), o.shape, value => this.setShape(o, value), path('shape'), localize('mep.f.shape', "Shape")));
			const circle = o.shape === 'circle';
			for (const [field, usable] of [[F.diameter, circle], [F.openingWidth, !circle], [F.openingHeight, !circle]] as const) {
				const td = append(row, $('td'));
				if (usable) {
					append(td, this.textInput(field, o[field.key], value => this.setField(o, field.key, value), path(field.key)));
				} else {
					td.classList.add('mep-muted');
					td.textContent = '—';
				}
			}
			append(row, $('td.mep-muted-cell', undefined, this.positionText(o)));
			append(append(row, $('td')), this.textInput(F.service, o.service, value => this.setField(o, 'service', value), path('service')));
			this.removeButton(row, () => {
				document.openings.splice(index, 1);
				this.selection = undefined;
				this.changed(true);
			});
		});
		if (!document.openings.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('mep.noOpenings', "None yet. Select a beam, slab or wall in the plan and add a sleeve through it, or let SAEngine suggest them from the clashes of the MEP models.")));
		}
	}

	private renderShaftTable(document: IMep): void {
		const section = this.section(localize('mep.shaftsHeading', "Shafts"), document.shafts.length, { label: localize('mep.addShaftShort', "Add Shaft"), run: () => this.addShaft() });
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('mep.f.fromLong', "Starts at"), width: 110 }, { label: localize('mep.f.toLong', "Up to"), width: 110 },
			{ label: F.service.label, width: 170 }, { label: localize('mep.f.area', "Area"), unit: localize('mep.unit.m2', "m²"), numeric: true, width: 64 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		document.shafts.forEach((s, index) => {
			const row = this.selectableRow(body, { kind: 'shaft', index });
			const path = (field: string) => `shafts.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, s.id, value => this.setField(s, 'id', value), path('id')));
			for (const end of ['fromStory', 'toStory'] as const) {
				append(append(row, $('td')), this.selectInput(this.storyOptions(), s[end], value => {
					s[end] = value;
					this.changed(true);
				}, path(end), end === 'fromStory' ? localize('mep.f.fromLong', "Starts at") : localize('mep.f.toLong', "Up to")));
			}
			append(append(row, $('td')), this.textInput(F.service, s.service, value => this.setField(s, 'service', value), path('service')));
			append(row, $('td.number', undefined, formatNumber(polygonArea(s.outline) / 1e6, 2)));
			this.removeButton(row, () => {
				document.shafts.splice(index, 1);
				this.selection = undefined;
				this.changed(true);
			});
		});
		if (!document.shafts.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('mep.noShafts', "None yet.")));
		}
	}

	private renderModelTable(document: IMep): void {
		const section = this.section(localize('mep.modelsHeading', "MEP IFC models"), document.ifcModels.length, { label: localize('mep.importShort', "Import Model"), run: () => void this.importIfc() });
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [{ label: F.path.label, width: 320 }, { label: localize('mep.f.discipline', "Discipline"), width: 130 }, { label: localize('mep.f.visible', "Visible"), width: 64 }, { label: '', width: 28 }];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		document.ifcModels.forEach((m, index) => {
			const row = append(body, $('tr'));
			const path = (field: string) => `ifcModels.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.path, m.path, value => this.setField(m, 'path', value), path('path')));
			append(append(row, $('td')), this.selectInput(DISCIPLINES.map(d => ({ value: d, label: disciplineLabel(d) })), m.discipline, value => {
				m.discipline = value;
				this.changed(true);
			}, path('discipline'), localize('mep.f.discipline', "Discipline")));
			append(append(row, $('td.mep-check-cell')), this.checkbox(m.visible !== false, value => {
				m.visible = value;
				this.changed(true);
			}, localize('mep.f.visibleAria', "Show {0}", m.path)));
			this.removeButton(row, () => {
				document.ifcModels.splice(index, 1);
				this.changed(true);
			});
		});
		if (!document.ifcModels.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('mep.noModels', "None yet. Import the mechanical, plumbing, fire and electrical IFC models to find where they cross the structure.")));
		}
	}

	/** Where an opening is on its host, in words. */
	private positionText(opening: IOpening): string {
		const host = findHost(this.context, opening.host);
		const p = opening.position ?? {};
		const mm = (v: unknown) => typeof v === 'number' ? formatNumber(v, 0) : '?';
		switch (host?.kind) {
			case 'beam': return localize('mep.posBeam', "{0} mm from start, {1} mm up", mm(p.distance), mm(p.elevation));
			case 'wall': return localize('mep.posWall', "{0} mm along, {1} mm up", mm(p.x), mm(p.y));
			case 'slab': return localize('mep.posSlab', "at {0}, {1} m", typeof p.x === 'number' ? formatNumber(p.x / 1000, 3) : '?', typeof p.y === 'number' ? formatNumber(p.y / 1000, 3) : '?');
			default: return '';
		}
	}

	private hostOptions(): { value: string; label: string }[] {
		return [
			...this.context.beams.map(b => ({ value: b.id, label: localize('mep.hostBeam', "Beam {0}", b.id) })),
			...this.context.slabs.map(s => ({ value: s.id, label: localize('mep.hostSlab', "Slab {0}", s.id) })),
			...this.context.walls.map(w => ({ value: w.id, label: localize('mep.hostWall', "Wall {0}", w.id) })),
		];
	}

	// ───────────────────────────── edits ─────────────────────────────

	private setField(target: { [key: string]: unknown }, key: string, value: number | string | undefined): void {
		if (value === undefined || value === '') {
			delete target[key];
		} else {
			target[key] = value;
		}
		this.changed(false);
	}

	private setStory(equipment: IEquipment, story: string): void {
		equipment.story = story;
		// Follow it to its story, so it stays in view.
		if (this.selection?.kind === 'equipment' && this.document?.equipment[this.selection.index] === equipment) {
			this.story = story;
			this.updateStoryPicker();
		}
		this.changed(true);
	}

	/** Moves an opening to another host: a new position where the new host needs one. */
	private setHost(opening: IOpening, hostId: string): void {
		const document = this.document;
		if (!document || opening.host === hostId) {
			return;
		}
		const fresh = newSleeve(document, this.context, hostId);
		opening.host = hostId;
		if (fresh) {
			opening.position = fresh.position;
		}
		this.changed(true);
	}

	private setShape(opening: IOpening, shape: string): void {
		if (opening.shape === shape) {
			return;
		}
		if (shape === 'circle') {
			opening.diameter ??= Math.max(opening.width ?? 0, opening.height ?? 0) || 150;
			delete opening.width;
			delete opening.height;
		} else {
			opening.width ??= opening.diameter ?? 300;
			opening.height ??= opening.diameter ?? 300;
			delete opening.diameter;
		}
		opening.shape = shape;
		this.changed(true);
	}

	// ───────────────────────────── inputs ─────────────────────────────

	private get inputStore(): DisposableStore {
		return this.renderingProperties ? this.propertiesDisposables : this.viewDisposables;
	}

	private get inputMap(): Map<string, HTMLElement> {
		return this.renderingProperties ? this.propertyInputs : this.inputs;
	}

	/** An input for a field: a valid value is stored (and saved after a pause), an invalid one is marked. */
	private textInput(field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key: string, placeholder?: string): HTMLInputElement {
		const numeric = field.kind !== 'text';
		const input = $<HTMLInputElement>(`input.mep-input${numeric ? '.number' : ''}`, { type: 'text', spellcheck: 'false', 'aria-label': field.unit ? `${field.label} (${field.unit})` : field.label });
		input.value = formatField(field, value);
		if (placeholder) {
			input.placeholder = placeholder;
		}
		this.inputStore.add(addDisposableListener(input, EventType.INPUT, () => {
			let parsed = parseField(field, input.value);
			const badId = field === F.id && typeof parsed.value === 'string' ? idError(parsed.value) : undefined;
			if (badId) {
				parsed = { error: localize('mep.v.id', "{0}: {1}", field.label, badId) };
			}
			this.markInvalid(input, parsed.error);
			if (!parsed.error) {
				store(parsed.value);
			}
		}));
		this.inputStore.add(addDisposableListener(input, EventType.BLUR, () => {
			if (!input.classList.contains('invalid')) {
				this.flush();
			}
		}));
		this.inputMap.set(key, input);
		return input;
	}

	private markInvalid(input: HTMLInputElement, error: string | undefined): void {
		input.classList.toggle('invalid', !!error);
		input.title = error ?? '';
		input.setAttribute('aria-invalid', String(!!error));
	}

	private selectInput(options: readonly { value: string; label: string }[], current: string, store: (value: string) => void, key: string, label: string, allowNone = false): HTMLSelectElement {
		const select = $<HTMLSelectElement>('select.mep-select', { 'aria-label': label });
		const all = [...(allowNone ? [{ value: '', label: '—' }] : []), ...options];
		if (current && !all.some(o => o.value === current)) {
			all.push({ value: current, label: current });
		}
		for (const option of all) {
			const element = append(select, $<HTMLOptionElement>('option', { value: option.value }, option.label));
			element.selected = option.value === current;
		}
		this.inputStore.add(addDisposableListener(select, EventType.CHANGE, () => store(select.value)));
		this.inputMap.set(key, select);
		return select;
	}

	private checkbox(checked: boolean, store: (value: boolean) => void, label: string): HTMLInputElement {
		const input = $<HTMLInputElement>('input.mep-checkbox', { type: 'checkbox', 'aria-label': label });
		input.checked = checked;
		this.inputStore.add(addDisposableListener(input, EventType.CHANGE, () => store(input.checked)));
		return input;
	}

	/** Marks the inputs that a check found a problem in (without re-rendering, so typing keeps focus). */
	private renderProblems(): void {
		for (const [key, input] of [...this.inputs, ...this.propertyInputs]) {
			if (input.classList.contains('invalid')) {
				continue;
			}
			const problem = this.problems.find(p => p.path === key);
			input.classList.toggle('warning', !!problem);
			input.title = problem?.message ?? '';
		}
	}

	// ───────────────────────────── results view ─────────────────────────────

	/** The backend's error, led by the file's own errors (which the backend refuses the file for) when there are any. */
	private reportErrorText(): string {
		const errors = this.problems.filter(p => p.severity === 'error');
		if (!errors.length) {
			return this.reportError ?? '';
		}
		return errors.length === 1
			? localize('mep.reportFixOne', "Fix this problem of the file first: {0}", errors[0].message)
			: localize('mep.reportFixMany', "Fix the {0} problems of the file first (see Problems in the properties panel); the first: {1}", errors.length, errors[0].message);
	}

	private renderResultsView(document: IMep): void {
		const view = this.viewElement;
		if (this.reportState !== 'ok' || !this.report) {
			const state = append(view, $('.mep-results-state'));
			const nothing = !this.hasContent(document);
			const computing = !nothing && (this.reportState === 'computing' || this.reportState === 'idle');
			const icon = nothing ? Codicon.tools : computing ? ThemeIcon.modify(Codicon.loading, 'spin') : this.reportState === 'error' ? Codicon.warning : Codicon.debugDisconnect;
			append(state, $(`span.mep-results-state-icon${ThemeIcon.asCSSSelector(icon)}`));
			append(state, $('.mep-results-state-title', undefined, nothing ? localize('mep.resultsNothing', "Nothing to check yet")
				: computing ? localize('mep.computing', "Checking the services...")
					: this.reportState === 'error' ? localize('mep.reportFailed', "The services could not be checked")
						: localize('mep.backendMissing', "Backend not available")));
			append(state, $('.mep-results-state-text', undefined, nothing
				? localize('mep.resultsNothingText', "Add equipment, sleeves or an MEP IFC model: their loads, checks and clashes appear here.")
				: this.reportState === 'error' ? this.reportErrorText()
					: this.reportState === 'missing' ? localize('mep.backendMissingText', "The equipment loads per story, the checks of the openings and the clashes of the MEP models with the structure are computed by the SAEngine Python backend; it is not running in this window. The services can still be laid out and edited; the results appear once the backend is available.") : ''));
			if (this.reportState === 'missing' && document.equipment.length) {
				this.renderLocalLoads(view, document);
			}
			return;
		}
		const report = this.report;
		const header = append(view, $('.mep-view-header'));
		append(header, $('span.mep-view-title', undefined, localize('mep.resultsTitle', "Loads, openings and clashes")));
		append(header, $('span.mep-view-subtitle', undefined, localize('mep.resultsSubtitle', "Computed by the backend from the services and the building model; not stored in the file.")));
		this.renderTiles(view, document, report);
		this.renderStoryLoads(view, report);
		this.renderOpeningChecks(view, document, report);
		this.renderClashes(view, report);
		if (report.notes.length) {
			const section = this.resultSection(view, localize('mep.notes', "Notes"));
			for (const note of report.notes) {
				append(section, $('p.mep-note', undefined, note));
			}
		}
		if (report.method.length) {
			const section = this.resultSection(view, localize('mep.method', "Method"));
			for (const line of report.method) {
				append(section, $('p.mep-note', undefined, line));
			}
		}
	}

	private resultSection(view: HTMLElement, title: string, detail?: string): HTMLElement {
		const section = append(view, $('.mep-section.result'));
		const heading = append(section, $('.mep-section-heading'));
		append(heading, $('span.mep-section-title', undefined, title));
		if (detail) {
			append(heading, $('span.mep-section-detail', undefined, detail));
		}
		return section;
	}

	private renderTiles(view: HTMLElement, document: IMep, report: IMepReport): void {
		const tiles = append(view, $('.mep-tiles'));
		const tile = (value: string, label: string, band?: string) => {
			const element = append(tiles, $('.mep-tile'));
			append(element, $(`span.mep-tile-value${band ? `.band-${band}` : ''}`, undefined, value));
			append(element, $('span.mep-tile-label', undefined, label));
		};
		const total = report.stories.length ? report.stories.reduce((s, x) => s + x.load, 0) : report.equipment.reduce((s, e) => s + (e.load ?? 0), 0);
		tile(String(document.equipment.length), localize('mep.tileEquipment', "equipment"));
		tile(localize('mep.knValue', "{0} kN", formatNumber(total, 0)), localize('mep.tileLoad', "equipment load on the structure"));
		const failed = report.openings.filter(o => !o.ok).length;
		const partial = report.openings.filter(isPartlyChecked).length;
		tile(String(failed), partial
			? localize('mep.tileOpeningsPartial', "of {0} openings fail; {1} not fully checked", report.openings.length, partial)
			: localize('mep.tileOpenings', "of {0} openings fail", report.openings.length), report.openings.length ? failed ? 'fail' : partial ? 'warn' : 'ok' : undefined);
		const open = report.clashes.filter(isOpenClash).length;
		tile(String(open), localize('mep.tileClashes', "clashes, {0} coordinated", report.clashes.filter(c => c.status === 'coordinated').length), report.clashes.length ? open ? 'fail' : 'ok' : undefined);
	}

	private storyName(id: string | undefined): string {
		return this.context.stories.find(s => s.id === id)?.name ?? id ?? '';
	}

	private renderStoryLoads(view: HTMLElement, report: IMepReport): void {
		const rows = report.stories.length ? report.stories : undefined;
		if (!rows && !report.equipment.length) {
			return;
		}
		const section = this.resultSection(view, localize('mep.storyLoads', "Equipment loads by story"));
		const table = append(section, $('table.mep-table.mep-result-table'));
		this.tableHead(table, [
			{ label: localize('mep.f.story', "Story"), width: 140 }, { label: localize('mep.f.count', "Equipment"), numeric: true, width: 80 },
			{ label: localize('mep.f.load', "Load"), unit: KN, numeric: true, width: 90 }, { label: localize('mep.note', "Note"), width: 300 },
		]);
		const body = append(table, $('tbody'));
		const list = rows ?? [...new Set(report.equipment.map(e => e.story ?? ''))].map(story => ({
			story, count: report.equipment.filter(e => (e.story ?? '') === story).length, load: report.equipment.filter(e => (e.story ?? '') === story).reduce((s, e) => s + (e.load ?? 0), 0), note: undefined,
		}));
		for (const row of list) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, this.storyName(row.story)));
			append(tr, $('td.number', undefined, row.count === undefined ? '' : String(row.count)));
			append(tr, $('td.number', undefined, formatNumber(row.load, 1)));
			append(tr, $('td.mep-wrap', undefined, row.note ?? ''));
		}
		if (report.equipment.length) {
			append(section, $('.mep-subheading', undefined, localize('mep.byEquipment', "By equipment")));
			const detail = append(section, $('table.mep-table.mep-result-table'));
			this.tableHead(detail, [
				{ label: F.id.label, width: 64 }, { label: localize('mep.f.story', "Story"), width: 120 }, { label: localize('mep.f.loads', "Loads"), width: 90 },
				{ label: localize('mep.f.load', "Load"), unit: KN, numeric: true, width: 80 }, { label: localize('mep.f.pressure', "Load"), unit: KPA, numeric: true, width: 72 },
				{ label: localize('mep.f.loadCase', "Load case"), width: 80 }, { label: localize('mep.note', "Note"), width: 260 },
			]);
			const detailBody = append(detail, $('tbody'));
			for (const e of report.equipment) {
				const index = this.document?.equipment.findIndex(x => x.id === e.id) ?? -1;
				const tr = index >= 0 ? this.selectableRow(detailBody, { kind: 'equipment', index }) : append(detailBody, $('tr'));
				append(tr, $('td', undefined, e.id));
				append(tr, $('td', undefined, this.storyName(e.story)));
				append(tr, $('td', undefined, e.host ?? ''));
				append(tr, $('td.number', undefined, e.load === undefined ? '' : formatNumber(e.load, 1)));
				append(tr, $('td.number', undefined, e.pressure === undefined ? '' : formatNumber(e.pressure, 1)));
				append(tr, $('td', undefined, e.loadCase ?? ''));
				append(tr, $('td.mep-wrap', undefined, e.note ?? ''));
			}
		}
	}

	/** Without the backend: the operating weights per story, summed here. */
	private renderLocalLoads(view: HTMLElement, document: IMep): void {
		const section = this.resultSection(view, localize('mep.localLoads', "Operating weights by story"), localize('mep.localLoadsDetail', "summed from the file; the loads on the structure come from the backend"));
		const table = append(section, $('table.mep-table.mep-result-table'));
		this.tableHead(table, [
			{ label: localize('mep.f.story', "Story"), width: 140 }, { label: localize('mep.f.count', "Equipment"), numeric: true, width: 80 },
			{ label: F.operatingWeight.label, unit: KN, numeric: true, width: 110 }, { label: localize('mep.f.plinths', "Plinths"), unit: KN, numeric: true, width: 80 },
		]);
		const body = append(table, $('tbody'));
		for (const row of storyLoads(document, this.context)) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, this.storyName(row.story)));
			append(tr, $('td.number', undefined, String(row.count)));
			append(tr, $('td.number', undefined, formatNumber(row.operating, 1)));
			append(tr, $('td.number', undefined, formatNumber(row.plinths, 1)));
		}
	}

	private utilisationCell(row: HTMLElement, utilisation: number | null | undefined, ok?: boolean): void {
		const td = append(row, $('td.number.mep-util-cell'));
		if (typeof utilisation !== 'number') {
			td.textContent = ok === false ? localize('mep.fails', "fails") : ok ? localize('mep.passes', "ok") : '';
			if (ok === false) {
				td.classList.add('band-fail');
			}
			return;
		}
		const band = ok === false && utilisation <= 1 ? 'fail' : utilisationBand(utilisation);
		const bar = append(td, $('span.mep-util-bar'));
		append(bar, $(`span.mep-util-fill.band-${band}`, { style: `width: ${Math.min(100, utilisation * 100).toFixed(0)}%` }));
		append(td, $(`span.mep-util-value.band-${band}`, undefined, formatUtilisation(utilisation)));
	}

	private renderOpeningChecks(view: HTMLElement, document: IMep, report: IMepReport): void {
		if (!report.openings.length) {
			return;
		}
		const section = this.resultSection(view, localize('mep.openingChecks', "Opening checks"), localize('mep.openingChecksDetail', "the governing check of each; click one to show it in the plan"));
		const table = append(section, $('table.mep-table.mep-result-table'));
		this.tableHead(table, [
			{ label: F.id.label, width: 64 }, { label: localize('mep.f.host', "Host"), width: 100 }, { label: F.service.label, width: 140 },
			{ label: localize('mep.check', "Check"), width: 220 }, { label: localize('mep.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('mep.note', "Note"), width: 280 },
		]);
		const body = append(table, $('tbody'));
		for (const check of report.openings) {
			const index = document.openings.findIndex(o => o.id === check.id);
			const opening = document.openings[index];
			const row = index >= 0 ? this.selectableRow(body, { kind: 'opening', index }) : append(body, $('tr'));
			append(row, $('td', undefined, check.id));
			append(row, $('td', undefined, check.host ?? opening?.host ?? ''));
			append(row, $('td', undefined, opening?.service ?? ''));
			const checkCell = append(row, $('td', undefined, check.check ?? ''));
			if (isPartlyChecked(check) && check.checked) {
				append(checkCell, $('span.mep-partial', undefined, localize('mep.strengthNotChecked', "strength not checked")));
			}
			if (check.checked) {
				this.utilisationCell(row, check.utilisation, check.ok);
			} else {
				append(row, $('td.number.mep-muted-cell', undefined, localize('mep.notChecked', "not checked")));
			}
			append(row, $('td.mep-wrap', undefined, check.note ?? ''));
			if (check.checked && !check.ok) {
				row.classList.add('failed');
			}
			if (index >= 0) {
				row.tabIndex = 0;
				this.viewDisposables.add(addDisposableListener(row, EventType.DBLCLICK, () => this.revealOpening(index)));
			}
		}
		this.markSelectedRows();
	}

	private revealOpening(index: number): void {
		const opening = this.document?.openings[index];
		if (!opening) {
			return;
		}
		const story = hostStory(this.context, findHost(this.context, opening.host))?.id;
		this.selection = { kind: 'opening', index };
		if (story) {
			this.story = story;
			this.updateStoryPicker();
		}
		this.view = 'plan';
		this.render();
	}

	private renderClashes(view: HTMLElement, report: IMepReport): void {
		if (!report.clashes.length) {
			if (this.document?.ifcModels.length) {
				const section = this.resultSection(view, localize('mep.clashes', "Clashes"));
				append(section, $('p.mep-note', undefined, localize('mep.noClashes', "No element of the MEP models crosses the structure without an opening.")));
			}
			return;
		}
		const open = report.clashes.filter(isOpenClash).length;
		const section = this.resultSection(view, localize('mep.clashes', "Clashes"), localize('mep.clashesDetail', "{0} open, {1} coordinated by an opening or shaft", open, report.clashes.filter(c => c.status === 'coordinated').length));
		const table = append(section, $('table.mep-table.mep-result-table.mep-clash-table'));
		this.tableHead(table, [
			{ label: localize('mep.f.mepElement', "MEP element"), width: 200 }, { label: localize('mep.f.structural', "Structural element"), width: 130 },
			{ label: localize('mep.f.clashKind', "Kind"), width: 90 }, { label: localize('mep.f.status', "Status"), width: 110 }, { label: '', width: 220 },
		]);
		const body = append(table, $('tbody'));
		// Open clashes first.
		for (const clash of [...report.clashes].sort((a, b) => Number(a.status === 'coordinated') - Number(b.status === 'coordinated'))) {
			const row = append(body, $(`tr.mep-clash-row${clash.status === 'clash' ? '.failed' : ''}${this.selectedClash === clash.id ? '.selected' : ''}`));
			const mep = append(row, $('td'));
			append(mep, $('span', undefined, clash.mepName ?? clash.mep));
			if (clash.discipline) {
				append(mep, $('span.mep-muted-inline', undefined, ` · ${disciplineLabel(clash.discipline)}`));
			}
			const host = findHost(this.context, clash.structural);
			append(row, $('td', undefined, host ? `${hostKindLabel(host.kind)} ${clash.structural}` : clash.structural));
			append(row, $('td', undefined, clash.kind === 'hard' ? localize('mep.clashHard', "passes through") : clash.kind === 'clearance' ? localize('mep.clashClearance', "too close") : clash.kind));
			const statusCell = append(row, $('td'));
			append(statusCell, $(`span.mep-status-pill.${clash.status}`, undefined, clash.status === 'clash'
				? localize('mep.statusClash', "clash")
				: clash.opening ? localize('mep.statusCoordinatedBy', "coordinated ({0})", clash.opening) : localize('mep.statusCoordinated', "coordinated")));
			const actions = append(row, $('td.mep-clash-actions'));
			// Only where the backend proposed a sleeve: a service along a beam or wall, or through a column, is rerouted.
			if (isOpenClash(clash) && clash.sleeve) {
				this.linkButton(actions, localize('mep.addSleeveShort', "Add Sleeve"), Codicon.add, () => this.addSleeveForClash(clash));
			} else if (isOpenClash(clash) && clash.note) {
				append(actions, $('span.mep-muted-inline', undefined, clash.note));
			}
			if (clash.point || this.clashStory(clash)) {
				this.linkButton(actions, localize('mep.showInPlan', "Show in Plan"), Codicon.location, () => this.showClash(clash));
			}
		}
	}

	private linkButton(container: HTMLElement, label: string, icon: ThemeIcon, run: () => void): void {
		const button = append(container, $<HTMLButtonElement>('button.mep-add', { type: 'button' }));
		append(button, $(ThemeIcon.asCSSSelector(icon)));
		append(button, $('span', undefined, label));
		this.viewDisposables.add(addDisposableListener(button, EventType.CLICK, e => {
			e.stopPropagation();
			run();
		}));
	}

	// ───────────────────────────── properties panel ─────────────────────────────

	private renderProperties(): void {
		const panel = this.frame?.properties;
		if (!panel) {
			return;
		}
		const document = this.document;
		const active = panel.ownerDocument.activeElement;
		const focused = active && panel.contains(active) && (isHTMLInputElement(active) || active.tagName === 'SELECT') ? active : undefined;
		const selection = this.selectionKey;
		const same = this.propertiesFor?.document === document && this.propertiesFor?.selection === selection;
		if (focused && same) {
			return;
		}
		const focusedKey = focused ? [...this.propertyInputs].find(([, input]) => input === focused)?.[0] : undefined;
		this.propertiesDisposables.clear();
		this.propertyInputs.clear();
		clearNode(panel);
		this.propertiesFor = { document, selection };
		if (!document) {
			appendPropertyNote(panel, this.parseError ?? localize('mep.propsNone', "No MEP file."));
			return;
		}
		this.renderingProperties = true;
		let paths: string[] = [];
		try {
			const s = this.selection;
			if (s?.kind === 'equipment' && document.equipment[s.index]) {
				this.renderEquipmentProperties(panel, document.equipment[s.index], s.index);
				paths = [`equipment.${s.index}.`];
			} else if (s?.kind === 'opening' && document.openings[s.index]) {
				this.renderOpeningProperties(panel, document.openings[s.index], s.index);
				paths = [`openings.${s.index}.`];
			} else if (s?.kind === 'shaft' && document.shafts[s.index]) {
				this.renderShaftProperties(panel, document.shafts[s.index], s.index);
				paths = [`shafts.${s.index}.`];
			} else if (s?.kind === 'element') {
				this.renderElementProperties(panel, document, s.id);
			} else {
				this.renderSummaryProperties(panel, document);
				paths = ['equipment.', 'openings.', 'shafts.', 'ifcModels.'];
			}
		} finally {
			this.renderingProperties = false;
		}
		const shown = this.problems.filter(p => paths.some(prefix => p.path.startsWith(prefix)));
		if (shown.length) {
			appendPropertyHeading(panel, localize('mep.problems', "Problems ({0})", shown.length));
			for (const problem of shown) {
				appendPropertyNote(panel, problem.message).classList.add(problem.severity);
			}
		}
		this.renderProblems();
		if (focusedKey) {
			this.propertyInputs.get(focusedKey)?.focus();
		}
	}

	private propertyRow(panel: HTMLElement, label: string, control: HTMLElement, unit?: string, title?: string): void {
		const wrapper = $('.mep-prop-control');
		append(wrapper, control);
		if (unit) {
			append(wrapper, $('span.mep-prop-unit', undefined, unit));
		}
		const row = appendPropertyRow(panel, label, wrapper);
		row.classList.add('mep-prop-row');
		if (title) {
			row.title = title;
		}
	}

	private fieldRow(panel: HTMLElement, field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key: string, placeholder?: string): void {
		this.propertyRow(panel, field.label, this.textInput(field, value, store, key, placeholder), field.unit, field.title);
	}

	private yesNo(current: boolean, store: (value: boolean) => void, key: string, label: string): HTMLSelectElement {
		return this.selectInput([
			{ value: 'no', label: localize('mep.no', "No") },
			{ value: 'yes', label: localize('mep.yes', "Yes") },
		], current ? 'yes' : 'no', value => store(value === 'yes'), key, label);
	}

	private renderEquipmentProperties(panel: HTMLElement, e: IEquipment, index: number): void {
		const path = (field: string) => `equipment.${index}.${field}`;
		appendPropertyHeading(panel, localize('mep.equipmentHeadingOne', "{0} {1}", equipmentKindLabel(e.kind), e.id));
		this.fieldRow(panel, F.id, e.id, value => this.setField(e, 'id', value), path('id'));
		this.fieldRow(panel, F.name, e.name, value => this.setField(e, 'name', value), path('name'));
		this.propertyRow(panel, localize('mep.f.kind', "Kind"), this.selectInput(EQUIPMENT_KINDS.map(k => ({ value: k, label: equipmentKindLabel(k) })), e.kind, value => {
			e.kind = value;
			this.changed(true);
		}, path('kind'), localize('mep.f.kind', "Kind")));
		this.propertyRow(panel, localize('mep.f.story', "Story"), this.selectInput(this.storyOptions(), e.story, value => this.setStory(e, value), path('story'), localize('mep.f.story', "Story")));

		appendPropertyHeading(panel, localize('mep.placement', "Placement and size"));
		this.fieldRow(panel, F.x, e.x, value => this.setField(e, 'x', value), path('x'));
		this.fieldRow(panel, F.y, e.y, value => this.setField(e, 'y', value), path('y'));
		this.fieldRow(panel, F.rotation, e.rotation, value => this.setField(e, 'rotation', value), path('rotation'), '0');
		this.fieldRow(panel, F.length, e.length, value => this.setField(e, 'length', value), path('length'));
		this.fieldRow(panel, F.width, e.width, value => this.setField(e, 'width', value), path('width'));
		this.fieldRow(panel, F.height, e.height, value => this.setField(e, 'height', value), path('height'));

		appendPropertyHeading(panel, localize('mep.loadHeading', "Load"));
		this.fieldRow(panel, F.operatingWeight, e.operatingWeight, value => this.setField(e, 'operatingWeight', value), path('operatingWeight'));
		this.fieldRow(panel, F.emptyWeight, e.emptyWeight, value => this.setField(e, 'emptyWeight', value), path('emptyWeight'));
		this.propertyRow(panel, localize('mep.f.loadAs', "Load as"), this.selectInput([
			{ value: 'area', label: localize('mep.loadAs.area', "Spread over the footprint") },
			{ value: 'points', label: localize('mep.loadAs.points', "On four feet") },
		], e.loadAs ?? 'area', value => {
			if (value === 'points') {
				e.loadAs = 'points';
			} else {
				delete e.loadAs;
			}
			this.changed(true);
		}, path('loadAs'), localize('mep.f.loadAs', "Load as")));
		this.propertyRow(panel, localize('mep.f.vibrating', "Vibrating"), this.yesNo(!!e.vibrating, value => {
			if (value) {
				e.vibrating = true;
			} else {
				delete e.vibrating;
			}
			this.changed(true);
		}, path('vibrating'), localize('mep.f.vibrating', "Vibrating")), undefined, localize('mep.f.vibratingTitle', "Rotating or reciprocating machinery (chillers, pumps, generators): the backend reports it for the floor's vibration and the mountings"));
		const pressure = equipmentPressure(e);
		appendPropertyRow(panel, localize('mep.f.footprint', "Footprint"), localize('mep.m2Value', "{0} m²", formatNumber(equipmentArea(e), 2)));
		if (pressure !== undefined) {
			appendPropertyRow(panel, localize('mep.f.pressureLong', "Load over the footprint"), localize('mep.kpaValue', "{0} kPa", formatNumber(pressure, 2)));
		}

		appendPropertyHeading(panel, localize('mep.plinthHeading', "Plinth"));
		this.fieldRow(panel, F.plinth, e.plinth?.height, value => {
			if (typeof value === 'number') {
				// A new plinth is of the first concrete of 03 Materials (the backend needs its material).
				const created = !e.plinth;
				const concrete = this.context.concretes[0]?.id;
				e.plinth ??= concrete ? { material: concrete } : {};
				e.plinth.height = value;
				this.changed(created);
			} else {
				const removed = !!e.plinth;
				delete e.plinth;
				this.changed(removed);
			}
		}, path('plinth.height'), localize('mep.none', "none"));
		if (e.plinth) {
			const current = e.plinth;
			// The material cannot be cleared: '—' is offered only while none is chosen yet.
			this.propertyRow(panel, localize('mep.f.concrete', "Concrete"), this.selectInput(this.context.concretes.map(c => ({ value: c.id, label: c.id })), current.material ?? '', value => {
				if (value) {
					current.material = value;
					this.changed(true);
				}
			}, path('plinth.material'), localize('mep.f.concrete', "Concrete"), !current.material));
			appendPropertyRow(panel, localize('mep.f.plinthWeight', "Plinth weight"), localize('mep.knValue', "{0} kN", formatNumber(plinthWeight(e, this.context), 2)));
		}

		const result = this.reportState === 'ok' ? this.report?.equipment.find(r => r.id === e.id) : undefined;
		if (result) {
			appendPropertyHeading(panel, localize('mep.onStructure', "On the structure"));
			if (result.load !== undefined) {
				appendPropertyRow(panel, localize('mep.f.load', "Load"), localize('mep.knValue', "{0} kN", formatNumber(result.load, 1)));
			}
			if (result.host) {
				appendPropertyRow(panel, localize('mep.f.loads', "Loads"), result.host);
			}
			if (result.loadCase) {
				appendPropertyRow(panel, localize('mep.f.loadCase', "Load case"), result.loadCase);
			}
			if (result.note) {
				appendPropertyNote(panel, result.note);
			}
		}
	}

	private renderOpeningProperties(panel: HTMLElement, o: IOpening, index: number): void {
		const path = (field: string) => `openings.${index}.${field}`;
		const host = findHost(this.context, o.host);
		appendPropertyHeading(panel, localize('mep.openingHeadingOne', "{0} {1}", openingKindLabel(o.kind), o.id));
		this.fieldRow(panel, F.id, o.id, value => this.setField(o, 'id', value), path('id'));
		this.propertyRow(panel, localize('mep.f.host', "Host"), this.selectInput(this.hostOptions(), o.host, value => this.setHost(o, value), path('host'), localize('mep.f.host', "Host")));
		if (host) {
			const span = host.kind === 'slab' ? undefined : Math.hypot(host.element.end[0] - host.element.start[0], host.element.end[1] - host.element.start[1]);
			appendPropertyRow(panel, '', host.kind === 'beam' ? localize('mep.beamInfo', "{0} × {1} mm, {2} m long", formatNumber(host.element.width, 0), formatNumber(host.element.depth, 0), formatNumber((span ?? 0) / 1000, 2))
				: host.kind === 'wall' ? localize('mep.wallInfo', "{0} mm thick, {1} m long", formatNumber(host.element.thickness, 0), formatNumber((span ?? 0) / 1000, 2))
					: localize('mep.slabInfo', "{0} mm thick", formatNumber(host.element.thickness, 0)));
		}
		this.propertyRow(panel, localize('mep.f.openingKind', "Kind"), this.selectInput(OPENING_KINDS.map(k => ({ value: k, label: openingKindLabel(k) })), o.kind, value => {
			o.kind = value;
			this.changed(true);
		}, path('kind'), localize('mep.f.openingKind', "Kind")), undefined, localize('mep.f.openingKindTitle', "A sleeve is cast in for a pipe; an opening is left for a duct or a group of services"));
		this.fieldRow(panel, F.service, o.service, value => this.setField(o, 'service', value), path('service'));

		appendPropertyHeading(panel, localize('mep.sizeHeading', "Size"));
		this.propertyRow(panel, localize('mep.f.shape', "Shape"), this.selectInput(OPENING_SHAPES.map(s => ({ value: s, label: openingShapeLabel(s) })), o.shape, value => this.setShape(o, value), path('shape'), localize('mep.f.shape', "Shape")));
		if (o.shape === 'circle') {
			this.fieldRow(panel, F.diameter, o.diameter, value => this.setField(o, 'diameter', value), path('diameter'));
		} else {
			this.fieldRow(panel, F.openingWidth, o.width, value => this.setField(o, 'width', value), path('width'));
			this.fieldRow(panel, F.openingHeight, o.height, value => this.setField(o, 'height', value), path('height'));
		}

		appendPropertyHeading(panel, localize('mep.positionHeading', "Position"));
		const position = o.position;
		const store = (key: string) => (value: number | string | undefined) => this.setField(position, key, value);
		if (host?.kind === 'beam') {
			this.fieldRow(panel, F.distance, position.distance, store('distance'), path('position.distance'));
			this.fieldRow(panel, F.elevation, position.elevation, store('elevation'), path('position.elevation'));
		} else if (host?.kind === 'wall') {
			this.fieldRow(panel, F.along, position.x, store('x'), path('position.x'));
			this.fieldRow(panel, F.up, position.y, store('y'), path('position.y'));
		} else {
			this.fieldRow(panel, F.slabX, position.x, store('x'), path('position.x'));
			this.fieldRow(panel, F.slabY, position.y, store('y'), path('position.y'));
		}

		const check = this.reportState === 'ok' ? this.report?.openings.find(r => r.id === o.id) : undefined;
		if (check) {
			appendPropertyHeading(panel, localize('mep.checkHeading', "Check"));
			if (check.check) {
				appendPropertyRow(panel, localize('mep.check', "Check"), check.check);
			}
			const band = check.ok ? utilisationBand(check.utilisation) : 'fail';
			appendPropertyRow(panel, localize('mep.f.utilisation', "Utilisation"), !check.checked ? localize('mep.notChecked', "not checked")
				: $(`span.mep-util-value.band-${band}`, undefined, typeof check.utilisation === 'number' ? formatUtilisation(check.utilisation) : check.ok ? localize('mep.passes', "ok") : localize('mep.fails', "fails")));
			if (check.checked && !check.strengthChecked) {
				appendPropertyRow(panel, localize('mep.strength', "Strength"), localize('mep.strengthNotRun', "not checked: only its size and spacing are"));
			}
			if (check.note) {
				appendPropertyNote(panel, check.note);
			}
		}
	}

	private renderShaftProperties(panel: HTMLElement, s: IShaft, index: number): void {
		const path = (field: string) => `shafts.${index}.${field}`;
		appendPropertyHeading(panel, localize('mep.shaftHeadingOne', "Shaft {0}", s.id));
		this.fieldRow(panel, F.id, s.id, value => this.setField(s, 'id', value), path('id'));
		this.fieldRow(panel, F.service, s.service, value => this.setField(s, 'service', value), path('service'));
		for (const end of ['fromStory', 'toStory'] as const) {
			const label = end === 'fromStory' ? localize('mep.f.fromLong', "Starts at") : localize('mep.f.toLong', "Up to");
			const select = this.selectInput(this.storyOptions(), s[end], value => {
				s[end] = value;
				this.changed(true);
			}, path(end), label);
			const title = end === 'fromStory' ? localize('mep.f.fromTitle', "The story the shaft starts at: its floor is not cut") : localize('mep.f.toTitle', "The highest story whose floor the shaft cuts");
			this.propertyRow(panel, label, select, undefined, title);
		}
		const cut = this.context.stories.filter(story => shaftOnStory(s, this.context, story.id)).map(story => story.name);
		if (cut.length) {
			appendPropertyRow(panel, localize('mep.f.cuts', "Cuts the floors of"), cut.join(', '));
		}
		appendPropertyHeading(panel, localize('mep.outlineHeading', "Outline"));
		const input = $<HTMLInputElement>('input.mep-input', { type: 'text', spellcheck: 'false', 'aria-label': localize('mep.f.outline', "Outline") });
		input.value = s.outline.map(p => `${formatNumber(p[0] / 1000, 3)} ${formatNumber(p[1] / 1000, 3)}`).join('; ');
		this.propertiesDisposables.add(addDisposableListener(input, EventType.INPUT, () => {
			const points = input.value.split(';').map(pair => pair.trim().split(/[\s,]+/).map(Number)).filter(p => p.length === 2 && p.every(Number.isFinite));
			const valid = points.length >= 3 && points.length === input.value.split(';').filter(t => t.trim()).length;
			this.markInvalid(input, valid ? undefined : localize('mep.outlineInvalid', "Give at least three points as x y in m, separated by semicolons: 0 0; 1.5 0; 1.5 1.5"));
			if (valid) {
				s.outline = points.map(p => [Math.round(p[0] * 1000), Math.round(p[1] * 1000)] as Point);
				this.changed(false);
			}
		}));
		this.propertiesDisposables.add(addDisposableListener(input, EventType.BLUR, () => this.flush()));
		this.propertyInputs.set(path('outline'), input);
		this.propertyRow(panel, localize('mep.f.outline', "Outline"), input, M, localize('mep.outlineTitle', "Corner points as x y in m, separated by semicolons; drag the shaft in the plan to move it"));
		appendPropertyRow(panel, localize('mep.f.area', "Area"), localize('mep.m2Value', "{0} m²", formatNumber(polygonArea(s.outline) / 1e6, 2)));
	}

	private renderElementProperties(panel: HTMLElement, document: IMep, id: string): void {
		const host = findHost(this.context, id);
		const column = this.context.columns.find(c => c.id === id);
		if (column) {
			appendPropertyHeading(panel, localize('mep.columnHeading', "Column {0}", id));
			appendPropertyRow(panel, localize('mep.f.section', "Section"), column.circle ? localize('mep.circleSection', "Ø{0} mm", formatNumber(column.xDim, 0)) : localize('mep.rectSection', "{0} × {1} mm", formatNumber(column.xDim, 0), formatNumber(column.yDim, 0)));
			appendPropertyNote(panel, localize('mep.columnHint', "Services do not pass through columns. Select a beam, slab or wall to add a sleeve through it."));
			return;
		}
		if (!host) {
			appendPropertyNote(panel, localize('mep.elementMissing', "{0} is not in the building model.", id));
			return;
		}
		appendPropertyHeading(panel, localize('mep.hostHeading', "{0} {1}", hostKindLabel(host.kind), id));
		if (host.kind === 'beam') {
			appendPropertyRow(panel, localize('mep.f.section', "Section"), localize('mep.rectSection', "{0} × {1} mm", formatNumber(host.element.width, 0), formatNumber(host.element.depth, 0)));
			appendPropertyRow(panel, localize('mep.f.span', "Length"), localize('mep.mValue', "{0} m", formatNumber(Math.hypot(host.element.end[0] - host.element.start[0], host.element.end[1] - host.element.start[1]) / 1000, 2)));
		} else if (host.kind === 'wall') {
			appendPropertyRow(panel, localize('mep.f.thickness', "Thickness"), localize('mep.mmValue', "{0} mm", formatNumber(host.element.thickness, 0)));
		} else {
			appendPropertyRow(panel, localize('mep.f.thickness', "Thickness"), localize('mep.mmValue', "{0} mm", formatNumber(host.element.thickness, 0)));
			appendPropertyRow(panel, localize('mep.f.area', "Area"), localize('mep.m2Value', "{0} m²", formatNumber(polygonArea(host.element.boundary) / 1e6, 2)));
		}
		const through = document.openings.filter(o => o.host === id);
		appendPropertyRow(panel, localize('mep.f.openings', "Sleeves and openings"), through.length ? through.map(o => o.id).join(', ') : localize('mep.noneShort', "none"));
		appendPropertyNote(panel, localize('mep.hostHint', "Add a sleeve through it with the sleeve button in the toolbar."));
	}

	private renderSummaryProperties(panel: HTMLElement, document: IMep): void {
		const story = this.context.stories.find(s => s.id === this.story);
		if (story) {
			appendPropertyHeading(panel, story.name);
			const onStory = document.equipment.filter(e => e.story === story.id);
			appendPropertyRow(panel, localize('mep.equipmentHeading', "Equipment"), String(onStory.length));
			appendPropertyRow(panel, localize('mep.f.operatingTotal', "Operating weight"), localize('mep.knValue', "{0} kN", formatNumber(onStory.reduce((s, e) => s + (e.operatingWeight || 0), 0), 1)));
			const elements = storyElements(this.context, story.id);
			appendPropertyRow(panel, localize('mep.f.floor', "Floor"), localize('mep.floorValue', "{0} slabs, {1} beams", elements.slabs.length, elements.beams.length));
		}
		appendPropertyHeading(panel, localize('mep.summaryHeading', "MEP"));
		appendPropertyRow(panel, localize('mep.equipmentHeading', "Equipment"), String(document.equipment.length));
		appendPropertyRow(panel, localize('mep.openingsHeading', "Sleeves and openings"), String(document.openings.length));
		appendPropertyRow(panel, localize('mep.shaftsHeading', "Shafts"), String(document.shafts.length));
		appendPropertyRow(panel, localize('mep.modelsHeading', "MEP IFC models"), String(document.ifcModels.length));
		appendPropertyNote(panel, localize('mep.summaryNote', "Select an equipment, a sleeve, a shaft or a beam, slab or wall in the plan to edit it here."));
	}

	// ───────────────────────────── status line ─────────────────────────────

	private renderStatus(): void {
		const frame = this.frame;
		if (!frame) {
			return;
		}
		const document = this.document;
		if (!document) {
			frame.setStatus(this.parseError ? { severity: 'warning', text: this.parseError } : undefined);
			return;
		}
		if (!this.hasContent(document)) {
			frame.setStatus({ text: localize('mep.statusEmpty', "No equipment yet · {0} stories", this.context.stories.length) });
			return;
		}
		const ok = this.reportState === 'ok' ? this.report : undefined;
		const parts = [mepSummary(document, ok)];
		if (this.reportState === 'missing') {
			parts.push(localize('mep.statusNoBackend', "checks need the backend"));
		} else if (this.reportState === 'error') {
			parts.push(localize('mep.statusFailed', "checks could not be computed"));
		}
		const errors = this.problems.filter(p => p.severity === 'error').length;
		const failed = !!ok && (ok.openings.some(o => !o.ok) || ok.clashes.some(isOpenClash));
		const partial = !!ok && ok.openings.some(isPartlyChecked);
		const status: IEditorFrameStatus = {
			text: parts.join(' · '),
			severity: errors || failed ? 'error' : this.problems.length || partial || this.reportState === 'error' ? 'warning' : undefined,
			busy: this.reportState === 'computing',
			link: this.problems.length ? {
				label: localize('mep.statusProblems', "{0} problem(s)", this.problems.length),
				run: () => this.revealFirstProblem(),
			} : ok && this.view !== 'results' ? {
				label: localize('mep.statusShowResults', "Results"),
				run: () => this.showView('results'),
			} : undefined,
		};
		frame.setStatus(status);
	}

	private revealFirstProblem(): void {
		const problem = this.problems[0];
		if (!problem) {
			return;
		}
		const match = /^(?<list>equipment|openings|shafts)\.(?<index>\d+)\./.exec(problem.path);
		const index = Number(match?.groups?.index);
		if (match?.groups?.list === 'equipment') {
			this.selection = { kind: 'equipment', index };
			const story = this.document?.equipment[index]?.story;
			if (story && this.context.stories.some(s => s.id === story)) {
				this.story = story;
				this.updateStoryPicker();
			}
		} else if (match?.groups?.list === 'openings') {
			this.selection = { kind: 'opening', index };
		} else if (match?.groups?.list === 'shafts') {
			this.selection = { kind: 'shaft', index };
		} else {
			this.view = 'data';
		}
		this.frame.setPropertiesVisible(true);
		this.render();
		(this.propertyInputs.get(problem.path) ?? this.inputs.get(problem.path))?.focus();
	}
}
