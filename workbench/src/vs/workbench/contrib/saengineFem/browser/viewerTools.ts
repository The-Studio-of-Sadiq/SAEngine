/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/viewerTools.css';
import type {
	BuildingLayer,
	BuildingViewer,
	FemViewer,
	MeasureEntry,
	SectionAxis,
	SectionBoxBounds,
	SectionPlaneSpec,
	SectionState,
	SnapKind,
	ViewerMeasureMode,
	VisibilityState,
	VisibilitySummary,
} from '@saengine/fem-viewer';
import { $, addDisposableListener, append, clearNode, EventType, getWindow, isEditableElement } from '../../../../base/browser/dom.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { Action, IAction, Separator, SubmenuAction } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';

export interface IViewerToolsTarget {
	hasModel(): boolean;
	getSelectionIds(): readonly string[];
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
	setMeasureMode(mode: ViewerMeasureMode): void;
	finishMeasureChain(): void;
	removeMeasurement(id: string): void;
	clearMeasurements(): void;
	getMeasurements(): readonly MeasureEntry[];
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

export function buildingViewerTarget(getViewer: () => BuildingViewer | undefined, hasModel: () => boolean): IViewerToolsTarget {
	return {
		hasModel,
		getSelectionIds: () => getViewer()?.getSelection() ?? [],
		toggleSectionBox: enabled => getViewer()?.toggleSectionBox(enabled) ?? false,
		setSectionBox: boundsMm => getViewer()?.setSectionBox(boundsMm),
		sectionBoxFromSelection: () => getViewer()?.sectionBoxFromSelection() ?? Promise.resolve(false),
		resetSectionBox: () => getViewer()?.resetSectionBox(),
		addSectionPlane: axis => getViewer()?.addSectionPlane(axis),
		setSectionPlanePickMode: active => getViewer()?.setSectionPlanePickMode(active),
		flipSectionPlane: id => getViewer()?.flipSectionPlane(id),
		removeSectionPlane: id => getViewer()?.removeSectionPlane(id),
		clearSectionPlanes: () => getViewer()?.clearSectionPlanes(),
		getSectionState: () => getViewer()?.getSectionState() ?? { boxEnabled: false, planes: [] },
		setSectionState: state => getViewer()?.setSectionState(state),
		setMeasureMode: mode => getViewer()?.setMeasureMode(mode),
		finishMeasureChain: () => getViewer()?.finishMeasureChain(),
		removeMeasurement: id => getViewer()?.removeMeasurement(id),
		clearMeasurements: () => getViewer()?.clearMeasurements(),
		getMeasurements: () => getViewer()?.getMeasurements() ?? [],
		hideSelectedTemp: () => getViewer()?.hideSelectedTemp() ?? Promise.resolve(),
		isolateSelectedTemp: () => getViewer()?.isolateSelectedTemp() ?? Promise.resolve(),
		hideSelectedCategoryTemp: () => getViewer()?.hideSelectedCategoryTemp() ?? Promise.resolve(),
		isolateSelectedCategoryTemp: () => getViewer()?.isolateSelectedCategoryTemp() ?? Promise.resolve(),
		resetTemporaryVisibility: () => getViewer()?.resetTemporaryVisibility() ?? Promise.resolve(),
		hideSelectedPermanent: () => getViewer()?.hideSelectedPermanent() ?? Promise.resolve(),
		unhideSelectedPermanent: () => getViewer()?.unhideSelectedPermanent() ?? Promise.resolve(),
		unhideAllPermanent: () => getViewer()?.unhideAllPermanent() ?? Promise.resolve(),
		applyTemporaryHideToPermanent: () => getViewer()?.applyTemporaryHideToPermanent() ?? Promise.resolve(),
		setRevealHidden: reveal => getViewer()?.setRevealHidden(reveal) ?? Promise.resolve(),
		getVisibilityState: () => getViewer()?.getVisibilityState() ?? emptyVis(),
		setVisibilityState: state => getViewer()?.setVisibilityState(state as Partial<VisibilityState<BuildingLayer>>) ?? Promise.resolve(),
	};
}

export function femViewerTarget(getViewer: () => FemViewer | undefined, hasModel: () => boolean): IViewerToolsTarget {
	return {
		hasModel,
		getSelectionIds: () => getViewer()?.getSelection() ?? [],
		toggleSectionBox: enabled => getViewer()?.toggleSectionBox(enabled) ?? false,
		setSectionBox: boundsMm => getViewer()?.setSectionBox(boundsMm),
		sectionBoxFromSelection: () => getViewer()?.sectionBoxFromSelection() ?? Promise.resolve(false),
		resetSectionBox: () => getViewer()?.resetSectionBox(),
		addSectionPlane: axis => getViewer()?.addSectionPlane(axis),
		setSectionPlanePickMode: active => getViewer()?.setSectionPlanePickMode(active),
		flipSectionPlane: id => getViewer()?.flipSectionPlane(id),
		removeSectionPlane: id => getViewer()?.removeSectionPlane(id),
		clearSectionPlanes: () => getViewer()?.clearSectionPlanes(),
		getSectionState: () => getViewer()?.getSectionState() ?? { boxEnabled: false, planes: [] },
		setSectionState: state => getViewer()?.setSectionState(state),
		setMeasureMode: mode => getViewer()?.setMeasureMode(mode),
		finishMeasureChain: () => getViewer()?.finishMeasureChain(),
		removeMeasurement: id => getViewer()?.removeMeasurement(id),
		clearMeasurements: () => getViewer()?.clearMeasurements(),
		getMeasurements: () => getViewer()?.getMeasurements() ?? [],
		hideSelectedTemp: () => getViewer()?.hideSelectedTemp() ?? Promise.resolve(),
		isolateSelectedTemp: () => getViewer()?.isolateSelectedTemp() ?? Promise.resolve(),
		hideSelectedCategoryTemp: () => getViewer()?.hideSelectedCategoryTemp() ?? Promise.resolve(),
		isolateSelectedCategoryTemp: () => getViewer()?.isolateSelectedCategoryTemp() ?? Promise.resolve(),
		resetTemporaryVisibility: () => getViewer()?.resetTemporaryVisibility() ?? Promise.resolve(),
		hideSelectedPermanent: () => getViewer()?.hideSelectedPermanent() ?? Promise.resolve(),
		unhideSelectedPermanent: () => getViewer()?.unhideSelectedPermanent() ?? Promise.resolve(),
		unhideAllPermanent: () => getViewer()?.unhideAllPermanent() ?? Promise.resolve(),
		applyTemporaryHideToPermanent: () => getViewer()?.applyTemporaryHideToPermanent() ?? Promise.resolve(),
		setRevealHidden: reveal => getViewer()?.setRevealHidden(reveal) ?? Promise.resolve(),
		getVisibilityState: () => getViewer()?.getVisibilityState() ?? emptyVis(),
		setVisibilityState: state => getViewer()?.setVisibilityState(state) ?? Promise.resolve(),
	};
}

function emptyVis(): VisibilityState {
	return {
		permanentHiddenElements: [],
		tempHiddenElements: [],
		tempIsolatedElements: undefined,
		tempHiddenCategories: [],
		tempIsolatedCategories: undefined,
		revealHidden: false,
	};
}

export interface IViewerToolsOptions {
	readonly viewId: string;
	readonly target: IViewerToolsTarget;
	readonly overlayParent: HTMLElement;
	readonly keyTarget: HTMLElement;
	readonly extraMeasureActions?: readonly IAction[];
	readonly onDidChangeActions?: () => void;
}

interface IPersistedViewState {
	readonly section?: SectionState;
	readonly permanentHiddenElements?: readonly string[];
}

const STORAGE_PREFIX = 'saengine.3dViewState.';
const CHORD_TIMEOUT_MS = 900;

const BOUND_FIELDS: readonly { readonly key: keyof SectionBoxBounds; readonly label: string }[] = [
	{ key: 'minX', label: 'X min' },
	{ key: 'maxX', label: 'X max' },
	{ key: 'minY', label: 'Y min' },
	{ key: 'maxY', label: 'Y max' },
	{ key: 'minZ', label: 'Z min' },
	{ key: 'maxZ', label: 'Z max' },
];

/**
 * Revit-parity 3D view controls shared by the BIM and FEM viewports:
 * - Section box (6 draggable faces, numeric mm bounds, from selection, reset) & single planes
 * - 3D Measure (point-to-point, chain, point-to-face perpendicular, edge-to-edge angle) with snap & copyable panel
 * - Temporary (HH, HI, HC, IC, HR) and permanent Hide/Isolate with Reveal Hidden mode
 */
export class ViewerTools extends Disposable {

