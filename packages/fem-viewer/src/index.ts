/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import { roundPointMaterial, subtleNodeColor, usableTheme } from './theme.js';
import { Floats, ModelIndex } from './geometry.js';
import { FemCameraView, FemElement, FemModel, FemResultDisplay, FemResultView, FemSelection, FemVisibleElements, outerFaces, sameSelection } from './model.js';
import { ResultOverlay } from './results.js';

export type { FemCameraView, FemElement, FemModel, FemNode, FemResultDisplay, FemResultElement, FemResultQuantity, FemResultShell, FemResultSolid, FemResultView, FemSelection, FemValueQuantity, FemVisibleElements } from './model.js';
export { FORCE_COMPONENTS, SHELL_COMPONENTS, SOLID_COMPONENTS, formatUtilisation, UTILISATION_WARN, utilisationBand } from './model.js';
export { contourColor } from './results.js';

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

export interface FemViewerOptions {
	readonly theme?: Partial<FemViewerTheme>;
	readonly onSelectionChanged?: (selection: FemSelection | undefined) => void;
}

export interface FemViewer {
	setModel(model: FemModel): void;
	setSelection(selection: FemSelection | undefined): void;
	/** Draws an analysis result over the model (undefined: the model alone). */
	setResults(results: FemResultView | undefined, display?: FemResultDisplay): void;
	setTheme(theme: Partial<FemViewerTheme>): void;
	/** Draws only these elements and their nodes (a floor, an elevation, a storey); undefined: all. */
	setVisibleElements(elements: FemVisibleElements): void;
	/**
	 * Looks at the model in 3D (perspective, orbiting) or straight down the model's Z (`top`: a
	 * plan), along its Y (`front`: an X-Z elevation) or along its X (`side`: a Y-Z elevation),
	 * orthographic, and frames what is drawn.
	 */
	setCameraView(view: FemCameraView): Promise<void>;
	fit(): Promise<void>;
	/** Call when the container changes size and the browser has not reported it (e.g. hidden tabs). */
	layout(): void;
	dispose(): void;
}

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

