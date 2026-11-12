/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { decodeBase64 } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { Disposable, DisposableStore, IDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { MCP } from '../../../../platform/mcp/common/modelContextProtocol.js';
import { IChatService } from '../../chat/common/chatService/chatService.js';
import { IChatRequestModel } from '../../chat/common/model/chatModel.js';
import { ILanguageModelsService } from '../../chat/common/languageModels.js';
import { CountTokensCallback, ILanguageModelToolsService, IPreparedToolInvocation, IToolData, IToolImpl, IToolInvocation, IToolInvocationPreparationContext, IToolResult, ToolDataSource, ToolProgress } from '../../chat/common/tools/languageModelToolsService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { TOOL_SET_NAME } from '../common/aiAssistant.js';
import { chatTools, IAiTool, sendsProjectData } from '../common/aiTools.js';
import { IAiReview } from './aiActionTools.js';
import { ChangeSetSource } from './aiChangeSets.js';
import { chatDestination } from './aiChatConsent.js';
import { AiChatReview, UNDO_CHANGE_SET_COMMAND } from './aiChatReview.js';
import { ISaengineAiDataConsentService } from './aiDataConsent.js';

/*
 * SAEngine's tools in the chat (agent mode): the tools of aiTools.ts that the assistant may use,
 * registered as chat language-model tools in one tool set ("saengine"), each running on the same
 * tool runner as the MCP server. The chat adds what it needs around a call: the project's consent
 * before a tool sends project data to the chat's model provider, and the change-set review and
 * run confirmations in the chat answer itself (aiChatReview).
 */

/** Longest text of a tool result sent back to the model [characters]: a whole results file would fill the context. */
export const MAX_TOOL_RESULT = 60_000;

/** The runner the tools call: the window's (AiToolRunner); a fake one in tests. */
export interface IAiToolCaller {
	call(name: string, args: Record<string, unknown>, source: ChangeSetSource, review?: IAiReview): Promise<MCP.CallToolResult>;
}

/** The chat tool id of a SAEngine tool. */
export function chatToolId(name: string): string {
	return `saengine_${name}`;
}

export function toChatToolData(tool: IAiTool): IToolData {
	return {
		id: chatToolId(tool.name),
		toolReferenceName: tool.name,
		displayName: tool.title,
		userDescription: tool.title,
		modelDescription: tool.description,
		inputSchema: tool.inputSchema,
		source: ToolDataSource.Internal,
		icon: ThemeIcon.fromId(Codicon.symbolStructure.id),
		canBeReferencedInPrompt: true,
	};
}

/** A tool's MCP result as the chat's: text (cut at {@link MAX_TOOL_RESULT}) and images. */
export function toChatToolResult(result: MCP.CallToolResult): IToolResult {
	const content: IToolResult['content'] = [];
	for (const part of result.content) {
		if (part.type === 'text') {
			content.push({ kind: 'text', value: part.text.length > MAX_TOOL_RESULT ? `${part.text.slice(0, MAX_TOOL_RESULT)}\n[cut: the result was longer]` : part.text });
		} else if (part.type === 'image') {
			content.push({ kind: 'data', value: { mimeType: part.mimeType, data: decodeBase64(part.data) } });
		}
	}
	const error = result.isError ? content.map(p => p.kind === 'text' ? p.value : '').join('\n') || true : undefined;
	return { content, ...(error ? { toolResultError: error } : {}) };
}

/** One SAEngine tool in the chat. */
export class SaengineChatTool implements IToolImpl {

	constructor(
		private readonly tool: IAiTool,
		private readonly caller: IAiToolCaller,
		@IChatService private readonly chatService: IChatService,
		@ILanguageModelsService private readonly languageModelsService: ILanguageModelsService,
		@ISaengineAiDataConsentService private readonly dataConsent: ISaengineAiDataConsentService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
	) { }

	async prepareToolInvocation(_context: IToolInvocationPreparationContext, _token: CancellationToken): Promise<IPreparedToolInvocation | undefined> {
		const [running, done] = toolMessages(this.tool.name);
		return { invocationMessage: running, pastTenseMessage: done };
	}

	async invoke(invocation: IToolInvocation, _countTokens: CountTokensCallback, _progress: ToolProgress, token: CancellationToken): Promise<IToolResult> {
		// U2: nothing of the project goes to the chat's model provider before the engineer allows it.
		if (sendsProjectData(this.tool) && this.projectService.project) {
			const model = invocation.modelId ? this.languageModelsService.lookupLanguageModel(invocation.modelId) : undefined;
			if (!await this.dataConsent.ensure(chatDestination(model))) {
				return toChatToolResult({
					content: [{ type: 'text', text: 'The engineer has not allowed sending this project\'s data to this model provider (SAEngine: AI Data Sharing for This Project). Nothing was read; ask them to allow it.' }],
					isError: true,
				});
			}
		}
		const store = new DisposableStore();
		try {
			const request = this.request(invocation);
			const review = request ? store.add(this.instantiationService.createInstance(AiChatReview, request, token)) : undefined;
			const result = toChatToolResult(await this.caller.call(this.tool.name, invocation.parameters, 'assistant', review));
			if (review?.accepted.length) {
				const last = review.accepted[review.accepted.length - 1];
				result.toolResultMessage = new MarkdownString(localize('chatTool.applied', "Applied \"{0}\" (unsaved). [Undo]({1})", last.title.replace(/[[\]]/g, ''), `command:${UNDO_CHANGE_SET_COMMAND}?${encodeURIComponent(JSON.stringify([last.id]))}`), { isTrusted: { enabledCommands: [UNDO_CHANGE_SET_COMMAND] } });
			}
			return result;
		} finally {
			store.dispose();
		}
	}

	/** The chat request the call belongs to, where its review cards go. */
	private request(invocation: IToolInvocation): IChatRequestModel | undefined {
		const session = invocation.context?.sessionResource && this.chatService.getSession(invocation.context.sessionResource);
		if (!session) {
			return undefined;
		}
		const requests = session.getRequests();
		return (invocation.chatRequestId ? requests.find(r => r.id === invocation.chatRequestId) : undefined) ?? requests.at(-1);
	}
}

/** Registers SAEngine's tools and their tool set ("saengine") with the chat. */
export function registerChatTools(toolsService: ILanguageModelToolsService, instantiationService: IInstantiationService, caller: IAiToolCaller): IDisposable {
	const store = new DisposableStore();
	const toolSet = store.add(toolsService.createToolSet(ToolDataSource.Internal, 'saengine', TOOL_SET_NAME, {
		icon: ThemeIcon.fromId(Codicon.symbolStructure.id),
		description: localize('chatTools.setDescription', "SAEngine: build, change and explain the open project"),
	}));
	for (const tool of chatTools()) {
		const data = toChatToolData(tool);
		store.add(toolsService.registerTool(data, instantiationService.createInstance(SaengineChatTool, tool, caller)));
		store.add(toolSet.addTool(data));
	}
	return store;
}

/** A disposable holder for the registration, so a contribution can own it. */
export class SaengineChatToolsRegistration extends Disposable {
	constructor(caller: IAiToolCaller, @ILanguageModelToolsService toolsService: ILanguageModelToolsService, @IInstantiationService instantiationService: IInstantiationService) {
		super();
		this._register(registerChatTools(toolsService, instantiationService, caller));
	}
}

/** What the chat shows while a tool runs and after it ran. */
function toolMessages(name: string): [string, string] {
	switch (name) {
		case 'search_code': return [localize('tool.searchCode.running', "Looking up the code pack"), localize('tool.searchCode', "Looked up the code pack")];
		case 'explain_results': return [localize('tool.explainResults.running', "Reading the design checks"), localize('tool.explainResults', "Read the design checks")];
		case 'read_results': return [localize('tool.readResults.running', "Reading the results summary"), localize('tool.readResults', "Read the results summary")];
		case 'get_project': return [localize('tool.getProject.running', "Reading the project overview"), localize('tool.getProject', "Read the project overview")];
		case 'list_editors': return [localize('tool.listEditors.running', "Reading the open editors"), localize('tool.listEditors', "Read the list of open editors")];
		case 'read_active_document': return [localize('tool.readDocument.running', "Reading the open document"), localize('tool.readDocument', "Read the open document")];
		case 'screenshot': return [localize('tool.screenshot.running', "Taking a picture of the window"), localize('tool.screenshot', "Took a picture of the window")];
		case 'open_part': return [localize('tool.openPart.running', "Opening a part"), localize('tool.openPart', "Opened a part")];
		case 'open_file': return [localize('tool.openFile.running', "Opening a project file"), localize('tool.openFile', "Opened a project file")];
		case 'reveal_element': return [localize('tool.reveal.running', "Showing a member"), localize('tool.reveal', "Showed a member")];
		case 'propose_changes': return [localize('tool.proposeChanges.running', "Proposing a change set"), localize('tool.proposeChanges', "Proposed a change set")];
		case 'list_actions': return [localize('tool.listActions.running', "Reading the action catalogue"), localize('tool.listActions', "Read the action catalogue")];
		case 'describe_action': return [localize('tool.describeAction.running', "Reading an action's parameters"), localize('tool.describeAction', "Read an action's parameters")];
		case 'run_actions': return [localize('tool.runActions.running', "Working out the actions on the project"), localize('tool.runActions', "Ran actions on the project")];
		default: return [name, name];
	}
}
