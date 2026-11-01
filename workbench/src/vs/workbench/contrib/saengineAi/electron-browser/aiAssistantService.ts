/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken, CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { isCancellationError } from '../../../../base/common/errors.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { generateUuid } from '../../../../base/common/uuid.js';
import { localize } from '../../../../nls.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { createDecorator, IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { ISharedProcessService } from '../../../../platform/ipc/electron-browser/services.js';
import { Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { ISaengineAiHttpRequest, ISaengineAiHttpResponse, SAENGINE_AI_CHANNEL } from '../../../../platform/saengine/common/saengineAi.js';
import { ISecretStorageService } from '../../../../platform/secrets/common/secrets.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IOutputService } from '../../../services/output/common/output.js';
import { TIME, formatDate } from '../../../services/saengineProject/common/formatting.js';
import { CONSENT_STORAGE_KEY, consentKey, readScopes, runAssistant, SCOPES_STORAGE_KEY, systemPrompt } from '../common/aiAssistant.js';
import { AiEffort, AiProviderId, AiTurn, ANTHROPIC_MODEL_SETTING, buildRequest, DEFAULT_ANTHROPIC_MODEL, EFFORT_SETTING, errorMessage, IAiToolCall, IAiToolResult, IProviderAnswer, IProviderConfig, OPENAI_ENDPOINT_SETTING, OPENAI_MODEL_SETTING, parseAnswer, PROVIDER_SETTING, providerHost, secretKey } from '../common/aiProviders.js';
import { AI_TOOLS, assistantTools, ContextScope, OptionalScope } from '../common/aiTools.js';
import { AI_ACTIVITY_CHANNEL_ID } from './aiController.js';
import { AiToolRunner } from './aiToolRunner.js';

/** One line of the conversation as the view shows it. */
export interface IAssistantEntry {
	readonly id: string;
	readonly kind: 'user' | 'answer' | 'tool' | 'error' | 'notice';
	readonly text: string;
	/** Tool lines: the tool, and what its result sent to the provider. */
	readonly tool?: string;
	readonly scope?: ContextScope;
	readonly failed?: boolean;
	/** Error lines: a fix the view offers. */
	readonly action?: 'setKey' | 'configure';
}

export const ISaengineAiAssistantService = createDecorator<ISaengineAiAssistantService>('saengineAiAssistantService');

export interface ISaengineAiAssistantService {
	readonly _serviceBrand: undefined;
	readonly entries: readonly IAssistantEntry[];
	readonly busy: boolean;
	/** The context the engineer lets the assistant read. */
	readonly scopes: ReadonlySet<OptionalScope>;
	readonly onDidChange: Event<void>;
	/** Where questions go, for the indicator: provider, host and model (undefined: not configured). */
	destination(): { readonly provider: AiProviderId; readonly host: string | undefined; readonly model: string };
	hasKey(): Promise<boolean>;
	ask(question: string): Promise<void>;
	cancel(): void;
	clear(): void;
	setScope(scope: OptionalScope, allowed: boolean): void;
	setKey(): Promise<void>;
	removeKey(): Promise<void>;
	/** Forgets "always allow" for every address. */
	resetConsent(): void;
}

export class SaengineAiAssistantService extends Disposable implements ISaengineAiAssistantService {

	declare readonly _serviceBrand: undefined;

	private turns: AiTurn[] = [];
	private readonly _entries: IAssistantEntry[] = [];
	get entries(): readonly IAssistantEntry[] { return this._entries; }

	private cancellation: CancellationTokenSource | undefined;
	get busy(): boolean { return !!this.cancellation; }

	private _scopes: Set<OptionalScope>;
	get scopes(): ReadonlySet<OptionalScope> { return this._scopes; }

	/** Addresses the engineer agreed to for this window's session. */
	private readonly sessionConsent = new Set<string>();
	private readonly runner: AiToolRunner;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	constructor(
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ISecretStorageService private readonly secretStorageService: ISecretStorageService,
		@ISharedProcessService private readonly sharedProcessService: ISharedProcessService,
		@IStorageService private readonly storageService: IStorageService,
		@IDialogService private readonly dialogService: IDialogService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@IOutputService private readonly outputService: IOutputService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		// Never set_json_value: the built-in assistant changes the model only through change sets.
		this.runner = instantiationService.createInstance(AiToolRunner, () => false);
		this._scopes = readScopes(this.storageService.get(SCOPES_STORAGE_KEY, StorageScope.APPLICATION));
		this._register(configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('saengine.ai.assistant')) {
				this._onDidChange.fire();
			}
		}));
		this._register(secretStorageService.onDidChangeSecret(() => this._onDidChange.fire()));
	}

	private config(): Omit<IProviderConfig, 'apiKey'> {
		const provider = this.configurationService.getValue<AiProviderId>(PROVIDER_SETTING) === 'openaiCompatible' ? 'openaiCompatible' : 'anthropic';
		const effortValue = this.configurationService.getValue<string>(EFFORT_SETTING);
		const effort: AiEffort = effortValue === 'low' || effortValue === 'medium' ? effortValue : 'high';
		if (provider === 'anthropic') {
			return { provider, model: this.configurationService.getValue<string>(ANTHROPIC_MODEL_SETTING)?.trim() || DEFAULT_ANTHROPIC_MODEL, effort };
		}
		return {
			provider,
			model: this.configurationService.getValue<string>(OPENAI_MODEL_SETTING)?.trim() ?? '',
			endpoint: this.configurationService.getValue<string>(OPENAI_ENDPOINT_SETTING)?.trim() ?? '',
			effort,
		};
	}

	destination() {
		const config = this.config();
		return { provider: config.provider, host: providerHost(config), model: config.model };
	}

	async hasKey(): Promise<boolean> {
		return !!(await this.secretStorageService.get(secretKey(this.config().provider)));
	}

	setScope(scope: OptionalScope, allowed: boolean): void {
		if (allowed) {
			this._scopes.add(scope);
		} else {
			this._scopes.delete(scope);
		}
		this.storageService.store(SCOPES_STORAGE_KEY, JSON.stringify([...this._scopes]), StorageScope.APPLICATION, StorageTarget.USER);
		this._onDidChange.fire();
	}

	async setKey(): Promise<void> {
		const { provider } = this.config();
		const key = await this.quickInputService.input({
			password: true,
			title: provider === 'anthropic' ? localize('assistant.keyTitleAnthropic', "Anthropic API Key") : localize('assistant.keyTitleOpenAi', "API Key of the OpenAI-Compatible Endpoint"),
			prompt: localize('assistant.keyPrompt', "Kept in the operating system's secret store for SAEngine, never in settings or project files."),
			placeHolder: provider === 'anthropic' ? 'sk-ant-…' : '',
			ignoreFocusLost: true,
		});
		if (!key?.trim()) {
			return;
		}
		await this.secretStorageService.set(secretKey(provider), key.trim());
		if (this.secretStorageService.type === 'in-memory') {
			this.notice(localize('assistant.keyInMemory', "The operating system's secret store is not available, so the key is kept only until SAEngine closes."));
		}
		this.log(localize('activity.keySet', "Assistant: an API key was saved for {0}.", provider));
		this._onDidChange.fire();
	}

	async removeKey(): Promise<void> {
		const { provider } = this.config();
		await this.secretStorageService.delete(secretKey(provider));
		this.log(localize('activity.keyRemoved', "Assistant: the API key of {0} was removed.", provider));
		this._onDidChange.fire();
	}

	resetConsent(): void {
		this.storageService.remove(CONSENT_STORAGE_KEY, StorageScope.APPLICATION);
		this.sessionConsent.clear();
		this._onDidChange.fire();
	}

	clear(): void {
		this.cancel();
		this.turns = [];
		this._entries.length = 0;
		this._onDidChange.fire();
	}

	cancel(): void {
		this.cancellation?.cancel();
	}

	async ask(question: string): Promise<void> {
		const text = question.trim();
		if (!text || this.busy) {
			return;
		}
		const base = this.config();
		const host = providerHost(base);
		if (!host || !base.model) {
			this.push({ kind: 'error', text: localize('assistant.notConfigured', "Choose the model provider first: the OpenAI-compatible endpoint needs its address and model name."), action: 'configure' });
			return;
		}
		const apiKey = await this.secretStorageService.get(secretKey(base.provider));
		if (base.provider === 'anthropic' && !apiKey) {
			this.push({ kind: 'error', text: localize('assistant.noKey', "Set your Anthropic API key first. It is kept in the operating system's secret store."), action: 'setKey' });
			return;
		}
		if (!await this.consent(base.provider, host, base.model)) {
			return;
		}
		const config: IProviderConfig = { ...base, apiKey };
		const scopes = new Set(this._scopes);
		const tools = assistantTools(scopes).map(tool => ({ name: tool.name, description: tool.description, inputSchema: tool.inputSchema }));
		const system = systemPrompt(scopes);
		const userTurn: AiTurn = { role: 'user', text };
		const cancellation = this.cancellation = new CancellationTokenSource();
		this.push({ kind: 'user', text });
		this.log(localize('activity.assistantAsk', "Assistant: a question ({0} characters) sent to {1} ({2}).", text.length, host, config.model));
		try {
			const added = await runAssistant([...this.turns, userTurn], {
				send: (turns, token) => this.send(config, system, turns, tools, token),
				runTool: (call, token) => this.runTool(call, scopes, token),
				onEvent: event => {
					switch (event.kind) {
						case 'answer': this.push({ kind: 'answer', text: event.text }); break;
						case 'toolCall': break;
						case 'toolResult': this.push({ kind: 'tool', text: describeTool(event.result), tool: event.result.name, scope: AI_TOOLS.find(t => t.name === event.result.name)?.assistant, failed: event.result.isError }); break;
						case 'stopped': this.push({
							kind: 'notice', text: event.reason === 'refusal'
								? localize('assistant.refused', "The model declined to answer this.")
								: event.reason === 'maxTokens'
									? localize('assistant.maxTokens', "The answer was cut at its length limit.")
									: localize('assistant.steps', "Stopped after many steps; ask again to continue."),
						}); break;
					}
				},
			}, cancellation.token);
			// Kept only when the whole round went through: the provider needs every tool result.
			this.turns.push(userTurn, ...added);
		} catch (error) {
			if (isCancellationError(error) || cancellation.token.isCancellationRequested) {
				this.push({ kind: 'notice', text: localize('assistant.cancelled', "Stopped.") });
			} else {
				this.push({ kind: 'error', text: error instanceof Error ? error.message : String(error) });
			}
		} finally {
			cancellation.dispose();
			this.cancellation = undefined;
			this._onDidChange.fire();
		}
	}

	/** Asks before the first question to an address (once a session, or always). */
	private async consent(provider: AiProviderId, host: string, model: string): Promise<boolean> {
		const key = consentKey(provider, host);
		const always = this.alwaysAllowed();
		if (this.sessionConsent.has(key) || always.includes(key)) {
			return true;
		}
		const scopes = [
			localize('consent.code', "passages of the code pack and the SAEngine manual the assistant looks up"),
			...(this._scopes.has('project') ? [localize('consent.project', "the project overview (name, parts and their status, open editors)")] : []),
			...(this._scopes.has('document') ? [localize('consent.document', "the document open in the editor, when the assistant reads it")] : []),
			...(this._scopes.has('results') ? [localize('consent.results', "analysis and design results, when the assistant reads them")] : []),
		];
		const { result } = await this.dialogService.prompt<'session' | 'always' | undefined>({
			type: Severity.Info,
			message: localize('consent.title', "Send to {0}?", host),
			detail: localize('consent.detail', "The AI assistant sends your questions and the conversation so far to {0} (model {1}), and with them:\n\n• {2}\n\nNothing else leaves this computer, and nothing is sent before you agree. Change what may be read with the switches in the AI Assistant view. The API key stays in the operating system's secret store; each request is listed in AI Activity.", host, model, scopes.join('\n• ')),
			buttons: [
				{ label: localize({ key: 'consent.session', comment: ['&& denotes a mnemonic'] }, "&&Allow for This Session"), run: () => 'session' as const },
				{ label: localize({ key: 'consent.always', comment: ['&& denotes a mnemonic'] }, "Always Allow {0}", host), run: () => 'always' as const },
			],
			cancelButton: { label: localize('consent.cancel', "Don't Send"), run: () => undefined },
		});
		if (result === 'always') {
			this.storageService.store(CONSENT_STORAGE_KEY, JSON.stringify([...always, key]), StorageScope.APPLICATION, StorageTarget.USER);
		}
		if (result) {
			this.sessionConsent.add(key);
			this.log(localize('activity.consent', "Assistant: you allowed sending to {0} ({1}).", host, result === 'always' ? localize('consent.alwaysShort', "always") : localize('consent.sessionShort', "this session")));
			return true;
		}
		return false;
	}

	private alwaysAllowed(): string[] {
		try {
			const value = JSON.parse(this.storageService.get(CONSENT_STORAGE_KEY, StorageScope.APPLICATION) ?? '[]');
			return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
		} catch {
			return [];
		}
	}

	private async send(config: IProviderConfig, system: string, turns: readonly AiTurn[], tools: Parameters<typeof buildRequest>[3], token: CancellationToken): Promise<IProviderAnswer> {
		const request = buildRequest(config, system, turns, tools);
		const id = generateUuid();
		const channel = this.sharedProcessService.getChannel(SAENGINE_AI_CHANNEL);
		const listener = token.onCancellationRequested(() => { void channel.call('cancelHttp', id); });
		try {
			const message: ISaengineAiHttpRequest = { id, url: request.url, headers: request.headers, body: JSON.stringify(request.body) };
			const response = await channel.call<ISaengineAiHttpResponse>('httpPost', message);
			if (token.isCancellationRequested) {
				throw new Error(localize('assistant.cancelledShort', "Stopped."));
			}
			if (response.error) {
				throw new Error(localize('assistant.unreachable', "{0} could not be reached: {1}", new URL(request.url).host, response.error));
			}
			if (response.status === 401 || response.status === 403) {
				throw new Error(localize('assistant.keyRefused', "The provider refused the API key ({0}). Set the key again.", errorMessage(response.body) ?? response.status));
			}
			if (response.status === 429) {
				throw new Error(localize('assistant.rateLimited', "The provider is busy or the account's limit is reached; try again in a minute. ({0})", errorMessage(response.body) ?? response.status));
			}
			if (response.status < 200 || response.status >= 300) {
				throw new Error(localize('assistant.httpError', "The provider answered {0}: {1}", response.status, errorMessage(response.body) ?? response.body.slice(0, 300)));
			}
			let body: unknown;
			try {
				body = JSON.parse(response.body);
			} catch {
				throw new Error(localize('assistant.notJson', "The provider's answer is not JSON."));
			}
			return parseAnswer(config.provider, body);
		} finally {
			listener.dispose();
		}
	}

	private async runTool(call: IAiToolCall, scopes: ReadonlySet<OptionalScope>, _token: CancellationToken): Promise<IAiToolResult> {
		const allowed = assistantTools(scopes).some(tool => tool.name === call.name);
		if (!allowed) {
			const tool = AI_TOOLS.find(t => t.name === call.name);
			const text = tool?.assistant
				? `The engineer has not allowed reading ${tool.assistant} in the AI Assistant view.`
				: `Unknown tool "${call.name}".`;
			this.log(localize('activity.assistantRefused', "Assistant: {0} refused ({1}).", call.name, text));
			return { id: call.id, name: call.name, text, isError: true };
		}
		const started = Date.now();
		const result = await this.runner.call(call.name, call.args, 'assistant');
		const text = result.content.map(part => part.type === 'text' ? part.text : `[${part.type} not sent]`).join('\n');
		this.log(localize('activity.assistantTool', "Assistant: {0}({1}) {2} [{3} ms]", call.name, shorten(JSON.stringify(call.args)), result.isError ? localize('activity.failedShort', "failed") : localize('activity.okShort', "ok"), Date.now() - started));
		return { id: call.id, name: call.name, text, isError: !!result.isError };
	}

	private push(entry: Omit<IAssistantEntry, 'id'>): void {
		this._entries.push({ id: generateUuid(), ...entry });
		this._onDidChange.fire();
	}

	private notice(text: string): void {
		this.push({ kind: 'notice', text });
	}

	private log(line: string): void {
		this.outputService.getChannel(AI_ACTIVITY_CHANNEL_ID)?.append(`[${formatDate(Date.now(), TIME)}] ${line}\n`);
	}

	override dispose(): void {
		this.cancel();
		super.dispose();
	}
}

