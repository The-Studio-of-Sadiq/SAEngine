/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { MemberGroup } from './modelSelection.js';

/*
 * Reading the members of the floor plan (`05 Floor Plan/floor-plan.json`) as the Model Explorer,
 * the Members Table and the floor plan show them: its stories, where a member is in grid labels,
 * and which story's plan shows it.
 */

type Json = { readonly [key: string]: unknown };

export interface IFloorPlanStory {
	readonly id: string;
	readonly name: string;
	readonly elevation: number;
}

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isObject) : [];
}

/** The stories of the floor plan, lowest first (a story without a name is named by its id). */
export function storiesOf(layout: unknown): IFloorPlanStory[] {
	return list(isObject(layout) ? layout.stories : undefined)
		.filter(s => typeof s.id === 'string' && typeof s.elevation === 'number' && Number.isFinite(s.elevation))
		.map(s => ({ id: s.id as string, name: typeof s.name === 'string' && s.name ? s.name : s.id as string, elevation: s.elevation as number }))
		.sort((a, b) => a.elevation - b.elevation);
}

/** Columns and walls rise from a base story to a top story; the other members are at one story. */
export function rises(group: MemberGroup): boolean {
	return group === 'columns' || group === 'walls';
}

/** A grid point in labels: "A-1", with its offset in mm when it has one ("A-1 (+150, 0)"). */
export function formatPoint(value: unknown): string {
	if (!isObject(value)) {
		return '?';
	}
	const [dx, dy] = [Number(value.dx) || 0, Number(value.dy) || 0];
	const at = `${value.x}-${value.y}`;
	const signed = (v: number) => v > 0 ? `+${v}` : String(v);
	return dx || dy ? `${at} (${signed(dx)}, ${signed(dy)})` : at;
}

/** A slab's outline: "A–B / 1–2" for a bay, else its corners. */
function formatBoundary(boundary: unknown): string {
	const points = list(boundary);
	const plain = points.every(p => !p.dx && !p.dy);
	const xs = [...new Set(points.map(p => String(p.x)))];
	const ys = [...new Set(points.map(p => String(p.y)))];
	if (points.length === 4 && plain && xs.length === 2 && ys.length === 2) {
		return `${xs.join('–')} / ${ys.join('–')}`;
	}
	return points.map(formatPoint).join(' · ');
}

/** Where a member is, in grid labels: "A-1", "A-1 (+150, 0)", "A-1 → B-1", "A–B / 1–2". */
export function location(group: MemberGroup, member: Json): string {
	switch (group) {
		case 'columns':
		case 'footings':
			return formatPoint(member.at);
		case 'slabs':
			return formatBoundary(member.boundary);
		default:
			return `${formatPoint(member.start)} → ${formatPoint(member.end)}`;
	}
}

/**
 * Whether the plan of `story` shows `member`: a column or wall rising through it to its top
 * (base below the story, top at or above it), any other member at it.
 */
export function onPlanOf(group: MemberGroup, member: Json, story: IFloorPlanStory, stories: readonly IFloorPlanStory[]): boolean {
	if (rises(group)) {
		const base = stories.find(s => s.id === member.base);
		const top = stories.find(s => s.id === member.top);
		return !!base && !!top && base.elevation < story.elevation && story.elevation <= top.elevation;
	}
	return member.story === story.id;
}
