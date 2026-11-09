/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import * as FRAGS from '@thatopen/fragments';
import { usableTheme } from './theme.js';
import { constructionState, ProjectFrame, renderStill, SceneLighting, terrainMesh, WalkKeys, type BuildingRenderPreset } from './render.js';

export type { BuildingRenderPreset } from './render.js';

/*
 * The 3D view of the building model: an IFC file (written by SAEngine's Python side with
 * IfcOpenShell) loaded with That Open's IFC loader, so the view shows exactly what is exported.
 */

export interface BuildingViewerTheme {
	readonly background: string;
	readonly grid: string;
	readonly selection: string;
	/** Colours by IFC class, matching the floor plan's layers. */
	readonly column: string;
	readonly beam: string;
	readonly wall: string;
	readonly slab: string;
	readonly footing: string;
	readonly stair: string;
	readonly member: string;
	/** Equipment, tanks, pipes, ducts and cable runs of 7 MEP. */
	readonly mep: string;
	/** The architecture's walls, doors, windows and finishes (ids `arch:...`): not structure. */
	readonly architecture: string;
	/** Rooms (IfcSpace), drawn see-through. */
	readonly room: string;
	/** Doors and windows of the architecture's layer: wood, and see-through glass. */
	readonly door: string;
	readonly window: string;
	/** The reinforcing bars of the cages (IfcReinforcingBar), when the IFC carries them. */
	readonly rebar: string;
}

/** The groups of elements the view can show or hide, each with its own colour. */
export type BuildingLayer = 'column' | 'beam' | 'wall' | 'slab' | 'footing' | 'stair' | 'member' | 'mep' | 'architecture' | 'room' | 'rebar';

/** Ids (in `load`'s map) of the architecture's elements: their own layer, whatever their IFC class. */
export const ARCHITECTURE_PREFIX = 'arch:';

/** Camera directions of the view presets. */
export type BuildingViewPreset = 'iso' | 'top' | 'front' | 'side';

export interface BuildingViewerOptions {
	/** Folder URL (with trailing slash) holding `fragments-worker.mjs` and `web-ifc/`. */
	readonly assetBaseUrl: string;
	readonly theme?: Partial<BuildingViewerTheme>;
	/** An element was clicked (its SAEngine id), or empty space (`undefined`). */
	readonly onSelectionChanged?: (elementId: string | undefined) => void;
}

export interface BuildingViewer {
	/**
	 * Shows the IFC `ifc`, replacing the building shown before. `ids` maps SAEngine element ids
	 * to IFC GlobalIds; ids starting with {@link ARCHITECTURE_PREFIX} are the architecture's. The
	 * camera keeps its place after the first load. `layers` puts elements (SAEngine ids) in a
	 * layer other than their IFC class says: a raft, an IfcSlab, among the foundations.
	 */
	load(ifc: Uint8Array, ids: Readonly<Record<string, string>>, layers?: Readonly<Record<string, BuildingLayer>>): Promise<void>;
	setSelection(elementId: string | undefined): Promise<void>;
	setTheme(theme: Partial<BuildingViewerTheme>): Promise<void>;
	fit(): Promise<void>;
	/** Looks at the whole building from a preset direction. */
	setView(preset: BuildingViewPreset): Promise<void>;
	/** The layers the loaded building has elements in: how many, and their colour (for a legend). */
	layers(): Promise<readonly { readonly layer: BuildingLayer; readonly count: number; readonly color: string }[]>;
	/** Shows or hides a layer. */
	setLayerVisible(layer: BuildingLayer, visible: boolean): Promise<void>;
	/**
	 * Shows only these elements (SAEngine ids) of the elements the view knows, e.g. one story;
	 * `undefined` shows them all. Hidden layers stay hidden.
	 */
	setVisibleElements(elementIds: readonly string[] | undefined): Promise<void>;
	/** Call when the container changes size without the browser reporting it. */
	layout(): void;
	dispose(): void;

