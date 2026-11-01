/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewsRegistry, ViewContainerLocation } from '../../../common/views.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { addComponentLink } from '../../saengineUpdate/common/components.js';
import { ISaengineAiChangeSetService, SaengineAiChangeSetService } from '../browser/aiChangeSets.js';
import { ASSISTANT_CONTAINER_ID, ASSISTANT_VIEW_ID } from '../common/aiAssistant.js';
import { AiProviderId, ANTHROPIC_MODEL_SETTING, ANTHROPIC_MODELS, DEFAULT_ANTHROPIC_MODEL, EFFORT_SETTING, OPENAI_ENDPOINT_SETTING, OPENAI_MODEL_SETTING, PROVIDER_SETTING } from '../common/aiProviders.js';
import { ISaengineAiAssistantService, SaengineAiAssistantService } from './aiAssistantService.js';
import { AI_COMPONENT_KEY, AiAssistantView, CONFIGURE_COMMAND, SET_KEY_COMMAND } from './aiAssistantView.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';

/*
 * The built-in AI assistant (round T49): its settings, its view in the secondary side bar and
 * its commands. It ships with the setup's optional AI component (`saengine.component.ai`):
 * without it the view says so and offers to add it. The engineer chooses the provider and
 * gives the key (kept in the operating system's secret store); nothing is sent before the
 * engineer agrees, and the view shows what is sent and where.
 */

const category = localize2('saengine.category', "SAEngine");

registerSingleton(ISaengineAiChangeSetService, SaengineAiChangeSetService, InstantiationType.Delayed);
registerSingleton(ISaengineAiAssistantService, SaengineAiAssistantService, InstantiationType.Delayed);

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineAiAssistant',
	order: 102,
	title: localize('assistantConfigurationTitle', "SAEngine AI Assistant"),
	type: 'object',
	// Application scope, restricted: a project's own settings must never redirect what is sent.
	properties: {
		[PROVIDER_SETTING]: {
			type: 'string',
			enum: ['anthropic', 'openaiCompatible'],
			enumDescriptions: [
				localize('provider.anthropic.description', "The Anthropic API (Claude models): needs your Anthropic API key."),
				localize('provider.openai.description', "An OpenAI-compatible chat completions endpoint, for example a model you host yourself on this computer or in your office."),
			],
			default: 'anthropic',
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.assistant.provider', "Where the AI assistant sends your questions. Nothing is sent before you agree, and the key is kept in the operating system's secret store (**SAEngine: Set AI Assistant API Key**)."),
		},
		[ANTHROPIC_MODEL_SETTING]: {
			type: 'string',
			default: DEFAULT_ANTHROPIC_MODEL,
			examples: [...ANTHROPIC_MODELS],
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.assistant.anthropicModel', "The Claude model: `claude-opus-5-5` (most capable, the default), `claude-sonnet-5-5` (faster, lower cost) or `claude-haiku-5-5` (fastest). Any other model id is sent as written."),
		},
		[EFFORT_SETTING]: {
			type: 'string',
			enum: ['low', 'medium', 'high'],
			default: 'high',
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.assistant.effort', "How hard the Anthropic model thinks before it answers: higher is slower and costs more, and is better for design questions."),
		},
		[OPENAI_ENDPOINT_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.assistant.endpoint', "The base URL of the OpenAI-compatible endpoint, for example `http://localhost:11434/v1` (https, or http to this computer only). `/chat/completions` is added."),
		},
		[OPENAI_MODEL_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.assistant.model', "The model name the OpenAI-compatible endpoint serves. It must support tool calls for the assistant to look up the code pack and your results."),
		},
	},
});

const assistantIcon = registerIcon('saengine-ai-assistant-view-icon', Codicon.sparkle, localize('assistantViewIcon', "View icon of the AI Assistant."));

