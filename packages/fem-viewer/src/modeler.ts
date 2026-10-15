/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';

/** A point of the structural model: x, y, z in mm, Z up. */
export type ModelPoint = readonly [number, number, number];

export interface ModelerScene {
	/** Grid line segments to draw, each [start, end]. */
	readonly gridLines: readonly (readonly [ModelPoint, ModelPoint])[];
	/** Grid intersections, drawn as dots and snapped to. */
	readonly gridPoints: readonly ModelPoint[];
	readonly members: readonly { readonly id: string; readonly start: ModelPoint; readonly end: ModelPoint; readonly kind: string }[];
	readonly areas: readonly { readonly id: string; readonly outline: readonly ModelPoint[]; readonly openings: readonly (readonly ModelPoint[])[]; readonly kind: string }[];
	readonly supports: readonly { readonly id: string; readonly at: ModelPoint; readonly fixity: string }[];
}

/** Elements shown as a preview before they are added: a parametric shape or an imported file. */
export interface ModelerGhost {
	readonly members: readonly { readonly start: ModelPoint; readonly end: ModelPoint }[];
	readonly areas: readonly { readonly outline: readonly ModelPoint[]; readonly openings: readonly (readonly ModelPoint[])[] }[];
	readonly supports: readonly { readonly at: ModelPoint }[];
}

export type ModelerEntity = { readonly kind: 'member' | 'area' | 'support'; readonly id: string };

/** What is under the pointer: the snapped point (if any) and the element (if any). */
export interface ModelerHit {
	readonly point?: ModelPoint;
	/** What the point snapped to; 'plane' is a free point on the work plane. */
	readonly snap?: 'grid' | 'end' | 'middle' | 'corner' | 'support' | 'plane';
	readonly entity?: ModelerEntity;
}

export interface ModelerTheme {
	readonly background: string;
	readonly grid: string;
	readonly gridPoint: string;
	readonly member: string;
	readonly column: string;
	readonly brace: string;
	readonly slab: string;
	readonly wall: string;
	readonly support: string;
	readonly selection: string;
	readonly preview: string;
	readonly cursor: string;
}

export type ModelerView = '3d' | 'top' | 'front' | 'side';

export interface StructureModelerOptions {
	readonly theme?: Partial<ModelerTheme>;
	readonly onPointerMove?: (hit: ModelerHit) => void;
	/** A click (no drag): `shift` adds to the selection, `secondary` is the right button. */
	readonly onClick?: (hit: ModelerHit, modifiers: { readonly shift: boolean; readonly secondary: boolean }) => void;
}

export interface StructureModeler {
	setScene(scene: ModelerScene): void;
	setSelection(entities: readonly ModelerEntity[]): void;
	/** A rubber band through `points` (closed into a polygon when `closed`), or none. */
	setPreview(points: readonly ModelPoint[] | undefined, closed?: boolean): void;
	/** The snap marker, or none. */
	setCursor(point: ModelPoint | undefined): void;
	/** Elements about to be added, drawn faintly, or none. */
	setGhost(ghost: ModelerGhost | undefined): void;
	/** Free points fall on the horizontal plane at this elevation (mm); none: only snapped points. */
	setWorkPlane(elevation: number | undefined): void;
	setView(view: ModelerView): Promise<void>;
	setTheme(theme: Partial<ModelerTheme>): void;
	fit(): Promise<void>;
	layout(): void;
	dispose(): void;
}

const defaultTheme: ModelerTheme = {
	background: '#1e1e1e',
	grid: '#3c3c3c',
	gridPoint: '#6a6a6a',
	member: '#4fc1ff',
	column: '#c586c0',
	brace: '#d7ba7d',
	slab: '#89d185',
	wall: '#ce9178',
	support: '#89d185',
	selection: '#ffcc00',
	preview: '#ffffff',
	cursor: '#ffcc00',
};

/** Pixels within which the pointer snaps to a point. */
const SNAP_PIXELS = 14;
/** Free points on the work plane are rounded to this (mm). */
const PLANE_STEP = 10;

/** Model mm, Z up -> world metres, Y up. */
function toWorld(p: ModelPoint): THREE.Vector3 {
	return new THREE.Vector3(p[0] / 1000, p[2] / 1000, -p[1] / 1000);
}

