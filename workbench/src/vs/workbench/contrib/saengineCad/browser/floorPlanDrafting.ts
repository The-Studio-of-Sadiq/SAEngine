/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { findNodeAtLocation, Node, parseTree } from '../../../../base/common/json.js';
import { applyEdits, removeProperty, setProperty, withFormatting } from '../../../../base/common/jsonEdit.js';
import type { Edit, FormattingOptions } from '../../../../base/common/jsonFormatter.js';

/*
 * 2D drafting geometry (AutoCAD-like lines, polylines, arcs, circles) on the floor plan
 * (`05 Floor Plan/floor-plan.json`). Draft shapes belong to one story and are not structural members.
 */

export type DraftPoint = [number, number];

export type DraftShapeKind = 'line' | 'polyline' | 'arc' | 'circle';

export interface IDraftBase {
	readonly id: string;
	readonly story: string;
	readonly layer?: string;
}

export interface IDraftLine extends IDraftBase {
	readonly kind: 'line';
	readonly start: DraftPoint;
	readonly end: DraftPoint;
}

export interface IDraftPolyline extends IDraftBase {
	readonly kind: 'polyline';
	readonly points: readonly DraftPoint[];
	readonly closed?: boolean;
}

export interface IDraftArc extends IDraftBase {
	readonly kind: 'arc';
	readonly center: DraftPoint;
	readonly radius: number;
	readonly startAngle: number;
	readonly endAngle: number;
}

export interface IDraftCircle extends IDraftBase {
	readonly kind: 'circle';
	readonly center: DraftPoint;
	readonly radius: number;
}

export type IDraftShape = IDraftLine | IDraftPolyline | IDraftArc | IDraftCircle;

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoint(value: unknown): value is DraftPoint {
	return Array.isArray(value)
		&& value.length === 2
		&& typeof value[0] === 'number' && Number.isFinite(value[0])
		&& typeof value[1] === 'number' && Number.isFinite(value[1]);
}

/**
 * Reads 2D drafting geometry loosely from `layout`, optionally filtered to `storyId`.
 * Malformed entries (non-finite coordinates, invalid shape parameters, missing required fields) are skipped.
 */
export function draftsOf(layout: unknown, storyId?: string): IDraftShape[] {
	if (!isObject(layout) || !Array.isArray(layout.drafting)) {
		return [];
	}
	const result: IDraftShape[] = [];
	for (const item of layout.drafting) {
		if (!isObject(item)) {
			continue;
		}
		if (typeof item.id !== 'string' || !item.id) {
			continue;
		}
		if (typeof item.story !== 'string' || !item.story) {
			continue;
		}
		if (storyId !== undefined && item.story !== storyId) {
			continue;
		}
		const layer = typeof item.layer === 'string' && item.layer ? item.layer : 'DRAFT';
		switch (item.kind) {
			case 'line': {
				if (isPoint(item.start) && isPoint(item.end)) {
					result.push({
						kind: 'line',
						id: item.id,
						story: item.story,
						layer,
						start: [item.start[0], item.start[1]],
						end: [item.end[0], item.end[1]],
					});
				}
				break;
			}
			case 'polyline': {
				if (Array.isArray(item.points)) {
					const pts: DraftPoint[] = [];
					let allValid = true;
					for (const p of item.points) {
						if (isPoint(p)) {
							pts.push([p[0], p[1]]);
						} else {
							allValid = false;
							break;
						}
					}
					if (!allValid || pts.length < 2) {
						break;
					}
					const closed = Boolean(item.closed);
					if (closed && pts.length < 3) {
						break;
					}
					result.push({
						kind: 'polyline',
						id: item.id,
						story: item.story,
						layer,
						points: pts,
						closed,
					});
				}
				break;
			}
			case 'arc': {
				if (
					isPoint(item.center)
					&& typeof item.radius === 'number' && Number.isFinite(item.radius) && item.radius > 0
					&& typeof item.startAngle === 'number' && Number.isFinite(item.startAngle)
					&& typeof item.endAngle === 'number' && Number.isFinite(item.endAngle)
				) {
					result.push({
						kind: 'arc',
						id: item.id,
						story: item.story,
						layer,
						center: [item.center[0], item.center[1]],
						radius: item.radius,
						startAngle: item.startAngle,
						endAngle: item.endAngle,
					});
				}
				break;
			}
			case 'circle': {
				if (
					isPoint(item.center)
					&& typeof item.radius === 'number' && Number.isFinite(item.radius) && item.radius > 0
				) {
					result.push({
						kind: 'circle',
						id: item.id,
						story: item.story,
						layer,
						center: [item.center[0], item.center[1]],
						radius: item.radius,
					});
				}
				break;
			}
		}
	}
	return result;
}

const MEMBER_GROUPS = ['columns', 'beams', 'walls', 'slabs', 'footings', 'towers'] as const;