	private resourceKey: string | undefined;
	private sectionState: SectionState = { boxEnabled: false, planes: [] };
	private sectionPickMode = false;
	private sectionPanelOpen = false;

	private measureMode: ViewerMeasureMode = 'off';
	private measureSnap: SnapKind | undefined;
	private measurePendingPoints = 0;
	private measureLiveLabel: string | undefined;
	private measureEntries: readonly MeasureEntry[] = [];
	private measurePanelOpen = false;

	private visibilitySummary: VisibilitySummary = {
		hasTemporary: false,
		permanentHiddenCount: 0,
		tempHiddenCount: 0,
		isIsolated: false,
		revealHidden: false,
	};

	private chordFirst: 'h' | 'i' | undefined;
	private chordTimer: number | undefined;

	private readonly banner: HTMLElement;
	private readonly bannerStore = this._register(new DisposableStore());
	private readonly sectionPanel: HTMLElement;
	private readonly sectionBody: HTMLElement;
	private readonly sectionStore = this._register(new DisposableStore());
	private readonly boundInputs = new Map<keyof SectionBoxBounds, HTMLInputElement>();
	private readonly measurePanel: HTMLElement;
	private readonly measureBody: HTMLElement;
	private readonly measureStore = this._register(new DisposableStore());

	// Primary toolbar icon actions
	private readonly sectionBoxAction: Action;
	private readonly measureAction: Action;
	private readonly revealHiddenAction: Action;

	// Submenu actions
	private readonly sectionToggleAction: Action;
	private readonly sectionFromSelectionAction: Action;
	private readonly sectionEditBoundsAction: Action;
	private readonly sectionResetAction: Action;
	private readonly sectionPlaneXAction: Action;
	private readonly sectionPlaneYAction: Action;
	private readonly sectionPlaneZAction: Action;
	private readonly sectionPlaneFaceAction: Action;
	private readonly sectionClearPlanesAction: Action;

	private readonly measureDistanceAction: Action;
	private readonly measureChainAction: Action;
	private readonly measurePointToFaceAction: Action;
	private readonly measureEdgeAngleAction: Action;
	private readonly measureClearAction: Action;

	private readonly hideElementTempAction: Action;
	private readonly isolateElementTempAction: Action;
	private readonly hideCategoryTempAction: Action;
	private readonly isolateCategoryTempAction: Action;
	private readonly resetTempAction: Action;
	private readonly hidePermanentAction: Action;
	private readonly unhideSelectedAction: Action;
	private readonly unhideAllAction: Action;
	private readonly applyTempPermanentAction: Action;
	private readonly revealHiddenMenuAction: Action;

	private readonly sectionSubmenu: SubmenuAction;
	private readonly measureSubmenu: SubmenuAction;
	private readonly visibilitySubmenu: SubmenuAction;

