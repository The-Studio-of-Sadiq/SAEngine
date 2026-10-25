/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/floorPlanLoads.css';
import type { CadEntitySpec, CadLayerSpec, CadPoint } from '@saengine/cad-editor';
import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Checkbox } from '../../../../base/browser/ui/toggle/toggle.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { defaultCheckboxStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { propertyLink } from '../../saengineModel/browser/propertySheetView.js';
import { appendPropertyHeading, appendPropertyRow, appendPropertyNote } from '../../saengineProject/browser/editorFrame.js';
import { storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { gridsOf, MemberGroup } from './floorPlanDrawing.js';
import { familyOf, masterOf } from './floorPlanTypical.js';

/*
 * Line and point loads on members (`05 Floor Plan/loads.json`, read by the analysis model through
 * `saengine.library.line_loads` and `saengine.fem.member_loads`): brick walls on beams entered as
 * a wall type × height (kN/m = the wall's weight per m² × height, less openings) or as kN/m, and
 * point loads on a beam or at a column's joint. The file sits beside the floor plan and is kept
 * apart from it: the floor plan is the geometry, these are loads.
 *
 * Typical floors: a load entered on a story of a family applies to the member at the same place on
 * every story of the family (as members follow the typical floor), unless it is for "this story
 * only". Family-wide loads are stored on the master story's member, so a family has each once.
 *
 * Units: mm, kN/m, kN, kN/m³ (as the Python model).
 */

type Json = { readonly [key: string]: unknown };

export const LOADS_FILE = 'loads.json';
export const LOADS_SCHEMA = 'saengine.memberLoads/1';

export type LoadCase = 'D' | 'SD' | 'L' | 'Lr';

/** The gravity cases a member load goes to; superimposed dead (SD) first, the default. */
export const LOAD_CASES: readonly { readonly id: LoadCase; readonly label: string }[] = [
	{ id: 'SD', label: localize('loads.caseSD', "SD: superimposed dead") },
	{ id: 'D', label: localize('loads.caseD', "D: dead") },
	{ id: 'L', label: localize('loads.caseL', "L: live") },
	{ id: 'Lr', label: localize('loads.caseLr', "Lr: roof live") },
];

export interface IWallType {
	readonly id: string;
	readonly name: string;
	/** Masonry thickness without plaster [mm]. */
	readonly thickness: number;
	/** Of the masonry [kN/m³]. */
	readonly unitWeight: number;
	/** Plaster on each face [mm]. */
	readonly plaster?: number;
	readonly plasterFaces?: number;
	/** [kN/m³] */
	readonly plasterUnitWeight?: number;
}

export interface IWallLoad {
	readonly type: string;
	/** [mm] */
	readonly height: number;
	/** Percentage of the wall face that is doors and windows. */
	readonly openings?: number;
}

interface ILoadBase {
	readonly id: string;
	readonly story: string;
	readonly member: string;
	readonly case?: LoadCase;
	readonly thisStoryOnly?: boolean;
	readonly note?: string;
}

export interface ILineLoad extends ILoadBase {
	readonly kind?: 'line';
	readonly wall?: IWallLoad;
	/** Explicit load [kN/m]. */
	readonly value?: number;
}

export interface IPointLoad extends ILoadBase {
	readonly kind: 'point';
	/** [kN] */
	readonly value: number;
	/** From the beam's start [mm]; none at a column's joint. */
	readonly distance?: number;
}

export type MemberLoad = ILineLoad | IPointLoad;

export interface IMemberLoads {
	readonly schema: string;
	readonly wallTypes: readonly IWallType[];
	readonly loads: readonly MemberLoad[];
}

/**
 * The wall types of a new loads file: BNBC 2020 Part 6 Table 6.2.2 (pp. 530-531), burnt clay
 * brick masonry 1.910 kN/m² per 100 mm and cement plaster 0.230 kN/m² per 10 mm, 12.5 mm on
 * each face. The same numbers as the code pack's (saengine.library.line_loads.default_wall_types);
 * once a file exists, its own wall types count.
 */
export function defaultWallTypes(): IWallType[] {
	return [125, 250].map(thickness => ({
		id: `BW${thickness}`,
		name: localize('loads.brickWall', "{0} mm brick wall, plastered both faces", thickness),
		thickness, unitWeight: 19.1, plaster: 12.5, plasterFaces: 2, plasterUnitWeight: 23,
	}));
}

export function emptyLoads(): IMemberLoads {
	return { schema: LOADS_SCHEMA, wallTypes: defaultWallTypes(), loads: [] };
}

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isObject) : [];
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** The loads file's content; a missing or empty file has none (and the default wall types). */
export function parseLoads(text: string | undefined): { readonly loads: IMemberLoads; readonly problem?: string } {
	if (!text?.trim()) {
		return { loads: emptyLoads() };
	}
	let data: unknown;
	try {
		data = JSON.parse(text);
	} catch (error) {
		return { loads: emptyLoads(), problem: localize('loads.badJson', "{0} is not valid JSON: {1}", LOADS_FILE, String(error)) };
	}
	if (!isObject(data)) {
		return { loads: emptyLoads(), problem: localize('loads.notObject', "{0} is not a loads file.", LOADS_FILE) };
	}
	if ((data.wallTypes !== undefined && !Array.isArray(data.wallTypes)) || (data.loads !== undefined && !Array.isArray(data.loads))) {
		return { loads: emptyLoads(), problem: localize('loads.notLists', "{0}: \"wallTypes\" and \"loads\" must be lists.", LOADS_FILE) };
	}
	const rawTypes: unknown[] = Array.isArray(data.wallTypes) ? data.wallTypes : [];
	const rawLoads: unknown[] = Array.isArray(data.loads) ? data.loads : [];
	const wallTypes = list(rawTypes).filter(w => typeof w.id === 'string' && num(w.thickness) && num(w.unitWeight)) as unknown as IWallType[];
	const loads = list(rawLoads).filter(readableLoad) as unknown as MemberLoad[];
	const parsed: IMemberLoads = { schema: LOADS_SCHEMA, wallTypes: Array.isArray(data.wallTypes) ? wallTypes : defaultWallTypes(), loads };
	// Entries that cannot be read would be lost by the next write: the file is then shown, not edited.
	const unreadable = rawTypes.length - wallTypes.length + rawLoads.length - loads.length;
	if (unreadable) {
		return { loads: parsed, problem: localize('loads.unreadable', "{0} entries of {1} cannot be read; fix the file (it is not changed here until then).", unreadable, LOADS_FILE) };
	}
	return { loads: parsed };
}

