/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { polygonArea } from '../../../../platform/saengine/common/geometry.js';
import { formatPoint, IFloorPlanStory, location, onPlanOf, storiesOf } from '../../../services/saengineProject/common/floorPlanMembers.js';
import { MemberGroup, ModelSelection } from '../../../services/saengineProject/common/modelSelection.js';
import { recordedStamp, sourceStamp } from '../../../services/saengineProject/common/partSources.js';

/*
 * What the Model Explorer and the Properties view show, built from the project files. Both are
 * read-only: they describe the project, and editing happens in the editor that owns each file.
 */

type Json = { readonly [key: string]: unknown };

/** The project files the views read (parsed), and the floor plan's text for its stamp. */
export interface IProjectDocuments {
	readonly floorPlan?: unknown;
	readonly floorPlanText?: string;
	/** The structural model of a special structure (instead of the floor plan). */
	readonly structure?: unknown;
	readonly structureText?: string;
	readonly objects?: unknown;
	readonly materials?: unknown;
	readonly bim?: unknown;
	readonly mep?: unknown;
}

export interface IModelNode {
	/** Stable id, so expansion and selection survive refreshes. */
	readonly id: string;
	readonly label: string;
	readonly description?: string;
	readonly icon: ThemeIcon;
	readonly selection?: ModelSelection;
	/** The part whose editor opens when the node is opened. */
	readonly part?: string;
	readonly problem?: string;
	readonly children?: readonly IModelNode[];
}

/** Where an engineer goes to change what a property sheet shows. */
export type PropertyAction = 'showInFloorPlan' | 'editGrids' | 'editObjectType';

export interface IPropertyRow {
	readonly label: string;
	readonly value: string;
	readonly problem?: boolean;
}

export interface IPropertySection {
	readonly title: string;
	readonly rows: readonly IPropertyRow[];
}

export interface IPropertySheet {
	readonly title: string;
	readonly subtitle: string;
	readonly sections: readonly IPropertySection[];
	readonly actions: readonly PropertyAction[];
	/** The object type `editObjectType` opens. */
	readonly objectType?: string;
}

const FLOOR_PLAN_SCHEMA_ID = 'saengine.floorPlan/1';

const GROUPS: readonly { readonly group: MemberGroup; readonly label: string; readonly singular: string; readonly icon: ThemeIcon }[] = [
	{ group: 'columns', label: localize('group.columns', "Columns"), singular: localize('kind.column', "Column"), icon: Codicon.primitiveSquare },
	{ group: 'beams', label: localize('group.beams', "Beams"), singular: localize('kind.beam', "Beam"), icon: Codicon.dash },
	{ group: 'walls', label: localize('group.walls', "Walls"), singular: localize('kind.wall', "Wall"), icon: Codicon.splitHorizontal },
	{ group: 'slabs', label: localize('group.slabs', "Slabs"), singular: localize('kind.slab', "Slab"), icon: Codicon.layout },
	{ group: 'footings', label: localize('group.footings', "Footings"), singular: localize('kind.footing', "Footing"), icon: Codicon.symbolStructure },
];

const TYPE_KINDS: readonly { readonly kinds: readonly string[]; readonly label: string }[] = [
	{ kinds: ['column'], label: localize('types.columns', "Column Types") },
	{ kinds: ['beam'], label: localize('types.beams', "Beam Types") },
	{ kinds: ['brace'], label: localize('types.braces', "Brace Types") },
	{ kinds: ['slab'], label: localize('types.slabs', "Slab Types") },
	{ kinds: ['wall'], label: localize('types.walls', "Wall Types") },
	{ kinds: ['staircase'], label: localize('types.stairs', "Staircase Types") },
	{ kinds: ['footing', 'pileCap'], label: localize('types.footings', "Footing and Pile Cap Types") },
	{ kinds: ['pile'], label: localize('types.piles', "Pile Types") },
];

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isObject) : [];
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function mm(value: number | undefined): string {
	return value === undefined ? '—' : localize('mm', "{0} mm", Number(value.toFixed(1)));
}

