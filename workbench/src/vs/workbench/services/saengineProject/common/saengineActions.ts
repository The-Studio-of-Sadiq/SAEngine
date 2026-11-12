/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';

/*
 * The shared editing actions (`saengine.actions` in Python): one catalogue of typed, validated
 * edits, queries and runs that the command line, the SDK, the app and the AI all use. The engine
 * works out each batch on the part files (with the app's unsaved texts as overrides) and answers
 * with the new texts; the app applies them through the part files' text models, so the editors,
 * undo and live co-editing see them like the engineer's own typing. The contract with the engine
 * (`actions/list`, `actions/run`) is in docs/actions.md.
 */

/** Edits change part files; queries only read; runs need the files on disk (analysis, design, exports). */
export type ActionKind = 'edit' | 'run' | 'query';

/** One action of the catalogue (`actions/list`). */
export interface IActionInfo {
	readonly name: string;
	/** What it does, in the engineer's words. */
	readonly summary: string;
	readonly kind: ActionKind;
	/** The parts it reads or changes (part ids or files). */
	readonly parts: readonly string[];
	/** Its parameters (the pydantic model's JSON schema). */
	readonly paramsSchema: IJSONSchema;
}

/** One step of a batch. */
export interface IActionStep {
	readonly action: string;
	readonly params?: { readonly [key: string]: unknown };
}

/** Why a guardrail refused a value: the field, the value given and the reason. */
export interface IActionProblem {
	readonly field?: string;
	readonly value?: unknown;
	readonly reason: string;
}

/** What one step did. */
export interface IActionResult {
	readonly ok: boolean;
	/** In the engineer's words ("Placed 12 columns: C1-C12"). */
	readonly message: string;
	/** Ids the step created (C1, B1, S1, ...). */
	readonly created: readonly string[];
	readonly warnings: readonly string[];
	readonly problems: readonly IActionProblem[];
	/** A query's answer. */
	readonly data?: unknown;
}

/** What a batch did (`actions/run`): all its steps or none of them. */
export interface IBatchResult {
	readonly ok: boolean;
	readonly results: readonly IActionResult[];
	/** Part file (relative to the project, forward slashes) -> its new text, formatted as the project formats it. */
	readonly changes: { readonly [path: string]: string };
	/** The step that failed (0-based), when one did. */
	readonly failedStep: number | undefined;
}

export interface IActionsRunOptions {
	/**
	 * Apply the changes to the part files' text models (edits: one undo step, unsaved until the
	 * engineer saves; runs: the project is saved first and the engine writes the files). Without
	 * it the batch is worked out only (a preview): nothing changes.
	 */
	readonly apply: boolean;
}

/** A batch the window ran: the engine's answer and what the window did with it. */
export interface IActionsOutcome extends IBatchResult {
	/** Whether the batch had run steps (written by the engine, after saving the project). */
	readonly ran: boolean;
	/** The project files whose text models were changed (relative paths): edits applied, or files a run wrote and the window reloaded. */
	readonly applied: readonly string[];
}

export const ISaengineActionsService = createDecorator<ISaengineActionsService>('saengineActionsService');

export interface ISaengineActionsService {
	readonly _serviceBrand: undefined;
	/** The catalogue, optionally of one kind. */
	listActions(kind?: ActionKind): Promise<readonly IActionInfo[]>;
	/** One action of the catalogue, or undefined when there is none of that name. */
	describe(name: string): Promise<IActionInfo | undefined>;
	/**
	 * Runs a batch on the open project. Edits and queries are worked out by the engine on the
	 * texts as the engineer sees them (unsaved edits included) and, with `apply`, applied to the
	 * text models as one undo step. A batch with a run step (Run All, design, exports) saves the
	 * project and lets the engine write the files, then reloads them. All or nothing: a failed
	 * batch changes nothing.
	 */
	run(steps: readonly IActionStep[], options: IActionsRunOptions): Promise<IActionsOutcome>;
	/** Whether the batch needs the files on disk (a run step, or creating the project). */
	needsWrite(steps: readonly IActionStep[]): Promise<boolean>;
}