	constructor(
		private readonly options: IViewerToolsOptions,
		@IStorageService private readonly storageService: IStorageService,
		@IHoverService private readonly hoverService: IHoverService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super();

		this.sectionBoxAction = this._register(new Action(
			'saengine.3d.sectionBox',
			localize('viewerTools.sectionBox', "Section Box"),
			ThemeIcon.asClassName(Codicon.symbolMisc),
			true,
			async () => this.toggleSectionBox(),
		));
		this.measureAction = this._register(new Action(
			'saengine.3d.measure',
			localize('viewerTools.measure', "Measure"),
			ThemeIcon.asClassName(Codicon.symbolRuler),
			true,
			async () => this.toggleMeasurePanel(),
		));
		this.revealHiddenAction = this._register(new Action(
			'saengine.3d.revealHidden',
			localize('viewerTools.revealHidden', "Reveal Hidden Elements"),
			ThemeIcon.asClassName(Codicon.lightbulb),
			true,
			async () => this.toggleRevealHidden(),
		));

		this.sectionToggleAction = this._register(new Action('saengine.3d.section.toggle', localize('viewerTools.section.toggle', "Section Box"), undefined, true, async () => this.toggleSectionBox()));
		this.sectionFromSelectionAction = this._register(new Action('saengine.3d.section.fromSelection', localize('viewerTools.section.fromSelection', "Section Box from Selection"), undefined, true, () => this.sectionBoxFromSelection()));
		this.sectionEditBoundsAction = this._register(new Action('saengine.3d.section.bounds', localize('viewerTools.section.bounds', "Section Box Bounds (mm)..."), undefined, true, async () => {
			this.sectionPanelOpen = !this.sectionPanelOpen;
			this.renderSectionPanel();
		}));
		this.sectionResetAction = this._register(new Action('saengine.3d.section.reset', localize('viewerTools.section.reset', "Reset Section Box"), undefined, true, async () => {
			this.options.target.resetSectionBox();
			this.sectionPanelOpen = true;
			this.syncState();
		}));
		this.sectionPlaneXAction = this._register(new Action('saengine.3d.section.planeX', localize('viewerTools.section.planeX', "Add Section Plane: X"), undefined, true, async () => this.addAxisPlane('x')));
		this.sectionPlaneYAction = this._register(new Action('saengine.3d.section.planeY', localize('viewerTools.section.planeY', "Add Section Plane: Y"), undefined, true, async () => this.addAxisPlane('y')));
		this.sectionPlaneZAction = this._register(new Action('saengine.3d.section.planeZ', localize('viewerTools.section.planeZ', "Add Section Plane: Z"), undefined, true, async () => this.addAxisPlane('z')));
		this.sectionPlaneFaceAction = this._register(new Action('saengine.3d.section.planeFace', localize('viewerTools.section.planeFace', "Section Plane from Face..."), undefined, true, async () => this.togglePlanePickMode()));
		this.sectionClearPlanesAction = this._register(new Action('saengine.3d.section.clearPlanes', localize('viewerTools.section.clearPlanes', "Clear Section Planes"), undefined, true, async () => {
			this.options.target.clearSectionPlanes();
			this.syncState();
		}));

		this.measureDistanceAction = this._register(new Action('saengine.3d.measure.distance', localize('viewerTools.measure.distance', "Point-to-Point Distance"), undefined, true, async () => this.selectMeasureMode('distance')));
		this.measureChainAction = this._register(new Action('saengine.3d.measure.chain', localize('viewerTools.measure.chain', "Chain Distance"), undefined, true, async () => this.selectMeasureMode('chain')));
		this.measurePointToFaceAction = this._register(new Action('saengine.3d.measure.pointToFace', localize('viewerTools.measure.pointToFace', "Point to Face (Perpendicular)"), undefined, true, async () => this.selectMeasureMode('pointToFace')));
		this.measureEdgeAngleAction = this._register(new Action('saengine.3d.measure.edgeAngle', localize('viewerTools.measure.edgeAngle', "Angle Between Two Edges"), undefined, true, async () => this.selectMeasureMode('edgeAngle')));
		this.measureClearAction = this._register(new Action('saengine.3d.measure.clear', localize('viewerTools.measure.clear', "Clear Measurements"), undefined, true, async () => {
			this.options.target.clearMeasurements();
			this.syncState();
		}));

		this.hideElementTempAction = this._register(new Action('saengine.3d.vis.hh', localize('viewerTools.vis.hh', "Hide Element (Temporary) [HH]"), undefined, true, () => this.hideTemp()));
		this.isolateElementTempAction = this._register(new Action('saengine.3d.vis.hi', localize('viewerTools.vis.hi', "Isolate Element (Temporary) [HI]"), undefined, true, () => this.isolateTemp()));
		this.hideCategoryTempAction = this._register(new Action('saengine.3d.vis.hc', localize('viewerTools.vis.hc', "Hide Category (Temporary) [HC]"), undefined, true, () => this.hideCategoryTemp()));
		this.isolateCategoryTempAction = this._register(new Action('saengine.3d.vis.ic', localize('viewerTools.vis.ic', "Isolate Category (Temporary) [IC]"), undefined, true, () => this.isolateCategoryTemp()));
		this.resetTempAction = this._register(new Action('saengine.3d.vis.hr', localize('viewerTools.vis.hr', "Reset Temporary Hide/Isolate [HR]"), undefined, true, () => this.resetTemp()));
		this.hidePermanentAction = this._register(new Action('saengine.3d.vis.hidePerm', localize('viewerTools.vis.hidePerm', "Hide Element Permanently"), undefined, true, () => this.hidePermanent()));
		this.unhideSelectedAction = this._register(new Action('saengine.3d.vis.unhideSel', localize('viewerTools.vis.unhideSel', "Unhide Selected Element"), undefined, true, () => this.unhideSelected()));
		this.unhideAllAction = this._register(new Action('saengine.3d.vis.unhideAll', localize('viewerTools.vis.unhideAll', "Unhide All Permanently Hidden"), undefined, true, () => this.unhideAll()));
		this.applyTempPermanentAction = this._register(new Action('saengine.3d.vis.applyPerm', localize('viewerTools.vis.applyPerm', "Apply Temporary Hide/Isolate Permanently"), undefined, true, () => this.applyTempPermanent()));
		this.revealHiddenMenuAction = this._register(new Action('saengine.3d.vis.reveal', localize('viewerTools.vis.reveal', "Reveal Hidden Elements"), undefined, true, () => this.toggleRevealHidden()));

		this.sectionSubmenu = new SubmenuAction('saengine.3d.sectionMenu', localize('viewerTools.sectionMenu', "Section"), [
			this.sectionToggleAction,
			this.sectionFromSelectionAction,
			this.sectionEditBoundsAction,
			this.sectionResetAction,
			new Separator(),
			this.sectionPlaneXAction,
			this.sectionPlaneYAction,
			this.sectionPlaneZAction,
			this.sectionPlaneFaceAction,
			this.sectionClearPlanesAction,
		]);

		this.measureSubmenu = new SubmenuAction('saengine.3d.measureMenu', localize('viewerTools.measureMenu', "Measure"), [
			this.measureDistanceAction,
			this.measureChainAction,
			this.measurePointToFaceAction,
			this.measureEdgeAngleAction,
			...(options.extraMeasureActions ?? []),
			new Separator(),
			this.measureClearAction,
		]);

		this.visibilitySubmenu = new SubmenuAction('saengine.3d.visibilityMenu', localize('viewerTools.visibilityMenu', "Hide / Isolate"), [
			this.hideElementTempAction,
			this.isolateElementTempAction,
			this.hideCategoryTempAction,
			this.isolateCategoryTempAction,
			this.resetTempAction,
			new Separator(),
			this.hidePermanentAction,
			this.unhideSelectedAction,
			this.unhideAllAction,
			this.applyTempPermanentAction,
			this.revealHiddenMenuAction,
		]);

		this.banner = append(options.overlayParent, $('.sa-3d-vis-banner.hidden'));
		this.sectionPanel = append(options.overlayParent, $('.sa-3d-panel.sa-3d-section-panel.hidden'));
		this.sectionBody = append(this.sectionPanel, $('.sa-3d-panel-body'));
		this.measurePanel = append(options.overlayParent, $('.sa-3d-panel.sa-3d-measure-panel.hidden'));
		this.measureBody = append(this.measurePanel, $('.sa-3d-panel-body'));

		this._register(addDisposableListener(options.keyTarget, EventType.KEY_DOWN, e => this.handleKeyDown(e)));
		this._register({ dispose: () => this.clearChord() });
		this.updateActionStates();
	}