	// Alpha 9 L11: rendering, 4D, phases, terrain and the sun.
	/** The look of the view: lighting, shadows, environment, a clay model (see render.ts). */
	setRenderPreset(preset: BuildingRenderPreset): Promise<void>;
	/** The sun towards `direction` (unit, project axes: x east, y north, z up); undefined: the default. */
	setSun(direction: readonly number[] | undefined): void;
	/** Walk through the building (first person: W/A/S/D, Q/E, the arrows) or orbit again. */
	setWalkMode(on: boolean): Promise<void>;
	/** A still of the view, `scale` times the canvas size, supersampled: a PNG blob. */
	exportStill(options?: { readonly scale?: number; readonly supersample?: number }): Promise<Blob>;
	/** The building's extents in the project [mm]: places project coordinates in the scene (terrain, sun). */
	setProjectFrame(min: readonly number[], max: readonly number[]): void;
	/** The site's terrain (TIN: points mm flat x, y, z; triangles flat), or none. */
	setTerrain(points: readonly number[] | undefined, triangles?: readonly number[]): void;
	/**
	 * 4D: each element's activity dates (ISO) and the day shown: elements not started are hidden,
	 * those under construction drawn see-through, the others as built. `day` undefined: all built.
	 */
	setConstruction(dates: Readonly<Record<string, { readonly start: string; readonly finish: string }>> | undefined, day: string | undefined): Promise<void>;
	/**
	 * Phases: each element's state in the phase shown (existing, new, demolished, temporary);
	 * elements not listed are hidden. Undefined: no phase filter.
	 */
	setPhaseStates(states: Readonly<Record<string, 'existing' | 'new' | 'demolished' | 'temporary'>> | undefined): Promise<void>;
}

/** Colours of the 4D and phase states (see-through where they are not solid). */
const STATE_STYLE = {
	building: { color: '#ff9f40', opacity: 0.45 },
	existing: { color: '#a0a0a0', opacity: 1 },
	demolished: { color: '#e05050', opacity: 0.4 },
	temporary: { color: '#d8b020', opacity: 0.6 },
} as const;

const defaultTheme: BuildingViewerTheme = {
	background: '#1e1e1e',
	grid: '#3c3c3c',
	selection: '#ffcc00',
	column: '#4fc1ff',
	beam: '#89d185',
	wall: '#6b8cff',
	slab: '#c586c0',
	footing: '#d7954b',
	stair: '#d4d4d4',
	member: '#f14c4c',
	mep: '#2bb3a3',
	architecture: '#d8c3a0',
	room: '#e2b84d',
	door: '#9a6a3a',
	window: '#7cc4e4',
	rebar: '#ff7043',
};

/** Rooms are drawn see-through, so the walls and structure show inside them. */
const ROOM_OPACITY = 0.18;
/** Windows are glass: the room behind shows through. */
const WINDOW_OPACITY = 0.45;

const CATEGORIES: readonly [BuildingLayer, RegExp][] = [
	['column', /^IFCCOLUMN$/],
	['beam', /^IFCBEAM$/],
	// Walls, not their types (IfcWallType: the architecture's walls have types).
	['wall', /^IFCWALL(STANDARDCASE|ELEMENTEDCASE)?$/],
	['slab', /^IFCSLAB$/],
	['footing', /^IFC(FOOTING|PILE)$/],
	['stair', /^IFCSTAIR/],
	['member', /^IFCMEMBER$/],
	// The IFC4 classes 7 MEP writes (see saengine.library.ifc): plant, tanks, segments, lifts.
	['mep', /^IFC(TANK|PUMP|CHILLER|COOLINGTOWER|UNITARYEQUIPMENT|FAN|TRANSFORMER|ELECTRIC\w*|SOLARDEVICE|PIPESEGMENT|DUCTSEGMENT|CABLESEGMENT|CABLECARRIERSEGMENT|TRANSPORTELEMENT)$/],
	['room', /^IFCSPACE$/],
	// The architecture's walls, doors, windows and coverings, by their ids (see ARCHITECTURE_PREFIX).
	['architecture', /^IFC(DOOR|WINDOW|COVERING)$/],
	// The reinforcement cages (saengine.library.ifc_rebar): hide the concrete to see them.
	['rebar', /^IFCREINFORCINGBAR$/],
];

/** Directions from the target to the camera of the view presets (y is up). */
const PRESETS: Readonly<Record<BuildingViewPreset, THREE.Vector3>> = {
	iso: new THREE.Vector3(1, 0.8, 1.2),
	top: new THREE.Vector3(0, 1, 0.0001), // a hair off vertical keeps the orbit's up axis defined
	front: new THREE.Vector3(0, 0, 1),
	side: new THREE.Vector3(1, 0, 0),
};

/** Wheel zoom per notch: gentler than camera-controls' default, so a building does not jump past. */
const DOLLY_SPEED = 0.35;

class BuildingViewerImpl implements BuildingViewer {

