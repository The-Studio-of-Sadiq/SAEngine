/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { timeout } from '../../../../base/common/async.js';
import { MCP } from '../../../../platform/mcp/common/modelContextProtocol.js';
import { ActionKind, describeFailure, IActionResult, IActionStep, IBatchResult, ISaengineActionsService, readSteps, stepNames } from '../../../services/saengineProject/common/saengineActions.js';
import { ChangeSetSource, IAiChangeSet, ISaengineAiChangeSetService } from './aiChangeSets.js';

/*
 * The AI's tools on the shared editing actions (list_actions, describe_action, run_actions), for
 * the built-in assistant and MCP clients alike. Edits come back as ONE change set per batch that
 * the engineer previews and accepts or rejects (nothing changes before); a batch with run steps
 * (Run All, design, exports, creating the project) runs only after the engineer agrees, and saves
 * the project first. A failed batch changes nothing and its guardrail problems go back to the
 * model word for word, so it can correct the values.
 */

/** How long run_actions waits for the engineer's decision on a change set before answering "pending" [ms]. */
export const ACTIONS_DECISION_WAIT = 5 * 60 * 1000;

/** What the window asks the engineer: run these steps (saving the project first)? */
export type ConfirmRun = (steps: readonly IActionStep[], source: ChangeSetSource) => Promise<boolean>;

export class AiActionTools {

	constructor(
		private readonly confirmRun: ConfirmRun,
		/** Shows the change set to the engineer (the AI Assistant view). */
		private readonly showChangeSet: (changeSet: IAiChangeSet) => Promise<void>,
		private readonly decisionWait: number,
		@ISaengineActionsService private readonly actions: ISaengineActionsService,
		@ISaengineAiChangeSetService private readonly changeSets: ISaengineAiChangeSetService,
	) { }

	async listActions(kind: ActionKind | undefined): Promise<MCP.CallToolResult> {
		const infos = await this.actions.listActions(kind);
		return jsonResult({
			actions: infos.map(info => ({ name: info.name, kind: info.kind, summary: info.summary })),
			note: 'Call describe_action for the parameters of an action; run_actions runs a batch of them.',
		});
	}

	async describeAction(name: string): Promise<MCP.CallToolResult> {
		const info = await this.actions.describe(name);
		if (!info) {
			const names = (await this.actions.listActions()).map(i => i.name);
			return errorResult(`No action "${name}". The actions: ${names.join(', ')}.`);
		}
		return jsonResult({ name: info.name, kind: info.kind, summary: info.summary, parts: info.parts, params: info.paramsSchema });
	}

	async runActions(args: { readonly [key: string]: unknown }, source: ChangeSetSource): Promise<MCP.CallToolResult> {
		let steps: IActionStep[];
		try {
			steps = readSteps(args.steps);
		} catch (error) {
			return errorResult(`The batch is not valid: ${error instanceof Error ? error.message : String(error)}.`);
		}
		const title = typeof args.title === 'string' && args.title.trim() ? args.title.trim().slice(0, 200) : stepNames(steps);
		const catalogue = await this.actions.listActions();
		const unknown = steps.filter(step => !catalogue.some(info => info.name === step.action)).map(step => step.action);
		if (unknown.length) {
			return errorResult(`Unknown action(s): ${unknown.join(', ')}. Call list_actions for the catalogue.`);
		}
		const kinds = steps.map(step => catalogue.find(info => info.name === step.action)!.kind);
		if (await this.actions.needsWrite(steps)) {
			return this.runWritten(steps, kinds, source);
		}
		const outcome = await this.actions.run(steps, { apply: false });
		if (!outcome.ok) {
			return failed(steps, outcome);
		}
		const results = outcome.results.map(compact);
		if (!Object.keys(outcome.changes).length) {
			return jsonResult({ ok: true, changed: false, results });
		}
		let changeSet: IAiChangeSet;
		try {
			changeSet = await this.changeSets.proposeTexts({ title, texts: outcome.changes, summary: outcome.results.map(r => r.message).filter(m => !!m) }, source);
		} catch (error) {
			return errorResult(`The change set could not be shown: ${error instanceof Error ? error.message : String(error)}`);
		}
		await this.showChangeSet(changeSet);
		const wait = timeout(this.decisionWait);
		const decision = await Promise.race([changeSet.decision, wait.then(() => 'pending' as const, () => 'pending' as const)]);
		wait.cancel();
		switch (decision) {
			case 'accepted':
				return jsonResult({ ok: true, decision: 'accepted', note: `The engineer accepted "${title}": applied as one undoable step, unsaved until saved.`, files: Object.keys(outcome.changes), results });
			case 'rejected':
				return jsonResult({ ok: false, decision: 'rejected', note: `The engineer rejected "${title}". Nothing changed; ask what to do differently.` });
			case 'pending':
				return jsonResult({ ok: true, decision: 'pending', note: `"${title}" waits for the engineer's decision in the AI Assistant view. Later batches are worked out on the project without it until it is accepted.`, results });
			default:
				return errorResult(`The change set was not applied (${decision}): ${changeSet.problem ?? ''}`);
		}
	}

	/** Run steps (and creating a project): the engineer agrees, the project is saved, the engine writes. */
	private async runWritten(steps: readonly IActionStep[], kinds: readonly ActionKind[], source: ChangeSetSource): Promise<MCP.CallToolResult> {
		const edits = steps.filter((step, index) => kinds[index] === 'edit' && step.action !== 'project.create').map(step => step.action);
		if (edits.length) {
			return errorResult(`A batch with run steps (${stepNames(steps.filter((_, i) => kinds[i] === 'run'))}) or project.create holds only those and queries, because the engine writes it to disk. Send the edits (${edits.join(', ')}) as a batch of their own first: the engineer reviews them as a change set.`);
		}
		if (!await this.confirmRun(steps, source)) {
			return jsonResult({ ok: false, decision: 'declined', note: `The engineer did not run ${stepNames(steps)}. Nothing changed.` });
		}
		const outcome = await this.actions.run(steps, { apply: true });
		if (!outcome.ok) {
			return failed(steps, outcome);
		}
		return jsonResult({ ok: true, files: Object.keys(outcome.changes), results: outcome.results.map(compact), note: 'Done and written to disk. The engineer checks the results; report them with their status, never as approved.' });
	}
}

/** A step's result for the model: no empty lists. */
function compact(result: IActionResult): object {
	return {
		ok: result.ok,
		message: result.message,
		...(result.created.length ? { created: result.created } : {}),
		...(result.warnings.length ? { warnings: result.warnings } : {}),
		...(result.problems.length ? { problems: result.problems } : {}),
		...(result.data !== undefined ? { data: result.data } : {}),
	};
}

/** A failed batch: nothing changed; the failing step and its problems word for word, so the model corrects them. */
function failed(steps: readonly IActionStep[], outcome: IBatchResult): MCP.CallToolResult {
	return {
		content: [{
			type: 'text',
			text: `Nothing was changed: the batch is all or nothing.\n${describeFailure(steps, outcome)}\n${JSON.stringify({ failedStep: outcome.failedStep, results: outcome.results.map(compact) }, undefined, 1)}`,
		}],
		isError: true,
	};
}

function jsonResult(value: unknown): MCP.CallToolResult {
	return { content: [{ type: 'text', text: JSON.stringify(value, undefined, 1) }] };
}

function errorResult(text: string): MCP.CallToolResult {
	return { content: [{ type: 'text', text }], isError: true };
}
