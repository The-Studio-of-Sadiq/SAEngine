/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import { disposeObject } from './geometry.js';
import {
	boxToClipPlanes,
	clampBoxBounds,
	dragAxisParameter,
	faceCenter,
	faceNormal,
	flipPlaneSpec,
	moveFace,
	padBox,
	planeSpecToEquation,
	projectBoxToScene,
	projectNormalToScene,
	projectPointToScene,
	sceneBoxToProject,
	sceneNormalToProject,
	scenePlaneToProject,
	SECTION_FACES,
	type SectionAxis,
	type SectionBoxBounds,
	type SectionFace,
	type SectionPlaneSpec,
	type SectionState,
} from './sectionMath.js';

export interface SectionControllerOptions {
	readonly camera: () => THREE.Camera;
	readonly domElement: () => HTMLElement;
	readonly setControlsEnabled: (enabled: boolean) => void;
	readonly onLiveChange?: (state: SectionState) => void;
	readonly onCommit?: (state: SectionState) => void;
	readonly onPickModeChanged?: (picking: boolean) => void;
	readonly accentColor?: string;
	readonly hoverColor?: string;
}

interface HandleMeta {
	readonly key: string;
	readonly target: { readonly kind: 'box'; readonly face: SectionFace } | { readonly kind: 'plane'; readonly id: string };
	readonly origin: THREE.Vector3;
	readonly axisDir: THREE.Vector3;
	readonly group: THREE.Group;
	readonly materials: THREE.MeshBasicMaterial[];
	readonly faceOverlay?: THREE.Mesh;
	readonly hitMesh: THREE.Mesh;
}

type ActiveDrag =
	| {
		readonly kind: 'box';
		readonly face: SectionFace;
		readonly origin: THREE.Vector3;
		readonly axisDir: THREE.Vector3;
		readonly t0: number;
		readonly initialValue: number;
		moved: boolean;
	}
	| {
		readonly kind: 'plane';
		readonly id: string;
		readonly origin: THREE.Vector3;
		readonly axisDir: THREE.Vector3;
		readonly t0: number;
		readonly initialPoint: readonly [number, number, number];
		moved: boolean;
	};

const NO_CLIP: THREE.Plane[] = [];

/**
 * Interactive 3D section box (6 draggable face handles) and single section planes.
 * Keeps clipping planes in {@link clipPlanes} (mutated in-place) so model materials can
 * reference the array directly while gizmos and measurement overlays stay unclipped.
 */
export class SectionController {

	readonly clipPlanes: THREE.Plane[] = [];
	readonly gizmoGroup = new THREE.Group();

	private scale = 0.001;
	private offset: readonly [number, number, number] = [0, 0, 0];
	private modelBoundsScene: THREE.Box3 | undefined;
	private boxEnabled = false;
	private boxScene: SectionBoxBounds | undefined;
	private planesScene: SectionPlaneSpec[] = [];
	private planeCounter = 0;
	private planePickMode = false;

	private handles: HandleMeta[] = [];
	private hitMeshes: THREE.Mesh[] = [];
	private hoveredKey: string | undefined;
	private drag: ActiveDrag | undefined;
	private justDragged = false;
	private accentColor: string;
	private hoverColor: string;
	private readonly raycaster = new THREE.Raycaster();
	private readonly hitSphereGeo = new THREE.SphereGeometry(0.45, 10, 8);

	constructor(private readonly options: SectionControllerOptions) {
		this.accentColor = options.accentColor ?? '#3794ff';
		this.hoverColor = options.hoverColor ?? '#ffcc00';
		this.gizmoGroup.renderOrder = 15;
	}

	get isBoxEnabled(): boolean {
		return this.boxEnabled;
	}

	get isPickMode(): boolean {
		return this.planePickMode;
	}

	get isDragging(): boolean {
		return !!this.drag;
	}

