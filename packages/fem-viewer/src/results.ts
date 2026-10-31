/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { disposeObject, Floats, ModelIndex } from './geometry.js';
import { LabelLayer } from './labels.js';
import { FemResultDisplay, FemResultElement, FemResultQuantity, FemResultShell, FemResultView, FemValueQuantity, FemVisibleElements, FORCE_COMPONENTS, formatUtilisation, outerFaces, SHELL_COMPONENTS, SOLID_COMPONENTS, utilisationBand } from './model.js';

export interface ResultColors {
	readonly deformed: string;
	readonly positive: string;
	readonly negative: string;
	readonly reaction: string;
	/** Design utilisation bands: below 0.9, 0.9 to 1.0, above 1.0. */
	readonly pass: string;
	readonly warn: string;
	readonly fail: string;
	readonly label: string;
	readonly labelBackground: string;
}

/** Colour stops of the contour scale, from the lowest value (blue) to the highest (red). */
const CONTOUR_STOPS: readonly (readonly [number, number, number])[] = [
	[0.19, 0.31, 0.89], [0.13, 0.72, 0.93], [0.25, 0.80, 0.42], [0.98, 0.84, 0.18], [0.91, 0.24, 0.19],
];

/** Colour (r, g, b in 0 … 1) of the contour scale at `t` (0: lowest, 1: highest). */
export function contourColor(t: number): [number, number, number] {
	const x = Math.min(1, Math.max(0, t)) * (CONTOUR_STOPS.length - 1);
	const k = Math.min(CONTOUR_STOPS.length - 2, Math.floor(x));
	const f = x - k;
	const [a, b] = [CONTOUR_STOPS[k], CONTOUR_STOPS[k + 1]];
	return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** Most member labels drawn at once: beyond it, the largest values only. */
const MAX_MEMBER_LABELS = 400;

/** Share of the model size the largest value is drawn at (scale 1). */
const DEFORMED_SHARE = 0.06;
const DIAGRAM_SHARE = 0.08;
const REACTION_SHARE = 0.1;

/**
 * Where each section force's diagram is drawn, as (local axis, sign). Moments are drawn on the
 * tension side: positive My stretches the +z fibres, positive Mz the -y fibres.
 */
const DIAGRAM_SIDE: { readonly [quantity: string]: readonly ['y' | 'z', number] } = {
	N: ['y', 1], Vy: ['y', 1], Vz: ['z', 1], T: ['y', 1], My: ['z', 1], Mz: ['y', -1],
};

/** A value and where its label goes. */
interface Extreme {
	readonly value: number;
	readonly at: THREE.Vector3;
}

/** The smallest of `values` (no spread: a model's worth of arguments overflows the stack). */
function least(values: ArrayLike<number>): number {
	let result = Infinity;
	for (let i = 0; i < values.length; i++) {
		result = Math.min(result, values[i]);
	}
	return result;
}

function largest(values: ArrayLike<number>): number {
	let result = -Infinity;
	for (let i = 0; i < values.length; i++) {
		result = Math.max(result, values[i]);
	}
	return result;
}

/** A key of the edge between nodes `a` and `b`, the same both ways. */
function edgeKey(a: number, b: number): number | string {
	const [low, high] = a < b ? [a, b] : [b, a];
	// Exact as a number while the ids fit in 21 bits each; else a string.
	return low >= 0 && high < 0x200000 ? low * 0x200000 + high : `${low}-${high}`;
}

/**
 * The drawing of one analysis result over the model: deflected shape, a force diagram, or the
 * support reactions, with labels of the largest value and of the selected element.
 */
export class ResultOverlay {

	readonly group = new THREE.Group();
	private readonly results: FemResultView;
	private readonly labels: LabelLayer;
	private animated: THREE.LineSegments | undefined;
	/** Adds the labels (some depend on the selected element); undefined: none. */
	private labelling: (() => void) | undefined;
	/** The labels change with the selected element. */
	private labelsFollowSelection = false;
	private memberExtremes: readonly Extreme[] | undefined;
	/** The nodes of the elements drawn; undefined: all of them. */
	private readonly visibleNodes: ReadonlySet<number> | undefined;

	constructor(
		private readonly index: ModelIndex,
		results: FemResultView,
		private readonly display: FemResultDisplay,
		private readonly colors: ResultColors,
		private selectedElement: number | undefined,
		/** Only these elements (and their nodes) are drawn; all when undefined. */
		private readonly visible: FemVisibleElements = undefined,
	) {
		this.labels = new LabelLayer(colors.labelBackground);
		this.group.add(this.labels.group);
		if (visible) {
			// The part of the result that belongs to what is shown.
			const nodes = new Set<number>();
			for (const id of visible) {
				const element = index.elements.get(id);
				if (element) {
					for (const n of element.nodes) {
						nodes.add(n);
					}
				}
			}
			this.visibleNodes = nodes;
			results = {
				...results,
				nodes: results.nodes.filter(n => nodes.has(n[0])),
				reactions: results.reactions.filter(r => nodes.has(r[0])),
				elements: results.elements.filter(e => visible.has(e.id)),
				shells: results.shells?.filter(s => visible.has(s.id)),
				solids: results.solids?.filter(s => visible.has(s.id)),
			};
		}
		this.results = results;
		if (display.show === 'deformed') {
			this.drawDeformed();
		} else if (SHELL_COMPONENTS.includes(display.show)) {
			this.drawContour(SHELL_COMPONENTS.indexOf(display.show));
		} else if (display.show === 'shellValues') {
			this.drawShellValues(display.shellValues ?? {}, display.shellValueQuantity ?? 'forcePerLength');
		} else if (display.show in SOLID_COMPONENTS) {
			this.drawStress(SOLID_COMPONENTS[display.show]);
		} else if (display.show === 'reactions') {
			this.drawReactions();
		} else if (display.show === 'utilisation') {
			this.drawUtilisation(display.utilisation ?? {});
		} else {
			this.drawDiagram(display.show);
		}
		this.drawLabels();
	}

	/** True when the shape oscillates (call {@link setPhase} every frame). */
	get isAnimated(): boolean {
		return !!this.animated;
	}

	/** Mode shape animation: the shape times `phase` (-1 … 1), moved on the GPU. */
	setPhase(phase: number): void {
		const influences = this.animated?.morphTargetInfluences;
		if (influences) {
			influences[0] = phase;
		}
	}

	/** Relabels for another selected element; the drawing stays. */
	setSelectedElement(id: number | undefined): void {
		if (id === this.selectedElement) {
			return;
		}
		this.selectedElement = id;
		if (this.labelsFollowSelection) {
			this.drawLabels();
		}
	}

	/**
	 * Labels keep their size on screen without attenuation only under a perspective camera; an
	 * orthographic one (plans, elevations) gives `factor`, the world size of the same share of
	 * the view, by which their sizes are multiplied.
	 */
	setLabelScale(factor: number): void {
		this.labels.setScale(factor);
	}

	dispose(): void {
		this.labels.dispose();
		for (const child of [...this.group.children]) {
			this.group.remove(child);
			if (child !== this.labels.group) {
				disposeObject(child);
			}
		}
	}

	private drawLabels(): void {
		this.labels.reset();
		this.labelling?.();
		this.labels.build();
	}

	private addLabel(text: string, position: THREE.Vector3, color: string, height?: number): void {
		this.labels.add(text, position, color, height);
	}

	/**
	 * The world positions of the `count` stations of `element` (evenly spaced from its node i to
	 * j) into `target` (x, y, z each), or false when the model lacks one of its nodes.
	 */
	private stations(element: FemResultElement, count: number, target: Float64Array): boolean {
		const source = this.index.elements.get(element.id);
		const a = source ? this.index.offset(source.nodes[0]) : -1;
		const b = source ? this.index.offset(source.nodes[1]) : -1;
		if (a < 0 || b < 0) {
			return false;
		}
		const w = this.index.world;
		for (let k = 0; k < count; k++) {
			const t = count > 1 ? k / (count - 1) : 0;
			for (let c = 0; c < 3; c++) {
				target[k * 3 + c] = w[a + c] + (w[b + c] - w[a + c]) * t;
			}
		}
		return true;
	}

	private drawDeformed(): void {
		const index = this.index;
		const world = index.world;
		const results = this.results;
		let peak = 0;
		for (const element of results.elements) {
			for (const d of element.displacements) {
				peak = Math.max(peak, Math.hypot(d[0], d[1], d[2]));
			}
		}
		const moved = new Map(results.nodes.map(n => [n[0], n]));
		// Solids: the edges of their outer faces, moving with their nodes, as for shells.
		const solidFaces = outerFaces(results.solids ?? []).map(f => ({ nodes: f.nodes }));
		const surfaces = [...(results.shells ?? []), ...solidFaces];
		for (const shell of surfaces) {
			for (const id of shell.nodes) {
				const d = moved.get(id);
				peak = Math.max(peak, d ? Math.hypot(d[1], d[2], d[3]) : 0);
			}
		}
		const factor = peak > 0 ? this.display.scale * DEFORMED_SHARE * index.size / peak : 0;
		const base = new Floats();
		const delta = new Floats();
		const move = new THREE.Vector3();
		// Shells and solids: their edges, each once, moving with their nodes.
		const edges = new Set<number | string>();
		const pushNode = (id: number, offset: number) => {
			base.pushFrom(world, offset, 3);
			const d = moved.get(id);
			if (d) {
				index.vector([d[1], d[2], d[3]], move).multiplyScalar(factor);
				delta.pushVector(move);
			} else {
				delta.push3(0, 0, 0);
			}
		};
		for (const shell of surfaces) {
			const n = shell.nodes;
			for (let k = 0; k < n.length; k++) {
				const a = n[k];
				const b = n[(k + 1) % n.length];
				const key = edgeKey(a, b);
				const oa = index.offset(a);
				const ob = index.offset(b);
				if (edges.has(key) || oa < 0 || ob < 0) {
					continue;
				}
				edges.add(key);
				pushNode(a, oa);
				pushNode(b, ob);
			}
		}
		let largestMove: Extreme | undefined;
		let points = new Float64Array(33);
		let moves = new Float64Array(33);
		for (const element of results.elements) {
			const count = element.displacements.length;
			if (points.length < count * 3) {
				points = new Float64Array(count * 3);
				moves = new Float64Array(count * 3);
			}
			if (!count || !this.stations(element, count, points)) {
				continue;
			}
			for (let k = 0; k < count; k++) {
				const d = element.displacements[k];
				index.vector(d, move).multiplyScalar(factor).toArray(moves, k * 3);
				const magnitude = Math.hypot(d[0], d[1], d[2]);
				if (!largestMove || magnitude > largestMove.value) {
					largestMove = { value: magnitude, at: new THREE.Vector3().fromArray(points, k * 3).add(move) };
				}
			}
			for (let k = 0; k + 1 < count; k++) {
				base.pushFrom(points, k * 3, 6);
				delta.pushFrom(moves, k * 3, 6);
			}
		}
		if (!base.length) {
			return;
		}
		const geometry = new THREE.BufferGeometry();
		const animate = this.results.kind === 'modal' && this.display.animate;
		if (animate) {
			// The shape times the phase, on the GPU: the undeformed lines plus the moves as a
			// (relative) morph target whose influence is the phase.
			geometry.setAttribute('position', base.attribute());
			geometry.morphAttributes.position = [delta.attribute()];
			geometry.morphTargetsRelative = true;
		} else {
			const positions = base.toArray();
			const moves = delta.toArray();
			for (let i = 0; i < positions.length; i++) {
				positions[i] += moves[i];
			}
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
		}
		const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: this.colors.deformed }));
		lines.frustumCulled = false;
		this.group.add(lines);
		if (animate) {
			lines.morphTargetInfluences = [1];
			this.animated = lines;
		}
		if (this.results.kind === 'modal') {
			return; // mode shapes have no physical size
		}
		if (largestMove && largestMove.value > 0) {
			this.labelling = this.fixedLabel(this.display.format('length', largestMove.value), largestMove.at, this.colors.deformed);
		}
	}

	private drawDiagram(quantity: FemResultQuantity): void {
		const component = FORCE_COMPONENTS.indexOf(quantity);
		const [axis, sign] = DIAGRAM_SIDE[quantity];
		const results = this.results;
		let peak = 0;
		for (const element of results.elements) {
			for (const f of element.forces ?? []) {
				peak = Math.max(peak, Math.abs(f[component]));
			}
		}
		if (peak <= 0) {
			return;
		}
		const factor = this.display.scale * DIAGRAM_SHARE * this.index.size / peak;
		const positive = new THREE.Color(this.colors.positive);
		const negative = new THREE.Color(this.colors.negative);
		const fill = new Floats();
		const fillColors = new Floats();
		const outline = new Floats();
		const outlineColors = new Floats();
		const quantityKind = quantity === 'N' || quantity === 'Vy' || quantity === 'Vz' ? 'force' : 'moment';
		const corner = (points: Float64Array, k: number, color: THREE.Color) => {
			fill.pushFrom(points, k * 3, 3);
			fillColors.push3(color.r, color.g, color.b);
		};
		const zero = new Float64Array(3);
		const crossing = (color: THREE.Color) => {
			fill.pushFrom(zero, 0, 3);
			fillColors.push3(color.r, color.g, color.b);
		};
		const segmentEnd = (points: Float64Array, k: number, color: THREE.Color) => {
			outline.pushFrom(points, k * 3, 3);
			outlineColors.push3(color.r, color.g, color.b);
		};
		const zeroEnd = (color: THREE.Color) => {
			outline.pushFrom(zero, 0, 3);
			outlineColors.push3(color.r, color.g, color.b);
		};
		const side = new THREE.Vector3();
		let biggest: { value: number; element: FemResultElement; k: number } | undefined;
		let bases = new Float64Array(33);
		let tips = new Float64Array(33);
		for (const element of results.elements) {
			const forces = element.forces;
			if (!forces?.length) {
				continue;
			}
			const count = forces.length;
			if (bases.length < count * 3) {
				bases = new Float64Array(count * 3);
				tips = new Float64Array(count * 3);
			}
			if (!this.stations(element, count, bases)) {
				continue;
			}
			this.index.vector(element[axis], side).normalize().multiplyScalar(sign * factor);
			for (let k = 0; k < count; k++) {
				const value = forces[k][component];
				tips[k * 3] = bases[k * 3] + side.x * value;
				tips[k * 3 + 1] = bases[k * 3 + 1] + side.y * value;
				tips[k * 3 + 2] = bases[k * 3 + 2] + side.z * value;
			}
			for (let k = 0; k + 1 < count; k++) {
				const v0 = forces[k][component];
				const v1 = forces[k + 1][component];
				if (v0 * v1 >= 0) {
					const color = v0 + v1 >= 0 ? positive : negative;
					corner(bases, k, color);
					corner(bases, k + 1, color);
					corner(tips, k + 1, color);
					corner(bases, k, color);
					corner(tips, k + 1, color);
					corner(tips, k, color);
					segmentEnd(tips, k, color);
					segmentEnd(tips, k + 1, color);
				} else {
					// The diagram crosses the axis inside the segment: split it there.
					const t = v0 / (v0 - v1);
					for (let c = 0; c < 3; c++) {
						zero[c] = bases[k * 3 + c] + (bases[(k + 1) * 3 + c] - bases[k * 3 + c]) * t;
					}
					const c0 = v0 > 0 ? positive : negative;
					const c1 = v1 > 0 ? positive : negative;
					corner(bases, k, c0);
					crossing(c0);
					corner(tips, k, c0);
					crossing(c1);
					corner(bases, k + 1, c1);
					corner(tips, k + 1, c1);
					segmentEnd(tips, k, c0);
					zeroEnd(c0);
					zeroEnd(c1);
					segmentEnd(tips, k + 1, c1);
				}
			}
			const first = forces[0][component] >= 0 ? positive : negative;
			segmentEnd(bases, 0, first);
			segmentEnd(tips, 0, first);
			const last = forces[count - 1][component] >= 0 ? positive : negative;
			segmentEnd(bases, count - 1, last);
			segmentEnd(tips, count - 1, last);
			for (let k = 0; k < count; k++) {
				const value = forces[k][component];
				if (!biggest || Math.abs(value) > Math.abs(biggest.value)) {
					biggest = { value, element, k };
				}
			}
		}
		if (fill.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', fill.attribute());
			geometry.setAttribute('color', fillColors.attribute());
			this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				vertexColors: true, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false,
			})));
			const lines = new THREE.BufferGeometry();
			lines.setAttribute('position', outline.attribute());
			lines.setAttribute('color', outlineColors.attribute());
			this.group.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ vertexColors: true })));
		}

		this.labelsFollowSelection = true;
		this.labelling = this.diagramLabels(component, quantityKind, factor, peak, biggest);
	}

	/**
	 * The labels of a diagram: the selected element's end values and its extreme inside; else
	 * every member's extremes (`memberLabels`), or the largest value of all.
	 * (A method of its own so the labels do not keep the drawing's buffers alive.)
	 */
	private diagramLabels(component: number, quantityKind: 'force' | 'moment', factor: number, peak: number, biggest: { value: number; element: FemResultElement; k: number } | undefined): () => void {
		const [axis, sign] = DIAGRAM_SIDE[FORCE_COMPONENTS[component]];
		const side = new THREE.Vector3();
		/** The diagram's tip at station `k` of `element`. */
		const tipOf = (element: FemResultElement, k: number): THREE.Vector3 => {
			const forces = element.forces!;
			const points = new Float64Array(forces.length * 3);
			this.stations(element, forces.length, points);
			this.index.vector(element[axis], side).normalize().multiplyScalar(sign * factor);
			return new THREE.Vector3().fromArray(points, k * 3).addScaledVector(side, forces[k][component]);
		};
		const valueColor = (value: number) => value >= 0 ? this.colors.positive : this.colors.negative;
		return () => {
			const selected = this.selectedElement;
			if (selected !== undefined) {
				// The selected element: its end values and its extreme inside.
				const element = this.results.elements.find(e => e.id === selected);
				const forces = element?.forces;
				if (element && forces?.length && this.stations(element, forces.length, new Float64Array(forces.length * 3))) {
					const count = forces.length;
					let extreme = 0;
					for (let k = 0; k < count; k++) {
						if (Math.abs(forces[k][component]) > Math.abs(forces[extreme][component])) {
							extreme = k;
						}
					}
					for (const k of new Set([0, count - 1, extreme])) {
						const value = forces[k][component];
						this.addLabel(this.display.format(quantityKind, value), tipOf(element, k), valueColor(value));
					}
				}
			} else if (this.display.memberLabels) {
				for (const label of this.memberLabels(component, peak, factor, axis, sign)) {
					this.addLabel(this.display.format(quantityKind, label.value), label.at, valueColor(label.value), 0.032);
				}
			} else if (biggest) {
				this.addLabel(this.display.format(quantityKind, biggest.value), tipOf(biggest.element, biggest.k), valueColor(biggest.value));
			}
		};
	}

	/** One label that does not change with the selection. */
	private fixedLabel(text: string, at: THREE.Vector3, color: string): () => void {
		return () => this.addLabel(text, at, color);
	}

	private reactionLabels(labels: readonly Extreme[]): () => void {
		return () => {
			for (const label of labels) {
				this.addLabel(this.display.format('force', label.value), label.at, this.colors.reaction);
			}
		};
	}

	/**
	 * The largest and the least value of every member (the elements named `B1`, `B1#2`, ...),
	 * at the diagram's tip; zero values and values below 1 % of the model's peak are left out.
	 * Worked out once per drawing.
	 */
	private memberLabels(component: number, peak: number, factor: number, axis: 'y' | 'z', sign: number): readonly Extreme[] {
		if (this.memberExtremes) {
			return this.memberExtremes;
		}
		const side = new THREE.Vector3();
		const members = new Map<string, { max?: Extreme; min?: Extreme }>();
		let bases = new Float64Array(33);
		for (const element of this.results.elements) {
			const forces = element.forces;
			if (!forces?.length) {
				continue;
			}
			if (bases.length < forces.length * 3) {
				bases = new Float64Array(forces.length * 3);
			}
			this.index.vector(element[axis], side).normalize().multiplyScalar(sign * factor);
			const member = element.name.split('#')[0];
			const entry = members.get(member) ?? {};
			if (this.stations(element, forces.length, bases)) {
				forces.forEach((f, k) => {
					const value = f[component];
					if (!entry.max || value > entry.max.value) {
						entry.max = { value, at: new THREE.Vector3().fromArray(bases, k * 3).addScaledVector(side, value) };
					}
					if (!entry.min || value < entry.min.value) {
						entry.min = { value, at: new THREE.Vector3().fromArray(bases, k * 3).addScaledVector(side, value) };
					}
				});
			}
			members.set(member, entry);
		}
		// Two members ending at the same point (within 1e-6) label it once: look for a label
		// already there in the grid cells around the point.
		const labels: Extreme[] = [];
		const cell = 1e-6;
		const grid = new Map<string, Extreme[]>();
		const near = (at: THREE.Vector3) => {
			const [i, j, k] = [Math.floor(at.x / cell), Math.floor(at.y / cell), Math.floor(at.z / cell)];
			for (let di = -1; di <= 1; di++) {
				for (let dj = -1; dj <= 1; dj++) {
					for (let dk = -1; dk <= 1; dk++) {
						if (grid.get(`${i + di},${j + dj},${k + dk}`)?.some(l => l.at.distanceToSquared(at) < 1e-12)) {
							return true;
						}
					}
				}
			}
			return false;
		};
		for (const { max, min } of members.values()) {
			for (const extreme of [max, min]) {
				if (extreme && Math.abs(extreme.value) >= 0.01 * peak && !near(extreme.at)) {
					labels.push(extreme);
					const key = `${Math.floor(extreme.at.x / cell)},${Math.floor(extreme.at.y / cell)},${Math.floor(extreme.at.z / cell)}`;
					grid.set(key, [...grid.get(key) ?? [], extreme]);
				}
			}
		}
		labels.sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
		return this.memberExtremes = labels.slice(0, MAX_MEMBER_LABELS);
	}

	/**
	 * The world positions of the nodes of `nodes` (x, y, z each), or undefined when the model
	 * lacks one of them.
	 */
	private corners(nodes: readonly number[]): Float64Array | undefined {
		const points = new Float64Array(nodes.length * 3);
		for (let k = 0; k < nodes.length; k++) {
			const o = this.index.offset(nodes[k]);
			if (o < 0) {
				return undefined;
			}
			points[k * 3] = this.index.world[o];
			points[k * 3 + 1] = this.index.world[o + 1];
			points[k * 3 + 2] = this.index.world[o + 2];
		}
		return points;
	}

	/** Triangles fanning from the first corner, and the outline (each edge as a segment). */
	private static polygon(points: Float64Array, faces: Floats, outline: Floats | undefined): void {
		const n = points.length / 3;
		for (let k = 1; k + 1 < n; k++) {
			faces.pushFrom(points, 0, 3);
			faces.pushFrom(points, k * 3, 6);
		}
		if (outline) {
			for (let k = 0; k < n; k++) {
				outline.pushFrom(points, k * 3, 3);
				outline.pushFrom(points, ((k + 1) % n) * 3, 3);
			}
		}
	}

	private static centre(points: Float64Array): THREE.Vector3 {
		const n = points.length / 3;
		const centre = new THREE.Vector3();
		for (let k = 0; k < n; k++) {
			centre.x += points[k * 3];
			centre.y += points[k * 3 + 1];
			centre.z += points[k * 3 + 2];
		}
		return centre.divideScalar(n);
	}

	/**
	 * Shell section force `component` as a contour: each shell coloured by its value at its
	 * centre on the scale from the lowest value (blue) to the highest (red).
	 */
	private drawContour(component: number): void {
		const shells = (this.results.shells ?? []).filter(s => s.forces);
		const kind = component < 3 ? 'forcePerLength' : component < 6 ? 'momentPerLength' : 'forcePerLength';
		this.contour(shells, shells.map(s => s.forces![component]), kind);
	}

	/** One given value per shell (by element id) as a contour; shells without one are left out. */
	private drawShellValues(byId: { readonly [elementId: number]: number }, kind: FemValueQuantity): void {
		const shells = (this.results.shells ?? []).filter(s => byId[s.id] !== undefined);
		this.contour(shells, shells.map(s => byId[s.id]), kind);
	}

	/** `shells` coloured by their `values` from the least to the largest, the largest labelled. */
	private contour(shells: readonly FemResultShell[], values: readonly number[], kind: FemValueQuantity): void {
		if (!shells.length) {
			return;
		}
		const low = least(values);
		const high = largest(values);
		const positions = new Floats();
		const colors = new Floats();
		const outline = new Floats();
		let biggest: Extreme | undefined;
		shells.forEach((shell, index) => {
			const points = this.corners(shell.nodes);
			if (!points) {
				return;
			}
			const [r, g, b] = contourColor(high > low ? (values[index] - low) / (high - low) : 0.5);
			const before = positions.length;
			ResultOverlay.polygon(points, positions, outline);
			for (let i = before; i < positions.length; i += 3) {
				colors.push3(r, g, b);
			}
			if (!biggest || Math.abs(values[index]) > Math.abs(biggest.value)) {
				biggest = { value: values[index], at: ResultOverlay.centre(points) };
			}
		});
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', positions.attribute());
		geometry.setAttribute('color', colors.attribute());
		this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
			vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
		})));
		const lines = new THREE.BufferGeometry();
		lines.setAttribute('position', outline.attribute());
		this.group.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color: this.colors.labelBackground, transparent: true, opacity: 0.5 })));
		if (biggest) {
			this.labelling = this.fixedLabel(this.display.format(kind, biggest.value), biggest.at, this.colors.label);
		}
	}

	/**
	 * A solid stress (`index` in {@link FemResultSolid.stress}) as a contour on the solids' outer
	 * faces: each face coloured by its tetrahedron's (constant) value.
	 */
	private drawStress(index: number): void {
		const solids = (this.results.solids ?? []).filter(s => s.stress);
		if (!solids.length) {
			return;
		}
		const values = solids.map(s => s.stress![index]);
		const low = least(values);
		const high = largest(values);
		const positions = new Floats();
		const colors = new Floats();
		let biggest: Extreme | undefined;
		for (const face of outerFaces(solids)) {
			const points = this.corners(face.nodes);
			if (!points) {
				continue;
			}
			const value = values[face.owner];
			const [r, g, b] = contourColor(high > low ? (value - low) / (high - low) : 0.5);
			positions.pushFrom(points, 0, 9);
			colors.push3(r, g, b);
			colors.push3(r, g, b);
			colors.push3(r, g, b);
			if (!biggest || Math.abs(value) > Math.abs(biggest.value)) {
				biggest = { value, at: ResultOverlay.centre(points) };
			}
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', positions.attribute());
		geometry.setAttribute('color', colors.attribute());
		this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
			vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
		})));
		if (biggest) {
			this.labelling = this.fixedLabel(this.display.format('stress', biggest.value), biggest.at, this.colors.label);
		}
	}

	/**
	 * Every support reaction as an arrow ending at its node (as `THREE.ArrowHelper` draws one),
	 * all the shafts in one draw and all the heads in another.
	 */
	private drawReactions(): void {
		let peak = 0;
		for (const r of this.results.reactions) {
			peak = Math.max(peak, Math.hypot(r[1], r[2], r[3]));
		}
		if (peak <= 0) {
			return;
		}
		const factor = this.display.scale * REACTION_SHARE * this.index.size / peak;
		const shafts = new Floats();
		const heads: THREE.Matrix4[] = [];
		const labels: Extreme[] = [];
		const up = new THREE.Vector3(0, 1, 0);
		for (const r of this.results.reactions) {
			const at = this.index.point(r[0]);
			const magnitude = Math.hypot(r[1], r[2], r[3]);
			if (!at || magnitude <= peak * 1e-6) {
				continue;
			}
			const direction = this.index.vector([r[1], r[2], r[3]]).normalize();
			const length = Math.max(magnitude * factor, this.index.size * 0.01);
			const headLength = length * 0.25;
			const headWidth = length * 0.12;
			// The support pushes on the structure: the arrow ends at the node.
			const origin = at.clone().addScaledVector(direction, -length);
			shafts.pushVector(origin);
			shafts.pushVector(origin.clone().addScaledVector(direction, Math.max(0.0001, length - headLength)));
			const rotation = direction.y > 0.99999 ? new THREE.Quaternion()
				: direction.y < -0.99999 ? new THREE.Quaternion(1, 0, 0, 0)
					: new THREE.Quaternion().setFromUnitVectors(up, direction);
			heads.push(new THREE.Matrix4().compose(at, rotation, new THREE.Vector3(headWidth, headLength, headWidth)));
			labels.push({ value: magnitude, at: origin });
		}
		if (!heads.length) {
			return;
		}
		const color = new THREE.Color(this.colors.reaction);
		const lines = new THREE.BufferGeometry();
		lines.setAttribute('position', shafts.attribute());
		this.group.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color, toneMapped: false })));
		const cone = new THREE.ConeGeometry(0.5, 1, 5, 1);
		cone.translate(0, -0.5, 0);
		const cones = new THREE.InstancedMesh(cone, new THREE.MeshBasicMaterial({ color, toneMapped: false }), heads.length);
		heads.forEach((matrix, i) => cones.setMatrixAt(i, matrix));
		cones.computeBoundingSphere();
		this.group.add(cones);
		this.labelling = this.reactionLabels(labels);
	}

	/**
	 * Frame elements (as lines) and shells (as filled faces, e.g. a slab's elements all with the
	 * slab's value) coloured by their design utilisation band (pass, warn, fail), labelled with
	 * the selected element's value, or else the largest.
	 */
	private drawUtilisation(utilisation: { readonly [elementId: number]: number }): void {
		const bands = { pass: new THREE.Color(this.colors.pass), warn: new THREE.Color(this.colors.warn), fail: new THREE.Color(this.colors.fail) };
		const positions = new Floats();
		const colors = new Floats();
		const faces = new Floats();
		const faceColors = new Floats();
		const outline = new Floats();
		let biggest: Extreme | undefined;
		for (const [key, value] of Object.entries(utilisation)) {
			const id = Number(key);
			const element = this.index.elements.get(id);
			if (!element || (this.visible && !this.visible.has(id))) {
				continue;
			}
			const points = this.corners(element.nodes);
			if (!points || points.length < 6) {
				continue;
			}
			const color = bands[utilisationBand(value)];
			if (points.length === 6) {
				positions.pushFrom(points, 0, 6);
				colors.push3(color.r, color.g, color.b);
				colors.push3(color.r, color.g, color.b);
			} else {
				const before = faces.length;
				ResultOverlay.polygon(points, faces, outline);
				for (let i = before; i < faces.length; i += 3) {
					faceColors.push3(color.r, color.g, color.b);
				}
			}
			if (!biggest || value > biggest.value) {
				biggest = { value, at: this.middleOf(id)! };
			}
		}
		if (positions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', positions.attribute());
			geometry.setAttribute('color', colors.attribute());
			this.group.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true })));
		}
		if (faces.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', faces.attribute());
			geometry.setAttribute('color', faceColors.attribute());
			this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				vertexColors: true, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false,
				polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
			})));
			const lines = new THREE.BufferGeometry();
			lines.setAttribute('position', outline.attribute());
			this.group.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color: this.colors.labelBackground, transparent: true, opacity: 0.35 })));
		}
		const joints = this.drawJointGlyphs(this.display.nodeUtilisation ?? {}, bands);
		this.labelsFollowSelection = true;
		const labels = this.utilisationLabels(utilisation, biggest);
		this.labelling = () => {
			labels();
			for (const joint of joints) {
				this.addLabel(formatUtilisation(joint.value), joint.at, this.colors[utilisationBand(joint.value)]);
			}
		};
	}

	/**
	 * A small box at each node with a check of its own (a beam-column joint), in its band's
	 * colour. Returns the failing ones, which are labelled too.
	 */
	private drawJointGlyphs(utilisation: { readonly [nodeId: number]: number }, bands: { readonly [band: string]: THREE.Color }): Extreme[] {
		const glyphs: { at: THREE.Vector3; color: THREE.Color }[] = [];
		const failing: Extreme[] = [];
		for (const [key, value] of Object.entries(utilisation)) {
			const id = Number(key);
			const at = this.visibleNodes && !this.visibleNodes.has(id) ? undefined : this.index.point(id);
			if (!at) {
				continue;
			}
			const band = utilisationBand(value);
			glyphs.push({ at, color: bands[band] });
			if (band === 'fail') {
				failing.push({ value, at });
			}
		}
		if (glyphs.length) {
			const size = this.index.size * 0.012;
			const box = new THREE.BoxGeometry(size, size, size);
			const mesh = new THREE.InstancedMesh(box, new THREE.MeshBasicMaterial({ toneMapped: false, depthTest: false, transparent: true }), glyphs.length);
			mesh.renderOrder = 1;
			const matrix = new THREE.Matrix4();
			glyphs.forEach((glyph, i) => {
				mesh.setMatrixAt(i, matrix.makeTranslation(glyph.at.x, glyph.at.y, glyph.at.z));
				mesh.setColorAt(i, glyph.color);
			});
			mesh.computeBoundingSphere();
			this.group.add(mesh);
		}
		// Many failing joints would bury the view in labels: only the worst few carry one.
		return failing.sort((a, b) => b.value - a.value).slice(0, 5);
	}

	/** Where the label of element `id` goes, or undefined when it is not drawn. */
	private middleOf(id: number): THREE.Vector3 | undefined {
		const element = this.index.elements.get(id);
		const points = element && (!this.visible || this.visible.has(id)) ? this.corners(element.nodes) : undefined;
		if (!points || points.length < 6) {
			return undefined;
		}
		return points.length === 6
			? new THREE.Vector3().fromArray(points, 0).lerp(new THREE.Vector3().fromArray(points, 3), 0.5)
			: ResultOverlay.centre(points);
	}

	/** The selected element's utilisation, or else the largest. */
	private utilisationLabels(utilisation: { readonly [elementId: number]: number }, biggest: Extreme | undefined): () => void {
		return () => {
			const id = this.selectedElement;
			const value = id === undefined ? undefined : utilisation[id];
			const at = id !== undefined && value !== undefined ? this.middleOf(id) : undefined;
			const label = at ? { value: value!, at } : biggest;
			if (label) {
				this.addLabel(formatUtilisation(label.value), label.at, this.colors[utilisationBand(label.value)]);
			}
		};
	}
}