/** Element names of the struts tying frames and shells into solids (not drawn). */
const EMBED = /\/embed(#\d+)?$/;

class FemViewerImpl implements FemViewer {

	private readonly components = new OBC.Components();
	private readonly world: OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;
	private readonly renderer: OBC.SimpleRenderer;
	private readonly camera: OBC.OrthoPerspectiveCamera;
	private readonly grid: OBC.SimpleGrid;
	private readonly modelGroup = new THREE.Group();
	private readonly pickTargets: THREE.Object3D[] = [];

	private theme: FemViewerTheme;
	private model: FemModel | undefined;
	/** The model's nodes in world space and its elements by id, shared with the results. */
	private index: ModelIndex | undefined;
	private selection: FemSelection | undefined;

	private members: THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial> | undefined;
	private memberIds: number[] = [];
	/** The outline of the solids (dimmed under a result, as the members). */
	private solidEdges: THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial> | undefined;
	private nodes: THREE.Points | undefined;
	private nodeIds: number[] = [];
	/** The shells' faces, as triangles, and the element of each triangle. */
	private faces: THREE.Mesh | undefined;
	private faceIds: number[] = [];
	private readonly highlight = new THREE.Group();
	private readonly resultGroup = new THREE.Group();
	private results: { readonly view: FemResultView; readonly display: FemResultDisplay } | undefined;
	private visible: FemVisibleElements;
	private cameraView: FemCameraView = '3d';
	private overlay: ResultOverlay | undefined;
	private animation: number | undefined;
	private readonly raycaster = new THREE.Raycaster();

	private pointerDown: { x: number; y: number } | undefined;
	private readonly onPointerDown = (e: PointerEvent) => { this.pointerDown = { x: e.clientX, y: e.clientY }; };
	private readonly onPointerUp = (e: PointerEvent) => this.handleClick(e);

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
		this.world.scene.three.add(this.highlight);
		this.world.scene.three.add(this.resultGroup);

		this.applyTheme();

		// Labels: the same size on screen under the orthographic camera as under the perspective one.
		this.renderer.onBeforeUpdate.add(() => this.overlay?.setLabelScale(this.labelScale()));

		const canvas = this.renderer.three.domElement;
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);
	}

	setModel(model: FemModel): void {
		const first = !this.model;
		this.model = model;
		this.index = new ModelIndex(model);
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
		if (first) {
			void this.fit();
		}
	}

	setSelection(selection: FemSelection | undefined): void {
		if (sameSelection(selection, this.selection)) {
			return;
		}
		this.selection = selection;
		this.renderHighlight();
		// Only the labels follow the selection: the result's drawing stays.
		this.overlay?.setSelectedElement(this.selectedElement());
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
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
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
		if (this.cameraView !== '3d') {
			await this.camera.controls.fitToSphere(new THREE.Sphere(sphere.center, radius * 1.05), false);
		}
	}

	layout(): void {
		this.renderer.resize();
		this.camera.updateAspect();
	}

	dispose(): void {
		const canvas = this.renderer.three.domElement;
		canvas?.removeEventListener('pointerdown', this.onPointerDown);
		canvas?.removeEventListener('pointerup', this.onPointerUp);
		this.clearGroup(this.modelGroup);
		this.clearGroup(this.highlight);
		this.clearResults();
		this.components.dispose();
	}

	private applyTheme(): void {
		this.world.scene.config.backgroundColor = new THREE.Color(this.theme.background);
		this.grid.config.color = new THREE.Color(this.theme.grid);
	}

	private rebuild(): void {
		this.clearGroup(this.modelGroup);
		this.pickTargets.length = 0;
		this.members = undefined;
		this.solidEdges = undefined;
		this.nodes = undefined;
		this.faces = undefined;
		const index = this.index;
		if (!index) {
			return;
		}
		const model = index.model;
		const world = index.world;
		const scale = index.size;

		// Members: every element is drawn as its edge loop (2-node elements as one segment).
		const positions = new Floats();
		this.memberIds = [];
		// Solids show their outer faces; the struts tying frames into them are not drawn.
		const visible = this.visible;
		const shown = (e: FemElement) => !visible || visible.has(e.id);
		const solids = model.elements.filter(e => e.type === 'Solid' && shown(e));
		for (const element of model.elements) {
			if (element.type === 'Solid' || !shown(element) || EMBED.test(element.name ?? '')) {
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
				positions.pushFrom(world, a, 3);
				positions.pushFrom(world, b, 3);
				this.memberIds.push(element.id);
			}
		}
		if (positions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', positions.attribute());
			this.members = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: this.theme.member }));
			this.modelGroup.add(this.members);
			this.pickTargets.push(this.members);
		}

		if (solids.length) {
			const faces = outerFaces(solids);
			const points = new Floats();
			// Only the feature edges, where the surface folds (the solid's own outline): every
			// triangle edge of a fine mesh would grey the solid out.
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
		const corners: number[] = [];
		for (const element of model.elements) {
			if (element.nodes.length < 3 || element.type === 'Solid' || !shown(element)) {
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
				facePositions.pushFrom(world, corners[0], 3);
				facePositions.pushFrom(world, corners[i], 3);
				facePositions.pushFrom(world, corners[i + 1], 3);
				this.faceIds.push(element.id);
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

		// Nodes: of the elements shown (all of them with nothing filtered).
		let used: Set<number> | undefined;
		if (visible) {
			used = new Set();
			for (const element of model.elements) {
				if (visible.has(element.id)) {
					element.nodes.forEach(n => used!.add(n));
				}
			}
		}
		const nodePositions = new Floats();
		this.nodeIds = [];
		model.nodes.forEach((node, i) => {
			if (!solidOnly.has(node.id) && (!used || used.has(node.id))) {
				nodePositions.pushFrom(world, i * 3, 3);
				this.nodeIds.push(node.id);
			}
		});
		if (nodePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', nodePositions.attribute());
			// Small round dots, faded towards the background: the members carry the picture.
			this.nodes = new THREE.Points(geometry, roundPointMaterial(subtleNodeColor(this.theme.node, this.theme.background), 5));
			this.modelGroup.add(this.nodes);
			this.pickTargets.push(this.nodes);
		}

		// Supports: a small pyramid under every node with any restrained DOF, except the nodes of a
		// supported solid face (a carpet of them would hide the solid): its face shows it. One
		// instanced mesh draws them all.
		const supported: number[] = [];
		model.nodes.forEach((node, i) => {
			if (node.restraint?.some(Boolean) && !solidOnly.has(node.id) && (!used || used.has(node.id))) {
				supported.push(i);
			}
		});
		if (supported.length) {
			const supportGeometry = new THREE.ConeGeometry(scale * 0.025, scale * 0.04, 4);
			supportGeometry.translate(0, -scale * 0.02, 0);
			const supports = new THREE.InstancedMesh(supportGeometry, new THREE.MeshBasicMaterial({ color: this.theme.support }), supported.length);
			const matrix = new THREE.Matrix4();
			supported.forEach((i, k) => supports.setMatrixAt(k, matrix.makeTranslation(world[i * 3], world[i * 3 + 1], world[i * 3 + 2])));
			supports.computeBoundingSphere();
			this.modelGroup.add(supports);
		}
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
		const overlay = new ResultOverlay(index, this.results.view, this.results.display, {
			deformed: theme.deformed,
			positive: theme.positive,
			negative: theme.negative,
			reaction: theme.reaction,
			pass: theme.pass,
			warn: theme.warn,
			fail: theme.fail,
			label: theme.node,
			labelBackground: theme.background,
		}, this.selectedElement(), this.visible);
		this.overlay = overlay;
		this.resultGroup.add(overlay.group);
		if (overlay.isAnimated) {
			const start = performance.now();
			const step = (now: number) => {
				overlay.setPhase(Math.sin((now - start) / 1600 * 2 * Math.PI));
				this.animation = requestAnimationFrame(step);
			};
			this.animation = requestAnimationFrame(step);
		}
	}

	private renderHighlight(): void {
		this.clearGroup(this.highlight);
		const index = this.index;
		const selection = this.selection;
		if (!index || !selection) {
			return;
		}
		const color = this.theme.selection;
		if (selection.kind === 'node') {
			const point = index.point(selection.id);
			if (point) {
				const geometry = new THREE.BufferGeometry().setFromPoints([point]);
				this.highlight.add(new THREE.Points(geometry, roundPointMaterial(color, 10, { depthTest: false })));
			}
			return;
		}
		const element = index.elements.get(selection.id);
		if (!element) {
			return;
		}
		const pts: THREE.Vector3[] = [];
		for (const [a, b] of this.edges(element)) {
			const pa = index.point(a);
			const pb = index.point(b);
			if (pa && pb) {
				pts.push(pa, pb);
			}
		}
		const geometry = new THREE.BufferGeometry().setFromPoints(pts);
		this.highlight.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, depthTest: false })));
	}

	private handleClick(e: PointerEvent): void {
		const down = this.pointerDown;
		this.pointerDown = undefined;
		// Ignore orbit/pan drags; only a stationary click selects.
		if (e.button !== 0 || !down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4 || !this.index) {
			return;
		}
		const rect = this.renderer.three.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((e.clientX - rect.left) / rect.width) * 2 - 1,
			-((e.clientY - rect.top) / rect.height) * 2 + 1,
		);
		const threshold = this.index.size * 0.01;
		this.raycaster.params.Line = { threshold };
		this.raycaster.params.Points = { threshold: threshold * 1.5 };
		this.raycaster.setFromCamera(ndc, this.camera.three);
		const hits = this.raycaster.intersectObjects(this.pickTargets, false);
		// Prefer nodes over members, and members over the shell faces behind them.
		const nodeHit = hits.find(h => h.object === this.nodes && h.index !== undefined);
		const memberHit = hits.find(h => h.object === this.members && h.index !== undefined);
		const faceHit = hits.find(h => h.object === this.faces && h.faceIndex !== undefined && h.faceIndex !== null);
		let next: FemSelection | undefined;
		if (nodeHit) {
			next = { kind: 'node', id: this.nodeIds[nodeHit.index!] };
		} else if (memberHit) {
			next = { kind: 'element', id: this.memberIds[Math.floor(memberHit.index! / 2)] };
		} else if (faceHit) {
			next = { kind: 'element', id: this.faceIds[faceHit.faceIndex!] };
		}
		if (!sameSelection(next, this.selection)) {
			this.selection = next;
			this.renderHighlight();
			this.options.onSelectionChanged?.(next);
		}
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

export { createBuildingViewer, type BuildingLayer, type BuildingViewer, type BuildingViewerOptions, type BuildingViewerTheme, type BuildingViewPreset } from './building.js';
export { setTrustedTypesHost, type TrustedTypesHost } from './trustedTypes.js';
export { createStructureModeler, type ModelerEntity, type ModelerGhost, type ModelerHit, type ModelerScene, type ModelerTheme, type ModelerView, type ModelPoint, type StructureModeler, type StructureModelerOptions } from './modeler.js';
