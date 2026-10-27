/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IProjectVersionsService } from './versionsService.js';
import { basename } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { hasIssueLabel, IVersionEntry, partLabel, partsSummary, pendingParts, restoreConfirmation, versionName, versionTitle } from './versionsModel.js';

/** The arguments of the Save Version command: any left out is asked. */
export interface ISaveVersionCommandArgs {
	readonly message?: string;
	readonly issued?: boolean;
	readonly label?: string;
	readonly author?: string;
}

/**
 * The small dialogs of the versions: Save Version (a message, an "issued" toggle and its label),
 * Restore (which parts, and a confirmation naming them) and Mark as Issued (the label).
 */
export class VersionsFlows {

	constructor(
		@IProjectVersionsService private readonly versionsService: IProjectVersionsService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@IDialogService private readonly dialogService: IDialogService,
		@INotificationService private readonly notificationService: INotificationService,
	) { }

	/** Asks the message (and whether it is an issue) and saves the current files as a version. */
	async save(args: ISaveVersionCommandArgs = {}): Promise<IVersionEntry | undefined> {
		if (!this.versionsService.available) {
			this.notificationService.info(localize('versions.unavailable', "Versions are not available in this build of SAEngine."));
			return undefined;
		}
		let { message, issued, label } = args;
		if (message === undefined) {
			const answer = await this.askMessage(issued ?? false);
			if (!answer) {
				return undefined;
			}
			message = answer.message;
			issued = answer.issued;
		}
		if (issued && label === undefined) {
			label = await this.askLabel();
			if (label === undefined) {
				return undefined;
			}
		}
		// The backend versions the files on disk: save the edits still open in editors first (as Run
		// All does), so that the version is what the engineer sees.
		if (!await this.saveEdits(files => localize('versions.saveEditsFailed', "The version was not saved: {0} could not be saved first.", files))) {
			return undefined;
		}
		try {
			const version = await this.versionsService.save(message, { issued, label, author: args.author });
			this.notificationService.info(version
				? localize('versions.saved', "Saved {0}.", versionTitle(version))
				: localize('versions.savedPlain', "Saved the version."));
			return version;
		} catch (error) {
			this.notificationService.error(localize('versions.saveFailed', "The version could not be saved: {0}", toErrorMessage(error)));
			return undefined;
		}
	}

	/**
	 * The message, and whether the version is an issue: two labelled choices under the message
	 * ("Save Version", "Save as Issued..."), the one asked for first.
	 */
	private askMessage(issued: boolean): Promise<{ message: string; issued: boolean } | undefined> {
		const store = new DisposableStore();
		const pick = store.add(this.quickInputService.createQuickPick<IQuickPickItem & { readonly issued: boolean }>());
		const plain = { label: `$(${Codicon.save.id}) ${localize('versions.saveChoice', "Save Version")}`, description: localize('versions.saveChoiceDetail', "a working version"), issued: false };
		const issue = { label: `$(${Codicon.verified.id}) ${localize('versions.issuedChoice', "Save as Issued...")}`, description: localize('versions.issuedChoiceDetail', "a submission or a drawing issue; asks its label next"), issued: true };
		pick.title = localize('versions.saveTitle', "Save Version");
		pick.placeholder = localize('versions.messagePlaceholder', "What changed, e.g. Column sizes after the wind check");
		// The typed text is the message, not a filter: both choices stay.
		pick.filterValue = () => '';
		pick.items = issued ? [issue, plain] : [plain, issue];
		pick.ignoreFocusOut = true;
		return new Promise(resolve => {
			let done = false;
			const finish = (value: { message: string; issued: boolean } | undefined) => {
				if (!done) {
					done = true;
					resolve(value);
					pick.hide();
				}
			};
			store.add(pick.onDidChangeValue(() => pick.validationMessage = undefined));
			store.add(pick.onDidAccept(() => {
				const message = pick.value.trim();
				if (!message) {
					pick.validationMessage = localize('versions.messageEmpty', "Say what changed in this version.");
					return;
				}
				finish({ message, issued: pick.activeItems[0]?.issued ?? false });
			}));
			store.add(pick.onDidHide(() => {
				finish(undefined);
				store.dispose();
			}));
			pick.show();
		});
	}

	/**
	 * Saves the open project's edits that are still only in editors. On a failure shows
	 * `failure(what failed)` and returns false.
	 */
	private async saveEdits(failure: (files: string) => string): Promise<boolean> {
		let failed: URI[];
		try {
			failed = await this.versionsService.saveEdits();
		} catch (error) {
			this.notificationService.error(failure(toErrorMessage(error)));
			return false;
		}
		if (failed.length) {
			this.notificationService.error(failure(failed.map(file => basename(file)).join(', ')));
			return false;
		}
		return true;
	}

