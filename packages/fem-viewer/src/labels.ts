/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';

/** Pixels per CSS pixel the labels are drawn at (sharp on high-density screens). */
const RATIO = 2;
const FONT_SIZE = 12 * RATIO;
const PADDING = 4 * RATIO;
const LABEL_HEIGHT = FONT_SIZE + PADDING * 2;
/** Empty pixels around every label in the atlas, so mipmaps do not bleed between labels. */
const GUTTER = 4;
const ATLAS_WIDTH = 2048;
const ATLAS_MAX_HEIGHT = 4096;

/**
 * Screen-sized label quads, as `THREE.Sprite`s with `sizeAttenuation: false` and
 * `center (0, 0)` draw them: the label's lower-left corner at its anchor, `size` in the sprite's
 * scale units (times `labelScale`, the orthographic camera's factor).
 */
const vertexShader = /* glsl */`
attribute vec3 anchor;
attribute vec2 size;
attribute vec4 rect;
uniform float labelScale;
varying vec2 vUv;
#include <common>
void main() {
	vec4 mvPosition = modelViewMatrix * vec4( anchor, 1.0 );
	vec2 scale = size * labelScale;
	if ( isPerspectiveMatrix( projectionMatrix ) ) scale *= - mvPosition.z;
	mvPosition.xy += ( position.xy + vec2( 0.5 ) ) * scale;
	gl_Position = projectionMatrix * mvPosition;
	vUv = rect.xy + uv * rect.zw;
}`;

const fragmentShader = /* glsl */`
uniform sampler2D map;
varying vec2 vUv;
void main() {
	gl_FragColor = texture2D( map, vUv );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`;

interface Label {
	readonly text: string;
	readonly position: THREE.Vector3;
	readonly color: string;
	readonly height: number;
}

/**
 * Text labels at points of the model, a constant size on screen: all of them drawn into one
 * texture atlas and drawn in one call (a sprite and a texture each would cost a draw call and an
 * upload per label), back to front as three.js orders sprites.
 */
export class LabelLayer {

	readonly group = new THREE.Group();
	private pending: Label[] = [];
	private readonly uniforms: { labelScale: THREE.IUniform<number> }[] = [];

	constructor(private readonly background: string) { }

	get count(): number {
		return this.pending.length;
	}

	/** Queues a label; {@link build} draws the queued ones. */
	add(text: string, position: THREE.Vector3, color: string, height = 0.04): void {
		this.pending.push({ text, position: position.clone(), color, height });
	}