const container = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry).registerViewContainer({
	id: ASSISTANT_CONTAINER_ID,
	title: localize2('assistantContainer', "AI Assistant"),
	icon: assistantIcon,
	order: 5,
	hideIfEmpty: true,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [ASSISTANT_CONTAINER_ID, { mergeViewWithContainerWhenSingleView: true }]),
	storageId: ASSISTANT_CONTAINER_ID,
}, ViewContainerLocation.AuxiliaryBar);

Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry).registerViews([{
	id: ASSISTANT_VIEW_ID,
	name: localize2('assistantView', "AI Assistant"),
	containerIcon: assistantIcon,
	ctorDescriptor: new SyncDescriptor(AiAssistantView),
	canToggleVisibility: false,
	canMoveView: true,
	// Hidden while the component's state is not known yet (start-up).
	when: ContextKeyExpr.notEquals(AI_COMPONENT_KEY, 'unknown'),
}], container);

Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry).registerViewWelcomeContent(ASSISTANT_VIEW_ID, {
	content: localize('assistant.componentMissing', "The AI assistant is an optional component of the SAEngine setup and is not installed. AI assistants outside SAEngine can still connect (SAEngine: Allow AI Assistants to Control This Window).\n[Add AI Component...]({0})", addComponentLink('ai')),
	when: ContextKeyExpr.equals(AI_COMPONENT_KEY, 'missing'),
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.assistant.open',
			title: localize2('assistant.open', "Open AI Assistant"),
			metadata: { description: localize2('assistant.open.description', "Asks about BNBC 2020 (answers cite the code pack), explains results and proposes changes you preview and accept.") },
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IViewsService).openView(ASSISTANT_VIEW_ID, true);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: SET_KEY_COMMAND, title: localize2('assistant.setKeyCommand', "Set AI Assistant API Key..."), category, f1: true });
	}
	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(ISaengineAiAssistantService).setKey();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.ai.assistant.removeKey', title: localize2('assistant.removeKeyCommand', "Remove AI Assistant API Key"), category, f1: true });
	}
	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(ISaengineAiAssistantService).removeKey();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.ai.assistant.clear', title: localize2('assistant.clearCommand', "Clear AI Assistant Conversation"), category, f1: true });
	}
	override run(accessor: ServicesAccessor): void {
		accessor.get(ISaengineAiAssistantService).clear();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({ id: 'saengine.ai.assistant.resetConsent', title: localize2('assistant.resetConsentCommand', "Ask Again Before the AI Assistant Sends"), category, f1: true });
	}
	override run(accessor: ServicesAccessor): void {
		accessor.get(ISaengineAiAssistantService).resetConsent();
	}
});

/** Provider…: the provider, then its model (and the endpoint of an OpenAI-compatible one). */
registerAction2(class extends Action2 {
	constructor() {
		super({ id: CONFIGURE_COMMAND, title: localize2('assistant.configureCommand', "Choose AI Assistant Provider..."), category, f1: true });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const quickInputService = accessor.get(IQuickInputService);
		const configurationService = accessor.get(IConfigurationService);
		const assistant = accessor.get(ISaengineAiAssistantService);
		type ProviderItem = IQuickPickItem & { provider: AiProviderId };
		const current = configurationService.getValue<string>(PROVIDER_SETTING);
		const provider = await quickInputService.pick<ProviderItem>([
			{ provider: 'anthropic', label: localize('pick.anthropic', "Anthropic (Claude)"), description: current !== 'openaiCompatible' ? localize('pick.current', "current") : undefined, detail: localize('pick.anthropicDetail', "api.anthropic.com, with your Anthropic API key.") },
			{ provider: 'openaiCompatible', label: localize('pick.openai', "OpenAI-compatible endpoint"), description: current === 'openaiCompatible' ? localize('pick.current', "current") : undefined, detail: localize('pick.openaiDetail', "A self-hosted model (for example on this computer) or any service with the chat completions API.") },
		], { title: localize('pick.providerTitle', "AI Assistant Provider") });
		if (!provider) {
			return;
		}
		await configurationService.updateValue(PROVIDER_SETTING, provider.provider);
		if (provider.provider === 'anthropic') {
			const model = await quickInputService.pick(ANTHROPIC_MODELS.map(id => ({ label: id, picked: id === configurationService.getValue<string>(ANTHROPIC_MODEL_SETTING) })), { title: localize('pick.modelTitle', "Claude Model") });
			if (model) {
				await configurationService.updateValue(ANTHROPIC_MODEL_SETTING, model.label);
			}
		} else {
			const endpoint = await quickInputService.input({
				title: localize('pick.endpointTitle', "Endpoint Base URL"),
				value: configurationService.getValue<string>(OPENAI_ENDPOINT_SETTING) || 'http://localhost:11434/v1',
				prompt: localize('pick.endpointPrompt', "https, or http to this computer only. /chat/completions is added."),
				ignoreFocusLost: true,
			});
			if (endpoint === undefined) {
				return;
			}
			await configurationService.updateValue(OPENAI_ENDPOINT_SETTING, endpoint.trim());
			const model = await quickInputService.input({
				title: localize('pick.openaiModelTitle', "Model Name"),
				value: configurationService.getValue<string>(OPENAI_MODEL_SETTING) || '',
				prompt: localize('pick.openaiModelPrompt', "The model the endpoint serves; it must support tool calls."),
				ignoreFocusLost: true,
			});
			if (model !== undefined) {
				await configurationService.updateValue(OPENAI_MODEL_SETTING, model.trim());
			}
		}
		if (!await assistant.hasKey()) {
			await assistant.setKey();
		}
	}
});
