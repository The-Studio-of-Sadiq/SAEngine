/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

/*
 * Alpha 9 L11: rendering of the BIM view: lighting presets (a hemisphere sky, a sun with
 * shadow maps, an image-based environment for the PBR materials, tone mapping), a walk mode,
 * high-quality stills (rasterised and supersampled: no path tracer is a dependency) and the
 * frame that places project coordinates (mm, z up) in the scene of the IFC model (y up).
 */

/** The look of the view. */
export type BuildingRenderPreset = 'standard' | 'daylight' | 'overcast' | 'dusk' | 'clay';

interface PresetSettings {
	/** Tone mapping exposure. */
	readonly exposure: number;
	readonly hemisphere: number;
	readonly sky: string;
	readonly ground: string;
	/** Sun intensity (0: no sun); the sun's direction is the study's or a default one. */
	readonly sun: number;
	readonly sunColor: string;
	/** Image-based lighting of a neutral room (PBR materials reflect it). */
	readonly environment: number;
	readonly shadows: boolean;
	/** Background colour; undefined keeps the theme's. */
	readonly background?: string;
	/** Every layer drawn in one matte colour (a clay model). */
	readonly clay?: string;
}

export const RENDER_PRESETS: Readonly<Record<BuildingRenderPreset, PresetSettings>> = {
	standard: { exposure: 1, hemisphere: 0, sky: '#ffffff', ground: '#444444', sun: 0, sunColor: '#ffffff', environment: 0, shadows: false },
	daylight: { exposure: 1.05, hemisphere: 0.9, sky: '#cfe6ff', ground: '#8c7d6a', sun: 2.6, sunColor: '#fff4e0', environment: 0.6, shadows: true, background: '#bcd8f2' },
	overcast: { exposure: 1.1, hemisphere: 1.6, sky: '#e8edf2', ground: '#9a958c', sun: 0.4, sunColor: '#f2f2f2', environment: 0.9, shadows: false, background: '#d6dbe0' },
	dusk: { exposure: 0.85, hemisphere: 0.45, sky: '#ffb889', ground: '#3b3346', sun: 1.6, sunColor: '#ff9a5c', environment: 0.35, shadows: true, background: '#2f2a3d' },
	clay: { exposure: 1, hemisphere: 1.1, sky: '#ffffff', ground: '#b8b2a7', sun: 1.8, sunColor: '#ffffff', environment: 0.5, shadows: true, background: '#f2f1ee', clay: '#dcd8cf' },
};

/** The default sun, from the south-east and 40° up, in project coordinates (x east, y north, z up). */
const DEFAULT_SUN: readonly [number, number, number] = [0.54, -0.54, 0.64];

/**
 * Project coordinates (mm, z up) to the scene (y up) of a model loaded from SAEngine's IFC: the
 * building's extents in the project and in the scene give the scale (mm to the model's unit)
 * and the offset (the IFC loader may move the model to the origin).
 */
export class ProjectFrame {
	private scale = 0.001;
	private readonly offset = new THREE.Vector3();
	private known = false;

	/** `projectMin`/`projectMax`: the building's extents [mm]; `sceneBox`: the model's box. */
	set(projectMin: readonly number[], projectMax: readonly number[], sceneBox: THREE.Box3): void {
		const dx = projectMax[0] - projectMin[0];
		const size = sceneBox.getSize(new THREE.Vector3());
		this.scale = dx > 0 && size.x > 0 ? size.x / dx : 0.001;
		// project (x, y, z) -> scene (x, z, -y): the scene's min corner is (minX, minZ, -maxY).
		this.offset.set(
			sceneBox.min.x - projectMin[0] * this.scale,
			sceneBox.min.y - projectMin[2] * this.scale,
			sceneBox.min.z + projectMax[1] * this.scale,
		);
		this.known = true;
	}

	get ready(): boolean {
		return this.known;
	}

	toScene(x: number, y: number, z: number, out = new THREE.Vector3()): THREE.Vector3 {
		return out.set(x * this.scale + this.offset.x, z * this.scale + this.offset.y, -y * this.scale + this.offset.z);
	}

	/** A direction (unit, project axes) in the scene's axes. */
	static direction(d: readonly number[]): THREE.Vector3 {
		return new THREE.Vector3(d[0], d[2], -d[1]).normalize();
	}
}

/** The lights, shadows and environment of a preset, added to the scene and removed again. */
export class SceneLighting {

