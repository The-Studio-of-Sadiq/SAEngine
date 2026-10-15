/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import { FemElement, FemModel, FemNode, FemResultDisplay, FemResultView, FemSelection, sameSelection } from './model.js';
import { ResultOverlay } from './results.js';

export type { FemElement, FemModel, FemNode, FemResultDisplay, FemResultElement, FemResultQuantity, FemResultShell, FemResultView, FemSelection, FemValueQuantity } from './model.js';
export { FORCE_COMPONENTS, SHELL_COMPONENTS } from './model.js';
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
};

/** Model space (Z up in 3D, Y up in 2D) to three.js world space (Y up). */
function toWorld(model: FemModel, coords: readonly number[]): THREE.Vector3 {
	const x = coords[0] ?? 0;
	const y = coords[1] ?? 0;
	if (model.ndm < 3) {
		return new THREE.Vector3(x, y, 0);
	}
	return new THREE.Vector3(x, coords[2] ?? 0, -y);
}

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
	private selection: FemSelection | undefined;

	private members: THREE.LineSegments | undefined;
	private memberIds: number[] = [];
	private nodes: THREE.Points | undefined;
	private nodeIds: number[] = [];
	private readonly highlight = new THREE.Group();
	private readonly resultGroup = new THREE.Group();
	private results: { readonly view: FemResultView; readonly display: FemResultDisplay } | undefined;
	private overlay: ResultOverlay | undefined;
	private animation: number | undefined;
	private readonly raycaster = new THREE.Raycaster();

	private pointerDown: { x: number; y: number } | undefined;
	private readonly onPointerDown = (e: PointerEvent) => { this.pointerDown = { x: e.clientX, y: e.clientY }; };
	private readonly onPointerUp = (e: PointerEvent) => this.handleClick(e);

	constructor(private readonly container: HTMLElement, private readonly options: FemViewerOptions) {
		this.theme = { ...defaultTheme, ...options.theme };

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

		const canvas = this.renderer.three.domElement;
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);
	}

	setModel(model: FemModel): void {
		const first = !this.model;
		this.model = model;
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
		this.renderResults();
	}

	setResults(view: FemResultView | undefined, display?: FemResultDisplay): void {
		this.results = view && display ? { view, display } : undefined;
		this.rebuild();
		this.renderResults();
	}

	setTheme(theme: Partial<FemViewerTheme>): void {
		this.theme = { ...this.theme, ...theme };
		this.applyTheme();
		this.rebuild();
		this.renderHighlight();
		this.renderResults();
	}

	async fit(): Promise<void> {
		const box = new THREE.Box3().setFromObject(this.modelGroup);
		if (box.isEmpty()) {
			return;
		}
		const sphere = box.getBoundingSphere(new THREE.Sphere());
		const radius = Math.max(sphere.radius, 1);
		const eye = sphere.center.clone().add(new THREE.Vector3(1, 0.8, 1.2).normalize().multiplyScalar(radius * 2.6));
		await this.camera.controls.setLookAt(eye.x, eye.y, eye.z, sphere.center.x, sphere.center.y, sphere.center.z, true);
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
		this.nodes = undefined;
		const model = this.model;
		if (!model) {
			return;
		}

		const nodeById = new Map<number, FemNode>(model.nodes.map(n => [n.id, n]));
		const scale = this.modelScale(model);

		// Members: every element is drawn as its edge loop (2-node elements as one segment).
		const positions: number[] = [];
		this.memberIds = [];
		for (const element of model.elements) {
			for (const [a, b] of this.edges(element)) {
				const na = nodeById.get(a);
				const nb = nodeById.get(b);
				if (!na || !nb) {
					continue;
				}
				const pa = toWorld(model, na.coords);
				const pb = toWorld(model, nb.coords);
				positions.push(pa.x, pa.y, pa.z, pb.x, pb.y, pb.z);
				this.memberIds.push(element.id);
			}
		}
		if (positions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
			// Under a result the model steps back.
			const dimmed = !!this.results;
			this.members = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: this.theme.member, transparent: dimmed, opacity: dimmed ? 0.35 : 1 }));
			this.modelGroup.add(this.members);
			this.pickTargets.push(this.members);
		}

		// Shell-like elements (3+ nodes) also get a translucent face so they read as areas.
		for (const element of model.elements) {
			if (element.nodes.length < 3) {
				continue;
			}
			const pts = element.nodes.map(id => nodeById.get(id)).filter((n): n is FemNode => !!n).map(n => toWorld(model, n.coords));
			if (pts.length < 3) {
				continue;
			}
			const geometry = new THREE.BufferGeometry().setFromPoints(pts);
			const index: number[] = [];
			for (let i = 1; i < pts.length - 1; i++) {
				index.push(0, i, i + 1);
			}
			geometry.setIndex(index);
			const face = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				color: this.theme.member, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false,
			}));
			this.modelGroup.add(face);
		}

		// Nodes.
		this.nodeIds = model.nodes.map(n => n.id);
		const nodePositions = model.nodes.flatMap(n => toWorld(model, n.coords).toArray());
		if (nodePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(nodePositions, 3));
			this.nodes = new THREE.Points(geometry, new THREE.PointsMaterial({ color: this.theme.node, size: 6, sizeAttenuation: false }));
			this.modelGroup.add(this.nodes);
			this.pickTargets.push(this.nodes);
		}

		// Supports: a small pyramid under every node with any restrained DOF.
		const supportGeometry = new THREE.ConeGeometry(scale * 0.025, scale * 0.04, 4);
		supportGeometry.translate(0, -scale * 0.02, 0);
		const supportMaterial = new THREE.MeshBasicMaterial({ color: this.theme.support });
		for (const node of model.nodes) {
			if (!node.restraint?.some(Boolean)) {
				continue;
			}
			const support = new THREE.Mesh(supportGeometry, supportMaterial);
			support.position.copy(toWorld(model, node.coords));
			this.modelGroup.add(support);
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
		const model = this.model;
		if (!model || !this.results) {
			return;
		}
		const theme = this.theme;
		const overlay = new ResultOverlay(model, this.results.view, this.results.display, {
			deformed: theme.deformed,
			positive: theme.positive,
			negative: theme.negative,
			reaction: theme.reaction,
			label: theme.node,
			labelBackground: theme.background,
		}, this.modelScale(model), coords => toWorld(model, coords), this.selection?.kind === 'element' ? this.selection.id : undefined);
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
		const model = this.model;
		const selection = this.selection;
		if (!model || !selection) {
			return;
		}
		const color = this.theme.selection;
		const nodeById = new Map<number, FemNode>(model.nodes.map(n => [n.id, n]));
		if (selection.kind === 'node') {
			const node = nodeById.get(selection.id);
			if (node) {
				const geometry = new THREE.BufferGeometry().setFromPoints([toWorld(model, node.coords)]);
				this.highlight.add(new THREE.Points(geometry, new THREE.PointsMaterial({ color, size: 11, sizeAttenuation: false, depthTest: false })));
			}
			return;
		}
		const element = model.elements.find(e => e.id === selection.id);
		if (!element) {
			return;
		}
		const pts: THREE.Vector3[] = [];
		for (const [a, b] of this.edges(element)) {
			const na = nodeById.get(a);
			const nb = nodeById.get(b);
			if (na && nb) {
				pts.push(toWorld(model, na.coords), toWorld(model, nb.coords));
			}
		}
		const geometry = new THREE.BufferGeometry().setFromPoints(pts);
		this.highlight.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, depthTest: false })));
	}

	private handleClick(e: PointerEvent): void {
		const down = this.pointerDown;
		this.pointerDown = undefined;
		// Ignore orbit/pan drags; only a stationary click selects.
		if (e.button !== 0 || !down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4 || !this.model) {
			return;
		}
		const rect = this.renderer.three.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((e.clientX - rect.left) / rect.width) * 2 - 1,
			-((e.clientY - rect.top) / rect.height) * 2 + 1,
		);
		const threshold = this.modelScale(this.model) * 0.01;
		this.raycaster.params.Line = { threshold };
		this.raycaster.params.Points = { threshold: threshold * 1.5 };
		this.raycaster.setFromCamera(ndc, this.camera.three);
		const hits = this.raycaster.intersectObjects(this.pickTargets, false);
		// Prefer nodes over members when both are under the cursor.
		const nodeHit = hits.find(h => h.object === this.nodes && h.index !== undefined);
		const memberHit = hits.find(h => h.object === this.members && h.index !== undefined);
		let next: FemSelection | undefined;
		if (nodeHit) {
			next = { kind: 'node', id: this.nodeIds[nodeHit.index!] };
		} else if (memberHit) {
			next = { kind: 'element', id: this.memberIds[Math.floor(memberHit.index! / 2)] };
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

	private modelScale(model: FemModel): number {
		const box = new THREE.Box3();
		for (const node of model.nodes) {
			box.expandByPoint(toWorld(model, node.coords));
		}
		return box.isEmpty() ? 1 : Math.max(box.getSize(new THREE.Vector3()).length(), 1);
	}

	private clearGroup(group: THREE.Group): void {
		for (const child of [...group.children]) {
			group.remove(child);
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

export { createBuildingViewer, type BuildingViewer, type BuildingViewerOptions, type BuildingViewerTheme } from './building.js';
export { setTrustedTypesHost, type TrustedTypesHost } from './trustedTypes.js';
export { createStructureModeler, type ModelerEntity, type ModelerGhost, type ModelerHit, type ModelerScene, type ModelerTheme, type ModelerView, type ModelPoint, type StructureModeler, type StructureModelerOptions } from './modeler.js';