	primaryActions(): readonly IAction[] {
		return [this.sectionBoxAction, this.measureAction, this.revealHiddenAction];
	}

	secondaryActions(): readonly IAction[] {
		return [this.sectionSubmenu, this.measureSubmenu, this.visibilitySubmenu];
	}

	/** Restores saved section & permanent-hide state for `resourceKey` after the model loads. */
	async restoreForResource(resourceKey: string | undefined): Promise<void> {
		this.resourceKey = resourceKey;
		if (!resourceKey) {
			return;
		}
		const saved = this.readPersisted(resourceKey);
		if (saved?.section) {
			this.options.target.setSectionState(saved.section);
			this.sectionState = this.options.target.getSectionState();
		} else {
			this.options.target.setSectionState({ boxEnabled: false, planes: [] });
			this.sectionState = { boxEnabled: false, planes: [] };
		}
		await this.options.target.setVisibilityState({
			permanentHiddenElements: saved?.permanentHiddenElements ?? [],
		});
		this.syncState();
	}

	onSelectionChanged(): void {
		this.updateActionStates();
	}

	onSectionChanged(state: SectionState): void {
		this.sectionState = state;
		this.updateActionStates();
		this.updateSectionInputsOrRender();
		this.savePersisted();
	}

	onSectionPickModeChanged(picking: boolean): void {
		this.sectionPickMode = picking;
		this.updateActionStates();
		this.renderSectionPanel();
	}

	onMeasureChanged(entries: readonly MeasureEntry[], status: { readonly mode: ViewerMeasureMode; readonly snap?: SnapKind; readonly pendingPoints: number; readonly liveLabel?: string }): void {
		this.measureEntries = entries;
		this.measureMode = status.mode;
		this.measureSnap = status.snap;
		this.measurePendingPoints = status.pendingPoints;
		this.measureLiveLabel = status.liveLabel;
		if (status.mode !== 'off' || entries.length > 0) {
			this.measurePanelOpen = true;
		}
		this.updateActionStates();
		this.renderMeasurePanel();
	}

	onVisibilityChanged(_state: VisibilityState, summary: VisibilitySummary): void {
		this.visibilitySummary = summary;
		this.updateActionStates();
		this.renderBanner();
		this.savePersisted();
	}

	syncState(): void {
		this.sectionState = this.options.target.getSectionState();
		this.measureEntries = this.options.target.getMeasurements();
		const vis = this.options.target.getVisibilityState();
		this.visibilitySummary = {
			hasTemporary: vis.tempHiddenElements.length > 0 || vis.tempIsolatedElements !== undefined || vis.tempHiddenCategories.length > 0 || vis.tempIsolatedCategories !== undefined,
			permanentHiddenCount: vis.permanentHiddenElements.length,
			tempHiddenCount: vis.tempHiddenElements.length,
			isIsolated: vis.tempIsolatedElements !== undefined || vis.tempIsolatedCategories !== undefined,
			revealHidden: vis.revealHidden,
		};
		this.updateActionStates();
		this.renderBanner();
		this.renderSectionPanel();
		this.renderMeasurePanel();
	}

