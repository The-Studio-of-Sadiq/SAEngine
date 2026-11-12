/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IFieldSpec } from '../../saengineSoil/browser/soilDocument.js';
import { IMep } from './mepDocument.js';
import { IMepFormHost, UNIT_MM } from './mepForm.js';

/*
 * The coordination of 07 MEP beyond the MEP models against the structure: the clash tests
 * between the disciplines (structure, architecture, the MEP models, other IFC models), the other
 * IFC models, the IDS files, and the issues with their status workflow (new, active, reviewed,
 * approved, resolved, closed), exchanged as BCF 3.0. Stored in `mep.json` under `coordination`
 * (saengine.library.mep.Coordination); the backend runs the tests and the IDS checks and returns
 * the merged issues (saengine.mep.coordination, saengine.mep.bcf, saengine.mep.ids).
 */

export const MEP_COORDINATE_COMMAND = 'saengine.mep.coordinate';
export const MEP_EXPORT_BCF_COMMAND = 'saengine.mep.exportBcf';
export const MEP_IMPORT_BCF_COMMAND = 'saengine.mep.importBcf';
export const MEP_CHECK_IDS_COMMAND = 'saengine.mep.checkIds';

export type ClashSet = 'structure' | 'architecture' | 'mechanical' | 'plumbing' | 'fire' | 'electrical' | 'external';
export const CLASH_SETS: readonly ClashSet[] = ['structure', 'architecture', 'mechanical', 'plumbing', 'fire', 'electrical', 'external'];
export type IssueStatus = 'new' | 'active' | 'reviewed' | 'approved' | 'resolved' | 'closed';
export const ISSUE_STATUSES: readonly IssueStatus[] = ['new', 'active', 'reviewed', 'approved', 'resolved', 'closed'];
export type IssuePriority = 'low' | 'normal' | 'high' | 'critical';
export const ISSUE_PRIORITIES: readonly IssuePriority[] = ['low', 'normal', 'high', 'critical'];

export interface IClashTest {
	id: string;
	name?: string;
	a: ClashSet[];
	b: ClashSet[];
	kind?: 'hard' | 'clearance';
	clearance?: number;
	tolerance?: number;
	ignoreSameModel?: boolean;
	enabled?: boolean;
	[key: string]: unknown;
}

export interface IIssueComment {
	guid?: string;
	date?: string;
	author?: string;
	text?: string;
}

export interface IIssue {
	id: string;
	guid?: string;
	title?: string;
	source?: 'clash' | 'ids' | 'bcf' | 'manual';
	key?: string;
	test?: string;
	status?: IssueStatus;
	priority?: IssuePriority;
	assignedTo?: string;
	dueDate?: string;
	description?: string;
	elements?: string[];
	point?: number[];
	story?: string;
	created?: string;
	modified?: string;
	comments?: IIssueComment[];
	[key: string]: unknown;
}

export interface ICoordination {
	models: { path: string; name?: string; visible?: boolean; [key: string]: unknown }[];
	tests: IClashTest[];
	idsFiles: string[];
	issues: IIssue[];
	author?: string;
	[key: string]: unknown;
}

