/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { Action, IAction, Separator, SubmenuAction } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { Disposable, DisposableStore, IDisposable, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { RibbonButtonSize, RibbonTabId } from './ribbonRegistry.js';

export interface IRibbonSelectOption {
	readonly id: string;
	readonly label: string;
	readonly description?: string;
	readonly disabled?: boolean;
	readonly isHeading?: boolean;
}

export interface IRibbonSelectEvent {
	readonly id: string;
	readonly index: number;
	readonly item: IRibbonSelectOption;
}

export type RibbonSelectWidth = 'compact' | 'normal' | 'wide';

export interface IRibbonSelectOptions {
	readonly id: string;
	readonly label?: string;
	readonly ariaLabel: string;
	readonly tooltip?: string;
	readonly items?: readonly IRibbonSelectOption[];
	readonly selectedId?: string;
	readonly visible?: boolean;
	readonly disabled?: boolean;
	readonly width?: RibbonSelectWidth;
}

/** Reactive model for a ribbon combo/select dropdown bound to an editor's state. */
export class RibbonSelectModel extends Disposable {

	readonly id: string;
	readonly ariaLabel: string;
	readonly width: RibbonSelectWidth;

	private _label: string;
	private _tooltip: string | undefined;
	private _items: readonly IRibbonSelectOption[] = [];
	private _selectedId: string | undefined;
	private _visible: boolean;
	private _disabled: boolean;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	private readonly _onDidSelect = this._register(new Emitter<IRibbonSelectEvent>());
	readonly onDidSelect: Event<IRibbonSelectEvent> = this._onDidSelect.event;

	constructor(options: IRibbonSelectOptions) {
		super();
		this.id = options.id;
		this.ariaLabel = options.ariaLabel;
		this.width = options.width ?? 'normal';
		this._label = options.label ?? '';
		this._tooltip = options.tooltip;
		this._visible = options.visible ?? true;
		this._disabled = options.disabled ?? false;
		if (options.items) {
			this.setItems(options.items, options.selectedId);
		}
	}

	get label(): string { return this._label; }
	get tooltip(): string | undefined { return this._tooltip; }
	get items(): readonly IRibbonSelectOption[] { return this._items; }
	get selectedId(): string | undefined { return this._selectedId; }
	get visible(): boolean { return this._visible; }
	get disabled(): boolean { return this._disabled; }

	get selectedIndex(): number {
		if (this._selectedId === undefined) {
			return -1;
		}
		return this._items.findIndex(item => item.id === this._selectedId && !item.isHeading);
	}

	get selectedItem(): IRibbonSelectOption | undefined {
		const idx = this.selectedIndex;
		return idx >= 0 ? this._items[idx] : undefined;
	}

	setItems(items: readonly IRibbonSelectOption[], selectedId?: string): void {
		this._items = items;
		if (selectedId !== undefined && items.some(item => item.id === selectedId && !item.isHeading)) {
			this._selectedId = selectedId;
		} else if (this._selectedId !== undefined && items.some(item => item.id === this._selectedId && !item.isHeading)) {
			// Keep current selection when still valid.
		} else {
			this._selectedId = items.find(item => !item.isHeading && !item.disabled)?.id ?? items.find(item => !item.isHeading)?.id;
		}
		this._onDidChange.fire();
	}

	select(idOrIndex: string | number, fireEvent = true): void {
		const index = typeof idOrIndex === 'number'
			? idOrIndex
			: this._items.findIndex(item => item.id === idOrIndex && !item.isHeading);
		const item = this._items[index];
		if (!item || item.isHeading || item.disabled) {
			return;
		}
		const changed = this._selectedId !== item.id;
		this._selectedId = item.id;
		if (changed) {
			this._onDidChange.fire();
		}
		if (fireEvent) {
			this._onDidSelect.fire({ id: item.id, index, item });
		}
	}

	setVisible(visible: boolean): void {
		if (this._visible !== visible) {
			this._visible = visible;
			this._onDidChange.fire();
		}
	}

	setDisabled(disabled: boolean): void {
		if (this._disabled !== disabled) {
			this._disabled = disabled;
			this._onDidChange.fire();
		}
	}

	setLabel(label: string): void {
		if (this._label !== label) {
			this._label = label;
			this._onDidChange.fire();
		}
	}

	setTooltip(tooltip: string | undefined): void {
		if (this._tooltip !== tooltip) {
			this._tooltip = tooltip;
			this._onDidChange.fire();
		}
	}
}

export interface IRibbonSegmentItem {
	readonly id: string;
	readonly label: string;
	readonly icon?: ThemeIcon;
	readonly tooltip?: string;
	readonly disabled?: boolean;
}

export interface IRibbonSegmentedOptions {
	readonly id: string;
	readonly ariaLabel: string;
	readonly items?: readonly IRibbonSegmentItem[];
	readonly selectedId?: string;
	readonly visible?: boolean;
	readonly disabled?: boolean;
}

/** Reactive model for an exclusive segmented view/tool switch group in the ribbon. */
export class RibbonSegmentedModel extends Disposable {

	readonly id: string;
	readonly ariaLabel: string;

	private _items: readonly IRibbonSegmentItem[] = [];
	private _selectedId: string | undefined;
	private _visible: boolean;
	private _disabled: boolean;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	private readonly _onDidSelect = this._register(new Emitter<string>());
	readonly onDidSelect: Event<string> = this._onDidSelect.event;

	constructor(options: IRibbonSegmentedOptions) {
		super();
		this.id = options.id;
		this.ariaLabel = options.ariaLabel;
		this._visible = options.visible ?? true;
		this._disabled = options.disabled ?? false;
		if (options.items) {
			this.setItems(options.items, options.selectedId);
		}
	}

	get items(): readonly IRibbonSegmentItem[] { return this._items; }
	get selectedId(): string | undefined { return this._selectedId; }
	get visible(): boolean { return this._visible; }
	get disabled(): boolean { return this._disabled; }

	setItems(items: readonly IRibbonSegmentItem[], selectedId?: string): void {
		this._items = items;
		if (selectedId !== undefined) {
			this._selectedId = items.some(item => item.id === selectedId) ? selectedId : undefined;
		} else if (this._selectedId !== undefined && !items.some(item => item.id === this._selectedId)) {
			this._selectedId = items[0]?.id;
		}
		this._onDidChange.fire();
	}

	select(id: string | undefined, fireEvent = true): void {
		if (id !== undefined) {
			const item = this._items.find(candidate => candidate.id === id);
			if (!item || item.disabled || this._disabled) {
				return;
			}
		}
		const changed = this._selectedId !== id;
		this._selectedId = id;
		if (changed) {
			this._onDidChange.fire();
		}
		if (fireEvent && id !== undefined) {
			this._onDidSelect.fire(id);
		}
	}

	setVisible(visible: boolean): void {
		if (this._visible !== visible) {
			this._visible = visible;
			this._onDidChange.fire();
		}
	}

	setDisabled(disabled: boolean): void {
		if (this._disabled !== disabled) {
			this._disabled = disabled;
			this._onDidChange.fire();
		}
	}

	setItemDisabled(id: string, disabled: boolean): void {
		let changed = false;
		this._items = this._items.map(item => {
			if (item.id === id && Boolean(item.disabled) !== disabled) {
				changed = true;
				return { ...item, disabled };
			}
			return item;
		});
		if (changed) {
			this._onDidChange.fire();
		}
	}

	addDisposable<T extends IDisposable>(disposable: T): T {
		return this._register(disposable);
	}
}

export interface IRibbonToggleOptions {
	readonly id: string;
	readonly label: string;
	readonly icon?: ThemeIcon;
	readonly tooltip?: string;
	readonly checked?: boolean;
	readonly disabled?: boolean;
	readonly visible?: boolean;
	readonly size?: RibbonButtonSize;
}

/** Reactive model for a ribbon toggle button with checked state. */
export class RibbonToggleModel extends Disposable {

	readonly id: string;
	readonly size: RibbonButtonSize;

	private _label: string;
	private _icon: ThemeIcon | undefined;
	private _tooltip: string | undefined;
	private _checked: boolean;
	private _disabled: boolean;
	private _visible: boolean;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	private readonly _onDidToggle = this._register(new Emitter<boolean>());
	readonly onDidToggle: Event<boolean> = this._onDidToggle.event;

	constructor(options: IRibbonToggleOptions) {
		super();
		this.id = options.id;
		this.size = options.size ?? 'small';
		this._label = options.label;
		this._icon = options.icon;
		this._tooltip = options.tooltip;
		this._checked = options.checked ?? false;
		this._disabled = options.disabled ?? false;
		this._visible = options.visible ?? true;
	}

	get label(): string { return this._label; }
	get icon(): ThemeIcon | undefined { return this._icon; }
	get tooltip(): string | undefined { return this._tooltip; }
	get checked(): boolean { return this._checked; }
	get disabled(): boolean { return this._disabled; }
	get visible(): boolean { return this._visible; }

	setChecked(checked: boolean, fireEvent = true): void {
		if (this._disabled && fireEvent) {
			return;
		}
		const changed = this._checked !== checked;
		this._checked = checked;
		if (changed) {
			this._onDidChange.fire();
		}
		if (fireEvent) {
			this._onDidToggle.fire(checked);
		}
	}

	setVisible(visible: boolean): void {
		if (this._visible !== visible) {
			this._visible = visible;
			this._onDidChange.fire();
		}
	}

	setDisabled(disabled: boolean): void {
		if (this._disabled !== disabled) {
			this._disabled = disabled;
			this._onDidChange.fire();
		}
	}

	setLabel(label: string): void {
		if (this._label !== label) {
			this._label = label;
			this._onDidChange.fire();
		}
	}

	setIcon(icon: ThemeIcon | undefined): void {
		if (this._icon?.id !== icon?.id) {
			this._icon = icon;
			this._onDidChange.fire();
		}
	}

	setTooltip(tooltip: string | undefined): void {
		if (this._tooltip !== tooltip) {
			this._tooltip = tooltip;
			this._onDidChange.fire();
		}
	}
}

export interface IRibbonSliderOptions {
	readonly id: string;
	readonly label: string;
	readonly ariaLabel: string;
	readonly tooltip?: string;
	readonly min: number;
	readonly max: number;
	readonly step?: number;
	readonly value: number;
	readonly valueText?: string;
	readonly resetValue?: number;
	readonly visible?: boolean;
	readonly disabled?: boolean;
}

/** Reactive model for a ribbon range slider (e.g. FEM scale or time-history scrubber). */
export class RibbonSliderModel extends Disposable {

	readonly id: string;
	readonly resetValue: number | undefined;

	private _label: string;
	private _ariaLabel: string;
	private _tooltip: string | undefined;
	private _min: number;
	private _max: number;
	private _step: number;
	private _value: number;
	private _valueText: string;
	private _visible: boolean;
	private _disabled: boolean;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	private readonly _onDidChangeValue = this._register(new Emitter<number>());
	readonly onDidChangeValue: Event<number> = this._onDidChangeValue.event;

	constructor(options: IRibbonSliderOptions) {
		super();
		this.id = options.id;
		this.resetValue = options.resetValue;
		this._label = options.label;
		this._ariaLabel = options.ariaLabel;
		this._tooltip = options.tooltip;
		this._min = options.min;
		this._max = options.max;
		this._step = options.step ?? 1;
		this._value = options.value;
		this._valueText = options.valueText ?? '';
		this._visible = options.visible ?? true;
		this._disabled = options.disabled ?? false;
	}

	get label(): string { return this._label; }
	get ariaLabel(): string { return this._ariaLabel; }
	get tooltip(): string | undefined { return this._tooltip; }
	get min(): number { return this._min; }
	get max(): number { return this._max; }
	get step(): number { return this._step; }
	get value(): number { return this._value; }
	get valueText(): string { return this._valueText; }
	get visible(): boolean { return this._visible; }
	get disabled(): boolean { return this._disabled; }

	setRange(min: number, max: number, step?: number): void {
		const nextStep = step ?? this._step;
		if (this._min !== min || this._max !== max || this._step !== nextStep) {
			this._min = min;
			this._max = max;
			this._step = nextStep;
			this._onDidChange.fire();
		}
	}

	setValue(value: number, fireEvent = true): void {
		const clamped = Math.max(this._min, Math.min(this._max, value));
		const changed = this._value !== clamped;
		this._value = clamped;
		if (changed) {
			this._onDidChange.fire();
		}
		if (fireEvent) {
			this._onDidChangeValue.fire(clamped);
		}
	}

	setValueText(text: string): void {
		if (this._valueText !== text) {
			this._valueText = text;
			this._onDidChange.fire();
		}
	}

	setLabel(label: string): void {
		if (this._label !== label) {
			this._label = label;
			this._onDidChange.fire();
		}
	}

	setAriaLabel(ariaLabel: string): void {
		if (this._ariaLabel !== ariaLabel) {
			this._ariaLabel = ariaLabel;
			this._onDidChange.fire();
		}
	}

	setTooltip(tooltip: string | undefined): void {
		if (this._tooltip !== tooltip) {
			this._tooltip = tooltip;
			this._onDidChange.fire();
		}
	}

	setVisible(visible: boolean): void {
		if (this._visible !== visible) {
			this._visible = visible;
			this._onDidChange.fire();
		}
	}

	setDisabled(disabled: boolean): void {
		if (this._disabled !== disabled) {
			this._disabled = disabled;
			this._onDidChange.fire();
		}
	}
}

export interface IRibbonElementOptions {
	readonly id: string;
	readonly element: HTMLElement;
	readonly visible?: boolean;
	readonly collapsedActions?: (store: DisposableStore) => readonly IAction[];
}

/** Hosts a live editor-owned inline element (such as an `InputBox` + apply button) inside the ribbon. */
export class RibbonElementControl extends Disposable {

	readonly id: string;
	readonly element: HTMLElement;
	readonly collapsedActions: ((store: DisposableStore) => readonly IAction[]) | undefined;
	private _visible: boolean;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	constructor(options: IRibbonElementOptions) {
		super();
		this.id = options.id;
		this.element = options.element;
		this.collapsedActions = options.collapsedActions;
		this._visible = options.visible ?? true;
	}

	get visible(): boolean { return this._visible; }

	setVisible(visible: boolean): void {
		if (this._visible !== visible) {
			this._visible = visible;
			this._onDidChange.fire();
		}
	}
}

export interface IRibbonInlineRowOptions {
	readonly id: string;
	readonly controls: readonly RibbonControl[];
	readonly visible?: boolean;
}

/** Places multiple compact ribbon controls side-by-side on a single 22px row. */
export class RibbonInlineRowControl extends Disposable {

	readonly id: string;
	readonly controls: readonly RibbonControl[];
	private _visible: boolean;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	constructor(options: IRibbonInlineRowOptions) {
		super();
		this.id = options.id;
		this.controls = options.controls;
		this._visible = options.visible ?? true;
		for (const child of options.controls) {
			this._register(child.onDidChange(() => this._onDidChange.fire()));
		}
	}

	get visible(): boolean { return this._visible; }

	setVisible(visible: boolean): void {
		if (this._visible !== visible) {
			this._visible = visible;
			this._onDidChange.fire();
		}
	}
}

export type RibbonControl =
	| RibbonSelectModel
	| RibbonSegmentedModel
	| RibbonToggleModel
	| RibbonSliderModel
	| RibbonElementControl
	| RibbonInlineRowControl;

export interface IRibbonPillDescriptor {
	readonly id: string;
	readonly text: string;
	readonly severity?: 'warn' | 'fail';
	readonly icon?: ThemeIcon;
	readonly title?: string;
	readonly run?: () => void;
}

export interface IRibbonHelpDescriptor {
	readonly text: string;
	readonly chapter?: string;
	readonly openManualCommand: string;
}

export interface IEditorRibbonTabGroup {
	readonly id: string;
	readonly tabId: RibbonTabId;
	readonly group: string;
	readonly label: string;
	readonly collapsePriority?: number;
	readonly icon?: ThemeIcon;
	readonly controls: readonly RibbonControl[];
	readonly isVisible?: () => boolean;
}

export interface IEditorRibbonFrame {
	readonly id: string;
	readonly element: HTMLElement;
	readonly title: string;
	readonly viewControls: readonly RibbonControl[];
	readonly toolControls: readonly RibbonControl[];
	readonly primaryActions: readonly IAction[];
	readonly secondaryActions: readonly IAction[];
	readonly pills: readonly IRibbonPillDescriptor[];
	readonly help: IRibbonHelpDescriptor | undefined;
	readonly tabGroups: readonly IEditorRibbonTabGroup[];
}

export const ISaengineRibbonToolbarService = createDecorator<ISaengineRibbonToolbarService>('saengineRibbonToolbarService');

/** Collects toolbar models published by `EditorFrame` instances so the active editor's toolbar renders in the ribbon. */
export interface ISaengineRibbonToolbarService {
	readonly _serviceBrand: undefined;
	readonly frames: readonly IEditorRibbonFrame[];
	readonly onDidChangeFrames: Event<void>;
	readonly onDidChangeToolbar: Event<IEditorRibbonFrame>;
	register(frame: IEditorRibbonFrame): IDisposable;
	notifyChanged(frame: IEditorRibbonFrame): void;
}

class SaengineRibbonToolbarService extends Disposable implements ISaengineRibbonToolbarService {

	declare readonly _serviceBrand: undefined;

	private readonly _frames: IEditorRibbonFrame[] = [];

	private readonly _onDidChangeFrames = this._register(new Emitter<void>());
	readonly onDidChangeFrames: Event<void> = this._onDidChangeFrames.event;

	private readonly _onDidChangeToolbar = this._register(new Emitter<IEditorRibbonFrame>());
	readonly onDidChangeToolbar: Event<IEditorRibbonFrame> = this._onDidChangeToolbar.event;

	get frames(): readonly IEditorRibbonFrame[] {
		return this._frames;
	}

	register(frame: IEditorRibbonFrame): IDisposable {
		this._frames.push(frame);
		this._onDidChangeFrames.fire();
		return toDisposable(() => {
			const idx = this._frames.indexOf(frame);
			if (idx >= 0) {
				this._frames.splice(idx, 1);
				this._onDidChangeFrames.fire();
			}
		});
	}

	notifyChanged(frame: IEditorRibbonFrame): void {
		this._onDidChangeToolbar.fire(frame);
	}
}

registerSingleton(ISaengineRibbonToolbarService, SaengineRibbonToolbarService, InstantiationType.Delayed);

export interface IRibbonControlServices {
	readonly hoverService: IHoverService;
	readonly contextMenuService: IContextMenuService;
	readonly commandService: ICommandService;
}

/** Returns true when at least one control in `controls` is visible. */
export function hasVisibleControls(controls: readonly RibbonControl[]): boolean {
	for (const control of controls) {
		if (!control.visible) {
			continue;
		}
		if (control instanceof RibbonInlineRowControl) {
			if (hasVisibleControls(control.controls)) {
				return true;
			}
			continue;
		}
		return true;
	}
	return false;
}

/** Computes a compact signature reflecting only the visible/hidden structure of `controls`. */
export function controlVisibilitySignature(controls: readonly RibbonControl[]): string {
	return controls.map(control => {
		if (control instanceof RibbonInlineRowControl) {
			return `${control.visible ? '1' : '0'}(${controlVisibilitySignature(control.controls)})`;
		}
		return control.visible ? '1' : '0';
	}).join(',');
}

function cleanSeparators(actions: readonly IAction[]): readonly IAction[] {
	const cleaned: IAction[] = [];
	for (const action of actions) {
		if (action instanceof Separator) {
			if (cleaned.length > 0 && !(cleaned[cleaned.length - 1] instanceof Separator)) {
				cleaned.push(action);
			}
		} else {
			cleaned.push(action);
		}
	}
	while (cleaned.length > 0 && cleaned[cleaned.length - 1] instanceof Separator) {
		cleaned.pop();
	}
	return cleaned;
}

/**
 * Filters out editor toolbar actions whose command IDs are already registered on the active
 * editor's contextual ribbon tabs, cleaning up redundant separators.
 */
export function dedupeEditorFrameActions(
	primary: readonly IAction[],
	secondary: readonly IAction[],
	existingCommandIds: ReadonlySet<string>,
): { readonly primary: readonly IAction[]; readonly secondary: readonly IAction[] } {
	const keep = (action: IAction) => action instanceof Separator || !existingCommandIds.has(action.id);
	return {
		primary: cleanSeparators(primary.filter(keep)),
		secondary: cleanSeparators(secondary.filter(keep)),
	};
}

/** Renders a `RibbonSelectModel` as a compact Office-style labeled dropdown button. */
export function renderRibbonSelect(
	container: HTMLElement,
	model: RibbonSelectModel,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const row = append(container, $('.sa-ribbon-ctrl.sa-ribbon-select-row'));
	const labelEl = append(row, $('span.sa-ribbon-ctrl-label'));
	const button = append(row, $<HTMLButtonElement>(`button.sa-ribbon-btn.sa-ribbon-btn-small.sa-ribbon-select.sa-ribbon-select-${model.width}`));
	button.type = 'button';
	button.setAttribute('role', 'combobox');
	button.setAttribute('aria-haspopup', 'listbox');
	button.setAttribute('aria-expanded', 'false');
	const textEl = append(button, $('span.sa-ribbon-select-text'));
	append(button, $(`span.sa-ribbon-caret${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');
	const hover = store.add(new MutableDisposable<IDisposable>());

	const sync = () => {
		row.classList.toggle('sa-ribbon-ctrl-hidden', !model.visible);
		labelEl.textContent = model.label;
		labelEl.classList.toggle('sa-ribbon-ctrl-hidden', !model.label);
		const selected = model.selectedItem;
		textEl.textContent = selected?.label ?? '';
		const noEnabledOptions = !model.items.some(item => !item.isHeading && !item.disabled);
		const disabled = model.disabled || noEnabledOptions;
		button.setAttribute('aria-disabled', String(disabled));
		button.classList.toggle('sa-ribbon-disabled', disabled);
		button.setAttribute('aria-label', selected ? `${model.ariaLabel}: ${selected.label}` : model.ariaLabel);
		const tip = model.tooltip || selected?.description || (selected ? `${model.ariaLabel}: ${selected.label}` : model.ariaLabel);
		hover.value = services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip);
	};

	const openDropdown = () => {
		if (button.getAttribute('aria-disabled') === 'true') {
			return;
		}
		const menuStore = new DisposableStore();
		const actions: IAction[] = [];
		model.items.forEach((option, index) => {
			if (option.isHeading) {
				if (actions.length > 0) {
					actions.push(menuStore.add(new Separator()));
				}
				const heading = menuStore.add(new Action(`${model.id}.heading.${index}`, option.label, undefined, false));
				actions.push(heading);
				return;
			}
			const itemAction = menuStore.add(new Action(
				`${model.id}.opt.${option.id}`,
				option.label,
				undefined,
				!option.disabled,
				async () => {
					model.select(option.id, true);
				},
			));
			if (option.description) {
				itemAction.tooltip = option.description;
			}
			if (option.id === model.selectedId) {
				itemAction.checked = true;
			}
			actions.push(itemAction);
		});
		if (!actions.length) {
			menuStore.dispose();
			return;
		}
		button.setAttribute('aria-expanded', 'true');
		services.contextMenuService.showContextMenu({
			getAnchor: () => button,
			getActions: () => actions,
			onHide: () => {
				button.setAttribute('aria-expanded', 'false');
				menuStore.dispose();
			},
		});
	};

	store.add(addDisposableListener(button, EventType.CLICK, () => openDropdown()));
	store.add(addDisposableListener(button, EventType.KEY_DOWN, e => {
		const event = new StandardKeyboardEvent(e);
		if (event.equals(KeyCode.DownArrow) || event.equals(KeyCode.Enter) || event.equals(KeyCode.Space)) {
			event.preventDefault();
			event.stopPropagation();
			openDropdown();
		}
	}));
	store.add(model.onDidChange(sync));
	store.add(toDisposable(() => row.remove()));
	sync();
	return store;
}

/** Renders a `RibbonSegmentedModel` as an exclusive radiogroup of compact buttons. */
export function renderRibbonSegmented(
	container: HTMLElement,
	model: RibbonSegmentedModel,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const group = append(container, $('.sa-ribbon-ctrl.sa-ribbon-segmented', {
		role: 'radiogroup',
		'aria-label': model.ariaLabel,
	}));
	const itemStore = store.add(new DisposableStore());
	let renderedIdsKey = '';
	const buttons = new Map<string, {
		readonly button: HTMLButtonElement;
		readonly labelEl: HTMLElement;
		readonly hover: MutableDisposable<IDisposable>;
	}>();

	const rebuildItems = () => {
		itemStore.clear();
		clearNode(group);
		buttons.clear();
		renderedIdsKey = model.items.map(item => `${item.id}:${item.icon?.id ?? ''}`).join('|');

		for (const item of model.items) {
			const button = append(group, $<HTMLButtonElement>('button.sa-ribbon-seg-btn', {
				type: 'button',
				role: 'radio',
			}));
			if (item.icon) {
				append(button, $(`span.sa-ribbon-seg-icon${ThemeIcon.asCSSSelector(item.icon)}`)).setAttribute('aria-hidden', 'true');
			}
			const labelEl = append(button, $('span.sa-ribbon-seg-label', undefined, item.label));
			const hover = itemStore.add(new MutableDisposable<IDisposable>());
			itemStore.add(addDisposableListener(button, EventType.CLICK, () => {
				if (button.getAttribute('aria-disabled') === 'true') {
					return;
				}
				model.select(item.id, true);
			}));
			buttons.set(item.id, { button, labelEl, hover });
		}
	};

	const sync = () => {
		group.classList.toggle('sa-ribbon-ctrl-hidden', !model.visible);
		const idsKey = model.items.map(item => `${item.id}:${item.icon?.id ?? ''}`).join('|');
		if (idsKey !== renderedIdsKey) {
			rebuildItems();
		}
		for (const item of model.items) {
			const entry = buttons.get(item.id);
			if (!entry) {
				continue;
			}
			const selected = item.id === model.selectedId;
			const disabled = model.disabled || !!item.disabled;
			entry.labelEl.textContent = item.label;
			entry.button.setAttribute('aria-checked', String(selected));
			entry.button.classList.toggle('active', selected);
			entry.button.setAttribute('aria-disabled', String(disabled));
			entry.button.classList.toggle('sa-ribbon-disabled', disabled);
			const tip = item.tooltip || item.label;
			entry.button.setAttribute('aria-label', item.label || tip);
			entry.hover.value = services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), entry.button, tip);
		}
	};

	store.add(model.onDidChange(sync));
	store.add(toDisposable(() => group.remove()));
	sync();
	return store;
}

/** Renders a `RibbonToggleModel` as a pressable large or small ribbon button. */
export function renderRibbonToggle(
	container: HTMLElement,
	model: RibbonToggleModel,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const button = append(container, $<HTMLButtonElement>(`button.sa-ribbon-ctrl.sa-ribbon-btn.sa-ribbon-btn-${model.size}.sa-ribbon-toggle`));
	button.type = 'button';
	const iconEl = append(button, $('span.sa-ribbon-icon'));
	iconEl.setAttribute('aria-hidden', 'true');
	const labelEl = append(button, $('span.sa-ribbon-btn-label'));
	const hover = store.add(new MutableDisposable<IDisposable>());

	const sync = () => {
		button.classList.toggle('sa-ribbon-ctrl-hidden', !model.visible);
		const icon = model.icon ?? Codicon.circleSmallFilled;
		iconEl.className = `sa-ribbon-icon ${ThemeIcon.asClassName(icon)}`;
		labelEl.textContent = model.label;
		button.setAttribute('aria-pressed', String(model.checked));
		button.setAttribute('aria-disabled', String(model.disabled));
		button.classList.toggle('sa-ribbon-disabled', model.disabled);
		const tip = model.tooltip || model.label;
		button.setAttribute('aria-label', model.label || tip);
		hover.value = services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip);
	};

	store.add(addDisposableListener(button, EventType.CLICK, () => {
		if (button.getAttribute('aria-disabled') === 'true') {
			return;
		}
		model.setChecked(!model.checked, true);
	}));
	store.add(model.onDidChange(sync));
	store.add(toDisposable(() => button.remove()));
	sync();
	return store;
}

/** Renders a `RibbonSliderModel` with caption, native range input, and value readout. */
export function renderRibbonSlider(
	container: HTMLElement,
	model: RibbonSliderModel,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const row = append(container, $('.sa-ribbon-ctrl.sa-ribbon-slider-row'));
	const labelEl = append(row, $('span.sa-ribbon-ctrl-label'));
	const input = append(row, $<HTMLInputElement>('input.sa-ribbon-slider', { type: 'range' }));
	const valueEl = append(row, $('span.sa-ribbon-slider-value'));
	const hover = store.add(new MutableDisposable<IDisposable>());

	const sync = () => {
		row.classList.toggle('sa-ribbon-ctrl-hidden', !model.visible);
		labelEl.textContent = model.label;
		labelEl.classList.toggle('sa-ribbon-ctrl-hidden', !model.label);
		input.min = String(model.min);
		input.max = String(model.max);
		input.step = String(model.step);
		input.value = String(model.value);
		input.disabled = model.disabled;
		input.setAttribute('aria-label', model.ariaLabel);
		valueEl.textContent = model.valueText;
		valueEl.classList.toggle('sa-ribbon-ctrl-hidden', !model.valueText);
		const tip = model.tooltip || (model.valueText ? `${model.ariaLabel}: ${model.valueText}` : model.ariaLabel);
		hover.value = services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), row, tip);
	};

	store.add(addDisposableListener(input, EventType.INPUT, () => {
		model.setValue(Number(input.value), true);
	}));
	if (model.resetValue !== undefined) {
		const resetValue = model.resetValue;
		store.add(addDisposableListener(input, EventType.DBLCLICK, () => {
			model.setValue(resetValue, true);
		}));
	}
	store.add(model.onDidChange(sync));
	store.add(toDisposable(() => row.remove()));
	sync();
	return store;
}

/** Renders a `RibbonElementControl` by attaching its live DOM node and detaching it cleanly on dispose. */
export function renderRibbonElement(container: HTMLElement, model: RibbonElementControl): IDisposable {
	const store = new DisposableStore();
	const host = append(container, $('.sa-ribbon-ctrl.sa-ribbon-element-host'));
	host.appendChild(model.element);
	const sync = () => host.classList.toggle('sa-ribbon-ctrl-hidden', !model.visible);
	store.add(model.onDidChange(sync));
	store.add(toDisposable(() => {
		if (model.element.parentElement === host) {
			model.element.remove();
		}
		host.remove();
	}));
	sync();
	return store;
}

/** Renders a `RibbonInlineRowControl` placing child controls horizontally on one row. */
export function renderRibbonInlineRow(
	container: HTMLElement,
	model: RibbonInlineRowControl,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const row = append(container, $('.sa-ribbon-ctrl.sa-ribbon-inline-row'));
	for (const child of model.controls) {
		store.add(renderRibbonControl(row, child, services));
	}
	const sync = () => {
		row.classList.toggle('sa-ribbon-ctrl-hidden', !model.visible || !hasVisibleControls(model.controls));
	};
	store.add(model.onDidChange(sync));
	store.add(toDisposable(() => row.remove()));
	sync();
	return store;
}

/** Dispatches rendering for any `RibbonControl`. */
export function renderRibbonControl(
	container: HTMLElement,
	control: RibbonControl,
	services: IRibbonControlServices,
): IDisposable {
	if (control instanceof RibbonSelectModel) {
		return renderRibbonSelect(container, control, services);
	}
	if (control instanceof RibbonSegmentedModel) {
		return renderRibbonSegmented(container, control, services);
	}
	if (control instanceof RibbonToggleModel) {
		return renderRibbonToggle(container, control, services);
	}
	if (control instanceof RibbonSliderModel) {
		return renderRibbonSlider(container, control, services);
	}
	if (control instanceof RibbonElementControl) {
		return renderRibbonElement(container, control);
	}
	return renderRibbonInlineRow(container, control, services);
}

/** Packs `controls` into standalone large columns and stacks of up to 3 visible compact controls. */
export function renderRibbonControlStack(
	container: HTMLElement,
	controls: readonly RibbonControl[],
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	let stackEl: HTMLElement | undefined;
	let stackCount = 0;

	const flush = () => {
		stackEl = undefined;
		stackCount = 0;
	};

	for (const control of controls) {
		if (!control.visible) {
			continue;
		}
		if (control instanceof RibbonInlineRowControl && !hasVisibleControls(control.controls)) {
			continue;
		}
		if (control instanceof RibbonToggleModel && control.size === 'large') {
			flush();
			store.add(renderRibbonToggle(container, control, services));
			continue;
		}
		if (!stackEl || stackCount >= 3) {
			stackEl = append(container, $('.sa-ribbon-stack'));
			stackCount = 0;
		}
		store.add(renderRibbonControl(stackEl, control, services));
		stackCount++;
	}

	return store;
}

/** Renders the Help (?) button for an active editor, matching `EditorFrame.setHelp` hover + manual link. */
export function renderRibbonHelpButton(
	container: HTMLElement,
	help: IRibbonHelpDescriptor,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const label = localize('ribbon.help.aria', "About This Editor");
	const button = append(container, $<HTMLButtonElement>('button.sa-ribbon-btn.sa-ribbon-btn-large.sa-ribbon-help-btn'));
	button.type = 'button';
	button.setAttribute('aria-label', label);
	append(button, $(`span.sa-ribbon-icon${ThemeIcon.asCSSSelector(Codicon.question)}`)).setAttribute('aria-hidden', 'true');
	append(button, $('span.sa-ribbon-btn-label', undefined, localize('ribbon.help.label', "Help")));

	const content = new MarkdownString(undefined, { isTrusted: { enabledCommands: [help.openManualCommand] } });
	content.appendText(help.text);
	if (help.chapter) {
		content.appendMarkdown(`\n\n[${localize('ribbon.help.learnMore', "Learn more in the user manual")}](command:${help.openManualCommand}?${encodeURIComponent(JSON.stringify([help.chapter]))})`);
	}
	const hover = store.add(services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, {
		markdown: content,
		markdownNotSupportedFallback: help.text,
	}));

	store.add(addDisposableListener(button, EventType.CLICK, () => {
		if (help.chapter) {
			button.classList.add('loading');
			button.setAttribute('aria-busy', 'true');
			void services.commandService.executeCommand(help.openManualCommand, help.chapter).finally(() => {
				button.classList.remove('loading');
				button.removeAttribute('aria-busy');
			});
		} else {
			hover.show(true);
		}
	}));
	store.add(toDisposable(() => button.remove()));
	return store;
}

function codiconClassFromActionClass(actionClass: string | undefined): ThemeIcon {
	if (!actionClass) {
		return Codicon.symbolMisc;
	}
	const match = /\bcodicon-([a-z0-9-]+)\b/i.exec(actionClass);
	if (match) {
		return ThemeIcon.fromId(match[1]);
	}
	return Codicon.symbolMisc;
}

/** Renders an editor `IAction` (or `SubmenuAction`) in the ribbon and stays synced with `Action.onDidChange`. */
export function renderRibbonActionButton(
	container: HTMLElement,
	action: IAction,
	size: RibbonButtonSize,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const isSubmenu = action instanceof SubmenuAction;
	const button = append(container, $<HTMLButtonElement>(
		isSubmenu
			? `button.sa-ribbon-btn.sa-ribbon-btn-${size}.sa-ribbon-dropdown`
			: `button.sa-ribbon-btn.sa-ribbon-btn-${size}`
	));
	button.type = 'button';
	if (isSubmenu) {
		button.setAttribute('aria-haspopup', 'menu');
		button.setAttribute('aria-expanded', 'false');
	}
	const iconEl = append(button, $('span.sa-ribbon-icon'));
	iconEl.setAttribute('aria-hidden', 'true');
	const labelEl = append(button, $('span.sa-ribbon-btn-label'));
	if (isSubmenu) {
		append(button, $(`span.sa-ribbon-caret${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');
	}
	const hover = store.add(new MutableDisposable<IDisposable>());

	const sync = () => {
		const icon = codiconClassFromActionClass(action.class);
		iconEl.className = `sa-ribbon-icon ${ThemeIcon.asClassName(icon)}`;
		labelEl.textContent = action.label || action.tooltip;
		if (action.checked !== undefined) {
			button.setAttribute('aria-pressed', String(action.checked));
		} else {
			button.removeAttribute('aria-pressed');
		}
		button.setAttribute('aria-disabled', String(!action.enabled));
		button.classList.toggle('sa-ribbon-disabled', !action.enabled);
		const tip = action.tooltip || action.label;
		button.setAttribute('aria-label', tip || action.label);
		hover.value = services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip);
	};

	if (action instanceof Action) {
		store.add(action.onDidChange(() => sync()));
	}

	store.add(addDisposableListener(button, EventType.CLICK, () => {
		if (button.getAttribute('aria-disabled') === 'true') {
			return;
		}
		if (action instanceof SubmenuAction) {
			button.setAttribute('aria-expanded', 'true');
			services.contextMenuService.showContextMenu({
				getAnchor: () => button,
				getActions: () => action.actions,
				onHide: () => button.setAttribute('aria-expanded', 'false'),
			});
		} else {
			void action.run();
		}
	}));
	store.add(toDisposable(() => button.remove()));
	sync();
	return store;
}

/** Renders an active editor status pill (e.g. "Out of date") in the ribbon. */
export function renderRibbonPill(
	container: HTMLElement,
	pill: IRibbonPillDescriptor,
	services: IRibbonControlServices,
): IDisposable {
	const store = new DisposableStore();
	const element = append(container, $<HTMLElement>(pill.run ? 'button.sa-ribbon-pill' : 'span.sa-ribbon-pill'));
	if (element.tagName === 'BUTTON') {
		(element as HTMLButtonElement).type = 'button';
	}
	if (pill.severity) {
		element.classList.add(pill.severity);
	}
	if (pill.icon) {
		append(element, $(ThemeIcon.asCSSSelector(pill.icon))).setAttribute('aria-hidden', 'true');
	}
	append(element, $('span', undefined, pill.text));
	if (pill.title) {
		store.add(services.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), element, pill.title));
	}
	if (pill.run) {
		const run = pill.run;
		store.add(addDisposableListener(element, EventType.CLICK, () => run()));
	}
	store.add(toDisposable(() => element.remove()));
	return store;
}

