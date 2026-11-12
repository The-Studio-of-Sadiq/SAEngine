/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../../base/common/buffer.js';
import { Event } from '../../../../../base/common/event.js';
import { DisposableStore, IReference } from '../../../../../base/common/lifecycle.js';
import { ResourceMap, ResourceSet } from '../../../../../base/common/map.js';
import { Schemas } from '../../../../../base/common/network.js';
import { joinPath } from '../../../../../base/common/resources.js';
import { URI } from '../../../../../base/common/uri.js';
import { mock } from '../../../../../base/test/common/mock.js';
import { ITextModel } from '../../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../../editor/common/services/resolverService.js';
import { createModelServices, instantiateTextModel } from '../../../../../editor/test/common/testTextModel.js';
import { CommandsRegistry, ICommandService } from '../../../../../platform/commands/common/commands.js';
import { FileService } from '../../../../../platform/files/common/fileService.js';
import { InMemoryFileSystemProvider } from '../../../../../platform/files/common/inMemoryFilesystemProvider.js';
import { NullLogService } from '../../../../../platform/log/common/log.js';
import { IProgress, IProgressService, IProgressStep } from '../../../../../platform/progress/common/progress.js';
import { IUndoRedoService } from '../../../../../platform/undoRedo/common/undoRedo.js';
import { testWorkspace } from '../../../../../platform/workspace/test/common/testWorkspace.js';
import { TestContextService } from '../../../../test/common/workbenchTestServices.js';
import { IResolvedTextFileEditorModel, ITextFileEditorModel, ITextFileEditorModelManager, ITextFileService } from '../../../textfile/common/textfiles.js';
import { SaengineActionsService } from '../../browser/saengineActionsService.js';
import { ACTIONS_LIST_COMMAND, ACTIONS_RUN_COMMAND, IActionsRunRequest, IActionStep } from '../../common/saengineActions.js';
import { ISaengineProject, ISaengineProjectService } from '../../common/saengineProject.js';

/*
 * A window for the actions service without Electron: an in-memory project folder, text models with
 * one undo service, a text file service that tracks unsaved models, and a fake engine that answers
 * `actions/list` and `actions/run` as `saengine.actions` does (the same shapes: snake_case keys,
 * all or nothing, changes as formatted JSON texts, guardrail problems with field, value, reason).
 */

export const SETTINGS_FILE = '02 Project Settings/project-settings.json';
export const FLOOR_PLAN_FILE = '05 Floor Plan/floor-plan.json';
export const DESIGN_SUMMARY = '08 FEM/model.results/design-summary.json';

type Json = { [key: string]: unknown };

interface IFakeAction {
	readonly name: string;
	readonly kind: 'edit' | 'run' | 'query';
	readonly summary: string;
	readonly parts: readonly string[];
	readonly params: Json;
}

const LENGTH = { type: 'array', items: { type: 'number' }, description: 'mm' };

export const FAKE_CATALOGUE: readonly IFakeAction[] = [
	{ name: 'project.create', kind: 'edit', summary: 'Create a project in an empty folder.', parts: ['settings', 'floorPlan'], params: { name: { type: 'string' } } },
	{ name: 'project.summary', kind: 'query', summary: 'The project in numbers.', parts: [], params: {} },
	{ name: 'settings.site', kind: 'edit', summary: 'Site: location, seismic zone, site class.', parts: ['settings'], params: { location: { type: 'string' }, siteClass: { type: 'string' } } },
	{ name: 'grid.set', kind: 'edit', summary: 'Set the x and y grid lines by their spacings.', parts: ['floorPlan'], params: { x: LENGTH, y: LENGTH } },
	{ name: 'storeys.set', kind: 'edit', summary: 'Set the storeys by their heights.', parts: ['floorPlan'], params: { heights: LENGTH } },
	{ name: 'columns.place', kind: 'edit', summary: 'Place columns at grid points.', parts: ['floorPlan'], params: { at: { type: 'string' }, type: { type: 'string' } } },
	{ name: 'beams.place', kind: 'edit', summary: 'Place beams along grid lines.', parts: ['floorPlan'], params: { along: { type: 'string' } } },
	{ name: 'slabs.place', kind: 'edit', summary: 'Place slabs in grid panels.', parts: ['floorPlan'], params: { panels: { type: 'string' } } },
	{ name: 'load.area.set', kind: 'edit', summary: 'Area loads per storey: SD, L, Lr [kPa].', parts: ['floorPlan'], params: { SD: { type: 'number' }, L: { type: 'number' } } },
	{ name: 'foundations.generate', kind: 'edit', summary: 'Footings under the columns, sized.', parts: ['floorPlan'], params: {} },
	{ name: 'run.all', kind: 'run', summary: 'Run All: analysis, design, report.', parts: [], params: {} },
	{ name: 'results.summary', kind: 'query', summary: 'The last run: checked, passed, failed.', parts: [], params: {} },
];

