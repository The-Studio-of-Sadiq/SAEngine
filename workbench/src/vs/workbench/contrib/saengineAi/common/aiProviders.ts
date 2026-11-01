/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IJSONSchema } from '../../../../base/common/jsonSchema.js';

/*
 * The model providers of the built-in AI assistant: the Anthropic Messages API (the default)
 * and any OpenAI-compatible chat completions endpoint (a self-hosted model). Pure request
 * building and answer parsing over plain JSON, so it is unit tested; the requests are sent by
 * the shared process (ISaengineAiHttpRequest). No SDK: the workbench cannot add dependencies in
 * a side round, and both APIs are a single POST.
 */

export type AiProviderId = 'anthropic' | 'openaiCompatible';
export type AiEffort = 'low' | 'medium' | 'high';

/** Settings (application scope only: a project's settings must not redirect what is sent). */
export const PROVIDER_SETTING = 'saengine.ai.assistant.provider';
export const ANTHROPIC_MODEL_SETTING = 'saengine.ai.assistant.anthropicModel';
export const EFFORT_SETTING = 'saengine.ai.assistant.effort';
export const OPENAI_ENDPOINT_SETTING = 'saengine.ai.assistant.endpoint';
export const OPENAI_MODEL_SETTING = 'saengine.ai.assistant.model';

/** The Claude models offered; any other id the engineer types is sent as it is. */
export const ANTHROPIC_MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'] as const;
export const DEFAULT_ANTHROPIC_MODEL = 'claude-opus-5-5';
export const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';
export const ANTHROPIC_VERSION = '2026-10-21';
/** Server-side fallback when a safety classifier declines (`fallbacks: "default"`). */
export const ANTHROPIC_FALLBACK_BETA = 'server-side-fallback-2026-07-01';
/** The models that accept `fallbacks: "default"` on the Anthropic API. */
const FALLBACK_MODELS: readonly string[] = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-opus-5', 'claude-fable-5-1'];
/** Room for one answer (not streamed). */
export const MAX_OUTPUT_TOKENS = 16000;

/** Secret storage keys of the API keys (the OS secret store; never settings or project files). */
export function secretKey(provider: AiProviderId): string {
	return `saengine.ai.assistant.key.${provider}`;
}

export interface IProviderConfig {
	readonly provider: AiProviderId;
	readonly model: string;
	/** OpenAI-compatible: the base URL, e.g. http://localhost:11434/v1. */
	readonly endpoint?: string;
	readonly effort: AiEffort;
	/** Self-hosted servers often need none. */
	readonly apiKey?: string;
}

/** Where `config` sends to, for the consent dialog and the indicator ("api.anthropic.com"). */
export function providerUrl(config: Pick<IProviderConfig, 'provider' | 'endpoint'>): string | undefined {
	if (config.provider === 'anthropic') {
		return ANTHROPIC_URL;
	}
	const base = config.endpoint?.trim();
	if (!base) {
		return undefined;
	}
	return /\/chat\/completions\/?$/.test(base) ? base : `${base.replace(/\/+$/, '')}/chat/completions`;
}

export function providerHost(config: Pick<IProviderConfig, 'provider' | 'endpoint'>): string | undefined {
	const url = providerUrl(config);
	try {
		return url ? new URL(url).host : undefined;
	} catch {
		return undefined;
	}
}

//#region The conversation, provider-neutral

export interface IAiToolCall {
	readonly id: string;
	readonly name: string;
	readonly args: Record<string, unknown>;
}

export interface IAiToolResult {
	readonly id: string;
	readonly name: string;
	readonly text: string;
	readonly isError?: boolean;
}

export type AiTurn =
	| { readonly role: 'user'; readonly text: string }
	/** `raw`: the provider's own content, sent back unchanged (Anthropic thinking blocks must be). */
	| { readonly role: 'assistant'; readonly text: string; readonly toolCalls: readonly IAiToolCall[]; readonly raw?: unknown; readonly provider?: AiProviderId }
	| { readonly role: 'tools'; readonly results: readonly IAiToolResult[] };