/** A load entry the panel can show and write back unchanged. */
function readableLoad(l: Json): boolean {
	if (typeof l.id !== 'string' || typeof l.story !== 'string' || typeof l.member !== 'string') {
		return false;
	}
	if (l.case !== undefined && !LOAD_CASES.some(c => c.id === l.case)) {
		return false;
	}
	if (l.kind === 'point') {
		return num(l.value) !== undefined && (l.distance === undefined || num(l.distance) !== undefined);
	}
	if (l.kind !== undefined && l.kind !== 'line') {
		return false;
	}
	const wall = l.wall;
	const wallOk = isObject(wall) && typeof wall.type === 'string' && num(wall.height) !== undefined && (wall.openings === undefined || num(wall.openings) !== undefined);
	return (wall === undefined) !== (l.value === undefined) && (wall === undefined ? num(l.value) !== undefined : wallOk);
}

export function loadsText(loads: IMemberLoads): string {
	return JSON.stringify(loads, undefined, '\t') + '\n';
}

// ───────────────────────────── values ─────────────────────────────

/** kN/m² of wall face: masonry and plaster. */
export function wallWeight(type: IWallType): number {
	return (type.unitWeight * type.thickness + (type.plasterUnitWeight ?? 23) * (type.plaster ?? 0) * (type.plasterFaces ?? 2)) / 1000;
}

/** kN/m of a wall `height` mm high on a beam, `openings` % of its face left out. */
export function wallLineLoad(type: IWallType, height: number, openings = 0): number {
	return wallWeight(type) * height / 1000 * (1 - openings / 100);
}

export function isPoint(load: MemberLoad): load is IPointLoad {
	return load.kind === 'point';
}

/** kN/m of a line load, kN of a point load; undefined for a wall of an unknown type. */
export function loadValue(load: MemberLoad, loads: IMemberLoads): number | undefined {
	if (isPoint(load) || load.value !== undefined) {
		return load.value;
	}
	const type = load.wall && loads.wallTypes.find(w => w.id === load.wall!.type);
	return type ? wallLineLoad(type, load.wall!.height, load.wall!.openings ?? 0) : undefined;
}

const round = (value: number, digits = 2) => Number(value.toFixed(digits)).toString();

/** "11.56 kN/m", "30 kN". */
export function valueLabel(load: MemberLoad, loads: IMemberLoads): string {
	const value = loadValue(load, loads);
	if (value === undefined) {
		return '?';
	}
	return isPoint(load) ? localize('loads.kN', "{0} kN", round(value)) : localize('loads.kNm', "{0} kN/m", round(value));
}

/** How the load is formed: "BW250 × 2.7 m − 20 %", "explicit", "at 2000 mm", "at the joint". */
export function sourceLabel(load: MemberLoad): string {
	if (isPoint(load)) {
		return load.distance !== undefined ? localize('loads.atDistance', "at {0} mm", load.distance) : localize('loads.atJoint', "at the joint");
	}
	if (!load.wall) {
		return localize('loads.explicit', "explicit");
	}
	const openings = load.wall.openings ? localize('loads.lessOpenings', " − {0} %", load.wall.openings) : '';
	return localize('loads.wallSource', "{0} × {1} m{2}", load.wall.type, round(load.wall.height / 1000, 3), openings);
}

// ───────────────────────────── the floor plan ─────────────────────────────

const pointKey = (p: unknown) => isObject(p) ? `${p.x}/${p.y}/${num(p.dx) ?? 0}/${num(p.dy) ?? 0}` : '?';

function beamsOf(layout: unknown): Json[] {
	return list(isObject(layout) ? layout.beams : undefined);
}

function columnsOf(layout: unknown): Json[] {
	return list(isObject(layout) ? layout.columns : undefined);
}

function beamKey(beam: Json): string {
	return [pointKey(beam.start), pointKey(beam.end)].sort().join(' ');
}

/** Where a beam is in plan [mm], or undefined when its grid points do not exist. */
export function beamEnds(layout: unknown, beamId: string): readonly [CadPoint, CadPoint] | undefined {
	const beam = beamsOf(layout).find(b => b.id === beamId);
	const { x, y } = gridsOf(layout);
	const at = (p: unknown): CadPoint | undefined => {
		const px = isObject(p) && typeof p.x === 'string' ? x.get(p.x) : undefined;
		const py = isObject(p) && typeof p.y === 'string' ? y.get(p.y) : undefined;
		return px === undefined || py === undefined || !isObject(p) ? undefined : [px + (num(p.dx) ?? 0), py + (num(p.dy) ?? 0)];
	};
	const [start, end] = beam ? [at(beam.start), at(beam.end)] : [undefined, undefined];
	return start && end ? [start, end] : undefined;
}

function columnAt(layout: unknown, columnId: string): CadPoint | undefined {
	const column = columnsOf(layout).find(c => c.id === columnId);
	const { x, y } = gridsOf(layout);
	const at = column && isObject(column.at) ? column.at : undefined;
	const px = at && typeof at.x === 'string' ? x.get(at.x) : undefined;
	const py = at && typeof at.y === 'string' ? y.get(at.y) : undefined;
	return at && px !== undefined && py !== undefined ? [px + (num(at.dx) ?? 0), py + (num(at.dy) ?? 0)] : undefined;
}

/** Depth of a beam's section [mm], from its object type's profile. */
export function beamDepth(layout: unknown, objects: unknown, beamId: string): number | undefined {
	const beam = beamsOf(layout).find(b => b.id === beamId);
	const type = beam && list(isObject(objects) ? objects.objects : undefined).find(o => o.id === beam.type);
	const profile = type && isObject(type.profile) ? type.profile : undefined;
	if (!profile) {
		return undefined;
	}
	return num(profile.yDim) ?? num(profile.overallDepth) ?? num(profile.depth) ?? (num(profile.radius) !== undefined ? 2 * num(profile.radius)! : undefined);
}

/** The usual parapet height on a roof beam [mm]. */
export const PARAPET_HEIGHT = 1000;

/**
 * The height of a wall on `beamId`: up to the soffit of the beam above it, i.e. the story height
 * above less that beam's depth (the loaded beam's own depth when there is no beam at that place on
 * the story above); on the top story, a parapet.
 */
