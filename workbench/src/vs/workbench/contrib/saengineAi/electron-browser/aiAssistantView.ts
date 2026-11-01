/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/aiAssistant.css';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { renderMarkdown } from '../../../../base/browser/markdownRenderer.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IAiChangeSet, ISaengineAiChangeSetService } from '../browser/aiChangeSets.js';
import { previewPath, previewValue } from '../common/aiChangeSet.js';
import { OptionalScope } from '../common/aiTools.js';
import { componentContextKey } from '../../saengineUpdate/common/components.js';
import { IAssistantEntry, ISaengineAiAssistantService } from './aiAssistantService.js';

/** The commands the view's links run (registered in the contribution). */
export const SET_KEY_COMMAND = 'saengine.ai.assistant.setKey';
export const CONFIGURE_COMMAND = 'saengine.ai.assistant.configure';
/** The setup's `ai` component state (contrib/saengineUpdate `componentContextKey('ai')`). */
export const AI_COMPONENT_KEY = componentContextKey('ai');

/**
 * The AI Assistant view: what is sent and where (always visible above the input), the switches
 * for what the assistant may read, the change sets waiting for the engineer, and the
 * conversation.
 */
export class AiAssistantView extends ViewPane {

	private root!: HTMLElement;
	private destinationEl!: HTMLElement;
	private sendsEl!: HTMLElement;
	private changeSetsEl!: HTMLElement;
	private conversationEl!: HTMLElement;
	private input!: HTMLTextAreaElement;
	private sendButton!: Button;
	private readonly renderStore = this._register(new DisposableStore());
	private readonly changeSetStore = this._register(new DisposableStore());
	private readonly destinationStore = this._register(new DisposableStore());
	private keySet: boolean | undefined;

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@ISaengineAiAssistantService private readonly assistant: ISaengineAiAssistantService,
		@ISaengineAiChangeSetService private readonly changeSets: ISaengineAiChangeSetService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this._register(this.assistant.onDidChange(() => this.refresh()));
		this._register(this.changeSets.onDidChange(() => this.renderChangeSets()));
		// Without the setup's AI component the view says so and offers to add it.
		this._register(contextKeyService.onDidChangeContext(e => {
			if (e.affectsSome(new Set([AI_COMPONENT_KEY]))) {
				this._onDidChangeViewWelcomeState.fire();
			}
		}));
	}

	override shouldShowWelcome(): boolean {
		return this.contextKeyService.getContextKeyValue<string>(AI_COMPONENT_KEY) === 'missing';
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		this.root = append(container, $('.saengine-ai-assistant'));

		const header = append(this.root, $('.ai-header'));
		this.destinationEl = append(header, $('.ai-destination'));
		const scopes = append(header, $('.ai-scopes'));
		append(scopes, $('span.ai-scopes-label', undefined, localize('assistant.mayRead', "May read:")));
		this.scopeToggle(scopes, 'project', localize('scope.project', "Project overview"));
		this.scopeToggle(scopes, 'document', localize('scope.document', "Open document"));
		this.scopeToggle(scopes, 'results', localize('scope.results', "Results"));

		this.changeSetsEl = append(this.root, $('.ai-change-sets'));
		this.conversationEl = append(this.root, $('.ai-conversation'));
		this.conversationEl.setAttribute('role', 'log');
		this.conversationEl.setAttribute('aria-live', 'polite');

		const footer = append(this.root, $('.ai-footer'));
		this.sendsEl = append(footer, $('.ai-sends'));
		const row = append(footer, $('.ai-input-row'));
		this.input = append(row, $('textarea.ai-input')) as HTMLTextAreaElement;
		this.input.rows = 3;
		this.input.placeholder = localize('assistant.placeholder', "Ask about BNBC 2020, your results, or describe a change…");
		this.input.setAttribute('aria-label', localize('assistant.inputLabel', "Question for the AI assistant"));
		this._register(addDisposableListener(this.input, EventType.KEY_DOWN, e => {
			const event = new StandardKeyboardEvent(e);
			if (event.keyCode === KeyCode.Enter && !event.shiftKey) {
				event.preventDefault();
				this.submit();
			}
		}));
		this.sendButton = this._register(new Button(row, { ...defaultButtonStyles, title: localize('assistant.send', "Send") }));
		this._register(this.sendButton.onDidClick(() => this.assistant.busy ? this.assistant.cancel() : this.submit()));

		this.refresh();
		this.renderChangeSets();
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
		this.root.style.height = `${height}px`;
	}

	override focus(): void {
		super.focus();
		this.input?.focus();
	}

	private submit(): void {
		const text = this.input.value;
		if (!text.trim() || this.assistant.busy) {
			return;
		}
		this.input.value = '';
		void this.assistant.ask(text);
	}

	private scopeToggle(parent: HTMLElement, scope: OptionalScope, label: string): void {
		const wrapper = append(parent, $('label.ai-scope'));
		const box = append(wrapper, $('input')) as HTMLInputElement;
		box.type = 'checkbox';
		box.checked = this.assistant.scopes.has(scope);
		append(wrapper, $('span', undefined, label));
		this._register(addDisposableListener(box, EventType.CHANGE, () => this.assistant.setScope(scope, box.checked)));
	}

	private refresh(): void {
		if (!this.root) {
			return;
		}
		void this.assistant.hasKey().then(has => {
			if (has !== this.keySet) {
				this.keySet = has;
				this.renderDestination();
			}
		});
		this.renderDestination();
		this.renderSends();
		this.renderConversation();
		this.sendButton.label = this.assistant.busy ? localize('assistant.stop', "Stop") : localize('assistant.send', "Send");
	}

	private renderDestination(): void {
		this.destinationStore.clear();
		clearNode(this.destinationEl);
		const { provider, host, model } = this.assistant.destination();
		const providerName = provider === 'anthropic' ? localize('provider.anthropic', "Anthropic") : localize('provider.openai', "OpenAI-compatible");
		append(this.destinationEl, $('span.ai-dest-text', undefined, host
			? localize('assistant.destination', "To {0} ({1}, {2})", host, providerName, model || '?')
			: localize('assistant.noDestination', "No provider set")));
		this.link(this.destinationEl, localize('assistant.configure', "Provider…"), () => this.commandService.executeCommand(CONFIGURE_COMMAND), this.destinationStore);
		this.link(this.destinationEl, this.keySet ? localize('assistant.changeKey', "Key ✓") : localize('assistant.setKey', "Set Key…"), () => this.commandService.executeCommand(SET_KEY_COMMAND), this.destinationStore);
	}

	/** The indicator: exactly what goes with each question. */
	private renderSends(): void {
		clearNode(this.sendsEl);
		const scopes = this.assistant.scopes;
		const parts = [
			localize('sends.messages', "your messages"),
			localize('sends.code', "code pack passages"),
			...(scopes.has('project') ? [localize('sends.project', "project overview")] : []),
			...(scopes.has('document') ? [localize('sends.document', "open document")] : []),
			...(scopes.has('results') ? [localize('sends.results', "results")] : []),
		];
		const { host } = this.assistant.destination();
		this.sendsEl.textContent = localize('assistant.sends', "Sends to {0}: {1} — only after you agree.", host ?? '?', parts.join(' · '));
	}

	private renderConversation(): void {
		this.renderStore.clear();
		clearNode(this.conversationEl);
		const entries = this.assistant.entries;
		if (!entries.length) {
			append(this.conversationEl, $('.ai-empty', undefined, localize('assistant.empty', "Ask what BNBC 2020 requires (answers cite the code pack's clauses), why a member fails, or describe a change: changes come as a preview you accept or reject.")));
		}
		for (const entry of entries) {
			this.renderEntry(entry);
		}
		if (this.assistant.busy) {
			append(this.conversationEl, $('.ai-entry.ai-busy', undefined, localize('assistant.thinking', "Working…")));
		}
		this.conversationEl.scrollTop = this.conversationEl.scrollHeight;
	}

	private renderEntry(entry: IAssistantEntry): void {
		const element = append(this.conversationEl, $(`.ai-entry.ai-${entry.kind}`));
		switch (entry.kind) {
			case 'answer': {
				const rendered = this.renderStore.add(renderMarkdown(new MarkdownString(entry.text, { supportThemeIcons: false })));
				append(element, rendered.element);
				break;
			}
			case 'tool': {
				element.textContent = entry.text;
				if (entry.scope && entry.scope !== 'local') {
					append(element, $('span.ai-chip', undefined, scopeLabel(entry.scope)));
				}
				break;
			}
			case 'error': {
				element.textContent = entry.text;
				if (entry.action === 'setKey') {
					this.link(element, localize('assistant.setKeyAction', "Set API Key…"), () => this.commandService.executeCommand(SET_KEY_COMMAND), this.renderStore);
				} else if (entry.action === 'configure') {
					this.link(element, localize('assistant.configureAction', "Choose Provider…"), () => this.commandService.executeCommand(CONFIGURE_COMMAND), this.renderStore);
				}
				break;
			}
			default:
				element.textContent = entry.text;
		}
	}

	private renderChangeSets(): void {
		if (!this.changeSetsEl) {
			return;
		}
		this.changeSetStore.clear();
		clearNode(this.changeSetsEl);
		const sets = this.changeSets.changeSets.filter(set => set.state === 'pending' || set.state === 'accepted' || set.state === 'failed');
		for (const set of sets.slice(0, 5)) {
			this.renderChangeSet(set);
		}
		if (this.changeSets.changeSets.some(set => set.state !== 'pending')) {
			this.link(this.changeSetsEl, localize('changeSets.clear', "Clear decided change sets"), () => this.changeSets.clearDecided(), this.changeSetStore);
		}
	}

	private renderChangeSet(set: IAiChangeSet): void {
		const card = append(this.changeSetsEl, $(`.ai-change-set.ai-${set.state}`));
		const title = append(card, $('.ai-cs-title'));
		append(title, $('strong', undefined, set.title));
		append(title, $('span.ai-cs-source', undefined, set.source === 'mcp' ? localize('changeSet.fromMcp', "from an MCP client") : localize('changeSet.fromAssistant', "from the AI assistant")));
		const table = append(card, $('table.ai-cs-table'));
		const head = append(table, $('tr'));
		for (const label of [localize('cs.file', "File"), localize('cs.path', "Value"), localize('cs.before', "Before"), localize('cs.after', "After")]) {
			append(head, $('th', undefined, label));
		}
		for (const file of set.files) {
			for (const planned of file.changes) {
				const row = append(table, $('tr'));
				append(row, $('td.ai-cs-file', undefined, file.file));
				const path = append(row, $('td.ai-cs-path', undefined, previewPath(planned.change.path)));
				if (planned.change.reason) {
					path.title = planned.change.reason;
					append(path, $('.ai-cs-reason', undefined, planned.change.reason));
				}
				append(row, $('td', undefined, previewValue(planned.before, planned.existed)));
				append(row, $('td', undefined, planned.change.remove ? localize('cs.removed', "(removed)") : previewValue(planned.after)));
				if (planned.noop) {
					row.classList.add('ai-cs-noop');
				}
			}
		}
		const actions = append(card, $('.ai-cs-actions'));
		switch (set.state) {
			case 'pending': {
				const accept = this.changeSetStore.add(new Button(actions, { ...defaultButtonStyles }));
				accept.label = localize('changeSet.accept', "Accept");
				this.changeSetStore.add(accept.onDidClick(() => this.changeSets.accept(set.id)));
				const reject = this.changeSetStore.add(new Button(actions, { ...defaultButtonStyles, secondary: true }));
				reject.label = localize('changeSet.reject', "Reject");
				this.changeSetStore.add(reject.onDidClick(() => this.changeSets.reject(set.id)));
				append(actions, $('span.ai-cs-hint', undefined, localize('changeSet.hint', "Accepted, it is one step you can undo; save to keep it.")));
				break;
			}
			case 'accepted': {
				append(actions, $('span.ai-cs-state', undefined, localize('changeSet.accepted', "Applied (unsaved).")));
				if (this.changeSets.canUndo(set.id)) {
					const undo = this.changeSetStore.add(new Button(actions, { ...defaultButtonStyles, secondary: true }));
					undo.label = localize('changeSet.undo', "Undo");
					this.changeSetStore.add(undo.onDidClick(() => this.changeSets.undo(set.id)));
				}
				break;
			}
			case 'failed':
				append(actions, $('span.ai-cs-state', undefined, set.problem ?? localize('changeSet.failedShort', "Could not be applied.")));
				break;
		}
	}

	private link(parent: HTMLElement, label: string, run: () => unknown, store: DisposableStore): void {
		const link = append(parent, $('a.ai-link', { href: '#', role: 'button', tabIndex: 0 }, label));
		store.add(addDisposableListener(link, EventType.CLICK, e => {
			e.preventDefault();
			run();
		}));
	}
}

function scopeLabel(scope: string): string {
	switch (scope) {
		case 'code': return localize('chip.code', "sent: code pack passages");
		case 'project': return localize('chip.project', "sent: project overview");
		case 'document': return localize('chip.document', "sent: open document");
		case 'results': return localize('chip.results', "sent: results");
		default: return scope;
	}
}
