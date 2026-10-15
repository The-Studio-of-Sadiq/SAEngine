/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { FemModel, FemNode, FemResultDisplay, FemResultElement, FemResultQuantity, FemResultView, FORCE_COMPONENTS } from './model.js';

export interface ResultColors {
	readonly deformed: string;
	readonly positive: string;
	readonly negative: string;
	readonly reaction: string;
	readonly label: string;
	readonly labelBackground: string;
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
		} else if (display.show === 'reactions') {
			this.drawReactions();
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
		const factor = peak > 0 ? this.display.scale * DEFORMED_SHARE * this.size / peak : 0;
		const base: number[] = [];
		const delta: number[] = [];
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