	private readonly components = new OBC.Components();
	private readonly world: OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;
	private readonly renderer: OBC.SimpleRenderer;
	private readonly camera: OBC.OrthoPerspectiveCamera;
	private readonly grid: OBC.SimpleGrid;
	private readonly fragments: OBC.FragmentsManager;
	private readonly ready: Promise<void>;

	private theme: BuildingViewerTheme;
	private model: FRAGS.FragmentsModel | undefined;
	private loads = 0;
	/** GlobalId <-> SAEngine id, and local item id <-> SAEngine id of the loaded model. */
	private localIds = new Map<string, number>();
	private elementIds = new Map<number, string>();
	/** The layer of the items whose IFC class does not give it (see `load`). */
	private layerOverrides = new Map<number, BuildingLayer>();
	private selection: string | undefined;
	/** The element drawn as selected now (its colour is restored when deselected). */
	private highlighted: number | undefined;
	/** Class colour of every coloured item. */
	private readonly itemColors = new Map<number, string>();
	/** Opacity of the see-through items (rooms, windows); the others are opaque. */
	private readonly itemOpacity = new Map<number, number>();
	private fitted = false;
	/** Local ids of each layer's items in the loaded model. */
	private layerItems = new Map<BuildingLayer, number[]>();
	private readonly hiddenLayers = new Set<BuildingLayer>();
	private visibleElements: ReadonlySet<string> | undefined;

	// Alpha 9 L11 (see render.ts).
	private lighting: SceneLighting | undefined;
	private walk: WalkKeys | undefined;
	private readonly frame = new ProjectFrame();
	private projectExtents: { readonly min: readonly number[]; readonly max: readonly number[] } | undefined;
	private terrain: THREE.Mesh | undefined;
	private terrainData: { readonly points: readonly number[]; readonly triangles: readonly number[] } | undefined;
	private constructionDates: Readonly<Record<string, { readonly start: string; readonly finish: string }>> | undefined;
	private constructionDay: string | undefined;
	private phaseStates: Readonly<Record<string, 'existing' | 'new' | 'demolished' | 'temporary'>> | undefined;

	private pointerDown: { x: number; y: number } | undefined;
	private readonly onPointerDown = (e: PointerEvent) => { this.pointerDown = { x: e.clientX, y: e.clientY }; };
	private readonly onPointerUp = (e: PointerEvent) => void this.handleClick(e);

