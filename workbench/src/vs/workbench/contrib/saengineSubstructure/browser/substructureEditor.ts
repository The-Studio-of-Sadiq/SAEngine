/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import './media/substructureEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow, isHTMLInputElement } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Action, IAction, Separator, toAction } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { DEFAULT_EDITOR_ASSOCIATION, IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DEVELOPER_MODE_SETTING } from '../../../services/saengineProject/common/developerMode.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { appendPlannedFeatureChip } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { formatField, formatNumber, IFieldSpec, parseField } from '../../saengineSoil/browser/soilDocument.js';
import {
	addPiles, applyPileLayout, applyProposal, capPileType, connectGradeBeams, DEFAULT_SPACING_FACTOR, deletePiles, formatSpacings, foundationOf, gridLines, IPile, intersectionsInBox, makePileCap, MIN_SPACING_FACTOR, movePiles, newPileGrid, parseSpacings, PILE_GROUPS, pileAt, pileCaps, pilesInBox, placePileGroup, refitCap, setCapPileType, snapPoint, tied, formatPileBars, formatPileTies, minimumMesh, parsePileBars, parsePileTies, carriedAlready, checkStateText, checkSubstructure, documentSignatures, defaultFoundingLevel, EMPTY_CONTEXT, formatMesh, formatUtilisation, foundationCenter, foundationOutlines, foundationSize, foundationTypeLabel, FOUNDATION_TYPES, FoundationType, governingCheck, IColumnBase, IFoundation, IFoundationResult, IPileType, ISiteContext, ISiteTexts,
	ISizingProposal, ISubstructure, ISubstructureMigration, ISubstructureProblem, ISubstructureReport, ISubstructureRequest, IRetainingWall, ITieBeam, importFoundations, maxPressure, MESH_KEYS, MeshKey, newFooting, newPileCap, newPileType, newRaft, newRetainingWall, newTieBeam, parseIdList, parseMesh, parseSubstructure, PILE_FACTOR_OF_SAFETY, pileFactorsUsed, PILE_KINDS, PILE_LAYOUTS,
	errorSummary, pileFixityLabel, PILE_FIXITIES, FOOTING_SECTIONS, FootingSection, footingSectionLabel, ISubstructureDesign, newGroundSlab, pileKindLabel, Point, proposalFor, RAFT_MESH_SIZE, readSiteContext, readSizingProposal, readSubstructureReport, serializeSubstructure, SUBSTRUCTURE_ENSURE_COMMAND, SUBSTRUCTURE_MIGRATE_COMMAND, SUBSTRUCTURE_REPORT_COMMAND, SUBSTRUCTURE_REPORT_FILE, SUBSTRUCTURE_SIZE_COMMAND, SUBSTRUCTURE_SUMMARY_FILE, substructureCheckState, substructureSummary, substructureSummaryFile, foundationSignature, ISubstructureCheckState, tieBeamSignature, uncoveredBases, uncoveredColumns, utilisationBand,
} from './substructureDocument.js';
import { SubstructureEditorInput } from './substructureEditorInput.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { HEAT_STEPS, IPlanDrawing, renderPlan, renderRaftHeatMap } from './substructurePlan.js';

type View = 'plan' | 'data' | 'results';

/** What a click on the plan does: select (and drag piles), place piles, or draw grade beams. */
type Tool = 'select' | 'pile' | 'beam';

/** The snap reach on the plan [px]. */
const SNAP_PX = 14;
/** How far the pointer moves before a press is a drag [px]. */
const DRAG_PX = 4;

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: 'plan', label: localize('sub.viewPlan', "Plan"), icon: Codicon.symbolStructure },
	{ view: 'data', label: localize('sub.viewData', "Data"), icon: Codicon.table },
	{ view: 'results', label: localize('sub.viewResults', "Results"), icon: Codicon.graphLine },
];

/** The backend's check of footings overlapping in plan (report.mark_overlaps). */
const CLEARANCE_CHECK = 'Clear of the other footings';

/** Notes as sentences: each starts with a capital and ends with a full stop (N-U12). */
function sentences(notes: readonly string[]): string {
	return notes.map(n => n.trim()).filter(Boolean).map(n => {
		const text = n.charAt(0).toUpperCase() + n.slice(1);
		return /[.!?)]$/.test(text) ? text : `${text}.`;
	}).join(' ');
}

/** Restart Engine (saengineFem's runAll): stops the Python backend; the next request starts a new one. */
const RESTART_ENGINE_COMMAND = 'saengine.restartEngine';

/** The state of the design report: not asked yet, being computed, computed, or no backend / failed. */
type ReportState = 'idle' | 'computing' | 'ok' | 'missing' | 'error';

/** The parts the plan is drawn against, by the key of {@link ISiteTexts}. */
const SITE_PARTS: readonly (readonly [keyof ISiteTexts, string])[] = [
	['bim', 'bim'], ['objects', 'objects'], ['floorPlan', 'floorPlan'], ['settings', 'settings'], ['soil', 'soil'], ['materials', 'materials'],
];

/** Planned pile features shown as chips under the pile types (registered in the contribution). */
const PLANNED_PILE_FEATURES = ['substructure.lateralPileBroms', 'substructure.lateralPilePy', 'substructure.piledRaft', 'substructure.pileGroupInteraction'];

const MM = localize('sub.unit.mm', "mm");
const M = localize('sub.unit.m', "m");

const F = {
	id: { key: 'id', label: localize('sub.f.id', "ID"), kind: 'text', required: true, width: 64 },
	x: { key: 'x', label: 'X', unit: M, kind: 'length', title: localize('sub.f.xTitle', "Plan position of the centre; the columns' centroid when empty") },
	y: { key: 'y', label: 'Y', unit: M, kind: 'length', title: localize('sub.f.yTitle', "Plan position of the centre; the columns' centroid when empty") },
	rotation: { key: 'rotation', label: localize('sub.f.rotation', "Rotation"), unit: '°', kind: 'number' },
	length: { key: 'length', label: localize('sub.f.length', "Length"), unit: MM, kind: 'number', min: 1, title: localize('sub.f.lengthTitle', "Plan dimension along the local x axis"), width: 72 },
	width: { key: 'width', label: localize('sub.f.width', "Width"), unit: MM, kind: 'number', min: 1, title: localize('sub.f.widthTitle', "Plan dimension along the local y axis"), width: 72 },
	thickness: { key: 'thickness', label: localize('sub.f.thickness', "Thickness"), unit: MM, kind: 'number', min: 1, width: 72 },
	foundingLevel: { key: 'foundingLevel', label: localize('sub.f.foundingLevel', "Founding level"), unit: M, kind: 'length', title: localize('sub.f.foundingTitle', "Underside of the foundation on the project datum; ground level − 1.5 m when empty"), width: 84 },
	cover: { key: 'cover', label: localize('sub.f.cover', "Cover"), unit: MM, kind: 'number', min: 20, max: 200 },
	note: { key: 'note', label: localize('sub.f.note', "Note"), kind: 'text' },
	diameter: { key: 'diameter', label: localize('sub.f.diameter', "Diameter"), unit: MM, kind: 'number', min: 1, required: true, width: 80, title: localize('sub.f.diameterTitle', "Bored piles: the diameter; driven precast piles: the side of the square") },
	pileLength: { key: 'length', label: localize('sub.f.pileLength', "Length"), unit: M, kind: 'length', min: 0.001, required: true, width: 72 },
	fixityDepth: { key: 'fixityDepth', label: localize('sub.f.fixityDepth', "Depth to fixity"), unit: M, kind: 'length', min: 0.001, title: localize('sub.f.fixityDepthTitle', "Below the pile head, where the pile acts as fixed against the lateral load, from the geotechnical report. Empty: the piles are designed for axial force only."), width: 80 },
	level: { key: 'level', label: localize('sub.f.level', "Level"), unit: M, kind: 'length', title: localize('sub.f.levelTitle', "Top of the tie beam; the foundations' top when empty"), width: 72 },
	pileCompression: { key: 'pileCompression', label: localize('sub.f.fsCompression', "FS pile compression"), kind: 'number', min: 1, max: 10, title: localize('sub.f.fsCompressionTitle', "BNBC 2020 Part 6 Table 6.3.10a: 2.5 for a permanent structure under normal control. Sec 3.10.1.18 (bored piles: Sec 3.10.4.10) asks at least 3.0 unless the design rests on a load test at the site (then 2.0): the design raises a smaller value.") },
	pileUplift: { key: 'pileUplift', label: localize('sub.f.fsUplift', "FS pile uplift"), kind: 'number', min: 1, max: 10, title: localize('sub.f.fsTitle', "BNBC 2020 Part 6 Table 6.3.10a: 2.5 for a permanent structure under normal control") },
	bearing: { key: 'bearing', label: localize('sub.f.fsBearing', "FS bearing"), kind: 'number', min: 1, max: 10, title: localize('sub.f.fsBearingTitle', "Factor of safety on the bearing capacity of footings and rafts; the soil report's when empty") },
	raftMeshSize: { key: 'raftMeshSize', label: localize('sub.f.raftMesh', "Raft mesh size"), unit: MM, kind: 'number', min: 100, max: 5000 },
	edgeThickness: { key: 'edgeThickness', label: localize('sub.f.edgeThickness', "Edge thickness"), unit: MM, kind: 'number', min: 1, title: localize('sub.f.edgeThicknessTitle', "Sloped: the thickness at the edges; stepped: the lower step's thickness") },
	topLength: { key: 'topLength', label: localize('sub.f.topLength', "Top length"), unit: MM, kind: 'number', min: 1, title: localize('sub.f.topLengthTitle', "Along the local x: the flat top round the column (sloped) or the upper step (stepped)") },
	topWidth: { key: 'topWidth', label: localize('sub.f.topWidth', "Top width"), unit: MM, kind: 'number', min: 1, title: localize('sub.f.topWidthTitle', "Along the local y: the flat top or the upper step") },
	slabThickness: { key: 'thickness', label: localize('sub.f.slabThickness', "Thickness"), unit: MM, kind: 'number', min: 50, required: true, width: 72 },
	uniformLoad: { key: 'uniformLoad', label: localize('sub.f.uniformLoad', "Floor load"), unit: localize('sub.unit.kpa', "kPa"), kind: 'number', min: 0, width: 72 },
	pointLoad: { key: 'pointLoad', label: localize('sub.f.pointLoad', "Post load"), unit: localize('sub.unit.kn', "kN"), kind: 'number', min: 0, title: localize('sub.f.pointLoadTitle', "The largest post, rack-leg or wheel load (service)"), width: 72 },
	contactSide: { key: 'contactSide', label: localize('sub.f.contactSide', "Contact side"), unit: MM, kind: 'number', min: 10, title: localize('sub.f.contactSideTitle', "Side of the square base plate or tyre print"), width: 72 },
	subgradeModulus: { key: 'subgradeModulus', label: localize('sub.f.subgradeK', "k"), unit: localize('sub.unit.knm3', "kN/m³"), kind: 'number', min: 1, title: localize('sub.f.subgradeKTitle', "Modulus of subgrade reaction of the compacted sub-base; the design's subgrade modulus when empty"), width: 80 },
	springs: { key: 'springs', label: localize('sub.f.springs', "Subgrade modulus ks"), unit: localize('sub.unit.knm3', "kN/m³"), kind: 'number', min: 0.001, title: localize('sub.f.springsTitle', "The raft's springs; the soil report's ks when empty") },
	pileX: { key: 'x', label: 'X', unit: M, kind: 'length', required: true, title: localize('sub.f.pileXTitle', "Plan position of the pile's centre") },
	pileY: { key: 'y', label: 'Y', unit: M, kind: 'length', required: true, title: localize('sub.f.pileYTitle', "Plan position of the pile's centre") },
	originX: { key: 'originX', label: localize('sub.f.originX', "Origin X"), unit: M, kind: 'length', title: localize('sub.f.originTitle', "Plan position of the pile grid's origin (its first lines' crossing)") },
	originY: { key: 'originY', label: localize('sub.f.originY', "Origin Y"), unit: M, kind: 'length', title: localize('sub.f.originTitle', "Plan position of the pile grid's origin (its first lines' crossing)") },
	spacingFactor: { key: 'spacingFactor', label: localize('sub.f.spacingFactor', "Spacing k"), unit: '× D', kind: 'number', min: MIN_SPACING_FACTOR, max: 10, title: localize('sub.f.spacingFactorTitle', "Pile group spacing s = k · D centre to centre; BNBC 2020 Part 6 Secs 3.10.1.19 and 3.10.1.30: at least 2.5 D and 750 mm, 3 D for friction piles") },
} satisfies { [key: string]: IFieldSpec };

/**
 * The substructure (`09 Substructure/substructure.json`) on the shared editor frame. The Plan
 * view draws the base level of the building (grid, column bases, boreholes) with the
 * foundations to scale, their piles and the tie beams; columns and foundations are picked there
 * and edited in the properties panel. The Data view lists the foundations, pile types and tie
 * beams as tables, and the Results view shows the backend's design report: the governing check
 * and utilisation of each foundation, the pile capacities and loads, and a raft's contact
 * pressure and settlement. The JSON text model stays the document: every edit is one undoable
 * text edit, so save, dirty state and undo come from the text file.
 */
export class SubstructureEditor extends EditorPane {

	static readonly ID = SubstructureEditorInput.EDITOR_ID;

	private frame!: EditorFrame;
	private viewElement!: HTMLElement;
	private readonly viewButtons = new Map<View, HTMLButtonElement>();

	private model: ITextModel | undefined;
	private document: ISubstructure | undefined;
	private parseError: string | undefined;
	private problems: ISubstructureProblem[] = [];
	private context: ISiteContext = EMPTY_CONTEXT;
	private applying = false;
	private view: View = 'plan';

	private selectedFoundations: number[] = [];
	private selectedColumns = new Set<string>();
	private selectedTieBeam: number | undefined;
	private selectedPiles = new Set<string>();
	/** The pile grid is shown in the properties. */
	private gridSelected = false;

	private tool: Tool = 'select';
	/** The pile type the pile tools place (the first one when not chosen). */
	private placeType: string | undefined;
	private groupCount = 4;
	private spacingFactor = DEFAULT_SPACING_FACTOR;
	/** The first end of a grade beam being drawn: a foundation id. */
	private beamStart: string | undefined;
	private drawing: IPlanDrawing | undefined;
	private overlay: SVGGElement | undefined;
	private press: { readonly x: number; readonly y: number; readonly mode: 'move' | 'box' | 'place' | 'click'; readonly pile?: string; moved: boolean; readonly add: boolean; readonly target: Element | null } | undefined;

	private report: ISubstructureReport | undefined;
	private reportState: ReportState = 'idle';
	private reportError: string | undefined;
	private reportVersion = 0;
	/**
	 * The signatures of the foundations and tie beams of the saved file the report was checked
	 * for (see documentSignatures): a result whose foundation has changed since is stale, never
	 * shown as the new one's checks.
	 */
	private checkedFor: Map<string, string> | undefined;
	/** Counts the changes of the other parts and the analysis results; the report records the one it read. */
	private siteVersion = 0;
	private checkedSiteVersion = 0;
	private proposal: ISizingProposal | undefined;
	private raftQuantity: 'pressure' | 'settlement' = 'pressure';
	private readonly busy = new Set<string>();
	private actionsKey: string | undefined;
	private lastSize = '';

