/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { CancellationToken } from '../../../../../base/common/cancellation.js';
import { Event } from '../../../../../base/common/event.js';
import { IMarkdownString } from '../../../../../base/common/htmlContent.js';
import { DisposableStore } from '../../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../../base/common/resources.js';
import { mock } from '../../../../../base/test/common/mock.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IAccessibilityService } from '../../../../../platform/accessibility/common/accessibility.js';
import { TestAccessibilityService } from '../../../../../platform/accessibility/test/common/testAccessibilityService.js';
import { IAccessibilitySignalService } from '../../../../../platform/accessibilitySignal/browser/accessibilitySignalService.js';
import { ICommandService } from '../../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../../platform/configuration/common/configuration.js';
import { TestConfigurationService } from '../../../../../platform/configuration/test/common/testConfigurationService.js';
import { IContextKeyService } from '../../../../../platform/contextkey/common/contextkey.js';
import { IDialogService } from '../../../../../platform/dialogs/common/dialogs.js';
import { TestDialogService } from '../../../../../platform/dialogs/test/common/testDialogService.js';
import { TestInstantiationService } from '../../../../../platform/instantiation/test/common/instantiationServiceMock.js';
import { ContextKeyService } from '../../../../../platform/contextkey/browser/contextKeyService.js';
import { ILogService, NullLogService } from '../../../../../platform/log/common/log.js';
import { MCP } from '../../../../../platform/mcp/common/modelContextProtocol.js';
import { InMemoryStorageService, IStorageService } from '../../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../../platform/telemetry/common/telemetry.js';
import { NullTelemetryService } from '../../../../../platform/telemetry/common/telemetryUtils.js';
import { IExtensionService, NullExtensionService } from '../../../../services/extensions/common/extensions.js';
import { ISaengineProject, ISaengineProjectService } from '../../../../services/saengineProject/common/saengineProject.js';
import { ActionKind } from '../../../../services/saengineProject/common/saengineActions.js';
import { actionsWindow, FLOOR_PLAN_FILE } from '../../../../services/saengineProject/test/browser/actionsFixture.js';
import { IChatWidgetService } from '../../../chat/browser/chat.js';
import { IChatToolRiskAssessmentService } from '../../../chat/browser/tools/chatToolRiskAssessmentService.js';
import { LanguageModelToolsService } from '../../../chat/browser/tools/languageModelToolsService.js';
import { IChatService } from '../../../chat/common/chatService/chatService.js';
import { ILanguageModelsService } from '../../../chat/common/languageModels.js';
import { ChatModel } from '../../../chat/common/model/chatModel.js';
import { ChatElicitationRequestPart } from '../../../chat/common/model/chatProgressTypes/chatElicitationRequestPart.js';
import { LocalChatSessionUri } from '../../../chat/common/model/chatUri.js';
import { ILanguageModelToolsConfirmationService } from '../../../chat/common/tools/languageModelToolsConfirmationService.js';
import { isToolSet, IToolInvocation, IToolResult } from '../../../chat/common/tools/languageModelToolsService.js';
import { IToolResultCompressor } from '../../../chat/common/tools/toolResultCompressor.js';
import { MockChatService } from '../../../chat/test/common/chatService/mockChatService.js';
import { MockLanguageModelToolsConfirmationService } from '../../../chat/test/common/tools/mockLanguageModelToolsConfirmationService.js';
import { TOOL_SET_NAME } from '../../common/aiAssistant.js';
import { chatTools } from '../../common/aiTools.js';
import { AiActionTools, IAiReview } from '../../browser/aiActionTools.js';
import { ISaengineAiChangeSetService, SaengineAiChangeSetService } from '../../browser/aiChangeSets.js';
import { chatDestination, chatDestinationId, withholdRequest } from '../../browser/aiChatConsent.js';
import { UNDO_CHANGE_SET_COMMAND } from '../../browser/aiChatReview.js';
import { chatToolId, IAiToolCaller, registerChatTools } from '../../browser/aiChatTools.js';
import { IAiDataDestination, ISaengineAiDataConsentService } from '../../browser/aiDataConsent.js';

const SESSION = 'saengine-session';

/** The engineer's answers to the consent dialog, and what they were asked. */
class FakeConsent extends mock<ISaengineAiDataConsentService>() {
	answer = true;
	readonly asked: IAiDataDestination[] = [];
	override readonly onDidChange = Event.None;
	override async ensure(destination: IAiDataDestination): Promise<boolean> {
		this.asked.push(destination);
		return this.answer;
	}
}

