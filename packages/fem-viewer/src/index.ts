/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import { roundPointMaterial, subtleNodeColor, usableTheme } from './theme.js';
import { Floats, ModelIndex } from './geometry.js';
import { FemCameraView, FemElement, FemModel, FemResultDisplay, FemResultView, FemSelection, FemVisibleElements, outerFaces, sameSelection } from './model.js';
import { ResultOverlay } from './results.js';
import { Development, FemPlanPath, isUsablePath } from './development.js';
import { fromWorld, FemMeasureMode, FemMeasurement, FemMeasurePoint, measure, MeasureOverlay, RichMeasureOverlay } from './measure.js';
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

export type { FemCameraView, FemElement, FemModel, FemNode, FemResultDisplay, FemResultElement, FemResultQuantity, FemResultShell, FemResultSolid, FemResultView, FemSelection, FemValueQuantity, FemVisibleElements } from './model.js';
export { FORCE_COMPONENTS, SHELL_COMPONENTS, SOLID_COMPONENTS, formatUtilisation, UTILISATION_WARN, utilisationBand } from './model.js';
export { contourColor } from './results.js';
export { Development, type FemPlanPath } from './development.js';
export { measure, type FemMeasureMode, type FemMeasurement, type FemMeasurePoint } from './measure.js';

export interface FemViewerTheme {
	readonly background: string;
	readonly member: string;
	readonly node: string;
	readonly support: string;
	readonly selection: string;
	readonly grid: string;
	/** Results: deflected shape, positive and negative diagram values, reactions. */
	readonly deformed: string;
	readonly positive: string;
	readonly negative: string;
	readonly reaction: string;
	/** Design utilisation bands: below 0.9, 0.9 to 1.0, above 1.0. */
	readonly pass: string;
	readonly warn: string;
	readonly fail: string;
}

export interface FemMeasureStatus {
	readonly mode: ViewerMeasureMode;
	readonly snap?: SnapKind;
	readonly pendingPoints: number;
	readonly liveLabel?: string;
}

export interface FemViewerOptions {
	readonly theme?: Partial<FemViewerTheme>;
	readonly onSelectionChanged?: (selection: FemSelection | undefined, elementIds?: readonly string[]) => void;
	/** A measurement taken (a point picked, or the measurement cleared: undefined). */
	readonly onMeasure?: (measurement: FemMeasurement | undefined) => void;
	readonly onMeasureChanged?: (entries: readonly MeasureEntry[], state: FemMeasureStatus) => void;
	readonly onSectionChanged?: (state: SectionState) => void;
	readonly onSectionPickModeChanged?: (picking: boolean) => void;
	readonly onVisibilityChanged?: (state: VisibilityState, summary: VisibilitySummary) => void;
	/** The unit of the model's lengths in the measure labels (default `m`). */
	readonly lengthUnit?: string;
}

/** Options of {@link FemViewer.recordAnimation}. */
export interface FemRecordOptions {
	/** Length of the video [s] (default: two cycles of the motion, 3.2 s). */
	readonly seconds?: number;
	/** Frames per second (default 30). */
	readonly fps?: number;
}

/** Alpha 9 L2: a decimated laser scan in model space (see {@link FemViewer.setPointCloud}). */
export interface FemPointCloud {
	readonly positions: ArrayLike<number>;
	readonly colors?: ArrayLike<number>;
	/** Point size on screen [px]; default 2. */
	readonly size?: number;
}

export interface FemViewer {
	setModel(model: FemModel): void;
	setSelection(selection: FemSelection | undefined): void;
	getSelection(): readonly string[];
	/** Draws an analysis result over the model (undefined: the model alone). */
	setResults(results: FemResultView | undefined, display?: FemResultDisplay): void;
	setTheme(theme: Partial<FemViewerTheme>): void;
	/** Draws only these elements and their nodes (a floor, an elevation, a storey); undefined: all. */
	setVisibleElements(elements: FemVisibleElements): void;
	/**
	 * Draws (and picks) the mesh's own nodes too: those inside a member split into pieces and
	 * those of the wall and slab meshes. Off by default: the joints, supports and diaphragm
	 * centres are drawn, and a click on a member picks the member.
	 */
	setMeshNodes(shown: boolean): void;
	/**
	 * Alpha 9 L2: shows a laser scan as a reference under the model (not picked, not measured):
	 * `positions` x, y, z in model space (Z up), `colors` r, g, b in 0-1 per point (grey by
	 * intensity) or undefined (one muted colour); undefined removes it.
	 */
	setPointCloud(cloud: FemPointCloud | undefined): void;
	/**
	 * Looks at the model in 3D (perspective, orbiting) or straight down the model's Z (`top`: a
	 * plan), along its Y (`front`: an X-Z elevation) or along its X (`side`: a Y-Z elevation),
	 * orthographic, and frames what is drawn.
	 */
	setCameraView(view: FemCameraView): Promise<void>;
	fit(): Promise<void>;
	/**
	 * A developed elevation: the frames and walls standing on the plan path `path` (model x, y),
	 * unfolded into one plane (the distance along the path across, Z up), results included.
	 * Returns the ids of the elements on the path (the host shows only those); undefined (or a
	 * path without length): the model as it stands.
	 */
	setDevelopment(path: FemPlanPath | undefined): FemVisibleElements;
	/**
	 * Clicks measure instead of selecting: a distance, chain, point-to-face, edge angle,
	 * 3-point angle or polygon area. Points snap to nodes/midpoints/edges/faces. Escape clears.
	 */
	setMeasureMode(mode: FemMeasureMode | ViewerMeasureMode): void;
	clearMeasurement(): void;
	finishMeasureChain(): void;
	removeMeasurement(id: string): void;
	clearMeasurements(): void;
	getMeasurements(): readonly MeasureEntry[];
	/**
	 * Records the deflected shape shown moving (a mode shape oscillating, a static one growing
	 * from rest and back) as a WebM video of the view; undefined when no deflected shape is shown
	 * or the browser cannot record.
	 */
	recordAnimation(options?: FemRecordOptions): Promise<Blob | undefined>;
	/** Call when the container changes size and the browser has not reported it (e.g. hidden tabs). */
	layout(): void;
	dispose(): void;

	// R3: Section box & single section planes
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

	// R3: Hide / Isolate
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
	getVisibilityState(): VisibilityState;
	setVisibilityState(state: Partial<VisibilityState>): Promise<void>;
}

/** One cycle of a deflected shape's motion [ms]. */
const ANIMATION_PERIOD_MS = 1600;
const REVEAL_COLOR = '#ff4d94';

const defaultTheme: FemViewerTheme = {
	background: '#1e1e1e',
	member: '#4fc1ff',
	node: '#d4d4d4',
	support: '#89d185',
	selection: '#ffcc00',
	grid: '#3c3c3c',
	deformed: '#d18616',
	positive: '#3794ff',
	negative: '#f14c4c',
	reaction: '#89d185',
	pass: '#89d185',
	warn: '#cca700',
	fail: '#f14c4c',
};

function sameTheme(a: FemViewerTheme, b: FemViewerTheme): boolean {
	return (Object.keys(a) as (keyof FemViewerTheme)[]).every(key => a[key] === b[key]);
}

function sameElements(a: FemVisibleElements, b: FemVisibleElements): boolean {
	if (!a || !b) {
		return a === b;
	}
	if (a.size !== b.size) {
		return false;
	}
	for (const id of a) {
		if (!b.has(id)) {
			return false;
		}
	}
	return true;
}

/**
 * The mesh's own nodes, not drawn unless asked for: a node joining just two pieces of one member
 * (`B3#2`, `B3#3`) and nothing else but plates, or a node of plates (wall and slab meshes) only;
 * never a restrained node. The members' ends, the joints and the diaphragms' centres stay.
 */
export function meshNodeIds(model: FemModel): Set<number> {
	const pieces = new Map<number, string[]>(); // node: the members of the frame pieces at it
	const plated = new Set<number>();
	for (const element of model.elements) {
		if (element.nodes.length === 2) {
			const member = (element.name ?? String(element.id)).split('#')[0];
			for (const n of element.nodes) {
				let at = pieces.get(n);
				if (!at) {
					pieces.set(n, at = []);
				}
				at.push(member);
			}
		} else if (element.nodes.length >= 3 && element.type !== 'Solid') {
			element.nodes.forEach(n => plated.add(n));
		}
	}
	const mesh = new Set<number>();
	for (const node of model.nodes) {
		if (node.restraint?.some(Boolean)) {
			continue;
		}
		const at = pieces.get(node.id);
		if (at ? at.length === 2 && at[0] === at[1] : plated.has(node.id)) {
			mesh.add(node.id);
		}
	}
	return mesh;
}