function toModel(v: THREE.Vector3): ModelPoint {
	return [v.x * 1000, -v.z * 1000, v.y * 1000];
}

interface ISnapCandidate {
	readonly point: ModelPoint;
	readonly snap: NonNullable<ModelerHit['snap']>;
}

class StructureModelerImpl implements StructureModeler {

	private readonly components = new OBC.Components();
	private readonly world: OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;
	private readonly renderer: OBC.SimpleRenderer;
	private readonly camera: OBC.OrthoPerspectiveCamera;
	private readonly modelGroup = new THREE.Group();
	private readonly overlay = new THREE.Group();
	private readonly raycaster = new THREE.Raycaster();

	private theme: ModelerTheme;
	private scene: ModelerScene | undefined;
	private selection: readonly ModelerEntity[] = [];
	private preview: { points: readonly ModelPoint[]; closed: boolean } | undefined;
	private cursor: ModelPoint | undefined;
	private ghost: ModelerGhost | undefined;
	private workPlane: number | undefined;
	private candidates: ISnapCandidate[] = [];
	private pointerDown: { x: number; y: number } | undefined;
	private fitted = false;

	private readonly onPointerDown = (e: PointerEvent) => { this.pointerDown = { x: e.clientX, y: e.clientY }; };
	private readonly onPointerUp = (e: PointerEvent) => this.handleClick(e);
	private readonly onPointerMove = (e: PointerEvent) => this.options.onPointerMove?.(this.hitAt(e.clientX, e.clientY));
	private readonly onContextMenu = (e: MouseEvent) => e.preventDefault();