function str(value: unknown): string {
	return typeof value === 'string' ? value : value === undefined ? '—' : String(value);
}

type IStory = IFloorPlanStory;

class Model {
	readonly plan: Json | undefined;
	readonly stories: readonly IStory[];
	readonly x: ReadonlyMap<string, number>;
	readonly y: ReadonlyMap<string, number>;
	readonly types: ReadonlyMap<string, Json>;
	readonly materials: ReadonlyMap<string, Json>;

	constructor(readonly docs: IProjectDocuments) {
		this.plan = isObject(docs.floorPlan) && docs.floorPlan.schema === FLOOR_PLAN_SCHEMA_ID ? docs.floorPlan : undefined;
		const plan = this.plan ?? {};
		this.stories = storiesOf(plan);
		const grids = isObject(plan.grids) ? plan.grids : {};
		const lines = (axis: 'x' | 'y') => new Map(list(grids[axis]).filter(g => typeof g.label === 'string' && num(g.position) !== undefined).map(g => [g.label as string, g.position as number]));
		this.x = lines('x');
		this.y = lines('y');
		this.types = new Map(list(isObject(docs.objects) ? docs.objects.objects : undefined).filter(o => typeof o.id === 'string').map(o => [o.id as string, o]));
		this.materials = new Map(list(isObject(docs.materials) ? docs.materials.materials : undefined).filter(m => typeof m.id === 'string').map(m => [m.id as string, m]));
	}

	members(group: MemberGroup): Json[] {
		return list(this.plan?.[group]).filter(m => typeof m.id === 'string');
	}

	story(id: unknown): IStory | undefined {
		return this.stories.find(s => s.id === id);
	}

	/** Members shown on the plan of `story`: columns and walls rising to it, the rest at its level. */
	onStory(group: MemberGroup, story: IStory): Json[] {
		return this.members(group).filter(m => onPlanOf(group, m, story, this.stories));
	}

	point(value: unknown): { label: string; at?: [number, number] } {
		if (!isObject(value)) {
			return { label: '?' };
		}
		const dx = num(value.dx) ?? 0;
		const dy = num(value.dy) ?? 0;
		const x = this.x.get(value.x as string);
		const y = this.y.get(value.y as string);
		return { label: formatPoint(value), at: x !== undefined && y !== undefined ? [x + dx, y + dy] : undefined };
	}

	/** Build state of the building model against the current floor plan (or structural model). */
	buildingStatus(): 'none' | 'outdated' | 'current' {
		const [part, text] = this.docs.structureText !== undefined ? ['structure', this.docs.structureText] : ['floorPlan', this.docs.floorPlanText];
		const recorded = recordedStamp(this.docs.bim, part);
		if (!recorded) {
			return 'none';
		}
		return text !== undefined && recorded === sourceStamp(text) ? 'current' : 'outdated';
	}
}

function memberDescription(group: MemberGroup, member: Json): string {
	return `${str(member.type)} · ${location(group, member)}`;
}

