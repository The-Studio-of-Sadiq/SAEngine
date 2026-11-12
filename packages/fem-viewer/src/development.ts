/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import { FemElement, FemModel, FemNode, FemResultDisplay, FemResultView } from './model.js';

/** A plan path (model x, y in model units, usually metres), point by point. */
export type FemPlanPath = readonly (readonly [number, number])[];

/** Nodes within this of a path segment (in plan) lie on it [model units]. */
const TOLERANCE = 0.005;

/**
 * A developed (unfolded) elevation: the frames and walls standing on a plan path, laid out in one
 * plane with the distance along the path as the horizontal axis and the model's Z kept. The
 * model is rewritten into that plane: a node on the path at distance `s` along it moves to
 * `(s, w, z)`, where `w` is its (tiny) offset from the path; a node shared by two segments that
 * are not in line (a corner) is cloned so each segment's elements keep their own copy of it.
 * Vectors at a node (displacements, local axes, reactions) turn with its segment.
 */
export class Development {

	/** The developed model: the elements on the path, their nodes moved (and cloned at corners). */
	readonly model: FemModel;
	/** The ids of the original elements lying on the path. */
	readonly elements: ReadonlySet<number>;
	/** A clone's original node id (clones have new, negative ids). */
	private readonly cloneOf = new Map<number, number>();
	/** The developed ids of each original node on the path. */
	private readonly copies = new Map<number, number[]>();
	/** The angle of each developed node's segment in plan [rad] (by developed id). */
	private readonly angles = new Map<number, number>();

	constructor(readonly source: FemModel, readonly path: FemPlanPath) {
		const segments = segmentsOf(path);
		const coords = new Map(source.nodes.map(n => [n.id, n]));
		/** The segment(s) each node lies on, with its distance along the path and offset. */
		const placed = new Map<number, { segment: number; s: number; w: number }[]>();
		const placesOf = (node: FemNode) => {
			let places = placed.get(node.id);
			if (!places) {
				places = [];
				const x = node.coords[0] ?? 0;
				const y = node.coords[1] ?? 0;
				segments.forEach((seg, k) => {
					const dx = x - seg.x0;
					const dy = y - seg.y0;
					const along = dx * seg.cos + dy * seg.sin;
					const off = -dx * seg.sin + dy * seg.cos;
					if (Math.abs(off) <= TOLERANCE && along >= -TOLERANCE && along <= seg.length + TOLERANCE) {
						places!.push({ segment: k, s: seg.start + along, w: off });
					}
				});
				placed.set(node.id, places);
			}
			return places;
		};

		const elements: FemElement[] = [];
		const onPath = new Set<number>();
		const nodes = new Map<number, FemNode>();
		/** The developed id of node `id` on segment `k` (the node itself on its first segment). */
		const developedIds = new Map<string, number>();
		/** The developed id each node got first. */
		const firstIds = new Map<number, number>();
		let nextClone = -1;
		for (const element of source.elements) {
			const points = element.nodes.map(id => coords.get(id));
			if (!points.length || points.some(p => !p)) {
				continue;
			}
			// A segment every node of the element lies on.
			const common = placesOf(points[0]!).map(p => p.segment)
				.filter(k => points.every(p => placesOf(p!).some(q => q.segment === k)));
			if (!common.length) {
				continue;
			}
			const k = common[0];
			const seg = segments[k];
			onPath.add(element.id);
			const ids = element.nodes.map((id, i) => {
				const key = `${id}@${k}`;
				let developed = developedIds.get(key);
				if (developed === undefined) {
					const node = points[i]!;
					const place = placesOf(node).find(p => p.segment === k)!;
					// The node's first segment keeps its id; another (not in line) gets a clone,
					// unless both place it at the same distance (segments in line, or a path that
					// turns back on itself at the node).
					const first = firstIds.get(id);
					if (first === undefined) {
						developed = id;
						firstIds.set(id, id);
					} else {
						const firstNode = nodes.get(first)!;
						if (Math.abs((firstNode.coords[0] ?? 0) - place.s) <= TOLERANCE) {
							developed = first;
						} else {
							developed = nextClone--;
							this.cloneOf.set(developed, id);
						}
					}
					developedIds.set(key, developed);
					if (!nodes.has(developed)) {
						nodes.set(developed, { ...node, id: developed, coords: [place.s, place.w, node.coords[2] ?? 0] });
						this.angles.set(developed, seg.angle);
					}
				}
				return developed;
			});
			elements.push(ids.every((id, i) => id === element.nodes[i]) ? element : { ...element, nodes: ids });
		}
		this.elements = onPath;
		for (const id of nodes.keys()) {
			const original = this.original(id);
			const list = this.copies.get(original);
			if (list) {
				list.push(id);
			} else {
				this.copies.set(original, [id]);
			}
		}
		this.model = { ndm: 3, nodes: [...nodes.values()], elements };
	}

