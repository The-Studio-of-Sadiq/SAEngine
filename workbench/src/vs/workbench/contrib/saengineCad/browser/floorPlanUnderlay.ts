/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadPoint } from '@saengine/cad-editor';
import { localize } from '../../../../nls.js';
import { ISnapSegment } from './floorPlanSnap.js';

/*
 * The architect's drawing under a story (`underlays` of `floor-plan.json`): where it sits and how
 * it is calibrated. A DXF or DWG is in its own units, a PDF page in paper mm (so a 1:100 plan has a
 * scale of 100). The CAD editor inserts it as a block: each drawing point p lands at
 * offset + R(rotation) · (scale · p). Calibrating, moving and rotating change those three numbers
 * and nothing else; a locked underlay refuses all three.
 *
 * Also the model workbook's (Excel round trip) diff, as the lines its preview shows.
 */

type Json = { readonly [key: string]: unknown };

export interface IUnderlayPlacement {
	readonly offset: CadPoint;
	readonly scale: number;
	/** [°], counter-clockwise. */
	readonly rotation: number;
}

const num = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback;

export function isPdf(file: unknown): boolean {
	return typeof file === 'string' && /\.pdf$/i.test(file);
}

/** Alpha 9 L2: a laser scan (LAS, XYZ, PTS; LAZ and E57 need a library the backend says it lacks). */
export function isPointCloud(file: unknown): boolean {
	return typeof file === 'string' && /\.(las|laz|e57|xyz|pts)$/i.test(file);
}

/** The scale a point cloud starts at: scans are usually in metres. */
export const DEFAULT_CLOUD_SCALE = 1000;

/** What the backend slices of a point cloud underlay, in the scan's units. */
export interface ICloudSlice {
	readonly cut: number;
	readonly thickness: number;
	readonly voxel: number;
}

/** The cut height of a point cloud slice above the story's floor when none is set [mm]. */
export const DEFAULT_CLOUD_CUT = 1200;
/** The thickness of a point cloud slice when none is set [mm]. */
export const DEFAULT_CLOUD_THICKNESS = 100;

/**
 * The slice of a point cloud underlay of a story whose floor is at `floor` [mm] (the level of the
 * story below: a story's elevation is its top, where its beams are): its cut height
 * (`cutHeight`, default 1200 mm) above that floor, its thickness (100 mm) and point spacing (20 mm), all in mm
 * on the plan, turned into the scan's units by the underlay's scale (scan units to mm) and moved
 * by the scan's own height of ±0 (`elevationOffset`, in the scan's units).
 */
export function cloudSlice(underlay: Json, floor: number): ICloudSlice {
	const scale = num(underlay.scale, 1) > 0 ? num(underlay.scale, 1) : 1;
	const cut = (floor + num(underlay.cutHeight, DEFAULT_CLOUD_CUT)) / scale + num(underlay.elevationOffset, 0);
	const thickness = num(underlay.sliceThickness, DEFAULT_CLOUD_THICKNESS) > 0 ? num(underlay.sliceThickness, DEFAULT_CLOUD_THICKNESS) : DEFAULT_CLOUD_THICKNESS;
	return { cut, thickness: thickness / scale, voxel: Math.max(0, num(underlay.pointSpacing, 20)) / scale };
}

export function placementOf(underlay: Json): IUnderlayPlacement {
	const scale = num(underlay.scale, 1);
	return { offset: [num(underlay.dx, 0), num(underlay.dy, 0)], scale: scale > 0 ? scale : 1, rotation: num(underlay.rotation, 0) };
}

/**
 * The floor level [mm] of a story among `stories` (lowest first, elevations at their tops): the
 * elevation of the story below it, or its own for the lowest story (the base, with nothing below).
 */
export function storyFloor(stories: readonly { readonly id: string; readonly elevation: number }[], story: string | undefined): number {
	const index = stories.findIndex(s => s.id === story);
	if (index < 0) {
		return 0;
	}
	return index > 0 ? stories[index - 1].elevation : stories[index].elevation;
}

/** The scale a PDF page starts at when its text states none: 1:100, the usual plan scale. */
export const DEFAULT_PDF_SCALE = 100;

/**
 * Where a newly attached PDF page goes before it is calibrated: at the drawing scale its text
 * states (`stated`, the backend's "1:N"), else {@link DEFAULT_PDF_SCALE}, with the page's centre
 * (`size`: paper mm) on `centre` (the middle of the plan's grid), so it shows near its size and
 * place instead of as a speck in paper mm.
 */