/** The Model Explorer tree: the floor plan by story, the object types, the building model (BIM) and the MEP services. */
export function modelTree(docs: IProjectDocuments): IModelNode[] {
	const model = new Model(docs);
	const nodes: IModelNode[] = [];

	if (docs.structureText !== undefined) {
		nodes.push(structureNode(docs.structure, model));
	} else if (!model.plan) {
		nodes.push({ id: 'floorPlan', label: localize('tree.floorPlan', "Floor Plan"), description: localize('tree.noFloorPlan', "not created yet"), icon: Codicon.symbolArray, part: 'floorPlan' });
	} else {
		const memberNode = (group: MemberGroup, member: Json, parent: string): IModelNode => {
			const problem = model.types.has(member.type as string) ? undefined : localize('tree.unknownType', "Unknown object type '{0}'", str(member.type));
			return {
				id: `${parent}/${member.id}`, label: member.id as string, description: memberDescription(group, member),
				icon: GROUPS.find(g => g.group === group)!.icon, selection: { kind: 'member', group, id: member.id as string }, part: 'floorPlan', problem,
			};
		};
		const stories: IModelNode[] = [...model.stories].reverse().map(story => {
			const groups = GROUPS.map(({ group, label, icon }) => {
				const members = model.onStory(group, story);
				return { group, label, icon, members };
			}).filter(g => g.members.length);
			const count = groups.reduce((n, g) => n + g.members.length, 0);
			const id = `story:${story.id}`;
			return {
				id, label: story.name, description: localize('tree.storyDescription', "{0} · {1} members", `${story.elevation >= 0 ? '+' : ''}${story.elevation}`, count),
				icon: Codicon.layers, selection: { kind: 'story', id: story.id }, part: 'floorPlan',
				children: groups.map(g => ({
					id: `${id}/${g.group}`, label: g.label, description: String(g.members.length), icon: g.icon,
					children: g.members.map(m => memberNode(g.group, m, `${id}/${g.group}`)),
				})),
			};
		});
		const gridNodes = (axis: 'x' | 'y', lines: ReadonlyMap<string, number>): IModelNode[] => [...lines]
			.sort((a, b) => a[1] - b[1])
			.map(([label, position]) => ({ id: `grid:${axis}:${label}`, label, description: mm(position), icon: Codicon.debugBreakpointLogUnverified, selection: { kind: 'gridLine', axis, label }, part: 'grids' }));
		nodes.push({
			id: 'floorPlan', label: localize('tree.floorPlan', "Floor Plan"), icon: Codicon.symbolArray, part: 'floorPlan',
			children: [
				{
					id: 'grids', label: localize('tree.grids', "Grid Lines"), description: `${model.x.size} × ${model.y.size}`, icon: Codicon.table, part: 'grids',
					children: [
						{ id: 'grids:x', label: localize('tree.gridsX', "X (lettered)"), icon: Codicon.arrowRight, children: gridNodes('x', model.x) },
						{ id: 'grids:y', label: localize('tree.gridsY', "Y (numbered)"), icon: Codicon.arrowUp, children: gridNodes('y', model.y) },
					],
				},
				{ id: 'stories', label: localize('tree.stories', "Stories"), description: String(model.stories.length), icon: Codicon.layers, part: 'grids', children: stories },
			],
		});
	}

	nodes.push({
		id: 'objects', label: localize('tree.objects', "Object Types"), description: String(model.types.size), icon: Codicon.symbolClass, part: 'objects',
		children: TYPE_KINDS.map(({ kinds, label }) => {
			const types = [...model.types.values()].filter(t => kinds.includes(t.kind as string));
			return {
				id: `objects:${kinds[0]}`, label, description: String(types.length), icon: Codicon.symbolClass,
				children: types.map(t => ({ id: `object:${t.id}`, label: t.id as string, description: str(t.name), icon: Codicon.symbolClass, selection: { kind: 'objectType' as const, id: t.id as string }, part: 'objects' })),
			};
		}).filter(n => n.children.length),
	});

	const status = model.buildingStatus();
	const elements = list(isObject(docs.bim) ? docs.bim.elements : undefined);
	nodes.push({
		id: 'bim', label: localize('tree.bimPart', "BIM (Building Model)"), icon: Codicon.symbolStructure, part: 'bim',
		description: status === 'none' ? localize('tree.bimNone', "not built yet") : status === 'outdated'
			? (docs.structureText !== undefined ? localize('tree.bimOutdatedStructure', "Structural Model changed since built") : localize('tree.bimOutdated', "Floor Plan changed since built"))
			: localize('tree.bimCurrent', "up to date"),
		problem: status === 'outdated' ? localize('tree.bimOutdatedProblem', "Update it in the Building Model editor.") : undefined,
		children: [
			...GROUPS.map(({ group, label, icon }) => ({ group, label, icon })),
			{ group: 'members', label: localize('tree.members', "Members"), icon: Codicon.dash },
			{ group: 'areas', label: localize('tree.areas', "Areas"), icon: Codicon.symbolArray },
		].map(({ group, label, icon }) => {
			const count = elements.filter(e => `${e.kind}s` === group).length;
			return { id: `bim:${group}`, label, description: String(count), icon, part: 'bim' };
		}).filter(n => n.description !== '0'),
	});
	if (docs.mep !== undefined) {
		nodes.push(mepNode(docs.mep));
	}
	return nodes;
}

