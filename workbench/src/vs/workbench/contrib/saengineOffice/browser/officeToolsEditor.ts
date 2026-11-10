/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/officeTools.css';
import '../../saengineLibrary/browser/media/modelEditors.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { designArguments } from '../../saengineFem/browser/femDesign.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { PDF_TO_DXF_COMMAND } from '../../saengineProject/browser/projectArchiveModel.js';
import {
	ENVIRONMENT_FILE, FABRICATION_FILE, ganttLayout, ICostOptimisation, ISchedule, IScheduleAnswer, ITakeoff, ITakeoffItem, ITakeoffSheet, measureItem, nextId,
	emptyTakeoff, OFFICE_REQUEST_COMMAND, OFFICE_TOOLS, OfficeTool, PHASING_FILE, Point2, SCHEDULE_FILE, sheetScale, TAKEOFF_FILE,
} from './officeModel.js';
import { OfficeToolsInput } from './officeToolsInput.js';

type Answer = { readonly problems?: readonly string[]; readonly [key: string]: unknown };
/** What every backend answer has: its problems (the typed answers below declare the rest). */
type Problems = { readonly problems?: readonly string[] };
type TakeoffMode = 'pan' | 'calibrate' | 'length' | 'area' | 'count';

const SVG = 'http://www.w3.org/2000/svg';

function svg<K extends keyof SVGElementTagNameMap>(parent: Element, tag: K, attributes: { readonly [name: string]: string | number } = {}): SVGElementTagNameMap[K] {
	const element = document.createElementNS(SVG, tag);
	for (const [name, value] of Object.entries(attributes)) {
		element.setAttribute(name, String(value));
	}
	parent.appendChild(element);
	return element;
}

function toolLabel(tool: OfficeTool): string {
	switch (tool) {
		case 'schedule': return localize('office.tab.schedule', "4D Programme");
		case 'cost': return localize('office.tab.cost', "Cost Optimisation");
		case 'takeoff': return localize('office.tab.takeoff', "PDF Takeoff");
		case 'site': return localize('office.tab.site', "Site and Environment");
		case 'fabrication': return localize('office.tab.fabrication', "MEP Fabrication");
		case 'phasing': return localize('office.tab.phasing', "Phases and Options");
	}
}

function fixed(value: unknown, digits = 2): string {
	return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-';
}

const GROUPS = ['earthwork', 'concrete', 'masonry', 'finishes', 'reinforcement', 'formwork', 'steel', 'mep'] as const;

/**
 * Alpha 9 L11, the office tools in one editor with a tab per tool: the 4D programme (Gantt),
 * cost-driven optimisation, 2D takeoff on PDF sheets, the site's terrain with sun, daylight and
 * road noise studies, MEP fabrication detailing and the phases and design options. The work is
 * the backend's (`saengine.rpc.office`); this editor shows it and keeps the project files.
 */
export class OfficeToolsEditor extends EditorPane {

	private frame!: EditorFrame;
	private content!: HTMLElement;
	private tool: OfficeTool = 'schedule';
	private readonly tabButtons = new Map<OfficeTool, HTMLButtonElement>();
	private readonly renderStore = this._register(new DisposableStore());