/** Element names of the struts tying frames and shells into solids (not drawn). */
const EMBED = /\/embed(#\d+)?$/;

function toProjectMm(v: THREE.Vector3): Vec3 {
	return [v.x * 1000, -v.z * 1000, v.y * 1000];
}

function toSceneM(p: Vec3): THREE.Vector3 {
	return new THREE.Vector3(p[0] / 1000, p[2] / 1000, -p[1] / 1000);
}

class FemViewerImpl implements FemViewer {

	private readonly components = new OBC.Components();
	private readonly world: OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;
	private readonly renderer: OBC.SimpleRenderer;
	private readonly camera: OBC.OrthoPerspectiveCamera;
	private readonly grid: OBC.SimpleGrid;
	private readonly modelGroup = new THREE.Group();
	private readonly revealGroup = new THREE.Group();
	private readonly pickTargets: THREE.Object3D[] = [];

	private theme: FemViewerTheme;
	private model: FemModel | undefined;
	private meshNodes = false;
	/** The model's nodes in world space and its elements by id, shared with the results. */
	private index: ModelIndex | undefined;
	private selection: FemSelection | undefined;
	private selectedElements: number[] = [];

	private members: THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial> | undefined;
	private memberIds: number[] = [];
	/** The outline of the solids (dimmed under a result, as the members). */
	private solidEdges: THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial> | undefined;
	private nodes: THREE.Points | undefined;
	private nodeIds: number[] = [];
	/** Alpha 9 L2: the laser scan shown under the model (not picked). */
	private pointCloud: THREE.Points | undefined;
	/** The shells' faces, as triangles, and the element of each triangle. */
	private faces: THREE.Mesh | undefined;
	private faceIds: number[] = [];
	private revealMembers: THREE.LineSegments | undefined;
	private revealMemberIds: number[] = [];
	private revealFaces: THREE.Mesh | undefined;
	private revealFaceIds: number[] = [];
	private readonly highlight = new THREE.Group();
	private readonly resultGroup = new THREE.Group();
	private results: { readonly view: FemResultView; readonly display: FemResultDisplay } | undefined;
	private visible: FemVisibleElements;
	private visibilityState: VisibilityState = emptyVisibilityState();
	private revealedElementIds = new Set<number>();
	private hiddenElementIds = new Set<number>();
	private cameraView: FemCameraView = '3d';
	private overlay: ResultOverlay | undefined;
	private animation: number | undefined;
	/** The developed elevation shown (its path), or undefined. */
	private developmentPath: FemPlanPath | undefined;
	private development: Development | undefined;
	private measureMode: ViewerMeasureMode = 'off';
	private measurePoints: FemMeasurePoint[] = [];
	private measureClosed = false;
	private readonly measureOverlay: MeasureOverlay;
	private readonly richMeasureOverlay: RichMeasureOverlay;
	private measureEntries: MeasureEntry[] = [];
	private measureCounter = 0;
	private richPoints: Vec3[] = [];
	private activeEdge: readonly [Vec3, Vec3] | undefined;
	private previewSnap: SnapResult | undefined;
	private readonly section: SectionController;
	/** Recording an animation: any deflected shape moves. */
	private recording = false;
	private readonly onKeyDown = (e: KeyboardEvent) => {
		if (e.key === 'Escape' && this.measureMode !== 'off' && (this.measurePoints.length || this.richPoints.length || this.activeEdge)) {
			e.stopPropagation();
			this.clearMeasurement();
		}
	};
	private readonly raycaster = new THREE.Raycaster();

	private pointerDown: { x: number; y: number } | undefined;
	private readonly onPointerDown = (e: PointerEvent) => {
		this.renderer.three.domElement.focus({ preventScroll: true });
		if (this.section.onPointerDown(e)) {
			this.pointerDown = undefined;
			return;
		}
		this.pointerDown = { x: e.clientX, y: e.clientY };
		this.untouched = false; // an orbit, pan or click: the camera is the engineer's now
	};
	private readonly onPointerMove = (e: PointerEvent) => {
		if (this.section.onPointerMove(e)) {
			return;
		}
		if (this.isRichMeasureMode(this.measureMode) && this.index && !this.section.isDragging) {
			this.previewSnap = this.snapAt(e.clientX, e.clientY, this.measureMode === 'edgeAngle');
			this.redrawRichMeasure();
			this.emitRichMeasureChanged();
		}
	};
	private readonly onWheel = () => { this.untouched = false; };
	/** The camera is where the last fit put it. */
	private untouched = false;
	private readonly onPointerUp = (e: PointerEvent) => {
		if (this.section.onPointerUp()) {
			return;
		}
		this.handleClick(e);
	};
	private readonly onPointerCancel = () => this.section.cancelDrag();
	private readonly onContextMenu = (e: MouseEvent) => {
		if (this.measureMode === 'chain' && this.richPoints.length >= 2) {
			e.preventDefault();
			this.finishMeasureChain();
		}
	};

	constructor(private readonly container: HTMLElement, private readonly options: FemViewerOptions) {
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
		this.world.scene.three.add(this.modelGroup);
		this.world.scene.three.add(this.revealGroup);
		this.world.scene.three.add(this.highlight);
		this.world.scene.three.add(this.resultGroup);
		this.measureOverlay = new MeasureOverlay(this.theme.selection, this.theme.background);
		this.world.scene.three.add(this.measureOverlay.group);
		this.richMeasureOverlay = new RichMeasureOverlay(this.theme.selection, this.theme.background);
		this.world.scene.three.add(this.richMeasureOverlay.group);

		this.section = new SectionController({
			camera: () => this.camera.three,
			domElement: () => this.renderer.three.domElement,
			setControlsEnabled: enabled => { this.camera.controls.enabled = enabled; },
			onLiveChange: state => this.options.onSectionChanged?.(state),
			onCommit: state => {
				this.applyClipping();
				this.options.onSectionChanged?.(state);
			},
			onPickModeChanged: picking => this.options.onSectionPickModeChanged?.(picking),
			hoverColor: this.theme.selection,
		});
		this.world.scene.three.add(this.section.gizmoGroup);

		this.applyTheme();

		// Labels: the same size on screen under the orthographic camera as under the perspective one.
		this.renderer.onBeforeUpdate.add(() => {
			const scale = this.labelScale();
			this.overlay?.setLabelScale(scale);
			this.measureOverlay.setLabelScale(scale);
			this.richMeasureOverlay.setLabelScale(scale);
			this.section.updateScale(this.camera.three);
		});

		const canvas = this.renderer.three.domElement;
		canvas.tabIndex = canvas.tabIndex < 0 ? 0 : canvas.tabIndex;
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointermove', this.onPointerMove);
		canvas.addEventListener('wheel', this.onWheel, { passive: true });
		canvas.addEventListener('pointerup', this.onPointerUp);
		canvas.addEventListener('pointercancel', this.onPointerCancel);
		canvas.addEventListener('contextmenu', this.onContextMenu);
		container.addEventListener('keydown', this.onKeyDown);
	}

	setModel(model: FemModel): void {
		const first = !this.model;
		this.model = model;
		this.development = isUsablePath(this.developmentPath) ? new Development(model, this.developmentPath) : undefined;
		this.index = new ModelIndex(this.development?.model ?? model);
		if (this.development) {
			this.visible = new Set(this.development.elements);
		}
		this.rebuild();
		this.section.setModelBounds(new THREE.Box3().setFromObject(this.modelGroup));
		this.renderHighlight();
		this.renderResults();
		if (first) {
			void this.fit();
		}
	}

	setSelection(selection: FemSelection | undefined): void {
		if (sameSelection(selection, this.selection) && this.selectedElements.length <= 1) {
			return;
		}
		this.selection = selection;
		this.selectedElements = selection?.kind === 'element' ? [selection.id] : [];
		this.renderHighlight();
		// Only the labels follow the selection: the result's drawing stays.
		this.overlay?.setSelectedElement(this.selectedElement());
	}

	getSelection(): readonly string[] {
		return this.selectedElements.map(String);
	}

	setResults(view: FemResultView | undefined, display?: FemResultDisplay): void {
		const dimmed = !!this.results;
		this.results = view && display ? { view, display } : undefined;
		if (dimmed !== !!this.results) {
			this.applyDimming();
		}
		this.renderResults();
	}

	setTheme(theme: Partial<FemViewerTheme>): void {
		const next = { ...this.theme, ...usableTheme(theme) };
		if (sameTheme(next, this.theme)) {
			return; // the host restyles often; redrawing a large model each time would stall
		}
		this.theme = next;
		this.applyTheme();
		this.section.setColors('#3794ff', this.theme.selection);
		this.richMeasureOverlay.setColor(this.theme.selection);
		this.redrawRichMeasure();
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
	}

	setMeshNodes(shown: boolean): void {
		if (shown === this.meshNodes) {
			return;
		}
		this.meshNodes = shown;
		this.rebuild();
		this.renderHighlight();
	}

	setPointCloud(cloud: FemPointCloud | undefined): void {
		if (this.pointCloud) {
			this.world.scene.three.remove(this.pointCloud);
			this.pointCloud.geometry.dispose();
			(this.pointCloud.material as THREE.Material).dispose();
			this.pointCloud = undefined;
		}
		const n = cloud ? Math.floor(cloud.positions.length / 3) : 0;
		if (!cloud || !n) {
			return;
		}
		// Model space (Z up) to world space (Y up), as the model's nodes (toWorld, ndm 3).
		const world = new Float32Array(n * 3);
		for (let i = 0; i < n; i++) {
			world[i * 3] = cloud.positions[i * 3];
			world[i * 3 + 1] = cloud.positions[i * 3 + 2];
			world[i * 3 + 2] = -cloud.positions[i * 3 + 1];
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.BufferAttribute(world, 3));
		const colored = !!cloud.colors && cloud.colors.length >= n * 3;
		if (colored) {
			geometry.setAttribute('color', new THREE.BufferAttribute(Float32Array.from(Array.prototype.slice.call(cloud.colors, 0, n * 3) as number[]), 3));
		}
		const material = new THREE.PointsMaterial({
			size: cloud.size ?? 2,
			sizeAttenuation: false,
			vertexColors: colored,
			color: colored ? 0xffffff : subtleNodeColor(this.theme.node, this.theme.background),
			transparent: true,
			opacity: 0.6,
			depthWrite: false,
			clippingPlanes: this.section.clipPlanes,
		});
		this.pointCloud = new THREE.Points(geometry, material);
		this.pointCloud.renderOrder = -1; // under the model's linework
		this.world.scene.three.add(this.pointCloud);
	}

	setVisibleElements(elements: FemVisibleElements): void {
		const visible = elements && elements.size ? new Set(elements) : undefined;
		if (sameElements(visible, this.visible)) {
			return;
		}
		this.visible = visible;
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
	}

	setDevelopment(path: FemPlanPath | undefined): FemVisibleElements {
		const next = isUsablePath(path) ? path.map(p => [p[0], p[1]] as const) : undefined;
		if (JSON.stringify(next) === JSON.stringify(this.developmentPath)) {
			return this.development?.elements;
		}
		this.developmentPath = next;
		this.clearMeasurement(); // measured in the other drawing
		const model = this.model;
		if (!model) {
			return undefined;
		}
		this.development = next ? new Development(model, next) : undefined;
		this.index = new ModelIndex(this.development?.model ?? model);
		// Only the elements on the path; the host sets what it shows otherwise.
		this.visible = this.development ? new Set(this.development.elements) : undefined;
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
		return this.development?.elements;
	}

	setMeasureMode(mode: FemMeasureMode | ViewerMeasureMode): void {
		if (mode === this.measureMode) {
			return;
		}
		if (mode !== 'off' && this.section.isPickMode) {
			this.section.setPlanePickMode(false);
		}
		this.measureMode = mode;
		this.clearMeasurement();
		this.renderer.three.domElement.style.cursor = mode !== 'off' ? 'crosshair' : '';
		this.emitRichMeasureChanged();
	}

	clearMeasurement(): void {
		const had = this.measurePoints.length > 0 || this.richPoints.length > 0 || !!this.activeEdge;
		this.measurePoints = [];
		this.measureClosed = false;
		this.richPoints = [];
		this.activeEdge = undefined;
		this.previewSnap = undefined;
		this.measureOverlay.draw(undefined, undefined);
		this.redrawRichMeasure();
		if (had) {
			this.options.onMeasure?.(undefined);
			this.emitRichMeasureChanged();
		}
	}

	finishMeasureChain(): void {
		if (this.measureMode === 'chain' && this.richPoints.length >= 2) {
			this.measureEntries.push(buildChainEntry(`m-${++this.measureCounter}`, this.richPoints, true, 1));
			this.richPoints = [];
			this.redrawRichMeasure();
			this.emitRichMeasureChanged();
		}
	}

	removeMeasurement(id: string): void {
		const before = this.measureEntries.length;
		this.measureEntries = this.measureEntries.filter(e => e.id !== id);
		if (this.measureEntries.length !== before) {
			this.redrawRichMeasure();
			this.emitRichMeasureChanged();
		}
	}

	clearMeasurements(): void {
		this.measureEntries = [];
		this.clearMeasurement();
		this.emitRichMeasureChanged();
	}

	getMeasurements(): readonly MeasureEntry[] {
		return [...this.measureEntries];
	}

	// ───────────────────────────── R3: Section ─────────────────────────────

	toggleSectionBox(enabled?: boolean): boolean {
		return this.section.toggleBox(enabled);
	}

	setSectionBox(boundsMm: SectionBoxBounds | undefined): void {
		this.section.setBoxMm(boundsMm);
	}

	async sectionBoxFromSelection(): Promise<boolean> {
		const index = this.index;
		if (!index || !this.selectedElements.length) {
			return false;
		}
		const box = new THREE.Box3();
		for (const id of this.selectedElements) {
			const el = index.elements.get(id);
			if (!el) {
				continue;
			}
			for (const n of el.nodes) {
				const pt = index.point(n);
				if (pt) {
					box.expandByPoint(pt);
				}
			}
		}
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

	// ───────────────────────────── R3: Hide & Isolate ─────────────────────────────

	async hideSelectedTemp(): Promise<void> {
		if (!this.selectedElements.length) {
			return;
		}
		this.visibilityState = hideElementsTemp(this.visibilityState, this.selectedElements.map(String));
		this.selection = undefined;
		this.selectedElements = [];
		this.commitVisibility();
		this.options.onSelectionChanged?.(undefined, []);
	}

	async isolateSelectedTemp(): Promise<void> {
		if (!this.selectedElements.length) {
			return;
		}
		this.visibilityState = isolateElementsTemp(this.visibilityState, this.selectedElements.map(String));
		this.commitVisibility();
	}

	async hideSelectedCategoryTemp(): Promise<void> {
		const cats = this.selectedCategories();
		if (!cats.length) {
			return;
		}
		this.visibilityState = hideCategoriesTemp(this.visibilityState, cats);
		this.selection = undefined;
		this.selectedElements = [];
		this.commitVisibility();
		this.options.onSelectionChanged?.(undefined, []);
	}

	async isolateSelectedCategoryTemp(): Promise<void> {
		const cats = this.selectedCategories();
		if (!cats.length) {
			return;
		}
		this.visibilityState = isolateCategoriesTemp(this.visibilityState, cats);
		this.commitVisibility();
	}

	async resetTemporaryVisibility(): Promise<void> {
		this.visibilityState = resetTemporaryVisibility(this.visibilityState);
		this.commitVisibility();
	}

	async hideSelectedPermanent(): Promise<void> {
		if (!this.selectedElements.length) {
			return;
		}
		this.visibilityState = hideElementsPermanent(this.visibilityState, this.selectedElements.map(String));
		this.selection = undefined;
		this.selectedElements = [];
		this.commitVisibility();
		this.options.onSelectionChanged?.(undefined, []);
	}

	async unhideSelectedPermanent(): Promise<void> {
		if (!this.selectedElements.length) {
			return;
		}
		this.visibilityState = unhideElementsPermanent(this.visibilityState, this.selectedElements.map(String));
		this.commitVisibility();
	}

	async unhideAllPermanent(): Promise<void> {
		this.visibilityState = unhideAllPermanent(this.visibilityState);
		this.commitVisibility();
	}

	async applyTemporaryHideToPermanent(): Promise<void> {
		const elements = this.index?.model.elements ?? [];
		this.visibilityState = applyTemporaryToPermanent(
			this.visibilityState,
			elements.map(e => ({ id: String(e.id), category: e.type })),
		);
		this.commitVisibility();
	}

	async setRevealHidden(reveal: boolean): Promise<void> {
		if (this.visibilityState.revealHidden === reveal) {
			return;
		}
		this.visibilityState = { ...this.visibilityState, revealHidden: reveal };
		this.commitVisibility();
	}

	getVisibilityState(): VisibilityState {
		return this.visibilityState;
	}

	async setVisibilityState(state: Partial<VisibilityState>): Promise<void> {
		this.visibilityState = { ...this.visibilityState, ...state };
		this.commitVisibility();
	}

	private selectedCategories(): string[] {
		const index = this.index;
		if (!index) {
			return [];
		}
		const cats = new Set<string>();
		for (const id of this.selectedElements) {
			const el = index.elements.get(id);
			if (el?.type) {
				cats.add(el.type);
			}
		}
		return [...cats];
	}

	private commitVisibility(): void {
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
		this.options.onVisibilityChanged?.(this.visibilityState, summarizeVisibility(this.visibilityState));
	}

	async recordAnimation(options: FemRecordOptions = {}): Promise<Blob | undefined> {
		const canvas = this.renderer.three.domElement as HTMLCanvasElement | undefined;
		if (!canvas || this.results?.display.show !== 'deformed' || this.recording || typeof MediaRecorder === 'undefined') {
			return undefined;
		}
		const type = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(t => MediaRecorder.isTypeSupported(t));
		if (!type) {
			return undefined;
		}
		const fps = Math.max(1, Math.min(60, options.fps ?? 30));
		const seconds = Math.max(0.5, Math.min(60, options.seconds ?? 2 * ANIMATION_PERIOD_MS / 1000));
		this.recording = true;
		this.renderResults(); // moving, from rest
		const stream = canvas.captureStream(fps);
		try {
			const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 8_000_000 });
			const chunks: Blob[] = [];
			recorder.ondataavailable = e => {
				if (e.data.size) {
					chunks.push(e.data);
				}
			};
			const stopped = new Promise<void>(resolve => recorder.onstop = () => resolve());
			recorder.start(250);
			await new Promise(resolve => setTimeout(resolve, seconds * 1000));
			recorder.stop();
			await stopped;
			return chunks.length ? new Blob(chunks, { type: 'video/webm' }) : undefined;
		} finally {
			stream.getTracks().forEach(track => track.stop());
			this.recording = false;
			this.renderResults();
		}
	}

	async setCameraView(view: FemCameraView): Promise<void> {
		this.cameraView = view;
		const orthographic = view !== '3d';
		if ((this.camera.projection.current === 'Orthographic') !== orthographic) {
			await this.camera.projection.set(orthographic ? 'Orthographic' : 'Perspective');
		}
		// A plan or an elevation pans and zooms; only the 3D view orbits.
		this.camera.set(orthographic ? 'Plan' : 'Orbit');
		await this.fit();
	}

	async fit(): Promise<void> {
		const box = new THREE.Box3().setFromObject(this.modelGroup);
		if (box.isEmpty()) {
			return;
		}
		const sphere = box.getBoundingSphere(new THREE.Sphere());
		const radius = Math.max(sphere.radius, 1);
		// World Y is the model's Z (up); world -Z is the model's Y.
		const direction = this.cameraView === 'top' ? new THREE.Vector3(0, 1, 1e-4)
			: this.cameraView === 'front' ? new THREE.Vector3(0, 0, 1)
				: this.cameraView === 'side' ? new THREE.Vector3(1, 0, 0)
					: new THREE.Vector3(1, 0.8, 1.2);
		const eye = sphere.center.clone().add(direction.normalize().multiplyScalar(radius * 2.6));
		await this.camera.controls.setLookAt(eye.x, eye.y, eye.z, sphere.center.x, sphere.center.y, sphere.center.z, false);
		// Centred and filling the view, in 3D too (a fixed distance left a tall model small).
		await this.camera.controls.fitToSphere(new THREE.Sphere(sphere.center, radius * 1.05), false);
		this.untouched = true;
	}

	layout(): void {
		this.renderer.resize();
		this.camera.updateAspect();
		// Resized before the engineer moved the camera (the editor opened small, then grew):
		// fitted again, so the model is not left small and off-centre.
		if (this.untouched && this.model) {
			void this.fit();
		}
	}

	dispose(): void {
		const canvas = this.renderer.three.domElement;
		canvas?.removeEventListener('pointerdown', this.onPointerDown);
		canvas?.removeEventListener('pointermove', this.onPointerMove);
		canvas?.removeEventListener('wheel', this.onWheel);
		canvas?.removeEventListener('pointerup', this.onPointerUp);
		canvas?.removeEventListener('pointercancel', this.onPointerCancel);
		canvas?.removeEventListener('contextmenu', this.onContextMenu);
		this.container.removeEventListener('keydown', this.onKeyDown);
		this.section.dispose();
		this.measureOverlay.dispose();
		this.richMeasureOverlay.dispose();
		this.setPointCloud(undefined);
		this.clearGroup(this.modelGroup);
		this.clearGroup(this.revealGroup);
		this.clearGroup(this.highlight);
		this.clearResults();
		this.components.dispose();
	}

	private applyTheme(): void {
		this.world.scene.config.backgroundColor = new THREE.Color(this.theme.background);
		this.grid.config.color = new THREE.Color(this.theme.grid);
	}

	private applyClipping(): void {
		this.section.applyToObject(this.modelGroup);
		this.section.applyToObject(this.revealGroup);
		this.section.applyToObject(this.highlight);
		this.section.applyToObject(this.resultGroup);
		if (this.pointCloud) {
			this.section.applyToObject(this.pointCloud);
		}
	}

	private rebuild(): void {
		this.clearGroup(this.modelGroup);
		this.clearGroup(this.revealGroup);
		this.pickTargets.length = 0;
		this.members = undefined;
		this.solidEdges = undefined;
		this.nodes = undefined;
		this.faces = undefined;
		this.revealMembers = undefined;
		this.revealMemberIds = [];
		this.revealFaces = undefined;
		this.revealFaceIds = [];
		this.revealedElementIds.clear();
		this.hiddenElementIds.clear();
		const index = this.index;
		if (!index) {
			return;
		}
		const model = index.model;
		const world = index.world;
		const scale = index.size;

		const externalHidden = new Set<string>();
		if (this.visible) {
			for (const element of model.elements) {
				if (!this.visible.has(element.id)) {
					externalHidden.add(String(element.id));
				}
			}
		}
		const visResult = computeElementVisibility(
			model.elements.map(e => ({ id: String(e.id), category: e.type })),
			this.visibilityState,
			externalHidden,
		);
		for (const id of visResult.hidden) {
			this.hiddenElementIds.add(Number(id));
		}
		for (const id of visResult.revealed) {
			this.revealedElementIds.add(Number(id));
		}

		// Members: every element is drawn as its edge loop (2-node elements as one segment).
		const positions = new Floats();
		this.memberIds = [];
		const revealLinePos = new Floats();
		this.revealMemberIds = [];
		const shown = (e: FemElement) => !this.hiddenElementIds.has(e.id) && !this.revealedElementIds.has(e.id);
		const isRevealed = (e: FemElement) => this.revealedElementIds.has(e.id);
		const solids = model.elements.filter(e => e.type === 'Solid' && !this.hiddenElementIds.has(e.id) && !this.revealedElementIds.has(e.id));
		for (const element of model.elements) {
			if (element.type === 'Solid' || EMBED.test(element.name ?? '')) {
				continue;
			}
			const visibleNormal = shown(element);
			const visibleReveal = isRevealed(element);
			if (!visibleNormal && !visibleReveal) {
				continue;
			}
			const n = element.nodes;
			const segments = n.length < 2 ? 0 : n.length === 2 ? 1 : n.length;
			for (let k = 0; k < segments; k++) {
				const a = index.offset(n[k]);
				const b = index.offset(n[(k + 1) % n.length]);
				if (a < 0 || b < 0) {
					continue;
				}
				if (visibleNormal) {
					positions.pushFrom(world, a, 3);
					positions.pushFrom(world, b, 3);
					this.memberIds.push(element.id);
				} else {
					revealLinePos.pushFrom(world, a, 3);
					revealLinePos.pushFrom(world, b, 3);
					this.revealMemberIds.push(element.id);
				}
			}
		}
		if (positions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', positions.attribute());
			this.members = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: this.theme.member }));
			this.modelGroup.add(this.members);
			this.pickTargets.push(this.members);
		}
		if (revealLinePos.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', revealLinePos.attribute());
			this.revealMembers = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: REVEAL_COLOR, transparent: true, opacity: 0.85 }));
			this.revealGroup.add(this.revealMembers);
			this.pickTargets.push(this.revealMembers);
		}

		if (solids.length) {
			const faces = outerFaces(solids);
			const points = new Floats();
			const sharing = new Map<string, { a: THREE.Vector3; b: THREE.Vector3; normals: THREE.Vector3[] }>();
			for (const face of faces) {
				const pts = face.nodes.map(id => index.point(id)).filter((p): p is THREE.Vector3 => !!p);
				if (pts.length !== 3) {
					continue;
				}
				pts.forEach(p => points.pushVector(p));
				const normal = pts[1].clone().sub(pts[0]).cross(pts[2].clone().sub(pts[0])).normalize();
				face.nodes.forEach((a, k) => {
					const b = face.nodes[(k + 1) % 3];
					const key = a < b ? `${a}-${b}` : `${b}-${a}`;
					const entry = sharing.get(key) ?? { a: pts[k], b: pts[(k + 1) % 3], normals: [] };
					entry.normals.push(normal);
					sharing.set(key, entry);
				});
			}
			const edges = new Floats();
			for (const { a, b, normals: [n1, n2] } of sharing.values()) {
				if (!n2 || Math.abs(n1.dot(n2)) < 0.94) {
					edges.pushVector(a);
					edges.pushVector(b);
				}
			}
			const surface = new THREE.BufferGeometry();
			surface.setAttribute('position', points.attribute());
			this.modelGroup.add(new THREE.Mesh(surface, new THREE.MeshBasicMaterial({
				color: this.theme.member, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false,
			})));
			const lines = new THREE.BufferGeometry();
			lines.setAttribute('position', edges.attribute());
			this.solidEdges = new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color: this.theme.member, transparent: true }));
			this.modelGroup.add(this.solidEdges);
		}
		this.applyDimming();

		// Shell-like elements (3+ nodes) also get a translucent face so they read as areas; a click
		// on the face selects the element.
		const facePositions = new Floats();
		this.faceIds = [];
		const revealFacePositions = new Floats();
		this.revealFaceIds = [];
		const corners: number[] = [];
		for (const element of model.elements) {
			if (element.nodes.length < 3 || element.type === 'Solid') {
				continue;
			}
			const visibleNormal = shown(element);
			const visibleReveal = isRevealed(element);
			if (!visibleNormal && !visibleReveal) {
				continue;
			}
			corners.length = 0;
			for (const id of element.nodes) {
				const o = index.offset(id);
				if (o >= 0) {
					corners.push(o);
				}
			}
			for (let i = 1; i < corners.length - 1; i++) {
				if (visibleNormal) {
					facePositions.pushFrom(world, corners[0], 3);
					facePositions.pushFrom(world, corners[i], 3);
					facePositions.pushFrom(world, corners[i + 1], 3);
					this.faceIds.push(element.id);
				} else {
					revealFacePositions.pushFrom(world, corners[0], 3);
					revealFacePositions.pushFrom(world, corners[i], 3);
					revealFacePositions.pushFrom(world, corners[i + 1], 3);
					this.revealFaceIds.push(element.id);
				}
			}
		}
		if (facePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', facePositions.attribute());
			this.faces = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				color: this.theme.member, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false,
			}));
			this.modelGroup.add(this.faces);
			this.pickTargets.push(this.faces);
		}
		if (revealFacePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', revealFacePositions.attribute());
			this.revealFaces = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				color: REVEAL_COLOR, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false,
			}));
			this.revealGroup.add(this.revealFaces);
			this.pickTargets.push(this.revealFaces);
		}

		// Nodes only solids use are not marked (or picked): a solid's mesh would bury it in them.
		const solidOnly = new Set<number>();
		if (solids.length) {
			solids.forEach(e => e.nodes.forEach(n => solidOnly.add(n)));
			for (const element of model.elements) {
				if (element.type !== 'Solid') {
					element.nodes.forEach(n => solidOnly.delete(n));
				}
			}
		}

		// Nodes: of the elements shown.
		const hasFilter = this.visible !== undefined || this.hiddenElementIds.size > 0 || this.revealedElementIds.size > 0;
		let used: Set<number> | undefined;
		if (hasFilter) {
			used = new Set();
			for (const element of model.elements) {
				if (!this.hiddenElementIds.has(element.id)) {
					element.nodes.forEach(n => used!.add(n));
				}
			}
		}
		const meshOnly = this.meshNodes ? new Set<number>() : meshNodeIds(model);
		const nodePositions = new Floats();
		this.nodeIds = [];
		model.nodes.forEach((node, i) => {
			if (!solidOnly.has(node.id) && !meshOnly.has(node.id) && (!used || used.has(node.id))) {
				nodePositions.pushFrom(world, i * 3, 3);
				this.nodeIds.push(node.id);
			}
		});
		if (nodePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', nodePositions.attribute());
			this.nodes = new THREE.Points(geometry, roundPointMaterial(subtleNodeColor(this.theme.node, this.theme.background), 5));
			this.modelGroup.add(this.nodes);
			this.pickTargets.push(this.nodes);
		}

		// #303: released member ends (`<member>/pin` links: a dot just inside the member's end) and
		// point springs (`<id>/spring` links to a fixed ground node: a coil post under the joint,
		// not the ground node's fixed-support block).
		const grounds = new Set<number>();
		const springAt: number[] = [];
		const releaseAt: number[] = [];
		const linkName = (e: { readonly name?: string }) => (e.name ?? '').split('#')[0];
		const frameAt = new Map<number, number>(); // twin node -> the other end of its member
		for (const element of model.elements) {
			if (element.nodes.length === 2 && element.type !== 'ZeroLength') {
				frameAt.set(element.nodes[0], element.nodes[1]);
				frameAt.set(element.nodes[1], element.nodes[0]);
			}
		}
		for (const element of model.elements) {
			if (element.type !== 'ZeroLength' || element.nodes.length !== 2) {
				continue;
			}
			const [joint, other] = element.nodes;
			const at = index.offset(joint);
			if (at < 0 || used && !used.has(joint)) {
				continue;
			}
			if (linkName(element).endsWith('/spring')) {
				grounds.add(other);
				springAt.push(at);
			} else if (linkName(element).endsWith('/pin')) {
				const far = index.offset(frameAt.get(other) ?? -1);
				const point = [world[at], world[at + 1], world[at + 2]];
				if (far >= 0) {
					const d = [world[far] - point[0], world[far + 1] - point[1], world[far + 2] - point[2]];
					const length = Math.hypot(d[0], d[1], d[2]) || 1;
					const step = Math.min(scale * 0.02, length * 0.2) / length;
					point[0] += d[0] * step;
					point[1] += d[1] * step;
					point[2] += d[2] * step;
				}
				releaseAt.push(...point);
			}
		}
		const addMarks = (positions: number[], geometry: THREE.BufferGeometry, material: THREE.Material) => {
			const count = positions.length / 3;
			if (!count) {
				geometry.dispose();
				material.dispose();
				return;
			}
			const marks = new THREE.InstancedMesh(geometry, material, count);
			const matrix = new THREE.Matrix4();
			for (let k = 0; k < count; k++) {
				marks.setMatrixAt(k, matrix.makeTranslation(positions[k * 3], positions[k * 3 + 1], positions[k * 3 + 2]));
			}
			marks.computeBoundingSphere();
			this.modelGroup.add(marks);
		};
		// A hinge: a dot of fixed screen size in the supports' colour, drawn over the members and
		// slabs so it reads at any zoom (a model-sized mark vanished on a whole-building view).
		if (releaseAt.length) {
			const hinges = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(releaseAt, 3)), roundPointMaterial(this.theme.support, 9, { depthTest: false }));
			hinges.renderOrder = 2;
			this.modelGroup.add(hinges);
		}
		// A spring: an open wire post below the joint (world space is Y up), and a dot on the joint.
		const springPoints = springAt.flatMap(at => [world[at], world[at + 1], world[at + 2]]);
		const coil = new THREE.CylinderGeometry(scale * 0.012, scale * 0.012, scale * 0.06, 6, 8, true);
		coil.translate(0, -scale * 0.03, 0);
		addMarks(springPoints, coil, new THREE.MeshBasicMaterial({ color: this.theme.support, wireframe: true }));
		if (springPoints.length) {
			const dots = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(springPoints, 3)), roundPointMaterial(this.theme.support, 9, { depthTest: false }));
			dots.renderOrder = 2;
			this.modelGroup.add(dots);
		}

		const fixed: number[] = [];
		const pinned: number[] = [];
		model.nodes.forEach((node, i) => {
			if (grounds.has(node.id)) {
				return;
			}
			if (node.restraint?.some(Boolean) && !solidOnly.has(node.id) && (!used || used.has(node.id))) {
				(node.restraint.length >= 6 && node.restraint.every(Boolean) ? fixed : pinned).push(i);
			}
		});
		const addSupports = (nodes: number[], geometry: THREE.BufferGeometry) => {
			if (!nodes.length) {
				geometry.dispose();
				return;
			}
			const supports = new THREE.InstancedMesh(geometry, new THREE.MeshBasicMaterial({ color: this.theme.support }), nodes.length);
			const matrix = new THREE.Matrix4();
			nodes.forEach((i, k) => supports.setMatrixAt(k, matrix.makeTranslation(world[i * 3], world[i * 3 + 1], world[i * 3 + 2])));
			supports.computeBoundingSphere();
			this.modelGroup.add(supports);
		};
		const pyramid = new THREE.ConeGeometry(scale * 0.025, scale * 0.04, 4);
		pyramid.translate(0, -scale * 0.02, 0);
		addSupports(pinned, pyramid);
		const block = new THREE.BoxGeometry(scale * 0.04, scale * 0.012, scale * 0.04);
		block.translate(0, -scale * 0.006, 0);
		addSupports(fixed, block);

		this.applyClipping();
	}

	/** Under a result the model steps back. */
	private applyDimming(): void {
		const dimmed = !!this.results;
		const members = this.members?.material;
		if (members && members.transparent !== dimmed) {
			members.transparent = dimmed;
			members.opacity = dimmed ? 0.35 : 1;
			members.needsUpdate = true;
		}
		if (this.solidEdges) {
			this.solidEdges.material.opacity = dimmed ? 0.15 : 0.35;
		}
		const nodes = this.nodes?.material as THREE.Material | undefined;
		if (nodes && nodes.transparent !== dimmed) {
			nodes.transparent = dimmed;
			nodes.opacity = dimmed ? 0.35 : 1;
			nodes.needsUpdate = true;
		}
	}

	private clearResults(): void {
		if (this.animation !== undefined) {
			cancelAnimationFrame(this.animation);
			this.animation = undefined;
		}
		if (this.overlay) {
			this.resultGroup.remove(this.overlay.group);
			this.overlay.dispose();
			this.overlay = undefined;
		}
	}

	private renderResults(): void {
		this.clearResults();
		const index = this.index;
		if (!index || !this.results) {
			return;
		}
		const theme = this.theme;
		const development = this.development;
		let view = this.results.view;
		let display = this.results.display;
		if (development) {
			view = development.results(view);
			display = development.display(display);
		}
		if (this.recording) {
			display = { ...display, animate: true, animateAny: true };
		}
		const oscillates = view.kind === 'modal';
		const visibleOverride = this.computeEffectiveVisible();
		const overlay = new ResultOverlay(index, view, display, {
			deformed: theme.deformed,
			positive: theme.positive,
			negative: theme.negative,
			reaction: theme.reaction,
			pass: theme.pass,
			warn: theme.warn,
			fail: theme.fail,
			label: theme.node,
			labelBackground: theme.background,
		}, this.selectedElement(), visibleOverride);
		this.overlay = overlay;
		this.resultGroup.add(overlay.group);
		this.section.applyToObject(this.resultGroup);
		if (overlay.isAnimated) {
			const start = performance.now();
			const step = (now: number) => {
				// A mode shape swings both ways; a static shape grows from rest and back.
				const angle = (now - start) / ANIMATION_PERIOD_MS * 2 * Math.PI;
				overlay.setPhase(oscillates ? Math.sin(angle) : (1 - Math.cos(angle)) / 2);
				this.animation = requestAnimationFrame(step);
			};
			this.animation = requestAnimationFrame(step);
		}
	}

	private computeEffectiveVisible(): FemVisibleElements {
		if (!this.index) {
			return this.visible;
		}
		if (!this.hiddenElementIds.size && !this.revealedElementIds.size) {
			return this.visible;
		}
		const out = new Set<number>();
		for (const el of this.index.model.elements) {
			if ((!this.visible || this.visible.has(el.id)) && !this.hiddenElementIds.has(el.id)) {
				out.add(el.id);
			}
		}
		return out;
	}

	private renderHighlight(): void {
		this.clearGroup(this.highlight);
		const index = this.index;
		if (!index) {
			return;
		}
		const color = this.theme.selection;
		if (this.selection?.kind === 'node') {
			const point = index.point(this.selection.id);
			if (point) {
				const geometry = new THREE.BufferGeometry().setFromPoints([point]);
				this.highlight.add(new THREE.Points(geometry, roundPointMaterial(color, 10, { depthTest: false })));
			}
			this.section.applyToObject(this.highlight);
			return;
		}
		const ids = this.selectedElements.length
			? this.selectedElements
			: (this.selection?.kind === 'element' ? [this.selection.id] : []);
		if (!ids.length) {
			return;
		}
		const pts: THREE.Vector3[] = [];
		for (const id of ids) {
			const element = index.elements.get(id);
			if (!element) {
				continue;
			}
			for (const [a, b] of this.edges(element)) {
				const pa = index.point(a);
				const pb = index.point(b);
				if (pa && pb) {
					pts.push(pa, pb);
				}
			}
		}
		if (pts.length) {
			const geometry = new THREE.BufferGeometry().setFromPoints(pts);
			this.highlight.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, depthTest: false })));
			this.section.applyToObject(this.highlight);
		}
	}

	private isRichMeasureMode(mode: ViewerMeasureMode): mode is 'chain' | 'pointToFace' | 'edgeAngle' {
		return mode === 'chain' || mode === 'pointToFace' || mode === 'edgeAngle';
	}

	private handleClick(e: PointerEvent): void {
		const down = this.pointerDown;
		this.pointerDown = undefined;
		if (this.section.consumeJustDragged()) {
			return;
		}
		// Ignore orbit/pan drags; only a stationary click selects.
		if (e.button !== 0 || !down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4 || !this.index) {
			return;
		}
		if (this.section.isPickMode) {
			const hit = this.raycastGeometry(e.clientX, e.clientY);
			if (hit.facePoint && hit.faceNormal) {
				this.section.addPlaneFromSceneHit(hit.facePoint, hit.faceNormal);
				this.applyClipping();
			}
			return;
		}
		if (this.measureMode !== 'off') {
			if (this.isRichMeasureMode(this.measureMode)) {
				this.handleRichMeasureClick(e.clientX, e.clientY);
			} else {
				const snap = this.snapAt(e.clientX, e.clientY, false);
				if (snap) {
					const point = toSceneM(snap.point);
					this.addMeasurePoint(fromWorld(point));
					if (this.measureMode === 'distance' && this.measurePoints.length === 0) {
						// Complete distance already recorded by addMeasurePoint -> mirror to rich list too.
					}
				}
			}
			return;
		}
		const hit = this.raycastGeometry(e.clientX, e.clientY);
		if (hit.nodeId !== undefined) {
			const next: FemSelection = { kind: 'node', id: this.development?.original(hit.nodeId) ?? hit.nodeId };
			this.selectedElements = [];
			if (!sameSelection(next, this.selection)) {
				this.selection = next;
				this.renderHighlight();
				this.options.onSelectionChanged?.(next, []);
			}
			return;
		}
		const elementId = hit.elementId;
		if (e.ctrlKey || e.metaKey || e.shiftKey) {
			if (elementId !== undefined) {
				if (this.selectedElements.includes(elementId)) {
					this.selectedElements = this.selectedElements.filter(id => id !== elementId);
				} else {
					this.selectedElements = [...this.selectedElements, elementId];
				}
			}
		} else {
			this.selectedElements = elementId !== undefined ? [elementId] : [];
		}
		const primaryId = this.selectedElements[this.selectedElements.length - 1];
		const next: FemSelection | undefined = primaryId !== undefined ? { kind: 'element', id: primaryId } : undefined;
		this.selection = next;
		this.renderHighlight();
		this.options.onSelectionChanged?.(next, this.selectedElements.map(String));
	}

	private raycastGeometry(clientX: number, clientY: number): {
		nodeId?: number;
		nodePoint?: THREE.Vector3;
		elementId?: number;
		memberPoint?: THREE.Vector3;
		memberEdge?: [THREE.Vector3, THREE.Vector3];
		facePoint?: THREE.Vector3;
		faceNormal?: THREE.Vector3;
		faceVertices?: [THREE.Vector3, THREE.Vector3, THREE.Vector3];
	} {
		const index = this.index;
		if (!index) {
			return {};
		}
		const rect = this.renderer.three.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((clientX - rect.left) / rect.width) * 2 - 1,
			-((clientY - rect.top) / rect.height) * 2 + 1,
		);
		const threshold = index.size * 0.01;
		this.raycaster.params.Line = { threshold };
		this.raycaster.params.Points = { threshold: threshold * 0.6 };
		this.raycaster.setFromCamera(ndc, this.camera.three);
		const hits = this.raycaster.intersectObjects(this.pickTargets, false).filter(h => this.isPointInsideSection(h.point));
		const nodeHit = hits.find(h => h.object === this.nodes && h.index !== undefined);
		const memberHit = hits.find(h => (h.object === this.members || h.object === this.revealMembers) && h.index !== undefined);
		const faceHit = hits.find(h => (h.object === this.faces || h.object === this.revealFaces) && h.faceIndex !== undefined && h.faceIndex !== null);

		const out: {
			nodeId?: number;
			nodePoint?: THREE.Vector3;
			elementId?: number;
			memberPoint?: THREE.Vector3;
			memberEdge?: [THREE.Vector3, THREE.Vector3];
			facePoint?: THREE.Vector3;
			faceNormal?: THREE.Vector3;
			faceVertices?: [THREE.Vector3, THREE.Vector3, THREE.Vector3];
		} = {};
		if (nodeHit) {
			out.nodeId = this.nodeIds[nodeHit.index!];
			out.nodePoint = index.point(out.nodeId);
		}
		if (memberHit) {
			const isReveal = memberHit.object === this.revealMembers;
			const mesh = isReveal ? this.revealMembers! : this.members!;
			const ids = isReveal ? this.revealMemberIds : this.memberIds;
			out.elementId = ids[Math.floor(memberHit.index! / 2)];
			const seg = this.memberSegment(mesh, memberHit.index!);
			if (seg) {
				out.memberEdge = seg;
				out.memberPoint = this.closestOnSegment(seg[0], seg[1], this.raycaster.ray);
			}
		}
		if (faceHit) {
			const isReveal = faceHit.object === this.revealFaces;
			const mesh = isReveal ? this.revealFaces! : this.faces!;
			const ids = isReveal ? this.revealFaceIds : this.faceIds;
			out.elementId ??= ids[faceHit.faceIndex!];
			out.facePoint = faceHit.point.clone();
			const pos = mesh.geometry.getAttribute('position');
			if (pos && faceHit.faceIndex !== undefined && faceHit.faceIndex !== null) {
				const base = faceHit.faceIndex * 3;
				const v0 = new THREE.Vector3().fromBufferAttribute(pos, base);
				const v1 = new THREE.Vector3().fromBufferAttribute(pos, base + 1);
				const v2 = new THREE.Vector3().fromBufferAttribute(pos, base + 2);
				out.faceVertices = [v0, v1, v2];
				const normal = v1.clone().sub(v0).cross(v2.clone().sub(v0)).normalize();
				if (normal.dot(this.raycaster.ray.direction) > 0) {
					normal.negate();
				}
				out.faceNormal = normal;
			}
		}
		return out;
	}

	private isPointInsideSection(p: THREE.Vector3): boolean {
		for (const plane of this.section.clipPlanes) {
			if (plane.distanceToPoint(p) < -1e-4) {
				return false;
			}
		}
		return true;
	}

	private snapAt(clientX: number, clientY: number, requireEdge: boolean): SnapResult | undefined {
		const hit = this.raycastGeometry(clientX, clientY);
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
		const pushScene = (worldPt: THREE.Vector3, kind: SnapKind, worldNormal?: THREE.Vector3, worldEdge?: readonly [THREE.Vector3, THREE.Vector3]) => {
			const proj = project(worldPt);
			if (!proj.visible) {
				return;
			}
			candidates.push({
				point: toProjectMm(worldPt),
				kind,
				screenDistancePx: Math.hypot(proj.x - clientX, proj.y - clientY),
				depth: proj.depth,
				normal: worldNormal ? sceneNormalToProject([worldNormal.x, worldNormal.y, worldNormal.z]) : undefined,
				edge: worldEdge ? [toProjectMm(worldEdge[0]), toProjectMm(worldEdge[1])] : undefined,
			});
		};

		if (hit.nodePoint) {
			pushScene(hit.nodePoint, 'vertex');
		}
		if (hit.memberEdge && hit.memberPoint) {
			const [a, b] = hit.memberEdge;
			pushScene(a, 'vertex', undefined, [a, b]);
			pushScene(b, 'vertex', undefined, [a, b]);
			pushScene(a.clone().add(b).multiplyScalar(0.5), 'midpoint', undefined, [a, b]);
			pushScene(hit.memberPoint, 'edge', undefined, [a, b]);
		}
		if (hit.facePoint && hit.faceNormal) {
			pushScene(hit.facePoint, 'face', hit.faceNormal);
			if (hit.faceVertices) {
				const verts = hit.faceVertices;
				let bestEdge: [THREE.Vector3, THREE.Vector3] | undefined;
				let bestDist = Infinity;
				const hp = toProjectMm(hit.facePoint);
				for (let i = 0; i < 3; i++) {
					const a = verts[i];
					const b = verts[(i + 1) % 3];
					pushScene(a, 'vertex', hit.faceNormal);
					pushScene(a.clone().add(b).multiplyScalar(0.5), 'midpoint', hit.faceNormal, [a, b]);
					const cp = closestPointOnSegment(hp, toProjectMm(a), toProjectMm(b));
					const d = distance3(hp, cp);
					if (d < bestDist) {
						bestDist = d;
						bestEdge = [a, b];
					}
				}
				if (bestEdge) {
					pushScene(hit.facePoint, 'edge', hit.faceNormal, bestEdge);
				}
			}
		}

		if (requireEdge) {
			const edgeOnly = candidates.filter(c => c.edge !== undefined);
			if (!edgeOnly.length) {
				return undefined;
			}
			edgeOnly.sort((a, b) => a.screenDistancePx - b.screenDistancePx || a.depth - b.depth);
			const chosen = edgeOnly[0];
			return { point: chosen.point, kind: 'edge', normal: chosen.normal, edge: chosen.edge };
		}
		return chooseSnap(candidates);
	}

	private handleRichMeasureClick(clientX: number, clientY: number): void {
		const snap = this.snapAt(clientX, clientY, this.measureMode === 'edgeAngle');
		if (!snap) {
			return;
		}
		this.previewSnap = snap;
		if (this.measureMode === 'chain') {
			this.richPoints.push(snap.point);
		} else if (this.measureMode === 'pointToFace') {
			if (!this.richPoints.length) {
				this.richPoints.push(snap.point);
			} else if (snap.normal) {
				this.measureEntries.push(buildPointToFaceEntry(`m-${++this.measureCounter}`, this.richPoints[0], snap.point, snap.normal, 1));
				this.richPoints = [];
			}
		} else if (this.measureMode === 'edgeAngle') {
			if (!snap.edge) {
				return;
			}
			if (!this.activeEdge) {
				this.activeEdge = snap.edge;
			} else {
				this.measureEntries.push(buildEdgeAngleEntry(`m-${++this.measureCounter}`, this.activeEdge, snap.edge));
				this.activeEdge = undefined;
			}
		}
		this.redrawRichMeasure();
		this.emitRichMeasureChanged();
	}

	private redrawRichMeasure(): void {
		this.richMeasureOverlay.drawEntries(
			this.measureEntries,
			toSceneM,
			this.richPoints,
			this.isRichMeasureMode(this.measureMode) ? this.measureMode : 'off',
			this.previewSnap,
			this.activeEdge,
			1,
		);
	}

	private emitRichMeasureChanged(): void {
		let liveLabel: string | undefined;
		if (this.richPoints.length && this.previewSnap && this.measureMode === 'chain') {
			const last = this.richPoints[this.richPoints.length - 1];
			liveLabel = `${Math.round(distance3(last, this.previewSnap.point))} mm`;
		} else if (this.measureMode === 'pointToFace' && this.richPoints.length === 1 && this.previewSnap?.normal) {
			liveLabel = buildPointToFaceEntry('preview', this.richPoints[0], this.previewSnap.point, this.previewSnap.normal, 1).label;
		} else if (this.measureMode === 'edgeAngle' && this.activeEdge && this.previewSnap?.edge) {
			liveLabel = buildEdgeAngleEntry('preview', this.activeEdge, this.previewSnap.edge).label;
		} else if (this.measureMode === 'chain' && this.richPoints.length >= 2) {
			const last = this.richPoints[this.richPoints.length - 1];
			const prev = this.richPoints[this.richPoints.length - 2];
			liveLabel = `${Math.round(distance3(prev, last))} mm`;
		} else if (this.measureMode === 'distance' && this.measurePoints.length === 1 && this.previewSnap) {
			const p0 = toProjectMm(new THREE.Vector3(this.measurePoints[0][0], this.measurePoints[0][2], -this.measurePoints[0][1]));
			liveLabel = `${Math.round(distance3(p0, this.previewSnap.point))} mm`;
		}
		this.options.onMeasureChanged?.([...this.measureEntries], {
			mode: this.measureMode,
			snap: this.previewSnap?.kind,
			pendingPoints: this.activeEdge ? 1 : (this.richPoints.length || this.measurePoints.length),
			liveLabel,
		});
	}

	private memberSegment(mesh: THREE.LineSegments, index: number): [THREE.Vector3, THREE.Vector3] | undefined {
		const position = mesh.geometry.getAttribute('position');
		if (!position) {
			return undefined;
		}
		const k = Math.floor(index / 2) * 2;
		return [
			new THREE.Vector3().fromBufferAttribute(position, k),
			new THREE.Vector3().fromBufferAttribute(position, k + 1),
		];
	}

	private closestOnSegment(a: THREE.Vector3, b: THREE.Vector3, ray: THREE.Ray): THREE.Vector3 {
		const onSegment = new THREE.Vector3();
		ray.distanceSqToSegment(a, b, undefined, onSegment);
		return onSegment;
	}

	private addMeasurePoint(point: FemMeasurePoint): void {
		const mode = this.measureMode;
		if (mode !== 'distance' && mode !== 'angle' && mode !== 'area') {
			return;
		}
		const needed = mode === 'distance' ? 2 : mode === 'angle' ? 3 : Infinity;
		if (this.measureClosed || this.measurePoints.length >= needed) {
			// The last measurement is done: this click starts the next.
			this.measurePoints = [];
			this.measureClosed = false;
		}
		const points = this.measurePoints;
		const first = points[0];
		const snap = (this.index?.size ?? 1) * 0.002;
		if (mode === 'area' && points.length >= 3 && first && Math.hypot(point[0] - first[0], point[1] - first[1], point[2] - first[2]) <= snap) {
			this.measureClosed = true; // back on the first point: the polygon is closed
		} else {
			points.push(point);
		}
		const measurement = measure(mode, points, mode === 'area' ? this.measureClosed : points.length >= needed);
		if (mode === 'distance' && measurement.complete && points.length >= 2) {
			this.measureOverlay.draw(undefined, undefined);
			const p0 = toProjectMm(new THREE.Vector3(points[0][0], points[0][2], -points[0][1]));
			const p1 = toProjectMm(new THREE.Vector3(points[1][0], points[1][2], -points[1][1]));
			this.measureEntries.push(buildDistanceEntry(`m-${++this.measureCounter}`, p0, p1, 1));
			this.redrawRichMeasure();
			this.emitRichMeasureChanged();
		} else {
			this.measureOverlay.draw(measurement, this.measureText(measurement));
			if (mode === 'angle' && measurement.complete && measurement.angle !== undefined) {
				const ptsMm = points.map(pt => toProjectMm(new THREE.Vector3(pt[0], pt[2], -pt[1])));
				this.measureEntries.push({
					id: `m-${++this.measureCounter}`,
					mode: 'angle',
					points: ptsMm,
					complete: true,
					label: `${measurement.angle.toFixed(1)}°`,
					summary: `${measurement.angle.toFixed(2)}°`,
					angleDeg: measurement.angle,
				});
				this.emitRichMeasureChanged();
			} else if (mode === 'area' && measurement.complete && measurement.area !== undefined) {
				const ptsMm = points.map(pt => toProjectMm(new THREE.Vector3(pt[0], pt[2], -pt[1])));
				this.measureEntries.push({
					id: `m-${++this.measureCounter}`,
					mode: 'area',
					points: ptsMm,
					complete: true,
					label: `${measurement.area.toFixed(2)} m²`,
					summary: `${measurement.area.toFixed(3)} m² (perimeter ${Math.round((measurement.perimeter ?? 0) * 1000)} mm)`,
					area: measurement.area,
					perimeter: measurement.perimeter,
				});
				this.emitRichMeasureChanged();
			} else {
				this.emitRichMeasureChanged();
			}
		}
		this.options.onMeasure?.(measurement);
	}

	private measureText(m: FemMeasurement): string | undefined {
		const unit = this.options.lengthUnit ?? 'm';
		if (m.length !== undefined) {
			return `${m.length.toFixed(3)} ${unit}`;
		}
		if (m.angle !== undefined) {
			return `${m.angle.toFixed(1)}°`;
		}
		if (m.area !== undefined && m.points.length >= 3) {
			return `${m.area.toFixed(2)} ${unit}²`;
		}
		return undefined;
	}

	private edges(element: FemElement): [number, number][] {
		const n = element.nodes;
		if (n.length < 2) {
			return [];
		}
		if (n.length === 2) {
			return [[n[0], n[1]]];
		}
		return n.map((id, i) => [id, n[(i + 1) % n.length]] as [number, number]);
	}

	/** 1 under the perspective camera; under the orthographic one, the view's world height per its NDC height times the perspective's focal factor. */
	private labelScale(): number {
		if (this.camera.projection.current !== 'Orthographic') {
			return 1;
		}
		const ortho = this.camera.threeOrtho;
		const focal = 1 / Math.tan(THREE.MathUtils.degToRad(this.camera.threePersp.fov) / 2);
		return focal * (ortho.top - ortho.bottom) / (2 * ortho.zoom);
	}

	private selectedElement(): number | undefined {
		return this.selection?.kind === 'element' ? this.selection.id : undefined;
	}

	private clearGroup(group: THREE.Group): void {
		for (const child of [...group.children]) {
			group.remove(child);
			if (child instanceof THREE.InstancedMesh) {
				child.dispose(); // its instance matrices
			}
			const mesh = child as THREE.Mesh;
			mesh.geometry?.dispose();
			const material = mesh.material;
			if (Array.isArray(material)) {
				material.forEach(m => m.dispose());
			} else {
				material?.dispose();
			}
		}
	}
}