	private updateActionStates(): void {
		const hasModel = this.options.target.hasModel();
		const hasSelection = this.options.target.getSelectionIds().length > 0;
		const boxOn = this.sectionState.boxEnabled;
		const hasPlanes = this.sectionState.planes.length > 0;

		this.sectionBoxAction.enabled = hasModel;
		this.sectionBoxAction.checked = boxOn || hasPlanes;
		this.measureAction.enabled = hasModel;
		this.measureAction.checked = this.measureMode !== 'off' || this.measurePanelOpen;
		this.revealHiddenAction.enabled = hasModel;
		this.revealHiddenAction.checked = this.visibilitySummary.revealHidden;

		this.sectionToggleAction.enabled = hasModel;
		this.sectionToggleAction.checked = boxOn;
		this.sectionFromSelectionAction.enabled = hasModel && hasSelection;
		this.sectionEditBoundsAction.enabled = hasModel;
		this.sectionEditBoundsAction.checked = this.sectionPanelOpen;
		this.sectionResetAction.enabled = hasModel && (boxOn || !!this.sectionState.box);
		this.sectionPlaneXAction.enabled = hasModel;
		this.sectionPlaneYAction.enabled = hasModel;
		this.sectionPlaneZAction.enabled = hasModel;
		this.sectionPlaneFaceAction.enabled = hasModel;
		this.sectionPlaneFaceAction.checked = this.sectionPickMode;
		this.sectionClearPlanesAction.enabled = hasModel && hasPlanes;

		this.measureDistanceAction.enabled = hasModel;
		this.measureDistanceAction.checked = this.measureMode === 'distance';
		this.measureChainAction.enabled = hasModel;
		this.measureChainAction.checked = this.measureMode === 'chain';
		this.measurePointToFaceAction.enabled = hasModel;
		this.measurePointToFaceAction.checked = this.measureMode === 'pointToFace';
		this.measureEdgeAngleAction.enabled = hasModel;
		this.measureEdgeAngleAction.checked = this.measureMode === 'edgeAngle';
		this.measureClearAction.enabled = hasModel && (this.measureEntries.length > 0 || this.measurePendingPoints > 0);

		this.hideElementTempAction.enabled = hasModel && hasSelection;
		this.isolateElementTempAction.enabled = hasModel && hasSelection;
		this.hideCategoryTempAction.enabled = hasModel && hasSelection;
		this.isolateCategoryTempAction.enabled = hasModel && hasSelection;
		this.resetTempAction.enabled = hasModel && this.visibilitySummary.hasTemporary;
		this.hidePermanentAction.enabled = hasModel && hasSelection;
		this.unhideSelectedAction.enabled = hasModel && hasSelection && this.visibilitySummary.revealHidden;
		this.unhideAllAction.enabled = hasModel && this.visibilitySummary.permanentHiddenCount > 0;
		this.applyTempPermanentAction.enabled = hasModel && this.visibilitySummary.hasTemporary;
		this.revealHiddenMenuAction.enabled = hasModel;
		this.revealHiddenMenuAction.checked = this.visibilitySummary.revealHidden;

		this.options.onDidChangeActions?.();
	}

	private async toggleSectionBox(): Promise<void> {
		const enabled = this.options.target.toggleSectionBox();
		if (enabled) {
			this.sectionPanelOpen = true;
		} else if (!this.options.target.getSectionState().planes.length) {
			this.sectionPanelOpen = false;
		}
		this.sectionState = this.options.target.getSectionState();
		this.updateActionStates();
		this.renderSectionPanel();
		this.savePersisted();
	}

	private async sectionBoxFromSelection(): Promise<void> {
		const ok = await this.options.target.sectionBoxFromSelection();
		if (!ok) {
			this.notificationService.info(localize('viewerTools.selectFirst', "Select one or more elements in the 3D view first."));
			return;
		}
		this.sectionPanelOpen = true;
		this.sectionState = this.options.target.getSectionState();
		this.updateActionStates();
		this.renderSectionPanel();
		this.savePersisted();
	}

	private async addAxisPlane(axis: SectionAxis): Promise<void> {
		this.options.target.addSectionPlane(axis);
		this.sectionPanelOpen = true;
		this.sectionState = this.options.target.getSectionState();
		this.updateActionStates();
		this.renderSectionPanel();
		this.savePersisted();
	}

	private async togglePlanePickMode(): Promise<void> {
		const next = !this.sectionPickMode;
		this.sectionPanelOpen = true;
		this.options.target.setSectionPlanePickMode(next);
		this.renderSectionPanel();
	}

	private async toggleMeasurePanel(): Promise<void> {
		if (this.measureMode !== 'off' || this.measurePanelOpen) {
			this.measurePanelOpen = false;
			this.options.target.setMeasureMode('off');
			this.measureMode = 'off';
		} else {
			this.measurePanelOpen = true;
			this.options.target.setMeasureMode('distance');
			this.measureMode = 'distance';
		}
		this.updateActionStates();
		this.renderMeasurePanel();
	}

	private async selectMeasureMode(mode: ViewerMeasureMode): Promise<void> {
		const next = this.measureMode === mode ? 'off' : mode;
		this.measureMode = next;
		if (next !== 'off') {
			this.measurePanelOpen = true;
		}
		this.options.target.setMeasureMode(next);
		this.updateActionStates();
		this.renderMeasurePanel();
	}

	private async hideTemp(): Promise<void> {
		if (!this.options.target.getSelectionIds().length) {
			return;
		}
		await this.options.target.hideSelectedTemp();
		this.syncState();
	}

	private async isolateTemp(): Promise<void> {
		if (!this.options.target.getSelectionIds().length) {
			return;
		}
		await this.options.target.isolateSelectedTemp();
		this.syncState();
	}

	private async hideCategoryTemp(): Promise<void> {
		if (!this.options.target.getSelectionIds().length) {
			return;
		}
		await this.options.target.hideSelectedCategoryTemp();
		this.syncState();
	}

	private async isolateCategoryTemp(): Promise<void> {
		if (!this.options.target.getSelectionIds().length) {
			return;
		}
		await this.options.target.isolateSelectedCategoryTemp();
		this.syncState();
	}

	private async resetTemp(): Promise<void> {
		await this.options.target.resetTemporaryVisibility();
		this.syncState();
	}

	private async hidePermanent(): Promise<void> {
		if (!this.options.target.getSelectionIds().length) {
			return;
		}
		await this.options.target.hideSelectedPermanent();
		this.syncState();
		this.savePersisted();
	}

	private async unhideSelected(): Promise<void> {
		if (!this.options.target.getSelectionIds().length) {
			return;
		}
		await this.options.target.unhideSelectedPermanent();
		this.syncState();
		this.savePersisted();
	}

	private async unhideAll(): Promise<void> {
		await this.options.target.unhideAllPermanent();
		this.syncState();
		this.savePersisted();
	}

	private async applyTempPermanent(): Promise<void> {
		await this.options.target.applyTemporaryHideToPermanent();
		this.syncState();
		this.savePersisted();
	}

	private async toggleRevealHidden(): Promise<void> {
		await this.options.target.setRevealHidden(!this.visibilitySummary.revealHidden);
		this.syncState();
	}