	/** The original id of developed node `id` (itself unless a clone). */
	original(id: number): number {
		return this.cloneOf.get(id) ?? id;
	}

	/**
	 * Model vector `v` (global x, y, z) at developed node `node`, in the developed plane's axes:
	 * along the path, across it, up.
	 */
	turn(v: readonly number[], node: number | undefined): [number, number, number] {
		const angle = node === undefined ? undefined : this.angles.get(node);
		const x = v[0] ?? 0;
		const y = v[1] ?? 0;
		const z = v[2] ?? 0;
		if (angle === undefined) {
			return [x, y, z];
		}
		const c = Math.cos(angle);
		const s = Math.sin(angle);
		return [x * c + y * s, -x * s + y * c, z];
	}

	/** Every developed id of original node `id` (the node itself and its clones). */
	developedIds(id: number): readonly number[] {
		return this.copies.get(id) ?? [];
	}

	/**
	 * A result in the developed plane: the node values of every copy of a node, the vectors
	 * turned with their segment, the shells' nodes as their elements', and no solids.
	 */
	results(view: FemResultView): FemResultView {
		const perNode = (rows: readonly (readonly number[])[]) => {
			const out: number[][] = [];
			for (const row of rows) {
				for (const id of this.developedIds(row[0])) {
					out.push([id, ...this.turn(row.slice(1, 4), id), ...this.turn(row.slice(4, 7), id)].slice(0, row.length));
				}
			}
			return out;
		};
		const elements = new Map(this.model.elements.map(e => [e.id, e]));
		return {
			...view,
			nodes: perNode(view.nodes),
			reactions: perNode(view.reactions),
			elements: view.elements.filter(e => elements.has(e.id)).map(e => {
				const node = elements.get(e.id)!.nodes[0];
				return {
					...e,
					y: this.turn(e.y, node),
					z: this.turn(e.z, node),
					displacements: e.displacements.map(d => [...this.turn(d.slice(0, 3), node), ...this.turn(d.slice(3, 6), node)].slice(0, d.length)),
				};
			}),
			shells: view.shells?.filter(s => elements.has(s.id)).map(s => ({ ...s, nodes: elements.get(s.id)!.nodes })),
			solids: [],
		};
	}

	/** A display whose node values (joint utilisation) are keyed by developed ids. */
	display(display: FemResultDisplay): FemResultDisplay {
		const joints = display.nodeUtilisation;
		if (!joints) {
			return display;
		}
		const out: { [nodeId: number]: number } = {};
		for (const [id, value] of Object.entries(joints)) {
			for (const developed of this.developedIds(Number(id))) {
				out[developed] = value;
			}
		}
		return { ...display, nodeUtilisation: out };
	}
}

interface Segment {
	readonly x0: number;
	readonly y0: number;
	readonly cos: number;
	readonly sin: number;
	readonly angle: number;
	readonly length: number;
	/** Distance along the path at the segment's start. */
	readonly start: number;
}

function segmentsOf(path: FemPlanPath): Segment[] {
	const segments: Segment[] = [];
	let start = 0;
	for (let k = 0; k + 1 < path.length; k++) {
		const [x0, y0] = path[k];
		const [x1, y1] = path[k + 1];
		const length = Math.hypot(x1 - x0, y1 - y0);
		if (length <= TOLERANCE) {
			continue;
		}
		const angle = Math.atan2(y1 - y0, x1 - x0);
		segments.push({ x0, y0, cos: Math.cos(angle), sin: Math.sin(angle), angle, length, start });
		start += length;
	}
	return segments;
}

/** Whether `path` has at least one segment longer than the tolerance. */
export function isUsablePath(path: FemPlanPath | undefined): path is FemPlanPath {
	return !!path && segmentsOf(path).length > 0;
}