export function firstPdfPlacement(size: unknown, stated: unknown, centre: CadPoint): IUnderlayPlacement {
	const scale = num(stated, 0) > 0 ? num(stated, 0) : DEFAULT_PDF_SCALE;
	const [w, h] = Array.isArray(size) ? [num(size[0], 0), num(size[1], 0)] : [0, 0];
	return { offset: [centre[0] - scale * w / 2, centre[1] - scale * h / 2], scale, rotation: 0 };
}

/** The middle of the plan's grid lines (`grids.x`, `grids.y` positions), [0, 0] without any. */
export function gridCentre(layout: unknown): CadPoint {
	const grids = typeof layout === 'object' && layout ? (layout as Json).grids : undefined;
	const middle = (axis: string) => {
		const lines = typeof grids === 'object' && grids ? (grids as Json)[axis] : undefined;
		const at = Array.isArray(lines) ? lines.map(g => num(typeof g === 'object' && g ? (g as Json).position : undefined, NaN)).filter(Number.isFinite) : [];
		return at.length ? (Math.min(...at) + Math.max(...at)) / 2 : 0;
	};
	return [middle('x'), middle('y')];
}

/** The placement as the underlay's fields, rounded as the floor plan stores them. */
export function placementFields(placement: IUnderlayPlacement): { dx: number; dy: number; scale: number; rotation: number } {
	const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits || 0;
	const rotation = ((placement.rotation % 360) + 540) % 360 - 180;
	return { dx: round(placement.offset[0], 1), dy: round(placement.offset[1], 1), scale: round(placement.scale, 6), rotation: round(rotation, 4) };
}

/** Where drawing point `p` lands on the plan. */
export function toPlan(placement: IUnderlayPlacement, [x, y]: CadPoint): CadPoint {
	const a = placement.rotation * Math.PI / 180;
	const [c, s] = [Math.cos(a), Math.sin(a)];
	const [sx, sy] = [x * placement.scale, y * placement.scale];
	return [placement.offset[0] + c * sx - s * sy, placement.offset[1] + s * sx + c * sy];
}

/**
 * The placement scaled so that the plan points `a` and `b` (on the underlay as it is shown now)
 * end up `known` mm apart, `a` staying where it is. Undefined when the points coincide.
 */
export function calibrated(placement: IUnderlayPlacement, a: CadPoint, b: CadPoint, known: number): IUnderlayPlacement | undefined {
	const measured = Math.hypot(b[0] - a[0], b[1] - a[1]);
	if (!(measured > 1e-9) || !(known > 0)) {
		return undefined;
	}
	const k = known / measured;
	return {
		offset: [a[0] - k * (a[0] - placement.offset[0]), a[1] - k * (a[1] - placement.offset[1])],
		scale: placement.scale * k,
		rotation: placement.rotation,
	};
}

/** The placement moved by `to - from`. */
export function moved(placement: IUnderlayPlacement, from: CadPoint, to: CadPoint): IUnderlayPlacement {
	return { ...placement, offset: [placement.offset[0] + to[0] - from[0], placement.offset[1] + to[1] - from[1]] };
}

/** The placement turned by `degrees` (counter-clockwise) about the plan point `base`. */
export function rotated(placement: IUnderlayPlacement, base: CadPoint, degrees: number): IUnderlayPlacement {
	const a = degrees * Math.PI / 180;
	const [c, s] = [Math.cos(a), Math.sin(a)];
	const [x, y] = [placement.offset[0] - base[0], placement.offset[1] - base[1]];
	return { ...placement, offset: [base[0] + c * x - s * y, base[1] + s * x + c * y], rotation: placement.rotation + degrees };
}

/** The angle that turns the line from `a` to `b` onto the nearest axis [°]: aligning a drawn wall with the grid. */
export function alignAngle(a: CadPoint, b: CadPoint): number {
	const angle = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI;
	return Math.round(angle / 90) * 90 - angle;
}

/** The underlay's lines (`[x1, y1, x2, y2]` in drawing units) on the plan, for object snaps. */
export function planSegments(placement: IUnderlayPlacement, segments: unknown): ISnapSegment[] {
	if (!Array.isArray(segments)) {
		return [];
	}
	const id = localize('underlay.snapName', "the underlay");
	const out: ISnapSegment[] = [];
	for (const s of segments) {
		if (Array.isArray(s) && s.length === 4 && s.every(v => typeof v === 'number' && Number.isFinite(v))) {
			out.push({ id, start: toPlan(placement, [s[0], s[1]]), end: toPlan(placement, [s[2], s[3]]) });
		}
	}
	return out;
}