//#region Engine answers

/** Internal commands the desktop layer registers to reach the engine (`actions/list`, `actions/run`). */
export const ACTIONS_LIST_COMMAND = 'saengine.actions.backend.list';
export const ACTIONS_RUN_COMMAND = 'saengine.actions.backend.run';

/** What `actions/run` takes. */
export interface IActionsRunRequest {
	readonly projectRoot: string;
	readonly steps: readonly IActionStep[];
	readonly overrides?: { readonly [path: string]: string };
	readonly write?: boolean;
}

/** The action that creates a project: it writes a new project's files, so it runs like a run step. */
export const PROJECT_CREATE_ACTION = 'project.create';

/** Whether `step` needs the files on disk, by the catalogue. */
export function stepNeedsWrite(step: IActionStep, catalogue: readonly IActionInfo[]): boolean {
	return step.action === PROJECT_CREATE_ACTION || catalogue.find(info => info.name === step.action)?.kind === 'run';
}

type Bag = { readonly [key: string]: unknown };

function bag(value: unknown): Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Bag : {};
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.map(item => typeof item === 'string' ? item : JSON.stringify(item)) : [];
}

const KINDS: readonly ActionKind[] = ['edit', 'run', 'query'];

/** The catalogue as the engine sent it, read defensively (snake_case or camelCase keys). */
export function readCatalogue(raw: unknown): IActionInfo[] {
	const list = Array.isArray(raw) ? raw : bag(raw).actions;
	if (!Array.isArray(list)) {
		return [];
	}
	const infos: IActionInfo[] = [];
	for (const item of list) {
		const entry = bag(item);
		if (typeof entry.name !== 'string' || !entry.name) {
			continue;
		}
		const kind = KINDS.find(k => k === entry.kind) ?? 'edit';
		const schema = bag(entry.params_schema ?? entry.paramsSchema);
		infos.push({
			name: entry.name,
			summary: typeof entry.summary === 'string' ? entry.summary : '',
			kind,
			parts: strings(entry.parts),
			paramsSchema: schema as IJSONSchema,
		});
	}
	return infos;
}

/** One problem as the engine sent it (a Problem model, or a plain text). */
function readProblem(raw: unknown): IActionProblem {
	if (typeof raw === 'string') {
		return { reason: raw };
	}
	const entry = bag(raw);
	return {
		...(typeof entry.field === 'string' ? { field: entry.field } : {}),
		...(Object.prototype.hasOwnProperty.call(entry, 'value') ? { value: entry.value } : {}),
		reason: typeof entry.reason === 'string' ? entry.reason : typeof entry.message === 'string' ? entry.message : JSON.stringify(raw),
	};
}

export function readActionResult(raw: unknown): IActionResult {
	const entry = bag(raw);
	return {
		ok: entry.ok === true,
		message: typeof entry.message === 'string' ? entry.message : '',
		created: strings(entry.created),
		warnings: strings(entry.warnings),
		problems: Array.isArray(entry.problems) ? entry.problems.map(readProblem) : [],
		...(entry.data !== undefined && entry.data !== null ? { data: entry.data } : {}),
	};
}

/**
 * The engine's answer to `actions/run`, read defensively. A refusal of the backend
 * (`{ok: false, code, message, problems}`, e.g. no such project) becomes a failed batch with that
 * message as its one result.
 */
export function readBatchResult(raw: unknown): IBatchResult {
	const answer = bag(raw);
	const changes: { [path: string]: string } = {};
	for (const [path, text] of Object.entries(bag(answer.changes))) {
		if (typeof text === 'string') {
			changes[path.replace(/\\/g, '/')] = text;
		}
	}
	const failed = answer.failed_step ?? answer.failedStep;
	const results = Array.isArray(answer.results) ? answer.results.map(readActionResult) : [];
	if (!results.length && answer.ok !== true) {
		results.push({
			ok: false,
			message: typeof answer.message === 'string' ? answer.message : 'The engine refused the batch.',
			created: [],
			warnings: [],
			problems: Array.isArray(answer.problems) ? answer.problems.map(readProblem) : [],
		});
	}
	const ok = answer.ok === true;
	return {
		ok,
		results,
		// All or nothing: a failed batch changes nothing, whatever it sent.
		changes: ok ? changes : {},
		failedStep: typeof failed === 'number' ? failed : (ok ? undefined : Math.max(0, results.findIndex(r => !r.ok))),
	};
}

