/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { FemElement, FemModel } from './model.js';

/** Model space (Z up in 3D, Y up in 2D) to three.js world space (Y up). */
export function toWorld(ndm: number, coords: readonly number[], target = new THREE.Vector3()): THREE.Vector3 {
	const x = coords[0] ?? 0;
	const y = coords[1] ?? 0;
	return ndm < 3 ? target.set(x, y, 0) : target.set(x, coords[2] ?? 0, -y);
}

/**
 * A model's nodes in world space and its elements, by id: worked out once per model and shared
 * by the model's drawing and the results', so a 50,000-element model is not walked again for
 * every result shown.
 */
export class ModelIndex {

	/** World x, y, z of every node, in the order of the model's nodes. */
	readonly world: Float64Array;
	readonly elements: ReadonlyMap<number, FemElement>;
	/** Bounding box diagonal (world units, at least 1). */
	readonly size: number;
	private readonly nodeIndex = new Map<number, number>();

	constructor(readonly model: FemModel) {
		const nodes = model.nodes;
		this.world = new Float64Array(nodes.length * 3);
		const point = new THREE.Vector3();
		const box = new THREE.Box3();
		nodes.forEach((node, i) => {
			this.nodeIndex.set(node.id, i);
			toWorld(model.ndm, node.coords, point).toArray(this.world, i * 3);
			box.expandByPoint(point);
		});
		this.elements = new Map(model.elements.map(e => [e.id, e]));
		this.size = box.isEmpty() ? 1 : Math.max(box.getSize(point).length(), 1);
	}

	/** Offset of node `id` in {@link world}, or -1 when the model has no such node. */
	offset(id: number): number {
		const index = this.nodeIndex.get(id);
		return index === undefined ? -1 : index * 3;
	}

	has(id: number): boolean {
		return this.nodeIndex.has(id);
	}

	/** World position of node `id` (into `target`), or undefined when there is no such node. */
	point(id: number, target = new THREE.Vector3()): THREE.Vector3 | undefined {
		const o = this.offset(id);
		return o < 0 ? undefined : target.fromArray(this.world, o);
	}

	/** World vector of a model-space vector (a displacement, a force, a local axis). */
	vector(coords: readonly number[], target = new THREE.Vector3()): THREE.Vector3 {
		return toWorld(this.model.ndm, coords, target);
	}
}

/** A growing list of floats (positions, colours) that becomes a buffer attribute without copies of plain arrays. */
export class Floats {

	private array: Float32Array;
	length = 0;

	constructor(capacity = 1024) {
		this.array = new Float32Array(Math.max(capacity, 16));
	}

	push3(x: number, y: number, z: number): void {
		if (this.length + 3 > this.array.length) {
			this.grow(this.length + 3);
		}
		const a = this.array;
		a[this.length] = x;
		a[this.length + 1] = y;
		a[this.length + 2] = z;
		this.length += 3;
	}

	/** Appends `count` floats of `source` from `offset`. */
	pushFrom(source: ArrayLike<number>, offset: number, count: number): void {
		if (this.length + count > this.array.length) {
			this.grow(this.length + count);
		}
		for (let i = 0; i < count; i++) {
			this.array[this.length + i] = source[offset + i];
		}
		this.length += count;
	}

	pushVector(v: THREE.Vector3): void {
		this.push3(v.x, v.y, v.z);
	}

	/** The floats pushed, as a tight array. */
	toArray(): Float32Array {
		return this.array.slice(0, this.length);
	}

	attribute(itemSize = 3): THREE.Float32BufferAttribute {
		return new THREE.Float32BufferAttribute(this.toArray(), itemSize);
	}

	private grow(needed: number): void {
		const next = new Float32Array(Math.max(needed, this.array.length * 2));
		next.set(this.array.subarray(0, this.length));
		this.array = next;
	}
}

/** Disposes the geometries, materials and textures of `object` and everything under it. */
export function disposeObject(object: THREE.Object3D): void {
	object.traverse(child => {
		if (child instanceof THREE.InstancedMesh) {
			child.dispose(); // its instance matrices
		}
		const mesh = child as THREE.Mesh;
		mesh.geometry?.dispose();
		const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
		for (const material of materials) {
			(material as THREE.SpriteMaterial).map?.dispose();
			material.dispose();
		}
	});
}