export class FakeEngine {
	/** Every request, in order. */
	readonly requests: { command: string; args: IActionsRunRequest | Json }[] = [];
	/** Called when project.create wrote the project. */
	onCreated: (() => void) | undefined;

	constructor(private readonly fileService: FileService) { }

	async handle(command: string, args: IActionsRunRequest | Json): Promise<unknown> {
		this.requests.push({ command, args: JSON.parse(JSON.stringify(args)) });
		if (command === ACTIONS_LIST_COMMAND) {
			return FAKE_CATALOGUE.map(a => ({ name: a.name, summary: a.summary, kind: a.kind, parts: a.parts, params_schema: { type: 'object', properties: a.params, required: Object.keys(a.params).slice(0, 1) } }));
		}
		const request = args as IActionsRunRequest;
		return this.run(URI.file(request.projectRoot).with({ scheme: Schemas.inMemory }), request.steps, request.overrides ?? {}, request.write === true);
	}

	private async run(root: URI, steps: readonly IActionStep[], overrides: { readonly [path: string]: string }, write: boolean): Promise<unknown> {
		const parts = new Map<string, Json>();
		const read = async (path: string): Promise<Json> => {
			let data = parts.get(path);
			if (!data) {
				// The app's unsaved text first, as ProjectView does; run steps read the disk only (the app saved).
				const text = overrides[path] ?? (await this.fileService.readFile(joinPath(root, ...path.split('/')))).value.toString();
				data = JSON.parse(text) as Json;
				parts.set(path, data);
			}
			return data;
		};
		const changed = new Set<string>();
		const put = (path: string, data: Json) => { parts.set(path, data); changed.add(path); };
		const results: Json[] = [];
		for (let index = 0; index < steps.length; index++) {
			const step = steps[index];
			const result = await this.step(step, read, put, root, write);
			results.push(result);
			if (result.ok !== true) {
				return { ok: false, results, changes: {}, failed_step: index };
			}
		}
		const changes: { [path: string]: string } = {};
		for (const path of changed) {
			changes[path] = JSON.stringify(parts.get(path), undefined, '\t') + '\n';
			if (write) {
				await this.fileService.writeFile(joinPath(root, ...path.split('/')), VSBuffer.fromString(changes[path]));
			}
		}
		if (write && steps.some(s => s.action === 'project.create')) {
			await this.fileService.writeFile(joinPath(root, 'Plot.saengine'), VSBuffer.fromString('{"schema": 1, "name": "Plot"}\n'));
			this.onCreated?.();
		}
		return { ok: true, results, changes, failed_step: null };
	}

