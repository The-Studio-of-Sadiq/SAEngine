/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createTrustedTypesPolicy } from '../../../../base/browser/trustedTypes.js';
import { resolveAmdNodeModulePath } from '../../../../amdX.js';

/*
 * MapLibre GL JS (npm `maplibre-gl`, BSD-3-Clause), loaded by URL on first use like the 3D viewers
 * (saengineFem/browser/viewerModule.ts), so the workbench's startup bundle does not pay for it.
 * Only the part of its API the site map uses is declared here: the map works against these
 * types whether or not the package's own declarations are installed.
 */

const PACKAGE = 'maplibre-gl';

/** The policy name the workbench's Content Security Policy must list under `trusted-types`. */
export const MAP_WORKER_POLICY = 'saengineMapWorker';

export type LngLatLike = [number, number];

export interface IMapLibreEvent {
	readonly type: string;
	readonly sourceId?: string;
	readonly dataType?: string;
	readonly tile?: unknown;
	readonly error?: { readonly message?: string; readonly status?: number };
	readonly lngLat?: { readonly lng: number; readonly lat: number };
}

export interface IMapLibreSource {
	setData(data: object): void;
}

export interface IMapLibreControl {
	onAdd(map: IMapLibreMap): HTMLElement;
	onRemove(): void;
}

export interface IMapLibreMap {
	on(type: string, listener: (event: IMapLibreEvent) => void): this;
	off(type: string, listener: (event: IMapLibreEvent) => void): this;
	once(type: string, listener: (event: IMapLibreEvent) => void): this;
	addControl(control: IMapLibreControl, position?: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'): this;
	addSource(id: string, source: object): this;
	getSource(id: string): IMapLibreSource | undefined;
	addLayer(layer: object): this;
	isStyleLoaded(): boolean | void;
	jumpTo(options: { center?: LngLatLike; zoom?: number }): this;
	fitBounds(bounds: [LngLatLike, LngLatLike], options?: { padding?: number; maxZoom?: number; animate?: boolean }): this;
	project(lngLat: LngLatLike): { readonly x: number; readonly y: number };
	getCenter(): { readonly lng: number; readonly lat: number };
	getZoom(): number;
	resize(): this;
	remove(): void;
}

export interface IMapLibreMarker {
	setLngLat(lngLat: LngLatLike): this;
	getLngLat(): { readonly lng: number; readonly lat: number };
	addTo(map: IMapLibreMap): this;
	remove(): this;
	on(type: 'dragstart' | 'drag' | 'dragend', listener: () => void): this;
	setDraggable(draggable: boolean): this;
	getElement(): HTMLElement;
}

export interface IMapLibreMapOptions {
	readonly container: HTMLElement;
	readonly style: object;
	readonly center: LngLatLike;
	readonly zoom: number;
	readonly maxZoom?: number;
	readonly attributionControl: false;
	/** false: tiles past their expiry are not fetched again while the map is open (the HTTP cache decides). */
	readonly refreshExpiredTiles?: boolean;
	readonly dragRotate?: boolean;
	readonly pitchWithRotate?: boolean;
	readonly fadeDuration?: number;
}

export interface IMapLibreModule {
	readonly Map: new (options: IMapLibreMapOptions) => IMapLibreMap;
	readonly Marker: new (options?: { element?: HTMLElement; draggable?: boolean; anchor?: 'center' | 'bottom' }) => IMapLibreMarker;
	readonly NavigationControl: new (options?: { showCompass?: boolean }) => IMapLibreControl;
	readonly ScaleControl: new (options?: { unit?: 'metric'; maxWidth?: number }) => IMapLibreControl;
	setWorkerUrl(url: string | TrustedScriptURL): void;
}

let mapLibre: Promise<IMapLibreModule> | undefined;

const styled = new WeakSet<Document>();

/** Adds MapLibre's stylesheet to a window's document once (the map may open in an auxiliary window). */
export function ensureMapLibreStyles(targetDocument: Document): void {
	if (styled.has(targetDocument)) {
		return;
	}
	styled.add(targetDocument);
	const link = targetDocument.createElement('link');
	link.rel = 'stylesheet';
	link.href = resolveAmdNodeModulePath(PACKAGE, 'dist/maplibre-gl.css');
	targetDocument.head.appendChild(link);
}

/**
 * Loads MapLibre. Its tile worker is a module worker started from the package's own folder; the
 * workbench enforces Trusted Types, so the worker's URL goes through a policy that only accepts
 * that folder (MapLibre's own fallback, a blob URL, is not allowed).
 */
export function loadMapLibre(): Promise<IMapLibreModule> {
	if (!mapLibre) {
		mapLibre = (async () => {
			const module = await import(/* webpackIgnore: true */ /* @vite-ignore */ `${resolveAmdNodeModulePath(PACKAGE, 'dist/maplibre-gl.mjs')}`) as IMapLibreModule;
			const base = resolveAmdNodeModulePath(PACKAGE, 'dist/');
			const workerUrl = resolveAmdNodeModulePath(PACKAGE, 'dist/maplibre-gl-worker.mjs');
			const policy = createTrustedTypesPolicy(MAP_WORKER_POLICY, {
				createScriptURL(value: string) {
					if (!value.startsWith(base)) {
						throw new Error(`Refusing to start a map worker from ${value}`);
					}
					return value;
				},
			});
			const trusted = policy?.createScriptURL(workerUrl);
			if (trusted) {
				// MapLibre reads the URL as a string (`endsWith`, `new URL`) before it starts the
				// worker with it: give the trusted value a string's methods for that.
				const url = trusted as TrustedScriptURL & { endsWith?: (suffix: string) => boolean };
				url.endsWith = (suffix: string) => workerUrl.endsWith(suffix);
				module.setWorkerUrl(url);
			} else {
				module.setWorkerUrl(workerUrl);
			}
			return module;
		})();
		mapLibre.catch(() => mapLibre = undefined);
	}
	return mapLibre;
}