	private handleKeyDown(e: KeyboardEvent): void {
		const target = e.target;
		if (e.ctrlKey || e.metaKey || e.altKey || (target instanceof getWindow(this.options.keyTarget).Element && isEditableElement(target))) {
			this.clearChord();
			return;
		}
		if (e.key === 'Escape') {
			this.clearChord();
			if (this.sectionPickMode) {
				this.options.target.setSectionPlanePickMode(false);
				e.preventDefault();
				e.stopPropagation();
				return;
			}
			if (this.measureMode !== 'off') {
				if (this.measurePendingPoints > 0) {
					this.options.target.setMeasureMode('off');
					this.options.target.setMeasureMode(this.measureMode);
				} else {
					this.options.target.setMeasureMode('off');
					this.measureMode = 'off';
				}
				this.syncState();
				e.preventDefault();
				e.stopPropagation();
			}
			return;
		}
		if (!this.options.target.hasModel()) {
			return;
		}
		const key = e.key.toLowerCase();
		if (this.chordFirst === 'h') {
			this.clearChord();
			if (key === 'h') {
				void this.hideTemp();
			} else if (key === 'i') {
				void this.isolateTemp();
			} else if (key === 'c') {
				void this.hideCategoryTemp();
			} else if (key === 'r') {
				void this.resetTemp();
			} else {
				return;
			}
			e.preventDefault();
			e.stopPropagation();
			return;
		}
		if (this.chordFirst === 'i') {
			this.clearChord();
			if (key === 'c') {
				void this.isolateCategoryTemp();
				e.preventDefault();
				e.stopPropagation();
			}
			return;
		}
		if (key === 'h' || key === 'i') {
			this.chordFirst = key;
			this.chordTimer = getWindow(this.options.keyTarget).setTimeout(() => this.clearChord(), CHORD_TIMEOUT_MS);
		}
	}

	private clearChord(): void {
		this.chordFirst = undefined;
		if (this.chordTimer !== undefined) {
			getWindow(this.options.keyTarget).clearTimeout(this.chordTimer);
			this.chordTimer = undefined;
		}
	}

	private renderBanner(): void {
		this.bannerStore.clear();
		clearNode(this.banner);
		const { hasTemporary, revealHidden, isIsolated, permanentHiddenCount } = this.visibilitySummary;
		const show = hasTemporary || revealHidden;
		this.banner.classList.toggle('hidden', !show);
		this.banner.classList.toggle('temp-active', hasTemporary && !revealHidden);
		this.banner.classList.toggle('reveal-active', revealHidden);
		if (!show) {
			return;
		}
		if (hasTemporary) {
			append(this.banner, $('span.sa-3d-banner-label', undefined,
				isIsolated ? localize('viewerTools.banner.isolated', "Temporary Isolate Active") : localize('viewerTools.banner.hidden', "Temporary Hide Active")));
			this.addSmallButton(this.banner, localize('viewerTools.banner.reset', "Reset (HR)"), localize('viewerTools.banner.resetTitle', "Restore temporarily hidden or isolated elements (shortcut: HR)"), () => void this.resetTemp(), this.bannerStore);
			this.addSmallButton(this.banner, localize('viewerTools.banner.apply', "Apply Permanently"), localize('viewerTools.banner.applyTitle', "Make temporary hide/isolate permanent in this view"), () => void this.applyTempPermanent(), this.bannerStore);
		}
		if (revealHidden) {
			append(this.banner, $('span.sa-3d-banner-label', undefined,
				permanentHiddenCount === 1
					? localize('viewerTools.banner.revealOne', "Reveal Hidden (1 element)")
					: localize('viewerTools.banner.revealCount', "Reveal Hidden ({0} elements)", permanentHiddenCount)));
			if (this.options.target.getSelectionIds().length > 0) {
				this.addSmallButton(this.banner, localize('viewerTools.banner.unhideSelected', "Unhide Selected"), localize('viewerTools.banner.unhideSelectedTitle', "Unhide the selected hidden elements"), () => void this.unhideSelected(), this.bannerStore);
			}
			if (permanentHiddenCount > 0) {
				this.addSmallButton(this.banner, localize('viewerTools.banner.unhideAll', "Unhide All"), localize('viewerTools.banner.unhideAllTitle', "Unhide all permanently hidden elements"), () => void this.unhideAll(), this.bannerStore);
			}
			this.addSmallButton(this.banner, localize('viewerTools.banner.closeReveal', "Close Reveal"), localize('viewerTools.banner.closeRevealTitle', "Exit Reveal Hidden mode"), () => void this.toggleRevealHidden(), this.bannerStore);
		}
	}

	private updateSectionInputsOrRender(): void {
		if (!this.sectionPanelOpen) {
			return;
		}
		const box = this.sectionState.box;
		if (!box || this.boundInputs.size !== 6) {
			this.renderSectionPanel();
			return;
		}
		const active = getWindow(this.sectionPanel).document.activeElement;
		for (const [key, input] of this.boundInputs) {
			if (input !== active) {
				input.value = String(Math.round(box[key]));
			}
		}
	}

