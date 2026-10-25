/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/** A grid line of the floor plan (as in `floor-plan.json`). */
export interface IGridLine {
	readonly label: string;
	readonly position: number;
}

/** Grid labels as on Bangladeshi drawings and the sample: A, B, ... Z, AA, AB, ... across X; 1, 2, 3 ... along Y. */
export function gridLabel(axis: 'x' | 'y', index: number): string {
	if (axis === 'y') {
		return String(index + 1);
	}
	let label = '';
	for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
		label = String.fromCharCode(65 + (n - 1) % 26) + label;
	}
	return label;
}

/** "A" -> "B", "Z" -> "AA", "AZ" -> "BA" (spreadsheet-style column letters). */
export function nextLetters(label: string): string {
	const chars = label.toUpperCase().split('');
	for (let i = chars.length - 1; i >= 0; i--) {
		if (chars[i] !== 'Z') {
			chars[i] = String.fromCharCode(chars[i].charCodeAt(0) + 1);
			return chars.join('');
		}
		chars[i] = 'A';
	}
	return 'A' + chars.join('');
}

/** The label after `label`: "3" -> "4", "AZ" -> "BA", anything else gets a 1 ("A1" -> "A11"). */
export function nextGridLabel(label: string): string {
	return /^\d+$/.test(label) ? String(Number(label) + 1) : /^[A-Za-z]+$/.test(label) ? nextLetters(label) : `${label}1`;
}