/** One line for a tool the assistant used, as the engineer reads it. */
function describeTool(result: IAiToolResult): string {
	const failed = result.isError ? ` ${localize('tool.failed', "(failed)")}` : '';
	switch (result.name) {
		case 'search_code': return localize('tool.searchCode', "Looked up the code pack") + failed;
		case 'explain_results': return localize('tool.explainResults', "Read the design checks") + failed;
		case 'read_results': return localize('tool.readResults', "Read the results summary") + failed;
		case 'get_project': return localize('tool.getProject', "Read the project overview") + failed;
		case 'list_editors': return localize('tool.listEditors', "Read the list of open editors") + failed;
		case 'read_active_document': return localize('tool.readDocument', "Read the open document") + failed;
		case 'open_part': return localize('tool.openPart', "Opened a part") + failed;
		case 'open_file': return localize('tool.openFile', "Opened a project file") + failed;
		case 'reveal_element': return localize('tool.reveal', "Showed a member") + failed;
		case 'propose_changes': return localize('tool.proposeChanges', "Proposed a change set") + failed;
		case 'propose_building': return localize('tool.proposeBuilding', "Filled the New Building wizard") + failed;
		default: return result.name + failed;
	}
}

function shorten(text: string, length = 200): string {
	return text.length > length ? `${text.slice(0, length)}…` : text;
}