	private schedule: ISchedule | undefined;
	private scheduleNotes: readonly string[] = [];
	private costResult: ICostOptimisation | undefined;
	private readonly costAccepted = new Set<string>();
	private takeoff: ITakeoff = emptyTakeoff();
	private takeoffSheet: string | undefined;
	private takeoffSegments: readonly number[][] = [];
	private takeoffSize: readonly number[] = [420, 297];
	private takeoffMode: TakeoffMode = 'pan';
	private takeoffDraft: Point2[] = [];
	private takeoffView = { x: 0, y: 0, w: 420, h: 297 };
	private siteResults: { [key: string]: Answer | undefined } = {};
	private fabricationResult: Answer | undefined;
	private phasingResult: Answer | undefined;
	private optionsResult: Answer | undefined;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiation: IInstantiationService,
		@ICommandService private readonly commands: ICommandService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogs: IFileDialogService,
		@IEditorService private readonly editorService: IEditorService,
		@ITextModelService private readonly textModels: ITextModelService,
		@ITextFileService private readonly textFiles: ITextFileService,
	) {
		super(OfficeToolsInput.EDITOR_ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiation.createInstance(EditorFrame, parent, {
			id: OfficeToolsInput.EDITOR_ID,
			ariaLabel: localize('office.toolbar', "Office Tools"),
		}));
		this.frame.element.classList.add('saengine-office-tools');
		const tabs = append(this.frame.titleSlot, $('.sa-segmented', { role: 'tablist', 'aria-label': localize('office.tabsAria', "Office tool") }));
		for (const tool of OFFICE_TOOLS) {
			const button = append(tabs, $<HTMLButtonElement>('button.sa-segment', { type: 'button', role: 'tab' }));
			append(button, $('span', undefined, toolLabel(tool)));
			this._register(addDisposableListener(button, EventType.CLICK, () => this.show(tool)));
			this.tabButtons.set(tool, button);
		}
		this.content = append(this.frame.main, $('.office-content', { tabIndex: -1 }));
	}

	override async setInput(input: OfficeToolsInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.show(input.tool);
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	/** Shows the tab of `tool` (also when the editor is opened again for another tool). */
	show(tool: OfficeTool): void {
		this.tool = tool;
		if (this.input instanceof OfficeToolsInput) {
			this.input.tool = tool;
		}
		for (const [t, button] of this.tabButtons) {
			button.classList.toggle('checked', t === tool);
			button.setAttribute('aria-selected', String(t === tool));
		}
		void this.render();
	}

	// ─────────────────────────────── plumbing ───────────────────────────────

	private get root(): URI | undefined {
		return this.projectService.project?.root;
	}

	private async request<T extends Problems>(method: string, params: object): Promise<T | undefined> {
		this.frame.showProgress();
		try {
			return await this.commands.executeCommand<T>(OFFICE_REQUEST_COMMAND, method, params);
		} catch (error) {
			this.frame.setStatus({ text: localize('office.failed', "The engine could not do it: {0}", String(error)), severity: 'error' });
			return undefined;
		} finally {
			this.frame.hideProgress();
		}
	}

	/** The text of a project file as the editors have it (unsaved edits included), or undefined. */
	private async readText(rel: string): Promise<string | undefined> {
		const root = this.root;
		if (!root) {
			return undefined;
		}
		const resource = joinPath(root, ...rel.split('/'));
		const model = this.textFiles.files.get(resource)?.textEditorModel;
		if (model) {
			return model.getValue();
		}
		try {
			return (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return undefined;
		}
	}

	/** Writes a project file: as an undoable edit of its open model, then saved; a new file directly. */
	private async writeText(rel: string, text: string): Promise<void> {
		const root = this.root;
		if (!root) {
			return;
		}
		const resource = joinPath(root, ...rel.split('/'));
		if (!(await this.fileService.exists(resource))) {
			await this.fileService.writeFile(resource, VSBuffer.fromString(text));
			return;
		}
		const reference = await this.textModels.createModelReference(resource);
		try {
			const model = reference.object.textEditorModel;
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null);
			await this.textFiles.save(resource);
		} finally {
			reference.dispose();
		}
	}

	private async openProjectFile(rel: string, template: string): Promise<void> {
		const root = this.root;
		if (!root) {
			return;
		}
		const resource = joinPath(root, ...rel.split('/'));
		if (!(await this.fileService.exists(resource))) {
			await this.fileService.writeFile(resource, VSBuffer.fromString(template));
		}
		await this.editorService.openEditor({ resource, options: { pinned: true } });
	}

	private problems(answer: Problems | undefined): boolean {
		if (!answer) {
			return true;
		}
		if (answer.problems?.length) {
			this.frame.setStatus({ text: answer.problems.join(' '), severity: 'warning' });
			return true;
		}
		return false;
	}

	private button(parent: HTMLElement, label: string, run: () => void | Promise<void>, primary = false): HTMLButtonElement {
		const button = append(parent, $<HTMLButtonElement>(`button.office-button${primary ? '.primary' : ''}`, { type: 'button' }, label));
		this.renderStore.add(addDisposableListener(button, EventType.CLICK, () => void run()));
		return button;
	}

	private field(parent: HTMLElement, label: string, value: string, type = 'text', width?: number): HTMLInputElement {
		const wrap = append(parent, $('label.office-field'));
		append(wrap, $('span', undefined, label));
		const input = append(wrap, $<HTMLInputElement>('input.office-input', { type, value }));
		if (width) {
			input.style.width = `${width}px`;
		}
		return input;
	}

	private table(parent: HTMLElement, headers: readonly string[], rows: readonly (readonly (string | HTMLElement)[])[]): HTMLTableElement {
		const table = append(parent, $<HTMLTableElement>('table.office-table'));
		const head = append(append(table, $('thead')), $('tr'));
		headers.forEach(h => append(head, $('th', undefined, h)));
		const body = append(table, $('tbody'));
		for (const row of rows) {
			const tr = append(body, $('tr'));
			for (const cell of row) {
				const td = append(tr, $('td'));
				if (typeof cell === 'string') {
					td.textContent = cell;
				} else {
					append(td, cell);
				}
			}
		}
		return table;
	}

	private notes(parent: HTMLElement, notes: readonly string[] | undefined): void {
		if (notes?.length) {
			const list = append(parent, $('ul.office-notes'));
			notes.forEach(n => append(list, $('li', undefined, n)));
		}
	}

	private async render(): Promise<void> {
		this.renderStore.clear();
		clearNode(this.content);
		this.frame.setStatus(undefined);
		if (!this.root) {
			append(this.content, $('p.office-empty', undefined, localize('office.noProject', "Open a SAEngine project to use the office tools.")));
			return;
		}
		switch (this.tool) {
			case 'schedule': return this.renderSchedule();
			case 'cost': return this.renderCost();
			case 'takeoff': return this.renderTakeoff();
			case 'site': return this.renderSite();
			case 'fabrication': return this.renderFabrication();
			case 'phasing': return this.renderPhasing();
		}
	}

	// ─────────────────────────────── 4D programme ───────────────────────────────

	private async renderSchedule(): Promise<void> {
		if (!this.schedule) {
			const text = await this.readText(SCHEDULE_FILE);
			if (text) {
				try {
					this.schedule = JSON.parse(text) as ISchedule;
				} catch {
					this.schedule = undefined;
				}
			}
		}
		const bar = append(this.content, $('.office-bar'));
		const start = this.field(bar, localize('office.schedule.start', "Start"), this.schedule?.start ?? new Date().toISOString().slice(0, 10), 'date');
		this.button(bar, localize('office.schedule.generate', "Generate from the Model"), async () => {
			const answer = await this.request<IScheduleAnswer>('office/schedule', { projectRoot: this.root!.fsPath, start: start.value || undefined });
			if (!this.problems(answer) && answer?.schedule) {
				this.schedule = answer.schedule;
				this.scheduleNotes = answer.schedule.notes ?? [];
				void this.render();
			}
		}, true);
		if (this.schedule) {
			this.button(bar, localize('office.schedule.save', "Save"), () => this.writeText(SCHEDULE_FILE, JSON.stringify(this.schedule, undefined, 2) + '\n'));
			for (const [format, label, ext] of [['csv', localize('office.schedule.csv', "Export CSV..."), 'csv'], ['mspdi', localize('office.schedule.msp', "Export MS Project XML..."), 'xml']] as const) {
				this.button(bar, label, async () => {
					const target = await this.fileDialogs.showSaveDialog({ defaultUri: joinPath(this.root!, '11 Exports', `programme.${ext}`), filters: [{ name: format.toUpperCase(), extensions: [ext] }] });
					if (target) {
						const answer = await this.request<Answer>('office/exportSchedule', { text: JSON.stringify(this.schedule), path: target.fsPath, format });
						if (!this.problems(answer)) {
							this.frame.setStatus({ text: localize('office.schedule.exported', "Written {0}", target.fsPath) });
						}
					}
				});
			}
			this.button(bar, localize('office.schedule.play', "Play in the BIM View"), async () => {
				// W4C-13: the BIM view plays the programme as saved: save it, then open the view with its 4D bar playing.
				await this.writeText(SCHEDULE_FILE, JSON.stringify(this.schedule, undefined, 2) + '\n');
				await this.commands.executeCommand('saengine.bim.play4d', true);
			});
		}
		if (!this.schedule) {
			append(this.content, $('p.office-empty', undefined, localize('office.schedule.empty', "Generate the programme from the building model and the bill of quantities: activities per level and zone, durations from the quantities and the office's productivity rates (10 BOQ/productivity.json), the floor cycle of Project Settings.")));
			this.button(this.content, localize('office.schedule.rates', "Edit Productivity Rates"), async () => {
				const template = await this.request<Answer>('office/productivityTemplate', {});
				await this.openProjectFile('10 BOQ/productivity.json', typeof template?.text === 'string' ? template.text : '{}\n');
			});
			return;
		}
		this.renderGantt(this.schedule);
		this.notes(this.content, this.scheduleNotes.length ? this.scheduleNotes : this.schedule.notes);
		const critical = this.schedule.activities.filter(a => a.critical).length;
		this.frame.setStatus({ text: localize('office.schedule.status', "{0} activities, finish {1}, {2} critical", this.schedule.activities.length, this.schedule.finish ?? '-', critical) });
	}

	private renderGantt(schedule: ISchedule): void {
		const layout = ganttLayout(schedule);
		const wrap = append(this.content, $('.office-gantt'));
		const left = append(wrap, $('table.office-table.office-gantt-table'));
		const head = append(append(left, $('thead')), $('tr'));
		[localize('office.gantt.activity', "Activity"), localize('office.gantt.days', "Days"), localize('office.gantt.startCol', "Start"), localize('office.gantt.finish', "Finish"), localize('office.gantt.float', "Float")]
			.forEach(h => append(head, $('th', undefined, h)));
		const body = append(left, $('tbody'));
		const rowHeight = 24;
		for (const bar of layout.bars) {
			const a = bar.activity;
			const tr = append(body, $(`tr${a.critical ? '.critical' : ''}`));
			tr.style.height = `${rowHeight}px`;
			append(tr, $('td', { title: a.id }, a.name));
			const days = append(append(tr, $('td')), $<HTMLInputElement>('input.office-input.office-days', { type: 'number', min: '0', step: '1', value: String(a.duration ?? a.days) }));
			this.renderStore.add(addDisposableListener(days, EventType.CHANGE, async () => {
				const value = Number(days.value);
				a.duration = Number.isFinite(value) && value >= 0 ? value : undefined;
				const answer = await this.request<IScheduleAnswer>('office/reschedule', { text: JSON.stringify(schedule) });
				if (!this.problems(answer) && answer?.schedule) {
					this.schedule = answer.schedule;
					void this.render();
				}
			}));
			append(tr, $('td', undefined, a.earlyStart ?? '-'));
			append(tr, $('td', undefined, a.earlyFinish ?? '-'));
			append(tr, $('td', undefined, a.totalFloat === undefined ? '-' : String(a.totalFloat)));
		}
		const dayWidth = Math.max(4, Math.min(24, 900 / layout.totalDays));
		const width = layout.totalDays * dayWidth + 40;
		const height = (layout.bars.length + 1) * rowHeight + 4;
		const chart = svg(append(wrap, $('.office-gantt-chart')), 'svg', { width, height, class: 'office-gantt-svg' });
		for (const tick of layout.ticks) {
			const x = tick.offset * dayWidth;
			svg(chart, 'line', { x1: x, y1: rowHeight, x2: x, y2: height, class: 'tick' });
			svg(chart, 'text', { x: x + 2, y: rowHeight - 8, class: 'tick-label' }).textContent = tick.label;
		}
		for (const bar of layout.bars) {
			const y = (bar.row + 1) * rowHeight + 4;
			const rect = svg(chart, 'rect', { x: bar.offset * dayWidth, y, width: Math.max(bar.length * dayWidth - 1, 2), height: rowHeight - 8, rx: 2, class: bar.activity.critical ? 'bar critical' : 'bar' });
			svg(rect, 'title').textContent = `${bar.activity.name}: ${bar.activity.earlyStart} - ${bar.activity.earlyFinish}`;
		}
		for (const link of layout.links) {
			const from = layout.bars[link.from];
			const to = layout.bars[link.to];
			const x1 = (link.type === 'FS' ? from.offset + from.length : from.offset) * dayWidth;
			const y1 = (from.row + 1) * rowHeight + rowHeight / 2;
			const x2 = to.offset * dayWidth;
			const y2 = (to.row + 1) * rowHeight + rowHeight / 2;
			svg(chart, 'path', { d: `M${x1},${y1} H${Math.max(x1, x2 - 4)} V${y2} H${x2}`, class: 'link' });
		}
	}

	// ─────────────────────────────── cost optimisation ───────────────────────────────

	private async renderCost(): Promise<void> {
		const bar = append(this.content, $('.office-bar'));
		const depths = this.field(bar, localize('office.cost.depths', "RC beam depth steps [mm]"), '0, 50, 100, 150', 'text', 140);
		this.button(bar, localize('office.cost.run', "Find the Cheapest Passing Options"), async () => {
			const fem = partById('fem');
			if (!fem?.mainFile) {
				return;
			}
			const model = joinPath(this.root!, fem.folder, fem.mainFile);
			const steps = depths.value.split(/[,;\s]+/).map(Number).filter(Number.isFinite);
			const answer = await this.request<ICostOptimisation>('office/optimise', {
				...designArguments(model),
				ratesText: await this.readText('10 BOQ/rates.json'),
				options: { depthSteps: steps.length ? steps : undefined },
			});
			if (!this.problems(answer) && answer) {
				this.costResult = answer;
				this.costAccepted.clear();
				answer.groups?.filter(g => g.status === 'cheaper').forEach(g => this.costAccepted.add(g.type));
				void this.render();
			}
		}, true);
		const result = this.costResult;
		if (!result) {
			append(this.content, $('p.office-empty', undefined, localize('office.cost.empty', "Searches each member group's sections, steel grades and concrete strengths for the cheapest that passes Design Reinforcement's checks, priced with the schedule of rates (10 BOQ/rates.json). Run the analysis and the design checks first.")));
			return;
		}
		if (result.groups?.some(g => g.status === 'cheaper')) {
			this.button(bar, localize('office.cost.apply', "Apply the Ticked Options to 04 Objects"), async () => {
				const objects = partById('objects');
				if (!objects?.mainFile) {
					return;
				}
				const rel = `${objects.folder}/${objects.mainFile}`;
				const text = await this.readText(rel);
				if (!text) {
					return;
				}
				const answer = await this.request<Answer>('office/applyOptimisation', { objectsText: text, result, accept: [...this.costAccepted] });
				if (!this.problems(answer) && typeof answer?.objectsText === 'string') {
					await this.writeText(rel, answer.objectsText);
					this.frame.setStatus({ text: localize('office.cost.applied', "04 Objects changed: run the analysis and the design checks again (the stiffness changed)."), severity: 'warning' });
				}
			});
		}
		const currency = result.currency ?? '';
		const rows = (result.groups ?? []).map(g => {
			const tick = $<HTMLInputElement>('input', { type: 'checkbox' });
			tick.checked = this.costAccepted.has(g.type);
			tick.disabled = g.status !== 'cheaper';
			this.renderStore.add(addDisposableListener(tick, EventType.CHANGE, () => {
				if (tick.checked) {
					this.costAccepted.add(g.type);
				} else {
					this.costAccepted.delete(g.type);
				}
			}));
			return [
				tick,
				g.name ? `${g.type} (${g.name})` : g.type,
				g.kind,
				g.skipped ? g.skipped : `${g.members?.length ?? 0} / ${fixed(g.length, 1)} m`,
				g.current ? `${g.current.label}: ${fixed(g.current.cost, 0)}${g.current.passes === false ? ` (${localize('office.cost.fails', "fails")})` : ''}` : '-',
				g.best ? `${g.best.label}: ${fixed(g.best.cost, 0)}` : '-',
				fixed(g.delta, 0),
				[...(g.notes ?? [])].join('; '),
			];
		});
		this.table(this.content, ['', localize('office.cost.group', "Group"), localize('office.cost.kind', "Kind"), localize('office.cost.members', "Members / length"),
			localize('office.cost.current', "Current ({0})", currency), localize('office.cost.best', "Cheapest passing ({0})", currency), localize('office.cost.delta', "Delta"), localize('office.cost.notes', "Notes")], rows);
		this.notes(this.content, [...(result.notes ?? []), ...(result.limits ?? [])]);
		if (result.total) {
			this.frame.setStatus({ text: localize('office.cost.total', "Optimised groups: {0} {1} now, {2} {1} at best ({3})", fixed(result.total.current, 0), currency, fixed(result.total.best, 0), fixed(result.total.delta, 0)) });
		}
	}

	// ─────────────────────────────── PDF takeoff ───────────────────────────────

	private async renderTakeoff(): Promise<void> {
		if (!this.takeoff.sheets.length) {
			const text = await this.readText(TAKEOFF_FILE);
			if (text) {
				try {
					this.takeoff = JSON.parse(text) as ITakeoff;
				} catch {
					this.takeoff = emptyTakeoff();
				}
			}
		}
		const bar = append(this.content, $('.office-bar'));
		const sheetSelect = append(bar, $<HTMLSelectElement>('select.office-input'));
		for (const sheet of this.takeoff.sheets) {
			append(sheetSelect, $<HTMLOptionElement>('option', { value: sheet.id }, sheet.name || `${sheet.file} p${sheet.page}`));
		}
		this.takeoffSheet ??= this.takeoff.sheets[0]?.id;
		if (this.takeoffSheet) {
			sheetSelect.value = this.takeoffSheet;
		}
		this.renderStore.add(addDisposableListener(sheetSelect, EventType.CHANGE, () => {
			this.takeoffSheet = sheetSelect.value;
			this.takeoffSegments = [];
			void this.render();
		}));
		this.button(bar, localize('office.takeoff.addSheet', "Add PDF Sheet..."), () => this.addSheet());
		const sheet = this.takeoff.sheets.find(s => s.id === this.takeoffSheet);
		if (!sheet) {
			append(this.content, $('p.office-empty', undefined, localize('office.takeoff.empty', "Add a PDF drawing, calibrate it to scale (two points and the length between them), then measure lengths, areas and counts. The items go into the bill as \"measured from drawing\" when 10 BOQ is computed again.")));
			return;
		}
		const modes: [TakeoffMode, string][] = [
			['pan', localize('office.takeoff.pan', "Pan")],
			['calibrate', localize('office.takeoff.calibrate', "Calibrate")],
			['length', localize('office.takeoff.length', "Length")],
			['area', localize('office.takeoff.area', "Area")],
			['count', localize('office.takeoff.count', "Count")],
		];
		const modeBar = append(bar, $('.sa-segmented'));
		for (const [mode, label] of modes) {
			const b = append(modeBar, $<HTMLButtonElement>(`button.sa-segment${this.takeoffMode === mode ? '.checked' : ''}`, { type: 'button' }, label));
			this.renderStore.add(addDisposableListener(b, EventType.CLICK, () => { this.takeoffMode = mode; this.takeoffDraft = []; void this.render(); }));
		}
		const description = this.field(bar, localize('office.takeoff.description', "Description"), '', 'text', 160);
		const group = append(bar, $<HTMLSelectElement>('select.office-input'));
		GROUPS.forEach(g => append(group, $<HTMLOptionElement>('option', { value: g }, g)));
		group.value = 'finishes';
		const extra = this.field(bar, localize('office.takeoff.extra', "Height / depth [mm]"), '', 'number', 90);
		const finish = this.button(bar, localize('office.takeoff.finish', "Finish Item"), () => {
			const points = [...this.takeoffDraft];
			const mode = this.takeoffMode;
			if (mode !== 'length' && mode !== 'area' && mode !== 'count') {
				return;
			}
			const kind: ITakeoffItem['kind'] = mode;
			if (points.length < (kind === 'area' ? 3 : kind === 'length' ? 2 : 1)) {
				return;
			}
			const value = Number(extra.value);
			const item: ITakeoffItem = {
				id: nextId('T', this.takeoff.items.map(i => i.id)), sheet: sheet.id, kind, points,
				description: description.value.trim() || localize('office.takeoff.unnamed', "Measured item"), group: group.value,
				...(kind === 'length' && value > 0 ? { height: value } : {}),
				...(kind === 'area' && value > 0 ? { depth: value } : {}),
			};
			this.takeoff.items.push(item);
			this.takeoffDraft = [];
			void this.render();
		});
		finish.disabled = this.takeoffMode === 'pan' || this.takeoffMode === 'calibrate';
		this.button(bar, localize('office.takeoff.save', "Save"), () => this.writeText(TAKEOFF_FILE, JSON.stringify(this.takeoff, undefined, 2) + '\n'), true);

		const scale = sheetScale(sheet);
		append(this.content, $('p.office-hint', undefined, scale
			? localize('office.takeoff.scale', "Scale 1:{0} ({1}). Click points on the drawing; Finish Item ends a length, area or count.", fixed(scale, 1), sheet.calibration ? localize('office.takeoff.calibrated', "calibrated") : localize('office.takeoff.stated', "drawing scale"))
			: localize('office.takeoff.uncalibrated', "Not calibrated: choose Calibrate, click two points whose true length you know, then give it.")));
		await this.loadSegments(sheet);
		this.renderSheet(sheet);
		const rows = this.takeoff.items.filter(i => i.sheet === sheet.id).map(item => {
			const measured = measureItem(item, sheet);
			const remove = $<HTMLButtonElement>('button.office-link', { type: 'button' }, localize('office.takeoff.remove', "Remove"));
			this.renderStore.add(addDisposableListener(remove, EventType.CLICK, () => {
				this.takeoff.items = this.takeoff.items.filter(i => i !== item);
				void this.render();
			}));
			return [item.id, item.description, item.group, item.kind, measured ? `${fixed(measured.quantity, 3)} ${measured.unit}` : '-', remove];
		});
		this.table(this.content, [localize('office.takeoff.id', "Id"), localize('office.takeoff.desc', "Description"), localize('office.takeoff.group', "Group"), localize('office.takeoff.kind', "Kind"), localize('office.takeoff.quantity', "Quantity"), ''], rows);
	}

	private async addSheet(): Promise<void> {
		const picked = await this.fileDialogs.showOpenDialog({ canSelectFiles: true, canSelectMany: false, filters: [{ name: 'PDF', extensions: ['pdf'] }], defaultUri: this.root });
		const file = picked?.[0];
		if (!file) {
			return;
		}
		const root = this.root!;
		const rel = file.fsPath.toLowerCase().startsWith(root.fsPath.toLowerCase()) ? file.fsPath.slice(root.fsPath.length + 1).replace(/\\/g, '/') : file.fsPath;
		const sheet: ITakeoffSheet = { id: nextId('S', this.takeoff.sheets.map(s => s.id)), file: rel, page: 1, name: `${file.path.replace(/^.*\//, '')} p1` };
		this.takeoff.sheets.push(sheet);
		this.takeoffSheet = sheet.id;
		this.takeoffSegments = [];
		void this.render();
	}

	private async loadSegments(sheet: ITakeoffSheet): Promise<void> {
		if (this.takeoffSegments.length) {
			return;
		}
		const path = /^[a-zA-Z]:|^\//.test(sheet.file) ? sheet.file : joinPath(this.root!, ...sheet.file.split('/')).fsPath;
		try {
			const answer = await this.commands.executeCommand<{ ok?: boolean; segments?: number[][]; size?: number[]; scale?: number; message?: string }>(PDF_TO_DXF_COMMAND, { path, page: sheet.page });
			if (answer?.ok) {
				this.takeoffSegments = answer.segments ?? [];
				this.takeoffSize = answer.size ?? [420, 297];
				this.takeoffView = { x: 0, y: 0, w: this.takeoffSize[0], h: this.takeoffSize[1] };
				if (!sheet.calibration && !sheet.scale && answer.scale) {
					sheet.scale = answer.scale; // the scale the page states, until calibrated
				}
			} else if (answer?.message) {
				this.frame.setStatus({ text: answer.message, severity: 'warning' });
			}
		} catch (error) {
			this.frame.setStatus({ text: String(error), severity: 'error' });
		}
	}

	private renderSheet(sheet: ITakeoffSheet): void {
		const [, pageHeight] = this.takeoffSize;
		const host = append(this.content, $('.office-sheet'));
		const view = this.takeoffView;
		const canvas = svg(host, 'svg', { class: 'office-sheet-svg', viewBox: `${view.x} ${view.y} ${view.w} ${view.h}`, preserveAspectRatio: 'xMidYMid meet' });
		// Paper mm, y up: flipped into the SVG's y down.
		const flip = (p: readonly number[]) => [p[0], pageHeight - p[1]];
		const drawing = svg(canvas, 'g', { class: 'drawing' });
		for (const s of this.takeoffSegments) {
			const [x1, y1] = flip([s[0], s[1]]);
			const [x2, y2] = flip([s[2], s[3]]);
			svg(drawing, 'line', { x1, y1, x2, y2 });
		}
		for (const item of this.takeoff.items.filter(i => i.sheet === sheet.id)) {
			const pts = item.points.map(flip).map(p => p.join(',')).join(' ');
			if (item.kind === 'count') {
				item.points.map(flip).forEach(([x, y]) => svg(canvas, 'circle', { cx: x, cy: y, r: view.w / 300, class: 'item count' }));
			} else {
				svg(canvas, item.kind === 'area' ? 'polygon' : 'polyline', { points: pts, class: `item ${item.kind}` });
			}
		}
		if (this.takeoffDraft.length) {
			svg(canvas, this.takeoffMode === 'area' ? 'polygon' : 'polyline', { points: this.takeoffDraft.map(flip).map(p => p.join(',')).join(' '), class: 'item draft' });
		}
		if (sheet.calibration) {
			const [a, b] = [flip(sheet.calibration.a), flip(sheet.calibration.b)];
			svg(canvas, 'line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: 'calibration' });
		}
		const toPaper = (e: MouseEvent): Point2 => {
			const box = canvas.getBoundingClientRect();
			const k = Math.max(view.w / box.width, view.h / box.height);
			const ox = (box.width * k - view.w) / 2;
			const oy = (box.height * k - view.h) / 2;
			const x = view.x + (e.clientX - box.left) * k - ox;
			const y = view.y + (e.clientY - box.top) * k - oy;
			let best: Point2 = [x, pageHeight - y];
			let distance = 8 * k; // snap within 8 px to a line's end
			for (const s of this.takeoffSegments) {
				for (const [px, py] of [[s[0], s[1]], [s[2], s[3]]]) {
					const d = Math.hypot(px - best[0], py - (pageHeight - y));
					if (d < distance) {
						distance = d;
						best = [px, py];
					}
				}
			}
			return best;
		};
		let drag: { x: number; y: number } | undefined;
		this.renderStore.add(addDisposableListener(canvas, EventType.MOUSE_DOWN, e => { if (this.takeoffMode === 'pan') { drag = { x: e.clientX, y: e.clientY }; } }));
		this.renderStore.add(addDisposableListener(canvas, EventType.MOUSE_MOVE, e => {
			if (drag) {
				const box = canvas.getBoundingClientRect();
				const k = Math.max(view.w / box.width, view.h / box.height);
				view.x -= (e.clientX - drag.x) * k;
				view.y -= (e.clientY - drag.y) * k;
				drag = { x: e.clientX, y: e.clientY };
				canvas.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
			}
		}));
		this.renderStore.add(addDisposableListener(canvas, EventType.MOUSE_UP, () => { drag = undefined; }));
		this.renderStore.add(addDisposableListener(canvas, EventType.MOUSE_WHEEL, (e: WheelEvent) => {
			e.preventDefault();
			const factor = e.deltaY > 0 ? 1.2 : 1 / 1.2;
			const cx = view.x + view.w / 2;
			const cy = view.y + view.h / 2;
			view.w *= factor;
			view.h *= factor;
			view.x = cx - view.w / 2;
			view.y = cy - view.h / 2;
			canvas.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
		}, { passive: false }));
		this.renderStore.add(addDisposableListener(canvas, EventType.CLICK, async e => {
			if (this.takeoffMode === 'pan') {
				return;
			}
			this.takeoffDraft.push(toPaper(e));
			if (this.takeoffMode === 'calibrate' && this.takeoffDraft.length === 2) {
				const [a, b] = this.takeoffDraft;
				this.takeoffDraft = [];
				const length = await this.askLength();
				if (length && length > 0) {
					const answer = await this.request<Answer>('office/calibrate', { a, b, length });
					const calibration = answer?.calibration as ITakeoffSheet['calibration'] | undefined;
					if (!this.problems(answer) && calibration) {
						sheet.calibration = calibration;
						this.takeoffMode = 'length';
					}
				}
			}
			void this.render();
		}));
	}

	/** The true length between the two calibration points [mm], asked in the toolbar. */
	private askLength(): Promise<number | undefined> {
		return new Promise(resolve => {
			const bar = append(this.content, $('.office-bar.office-ask'));
			const input = this.field(bar, localize('office.takeoff.trueLength', "True length between the two points [mm]"), '', 'number', 120);
			this.button(bar, localize('office.takeoff.setScale', "Set Scale"), () => { resolve(Number(input.value)); bar.remove(); }, true);
			this.button(bar, localize('office.takeoff.cancel', "Cancel"), () => { resolve(undefined); bar.remove(); });
			bar.scrollIntoView();
			input.focus();
		});
	}

	// ─────────────────────────────── site and environment ───────────────────────────────

	private async renderSite(): Promise<void> {
		const root = this.root!;
		// Terrain.
		const terrain = append(this.content, $('section.office-section'));
		append(terrain, $('h3', undefined, localize('office.site.terrain', "Terrain and cut / fill")));
		const tbar = append(terrain, $('.office-bar'));
		const units = append(tbar, $<HTMLSelectElement>('select.office-input', { title: localize('office.site.units', "Survey units") }));
		['m', 'mm', 'ft'].forEach(u => append(units, $<HTMLOptionElement>('option', { value: u }, u)));
		const crs = this.field(tbar, localize('office.site.crs', "Coordinates"), 'project', 'text', 110);
		const datum = this.field(tbar, localize('office.site.datum', "Datum (survey level of z = 0)"), '', 'number', 90);
		const outline = append(tbar, $<HTMLSelectElement>('select.office-input', { title: localize('office.site.platform', "Platform") }));
		[['building', localize('office.site.building', "Building outline")], ['plot', localize('office.site.plot', "The plot")]].forEach(([v, l]) => append(outline, $<HTMLOptionElement>('option', { value: v }, l)));
		const level = this.field(tbar, localize('office.site.level', "Platform level [mm]"), '', 'number', 90);
		const margin = this.field(tbar, localize('office.site.margin', "Margin [mm]"), '0', 'number', 80);
		const platform = () => ({ outline: outline.value, margin: Number(margin.value) || 0, ...(level.value ? { level: Number(level.value) } : {}) });
		this.button(tbar, localize('office.site.import', "Import Survey (GeoTIFF, XYZ, DXF)..."), async () => {
			const picked = await this.fileDialogs.showOpenDialog({ canSelectFiles: true, filters: [{ name: localize('office.site.survey', "Survey"), extensions: ['tif', 'tiff', 'xyz', 'txt', 'csv', 'dxf'] }], defaultUri: root });
			if (picked?.[0]) {
				this.siteResults.terrain = await this.request<Answer>('office/terrainImport', {
					projectRoot: root.fsPath, path: picked[0].fsPath, units: units.value,
					crs: crs.value.trim() && crs.value.trim() !== 'project' ? crs.value.trim() : undefined,
					datum: datum.value ? Number(datum.value) : undefined, platform: platform(),
				});
				void this.render();
			}
		}, true);
		this.button(tbar, localize('office.site.recompute', "Cut and Fill Again"), async () => {
			this.siteResults.terrain = await this.request<Answer>('office/terrainRecompute', { projectRoot: root.fsPath, platform: platform() });
			void this.render();
		});
		const tr = this.siteResults.terrain;
		if (tr && !this.problems(tr)) {
			const t = (tr.terrain ?? {}) as { cut?: number; fill?: number; platformArea?: number };
			append(terrain, $('p', undefined, localize('office.site.cutFill', "Cut {0} m³, fill {1} m³ over {2} m² ({3} points, {4} triangles). Compute 10 BOQ again to add them to the earthwork.", fixed(t.cut), fixed(t.fill), fixed(t.platformArea, 1), String(tr.pointCount ?? '-'), String(tr.triangleCount ?? '-'))));
			this.notes(terrain, tr.notes as string[] | undefined);
		}

		// Sun, daylight, noise.
		const env = append(this.content, $('section.office-section'));
		append(env, $('h3', undefined, localize('office.site.environment', "Sun, daylight and road noise")));
		const ebar = append(env, $('.office-bar'));
		const day = this.field(ebar, localize('office.site.day', "Day"), `${new Date().getFullYear()}-06-21`, 'date');
		this.button(ebar, localize('office.site.sun', "Sun and Shadows"), async () => { this.siteResults.sun = await this.request<Answer>('office/sun', { projectRoot: root.fsPath, day: day.value }); void this.render(); }, true);
		this.button(ebar, localize('office.site.daylight', "Daylight Factors"), async () => { this.siteResults.daylight = await this.request<Answer>('office/daylight', { projectRoot: root.fsPath }); void this.render(); });
		this.button(ebar, localize('office.site.noise', "Road Noise"), async () => { this.siteResults.noise = await this.request<Answer>('office/noise', { projectRoot: root.fsPath }); void this.render(); });
		this.button(ebar, localize('office.site.settings', "Study Settings (context, roads)"), () => this.openProjectFile(ENVIRONMENT_FILE, JSON.stringify({ schema: 'saengine.environment/1', context: [], roads: [], daylight: {} }, undefined, 2) + '\n'));
		const sun = this.siteResults.sun;
		if (sun && !this.problems(sun)) {
			this.renderSun(env, sun);
		}
		const daylight = this.siteResults.daylight;
		if (daylight && !this.problems(daylight)) {
			const rooms = (daylight.rooms ?? []) as { room: string; name: string; story: string; floorArea?: number; windowArea?: number; skyAngle?: number; df?: number; notes?: string[] }[];
			this.table(env, [localize('office.site.room', "Room"), localize('office.site.story', "Storey"), localize('office.site.floor', "Floor m²"), localize('office.site.glazing', "Glazing m²"), localize('office.site.sky', "Sky angle °"), localize('office.site.df', "Average DF %"), localize('office.site.notes', "Notes")],
				rooms.map(r => [`${r.room} ${r.name}`, r.story, fixed(r.floorArea, 1), fixed(r.windowArea), fixed(r.skyAngle, 0), fixed(r.df), (r.notes ?? []).join('; ')]));
			this.notes(env, daylight.notes as string[] | undefined);
		}
		const noise = this.siteResults.noise;
		if (noise && !this.problems(noise)) {
			const levels = ((noise.facades as { levels?: { l10?: number | null; screened?: string[] }[] } | undefined)?.levels ?? []);
			const values = levels.map(l => l.l10).filter((v): v is number => typeof v === 'number');
			append(env, $('p', undefined, localize('office.site.noiseSummary', "Facade L10,18h: {0} to {1} dB(A) at {2} points ({3} screened from every road).", values.length ? fixed(Math.min(...values), 1) : '-', values.length ? fixed(Math.max(...values), 1) : '-', String(levels.length), String(levels.filter(l => l.l10 === null).length))));
			this.notes(env, noise.notes as string[] | undefined);
		}
	}

	private renderSun(parent: HTMLElement, sun: Answer): void {
		const path = (sun.path ?? []) as { time: string; azimuth: number; elevation: number }[];
		append(parent, $('p', undefined, localize('office.site.sunSummary', "{0}: the sun is up {1} h (clock UTC{2}).", String(sun.day), fixed(sun.daylightHours, 1), String(sun.utcOffset))));
		const shadows = (sun.shadows ?? []) as { time: string; rings: number[][][] }[];
		const ground = sun.ground as { points?: number[]; hours?: number[] } | undefined;
		const pts = ground?.points ?? [];
		const hours = ground?.hours ?? [];
		if (pts.length) {
			let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
			for (let i = 0; i + 2 < pts.length; i += 3) {
				minX = Math.min(minX, pts[i]); maxX = Math.max(maxX, pts[i]);
				minY = Math.min(minY, pts[i + 1]); maxY = Math.max(maxY, pts[i + 1]);
			}
			const sel = append(parent, $<HTMLSelectElement>('select.office-input'));
			shadows.forEach((s, i) => append(sel, $<HTMLOptionElement>('option', { value: String(i) }, s.time)));
			sel.value = String(Math.floor(shadows.length / 2));
			const chart = svg(append(parent, $('.office-sun')), 'svg', { viewBox: `${minX} ${-maxY} ${Math.max(maxX - minX, 1)} ${Math.max(maxY - minY, 1)}`, class: 'office-sun-svg' });
			const top = Math.max(1, ...hours);
			const cell = Number((sun.ground as { spacing?: number }).spacing ?? 2000);
			for (let i = 0, k = 0; i + 2 < pts.length; i += 3, k++) {
				const t = hours[k] / top;
				svg(chart, 'rect', { x: pts[i] - cell / 2, y: -pts[i + 1] - cell / 2, width: cell, height: cell, fill: `hsl(${45 - 45 * (1 - t)}, 90%, ${25 + 45 * t}%)` });
			}
			const layer = svg(chart, 'g', { class: 'shadow' });
			const draw = () => {
				while (layer.firstChild) {
					layer.removeChild(layer.firstChild);
				}
				for (const ring of shadows[Number(sel.value)]?.rings ?? []) {
					svg(layer, 'polygon', { points: ring.map(p => `${p[0]},${-p[1]}`).join(' ') });
				}
			};
			draw();
			this.renderStore.add(addDisposableListener(sel, EventType.CHANGE, draw));
			append(parent, $('p.office-hint', undefined, localize('office.site.sunLegend', "Ground: direct sun hours of the day (dark: none, bright: {0} h); grey: the shadow at the time chosen.", fixed(top, 1))));
		}
		const facades = sun.facades as { hours?: number[] } | undefined;
		if (facades?.hours?.length) {
			append(parent, $('p', undefined, localize('office.site.facades', "Facade points: {0} to {1} h of direct sun.", fixed(Math.min(...facades.hours), 1), fixed(Math.max(...facades.hours), 1))));
		}
		this.table(parent, [localize('office.site.time', "Time"), localize('office.site.azimuth', "Azimuth °"), localize('office.site.elevation', "Elevation °")], path.filter((_, i) => i % 2 === 0).map(p => [p.time, fixed(p.azimuth, 1), fixed(p.elevation, 1)]));
		this.notes(parent, sun.notes as string[] | undefined);
	}

	// ─────────────────────────────── MEP fabrication ───────────────────────────────

	private async renderFabrication(): Promise<void> {
		const root = this.root!;
		const bar = append(this.content, $('.office-bar'));
		this.button(bar, localize('office.fab.run', "Detail the Routed Services and Write Spool Sheets"), async () => {
			this.fabricationResult = await this.request<Answer>('office/fabrication', { projectRoot: root.fsPath, write: true });
			void this.render();
		}, true);
		this.button(bar, localize('office.fab.options', "Fabrication Options"), () => this.openProjectFile(FABRICATION_FILE, JSON.stringify({ schema: 'saengine.mepFabrication/1' }, undefined, 2) + '\n'));
		const result = this.fabricationResult;
		if (!result) {
			append(this.content, $('p.office-empty', undefined, localize('office.fab.empty', "Details 7 MEP's ducts, fire mains and risers, cable trays and plumbing risers to fabrication level: fittings, cut pieces, spools and hangers at the code pack's spacings, with a spool sheet (DXF) per run in 11 Exports/MEP Fabrication.")));
			return;
		}
		if (this.problems(result)) {
			return;
		}
		const runs = (result.runs ?? []) as { id: string; family: string; size: string; length: number; pieces: unknown[]; fittings: unknown[]; hangers: unknown[]; spools: unknown[]; supportRule?: string; notes?: string[] }[];
		this.table(this.content, [localize('office.fab.runCol', "Run"), localize('office.fab.family', "Kind"), localize('office.fab.size', "Size"), localize('office.fab.length', "Length m"), localize('office.fab.pieces', "Pieces"), localize('office.fab.fittings', "Fittings"), localize('office.fab.hangers', "Hangers"), localize('office.fab.spools', "Spools"), localize('office.fab.rule', "Supports per"), localize('office.fab.notes', "Notes")],
			runs.map(r => [r.id, r.family, r.size, fixed(r.length), String(r.pieces.length), String(r.fittings.length), String(r.hangers.length), String(r.spools.length), r.supportRule ?? '-', (r.notes ?? []).join('; ')]));
		this.notes(this.content, result.notes as string[] | undefined);
		const files = (result.files ?? []) as string[];
		this.frame.setStatus({ text: localize('office.fab.written', "{0} files written to 11 Exports/MEP Fabrication", files.length) });
	}

	// ─────────────────────────────── phases and options ───────────────────────────────

	private async renderPhasing(): Promise<void> {
		const root = this.root!;
		const bar = append(this.content, $('.office-bar'));
		this.button(bar, localize('office.phase.edit', "Edit Phases"), () => this.openProjectFile(PHASING_FILE, JSON.stringify({ schema: 'saengine.phasing/1', phases: [{ id: 'existing', name: 'Existing' }, { id: 'new', name: 'New construction' }], defaultPhase: 'new', elements: {}, optionSets: [] }, undefined, 2) + '\n'));
		this.button(bar, localize('office.phase.bill', "Split the Bill by Phase"), async () => {
			this.phasingResult = await this.request<Answer>('office/phaseBill', { projectRoot: root.fsPath });
			void this.render();
		}, true);
		const versions = this.field(bar, localize('office.phase.versions', "Options (versions, labels or branches)"), 'working', 'text', 220);
		this.button(bar, localize('office.phase.compare', "Compare Side by Side"), async () => {
			const options = versions.value.split(',').map(v => v.trim()).filter(Boolean).map(version => ({ name: version, version }));
			this.optionsResult = await this.request<Answer>('office/compareOptions', { projectRoot: root.fsPath, options });
			void this.render();
		});
		const split = this.phasingResult;
		if (split && !this.problems(split)) {
			type Row = { code: string; description: string; unit: string; quantity: number };
			for (const phase of (split.phases ?? []) as { name: string; new: Row[]; demolished: Row[] }[]) {
				append(this.content, $('h3', undefined, phase.name));
				const rows = [...phase.new.map(r => [r.code, r.description, `${fixed(r.quantity, 3)} ${r.unit}`, localize('office.phase.new', "built")]), ...phase.demolished.map(r => [r.code, r.description, `${fixed(r.quantity, 3)} ${r.unit}`, localize('office.phase.demolished', "demolished")])];
				if (rows.length) {
					this.table(this.content, [localize('office.phase.code', "Item"), localize('office.phase.description', "Description"), localize('office.phase.quantity', "Quantity"), localize('office.phase.what', "Work")], rows);
				}
			}
		}
		const compared = this.optionsResult;
		if (compared && !this.problems(compared)) {
			type Option = { name: string; version: string; cost?: number; currency?: string; carbon?: number; quantities?: { [k: string]: number }; model?: { storeys?: number; height?: number }; results?: { failed?: number; maxUtilisation?: number } | null; problems?: string[] };
			const options = (compared.options ?? []) as Option[];
			const figure = (label: string, value: (o: Option) => string) => [label, ...options.map(value)];
			this.table(this.content, [localize('office.phase.figure', "Figure"), ...options.map(o => `${o.name} (${o.version})`)], [
				figure(localize('office.phase.storeys', "Storeys"), o => String(o.model?.storeys ?? '-')),
				figure(localize('office.phase.height', "Height m"), o => fixed(o.model?.height)),
				figure(localize('office.phase.concrete', "Concrete m³"), o => fixed(o.quantities?.concrete)),
				figure(localize('office.phase.bars', "Bars kg"), o => fixed(o.quantities?.reinforcement, 0)),
				figure(localize('office.phase.steel', "Structural steel kg"), o => fixed(o.quantities?.steel, 0)),
				figure(localize('office.phase.cost', "Cost"), o => `${fixed(o.cost, 0)} ${o.currency ?? ''}`),
				figure(localize('office.phase.carbon', "Embodied carbon t CO2e"), o => fixed(o.carbon)),
				figure(localize('office.phase.checks', "Design checks"), o => o.results ? localize('office.phase.checksValue', "{0} failing, max {1}", String(o.results.failed ?? '-'), fixed(o.results.maxUtilisation)) : '-'),
				figure(localize('office.phase.problems', "Notes"), o => (o.problems ?? []).join('; ')),
			]);
			this.notes(this.content, compared.notes as string[] | undefined);
		}
	}
}
