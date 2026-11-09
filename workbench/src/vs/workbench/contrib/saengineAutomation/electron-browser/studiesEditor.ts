/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/automation.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, getWindow } from '../../../../base/browser/dom.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { Action } from '../../../../base/common/actions.js';
import { disposableTimeout } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IFemSolverService } from '../../../../platform/saengine/common/femSolver.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { formatNumber } from '../../../services/saengineProject/common/formatting.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { chartBars, IStudyDocument, IStudyParameter, IStudyRow, PARAMETER_KINDS, ParameterKind, parseValues, slugId, STUDY_METRICS, STUDY_SCHEMA, StudyMetric, studyProblems, studyRows, variantCount } from '../common/automationModel.js';
import { bag, callBackend, saveProjectParts } from './automationBackend.js';
import { StudiesEditorInput } from './studiesEditorInput.js';

const POLL = 3000;
const SVG_NS = 'http://www.w3.org/2000/svg';
const DEFAULT_STEPS = ['bim', 'derive', 'analysis', 'design', 'boq'];

interface IParameterRow {
	kind: ParameterKind;
	values: string;
	option: string;
}

function kindLabel(kind: ParameterKind): string {
	switch (kind) {
		case 'gridSpacing': return localize('studies.gridSpacing', "Grid spacing (factor)");
		case 'storeyHeight': return localize('studies.storeyHeight', "Storey height (mm)");
		case 'concreteGrade': return localize('studies.concreteGrade', "Concrete grade (material id)");
		case 'sectionScale': return localize('studies.sectionScale', "Section size (factor)");
		case 'sectionFamily': return localize('studies.sectionFamily', "Section family (object type id)");
		case 'setValue': return localize('studies.setValue', "Any value (file and path)");
	}
}

function optionHint(kind: ParameterKind): string | undefined {
	switch (kind) {
		case 'gridSpacing': return localize('studies.axisHint', "axis: x, y or both");
		case 'sectionScale': return localize('studies.kindsHint', "kinds, e.g. column, beam");
		case 'sectionFamily': return localize('studies.typesHint', "object types to replace (empty: all of that kind)");
		case 'setValue': return localize('studies.pathHint', "file | path, e.g. 02 Project Settings/project-settings.json | loads/live");
		case 'storeyHeight': return localize('studies.firstHint', "\"first\": the first storey too");
		default: return undefined;
	}
}

function metricLabel(metric: StudyMetric): string {
	switch (metric) {
		case 'cost': return localize('studies.cost', "Cost");
		case 'steelKg': return localize('studies.steel', "Steel (kg)");
		case 'carbonKg': return localize('studies.carbon', "Carbon (kg CO2e)");
		case 'maxUtilisation': return localize('studies.utilisation', "Largest utilisation");
		case 'drift': return localize('studies.drift', "Largest drift ratio");
		case 'failed': return localize('studies.failed', "Failing members");
	}
}

/**
 * Design studies: parameters and their values make variants of the project (copies in
 * `12 Automation/studies/<id>/variants`), each run through Run All's steps in the engine's
 * background; the comparison (cost, steel, carbon, utilisation, drift) as a table and a bar
 * chart. Apply makes a variant's part files the project's and saves a version.
 */
export class StudiesEditor extends EditorPane {

	static readonly ID = 'workbench.editor.saengine.studies';

	private frame!: EditorFrame;
	private content!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private name = localize('studies.defaultName', "Study 1");
	private combine: 'all' | 'oneAtATime' = 'all';
	private parameters: IParameterRow[] = [{ kind: 'gridSpacing', values: '0.9, 1.0, 1.1', option: 'both' }];
	private metric: StudyMetric = 'cost';
	private state: Record<string, unknown> = {};
	private studyId: string | undefined;
	private readonly renderDisposables = this._register(new DisposableStore());
	private readonly poll = this._register(new MutableDisposable());

