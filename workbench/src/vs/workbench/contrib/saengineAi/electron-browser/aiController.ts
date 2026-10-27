/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { join } from '../../../../base/common/path.js';
import { process } from '../../../../base/parts/sandbox/electron-browser/globals.js';
import { IServerChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { localize } from '../../../../nls.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService, RawContextKey, IContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { createDecorator, IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { ISharedProcessService } from '../../../../platform/ipc/electron-browser/services.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { MCP } from '../../../../platform/mcp/common/modelContextProtocol.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { ISaengineAiClientEvent, ISaengineAiServerInfo, ISaengineAiStartOptions, SAENGINE_AI_BROKER_CHANNEL, SAENGINE_AI_CHANNEL } from '../../../../platform/saengine/common/saengineAi.js';
import { INativeWorkbenchEnvironmentService } from '../../../services/environment/electron-browser/environmentService.js';
import { IOutputService } from '../../../services/output/common/output.js';
import { IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { ALLOW_CONTROL_SETTING, PORT_SETTING, toMcpTool, visibleTools } from '../common/aiTools.js';
import { AiToolRunner } from './aiToolRunner.js';
import { TIME, formatDate } from '../../../services/saengineProject/common/formatting.js';

export const AI_ACTIVITY_CHANNEL_ID = 'saengine.aiActivity';
export const MANAGE_AI_COMMAND = 'saengine.ai.manage';

/** The server of this window is listening. */
export const AiServerRunningContext = new RawContextKey<boolean>('saengineAiRunning', false);
/** The assistant may edit the project (this session). */
export const AiEditsAllowedContext = new RawContextKey<boolean>('saengineAiEditsAllowed', false);

/** Dev launch: `SAENGINE_AI=1 scripts/code.bat` starts the server and writes the connection file. */
const DEV_ENV = 'SAENGINE_AI';

export const ISaengineAiService = createDecorator<ISaengineAiService>('saengineAiService');

export interface ISaengineAiService {
	readonly _serviceBrand: undefined;
	readonly info: ISaengineAiServerInfo | undefined;
	readonly editsAllowed: boolean;
	readonly onDidChange: Event<void>;
	start(): Promise<ISaengineAiServerInfo | undefined>;
	stop(): Promise<void>;
	setEditsAllowed(allowed: boolean): Promise<void>;
	showConnection(): Promise<void>;
	/** The exact config lines for the clients. */
	claudeCodeCommand(info: ISaengineAiServerInfo): string;
	claudeDesktopConfig(info: ISaengineAiServerInfo): string;
}

/**
 * The window's side of the AI assistant server: starts and stops it in the shared process, runs
 * the tool calls (AiToolRunner), logs every call in "AI Activity", and shows its state in the
 * status bar. Nothing listens until the engineer allows it.
 */
export class SaengineAiService extends Disposable implements ISaengineAiService {

	declare readonly _serviceBrand: undefined;

	private _info: ISaengineAiServerInfo | undefined;
	get info() { return this._info; }
	private _editsAllowed = false;
	get editsAllowed() { return this._editsAllowed; }
	private client: string | undefined;
	private rejectedShown = false;
	private starting: Promise<ISaengineAiServerInfo | undefined> | undefined;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	private readonly runner: AiToolRunner;
	private readonly statusEntry = this._register(new MutableDisposable<IStatusbarEntryAccessor>());
	private readonly runningKey: IContextKey<boolean>;
	private readonly editsKey: IContextKey<boolean>;

	constructor(
		@ISharedProcessService private readonly sharedProcessService: ISharedProcessService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@INotificationService private readonly notificationService: INotificationService,
		@IDialogService private readonly dialogService: IDialogService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@IOutputService private readonly outputService: IOutputService,
		@IProductService private readonly productService: IProductService,
		@INativeWorkbenchEnvironmentService private readonly environmentService: INativeWorkbenchEnvironmentService,
		@INativeHostService private readonly nativeHostService: INativeHostService,
		@ILogService private readonly logService: ILogService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		super();
		this.runner = instantiationService.createInstance(AiToolRunner, () => this._editsAllowed);
		this.runningKey = AiServerRunningContext.bindTo(contextKeyService);
		this.editsKey = AiEditsAllowedContext.bindTo(contextKeyService);
		this.sharedProcessService.registerChannel(SAENGINE_AI_BROKER_CHANNEL, this.brokerChannel());

		this._register(configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(ALLOW_CONTROL_SETTING)) {
				void (configurationService.getValue<boolean>(ALLOW_CONTROL_SETTING) ? this.start() : this.stop());
			}
		}));
		if (configurationService.getValue<boolean>(ALLOW_CONTROL_SETTING) || this.devLaunch) {
			void this.start();
		}
	}

	/** Only a development build reads the environment switch; a release needs the setting or the command. */
	private get devLaunch(): boolean {
		return !this.environmentService.isBuilt && process.env[DEV_ENV] === '1';
	}

	private brokerChannel(): IServerChannel<string> {
		return {
			listen: <T>(_: unknown, event: string): Event<T> => { throw new Error(`Invalid listen: ${event}`); },
			call: async <T>(_: unknown, command: string, arg?: unknown): Promise<T> => {
				switch (command) {
					case 'listTools': return visibleTools(this._editsAllowed).map(toMcpTool) as T;
					case 'callTool': {
						const { name, args } = arg as { name: string; args: Record<string, unknown> };
						return await this.callTool(name, args ?? {}) as T;
					}
					case 'clientEvent': this.onClientEvent(arg as ISaengineAiClientEvent); return undefined as T;
				}
				throw new Error(`Invalid call: ${command}`);
			},
		};
	}

	private async callTool(name: string, args: Record<string, unknown>): Promise<MCP.CallToolResult> {
		if (!this._info) {
			// The server was stopped while the request was on its way.
			return { content: [{ type: 'text', text: 'AI access to this window was turned off.' }], isError: true };
		}
		const started = Date.now();
		const result = await this.runner.call(name, args);
		const summary = result.isError
			? localize('activity.failed', "failed: {0}", textOf(result))
			: localize('activity.ok', "ok");
		this.log(localize('activity.tool', "{0}({1}) {2} [{3} ms]", name, shorten(JSON.stringify(args)), summary, Date.now() - started));
		return result;
	}

	private onClientEvent(event: ISaengineAiClientEvent): void {
		switch (event.kind) {
			case 'connected': {
				this.client = event.client ?? localize('unknownClient', "an AI assistant");
				this.log(localize('activity.connected', "{0} connected.", this.client));
				this.notificationService.notify({
					severity: Severity.Info,
					message: localize('connected', "{0} connected to this window and can now use SAEngine here. Every action is listed in AI Activity.", this.client),
					actions: {
						primary: [
							{ id: 'saengine.ai.showActivity', label: localize('showActivity', "Show AI Activity"), tooltip: '', class: undefined, enabled: true, run: () => this.outputService.showChannel(AI_ACTIVITY_CHANNEL_ID) },
							{ id: 'saengine.ai.stopNow', label: localize('stopAccess', "Stop AI Access"), tooltip: '', class: undefined, enabled: true, run: () => this.stop() },
						],
					},
				});
				break;
			}
			case 'disconnected':
				this.log(localize('activity.disconnected', "An AI assistant disconnected."));
				break;
			case 'rejected':
				this.log(localize('activity.rejected', "Refused a request ({0}): wrong or missing token, or not from a local program.", event.reason ?? '?'));
				if (!this.rejectedShown) {
					this.rejectedShown = true;
					this.notificationService.notify({ severity: Severity.Warning, message: localize('rejected', "SAEngine refused a connection to the AI server of this window (wrong token or not a local program). See AI Activity.") });
				}
				break;
		}
		this.updateStatus();
		this._onDidChange.fire();
	}

	start(): Promise<ISaengineAiServerInfo | undefined> {
		if (this._info) {
			return Promise.resolve(this._info);
		}
		this.starting ??= this.doStart().finally(() => this.starting = undefined);
		return this.starting;
	}

	private async doStart(): Promise<ISaengineAiServerInfo | undefined> {
		const options: ISaengineAiStartOptions = {
			port: this.configurationService.getValue<number>(PORT_SETTING) || 0,
			connectionFile: this.devLaunch ? join(this.environmentService.userDataPath, `saengine-ai-window-${this.nativeHostService.windowId}.json`) : undefined,
			version: this.productService.version,
			instructions: INSTRUCTIONS,
		};
		try {
			this._info = await this.sharedProcessService.getChannel(SAENGINE_AI_CHANNEL).call<ISaengineAiServerInfo>('start', options);
		} catch (error) {
			this.logService.error('[saengineAi] could not start the server', error);
			this.notificationService.error(localize('startFailed', "The AI assistant server could not start: {0}", error instanceof Error ? error.message : String(error)));
			return undefined;
		}
		this.client = undefined;
		this.rejectedShown = false;
		this.runningKey.set(true);
		this.log(localize('activity.started', "AI assistants may control this window at {0} (token required).", this._info.url));
		if (this.devLaunch) {
			console.log(`[SAEngine AI] window ${this.nativeHostService.windowId}: ${this._info.url} token ${this._info.token} (also in ${options.connectionFile})`);
		}
		this.updateStatus();
		this._onDidChange.fire();
		return this._info;
	}

	async stop(): Promise<void> {
		if (!this._info) {
			return;
		}
		this._info = undefined;
		this.client = undefined;
		this._editsAllowed = false;
		this.runningKey.set(false);
		this.editsKey.set(false);
		try {
			await this.sharedProcessService.getChannel(SAENGINE_AI_CHANNEL).call('stop');
		} catch (error) {
			this.logService.warn(`[saengineAi] could not stop the server: ${error}`);
		}
		this.log(localize('activity.stopped', "AI access to this window stopped; the token no longer works."));
		this.updateStatus();
		this._onDidChange.fire();
	}

	async setEditsAllowed(allowed: boolean): Promise<void> {
		if (allowed === this._editsAllowed || (allowed && !this._info)) {
			return;
		}
		this._editsAllowed = allowed;
		this.editsKey.set(allowed);
		this.log(allowed
			? localize('activity.editsOn', "Edits allowed for this session: the assistant may change the project (undoable, unsaved until you save).")
			: localize('activity.editsOff', "Edits no longer allowed."));
		await this.sharedProcessService.getChannel(SAENGINE_AI_CHANNEL).call('toolsChanged').catch(() => undefined);
		this.updateStatus();
		this._onDidChange.fire();
	}

	claudeCodeCommand(info: ISaengineAiServerInfo): string {
		return `claude mcp add --transport http saengine ${info.url} --header "Authorization: Bearer ${info.token}"`;
	}

	claudeDesktopConfig(info: ISaengineAiServerInfo): string {
		return JSON.stringify({
			mcpServers: {
				saengine: {
					command: 'npx',
					args: ['-y', 'mcp-remote', info.url, '--header', 'Authorization:${SAENGINE_AUTH}'],
					env: { SAENGINE_AUTH: `Bearer ${info.token}` },
				},
			},
		}, undefined, 2);
	}

	async showConnection(): Promise<void> {
		const info = this._info ?? await this.start();
		if (!info) {
			return;
		}
		const claudeCode = this.claudeCodeCommand(info);
		await this.dialogService.prompt({
			type: Severity.Info,
			message: localize('connection.title', "AI assistants may control this window"),
			detail: localize('connection.detail', "An MCP client on this computer (Claude Code, Claude Desktop, ...) can now connect to SAEngine with this window's token. The token works until you stop AI access or close the window; keep it private.\n\nAddress: {0}\nToken: {1}\n\nClaude Code (run in a terminal):\n{2}\n\nClaude Desktop: copy the config into claude_desktop_config.json (needs Node.js; see docs/ai-assistants.md).", info.url, info.token, claudeCode),
			buttons: [
				{ label: localize('copyClaudeCode', "Copy Claude Code Command"), run: () => this.clipboardService.writeText(claudeCode) },
				{ label: localize('copyClaudeDesktop', "Copy Claude Desktop Config"), run: () => this.clipboardService.writeText(this.claudeDesktopConfig(info)) },
				{ label: localize('copyToken', "Copy Token"), run: () => this.clipboardService.writeText(info.token) },
			],
			cancelButton: localize('close', "Close"),
		});
	}

	private updateStatus(): void {
		if (!this._info) {
			this.statusEntry.clear();
			return;
		}
		const label = this.client
			? (this._editsAllowed ? localize('status.connectedEdits', "AI connected · edits") : localize('status.connected', "AI connected"))
			: (this._editsAllowed ? localize('status.allowedEdits', "AI allowed · edits") : localize('status.allowed', "AI allowed"));
		const text = `$(plug) ${label}`;
		const tooltip = this.client
			? localize('status.connectedTooltip', "{0} is connected to this window. Click to disconnect, allow edits or see its activity.", this.client)
			: localize('status.allowedTooltip', "AI assistants may connect to this window (127.0.0.1, token required). Click to disable or show the connection details.");
		const entry = { name: localize('status.name', "AI Assistant Access"), text, ariaLabel: tooltip, tooltip, command: MANAGE_AI_COMMAND, kind: this._editsAllowed ? 'warning' as const : 'prominent' as const };
		if (this.statusEntry.value) {
			this.statusEntry.value.update(entry);
		} else {
			this.statusEntry.value = this.statusbarService.addEntry(entry, 'saengine.ai.status', StatusbarAlignment.RIGHT, 1000);
		}
	}

	private log(line: string): void {
		const time = formatDate(Date.now(), TIME);
		this.outputService.getChannel(AI_ACTIVITY_CHANNEL_ID)?.append(`[${time}] ${line}\n`);
	}

	override dispose(): void {
		void this.stop();
		super.dispose();
	}
}

/** What the assistant is told at initialize. */
const INSTRUCTIONS = [
	'You are connected to one window of SAEngine, a structural engineering desktop app (soil report, floor plan, FEM analysis and design, substructure, BOQ, drawings).',
	'Start with get_project to see the project and the status of each part. Use show_message to tell the engineer what you are about to do; they are watching the window.',
	'Commands run exactly as from the menus (run_command, see list_commands). Edits to the model are off unless the engineer allows them; edits are undoable and stay unsaved until the engineer saves.',
	'Every call is listed in the window\'s "AI Activity" output. Never claim a design is adequate without the design results (read_results "design").',
].join(' ');

function textOf(result: MCP.CallToolResult): string {
	const first = result.content[0];
	return first && first.type === 'text' ? shorten(first.text) : '';
}

function shorten(text: string, length = 300): string {
	return text.length > length ? `${text.slice(0, length)}…` : text;
}
