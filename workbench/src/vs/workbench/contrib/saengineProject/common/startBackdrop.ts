/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Whether the window may show the acrylic backdrop behind the Start page: only while no project
 * is open, never in a high-contrast theme, and not when Windows turns transparency effects off.
 */
export function wantsAcrylic(projectOpen: boolean, highContrast: boolean, reducedTransparency: boolean): boolean {
	return !projectOpen && !highContrast && !reducedTransparency;
}