	setColors(accentColor: string, hoverColor: string): void {
		this.accentColor = accentColor;
		this.hoverColor = hoverColor;
		this.rebuildGizmos();
	}

	setFrame(scale: number, offset: readonly [number, number, number]): void {
		if (scale === this.scale && offset[0] === this.offset[0] && offset[1] === this.offset[1] && offset[2] === this.offset[2]) {
			return;
		}
		// Preserve current section geometry in project mm when the frame updates.
		const currentMm = this.getState();
		this.scale = scale;
		this.offset = offset;
		if (currentMm.box || currentMm.planes.length) {
			this.applyMmStateInternal(currentMm);
			this.syncClipPlanes();
			this.rebuildGizmos();
		}
	}

	setModelBounds(box: THREE.Box3 | undefined): void {
		this.modelBoundsScene = box && !box.isEmpty() ? box.clone() : undefined;
		if (this.boxEnabled && !this.boxScene && this.modelBoundsScene) {
			this.boxScene = this.defaultSceneBox();
			this.syncClipPlanes();
		}
		this.rebuildGizmos();
	}

	toggleBox(enabled?: boolean): boolean {
		const next = enabled ?? !this.boxEnabled;
		this.boxEnabled = next;
		if (next && !this.boxScene) {
			this.boxScene = this.defaultSceneBox();
		}
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
		return this.boxEnabled;
	}

	setBoxFromSceneBounds(box: THREE.Box3): boolean {
		if (box.isEmpty()) {
			return false;
		}
		const diag = box.getSize(new THREE.Vector3()).length();
		const padding = Math.max(0.15, diag * 0.08);
		this.boxScene = padBox({
			minX: box.min.x,
			maxX: box.max.x,
			minY: box.min.y,
			maxY: box.max.y,
			minZ: box.min.z,
			maxZ: box.max.z,
		}, padding);
		this.boxEnabled = true;
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
		return true;
	}

	setBoxMm(boundsMm: SectionBoxBounds | undefined): void {
		if (!boundsMm) {
			this.boxEnabled = false;
			this.boxScene = undefined;
		} else {
			this.boxScene = projectBoxToScene(boundsMm, this.scale, this.offset);
			this.boxEnabled = true;
		}
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
	}

	resetBox(): void {
		this.boxScene = this.defaultSceneBox();
		this.boxEnabled = true;
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
	}

	setPlanePickMode(active: boolean): void {
		if (active === this.planePickMode) {
			return;
		}
		this.planePickMode = active;
		this.updateCursor();
		this.options.onPickModeChanged?.(active);
	}

	addAxisPlane(axis: SectionAxis): SectionPlaneSpec {
		const center = this.modelCenterScene();
		const projectNormal: [number, number, number] = axis === 'x' ? [1, 0, 0] : axis === 'y' ? [0, 1, 0] : [0, 0, 1];
		const sceneNormal = projectNormalToScene(projectNormal);
		const spec: SectionPlaneSpec = {
			id: `plane-${++this.planeCounter}`,
			normal: sceneNormal,
			point: [center.x, center.y, center.z],
			axis,
			flipped: false,
		};
		this.planesScene.push(spec);
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
		return scenePlaneToProject(spec, this.scale, this.offset);
	}

	addPlaneFromSceneHit(point: THREE.Vector3, normal: THREE.Vector3): SectionPlaneSpec {
		const n = normal.clone().normalize();
		if (n.lengthSq() < 1e-6) {
			n.set(0, 1, 0);
		}
		// Negate surface outward normal so the section cuts into the picked solid from that face.
		n.negate();
		const spec: SectionPlaneSpec = {
			id: `plane-${++this.planeCounter}`,
			normal: [n.x, n.y, n.z],
			point: [point.x, point.y, point.z],
			axis: 'face',
			flipped: false,
		};
		this.planesScene.push(spec);
		if (this.planePickMode) {
			this.planePickMode = false;
			this.options.onPickModeChanged?.(false);
		}
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.updateCursor();
		this.options.onCommit?.(this.getState());
		return scenePlaneToProject(spec, this.scale, this.offset);
	}