	private renderSectionPanel(): void {
		this.sectionStore.clear();
		this.boundInputs.clear();
		clearNode(this.sectionBody);
		const show = this.sectionPanelOpen;
		this.sectionPanel.classList.toggle('hidden', !show);
		if (!show) {
			return;
		}

		const header = append(this.sectionBody, $('.sa-3d-panel-head'));
		append(header, $('span.sa-3d-panel-title', undefined, localize('viewerTools.section.title', "Section")));
		const boxToggle = this.addSmallButton(header, this.sectionState.boxEnabled ? localize('viewerTools.section.boxOn', "Box On") : localize('viewerTools.section.boxOff', "Box Off"), localize('viewerTools.section.boxToggleTitle', "Toggle the 3D section box"), () => void this.toggleSectionBox(), this.sectionStore);
		boxToggle.classList.toggle('active', this.sectionState.boxEnabled);
		this.addSmallButton(header, localize('viewerTools.section.fromSelShort', "From Sel"), localize('viewerTools.section.fromSelTitle', "Fit the section box around the selected elements"), () => void this.sectionBoxFromSelection(), this.sectionStore);
		this.addSmallButton(header, localize('viewerTools.section.resetShort', "Reset"), localize('viewerTools.section.resetTitle', "Reset section box to model extents"), () => {
			this.options.target.resetSectionBox();
			this.syncState();
			this.savePersisted();
		}, this.sectionStore);
		this.addIconButton(header, Codicon.close, localize('viewerTools.section.close', "Close Section Panel"), () => {
			this.sectionPanelOpen = false;
			this.renderSectionPanel();
		}, this.sectionStore);

		if (this.sectionState.box) {
			const box = this.sectionState.box;
			const grid = append(this.sectionBody, $('.sa-3d-bounds-grid'));
			for (const field of BOUND_FIELDS) {
				const cell = append(grid, $('label.sa-3d-bound-field'));
				append(cell, $('span.sa-3d-bound-label', undefined, field.label));
				const input = append(cell, $<HTMLInputElement>('input.sa-3d-bound-input', {
					type: 'number',
					step: '100',
					value: String(Math.round(box[field.key])),
					'aria-label': localize('viewerTools.section.boundAria', "{0} bound (mm)", field.label),
				}));
				this.boundInputs.set(field.key, input);
				const commit = () => {
					const val = Number(input.value);
					if (!Number.isFinite(val)) {
						input.value = String(Math.round((this.sectionState.box ?? box)[field.key]));
						return;
					}
					const current = this.options.target.getSectionState().box ?? box;
					const next: SectionBoxBounds = { ...current, [field.key]: val };
					this.options.target.setSectionBox(next);
					this.sectionState = this.options.target.getSectionState();
					this.updateSectionInputsOrRender();
					this.savePersisted();
				};
				this.sectionStore.add(addDisposableListener(input, EventType.CHANGE, commit));
				this.sectionStore.add(addDisposableListener(input, EventType.KEY_DOWN, e => {
					if (e.key === 'Enter') {
						e.preventDefault();
						commit();
					}
				}));
			}
		}

		const planeBar = append(this.sectionBody, $('.sa-3d-plane-bar'));
		append(planeBar, $('span.sa-3d-sublabel', undefined, localize('viewerTools.section.planesLabel', "Planes:")));
		this.addSmallButton(planeBar, '+X', localize('viewerTools.section.addXTitle', "Add an X section plane"), () => void this.addAxisPlane('x'), this.sectionStore);
		this.addSmallButton(planeBar, '+Y', localize('viewerTools.section.addYTitle', "Add a Y section plane"), () => void this.addAxisPlane('y'), this.sectionStore);
		this.addSmallButton(planeBar, '+Z', localize('viewerTools.section.addZTitle', "Add a Z section plane"), () => void this.addAxisPlane('z'), this.sectionStore);
		const faceBtn = this.addSmallButton(planeBar, localize('viewerTools.section.pickFace', "+Face"), localize('viewerTools.section.pickFaceTitle', "Click any face in the 3D view to place a section plane"), () => void this.togglePlanePickMode(), this.sectionStore);
		faceBtn.classList.toggle('active', this.sectionPickMode);
		if (this.sectionState.planes.length > 0) {
			this.addSmallButton(planeBar, localize('viewerTools.section.clearPlanesShort', "Clear"), localize('viewerTools.section.clearPlanesTitle', "Remove all single section planes"), () => {
				this.options.target.clearSectionPlanes();
				this.syncState();
				this.savePersisted();
			}, this.sectionStore);
		}

		if (this.sectionPickMode) {
			append(this.sectionBody, $('.sa-3d-hint', undefined, localize('viewerTools.section.pickHint', "Click a surface in 3D to cut along that face (Esc cancels).")));
		}

		if (this.sectionState.planes.length > 0) {
			const list = append(this.sectionBody, $('.sa-3d-list'));
			this.sectionState.planes.forEach((plane, idx) => {
				const row = append(list, $('.sa-3d-list-row'));
				const labelText = plane.axis === 'x' ? localize('viewerTools.plane.x', "X @ {0} mm", Math.round(plane.point[0]))
					: plane.axis === 'y' ? localize('viewerTools.plane.y', "Y @ {0} mm", Math.round(plane.point[1]))
						: plane.axis === 'z' ? localize('viewerTools.plane.z', "Z @ {0} mm", Math.round(plane.point[2]))
							: localize('viewerTools.plane.face', "Face {0}", idx + 1);
				append(row, $('span.sa-3d-list-label', undefined, `${labelText}${plane.flipped ? ' ⇄' : ''}`));
				this.addIconButton(row, Codicon.arrowSwap, localize('viewerTools.section.flipTitle', "Flip clipping side"), () => {
					this.options.target.flipSectionPlane(plane.id);
					this.syncState();
					this.savePersisted();
				}, this.sectionStore);
				this.addIconButton(row, Codicon.close, localize('viewerTools.section.removePlaneTitle', "Remove section plane"), () => {
					this.options.target.removeSectionPlane(plane.id);
					this.syncState();
					this.savePersisted();
				}, this.sectionStore);
			});
		}
	}