	private async step(step: IActionStep, read: (path: string) => Promise<Json>, put: (path: string, data: Json) => void, root: URI, write: boolean): Promise<Json> {
		const p = (step.params ?? {}) as Json;
		const ok = (message: string, created: string[] = [], data?: unknown) => ({ ok: true, message, created, warnings: [], problems: [], data: data ?? null });
		const refuse = (message: string, field: string, value: unknown, reason: string) => ({ ok: false, message, created: [], warnings: [], problems: [{ field, value, reason }], data: null });
		switch (step.action) {
			case 'project.create': {
				if (!write) {
					return refuse('project.create writes the project', 'write', false, 'run it with write');
				}
				put(SETTINGS_FILE, { schema: 1, project: { name: p.name ?? 'Plot' }, site: {} });
				put(FLOOR_PLAN_FILE, { schema: 1, grids: { x: [], y: [] }, stories: [], columns: [], beams: [], slabs: [], footings: [], loads: {} });
				return ok(`Created the project "${p.name ?? 'Plot'}".`);
			}
			case 'settings.site': {
				const settings = await read(SETTINGS_FILE);
				put(SETTINGS_FILE, { ...settings, site: { location: p.location, siteClass: p.siteClass } });
				return ok(`Site: ${p.location}, site class ${p.siteClass}.`);
			}
			case 'grid.set': {
				const plan = await read(FLOOR_PLAN_FILE);
				const lines = (spacings: number[], label: (i: number) => string) => {
					let position = 0;
					return [0, ...spacings].map((s, i) => ({ label: label(i), position: position += s }));
				};
				const x = p.x as number[];
				const y = p.y as number[];
				for (const [axis, list] of [['x', x], ['y', y]] as const) {
					const bad = list.findIndex(s => s < 1000 || s > 15000);
					if (bad >= 0) {
						return refuse('The grid was not set.', `${axis}[${bad}]`, list[bad], 'a grid spacing is between 1000 and 15000 mm');
					}
				}
				put(FLOOR_PLAN_FILE, { ...plan, grids: { x: lines(x, i => String.fromCharCode(65 + i)), y: lines(y, i => String(i + 1)) } });
				return ok(`Grid: ${x.length + 1} x lines, ${y.length + 1} y lines.`);
			}
			case 'storeys.set': {
				const plan = await read(FLOOR_PLAN_FILE);
				const heights = p.heights as number[];
				const bad = heights.findIndex(h => h < 2000 || h > 6000);
				if (bad >= 0) {
					return refuse('The storeys were not set.', `heights[${bad}]`, heights[bad], 'a storey height is between 2000 and 6000 mm');
				}
				let elevation = 0;
				put(FLOOR_PLAN_FILE, { ...plan, stories: heights.map((height, i) => ({ id: `L${i + 1}`, elevation: elevation += height, height })) });
				return ok(`${heights.length} storeys.`, heights.map((_, i) => `L${i + 1}`));
			}
			case 'columns.place': {
				const plan = await read(FLOOR_PLAN_FILE);
				const grids = plan.grids as { x: { label: string }[]; y: { label: string }[] };
				const ids: string[] = [];
				const columns = grids.x.flatMap(x => grids.y.map(y => {
					ids.push(`C${ids.length + 1}`);
					return { id: ids[ids.length - 1], at: `${x.label}${y.label}`, type: p.type ?? 'C400' };
				}));
				put(FLOOR_PLAN_FILE, { ...plan, columns });
				return ok(`Placed ${ids.length} columns.`, ids);
			}
			case 'beams.place': {
				const plan = await read(FLOOR_PLAN_FILE);
				const grids = plan.grids as { x: unknown[]; y: unknown[] };
				const count = (grids.x.length - 1) * grids.y.length + (grids.y.length - 1) * grids.x.length;
				const ids = Array.from({ length: count }, (_, i) => `B${i + 1}`);
				put(FLOOR_PLAN_FILE, { ...plan, beams: ids.map(id => ({ id, type: 'B300x500' })) });
				return ok(`Placed ${count} beams.`, ids);
			}
			case 'slabs.place': {
				const plan = await read(FLOOR_PLAN_FILE);
				const grids = plan.grids as { x: unknown[]; y: unknown[] };
				const ids = Array.from({ length: (grids.x.length - 1) * (grids.y.length - 1) }, (_, i) => `S${i + 1}`);
				put(FLOOR_PLAN_FILE, { ...plan, slabs: ids.map(id => ({ id, thickness: 150 })) });
				return ok(`Placed ${ids.length} slabs.`, ids);
			}
			case 'load.area.set': {
				const plan = await read(FLOOR_PLAN_FILE);
				put(FLOOR_PLAN_FILE, { ...plan, loads: { SD: p.SD, L: p.L } });
				return ok(`Area loads: SD ${p.SD} kPa, L ${p.L} kPa on every storey.`);
			}
			case 'foundations.generate': {
				const plan = await read(FLOOR_PLAN_FILE);
				const columns = plan.columns as { id: string }[];
				put(FLOOR_PLAN_FILE, { ...plan, footings: columns.map((c, i) => ({ id: `F${i + 1}`, under: c.id, size: [1800, 1800] })) });
				return ok(`${columns.length} isolated footings.`, columns.map((_, i) => `F${i + 1}`));
			}
			case 'project.summary': {
				const plan = await read(FLOOR_PLAN_FILE);
				return ok('The project.', [], { storeys: (plan.stories as unknown[]).length, columns: (plan.columns as unknown[]).length });
			}
			case 'run.all': {
				if (!write) {
					return refuse('Run All needs the files on disk.', 'write', false, 'the app saves and runs with write');
				}
				const plan = JSON.parse((await this.fileService.readFile(joinPath(root, ...FLOOR_PLAN_FILE.split('/')))).value.toString()) as Json;
				const checked = (plan.columns as unknown[]).length + (plan.beams as unknown[]).length;
				put(DESIGN_SUMMARY, { checked, passed: checked - 1, failed: 1, governing: 'B3' });
				return ok(`Run All done: ${checked} members checked, 1 fails (B3).`);
			}
			case 'results.summary': {
				const summary = await read(DESIGN_SUMMARY);
				return ok('The last run.', [], summary);
			}
		}
		return refuse(`Unknown action ${step.action}.`, 'action', step.action, 'not in the catalogue');
	}
}

