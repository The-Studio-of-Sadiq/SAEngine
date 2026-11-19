/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * AutoCAD's Space = Enter at point prompts. The library's dynamic-input box and command line only
 * answer Enter, so Space never ended a prompt (GRIPEDIT could not cycle Stretch → Move → … with
 * Space). While a point prompt waits, a Space typed in the drawing, its dynamic-input box or its
 * command line is turned into Enter on the same element.
 */

/** The parts of a keydown event the rule reads. */
export interface SpaceKeyEvent {
	readonly key: string;
	readonly ctrlKey?: boolean;
	readonly altKey?: boolean;
	readonly metaKey?: boolean;
	readonly isComposing?: boolean;
	/** Whether the event's target is the drawing, its dynamic-input box or its command line. */
	readonly inDrawing: boolean;
	/** Whether the target edits free text (a textarea or a contenteditable). */
	readonly inTextEditor: boolean;
}

/** Whether a keydown should act as Enter at a point prompt. */
export function spaceActsAsEnter(e: SpaceKeyEvent): boolean {
	return e.key === ' ' && !e.ctrlKey && !e.altKey && !e.metaKey && !e.isComposing && e.inDrawing && !e.inTextEditor;
}

/** The selectors of the drawing's own elements: the canvas host, the dynamic input, the command line. */
const DRAWING_SELECTOR = '.ml-floating-input, .ml-cli-text, .saengine-cad-editor, .cad-instance, canvas';

function describe(event: KeyboardEvent): SpaceKeyEvent {
	const target = event.target as (Element & { isContentEditable?: boolean }) | null;
	const isElement = !!target && typeof (target as Element).closest === 'function';
	const inDrawing = isElement
		? !!(target as Element).closest(DRAWING_SELECTOR) || target === target.ownerDocument?.body
		: true;
	const inTextEditor = isElement && ((target as Element).tagName === 'TEXTAREA' || !!target.isContentEditable);
	return {
		key: event.key,
		ctrlKey: event.ctrlKey,
		altKey: event.altKey,
		metaKey: event.metaKey,
		isComposing: event.isComposing,
		inDrawing,
		inTextEditor,
	};
}

let installed = 0;
let listener: ((event: KeyboardEvent) => void) | undefined;

/**
 * Makes Space act as Enter until the returned function is called. Nested calls share one listener.
 */
export function installSpaceAsEnter(): () => void {
	if (typeof window === 'undefined') {
		return () => { };
	}
	if (installed++ === 0) {
		listener = event => {
			if (!spaceActsAsEnter(describe(event))) {
				return;
			}
			event.preventDefault();
			event.stopImmediatePropagation();
			const target = (event.target as EventTarget | null) ?? document;
			target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
		};
		window.addEventListener('keydown', listener, true);
	}
	let disposed = false;
	return () => {
		if (disposed) {
			return;
		}
		disposed = true;
		if (--installed === 0 && listener) {
			window.removeEventListener('keydown', listener, true);
			listener = undefined;
		}
	};
}