/** The chat with SAEngine's tools registered on the chat's tool service, a fake model calling them. */
function chatWindow(store: Pick<DisposableStore, 'add'>, caller: IAiToolCaller, options: { readonly project: ISaengineProjectService; readonly changeSets?: ISaengineAiChangeSetService }) {
	const instantiation = store.add(new TestInstantiationService());
	const configurationService = new TestConfigurationService();
	const chatService = new MockChatService();
	const consent = new FakeConsent();
	instantiation.stub(IConfigurationService, configurationService);
	instantiation.stub(IContextKeyService, store.add(new ContextKeyService(configurationService)));
	instantiation.stub(IExtensionService, new NullExtensionService());
	instantiation.stub(IChatService, chatService);
	instantiation.stub(IDialogService, new TestDialogService());
	instantiation.stub(ITelemetryService, NullTelemetryService);
	instantiation.stub(ILogService, new NullLogService());
	instantiation.stub(IAccessibilityService, new TestAccessibilityService());
	instantiation.stub(IAccessibilitySignalService, { playSignal: async () => { } } as unknown as IAccessibilitySignalService);
	instantiation.stub(IStorageService, store.add(new InMemoryStorageService()));
	instantiation.stub(ILanguageModelToolsConfirmationService, new MockLanguageModelToolsConfirmationService());
	instantiation.stub(ICommandService, { executeCommand: async () => undefined } as unknown as ICommandService);
	instantiation.stub(IChatWidgetService, { getWidgetBySessionResource: () => undefined, lastFocusedWidget: undefined } as unknown as IChatWidgetService);
	instantiation.stub(IToolResultCompressor, { _serviceBrand: undefined, registerFilter: () => { }, registerCache: () => { }, maybeCompress: () => undefined });
	instantiation.stub(IChatToolRiskAssessmentService, { _serviceBrand: undefined, isEnabled: () => false, getCached: () => undefined, assess: async () => undefined });
	instantiation.stub(ILanguageModelsService, { lookupLanguageModel: (id: string) => id === 'claude' ? { vendor: 'anthropic', name: 'Claude Opus 5.5' } : undefined } as unknown as ILanguageModelsService);
	instantiation.stub(ISaengineAiDataConsentService, consent);
	instantiation.stub(ISaengineProjectService, options.project);
	if (options.changeSets) {
		instantiation.stub(ISaengineAiChangeSetService, options.changeSets);
	}
	const tools = store.add(instantiation.createInstance(LanguageModelToolsService));
	store.add(registerChatTools(tools, instantiation, caller));

	// The chat session the model answers in; the engineer answers SAEngine's cards in it.
	const cards: ChatElicitationRequestPart[] = [];
	let engineer: (card: ChatElicitationRequestPart) => void = () => { };
	chatService.addSession({ sessionId: SESSION, sessionResource: LocalChatSessionUri.forSession(SESSION), getRequests: () => [{ id: 'request', modelId: 'claude' }] } as unknown as ChatModel);
	chatService.appendProgress = (_request, progress) => {
		if (progress instanceof ChatElicitationRequestPart) {
			cards.push(progress);
			engineer(progress);
		}
	};
	let call = 0;
	/** One tool call of the model, through the chat's tool service. */
	const invoke = (name: string, parameters: Record<string, unknown>): Promise<IToolResult> => tools.invokeTool({
		callId: `call${++call}`,
		toolId: chatToolId(name),
		parameters,
		modelId: 'claude',
		context: { sessionResource: LocalChatSessionUri.forSession(SESSION) },
	} satisfies IToolInvocation, async () => 0, CancellationToken.None);
	return { tools, consent, cards, invoke, answerWith: (answer: typeof engineer) => engineer = answer };
}

function textOf(result: IToolResult): string {
	return result.content.map(part => part.kind === 'text' ? part.value : '').join('\n');
}

const OPEN_PROJECT = new class extends mock<ISaengineProjectService>() {
	override readonly project = { name: 'Plot', type: 'building' } as ISaengineProject;
};

