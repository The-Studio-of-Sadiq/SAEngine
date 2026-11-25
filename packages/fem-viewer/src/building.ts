/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import * as FRAGS from '@thatopen/fragments';
import { usableTheme } from './theme.js';
import { constructionState, ProjectFrame, renderStill, SceneLighting, terrainMesh, WalkKeys, type BuildingRenderPreset } from './render.js';
import { RichMeasureOverlay } from './measure.js';
import {
	buildChainEntry,
	buildDistanceEntry,
	buildEdgeAngleEntry,
	buildPointToFaceEntry,
	chooseSnap,
	closestPointOnSegment,
	distance3,
	type MeasureEntry,
	type SnapCandidate,
	type SnapKind,
	type SnapResult,
	type Vec3,
	type ViewerMeasureMode,
} from './measureMath.js';
import { SectionController } from './section.js';
import {
	sceneNormalToProject,
	type SectionAxis,
	type SectionBoxBounds,
	type SectionPlaneSpec,
	type SectionState,
} from './sectionMath.js';
import {
	applyTemporaryToPermanent,
	computeElementVisibility,
	emptyVisibilityState,
	hideCategoriesTemp,
	hideElementsPermanent,
	hideElementsTemp,
	isolateCategoriesTemp,
	isolateElementsTemp,
	resetTemporaryVisibility,
	summarizeVisibility,
	unhideAllPermanent,
	unhideElementsPermanent,
	type VisibilityState,
	type VisibilitySummary,
} from './visibilityMath.js';

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

export interface MeasureStatus {
	readonly mode: ViewerMeasureMode;
	readonly snap?: SnapKind;
	readonly pendingPoints: number;
	readonly liveLabel?: string;
}

export interface BuildingViewerOptions {
	/** Folder URL (with trailing slash) holding `fragments-worker.mjs` and `web-ifc/`. */
	readonly assetBaseUrl: string;
	readonly theme?: Partial<BuildingViewerTheme>;
	/** An element was clicked (its SAEngine id), or empty space (`undefined`); `elementIds` holds full multi-selection. */
	readonly onSelectionChanged?: (elementId: string | undefined, elementIds?: readonly string[]) => void;
	readonly onSectionChanged?: (state: SectionState) => void;
	readonly onSectionPickModeChanged?: (picking: boolean) => void;
	readonly onMeasureChanged?: (entries: readonly MeasureEntry[], state: MeasureStatus) => void;
	readonly onVisibilityChanged?: (state: VisibilityState<BuildingLayer>, summary: VisibilitySummary) => void;
}

export interface BuildingViewer {
	/**
	 * Shows the IFC `ifc`, replacing the building shown before. `ids` maps SAEngine element ids
	 * to IFC GlobalIds; ids starting with {@link ARCHITECTURE_PREFIX} are the architecture's. The
	 * camera keeps its place after the first load. `layers` puts elements (SAEngine ids) in a
	 * layer other than their IFC class says: a raft, an IfcSlab, among the foundations.
	 */
	load(ifc: Uint8Array, ids: Readonly<Record<string, string>>, layers?: Readonly<Record<string, BuildingLayer>>): Promise<void>;
	setSelection(elementId: string | readonly string[] | undefined): Promise<void>;
	getSelection(): readonly string[];
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

	// R3: Section box, single section planes, 3D measure with snap, and temporary/permanent hide & isolate.
	toggleSectionBox(enabled?: boolean): boolean;
	setSectionBox(boundsMm: SectionBoxBounds | undefined): void;
	sectionBoxFromSelection(): Promise<boolean>;
	resetSectionBox(): void;
	addSectionPlane(axis: SectionAxis): SectionPlaneSpec | undefined;
	setSectionPlanePickMode(active: boolean): void;
	flipSectionPlane(id: string): void;
	removeSectionPlane(id: string): void;
	clearSectionPlanes(): void;
	getSectionState(): SectionState;
	setSectionState(state: SectionState): void;

	setMeasureMode(mode: ViewerMeasureMode): void;
	finishMeasureChain(): void;
	removeMeasurement(id: string): void;
	clearMeasurements(): void;
	getMeasurements(): readonly MeasureEntry[];

	hideSelectedTemp(): Promise<void>;
	isolateSelectedTemp(): Promise<void>;
	hideSelectedCategoryTemp(): Promise<void>;
	isolateSelectedCategoryTemp(): Promise<void>;
	resetTemporaryVisibility(): Promise<void>;
	hideSelectedPermanent(): Promise<void>;
	unhideSelectedPermanent(): Promise<void>;
	unhideAllPermanent(): Promise<void>;
	applyTemporaryHideToPermanent(): Promise<void>;
	setRevealHidden(reveal: boolean): Promise<void>;
	getVisibilityState(): VisibilityState<BuildingLayer>;
	setVisibilityState(state: Partial<VisibilityState<BuildingLayer>>): Promise<void>;
}

