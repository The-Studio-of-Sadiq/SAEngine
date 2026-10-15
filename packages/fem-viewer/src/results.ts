/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { FemModel, FemNode, FemResultDisplay, FemResultElement, FemResultQuantity, FemResultView, FORCE_COMPONENTS, formatUtilisation, outerFaces, SHELL_COMPONENTS, SOLID_COMPONENTS, utilisationBand } from './model.js';

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

/**
 * The drawing of one analysis result over the model: deflected shape, a force diagram, or the
 * support reactions, with labels of the largest value and of the selected element.
 */
export class ResultOverlay {

	readonly group = new THREE.Group();
	private readonly modelElements: Map<number, FemModel['elements'][number]>;
	private animated: { readonly attribute: THREE.BufferAttribute; readonly base: Float32Array; readonly delta: Float32Array } | undefined;

	constructor(
		private readonly model: FemModel,
		private readonly results: FemResultView,
		private readonly display: FemResultDisplay,
		private readonly colors: ResultColors,
		/** Model size (bounding box diagonal, world units). */
		private readonly size: number,
		private readonly toWorld: (coords: readonly number[]) => THREE.Vector3,
		private readonly selectedElement: number | undefined,
	) {
		this.modelElements = new Map(model.elements.map(e => [e.id, e]));
		if (display.show === 'deformed') {
			this.drawDeformed();
		} else if (SHELL_COMPONENTS.includes(display.show)) {
			this.drawContour(SHELL_COMPONENTS.indexOf(display.show));
		} else if (display.show in SOLID_COMPONENTS) {
			this.drawStress(SOLID_COMPONENTS[display.show]);
		} else if (display.show === 'reactions') {
			this.drawReactions();
		} else if (display.show === 'utilisation') {
			this.drawUtilisation(display.utilisation ?? {});
		} else {
			this.drawDiagram(display.show);
		}
	}

	/** True when the shape oscillates (call {@link setPhase} every frame). */
	get isAnimated(): boolean {
		return !!this.animated;
	}

	/** Mode shape animation: the shape times `phase` (-1 … 1). */
	setPhase(phase: number): void {
		const animated = this.animated;
		if (!animated) {
			return;
		}
		const array = animated.attribute.array as Float32Array;
		for (let i = 0; i < array.length; i++) {
			array[i] = animated.base[i] + phase * animated.delta[i];
		}
		animated.attribute.needsUpdate = true;
	}

	dispose(): void {
		for (const child of [...this.group.children]) {
			this.group.remove(child);
			child.traverse(object => {
				const mesh = object as THREE.Mesh;
				mesh.geometry?.dispose();
				const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
				for (const material of materials) {
					(material as THREE.SpriteMaterial).map?.dispose();
					material.dispose();
				}
			});
		}
	}

	private nodes(): Map<number, FemNode> {
		return new Map(this.model.nodes.map(n => [n.id, n]));
	}

	/** World position of station `k` of `count` on the undeformed element. */
	private stationPoint(element: FemResultElement, k: number, count: number, nodes: Map<number, FemNode>): THREE.Vector3 | undefined {
		const source = this.modelElements.get(element.id);
		const a = source && nodes.get(source.nodes[0]);
		const b = source && nodes.get(source.nodes[1]);
		if (!a || !b) {
			return undefined;
		}
		const t = count > 1 ? k / (count - 1) : 0;
		return this.toWorld(a.coords).lerp(this.toWorld(b.coords), t);
	}

