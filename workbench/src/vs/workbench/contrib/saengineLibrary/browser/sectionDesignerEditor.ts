/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modelEditors.css';
import './media/sectionDesigner.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { projectMaterial } from '../../../services/saengineProject/common/materialDefaults.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyHeading, appendPropertyNote, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { renderChart } from '../../saengineFem/browser/femChart.js';
import { svg } from '../../saengineSoil/browser/soilLog.js';
import { SectionDesignerInput } from './sectionDesignerInput.js';
import {
	barArea, barsAlongEdges, barsLine, barsRing, bounds, cleanProperties, formatNumber, hitTest, IBar, IDesignedSection, interactionCurve, ISectionAnalysis, ITemplateParams, IUniaxial,
	moveSelection, parseSection, Point, pointInRegion, propertyRows, rectangle, Ring, sameRegions, Selection, serializeSection, snapPoint, TEMPLATE_DEFAULTS, templateFields, TemplateKind, templateLabel, templateProblem, templateRegions,
} from './sectionDesignerModel.js';

/** Desktop command analysing a section with the Python models (`section/analyse`). */
export const SECTION_ANALYSE_COMMAND = 'saengine.section.analyse';

type Tool = 'select' | 'rectangle' | 'polygon' | 'hole' | 'bar' | 'barLine' | 'barRing';

interface IToolSpec {
	readonly tool: Tool;
	readonly icon: ThemeIcon;
	readonly label: string;
	readonly key: KeyCode;
	readonly keyLabel: string;
}

const TOOLS: readonly IToolSpec[] = [
	{ tool: 'select', icon: Codicon.inspect, label: localize('section.tool.select', "Select and move"), key: KeyCode.KeyV, keyLabel: 'V' },
	{ tool: 'rectangle', icon: Codicon.primitiveSquare, label: localize('section.tool.rectangle', "Rectangle region"), key: KeyCode.KeyR, keyLabel: 'R' },
	{ tool: 'polygon', icon: Codicon.symbolInterface, label: localize('section.tool.polygon', "Polygon region (Enter closes)"), key: KeyCode.KeyP, keyLabel: 'P' },
	{ tool: 'hole', icon: Codicon.circleLargeOutline, label: localize('section.tool.hole', "Rectangular opening"), key: KeyCode.KeyH, keyLabel: 'H' },
	{ tool: 'bar', icon: Codicon.circleFilled, label: localize('section.tool.bar', "Single bar"), key: KeyCode.KeyB, keyLabel: 'B' },
	{ tool: 'barLine', icon: Codicon.ellipsis, label: localize('section.tool.barLine', "Line of bars"), key: KeyCode.KeyL, keyLabel: 'L' },
	{ tool: 'barRing', icon: Codicon.circleLarge, label: localize('section.tool.barRing', "Ring of bars"), key: KeyCode.KeyO, keyLabel: 'O' },
];

const BAR_DIAMETERS = [10, 12, 16, 20, 25, 28, 32];
const GRID_STEPS = [5, 10, 25, 50, 100];
const TEMPLATE_KINDS: readonly TemplateKind[] = ['rectangle', 'circle', 'L', 'T', 'C', 'box', 'core', 'I'];
/** Ties assumed between the cover and the bars when bars are laid along the edges [mm]. */
const TIE_DIA = 10;

interface IMaterialChoice {
	readonly id: string;
	readonly name: string;
	readonly category: string;
}

/** The template a section was drawn from, while its regions are still that template's. */
interface ITemplateState {
	readonly kind: TemplateKind;
	readonly params: ITemplateParams;
}

/** Templates by section file, kept across tab switches (the file itself has no room for them). */
const templates = new Map<string, ITemplateState>();

/**
 * Analyses by section and materials text: switching back to a section's tab shows its results
 * at once instead of computing them again (O15). Oldest first, at most {@link ANALYSIS_CACHE_SIZE}.
 */
const analyses = new Map<string, ISectionAnalysis>();
const ANALYSIS_CACHE_SIZE = 24;

/** Above this axial load [kN] the chart is drawn in MN, so the tick labels stay short. */
const MN_FROM = 1000;

/**
 * The Section Designer: draws and edits a designed section on a snapping grid (regions,
 * openings, bars, templates), and shows its properties and interaction diagrams as computed by
 * the Python models (sectionproperties and concreteproperties, φ from the project's code pack).
 */
export class SectionDesignerEditor extends EditorPane {

	static readonly ID = SectionDesignerInput.EDITOR_ID;

	private frame!: EditorFrame;
	private canvas!: SVGSVGElement;
	private panel!: HTMLElement;
	private model: ITextModel | undefined;
	private section: IDesignedSection | undefined;
	private analysis: ISectionAnalysis | undefined;
	private analysing = false;
	private analyseVersion = 0;
	private applying = false;
	private selection: Selection;
	private tool: Tool = 'select';
	private draft: Point[] = [];
	private cursor: Point | undefined;
	private drag: { start: Point; last: Point; moved: boolean; pan?: { x: number; y: number } } | undefined;
	private chartAxis: 'x' | 'y' = 'x';
	/** The large interaction diagram over the drawing, while it is shown. */
	private chartOverlay: HTMLElement | undefined;
	private materials: IMaterialChoice[] = [];
	/** The project's concrete and rebar (03 Materials `defaults`, else the first of each). */
	private projectMaterials: { concrete?: string; rebar?: string } = {};
	private readonly settings = { material: '', rebar: '', dia: 20, spacing: 150, count: 4, grid: 25 };
	/** View: screen = (origin.x + x k, origin.y - y k). */
	private view = { k: 0.5, ox: 0, oy: 0 };
	private fitted = false;
	private readonly toolButtons = new Map<Tool, HTMLButtonElement>();

	private readonly inputDisposables = this._register(new DisposableStore());
	private readonly panelDisposables = this._register(new DisposableStore());
	private readonly materialsReference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly commitScheduler = this._register(new RunOnceScheduler(() => this.commit(), 250));
	private readonly analyseScheduler = this._register(new RunOnceScheduler(() => this.analyse(), 700));
	private readonly fitAction = this._register(new Action('saengine.section.fit', localize('section.fit', "Fit to View"), ThemeIcon.asClassName(Codicon.screenFull), true, async () => { this.fit(); this.renderCanvas(); }));
	private readonly edgesAction = this._register(new Action('saengine.section.edges', localize('section.edges', "Bars Along Edges of the Selected Region (or All)"), ThemeIcon.asClassName(Codicon.symbolArray), true, async () => this.barsAlongEdges()));
	private readonly deleteAction = this._register(new Action('saengine.section.delete', localize('section.delete', "Delete Selection (Delete)"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteSelection()));
	private readonly clearBarsAction = this._register(new Action('saengine.section.clearBars', localize('section.clearBars', "Remove All Bars"), undefined, true, async () => this.edit(s => { s.bars = []; })));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ICommandService private readonly commandService: ICommandService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super(SectionDesignerEditor.ID, group, telemetryService, themeService, storageService);
	}

