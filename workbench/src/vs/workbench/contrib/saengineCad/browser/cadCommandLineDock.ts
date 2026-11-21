/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, getWindow, isHTMLElement } from '../../../../base/browser/dom.js';
import { DisposableStore, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';

const NO_HISTORY_KEY = 'main.commandLine.noHistory';

function findByClass(root: HTMLElement, className: string): HTMLElement | undefined {
	let child = root.firstElementChild;
	while (child) {
		if (isHTMLElement(child)) {
			if (child.classList.contains(className)) {
				return child;
			}
			const nested = findByClass(child, className);
			if (nested) {
				return nested;
			}
		}
		child = child.nextElementSibling;
	}
	return undefined;
}

function removePlaceholders(panel: HTMLElement): void {
	const toRemove: HTMLElement[] = [];
	let child = panel.firstElementChild;
	while (child) {
		if (isHTMLElement(child) && child.dataset.msgKey === NO_HISTORY_KEY) {
			toRemove.push(child);
		}
		child = child.nextElementSibling;
	}
	for (const el of toRemove) {
		el.remove();
	}
}

/**
 * Enhances mlightcad's mounted `.ml-cli-container` so it acts as a docked AutoCAD-style command
 * line with a visible 3-line history strip that always scrolls to the latest output.
 */
export function dockCadCommandLine(host: HTMLElement): IDisposable {
	const store = new DisposableStore();
	const win = getWindow(host);
	let attachedPanel: HTMLElement | undefined;

	const attachPanel = () => {
		const msgPanel = findByClass(host, 'ml-cli-msg-panel');
		if (!msgPanel || msgPanel === attachedPanel) {
			return;
		}
		attachedPanel = msgPanel;

		// Replace mlightcad's empty placeholder (or seed an initial ready line) so the 3-line
		// docked strip is immediately informative before the first command runs.
		let placeholder: HTMLElement | undefined;
		let child = msgPanel.firstElementChild;
		while (child) {
			if (isHTMLElement(child) && child.dataset.msgKey === NO_HISTORY_KEY) {
				placeholder = child;
				break;
			}
			child = child.nextElementSibling;
		}
		if (placeholder) {
			placeholder.textContent = localize('cad.commandLine.ready', "Command: Type a command or pick a tool from the Draft ribbon (press : to hide)");
		} else if (msgPanel.children.length === 0) {
			const line = $('div.ml-cli-history-line');
			line.dataset.msgKey = NO_HISTORY_KEY;
			line.textContent = localize('cad.commandLine.ready', "Command: Type a command or pick a tool from the Draft ribbon (press : to hide)");
			msgPanel.appendChild(line);
		}

		const scrollToBottom = () => {
			win.queueMicrotask(() => {
				msgPanel.scrollTop = msgPanel.scrollHeight;
			});
		};
		scrollToBottom();

		const panelObserver = new win.MutationObserver(() => {
			scrollToBottom();
		});
		panelObserver.observe(msgPanel, { childList: true });
		store.add(toDisposable(() => panelObserver.disconnect()));
	};

	attachPanel();
	const hostObserver = new win.MutationObserver(() => attachPanel());
	hostObserver.observe(host, { childList: true, subtree: true });
	store.add(toDisposable(() => hostObserver.disconnect()));

	return store;
}

/** Appends a command line echo/message to mlightcad's docked history panel and scrolls to bottom. */
export function appendCommandHistoryLine(host: HTMLElement, text: string): void {
	const msgPanel = findByClass(host, 'ml-cli-msg-panel');
	if (!msgPanel) {
		return;
	}
	removePlaceholders(msgPanel);

	const line = $('div.ml-cli-history-line');
	line.textContent = text;
	msgPanel.appendChild(line);
	msgPanel.scrollTop = msgPanel.scrollHeight;
}
