/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { timeout } from '../../../../base/common/async.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { MCP } from '../../../../platform/mcp/common/modelContextProtocol.js';
import { ActionKind, describeFailure, IActionInfo, IActionResult, IActionStep, IBatchResult, ISaengineActionsService, readSteps, stepNames } from '../../../services/saengineProject/common/saengineActions.js';
import { ChangeSetSource, IAiChangeSet, ISaengineAiChangeSetService } from './aiChangeSets.js';

/*
 * The AI's tools on the shared editing actions (list_actions, describe_action, run_actions), for
 * the chat's assistant and MCP clients alike. Edits come back as ONE change set per batch that
 * the engineer previews and accepts or rejects (nothing changes before); a batch whose steps write
 * to disk (`writes` in the catalogue: Run All, design, exports, creating the project) runs only
 * after the engineer agrees, saves the project first, and can be stopped (the caller's token). A
 * failed batch changes nothing and its guardrail problems go back to the
 * model word for word, so it can correct the values.
 */

/** How long run_actions waits for the engineer's decision on a change set before answering "pending" [ms]. */
export const ACTIONS_DECISION_WAIT = 5 * 60 * 1000;

/**
 * Where the engineer reviews what an assistant asks for: in the chat for the chat's assistant
 * (aiChatReview.ts), in dialogs for MCP clients (aiDialogReview.ts).
 */
export interface IAiReview {
	/** Shows the change set to accept or reject; resolves once shown (the decision is the set's). */
	showChangeSet(changeSet: IAiChangeSet): Promise<void>;
	/** Asks whether to save the project and run these steps. */
	confirmRun(steps: readonly IActionStep[], source: ChangeSetSource): Promise<boolean>;
}

export class AiActionTools {

	constructor(
		/** The review used when a call brings none of its own. */
		private readonly review: IAiReview,
		private readonly decisionWait: number,
		@ISaengineActionsService private readonly actions: ISaengineActionsService,
		@ISaengineAiChangeSetService private readonly changeSets: ISaengineAiChangeSetService,
	) { }

	async listActions(kind: ActionKind | undefined): Promise<MCP.CallToolResult> {
		const infos = await this.actions.listActions(kind);
		return jsonResult({
			actions: infos.map(info => ({ name: info.name, kind: info.kind, writes: info.writes, summary: info.summary })),
			note: 'Call describe_action for the parameters of an action; run_actions runs a batch of them.',
		});
	}

	async describeAction(name: string): Promise<MCP.CallToolResult> {
		const info = await this.actions.describe(name);
		if (!info) {
			const names = (await this.actions.listActions()).map(i => i.name);
			return errorResult(`No action "${name}". The actions: ${names.join(', ')}.`);
		}
		return jsonResult({ name: info.name, kind: info.kind, writes: info.writes, summary: info.summary, parts: info.parts, params: info.paramsSchema });
	}

	/** `token`: the engineer's Stop (the chat's, or the run's progress): a run stops before its next step. */
	async runActions(args: { readonly [key: string]: unknown }, source: ChangeSetSource, review: IAiReview = this.review, token: CancellationToken = CancellationToken.None): Promise<MCP.CallToolResult> {
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
		const infos = steps.map(step => catalogue.find(info => info.name === step.action)!);
		if (infos.some(info => info.writes)) {
			return this.runWritten(steps, infos, source, review, token);
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
		await review.showChangeSet(changeSet);
		const wait = timeout(this.decisionWait);
		const decision = await Promise.race([changeSet.decision, wait.then(() => 'pending' as const, () => 'pending' as const)]);
		wait.cancel();
		switch (decision) {
			case 'accepted':
				return jsonResult({ ok: true, decision: 'accepted', note: `The engineer accepted "${title}": applied as one undoable step, unsaved until saved.`, files: Object.keys(outcome.changes), results });
			case 'rejected':
				return jsonResult({ ok: false, decision: 'rejected', note: `The engineer rejected "${title}". Nothing changed; ask what to do differently.` });
			case 'pending':
				return jsonResult({ ok: true, decision: 'pending', note: `"${title}" waits for the engineer's decision (shown to them with Accept and Reject). Later batches are worked out on the project without it until it is accepted.`, results });
			default:
				return errorResult(`The change set was not applied (${decision}): ${changeSet.problem ?? ''}`);
		}
	}

	/** Steps that write to disk (runs, creating a project): the engineer agrees, the project is saved, the engine writes. */
	private async runWritten(steps: readonly IActionStep[], infos: readonly IActionInfo[], source: ChangeSetSource, review: IAiReview, token: CancellationToken): Promise<MCP.CallToolResult> {
		const edits = infos.filter(info => info.kind === 'edit' && !info.writes).map(info => info.name);
		if (edits.length) {
			return errorResult(`A batch with steps that write to disk (${stepNames(steps.filter((_, i) => infos[i].writes))}) holds only those and queries, because the engine writes it to disk. Send the edits (${edits.join(', ')}) as a batch of their own first: the engineer reviews them as a change set.`);
		}
		if (!await review.confirmRun(steps, source)) {
			return jsonResult({ ok: false, decision: 'declined', note: `The engineer did not run ${stepNames(steps)}. Nothing changed.` });
		}
		const outcome = await this.actions.run(steps, { apply: true }, token);
		if (!outcome.ok) {
			return failed(steps, outcome);
		}
		return jsonResult({
			ok: true,
			files: Object.keys(outcome.changes),
			written: outcome.written,
			...(outcome.createdIn ? { createdIn: outcome.createdIn, note: `The project was created in ${outcome.createdIn} and opens in this window now.` } : { note: 'Done and written to disk. The engineer checks the results; report them with their status, never as approved.' }),
			results: outcome.results.map(compact),
		});
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
		...(result.written.length ? { written: result.written } : {}),
	};
}

/**
 * A failed (or stopped) batch: the failing step and its problems word for word, so the model
 * corrects them, and what was written before it (it stays written: all or nothing per segment).
 */
function failed(steps: readonly IActionStep[], outcome: IBatchResult): MCP.CallToolResult {
	const head = outcome.cancelled
		? 'The engineer stopped the batch: the steps from the one named were not run.'
		: outcome.written.length ? 'The batch failed. The files saved before its run step stay written; nothing else changed.' : 'Nothing was changed: the batch is all or nothing.';
	return {
		content: [{
			type: 'text',
			text: `${head}\n${describeFailure(steps, outcome)}\n${JSON.stringify({ failedStep: outcome.failedStep, cancelled: outcome.cancelled, written: outcome.written, results: outcome.results.map(compact) }, undefined, 1)}`,
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