	get resource(): URI | undefined {
		return (this.input as SectionDesignerInput | undefined)?.resource;
	}

	protected createEditor(parent: HTMLElement): void {
		const frame = this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: SectionDesignerEditor.ID,
			ariaLabel: localize('section.toolbar', "Section Designer"),
			properties: { title: localize('section.properties', "Section"), defaultWidth: 340 },
		}));
		frame.element.classList.add('saengine-section-designer');
		frame.setTitle(localize('section.title', "Section Designer"));
		frame.setHelp(localize('section.help', "Draw an arbitrary cross-section: regions of concrete or steel plates with openings, and reinforcing bars. Points snap to the grid. Keys: V select, R rectangle, P polygon (Enter closes, Backspace removes the last point), H opening, B bar, L line of bars, O ring of bars, arrows move the selection, Delete removes it, Escape cancels. Properties come from sectionproperties, the interaction diagrams from concreteproperties with the strength reduction factors of the project's code pack. Object types use the section through the profile \"Designed section\"."));

		const tools = append(frame.controlsSlot, $('.sa-segmented', { role: 'toolbar', 'aria-label': localize('section.toolsAria', "Drawing tools") }));
		for (const spec of TOOLS) {
			const button = append(tools, $<HTMLButtonElement>('button.sa-segment', { type: 'button', 'aria-pressed': 'false', 'aria-label': `${spec.label} (${spec.keyLabel})`, title: `${spec.label} (${spec.keyLabel})` }));
			append(button, $(ThemeIcon.asCSSSelector(spec.icon)));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.setTool(spec.tool)));
			this.toolButtons.set(spec.tool, button);
		}
		const template = append(frame.controlsSlot, $<HTMLSelectElement>('select.section-select.section-template', { 'aria-label': localize('section.templateAria', "Insert a template") }));
		append(template, $<HTMLOptionElement>('option', { value: '' }, localize('section.template', "Template…")));
		for (const kind of TEMPLATE_KINDS) {
			append(template, $<HTMLOptionElement>('option', { value: kind }, templateLabel(kind)));
		}
		this._register(addDisposableListener(template, EventType.CHANGE, () => {
			if (template.value) {
				this.insertTemplate(template.value as TemplateKind);
				template.value = '';
			}
		}));
		frame.setActions([this.edgesAction, this.deleteAction, this.fitAction, frame.togglePropertiesAction], [this.clearBarsAction]);

		const host = append(frame.main, $('.section-canvas-host'));
		this.canvas = svg(host, 'svg', { class: 'section-canvas', tabindex: 0, role: 'application', 'aria-label': localize('section.canvasAria', "Section drawing. Use the tool keys to draw, arrows to move the selection.") });
		this._register(addDisposableListener(this.canvas, EventType.POINTER_DOWN, e => this.onPointerDown(e)));
		this._register(addDisposableListener(this.canvas, EventType.POINTER_MOVE, e => this.onPointerMove(e)));
		this._register(addDisposableListener(this.canvas, EventType.POINTER_UP, e => this.onPointerUp(e)));
		this._register(addDisposableListener(this.canvas, EventType.DBLCLICK, () => this.closePolygon()));
		this._register(addDisposableListener(this.canvas, EventType.MOUSE_WHEEL, e => this.onWheel(e as WheelEvent), { passive: false }));
		this._register(addDisposableListener(this.canvas, EventType.KEY_DOWN, e => this.onKey(new StandardKeyboardEvent(e))));
		this.panel = frame.properties!;
		this._register(frame.onDidLayoutMain(() => this.renderCanvas()));
		this.updateToolButtons();
	}

	override async setInput(input: SectionDesignerInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.inputDisposables.clear();
		this.materialsReference.clear();
		this.model = undefined;
		this.section = undefined;
		this.analysis = undefined;
		this.selection = undefined;
		this.draft = [];
		this.fitted = false;
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
		await this.trackMaterials(input);
		this.load();
	}

	override clearInput(): void {
		this.chartOverlay?.remove();
		this.chartOverlay = undefined;
		this.flush();
		this.inputDisposables.clear();
		this.materialsReference.clear();
		this.analyseScheduler.cancel();
		this.model = undefined;
		this.section = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.canvas?.focus();
	}

	override dispose(): void {
		this.flush();
		super.dispose();
	}

	// ───────────────────────────── document ─────────────────────────────

	private load(): void {
		if (!this.model) {
			return;
		}
		const parsed = parseSection(this.model.getValue());
		if (!parsed.ok) {
			this.section = undefined;
			this.frame.setEmpty({ icon: Codicon.warning, title: localize('section.cannotShow', "This section cannot be shown"), text: parsed.error });
			this.frame.setStatus({ severity: 'warning', text: parsed.error });
			clearNode(this.panel);
			return;
		}
		this.frame.setEmpty(undefined);
		this.section = parsed.section;
		this.frame.setTitle(localize('section.titleNamed', "Section Designer: {0}", this.section.name));
		this.defaultsFromSection();
		if (this.selection && !this.selected()) {
			this.selection = undefined;
		}
		if (!this.fitted) {
			this.fit();
		}
		this.render();
		// Opening a section (or coming back to its tab) shows a cached analysis at once.
		this.analyseScheduler.schedule(this.analysis ? undefined : 0);
	}

	private defaultsFromSection(): void {
		const section = this.section!;
		this.settings.material ||= section.regions[0]?.material ?? this.projectMaterials.concrete ?? '';
		this.settings.rebar = section.rebar ?? (this.settings.rebar || this.projectMaterials.rebar || '');
	}

	private commit(): void {
		this.commitScheduler.cancel();
		const model = this.model;
		if (!model || !this.section || model.isDisposed()) {
			return;
		}
		const text = serializeSection(this.section);
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
		this.analyseScheduler.schedule();
	}

	private flush(): void {
		if (this.commitScheduler.isScheduled()) {
			this.commit();
		}
	}

	/** Applies `change` to the section, saves it to the text model (one undo step) and redraws. */
	private edit(change: (section: IDesignedSection) => void, batched = false): void {
		if (!this.section) {
			return;
		}
		change(this.section);
		if (batched) {
			this.commitScheduler.schedule();
		} else {
			this.commit();
		}
		this.render();
	}

	/** The materials file (unsaved edits included) for the material pickers. */
	private async trackMaterials(input: SectionDesignerInput): Promise<void> {
		const project = this.projectService.project;
		const part = partById('materials');
		if (!project || !part?.mainFile) {
			return;
		}
		try {
			const reference = await this.textModelService.createModelReference(joinPath(project.root, part.folder, part.mainFile));
			if (this.input !== input) {
				reference.dispose();
				return;
			}
			this.materialsReference.value = reference;
		} catch {
			return;
		}
		const model = this.materialsReference.value.object.textEditorModel;
		const read = () => {
			try {
				const data = JSON.parse(model.getValue());
				this.projectMaterials = { concrete: projectMaterial(data, 'concrete'), rebar: projectMaterial(data, 'rebar') };
				this.materials = (Array.isArray(data?.materials) ? data.materials : [])
					.filter((m: IMaterialChoice) => typeof m?.id === 'string' && ['concrete', 'steel', 'rebar'].includes(m.category))
					.map((m: IMaterialChoice) => ({ id: m.id, name: typeof m.name === 'string' ? m.name : m.id, category: m.category }));
			} catch {
				this.materials = [];
				this.projectMaterials = {};
			}
		};
		read();
		this.inputDisposables.add(model.onDidChangeContent(() => {
			read();
			this.renderPanel();
			this.analyseScheduler.schedule();
		}));
	}

	// ───────────────────────────── analysis ─────────────────────────────

	private async analyse(): Promise<void> {
		const model = this.model;
		const input = this.input;
		if (!model || !this.section) {
			return;
		}
		const version = ++this.analyseVersion;
		const text = model.getValue();
		const key = `${text}\u0000${this.materialsReference.value?.object.textEditorModel.getValue() ?? ''}`;
		const cached = analyses.get(key);
		if (cached) {
			this.analysing = false;
			this.analysis = cached;
			this.render();
			return;
		}
		this.analysing = true;
		this.renderStatus();
		let analysis: ISectionAnalysis | undefined;
		let failure: string | undefined;
		try {
			analysis = await this.commandService.executeCommand<ISectionAnalysis>(SECTION_ANALYSE_COMMAND, text);
			if (analysis) {
				analyses.delete(key);
				analyses.set(key, analysis);
				if (analyses.size > ANALYSIS_CACHE_SIZE) {
					analyses.delete(analyses.keys().next().value!);
				}
			}
		} catch (error) {
			// A backend error carries its traceback: its first line says what went wrong.
			failure = (error instanceof Error ? error.message : String(error)).split(/\r?\n/)[0].trim().slice(0, 300);
		}
		if (version !== this.analyseVersion || this.input !== input) {
			return; // a newer analysis is on its way
		}
		this.analysing = false;
		this.analysis = analysis;
		if (!analysis) {
			this.frame.setStatus({ severity: 'warning', text: failure ? localize('section.failed', "The section could not be analysed: {0}", failure) : localize('section.noBackend', "The properties need the Python backend (desktop app).") });
		}
		this.render();
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		this.renderCanvas();
		this.renderPanel();
		this.renderStatus();
		this.deleteAction.enabled = !!this.selection;
		this.edgesAction.enabled = !!this.section?.regions.length;
	}

	private renderStatus(): void {
		const section = this.section;
		if (!section) {
			return;
		}
		if (this.analysing) {
			this.frame.setStatus({ busy: true, text: localize('section.analysing', "Computing properties and interaction diagrams…") });
			return;
		}
		const analysis = this.analysis;
		if (!analysis) {
			return;
		}
		if (analysis.problems.length) {
			this.frame.setStatus({ severity: 'error', text: analysis.problems.map(p => p.message).join('; ') });
			return;
		}
		const p = analysis.properties;
		const bars = section.bars.length;
		this.frame.setStatus({
			severity: 'info',
			text: p ? localize('section.status', "A = {0} mm²  ·  Ixx = {1} mm⁴  ·  Iyy = {2} mm⁴  ·  {3} bars, ρ = {4} %", formatNumber(p.area), formatNumber(p.ixx), formatNumber(p.iyy), bars, formatNumber(p.barRatio * 100)) : '',
		});
	}

	private toScreen([x, y]: Point): Point {
		return [this.view.ox + x * this.view.k, this.view.oy - y * this.view.k];
	}

	private toWorld(clientX: number, clientY: number): Point {
		const box = this.canvas.getBoundingClientRect();
		return [(clientX - box.left - this.view.ox) / this.view.k, -(clientY - box.top - this.view.oy) / this.view.k];
	}

	private fit(): void {
		const box = this.canvas.getBoundingClientRect();
		const extent = this.section && bounds(this.section);
		if (!extent || box.width < 10 || box.height < 10) {
			return;
		}
		const w = Math.max(extent.maxX - extent.minX, 100), h = Math.max(extent.maxY - extent.minY, 100);
		const k = Math.min(box.width / (w * 1.25), box.height / (h * 1.25));
		this.view = { k, ox: box.width / 2 - (extent.minX + extent.maxX) / 2 * k, oy: box.height / 2 + (extent.minY + extent.maxY) / 2 * k };
		this.fitted = true;
	}

	private ringPath(ring: readonly Point[]): string {
		return ring.map((p, i) => {
			const [x, y] = this.toScreen(p);
			return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
		}).join(' ') + ' Z';
	}

	private renderCanvas(): void {
		const canvas = this.canvas;
		if (!canvas) {
			return;
		}
		canvas.replaceChildren();
		const section = this.section;
		if (!section) {
			return;
		}
		if (!this.fitted) {
			this.fit();
		}
		const box = canvas.getBoundingClientRect();
		const { k } = this.view;
		// Grid: the snap step, or a multiple of it when the lines would be closer than 8 px.
		let step = this.settings.grid;
		while (step * k < 8) {
			step *= 5;
		}
		const grid = svg(canvas, 'g', { class: 'section-grid' });
		const [x0, y1] = this.toWorld(box.left, box.top);
		const [x1, y0] = this.toWorld(box.right, box.bottom);
		for (let x = Math.ceil(x0 / step) * step; x <= x1; x += step) {
			const sx = this.toScreen([x, 0])[0];
			svg(grid, 'line', { x1: sx, y1: 0, x2: sx, y2: box.height, class: x === 0 ? 'axis' : (Math.round(x / step) % 5 === 0 ? 'major' : '') });
		}
		for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
			const sy = this.toScreen([0, y])[1];
			svg(grid, 'line', { x1: 0, y1: sy, x2: box.width, y2: sy, class: y === 0 ? 'axis' : (Math.round(y / step) % 5 === 0 ? 'major' : '') });
		}

		const categories = new Map(this.materials.map(m => [m.id, m.category]));
		section.regions.forEach((region, index) => {
			const selected = this.selection?.kind === 'region' && this.selection.index === index;
			const category = categories.get(region.material) ?? 'concrete';
			const path = svg(canvas, 'path', {
				d: [region.outline, ...region.holes].map(r => this.ringPath(r)).join(' '),
				class: `section-region ${category}${selected ? ' selected' : ''}`,
				'fill-rule': 'evenodd',
			});
			svg(path, 'title', {}, localize('section.regionTitle', "Region {0}: {1}", index + 1, region.material));
		});
		section.bars.forEach((bar, index) => {
			const selected = this.selection?.kind === 'bar' && this.selection.index === index;
			const [x, y] = this.toScreen([bar.x, bar.y]);
			const circle = svg(canvas, 'circle', { cx: x, cy: y, r: Math.max(2.5, bar.dia / 2 * k), class: `section-bar${selected ? ' selected' : ''}` });
			svg(circle, 'title', {}, localize('section.barTitle', "Bar Ø{0} at ({1}, {2})", bar.dia, bar.x, bar.y));
		});

		this.renderDimensions(canvas, section);

		const p = this.analysis?.properties && cleanProperties(this.analysis.properties);
		if (p) {
			const [cx, cy] = this.toScreen([p.cx, p.cy]);
			const marker = svg(canvas, 'g', { class: 'section-centroid' });
			svg(marker, 'circle', { cx, cy, r: 5 });
			svg(marker, 'line', { x1: cx - 9, y1: cy, x2: cx + 9, y2: cy });
			svg(marker, 'line', { x1: cx, y1: cy - 9, x2: cx, y2: cy + 9 });
			svg(marker, 'title', {}, localize('section.centroid', "Centroid ({0}, {1})", formatNumber(p.cx), formatNumber(p.cy)));
			const [sx, sy] = this.toScreen([p.scx, p.scy]);
			const shear = svg(canvas, 'rect', { x: sx - 4, y: sy - 4, width: 8, height: 8, class: 'section-shear-centre' });
			svg(shear, 'title', {}, localize('section.shearCentre', "Shear centre ({0}, {1})", formatNumber(p.scx), formatNumber(p.scy)));
		}

		this.renderDraft(canvas);
	}

	/**
	 * Dimensions on the drawing: the overall width (below) and depth (left), and the length of
	 * every edge of the selected region next to it.
	 */
	private renderDimensions(canvas: SVGSVGElement, section: IDesignedSection): void {
		const extent = bounds(section);
		if (!extent) {
			return;
		}
		const group = svg(canvas, 'g', { class: 'section-dimensions' });
		const gap = 18;
		const [left, bottom] = this.toScreen([extent.minX, extent.minY]);
		const [right, top] = this.toScreen([extent.maxX, extent.maxY]);
		const line = (x1: number, y1: number, x2: number, y2: number) => svg(group, 'line', { x1, y1, x2, y2 });
		const label = (x: number, y: number, text: string, rotate = false) => {
			const node = svg(group, 'text', { x, y, 'text-anchor': 'middle', 'dominant-baseline': 'central', transform: rotate ? `rotate(-90 ${x} ${y})` : '' });
			node.textContent = text;
		};
		// Width below the section, depth to its left: extension lines, the dimension line, the value.
		const y = bottom + gap;
		line(left, bottom + 4, left, y + 4);
		line(right, bottom + 4, right, y + 4);
		line(left, y, right, y);
		label((left + right) / 2, y + 10, formatNumber(extent.maxX - extent.minX));
		const x = left - gap;
		line(left - 4, top, x - 4, top);
		line(left - 4, bottom, x - 4, bottom);
		line(x, top, x, bottom);
		label(x - 10, (top + bottom) / 2, formatNumber(extent.maxY - extent.minY), true);

		if (this.selection?.kind === 'region') {
			const region = section.regions[this.selection.index];
			const centre: Point = [(extent.minX + extent.maxX) / 2, (extent.minY + extent.maxY) / 2];
			for (const ring of [region.outline, ...region.holes]) {
				ring.forEach((p, i) => {
					const q = ring[(i + 1) % ring.length];
					const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
					// An outer edge as long as the section is wide or deep: the overall dimension says it.
					const full = (p[1] === q[1] && (p[1] === extent.minY || p[1] === extent.maxY) && Math.abs(length - (extent.maxX - extent.minX)) < 0.01)
						|| (p[0] === q[0] && (p[0] === extent.minX || p[0] === extent.maxX) && Math.abs(length - (extent.maxY - extent.minY)) < 0.01);
					if (full) {
						return;
					}
					const mid: Point = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
					// Beside the edge, on the side away from the middle of the section.
					let [nx, ny] = [(q[1] - p[1]) / (length || 1), -(q[0] - p[0]) / (length || 1)];
					if (nx * (mid[0] - centre[0]) + ny * (mid[1] - centre[1]) < 0) {
						[nx, ny] = [-nx, -ny];
					}
					const [sx, sy] = this.toScreen(mid);
					if (length * this.view.k >= 28) { // only where the number fits along the edge
						const node = svg(group, 'text', { x: sx + nx * 11, y: sy - ny * 11, 'text-anchor': 'middle', 'dominant-baseline': 'central', class: 'edge' });
						node.textContent = formatNumber(length);
					}
				});
			}
		}
	}

	private renderDraft(canvas: SVGSVGElement): void {
		const cursor = this.cursor;
		if (cursor && this.tool !== 'select') {
			const [x, y] = this.toScreen(cursor);
			svg(canvas, 'circle', { cx: x, cy: y, r: 3, class: 'section-snap' });
		}
		const points = cursor ? [...this.draft, cursor] : this.draft;
		if (!points.length) {
			return;
		}
		const dia = this.settings.dia;
		switch (this.tool) {
			case 'rectangle':
			case 'hole':
				if (points.length >= 2) {
					svg(canvas, 'path', { d: this.ringPath(this.corners(points[0], points[points.length - 1])), class: 'section-draft' });
				}
				break;
			case 'polygon':
				svg(canvas, 'path', { d: this.ringPath(points).replace(/ Z$/, ''), class: 'section-draft' });
				break;
			case 'barLine':
				if (points.length >= 2) {
					for (const bar of barsLine(points[0], points[points.length - 1], this.settings.count, dia)) {
						const [x, y] = this.toScreen([bar.x, bar.y]);
						svg(canvas, 'circle', { cx: x, cy: y, r: Math.max(2.5, dia / 2 * this.view.k), class: 'section-bar draft' });
					}
				}
				break;
			case 'barRing':
				if (points.length >= 2) {
					const [c, r] = [points[0], points[points.length - 1]];
					for (const bar of barsRing(c, Math.hypot(r[0] - c[0], r[1] - c[1]), this.settings.count, dia)) {
						const [x, y] = this.toScreen([bar.x, bar.y]);
						svg(canvas, 'circle', { cx: x, cy: y, r: Math.max(2.5, dia / 2 * this.view.k), class: 'section-bar draft' });
					}
				}
				break;
		}
	}

	private corners(a: Point, b: Point): Ring {
		const [xa, xb] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
		const [ya, yb] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
		return rectangle(xb - xa, yb - ya, (xa + xb) / 2, (ya + yb) / 2);
	}

	// ───────────────────────────── panel ─────────────────────────────

	private renderPanel(): void {
		const panel = this.panel;
		const section = this.section;
		if (!panel || !section) {
			return;
		}
		this.panelDisposables.clear();
		clearNode(panel);
		const concrete = this.materials.filter(m => m.category !== 'rebar');
		const rebar = this.materials.filter(m => m.category === 'rebar');

		appendPropertyHeading(panel, localize('section.heading.section', "Section"));
		const form = append(panel, $('.section-form'));
		this.textField(form, localize('section.name', "Name"), section.name, value => this.edit(s => { s.name = value || s.id; }, true));
		this.selectField(form, localize('section.confinement', "Ties"), section.confinement, [['tied', localize('section.tied', "Tied")], ['spiral', localize('section.spiral', "Spiral")]], value => this.edit(s => { s.confinement = value as 'tied' | 'spiral'; }));
		this.selectField(form, localize('section.rebar', "Bar material"), section.rebar ?? '', this.materialOptions(rebar, section.rebar), value => {
			this.settings.rebar = value;
			this.edit(s => { s.rebar = value || undefined; });
		});
		this.numberField(form, localize('section.cover', "Clear cover [mm]"), section.cover ?? 40, value => this.edit(s => { s.cover = value; }, true));

		appendPropertyHeading(panel, localize('section.heading.drawing', "Drawing"));
		const drawing = append(panel, $('.section-form'));
		this.selectField(drawing, localize('section.newMaterial', "New regions"), this.settings.material, this.materialOptions(concrete, this.settings.material), value => { this.settings.material = value; });
		this.selectField(drawing, localize('section.dia', "Bar Ø [mm]"), String(this.settings.dia), BAR_DIAMETERS.map(d => [String(d), String(d)]), value => { this.settings.dia = Number(value); });
		this.numberField(drawing, localize('section.spacing', "Bar spacing [mm]"), this.settings.spacing, value => { this.settings.spacing = value; });
		this.numberField(drawing, localize('section.count', "Bars per line / ring"), this.settings.count, value => { this.settings.count = Math.max(1, Math.round(value)); });
		this.selectField(drawing, localize('section.grid', "Grid [mm]"), String(this.settings.grid), GRID_STEPS.map(g => [String(g), String(g)]), value => {
			this.settings.grid = Number(value);
			this.renderCanvas();
		});

		this.renderTemplateForm(panel);

		const selected = this.selected();
		if (selected) {
			appendPropertyHeading(panel, localize('section.heading.selection', "Selection"));
			const sel = append(panel, $('.section-form'));
			if (this.selection?.kind === 'region') {
				const index = this.selection.index;
				const region = section.regions[index];
				this.selectField(sel, localize('section.material', "Material"), region.material, this.materialOptions(concrete, region.material), value => this.edit(s => { s.regions[index].material = value; }));
				appendPropertyNote(sel, localize('section.regionInfo', "{0} corners, {1} openings", region.outline.length, region.holes.length));
				this.renderVertexTable(panel, index);
			} else if (this.selection?.kind === 'bar') {
				const index = this.selection.index;
				const bar = section.bars[index];
				this.numberField(sel, 'x [mm]', bar.x, value => this.edit(s => { s.bars[index].x = value; }, true));
				this.numberField(sel, 'y [mm]', bar.y, value => this.edit(s => { s.bars[index].y = value; }, true));
				this.selectField(sel, localize('section.barDia', "Ø [mm]"), String(bar.dia), BAR_DIAMETERS.map(d => [String(d), String(d)]), value => this.edit(s => { s.bars[index].dia = Number(value); }));
				appendPropertyNote(sel, localize('section.barArea', "As = {0} mm²", formatNumber(barArea(bar.dia))));
			}
		}

		const analysis = this.analysis;
		if (analysis?.problems.length) {
			appendPropertyHeading(panel, localize('section.heading.problems', "Problems"));
			const list = append(panel, $('ul.section-problems'));
			for (const problem of analysis.problems) {
				append(list, $('li', undefined, problem.message));
			}
		}
		if (analysis?.properties) {
			appendPropertyHeading(panel, localize('section.heading.properties', "Properties"));
			const table = append(panel, $('table.section-properties', { 'aria-label': localize('section.propertiesAria', "Section properties") }));
			for (const row of propertyRows(analysis.properties)) {
				const tr = append(table, $('tr', row.title ? { title: row.title } : undefined));
				append(tr, $('th', { scope: 'row' }, row.label));
				append(tr, $('td.value', undefined, row.value));
				append(tr, $('td.unit', undefined, row.unit));
			}
			appendPropertyNote(panel, localize('section.reference', "Transformed to {0} (E = {1} MPa); bars not included.", analysis.properties.referenceMaterial, formatNumber(analysis.properties.E)));
		}
		if (analysis?.uniaxial) {
			this.renderChart(panel, analysis);
		} else if (analysis?.capacityNote) {
			appendPropertyHeading(panel, localize('section.heading.capacity', "Interaction diagram"));
			appendPropertyNote(panel, localize('section.noCapacity', "No RC capacity: {0}", analysis.capacityNote));
		}
	}

	/** The template this section still is (its regions unchanged since), if any. */
	private currentTemplate(): ITemplateState | undefined {
		const resource = this.resource?.toString();
		const state = resource ? templates.get(resource) : undefined;
		const section = this.section;
		if (!state || !section) {
			return undefined;
		}
		const material = section.regions[0]?.material ?? '';
		return sameRegions(section.regions, templateRegions(state.kind, state.params, material)) ? state : undefined;
	}

	/**
	 * A section drawn from a template keeps its dimensions as a form: changing one redraws the
	 * template (and its bars along the edges). Editing the drawing by hand ends the form.
	 */
	private renderTemplateForm(panel: HTMLElement): void {
		const state = this.currentTemplate();
		if (!state) {
			return;
		}
		appendPropertyHeading(panel, localize('section.heading.template', "Template"), templateLabel(state.kind));
		const form = append(panel, $('.section-form'));
		for (const { key, label } of templateFields(state.kind)) {
			const value = state.params[key] ?? (key === 'tf' ? state.params.t : 0);
			this.numberField(form, label, value, number => {
				const params = { ...state.params, [key]: number, ...(state.kind === 'circle' && key === 'b' ? { h: number } : {}) };
				const problem = templateProblem(state.kind, params);
				if (problem) {
					this.frame.setStatus({ severity: 'warning', text: problem });
					this.renderPanel(); // back to the dimensions that draw
					return;
				}
				this.insertTemplate(state.kind, params);
			});
		}
		appendPropertyNote(panel, localize('section.templateNote', "Changing a dimension redraws the template and its bars. Moving a corner by hand makes it a free shape."));
	}

	/** The corners of the selected region as x, y fields, typed exactly. */
	private renderVertexTable(panel: HTMLElement, index: number): void {
		const region = this.section!.regions[index];
		appendPropertyHeading(panel, localize('section.heading.corners', "Corners"), localize('section.cornersDetail', "mm"));
		const table = append(panel, $('table.section-vertices', { 'aria-label': localize('section.verticesAria', "Corners of the selected region") }));
		const head = append(table, $('tr'));
		for (const text of ['#', 'x', 'y']) {
			append(head, $('th', { scope: 'col' }, text));
		}
		region.outline.forEach(([x, y], corner) => {
			const tr = append(table, $('tr'));
			append(tr, $('td.index', undefined, String(corner + 1)));
			for (const [axis, value] of [[0, x], [1, y]] as const) {
				const input = append(append(tr, $('td')), $<HTMLInputElement>('input.section-input', {
					type: 'number', value: String(value), step: 'any',
					'aria-label': localize('section.cornerAria', "Corner {0} {1}", corner + 1, axis ? 'y' : 'x'),
				}));
				this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, () => {
					const number = Number(input.value);
					if (input.value.trim() !== '' && Number.isFinite(number)) {
						this.edit(s => {
							const point = [...s.regions[index].outline[corner]] as [number, number];
							point[axis] = number;
							s.regions[index].outline[corner] = point;
						});
					}
				}));
			}
		});
	}

	private renderChart(panel: HTMLElement, analysis: ISectionAnalysis): void {
		const heading = appendPropertyHeading(panel, localize('section.heading.capacity', "Interaction diagram"));
		const expand = append(heading, $<HTMLButtonElement>('button.section-chart-expand', { type: 'button', title: localize('section.expandChart', "Show the diagram larger") }));
		append(expand, $(ThemeIcon.asCSSSelector(Codicon.screenFull)));
		this.panelDisposables.add(addDisposableListener(expand, EventType.CLICK, () => this.showLargeChart(analysis)));
		const axes = append(panel, $('.sa-segmented.section-axes', { role: 'tablist', 'aria-label': localize('section.axisAria', "Bending axis") }));
		for (const axis of ['x', 'y'] as const) {
			const button = append(axes, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab', 'aria-selected': String(this.chartAxis === axis) }, axis === 'x' ? localize('section.aboutX', "About x (Mx)") : localize('section.aboutY', "About y (My)")));
			button.classList.toggle('active', this.chartAxis === axis);
			this.panelDisposables.add(addDisposableListener(button, EventType.CLICK, () => {
				this.chartAxis = axis;
				this.renderPanel();
			}));
		}
		const diagram: IUniaxial = analysis.uniaxial![this.chartAxis];
		this.drawChart(append(panel, $('.section-chart')), diagram, 260);
		if (analysis.phi) {
			appendPropertyNote(panel, localize('section.phiNote', "φ from the code pack: {0} tension-controlled, {1} compression-controlled; φPn,max = {2} kN, P0 = {3} kN.", analysis.phi.tension, analysis.phi.compression, formatNumber(diagram.phiPnMax / 1e3), formatNumber(diagram.p0 / 1e3)));
		}
	}

	/** The P-M diagram about the chosen axis, in MN when the loads are large (short tick labels). */
	private drawChart(container: HTMLElement, diagram: IUniaxial, height: number): void {
		const nominal = interactionCurve(diagram, false);
		const design = interactionCurve(diagram, true);
		const mega = Math.max(...nominal.map(([, p]) => Math.abs(p)), 0) >= MN_FROM;
		const scale = (points: number[][]) => mega ? points.map(([m, p]) => [m, p / 1e3]) : points;
		renderChart(container, {
			title: localize('section.chartTitle', "P-M interaction about {0}", this.chartAxis),
			xLabel: this.chartAxis === 'x' ? 'Mx [kN·m]' : 'My [kN·m]',
			yLabel: mega ? 'P [MN]' : 'P [kN]',
			xFormat: formatNumber,
			yFormat: formatNumber,
			series: [
				{ name: localize('section.nominal', "Nominal Pn, Mn"), color: 'foreground', style: 'dashed', points: scale(nominal) },
				{ name: localize('section.design', "Design φPn, φMn"), color: 'blue', points: scale(design) },
			],
			caption: localize('section.chartAria', "P-M interaction diagram about {0}: φPn,max {1} kN", this.chartAxis, formatNumber(diagram.phiPnMax / 1e3)),
			height,
		});
	}

	/** The diagram over the drawing, as large as the editor allows; Escape or Close returns. */
	private showLargeChart(analysis: ISectionAnalysis): void {
		const host = this.canvas.parentElement!; // the canvas host, positioned
		this.chartOverlay?.remove();
		const overlay = this.chartOverlay = append(host, $('.section-chart-overlay', { role: 'dialog', 'aria-label': localize('section.chartLarge', "Interaction diagram") }));
		const bar = append(overlay, $('.section-chart-overlay-bar'));
		const axes = append(bar, $('.sa-segmented', { role: 'tablist' }));
		const close = append(bar, $<HTMLButtonElement>('button.section-chart-close', { type: 'button' }, localize('section.closeChart', "Close")));
		const body = append(overlay, $('.section-chart'));
		const draw = () => {
			clearNode(axes);
			for (const axis of ['x', 'y'] as const) {
				const button = append(axes, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab', 'aria-selected': String(this.chartAxis === axis) }, axis === 'x' ? localize('section.aboutX', "About x (Mx)") : localize('section.aboutY', "About y (My)")));
				button.classList.toggle('active', this.chartAxis === axis);
				button.addEventListener('click', () => {
					this.chartAxis = axis;
					draw();
					this.renderPanel();
				});
			}
			clearNode(body);
			this.drawChart(body, analysis.uniaxial![this.chartAxis], Math.max(240, host.clientHeight - 150));
		};
		const dismiss = () => {
			overlay.remove();
			this.canvas.focus();
		};
		close.addEventListener('click', dismiss);
		overlay.addEventListener('keydown', e => {
			if (e.key === 'Escape') {
				e.preventDefault();
				dismiss();
			}
		});
		draw();
		close.focus();
	}

	private materialOptions(materials: readonly IMaterialChoice[], current: string | undefined): [string, string][] {
		const list: [string, string][] = materials.map(m => [m.id, m.name === m.id ? m.id : `${m.id} (${m.name})`]);
		if (current && !materials.some(m => m.id === current)) {
			list.unshift([current, current]);
		}
		return list;
	}

	private field(container: HTMLElement, label: string): HTMLElement {
		const row = append(container, $('label.section-field'));
		append(row, $('span.name', undefined, label));
		return row;
	}

	private textField(container: HTMLElement, label: string, value: string, change: (value: string) => void): void {
		const input = append(this.field(container, label), $<HTMLInputElement>('input.section-input', { type: 'text', value, spellcheck: 'false' }));
		this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, () => change(input.value.trim())));
	}

	private numberField(container: HTMLElement, label: string, value: number, change: (value: number) => void): void {
		const input = append(this.field(container, label), $<HTMLInputElement>('input.section-input', { type: 'number', value: String(value), step: 'any' }));
		this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, () => {
			const number = Number(input.value);
			if (Number.isFinite(number)) {
				change(number);
			}
		}));
	}

	private selectField(container: HTMLElement, label: string, value: string, options: readonly (readonly [string, string])[], change: (value: string) => void): void {
		const select = append(this.field(container, label), $<HTMLSelectElement>('select.section-select'));
		for (const [id, text] of options) {
			const option = append(select, $<HTMLOptionElement>('option', { value: id }, text));
			option.selected = id === value;
		}
		this.panelDisposables.add(addDisposableListener(select, EventType.CHANGE, () => change(select.value)));
	}

	// ───────────────────────────── tools ─────────────────────────────

	private setTool(tool: Tool): void {
		this.tool = tool;
		this.draft = [];
		this.updateToolButtons();
		this.renderCanvas();
		this.canvas.focus();
	}

	private updateToolButtons(): void {
		for (const [tool, button] of this.toolButtons) {
			button.classList.toggle('active', tool === this.tool);
			button.setAttribute('aria-pressed', String(tool === this.tool));
		}
		this.canvas?.setAttribute('data-tool', this.tool);
	}

	private selected(): object | undefined {
		const s = this.section;
		if (!s || !this.selection) {
			return undefined;
		}
		return this.selection.kind === 'bar' ? s.bars[this.selection.index] : s.regions[this.selection.index];
	}

	private select(selection: Selection): void {
		this.selection = selection;
		this.render();
	}

	private snapped(e: PointerEvent | MouseEvent): Point {
		return snapPoint(this.toWorld(e.clientX, e.clientY), this.settings.grid);
	}

	private onPointerDown(e: PointerEvent): void {
		if (!this.section || e.button > 1) {
			return;
		}
		this.canvas.focus();
		this.canvas.setPointerCapture(e.pointerId);
		const point = this.snapped(e);
		const exact = this.toWorld(e.clientX, e.clientY);
		if (e.button === 1 || this.tool === 'select') {
			const hit = e.button === 1 ? undefined : hitTest(this.section, exact, 4 / this.view.k);
			if (hit && (hit.kind !== this.selection?.kind || hit.index !== this.selection.index)) {
				this.select(hit);
			}
			this.drag = { start: point, last: point, moved: false, pan: hit ? undefined : { x: e.clientX, y: e.clientY } };
			if (!hit && e.button === 0 && this.selection) {
				this.select(undefined);
			}
			return;
		}
		switch (this.tool) {
			case 'rectangle':
			case 'hole':
				this.draft = [point];
				break;
			case 'polygon':
				this.draft.push(point);
				break;
			case 'bar':
				this.addBars([{ x: point[0], y: point[1], dia: this.settings.dia }]);
				break;
			case 'barLine':
			case 'barRing':
				if (!this.draft.length) {
					this.draft = [point];
				} else {
					this.finishBars(point);
				}
				break;
		}
		this.renderCanvas();
	}

	private onPointerMove(e: PointerEvent): void {
		const point = this.snapped(e);
		const drag = this.drag;
		if (drag?.pan) {
			this.view.ox += e.clientX - drag.pan.x;
			this.view.oy += e.clientY - drag.pan.y;
			drag.pan = { x: e.clientX, y: e.clientY };
			this.renderCanvas();
			return;
		}
		if (drag && this.selection && (point[0] !== drag.last[0] || point[1] !== drag.last[1])) {
			moveSelection(this.section!, this.selection, point[0] - drag.last[0], point[1] - drag.last[1]);
			drag.last = point;
			drag.moved = true;
			this.renderCanvas();
			return;
		}
		if (this.tool !== 'select') {
			this.cursor = point;
			this.renderCanvas();
		}
	}

	private onPointerUp(e: PointerEvent): void {
		if (this.canvas.hasPointerCapture(e.pointerId)) {
			this.canvas.releasePointerCapture(e.pointerId);
		}
		const drag = this.drag;
		this.drag = undefined;
		if (drag?.moved) {
			this.edit(() => { });
			return;
		}
		if ((this.tool === 'rectangle' || this.tool === 'hole') && this.draft.length) {
			const a = this.draft[0], b = this.snapped(e);
			this.draft = [];
			if (a[0] !== b[0] && a[1] !== b[1]) {
				this.addRectangle(this.corners(a, b), this.tool === 'hole');
			} else {
				this.renderCanvas();
			}
		}
	}

	private onWheel(e: WheelEvent): void {
		e.preventDefault();
		const box = this.canvas.getBoundingClientRect();
		const factor = Math.exp(-e.deltaY * 0.0015);
		const mx = e.clientX - box.left, my = e.clientY - box.top;
		this.view = { k: this.view.k * factor, ox: mx - (mx - this.view.ox) * factor, oy: my - (my - this.view.oy) * factor };
		this.renderCanvas();
	}

	private onKey(e: StandardKeyboardEvent): void {
		const tool = TOOLS.find(t => t.key === e.keyCode);
		if (tool && !e.ctrlKey && !e.altKey && !e.metaKey) {
			this.setTool(tool.tool);
			e.preventDefault();
			return;
		}
		const step = this.settings.grid;
		const arrows: { [key: number]: Point } = { [KeyCode.LeftArrow]: [-step, 0], [KeyCode.RightArrow]: [step, 0], [KeyCode.UpArrow]: [0, step], [KeyCode.DownArrow]: [0, -step] };
		const arrow = arrows[e.keyCode];
		if (arrow && this.selection) {
			this.edit(s => moveSelection(s, this.selection, arrow[0], arrow[1]));
			e.preventDefault();
			return;
		}
		switch (e.keyCode) {
			case KeyCode.Escape:
				if (this.draft.length) {
					this.draft = [];
					this.renderCanvas();
				} else if (this.selection) {
					this.select(undefined);
				}
				e.preventDefault();
				break;
			case KeyCode.Enter:
				this.closePolygon();
				e.preventDefault();
				break;
			case KeyCode.Backspace:
				if (this.draft.length) {
					this.draft.pop();
					this.renderCanvas();
					e.preventDefault();
				}
				break;
			case KeyCode.Delete:
				this.deleteSelection();
				e.preventDefault();
				break;
			case KeyCode.Tab:
				if (this.section && (this.section.regions.length || this.section.bars.length) && !e.ctrlKey) {
					this.cycleSelection(e.shiftKey ? -1 : 1);
					e.preventDefault();
				}
				break;
		}
	}

	/** Tab walks the regions and bars, so everything can be selected from the keyboard. */
	private cycleSelection(direction: number): void {
		const s = this.section!;
		const all: Selection[] = [...s.regions.map((_, index) => ({ kind: 'region' as const, index })), ...s.bars.map((_, index) => ({ kind: 'bar' as const, index }))];
		const current = all.findIndex(item => item?.kind === this.selection?.kind && item?.index === this.selection?.index);
		this.select(all[(current + direction + all.length + (current < 0 && direction < 0 ? 1 : 0)) % all.length]);
	}

	private closePolygon(): void {
		if (this.tool !== 'polygon' || this.draft.length < 3) {
			return;
		}
		const outline = this.draft;
		this.draft = [];
		this.edit(s => { s.regions.push({ outline, holes: [], material: this.settings.material || s.regions[0]?.material || 'C30' }); });
	}

	private addRectangle(ring: Ring, hole: boolean): void {
		this.edit(s => {
			if (hole) {
				const centre: Point = [(ring[0][0] + ring[2][0]) / 2, (ring[0][1] + ring[2][1]) / 2];
				const region = s.regions.find(r => pointInRegion(centre, r));
				region?.holes.push(ring);
				// An opening removes the bars inside it.
				s.bars = s.bars.filter(b => !(b.x > ring[0][0] && b.x < ring[2][0] && b.y > ring[0][1] && b.y < ring[2][1]));
			} else {
				s.regions.push({ outline: ring, holes: [], material: this.settings.material || s.regions[0]?.material || 'C30' });
			}
		});
	}

	private addBars(bars: IBar[]): void {
		this.edit(s => {
			if (!s.rebar && this.settings.rebar) {
				s.rebar = this.settings.rebar;
			}
			s.bars.push(...bars);
		});
	}

	private finishBars(end: Point): void {
		const start = this.draft[0];
		this.draft = [];
		const { count, dia } = this.settings;
		this.addBars(this.tool === 'barLine' ? barsLine(start, end, count, dia) : barsRing(start, Math.hypot(end[0] - start[0], end[1] - start[1]), count, dia));
	}

	private barsAlongEdges(): void {
		const s = this.section;
		if (!s) {
			return;
		}
		const categories = new Map(this.materials.map(m => [m.id, m.category]));
		const indices = this.selection?.kind === 'region' ? [this.selection.index] : s.regions.map((_, i) => i);
		const inset = (s.cover ?? 40) + TIE_DIA + this.settings.dia / 2;
		const bars = indices
			.filter(i => (categories.get(s.regions[i].material) ?? 'concrete') === 'concrete')
			.flatMap(i => barsAlongEdges(s.regions[i], inset, this.settings.dia, this.settings.spacing));
		this.addBars(bars.filter(b => !s.bars.some(o => Math.hypot(o.x - b.x, o.y - b.y) < (o.dia + b.dia) / 2)));
	}

	private deleteSelection(): void {
		const selection = this.selection;
		if (!selection) {
			return;
		}
		this.selection = undefined;
		this.edit(s => {
			if (selection.kind === 'bar') {
				s.bars.splice(selection.index, 1);
			} else if (s.regions.length > 1) {
				const [region] = s.regions.splice(selection.index, 1);
				s.bars = s.bars.filter(b => !pointInRegion([b.x, b.y], region));
			}
		});
	}

	private insertTemplate(kind: TemplateKind, params: ITemplateParams = TEMPLATE_DEFAULTS[kind]): void {
		const material = this.settings.material || this.section?.regions[0]?.material || 'C30';
		const steel = this.materials.find(m => m.id === material)?.category === 'steel';
		const resource = this.resource?.toString();
		if (resource) {
			templates.set(resource, { kind, params });
		}
		this.selection = undefined;
		this.edit(s => {
			s.regions = templateRegions(kind, params, material);
			s.bars = [];
			if (!steel && kind !== 'I') {
				const inset = (s.cover ?? 40) + TIE_DIA + this.settings.dia / 2;
				s.bars = s.regions.flatMap(r => barsAlongEdges(r, inset, this.settings.dia, this.settings.spacing));
				s.rebar ||= this.settings.rebar || undefined;
			}
		});
		this.fit();
		this.renderCanvas();
	}
}
