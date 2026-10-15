/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/** Creates the TrustedScriptURL the host's Trusted Types policy allows for a worker script. */
export interface TrustedTypesHost {
	readonly scriptUrl: (url: string) => unknown;
}

let host: TrustedTypesHost | undefined;

/** Connects the viewer to the host's Trusted Types policy (the workbench enforces them). */
export function setTrustedTypesHost(value: TrustedTypesHost): void {
	host = value;
}

/** Used by the bundle in place of a bare worker URL (see build.mjs). */
export function trustedScriptUrl(url: string | URL): string | URL {
	return host ? host.scriptUrl(String(url)) as string : url;
}