	private readonly inputs = new Map<string, HTMLElement>();
	/** The rows of the foundations in the view's tables, by foundation index. */
	private readonly foundationRows = new Map<HTMLElement, number>();
	private readonly propertyInputs = new Map<string, HTMLElement>();
	private propertiesFor: { document: ISubstructure | undefined; selection: string } | undefined;
	private renderingProperties = false;

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly siteDisposables = this._register(new DisposableStore());
	private readonly viewDisposables = this._register(new DisposableStore());
	private readonly propertiesDisposables = this._register(new DisposableStore());
	private readonly siteModels = new Map<keyof ISiteTexts, ITextModel>();
	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 300));
	private readonly reportScheduler = this._register(new RunOnceScheduler(() => void this.computeReport(), 1200));
	private readonly siteScheduler = this._register(new RunOnceScheduler(() => this.readSite(), 300));
	private readonly layoutScheduler = this._register(new RunOnceScheduler(() => this.onMainResized(), 50));

	private readonly addFootingAction = this._register(new Action('saengine.substructure.editor.addFooting', localize('sub.addFooting', "Add Footing under the Selected Columns"), ThemeIcon.asClassName(Codicon.add), true, async () => this.addFootings()));
	private readonly addPileCapAction = this._register(new Action('saengine.substructure.editor.addPileCap', localize('sub.addPileCap', "Add Pile Cap under the Selected Columns"), ThemeIcon.asClassName(Codicon.circleLargeOutline), true, async () => this.addPileCaps()));
	private readonly addRaftAction = this._register(new Action('saengine.substructure.editor.addRaft', localize('sub.addRaft', "Add Raft under the Selected Columns"), ThemeIcon.asClassName(Codicon.primitiveSquare), true, async () => this.addRaft()));
	private readonly addTieAction = this._register(new Action('saengine.substructure.editor.addTieBeam', localize('sub.addTie', "Add Tie Beam between the Two Selected Foundations"), ThemeIcon.asClassName(Codicon.dash), true, async () => this.addTieBeam()));
	private readonly sizeAction = this._register(new Action('saengine.substructure.editor.size', localize('sub.size', "Size Footings"), ThemeIcon.asClassName(Codicon.wand), true, () => this.sizeAll()));
	private readonly migrateAction = this._register(new Action('saengine.substructure.editor.migrate', localize('sub.migrate', "Import Footings from the Building Model"), ThemeIcon.asClassName(Codicon.cloudDownload), true, () => this.migrate()));
	private readonly deleteAction = this._register(new Action('saengine.substructure.editor.delete', localize('sub.delete', "Delete"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteSelection()));
	private readonly addStripAction = this._register(new Action('saengine.substructure.editor.addStrip', localize('sub.addStrip', "Add Strip Footing along the Selected Columns"), undefined, true, async () => this.addStrip()));
	private readonly addPileTypeAction = this._register(new Action('saengine.substructure.editor.addPileType', localize('sub.addPileType', "Add Pile Type"), undefined, true, async () => this.addPileType()));
	private readonly selectAllAction = this._register(new Action('saengine.substructure.editor.selectColumns', localize('sub.selectColumns', "Select Columns without a Foundation"), undefined, true, async () => this.selectUncovered()));
	private readonly recomputeAction = this._register(new Action('saengine.substructure.editor.recompute', localize('sub.recompute', "Check the Foundations Again"), undefined, true, () => this.computeReport()));
	private readonly saveAndCheckAction = this._register(new Action('saengine.substructure.editor.saveAndCheck', localize('sub.saveAndCheck', "Save and Check"), ThemeIcon.asClassName(Codicon.checkAll), true, () => this.saveAndCheck()));
	private readonly openTextAction = this._register(new Action('saengine.substructure.editor.openText', localize('sub.openText', "Open as Text"), undefined, true, () => this.openAsText()));
	private readonly pileGridAction = this._register(new Action('saengine.substructure.editor.pileGrid', localize('sub.pileGrid', "Pile Grid"), ThemeIcon.asClassName(Codicon.symbolNumeric), true, async () => this.editPileGrid()));
	private readonly placePilesAction = this._register(new Action('saengine.substructure.editor.placePiles', localize('sub.placePiles', "Place Piles (click a grid crossing or a point, drag a box over crossings)"), ThemeIcon.asClassName(Codicon.circleFilled), true, async () => this.setTool(this.tool === 'pile' ? 'select' : 'pile')));
	private readonly pileGroupAction = this._register(new Action('saengine.substructure.editor.pileGroup', localize('sub.pileGroup', "Place a Pile Group under the Selected Columns"), ThemeIcon.asClassName(Codicon.location), true, async () => this.placeGroups()));
	private readonly makeCapAction = this._register(new Action('saengine.substructure.editor.makeCap', localize('sub.makeCap', "Make Pile Cap from the Selected Piles"), ThemeIcon.asClassName(Codicon.package), false, async () => this.makeCap()));
	private readonly gradeBeamAction = this._register(new Action('saengine.substructure.editor.gradeBeam', localize('sub.gradeBeamTool', "Draw Grade Beams (click two caps or columns)"), ThemeIcon.asClassName(Codicon.arrowBoth), true, async () => this.setTool(this.tool === 'beam' ? 'select' : 'beam')));
	private readonly connectAction = this._register(new Action('saengine.substructure.editor.connectBeams', localize('sub.connectBeams', "Connect Grade Beams along the Grid Lines"), undefined, true, async () => this.connectBeams()));

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
		@IDialogService private readonly dialogService: IDialogService,
	) {
		super(SubstructureEditor.ID, group, telemetryService, themeService, storageService);
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.renderActions();
			}
		}));
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			// The backend registers its commands when it starts: check as soon as it can.
			if (id === SUBSTRUCTURE_REPORT_COMMAND && this.reportState === 'missing') {
				this.reportScheduler.schedule(0);
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: SubstructureEditor.ID,
			ariaLabel: localize('sub.toolbar', "Substructure"),
			properties: { title: localize('sub.properties', "Properties"), defaultWidth: 300 },
		}));
		frame.element.classList.add('saengine-substructure-editor');
		frame.setTitle(localize('sub.title', "Substructure"));
		frame.setHelp(localize('sub.help', "The foundations of the building: isolated, combined and strip footings, pile caps on piles, and rafts, with the tie beams between them. Pick columns in the plan and add a foundation under them, or let SAEngine size all of them from the analysis reactions and the soil report. The Results view checks them: bearing pressure, punching and one-way shear, flexure, pile loads against the pile capacity, and a raft's contact pressure and settlement."));

		const views = append(frame.controlsSlot, $('.sa-segmented', { role: 'tablist', 'aria-label': localize('sub.viewsAria', "Substructure view") }));
		for (const { view, label, icon } of VIEWS) {
			const button = append(views, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }));
			append(button, $(ThemeIcon.asCSSSelector(icon)));
			append(button, $('span', undefined, label));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.showView(view)));
			this.viewButtons.set(view, button);
		}
		this.viewElement = append(frame.main, $('.sub-view', { tabIndex: 0 }));
		this._register(addDisposableListener(this.viewElement, EventType.KEY_DOWN, e => this.onKey(e)));
		this._register(frame.onDidLayoutMain(() => this.layoutScheduler.schedule()));
		this.updateViewButtons();
	}

	override async setInput(input: SubstructureEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.siteDisposables.clear();
		this.siteModels.clear();
		this.model = undefined;
		this.report = undefined;
		this.checkedFor = undefined;
		this.reportState = 'idle';
		this.proposal = undefined;
		this.clearSelection();
		await this.ensureMigrated(input);
		if (token.isCancellationRequested || this.input !== input) {
			return;
		}
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
		// New analysis results (a run, Run All) change every foundation's loads: check again.
		const results = joinPath(dirname(dirname(input.resource)), '08 FEM', 'model.results');
		this.inputDisposables.add(this.fileService.onDidFilesChange(e => {
			if (e.affects(results) && this.document?.foundations.length) {
				this.siteVersion++;
				this.renderReportDependent();
				this.reportScheduler.schedule();
			}
		}));
		this.inputDisposables.add(input.onDidChangeDirty(() => {
			// The backend checks the saved file: check again once the edits are saved.
			if (!input.isDirty() && this.document?.foundations.length) {
				this.reportScheduler.schedule(0);
			}
			this.renderStatus();
		}));
		await this.openSite(input);
		if (this.input !== input) {
			return;
		}
		await this.restoreReport(input);
		if (this.input !== input) {
			return;
		}
		this.load();
	}

	/**
	 * The last checks of the saved file ({@link SUBSTRUCTURE_REPORT_FILE}), shown at once while
	 * they are computed again: the plan is coloured as soon as it opens (N-U8). Not when the
	 * analysis ran since (its results are newer); a foundation edited since shows as changed.
	 */
	private async restoreReport(input: SubstructureEditorInput): Promise<void> {
		const folder = dirname(input.resource);
		try {
			const file = joinPath(folder, SUBSTRUCTURE_REPORT_FILE);
			const [stat, content] = await Promise.all([this.fileService.stat(file), this.fileService.readFile(file)]);
			const manifest = joinPath(dirname(folder), '08 FEM', 'model.results', 'manifest.json');
			const results = await this.fileService.stat(manifest).catch(() => undefined);
			if (!results || results.mtime > stat.mtime || this.input !== input || this.report) {
				return;
			}
			const value: unknown = JSON.parse(content.value.toString());
			const raw = typeof value === 'object' && value !== null ? value as { report?: unknown; checkedFor?: unknown } : {};
			const report = readSubstructureReport(raw.report);
			if (!report || typeof raw.checkedFor !== 'object' || raw.checkedFor === null) {
				return;
			}
			this.report = report;
			this.checkedFor = new Map(Object.entries(raw.checkedFor).filter((e): e is [string, string] => typeof e[1] === 'string'));
			this.checkedSiteVersion = this.siteVersion;
			this.reportState = 'ok';
		} catch {
			// None yet, or unreadable: the plan waits for the checks.
		}
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

	/** The substructure's file. */
	get resource(): URI | undefined {
		return (this.input as SubstructureEditorInput | undefined)?.resource;
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

	// ───────────────────────────── the project around it ─────────────────────────────

	/**
	 * A project from before Part 9: the first time its substructure is opened (still the
	 * placeholder), the footings drawn in the building model are written into it, so nothing
	 * designed in Part 8 is lost. Nothing happens once the file has foundations of its own.
	 */
	private async ensureMigrated(input: SubstructureEditorInput): Promise<void> {
		if (input.isDirty() || !CommandsRegistry.getCommand(SUBSTRUCTURE_ENSURE_COMMAND)) {
			return;
		}
		const request: ISubstructureRequest = { projectRoot: dirname(dirname(input.resource)).fsPath };
		try {
			const result = await this.commandService.executeCommand<ISubstructureMigration>(SUBSTRUCTURE_ENSURE_COMMAND, request);
			if (result?.problems?.length) {
				this.notificationService.warn(result.problems.join(' '));
			} else if (result?.migrated && result.count) {
				this.notificationService.info(result.count === 1
					? localize('sub.movedOne', "The footing drawn in the building model is now in the substructure, where foundations are placed and designed.")
					: localize('sub.moved', "The {0} footings drawn in the building model are now in the substructure, where foundations are placed and designed.", result.count));
			}
		} catch {
			// The backend is not available: the editor opens the file as it is.
		}
	}

	/** Opens the parts the plan is drawn against and follows their edits. */
	private async openSite(input: SubstructureEditorInput): Promise<void> {
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

	private readSite(render = true): void {
		const texts: { -readonly [K in keyof ISiteTexts]?: string } = {};
		for (const [key, model] of this.siteModels) {
			if (!model.isDisposed()) {
				texts[key] = model.getValue();
			}
		}
		this.context = readSiteContext(texts);
		if (render) {
			this.siteVersion++;
		}
		if (render && this.document) {
			this.problems = checkSubstructure(this.document, this.context);
			this.render();
			this.reportScheduler.schedule();
		}
	}

	// ───────────────────────────── document ─────────────────────────────

	private load(): void {
		if (!this.model) {
			return;
		}
		const parsed = parseSubstructure(this.model.getValue(), this.context.columns);
		if (parsed.kind === 'error') {
			this.document = undefined;
			this.parseError = parsed.message;
		} else {
			this.document = parsed.document;
			this.parseError = undefined;
			const count = this.document.foundations.length;
			this.selectedFoundations = this.selectedFoundations.filter(i => i < count);
			const piles = new Set(this.document.piles.map(p => p.id));
			this.selectedPiles = new Set([...this.selectedPiles].filter(id => piles.has(id)));
			if (this.selectedTieBeam !== undefined && this.selectedTieBeam >= this.document.tieBeams.length) {
				this.selectedTieBeam = undefined;
			}
		}
		this.problems = this.document ? checkSubstructure(this.document, this.context) : [];
		this.render();
		this.reportScheduler.schedule(this.reportState === 'idle' ? 0 : undefined);
	}

	/** Writes the document to the text model as one undoable edit. */
	private commit(): void {
		this.commitScheduler.cancel();
		const model = this.model;
		if (!model || !this.document || model.isDisposed()) {
			return;
		}
		const text = serializeSubstructure(this.document);
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
		this.problems = checkSubstructure(this.document, this.context);
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

	private clearSelection(): void {
		this.selectedFoundations = [];
		this.selectedColumns = new Set();
		this.selectedTieBeam = undefined;
		this.selectedPiles = new Set();
		this.gridSelected = false;
	}

	private get selectionKey(): string {
		return `${this.selectedFoundations.join()}|${[...this.selectedColumns].join()}|${this.selectedTieBeam ?? ''}|${[...this.selectedPiles].join()}|${this.gridSelected}|${this.tool}`;
	}

	private get foundation(): IFoundation | undefined {
		return this.selectedFoundations.length === 1 ? this.document?.foundations[this.selectedFoundations[0]] : undefined;
	}

	/** The columns picked, in the order of the building model. */
	private get pickedColumns(): IColumnBase[] {
		return this.context.columns.filter(c => this.selectedColumns.has(c.id));
	}

	private selectFoundation(index: number, add: boolean): void {
		this.flush();
		if (add) {
			const at = this.selectedFoundations.indexOf(index);
			if (at >= 0) {
				this.selectedFoundations.splice(at, 1);
			} else {
				this.selectedFoundations.push(index);
			}
		} else {
			this.selectedFoundations = [index];
		}
		this.selectedColumns = new Set();
		this.selectedTieBeam = undefined;
		this.selectedPiles = new Set();
		this.gridSelected = false;
		this.renderSelection();
	}

	private selectColumn(id: string, add: boolean): void {
		this.flush();
		if (add) {
			if (!this.selectedColumns.delete(id)) {
				this.selectedColumns.add(id);
			}
		} else {
			this.selectedColumns = new Set([id]);
			this.selectedPiles = new Set();
		}
		this.selectedFoundations = [];
		this.selectedTieBeam = undefined;
		this.gridSelected = false;
		this.renderSelection();
	}

	/** Selects a pile; `add` toggles it in the selection (the columns picked stay, for Make Pile Cap). */
	private selectPile(id: string, add: boolean): void {
		this.flush();
		if (add) {
			if (!this.selectedPiles.delete(id)) {
				this.selectedPiles.add(id);
			}
		} else {
			this.selectedPiles = new Set([id]);
			this.selectedColumns = new Set();
		}
		this.selectedFoundations = [];
		this.selectedTieBeam = undefined;
		this.gridSelected = false;
		this.renderSelection();
	}

	private selectTieBeam(index: number): void {
		this.flush();
		this.clearSelection();
		this.selectedTieBeam = index;
		this.renderSelection();
	}

	private selectUncovered(): void {
		if (!this.document) {
			return;
		}
		this.clearSelection();
		this.selectedColumns = new Set(uncoveredColumns(this.document, this.context).map(c => c.id));
		this.view = 'plan';
		this.render();
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

	/** The plan point [mm] under a pointer event. */
	private planPoint(e: MouseEvent): Point | undefined {
		const drawing = this.drawing;
		if (!drawing) {
			return undefined;
		}
		const box = drawing.svg.getBoundingClientRect();
		return drawing.toPlan(e.clientX - box.left, e.clientY - box.top);
	}

	private onPlanDown(e: PointerEvent): void {
		if (e.button !== 0 || !this.drawing) {
			return;
		}
		// A press in the drawing selects; the view takes the keys (Delete, Escape, arrows) from then on.
		this.viewElement.focus({ preventScroll: true });
		const target = e.target as Element | null;
		const add = e.shiftKey || e.ctrlKey || e.metaKey;
		const pile = target?.closest('[data-pile]')?.getAttribute('data-pile') ?? undefined;
		const empty = !target?.closest('[data-pile], [data-column], [data-foundation], [data-tie]');
		let mode: 'move' | 'box' | 'place' | 'click' = 'click';
		if (this.tool === 'pile') {
			mode = 'place';
		} else if (this.tool === 'select' && pile) {
			mode = 'move';
			if (!this.selectedPiles.has(pile) || add) {
				this.selectPile(pile, add);
			}
		} else if (this.tool === 'select' && empty) {
			mode = 'box';
		}
		// The element pressed: with the pointer captured, the release's target is the canvas.
		this.press = { x: e.clientX, y: e.clientY, mode, pile, moved: false, add, target };
		(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
		e.preventDefault();
	}

	private onPlanMove(e: PointerEvent): void {
		const press = this.press;
		const drawing = this.drawing;
		const point = this.planPoint(e);
		if (!drawing || !point || !this.document) {
			return;
		}
		const overlay = this.planOverlay();
		overlay.replaceChildren();
		if (press && !press.moved && Math.hypot(e.clientX - press.x, e.clientY - press.y) > DRAG_PX) {
			press.moved = true;
		}
		const box = drawing.svg.getBoundingClientRect();
		if (press?.moved && (press.mode === 'box' || press.mode === 'place')) {
			const [x0, y0] = [press.x - box.left, press.y - box.top];
			const [x1, y1] = [e.clientX - box.left, e.clientY - box.top];
			svg(overlay, 'rect', { x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0), class: 'sub-box' });
			if (press.mode === 'place') {
				const start = drawing.toPlan(x0, y0);
				for (const p of intersectionsInBox(this.document.pileGrid, start, point)) {
					const [sx, sy] = drawing.toScreen(p);
					svg(overlay, 'circle', { cx: sx, cy: sy, r: 5, class: 'sub-snap' });
				}
			}
			return;
		}
		if (press?.moved && press.mode === 'move' && press.pile) {
			const delta = this.moveDelta(press, e);
			if (delta) {
				// Where the selected piles go: outlines in the overlay, at the snapped move.
				for (const pile of this.document.piles.filter(p => this.selectedPiles.has(p.id))) {
					const [sx, sy] = drawing.toScreen([pile.position[0] + delta[0], pile.position[1] + delta[1]]);
					const diameter = this.document.pileTypes.find(t => t.id === pile.type)?.diameter ?? 500;
					svg(overlay, 'circle', { cx: sx, cy: sy, r: Math.max(3, diameter / 2 / drawing.mmPerPx), class: 'sub-snap' });
				}
			}
			return;
		}
		if (this.tool === 'pile' && !press) {
			const snap = snapPoint(point, this.document, this.context, SNAP_PX * drawing.mmPerPx, false);
			const [sx, sy] = drawing.toScreen(snap.point);
			svg(overlay, 'circle', { cx: sx, cy: sy, r: 7, class: 'sub-snap' });
			svg(overlay, 'text', { x: sx + 10, y: sy - 8, class: 'sub-snap-label' }, snap.label ?? `${formatNumber(snap.point[0] / 1000, 2)}, ${formatNumber(snap.point[1] / 1000, 2)}`);
		}
	}

	/** The move [mm] of the pile dragged: its new position snapped (a grid crossing, a column, 50 mm), less its old. */
	private moveDelta(press: { readonly x: number; readonly y: number; readonly pile?: string }, e: MouseEvent): Point | undefined {
		const drawing = this.drawing;
		const pile = this.document?.piles.find(p => p.id === press.pile);
		if (!drawing || !pile || !this.document) {
			return undefined;
		}
		const raw: Point = [pile.position[0] + (e.clientX - press.x) * drawing.mmPerPx, pile.position[1] - (e.clientY - press.y) * drawing.mmPerPx];
		const snap = snapPoint(raw, this.document, this.context, SNAP_PX * drawing.mmPerPx, false);
		return [snap.point[0] - pile.position[0], snap.point[1] - pile.position[1]];
	}

	private onPlanUp(e: PointerEvent): void {
		const press = this.press;
		this.press = undefined;
		const document = this.document;
		const drawing = this.drawing;
		const point = this.planPoint(e);
		if (!press || !document || !drawing || !point) {
			return;
		}
		if (press.mode === 'move') {
			const delta = press.moved ? this.moveDelta(press, e) : undefined;
			if (delta && (delta[0] || delta[1])) {
				this.moveSelectedPiles(delta[0], delta[1]);
			} else if (press.moved) {
				this.renderView();
			} else if (!press.add && press.pile && this.selectedPiles.size > 1) {
				// A click (no drag) on one of several selected piles selects it alone.
				this.selectPile(press.pile, false);
			}
			return;
		}
		const box = drawing.svg.getBoundingClientRect();
		const start = drawing.toPlan(press.x - box.left, press.y - box.top);
		if (press.mode === 'box' && press.moved) {
			// Piles, columns and foundations (by their centre) inside the box; Shift adds to the selection.
			this.flush();
			const inside = (x: number, y: number) => x >= Math.min(start[0], point[0]) && x <= Math.max(start[0], point[0]) && y >= Math.min(start[1], point[1]) && y <= Math.max(start[1], point[1]);
			const piles = pilesInBox(document, start, point).map(p => p.id);
			const columns = this.context.columns.filter(c => inside(c.x, c.y)).map(c => c.id);
			const foundations = document.foundations.map((f, i) => {
				const center = foundationCenter(f, this.context);
				return center && inside(center[0], center[1]) ? i : -1;
			}).filter(i => i >= 0);
			this.selectedFoundations = [...new Set([...(press.add ? this.selectedFoundations : []), ...foundations])];
			this.selectedTieBeam = undefined;
			this.gridSelected = false;
			this.selectedPiles = new Set([...(press.add ? this.selectedPiles : []), ...piles]);
			this.selectedColumns = new Set([...(press.add ? this.selectedColumns : []), ...columns]);
			this.renderSelection();
			return;
		}
		if (press.mode === 'place') {
			this.placePilesAt(press.moved ? intersectionsInBox(document.pileGrid, start, point) : [snapPoint(point, document, this.context, SNAP_PX * drawing.mmPerPx, false).point]);
			return;
		}
		this.onPlanClick(press.target, press.add);
	}

	private onPlanClick(target: Element | null, add: boolean): void {
		const column = target?.closest('[data-column]')?.getAttribute('data-column');
		const foundation = target?.closest('[data-foundation]')?.getAttribute('data-foundation');
		const tie = target?.closest('[data-tie]')?.getAttribute('data-tie');
		if (this.tool === 'beam') {
			this.pickBeamEnd(column ? foundationOf(this.document!, column)?.id : foundation ? this.document?.foundations[Number(foundation)]?.id : undefined, column ?? undefined);
			return;
		}
		if (column) {
			this.selectColumn(column, add);
		} else if (tie) {
			this.selectTieBeam(Number(tie));
		} else if (foundation) {
			this.selectFoundation(Number(foundation), add);
		} else if (!add) {
			this.flush();
			this.clearSelection();
			this.renderSelection();
		}
	}

	private onKey(e: KeyboardEvent): void {
		const target = e.target as HTMLElement;
		if (isHTMLInputElement(target) || target.tagName === 'SELECT') {
			return;
		}
		const arrows: Record<string, Point> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
		if (e.key === 'Delete' && this.deleteAction.enabled) {
			e.preventDefault();
			void this.deleteSelection();
		} else if (arrows[e.key] && this.selectedPiles.size && this.view === 'plan') {
			// Nudge the selected piles 50 mm (Shift: 500 mm).
			e.preventDefault();
			const step = e.shiftKey ? 500 : 50;
			this.moveSelectedPiles(arrows[e.key][0] * step, arrows[e.key][1] * step);
		} else if (e.key === 'Escape') {
			if (this.tool !== 'select') {
				this.setTool('select');
			} else if (this.proposal) {
				this.discardProposal();
			} else {
				this.clearSelection();
				this.renderSelection();
			}
		}
	}

	// ───────────────────────────── actions ─────────────────────────────

	/** Selects `added` foundations after a structural edit and shows them in the plan. */
	private added(foundations: readonly IFoundation[]): void {
		if (!this.document) {
			return;
		}
		this.clearSelection();
		this.selectedFoundations = foundations.map(f => this.document!.foundations.indexOf(f)).filter(i => i >= 0);
		this.view = this.view === 'results' ? 'plan' : this.view;
		this.changed(true);
	}

	/** Whether none of `ids` stands on a foundation yet; says which do when some do. */
	private free(document: ISubstructure, ids: readonly string[]): boolean {
		const carried = carriedAlready(document, ids);
		if (carried.length) {
			this.notificationService.info(localize('sub.alreadyOn', "{0} already stands on a foundation ({1}). A column or wall stands on one foundation only: delete that one first, or change its columns.", carried.map(c => c.id).join(', '), [...new Set(carried.map(c => c.foundation))].join(', ')));
			return false;
		}
		return true;
	}

	/**
	 * Footings under the selected columns: one isolated footing under a single column, a combined
	 * footing under several; with none selected, an isolated footing under every column without one.
	 */
	addFootings(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const picked = this.pickedColumns;
		if (picked.length && !this.free(document, picked.map(c => c.id))) {
			return;
		}
		const columns = picked.length ? [picked] : uncoveredColumns(document, this.context).map(c => [c]);
		if (!columns.length) {
			this.notificationService.info(localize('sub.allCovered', "Every column already stands on a foundation. Select columns in the plan to add another."));
			return;
		}
		const added: IFoundation[] = [];
		for (const group of columns) {
			const footing = newFooting(document, this.context, group);
			document.foundations.push(footing);
			added.push(footing);
		}
		this.added(added);
	}

	private addPileCaps(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const picked = this.pickedColumns;
		if (picked.length && !this.free(document, picked.map(c => c.id))) {
			return;
		}
		const columns = picked.length ? [picked] : uncoveredColumns(document, this.context).map(c => [c]);
		if (!columns.length) {
			this.notificationService.info(localize('sub.allCovered', "Every column already stands on a foundation. Select columns in the plan to add another."));
			return;
		}
		let pile = document.pileTypes[0];
		if (!pile) {
			pile = newPileType(document, this.context);
			document.pileTypes.push(pile);
		}
		const added: IFoundation[] = [];
		for (const group of columns) {
			const cap = newPileCap(document, this.context, group, pile, group.length > 1 ? 6 : this.groupCount, this.spacingFactor);
			document.foundations.push(cap);
			added.push(cap);
		}
		this.added(added);
	}

	private async addRaft(): Promise<void> {
		const document = this.document;
		if (!document) {
			return;
		}
		this.flush();
		const picked = this.pickedColumns;
		const wanted = new Set((picked.length ? picked : this.context.columns).map(c => c.id));
		// The foundations under those columns (all of them for a raft under the whole building):
		// replaced by the raft once the engineer agrees (N-U6).
		const replaced = document.foundations.filter(f => picked.length ? (f.columns ?? []).some(c => wanted.has(c)) : (f.columns?.length || f.type === 'raft'));
		// Made before the others go: it takes their concrete and bars.
		const raft = newRaft(document, this.context, picked.length ? picked : this.context.columns);
		if (!raft) {
			this.notificationService.info(localize('sub.noColumns', "The building model has no columns on its base level yet."));
			return;
		}
		if (replaced.length) {
			const ids = replaced.map(f => f.id);
			const ties = document.tieBeams.filter(t => ids.includes(t.from) || ids.includes(t.to));
			const { confirmed } = await this.dialogService.confirm({
				type: 'warning',
				message: replaced.length === 1
					? localize('sub.raftReplaceOne', "Replace {0} with a raft?", ids[0])
					: localize('sub.raftReplaceMany', "Replace {0} foundations with a raft?", replaced.length),
				detail: (replaced.length > 1 ? localize('sub.raftReplaceList', "{0}.", ids.join(', ')) + ' ' : '')
					+ (ties.length ? localize('sub.raftReplaceTies', "Their tie beams are deleted with them: {0}. ", ties.map(t => t.id).join(', ')) : '')
					+ localize('sub.raftReplaceUndo', "The raft carries their columns. Undo (Ctrl+Z) brings them back."),
				primaryButton: localize({ key: 'sub.raftReplaceButton', comment: ['&& denotes a mnemonic'] }, "&&Replace with a Raft"),
			});
			if (!confirmed || this.document !== document) {
				return;
			}
			const gone = new Set(ids);
			document.foundations = document.foundations.filter(f => !gone.has(f.id));
			document.tieBeams = document.tieBeams.filter(t => !gone.has(t.from) && !gone.has(t.to));
			// A pile cap's piles go with it.
			const capPiles = new Set(replaced.flatMap(f => f.type === 'pileCap' ? f.piles ?? [] : []));
			if (capPiles.size) {
				deletePiles(document, capPiles);
			}
		}
		if (!picked.length) {
			// A raft under the whole building carries every column inside its outline.
			delete raft.columns;
		}
		document.foundations.push(raft);
		this.added([raft]);
	}

	private addStrip(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const picked = this.pickedColumns;
		if (picked.length && !this.free(document, picked.map(c => c.id))) {
			return;
		}
		let path: Point[] | undefined;
		let width = 1200;
		let carried: string[] = picked.map(c => c.id);
		if (picked.length >= 2) {
			// Along the line from the first to the farthest column, ordered by their projection on it.
			const first = picked[0];
			const far = picked.reduce((f, c) => Math.hypot(c.x - first.x, c.y - first.y) > Math.hypot(f.x - first.x, f.y - first.y) ? c : f, first);
			const dx = far.x - first.x;
			const dy = far.y - first.y;
			path = [...picked].sort((a, b) => (a.x - first.x) * dx + (a.y - first.y) * dy - ((b.x - first.x) * dx + (b.y - first.y) * dy)).map(c => [c.x, c.y] as Point);
		} else if (!picked.length && this.context.walls.length) {
			// Under the first wall of the base level no foundation carries yet.
			const wall = this.context.walls.find(w => !carriedAlready(document, [w.id]).length);
			if (!wall) {
				this.notificationService.info(localize('sub.wallsCovered', "Every wall of the base level already stands on a foundation. Select two or more columns for a strip footing along them."));
				return;
			}
			path = [[...wall.start], [...wall.end]] as Point[];
			width = Math.max(900, wall.thickness * 4);
			carried = [wall.id];
		}
		if (!path) {
			this.notificationService.info(localize('sub.stripNeeds', "Select two or more columns in the plan for a strip footing along them."));
			return;
		}
		const strip = newFooting(document, this.context, picked);
		strip.columns = carried;
		strip.type = 'strip';
		strip.path = path;
		strip.width = width;
		strip.thickness = 450;
		delete strip.length;
		delete strip.center;
		delete strip.rotation;
		document.foundations.push(strip);
		this.added([strip]);
	}

	private addTieBeam(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		if (this.selectedFoundations.length !== 2) {
			this.notificationService.info(localize('sub.tieNeeds', "Select two foundations in the plan (Shift+click the second) to tie them."));
			return;
		}
		const [from, to] = this.selectedFoundations.map(i => document.foundations[i].id);
		document.tieBeams.push(newTieBeam(document, this.context, from, to));
		this.clearSelection();
		this.selectedTieBeam = document.tieBeams.length - 1;
		this.changed(true);
	}

	private addPileType(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		document.pileTypes.push(newPileType(document, this.context));
		this.view = 'data';
		this.changed(true);
	}

	private async deleteSelection(): Promise<void> {
		const document = this.document;
		if (!document) {
			return;
		}
		if (this.selectedTieBeam !== undefined) {
			document.tieBeams.splice(this.selectedTieBeam, 1);
		} else if (this.selectedPiles.size) {
			const emptied = deletePiles(document, this.selectedPiles);
			for (const id of emptied) {
				this.notificationService.info(localize('sub.capEmptied', "{0} stands on no piles now: place piles under it, or delete it.", id));
			}
			for (const cap of document.foundations.filter(f => f.type === 'pileCap' && f.piles?.length)) {
				refitCap(document, cap);
			}
		} else if (this.selectedFoundations.length) {
			const removed = new Set(this.selectedFoundations.map(i => document.foundations[i]?.id));
			const ties = document.tieBeams.filter(t => removed.has(t.from) || removed.has(t.to));
			if (ties.length) {
				// A tie beam needs both its foundations: it goes with them. Say so first.
				const { confirmed } = await this.dialogService.confirm({
					type: 'warning',
					message: removed.size === 1
						? localize('sub.deleteTiesOne', "Delete {0} and its tie beams?", [...removed][0])
						: localize('sub.deleteTiesMany', "Delete {0} and their tie beams?", [...removed].join(', ')),
					detail: localize('sub.deleteTiesDetail', "These tie beams join a deleted foundation and are deleted with it: {0}. Undo (Ctrl+Z) brings all back.", ties.map(t => `${t.id} (${t.from} – ${t.to})`).join(', ')),
					primaryButton: localize({ key: 'sub.deleteTiesButton', comment: ['&& denotes a mnemonic'] }, "&&Delete"),
				});
				if (!confirmed || this.document !== document) {
					return;
				}
			} else if (removed.size > 1) {
				// Several at once (a box over the plan) are asked about first (N-U6).
				const { confirmed } = await this.dialogService.confirm({
					type: 'warning',
					message: localize('sub.deleteMany', "Delete {0} foundations?", removed.size),
					detail: localize('sub.deleteManyDetail', "{0}. Undo (Ctrl+Z) brings them back.", [...removed].join(', ')),
					primaryButton: localize({ key: 'sub.deleteManyButton', comment: ['&& denotes a mnemonic'] }, "&&Delete"),
				});
				if (!confirmed || this.document !== document) {
					return;
				}
			}
			document.foundations = document.foundations.filter((_, i) => !this.selectedFoundations.includes(i));
			document.tieBeams = document.tieBeams.filter(t => !removed.has(t.from) && !removed.has(t.to));
		} else {
			return;
		}
		this.clearSelection();
		this.changed(true);
	}

	// ───────────────────────────── piles, caps and grade beams ─────────────────────────────

	private setTool(tool: Tool): void {
		this.tool = tool;
		this.beamStart = undefined;
		this.press = undefined;
		if (tool !== 'select') {
			this.view = 'plan';
		}
		if (tool === 'pile') {
			this.pileType();
		}
		this.render();
	}

	/** The pile type the pile tools place; a 500 mm bored pile type is added when there is none. */
	private pileType(): IPileType | undefined {
		const document = this.document;
		if (!document) {
			return undefined;
		}
		let pile = document.pileTypes.find(p => p.id === this.placeType) ?? document.pileTypes[0];
		if (!pile) {
			pile = newPileType(document, this.context);
			document.pileTypes.push(pile);
			this.changed(true);
		}
		this.placeType = pile.id;
		return pile;
	}

	/** Places piles of the tools' pile type at `points` (none where a pile stands already). */
	private placePilesAt(points: readonly Point[]): void {
		const document = this.document;
		const pile = this.pileType();
		if (!document || !pile) {
			return;
		}
		const free = points.filter(p => !pileAt(document, p));
		if (!free.length) {
			this.notificationService.info(points.length ? localize('sub.pileThere', "A pile stands there already.") : localize('sub.noCrossings', "No pile grid crossing inside the box. Add a pile grid (Pile Grid), or click single points."));
			return;
		}
		const added = addPiles(document, pile.id, free);
		this.selectedPiles = new Set(added.map(p => p.id));
		this.selectedFoundations = [];
		this.selectedTieBeam = undefined;
		this.changed(true);
	}

	/** A standard pile group under each selected column (the tools' pile type, count and spacing). */
	private placeGroups(): void {
		const document = this.document;
		const columns = this.pickedColumns;
		if (!document) {
			return;
		}
		if (!columns.length) {
			this.notificationService.info(localize('sub.groupNeeds', "Select the columns in the plan to place a pile group under each."));
			return;
		}
		const pile = this.pileType();
		if (!pile) {
			return;
		}
		const added: IPile[] = [];
		for (const column of columns) {
			added.push(...placePileGroup(document, [column], pile, this.groupCount, this.spacingFactor));
		}
		this.selectedPiles = new Set(added.map(p => p.id));
		this.changed(true);
		this.renderSelection();
	}

	/** Make Pile Cap: one cap over the selected piles, carrying the selected columns (or the free ones inside it). */
	private makeCap(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const columns = this.pickedColumns;
		if (columns.length && !this.free(document, columns.map(c => c.id))) {
			return;
		}
		const { cap, error } = makePileCap(document, this.context, [...this.selectedPiles], columns.length ? columns : undefined);
		if (!cap) {
			this.notificationService.info(error ?? '');
			return;
		}
		document.foundations.push(cap);
		if (!cap.columns?.length) {
			this.notificationService.info(localize('sub.capNoColumns', "{0} carries no column: no free column base stands inside it. Give its columns in Properties.", cap.id));
		}
		this.added([cap]);
	}

	/** The grade beam tool: the first click picks an end, the second ties the two foundations. */
	private pickBeamEnd(foundation: string | undefined, column: string | undefined): void {
		const document = this.document;
		if (!document) {
			return;
		}
		if (!foundation) {
			if (column) {
				this.notificationService.info(localize('sub.beamNoFoundation', "{0} stands on no foundation yet: a grade beam joins two foundations.", column));
			}
			this.beamStart = undefined;
			this.renderView();
			return;
		}
		if (!this.beamStart || this.beamStart === foundation) {
			this.beamStart = foundation;
			this.renderView();
			return;
		}
		const from = this.beamStart;
		this.beamStart = foundation;
		if (tied(document, from, foundation)) {
			this.notificationService.info(localize('sub.beamThere', "{0} and {1} are tied already.", from, foundation));
			this.renderView();
			return;
		}
		document.tieBeams.push(newTieBeam(document, this.context, from, foundation));
		this.changed(true);
	}

	private connectBeams(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const added = connectGradeBeams(document, this.context);
		if (!added.length) {
			this.notificationService.info(localize('sub.connectNone', "No grade beam to add: the foundations along each grid line are tied already, or their columns stand on one foundation."));
			return;
		}
		this.notificationService.info(localize('sub.connected', "{0} grade beams added along the grid lines ({1}).", added.length, added.map(t => t.id).join(', ')));
		this.changed(true);
	}

	/** Moves the selected piles, fitting their caps round them again. */
	private moveSelectedPiles(dx: number, dy: number): void {
		const document = this.document;
		if (!document || !this.selectedPiles.size) {
			return;
		}
		movePiles(document, this.selectedPiles, dx, dy);
		const caps = pileCaps(document);
		const moved = new Set([...this.selectedPiles].map(id => caps.get(id)).filter((id): id is string => !!id));
		for (const cap of document.foundations.filter(f => moved.has(f.id))) {
			refitCap(document, cap);
		}
		this.changed(true);
	}

	/** Shows the pile grid in the properties, adding one over the columns when there is none. */
	private editPileGrid(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		if (!document.pileGrid) {
			document.pileGrid = newPileGrid(document, this.context);
			this.changed(true);
		}
		this.clearSelection();
		this.gridSelected = true;
		this.view = 'plan';
		this.frame.setPropertiesVisible(true);
		this.render();
	}

	private planOverlay(): SVGGElement {
		if (!this.overlay?.isConnected && this.drawing) {
			this.overlay = svg(this.drawing.svg, 'g', { class: 'sub-overlay' }) as SVGGElement;
		}
		return this.overlay!;
	}

	private request(): ISubstructureRequest | undefined {
		const root = this.projectRoot;
		const model = this.model;
		if (!root || !model) {
			return undefined;
		}
		return { projectRoot: root.fsPath, substructureText: model.getValue() };
	}

	/**
	 * The columns the sizing assistant is asked about: those of the selected foundations and the
	 * selected columns, each with all the columns of the foundation it stands on (a foundation is
	 * resized as a whole); with nothing selected, the columns without a foundation.
	 */
	private sizingColumns(document: ISubstructure): string[] {
		const picked = [
			...this.selectedFoundations.flatMap(i => document.foundations[i]?.columns ?? []),
			...this.pickedColumns.map(c => c.id),
		];
		if (!picked.length) {
			return uncoveredColumns(document, this.context).map(c => c.id);
		}
		const ids = new Set(picked);
		for (const f of document.foundations) {
			if (f.columns?.some(c => ids.has(c))) {
				f.columns.forEach(c => ids.add(c));
			}
		}
		return [...ids];
	}

	/**
	 * The sizing assistant: footings sized for the selected foundations and columns, or for every
	 * column without a foundation, shown in the plan until accepted or discarded.
	 */
	async sizeAll(): Promise<void> {
		this.flush();
		const base = this.request();
		const document = this.document;
		if (!base || !document) {
			return;
		}
		const columns = this.sizingColumns(document);
		if (!columns.length) {
			this.notificationService.info(localize('sub.sizeNone', "Every column already stands on a foundation. Select the foundations or columns to size again."));
			return;
		}
		const request: ISubstructureRequest = { ...base, columns };
		if (!CommandsRegistry.getCommand(SUBSTRUCTURE_SIZE_COMMAND)) {
			this.notificationService.info(localize('sub.sizeNoBackend', "Sizing the foundations needs the SAEngine backend, which is not available in this window."));
			return;
		}
		if (this.busy.has('size')) {
			this.notificationService.info(localize('sub.sizeRunning', "The footings are being sized already; the proposal appears in the plan when it is ready."));
			return;
		}
		this.setBusy('size', true);
		this.sizeAction.enabled = false;
		// Sizing runs every trial through the checks: it takes a while, so say what is going on,
		// how long it has run, and let the engineer stop waiting for it (N-U4).
		const message = (seconds: number) => {
			const what = columns.length === 1
				? localize('sub.sizingOne', "Sizing the footing under {0} from the reactions and the soil report…", columns[0])
				: localize('sub.sizingMany', "Sizing footings under {0} columns from the reactions and the soil report…", columns.length);
			return seconds ? `${what} ${localize('sub.sizingElapsed', "{0} s", seconds)}` : what;
		};
		let cancelled = false;
		const progress = this.notificationService.notify({
			severity: Severity.Info,
			message: message(0),
			progress: { infinite: true },
			actions: {
				primary: [toAction({
					id: 'saengine.substructure.sizeCancel', label: localize('sub.sizeCancel', "Cancel"), run: () => {
						cancelled = true;
						progress.close();
					},
				})],
			},
		});
		const started = Date.now();
		const targetWindow = getWindow(this.viewElement);
		const ticker = targetWindow.setInterval(() => progress.updateMessage(message(Math.round((Date.now() - started) / 1000))), 1000);
		let proposal: ISizingProposal | undefined;
		try {
			const answer = readSizingProposal(await this.commandService.executeCommand<unknown>(SUBSTRUCTURE_SIZE_COMMAND, request));
			proposal = answer && proposalFor(answer, columns);
		} catch (error) {
			if (!cancelled) {
				this.notificationService.error(localize('sub.sizeFailed', "The foundations could not be sized: {0}", errorSummary(error instanceof Error ? error.message : String(error)).summary));
			}
			return;
		} finally {
			targetWindow.clearInterval(ticker);
			progress.close();
			this.sizeAction.enabled = true;
			this.setBusy('size', false);
		}
		if (cancelled || this.document !== document) {
			return;
		}
		if (!proposal?.foundations.length) {
			this.notificationService.info(proposal?.notes.length ? sentences(proposal.notes) : localize('sub.sizeNothing', "The sizing assistant proposed no foundations. Run the analysis first: it sizes from the support reactions."));
			return;
		}
		this.proposal = proposal;
		this.view = 'plan';
		this.render();
	}

	private acceptProposal(): void {
		const document = this.document;
		const proposal = this.proposal;
		if (!document || !proposal) {
			return;
		}
		this.proposal = undefined;
		const ids = new Set(applyProposal(document, proposal));
		this.clearSelection();
		this.selectedFoundations = document.foundations.map((f, i) => ids.has(f.id) ? i : -1).filter(i => i >= 0);
		this.changed(true);
		// The backend checks the saved file: Accept saves and checks at once, not on the next Ctrl+S (N-U7).
		void this.saveAndCheck();
	}

	private discardProposal(): void {
		this.proposal = undefined;
		this.render();
	}

	/** Brings the footings drawn in the floor plan (Part 8's footing design) in as foundations. */
	async migrate(): Promise<void> {
		this.flush();
		const request = this.request();
		const document = this.document;
		if (!request || !document) {
			return;
		}
		if (!CommandsRegistry.getCommand(SUBSTRUCTURE_MIGRATE_COMMAND)) {
			this.notificationService.info(localize('sub.migrateNoBackend', "Importing the footings needs the SAEngine backend, which is not available in this window."));
			return;
		}
		this.setBusy('migrate', true);
		let imported: ISizingProposal | undefined;
		let savedIds = new Set<string>();
		try {
			imported = readSizingProposal(await this.commandService.executeCommand<unknown>(SUBSTRUCTURE_MIGRATE_COMMAND, request));
			savedIds = await this.savedFoundationIds();
		} catch (error) {
			this.notificationService.error(localize('sub.migrateFailed', "The footings could not be imported: {0}", error instanceof Error ? error.message : String(error)));
			return;
		} finally {
			this.setBusy('migrate', false);
		}
		if (!imported?.foundations.length || this.document !== document) {
			this.notificationService.info(imported?.notes.length ? sentences(imported.notes) : localize('sub.migrateNothing', "The building model has no footings to import."));
			return;
		}
		const { added, skipped } = importFoundations(document, imported, savedIds);
		const ids = new Set(added);
		if (!ids.size) {
			this.notificationService.info(skipped.length
				? localize('sub.migrateCarried', "The footings of the building model stand under columns that already have a foundation here ({0}); nothing was imported.", skipped.length)
				: localize('sub.migrateNone', "Every footing of the building model is already in the substructure."));
			return;
		}
		this.clearSelection();
		this.selectedFoundations = document.foundations.map((f, i) => ids.has(f.id) ? i : -1).filter(i => i >= 0);
		this.view = 'plan';
		this.changed(true);
		this.notificationService.info(ids.size === 1 ? localize('sub.migratedOne', "Imported 1 footing from the building model.") : localize('sub.migrated', "Imported {0} footings from the building model.", ids.size));
	}

	/**
	 * The ids of the foundations in the saved file: the import returns the saved file with the
	 * imported footings added, so these are the ones that were not imported.
	 */
	private async savedFoundationIds(): Promise<Set<string>> {
		const resource = this.resource;
		if (!resource) {
			return new Set();
		}
		try {
			const parsed = parseSubstructure((await this.fileService.readFile(resource)).value.toString());
			return new Set(parsed.kind === 'error' ? [] : parsed.document.foundations.map(f => f.id));
		} catch {
			return new Set(); // no file yet
		}
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

	/** Saves the edits (the backend checks the saved file) and checks the foundations at once. */
	async saveAndCheck(): Promise<void> {
		this.flush();
		const input = this.input;
		if (input?.isDirty()) {
			await input.save(this.group.id);
			// Saving schedules the check (onDidChangeDirty); run it now instead of after the pause.
		}
		this.reportScheduler.cancel();
		await this.computeReport();
	}

	/** Asks the backend for the design report (debounced after every edit). */
	async computeReport(): Promise<void> {
		const document = this.document;
		const version = ++this.reportVersion;
		const request = this.request();
		if (!document || !request || !document.foundations.length) {
			this.setBusy('report', false);
			this.report = undefined;
			this.reportState = 'idle';
			this.renderReportDependent();
			return;
		}
		if (!CommandsRegistry.getCommand(SUBSTRUCTURE_REPORT_COMMAND)) {
			this.setBusy('report', false);
			this.report = undefined;
			this.reportState = 'missing';
			this.renderReportDependent();
			return;
		}
		this.flush();
		this.reportState = this.report ? 'ok' : 'computing';
		this.setBusy('report', true);
		this.renderReportDependent();
		const siteVersion = this.siteVersion;
		// The backend checks the saved file: what it checks is what is on disk now (read again
		// after, in case a save came in between).
		const before = await this.savedText();
		let report: ISubstructureReport | undefined;
		let raw: unknown;
		let error: string | undefined;
		try {
			raw = await this.commandService.executeCommand<unknown>(SUBSTRUCTURE_REPORT_COMMAND, request);
			report = readSubstructureReport(raw);
			if (!report) {
				error = localize('sub.reportEmpty', "The backend gave no design report.");
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		const after = await this.savedText();
		if (version !== this.reportVersion) {
			return;
		}
		this.setBusy('report', false);
		const saved = before !== undefined && before === after ? parseSubstructure(before) : undefined;
		this.report = report;
		// A save while the backend ran: it may have read either file, so no result is trusted.
		this.checkedFor = saved && saved.kind !== 'error' ? documentSignatures(saved.document) : new Map();
		this.checkedSiteVersion = siteVersion;
		this.reportState = report ? 'ok' : 'error';
		this.reportError = error;
		this.renderReportDependent();
		if (before !== after || siteVersion !== this.siteVersion) {
			this.reportScheduler.schedule(0);
			return;
		}
		// The backend checks the saved file: the part list's summary is written only when the
		// editor holds no unsaved edits, so it describes the file it sits next to.
		if (report && this.resource && !this.input?.isDirty()) {
			const content = JSON.stringify(substructureSummaryFile(document, report, new Date()), undefined, '\t') + '\n';
			this.fileService.writeFile(joinPath(dirname(this.resource), SUBSTRUCTURE_SUMMARY_FILE), VSBuffer.fromString(content)).catch(() => { /* the part list then shows the count only */ });
			const kept = JSON.stringify({ checkedFor: Object.fromEntries(this.checkedFor ?? []), report: raw }) + '\n';
			this.fileService.writeFile(joinPath(dirname(this.resource), SUBSTRUCTURE_REPORT_FILE), VSBuffer.fromString(kept)).catch(() => { /* the next open checks first */ });
		}
	}

	/** The text of the saved file, undefined when it cannot be read. */
	private async savedText(): Promise<string | undefined> {
		const resource = this.resource;
		if (!resource) {
			return undefined;
		}
		try {
			return (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return undefined;
		}
	}

	/** Whether the report's results describe the parts as they are now (no edit of BIM, soil, analysis since). */
	private get siteCurrent(): boolean {
		return this.checkedSiteVersion === this.siteVersion;
	}

	/** The checks of `foundation` as it is now; undefined when it has none or changed since they were computed. */
	private resultOf(foundation: IFoundation): IFoundationResult | undefined {
		const result = this.report?.foundations.find(f => f.id === foundation.id);
		return result && this.document && this.siteCurrent && this.checkedFor?.get(`f:${foundation.id}`) === foundationSignature(this.document, foundation) ? result : undefined;
	}

	/** The checks of a tie beam as it is now (see {@link resultOf}). */
	private tieResultOf(tie: ITieBeam): IFoundationResult | undefined {
		const result = this.report?.tieBeams.find(t => t.id === tie.id);
		return result && this.document && this.siteCurrent && this.checkedFor?.get(`t:${tie.id}`) === tieBeamSignature(this.document, tie) ? result : undefined;
	}

	/** Whether `foundation` (or tie beam) has checks, but of what it was before an edit. */
	private isStale(item: IFoundation | ITieBeam, tie = false): boolean {
		if (tie) {
			return !!this.report?.tieBeams.some(r => r.id === item.id) && !this.tieResultOf(item as ITieBeam);
		}
		return !!this.report?.foundations.some(r => r.id === item.id) && !this.resultOf(item as IFoundation);
	}

	/** How far the checks cover the document as it is now (the one "all pass" verdict). */
	private get checkState(): ISubstructureCheckState | undefined {
		const document = this.document;
		if (!document || this.reportState !== 'ok' || !this.report) {
			return undefined;
		}
		const checkedFor = this.siteCurrent ? this.checkedFor : new Map<string, string>();
		return substructureCheckState(document, this.report, checkedFor, uncoveredBases(document, this.context));
	}

	/** "checking again…" while the backend runs, else what brings the checks up to date. */
	private get staleText(): string {
		return this.busy.has('report') ? localize('sub.recheckingRow', "changed: checking again…")
			: this.input?.isDirty() ? localize('sub.staleUnsaved', "changed: save to check") : localize('sub.staleRow', "changed: not checked yet");
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
		if (size !== this.lastSize && this.view !== 'data') {
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
		const usable = !!this.document;
		const picked = this.selectedColumns.size;
		this.addFootingAction.label = picked > 1 ? localize('sub.addCombined', "Add Combined Footing under the {0} Selected Columns", picked)
			: picked === 1 ? localize('sub.addFooting', "Add Footing under the Selected Columns")
				: localize('sub.addFootingsAll', "Add Footings under the Columns without a Foundation");
		this.addTieAction.enabled = this.selectedFoundations.length === 2;
		this.makeCapAction.enabled = this.selectedPiles.size > 0;
		this.makeCapAction.label = this.selectedPiles.size ? localize('sub.makeCapCount', "Make Pile Cap from the {0} Selected Piles", this.selectedPiles.size) : localize('sub.makeCap', "Make Pile Cap from the Selected Piles");
		this.pileGroupAction.enabled = this.selectedColumns.size > 0;
		this.placePilesAction.checked = this.tool === 'pile';
		this.gradeBeamAction.checked = this.tool === 'beam';
		this.deleteAction.enabled = this.selectedFoundations.length > 0 || this.selectedTieBeam !== undefined || this.selectedPiles.size > 0;
		this.deleteAction.label = this.selectedPiles.size ? localize('sub.deletePiles', "Delete {0} Piles", this.selectedPiles.size) : this.selectedTieBeam !== undefined
			? localize('sub.deleteNamed', "Delete {0}", this.document?.tieBeams[this.selectedTieBeam]?.id ?? '')
			: this.selectedFoundations.length === 1 ? localize('sub.deleteNamed', "Delete {0}", this.document?.foundations[this.selectedFoundations[0]]?.id ?? '')
				: localize('sub.delete', "Delete");
		this.recomputeAction.enabled = !!this.document?.foundations.length;
		this.saveAndCheckAction.enabled = !!this.document?.foundations.length;
		this.saveAndCheckAction.tooltip = this.input?.isDirty()
			? localize('sub.saveAndCheckDirty', "Save the edits and check the foundations (the checks read the saved file)")
			: localize('sub.saveAndCheckClean', "Check the foundations again");
		const primary: IAction[] = usable ? [
			this.addFootingAction, this.addPileCapAction, this.addRaftAction,
			this.pileGridAction, this.placePilesAction, this.pileGroupAction, this.makeCapAction, this.gradeBeamAction,
			this.sizeAction, this.saveAndCheckAction, this.deleteAction, frame.togglePropertiesAction,
		] : [frame.togglePropertiesAction];
		const secondary: IAction[] = usable ? [
			this.addTieAction, this.connectAction, this.addStripAction, this.addPileTypeAction, this.selectAllAction, this.migrateAction, new Separator(), this.recomputeAction,
		] : [];
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
				title: localize('sub.cannotShow', "The substructure cannot be shown"),
				text: this.parseError,
				actions: [{ label: localize('sub.openText', "Open as Text"), primary: true, run: () => void this.openAsText() }],
			});
		} else if (this.document && !this.document.foundations.length && !this.document.piles.length && !this.document.pileGrid && !this.proposal && !this.context.columns.length) {
			this.frame.setEmpty({
				icon: Codicon.symbolStructure,
				title: localize('sub.emptyNoColumns', "No columns to found yet"),
				text: localize('sub.emptyNoColumnsText', "The foundations stand under the columns of the building model. Build the building model (6 BIM) first; its columns on the base level then appear here."),
			});
		} else if (this.document && !this.document.foundations.length && !this.document.piles.length && !this.document.pileGrid && !this.proposal) {
			this.frame.setEmpty({
				icon: Codicon.symbolStructure,
				title: localize('sub.emptyTitle', "No foundations yet"),
				text: localize('sub.emptyText', "{0} columns stand on the base level. Let SAEngine size a footing under each from the analysis reactions and the soil report, bring in the footings drawn in the floor plan, or start with a footing under every column and size them yourself. For bored piles, lay them out on a pile grid of their own and form the caps over them.", this.context.columns.length),
				actions: [
					{ label: localize('sub.size', "Size Footings"), icon: Codicon.wand, primary: true, run: () => void this.sizeAll() },
					{ label: localize('sub.emptyFootings', "Add Footings under All Columns"), icon: Codicon.add, run: () => this.addFootings() },
					{ label: localize('sub.emptyPiles', "Lay Out Piles on a Pile Grid"), icon: Codicon.symbolNumeric, run: () => this.editPileGrid() },
				],
				link: { label: localize('sub.migrate', "Import Footings from the Building Model"), run: () => void this.migrate() },
			});
		} else {
			this.frame.setEmpty(undefined);
		}
	}

	private renderView(): void {
		this.viewDisposables.clear();
		this.inputs.clear();
		this.foundationRows.clear();
		const scroll = this.viewElement.scrollTop;
		clearNode(this.viewElement);
		this.viewElement.className = `sub-view ${this.view}`;
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

	private renderPlanView(document: ISubstructure): void {
		const view = this.viewElement;
		const header = append(view, $('.sub-view-header'));
		append(header, $('span.sub-view-title', undefined, localize('sub.planTitle', "Base level")));
		// A tool's hint takes the subtitle's place, so the plan does not move when a tool is picked.
		const subtitle = append(header, $(`span.sub-view-subtitle${this.tool === 'select' ? '' : '.sub-tool-hint'}`, { role: this.tool === 'select' ? undefined : 'status' }, this.tool === 'pile'
			? localize('sub.pileToolHint', "Placing {0} piles: click a pile grid crossing, a column or a point (snaps to 50 mm); drag a box to place one at every crossing inside. Escape ends.", this.placeType ?? '')
			: this.tool === 'beam'
				? this.beamStart
					? localize('sub.beamToolNext', "Grade beam from {0}: click the cap or column it runs to. Escape ends.", this.beamStart)
					: localize('sub.beamToolHint', "Grade beams: click a pile cap (or a column on a foundation), then the one it runs to. Escape ends.")
				: localize('sub.planSubtitle', "ground {0} m · founding level {1} m unless set · click a column or foundation, Shift+click to add to the selection",
					formatNumber(this.context.groundLevel / 1000, 2), formatNumber(defaultFoundingLevel(this.context) / 1000, 2))));
		subtitle.title = subtitle.textContent ?? '';

		const drawn = this.context.bimFootings ?? [];
		if (drawn.length && document.foundations.length) {
			// One source of truth: the substructure's foundations; the building model's are left over.
			append(view, $('p.sub-note.warning', undefined, localize('sub.bimFootings', "6 BIM still has footings drawn ({0}). They are not designed or measured: the foundations here are. Delete them from the floor plan so that the 3D view shows these.", drawn.join(', '))));
		}

		if (this.proposal) {
			const banner = append(view, $('.sub-banner', { role: 'status' }));
			append(banner, $(`span.sub-banner-icon${ThemeIcon.asCSSSelector(Codicon.wand)}`));
			const text = append(banner, $('.sub-banner-text'));
			const count = this.proposal.foundations.length;
			append(text, $('span.sub-banner-title', undefined, count === 1
				? localize('sub.proposalOne', "Proposed size for 1 foundation (dashed)")
				: localize('sub.proposal', "Proposed sizes for {0} foundations (dashed)", count)));
			const [first, ...more] = this.proposal.notes;
			if (first) {
				// The first note says what is proposed and why; the others (each footing's sizing, the
				// footings a raft replaces) fold away so the plan stays in view (N-U12).
				append(text, $('span.sub-banner-detail', undefined, sentences([first])));
				if (more.length) {
					const details = append(text, $<HTMLDetailsElement>('details.sub-banner-more'));
					append(details, $('summary', undefined, more.length === 1 ? localize('sub.proposalMoreOne', "1 more note") : localize('sub.proposalMore', "{0} more notes", more.length)));
					for (const note of more) {
						append(details, $('div.sub-banner-detail', undefined, sentences([note])));
					}
				}
			}
			this.renderProposalTable(text, document, this.proposal);
			const accept = this.viewDisposables.add(new Button(banner, { ...defaultButtonStyles }));
			accept.label = localize('sub.accept', "Accept");
			this.viewDisposables.add(accept.onDidClick(() => this.acceptProposal()));
			const discard = this.viewDisposables.add(new Button(banner, { ...defaultButtonStyles, secondary: true }));
			discard.label = localize('sub.discard', "Discard");
			this.viewDisposables.add(discard.onDidClick(() => this.discardProposal()));
		}

		const legend = append(view, $('.sub-legend'));
		const item = (cls: string, label: string) => {
			const element = append(legend, $('span.sub-legend-item'));
			append(element, $(`span.sub-swatch.${cls}`));
			append(element, $('span', undefined, label));
		};
		item('footing', localize('sub.legendFooting', "Footing"));
		item('cap', localize('sub.legendCap', "Pile cap and piles"));
		item('raft', localize('sub.legendRaft', "Raft"));
		item('tie', localize('sub.legendTie', "Tie beam"));
		if (document.pileGrid) {
			item('pile-grid', localize('sub.legendPileGrid', "Pile grid"));
		}
		item('column', localize('sub.legendColumn', "Column"));
		if (this.context.boreholes.length) {
			item('borehole', localize('sub.legendBorehole', "Borehole"));
		}
		if (this.report) {
			item('band-ok', localize('sub.legendOk', "below 0.9"));
			item('band-warn', localize('sub.legendWarn', "0.9 to 1.0"));
			item('band-fail', localize('sub.legendFail', "above 1.0"));
		}

		const canvas = append(view, $(`.sub-canvas.tool-${this.tool}`));
		const width = Math.max(240, view.clientWidth - 32);
		// What is left below the header, legend and banner (the banner's table grows with the proposal).
		const used = canvas.getBoundingClientRect().top - view.getBoundingClientRect().top + view.scrollTop;
		const height = Math.max(240, view.clientHeight - used - 16);
		// A footing passing all but its bearing check (no qa) is amber, not green (N-U3).
		const band = (r: IFoundationResult | undefined) => r?.ok && r.notChecked?.length ? 'warn' : utilisationBand(r?.utilisation);
		const bands = this.report ? new Map(document.foundations.map(f => [f.id, band(this.resultOf(f))])) : undefined;
		this.drawing = renderPlan(canvas, document, this.context, {
			width, height,
			selectedFoundations: new Set(this.selectedFoundations),
			selectedColumns: this.selectedColumns,
			selectedTieBeam: this.selectedTieBeam,
			selectedPiles: this.selectedPiles,
			beamStart: this.beamStart,
			proposals: this.proposal?.foundations,
			bands,
			utilisations: new Map(document.foundations.flatMap(f => {
				const u = this.resultOf(f)?.utilisation;
				return typeof u === 'number' ? [[f.id, u] as const] : [];
			})),
		});
		this.overlay = undefined;
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_DOWN, e => this.onPlanDown(e)));
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_MOVE, e => this.onPlanMove(e)));
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_UP, e => this.onPlanUp(e)));
		this.viewDisposables.add(addDisposableListener(canvas, EventType.POINTER_LEAVE, () => {
			if (!this.press && this.overlay) {
				this.overlay.replaceChildren();
			}
		}));
	}

	/** What Accept changes: each proposed foundation against the one it replaces (or "new"). */
	private renderProposalTable(parent: HTMLElement, document: ISubstructure, proposal: ISizingProposal): void {
		const table = append(parent, $('table.sub-table.sub-proposal-table'));
		this.tableHead(table, [
			{ label: localize('sub.f.columns', "Columns"), width: 110 }, { label: localize('sub.proposalNow', "Now"), width: 190 },
			{ label: localize('sub.proposalAfter', "After Accept"), width: 190 }, { label: localize('sub.proposalBars', "Bottom bars"), width: 110 },
		]);
		const body = append(table, $('tbody'));
		for (const proposed of proposal.foundations) {
			const columns = new Set(proposed.columns ?? []);
			const replaced = document.foundations.filter(f => (f.columns ?? []).some(c => columns.has(c)));
			const row = append(body, $('tr'));
			append(row, $('td', undefined, (proposed.columns ?? []).join(', ')));
			append(row, $('td', undefined, replaced.length ? replaced.map(f => `${f.id} ${foundationSize(f)}`).join('; ') : localize('sub.proposalNew', "none (new)")));
			append(row, $('td', undefined, `${foundationTypeLabel(proposed.type)} ${foundationSize(proposed)}`));
			const before = replaced[0]?.reinforcement?.bottomX;
			const after = proposed.reinforcement?.bottomX;
			append(row, $('td', undefined, after ? before && formatMesh(before) !== formatMesh(after) ? `${formatMesh(before)} → ${formatMesh(after)}` : formatMesh(after) : '—'));
		}
	}

	// ───────────────────────────── data view ─────────────────────────────

	private renderDataView(document: ISubstructure): void {
		const header = append(this.viewElement, $('.sub-view-header'));
		append(header, $('span.sub-view-title', undefined, localize('sub.dataTitle', "Foundations, piles and tie beams")));
		append(header, $('span.sub-view-subtitle', undefined, localize('sub.dataSubtitle', "Sizes in mm, levels and positions in m; click a row to edit the rest in Properties.")));
		this.renderFoundationTable(document);
		this.renderPileTypeTable(document);
		this.renderPileTable(document);
		this.renderTieBeamTable(document);
		this.renderGroundSlabTable(document);
		this.renderRetainingWallTable(document);
	}

	private renderRetainingWallTable(document: ISubstructure): void {
		const walls = document.retainingWalls ?? [];
		const section = this.section(localize('sub.retainingWalls', "Retaining walls"), walls.length, {
			label: localize('sub.addRetainingWall', "Add Retaining Wall"),
			run: () => {
				document.retainingWalls = [...walls, newRetainingWall(document, this.context)];
				this.changed(true);
			},
		});
		const table = append(append(section, $('.sub-table-scroll')), $('table.sub-table'));
		const lengthField = (key: string, label: string): IFieldSpec => ({ key, label, unit: MM, kind: 'number', min: 0 });
		const levelField = (key: string, label: string): IFieldSpec => ({ key, label, unit: M, kind: 'length' });
		const sizes = [
			lengthField('stemTop', localize('sub.f.stemTop', "Stem top")),
			lengthField('stemBottom', localize('sub.f.stemBottom', "Stem base")),
			lengthField('baseThickness', localize('sub.f.baseThickness', "Base")),
			lengthField('toe', localize('sub.f.toe', "Toe")),
			lengthField('heel', localize('sub.f.heel', "Heel")),
		];
		const top = levelField('topLevel', localize('sub.f.topLevel', "Top"));
		const founding = levelField('foundingLevel', F.foundingLevel.label);
		const pathField: IFieldSpec = { key: 'path', label: localize('sub.f.path', "Path (x, y; ...)"), kind: 'text' };
		const floorsField: IFieldSpec = { key: 'supports', label: localize('sub.f.floors', "Floors (levels; ...)"), kind: 'text' };
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('sub.f.wallKind', "Kind"), width: 110 }, { label: pathField.label, unit: M, width: 150 },
			{ label: top.label, unit: M, numeric: true }, { label: founding.label, unit: M, numeric: true, width: 84 },
			...sizes.map(f => ({ label: f.label, unit: MM, numeric: true, width: 64 })),
			{ label: floorsField.label, unit: M, width: 110 }, { label: localize('sub.f.buildingWall', "Building wall"), width: 90 },
			{ label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 72 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		const kinds = [
			{ value: 'cantilever', label: localize('sub.rw.cantilever', "Cantilever") },
			{ value: 'basement', label: localize('sub.rw.basement', "Basement (propped)") },
		];
		const wallOptions = this.context.walls.map(w => ({ value: w.id, label: w.id }));
		const metres = (values: readonly number[]) => values.map(v => formatNumber(v / 1000, 3)).join('; ');
		const parseList = (text: string): number[] | undefined => {
			const values = text.split(';').map(t => t.trim()).filter(t => t).map(Number);
			return values.every(v => Number.isFinite(v)) ? values.map(v => Math.round(v * 1000)) : undefined;
		};
		walls.forEach((wall: IRetainingWall, index) => {
			const row = append(body, $('tr'));
			const path = (field: string) => `retainingWalls.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, wall.id, value => {
				wall.id = String(value ?? '');
				this.changed(false);
			}, path('id')));
			append(append(row, $('td')), this.selectInput(kinds, wall.kind ?? 'cantilever', value => {
				wall.kind = value === 'basement' ? 'basement' : 'cantilever';
				this.changed(true);
			}, path('kind'), localize('sub.f.wallKind', "Kind")));
			const points = wall.path.map(p => `${formatNumber(p[0] / 1000, 3)}, ${formatNumber(p[1] / 1000, 3)}`).join('; ');
			append(append(row, $('td')), this.textInput(pathField, points, value => {
				const parsed = String(value ?? '').split(';').map(t => t.split(',').map(v => Number(v.trim())));
				if (parsed.length >= 2 && parsed.every(p => p.length === 2 && p.every(v => Number.isFinite(v)))) {
					wall.path = parsed.map(p => [Math.round(p[0] * 1000), Math.round(p[1] * 1000)] as [number, number]);
					this.changed(true);
				}
			}, path('path')));
			for (const field of [top, founding]) {
				append(append(row, $('td')), this.textInput(field, wall[field.key], value => {
					if (typeof value === 'number') {
						wall[field.key] = value;
						this.changed(true);
					}
				}, path(field.key)));
			}
			for (const field of sizes) {
				append(append(row, $('td')), this.textInput(field, wall[field.key], value => {
					if (typeof value === 'number') {
						wall[field.key] = value;
					} else {
						delete wall[field.key];
					}
					this.changed(true);
				}, path(field.key)));
			}
			append(append(row, $('td')), this.textInput(floorsField, metres(wall.supports ?? []), value => {
				const levels = parseList(String(value ?? ''));
				if (levels) {
					wall.supports = levels;
					this.changed(true);
				}
			}, path('supports')));
			append(append(row, $('td')), this.selectInput(wallOptions, wall.wall ?? '', value => {
				if (value) {
					wall.wall = value;
				} else {
					delete wall.wall;
				}
				this.changed(true);
			}, path('wall'), localize('sub.f.buildingWall', "Building wall"), true));
			const result = this.report?.retainingWalls?.find(r => r.id === wall.id);
			const utilisation = result?.utilisation;
			append(row, $(`td.number${result && !result.ok ? '.sub-rw-fail' : ''}`, undefined, typeof utilisation === 'number' ? formatNumber(utilisation, 2) : ''));
			this.removeButton(row, () => {
				document.retainingWalls = walls.filter((_, i) => i !== index);
				this.changed(true);
			});
		});
		if (!walls.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noRetainingWalls', "None yet. Add a cantilever retaining wall, or a basement wall propped by the floors; the soil comes from 1 Soil Report.")));
		}
	}

	private section(title: string, count: number, add?: { label: string; run: () => void }): HTMLElement {
		const section = append(this.viewElement, $('.sub-section'));
		const heading = append(section, $('.sub-section-heading'));
		append(heading, $('span.sub-section-title', undefined, title));
		append(heading, $('span.sub-section-count', undefined, String(count)));
		if (add) {
			const button = append(heading, $<HTMLButtonElement>('button.sub-add', { type: 'button' }));
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
				append(th, $('span.sub-unit', undefined, column.unit));
			}
		}
	}

	private removeButton(row: HTMLElement, run: () => void): void {
		const label = localize('sub.removeRow', "Remove");
		const button = append(append(row, $('td.sub-row-actions')), $<HTMLButtonElement>('button.sub-remove', { type: 'button', title: label, 'aria-label': label }));
		append(button, $(ThemeIcon.asCSSSelector(Codicon.trash)));
		this.viewDisposables.add(addDisposableListener(button, EventType.CLICK, e => {
			e.stopPropagation();
			run();
		}));
	}

	private renderFoundationTable(document: ISubstructure): void {
		const section = this.section(localize('sub.foundationsHeading', "Foundations"), document.foundations.length, { label: localize('sub.addFootingShort', "Add Footing"), run: () => this.addFootings() });
		const scroller = append(section, $('.sub-table-scroll'));
		const table = append(scroller, $('table.sub-table.sub-foundations'));
		const columns = [
			{ label: F.id.label, width: 88 }, { label: localize('sub.f.type', "Type"), width: 156 }, { label: localize('sub.f.columns', "Columns"), width: 150 },
			{ label: F.length.label, unit: MM, numeric: true }, { label: F.width.label, unit: MM, numeric: true }, { label: F.thickness.label, unit: MM, numeric: true },
			{ label: F.foundingLevel.label, unit: M, numeric: true, width: 84 }, { label: localize('sub.f.pileType', "Pile type"), width: 84 }, { label: localize('sub.f.piles', "Piles"), numeric: true, width: 48 },
			{ label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 84 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		document.foundations.forEach((f, index) => {
			const row = append(body, $('tr.sub-row', { 'data-index': String(index) }));
			this.foundationRows.set(row, index);
			const path = (field: string) => `foundations.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, f.id, value => this.renameFoundation(f, String(value ?? '')), path('id')));
			append(append(row, $('td')), this.selectInput(FOUNDATION_TYPES.map(t => ({ value: t, label: foundationTypeLabel(t) })), f.type, value => this.setType(f, value as FoundationType), path('type'), localize('sub.f.type', "Type")));
			append(append(row, $('td')), this.columnsInput(f, path('columns')));
			for (const field of [F.length, F.width, F.thickness]) {
				const usable = !(f.type === 'raft' && field !== F.thickness) && !(f.type === 'strip' && field === F.length);
				const td = append(row, $('td'));
				if (usable) {
					append(td, this.textInput(field, f[field.key], value => this.setField(f, field.key, value), path(field.key)));
				} else {
					td.classList.add('sub-muted');
					td.textContent = '—';
				}
			}
			append(append(row, $('td')), this.textInput(F.foundingLevel, f.foundingLevel, value => this.setField(f, 'foundingLevel', value), path('foundingLevel'), formatNumber(defaultFoundingLevel(this.context) / 1000, 3)));
			const pileCell = append(row, $('td'));
			if (f.type === 'pileCap') {
				append(pileCell, this.selectInput(document.pileTypes.map(p => ({ value: p.id, label: p.id })), capPileType(f, document)?.id ?? '', value => this.setPileType(f, value), path('pileType'), localize('sub.f.pileType', "Pile type"), true));
			} else {
				pileCell.classList.add('sub-muted');
				pileCell.textContent = '—';
			}
			append(row, $('td.number', undefined, f.type === 'pileCap' ? String(f.piles?.length ?? 0) : ''));
			this.utilisationCell(row, this.resultOf(f)?.utilisation);
			this.removeButton(row, () => {
				this.selectedFoundations = [index];
				void this.deleteSelection();
			});
			this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, e => {
				if (!(e.target as HTMLElement).closest('input, select, button')) {
					this.selectFoundation(index, e.shiftKey || e.ctrlKey || e.metaKey);
				}
			}));
		});
		if (!document.foundations.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noRows', "None yet.")));
		}
		this.markSelectedRows();
	}

	private markSelectedRows(): void {
		for (const [row, index] of this.foundationRows) {
			row.classList.toggle('selected', this.selectedFoundations.includes(index));
		}
	}

	private renderPileTypeTable(document: ISubstructure): void {
		const section = this.section(localize('sub.pileTypes', "Pile types"), document.pileTypes.length, { label: localize('sub.addPileType', "Add Pile Type"), run: () => this.addPileType() });
		const table = append(append(section, $('.sub-table-scroll')), $('table.sub-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('sub.f.kind', "Kind"), width: 170 }, { label: F.diameter.label, unit: MM, numeric: true, width: 80 },
			{ label: F.pileLength.label, unit: M, numeric: true }, { label: localize('sub.f.material', "Concrete"), width: 96 },
			{ label: localize('sub.f.pileBars', "Bars"), width: 84 }, { label: localize('sub.f.pileTies', "Ties"), width: 110 },
			{ label: localize('sub.f.headFixity', "Head"), width: 120 }, { label: F.fixityDepth.label, unit: M, numeric: true, width: 80 },
			{ label: localize('sub.f.pileCount', "Piles"), numeric: true, width: 48 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		document.pileTypes.forEach((pile, index) => {
			const row = append(body, $('tr'));
			const path = (field: string) => `pileTypes.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, pile.id, value => this.renamePileType(pile, String(value ?? '')), path('id')));
			append(append(row, $('td')), this.selectInput(PILE_KINDS.map(k => ({ value: k, label: pileKindLabel(k) })), pile.kind, value => {
				pile.kind = value as IPileType['kind'];
				this.changed(true);
			}, path('kind'), localize('sub.f.kind', "Kind")));
			append(append(row, $('td')), this.textInput(F.diameter, pile.diameter, value => {
				pile.diameter = typeof value === 'number' ? value : 0;
				this.changed(false);
			}, path('diameter')));
			append(append(row, $('td')), this.textInput(F.pileLength, pile.length, value => {
				pile.length = typeof value === 'number' ? value : 0;
				this.changed(false);
			}, path('length')));
			append(append(row, $('td')), this.materialInput(pile.material, value => {
				if (value) {
					pile.material = value;
					this.changed(true);
				}
			}, path('material'), true));
			append(append(row, $('td')), this.pileBarsInput(pile, path('reinforcement.longitudinal')));
			append(append(row, $('td')), this.pileTiesInput(pile, path('reinforcement.transverse')));
			append(append(row, $('td')), this.selectInput(PILE_FIXITIES.map(k => ({ value: k, label: pileFixityLabel(k) })), pile.headFixity ?? 'fixed', value => {
				pile.headFixity = value as IPileType['headFixity'];
				this.changed(false);
			}, path('headFixity'), localize('sub.f.headFixity', "Head")));
			append(append(row, $('td')), this.textInput(F.fixityDepth, pile.fixityDepth, value => {
				if (typeof value === 'number') {
					pile.fixityDepth = value;
				} else {
					delete pile.fixityDepth;
				}
				this.changed(false);
			}, path('fixityDepth')));
			append(row, $('td.number', undefined, String(document.piles.filter(p => p.type === pile.id).length)));
			this.removeButton(row, () => {
				document.pileTypes.splice(index, 1);
				this.changed(true);
			});
		});
		if (!document.pileTypes.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noPileTypes', "None yet. A pile cap adds a 500 mm bored pile type to start with.")));
		}
		const planned = append(section, $('.sub-planned'));
		for (const id of PLANNED_PILE_FEATURES) {
			this.viewDisposables.add(appendPlannedFeatureChip(planned, id, this.commandService));
		}
	}

	/** The piles placed in plan: mark, pile type, position and the cap each is under. */
	private renderPileTable(document: ISubstructure): void {
		const section = this.section(localize('sub.pilesHeading', "Piles"), document.piles.length, { label: localize('sub.placePilesShort', "Place Piles"), run: () => this.setTool('pile') });
		const table = append(append(section, $('.sub-table-scroll')), $('table.sub-table'));
		const columns = [
			{ label: localize('sub.f.mark', "Mark"), width: 64 }, { label: localize('sub.f.pileType', "Pile type"), width: 96 },
			{ label: F.pileX.label, unit: M, numeric: true, width: 84 }, { label: F.pileY.label, unit: M, numeric: true, width: 84 },
			{ label: localize('sub.f.cap', "Cap"), width: 64 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		const caps = pileCaps(document);
		document.piles.forEach((pile, index) => {
			const row = append(body, $('tr.sub-row'));
			row.classList.toggle('selected', this.selectedPiles.has(pile.id));
			const path = (field: string) => `piles.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, pile.id, value => this.renamePile(pile, String(value ?? '')), path('id')));
			append(append(row, $('td')), this.selectInput(document.pileTypes.map(p => ({ value: p.id, label: p.id })), pile.type, value => {
				pile.type = value;
				this.changed(true);
			}, path('type'), localize('sub.f.pileType', "Pile type")));
			for (const [field, axis] of [[F.pileX, 0], [F.pileY, 1]] as const) {
				append(append(row, $('td')), this.textInput(field, pile.position[axis], value => this.setPilePosition(pile, axis, value), path(`position.${axis}`)));
			}
			append(row, $(caps.has(pile.id) ? 'td' : 'td.sub-muted', undefined, caps.get(pile.id) ?? localize('sub.noCap', "none")));
			this.removeButton(row, () => {
				this.selectedPiles = new Set([pile.id]);
				void this.deleteSelection();
			});
			this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, e => {
				if (!(e.target as HTMLElement).closest('input, select, button')) {
					this.selectPile(pile.id, e.shiftKey || e.ctrlKey || e.metaKey);
				}
			}));
		});
		if (!document.piles.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noPiles', "None yet. Place piles on the pile grid in the plan, or a pile group under a column.")));
		}
	}

	private renamePile(pile: IPile, id: string): void {
		const old = pile.id;
		pile.id = id;
		for (const f of this.document?.foundations ?? []) {
			if (f.piles?.includes(old)) {
				f.piles = f.piles.map(p => p === old ? id : p);
			}
		}
		if (this.selectedPiles.delete(old)) {
			this.selectedPiles.add(id);
		}
		this.changed(false);
	}

	private setPilePosition(pile: IPile, axis: 0 | 1, value: number | string | undefined): void {
		if (typeof value !== 'number' || !this.document) {
			return;
		}
		const position: Point = [...pile.position] as Point;
		position[axis] = value;
		pile.position = position;
		const cap = this.document.foundations.find(f => f.type === 'pileCap' && f.piles?.includes(pile.id));
		if (cap) {
			refitCap(this.document, cap);
		}
		this.changed(false);
	}

	private renderTieBeamTable(document: ISubstructure): void {
		const section = this.section(localize('sub.tieBeams', "Tie beams"), document.tieBeams.length, document.foundations.length >= 2 ? {
			label: localize('sub.addTieShort', "Add Tie Beam"),
			run: () => {
				const [a, b] = this.selectedFoundations.length === 2 ? this.selectedFoundations.map(i => document.foundations[i].id) : [document.foundations[0].id, document.foundations[1].id];
				document.tieBeams.push(newTieBeam(document, this.context, a, b));
				this.changed(true);
			},
		} : undefined);
		const table = append(append(section, $('.sub-table-scroll')), $('table.sub-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: localize('sub.f.from', "From"), width: 84 }, { label: localize('sub.f.to', "To"), width: 84 },
			{ label: localize('sub.f.beamType', "Beam type"), width: 150 }, { label: F.level.label, unit: M, numeric: true }, { label: localize('sub.f.span', "Span"), unit: M, numeric: true, width: 64 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		const foundationOptions = document.foundations.map(f => ({ value: f.id, label: f.id }));
		document.tieBeams.forEach((tie, index) => {
			const row = append(body, $('tr'));
			const path = (field: string) => `tieBeams.${index}.${field}`;
			append(append(row, $('td')), this.textInput(F.id, tie.id, value => {
				tie.id = String(value ?? '');
				this.changed(false);
			}, path('id')));
			for (const end of ['from', 'to'] as const) {
				append(append(row, $('td')), this.selectInput(foundationOptions, tie[end], value => {
					tie[end] = value;
					this.changed(true);
				}, path(end), end === 'from' ? localize('sub.f.from', "From") : localize('sub.f.to', "To")));
			}
			append(append(row, $('td')), this.beamTypeInput(tie, path('type')));
			append(append(row, $('td')), this.textInput(F.level, tie.level, value => this.setTieLevel(tie, value), path('level'), this.tieLevelPlaceholder(tie)));
			append(row, $('td.number', undefined, this.tieSpan(tie)));
			this.removeButton(row, () => {
				document.tieBeams.splice(index, 1);
				this.changed(true);
			});
		});
		if (!document.tieBeams.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noTies', "None yet. Select two foundations in the plan and add a tie beam between them.")));
		}
	}

	/** The slabs on grade: thickness, concrete, loads, sub-base k, mesh and utilisation. */
	private renderGroundSlabTable(document: ISubstructure): void {
		const section = this.section(localize('sub.groundSlabs', "Slabs on grade"), document.groundSlabs.length, {
			label: localize('sub.addGroundSlab', "Add Slab on Grade"),
			run: () => {
				document.groundSlabs.push(newGroundSlab(document, this.context));
				this.changed(true);
			},
		});
		const table = append(append(section, $('.sub-table-scroll')), $('table.sub-table'));
		const columns = [
			{ label: F.id.label, width: 64 }, { label: F.slabThickness.label, unit: MM, numeric: true, width: 72 }, { label: localize('sub.f.material', "Concrete"), width: 96 },
			{ label: F.uniformLoad.label, unit: F.uniformLoad.unit, numeric: true, width: 72 }, { label: F.pointLoad.label, unit: F.pointLoad.unit, numeric: true, width: 72 },
			{ label: F.contactSide.label, unit: MM, numeric: true, width: 72 }, { label: F.subgradeModulus.label, unit: F.subgradeModulus.unit, numeric: true, width: 80 },
			{ label: localize('sub.f.slabMesh', "Mesh"), width: 84 }, { label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: '', width: 28 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		document.groundSlabs.forEach((slab, index) => {
			const row = append(body, $('tr'));
			const path = (field: string) => `groundSlabs.${index}.${field}`;
			const set = (key: string) => (value: number | string | undefined) => {
				if (value === undefined || value === '') {
					delete slab[key];
				} else {
					slab[key] = value;
				}
				this.changed(false);
			};
			append(append(row, $('td')), this.textInput(F.id, slab.id, value => {
				slab.id = String(value ?? '');
				this.changed(false);
			}, path('id')));
			append(append(row, $('td')), this.textInput(F.slabThickness, slab.thickness, set('thickness'), path('thickness')));
			append(append(row, $('td')), this.materialInput(slab.material, value => {
				if (value) {
					slab.material = value;
					this.changed(true);
				}
			}, path('material'), true));
			append(append(row, $('td')), this.textInput(F.uniformLoad, slab.uniformLoad, set('uniformLoad'), path('uniformLoad'), '5'));
			append(append(row, $('td')), this.textInput(F.pointLoad, slab.pointLoad, set('pointLoad'), path('pointLoad'), '0'));
			append(append(row, $('td')), this.textInput(F.contactSide, slab.contactSide, set('contactSide'), path('contactSide'), '150'));
			append(append(row, $('td')), this.textInput(F.subgradeModulus, slab.subgradeModulus, set('subgradeModulus'), path('subgradeModulus')));
			const mesh = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', placeholder: localize('sub.plain', "plain"), 'aria-label': localize('sub.f.slabMesh', "Mesh") });
			mesh.value = formatMesh(slab.mesh);
			this.viewDisposables.add(addDisposableListener(mesh, EventType.CHANGE, () => {
				const parsed = parseMesh(mesh.value);
				if (parsed.error) {
					mesh.classList.add('invalid');
					mesh.title = parsed.error;
					return;
				}
				if (parsed.value) {
					slab.mesh = parsed.value;
					slab.meshMaterial ??= this.context.barMaterial;
				} else {
					delete slab.mesh;
					delete slab.meshMaterial;
				}
				this.changed(false);
			}));
			append(append(row, $('td')), mesh);
			this.utilisationCell(row, this.report?.groundSlabs.find(r => r.id === slab.id)?.utilisation);
			this.removeButton(row, () => {
				document.groundSlabs.splice(index, 1);
				this.changed(true);
			});
		});
		if (!document.groundSlabs.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noGroundSlabs', "None yet. A slab on grade is checked for its largest post or wheel load (Westergaard) and punching.")));
		}
		const planned = append(section, $('.sub-planned'));
		this.viewDisposables.add(appendPlannedFeatureChip(planned, 'substructure.machineFoundation', this.commandService));
	}

	private tieSpan(tie: ITieBeam): string {
		const from = this.document?.foundations.find(f => f.id === tie.from);
		const to = this.document?.foundations.find(f => f.id === tie.to);
		const a = from && foundationCenter(from, this.context);
		const b = to && foundationCenter(to, this.context);
		return a && b ? formatNumber(Math.hypot(b[0] - a[0], b[1] - a[1]) / 1000, 2) : '';
	}

	/** The level a tie beam without one is designed at: the higher top of its two foundations [m]. */
	private tieLevelPlaceholder(tie: ITieBeam): string | undefined {
		const tops = [tie.from, tie.to].map(id => this.document?.foundations.find(f => f.id === id)).filter((f): f is IFoundation => !!f)
			.map(f => (typeof f.foundingLevel === 'number' ? f.foundingLevel : defaultFoundingLevel(this.context)) + (typeof f.thickness === 'number' ? f.thickness : 0));
		return tops.length ? formatNumber(Math.max(...tops) / 1000, 3) : undefined;
	}

	private setTieLevel(tie: ITieBeam, value: number | string | undefined): void {
		if (typeof value === 'number') {
			tie.level = value;
		} else {
			delete tie.level;
		}
		this.changed(false);
	}

	// ───────────────────────────── edits ─────────────────────────────

	/** An isolated footing's section (flat, sloped, stepped) and the sizes of its top. */
	private renderFootingSection(panel: HTMLElement, foundation: IFoundation, path: (field: string) => string): void {
		const label = localize('sub.f.section', "Section");
		const current = foundation.section ?? 'flat';
		this.propertyRow(panel, label, this.selectInput(FOOTING_SECTIONS.map(k => ({ value: k, label: footingSectionLabel(k) })), current, value => {
			if (value === 'flat') {
				delete foundation.section;
				delete foundation.edgeThickness;
				delete foundation.topLength;
				delete foundation.topWidth;
			} else {
				foundation.section = value as FootingSection;
				// Start from half the thickness at the edges and a top 75 mm round the column.
				const column = this.context.columns.find(c => foundation.columns?.includes(c.id));
				const thickness = foundation.thickness ?? 600;
				foundation.edgeThickness ??= Math.round(thickness / 2 / 25) * 25;
				foundation.topLength ??= Math.min(foundation.length ?? 1500, (column?.xDim ?? 400) + 150);
				foundation.topWidth ??= Math.min(foundation.width ?? 1500, (column?.yDim ?? 400) + 150);
			}
			this.changed(true);
		}, path('section'), label), undefined, localize('sub.f.sectionTitle', "Sloped: the top slopes from a flat top round the column to the edge thickness. Stepped: an upper step round the column on a lower slab. ACI 318-19 13.2.7.3: every section is checked with its own depth."));
		if (current !== 'flat') {
			this.fieldRow(panel, F.edgeThickness, foundation.edgeThickness, value => this.setField(foundation, 'edgeThickness', value), path('edgeThickness'));
			this.fieldRow(panel, F.topLength, foundation.topLength, value => this.setField(foundation, 'topLength', value), path('topLength'));
			this.fieldRow(panel, F.topWidth, foundation.topWidth, value => this.setField(foundation, 'topWidth', value), path('topWidth'));
		}
	}

	private setField(foundation: IFoundation, key: string, value: number | string | undefined): void {
		if (value === undefined || value === '') {
			delete foundation[key];
		} else {
			foundation[key] = value;
		}
		this.changed(false);
	}

	private renameFoundation(foundation: IFoundation, id: string): void {
		const old = foundation.id;
		foundation.id = id;
		for (const tie of this.document?.tieBeams ?? []) {
			if (tie.from === old) {
				tie.from = id;
			}
			if (tie.to === old) {
				tie.to = id;
			}
		}
		this.changed(false);
	}

	private renamePileType(pile: IPileType, id: string): void {
		const old = pile.id;
		pile.id = id;
		for (const p of this.document?.piles ?? []) {
			if (p.type === old) {
				p.type = id;
			}
		}
		if (this.placeType === old) {
			this.placeType = id;
		}
		this.changed(false);
	}

	/** Changes a foundation's type, giving it what the new type needs (piles, an outline, a path). */
	private setType(foundation: IFoundation, type: FoundationType): void {
		const document = this.document;
		if (!document || foundation.type === type) {
			return;
		}
		const columns = this.context.columns.filter(c => foundation.columns?.includes(c.id));
		const center = foundationCenter(foundation, this.context);
		foundation.type = type;
		if (type === 'pileCap') {
			let pile = document.pileTypes[0];
			if (!pile) {
				pile = newPileType(document, this.context);
				document.pileTypes.push(pile);
			}
			applyPileLayout(document, this.context, foundation, pile, columns.length > 1 ? 6 : 4, this.spacingFactor);
		} else {
			deletePiles(document, new Set(foundation.piles ?? []));
			delete foundation.piles;
		}
		if (type === 'raft') {
			const raft = newRaft(document, this.context, columns.length ? columns : this.context.columns);
			foundation.outline = raft?.outline ?? (center ? [[center[0] - 1000, center[1] - 1000], [center[0] + 1000, center[1] - 1000], [center[0] + 1000, center[1] + 1000], [center[0] - 1000, center[1] + 1000]] : []);
			delete foundation.length;
			delete foundation.width;
			delete foundation.center;
			delete foundation.rotation;
		} else {
			delete foundation.outline;
		}
		if (type === 'strip') {
			foundation.path = columns.length >= 2 ? columns.map(c => [c.x, c.y] as Point) : center ? [[center[0] - 1500, center[1]], [center[0] + 1500, center[1]]] : [];
			foundation.width ??= 1200;
			delete foundation.length;
			delete foundation.center;
		} else {
			delete foundation.path;
		}
		if ((type === 'isolated' || type === 'combined') && !(foundation.length && foundation.width)) {
			Object.assign(foundation, { length: 1500, width: 1500 });
		}
		foundation.thickness ??= 450;
		// The bars of the old type may be too light for the new thickness (a footing turned into a
		// 1 m pile cap): raise each bottom layer to the minimum mesh, and give a raft its top bars.
		const least = minimumMesh(Number(foundation.thickness));
		const area = (mesh: { dia: number; spacing: number } | undefined) => mesh ? Math.PI * mesh.dia * mesh.dia / 4 * 1000 / mesh.spacing : 0;
		const bars = foundation.reinforcement;
		if (bars) {
			for (const layer of type === 'raft' ? MESH_KEYS : ['bottomX', 'bottomY'] as const) {
				if (area(bars[layer]) < area(least) - 1e-6) {
					bars[layer] = { ...least };
				}
			}
		}
		this.changed(true);
	}

	/** Sets the pile type of a cap's piles and fits the cap round them (their spacing stays). */
	private setPileType(foundation: IFoundation, id: string): void {
		const document = this.document;
		if (!document || !id) {
			return;
		}
		setCapPileType(document, foundation, id);
		refitCap(document, foundation);
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
		const input = $<HTMLInputElement>(`input.sub-input${numeric ? '.number' : ''}`, { type: 'text', spellcheck: 'false', 'aria-label': field.unit ? `${field.label} (${field.unit})` : field.label });
		input.value = formatField(field, value);
		if (placeholder) {
			input.placeholder = placeholder;
		}
		this.inputStore.add(addDisposableListener(input, EventType.INPUT, () => {
			const parsed = parseField(field, input.value);
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
		const select = $<HTMLSelectElement>('select.sub-select', { 'aria-label': label });
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

	/** A concrete; `required` offers no empty choice once one is set. */
	private materialInput(current: string | undefined, store: (value: string | undefined) => void, key: string, required = false): HTMLSelectElement {
		return this.selectInput(this.context.materials.map(m => ({ value: m, label: m })), current ?? '', value => store(value || undefined), key, localize('sub.f.material', "Concrete"), !required || !current);
	}

	/** A tie beam's beam type: required, so the empty choice is there only while none is chosen. */
	private beamTypeInput(tie: ITieBeam, key: string): HTMLSelectElement {
		return this.selectInput(this.context.beamTypes.map(b => ({ value: b.id, label: b.name })), tie.type ?? '', value => {
			if (value) {
				tie.type = value;
				this.changed(true);
			}
		}, key, localize('sub.f.beamType', "Beam type"), !tie.type);
	}

	/** A pile's longitudinal bars, typed as "8Ø16"; a pile without bars gets the bar material and cover first. */
	private pileBarsInput(pile: IPileType, key: string): HTMLInputElement {
		const input = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': localize('sub.f.pileBars', "Bars"), placeholder: localize('sub.plain', "plain") });
		input.value = formatPileBars(pile.reinforcement);
		input.title = localize('sub.pileBarsTitle', "Bars round the perimeter, count Ø diameter (e.g. 8Ø16); BNBC 2020 Part 6 Table 6.3.11 gives the least for a bored pile. Empty: plain concrete.");
		this.inputStore.add(addDisposableListener(input, EventType.INPUT, () => {
			const parsed = parsePileBars(input.value);
			this.markInvalid(input, parsed.error);
			if (parsed.error) {
				return;
			}
			if (parsed.value) {
				const bars = pile.reinforcement ??= { ...(this.context.barMaterial ? { material: this.context.barMaterial } : {}), cover: 75 };
				bars.longitudinal = [{ position: 'perimeter', ...parsed.value }];
			} else if (pile.reinforcement) {
				delete pile.reinforcement.longitudinal;
				if (!pile.reinforcement.transverse) {
					delete pile.reinforcement;
				}
			}
			this.changed(false);
		}));
		this.inputStore.add(addDisposableListener(input, EventType.BLUR, () => this.flush()));
		this.inputMap.set(key, input);
		return input;
	}

	/** A pile's ties or spiral, typed as "Ø8@250" or "spiral Ø8@75". */
	private pileTiesInput(pile: IPileType, key: string): HTMLInputElement {
		const input = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': localize('sub.f.pileTies', "Ties"), placeholder: localize('sub.none', "none") });
		input.value = formatPileTies(pile.reinforcement);
		input.title = localize('sub.pileTiesTitle', "Ties (Ø diameter @ spacing, e.g. Ø8@250) or a spiral (spiral Ø8@75), in mm");
		this.inputStore.add(addDisposableListener(input, EventType.INPUT, () => {
			const parsed = parsePileTies(input.value);
			this.markInvalid(input, parsed.error);
			if (parsed.error) {
				return;
			}
			if (parsed.value) {
				const bars = pile.reinforcement ??= { ...(this.context.barMaterial ? { material: this.context.barMaterial } : {}), cover: 75 };
				bars.transverse = { ...bars.transverse, ...parsed.value };
			} else if (pile.reinforcement) {
				delete pile.reinforcement.transverse;
			}
			this.changed(false);
		}));
		this.inputStore.add(addDisposableListener(input, EventType.BLUR, () => this.flush()));
		this.inputMap.set(key, input);
		return input;
	}

	/** The columns a foundation carries, typed as a list: "C1, C2". */
	private columnsInput(foundation: IFoundation, key: string): HTMLInputElement {
		const input = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': localize('sub.f.columns', "Columns") });
		input.value = (foundation.columns ?? []).join(', ');
		input.title = input.value; // a combined footing's or raft's list is longer than the cell
		if (foundation.type === 'raft' && !foundation.columns?.length) {
			input.placeholder = localize('sub.f.columnsInside', "all inside");
		}
		this.inputStore.add(addDisposableListener(input, EventType.INPUT, () => {
			const ids = parseIdList(input.value);
			if (ids.length) {
				foundation.columns = ids;
			} else {
				delete foundation.columns;
			}
			this.changed(false);
		}));
		this.inputStore.add(addDisposableListener(input, EventType.BLUR, () => this.flush()));
		this.inputMap.set(key, input);
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

	private renderResultsView(document: ISubstructure): void {
		const view = this.viewElement;
		if (!document.foundations.length) {
			return;
		}
		if (this.reportState !== 'ok' || !this.report) {
			const state = append(view, $('.sub-results-state'));
			const computing = this.reportState === 'computing' || this.reportState === 'idle';
			const icon = computing ? ThemeIcon.modify(Codicon.loading, 'spin') : this.reportState === 'error' ? Codicon.warning : Codicon.debugDisconnect;
			append(state, $(`span.sub-results-state-icon${ThemeIcon.asCSSSelector(icon)}`));
			append(state, $('.sub-results-state-title', undefined, computing
				? localize('sub.computing', "Checking the foundations...")
				: this.reportState === 'error' ? localize('sub.reportFailed', "The foundations could not be checked")
					: localize('sub.backendMissing', "Backend not available")));
			if (this.reportState === 'error') {
				// One line and Details, never the raw traceback (N-U1).
				const error = errorSummary(this.reportError ?? '');
				append(state, $('.sub-results-state-text', undefined, error.summary));
				const actions = append(state, $('.sub-results-state-actions'));
				const again = this.viewDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: error.restart }));
				again.label = localize('sub.checkAgain', "Check Again");
				this.viewDisposables.add(again.onDidClick(() => void this.computeReport()));
				if (error.restart) {
					const restart = this.viewDisposables.add(new Button(actions, defaultButtonStyles));
					restart.label = localize('sub.restartEngine', "Restart Engine");
					restart.element.title = localize('sub.restartEngineHint', "The engine's files changed while it ran (a code pack, an update): restart it, then the foundations are checked again.");
					this.viewDisposables.add(restart.onDidClick(async () => {
						await this.commandService.executeCommand(RESTART_ENGINE_COMMAND);
						void this.computeReport();
					}));
					actions.insertBefore(restart.element, again.element);
				}
				if (error.details) {
					const details = append(state, $<HTMLDetailsElement>('details.sub-results-state-details'));
					append(details, $('summary', undefined, localize('sub.errorDetails', "Details")));
					append(details, $('pre', undefined, error.details));
				}
				return;
			}
			append(state, $('.sub-results-state-text', undefined, this.reportState === 'missing' ? localize('sub.backendMissingText', "The bearing, shear, flexure, pile and raft checks are computed by the SAEngine Python backend from the analysis reactions and the soil report; it is not running in this window. The foundations can still be drawn and edited; the checks appear once the backend is available.") : ''));
			return;
		}
		const report = this.report;
		const header = append(view, $('.sub-view-header'));
		append(header, $('span.sub-view-title', undefined, localize('sub.resultsTitle', "Design checks")));
		append(header, $('span.sub-view-subtitle', undefined, localize('sub.resultsSubtitle', "Computed from the analysis reactions and the soil report; not stored in the file.")));
		const state = this.checkState!;
		const verdict = append(view, $(`p.sub-note.sub-verdict.${state.status === 'pass' ? 'ok' : state.status === 'fail' ? 'error' : 'warning'}`, { role: 'status' }));
		verdict.textContent = checkStateText(state);
		if (state.stale) {
			append(verdict, $('span', undefined, ` · ${this.input?.isDirty()
				? localize('sub.resultsUnsavedShort', "save to check the edits")
				: this.busy.has('report') ? localize('sub.recheckingShort', "checking again…") : ''}`));
		}
		if (state.unsupported.length) {
			append(view, $('p.sub-note.warning', undefined, localize('sub.unsupportedList', "Without a foundation, so not designed: {0}. Add a footing (a strip footing for a wall) under each.", state.unsupported.join(', '))));
		}

		this.renderTiles(view, document, state);
		this.renderResultTable(view, document, report);
		const selected = this.foundation ?? document.foundations.find(f => f.id === report.summary.governing);
		const result = selected && this.resultOf(selected);
		if (selected && result) {
			this.renderFoundationDetail(view, selected, result);
		} else if (selected && this.isStale(selected)) {
			const section = this.resultSection(view, localize('sub.detailTitle', "{0}: all checks", selected.id), `${foundationTypeLabel(selected.type)} · ${foundationSize(selected)}`);
			append(section, $('p.sub-note.warning', undefined, localize('sub.detailStale', "{0} changed since its checks were computed, so they are not shown ({1})", selected.id, this.staleText)));
		}
		this.renderPileCapacities(view, report);
		if (report.notes.length || report.skipped.length) {
			const section = this.resultSection(view, localize('sub.notes', "Notes"));
			for (const skipped of report.skipped) {
				append(section, $('p.sub-note.warning', undefined, localize('sub.skipped', "{0} not checked: {1}.", skipped.id, skipped.reason)));
			}
			for (const note of report.notes) {
				append(section, $('p.sub-note', undefined, note));
			}
		}
		if (report.method.length) {
			const section = this.resultSection(view, localize('sub.method', "Method"));
			for (const line of report.method) {
				append(section, $('p.sub-note', undefined, line));
			}
		}
	}

	private resultSection(view: HTMLElement, title: string, detail?: string): HTMLElement {
		const section = append(view, $('.sub-section.result'));
		const heading = append(section, $('.sub-section-heading'));
		append(heading, $('span.sub-section-title', undefined, title));
		if (detail) {
			append(heading, $('span.sub-section-detail', undefined, detail));
		}
		return section;
	}

	private renderTiles(view: HTMLElement, document: ISubstructure, state: ISubstructureCheckState): void {
		const tiles = append(view, $('.sub-tiles'));
		const tile = (value: string, label: string, band?: string) => {
			const element = append(tiles, $('.sub-tile'));
			append(element, $(`span.sub-tile-value${band ? `.band-${band}` : ''}`, undefined, value));
			append(element, $('span.sub-tile-label', undefined, label));
		};
		tile(localize('sub.tileOf', "{0} of {1}", state.checked, state.total), document.tieBeams.length ? localize('sub.tileCheckedTies', "foundations and tie beams checked") : localize('sub.tileChecked', "foundations checked"), state.checked < state.total ? 'warn' : undefined);
		tile(String(state.failed), localize('sub.tileFailed', "fail"), state.failed ? 'fail' : state.status === 'pass' ? 'ok' : undefined);
		// The largest utilisation and pressure of the results that describe the foundations as they are now.
		const current = document.foundations.map(f => this.resultOf(f)).filter((r): r is IFoundationResult => !!r);
		const designed = [...current, ...document.tieBeams.map(t => this.tieResultOf(t)).filter((r): r is IFoundationResult => !!r)];
		const worst = designed.reduce<IFoundationResult | undefined>((w, f) => f.utilisation !== null && (w?.utilisation ?? -1) < f.utilisation ? f : w, undefined);
		// While a check runs the maxima may describe the foundations before the edit (an overlap
		// with a changed neighbour): shown again once it is done (N-U7).
		if (this.busy.has('report')) {
			tile('…', localize('sub.tileChecking', "checking again"));
			return;
		}
		if (typeof worst?.utilisation === 'number') {
			tile(formatUtilisation(worst.utilisation), localize('sub.tileMaxIn', "largest utilisation, {0}", worst.id), utilisationBand(worst.utilisation));
		}
		const pressure = maxPressure({ foundations: current });
		if (pressure) {
			tile(localize('sub.kpaValue', "{0} kPa", formatNumber(pressure.pressure, 0)), typeof pressure.allowable === 'number'
				? localize('sub.tilePressureQa', "max bearing pressure, {0} (qa {1} kPa)", pressure.id, formatNumber(pressure.allowable, 0))
				: localize('sub.tilePressure', "max bearing pressure, {0}", pressure.id),
				typeof pressure.allowable === 'number' ? utilisationBand(pressure.pressure / pressure.allowable) : undefined);
		}
	}

	private utilisationCell(row: HTMLElement, utilisation: number | null | undefined): void {
		const td = append(row, $('td.number.sub-util-cell'));
		if (typeof utilisation !== 'number') {
			td.textContent = '';
			return;
		}
		const band = utilisationBand(utilisation);
		const bar = append(td, $('span.sub-util-bar'));
		append(bar, $(`span.sub-util-fill.band-${band}`, { style: `width: ${Math.min(100, utilisation * 100).toFixed(0)}%` }));
		append(td, $(`span.sub-util-value.band-${band}`, undefined, formatUtilisation(utilisation)));
	}

	private renderResultTable(view: HTMLElement, document: ISubstructure, report: ISubstructureReport): void {
		const section = this.resultSection(view, localize('sub.byFoundation', "By foundation"), localize('sub.byFoundationDetail', "the governing check of each; click one for all its checks"));
		const table = append(section, $('table.sub-table.sub-result-table.sub-results'));
		this.tableHead(table, [
			{ label: F.id.label, width: 64 }, { label: localize('sub.f.type', "Type"), width: 130 }, { label: localize('sub.f.size', "Size"), width: 150 },
			{ label: localize('sub.governing', "Governing check"), width: 200 }, { label: localize('sub.combination', "Combination"), width: 180 }, { label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 120 },
		]);
		const body = append(table, $('tbody'));
		document.foundations.forEach((f, index) => {
			const result = this.resultOf(f);
			const stale = !result && this.isStale(f);
			const row = append(body, $('tr.sub-row', { 'data-index': String(index), tabIndex: 0 }));
			this.foundationRows.set(row, index);
			row.classList.toggle('stale', stale);
			const governing = governingCheck(result);
			append(row, $('td', undefined, f.id));
			append(row, $('td', undefined, foundationTypeLabel(f.type)));
			append(row, $('td', undefined, foundationSize(f)));
			append(row, $('td', undefined, result ? governing?.name ?? '' : stale ? this.staleText : this.notCheckedText(f.id)));
			append(row, $('td.sub-muted-cell', undefined, governing?.combination || '—'));
			if (result?.notChecked?.includes('bearing') && result.ok) {
				// Passing what was checked is not passing: the bearing that sizes it was not (N-U3).
				append(append(row, $('td.number.sub-util-cell')), $('span.sub-util-value.band-warn', undefined, localize('sub.noBearing', "bearing not checked")));
			} else {
				this.utilisationCell(row, result?.utilisation);
			}
			if (result && !result.ok) {
				row.classList.add('failed');
			}
			this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, e => this.selectFoundation(index, e.shiftKey || e.ctrlKey || e.metaKey)));
			this.viewDisposables.add(addDisposableListener(row, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter') {
					this.selectFoundation(index, false);
				}
			}));
		});
		document.tieBeams.forEach((tie, index) => {
			const result = this.tieResultOf(tie);
			const stale = !result && this.isStale(tie, true);
			const row = append(body, $('tr.sub-row.tie', { tabIndex: 0 }));
			row.classList.toggle('stale', stale);
			const governing = governingCheck(result);
			append(row, $('td', undefined, tie.id));
			append(row, $('td', undefined, localize('sub.tieBeam', "Tie beam")));
			append(row, $('td', undefined, localize('sub.tieBetween', "{0} – {1}", tie.from, tie.to)));
			append(row, $('td', undefined, result ? governing?.name ?? '' : stale ? this.staleText : this.notCheckedText(tie.id)));
			append(row, $('td.sub-muted-cell', undefined, governing?.combination || '—'));
			this.utilisationCell(row, result?.utilisation);
			if (result && !result.ok) {
				row.classList.add('failed');
			}
			this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.selectTieBeam(index)));
		});
		this.markSelectedRows();
	}

	/** "not checked: <the backend's reason>" for a foundation or tie beam the design skipped. */
	private notCheckedText(id: string): string {
		const reason = this.report?.skipped.find(s => s.id === id)?.reason;
		return reason ? localize('sub.notCheckedWhy', "not checked: {0}", reason) : localize('sub.notChecked', "not checked");
	}

	private renderFoundationDetail(view: HTMLElement, foundation: IFoundation, result: IFoundationResult): void {
		const section = this.resultSection(view, localize('sub.detailTitle', "{0}: all checks", foundation.id), `${foundationTypeLabel(foundation.type)} · ${foundationSize(foundation)}`);
		// The note (and for a failing check, the suggested fix) on its own full-width line under each
		// check, so that the table fits a 1366 px window instead of running off to the right.
		const table = append(section, $('table.sub-table.sub-result-table.sub-check-table'));
		const columns = [
			{ label: localize('sub.check', "Check"), width: 200 }, { label: localize('sub.demand', "Demand / required"), numeric: true, width: 96 }, { label: localize('sub.capacity', "Capacity / provided"), numeric: true, width: 96 },
			{ label: localize('sub.unit', "Unit"), width: 60 }, { label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('sub.combination', "Combination"), width: 150 },
		];
		this.tableHead(table, columns);
		const body = append(table, $('tbody'));
		const value = (v: number | null) => v === null ? '—' : Math.abs(v) >= 100 ? formatNumber(v, 0) : Math.abs(v) >= 1 || v === 0 ? formatNumber(v, 2) : String(Number(v.toPrecision(3)));
		// The checks that count first, by utilisation; the ones only reported after them.
		for (const check of [...result.checks].sort((a, b) => Number(a.flag) - Number(b.flag) || (b.utilisation ?? -1) - (a.utilisation ?? -1))) {
			const row = append(body, $(check.flag ? 'tr.flag' : 'tr'));
			append(row, $('td', undefined, check.flag ? localize('sub.flagged', "{0} (reported only)", check.name) : check.name));
			append(row, $('td.number', undefined, value(check.demand)));
			const overlap = check.name === CLEARANCE_CHECK;
			// The clearance between footings passes or fails; its "capacity" 0 mm and a ratio mean little (N-U12).
			append(row, $('td.number', undefined, overlap ? '—' : value(check.capacity)));
			append(row, $('td.sub-muted-cell', undefined, check.unit));
			if (overlap && !check.ok) {
				append(append(row, $('td.number.sub-util-cell')), $('span.sub-util-value.band-fail', undefined, localize('sub.overlapBy', "overlaps by {0} mm", formatNumber(check.demand ?? 0, 0))));
			} else if (check.capacity === 0 && (check.utilisation ?? 0) >= 99) {
				// Nothing provided (no bars in that layer): a ratio means nothing.
				append(append(row, $('td.number.sub-util-cell')), $('span.sub-util-value.band-fail', undefined, localize('sub.needsBars', "none provided")));
			} else {
				this.utilisationCell(row, check.utilisation);
			}
			append(row, $('td.sub-muted-cell.sub-combination-cell', undefined, check.combination || '—'));
			const suggestion = check.ok || check.flag ? '' : this.suggestion(foundation, check);
			if (suggestion || check.note) {
				row.classList.add('has-note');
				const line = append(append(body, $(check.flag ? 'tr.sub-note-row.flag' : 'tr.sub-note-row')), $('td.sub-wrap.sub-note-cell', { colspan: String(columns.length) }));
				if (suggestion) {
					append(line, $('span.sub-suggestion', undefined, localize('sub.suggestedText', "Suggested: {0}. ", suggestion)));
				}
				append(line, $('span', undefined, check.note));
			}
		}
		for (const note of result.notes ?? []) {
			append(section, $('p.sub-note', undefined, note));
		}
		if (result.piles?.length) {
			this.renderPileLoads(section, result);
		}
		if (result.raft) {
			this.renderRaft(section, foundation, result);
		}
	}

	/** A first step to make a failing check pass. */
	private suggestion(foundation: IFoundation, check: { readonly name: string }): string {
		const name = check.name.toLowerCase();
		const thickness = typeof foundation.thickness === 'number' ? foundation.thickness : undefined;
		if ((name.startsWith('min') || name.includes('flexure') || name.includes('steel') || name.includes('tie (')) && thickness) {
			return localize('sub.suggestBars', "at least {0} each way (As,min of {1} mm); more for the flexure", formatMesh(minimumMesh(thickness)), formatNumber(thickness, 0));
		}
		// Size Footings proposes a raft only from scratch: a raft is made thicker or larger by hand.
		if (foundation.type === 'raft' && (name.includes('punching') || name.includes('shear'))) {
			return localize('sub.suggestRaftThicker', "thicker: raise its Thickness, then Save and Check");
		}
		if (foundation.type === 'raft' && (name.includes('bearing') || name.includes('contact') || name.includes('settlement'))) {
			return localize('sub.suggestRaftLarger', "a larger outline (or piles under it), then Save and Check");
		}
		if (name.includes('bearing') || name.includes('resultant') || name.includes('contact') || name.includes('uplift')) {
			return localize('sub.suggestSize', "larger plan: Size Footings with it selected");
		}
		if (name.includes('punching') || name.includes('shear')) {
			return localize('sub.suggestThicker', "thicker: Size Footings with it selected");
		}
		if (name.includes('pile')) {
			return localize('sub.suggestPiles', "more or larger piles (Layout, Pile type)");
		}
		return '';
	}

	private renderPileLoads(section: HTMLElement, result: IFoundationResult): void {
		append(section, $('.sub-subheading', undefined, localize('sub.pileLoads', "Pile loads")));
		const table = append(section, $('table.sub-table.sub-result-table'));
		const kn = localize('sub.unit.kn', "kN");
		const capacity = result.capacity?.compression;
		this.tableHead(table, [
			{ label: localize('sub.pile', "Pile"), width: 48 }, { label: 'u', unit: M, numeric: true, width: 64 }, { label: 'v', unit: M, numeric: true, width: 64 },
			{ label: localize('sub.serviceMax', "Service max"), unit: kn, numeric: true, width: 96 }, { label: localize('sub.serviceMin', "Service min"), unit: kn, numeric: true, width: 96 },
			{ label: localize('sub.factoredMax', "Factored max"), unit: kn, numeric: true, width: 96 }, { label: localize('sub.allowable', "Allowable"), unit: kn, numeric: true, width: 84 },
			{ label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 120 },
		]);
		const body = append(table, $('tbody'));
		const dash = (v: number | undefined, scale = 1, decimals = 0) => typeof v === 'number' ? formatNumber(v / scale, decimals) : '—';
		for (const pile of result.piles ?? []) {
			const row = append(body, $('tr'));
			const allowable = pile.capacity ?? capacity;
			append(row, $('td', undefined, pile.mark ?? String(pile.number)));
			append(row, $('td.number', undefined, dash(pile.u, 1000, 2)));
			append(row, $('td.number', undefined, dash(pile.v, 1000, 2)));
			append(row, $('td.number', undefined, dash(pile.compression, 1, 1)));
			append(row, $('td.number', undefined, dash(pile.least, 1, 1)));
			append(row, $('td.number', undefined, dash(pile.factored, 1, 1)));
			append(row, $('td.number', undefined, dash(allowable)));
			this.utilisationCell(row, pile.utilisation ?? (typeof pile.compression === 'number' && allowable ? pile.compression / allowable : undefined));
		}
		append(section, $('p.sub-note', undefined, localize('sub.pileLoadsNote', "u, v: offsets from the cap's centre in its local axes. Service min below zero: the pile pulls out.")));
	}

	private renderRaft(section: HTMLElement, foundation: IFoundation, result: IFoundationResult): void {
		const raft = result.raft!;
		append(section, $('.sub-subheading', undefined, localize('sub.raftHeading', "Contact pressure and settlement")));
		const facts = append(section, $('dl.sub-basis'));
		const fact = (label: string, text: string | undefined) => {
			if (text) {
				append(facts, $('dt', undefined, label));
				append(facts, $('dd', undefined, text));
			}
		};
		const n = (v: number | undefined, unit: string, decimals = 0) => typeof v === 'number' ? `${formatNumber(v, decimals)} ${unit}` : undefined;
		const kpa = localize('sub.unit.kpa', "kPa");
		const net = result.pressure;
		fact(localize('sub.raftNetPressure', "Max net pressure"), typeof net?.max === 'number'
			? typeof net.allowable === 'number' ? localize('sub.raftPressureQa', "{0} kPa (qa {1} kPa)", formatNumber(net.max, 0), formatNumber(net.allowable, 0)) : n(net.max, kpa)
			: undefined);
		fact(localize('sub.raftGrossPressure', "Max gross contact pressure"), typeof raft.maxPressure === 'number'
			? localize('sub.raftGrossValue', "{0} kPa (with the overburden)", formatNumber(raft.maxPressure, 0))
			: undefined);
		fact(localize('sub.raftMaxSettlement', "Max settlement"), n(raft.maxSettlement, MM, 1));
		fact(localize('sub.raftDifferential', "Differential settlement"), n(raft.differentialSettlement, MM, 1));
		fact(localize('sub.raftDistortion', "Angular distortion"), typeof raft.angularDistortion === 'number' && raft.angularDistortion > 0 ? localize('sub.raftDistortionValue', "1/{0}", formatNumber(1 / raft.angularDistortion, 0)) : undefined);
		fact(localize('sub.combination', "Combination"), raft.combination);
		if (!raft.points.length) {
			return;
		}
		const switcher = append(section, $('.sa-segmented.sub-heat-switch', { role: 'tablist' }));
		for (const [quantity, label] of [['pressure', localize('sub.heatPressureShort', "Contact pressure")], ['settlement', localize('sub.heatSettlementShort', "Settlement")]] as const) {
			const button = append(switcher, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }, label));
			button.classList.toggle('active', this.raftQuantity === quantity);
			button.setAttribute('aria-selected', String(this.raftQuantity === quantity));
			this.viewDisposables.add(addDisposableListener(button, EventType.CLICK, () => {
				this.raftQuantity = quantity;
				this.renderView();
			}));
		}
		const chart = append(section, $('.sub-heat-chart'));
		const width = Math.min(640, Math.max(320, this.viewElement.clientWidth - 80));
		const outline = foundationOutlines(foundation, this.context).flat();
		const spanX = outline.length ? Math.max(...outline.map(p => p[0])) - Math.min(...outline.map(p => p[0])) : 1;
		const spanY = outline.length ? Math.max(...outline.map(p => p[1])) - Math.min(...outline.map(p => p[1])) : 1;
		const height = Math.round(Math.max(160, Math.min(width * 0.75, (width - 48) * spanY / Math.max(spanX, 1) + 48)));
		const range = renderRaftHeatMap(chart, foundation, raft, this.context, this.raftQuantity, { width, height });
		if (range) {
			const unit = this.raftQuantity === 'pressure' ? localize('sub.unit.kpa', "kPa") : MM;
			const scale = append(chart, $('.sub-heat-scale'));
			append(scale, $('span', undefined, `${formatNumber(range.min, this.raftQuantity === 'pressure' ? 0 : 1)} ${unit}`));
			const ramp = append(scale, $('span.sub-heat-ramp'));
			for (let i = 0; i < HEAT_STEPS; i++) {
				append(ramp, $(`span.sub-heat-${i}`));
			}
			append(scale, $('span', undefined, `${formatNumber(range.max, this.raftQuantity === 'pressure' ? 0 : 1)} ${unit}`));
		}
	}

	private renderPileCapacities(view: HTMLElement, report: ISubstructureReport): void {
		if (!report.pileCapacities.length) {
			return;
		}
		const document = this.document;
		const method = document?.design.pileCapacity === 'bnbcSpt' ? localize('sub.capacityBnbc', "BNBC 2020 SPT method") : localize('sub.capacitySoil', "per-layer skin friction and end bearing of the soil report");
		const section = this.resultSection(view, localize('sub.pileCapacities', "Pile capacity"), localize('sub.pileCapacitiesDetail', "per pile type and borehole · {0}", method));
		const kn = localize('sub.unit.kn', "kN");
		const table = append(section, $('table.sub-table.sub-result-table'));
		this.tableHead(table, [
			{ label: localize('sub.pileTypeShort', "Pile type"), width: 72 }, { label: localize('sub.borehole', "Borehole"), width: 84 }, { label: localize('sub.skin', "Skin friction"), unit: kn, numeric: true, width: 96 },
			{ label: localize('sub.base', "End bearing"), unit: kn, numeric: true, width: 96 }, { label: localize('sub.ultimate', "Ultimate"), unit: kn, numeric: true, width: 84 },
			{ label: localize('sub.allowableCompression', "Allowable compression"), unit: kn, numeric: true, width: 120 }, { label: localize('sub.allowableUplift', "Allowable uplift"), unit: kn, numeric: true, width: 100 }, { label: localize('sub.note', "Note"), width: 260 },
		]);
		const body = append(table, $('tbody'));
		const dash = (v: number | undefined) => typeof v === 'number' ? formatNumber(v, 0) : '—';
		for (const row of report.pileCapacities) {
			const tr = append(body, $('tr'));
			append(tr, $('td', undefined, row.pileType));
			append(tr, $('td', undefined, row.borehole ?? '—'));
			append(tr, $('td.number', undefined, dash(row.skin)));
			append(tr, $('td.number', undefined, dash(row.base)));
			append(tr, $('td.number', undefined, dash(row.ultimate)));
			append(tr, $('td.number', undefined, dash(row.compression)));
			append(tr, $('td.number', undefined, dash(row.uplift)));
			append(tr, $('td.sub-wrap', undefined, row.note ?? row.method ?? ''));
		}
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
			// Before the file is open (opening waits on the backend, busy on a big model): loading.
			appendPropertyNote(panel, this.parseError ?? (this.model ? localize('sub.propsNone', "No substructure.") : localize('sub.propsLoading', "Opening the substructure…")));
			return;
		}
		this.renderingProperties = true;
		let paths: string[] = [];
		try {
			const foundation = this.foundation;
			if (this.selectedPiles.size) {
				this.renderPileProperties(panel, document);
				paths = document.piles.flatMap((p, i) => this.selectedPiles.has(p.id) ? [`piles.${i}.`] : []);
			} else if (this.gridSelected) {
				this.renderPileGridProperties(panel, document);
				paths = ['pileGrid.'];
			} else if (foundation) {
				this.renderFoundationProperties(panel, document, foundation);
				paths = [`foundations.${this.selectedFoundations[0]}.`];
			} else if (this.selectedTieBeam !== undefined && document.tieBeams[this.selectedTieBeam]) {
				this.renderTieProperties(panel, document, document.tieBeams[this.selectedTieBeam]);
				paths = [`tieBeams.${this.selectedTieBeam}.`];
			} else if (this.selectedFoundations.length > 1) {
				appendPropertyHeading(panel, localize('sub.manySelected', "{0} foundations", this.selectedFoundations.length));
				const ids = this.selectedFoundations.map(i => document.foundations[i]?.id).filter((id): id is string => !!id);
				append(panel, $('.sub-selected-list', undefined, ids.join(', ')));
				// The next step that fits the selection (N-U11): overlapping footings are combined first.
				const overlapping = ids.some(id => this.report?.foundations.find(r => r.id === id)?.checks.some(c => c.name === CLEARANCE_CHECK && !c.ok));
				appendPropertyNote(panel, overlapping
					? localize('sub.overlapHint', "Some of them overlap: Size Footings with them selected makes one combined footing, or Add Raft replaces them with a raft.")
					: this.selectedFoundations.length === 2
						? localize('sub.tieHint', "Add a tie beam between them with the tie beam button in the toolbar, or Delete removes both.")
						: localize('sub.manyHint', "Size Footings, Add Raft and Delete act on all of them. Select exactly two to tie them."));
			} else if (this.selectedColumns.size) {
				this.renderColumnProperties(panel, document);
			} else {
				if (this.tool === 'pile') {
					this.renderPileToolProperties(panel, document);
				}
				this.renderDesignProperties(panel, document);
				paths = ['pileTypes.', 'tieBeams.', 'foundations.', 'piles.', 'pileGrid.'];
			}
		} finally {
			this.renderingProperties = false;
		}
		const shown = this.problems.filter(p => paths.some(prefix => p.path.startsWith(prefix)));
		if (shown.length) {
			appendPropertyHeading(panel, localize('sub.problems', "Problems ({0})", shown.length));
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
		const wrapper = $('.sub-prop-control');
		append(wrapper, control);
		if (unit) {
			append(wrapper, $('span.sub-prop-unit', undefined, unit));
		}
		const row = appendPropertyRow(panel, label, wrapper);
		row.classList.add('sub-prop-row');
		if (title) {
			row.title = title;
		}
	}

	private fieldRow(panel: HTMLElement, field: IFieldSpec, value: unknown, store: (value: number | string | undefined) => void, key: string, placeholder?: string): void {
		this.propertyRow(panel, field.label, this.textInput(field, value, store, key, placeholder), field.unit, field.title);
	}

	private renderFoundationProperties(panel: HTMLElement, document: ISubstructure, foundation: IFoundation): void {
		const index = this.selectedFoundations[0];
		const path = (field: string) => `foundations.${index}.${field}`;
		appendPropertyHeading(panel, localize('sub.foundationHeading', "{0} {1}", foundationTypeLabel(foundation.type), foundation.id));
		this.fieldRow(panel, F.id, foundation.id, value => this.renameFoundation(foundation, String(value ?? '')), path('id'));
		this.propertyRow(panel, localize('sub.f.type', "Type"), this.selectInput(FOUNDATION_TYPES.map(t => ({ value: t, label: foundationTypeLabel(t) })), foundation.type, value => this.setType(foundation, value as FoundationType), path('type'), localize('sub.f.type', "Type")));
		this.propertyRow(panel, localize('sub.f.columns', "Columns"), this.columnsInput(foundation, path('columns')), undefined, localize('sub.f.columnsTitle', "Ids of the building model's columns it carries, separated by commas"));

		appendPropertyHeading(panel, localize('sub.geometry', "Geometry"));
		const rectangular = foundation.type !== 'raft' && foundation.type !== 'strip';
		if (rectangular) {
			const centroid = foundationCenter({ ...foundation, center: undefined }, this.context);
			const center = foundation.center;
			for (const [field, axis] of [[F.x, 0], [F.y, 1]] as const) {
				this.fieldRow(panel, field, center?.[axis], value => {
					if (typeof value === 'number') {
						const next: Point = foundation.center ? [...foundation.center] as Point : centroid ? [...centroid] as Point : [0, 0];
						next[axis] = value;
						foundation.center = next;
					} else {
						delete foundation.center;
					}
					this.changed(false);
				}, path(`center.${axis}`), centroid ? formatNumber(centroid[axis] / 1000, 3) : undefined);
			}
			this.fieldRow(panel, F.rotation, foundation.rotation, value => this.setField(foundation, 'rotation', value), path('rotation'), '0');
			this.fieldRow(panel, F.length, foundation.length, value => this.setField(foundation, 'length', value), path('length'));
		}
		if (foundation.type !== 'raft') {
			this.fieldRow(panel, F.width, foundation.width, value => this.setField(foundation, 'width', value), path('width'));
		}
		this.fieldRow(panel, F.thickness, foundation.thickness, value => this.setField(foundation, 'thickness', value), path('thickness'));
		if (foundation.type === 'isolated') {
			this.renderFootingSection(panel, foundation, path);
		}
		this.fieldRow(panel, F.foundingLevel, foundation.foundingLevel, value => this.setField(foundation, 'foundingLevel', value), path('foundingLevel'), formatNumber(defaultFoundingLevel(this.context) / 1000, 3));
		if (foundation.type === 'raft') {
			this.renderRaftOutline(panel, foundation, path);
		}
		if (foundation.type === 'strip') {
			appendPropertyRow(panel, localize('sub.path', "Path"), localize('sub.outlinePoints', "{0} points", foundation.path?.length ?? 0));
		}

		if (foundation.type === 'pileCap') {
			appendPropertyHeading(panel, localize('sub.pilesHeading', "Piles"));
			const capType = capPileType(foundation, document);
			this.propertyRow(panel, localize('sub.f.pileType', "Pile type"), this.selectInput(document.pileTypes.map(p => ({ value: p.id, label: `${p.id} · ${pileKindLabel(p.kind)} ${formatNumber(p.diameter, 0)} mm` })), capType?.id ?? '', value => this.setPileType(foundation, value), path('pileType'), localize('sub.f.pileType', "Pile type"), true));
			const count = foundation.piles?.length ?? 0;
			const layouts = PILE_LAYOUTS.map(n => ({ value: String(n), label: localize('sub.layoutOptionK', "{0} piles at {1} D under its columns", n, formatNumber(this.spacingFactor, 2)) }));
			const layoutSelect = this.selectInput(layouts, '', value => {
				const pile = capType ?? this.pileType();
				if (!pile || !value) {
					return;
				}
				applyPileLayout(document, this.context, foundation, pile, Number(value), this.spacingFactor);
				this.changed(true);
			}, path('piles'), localize('sub.f.layout', "Layout"), true);
			this.propertyRow(panel, localize('sub.f.relayout', "Lay out again"), layoutSelect, undefined, localize('sub.layoutTitleK', "Replaces its piles by a standard group at k diameters centre to centre (k of the pile tools, at least 2.5: BNBC 2020 Part 6 Secs 3.10.1.19, 3.10.1.30), centred on its columns, and fits the cap 150 mm beyond the piles"));
			appendPropertyRow(panel, localize('sub.f.piles', "Piles"), count ? `${count} · ${(foundation.piles ?? []).join(', ')}` : '0');
			const center = foundation.center;
			const columns = this.context.columns.filter(c => foundation.columns?.includes(c.id));
			if (center && columns.length) {
				const cx = columns.reduce((s, c) => s + c.x, 0) / columns.length;
				const cy = columns.reduce((s, c) => s + c.y, 0) / columns.length;
				appendPropertyRow(panel, localize('sub.f.eccentricity', "Columns off its centre"), localize('sub.eccValue', "{0}, {1} mm", formatNumber(cx - center[0], 0), formatNumber(cy - center[1], 0)));
				appendPropertyNote(panel, localize('sub.eccNote', "The cap is placed over its piles; the design carries the columns' eccentricity (P · e) into the pile loads, rigid cap: P/n ± M x/Σx² both ways."));
			}
		}

		appendPropertyHeading(panel, localize('sub.material', "Material and reinforcement"));
		this.propertyRow(panel, localize('sub.f.material', "Concrete"), this.materialInput(foundation.material, value => this.setField(foundation, 'material', value), path('material')));
		// A new reinforcement starts with the bar material and cover the backend needs.
		const reinforcement = () => foundation.reinforcement ??= { ...(this.context.barMaterial ? { material: this.context.barMaterial } : {}), cover: 75 };
		const bars = this.context.barMaterials ?? [];
		const barMaterial = foundation.reinforcement?.material;
		this.propertyRow(panel, localize('sub.f.barMaterial', "Bars"), this.selectInput(bars.map(m => ({ value: m, label: m })), barMaterial ?? '', value => {
			if (value) {
				reinforcement().material = value;
				this.changed(true);
			}
		}, path('reinforcement.material'), localize('sub.f.barMaterial', "Bars"), !barMaterial), undefined, localize('sub.f.barMaterialTitle', "The rebar material of the bars (03 Materials)"));
		this.fieldRow(panel, F.cover, foundation.reinforcement?.cover, value => {
			if (typeof value === 'number') {
				reinforcement().cover = value;
			} else if (foundation.reinforcement) {
				delete foundation.reinforcement.cover;
			}
			this.changed(false);
		}, path('reinforcement.cover'), '75');
		const meshLabels: Record<MeshKey, string> = {
			bottomX: localize('sub.f.bottomX', "Bottom x"), bottomY: localize('sub.f.bottomY', "Bottom y"),
			topX: localize('sub.f.topX', "Top x"), topY: localize('sub.f.topY', "Top y"),
		};
		for (const key of MESH_KEYS) {
			const input = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': meshLabels[key], placeholder: key.startsWith('top') ? localize('sub.none', "none") : '' });
			input.value = formatMesh(foundation.reinforcement?.[key]);
			this.propertiesDisposables.add(addDisposableListener(input, EventType.INPUT, () => {
				const parsed = parseMesh(input.value);
				this.markInvalid(input, parsed.error);
				if (parsed.error) {
					return;
				}
				if (parsed.value) {
					reinforcement()[key] = parsed.value;
				} else if (foundation.reinforcement) {
					delete foundation.reinforcement[key];
				}
				this.changed(false);
			}));
			this.propertiesDisposables.add(addDisposableListener(input, EventType.BLUR, () => this.flush()));
			this.propertyInputs.set(path(`reinforcement.${key}`), input);
			this.propertyRow(panel, meshLabels[key], input, localize('sub.unit.meshUnit', "mm@mm"), localize('sub.meshTitle', "Bar diameter @ spacing in mm, e.g. 12@150"));
		}
		appendPropertyHeading(panel, localize('sub.notesHeading', "Notes"));
		this.fieldRow(panel, F.note, foundation.note, value => this.setField(foundation, 'note', value), path('note'));

		const result = this.resultOf(foundation);
		if (result) {
			appendPropertyHeading(panel, localize('sub.resultsHeading', "Design"));
			if (typeof result.utilisation === 'number') {
				const value = $(`span.sub-util-value.band-${utilisationBand(result.utilisation)}`, undefined, formatUtilisation(result.utilisation));
				appendPropertyRow(panel, localize('sub.f.utilisation', "Utilisation"), value);
			}
			const governing = governingCheck(result);
			if (governing) {
				appendPropertyRow(panel, localize('sub.governing', "Governing check"), governing.name);
			}
			if (typeof result.pressure?.max === 'number') {
				appendPropertyRow(panel, localize('sub.pressure', "Bearing pressure"), typeof result.pressure.allowable === 'number'
					? localize('sub.pressureQa', "{0} kPa (qa {1})", formatNumber(result.pressure.max, 0), formatNumber(result.pressure.allowable, 0))
					: localize('sub.kpaValue', "{0} kPa", formatNumber(result.pressure.max, 0)));
			}
		}
	}

	/**
	 * A rectangular raft's outline as its plan size and centre (edits rewrite the four corners);
	 * another outline as its points, edited in the text.
	 */
	private renderRaftOutline(panel: HTMLElement, foundation: IFoundation, path: (field: string) => string): void {
		const outline = foundation.outline ?? [];
		const xs = [...new Set(outline.map(p => p[0]))];
		const ys = [...new Set(outline.map(p => p[1]))];
		if (outline.length !== 4 || xs.length !== 2 || ys.length !== 2) {
			appendPropertyRow(panel, localize('sub.outline', "Outline"), localize('sub.outlinePoints', "{0} points", outline.length));
			appendPropertyNote(panel, localize('sub.outlineText', "Not a rectangle along the axes: edit its points with Open as Text (… menu)."));
			return;
		}
		const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
		const write = () => {
			foundation.outline = [[box.x0, box.y0], [box.x1, box.y0], [box.x1, box.y1], [box.x0, box.y1]];
			this.changed(false);
		};
		const lengthX: IFieldSpec = { key: 'outlineX', label: localize('sub.f.raftX', "Length along X"), unit: MM, kind: 'number', min: 1000 };
		const lengthY: IFieldSpec = { key: 'outlineY', label: localize('sub.f.raftY', "Length along Y"), unit: MM, kind: 'number', min: 1000 };
		this.fieldRow(panel, lengthX, box.x1 - box.x0, value => {
			if (typeof value === 'number') {
				const middle = (box.x0 + box.x1) / 2;
				[box.x0, box.x1] = [middle - value / 2, middle + value / 2];
				write();
			}
		}, path('outline.x'));
		this.fieldRow(panel, lengthY, box.y1 - box.y0, value => {
			if (typeof value === 'number') {
				const middle = (box.y0 + box.y1) / 2;
				[box.y0, box.y1] = [middle - value / 2, middle + value / 2];
				write();
			}
		}, path('outline.y'));
		for (const [field, axis] of [[F.x, 0], [F.y, 1]] as const) {
			this.fieldRow(panel, field, axis === 0 ? (box.x0 + box.x1) / 2 : (box.y0 + box.y1) / 2, value => {
				if (typeof value !== 'number') {
					return;
				}
				if (axis === 0) {
					const half = (box.x1 - box.x0) / 2;
					[box.x0, box.x1] = [value - half, value + half];
				} else {
					const half = (box.y1 - box.y0) / 2;
					[box.y0, box.y1] = [value - half, value + half];
				}
				write();
			}, path(`outline.center.${axis}`));
		}
	}

	private renderTieProperties(panel: HTMLElement, document: ISubstructure, tie: ITieBeam): void {
		const index = this.selectedTieBeam!;
		const path = (field: string) => `tieBeams.${index}.${field}`;
		appendPropertyHeading(panel, localize('sub.tieHeading', "Tie beam {0}", tie.id));
		this.fieldRow(panel, F.id, tie.id, value => {
			tie.id = String(value ?? '');
			this.changed(false);
		}, path('id'));
		const options = document.foundations.map(f => ({ value: f.id, label: f.id }));
		for (const end of ['from', 'to'] as const) {
			const label = end === 'from' ? localize('sub.f.from', "From") : localize('sub.f.to', "To");
			this.propertyRow(panel, label, this.selectInput(options, tie[end], value => {
				tie[end] = value;
				this.changed(true);
			}, path(end), label));
		}
		this.propertyRow(panel, localize('sub.f.beamType', "Beam type"), this.beamTypeInput(tie, path('type')));
		this.fieldRow(panel, F.level, tie.level, value => this.setTieLevel(tie, value), path('level'), this.tieLevelPlaceholder(tie));
		const span = this.tieSpan(tie);
		if (span) {
			appendPropertyRow(panel, localize('sub.f.span', "Span"), localize('sub.mValue', "{0} m", span));
		}
	}

	private renderColumnProperties(panel: HTMLElement, document: ISubstructure): void {
		const columns = this.pickedColumns;
		appendPropertyHeading(panel, columns.length === 1 ? localize('sub.columnHeading', "Column {0}", columns[0].id) : localize('sub.columnsHeading', "{0} columns", columns.length));
		if (columns.length === 1) {
			const column = columns[0];
			appendPropertyRow(panel, localize('sub.f.section', "Section"), column.circle ? localize('sub.circleSection', "Ø{0} mm", formatNumber(column.xDim, 0)) : localize('sub.rectSection', "{0} × {1} mm", formatNumber(column.xDim, 0), formatNumber(column.yDim, 0)));
			appendPropertyRow(panel, localize('sub.f.position', "Position"), localize('sub.positionValue', "{0}, {1} m", formatNumber(column.x / 1000, 3), formatNumber(column.y / 1000, 3)));
			const on = document.foundations.find(f => f.columns?.includes(column.id));
			appendPropertyRow(panel, localize('sub.f.foundation', "Foundation"), on?.id ?? localize('sub.noneYet', "none yet"));
		} else {
			append(panel, $('.sub-selected-list', undefined, columns.map(c => c.id).join(', ')));
		}
		appendPropertyNote(panel, columns.length > 1
			? localize('sub.columnsHint', "Add a combined footing, one pile cap or a raft under them with the toolbar buttons.")
			: localize('sub.columnHint', "Add a footing or a pile cap under it with the toolbar buttons; Shift+click more columns for a combined footing."));
		appendPropertyHeading(panel, localize('sub.pileGroupHeading', "Pile group"));
		this.renderPileToolFields(panel, document);
		const place = this.propertiesDisposables.add(new Button(panel, { ...defaultButtonStyles, secondary: true }));
		place.label = columns.length > 1 ? localize('sub.placeGroups', "Place a Group under Each") : localize('sub.placeGroup', "Place Pile Group");
		place.element.classList.add('sub-prop-button');
		this.propertiesDisposables.add(place.onDidClick(() => this.placeGroups()));
		appendPropertyNote(panel, localize('sub.groupNote', "Standard groups of 2 to 6 piles at k · D centre to centre (BNBC 2020 Part 6: at least 2.5 D and 750 mm), centred under the column and turned with the pile grid. Then select the piles and the column and Make Pile Cap; the cap need not be centred on the column."));
	}

	/** The pile tools' settings: the pile type placed, the group's pile count and the spacing factor k. */
	private renderPileToolFields(panel: HTMLElement, document: ISubstructure): void {
		const types = document.pileTypes.map(p => ({ value: p.id, label: `${p.id} · ${pileKindLabel(p.kind)} ${formatNumber(p.diameter, 0)} mm` }));
		this.propertyRow(panel, localize('sub.f.pileType', "Pile type"), this.selectInput(types, this.placeType ?? document.pileTypes[0]?.id ?? '', value => {
			this.placeType = value || undefined;
		}, 'tool.pileType', localize('sub.f.pileType', "Pile type"), !types.length), undefined, localize('sub.toolTypeTitle', "The pile type placed; a 500 mm bored pile type is added when there is none"));
		this.propertyRow(panel, localize('sub.f.groupCount', "Piles in a group"), this.selectInput(PILE_GROUPS.map(n => ({ value: String(n), label: String(n) })), String(this.groupCount), value => {
			this.groupCount = Number(value) || 4;
		}, 'tool.groupCount', localize('sub.f.groupCount', "Piles in a group")));
		this.fieldRow(panel, F.spacingFactor, this.spacingFactor, value => {
			if (typeof value === 'number' && value >= MIN_SPACING_FACTOR) {
				this.spacingFactor = value;
			}
		}, 'tool.spacingFactor', formatNumber(DEFAULT_SPACING_FACTOR, 1));
	}

	private renderPileToolProperties(panel: HTMLElement, document: ISubstructure): void {
		appendPropertyHeading(panel, localize('sub.pileToolHeading', "Placing piles"));
		this.renderPileToolFields(panel, document);
		appendPropertyNote(panel, localize('sub.pileToolNote', "Click a pile grid crossing (or a column, or any point: it snaps to 50 mm) to place a pile; drag a box to place one at every crossing inside it. Select piles (click, Shift+click or drag a box with the select tool), drag them to move, arrow keys nudge 50 mm."));
	}

	/** One pile, or several: mark, type, position, the cap it is under. */
	private renderPileProperties(panel: HTMLElement, document: ISubstructure): void {
		const piles = document.piles.filter(p => this.selectedPiles.has(p.id));
		const caps = pileCaps(document);
		const types = document.pileTypes.map(p => ({ value: p.id, label: `${p.id} · ${pileKindLabel(p.kind)} ${formatNumber(p.diameter, 0)} mm` }));
		if (piles.length === 1) {
			const pile = piles[0];
			const index = document.piles.indexOf(pile);
			const path = (field: string) => `piles.${index}.${field}`;
			appendPropertyHeading(panel, localize('sub.pileHeading', "Pile {0}", pile.id));
			this.fieldRow(panel, { ...F.id, label: localize('sub.f.mark', "Mark") }, pile.id, value => this.renamePile(pile, String(value ?? '')), path('id'));
			this.propertyRow(panel, localize('sub.f.pileType', "Pile type"), this.selectInput(types, pile.type, value => {
				pile.type = value;
				this.changed(true);
			}, path('type'), localize('sub.f.pileType', "Pile type")));
			this.fieldRow(panel, F.pileX, pile.position[0], value => this.setPilePosition(pile, 0, value), path('position.0'));
			this.fieldRow(panel, F.pileY, pile.position[1], value => this.setPilePosition(pile, 1, value), path('position.1'));
			appendPropertyRow(panel, localize('sub.f.cap', "Cap"), caps.get(pile.id) ?? localize('sub.noCap', "none"));
		} else {
			appendPropertyHeading(panel, localize('sub.pilesSelected', "{0} piles", piles.length));
			append(panel, $('.sub-selected-list', undefined, piles.map(p => p.id).join(', ')));
			const kinds = [...new Set(piles.map(p => p.type))];
			this.propertyRow(panel, localize('sub.f.pileType', "Pile type"), this.selectInput(types, kinds.length === 1 ? kinds[0] : '', value => {
				for (const pile of piles) {
					pile.type = value;
				}
				this.changed(true);
			}, 'piles.type', localize('sub.f.pileType', "Pile type"), kinds.length !== 1));
			const capped = [...new Set(piles.map(p => caps.get(p.id)).filter((c): c is string => !!c))];
			appendPropertyRow(panel, localize('sub.f.caps', "Caps"), capped.length ? capped.join(', ') : localize('sub.noCap', "none"));
		}
		if (this.selectedColumns.size) {
			appendPropertyRow(panel, localize('sub.f.columns', "Columns"), [...this.selectedColumns].join(', '));
		}
		appendPropertyNote(panel, piles.some(p => caps.has(p.id))
			? localize('sub.pilesCappedHint', "Drag the piles (or nudge them with the arrow keys) to move them: their cap fits round them again. Delete takes them out of their cap.")
			: localize('sub.pilesFreeHint', "Make Pile Cap forms a cap over them (Shift+click the column it carries, or it takes the free columns inside it). Its centre is the group's: it may be off the column, and the design carries that eccentricity."));
	}

	/** The pile grid: its origin, rotation and the spacings and labels of its lines. */
	private renderPileGridProperties(panel: HTMLElement, document: ISubstructure): void {
		appendPropertyHeading(panel, localize('sub.pileGridHeading', "Pile grid"));
		const grid = document.pileGrid;
		if (!grid) {
			appendPropertyNote(panel, localize('sub.noPileGrid', "No pile grid. Pile Grid in the toolbar adds one over the columns."));
			return;
		}
		const origin = () => grid.origin ??= [0, 0];
		this.fieldRow(panel, F.originX, grid.origin?.[0] ?? 0, value => {
			if (typeof value === 'number') {
				origin()[0] = value;
				this.changed(false);
			}
		}, 'pileGrid.origin.0');
		this.fieldRow(panel, F.originY, grid.origin?.[1] ?? 0, value => {
			if (typeof value === 'number') {
				origin()[1] = value;
				this.changed(false);
			}
		}, 'pileGrid.origin.1');
		this.fieldRow(panel, F.rotation, grid.rotation, value => {
			grid.rotation = typeof value === 'number' ? value : 0;
			this.changed(false);
		}, 'pileGrid.rotation', '0');
		for (const axis of ['x', 'y'] as const) {
			const label = axis === 'x' ? localize('sub.f.xSpacings', "X spacings") : localize('sub.f.ySpacings', "Y spacings");
			const input = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': label });
			input.value = formatSpacings(grid[axis]);
			this.propertiesDisposables.add(addDisposableListener(input, EventType.INPUT, () => {
				const parsed = parseSpacings(input.value);
				this.markInvalid(input, parsed.error);
				if (parsed.value) {
					const start = Math.min(0, ...grid[axis].map(l => l.position));
					const labels = grid[axis].map(l => l.label);
					grid[axis] = gridLines(axis, parsed.value, start).map((line, i) => ({ ...line, label: labels[i] ?? line.label }));
					this.changed(false);
				}
			}));
			this.propertiesDisposables.add(addDisposableListener(input, EventType.BLUR, () => this.flush()));
			this.propertyInputs.set(`pileGrid.${axis}`, input);
			this.propertyRow(panel, label, input, MM, localize('sub.spacingsTitle', "The distances between the lines, e.g. 4@1500, 2000 (from the origin along the grid's own axis)"));
			const labels = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': localize('sub.f.labels', "Labels") });
			labels.value = grid[axis].map(l => l.label).join(' ');
			this.propertiesDisposables.add(addDisposableListener(labels, EventType.INPUT, () => {
				const names = parseIdList(labels.value);
				grid[axis] = grid[axis].map((line, i) => ({ ...line, label: names[i] ?? line.label }));
				this.changed(false);
			}));
			this.propertiesDisposables.add(addDisposableListener(labels, EventType.BLUR, () => this.flush()));
			this.propertyInputs.set(`pileGrid.${axis}.labels`, labels);
			this.propertyRow(panel, axis === 'x' ? localize('sub.f.xLabels', "X labels") : localize('sub.f.yLabels', "Y labels"), labels);
		}
		appendPropertyRow(panel, localize('sub.f.crossings', "Crossings"), String(grid.x.length * grid.y.length));
		const remove = this.propertiesDisposables.add(new Button(panel, { ...defaultButtonStyles, secondary: true }));
		remove.label = localize('sub.removePileGrid', "Remove Pile Grid");
		remove.element.classList.add('sub-prop-button');
		this.propertiesDisposables.add(remove.onDidClick(() => {
			delete document.pileGrid;
			this.gridSelected = false;
			this.changed(true);
		}));
		appendPropertyNote(panel, localize('sub.pileGridNote', "The piles are set out on their own grid, independent of the building's: Place Piles snaps to its crossings. Removing the grid keeps the piles where they are."));
	}

	private renderDesignProperties(panel: HTMLElement, document: ISubstructure): void {
		appendPropertyHeading(panel, localize('sub.summaryHeading', "Substructure"));
		appendPropertyRow(panel, localize('sub.foundationsHeading', "Foundations"), String(document.foundations.length));
		appendPropertyRow(panel, localize('sub.pileTypes', "Pile types"), String(document.pileTypes.length));
		appendPropertyRow(panel, localize('sub.pilesHeading', "Piles"), String(document.piles.length));
		appendPropertyRow(panel, localize('sub.tieBeams', "Tie beams"), String(document.tieBeams.length));
		const uncovered = uncoveredBases(document, this.context);
		appendPropertyRow(panel, localize('sub.uncovered', "Columns and walls without one"), uncovered.length ? uncovered.join(', ') : localize('sub.noneShort', "none"));

		appendPropertyHeading(panel, localize('sub.designHeading', "Design"));
		const design = document.design;
		this.propertyRow(panel, localize('sub.f.pileCapacity', "Pile capacity"), this.selectInput([
			{ value: 'soilReport', label: localize('sub.capacity.soil', "Soil report (per layer)") },
			{ value: 'bnbcSpt', label: localize('sub.capacity.bnbc', "BNBC SPT equations") },
		], design.pileCapacity ?? 'soilReport', value => {
			design.pileCapacity = value as ISubstructure['design']['pileCapacity'];
			this.changed(true);
		}, 'design.pileCapacity', localize('sub.f.pileCapacity', "Pile capacity")), undefined,
			localize('sub.capacityTitle', "Soil report: skin friction and end bearing per layer from 1 Soil Report. BNBC SPT equations: BNBC 2020 Part 6 Sec 3.10 from the SPT N values."));
		const fs = () => design.factorOfSafety ??= {};
		// The factors the design actually uses, updated as the fields are typed.
		let refreshUsed = () => { };
		// The pile settings only where there are piles; the bearing factor always.
		const piled = document.pileTypes.length > 0 || document.piles.length > 0 || document.foundations.some(f => f.type === 'pileCap');
		for (const field of piled ? [F.pileCompression, F.pileUplift, F.bearing] : [F.bearing]) {
			this.fieldRow(panel, field, design.factorOfSafety?.[field.key], value => {
				if (typeof value === 'number') {
					fs()[field.key] = value;
				} else if (design.factorOfSafety) {
					delete design.factorOfSafety[field.key];
				}
				this.changed(false);
				refreshUsed();
			}, `design.factorOfSafety.${field.key}`, field === F.bearing ? localize('sub.fromSoil', "soil report") : formatNumber(PILE_FACTOR_OF_SAFETY, 1));
		}
		if (!piled) {
			this.fieldRow(panel, F.raftMeshSize, design.raftMeshSize, value => this.setDesign('raftMeshSize', value), 'design.raftMeshSize', String(RAFT_MESH_SIZE));
			this.fieldRow(panel, F.springs, typeof design.springsFrom === 'number' ? design.springsFrom : undefined, value => this.setDesign('springsFrom', value), 'design.springsFrom', localize('sub.fromSoil', "soil report"));
			this.raftSpringsRow(panel, design);
			appendPropertyNote(panel, localize('sub.designNoteNoPiles', "Empty values use the soil report's bearing factor and subgrade modulus and a 500 mm raft mesh. The pile settings appear once there is a pile cap."));
			return;
		}
		const loadTestLabel = localize('sub.f.loadTest', "Pile load test at the site");
		this.propertyRow(panel, loadTestLabel, this.selectInput([
			{ value: 'no', label: localize('sub.loadTest.no', "No") },
			{ value: 'yes', label: localize('sub.loadTest.yes', "Yes") },
		], design.factorOfSafety?.pileLoadTest === true ? 'yes' : 'no', value => {
			if (value === 'yes') {
				fs().pileLoadTest = true;
			} else if (design.factorOfSafety) {
				delete design.factorOfSafety.pileLoadTest;
			}
			this.changed(true);
		}, 'design.factorOfSafety.pileLoadTest', loadTestLabel), undefined,
			localize('sub.loadTestTitle', "BNBC 2020 Part 6 Sec 3.10.1.18 (bored piles: Sec 3.10.4.10): the overall factor of safety in compression is at least 3.0 unless the design rests on a load test at the site with good quality control, then at least 2.0."));
		const usedValue = $('span');
		appendPropertyRow(panel, localize('sub.fsUsed', "FS used (compression / uplift)"), usedValue);
		const usedNote = appendPropertyNote(panel, '');
		refreshUsed = () => {
			const used = pileFactorsUsed(design);
			usedValue.textContent = `${formatNumber(used.compression, 1)} / ${formatNumber(used.uplift, 1)}`;
			usedNote.textContent = used.raised === 'loadTest'
				? localize('sub.fsRaisedLoadTest', "Compression FS raised from {0} to {1}: BNBC 2020 Part 6 Sec 3.10.1.18 asks at least 3.0 unless the design rests on a load test at the site.", formatNumber(used.given, 1), formatNumber(used.compression, 1))
				: used.raised === 'spt' ? localize('sub.fsRaisedSpt', "FS raised to {0} with the BNBC SPT equations.", formatNumber(used.compression, 1)) : '';
			usedNote.hidden = !used.raised;
		};
		refreshUsed();
		this.fieldRow(panel, F.raftMeshSize, design.raftMeshSize, value => this.setDesign('raftMeshSize', value), 'design.raftMeshSize', String(RAFT_MESH_SIZE));
		this.fieldRow(panel, F.springs, typeof design.springsFrom === 'number' ? design.springsFrom : undefined, value => this.setDesign('springsFrom', value), 'design.springsFrom', localize('sub.fromSoil', "soil report"));
		this.raftSpringsRow(panel, design);
		appendPropertyNote(panel, localize('sub.designNote', "Empty values use the defaults: pile factors of safety 2.5 (BNBC 2020 Part 6 Table 6.3.10a, permanent structure, normal control; in compression raised to 3.0 without a load test at the site), the soil report's bearing factor and subgrade modulus, a 500 mm raft mesh."));
	}

	private raftSpringsRow(panel: HTMLElement, design: ISubstructureDesign): void {
		const label = localize('sub.f.raftSprings', "Raft springs");
		this.propertyRow(panel, label, this.selectInput([
			{ value: 'noTension', label: localize('sub.raftSprings.noTension', "No tension (iterative)") },
			{ value: 'linear', label: localize('sub.raftSprings.linear', "Linear") },
		], design.raftSprings ?? 'noTension', value => this.setDesign('raftSprings', value === 'noTension' ? undefined : value), 'design.raftSprings', label), undefined,
			localize('sub.raftSpringsTitle', "No tension: where the raft lifts off, the soil carries nothing (solved iteratively, in load steps if one step does not converge). Linear: the springs may pull."));
	}

	private setDesign(key: string, value: number | string | undefined): void {
		const design = this.document?.design;
		if (!design) {
			return;
		}
		if (value === undefined) {
			delete design[key];
		} else {
			design[key] = value;
		}
		this.changed(false);
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
		if (!document.foundations.length) {
			frame.setStatus({ text: this.context.columns.length ? localize('sub.statusEmpty', "No foundations yet · {0} columns on the base level", this.context.columns.length) : localize('sub.statusNoColumns', "No foundations yet.") });
			return;
		}
		const state = this.checkState;
		const parts = [substructureSummary(document, state ? this.report : undefined, state)];
		if (state?.stale && this.input?.isDirty()) {
			parts.push(localize('sub.statusUnsaved', "save to check the edits"));
		} else if (state?.stale && this.busy.has('report')) {
			parts.push(localize('sub.statusRechecking', "checking again…"));
		}
		if (this.reportState === 'missing') {
			parts.push(localize('sub.statusNoBackend', "checks need the backend"));
		} else if (this.reportState === 'error') {
			parts.push(localize('sub.statusFailed', "checks could not be computed"));
		}
		const uncovered = uncoveredBases(document, this.context).length;
		if (uncovered) {
			parts.push(uncovered === 1 ? localize('sub.statusUncoveredOne', "1 column or wall without a foundation") : localize('sub.statusUncovered', "{0} columns or walls without a foundation", uncovered));
		}
		const errors = this.problems.filter(p => p.severity === 'error').length;
		const failed = (state?.failed ?? 0) > 0;
		const incomplete = !!state && state.status !== 'pass';
		const status: IEditorFrameStatus = {
			text: parts.join(' · '),
			severity: errors || failed ? 'error' : this.problems.length || uncovered || incomplete || this.reportState === 'error' ? 'warning' : undefined,
			busy: this.reportState === 'computing' || this.busy.has('report'),
			link: this.problems.length ? {
				label: localize('sub.statusProblems', "{0} problem(s)", this.problems.length),
				run: () => this.revealFirstProblem(),
			} : this.reportState === 'ok' && this.view !== 'results' ? {
				label: localize('sub.statusShowResults', "Results"),
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
		const match = /^(?<list>foundations|tieBeams|pileTypes|piles|pileGrid)\.(?<index>\d+)?/.exec(problem.path);
		this.clearSelection();
		if (match?.groups?.list === 'piles') {
			const pile = this.document?.piles[Number(match.groups.index)];
			if (pile) {
				this.selectedPiles = new Set([pile.id]);
			}
			this.view = 'plan';
		} else if (match?.groups?.list === 'pileGrid') {
			this.gridSelected = true;
			this.view = 'plan';
		} else if (match?.groups?.list === 'foundations') {
			this.selectedFoundations = [Number(match.groups.index)];
		} else if (match?.groups?.list === 'tieBeams') {
			this.selectedTieBeam = Number(match.groups.index);
		} else {
			this.view = 'data';
		}
		this.frame.setPropertiesVisible(true);
		this.render();
		(this.propertyInputs.get(problem.path) ?? this.inputs.get(problem.path))?.focus();
	}
}
