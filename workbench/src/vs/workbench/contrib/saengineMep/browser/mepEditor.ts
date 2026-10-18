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
	idError, isOpenClash, isPartlyChecked, nextId, storyAt, storyElements, storyLoads, utilisationBand,
} from './mepDocument.js';
import { MepEditorInput } from './mepEditorInput.js';
import { IPlanClash, IPlanView, MepSelection, renderPlan } from './mepPlan.js';
import {
	allIds, checkPlumbing, constructionLabel, ensurePlumbing, FIXTURES, fixtureLabel, fixtureTotals, hasPlumbing, IOccupancy, IPlumbing, IPlumbingReport, IRiser, IRoofDrain, ITank, isGroundTank, mergeSizedTanks,
	newRiser, newRoofDrain, newTank, PIPE_MATERIALS, PLUMBING_OCCUPANCIES_COMMAND, PLUMBING_REPORT_COMMAND, PLUMBING_SIZE_TANKS_COMMAND, PLUMBING_SLEEVES_COMMAND, PLUMBING_SYSTEMS, plumbingFailures, plumbingOf,
	plumbingSummary, plumbingSummaryFile, PlumbingSystem, readOccupancies, readPlumbingReport, readSizedTanks, riserOnStory, sourceLabel, STATIC_OCCUPANCIES, storyRow, SUPPLY_SOURCES, systemLabel, systemLetters,
	TANK_CONSTRUCTIONS, TANK_KINDS, tankCapacity, TankKind, tankKindLabel, tankStory,
} from './plumbingDocument.js';
import { plumbingExtent, renderPlumbing } from './plumbingPlan.js';
import { renderPlumbingReport } from './plumbingResults.js';

type View = 'plan' | 'data' | 'results';

/** What can be dragged in the plan, the plumbing (drawn on top) first. */
type DragKind = 'riser' | 'drain' | 'tank' | 'equipment' | 'shaft';
const DRAG_KINDS: readonly DragKind[] = ['riser', 'drain', 'tank', 'equipment', 'shaft'];

/** What the editor shows: the coordination of the services with the structure, or the plumbing set-up. */
type Discipline = 'coordination' | 'plumbing';

const DISCIPLINE_VIEWS: readonly { readonly discipline: Discipline; readonly label: string }[] = [
	{ discipline: 'coordination', label: localize('mep.disciplineCoordination', "Coordination") },
	{ discipline: 'plumbing', label: localize('mep.disciplinePlumbing', "Plumbing") },
];

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

/** The plumbing's fields (the contract of `plumbing` in mep.json): sizes in mm, positions in m. */
const P = {
	mainsHead: { key: 'mainsHead', label: localize('plb.f.mainsHead', "Mains residual head"), unit: M, kind: 'number', min: 0, title: localize('plb.f.mainsHeadTitle', "Residual head of the city main at the connection") },
	pumpHours: { key: 'pumpHours', label: localize('plb.f.pumpHours', "Pumping hours"), unit: localize('plb.unit.hDay', "h/day"), kind: 'number', min: 0.5, max: 24, title: localize('plb.f.pumpHoursTitle', "Hours a day the pump fills the overhead tank; empty for the backend's default") },
	minResidualHead: { key: 'minResidualHead', label: localize('plb.f.minHead', "Minimum residual head"), unit: M, kind: 'number', min: 0.1, title: localize('plb.f.minHeadTitle', "Override of the minimum residual head at the outlets; empty for the code's") },
	rainfall: { key: 'rainfallIntensity', label: localize('plb.f.rainfall', "Rainfall intensity"), unit: localize('plb.unit.mmh', "mm/h"), kind: 'number', min: 1, title: localize('plb.f.rainfallTitle', "Design rainfall intensity for the roof drains; empty for the backend's Dhaka value") },
	population: { key: 'population', label: localize('plb.f.population', "Population"), kind: 'integer', min: 0, width: 80, title: localize('plb.f.populationTitle', "Persons on the storey; for a hotel, its beds (BNBC Table 8.5.1(d) gives hotels per bed, hospitals per person)") },
	diameter: { key: 'diameter', label: localize('plb.f.diameter', "Diameter"), unit: MM, kind: 'number', min: 1, width: 72, title: localize('plb.f.diameterTitle', "Your size; empty to have it sized by the backend") },
	length: { key: 'length', label: localize('plb.f.length', "Length"), unit: MM, kind: 'number', min: 1, width: 72, title: localize('plb.f.lengthTitle', "Inside length") },
	width: { key: 'width', label: localize('plb.f.width', "Width"), unit: MM, kind: 'number', min: 1, width: 72, title: localize('plb.f.widthTitle', "Inside width") },
	wellDiameter: { key: 'diameter', label: localize('plb.f.wellDiameter', "Diameter"), unit: MM, kind: 'number', min: 1, width: 72, title: localize('plb.f.wellDiameterTitle', "Inside diameter of the soak well") },
	waterDepth: { key: 'waterDepth', label: localize('plb.f.waterDepth', "Water depth"), unit: MM, kind: 'number', min: 1, width: 72 },
	freeboard: { key: 'freeboard', label: localize('plb.f.freeboard', "Freeboard"), unit: MM, kind: 'number', min: 0, width: 72 },
	compartments: { key: 'compartments', label: localize('plb.f.compartments', "Compartments"), kind: 'integer', min: 1, width: 72 },
	walls: { key: 'walls', label: localize('plb.f.walls', "Walls"), unit: MM, kind: 'number', min: 1, title: localize('plb.f.wallsTitle', "Wall thickness") },
	base: { key: 'base', label: localize('plb.f.base', "Base"), unit: MM, kind: 'number', min: 1, title: localize('plb.f.baseTitle', "Base slab thickness") },
	roof: { key: 'roof', label: localize('plb.f.roof', "Roof"), unit: MM, kind: 'number', min: 1, title: localize('plb.f.roofTitle', "Cover slab thickness") },
	topLevel: { key: 'topLevel', label: localize('plb.f.topLevel', "Top level"), unit: MM, kind: 'number', title: localize('plb.f.topLevelTitle', "Top of the tank relative to the ground (negative: buried below it)") },
	area: { key: 'area', label: localize('plb.f.catchment', "Catchment"), unit: localize('plb.unit.m2', "m²"), kind: 'number', min: 0.01, width: 80, title: localize('plb.f.catchmentTitle', "Roof area the drain takes; empty to split the roof slab by the nearest drain") },
} satisfies { [key: string]: IFieldSpec };