export interface IAiToolSpec {
	readonly name: string;
	readonly description: string;
	readonly inputSchema: IJSONSchema;
}

export interface IProviderRequest {
	readonly url: string;
	readonly headers: { readonly [name: string]: string };
	readonly body: unknown;
}

export type StopKind = 'done' | 'tools' | 'maxTokens' | 'refusal' | 'other';

export interface IProviderAnswer {
	readonly text: string;
	readonly toolCalls: readonly IAiToolCall[];
	readonly stop: StopKind;
	/** The assistant turn to keep in the conversation. */
	readonly turn: AiTurn & { role: 'assistant' };
	readonly usage?: { readonly input?: number; readonly output?: number };
}

//#endregion

//#region Anthropic Messages API

export function anthropicRequest(config: IProviderConfig, system: string, turns: readonly AiTurn[], tools: readonly IAiToolSpec[]): IProviderRequest {
	const messages: unknown[] = [];
	for (const turn of turns) {
		switch (turn.role) {
			case 'user':
				messages.push({ role: 'user', content: turn.text });
				break;
			case 'assistant':
				messages.push({
					role: 'assistant',
					content: turn.provider === 'anthropic' && Array.isArray(turn.raw)
						? turn.raw
						: [
							...(turn.text ? [{ type: 'text', text: turn.text }] : []),
							...turn.toolCalls.map(call => ({ type: 'tool_use', id: call.id, name: call.name, input: call.args })),
						],
				});
				break;
			case 'tools':
				messages.push({
					role: 'user',
					content: turn.results.map(result => ({ type: 'tool_result', tool_use_id: result.id, content: result.text, ...(result.isError ? { is_error: true } : {}) })),
				});
				break;
		}
	}
	const fallback = FALLBACK_MODELS.includes(config.model);
	const headers: Record<string, string> = {
		'x-api-key': config.apiKey ?? '',
		'anthropic-version': ANTHROPIC_VERSION,
	};
	if (fallback) {
		headers['anthropic-beta'] = ANTHROPIC_FALLBACK_BETA;
	}
	return {
		url: ANTHROPIC_URL,
		headers,
		body: {
			model: config.model,
			max_tokens: MAX_OUTPUT_TOKENS,
			// The system prompt and the tools never change in a conversation: cached after the first turn.
			system: [{ type: 'text', text: system, cache_control: { type: 'ephemeral' } }],
			messages,
			tools: tools.map(tool => ({ name: tool.name, description: tool.description, input_schema: tool.inputSchema })),
			thinking: { type: 'adaptive' },
			output_config: { effort: config.effort },
			...(fallback ? { fallbacks: 'default' } : {}),
		},
	};
}

export function parseAnthropic(answer: unknown): IProviderAnswer {
	const bag = record(answer);
	const content = Array.isArray(bag.content) ? bag.content : [];
	const texts: string[] = [];
	const toolCalls: IAiToolCall[] = [];
	for (const block of content) {
		const b = record(block);
		if (b.type === 'text' && typeof b.text === 'string') {
			texts.push(b.text);
		} else if (b.type === 'tool_use' && typeof b.id === 'string' && typeof b.name === 'string') {
			toolCalls.push({ id: b.id, name: b.name, args: record(b.input) });
		}
	}
	const reason = bag.stop_reason;
	const stop: StopKind = reason === 'tool_use' ? 'tools' : reason === 'end_turn' || reason === 'stop_sequence' ? 'done' : reason === 'max_tokens' ? 'maxTokens' : reason === 'refusal' ? 'refusal' : 'other';
	const usage = record(bag.usage);
	const text = texts.join('\n\n');
	return {
		text,
		toolCalls,
		stop: stop === 'other' && toolCalls.length ? 'tools' : stop,
		turn: { role: 'assistant', text, toolCalls, raw: content, provider: 'anthropic' },
		usage: { input: num(usage.input_tokens), output: num(usage.output_tokens) },
	};
}