/** What the MEP part holds, by service; each item opens the MEP editor. */
const MEP_LISTS: readonly { readonly id: string; readonly label: string; readonly icon: ThemeIcon; readonly path: readonly string[]; readonly describe: (item: Json) => string }[] = [
	{ id: 'shafts', label: localize('mep.shafts', "Shafts"), icon: Codicon.symbolArray, path: ['shafts'], describe: i => `${str(i.service)} · ${str(i.fromStory)} → ${str(i.toStory)}` },
	{ id: 'openings', label: localize('mep.openings', "Openings"), icon: Codicon.circleLarge, path: ['openings'], describe: i => `${str(i.kind)} · ${str(i.host)}` },
	{ id: 'equipment', label: localize('mep.equipment', "Equipment"), icon: Codicon.package, path: ['equipment'], describe: i => str(i.kind) },
	{ id: 'risers', label: localize('mep.plumbingRisers', "Plumbing Risers"), icon: Codicon.arrowUp, path: ['plumbing', 'risers'], describe: i => `${str(i.system)} · ${str(i.fromStory)} → ${str(i.toStory)}` },
	{ id: 'tanks', label: localize('mep.tanks', "Water Tanks"), icon: Codicon.database, path: ['plumbing', 'tanks'], describe: i => `${str(i.kind)} · ${str(i.story)}` },
	{ id: 'plant', label: localize('mep.hvacPlant', "HVAC Plant"), icon: Codicon.package, path: ['hvac', 'plant'], describe: i => `${str(i.kind)} · ${str(i.story)}` },
	{ id: 'ducts', label: localize('mep.ducts', "Ducts"), icon: Codicon.dash, path: ['hvac', 'ducts'], describe: i => `${str(i.system)} · ${str(i.story)}` },
	{ id: 'electrical', label: localize('mep.electricalEquipment', "Electrical Equipment"), icon: Codicon.zap, path: ['electrical', 'equipment'], describe: i => `${str(i.kind)} · ${str(i.story)}` },
	{ id: 'electricalRisers', label: localize('mep.electricalRisers', "Electrical Risers"), icon: Codicon.arrowUp, path: ['electrical', 'risers'], describe: i => `${str(i.kind)} · ${str(i.fromStory)} → ${str(i.toStory)}` },
	{ id: 'trays', label: localize('mep.trays', "Cable Trays"), icon: Codicon.dash, path: ['electrical', 'trays'], describe: i => str(i.story) },
];

function mepNode(mep: unknown): IModelNode {
	const lists = MEP_LISTS.map(l => {
		const items = list(l.path.reduce<unknown>((value, key) => isObject(value) ? value[key] : undefined, mep));
		return {
			id: `mep:${l.id}`, label: l.label, description: String(items.length), icon: l.icon, part: 'mep',
			children: items.map((item, index) => ({ id: `mep:${l.id}/${str(item.id ?? index)}`, label: str(item.id ?? index + 1), description: l.describe(item), icon: l.icon, part: 'mep' })),
		};
	}).filter(n => n.children.length);
	const count = lists.reduce((n, l) => n + l.children.length, 0);
	return {
		id: 'mep', label: localize('tree.mep', "MEP"), icon: Codicon.tools, part: 'mep',
		description: count ? localize('tree.mepCount', "{0} items", count) : localize('tree.mepEmpty', "nothing placed yet"),
		children: lists,
	};
}

