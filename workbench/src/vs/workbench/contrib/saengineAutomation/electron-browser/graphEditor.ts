/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/automation.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService, IQuickPickItem, IQuickPickSeparator } from '../../../../platform/quickinput/common/quickInput.js';
import { IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { addNode, connect, disconnect, formatParam, IGraphDocument, IGraphNode, INodeType, IPortRef, moveNode, parseParam, readGraph, readNodeTypes, removeNode, setParam, summariseOutput, writeGraph } from '../common/automationModel.js';
import { bag, callBackend, saveProjectParts } from './automationBackend.js';
import { GraphEditorInput } from './graphEditorInput.js';

/** Node layout [px]: width, header, one port row. */
const NODE_WIDTH = 210;
const HEADER = 26;
const ROW = 22;
const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * The node editor of a visual program: nodes (SAEngine functions from the backend's
 * `graph/nodeTypes`) wired output to input on a canvas, parameters in the properties panel, Run
 * executes the graph in the backend (`graph/run`) and shows each node's outputs on it.
 */
export class GraphEditor extends EditorPane {

	static readonly ID = 'workbench.editor.saengine.graph';

	private frame!: EditorFrame;
	private canvas!: HTMLElement;
	private wires!: SVGSVGElement;
	private nodesLayer!: HTMLElement;
	private graph: IGraphDocument | undefined;
	private types: INodeType[] = [];
	private selected: string | undefined;
	private pending: IPortRef | undefined;
	private outputs: Record<string, Record<string, unknown>> = {};
	private errors: Record<string, string> = {};
	private dirty = false;
	private running = false;
	private readonly renderDisposables = this._register(new DisposableStore());
	private readonly dragDisposables = this._register(new DisposableStore());

	private readonly addAction = this._register(new Action('saengine.graph.add', localize('graph.add', "Add Node"), ThemeIcon.asClassName(Codicon.add), true, () => this.pickNode()));
	private readonly deleteAction = this._register(new Action('saengine.graph.delete', localize('graph.delete', "Delete Node"), ThemeIcon.asClassName(Codicon.trash), false, async () => this.deleteSelected()));
	private readonly saveAction = this._register(new Action('saengine.graph.save', localize('graph.save', "Save"), ThemeIcon.asClassName(Codicon.save), true, () => this.save()));
	private readonly runAction = this._register(new Action('saengine.graph.run', localize('graph.run', "Run"), ThemeIcon.asClassName(Codicon.play), true, () => this.run()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IFileService private readonly fileService: IFileService,
		@IFemSolverService private readonly femSolverService: IFemSolverService,
		@INotificationService private readonly notificationService: INotificationService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super(GraphEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: GraphEditor.ID,
			ariaLabel: localize('graph.aria', "Visual program"),
			properties: { title: localize('graph.properties', "Node") },
		}));
		append(this.frame.titleSlot, $('span', undefined, localize('graph.title', "Visual Program")));
		this.frame.setHelp(localize('graph.help', "Nodes are SAEngine's functions: values, geometry, project edits, Run All's steps, results and exports. Wire an output (right) to an input (left): click the output, then the input; click a wired input to remove its wire. Inputs without a wire take the node's own value (Node panel). Run executes the program in the engine; nodes that write the project say so."));
		this.frame.setActions([this.addAction, this.runAction, this.saveAction, this.deleteAction, this.frame.togglePropertiesAction]);
		this.canvas = append(this.frame.main, $('.saengine-graph-canvas', { tabIndex: 0 }));
		this.wires = getWindow(parent).document.createElementNS(SVG_NS, 'svg');
		this.wires.classList.add('saengine-graph-wires');
		this.canvas.appendChild(this.wires);
		this.nodesLayer = append(this.canvas, $('.saengine-graph-nodes'));
		this._register(addDisposableListener(this.canvas, EventType.KEY_DOWN, e => {
			if ((e.key === 'Delete' || e.key === 'Backspace') && this.selected && e.target === this.canvas) {
				this.deleteSelected();
			} else if (e.key === 'Escape') {
				this.pending = undefined;
				this.render();
			}
		}));
		this._register(addDisposableListener(this.canvas, EventType.POINTER_DOWN, e => {
			if (e.target === this.canvas || e.target === this.wires || e.target === this.nodesLayer) {
				this.select(undefined);
			}
		}));
	}

	override async setInput(input: GraphEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.graph = undefined;
		this.outputs = {};
		this.errors = {};
		this.selected = undefined;
		this.dirty = false;
		if (!this.types.length) {
			this.types = readNodeTypes(await callBackend(this.instantiationService, this.femSolverService, 'graph/nodeTypes', {}).catch(() => undefined));
		}
		try {
			const text = (await this.fileService.readFile(input.resource)).value.toString();
			const { graph, problems } = readGraph(text);
			this.graph = graph;
			if (!graph) {
				this.frame.setEmpty({ title: localize('graph.unreadable', "The visual program cannot be read"), text: problems.join('; ') });
			}
		} catch (error) {
			this.frame.setEmpty({ title: localize('graph.unreadable', "The visual program cannot be read"), text: error instanceof Error ? error.message : String(error) });
		}
		if (token.isCancellationRequested) {
			return;
		}
		if (this.graph) {
			this.frame.setEmpty(undefined);
		}
		this.render();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.canvas.focus();
	}

	private type(node: IGraphNode): INodeType | undefined {
		return this.types.find(t => t.id === node.type);
	}

	private update(graph: IGraphDocument): void {
		this.graph = graph;
		this.dirty = true;
		this.render();
	}

	private select(id: string | undefined): void {
		this.selected = id;
		this.render();
	}

	private portPoint(node: IGraphNode, index: number, side: 'in' | 'out'): { x: number; y: number } {
		return { x: node.x + (side === 'out' ? NODE_WIDTH : 0), y: node.y + HEADER + ROW * index + ROW / 2 };
	}

	private render(): void {
		this.renderDisposables.clear();
		clearNode(this.nodesLayer);
		while (this.wires.firstChild) {
			this.wires.removeChild(this.wires.firstChild);
		}
		const graph = this.graph;
		this.deleteAction.enabled = !!this.selected;
		this.runAction.enabled = !!graph && !this.running;
		this.saveAction.enabled = !!graph && this.dirty;
		this.renderProperties();
		if (!graph) {
			return;
		}
		let right = 0, bottom = 0;
		for (const node of graph.nodes) {
			const type = this.type(node);
			const rows = Math.max(type?.inputs.length ?? 0, type?.outputs.length ?? 0, 1);
			const element = append(this.nodesLayer, $('.saengine-graph-node'));
			element.classList.toggle('selected', node.id === this.selected);
			element.classList.toggle('failed', !!this.errors[node.id]);
			element.style.left = `${node.x}px`;
			element.style.top = `${node.y}px`;
			element.style.width = `${NODE_WIDTH}px`;
			const header = append(element, $('.header', { title: type?.description ?? node.type }, type?.title ?? localize('graph.unknownType', "Unknown: {0}", node.type)));
			if (type?.writes) {
				append(header, $(`span.writes${ThemeIcon.asCSSSelector(Codicon.edit)}`, { title: localize('graph.writes', "Writes the project's files") }));
			}
			const body = append(element, $('.ports'));
			for (let k = 0; k < rows; k++) {
				const row = append(body, $('.row'));
				const input = type?.inputs[k];
				const output = type?.outputs[k];
				const left = append(row, $('.in'));
				if (input) {
					const wired = graph.edges.some(e => e.to.node === node.id && e.to.port === input.name);
					const dot = append(left, $('span.dot', { title: input.description ?? input.type, role: 'button', 'aria-label': localize('graph.inputPort', "Input {0}", input.name) }));
					dot.classList.toggle('wired', wired);
					append(left, $('span.name', undefined, input.name));
					this.renderDisposables.add(addDisposableListener(dot, EventType.CLICK, e => {
						e.stopPropagation();
						this.clickInput({ node: node.id, port: input.name }, wired);
					}));
				}
				const rightCell = append(row, $('.out'));
				if (output) {
					append(rightCell, $('span.name', undefined, output.name));
					const dot = append(rightCell, $('span.dot', { title: output.type, role: 'button', 'aria-label': localize('graph.outputPort', "Output {0}", output.name) }));
					dot.classList.toggle('pending', this.pending?.node === node.id && this.pending.port === output.name);
					this.renderDisposables.add(addDisposableListener(dot, EventType.CLICK, e => {
						e.stopPropagation();
						this.pending = { node: node.id, port: output.name };
						this.render();
					}));
				}
			}
			const result = this.errors[node.id] ?? (this.outputs[node.id] ? Object.values(this.outputs[node.id]).map(v => summariseOutput(v)).join(' · ') : undefined);
			if (result !== undefined) {
				append(element, $('.result', { title: result }, result));
			}
			this.renderDisposables.add(addDisposableListener(element, EventType.POINTER_DOWN, e => {
				const target = e.target as HTMLElement;
				if (target.classList.contains('dot') || target.tagName === 'INPUT') {
					return; // a port's click (rendering now would remove the element it lands on)
				}
				if (target !== header) {
					if (this.selected !== node.id) {
						this.select(node.id);
					}
					return;
				}
				this.drag(node, e);
			}));
			right = Math.max(right, node.x + NODE_WIDTH + 40);
			bottom = Math.max(bottom, node.y + HEADER + rows * ROW + 60);
		}
		this.nodesLayer.style.width = this.wires.style.width = `${right}px`;
		this.nodesLayer.style.height = this.wires.style.height = `${bottom}px`;
		const doc = getWindow(this.canvas).document;
		for (const edge of graph.edges) {
			const from = graph.nodes.find(n => n.id === edge.from.node);
			const to = graph.nodes.find(n => n.id === edge.to.node);
			const fromType = from && this.type(from), toType = to && this.type(to);
			const out = fromType?.outputs.findIndex(p => p.name === edge.from.port) ?? -1;
			const inn = toType?.inputs.findIndex(p => p.name === edge.to.port) ?? -1;
			if (!from || !to || out < 0 || inn < 0) {
				continue;
			}
			const a = this.portPoint(from, out, 'out'), b = this.portPoint(to, inn, 'in');
			const bend = Math.max(40, Math.abs(b.x - a.x) / 2);
			const path = doc.createElementNS(SVG_NS, 'path');
			path.setAttribute('d', `M ${a.x} ${a.y} C ${a.x + bend} ${a.y}, ${b.x - bend} ${b.y}, ${b.x} ${b.y}`);
			path.classList.add('wire');
			this.wires.appendChild(path);
		}
		this.frame.setStatus({
			text: this.running
				? localize('graph.running', "Running in the engine...")
				: this.pending
					? localize('graph.pendingWire', "Click an input to wire {0}.{1} to it (Esc: cancel).", this.pending.node, this.pending.port)
					: Object.keys(this.errors).length
						? localize('graph.errors', "{0} node(s) failed: see the red nodes.", Object.keys(this.errors).length)
						: this.dirty ? localize('graph.unsaved', "Unsaved changes.") : localize('graph.saved', "{0} nodes, {1} wires.", graph.nodes.length, graph.edges.length),
			busy: this.running,
			severity: Object.keys(this.errors).length ? 'warning' : 'info',
		});
	}

	private clickInput(to: IPortRef, wired: boolean): void {
		if (!this.graph) {
			return;
		}
		if (this.pending) {
			const next = connect(this.graph, this.pending, to);
			this.pending = undefined;
			if (!next) {
				this.notificationService.info(localize('graph.loop', "That wire would make a loop (or join a node to itself)."));
				this.render();
				return;
			}
			this.update(next);
		} else if (wired) {
			this.update(disconnect(this.graph, to));
		}
	}

	private drag(node: IGraphNode, start: PointerEvent): void {
		start.preventDefault();
		this.selected = node.id;
		const window = getWindow(this.canvas);
		const x0 = node.x, y0 = node.y;
		// Not in renderDisposables: every move renders again, which clears those.
		this.dragDisposables.clear();
		this.dragDisposables.add(addDisposableListener(window, EventType.POINTER_MOVE, (e: PointerEvent) => {
			if (this.graph) {
				this.graph = moveNode(this.graph, node.id, x0 + e.clientX - start.clientX, y0 + e.clientY - start.clientY);
				this.dirty = true;
				this.render();
			}
		}));
		this.dragDisposables.add(addDisposableListener(window, EventType.POINTER_UP, () => this.dragDisposables.clear()));
		this.render();
	}

	private renderProperties(): void {
		const panel = this.frame.properties;
		if (!panel) {
			return;
		}
		clearNode(panel);
		const node = this.graph?.nodes.find(n => n.id === this.selected);
		if (!node) {
			appendPropertyNote(panel, localize('graph.noSelection', "Select a node to see and change its values."));
			return;
		}
		const type = this.type(node);
		appendPropertyHeading(panel, type?.title ?? node.type, node.id);
		if (type?.description) {
			appendPropertyNote(panel, type.description);
		}
		for (const input of type?.inputs ?? []) {
			if (this.graph!.edges.some(e => e.to.node === node.id && e.to.port === input.name)) {
				appendPropertyRow(panel, input.name, localize('graph.wired', "from its wire"));
				continue;
			}
			const field = $('input.saengine-graph-param', { type: 'text', placeholder: formatParam(input.default), 'aria-label': input.name, title: input.description ?? '' }) as HTMLInputElement;
			field.value = formatParam(node.params[input.name]);
			this.renderDisposables.add(addDisposableListener(field, EventType.CHANGE, () => {
				if (this.graph) {
					this.graph = setParam(this.graph, node.id, input.name, parseParam(field.value, input.type));
					this.dirty = true;
					this.render();
				}
			}));
			appendPropertyRow(panel, input.name, field);
		}
		if (this.errors[node.id]) {
			appendPropertyRow(panel, localize('graph.error', "Error"), this.errors[node.id], true);
		}
		for (const [name, value] of Object.entries(this.outputs[node.id] ?? {})) {
			appendPropertyRow(panel, name, summariseOutput(value, 400));
		}
	}

	private async pickNode(): Promise<void> {
		if (!this.graph) {
			return;
		}
		type Item = IQuickPickItem & { nodeType: INodeType };
		const items: (Item | IQuickPickSeparator)[] = [];
		let category = '';
		for (const type of this.types) {
			if (type.category !== category) {
				category = type.category;
				items.push({ type: 'separator', label: category });
			}
			items.push({ label: type.title, description: type.writes ? localize('graph.writesShort', "writes the project") : undefined, detail: type.description, nodeType: type });
		}
		const picked = await this.quickInputService.pick(items, { placeHolder: localize('graph.pickNode', "Node to add") }) as Item | undefined;
		if (!picked) {
			return;
		}
		const last = this.graph.nodes[this.graph.nodes.length - 1];
		const { graph, id } = addNode(this.graph, picked.nodeType, last ? last.x + NODE_WIDTH + 60 : 40, last ? last.y : 40);
		this.selected = id;
		this.update(graph);
	}

	private deleteSelected(): void {
		if (this.graph && this.selected) {
			const id = this.selected;
			this.selected = undefined;
			delete this.outputs[id];
			delete this.errors[id];
			this.update(removeNode(this.graph, id));
		}
	}

	private async save(): Promise<void> {
		const input = this.input;
		if (!(input instanceof GraphEditorInput) || !this.graph) {
			return;
		}
		await this.fileService.writeFile(input.resource, VSBuffer.fromString(writeGraph(this.graph)));
		this.dirty = false;
		this.render();
	}

	private async run(): Promise<void> {
		if (!this.graph || this.running) {
			return;
		}
		await this.save();
		const project = this.projectService.project;
		if (project && this.graph.nodes.some(n => this.type(n)?.writes)) {
			// The engine reads and writes the files on disk: the open editors' edits first.
			await saveProjectParts(this.textFileService, project);
		}
		this.running = true;
		this.render();
		try {
			const answer = bag(await callBackend(this.instantiationService, this.femSolverService, 'graph/run', { graph: this.graph, ...(project ? { projectRoot: project.root.fsPath } : {}) }));
			if (answer.ok === false && Array.isArray(answer.problems)) {
				this.notificationService.error(localize('graph.cannotRun', "The program cannot run: {0}", answer.problems.join('; ')));
				this.outputs = {};
				this.errors = {};
			} else {
				this.outputs = bag(answer.outputs) as Record<string, Record<string, unknown>>;
				this.errors = bag(answer.errors) as Record<string, string>;
			}
		} catch (error) {
			this.notificationService.error(error instanceof Error ? error.message : String(error));
		} finally {
			this.running = false;
			this.render();
		}
	}
}