/** Colours of the 4D and phase states (see-through where they are not solid). */
const STATE_STYLE = {
	building: { color: '#ff9f40', opacity: 0.45 },
	existing: { color: '#a0a0a0', opacity: 1 },
	demolished: { color: '#e05050', opacity: 0.4 },
	temporary: { color: '#d8b020', opacity: 0.6 },
} as const;

const REVEAL_COLOR = '#ff4d94';
const REVEAL_OPACITY = 0.78;

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
	/** Layer of every item by local id, for category hide/isolate. */
	private itemLayer = new Map<number, BuildingLayer>();
	private selection: string[] = [];
	/** Local ids currently highlighted for selection or reveal-hidden. */
	private readonly highlightedLocals = new Set<number>();
	private readonly revealedLocals = new Set<number>();
	/** Class colour of every coloured item. */
	private readonly itemColors = new Map<number, string>();
	/** Opacity of the see-through items (rooms, windows); the others are opaque. */
	private readonly itemOpacity = new Map<number, number>();
	private fitted = false;
	/** Local ids of each layer's items in the loaded model. */
	private layerItems = new Map<BuildingLayer, number[]>();
	private readonly hiddenLayers = new Set<BuildingLayer>();
	private visibleElements: ReadonlySet<string> | undefined;
	private visibilityState: VisibilityState<BuildingLayer> = emptyVisibilityState();

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

	// R3: section box/planes and rich 3D measurement.
	private readonly section: SectionController;
	private readonly measureOverlay: RichMeasureOverlay;
	private measureMode: ViewerMeasureMode = 'off';
	private measureEntries: MeasureEntry[] = [];
	private measureCounter = 0;
	private activePoints: Vec3[] = [];
	private activeEdge: readonly [Vec3, Vec3] | undefined;
	private previewSnap: SnapResult | undefined;
	private snapBusy = false;
	private pendingSnapPos: { x: number; y: number } | undefined;
	private disposed = false;

	private pointerDown: { x: number; y: number } | undefined;
	private readonly onPointerDown = (e: PointerEvent) => {
		this.renderer.three.domElement.focus({ preventScroll: true });
		if (this.section.onPointerDown(e)) {
			this.pointerDown = undefined;
			return;
		}
		this.pointerDown = { x: e.clientX, y: e.clientY };
	};
	private readonly onPointerMove = (e: PointerEvent) => {
		if (this.section.onPointerMove(e)) {
			return;
		}
		if (this.measureMode !== 'off' && this.model && !this.section.isDragging) {
			this.scheduleSnapPreview(e.clientX, e.clientY);
		}
	};
	private readonly onPointerUp = (e: PointerEvent) => {
		if (this.section.onPointerUp()) {
			return;
		}
		void this.handleClick(e);
	};
	private readonly onPointerCancel = () => this.section.cancelDrag();
	private readonly onContextMenu = (e: MouseEvent) => {
		if (this.measureMode === 'chain' && this.activePoints.length >= 2) {
			e.preventDefault();
			this.finishMeasureChain();
		}
	};

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

		this.section = new SectionController({
			camera: () => this.camera.three,
			domElement: () => this.renderer.three.domElement,
			setControlsEnabled: enabled => { this.camera.controls.enabled = enabled; },
			onLiveChange: state => this.options.onSectionChanged?.(state),
			onCommit: state => {
				this.syncClippingMaterials();
				void this.fragments.core.update(true);
				this.options.onSectionChanged?.(state);
			},
			onPickModeChanged: picking => this.options.onSectionPickModeChanged?.(picking),
			hoverColor: this.theme.selection,
		});
		this.world.scene.three.add(this.section.gizmoGroup);

		this.measureOverlay = new RichMeasureOverlay(this.theme.selection, this.theme.background);
		this.world.scene.three.add(this.measureOverlay.group);

		this.fragments = this.components.get(OBC.FragmentsManager);
		this.fragments.init(`${options.assetBaseUrl}fragments-worker.mjs`);
		// Fragments stream their geometry by view: refresh it when the camera settles.
		this.camera.controls.dollySpeed = DOLLY_SPEED;
		this.camera.controls.dollyToCursor = true;
		this.camera.controls.addEventListener('rest', () => void this.fragments.core.update(true));
		this.fragments.list.onItemSet.add(({ value: model }) => {
			model.useCamera(this.camera.three);
			model.useClippingPlanes(this.section.clipPlanes);
			this.world.scene.three.add(model.object);
			this.syncClippingMaterials();
			void this.fragments.core.update(true);
		});
		this.fragments.core.models.materials.list.onItemSet.add(({ value }) => {
			this.applyClipToMaterial(value);
		});
		this.renderer.onBeforeUpdate.add(() => {
			this.section.updateScale(this.camera.three);
			this.measureOverlay.setLabelScale(this.labelScale());
		});

		// The IFC importer's web-ifc wasm ships with the viewer (no download from a CDN).
		this.ready = this.components.get(OBC.IfcLoader).setup({
			autoSetWasm: false,
			wasm: { path: `${options.assetBaseUrl}web-ifc/`, absolute: true },
		});

		this.applyTheme();
		const canvas = this.renderer.three.domElement;
		canvas.tabIndex = canvas.tabIndex < 0 ? 0 : canvas.tabIndex;
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointermove', this.onPointerMove);
		canvas.addEventListener('pointerup', this.onPointerUp);
		canvas.addEventListener('pointercancel', this.onPointerCancel);
		canvas.addEventListener('contextmenu', this.onContextMenu);
	}

	async load(ifc: Uint8Array, ids: Readonly<Record<string, string>>, layers?: Readonly<Record<string, BuildingLayer>>): Promise<void> {
		await this.ready;
		const load = ++this.loads;
		const model = await this.components.get(OBC.IfcLoader).load(ifc, false, `building-${load}`);
		if (load !== this.loads || this.disposed) {
			await this.fragments.core.disposeModel(model.modelId); // a newer load superseded it
			return;
		}
		const previous = this.model;
		this.model = model;
		if (previous) {
			await this.fragments.core.disposeModel(previous.modelId);
		}
		model.useClippingPlanes(this.section.clipPlanes);
		model.onViewUpdated.add(() => {
			if (!this.disposed && this.model === model) {
				this.syncClippingMaterials();
			}
		});

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
		await this.applyHighlights();
		this.placeFrame();
		this.section.setModelBounds(model.box);
		this.syncClippingMaterials();
		this.lighting?.shadows(this.lighting.current !== 'standard');
		if (!this.fitted) {
			this.fitted = true;
			await this.fit();
		}
		await this.fragments.core.update(true);
	}

	async setSelection(elementId: string | readonly string[] | undefined): Promise<void> {
		const next = elementId === undefined ? [] : (Array.isArray(elementId) ? [...new Set(elementId)] : [elementId as string]);
		if (next.length === this.selection.length && next.every((id, i) => id === this.selection[i])) {
			return;
		}
		this.selection = next;
		await this.applyHighlights();
		await this.fragments.core.update(true);
	}

	getSelection(): readonly string[] {
		return [...this.selection];
	}

	async setTheme(theme: Partial<BuildingViewerTheme>): Promise<void> {
		this.theme = { ...this.theme, ...usableTheme(theme) };
		this.applyTheme();
		this.section.setColors('#3794ff', this.theme.selection);
		this.measureOverlay.setColor(this.theme.selection);
		this.redrawMeasure();
		await this.applyColors();
		await this.applyStates();
		await this.applyHighlights();
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
			await this.applyHighlights();
			await this.fragments.core.update(true);
		}
	}

	async setVisibleElements(elementIds: readonly string[] | undefined): Promise<void> {
		this.visibleElements = elementIds && new Set(elementIds);
		await this.applyVisibility();
		await this.applyHighlights();
		await this.fragments.core.update(true);
	}

	layout(): void {
		this.renderer.resize();
		this.camera.updateAspect();
	}

	dispose(): void {
		this.disposed = true;
		const canvas = this.renderer.three.domElement;
		canvas?.removeEventListener('pointerdown', this.onPointerDown);
		canvas?.removeEventListener('pointermove', this.onPointerMove);
		canvas?.removeEventListener('pointerup', this.onPointerUp);
		canvas?.removeEventListener('pointercancel', this.onPointerCancel);
		canvas?.removeEventListener('contextmenu', this.onContextMenu);
		this.section.dispose();
		this.measureOverlay.dispose();
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
		await this.applyHighlights();
		this.syncClippingMaterials();
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

	// ───────────────────────────── R3: Section ─────────────────────────────

	toggleSectionBox(enabled?: boolean): boolean {
		return this.section.toggleBox(enabled);
	}

	setSectionBox(boundsMm: SectionBoxBounds | undefined): void {
		this.section.setBoxMm(boundsMm);
	}

	async sectionBoxFromSelection(): Promise<boolean> {
		const model = this.model;
		if (!model || !this.selection.length) {
			return false;
		}
		const locals = this.selection.map(id => this.localIds.get(id)).filter((l): l is number => l !== undefined);
		if (!locals.length) {
			return false;
		}
		const box = await model.getMergedBox(locals);
		return this.section.setBoxFromSceneBounds(box);
	}

	resetSectionBox(): void {
		this.section.resetBox();
	}

	addSectionPlane(axis: SectionAxis): SectionPlaneSpec | undefined {
		return this.section.addAxisPlane(axis);
	}

	setSectionPlanePickMode(active: boolean): void {
		if (active && this.measureMode !== 'off') {
			this.setMeasureMode('off');
		}
		this.section.setPlanePickMode(active);
	}

	flipSectionPlane(id: string): void {
		this.section.flipPlane(id);
	}

	removeSectionPlane(id: string): void {
		this.section.removePlane(id);
	}

	clearSectionPlanes(): void {
		this.section.clearPlanes();
	}

	getSectionState(): SectionState {
		return this.section.getState();
	}

	setSectionState(state: SectionState): void {
		this.section.setState(state);
	}

	// ───────────────────────────── R3: Measure ─────────────────────────────

	setMeasureMode(mode: ViewerMeasureMode): void {
		if (mode === this.measureMode) {
			return;
		}
		if (mode !== 'off' && this.section.isPickMode) {
			this.section.setPlanePickMode(false);
		}
		this.measureMode = mode;
		this.activePoints = [];
		this.activeEdge = undefined;
		this.previewSnap = undefined;
		this.renderer.three.domElement.style.cursor = mode !== 'off' ? 'crosshair' : '';
		this.redrawMeasure();
		this.emitMeasureChanged();
	}

	finishMeasureChain(): void {
		if (this.measureMode === 'chain' && this.activePoints.length >= 2) {
			this.measureEntries.push(buildChainEntry(`m-${++this.measureCounter}`, this.activePoints, true, 1));
			this.activePoints = [];
			this.redrawMeasure();
			this.emitMeasureChanged();
		}
	}

	removeMeasurement(id: string): void {
		const before = this.measureEntries.length;
		this.measureEntries = this.measureEntries.filter(e => e.id !== id);
		if (this.measureEntries.length !== before) {
			this.redrawMeasure();
			this.emitMeasureChanged();
		}
	}

	clearMeasurements(): void {
		this.measureEntries = [];
		this.activePoints = [];
		this.activeEdge = undefined;
		this.previewSnap = undefined;
		this.redrawMeasure();
		this.emitMeasureChanged();
	}

	getMeasurements(): readonly MeasureEntry[] {
		return [...this.measureEntries];
	}

	// ───────────────────────────── R3: Hide & Isolate ─────────────────────────────

	async hideSelectedTemp(): Promise<void> {
		if (!this.selection.length) {
			return;
		}
		this.visibilityState = hideElementsTemp(this.visibilityState, this.selection);
		this.selection = [];
		await this.commitVisibility();
		this.options.onSelectionChanged?.(undefined, []);
	}

	async isolateSelectedTemp(): Promise<void> {
		if (!this.selection.length) {
			return;
		}
		this.visibilityState = isolateElementsTemp(this.visibilityState, this.selection);
		await this.commitVisibility();
	}

	async hideSelectedCategoryTemp(): Promise<void> {
		const cats = this.selectedCategories();
		if (!cats.length) {
			return;
		}
		this.visibilityState = hideCategoriesTemp(this.visibilityState, cats);
		this.selection = [];
		await this.commitVisibility();
		this.options.onSelectionChanged?.(undefined, []);
	}

	async isolateSelectedCategoryTemp(): Promise<void> {
		const cats = this.selectedCategories();
		if (!cats.length) {
			return;
		}
		this.visibilityState = isolateCategoriesTemp(this.visibilityState, cats);
		await this.commitVisibility();
	}

	async resetTemporaryVisibility(): Promise<void> {
		this.visibilityState = resetTemporaryVisibility(this.visibilityState);
		await this.commitVisibility();
	}

	async hideSelectedPermanent(): Promise<void> {
		if (!this.selection.length) {
			return;
		}
		this.visibilityState = hideElementsPermanent(this.visibilityState, this.selection);
		this.selection = [];
		await this.commitVisibility();
		this.options.onSelectionChanged?.(undefined, []);
	}

	async unhideSelectedPermanent(): Promise<void> {
		if (!this.selection.length) {
			return;
		}
		this.visibilityState = unhideElementsPermanent(this.visibilityState, this.selection);
		await this.commitVisibility();
	}

	async unhideAllPermanent(): Promise<void> {
		this.visibilityState = unhideAllPermanent(this.visibilityState);
		await this.commitVisibility();
	}

	async applyTemporaryHideToPermanent(): Promise<void> {
		this.visibilityState = applyTemporaryToPermanent(this.visibilityState, this.allTrackedElements());
		await this.commitVisibility();
	}

	async setRevealHidden(reveal: boolean): Promise<void> {
		if (this.visibilityState.revealHidden === reveal) {
			return;
		}
		this.visibilityState = { ...this.visibilityState, revealHidden: reveal };
		await this.commitVisibility();
	}

	getVisibilityState(): VisibilityState<BuildingLayer> {
		return this.visibilityState;
	}

	async setVisibilityState(state: Partial<VisibilityState<BuildingLayer>>): Promise<void> {
		this.visibilityState = {
			...this.visibilityState,
			...state,
		};
		await this.commitVisibility();
	}

	private selectedCategories(): BuildingLayer[] {
		const cats = new Set<BuildingLayer>();
		for (const id of this.selection) {
			const local = this.localIds.get(id);
			const layer = local !== undefined ? this.itemLayer.get(local) : undefined;
			if (layer) {
				cats.add(layer);
			}
		}
		return [...cats];
	}

	private allTrackedElements(): { readonly id: string; readonly category?: BuildingLayer }[] {
		const list: { id: string; category?: BuildingLayer }[] = [];
		for (const [id, local] of this.localIds) {
			list.push({ id, category: this.itemLayer.get(local) });
		}
		return list;
	}

	private async commitVisibility(): Promise<void> {
		await this.applyVisibility();
		await this.applyHighlights();
		await this.fragments.core.update(true);
		this.options.onVisibilityChanged?.(this.visibilityState, summarizeVisibility(this.visibilityState));
	}

	private async refreshStates(): Promise<void> {
		await this.applyVisibility();
		await this.applyColors();
		await this.applyStates();
		await this.applyHighlights();
		this.syncClippingMaterials();
		await this.fragments.core.update(true);
	}

	/** The project frame from the building's extents and the model's box, then the terrain in it. */
	private placeFrame(): void {
		const box = this.model?.box;
		if (this.projectExtents && box && !box.isEmpty()) {
			this.frame.set(this.projectExtents.min, this.projectExtents.max, box);
			this.section.setFrame(this.frame.factor, this.frame.origin);
		}
		this.placeTerrain();
	}

	private placeTerrain(): void {
		this.disposeTerrain();
		if (!this.terrainData || !this.frame.ready) {
			return;
		}
		this.terrain = terrainMesh(this.terrainData.points, this.terrainData.triangles, this.frame, this.theme.footing);
		this.applyClipToMaterial(this.terrain.material as THREE.Material);
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

	private applyClipToMaterial(material: THREE.Material | THREE.Material[] | undefined): void {
		if (!material) {
			return;
		}
		const list = Array.isArray(material) ? material : [material];
		for (const mat of list) {
			if (mat.clippingPlanes !== this.section.clipPlanes) {
				mat.clippingPlanes = this.section.clipPlanes;
				mat.needsUpdate = true;
			}
		}
	}

	private syncClippingMaterials(): void {
		for (const [, mat] of this.fragments.core.models.materials.list) {
			this.applyClipToMaterial(mat);
		}
		if (this.model?.object) {
			this.section.applyToObject(this.model.object);
		}
		if (this.terrain) {
			this.applyClipToMaterial(this.terrain.material);
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
		this.highlightedLocals.clear();
		this.revealedLocals.clear();
		this.layerItems = new Map();
		this.itemLayer.clear();
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
			for (const id of ids) {
				this.itemLayer.set(id, key);
			}
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

	/** Shows everything, then hides hidden layers, external filters, and user-hidden elements. */
	private async applyVisibility(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		await model.resetVisible();
		const hidden = new Set<number>();
		this.revealedLocals.clear();

		const externalHiddenIds = new Set<string>();
		const externalHiddenLocals = new Set<number>();
		for (const layer of this.hiddenLayers) {
			for (const local of this.layerItems.get(layer) ?? []) {
				externalHiddenLocals.add(local);
				const saId = this.elementIds.get(local);
				if (saId !== undefined) {
					externalHiddenIds.add(saId);
				}
			}
		}
		for (const [id, local] of this.localIds) {
			if (this.visibleElements && !this.visibleElements.has(id)) {
				externalHiddenIds.add(id);
				externalHiddenLocals.add(local);
			} else if (this.constructionDay !== undefined && constructionState(this.constructionDates?.[id], this.constructionDay) === 'notStarted') {
				externalHiddenIds.add(id);
				externalHiddenLocals.add(local);
			} else if (this.phaseStates && !(id in this.phaseStates)) {
				externalHiddenIds.add(id);
				externalHiddenLocals.add(local);
			}
		}

		const result = computeElementVisibility(this.allTrackedElements(), this.visibilityState, externalHiddenIds);
		for (const id of result.hidden) {
			const local = this.localIds.get(id);
			if (local !== undefined) {
				hidden.add(local);
			}
		}
		for (const id of result.revealed) {
			const local = this.localIds.get(id);
			if (local !== undefined) {
				this.revealedLocals.add(local);
			}
		}

		// Handle items without an SAEngine element id (e.g. unmapped IFC subparts) during layer/category/isolate filters.
		const catHidden = new Set(this.visibilityState.tempHiddenCategories);
		const catIso = this.visibilityState.tempIsolatedCategories ? new Set(this.visibilityState.tempIsolatedCategories) : undefined;
		const isolatingElements = this.visibilityState.tempIsolatedElements !== undefined;
		for (const [local, layer] of this.itemLayer) {
			if (this.elementIds.has(local)) {
				continue;
			}
			if (externalHiddenLocals.has(local)) {
				hidden.add(local);
				continue;
			}
			const hiddenByCat = catHidden.has(layer) || (catIso !== undefined && !catIso.has(layer));
			if (hiddenByCat || isolatingElements) {
				if (this.visibilityState.revealHidden) {
					this.revealedLocals.add(local);
				} else {
					hidden.add(local);
				}
			}
		}

		for (const local of externalHiddenLocals) {
			hidden.add(local);
		}
		if (hidden.size) {
			await model.setVisible([...hidden], false);
		}
	}

	private async applyHighlights(): Promise<void> {
		const model = this.model;
		if (!model) {
			return;
		}
		const selectedLocals = new Set<number>();
		for (const id of this.selection) {
			const local = this.localIds.get(id);
			if (local !== undefined) {
				selectedLocals.add(local);
			}
		}
		const desired = new Set<number>([...selectedLocals, ...this.revealedLocals]);

		// Restore any items no longer selected or revealed back to their base layer/state colour.
		const resetIds: number[] = [];
		for (const prev of this.highlightedLocals) {
			if (!desired.has(prev)) {
				const color = this.itemColors.get(prev);
				if (color) {
					await model.highlight([prev], this.material(color, this.itemOpacity.get(prev) ?? 1));
				} else {
					resetIds.push(prev);
				}
			}
		}
		if (resetIds.length) {
			await model.resetHighlight(resetIds);
		}

		const revealOnly = [...this.revealedLocals].filter(id => !selectedLocals.has(id));
		if (revealOnly.length) {
			await model.highlight(revealOnly, this.material(REVEAL_COLOR, REVEAL_OPACITY));
		}
		if (selectedLocals.size) {
			await model.highlight([...selectedLocals], this.material(this.theme.selection));
		}

		this.highlightedLocals.clear();
		for (const id of desired) {
			this.highlightedLocals.add(id);
		}
	}

	private async handleClick(e: PointerEvent): Promise<void> {
		const down = this.pointerDown;
		this.pointerDown = undefined;
		if (this.section.consumeJustDragged()) {
			return;
		}
		// Ignore orbit and pan drags; only a stationary click acts.
		if (e.button !== 0 || !down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4 || !this.model) {
			return;
		}
		if (this.section.isPickMode) {
			const hit = await this.model.raycast({
				camera: this.camera.three,
				mouse: new THREE.Vector2(e.clientX, e.clientY),
				dom: this.renderer.three.domElement,
			});
			if (hit?.normal) {
				this.section.addPlaneFromSceneHit(hit.point, hit.normal);
				this.syncClippingMaterials();
				await this.fragments.core.update(true);
			}
			return;
		}
		if (this.measureMode !== 'off') {
			await this.handleMeasureClick(e.clientX, e.clientY);
			return;
		}
		const hit = await this.model.raycast({
			camera: this.camera.three,
			mouse: new THREE.Vector2(e.clientX, e.clientY),
			dom: this.renderer.three.domElement,
		});
		const elementId = hit ? this.elementIds.get(hit.localId) : undefined;
		if (e.ctrlKey || e.metaKey || e.shiftKey) {
			if (elementId) {
				if (this.selection.includes(elementId)) {
					this.selection = this.selection.filter(id => id !== elementId);
				} else {
					this.selection = [...this.selection, elementId];
				}
			}
		} else {
			this.selection = elementId ? [elementId] : [];
		}
		await this.applyHighlights();
		await this.fragments.core.update(true);
		const primary = this.selection[this.selection.length - 1];
		this.options.onSelectionChanged?.(primary, [...this.selection]);
	}

	private scheduleSnapPreview(clientX: number, clientY: number): void {
		this.pendingSnapPos = { x: clientX, y: clientY };
		if (this.snapBusy) {
			return;
		}
		void this.flushSnapPreview();
	}

	private async flushSnapPreview(): Promise<void> {
		this.snapBusy = true;
		try {
			while (this.pendingSnapPos && !this.disposed && this.measureMode !== 'off') {
				const pos = this.pendingSnapPos;
				this.pendingSnapPos = undefined;
				const snap = await this.raycastSnap(pos.x, pos.y, this.measureMode === 'edgeAngle');
				if (this.disposed || (this.measureMode as ViewerMeasureMode) === 'off') {
					break;
				}
				this.previewSnap = snap;
				this.redrawMeasure();
				this.emitMeasureChanged();
			}
		} finally {
			this.snapBusy = false;
		}
	}

	private async handleMeasureClick(clientX: number, clientY: number): Promise<void> {
		const snap = await this.raycastSnap(clientX, clientY, this.measureMode === 'edgeAngle');
		if (!snap) {
			return;
		}
		this.previewSnap = snap;

		if (this.measureMode === 'distance') {
			this.activePoints.push(snap.point);
			if (this.activePoints.length >= 2) {
				this.measureEntries.push(buildDistanceEntry(`m-${++this.measureCounter}`, this.activePoints[0], this.activePoints[1], 1));
				this.activePoints = [];
			}
		} else if (this.measureMode === 'chain') {
			this.activePoints.push(snap.point);
		} else if (this.measureMode === 'pointToFace') {
			if (this.activePoints.length === 0) {
				this.activePoints.push(snap.point);
			} else if (snap.normal) {
				this.measureEntries.push(buildPointToFaceEntry(`m-${++this.measureCounter}`, this.activePoints[0], snap.point, snap.normal, 1));
				this.activePoints = [];
			}
		} else if (this.measureMode === 'edgeAngle') {
			const edge = snap.edge;
			if (!edge) {
				return;
			}
			if (!this.activeEdge) {
				this.activeEdge = edge;
			} else {
				this.measureEntries.push(buildEdgeAngleEntry(`m-${++this.measureCounter}`, this.activeEdge, edge));
				this.activeEdge = undefined;
			}
		}
		this.redrawMeasure();
		this.emitMeasureChanged();
	}

	private async raycastSnap(clientX: number, clientY: number, requireEdge: boolean): Promise<SnapResult | undefined> {
		const model = this.model;
		if (!model) {
			return undefined;
		}
		const canvas = this.renderer.three.domElement;
		const rect = canvas.getBoundingClientRect();
		const camera = this.camera.three;
		const project = (worldPos: THREE.Vector3) => {
			const ndc = worldPos.clone().project(camera);
			return {
				x: rect.left + (ndc.x + 1) / 2 * rect.width,
				y: rect.top + (1 - ndc.y) / 2 * rect.height,
				depth: ndc.z,
				visible: ndc.z >= -1 && ndc.z <= 1,
			};
		};

		const candidates: SnapCandidate[] = [];
		const snapClasses = requireEdge
			? [FRAGS.SnappingClass.LINE, FRAGS.SnappingClass.FACE]
			: [FRAGS.SnappingClass.POINT, FRAGS.SnappingClass.LINE, FRAGS.SnappingClass.FACE];

		let snapHits: FRAGS.RaycastResult[] | null = null;
		try {
			snapHits = await model.raycastWithSnapping({
				camera,
				mouse: new THREE.Vector2(clientX, clientY),
				dom: canvas,
				snappingClasses: snapClasses,
			});
		} catch {
			snapHits = null;
		}

		const toProj = (v: THREE.Vector3): Vec3 => this.frame.toProject(v);
		const pushSceneCandidate = (worldPt: THREE.Vector3, kind: SnapKind, worldNormal?: THREE.Vector3, worldEdge?: readonly [THREE.Vector3, THREE.Vector3]) => {
			const proj = project(worldPt);
			if (!proj.visible) {
				return;
			}
			const edge: readonly [Vec3, Vec3] | undefined = worldEdge ? [toProj(worldEdge[0]), toProj(worldEdge[1])] : undefined;
			const normal: Vec3 | undefined = worldNormal ? sceneNormalToProject([worldNormal.x, worldNormal.y, worldNormal.z]) : undefined;
			candidates.push({
				point: toProj(worldPt),
				kind,
				screenDistancePx: Math.hypot(proj.x - clientX, proj.y - clientY),
				depth: proj.depth,
				normal,
				edge,
			});
		};

		if (snapHits && snapHits.length) {
			for (const hit of snapHits) {
				if (hit.snappingClass === FRAGS.SnappingClass.POINT) {
					pushSceneCandidate(hit.point, 'vertex', hit.normal);
				} else if (hit.snappingClass === FRAGS.SnappingClass.LINE && hit.snappedEdgeP1 && hit.snappedEdgeP2) {
					const p1 = hit.snappedEdgeP1;
					const p2 = hit.snappedEdgeP2;
					const mid = p1.clone().add(p2).multiplyScalar(0.5);
					pushSceneCandidate(p1, 'vertex', hit.normal, [p1, p2]);
					pushSceneCandidate(p2, 'vertex', hit.normal, [p1, p2]);
					pushSceneCandidate(mid, 'midpoint', hit.normal, [p1, p2]);
					pushSceneCandidate(hit.point, 'edge', hit.normal, [p1, p2]);
				} else if (hit.snappingClass === FRAGS.SnappingClass.FACE) {
					pushSceneCandidate(hit.point, 'face', hit.normal);
					if (hit.facePoints && hit.facePoints.length >= 9) {
						const fp = hit.facePoints;
						const mat = model.object.matrixWorld;
						const pts: THREE.Vector3[] = [];
						for (let i = 0; i + 2 < fp.length; i += 3) {
							pts.push(new THREE.Vector3(fp[i], fp[i + 1], fp[i + 2]).applyMatrix4(mat));
						}
						if (pts.length >= 3) {
							let bestEdge: [THREE.Vector3, THREE.Vector3] | undefined;
							let bestEdgeDist = Infinity;
							const hitProj = toProj(hit.point);
							for (let i = 0; i < pts.length; i++) {
								const a = pts[i];
								const b = pts[(i + 1) % pts.length];
								if (!requireEdge) {
									pushSceneCandidate(a, 'vertex', hit.normal);
									pushSceneCandidate(a.clone().add(b).multiplyScalar(0.5), 'midpoint', hit.normal, [a, b]);
								}
								const pa = toProj(a);
								const pb = toProj(b);
								const cp = closestPointOnSegment(hitProj, pa, pb);
								const d = distance3(hitProj, cp);
								if (d < bestEdgeDist) {
									bestEdgeDist = d;
									bestEdge = [a, b];
								}
							}
							if (bestEdge) {
								pushSceneCandidate(hit.point, 'edge', hit.normal, bestEdge);
							}
						}
					}
				}
			}
		}

		if (!candidates.length) {
			const fallback = await model.raycast({
				camera,
				mouse: new THREE.Vector2(clientX, clientY),
				dom: canvas,
			});
			if (fallback) {
				pushSceneCandidate(fallback.point, 'face', fallback.normal);
			}
		}

		if (requireEdge) {
			const edgeOnly = candidates.filter(c => c.edge !== undefined);
			if (!edgeOnly.length) {
				return undefined;
			}
			// Prefer explicit line snaps closest to the cursor when picking edges for angles.
			edgeOnly.sort((a, b) => a.screenDistancePx - b.screenDistancePx || a.depth - b.depth);
			const chosen = edgeOnly[0];
			return { point: chosen.point, kind: 'edge', normal: chosen.normal, edge: chosen.edge };
		}

		return chooseSnap(candidates);
	}

	private redrawMeasure(): void {
		this.measureOverlay.drawEntries(
			this.measureEntries,
			p => this.frame.toScene(p[0], p[1], p[2]),
			this.activePoints,
			this.measureMode,
			this.previewSnap,
			this.activeEdge,
			1,
		);
	}

	private emitMeasureChanged(): void {
		let liveLabel: string | undefined;
		if (this.activePoints.length && this.previewSnap && (this.measureMode === 'distance' || this.measureMode === 'chain')) {
			const last = this.activePoints[this.activePoints.length - 1];
			liveLabel = `${Math.round(distance3(last, this.previewSnap.point))} mm`;
		} else if (this.measureMode === 'chain' && this.activePoints.length >= 2) {
			const last = this.activePoints[this.activePoints.length - 1];
			const prev = this.activePoints[this.activePoints.length - 2];
			liveLabel = `${Math.round(distance3(prev, last))} mm`;
		} else if (this.measureMode === 'pointToFace' && this.activePoints.length === 1 && this.previewSnap?.normal) {
			const entry = buildPointToFaceEntry('preview', this.activePoints[0], this.previewSnap.point, this.previewSnap.normal, 1);
			liveLabel = entry.label;
		} else if (this.measureMode === 'edgeAngle' && this.activeEdge && this.previewSnap?.edge) {
			const entry = buildEdgeAngleEntry('preview', this.activeEdge, this.previewSnap.edge);
			liveLabel = entry.label;
		}
		this.options.onMeasureChanged?.([...this.measureEntries], {
			mode: this.measureMode,
			snap: this.previewSnap?.kind,
			pendingPoints: this.activeEdge ? 1 : this.activePoints.length,
			liveLabel,
		});
	}

	private labelScale(): number {
		if (this.camera.projection.current !== 'Orthographic') {
			return 1;
		}
		const ortho = this.camera.threeOrtho;
		const focal = 1 / Math.tan(THREE.MathUtils.degToRad(this.camera.threePersp.fov) / 2);
		return focal * (ortho.top - ortho.bottom) / (2 * ortho.zoom);
	}
}

export function createBuildingViewer(container: HTMLElement, options: BuildingViewerOptions): BuildingViewer {
	return new BuildingViewerImpl(container, options);
}