export function defaultWallHeight(layout: unknown, objects: unknown, beamId: string): number {
	const beam = beamsOf(layout).find(b => b.id === beamId);
	const stories = storiesOf(layout);
	const index = stories.findIndex(s => s.id === beam?.story);
	if (!beam || index < 0 || index === stories.length - 1) {
		return PARAPET_HEIGHT;
	}
	const key = beamKey(beam);
	const above = beamsOf(layout).find(b => b.story === stories[index + 1].id && beamKey(b) === key);
	const depth = (typeof above?.id === 'string' ? beamDepth(layout, objects, above.id) : undefined) ?? beamDepth(layout, objects, beamId) ?? 0;
	const height = stories[index + 1].elevation - stories[index].elevation - depth;
	return height > 0 ? Math.round(height) : PARAPET_HEIGHT;
}

/** Whether beam `other` runs the other way from beam `beamId` (same place, start and end swapped). */
function reversed(layout: unknown, beamId: string, other: string): boolean {
	if (beamId === other) {
		return false;
	}
	const a = beamsOf(layout).find(b => b.id === beamId);
	const b = beamsOf(layout).find(x => x.id === other);
	return !!a && !!b && pointKey(a.start) !== pointKey(b.start) && pointKey(a.start) === pointKey(b.end);
}

/** The member at the place of `member` (on `from`) on story `to`, or undefined. */
function samePlace(layout: unknown, member: string, from: string, to: string): string | undefined {
	if (from === to) {
		return member;
	}
	const beam = beamsOf(layout).find(b => b.id === member);
	if (beam) {
		const key = beamKey(beam);
		return beamsOf(layout).find(b => b.story === to && beamKey(b) === key)?.id as string | undefined;
	}
	const column = columnsOf(layout).find(c => c.id === member);
	if (column) {
		const key = pointKey(column.at);
		return columnsOf(layout).find(c => c.top === to && pointKey(c.at) === key)?.id as string | undefined;
	}
	return undefined;
}

/** The stories `load` applies to. */
export function storiesOfLoad(layout: unknown, load: MemberLoad): string[] {
	return load.thisStoryOnly ? [load.story] : familyOf(layout, load.story);
}

export interface IStoryLoad {
	readonly load: MemberLoad;
	/** The member on the story the load is on. */
	readonly member: string;
	/** Entered on another story of the typical floor. */
	readonly inherited: boolean;
}

/** The loads on the plan of `story`, with those of its typical floor. */
export function loadsOnStory(loads: IMemberLoads, layout: unknown, story: string): IStoryLoad[] {
	const found: IStoryLoad[] = [];
	for (const load of loads.loads) {
		if (!storiesOfLoad(layout, load).includes(story)) {
			continue;
		}
		const member = samePlace(layout, load.member, load.story, story);
		if (member) {
			found.push({ load, member, inherited: load.story !== story });
		}
	}
	return found;
}

function nextLoadId(loads: IMemberLoads, prefix: string, taken: Set<string>): string {
	const used = new Set([...loads.loads.map(l => l.id), ...taken]);
	let n = 1;
	while (used.has(`${prefix}${n}`)) {
		n++;
	}
	taken.add(`${prefix}${n}`);
	return `${prefix}${n}`;
}

/**
 * Where a load entered on `member` of `story` is stored: on the master story's member at the same
 * place (a family-wide load), or as entered (this story only, no typical floor, or no member at
 * that place on the master).
 */
function storedOn(layout: unknown, member: string, story: string, thisStoryOnly: boolean): { readonly story: string; readonly member: string } {
	const master = masterOf(layout, story);
	if (thisStoryOnly || !master) {
		return { story, member };
	}
	const onMaster = samePlace(layout, member, story, master);
	return onMaster ? { story: master, member: onMaster } : { story, member };
}

export interface ILineLoadSpec {
	readonly case: LoadCase;
	readonly wall?: IWallLoad;
	readonly value?: number;
	readonly thisStoryOnly?: boolean;
}

export interface ILoadEdit {
	readonly loads: IMemberLoads;
	readonly ids: readonly string[];
	readonly problems: readonly string[];
}

/** `loads` with a line load added on each of `beams` (floor-plan beam ids). */
export function addLineLoads(loads: IMemberLoads, layout: unknown, beams: readonly string[], spec: ILineLoadSpec): ILoadEdit {
	const problems: string[] = [];
	if ((spec.wall === undefined) === (spec.value === undefined)) {
		return { loads, ids: [], problems: [localize('loads.wallOrValue', "Give a wall (type and height) or a load in kN/m.")] };
	}
	if (spec.wall && !loads.wallTypes.some(w => w.id === spec.wall!.type)) {
		return { loads, ids: [], problems: [localize('loads.noWallType', "There is no wall type {0}.", spec.wall.type)] };
	}
	const taken = new Set<string>();
	const added: MemberLoad[] = [];
	for (const id of beams) {
		const beam = beamsOf(layout).find(b => b.id === id);
		if (!beam || typeof beam.story !== 'string') {
			problems.push(localize('loads.notBeam', "{0} is not a beam of the floor plan.", id));
			continue;
		}
		const where = storedOn(layout, id, beam.story, !!spec.thisStoryOnly);
		added.push({
			id: nextLoadId(loads, 'LL', taken), kind: 'line', ...where, case: spec.case,
			...(spec.wall ? { wall: { ...spec.wall } } : { value: spec.value }),
			...(spec.thisStoryOnly ? { thisStoryOnly: true } : {}),
		});
	}
	return { loads: { ...loads, loads: [...loads.loads, ...added] }, ids: added.map(l => l.id), problems };
}

export interface IPointLoadSpec {
	readonly case: LoadCase;
	readonly value: number;
	/** On a beam: from its start [mm]. */
	readonly distance?: number;
	readonly thisStoryOnly?: boolean;
}

