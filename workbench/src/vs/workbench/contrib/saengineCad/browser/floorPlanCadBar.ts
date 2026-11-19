/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadColorValue, CadEditor as CadEditorApi, CadLayerInfo, CadPoint, DraftingSettings } from '@saengine/cad-editor';
import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { Action, IAction, Separator } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService, IQuickPickItem } from '../../../../platform/quickinput/common/quickInput.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { isLightCanvas } from './cadHost.js';

const CAD_DRAFTING_STORAGE_KEY = 'saengine.cad.draftingSettings';

const POLAR_ANGLES = [90, 45, 30, 22.5, 15, 10, 5] as const;

interface OsnapModeItem {
	readonly bit: number;
	readonly name: string;
	readonly code: string;
}

const OSNAP_MODES: readonly OsnapModeItem[] = [
	{ bit: 1, name: 'Endpoint', code: 'END' },
	{ bit: 2, name: 'Midpoint', code: 'MID' },
	{ bit: 4, name: 'Center', code: 'CEN' },
	{ bit: 1024, name: 'Geometric Center', code: 'GCE' },
	{ bit: 8, name: 'Node', code: 'NOD' },
	{ bit: 16, name: 'Quadrant', code: 'QUA' },
	{ bit: 32, name: 'Intersection', code: 'INT' },
	{ bit: 64, name: 'Insertion', code: 'INS' },
	{ bit: 128, name: 'Perpendicular', code: 'PER' },
	{ bit: 256, name: 'Tangent', code: 'TAN' },
	{ bit: 512, name: 'Nearest', code: 'NEA' },
];

export const STANDARD_COLORS: readonly { readonly name: string; readonly value: number; readonly hex: string }[] = [
	{ name: 'Red', value: 1, hex: '#ff0000' },
	{ name: 'Yellow', value: 2, hex: '#ffff00' },
	{ name: 'Green', value: 3, hex: '#00ff00' },
	{ name: 'Cyan', value: 4, hex: '#00ffff' },
	{ name: 'Blue', value: 5, hex: '#0000ff' },
	{ name: 'Magenta', value: 6, hex: '#ff00ff' },
	{ name: 'White', value: 7, hex: '#ffffff' },
	{ name: '8 (Dark Grey)', value: 8, hex: '#808080' },
	{ name: '9 (Light Grey)', value: 9, hex: '#c0c0c0' },
];

export const STANDARD_LINETYPES: readonly string[] = [
	'Continuous',
	'Dashed',
	'Dashed2',
	'Hidden',
	'Hidden2',
	'Center',
	'Center2',
	'Phantom',
	'Dot',
	'Divide',
];

export const STANDARD_LINEWEIGHTS: readonly number[] = [
	0.00, 0.05, 0.09, 0.13, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.20, 1.40, 2.00,
];

export function aciToCss(color: CadColorValue | 'varies', isLight: boolean): string {
	if (color === 'varies') {
		return 'linear-gradient(135deg, #ff0000, #00ff00, #0000ff)';
	}
	if (color === 'ByLayer' || color === 'ByBlock') {
		return 'transparent';
	}
	if (typeof color === 'number') {
		if (color === 7) {
			return isLight ? '#000000' : '#ffffff';
		}
		if (color === 2 && isLight) {
			return '#b8860b';
		}
		const std = STANDARD_COLORS.find(c => c.value === color);
		return std ? std.hex : '#888888';
	}
	if (typeof color === 'object' && color !== null) {
		return `rgb(${color.r}, ${color.g}, ${color.b})`;
	}
	return '#888888';
}

interface LayerPickItem extends IQuickPickItem {
	readonly layer: CadLayerInfo;
}

export class FloorPlanCadBar extends Disposable {
	private readonly element: HTMLElement;
	private readonly cursorLabel: HTMLElement;

	private readonly snapBtn: HTMLButtonElement;
	private readonly gridBtn: HTMLButtonElement;
	private readonly orthoBtn: HTMLButtonElement;
	private readonly polarBtn: HTMLButtonElement;
	private readonly polarDropBtn: HTMLButtonElement;
	private readonly osnapBtn: HTMLButtonElement;
	private readonly osnapDropBtn: HTMLButtonElement;
	private readonly otrackBtn: HTMLButtonElement;
	private readonly dynBtn: HTMLButtonElement;