/** The structural model of a special structure: its grid systems, members, areas and supports. */
function structureNode(structure: unknown, model: Model): IModelNode {
	const doc = isObject(structure) ? structure : {};
	const point = (p: unknown) => isObject(p) ? `(${num(p.x) ?? '?'}, ${num(p.y) ?? '?'}, ${num(p.z) ?? '?'})` : '?';
	const typeProblem = (entry: Json) => model.types.has(entry.type as string) ? undefined : localize('tree.unknownType', "Unknown object type '{0}'", str(entry.type));
	const section = (id: string, label: string, icon: ThemeIcon, entries: Json[], describe: (entry: Json) => string, typed: boolean): IModelNode => ({
		id: `structure:${id}`, label, description: String(entries.length), icon, part: 'structure',
		children: entries.map(e => ({
			id: `structure:${id}/${e.id}`, label: str(e.id), description: describe(e), icon, part: 'structure',
			problem: typed ? typeProblem(e) : undefined,
		})),
	});
	return {
		id: 'structure', label: localize('tree.structure', "Structural Model"), icon: Codicon.symbolStructure, part: 'structure',
		children: [
			section('grids', localize('tree.gridSystems', "Grid Systems"), Codicon.table, list(doc.grids), g => str(g.name) || str(g.kind), false),
			section('members', localize('tree.members', "Members"), Codicon.dash, list(doc.members), m => `${str(m.type)} · ${point(m.start)} → ${point(m.end)}`, true),
			section('areas', localize('tree.areas', "Areas"), Codicon.symbolArray, list(doc.areas), a => `${str(a.type)} · ${list(a.outline).length} corners`, true),
			section('supports', localize('tree.supports', "Supports"), Codicon.pinned, list(doc.supports), s => `${str(s.fixity) || 'fixed'} · ${point(s.at)}`, false),
		],
	};
}

function profileText(profile: unknown): string {
	if (!isObject(profile)) {
		return '—';
	}
	const n = (key: string) => Number((num(profile[key]) ?? 0).toFixed(1));
	switch (profile.shape) {
		case 'rectangle': return localize('profile.rectangle', "Rectangle {0} × {1} mm", n('xDim'), n('yDim'));
		case 'circle': return localize('profile.circle', "Circle Ø{0} mm", 2 * n('radius'));
		case 'rectangleHollow': return localize('profile.rhs', "Hollow rectangle {0} × {1} × {2} mm", n('xDim'), n('yDim'), n('wallThickness'));
		case 'circleHollow': return localize('profile.chs', "Hollow circle Ø{0} × {1} mm", 2 * n('radius'), n('wallThickness'));
		case 'I': return localize('profile.i', "I {0} × {1} mm (web {2}, flange {3})", n('overallWidth'), n('overallDepth'), n('webThickness'), n('flangeThickness'));
		case 'T': return localize('profile.t', "T {0} × {1} mm (web {2}, flange {3})", n('flangeWidth'), n('depth'), n('webThickness'), n('flangeThickness'));
		case 'L': return localize('profile.l', "L {0} × {1} × {2} mm", n('depth'), n('width'), n('thickness'));
		case 'U': return localize('profile.u', "U {0} × {1} mm (web {2}, flange {3})", n('flangeWidth'), n('depth'), n('webThickness'), n('flangeThickness'));
	}
	return str(profile.shape);
}

/** Rows describing an object type: what it is made of and its size. */
function typeRows(model: Model, type: Json): IPropertyRow[] {
	const material = model.materials.get(type.material as string);
	const rows: IPropertyRow[] = [
		{ label: localize('prop.typeName', "Name"), value: str(type.name) },
		{ label: localize('prop.material', "Material"), value: material ? `${str(material.name)} (${type.material})` : localize('prop.unknownMaterial', "Unknown material '{0}'", str(type.material)), problem: !material },
	];
	if (isObject(type.profile)) {
		rows.push({ label: localize('prop.profile', "Section"), value: profileText(type.profile) });
	}
	for (const [key, label] of [['thickness', localize('prop.thickness', "Thickness")], ['length', localize('prop.length', "Length")], ['width', localize('prop.width', "Width")]] as const) {
		if (num(type[key]) !== undefined) {
			rows.push({ label, value: mm(num(type[key])) });
		}
	}
	return rows;
}

