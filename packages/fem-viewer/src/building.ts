/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

import * as THREE from 'three';
import * as OBC from '@thatopen/components';
import * as FRAGS from '@thatopen/fragments';
import { usableTheme } from './theme.js';

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
}

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
	 * to IFC GlobalIds. The camera keeps its place after the first load.
	 */
	load(ifc: Uint8Array, ids: Readonly<Record<string, string>>): Promise<void>;
	setSelection(elementId: string | undefined): Promise<void>;
	setTheme(theme: Partial<BuildingViewerTheme>): Promise<void>;
	fit(): Promise<void>;
	/** Call when the container changes size without the browser reporting it. */
	layout(): void;
	dispose(): void;
}

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
};

const CATEGORIES: readonly [keyof BuildingViewerTheme, RegExp][] = [
	['column', /^IFCCOLUMN$/],
	['beam', /^IFCBEAM$/],
	['wall', /^IFCWALL/],
	['slab', /^IFCSLAB$/],
	['footing', /^IFCFOOTING$/],
	['stair', /^IFCSTAIR/],
	['member', /^IFCMEMBER$/],
];

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
	private selection: string | undefined;
	/** The element drawn as selected now (its colour is restored when deselected). */
	private highlighted: number | undefined;
	/** Class colour of every coloured item. */
	private readonly itemColors = new Map<number, string>();
	private fitted = false;

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

	async load(ifc: Uint8Array, ids: Readonly<Record<string, string>>): Promise<void> {
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
		await this.applyColors();
		await this.applySelection();
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
		await this.applySelection();
		await this.fragments.core.update(true);
	}

	async fit(): Promise<void> {
		const box = this.model?.box;
		if (!box || box.isEmpty()) {
			return;
		}
		const sphere = box.getBoundingSphere(new THREE.Sphere());
		const radius = Math.max(sphere.radius, 1);
		const eye = sphere.center.clone().add(new THREE.Vector3(1, 0.8, 1.2).normalize().multiplyScalar(radius * 2.4));
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
		this.components.dispose();
	}

	private applyTheme(): void {
		this.world.scene.config.backgroundColor = new THREE.Color(this.theme.background);
		this.grid.config.color = new THREE.Color(this.theme.grid);
	}

	private material(color: string): FRAGS.MaterialDefinition {
		return { color: new THREE.Color(color), renderedFaces: FRAGS.RenderedFaces.TWO, opacity: 1, transparent: false };
	}

	/**
	 * Colours elements by class, like the floor plan's layers. Fragments keep one highlight per
	 * item, so class colours and the selection are both highlights.
	 */
	private async applyColors(): Promise<void> {
		const model = this.model;
		this.itemColors.clear();
		this.highlighted = undefined;
		if (!model) {
			return;
		}
		const items = await model.getItemsOfCategories(CATEGORIES.map(([, pattern]) => pattern));
		for (const [key, pattern] of CATEGORIES) {
			const ids = Object.entries(items).filter(([category]) => pattern.test(category.toUpperCase())).flatMap(([, list]) => list);
			if (ids.length) {
				ids.forEach(id => this.itemColors.set(id, this.theme[key]));
				await model.highlight(ids, this.material(this.theme[key]));
			}
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
				await model.highlight([this.highlighted], this.material(color));
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
