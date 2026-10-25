/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkbenchContribution, WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { Extensions as OutputExtensions, IOutputChannelRegistry, IOutputService } from '../../../services/output/common/output.js';
import { ALLOW_CONTROL_SETTING, PORT_SETTING } from '../common/aiTools.js';
import { AI_ACTIVITY_CHANNEL_ID, AiEditsAllowedContext, AiServerRunningContext, ISaengineAiService, MANAGE_AI_COMMAND, SaengineAiService } from './aiController.js';

const category = localize2('saengine.category', "SAEngine");

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengineAi',
	order: 101,
	title: localize('saengineAiConfigurationTitle', "SAEngine AI Assistants"),
	type: 'object',
	properties: {
		[ALLOW_CONTROL_SETTING]: {
			type: 'boolean',
			default: false,
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.allowControl', "Allow AI assistants to control this window: every SAEngine window starts a local MCP server (127.0.0.1 only) that an AI assistant such as Claude Code can connect to with the window's random token. Off by default; **SAEngine: Allow AI Assistants to Control This Window** turns it on for one session. Every action is listed in the **AI Activity** output."),
		},
		[PORT_SETTING]: {
			type: 'number',
			default: 0,
			minimum: 0,
			maximum: 65535,
			scope: ConfigurationScope.APPLICATION,
			restricted: true,
			markdownDescription: localize('saengine.ai.port', "The port of the AI assistant server on 127.0.0.1. 0 picks a free port each time; a fixed port keeps the address in the assistant's config the same (only the token changes). With several windows, only the first gets a fixed port."),
		},
	},
});

Registry.as<IOutputChannelRegistry>(OutputExtensions.OutputChannels).registerChannel({
	id: AI_ACTIVITY_CHANNEL_ID,
	label: localize('aiActivity', "AI Activity"),
	log: false,
});

registerSingleton(ISaengineAiService, SaengineAiService, InstantiationType.Delayed);

/** Starts the service with the window, so the setting or the dev switch take effect. */
class SaengineAiContribution implements IWorkbenchContribution {
	static readonly ID = 'workbench.contrib.saengineAi';
	constructor(@ISaengineAiService _service: ISaengineAiService) { }
}
registerWorkbenchContribution2(SaengineAiContribution.ID, SaengineAiContribution, WorkbenchPhase.AfterRestored);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.allowControl',
			title: localize2('saengine.ai.allow', "Allow AI Assistants to Control This Window"),
			metadata: { description: localize2('saengine.ai.allow.description', "Starts a local MCP server for this window (127.0.0.1, random token) until you stop it or close the window, and shows how to connect Claude Code or Claude Desktop.") },
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ISaengineAiService).showConnection();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.stop',
			title: localize2('saengine.ai.stop', "Stop AI Assistant Access"),
			category,
			f1: true,
			precondition: AiServerRunningContext,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ISaengineAiService).stop();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.showConnection',
			title: localize2('saengine.ai.showConnection', "Show AI Connection Details"),
			category,
			f1: true,
			precondition: AiServerRunningContext,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ISaengineAiService).showConnection();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.allowEdits',
			title: localize2('saengine.ai.allowEdits', "Allow AI Edits for This Session"),
			category,
			f1: true,
			precondition: ContextKeyExpr.and(AiServerRunningContext, AiEditsAllowedContext.negate()),
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ISaengineAiService).setEditsAllowed(true);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.disallowEdits',
			title: localize2('saengine.ai.disallowEdits', "Stop AI Edits"),
			category,
			f1: true,
			precondition: AiEditsAllowedContext,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ISaengineAiService).setEditsAllowed(false);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.ai.showActivity',
			title: localize2('saengine.ai.showActivity', "Show AI Activity"),
			category,
			f1: true,
		});
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IOutputService).showChannel(AI_ACTIVITY_CHANNEL_ID);
	}
});

/** The status bar item's menu. */
registerAction2(class extends Action2 {
	constructor() {
		super({ id: MANAGE_AI_COMMAND, title: localize2('saengine.ai.manage', "Manage AI Assistant Access"), category, f1: false });
	}
	override async run(accessor: ServicesAccessor): Promise<void> {
		const service = accessor.get(ISaengineAiService);
		const quickInputService = accessor.get(IQuickInputService);
		const outputService = accessor.get(IOutputService);
		type Item = IQuickPickItem & { run: () => unknown };
		const items: Item[] = [
			{ label: localize('manage.stop', "Disconnect and Stop AI Access"), detail: localize('manage.stop.detail', "The token stops working at once; Allow AI Assistants gives a new one."), run: () => service.stop() },
			service.editsAllowed
				? { label: localize('manage.disallowEdits', "Stop AI Edits"), run: () => service.setEditsAllowed(false) }
				: { label: localize('manage.allowEdits', "Allow AI Edits for This Session"), detail: localize('manage.allowEdits.detail', "The assistant may change the project: undoable, and unsaved until you save."), run: () => service.setEditsAllowed(true) },
			{ label: localize('manage.connection', "Show Connection Details"), run: () => service.showConnection() },
			{ label: localize('manage.activity', "Show AI Activity"), run: () => outputService.showChannel(AI_ACTIVITY_CHANNEL_ID) },
		];
		const picked = await quickInputService.pick(items, { placeHolder: localize('manage.placeholder', "AI assistant access to this window") });
		await picked?.run();
	}
});
