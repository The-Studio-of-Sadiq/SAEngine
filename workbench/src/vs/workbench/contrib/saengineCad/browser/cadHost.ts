/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEditor } from '@saengine/cad-editor';
import { $, append, getWindow } from '../../../../base/browser/dom.js';
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

/** Id of the SVG filter that turns mlightcad's black canvas into a paper one (see cadEditor.css). */
const PAPER_FILTER_ID = 'saengine-cad-paper';
const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * Light themes show mlightcad's dark canvas through this filter. A plain inversion would turn
 * dark saturated linework (blue walls) almost white, so greys are inverted and darkened while
 * coloured pixels keep their hue and are only darkened by half their luma:
 * out = I + w (K - I), with I = f(1 - c) (an inversion that darkens faint greys),
 * K = c - 0.5 Y and w = clamp(8 |c - Y|^2).
 * All primitives are linear maps or the arithmetic composite, which the GPU runs per pixel.
 */
const PAPER_FILTER: ReadonlyArray<{ readonly tag: string; readonly attributes: Readonly<Record<string, string>>; readonly children?: ReadonlyArray<{ readonly tag: string; readonly attributes: Readonly<Record<string, string>> }> }> = [
	// d = 0.5 + 0.5 (c - Y)
	{ tag: 'feColorMatrix', attributes: { in: 'SourceGraphic', type: 'matrix', result: 'd', values: '0.3937 -0.3576 -0.0361 0 0.5  -0.1063 0.1424 -0.0361 0 0.5  -0.1063 -0.3576 0.4639 0 0.5  0 0 0 0 1' } },
	// (2d - 1)^2 = (c - Y)^2 per channel
	{ tag: 'feComposite', attributes: { in: 'd', in2: 'd', operator: 'arithmetic', k1: '4', k2: '-4', k3: '0', k4: '1', result: 'chroma' } },
	// w = clamp(8 sum of (c - Y)^2)
	{ tag: 'feColorMatrix', attributes: { in: 'chroma', type: 'matrix', result: 'w', values: '8 8 8 0 0  8 8 8 0 0  8 8 8 0 0  0 0 0 0 1' } },
	// e = 0.5 (K + c), so that K - I = 2e - 1
	{ tag: 'feColorMatrix', attributes: { in: 'SourceGraphic', type: 'matrix', result: 'e', values: '0.94685 -0.1788 -0.01805 0 0  -0.05315 0.8212 -0.01805 0 0  -0.05315 -0.1788 0.98195 0 0  0 0 0 0 1' } },
	// p = 0.5 + w (e - 0.5)
	{ tag: 'feComposite', attributes: { in: 'w', in2: 'e', operator: 'arithmetic', k1: '1', k2: '-0.5', k3: '0', k4: '0.5', result: 'p' } },
	// I = f(1 - c): inverted, with faint (dim) greys pulled darker so underlays stay visible on white
	{
		tag: 'feComponentTransfer', attributes: { in: 'SourceGraphic', result: 'i' }, children: ['feFuncR', 'feFuncG', 'feFuncB'].map(tag => ({ tag, attributes: { type: 'table', tableValues: '1 0.68 0.58 0.5 0.44 0.38 0.31 0.24 0.16 0.08 0' } }))
	},
	// out = I + 2p - 1 = I + w (K - I)
	{ tag: 'feComposite', attributes: { in: 'i', in2: 'p', operator: 'arithmetic', k1: '0', k2: '1', k3: '2', k4: '-1', result: 'paper' } },
	// keep the canvas's own transparency
	{ tag: 'feComposite', attributes: { in: 'paper', in2: 'SourceGraphic', operator: 'in' } },
];

const paperFilters = new WeakSet<Document>();

function svgElement(targetDocument: Document, tag: string, attributes: Readonly<Record<string, string>>): SVGElement {
	const element = targetDocument.createElementNS(SVG_NS, tag);
	for (const [name, value] of Object.entries(attributes)) {
		element.setAttribute(name, value);
	}
	return element;
}

/** Adds the paper filter to the window's document once; the CSS refers to it by id. */
function ensurePaperFilter(targetDocument: Document): void {
	if (paperFilters.has(targetDocument)) {
		return;
	}
	paperFilters.add(targetDocument);
	const svg = svgElement(targetDocument, 'svg', { width: '0', height: '0', 'aria-hidden': 'true', focusable: 'false', style: 'position: absolute; width: 0; height: 0; overflow: hidden; pointer-events: none;' });
	const filter = svgElement(targetDocument, 'filter', { id: PAPER_FILTER_ID, 'color-interpolation-filters': 'sRGB', x: '0', y: '0', width: '100%', height: '100%' });
	for (const primitive of PAPER_FILTER) {
		const element = svgElement(targetDocument, primitive.tag, primitive.attributes);
		for (const child of primitive.children ?? []) {
			element.appendChild(svgElement(targetDocument, child.tag, child.attributes));
		}
		filter.appendChild(element);
	}
	svg.appendChild(filter);
	targetDocument.body.appendChild(svg);
}

let released: Promise<void> = Promise.resolve();
const hosts = new WeakMap<CadEditor, HTMLElement>();

/**
 * Starts the CAD editor in `container`. mlightcad allows one live editor per window, so editor
 * panes take it when they show an input and give it back with {@link releaseCadEditor} when they
 * stop; a second pane visible at the same time gets an error.
 */
export async function acquireCadEditor(container: HTMLElement): Promise<CadEditor> {
	await released;
	const { createCadEditor } = await loadCadModule();
	ensurePaperFilter(getWindow(container).document);
	// mlightcad leaves its canvas behind when destroyed: give each editor its own element.
	const host = append(container, $('.cad-instance'));
	try {
		const editor = createCadEditor({
			container: host,
			workerBaseUrl: resolveAmdNodeModulePath(PACKAGE, 'dist/'),
			assetBaseUrl: resolveAmdNodeModulePath(PACKAGE, 'dist/assets/'),
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
