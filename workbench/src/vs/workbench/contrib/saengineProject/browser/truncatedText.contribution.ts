/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { addDisposableListener, isHTMLElement, isHTMLInputElement, onDidRegisterWindow } from '../../../../base/browser/dom.js';
import { mainWindow } from '../../../../base/browser/window.js';
import { Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';

/*
 * The full text, as a tooltip, on any SAEngine label or table cell cut short with an ellipsis
 * (`text-overflow: ellipsis`): material names, export files, BOQ status, stair names at 1366.
 * One delegated hover listener covers every part, so no part has to remember to set `title`. A
 * label that has its own title keeps it; the tooltip goes again once the text fits.
 */

/** SAEngine UI: a `saengine*` root or an `sa-` class. */
const SCOPE = '[class*="saengine"], [class^="sa-"], [class*=" sa-"]';

/** How far up from the hovered node to look for the clipped element. */
const MAX_DEPTH = 4;

const OWNED = 'saTruncatedTitle';

function fullText(element: HTMLElement): string {
	if (element.tagName === 'SELECT') {
		return (element as HTMLSelectElement).selectedOptions[0]?.text ?? '';
	}
	if (isHTMLInputElement(element)) {
		return element.value;
	}
	return (element.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/** Sets or clears the tooltip of `element` when it is an ellipsised label; whether it is one. */
export function updateTruncatedTitle(element: HTMLElement): boolean {
	const style = element.ownerDocument.defaultView?.getComputedStyle(element);
	if (style?.textOverflow !== 'ellipsis' || !element.closest(SCOPE)) {
		return false;
	}
	const owned = element.dataset[OWNED] !== undefined;
	if (element.title && !owned) {
		return true;
	}
	const text = fullText(element);
	if (text && element.scrollWidth > element.clientWidth) {
		element.title = text;
		element.dataset[OWNED] = '';
	} else if (owned) {
		element.removeAttribute('title');
		delete element.dataset[OWNED];
	}
	return true;
}

class TruncatedTextTitles extends Disposable implements IWorkbenchContribution {
	static readonly ID = 'workbench.contrib.saengineTruncatedTextTitles';

	constructor() {
		super();
		this._register(Event.runAndSubscribe(onDidRegisterWindow, ({ window, disposables }) => {
			disposables.add(addDisposableListener(window.document, 'mouseover', e => {
				let node = e.target as Node | null;
				for (let depth = 0; node && depth < MAX_DEPTH; depth++, node = node.parentElement) {
					if (isHTMLElement(node) && updateTruncatedTitle(node)) {
						break;
					}
				}
			}, { passive: true }));
		}, { window: mainWindow, disposables: this._store }));
	}
}

registerWorkbenchContribution2(TruncatedTextTitles.ID, TruncatedTextTitles, WorkbenchPhase.AfterRestored);