	flipPlane(id: string): void {
		const index = this.planesScene.findIndex(p => p.id === id);
		if (index < 0) {
			return;
		}
		this.planesScene[index] = flipPlaneSpec(this.planesScene[index]);
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
	}

	removePlane(id: string): void {
		const before = this.planesScene.length;
		this.planesScene = this.planesScene.filter(p => p.id !== id);
		if (this.planesScene.length !== before) {
			this.syncClipPlanes();
			this.rebuildGizmos();
			this.options.onCommit?.(this.getState());
		}
	}

	clearPlanes(): void {
		if (!this.planesScene.length && !this.planePickMode) {
			return;
		}
		this.planesScene = [];
		if (this.planePickMode) {
			this.planePickMode = false;
			this.options.onPickModeChanged?.(false);
		}
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.updateCursor();
		this.options.onCommit?.(this.getState());
	}

	getState(): SectionState {
		return {
			boxEnabled: this.boxEnabled,
			box: this.boxScene ? sceneBoxToProject(this.boxScene, this.scale, this.offset) : undefined,
			planes: this.planesScene.map(p => scenePlaneToProject(p, this.scale, this.offset)),
		};
	}

	setState(state: SectionState): void {
		this.applyMmStateInternal(state);
		this.syncClipPlanes();
		this.rebuildGizmos();
		this.options.onCommit?.(this.getState());
	}

	/** Sets `material.clippingPlanes` on all meshes under `root` to this controller's live plane array. */
	applyToObject(root: THREE.Object3D): void {
		root.traverse(obj => {
			if (obj === this.gizmoGroup) {
				return;
			}
			const mat = (obj as THREE.Mesh).material;
			if (!mat) {
				return;
			}
			const list = Array.isArray(mat) ? mat : [mat];
			for (const m of list) {
				if (m.clippingPlanes !== this.clipPlanes) {
					m.clippingPlanes = this.clipPlanes;
					m.needsUpdate = true;
				}
			}
		});
	}

	/** Scales face/plane handles based on camera distance so they remain consistent on screen. */
	updateScale(camera: THREE.Camera): void {
		if (!this.handles.length) {
			return;
		}
		const ortho = (camera as THREE.OrthographicCamera).isOrthographicCamera ? (camera as THREE.OrthographicCamera) : undefined;
		const orthoScale = ortho ? Math.max(0.05, (ortho.top - ortho.bottom) / (2 * ortho.zoom) * 0.045) : 0;
		for (const handle of this.handles) {
			const s = ortho ? orthoScale : Math.max(0.04, handle.origin.distanceTo(camera.position) * 0.032);
			handle.group.scale.setScalar(s);
		}
	}

	consumeJustDragged(): boolean {
		const was = this.justDragged;
		this.justDragged = false;
		return was;
	}

	onPointerDown(e: PointerEvent): boolean {
		if (e.button !== 0 || this.planePickMode || !this.hitMeshes.length) {
			return false;
		}
		this.setRayFromEvent(e);
		const hits = this.raycaster.intersectObjects(this.hitMeshes, false);
		const hit = hits[0];
		if (!hit) {
			return false;
		}
		const meta = this.handles.find(h => h.hitMesh === hit.object || h.group.children.includes(hit.object));
		if (!meta) {
			return false;
		}
		const t0 = this.computeRayT(meta.origin, meta.axisDir);
		if (t0 === undefined) {
			return false;
		}
		if (meta.target.kind === 'box' && this.boxScene) {
			this.drag = {
				kind: 'box',
				face: meta.target.face,
				origin: meta.origin.clone(),
				axisDir: meta.axisDir.clone(),
				t0,
				initialValue: this.boxScene[meta.target.face],
				moved: false,
			};
		} else if (meta.target.kind === 'plane') {
			const planeId = meta.target.id;
			const spec = this.planesScene.find(p => p.id === planeId);
			if (!spec) {
				return false;
			}
			this.drag = {
				kind: 'plane',
				id: spec.id,
				origin: meta.origin.clone(),
				axisDir: meta.axisDir.clone(),
				t0,
				initialPoint: spec.point,
				moved: false,
			};
		} else {
			return false;
		}
		this.hoveredKey = meta.key;
		this.options.setControlsEnabled(false);
		this.applyHoverVisuals();
		this.updateCursor();
		return true;
	}

