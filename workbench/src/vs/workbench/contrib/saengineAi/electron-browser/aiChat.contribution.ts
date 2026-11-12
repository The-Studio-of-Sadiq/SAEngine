/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { Event } from '../../../../base/common/event.js';
import { Disposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions, IConfigurationDefaults, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ExtensionIdentifier } from '../../../../platform/extensions/common/extensions.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InMemoryFileSystemProvider } from '../../../../platform/files/common/inMemoryFilesystemProvider.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ISecretStorageService } from '../../../../platform/secrets/common/secrets.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IWorkbenchContribution, WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { nullExtensionDescription } from '../../../services/extensions/common/extensions.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { IChatWidgetService } from '../../chat/browser/chat.js';
import { IChatSubmitRequestHandlerService } from '../../chat/browser/chatSubmitRequestHandlerService.js';
import { MANAGE_CHAT_COMMAND_ID } from '../../chat/common/constants.js';
import { ILanguageModelsService } from '../../chat/common/languageModels.js';
import { ILanguageModelsConfigurationService } from '../../chat/common/languageModelsConfiguration.js';
import { PromptsType } from '../../chat/common/promptSyntax/promptTypes.js';
import { IPromptsService } from '../../chat/common/promptSyntax/service/promptsService.js';
import { ConfigurationDefaultsSwitch } from '../../saengineProject/browser/saengineShell.js';
import { AGENT_NAME, agentFile } from '../common/aiAssistant.js';
import { ISaengineAiChangeSetService } from '../browser/aiChangeSets.js';
import { destinationLabel, withholdRequest } from '../browser/aiChatConsent.js';
import { UNDO_CHANGE_SET_COMMAND } from '../browser/aiChatReview.js';
import { SaengineChatToolsRegistration } from '../browser/aiChatTools.js';
import { ISaengineAiDataConsentService, MANAGE_PROJECT_CONSENT_COMMAND } from '../browser/aiDataConsent.js';
import { AI_ACTIVITY_CHANNEL_ID } from './aiController.js';
import { AiToolRunner } from './aiToolRunner.js';
import { IOutputService } from '../../../services/output/common/output.js';
import { TIME, formatDate } from '../../../services/saengineProject/common/formatting.js';

/*
 * SAEngine's assistant in the title-bar chat (AI round, track C; owner: one chat, not two). The
 * chat (VS Code's, with the bundled Copilot Chat extension) runs the conversation with the model
 * the engineer picks: Copilot after Sign In, or their own key (Anthropic, an OpenAI-compatible
 * endpoint, ...) in Manage Language Models. SAEngine adds:
 * - its tools as chat tools in the "saengine" tool set, on the MCP server's tool runner;
 * - the "SAEngine" agent (mode) with the build-a-project playbook, offering only that tool set,
 *   the default for new chats while a project is open;
 * - the project's consent before a request goes out (the chat's submit handler) and before a
 *   tool reads project data, and the status bar item that says where this project's data goes;
 * - the change-set review and run confirmations in the chat (aiChatReview);
 * - moving the old AI Assistant's provider and key into the chat's language models, once.
 */

const category = localize2('saengine.category', "SAEngine");

/** The in-memory scheme of the SAEngine agent's file (it is generated, not shipped). */
const AGENT_SCHEME = 'saengine-ai';

/** The SAEngine agent is contributed as built into the app, not by an extension the user installed. */
const SAENGINE_CONTRIBUTOR = Object.freeze({
	...nullExtensionDescription,
	identifier: new ExtensionIdentifier('saengine.assistant'),
	name: 'saengine-assistant',
	displayName: 'SAEngine',
	publisher: 'saengine',
	isBuiltin: true,
});

/** How the chat behaves in SAEngine (both modes): it never saves the engineer's parts or attaches the open document by itself. */
const CHAT_DEFAULTS: IConfigurationDefaults = {
	overrides: {
		// Unsaved part edits are the engineer's: sending a question must not save them.
		'chat.saveBeforeSend': false,
		// The open part goes to the provider only when a tool reads it (after the project's consent).
		'chat.implicitContext.enabled': { panel: 'never' },
		'chat.implicitContext.includeActiveEditor': false,
	},
	source: { id: 'saengine.chat', displayName: 'SAEngine' },
};
const configurationRegistry = Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration);
configurationRegistry.registerDefaultConfigurations([CHAT_DEFAULTS]);