//#endregion

//#region OpenAI-compatible chat completions

export function openAiRequest(config: IProviderConfig, system: string, turns: readonly AiTurn[], tools: readonly IAiToolSpec[]): IProviderRequest {
	const url = providerUrl(config);
	if (!url) {
		throw new Error('no endpoint');
	}
	const messages: unknown[] = [{ role: 'system', content: system }];
	for (const turn of turns) {
		switch (turn.role) {
			case 'user':
				messages.push({ role: 'user', content: turn.text });
				break;
			case 'assistant':
				messages.push({
					role: 'assistant',
					content: turn.text || null,
					...(turn.toolCalls.length ? { tool_calls: turn.toolCalls.map(call => ({ id: call.id, type: 'function', function: { name: call.name, arguments: JSON.stringify(call.args) } })) } : {}),
				});
				break;
			case 'tools':
				for (const result of turn.results) {
					messages.push({ role: 'tool', tool_call_id: result.id, content: result.isError ? `Error: ${result.text}` : result.text });
				}
				break;
		}
	}
	const headers: Record<string, string> = {};
	if (config.apiKey) {
		headers['authorization'] = `Bearer ${config.apiKey}`;
	}
	return {
		url,
		headers,
		body: {
			model: config.model,
			messages,
			max_tokens: MAX_OUTPUT_TOKENS,
			...(tools.length ? { tools: tools.map(tool => ({ type: 'function', function: { name: tool.name, description: tool.description, parameters: tool.inputSchema } })) } : {}),
		},
	};
}

export function parseOpenAi(answer: unknown): IProviderAnswer {
	const bag = record(answer);
	const choice = record(Array.isArray(bag.choices) ? bag.choices[0] : undefined);
	const message = record(choice.message);
	const text = typeof message.content === 'string' ? message.content : '';
	const toolCalls: IAiToolCall[] = [];
	for (const raw of Array.isArray(message.tool_calls) ? message.tool_calls : []) {
		const call = record(raw);
		const fn = record(call.function);
		if (typeof fn.name !== 'string') {
			continue;
		}
		let args: Record<string, unknown> = {};
		try {
			args = typeof fn.arguments === 'string' ? record(JSON.parse(fn.arguments || '{}')) : record(fn.arguments);
		} catch {
			// Invalid JSON from the model: the tool reports the missing arguments.
		}
		toolCalls.push({ id: typeof call.id === 'string' ? call.id : `call_${toolCalls.length}`, name: fn.name, args });
	}
	const reason = choice.finish_reason;
	const stop: StopKind = toolCalls.length || reason === 'tool_calls' ? 'tools' : reason === 'stop' ? 'done' : reason === 'length' ? 'maxTokens' : reason === 'content_filter' ? 'refusal' : 'done';
	const usage = record(bag.usage);
	return {
		text,
		toolCalls,
		stop,
		turn: { role: 'assistant', text, toolCalls, provider: 'openaiCompatible' },
		usage: { input: num(usage.prompt_tokens), output: num(usage.completion_tokens) },
	};
}

//#endregion

export function buildRequest(config: IProviderConfig, system: string, turns: readonly AiTurn[], tools: readonly IAiToolSpec[]): IProviderRequest {
	return config.provider === 'anthropic' ? anthropicRequest(config, system, turns, tools) : openAiRequest(config, system, turns, tools);
}

export function parseAnswer(provider: AiProviderId, answer: unknown): IProviderAnswer {
	return provider === 'anthropic' ? parseAnthropic(answer) : parseOpenAi(answer);
}

/** The provider's error message in an error answer (both APIs put it at `error.message`). */
export function errorMessage(body: string): string | undefined {
	try {
		const error = record(record(JSON.parse(body)).error);
		return typeof error.message === 'string' ? error.message : undefined;
	} catch {
		return undefined;
	}
}

function record(value: unknown): Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}
