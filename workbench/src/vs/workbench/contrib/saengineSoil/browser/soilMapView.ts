/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType, getWindow } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { formatNumber, ILatLon, ISoilLocationResult, ISoilReport } from './soilDocument.js';
import { ensureMapLibreStyles, IMapLibreMap, IMapLibreMarker, IMapLibreModule, loadMapLibre } from './mapLibreModule.js';
import { bnbcSuggestion, boreholePoints, formatBtm, formatDms, formatLatLon, formatProjectPoint, gridExtent, IBnbcSuggestion, IMapPoint, inBangladesh, ITileSource, mapState, MapState, OSM_COPYRIGHT_URL, OSM_MAX_ZOOM, offlineNote, outlineProject, outlineRings, parseLatLon, sitePosition } from './soilMap.js';
import { niceStep, svg } from './soilLog.js';

/*
 * The Map view of the soil report: the site and the boreholes on OpenStreetMap tiles (MapLibre
 * GL JS), the building outline from the site's georeference, and a side panel with the
 * coordinates (lat/lon, BTM, project x/y), the GIS exchange with QGIS and the BNBC suggestion.
 * Without tiles (offline, no WebGL) the view draws a plain grid of the project coordinates with
 * the outline and the boreholes instead. The view only shows and asks: every change goes back
 * to the editor (ISoilMapHost), which stores it in the report as one undoable edit.
 */

export interface ISoilMapHost {
	readonly report: ISoilReport;
	readonly location: ISoilLocationResult | undefined;
	/** `missing`: no backend, `computing` while asked. */
	readonly locationState: 'idle' | 'computing' | 'ok' | 'missing' | 'error';
	readonly tiles: ITileSource;
	/** The QGIS found on this computer. */
	readonly qgis: { readonly path: string; readonly version?: string } | undefined;
	/** The selected borehole's index. */
	readonly selected: number | undefined;
	moveSite(position: ILatLon): void;
	setRotation(degrees: number | undefined): void;
	moveBorehole(index: number, position: ILatLon): void;
	/** On the plain grid: the borehole's project position [mm]. */
	moveBoreholeOnGrid(index: number, x: number, y: number): void;
	select(index: number | undefined): void;
	applyBnbc(suggestion: IBnbcSuggestion): void;
	exportGis(format: 'geojson' | 'gpkg'): void;
	importGis(): void;
	openInQgis(): void;
	openLink(url: string): void;
}

/** What the view keeps between renders: where the map looks, and what failed. */
export interface IMapViewState {
	center?: ILatLon;
	zoom?: number;
	tilesFailed?: boolean;
	mapLibreFailed?: boolean;
	/** The answer of "Use My Location" when it failed. */
	geolocationNote?: string;
	coordinateStyle: 'decimal' | 'dms';
}

const DEFAULT_ZOOM = 17;

/** Tile errors without a single tile loaded that count as no tiles. */
const TILE_FAILURES = 3;

export class SoilMapView extends Disposable {

	readonly element: HTMLElement;
	private readonly banner: HTMLElement;
	private readonly mapArea: HTMLElement;
	private readonly panel: HTMLElement;
	private readonly note: HTMLElement;
	private readonly panelDisposables = this._register(new DisposableStore());
	/** The panel's inputs by key, to give the focus back after it is rendered again. */
	private readonly panelInputs = new Map<string, HTMLInputElement>();
	private readonly bannerDisposables = this._register(new DisposableStore());
	private readonly gridDisposables = this._register(new DisposableStore());
	private readonly map = this._register(new MutableDisposable<DisposableStore>());
	private mapInstance: IMapLibreMap | undefined;
	private markers: IMapLibreMarker[] = [];
	private siteMarker: IMapLibreMarker | undefined;
	private module: IMapLibreModule | undefined;
	private loading = false;
	private tileLoaded = false;
	private tileErrors = 0;
	private shown: MapState | undefined;

