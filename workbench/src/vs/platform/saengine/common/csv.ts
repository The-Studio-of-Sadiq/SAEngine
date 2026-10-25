/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/** One CSV field (RFC 4180): quoted only when it holds a quote, comma or line break; `undefined` is empty. */
export function csvField(value: string | number | undefined): string {
	const text = value === undefined ? '' : String(value);
	return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Rows as CSV text (RFC 4180): CRLF line ends, one after the last row too; an empty row is a blank line. */
export function csvText(rows: readonly (readonly (string | number | undefined)[])[]): string {
	return rows.map(row => row.map(csvField).join(',')).join('\r\n') + '\r\n';
}