	constructor(private readonly container: HTMLElement, private readonly options: StructureModelerOptions) {
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
		this.world.scene.three.add(this.modelGroup);
		this.world.scene.three.add(this.overlay);
		this.applyTheme();

		const canvas = this.renderer.three.domElement;
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);
		canvas.addEventListener('pointermove', this.onPointerMove);
		canvas.addEventListener('contextmenu', this.onContextMenu);
	}

	setScene(scene: ModelerScene): void {
		this.scene = scene;
		this.rebuild();
		this.renderOverlay();
		if (!this.fitted && (scene.gridPoints.length || scene.members.length || scene.areas.length)) {
			this.fitted = true;
			void this.fit();
		}
	}

	setSelection(entities: readonly ModelerEntity[]): void {
		this.selection = entities;
		this.rebuild();
	}

	setPreview(points: readonly ModelPoint[] | undefined, closed = false): void {
		this.preview = points && points.length ? { points, closed } : undefined;
		this.renderOverlay();
	}

	setCursor(point: ModelPoint | undefined): void {
		this.cursor = point;
		this.renderOverlay();
	}

	setGhost(ghost: ModelerGhost | undefined): void {
		this.ghost = ghost;
		this.renderOverlay();
	}

	setWorkPlane(elevation: number | undefined): void {
		this.workPlane = elevation;
	}

	async setView(view: ModelerView): Promise<void> {
		const box = this.bounds();
		// What is about to be added counts too: an imported file may lie away from the model.
		for (const m of this.ghost?.members ?? []) {
			box.expandByPoint(toWorld(m.start)).expandByPoint(toWorld(m.end));
		}
		for (const area of this.ghost?.areas ?? []) {
			area.outline.forEach(p => box.expandByPoint(toWorld(p)));
		}
		const centre = box.getCenter(new THREE.Vector3());
		const radius = Math.max(box.getBoundingSphere(new THREE.Sphere()).radius, 1);
		const distance = radius * 2.6;
		await this.camera.projection.set(view === '3d' ? 'Perspective' : 'Orthographic');
		const eye = {
			'3d': new THREE.Vector3(1, 0.8, 1.2).normalize(),
			// A hair off the axis keeps the orbit controls from flipping at the pole.
			top: new THREE.Vector3(0, 1, 0.0001).normalize(),
			front: new THREE.Vector3(0, 0, 1),
			side: new THREE.Vector3(1, 0, 0),
		}[view].multiplyScalar(distance).add(centre);
		await this.camera.controls.setLookAt(eye.x, eye.y, eye.z, centre.x, centre.y, centre.z, true);
	}

	setTheme(theme: Partial<ModelerTheme>): void {
		this.theme = { ...this.theme, ...theme };
		this.applyTheme();
		this.rebuild();
		this.renderOverlay();
	}

	async fit(): Promise<void> {
		await this.setView('3d');
	}

	layout(): void {
		this.renderer.resize();
		this.camera.updateAspect();
	}

	dispose(): void {
		const canvas = this.renderer.three.domElement;
		canvas?.removeEventListener('pointerdown', this.onPointerDown);
		canvas?.removeEventListener('pointerup', this.onPointerUp);
		canvas?.removeEventListener('pointermove', this.onPointerMove);
		canvas?.removeEventListener('contextmenu', this.onContextMenu);
		clear(this.modelGroup);
		clear(this.overlay);
		this.components.dispose();
	}

	// ───────────────────────────── drawing ─────────────────────────────

	private applyTheme(): void {
		this.world.scene.config.backgroundColor = new THREE.Color(this.theme.background);
	}

	private bounds(): THREE.Box3 {
		const box = new THREE.Box3().setFromObject(this.modelGroup);
		return box.isEmpty() ? new THREE.Box3(new THREE.Vector3(-5, 0, -5), new THREE.Vector3(5, 5, 5)) : box;
	}

	private isSelected(kind: ModelerEntity['kind'], id: string): boolean {
		return this.selection.some(s => s.kind === kind && s.id === id);
	}

	private rebuild(): void {
		clear(this.modelGroup);
		this.candidates = [];
		const scene = this.scene;
		if (!scene) {
			return;
		}
		const theme = this.theme;

		// Grids: faint lines and dots at the intersections.
		if (scene.gridLines.length) {
			const positions = scene.gridLines.flatMap(([a, b]) => [...toWorld(a).toArray(), ...toWorld(b).toArray()]);
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
			this.modelGroup.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: theme.grid, transparent: true, opacity: 0.8 })));
		}
		if (scene.gridPoints.length) {
			const geometry = new THREE.BufferGeometry();
			geometry.setAttribute('position', new THREE.Float32BufferAttribute(scene.gridPoints.flatMap(p => toWorld(p).toArray()), 3));
			this.modelGroup.add(new THREE.Points(geometry, new THREE.PointsMaterial({ color: theme.gridPoint, size: 4, sizeAttenuation: false })));
			this.candidates.push(...scene.gridPoints.map(point => ({ point, snap: 'grid' as const })));
		}

		// Areas: translucent faces (openings cut) with outlines.
		for (const area of scene.areas) {
			const selected = this.isSelected('area', area.id);
			const color = selected ? theme.selection : area.kind === 'wall' ? theme.wall : theme.slab;
			const face = polygonMesh(area.outline, area.openings, color, selected ? 0.45 : 0.25);
			if (face) {
				this.modelGroup.add(face);
			}
			for (const loop of [area.outline, ...area.openings]) {
				const points = [...loop, loop[0]].map(toWorld);
				this.modelGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color })));
			}
			this.candidates.push(...area.outline.map(point => ({ point, snap: 'corner' as const })));
		}

		// Members: lines coloured by kind.
		for (const member of scene.members) {
			const selected = this.isSelected('member', member.id);
			const color = selected ? theme.selection : member.kind === 'column' ? theme.column : member.kind === 'brace' ? theme.brace : theme.member;
			const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([toWorld(member.start), toWorld(member.end)]), new THREE.LineBasicMaterial({ color }));
			this.modelGroup.add(line);
			const middle: ModelPoint = [(member.start[0] + member.end[0]) / 2, (member.start[1] + member.end[1]) / 2, (member.start[2] + member.end[2]) / 2];
			this.candidates.push({ point: member.start, snap: 'end' }, { point: member.end, snap: 'end' }, { point: middle, snap: 'middle' });
		}

		// Supports: small pyramids under their points.
		const size = Math.max(this.bounds().getSize(new THREE.Vector3()).length() * 0.02, 0.15);
		for (const support of scene.supports) {
			const selected = this.isSelected('support', support.id);
			const geometry = support.fixity === 'pinned' ? new THREE.ConeGeometry(size * 0.6, size, 12) : new THREE.ConeGeometry(size * 0.7, size, 4);
			geometry.translate(0, -size / 2, 0);
			const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: selected ? theme.selection : theme.support }));
			mesh.position.copy(toWorld(support.at));
			this.modelGroup.add(mesh);
			this.candidates.push({ point: support.at, snap: 'support' });
		}
	}

	private renderOverlay(): void {
		clear(this.overlay);
		const ghost = this.ghost;
		if (ghost) {
			const color = this.theme.preview;
			if (ghost.members.length) {
				const geometry = new THREE.BufferGeometry();
				geometry.setAttribute('position', new THREE.Float32BufferAttribute(ghost.members.flatMap(m => [...toWorld(m.start).toArray(), ...toWorld(m.end).toArray()]), 3));
				this.overlay.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.7 })));
			}
			for (const area of ghost.areas) {
				const face = polygonMesh(area.outline, area.openings, color, 0.12);
				if (face) {
					this.overlay.add(face);
				}
			}
			if (ghost.supports.length) {
				const geometry = new THREE.BufferGeometry().setFromPoints(ghost.supports.map(s => toWorld(s.at)));
				this.overlay.add(new THREE.Points(geometry, new THREE.PointsMaterial({ color: this.theme.support, size: 7, sizeAttenuation: false })));
			}
		}
		const preview = this.preview;
		if (preview) {
			const points = (preview.closed ? [...preview.points, preview.points[0]] : preview.points).map(toWorld);
			const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineDashedMaterial({ color: this.theme.preview, dashSize: 0.2, gapSize: 0.1, depthTest: false }));
			line.computeLineDistances();
			line.renderOrder = 5;
			this.overlay.add(line);
		}
		if (this.cursor) {
			const geometry = new THREE.BufferGeometry().setFromPoints([toWorld(this.cursor)]);
			const marker = new THREE.Points(geometry, new THREE.PointsMaterial({ color: this.theme.cursor, size: 10, sizeAttenuation: false, depthTest: false }));
			marker.renderOrder = 6;
			this.overlay.add(marker);
		}
	}

	// ───────────────────────────── picking and snapping ─────────────────────────────

	private handleClick(e: PointerEvent): void {
		const down = this.pointerDown;
		this.pointerDown = undefined;
		if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) {
			return; // an orbit or pan drag
		}
		this.options.onClick?.(this.hitAt(e.clientX, e.clientY), { shift: e.shiftKey, secondary: e.button === 2 });
	}

	/**
	 * The element under the pointer, found on screen (thin lines are hard to hit with rays):
	 * a support near it, else the nearest member, else the nearest area containing it.
	 */
	private entityAt(x: number, y: number, width: number, height: number): ModelerEntity | undefined {
		const scene = this.scene;
		if (!scene) {
			return undefined;
		}
		const camera = this.camera.three;
		const screen = (p: ModelPoint) => {
			const v = toWorld(p).project(camera);
			return { x: (v.x + 1) / 2 * width, y: (1 - v.y) / 2 * height, z: v.z, visible: v.z >= -1 && v.z <= 1 };
		};
		for (const support of scene.supports) {
			const s = screen(support.at);
			if (s.visible && Math.hypot(s.x - x, s.y - y) <= PICK_PIXELS * 1.5) {
				return { kind: 'support', id: support.id };
			}
		}
		let member: { id: string; distance: number } | undefined;
		for (const m of scene.members) {
			const a = screen(m.start);
			const b = screen(m.end);
			if (!a.visible && !b.visible) {
				continue;
			}
			const dx = b.x - a.x;
			const dy = b.y - a.y;
			const length2 = dx * dx + dy * dy;
			const t = length2 ? Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / length2)) : 0;
			const distance = Math.hypot(a.x + t * dx - x, a.y + t * dy - y);
			if (distance <= PICK_PIXELS && (!member || distance < member.distance)) {
				member = { id: m.id, distance };
			}
		}
		if (member) {
			return { kind: 'member', id: member.id };
		}
		let area: { id: string; depth: number } | undefined;
		for (const a of scene.areas) {
			const outline = a.outline.map(screen);
			if (!outline.some(p => p.visible) || !inside(outline, x, y) || a.openings.some(o => inside(o.map(screen), x, y))) {
				continue;
			}
			const depth = outline.reduce((sum, p) => sum + p.z, 0) / outline.length;
			if (!area || depth < area.depth) {
				area = { id: a.id, depth };
			}
		}
		return area && { kind: 'area', id: area.id };
	}

	private hitAt(clientX: number, clientY: number): ModelerHit {
		const canvas = this.renderer.three.domElement;
		const rect = canvas.getBoundingClientRect();
		const camera = this.camera.three;
		// The nearest snap point on screen, within reach.
		let best: { candidate: ISnapCandidate; distance: number; depth: number } | undefined;
		for (const candidate of this.candidates) {
			const screen = toWorld(candidate.point).project(camera);
			if (screen.z < -1 || screen.z > 1) {
				continue;
			}
			const x = rect.left + (screen.x + 1) / 2 * rect.width;
			const y = rect.top + (1 - screen.y) / 2 * rect.height;
			const distance = Math.hypot(x - clientX, y - clientY);
			// Points on top of each other on screen (a column's ends seen from above): the one nearest
			// the eye, then elements before grid points.
			const better = !best || distance < best.distance - 0.5 || (Math.abs(distance - best.distance) <= 0.5
				&& (screen.z < best.depth - 1e-6 || (Math.abs(screen.z - best.depth) <= 1e-6 && rank(candidate.snap) < rank(best.candidate.snap))));
			if (distance <= SNAP_PIXELS && better) {
				best = { candidate, distance, depth: screen.z };
			}
		}
		const ndc = new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
		this.raycaster.setFromCamera(ndc, camera);
		const entity = this.entityAt(clientX - rect.left, clientY - rect.top, rect.width, rect.height);
		if (best) {
			return { point: best.candidate.point, snap: best.candidate.snap, entity };
		}
		if (this.workPlane !== undefined) {
			const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -this.workPlane / 1000);
			const at = this.raycaster.ray.intersectPlane(plane, new THREE.Vector3());
			if (at) {
				const [x, y] = toModel(at);
				return { point: [Math.round(x / PLANE_STEP) * PLANE_STEP, Math.round(y / PLANE_STEP) * PLANE_STEP, this.workPlane], snap: 'plane', entity };
			}
		}
		return { entity };
	}
}