export function createFemViewer(container: HTMLElement, options: FemViewerOptions = {}): FemViewer {
	return new FemViewerImpl(container, options);
}

export { ARCHITECTURE_PREFIX, createBuildingViewer, type BuildingLayer, type BuildingRenderPreset, type BuildingViewer, type BuildingViewerOptions, type BuildingViewerTheme, type BuildingViewPreset, type MeasureStatus } from './building.js';
export { constructionState, RENDER_PRESETS, type ConstructionState } from './render.js';
export { setTrustedTypesHost, type TrustedTypesHost } from './trustedTypes.js';
export { createStructureModeler, type ModelerEntity, type ModelerGhost, type ModelerHit, type ModelerScene, type ModelerTheme, type ModelerView, type ModelPoint, type StructureModeler, type StructureModelerOptions } from './modeler.js';
export {
	boxToClipPlanes,
	clampBoxBounds,
	dragAxisParameter,
	faceCenter,
	faceNormal,
	flipPlaneSpec,
	isPointInClipPlanes,
	moveFace,
	padBox,
	planeSpecToEquation,
	projectBoxToScene,
	projectNormalToScene,
	projectPlaneToScene,
	projectPointToScene,
	sceneBoxToProject,
	sceneNormalToProject,
	scenePlaneToProject,
	scenePointToProject,
	SECTION_FACES,
	type ClipPlaneEquation,
	type SectionAxis,
	type SectionBoxBounds,
	type SectionFace,
	type SectionPlaneSpec,
	type SectionState,
} from './sectionMath.js';
export {
	angleBetweenEdges,
	buildChainEntry,
	buildDistanceEntry,
	buildEdgeAngleEntry,
	buildPointToFaceEntry,
	chainMetrics,
	chooseSnap,
	closestPointOnSegment,
	distance3,
	distancePointToPlane,
	extractFaceSnapCandidates,
	formatMm,
	midpoint,
	normalize3,
	SNAP_PRIORITY,
	type MeasureEntry,
	type SnapCandidate,
	type SnapKind,
	type SnapResult,
	type Vec3,
	type ViewerMeasureMode,
} from './measureMath.js';
export {
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