/** What the backend answers the coordination commands with (only what the editor reads). */
export interface ICoordinationAnswer {
	readonly coordination: ICoordination | undefined;
	readonly counts: { readonly [key: string]: number };
	readonly notes: readonly string[];
	readonly tests: readonly { readonly test: string; readonly name: string; readonly found: number; readonly coordinated: number }[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list<T>(value: unknown): T[] {
	return Array.isArray(value) ? value.filter(isRecord) as unknown as T[] : [];
}

/** The coordination of a parsed value (the file's or the backend's), its lists made safe. */
export function readCoordination(value: unknown): ICoordination | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const coordination = value as ICoordination;
	coordination.models = list(value.models);
	coordination.tests = list<IClashTest>(value.tests).map(t => ({ ...t, a: Array.isArray(t.a) ? t.a : [], b: Array.isArray(t.b) ? t.b : [] }));
	coordination.idsFiles = Array.isArray(value.idsFiles) ? value.idsFiles.filter((p): p is string => typeof p === 'string') : [];
	coordination.issues = list<IIssue>(value.issues);
	return coordination;
}

export function readCoordinationAnswer(value: unknown): ICoordinationAnswer | undefined {
	if (!isRecord(value)) {
		return undefined;
	}
	const counts: { [key: string]: number } = {};
	if (isRecord(value.counts)) {
		for (const [key, n] of Object.entries(value.counts)) {
			if (typeof n === 'number') {
				counts[key] = n;
			}
		}
	}
	return {
		coordination: readCoordination(value.coordination),
		counts,
		notes: Array.isArray(value.notes) ? value.notes.map(String) : [],
		tests: list<{ test: string; name: string; found: number; coordinated: number }>(value.tests),
	};
}

/** The tests a new coordination starts with (the same as the backend's default_tests). */
export function defaultTests(): IClashTest[] {
	const services: ClashSet[] = ['mechanical', 'plumbing', 'fire', 'electrical'];
	return [
		{ id: 'T1', name: 'Structure vs services', a: ['structure'], b: [...services], kind: 'hard', tolerance: 2, enabled: true },
		{ id: 'T2', name: 'Architecture vs services', a: ['architecture'], b: [...services], kind: 'hard', tolerance: 2, enabled: true },
		{ id: 'T3', name: 'Services vs services', a: [...services], b: [...services], kind: 'hard', tolerance: 2, ignoreSameModel: true, enabled: true },
		{ id: 'T4', name: 'Structure vs architecture', a: ['structure'], b: ['architecture'], kind: 'hard', tolerance: 2, enabled: true },
		{ id: 'T5', name: 'Other models vs structure', a: ['external'], b: ['structure'], kind: 'hard', tolerance: 2, enabled: true },
	];
}

export function coordinationOf(document: IMep): ICoordination | undefined {
	return readCoordination(document.coordination);
}

export function ensureCoordination(document: IMep): ICoordination {
	const existing = coordinationOf(document);
	if (existing) {
		document.coordination = existing;
		return existing;
	}
	const created: ICoordination = { models: [], tests: defaultTests(), idsFiles: [], issues: [] };
	document.coordination = created;
	return created;
}

export function isOpenIssue(issue: IIssue): boolean {
	return issue.status === undefined || issue.status === 'new' || issue.status === 'active' || issue.status === 'reviewed';
}

export function clashSetLabel(set: ClashSet): string {
	switch (set) {
		case 'structure': return localize('coord.set.structure', "Structure");
		case 'architecture': return localize('coord.set.architecture', "Architecture");
		case 'mechanical': return localize('coord.set.mechanical', "Mechanical");
		case 'plumbing': return localize('coord.set.plumbing', "Plumbing");
		case 'fire': return localize('coord.set.fire', "Fire");
		case 'electrical': return localize('coord.set.electrical', "Electrical");
		case 'external': return localize('coord.set.external', "Other models");
	}
}

export function issueStatusLabel(status: IssueStatus): string {
	switch (status) {
		case 'new': return localize('coord.status.new', "New");
		case 'active': return localize('coord.status.active', "Active");
		case 'reviewed': return localize('coord.status.reviewed', "Reviewed");
		case 'approved': return localize('coord.status.approved', "Approved");
		case 'resolved': return localize('coord.status.resolved', "Resolved");
		case 'closed': return localize('coord.status.closed', "Closed");
	}
}

function priorityLabel(priority: IssuePriority): string {
	switch (priority) {
		case 'low': return localize('coord.priority.low', "Low");
		case 'normal': return localize('coord.priority.normal', "Normal");
		case 'high': return localize('coord.priority.high', "High");
		case 'critical': return localize('coord.priority.critical', "Critical");
	}
}

function sourceLabel(issue: IIssue): string {
	switch (issue.source) {
		case 'ids': return localize('coord.source.ids', "IDS");
		case 'bcf': return localize('coord.source.bcf', "BCF");
		case 'manual': return localize('coord.source.manual', "Manual");
		default: return issue.test ? localize('coord.source.test', "Clash {0}", issue.test) : localize('coord.source.clash', "Clash");
	}
}

const FIELDS = {
	id: { key: 'id', label: localize('coord.f.id', "ID"), kind: 'text', required: true, width: 52 },
	name: { key: 'name', label: localize('coord.f.name', "Name"), kind: 'text', width: 170 },
	clearance: { key: 'clearance', label: localize('coord.f.clearance', "Clearance"), unit: UNIT_MM, kind: 'number', min: 0, title: localize('coord.f.clearanceTitle', "Least gap for a clearance test"), width: 72 },
	tolerance: { key: 'tolerance', label: localize('coord.f.tolerance', "Tolerance"), unit: UNIT_MM, kind: 'number', min: 0, title: localize('coord.f.toleranceTitle', "Least overlap reported as a hard clash"), width: 72 },
	path: { key: 'path', label: localize('coord.f.path', "File"), kind: 'text', width: 300 },
	assignedTo: { key: 'assignedTo', label: localize('coord.f.assigned', "Assigned to"), kind: 'text', width: 120 },
	dueDate: { key: 'dueDate', label: localize('coord.f.due', "Due"), kind: 'text', width: 90 },
	comment: { key: 'comment', label: localize('coord.f.comment', "Add comment"), kind: 'text', width: 200 },
	author: { key: 'author', label: localize('coord.f.author', "Author"), kind: 'text', width: 160 },
} satisfies { [key: string]: IFieldSpec };

/** What the coordination's tables run in the editor. */
export interface ICoordinationActions {
	runTests(): void;
	importBcf(): void;
	exportBcf(): void;
	checkIds(): void;
	addModel(): void;
	addIdsFile(): void;
	/** Renders the view again (a change that is not in the file, such as the issue filter). */
	rerender(): void;
	readonly busy: (kind: 'tests' | 'bcf' | 'ids') => boolean;
}

/** Which issues the table shows (kept by the editor across renders). */
export interface ICoordinationViewState {
	filter: 'open' | 'all';
}

function now(): string {
	return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function touch(issue: IIssue): void {
	issue.modified = now();
}

/** The coordination sections of 07 MEP's Data view (Coordination). */
export function renderCoordinationData(host: IMepFormHost, actions: ICoordinationActions, state: ICoordinationViewState, disposables: DisposableStore): void {
	const document = host.document;
	const existing = coordinationOf(document);
	const ensure = () => ensureCoordination(document);
	const tests = existing?.tests ?? defaultTests();

	// ── the clash tests ──
	const testSection = host.section(localize('coord.tests', "Clash tests"), tests.length, {
		label: localize('coord.addTest', "Add Test"),
		run: () => {
			const coordination = ensure();
			let n = coordination.tests.length + 1;
			while (coordination.tests.some(t => t.id === `T${n}`)) {
				n++;
			}
			coordination.tests.push({ id: `T${n}`, name: '', a: ['structure'], b: ['mechanical', 'plumbing', 'fire', 'electrical'], kind: 'hard', tolerance: 2, enabled: true });
			host.changed(true);
		},
	});
	const buttons = append(testSection, $('.coord-actions'));
	const button = (label: string, title: string, busy: boolean, run: () => void) => {
		const element = append(buttons, $<HTMLButtonElement>('button.mep-add', { type: 'button', title }));
		append(element, $('span', undefined, busy ? localize('coord.working', "{0}…", label) : label));
		element.disabled = busy;
		disposables.add(addDisposableListener(element, EventType.CLICK, () => run()));
	};
	button(localize('coord.run', "Run Clash Tests"), localize('coord.runTitle', "Runs the enabled tests and updates the issues: new clashes are added, the status of known ones is kept, those no longer found are resolved."), actions.busy('tests'), () => actions.runTests());
	button(localize('coord.ids', "Check IDS"), localize('coord.idsTitle', "Checks every model against the IDS files below; failing specifications become issues."), actions.busy('ids'), () => actions.checkIds());
	button(localize('coord.importBcf', "Import BCF"), localize('coord.importBcfTitle', "Reads a BCF 2.1 or 3.0 file: known topics update their issues, the others are added."), actions.busy('bcf'), () => actions.importBcf());
	button(localize('coord.exportBcf', "Export BCF"), localize('coord.exportBcfTitle', "Writes the issues to a BCF 3.0 file with a viewpoint each (the two elements selected, a camera on the clash)."), actions.busy('bcf'), () => actions.exportBcf());
	if (!existing) {
		append(testSection, $('p.mep-note', undefined, localize('coord.defaultTests', "The default tests are shown; editing one or running them stores the coordination in mep.json.")));
	}
	const table = append(append(testSection, $('.mep-table-scroll')), $('table.mep-table'));
	const columns = [
		{ label: FIELDS.id.label, width: 52 }, { label: FIELDS.name.label, width: 170 },
		{ label: localize('coord.f.a', "Set A"), width: 230 }, { label: localize('coord.f.b', "Set B"), width: 230 },
		{ label: localize('coord.f.kind', "Kind"), width: 96 }, { label: FIELDS.clearance.label, unit: UNIT_MM, numeric: true, width: 72 },
		{ label: FIELDS.tolerance.label, unit: UNIT_MM, numeric: true, width: 72 },
		{ label: localize('coord.f.sameModel', "Skip same model"), width: 70, title: localize('coord.f.sameModelTitle', "Skip pairs from the same IFC model (a model's own fittings touch)") },
		{ label: localize('coord.f.enabled', "Run"), width: 44 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	tests.forEach((test, index) => {
		const row = append(body, $('tr'));
		const key = (field: string) => `coordination.tests.${index}.${field}`;
		const edit = () => ensure().tests[index];
		append(append(row, $('td')), host.textInput(FIELDS.id, test.id, value => host.setField(edit(), 'id', value), key('id')));
		append(append(row, $('td')), host.textInput(FIELDS.name, test.name ?? '', value => host.setField(edit(), 'name', value), key('name')));
		for (const side of ['a', 'b'] as const) {
			const cell = append(row, $('td.coord-sets'));
			for (const set of CLASH_SETS) {
				const label = append(cell, $('label.coord-set'));
				append(label, host.checkbox(test[side].includes(set), checked => {
					const target = edit();
					const sets = new Set(target[side]);
					if (checked) {
						sets.add(set);
					} else {
						sets.delete(set);
					}
					target[side] = CLASH_SETS.filter(s => sets.has(s));
					host.changed(true);
				}, localize('coord.setAria', "{0} in set {1} of {2}", clashSetLabel(set), side.toUpperCase(), test.id)));
				append(label, $('span', undefined, clashSetLabel(set)));
			}
		}
		append(append(row, $('td')), host.selectInput([
			{ value: 'hard', label: localize('coord.kind.hard', "Hard") },
			{ value: 'clearance', label: localize('coord.kind.clearance', "Clearance") },
		], test.kind ?? 'hard', value => {
			edit().kind = value === 'clearance' ? 'clearance' : 'hard';
			host.changed(true);
		}, key('kind'), localize('coord.f.kind', "Kind")));
		append(append(row, $('td')), host.textInput(FIELDS.clearance, test.clearance ?? 0, value => host.setField(edit(), 'clearance', value), key('clearance')));
		append(append(row, $('td')), host.textInput(FIELDS.tolerance, test.tolerance ?? 2, value => host.setField(edit(), 'tolerance', value), key('tolerance')));
		append(append(row, $('td.mep-check-cell')), host.checkbox(!!test.ignoreSameModel, value => {
			edit().ignoreSameModel = value;
			host.changed(true);
		}, localize('coord.f.sameModelAria', "Skip pairs within one model in {0}", test.id)));
		append(append(row, $('td.mep-check-cell')), host.checkbox(test.enabled !== false, value => {
			edit().enabled = value;
			host.changed(true);
		}, localize('coord.f.enabledAria', "Run {0}", test.id)));
		host.removeButton(row, () => {
			ensure().tests.splice(index, 1);
			host.changed(true);
		});
	});

	// ── the other IFC models and the IDS files ──
	const coordination = existing;
	const models = coordination?.models ?? [];
	const modelSection = host.section(localize('coord.models', "Other IFC models"), models.length, { label: localize('coord.addModel', "Add Model"), run: () => actions.addModel() });
	const modelTable = append(append(modelSection, $('.mep-table-scroll')), $('table.mep-table'));
	host.tableHead(modelTable, [{ label: FIELDS.path.label, width: 300 }, { label: FIELDS.name.label, width: 170 }, { label: '', width: 28 }]);
	const modelBody = append(modelTable, $('tbody'));
	models.forEach((model, index) => {
		const row = append(modelBody, $('tr'));
		append(append(row, $('td')), host.textInput(FIELDS.path, model.path, value => host.setField(ensure().models[index], 'path', value), `coordination.models.${index}.path`));
		append(append(row, $('td')), host.textInput(FIELDS.name, model.name ?? '', value => host.setField(ensure().models[index], 'name', value), `coordination.models.${index}.name`));
		host.removeButton(row, () => {
			ensure().models.splice(index, 1);
			host.changed(true);
		});
	});
	if (!models.length) {
		append(append(modelBody, $('tr')), $('td.mep-muted', { colspan: '3' }, localize('coord.noModels', "None yet. Add an architect's or another consultant's IFC model to test it as \"Other models\".")));
	}

	const idsFiles = coordination?.idsFiles ?? [];
	const idsSection = host.section(localize('coord.idsFiles', "IDS files"), idsFiles.length, { label: localize('coord.addIds', "Add IDS File"), run: () => actions.addIdsFile() });
	const idsTable = append(append(idsSection, $('.mep-table-scroll')), $('table.mep-table'));
	host.tableHead(idsTable, [{ label: FIELDS.path.label, width: 300 }, { label: '', width: 28 }]);
	const idsBody = append(idsTable, $('tbody'));
	idsFiles.forEach((path, index) => {
		const row = append(idsBody, $('tr'));
		append(append(row, $('td')), host.textInput(FIELDS.path, path, value => {
			if (typeof value === 'string' && value) {
				ensure().idsFiles[index] = value;
				host.changed(false);
			}
		}, `coordination.idsFiles.${index}`));
		host.removeButton(row, () => {
			ensure().idsFiles.splice(index, 1);
			host.changed(true);
		});
	});
	if (!idsFiles.length) {
		append(append(idsBody, $('tr')), $('td.mep-muted', { colspan: '2' }, localize('coord.noIds', "None yet. Add the IDS (Information Delivery Specification) files the models must meet.")));
	}

	// ── the issues ──
	const issues = coordination?.issues ?? [];
	const open = issues.filter(isOpenIssue);
	const issueSection = host.section(localize('coord.issues', "Issues"), issues.length);
	const bar = append(issueSection, $('.coord-actions'));
	append(bar, $('span.mep-note', undefined, localize('coord.issueCounts', "{0} open, {1} approved, resolved or closed.", open.length, issues.length - open.length)));
	append(bar, host.selectInput([
		{ value: 'open', label: localize('coord.filterOpen', "Show open issues") },
		{ value: 'all', label: localize('coord.filterAll', "Show all issues") },
	], state.filter, value => {
		state.filter = value === 'all' ? 'all' : 'open';
		actions.rerender();
	}, 'coordination.filter', localize('coord.filter', "Issues shown")));
	const authorLabel = append(bar, $('label.coord-author'));
	append(authorLabel, $('span', undefined, FIELDS.author.label));
	append(authorLabel, host.textInput(FIELDS.author, coordination?.author ?? '', value => host.setField(ensure(), 'author', value), 'coordination.author', localize('coord.authorPlaceholder', "Your name (BCF)")));
	const issueTable = append(append(issueSection, $('.mep-table-scroll')), $('table.mep-table'));
	host.tableHead(issueTable, [
		{ label: FIELDS.id.label, width: 52 }, { label: localize('coord.f.status', "Status"), width: 110 }, { label: localize('coord.f.priority', "Priority"), width: 90 },
		{ label: localize('coord.f.title', "Title"), width: 260 }, { label: localize('coord.f.source', "Source"), width: 80 }, { label: localize('coord.f.story', "Story"), width: 90 },
		{ label: FIELDS.assignedTo.label, width: 120 }, { label: FIELDS.dueDate.label, width: 90 },
		{ label: localize('coord.f.lastComment', "Last comment"), width: 220 }, { label: FIELDS.comment.label, width: 200 },
	]);
	const issueBody = append(issueTable, $('tbody'));
	const shown = issues.map((issue, index) => ({ issue, index })).filter(({ issue }) => state.filter === 'all' || isOpenIssue(issue));
	for (const { issue, index } of shown) {
		const row = append(issueBody, $(`tr${isOpenIssue(issue) ? '' : '.mep-muted'}`));
		const key = (field: string) => `coordination.issues.${index}.${field}`;
		const edit = () => ensure().issues[index];
		append(row, $('td', undefined, issue.id));
		append(append(row, $('td')), host.selectInput(ISSUE_STATUSES.map(s => ({ value: s, label: issueStatusLabel(s) })), issue.status ?? 'new', value => {
			const target = edit();
			const status = ISSUE_STATUSES.find(s => s === value) ?? 'new';
			if (target.status !== status) {
				target.comments = [...(target.comments ?? []), { date: now(), author: ensure().author ?? '', text: localize('coord.statusChanged', "Status: {0} -> {1}", issueStatusLabel(target.status ?? 'new'), issueStatusLabel(status)) }];
				target.status = status;
				touch(target);
				host.changed(true);
			}
		}, key('status'), localize('coord.f.status', "Status")));
		append(append(row, $('td')), host.selectInput(ISSUE_PRIORITIES.map(p => ({ value: p, label: priorityLabel(p) })), issue.priority ?? 'normal', value => {
			const target = edit();
			target.priority = ISSUE_PRIORITIES.find(p => p === value) ?? 'normal';
			touch(target);
			host.changed(true);
		}, key('priority'), localize('coord.f.priority', "Priority")));
		const title = append(row, $('td.mep-wrap', { title: issue.description ?? '' }, issue.title ?? ''));
		title.title = [issue.description, issue.elements?.length ? localize('coord.elements', "Elements: {0}", issue.elements.join(', ')) : ''].filter(Boolean).join('\n');
		append(row, $('td', undefined, sourceLabel(issue)));
		append(row, $('td', undefined, host.storyName(issue.story)));
		append(append(row, $('td')), host.textInput(FIELDS.assignedTo, issue.assignedTo ?? '', value => {
			host.setField(edit(), 'assignedTo', value);
			touch(edit());
		}, key('assignedTo')));
		append(append(row, $('td')), host.textInput(FIELDS.dueDate, issue.dueDate ?? '', value => host.setField(edit(), 'dueDate', value), key('dueDate'), localize('coord.duePlaceholder', "YYYY-MM-DD")));
		const last = issue.comments?.[issue.comments.length - 1];
		append(row, $('td.mep-wrap', { title: (issue.comments ?? []).map(c => `${c.date ?? ''} ${c.author ?? ''}: ${c.text ?? ''}`).join('\n') }, last ? `${last.author ? `${last.author}: ` : ''}${last.text ?? ''}` : ''));
		const comment = append(append(row, $('td')), $<HTMLInputElement>('input.mep-input', { type: 'text', spellcheck: 'true', 'aria-label': localize('coord.commentAria', "Add a comment to {0} (Enter)", issue.id), placeholder: localize('coord.commentPlaceholder', "Comment, then Enter") }));
		disposables.add(addDisposableListener(comment, EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key !== 'Enter' || !comment.value.trim()) {
				return;
			}
			const target = edit();
			target.comments = [...(target.comments ?? []), { date: now(), author: ensure().author ?? '', text: comment.value.trim() }];
			touch(target);
			host.changed(true);
		}));
	}
	if (!shown.length) {
		append(append(issueBody, $('tr')), $('td.mep-muted', { colspan: '10' }, issues.length
			? localize('coord.noOpenIssues', "No open issues.")
			: localize('coord.noIssues', "None yet. Run the clash tests, check the IDS files or import a BCF file.")));
	}
}
