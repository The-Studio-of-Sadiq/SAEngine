/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import '../../saengineLibrary/browser/media/modelEditors.css';
import './media/substructureEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isHTMLInputElement } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
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
import { INotificationService } from '../../../../platform/notification/common/notification.js';
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
import { formatField, formatNumber, IFieldSpec, parseField } from '../../saengineSoil/browser/soilDocument.js';
import {
	applyPileLayout, applyProposal, carriedAlready, checkSubstructure, defaultFoundingLevel, EMPTY_CONTEXT, formatMesh, formatUtilisation, foundationCenter, foundationOutlines, foundationSize, foundationTypeLabel, FOUNDATION_TYPES, FoundationType, governingCheck, IColumnBase, IFoundation, IFoundationResult, IPileType, ISiteContext, ISiteTexts,
	ISizingProposal, ISubstructure, ISubstructureMigration, ISubstructureProblem, ISubstructureReport, ISubstructureRequest, ITieBeam, importFoundations, maxPressure, MESH_KEYS, MeshKey, newFooting, newPileCap, newPileType, newRaft, newTieBeam, parseIdList, parseMesh, parseSubstructure, PILE_FACTOR_OF_SAFETY, pileFactorsUsed, PILE_KINDS, PILE_LAYOUTS,
	pileKindLabel, Point, proposalFor, RAFT_MESH_SIZE, readSiteContext, readSizingProposal, readSubstructureReport, serializeSubstructure, SUBSTRUCTURE_ENSURE_COMMAND, SUBSTRUCTURE_MIGRATE_COMMAND, SUBSTRUCTURE_REPORT_COMMAND, SUBSTRUCTURE_SIZE_COMMAND, SUBSTRUCTURE_SUMMARY_FILE, substructureSummary, substructureSummaryFile, uncoveredColumns, utilisationBand,
} from './substructureDocument.js';
import { SubstructureEditorInput } from './substructureEditorInput.js';
import { HEAT_STEPS, renderPlan, renderRaftHeatMap } from './substructurePlan.js';

type View = 'plan' | 'data' | 'results';

const VIEWS: readonly { readonly view: View; readonly label: string; readonly icon: ThemeIcon }[] = [
	{ view: 'plan', label: localize('sub.viewPlan', "Plan"), icon: Codicon.symbolStructure },
	{ view: 'data', label: localize('sub.viewData', "Data"), icon: Codicon.table },
	{ view: 'results', label: localize('sub.viewResults', "Results"), icon: Codicon.graphLine },
];

/** The state of the design report: not asked yet, being computed, computed, or no backend / failed. */
type ReportState = 'idle' | 'computing' | 'ok' | 'missing' | 'error';