/** The steps of a batch file: a list of steps, or `{steps: [...]}`. Throws with the reason when it is not one. */
export function readSteps(raw: unknown): IActionStep[] {
	const list = Array.isArray(raw) ? raw : bag(raw).steps;
	if (!Array.isArray(list) || !list.length) {
		throw new Error('a batch is a non-empty list of steps ({"action": ..., "params": {...}}), or {"steps": [...]}');
	}
	return list.map((item, index) => {
		const step = bag(item);
		if (typeof step.action !== 'string' || !step.action.trim()) {
			throw new Error(`step ${index + 1} has no "action"`);
		}
		if (step.params !== undefined && (typeof step.params !== 'object' || step.params === null || Array.isArray(step.params))) {
			throw new Error(`step ${index + 1}: "params" must be an object`);
		}
		return { action: step.action.trim(), params: (step.params ?? {}) as Bag };
	});
}

//#endregion

//#region Text

/**
 * The one edit that turns `before` into `after`: the text between their common start and common
 * end. Applied as a single small edit, the rest of the document (its markers, the co-editing
 * peers' cursors) stays where it is.
 */
export function minimalEdit(before: string, after: string): { readonly start: number; readonly end: number; readonly text: string } | undefined {
	if (before === after) {
		return undefined;
	}
	const max = Math.min(before.length, after.length);
	let start = 0;
	while (start < max && before.charCodeAt(start) === after.charCodeAt(start)) {
		start++;
	}
	let end = 0;
	while (end < max - start && before.charCodeAt(before.length - 1 - end) === after.charCodeAt(after.length - 1 - end)) {
		end++;
	}
	// Never split a surrogate pair or a CRLF.
	while (start > 0 && (isLowSurrogate(before.charCodeAt(start)) || (before.charCodeAt(start) === 10 && before.charCodeAt(start - 1) === 13))) {
		start--;
	}
	while (end > 0 && (isLowSurrogate(before.charCodeAt(before.length - end)) || (before.charCodeAt(before.length - end) === 10 && before.charCodeAt(before.length - end - 1) === 13))) {
		end--;
	}
	return { start, end: before.length - end, text: after.slice(start, after.length - end) };
}

function isLowSurrogate(code: number): boolean {
	return code >= 0xDC00 && code <= 0xDFFF;
}

//#endregion

//#region For the engineer and the AI

/** The batch's step names, for a title: "grid.set, storeys.set and 3 more". */
export function stepNames(steps: readonly IActionStep[], max = 3): string {
	const names = steps.map(s => s.action);
	return names.length <= max ? names.join(', ') : `${names.slice(0, max).join(', ')} and ${names.length - max} more`;
}

/** A failed batch in a few lines: the step, its message and each problem (field, value, reason). */
export function describeFailure(steps: readonly IActionStep[], result: IBatchResult): string {
	const index = result.failedStep ?? result.results.findIndex(r => !r.ok);
	const failed = index >= 0 ? result.results[index] : undefined;
	const name = index >= 0 && index < steps.length ? steps[index].action : undefined;
	const lines = [name ? `Step ${index + 1} (${name}) failed: ${failed?.message ?? ''}`.trim() : (failed?.message ?? 'The batch failed.')];
	for (const problem of failed?.problems ?? []) {
		const value = problem.value !== undefined ? ` = ${JSON.stringify(problem.value)}` : '';
		lines.push(`- ${problem.field ? `${problem.field}${value}: ` : ''}${problem.reason}`);
	}
	return lines.join('\n');
}

//#endregion