suite('SAEngine - AI in the chat', () => {

	const store = ensureNoDisposablesAreLeakedInTestSuite();

	test('SAEngine\'s tools are chat tools in the "saengine" tool set, and run on the shared tool runner', async () => {
		const calls: [string, Record<string, unknown>, string][] = [];
		const caller: IAiToolCaller = {
			call: async (name, args, source) => {
				calls.push([name, args, source]);
				return name === 'screenshot'
					? { content: [{ type: 'image', data: 'iVBORw0KGgo=', mimeType: 'image/png' }] }
					: { content: [{ type: 'text', text: `${name} answered` }] };
			},
		};
		const chat = chatWindow(store, caller, { project: OPEN_PROJECT });

		const registered = [...chat.tools.getAllToolsIncludingDisabled()].filter(tool => tool.id.startsWith('saengine_'));
		assert.deepStrictEqual(registered.map(tool => tool.id).sort(), chatTools().map(tool => chatToolId(tool.name)).sort());
		assert.ok(!registered.some(tool => tool.id === 'saengine_run_command' || tool.id === 'saengine_annotate_drawings'));
		const toolSet = chat.tools.getToolSetByName(TOOL_SET_NAME);
		assert.ok(toolSet);
		assert.strictEqual([...toolSet.getTools()].length, chatTools().length);
		assert.strictEqual(chat.tools.getTool('saengine_describe_action')?.modelDescription, chatTools().find(t => t.name === 'describe_action')?.description);
		// The SAEngine agent's `tools: ["saengine"]` turns on exactly these tools.
		const enabled = [...chat.tools.toToolAndToolSetEnablementMap([TOOL_SET_NAME], undefined)].filter(([item, on]) => on && !isToolSet(item)).map(([item]) => item.id);
		assert.deepStrictEqual(enabled.sort(), registered.map(tool => tool.id).sort());

		const described = await chat.invoke('describe_action', { name: 'columns.place' });
		assert.strictEqual(textOf(described), 'describe_action answered');
		const picture = await chat.invoke('screenshot', {});
		assert.deepStrictEqual(picture.content.map(part => part.kind === 'data' ? part.value.mimeType : part.kind), ['image/png']);
		assert.deepStrictEqual(calls.map(([name, args, source]) => [name, args, source]), [['describe_action', { name: 'columns.place' }, 'assistant'], ['screenshot', {}, 'assistant']]);
	});

	test('tools that send project data ask the project\'s consent for the chat\'s model provider first', async () => {
		const calls: string[] = [];
		const caller: IAiToolCaller = { call: async name => { calls.push(name); return { content: [{ type: 'text', text: 'ok' }] }; } };
		const chat = chatWindow(store, caller, { project: OPEN_PROJECT });

		chat.consent.answer = false;
		const refused = await chat.invoke('get_project', {});
		assert.match(textOf(refused), /has not allowed sending this project's data/);
		assert.ok(refused.toolResultError);
		assert.deepStrictEqual(calls, []);
		assert.strictEqual(chat.consent.asked[0].id, 'anthropic|api.anthropic.com');
		assert.match(chat.consent.asked[0].receiver, /Anthropic \(api\.anthropic\.com\), model Claude Opus 5\.5/);

		// Code pack passages and the catalogue hold no project data: no question.
		await chat.invoke('search_code', { query: 'minimum cover' });
		assert.strictEqual(chat.consent.asked.length, 1);

		chat.consent.answer = true;
		assert.strictEqual(textOf(await chat.invoke('explain_results', { onlyFailing: true })), 'ok');
		assert.deepStrictEqual(calls, ['search_code', 'explain_results']);

		// Before a request goes out at all: withheld only with a project open and no consent.
		const copilot = { vendor: 'copilot', name: 'GPT' };
		chat.consent.answer = false;
		assert.strictEqual(await withholdRequest(true, copilot, chat.consent), true);
		assert.strictEqual(chat.consent.asked.at(-1)?.id, 'copilot|api.githubcopilot.com');
		const asked = chat.consent.asked.length;
		assert.strictEqual(await withholdRequest(false, copilot, chat.consent), false);
		assert.strictEqual(chat.consent.asked.length, asked);
		chat.consent.answer = true;
		assert.strictEqual(await withholdRequest(true, copilot, chat.consent), false);

		// Each provider is its own destination (Copilot, a self-hosted endpoint, none picked yet).
		assert.strictEqual(chatDestinationId({ vendor: 'copilot', name: 'GPT' }), 'copilot|api.githubcopilot.com');
		assert.strictEqual(chatDestinationId({ vendor: 'customendpoint', name: 'Qwen3' }), 'customendpoint|qwen3');
		assert.strictEqual(chatDestination(undefined).id, 'chat');
	});

	test('a fake model builds in the chat: the change set is reviewed in the chat, accepted, undone; Run All asks first', async () => {
		const window = await actionsWindow(store, { project: false });
		const changeSets = store.add(new SaengineAiChangeSetService(window.projectService, window.textModels, window.fileService, window.textModels.undoRedo, window.commandService));
		const notInChat: IAiReview = {
			showChangeSet: () => { throw new Error('the chat\'s change sets are reviewed in the chat'); },
			confirmRun: () => { throw new Error('the chat\'s runs are confirmed in the chat'); },
		};
		const actions = new AiActionTools(notInChat, 5000, window.service, changeSets);
		const caller: IAiToolCaller = {
			call: async (name, args, source, review): Promise<MCP.CallToolResult> => {
				switch (name) {
					case 'list_actions': return actions.listActions(args.kind as ActionKind | undefined);
					case 'run_actions': return actions.runActions(args, source, review);
				}
				throw new Error(name);
			},
		};
		const chat = chatWindow(store, caller, { project: window.projectService, changeSets });
		const planText = async () => (await window.textModels.createModelReference(joinPath(window.root, ...FLOOR_PLAN_FILE.split('/')))).object.textEditorModel.getValue();

		// The model reads the catalogue and creates the project in the empty folder: the engineer agrees in the chat.
		assert.match(textOf(await chat.invoke('list_actions', {})), /"grid\.set"/);
		chat.answerWith(card => void card.accept(true));
		const created = JSON.parse(textOf(await chat.invoke('run_actions', { steps: [{ action: 'project.create', params: { name: 'Plot' } }] })));
		assert.strictEqual(created.ok, true);
		assert.match(String(chat.cards[0].title), /Save the project and run project\.create/);
		const before = await planText();

		// Then the geometry: the engineer sees the change set in the chat and accepts it.
		const geometry = [
			{ action: 'grid.set', params: { x: [6000, 6000], y: [5000] } },
			{ action: 'storeys.set', params: { heights: [3200, 3000, 3000] } },
		];
		const accepted = await chat.invoke('run_actions', { title: 'Grid and storeys', steps: geometry });
		assert.strictEqual(JSON.parse(textOf(accepted)).decision, 'accepted');
		const card = chat.cards[1];
		assert.match(String(card.title), /Change set: Grid and storeys/);
		assert.match((card.message as IMarkdownString).value, /\| Before \| After \|/);
		assert.match((card.message as IMarkdownString).value, /stories/);
		assert.strictEqual(card.state.get(), 'accepted');
		const set = changeSets.changeSets[0];
		assert.strictEqual(set.state, 'accepted');
		assert.notStrictEqual(await planText(), before);
		// The chat offers Undo for it, and Undo takes the whole set back.
		const message = accepted.toolResultMessage as IMarkdownString;
		assert.ok(message.value.includes(`command:${UNDO_CHANGE_SET_COMMAND}?${encodeURIComponent(JSON.stringify([set.id]))}`), message.value);
		assert.ok(changeSets.canUndo(set.id));
		await changeSets.undo(set.id);
		assert.strictEqual(await planText(), before);

		// A rejected set changes nothing.
		chat.answerWith(card => void card.reject?.());
		const rejected = await chat.invoke('run_actions', { title: 'Grid and storeys', steps: geometry });
		assert.strictEqual(JSON.parse(textOf(rejected)).decision, 'rejected');
		assert.strictEqual(await planText(), before);

		// Run All is confirmed in the chat: Cancel runs nothing.
		const runAll = { title: 'Run All', steps: [{ action: 'run.all' }] };
		const declined = await chat.invoke('run_actions', runAll);
		assert.strictEqual(JSON.parse(textOf(declined)).decision, 'declined');
		assert.match(String(chat.cards.at(-1)?.title), /Save the project and run run\.all/);
		chat.answerWith(card => void card.accept(true));
		const ran = JSON.parse(textOf(await chat.invoke('run_actions', runAll)));
		assert.strictEqual(ran.ok, true);
		assert.ok(!ran.decision);
	});
});