/** The parts the plan is drawn against, by the key of {@link ISiteTexts}. */
const SITE_PARTS: readonly (readonly [keyof ISiteTexts, string])[] = [
	['bim', 'bim'], ['objects', 'objects'], ['floorPlan', 'floorPlan'], ['settings', 'settings'], ['soil', 'soil'], ['materials', 'materials'],
];

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
	diameter: { key: 'diameter', label: localize('sub.f.diameter', "Diameter"), unit: MM, kind: 'number', min: 1, required: true, width: 80 },
	pileLength: { key: 'length', label: localize('sub.f.pileLength', "Length"), unit: M, kind: 'length', min: 0.001, required: true, width: 72 },
	level: { key: 'level', label: localize('sub.f.level', "Level"), unit: M, kind: 'length', title: localize('sub.f.levelTitle', "Top of the tie beam; the foundations' top when empty"), width: 72 },
	pileCompression: { key: 'pileCompression', label: localize('sub.f.fsCompression', "FS pile compression"), kind: 'number', min: 1, max: 10, title: localize('sub.f.fsCompressionTitle', "BNBC 2020 Part 6 Table 6.3.10a: 2.5 for a permanent structure under normal control. Sec 3.10.1.18 (bored piles: Sec 3.10.4.10) asks at least 3.0 unless the design rests on a load test at the site (then 2.0): the design raises a smaller value.") },
	pileUplift: { key: 'pileUplift', label: localize('sub.f.fsUplift', "FS pile uplift"), kind: 'number', min: 1, max: 10, title: localize('sub.f.fsTitle', "BNBC 2020 Part 6 Table 6.3.10a: 2.5 for a permanent structure under normal control") },
	bearing: { key: 'bearing', label: localize('sub.f.fsBearing', "FS bearing"), kind: 'number', min: 1, max: 10, title: localize('sub.f.fsBearingTitle', "Factor of safety on the bearing capacity of footings and rafts; the soil report's when empty") },
	raftMeshSize: { key: 'raftMeshSize', label: localize('sub.f.raftMesh', "Raft mesh size"), unit: MM, kind: 'number', min: 100, max: 5000 },
	springs: { key: 'springs', label: localize('sub.f.springs', "Subgrade modulus ks"), unit: localize('sub.unit.knm3', "kN/m³"), kind: 'number', min: 0.001, title: localize('sub.f.springsTitle', "The raft's springs; the soil report's ks when empty") },
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

	private report: ISubstructureReport | undefined;
	private reportState: ReportState = 'idle';
	private reportError: string | undefined;
	private reportVersion = 0;
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
	private readonly openTextAction = this._register(new Action('saengine.substructure.editor.openText', localize('sub.openText', "Open as Text"), undefined, true, () => this.openAsText()));

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
		const parsed = parseSubstructure(this.model.getValue());
		if (parsed.kind === 'error') {
			this.document = undefined;
			this.parseError = parsed.message;
		} else {
			this.document = parsed.document;
			this.parseError = undefined;
			const count = this.document.foundations.length;
			this.selectedFoundations = this.selectedFoundations.filter(i => i < count);
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
	}

	private get selectionKey(): string {
		return `${this.selectedFoundations.join()}|${[...this.selectedColumns].join()}|${this.selectedTieBeam ?? ''}`;
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
		}
		this.selectedFoundations = [];
		this.selectedTieBeam = undefined;
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

	private onPlanClick(e: MouseEvent): void {
		const target = e.target as Element | null;
		const add = e.shiftKey || e.ctrlKey || e.metaKey;
		const column = target?.closest('[data-column]')?.getAttribute('data-column');
		const foundation = target?.closest('[data-foundation]')?.getAttribute('data-foundation');
		const tie = target?.closest('[data-tie]')?.getAttribute('data-tie');
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
		if (e.key === 'Delete' && this.deleteAction.enabled) {
			e.preventDefault();
			this.deleteSelection();
		} else if (e.key === 'Escape') {
			if (this.proposal) {
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
			const cap = newPileCap(document, this.context, group, pile, group.length > 1 ? 6 : 4);
			document.foundations.push(cap);
			added.push(cap);
		}
		this.added(added);
	}

	private addRaft(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		const picked = this.pickedColumns;
		if (picked.length && !this.free(document, picked.map(c => c.id))) {
			return;
		}
		if (!picked.length && document.foundations.some(f => f.columns?.length || f.type === 'raft')) {
			this.notificationService.info(localize('sub.raftWhole', "Some columns already stand on foundations. Select the columns the raft is to carry, or delete the other foundations for a raft under the whole building."));
			return;
		}
		const raft = newRaft(document, this.context, picked.length ? picked : this.context.columns);
		if (!raft) {
			this.notificationService.info(localize('sub.noColumns', "The building model has no columns on its base level yet."));
			return;
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

	private deleteSelection(): void {
		const document = this.document;
		if (!document) {
			return;
		}
		if (this.selectedTieBeam !== undefined) {
			document.tieBeams.splice(this.selectedTieBeam, 1);
		} else if (this.selectedFoundations.length) {
			const removed = new Set(this.selectedFoundations.map(i => document.foundations[i]?.id));
			document.foundations = document.foundations.filter((_, i) => !this.selectedFoundations.includes(i));
			document.tieBeams = document.tieBeams.filter(t => !removed.has(t.from) && !removed.has(t.to));
		} else {
			return;
		}
		this.clearSelection();
		this.changed(true);
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
		this.setBusy('size', true);
		let proposal: ISizingProposal | undefined;
		try {
			const answer = readSizingProposal(await this.commandService.executeCommand<unknown>(SUBSTRUCTURE_SIZE_COMMAND, request));
			proposal = answer && proposalFor(answer, columns);
		} catch (error) {
			this.notificationService.error(localize('sub.sizeFailed', "The foundations could not be sized: {0}", error instanceof Error ? error.message : String(error)));
			return;
		} finally {
			this.setBusy('size', false);
		}
		if (this.document !== document) {
			return;
		}
		if (!proposal?.foundations.length) {
			this.notificationService.info(proposal?.notes.length ? proposal.notes.join(' ') : localize('sub.sizeNothing', "The sizing assistant proposed no foundations. Run the analysis first: it sizes from the support reactions."));
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
			this.notificationService.info(imported?.notes.length ? imported.notes.join(' ') : localize('sub.migrateNothing', "The building model has no footings to import."));
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
		let report: ISubstructureReport | undefined;
		let error: string | undefined;
		try {
			report = readSubstructureReport(await this.commandService.executeCommand<unknown>(SUBSTRUCTURE_REPORT_COMMAND, request));
			if (!report) {
				error = localize('sub.reportEmpty', "The backend gave no design report.");
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
		// The backend checks the saved file: the part list's summary is written only when the
		// editor holds no unsaved edits, so it describes the file it sits next to.
		if (report && this.resource && !this.input?.isDirty()) {
			const content = JSON.stringify(substructureSummaryFile(document, report, new Date()), undefined, '\t') + '\n';
			this.fileService.writeFile(joinPath(dirname(this.resource), SUBSTRUCTURE_SUMMARY_FILE), VSBuffer.fromString(content)).catch(() => { /* the part list then shows the count only */ });
		}
	}

	private resultOf(foundation: IFoundation): IFoundationResult | undefined {
		return this.report?.foundations.find(f => f.id === foundation.id);
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
		this.deleteAction.enabled = this.selectedFoundations.length > 0 || this.selectedTieBeam !== undefined;
		this.deleteAction.label = this.selectedTieBeam !== undefined
			? localize('sub.deleteNamed', "Delete {0}", this.document?.tieBeams[this.selectedTieBeam]?.id ?? '')
			: this.selectedFoundations.length === 1 ? localize('sub.deleteNamed', "Delete {0}", this.document?.foundations[this.selectedFoundations[0]]?.id ?? '')
				: localize('sub.delete', "Delete");
		this.recomputeAction.enabled = !!this.document?.foundations.length;
		const primary: IAction[] = usable ? [
			this.addFootingAction, this.addPileCapAction, this.addRaftAction, this.addTieAction,
			this.sizeAction, this.migrateAction, this.deleteAction, frame.togglePropertiesAction,
		] : [frame.togglePropertiesAction];
		const secondary: IAction[] = usable ? [this.addStripAction, this.addPileTypeAction, this.selectAllAction, new Separator(), this.recomputeAction] : [];
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
		} else if (this.document && !this.document.foundations.length && !this.proposal && !this.context.columns.length) {
			this.frame.setEmpty({
				icon: Codicon.symbolStructure,
				title: localize('sub.emptyNoColumns', "No columns to found yet"),
				text: localize('sub.emptyNoColumnsText', "The foundations stand under the columns of the building model. Build the building model (6 BIM) first; its columns on the base level then appear here."),
			});
		} else if (this.document && !this.document.foundations.length && !this.proposal) {
			this.frame.setEmpty({
				icon: Codicon.symbolStructure,
				title: localize('sub.emptyTitle', "No foundations yet"),
				text: localize('sub.emptyText', "{0} columns stand on the base level. Let SAEngine size a footing under each from the analysis reactions and the soil report, bring in the footings drawn in the floor plan, or start with a footing under every column and size them yourself.", this.context.columns.length),
				actions: [
					{ label: localize('sub.size', "Size Footings"), icon: Codicon.wand, primary: true, run: () => void this.sizeAll() },
					{ label: localize('sub.emptyFootings', "Add Footings under All Columns"), icon: Codicon.add, run: () => this.addFootings() },
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
		append(header, $('span.sub-view-subtitle', undefined, localize('sub.planSubtitle', "ground {0} m · founding level {1} m unless set · click a column or foundation, Shift+click to add to the selection",
			formatNumber(this.context.groundLevel / 1000, 2), formatNumber(defaultFoundingLevel(this.context) / 1000, 2))));

		if (this.proposal) {
			const banner = append(view, $('.sub-banner', { role: 'status' }));
			append(banner, $(`span.sub-banner-icon${ThemeIcon.asCSSSelector(Codicon.wand)}`));
			const text = append(banner, $('.sub-banner-text'));
			const count = this.proposal.foundations.length;
			append(text, $('span.sub-banner-title', undefined, count === 1
				? localize('sub.proposalOne', "Proposed size for 1 foundation (dashed)")
				: localize('sub.proposal', "Proposed sizes for {0} foundations (dashed)", count)));
			if (this.proposal.notes.length) {
				append(text, $('span.sub-banner-detail', undefined, this.proposal.notes.join(' ')));
			}
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
		item('column', localize('sub.legendColumn', "Column"));
		if (this.context.boreholes.length) {
			item('borehole', localize('sub.legendBorehole', "Borehole"));
		}
		if (this.report) {
			item('band-ok', localize('sub.legendOk', "below 0.9"));
			item('band-warn', localize('sub.legendWarn', "0.9 to 1.0"));
			item('band-fail', localize('sub.legendFail', "above 1.0"));
		}

		const canvas = append(view, $('.sub-canvas'));
		const width = Math.max(240, view.clientWidth - 32);
		const height = Math.max(240, view.clientHeight - (this.proposal ? 150 : 96));
		const bands = this.report ? new Map(this.report.foundations.map(f => [f.id, utilisationBand(f.utilisation)])) : undefined;
		renderPlan(canvas, document, this.context, {
			width, height,
			selectedFoundations: new Set(this.selectedFoundations),
			selectedColumns: this.selectedColumns,
			selectedTieBeam: this.selectedTieBeam,
			proposals: this.proposal?.foundations,
			bands,
		});
		this.viewDisposables.add(addDisposableListener(canvas, EventType.CLICK, e => this.onPlanClick(e)));
	}

	// ───────────────────────────── data view ─────────────────────────────

	private renderDataView(document: ISubstructure): void {
		const header = append(this.viewElement, $('.sub-view-header'));
		append(header, $('span.sub-view-title', undefined, localize('sub.dataTitle', "Foundations, piles and tie beams")));
		append(header, $('span.sub-view-subtitle', undefined, localize('sub.dataSubtitle', "Sizes in mm, levels and positions in m; click a row to edit the rest in Properties.")));
		this.renderFoundationTable(document);
		this.renderPileTypeTable(document);
		this.renderTieBeamTable(document);
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
			{ label: F.id.label, width: 64 }, { label: localize('sub.f.type', "Type"), width: 140 }, { label: localize('sub.f.columns', "Columns"), width: 110 },
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
				append(pileCell, this.selectInput(document.pileTypes.map(p => ({ value: p.id, label: p.id })), f.pileType ?? '', value => this.setPileType(f, value), path('pileType'), localize('sub.f.pileType', "Pile type"), true));
			} else {
				pileCell.classList.add('sub-muted');
				pileCell.textContent = '—';
			}
			append(row, $('td.number', undefined, f.type === 'pileCap' ? String(f.piles?.length ?? 0) : ''));
			this.utilisationCell(row, this.resultOf(f)?.utilisation);
			this.removeButton(row, () => {
				this.selectedFoundations = [index];
				this.deleteSelection();
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
			{ label: F.pileLength.label, unit: M, numeric: true }, { label: localize('sub.f.material', "Concrete"), width: 96 }, { label: localize('sub.f.usedBy', "Caps"), numeric: true, width: 48 }, { label: '', width: 28 },
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
			append(row, $('td.number', undefined, String(document.foundations.filter(f => f.type === 'pileCap' && f.pileType === pile.id).length)));
			this.removeButton(row, () => {
				document.pileTypes.splice(index, 1);
				this.changed(true);
			});
		});
		if (!document.pileTypes.length) {
			append(append(body, $('tr')), $('td.sub-muted', { colspan: String(columns.length) }, localize('sub.noPileTypes', "None yet. A pile cap adds a 500 mm bored pile type to start with.")));
		}
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
			append(append(row, $('td')), this.textInput(F.level, tie.level, value => this.setTieLevel(tie, value), path('level')));
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

	private tieSpan(tie: ITieBeam): string {
		const from = this.document?.foundations.find(f => f.id === tie.from);
		const to = this.document?.foundations.find(f => f.id === tie.to);
		const a = from && foundationCenter(from, this.context);
		const b = to && foundationCenter(to, this.context);
		return a && b ? formatNumber(Math.hypot(b[0] - a[0], b[1] - a[1]) / 1000, 2) : '';
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
		for (const f of this.document?.foundations ?? []) {
			if (f.pileType === old) {
				f.pileType = id;
			}
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
			foundation.pileType = pile.id;
			applyPileLayout(foundation, pile, columns.length > 1 ? 6 : 4);
		} else {
			delete foundation.pileType;
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
		this.changed(true);
	}

	private setPileType(foundation: IFoundation, id: string): void {
		const pile = this.document?.pileTypes.find(p => p.id === id);
		foundation.pileType = id || undefined;
		if (pile) {
			applyPileLayout(foundation, pile, foundation.piles?.length && (PILE_LAYOUTS as readonly number[]).includes(foundation.piles.length) ? foundation.piles.length : 4);
		}
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

	/** The columns a foundation carries, typed as a list: "C1, C2". */
	private columnsInput(foundation: IFoundation, key: string): HTMLInputElement {
		const input = $<HTMLInputElement>('input.sub-input', { type: 'text', spellcheck: 'false', 'aria-label': localize('sub.f.columns', "Columns") });
		input.value = (foundation.columns ?? []).join(', ');
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
			append(state, $('.sub-results-state-text', undefined, this.reportState === 'error'
				? this.reportError ?? ''
				: this.reportState === 'missing' ? localize('sub.backendMissingText', "The bearing, shear, flexure, pile and raft checks are computed by the SAEngine Python backend from the analysis reactions and the soil report; it is not running in this window. The foundations can still be drawn and edited; the checks appear once the backend is available.") : ''));
			return;
		}
		const report = this.report;
		const header = append(view, $('.sub-view-header'));
		append(header, $('span.sub-view-title', undefined, localize('sub.resultsTitle', "Design checks")));
		append(header, $('span.sub-view-subtitle', undefined, localize('sub.resultsSubtitle', "Computed from the analysis reactions and the soil report; not stored in the file.")));
		if (this.input?.isDirty()) {
			append(view, $('p.sub-note.warning.sub-unsaved-note', undefined, localize('sub.resultsUnsaved', "These are the checks of the saved file. Save to check the latest edits.")));
		}

		this.renderTiles(view, report);
		this.renderResultTable(view, document, report);
		const selected = this.foundation ?? document.foundations.find(f => f.id === report.summary.governing);
		const result = selected && this.resultOf(selected);
		if (selected && result) {
			this.renderFoundationDetail(view, selected, result);
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

	private renderTiles(view: HTMLElement, report: ISubstructureReport): void {
		const tiles = append(view, $('.sub-tiles'));
		const tile = (value: string, label: string, band?: string) => {
			const element = append(tiles, $('.sub-tile'));
			append(element, $(`span.sub-tile-value${band ? `.band-${band}` : ''}`, undefined, value));
			append(element, $('span.sub-tile-label', undefined, label));
		};
		tile(String(report.summary.checked), report.tieBeams.length ? localize('sub.tileCheckedTies', "foundations and tie beams checked") : localize('sub.tileChecked', "foundations checked"));
		tile(String(report.summary.failed), localize('sub.tileFailed', "fail"), report.summary.failed ? 'fail' : 'ok');
		const max = report.summary.maxUtilisation;
		if (typeof max === 'number') {
			tile(formatUtilisation(max), report.summary.governing ? localize('sub.tileMaxIn', "largest utilisation, {0}", report.summary.governing) : localize('sub.tileMax', "largest utilisation"), utilisationBand(max));
		}
		const pressure = maxPressure(report);
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
			const row = append(body, $('tr.sub-row', { 'data-index': String(index), tabIndex: 0 }));
			this.foundationRows.set(row, index);
			const governing = governingCheck(result);
			append(row, $('td', undefined, f.id));
			append(row, $('td', undefined, foundationTypeLabel(f.type)));
			append(row, $('td', undefined, foundationSize(f)));
			append(row, $('td', undefined, result ? governing?.name ?? '' : localize('sub.notChecked', "not checked")));
			append(row, $('td.sub-muted-cell', undefined, governing?.combination ?? ''));
			this.utilisationCell(row, result?.utilisation);
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
			const result = report.tieBeams.find(t => t.id === tie.id);
			const row = append(body, $('tr.sub-row.tie', { tabIndex: 0 }));
			const governing = governingCheck(result);
			append(row, $('td', undefined, tie.id));
			append(row, $('td', undefined, localize('sub.tieBeam', "Tie beam")));
			append(row, $('td', undefined, localize('sub.tieBetween', "{0} – {1}", tie.from, tie.to)));
			append(row, $('td', undefined, result ? governing?.name ?? '' : localize('sub.notChecked', "not checked")));
			append(row, $('td.sub-muted-cell', undefined, governing?.combination ?? ''));
			this.utilisationCell(row, result?.utilisation);
			if (result && !result.ok) {
				row.classList.add('failed');
			}
			this.viewDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.selectTieBeam(index)));
		});
		this.markSelectedRows();
	}

	private renderFoundationDetail(view: HTMLElement, foundation: IFoundation, result: IFoundationResult): void {
		const section = this.resultSection(view, localize('sub.detailTitle', "{0}: all checks", foundation.id), `${foundationTypeLabel(foundation.type)} · ${foundationSize(foundation)}`);
		const table = append(section, $('table.sub-table.sub-result-table'));
		this.tableHead(table, [
			{ label: localize('sub.check', "Check"), width: 220 }, { label: localize('sub.demand', "Demand"), numeric: true }, { label: localize('sub.capacity', "Capacity"), numeric: true },
			{ label: localize('sub.unit', "Unit"), width: 60 }, { label: localize('sub.f.utilisation', "Utilisation"), numeric: true, width: 120 }, { label: localize('sub.combination', "Combination"), width: 180 }, { label: localize('sub.note', "Note"), width: 260 },
		]);
		const body = append(table, $('tbody'));
		const value = (v: number | null) => v === null ? '—' : Math.abs(v) >= 100 ? formatNumber(v, 0) : Math.abs(v) >= 1 || v === 0 ? formatNumber(v, 2) : String(Number(v.toPrecision(3)));
		// The checks that count first, by utilisation; the ones only reported after them.
		for (const check of [...result.checks].sort((a, b) => Number(a.flag) - Number(b.flag) || (b.utilisation ?? -1) - (a.utilisation ?? -1))) {
			const row = append(body, $(check.flag ? 'tr.flag' : 'tr'));
			append(row, $('td', undefined, check.flag ? localize('sub.flagged', "{0} (reported only)", check.name) : check.name));
			append(row, $('td.number', undefined, value(check.demand)));
			append(row, $('td.number', undefined, value(check.capacity)));
			append(row, $('td.sub-muted-cell', undefined, check.unit));
			this.utilisationCell(row, check.utilisation);
			append(row, $('td.sub-muted-cell', undefined, check.combination ?? ''));
			append(row, $('td.sub-wrap', undefined, check.note));
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
			append(row, $('td', undefined, String(pile.number)));
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
			appendPropertyNote(panel, this.parseError ?? localize('sub.propsNone', "No substructure."));
			return;
		}
		this.renderingProperties = true;
		let paths: string[] = [];
		try {
			const foundation = this.foundation;
			if (foundation) {
				this.renderFoundationProperties(panel, document, foundation);
				paths = [`foundations.${this.selectedFoundations[0]}.`];
			} else if (this.selectedTieBeam !== undefined && document.tieBeams[this.selectedTieBeam]) {
				this.renderTieProperties(panel, document, document.tieBeams[this.selectedTieBeam]);
				paths = [`tieBeams.${this.selectedTieBeam}.`];
			} else if (this.selectedFoundations.length > 1) {
				appendPropertyHeading(panel, localize('sub.manySelected', "{0} foundations", this.selectedFoundations.length));
				appendPropertyRow(panel, localize('sub.selected', "Selected"), this.selectedFoundations.map(i => document.foundations[i]?.id).join(', '));
				appendPropertyNote(panel, this.selectedFoundations.length === 2
					? localize('sub.tieHint', "Add a tie beam between them with the tie beam button in the toolbar.")
					: localize('sub.tieHintTwo', "Select exactly two foundations to tie them."));
			} else if (this.selectedColumns.size) {
				this.renderColumnProperties(panel, document);
			} else {
				this.renderDesignProperties(panel, document);
				paths = ['pileTypes.', 'tieBeams.', 'foundations.'];
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
		this.fieldRow(panel, F.foundingLevel, foundation.foundingLevel, value => this.setField(foundation, 'foundingLevel', value), path('foundingLevel'), formatNumber(defaultFoundingLevel(this.context) / 1000, 3));
		if (foundation.type === 'raft') {
			appendPropertyRow(panel, localize('sub.outline', "Outline"), localize('sub.outlinePoints', "{0} points", foundation.outline?.length ?? 0));
		}
		if (foundation.type === 'strip') {
			appendPropertyRow(panel, localize('sub.path', "Path"), localize('sub.outlinePoints', "{0} points", foundation.path?.length ?? 0));
		}

		if (foundation.type === 'pileCap') {
			appendPropertyHeading(panel, localize('sub.pilesHeading', "Piles"));
			this.propertyRow(panel, localize('sub.f.pileType', "Pile type"), this.selectInput(document.pileTypes.map(p => ({ value: p.id, label: `${p.id} · ${pileKindLabel(p.kind)} ${formatNumber(p.diameter, 0)} mm` })), foundation.pileType ?? '', value => this.setPileType(foundation, value), path('pileType'), localize('sub.f.pileType', "Pile type"), true));
			const count = foundation.piles?.length ?? 0;
			const layouts = PILE_LAYOUTS.map(n => ({ value: String(n), label: localize('sub.layoutOption', "{0} piles at 3 diameters", n) }));
			const layoutSelect = this.selectInput(layouts, (PILE_LAYOUTS as readonly number[]).includes(count) ? String(count) : '', value => {
				const pile = document.pileTypes.find(p => p.id === foundation.pileType);
				if (!pile || !value) {
					return;
				}
				applyPileLayout(foundation, pile, Number(value));
				this.changed(true);
			}, path('piles'), localize('sub.f.layout', "Layout"), !(PILE_LAYOUTS as readonly number[]).includes(count));
			this.propertyRow(panel, localize('sub.f.layout', "Layout"), layoutSelect, undefined, localize('sub.layoutTitle', "Puts the piles at three diameters centre to centre (the spacing BNBC 2020 Part 6 Sec 3.10.1.30 generally asks for driven friction piles) and sizes the cap with 150 mm beyond the piles"));
			appendPropertyRow(panel, localize('sub.f.piles', "Piles"), String(count));
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
		this.fieldRow(panel, F.level, tie.level, value => this.setTieLevel(tie, value), path('level'));
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
			appendPropertyRow(panel, localize('sub.selected', "Selected"), columns.map(c => c.id).join(', '));
		}
		appendPropertyNote(panel, columns.length > 1
			? localize('sub.columnsHint', "Add a combined footing, one pile cap or a raft under them with the toolbar buttons.")
			: localize('sub.columnHint', "Add a footing or a pile cap under it with the toolbar buttons; Shift+click more columns for a combined footing."));
	}

	private renderDesignProperties(panel: HTMLElement, document: ISubstructure): void {
		appendPropertyHeading(panel, localize('sub.summaryHeading', "Substructure"));
		appendPropertyRow(panel, localize('sub.foundationsHeading', "Foundations"), String(document.foundations.length));
		appendPropertyRow(panel, localize('sub.pileTypes', "Pile types"), String(document.pileTypes.length));
		appendPropertyRow(panel, localize('sub.tieBeams', "Tie beams"), String(document.tieBeams.length));
		const uncovered = uncoveredColumns(document, this.context);
		appendPropertyRow(panel, localize('sub.uncovered', "Columns without one"), uncovered.length ? uncovered.map(c => c.id).join(', ') : localize('sub.noneShort', "none"));

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
		for (const field of [F.pileCompression, F.pileUplift, F.bearing]) {
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
		appendPropertyNote(panel, localize('sub.designNote', "Empty values use the defaults: pile factors of safety 2.5 (BNBC 2020 Part 6 Table 6.3.10a, permanent structure, normal control; in compression raised to 3.0 without a load test at the site), the soil report's bearing factor and subgrade modulus, a 500 mm raft mesh."));
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
		const parts = [substructureSummary(document, this.reportState === 'ok' ? this.report : undefined)];
		if (this.reportState === 'ok' && this.input?.isDirty()) {
			parts.push(localize('sub.statusUnsaved', "checks of the saved file"));
		}
		if (this.reportState === 'missing') {
			parts.push(localize('sub.statusNoBackend', "checks need the backend"));
		} else if (this.reportState === 'error') {
			parts.push(localize('sub.statusFailed', "checks could not be computed"));
		}
		const uncovered = uncoveredColumns(document, this.context).length;
		if (uncovered) {
			parts.push(uncovered === 1 ? localize('sub.statusUncoveredOne', "1 column without a foundation") : localize('sub.statusUncovered', "{0} columns without a foundation", uncovered));
		}
		const errors = this.problems.filter(p => p.severity === 'error').length;
		const failed = this.reportState === 'ok' && (this.report?.summary.failed ?? 0) > 0;
		const status: IEditorFrameStatus = {
			text: parts.join(' · '),
			severity: errors || failed ? 'error' : this.problems.length || uncovered || this.reportState === 'error' ? 'warning' : undefined,
			busy: this.reportState === 'computing',
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
		const match = /^(?<list>foundations|tieBeams|pileTypes)\.(?<index>\d+)\./.exec(problem.path);
		this.clearSelection();
		if (match?.groups?.list === 'foundations') {
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