	constructor(container: HTMLElement, private host: ISoilMapHost, private readonly state: IMapViewState) {
		super();
		this.element = append(container, $('.soil-map-view'));
		this.banner = append(this.element, $('.soil-map-banner', { role: 'status' }));
		const body = append(this.element, $('.soil-map-body'));
		const stage = append(body, $('.soil-map-stage'));
		this.mapArea = append(stage, $('.soil-map-area'));
		this.note = append(stage, $('.soil-map-note', { role: 'note' }));
		const attribution = append(stage, $('.soil-map-attribution'));
		const link = append(attribution, $<HTMLAnchorElement>('a', { href: OSM_COPYRIGHT_URL, role: 'link' }, host.tiles.attribution));
		this._register(addDisposableListener(link, EventType.CLICK, e => {
			e.preventDefault();
			this.host.openLink(OSM_COPYRIGHT_URL);
		}));
		this.panel = append(body, $('.soil-map-panel'));
		const window = getWindow(this.element);
		this._register(addDisposableListener(window, 'online', () => this.update(this.host)));
		this._register(addDisposableListener(window, 'offline', () => this.update(this.host)));
		this.update(host);
	}

	/** Shows the report again (after an edit, new results): the map stays, its points move. */
	update(host: ISoilMapHost): void {
		this.host = host;
		this.renderBanner();
		this.renderPanel();
		const site = sitePosition(host.report, host.location);
		const online = getWindow(this.element).navigator.onLine;
		const state = mapState({ hasSite: !!site, online, mapLibre: !this.state.mapLibreFailed, tilesFailed: !!this.state.tilesFailed });
		if (state !== this.shown) {
			this.shown = state;
			this.map.clear();
			this.mapInstance = undefined;
			this.markers = [];
			this.siteMarker = undefined;
			this.gridDisposables.clear();
			clearNode(this.mapArea);
			this.element.classList.toggle('offline', state !== 'map');
		}
		if (state === 'map') {
			this.note.hidden = true;
			if (!this.mapInstance && !this.loading) {
				void this.startMap(site!);
			} else {
				this.updateMap();
			}
		} else {
			this.note.hidden = false;
			this.note.textContent = state === 'noSite'
				? localize('soil.map.noSite', "The site has no position yet. Enter its coordinates on the right (or paste them from Google Maps or QGIS); the map shows the project coordinates until then.")
				: offlineNote({ online, mapLibre: !this.state.mapLibreFailed, tilesFailed: !!this.state.tilesFailed });
			this.renderGrid();
		}
	}

	/** The map area's size changed. */
	layout(): void {
		this.mapInstance?.resize();
		if (this.shown !== 'map') {
			this.renderGrid();
		}
	}

	// ───────────────────────────── banner ─────────────────────────────

	private renderBanner(): void {
		this.bannerDisposables.clear();
		clearNode(this.banner);
		const suggestion = bnbcSuggestion(this.host.location);
		this.banner.hidden = !suggestion;
		if (!suggestion) {
			return;
		}
		append(this.banner, $(`span.soil-map-banner-icon${ThemeIcon.asCSSSelector(Codicon.lightbulb)}`));
		append(this.banner, $('span.soil-map-banner-text', undefined, suggestion.text));
		const apply = append(this.banner, $<HTMLButtonElement>('button.soil-map-banner-apply', { type: 'button' }, localize('soil.map.apply', "Apply to Project Settings")));
		this.bannerDisposables.add(addDisposableListener(apply, EventType.CLICK, () => this.host.applyBnbc(suggestion)));
	}

	// ───────────────────────────── side panel ─────────────────────────────

