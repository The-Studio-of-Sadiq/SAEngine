/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/*
 * Shared projects (live collaboration, office-server sync): the office copy of a project's
 * versions on a shared folder or a self-hosted git server, with part locks and presence. The
 * backend is `saengine.project.share`; these are the workbench's commands and the readers of
 * its answers (pure, so they are tested without the backend).
 */

/** `{projectRoot, fetch?}` -> {@link IShareStatus}. */
export const SHARE_STATUS_COMMAND = 'saengine.share.status';
/** `{projectRoot, location}` -> {@link ISyncResult}: shares the project there and syncs. */
export const SHARE_CONNECT_COMMAND = 'saengine.share.connect';
/** `{projectRoot}`: stops syncing this copy. */
export const SHARE_DISCONNECT_COMMAND = 'saengine.share.disconnect';
/** `{location, target}` -> `{projectRoot}`: copies a shared project to a new local folder. */
export const SHARE_JOIN_COMMAND = 'saengine.share.join';
/** `{projectRoot, resolutions?}` -> {@link ISyncResult}. */
export const SHARE_SYNC_COMMAND = 'saengine.share.sync';
/** `{projectRoot, part, note?}` -> `{lock}`. */
export const SHARE_LOCK_COMMAND = 'saengine.share.lock';
/** `{projectRoot, part, force?}` -> `{released, was}`. */
export const SHARE_UNLOCK_COMMAND = 'saengine.share.unlock';
/** `{projectRoot, part?, leaving?}` -> `{available, people}`. */
export const SHARE_HEARTBEAT_COMMAND = 'saengine.share.heartbeat';

/** How often an open shared project says it is open (the backend hides entries after 180 s). */
export const PRESENCE_INTERVAL_MS = 60_000;

export interface IPartLock {
	readonly part: string;
	readonly title: string;
	readonly user: string;
	readonly host: string;
	/** Seconds since 1970. */
	readonly since: number | undefined;
	readonly note: string;
	/** Taken by this engineer on this computer. */
	readonly mine: boolean;
}

export interface IPresence {
	readonly user: string;
	readonly host: string;
	readonly part: string | undefined;
	readonly me: boolean;
}

export interface IShareStatus {
	readonly shared: boolean;
	readonly location?: string;
	/** `folder`: a shared folder (sync, locks, presence); `server`: a git server (sync only). */
	readonly kind?: 'folder' | 'server';
	/** Versions here that the office copy does not have yet. */
	readonly ahead: number;
	/** Versions in the office copy that are not here yet. */
	readonly behind: number;
	readonly locks: readonly IPartLock[];
	readonly people: readonly IPresence[];
	readonly problems: readonly string[];
}

export type Resolution = 'mine' | 'theirs';

export interface IShareConflict {
	readonly part: string;
	readonly title: string;
	readonly paths: readonly string[];
}

export interface ISyncResult {
	readonly state: 'upToDate' | 'sent' | 'received' | 'merged' | 'conflicts';
	readonly received: readonly string[];
	readonly sent: boolean;
	readonly conflicts: readonly IShareConflict[];
}

type Bag = { readonly [key: string]: unknown };

function bag(value: unknown): Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Bag : {};
}

function text(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() ? value : undefined;
}

function count(value: unknown): number {
	return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export function readLock(value: unknown): IPartLock | undefined {
	const b = bag(value);
	const part = text(b.part);
	if (!part) {
		return undefined;
	}
	return {
		part,
		title: text(b.title) ?? part,
		user: text(b.user) ?? localize('share.someone', "someone"),
		host: text(b.host) ?? '',
		since: typeof b.since === 'number' ? b.since : undefined,
		note: text(b.note) ?? '',
		mine: b.mine === true,
	};
}

export function readPresence(value: unknown): IPresence | undefined {
	const b = bag(value);
	const user = text(b.user);
	return user ? { user, host: text(b.host) ?? '', part: text(b.part), me: b.me === true } : undefined;
}

export function readShareStatus(value: unknown): IShareStatus {
	const b = bag(value);
	const kind = b.kind === 'server' ? 'server' : b.kind === 'folder' ? 'folder' : undefined;
	return {
		shared: b.shared === true,
		location: text(b.location),
		kind,
		ahead: count(b.ahead),
		behind: count(b.behind),
		locks: (Array.isArray(b.locks) ? b.locks : []).map(readLock).filter((l): l is IPartLock => !!l),
		people: (Array.isArray(b.people) ? b.people : []).map(readPresence).filter((p): p is IPresence => !!p),
		problems: strings(b.problems),
	};
}

const SYNC_STATES = ['upToDate', 'sent', 'received', 'merged', 'conflicts'] as const;

export function readSyncResult(value: unknown): ISyncResult {
	const b = bag(value);
	const state = (SYNC_STATES as readonly unknown[]).includes(b.state) ? b.state as ISyncResult['state'] : 'upToDate';
	const conflicts = (Array.isArray(b.conflicts) ? b.conflicts : []).flatMap(c => {
		const entry = bag(c);
		const part = text(entry.part);
		return part ? [{ part, title: text(entry.title) ?? part, paths: strings(entry.paths) }] : [];
	});
	return { state, received: strings(b.received), sent: b.sent === true, conflicts };
}

/** Whether `location` is a git server address rather than a shared folder (as the backend decides). */
export function isServerLocation(location: string): boolean {
	return /^(?:https?|ssh|git):\/\/|^[\w.-]+@[\w.-]+:/i.test(location.trim());
}

/** The lock of `part` held by someone else, if any. */
export function lockedByOther(status: IShareStatus | undefined, part: string): IPartLock | undefined {
	return status?.locks.find(l => l.part === part && !l.mine);
}

/** One line for the sync result, for a notification. */
export function syncMessage(result: ISyncResult): string {
	const files = result.received.length;
	switch (result.state) {
		case 'upToDate': return localize('share.upToDate', "This copy and the office copy are the same.");
		case 'sent': return localize('share.sent', "Your versions were sent to the office copy.");
		case 'received': return files === 1
			? localize('share.receivedOne', "1 file was brought in from the office copy.")
			: localize('share.received', "{0} files were brought in from the office copy.", files);
		case 'merged': return localize('share.merged', "Your versions and the office copy's were merged part by part ({0} files brought in){1}.", files, result.sent ? localize('share.mergedSent', " and sent back") : '');
		case 'conflicts': return localize('share.conflicts', "{0} changed both here and in the office copy: choose whose version to keep.", result.conflicts.map(c => c.title).join(', '));
	}
}

/** One line for the shared state: where, and what is waiting each way. */
export function shareSummary(status: IShareStatus): string {
	if (!status.shared) {
		return localize('share.notShared', "Not shared: this project's versions are on this computer only.");
	}
	const waiting = status.ahead && status.behind
		? localize('share.both', "{0} to send, {1} to bring in", status.ahead, status.behind)
		: status.ahead ? localize('share.ahead', "{0} to send", status.ahead)
			: status.behind ? localize('share.behind', "{0} to bring in", status.behind)
				: localize('share.inSync', "in sync");
	return localize('share.summary', "Shared at {0}: {1}.", status.location ?? '', waiting);
}
