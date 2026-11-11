/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';

/**
 * The one confirmation before important data is deleted (U2, decision "Guardrails on input" of
 * 2026-11-11): storeys, grid lines, many members at once, foundations, boreholes, materials and
 * object types, code packs and packages. It names exactly what goes and whether and how it can
 * be undone, in SAEngine's own dialog. Single small edits (one member, one load value) do not
 * ask: callers use {@link needsBulkConfirmation} for members.
 */

/** From this many members (or similar entries) at once a delete asks first; fewer is a small edit. */
export const BULK_DELETE_THRESHOLD = 10;

/** Whether deleting `count` members at once asks first. */
export function needsBulkConfirmation(count: number): boolean {
	return count >= BULK_DELETE_THRESHOLD;
}

/** How what is deleted can come back. */
export type DeleteRecovery =
	/** Undo (Ctrl+Z) in the editor, until it is closed. */
	| 'undo'
	/** Not undone here: installed again (a package or code pack). */
	| 'reinstall'
	/** Gone for good. */
	| 'never';

export interface IDeleteConfirmation {
	/** The question, naming what goes: "Delete 3 storeys?". */
	readonly message: string;
	/** What goes, by name; the first {@link LISTED} are listed. */
	readonly items?: readonly string[];
	/** What goes with it or what follows: "Their 24 members go with them." */
	readonly consequences?: string;
	readonly recovery: DeleteRecovery;
	/** The button, with a mnemonic (default "&&Delete"). */
	readonly button?: string;
	/**
	 * Something still uses it (a material of object types): Keep is the default button and
	 * Delete Anyway the other, so Enter keeps it.
	 */
	readonly inUse?: boolean;
}

/** Items named in the dialog; more are counted. */
export const LISTED = 12;

/** The dialog's text below the question: what goes, what follows, and whether it can be undone. */
export function deleteDetail(confirmation: Pick<IDeleteConfirmation, 'items' | 'consequences' | 'recovery'>): string {
	const lines: string[] = [];
	const items = confirmation.items ?? [];
	if (items.length) {
		const listed = items.slice(0, LISTED).join(', ');
		lines.push(items.length > LISTED ? localize('confirmDelete.more', "{0} and {1} more.", listed, items.length - LISTED) : `${listed}.`);
	}
	if (confirmation.consequences) {
		lines.push(confirmation.consequences);
	}
	lines.push(confirmation.recovery === 'undo'
		? localize('confirmDelete.undo', "Undo (Ctrl+Z) brings it back while the editor is open.")
		: confirmation.recovery === 'reinstall'
			? localize('confirmDelete.reinstall', "It is not undone by Ctrl+Z: install it again to have it back.")
			: localize('confirmDelete.never', "This cannot be undone."));
	return lines.join('\n\n');
}

/** Asks before deleting important data; true when the engineer chose Delete. */
export async function confirmDelete(dialogService: IDialogService, confirmation: IDeleteConfirmation): Promise<boolean> {
	const detail = deleteDetail(confirmation);
	const button = confirmation.button ?? localize({ key: 'confirmDelete.delete', comment: ['&& denotes a mnemonic'] }, "&&Delete");
	if (confirmation.inUse) {
		const { result } = await dialogService.prompt<boolean>({
			type: 'warning',
			message: confirmation.message,
			detail,
			buttons: [
				{ label: localize({ key: 'confirmDelete.keep', comment: ['&& denotes a mnemonic'] }, "&&Keep"), run: () => false },
				{ label: localize({ key: 'confirmDelete.anyway', comment: ['&& denotes a mnemonic'] }, "&&Delete Anyway"), run: () => true },
			],
			cancelButton: { label: localize('confirmDelete.cancel', "Cancel"), run: () => false },
		});
		return result === true;
	}
	const { confirmed } = await dialogService.confirm({ type: 'warning', message: confirmation.message, detail, primaryButton: button });
	return confirmed;
}
