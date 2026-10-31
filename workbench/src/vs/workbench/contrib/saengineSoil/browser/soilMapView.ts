/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType, getWindow, isHTMLElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { formatNumber, ILatLon, ISoilLocationResult, ISoilReport, PLANNING_DEFAULT_USE, PlanningNumberKey } from './soilDocument.js';
import { ensureMapLibreStyles, IMapLibreMap, IMapLibreMarker, IMapLibreModule, loadMapLibre } from './mapLibreModule.js';
import { bnbcSuggestion, boreholePoints, boundsOf, spreadLabels, compassPoint, envelopeProject, formatBtm, formatDms, formatLatLon, formatPlotArea, formatProjectPoint, gridExtent, GRID_SIDES, GridSide, gridSideLabel, IBnbcSuggestion, IMapPoint, inBangladesh, IPlotEdit, isGeoreferenced, ITileSource, LengthUnit, mapState, MapState, OSM_COPYRIGHT_URL, OSM_MAX_ZOOM, offlineNote, outlineProject, outlineRings, parseLatLon, parsePlotLength, plotLonLat, plotProject, plotSideLabel, rectanglePlot, roadAfterDelete, sitePosition } from './soilMap.js';
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
	/** Changes the plot (its corners, road side or setbacks) as one undoable edit. */
	editPlot(edit: IPlotEdit): void;
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
	/** The map was framed on the site and all the boreholes once (on its first opening). */
	framed?: boolean;
	/** Frame the plot when the map shows it next (a plot typed in, not drawn on the map). */
	framePlot?: boolean;
	/** The plot being drawn: its corners so far, [lon, lat] on the map or project [x, y] mm on the grid. */
	plotDraft?: { readonly on: 'map' | 'grid'; readonly corners: number[][] };
	/** The plot corner picked (Delete removes it). */
	plotCorner?: number;
	/** What the rectangle form holds, kept while the panel is drawn again. */
	plotForm?: { frontage: string; depth: string; unit: LengthUnit; road: GridSide };
}