/**
 * Returns the next free draft id ("D1", "D2", ...) not clashing with existing drafts or member ids.
 */
export function nextDraftId(layout: unknown): string {
	const used = new Set<string>();
	if (isObject(layout)) {
		for (const group of MEMBER_GROUPS) {
			const list = layout[group];
			if (Array.isArray(list)) {
				for (const item of list) {
					if (isObject(item) && typeof item.id === 'string') {
						used.add(item.id);
					}
				}
			}
		}
		if (Array.isArray(layout.drafting)) {
			for (const item of layout.drafting) {
				if (isObject(item) && typeof item.id === 'string') {
					used.add(item.id);
				}
			}
		}
	}
	let n = 1;
	while (used.has(`D${n}`)) {
		n++;
	}
	return `D${n}`;
}

function guessFormattingOptions(text: string, override?: FormattingOptions): FormattingOptions {
	const eol = override?.eol ?? (text.includes('\r\n') ? '\r\n' : '\n');
	const insertSpaces = override?.insertSpaces ?? (!text.includes('\t'));
	const tabSize = override?.tabSize ?? (insertSpaces ? 2 : 4);
	return { tabSize, insertSpaces, eol };
}

function findDraftIndex(draftingNode: Node, id: string): number {
	if (!Array.isArray(draftingNode.children)) {
		return -1;
	}
	for (let i = 0; i < draftingNode.children.length; i++) {
		const child = draftingNode.children[i];
		const idNode = findNodeAtLocation(child, ['id']);
		if (idNode && idNode.value === id) {
			return i;
		}
	}
	return -1;
}

/**
 * Produces minimal JSON text edits for adding a draft shape to `floor-plan.json`.
 */
export function addDraftEdit(jsonText: string, draft: IDraftShape, options?: FormattingOptions): Edit[] {
	const formattingOptions = guessFormattingOptions(jsonText, options);
	const root = parseTree(jsonText);
	if (!root) {
		return [];
	}
	const draftingNode = findNodeAtLocation(root, ['drafting']);
	if (!draftingNode || draftingNode.type !== 'array') {
		return setProperty(jsonText, ['drafting'], [draft], formattingOptions);
	}
	return setProperty(jsonText, ['drafting', -1], draft, formattingOptions);
}

/**
 * Returns the new JSON text with `draft` appended to the floor plan's drafting array.
 */
export function addDraft(jsonText: string, draft: IDraftShape, options?: FormattingOptions): string {
	const edits = addDraftEdit(jsonText, draft, options);
	return edits.length > 0 ? applyEdits(jsonText, edits) : jsonText;
}

/**
 * Produces minimal JSON text edits for removing draft `id` from `floor-plan.json`.
 */
export function removeDraftEdit(jsonText: string, id: string, options?: FormattingOptions): Edit[] {
	const formattingOptions = guessFormattingOptions(jsonText, options);
	const root = parseTree(jsonText);
	if (!root) {
		return [];
	}
	const draftingNode = findNodeAtLocation(root, ['drafting']);
	if (!draftingNode || draftingNode.type !== 'array') {
		return [];
	}
	const index = findDraftIndex(draftingNode, id);
	if (index < 0) {
		return [];
	}
	return removeProperty(jsonText, ['drafting', index], formattingOptions);
}

/**
 * Returns the new JSON text without draft `id`.
 */
export function removeDraft(jsonText: string, id: string, options?: FormattingOptions): string {
	const edits = removeDraftEdit(jsonText, id, options);
	return edits.length > 0 ? applyEdits(jsonText, edits) : jsonText;
}

/**
 * Produces minimal JSON text edits for replacing an existing draft shape in `floor-plan.json`.
 */
export function replaceDraftEdit(jsonText: string, draft: IDraftShape, options?: FormattingOptions): Edit[] {
	const formattingOptions = guessFormattingOptions(jsonText, options);
	const root = parseTree(jsonText);
	if (!root) {
		return [];
	}
	const draftingNode = findNodeAtLocation(root, ['drafting']);
	if (!draftingNode || draftingNode.type !== 'array' || !Array.isArray(draftingNode.children)) {
		return [];
	}
	const index = findDraftIndex(draftingNode, draft.id);
	if (index < 0) {
		return [];
	}
	const targetNode = draftingNode.children[index];
	const content = JSON.stringify(draft);
	return withFormatting(jsonText, { offset: targetNode.offset, length: targetNode.length, content }, formattingOptions);
}

/**
 * Returns the new JSON text with the existing draft matching `draft.id` replaced.
 */
export function replaceDraft(jsonText: string, draft: IDraftShape, options?: FormattingOptions): string {
	const edits = replaceDraftEdit(jsonText, draft, options);
	return edits.length > 0 ? applyEdits(jsonText, edits) : jsonText;
}