/** A fixture count's field. */
function fixtureField(key: string, label: string): IFieldSpec {
	return { key, label, kind: 'integer', min: 0, width: 56 };
}

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
	private discipline: Discipline = 'coordination';
	private readonly disciplineButtons = new Map<Discipline, HTMLButtonElement>();

	private plumbingReport: IPlumbingReport | undefined;
	private plumbingState: ReportState = 'idle';
	private plumbingError: string | undefined;
	private plumbingVersion = 0;
	private occupancies: readonly IOccupancy[] = STATIC_OCCUPANCIES;
	private occupanciesFromBackend = false;
	/** The cells of the fixtures table's totals row, refreshed while typing. */
	private readonly totalCells = new Map<string, HTMLElement>();

	private report: IMepReport | undefined;
	private reportState: ReportState = 'idle';
	private reportError: string | undefined;
	private reportVersion = 0;
	private readonly busy = new Set<string>();
	private actionsKey: string | undefined;
	private lastSize = '';
	private planView: IPlanView | undefined;
	private drag: { kind: DragKind; index: number; x: number; y: number; group: Element; moved: boolean } | undefined;
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
	private readonly reportScheduler = this._register(new RunOnceScheduler(() => void this.computeReports(), 1200));
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

	private readonly riserActions = PLUMBING_SYSTEMS.map(system => this._register(new Action(`saengine.mep.editor.addRiser.${system}`, localize('plb.addSystem', "{0} ({1})", systemLabel(system), systemLetters(system)), undefined, true, async () => this.addRiser(system))));
	private readonly addRiserAction = new SubmenuAction('saengine.mep.editor.addRiser', localize('plb.addRiser', "Add Riser or Stack"), this.riserActions, ThemeIcon.asClassName(Codicon.arrowUp));
	private readonly tankActions = (['overhead', 'underground', 'septic', 'soakWell', 'rainwater'] as const).map(kind => this._register(new Action(`saengine.mep.editor.addTank.${kind}`, tankKindLabel(kind), undefined, true, async () => this.addTank(kind))));
	private readonly addTankAction = new SubmenuAction('saengine.mep.editor.addTank', localize('plb.addTank', "Add Tank"), this.tankActions, ThemeIcon.asClassName(Codicon.database));
	private readonly addDrainAction = this._register(new Action('saengine.mep.editor.addDrain', localize('plb.addDrain', "Add Roof Drain"), ThemeIcon.asClassName(Codicon.arrowCircleDown), true, async () => this.addDrain()));
	private readonly sizeTanksAction = this._register(new Action('saengine.mep.editor.sizeTanks', localize('plb.sizeTanks', "Size Tanks"), ThemeIcon.asClassName(Codicon.wand), true, () => this.sizeTanks()));
	private readonly riserSleevesAction = this._register(new Action('saengine.mep.editor.riserSleeves', localize('plb.riserSleeves', "Add Sleeves for Risers"), ThemeIcon.asClassName(Codicon.circleLargeOutline), true, () => this.addRiserSleeves()));
	private readonly recomputePlumbingAction = this._register(new Action('saengine.mep.editor.recomputePlumbing', localize('plb.recompute', "Check the Plumbing Again"), undefined, true, () => this.computePlumbingReport()));

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
			if ((id === MEP_REPORT_COMMAND && this.reportState === 'missing') || (id === PLUMBING_REPORT_COMMAND && this.plumbingState === 'missing')) {
				this.reportScheduler.schedule(0);
			}
			if (id === PLUMBING_OCCUPANCIES_COMMAND) {
				void this.loadOccupancies();
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

		const disciplines = append(frame.titleSlot, $('.sa-segmented.mep-discipline', { role: 'tablist', 'aria-label': localize('mep.disciplineAria', "Discipline") }));
		for (const { discipline, label } of DISCIPLINE_VIEWS) {
			const button = append(disciplines, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }));
			append(button, $('span', undefined, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.showDiscipline(discipline)));
			this.disciplineButtons.set(discipline, button);
		}
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
		this.plumbingReport = undefined;
		this.plumbingState = 'idle';
		this.selection = undefined;
		this.selectedClash = undefined;
		this.story = undefined;
		void this.loadOccupancies();
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
			this.problems = this.check(this.document);
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
		this.problems = this.document ? this.check(this.document) : [];
		this.render();
		this.reportScheduler.schedule(this.reportState === 'idle' ? 0 : undefined);
	}

	private selectionExists(document: IMep): boolean {
		const selection = this.selection;
		switch (selection?.kind) {
			case 'equipment': return selection.index < document.equipment.length;
			case 'opening': return selection.index < document.openings.length;
			case 'shaft': return selection.index < document.shafts.length;
			case 'riser': return selection.index < (plumbingOf(document)?.risers.length ?? 0);
			case 'tank': return selection.index < (plumbingOf(document)?.tanks.length ?? 0);
			case 'drain': return selection.index < (plumbingOf(document)?.roof.drains.length ?? 0);
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
		if (this.selection?.kind !== 'opening' && this.selection?.kind !== 'riser') {
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
		this.problems = this.check(this.document);
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
		for (const kind of ['riser', 'drain', 'tank'] as const) {
			const index = pick(`data-${kind}`);
			if (index) {
				this.select({ kind, index: Number(index) });
				return;
			}
		}
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
		const kind = DRAG_KINDS.find(k => target?.closest(`[data-${k}]`));
		const group = kind ? target?.closest(`[data-${kind}]`) : undefined;
		if (!kind || !group || e.button !== 0) {
			return;
		}
		this.drag = { kind, index: Number(group.getAttribute(`data-${kind}`)), x: e.clientX, y: e.clientY, group, moved: false };
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
		const plumbing = plumbingOf(document);
		const point = drag.kind === 'equipment' ? document.equipment[drag.index]
			: drag.kind === 'riser' ? plumbing?.risers[drag.index]
				: drag.kind === 'tank' ? plumbing?.tanks[drag.index]
					: drag.kind === 'drain' ? plumbing?.roof.drains[drag.index] : undefined;
		if (point) {
			point.x = point.x + dx;
			point.y = point.y + dy;
		} else if (drag.kind === 'shaft') {
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
			case 'riser': plumbingOf(document)?.risers.splice(selection.index, 1); break;
			case 'tank': plumbingOf(document)?.tanks.splice(selection.index, 1); break;
			case 'drain': plumbingOf(document)?.roof.drains.splice(selection.index, 1); break;
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
		const added = this.addOpenings(document, answer?.openings ?? []);
		if (!added.length) {
			this.notificationService.info(answer?.notes.length ? answer.notes.join(' ') : localize('mep.suggestNone', "No crossing of the MEP models with the structure needs a new sleeve."));
			return;
		}
		const first = added[0];
		this.added({ kind: 'opening', index: document.openings.indexOf(first) }, hostStory(this.context, findHost(this.context, first.host))?.id);
		this.notificationService.info(added.length === 1 ? localize('mep.suggestedOne', "Added 1 sleeve where an MEP model crosses the structure.") : localize('mep.suggested', "Added {0} sleeves where the MEP models cross the structure.", added.length));
	}

	/** Adds the proposed openings the file does not have yet (none on the same host within 50 mm), with unused IDs. */
	private addOpenings(document: IMep, proposals: readonly IOpening[]): IOpening[] {
		const added: IOpening[] = [];
		for (const proposal of proposals) {
			const point = openingPoint(proposal, this.context);
			const same = document.openings.some(o => {
				const other = openingPoint(o, this.context);
				return o.host === proposal.host && !!point && !!other && Math.hypot(point[0] - other[0], point[1] - other[1]) < 50;
			});
			if (same) {
				continue;
			}
			const used = allIds(document);
			if (!proposal.id || used.includes(proposal.id)) {
				proposal.id = nextId('OP', used);
			}
			document.openings.push(proposal);
			added.push(proposal);
		}
		return added;
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
		return document.equipment.length + document.openings.length + document.shafts.length + document.ifcModels.length > 0 || hasPlumbing(document);
	}

	/** The file's problems: the coordination's and the plumbing's. */
	private check(document: IMep): IMepProblem[] {
		return [...checkMep(document, this.context), ...checkPlumbing(document, this.context)];
	}

	/** Both reports, after an edit. */
	private async computeReports(): Promise<void> {
		await Promise.all([this.computeReport(), this.computePlumbingReport()]);
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
		this.writeSummary(document, sourceTexts);
	}

	/**
	 * The part list's summary, once the coordination report is in: with the plumbing's failures
	 * (key `plumbing`) when its report is in too. It describes the saved file: written only when
	 * the editor holds no unsaved edits.
	 */
	private writeSummary(document: IMep, sourceTexts: IMepContextTexts): void {
		const model = this.model;
		const report = this.reportState === 'ok' ? this.report : undefined;
		if (!report || !model || !this.resource || this.input?.isDirty() || this.document !== document) {
			return;
		}
		const plumbing = this.plumbingState === 'ok' && this.plumbingReport ? { plumbing: plumbingSummaryFile(document, this.plumbingReport) } : {};
		const content = JSON.stringify({ ...mepSummaryFile(document, report, model.getValue(), new Date(), sourceTexts), ...plumbing }, undefined, '\t') + '\n';
		this.fileService.writeFile(joinPath(dirname(this.resource), MEP_SUMMARY_FILE), VSBuffer.fromString(content)).catch(() => { /* the part list then shows the count only */ });
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		if (!this.frame) {
			return;
		}
		this.frame.element.classList.toggle('plumbing', this.discipline === 'plumbing');
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
		for (const [discipline, button] of this.disciplineButtons) {
			const active = discipline === this.discipline;
			button.classList.toggle('active', active);
			button.setAttribute('aria-selected', String(active));
			button.disabled = !usable;
		}
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
		const plumbing = document ? plumbingOf(document) : undefined;
		const named = selection?.kind === 'equipment' ? document?.equipment[selection.index]?.id
			: selection?.kind === 'opening' ? document?.openings[selection.index]?.id
				: selection?.kind === 'shaft' ? document?.shafts[selection.index]?.id
					: selection?.kind === 'riser' ? plumbing?.risers[selection.index]?.id
						: selection?.kind === 'tank' ? plumbing?.tanks[selection.index]?.id
							: selection?.kind === 'drain' ? plumbing?.roof.drains[selection.index]?.id : undefined;
		this.deleteAction.enabled = !!named;
		this.deleteAction.label = named ? localize('mep.deleteNamed', "Delete {0}", named) : localize('mep.delete', "Delete");
		this.recomputeAction.enabled = !!document && this.hasContent(document);
		const plumbingView = this.discipline === 'plumbing';
		this.recomputePlumbingAction.enabled = !!document && hasPlumbing(document);
		this.riserSleevesAction.enabled = !!plumbing?.risers.length;
		const primary: IAction[] = !usable ? [frame.togglePropertiesAction] : plumbingView ? [
			this.addRiserAction, this.addTankAction, this.addDrainAction, this.sizeTanksAction, this.riserSleevesAction, this.deleteAction, frame.togglePropertiesAction,
		] : [
			this.addEquipmentAction, this.addSleeveAction, this.addShaftAction, this.importIfcAction, this.suggestAction, this.deleteAction, frame.togglePropertiesAction,
		];
		const secondary: IAction[] = usable ? [plumbingView ? this.recomputePlumbingAction : this.recomputeAction] : [];
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
		this.totalCells.clear();
		if (this.discipline === 'plumbing') {
			switch (this.view) {
				case 'plan': this.renderPlanView(document); break;
				case 'data': this.renderPlumbingData(document); break;
				case 'results': this.renderPlumbingResults(document); break;
			}
		} else {
			switch (this.view) {
				case 'plan': this.renderPlanView(document); break;
				case 'data': this.renderDataView(document); break;
				case 'results': this.renderResultsView(document); break;
			}
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
		const plumbingView = this.discipline === 'plumbing';
		const onStory = document.equipment.filter(e => e.story === this.story);
		const load = onStory.reduce((sum, e) => sum + (e.operatingWeight || 0), 0);
		const plumbing = plumbingOf(document);
		append(header, $('span.mep-view-subtitle', undefined, !story
			? localize('mep.planSubtitleNone', "Build the building model to lay out the services on its stories.")
			: plumbingView
				? localize('plb.planSubtitle', "level {0} m · risers and stacks: {1}, tanks: {2} · click to select, drag to move",
					formatNumber(story.elevation / 1000, 2), plumbing?.risers.filter(r => riserOnStory(r, this.context, story.id)).length ?? 0, plumbing?.tanks.filter(t => tankStory(t, this.context) === story.id).length ?? 0)
				: localize('mep.planSubtitle', "level {0} m · {1} equipment, {2} kN · click to select, drag equipment and shafts to move them",
					formatNumber(story.elevation / 1000, 2), onStory.length, formatNumber(load, 1))));

		const legend = append(view, $('.mep-legend'));
		const item = (cls: string, label: string, text?: string) => {
			const element = append(legend, $('span.mep-legend-item'));
			append(element, text ? $(`span.mep-swatch.${cls}`, undefined, text) : $(`span.mep-swatch.${cls}`));
			append(element, $('span', undefined, label));
		};
		if (plumbingView) {
			const systems = new Set(plumbing?.risers.filter(r => !story || riserOnStory(r, this.context, story.id)).map(r => r.system));
			for (const system of PLUMBING_SYSTEMS.filter(s => systems.has(s))) {
				item(`plb-sys.sys-${system}`, systemLabel(system), systemLetters(system));
			}
			item('plb-tank', localize('plb.legendTank', "Tank"));
			if (plumbing?.roof.drains.some(d => d.story === story?.id)) {
				item('plb-drain', localize('plb.legendDrain', "Roof drain"));
			}
			item('shaft', localize('mep.legendShaft', "Shaft"));
			item('sleeve', localize('mep.legendSleeve', "Sleeve or opening"));
		} else {
			item('equipment', localize('mep.legendEquipment', "Equipment"));
			item('shaft', localize('mep.legendShaft', "Shaft"));
			item('sleeve', localize('mep.legendSleeve', "Sleeve or opening"));
			item('beam', localize('mep.legendBeam', "Beam"));
			item('slab', localize('mep.legendSlab', "Slab"));
		}
		const clashes = plumbingView ? [] : this.planClashes();
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
		const plumbingReport = this.plumbingState === 'ok' ? this.plumbingReport : undefined;
		this.planView = renderPlan(canvas, document, this.context, {
			width, height, story: story.id, selection: this.selection, openingBands: bands, clashes, selectedClash: this.selectedClash,
			...(plumbingView ? {
				plumbing: true,
				extraExtent: plumbingExtent(document, this.context, story.id),
				overlay: (root, planView) => renderPlumbing(root, planView, document, this.context, { story: story.id, selection: this.selection, report: plumbingReport }),
			} : {}),
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

	private section(title: string, count: number | undefined, add?: { label: string; run: () => void }): HTMLElement {
		const section = append(this.viewElement, $('.mep-section'));
		const heading = append(section, $('.mep-section-heading'));
		append(heading, $('span.mep-section-title', undefined, title));
		if (count !== undefined) {
			append(heading, $('span.mep-section-count', undefined, String(count)));
		}
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
			} else if (s?.kind === 'riser' && plumbingOf(document)?.risers[s.index]) {
				this.renderRiserProperties(panel, ensurePlumbing(document).risers[s.index], s.index);
				paths = [`plumbing.risers.${s.index}.`];
			} else if (s?.kind === 'tank' && plumbingOf(document)?.tanks[s.index]) {
				this.renderTankProperties(panel, ensurePlumbing(document).tanks[s.index], s.index);
				paths = [`plumbing.tanks.${s.index}.`];
			} else if (s?.kind === 'drain' && plumbingOf(document)?.roof.drains[s.index]) {
				this.renderDrainProperties(panel, ensurePlumbing(document).roof.drains[s.index], s.index);
				paths = [`plumbing.roof.drains.${s.index}.`];
			} else if (s?.kind === 'element') {
				this.renderElementProperties(panel, document, s.id);
			} else if (this.discipline === 'plumbing') {
				this.renderPlumbingSummaryProperties(panel, document);
				paths = ['plumbing.'];
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
		if (this.discipline === 'plumbing') {
			this.renderPlumbingStatus(document);
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
		this.revealProblem(this.problems[0]);
	}

	private revealProblem(problem: IMepProblem | undefined): void {
		if (!problem) {
			return;
		}
		const match = /^(?<list>equipment|openings|shafts|plumbing\.risers|plumbing\.tanks|plumbing\.roof\.drains)\.(?<index>\d+)\./.exec(problem.path);
		const index = Number(match?.groups?.index);
		const plumbingKind = match?.groups?.list === 'plumbing.risers' ? 'riser' : match?.groups?.list === 'plumbing.tanks' ? 'tank' : match?.groups?.list === 'plumbing.roof.drains' ? 'drain' : undefined;
		if (problem.path.startsWith('plumbing.') && this.discipline !== 'plumbing') {
			this.discipline = 'plumbing';
		} else if (!problem.path.startsWith('plumbing.') && this.discipline === 'plumbing') {
			this.discipline = 'coordination';
		}
		if (plumbingKind) {
			const selection: MepSelection = { kind: plumbingKind, index };
			this.selection = selection;
			const story = this.selectionStory(selection);
			if (story) {
				this.story = story;
				this.updateStoryPicker();
			}
			if (this.view !== 'plan') {
				this.view = 'plan';
			}
		} else if (problem.path.startsWith('plumbing.')) {
			this.view = 'data';
		} else if (match?.groups?.list === 'equipment') {
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

	// ───────────────────────────── plumbing ─────────────────────────────

	/** The occupancies of BNBC Table 8.5.1 from the backend, once it lists them; until then the static list. */
	private async loadOccupancies(): Promise<void> {
		if (this.occupanciesFromBackend || !CommandsRegistry.getCommand(PLUMBING_OCCUPANCIES_COMMAND)) {
			return;
		}
		try {
			const list = readOccupancies(await this.commandService.executeCommand<unknown>(PLUMBING_OCCUPANCIES_COMMAND));
			if (list) {
				this.occupancies = list;
				this.occupanciesFromBackend = true;
				if (this.discipline === 'plumbing' && this.view === 'data') {
					this.renderView();
				}
			}
		} catch {
			// The static list stays.
		}
	}

	private showDiscipline(discipline: Discipline): void {
		if (discipline === this.discipline) {
			return;
		}
		this.flush();
		this.discipline = discipline;
		this.selection = undefined;
		this.selectedClash = undefined;
		this.render();
	}

	/** The story a riser, tank or drain is seen on: the one shown when it is on it, else its own. */
	private selectionStory(selection: MepSelection): string | undefined {
		const plumbing = this.document ? plumbingOf(this.document) : undefined;
		switch (selection.kind) {
			case 'riser': {
				const riser = plumbing?.risers[selection.index];
				return riser && this.story && riserOnStory(riser, this.context, this.story) ? this.story : riser?.fromStory;
			}
			case 'tank': {
				const tank = plumbing?.tanks[selection.index];
				return tank ? tankStory(tank, this.context) : undefined;
			}
			case 'drain': return plumbing?.roof.drains[selection.index]?.story;
			default: return undefined;
		}
	}

	private noStories(): boolean {
		if (this.context.stories.length) {
			return false;
		}
		this.notificationService.info(localize('plb.noStories', "The building model has no stories yet. Build it (6 BIM) first: the plumbing is laid out on its stories."));
		return true;
	}

	addRiser(system: PlumbingSystem): void {
		const document = this.document;
		if (!document || this.noStories()) {
			return;
		}
		const plumbing = ensurePlumbing(document);
		plumbing.risers.push(newRiser(document, this.context, system, this.story));
		this.added({ kind: 'riser', index: plumbing.risers.length - 1 });
	}

	addTank(kind: TankKind): void {
		const document = this.document;
		if (!document || this.noStories()) {
			return;
		}
		const plumbing = ensurePlumbing(document);
		const top = this.context.stories[this.context.stories.length - 1]?.id;
		// An overhead tank on the story shown when it is above the base, else on the roof.
		const story = kind === 'overhead' ? (this.story && this.story !== this.context.stories[0]?.id ? this.story : top) : undefined;
		const tank = newTank(document, this.context, kind, story);
		plumbing.tanks.push(tank);
		this.added({ kind: 'tank', index: plumbing.tanks.length - 1 }, tankStory(tank, this.context));
	}

	addDrain(): void {
		const document = this.document;
		if (!document || this.noStories()) {
			return;
		}
		const plumbing = ensurePlumbing(document);
		const story = this.story && this.story !== this.context.stories[0]?.id ? this.story : this.context.stories[this.context.stories.length - 1].id;
		plumbing.roof.drains.push(newRoofDrain(document, this.context, story));
		this.added({ kind: 'drain', index: plumbing.roof.drains.length - 1 }, story);
	}

	/** The backend proposes the tanks (overhead, reservoir, septic tank...) from the demand: one undoable edit. */
	async sizeTanks(): Promise<void> {
		this.flush();
		const request = this.request();
		const document = this.document;
		if (!request || !document) {
			return;
		}
		if (!plumbingOf(document)?.stories.length) {
			this.notificationService.info(localize('plb.sizeNeedsFixtures', "Give the fixtures and population of the storeys first (Data): the tanks are sized from the daily demand."));
			return;
		}
		if (!CommandsRegistry.getCommand(PLUMBING_SIZE_TANKS_COMMAND)) {
			this.notificationService.info(localize('plb.sizeNoBackend', "Sizing the tanks needs the SAEngine backend, which is not available in this window."));
			return;
		}
		this.setBusy('sizeTanks', true);
		let answer: { tanks: ITank[]; notes: string[] } | undefined;
		try {
			answer = readSizedTanks(await this.commandService.executeCommand<unknown>(PLUMBING_SIZE_TANKS_COMMAND, request));
		} catch (error) {
			this.notificationService.error(localize('plb.sizeFailed', "The tanks could not be sized: {0}", error instanceof Error ? error.message : String(error)));
			return;
		} finally {
			this.setBusy('sizeTanks', false);
		}
		if (this.document !== document || !answer) {
			return;
		}
		if (!answer.tanks.length) {
			this.notificationService.info(answer.notes.length ? answer.notes.join(' ') : localize('plb.sizeNone', "The backend proposed no tanks."));
			return;
		}
		const touched = mergeSizedTanks(document, answer.tanks);
		if (!touched.length) {
			this.notificationService.info([localize('plb.sizeSame', "The tanks already have the sizes SAEngine proposes."), ...answer.notes].join(' '));
			return;
		}
		const plumbing = ensurePlumbing(document);
		const first = touched[0];
		this.added({ kind: 'tank', index: plumbing.tanks.indexOf(first) }, tankStory(first, this.context));
		this.notificationService.info([
			touched.length === 1 ? localize('plb.sizedOne', "Sized 1 tank; edit it as needed (undo restores the previous sizes).") : localize('plb.sized', "Sized {0} tanks; edit them as needed (undo restores the previous sizes).", touched.length),
			...answer.notes,
		].join(' '));
	}

	/** The sleeves the risers and stacks need through the floors, added as one undoable edit. */
	async addRiserSleeves(): Promise<void> {
		this.flush();
		const request = this.request();
		const document = this.document;
		if (!request || !document) {
			return;
		}
		if (!CommandsRegistry.getCommand(PLUMBING_SLEEVES_COMMAND)) {
			this.notificationService.info(localize('plb.sleevesNoBackend', "Adding sleeves for the risers needs the SAEngine backend, which is not available in this window."));
			return;
		}
		this.setBusy('riserSleeves', true);
		let answer: { openings: IOpening[]; notes: string[] } | undefined;
		try {
			answer = readSleeveSuggestions(await this.commandService.executeCommand<unknown>(PLUMBING_SLEEVES_COMMAND, request));
		} catch (error) {
			this.notificationService.error(localize('plb.sleevesFailed', "The sleeves could not be found: {0}", error instanceof Error ? error.message : String(error)));
			return;
		} finally {
			this.setBusy('riserSleeves', false);
		}
		if (this.document !== document) {
			return;
		}
		const added = this.addOpenings(document, answer?.openings ?? []);
		if (!added.length) {
			this.notificationService.info(answer?.notes.length ? answer.notes.join(' ') : localize('plb.sleevesNone', "Every riser and stack already has its sleeves."));
			return;
		}
		const first = added[0];
		this.added({ kind: 'opening', index: document.openings.indexOf(first) }, hostStory(this.context, findHost(this.context, first.host))?.id);
		this.notificationService.info(added.length === 1 ? localize('plb.sleevesOne', "Added 1 sleeve for the risers and stacks.") : localize('plb.sleeves', "Added {0} sleeves for the risers and stacks.", added.length));
	}

	/** Asks the backend for the plumbing report (with the coordination's, after every edit). */
	async computePlumbingReport(): Promise<void> {
		const document = this.document;
		const version = ++this.plumbingVersion;
		const request = this.request();
		if (!document || !request || !hasPlumbing(document)) {
			this.setBusy('plumbing', false);
			this.plumbingReport = undefined;
			this.plumbingState = 'idle';
			this.renderReportDependent();
			return;
		}
		if (!CommandsRegistry.getCommand(PLUMBING_REPORT_COMMAND)) {
			this.setBusy('plumbing', false);
			this.plumbingReport = undefined;
			this.plumbingState = 'missing';
			this.renderReportDependent();
			return;
		}
		this.flush();
		const sourceTexts = this.siteTexts();
		this.plumbingState = this.plumbingReport ? 'ok' : 'computing';
		this.setBusy('plumbing', true);
		let report: IPlumbingReport | undefined;
		let error: string | undefined;
		try {
			report = readPlumbingReport(await this.commandService.executeCommand<unknown>(PLUMBING_REPORT_COMMAND, request));
			if (!report) {
				error = localize('plb.reportEmpty', "The backend gave no plumbing report.");
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		if (version !== this.plumbingVersion) {
			return;
		}
		this.setBusy('plumbing', false);
		this.plumbingReport = report;
		this.plumbingState = report ? 'ok' : 'error';
		this.plumbingError = error;
		this.renderReportDependent();
		this.writeSummary(document, sourceTexts);
	}

	// ───────────────────────────── plumbing: data view ─────────────────────────────

	private occupancyOptions(): { value: string; label: string }[] {
		return this.occupancies.map(o => ({ value: o.key, label: o.lpcd ? localize('plb.occOption', "{0} ({1} lpcd)", o.label, o.lpcd) : o.label }));
	}

	/** A store into the plumbing's object `target` of field `key`; creates the plumbing on the first edit. */
	private plumbingStore(target: () => { [key: string]: unknown }, key: string, after?: () => void): (value: number | string | undefined) => void {
		return value => {
			const object = target();
			if (value === undefined || value === '') {
				delete object[key];
			} else {
				object[key] = value;
			}
			after?.();
			this.changed(false);
		};
	}

	private renderPlumbingData(document: IMep): void {
		const view = this.viewElement;
		const plumbing = plumbingOf(document);
		const header = append(view, $('.mep-view-header'));
		append(header, $('span.mep-view-title', undefined, localize('plb.dataTitle', "Plumbing set-up")));
		append(header, $('span.mep-view-subtitle', undefined, localize('plb.dataSubtitle', "The fixtures and population of each storey, the supply, the risers and stacks, the tanks and the roof drains; sizes in mm, positions in m.")));
		const p = () => ensurePlumbing(document);

		// Supply and roof.
		const supply = this.section(localize('plb.supply', "Supply and roof"), undefined);
		const grid = append(supply, $('.plb-settings'));
		const setting = (label: string, control: HTMLElement, unit?: string, title?: string) => {
			const element = append(grid, $('label.plb-setting', title ? { title } : undefined));
			append(element, $('span.plb-setting-label', undefined, label));
			const wrapper = append(element, $('span.plb-setting-control'));
			append(wrapper, control);
			if (unit) {
				append(wrapper, $('span.mep-unit', undefined, unit));
			}
		};
		setting(localize('plb.f.source', "Source"), this.selectInput(SUPPLY_SOURCES.map(s => ({ value: s, label: sourceLabel(s) })), String(plumbing?.supply.source ?? ''), value => {
			const s = p().supply;
			if (value) {
				s.source = value;
			} else {
				delete s.source;
			}
			this.changed(true);
		}, 'plumbing.supply.source', localize('plb.f.source', "Source"), true));
		for (const field of [P.mainsHead, P.pumpHours, P.minResidualHead] as const) {
			setting(field.label, this.textInput(field, plumbing?.supply[field.key], this.plumbingStore(() => p().supply, field.key), `plumbing.supply.${field.key}`, field === P.minResidualHead ? localize('plb.codeValue', "code") : undefined), field.unit, field.title);
		}
		setting(P.rainfall.label, this.textInput(P.rainfall, plumbing?.roof.rainfallIntensity, this.plumbingStore(() => p().roof, P.rainfall.key), 'plumbing.roof.rainfallIntensity', localize('plb.defaultValue', "default")), P.rainfall.unit, P.rainfall.title);

		// Fixtures by storey: one row per story of the building (and any the file names that it lacks).
		const rows = plumbing?.stories ?? [];
		const known = new Set(this.context.stories.map(s => s.id));
		const storyIds = [...this.context.stories.map(s => s.id).reverse(), ...rows.map(r => r.story).filter(id => !known.has(id))];
		const fixtures = this.section(localize('plb.fixtures', "Fixtures by storey"), rows.length);
		if (!this.occupanciesFromBackend) {
			append(fixtures, $('p.mep-note.plb-static-note', undefined, localize('plb.staticOccupancies', "Occupancies: the BNBC Table 8.5.1 rows SAEngine starts from (full facility); the backend's list replaces them when it is available.")));
		}
		const table = append(append(fixtures, $('.mep-table-scroll')), $('table.mep-table.plb-fixtures'));
		const columns = [
			{ label: localize('plb.f.story', "Storey"), width: 110 }, { label: localize('plb.f.occupancy', "Occupancy"), width: 270 }, { label: P.population.label, numeric: true, width: 80 },
			...FIXTURES.map(key => ({ label: fixtureLabel(key), numeric: true, width: 62 })), { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		for (const storyId of storyIds) {
			const index = rows.findIndex(r => r.story === storyId);
			const row = rows[index];
			const tr = append(body, $(`tr.mep-row${row ? '' : '.plb-empty-row'}`));
			const path = (field: string) => index >= 0 ? `plumbing.stories.${index}.${field}` : `plumbing.new.${storyId}.${field}`;
			const target = () => storyRow(p(), storyId);
			append(tr, $('td', undefined, this.storyName(storyId)));
			append(append(tr, $('td')), this.selectInput(this.occupancyOptions(), String(row?.occupancy ?? ''), value => {
				const r = target();
				if (value) {
					r.occupancy = value;
				} else {
					delete r.occupancy;
				}
				this.changed(true);
			}, path('occupancy'), localize('plb.f.occupancyOf', "Occupancy of {0}", this.storyName(storyId)), true));
			append(append(tr, $('td')), this.textInput(P.population, row?.population, this.plumbingStore(target, 'population', () => this.updatePlumbingTotals(document)), path('population')));
			for (const key of FIXTURES) {
				const field = fixtureField(key, fixtureLabel(key));
				append(append(tr, $('td')), this.textInput(field, row?.fixtures[key], this.plumbingStore(() => target().fixtures, key, () => this.updatePlumbingTotals(document)), path(`fixtures.${key}`)));
			}
			if (row) {
				this.removeButton(tr, () => {
					p().stories.splice(index, 1);
					this.changed(true);
				});
			} else {
				append(tr, $('td'));
			}
		}
		const totals = append(body, $('tr.plb-total'));
		append(totals, $('td', { colspan: '2' }, localize('plb.totals', "Totals")));
		for (const key of ['population', ...FIXTURES]) {
			this.totalCells.set(key, append(totals, $('td.number')));
		}
		append(totals, $('td'));
		this.updatePlumbingTotals(document);
		if (rows.some(r => r.fixtures.other?.length)) {
			append(fixtures, $('p.mep-note', undefined, localize('plb.otherNote', "Other fixtures of the file (with their own supply and drainage units) are kept and counted; edit them as text.")));
		}

		this.renderRiserTable(document);
		this.renderTankTable(document);
		this.renderDrainTable(document);
		this.markSelectedRows();
	}

	private updatePlumbingTotals(document: IMep): void {
		const plumbing = plumbingOf(document);
		const totals = plumbing ? fixtureTotals(plumbing) : undefined;
		for (const [key, cell] of this.totalCells) {
			const value = totals?.[key as keyof typeof totals] ?? 0;
			cell.textContent = value ? formatNumber(value, 0) : '';
		}
	}

	private renderRiserTable(document: IMep): void {
		const risers = plumbingOf(document)?.risers ?? [];
		const section = this.section(localize('plb.risers', "Risers and stacks"), risers.length, { label: localize('plb.addColdRiser', "Add Cold Water Riser"), run: () => this.addRiser('coldWater') });
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('plb.f.system', "System"), width: 190 }, { label: F.x.label, unit: M, numeric: true }, { label: F.y.label, unit: M, numeric: true },
			{ label: localize('mep.f.fromLong', "Starts at"), width: 110 }, { label: localize('mep.f.toLong', "Up to"), width: 110 }, { label: localize('plb.f.shaft', "Shaft"), width: 90 },
			{ label: P.diameter.label, unit: MM, numeric: true }, { label: localize('plb.f.material', "Material"), width: 86 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		risers.forEach((r, index) => {
			const row = this.selectableRow(body, { kind: 'riser', index });
			const path = (field: string) => `plumbing.risers.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, r.id, value => this.setField(r, 'id', value), path('id')));
			append(append(row, $('td')), this.selectInput(PLUMBING_SYSTEMS.map(s => ({ value: s, label: `${systemLetters(s)} · ${systemLabel(s)}` })), r.system, value => {
				r.system = value;
				this.changed(true);
			}, path('system'), localize('plb.f.system', "System")));
			for (const field of [F.x, F.y]) {
				append(append(row, $('td')), this.textInput(field, r[field.key], value => this.setField(r, field.key, value), path(field.key)));
			}
			for (const end of ['fromStory', 'toStory'] as const) {
				append(append(row, $('td')), this.selectInput(this.storyOptions(), r[end], value => {
					r[end] = value;
					this.changed(true);
				}, path(end), end === 'fromStory' ? localize('mep.f.fromLong', "Starts at") : localize('mep.f.toLong', "Up to")));
			}
			append(append(row, $('td')), this.selectInput(document.shafts.map(s => ({ value: s.id, label: s.id })), r.shaft ?? '', value => this.setOptional(r, 'shaft', value), path('shaft'), localize('plb.f.shaft', "Shaft"), true));
			append(append(row, $('td')), this.textInput(P.diameter, r.diameter, value => this.setField(r, 'diameter', value), path('diameter'), this.sizedDiameter(r)));
			append(append(row, $('td')), this.selectInput(PIPE_MATERIALS.map(m => ({ value: m, label: m })), r.material ?? '', value => this.setOptional(r, 'material', value), path('material'), localize('plb.f.material', "Material"), true));
			this.removeButton(row, () => {
				ensurePlumbing(document).risers.splice(index, 1);
				this.selection = undefined;
				this.changed(true);
			});
		});
		if (!risers.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('plb.noRisers', "None yet. Add the cold water risers, the soil and waste stacks and the vents from the toolbar: each needs a sleeve or shaft through the floors it passes.")));
		}
	}

	/** The backend's size of a riser without one given, as the input's placeholder. */
	private sizedDiameter(riser: IRiser): string | undefined {
		const sized = this.plumbingState === 'ok' ? this.plumbingReport?.risers.find(r => r.id === riser.id)?.diameter : undefined;
		return sized !== undefined ? formatNumber(sized, 0) : localize('plb.sizedPlaceholder', "sized");
	}

	private setOptional(target: { [key: string]: unknown }, key: string, value: string): void {
		if (value) {
			target[key] = value;
		} else {
			delete target[key];
		}
		this.changed(true);
	}

	private setTankKind(tank: ITank, kind: string): void {
		if (tank.kind === kind) {
			return;
		}
		const wasGround = isGroundTank(tank);
		tank.kind = kind;
		if (isGroundTank(tank)) {
			tank.story = null;
		} else if (wasGround) {
			tank.story = this.story && this.story !== this.context.stories[0]?.id ? this.story : this.context.stories[this.context.stories.length - 1]?.id ?? null;
		}
		if (kind === 'soakWell') {
			tank.diameter ??= 1200;
		}
		const story = tankStory(tank, this.context);
		if (story && this.selection?.kind === 'tank') {
			this.story = story;
			this.updateStoryPicker();
		}
		this.changed(true);
	}

	private renderTankTable(document: IMep): void {
		const tanks = plumbingOf(document)?.tanks ?? [];
		const section = this.section(localize('plb.tanks', "Tanks"), tanks.length, { label: localize('plb.sizeTanksShort', "Size Tanks"), run: () => void this.sizeTanks() });
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('plb.f.kind', "Kind"), width: 170 }, { label: localize('plb.f.storyOn', "On"), width: 100 },
			{ label: F.x.label, unit: M, numeric: true }, { label: F.y.label, unit: M, numeric: true }, { label: P.length.label, unit: MM, numeric: true }, { label: P.width.label, unit: MM, numeric: true },
			{ label: P.wellDiameter.label, unit: MM, numeric: true }, { label: P.waterDepth.label, unit: MM, numeric: true }, { label: localize('plb.f.construction', "Construction"), width: 150 },
			{ label: localize('plb.f.capacity', "Capacity"), unit: localize('plb.unit.m3', "m³"), numeric: true, width: 72 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		tanks.forEach((t, index) => {
			const row = this.selectableRow(body, { kind: 'tank', index });
			const path = (field: string) => `plumbing.tanks.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, t.id, value => this.setField(t, 'id', value), path('id')));
			append(append(row, $('td')), this.selectInput(TANK_KINDS.map(k => ({ value: k, label: tankKindLabel(k) })), t.kind, value => this.setTankKind(t, value), path('kind'), localize('plb.f.kind', "Kind")));
			const storyCell = append(row, $('td'));
			if (isGroundTank(t)) {
				storyCell.classList.add('mep-muted');
				storyCell.textContent = localize('plb.inGround', "in the ground");
			} else {
				append(storyCell, this.selectInput(this.storyOptions(), t.story ?? '', value => {
					t.story = value;
					this.changed(true);
				}, path('story'), localize('plb.f.storyOn', "On")));
			}
			const round = t.kind === 'soakWell';
			for (const [field, usable] of [[F.x, true], [F.y, true], [P.length, !round], [P.width, !round], [P.wellDiameter, round], [P.waterDepth, true]] as const) {
				const td = append(row, $('td'));
				if (usable) {
					append(td, this.textInput(field, t[field.key], value => this.setField(t, field.key, value), path(field.key)));
				} else {
					td.classList.add('mep-muted');
					td.textContent = '—';
				}
			}
			append(append(row, $('td')), this.selectInput(TANK_CONSTRUCTIONS.map(c => ({ value: c, label: constructionLabel(c) })), String(t.construction ?? ''), value => this.setOptional(t, 'construction', value), path('construction'), localize('plb.f.construction', "Construction"), true));
			const capacity = tankCapacity(t);
			const capacityCell = append(row, $('td.number', undefined, capacity === undefined ? '' : formatNumber(capacity, 1)));
			if (t.sized) {
				capacityCell.title = localize('plb.sizedTitle', "Proposed by SAEngine; edit it as needed");
				capacityCell.classList.add('plb-sized');
			}
			this.removeButton(row, () => {
				ensurePlumbing(document).tanks.splice(index, 1);
				this.selection = undefined;
				this.changed(true);
			});
		});
		if (!tanks.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('plb.noTanks', "None yet. Add the overhead tank, the underground reservoir and the septic tank from the toolbar, or let SAEngine size them from the demand.")));
		}
	}

	private renderDrainTable(document: IMep): void {
		const drains = plumbingOf(document)?.roof.drains ?? [];
		const section = this.section(localize('plb.drains', "Roof drains"), drains.length, { label: localize('plb.addDrainShort', "Add Roof Drain"), run: () => this.addDrain() });
		const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('plb.f.storyRoof', "Roof"), width: 110 }, { label: F.x.label, unit: M, numeric: true }, { label: F.y.label, unit: M, numeric: true },
			{ label: P.area.label, unit: P.area.unit, numeric: true, width: 80 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		drains.forEach((d, index) => {
			const row = this.selectableRow(body, { kind: 'drain', index });
			const path = (field: string) => `plumbing.roof.drains.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, d.id, value => this.setField(d, 'id', value), path('id')));
			append(append(row, $('td')), this.selectInput(this.storyOptions(), d.story, value => {
				d.story = value;
				this.changed(true);
			}, path('story'), localize('plb.f.storyRoof', "Roof")));
			for (const field of [F.x, F.y]) {
				append(append(row, $('td')), this.textInput(field, d[field.key], value => this.setField(d, field.key, value), path(field.key)));
			}
			append(append(row, $('td')), this.textInput(P.area, d.area, value => this.setField(d, 'area', value), path('area'), this.catchmentPlaceholder(d)));
			this.removeButton(row, () => {
				ensurePlumbing(document).roof.drains.splice(index, 1);
				this.selection = undefined;
				this.changed(true);
			});
		});
		if (!drains.length) {
			append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('plb.noDrains', "None yet. Add the roof drains on the roof: their leaders come down the building and are sized from the catchments.")));
		}
	}

	private catchmentPlaceholder(drain: IRoofDrain): string {
		const area = this.plumbingState === 'ok' ? this.plumbingReport?.catchments.find(c => c.drain === drain.id)?.area : undefined;
		return area !== undefined ? formatNumber(area, 1) : localize('plb.splitPlaceholder', "split");
	}

	// ───────────────────────────── plumbing: results view ─────────────────────────────

	private renderPlumbingResults(document: IMep): void {
		const view = this.viewElement;
		const report = this.plumbingState === 'ok' ? this.plumbingReport : undefined;
		if (!report) {
			const state = append(view, $('.mep-results-state'));
			const nothing = !hasPlumbing(document);
			const computing = !nothing && (this.plumbingState === 'computing' || this.plumbingState === 'idle');
			const icon = nothing ? Codicon.tools : computing ? ThemeIcon.modify(Codicon.loading, 'spin') : this.plumbingState === 'error' ? Codicon.warning : Codicon.debugDisconnect;
			append(state, $(`span.mep-results-state-icon${ThemeIcon.asCSSSelector(icon)}`));
			append(state, $('.mep-results-state-title', undefined, nothing ? localize('plb.resultsNothing', "No plumbing to check yet")
				: computing ? localize('plb.computing', "Checking the plumbing...")
					: this.plumbingState === 'error' ? localize('plb.reportFailed', "The plumbing could not be checked")
						: localize('mep.backendMissing', "Backend not available")));
			append(state, $('.mep-results-state-text', undefined, nothing
				? localize('plb.resultsNothingText', "Give the fixtures of the storeys and add the risers, tanks and roof drains: the demand, the sizes, the tanks' design and the pressures appear here.")
				: this.plumbingState === 'error' ? (this.plumbingError ?? '')
					: this.plumbingState === 'missing' ? localize('plb.backendMissingText', "The demand and storage, the riser and stack sizes, the leaders, the septic tank, the tanks' design and the pressure at each floor are computed by the SAEngine Python backend; it is not running in this window. The plumbing can still be set up and edited.") : ''));
			if (this.plumbingState === 'missing') {
				this.renderLocalPlumbing(view, document);
			}
			return;
		}
		renderPlumbingReport(view, report, {
			storyName: id => this.storyName(id),
			occupancyName: key => this.occupancies.find(o => o.key === key)?.label ?? key,
			tableHead: (table, columns) => this.tableHead(table, columns),
			row: (body, id) => {
				const plumbing = plumbingOf(document);
				const riser = plumbing?.risers.findIndex(r => r.id === id) ?? -1;
				const tank = plumbing?.tanks.findIndex(t => t.id === id) ?? -1;
				const drain = plumbing?.roof.drains.findIndex(d => d.id === id) ?? -1;
				const selection: MepSelection | undefined = riser >= 0 ? { kind: 'riser', index: riser } : tank >= 0 ? { kind: 'tank', index: tank } : drain >= 0 ? { kind: 'drain', index: drain } : undefined;
				return selection ? this.selectableRow(body, selection) : append(body, $('tr'));
			},
		});
		this.markSelectedRows();
	}

	/** Without the backend: what the file itself says (fixtures, tank capacities). */
	private renderLocalPlumbing(view: HTMLElement, document: IMep): void {
		const plumbing = plumbingOf(document);
		if (!plumbing) {
			return;
		}
		const totals = fixtureTotals(plumbing);
		const section = this.resultSection(view, localize('plb.localTitle', "As set up"), localize('plb.localDetail', "summed from the file; the sizes and checks come from the backend"));
		const table = append(section, $('table.mep-table.mep-result-table'));
		this.tableHead(table, [{ label: localize('plb.f.item', "Item"), width: 220 }, { label: localize('plb.f.value', "Value"), numeric: true, width: 120 }]);
		const body = append(table, $('tbody'));
		const line = (label: string, text: string) => {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, label));
			append(tr, $('td.number', undefined, text));
		};
		line(localize('plb.localPopulation', "Population"), formatNumber(totals.population, 0));
		line(localize('plb.localFixtures', "Fixtures"), formatNumber(FIXTURES.reduce((s, k) => s + totals[k], 0) + totals.other, 0));
		for (const tank of plumbing.tanks) {
			const capacity = tankCapacity(tank);
			line(localize('plb.localTank', "{0} {1}", tankKindLabel(tank.kind), tank.id), capacity === undefined ? '' : localize('plb.m3Value', "{0} m³", formatNumber(capacity, 1)));
		}
	}

	// ───────────────────────────── plumbing: properties ─────────────────────────────

	private renderRiserProperties(panel: HTMLElement, r: IRiser, index: number): void {
		const path = (field: string) => `plumbing.risers.${index}.${field}`;
		appendPropertyHeading(panel, localize('plb.riserHeading', "{0} {1}", systemLabel(r.system), r.id));
		this.fieldRow(panel, F.id, r.id, value => this.setField(r, 'id', value), path('id'));
		this.propertyRow(panel, localize('plb.f.system', "System"), this.selectInput(PLUMBING_SYSTEMS.map(s => ({ value: s, label: `${systemLetters(s)} · ${systemLabel(s)}` })), r.system, value => {
			r.system = value;
			this.changed(true);
		}, path('system'), localize('plb.f.system', "System")));
		this.fieldRow(panel, F.x, r.x, value => this.setField(r, 'x', value), path('x'));
		this.fieldRow(panel, F.y, r.y, value => this.setField(r, 'y', value), path('y'));
		for (const end of ['fromStory', 'toStory'] as const) {
			const label = end === 'fromStory' ? localize('mep.f.fromLong', "Starts at") : localize('mep.f.toLong', "Up to");
			this.propertyRow(panel, label, this.selectInput(this.storyOptions(), r[end], value => {
				r[end] = value;
				this.changed(true);
			}, path(end), label));
		}
		this.propertyRow(panel, localize('plb.f.shaft', "Shaft"), this.selectInput(this.document?.shafts.map(s => ({ value: s.id, label: s.id })) ?? [], r.shaft ?? '', value => this.setOptional(r, 'shaft', value), path('shaft'), localize('plb.f.shaft', "Shaft"), true),
			undefined, localize('plb.f.shaftTitle', "The shaft it runs in; else it needs a sleeve through each floor"));
		appendPropertyHeading(panel, localize('plb.pipeHeading', "Pipe"));
		this.fieldRow(panel, P.diameter, r.diameter, value => this.setField(r, 'diameter', value), path('diameter'), this.sizedDiameter(r));
		this.propertyRow(panel, localize('plb.f.material', "Material"), this.selectInput(PIPE_MATERIALS.map(m => ({ value: m, label: m })), r.material ?? '', value => this.setOptional(r, 'material', value), path('material'), localize('plb.f.material', "Material"), true));
		const served = r.serves?.length ? r.serves.map(s => this.storyName(s)).join(', ') : localize('plb.servesAll', "every storey it passes");
		appendPropertyRow(panel, localize('plb.f.serves', "Serves"), served);
		const result = this.plumbingState === 'ok' ? this.plumbingReport?.risers.find(x => x.id === r.id) : undefined;
		if (result) {
			appendPropertyHeading(panel, localize('plb.sizeCheck', "Size"));
			if (result.load !== undefined) {
				appendPropertyRow(panel, localize('plb.f.load', "Load"), `${formatNumber(result.load, 1)}${result.loadUnit ? ` ${result.loadUnit}` : ''}`);
			}
			if (result.required !== undefined) {
				appendPropertyRow(panel, localize('plb.f.requiredSize', "Required"), localize('mep.mmValue', "{0} mm", formatNumber(result.required, 0)));
			}
			appendPropertyRow(panel, localize('plb.f.status', "Status"), $(`span.plb-pill.band-${result.status}`, undefined, result.status === 'fail' ? localize('plb.status.fail', "fails") : result.status === 'ok' ? localize('plb.status.ok', "ok") : result.status === 'warn' ? localize('plb.status.warn', "check") : '—'));
			if (result.note) {
				appendPropertyNote(panel, result.note);
			}
		}
	}

	private renderTankProperties(panel: HTMLElement, t: ITank, index: number): void {
		const path = (field: string) => `plumbing.tanks.${index}.${field}`;
		appendPropertyHeading(panel, localize('plb.tankHeading', "{0} {1}", tankKindLabel(t.kind), t.id));
		this.fieldRow(panel, F.id, t.id, value => this.setField(t, 'id', value), path('id'));
		this.propertyRow(panel, localize('plb.f.kind', "Kind"), this.selectInput(TANK_KINDS.map(k => ({ value: k, label: tankKindLabel(k) })), t.kind, value => this.setTankKind(t, value), path('kind'), localize('plb.f.kind', "Kind")));
		if (isGroundTank(t)) {
			appendPropertyRow(panel, localize('plb.f.storyOn', "On"), localize('plb.inGroundLong', "in the ground (drawn on {0})", this.storyName(this.context.stories[0]?.id ?? '')));
			this.fieldRow(panel, P.topLevel, t.topLevel, value => this.setField(t, 'topLevel', value), path('topLevel'), '0');
		} else {
			this.propertyRow(panel, localize('plb.f.storyOn', "On"), this.selectInput(this.storyOptions(), t.story ?? '', value => {
				t.story = value;
				this.story = value;
				this.updateStoryPicker();
				this.changed(true);
			}, path('story'), localize('plb.f.storyOn', "On")));
		}
		this.fieldRow(panel, F.x, t.x, value => this.setField(t, 'x', value), path('x'));
		this.fieldRow(panel, F.y, t.y, value => this.setField(t, 'y', value), path('y'));
		appendPropertyHeading(panel, localize('plb.insideHeading', "Inside sizes"));
		if (t.kind === 'soakWell') {
			this.fieldRow(panel, P.wellDiameter, t.diameter, value => this.setField(t, 'diameter', value), path('diameter'));
		} else {
			this.fieldRow(panel, P.length, t.length, value => this.setField(t, 'length', value), path('length'));
			this.fieldRow(panel, P.width, t.width, value => this.setField(t, 'width', value), path('width'));
		}
		this.fieldRow(panel, P.waterDepth, t.waterDepth, value => this.setField(t, 'waterDepth', value), path('waterDepth'));
		this.fieldRow(panel, P.freeboard, t.freeboard, value => this.setField(t, 'freeboard', value), path('freeboard'));
		if (t.kind !== 'soakWell') {
			this.fieldRow(panel, P.compartments, t.compartments, value => this.setField(t, 'compartments', value), path('compartments'), '1');
		}
		const capacity = tankCapacity(t);
		if (capacity !== undefined) {
			appendPropertyRow(panel, localize('plb.f.capacity', "Capacity"), localize('plb.m3Value', "{0} m³", formatNumber(capacity, 2)));
		}
		if (t.sized) {
			appendPropertyNote(panel, localize('plb.sizedNote', "Sized by SAEngine from the demand: edit it as needed."));
		}
		appendPropertyHeading(panel, localize('plb.constructionHeading', "Construction"));
		this.propertyRow(panel, localize('plb.f.construction', "Construction"), this.selectInput(TANK_CONSTRUCTIONS.map(c => ({ value: c, label: constructionLabel(c) })), String(t.construction ?? ''), value => this.setOptional(t, 'construction', value), path('construction'), localize('plb.f.construction', "Construction"), true));
		this.fieldRow(panel, P.walls, t.walls, value => this.setField(t, 'walls', value), path('walls'));
		if (t.kind !== 'soakWell') {
			this.fieldRow(panel, P.base, t.base, value => this.setField(t, 'base', value), path('base'));
			this.fieldRow(panel, P.roof, t.roof, value => this.setField(t, 'roof', value), path('roof'));
		}
		if (t.construction === 'rc' || t.construction === undefined) {
			this.propertyRow(panel, localize('mep.f.concrete', "Concrete"), this.selectInput(this.context.concretes.map(c => ({ value: c.id, label: c.id })), t.material ?? '', value => this.setOptional(t, 'material', value), path('material'), localize('mep.f.concrete', "Concrete"), true));
		}
		const design = this.plumbingState === 'ok' ? this.plumbingReport?.tanks.find(x => x.id === t.id) : undefined;
		if (design) {
			appendPropertyHeading(panel, localize('plb.designHeading', "Design"));
			// The governing checks (all of them are in Results).
			const governing = [...design.checks].sort((a, b) => (b.status === 'fail' ? 1 : 0) - (a.status === 'fail' ? 1 : 0) || (b.utilisation ?? 0) - (a.utilisation ?? 0)).slice(0, 5);
			for (const check of governing) {
				appendPropertyRow(panel, check.name, $(`span.mep-util-value.band-${check.status === 'none' ? 'ok' : check.status}`, undefined, check.utilisation !== undefined ? check.utilisation.toFixed(2) : check.status));
			}
			for (const bar of design.reinforcement) {
				appendPropertyRow(panel, bar.location, bar.bars);
			}
			if (design.loads) {
				appendPropertyNote(panel, design.loads);
			}
		}
	}

	private renderDrainProperties(panel: HTMLElement, d: IRoofDrain, index: number): void {
		const path = (field: string) => `plumbing.roof.drains.${index}.${field}`;
		appendPropertyHeading(panel, localize('plb.drainHeading', "Roof drain {0}", d.id));
		this.fieldRow(panel, F.id, d.id, value => this.setField(d, 'id', value), path('id'));
		this.propertyRow(panel, localize('plb.f.storyRoof', "Roof"), this.selectInput(this.storyOptions(), d.story, value => {
			d.story = value;
			this.story = value;
			this.updateStoryPicker();
			this.changed(true);
		}, path('story'), localize('plb.f.storyRoof', "Roof")));
		this.fieldRow(panel, F.x, d.x, value => this.setField(d, 'x', value), path('x'));
		this.fieldRow(panel, F.y, d.y, value => this.setField(d, 'y', value), path('y'));
		this.fieldRow(panel, P.area, d.area, value => this.setField(d, 'area', value), path('area'), this.catchmentPlaceholder(d));
		const catchment = this.plumbingState === 'ok' ? this.plumbingReport?.catchments.find(x => x.drain === d.id) : undefined;
		if (catchment?.leader !== undefined) {
			appendPropertyRow(panel, localize('plb.f.leader', "Leader"), localize('mep.mmValue', "{0} mm", formatNumber(catchment.leader, 0)));
		}
		if (catchment?.note) {
			appendPropertyNote(panel, catchment.note);
		}
	}

	private renderPlumbingSummaryProperties(panel: HTMLElement, document: IMep): void {
		const plumbing: IPlumbing | undefined = plumbingOf(document);
		const story = this.context.stories.find(s => s.id === this.story);
		if (story) {
			appendPropertyHeading(panel, story.name);
			const row = plumbing?.stories.find(s => s.story === story.id);
			appendPropertyRow(panel, localize('plb.f.occupancy', "Occupancy"), row?.occupancy ? this.occupancies.find(o => o.key === row.occupancy)?.label ?? row.occupancy : '—');
			appendPropertyRow(panel, P.population.label, row?.population !== undefined ? String(row.population) : '—');
			appendPropertyRow(panel, localize('plb.risers', "Risers and stacks"), String(plumbing?.risers.filter(r => riserOnStory(r, this.context, story.id)).length ?? 0));
		}
		appendPropertyHeading(panel, localize('plb.summaryHeading', "Plumbing"));
		appendPropertyRow(panel, localize('plb.f.storeys', "Storeys with fixtures"), String(plumbing?.stories.length ?? 0));
		appendPropertyRow(panel, localize('plb.risers', "Risers and stacks"), String(plumbing?.risers.length ?? 0));
		appendPropertyRow(panel, localize('plb.tanks', "Tanks"), String(plumbing?.tanks.length ?? 0));
		appendPropertyRow(panel, localize('plb.drains', "Roof drains"), String(plumbing?.roof.drains.length ?? 0));
		if (plumbing?.supply.source) {
			appendPropertyRow(panel, localize('plb.f.source', "Source"), sourceLabel(String(plumbing.supply.source)));
		}
		appendPropertyNote(panel, localize('plb.summaryNote', "Select a riser, a tank or a roof drain in the plan to edit it here; the fixtures of the storeys are in Data."));
	}

	private renderPlumbingStatus(document: IMep): void {
		const ok = this.plumbingState === 'ok' ? this.plumbingReport : undefined;
		const parts = [plumbingSummary(document, ok)];
		if (hasPlumbing(document)) {
			if (this.plumbingState === 'missing') {
				parts.push(localize('plb.statusNoBackend', "checks need the backend"));
			} else if (this.plumbingState === 'error') {
				parts.push(localize('plb.statusFailed', "checks could not be computed"));
			}
		}
		const problems = this.problems.filter(p => p.path.startsWith('plumbing.'));
		const errors = problems.filter(p => p.severity === 'error').length;
		const failures = ok ? plumbingFailures(ok) : undefined;
		const failed = !!failures && (failures.items > 0 || failures.floorsLow > 0);
		this.frame.setStatus({
			text: parts.join(' · '),
			severity: errors || failed ? 'error' : problems.length || this.plumbingState === 'error' ? 'warning' : undefined,
			busy: this.plumbingState === 'computing',
			link: problems.length ? {
				label: localize('mep.statusProblems', "{0} problem(s)", problems.length),
				run: () => this.revealProblem(problems[0]),
			} : ok && this.view !== 'results' ? {
				label: localize('mep.statusShowResults', "Results"),
				run: () => this.showView('results'),
			} : undefined,
		});
	}
}
