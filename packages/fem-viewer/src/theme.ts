/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';

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

/** How far node markers fade towards the background: present, but quieter than the members. */
const NODE_FADE = 0.45;

/**
 * The colour of the node markers: the host's node colour (its foreground) faded towards the
 * background, so a dense mesh reads as members with quiet joints in either theme, while the
 * supports and the selection keep their full colours.
 */
export function subtleNodeColor(node: string, background: string): THREE.Color {
	return new THREE.Color(node).lerp(new THREE.Color(background), NODE_FADE);
}

let roundPoint: THREE.Texture | undefined;

/** A round mask for point markers (three.js draws points as squares), shared by every viewer. */
export function roundPointTexture(): THREE.Texture {
	if (!roundPoint) {
		const size = 32;
		const data = new Uint8Array(size * size * 4);
		const centre = (size - 1) / 2;
		for (let y = 0; y < size; y++) {
			for (let x = 0; x < size; x++) {
				const distance = Math.hypot(x - centre, y - centre) / (size / 2);
				// A soft edge of about one texel keeps small dots smooth.
				const alpha = Math.max(0, Math.min(1, (1 - distance) * size / 2));
				const i = (y * size + x) * 4;
				data[i] = data[i + 1] = data[i + 2] = 255;
				data[i + 3] = Math.round(alpha * 255);
			}
		}
		roundPoint = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
		roundPoint.magFilter = THREE.LinearFilter;
		roundPoint.minFilter = THREE.LinearFilter;
		roundPoint.needsUpdate = true;
	}
	return roundPoint;
}

/** Material of round, screen-sized point markers. */
export function roundPointMaterial(color: THREE.ColorRepresentation, size: number, options: { readonly depthTest?: boolean } = {}): THREE.PointsMaterial {
	return new THREE.PointsMaterial({
		color, size, sizeAttenuation: false, map: roundPointTexture(), transparent: true, alphaTest: 0.2,
		depthTest: options.depthTest ?? true,
	});
}
