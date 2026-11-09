/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Alpha 9 L12: the pure parts of the visual programs (node graphs, `saengine.automation.graph`),
 * the design studies (`saengine.automation.studies`), the exchange exports and the office server:
 * documents read defensively, edits as functions returning new documents, the table and chart of
 * a study. No DOM and no services, so they are unit tested.
 */

export const GRAPH_SCHEMA = 'saengine.graph/1';
export const STUDY_SCHEMA = 'saengine.study/1';
/** The folder of the graphs and studies in a project (`saengine.automation.FOLDER`). */
export const AUTOMATION_FOLDER = '12 Automation';
export const GRAPH_EXTENSION = '.sagraph.json';
/** At most this many variants run in one study (`saengine.automation.studies.MAX_VARIANTS`). */
export const MAX_VARIANTS = 32;

//#region Graphs

export interface IPortType {
	readonly name: string;
	readonly type: string;
	readonly default?: unknown;
	readonly description?: string;
}

export interface INodeType {
	readonly id: string;
	readonly title: string;
	readonly category: string;
	readonly description?: string;
	readonly inputs: readonly IPortType[];
	readonly outputs: readonly IPortType[];
	readonly writes?: boolean;
}

export interface IGraphNode {
	readonly id: string;
	readonly type: string;
	readonly x: number;
	readonly y: number;
	readonly params: Readonly<Record<string, unknown>>;
}

export interface IPortRef {
	readonly node: string;
	readonly port: string;
}

export interface IGraphEdge {
	readonly from: IPortRef;
	readonly to: IPortRef;
}

export interface IGraphDocument {
	readonly schema: string;
	readonly name: string;
	readonly nodes: readonly IGraphNode[];
	readonly edges: readonly IGraphEdge[];
}

function record(value: unknown): Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function finite(value: unknown, fallback: number): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** The node types of the backend's `graph/nodeTypes` answer (unknown entries dropped). */
export function readNodeTypes(answer: unknown): INodeType[] {
	const types = record(answer).types;
	if (!Array.isArray(types)) {
		return [];
	}
	const ports = (value: unknown): IPortType[] => (Array.isArray(value) ? value : [])
		.map(record)
		.filter(p => typeof p.name === 'string')
		.map(p => ({ name: p.name as string, type: typeof p.type === 'string' ? p.type : 'any', default: p.default, description: typeof p.description === 'string' ? p.description : undefined }));
	return types.map(record).filter(t => typeof t.id === 'string' && typeof t.title === 'string').map(t => ({
		id: t.id as string,
		title: t.title as string,
		category: typeof t.category === 'string' ? t.category : '',
		description: typeof t.description === 'string' ? t.description : undefined,
		inputs: ports(t.inputs),
		outputs: ports(t.outputs),
		writes: t.writes === true,
	}));
}

/** A graph file's text as a document, or the problems that stop it being read. */
export function readGraph(text: string): { readonly graph?: IGraphDocument; readonly problems: string[] } {
	let raw: unknown;
	try {
		raw = JSON.parse(text);
	} catch (error) {
		return { problems: [`not JSON: ${error instanceof Error ? error.message : String(error)}`] };
	}
	const doc = record(raw);
	if (doc.schema !== GRAPH_SCHEMA) {
		return { problems: [`not a SAEngine graph (schema ${GRAPH_SCHEMA})`] };
	}
	const nodes: IGraphNode[] = [];
	const ids = new Set<string>();
	for (const n of Array.isArray(doc.nodes) ? doc.nodes.map(record) : []) {
		if (typeof n.id !== 'string' || typeof n.type !== 'string' || ids.has(n.id)) {
			continue;
		}
		ids.add(n.id);
		nodes.push({ id: n.id, type: n.type, x: finite(n.x, 40), y: finite(n.y, 40), params: { ...record(n.params) } });
	}
	const edges: IGraphEdge[] = [];
	for (const e of Array.isArray(doc.edges) ? doc.edges.map(record) : []) {
		const from = record(e.from), to = record(e.to);
		if (typeof from.node === 'string' && typeof from.port === 'string' && typeof to.node === 'string' && typeof to.port === 'string' && ids.has(from.node) && ids.has(to.node)) {
			edges.push({ from: { node: from.node, port: from.port }, to: { node: to.node, port: to.port } });
		}
	}
	return { graph: { schema: GRAPH_SCHEMA, name: typeof doc.name === 'string' ? doc.name : 'Graph', nodes, edges }, problems: [] };
}

export function writeGraph(graph: IGraphDocument): string {
	return JSON.stringify(graph, undefined, '\t') + '\n';
}

/** A node id not used in the graph yet (`n1`, `n2`, ...). */
export function nextNodeId(graph: IGraphDocument): string {
	const used = new Set(graph.nodes.map(n => n.id));
	let k = graph.nodes.length + 1;
	while (used.has(`n${k}`)) {
		k++;
	}
	return `n${k}`;
}

