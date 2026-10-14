/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * mlightcad builds parts of its UI with `innerHTML` and starts Web Workers from URL strings.
 * The build rewrites both (`x.innerHTML = trustedHtml(v)`, `new Worker(trustedScriptUrl(u))`),
 * so a host that enforces Trusted Types (the workbench) can supply its policies. Without
 * them, values pass through unchanged (plain web pages).
 */
export interface TrustedTypesHost {
	/** Sanitizes HTML and returns a TrustedHTML. */
	html(value: string): unknown;
	/** Checks a worker script URL and returns a TrustedScriptURL. */
	scriptUrl(value: string): unknown;
}

let host: TrustedTypesHost = { html: value => value, scriptUrl: value => value };

export function setTrustedTypesHost(value: TrustedTypesHost): void {
	host = value;
}

// Typed as string so the rewritten library code still type-checks its assignments.
export function trustedHtml(value: unknown): string {
	return host.html(String(value ?? '')) as string;
}

export function trustedScriptUrl(value: unknown): string {
	return host.scriptUrl(String(value)) as string;
}
