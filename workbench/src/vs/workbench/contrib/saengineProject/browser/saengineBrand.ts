/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import { localize } from '../../../../nls.js';
import { registerColor } from '../../../../platform/theme/common/colorUtils.js';
import { BrandArtNode, MARK_ART, MARK_VIEWBOX, WORDMARK_ART, WORDMARK_VIEWBOX } from './saengineBrandArt.js';

/*
 * The SAEngine brand colours (workbench/resources/brand/README.md) as theme colours, so SAEngine
 * Light / Dark (and any other theme) can set them. They colour the logo and brand headings only;
 * the UI's accent stays the theme's own. Text in brand ink or brand blue keeps WCAG AA contrast
 * on the editor and side bar backgrounds of the SAEngine themes (ink about 16:1, blue 5.9:1 light
 * and 6.9:1 dark).
 */
export const brandInk = registerColor('saengine.brandInk', { light: '#0A1F3D', dark: '#F2F5FA', hcDark: '#FFFFFF', hcLight: '#000000' }, localize('saengine.brandInk', "SAEngine brand ink: the logo's frame and wordmark, and brand headings."));
export const brandBlue = registerColor('saengine.brandBlue', { light: '#1A5FB4', dark: '#6EA8F2', hcDark: '#6EA8F2', hcLight: '#0B3C84' }, localize('saengine.brandBlue', "SAEngine brand blue, for brand text and highlights (not the UI accent)."));
export const brandFacadeTop = registerColor('saengine.brandFacadeTop', { light: '#1C6EC1', dark: '#4C94E8', hcDark: '#FFFFFF', hcLight: '#000000' }, localize('saengine.brandFacadeTop', "Top of the gradient of the facade in the SAEngine mark."));
export const brandFacadeBottom = registerColor('saengine.brandFacadeBottom', { light: '#0B3C84', dark: '#1F5FBF', hcDark: '#FFFFFF', hcLight: '#000000' }, localize('saengine.brandFacadeBottom', "Bottom of the gradient of the facade in the SAEngine mark."));
export const brandGrey = registerColor('saengine.brandGrey', { light: '#939AA3', dark: '#6B7686', hcDark: '#FFFFFF', hcLight: '#000000' }, localize('saengine.brandGrey', "SAEngine brand grey: the divider of the logo."));

const SVG = 'http://www.w3.org/2000/svg';
let copies = 0;

function build(document: Document, node: BrandArtNode, into: Element, id: string): void {
	const [tag, attributes, children] = node;
	const element = into.appendChild(document.createElementNS(SVG, tag));
	for (const [key, value] of Object.entries(attributes)) {
		element.setAttribute(key, value.replace(/\{id\}/g, id));
	}
	for (const child of children) {
		build(document, child, element, id);
	}
}

function render(parent: HTMLElement, art: BrandArtNode, viewBox: string, className: string, label?: string): SVGSVGElement {
	const document = parent.ownerDocument;
	const svg = parent.appendChild(document.createElementNS(SVG, 'svg'));
	svg.setAttribute('viewBox', viewBox);
	svg.setAttribute('class', `sa-brand-art ${className}`);
	if (label) {
		svg.setAttribute('role', 'img');
		svg.setAttribute('aria-label', label);
	} else {
		svg.setAttribute('aria-hidden', 'true');
	}
	build(document, art, svg, `sa-brand-${++copies}`);
	return svg;
}

/** The SAEngine mark (building frame and meshed facade), in the active theme's brand colours. */
export function renderBrandMark(parent: HTMLElement, className = 'mark'): SVGSVGElement {
	return render(parent, MARK_ART, MARK_VIEWBOX, className);
}

/** The "SAEngine" wordmark as outlines (it needs no font), labelled for screen readers. */
export function renderBrandWordmark(parent: HTMLElement, label: string = localize('saengine.name', "SAEngine"), className = 'wordmark'): SVGSVGElement {
	return render(parent, WORDMARK_ART, WORDMARK_VIEWBOX, className, label);
}