export function addNode(graph: IGraphDocument, type: INodeType, x: number, y: number): { readonly graph: IGraphDocument; readonly id: string } {
	const id = nextNodeId(graph);
	return { graph: { ...graph, nodes: [...graph.nodes, { id, type: type.id, x: Math.round(x), y: Math.round(y), params: {} }] }, id };
}

export function removeNode(graph: IGraphDocument, id: string): IGraphDocument {
	return {
		...graph,
		nodes: graph.nodes.filter(n => n.id !== id),
		edges: graph.edges.filter(e => e.from.node !== id && e.to.node !== id),
	};
}

export function moveNode(graph: IGraphDocument, id: string, x: number, y: number): IGraphDocument {
	return { ...graph, nodes: graph.nodes.map(n => n.id === id ? { ...n, x: Math.max(0, Math.round(x)), y: Math.max(0, Math.round(y)) } : n) };
}

export function setParam(graph: IGraphDocument, id: string, name: string, value: unknown): IGraphDocument {
	return {
		...graph,
		nodes: graph.nodes.map(n => {
			if (n.id !== id) {
				return n;
			}
			const params = { ...n.params };
			if (value === undefined || value === '') {
				delete params[name];
			} else {
				params[name] = value;
			}
			return { ...n, params };
		}),
	};
}

/** Whether `to` is reachable from `from` along the wires (a new wire back would make a loop). */
function reaches(graph: IGraphDocument, from: string, to: string): boolean {
	const seen = new Set<string>();
	const stack = [from];
	while (stack.length) {
		const id = stack.pop()!;
		if (id === to) {
			return true;
		}
		if (seen.has(id)) {
			continue;
		}
		seen.add(id);
		for (const e of graph.edges) {
			if (e.from.node === id) {
				stack.push(e.to.node);
			}
		}
	}
	return false;
}

/**
 * Wires an output to an input: an input takes one wire (a new one replaces the old). Refused
 * (undefined) for a node's own ports and for a wire that would close a loop.
 */
export function connect(graph: IGraphDocument, from: IPortRef, to: IPortRef): IGraphDocument | undefined {
	if (from.node === to.node || reaches(graph, to.node, from.node)) {
		return undefined;
	}
	const edges = graph.edges.filter(e => !(e.to.node === to.node && e.to.port === to.port));
	return { ...graph, edges: [...edges, { from, to }] };
}

export function disconnect(graph: IGraphDocument, to: IPortRef): IGraphDocument {
	return { ...graph, edges: graph.edges.filter(e => !(e.to.node === to.node && e.to.port === to.port)) };
}

