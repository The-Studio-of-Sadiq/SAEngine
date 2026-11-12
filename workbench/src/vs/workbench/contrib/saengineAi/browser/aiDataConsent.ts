/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ConfigurationTarget, IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { Severity } from '../../../../platform/notification/common/notification.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';

/**
 * The engineer's consent before project data goes to an AI provider (U2, decision "AI assistant
 * scope, privacy and order" of 2026-11-11). Every path that sends project data asks it first:
 * the built-in assistant before each question goes to its provider, the MCP server before a
 * connected assistant reads the project. The dialog says who receives what, and that SAEngine
 * and its developers never receive or sell it; the answer is remembered per project (and per
 * destination) in the user's settings ({@link PROJECT_DATA_CONSENT_SETTING}), never in the
 * project's own files, so a shared project does not carry one engineer's consent to another.
 */

/** User setting: project folder -> the destinations allowed to receive its data. */
export const PROJECT_DATA_CONSENT_SETTING = 'saengine.ai.projectDataConsent';

/** Internal command: the consent of the open project, to change it (menu, view, palette). */
export const MANAGE_PROJECT_CONSENT_COMMAND = 'saengine.ai.manageProjectConsent';

/** Where project data would go, as the dialog names it. */
export interface IAiDataDestination {
	/** Stable id of the destination ("anthropic|api.anthropic.com", "mcp"). */
	readonly id: string;
	/** Who receives the data: "Anthropic (api.anthropic.com), model claude-…". */
	readonly receiver: string;
	/** What is sent, one line each. */
	readonly sends: readonly string[];
	/** Whose terms apply: "Anthropic's". */
	readonly terms: string;
}

export const ISaengineAiDataConsentService = createDecorator<ISaengineAiDataConsentService>('saengineAiDataConsentService');

export interface ISaengineAiDataConsentService {
	readonly _serviceBrand: undefined;
	readonly onDidChange: Event<void>;
	/** Whether the open project's data may go to `destinationId` (no dialog). */
	isAllowed(destinationId: string): boolean;
	/**
	 * True when the open project's data may go to `destination`: allowed before, or the engineer
	 * chooses "Allow for This Project" now. "Not Now" sends nothing and asks again next time.
	 */
	ensure(destination: IAiDataDestination): Promise<boolean>;
	/** The destinations allowed for the open project. */
	allowed(): readonly string[];
	/** Withdraws the open project's consent (all destinations, or one). */
	revoke(destinationId?: string): Promise<void>;
}

type ConsentMap = { [project: string]: string[] };

/** The key of a project in the setting: its folder; '' without a project (kept for the session only). */
function projectKey(root: string | undefined): string {
	return root ? root.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase() : '';
}

export class SaengineAiDataConsentService extends Disposable implements ISaengineAiDataConsentService {

	declare readonly _serviceBrand: undefined;

	/** Consent without a project open: for this window only. */
	private readonly sessionOnly = new Set<string>();
	private asking: Promise<boolean> | undefined;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	constructor(
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IDialogService private readonly dialogService: IDialogService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
	) {
		super();
		this._register(configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(PROJECT_DATA_CONSENT_SETTING)) {
				this._onDidChange.fire();
			}
		}));
		this._register(projectService.onDidChangeProject(() => this._onDidChange.fire()));
	}

	private get key(): string {
		return projectKey(this.projectService.project?.root.fsPath);
	}

	private map(): ConsentMap {
		const value = this.configurationService.getValue<unknown>(PROJECT_DATA_CONSENT_SETTING);
		const out: ConsentMap = {};
		if (value && typeof value === 'object' && !Array.isArray(value)) {
			for (const [project, list] of Object.entries(value)) {
				if (Array.isArray(list)) {
					out[projectKey(project)] = list.filter((v): v is string => typeof v === 'string');
				}
			}
		}
		return out;
	}

	allowed(): readonly string[] {
		const key = this.key;
		return key ? this.map()[key] ?? [] : [...this.sessionOnly];
	}

	isAllowed(destinationId: string): boolean {
		return this.allowed().includes(destinationId);
	}

	async ensure(destination: IAiDataDestination): Promise<boolean> {
		if (this.isAllowed(destination.id)) {
			return true;
		}
		// Several requests at once (an assistant's tool calls) wait for the one dialog.
		this.asking ??= this.ask(destination).finally(() => this.asking = undefined);
		await this.asking;
		return this.isAllowed(destination.id);
	}

	private async ask(destination: IAiDataDestination): Promise<boolean> {
		const project = this.projectService.project;
		const name = project?.name ?? localize('consent.noProject', "no project open");
		const { result } = await this.dialogService.prompt<boolean>({
			type: Severity.Info,
			message: localize('consent.projectTitle', "Send data of {0} to an AI provider?", name),
			detail: [
				localize('consent.receiver', "Who receives it: {0}.", destination.receiver),
				localize('consent.what', "What is sent:\n• {0}", destination.sends.join('\n• ')),
				localize('consent.never', "It goes straight from this computer to that provider, under {0} terms. SAEngine and its developers never receive, see or sell your project data.", destination.terms),
				project
					? localize('consent.remembered', "Your answer is kept for this project on this computer, not in the project's files. Change it at any time: SAEngine: AI Data Sharing for This Project, or Settings › SAEngine AI Assistants.")
					: localize('consent.rememberedSession', "With no project open, your answer is kept until SAEngine closes."),
			].join('\n\n'),
			buttons: [
				{ label: localize({ key: 'consent.allowProject', comment: ['&& denotes a mnemonic'] }, "&&Allow for This Project"), run: () => true },
			],
			cancelButton: { label: localize('consent.notNow', "Not Now"), run: () => false },
		});
		if (result !== true) {
			return false;
		}
		await this.write(destination.id, true);
		return true;
	}

	async revoke(destinationId?: string): Promise<void> {
		if (destinationId === undefined) {
			for (const id of this.allowed()) {
				await this.write(id, false);
			}
			return;
		}
		await this.write(destinationId, false);
	}

	private async write(destinationId: string, allow: boolean): Promise<void> {
		const key = this.key;
		if (!key) {
			if (allow) {
				this.sessionOnly.add(destinationId);
			} else {
				this.sessionOnly.delete(destinationId);
			}
			this._onDidChange.fire();
			return;
		}
		const map = this.map();
		const list = new Set(map[key] ?? []);
		if (allow) {
			list.add(destinationId);
		} else {
			list.delete(destinationId);
		}
		if (list.size) {
			map[key] = [...list];
		} else {
			delete map[key];
		}
		await this.configurationService.updateValue(PROJECT_DATA_CONSENT_SETTING, map, ConfigurationTarget.USER);
	}
}