	private readonly layerBtn: HTMLButtonElement;
	private readonly layerSwatch: HTMLElement;
	private readonly layerStateIcon: HTMLElement;
	private readonly layerLabel: HTMLElement;

	private readonly colorBtn: HTMLButtonElement;
	private readonly colorSwatch: HTMLElement;
	private readonly colorLabel: HTMLElement;

	private readonly ltBtn: HTMLButtonElement;
	private readonly ltLabel: HTMLElement;

	private readonly lwBtn: HTMLButtonElement;
	private readonly lwLabel: HTMLElement;

	private editor: CadEditorApi | undefined;
	private readonly editorDisposables = this._register(new DisposableStore());
	private isLight = false;

	constructor(
		container: HTMLElement,
		@IContextMenuService private readonly contextMenuService: IContextMenuService,
		@IQuickInputService private readonly quickInputService: IQuickInputService,
		@IStorageService private readonly storageService: IStorageService,
		@INotificationService private readonly notificationService: INotificationService,
		@IThemeService private readonly themeService: IThemeService,
	) {
		super();
		this.isLight = isLightCanvas(this.themeService.getColorTheme());
		this._register(this.themeService.onDidColorThemeChange(theme => {
			this.isLight = isLightCanvas(theme);
			this.updateProperties();
		}));

		this.element = append(container, $('.floor-plan-status-bar'));

		// 1. Left: Cursor coordinates in mm
		const left = append(this.element, $('.cad-bar-left'));
		this.cursorLabel = append(left, $('span.cad-bar-cursor', undefined, '-- , -- mm'));

		// 2. Center: Drafting toggles
		const drafting = append(this.element, $('.cad-bar-drafting'));

		// SNAP (F9)
		this.snapBtn = append(drafting, $('button.cad-bar-btn', { title: localize('drafting.snapTooltip', "Snap Mode (F9)") }));
		this.snapBtn.textContent = 'SNAP';
		this._register(addDisposableListener(this.snapBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ snap: !curr.snap });
			}
		}));

		// GRID (F7)
		this.gridBtn = append(drafting, $('button.cad-bar-btn', { title: localize('drafting.gridTooltip', "Grid Display (F7)") }));
		this.gridBtn.textContent = 'GRID';
		this._register(addDisposableListener(this.gridBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ grid: !curr.grid });
			}
		}));

		// ORTHO (F8)
		this.orthoBtn = append(drafting, $('button.cad-bar-btn', { title: localize('drafting.orthoTooltip', "Ortho Mode (F8)") }));
		this.orthoBtn.textContent = 'ORTHO';
		this._register(addDisposableListener(this.orthoBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ ortho: !curr.ortho });
			}
		}));

		// POLAR (F10) + Dropdown
		const polarGroup = append(drafting, $('.cad-bar-group'));
		this.polarBtn = append(polarGroup, $('button.cad-bar-btn.grouped-left', { title: localize('drafting.polarTooltip', "Polar Tracking (F10)") }));
		this.polarBtn.textContent = 'POLAR';
		this._register(addDisposableListener(this.polarBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ polar: !curr.polar });
			}
		}));
		this.polarDropBtn = append(polarGroup, $('button.cad-bar-btn.grouped-right', { title: localize('drafting.polarAngles', "Polar Tracking Angles") }));
		append(this.polarDropBtn, $(ThemeIcon.asCSSSelector(Codicon.chevronDown)));
		this._register(addDisposableListener(this.polarDropBtn, EventType.CLICK, e => {
			e.stopPropagation();
			this.showPolarMenu();
		}));

		// OSNAP (F3) + Dropdown
		const osnapGroup = append(drafting, $('.cad-bar-group'));
		this.osnapBtn = append(osnapGroup, $('button.cad-bar-btn.grouped-left', { title: localize('drafting.osnapTooltip', "Object Snap (F3)") }));
		this.osnapBtn.textContent = 'OSNAP';
		this._register(addDisposableListener(this.osnapBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ osnap: !curr.osnap });
			}
		}));
		this.osnapDropBtn = append(osnapGroup, $('button.cad-bar-btn.grouped-right', { title: localize('drafting.osnapModes', "Object Snap Modes") }));
		append(this.osnapDropBtn, $(ThemeIcon.asCSSSelector(Codicon.chevronDown)));
		this._register(addDisposableListener(this.osnapDropBtn, EventType.CLICK, e => {
			e.stopPropagation();
			this.showOsnapMenu();
		}));

		// OTRACK (F11)
		this.otrackBtn = append(drafting, $('button.cad-bar-btn', { title: localize('drafting.otrackTooltip', "Object Snap Tracking (F11)") }));
		this.otrackBtn.textContent = 'OTRACK';
		this._register(addDisposableListener(this.otrackBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ otrack: !curr.otrack });
			}
		}));

		// DYN (F12)
		this.dynBtn = append(drafting, $('button.cad-bar-btn', { title: localize('drafting.dynTooltip', "Dynamic Input (F12)") }));
		this.dynBtn.textContent = 'DYN';
		this._register(addDisposableListener(this.dynBtn, EventType.CLICK, () => {
			if (this.editor) {
				const curr = this.editor.drafting.get();
				this.editor.drafting.set({ dyn: !curr.dyn });
			}
		}));

		// 3. Right: Properties strip
		const props = append(this.element, $('.cad-bar-props'));

		// Layer picker
		this.layerBtn = append(props, $('button.cad-bar-btn.cad-prop-btn.cad-layer-btn', { title: localize('cad.layerTooltip', "Current Layer / Move Selection to Layer") }));
		this.layerSwatch = append(this.layerBtn, $('span.cad-swatch'));
		this.layerStateIcon = append(this.layerBtn, $('span.cad-layer-state'));
		this.layerLabel = append(this.layerBtn, $('span.cad-layer-name', undefined, 'DRAFT'));
		append(this.layerBtn, $(ThemeIcon.asCSSSelector(Codicon.chevronDown)));
		this._register(addDisposableListener(this.layerBtn, EventType.CLICK, () => this.showLayerPicker()));

		// Color picker
		this.colorBtn = append(props, $('button.cad-bar-btn.cad-prop-btn.cad-color-btn', { title: localize('cad.colorTooltip', "Object Color") }));
		this.colorSwatch = append(this.colorBtn, $('span.cad-swatch'));
		this.colorLabel = append(this.colorBtn, $('span.cad-prop-label', undefined, 'ByLayer'));
		append(this.colorBtn, $(ThemeIcon.asCSSSelector(Codicon.chevronDown)));
		this._register(addDisposableListener(this.colorBtn, EventType.CLICK, () => this.showColorMenu()));

		// Linetype picker
		this.ltBtn = append(props, $('button.cad-bar-btn.cad-prop-btn.cad-lt-btn', { title: localize('cad.linetypeTooltip', "Object Linetype") }));
		this.ltLabel = append(this.ltBtn, $('span.cad-prop-label', undefined, 'ByLayer'));
		append(this.ltBtn, $(ThemeIcon.asCSSSelector(Codicon.chevronDown)));
		this._register(addDisposableListener(this.ltBtn, EventType.CLICK, () => this.showLinetypeMenu()));

		// Lineweight picker
		this.lwBtn = append(props, $('button.cad-bar-btn.cad-prop-btn.cad-lw-btn', { title: localize('cad.lineweightTooltip', "Object Lineweight") }));
		this.lwLabel = append(this.lwBtn, $('span.cad-prop-label', undefined, 'ByLayer'));
		append(this.lwBtn, $(ThemeIcon.asCSSSelector(Codicon.chevronDown)));
		this._register(addDisposableListener(this.lwBtn, EventType.CLICK, () => this.showLineweightMenu()));
	}

	public setEditor(editor: CadEditorApi | undefined): void {
		this.editor = editor;
		this.editorDisposables.clear();
		if (!editor) {
			this.cursorLabel.textContent = '-- , -- mm';
			return;
		}

		// Reapply saved drafting settings per workspace
		const saved = this.storageService.get(CAD_DRAFTING_STORAGE_KEY, StorageScope.WORKSPACE);
		if (saved) {
			try {
				const parsed = JSON.parse(saved) as Partial<DraftingSettings>;
				editor.drafting.set(parsed);
			} catch {
				// Ignore invalid storage data
			}
		}

		this.updateDrafting(editor.drafting.get());
		this.updateProperties();

		// Listen to drafting changes (including F-keys pressed inside canvas)
		this.editorDisposables.add(toDisposable(editor.drafting.onDidChangeDrafting(settings => {
			this.updateDrafting(settings);
			this.storageService.store(CAD_DRAFTING_STORAGE_KEY, JSON.stringify(settings), StorageScope.WORKSPACE, StorageTarget.MACHINE);
		})));

		// Listen to selection changes
		this.editorDisposables.add(toDisposable(editor.selection.onDidChangeSelection(() => {
			this.updateProperties();
		})));

		// Listen to layer changes
		this.editorDisposables.add(toDisposable(editor.layers.onDidChangeLayers(() => {
			this.updateProperties();
		})));

		// Listen to drawing edits (transactions/undo/redo)
		this.editorDisposables.add(toDisposable(editor.onDidChange(() => {
			this.updateProperties();
		})));
	}

	public setCursor(point: CadPoint | undefined): void {
		if (point) {
			this.cursorLabel.textContent = `${Math.round(point[0])}, ${Math.round(point[1])} mm`;
		} else {
			this.cursorLabel.textContent = '-- , -- mm';
		}
	}

	public updateDrafting(settings: DraftingSettings): void {
		this.snapBtn.classList.toggle('active', settings.snap);
		this.gridBtn.classList.toggle('active', settings.grid);
		this.orthoBtn.classList.toggle('active', settings.ortho);
		this.polarBtn.classList.toggle('active', settings.polar);
		this.polarDropBtn.classList.toggle('active', settings.polar);
		this.osnapBtn.classList.toggle('active', settings.osnap);
		this.osnapDropBtn.classList.toggle('active', settings.osnap);
		this.otrackBtn.classList.toggle('active', settings.otrack);
		this.dynBtn.classList.toggle('active', settings.dyn);

		this.polarDropBtn.title = localize('drafting.polarAngleValue', "Polar Increment: {0}°", settings.polarAngle);
	}

	public updateProperties(): void {
		if (!this.editor) {
			return;
		}
		try {
			const props = this.editor.properties.get();
			const currentLayerName = this.editor.layers.current();
			const layers = this.editor.layers.list();
			const currentLayer = layers.find(l => l.name === currentLayerName);

			// Layer button
			const dispLayer = props.layer === 'varies' ? '*VARIES*' : currentLayerName;
			this.layerLabel.textContent = dispLayer;
			if (currentLayer) {
				this.layerSwatch.style.background = aciToCss(currentLayer.color, this.isLight);
				this.layerStateIcon.className = 'cad-layer-state';
				if (currentLayer.locked) {
					this.layerStateIcon.classList.add(...ThemeIcon.asClassName(Codicon.lock).split(' '));
				} else if (!currentLayer.on) {
					this.layerStateIcon.classList.add(...ThemeIcon.asClassName(Codicon.eyeClosed).split(' '));
				}
			}

			// Color button
			if (props.color === 'varies') {
				this.colorLabel.textContent = '*VARIES*';
				this.colorSwatch.style.background = 'linear-gradient(135deg, #ff0000, #00ff00, #0000ff)';
			} else {
				this.colorSwatch.style.background = aciToCss(props.color, this.isLight);
				if (props.color === 'ByLayer' || props.color === 'ByBlock') {
					this.colorLabel.textContent = String(props.color);
				} else if (typeof props.color === 'number') {
					const std = STANDARD_COLORS.find(c => c.value === props.color);
					this.colorLabel.textContent = std ? std.name : String(props.color);
				} else {
					this.colorLabel.textContent = 'RGB';
				}
			}

			// Linetype button
			this.ltLabel.textContent = props.linetype === 'varies' ? '*VARIES*' : props.linetype;

			// Lineweight button
			if (props.lineweight === 'varies') {
				this.lwLabel.textContent = '*VARIES*';
			} else if (props.lineweight === 'ByLayer' || props.lineweight === 'ByBlock' || props.lineweight === 'default') {
				this.lwLabel.textContent = props.lineweight === 'default' ? 'Default' : props.lineweight;
			} else {
				this.lwLabel.textContent = `${Number(props.lineweight).toFixed(2)} mm`;
			}
		} catch {
			// Editor database might not be opened yet
		}
	}

	public layout(width: number): void {
		// At 1366 px window width and below:
		// 1. Collapse property pickers first (width < 1200)
		// 2. Shorten labels (width < 900)
		// 3. Hide cursor text on very narrow (width < 700)
		this.element.classList.toggle('collapse-props', width < 1200);
		this.element.classList.toggle('short-labels', width < 900);
		this.element.classList.toggle('hide-cursor', width < 700);

		const isShort = width < 900;
		this.snapBtn.textContent = isShort ? 'SNP' : 'SNAP';
		this.gridBtn.textContent = isShort ? 'GRD' : 'GRID';
		this.orthoBtn.textContent = isShort ? 'ORTH' : 'ORTHO';
		this.polarBtn.textContent = isShort ? 'POL' : 'POLAR';
		this.osnapBtn.textContent = isShort ? 'OSN' : 'OSNAP';
		this.otrackBtn.textContent = isShort ? 'OTR' : 'OTRACK';
		this.dynBtn.textContent = isShort ? 'DYN' : 'DYN';
	}

	private showPolarMenu(): void {
		if (!this.editor) {
			return;
		}
		const currentAngle = this.editor.drafting.get().polarAngle ?? 90;
		const actions: IAction[] = POLAR_ANGLES.map(angle => {
			const action = new Action(
				`saengine.cad.polar.${angle}`,
				`${angle}°`,
				undefined,
				true,
				async () => {
					this.editor?.drafting.set({ polarAngle: angle, polar: true });
				}
			);
			action.checked = Math.abs(angle - currentAngle) < 0.01;
			return action;
		});

		this.contextMenuService.showContextMenu({
			getAnchor: () => this.polarDropBtn,
			getActions: () => actions,
		});
	}

	private showOsnapMenu(): void {
		if (!this.editor) {
			return;
		}
		const settings = this.editor.drafting.get();
		const mask = settings.osnapModes ?? 0;

		const actions: IAction[] = OSNAP_MODES.map(mode => {
			const isEnabled = (mask & mode.bit) !== 0;
			const action = new Action(
				`saengine.cad.osnap.${mode.code}`,
				`${mode.name} (${mode.code})`,
				undefined,
				true,
				async () => {
					const newMask = isEnabled ? (mask & ~mode.bit) : (mask | mode.bit);
					this.editor?.drafting.set({ osnapModes: newMask, osnap: true });
				}
			);
			action.checked = isEnabled;
			return action;
		});

		actions.push(new Separator());
		actions.push(new Action('saengine.cad.osnap.all', localize('osnap.selectAll', "Select All"), undefined, true, async () => {
			const allMask = OSNAP_MODES.reduce((m, item) => m | item.bit, 0);
			this.editor?.drafting.set({ osnapModes: allMask, osnap: true });
		}));
		actions.push(new Action('saengine.cad.osnap.clear', localize('osnap.clearAll', "Clear All"), undefined, true, async () => {
			this.editor?.drafting.set({ osnapModes: 0 });
		}));

		this.contextMenuService.showContextMenu({
			getAnchor: () => this.osnapDropBtn,
			getActions: () => actions,
		});
	}

	private async showLayerPicker(): Promise<void> {
		if (!this.editor) {
			return;
		}
		const layers = this.editor.layers.list();
		const selectedIds = this.editor.selection.get();
		const isSelected = selectedIds.length > 0;

		const items: LayerPickItem[] = layers.map(layer => {
			let stateDesc = '';
			if (layer.current) {
				stateDesc += localize('layer.current', "[Current] ");
			}
			if (layer.generated) {
				stateDesc += localize('layer.generated', "[Structural, Read-only] ");
			}
			if (layer.locked) {
				stateDesc += '🔒 ';
			}
			if (layer.frozen) {
				stateDesc += '❄️ ';
			}
			if (!layer.on) {
				stateDesc += localize('layer.off', "(Off) ");
			}

			return {
				id: layer.name,
				label: layer.name,
				description: stateDesc.trim(),
				layer,
			};
		});

		const picked = await this.quickInputService.pick(items, {
			title: isSelected
				? localize('cad.moveSelectionLayer', "Move Selection to Layer")
				: localize('cad.setCurrentLayer', "Set Current Layer"),
			placeHolder: localize('cad.chooseLayer', "Select layer..."),
		});

		if (!picked || !this.editor) {
			return;
		}

		if (picked.layer.generated) {
			this.notificationService.warn(localize('layer.generatedReadOnly', "Generated structural layers cannot be modified or made current."));
			return;
		}

		if (isSelected) {
			this.editor.properties.set(selectedIds, { layer: picked.layer.name });
		} else {
			this.editor.layers.setCurrent(picked.layer.name);
		}
		this.updateProperties();
	}

	private showColorMenu(): void {
		if (!this.editor) {
			return;
		}
		const selectedIds = this.editor.selection.get();
		const actions: IAction[] = [
			new Action('saengine.cad.col.bylayer', 'ByLayer', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { color: 'ByLayer' });
				}
				this.updateProperties();
			}),
			new Action('saengine.cad.col.byblock', 'ByBlock', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { color: 'ByBlock' });
				}
				this.updateProperties();
			}),
			new Separator(),
			...STANDARD_COLORS.map(c => new Action(`saengine.cad.col.${c.value}`, `${c.value} - ${c.name}`, undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { color: c.value });
				}
				this.updateProperties();
			})),
		];

		this.contextMenuService.showContextMenu({
			getAnchor: () => this.colorBtn,
			getActions: () => actions,
		});
	}

	private showLinetypeMenu(): void {
		if (!this.editor) {
			return;
		}
		const selectedIds = this.editor.selection.get();
		const actions: IAction[] = [
			new Action('saengine.cad.lt.bylayer', 'ByLayer', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { linetype: 'ByLayer' });
				}
				this.updateProperties();
			}),
			new Action('saengine.cad.lt.byblock', 'ByBlock', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { linetype: 'ByBlock' });
				}
				this.updateProperties();
			}),
			new Separator(),
			...STANDARD_LINETYPES.map(lt => new Action(`saengine.cad.lt.${lt}`, lt, undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { linetype: lt });
				}
				this.updateProperties();
			})),
		];

		this.contextMenuService.showContextMenu({
			getAnchor: () => this.ltBtn,
			getActions: () => actions,
		});
	}

	private showLineweightMenu(): void {
		if (!this.editor) {
			return;
		}
		const selectedIds = this.editor.selection.get();
		const actions: IAction[] = [
			new Action('saengine.cad.lw.bylayer', 'ByLayer', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { lineweight: 'ByLayer' });
				}
				this.updateProperties();
			}),
			new Action('saengine.cad.lw.byblock', 'ByBlock', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { lineweight: 'ByBlock' });
				}
				this.updateProperties();
			}),
			new Action('saengine.cad.lw.default', 'Default', undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { lineweight: 'default' });
				}
				this.updateProperties();
			}),
			new Separator(),
			...STANDARD_LINEWEIGHTS.map(lw => new Action(`saengine.cad.lw.${lw}`, `${lw.toFixed(2)} mm`, undefined, true, async () => {
				if (selectedIds.length > 0) {
					this.editor?.properties.set(selectedIds, { lineweight: lw });
				}
				this.updateProperties();
			})),
		];

		this.contextMenuService.showContextMenu({
			getAnchor: () => this.lwBtn,
			getActions: () => actions,
		});
	}
}
