/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadChrome, CadEditor } from '@saengine/cad-editor';
import { $, append } from '../../../../base/browser/dom.js';
import { Color } from '../../../../base/common/color.js';
import { editorBackground } from '../../../../platform/theme/common/colors/editorColors.js';
import { IColorTheme } from '../../../../platform/theme/common/themeService.js';
import { sanitizeHtml } from '../../../../base/browser/domSanitize.js';
import { createTrustedTypesPolicy } from '../../../../base/browser/trustedTypes.js';
import { resolveAmdNodeModulePath } from '../../../../amdX.js';

type CadEditorModule = typeof import('@saengine/cad-editor');

const PACKAGE = '@saengine/cad-editor';

/** SVG icons and a few text tags: everything mlightcad's own UI writes with innerHTML. */
const CAD_UI_TAGS = ['svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'text', 'tspan', 'defs', 'use', 'span', 'strong', 'div'];
const CAD_UI_ATTRIBUTES = ['viewBox', 'd', 'fill', 'fill-rule', 'clip-rule', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'cx', 'cy', 'r', 'rx', 'ry', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'points', 'transform', 'width', 'height', 'opacity', 'xmlns', 'aria-hidden', 'class', 'font-size', 'text-anchor'];

let cadModule: Promise<CadEditorModule> | undefined;

/**
 * Loads the bundled mlightcad editor and connects it to the workbench's Trusted Types rules:
 * its HTML goes through the workbench sanitizer and its worker may only come from its own folder.
 */
function loadCadModule(): Promise<CadEditorModule> {
	if (!cadModule) {
		cadModule = (async () => {
			const module = await import(/* webpackIgnore: true */ /* @vite-ignore */ `${resolveAmdNodeModulePath(PACKAGE, 'dist/cad-editor.js')}`) as CadEditorModule;
			const workerBase = resolveAmdNodeModulePath(PACKAGE, 'dist/');
			const workerPolicy = createTrustedTypesPolicy('saengineCadWorker', {
				createScriptURL(value: string) {
					if (!value.startsWith(workerBase)) {
						throw new Error(`Refusing to start a CAD worker from ${value}`);
					}
					return value;
				},
			});
			module.setTrustedTypesHost({
				html: value => sanitizeHtml(value, { allowedTags: { augment: CAD_UI_TAGS }, allowedAttributes: { augment: CAD_UI_ATTRIBUTES } }),
				scriptUrl: value => workerPolicy?.createScriptURL(value) ?? value,
			});
			return module;
		})();
		cadModule.catch(() => cadModule = undefined);
	}
	return cadModule;
}

let released: Promise<void> = Promise.resolve();
const hosts = new WeakMap<CadEditor, HTMLElement>();

/**
 * Starts the CAD editor in `container`. mlightcad allows one live editor per window, so editor
 * panes take it when they show an input and give it back with {@link releaseCadEditor} when they
 * stop; a second pane visible at the same time gets an error.
 */
export async function acquireCadEditor(container: HTMLElement, options?: { readonly chrome?: CadChrome; readonly background?: number }): Promise<CadEditor> {
	await released;
	const { createCadEditor } = await loadCadModule();
	// mlightcad leaves its canvas behind when destroyed: give each editor its own element.
	const host = append(container, $('.cad-instance'));
	try {
		const editor = createCadEditor({
			container: host,
			workerBaseUrl: resolveAmdNodeModulePath(PACKAGE, 'dist/'),
			assetBaseUrl: resolveAmdNodeModulePath(PACKAGE, 'dist/assets/'),
			chrome: options?.chrome,
			background: options?.background,
		});
		hosts.set(editor, host);
		return editor;
	} catch (error) {
		host.remove();
		throw error;
	}
}

export function releaseCadEditor(editor: CadEditor): void {
	released = released.then(() => editor.dispose()).catch(() => { }).finally(() => hosts.get(editor)?.remove());
}

/**
 * The CAD canvas background of `theme`: the editor background, so the drawing sits on the same
 * surface as the rest of the window. mlightcad draws ACI 7 linework black on light backgrounds and
 * white on dark ones.
 */
export function cadBackground(theme: IColorTheme): number {
	const color = theme.getColor(editorBackground) ?? Color.black;
	const { r, g, b } = color.rgba;
	return (r << 16) | (g << 8) | b;
}

/** Whether `theme` shows the CAD canvas light (for layer colours that read on it). */
export function isLightCanvas(theme: IColorTheme): boolean {
	return (theme.getColor(editorBackground) ?? Color.black).isLighter();
}
