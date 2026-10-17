/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import { roundPointMaterial, subtleNodeColor, usableTheme } from './theme.js';
import { FemElement, FemModel, FemNode, FemResultDisplay, FemResultView, FemSelection, outerFaces, sameSelection } from './model.js';
import { ResultOverlay } from './results.js';

export type { FemElement, FemModel, FemNode, FemResultDisplay, FemResultElement, FemResultQuantity, FemResultShell, FemResultSolid, FemResultView, FemSelection, FemValueQuantity } from './model.js';
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
	/** The shells' faces, as triangles, and the element of each triangle. */
	private faces: THREE.Mesh | undefined;
	private faceIds: number[] = [];
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
		this.theme = { ...this.theme, ...usableTheme(theme) };
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
		this.faces = undefined;
		const model = this.model;
		if (!model) {
			return;
		}

		const nodeById = new Map<number, FemNode>(model.nodes.map(n => [n.id, n]));
		const scale = this.modelScale(model);

		// Members: every element is drawn as its edge loop (2-node elements as one segment).
		const positions: number[] = [];
		this.memberIds = [];
		// Solids show their outer faces; the struts tying frames into them are not drawn.
		const solids = model.elements.filter(e => e.type === 'Solid');
		const hidden = (e: FemElement) => e.type === 'Solid' || /\/embed(#\d+)?$/.test(e.name ?? '');
		for (const element of model.elements) {
			if (hidden(element)) {
				continue;
			}
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

		if (solids.length) {
			const faces = outerFaces(solids);
			const points: number[] = [];
			// Only the feature edges, where the surface folds (the solid's own outline): every
			// triangle edge of a fine mesh would grey the solid out.
			const sharing = new Map<string, { a: THREE.Vector3; b: THREE.Vector3; normals: THREE.Vector3[] }>();
			for (const face of faces) {
				const pts = face.nodes.map(id => nodeById.get(id)).filter((n): n is FemNode => !!n).map(n => toWorld(model, n.coords));
				if (pts.length !== 3) {
					continue;
				}
				points.push(...pts.flatMap(p => p.toArray()));
				const normal = pts[1].clone().sub(pts[0]).cross(pts[2].clone().sub(pts[0])).normalize();
				face.nodes.forEach((a, k) => {
					const b = face.nodes[(k + 1) % 3];
					const key = a < b ? `${a}-${b}` : `${b}-${a}`;
					const entry = sharing.get(key) ?? { a: pts[k], b: pts[(k + 1) % 3], normals: [] };
					entry.normals.push(normal);
					sharing.set(key, entry);
				});
			}
			const edges: number[] = [];
			for (const { a, b, normals: [n1, n2] } of sharing.values()) {
				if (!n2 || Math.abs(n1.dot(n2)) < 0.94) {
					edges.push(...a.toArray(), ...b.toArray());
				}
			}
			const surface = new THREE.BufferGeometry();
			surface.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
			this.modelGroup.add(new THREE.Mesh(surface, new THREE.MeshBasicMaterial({
				color: this.theme.member, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false,
			})));
			const lines = new THREE.BufferGeometry();
			lines.setAttribute('position', new THREE.Float32BufferAttribute(edges, 3));
			const dimmed = !!this.results;
			this.modelGroup.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color: this.theme.member, transparent: true, opacity: dimmed ? 0.15 : 0.35 })));
		}

		// Shell-like elements (3+ nodes) also get a translucent face so they read as areas; a click
		// on the face selects the element.
		const facePositions: number[] = [];
		this.faceIds = [];
		for (const element of model.elements) {
			if (element.nodes.length < 3 || element.type === 'Solid') {
				continue;
			}
			const pts = element.nodes.map(id => nodeById.get(id)).filter((n): n is FemNode => !!n).map(n => toWorld(model, n.coords));
			if (pts.length < 3) {
				continue;
			}
			for (let i = 1; i < pts.length - 1; i++) {
				facePositions.push(...pts[0].toArray(), ...pts[i].toArray(), ...pts[i + 1].toArray());
				this.faceIds.push(element.id);
			}
		}
		if (facePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(facePositions, 3));
			this.faces = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
				color: this.theme.member, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false,
			}));
			this.modelGroup.add(this.faces);
			this.pickTargets.push(this.faces);
		}

		// Nodes only solids use are not marked (or picked): a solid's mesh would bury it in them.
		const solidOnly = new Set(solids.flatMap(e => e.nodes));
		for (const element of model.elements) {
			if (element.type !== 'Solid') {
				element.nodes.forEach(n => solidOnly.delete(n));
			}
		}

		// Nodes.
		const marked = model.nodes.filter(n => !solidOnly.has(n.id));
		this.nodeIds = marked.map(n => n.id);
		const nodePositions = marked.flatMap(n => toWorld(model, n.coords).toArray());
		if (nodePositions.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(nodePositions, 3));
			// Small round dots, faded towards the background: the members carry the picture.
			this.nodes = new THREE.Points(geometry, roundPointMaterial(subtleNodeColor(this.theme.node, this.theme.background), 5));
			this.modelGroup.add(this.nodes);
			this.pickTargets.push(this.nodes);
		}

		// Supports: a small pyramid under every node with any restrained DOF, except the nodes of a
		// supported solid face (a carpet of them would hide the solid): its face shows it.
		const supportGeometry = new THREE.ConeGeometry(scale * 0.025, scale * 0.04, 4);
		supportGeometry.translate(0, -scale * 0.02, 0);
		const supportMaterial = new THREE.MeshBasicMaterial({ color: this.theme.support });
		for (const node of model.nodes) {
			if (!node.restraint?.some(Boolean) || solidOnly.has(node.id)) {
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
			pass: theme.pass,
			warn: theme.warn,
			fail: theme.fail,
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
				this.highlight.add(new THREE.Points(geometry, roundPointMaterial(color, 10, { depthTest: false })));
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