	/**
	 * Asks an issue label. For a version already issued it asks a further label: labels are only
	 * ever added (an issue is a record), so the old ones stay and are named in the prompt.
	 */
	private async askLabel(version?: IVersionEntry): Promise<string | undefined> {
		const issued = version?.issued && version.labels.length ? version.labels.join(', ') : undefined;
		const label = await this.quickInputService.input({
			title: !version ? localize('versions.issueTitle', "Issued Version")
				: issued ? localize('versions.addLabelTitle', "Add an Issue Label to {0}", versionName(version))
					: localize('versions.markTitle', "Mark {0} as Issued", versionName(version)),
			prompt: issued
				? localize('versions.addLabelPrompt', "Already issued as {0}; those labels stay. The new label, as on the drawings and the report", issued)
				: localize('versions.labelPrompt', "The issue label, as on the drawings and the report"),
			placeHolder: localize('versions.labelPlaceholder', "e.g. Rev A, Issued for Approval"),
			ignoreFocusLost: true,
			validateInput: async value => !value.trim()
				? localize('versions.labelEmpty', "Enter the issue label.")
				: version && hasIssueLabel(version, value) ? localize('versions.labelExists', "{0} is already issued as {1}.", versionName(version), value.trim()) : undefined,
		});
		return label?.trim();
	}

	/** Marks `version` as issued under a label (asked when not given); a label it has already changes nothing. */
	async markIssued(version: IVersionEntry, label?: string): Promise<boolean> {
		const value = label ?? await this.askLabel(version);
		if (!value) {
			return false;
		}
		if (hasIssueLabel(version, value)) {
			this.notificationService.info(localize('versions.labelExists', "{0} is already issued as {1}.", versionName(version), value.trim()));
			return false;
		}
		try {
			await this.versionsService.markIssued(version.id, value);
			return true;
		} catch (error) {
			this.notificationService.error(localize('versions.markFailed', "{0} could not be marked as issued: {1}", versionName(version), toErrorMessage(error)));
			return false;
		}
	}

	/**
	 * Restores `version`: the parts that differ from it (all, or those the user picks, or `parts`),
	 * after a confirmation that names them.
	 */
	async restore(version: IVersionEntry, parts?: readonly string[]): Promise<boolean> {
		// The backend restores (and first keeps) the files on disk. Edits still open in editors would
		// be neither kept nor replaced: the editor would keep the old text and a later save would undo
		// the restore. So they are saved first, with the engineer's agreement.
		const edited = this.versionsService.editedParts;
		if (edited.length) {
			const { confirmed } = await this.dialogService.confirm({
				type: 'info',
				message: localize('versions.restoreEditsMessage', "Save your edits before restoring?"),
				detail: localize('versions.restoreEditsDetail', "{0} has edits that are not saved yet. They are saved first, so that the restore keeps them in a version of their own and the editors show the restored files.", partsSummary(edited, 5)),
				primaryButton: localize('versions.restoreEditsButton', "&&Save and Continue"),
			});
			if (!confirmed || !await this.saveEdits(files => localize('versions.restoreEditsFailed', "Nothing was restored: {0} could not be saved first.", files))) {
				return false;
			}
			// The status the confirmation names comes from the files on disk: ask it again now.
			await this.versionsService.refresh();
		}
		let changed: string[];
		try {
			changed = (await this.versionsService.diff(version.id)).parts.map(p => p.part).filter(Boolean);
		} catch (error) {
			// Without the diff the confirmation cannot say what changes: stop rather than restore blind.
			this.notificationService.error(localize('versions.restoreDiffFailed', "{0} could not be compared with the current files, so nothing was restored: {1}", versionName(version), toErrorMessage(error)));
			return false;
		}
		if (!changed.length) {
			this.notificationService.info(localize('versions.restoreSame', "The current files are the same as {0}; there is nothing to restore.", versionName(version)));
			return false;
		}
		let chosen = parts ? parts.filter(p => changed.includes(p)) : changed;
		if (!chosen.length) {
			this.notificationService.info(localize('versions.restoreSameParts', "Those parts are the same as in {0}; there is nothing to restore.", versionName(version)));
			return false;
		}
		if (!parts && changed.length > 1) {
			interface IPartItem extends IQuickPickItem { readonly part: string }
			const items: IPartItem[] = changed.map(part => ({ part, label: partLabel(part), picked: true }));
			const picked = await this.quickInputService.pick(items, {
				canPickMany: true,
				title: localize('versions.restorePartsTitle', "Restore {0}", versionTitle(version)),
				placeHolder: localize('versions.restoreParts', "The parts to bring back as they were in {0}", versionName(version)),
				ignoreFocusLost: true,
			});
			if (!picked?.length) {
				return false;
			}
			chosen = picked.map(item => item.part);
		}
		const { message, detail } = restoreConfirmation(version, chosen, pendingParts(this.versionsService.status, this.versionsService.editedParts));
		const { confirmed } = await this.dialogService.confirm({
			type: 'warning',
			message,
			detail,
			primaryButton: localize('versions.restoreButton', "&&Restore"),
		});
		if (!confirmed) {
			return false;
		}
		try {
			await this.versionsService.restore(version.id, chosen, changed);
			this.notificationService.info(localize('versions.restored', "Restored {0} from {1}.", chosen.map(p => partLabel(p)).join(', '), versionName(version)));
			return true;
		} catch (error) {
			this.notificationService.error(localize('versions.restoreFailed', "{0} could not be restored: {1}", versionName(version), toErrorMessage(error)));
			return false;
		}
	}
}
