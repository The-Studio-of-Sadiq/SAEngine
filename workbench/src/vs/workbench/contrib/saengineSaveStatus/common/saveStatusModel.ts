/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';

export const enum SaveStatusKind {
	/** Nothing unsaved. */
	Saved = 'saved',
	/** Unsaved changes that wait for the user to save them. */
	Unsaved = 'unsaved',
	/** A save is writing, or auto-save (after a delay) will write the unsaved changes shortly. */
	Saving = 'saving',
	/** A save failed and the document has not been saved since. */
	Failed = 'failed',
}

export interface ISaveStatus {
	readonly kind: SaveStatusKind;
	/** Labels of the unsaved documents, sorted. */
	readonly unsaved: readonly string[];
	/** Labels of the documents whose last save failed, sorted. */
	readonly failed: readonly string[];
	/** Saves still writing. */
	readonly saving: number;
	/** Saving only because auto-save will write the unsaved changes shortly (no write running). */
	readonly autoSavePending: boolean;
	/** When the last save or write finished (ms since the epoch). */
	readonly lastSaved: number | undefined;
	/** Until when (ms since the epoch) a finished save is still shown as saving, so it can be seen. */
	readonly showSavingUntil: number | undefined;
}

/** How long a save is shown at least (a save usually takes a few milliseconds). */
export const MIN_SAVING_DISPLAY = 600;

interface IDirtyEntry {
	readonly label: string;
	readonly autoSave: boolean;
}

/**
 * The state behind the save status of the status bar: which documents are unsaved, which saves
 * are writing and which failed. Documents are keyed by an id of the caller's choosing (one per
 * working copy); times are passed in so the state is easy to test.
 */
export class SaveStatusModel extends Disposable {

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	private readonly dirty = new Map<string, IDirtyEntry>();
	private readonly failed = new Map<string, string>();
	/** Saves writing, by document: when the first one started and how many there are. */
	private readonly saving = new Map<string, { started: number; count: number }>();
	private lastSaved: number | undefined;
	private showSavingUntil: number | undefined;

	/** A document became unsaved or saved; `autoSave` when auto-save after a delay will write it. */
	setDirty(id: string, label: string, dirty: boolean, autoSave = false): void {
		if (dirty) {
			const entry = this.dirty.get(id);
			if (entry?.label === label && entry.autoSave === autoSave) {
				return;
			}
			this.dirty.set(id, { label, autoSave });
		} else {
			const changed = this.dirty.delete(id);
			// Saved or reverted: an earlier failure no longer applies.
			if (!this.failed.delete(id) && !changed) {
				return;
			}
		}
		this._onDidChange.fire();
	}

	/** A document is closed or gone: forget it. */
	remove(id: string): void {
		const changed = [this.dirty.delete(id), this.failed.delete(id), this.saving.delete(id)].some(Boolean);
		if (changed) {
			this._onDidChange.fire();
		}
	}

	saveStarted(id: string, now: number): void {
		const running = this.saving.get(id);
		this.saving.set(id, { started: running?.started ?? now, count: (running?.count ?? 0) + 1 });
		this._onDidChange.fire();
	}

	/** A save started with {@link saveStarted} is over, whatever its outcome. */
	saveEnded(id: string, now: number): void {
		const running = this.saving.get(id);
		if (!running) {
			return;
		}
		if (running.count > 1) {
			this.saving.set(id, { started: running.started, count: running.count - 1 });
		} else {
			this.saving.delete(id);
			this.extendSaving(running.started + MIN_SAVING_DISPLAY, now);
		}
		this._onDidChange.fire();
	}

	/** A document was written to disk. */
	saved(id: string, now: number): void {
		this.failed.delete(id);
		this.lastSaved = now;
		this._onDidChange.fire();
	}

	saveFailed(id: string, label: string): void {
		this.failed.set(id, label);
		this._onDidChange.fire();
	}

	/** A file was written that is not an open document (results of a run, an export): shown as a short save. */
	wrote(now: number): void {
		this.lastSaved = now;
		this.extendSaving(now + MIN_SAVING_DISPLAY, now);
		this._onDidChange.fire();
	}

	/** Forgets all failures (the user saw them). */
	clearFailures(): void {
		if (this.failed.size) {
			this.failed.clear();
			this._onDidChange.fire();
		}
	}

	private extendSaving(until: number, now: number): void {
		if (until > now && (this.showSavingUntil === undefined || until > this.showSavingUntil)) {
			this.showSavingUntil = until;
		}
	}

	status(now: number): ISaveStatus {
		const unsaved = [...this.dirty.values()].map(entry => entry.label).sort();
		const failed = [...this.failed.values()].sort();
		let saving = 0;
		for (const { count } of this.saving.values()) {
			saving += count;
		}
		const showSavingUntil = this.showSavingUntil !== undefined && this.showSavingUntil > now ? this.showSavingUntil : undefined;
		const autoSavePending = saving === 0 && this.dirty.size > 0 && [...this.dirty.values()].every(entry => entry.autoSave);

		let kind: SaveStatusKind;
		if (failed.length) {
			kind = SaveStatusKind.Failed;
		} else if (saving > 0 || autoSavePending || (showSavingUntil !== undefined && this.dirty.size === 0)) {
			kind = SaveStatusKind.Saving;
		} else if (this.dirty.size) {
			kind = SaveStatusKind.Unsaved;
		} else {
			kind = SaveStatusKind.Saved;
		}
		return { kind, unsaved, failed, saving, autoSavePending, lastSaved: this.lastSaved, showSavingUntil };
	}
}