/** New chats start in the SAEngine agent while a project is open. */
const PROJECT_CHAT_DEFAULTS = new ConfigurationDefaultsSwitch(configurationRegistry, {
	overrides: { 'chat.newSession.defaultMode': AGENT_NAME },
	source: { id: 'saengine.chat.project', displayName: 'SAEngine' },
});

/** Application storage: the old assistant's provider settings and key were moved into the chat. */
const PROVIDERS_MIGRATED_KEY = 'saengine.ai.providersMigrated';
/** The old AI Assistant's settings and secret store keys (round T49), read once to migrate. */
const LEGACY = {
	provider: 'saengine.ai.assistant.provider',
	endpoint: 'saengine.ai.assistant.endpoint',
	model: 'saengine.ai.assistant.model',
	anthropicKey: 'saengine.ai.assistant.key.anthropic',
	endpointKey: 'saengine.ai.assistant.key.openaiCompatible',
};

class SaengineChatContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengineAiChat';

	private readonly statusEntry = this._register(new MutableDisposable<IStatusbarEntryAccessor>());

	constructor(
		@IInstantiationService instantiationService: IInstantiationService,
		@IFileService fileService: IFileService,
		@IPromptsService promptsService: IPromptsService,
		@IChatSubmitRequestHandlerService submitHandlers: IChatSubmitRequestHandlerService,
		@IChatWidgetService private readonly chatWidgetService: IChatWidgetService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaengineAiDataConsentService private readonly dataConsent: ISaengineAiDataConsentService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@ILanguageModelsService private readonly languageModelsService: ILanguageModelsService,
		@ILanguageModelsConfigurationService private readonly languageModelsConfiguration: ILanguageModelsConfigurationService,
		@ISecretStorageService private readonly secretStorageService: ISecretStorageService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IStorageService private readonly storageService: IStorageService,
		@IOutputService private readonly outputService: IOutputService,
		@INotificationService private readonly notificationService: INotificationService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		// The tools: one runner for the chat, edits only through change sets (no edits switch).
		const runner = instantiationService.createInstance(AiToolRunner, () => false);
		this._register(instantiationService.createInstance(SaengineChatToolsRegistration, runner));

		// The SAEngine agent, from the same instructions SAEngine keeps in code.
		const agentFiles = this._register(new InMemoryFileSystemProvider());
		this._register(fileService.registerProvider(AGENT_SCHEME, agentFiles));
		const agentUri = URI.from({ scheme: AGENT_SCHEME, path: '/saengine.agent.md' });
		void agentFiles.writeFile(agentUri, VSBuffer.fromString(agentFile()).buffer, { create: true, overwrite: true, unlock: false, atomic: false }).then(() => {
			if (!this._store.isDisposed) {
				this._register(promptsService.registerContributedFile(PromptsType.agent, agentUri, SAENGINE_CONTRIBUTOR, AGENT_NAME, localize('agent.description', "Builds, changes and explains your SAEngine project; every change is a change set you accept.")));
			}
		});

		// U2: nothing of a project goes to the chat's model provider before the engineer allows it.
		this._register(submitHandlers.register({ id: 'saengine.projectDataConsent', tryHandle: request => this.withholdWithoutConsent(request.sessionResource, request.input) }));

		this._register(projectService.onDidChangeProject(() => this.update()));
		this._register(dataConsent.onDidChange(() => this.update()));
		this.update();

		void this.migrateProviders().catch(error => this.logService.warn('[saengineAi] moving the AI Assistant provider into the chat failed', error));
	}

	/** True (the request is not sent) when the engineer does not allow it now; their words stay in the input. */
	private async withholdWithoutConsent(sessionResource: URI, input: string): Promise<boolean> {
		const widget = this.chatWidgetService.getWidgetBySessionResource(sessionResource);
		if (!await withholdRequest(!!this.projectService.project, widget?.input.selectedLanguageModel.get()?.metadata, this.dataConsent)) {
			return false;
		}
		// The chat clears its input after a handled submission: give the words back.
		setTimeout(() => widget?.setInput(input), 0);
		return true;
	}

	private update(): void {
		const project = this.projectService.project;
		PROJECT_CHAT_DEFAULTS.set(!!project);
		if (!project) {
			this.statusEntry.clear();
			return;
		}
		// Where this project's data may go, always in sight while a project is open.
		const allowed = this.dataConsent.allowed().map(destinationLabel);
		const text = allowed.length
			? `$(cloud-upload) ${localize('chatData.status', "AI: {0}", allowed.join(', '))}`
			: `$(shield) ${localize('chatData.statusNone', "AI: asks first")}`;
		const tooltip = allowed.length
			? localize('chatData.tooltip', "This project's data may go to: {0}. SAEngine and its developers never receive or sell it. Click to stop it.", allowed.join(', '))
			: localize('chatData.tooltipNone', "No AI provider receives this project's data yet: SAEngine asks before the first request. Click for AI data sharing.");
		const entry = { name: localize('chatData.name', "AI Data Sharing"), text, ariaLabel: tooltip, tooltip, command: MANAGE_PROJECT_CONSENT_COMMAND };
		if (this.statusEntry.value) {
			this.statusEntry.value.update(entry);
		} else {
			this.statusEntry.value = this.statusbarService.addEntry(entry, 'saengine.ai.chatData', StatusbarAlignment.RIGHT, 999);
		}
	}

	/**
	 * The old AI Assistant kept its own provider settings and key (saengine.ai.assistant.*). They
	 * move into the chat's language models once, where the model picker and Manage Language
	 * Models show them: the Anthropic key as an "Anthropic" provider, the OpenAI-compatible
	 * endpoint as a "Self-hosted" Custom Endpoint. The keys stay in the secret store.
	 */
	private async migrateProviders(): Promise<void> {
		if (this.storageService.getBoolean(PROVIDERS_MIGRATED_KEY, StorageScope.APPLICATION, false)) {
			return;
		}
		const anthropicKey = await this.secretStorageService.get(LEGACY.anthropicKey);
		const endpoint = this.configurationService.getValue<string>(LEGACY.endpoint)?.trim();
		const model = this.configurationService.getValue<string>(LEGACY.model)?.trim();
		const wantsEndpoint = this.configurationService.getValue<string>(LEGACY.provider) === 'openaiCompatible' && !!endpoint && !!model;
		if (!anthropicKey && !wantsEndpoint) {
			this.storageService.store(PROVIDERS_MIGRATED_KEY, true, StorageScope.APPLICATION, StorageTarget.MACHINE);
			return;
		}
		// The providers are the chat extension's (the setup's AI component): without it, next time.
		const vendors = await this.vendors(['anthropic', 'customendpoint']);
		if (!vendors) {
			return;
		}
		await this.languageModelsConfiguration.whenReady;
		const groups = this.languageModelsConfiguration.getLanguageModelsProviderGroups();
		const moved: string[] = [];
		if (anthropicKey) {
			if (!groups.some(group => group.vendor === 'anthropic')) {
				await this.languageModelsService.addLanguageModelsProviderGroup('Anthropic', 'anthropic', { apiKey: anthropicKey });
				moved.push('Anthropic');
			}
			await this.secretStorageService.delete(LEGACY.anthropicKey);
		}
		if (wantsEndpoint && !groups.some(group => group.vendor === 'customendpoint' && group.name === 'Self-hosted')) {
			const key = await this.secretStorageService.get(LEGACY.endpointKey);
			const url = /\/chat\/completions\/?$/.test(endpoint!) ? endpoint! : `${endpoint!.replace(/\/+$/, '')}/chat/completions`;
			await this.languageModelsService.addLanguageModelsProviderGroup('Self-hosted', 'customendpoint', {
				// The provider needs a key; a server on this computer usually takes any.
				apiKey: key || 'none',
				apiType: 'chat-completions',
				models: [{ id: model, name: model, url, toolCalling: true, vision: false, maxInputTokens: 128000, maxOutputTokens: 16000 }],
			});
			await this.secretStorageService.delete(LEGACY.endpointKey);
			moved.push('Self-hosted');
		}
		this.storageService.store(PROVIDERS_MIGRATED_KEY, true, StorageScope.APPLICATION, StorageTarget.MACHINE);
		if (moved.length) {
			this.outputService.getChannel(AI_ACTIVITY_CHANNEL_ID)?.append(`[${formatDate(Date.now(), TIME)}] ${localize('migrated.log', "The AI Assistant's provider moved into the chat's language models: {0}.", moved.join(', '))}\n`);
			this.notificationService.notify({
				severity: Severity.Info,
				message: localize('migrated', "SAEngine's assistant is now in the chat (title bar). Your AI provider moved there too ({0}): pick its model in the chat's model picker.", moved.join(', ')),
			});
		}
	}

	/** Resolves true once all `ids` are known chat model vendors (the chat extension registered them), false after a while without. */
	private async vendors(ids: readonly string[]): Promise<boolean> {
		const known = () => ids.every(id => this.languageModelsService.getVendors().some(vendor => vendor.vendor === id));
		if (known()) {
			return true;
		}
		const changed = Event.toPromise(Event.filter(this.languageModelsService.onDidChangeLanguageModelVendors, () => known()), this._store);
		let timer: ReturnType<typeof setTimeout> | undefined;
		const waited = new Promise<false>(resolve => timer = setTimeout(() => resolve(false), 60_000));
		try {
			return await Promise.race([changed.then(() => true), waited]);
		} finally {
			clearTimeout(timer);
		}
	}
}

