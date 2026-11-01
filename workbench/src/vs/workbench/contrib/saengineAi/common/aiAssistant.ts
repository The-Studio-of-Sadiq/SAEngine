/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../../base/common/cancellation.js';
import { CancellationError } from '../../../../base/common/errors.js';
import { AiTurn, IAiToolCall, IAiToolResult, IProviderAnswer } from './aiProviders.js';
import { OptionalScope } from './aiTools.js';

/*
 * The built-in AI assistant (round T49): one conversation per window with the provider the
 * engineer configured, using the same tools as MCP clients (aiTools.ts) through the same runner,
 * so there is one assistant with two doors. The loop is here, without I/O, so it is unit tested;
 * the window's service sends the requests (through the shared process) and runs the tools.
 */

export const ASSISTANT_CONTAINER_ID = 'workbench.view.saengine.aiAssistant';
export const ASSISTANT_VIEW_ID = 'saengine.aiAssistant';

/** Application storage: the context scopes the engineer lets the assistant read. */
export const SCOPES_STORAGE_KEY = 'saengine.ai.assistant.scopes';
/** Application storage: the provider addresses the engineer agreed to send to every time. */
export const CONSENT_STORAGE_KEY = 'saengine.ai.assistant.consent';

/** Most model requests for one question (each tool round is one). */
export const MAX_STEPS = 12;
/** Longest tool result sent back [characters]: a whole results file would fill the context. */
export const MAX_TOOL_RESULT = 60_000;

/** What the assistant is told. English: it answers in the engineer's language. */
export function systemPrompt(scopes: ReadonlySet<OptionalScope>): string {
	const lines = [
		'You are the AI assistant built into SAEngine, a structural engineering desktop application for buildings designed to the Bangladesh National Building Code 2020 (BNBC 2020): soil report, project settings, materials, object types, floor plan, building model, MEP, FEM analysis and design, substructure, bill of quantities, drawings.',
		'You help a practising structural engineer. Be precise and brief; use SI units as SAEngine does (mm, m, kN, kN·m, MPa, kPa). Answer in the language the engineer writes in (English or Bangla).',
		'Design code questions: call search_code and answer ONLY from the passages it returns, citing each value with the clause, table and page the passage gives (e.g. "BNBC 2020 Part 6 Table 6.2.14 (p. 615)"). If search_code finds nothing that answers the question, say plainly that it is not in the code pack and do not answer from memory. Never invent or guess a clause number. Passages from the SAEngine manual explain how SAEngine applies the code; say so when you quote them.',
		'Results: to explain why a member fails or what governs, call explain_results (and read_results for summaries). Quote the governing check, its demand, capacity, utilisation and load combination. If the results are stale, say the project changed since the last run. Never call a design adequate without the design results.',
		'Changes to the model: never claim a change is made. Read the file first, then call propose_changes with one change set; the engineer previews every value before and after and accepts or rejects it. Report the outcome the tool returns. For a whole new building, call propose_building: it fills the New Building wizard, where the engineer checks and generates it.',
		'Opening a part, a file or revealing a member (open_part, open_file, reveal_element) helps the engineer follow you.',
	];
	const off: string[] = [];
	if (!scopes.has('project')) {
		off.push('the project overview');
	}
	if (!scopes.has('document')) {
		off.push('the open document');
	}
	if (!scopes.has('results')) {
		off.push('the results');
	}
	if (off.length) {
		lines.push(`The engineer has not allowed you to read ${off.join(', ')}; if a question needs it, say which switch in the AI Assistant view to turn on.`);
	}
	return lines.join('\n\n');
}

/** What happened in the loop, for the view. */
export type AssistantEvent =
	| { readonly kind: 'answer'; readonly text: string }
	| { readonly kind: 'toolCall'; readonly call: IAiToolCall }
	| { readonly kind: 'toolResult'; readonly result: IAiToolResult }
	| { readonly kind: 'stopped'; readonly reason: 'maxTokens' | 'refusal' | 'steps' };

export interface IAssistantLoop {
	/** One model request with the conversation so far. */
	send(turns: readonly AiTurn[], token: CancellationToken): Promise<IProviderAnswer>;
	/** Runs one tool call (unknown tools and refused scopes answer with an error result). */
	runTool(call: IAiToolCall, token: CancellationToken): Promise<IAiToolResult>;
	onEvent(event: AssistantEvent): void;
}

/**
 * Answers the last user turn: asks the model, runs the tools it calls, sends their results back,
 * until it answers without tools (or MAX_STEPS). Returns the turns to append (assistant and
 * tool turns, in order); `turns` itself is not changed, so a failed request leaves the
 * conversation as it was.
 */
export async function runAssistant(turns: readonly AiTurn[], loop: IAssistantLoop, token: CancellationToken): Promise<AiTurn[]> {
	const added: AiTurn[] = [];
	for (let step = 0; step < MAX_STEPS; step++) {
		if (token.isCancellationRequested) {
			throw new CancellationError();
		}
		const answer = await loop.send([...turns, ...added], token);
		added.push(answer.turn);
		if (answer.text) {
			loop.onEvent({ kind: 'answer', text: answer.text });
		}
		if (answer.stop === 'refusal' || answer.stop === 'maxTokens') {
			loop.onEvent({ kind: 'stopped', reason: answer.stop });
			return added;
		}
		if (!answer.toolCalls.length) {
			return added;
		}
		const results: IAiToolResult[] = [];
		for (const call of answer.toolCalls) {
			if (token.isCancellationRequested) {
				throw new CancellationError();
			}
			loop.onEvent({ kind: 'toolCall', call });
			const result = await loop.runTool(call, token);
			const text = result.text.length > MAX_TOOL_RESULT ? `${result.text.slice(0, MAX_TOOL_RESULT)}\n[cut: the result was longer]` : result.text;
			const kept = { ...result, text };
			results.push(kept);
			loop.onEvent({ kind: 'toolResult', result: kept });
		}
		// Every result of one answer in one turn.
		added.push({ role: 'tools', results });
	}
	loop.onEvent({ kind: 'stopped', reason: 'steps' });
	return added;
}

/** The scopes as stored (unknown names dropped); default: the project overview and the results. */
export function readScopes(raw: string | undefined): Set<OptionalScope> {
	const all: readonly OptionalScope[] = ['project', 'document', 'results'];
	if (!raw) {
		return new Set<OptionalScope>(['project', 'results']);
	}
	try {
		const value = JSON.parse(raw);
		return new Set(Array.isArray(value) ? all.filter(scope => value.includes(scope)) : []);
	} catch {
		return new Set<OptionalScope>(['project', 'results']);
	}
}

/** Consent is per provider and address: "anthropic|api.anthropic.com". */
export function consentKey(provider: string, host: string): string {
	return `${provider}|${host.toLowerCase()}`;
}