/** A parameter typed in the properties panel as the value it stands for. */
export function parseParam(text: string, type: string): unknown {
	const trimmed = text.trim();
	if (trimmed === '') {
		return undefined;
	}
	if (type === 'number') {
		const value = Number(trimmed);
		return Number.isFinite(value) ? value : trimmed;
	}
	if (type === 'json' || type === 'any') {
		if (/^[[{"]|^(true|false|null)$|^-?\d/.test(trimmed)) {
			try {
				return JSON.parse(trimmed);
			} catch {
				return trimmed;
			}
		}
	}
	return trimmed;
}

export function formatParam(value: unknown): string {
	if (value === undefined || value === null) {
		return '';
	}
	return typeof value === 'string' ? value : JSON.stringify(value);
}

/** A run's output shown on a node: one short line. */
export function summariseOutput(value: unknown, max = 60): string {
	let text: string;
	if (typeof value === 'number') {
		text = Number.isInteger(value) ? String(value) : value.toPrecision(4);
	} else if (typeof value === 'string') {
		text = value;
	} else {
		text = JSON.stringify(value) ?? '';
	}
	return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

//#endregion

//#region Studies

export const PARAMETER_KINDS = ['gridSpacing', 'storeyHeight', 'concreteGrade', 'sectionScale', 'sectionFamily', 'setValue'] as const;
export type ParameterKind = typeof PARAMETER_KINDS[number];

export interface IStudyParameter {
	readonly kind: ParameterKind;
	readonly values: readonly unknown[];
	readonly axis?: string;
	readonly kinds?: readonly string[];
	/** sectionFamily: the object types whose members take the value's type. */
	readonly types?: readonly string[];
	readonly includeFirst?: boolean;
	readonly file?: string;
	readonly path?: string;
}

export interface IStudyDocument {
	readonly schema: string;
	readonly id: string;
	readonly name: string;
	readonly combine: 'all' | 'oneAtATime';
	readonly steps: readonly string[];
	readonly parameters: readonly IStudyParameter[];
}

/** Values typed as `0.9, 1.0, 1.1` (numbers where they are numbers). */
export function parseValues(text: string, kind: ParameterKind): unknown[] {
	return text.split(/[,;]/).map(v => v.trim()).filter(v => v.length > 0).map(v => {
		if (kind === 'concreteGrade' || kind === 'sectionFamily') {
			return v;
		}
		const n = Number(v);
		return Number.isFinite(n) ? n : v;
	});
}

export function variantCount(study: IStudyDocument): number {
	const counts = study.parameters.map(p => p.values.length);
	if (!counts.length || counts.some(c => c === 0)) {
		return 0;
	}
	return study.combine === 'oneAtATime'
		? 1 + counts.reduce((sum, c) => sum + c - 1, 0)
		: counts.reduce((product, c) => product * c, 1);
}

/** What stops a study from running (empty: it can run). */
export function studyProblems(study: IStudyDocument): string[] {
	const problems: string[] = [];
	if (!/^[A-Za-z0-9._-]{1,60}$/.test(study.id)) {
		problems.push('id');
	}
	if (!study.parameters.length) {
		problems.push('parameters');
	}
	const count = variantCount(study);
	if (count === 0) {
		problems.push('values');
	} else if (count > MAX_VARIANTS) {
		problems.push('tooMany');
	}
	return problems;
}

export function slugId(name: string): string {
	return name.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'study';
}

/** One row of a study's comparison table. */
export interface IStudyRow {
	readonly id: string;
	readonly label: string;
	readonly ok: boolean;
	readonly error?: string;
	readonly maxUtilisation?: number;
	readonly failed?: number;
	readonly drift?: number;
	readonly cost?: number;
	readonly steelKg?: number;
	readonly carbonKg?: number;
}

export const STUDY_METRICS = ['cost', 'steelKg', 'carbonKg', 'maxUtilisation', 'drift', 'failed'] as const;
export type StudyMetric = typeof STUDY_METRICS[number];

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** The rows of a study's `results.json`. */
export function studyRows(results: unknown): IStudyRow[] {
	const rows = record(results).rows;
	return (Array.isArray(rows) ? rows : []).map(record).filter(r => typeof r.id === 'string').map(r => {
		const design = record(r.design), boq = record(r.boq);
		return {
			id: r.id as string,
			label: typeof r.label === 'string' ? r.label : '',
			ok: r.ok === true,
			error: typeof r.error === 'string' ? r.error : undefined,
			maxUtilisation: num(design.maxUtilisation),
			failed: num(design.failed),
			drift: num(r.drift),
			cost: num(boq.cost),
			steelKg: num(boq.steelKg),
			carbonKg: num(boq.carbonKg),
		};
	});
}

export interface IChartBar {
	readonly id: string;
	readonly value: number | undefined;
	/** 0..1 of the largest value. */
	readonly fraction: number;
	readonly best: boolean;
}

/** The bars of `metric` (the lowest value is the best, as every metric here is a cost). */
export function chartBars(rows: readonly IStudyRow[], metric: StudyMetric): IChartBar[] {
	const values = rows.map(r => r[metric]);
	const known = values.filter((v): v is number => v !== undefined);
	const max = known.length ? Math.max(...known.map(Math.abs)) : 0;
	const min = known.length ? Math.min(...known) : undefined;
	return rows.map((r, k) => {
		const value = values[k];
		return { id: r.id, value, fraction: value === undefined || max === 0 ? 0 : Math.abs(value) / max, best: value !== undefined && value === min && known.length > 1 };
	});
}

//#endregion

//#region Exchange and the office server

export const EXCHANGE_FORMATS = ['s2k', 'std', 'saf', 'sdnf', 'cis2', 'webViewer'] as const;
export type ExchangeFormat = typeof EXCHANGE_FORMATS[number];

/** The office server's address as the backend gets it, or undefined when it is not one. */
export function officeServerUrl(text: string | undefined): string | undefined {
	const trimmed = (text ?? '').trim().replace(/\/+$/, '');
	if (!/^https?:\/\/[^\s/?#]+(:\d+)?(\/[^\s?#]*)?$/i.test(trimmed)) {
		return undefined;
	}
	return trimmed;
}

/** Why a project cannot go to the office server now (undefined: it can). */
export function officeBlocker(enabled: boolean, url: string | undefined, hasToken: boolean): 'disabled' | 'noUrl' | 'noToken' | undefined {
	if (!enabled) {
		return 'disabled';
	}
	if (!officeServerUrl(url)) {
		return 'noUrl';
	}
	return hasToken ? undefined : 'noToken';
}

/** Whether the address sends the token unencrypted over the network (http to another machine). */
export function isPlainNetworkUrl(url: string): boolean {
	const match = /^http:\/\/([^/:]+|\[[^\]]+\])/i.exec(url);
	if (!match) {
		return false;
	}
	const host = match[1].toLowerCase();
	return !(host === 'localhost' || host === '127.0.0.1' || host === '[::1]');
}

//#endregion