/** Converts visible `RibbonControl`s into menu actions for narrow-width collapsed group dropdowns. */
export function collectControlCollapsedActions(controls: readonly RibbonControl[], store: DisposableStore): readonly IAction[] {
	const out: IAction[] = [];
	for (const control of controls) {
		if (!control.visible) {
			continue;
		}
		if (control instanceof RibbonSelectModel) {
			const children: IAction[] = [];
			control.items.forEach((opt, index) => {
				if (opt.isHeading) {
					if (children.length > 0) {
						children.push(store.add(new Separator()));
					}
					children.push(store.add(new Action(`${control.id}.h.${index}`, opt.label, undefined, false)));
					return;
				}
				const act = store.add(new Action(`${control.id}.o.${opt.id}`, opt.label, undefined, !opt.disabled && !control.disabled, async () => {
					control.select(opt.id, true);
				}));
				if (opt.id === control.selectedId) {
					act.checked = true;
				}
				children.push(act);
			});
			const subTitle = control.label ? `${control.label}: ${control.selectedItem?.label ?? ''}` : (control.selectedItem?.label || control.ariaLabel);
			out.push(store.add(new SubmenuAction(control.id, subTitle, children)));
		} else if (control instanceof RibbonSegmentedModel) {
			const children: IAction[] = control.items.map(item => {
				const act = store.add(new Action(`${control.id}.s.${item.id}`, item.label, item.icon ? ThemeIcon.asClassName(item.icon) : undefined, !control.disabled && !item.disabled, async () => {
					control.select(item.id, true);
				}));
				if (item.id === control.selectedId) {
					act.checked = true;
				}
				return act;
			});
			out.push(store.add(new SubmenuAction(control.id, control.ariaLabel, children)));
		} else if (control instanceof RibbonToggleModel) {
			const act = store.add(new Action(control.id, control.label, control.icon ? ThemeIcon.asClassName(control.icon) : undefined, !control.disabled, async () => {
				control.setChecked(!control.checked, true);
			}));
			act.checked = control.checked;
			out.push(act);
		} else if (control instanceof RibbonSliderModel) {
			const children: IAction[] = [
				store.add(new Action(`${control.id}.dec`, localize('ribbon.slider.dec', "Decrease {0}", control.label), undefined, !control.disabled && control.value > control.min, async () => {
					control.setValue(control.value - control.step, true);
				})),
				...(control.resetValue !== undefined ? [store.add(new Action(`${control.id}.reset`, localize('ribbon.slider.reset', "Reset {0}", control.label), undefined, !control.disabled, async () => {
					control.setValue(control.resetValue!, true);
				}))] : []),
				store.add(new Action(`${control.id}.inc`, localize('ribbon.slider.inc', "Increase {0}", control.label), undefined, !control.disabled && control.value < control.max, async () => {
					control.setValue(control.value + control.step, true);
				})),
			];
			const title = control.valueText ? `${control.label}: ${control.valueText}` : control.label;
			out.push(store.add(new SubmenuAction(control.id, title, children)));
		} else if (control instanceof RibbonElementControl) {
			if (control.collapsedActions) {
				out.push(...control.collapsedActions(store));
			}
		} else if (control instanceof RibbonInlineRowControl) {
			out.push(...collectControlCollapsedActions(control.controls, store));
		}
	}
	return out;
}
