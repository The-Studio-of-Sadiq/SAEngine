/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IActionStep, stepNames } from '../../../services/saengineProject/common/saengineActions.js';
import { previewRows } from '../common/aiChangeSet.js';
import { IAiReview } from './aiActionTools.js';
import { ChangeSetSource, IAiChangeSet, ISaengineAiChangeSetService } from './aiChangeSets.js';

/** Most values the dialog lists; the rest are counted. */
const DIALOG_ROWS = 20;

/**
 * The review of an MCP client's requests (an assistant outside SAEngine, so not in the chat): a
 * dialog with the change set's values before and after, Accept or Reject; a notification with
 * Undo after accepting; the run confirmation as a dialog.
 */
export class AiDialogReview implements IAiReview {

	constructor(
		@IDialogService private readonly dialogService: IDialogService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISaengineAiChangeSetService private readonly changeSets: ISaengineAiChangeSetService,
	) { }

	async showChangeSet(changeSet: IAiChangeSet): Promise<void> {
		const { rows, more } = previewRows(changeSet.files, DIALOG_ROWS);
		const lines = rows.map(row => row.after === undefined
			? localize('dialogReview.removed', "{0} {1}: {2} → (removed)", row.file, row.value, row.before)
			: localize('dialogReview.row', "{0} {1}: {2} → {3}", row.file, row.value, row.before, row.after));
		if (more) {
			lines.push(localize('dialogReview.more', "... and {0} more values.", more));
		}
		const { result } = await this.dialogService.prompt<boolean>({
			type: Severity.Info,
			message: localize('dialogReview.title', "An AI assistant connected to this window proposes: {0}", changeSet.title),
			detail: [...(changeSet.summary ?? []), '', ...lines, '', localize('dialogReview.hint', "Accepted, it is one step you can undo (Ctrl+Z); it stays unsaved until you save.")].join('\n'),
			buttons: [{ label: localize({ key: 'dialogReview.accept', comment: ['&& denotes a mnemonic'] }, "&&Accept"), run: () => true }],
			cancelButton: { label: localize('dialogReview.reject', "Reject"), run: () => false },
		});
		if (result !== true) {
			this.changeSets.reject(changeSet.id);
			return;
		}
		await this.changeSets.accept(changeSet.id);
		if (changeSet.state === 'accepted') {
			this.notificationService.notify({
				severity: Severity.Info,
				message: localize('dialogReview.applied', "Applied \"{0}\" (unsaved).", changeSet.title),
				actions: {
					primary: [{
						id: 'saengine.ai.changeSet.undoNotification', label: localize('dialogReview.undo', "Undo"), tooltip: '', class: undefined, enabled: true,
						run: () => this.changeSets.undo(changeSet.id),
					}],
				},
			});
		}
	}

	async confirmRun(steps: readonly IActionStep[], source: ChangeSetSource): Promise<boolean> {
		const { confirmed } = await this.dialogService.confirm({
			message: source === 'mcp'
				? localize('actions.confirmMcp', "An MCP client asks to save the project and run {0}.", stepNames(steps))
				: localize('actions.confirmAssistant', "The AI assistant asks to save the project and run {0}.", stepNames(steps)),
			detail: localize('actions.confirmDetail', "SAEngine saves your edited parts first; the results are written to the project. You check them before they are used."),
			primaryButton: localize({ key: 'actions.run', comment: ['&& denotes a mnemonic'] }, "&&Save and Run"),
		});
		return confirmed;
	}
}