	private renderPanel(): void {
		const active = this.panel.ownerDocument.activeElement;
		const focusedKey = active && this.panel.contains(active) ? (active as HTMLElement).dataset.key : undefined;
		this.panelDisposables.clear();
		this.panelInputs.clear();
		clearNode(this.panel);
		const { report, location } = this.host;
		const site = sitePosition(report, location);
		const style = this.state.coordinateStyle;

		const heading = (text: string) => append(this.panel, $('.soil-map-heading', undefined, text));
		const row = (label: string, value: string, title?: string) => {
			const element = append(this.panel, $('.soil-map-row', { title: title ?? '' }));
			append(element, $('span.soil-map-label', undefined, label));
			append(element, $('span.soil-map-value', undefined, value));
			return element;
		};

		heading(localize('soil.map.site', "Site"));
		this.positionInput('site', site, value => this.host.moveSite(value), localize('soil.map.siteAria', "Site latitude and longitude"));
		if (site) {
			row(localize('soil.map.dms', "DMS"), `${formatDms(site.lat, 'lat')}\n${formatDms(site.lon, 'lon')}`);
			if (location?.site?.btm) {
				row(localize('soil.map.btmLabel', "BTM"), formatBtm(location.site.btm), localize('soil.map.btmTitle', "Bangladesh Transverse Mercator (EPSG:9678)"));
			}
			if (!inBangladesh(site)) {
				append(this.panel, $('p.soil-note.warning', undefined, localize('soil.map.outside', "This position is outside Bangladesh: the BNBC location towns do not apply.")));
			}
		}
		row(localize('soil.map.origin', "Project point"), formatProjectPoint(report.site?.x ?? 0, report.site?.y ?? 0), localize('soil.map.originTitle', "The point of the project coordinates at the site's position"));
		this.rotationInput(report.site?.rotation);
		const actions = append(this.panel, $('.soil-map-actions'));
		this.button(actions, Codicon.location, localize('soil.map.useLocation', "Use My Location"), () => this.useMyLocation());
		this.button(actions, Codicon.arrowSwap, style === 'dms' ? localize('soil.map.showDecimal', "Show Decimal Degrees") : localize('soil.map.showDms', "Show Degrees, Minutes, Seconds"), () => {
			this.state.coordinateStyle = style === 'dms' ? 'decimal' : 'dms';
			this.renderPanel();
		});
		if (this.state.geolocationNote) {
			append(this.panel, $('p.soil-note', undefined, this.state.geolocationNote));
		}

		heading(localize('soil.map.boreholes', "Boreholes"));
		const points = boreholePoints(report, location);
		const list = append(this.panel, $('.soil-map-list', { role: 'listbox', 'aria-label': localize('soil.map.boreholes', "Boreholes") }));
		report.boreholes.forEach((borehole, index) => {
			const point = points.find(p => p.index === index);
			const item = append(list, $('.soil-map-item', { role: 'option', tabIndex: 0, 'aria-selected': String(index === this.host.selected) }));
			item.classList.toggle('selected', index === this.host.selected);
			append(item, $('span.soil-map-item-id', undefined, borehole.id));
			append(item, $('span.soil-map-item-detail', undefined, point ? formatLatLon(point, style) : localize('soil.map.unplaced', "not placed: {0}", formatProjectPoint(borehole.x, borehole.y))));
			this.panelDisposables.add(addDisposableListener(item, EventType.CLICK, () => this.host.select(index)));
			this.panelDisposables.add(addDisposableListener(item, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					this.host.select(index);
				}
			}));
		});
		const selected = this.host.selected !== undefined ? report.boreholes[this.host.selected] : undefined;
		if (selected) {
			const point = points.find(p => p.index === this.host.selected);
			heading(localize('soil.map.boreholeHeading', "Borehole {0}", selected.id));
			this.positionInput(`borehole-${this.host.selected}`, point, value => this.host.moveBorehole(this.host.selected!, value), localize('soil.map.boreholeAria', "Latitude and longitude of {0}", selected.id));
			row(localize('soil.map.projectLabel', "Project"), formatProjectPoint(point?.x ?? selected.x, point?.y ?? selected.y));
			if (point?.btm) {
				row(localize('soil.map.btmLabel', "BTM"), formatBtm(point.btm));
			}
			append(this.panel, $('p.soil-note', undefined, point?.own
				? localize('soil.map.ownPosition', "Placed by its own latitude and longitude; dragging it on the map moves both.")
				: localize('soil.map.gridPosition', "Placed from its project coordinates and the site; drag it on the map to give it its own position.")));
		}

		heading(localize('soil.map.gis', "GIS"));
		const gis = append(this.panel, $('.soil-map-actions'));
		this.button(gis, Codicon.export, localize('soil.map.exportGeoJson', "Export GeoJSON..."), () => this.host.exportGis('geojson'));
		this.button(gis, Codicon.export, localize('soil.map.exportGpkg', "Export GeoPackage..."), () => this.host.exportGis('gpkg'));
		this.button(gis, Codicon.cloudDownload, localize('soil.map.import', "Import from GIS..."), () => this.host.importGis());
		if (this.host.qgis?.path) {
			this.button(gis, Codicon.linkExternal, localize('soil.map.openQgis', "Open in QGIS"), () => this.host.openInQgis(), this.host.qgis.version ? localize('soil.map.qgisVersion', "QGIS {0}", this.host.qgis.version) : this.host.qgis.path);
		}
		if (this.host.locationState === 'missing') {
			append(this.panel, $('p.soil-note', undefined, localize('soil.map.noBackend', "The BTM coordinates, the building outline, the nearest BNBC town and the GIS exchange need the SAEngine backend, which is not available in this window.")));
		} else if (this.host.locationState === 'error') {
			append(this.panel, $('p.soil-note.warning', undefined, (location?.problems ?? []).join(' ') || localize('soil.map.locationFailed', "The positions could not be worked out.")));
		}
		for (const problem of this.host.locationState === 'ok' ? location?.problems ?? [] : []) {
			append(this.panel, $('p.soil-note.warning', undefined, problem));
		}
		if (focusedKey) {
			this.panelInputs.get(focusedKey)?.focus();
		}
	}

	private button(container: HTMLElement, icon: ThemeIcon, label: string, run: () => void, title?: string): void {
		const button = append(container, $<HTMLButtonElement>('button.soil-map-button', { type: 'button', title: title ?? '' }));
		append(button, $(ThemeIcon.asCSSSelector(icon)));
		append(button, $('span', undefined, label));
		this.panelDisposables.add(addDisposableListener(button, EventType.CLICK, run));
	}

	/** A lat/lon box: takes what Google Maps, QGIS or a survey sheet gives; Enter or leaving it applies. */
	private positionInput(key: string, value: ILatLon | undefined, store: (value: ILatLon) => void, label: string): void {
		const input = append(this.panel, $<HTMLInputElement>('input.soil-input.soil-map-input', { type: 'text', spellcheck: 'false', 'aria-label': label, placeholder: localize('soil.map.latLonPlaceholder', "23.8103, 90.4125") }));
		input.dataset.key = key;
		this.panelInputs.set(key, input);
		input.value = value ? formatLatLon(value, 'decimal') : '';
		const apply = () => {
			const text = input.value.trim();
			if (!text || value && text === formatLatLon(value, 'decimal')) {
				input.classList.remove('invalid');
				return;
			}
			const parsed = parseLatLon(text);
			input.classList.toggle('invalid', !parsed);
			input.title = parsed ? '' : localize('soil.map.badLatLon', "Give the latitude and longitude, e.g. 23.8103, 90.4125 or 23°48′37″N 90°24′45″E.");
			if (parsed) {
				store(parsed);
			}
		};
		this.panelDisposables.add(addDisposableListener(input, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				apply();
			}
		}));
		this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, apply));
	}

	private rotationInput(value: number | undefined): void {
		const element = append(this.panel, $('.soil-map-row'));
		const label = localize('soil.map.rotation', "Grid bearing");
		append(element, $('span.soil-map-label', { title: localize('soil.map.rotationTitle', "The bearing of the project's +Y axis, clockwise from true north") }, label));
		const control = append(element, $('span.soil-map-value.soil-prop-control'));
		const input = append(control, $<HTMLInputElement>('input.soil-input.number', { type: 'text', spellcheck: 'false', 'aria-label': label }));
		input.dataset.key = 'rotation';
		this.panelInputs.set('rotation', input);
		input.value = typeof value === 'number' ? formatNumber(value, 3) : '';
		input.placeholder = '0';
		append(control, $('span.soil-prop-unit', undefined, '°'));
		this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, () => {
			const text = input.value.trim();
			const number = text ? Number(text) : undefined;
			const valid = number === undefined || Number.isFinite(number) && Math.abs(number) <= 360;
			input.classList.toggle('invalid', !valid);
			if (valid) {
				this.host.setRotation(number);
			}
		}));
	}

	/**
	 * The computer's position, when the window may have it: Electron asks the system (Windows
	 * location services) only when the workbench grants the permission, and otherwise answers
	 * with an error at once. The engineer then types or pastes the coordinates.
	 */
	private useMyLocation(): void {
		const geolocation = getWindow(this.element).navigator.geolocation;
		const unavailable = localize('soil.map.noGeolocation', "Your location is not available to SAEngine on this computer. Enter the site's coordinates (copy them from Google Maps: right-click the place, then the coordinates), or drag the site marker.");
		if (!geolocation) {
			this.state.geolocationNote = unavailable;
			this.renderPanel();
			return;
		}
		geolocation.getCurrentPosition(position => {
			this.state.geolocationNote = localize('soil.map.locationAccuracy', "Your location, to about {0} m.", formatNumber(position.coords.accuracy, 0));
			this.host.moveSite({ lat: position.coords.latitude, lon: position.coords.longitude });
		}, () => {
			this.state.geolocationNote = unavailable;
			this.renderPanel();
		}, { timeout: 10000, maximumAge: 600000 });
	}

	// ───────────────────────────── the map ─────────────────────────────

	private async startMap(site: ILatLon): Promise<void> {
		this.loading = true;
		let module: IMapLibreModule;
		try {
			module = this.module ??= await loadMapLibre();
		} catch {
			this.loading = false;
			this.state.mapLibreFailed = true;
			if (!this._store.isDisposed) {
				this.update(this.host);
			}
			return;
		}
		this.loading = false;
		if (this._store.isDisposed || this.shown !== 'map') {
			return;
		}
		ensureMapLibreStyles(this.element.ownerDocument);
		const store = new DisposableStore();
		this.map.value = store;
		const container = append(this.mapArea, $('.soil-map-canvas'));
		const center = this.state.center ?? site;
		let map: IMapLibreMap;
		try {
			map = new module.Map({
				container,
				style: {
					version: 8,
					sources: { tiles: { type: 'raster', tiles: [this.host.tiles.url], tileSize: 256, maxzoom: OSM_MAX_ZOOM } },
					layers: [{ id: 'tiles', type: 'raster', source: 'tiles' }],
				},
				center: [center.lon, center.lat],
				zoom: this.state.zoom ?? DEFAULT_ZOOM,
				maxZoom: OSM_MAX_ZOOM,
				attributionControl: false,
				refreshExpiredTiles: false,
				dragRotate: false,
				pitchWithRotate: false,
			});
		} catch {
			this.state.mapLibreFailed = true; // no WebGL
			this.update(this.host);
			return;
		}
		this.mapInstance = map;
		store.add(toDisposable(() => {
			const c = map.getCenter();
			this.state.center = { lat: c.lat, lon: c.lng };
			this.state.zoom = map.getZoom();
			map.remove();
		}));
		map.addControl(new module.NavigationControl({ showCompass: false }), 'top-left');
		map.addControl(new module.ScaleControl({ unit: 'metric', maxWidth: 120 }), 'bottom-left');
		map.on('data', e => {
			if (e.sourceId === 'tiles' && e.tile) {
				this.tileLoaded = true;
			}
		});
		map.on('error', () => {
			// A tile that does not come (offline, blocked, the server refused): after a few with
			// none loaded, the plain grid replaces the map.
			if (!this.tileLoaded && ++this.tileErrors >= TILE_FAILURES && !this.state.tilesFailed) {
				this.state.tilesFailed = true;
				this.update(this.host);
			}
		});
		map.on('load', () => {
			// The theme's chart blue (MapLibre paints with colours, not CSS variables).
			const blue = getWindow(this.element).getComputedStyle(this.element).getPropertyValue('--vscode-charts-blue').trim() || 'rgb(44, 111, 190)';
			map.addSource('outline', { type: 'geojson', data: this.outlineData() });
			map.addLayer({ id: 'outline-fill', type: 'fill', source: 'outline', paint: { 'fill-color': blue, 'fill-opacity': 0.12 } });
			map.addLayer({ id: 'outline-line', type: 'line', source: 'outline', paint: { 'line-color': blue, 'line-width': 2 } });
			this.updateMap();
		});
		this.updateMap();
	}

	private outlineData(): object {
		return {
			type: 'FeatureCollection',
			features: outlineRings(this.host.location).map(ring => ({
				type: 'Feature', properties: {},
				geometry: { type: 'Polygon', coordinates: [ring] },
			})),
		};
	}

	/** Places the site, the boreholes and the outline on the map. */
	private updateMap(): void {
		const map = this.mapInstance;
		const module = this.module;
		if (!map || !module) {
			return;
		}
		(map.getSource('outline'))?.setData(this.outlineData());
		const site = sitePosition(this.host.report, this.host.location);
		if (site) {
			if (!this.siteMarker) {
				const element = $('.soil-map-site', { role: 'button', 'aria-label': localize('soil.map.siteMarker', "Site (drag to move)"), title: localize('soil.map.siteMarker', "Site (drag to move)") });
				append(element, $(ThemeIcon.asCSSSelector(Codicon.location)));
				this.siteMarker = new module.Marker({ element, draggable: true, anchor: 'bottom' }).setLngLat([site.lon, site.lat]).addTo(map);
				const marker = this.siteMarker;
				marker.on('dragend', () => {
					const p = marker.getLngLat();
					this.host.moveSite({ lat: p.lat, lon: p.lng });
				});
			} else {
				this.siteMarker.setLngLat([site.lon, site.lat]);
			}
		}
		for (const marker of this.markers) {
			marker.remove();
		}
		this.markers = boreholePoints(this.host.report, this.host.location).map(point => this.boreholeMarker(module, map, point));
	}

	private boreholeMarker(module: IMapLibreModule, map: IMapLibreMap, point: IMapPoint): IMapLibreMarker {
		const element = $('.soil-map-borehole', { role: 'button', tabIndex: 0, 'aria-label': localize('soil.map.boreholeMarker', "{0} (drag to move)", point.id), title: `${point.id}\n${formatLatLon(point)}` });
		element.classList.toggle('selected', point.index === this.host.selected);
		append(element, $('span.soil-map-borehole-dot'));
		append(element, $('span.soil-map-borehole-id', undefined, point.id));
		const marker = new module.Marker({ element, draggable: true, anchor: 'center' }).setLngLat([point.lon, point.lat]).addTo(map);
		let dragged = false;
		marker.on('dragstart', () => dragged = true);
		marker.on('dragend', () => {
			const p = marker.getLngLat();
			this.host.moveBorehole(point.index, { lat: p.lat, lon: p.lng });
		});
		element.addEventListener('click', () => {
			if (!dragged) {
				this.host.select(point.index);
			}
			dragged = false;
		});
		return marker;
	}

	// ───────────────────────────── the plain grid ─────────────────────────────

	/** The project coordinates as a plain grid: the outline, the site's project point and the boreholes (drag to move). */
	private renderGrid(): void {
		this.gridDisposables.clear();
		clearNode(this.mapArea);
		const { report, location } = this.host;
		const width = Math.max(320, this.mapArea.clientWidth || 640);
		const height = Math.max(260, this.mapArea.clientHeight || 420);
		const outline = [outlineProject(location)].filter(ring => ring.length > 2);
		const origin = { x: report.site?.x ?? 0, y: report.site?.y ?? 0 };
		const extent = gridExtent([...report.boreholes, ...outline.flat(), origin]);
		const pad = 28;
		const scale = Math.min((width - 2 * pad) / (extent.maxX - extent.minX), (height - 2 * pad) / (extent.maxY - extent.minY));
		const cx = (extent.minX + extent.maxX) / 2;
		const cy = (extent.minY + extent.maxY) / 2;
		const px = (x: number) => width / 2 + (x - cx) * scale;
		const py = (y: number) => height / 2 - (y - cy) * scale;
		const root = svg(this.mapArea, 'svg', { width, height, viewBox: `0 0 ${width} ${height}`, class: 'soil-site-grid', role: 'img', 'aria-label': localize('soil.map.gridAria', "The site in project coordinates") });
		const step = niceStep((extent.maxX - extent.minX) / 1000, 8) * 1000;
		for (let x = Math.ceil(extent.minX / step) * step; x <= extent.maxX; x += step) {
			svg(root, 'line', { x1: px(x), x2: px(x), y1: 0, y2: height, class: 'soil-grid' });
			svg(root, 'text', { x: px(x) + 3, y: height - 6, class: 'soil-tick' }, formatNumber(x / 1000, 1));
		}
		for (let y = Math.ceil(extent.minY / step) * step; y <= extent.maxY; y += step) {
			svg(root, 'line', { x1: 0, x2: width, y1: py(y), y2: py(y), class: 'soil-grid' });
			svg(root, 'text', { x: 4, y: py(y) - 3, class: 'soil-tick' }, formatNumber(y / 1000, 1));
		}
		svg(root, 'text', { x: width - 8, y: height - 6, class: 'soil-heading', 'text-anchor': 'end' }, localize('soil.map.xAxis', "X (m)"));
		svg(root, 'text', { x: 4, y: 14, class: 'soil-heading' }, localize('soil.map.yAxis', "Y (m)"));
		for (const polygon of outline) {
			if (polygon.length > 2) {
				svg(root, 'polygon', { points: polygon.map(p => `${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join(' '), class: 'soil-site-outline' });
			}
		}
		// North: the project's +Y is `rotation` clockwise from north, so north is that much anticlockwise from +Y.
		const north = svg(root, 'g', { class: 'soil-site-north', transform: `translate(${width - 30} 34) rotate(${-(report.site?.rotation ?? 0)})` });
		svg(north, 'path', { d: 'M0 -16 L6 6 L0 2 L-6 6 Z' });
		svg(north, 'text', { x: 0, y: -20, 'text-anchor': 'middle', class: 'soil-heading' }, localize('soil.map.north', "N"));
		const originMark = svg(root, 'g', { class: 'soil-site-origin' });
		svg(originMark, 'path', { d: `M${px(origin.x) - 7} ${py(origin.y)}h14M${px(origin.x)} ${py(origin.y) - 7}v14` });
		svg(originMark, 'title', {}, localize('soil.map.originTitle', "The point of the project coordinates at the site's position"));
		report.boreholes.forEach((borehole, index) => {
			const group = svg(root, 'g', { class: index === this.host.selected ? 'soil-site-borehole selected' : 'soil-site-borehole', tabindex: 0, role: 'button', 'aria-label': localize('soil.map.boreholeMarker', "{0} (drag to move)", borehole.id) });
			const circle = svg(group, 'circle', { cx: px(borehole.x), cy: py(borehole.y), r: 6 });
			const label = svg(group, 'text', { x: px(borehole.x) + 9, y: py(borehole.y) + 4, class: 'soil-site-label' }, borehole.id);
			svg(group, 'title', {}, `${borehole.id}: ${formatProjectPoint(borehole.x, borehole.y)}`);
			let drag: { startX: number; startY: number; moved: boolean } | undefined;
			this.gridDisposables.add(addDisposableListener(group, EventType.POINTER_DOWN, (e: PointerEvent) => {
				e.preventDefault();
				group.setPointerCapture(e.pointerId);
				drag = { startX: e.clientX, startY: e.clientY, moved: false };
			}));
			this.gridDisposables.add(addDisposableListener(group, EventType.POINTER_MOVE, (e: PointerEvent) => {
				if (!drag) {
					return;
				}
				const dx = e.clientX - drag.startX;
				const dy = e.clientY - drag.startY;
				drag.moved ||= Math.abs(dx) + Math.abs(dy) > 3;
				circle.setAttribute('cx', String(px(borehole.x) + dx));
				circle.setAttribute('cy', String(py(borehole.y) + dy));
				label.setAttribute('x', String(px(borehole.x) + dx + 9));
				label.setAttribute('y', String(py(borehole.y) + dy + 4));
			}));
			this.gridDisposables.add(addDisposableListener(group, EventType.POINTER_UP, (e: PointerEvent) => {
				const d = drag;
				drag = undefined;
				if (!d) {
					return;
				}
				if (!d.moved) {
					this.host.select(index);
					return;
				}
				// To 10 mm: a drag is not a survey.
				const x = Math.round((borehole.x + (e.clientX - d.startX) / scale) / 10) * 10;
				const y = Math.round((borehole.y - (e.clientY - d.startY) / scale) / 10) * 10;
				this.host.moveBoreholeOnGrid(index, x, y);
			}));
			this.gridDisposables.add(addDisposableListener(group, EventType.KEY_DOWN, (e: KeyboardEvent) => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					this.host.select(index);
				}
			}));
		});
	}
}