	onPointerMove(e: PointerEvent): boolean {
		this.setRayFromEvent(e);
		if (this.drag) {
			const t = this.computeRayT(this.drag.origin, this.drag.axisDir);
			if (t !== undefined) {
				const delta = t - this.drag.t0;
				if (Math.abs(delta) > 1e-4) {
					this.drag.moved = true;
				}
				if (this.drag.kind === 'box' && this.boxScene) {
					this.boxScene = moveFace(this.boxScene, this.drag.face, this.drag.initialValue + delta, 0.05);
				} else if (this.drag.kind === 'plane') {
					const dragId = this.drag.id;
					const idx = this.planesScene.findIndex(p => p.id === dragId);
					if (idx >= 0) {
						const spec = this.planesScene[idx];
						const dir = this.drag.axisDir;
						this.planesScene[idx] = {
							...spec,
							point: [
								this.drag.initialPoint[0] + dir.x * delta,
								this.drag.initialPoint[1] + dir.y * delta,
								this.drag.initialPoint[2] + dir.z * delta,
							],
						};
					}
				}
				this.syncClipPlanes();
				this.rebuildGizmos();
				this.options.onLiveChange?.(this.getState());
			}
			return true;
		}
		if (this.planePickMode || !this.hitMeshes.length) {
			if (this.hoveredKey !== undefined) {
				this.hoveredKey = undefined;
				this.applyHoverVisuals();
				this.updateCursor();
			}
			return false;
		}
		const hits = this.raycaster.intersectObjects(this.hitMeshes, false);
		const hit = hits[0];
		const meta = hit ? this.handles.find(h => h.hitMesh === hit.object) : undefined;
		const nextKey = meta?.key;
		if (nextKey !== this.hoveredKey) {
			this.hoveredKey = nextKey;
			this.applyHoverVisuals();
			this.updateCursor();
		}
		return false;
	}

	onPointerUp(): boolean {
		if (!this.drag) {
			return false;
		}
		this.drag = undefined;
		this.justDragged = true;
		this.options.setControlsEnabled(true);
		this.applyHoverVisuals();
		this.updateCursor();
		this.options.onCommit?.(this.getState());
		return true;
	}

	cancelDrag(): void {
		if (!this.drag) {
			return;
		}
		this.drag = undefined;
		this.options.setControlsEnabled(true);
		this.applyHoverVisuals();
		this.updateCursor();
	}

	dispose(): void {
		this.cancelDrag();
		this.clearGizmos();
		this.hitSphereGeo.dispose();
		this.clipPlanes.length = 0;
	}

	private applyMmStateInternal(state: SectionState): void {
		this.boxEnabled = state.boxEnabled;
		this.boxScene = state.box ? projectBoxToScene(state.box, this.scale, this.offset) : (state.boxEnabled ? this.defaultSceneBox() : undefined);
		this.planesScene = state.planes.map((p, idx) => {
			const n = Number(p.id.replace(/^plane-/, ''));
			if (Number.isFinite(n)) {
				this.planeCounter = Math.max(this.planeCounter, n);
			} else {
				this.planeCounter = Math.max(this.planeCounter, idx + 1);
			}
			return {
				...p,
				normal: projectNormalToScene(p.normal),
				point: projectPointToScene(p.point, this.scale, this.offset),
			};
		});
	}

