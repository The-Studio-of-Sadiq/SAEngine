/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femStrutAndTie.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { Action, Separator } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { checkStmModel, emptyStmModel, formatUtilisation, IFemDesignCheck, IStmFile, IStmMember, IStmModel, IStmNode, IStmResult, nextStmId, parseStmFile, stmFile, stmTemplate } from './femDesign.js';
import { FemStrutAndTieInput } from './femStrutAndTieInput.js';

/** What a click on the drawing does. */
type StmTool = 'select' | 'node' | 'strut' | 'tie';

/** What is selected: a node or a member by id. */
type StmSelection = { readonly kind: 'node' | 'member'; readonly id: string } | undefined;

const SVG_NS = 'http://www.w3.org/2000/svg';
/** New nodes snap to this grid [mm]. */
const SNAP = 25;
/** Margin around the model in the drawing [px]. */
const MARGIN = 48;

const TEMPLATES: readonly { readonly id: string; readonly label: string; readonly detail: string }[] = [
	{ id: 'deepBeam', label: localize('femStm.tplDeepBeam', "Deep Beam"), detail: localize('femStm.tplDeepBeamDetail', "A simply supported deep beam with a point load at mid-span") },
	{ id: 'dappedEnd', label: localize('femStm.tplDapped', "Dapped End"), detail: localize('femStm.tplDappedDetail', "A beam end with a nib on a bearing, with its hanger and nib ties") },
	{ id: 'corbel', label: localize('femStm.tplCorbel', "Corbel"), detail: localize('femStm.tplCorbelDetail', "A corbel with a vertical and a horizontal load, held by its column") },
	{ id: 'frameCorner', label: localize('femStm.tplCorner', "Frame Corner"), detail: localize('femStm.tplCornerDetail', "A beam-column knee under a closing moment") },
];

const SUPPORTS: readonly { readonly value: IStmNode['support']; readonly label: string }[] = [
	{ value: '', label: localize('femStm.supportNone', "Free") },
	{ value: 'pin', label: localize('femStm.supportPin', "Pin (holds x and y)") },
	{ value: 'rollerX', label: localize('femStm.supportRollerX', "Roller (holds y)") },
	{ value: 'rollerY', label: localize('femStm.supportRollerY', "Roller (holds x)") },
];

const ANCHORAGES: readonly { readonly value: IStmNode['anchorage']; readonly label: string }[] = [
	{ value: '', label: localize('femStm.anchorNone', "Not given") },
	{ value: 'hook', label: localize('femStm.anchorHook', "Standard hooks") },
	{ value: 'plate', label: localize('femStm.anchorPlate', "Bearing plate or device") },
	{ value: 'through', label: localize('femStm.anchorThrough', "Bars run through") },
];

const SHAPES: readonly { readonly value: IStmMember['shape']; readonly label: string }[] = [
	{ value: 'bottle', label: localize('femStm.shapeBottle', "Bottle-shaped") },
	{ value: 'prism', label: localize('femStm.shapePrism', "Uniform (prism)") },
	{ value: 'tension', label: localize('femStm.shapeTension', "In a tension member or flange") },
	{ value: 'other', label: localize('femStm.shapeOther', "Other") },
];

function newMember(id: string, start: string, end: string, kind: 'strut' | 'tie'): IStmMember {
	return { id, start, end, kind, width: kind === 'strut' ? 150 : 0, shape: 'bottle', steelArea: 0, barArea: 0, barDiameter: 16, prestressArea: 0, fse: 0, fpy: 0, bonded: true };
}

function newNode(id: string, x: number, y: number): IStmNode {
	return { id, x, y, support: '', bearing: 0, anchorage: '', anchorLength: 0 };
}

/**
 * Strut-and-Tie Models: draw and check a strut-and-tie model of any D-region (a dapped end, a
 * corbel, a frame corner, a wall or beam with an opening). The engineer lays out nodes, struts
 * and ties (or starts from a template), puts the factored forces from the analysis on the nodes
 * case by case, and the backend (`saengine.design.strutAndTie`) solves the truss and checks every
 * strut, tie and nodal zone with the active code pack's procedure. The models are saved in
 * `08 FEM/strut-and-tie.json` as they are edited.
 */
export class FemStrutAndTieEditor extends EditorPane {

	static readonly ID = FemStrutAndTieInput.EDITOR_ID;

	private frame!: EditorFrame;
	private host!: HTMLElement;
	private svg!: SVGSVGElement;
	private modelSelect!: HTMLSelectElement;
	private file: IStmFile = { models: [] };
	private current = 0;
	private caseIndex = 0;
	private tool: StmTool = 'select';
	private selection: StmSelection;
	/** First node of a member being drawn. */
	private pending: string | undefined;
	private result: IStmResult | undefined;
	private problem: string | undefined;
	private checking = false;
	private request = 0;
	private loaded = false;
	/** mm -> px of the last drawing. */
	private view = { scale: 0.1, x0: 0, y0: 0, height: 0 };

	private readonly renderStore = this._register(new DisposableStore());
	private readonly propertiesStore = this._register(new DisposableStore());
	private readonly saveScheduler = this._register(new RunOnceScheduler(() => this.saveAndCheck(), 400));