/** `loads` with a point load on `member`: a beam (at `distance`), or a column's joint on `story`. */
export function addPointLoad(loads: IMemberLoads, layout: unknown, member: { readonly group: MemberGroup; readonly id: string }, story: string, spec: IPointLoadSpec): ILoadEdit {
	if (!Number.isFinite(spec.value) || spec.value === 0) {
		return { loads, ids: [], problems: [localize('loads.needValue', "Give the load in kN.")] };
	}
	let at: { readonly story: string; readonly member: string };
	let distance: number | undefined;
	if (member.group === 'beams') {
		const ends = beamEnds(layout, member.id);
		const beam = beamsOf(layout).find(b => b.id === member.id);
		if (!ends || typeof beam?.story !== 'string') {
			return { loads, ids: [], problems: [localize('loads.notBeam', "{0} is not a beam of the floor plan.", member.id)] };
		}
		const length = Math.hypot(ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]);
		distance = Math.min(Math.max(spec.distance ?? length / 2, 0), length);
		at = storedOn(layout, member.id, beam.story, !!spec.thisStoryOnly);
		// Stored distances are from the start of the stored beam (as the analysis reads them).
		if (reversed(layout, member.id, at.member)) {
			distance = length - distance;
		}
	} else if (member.group === 'columns') {
		const column = columnsOf(layout).find(c => c.id === member.id);
		if (!column || column.top !== story) {
			return { loads, ids: [], problems: [localize('loads.notJoint', "{0} does not reach this story's level.", member.id)] };
		}
		at = storedOn(layout, member.id, story, !!spec.thisStoryOnly);
	} else {
		return { loads, ids: [], problems: [localize('loads.pointHosts', "Point loads go on a beam or at a column's joint.")] };
	}
	const id = nextLoadId(loads, 'PL', new Set());
	const load: IPointLoad = {
		id, kind: 'point', ...at, case: spec.case, value: spec.value,
		...(distance !== undefined ? { distance: Math.round(distance) } : {}),
		...(spec.thisStoryOnly ? { thisStoryOnly: true } : {}),
	};
	return { loads: { ...loads, loads: [...loads.loads, load] }, ids: [id], problems: [] };
}

export function removeLoads(loads: IMemberLoads, ids: readonly string[]): IMemberLoads {
	return { ...loads, loads: loads.loads.filter(l => !ids.includes(l.id)) };
}

export type LoadPatch = { readonly case?: LoadCase; readonly value?: number; readonly height?: number; readonly openings?: number; readonly distance?: number };

/** `loads` with load `id` changed: its case, its kN/m or kN, or its wall's height and openings. */
export function updateLoad(loads: IMemberLoads, id: string, patch: LoadPatch): IMemberLoads {
	return {
		...loads, loads: loads.loads.map(load => {
			if (load.id !== id) {
				return load;
			}
			let next: MemberLoad = patch.case ? { ...load, case: patch.case } : load;
			if (isPoint(next)) {
				next = { ...next, ...(patch.value !== undefined ? { value: patch.value } : {}), ...(patch.distance !== undefined ? { distance: patch.distance } : {}) };
			} else if (next.wall) {
				next = { ...next, wall: { ...next.wall, ...(patch.height !== undefined ? { height: patch.height } : {}), ...(patch.openings !== undefined ? { openings: patch.openings } : {}) } };
			} else if (patch.value !== undefined) {
				next = { ...next, value: patch.value };
			}
			return next;
		}),
	};
}

export interface ILoadRow {
	readonly id: string;
	readonly story: string;
	readonly storyName: string;
	/** How many stories it is on (its typical floor's). */
	readonly stories: number;
	readonly member: string;
	readonly kind: 'line' | 'point';
	readonly case: LoadCase;
	readonly value: number | undefined;
	readonly valueLabel: string;
	readonly source: string;
	/** Total on all its stories [kN], for the beams' lengths in the plan. */
	readonly total: number | undefined;
}

/** The rows of the Loads list, by story (lowest first), then member. */
export function loadRows(loads: IMemberLoads, layout: unknown): ILoadRow[] {
	const stories = storiesOf(layout);
	const order = new Map(stories.map((s, i) => [s.id, i]));
	const names = new Map(stories.map(s => [s.id, s.name]));
	return loads.loads.map(load => {
		const value = loadValue(load, loads);
		const on = storiesOfLoad(layout, load).length;
		let total: number | undefined;
		if (value !== undefined) {
			if (isPoint(load)) {
				total = value * on;
			} else {
				const ends = beamEnds(layout, load.member);
				total = ends ? value * Math.hypot(ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]) / 1000 * on : undefined;
			}
		}
		return {
			id: load.id, story: load.story, storyName: names.get(load.story) ?? load.story, stories: on, member: load.member,
			kind: isPoint(load) ? 'point' as const : 'line' as const, case: load.case ?? 'SD', value,
			valueLabel: valueLabel(load, loads), source: sourceLabel(load), total,
		};
	}).sort((a, b) => (order.get(a.story) ?? 99) - (order.get(b.story) ?? 99) || a.member.localeCompare(b.member, undefined, { numeric: true }) || a.id.localeCompare(b.id, undefined, { numeric: true }));
}

// ───────────────────────────── drawing ─────────────────────────────

export const LOAD_LAYERS = { loads: 'S-LOAD', labels: 'S-LOAD-IDEN' } as const;

export const LOAD_LAYER_SPECS: readonly CadLayerSpec[] = [
	{ name: LOAD_LAYERS.loads, color: 1, description: 'Line and point loads on members' },
	{ name: LOAD_LAYERS.labels, color: 1, description: 'Load values' },
];

/** Drawing sizes at 1:100 [mm]: the first load 450 mm off the beam, the next ones further. */
const LOAD_OFFSET = 450;
const LOAD_STEP = 400;
const TICK_SPACING = 750;
const LABEL_TEXT = 220;
const POINT_RADIUS = 160;

