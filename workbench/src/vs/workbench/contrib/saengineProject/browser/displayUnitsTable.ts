/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { activeDisplayUnits, convertText, IDisplayUnits, isConverted, significantText, toDisplay } from '../../../services/saengineProject/common/displayUnits.js';

/**
 * C13b: the quantities the texts under `root` write in SI ("142 kPa", "500 mm bored pile", "Ø16 @
 * 150") in the display units ({@link convertText}), for the editors that compose their readouts
 * from SAEngine's SI texts (substructure, soil, MEP, architecture, section designer). Text a user
 * edits (a textarea, an editable element) and the values of inputs are never touched; nothing
 * changes in SI. Run after the panel is drawn (a microtask later).
 */
export function convertTextNodes(root: HTMLElement | undefined, display: IDisplayUnits = activeDisplayUnits()): void {
	if (!root || display.system !== 'USCustomary') {
		return;
	}
	queueMicrotask(() => {
		const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
		const texts: Text[] = [];
		for (let node = walker.nextNode(); node; node = walker.nextNode()) {
			const parent = node.parentElement;
			if (parent && !parent.closest('textarea, [contenteditable="true"], script, style')) {
				texts.push(node as Text);
			}
		}
		for (const text of texts) {
			const before = text.data;
			const after = convertText(before, display);
			if (after !== before) {
				text.data = after;
			}
		}
	});
}

/** A plain number as the editors' tables write one: "1,250", "-12.50". */
const PLAIN_NUMBER = /^\s*(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*$/;

/**
 * C13b: the cells of a result table whose column has a unit SAEngine converts (`units[k]`: the SI
 * unit of column k, "kN", "mm", "m"), in the display units once the rows are in (a microtask after
 * the table is drawn). Only a cell that is a plain number is converted (an input field shows its
 * value in the display units itself, a "—" or a text stays); nothing changes in SI.
 */
export function convertTableCells(table: HTMLElement, units: readonly (string | undefined)[], display: IDisplayUnits = activeDisplayUnits()): void {
	if (!units.some(u => u && isConverted(u, display))) {
		return;
	}
	queueMicrotask(() => {
		const rows = Array.from(table.children).filter(c => c.tagName === 'TBODY').flatMap(body => Array.from(body.children));
		for (const row of rows) {
			const cells = Array.from(row.children).filter((c): c is HTMLElement => c.tagName === 'TD');
			let column = 0;
			for (const cell of cells) {
				const unit = units[column];
				column += Math.max(1, Number(cell.getAttribute('colspan') ?? 1));
				if (!unit || !isConverted(unit, display) || cell.children.length) {
					continue;
				}
				const match = PLAIN_NUMBER.exec(cell.textContent ?? '');
				if (match) {
					cell.textContent = significantText(toDisplay(Number(match[1].replace(/,/g, '')), unit, display), 4);
				}
			}
		}
	});
}