	private readonly runAction = this._register(new Action('saengine.studies.run', localize('studies.run', "Run Study"), ThemeIcon.asClassName(Codicon.play), true, () => this.run()));
	private readonly cancelAction = this._register(new Action('saengine.studies.cancel', localize('studies.cancelRun', "Stop the Study"), ThemeIcon.asClassName(Codicon.debugStop), false, () => this.cancel()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IFemSolverService private readonly femSolverService: IFemSolverService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super(StudiesEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: StudiesEditor.ID,
			ariaLabel: localize('studies.aria', "Design studies"),
		}));
		append(this.frame.titleSlot, $('span', undefined, localize('studies.title', "Design Studies")));
		this.frame.setHelp(localize('studies.help', "A study varies parameters of the project (grid spacing, storey height, concrete grade, section sizes or families, any value) and runs the analysis, design and bill of quantities for each variant on a copy of the project, one after the other in the background. The project itself is not changed until you apply a variant; before the study runs, its current state is saved as a version when the project keeps versions."));
		this.frame.setActions([this.runAction, this.cancelAction]);
		this.content = $('.saengine-studies');
		this.scrollable = this._register(new DomScrollableElement(this.content, { horizontal: ScrollbarVisibility.Auto, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode());
	}

	override async setInput(input: StudiesEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		const list = bag(await this.call('studies/list', { projectRoot: input.projectRoot.fsPath }));
		const studies = Array.isArray(list.studies) ? list.studies.map(bag) : [];
		if (studies.length && typeof studies[0].id === 'string') {
			this.studyId = studies[0].id;
			this.name = String(studies[0].name ?? this.studyId);
			await this.refresh();
		}
		this.render();
	}

	override clearInput(): void {
		this.poll.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
		this.scrollable.scanDomNode();
	}

	private call(method: 'studies/list' | 'studies/start' | 'studies/status' | 'studies/cancel' | 'studies/apply', params: object): Promise<unknown> {
		return callBackend(this.instantiationService, this.femSolverService, method, params).catch(error => ({ error: error instanceof Error ? error.message : String(error) }));
	}

	private root(): string | undefined {
		const input = this.input;
		return input instanceof StudiesEditorInput ? input.projectRoot.fsPath : undefined;
	}

	private study(): IStudyDocument {
		const parameters: IStudyParameter[] = this.parameters.map(p => {
			const values = parseValues(p.values, p.kind);
			const option = p.option.trim();
			switch (p.kind) {
				case 'gridSpacing': return { kind: p.kind, values, axis: ['x', 'y'].includes(option) ? option : 'both' };
				case 'storeyHeight': return { kind: p.kind, values, includeFirst: option === 'first' };
				case 'sectionScale': return { kind: p.kind, values, kinds: option ? option.split(/[,\s]+/).filter(Boolean) : ['column', 'beam'] };
				case 'sectionFamily': {
					const family: IStudyParameter = { kind: p.kind, values, ...(option ? { types: option.split(/[,\s]+/).filter(Boolean) } : {}) };
					return family;
				}
				case 'setValue': {
					const [file, path] = option.split('|').map(s => s.trim());
					return { kind: p.kind, values, file, path };
				}
				default: return { kind: p.kind, values };
			}
		});
		return { schema: STUDY_SCHEMA, id: slugId(this.name), name: this.name, combine: this.combine, steps: DEFAULT_STEPS, parameters };
	}

	private render(): void {
		this.renderDisposables.clear();
		clearNode(this.content);
		const study = this.study();
		const running = this.state.state === 'running';
		const problems = studyProblems(study);
		this.runAction.enabled = !running && !problems.length && !!this.root();
		this.cancelAction.enabled = running;

		const form = append(this.content, $('section.form'));
		append(form, $('h2', undefined, localize('studies.define', "Study")));
		const nameRow = append(form, $('label.row'));
		append(nameRow, $('span', undefined, localize('studies.nameLabel', "Name")));
		const name = append(nameRow, $('input', { type: 'text', value: this.name })) as HTMLInputElement;
		name.value = this.name;
		this.renderDisposables.add(addDisposableListener(name, EventType.CHANGE, () => { this.name = name.value.trim() || this.name; this.render(); }));
		const combineRow = append(form, $('label.row'));
		append(combineRow, $('span', undefined, localize('studies.combine', "Variants")));
		const combine = append(combineRow, $('select')) as HTMLSelectElement;
		for (const [value, label] of [['all', localize('studies.all', "Every combination")], ['oneAtATime', localize('studies.oneAtATime', "One parameter at a time")]] as const) {
			const option = append(combine, $('option', { value }, label)) as HTMLOptionElement;
			option.selected = value === this.combine;
		}
		this.renderDisposables.add(addDisposableListener(combine, EventType.CHANGE, () => { this.combine = combine.value === 'oneAtATime' ? 'oneAtATime' : 'all'; this.render(); }));

		const table = append(form, $('table.parameters'));
		const head = append(table, $('tr'));
		for (const title of [localize('studies.parameter', "Parameter"), localize('studies.values', "Values (comma-separated)"), localize('studies.option', "Option"), '']) {
			append(head, $('th', undefined, title));
		}
		this.parameters.forEach((p, k) => {
			const row = append(table, $('tr'));
			const kind = append(append(row, $('td')), $('select')) as HTMLSelectElement;
			for (const value of PARAMETER_KINDS) {
				const option = append(kind, $('option', { value }, kindLabel(value))) as HTMLOptionElement;
				option.selected = value === p.kind;
			}
			this.renderDisposables.add(addDisposableListener(kind, EventType.CHANGE, () => { p.kind = kind.value as ParameterKind; p.option = ''; this.render(); }));
			const values = append(append(row, $('td')), $('input', { type: 'text' })) as HTMLInputElement;
			values.value = p.values;
			this.renderDisposables.add(addDisposableListener(values, EventType.CHANGE, () => { p.values = values.value; this.render(); }));
			const option = append(append(row, $('td')), $('input', { type: 'text', placeholder: optionHint(p.kind) ?? '' })) as HTMLInputElement;
			option.value = p.option;
			option.disabled = !optionHint(p.kind);
			this.renderDisposables.add(addDisposableListener(option, EventType.CHANGE, () => { p.option = option.value; this.render(); }));
			const remove = append(append(row, $('td')), $(`button.icon${ThemeIcon.asCSSSelector(Codicon.close)}`, { title: localize('studies.remove', "Remove"), 'aria-label': localize('studies.remove', "Remove") }));
			this.renderDisposables.add(addDisposableListener(remove, EventType.CLICK, () => { this.parameters.splice(k, 1); this.render(); }));
		});
		const add = append(form, $('button.link', undefined, localize('studies.addParameter', "Add a parameter")));
		this.renderDisposables.add(addDisposableListener(add, EventType.CLICK, () => { this.parameters.push({ kind: 'storeyHeight', values: '3000, 3300', option: '' }); this.render(); }));
		const count = variantCount(study);
		append(form, $('p.note', undefined, problems.includes('tooMany')
			? localize('studies.tooMany', "{0} variants: at most 32. Use fewer values or one parameter at a time.", count)
			: localize('studies.count', "{0} variant(s); each runs the building model, analysis, design and bill of quantities.", count)));

		this.renderResults();
		this.frame.setStatus({
			text: running
				? localize('studies.progress', "Running variant {0} of {1}...", String(this.state.index ?? 0), String(this.state.count ?? '?'))
				: this.state.state === 'failed' ? localize('studies.stopped', "The study stopped: {0}", String(this.state.error ?? '')) : localize('studies.idle', "Change the parameters, then Run Study."),
			busy: running,
			severity: this.state.state === 'failed' ? 'error' : 'info',
		});
		this.scrollable.scanDomNode();
	}

	private renderResults(): void {
		const rows: IStudyRow[] = studyRows(this.state.results);
		if (!rows.length) {
			return;
		}
		const section = append(this.content, $('section.results'));
		append(section, $('h2', undefined, localize('studies.comparison', "Comparison")));
		const base = bag(this.state.results).baseVersion;
		if (typeof base === 'string') {
			append(section, $('p.note', undefined, localize('studies.base', "Base: version {0}.", base)));
		}
		const table = append(section, $('table.comparison'));
		const head = append(table, $('tr'));
		for (const title of [localize('studies.variant', "Variant"), localize('studies.label', "Parameters"), ...STUDY_METRICS.map(metricLabel), '']) {
			append(head, $('th', undefined, title));
		}
		for (const row of rows) {
			const tr = append(table, $('tr'));
			tr.classList.toggle('failed', !row.ok);
			append(tr, $('td', undefined, row.id));
			append(tr, $('td', { title: row.error ?? '' }, row.error ? `${row.label} (${row.error})` : row.label));
			for (const metric of STUDY_METRICS) {
				const value = row[metric];
				append(tr, $('td.number', undefined, value === undefined ? '-' : metric === 'drift' ? value.toPrecision(3) : formatNumber(value, { decimals: metric === 'maxUtilisation' ? 2 : 0 })));
			}
			const cell = append(tr, $('td'));
			if (row.ok) {
				const apply = append(cell, $('button.link', undefined, localize('studies.apply', "Apply")));
				this.renderDisposables.add(addDisposableListener(apply, EventType.CLICK, () => this.apply(row.id)));
			}
		}
		const chartHead = append(section, $('label.row'));
		append(chartHead, $('span', undefined, localize('studies.chart', "Chart")));
		const select = append(chartHead, $('select')) as HTMLSelectElement;
		for (const metric of STUDY_METRICS) {
			const option = append(select, $('option', { value: metric }, metricLabel(metric))) as HTMLOptionElement;
			option.selected = metric === this.metric;
		}
		this.renderDisposables.add(addDisposableListener(select, EventType.CHANGE, () => { this.metric = select.value as StudyMetric; this.render(); }));
		const bars = chartBars(rows, this.metric);
		const doc = getWindow(this.content).document;
		const width = 520, barHeight = 18, gap = 6, labelWidth = 60;
		const svg = doc.createElementNS(SVG_NS, 'svg');
		svg.setAttribute('class', 'saengine-studies-chart');
		svg.setAttribute('width', String(width + labelWidth + 90));
		svg.setAttribute('height', String(bars.length * (barHeight + gap)));
		svg.setAttribute('role', 'img');
		svg.setAttribute('aria-label', localize('studies.chartAria', "{0} per variant", metricLabel(this.metric)));
		bars.forEach((bar, k) => {
			const y = k * (barHeight + gap);
			const label = doc.createElementNS(SVG_NS, 'text');
			label.setAttribute('x', '0');
			label.setAttribute('y', String(y + barHeight - 4));
			label.textContent = bar.id;
			svg.appendChild(label);
			const rect = doc.createElementNS(SVG_NS, 'rect');
			rect.setAttribute('x', String(labelWidth));
			rect.setAttribute('y', String(y));
			rect.setAttribute('height', String(barHeight));
			rect.setAttribute('width', String(Math.max(1, bar.fraction * width)));
			rect.setAttribute('class', bar.best ? 'bar best' : 'bar');
			svg.appendChild(rect);
			const value = doc.createElementNS(SVG_NS, 'text');
			value.setAttribute('x', String(labelWidth + bar.fraction * width + 6));
			value.setAttribute('y', String(y + barHeight - 4));
			value.textContent = bar.value === undefined ? '-' : this.metric === 'drift' ? bar.value.toPrecision(3) : formatNumber(bar.value, { decimals: this.metric === 'maxUtilisation' ? 2 : 0 });
			svg.appendChild(value);
		});
		section.appendChild(svg);
	}

	private async refresh(): Promise<void> {
		const root = this.root();
		if (!root || !this.studyId) {
			return;
		}
		this.state = bag(await this.call('studies/status', { projectRoot: root, id: this.studyId }));
		if (this.state.state === 'running') {
			this.poll.value = disposableTimeout(() => this.refresh().then(() => this.render()), POLL);
		} else {
			this.poll.clear();
		}
	}

	private async run(): Promise<void> {
		const root = this.root();
		const project = this.projectService.project;
		if (!root) {
			return;
		}
		if (project) {
			await saveProjectParts(this.textFileService, project);
		}
		const study = this.study();
		const answer = bag(await this.call('studies/start', { projectRoot: root, study }));
		if (typeof answer.error === 'string') {
			this.notificationService.error(localize('studies.cannotStart', "The study cannot start: {0}", answer.error));
			return;
		}
		this.studyId = study.id;
		await this.refresh();
		this.render();
	}

	private async cancel(): Promise<void> {
		const root = this.root();
		if (root && this.studyId) {
			await this.call('studies/cancel', { projectRoot: root, id: this.studyId });
			await this.refresh();
			this.render();
		}
	}

	private async apply(variant: string): Promise<void> {
		const root = this.root();
		if (!root || !this.studyId) {
			return;
		}
		const answer = bag(await this.call('studies/apply', { projectRoot: root, id: this.studyId, variant }));
		if (typeof answer.error === 'string') {
			this.notificationService.error(answer.error);
			return;
		}
		const copied = Array.isArray(answer.copied) ? answer.copied.length : 0;
		this.notificationService.info(typeof answer.version === 'string'
			? localize('studies.applied', "Variant {0} applied ({1} part files) and saved as version {2}.", variant, copied, answer.version)
			: localize('studies.appliedNoVersion', "Variant {0} applied ({1} part files). {2}", variant, copied, String(answer.note ?? '')));
	}
}