	private readonly hemisphere = new THREE.HemisphereLight('#ffffff', '#444444', 0);
	private readonly sun = new THREE.DirectionalLight('#ffffff', 0);
	private envTarget: THREE.WebGLRenderTarget | undefined;
	private preset: BuildingRenderPreset = 'standard';
	private sunDirection = ProjectFrame.direction(DEFAULT_SUN);
	private readonly savedBackground: THREE.Color | THREE.Texture | null;

	constructor(private readonly scene: THREE.Scene, private readonly renderer: THREE.WebGLRenderer) {
		this.savedBackground = scene.background as THREE.Color | THREE.Texture | null;
		this.sun.castShadow = true;
		this.sun.shadow.mapSize.set(4096, 4096);
		this.sun.shadow.bias = -0.0005;
		this.sun.shadow.normalBias = 0.02;
		scene.add(this.hemisphere, this.sun, this.sun.target);
	}

	get current(): BuildingRenderPreset {
		return this.preset;
	}

	get clayColor(): string | undefined {
		return RENDER_PRESETS[this.preset].clay;
	}

	/** Applies `preset`; `bounds` (the model's box) sizes the sun's shadow camera. */
	apply(preset: BuildingRenderPreset, bounds: THREE.Box3 | undefined): void {
		this.preset = preset;
		const p = RENDER_PRESETS[preset];
		const r = this.renderer;
		r.toneMapping = preset === 'standard' ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
		r.toneMappingExposure = p.exposure;
		r.shadowMap.enabled = p.shadows;
		r.shadowMap.type = THREE.PCFSoftShadowMap;
		this.hemisphere.color.set(p.sky);
		this.hemisphere.groundColor.set(p.ground);
		this.hemisphere.intensity = p.hemisphere;
		this.sun.color.set(p.sunColor);
		this.sun.intensity = p.sun;
		this.sun.castShadow = p.shadows;
		if (p.environment > 0) {
			if (!this.envTarget) {
				const pmrem = new THREE.PMREMGenerator(r);
				this.envTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
				pmrem.dispose();
			}
			this.scene.environment = this.envTarget.texture;
			this.scene.environmentIntensity = p.environment;
		} else {
			this.scene.environment = null;
		}
		this.scene.background = p.background ? new THREE.Color(p.background) : this.savedBackground;
		this.place(bounds);
		this.shadows(p.shadows);
	}

	/** The sun towards `direction` (unit, project axes: x east, y north, z up), or the default. */
	setSun(direction: readonly number[] | undefined, bounds: THREE.Box3 | undefined): void {
		this.sunDirection = ProjectFrame.direction(direction ?? DEFAULT_SUN);
		this.place(bounds);
	}

	/** Every mesh of the scene casts and receives shadows while the preset has them. */
	shadows(on: boolean): void {
		this.scene.traverse(object => {
			if ((object as THREE.Mesh).isMesh) {
				object.castShadow = on;
				object.receiveShadow = on;
			}
		});
	}

	private place(bounds: THREE.Box3 | undefined): void {
		const box = bounds && !bounds.isEmpty() ? bounds : new THREE.Box3(new THREE.Vector3(-10, 0, -10), new THREE.Vector3(10, 10, 10));
		const sphere = box.getBoundingSphere(new THREE.Sphere());
		const radius = Math.max(sphere.radius, 1) * 1.5;
		this.sun.target.position.copy(sphere.center);
		this.sun.position.copy(sphere.center).addScaledVector(this.sunDirection, radius * 2);
		const camera = this.sun.shadow.camera;
		camera.left = -radius;
		camera.right = radius;
		camera.top = radius;
		camera.bottom = -radius;
		camera.near = 0.1;
		camera.far = radius * 4;
		camera.updateProjectionMatrix();
		this.sun.target.updateMatrixWorld();
	}

	dispose(): void {
		this.scene.remove(this.hemisphere, this.sun, this.sun.target);
		this.envTarget?.dispose();
		this.scene.environment = null;
		this.scene.background = this.savedBackground;
	}
}

/**
 * A still of the view at `scale` times the canvas's size, rendered `supersample` times larger
 * again and filtered down (rasterised supersampling): a PNG (or JPEG) blob. Rendered on the
 * view's own canvas, resized for the moment, so tone mapping and the output colour space apply
 * as on screen; the canvas is drawn into the still in the same task, before it is shown.
 */