	private defaultSceneBox(): SectionBoxBounds {
		const box = this.modelBoundsScene;
		if (!box || box.isEmpty()) {
			return { minX: -5, maxX: 5, minY: -1, maxY: 10, minZ: -5, maxZ: 5 };
		}
		const diag = box.getSize(new THREE.Vector3()).length();
		const pad = Math.max(0.15, diag * 0.03);
		return padBox({
			minX: box.min.x,
			maxX: box.max.x,
			minY: box.min.y,
			maxY: box.max.y,
			minZ: box.min.z,
			maxZ: box.max.z,
		}, pad);
	}

	private modelCenterScene(): THREE.Vector3 {
		if (this.modelBoundsScene && !this.modelBoundsScene.isEmpty()) {
			return this.modelBoundsScene.getCenter(new THREE.Vector3());
		}
		return new THREE.Vector3(0, 0, 0);
	}

	private syncClipPlanes(): void {
		this.clipPlanes.length = 0;
		if (this.boxEnabled && this.boxScene) {
			for (const eq of boxToClipPlanes(this.boxScene)) {
				this.clipPlanes.push(new THREE.Plane(new THREE.Vector3(eq.normal[0], eq.normal[1], eq.normal[2]), eq.constant));
			}
		}
		for (const spec of this.planesScene) {
			const eq = planeSpecToEquation(spec);
			this.clipPlanes.push(new THREE.Plane(new THREE.Vector3(eq.normal[0], eq.normal[1], eq.normal[2]), eq.constant));
		}
	}

	private clearGizmos(): void {
		this.handles = [];
		this.hitMeshes = [];
		for (const child of [...this.gizmoGroup.children]) {
			this.gizmoGroup.remove(child);
			disposeObject(child);
		}
	}

