/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/**
 * A theme from the host as three.js can use it: entries the host has no colour for are dropped
 * (so the viewer keeps its current or default colour instead of turning black), and CSS
 * `#rrggbbaa` colours, which three.js rejects, lose their alpha.
 */
export function usableTheme<T extends object>(theme: Partial<T> | undefined): Partial<T> {
	const result: Record<string, string> = {};
	for (const [key, value] of Object.entries(theme ?? {})) {
		if (typeof value === 'string' && value) {
			result[key] = /^#[0-9a-f]{8}$/i.test(value) ? value.slice(0, 7) : value;
		}
	}
	return result as Partial<T>;
}