	/** Draws the labels added (replacing those drawn before). */
	build(): void {
		this.clear();
		const labels = this.pending;
		if (!labels.length) {
			return;
		}
		const measure = document.createElement('canvas').getContext('2d');
		if (!measure) {
			return;
		}
		const font = `${FONT_SIZE}px system-ui, sans-serif`;
		measure.font = font;
		// Pack the labels in rows; a new atlas page when one is full.
		const widths = labels.map(l => Math.ceil(measure.measureText(l.text).width) + PADDING * 2);
		const pages: { labels: number[]; x: number[]; y: number[]; height: number }[] = [];
		let page = { labels: [] as number[], x: [] as number[], y: [] as number[], height: 0 };
		let x = 0;
		let y = 0;
		const rowHeight = LABEL_HEIGHT + GUTTER * 2;
		labels.forEach((_, i) => {
			const width = Math.min(widths[i], ATLAS_WIDTH - GUTTER * 2) + GUTTER * 2;
			if (x + width > ATLAS_WIDTH) {
				x = 0;
				y += rowHeight;
			}
			if (y + rowHeight > ATLAS_MAX_HEIGHT) {
				pages.push(page);
				page = { labels: [], x: [], y: [], height: 0 };
				x = 0;
				y = 0;
			}
			page.labels.push(i);
			page.x.push(x + GUTTER);
			page.y.push(y + GUTTER);
			page.height = y + rowHeight;
			x += width;
		});
		pages.push(page);

		for (const { labels: members, x: xs, y: ys, height } of pages) {
			const canvas = document.createElement('canvas');
			canvas.width = ATLAS_WIDTH;
			canvas.height = height;
			const context = canvas.getContext('2d')!;
			context.font = font;
			context.textBaseline = 'middle';
			const count = members.length;
			const anchors = new Float32Array(count * 3);
			const sizes = new Float32Array(count * 2);
			const rects = new Float32Array(count * 4);
			members.forEach((i, k) => {
				const label = labels[i];
				const width = widths[i];
				context.fillStyle = this.background;
				context.fillRect(xs[k], ys[k], width, LABEL_HEIGHT);
				context.save();
				context.beginPath();
				context.rect(xs[k], ys[k], width, LABEL_HEIGHT);
				context.clip();
				context.fillStyle = label.color;
				context.fillText(label.text, xs[k] + PADDING, ys[k] + LABEL_HEIGHT / 2);
				context.restore();
				label.position.toArray(anchors, k * 3);
				sizes[k * 2] = label.height * width / LABEL_HEIGHT;
				sizes[k * 2 + 1] = label.height;
				// The texture is flipped: v runs from the canvas's bottom.
				rects.set([xs[k] / ATLAS_WIDTH, 1 - (ys[k] + LABEL_HEIGHT) / height, width / ATLAS_WIDTH, LABEL_HEIGHT / height], k * 4);
			});
			const texture = new THREE.CanvasTexture(canvas);
			texture.colorSpace = THREE.SRGBColorSpace;
			const geometry = new THREE.InstancedBufferGeometry();
			const quad = new THREE.PlaneGeometry(1, 1);
			geometry.index = quad.index;
			geometry.setAttribute('position', quad.getAttribute('position'));
			geometry.setAttribute('uv', quad.getAttribute('uv'));
			geometry.setAttribute('anchor', new THREE.InstancedBufferAttribute(anchors, 3));
			geometry.setAttribute('size', new THREE.InstancedBufferAttribute(sizes, 2));
			geometry.setAttribute('rect', new THREE.InstancedBufferAttribute(rects, 4));
			geometry.instanceCount = count;
			const uniforms = { map: { value: texture }, labelScale: { value: 1 } };
			this.uniforms.push(uniforms);
			const mesh = new THREE.Mesh(geometry, new THREE.ShaderMaterial({
				uniforms, vertexShader, fragmentShader, transparent: true, depthTest: false,
			}));
			mesh.frustumCulled = false;
			mesh.renderOrder = 10;
			mesh.onBeforeRender = (_renderer, _scene, camera) => sortBackToFront(geometry, camera);
			this.group.add(mesh);
		}
	}

	/** See {@link ResultOverlay.setLabelScale}. */
	setScale(factor: number): void {
		for (const uniforms of this.uniforms) {
			uniforms.labelScale.value = factor;
		}
	}

	/** Removes the labels drawn and those queued. */
	reset(): void {
		this.pending = [];
		this.clear();
	}

	dispose(): void {
		this.reset();
	}

	private clear(): void {
		for (const child of [...this.group.children]) {
			this.group.remove(child);
			const mesh = child as THREE.Mesh<THREE.InstancedBufferGeometry, THREE.ShaderMaterial>;
			mesh.geometry.dispose();
			mesh.material.uniforms.map.value.dispose();
			mesh.material.dispose();
		}
		this.uniforms.length = 0;
	}
}

const projected = new THREE.Vector3();
const viewProjection = new THREE.Matrix4();

/**
 * Orders the label instances farthest first, as three.js orders transparent sprites, so where
 * labels overlap the nearer one is on top. Only rewrites the attributes when the order changes.
 */
function sortBackToFront(geometry: THREE.InstancedBufferGeometry, camera: THREE.Camera): void {
	const count = geometry.instanceCount;
	if (count < 2) {
		return;
	}
	const anchor = geometry.getAttribute('anchor') as THREE.InstancedBufferAttribute;
	const array = anchor.array as Float32Array;
	viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
	const depth = new Float32Array(count);
	let sorted = true;
	for (let i = 0; i < count; i++) {
		depth[i] = projected.fromArray(array, i * 3).applyMatrix4(viewProjection).z;
		if (i && depth[i] > depth[i - 1]) {
			sorted = false;
		}
	}
	if (sorted) {
		return;
	}
	const order = Array.from({ length: count }, (_, i) => i).sort((a, b) => depth[b] - depth[a] || a - b);
	for (const name of ['anchor', 'size', 'rect']) {
		const attribute = geometry.getAttribute(name) as THREE.InstancedBufferAttribute;
		const size = attribute.itemSize;
		const source = (attribute.array as Float32Array).slice();
		const target = attribute.array as Float32Array;
		order.forEach((from, to) => target.set(source.subarray(from * size, from * size + size), to * size));
		attribute.needsUpdate = true;
	}
}
