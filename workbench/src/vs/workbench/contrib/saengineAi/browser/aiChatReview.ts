/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../../base/common/cancellation.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ElicitationState, IChatService } from '../../chat/common/chatService/chatService.js';
import { IChatRequestModel } from '../../chat/common/model/chatModel.js';
import { ChatElicitationRequestPart } from '../../chat/common/model/chatProgressTypes/chatElicitationRequestPart.js';
import { IActionStep, stepNames } from '../../../services/saengineProject/common/saengineActions.js';
import { IPreviewRow, MAX_PREVIEW_ROWS, previewRows } from '../common/aiChangeSet.js';
import { IAiReview } from './aiActionTools.js';
import { IAiChangeSet, ISaengineAiChangeSetService } from './aiChangeSets.js';

/** Undoes an accepted change set from the chat's link (argument: the set's id). */
export const UNDO_CHANGE_SET_COMMAND = 'saengine.ai.changeSet.undo';

/**
 * The review of the chat assistant's requests inside the chat, in the answer that asked for
 * them: each change set as a card with its values before and after and Accept / Reject, each run
 * step (Run All, exports, creating the project) as a card with Save and Run / Cancel. These are
 * SAEngine's own questions, not the chat's tool approval, so no "always allow" or auto-approve
 * setting skips them: the engineer decides every change. Stopping the request rejects what is
 * still open.
 */
export class AiChatReview extends Disposable implements IAiReview {

	private readonly parts = this._register(new DisposableStore());
	/** The change sets the engineer accepted through this review, for the tool's Undo link. */
	readonly accepted: IAiChangeSet[] = [];

	constructor(
		private readonly request: IChatRequestModel,
		private readonly token: CancellationToken,
		@IChatService private readonly chatService: IChatService,
		@ISaengineAiChangeSetService private readonly changeSets: ISaengineAiChangeSetService,
	) {
		super();
	}

	async showChangeSet(changeSet: IAiChangeSet): Promise<void> {
		const values = changeSet.files.reduce((sum, file) => sum + file.changes.length, 0);
		const part = new ChatElicitationRequestPart(
			localize('chatReview.title', "Change set: {0}", changeSet.title),
			changeSetMarkdown(changeSet),
			localize('chatReview.subtitle', "{0} values · accepted, it is one undoable step, unsaved until you save", values),
			localize('chatReview.accept', "Accept"),
			localize('chatReview.reject', "Reject"),
			async () => {
				await this.changeSets.accept(changeSet.id);
				if (changeSet.state === 'accepted') {
					this.accepted.push(changeSet);
					return ElicitationState.Accepted;
				}
				return ElicitationState.Rejected;
			},
			async () => {
				this.changeSets.reject(changeSet.id);
				return ElicitationState.Rejected;
			},
		);
		this.chatService.appendProgress(this.request, part);
		// Stopped, or stale (the project closed): nothing to decide any more.
		const listener = this.token.onCancellationRequested(() => this.changeSets.reject(changeSet.id));
		this.parts.add(listener);
		void changeSet.decision.then(state => {
			listener.dispose();
			if (state !== 'accepted' && state !== 'rejected') {
				part.hide();
			}
		});
	}

	confirmRun(steps: readonly IActionStep[]): Promise<boolean> {
		return new Promise<boolean>(resolve => {
			const part = new ChatElicitationRequestPart(
				localize('chatReview.runTitle', "Save the project and run {0}?", stepNames(steps)),
				new MarkdownString(localize('chatReview.runDetail', "SAEngine saves your edited parts first; the engine then writes the results to the project. You check them before they are used.")),
				'',
				localize('chatReview.run', "Save and Run"),
				localize('chatReview.cancel', "Cancel"),
				async () => { resolve(true); return ElicitationState.Accepted; },
				async () => { resolve(false); return ElicitationState.Rejected; },
			);
			this.chatService.appendProgress(this.request, part);
			this.parts.add(this.token.onCancellationRequested(() => {
				resolve(false);
				part.hide();
			}));
		});
	}
}

/** The change set as the chat shows it: what each step did, then every value before and after. */
export function changeSetMarkdown(changeSet: Pick<IAiChangeSet, 'files' | 'summary'>, max = MAX_PREVIEW_ROWS): MarkdownString {
	const markdown = new MarkdownString();
	for (const line of changeSet.summary ?? []) {
		markdown.appendMarkdown('- ').appendText(line).appendMarkdown('\n');
	}
	const { rows, more } = previewRows(changeSet.files, max);
	markdown.appendMarkdown(`\n| ${localize('chatReview.file', "File")} | ${localize('chatReview.value', "Value")} | ${localize('chatReview.before', "Before")} | ${localize('chatReview.after', "After")} |\n|---|---|---|---|\n`);
	for (const row of rows) {
		markdown.appendMarkdown(`| ${cell(row.file)} | ${cell(row.value)}${row.reason ? ` (${cell(row.reason)})` : ''} | ${cell(row.before)} | ${row.after === undefined ? localize('chatReview.removed', "(removed)") : cell(row.after)} |\n`);
	}
	if (more) {
		markdown.appendMarkdown('\n').appendText(localize('chatReview.more', "... and {0} more values.", more));
	}
	return markdown;
}

/** A table cell's text: no markdown, no line breaks, no column separators. */
function cell(text: IPreviewRow['value']): string {
	return text.replace(/[\\`*_{}[\]()#+\-.!<>|~]/g, '\\$&').replace(/\r?\n/g, ' ');
}