function at(point: { label: string; at?: [number, number] }): string {
	return point.at ? `${point.label}  (x ${Number(point.at[0].toFixed(1))}, y ${Number(point.at[1].toFixed(1))})` : localize('prop.missingPoint', "{0} (grid line missing)", point.label);
}

/** The read-only property sheet of `selection`, or undefined when it no longer exists. */
export function propertySheet(selection: ModelSelection, docs: IProjectDocuments): IPropertySheet | undefined {
	const model = new Model(docs);
	switch (selection.kind) {
		case 'member': {
			const member = model.members(selection.group).find(m => m.id === selection.id);
			const info = GROUPS.find(g => g.group === selection.group)!;
			if (!member) {
				return undefined;
			}
			const type = model.types.get(member.type as string);
			const placement: IPropertyRow[] = [];
			const storyName = (id: unknown) => {
				const story = model.story(id);
				return story ? `${story.name} (${story.elevation >= 0 ? '+' : ''}${story.elevation})` : localize('prop.missingStory', "Missing story '{0}'", str(id));
			};
			const span = () => {
				const base = model.story(member.base);
				const top = model.story(member.top);
				placement.push({ label: localize('prop.base', "From"), value: storyName(member.base), problem: !base });
				placement.push({ label: localize('prop.top', "To"), value: storyName(member.top), problem: !top });
				placement.push({ label: localize('prop.height', "Height"), value: base && top ? mm(top.elevation - base.elevation) : '—' });
			};
			const line = () => {
				const start = model.point(member.start);
				const end = model.point(member.end);
				placement.push({ label: localize('prop.start', "Start"), value: at(start), problem: !start.at });
				placement.push({ label: localize('prop.end', "End"), value: at(end), problem: !end.at });
				placement.push({ label: localize('prop.length2', "Length"), value: start.at && end.at ? mm(Math.hypot(end.at[0] - start.at[0], end.at[1] - start.at[1])) : '—' });
			};
			switch (selection.group) {
				case 'columns': {
					const point = model.point(member.at);
					placement.push({ label: localize('prop.at', "Location"), value: at(point), problem: !point.at });
					span();
					placement.push({ label: localize('prop.rotation', "Rotation"), value: `${num(member.rotation) ?? 0}°` });
					break;
				}
				case 'walls':
					line();
					span();
					break;
				case 'beams':
					line();
					placement.push({ label: localize('prop.story', "Story"), value: storyName(member.story), problem: !model.story(member.story) });
					break;
				case 'slabs': {
					const corners = list(member.boundary).map(p => model.point(p));
					placement.push({ label: localize('prop.story', "Story"), value: storyName(member.story), problem: !model.story(member.story) });
					placement.push({ label: localize('prop.corners', "Corners"), value: corners.map(c => c.label).join(', ') });
					const points = corners.map(c => c.at).filter((p): p is [number, number] => !!p);
					placement.push({ label: localize('prop.area', "Area"), value: points.length === corners.length ? localize('m2', "{0} m²", Number((polygonArea(points) / 1e6).toFixed(2))) : '—' });
					break;
				}
				case 'footings': {
					const point = model.point(member.at);
					placement.push({ label: localize('prop.at', "Location"), value: at(point), problem: !point.at });
					placement.push({ label: localize('prop.topAt', "Top at"), value: storyName(member.story), problem: !model.story(member.story) });
					placement.push({ label: localize('prop.rotation', "Rotation"), value: `${num(member.rotation) ?? 0}°` });
					break;
				}
			}
			const status = model.buildingStatus();
			const element = list(isObject(docs.bim) ? docs.bim.elements : undefined).find(e => e.source === member.id);
			return {
				title: member.id as string,
				subtitle: info.singular,
				sections: [
					{ title: localize('section.placement', "Placement"), rows: placement },
					{
						title: localize('section.type', "Object Type"),
						rows: type
							? [{ label: localize('prop.type', "Type"), value: str(member.type) }, ...typeRows(model, type)]
							: [{ label: localize('prop.type', "Type"), value: localize('prop.unknownType', "Unknown object type '{0}'", str(member.type)), problem: true }],
					},
					{
						title: localize('section.bim', "Building Model"),
						rows: [{
							label: localize('prop.element', "Element"),
							value: status === 'none' ? localize('prop.notBuilt', "Not built yet")
								: !element ? localize('prop.notInBim', "Not in the building model yet (update it)")
									: status === 'outdated' ? localize('prop.outdated', "Built, but the Floor Plan changed since")
										: localize('prop.current', "Built and up to date"),
							problem: status !== 'current' || !element,
						}],
					},
				],
				actions: type ? ['showInFloorPlan', 'editObjectType'] : ['showInFloorPlan'],
				objectType: type ? member.type as string : undefined,
			};
		}
		case 'story': {
			const index = model.stories.findIndex(s => s.id === selection.id);
			const story = model.stories[index];
			if (!story) {
				return undefined;
			}
			const above = model.stories[index + 1];
			const below = model.stories[index - 1];
			return {
				title: story.name,
				subtitle: localize('kind.story', "Story"),
				sections: [
					{
						title: localize('section.level', "Level"),
						rows: [
							{ label: localize('prop.id', "ID"), value: story.id },
							{ label: localize('prop.elevation', "Elevation"), value: mm(story.elevation) },
							{ label: localize('prop.storyHeight', "Height below"), value: below ? mm(story.elevation - below.elevation) : '—' },
							{ label: localize('prop.storyAbove', "Story above"), value: above ? `${above.name} (${mm(above.elevation - story.elevation)} up)` : '—' },
						],
					},
					{
						title: localize('section.members', "Members on the Plan"),
						rows: GROUPS.map(g => ({ label: g.label, value: String(model.onStory(g.group, story).length) })),
					},
				],
				actions: ['showInFloorPlan', 'editGrids'],
			};
		}
		case 'gridLine': {
			const lines = selection.axis === 'x' ? model.x : model.y;
			const position = lines.get(selection.label);
			if (position === undefined) {
				return undefined;
			}
			const sorted = [...lines].sort((a, b) => a[1] - b[1]);
			const index = sorted.findIndex(([label]) => label === selection.label);
			const previous = sorted[index - 1];
			const next = sorted[index + 1];
			return {
				title: selection.label,
				subtitle: selection.axis === 'x' ? localize('kind.gridX', "X grid line") : localize('kind.gridY', "Y grid line"),
				sections: [{
					title: localize('section.grid', "Grid Line"),
					rows: [
						{ label: localize('prop.position', "Position"), value: mm(position) },
						{ label: localize('prop.previous', "From previous"), value: previous ? `${previous[0]}: ${mm(position - previous[1])}` : '—' },
						{ label: localize('prop.next', "To next"), value: next ? `${next[0]}: ${mm(next[1] - position)}` : '—' },
					],
				}],
				actions: ['editGrids'],
			};
		}
		case 'objectType': {
			const type = model.types.get(selection.id);
			if (!type) {
				return undefined;
			}
			const used = GROUPS.reduce((n, g) => n + model.members(g.group).filter(m => m.type === selection.id).length, 0);
			return {
				title: selection.id,
				subtitle: localize('kind.objectType', "Object type ({0})", str(type.kind)),
				sections: [{
					title: localize('section.objectType', "Object Type"),
					rows: [...typeRows(model, type), { label: localize('prop.used', "Placed members"), value: String(used) }],
				}],
				actions: ['editObjectType'],
				objectType: selection.id,
			};
		}
	}
}