	private rebuildGizmos(): void {
		this.clearGizmos();
		const up = new THREE.Vector3(0, 1, 0);
		if (this.boxEnabled && this.boxScene) {
			const b = clampBoxBounds(this.boxScene);
			const min = new THREE.Vector3(b.minX, b.minY, b.minZ);
			const max = new THREE.Vector3(b.maxX, b.maxY, b.maxZ);
			const box3 = new THREE.Box3(min, max);
			const corners = [
				new THREE.Vector3(b.minX, b.minY, b.minZ),
				new THREE.Vector3(b.maxX, b.minY, b.minZ),
				new THREE.Vector3(b.maxX, b.maxY, b.minZ),
				new THREE.Vector3(b.minX, b.maxY, b.minZ),
				new THREE.Vector3(b.minX, b.minY, b.maxZ),
				new THREE.Vector3(b.maxX, b.minY, b.maxZ),
				new THREE.Vector3(b.maxX, b.maxY, b.maxZ),
				new THREE.Vector3(b.minX, b.maxY, b.maxZ),
			];
			const edgeIdx = [0, 1, 1, 2, 2, 3, 3, 0, 4, 5, 5, 6, 6, 7, 7, 4, 0, 4, 1, 5, 2, 6, 3, 7];
			const edgePts = edgeIdx.map(i => corners[i]);
			const wireGeo = new THREE.BufferGeometry().setFromPoints(edgePts);
			const wireMat = new THREE.LineBasicMaterial({
				color: this.accentColor,
				transparent: true,
				opacity: 0.85,
				clippingPlanes: NO_CLIP,
			});
			this.gizmoGroup.add(new THREE.LineSegments(wireGeo, wireMat));

			const size = box3.getSize(new THREE.Vector3());
			for (const face of SECTION_FACES) {
				const c = faceCenter(b, face);
				const origin = new THREE.Vector3(c[0], c[1], c[2]);
				const normalArr = faceNormal(face);
				const normal = new THREE.Vector3(normalArr[0], normalArr[1], normalArr[2]);
				// Positive coordinate axis so ray delta matches coordinate delta directly.
				const axisDir = face.endsWith('X') ? new THREE.Vector3(1, 0, 0)
					: face.endsWith('Y') ? new THREE.Vector3(0, 1, 0)
						: new THREE.Vector3(0, 0, 1);

				const [w, h] = face.endsWith('X') ? [size.z, size.y]
					: face.endsWith('Y') ? [size.x, size.z]
						: [size.x, size.y];
				const overlayMat = new THREE.MeshBasicMaterial({
					color: this.hoverColor,
					transparent: true,
					opacity: 0,
					side: THREE.DoubleSide,
					depthWrite: false,
					clippingPlanes: NO_CLIP,
				});
				const faceOverlay = new THREE.Mesh(new THREE.PlaneGeometry(Math.max(w, 0.05), Math.max(h, 0.05)), overlayMat);
				faceOverlay.position.copy(origin);
				if (face.endsWith('X')) {
					faceOverlay.rotation.y = Math.PI / 2;
				} else if (face.endsWith('Y')) {
					faceOverlay.rotation.x = Math.PI / 2;
				}
				this.gizmoGroup.add(faceOverlay);

				const handleGroup = new THREE.Group();
				handleGroup.position.copy(origin);
				handleGroup.quaternion.setFromUnitVectors(up, normal);
				const mats: THREE.MeshBasicMaterial[] = [];
				const discMat = new THREE.MeshBasicMaterial({ color: this.accentColor, depthTest: false, clippingPlanes: NO_CLIP });
				const tipMat = new THREE.MeshBasicMaterial({ color: this.accentColor, depthTest: false, clippingPlanes: NO_CLIP });
				mats.push(discMat, tipMat);

				const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.05, 16), discMat);
				const outCone = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.22, 12), tipMat);
				outCone.position.y = 0.18;
				const inCone = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.22, 12), tipMat);
				inCone.rotation.x = Math.PI;
				inCone.position.y = -0.18;

				const hitMat = new THREE.MeshBasicMaterial({ visible: false, clippingPlanes: NO_CLIP });
				const hitMesh = new THREE.Mesh(this.hitSphereGeo, hitMat);
				handleGroup.add(disc, outCone, inCone, hitMesh);
				this.gizmoGroup.add(handleGroup);
				this.hitMeshes.push(hitMesh);
				this.handles.push({
					key: `box:${face}`,
					target: { kind: 'box', face },
					origin,
					axisDir,
					group: handleGroup,
					materials: mats,
					faceOverlay,
					hitMesh,
				} as HandleMeta & { hitMesh: THREE.Mesh });
			}
		}

		const sphere = this.modelBoundsScene && !this.modelBoundsScene.isEmpty()
			? this.modelBoundsScene.getBoundingSphere(new THREE.Sphere())
			: new THREE.Sphere(new THREE.Vector3(), 5);
		const halfSpan = Math.max(sphere.radius * 1.15, 2.5);

		for (const spec of this.planesScene) {
			const n = new THREE.Vector3(spec.normal[0], spec.normal[1], spec.normal[2]).normalize();
			const point = new THREE.Vector3(spec.point[0], spec.point[1], spec.point[2]);
			const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, point);
			// Center visual plane outline over the model along the plane so off-center picks frame the model.
			const quadCenter = plane.projectPoint(sphere.center, new THREE.Vector3());

			const tangentA = new THREE.Vector3().crossVectors(n, Math.abs(n.y) < 0.9 ? up : new THREE.Vector3(1, 0, 0)).normalize();
			const tangentB = new THREE.Vector3().crossVectors(n, tangentA).normalize();
			const corners = [
				quadCenter.clone().addScaledVector(tangentA, -halfSpan).addScaledVector(tangentB, -halfSpan),
				quadCenter.clone().addScaledVector(tangentA, halfSpan).addScaledVector(tangentB, -halfSpan),
				quadCenter.clone().addScaledVector(tangentA, halfSpan).addScaledVector(tangentB, halfSpan),
				quadCenter.clone().addScaledVector(tangentA, -halfSpan).addScaledVector(tangentB, halfSpan),
			];
			const border = new THREE.LineLoop(
				new THREE.BufferGeometry().setFromPoints(corners),
				new THREE.LineBasicMaterial({ color: this.accentColor, transparent: true, opacity: 0.9, clippingPlanes: NO_CLIP }),
			);
			this.gizmoGroup.add(border);

			const fillGeo = new THREE.BufferGeometry().setFromPoints([
				corners[0], corners[1], corners[2],
				corners[0], corners[2], corners[3],
			]);
			const fillMat = new THREE.MeshBasicMaterial({
				color: this.accentColor,
				transparent: true,
				opacity: 0.06,
				side: THREE.DoubleSide,
				depthWrite: false,
				clippingPlanes: NO_CLIP,
			});
			this.gizmoGroup.add(new THREE.Mesh(fillGeo, fillMat));

			const handleOrigin = spec.axis === 'face' ? point : quadCenter;
			const handleGroup = new THREE.Group();
			handleGroup.position.copy(handleOrigin);
			handleGroup.quaternion.setFromUnitVectors(up, n);
			const mat = new THREE.MeshBasicMaterial({ color: this.accentColor, depthTest: false, clippingPlanes: NO_CLIP });
			const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.4, 10), mat);
			stem.position.y = 0.2;
			const cone = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.28, 12), mat);
			cone.position.y = 0.52;
			const backCone = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.2, 12), mat);
			backCone.rotation.x = Math.PI;
			backCone.position.y = -0.14;
			const hitMat = new THREE.MeshBasicMaterial({ visible: false, clippingPlanes: NO_CLIP });
			const hitMesh = new THREE.Mesh(this.hitSphereGeo, hitMat);
			handleGroup.add(stem, cone, backCone, hitMesh);
			this.gizmoGroup.add(handleGroup);
			this.hitMeshes.push(hitMesh);
			this.handles.push({
				key: `plane:${spec.id}`,
				target: { kind: 'plane', id: spec.id },
				origin: handleOrigin,
				axisDir: n.clone(),
				group: handleGroup,
				materials: [mat],
				faceOverlay: undefined,
				hitMesh,
			} as HandleMeta & { hitMesh: THREE.Mesh });
		}

		this.applyHoverVisuals();
		this.updateScale(this.options.camera());
	}

	private applyHoverVisuals(): void {
		const activeKey = this.drag
			? (this.drag.kind === 'box' ? `box:${this.drag.face}` : `plane:${this.drag.id}`)
			: this.hoveredKey;
		for (const handle of this.handles) {
			const active = handle.key === activeKey;
			const color = active ? this.hoverColor : this.accentColor;
			for (const mat of handle.materials) {
				mat.color.set(color);
			}
			if (handle.faceOverlay) {
				const overlayMat = handle.faceOverlay.material as THREE.MeshBasicMaterial;
				overlayMat.opacity = active ? 0.14 : 0;
			}
		}
	}

	private updateCursor(): void {
		const dom = this.options.domElement();
		if (this.drag) {
			dom.style.cursor = 'grabbing';
		} else if (this.planePickMode) {
			dom.style.cursor = 'crosshair';
		} else if (this.hoveredKey) {
			dom.style.cursor = 'grab';
		} else {
			dom.style.cursor = '';
		}
	}

	private setRayFromEvent(e: PointerEvent): void {
		const rect = this.options.domElement().getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((e.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1,
			-((e.clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1,
		);
		this.raycaster.setFromCamera(ndc, this.options.camera());
	}

	private computeRayT(origin: THREE.Vector3, axisDir: THREE.Vector3): number | undefined {
		const ray = this.raycaster.ray;
		return dragAxisParameter(
			[ray.origin.x, ray.origin.y, ray.origin.z],
			[ray.direction.x, ray.direction.y, ray.direction.z],
			[origin.x, origin.y, origin.z],
			[axisDir.x, axisDir.y, axisDir.z],
		);
	}
}
