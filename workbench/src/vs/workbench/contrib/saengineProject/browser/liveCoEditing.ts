/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';

/*
 * Real-time co-editing of one part by several engineers at once, with presence (who is in the
 * part, where their cursor or selection is). The engine is a CRDT behind this interface so that
 * the part editors do not depend on it:
 *
 * - The planned engine is Yjs (MIT licence, compatible with AGPL-3.0) with its y-protocols
 *   awareness for presence, over a WebSocket relay the office runs itself (`y-websocket`'s
 *   server, MIT). SAEngine ships no relay address: without `saengine.collaboration.relayUrl` set
 *   by the office nothing leaves the computer, and no third-party cloud is used.
 * - Until the dependency is added to the workbench, no provider is registered and the commands
 *   say so; office-server sync, part locks and presence (`saengine.project.share`) work without it.
 *
 * A part document is a JSON file (`floor-plan.json`, `structure.json`, ...). A provider maps it
 * onto a shared map keyed by the document's object ids, so two engineers editing different
 * members merge, and the same member edited twice keeps the later edit (last writer wins per
 * field). The part editor stays the owner of its model: it gives the provider its text and
 * applies the text the provider hands back.
 */

/** The setting with the office's own relay (`wss://server.office.local:1234`); empty: off. */
export const RELAY_URL_SETTING = 'saengine.collaboration.relayUrl';

/** The part document as a co-editing session sees it. */
export interface ICoEditedDocument {
	/** `<projectRoot>`-relative path of the part file, the session's room name with the project id. */
	readonly path: string;
	/** The document's current text (the part editor's unsaved model, not the file on disk). */
	getText(): string;
	/** Fires when the engineer edits the document here. */
	readonly onDidChangeLocally: Event<void>;
	/** Replaces the document's text with the merged text (the part editor applies it as an edit). */
	applyRemote(text: string): void;
}

/** Someone in the same part, as the awareness protocol reports them. */
export interface ICoEditor {
	readonly id: string;
	readonly name: string;
	/** The object ids they have selected, for highlighting. */
	readonly selection: readonly string[];
}

export interface ICoEditingSession extends IDisposable {
	readonly onDidChangePeople: Event<readonly ICoEditor[]>;
	readonly people: readonly ICoEditor[];
	/** Tells the others what this engineer has selected. */
	setSelection(ids: readonly string[]): void;
}

export interface ICoEditingProvider {
	/** A short name for the UI (`Yjs`). */
	readonly name: string;
	/**
	 * Joins the room of `document` in project `projectId` at `relayUrl`; the provider merges the
	 * document's state with the room's and keeps them in step until the session is disposed.
	 */
	join(relayUrl: string, projectId: string, document: ICoEditedDocument, me: { readonly name: string }): Promise<ICoEditingSession>;
}

let provider: ICoEditingProvider | undefined;

/** Registers the co-editing engine; there is one at most. */
export function registerCoEditingProvider(value: ICoEditingProvider): IDisposable {
	provider = value;
	return toDisposable(() => {
		if (provider === value) {
			provider = undefined;
		}
	});
}

export function coEditingProvider(): ICoEditingProvider | undefined {
	return provider;
}

/** Why live co-editing cannot start, or undefined when it can. */
export type CoEditingBlocker = 'component' | 'engine' | 'relay' | 'notShared';

export function coEditingBlocker(state: { readonly componentUsable: boolean; readonly provider: boolean; readonly relayUrl: string | undefined; readonly shared: boolean }): CoEditingBlocker | undefined {
	if (!state.componentUsable) {
		return 'component';
	}
	if (!state.provider) {
		return 'engine';
	}
	if (!state.shared) {
		return 'notShared';
	}
	if (!state.relayUrl?.trim() || !/^wss?:\/\//i.test(state.relayUrl.trim())) {
		return 'relay';
	}
	return undefined;
}