const DEFAULT_ZOOM = 17;
/** Past the tiles' own zoom the map enlarges the last tiles: a plot of a few katha fills the view. */
const MAP_MAX_ZOOM = 22;

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
	/** The id label of each borehole marker, moved apart where they would overlap. */
	private readonly markerLabels = new Map<IMapLibreMarker, HTMLElement>();
	private siteMarker: IMapLibreMarker | undefined;
	/** The plot's corners on the map (draggable), and the corners of the plot being drawn. */
	private plotMarkers: IMapLibreMarker[] = [];
	private readonly compass: HTMLElement;
	private module: IMapLibreModule | undefined;
	private loading = false;
	private tileLoaded = false;
	private tileErrors = 0;
	private shown: MapState | undefined;

	constructor(container: HTMLElement, private host: ISoilMapHost, private readonly state: IMapViewState) {
		super();
		this.element = append(container, $('.soil-map-view', { tabIndex: -1 }));
		this.banner = append(this.element, $('.soil-map-banner', { role: 'status' }));
		const body = append(this.element, $('.soil-map-body'));
		const stage = append(body, $('.soil-map-stage'));
		this.mapArea = append(stage, $('.soil-map-area'));
		this.note = append(stage, $('.soil-map-note', { role: 'note' }));
		this.compass = append(stage, $('.soil-map-compass', { role: 'img' }));
		const attribution = append(stage, $('.soil-map-attribution'));
		const link = append(attribution, $<HTMLAnchorElement>('a', { href: OSM_COPYRIGHT_URL, role: 'link' }, host.tiles.attribution));
		this._register(addDisposableListener(link, EventType.CLICK, e => {
			e.preventDefault();
			this.host.openLink(OSM_COPYRIGHT_URL);
		}));
		this.panel = append(body, $('.soil-map-panel'));
		const window = getWindow(this.element);
		this._register(addDisposableListener(this.element, EventType.KEY_DOWN, e => this.onKey(e)));
		this._register(addDisposableListener(window, 'online', () => this.update(this.host)));
		this._register(addDisposableListener(window, 'offline', () => this.update(this.host)));
		this.update(host);
	}

	/** Shows the report again (after an edit, new results): the map stays, its points move. */
	update(host: ISoilMapHost): void {
		this.host = host;
		this.renderBanner();
		this.renderPanel();
		this.renderCompass();
		const site = sitePosition(host.report, host.location);
		const online = getWindow(this.element).navigator.onLine;
		const state = mapState({ hasSite: !!site, online, mapLibre: !this.state.mapLibreFailed, tilesFailed: !!this.state.tilesFailed });
		if (state !== this.shown) {
			this.shown = state;
			this.map.clear();
			this.mapInstance = undefined;
			this.markers = [];
			this.markerLabels.clear();
			this.siteMarker = undefined;
			this.plotMarkers = [];
			if (this.state.plotDraft && this.state.plotDraft.on !== (state === 'map' ? 'map' : 'grid')) {
				this.state.plotDraft = undefined; // drawn in the other view
			}
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
		// The site's own point only: until it is set, the map is centred on the boreholes, and the
		// field stays empty (it would otherwise show a point the site does not have).
		const own = isGeoreferenced(report) ? site : undefined;
		this.positionInput('site', own, value => this.host.moveSite(value), localize('soil.map.siteAria', "Site latitude and longitude"));
		if (!own) {
			append(this.panel, $('p.soil-note', undefined, site
				? localize('soil.map.siteUnsetNear', "Not set yet. The map is centred on the boreholes placed by latitude and longitude ({0}); type the site point to place the project grid.", formatLatLon(site, style))
				: localize('soil.map.siteUnset', "Not set yet: type the site point's latitude and longitude to place the project grid on the map.")));
		}
		if (own) {
			row(localize('soil.map.dms', "DMS"), `${formatDms(own.lat, 'lat')}\n${formatDms(own.lon, 'lon')}`);
			if (location?.site?.btm) {
				row(localize('soil.map.btmLabel', "BTM"), formatBtm(location.site.btm), localize('soil.map.btmTitle', "Bangladesh Transverse Mercator (EPSG:9678)"));
			}
			if (!inBangladesh(own)) {
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

		this.renderPlotPanel(heading, row);
		this.renderPlanningPanel(heading, row);

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
		if (points.length) {
			// A borehole far from the others (or placed after the map was framed) may be off the map.
			this.button(append(this.panel, $('.soil-map-actions')), Codicon.screenFull, localize('soil.map.fitAll', "Show All Boreholes"), () => this.fitAll());
		}
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

	private button(container: HTMLElement, icon: ThemeIcon, label: string, run: () => void, title?: string): HTMLButtonElement {
		const button = append(container, $<HTMLButtonElement>('button.soil-map-button', { type: 'button', title: title ?? '' }));
		append(button, $(ThemeIcon.asCSSSelector(icon)));
		append(button, $('span', undefined, label));
		this.panelDisposables.add(addDisposableListener(button, EventType.CLICK, run));
		return button;
	}

	// ───────────────────────────── the plot ─────────────────────────────

	/**
	 * The plot: drawn on the map or the grid (corners dragged, picked and deleted), or typed as a
	 * rectangle at the project point; its area, sides and the setbacks that leave the buildable
	 * envelope (measured by the backend, saengine.gis.plot).
	 */
	private renderPlotPanel(heading: (text: string) => HTMLElement, row: (label: string, value: string, title?: string) => HTMLElement): void {
		const { report, location } = this.host;
		const plot = location?.plot ?? undefined;
		const own = report.site?.plot;
		const draft = this.state.plotDraft;
		const corners = this.currentCorners();
		heading(localize('soil.plot.heading', "Plot"));
		const drawing = append(this.panel, $('.soil-map-actions'));
		if (draft) {
			append(this.panel, $('p.soil-note', { role: 'status' }, localize('soil.plot.drawing', "Click the corners in order around the plot ({0} so far). Close it with Close Plot or by clicking the first corner; Escape cancels.", draft.corners.length)));
			const close = this.button(drawing, Codicon.check, localize('soil.plot.close', "Close Plot"), () => this.closeDraft());
			close.disabled = draft.corners.length < 3;
			this.button(drawing, Codicon.close, localize('soil.plot.cancel', "Cancel"), () => this.cancelDraft());
		} else {
			this.button(drawing, Codicon.edit, corners.length ? localize('soil.plot.redraw', "Draw Again") : localize('soil.plot.draw', "Draw Plot"), () => this.startDraft(), localize('soil.plot.drawTitle', "Click the plot's corners on the map (or on the project grid)"));
			if (this.state.plotCorner !== undefined && this.state.plotCorner < corners.length) {
				const remove = this.button(drawing, Codicon.trash, localize('soil.plot.deleteCorner', "Delete Corner {0}", this.state.plotCorner + 1), () => this.deleteCorner());
				remove.disabled = corners.length <= 3;
				remove.title = corners.length <= 3 ? localize('soil.plot.keepThree', "A plot needs three corners.") : '';
			}
			if (corners.length) {
				this.button(drawing, Codicon.clearAll, localize('soil.plot.clear', "Clear Plot"), () => {
					this.state.plotCorner = undefined;
					this.host.editPlot({ clear: true });
				});
			}
		}

		if (plot && typeof plot.area === 'number') {
			row(localize('soil.plot.areaLabel', "Area"), formatPlotArea(plot.area, plot.katha ?? 0, plot.decimal ?? 0), localize('soil.plot.areaTitle', "1 katha = 720 sq ft, 1 decimal = 435.6 sq ft"));
			row(localize('soil.plot.perimeter', "Perimeter"), localize('soil.plot.metres', "{0} m", formatNumber((plot.perimeter ?? 0) / 1000, 2)));
			const sides = append(this.panel, $('.soil-map-list.soil-plot-sides', { role: 'list', 'aria-label': localize('soil.plot.sides', "Sides") }));
			for (const side of plot.sides ?? []) {
				const item = append(sides, $('.soil-map-item', { role: 'listitem' }));
				append(item, $('span.soil-map-item-id', undefined, localize('soil.plot.sideNumber', "{0}", side.index + 1)));
				append(item, $('span.soil-map-item-detail', undefined, localize('soil.plot.sideDetail', "{0} m, bearing {1}°, faces {2}{3}", formatNumber(side.length / 1000, 2), formatNumber(side.bearing, 1), side.facing,
					side.kind ? localize('soil.plot.sideSetback', " · {0} {1} m", side.kind === 'front' ? localize('soil.plot.front', "front") : side.kind === 'rear' ? localize('soil.plot.rear', "rear") : localize('soil.plot.side', "side"), formatNumber(side.setback / 1000, 2)) : '')));
			}
			// The road side picks which setback each side takes.
			const roadRow = append(this.panel, $('.soil-map-row'));
			const roadLabel = localize('soil.plot.road', "Road side");
			append(roadRow, $('span.soil-map-label', { title: localize('soil.plot.roadTitle', "The side facing the road: it takes the front setback, the side opposite it the rear") }, roadLabel));
			const roadSelect = append(append(roadRow, $('span.soil-map-value.soil-prop-control')), $<HTMLSelectElement>('select.soil-input', { 'aria-label': roadLabel }));
			roadSelect.dataset.key = 'plotRoad';
			append(roadSelect, $<HTMLOptionElement>('option', { value: '' }, localize('soil.plot.noRoad', "(not set)")));
			for (const side of plot.sides ?? []) {
				const option = append(roadSelect, $<HTMLOptionElement>('option', { value: String(side.index) }, plotSideLabel({ ...side, kind: null })));
				option.selected = side.index === plot.road;
			}
			this.panelDisposables.add(addDisposableListener(roadSelect, EventType.CHANGE, () => this.host.editPlot({ road: roadSelect.value === '' ? null : Number(roadSelect.value) })));
		} else if (corners.length >= 3 && this.host.locationState === 'computing') {
			append(this.panel, $('p.soil-note', undefined, localize('soil.plot.measuring', "Measuring the plot...")));
		}

		// Setbacks [m]: front (the road side), rear, each other side.
		const setbacks = append(this.panel, $('.soil-plot-setbacks'));
		append(setbacks, $('span.soil-map-label', undefined, localize('soil.plot.setbacks', "Setbacks")));
		for (const [key, label] of [['front', localize('soil.plot.setbackFront', "Front")], ['rear', localize('soil.plot.setbackRear', "Rear")], ['side', localize('soil.plot.setbackSide', "Each side")]] as const) {
			const cell = append(setbacks, $('label.soil-plot-setback'));
			append(cell, $('span', undefined, localize('soil.plot.inMetres', "{0} (m)", label)));
			const input = append(cell, $<HTMLInputElement>('input.soil-input.number', { type: 'text', spellcheck: 'false', 'aria-label': localize('soil.plot.setbackAria', "{0} setback in m", label) }));
			input.dataset.key = `plot-${key}`;
			this.panelInputs.set(`plot-${key}`, input);
			const value = own?.[key];
			input.value = typeof value === 'number' ? formatNumber(value / 1000, 3) : '';
			input.placeholder = '0';
			this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, () => {
				const text = input.value.trim();
				const number = text ? Number(text) : 0;
				const valid = Number.isFinite(number) && number >= 0 && number < 1000;
				input.classList.toggle('invalid', !valid);
				if (valid) {
					this.host.editPlot({ [key]: number ? number * 1000 : null });
				}
			}));
		}
		if (plot && typeof plot.envelopeArea === 'number') {
			row(localize('soil.plot.buildable', "Buildable"), localize('soil.plot.buildableArea', "{0} m² inside the setbacks", formatNumber(plot.envelopeArea, 1)), localize('soil.plot.buildableTitle', "The buildable envelope: the plot less its setbacks (dashed)"));
		}

		// A rectangle typed: frontage along the road side, at the project point, along the grid.
		const form = this.state.plotForm ??= { frontage: '', depth: '', unit: 'm', road: '-y' };
		const rectangle = append(this.panel, $('.soil-plot-rectangle'));
		append(rectangle, $('span.soil-map-label', undefined, localize('soil.plot.rectangle', "Or type a rectangle")));
		const sizes = append(rectangle, $('.soil-plot-sizes'));
		const field = (key: 'frontage' | 'depth', label: string) => {
			const cell = append(sizes, $('label.soil-plot-setback'));
			append(cell, $('span', undefined, label));
			const input = append(cell, $<HTMLInputElement>('input.soil-input.number', { type: 'text', spellcheck: 'false', 'aria-label': label }));
			input.dataset.key = `plot-${key}`;
			this.panelInputs.set(`plot-${key}`, input);
			input.value = form[key];
			this.panelDisposables.add(addDisposableListener(input, EventType.INPUT, () => form[key] = input.value));
			return input;
		};
		const frontage = field('frontage', localize('soil.plot.frontage', "Frontage"));
		const depth = field('depth', localize('soil.plot.depth', "Depth"));
		const unit = append(sizes, $<HTMLSelectElement>('select.soil-input', { 'aria-label': localize('soil.plot.unit', "Unit") }));
		for (const value of ['m', 'ft'] as const) {
			const option = append(unit, $<HTMLOptionElement>('option', { value }, value === 'm' ? localize('soil.plot.unitM', "m") : localize('soil.plot.unitFt', "ft")));
			option.selected = form.unit === value;
		}
		this.panelDisposables.add(addDisposableListener(unit, EventType.CHANGE, () => form.unit = unit.value === 'ft' ? 'ft' : 'm'));
		const roadSide = append(rectangle, $<HTMLSelectElement>('select.soil-input', { 'aria-label': localize('soil.plot.roadFacing', "Side facing the road") }));
		const rotation = report.site?.rotation ?? 0;
		for (const side of GRID_SIDES) {
			const option = append(roadSide, $<HTMLOptionElement>('option', { value: side }, localize('soil.plot.roadOn', "Road: {0}", gridSideLabel(side, rotation))));
			option.selected = form.road === side;
		}
		this.panelDisposables.add(addDisposableListener(roadSide, EventType.CHANGE, () => form.road = roadSide.value as GridSide));
		const set = append(rectangle, $('.soil-map-actions'));
		this.button(set, Codicon.check, localize('soil.plot.setRectangle', "Set Rectangle"), () => {
			const f = parsePlotLength(frontage.value, form.unit);
			const d = parsePlotLength(depth.value, form.unit);
			frontage.classList.toggle('invalid', f === undefined);
			depth.classList.toggle('invalid', d === undefined);
			if (f === undefined || d === undefined) {
				return;
			}
			this.state.plotDraft = undefined;
			this.state.plotCorner = undefined;
			this.state.framePlot = true;
			const placed = rectanglePlot(f, d, form.road, { x: report.site?.x ?? 0, y: report.site?.y ?? 0 });
			this.host.editPlot({ points: placed.points, road: placed.road });
			this.updateMap(); // frames the plot, also when it is the one already there
		}, localize('soil.plot.setRectangleTitle', "A rectangle with its lower-left corner at the project point, along the project grid"));
		for (const problem of plot?.problems ?? []) {
			append(this.panel, $('p.soil-note.warning', undefined, problem));
		}
	}

	/** The plot's corners where the plot is shown now: [lon, lat] on the map, project [x, y] on the grid. */
	private currentCorners(): number[][] {
		const { report, location } = this.host;
		return this.shown === 'map' ? plotLonLat(report, location) : plotProject(report, location).map(p => [p.x, p.y]);
	}

	/** Stores `corners` (in the space shown) as the plot, keeping its road side. */
	private storeCorners(corners: number[][], road?: number | null): void {
		const edit: IPlotEdit = this.shown === 'map' ? { lonlat: corners } : { points: corners };
		this.host.editPlot(road === undefined ? edit : { ...edit, road });
	}

	private startDraft(): void {
		this.state.plotDraft = { on: this.shown === 'map' ? 'map' : 'grid', corners: [] };
		this.state.plotCorner = undefined;
		this.update(this.host);
		this.element.focus();
	}

	private cancelDraft(): void {
		this.state.plotDraft = undefined;
		this.update(this.host);
	}

	private closeDraft(): void {
		const draft = this.state.plotDraft;
		if (!draft || draft.corners.length < 3) {
			return;
		}
		this.state.plotDraft = undefined;
		this.state.plotCorner = undefined;
		// A new shape: its sides are new, so the road side is chosen again.
		this.host.editPlot(draft.on === 'map' ? { lonlat: draft.corners, road: null } : { points: draft.corners, road: null });
	}

	/** Adds a corner to the plot being drawn; a click on the first corner closes it. */
	private addDraftCorner(corner: number[]): void {
		const draft = this.state.plotDraft;
		if (!draft) {
			return;
		}
		draft.corners.push(corner);
		this.update(this.host);
	}

	private deleteCorner(): void {
		const index = this.state.plotCorner;
		const corners = this.currentCorners();
		if (index === undefined || index >= corners.length || corners.length <= 3) {
			return;
		}
		this.state.plotCorner = undefined;
		const road = roadAfterDelete(this.host.report.site?.plot?.road, index, corners.length);
		this.storeCorners(corners.filter((_, i) => i !== index), road ?? null);
	}

	private onKey(e: KeyboardEvent): void {
		const target = e.target as HTMLElement | null;
		if (target && (target.tagName === 'INPUT' || target.tagName === 'SELECT')) {
			return;
		}
		if (e.key === 'Escape' && this.state.plotDraft) {
			e.preventDefault();
			this.cancelDraft();
		} else if (e.key === 'Enter' && this.state.plotDraft) {
			e.preventDefault();
			this.closeDraft();
		} else if ((e.key === 'Delete' || e.key === 'Backspace') && this.state.plotCorner !== undefined && !this.state.plotDraft) {
			e.preventDefault();
			this.deleteCorner();
		}
	}

	private pickCorner(index: number): void {
		this.state.plotCorner = this.state.plotCorner === index ? undefined : index;
		this.update(this.host);
	}

	/** True north, and the project +Y axis at the grid bearing. */
	// ───────────────────────────── planning compliance ─────────────────────────────

	/**
	 * Planning compliance of the plot (saengine.gis.planning, the code pack's planning table):
	 * the use and the road width it is checked for, FAR and MGC permitted, the setbacks Table 2
	 * asks for against those entered, and the area statement from the building model (or areas
	 * typed in).
	 */
	private renderPlanningPanel(heading: (text: string) => HTMLElement, row: (label: string, value: string, title?: string) => HTMLElement): void {
		const { report, location } = this.host;
		const own = report.site?.plot?.planning;
		const result = location?.planning ?? undefined;
		heading(localize('soil.planning.heading', "Planning Compliance"));
		if (!own) {
			append(this.panel, $('p.soil-note', undefined, localize('soil.planning.intro', "FAR, ground coverage and setbacks of the plot by the planning rules of the code pack (Dhaka: Imarat Nirman Bidhimala 2008), with the area statement of the building.")));
			this.button(append(this.panel, $('.soil-map-actions')), Codicon.checklist, localize('soil.planning.start', "Check Planning Rules"), () => this.host.editPlot({ planning: { use: PLANNING_DEFAULT_USE } }));
			return;
		}
		if (result?.authority) {
			append(this.panel, $('p.soil-note', { title: result.source ?? '' }, result.authority));
		}
		// The use class.
		const useRow = append(this.panel, $('.soil-map-row'));
		const useLabel = localize('soil.planning.use', "Use");
		append(useRow, $('span.soil-map-label', undefined, useLabel));
		const useSelect = append(append(useRow, $('span.soil-map-value.soil-prop-control')), $<HTMLSelectElement>('select.soil-input', { 'aria-label': useLabel }));
		useSelect.dataset.key = 'planningUse';
		const uses = result?.uses?.length ? result.uses : [{ id: own.use ?? PLANNING_DEFAULT_USE, name: own.use ?? PLANNING_DEFAULT_USE }];
		for (const use of uses) {
			const option = append(useSelect, $<HTMLOptionElement>('option', { value: use.id }, use.name));
			option.selected = use.id === own.use;
		}
		this.panelDisposables.add(addDisposableListener(useSelect, EventType.CHANGE, () => this.host.editPlot({ planning: { use: useSelect.value } })));
		// Numbers: road width, height and storeys (from the building model when empty), areas.
		const numbers = append(this.panel, $('.soil-plot-setbacks.soil-planning-inputs'));
		const field = (key: PlanningNumberKey, label: string, scale: number, placeholder: string, title: string) => {
			const cell = append(numbers, $('label.soil-plot-setback', { title }));
			append(cell, $('span', undefined, label));
			const input = append(cell, $<HTMLInputElement>('input.soil-input.number', { type: 'text', spellcheck: 'false', 'aria-label': label }));
			input.dataset.key = `planning-${key}`;
			this.panelInputs.set(`planning-${key}`, input);
			const value = own[key];
			input.value = typeof value === 'number' ? formatNumber(value / scale, 3) : '';
			input.placeholder = placeholder;
			this.panelDisposables.add(addDisposableListener(input, EventType.CHANGE, () => {
				const text = input.value.trim();
				const number = text ? Number(text) : undefined;
				const valid = number === undefined || (Number.isFinite(number) && number >= 0);
				input.classList.toggle('invalid', !valid);
				if (valid) {
					this.host.editPlot({ planning: { [key]: number === undefined ? null : key === 'storeys' ? Math.round(number) : number * scale } });
				}
			}));
		};
		const measured = (value: number | null | undefined, digits: number) => typeof value === 'number' ? formatNumber(value, digits) : '';
		field('roadWidth', localize('soil.planning.road', "Road width (m)"), 1000, '', localize('soil.planning.roadTitle', "Width of the road the plot faces"));
		field('height', localize('soil.planning.height', "Height (m)"), 1000, measured(result?.height, 1), localize('soil.planning.heightTitle', "Building height above ground; empty: from the building model"));
		field('storeys', localize('soil.planning.storeys', "Storeys"), 1, measured(result?.storeys, 0), localize('soil.planning.storeysTitle', "Empty: from the building model"));
		field('groundCoverage', localize('soil.planning.coverage', "Coverage (m²)"), 1, measured(result?.areas?.groundCoverage, 1), localize('soil.planning.coverageTitle', "Ground coverage; empty: the building model's slabs on plan"));
		field('floorArea', localize('soil.planning.floorArea', "Floor area (m²)"), 1, measured(result?.areas?.grossFloorArea, 1), localize('soil.planning.floorAreaTitle', "Gross floor area; empty: the building model's storeys"));
		field('excludedArea', localize('soil.planning.excluded', "Excluded (m²)"), 1, '0', localize('soil.planning.excludedTitle', "Floor area not counted in FAR (Rule 51(5): stair and lift rooms over the roof, parking, services, ...)"));

		if (this.host.locationState === 'computing' && !result) {
			append(this.panel, $('p.soil-note', undefined, localize('soil.planning.checking', "Checking...")));
		}
		if (!result) {
			return;
		}
		if (typeof result.plotArea === 'number') {
			row(localize('soil.planning.plotRow', "Plot size row"), result.band ?? '');
		}
		const permitted = result.permitted;
		if (permitted?.allowed) {
			row(localize('soil.planning.permitted', "Permitted"), localize('soil.planning.permittedValue', "FAR {0}, MGC {1} %", permitted.farText ?? '', formatNumber(permitted.mgc ?? 0, 1)), permitted.rule ?? '');
		}
		const limits = result.limits;
		const areas = result.areas;
		if (limits || areas) {
			const table = append(this.panel, $('table.soil-planning-statement', { 'aria-label': localize('soil.planning.statement', "Area statement") }));
			const line = (label: string, value: string, limit?: string) => {
				const tr = append(table, $('tr'));
				append(tr, $('td', undefined, label));
				append(tr, $('td.number', undefined, value));
				append(tr, $('td.number', undefined, limit ?? ''));
			};
			const head = append(table, $('tr'));
			append(head, $('th', undefined, localize('soil.planning.statement', "Area statement")));
			append(head, $('th.number', undefined, localize('soil.planning.provided', "Provided")));
			append(head, $('th.number', undefined, localize('soil.planning.limit', "Limit")));
			line(localize('soil.planning.plotArea', "Plot area (m²)"), formatNumber(result.plotArea ?? 0, 1));
			line(localize('soil.planning.coverageRow', "Ground coverage (m²)"), measured(areas?.groundCoverage, 1), limits ? formatNumber(limits.mgcArea, 1) : '');
			line(localize('soil.planning.openRow', "Open space (m²)"), measured(areas?.openSpace, 1), limits ? `≥ ${formatNumber(limits.openSpace, 1)}` : '');
			for (const storey of areas?.storeys ?? []) {
				line(localize('soil.planning.storeyRow', "  {0}", storey.name), formatNumber(storey.area, 1));
			}
			line(localize('soil.planning.grossRow', "Gross floor area (m²)"), measured(areas?.grossFloorArea, 1));
			if (areas?.excluded) {
				line(localize('soil.planning.excludedRow', "Less excluded (m²)"), formatNumber(areas.excluded, 1));
			}
			line(localize('soil.planning.farRow', "Floor area for FAR (m²)"), measured(areas?.farArea, 1), limits ? (limits.floorArea === null ? localize('soil.planning.nr', "not restricted") : formatNumber(limits.floorArea, 1)) : '');
		}
		const list = append(this.panel, $('.soil-map-list.soil-planning-checks', { role: 'list', 'aria-label': localize('soil.planning.checks', "Planning checks") }));
		for (const check of result.checks ?? []) {
			const item = append(list, $('.soil-map-item', { role: 'listitem', title: check.rule }));
			item.classList.toggle('fail', !check.ok);
			append(item, $(`span${ThemeIcon.asCSSSelector(check.ok ? Codicon.pass : Codicon.error)}`));
			const limit = check.limit === null ? localize('soil.planning.nr', "not restricted") : formatNumber(check.limit, 2);
			append(item, $('span.soil-map-item-detail', undefined, localize('soil.planning.checkLine', "{0}: {1} {2} {3} {4}", check.label, formatNumber(check.provided, 2), check.sense, limit, check.unit).trim()));
		}
		for (const note of [...result.problems ?? [], ...result.notes ?? []]) {
			append(this.panel, $('p.soil-note', undefined, note));
		}
		this.button(append(this.panel, $('.soil-map-actions')), Codicon.trash, localize('soil.planning.remove', "Remove Planning Check"), () => this.host.editPlot({ planning: null }));
	}

	private renderCompass(): void {
		clearNode(this.compass);
		const rotation = this.host.report.site?.rotation ?? 0;
		this.compass.setAttribute('aria-label', localize('soil.plot.compassAria', "North; the project +Y axis is at {0}° ({1})", formatNumber(rotation, 1), compassPoint(rotation)));
		this.compass.title = localize('soil.plot.compassTitle', "North is up. The project +Y axis points {0}° clockwise from north (the grid bearing).", formatNumber(rotation, 1));
		const root = svg(this.compass, 'svg', { width: 56, height: 64, viewBox: '-28 -34 56 64' });
		svg(root, 'path', { d: 'M0 -20 L6 4 L0 0 L-6 4 Z', class: 'soil-compass-north' });
		svg(root, 'text', { x: 0, y: -24, 'text-anchor': 'middle', class: 'soil-compass-label' }, localize('soil.map.north', "N"));
		const grid = svg(root, 'g', { transform: `rotate(${rotation})`, class: 'soil-compass-grid' });
		svg(grid, 'line', { x1: 0, y1: 8, x2: 0, y2: -16 });
		svg(grid, 'path', { d: 'M0 -18 L3 -12 L-3 -12 Z' });
		svg(root, 'text', { x: 0, y: 26, 'text-anchor': 'middle', class: 'soil-compass-label grid' }, localize('soil.plot.gridLabel', "+Y {0}°", formatNumber(rotation, 1)));
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
				maxZoom: MAP_MAX_ZOOM,
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
			const style = getWindow(this.element).getComputedStyle(this.element);
			const orange = style.getPropertyValue('--vscode-charts-orange').trim() || 'rgb(209, 134, 22)';
			const green = style.getPropertyValue('--vscode-charts-green').trim() || 'rgb(56, 138, 52)';
			map.addSource('plot', { type: 'geojson', data: this.plotData() });
			map.addLayer({ id: 'plot-fill', type: 'fill', source: 'plot', filter: ['==', ['get', 'kind'], 'plot'], paint: { 'fill-color': orange, 'fill-opacity': 0.08 } });
			map.addLayer({ id: 'plot-line', type: 'line', source: 'plot', filter: ['==', ['get', 'kind'], 'plot'], paint: { 'line-color': orange, 'line-width': 2.5 } });
			map.addLayer({ id: 'plot-envelope', type: 'line', source: 'plot', filter: ['==', ['get', 'kind'], 'envelope'], paint: { 'line-color': green, 'line-width': 1.5, 'line-dasharray': [3, 2] } });
			map.addLayer({ id: 'plot-draft', type: 'line', source: 'plot', filter: ['==', ['get', 'kind'], 'draft'], paint: { 'line-color': orange, 'line-width': 2, 'line-dasharray': [2, 1] } });
			this.updateMap();
			if (!this.state.framed) {
				// The first time: the site and every borehole in view, however far apart.
				this.state.framed = true;
				const points = boreholePoints(this.host.report, this.host.location);
				const bounds = boundsOf([site, ...points]);
				if (bounds) {
					map.fitBounds(bounds, { padding: 60, maxZoom: OSM_MAX_ZOOM - 1, animate: false });
				}
			}
			this.spreadMapLabels();
		});
		map.on('zoomend', () => this.spreadMapLabels());
		map.on('click', e => {
			// A click on a corner marker is the marker's (the first one closes the plot), not a new corner.
			const target = e.originalEvent?.target;
			const onCorner = isHTMLElement(target) && !!target.closest('.soil-map-corner');
			if (this.state.plotDraft?.on === 'map' && e.lngLat && !onCorner) {
				this.addDraftCorner([e.lngLat.lng, e.lngLat.lat]);
			}
		});
		this.updateMap();
	}

	/** Frames the site and every borehole, however far apart. */
	private fitAll(): void {
		const site = sitePosition(this.host.report, this.host.location);
		const bounds = boundsOf([...site ? [site] : [], ...boreholePoints(this.host.report, this.host.location)]);
		if (bounds && this.mapInstance) {
			this.mapInstance.fitBounds(bounds, { padding: 60, maxZoom: OSM_MAX_ZOOM - 1, animate: false });
		}
	}

	/** The plot, its envelope and the plot being drawn, as GeoJSON for the map. */
	private plotData(): object {
		const features: object[] = [];
		const corners = plotLonLat(this.host.report, this.host.location);
		if (corners.length >= 3 && !this.state.plotDraft) {
			features.push({ type: 'Feature', properties: { kind: 'plot' }, geometry: { type: 'Polygon', coordinates: [[...corners, corners[0]]] } });
		}
		const envelope = this.host.location?.plot?.envelopeLonlat;
		if (envelope && envelope.length > 3 && !this.state.plotDraft) {
			features.push({ type: 'Feature', properties: { kind: 'envelope' }, geometry: { type: 'LineString', coordinates: envelope } });
		}
		const draft = this.state.plotDraft?.on === 'map' ? this.state.plotDraft.corners : [];
		if (draft.length >= 2) {
			features.push({ type: 'Feature', properties: { kind: 'draft' }, geometry: { type: 'LineString', coordinates: draft } });
		}
		return { type: 'FeatureCollection', features };
	}

	/** The plot's corners (drag to move, click to pick), or the corners drawn so far. */
	private updatePlotMarkers(module: IMapLibreModule, map: IMapLibreMap): void {
		for (const marker of this.plotMarkers) {
			marker.remove();
		}
		const draft = this.state.plotDraft?.on === 'map' ? this.state.plotDraft.corners : undefined;
		const corners = draft ?? plotLonLat(this.host.report, this.host.location);
		this.plotMarkers = corners.map((corner, index) => {
			const element = $('.soil-map-corner', { role: 'button', tabIndex: 0, 'aria-label': draft ? localize('soil.plot.draftCorner', "Corner {0}", index + 1) : localize('soil.plot.cornerMarker', "Plot corner {0} (drag to move, click to pick)", index + 1) });
			element.classList.toggle('selected', !draft && index === this.state.plotCorner);
			element.classList.toggle('first', !!draft && index === 0 && corners.length >= 3);
			append(element, $('span.soil-map-corner-label', undefined, String(index + 1)));
			const marker = new module.Marker({ element, draggable: !draft, anchor: 'center' }).setLngLat([corner[0], corner[1]]).addTo(map);
			let dragged = false;
			marker.on('dragstart', () => dragged = true);
			marker.on('dragend', () => {
				const p = marker.getLngLat();
				const moved = corners.map((c, i) => i === index ? [p.lng, p.lat] : c);
				this.storeCorners(moved);
			});
			element.addEventListener('click', e => {
				e.stopPropagation(); // not a new corner on the map under it
				if (draft) {
					if (index === 0) {
						this.closeDraft();
					}
				} else if (!dragged) {
					this.pickCorner(index);
				}
				dragged = false;
			});
			return marker;
		});
	}

	/** Moves the borehole ids apart where they would overlap at this zoom. */
	private spreadMapLabels(): void {
		const map = this.mapInstance;
		if (!map) {
			return;
		}
		const labels = this.markers.map(marker => {
			const element = this.markerLabels.get(marker);
			const at = marker.getLngLat();
			const point = map.project([at.lng, at.lat]);
			return { element, box: { x: point.x + 8, y: point.y, width: (element?.offsetWidth ?? 40) + 2 } };
		});
		const offsets = spreadLabels(labels.map(l => l.box), 16);
		labels.forEach((label, i) => {
			if (label.element) {
				label.element.style.transform = offsets[i] ? `translateY(${offsets[i]}px)` : '';
			}
		});
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
		(map.getSource('plot'))?.setData(this.plotData());
		this.updatePlotMarkers(module, map);
		const plot = this.state.framePlot ? boundsOf(plotLonLat(this.host.report, this.host.location).map(([lon, lat]) => ({ lat, lon }))) : undefined;
		if (plot) {
			this.state.framePlot = false;
			map.fitBounds(plot, { padding: 80, maxZoom: MAP_MAX_ZOOM - 1, animate: false });
		}
		this.mapArea.classList.toggle('drawing', this.state.plotDraft?.on === 'map');
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
		this.markerLabels.clear();
		this.markers = boreholePoints(this.host.report, this.host.location).map(point => this.boreholeMarker(module, map, point));
		this.spreadMapLabels();
	}

	private boreholeMarker(module: IMapLibreModule, map: IMapLibreMap, point: IMapPoint): IMapLibreMarker {
		const element = $('.soil-map-borehole', { role: 'button', tabIndex: 0, 'aria-label': localize('soil.map.boreholeMarker', "{0} (drag to move)", point.id), title: `${point.id}\n${formatLatLon(point)}` });
		element.classList.toggle('selected', point.index === this.host.selected);
		append(element, $('span.soil-map-borehole-dot'));
		const label = append(element, $('span.soil-map-borehole-id', undefined, point.id));
		const marker = new module.Marker({ element, draggable: true, anchor: 'center' }).setLngLat([point.lon, point.lat]).addTo(map);
		this.markerLabels.set(marker, label);
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

	/** A plot corner on the grid: drag to move it, click to pick it; while drawing, the first one closes the plot. */
	private gridCorner(root: SVGElement, corner: { readonly x: number; readonly y: number }, index: number, drafting: boolean, count: number, px: (x: number) => number, py: (y: number) => number, scale: number): void {
		const selected = !drafting && index === this.state.plotCorner;
		const group = svg(root, 'g', { class: `soil-site-corner${selected ? ' selected' : ''}${drafting && index === 0 && count >= 3 ? ' first' : ''}`, tabindex: 0, role: 'button', 'aria-label': localize('soil.plot.cornerMarker', "Plot corner {0} (drag to move, click to pick)", index + 1) });
		const handle = svg(group, 'rect', { x: px(corner.x) - 5, y: py(corner.y) - 5, width: 10, height: 10 });
		svg(group, 'text', { x: px(corner.x) + 8, y: py(corner.y) - 6, class: 'soil-site-label' }, String(index + 1));
		svg(group, 'title', {}, localize('soil.plot.cornerTitle', "Corner {0}: {1}", index + 1, formatProjectPoint(corner.x, corner.y)));
		let drag: { startX: number; startY: number; moved: boolean } | undefined;
		this.gridDisposables.add(addDisposableListener(group, EventType.POINTER_DOWN, (e: PointerEvent) => {
			e.preventDefault();
			e.stopPropagation();
			group.setPointerCapture(e.pointerId);
			drag = { startX: e.clientX, startY: e.clientY, moved: false };
		}));
		this.gridDisposables.add(addDisposableListener(group, EventType.POINTER_MOVE, (e: PointerEvent) => {
			if (!drag || drafting) {
				return;
			}
			const dx = e.clientX - drag.startX;
			const dy = e.clientY - drag.startY;
			drag.moved ||= Math.abs(dx) + Math.abs(dy) > 3;
			handle.setAttribute('x', String(px(corner.x) + dx - 5));
			handle.setAttribute('y', String(py(corner.y) + dy - 5));
		}));
		this.gridDisposables.add(addDisposableListener(group, EventType.CLICK, (e: MouseEvent) => e.stopPropagation()));
		this.gridDisposables.add(addDisposableListener(group, EventType.POINTER_UP, (e: PointerEvent) => {
			const d = drag;
			drag = undefined;
			if (!d) {
				return;
			}
			if (drafting) {
				if (index === 0) {
					this.closeDraft();
				}
				return;
			}
			if (!d.moved) {
				this.pickCorner(index);
				return;
			}
			const x = Math.round((corner.x + (e.clientX - d.startX) / scale) / 10) * 10;
			const y = Math.round((corner.y - (e.clientY - d.startY) / scale) / 10) * 10;
			const corners = plotProject(this.host.report, this.host.location).map((p, i) => i === index ? [x, y] : [p.x, p.y]);
			this.storeCorners(corners);
		}));
		this.gridDisposables.add(addDisposableListener(group, EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				this.pickCorner(index);
			}
		}));
	}

	/** The project coordinates as a plain grid: the outline, the site's project point and the boreholes (drag to move). */
	private renderGrid(): void {
		this.gridDisposables.clear();
		clearNode(this.mapArea);
		const { report, location } = this.host;
		const width = Math.max(320, this.mapArea.clientWidth || 640);
		const height = Math.max(260, this.mapArea.clientHeight || 420);
		const outline = [outlineProject(location)].filter(ring => ring.length > 2);
		const origin = { x: report.site?.x ?? 0, y: report.site?.y ?? 0 };
		const draft = this.state.plotDraft?.on === 'grid' ? this.state.plotDraft.corners.map(([x, y]) => ({ x, y })) : undefined;
		const plot = plotProject(report, location);
		const envelope = envelopeProject(location);
		const extent = gridExtent([...report.boreholes, ...outline.flat(), origin, ...plot, ...(draft ?? [])]);
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
		const pointsOf = (ring: readonly { readonly x: number; readonly y: number }[]) => ring.map(p => `${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join(' ');
		if (plot.length > 2 && !draft) {
			svg(root, 'polygon', { points: pointsOf(plot), class: 'soil-site-plot' });
			if (envelope.length > 2) {
				svg(root, 'polygon', { points: pointsOf(envelope), class: 'soil-site-envelope' });
			}
		}
		for (const polygon of outline) {
			if (polygon.length > 2) {
				svg(root, 'polygon', { points: pointsOf(polygon), class: 'soil-site-outline' });
			}
		}
		// While drawing, a click on the grid places the next corner (to 10 mm).
		root.classList.toggle('drawing', !!draft);
		this.gridDisposables.add(addDisposableListener(root, EventType.CLICK, (e: MouseEvent) => {
			if (!draft) {
				return;
			}
			const rect = root.getBoundingClientRect();
			const x = Math.round((cx + (e.clientX - rect.left - width / 2) / scale) / 10) * 10;
			const y = Math.round((cy - (e.clientY - rect.top - height / 2) / scale) / 10) * 10;
			this.addDraftCorner([x, y]);
		}));
		if (draft && draft.length >= 2) {
			svg(root, 'polyline', { points: pointsOf(draft), class: 'soil-site-draft' });
		}
		(draft ?? plot).forEach((corner, index) => this.gridCorner(root, corner, index, !!draft, (draft ?? plot).length, px, py, scale));
		// North and the grid bearing: the compass over the stage (renderCompass), as on the map.
		// Ids that would overlap are stepped down a line.
		const offsets = spreadLabels(report.boreholes.map(b => ({ x: px(b.x) + 9, y: py(b.y), width: b.id.length * 7 + 4 })));
		const originMark = svg(root, 'g', { class: 'soil-site-origin' });
		svg(originMark, 'path', { d: `M${px(origin.x) - 7} ${py(origin.y)}h14M${px(origin.x)} ${py(origin.y) - 7}v14` });
		svg(originMark, 'title', {}, localize('soil.map.originTitle', "The point of the project coordinates at the site's position"));
		report.boreholes.forEach((borehole, index) => {
			const group = svg(root, 'g', { class: index === this.host.selected ? 'soil-site-borehole selected' : 'soil-site-borehole', tabindex: 0, role: 'button', 'aria-label': localize('soil.map.boreholeMarker', "{0} (drag to move)", borehole.id) });
			const circle = svg(group, 'circle', { cx: px(borehole.x), cy: py(borehole.y), r: 6 });
			const label = svg(group, 'text', { x: px(borehole.x) + 9, y: py(borehole.y) + 4 + offsets[index], class: 'soil-site-label' }, borehole.id);
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
				label.setAttribute('y', String(py(borehole.y) + dy + 4 + offsets[index]));
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