	constructor(container: HTMLElement, private readonly options: BuildingViewerOptions) {
		this.theme = { ...defaultTheme, ...usableTheme(options.theme) };

		const worlds = this.components.get(OBC.Worlds);
		this.world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();
		this.world.scene = new OBC.SimpleScene(this.components);
		this.world.scene.setup();
		this.renderer = new OBC.SimpleRenderer(this.components, container, { antialias: true });
		this.renderer.showLogo = false;
		this.world.renderer = this.renderer;
		this.camera = new OBC.OrthoPerspectiveCamera(this.components);
		this.world.camera = this.camera;
		this.components.init();
		this.grid = this.components.get(OBC.Grids).create(this.world);

		this.fragments = this.components.get(OBC.FragmentsManager);
		this.fragments.init(`${options.assetBaseUrl}fragments-worker.mjs`);
		// Fragments stream their geometry by view: refresh it when the camera settles.
		this.camera.controls.dollySpeed = DOLLY_SPEED;
		this.camera.controls.dollyToCursor = true;
		this.camera.controls.addEventListener('rest', () => void this.fragments.core.update(true));
		this.fragments.list.onItemSet.add(({ value: model }) => {
			model.useCamera(this.camera.three);
			this.world.scene.three.add(model.object);
			void this.fragments.core.update(true);
		});

		// The IFC importer's web-ifc wasm ships with the viewer (no download from a CDN).
		this.ready = this.components.get(OBC.IfcLoader).setup({
			autoSetWasm: false,
			wasm: { path: `${options.assetBaseUrl}web-ifc/`, absolute: true },
		});

		this.applyTheme();
		const canvas = this.renderer.three.domElement;
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);
	}

	async load(ifc: Uint8Array, ids: Readonly<Record<string, string>>, layers?: Readonly<Record<string, BuildingLayer>>): Promise<void> {
		await this.ready;
		const load = ++this.loads;
		const model = await this.components.get(OBC.IfcLoader).load(ifc, false, `building-${load}`);
		if (load !== this.loads) {
			await this.fragments.core.disposeModel(model.modelId); // a newer load superseded it
			return;
		}
		const previous = this.model;
		this.model = model;
		if (previous) {
			await this.fragments.core.disposeModel(previous.modelId);
		}

		const entries = Object.entries(ids);
		const locals = await model.getLocalIdsByGuids(entries.map(([, guid]) => guid));
		this.localIds = new Map();
		this.elementIds = new Map();
		entries.forEach(([id], i) => {
			const local = locals[i];
			if (local !== null && local !== undefined) {
				this.localIds.set(id, local);
				this.elementIds.set(local, id);
			}
		});
		this.layerOverrides = new Map();
		for (const [id, layer] of Object.entries(layers ?? {})) {
			const local = this.localIds.get(id);
			if (local !== undefined) {
				this.layerOverrides.set(local, layer);
			}
		}
		await this.applyColors();
		await this.applyStates();
		await this.applyVisibility();
		await this.applySelection();
		this.placeFrame();
		this.lighting?.shadows(this.lighting.current !== 'standard');
		if (!this.fitted) {
			this.fitted = true;
			await this.fit();
		}
		await this.fragments.core.update(true);
	}

	async setSelection(elementId: string | undefined): Promise<void> {
		if (elementId !== this.selection) {
			this.selection = elementId;
			await this.applySelection();
			await this.fragments.core.update(true);
		}
	}

	async setTheme(theme: Partial<BuildingViewerTheme>): Promise<void> {
		this.theme = { ...this.theme, ...usableTheme(theme) };
		this.applyTheme();
		await this.applyColors();
		await this.applyStates();
		await this.applySelection();
		await this.fragments.core.update(true);
	}

	async fit(): Promise<void> {
		await this.setView('iso');
	}

	async setView(preset: BuildingViewPreset): Promise<void> {
		const box = this.model?.box;
		if (!box || box.isEmpty()) {
			return;
		}
		const sphere = box.getBoundingSphere(new THREE.Sphere());
		const radius = Math.max(sphere.radius, 1);
		const eye = sphere.center.clone().add(PRESETS[preset].clone().normalize().multiplyScalar(radius * 2.4));
		await this.camera.controls.setLookAt(eye.x, eye.y, eye.z, sphere.center.x, sphere.center.y, sphere.center.z, true);
	}

	async layers(): Promise<readonly { readonly layer: BuildingLayer; readonly count: number; readonly color: string }[]> {
		return CATEGORIES.map(([layer]) => ({ layer, count: this.layerItems.get(layer)?.length ?? 0, color: this.theme[layer] })).filter(l => l.count > 0);
	}

	async setLayerVisible(layer: BuildingLayer, visible: boolean): Promise<void> {
		if (visible === this.hiddenLayers.has(layer)) {
			if (visible) {
				this.hiddenLayers.delete(layer);
			} else {
				this.hiddenLayers.add(layer);
			}
			await this.applyVisibility();
			await this.fragments.core.update(true);
		}
	}

	async setVisibleElements(elementIds: readonly string[] | undefined): Promise<void> {
		this.visibleElements = elementIds && new Set(elementIds);
		await this.applyVisibility();
		await this.fragments.core.update(true);
	}

	layout(): void {
		this.renderer.resize();
		this.camera.updateAspect();
	}

	dispose(): void {
		const canvas = this.renderer.three.domElement;
		canvas?.removeEventListener('pointerdown', this.onPointerDown);
		canvas?.removeEventListener('pointerup', this.onPointerUp);
		this.walk?.dispose();
		this.lighting?.dispose();
		this.disposeTerrain();
		this.components.dispose();
	}

	async setRenderPreset(preset: BuildingRenderPreset): Promise<void> {
		this.lighting ??= new SceneLighting(this.world.scene.three as THREE.Scene, this.renderer.three);
		this.lighting.apply(preset, this.model?.box);
		await this.applyColors();
		await this.applyStates();
		await this.applySelection();
		await this.fragments.core.update(true);
	}

	setSun(direction: readonly number[] | undefined): void {
		this.lighting ??= new SceneLighting(this.world.scene.three as THREE.Scene, this.renderer.three);
		this.lighting.setSun(direction, this.model?.box);
	}

	async setWalkMode(on: boolean): Promise<void> {
		const canvas = this.renderer.three.domElement;
		this.walk?.dispose();
		this.walk = undefined;
		if (on) {
			this.camera.set('FirstPerson');
			this.walk = new WalkKeys(canvas, this.camera.controls);
			canvas.focus();
		} else {
			this.camera.set('Orbit');
		}
	}

	async exportStill(options?: { readonly scale?: number; readonly supersample?: number }): Promise<Blob> {
		await this.fragments.core.update(true);
		return renderStill(this.renderer.three, this.world.scene.three as THREE.Scene, this.camera.three, options);
	}

	setProjectFrame(min: readonly number[], max: readonly number[]): void {
		this.projectExtents = { min, max };
		this.placeFrame();
	}

	setTerrain(points: readonly number[] | undefined, triangles?: readonly number[]): void {
		this.terrainData = points && points.length && triangles?.length ? { points, triangles } : undefined;
		this.placeTerrain();
	}

	async setConstruction(dates: Readonly<Record<string, { readonly start: string; readonly finish: string }>> | undefined, day: string | undefined): Promise<void> {
		this.constructionDates = dates;
		this.constructionDay = day;
		await this.refreshStates();
	}

	async setPhaseStates(states: Readonly<Record<string, 'existing' | 'new' | 'demolished' | 'temporary'>> | undefined): Promise<void> {
		this.phaseStates = states;
		await this.refreshStates();
	}

	private async refreshStates(): Promise<void> {
		await this.applyVisibility();
		await this.applyColors();
		await this.applyStates();
		await this.applySelection();
		await this.fragments.core.update(true);
	}

	/** The project frame from the building's extents and the model's box, then the terrain in it. */
	private placeFrame(): void {
		const box = this.model?.box;
		if (this.projectExtents && box && !box.isEmpty()) {
			this.frame.set(this.projectExtents.min, this.projectExtents.max, box);
		}
		this.placeTerrain();
	}

	private placeTerrain(): void {
		this.disposeTerrain();
		if (!this.terrainData || !this.frame.ready) {
			return;
		}
		this.terrain = terrainMesh(this.terrainData.points, this.terrainData.triangles, this.frame, this.theme.footing);
		this.world.scene.three.add(this.terrain);
	}

	private disposeTerrain(): void {
		if (this.terrain) {
			this.world.scene.three.remove(this.terrain);
			this.terrain.geometry.dispose();
			(this.terrain.material as THREE.Material).dispose();
			this.terrain = undefined;
		}
	}

	/** The clay model's single colour, then the 4D and phase colours, over the class colours. */
	private async applyStates(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		const clay = this.lighting?.clayColor;
		if (clay) {
			const all = [...this.itemColors.keys()];
			all.forEach(id => this.itemColors.set(id, clay));
			if (all.length) {
				await model.highlight(all, this.material(clay));
			}
		}
		const groups = new Map<keyof typeof STATE_STYLE, number[]>();
		for (const [id, local] of this.localIds) {
			let state: keyof typeof STATE_STYLE | undefined;
			if (this.constructionDay !== undefined && constructionState(this.constructionDates?.[id], this.constructionDay) === 'building') {
				state = 'building';
			} else {
				const phase = this.phaseStates?.[id];
				state = phase === 'existing' || phase === 'demolished' || phase === 'temporary' ? phase : undefined;
			}
			if (state) {
				let list = groups.get(state);
				if (!list) {
					list = [];
					groups.set(state, list);
				}
				list.push(local);
			}
		}
		for (const [state, ids] of groups) {
			const style = STATE_STYLE[state];
			ids.forEach(id => {
				this.itemColors.set(id, style.color);
				this.itemOpacity.set(id, style.opacity);
			});
			await model.highlight(ids, this.material(style.color, style.opacity));
		}
	}

	private applyTheme(): void {
		this.world.scene.config.backgroundColor = new THREE.Color(this.theme.background);
		this.grid.config.color = new THREE.Color(this.theme.grid);
	}

	private material(color: string, opacity = 1): FRAGS.MaterialDefinition {
		return { color: new THREE.Color(color), renderedFaces: FRAGS.RenderedFaces.TWO, opacity, transparent: opacity < 1 };
	}

	/**
	 * Colours elements by class, like the floor plan's layers. Fragments keep one highlight per
	 * item, so class colours and the selection are both highlights.
	 */
	private async applyColors(): Promise<void> {
		const model = this.model;
		this.itemColors.clear();
		this.itemOpacity.clear();
		this.highlighted = undefined;
		this.layerItems = new Map();
		if (!model) {
			return;
		}
		const items = await model.getItemsOfCategories(CATEGORIES.map(([, pattern]) => pattern));
		// The architecture's walls are IfcWalls too: by their ids they leave the structure's layer.
		const architecture = new Set([...this.localIds].filter(([id]) => id.startsWith(ARCHITECTURE_PREFIX)).map(([, local]) => local));
		const layers = new Map<BuildingLayer, number[]>();
		for (const [key, pattern] of CATEGORIES) {
			const ids = Object.entries(items).filter(([category]) => pattern.test(category.toUpperCase())).flatMap(([, list]) => list);
			layers.set(key, key === 'room' || key === 'architecture' ? ids : ids.filter(id => !architecture.has(id) && !this.layerOverrides.has(id)));
		}
		for (const [id, layer] of this.layerOverrides) {
			layers.get(layer)?.push(id);
		}
		const rooms = new Set(layers.get('room'));
		layers.set('architecture', [...new Set([...layers.get('architecture')!, ...[...architecture].filter(id => !rooms.has(id))])]);
		for (const [key] of CATEGORIES) {
			const ids = layers.get(key)!;
			this.layerItems.set(key, ids);
			if (ids.length) {
				ids.forEach(id => this.itemColors.set(id, this.theme[key]));
				if (key === 'room') {
					ids.forEach(id => this.itemOpacity.set(id, ROOM_OPACITY));
				}
				await model.highlight(ids, this.material(this.theme[key], key === 'room' ? ROOM_OPACITY : 1));
			}
		}
		// In the architecture's layer, doors in wood and windows in glass, so their openings read.
		const inArchitecture = new Set(layers.get('architecture'));
		for (const [pattern, color, opacity] of [[/^IFCDOOR$/, this.theme.door, 1], [/^IFCWINDOW$/, this.theme.window, WINDOW_OPACITY]] as const) {
			const ids = Object.entries(items).filter(([category]) => pattern.test(category.toUpperCase())).flatMap(([, list]) => list).filter(id => inArchitecture.has(id));
			if (ids.length) {
				ids.forEach(id => {
					this.itemColors.set(id, color);
					this.itemOpacity.set(id, opacity);
				});
				await model.highlight(ids, this.material(color, opacity));
			}
		}
	}

	/** Shows everything, then hides the hidden layers and the elements outside the filter. */
	private async applyVisibility(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		await model.resetVisible();
		const hidden = new Set<number>();
		for (const layer of this.hiddenLayers) {
			this.layerItems.get(layer)?.forEach(id => hidden.add(id));
		}
		if (this.visibleElements) {
			for (const [id, local] of this.localIds) {
				if (!this.visibleElements.has(id)) {
					hidden.add(local);
				}
			}
		}
		// Alpha 9 L11: elements not started on the 4D day, and those not in the phase shown.
		for (const [id, local] of this.localIds) {
			if (this.constructionDay !== undefined && constructionState(this.constructionDates?.[id], this.constructionDay) === 'notStarted') {
				hidden.add(local);
			} else if (this.phaseStates && !(id in this.phaseStates)) {
				hidden.add(local);
			}
		}
		if (hidden.size) {
			await model.setVisible([...hidden], false);
		}
	}

	private async applySelection(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		const local = this.selection === undefined ? undefined : this.localIds.get(this.selection);
		if (this.highlighted !== undefined && this.highlighted !== local) {
			const color = this.itemColors.get(this.highlighted);
			if (color) {
				await model.highlight([this.highlighted], this.material(color, this.itemOpacity.get(this.highlighted) ?? 1));
			} else {
				await model.resetHighlight([this.highlighted]);
			}
		}
		this.highlighted = local;
		if (local !== undefined) {
			await model.highlight([local], this.material(this.theme.selection));
		}
	}

	private async handleClick(e: PointerEvent): Promise<void> {
		const down = this.pointerDown;
		this.pointerDown = undefined;
		// Ignore orbit and pan drags; only a stationary click selects.
		if (e.button !== 0 || !down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4 || !this.model) {
			return;
		}
		const hit = await this.model.raycast({
			camera: this.camera.three,
			mouse: new THREE.Vector2(e.clientX, e.clientY),
			dom: this.renderer.three.domElement,
		});
		const elementId = hit ? this.elementIds.get(hit.localId) : undefined;
		await this.setSelection(elementId);
		this.options.onSelectionChanged?.(elementId);
	}
}

export function createBuildingViewer(container: HTMLElement, options: BuildingViewerOptions): BuildingViewer {
	return new BuildingViewerImpl(container, options);
}