	private readonly toolActions: Record<StmTool, Action>;
	private readonly deleteAction = this._register(new Action('saengine.fem.stm.delete', localize('femStm.delete', "Delete Selected"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteSelected()));
	private readonly checkAction = this._register(new Action('saengine.fem.stm.check', localize('femStm.check', "Check Again"), ThemeIcon.asClassName(Codicon.refresh), true, async () => this.check()));
	private readonly newAction = this._register(new Action('saengine.fem.stm.new', localize('femStm.new', "New Model..."), undefined, true, () => this.newModel()));
	private readonly templateAction = this._register(new Action('saengine.fem.stm.template', localize('femStm.fromTemplate', "New Model from Template..."), undefined, true, () => this.newFromTemplate()));
	private readonly renameAction = this._register(new Action('saengine.fem.stm.rename', localize('femStm.rename', "Rename Model..."), undefined, true, () => this.renameModel()));
	private readonly removeAction = this._register(new Action('saengine.fem.stm.remove', localize('femStm.remove', "Delete Model"), undefined, true, async () => this.removeModel()));
	private readonly addCaseAction = this._register(new Action('saengine.fem.stm.addCase', localize('femStm.addCase', "Add Load Case..."), undefined, true, () => this.addCase()));
	private readonly openJsonAction = this._register(new Action('saengine.fem.stm.openJson', localize('femStm.openJson', "Open strut-and-tie.json"), undefined, true, () => this.openJson()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(FemStrutAndTieEditor.ID, group, telemetryService, themeService, storageService);
		const tool = (id: StmTool, label: string, icon: ThemeIcon) => this._register(new Action(`saengine.fem.stm.tool.${id}`, label, ThemeIcon.asClassName(icon), true, async () => this.setTool(id)));
		this.toolActions = {
			select: tool('select', localize('femStm.toolSelect', "Select"), Codicon.inspect),
			node: tool('node', localize('femStm.toolNode', "Add Node (click the drawing)"), Codicon.circleLargeOutline),
			strut: tool('strut', localize('femStm.toolStrut', "Add Strut (click two nodes)"), Codicon.dash),
			tie: tool('tie', localize('femStm.toolTie', "Add Tie (click two nodes)"), Codicon.arrowBoth),
		};
		this.toolActions.select.checked = true;
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: FemStrutAndTieEditor.ID,
			ariaLabel: localize('femStm.toolbar', "Strut-and-Tie Models"),
			properties: { title: localize('femStm.properties', "Properties"), defaultWidth: 340 },
		}));
		this.frame.element.classList.add('saengine-fem-stm-editor');
		this.modelSelect = append(this.frame.titleSlot, $<HTMLSelectElement>('select.fem-stm-select', { 'aria-label': localize('femStm.modelAria', "Strut-and-tie model shown") }));
		this._register(addDisposableListener(this.modelSelect, EventType.CHANGE, () => {
			this.current = this.modelSelect.selectedIndex;
			this.caseIndex = 0;
			this.selection = undefined;
			this.result = undefined;
			this.render();
			void this.check();
		}));
		this.frame.setHelp(localize('femStm.help', "Draw a strut-and-tie model of a D-region the deep-beam checks do not cover: a dapped end, a corbel with several loads, a frame corner, a wall or beam with an opening. Lay out nodes, struts and ties (or start from a template) in the region's plane, x along the member and y up, in mm; hold its boundary with supports and put the factored forces from the analysis on its nodes, one load case per combination. The truss is solved for every case and each strut, tie and nodal zone is checked with the strut-and-tie procedure of the project's code pack. The models are saved in 08 FEM/strut-and-tie.json."));
		this.frame.setActions(
			[this.toolActions.select, this.toolActions.node, this.toolActions.strut, this.toolActions.tie, this.deleteAction, this.checkAction, this.frame.togglePropertiesAction],
			[this.templateAction, this.newAction, this.renameAction, this.removeAction, new Separator(), this.addCaseAction, new Separator(), this.openJsonAction],
		);
		this.host = append(this.frame.main, $('.fem-stm-host'));
		this.svg = document.createElementNS(SVG_NS, 'svg');
		this.svg.classList.add('fem-stm-canvas');
		this.svg.setAttribute('role', 'img');
		this.svg.setAttribute('aria-label', localize('femStm.drawingAria', "Drawing of the strut-and-tie model"));
		this.host.appendChild(this.svg);
		this._register(addDisposableListener(this.svg, EventType.CLICK, e => this.onClick(e)));
		this._register(addDisposableListener(this.host, EventType.KEY_DOWN, e => {
			if (e.key === 'Delete') {
				void this.deleteSelected();
			} else if (e.key === 'Escape') {
				this.pending = undefined;
				this.setTool('select');
			}
		}));
		this.host.tabIndex = 0;
		this._register(this.frame.onDidLayoutMain(() => this.renderDrawing()));
	}

	override async setInput(input: FemStrutAndTieInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		const changed = !this.input || !input.matches(this.input);
		await super.setInput(input, options, context, token);
		if (changed) {
			await this.load(input.region);
		}
	}

	override clearInput(): void {
		this.saveScheduler.flush();
		this.request++;
		this.loaded = false;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.host.focus();
	}

	private get analysisModel(): URI | undefined {
		return (this.input as FemStrutAndTieInput | undefined)?.model;
	}

	private get model(): IStmModel | undefined {
		return this.file.models[this.current];
	}

	// ── file ──

	private async load(region: string | undefined): Promise<void> {
		const target = this.analysisModel;
		if (!target) {
			return;
		}
		let text: string | undefined;
		try {
			text = (await this.fileService.readFile(stmFile(target))).value.toString();
		} catch {
			text = undefined;
		}
		this.file = parseStmFile(text);
		this.current = Math.max(0, region ? this.file.models.findIndex(m => m.name === region || m.member === region) : 0);
		this.caseIndex = 0;
		this.selection = undefined;
		this.result = undefined;
		this.loaded = true;
		this.render();
		void this.check();
	}

	/** Saves the file (debounced) and checks the model shown again. */
	private changed(): void {
		this.render();
		this.saveScheduler.schedule();
	}

	private async saveAndCheck(): Promise<void> {
		const target = this.analysisModel;
		if (!target || !this.loaded) {
			return;
		}
		const content = { $schema: this.file.$schema ?? 'saengine.strutAndTie/1', models: this.file.models };
		try {
			await this.fileService.writeFile(stmFile(target), VSBuffer.fromString(JSON.stringify(content, undefined, '\t') + '\n'));
			this.problem = undefined;
		} catch (error) {
			this.problem = localize('femStm.saveFailed', "The models could not be saved: {0}", error instanceof Error ? error.message : String(error));
		}
		await this.check();
	}

	private async check(): Promise<void> {
		const model = this.model;
		const request = ++this.request;
		if (!model) {
			this.result = undefined;
			this.renderStatus();
			return;
		}
		this.checking = true;
		this.frame.showProgress();
		this.renderStatus();
		try {
			const result = await checkStmModel(this.commandService, model, this.analysisModel);
			if (request !== this.request) {
				return;
			}
			this.result = result;
			this.problem = result ? this.problem : localize('femStm.noBackend', "The design backend is not available in this build: the model is saved but not checked.");
		} catch (error) {
			if (request !== this.request) {
				return;
			}
			this.result = undefined;
			this.problem = error instanceof Error ? error.message : String(error);
		} finally {
			if (request === this.request) {
				this.checking = false;
				this.frame.hideProgress();
				this.render();
			}
		}
	}

	private async openJson(): Promise<void> {
		const target = this.analysisModel;
		if (target) {
			this.saveScheduler.flush();
			await this.editorService.openEditor({ resource: stmFile(target), options: { override: 'default', pinned: true } });
		}
	}

	// ── models ──

	private async newModel(): Promise<void> {
		const name = await this.quickInputService.input({
			prompt: localize('femStm.newPrompt', "Name of the D-region (for example \"Dapped end of B12\")"),
			value: nextStmId(localize('femStm.regionPrefix', "Region "), this.file.models.map(m => m.name)),
		});
		if (!name) {
			return;
		}
		this.file.models.push(emptyStmModel(name));
		this.current = this.file.models.length - 1;
		this.selection = undefined;
		this.result = undefined;
		this.setTool('node');
		this.changed();
	}

	private async newFromTemplate(): Promise<void> {
		const picked = await this.quickInputService.pick(TEMPLATES.map<IQuickPickItem & { id: string }>(t => ({ id: t.id, label: t.label, detail: t.detail })), {
			placeHolder: localize('femStm.templatePlaceholder', "Template to start from (sizes and loads are changed afterwards)"),
		});
		if (!picked) {
			return;
		}
		const made = await stmTemplate(this.commandService, picked.id);
		if (!made || typeof made === 'string') {
			this.problem = typeof made === 'string' ? made : localize('femStm.noBackend', "The design backend is not available in this build: the model is saved but not checked.");
			this.renderStatus();
			return;
		}
		const taken = this.file.models.map(m => m.name);
		const name = taken.includes(made.name) ? nextStmId(`${made.name} `, taken) : made.name;
		this.file.models.push({ ...made, name });
		this.current = this.file.models.length - 1;
		this.caseIndex = 0;
		this.selection = undefined;
		this.result = undefined;
		this.changed();
	}

	private async renameModel(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		const name = await this.quickInputService.input({ prompt: localize('femStm.renamePrompt', "New name of the model"), value: model.name });
		if (name) {
			model.name = name;
			this.changed();
		}
	}

	private async removeModel(): Promise<void> {
		if (!this.model) {
			return;
		}
		this.file.models.splice(this.current, 1);
		this.current = Math.max(0, Math.min(this.current, this.file.models.length - 1));
		this.selection = undefined;
		this.result = undefined;
		this.changed();
	}

	private async addCase(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		const name = await this.quickInputService.input({
			prompt: localize('femStm.casePrompt', "Name of the load case: the factored combination its forces come from"),
			value: nextStmId('U', model.cases.map(c => c.name)),
		});
		if (name && !model.cases.some(c => c.name === name)) {
			model.cases.push({ name, loads: [] });
			this.caseIndex = model.cases.length - 1;
			this.changed();
		}
	}

	// ── drawing tools ──

	private setTool(tool: StmTool): void {
		this.tool = tool;
		this.pending = undefined;
		for (const [id, action] of Object.entries(this.toolActions)) {
			action.checked = id === tool;
		}
		this.renderDrawing();
		this.renderStatus();
	}

	private async deleteSelected(): Promise<void> {
		const model = this.model;
		const selection = this.selection;
		if (!model || !selection) {
			return;
		}
		if (selection.kind === 'member') {
			model.members = model.members.filter(m => m.id !== selection.id);
		} else {
			model.nodes = model.nodes.filter(n => n.id !== selection.id);
			model.members = model.members.filter(m => m.start !== selection.id && m.end !== selection.id);
			for (const c of model.cases) {
				c.loads = c.loads.filter(l => l.node !== selection.id);
			}
		}
		this.selection = undefined;
		this.changed();
	}

	/** The point [mm] under a click on the drawing. */
	private toModel(e: MouseEvent): { x: number; y: number } {
		const box = this.svg.getBoundingClientRect();
		const px = e.clientX - box.left;
		const py = e.clientY - box.top;
		return { x: (px - this.view.x0) / this.view.scale, y: (this.view.y0 - py) / this.view.scale };
	}

	private onClick(e: MouseEvent): void {
		const model = this.model;
		if (!model) {
			return;
		}
		const target = (e.target as Element | null)?.closest('[data-node],[data-member]');
		const nodeId = target?.getAttribute('data-node') ?? undefined;
		const memberId = target?.getAttribute('data-member') ?? undefined;
		if (this.tool === 'node' && !nodeId) {
			const at = this.toModel(e);
			const id = nextStmId('N', model.nodes.map(n => n.id));
			model.nodes.push(newNode(id, Math.round(at.x / SNAP) * SNAP, Math.round(at.y / SNAP) * SNAP));
			this.selection = { kind: 'node', id };
			this.changed();
			return;
		}
		if ((this.tool === 'strut' || this.tool === 'tie') && nodeId) {
			if (!this.pending) {
				this.pending = nodeId;
				this.selection = { kind: 'node', id: nodeId };
				this.render();
				return;
			}
			if (this.pending !== nodeId && !model.members.some(m => (m.start === this.pending && m.end === nodeId) || (m.start === nodeId && m.end === this.pending))) {
				const id = nextStmId(this.tool === 'strut' ? 'S' : 'T', model.members.map(m => m.id));
				model.members.push(newMember(id, this.pending, nodeId, this.tool));
				this.selection = { kind: 'member', id };
				this.pending = undefined;
				this.changed();
				return;
			}
			this.pending = undefined;
			this.render();
			return;
		}
		this.selection = nodeId ? { kind: 'node', id: nodeId } : memberId ? { kind: 'member', id: memberId } : undefined;
		this.render();
	}

	// ── render ──

	private render(): void {
		this.renderStore.clear();
		clearNode(this.modelSelect);
		this.file.models.forEach((m, k) => {
			const option = append(this.modelSelect, $<HTMLOptionElement>('option', { value: String(k) }, m.name));
			option.selected = k === this.current;
		});
		this.modelSelect.disabled = !this.file.models.length;
		const model = this.model;
		this.deleteAction.enabled = !!this.selection;
		for (const action of [this.renameAction, this.removeAction, this.addCaseAction, this.checkAction, ...Object.values(this.toolActions)]) {
			action.enabled = !!model;
		}
		if (!model) {
			this.frame.setEmpty({
				icon: Codicon.symbolStructure,
				title: localize('femStm.emptyTitle', "No strut-and-tie models yet"),
				text: localize('femStm.emptyText', "Model a D-region the deep-beam and corbel checks do not cover: a dapped end, a corbel with several loads, a frame corner, a wall or beam with an opening. Start from a template or draw the struts and ties yourself."),
				actions: [
					{ label: localize('femStm.fromTemplateButton', "Start from a Template"), primary: true, run: () => void this.newFromTemplate() },
					{ label: localize('femStm.blankButton', "Draw a New Model"), run: () => void this.newModel() },
				],
			});
		} else {
			this.frame.setEmpty(undefined);
		}
		this.renderDrawing();
		this.renderProperties();
		this.renderStatus();
	}

	private renderStatus(): void {
		const model = this.model;
		if (this.problem) {
			this.frame.setStatus({ text: this.problem, severity: 'error' });
		} else if (!model) {
			this.frame.setStatus(undefined);
		} else if (this.tool === 'node') {
			this.frame.setStatus({ text: localize('femStm.statusNode', "Click the drawing to place a node (snapped to {0} mm); Escape to stop.", SNAP) });
		} else if (this.tool === 'strut' || this.tool === 'tie') {
			this.frame.setStatus({ text: this.pending ? localize('femStm.statusSecond', "Click the node at the other end of the member from {0}.", this.pending) : localize('femStm.statusFirst', "Click the node at one end of the new member.") });
		} else if (this.checking) {
			this.frame.setStatus({ text: localize('femStm.checking', "Solving and checking the model..."), busy: true });
		} else if (this.result?.problems.length) {
			this.frame.setStatus({ text: this.result.problems[0], severity: 'warning' });
		} else if (this.result && this.result.covered === false) {
			this.frame.setStatus({ text: localize('femStm.notCovered', "The code pack {0} does not cover strut-and-tie models of any D-region: the checks use its strut-and-tie values as given.", this.result.code ?? ''), severity: 'warning' });
		} else if (this.result) {
			const failing = this.result.checks.filter(c => !c.ok).length;
			this.frame.setStatus({
				text: failing
					? localize('femStm.statusFails', "{0}: {1} of {2} checks fail, {3}.", model.name, failing, this.result.checks.length, formatUtilisation(this.result.utilisation ?? 0))
					: localize('femStm.statusPasses', "{0}: all {1} checks pass, {2}.", model.name, this.result.checks.length, formatUtilisation(this.result.utilisation ?? 0)),
				severity: failing ? 'warning' : undefined,
				icon: failing ? undefined : Codicon.pass,
			});
		} else {
			this.frame.setStatus(undefined);
		}
	}

	private svgEl<K extends keyof SVGElementTagNameMap>(parent: Element, tag: K, attrs: Record<string, string | number>, text?: string): SVGElementTagNameMap[K] {
		const el = document.createElementNS(SVG_NS, tag);
		for (const [k, v] of Object.entries(attrs)) {
			el.setAttribute(k, String(v));
		}
		if (text !== undefined) {
			el.textContent = text;
		}
		parent.appendChild(el);
		return el;
	}

	private renderDrawing(): void {
		while (this.svg.firstChild) {
			this.svg.removeChild(this.svg.firstChild);
		}
		const model = this.model;
		const width = this.host.clientWidth;
		const height = this.host.clientHeight;
		if (!model || width <= 0 || height <= 0) {
			return;
		}
		this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
		this.svg.classList.toggle('placing', this.tool !== 'select');
		const xs = model.nodes.map(n => n.x);
		const ys = model.nodes.map(n => n.y);
		let minX = Math.min(0, ...xs), maxX = Math.max(3000, ...xs);
		let minY = Math.min(0, ...ys), maxY = Math.max(1500, ...ys);
		if (model.nodes.length >= 2) {
			minX = Math.min(...xs); maxX = Math.max(...xs); minY = Math.min(...ys); maxY = Math.max(...ys);
		}
		const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
		const scale = Math.max(1e-4, Math.min((width - 2 * MARGIN) / spanX, (height - 2 * MARGIN) / spanY));
		const x0 = (width - spanX * scale) / 2 - minX * scale;
		const y0 = (height + spanY * scale) / 2 + minY * scale;
		this.view = { scale, x0, y0, height };
		const px = (x: number) => x0 + x * scale;
		const py = (y: number) => y0 - y * scale;
		// Grid, every 100 mm when it is not too dense, else every 500 or 1000.
		const step = [100, 250, 500, 1000, 2500].find(s => s * scale >= 18) ?? 5000;
		const grid = this.svgEl(this.svg, 'g', { class: 'fem-stm-grid' });
		const left = -x0 / scale, right = (width - x0) / scale, top = y0 / scale, bottom = (y0 - height) / scale;
		for (let x = Math.ceil(left / step) * step; x <= right; x += step) {
			this.svgEl(grid, 'line', { x1: px(x), x2: px(x), y1: 0, y2: height, class: x === 0 ? 'axis' : '' });
		}
		for (let y = Math.ceil(bottom / step) * step; y <= top; y += step) {
			this.svgEl(grid, 'line', { x1: 0, x2: width, y1: py(y), y2: py(y), class: y === 0 ? 'axis' : '' });
		}
		const nodes = new Map(model.nodes.map(n => [n.id, n]));
		const results = new Map((this.result?.members ?? []).map(m => [m.id, m]));
		const nodeResults = new Map((this.result?.nodes ?? []).map(n => [n.id, n]));
		const memberLayer = this.svgEl(this.svg, 'g', {});
		for (const m of model.members) {
			const a = nodes.get(m.start), b = nodes.get(m.end);
			if (!a || !b) {
				continue;
			}
			const r = results.get(m.id);
			const state = !r ? '' : r.ok ? (r.utilisation > 0.9 ? 'warn' : 'pass') : 'fail';
			const selected = this.selection?.kind === 'member' && this.selection.id === m.id;
			const group = this.svgEl(memberLayer, 'g', { 'data-member': m.id, class: `fem-stm-member ${m.kind} ${state}${selected ? ' selected' : ''}` });
			if (m.kind === 'strut') {
				// A strut drawn with its width (a band) when it is wide enough to show.
				const bandWidth = Math.max(4, m.width * scale);
				this.svgEl(group, 'line', { x1: px(a.x), y1: py(a.y), x2: px(b.x), y2: py(b.y), class: 'band', 'stroke-width': bandWidth });
			}
			this.svgEl(group, 'line', { x1: px(a.x), y1: py(a.y), x2: px(b.x), y2: py(b.y), class: 'axis-line' });
			this.svgEl(group, 'line', { x1: px(a.x), y1: py(a.y), x2: px(b.x), y2: py(b.y), class: 'hit' });
			const label = r ? `${m.id} ${r.force > 0 ? '+' : ''}${r.force.toFixed(0)} kN` : m.id;
			this.svgEl(group, 'text', { x: (px(a.x) + px(b.x)) / 2 + 4, y: (py(a.y) + py(b.y)) / 2 - 4, class: 'label' }, label);
		}
		const loads = model.cases[this.caseIndex]?.loads ?? [];
		const nodeLayer = this.svgEl(this.svg, 'g', {});
		for (const n of model.nodes) {
			const selected = this.selection?.kind === 'node' && this.selection.id === n.id;
			const r = nodeResults.get(n.id);
			const state = !r ? '' : r.ok ? 'pass' : 'fail';
			const group = this.svgEl(nodeLayer, 'g', { 'data-node': n.id, class: `fem-stm-node ${state}${selected || this.pending === n.id ? ' selected' : ''}` });
			const x = px(n.x), y = py(n.y);
			if (n.support) {
				const s = 10;
				this.svgEl(group, 'path', { d: `M ${x} ${y} L ${x - s} ${y + 1.6 * s} L ${x + s} ${y + 1.6 * s} Z`, class: 'support' });
				if (n.support !== 'pin') {
					this.svgEl(group, 'line', { x1: x - s, x2: x + s, y1: y + 1.6 * s + 4, y2: y + 1.6 * s + 4, class: 'support' });
				}
			}
			this.svgEl(group, 'circle', { cx: x, cy: y, r: 5, class: 'dot' });
			this.svgEl(group, 'circle', { cx: x, cy: y, r: 12, class: 'hit' });
			this.svgEl(group, 'text', { x: x - 8, y: y - 8, class: 'label', 'text-anchor': 'end' }, r ? `${n.id} ${r.type}` : n.id);
			for (const load of loads.filter(l => l.node === n.id)) {
				const size = Math.hypot(load.fx, load.fy);
				if (size <= 0) {
					continue;
				}
				const ux = load.fx / size, uy = -load.fy / size;
				const length = 40;
				this.svgEl(group, 'line', { x1: x - ux * length, y1: y - uy * length, x2: x - ux * 8, y2: y - uy * 8, class: 'load' });
				this.svgEl(group, 'path', { d: `M ${x - ux * 8} ${y - uy * 8} l ${-ux * 8 - uy * 4} ${-uy * 8 + ux * 4} l ${uy * 8} ${-ux * 8} Z`, class: 'load-head' });
				this.svgEl(group, 'text', { x: x - ux * (length + 4), y: y - uy * (length + 4), class: 'label load-label', 'text-anchor': 'middle' }, `${size.toFixed(0)} kN`);
			}
		}
	}

	// ── properties ──

	private numberRow(container: HTMLElement, label: string, value: number, apply: (value: number) => void, unit?: string): void {
		const input = $<HTMLInputElement>('input.fem-stm-input', { type: 'number', value: String(value), step: 'any', 'aria-label': label });
		const cell = $('span.fem-stm-field');
		cell.appendChild(input);
		if (unit) {
			append(cell, $('span.fem-stm-unit', undefined, unit));
		}
		appendPropertyRow(container, label, cell);
		this.propertiesStore.add(addDisposableListener(input, EventType.CHANGE, () => {
			const parsed = Number(input.value);
			if (Number.isFinite(parsed)) {
				apply(parsed);
				this.changed();
			}
		}));
	}

	private textRow(container: HTMLElement, label: string, value: string, apply: (value: string) => void): void {
		const input = $<HTMLInputElement>('input.fem-stm-input', { type: 'text', value, 'aria-label': label });
		appendPropertyRow(container, label, input);
		this.propertiesStore.add(addDisposableListener(input, EventType.CHANGE, () => {
			apply(input.value.trim());
			this.changed();
		}));
	}

	private selectRow<T extends string>(container: HTMLElement, label: string, value: T, options: readonly { readonly value: T; readonly label: string }[], apply: (value: T) => void): void {
		const select = $<HTMLSelectElement>('select.fem-stm-input', { 'aria-label': label });
		for (const option of options) {
			const el = append(select, $<HTMLOptionElement>('option', { value: option.value }, option.label));
			el.selected = option.value === value;
		}
		appendPropertyRow(container, label, select);
		this.propertiesStore.add(addDisposableListener(select, EventType.CHANGE, () => {
			apply(select.value as T);
			this.changed();
		}));
	}

	private checkRows(container: HTMLElement, checks: readonly IFemDesignCheck[]): void {
		for (const check of checks) {
			const row = append(container, $(`details.fem-stm-check${check.ok ? '' : '.fail'}`));
			append(row, $('summary', undefined, `${check.name}: ${check.demand} / ${check.capacity} ${check.unit} (${formatUtilisation(check.utilisation)})${check.combination ? `, ${check.combination}` : ''}`));
			append(row, $('.fem-stm-check-note', undefined, check.note));
		}
	}

	private renderProperties(): void {
		const container = this.frame.properties;
		if (!container) {
			return;
		}
		this.propertiesStore.clear();
		clearNode(container);
		const model = this.model;
		if (!model) {
			appendPropertyNote(container, localize('femStm.propertiesEmpty', "Start from a template or draw a new model."));
			return;
		}
		const selection = this.selection;
		const node = selection?.kind === 'node' ? model.nodes.find(n => n.id === selection.id) : undefined;
		const member = selection?.kind === 'member' ? model.members.find(m => m.id === selection.id) : undefined;
		if (node) {
			this.renderNode(container, model, node);
		} else if (member) {
			this.renderMember(container, member);
		} else {
			this.renderModel(container, model);
		}
	}

	private renderNode(container: HTMLElement, model: IStmModel, node: IStmNode): void {
		appendPropertyHeading(container, localize('femStm.nodeHeading', "Node {0}", node.id));
		this.numberRow(container, 'x', node.x, v => node.x = v, 'mm');
		this.numberRow(container, 'y', node.y, v => node.y = v, 'mm');
		this.selectRow(container, localize('femStm.support', "Support"), node.support, SUPPORTS, v => node.support = v);
		this.numberRow(container, localize('femStm.bearing', "Bearing length"), node.bearing, v => node.bearing = Math.max(0, v), 'mm');
		this.selectRow(container, localize('femStm.anchorage', "Tie anchorage"), node.anchorage, ANCHORAGES, v => node.anchorage = v);
		if (node.anchorage === 'hook') {
			this.numberRow(container, localize('femStm.anchorLength', "Length past the nodal zone"), node.anchorLength, v => node.anchorLength = Math.max(0, v), 'mm');
		}
		const loadCase = model.cases[this.caseIndex];
		if (loadCase) {
			appendPropertyHeading(container, localize('femStm.nodeLoad', "Load in {0}", loadCase.name));
			const existing = loadCase.loads.find(l => l.node === node.id);
			const update = (fx: number | undefined, fy: number | undefined) => {
				let load = loadCase.loads.find(l => l.node === node.id);
				if (!load) {
					load = { node: node.id, fx: 0, fy: 0 };
					loadCase.loads.push(load);
				}
				load.fx = fx ?? load.fx;
				load.fy = fy ?? load.fy;
				loadCase.loads = loadCase.loads.filter(l => l.fx !== 0 || l.fy !== 0);
			};
			this.numberRow(container, 'Fx', existing?.fx ?? 0, v => update(v, undefined), 'kN');
			this.numberRow(container, localize('femStm.fyUp', "Fy (up)"), existing?.fy ?? 0, v => update(undefined, v), 'kN');
		}
		const reactions = this.result?.cases?.[this.caseIndex]?.reactions?.[node.id];
		if (reactions) {
			appendPropertyRow(container, localize('femStm.reaction', "Reaction"), `${reactions[0].toFixed(1)}, ${reactions[1].toFixed(1)} kN`);
		}
		const result = this.result?.nodes?.find(n => n.id === node.id);
		if (result) {
			appendPropertyHeading(container, localize('femStm.nodeChecks', "Nodal zone {0}, βn = {1}", result.type, result.betaN));
			this.checkRows(container, this.result!.checks.filter(c => c.name.startsWith(`Node ${node.id} `) || c.name.endsWith(` at ${node.id}`) || c.name.includes(` at ${node.id} `)));
		}
	}

	private renderMember(container: HTMLElement, member: IStmMember): void {
		appendPropertyHeading(container, member.kind === 'strut' ? localize('femStm.strutHeading', "Strut {0} ({1} to {2})", member.id, member.start, member.end) : localize('femStm.tieHeading', "Tie {0} ({1} to {2})", member.id, member.start, member.end));
		this.selectRow(container, localize('femStm.kind', "Kind"), member.kind, [{ value: 'strut', label: localize('femStm.kindStrut', "Strut") }, { value: 'tie', label: localize('femStm.kindTie', "Tie") }], v => member.kind = v);
		if (member.kind === 'strut') {
			this.numberRow(container, localize('femStm.strutWidth', "Width ws"), member.width, v => member.width = Math.max(0, v), 'mm');
			this.selectRow(container, localize('femStm.shape', "Shape"), member.shape, SHAPES, v => member.shape = v);
			this.numberRow(container, localize('femStm.steelArea', "Compression bars As'"), member.steelArea, v => member.steelArea = Math.max(0, v), 'mm²');
		} else {
			this.numberRow(container, localize('femStm.barArea', "Bars Ats"), member.barArea, v => member.barArea = Math.max(0, v), 'mm²');
			this.numberRow(container, localize('femStm.barDiameter', "Bar diameter"), member.barDiameter, v => member.barDiameter = Math.max(0, v), 'mm');
			this.numberRow(container, localize('femStm.tieWidth', "Effective width wt"), member.width, v => member.width = Math.max(0, v), 'mm');
			this.numberRow(container, localize('femStm.prestressArea', "Prestressing steel Atp"), member.prestressArea, v => member.prestressArea = Math.max(0, v), 'mm²');
			if (member.prestressArea > 0) {
				this.numberRow(container, 'fse', member.fse, v => member.fse = Math.max(0, v), 'MPa');
				this.numberRow(container, 'fpy', member.fpy, v => member.fpy = Math.max(0, v), 'MPa');
				this.selectRow(container, localize('femStm.bonded', "Tendons"), member.bonded ? 'bonded' : 'unbonded', [{ value: 'bonded', label: localize('femStm.bondedYes', "Bonded") }, { value: 'unbonded', label: localize('femStm.bondedNo', "Unbonded") }], v => member.bonded = v === 'bonded');
			}
		}
		const result = this.result?.members?.find(m => m.id === member.id);
		if (result) {
			appendPropertyRow(container, localize('femStm.force', "Governing force"), `${result.force.toFixed(1)} kN${result.case ? `, ${result.case}` : ''}`, !result.ok);
			if (result.required !== undefined) {
				appendPropertyRow(container, localize('femStm.required', "Ats needed"), `${result.required.toFixed(0)} mm²`, member.barArea + 1e-6 < result.required);
			}
			const own = new RegExp(`(^| )(strut|tie|Strut|Tie) ${member.id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}( |$|:)`);
			this.checkRows(container, this.result!.checks.filter(c => own.test(c.name)));
		}
	}

	private renderModel(container: HTMLElement, model: IStmModel): void {
		appendPropertyHeading(container, localize('femStm.modelHeading', "Region"));
		this.textRow(container, localize('femStm.name', "Name"), model.name, v => model.name = v || model.name);
		this.textRow(container, localize('femStm.member', "Analysis member"), model.member, v => model.member = v);
		this.numberRow(container, localize('femStm.thickness', "Thickness bs"), model.thickness, v => model.thickness = Math.max(1, v), 'mm');
		this.numberRow(container, localize('femStm.depth', "Member depth h"), model.depth, v => model.depth = Math.max(0, v), 'mm');
		this.numberRow(container, "f'c", model.fc, v => model.fc = Math.max(1, v), 'MPa');
		this.numberRow(container, 'fy', model.fy, v => model.fy = Math.max(1, v), 'MPa');
		this.numberRow(container, 'λ', model.lam, v => model.lam = Math.min(1, Math.max(0.5, v)));

		appendPropertyHeading(container, localize('femStm.casesHeading', "Load Cases"));
		if (model.cases.length) {
			this.selectRow(container, localize('femStm.caseShown', "Shown"), String(this.caseIndex), model.cases.map((c, k) => ({ value: String(k), label: c.name })), v => this.caseIndex = Number(v));
		}
		appendPropertyNote(container, localize('femStm.casesNote', "Select a node to put the factored forces of the case shown on it; add a case per combination with Add Load Case."));

		appendPropertyHeading(container, localize('femStm.webHeading', "Distributed Web Bars"));
		model.web.forEach((layer, k) => {
			this.numberRow(container, localize('femStm.webArea', "Layer {0}: bars", k + 1), layer.area, v => layer.area = Math.max(1, v), 'mm²');
			this.numberRow(container, localize('femStm.webSpacing', "Layer {0}: spacing", k + 1), layer.spacing, v => layer.spacing = Math.max(1, v), 'mm');
			this.numberRow(container, localize('femStm.webAngle', "Layer {0}: angle from x", k + 1), layer.angle, v => layer.angle = v, '°');
		});
		const webButtons = append(container, $('.fem-stm-buttons'));
		const add = append(webButtons, $<HTMLButtonElement>('button.fem-stm-link', { type: 'button' }, localize('femStm.addWeb', "Add a layer")));
		this.propertiesStore.add(addDisposableListener(add, EventType.CLICK, () => {
			model.web.push({ area: 157, spacing: 150, angle: model.web.length ? 0 : 90 });
			this.changed();
		}));
		if (model.web.length) {
			const remove = append(webButtons, $<HTMLButtonElement>('button.fem-stm-link', { type: 'button' }, localize('femStm.removeWeb', "Remove the last layer")));
			this.propertiesStore.add(addDisposableListener(remove, EventType.CLICK, () => {
				model.web.pop();
				this.changed();
			}));
		}

		const result = this.result;
		if (!result) {
			return;
		}
		appendPropertyHeading(container, localize('femStm.resultHeading', "Checks"), result.code);
		for (const problem of result.problems) {
			appendPropertyRow(container, localize('femStm.problem', "Problem"), problem, true);
		}
		for (const warning of result.warnings ?? []) {
			appendPropertyNote(container, warning);
		}
		this.checkRows(container, [...result.checks].sort((a, b) => b.utilisation - a.utilisation));
		if (result.assumptions?.length) {
			appendPropertyHeading(container, localize('femStm.assumptions', "Assumptions"));
			for (const assumption of result.assumptions) {
				appendPropertyNote(container, assumption);
			}
		}
		if (result.source) {
			appendPropertyNote(container, result.source);
		}
	}
}