/** The loads on the plan of `story`: a line beside each loaded beam with ticks to it and its value, a circled cross at each point load. */
export function loadsDrawing(loads: IMemberLoads, layout: unknown, story: string): CadEntitySpec[] {
	const entities: CadEntitySpec[] = [];
	const stacked = new Map<string, number>();
	for (const { load, member } of loadsOnStory(loads, layout, story)) {
		const label = valueLabel(load, loads);
		if (isPoint(load)) {
			// The point on the member, and the side the symbol goes to: right of the beam's
			// direction (line loads are on its left, the member's id on its centreline), or
			// diagonally off a column's joint.
			let at: CadPoint | undefined;
			let side: CadPoint = [Math.SQRT1_2, -Math.SQRT1_2];
			if (load.distance !== undefined) {
				// The distance is from the start of the beam the load is stored on; the place in plan is the same on every story.
				const stored = beamEnds(layout, load.member);
				const shown = beamEnds(layout, member);
				if (stored && shown) {
					const length = Math.hypot(stored[1][0] - stored[0][0], stored[1][1] - stored[0][1]) || 1;
					const t = Math.min(load.distance / length, 1);
					at = [stored[0][0] + (stored[1][0] - stored[0][0]) * t, stored[0][1] + (stored[1][1] - stored[0][1]) * t];
					const shownLength = Math.hypot(shown[1][0] - shown[0][0], shown[1][1] - shown[0][1]) || 1;
					side = [(shown[1][1] - shown[0][1]) / shownLength, -(shown[1][0] - shown[0][0]) / shownLength];
				}
			} else {
				at = columnAt(layout, member);
			}
			if (!at) {
				continue;
			}
			const r = POINT_RADIUS;
			const off = (d: number): CadPoint => [at![0] + side[0] * d, at![1] + side[1] * d];
			const center = off(LOAD_OFFSET + r);
			entities.push({ kind: 'line', layer: LOAD_LAYERS.loads, start: off(LOAD_OFFSET), end: at });
			entities.push({ kind: 'circle', layer: LOAD_LAYERS.loads, center, radius: r });
			entities.push({ kind: 'line', layer: LOAD_LAYERS.loads, start: [center[0] - r * Math.SQRT1_2, center[1] - r * Math.SQRT1_2], end: [center[0] + r * Math.SQRT1_2, center[1] + r * Math.SQRT1_2] });
			entities.push({ kind: 'line', layer: LOAD_LAYERS.loads, start: [center[0] - r * Math.SQRT1_2, center[1] + r * Math.SQRT1_2], end: [center[0] + r * Math.SQRT1_2, center[1] - r * Math.SQRT1_2] });
			// Centred text beyond the symbol; across a vertical beam it also needs half its width of room.
			entities.push({ kind: 'text', layer: LOAD_LAYERS.labels, position: off(LOAD_OFFSET + 2 * r + LABEL_TEXT * 1.2 + Math.abs(side[0]) * label.length * LABEL_TEXT * 0.32), height: LABEL_TEXT, text: label });
			continue;
		}
		const ends = beamEnds(layout, member);
		if (!ends) {
			continue;
		}
		const [a, b] = ends;
		const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
		if (!length) {
			continue;
		}
		const level = stacked.get(member) ?? 0;
		stacked.set(member, level + 1);
		// To the left of the beam's direction, so a beam's loads stack on one side.
		const offset = LOAD_OFFSET + level * LOAD_STEP;
		const [nx, ny] = [-(b[1] - a[1]) / length, (b[0] - a[0]) / length];
		const shift = (p: CadPoint, d: number): CadPoint => [p[0] + nx * d, p[1] + ny * d];
		const [p, q] = [shift(a, offset), shift(b, offset)];
		entities.push({ kind: 'line', layer: LOAD_LAYERS.loads, start: p, end: q });
		const ticks = Math.max(2, Math.round(length / TICK_SPACING) + 1);
		for (let i = 0; i < ticks; i++) {
			const t = i / (ticks - 1);
			const top: CadPoint = [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
			entities.push({ kind: 'line', layer: LOAD_LAYERS.loads, start: top, end: shift(top, -offset * 0.55) });
		}
		// Centred text: across a vertical beam it also needs half its width of room.
		const mid: CadPoint = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
		entities.push({ kind: 'text', layer: LOAD_LAYERS.labels, position: shift(mid, LABEL_TEXT * 1.2 + Math.abs(nx) * label.length * LABEL_TEXT * 0.32), height: LABEL_TEXT, text: label });
	}
	return entities;
}

// ───────────────────────────── the file ─────────────────────────────

/** `05 Floor Plan/loads.json` beside the floor plan `planFile`. */
export function loadsFileOf(planFile: URI): URI {
	return joinPath(dirname(planFile), LOADS_FILE);
}

/**
 * The loads file of a floor plan, as a text model while it exists (so its edits are undoable).
 * Each write creates the file when it is missing and saves it: the panel has no Save of its own.
 */
export class FloorPlanLoadsFile extends Disposable {

	private readonly reference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly listener = this._register(new MutableDisposable());
	private resource: URI | undefined;
	private readonly _onDidChange = this._register(new Emitter<void>());
	/** The file changed (an edit here, undo, another editor). */
	readonly onDidChange: Event<void> = this._onDidChange.event;

	constructor(
		@ITextModelService private readonly textModelService: ITextModelService,
		@IFileService private readonly fileService: IFileService,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super();
	}

	/** Follows the loads file of the floor plan `planFile`; no file is created yet. */
	async open(planFile: URI): Promise<void> {
		this.resource = loadsFileOf(planFile);
		this.reference.clear();
		this.listener.clear();
		if (await this.fileService.exists(this.resource)) {
			await this.resolve(this.resource);
		}
		this._onDidChange.fire();
	}

	private async resolve(resource: URI): Promise<ITextModel | undefined> {
		const reference = await this.textModelService.createModelReference(resource);
		if (this.resource?.toString() !== resource.toString()) {
			reference.dispose();
			return undefined;
		}
		this.reference.value = reference;
		const model = reference.object.textEditorModel;
		this.listener.value = model.onDidChangeContent(() => this._onDidChange.fire());
		return model;
	}

	get model(): ITextModel | undefined {
		const model = this.reference.value?.object.textEditorModel;
		return model && !model.isDisposed() ? model : undefined;
	}

	read(): { readonly loads: IMemberLoads; readonly problem?: string } {
		return parseLoads(this.model?.getValue());
	}

	/** Replaces the file's content with `loads` as one undoable edit (creating the file first) and saves it. */
	async write(loads: IMemberLoads): Promise<void> {
		const resource = this.resource;
		if (!resource) {
			return;
		}
		let model = this.model;
		if (!model) {
			if (!await this.fileService.exists(resource)) {
				await this.fileService.writeFile(resource, VSBuffer.fromString(loadsText(emptyLoads())));
			}
			model = await this.resolve(resource);
			if (!model) {
				return;
			}
		}
		const current = parseLoads(model.getValue());
		if (current.problem) {
			throw new Error(current.problem);
		}
		model.pushStackElement();
		model.pushEditOperations([], [{ range: model.getFullModelRange(), text: loadsText(loads) }], () => null);
		model.pushStackElement();
		await this.textFileService.save(resource);
	}
}

// ───────────────────────────── properties panel ─────────────────────────────

export interface ILoadsPanelContext {
	readonly layout: unknown;
	readonly objects: unknown;
	/** The story shown in the plan. */
	readonly story: string | undefined;
	/** The members selected on the plan. */
	readonly selected: readonly { readonly group: MemberGroup; readonly id: string }[];
	/** Whether the floor plan can be edited (it parses and is valid). */
	readonly editable: boolean;
	/** Shows a message in the editor's status line. */
	readonly notify: (text: string) => void;
	/** Draws the properties panel again (a form opened or closed). */
	readonly rerender: () => void;
	/** Selects a member on the plan (from the Loads list). */
	readonly reveal?: (member: { readonly group: MemberGroup; readonly id: string }, story: string) => void;
}

type Form = { readonly kind: 'line'; readonly beams: readonly string[] } | { readonly kind: 'point'; readonly member: { readonly group: MemberGroup; readonly id: string } };

/**
 * The loads section of the floor plan's properties panel: "Line Load..." and "Point Load..." for
 * the selection, their forms, and the Loads list (every load of the project, editable).
 */
export class FloorPlanLoadsPanel extends Disposable {

	private form: Form | undefined;
	private showAll = false;

	constructor(
		readonly file: FloorPlanLoadsFile,
		@IContextViewService private readonly contextViewService: IContextViewService,
	) {
		super();
	}

	/** Opens the Line Load form for the beams among `selected`; false when none is a beam. */
	openLineLoad(selected: readonly { readonly group: MemberGroup; readonly id: string }[]): boolean {
		const beams = selected.filter(m => m.group === 'beams').map(m => m.id);
		this.form = beams.length ? { kind: 'line', beams } : undefined;
		return !!this.form;
	}

	/** Opens the Point Load form for one beam or column; false otherwise. */
	openPointLoad(selected: readonly { readonly group: MemberGroup; readonly id: string }[]): boolean {
		const member = selected.length === 1 && (selected[0].group === 'beams' || selected[0].group === 'columns') ? selected[0] : undefined;
		this.form = member ? { kind: 'point', member } : undefined;
		return !!this.form;
	}

	close(): void {
		this.form = undefined;
	}

	/** Renders the section into `panel`; listeners go to `store` (cleared with the panel). */
	render(panel: HTMLElement, store: DisposableStore, floorPlan: ILoadsPanelContext): void {
		const { loads, problem } = this.file.read();
		// A loads file that does not read is shown, never written over (a write would lose its loads).
		const context: ILoadsPanelContext = { ...floorPlan, editable: floorPlan.editable && !problem };
		const section = append(panel, $('.floor-plan-loads'));
		if (this.form && context.editable) {
			const stillSelected = this.form.kind === 'line'
				? this.form.beams.every(id => context.selected.some(m => m.group === 'beams' && m.id === id))
				: context.selected.some(m => this.form?.kind === 'point' && m.group === this.form.member.group && m.id === this.form.member.id);
			if (!stillSelected) {
				this.form = undefined;
			}
		}
		if (this.form?.kind === 'line' && context.editable) {
			this.renderLineForm(section, store, context, loads, this.form.beams);
		} else if (this.form?.kind === 'point' && context.editable) {
			this.renderPointForm(section, store, context, loads, this.form.member);
		} else {
			const links = append(section, $('.sa-props-links'));
			const beams = context.selected.filter(m => m.group === 'beams');
			if (context.editable && beams.length) {
				propertyLink(links, beams.length === 1 ? localize('loads.lineLoadLink', "Line Load...") : localize('loads.lineLoadsLink', "Line Load on {0} Beams...", beams.length), () => {
					this.openLineLoad(context.selected);
					context.rerender();
				}, store);
			}
			if (context.editable && context.selected.length === 1 && (context.selected[0].group === 'beams' || context.selected[0].group === 'columns')) {
				propertyLink(links, localize('loads.pointLoadLink', "Point Load..."), () => {
					this.openPointLoad(context.selected);
					context.rerender();
				}, store);
			}
		}
		this.renderList(section, store, context, loads, problem);
	}

	private async write(loads: IMemberLoads, notice: string, context: ILoadsPanelContext): Promise<void> {
		try {
			await this.file.write(loads);
		} catch (error) {
			context.notify(localize('loads.writeFailed', "The loads could not be written: {0}", String(error)));
			return;
		}
		context.notify(notice);
		context.rerender();
	}

	private input(container: HTMLElement, store: DisposableStore, label: string, value: string, placeholder: string, onChange?: (text: string) => void, onEnter?: () => void): InputBox {
		const cell = $('.floor-plan-prop-control');
		const box = store.add(new InputBox(cell, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, placeholder, ariaLabel: label }));
		box.value = value;
		if (onChange) {
			store.add(box.onDidChange(onChange));
		}
		store.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter' && onEnter) {
				e.preventDefault();
				e.stopPropagation();
				onEnter();
			}
		}));
		appendPropertyRow(container, label, cell).classList.add('editable');
		return box;
	}

	private select(container: HTMLElement, store: DisposableStore, label: string, options: readonly string[], index: number, onSelect: (index: number) => void): SelectBox {
		const cell = $('.floor-plan-prop-control');
		const box = store.add(new SelectBox(options.map(text => ({ text })), index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
		box.render(cell);
		store.add(box.onDidSelect(({ index }) => onSelect(index)));
		appendPropertyRow(container, label, cell).classList.add('editable');
		return box;
	}

	private familyCheckbox(container: HTMLElement, store: DisposableStore, context: ILoadsPanelContext, story: string | undefined): () => boolean {
		const family = story ? familyOf(context.layout, story) : [];
		if (family.length < 2) {
			return () => false;
		}
		const label = localize('loads.thisStoryOnly', "This story only");
		const checkbox = store.add(new Checkbox(label, false, defaultCheckboxStyles));
		const cell = $('.floor-plan-loads-check');
		cell.appendChild(checkbox.domNode);
		append(cell, $('span', undefined, localize('loads.familyNote', "else on all {0} stories of the typical floor", family.length)));
		appendPropertyRow(container, label, cell).classList.add('editable');
		return () => checkbox.checked;
	}

	private renderLineForm(section: HTMLElement, store: DisposableStore, context: ILoadsPanelContext, loads: IMemberLoads, beams: readonly string[]): void {
		appendPropertyHeading(section, beams.length === 1 ? localize('loads.lineLoadOn', "Line Load on {0}", beams[0]) : localize('loads.lineLoadOnMany', "Line Load on {0} Beams", beams.length));
		const types = loads.wallTypes;
		const kinds = [localize('loads.fromWall', "Wall on the beam"), localize('loads.explicitKnm', "Load in kN/m")];
		let fromWall = types.length > 0;
		let typeIndex = Math.max(0, types.findIndex(t => t.id === 'BW250'));
		let caseIndex = 0;
		const height = defaultWallHeight(context.layout, context.objects, beams[0]);
		const form = append(section, $('.floor-plan-loads-form'));
		const wallRows: HTMLElement[] = [];
		/** The form's controls, set as they are made (the callbacks run after that). */
		const c: { result?: HTMLElement; height?: InputBox; openings?: InputBox; value?: InputBox; valueRow?: HTMLElement } = {};
		const spec = (): ILineLoadSpec | undefined => {
			const kase = LOAD_CASES[caseIndex].id;
			if (fromWall) {
				const h = Number(c.height?.value), o = Number(c.openings?.value || '0');
				return types[typeIndex] && h > 0 && o >= 0 && o < 100 ? { case: kase, wall: { type: types[typeIndex].id, height: h, ...(o ? { openings: o } : {}) } } : undefined;
			}
			const text = c.value?.value ?? '';
			const v = Number(text);
			return text.trim() && Number.isFinite(v) && v !== 0 ? { case: kase, value: v } : undefined;
		};
		const refresh = () => {
			wallRows.forEach(row => row.classList.toggle('hidden', !fromWall));
			c.valueRow?.classList.toggle('hidden', fromWall);
			const s = spec();
			const value = s?.wall ? wallLineLoad(types[typeIndex], s.wall.height, s.wall.openings ?? 0) : s?.value;
			if (!c.result) {
				return;
			}
			c.result.textContent = value !== undefined
				? localize('loads.preview', "{0} kN/m on each beam", round(value))
				: localize('loads.previewIncomplete', "Enter the wall's height (and openings below 100 %) or a load in kN/m.");
		};
		this.select(form, store, localize('loads.source', "Load from"), kinds, fromWall ? 0 : 1, index => {
			fromWall = index === 0 && types.length > 0;
			refresh();
		});
		const before = form.childElementCount;
		this.select(form, store, localize('loads.wallType', "Wall type"), types.map(t => localize('loads.wallTypeOption', "{0} ({1} kN/m²)", t.name, round(wallWeight(t)))), typeIndex, index => {
			typeIndex = index;
			refresh();
		});
		const apply = () => {
			const s = spec();
			if (!s) {
				context.notify(localize('loads.incomplete', "The line load is incomplete."));
				return;
			}
			const edit = addLineLoads(loads, context.layout, beams, { ...s, thisStoryOnly: onlyHere() });
			if (!edit.ids.length) {
				context.notify(edit.problems.join(' '));
				return;
			}
			this.form = undefined;
			void this.write(edit.loads, edit.ids.length === 1 ? localize('loads.addedOne', "Added line load {0}.", edit.ids[0]) : localize('loads.addedMany', "Added {0} line loads.", edit.ids.length), context);
		};
		c.height = this.input(form, store, localize('loads.height', "Height (mm)"), String(height), localize('loads.heightHint', "Storey height less the beam depth"), refresh, apply);
		c.openings = this.input(form, store, localize('loads.openings', "Openings (%)"), '0', localize('loads.openingsHint', "Doors and windows, % of the wall face"), refresh, apply);
		for (let i = before; i < form.childElementCount; i++) {
			wallRows.push(form.children[i] as HTMLElement);
		}
		c.value = this.input(form, store, localize('loads.valueKnm', "Load (kN/m)"), '', localize('loads.valueKnmHint', "e.g. 7.5"), refresh, apply);
		c.valueRow = form.lastElementChild as HTMLElement;
		this.select(form, store, localize('loads.case', "Load case"), LOAD_CASES.map(c => c.label), caseIndex, index => caseIndex = index);
		const onlyHere = this.familyCheckbox(form, store, context, context.story);
		c.result = appendPropertyNote(form, '');
		refresh();
		const links = append(form, $('.sa-props-links'));
		propertyLink(links, localize('loads.add', "Add"), apply, store);
		propertyLink(links, localize('loads.cancel', "Cancel"), () => {
			this.form = undefined;
			context.rerender();
		}, store);
	}

	private renderPointForm(section: HTMLElement, store: DisposableStore, context: ILoadsPanelContext, loads: IMemberLoads, member: { readonly group: MemberGroup; readonly id: string }): void {
		const onBeam = member.group === 'beams';
		appendPropertyHeading(section, onBeam ? localize('loads.pointLoadOnBeam', "Point Load on {0}", member.id) : localize('loads.pointLoadAtJoint', "Point Load at {0}'s Joint", member.id));
		const form = append(section, $('.floor-plan-loads-form'));
		const ends = onBeam ? beamEnds(context.layout, member.id) : undefined;
		const length = ends ? Math.round(Math.hypot(ends[1][0] - ends[0][0], ends[1][1] - ends[0][1])) : 0;
		let caseIndex = 0;
		const c: { value?: InputBox; distance?: InputBox } = {};
		const apply = () => {
			const text = c.value?.value ?? '';
			const value = Number(text);
			const distance = c.distance ? Number(c.distance.value) : undefined;
			if (!text.trim() || !Number.isFinite(value) || (distance !== undefined && !(distance >= 0 && distance <= length))) {
				context.notify(localize('loads.pointIncomplete', "Give the load in kN and, on a beam, a distance from 0 to {0} mm.", length));
				return;
			}
			const edit = addPointLoad(loads, context.layout, member, context.story ?? '', { case: LOAD_CASES[caseIndex].id, value, distance, thisStoryOnly: onlyHere() });
			if (!edit.ids.length) {
				context.notify(edit.problems.join(' '));
				return;
			}
			this.form = undefined;
			void this.write(edit.loads, localize('loads.addedPoint', "Added point load {0}.", edit.ids[0]), context);
		};
		c.value = this.input(form, store, localize('loads.valueKn', "Load (kN)"), '', localize('loads.valueKnHint', "e.g. 30 for a water tank's support"), undefined, apply);
		if (onBeam) {
			c.distance = this.input(form, store, localize('loads.distance', "From start (mm)"), String(Math.round(length / 2)), localize('loads.distanceHint', "0 to {0}", length), undefined, apply);
		}
		this.select(form, store, localize('loads.case', "Load case"), LOAD_CASES.map(c => c.label), caseIndex, index => caseIndex = index);
		const onlyHere = this.familyCheckbox(form, store, context, context.story);
		const links = append(form, $('.sa-props-links'));
		propertyLink(links, localize('loads.add', "Add"), apply, store);
		propertyLink(links, localize('loads.cancel', "Cancel"), () => {
			this.form = undefined;
			context.rerender();
		}, store);
	}

	/** The Loads list: story, member, kind, case, value and how it is formed; editable. */
	private renderList(section: HTMLElement, store: DisposableStore, context: ILoadsPanelContext, loads: IMemberLoads, problem: string | undefined): void {
		const rows = loadRows(loads, context.layout);
		const onStory = context.story ? new Set(loadsOnStory(loads, context.layout, context.story).map(s => s.load.id)) : new Set<string>();
		const shown = this.showAll ? rows : rows.filter(r => onStory.has(r.id));
		const total = shown.reduce((sum, r) => sum + (r.total ?? 0), 0);
		appendPropertyHeading(section, localize('loads.listHeading', "Loads"), this.showAll
			? localize('loads.listAll', "{0} in the project", rows.length)
			: localize('loads.listStory', "{0} on this story, {1} in all", shown.length, rows.length));
		if (problem) {
			appendPropertyRow(section, LOADS_FILE, problem, true);
			appendPropertyNote(section, localize('loads.readOnly', "Loads cannot be added or changed here until {0} is fixed, so that none of its loads are lost.", LOADS_FILE));
		}
		const toggle = append(section, $('.sa-props-links'));
		propertyLink(toggle, this.showAll ? localize('loads.showStory', "Show This Story's") : localize('loads.showAll', "Show All Stories"), () => {
			this.showAll = !this.showAll;
			context.rerender();
		}, store);
		if (!shown.length) {
			appendPropertyNote(section, localize('loads.none', "No line or point loads here. Select beams and choose Line Load..., or a beam or column and Point Load..."));
			return;
		}
		const table = append(section, $('table.floor-plan-loads-table'));
		const head = append(append(table, $('thead')), $('tr'));
		// Two lines per load, to fit the panel: member, case, value and Delete; then story, kind and how it is formed.
		for (const title of [localize('loads.colMember', "Member"), localize('loads.colCase', "Case"), localize('loads.colValue', "Value"), '']) {
			append(head, $('th', undefined, title));
		}
		const body = append(table, $('tbody'));
		for (const row of shown) {
			const tr = append(body, $('tr.load'));
			const memberCell = append(tr, $('td', { title: row.id }));
			const link = append(memberCell, $<HTMLAnchorElement>('a.sa-props-link', { role: 'button', tabIndex: 0 }, row.member));
			store.add(addDisposableListener(link, EventType.CLICK, () => context.reveal?.({ group: beamsOf(context.layout).some(b => b.id === row.member) ? 'beams' : 'columns', id: row.member }, row.story)));
			const caseCell = append(tr, $('td'));
			const load = loads.loads.find(l => l.id === row.id)!;
			if (context.editable) {
				const box = store.add(new SelectBox(LOAD_CASES.map(c => ({ text: c.id })), Math.max(0, LOAD_CASES.findIndex(c => c.id === row.case)), this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('loads.caseOf', "Load case of {0}", row.id) }));
				box.render(caseCell);
				store.add(box.onDidSelect(({ index }) => void this.write(updateLoad(loads, row.id, { case: LOAD_CASES[index].id }), localize('loads.changed', "Changed {0}.", row.id), context)));
			} else {
				caseCell.textContent = row.case;
			}
			const valueCell = append(tr, $('td.value'));
			const wall = !isPoint(load) ? load.wall : undefined;
			if (context.editable) {
				// A wall's height is edited (its kN/m follows); else the value itself.
				const box = store.add(new InputBox(valueCell, this.contextViewService, {
					inputBoxStyles: defaultInputBoxStyles,
					ariaLabel: wall ? localize('loads.heightOf', "Wall height of {0} in mm", row.id) : localize('loads.valueOf', "Value of {0}", row.id),
				}));
				box.value = wall ? String(wall.height) : String(row.value ?? '');
				box.element.title = wall ? localize('loads.heightTitle', "Wall height (mm): {0}", row.valueLabel) : row.valueLabel;
				store.add(addDisposableListener(box.inputElement, EventType.KEY_DOWN, e => {
					if (e.key !== 'Enter') {
						return;
					}
					e.preventDefault();
					e.stopPropagation();
					const v = Number(box.value);
					if (!Number.isFinite(v) || v === 0 || (wall && v < 0)) {
						context.notify(localize('loads.badValue', "Type a number."));
						return;
					}
					void this.write(updateLoad(loads, row.id, wall ? { height: v } : { value: v }), localize('loads.changed', "Changed {0}.", row.id), context);
				}));
				append(valueCell, $('span.unit', undefined, wall ? localize('loads.mmUnit', "mm") : row.kind === 'point' ? localize('loads.kNUnit', "kN") : localize('loads.kNmUnit', "kN/m")));
			} else {
				valueCell.textContent = row.valueLabel;
			}
			const actions = append(tr, $('td'));
			if (context.editable) {
				propertyLink(actions, localize('loads.delete', "Delete"), () => void this.write(removeLoads(loads, [row.id]), localize('loads.deleted', "Deleted {0}.", row.id), context), store);
			}
			const story = row.stories > 1 ? localize('loads.storyFamily', "{0} (+{1})", row.storyName, row.stories - 1) : row.storyName;
			const kind = row.kind === 'point' ? localize('loads.kindPoint', "point") : localize('loads.kindLine', "line");
			const source = wall ? localize('loads.wallSourceValue', "{0} = {1}", row.source, row.valueLabel) : row.source;
			append(append(body, $('tr.detail')), $('td.source', { colSpan: 4 }, localize('loads.detail', "{0} · {1}, {2} · {3}", row.id, story, kind, source)));
		}
		appendPropertyNote(section, localize('loads.totalNote', "Total {0} kN on the stories listed (each typical-floor load counted on every story it is on). Loads go to the analysis as their load case; walls are superimposed dead load by default.", round(total, 1)));
	}
}