/** Pixels within which the pointer picks a member or a support. */
const PICK_PIXELS = 7;

/** Element snaps win ties with grid points: drawing usually continues from what is drawn. */
function rank(snap: NonNullable<ModelerHit['snap']>): number {
	return ['end', 'support', 'corner', 'middle', 'grid', 'plane'].indexOf(snap);
}

/** Whether (x, y) is inside the polygon (even-odd rule). */
function inside(polygon: readonly { x: number; y: number }[], x: number, y: number): boolean {
	let result = false;
	for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
		const a = polygon[i];
		const b = polygon[j];
		if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) {
			result = !result;
		}
	}
	return result;
}

/** A flat polygon (with holes) as a mesh, triangulated in its own plane. */
function polygonMesh(outline: readonly ModelPoint[], openings: readonly (readonly ModelPoint[])[], color: string, opacity: number): THREE.Mesh | undefined {
	const points = outline.map(toWorld);
	if (points.length < 3) {
		return undefined;
	}
	const normal = new THREE.Vector3();
	for (let i = 0; i < points.length; i++) {
		const a = points[i];
		const b = points[(i + 1) % points.length];
		normal.x += (a.y - b.y) * (a.z + b.z);
		normal.y += (a.z - b.z) * (a.x + b.x);
		normal.z += (a.x - b.x) * (a.y + b.y);
	}
	if (normal.lengthSq() === 0) {
		return undefined;
	}
	normal.normalize();
	const u = points[1].clone().sub(points[0]).normalize();
	const v = normal.clone().cross(u);
	const origin = points[0];
	const flat = (p: THREE.Vector3) => new THREE.Vector2(p.clone().sub(origin).dot(u), p.clone().sub(origin).dot(v));
	const shape = new THREE.Shape(points.map(flat));
	for (const hole of openings) {
		shape.holes.push(new THREE.Path(hole.map(toWorld).map(flat)));
	}
	const geometry = new THREE.ShapeGeometry(shape);
	const position = geometry.getAttribute('position');
	for (let i = 0; i < position.count; i++) {
		const p = origin.clone().addScaledVector(u, position.getX(i)).addScaledVector(v, position.getY(i));
		position.setXYZ(i, p.x, p.y, p.z);
	}
	geometry.computeBoundingSphere();
	return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false }));
}

function clear(group: THREE.Group): void {
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

export function createStructureModeler(container: HTMLElement, options: StructureModelerOptions = {}): StructureModeler {
	return new StructureModelerImpl(container, options);
}