export async function renderStill(
	renderer: THREE.WebGLRenderer,
	scene: THREE.Scene,
	camera: THREE.Camera,
	options: { readonly scale?: number; readonly supersample?: number; readonly type?: string } = {},
): Promise<Blob> {
	const canvas = renderer.domElement;
	const scale = Math.max(1, options.scale ?? 2);
	const supersample = Math.max(1, Math.min(4, options.supersample ?? 2));
	const width = Math.max(1, Math.round(canvas.clientWidth * scale));
	const height = Math.max(1, Math.round(canvas.clientHeight * scale));
	const max = Math.min(renderer.capabilities.maxTextureSize, 8192);
	const factor = Math.max(1, Math.min(supersample, max / Math.max(width, height)));
	const size = renderer.getSize(new THREE.Vector2());
	const ratio = renderer.getPixelRatio();
	const out = document.createElement('canvas');
	out.width = width;
	out.height = height;
	const context = out.getContext('2d')!;
	context.imageSmoothingEnabled = true;
	context.imageSmoothingQuality = 'high';
	try {
		renderer.setPixelRatio(1);
		renderer.setSize(Math.round(width * factor), Math.round(height * factor), false);
		renderer.render(scene, camera);
		context.drawImage(canvas, 0, 0, width, height);
	} finally {
		renderer.setPixelRatio(ratio);
		renderer.setSize(size.x, size.y, false);
		renderer.render(scene, camera);
	}
	return new Promise<Blob>((resolve, reject) => out.toBlob(blob => blob ? resolve(blob) : reject(new Error('the still could not be encoded')), options.type ?? 'image/png', 0.95));
}

/** What the walk mode moves: the subset of camera-controls it calls. */
export interface WalkableControls {
	forward(distance: number, enableTransition?: boolean): unknown;
	truck(x: number, y: number, enableTransition?: boolean): unknown;
	elevate(height: number, enableTransition?: boolean): unknown;
	rotate(azimuth: number, polar: number, enableTransition?: boolean): unknown;
}

/**
 * A walk through the building: W/S forward and back, A/D sideways, Q/E down and up, the arrows
 * turn; Shift walks faster. `speed` is per key press in the scene's units (m).
 */
export class WalkKeys {

	private readonly onKey = (e: KeyboardEvent) => this.key(e);

	constructor(private readonly target: HTMLElement, private readonly controls: WalkableControls, private readonly speed = 0.5) {
		target.tabIndex = target.tabIndex < 0 ? 0 : target.tabIndex;
		target.addEventListener('keydown', this.onKey);
	}

	private key(e: KeyboardEvent): void {
		const step = this.speed * (e.shiftKey ? 3 : 1);
		const turn = Math.PI / 36;
		switch (e.key.toLowerCase()) {
			case 'w': void this.controls.forward(step, true); break;
			case 's': void this.controls.forward(-step, true); break;
			case 'a': void this.controls.truck(-step, 0, true); break;
			case 'd': void this.controls.truck(step, 0, true); break;
			case 'q': void this.controls.elevate(-step, true); break;
			case 'e': void this.controls.elevate(step, true); break;
			case 'arrowleft': void this.controls.rotate(turn, 0, true); break;
			case 'arrowright': void this.controls.rotate(-turn, 0, true); break;
			case 'arrowup': void this.controls.rotate(0, -turn, true); break;
			case 'arrowdown': void this.controls.rotate(0, turn, true); break;
			default: return;
		}
		e.preventDefault();
		e.stopPropagation();
	}

	dispose(): void {
		this.target.removeEventListener('keydown', this.onKey);
	}
}

/** A terrain surface (TIN) from project points (mm, flat x, y, z) and triangles (flat indices). */
export function terrainMesh(points: readonly number[], triangles: readonly number[], frame: ProjectFrame, color: string): THREE.Mesh {
	const positions = new Float32Array(points.length);
	const v = new THREE.Vector3();
	for (let i = 0; i + 2 < points.length; i += 3) {
		frame.toScene(points[i], points[i + 1], points[i + 2], v);
		positions[i] = v.x;
		positions[i + 1] = v.y;
		positions[i + 2] = v.z;
	}
	const geometry = new THREE.BufferGeometry();
	geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
	geometry.setIndex([...triangles]);
	geometry.computeVertexNormals();
	const material = new THREE.MeshStandardMaterial({ color, roughness: 0.95, metalness: 0, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
	const mesh = new THREE.Mesh(geometry, material);
	mesh.name = 'saengine-terrain';
	mesh.receiveShadow = true;
	return mesh;
}

/** The state of an element on a day of the programme (4D). */
export type ConstructionState = 'notStarted' | 'building' | 'built';

/** An element's state on `day` (ISO date) from its activity's dates. */
export function constructionState(dates: { readonly start: string; readonly finish: string } | undefined, day: string): ConstructionState {
	if (!dates) {
		return 'built';
	}
	if (day < dates.start) {
		return 'notStarted';
	}
	return day > dates.finish ? 'built' : 'building';
}