/** The text models of the window, one undo service for them all. */
export class FakeTextModels extends mock<ITextModelService>() {
	readonly models = new ResourceMap<ITextModel>();
	readonly undoRedo: IUndoRedoService;
	/** Called for each model as it is created (the text files track its unsaved state). */
	onCreate: ((resource: URI, model: ITextModel) => void) | undefined;
	private readonly instantiation;

	constructor(private readonly store: DisposableStore, private readonly fileService: FileService) {
		super();
		this.instantiation = createModelServices(store);
		this.undoRedo = this.instantiation.get(IUndoRedoService);
	}

	override async createModelReference(resource: URI): Promise<IReference<IResolvedTextEditorModel>> {
		let model = this.models.get(resource);
		if (!model) {
			const text = (await this.fileService.readFile(resource)).value.toString();
			model = this.store.add(instantiateTextModel(this.instantiation, text, null, undefined, resource));
			this.models.set(resource, model);
			this.onCreate?.(resource, model);
		}
		const textEditorModel = model;
		const object = new class extends mock<IResolvedTextEditorModel>() {
			override readonly textEditorModel = textEditorModel;
		};
		return { object, dispose: () => { } };
	}
}

/** Unsaved models are the ones changed since they were read or saved. */
export class FakeTextFiles extends mock<ITextFileService>() {
	readonly dirty = new ResourceSet();
	readonly saved: string[] = [];
	readonly reloaded: string[] = [];
	private readonly listening = new ResourceSet();
	private reloading = false;

	constructor(private readonly store: DisposableStore, private readonly textModels: FakeTextModels, private readonly fileService: FileService) {
		super();
		textModels.onCreate = (resource, model) => this.watch(resource, model);
	}

	/** Opens `resource` as the engineer would, optionally typing `text` (unsaved). */
	async open(resource: URI, text?: string): Promise<ITextModel> {
		const model = (await this.textModels.createModelReference(resource)).object.textEditorModel;
		if (text !== undefined) {
			model.setValue(text);
		}
		return model;
	}

	private watch(resource: URI, model: ITextModel): void {
		if (!this.listening.has(resource)) {
			this.listening.add(resource);
			this.store.add(model.onDidChangeContent(() => {
				if (!this.reloading) {
					this.dirty.add(resource);
				}
			}));
		}
	}

	private fileModel(resource: URI, model: ITextModel): ITextFileEditorModel {
		this.watch(resource, model);
		const files = this;
		return new class extends mock<ITextFileEditorModel>() {
			override readonly resource = resource;
			override get textEditorModel() { return model; }
			override isDirty(): this is IResolvedTextFileEditorModel { return files.dirty.has(resource); }
			override async resolve(): Promise<void> {
				files.reloaded.push(resource.path);
				files.reloading = true;
				try {
					model.setValue((await files.fileService.readFile(resource)).value.toString());
				} finally {
					files.reloading = false;
				}
			}
		};
	}

