/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/** ACI 9: the light grey an architect's underlay is drawn in, well behind the model's own linework. */
export const UNDERLAY_ACI = 9;

/**
 * `dxf` with every colour turned to {@link UNDERLAY_ACI}: each colour number (group 62; a layer
 * that is off keeps its sign) and no true colours or colour names (groups 420 and 430), so its
 * layers, blocks and entities all draw grey. The underlay alone is greyed this way; mlightcad's
 * compare display greys the whole view, the model with it.
 */
export function greyDxf(dxf: string): string {
	const lines = dxf.split(/\r?\n/);
	const out: string[] = [];
	for (let i = 0; i + 1 < lines.length; i += 2) {
		const code = lines[i].trim();
		const value = lines[i + 1];
		if (code === '420' || code === '430') {
			continue;
		}
		out.push(lines[i], code === '62' ? (value.trim().startsWith('-') ? `-${UNDERLAY_ACI}` : String(UNDERLAY_ACI)) : value);
	}
	if (lines.length % 2) {
		out.push(lines[lines.length - 1]);
	}
	return out.join('\n');
}