registerWorkbenchContribution2(SaengineChatContribution.ID, SaengineChatContribution, WorkbenchPhase.AfterRestored);

/** Undo of a change set accepted in the chat (the Undo link after it). */
registerAction2(class extends Action2 {
	constructor() {
		super({ id: UNDO_CHANGE_SET_COMMAND, title: localize2('changeSet.undo', "Undo AI Change Set"), category, f1: false });
	}
	override async run(accessor: ServicesAccessor, id?: string): Promise<void> {
		const changeSets = accessor.get(ISaengineAiChangeSetService);
		const notificationService = accessor.get(INotificationService);
		const set = typeof id === 'string' ? changeSets.changeSets.find(s => s.id === id) : changeSets.changeSets.find(s => s.state === 'accepted');
		if (set && changeSets.canUndo(set.id)) {
			await changeSets.undo(set.id);
			notificationService.notify({ severity: Severity.Info, message: localize('changeSet.undone', "Undid \"{0}\".", set.title) });
		} else {
			notificationService.notify({ severity: Severity.Info, message: localize('changeSet.cannotUndo', "This change set can no longer be undone on its own (the files changed since). Use Undo (Ctrl+Z) in the part's editor.") });
		}
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.openChat',
			title: localize2('openChat', "Ask the AI Assistant"),
			metadata: { description: localize2('openChat.description', "Opens the chat with the SAEngine agent: build or change the project by asking, answers about the code pack with clauses, explanations of results.") },
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.chat.open', { mode: AGENT_NAME });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.manageModels',
			title: localize2('manageModels', "Choose AI Models and Providers..."),
			metadata: { description: localize2('manageModels.description', "Manage Language Models: Copilot after Sign In, or your own key (Anthropic, OpenAI-compatible endpoint, ...).") },
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand(MANAGE_CHAT_COMMAND_ID);
	}
});

/** Adds a provider of the chat's models with the engineer's own key (Anthropic, the default) or endpoint. */
async function addProvider(accessor: ServicesAccessor, vendor: 'anthropic' | 'customendpoint'): Promise<void> {
	const languageModelsService = accessor.get(ILanguageModelsService);
	const notificationService = accessor.get(INotificationService);
	if (!languageModelsService.getVendors().some(v => v.vendor === vendor)) {
		notificationService.notify({ severity: Severity.Warning, message: localize('noChatExtension', "The chat's model providers come with the setup's AI component (GitHub Copilot Chat), which is not installed or not running.") });
		return;
	}
	await languageModelsService.configureLanguageModelsProviderGroup(vendor);
}

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.ai.useAnthropicKey', title: localize2('useAnthropicKey', "Use My Anthropic API Key..."), category, f1: true });
	}
	override run(accessor: ServicesAccessor): Promise<void> {
		return addProvider(accessor, 'anthropic');
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.ai.useEndpoint', title: localize2('useEndpoint', "Use a Self-Hosted Model (OpenAI-Compatible Endpoint)..."), category, f1: true });
	}
	override run(accessor: ServicesAccessor): Promise<void> {
		return addProvider(accessor, 'customendpoint');
	}
});