	override get files(): ITextFileEditorModelManager {
		const files = this;
		return new class extends mock<ITextFileEditorModelManager>() {
			override get models() {
				return [...files.textModels.models].map(([resource, model]) => files.fileModel(resource, model));
			}
			override get(resource: URI) {
				const model = files.textModels.models.get(resource);
				return model ? files.fileModel(resource, model) : undefined;
			}
		};
	}

	override isDirty(resource: URI): boolean {
		return this.dirty.has(resource);
	}

	override async save(resource: URI): Promise<URI | undefined> {
		const model = this.textModels.models.get(resource);
		if (model) {
			await this.fileService.writeFile(resource, VSBuffer.fromString(model.getValue()));
			this.dirty.delete(resource);
			this.saved.push(resource.path);
		}
		return resource;
	}
}

export class FakeProjectService extends mock<ISaengineProjectService>() {
	private current: ISaengineProject | undefined;
	override readonly onDidChangeProject = Event.None;
	override readonly parts = [];

	constructor(private readonly root: URI, open: boolean) {
		super();
		if (open) {
			this.markOpen();
		}
	}

	override get project(): ISaengineProject | undefined {
		return this.current;
	}

	markOpen(): void {
		this.current = { root: this.root, manifest: joinPath(this.root, 'Plot.saengine'), name: 'Plot', type: 'building' };
	}
}

export interface IActionsWindow {
	readonly root: URI;
	readonly fileService: FileService;
	readonly engine: FakeEngine;
	readonly textModels: FakeTextModels;
	readonly textFiles: FakeTextFiles;
	readonly projectService: FakeProjectService;
	readonly commandService: ICommandService;
	readonly service: SaengineActionsService;
}

/** A window with the project at `/projects/Plot` (open, or an empty folder for project.create). */
export async function actionsWindow(disposables: Pick<DisposableStore, 'add'>, options: { readonly project: boolean }): Promise<IActionsWindow> {
	const store = disposables.add(new DisposableStore());
	const root = URI.from({ scheme: Schemas.inMemory, path: '/projects/Plot' });
	const fileService = store.add(new FileService(new NullLogService()));
	store.add(fileService.registerProvider(Schemas.inMemory, store.add(new InMemoryFileSystemProvider())));
	await fileService.createFolder(root);
	const engine = new FakeEngine(fileService);
	const textModels = new FakeTextModels(store, fileService);
	const textFiles = new FakeTextFiles(store, textModels, fileService);
	const projectService = new FakeProjectService(root, options.project);
	engine.onCreated = () => projectService.markOpen();
	store.add(CommandsRegistry.registerCommand(ACTIONS_LIST_COMMAND, () => undefined));
	store.add(CommandsRegistry.registerCommand(ACTIONS_RUN_COMMAND, () => undefined));
	const commandService = new class extends mock<ICommandService>() {
		override executeCommand<R>(id: string, ...args: unknown[]): Promise<R | undefined> {
			return engine.handle(id, (args[0] ?? {}) as Json) as Promise<R>;
		}
	};
	const progressService = new class extends mock<IProgressService>() {
		override withProgress<R>(_options: unknown, task: (progress: IProgress<IProgressStep>) => Promise<R>): Promise<R> {
			return task({ report: () => { } });
		}
	};
	const service = store.add(new SaengineActionsService(projectService, commandService, textModels, textFiles, fileService, new TestContextService(testWorkspace(root)), progressService));
	return { root, fileService, engine, textModels, textFiles, projectService, commandService, service };
}

export async function readText(window: IActionsWindow, path: string): Promise<string> {
	return (await window.fileService.readFile(joinPath(window.root, ...path.split('/')))).value.toString();
}

export async function writeText(window: IActionsWindow, path: string, value: unknown): Promise<void> {
	await window.fileService.writeFile(joinPath(window.root, ...path.split('/')), VSBuffer.fromString(JSON.stringify(value, undefined, '\t') + '\n'));
}