/**
 * The segments passing within `reach` of `point` (by their bounding boxes), at most `limit` of
 * them: a page has tens of thousands of lines and the snaps look at every pair of the ones given.
 */
export function segmentsNear(segments: readonly ISnapSegment[], point: CadPoint, reach: number, limit = 60): ISnapSegment[] {
	const out: ISnapSegment[] = [];
	const [x, y] = point;
	for (const s of segments) {
		if (Math.min(s.start[0], s.end[0]) - reach <= x && x <= Math.max(s.start[0], s.end[0]) + reach
			&& Math.min(s.start[1], s.end[1]) - reach <= y && y <= Math.max(s.start[1], s.end[1]) + reach) {
			out.push(s);
			if (out.length >= limit) {
				break;
			}
		}
	}
	return out;
}

// ───────────────────────────── the model workbook's diff ─────────────────────────────

export interface IWorkbookChange {
	readonly id: string;
	readonly fields: readonly { readonly field: string; readonly old: unknown; readonly new: unknown }[];
}

export interface IWorkbookSheetDiff {
	readonly added: readonly string[];
	readonly removed: readonly string[];
	readonly changed: readonly IWorkbookChange[];
}

export interface IWorkbookImport {
	readonly ok: boolean;
	readonly problems: readonly string[];
	readonly diff: { readonly [sheet: string]: IWorkbookSheetDiff };
	/** The new text of each changed file: `floorPlan`, `objects`, `loads`. */
	readonly texts: { readonly [file: string]: string };
	readonly changed: readonly string[];
}

export function readWorkbookImport(value: unknown): IWorkbookImport {
	const v = typeof value === 'object' && value !== null ? value as Json : {};
	const strings = (x: unknown) => Array.isArray(x) ? x.map(String) : [];
	const diff: { [sheet: string]: IWorkbookSheetDiff } = {};
	if (typeof v.diff === 'object' && v.diff !== null) {
		for (const [sheet, d] of Object.entries(v.diff as Json)) {
			const s = typeof d === 'object' && d !== null ? d as Json : {};
			const changed = Array.isArray(s.changed) ? s.changed.filter((c): c is Json => typeof c === 'object' && c !== null).map(c => ({
				id: String(c.id),
				fields: Array.isArray(c.fields) ? c.fields.filter((f): f is Json => typeof f === 'object' && f !== null).map(f => ({ field: String(f.field), old: f.old, new: f.new })) : [],
			})) : [];
			diff[sheet] = { added: strings(s.added), removed: strings(s.removed), changed };
		}
	}
	const texts: { [file: string]: string } = {};
	if (typeof v.texts === 'object' && v.texts !== null) {
		for (const [file, text] of Object.entries(v.texts as Json)) {
			if (typeof text === 'string') {
				texts[file] = text;
			}
		}
	}
	return { ok: v.ok === true, problems: strings(v.problems), diff, texts, changed: strings(v.changed) };
}

const shown = (value: unknown) => value === null || value === undefined || value === '' ? localize('workbook.empty', "(empty)") : String(value);

/** The preview's lines, a sheet at a time: "Beams: added B12", "Grids: A: position 0 → 150". */
export function diffLines(diff: IWorkbookImport['diff']): { readonly sheet: string; readonly kind: 'added' | 'removed' | 'changed'; readonly text: string }[] {
	const lines: { sheet: string; kind: 'added' | 'removed' | 'changed'; text: string }[] = [];
	for (const [sheet, d] of Object.entries(diff)) {
		d.added.forEach(id => lines.push({ sheet, kind: 'added', text: localize('workbook.added', "Added {0}", id) }));
		d.removed.forEach(id => lines.push({ sheet, kind: 'removed', text: localize('workbook.removed', "Deleted {0}", id) }));
		d.changed.forEach(c => lines.push({
			sheet, kind: 'changed',
			text: c.fields.length
				? localize('workbook.changed', "{0}: {1}", c.id, c.fields.map(f => `${f.field} ${shown(f.old)} → ${shown(f.new)}`).join('; '))
				: localize('workbook.changedOrder', "{0}: changed", c.id),
		}));
	}
	return lines;
}

/** "3 added, 1 deleted, 12 changed". */
export function diffSummary(diff: IWorkbookImport['diff']): string {
	let [added, removed, changed] = [0, 0, 0];
	for (const d of Object.values(diff)) {
		added += d.added.length;
		removed += d.removed.length;
		changed += d.changed.length;
	}
	return localize('workbook.summary', "{0} added, {1} deleted, {2} changed", added, removed, changed);
}