	private renderMeasurePanel(): void {
		this.measureStore.clear();
		clearNode(this.measureBody);
		const show = this.measurePanelOpen || this.measureMode !== 'off' || this.measureEntries.length > 0;
		this.measurePanel.classList.toggle('hidden', !show);
		if (!show) {
			return;
		}

		const header = append(this.measureBody, $('.sa-3d-panel-head'));
		append(header, $('span.sa-3d-panel-title', undefined, localize('viewerTools.measure.title', "Measure")));
		if (this.measureMode === 'chain' && this.measurePendingPoints >= 2) {
			this.addSmallButton(header, localize('viewerTools.measure.finishChain', "Finish"), localize('viewerTools.measure.finishChainTitle', "Finish the current distance chain (or right-click)"), () => {
				this.options.target.finishMeasureChain();
				this.syncState();
			}, this.measureStore);
		}
		this.addIconButton(header, Codicon.close, localize('viewerTools.measure.close', "Close Measure Panel"), () => {
			this.measurePanelOpen = false;
			this.options.target.setMeasureMode('off');
			this.measureMode = 'off';
			this.updateActionStates();
			this.renderMeasurePanel();
		}, this.measureStore);

		const modes = append(this.measureBody, $('.sa-3d-mode-row'));
		const modeDefs: readonly [ViewerMeasureMode, string, string][] = [
			['distance', localize('viewerTools.mode.dist', "Dist"), localize('viewerTools.mode.distTitle', "Point-to-point distance with vertex/midpoint/face snap")],
			['chain', localize('viewerTools.mode.chain', "Chain"), localize('viewerTools.mode.chainTitle', "Chain multiple segments (right-click or Finish to end)")],
			['pointToFace', localize('viewerTools.mode.ptFace', "Pt-Face"), localize('viewerTools.mode.ptFaceTitle', "Perpendicular distance from a picked point to a picked face")],
			['edgeAngle', localize('viewerTools.mode.angle', "Angle"), localize('viewerTools.mode.angleTitle', "Angle between two picked edges")],
		];
		for (const [mode, label, title] of modeDefs) {
			const btn = this.addSmallButton(modes, label, title, () => void this.selectMeasureMode(mode), this.measureStore);
			btn.classList.toggle('active', this.measureMode === mode);
		}

		if (this.measureMode !== 'off') {
			const snapText = this.measureSnap === 'vertex' ? localize('viewerTools.snap.vertex', "Vertex")
				: this.measureSnap === 'midpoint' ? localize('viewerTools.snap.midpoint', "Midpoint")
					: this.measureSnap === 'edge' ? localize('viewerTools.snap.edge', "Edge")
						: this.measureSnap === 'face' ? localize('viewerTools.snap.face', "Face")
							: undefined;
			const promptText = this.measureMode === 'distance'
				? (this.measurePendingPoints ? localize('viewerTools.prompt.dist2', "Click second point") : localize('viewerTools.prompt.dist1', "Click first point"))
				: this.measureMode === 'chain'
					? (this.measurePendingPoints ? localize('viewerTools.prompt.chainNext', "Click next point (right-click to finish)") : localize('viewerTools.prompt.chain1', "Click chain start point"))
					: this.measureMode === 'pointToFace'
						? (this.measurePendingPoints ? localize('viewerTools.prompt.ptFace2', "Click target face") : localize('viewerTools.prompt.ptFace1', "Click point"))
						: this.measureMode === 'edgeAngle'
							? (this.measurePendingPoints ? localize('viewerTools.prompt.angle2', "Click second edge") : localize('viewerTools.prompt.angle1', "Click first edge"))
							: localize('viewerTools.prompt.generic', "Click in the 3D view");
			const statusParts = [promptText];
			if (snapText) {
				statusParts.push(localize('viewerTools.snapPrefix', "Snap: {0}", snapText));
			}
			if (this.measureLiveLabel) {
				statusParts.push(this.measureLiveLabel);
			}
			append(this.measureBody, $('.sa-3d-hint', undefined, statusParts.join(' · ')));
		}

		if (this.measureEntries.length > 0) {
			const list = append(this.measureBody, $('.sa-3d-list.sa-3d-measure-list'));
			for (const entry of this.measureEntries) {
				const row = append(list, $('.sa-3d-list-row'));
				const info = append(row, $('.sa-3d-measure-info'));
				append(info, $('span.sa-3d-measure-val', undefined, entry.label));
				if (entry.summary !== entry.label) {
					append(info, $('span.sa-3d-measure-detail', undefined, entry.summary));
				}
				this.addIconButton(row, Codicon.copy, localize('viewerTools.measure.copyOne', "Copy measurement"), () => {
					void this.clipboardService.writeText(entry.summary);
				}, this.measureStore);
				this.addIconButton(row, Codicon.close, localize('viewerTools.measure.removeOne', "Remove measurement"), () => {
					this.options.target.removeMeasurement(entry.id);
					this.syncState();
				}, this.measureStore);
			}
			const footer = append(this.measureBody, $('.sa-3d-panel-foot'));
			this.addSmallButton(footer, localize('viewerTools.measure.copyAll', "Copy All"), localize('viewerTools.measure.copyAllTitle', "Copy all measurements to clipboard"), () => {
				const text = this.measureEntries.map((e, i) => `${i + 1}. ${e.summary}`).join('\n');
				void this.clipboardService.writeText(text);
			}, this.measureStore);
			this.addSmallButton(footer, localize('viewerTools.measure.clearAll', "Clear"), localize('viewerTools.measure.clearAllTitle', "Clear all measurements"), () => {
				this.options.target.clearMeasurements();
				this.syncState();
			}, this.measureStore);
		}
	}

	private addSmallButton(parent: HTMLElement, label: string, title: string, onClick: () => void, store: DisposableStore): HTMLButtonElement {
		const btn = append(parent, $<HTMLButtonElement>('button.sa-3d-btn', { type: 'button', 'aria-label': title }, label));
		store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), btn, title));
		store.add(addDisposableListener(btn, EventType.CLICK, e => {
			e.stopPropagation();
			onClick();
		}));
		return btn;
	}

	private addIconButton(parent: HTMLElement, icon: ThemeIcon, title: string, onClick: () => void, store: DisposableStore): HTMLButtonElement {
		const btn = append(parent, $<HTMLButtonElement>('button.sa-3d-icon-btn', { type: 'button', 'aria-label': title }));
		append(btn, $(ThemeIcon.asCSSSelector(icon)));
		store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), btn, title));
		store.add(addDisposableListener(btn, EventType.CLICK, e => {
			e.stopPropagation();
			onClick();
		}));
		return btn;
	}

	private readPersisted(resourceKey: string): IPersistedViewState | undefined {
		const raw = this.storageService.get(`${STORAGE_PREFIX}${this.options.viewId}.${resourceKey}`, StorageScope.WORKSPACE);
		if (!raw) {
			return undefined;
		}
		try {
			const parsed = JSON.parse(raw) as IPersistedViewState;
			return parsed && typeof parsed === 'object' ? parsed : undefined;
		} catch {
			return undefined;
		}
	}

	private savePersisted(): void {
		if (!this.resourceKey) {
			return;
		}
		const payload: IPersistedViewState = {
			section: this.options.target.getSectionState(),
			permanentHiddenElements: this.options.target.getVisibilityState().permanentHiddenElements,
		};
		this.storageService.store(`${STORAGE_PREFIX}${this.options.viewId}.${this.resourceKey}`, JSON.stringify(payload), StorageScope.WORKSPACE, StorageTarget.USER);
	}
}