	private drawDeformed(): void {
		const nodes = this.nodes();
		let peak = 0;
		for (const element of this.results.elements) {
			for (const d of element.displacements) {
				peak = Math.max(peak, Math.hypot(d[0], d[1], d[2]));
			}
		}
		const moved = new Map(this.results.nodes.map(n => [n[0], n]));
		// Solids: the edges of their outer faces, moving with their nodes, as for shells.
		const solidFaces = outerFaces(this.results.solids ?? []).map(f => ({ nodes: f.nodes }));
		for (const shell of [...(this.results.shells ?? []), ...solidFaces]) {
			for (const id of shell.nodes) {
				const d = moved.get(id);
				peak = Math.max(peak, d ? Math.hypot(d[1], d[2], d[3]) : 0);
			}
		}
		const factor = peak > 0 ? this.display.scale * DEFORMED_SHARE * this.size / peak : 0;
		const base: number[] = [];
		const delta: number[] = [];
		// Shells and solids: their edges, each once, moving with their nodes.
		const edges = new Set<string>();
		for (const shell of [...(this.results.shells ?? []), ...solidFaces]) {
			shell.nodes.forEach((a, k) => {
				const b = shell.nodes[(k + 1) % shell.nodes.length];
				const key = a < b ? `${a}-${b}` : `${b}-${a}`;
				const na = nodes.get(a);
				const nb = nodes.get(b);
				if (edges.has(key) || !na || !nb) {
					return;
				}
				edges.add(key);
				for (const [node, id] of [[na, a], [nb, b]] as const) {
					const d = moved.get(id);
					base.push(...this.toWorld(node.coords).toArray());
					delta.push(...(d ? this.toWorld([d[1], d[2], d[3]]).multiplyScalar(factor) : new THREE.Vector3()).toArray());
				}
			});
		}
		let largest: { value: number; at: THREE.Vector3 } | undefined;
		for (const element of this.results.elements) {
			const count = element.displacements.length;
			const points: THREE.Vector3[] = [];
			const moves: THREE.Vector3[] = [];
			for (let k = 0; k < count; k++) {
				const point = this.stationPoint(element, k, count, nodes);
				if (!point) {
					break;
				}
				const d = element.displacements[k];
				const move = this.toWorld(d).multiplyScalar(factor);
				points.push(point);
				moves.push(move);
				const magnitude = Math.hypot(d[0], d[1], d[2]);
				if (!largest || magnitude > largest.value) {
					largest = { value: magnitude, at: point.clone().add(move) };
				}
			}
			for (let k = 0; k + 1 < points.length; k++) {
				base.push(...points[k].toArray(), ...points[k + 1].toArray());
				delta.push(...moves[k].toArray(), ...moves[k + 1].toArray());
			}
		}
		if (!base.length) {
			return;
		}
		const baseArray = new Float32Array(base);
		const deltaArray = new Float32Array(delta);
		const positions = new THREE.Float32BufferAttribute(baseArray.map((v, i) => v + deltaArray[i]), 3);
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', positions);
		const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: this.colors.deformed }));
		lines.frustumCulled = false;
		this.group.add(lines);
		if (this.results.kind === 'modal') {
			if (this.display.animate) {
				this.animated = { attribute: positions, base: baseArray, delta: deltaArray };
			}
			return; // mode shapes have no physical size
		}
		if (largest && largest.value > 0) {
			this.addLabel(this.display.format('length', largest.value), largest.at, this.colors.deformed);
		}
	}

	private drawDiagram(quantity: FemResultQuantity): void {
		const component = FORCE_COMPONENTS.indexOf(quantity);
		const [axis, sign] = DIAGRAM_SIDE[quantity];
		const nodes = this.nodes();
		let peak = 0;
		for (const element of this.results.elements) {
			for (const f of element.forces ?? []) {
				peak = Math.max(peak, Math.abs(f[component]));
			}
		}
		if (peak <= 0) {
			return;
		}
		const factor = this.display.scale * DIAGRAM_SHARE * this.size / peak;
		const positive = new THREE.Color(this.colors.positive);
		const negative = new THREE.Color(this.colors.negative);
		const fill: number[] = [];
		const fillColors: number[] = [];
		const outline: number[] = [];
		const outlineColors: number[] = [];
		const quantityKind = quantity === 'N' || quantity === 'Vy' || quantity === 'Vz' ? 'force' : 'moment';
		const triangle = (points: readonly THREE.Vector3[], color: THREE.Color) => {
			for (const p of points) {
				fill.push(p.x, p.y, p.z);
				fillColors.push(color.r, color.g, color.b);
			}
		};
		const segment = (a: THREE.Vector3, b: THREE.Vector3, color: THREE.Color) => {
			outline.push(a.x, a.y, a.z, b.x, b.y, b.z);
			outlineColors.push(color.r, color.g, color.b, color.r, color.g, color.b);
		};
		let largest: { value: number; at: THREE.Vector3 } | undefined;
		for (const element of this.results.elements) {
			const forces = element.forces;
			if (!forces?.length) {
				continue;
			}
			const side = this.toWorld(element[axis]).normalize().multiplyScalar(sign * factor);
			const count = forces.length;
			const values = forces.map(f => f[component]);
			const bases: THREE.Vector3[] = [];
			for (let k = 0; k < count; k++) {
				const point = this.stationPoint(element, k, count, nodes);
				if (!point) {
					break;
				}
				bases.push(point);
			}
			if (bases.length !== count) {
				continue;
			}
			const tip = (k: number) => bases[k].clone().addScaledVector(side, values[k]);
			for (let k = 0; k + 1 < count; k++) {
				const v0 = values[k];
				const v1 = values[k + 1];
				if (v0 * v1 >= 0) {
					const color = v0 + v1 >= 0 ? positive : negative;
					triangle([bases[k], bases[k + 1], tip(k + 1)], color);
					triangle([bases[k], tip(k + 1), tip(k)], color);
					segment(tip(k), tip(k + 1), color);
				} else {
					// The diagram crosses the axis inside the segment: split it there.
					const zero = bases[k].clone().lerp(bases[k + 1], v0 / (v0 - v1));
					triangle([bases[k], zero, tip(k)], v0 > 0 ? positive : negative);
					triangle([zero, bases[k + 1], tip(k + 1)], v1 > 0 ? positive : negative);
					segment(tip(k), zero, v0 > 0 ? positive : negative);
					segment(zero, tip(k + 1), v1 > 0 ? positive : negative);
				}
			}
			segment(bases[0], tip(0), values[0] >= 0 ? positive : negative);
			segment(bases[count - 1], tip(count - 1), values[count - 1] >= 0 ? positive : negative);

			let extreme = 0;
			for (let k = 0; k < count; k++) {
				if (Math.abs(values[k]) > Math.abs(values[extreme])) {
					extreme = k;
				}
				if (!largest || Math.abs(values[k]) > Math.abs(largest.value)) {
					largest = { value: values[k], at: tip(k) };
				}
			}
			if (element.id === this.selectedElement) {
				// The selected element: its end values and its extreme inside.
				for (const k of new Set([0, count - 1, extreme])) {
					this.addLabel(this.display.format(quantityKind, values[k]), tip(k), values[k] >= 0 ? this.colors.positive : this.colors.negative);
				}
			}
		}
		if (fill.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(fill, 3));
			geometry.setAttribute('color', new THREE.Float32BufferAttribute(fillColors, 3));
			this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				vertexColors: true, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false,
			})));
			const lines = new THREE.BufferGeometry();
			lines.setAttribute('position', new THREE.Float32BufferAttribute(outline, 3));
			lines.setAttribute('color', new THREE.Float32BufferAttribute(outlineColors, 3));
			this.group.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ vertexColors: true })));
		}
		if (largest && this.selectedElement === undefined) {
			this.addLabel(this.display.format(quantityKind, largest.value), largest.at, largest.value >= 0 ? this.colors.positive : this.colors.negative);
		}
	}

	/**
	 * Shell section force `component` as a contour: each shell coloured by its value at its
	 * centre on the scale from the lowest value (blue) to the highest (red).
	 */
	private drawContour(component: number): void {
		const nodes = this.nodes();
		const shells = (this.results.shells ?? []).filter(s => s.forces);
		if (!shells.length) {
			return;
		}
		const values = shells.map(s => s.forces![component]);
		const low = Math.min(...values);
		const high = Math.max(...values);
		const positions: number[] = [];
		const colors: number[] = [];
		const outline: number[] = [];
		let largest: { value: number; at: THREE.Vector3 } | undefined;
		shells.forEach((shell, index) => {
			const points = shell.nodes.map(id => nodes.get(id)).filter((n): n is FemNode => !!n).map(n => this.toWorld(n.coords));
			if (points.length !== shell.nodes.length) {
				return;
			}
			const color = contourColor(high > low ? (values[index] - low) / (high - low) : 0.5);
			for (let k = 1; k + 1 < points.length; k++) {
				for (const p of [points[0], points[k], points[k + 1]]) {
					positions.push(p.x, p.y, p.z);
					colors.push(...color);
				}
			}
			points.forEach((p, k) => outline.push(...p.toArray(), ...points[(k + 1) % points.length].toArray()));
			if (!largest || Math.abs(values[index]) > Math.abs(largest.value)) {
				const centre = points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).divideScalar(points.length);
				largest = { value: values[index], at: centre };
			}
		});
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
		geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
		this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
			vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
		})));
		const lines = new THREE.BufferGeometry();
		lines.setAttribute('position', new THREE.Float32BufferAttribute(outline, 3));
		this.group.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color: this.colors.labelBackground, transparent: true, opacity: 0.5 })));
		if (largest) {
			const kind = component < 3 ? 'forcePerLength' : component < 6 ? 'momentPerLength' : 'forcePerLength';
			this.addLabel(this.display.format(kind, largest.value), largest.at, this.colors.label);
		}
	}

	/**
	 * A solid stress (`index` in {@link FemResultSolid.stress}) as a contour on the solids' outer
	 * faces: each face coloured by its tetrahedron's (constant) value.
	 */
	private drawStress(index: number): void {
		const nodes = this.nodes();
		const solids = (this.results.solids ?? []).filter(s => s.stress);
		if (!solids.length) {
			return;
		}
		const values = solids.map(s => s.stress![index]);
		const low = Math.min(...values);
		const high = Math.max(...values);
		const positions: number[] = [];
		const colors: number[] = [];
		let largest: { value: number; at: THREE.Vector3 } | undefined;
		for (const face of outerFaces(solids)) {
			const points = face.nodes.map(id => nodes.get(id)).filter((n): n is FemNode => !!n).map(n => this.toWorld(n.coords));
			if (points.length !== 3) {
				continue;
			}
			const value = values[face.owner];
			const color = contourColor(high > low ? (value - low) / (high - low) : 0.5);
			for (const p of points) {
				positions.push(p.x, p.y, p.z);
				colors.push(...color);
			}
			if (!largest || Math.abs(value) > Math.abs(largest.value)) {
				largest = { value, at: points[0].clone().add(points[1]).add(points[2]).divideScalar(3) };
			}
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
		geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
		this.group.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
			vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
		})));
		if (largest) {
			this.addLabel(this.display.format('stress', largest.value), largest.at, this.colors.label);
		}
	}

	private drawReactions(): void {
		const nodes = this.nodes();
		let peak = 0;
		for (const r of this.results.reactions) {
			peak = Math.max(peak, Math.hypot(r[1], r[2], r[3]));
		}
		if (peak <= 0) {
			return;
		}
		const factor = this.display.scale * REACTION_SHARE * this.size / peak;
		const color = new THREE.Color(this.colors.reaction);
		for (const r of this.results.reactions) {
			const node = nodes.get(r[0]);
			const magnitude = Math.hypot(r[1], r[2], r[3]);
			if (!node || magnitude <= peak * 1e-6) {
				continue;
			}
			const at = this.toWorld(node.coords);
			const direction = this.toWorld([r[1], r[2], r[3]]).normalize();
			const length = Math.max(magnitude * factor, this.size * 0.01);
			// The support pushes on the structure: the arrow ends at the node.
			const arrow = new THREE.ArrowHelper(direction, at.clone().addScaledVector(direction, -length), length, color, length * 0.25, length * 0.12);
			this.group.add(arrow);
			this.addLabel(this.display.format('force', magnitude), at.clone().addScaledVector(direction, -length), this.colors.reaction);
		}
	}

	/**
	 * Frame elements coloured by their design utilisation band (pass, warn, fail), labelled with
	 * the selected element's value, or else the largest.
	 */
	private drawUtilisation(utilisation: { readonly [elementId: number]: number }): void {
		const nodes = this.nodes();
		const bands = { pass: new THREE.Color(this.colors.pass), warn: new THREE.Color(this.colors.warn), fail: new THREE.Color(this.colors.fail) };
		const positions: number[] = [];
		const colors: number[] = [];
		let largest: { value: number; at: THREE.Vector3 } | undefined;
		let selected: { value: number; at: THREE.Vector3 } | undefined;
		for (const [key, value] of Object.entries(utilisation)) {
			const id = Number(key);
			const element = this.modelElements.get(id);
			const a = element?.nodes.length === 2 ? nodes.get(element.nodes[0]) : undefined;
			const b = element?.nodes.length === 2 ? nodes.get(element.nodes[1]) : undefined;
			if (!a || !b) {
				continue;
			}
			const pa = this.toWorld(a.coords);
			const pb = this.toWorld(b.coords);
			const color = bands[utilisationBand(value)];
			positions.push(pa.x, pa.y, pa.z, pb.x, pb.y, pb.z);
			colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
			const middle = pa.clone().lerp(pb, 0.5);
			if (!largest || value > largest.value) {
				largest = { value, at: middle };
			}
			if (id === this.selectedElement) {
				selected = { value, at: middle };
			}
		}
		if (!positions.length) {
			return;
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
		geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
		this.group.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true })));
		const label = selected ?? largest;
		if (label) {
			this.addLabel(formatUtilisation(label.value), label.at, this.colors[utilisationBand(label.value)]);
		}
	}

	/** A text label at `position`, a constant size on screen. */
	private addLabel(text: string, position: THREE.Vector3, color: string): void {
		const ratio = 2;
		const fontSize = 12 * ratio;
		const canvas = document.createElement('canvas');
		const context = canvas.getContext('2d');
		if (!context) {
			return;
		}
		const font = `${fontSize}px system-ui, sans-serif`;
		context.font = font;
		const padding = 4 * ratio;
		canvas.width = Math.ceil(context.measureText(text).width) + padding * 2;
		canvas.height = fontSize + padding * 2;
		context.font = font;
		context.fillStyle = this.colors.labelBackground;
		context.fillRect(0, 0, canvas.width, canvas.height);
		context.fillStyle = color;
		context.textBaseline = 'middle';
		context.fillText(text, padding, canvas.height / 2);
		const texture = new THREE.CanvasTexture(canvas);
		texture.colorSpace = THREE.SRGBColorSpace;
		const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, sizeAttenuation: false, depthTest: false, transparent: true }));
		const height = 0.04;
		sprite.scale.set(height * canvas.width / canvas.height, height, 1);
		sprite.center.set(0, 0);
		sprite.position.copy(position);
		sprite.renderOrder = 10;
		this.group.add(sprite);
	}
}
