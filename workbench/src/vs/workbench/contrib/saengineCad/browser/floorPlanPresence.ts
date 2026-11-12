/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEntitySpec, CadGeneratedDrawing, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { ICoEditingColleague } from '../../../services/saengineProject/common/coEditingPresence.js';
import { IMemberShape } from './floorPlanDrawing.js';

/*
 * Live co-editing presence on the floor plan: each colleague's selected members outlined in
 * their colour, a little outside the member so its own lines stay visible, with their name
 * above the first one. Drawn with the plan (generated, not pickable); colleagues selecting
 * members on another storey show nothing here.
 */

/** How far outside a member its colleague outline runs [mm]. */
const PRESENCE_OFFSET = 120;
/** Text height of the colleague's name [mm], a little under the member labels'. */
const PRESENCE_TEXT = 220;

/** The AutoCAD colours a colleague's colour is drawn in (layers carry ACI colours). */
const ACI_COLORS: readonly (readonly [aci: number, rgb: readonly [number, number, number]])[] = [
	[1, [255, 0, 0]],
	[2, [255, 255, 0]],
	[3, [0, 255, 0]],
	[4, [0, 255, 255]],
	[5, [0, 0, 255]],
	[6, [255, 0, 255]],
	[30, [255, 127, 0]],
];

/** The AutoCAD Color Index nearest to `#rrggbb` (magenta for a missing or unreadable colour). */
export function nearestAci(color: string | undefined): number {
	const match = color && /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color.trim());
	if (!match) {
		return 6;
	}
	const [r, g, b] = [match[1], match[2], match[3]].map(h => parseInt(h, 16));
	let best = ACI_COLORS[0];
	let distance = Infinity;
	for (const entry of ACI_COLORS) {
		const [er, eg, eb] = entry[1];
		const d = (r - er) ** 2 + (g - eg) ** 2 + (b - eb) ** 2;
		if (d < distance) {
			[best, distance] = [entry, d];
		}
	}
	return best[0];
}

/** `points` (a simple polygon) moved `offset` outward along its edges, mitred at the corners. */
export function offsetPolygon(points: readonly CadPoint[], offset: number): CadPoint[] {
	const n = points.length;
	if (n < 3) {
		return [...points];
	}
	let area = 0;
	for (let i = 0; i < n; i++) {
		const [a, b] = [points[i], points[(i + 1) % n]];
		area += a[0] * b[1] - b[0] * a[1];
	}
	// Outward is right of each edge for a counter-clockwise polygon, left for a clockwise one.
	const side = area >= 0 ? 1 : -1;
	const normal = (a: CadPoint, b: CadPoint): CadPoint => {
		const [dx, dy] = [b[0] - a[0], b[1] - a[1]];
		const length = Math.hypot(dx, dy) || 1;
		return [side * dy / length, -side * dx / length];
	};
	return points.map((p, i) => {
		const [n1, n2] = [normal(points[(i - 1 + n) % n], p), normal(p, points[(i + 1) % n])];
		// The mitre (n1 + n2) / (1 + n1·n2), at most four offsets long on very sharp corners.
		const dot = 1 + n1[0] * n2[0] + n1[1] * n2[1];
		let [mx, my] = dot > 1e-9 ? [(n1[0] + n2[0]) / dot, (n1[1] + n2[1]) / dot] : [n1[0], n1[1]];
		const length = Math.hypot(mx, my);
		if (length > 4) {
			[mx, my] = [mx * 4 / length, my * 4 / length];
		}
		return [p[0] + mx * offset, p[1] + my * offset] as CadPoint;
	});
}

/** The layer of the colleagues drawn in ACI colour `aci`. */
function presenceLayer(aci: number): CadLayerSpec {
	return { name: `SAENGINE-PRESENCE-${aci}`, color: aci, description: 'Live co-editing: what colleagues have selected' };
}

/** The colleagues' selected members among `members` (this storey's), outlined in their colours. */
export function presenceDrawing(members: readonly IMemberShape[], colleagues: readonly ICoEditingColleague[]): CadGeneratedDrawing {
	const layers = new Map<number, CadLayerSpec>();
	const entities: CadEntitySpec[] = [];
	for (const colleague of colleagues) {
		const ids = new Set(colleague.selection);
		const selected = members.filter(m => ids.has(m.id));
		if (!selected.length) {
			continue;
		}
		const aci = nearestAci(colleague.color);
		const layer = presenceLayer(aci);
		layers.set(aci, layer);
		let top: CadPoint | undefined;
		for (const member of selected) {
			const outline = member.outline;
			if (outline.kind === 'circle') {
				entities.push({ kind: 'circle', layer: layer.name, center: outline.center, radius: outline.radius + PRESENCE_OFFSET });
				top ??= [outline.center[0], outline.center[1] + outline.radius + PRESENCE_OFFSET];
			} else {
				const points = offsetPolygon(outline.points, PRESENCE_OFFSET);
				entities.push({ kind: 'polyline', layer: layer.name, points, closed: true });
				if (!top) {
					const xs = points.map(p => p[0]);
					top = [(Math.min(...xs) + Math.max(...xs)) / 2, Math.max(...points.map(p => p[1]))];
				}
			}
		}
		if (top && colleague.name) {
			entities.push({ kind: 'text', layer: layer.name, position: [top[0], top[1] + PRESENCE_TEXT], height: PRESENCE_TEXT, text: colleague.name });
		}
	}
	return { layers: [...layers.values()], entities };
}
