/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IAiDataDestination, ISaengineAiDataConsentService } from './aiDataConsent.js';

/*
 * Where the chat sends a SAEngine project's data: the model provider of the model picked in the
 * chat (Copilot with the engineer's GitHub account, or their own key through Manage Language
 * Models). The project's consent (aiDataConsent) is per destination; a provider keeps the id the
 * built-in assistant used ("anthropic|api.anthropic.com"), so an earlier "Allow for This
 * Project" still holds.
 */

/** The chat model as far as the consent needs it. */
export interface IChatModelInfo {
	readonly vendor: string;
	readonly name: string;
}

/** The hosted providers of the chat's models: the host the data goes to and whose terms apply. */
const PROVIDERS: { readonly [vendor: string]: { readonly host: string; readonly label: string } } = {
	copilot: { host: 'api.githubcopilot.com', label: 'GitHub Copilot' },
	anthropic: { host: 'api.anthropic.com', label: 'Anthropic' },
	openai: { host: 'api.openai.com', label: 'OpenAI' },
	gemini: { host: 'generativelanguage.googleapis.com', label: 'Google' },
	xai: { host: 'api.x.ai', label: 'xAI' },
	openrouter: { host: 'openrouter.ai', label: 'OpenRouter' },
};

/** The destination id of the chat's model `model` (undefined: none picked yet). */
export function chatDestinationId(model: IChatModelInfo | undefined): string {
	if (!model) {
		return 'chat';
	}
	const provider = PROVIDERS[model.vendor];
	return provider ? `${model.vendor}|${provider.host}` : `${model.vendor}|${model.name.toLowerCase()}`;
}

/** The consent dialog's destination for a request of the chat with `model`. */
export function chatDestination(model: IChatModelInfo | undefined): IAiDataDestination {
	const provider = model && PROVIDERS[model.vendor];
	const sends = [
		localize('chatConsent.messages', "your messages and the conversation so far"),
		localize('chatConsent.tools', "what SAEngine's tools read when the assistant asks: the project overview, the open document, results, batches worked out on the project, pictures of the window"),
		localize('chatConsent.agent', "in the chat's other modes (Agent, Ask), the project's files the chat reads"),
	];
	if (!model) {
		return {
			id: chatDestinationId(undefined),
			receiver: localize('chatConsent.anyModel', "the AI model selected in the chat (its model picker shows which)"),
			sends,
			terms: localize('chatConsent.anyTerms', "that model provider's"),
		};
	}
	if (model.vendor === 'copilot') {
		return {
			id: chatDestinationId(model),
			receiver: localize('chatConsent.copilot', "GitHub Copilot ({0}), model {1}, with your GitHub account", provider!.host, model.name),
			sends,
			terms: localize('chatConsent.copilotTerms', "GitHub's"),
		};
	}
	if (provider) {
		return {
			id: chatDestinationId(model),
			receiver: localize('chatConsent.byok', "{0} ({1}), model {2}, with your API key", provider.label, provider.host, model.name),
			sends,
			terms: localize('chatConsent.byokTerms', "{0}'s", provider.label),
		};
	}
	return {
		id: chatDestinationId(model),
		receiver: localize('chatConsent.endpoint', "the endpoint that serves model {0} ({1}, as set in Manage Language Models)", model.name, model.vendor),
		sends,
		terms: localize('chatConsent.endpointTerms', "that endpoint's"),
	};
}

/**
 * The chat's submit check: true when a request must not go out, because a project is open and
 * the engineer does not allow its data to go to the chat model's provider (asked now if not
 * decided yet). Without a project nothing of a project can be sent.
 */
export async function withholdRequest(projectOpen: boolean, model: IChatModelInfo | undefined, consent: Pick<ISaengineAiDataConsentService, 'ensure'>): Promise<boolean> {
	return projectOpen && !await consent.ensure(chatDestination(model));
}

/** A destination id as the status bar names it: "api.anthropic.com", "MCP clients". */
export function destinationLabel(id: string): string {
	if (id === 'mcp') {
		return localize('chatConsent.mcpShort', "MCP clients");
	}
	if (id === 'chat') {
		return localize('chatConsent.chatShort', "the chat's model");
	}
	return id.slice(id.indexOf('|') + 1);
}
